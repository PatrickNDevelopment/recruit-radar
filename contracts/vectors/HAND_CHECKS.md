# Hand checks

How the oracle was cross-checked. For 21 of the smallest analysis vectors (42 company results) plus the
candidate lists, event orders, observation pairing and role timestamps of 8 more, the per-component values,
coverage, score and rank were derived
**by hand from `docs/spec/02` sections 4-5 and the vector's input only**, and typed into
`contracts/tools/oracle.py` (`HAND_DERIVED`, `HAND_CANDIDATES`, `HAND_EVENTS`, `HAND_OBSERVATIONS`,
`HAND_ROLE_TIMES`) _before_ the oracle was first run on these vectors. `oracle.py --self-check` asserts every number below against the committed files.

**Result: all 42 company results, 11 candidate lists (with independently computed ids), 7 event orders, 2
observation pairings and 1 set of role timestamps agreed with the oracle on the first run. No oracle change
was needed.** (Vectors added or changed after the first round - HC-17 to HC-23 and the d=61/d=400 rows of
HC-03 - were hand-derived the same way, before the oracle saw them, and agreed as well.) (The self-check was also shown to
fail when a hand value or a vector file is deliberately corrupted.)

What this does and does not prove: hand derivation and oracle were written by the same author from the same
reading of the spec, so this catches arithmetic and coding slips (rounding, boundary operators, ordering) but
not a _shared misreading_. Those risks are listed, with the reading taken, in
`docs/spec/ambiguities/vectors.md`, and every vector except the three added after the differential review
(45-47, which _pin_ a decided reading, see README) is proven insensitive to the alternatives that could be
machine-checked.

Notation: `rhu(n,d) = floor((2n+d)/(2d))`. `days(a,b) = floor((b-a)/86400 s)`. `as_of = 2026-10-13T12:00:00Z`
unless stated; `as_of-30d = 2026-09-13T12:00:00Z`. Weights: relevance 30, volume 20, change 15, urgency 10,
confidence 15, freshness 10. `W` = sum of weights of non-null components = `coverage`.
`score = rhu(sum(weight*value), W)`. Day-of-year helper (2026 is not leap): Aug 1 = 213, Sep 1 = 244,
Oct 1 = 274; Oct 13 = 286.

---

## HC-01 `minimal-single-role` - key `software house`

Input: greenhouse full snapshot 2026-10-10T12:00:00Z, one role "Software Engineer" (no posted_at), keywords
include `engineer`.

- A = 1; `title_key = "software engineer"` contains token `engineer` so R = 1; scope = R = 1.
- relevance: rhu(1000*1, 1) = floor(2001/2) = **1000**.
- volume: table[1] = **300**.
- change: T = {10-10T12:00}, |T| = 1 -> **null** `insufficient_history`.
- urgency: posted_at null, span null -> unknown, known = 0 -> **null** `no_dated_roles`, inputs {0,0,45}.
- confidence: greenhouse 1000, one active observation -> rhu(1000,1) = **1000**, corroborated 0.
- freshness: d = days(10-10T12:00, 10-13T12:00) = 3 <= 7 -> **1000**.
- W = 30+20+15+10 = **75**. Sum = 30000+6000+15000+10000 = 61000. score = floor((122000+75)/150) =
  floor(813.83) = **813**. rank **1**.
  Oracle: agreed.

## HC-02 `name-variants-collapse` - key `acme`

Input: four sources at 2026-10-12T09:00:00Z; names `Acme` (greenhouse, 2 roles), `ACME Inc.` (csv),
`acme, inc` (manual), `The Acme Corporation` (csv, other title). No keywords.

- Keys: `Acme`->acme; `ACME Inc.`->tokens [acme,inc]->acme; `acme, inc`->acme; `The Acme Corporation`->
  tokens [the,acme,corporation]->drop `corporation`, drop `the`->acme. **One company.**
- Name: all four postings share `observed_at`, so smallest raw name by code point. Code points: `A`(41)
  `C`(43) < `A`(41) `c`(63) < `T`(54) < `a`(61): **`ACME Inc.`**. Aliases sorted: `ACME Inc.`, `Acme`,
  `The Acme Corporation`, `acme, inc`.
- Roles: "Backend Engineer" at `Austin, TX` / `TX - Austin` / `Austin TX` all give location_key
  `austin tx` -> one canonical role with 3 observations; "Product Designer"; "Data Analyst" -> A = 3.
- relevance null `no_keywords`. volume table[3] = **600**. change: one full snapshot -> null. urgency: null
  `no_dated_roles`.
- confidence: Backend: best 1000, 3 distinct sources -> min(1000,1100) = 1000 (corroborated); Designer 1000
  (greenhouse); Analyst csv 600. Sum = 2600; rhu(2600,3) = floor(5203/6) = **867**; corroborated 1.
- freshness: d = days(10-12T09:00, 10-13T12:00) = 1 -> **1000**.
- W = 20+15+10 = **45**. Sum = 12000+13005+10000 = 35005. score = floor((70010+45)/90) = floor(778.39) =
  **778**. rank 1.
  Oracle: agreed.

## HC-03 `freshness-boundaries` - nine single-role companies, no keywords

Each: relevance null, volume table[1] = 300, change null (one snapshot), urgency null, confidence 1000.
W = 20+15+10 = 45. Sum = 6000 + 15000 + 10*F = 21000 + 10F.

| company      | snapshot            | d                 | F                                                 | sum   | score = floor((2*sum+45)/90) | rank |
| ------------ | ------------------- | ----------------- | ------------------------------------------------- | ----- | ---------------------------- | ---- |
| amberly      | 10-13T12:00:00      | 0                 | 1000                                              | 31000 | floor(62045/90) = **689**    | 1    |
| birchwood    | 10-06T12:00:00      | 7                 | 1000                                              | 31000 | **689**                      | 2    |
| cedarville   | 10-05T12:00:01      | 7 (7d 23:59:59)   | 1000                                              | 31000 | **689**                      | 3    |
| dahlia works | 10-05T12:00:00      | 8                 | rhu(52000,53) = floor(104053/106) = **981**       | 30810 | floor(61665/90) = **685**    | 4    |
| elmstead     | 08-15T12:00:00      | 59                | rhu(1000,53) = floor(2053/106) = **19**           | 21190 | floor(42425/90) = **471**    | 5    |
| fjordhaven   | 08-14T12:00:01      | 59 (59d 23:59:59) | **19**                                            | 21190 | **471**                      | 6    |
| granite quay | 08-14T12:00:00      | 60                | **0** (d >= 60)                                   | 21000 | floor(42045/90) = **467**    | 7    |
| hollowell    | 08-13T12:00:00      | 61                | **0** (d >= 60; the formula alone would give -19) | 21000 | **467**                      | 8    |
| ivywood      | 2025-09-08T12:00:00 | 400               | **0**                                             | 21000 | **467**                      | 9    |

Day checks: 10-13 minus 7 d = 10-06 (d=7). 10-05T12:00:01 is 8 d minus 1 s -> floor = 7. Aug 15 = day 227,
Oct 13 = 286 -> 59. 08-14T12:00:01 is 60 d minus 1 s -> 59; 08-14T12:00:00 is exactly 60. Ties at 689 and
471 are ordered by key ascending (amberly < birchwood < cedarville; elmstead < fjordhaven).
Oracle: agreed (all 9).

## HC-04 `change-span-14-vs-13` - `xray xylem`, `yankee yards`

Both: two greenhouse full snapshots, second adds role 2 "Designer"; no keywords; no posted_at.

- **Xray**: 2026-09-01T00:00:00Z -> 2026-09-15T00:00:00Z: days = 14*86400/86400 = **14** (>= 14 OK).
  A = 2. volume table[2] = 480. Event `added` at 09-15T00:00 > 09-13T12:00 -> added 1, removed 0, net 1 ->
  clamp(500+100) = **600**. urgency: span 14 < 45 and no posted_at -> known 0 -> null. confidence 1000.
  freshness: last_seen 09-15T00:00 -> as_of = 28 d 12 h -> d = 28; rhu(1000*32, 53) = floor(64053/106) =
  **604**. W = 20+15+15+10 = **60**. Sum = 9600+9000+15000+6040 = 39640. score = floor((79280+60)/120) =
  floor(661.17) = **661**.
- **Yankee**: 09-01T00:00:00Z -> 09-14T23:59:59Z = 13 d 23:59:59 -> days = **13** (< 14) -> change null
  `insufficient_history`, `span_days: 13`. volume 480, confidence 1000, freshness: 09-14T23:59:59 -> as_of =
  28 d 12 h 0 m 1 s -> d = 28 -> 604. W = 45. Sum = 9600+15000+6040 = 30640. score = floor((61280+45)/90) =
  floor(681.39) = **681**.
- Rank: Yankee 681 > Xray 661 (a company with _less_ history can outrank: coverage normalizes).
  Oracle: agreed.

## HC-05 `urgency-44-vs-45` - `tern analytics`

as_of = **2026-10-13T00:00:00Z**; snapshot 2026-10-12T00:00:00Z; include `engineer`; roles "Platform
Engineer" (posted 2026-08-29) and "Data Engineer" (posted 2026-08-30).

- Ages: Aug 29 -> Oct 13: (Aug 29 -> Sep 29 = 31) + (Sep 29 -> Oct 13 = 14) = **45** -> aged (>= 45).
  Aug 30 -> **44** -> not aged. known 2, aged 1.
- relevance: A=2, R=2 -> rhu(2000,2) = floor(2002/4) = **1000**. volume table[2] = **480**. change null.
- urgency: rhu(1000*1, 2) = floor(2002/4) = **500**.
- confidence 1000. freshness: d = 1 -> **1000**.
- W = 30+20+10+15+10 = **85**. Sum = 30000+9600+5000+15000+10000 = 69600. score = floor((139200+85)/170) =
  floor(819.32) = **819**.
  Oracle: agreed.

## HC-06 `cross-source-corroboration` - `acme`

greenhouse (10-01, full): Staff Engineer, QA Engineer; csv (10-02, additive): Staff Engineer, Sales Lead;
manual (10-03, additive): Sales Lead, Ops Coordinator. No keywords.

- Canonical roles: Staff {gh,csv}, QA {gh}, Sales {csv,manual}, Ops {manual} -> A = 4.
- volume table[4] = **690**. change: T = {10-01} (csv/manual are additive) -> null. urgency null.
- confidence: Staff best max(1000,600) = 1000, two sources -> min(1000,1100) = 1000; QA 1000; Sales best
  max(600,400) = 600 -> 700; Ops 400. Sum 3100; rhu(3100,4) = floor(6204/8) = **775**; corroborated 2.
- freshness: last_seen = 10-03T00:00 -> 10 d 12 h -> d = 10; rhu(50000,53) = floor(100053/106) = **943**.
- W = 45. Sum = 13800+11625+9430 = 34855. score = floor((69710+45)/90) = floor(775.06) = **775**.
  Oracle: agreed.

## HC-07 `keyword-token-sequence-and-exclude` - `kestrel`

include `engineer`, `machine learning`; exclude `intern`; eight titles, snapshot 2026-10-11T12:00:00Z.

| title                          | title_key tokens             | include                            | exclude                | relevant |
| ------------------------------ | ---------------------------- | ---------------------------------- | ---------------------- | -------- |
| Senior Engineer                | senior engineer              | `engineer`                         | -                      | yes      |
| Engineering Manager            | engineering manager          | none (`engineering` != `engineer`) | -                      | no       |
| Engineer Intern                | engineer intern              | `engineer`                         | `intern`               | no       |
| Internal Tools Engineer        | internal tools engineer      | `engineer`                         | `intern` != `internal` | yes      |
| Manager (Engineer track)       | manager (bracket removed)    | none                               | -                      | no       |
| Machine Learning Researcher    | machine learning researcher  | `machine learning`                 | -                      | yes      |
| Learning Machine Operator      | learning machine operator    | order wrong                        | -                      | no       |
| Machine Vision & Learning Lead | machine vision learning lead | not adjacent                       | -                      | no       |

- A = 8, R = 3: relevance rhu(3000,8) = floor(6008/16) = **375**. volume (scope 3) table[3] = **600**.
- change null, urgency null (`no_dated_roles`). confidence: 3 greenhouse -> **1000**. freshness d = 2 ->
  **1000**. W = 30+20+15+10 = **75**. Sum = 11250+12000+15000+10000 = 48250. score =
  floor((96500+75)/150) = floor(643.83) = **643**.
  Oracle: agreed.

## HC-08 `change-window-30d-edges` - `marsh`

Greenhouse full snapshots: s1 08-20T00:00 [1,2,3]; s2 09-13T12:00:00 [1,2,3,4]; s3 09-13T12:00:01
[1,2,3,4,5]; s4 10-13T12:00:00 (= as_of) [1,2,4,5].

- Window `(09-13T12:00:00, 10-13T12:00:00]`. Events: baseline x3 (never counted); `added` role 4 at
  09-13T12:00:00 -> `at > as_of-30d` is **false** (excluded); `added` role 5 at 09-13T12:00:01 -> in;
  `removed` role 3 at 10-13T12:00:00 -> `at <= as_of` true (in). added 1, removed 1, net 0 -> **500**.
- span: days(08-20T00:00, 10-13T12:00) = 54 d 12 h -> **54** (>= 14 OK, >= 45 OK).
- A = 4 -> volume table[4] = **690**. No keywords -> relevance null.
- urgency (span rule satisfied): first_seen ages: roles 1,2: 54 (aged); role 4: first_seen 09-13T12:00:00
  -> exactly 30 d -> 30 (no); role 5: 09-13T12:00:01 -> 29 d 23:59:59 -> 29 (no). known 4, aged 2 ->
  rhu(2000,4) = floor(4004/8) = **500**.
- confidence 1000. freshness: last_seen 10-13T12:00 = as_of -> d = 0 -> **1000**.
- W = 20+15+10+15+10 = **70**. Sum = 13800+7500+5000+15000+10000 = 51300. score = floor((102600+70)/140) =
  floor(733.36) = **733**.
  Oracle: agreed.

## HC-09 `all-roles-removed` - `ghost kitchen` and `live oak`

- **Ghost Kitchen Co**: greenhouse s1 09-01 [Chef, Dishwasher], s2 09-20 `[]` (full) -> both removed.
  A = 0 -> every component null `no_active_roles`; W = 0 -> **score null, coverage 0, rank null**,
  last_seen null, removed_roles 2. `change.inputs.span_days = days(09-01, 09-20) = 19` (two full
  snapshots), other change inputs null; `source_confidence.inputs = {scope_roles: 0, corroborated: null}`.
- **Live Oak**: one role, snapshot 10-10T00:00 -> volume 300, confidence 1000, freshness d = 3 -> 1000;
  W = 45; score floor((62000+45)/90) = **689**, rank 1.
- Order: ranked Live Oak first, unscored Ghost last.
  Oracle: agreed.

## HC-10 `score-ties-order-by-key` - five companies

Each: one role, one snapshot at 2026-10-12T12:00:00Z (d = 1), no keywords: volume 300, confidence 1000,
freshness 1000, W = 45 -> **689** for all. (The display names are `Zebra Works`, `alpha works`, ...: as
_names_ `Zebra Works` < `alpha works`, as _keys_ the reverse - the rank follows the key.) Ranking is by key ascending _by code point_:
`7 seas` (U+0037) < `alpha works` (U+0061) < `zebra works` (U+007A) < `<e-acute>mile works` (U+00E9) <
`<omega>mega works` (U+03C9) -> ranks 1..5.
Oracle: agreed.

## HC-11 `no-scope-roles` - `plum row`

include `engineer`; greenhouse full snapshots 09-20T00:00 and 10-05T00:00 listing "Marketing Manager" and
"Sales Lead" both times.

- A = 2, R = 0, scope = empty. relevance rhu(0,2) = floor(2/4) = **0**. volume table[0] = **0**.
- span = days(09-20, 10-05) = 15 >= 14 -> change computed; only baselines -> added 0, removed 0 -> **500**.
- urgency null `no_scope_roles` {aged 0, known 0}; confidence null `no_scope_roles` {scope_roles 0,
  corroborated 0}.
- freshness: last_seen 10-05T00:00 -> 8 d 12 h -> d = 8 -> **981**.
- W = 30+20+15+10 = **75**. Sum = 0+0+7500+9810 = 17310. score = floor((34620+75)/150) = floor(231.3) =
  **231**.
  Oracle: agreed.

## HC-12 `urgency-posted-at-vs-first-seen-span-rule` - three companies, no keywords

- **Pine Harbor**: snapshots 08-01T00:00 and 09-15T00:00 -> span = 31 (Aug) + 14 = **45** (>= 45 OK).
  Roles: #1 undated, first_seen 08-01 -> 73 d (aged); #2 posted 2026-10-01 -> 12 d (posted_at wins over
  first_seen 08-01; not aged); #3 undated, first_seen 09-15 -> 28 d. known 3, aged 1 -> rhu(1000,3) =
  floor(2003/6) = **333**. A = 3 -> volume 600. change: `added` #3 at 09-15 in window -> net 1 -> **600**.
  confidence 1000. freshness: 09-15T00:00 -> d = 28 -> 604. W = 70. Sum = 12000+9000+3330+15000+6040 = 45370. score = floor((90740+70)/140) = floor(648.64) = **648**.
- **Quartz Mill**: 08-01T00:00 and 09-14T23:59:59 -> 44 d 23:59:59 -> span **44** (< 45). #1 posted
  2026-08-01 -> 73 d (aged); #2 undated and span < 45 -> unknown. known 1, aged 1 -> **1000**. volume 480.
  change: no non-baseline events -> 0/0 -> **500** (span 44 >= 14). confidence 1000. freshness: d = 28 -> 604. W = 70. Sum = 9600+7500+10000+15000+6040 = 48140. score = floor((96280+70)/140) = floor(688.2) =
  **688**.
- **Raven Press**: one snapshot 10-01T00:00; volume 300; change null; urgency null; confidence 1000;
  freshness: 12 d 12 h -> d = 12; rhu(48000,53) = floor(96053/106) = **906**. W = 45. Sum =
  6000+15000+9060 = 30060. score = floor((60120+45)/90) = floor(668.5) = **668**.
- Rank: Quartz 688, Raven 668, Pine 648.
  Oracle: agreed (all 3).

## HC-13 `headcounts-two-roles-same-source` - `support house`

include `engineer`; one greenhouse snapshot (10-09T12:00) with ids 201, 202 ("Support Engineer", Berlin)
and 203 (Munich).

- Distinct source role keys -> never merged within a source: A = 3 (two Berlin headcount, one Munich); all
  match `engineer` so R = 3. Role ids differ by group index (`...|berlin|0` and `...|berlin|1`).
- relevance 1000; volume table[3] = 600; change null; urgency null; confidence 1000; freshness d = 4 -> 1000.
- W = 75. Sum = 30000+12000+15000+10000 = 67000. score = floor((134000+75)/150) = floor(893.8) = **893**.
  Oracle: agreed.

## HC-14 `duplicate-keys-last-wins` - `acme`

One snapshot (2026-10-10T00:00) in listed order: `a` "Engineer v1", `b` "Designer", `a` "Engineer v2",
`n1` "Office Manager", `n1` "Office Manager" (dept Facilities).

- Distinct keys by _last_ occurrence: b (index 1), a (2), n1 (4) -> events `baseline`: Designer, Engineer v2,
  Office Manager. The superseded posting makes no event; role `a` has title "Engineer v2". postings_observed 5.
- A = 3: volume 600; confidence 1000; freshness d = 3 -> 1000; W = 45. Sum = 12000+15000+10000 = 37000.
  score = floor((74000+45)/90) = floor(822.7) = **822**.
  Oracle: agreed.

## HC-15 candidate lists (reasons by hand; ids by a bare `hashlib` call)

- `merge-candidates-three-reasons`: keys `doordash`/`door dash` -> equal after removing spaces ->
  `spacing_variant` (a = `door dash` since `' '` U+20 < `d`); `blue ocean shipping` (3 tokens) vs
  `blue ocean shipping group` (4): |A n B| = 3, |A u B| = 4, 3*100 = 300 >= 75*4 = 300 -> `token_overlap`;
  `acme robotic`/`acme robotics`: both >= 6 cp, Levenshtein 1 -> `near_typo`. Order: spacing, overlap,
  typo. Ids: sha12(`door dash|doordash`) = `ab57d53a978a`, sha12(`blue ocean shipping|blue ocean shipping
group`) = `5dda8a28b3a6`, sha12(`acme robotic|acme robotics`) = `e9c738f08ae2`.
- `candidate-reason-precedence`: 9 shared of 12 tokens (spacing wins, although also 75% and distance 1);
  6 of 8 = 75% (token_overlap wins over near_typo); 7 of 9 = 77.8% -> token_overlap; 2 of 3 = 66.7% -> none.
- `near-typo-boundaries`: nordic/nordik and quantum/quantom (distance 1, both >= 6) yes; google (6) /
  gogle (5) no; hooli (5) / hoolie (6) no; initech/intiech distance 2 no; six astral code points differing
  in one code point yes; five astral code points no.
- `candidate-code-point-order`: `rocket <U+FE0F>` vs `rocket <U+20000>`: distance 1, 8 code points each ->
  near_typo; a_key is the one whose last token is U+FE0F (0xFE0F < 0x20000).
- `not-same-hides-candidate`: only the near_typo pair remains. The two merge vectors: no candidate.
  Oracle: agreed.

## HC-16 event orders

- `snapshot-order-id-tiebreak`: `s10`, `s2`, `snap-a`, `snap-b` at one instant sort as strings
  ("s1" < "s2" at index 1; "s2" < "sn" at index 1): alpha baseline, beta baseline, csv `Rigger` baseline
  (snap-a is csv's first), then in snap-b `Rigger` unchanged (no event) and `Fitter` **added**.
- `all-roles-removed`: the roles are listed in the order 2, 1; baselines follow listing order (Dishwasher,
  Chef) but the empty full snapshot removes them in ascending key order (1, 2): Chef, then Dishwasher.
- `duplicate-keys-last-wins`, `removal-then-reappearance` (baseline x2, removed 09-10, reappeared 09-20,
  removed 10-01), `rename-and-field-changes` (`['title']`, `['department','url']`, `['posted_at']`,
  `['location','title','work_mode']`), `csv-null-id-rows-collapse` (collapsed rows -> 2 + 2 baselines, then
  `changed ['department','location']`).
  Oracle: agreed.

## HC-17 `change-title-scope-filter` - `acme`

include `engineer`, exclude `intern`; greenhouse full snapshots 08-01, 09-20, 10-01. Ids: s1 [1 Engineer, 2
Designer, 3 Engineer Intern, 4 Engineer Two]; s2 [1 Designer (renamed), 2, 3, 4, 5 Backend Engineer, 6 Marketing
Lead, 7 Engineer Intern, 8 Staff Engineer]; s3 [5, 6, 7, 8 Staff Designer].

- Events inside `(09-13T12:00, as_of]`: s2: `changed` 1 (never counted); `added` 5 "Backend Engineer" **+1**
  (match, no exclude); `added` 6 "Marketing Lead" (no match); `added` 7 "Engineer Intern" (matches `engineer`
  but `intern` excludes); `added` 8 "Staff Engineer" **+1** (title _at event time_). s3: `changed` 8 (never
  counted); `removed` 1 under its new title "Designer" (no); `removed` 2 "Designer" (no); `removed` 3
  "Engineer Intern" (excluded); `removed` 4 "Engineer Two" **-1**. added 2, removed 1, net +1 -> **600**.
- span = days(08-01, 10-01) = 61 (>= 14 and >= 45).
- A = {5,6,7,8} = 4. Relevant: 5 yes; 6 no; 7 no (exclude); 8 is now "Staff Designer" -> no. R = 1;
  relevance rhu(1000,4) = floor(2004/8) = **250**; volume (scope 1) = **300**.
- urgency: scope = {5}, no posted_at, span 61 >= 45 -> first_seen 09-20T00:00 -> as_of = 23 d 12 h -> 23: not
  aged; known 1, aged 0 -> rhu(0,1) = floor(1/2) = **0** (a computed zero, weight 10 counts).
- confidence: role 5 greenhouse -> **1000**. freshness: last_seen 10-01T00:00 -> 12 d 12 h -> d = 12;
  rhu(48000,53) = floor(96053/106) = **906**.
- W = 100. Sum = 7500+6000+9000+0+15000+9060 = 46560. score = floor((93120+100)/200) = floor(466.1) = **466**.
  Oracle: agreed (events in HAND_EVENTS as well).

## HC-18 `headcounts-match-across-sources` - `support hub`

greenhouse/support: 09-01 [202], 09-10 [202, 201]; lever/support: 09-03 [L-b], 09-12 [L-b, L-a]; csv one row
(09-05, additive); all "Support Engineer", Berlin.

- One group (support hub, support engineer, berlin). Keys sorted per source: greenhouse `201` < `202`; lever
  `L-a` < `L-b`; csv has one. Canonical role 0 = i-th smallest of every source = {gh:201, lever:L-a, csv};
  canonical role 1 = {gh:202, lever:L-b} - although 202 and L-b were seen _first_.
- A = 2: volume table[2] = **480**. T = {09-01, 09-10, 09-03, 09-12}: span = days(09-01, 09-12) = 11 < 14 ->
  change null, `span_days` 11. urgency null (no dated roles).
- confidence: role 0 best 1000 (3 sources) -> min(1000,1100) = 1000; role 1 (2 sources) -> 1000; rhu(2000,2) =
  **1000**, corroborated 2. freshness: last_seen 09-12T00:00 -> 31 d 12 h -> d = 31; rhu(29000, 53) =
  floor(58053/106) = **547**.
- W = 45. Sum = 9600+15000+5470 = 30070. score = floor((60140+45)/90) = floor(668.7) = **668**.
  Oracle: agreed (the pairing is asserted through `HAND_OBSERVATIONS`).

## HC-19 `additive-imports-are-not-history` - `lumen`

greenhouse full 08-01 [Optics Engineer]; csv additive 10-05 [Optics Engineer, Sales Lead]; no keywords.

- A = 2 (Optics = gh + csv; Sales = csv). T = _full_ snapshots only = {08-01}: |T| = 1 -> change null with
  `span_days` null; the 65 days up to the import do not count. urgency: no posted_at, span null -> null
  `no_dated_roles`.
- volume table[2] = **480**. confidence: Optics best 1000, two sources -> 1000; Sales csv 600; rhu(1600,2) =
  floor(3202/4) = **800**, corroborated 1. freshness: last_seen 10-05T00:00 -> 8 d 12 h -> 8 -> **981**.
- W = 45. Sum = 9600+12000+9810 = 31410. score = floor((62820+45)/90) = floor(698.5) = **698**.
  Oracle: agreed.

## HC-20 `canonical-last-seen-ignores-removed-members` - `prism labs`

greenhouse/prism full: 09-01 [1 Optics Engineer, 9 Legacy Analyst], 09-10 [1, 9], 10-05 []; csv/prism-sheet
additive 09-05 [Optics Engineer]; lever/prism full: 09-20 [L9 Legacy Analyst], 10-08 [].

- Source roles: gh:1 last 09-10, removed 10-05; csv:Optics active, last 09-05; gh:9 last 09-10, removed 10-05;
  lever:L9 last 09-20, removed 10-08.
- Canonical Optics {gh:1, csv}: active (csv). last_seen = max over **active** members = **09-05** (not 09-10);
  first_seen 09-01; removed_at null.
- Canonical Legacy {gh:9, lever:L9}: no active member -> removed; last_seen = max over all members = **09-20**;
  removed_at = max(10-05, 10-08) = **10-08**; first_seen 09-01.
- Company: A = 1, removed_roles 1. volume (scope 1) = 300. T = {09-01, 09-10, 10-05, 09-20, 10-08}: span =
  days(09-01, 10-08) = 37 (>= 14, < 45). Window events: removals gh:1 (10-05), gh:9 (10-05), lever:L9 (10-08)
  -> removed 3, added 0 (baselines never count) -> clamp(500-300) = **200**. urgency null (no dated roles).
- confidence: only active observation is csv (600) -> **600**, corroborated 0. freshness: company last_seen
  09-05T00:00 -> 38 d 12 h -> d = 38; rhu(22000,53) = floor(44053/106) = **415**.
- W = 20+15+15+10 = **60**. Sum = 6000+3000+9000+4150 = 22150. score = floor((44300+60)/120) =
  floor(369.7) = **369**. Oracle: agreed (role timestamps asserted through `HAND_ROLE_TIMES`).

## HC-21 `span-counts-instants-not-snapshots` - `tidewater freight`, `pier nine`

Added after the differential review (D-2), derived by hand before the oracle saw the vector. No keywords.

Tidewater: greenhouse/tidewater full 10-01T00:00 [501], lever/tidewater full 10-01T00:00 [L-501]; both
"Dock Planner", Rotterdam.

- One canonical role with two active observations (two distinct sources): A = 1. T = _set_ of full-snapshot
  instants = {10-01T00:00}: |T| = 1 -> change null `insufficient_history`, `span_days` **null** (a multiset
  would count two entries and report 0).
- relevance null `no_keywords`. volume table[1] = **300**. urgency: no posted_at, span null -> null
  `no_dated_roles`. confidence: best 1000, two sources -> min(1000,1100) = **1000**, corroborated 1.
  freshness: last_seen 10-01T00:00 -> 12 d 12 h -> d = 12; rhu(48000,53) = floor(96053/106) = **906**.
- W = 20+15+10 = **45**. Sum = 6000+15000+9060 = 30060. score = floor((60120+45)/90) = floor(668.5) =
  **668**. rank 1.

Pier Nine: greenhouse/pier-nine full 09-01T00:00 [601], lever/pier-nine full 10-01T00:00 [L-601]; both "Berth
Planner", Bergen.

- A = 1 (gh + lever). T = {09-01T00:00, 10-01T00:00}: span = days(09-01, 10-01) = 30 >= 14 -> change is
  computed. Window (09-13T12:00 < at <= 10-13T12:00): the lever `baseline` (10-01) is in the window but
  baselines never count; gh's baseline is 09-01 (outside). added 0, removed 0, net 0 -> **500**.
- urgency: span 30 < 45 -> no first_seen rule, no posted_at -> null `no_dated_roles`. volume **300**.
  confidence **1000** (corroborated 1). freshness: active members' max last_seen = lever 10-01 -> d = 12
  -> **906**.
- W = 20+15+15+10 = **60**. Sum = 6000+7500+15000+9060 = 37560. score = floor((75120+60)/120) =
  floor(626.5) = **626**. rank 2. Oracle: agreed on the first run.

## HC-22 `merge-through-absent-key-names-the-group` - `ardent hollow`, `dune row`

Added after the differential review (D-3). csv/hollow-a additive 10-05T00:00 [Birch Hollow Kiln Operator Delft,
Dune Row Glaze Chemist Utrecht]; csv/hollow-b additive 10-06T00:00 [Cedar Hollow Kiln Operator Delft, Elm Row
Glaze Chemist Utrecht]. Decisions: merge(ardent hollow, birch hollow), merge(ardent hollow, cedar hollow),
merge(dune row, zenith row), merge(elm row, zenith row). Present keys: birch hollow, cedar hollow, dune row,
elm row. `ardent hollow` and `zenith row` have no posting.

- Union-find over every key a decision names: {ardent hollow, birch hollow, cedar hollow} -> smallest member
  **ardent hollow** (absent, but a member); {dune row, elm row, zenith row} -> smallest member **dune row**.
  Two companies, no merge candidate between them (no shared token, far apart).
- Names: ardent hollow's earliest posting is Birch Hollow (10-05) -> name `Birch Hollow`, aliases `Birch
Hollow`, `Cedar Hollow`; dune row -> `Dune Row`, aliases `Dune Row`, `Elm Row`.
- Each company: Kiln Operator (resp. Glaze Chemist) appears in both csv sources with the same company (after
  merge), title and location, one row per source -> ONE canonical role with two observations. A = 1.
- volume **300**. T = {} (both additive): change null, span null. urgency null `no_dated_roles`. confidence:
  csv 600, two distinct sources -> 700 -> **700**, corroborated 1. freshness: last_seen max = 10-06T00:00 ->
  7 d 12 h -> d = 7 <= 7 -> **1000**.
- W = 45. Sum = 6000+10500+10000 = 26500. score = floor((53000+45)/90) = floor(589.4) = **589** for both;
  tie -> key order: `ardent hollow` rank 1, `dune row` rank 2.
  Oracle: agreed (the two role pairings are asserted through `HAND_OBSERVATIONS`).

## HC-23 `not-same-names-the-canonical-pair` - four companies

Added after the differential review (D-4). csv/list-a additive 10-12T00:00 [Alpha Group, Alpha Groupz, Delta
Works, Delta Workz - all "Engineer", Lisbon]; csv/list-b additive 10-12T00:00 [Alpha Groupy Engineer Lisbon].
Decisions: merge(alpha group, alpha groupy); not_same(alpha groupy, alpha groupz); not_same(delta works, delta
workz).

- Groups: {alpha group, alpha groupy} -> canonical `alpha group`; the others stand alone. Distinct canonical
  keys: alpha group, alpha groupz, delta works, delta workz.
- Candidates: (alpha group, alpha groupz): lengths 11 and 12, Levenshtein 1 -> `near_typo`; tokens
  {alpha,group} vs {alpha,groupz}: 1/3 < 75% so not token_overlap. The decision names (alpha groupy,
  alpha groupz), not this pair -> **emitted**. (delta works, delta workz): `near_typo`, but the decision names
  exactly this pair -> hidden. Other pairs are far apart. `candidate_id` = sha256("alpha group|alpha
  groupz")[:12] = `3895f6ac16ad` (bare hashlib). a_name: both raw names at 10-12T00:00 -> smaller by code
  point `Alpha Group` (prefix of `Alpha Groupy`); b_name `Alpha Groupz`.
- alpha group: Engineer/Lisbon from list-a and list-b (one row per source) -> one canonical role, 2
  observations; volume **300**, confidence 600 -> 700 -> **700**, freshness d = 1 -> **1000**; W = 45, sum =
  6000+10500+10000 = 26500 -> **589**.
- The three others: one csv role each: volume 300, confidence **600**, freshness **1000**: sum = 6000+9000+
  10000 = 25000; score = floor((50000+45)/90) = floor(556.06) = **556**. Ties on 556 -> key order: `alpha
groupz` (2), `delta works` (3), `delta workz` (4; `s` < `z`). Oracle: agreed.
