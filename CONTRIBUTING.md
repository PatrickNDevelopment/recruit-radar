# Contributing

1. Node.js 20.19+ (developed on 24) and Python 3.11+ (developed on 3.14).
2. `npm ci`, then `python -m venv .venv` and `pip install -r backend/requirements.lock.txt` inside it.
3. `npm run dev` for the front end; `cd backend && python -m recruit_radar` for the backend.
4. Before opening a pull request run `npm run verify` (format, lint, types, unit tests, backend
   checks, vectors, build, secret scan, Playwright). All steps must pass.

## Rules for changes

- **The spec is the contract** (`docs/spec/`). A change to scoring, identity or normalization starts
  there. Both engines (`backend/recruit_radar/engine`, `src/engine`) and the oracle
  (`contracts/tools/oracle.py`) must change together, and `npm run fuzz` must show 0 mismatches.
- New behavior that affects results gets a golden vector (`contracts/tools/generate_vectors.py`)
  with a hand check in `contracts/vectors/HAND_CHECKS.md`.
- The honesty rules are binding: no claim that a company needs or will pay a recruiter, fixtures
  are labeled synthetic, missing information is shown, never scored as zero.
- Do not add network calls other than the three documented read-only provider GETs, HTML scraping,
  candidate data, or secrets.
- Every control must do real work; no decorative buttons or fake success messages.

## Formatting

Prettier (`npm run format`), ESLint, `ruff format` / `ruff check`, `mypy --strict` are enforced in CI.
