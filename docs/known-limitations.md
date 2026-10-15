# Known limitations

- **Hosted demo is local-data mode only.** https://patrickndevelopment.github.io/recruit-radar/ is static GitHub Pages; connected mode needs the local backend.
- **The static demo cannot refresh from ATS APIs.** Browsers would hit CORS/policy limits and it
  would put third-party calls in a public page. Live refresh needs the local backend.
- **Provider facts come from documentation, not recorded traffic.** Payload shapes were taken from
  each provider's public docs (2026-10-13) and the automated tests use synthetic payloads in those
  shapes. The independent acceptance review (2026-10-14) additionally made one real read-only
  refresh per provider through the product (Greenhouse's own board, Lever's documented `leverdemo`
  site, Ashby's own board): all three answered in the documented shapes, with dates, URLs,
  departments and locations mapped. That was a one-off check, not a test in the suite. None of the
  three documents a rate limit or terms, so the client is deliberately conservative (sequential,
  60 s minimum interval, caps). Check a provider's current terms before using a real board.
- **Ashby has no documented job id.** The id is derived from the job URL, so a changed URL looks
  like a removal plus an addition.
- **Greenhouse `first_published` is only documented on the single-job endpoint, and Lever's
  `createdAt` is not documented at all.** Live boards returned both in the list responses; when a
  board omits one the role has no posting date (its age is then estimated only from a history of
  45 days or more).
- **The two shortlist exporters word the evidence column differently.** The columns, order and
  numbers are identical in local-data and connected mode (and both write a UTF-8 BOM); only the
  sentences in `strongest_evidence` / `missing_information` differ slightly.
- **Lever `createdAt` is undocumented.** When present it is used as the posting date; when absent
  the role has no posting date.
- **Scores are heuristics.** Weights and thresholds are fixed by the spec, not learned. There is no
  semantic title matching: keywords match whole words/phrases in titles only.
- **"Change" needs history.** It requires at least two full-list refreshes at least 14 days apart;
  CSV imports and manual entries are not full lists and cannot show removals.
- **"Possible urgency" is a proxy** (share of postings listed 45+ days) and is labeled as such.
- **Identity resolution is name-based.** Different companies with the same name merge; renames and
  subsidiaries need a manual merge decision.
- **Unicode database skew.** Python 3.14 (Unicode 16) and Node 24 (Unicode 17) disagree on 4,699
  newly assigned code points; names using them may normalize differently across modes.
- **Local storage limits.** Local-data mode is per-browser and subject to the browser's quota
  (workspace capped at 5,000 postings); there is no sync. Another tab's changes are detected and
  flagged, not merged.
- **Single user, no auth.** The backend is meant for `127.0.0.1` only. It refuses requests whose
  `Host` header is not loopback, its bind address or `RECRUIT_RADAR_ALLOWED_HOSTS` (DNS-rebinding
  guard), so browsing to it by another name needs that variable.
- **A public page reaching a local backend is up to the browser.** "Use the backend" from a
  published page sends requests to `127.0.0.1`; whether the browser allows a public page to do that
  (local-network access prompts or blocks) was not tested because nothing is published. The app
  explains the CORS and offline cases it can observe.
- **Connected mode cannot remove a single dataset or export raw postings** (the backend has no
  endpoint for either); "Erase all data" wipes the database. Local-data mode has both.
- **Large inputs.** A 5,000-row import takes about a second; the radar renders every company
  (1,000 companies stay responsive, there is no virtualization), and merge candidates are shown 25
  at a time.
- **Accessibility** is covered by automated checks (names, keyboard focus visibility, overflow at
  320/375 px, WCAG AA text contrast in light and dark) and screenshot review; there has been no
  screen-reader session or 200% zoom audit.
- **Browsers tested:** Microsoft Edge (Chromium) locally, Chromium in CI. Firefox and Safari are
  untested.
