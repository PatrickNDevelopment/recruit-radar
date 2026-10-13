# Ambiguities recorded by the python-engine implementer

Each entry: the case, the reading implemented, and why. Where two readings are plausible the
other one is named so that a vector or the TypeScript engine can be compared against it.
Items marked **(affects output)** change the numbers or arrays `analyze` returns for
well-formed input; the rest only decide which malformed input is rejected.

## A. Scoring and aggregation

### A1. `T` / `|T|` is a multiset: one entry per full snapshot **(affects output)**

Spec 02 section 4: "`T` = observed_at of `mode == "full"` snapshots ... of every source that ever
supplied a source role to this company; `span_days = ... if |T| >= 2 else null`".
_Reading:_ `T` has one entry per full snapshot (processed, `<= as_of`) of every supplying source,
so two full snapshots with the same `observed_at` give `|T| = 2` and `span_days = 0`
(`change` is then `insufficient_history` with `span_days: 0`).
_Other reading:_ `T` is a set of distinct instants, giving `span_days: null` for that case.
_Why:_ "observed_at of snapshots" reads as one value per snapshot; ties on `observed_at` are
explicitly anticipated by the `(observed_at, snapshot_id)` replay order, so they are expected input.

### A2. A source "supplies" a company through its final company assignment **(affects output)**

"Every source that ever supplied a source role to this company" is evaluated after replay with
the final company assignment (latest `company_name`, merge decisions applied). All full snapshots
of such a source count, including ones that no longer list the company.

### A3. Company `last_seen` is the max `last_seen` of its _active_ canonical roles **(affects output)**

Spec 02 section 5: `"last_seen": ... /* null if never active */`. Every source role starts out
active, so a company that exists has always been active at some time; the only reading under
which the field can be `null` is "no currently active role". Implemented: `max(last_seen)` over
active canonical roles, `null` when there are none (the same quantity freshness uses).
_Other reading:_ max over all roles, never null. Company `first_seen` is the min over all
canonical roles (active or not).

### A4. Display name and aliases come from every observed posting **(affects output)**

Spec 01 section 3 / 02 section 5: display name = "the company_name of the earliest observed
posting in the company (ties: lexicographically smallest raw name)"; aliases = "distinct raw
company names of the company's postings".
_Reading:_ a company's postings are _all_ raw postings observed (every occurrence in a processed
snapshot, including ones superseded by a later duplicate in the same snapshot and earlier
spellings of a role later renamed) whose source role is assigned to the company. "Earliest" is by
snapshot `observed_at`.
_Other reading:_ only the latest raw name per source role. The tie rule in the spec (several
spellings at one `observed_at`) and the section 5 example ("3 postings ... deduped") favour the
reading above.

### A5. Canonical role display fields come from the member with the greatest `last_seen`, over all members **(affects output)**

Spec 02 section 3 does not say whether removed members compete. Implemented literally: every
member competes (ties: smallest source role key string). Canonical `last_seen` itself is the max
over active members only (or over all members when none is active), as stated.

### A6. "Keywords configured" means a non-empty `include_keywords` list **(affects output)**

`relevant` is `null` "when include_keywords empty", so an exclude-only profile has no relevance
and no scope: `role_relevance` is `no_keywords`, scope is all active roles, and the `change`
component counts every event (no title filter). A keyword that normalizes to the empty string
(`"!!!"`) counts as configured but never matches (`token_sequence_match` requires a non-empty
phrase).

### A7. `relevant_roles` with keywords but no active role is `0`

The spec only says `null` without keywords. With keywords configured and `A = 0` the count of
relevant active roles is `0`; `role_relevance.inputs.relevant` is `null` there, as specified.

### A8. `no_scope_roles` inputs

Spec: "the other computable inputs stay filled". Implemented: urgency `{aged: 0, known: 0,
threshold_days: 45}`; source_confidence `{scope_roles: 0, corroborated: 0}`; volume is _computed_
(value 0, not null) because its only null reason is `no_active_roles`.

### A9. `stats.snapshots`

Number of snapshots processed (those with `observed_at <= as_of`), consistent with
`postings_observed`, which the spec defines over processed snapshots.

## B. Identity

### B1. Canonical key of a merge group is its smallest _present_ member **(affects output)**

Spec 01 section 3: "The canonical key of a merged group is its lexicographically smallest member
key." A decision may name a key that no posting produces (stale decision). Such a key still links
the groups it connects (union-find transitivity) but is never chosen as the canonical key, so
`company_id` is always derived from a key that exists in the data.

### B2. `not_same` is matched against the compared (group canonical) keys **(affects output)**

Spec 01 section 3: pairs are compared by group canonical keys and emitted unless "marked
not_same". Implemented: the pair `(a_key, b_key)` of the two canonical keys is looked up in the
`not_same` set. A `not_same` decision recorded against a non-canonical member key of a merged
group therefore does not suppress the candidate between the merged groups.

### B3. `token_overlap` eligibility

"both have >= 2 tokens" is the number of tokens in the key (a key such as `x x` has 2); the
overlap ratio itself uses token _sets_, as the spec emphasises.

### B4. Source role key string

Where the spec orders "source role key strings" the key parts are joined with `|` (the separator
the spec uses for `role_id` and `candidate_id`), e.g. `greenhouse|acme|id|123` and
`csv|leads|k|acme|engineer|new ny york`. Ties on the string fall back to the tuple.

### B5. Matching titles/locations use the source role's _current_ values

Canonical grouping uses the `title_key`/`location_key` of the latest title/location of each
source role (the tracked fields), so a rename moves the role to a new canonical role id, as the
spec's note about `role_id` changing implies.

## C. Normalization

### C1. `title_key` removal procedure

"repeatedly remove `\([^()]*\)` and `\[[^\[\]]*\]` segments until none remain": segments are
_deleted_ (not replaced by a space), one pass applies the parenthesis pattern then the bracket
pattern, and passes repeat until the text stops changing. Inputs where the two patterns overlap
in conflicting ways (for example `([x)y]`) are order dependent; the order above is used.

### C2. "Trim"

Strings are trimmed with ECMAScript `String.prototype.trim` semantics (WhiteSpace +
LineTerminator, including U+FEFF, excluding U+0085 and U+001C..U+001F), because the TypeScript
engine can only use `trim()`. Python's `str.strip()` differs on those code points.

### C3. Lengths are counted in code points

The 200/300 character limits count Unicode code points; JavaScript `.length` counts UTF-16
units, so astral characters (emoji) count once here and twice there. Only matters at the limit.

### C4. `sha12` of lone surrogates

Lone surrogates cannot be UTF-8 encoded; they are replaced by U+FFFD before hashing, which is
what `TextEncoder` does, so degenerate input hashes the same in both engines.

## D. Input validation (decides which malformed input is rejected)

### D1. Which top-level keys are required

Only `as_of` is marked required. `profile`, `decisions` and `snapshots` default to an empty
profile / empty lists; a snapshot's `postings` defaults to `[]`. Unknown keys anywhere are
rejected (`extra="forbid"`).

### D2. Posting `source_kind` / `source_ref`

Spec 02 shows postings as "RawPosting without observed_at" while the snapshot already carries
`source_kind`/`source_ref`. Both fields are accepted on a posting but optional; when present they
must equal the snapshot's, otherwise the input is invalid.

### D3. `source_posting_id` may be `null` for any source kind

Spec 01 says "null allowed for csv/manual" without forbidding it elsewhere; the source role key
rules are defined for any kind, so a `null` id is accepted for ATS sources too.

### D4. Empty strings

`""` (after trimming) for any optional posting field, including `work_mode` and
`source_posting_id`, means `null`; `work_mode` `null` means `unknown`. `work_mode` is
case-sensitive (`Remote` is invalid).

### D5. `url`

Only the scheme is validated (`http:` or `https:`, ASCII case-insensitive, after trimming); no
further URL grammar is enforced and no length limit is applied.

### D6. `posted_at`

Exactly `YYYY-MM-DD` with ASCII digits, a real Gregorian date, year 0001..9999 (year `0000` is
rejected because Python's `date` has no year 0).

### D7. Decisions

`a_key < b_key` (code point order, strict) is enforced; a violating decision is an input error
rather than being silently swapped. Duplicate or contradictory decisions for one pair are
accepted: all `merge` decisions union, all `not_same` decisions suppress.

### D8. Snapshot validation

`snapshot_id` must be non-empty and unique (compared verbatim, not trimmed); `source_ref` is
trimmed and must be 1..200 characters. Snapshots after `as_of` are ignored for analysis but are
still validated, so an invalid posting inside a future snapshot is an input error.

### D9. Keyword lists

No count/length limit is applied by the engine (those belong to the API profile endpoint).

## E. Tooling note (not a spec ambiguity)

`backend/pyproject.toml` starts with a UTF-8 byte order mark. Python's `tomllib` (used by pytest
and mypy) rejects it ("Invalid statement (at line 1, column 1)"), so pytest cannot start from the
backend tree and mypy ignores the file (including the pydantic plugin). Ruff tolerates it. The
file was outside the python-engine assignment and was left untouched; verification used a
BOM-free copy of the same settings.
