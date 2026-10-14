# Progress: backend-service

Role: build the FastAPI backend (spec 03 + 04, CSV per 05) on top of the pure engine.
Owner area: `backend/**` (except `backend/recruit_radar/engine/**`, `backend/tests/engine/**`,
`backend/tests/test_vectors.py`), `contracts/openapi.json`, `docs/progress/backend-service.md`,
`docs/spec/ambiguities/backend-service.md`.

Always run Python through `.venv/Scripts/python.exe`; from `backend/` for pytest/ruff/mypy.

## Status

- [x] M0 config, db models, session/PRAGMAs, Alembic 0001 (migration test still to write)
- [x] M1 normalization keys, posting validation, CSV import/export (tests still to write)
- [x] M2 adapters (base client, greenhouse, lever, ashby) (tests still to write)
- [x] M3 services + API (app factory, routers, error envelope) - smoke-run OK, tests still to write
- [x] M4a export_openapi + `contracts/openapi.json` (prettier-stable); drift test still to write
- [ ] M5 tests: conftest + fakes, migration, normalization, csv, adapters (http + mapping),
      every endpoint happy/error path, persistence across restarts, openapi drift, CORS,
      GET-only guard
- [ ] M6 backend/README.md, docs/spec/ambiguities/backend-service.md, final verification and live
      server smoke on port 8787

## Done

- Reviewed every pre-existing file (config, clock, errors, normalization, db/, adapters/, services/);
  fixed: mypy error in config.py, lone-surrogate text in provider JSON (would crash the INSERT),
  `Self` return type, `http_status` on all-invalid payloads, CSV BOM literal, duplicate-row warning
  only within one instant.
- `recruit_radar/api/` (app factory, state/deps, error envelope, schemas, 8 routers), `main.py`,
  `__main__.py`, `export_openapi.py`.

## In progress

M5 tests.

## Verify commands

```
cd backend
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m ruff check .
..\.venv\Scripts\python.exe -m ruff format --check .
..\.venv\Scripts\python.exe -m mypy --strict recruit_radar
..\.venv\Scripts\python.exe -m recruit_radar.export_openapi        # rewrites ../contracts/openapi.json
..\.venv\Scripts\python.exe -m recruit_radar.export_openapi --check
```
