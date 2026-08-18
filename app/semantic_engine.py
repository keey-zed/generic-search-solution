from __future__ import annotations

import logging
import pickle
import re
from pathlib import Path
from functools import lru_cache
from typing import Any, Dict, List, Tuple, Optional

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
import hashlib
from collections import OrderedDict
# Works whether semantic_engine.py is imported as package module or script-level module
try:
    from . import data_loader
except Exception:
    import data_loader  # type: ignore

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Arabic normalization (matches your notebook logic)
# -------------------------------------------------------------------
_DIACRITICS_LIST = ['ً', 'ٌ', 'ٍ', 'َ', 'ُ', 'ِ', 'ّ', 'ْ']
_TATWEEL = 'ـ'


def undiacritize(original_text: str) -> str:
    text = "" if original_text is None else str(original_text)

    for haraka in _DIACRITICS_LIST:
        text = text.replace(haraka, "")

    text = text.replace(_TATWEEL, "")

    # Replace successive spaces with a single space
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _as_f32(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x)
    if x.dtype != np.float32:
        x = x.astype(np.float32)
    return np.ascontiguousarray(x)


def _choose_device(device: str) -> str:
    """
    Returns 'cuda' or 'cpu' (SentenceTransformer-friendly).
    """
    if device and device != "auto":
        return device
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _normalize_rel_path(p: str) -> str:
    """
    Keep consistent with data_loader path semantics.
    """
    if not p:
        return ""
    s = str(p).strip().replace("\\", "/")
    s = s.lstrip("/")
    return s


def _merge_ranges(ranges: list[tuple[int, int]], join_if_gap_leq: int = 2) -> list[tuple[int, int]]:
    """
    Merge overlapping / adjacent source ranges.
    Example: [(0,97), (99,250)] becomes one range if small gap allowed.
    """
    clean: list[tuple[int, int]] = []
    for r in ranges or []:
        if not r or len(r) != 2:
            continue
        a, b = r
        if a is None or b is None:
            continue
        try:
            a = int(a)
            b = int(b)
        except Exception:
            continue
        if b < a:
            a, b = b, a
        clean.append((a, b))

    if not clean:
        return []

    clean.sort(key=lambda x: (x[0], x[1]))
    merged = [clean[0]]

    for a, b in clean[1:]:
        la, lb = merged[-1]
        if a <= lb + 1 + join_if_gap_leq:
            merged[-1] = (la, max(lb, b))
        else:
            merged.append((a, b))
    return merged


# -------------------------------------------------------------------
# Hybrid retrieval helpers (ported from your notebook, same behavior)
# -------------------------------------------------------------------
def scale_scores(values, method="minmax", eps=1e-12):
    v = np.asarray(values, dtype=np.float32)
    if v.size == 0:
        return v
    if method == "minmax":
        vmin, vmax = float(v.min()), float(v.max())
        if abs(vmax - vmin) < eps:
            return np.ones_like(v, dtype=np.float32)
        return (v - vmin) / (vmax - vmin)
    elif method == "zsigmoid":
        mu, sd = float(v.mean()), float(v.std())
        if sd < eps:
            return np.ones_like(v, dtype=np.float32)
        z = (v - mu) / sd
        return 1.0 / (1.0 + np.exp(-z))
    else:
        raise ValueError("scale method must be one of: 'minmax', 'zsigmoid'")


def _build_scaled_maps(idx_to_rawscore, method="minmax"):
    """Return idx->scaled_score computed over the provided set only."""
    idxs = list(idx_to_rawscore.keys())
    raws = [idx_to_rawscore[i] for i in idxs]
    scaled = scale_scores(raws, method=method)
    return {i: float(s) for i, s in zip(idxs, scaled)}


def _rank_percentiles(idx_to_rawscore_desc):
    """
    Given idx->rawscore, produce idx->percentile based on rank among its own list.
    Best item ~ 1.0, worst ~ 0.0 (or 1.0 if only one).
    """
    items = sorted(idx_to_rawscore_desc.items(), key=lambda x: x[1], reverse=True)
    n = len(items)
    out = {}
    if n == 0:
        return out
    if n == 1:
        out[items[0][0]] = 1.0
        return out
    for r, (idx_, _) in enumerate(items):
        out[idx_] = 1.0 - (r / (n - 1))
    return out


def _quantile_from_scaled_distribution(scaled_values_sorted, q):
    """
    scaled_values_sorted: sorted list of scaled scores (ascending)
    q in [0,1]
    returns approximate quantile value.
    """
    if len(scaled_values_sorted) == 0:
        return 0.0
    q = float(np.clip(q, 0.0, 1.0))
    pos = q * (len(scaled_values_sorted) - 1)
    lo = int(np.floor(pos))
    hi = int(np.ceil(pos))
    if lo == hi:
        return float(scaled_values_sorted[lo])
    w = pos - lo
    return float((1 - w) * scaled_values_sorted[lo] + w * scaled_values_sorted[hi])


class SemanticEngine:
    """
    Semantic retrieval using precomputed embeddings + FAISS.

    ✅ Uses E5-only semantic retrieval:
      - FAISS IndexFlatIP (cosine-like on normalized vectors)
      - query normalization (undiacritize)
      - auto-tuned E5 threshold for stable #hits

    ✅ CRITICAL FIX (your notebook mapping):
      - page_index from chunks_tobe_embedded is used to fetch the REAL PAGE metadata
        (path/book/page numbers/author...) from data_loader arrays loaded from books_chunks.pickle
        just like: pages[chunks[idx]['page_index']]
    """

    _DEFAULT_E5_KWARGS = dict(
        start_threshold=0.8,
        min_hits=7,
        max_hits=25,
        step=0.002,
        min_threshold=0.7,
        max_threshold=1.0,
        max_iters=500,
        max_results=None,
        verbose=False,
    )

    def __init__(self, settings: Any | None = None, *, device: str | None = None):
        self.settings = settings

        settings_device = getattr(settings, "device", "auto") if settings is not None else "auto"
        self.device = _choose_device(device or settings_device)

        self.index_e5: Optional[faiss.Index] = None
        self.e5: Optional[SentenceTransformer] = None
        self.emb_e5: Optional[np.ndarray] = None

        # semantic chunks list
        self.chunks: list[dict[str, Any]] | None = None

        self._loaded = False
        self._loaded_data_version = None  # for safe auto-reload if ingestion updates DATA_VERSION
        # Cache subset indices so repeated filtered searches don't rebuild every time
        self._subset_index_cache: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._subset_index_cache_max = 16

    # ---------------- pickle/path helpers ----------------
    def _find_existing(self, candidates: list[Path], label: str) -> Path:
        for p in candidates:
            if p.exists():
                return p
        raise FileNotFoundError(f"Missing {label}. Tried:\n" + "\n".join(str(p) for p in candidates))

    @staticmethod
    def _load_pickle(path: Path):
        if not path.exists():
            raise FileNotFoundError(f"Missing pickle file: {path}")
        with path.open("rb") as f:
            return pickle.load(f)

    def _resolve_embeddings_paths(self) -> Path:
        """Resolve the E5 embedding pickle only."""
        emb_dir = (
            Path(data_loader.embeddings_dir())
            if hasattr(data_loader, "embeddings_dir")
            else (Path(data_loader._app_root()) / "data" / "embeddings")
        )
        return self._find_existing(
            [
                emb_dir / "embeddings_e5_FULL.pickle",
                emb_dir / "embeddings_e5.pickle",
            ],
            "E5 embeddings",
        )

    def _resolve_chunks_path(self) -> Path:
        explicit = getattr(self.settings, "chunks_pickle_path", None) if self.settings is not None else None
        if explicit:
            p = Path(explicit)
            if p.exists():
                return p

        if hasattr(data_loader, "semantic_chunks_pickle_path"):
            return Path(data_loader.semantic_chunks_pickle_path())

        return self._find_existing([Path(data_loader._app_root()) / "data" / "chunks_tobe_embedded.pickle"], "chunks_tobe_embedded.pickle")

    # ---------------- lifecycle ----------------
    def _reset(self):
        self.index_e5 = None
        self.e5 = None
        self.emb_e5 = None
        self.chunks = None
        self._loaded = False

        try:
            self.search.cache_clear()  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            self.search_chunk_indices.cache_clear()  # type: ignore[attr-defined]
        except Exception:
            pass

    def load(self) -> None:
        """Lazy-load the E5-only semantic engine."""
        current_ver = getattr(data_loader, "DATA_VERSION", None)

        if self._loaded and self._loaded_data_version == current_ver:
            return

        if self._loaded and self._loaded_data_version != current_ver:
            logger.info(
                "SemanticEngine reload due to DATA_VERSION change (%s -> %s)",
                self._loaded_data_version,
                current_ver,
            )
            self._reset()

        # Ensure pages are loaded for authoritative page mapping.
        if hasattr(data_loader, "chunks") and len(getattr(data_loader, "chunks", [])) == 0:
            try:
                data_loader.load_chunks()
            except Exception:
                pass

        emb_e5_path = self._resolve_embeddings_paths()
        chunks_path = self._resolve_chunks_path()

        emb_e5 = _as_f32(self._load_pickle(emb_e5_path))
        if emb_e5.ndim != 2:
            raise ValueError("E5 embeddings must be a 2D array [n_chunks, dim].")

        self.index_e5 = faiss.IndexFlatIP(emb_e5.shape[1])
        self.index_e5.add(emb_e5)
        self.emb_e5 = emb_e5

        self.chunks = self._load_pickle(chunks_path)
        if not isinstance(self.chunks, list):
            raise TypeError(f"Expected chunks to be a list, got {type(self.chunks)}")

        if len(self.chunks) != emb_e5.shape[0]:
            raise ValueError(
                f"Mismatch: len(chunks)={len(self.chunks)} "
                f"but E5 embeddings rows={emb_e5.shape[0]}"
            )

        all_chunks = [x["text"] for x in self.chunks]
        self.all_chunks = [undiacritize(x) for x in all_chunks]

        e5_kwargs = {}
        if str(self.device).startswith("cuda"):
            e5_kwargs = {"model_kwargs": {"torch_dtype": "float16"}}

        self.e5 = SentenceTransformer(
            "intfloat/multilingual-e5-large",
            device=self.device,
            **e5_kwargs,
        )

        try:
            warm_q = "warmup"
            _ = self.e5.encode(
                [f"query: {warm_q}"],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as e:
            logger.warning("SemanticEngine warmup skipped/failed: %s", e)

        self._loaded = True
        self._loaded_data_version = current_ver

        logger.info(
            "SemanticEngine loaded (device=%s, n_chunks=%d, e5_dim=%d).",
            self.device,
            emb_e5.shape[0],
            emb_e5.shape[1],
        )

    def _get_query_candidates(self, query: str, *, model_name: str, candidate_k: int) -> Tuple[np.ndarray, np.ndarray]:
        if self.index_e5 is None or self.e5 is None:
            raise RuntimeError("Engine not loaded.")

        if model_name != "e5":
            raise ValueError("model_name must be 'e5'")

        q = undiacritize(query)
        q_emb = self.e5.encode(
            [f"query: {q}"],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        q_emb = _as_f32(q_emb)
        k = min(int(candidate_k), int(self.index_e5.ntotal))
        D, I = self.index_e5.search(q_emb, k)
        return D[0], I[0]

    def _filter_hits_by_threshold(scores, ids, threshold: float, max_results=None):
        hits = []
        for score, idx_ in zip(scores, ids):
            if int(idx_) == -1:
                continue
            if float(score) >= float(threshold):
                hits.append((float(score), int(idx_)))
        if max_results is not None:
            hits = hits[:max_results]
        return hits

    def _auto_tune_threshold_for_query(
        self,
        query: str,
        *,
        model_name: str,
        start_threshold: float,
        min_hits: int,
        max_hits: int,
        candidate_k: int,
        step: float,
        min_threshold: float,
        max_threshold: float,
        max_iters: int,
        max_results=None,
        verbose: bool = False,
    ) -> Tuple[float, List[Tuple[float, int]]]:
        scores, ids = self._get_query_candidates(query, model_name=model_name, candidate_k=candidate_k)

        thr = float(start_threshold)
        best_thr = thr
        best_hits = self._filter_hits_by_threshold(scores, ids, thr, max_results=max_results)
        best_count = len(best_hits)

        if min_hits <= best_count <= max_hits:
            return thr, best_hits

        visited = set()

        for _it in range(int(max_iters)):
            key = round(thr, 6)
            if key in visited:
                break
            visited.add(key)

            count = len(self._filter_hits_by_threshold(scores, ids, thr, max_results=None))

            if count < min_hits:
                dist = min_hits - count
            elif count > max_hits:
                dist = count - max_hits
            else:
                dist = 0

            if best_count < min_hits:
                best_dist = min_hits - best_count
            elif best_count > max_hits:
                best_dist = best_count - max_hits
            else:
                best_dist = 0

            if dist < best_dist:
                best_thr = thr
                best_count = count
                best_hits = self._filter_hits_by_threshold(scores, ids, thr, max_results=max_results)

            if min_hits <= count <= max_hits:
                final_hits = self._filter_hits_by_threshold(scores, ids, thr, max_results=max_results)
                return thr, final_hits

            if count < min_hits:
                thr -= float(step)
            else:
                thr += float(step)

            thr = max(float(min_threshold), min(float(max_threshold), thr))

            if thr in (float(min_threshold), float(max_threshold)):
                break

        return best_thr, best_hits

    def _run_model_retrieval_autotuned(
        self,
        query: str,
        *,
        model_name: str,
        tuned_kwargs: dict,
    ) -> Tuple[float, Dict[int, float]]:
        thr, hits = self._auto_tune_threshold_for_query(query, model_name=model_name, **tuned_kwargs)

        out: Dict[int, float] = {}
        for score, idx_ in hits:
            if idx_ not in out or score > out[idx_]:
                out[idx_] = float(score)
        return thr, out

    def _hybrid_two_stage_rank(
        self,
        query: str,
        *,
        e5_kwargs: dict,
        scale_method: str = "minmax",
        top_n_common=None,
        top_n_single=None,
        print_debug: bool = False,
    ) -> List[Dict[str, Any]]:
        """E5-only ranking. Name kept to minimize changes elsewhere."""
        _, e5_map = self._run_model_retrieval_autotuned(
            query,
            model_name="e5",
            tuned_kwargs=e5_kwargs,
        )

        ranked = [
            {
                "idx": int(idx_),
                "group": "e5",
                "mean_score": float(score),
                "e5_raw": float(score),
                "e5_scaled": float(score),
                "text": self.all_chunks[idx_],
            }
            for idx_, score in e5_map.items()
        ]
        ranked.sort(key=lambda x: x["mean_score"], reverse=True)
        return ranked

    def _page_meta_from_pages_pickle(self, page_index: int) -> dict[str, Any]:
        """
        page_index aligns with data_loader arrays loaded from books_chunks.pickle.
        This is the SAME idea as:
          pages[chunks[idx]['page_index']]
        """
        meta: dict[str, Any] = {}

        try:
            i = int(page_index)
        except Exception:
            return meta

        def _get(lst_name, default=None):
            try:
                lst = getattr(data_loader, lst_name, [])
                if 0 <= i < len(lst):
                    return lst[i]
            except Exception:
                pass
            return default

        meta["page_index"] = i
        meta["book_name"] = _get("book_names", "")
        meta["author"] = _get("authors", "")
        meta["page_number"] = _get("page_numbers", None)
        meta["printed_page_number"] = _get("printed_page_numbers", None)
        meta["path"] = _normalize_rel_path(_get("paths", "") or "")
        meta["Subjects"] = _get("Subject_list", [])
        return meta

    def _chunk_page_index(self, row_idx: int) -> Optional[int]:
        """
        Get page_index from semantic chunk row.
        """
        if self.chunks is None:
            return None
        if row_idx < 0 or row_idx >= len(self.chunks):
            return None

        ch = self.chunks[row_idx]
        if not isinstance(ch, dict):
            return None

        pi = ch.get("page_index")
        try:
            if pi is None:
                return None
            return int(pi)
        except Exception:
            return None

    def _chunk_source_ranges(self, row_idx: int) -> list[tuple[int, int]]:
        """
        source_ranges are expected to be in PAGE TEXT coordinates.
        Your mapping pickle may contain them; if not, fallback to chunk fields.
        """
        if self.chunks is None:
            return []

        ch = self.chunks[row_idx]
        if not isinstance(ch, dict):
            return []

        sr = ch.get("source_ranges") or []
        out = []
        if isinstance(sr, (list, tuple)):
            for r in sr:
                if isinstance(r, (list, tuple)) and len(r) == 2:
                    try:
                        out.append((int(r[0]), int(r[1])))
                    except Exception:
                        continue
                elif isinstance(r, dict):
                    try:
                        out.append((int(r.get("start")), int(r.get("end"))))
                    except Exception:
                        continue
        return out


    # -------------------------------------------------------------------
    # Public API (routes.py compatible)
    # -------------------------------------------------------------------
    @lru_cache(maxsize=2048)
    def search_chunk_indices(self, query: str, k: int = 80) -> tuple[int, ...]:
        """Returns ordered chunk row indices using E5 only."""
        self.load()

        if not query or not str(query).strip():
            return tuple()
        if self.index_e5 is None:
            return tuple()

        ntotal = int(self.index_e5.ntotal)
        candidate_k = min(ntotal, 250000)

        e5_kwargs = dict(self._DEFAULT_E5_KWARGS)
        e5_kwargs["candidate_k"] = candidate_k

        ranked = self._hybrid_two_stage_rank(
            query,
            e5_kwargs=e5_kwargs,
            scale_method="minmax",
            top_n_common=None,
            top_n_single=None,
            print_debug=False,
        )

        idxs = [int(x["idx"]) for x in ranked if "idx" in x]
        seen = set()
        out = []
        for i in idxs:
            if i not in seen:
                out.append(i)
                seen.add(i)

        try:
            kk = int(k)
            if kk > 0:
                out = out[:kk]
        except Exception:
            pass

        return tuple(out)

    def search(self, query: str, k: int = 300000) -> tuple[dict[str, Any], ...]:
        """Returns E5-ranked chunk-level hits."""
        self.load()

        q = (query or "").strip()
        if not q:
            return tuple()
        if self.index_e5 is None:
            return tuple()

        ntotal = int(self.index_e5.ntotal)
        candidate_k = min(ntotal, 300000)

        e5_kwargs = dict(self._DEFAULT_E5_KWARGS)
        e5_kwargs["candidate_k"] = candidate_k

        ranked = self._hybrid_two_stage_rank(
            q,
            e5_kwargs=e5_kwargs,
            scale_method="minmax",
            top_n_common=None,
            top_n_single=None,
            print_debug=False,
        )

        try:
            kk = int(k)
            if kk <= 0:
                kk = 80
        except Exception:
            kk = 80

        hits = []
        seen_chunks = set()

        for r in ranked:
            try:
                chunk_idx = int(r["idx"])
            except Exception:
                continue

            if chunk_idx in seen_chunks:
                continue
            seen_chunks.add(chunk_idx)

            ch = self.chunks[chunk_idx] if self.chunks is not None and 0 <= chunk_idx < len(self.chunks) else None
            if not isinstance(ch, dict):
                continue

            try:
                page_index = ch.get("page_index", None)
                page_index = None if page_index is None else int(page_index)
            except Exception:
                page_index = None

            sr = ch.get("source_ranges") or []
            source_ranges = []
            if isinstance(sr, (list, tuple)):
                for rr in sr:
                    if isinstance(rr, (list, tuple)) and len(rr) == 2:
                        try:
                            source_ranges.append((int(rr[0]), int(rr[1])))
                        except Exception:
                            pass
                    elif isinstance(rr, dict):
                        try:
                            source_ranges.append((int(rr.get("start")), int(rr.get("end"))))
                        except Exception:
                            pass

            try:
                score = float(r.get("mean_score", 0.0))
            except Exception:
                score = 0.0

            hits.append({
                "chunk_index": chunk_idx,
                "page_index": page_index,
                "semantic_score": score,
                "source_ranges": source_ranges,
                "chunk_text": ch.get("text", ""),
                "group": r.get("group"),
            })

            if len(hits) >= kk:
                break

        return tuple(hits)

    def search_chunks(self, query: str, k: int = 80) -> tuple[dict[str, Any], ...]:
        return self.search(query, k=k)
        
        # ============================================================
    # Subset semantic search: auto-tune on filtered subset ONLY
    # ============================================================

    def _subset_key_from_pages(self, pages: list[int]) -> str:
        uniq = sorted({int(x) for x in (pages or [])})
        raw = (",".join(map(str, uniq))).encode("utf-8")
        return hashlib.sha1(raw).hexdigest()

    def _subset_cache_get(self, key: str):
        v = self._subset_index_cache.get(key)
        if v is not None:
            self._subset_index_cache.move_to_end(key)
        return v

    def _subset_cache_put(self, key: str, value: dict[str, Any]):
        self._subset_index_cache[key] = value
        self._subset_index_cache.move_to_end(key)
        while len(self._subset_index_cache) > int(self._subset_index_cache_max):
            self._subset_index_cache.popitem(last=False)

    def _build_subset_indices_for_pages(self, valid_page_indices: list[int]) -> dict[str, Any]:
        """Build an E5 FAISS index restricted to chunks in valid_page_indices."""
        if self.chunks is None or self.emb_e5 is None:
            raise RuntimeError("Engine not loaded.")

        page_set = {int(x) for x in (valid_page_indices or [])}
        chunk_ids = []
        for i, ch in enumerate(self.chunks):
            if not isinstance(ch, dict):
                continue
            pi = ch.get("page_index", None)
            try:
                pi = None if pi is None else int(pi)
            except Exception:
                pi = None
            if pi is not None and pi in page_set:
                chunk_ids.append(int(i))

        chunk_ids_arr = np.asarray(chunk_ids, dtype=np.int32)
        if chunk_ids_arr.size == 0:
            return {"index_e5_sub": None, "chunk_ids": chunk_ids_arr}

        emb_e5_sub = _as_f32(self.emb_e5[chunk_ids_arr])
        idx_e5 = faiss.IndexFlatIP(emb_e5_sub.shape[1])
        idx_e5.add(emb_e5_sub)

        return {"index_e5_sub": idx_e5, "chunk_ids": chunk_ids_arr}

    def _get_query_candidates_subset(
        self,
        query: str,
        *,
        model_name: str,
        candidate_k: int,
        index_override: faiss.Index,
        chunk_ids_map: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        if self.e5 is None:
            raise RuntimeError("Engine not loaded.")
        if model_name != "e5":
            raise ValueError("model_name must be 'e5'")

        q = undiacritize(query)
        q_emb = self.e5.encode(
            [f"query: {q}"],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        q_emb = _as_f32(q_emb)
        k = min(int(candidate_k), int(index_override.ntotal))
        D, I = index_override.search(q_emb, k)
        local_ids = I[0]
        global_ids = np.array(
            [-1 if int(x) == -1 else int(chunk_ids_map[int(x)]) for x in local_ids],
            dtype=np.int64,
        )
        return D[0], global_ids

    def _auto_tune_threshold_for_query_subset(
        self,
        query: str,
        *,
        model_name: str,
        start_threshold: float,
        min_hits: int,
        max_hits: int,
        candidate_k: int,
        step: float,
        min_threshold: float,
        max_threshold: float,
        max_iters: int,
        max_results=None,
        verbose: bool = False,
        index_override: faiss.Index,
        chunk_ids_map: np.ndarray,
    ) -> Tuple[float, List[Tuple[float, int]]]:
        scores, ids = self._get_query_candidates_subset(
            query,
            model_name=model_name,
            candidate_k=candidate_k,
            index_override=index_override,
            chunk_ids_map=chunk_ids_map,
        )

        thr = float(start_threshold)
        best_thr = thr
        best_hits = self._filter_hits_by_threshold(scores, ids, thr, max_results=max_results)
        best_count = len(best_hits)

        if min_hits <= best_count <= max_hits:
            return thr, best_hits

        visited = set()

        for _it in range(int(max_iters)):
            key = round(thr, 6)
            if key in visited:
                break
            visited.add(key)

            count = len(self._filter_hits_by_threshold(scores, ids, thr, max_results=None))

            if count < min_hits:
                dist = min_hits - count
            elif count > max_hits:
                dist = count - max_hits
            else:
                dist = 0

            if best_count < min_hits:
                best_dist = min_hits - best_count
            elif best_count > max_hits:
                best_dist = best_count - max_hits
            else:
                best_dist = 0

            if dist < best_dist:
                best_thr = thr
                best_count = count
                best_hits = self._filter_hits_by_threshold(scores, ids, thr, max_results=max_results)

            if min_hits <= count <= max_hits:
                final_hits = self._filter_hits_by_threshold(scores, ids, thr, max_results=max_results)
                return thr, final_hits

            if count < min_hits:
                thr -= float(step)
            else:
                thr += float(step)

            thr = max(float(min_threshold), min(float(max_threshold), thr))

            if thr in (float(min_threshold), float(max_threshold)):
                break

        return best_thr, best_hits

    def _run_model_retrieval_autotuned_subset(
        self,
        query: str,
        *,
        model_name: str,
        tuned_kwargs: dict,
        index_override: faiss.Index,
        chunk_ids_map: np.ndarray,
    ) -> Tuple[float, Dict[int, float]]:
        thr, hits = self._auto_tune_threshold_for_query_subset(
            query,
            model_name=model_name,
            index_override=index_override,
            chunk_ids_map=chunk_ids_map,
            **tuned_kwargs,
        )
        out: Dict[int, float] = {}
        for score, idx_ in hits:
            if idx_ not in out or score > out[idx_]:
                out[idx_] = float(score)
        return thr, out

    def _hybrid_two_stage_rank_subset(
        self,
        query: str,
        *,
        e5_kwargs: dict,
        index_e5_sub: faiss.Index,
        chunk_ids_map: np.ndarray,
        scale_method: str = "minmax",
        top_n_common=None,
        top_n_single=None,
        print_debug: bool = False,
    ) -> List[Dict[str, Any]]:
        """E5-only ranking inside a filtered subset."""
        _, e5_map = self._run_model_retrieval_autotuned_subset(
            query,
            model_name="e5",
            tuned_kwargs=e5_kwargs,
            index_override=index_e5_sub,
            chunk_ids_map=chunk_ids_map,
        )

        ranked = [
            {
                "idx": int(idx_),
                "group": "e5",
                "mean_score": float(score),
                "e5_raw": float(score),
                "e5_scaled": float(score),
                "text": self.all_chunks[int(idx_)] if hasattr(self, "all_chunks") else "",
            }
            for idx_, score in e5_map.items()
        ]
        ranked.sort(key=lambda x: x["mean_score"], reverse=True)
        return ranked

    def search_in_pages(
        self,
        query: str,
        *,
        valid_page_indices: list[int],
        k: int = 300000,
    ) -> tuple[dict[str, Any], ...]:
        """E5-only semantic search restricted to the selected pages."""
        self.load()

        q = (query or "").strip()
        if not q:
            return tuple()
        if self.chunks is None or self.emb_e5 is None:
            return tuple()

        pages = list(valid_page_indices or [])
        if not pages:
            return tuple()

        key = self._subset_key_from_pages(pages)
        cached = self._subset_cache_get(key)
        if cached is None:
            cached = self._build_subset_indices_for_pages(pages)
            self._subset_cache_put(key, cached)

        index_e5_sub = cached.get("index_e5_sub")
        chunk_ids_map = cached.get("chunk_ids")
        if index_e5_sub is None or chunk_ids_map is None:
            return tuple()

        subset_n = int(index_e5_sub.ntotal)
        if subset_n <= 0:
            return tuple()

        candidate_k = min(subset_n, 300000)
        e5_kwargs = dict(self._DEFAULT_E5_KWARGS)
        e5_kwargs["candidate_k"] = candidate_k

        ranked = self._hybrid_two_stage_rank_subset(
            q,
            e5_kwargs=e5_kwargs,
            index_e5_sub=index_e5_sub,
            chunk_ids_map=chunk_ids_map,
            scale_method="minmax",
            top_n_common=None,
            top_n_single=None,
            print_debug=False,
        )

        try:
            kk = int(k)
            if kk <= 0:
                kk = 80
        except Exception:
            kk = 80

        hits = []
        seen_chunks = set()
        for r in ranked:
            try:
                chunk_idx = int(r["idx"])
            except Exception:
                continue

            if chunk_idx in seen_chunks:
                continue
            seen_chunks.add(chunk_idx)

            ch = self.chunks[chunk_idx] if 0 <= chunk_idx < len(self.chunks) else None
            if not isinstance(ch, dict):
                continue

            try:
                page_index = ch.get("page_index", None)
                page_index = None if page_index is None else int(page_index)
            except Exception:
                page_index = None

            sr = ch.get("source_ranges") or []
            source_ranges = []
            if isinstance(sr, (list, tuple)):
                for rr in sr:
                    if isinstance(rr, (list, tuple)) and len(rr) == 2:
                        try:
                            source_ranges.append((int(rr[0]), int(rr[1])))
                        except Exception:
                            pass
                    elif isinstance(rr, dict):
                        try:
                            source_ranges.append((int(rr.get("start")), int(rr.get("end"))))
                        except Exception:
                            pass

            try:
                score = float(r.get("mean_score", 0.0))
            except Exception:
                score = 0.0

            hits.append({
                "chunk_index": chunk_idx,
                "page_index": page_index,
                "semantic_score": score,
                "source_ranges": source_ranges,
                "chunk_text": ch.get("text", ""),
                "group": r.get("group"),
            })

            if len(hits) >= kk:
                break

        return tuple(hits)
