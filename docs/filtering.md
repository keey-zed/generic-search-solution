# Generic Filtering Framework

This document specifies **Phase 1, Track B, Tasks 2 and 4**: the generic
`Filter` interface, its three built-in implementations (range, equality,
contains), and the registration mechanism that lets new filter types be
added without editing a big if/elif chain.

Read `docs/metadata-typing.md` first — everything here operates on the
typed metadata that layer produces (`NormalizedDocument.metadata` /
`IngestedDocument.metadata`), and reuses its type vocabulary and
type→operation compatibility table directly rather than redefining
either.

```bash
PYTHONPATH=. python3 -m pytest tests/test_filters.py tests/test_filtering_registry.py
```

Track B's Definition of Done is verified as one end-to-end acceptance
test in `tests/test_track_b_definition_of_done.py` — a fake YAML config
and a fake set of raw records run through ingestion, config-driven
filter construction, and every filter type in one pass, including all
four named edge cases (missing field, wrong type, empty filter list,
malformed config). Everything else in this document is covered in more
depth by the other `tests/test_*.py` files; that one file exists purely
to demonstrate the whole pipeline working together the way the DoD
describes it.

## 1. The shared interface

```python
class Filter(ABC):
    operation: ClassVar[str]

    def __init__(self, field_type: MetadataFieldType, item_type: Optional[MetadataFieldType] = None): ...

    @abstractmethod
    def apply(self, records: Sequence[NormalizedDocument], field: str, params: Any) -> list[NormalizedDocument]: ...
```

- One **Filter instance is built per declared config field** — it's
  constructed once, from that field's `type` (and `item_type` for `LIST`
  fields), and reused for every query. `apply()` only takes `records`,
  `field`, and `params`, exactly matching the source doc's interface
  sketch — the field's type doesn't need to be threaded through every
  call because the instance already knows it.
- `records` is, for v0, simply an in-memory `Sequence[NormalizedDocument]`
  — there's no query-builder/DB abstraction in this project yet, so
  `records_or_query` from the source doc's sketch is concretely "a list
  of already-ingested documents."
- This uniform shape (same three-argument `apply()` on every filter type)
  is what makes it possible for the config loader (task 3, next) to build
  a dict of `{field_name: Filter_instance}` from a YAML file and run all
  of them identically in a loop, regardless of which concrete filter
  class each one is.

### Compatibility is checked at construction, reusing one table

Every filter's `__init__` calls
`metadata_types.is_operation_compatible(field_type, self.operation)` —
the exact same table task 3's YAML loader will use to reject a bad
config at load time (§5 of `docs/metadata-typing.md`):

```python
FILTER_OPERATION_COMPATIBILITY = {
    STRING: {"equality", "contains"},
    DATE:   {"equality", "range"},
    INT:    {"equality", "range"},
    FLOAT:  {"equality", "range"},
    BOOL:   {"equality"},
    LIST:   {"contains"},
}
```

So `ContainsFilter(field_type=MetadataFieldType.BOOL)` raises
immediately — this isn't a second, competing definition of which
operations are valid for which type; it's the same one, checked in two
places (config load time, and filter construction time) as a defense in
depth against anything that builds a `Filter` without going through the
config loader.

## 2. Common conventions across all three filters

- **Empty params = no-op, not "match nothing".** `None`, `[]`, or a range
  with both bounds absent all mean "this filter wasn't applied" — the
  input records pass through unchanged. This mirrors how a UI filter
  control behaves when nothing is selected: "no doctype chosen" doesn't
  mean "match zero documents." This is also the "empty filter list" edge
  case from Track B's Definition of Done.
- **A missing/None field value never matches a non-empty filter.** A
  record can't satisfy "date between X and Y" if it has no date at all —
  it's simply excluded, not an error.
- **Multiple selected values = OR.** Passing a list of values to
  equality or contains matches a record if *any* value matches (e.g.
  several doctypes selected in a checkbox group).
- **Bad filter parameters raise `FilterError` immediately** (wrong type,
  `min > max`, an unsupported operation/type pairing) — they never
  silently produce an empty or wrong result. A malformed filter
  parameter is a bug to surface, not swallow.
- **Filters never mutate their input** — `apply()` always returns a new
  list.

## 3. The three filter types

### `EqualityFilter` (operation: `"equality"`)

Works across string / date / int / float / bool. Matches a record if its
field value equals any of the given params.

```python
EqualityFilter(field_type=MetadataFieldType.STRING).apply(
    records, "doctype", ["dahir", "marsoum"]  # OR
)
```

### `RangeFilter` (operation: `"range"`)

Works for date / int / float. `params` is a mapping:

```python
{"min": ..., "max": ..., "min_inclusive": True, "max_inclusive": True}
```

Both bounds are optional and independent — `{"min": 10}` alone means
"at least 10, no upper bound." `min_inclusive`/`max_inclusive` default to
`True`, so the default is an inclusive `[min, max]` range; set either to
`False` for an exclusive boundary on that side only.

```python
RangeFilter(field_type=MetadataFieldType.DATE).apply(
    records, "publication_date", {"min": "2020-01-01", "max": "2020-12-31"}
)
```

Date strings in `params` are coerced through the exact same strict
ISO-8601 rules ingestion uses (see §4 below) — `"01/01/2020"` is
rejected, `"2020-01-01"` is accepted.

### `ContainsFilter` (operation: `"contains"`)

Two different meanings depending on the field's declared type — this is
the one operation name that behaves differently per type, and it's
deliberate (source doc §3 calls "contains" a text-field operation; §5 of
`docs/metadata-typing.md` additionally gives `LIST` a "contains" meaning
as membership):

| `field_type` | Meaning | Case sensitivity (documented default) |
|---|---|---|
| `STRING` | Substring search | **Case-insensitive.** `"climate"` matches `"Climate Change Act"`. |
| `LIST` (needs `item_type`) | Membership — record's list contains ANY given value | Case-insensitive for `item_type=STRING`; exact equality otherwise (int/float/bool/date items). |

```python
ContainsFilter(field_type=MetadataFieldType.STRING).apply(records, "title", "climate")

ContainsFilter(field_type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING).apply(
    records, "subjects", ["finance", "health"]  # OR
)
```

`contains` is intentionally not offered for `INT`/`FLOAT`/`BOOL`/`DATE`
scalars — "substring of a number" isn't a meaningful operation, and the
compatibility table (§1 above) enforces this at construction time rather
than leaving it to produce a confusing runtime result.

## 4. Type coercion is centralized, not duplicated

A filter parameter (e.g. a date arriving as the string `"2020-01-01"`
from a request) is coerced with `_coerce_param_value()`
(`app/core/filtering/base.py`), which is a thin wrapper that:

1. Accepts a value that's already the correct native Python type as-is
   (a fast path for filters called programmatically with real `date`/
   `int` objects already in hand).
2. Otherwise delegates to `metadata_types._coerce_scalar` — the **exact
   same function** ingestion already uses to type a record's own
   metadata values (strict ISO-8601 dates, the `bool`-is-not-`int` trap,
   etc.)

This is the "type coercion ... done once, centrally" requirement from
the task: there is one set of type-coercion rules in the whole project,
applied identically to a record's stored value and to a filter's query
parameter, so they can never silently disagree about what counts as a
valid date/int/float/bool.

## 5. The registry (task 4)

```python
@register_filter("equality")
class EqualityFilter(Filter):
    operation = "equality"
    def apply(self, records, field, params): ...
```

`register_filter(operation)` is a class decorator that:

- Requires the class to declare its own `operation` attribute matching
  the decorator argument (so a class's operation is always visible in
  its own definition, never assigned invisibly by the decorator).
- Raises at class-definition time if that operation name is already
  claimed by a different class — two filters silently fighting over one
  name is a bug that should surface at import time, not "the wrong
  filter ran" deep inside a search request.

```python
get_filter_class("equality")       # -> EqualityFilter
get_filter_class("fuzzy_match")    # -> FilterError: no filter is registered for operation 'fuzzy_match' ...
list_registered_operations()       # -> ['contains', 'equality', 'range']
```

This is what lets task 3's YAML config loader stay generic — for every
declared field, regardless of which operation it names:

```python
filter_cls = get_filter_class(field_config.operation)
filter_instance = filter_cls(field_type=field_config.type, item_type=field_config.item_type)
```

...with zero knowledge of which concrete class that resolves to. Adding
a project-specific filter later (source doc §4/§6: a custom filter that
may later be promoted to generic) is a new file with one class and one
`@register_filter("...")` line — never a change to the loader or to any
other filter.

## 6. Task 3: building `Filter` instances from a config

Everything task 3 asked for except one step already existed by the time
this was built — the config layer (`app/core/config/`, a separate
teammate's Phase 0 deliverable) already handles:

- **Parsing** `config.yaml` — `load_use_case_config()`.
- **Validating** it against the schema, including **failing fast at
  config-load time** if a field declares an operation incompatible with
  its type (e.g. `contains` on an `int`) — `FilterFieldConfig`'s own
  validator, which calls the exact same `is_operation_compatible()` used
  in §1 above. One compatibility table, checked in both places.

The one missing piece — turning each validated `FilterFieldConfig` into
the actual `Filter` object that runs it — is `app/core/filtering/config_loader.py`:

```python
def build_filters_from_config(config: UseCaseConfig) -> dict[str, Filter]:
    filters = {}
    for name, field_cfg in config.filters.items():
        filter_cls = get_filter_class(field_cfg.operation)
        filters[name] = filter_cls(field_type=field_cfg.type, item_type=field_cfg.item_type)
    return filters
```

No if/elif over operation names anywhere — `get_filter_class()` (the
registry, task 4) resolves `"equality"`/`"range"`/`"contains"` (or any
future custom operation) to the right class generically.

`load_filters(path)` is the convenience entry point that combines both
steps for a project's startup code:

```python
from app.core.filtering import load_filters

config, filters = load_filters("app/custom/legal/config.yaml")

filters["doctype"].apply(records, "doctype", ["dahir"])
```

Both raise `ConfigLoadError` (the same exception type the config layer
already uses) for any failure at any stage — file not found, invalid
YAML, an incompatible type/operation pairing, or (defensively) a filter
construction problem — always naming the specific field, never a bare
stack trace.

### Fail-fast in practice

```yaml
filters:
  page_count:
    type: int
    operation: contains   # invalid: 'contains' only applies to string/list
```

```
ConfigLoadError: config file config.yaml failed validation:
1 validation error for UseCaseConfig
filters.page_count
  Value error, operation 'contains' is not compatible with type 'int'
  (allowed operations for this type: ['equality', 'range'])
```

This fails the moment the config is loaded — at process startup — not
the first time a search request happens to filter on `page_count`.

## 7. What's deliberately not built here

- **No combining of multiple fields' filters into one query.** `apply()`
  filters by one field at a time; running several fields' filters in
  sequence (`equality` on `doctype` AND `range` on `date` AND ...) for
  one search request is a later retrieval/query-orchestration
  deliverable's job, not something baked into `Filter` or the config
  loader.
- **No `NOT`/negation, no cross-field filters.** Out of scope for v0,
  same as the rest of Phase 0/1's deliberately small surface area.