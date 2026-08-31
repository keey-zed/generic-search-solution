# YAML Config Schema v0

The `config.yaml` every project must supply, validated by
`app/core/config/models.py` (Pydantic) and loaded via
`app/core/config/loader.py::load_use_case_config()`.

## 1. The four required top-level keys

```yaml
schema_version: 1     # int, must be one this core supports

filters:               # backend truth: field name -> type + operation
  <field_name>:
    type: string | date | int | float | bool | list
    item_type: string | date | int | float | bool   # required iff type == list
    required: true | false                            # default: false
    operation: equality | range | contains

search:                 # generic search/ranking/pagination behavior
  semantic: { enabled: bool, multi_query_combination: max_score | weighted_average }
  lexical: { enabled: bool }
  ranking: { strategy: weighted_sum, weights: { semantic: float, lexical: float } }
  pagination: { default_page_size: int, max_page_size: int }

frontend:                # presentation layer
  branding:
    title: string
    subtitle: string | null
    logo_url: string | null
    primary_color: "#RRGGBB" | null
    search_placeholder: string | null
  filters:                # subset of `filters:` — which get a UI control
    <field_name>:
      label: string
      control: <optional, auto-resolved if omitted>
      order: int           # unique among exposed filters
      placeholder: string | null
  result_card_fields: [field_name, ...]
```

All four keys are required at the top level (`extra="forbid"` rejects any
5th key — usually a typo). `filters:` may be an empty mapping (a project
doing pure semantic/lexical search with no metadata filters is valid).
`search:` may be `{}` — every sub-key has a sane default.

## 2. `filters:` reuses Layer 1's typing, doesn't redeclare it

`type` and `item_type` are the exact same `MetadataFieldType` enum from
`app/core/schema/metadata_types.py`. `operation`
is validated against the exact same `FILTER_OPERATION_COMPATIBILITY`
matrix used at ingestion — a `contains` filter on a `bool` field is
rejected by one shared rule, not by two independently-maintained copies
of that rule. This is the source doc's §5 principle made concrete:
"avoids duplicating the same configuration logic in several places."

| Type | Allowed operations |
|---|---|
| `string` | `equality`, `contains` |
| `date` | `equality`, `range` |
| `int` | `equality`, `range` |
| `float` | `equality`, `range` |
| `bool` | `equality` |
| `list` | `contains` (membership: value ∈ list) |

`item_type` is required when `type: list` and forbidden otherwise —
enforced by `FilterFieldConfig`'s own validator, which mirrors (and is
cross-tested against) `MetadataFieldDef`'s identical rule.

**`UseCaseConfig.to_metadata_schema()`** converts the validated `filters:`
block directly into a `MetadataSchema` (`list[MetadataFieldDef]`) —
call this once at startup and hand the result to `normalize_metadata()` /
`validate_document_batch()`. There is exactly one place a field's type is
declared; config and ingestion both read from it.

## 3. `frontend:` — opt-in exposure, not opt-out

A field declared under `filters:` is **not** automatically shown in the
UI. Only fields explicitly listed under `frontend.filters:` get a
rendered control. This is a deliberate fail-safe default: if a developer
adds a new backend filter and forgets the frontend entry, the filter
stays hidden (safe) rather than silently appearing in the UI (unsafe,
especially for an internal/unfinished filter). The reference example
(`app/custom/legal/config.yaml`) demonstrates this: `promulgation_date`
is filterable via the API but has no `frontend.filters` entry.

### Control resolution

Every `(type, operation)` pair that `FILTER_OPERATION_COMPATIBILITY`
allows has exactly one entry in `DEFAULT_CONTROL` and a non-empty set in
`ALLOWED_CONTROLS` (`app/core/config/models.py`) — guarded by
`test_every_default_control_pair_covers_all_compatible_type_operations`,
so a future new type/operation combo can't silently ship without a
resolvable UI control.

| Type + operation | Default control | Other allowed controls |
|---|---|---|
| `string` + `equality` | `dropdown` | `radio` |
| `string` + `contains` | `text` | — |
| `date` + `equality` | `date` | — |
| `date` + `range` | `date_range` | — |
| `int`/`float` + `equality` | `number` | `dropdown` (int only) |
| `int`/`float` + `range` | `number_range` | — |
| `bool` + `equality` | `checkbox` | `toggle` |
| `list` + `contains` | `multi_select` | `checkbox_group` |

If `control` is omitted, the loader fills in the default so every
downstream consumer always sees a concrete value. If `control` is
explicitly set to something incompatible with the field's type+operation
(e.g. `date_range` on a `bool` field), config loading fails with a
message naming the field, the bad value, and what's actually allowed.

### Other cross-checks

- Every `frontend.filters` key must exist under `filters:` — an unknown
  reference fails with the list of valid names.
- `order` values must be unique among exposed filters (a common
  copy-paste mistake otherwise produces ambiguous UI ordering silently).
- `primary_color`, if set, must be a 6-digit hex color (`#1A2B3C`).
- `result_card_fields` is **not** cross-validated against `filters:` —
  see §5, "Deferred."

## 4. `search:` — sane defaults, explicit failure modes

- `semantic.multi_query_combination`: `max_score` (default) or
  `weighted_average` — exactly the two strategies retrieval work is scoped to implement.
- `ranking.strategy`: `weighted_sum` only in v0 (a `Literal` with one
  value — extend deliberately when a second strategy is actually
  needed). `weights` defaults to `{semantic: 0.5, lexical: 0.5}` and is
  rejected if both are set to `0` (a config that would make ranking a
  no-op).
- `pagination.default_page_size` cannot exceed `max_page_size`.
- **At least one of `semantic.enabled` / `lexical.enabled` must be
  `true`.** A config disabling both would produce a search engine
  incapable of returning any result — caught at load time, not the first
  time someone runs a query against it.

## 5. Deferred / explicitly out of scope for v0

Documented here so nobody "fixes" these ad hoc in one project's fork,
creating drift. Promote deliberately (and update this doc) if a real
project needs one.

- **`result_card_fields` is not cross-validated** against `filters:` or
  any declared metadata schema — a displayed field need not be
  filterable, and v0 has no separate "display-only field" declaration
  block. If this causes real bugs (typo'd field names on result cards
  going unnoticed), add a lightweight declaration for display-only
  fields rather than overloading `filters:`.
- **A field cannot have more than one simultaneous filter operation**
  (e.g. a date field offering both exact-match and range). Declare it
  under one operation per field name for now.
- **No conditional weights-required-per-strategy logic** — moot while
  `ranking.strategy` has exactly one value. Revisit when a second
  strategy is added.
- **No JSON Schema export for `config.yaml`** (unlike the document
  schema, which does have one at `app/core/schema/document.schema.json`).
  Would be useful for editor autocomplete (`yaml-language-server`) but is
  not built in v0 — nice-to-have, not required.
- **No environment-variable interpolation** inside `config.yaml` (e.g.
  `${SOME_SECRET}`). If a project needs this, resolve it before the raw
  dict reaches `yaml.safe_load`, not inside the schema itself.

## 6. Versioning policy

`SUPPORTED_SCHEMA_VERSIONS` (currently `{1}`) is the single source of
truth for which `schema_version` values this core accepts. Bump it, and
add migration notes here, whenever a **breaking** change is made (one
that would make an existing valid `config.yaml` invalid or silently
change its meaning). A purely additive, backward-compatible change (a
new optional key with a safe default) does not require a bump.

An unsupported version fails immediately and by name:
`schema_version 999 is not supported by this core (supported: [1])` —
never a confusing downstream error from a field the new version expected
but the old config doesn't have.

## 7. Security note

`load_use_case_config()` uses `yaml.safe_load()`, never `yaml.load()` or
`yaml.unsafe_load()`. Config files may originate from a project fork
someone else authored; arbitrary YAML tag execution is not an acceptable
risk for something loaded at every process boot.

## 8. Reference example

`app/custom/legal/config.yaml` is a complete, working config validated by
`tests/test_config_schema.py::test_legal_reference_config_loads_and_produces_expected_metadata_schema`.
Load it directly:

```bash
PYTHONPATH=. python3 -c "
from app.core.config import load_use_case_config
cfg = load_use_case_config('app/custom/legal/config.yaml')
print(cfg.to_metadata_schema())
"
```
