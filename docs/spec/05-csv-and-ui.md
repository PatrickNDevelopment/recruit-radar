# 05 — CSV format, UI screens, journeys, honesty copy

## CSV (import and export are symmetric)
UTF-8, RFC 4180 (quotes, embedded commas/newlines, CRLF/LF, BOM tolerated). ≤1 MB, ≤5,000 data rows.
Header names are case-insensitive, spaces/hyphens → `_`; duplicate headers are a file error; unknown
columns are ignored with a warning.

Columns: `company_name`* · `title`* · `location` · `work_mode` (`remote|hybrid|onsite|unknown`, blank =
`unknown`) · `department` · `url` · `posted_at` (`YYYY-MM-DD`) · `source_posting_id` · `observed_at`
(`YYYY-MM-DDTHH:MM:SSZ`; blank = import time). `*` required.
Row validation errors (row rejected, others kept) carry the 1-based CSV line number, field, message:
missing required; over-length; bad `work_mode`; non-http(s) url; impossible date; unterminated quote
(file-level error). Export formula guard: any text cell starting with `= + - @ tab CR` gets one leading
apostrophe on export and exactly one leading apostrophe followed by such a character is removed on import.
Importing assigns `dataset_label` (user-provided, required) as `source_ref`, `source_kind="csv"`,
`mode="additive"`. Manual entry uses `source_kind="manual"`, `source_ref="manual"`.

**Shortlist export CSV**: `rank, company, score, coverage_percent, active_roles, relevant_roles,
last_seen, strongest_evidence, missing_information, note, as_of`.

## Screens (single-page app, tabs; no client router so refresh works under `/recruit-radar/`)
1. **Radar** — table of companies: name, active roles, relevant roles, role mix (work mode),
   locations, sources, last seen, signal age ("last seen N days ago"), **priority score** with coverage,
   shortlist toggle. Sort, filter (text, work mode, source, min score, shortlisted only), saved views
   (name + filter + sort; stored locally), URL-less. Empty state explains how to add data.
2. **Company detail** — roles (status, first/last seen, sources + links), role history events, score
   breakdown (each component: value, weight, human-readable calculation from `inputs`, or the missing
   information reason), evidence provenance (source kind/ref, observed_at, url), qualification note,
   shortlist toggle.
3. **Data** — manual entry form; CSV import (file or paste) with per-line error report and in-place
   correction; dataset list; export; **Merge review** (candidates with reason, accept/reject, undo).
4. **Sources (connected mode only)** — add/remove ATS source, refresh button, refresh history table
   (time, status, error kind, counts), changed/removed roles of the last run. In local mode this tab
   explains why refresh is unavailable and how to run the backend.
5. **Settings** — role keywords (include/exclude), backend URL + connection status, erase data.
6. **About** — method, scoring formulas, limitations.

## Honesty copy (must appear; tests assert key phrases)
- Banner in local-data mode: "Local-data mode: your data stays in this browser. Live ATS refresh needs
  the local backend."
- Sample data banner when synthetic rows are present: "Synthetic sample data — invented companies, not real hiring data."
- Score caption: "Priority score = observed hiring activity in the roles you configured, from the sources
  you loaded. It is not evidence that a company needs or will use an outside recruiter."
- Missing components are listed under "Missing information", never silently scored as zero.
- `urgency` label: "Possible urgency signal (aged postings) — not evidence of hiring difficulty."

## Journeys (Playwright, production build under `/recruit-radar/`)
1. **Local overlap** (no backend): load two overlapping CSVs (different dataset labels), see duplicates
   collapsed into canonical companies/roles, resolve a merge candidate, open an evidence score
   breakdown, add the company to the shortlist, export shortlist CSV.
2. **Connected refresh** (backend + local fake ATS server): add a Greenhouse source, refresh, see
   normalized roles + refresh history; change the fake board (rename one role, remove one, add one),
   refresh again, inspect timestamps, source URLs and the changed/removed role events; make the fake
   board return 404/429/malformed and see the error run in history with data preserved.
3. **Backend offline**: with no backend, connected-mode screens show an explicit offline state and the
   app stays usable in local mode.
