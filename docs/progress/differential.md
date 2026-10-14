# Differential agent progress

Role: make the oracle (`contracts/tools/oracle.py` + `contracts/vectors/*`), the Python engine
(`backend/recruit_radar/engine`) and the TypeScript engine (`src/engine`) agree, and decide from the
spec text which side is wrong when they do not.

Started from commit `b17b321` (clean tree; pytest 922, vitest 465 at launch).

## Status

- [x] 0. Read spec 00-05, both engines, oracle, vector loaders. Baseline: vectors green in both
      engines (223 pytest cases, 217 vitest cases), oracle `--self-check` OK.
- [x] 1. Fuzz harness: `contracts/tools/fuzz_diff.py` + `tests/fuzz-diff.test.ts` (runs; ~10 s for
      950 cases). Out of the default test run (vitest leg is skipped without `RR_FUZZ_FILE`).
- [x] 2. First fuzz run on the committed engines (HEAD `b17b321`): 212 of 940 cases mismatched
      (90 conforming, 107 extended, 15 validity) -> classified into D-1..D-10.
- [x] 3. Fixes landed in the working tree (not committed): Python `identity.py`, `analyze.py`,
      `models.py`; TS `identity.ts`, `normalize.ts`, `analyze.ts`, `validate.ts`; existing tests
      updated to the decided readings.
- [x] 4. Validity (accept/reject) differential: 148-case catalogue, python == ts on all.
- [x] 4b. Vectors 45-47 added (`generate_vectors.py`, hand derivations HC-21..23 in HAND_CHECKS.md,
      `oracle.py` HAND_* + self-check `pinned` readings). They pin D-2, D-3, D-4; the HEAD Python engine
      fails 45 and 46, the HEAD TS engine fails 47. Now 226 pytest / 220 vitest vector cases.
- [x] 4c. Normalization sweep (`fuzz_diff.py norm-sweep`): all 1,152,198 code points + sequences:
      0 real divergences; 4,699 single code points are Unicode 16 (Python) vs 17 (Node) version skew.
- [ ] 5. `docs/spec/ambiguities/differential.md` (the decision record D-1..D-10)
- [ ] 6. Regression tests for D-5..D-10 in both engines (`tests/differential.test.ts`,
      `backend/tests/engine/test_engine_differential.py`)
- [ ] 7. Generator widening (code-point-order stress, heavy companies), multi-seed runs,
      before/after counts with the final generator
- [ ] 8. Final re-run of everything

## Decisions (short form; the record is docs/spec/ambiguities/differential.md)

| id   | question                                   | decided reading                              | wrong artifact |
| ---- | ------------------------------------------ | -------------------------------------------- | -------------- |
| D-1  | what "trimmed" strips                      | ECMAScript WhiteSpace+LineTerminator (+FEFF) | TS             |
| D-2  | T (full-snapshot instants) set/multiset    | set                                          | Python         |
| D-3  | canonical key may be a key with no posting | yes (smallest member key)                    | Python         |
| D-4  | not_same names a pair of ...               | exactly the canonical keys it names          | TS             |
| D-5  | unknown input keys                         | ignored                                      | Python         |
| D-6  | padded `as_of` / `observed_at`             | rejected (not RawPosting strings)            | TS             |
| D-7  | omitted `snapshots` / `postings`           | empty                                        | TS             |
| D-8  | url validity                               | scheme only (`http:`/`https:`)               | TS             |
| D-9  | keyword limits at engine boundary          | enforced (<=50, <=60 code points)            | Python         |
| D-10 | posting-level `source_ref: ""`             | invalid                                      | Python         |

## Commands that verify what is done

```
# vectors (both engines) + oracle self-check
$env:RR_REQUIRE_VECTORS='1'
.\.venv\Scripts\python.exe -m pytest backend/tests/test_vectors.py -q
npx vitest run tests/vectors.test.ts
.\.venv\Scripts\python.exe contracts/tools/oracle.py --self-check

# engine unit tests
.\.venv\Scripts\python.exe -m pytest backend/tests/engine -q
npx vitest run tests/analyze.test.ts tests/identity.test.ts tests/normalize.test.ts

# cross-implementation fuzz (oracle + python + typescript); exit 0 only if all agree
.\.venv\Scripts\python.exe contracts/tools/fuzz_diff.py all --seed 1 --count 800
```

## Notes for a resumed session

- No git add/commit/checkout/stash/reset; the lead commits.
- Edit only: `contracts/tools/fuzz_diff.py`, `tests/fuzz-diff.test.ts`, engine files for fixes
  (with regression tests), `docs/spec/ambiguities/differential.md`, this file.
- "Before" numbers were measured on a pristine `git archive HEAD` copy with the same fuzz tool and
  a junction to node_modules (scratch dir, not in the repo).
