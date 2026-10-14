# Handoff

**State:** v0.1 built locally on branch `phase/02a-build`. Independent acceptance (Prompt 02B) has
**not** been run. Not pushed, not deployed.

## Run

```powershell
npm ci
python -m venv .venv ; .\.venv\Scripts\python -m pip install -r backend\requirements.lock.txt
npm run dev                                  # local-data mode: http://localhost:5173/recruit-radar/
cd backend ; ..\.venv\Scripts\python -m recruit_radar   # backend: http://127.0.0.1:8787
npm run verify                               # full gate (or scripts/verify.ps1)
```

## What really works

- Radar, company detail with score breakdown and missing information, role history events.
- Manual entry, CSV import with line-level errors and in-place correction, datasets, merge review,
  shortlist with notes, shortlist and postings CSV export, saved views, role keywords.
- Local-data mode (localStorage, corruption recovery, newer-schema protection, cross-tab notice).
- Connected mode: SQLite + Alembic, Greenhouse / Lever / Ashby read-only adapters, refresh history,
  error taxonomy, failed runs keep data, OpenAPI contract with drift test.
- Two independent engines + oracle, 47 golden analysis vectors, 173 normalization cases, three-way
  differential fuzz (see `docs/spec/ambiguities/differential.md`).

## What is absent

- No hosted demo; the Pages workflow has never run (no remote).
- No scheduled refresh, no auth (loopback only), no HTML scraping, no candidate data (by design).
- Provider payload shapes come from documentation, not from recordings of live traffic.

## Release blockers before publication

1. Run Prompt 02B (independent adversarial acceptance) in a fresh session.
2. Owner approval to create the public repo, push, and enable Pages (MIT and the
   `PatrickNDevelopment` account are already confirmed, decision D-005).
3. Verify the CI workflows on a real remote (never executed locally).
4. Decide whether to rewrite the git author e-mail in history before publishing.

## Next exact step

Open a **new** Claude Code session at `C:\Users\patno\Desktop\Github` and paste **Prompt 02B** from
`Claude_GitHub_Portfolio_Build_Chain.md`.

## Gotchas

- `vite.config.ts` sets `base: '/recruit-radar/'`; e2e tests use that prefix on port 4174.
- Ports: backend 8787, fake ATS 8788, preview 4174, dev 5173.
- If you change scoring, identity or normalization: spec, both engines and the oracle together,
  then `npm run fuzz` must report 0 mismatches.
