# Handoff

**State:** v0.1 built locally on branch `phase/02a-build`, then independently reviewed and corrected
in an independent acceptance review (2026-10-14, see `docs/test-report.md`). Gate G2 is met: status
`ready_for_publication_review`. Published on GitHub; static demo at https://patrickndevelopment.github.io/recruit-radar/.

## Run

```powershell
npm ci
python -m venv .venv ; .\.venv\Scripts\python -m pip install -r backend\requirements.lock.txt
npm run dev                                  # local-data mode: http://localhost:5173/recruit-radar/
cd backend ; ..\.venv\Scripts\python -m recruit_radar   # backend: http://127.0.0.1:8787
npm run verify                               # full gate (or scripts/verify.ps1 / verify.sh)
```

## What really works

- Radar, company detail with score breakdown and missing information, role history events.
- Manual entry, CSV import with line-level errors and in-place correction, datasets, merge review
  (paged, 25 at a time), shortlist with notes, shortlist and postings CSV export, saved views, role
  keywords.
- Local-data mode (localStorage, corruption recovery, newer-schema protection, cross-tab notice,
  quota failure is reported and nothing half-saved).
- Connected mode: SQLite + Alembic, Greenhouse / Lever / Ashby read-only adapters (also checked once
  against the three providers' live sample boards), refresh history, error taxonomy, failed runs
  keep data, OpenAPI contract with drift test, Host/Origin guards, busy-database 503.
- Two independent `analyze()` engines + oracle (47 golden vectors, 173 normalization cases,
  three-way differential fuzz) **and** two independent CSV importers held to 52 shared vectors and
  their own differential fuzz (`contracts/tools/fuzz_csv.py`).

## What is absent

- The hosted demo has no backend (local-data mode only); CI and Pages have run on GitHub (2026-10-15).
- No scheduled refresh, no auth (loopback only), no HTML scraping, no candidate data (by design).
- Connected mode cannot remove a single dataset or export raw postings (no backend endpoint).
- No automated provider-traffic test (the 02B live check was a one-off, recorded in the report).

## Release blockers before publication

Published; no remaining release blockers. Open items are listed in `docs/known-limitations.md`.
Note: commits made before publication carry the author name `patno` with the owner's e-mail address
(history was deliberately not rewritten, owner decision D-006).

## Next exact step

Owner review (G3). Publishing this repository is a separate, explicitly approved action.

## Gotchas

- `vite.config.ts` sets `base: '/recruit-radar/'`; e2e tests use that prefix on port 4174.
- Ports: backend 8787, fake ATS 8788, preview 4174, dev 5173.
- If you change scoring, identity or normalization: spec, both engines and the oracle together,
  then `npm run fuzz` must report 0 mismatches. If you change CSV parsing or validation: spec 05
  "CSV details", both importers (`src/engine/csv.ts`, `backend/recruit_radar/services/csv_io.py`)
  and `contracts/vectors/csv-import.json` together.
- `npm run e2e` rewrites `docs/screenshots/*.png` (they carry a timestamp); commit them only when
  the UI changed.
- The backend refuses requests whose `Host` is not loopback / its bind address /
  `RECRUIT_RADAR_ALLOWED_HOSTS` (DNS-rebinding guard).
