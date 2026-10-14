# Test report (Prompt 02A build, builder's report)

This is the **builder's** evidence. Independent acceptance (Prompt 02B) has not been run.

Environment: Windows 10, Node.js v24.20.0, npm 11.19.0, Python 3.14.7, Microsoft Edge (Chromium)
via Playwright 1.64.0. Date: 2026-10-13/14. Command: `scripts/verify.ps1` (runs `npm ci` first).
Overall exit code: **0**.

| #   | Step                                  | Result                                                                                      |
| --- | ------------------------------------- | ------------------------------------------------------------------------------------------- |
| 1   | `npm ci`                              | exit 0, 0 vulnerabilities                                                                   |
| 2   | `npm run format:check`                | exit 0                                                                                      |
| 3   | `npm run lint` (ESLint)               | exit 0                                                                                      |
| 4   | `npm run typecheck` (`tsc --noEmit`)  | exit 0                                                                                      |
| 5   | `npm test` (Vitest)                   | exit 0, **646 passed**, 2 skipped (the fuzz leg, which needs `RR_FUZZ_FILE`), 17 files      |
| 6   | `npm run backend:lint` (ruff)         | exit 0                                                                                      |
| 7   | `npm run backend:format`              | exit 0, 87 files formatted                                                                  |
| 8   | `npm run backend:types` (mypy strict) | exit 0, 52 source files, no issues                                                          |
| 9   | `npm run backend:test` (pytest)       | exit 0, **1,496 passed**                                                                    |
| 10  | `npm run vectors:check`               | exit 0, oracle self-check OK (47 analysis vectors, 173 normalization cases, hand checks)    |
| 11  | `npm run fuzz`                        | exit 0, **948 generated cases, 0 mismatches** between oracle, Python and TypeScript engines |
| 12  | `npm run build`                       | exit 0                                                                                      |
| 13  | `npm run secrets`                     | exit 0, no findings                                                                         |
| 14  | `npm run e2e` (Playwright)            | exit 0, **18 passed** against the production build under `/recruit-radar/`                  |

## Clean-clone check

The committed branch `phase/02a-build` was cloned into a fresh directory, a new virtualenv was
created with `pip install -r backend/requirements.lock.txt`, and `scripts/verify.ps1` was run there:
exit 0 with the same counts (646 Vitest, 1,496 pytest, 948 fuzz cases / 0 mismatches, 18
Playwright). The commit therefore contains everything the gate needs.

## Browser tests (against a real backend and a local fake ATS)

- **Journey 1** (local-data mode): two overlapping CSVs; 6 companies before decisions; spacing-variant
  and near-typo merge candidates; merge one, reject the other; Radar shows 5; company breakdown with
  the corroboration, missing-information and honesty caption; shortlist note; shortlist CSV content.
- **Journey 2** (connected): add Greenhouse board, refresh, run history and provider-host column,
  role links; mutate the board (rename, remove, add); second refresh shows changed/removed/added with
  the counters 4/1/1/1/0/2; removed role kept as history; a role that returns is "Listed again".
- Failed refreshes (404, 401, 429 with Retry-After, 500, malformed) are recorded with explanations
  and six failed runs delete nothing. Lever pagination (130 roles over two pages) and Ashby without
  job ids and with an unlisted posting. The fake ATS received only `GET` requests.
- Backend offline: explained, falls back to local-data mode, local import still works.
- Persistence across reload; corrupt workspace recovered with the raw text kept as a backup.
- Keyboard: skip link first, 25 tab stops all show a focus indicator, Enter opens a company.
- Every control on every tab has an accessible name; no horizontal overflow at 375 and 320 px.
- Text contrast meets WCAG AA (4.5:1; 3:1 large) on every tab in light **and** dark mode.
- Honesty copy present; no recruiter-need / hiring-pain assertions (About may only negate them).

## Screenshots inspected

`desktop-radar.png`, `desktop-company.png`, `mobile-radar.png`, `desktop-radar-dark.png`,
`desktop-sources.png`.

## Defects found by running the product (all fixed)

| Defect                                                                                                                                             | Where found         | Fix                                                                                |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | ---------------------------------------------------------------------------------- |
| Data tab overflowed horizontally on phones (867 px page at 375 px): `.sr-only` text inside table cells escaped the non-positioned scroll container | quality e2e         | `position: relative` on `.table-scroll`                                            |
| "Role changes in the last successful run" listed the first run's baseline events when two refreshes ended in the same second                       | screenshot review   | baseline events attributed only to a source's first successful run + e2e assertion |
| Secret scan flagged URL-userinfo strings in a security test                                                                                        | `npm run secrets`   | strings built by concatenation                                                     |
| `pyproject.toml` written with a UTF-8 BOM broke pytest/mypy config parsing                                                                         | engine agent report | BOM removed                                                                        |
| 212 of 940 fuzz cases mismatched between engines (10 root causes, D-1..D-10)                                                                       | differential fuzz   | decided from the spec; vectors 45-47; regression tests in both engines             |

## Process note

The parallel build was interrupted three times (two usage limits, one API 529). Work recovered from
the interrupted agents was verified and completed inline. Every number above comes from the final
`scripts/verify.ps1` run on the committed tree, not from agent reports.

## Not tested

- Firefox and Safari; screen readers; 200% zoom.
- Real provider traffic (all provider payloads are synthetic, in the documented shapes).
- The GitHub Actions workflows (never executed; no remote).
- Python versions other than 3.14 locally (CI targets 3.12).
