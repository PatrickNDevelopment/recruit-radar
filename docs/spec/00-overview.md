# 00 — Overview, scope and ownership

**Product (one sentence):** RecruitRadar turns public job-posting data into an evidence-backed,
explainable view of which companies show hiring activity in the roles you care about.

## What it is NOT (hard rules — tests enforce several)
- Not a candidate tool: no candidate records, no candidate scoring, no outreach, no emails (guessed or real).
- Never states or implies that a company *needs*, *is struggling*, or *will pay* an outside recruiter.
  A posting is a posting. Scores say "observed hiring activity", never "hiring pain".
- No LinkedIn or other logged-in scraping; no CAPTCHA evasion; no HTML scraping at all. Only the three
  documented public JSON APIs (Greenhouse, Lever, Ashby) and user-provided CSV / manual entry.
- No secrets, no accounts, no paid services. The three ATS GET endpoints need no key.

## Two runtime modes sharing one contract
1. **Local-data mode (static GitHub Pages demo, works offline):** browser-only TypeScript engine +
   `localStorage`. Features: manual entry, CSV import/export, dedup, identity resolution, scoring,
   company detail, saved views, qualification notes, shortlist export. No ATS refresh (CORS/policy);
   the UI says so.
2. **Connected mode (local FastAPI backend):** everything above, persisted in SQLite with Alembic
   migrations, plus read-only ATS refresh with refresh history.

The Python engine (`backend/recruit_radar/engine/`) and the TypeScript engine (`src/engine/`) are two
independent implementations of the same pure function `analyze(...)` defined in `01`/`02`. They must
produce identical results on every vector in `contracts/vectors/*.json`.

## Repository layout
```
docs/spec/                 these documents (the contract)
contracts/vectors/*.json   golden analysis vectors (hand-derived, implementation-independent)
contracts/openapi.json     generated from FastAPI; a test fails on drift
backend/recruit_radar/     engine/ (pure) · db/ · adapters/ · api/ · services/
backend/tests/             pytest
backend/alembic/           migrations
src/engine/                TS engine (pure, no DOM)
src/data/                  AnalysisSource: LocalSource (engine + localStorage), RemoteSource (HTTP)
src/ui/                    React components
tests/                     vitest (engine, CSV, vectors)
e2e/                       Playwright
```

## Ownership boundaries (avoid edit conflicts)
- `backend/**` — backend agents only. `src/engine/**`, `tests/**` — TS engine agent only.
  `src/data/**`, `src/ui/**`, `src/*.tsx`, `src/*.css`, `e2e/**` — UI agent only.
- `docs/spec/**` and `contracts/vectors/**` are read-only for implementers. If the spec is ambiguous
  or wrong, do NOT silently pick: record it in `docs/spec/AMBIGUITIES.md` (append) with the case, your
  chosen reading and why, and implement that reading.

## Determinism
`analyze` never reads the clock, randomness, locale, or environment. `as_of` is an explicit input.
All money-free arithmetic is integer arithmetic; "round half up" for non-negative integers is
`floor((2*num + den) / (2*den))`. No floating point anywhere in scoring.
