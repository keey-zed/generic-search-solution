# Frontend Control Mapping (Phase 5, item 1)

This document specifies **Phase 5, item 1**: "define the config →
UI-control mapping (date range picker, dropdown, text filter, etc., per
§10's example) as an explicit table, not implicit convention."

**What already existed** (built during the config schema work, Phase
0/2): `app/core/config/models.py`'s `DEFAULT_CONTROL`/`ALLOWED_CONTROLS`
tables and `docs/config-schema.md`'s "Control resolution" section
already make the type+operation → control-name mapping explicit and
tested (`test_every_default_control_pair_covers_all_compatible_type_operations`).
That part of item 1 was already done.

**What this document adds**: the piece a frontend developer actually
needs to build item 2's components — for each control name, what it
renders as, and critically, the **exact payload shape** selecting a
value must produce to be a valid `Filter.apply()` call
(`docs/filtering.md` §3). This wasn't written down anywhere yet; without
it, "the config says `control: date_range`" doesn't tell a frontend
developer what shape to send back to the API.

This document is deliberately framework-agnostic (no Angular/React
specifics) — it's the contract, not an implementation. The actual
frontend implementation (items 2–4: real components, branding wiring,
pilot validation) is separate future work, and belongs to whichever
codebase owns the frontend (a different repo than this one, per the
roadmap's note that "front-end code already exists").

```bash
PYTHONPATH=. python3 -m pytest tests/test_frontend_control_mapping.py
```

## The full mapping, with payload contracts

| Control | Renders as | `frontend.filters[name]` fields used | Payload shape sent as this field's filter value |
|---|---|---|---|
| `text` | Free-text input | `label`, `placeholder` | A string. Sent as-is; substring search is case-insensitive server-side (`docs/filtering.md` §3). |
| `dropdown` | Single-select list | `label`, `placeholder` | A single string/int/float (whichever the field's `type` is) — **or** a list of them if the control allows multi-selection (a project may choose to let a `dropdown` emit several values; `equality`'s OR semantics accept either shape). |
| `radio` | Single-select, all options visible at once | `label` | A single scalar value — never a list. Radio is exclusive-choice by construction. |
| `date` | Single date picker | `label`, `placeholder` | An ISO-8601 date string (`"YYYY-MM-DD"`), or a list of such strings for OR semantics. |
| `date_range` | Two date pickers ("from"/"to"), or one range picker widget | `label` | `{"min": "YYYY-MM-DD", "max": "YYYY-MM-DD"}` — either key may be omitted if that bound isn't set. Add `"min_inclusive"`/`"max_inclusive"` (booleans) only if the UI exposes inclusive/exclusive toggles; omit them to get the default (both inclusive). |
| `number` | Single numeric input | `label`, `placeholder` | A single int/float, or a list of them for OR semantics. |
| `number_range` | Two numeric inputs ("min"/"max"), or a slider | `label` | `{"min": <number>, "max": <number>}` — same shape as `date_range`, numeric bounds instead of date strings. |
| `checkbox` | Single checkbox (on/off) | `label` | `true` or `false`. Omit the field entirely (don't send `false`) if the UI's "unchecked" state should mean "no filter applied" rather than "explicitly filter for false" — these are different things (see `docs/filtering.md` §2: empty/absent params is a no-op). |
| `toggle` | Single on/off switch | `label` | Same contract as `checkbox` — purely a visual choice between the two, not a behavioral one. |
| `multi_select` | Multi-select list (dropdown-with-checkboxes, tag input, etc.) | `label`, `placeholder` | A list of strings (or whatever `item_type` is for a `list` field). An empty list or omitting the field entirely both mean "no restriction" — same convention as every other control. |
| `checkbox_group` | A visible group of checkboxes, one per option | `label` | Same shape as `multi_select` — purely a visual choice between the two for `list`+`contains` fields. |

## Reading this table together with `docs/config-schema.md`

For a given field, resolve its control in two steps:

1. Look up `(type, operation)` in `DEFAULT_CONTROL`/`ALLOWED_CONTROLS`
   (`docs/config-schema.md`'s "Control resolution" table) to get the
   control name — this is enforced by config validation, not something
   a frontend needs to re-derive.
2. Look up that control name in the table above to know what to render
   and what payload shape to send back.

Example, using `app/custom/legal/config.yaml`'s `publication_date`
field (`type: date`, `operation: range`):

- Step 1: `(date, range)` → default control `date_range`.
- Step 2: `date_range` → render two date pickers; on submit, send
  `{"publication_date": {"min": "2020-01-01", "max": "2020-12-31"}}` as
  part of the search request's `filters` — this is exactly the shape
  `RangeFilter.apply()` already expects (`docs/filtering.md` §3), with
  zero translation needed on the backend side.

## Branding and non-filter frontend fields

Not covered by the control table above, since they're not filter
controls: `frontend.branding.*` (title, subtitle, logo, colors, search
placeholder) map directly to top-level presentation elements, one field
each, no widget-selection logic involved. `result_card_fields` (where
declared) lists which metadata fields to show in a result card, in
order — a display concern, not an input control. Wiring these into
actual components is Phase 5, item 3.

## What's deliberately not built here

- **Actual UI components.** This is a contract/spec document, not code.
  Phase 5, item 2.
- **Branding/result-card component wiring.** Phase 5, item 3.
- **Validation against a real pilot's rendered UI.** Phase 5, item 4 —
  needs the Phase 4 pilot's real `config.yaml` and an actual frontend to
  render it in, neither of which this document depends on.
- **A machine-readable export of this contract** (e.g., an API endpoint
  serving `frontend:` config as JSON for a remote frontend to consume,
  per source doc §5: "the frontend should also read or receive the same
  configuration"). `UseCaseConfig` is already a Pydantic model
  (`model_dump()` produces this JSON directly) — exposing it over the
  API is a small addition but belongs with the actual API/frontend
  wiring work (items 2–3), not this contract document.