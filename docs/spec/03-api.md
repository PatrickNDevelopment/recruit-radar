# 03 — Backend HTTP API (FastAPI, JSON, local-only)

Base path `/api`. Binds to `127.0.0.1` by default; CORS allows only origins listed in
`RECRUIT_RADAR_CORS_ORIGINS` (default `http://localhost:5173,http://localhost:4174`). No auth (local
tool; documented). Errors use `{ "error": { "code": "<snake_case>", "message": "…", "details": {…}? } }`
with the HTTP status noted below. Every request body is a Pydantic model with `extra="forbid"`.

| Method & path                                        | Purpose                                                                                                   | Success                                    | Errors                                                                       |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------ | ---------------------------------------------------------------------------- |
| `GET /api/health`                                    | liveness + `schema_version`, `app_version`, `db_ok`                                                       | 200                                        | —                                                                            |
| `GET /api/profile` / `PUT /api/profile`              | role keywords `{include_keywords[], exclude_keywords[]}` (≤50 each, ≤60 chars)                            | 200                                        | 422 `invalid_profile`                                                        |
| `GET /api/sources`                                   | list sources + last run summary                                                                           | 200                                        | —                                                                            |
| `POST /api/sources`                                  | `{provider: greenhouse\|lever\|ashby, token, company_name}`; `token` must match `^[A-Za-z0-9_.-]{1,100}$` | 201                                        | 422 `invalid_token`, 409 `source_exists`                                     |
| `DELETE /api/sources/{id}`                           | removes source with its runs/snapshots                                                                    | 204                                        | 404 `not_found`                                                              |
| `POST /api/sources/{id}/refresh`                     | one read-only fetch, normalize, store snapshot, diff                                                      | 200 `RefreshRun` (status `ok` or `failed`) | 404, 429 `too_soon` (min interval 60 s, `Retry-After`)                       |
| `GET /api/sources/{id}/runs`                         | refresh history, newest first (≤100)                                                                      | 200                                        | 404                                                                          |
| `POST /api/imports/csv`                              | `{dataset_label, csv_text, observed_at?}` per `05`; additive snapshot                                     | 201 `ImportResult`                         | 422 `invalid_csv` (file-level), per-row errors returned in body with 200/201 |
| `POST /api/postings`                                 | one manual posting (`dataset_label`, fields of RawPosting)                                                | 201                                        | 422 `invalid_posting`                                                        |
| `GET /api/analysis`                                  | `?as_of=` optional (default now UTC, whole seconds) → Analysis (02 §5)                                    | 200                                        | 422 `invalid_as_of`                                                          |
| `GET /api/companies/{company_id}`                    | company object + its roles + events + per-source freshness                                                | 200                                        | 404                                                                          |
| `GET /api/merge-decisions` / `POST` / `DELETE /{id}` | list/create/delete `{a_key,b_key,decision}`                                                               | 200/201/204                                | 422 `invalid_decision`, 409                                                  |
| `GET /api/shortlist`                                 | entries `{company_id, name, note, added_at}`                                                              | 200                                        | —                                                                            |
| `PUT /api/companies/{company_id}/shortlist`          | `{shortlisted: bool, note?: str≤2000}`                                                                    | 200                                        | 404 `unknown_company`                                                        |
| `GET /api/shortlist/export.csv`                      | shortlist CSV with score + evidence summary                                                               | 200 `text/csv`                             | —                                                                            |
| `DELETE /api/data`                                   | wipes all data (requires `?confirm=erase-all`)                                                            | 204                                        | 400 `confirmation_required`                                                  |

`RefreshRun`: `{id, source_id, started_at, finished_at, status: "ok"|"failed", error_kind: null|
"not_found"|"unauthorized"|"rate_limited"|"server_error"|"network"|"timeout"|"malformed"|"too_large",
http_status: int|null, retry_after_s: int|null, items_seen, added, changed, removed, reappeared,
unchanged, message}`.
A failed run stores **no snapshot** and removes nothing. A run is stored in history either way.

`ImportResult`: `{snapshot_id, dataset_label, accepted, rejected, errors: [{line, field?, message}],
warnings: [{line, message}]}` — rows are validated individually; valid rows are stored.

OpenAPI is exported to `contracts/openapi.json` by `python -m recruit_radar.export_openapi`; a pytest
fails when the committed file differs from the live schema.

## Persistence (SQLite, SQLAlchemy 2, Alembic migration `0001_initial`)

Tables: `sources`, `refresh_runs`, `snapshots` (per run/import: id, source ref, observed_at, mode),
`posting_observations` (snapshot_id, normalized RawPosting fields + `company_key`, `title_key`,
`location_key`), `merge_decisions`, `shortlist`, `profile`, `meta(schema_version)`.
Foreign keys ON, WAL, `busy_timeout`. `analysis` is derived by replaying stored snapshots through the
pure engine (no derived tables).
