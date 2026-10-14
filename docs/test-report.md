# Test report

Two reports live here. **Part 1** is the independent acceptance review (Prompt 02B, 2026-10-14): a
separate session that did not write the code, reran everything, attacked it, fixed what it found and
reran the gate. **Part 2** is the builder's original 02A report, kept for the record; where the two
differ, Part 1 is the later evidence.

Environment: Windows 10 (10.0.19045), Node.js v24.20.0, npm 11.19.0, Python 3.14.7, Microsoft Edge
(Chromium) via Playwright 1.64.0. Reviewed commit: `d05d57f` (builder's last). Fixed tree: see
`git log` on `phase/02a-build` (five review commits followed by this report).

---

# Part 1: independent acceptance (Prompt 02B)

## Verdict

**Ready for publication review.** Both required journeys work end to end; every REQUIRED V0.1 item
exists and does what it says; nothing blocks the local demo. The review found and fixed one
medium-severity defect class the builder's own differential testing had not looked at (two CSV
importers that disagreed, see D-1), one scale defect (D-2) and several smaller ones (table below).
Nothing is marked BLOCKED. Items that could not be verified here are listed under "Not verified".

## Commands run and results

Final gate on the fixed tree: `scripts/verify.ps1` (runs `npm ci` first), **overall exit 0**.

| #   | Step                                  | Result                                                                                              |
| --- | ------------------------------------- | --------------------------------------------------------------------------------------------------- |
| 1   | `npm ci`                              | exit 0                                                                                              |
| 2   | `npm run format:check`                | exit 0                                                                                              |
| 3   | `npm run lint` (ESLint)               | exit 0                                                                                              |
| 4   | `npm run typecheck` (`tsc --noEmit`)  | exit 0                                                                                              |
| 5   | `npm test` (Vitest)                   | exit 0, **706 passed**, 3 skipped (the three differential-fuzz legs, which need an input file)      |
| 6   | `npm run backend:lint` (ruff)         | exit 0                                                                                              |
| 7   | `npm run backend:format`              | exit 0                                                                                              |
| 8   | `npm run backend:types` (mypy strict) | exit 0                                                                                              |
| 9   | `npm run backend:test` (pytest)       | exit 0, **1,578 passed**                                                                            |
| 10  | `npm run vectors:check`               | exit 0 (47 analysis vectors + 173 normalization cases re-derived)                                   |
| 11  | `npm run fuzz`                        | exit 0: analyze **948 cases / 0 mismatches** (oracle, Python, TS); CSV **610 cases / 0 mismatches** |
| 12  | `npm run build`                       | exit 0                                                                                              |
| 13  | `npm run secrets`                     | exit 0, no findings                                                                                 |
| 14  | `npm run e2e` (Playwright)            | exit 0, **20 passed** against the production build under `/recruit-radar/`                          |

Before the fixes, the builder's commit `d05d57f` was also cloned into a fresh directory with a new
virtualenv (`pip install -r backend/requirements.lock.txt`) and `scripts/verify.ps1` run there:
exit 0 (646 Vitest, 1,496 pytest, fuzz 948/0, 18 Playwright). So the builder's claim held: the
defects below were not visible to the gate, they were missing from it.

## What was attacked, and how

### 1. Spec conformance, independently

- **17 new scenarios hand-derived from `docs/spec/02`** before any engine was run, then compared with
  the oracle, the Python engine and the TypeScript engine: 0 disagreements. They cover the change
  window at exactly 30 days (excluded), +1 s (included), at `as_of` (included) and a snapshot 1 s
  after `as_of` (ignored); the urgency threshold at exactly 45 days and 1 s short; the history span
  at 14 vs 13 days; freshness at 7, 8, 59 and 60 days; a role removed then listed again; a
  cross-source duplicate with corroboration; brackets, accents, CJK and keyword substring traps
  ("engineer"/"engineering", "data"/"database"); a rename; a company whose roles all disappeared;
  merge decisions with a stale "ghost" key; accent and full-width folding. (One expectation was
  wrong: mine, a date-arithmetic slip at day 59/60. The engines were right.)
- **More fuzz seeds against the unfixed tree:** seed 2 (1,648 cases), seed 99 (1,148), seed 31337
  (748): 0 mismatches, and the 148-case accept/reject catalogue agreed on every case.
- **Mutation checks in a scratch clone** (never the real tree): a Python-only change of the 30-day
  window bound, a Python-only urgency threshold, a TypeScript-only window, an oracle-only freshness
  bound: each is caught by the vectors, the engine unit tests and the fuzzer. Adding a field to a
  Pydantic response model makes the OpenAPI drift test fail (2 failures). A formatting violation
  makes `verify.ps1` and `verify.sh` exit 1 at the right step. A seeded GitHub-style token makes
  `npm run secrets` exit 1.
- The documented Unicode skew (Node 24 = Unicode 17, Python 3.14 = Unicode 16) was measured: exactly
  4,699 letter/number/mark code points differ, none used by the golden vectors.

### 2. Adapters against an adversarial ATS (own server, real sockets, 171 requests)

Redirects to another host, port or scheme are refused and never followed; a redirect loop stops at
3; declared-large, chunked and gzip-bomb bodies end in `too_large`; an endless Lever feed ends in
`too_large` at 5,100 items; 401, 403, 404, 429 (with and without a usable `Retry-After`), 500, 204,
an HTML 200, a `null` body, `NaN`, 100,000-deep JSON, invalid UTF-8 and an empty body each become
exactly one recorded failed run and leave existing data untouched. Mixed-type fields (numeric ids,
objects as titles, lone surrogates, `javascript:`/`ftp:` URLs, 10,000-character titles, duplicate ids,
non-listed Ashby jobs) are dropped or nulled with the counts in the run message. The server saw only
`GET`, one user agent, no cookies, no authorization header, and no path outside the three board
templates. Job descriptions placed in every payload were never stored (searched the whole SQLite
file). HTML in titles is stored as text and rendered as text.

### 3. API

22 token-bypass attempts (`../`, `%2e%2e`, `.`, `...`, unicode dots, full-width letters, NUL, newline,
whitespace, 101 characters, `%2f`...) are all `422 invalid_token`; the same board with another letter
case is `409 source_exists`; the error envelope was verified on 28 error paths; a CORS preflight
from a foreign origin is refused and a foreign-origin `POST` is `403`; `DELETE /api/data` without the
exact confirmation is `400`; 80 parallel writes and 24 parallel imports all succeed; a 40 MB body is
`422` in 0.3 s; analysis of 50,000 stored postings takes 3.4 s. Start-up with a corrupt database,
an unwritable path and a busy port were exercised.

### 4. Journeys in the real UI

The static build was served from a simulated GitHub Pages origin (`https://<account>.github.io/recruit-radar/`,
browser route interception, nothing deployed) in a fresh browser context.

- **Journey 1:** two overlapping CSVs of my own under different labels (4 + 5 rows), keywords set,
  merge candidate found and accepted, evidence score hand-checked against the formulas (76.6: 30x1000
  - 20x480 + 10x500 + 15x700 + 10x1000 over 85), the shortlist entry followed its company through
    the merge, the shortlist export carried the same figures.
- **Journey 2:** a Greenhouse board on the repository's fake ATS: first refresh baseline, board
  changed (rename, removal, addition), second refresh shows `changed: title`, "no longer listed" and
  "added" with timestamps and links, a listed-again role, 404/401/429/500/malformed runs recorded with
  data preserved; a too-soon second click explains the 60 s rule; a source deleted from another tab
  is reported when refreshed from a stale one; a company whose roles all disappear is "Not scored",
  sorts last in both directions and exports blank score and rank.
- **Live check, once:** one real read-only refresh per provider through the product's own adapters,
  against the vendors' own sample/documented boards (Greenhouse's board, Lever's `leverdemo`,
  Ashby's board): 17, 10 and 62 postings, all with dates, URLs, departments and locations mapped.
  Three GET requests in total.
- **Failure states:** backend offline (explained, local mode keeps working), backend answers with a
  CORS problem (explained with the exact variable to set), storage quota exceeded (reported, nothing
  half-saved), newer-schema and corrupt storage (kept untouched / backed up), a second tab (notice,
  no lost update), hostile HTML in stored data (rendered as text, no script ran).
- **Accessibility and layout:** skip link first; every tab stop has a focus ring; native dialog traps
  focus, closes on Escape and returns focus to its trigger; `aria-sort` follows the sort; no
  horizontal overflow at 320 px; reduced motion honored; dark mode readable; every in-page anchor
  has a target; every external link is http(s) with `rel="noopener"`.
- **Honesty:** the score caption, the "Possible urgency signal ... not evidence of hiring
  difficulty" label (Radar breakdown, company page, About, exports) and "Missing information" are
  present where the score is; no screen, export column, API field or error message implies that a
  company needs, struggles with or will pay for a recruiter (the About page only negates it);
  no LinkedIn, e-mail, outreach or candidate feature exists; a null component is never treated as
  zero (sorting keeps unscored rows last in both directions, the minimum-score filter says it hides
  them, exports leave the cells blank, coverage excludes them).

## Defects found

| #    | Severity   | Defect                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Status                                                                                           |
| ---- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| D-1  | Medium     | **The two CSV importers disagreed** (Python for the backend, TypeScript for local-data mode; never compared). A differential fuzz found 426 of 1,210 generated files giving different results; single-feature probes: whitespace-only lines, `""` lines, trailing empty cells, spaces around quoted fields, tab/NBSP in headers, NUL, apostrophe-led formula cells, malformed header rows, errors reported for broken rows. Connected mode re-derives correction rows with the TypeScript importer, so the in-place forms could contradict the backend. | Fixed: spec 05 "CSV details", both importers, 52 shared vectors, `fuzz_csv.py` in `npm run fuzz` |
| D-2  | Medium     | Merge review rendered every candidate at once. 300 look-alike names ("Store 001"...) gave ~3,000 candidates and an **18 s** tab switch; 1,000 gave ~13,500.                                                                                                                                                                                                                                                                                                                                                                                             | Fixed: 25 per page; e2e `scale.spec.ts`; 1,000 look-alike companies import in about a second     |
| D-3  | Low-medium | No `Host` header check: a hostile page whose domain is rebound to 127.0.0.1 could read the unauthenticated API as same origin.                                                                                                                                                                                                                                                                                                                                                                                                                          | Fixed: `400 host_not_allowed` before CORS/routing; `RECRUIT_RADAR_ALLOWED_HOSTS`; tests          |
| D-4  | Low        | The 15 s provider timeout bounds each read, not the sum: a provider dripping a byte every 14 s held the global refresh lock for as long as it liked.                                                                                                                                                                                                                                                                                                                                                                                                    | Fixed: 60 s total per request; test with a drip stream                                           |
| D-5  | Low        | A database locked by another program surfaced as an opaque 500 after 5 s.                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Fixed: `503 database_busy` + `Retry-After`; nothing lost; test                                   |
| D-6  | Low        | A corrupt or unwritable database file crashed start-up with a traceback.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | Fixed: one line naming the file, exit code 2; tests                                              |
| D-7  | Low        | Connected-mode shortlist export had no UTF-8 BOM (local mode did): Excel read accents as mojibake.                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Fixed with tests                                                                                 |
| D-8  | Low        | `npm run verify` omitted `npm run fuzz` although README, `verify.ps1`, `verify.sh` and CI include it.                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Fixed                                                                                            |
| D-9  | Low        | The randomized invariant suite used vitest's 5 s timeout and failed once under CPU load (flaky gate).                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Fixed: 30 s project timeout                                                                      |
| D-10 | Low        | No React error boundary: any render exception left a blank page with no explanation.                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Fixed: explained fallback; e2e forces a failure                                                  |
| D-11 | Low        | On phones the radar's score column is off screen in the sideways-scrolling table.                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | Fixed: score repeated under the name on narrow screens                                           |
| D-12 | Info       | Settings said "Use the backend ... (also from a public page)", an unverifiable promise; architecture doc said snapshot ids are zero-padded (backend only); known limitations missed several facts.                                                                                                                                                                                                                                                                                                                                                      | Fixed (copy and docs)                                                                            |

Not defects, recorded: local snapshot ids are plain sequence numbers, so two imports in the same
wall-clock second that cross a digit boundary (9 to 10) would replay in string order (needs two
imports within one second); the shortlist exporters word the evidence column slightly differently in
the two modes; the e2e run rewrites tracked screenshots (documented in CONTRIBUTING).

## Not verified (external or out of reach) and remaining issues

- **GitHub Actions workflows** (CI, Pages): YAML parses and every action major equals the latest
  release (checkout 7, setup-node 7, setup-python 7, upload-artifact 7, configure-pages 6,
  upload-pages-artifact 5, deploy-pages 5), but nothing can run without a remote.
- **Python 3.11 / 3.12 and Linux**: only Python 3.14 on Windows was available; mypy is configured
  for 3.11 and passes. CI targets 3.12.
- **A public page reaching a local backend**: depends on the browser's local-network-access policy;
  not testable without a published page. The app explains the CORS and offline cases it can see.
- **Browsers other than Edge/Chromium, a real screen reader, 200% browser zoom**: not tested (320 px
  reflow, keyboard and contrast were).
- **Content-Security-Policy**: none (GitHub Pages cannot set headers and no meta policy was added).
- Git history carries the local author e-mail address (owner decision before publishing).

## README claims checked against the running app

Every bullet under "What it does", the quick-start commands (clean clone, new virtualenv), the command
table, the ethics paragraph, the test counts (47 vectors, 173 normalization cases, ~950 fuzz cases)
and the status paragraph match observed behavior. Corrected: the `npm run verify` description
(fuzz missing), the fuzz row, and the CSV-importer sentence. Screenshots in `docs/screenshots/` were
regenerated from the final production build and inspected: `desktop-radar.png`, `desktop-company.png`,
`desktop-radar-dark.png`, `desktop-sources.png`, `mobile-radar.png` (shows the new per-row score).
License is MIT (copyright PatrickNDevelopment); 204 npm packages (4 shipped at runtime, all MIT) and the 34
Python distributions in the virtualenv carry permissive licenses; no GPL, no unspecified license; no fonts, images or
scripts are loaded from other sites; the secret scan and a manual scan found no secrets, local paths
or personal data in the tree or in the content of the 10 commits of history (apart from the author
e-mail address in commit metadata, above).

---

# Part 2: builder's report (Prompt 02A), unchanged

This is the **builder's** evidence.

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

## Defects found by running the product (all fixed)

| Defect                                                                                                                                             | Where found         | Fix                                                                                |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | ---------------------------------------------------------------------------------- |
| Data tab overflowed horizontally on phones (867 px page at 375 px): `.sr-only` text inside table cells escaped the non-positioned scroll container | quality e2e         | `position: relative` on `.table-scroll`                                            |
| "Role changes in the last successful run" listed the first run's baseline events when two refreshes ended in the same second                       | screenshot review   | baseline events attributed only to a source's first successful run + e2e assertion |
| Secret scan flagged URL-userinfo strings in a security test                                                                                        | `npm run secrets`   | strings built by concatenation                                                     |
| `pyproject.toml` written with a UTF-8 BOM broke pytest/mypy config parsing                                                                         | engine agent report | BOM removed                                                                        |
| 212 of 940 fuzz cases mismatched between engines (10 root causes, D-1..D-10)                                                                       | differential fuzz   | decided from the spec; vectors 45-47; regression tests in both engines             |

## Not tested (by the builder)

- Firefox and Safari; screen readers; 200% zoom.
- Real provider traffic (all provider payloads are synthetic, in the documented shapes), since
  checked once by the 02B review (Part 1).
- The GitHub Actions workflows (never executed; no remote).
- Python versions other than 3.14 locally (CI targets 3.12).
