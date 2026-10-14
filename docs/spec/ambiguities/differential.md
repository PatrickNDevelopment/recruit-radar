# Differential review: decisions D-1 .. D-11

Three artifacts were written independently from `docs/spec/`: the Python engine, the TypeScript
engine, and the oracle with its golden vectors. All 44 original vectors passed in both engines, yet a
seeded cross-implementation fuzz (`contracts/tools/fuzz_diff.py`) found **212 of 940 generated cases
mismatching** (90 on conforming inputs, 107 on inputs the spec allows but the vectors did not cover,
15 on accept/reject). Each distinct root cause was decided from the spec text, not from which
implementation was more convenient. After the fixes: **948 cases, 0 mismatches** across all three,
plus a 148-case accept/reject catalogue with `python == typescript` on every case and a normalization
sweep over all 1,152,198 Unicode code points (see D-0).

| id   | question                                             | decided reading                                                                                                                                                              | spec text                                    | artifact that was wrong                                                                            |
| ---- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| D-0  | Unicode database version skew                        | accepted, documented                                                                                                                                                         | 01 s2                                        | none (4,699 code points differ only because Python 3.14 ships Unicode 16 and Node 24 ICU ships 17) |
| D-1  | what "trimmed" strips                                | exactly ECMAScript WhiteSpace + LineTerminator (incl. U+FEFF); not NEL U+0085, not C0 separators                                                                             | 01 s1 "Strings are trimmed"                  | TypeScript                                                                                         |
| D-2  | `T` (full-snapshot instants): set or multiset        | **set** of distinct instants; two sources observed at the same instant give `\|T\| = 1`                                                                                      | 02 s4 "`\|T\| >= 2`, min T, max T"           | Python (vector 45)                                                                                 |
| D-3  | may a canonical key be a key no posting has any more | **yes**: the canonical key of a merged group is its smallest _member_ key, and every key a merge decision names is a member (stale decisions are valid)                      | 01 s3.3                                      | Python (vector 46)                                                                                 |
| D-4  | what a `not_same` decision names                     | **exactly the (a_key, b_key) pair**; it does not propagate through merge groups; a decision naming a non-canonical member does not hide the candidate between canonical keys | 01 s3.3/3.4 "pair ... not marked `not_same`" | TypeScript (vector 47)                                                                             |
| D-5  | unknown keys in the input                            | ignored                                                                                                                                                                      | 02 s1 shape                                  | Python (was rejecting)                                                                             |
| D-6  | whitespace-padded `as_of` / `observed_at`            | **rejected**: these are instants, not RawPosting strings, so the trim rule does not apply                                                                                    | 02 s1 "format YYYY-MM-DDTHH:MM:SSZ"          | TypeScript (was trimming)                                                                          |
| D-7  | omitted `snapshots` / `postings`                     | treated as empty; `null` is **not** an omission and is rejected                                                                                                              | 02 s1                                        | TypeScript                                                                                         |
| D-8  | `url` validity                                       | the scheme is the only constraint (`http:` / `https:`, case-insensitive); the rest of the string is stored as given                                                          | 01 s1                                        | TypeScript                                                                                         |
| D-9  | keyword limits                                       | enforced at the engine boundary (<= 50 per list, <= 60 code points after trimming; blank keywords allowed and never match)                                                   | 03 `PUT /api/profile` limits                 | Python                                                                                             |
| D-10 | posting-level `source_ref` present but empty         | invalid; `null`/absent inherit the snapshot's `source_ref`; a padded copy of the snapshot's ref agrees                                                                       | 01 s1 `source_ref` 1..200                    | Python                                                                                             |

## D-11: the CSV importers (found by the 02B acceptance review)

The differential review above covered `analyze()` only. The product has a second pair of
independent implementations nobody had compared: the CSV importers (Python `csv_io.py` for the
backend, TypeScript `csv.ts` for local-data mode), written separately from spec 05 and each tested
only against its own author's reading. The same file therefore gave different results depending on
the mode. A seeded differential fuzz of the two found **426 of 1,210 generated files** disagreeing
(70 signatures). After reducing them to single-feature probes the real differences were:

| input                                                     | Python (before)         | TypeScript (before)      | decided (spec 05 "CSV details") |
| --------------------------------------------------------- | ----------------------- | ------------------------ | ------------------------------- |
| whitespace-only or tab-only line                          | skipped                 | row rejected, 2 errors   | skipped (blank line)            |
| line holding only `""`                                    | skipped                 | row rejected             | skipped                         |
| trailing empty cells (`A,B,,`)                            | row rejected            | accepted                 | accepted                        |
| `Acme, "Senior, Engineer"` (space before quote)           | quoted field            | literal; row shifted     | quoted field                    |
| `"Acme" ,Engineer` (space after closing quote)            | accepted                | row rejected             | accepted                        |
| header `Company<TAB>Name` or with a no-break space        | file refused            | mapped to `company_name` | mapped to `_`                   |
| NUL inside a cell                                         | file refused            | stored in the name       | file refused                    |
| `''=x` / `  '=x` (apostrophes in front of a formula char) | one apostrophe lost     | exact round trip         | exact round trip (bijection)    |
| malformed header row                                      | file refused            | accepted silently        | file refused                    |
| malformed or shifted row                                  | 1 error, fields skipped | 1 error + every field    | 1 error, fields skipped         |

Both importers now implement the decided column; 52 hand-derived vectors in
`contracts/vectors/csv-import.json` pin it in both test suites, and
`contracts/tools/fuzz_csv.py` (part of `npm run fuzz`) re-runs the comparison: 0 mismatches over
seeds 1, 2, 3 (1,510 files each) after the fix. The spec 05 text was extended instead of picking
silently, as the ownership rules in spec 00 require.

## Evidence and regression coverage

- Vectors 45, 46, 47 pin D-2, D-3, D-4 with hand derivations (HC-21..23 in
  `contracts/vectors/HAND_CHECKS.md`); the pre-fix Python engine fails 45 and 46, the pre-fix
  TypeScript engine fails 47.
- D-1, D-4, D-6 .. D-10 are asserted in `backend/tests/engine/test_engine_differential.py` and its
  twin `tests/differential.test.ts` (46 cases).
- `contracts/tools/fuzz_diff.py all --seed N --count M` re-runs the three-way comparison; it exits
  non-zero on any mismatch. It is kept out of the default test run because it spawns the TypeScript
  engine through vitest.

## Lesson recorded

Golden vectors written by the same author as one implementation catch arithmetic slips, not shared
misreadings. The independent second implementation plus randomized differential testing found ten
real ambiguities that the hand-written vectors did not. The vectors were then extended to pin the
three that affect user-visible results.
