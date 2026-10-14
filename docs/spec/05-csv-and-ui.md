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

### CSV details (binding; pinned by `contracts/vectors/csv-import.json`)

Both importers (Python `csv_io.py`, TypeScript `csv.ts`) implement exactly this, and
`contracts/tools/fuzz_csv.py` compares them on generated files. Before this section existed they
disagreed on eight input classes (docs/spec/ambiguities/differential.md D-11).

1. **Text.** U+0000 anywhere refuses the file (`contains_nul`). A leading BOM is ignored. Records end
   at CRLF, LF or a lone CR; a quoted field may contain delimiters, `""` and line breaks.
2. **Quotes.** Spaces and tabs between a delimiter (or the line start) and an opening quote, and
   between a closing quote and the next delimiter or line end, are ignored. Any other text after a
   closing quote makes that row malformed. A quote inside an unquoted field is literal. An
   unterminated quoted field refuses the file (`unterminated_quote`, with the line it opened on).
3. **Blank lines.** A record whose only cell is empty or whitespace-only, quoted or not (`""`), is
   skipped. It still advances the line counter, and does not count against the 5,000-row cap.
4. **Header.** The first non-blank record. Each name is trimmed (spec 01 trim set), lower-cased, and
   every whitespace character (a tab and a no-break space count) or hyphen becomes `_`. Duplicates
   after normalization refuse the file (`duplicate_header`); a blank name is ignored with a warning,
   as is an unknown name; `company_name` and `title` are required (`missing_required_column`); a
   malformed header row refuses the file (`malformed_header`).
5. **Rows.** Fewer cells than the header leave the rest blank. More cells are tolerated only when
   every extra cell is blank (a trailing comma); an extra non-blank cell would shift columns, so the
   row is refused. Malformed quoting and shifted columns each give **one** row-level error (no
   field); the fields of such a row are not validated. Otherwise every invalid field is reported
   with its name. Valid rows are kept.
6. **Cells.** Trimmed with the spec 01 trim set, then, when the result is apostrophes followed by
   `=`, `+`, `-`, `@`, tab or CR (`^'+[=+\-@\t\r]`), exactly one apostrophe is removed. Export adds
   one apostrophe to a cell that matches `^'*[=+\-@\t\r]`, so `'=x` leaves as `''=x` and returns as
   `'=x` (the transform is a bijection).
7. **Limits.** 1,048,576 UTF-8 bytes (a BOM counts) and 5,000 non-blank data records
   (`too_large`, `too_many_rows`). Field limits count Unicode code points.
8. **Warnings.** One per unknown or blank header name; one for a row that replaces an earlier row
   for the same role at the same stated instant ("Same posting as line N ..."); one for a row whose
   `observed_at` is later than the import time (the analysis ignores it until then).
9. **Order of file-level checks:** size, NUL, unterminated quote, empty file, malformed header,
   duplicate header, missing required column, row cap.

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
