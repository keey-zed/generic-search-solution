# Custom vs. Generic — When Does Something Belong in the Custom Layer?

This document specifies **Phase 3, item 3**: codifying the promotion
rule from source doc §4, so a future contributor doesn't have to guess
whether something they need belongs in `custom_filters.py` or in
`app/core/filtering/`.

Read `app/custom/_template/README.md` first if you're setting up a new
project — that's the step-by-step guide. This document answers one
narrower question: *once you're building something, where does it go?*

## §4, the rule, quoted directly

> If we encounter a filter that is genuinely specific to one
> application, we can implement it in the custom layer... Initially,
> such functionality could be implemented as a custom operation for the
> [one] application. If we later realize that fuzzy matching is useful
> across many applications, we can promote it into the generic core.
>
> **Start use-case-specific functionality in the custom layer, and move
> it into the generic layer once it proves sufficiently reusable.**

Two things follow directly from this, and both matter as much as the
rule itself:

1. **Default to custom.** Nothing gets added to `app/core/` on a "this
   seems generally useful" guess — only after a second, independent
   project actually needs it.
2. **Promotion is deliberate, not automatic.** A generic core change
   affects every project's next repo-copy sync (see Phase 6's changelog
   convention) — it's a reviewed decision, not something that happens
   just because a pattern repeated once.

## The decision procedure

Ask these in order; stop at the first "yes."

**1. Can an existing generic filter already do this correctly, as-is?**
→ Use it directly in `config.yaml`. No code, custom or otherwise.
Check `docs/filtering.md` §3's type→operation table before assuming it
can't — `EqualityFilter`/`RangeFilter`/`ContainsFilter` cover more than
it looks like at a glance (e.g. `RangeFilter`'s independent
`min_inclusive`/`max_inclusive` per bound, or `equality`'s built-in
OR-across-multiple-values).

**2. Does only THIS project need behavior a generic filter can't
express — a different matching rule for the same operation, applied to
one specific field?**
→ Custom layer. Write one class in `custom_filters.py`, following
`app/custom/_template/`'s pattern. This is the common case, and it's
meant to be — see `docs/override-mechanism.md` for the mechanics
(same declared `operation`, different implementation, scoped to one
field).

**3. Has a SECOND, independent project now built essentially the same
custom filter for essentially the same reason?**
→ That repetition **is** the promotion signal (§4's own words: "if we
later realize... useful across many applications"). Generalize it into
`app/core/filtering/filters.py` as a new built-in operation (or a
configurable parameter on an existing one, if that's a better fit —
see the fuzzy-matching example below). Once promoted, each project's
now-redundant custom class gets replaced by the generic one, not kept
alongside it.

**4. Are you tempted to special-case a field name inside
`app/core/`?** (`if field == "title": ...`)
→ Stop. This is never the answer, at any point in the procedure above.
A generic core file that knows a specific field name has stopped being
generic. If the behavior is genuinely one-project-specific, it belongs
in that project's `custom_filters.py` (step 2). If it's genuinely
reusable, it belongs in core as a *parameterized*, field-agnostic
capability (step 3) — not as a hardcoded exception for one field.

## Worked examples from this codebase

### Staying custom: legal's `document_type` field (this deliverable)

`app/custom/legal/case_insensitive_equality_filter.py` — legal's raw
data occasionally has `document_type` values typed with inconsistent
case (`"Dahir"` vs `"dahir"`), and the generic `EqualityFilter` is
exact-match, so a query for `"dahir"` would silently miss a record
stored as `"Dahir"`. This is exactly step 2: one project, one field,
generic filter genuinely insufficient. No other project has hit this
yet, so it stays in legal's custom layer — it does **not** get promoted
just because case-insensitivity sounds broadly useful in the abstract.
(If it turns out several projects independently want case-insensitive
equality as a general capability, *that's* when step 3 applies — and at
that point, note that `ContainsFilter` already treats string matching as
case-insensitive by default per `docs/filtering.md` §3, which is a clue
that "case-insensitive equality" might really be "promote a
`case_sensitive: bool` option onto the generic `EqualityFilter`" rather
than a wholesale new operation.)

### Staying custom, but closer to the line: books' fuzzy title matching

`app/custom/books/fuzzy_title_filter.py` (Phase 3, item 2) is a stronger
promotion candidate than the example above — the *technique* (normalize
+ sliding-window similarity ratio) is entirely domain-agnostic; nothing
about it is books-specific except which field it's applied to. It stays
custom for now purely because only one project has needed it. The
moment a second project independently wants approximate text matching
on some field, that's the concrete trigger for step 3: promote a
generalized `FuzzyContainsFilter` (matching algorithm and threshold as
constructor parameters, not hardcoded) into
`app/core/filtering/filters.py`, and update both projects'
`custom_filters.py` to stop registering their own copies.

### What NOT to do: promoting after one use case

It would be premature to move either example above into `app/core/`
today, even though both are well-written and arguably "obviously"
generally useful. One data point isn't a pattern — §4 says "if we later
realize," not "if we can imagine." Promoting speculatively costs real
things: it adds surface area to `app/core/` (more to test, document, and
keep backward-compatible) for a feature that might turn out to only
ever have one real caller, and it's exactly the kind of core change that
Phase 6's changelog/back-port process exists to make expensive to get
wrong across every repo copy. When in doubt, leave it in the custom
layer — moving it later is cheap; un-generalizing a bad abstraction
later is not.

## If you're still not sure

Default to the custom layer. It's the reversible choice — promoting
later costs one small, reviewed core change; promoting prematurely and
having to walk it back costs more (a core API change, potentially a
breaking one, propagated back through every project that already copied
the old shape). The custom layer is deliberately cheap to use for
exactly this reason.