# Demo walkthrough

Labels below are the real UI labels.

## Journey 1: overlapping datasets in local-data mode (no backend)

1. `npm run dev`, open `http://localhost:5173/recruit-radar/`.
2. **Settings** → **Where should data come from?** → **Always local-data mode**.
3. **Data** → **Load sample data** (two overlapping datasets of invented companies; the banner
   "Synthetic sample data — invented companies, not real hiring data." appears), or import your own
   two CSVs under different dataset labels.
4. **Radar**: duplicates that are equal after normalization (case, punctuation, legal suffixes)
   are already one company; look-alikes such as "Cedar Point Robotic" / "Cedar Point Robotics"
   stay separate.
5. **Data → Merge review**: each candidate says why it was flagged. **Merge as one company** or
   **Not the same company**; both are reversible from "Your decisions".
6. Open a company: read the **Score breakdown** and **Missing information**; add a qualification
   note and **Save note and add to shortlist**.
7. **Data → Export shortlist CSV**.

## Journey 2: connected refresh (backend + a board)

1. Start the backend (`cd backend && python -m recruit_radar`) and reload the app (Settings →
   Automatic).
2. **Sources** → provider **Greenhouse**, a board token, a company name → **Add source** →
   **Refresh**. (To try it without a real board, run `python e2e/fake-ats/server.py` and start the
   backend with the `RECRUIT_RADAR_*_BASE_URL` variables pointing at it, as the Playwright suite
   does.)
3. **History** shows the run: status, provider host, seen/added/changed/removed/listed-again
   counts. The Radar and company pages now show the normalized roles with links to the posting.
4. Refresh again after the board changes: **Role changes in the last successful run** lists
   changed (with the changed fields), no longer listed, added and listed-again roles with
   timestamps.
5. When a refresh fails (404, 401/403, 429 with Retry-After, 5xx, malformed answer) the run is
   recorded with a plain explanation and everything already stored is left untouched.

## Things to try

- Import a CSV with a bad URL or an impossible date: each bad row is reported by line number and
  the valid rows are kept.
- Point the backend address at a dead port and choose **Use the backend**: the app explains it
  cannot reach it and falls back to local-data mode.
- Add role keywords in **Settings** and watch relevance, volume and every score recalculate.
