"""
app/api/orchestrator.py

The ONE entry point that takes a `SearchRequest` (semantic query/queries + boolean
rules + filter values + pagination -- `app/api/request.py`), runs 
filters to narrow candidates, runs search/ranking within
that narrowed set, and returns a paginated, standardized response.

    SearchRequest
         |
         v
    [1] FILTER    (app.core.filtering)
         |          -- narrows the full corpus to a candidate set, one
         |             field at a time, AND across fields.
         v
    [2] SEARCH     (app.core.search.semantic / .lexical)
         |          -- runs semantic and/or lexical retrieval, SCOPED TO
         |             the candidate set from [1] (never the whole
         |             corpus) -- this is the actual integration seam:
         |             filtering narrows WHICH documents search is even
         |             allowed to return, per source doc §3 ("filters
         |             narrow the candidate set, search ranks within
         |             it").
         v
    [3] RANK       (app.core.search.ranking)
         |          -- merges semantic + lexical hits into one ordered list.
         v
    [4] HYDRATE     -- attaches each surviving hit's full metadata (see
         |             `_hydrate_metadata`'s docstring for why this step
         |             exists and lives here, not in retrieval).
         v
    [5] PAGINATE   (app.core.search.pagination)
         |          -- slices the ranked, hydrated list into one page.
         v
    SearchResultPage

Every stage is wrapped in `app.api.observability.log_stage` (deliverable
3: "basic structured logging around each stage"), and every place a
lower-level exception can surface is caught and re-raised as one of the
two `app.api.errors` types (deliverable 3: "consistent error types"), so
nothing calling `SearchEngine.search()` ever needs to know about
`FilterError`, `ConfigLoadError`, or a bare `ValueError` from
`paginate()`/`semantic_search()` -- only `BadConfigError`/`BadQueryError`.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

from app.api.errors import BadConfigError, BadQueryError
from app.api.observability import log_no_results, log_stage
from app.api.request import SearchRequest
from app.core.config.loader import ConfigLoadError
from app.core.config.models import UseCaseConfig
from app.core.embeddings.provider import EmbeddingProvider, TextEmbedder
from app.core.filtering import CustomFilterMap, Filter, FilterError, load_filters
from app.core.schema.metadata_types import NormalizedDocument
from app.core.schema.search_hit import SearchHit
from app.core.search.lexical import lexical_search
from app.core.search.pagination import SearchResultPage, paginate
from app.core.search.ranking import merge_and_rank
from app.core.search.semantic import InMemoryVectorStore, SemanticQuery, semantic_search


def _hydrate_metadata(
    hits: Sequence[SearchHit], documents_by_id: Mapping[str, NormalizedDocument]
) -> list[SearchHit]:
    """Attach each hit's full metadata from the source document.

    Neither `semantic_search()` nor `lexical_search()`
    attaches metadata to the `SearchHit`s they produce -- by design, per
    both modules' own docstrings ("enriching a hit with metadata is the
    API layer's job, not retrieval's"). This function is that job: the
    one place metadata gets joined back onto a hit, using the SAME
    `documents_by_id` lookup the filtering stage already built its
    candidate set from, so there is exactly one source of truth for "what
    does this document's metadata look like" throughout one request.

    A hit whose id is somehow absent from `documents_by_id` (should not
    happen -- every hit's id came from a candidate that IS in this map)
    is dropped rather than raising, matching the codebase's general
    "loud at setup time, tolerant at query time for the merely
    unexpected" posture; nothing today is expected to exercise this
    path.
    """
    hydrated: list[SearchHit] = []
    for hit in hits:
        document = documents_by_id.get(hit.id)
        if document is None:
            continue
        hydrated.append(hit.model_copy(update={"metadata": document.metadata}))
    return hydrated


class SearchEngine:
    """One project's common API surface: config + filters + corpus (+
    optionally an embedding provider), bundled once at startup, exposing
    a single `search()` method per source doc §11.

    Construct directly when the config/filters/documents are already in
    hand (e.g. in tests, or after a custom startup sequence), or via
    `SearchEngine.from_config_path()` for the common case of "load
    config.yaml from disk."
    """

    def __init__(
        self,
        config: UseCaseConfig,
        filters: Mapping[str, Filter],
        documents: Iterable[NormalizedDocument],
        *,
        embedding_provider: Optional[EmbeddingProvider] = None,
        text_embedder: Optional[TextEmbedder] = None,
    ):
        self._config = config
        self._filters: dict[str, Filter] = dict(filters)
        self._documents: list[NormalizedDocument] = list(documents)
        self._documents_by_id: dict[str, NormalizedDocument] = {
            doc.id: doc for doc in self._documents
        }
        self._embedding_provider = embedding_provider
        self._text_embedder = text_embedder
        provider_model_id = getattr(embedding_provider, "model_id", None)
        if (
            text_embedder is not None
            and provider_model_id is not None
            and provider_model_id != text_embedder.model_id
        ):
            raise ValueError(
                "text_embedder and embedding_provider use different models "
                f"({text_embedder.model_id!r} vs {provider_model_id!r}); semantic "
                "queries and document vectors must share one vector space"
            )

    @classmethod
    def from_config_path(
        cls,
        config_path: Union[str, Path],
        documents: Iterable[NormalizedDocument],
        *,
        custom_filters: Optional[CustomFilterMap] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        text_embedder: Optional[TextEmbedder] = None,
    ) -> "SearchEngine":
        """Load `config_path`, build its filters (including any §6
        `custom_filters` override), and bundle them with `documents` into
        one `SearchEngine`.

        Raises `BadConfigError` (never a bare `ConfigLoadError`) if the
        config can't be loaded or its filters can't be built -- this is
        the one place a project's startup code needs to catch a single
        error type for "this project's search engine could not be
        constructed."
        """
        try:
            config, filters = load_filters(config_path, custom_filters=custom_filters)
        except ConfigLoadError as exc:
            raise BadConfigError(str(exc)) from exc
        return cls(
            config,
            filters,
            documents,
            embedding_provider=embedding_provider,
            text_embedder=text_embedder,
        )

    @property
    def config(self) -> UseCaseConfig:
        """Return the validated project configuration for transport adapters.

        The engine retains ownership of its operational state (documents,
        filters, and embedding providers). This read-only access point avoids
        a frontend adapter reaching into private state or duplicating YAML.
        """
        return self._config

    def get_document(self, document_id: str) -> Optional[NormalizedDocument]:
        """Return an indexed document by its opaque ID, if it exists."""
        return self._documents_by_id.get(document_id)

    def capabilities(self) -> dict[str, bool]:
        """Return query modes that this initialized engine can actually serve."""
        semantic = self._config.search.semantic.enabled and self._embedding_provider is not None
        return {
            "lexical": self._config.search.lexical.enabled,
            "semantic": semantic,
            "semantic_text": semantic and self._text_embedder is not None,
        }

    def filter_facets(self, fields: Optional[Iterable[str]] = None) -> dict[str, dict[str, Any]]:
        """Summarize filterable values currently present in the corpus.

        The result is configuration-driven: equality fields expose distinct
        values, list ``contains`` fields expose distinct list items, and range
        fields expose their populated bounds. String ``contains`` fields are
        free-text controls, so they only report their populated-record count.
        This lets a UI avoid rendering a selectable filter with no source data.
        """
        requested_fields = list(fields) if fields is not None else list(self._config.filters)
        unknown_fields = set(requested_fields) - set(self._config.filters)
        if unknown_fields:
            raise ValueError(f"unknown filter field(s): {sorted(unknown_fields)}")

        def json_value(value: Any) -> Any:
            return value.isoformat() if isinstance(value, date) else value

        facets: dict[str, dict[str, Any]] = {}
        for field_name in requested_fields:
            field_config = self._config.filters[field_name]
            populated = [
                document.metadata.get(field_name)
                for document in self._documents
                if document.metadata.get(field_name) is not None
            ]
            facet: dict[str, Any] = {"available_count": len(populated)}

            if field_config.operation == "range":
                facet["min"] = json_value(min(populated)) if populated else None
                facet["max"] = json_value(max(populated)) if populated else None
            elif field_config.operation == "equality":
                counts: dict[Any, int] = {}
                for value in populated:
                    counts[value] = counts.get(value, 0) + 1
                facet["values"] = [
                    {"value": json_value(value), "count": count}
                    for value, count in sorted(counts.items(), key=lambda item: str(item[0]).casefold())
                ]
            elif field_config.type.value == "list":
                counts = {}
                for values in populated:
                    for value in set(values):
                        counts[value] = counts.get(value, 0) + 1
                facet["values"] = [
                    {"value": json_value(value), "count": count}
                    for value, count in sorted(counts.items(), key=lambda item: str(item[0]).casefold())
                ]

            facets[field_name] = facet
        return facets

    # -- internal stages ----------------------------------------------

    def _apply_filters(self, requested_filters: Mapping[str, object]) -> list[NormalizedDocument]:
        """Stage 1 (FILTER). AND semantics across fields: each
        declared filter narrows whatever the previous one returned,
        starting from the full corpus. An empty `requested_filters`
        (the request declared no filters at all) is a no-op, same as
        every individual `Filter.apply()`'s own "empty params" contract
        (`app/core/filtering/filters.py`) -- narrowing by nothing narrows
        nothing.
        """
        unknown_fields = set(requested_filters) - set(self._filters)
        if unknown_fields:
            raise BadQueryError(
                f"unknown filter field(s): {sorted(unknown_fields)} "
                f"(this project declares: {sorted(self._filters)})"
            )

        candidates: list[NormalizedDocument] = self._documents
        for field, params in requested_filters.items():
            try:
                candidates = self._filters[field].apply(candidates, field, params)
            except FilterError as exc:
                raise BadQueryError(f"filters['{field}']: {exc}") from exc
        return candidates

    def _run_semantic(
        self, candidates: Sequence[NormalizedDocument], request: SearchRequest
    ) -> list[SearchHit]:
        """Stage 2a (SEARCH -- semantic half). Scoped to
        `candidates`, never the full corpus (see module docstring): the
        vector store built here contains ONLY the ids that survived
        filtering, so semantic search cannot resurrect a document
        filtering already excluded.
        """
        queries = list(request.semantic)
        if request.semantic_text:
            if self._text_embedder is None:
                raise BadConfigError(
                    "a semantic_text query was provided, but this SearchEngine was "
                    "constructed without a text_embedder"
                )
            vectors = self._text_embedder.embed_queries(request.semantic_text)
            if len(vectors) != len(request.semantic_text):
                raise BadConfigError(
                    f"text_embedder returned {len(vectors)} vectors for "
                    f"{len(request.semantic_text)} semantic text queries"
                )
            try:
                queries.extend(SemanticQuery(vector=vector) for vector in vectors)
            except ValueError as exc:
                raise BadConfigError(f"text_embedder returned an invalid vector: {exc}") from exc

        if not queries:
            return []
        if not self._config.search.semantic.enabled:
            raise BadQueryError(
                "a semantic query was provided, but search.semantic.enabled "
                "is false in this project's config"
            )
        if self._embedding_provider is None:
            raise BadConfigError(
                "a semantic query was provided, but this SearchEngine was "
                "constructed without an embedding_provider -- semantic "
                "search has no vectors to search against"
            )

        vectors = []
        for document in candidates:
            embedding = self._embedding_provider.get_embedding(document.id)
            if embedding is not None:
                vectors.append((document.id, embedding.vector))

        if not vectors:
            # Every candidate is missing an embedding (not embedded yet,
            # or a text-only project) -- a normal, non-error outcome per
            # EmbeddingProvider's own docstring ("None is a normal,
            # expected outcome ... not an error condition").
            return []

        store = InMemoryVectorStore(vectors)
        try:
            return semantic_search(
                store,
                queries,
                top_k=len(store),
                strategy=self._config.search.semantic.multi_query_combination,
            )
        except ValueError as exc:
            raise BadQueryError(f"semantic query: {exc}") from exc

    def _run_lexical(
        self, candidates: Sequence[NormalizedDocument], request: SearchRequest
    ) -> list[SearchHit]:
        """Stage 2b (SEARCH -- lexical half). Scoped to
        `candidates`, same reasoning as `_run_semantic`."""
        if request.lexical is None:
            return []
        if not self._config.search.lexical.enabled:
            raise BadQueryError(
                "a lexical query was provided, but search.lexical.enabled "
                "is false in this project's config"
            )

        document_pairs = [(document.id, document.text) for document in candidates]
        try:
            return lexical_search(document_pairs, request.lexical)
        except ValueError as exc:
            raise BadQueryError(f"lexical query: {exc}") from exc

    # -- public entry point ---------------------------------------------

    def search(self, request: SearchRequest) -> SearchResultPage:
        """Run one `SearchRequest` end to end (per module docstring) and
        return one `SearchResultPage`.

        Raises `BadQueryError` for anything wrong with THIS request given
        a valid config (unknown filter field, disabled search mode,
        invalid page/page_size, ...), and `BadConfigError` for a setup
        problem with the engine itself (missing embedding_provider for a
        semantic request). Never raises merely because zero documents
        matched -- see `app/api/errors.py`'s "no results" section; that
        case returns a normal, empty `SearchResultPage` and is logged via
        `log_no_results` instead.
        """
        with log_stage("filtering", requested_fields=sorted(request.filters)) as out:
            candidates = self._apply_filters(request.filters)
            out["candidate_count"] = len(candidates)

        with log_stage(
            "search",
            semantic_query_count=len(request.semantic) + len(request.semantic_text),
            has_lexical_rule=request.lexical is not None,
        ) as out:
            semantic_hits = self._run_semantic(candidates, request)
            lexical_hits = self._run_lexical(candidates, request)
            out["semantic_hit_count"] = len(semantic_hits)
            out["lexical_hit_count"] = len(lexical_hits)

        with log_stage("ranking", strategy=self._config.search.ranking.strategy) as out:
            ranking_weights = self._config.search.ranking.weights
            merged = merge_and_rank(
                semantic_hits,
                lexical_hits,
                strategy=self._config.search.ranking.strategy,
                weights={
                    "semantic": ranking_weights.semantic,
                    "lexical": ranking_weights.lexical,
                },
            )
            merged = _hydrate_metadata(merged, self._documents_by_id)
            out["merged_hit_count"] = len(merged)

        with log_stage("pagination", page=request.page, page_size=request.page_size) as out:
            try:
                result_page = paginate(
                    merged,
                    page=request.page,
                    page_size=request.page_size,
                    default_page_size=self._config.search.pagination.default_page_size,
                    max_page_size=self._config.search.pagination.max_page_size,
                )
            except ValueError as exc:
                raise BadQueryError(f"pagination: {exc}") from exc
            out["total_hits"] = result_page.total_hits
            out["total_pages"] = result_page.total_pages

        if result_page.total_hits == 0:
            log_no_results(
                requested_fields=sorted(request.filters),
                semantic_query_count=len(request.semantic),
                has_lexical_rule=request.lexical is not None,
            )

        return result_page
