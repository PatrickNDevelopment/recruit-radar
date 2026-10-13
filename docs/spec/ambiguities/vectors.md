# Spec ambiguities found while writing the golden vectors (role: `vectors`)

Written by the vectors role, from `docs/spec/00-02` only (no engine code was read). For every place where
the spec text admits more than one reading this file records: the case, **the reading the oracle
(`contracts/tools/oracle.py`) implements** ("literal" = the most literal reading), the alternatives, and
how the committed vectors relate to it.

Vectors are protected in two ways:

- **Machine-checked insensitivity** (`oracle.py --self-check`): the oracle has a switch for each alternative
  reading marked "switch" below; the self-check re-runs all 44 analysis vectors under every alternative and
  fails if any vector's `expected` changes. So _no committed vector depends on those ambiguities_, and an
  engine that took the other reading still passes every vector.
- **Excluded by construction**: cases marked "excluded" are rejected by the oracle's input validator, so no
  vector can contain them.

Where a vector _does_ depend on a reading it is called out ("dependent"). If the lead decides a different
reading, change `contracts/tools/oracle.py` (one place) and run `generate_vectors.py`; the self-check lists
exactly which files change.

> Note on location: `docs/spec/00-overview.md` says to append to `docs/spec/AMBIGUITIES.md`; the task for this
> role said to write `docs/spec/ambiguities/<role>.md`. This file follows the task. The lead may want to
> reconcile the two conventions.

## Summary

| #    | Spec location     | Question                                                                                     | Oracle reading                                 | Vectors                                                          |
| ---- | ----------------- | -------------------------------------------------------------------------------------------- | ---------------------------------------------- | ---------------------------------------------------------------- |
| A-01 | 01 s4, 02 s2      | separator of "the joined key" string                                                         | `\|`                                           | switch, insensitive                                              |
| A-02 | 01 s2 `title_key` | order of `( )`/`[ ]` stripping when they interleave                                          | parens, then brackets, repeat                  | switch, insensitive; excluded                                    |
| A-03 | 01 s2 `title_key` | "remove" = delete or replace by space                                                        | delete                                         | switch, insensitive for analysis; **normalization.json depends** |
| A-04 | 01 s3             | does `not_same` match raw keys or canonical keys of merged groups                            | raw (literal)                                  | switch, insensitive                                              |
| A-05 | 01 s3             | decisions that name a company key no posting has                                             | absent keys join groups and may be canonical   | switch, insensitive                                              |
| A-06 | 01 s3             | "both have >= 2 tokens": token count or distinct tokens                                      | token count                                    | switch, insensitive                                              |
| A-07 | 02 s4             | `T`: set of timestamps or one per snapshot                                                   | set                                            | switch, insensitive                                              |
| A-08 | 02 s3             | display fields "from the member with the greatest last_seen": all or active members          | all members                                    | switch, insensitive                                              |
| A-09 | 01 s3, 02 s5      | `name`/`aliases`: all postings (incl. superseded, historical) or latest only                 | all postings                                   | switch, insensitive                                              |
| A-10 | 02 s2             | title carried by a `reappeared` event                                                        | the new (re-listed) title                      | switch, insensitive                                              |
| A-11 | 02 s5             | company `first_seen` is undefined                                                            | min over all canonical roles                   | informational: 2 vectors                                         |
| A-12 | 02 s5             | company `last_seen` "null if never active"                                                   | max over active roles; null iff no active role | dependent (all)                                                  |
| A-13 | 02 s3             | `relevant` of a _removed_ role                                                               | computed from title                            | informational: 1 vector                                          |
| A-14 | 02 s3-4           | `exclude_keywords` without any include keyword                                               | not exercised                                  | excluded                                                         |
| A-15 | 02 s3             | a keyword that normalizes to `""`                                                            | not exercised                                  | excluded                                                         |
| A-16 | 02 s1             | posting-level `source_kind`/`source_ref` vs the snapshot's; "RawPosting without observed_at" | always equal; all 10 fields present            | excluded                                                         |
| A-17 | 01 s1, 02 s1      | does `analyze` trim inputs                                                                   | inputs are pre-trimmed                         | excluded                                                         |
| A-18 | 02 s5             | `stats.snapshots`                                                                            | count of _processed_ snapshots                 | dependent (1 vector)                                             |
| A-19 | 02 s4             | inputs of `no_scope_roles` components                                                        | empty-set counts (`0`), not `null`             | dependent (2 vectors)                                            |
| A-20 | 01 s4             | do removed source roles take part in cross-source matching                                   | yes (all source roles)                         | dependent (strongly implied)                                     |
| A-21 | 01 s2/3, 02       | an empty company/title/location key                                                          | valid key `""`                                 | dependent (1 vector)                                             |
| A-22 | 02 s2             | `company_id`/`role_id` on events                                                             | final ids after replay                         | dependent (all)                                                  |
| A-23 | 02 s4             | `volume`/`role_relevance` when scope is empty                                                | real `0`, counted in coverage                  | dependent                                                        |
| A-24 | 01 s2             | first argument of `token_sequence_match`                                                     | an already-built `title_key`                   | by definition                                                    |

---

## A-01 Joined source role key

`01 s4`: "sort each source's role keys ascending (string compare of the joined key)"; `02 s2`: "ascending
source-role-key string order". No separator is given. The only other joins in the spec use `|`
(`role_id`, `candidate_id`), so `|` is used. It matters only when one component is a prefix of another at a
word boundary (e.g. null-id roles titled `engineer` and `engineer senior`, or two source refs `acme` and
`acme-2`): `|` (0x7C) sorts after ` ` and `-`, while NUL/tuple comparison sorts the shorter first.
Affects: removal event order and the `i`-th matching within a group. **Switch** `key_sep` tried with
`\x00 \x1f / :` - no vector changes. Vectors deliberately use id-keyed roles, or keys that differ before
any separator, for multi-role removals.

## A-02 Interleaved brackets in `title_key`

"repeatedly remove `\([^()]*\)` and `\[[^\[\]]*\]` segments until none remain" does not say in which order
the two patterns are applied inside one pass. For properly nested or unbalanced input every order agrees. For
_interleaved_ input it does not:

| title                | parens then brackets (oracle) | brackets then parens | one combined alternation |
| -------------------- | ----------------------------- | -------------------- | ------------------------ |
| `Engineer (A [B) C]` | `engineer c`                  | `engineer a`         | `engineer c`             |
| `Engineer [A (B] C)` | `engineer a`                  | `engineer c`         | `engineer c`             |

**Excluded**: no vector (analysis or normalization) contains interleaved brackets. **Switch**
`bracket_mode` - no vector changes. Recommend the lead pin one order in the spec.

## A-03 "Remove" = delete (dependent)

`title_key("Data(Science)Engineer")` is `dataengineer` if the segment is deleted and `data engineer` if it is
replaced by a space. The spec says _remove_ (and, for `norm_text`, explicitly says "replace ... by a single
space"), so deletion is the literal reading. **normalization.json `title_key-009` depends on it.** The
analysis vectors do not (switch `bracket_replace`, no change): every bracketed segment there is surrounded by
spaces. If the lead picks "replace by space", regenerate and update that one case.

## A-04 `not_same` matching

`01 s3.4` emits a candidate "if ... not marked `not_same`" for a pair of _canonical_ keys. A decision names
raw keys. Reading: the pair is hidden iff a `not_same` decision names exactly that pair of canonical keys.
Alternative: map both decision keys to their group's canonical key first. They differ when a `not_same`
decision names a non-canonical member of a merged group. **Switch** `not_same=mapped` - no vector changes
(the decisions in the vectors use canonical keys of their final groups).

## A-05 Decisions naming absent keys

A `merge` decision may name a key that currently has no posting (e.g. after a source was deleted).
Literal union-find over "keys" makes it a member and possibly the _canonical_ key (a company whose `key`
matches no posting). Alternatives: ignore such decisions; or let them link present keys transitively but pick
the canonical key among present members. **Switch** `dangling` - no vector changes; no vector contains a
dangling decision.

## A-06 Token count for `token_overlap`

"both have >= 2 tokens and `|A n B|*100 >= 75*|A u B|` (token sets)". Keys with repeated tokens (`go go`)
make "has >= 2 tokens" ambiguous (list length vs. set size). Reading: list length. **Switch**
`overlap_tokens=set` - no vector changes.

## A-07 `T` as a set

`T = observed_at of full snapshots ...; span_days = days(min T, max T) if |T| >= 2`. If two sources have a
full snapshot at the _same instant_, `|T|` is 1 (set) or 2 (multiset, then `span_days = 0` instead of
`null` in `change.inputs`). Reading: set. **Switch** `T=multiset` - no vector changes (vectors never give two
related full snapshots the same `observed_at`; `snapshot-order-id-tiebreak` uses different companies).

## A-08 Display member

"display fields ... from the member with the greatest `last_seen`": the member could be a _removed_ source
role whose last listing is later than every active member's. Reading: all members (literal). Alternative:
prefer active members when the canonical role is active. **Switch** `display_members` - no vector changes.

## A-09 Names and aliases

`aliases` = "distinct raw company names of the company's postings"; name = "earliest observed posting".
Reading: every posting of every source role assigned to the company, including postings superseded by a
later duplicate in the same snapshot and names a role had in earlier snapshots. Alternative: only each
role's latest posting. **Switch** `names=latest_only` - no vector changes (vectors never rename a company on
the same posting id or give conflicting names to duplicates).

## A-10 `reappeared` title

`02 s2` lists "event `reappeared`" _before_ "update fields", while events carry the "title at event time".
Reading: the title in the re-listing snapshot. **Switch** `reappeared_title=old` - no vector changes
(the reappearance vector keeps the title).

## A-11 Company `first_seen`

Not defined in `02`. Reading: earliest `first_seen` over all of the company's canonical roles (active or
removed). Alternative: active roles only. **Informational**: would change
`additive-snapshot-never-removes` and `change-title-scope-filter` (companies whose earliest role is removed).

## A-12 Company `last_seen`

`02 s5` says "null if never active", which cannot literally happen (a role is created active). Reading:
latest `last_seen` among the company's _active_ canonical roles, null iff it has none - consistent with
`freshness` ("max last_seen over A"). Every vector depends on it (`all-roles-removed` shows the null).

## A-13 `relevant` on removed roles

`02 s3` defines `relevant` for "each canonical role" without a status condition. Reading: computed for
removed roles too (not null). **Informational**: only `change-title-scope-filter` changes (switch
`relevant_removed=null`).

## A-14 / A-15 Keyword corner cases (excluded)

- `include_keywords = []` with a non-empty `exclude_keywords`: `relevant` is null (02 s3) but 02 s4 `change`
  says "every event when no keywords are configured", so it is unclear whether exclude still filters events.
- A keyword such as `"!!!"` normalizes to `""` and never matches, but the _list_ is non-empty, so keywords
  are "configured" (every role not relevant) under the literal reading; an engine might treat it as absent.
  The oracle's input validator rejects both, so no vector contains them. Recommend resolving in the spec.

## A-16 Posting-level source fields (excluded)

`02 s1` says postings are "RawPosting without observed_at", but `RawPosting` (01 s1) has no `observed_at`
and _does_ contain `source_kind`/`source_ref`, which the snapshot also carries. Vectors always give a
posting the same `source_kind`/`source_ref` as its snapshot and always include all ten fields
(`null`s explicit). What an engine does when they disagree is untested.

## A-17 Trimming (excluded)

`01 s1` says strings are trimmed; `02 s2` compares "raw trimmed values". Reading: trimming is the
intake layer's job and `analyze` receives trimmed values. Vectors never contain untrimmed fields (the
validator enforces it). (Python `strip()` and JS `trim()` also disagree on U+FEFF and U+001C-U+001F,
which is one more reason not to test it.)

## A-18 `stats.snapshots`

Not defined; only `postings_observed` is ("across processed snapshots (after the as_of filter)").
Reading: number of processed snapshots (snapshots after `as_of` are "ignored entirely"). Dependent:
`snapshots-after-as-of-ignored` (`stats.snapshots` is 2, not 4).

## A-19 Inputs of `no_scope_roles`

"the other computable inputs stay filled". With keywords configured and nothing relevant, the counts over
the empty scope are real values: urgency `{aged: 0, known: 0}`, confidence `{scope_roles: 0, corroborated:
0}` (versus `null`s in the `A == 0` case). Dependent: `no-scope-roles`, `empty-keys`.

## A-20 Removed source roles in matching

`01 s4` matches all source roles of a `(company, title_key, location_key)` group, and `02 s3` speaks of
"any member ... active" and of "_active_ observations", which only makes sense if removed members belong to
the canonical role. Reading: removed source roles take part in matching. Dependent:
`corroboration-needs-two-active-observations` (one canonical role with a removed and an active observation).
Low risk, recorded for completeness.

## A-21 Empty keys

`RawPosting` only requires a non-empty raw name; `!!!` normalizes to `""`. Reading: `""` is an ordinary key
(`company_id = c_ + sha12("")`, i.e. `c_e3b0c44298fc`); an empty `title_key`/`location_key` is an ordinary
group component (and a null location equals `"???"`). Dependent: `empty-keys`. An engine that treats an
empty key as "no company" would diverge there.

## A-22 Final ids on events

Events carry `company_id`/`role_id`; identity "is resolved after replay so merges apply to history", so the
ids are the _final_ ones (a renamed role's baseline event carries the id derived from its new title).

## A-23 Real zeros

`volume` is `table[min(|scope|,10)]` so an empty scope yields a computed `0` (weight 20 counted in
`coverage`); `role_relevance` is `rhu(0, |A|) = 0` when nothing matches. Only `no_active_roles`,
`no_keywords`, `insufficient_history`, `no_scope_roles` and `no_dated_roles` are nulls.

## A-24 `token_sequence_match` input

`token_sequence_match(title_key, phrase)`: the vectors pass an already-built `title_key` (they assert
`title_key(title) == title`), so engines that re-normalize and engines that don't agree.

---

## Observations that are not ambiguities but are worth knowing

- A company with less history can outrank one with more: `change-span-14-vs-13` ranks `yankee yards`
  (coverage 45, score 681) above `xray xylem` (coverage 60, score 661) because missing components are
  excluded from `W` rather than scored as zero. This is what the spec says ("never scored as zero"); the UI
  should show `coverage` next to the score.
- The ambiguity switches live in `oracle.py` (`READINGS`) so a decision by the lead is a one-line change
  followed by `generate_vectors.py` and `oracle.py --self-check`.
