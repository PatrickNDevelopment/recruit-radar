# Architecture

## Shape

```
browser (React + TS)                          local backend (FastAPI, optional)
  src/ui     screens                            backend/recruit_radar/api        routers, error envelope
  src/data   AnalysisSource: LocalSource  <-->    services/    refresh, intake, analysis, shortlist
             (engine + localStorage)              adapters/    greenhouse, lever, ashby (GET only)
             RemoteSource (fetch)                 db/          SQLAlchemy 2 + Alembic, SQLite
  src/engine analyze() + CSV (pure TS)            engine/      analyze() (pure Python)
                      \                              /
                       docs/spec + contracts/vectors  (shared contract, golden vectors, oracle)
```

The UI talks to an `AnalysisSource` interface with two implementations. Both return the same
`Analysis` shape (`docs/spec/02`). In **local-data mode** the TypeScript engine computes it from data
in `localStorage`; in **connected mode** the backend replays stored snapshots through the Python
engine and the UI renders the response. The static GitHub Pages build never needs the backend.

## Core idea: snapshot replay

Raw observations are the only stored truth. A **snapshot** is a list of postings from one source at
one instant, either `full` (the source's complete current list: absence means removal) or
`additive` (a CSV import or manual entry: absence means nothing). `analyze(snapshots, profile,
decisions, as_of)` replays them in `(observed_at, snapshot_id)` order and derives companies, canonical
roles, lifecycle events and scores. There are no derived tables, so a merge decision or a keyword
change applies retroactively and can never drift from the data.

## Identity and de-duplication (docs/spec/01)

- Company key = normalized name with legal suffixes removed; equal keys are one company.
  Look-alikes (`spacing_variant`, `token_overlap`, `near_typo`) become **merge candidates** that only
  a user decision can merge.
- Within one source, distinct posting ids are distinct headcount. Across sources, a role matches on
  `(company, title_key, location_key)` one-to-one, so a board and a CSV that list the same opening
  corroborate each other instead of double counting.
- Renames are tracked by the source role key, so a renamed role is a `changed` event, not a
  remove-plus-add.

## Scoring (docs/spec/02)

Six components with integer weights summing to 100: role relevance 30, volume 20, change 15,
urgency 10, source confidence 15, freshness 10. Every component is an integer 0..1000 or **null with
a reason code**; the overall score is the weight-normalized mean of the non-null components and
`coverage` is the weight that was measured. All arithmetic is integer (round-half-up); there is no
floating point. Missing information is displayed, never scored as zero.

## Backend

| Concern  | Decision                                                                                                          |
| -------- | ----------------------------------------------------------------------------------------------------------------- |
| Storage  | SQLite (WAL, foreign keys on, busy timeout), SQLAlchemy 2 typed models, Alembic `0001_initial`                    |
| Refresh  | one request per page, sequential; failed runs recorded but store no snapshot and remove nothing                   |
| Counters | refresh counters are the diff of engine events before/after the new snapshot (not a second implementation)        |
| Ordering | snapshot ids are zero-padded and monotonic, so same-second snapshots replay in insertion order                    |
| API      | Pydantic `extra="forbid"`, uniform error envelope, OpenAPI exported to `contracts/openapi.json` with a drift test |
| Security | token-only inputs, fixed hosts, GET only, size/time/item caps, loopback bind, strict CORS                         |

## Decisions

| Decision                                             | Reason                                                                                                                                                      |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Two independent engines + oracle + differential fuzz | A static demo needs the logic in the browser; a backend needs it in Python; independence turns duplication into verification (it found 212 real mismatches) |
| Pure `analyze()` with explicit `as_of`               | Deterministic, testable, no clock or locale dependence                                                                                                      |
| Derive, don't store, analysis                        | Retroactive decisions, no drift, trivially testable                                                                                                         |
| Integer scoring tables, no `log`                     | Bit-identical results across languages                                                                                                                      |
| No HTML scraping, three JSON APIs only               | Policy-safe and stable; payloads are small and documented                                                                                                   |
| Local-data mode as a first-class mode                | The public demo is useful without any server                                                                                                                |
| Ashby job id derived from `jobUrl`                   | Ashby's documentation lists no job id                                                                                                                       |

## Visual identity

"Radar" theme: deep ink-blue header with a concentric-ring mark, teal primary, amber for caution,
sans-serif, light and dark via `prefers-color-scheme`, visible focus rings, tables that scroll
inside labelled regions with a sticky first column.
