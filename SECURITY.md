# Security

## Model

RecruitRadar is a single-user, local tool. The static front end has no server and makes no network
calls unless you choose connected mode. The optional backend binds to `127.0.0.1`, has **no
authentication** (it is not meant to be exposed), and CORS only allows the origins listed in
`RECRUIT_RADAR_CORS_ORIGINS` (never `*`).

Because there is no authentication, the backend also refuses any request whose `Host` header is not
`localhost`, `127.0.0.1`, `::1`, its own bind address or a name in `RECRUIT_RADAR_ALLOWED_HOSTS`
(`400 host_not_allowed`). That is the DNS-rebinding guard: a hostile web page that points its own
domain at `127.0.0.1` would otherwise be able to read the API as "same origin". State-changing
requests that carry a foreign `Origin` are refused too (`403 origin_not_allowed`).

## Outbound requests (SSRF-proofing)

- The backend contacts only the three provider hosts (`boards-api.greenhouse.io`,
  `api.lever.co`, `api.ashbyhq.com`) over `https`, with fixed path templates. A user supplies a
  **board token only**, validated against `^[A-Za-z0-9_.-]{1,100}$` and URL-quoted; callers can never
  provide a URL.
- Base URLs are overridable by environment variable **only** so tests can target a local fake
  server; a plain-`http` base is accepted only for loopback hosts.
- Only `GET`. A test asserts that no adapter issues any other method. No cross-host redirects,
  15 s per read and 60 s in total per request (a provider that drips bytes cannot hold a refresh
  open), 10 MB response cap, 5,000-item cap, 60 s minimum between refreshes of a source.
- Fetched job descriptions/HTML are never stored or rendered; only normalized fields are kept.

## Untrusted input

- CSV import: 1 MB / 5,000 rows, strict row-level validation, `http:`/`https:` URLs only, NUL
  refused. Two importers (Python, TypeScript) implement one specified format and are compared on
  shared vectors and by a differential fuzz.
- Rendering uses React escaping; no `dangerouslySetInnerHTML`; links from data open with
  `rel="noopener noreferrer"` and only when the URL scheme is http(s).
- CSV export prefixes text cells starting with `=`, `+`, `-`, `@`, tab or CR (optionally behind
  apostrophes already) with one apostrophe; import removes exactly one again, so the round trip is
  lossless.
- The API validates every request body with Pydantic (`extra="forbid"`) and returns a uniform error
  envelope.

## Secrets and data

No credentials are required or stored. `npm run secrets` scans for common token patterns and
personal e-mail addresses. Data lives in browser `localStorage` (local mode) or a SQLite file under
`backend/data/` (git-ignored). Postings are public job data; no candidate data is handled.

## Reporting

Open a private security advisory on the repository once it is published, or contact the maintainer
through their GitHub profile. Do not post exploit details in public issues.
