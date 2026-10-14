# Known limitations

- **No hosted demo.** The Pages workflow exists but has never run (no remote).
- **The static demo cannot refresh from ATS APIs.** Browsers would hit CORS/policy limits and it
  would put third-party calls in a public page. Live refresh needs the local backend.
- **Provider facts come from documentation, not traffic.** Payload shapes were taken from each
  provider's public docs (2026-10-13); the tests use synthetic payloads in those shapes. None of the
  three documents a rate limit or terms, so the client is deliberately conservative (sequential,
  60 s minimum interval, caps). Check a provider's current terms before using a real board.
- **Ashby has no documented job id.** The id is derived from the job URL, so a changed URL looks
  like a removal plus an addition.
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
- **Single user, no auth.** The backend is meant for `127.0.0.1` only.
- **Accessibility** is covered by automated checks (names, keyboard focus visibility, overflow at
  320/375 px, WCAG AA text contrast in light and dark) and screenshot review; there has been no
  screen-reader session or 200% zoom audit.
- **Browsers tested:** Microsoft Edge (Chromium) locally, Chromium in CI. Firefox and Safari are
  untested.
