# Frontend Control Mapping & API Contract (Phase 5, item 1)

This document specifies **Phase 5, item 1**: "define the config →
UI-control mapping (date range picker, dropdown, text filter, etc., per
§10's example) as an explicit table, not implicit convention."

**Status of the rest of Phase 5**: items 2–3 (generic components,
branding wiring) are frontend-repo work — "front-end code already
exists" per the roadmap, and that codebase isn't part of this
repository. What *is* in this repository, and complete, is the backend
contract those components consume: `GET /api/config` and
`GET /api/facets` (`app/api/http.py`). This document describes that
contract precisely, verified against the actual implementation, not
speculatively. Item 4's Definition of Done is validated in
`tests/test_phase5_definition_of_done.py` — see that file's own
docstring for the honest scope note on what "validated" means without
access to the actual frontend.

```bash
PYTHONPATH=. python3 -m pytest tests/test_phase5_definition_of_done.py tests/test_http_api.py
```

## `GET /api/config` — the static UI contract

Returns, for the currently-running use case:

```json
{
  "branding": { "title": "...", "subtitle": "...", "primary_color": "...", "search_placeholder": "..." },
  "filters": [
    {
      "name": "publication_date",
      "label": "Date de publication",
      "control": "date_range",
      "order": 1,
      "placeholder": null,
      "type": "date",
      "item_type": null,
      "operation": "range",
      "required": false,
      "default": null
    }
  ],
  "result_card_fields": ["document_type", "legal_status", "publication_date", "title"],
  "search": { "lexical": true, "semantic": true, "semantic_text": false },
  "pagination": { "default_page_size": 20, "max_page_size": 100 }
}
```

- **`filters`** is sorted by `order` — a frontend renders it top-to-bottom
  as-is, no client-side sorting needed.
- Only fields listed under `frontend.filters:` in `config.yaml` appear
  here — a field declared under `filters:` but not under
  `frontend.filters:` is still filterable via `POST /search`, just not
  advertised as a UI control (`docs/config-schema.md` §3, "opt-in
  exposure, not opt-out").
- **`control`** is always resolved to a concrete value (never `null`) —
  either the one explicitly set in `frontend.filters[name].control`, or
  the type+operation default from `DEFAULT_CONTROL`
  (`docs/config-schema.md`'s "Control resolution" table). A frontend
  never has to compute this itself.
- **`search`** (`engine.capabilities()`) tells a frontend which query
  modes to actually offer — e.g. `semantic: false` if the project has no
  embedding provider configured, even though `config.yaml` might declare
  `search.semantic.enabled: true`. Effective capability, not raw config.

## `GET /api/facets` — the dynamic data behind each control

Returns, per visible filter field, a summary of what's actually in the
corpus right now — the data a control needs to populate itself (dropdown
options, a range slider's real min/max), not just its static shape:

| `operation` / `type` | Facet shape | Used for |
|---|---|---|
| `equality` (any type) | `{"available_count": N, "values": [{"value": ..., "count": ...}, ...]}`, sorted case-insensitively | Populating a `dropdown`/`radio`'s option list, with counts if the UI wants to show them. |
| `range` | `{"available_count": N, "min": ..., "max": ...}` (`null`/`null` if no record has this field populated) | Setting a `date_range`/`number_range` control's actual bounds — never hardcode min/max in the frontend. |
| `contains` on `type: list` | Same shape as `equality` — distinct list items across the corpus, with counts | Populating a `multi_select`/`checkbox_group`'s option list. |
| `contains` on `type: string` | `{"available_count": N}` only — no `values` key | Free-text search has no finite option set; a frontend should render a plain text input, not try to read `values` (it won't be there). |

`app/custom/legal_pilot`'s own facets test
(`tests/test_http_api.py::test_facets_endpoint_exposes_only_visible_filter_data`)
demonstrates exactly this: `title` (`contains` on `string`) reports only
`available_count`, no `values` — confirmed by asserting
`"values" not in facets["title"]`, not merely that it's empty.

## Payload contract: what a control sends back to `POST /search`

This is the piece that ties a rendered control to the filter it drives —
the exact shape `Filter.apply()`'s `params` argument expects
(`docs/filtering.md` §3):

| Control | Payload sent under `filters.<name>` |
|---|---|
| `text` | A string. |
| `dropdown` / `radio` | A single scalar (matching the field's `type`), or a list of scalars for OR semantics if the control allows multi-select. |
| `date` / `number` | A single value, or a list of them for OR semantics. |
| `date_range` / `number_range` | `{"min": ..., "max": ...}` — either key omittable; add `"min_inclusive"`/`"max_inclusive"` (booleans) only to override the default (both inclusive). |
| `checkbox` / `toggle` | `true` or `false`. Omit the field entirely (don't send `false`) if "unchecked" should mean "no filter applied" rather than "explicitly filter for false" — these are different things (`docs/filtering.md` §2: absent/empty params is a no-op). |
| `multi_select` / `checkbox_group` | A list of strings (or the field's `item_type`). An empty list and an omitted field both mean "no restriction." |

Worked example, using `app/custom/legal_pilot/config.yaml`'s
`publication_date` field (`type: date`, `operation: range`, resolved
control `date_range`): a frontend renders two date pickers seeded with
`/api/facets`'s reported `min`/`max`, and on submit sends
`{"publication_date": {"min": "2020-01-01", "max": "2020-12-31"}}` as
part of `POST /search`'s `filters` — exactly what `RangeFilter.apply()`
already expects, zero backend translation needed.

## What's deliberately not built here

- **Actual UI components** (Angular/React/whatever the frontend
  repository uses). Phase 5, items 2–3 — out of reach in this session;
  this document is the contract they'd be built against.
- **A live visual validation** of item 4's DoD against a real rendered
  page. `tests/test_phase5_definition_of_done.py` validates the backend
  half (the API contract changes correctly from config alone); the
  actual "the UI re-renders with zero frontend code" claim can only be
  fully confirmed inside the frontend repository itself.