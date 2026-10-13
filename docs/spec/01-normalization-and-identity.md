# 01 — Records, normalization, company identity, role dedup

## 1. RawPosting (what adapters / CSV / manual entry produce)

| field | type | rules |
|---|---|---|
| `source_kind` | `"greenhouse" \| "lever" \| "ashby" \| "csv" \| "manual"` | required |
| `source_ref` | string | required, 1..200 after trim. ATS: board token/site/board name. csv/manual: dataset label |
| `source_posting_id` | string \| null | stable id *within* (source_kind, source_ref); null allowed for csv/manual |
| `company_name` | string | required, 1..200 after trim |
| `title` | string | required, 1..300 after trim |
| `location` | string \| null | ≤300 |
| `work_mode` | `"remote" \| "hybrid" \| "onsite" \| "unknown"` | default `unknown` |
| `department` | string \| null | ≤200 |
| `url` | string \| null | only `http:`/`https:` schemes; anything else is rejected (field invalid) |
| `posted_at` | `"YYYY-MM-DD"` \| null | must be a real calendar date |

Strings are trimmed; internal whitespace is preserved in display fields (keys are derived separately).
An empty string for an optional field means null.

## 2. Normalization (identical in both engines)

**`norm_text(s)`**: (1) Unicode NFKC; (2) lowercase using the language's default (non-locale)
lowercasing (`str.lower()` / `toLowerCase()`); (3) replace every code point whose Unicode general
category does NOT start with `L`, `N` or `M` by a single space; (4) split on whitespace, drop empties,
join with one space. Result may be `""`.

**`company_key(name)`**: tokens = `norm_text(name)` split on space. Repeatedly drop a *trailing* token
that is in the legal-suffix set {inc, incorporated, llc, ltd, limited, corp, corporation, co, company,
gmbh, plc, ag, sa, bv, nv, llp, lp, pte, pty}, then drop a single leading token `the`. If that leaves
no tokens, use the original token list. Key = tokens joined by one space.
Examples: `"Acme, Inc."→"acme"`, `"The Acme Corporation"→"acme"`, `"Inc"→"inc"`, `"AT&T"→"at t"`.

**`title_key(title)`**: repeatedly remove `\([^()]*\)` and `\[[^\[\]]*\]` segments until none remain,
then `norm_text`. Example: `"Senior Engineer (Remote) [US]"→"senior engineer"`.

**`location_key(loc)`**: `norm_text(loc or "")` → unique tokens → sorted ascending by code point →
joined by space. Example: `"New York, NY"` and `"NY - New York"` → `"new ny york"`.

**`token_sequence_match(title_key, phrase)`** (used by scoring): `phrase_key = norm_text(phrase)`;
true iff `phrase_key` non-empty and its tokens appear as a contiguous sub-sequence of title_key tokens.

**`sha12(s)`**: first 12 lowercase hex chars of SHA-256 of the UTF-8 bytes of `s`.

## 3. Company identity

1. `company_key` equality ⇒ same company (automatic; reason `exact_name`).
2. `company_id = "c_" + sha12(canonical_key)` where `canonical_key` is the key of the company *after*
   applying user merge decisions (below). Display name = the `company_name` of the **earliest observed**
   posting in the company (ties: lexicographically smallest raw name).
3. **User decisions** (`decisions`): list of `{a_key, b_key, decision}` with `a_key < b_key`
   (code-point order) and `decision ∈ {"merge","not_same"}`.
   - `merge`: the two keys are one company. Merges are transitive (union-find). The canonical key of a
     merged group is its lexicographically smallest member key.
   - `not_same`: suppresses the pair from the candidate list. (Does not prevent exact-name equality.)
4. **Merge candidates** (never auto-merged): for every unordered pair of *distinct* company keys
   (after applying `merge` decisions; compare group canonical keys) not marked `not_same`, emit a
   candidate if ANY holds, reported with the first matching reason in this order:
   - `spacing_variant`: keys equal after removing all spaces;
   - `token_overlap`: both have ≥2 tokens and `|A∩B|*100 >= 75*|A∪B|` (token *sets*);
   - `near_typo`: both keys have ≥6 code points and Levenshtein distance ≤1.
   Candidate fields: `a_key`, `b_key` (a<b), `a_name`, `b_name` (display names), `reason`,
   `candidate_id = sha12(a_key + "|" + b_key)`. Sorted by (reason order above, a_key, b_key).

## 4. Role identity and dedup

- **Source role key** (a role as seen by one source): if `source_posting_id` non-null:
  `(source_kind, source_ref, "id", source_posting_id)`; else
  `(source_kind, source_ref, "k", company_key, title_key, location_key)`.
- **Canonical role** = one real-world opening, possibly corroborated by several sources.
  Cross-source match: two source roles from *different* `(source_kind, source_ref)` pairs match iff
  same company (after merges), same `title_key`, same `location_key`.
  Within one source, distinct source role keys are *never* merged (two headcounts stay two roles).
  Matching is one-to-one and deterministic: for each (company, title_key, location_key) group, sort
  each source's role keys ascending (string compare of the joined key); canonical role *i* (0-based)
  consists of the *i*-th role of every source that has at least *i+1* roles in the group. Sources are
  processed in ascending `(source_kind, source_ref)` order.
- `role_id = "r_" + sha12(canonical_key_string)` where `canonical_key_string` is
  `company_id + "|" + title_key + "|" + location_key + "|" + i` using the group index *i*.
  (Therefore a rename changes `role_id` of the canonical role; the *source role key* persists and the
  rename is reported as an event — see 02.)

## 5. Consequences that must be tested
- Same company spelled `Acme`, `ACME Inc.`, `acme, inc` ⇒ one company, 3 postings ⇒ roles deduped.
- `DoorDash` / `Door Dash` ⇒ two companies + one `spacing_variant` candidate (not merged until the user decides).
- `Acme Robotics` / `Acme Robotic` ⇒ `near_typo` candidate.
- Identical title+location in the same source with different posting ids ⇒ 2 roles, 2 headcount.
- Same title+location in a greenhouse board and a csv dataset ⇒ 1 canonical role, 2 observations.
