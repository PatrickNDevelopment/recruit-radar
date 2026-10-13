# 04 — Read-only ATS adapters

Verified against each provider's official documentation on 2026-10-13. All three are public,
unauthenticated, read-only `GET` JSON endpoints. **Application-submission endpoints must never be
called.** None of the three documents a rate limit or usage terms; the client is therefore
deliberately conservative.

| Provider                     | Endpoint (default base URL)                                                                        | Notes                                                                             |
| ---------------------------- | -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Greenhouse Job Board API     | `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`                         | doc: https://docs.greenhouse.io/job-board.html                                    |
| Lever Postings API           | `GET https://api.lever.co/v0/postings/{site}?mode=json&skip={n}&limit={m}` (EU: `api.eu.lever.co`) | doc: https://github.com/lever/postings-api ; only `published` postings are public |
| Ashby Public Job Posting API | `GET https://api.ashbyhq.com/posting-api/job-board/{name}`                                         | doc: https://developers.ashbyhq.com/docs/public-job-posting-api                   |

Base URLs are configurable (env `RECRUIT_RADAR_GREENHOUSE_BASE_URL`, `…_LEVER_BASE_URL`,
`…_ASHBY_BASE_URL`) **only so tests can target a local fake server**; defaults are the real hosts.
The UI shows the active base host for every refresh.

## Field mapping → RawPosting

**Greenhouse** (`{"jobs":[…],"meta":{"total":n}}`): `source_posting_id = str(job.id)` ·
`title = job.title` · `location = job.location.name` (may be missing) · `url = job.absolute_url` ·
`department = job.departments[0].name` if present · `posted_at = date(job.first_published)` if present
(else null; `updated_at` is NOT a posting date) · `work_mode = "remote"` iff the location tokens contain
`remote`, else `unknown`.

**Lever** (JSON array): `source_posting_id = job.id` · `title = job.text` ·
`location = job.categories.location` · `department = job.categories.department or categories.team` ·
`url = job.hostedUrl` · `posted_at = date(job.createdAt ms)` if present and numeric (the doc page does
not list `createdAt`; treat as optional) · `work_mode`: `workplaceType` `remote→remote`,
`hybrid→hybrid`, `on-site|onsite→onsite`, else `unknown`. Pagination: request `limit=100`; follow
`skip` until a page returns fewer than `limit` items; hard cap 5,000 items total.

**Ashby** (`{"apiVersion":"1","jobs":[…]}`): the docs list **no job id**. `source_posting_id` is the
last non-empty path segment of `jobUrl` if it looks like a UUID/slug (`^[A-Za-z0-9-]{8,}$`), else
`"u_" + sha12(jobUrl)`; a job with neither `jobUrl` nor `applyUrl` is rejected as malformed. ·
`title` · `location = job.location` · `department = job.department or team` · `url = jobUrl` ·
`posted_at = date(publishedAt)` · `work_mode`: `workplaceType` `Remote→remote`, `Hybrid→hybrid`,
`OnSite→onsite`; else `remote` if `isRemote` true; else `unknown`. Skip jobs with `isListed == false`.

`company_name` is always the user-supplied name on the source (provider data is not trusted for it).

## HTTP client policy (all providers)

- Exactly one request per page; no parallel requests; `User-Agent: RecruitRadar/<version> (+read-only)`.
- Connect/read timeout 15 s; response size cap 10 MB; item cap 5,000 → `too_large` (run failed, no snapshot).
- Only `https` to the default hosts (an `http://localhost`/`127.0.0.1` base is allowed _only_ when set
  via the env override). Tokens are validated against `^[A-Za-z0-9_.-]{1,100}$` and URL-quoted — callers
  can never supply a URL.
- No redirects to a different host are followed.
- Error mapping: 404 → `not_found`; 401/403 → `unauthorized`; 429 → `rate_limited` (record
  `Retry-After` seconds if integer); 5xx → `server_error`; transport errors → `network`/`timeout`;
  non-JSON or schema-violating payload → `malformed` (a job missing a required field is dropped and
  counted in `message`; if **all** jobs are invalid → `malformed`).
- Min 60 s between refreshes of one source (`429 too_soon` from our API).
- Success ⇒ snapshot `mode="full"` with every valid job; diff counters come from the engine's replay
  of this snapshot against prior ones.
- Fetched descriptions/HTML are **never stored or rendered**; only the normalized fields above.
