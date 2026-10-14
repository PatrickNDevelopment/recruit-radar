# 02 — Snapshot replay, lifecycle events, scoring, Analysis shape

## 1. `analyze(input) -> Analysis` (pure)

```jsonc
{
  "as_of": "2026-10-13T12:00:00Z", // required, UTC, format YYYY-MM-DDTHH:MM:SSZ
  "profile": { "include_keywords": ["engineer"], "exclude_keywords": ["intern"] },
  "decisions": [{ "a_key": "acme", "b_key": "acme robotics", "decision": "merge" }],
  "snapshots": [
    {
      "snapshot_id": "s1", // unique
      "source_kind": "greenhouse",
      "source_ref": "acme",
      "observed_at": "2026-09-01T08:00:00Z",
      "mode": "full", // "full": list is everything published (absence = removal)
      // "additive": import; absence means nothing
      "postings": [{/* RawPosting without observed_at, see 01 */}],
    },
  ],
}
```

Snapshots with `observed_at > as_of` are ignored entirely. All timestamps are UTC, whole seconds.
`day math`: `days_between(a, b) = floor((epoch(b) - epoch(a)) / 86400)` using epoch seconds; `posted_at`
is `YYYY-MM-DD` interpreted as `00:00:00Z`. Negative results clamp to 0 where "age/days" is reported.

## 2. Replay (per source role key; see 01 §4)

Process snapshots sorted by `(observed_at, snapshot_id)`. The _first processed snapshot of each
`(source_kind, source_ref)`_ is that source's **baseline**. For snapshot _s_ of source _S_:

1. For each posting in listed order, compute its source role key. If the same key already occurred
   earlier in this snapshot, the later posting replaces the earlier one (last wins; no event for the
   superseded one).
2. For each distinct key, in order of last occurrence:
   - **unknown role** → create (`status=active`, `first_seen=last_seen=observed_at`); event
     `baseline` if _s_ is the baseline snapshot of _S_, else `added`.
   - **known, active** → compare tracked fields `title, location, work_mode, department, url,
posted_at` (raw trimmed values; null vs null equal). If any differ: event `changed` with
     `fields` = sorted list of names that differ. Update fields. Set `last_seen`.
   - **known, removed** → `status=active`, `removed_at=null`, event `reappeared`, update fields,
     `last_seen`.
3. If `mode == "full"`: every role of _S_ that is active and was NOT listed in _s_ becomes
   `removed` (`removed_at = observed_at`), event `removed`, processed in ascending source-role-key
   string order after step 2. (`additive` snapshots never remove.)

Events carry: `at`, `type`, source role key parts, `title` (title at event time; for `changed` the
_new_ title), `fields` (changed only, else null). Events are emitted in processing order.

Company assignment uses the **latest** `company_name` of the source role and the decisions in force
at the end of replay (identity is resolved after replay, so merges apply to history).

## 3. Canonical roles and company aggregates (after replay)

Apply 01 §3–§4. For each canonical role: `status = active` iff any member source role is active;
`first_seen = min`, `last_seen = max over active members` (all members if none active);
`removed_at` = max member `removed_at` if not active else null; `posted_at = min non-null`
(else null); display fields (`title`, `location`, `work_mode`, `department`) from the member with
the greatest `last_seen` (ties: smallest source role key string).
`relevant`: null when `include_keywords` empty; else true iff some include keyword matches
(`token_sequence_match` on the displayed title's `title_key`) and no exclude keyword matches.

## 4. Scoring (integers 0..1000; per company)

Let `A` = active canonical roles of the company, `R` = those with `relevant == true`.
`scope` = `R` if keywords configured, else `A`. `rhu(num, den) = floor((2*num + den) / (2*den))`.
`T` = observed_at of `mode == "full"` snapshots (≤ as_of) of every source that ever supplied a
source role to this company; `span_days = days_between(min T, max T)` if `|T| ≥ 2` else null.

| key (order)         | weight | value                                                    | null reason_code (precedence top→bottom)                                        |
| ------------------- | -----: | -------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `role_relevance`    |     30 | `rhu(1000*                                               | R                                                                               | ,      | A                                   | )`  | `no_active_roles` (A=0); `no_keywords` |
| `volume`            |     20 | `[0,300,480,600,690,760,820,870,910,950,1000][min(       | scope                                                                           | ,10)]` | `no_active_roles`                   |
| `change`            |     15 | `clamp(500 + 100*net, 0, 1000)`, `net = added - removed` | `no_active_roles`; `insufficient_history` (`                                    | T      | <2`or`span_days<14`)                |
| `urgency`           |     10 | `rhu(1000*aged, known)`                                  | `no_active_roles`; `no_scope_roles` (scope empty); `no_dated_roles` (`known=0`) |
| `source_confidence` |     15 | `rhu(Σ role_conf,                                        | scope                                                                           | )`     | `no_active_roles`; `no_scope_roles` |
| `freshness`         |     10 | see below                                                | `no_active_roles`                                                               |

- **change**: count events with `as_of - 30d < at ≤ as_of` (`30d = 2592000 s`) whose role is
  "in scope by title": include-keyword match (and no exclude match) on the event title's `title_key`
  — or every event when no keywords are configured. `added` = count of `added` + `reappeared`;
  `removed` = count of `removed`. `baseline` and `changed` events never count.
- **urgency**: for each role in `scope`: `age = days_between(posted_at, as_of)` if `posted_at` non-null;
  else `days_between(first_seen, as_of)` only if `span_days != null && span_days ≥ 45`; else unknown.
  `known` = roles with known age; `aged` = those with `age ≥ 45`. (A possible signal only; the UI must
  say so.)
- **role_conf** for a scope role: `best = max` over its _active_ observations of source weight
  (`greenhouse|lever|ashby = 1000`, `csv = 600`, `manual = 400`); if its active observations span ≥2
  distinct `(source_kind, source_ref)` → `min(1000, best+100)` and count it in `corroborated`.
- **freshness**: `last_seen` = max `last_seen` over A; `d = max(0, days_between(last_seen, as_of))`;
  value `1000` if `d ≤ 7`; `0` if `d ≥ 60`; else `rhu(1000*(60 - d), 53)`.

`inputs` objects (all keys always present; non-computable ⇒ `null`; constants always set):

| component         | inputs                                              |
| ----------------- | --------------------------------------------------- |
| role_relevance    | `{relevant, active}`                                |
| volume            | `{scope_roles}`                                     |
| change            | `{added, removed, net, span_days, window_days: 30}` |
| urgency           | `{aged, known, threshold_days: 45}`                 |
| source_confidence | `{scope_roles, corroborated}`                       |
| freshness         | `{days_since_last_seen}`                            |

When `A == 0` every component is null with `no_active_roles` and: `relevant:null, active:0`,
`scope_roles:0`, change `{added:null,removed:null,net:null,span_days:<computed or null>,window_days:30}`,
urgency `{aged:null,known:null,threshold_days:45}`, confidence `{scope_roles:0,corroborated:null}`,
freshness `{days_since_last_seen:null}`.
For `no_keywords`: `{relevant:null, active:A}`. For `no_scope_roles`/`no_dated_roles`/`insufficient_history`
the other computable inputs stay filled (e.g. urgency `no_dated_roles` ⇒ `{aged:0, known:0, ...}`;
`insufficient_history` ⇒ `{added:null, removed:null, net:null, span_days:<span or null>, ...}`).

**Overall**: `W = Σ weight` of non-null components (this is `coverage`, 0..100). If `W == 0`:
`score = null`. Else `score = rhu(Σ weight*value, W)` (0..1000). UI shows `score/10` with one decimal.

**Rank**: companies with non-null score sorted by `(score desc, key asc, company_id asc)`;
`rank` is the 1-based position. Others `rank = null`.

## 5. Analysis output shape (JSON; key order irrelevant, array order significant)

```jsonc
{
  "as_of": "…",
  "companies": [
    {
      "company_id": "c_ab12cd34ef56",
      "key": "acme",
      "name": "Acme Inc.",
      "aliases": ["ACME", "Acme Inc."],
      "first_seen": "…",
      "last_seen": "…" /* null if never active */,
      "active_roles": 3,
      "relevant_roles": 2 /* null w/o keywords */,
      "removed_roles": 1,
      "score": 640 /* or null */,
      "coverage": 90,
      "rank": 1 /* or null */,
      "components": [
        {
          "key": "role_relevance",
          "weight": 30,
          "value": 667,
          "reason_code": null,
          "inputs": { "relevant": 2, "active": 3 },
        } /* … all 6, fixed order … */,
      ],
    },
  ],
  "roles": [
    {
      "role_id": "r_…",
      "company_id": "c_…",
      "title": "…",
      "location": null,
      "work_mode": "remote",
      "department": null,
      "posted_at": null,
      "status": "active",
      "first_seen": "…",
      "last_seen": "…",
      "removed_at": null,
      "relevant": true /* or null */,
      "age_days": 12 /* or null */,
      "observations": [
        {
          "source_kind": "greenhouse",
          "source_ref": "acme",
          "source_posting_id": "123",
          "url": null,
          "status": "active",
          "first_seen": "…",
          "last_seen": "…",
        },
      ],
    },
  ],
  "events": [
    {
      "at": "…",
      "type": "added",
      "company_id": "c_…",
      "role_id": "r_…",
      "source_kind": "…",
      "source_ref": "…",
      "title": "…",
      "fields": null,
    },
  ],
  "merge_candidates": [
    {
      "candidate_id": "…",
      "a_key": "…",
      "b_key": "…",
      "a_name": "…",
      "b_name": "…",
      "reason": "spacing_variant",
    },
  ],
  "stats": { "snapshots": 2, "postings_observed": 9, "companies": 4, "active_roles": 7 },
}
```

- `aliases`: distinct raw company names (trimmed) of the company's postings, sorted by code point.
- `age_days` on roles: as in urgency but without the 45-day span rule: `posted_at` if present, else
  `days_between(first_seen, as_of)`; never null for any role (first_seen always exists). Clamp ≥ 0.
- `observations` sorted by `(source_kind, source_ref, source_posting_id or "")`.
- `companies` order: ranked companies (rank asc), then unscored by `(key, company_id)`.
- `roles` order: by company order, then `status` (active first), then `first_seen`, then `role_id`.
- `stats.postings_observed` = total postings across processed snapshots (after the as_of filter).

## 6. Clarifications from the differential review (binding)

- `T` is the **set** of distinct `observed_at` instants of full snapshots; `|T|` counts instants, not
  snapshots (two sources observed at the same instant give `|T| = 1`).
- `as_of` and each `observed_at` must match `YYYY-MM-DDTHH:MM:SSZ` exactly (no padding, no trimming).
- Unknown input keys are ignored. An omitted `snapshots` or `postings` is empty; `null` is invalid.
- Keywords: at most 50 per list, each at most 60 code points after trimming; blank keywords never match.
