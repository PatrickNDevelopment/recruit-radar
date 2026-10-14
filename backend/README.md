# RecruitRadar backend

FastAPI + SQLAlchemy 2 + Alembic (SQLite). Contract: `docs/spec/03-api.md`, `04-ats-adapters.md`.

```bash
python -m venv ../.venv
../.venv/Scripts/python -m pip install -r requirements.lock.txt
../.venv/Scripts/python -m recruit_radar        # http://127.0.0.1:8787, migrates the DB on start
```

## Configuration (environment)

| Variable                                          | Default                                       | Purpose                                         |
| ------------------------------------------------- | --------------------------------------------- | ----------------------------------------------- |
| `RECRUIT_RADAR_DB_PATH`                           | `backend/data/recruit_radar.sqlite3`          | SQLite file                                     |
| `RECRUIT_RADAR_HOST` / `_PORT`                    | `127.0.0.1` / `8787`                          | bind address                                    |
| `RECRUIT_RADAR_CORS_ORIGINS`                      | `http://localhost:5173,http://localhost:4174` | explicit origins (never `*`)                    |
| `RECRUIT_RADAR_MIN_REFRESH_INTERVAL_S`            | `60`                                          | minimum seconds between refreshes of one source |
| `RECRUIT_RADAR_{GREENHOUSE,LEVER,ASHBY}_BASE_URL` | the real provider hosts                       | **tests only**: point at a local fake ATS       |

## Development

```bash
python -m pytest backend -q                 # from the repo root
python -m ruff check backend && python -m ruff format --check backend
python -m mypy --strict backend/recruit_radar
python -m recruit_radar.export_openapi      # regenerates contracts/openapi.json (from backend/)
```
