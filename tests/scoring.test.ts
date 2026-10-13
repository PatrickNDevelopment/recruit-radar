import { describe, expect, it } from 'vitest';
import { analyze, type Analysis, type PostingInput, type Profile } from '../src/engine';
import { DAY, component, company, makeInput, post, shift, snap } from './helpers';

const T0 = '2026-08-01T00:00:00Z';

/** One greenhouse board observed in `full` mode at each `[time, postings]` step. */
function board(
  steps: Array<[string, PostingInput[]]>,
  options: { as_of?: string; profile?: Profile; name?: string } = {},
): Analysis {
  return analyze(
    makeInput(
      steps.map(([at, postings], i) => snap(`s${i}`, 'greenhouse', 'acme', at, 'full', postings)),
      { as_of: options.as_of ?? '2026-10-13T12:00:00Z', profile: options.profile },
    ),
  );
}

const roles = (count: number, prefix = 'Role'): PostingInput[] =>
  Array.from({ length: count }, (_, i) =>
    post('Acme', `${prefix} ${i + 1}`, { source_posting_id: String(i + 1) }),
  );

describe('hand-derived golden: keywords, history, dated roles', () => {
  const profile: Profile = { include_keywords: ['engineer'], exclude_keywords: ['intern'] };
  const base: PostingInput[] = [
    post('Acme', 'Software Engineer', { source_posting_id: '1', posted_at: '2026-06-01' }),
    post('Acme', 'Engineering Manager', { source_posting_id: '2' }),
    post('Acme', 'Engineer Intern', { source_posting_id: '3' }),
  ];
  const analysis = board(
    [
      [T0, base],
      [
        '2026-09-30T00:00:00Z',
        [...base, post('Acme', 'Staff Engineer', { source_posting_id: '4' })],
      ],
    ],
    { profile },
  );
  const acme = company(analysis, 'Acme');

  it('counts active, relevant and removed roles', () => {
    expect(acme).toMatchObject({
      active_roles: 4,
      relevant_roles: 2,
      removed_roles: 0,
      first_seen: T0,
      last_seen: '2026-09-30T00:00:00Z',
    });
  });

  it('computes every component from the spec formulas', () => {
    expect(acme.components.map((c) => [c.key, c.weight, c.value, c.reason_code])).toEqual([
      ['role_relevance', 30, 500, null], // rhu(1000*2, 4)
      ['volume', 20, 480, null], // table[2]
      ['change', 15, 600, null], // net +1 inside the window, span 60 days
      ['urgency', 10, 500, null], // 1 aged of 2 dated roles
      ['source_confidence', 15, 1000, null],
      ['freshness', 10, 887, null], // d = 13 -> rhu(1000*47, 53)
    ]);
    expect(component(acme, 'role_relevance').inputs).toEqual({ relevant: 2, active: 4 });
    expect(component(acme, 'volume').inputs).toEqual({ scope_roles: 2 });
    expect(component(acme, 'change').inputs).toEqual({
      added: 1,
      removed: 0,
      net: 1,
      span_days: 60,
      window_days: 30,
    });
    expect(component(acme, 'urgency').inputs).toEqual({ aged: 1, known: 2, threshold_days: 45 });
    expect(component(acme, 'source_confidence').inputs).toEqual({
      scope_roles: 2,
      corroborated: 0,
    });
    expect(component(acme, 'freshness').inputs).toEqual({ days_since_last_seen: 13 });
  });

  it('combines them into score 625 with 100% coverage', () => {
    // (30*500 + 20*480 + 15*600 + 10*500 + 15*1000 + 10*887) / 100 = 624.7 -> rhu = 625
    expect(acme.coverage).toBe(100);
    expect(acme.score).toBe(625);
    expect(acme.rank).toBe(1);
  });

  it('flags relevance per role', () => {
    const byTitle = Object.fromEntries(analysis.roles.map((r) => [r.title, r.relevant]));
    expect(byTitle).toEqual({
      'Software Engineer': true,
      'Engineering Manager': false,
      'Engineer Intern': false,
      'Staff Engineer': true,
    });
  });
});

describe('hand-derived golden: corroboration, no keywords, thin history', () => {
  const analysis = analyze(
    makeInput([
      snap('g', 'greenhouse', 'beta', '2026-10-10T00:00:00Z', 'full', [
        post('Beta', 'Data Analyst', { location: 'Remote', source_posting_id: '7' }),
      ]),
      snap('c', 'csv', 'leads', '2026-10-10T00:00:00Z', 'additive', [
        post('Beta', 'Data Analyst', { location: 'Remote' }),
      ]),
    ]),
  );
  const beta = company(analysis, 'Beta');

  it('reports missing components with their reasons instead of zeros', () => {
    expect(beta.components.map((c) => [c.key, c.value, c.reason_code])).toEqual([
      ['role_relevance', null, 'no_keywords'],
      ['volume', 300, null],
      ['change', null, 'insufficient_history'],
      ['urgency', null, 'no_dated_roles'],
      ['source_confidence', 1000, null],
      ['freshness', 1000, null],
    ]);
    expect(component(beta, 'role_relevance').inputs).toEqual({ relevant: null, active: 1 });
    expect(component(beta, 'change').inputs).toEqual({
      added: null,
      removed: null,
      net: null,
      span_days: null,
      window_days: 30,
    });
    expect(component(beta, 'urgency').inputs).toEqual({ aged: 0, known: 0, threshold_days: 45 });
    expect(component(beta, 'source_confidence').inputs).toEqual({
      scope_roles: 1,
      corroborated: 1,
    });
    expect(component(beta, 'freshness').inputs).toEqual({ days_since_last_seen: 3 });
  });

  it('scores over the computable weights only (coverage 45)', () => {
    // (20*300 + 15*1000 + 10*1000) / 45 = 688.9 -> 689
    expect(beta.coverage).toBe(45);
    expect(beta.score).toBe(689);
    expect(beta.relevant_roles).toBeNull();
  });
});

describe('role_relevance', () => {
  const profile: Profile = { include_keywords: ['engineer'], exclude_keywords: [] };
  const mix = (relevant: number, other: number): PostingInput[] => [
    ...Array.from({ length: relevant }, (_, i) =>
      post('Acme', `Engineer ${i}`, { source_posting_id: `e${i}` }),
    ),
    ...Array.from({ length: other }, (_, i) =>
      post('Acme', `Cook ${i}`, { source_posting_id: `c${i}` }),
    ),
  ];

  it.each([
    [2, 1, 667], // rhu(2000, 3)
    [1, 2, 333],
    [1, 1, 500],
    [0, 3, 0],
    [3, 0, 1000],
  ])('%i relevant of %i others -> %i', (relevant, other, value) => {
    const a = board([[T0, mix(relevant, other)]], { profile });
    const c = component(company(a, 'Acme'), 'role_relevance');
    expect(c.value).toBe(value);
    expect(c.inputs).toEqual({ relevant, active: relevant + other });
  });
});

describe('volume table', () => {
  const expected = [300, 480, 600, 690, 760, 820, 870, 910, 950, 1000, 1000, 1000];
  it.each(expected.map((value, i) => [i + 1, value] as const))(
    '%i in-scope roles -> %i',
    (count, value) => {
      const a = board([[T0, roles(count)]]);
      const c = component(company(a, 'Acme'), 'volume');
      expect(c.value).toBe(value);
      expect(c.inputs).toEqual({ scope_roles: count });
    },
  );

  it('scores zero (not missing) when roles exist but none match the keywords', () => {
    const a = board([[T0, roles(2)]], {
      profile: { include_keywords: ['pilot'], exclude_keywords: [] },
    });
    const acme = company(a, 'Acme');
    expect(component(acme, 'volume').value).toBe(0);
    expect(component(acme, 'role_relevance').value).toBe(0);
    expect(component(acme, 'urgency')).toMatchObject({
      value: null,
      reason_code: 'no_scope_roles',
    });
    expect(component(acme, 'source_confidence')).toMatchObject({
      value: null,
      reason_code: 'no_scope_roles',
      inputs: { scope_roles: 0, corroborated: 0 },
    });
    expect(component(acme, 'urgency').inputs).toEqual({ aged: 0, known: 0, threshold_days: 45 });
    expect(acme.relevant_roles).toBe(0);
  });
});

describe('change: window and history boundaries', () => {
  const T1 = '2026-08-21T00:00:00Z'; // 20 days after T0 -> span 20
  const steps = (): Array<[string, PostingInput[]]> => [
    [T0, roles(1)],
    [T1, roles(2)],
  ];

  it('excludes an event exactly 30 days before as_of and includes one a second later', () => {
    const edge = board(steps(), { as_of: shift(T1, 30 * DAY) });
    expect(component(company(edge, 'Acme'), 'change')).toMatchObject({
      value: 500,
      inputs: { added: 0, removed: 0, net: 0, span_days: 20 },
    });
    const inside = board(steps(), { as_of: shift(T1, 30 * DAY - 1) });
    expect(component(company(inside, 'Acme'), 'change')).toMatchObject({
      value: 600,
      inputs: { added: 1, removed: 0, net: 1 },
    });
  });

  it('includes an event at as_of itself', () => {
    const a = board(steps(), { as_of: T1 });
    expect(component(company(a, 'Acme'), 'change')).toMatchObject({
      value: 600,
      inputs: { added: 1, span_days: 20 },
    });
  });

  it('needs a 14-day span: 14 days is enough, 13 days 23:59:59 is not', () => {
    const t = '2026-09-01T00:00:00Z';
    const enough = board(
      [
        [t, roles(1)],
        [shift(t, 14 * DAY), roles(2)],
      ],
      { as_of: shift(t, 15 * DAY) },
    );
    expect(component(company(enough, 'Acme'), 'change')).toMatchObject({
      value: 600,
      reason_code: null,
      inputs: { span_days: 14 },
    });
    const short = board(
      [
        [t, roles(1)],
        [shift(t, 14 * DAY - 1), roles(2)],
      ],
      { as_of: shift(t, 15 * DAY) },
    );
    expect(component(company(short, 'Acme'), 'change')).toMatchObject({
      value: null,
      reason_code: 'insufficient_history',
      inputs: { added: null, removed: null, net: null, span_days: 13, window_days: 30 },
    });
  });

  it('clamps to 0..1000', () => {
    const up = board(
      [
        [T0, roles(1)],
        [T1, roles(7)],
      ],
      { as_of: shift(T1, DAY) },
    );
    expect(component(company(up, 'Acme'), 'change')).toMatchObject({
      value: 1000,
      inputs: { added: 6, net: 6 },
    });
    const down = board(
      [
        [T0, roles(7)],
        [T1, roles(1)],
      ],
      { as_of: shift(T1, DAY) },
    );
    expect(component(company(down, 'Acme'), 'change')).toMatchObject({
      value: 0,
      inputs: { removed: 6, net: -6 },
    });
  });

  it('counts reappeared as added; ignores baseline and changed events', () => {
    const t2 = '2026-09-10T00:00:00Z';
    const a = board(
      [
        [
          T0,
          [
            post('Acme', 'Alpha', { source_posting_id: '1' }),
            post('Acme', 'Beta', { source_posting_id: '2' }),
          ],
        ],
        [T1, [post('Acme', 'Alpha', { source_posting_id: '1' })]],
        [
          t2,
          [
            post('Acme', 'Alpha II', { source_posting_id: '1' }),
            post('Acme', 'Beta', { source_posting_id: '2' }),
          ],
        ],
      ],
      { as_of: shift(t2, DAY) },
    );
    // Window (as_of - 30d, as_of] holds: T1 removed(Beta), t2 changed(Alpha), t2 reappeared(Beta).
    expect(component(company(a, 'Acme'), 'change').inputs).toEqual({
      added: 1,
      removed: 1,
      net: 0,
      span_days: 40,
      window_days: 30,
    });
  });

  it('only counts events whose title is in scope when keywords are configured', () => {
    const profile: Profile = { include_keywords: ['engineer'], exclude_keywords: ['intern'] };
    const a = board(
      [
        [T0, [post('Acme', 'Engineer', { source_posting_id: '0' })]],
        [
          T1,
          [
            post('Acme', 'Engineer', { source_posting_id: '0' }),
            post('Acme', 'Staff Engineer', { source_posting_id: '1' }),
            post('Acme', 'Engineer Intern', { source_posting_id: '2' }),
            post('Acme', 'Cook', { source_posting_id: '3' }),
          ],
        ],
      ],
      { profile, as_of: shift(T1, DAY) },
    );
    expect(component(company(a, 'Acme'), 'change').inputs).toMatchObject({ added: 1, net: 1 });
  });

  it('measures history across every source that supplied roles to the company', () => {
    const a = analyze(
      makeInput(
        [
          snap('g1', 'greenhouse', 'acme', T0, 'full', roles(1)),
          snap('l1', 'lever', 'acme', T1, 'full', [
            post('Acme', 'Role 1', { source_posting_id: 'x' }),
          ]),
        ],
        { as_of: shift(T1, DAY) },
      ),
    );
    // Neither source alone spans 14 days, but together their full snapshots do.
    expect(component(company(a, 'Acme'), 'change').inputs).toMatchObject({ span_days: 20 });
  });

  it('ignores additive snapshots when measuring history', () => {
    const a = analyze(
      makeInput(
        [
          snap('g1', 'greenhouse', 'acme', T0, 'full', roles(1)),
          snap('c1', 'csv', 'leads', T1, 'additive', [post('Acme', 'Role 1')]),
        ],
        { as_of: shift(T1, DAY) },
      ),
    );
    expect(component(company(a, 'Acme'), 'change')).toMatchObject({
      value: null,
      reason_code: 'insufficient_history',
      inputs: { span_days: null },
    });
  });
});

describe('urgency: 44 vs 45 days', () => {
  const dated = (posted_at: string, as_of: string) =>
    board([[T0, [post('Acme', 'Engineer', { source_posting_id: '1', posted_at })]]], { as_of });

  it('counts a role posted exactly 45 days earlier as aged, 44 as not', () => {
    const aged = component(company(dated('2026-08-29', '2026-10-13T00:00:00Z'), 'Acme'), 'urgency');
    expect(aged).toMatchObject({ value: 1000, inputs: { aged: 1, known: 1, threshold_days: 45 } });
    const fresh = component(
      company(dated('2026-08-30', '2026-10-13T00:00:00Z'), 'Acme'),
      'urgency',
    );
    expect(fresh).toMatchObject({ value: 0, inputs: { aged: 0, known: 1 } });
  });

  it('floors partial days (45 days minus one second is 44)', () => {
    const a = dated('2026-08-29', '2026-10-12T23:59:59Z');
    expect(component(company(a, 'Acme'), 'urgency').inputs).toEqual({
      aged: 0,
      known: 1,
      threshold_days: 45,
    });
  });

  it('clamps a posting date in the future to age 0', () => {
    const a = dated('2026-12-01', '2026-10-13T12:00:00Z');
    expect(component(company(a, 'Acme'), 'urgency')).toMatchObject({
      value: 0,
      inputs: { aged: 0, known: 1 },
    });
  });

  it('falls back to first_seen only with a 45-day history span, and not before', () => {
    const undated = (p: PostingInput[]) => p;
    const longHistory = board(
      [
        [T0, undated(roles(1))],
        [shift(T0, 45 * DAY), undated(roles(1))],
      ],
      { as_of: shift(T0, 46 * DAY) },
    );
    // first_seen is T0, 46 days before as_of, and the span (45) is long enough.
    expect(component(company(longHistory, 'Acme'), 'urgency')).toMatchObject({
      value: 1000,
      inputs: { aged: 1, known: 1 },
    });
    const shortHistory = board(
      [
        [T0, undated(roles(1))],
        [shift(T0, 44 * DAY), undated(roles(1))],
      ],
      { as_of: shift(T0, 100 * DAY) },
    );
    expect(component(company(shortHistory, 'Acme'), 'urgency')).toMatchObject({
      value: null,
      reason_code: 'no_dated_roles',
      inputs: { aged: 0, known: 0 },
    });
  });
});

describe('freshness: 7 / 8 / 59 / 60 days', () => {
  const at = (seconds: number) => board([[T0, roles(1)]], { as_of: shift(T0, seconds) });
  const fresh = (seconds: number) => component(company(at(seconds), 'Acme'), 'freshness');

  it.each([
    [0, 1000, 0],
    [7 * DAY, 1000, 7],
    [8 * DAY - 1, 1000, 7],
    [8 * DAY, 981, 8], // rhu(1000*52, 53)
    [30 * DAY, 566, 30], // rhu(1000*30, 53) = 566
    [59 * DAY, 19, 59], // rhu(1000*1, 53)
    [60 * DAY - 1, 19, 59],
    [60 * DAY, 0, 60],
    [400 * DAY, 0, 400],
  ])('as_of = last_seen + %i s -> value %i (d = %i)', (seconds, value, days) => {
    expect(fresh(seconds)).toMatchObject({ value, inputs: { days_since_last_seen: days } });
  });
});

describe('source_confidence', () => {
  const sources = (
    specs: Array<['greenhouse' | 'lever' | 'ashby' | 'csv' | 'manual', 'full' | 'additive']>,
  ) =>
    analyze(
      makeInput(
        specs.map(([kind, mode], i) =>
          snap(`s${i}`, kind, kind === 'manual' ? 'manual' : `ref${i}`, T0, mode, [
            post('Acme', 'Engineer', { location: 'Remote' }),
          ]),
        ),
      ),
    );
  const confidence = (a: Analysis) => component(company(a, 'Acme'), 'source_confidence');

  it('uses 1000 for ATS sources, 600 for csv and 400 for manual', () => {
    expect(confidence(sources([['greenhouse', 'full']])).value).toBe(1000);
    expect(confidence(sources([['lever', 'full']])).value).toBe(1000);
    expect(confidence(sources([['ashby', 'full']])).value).toBe(1000);
    expect(confidence(sources([['csv', 'additive']])).value).toBe(600);
    expect(confidence(sources([['manual', 'additive']])).value).toBe(400);
  });

  it('adds 100 (capped at 1000) when two distinct sources corroborate a role', () => {
    const csvAndManual = confidence(
      sources([
        ['csv', 'additive'],
        ['manual', 'additive'],
      ]),
    );
    expect(csvAndManual).toMatchObject({ value: 700, inputs: { scope_roles: 1, corroborated: 1 } });
    const ats = confidence(
      sources([
        ['greenhouse', 'full'],
        ['csv', 'additive'],
      ]),
    );
    expect(ats).toMatchObject({ value: 1000, inputs: { corroborated: 1 } });
  });

  it('counts two datasets of the same kind as two sources', () => {
    const a = analyze(
      makeInput([
        snap('a', 'csv', 'list-a', T0, 'additive', [post('Acme', 'Engineer')]),
        snap('b', 'csv', 'list-b', T0, 'additive', [post('Acme', 'Engineer')]),
      ]),
    );
    expect(confidence(a)).toMatchObject({ value: 700, inputs: { corroborated: 1 } });
  });

  it('ignores observations that are no longer active', () => {
    const a = analyze(
      makeInput([
        snap('g', 'greenhouse', 'acme', T0, 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
        ]),
        snap('c', 'csv', 'leads', T0, 'additive', [post('Acme', 'Engineer')]),
        snap('g2', 'greenhouse', 'acme', '2026-08-02T00:00:00Z', 'full', []),
      ]),
    );
    expect(confidence(a)).toMatchObject({
      value: 600,
      inputs: { scope_roles: 1, corroborated: 0 },
    });
  });

  it('averages over the scope roles with half-up rounding', () => {
    const a = analyze(
      makeInput([
        snap('g', 'greenhouse', 'acme', T0, 'full', [
          post('Acme', 'Engineer A', { source_posting_id: '1' }),
        ]),
        snap('c', 'csv', 'leads', T0, 'additive', [
          post('Acme', 'Engineer B'),
          post('Acme', 'Engineer C'),
        ]),
      ]),
    );
    // (1000 + 600 + 600) / 3 = 733.33 -> 733
    expect(confidence(a).value).toBe(733);
  });
});

describe('companies without active roles', () => {
  const a = analyze(
    makeInput(
      [
        snap('s1', 'greenhouse', 'acme', T0, 'full', roles(1)),
        snap('s2', 'greenhouse', 'acme', '2026-08-21T00:00:00Z', 'full', []),
      ],
      { profile: { include_keywords: ['role'], exclude_keywords: [] } },
    ),
  );
  const acme = company(a, 'Acme');

  it('has every component null with no_active_roles and the documented inputs', () => {
    expect(acme.components.map((c) => [c.key, c.value, c.reason_code])).toEqual([
      ['role_relevance', null, 'no_active_roles'],
      ['volume', null, 'no_active_roles'],
      ['change', null, 'no_active_roles'],
      ['urgency', null, 'no_active_roles'],
      ['source_confidence', null, 'no_active_roles'],
      ['freshness', null, 'no_active_roles'],
    ]);
    expect(acme.components.map((c) => c.inputs)).toEqual([
      { relevant: null, active: 0 },
      { scope_roles: 0 },
      { added: null, removed: null, net: null, span_days: 20, window_days: 30 },
      { aged: null, known: null, threshold_days: 45 },
      { scope_roles: 0, corroborated: null },
      { days_since_last_seen: null },
    ]);
  });

  it('has no score, no rank, zero coverage and no last_seen', () => {
    expect(acme).toMatchObject({
      score: null,
      coverage: 0,
      rank: null,
      last_seen: null,
      active_roles: 0,
      relevant_roles: 0,
      removed_roles: 1,
    });
  });
});

describe('ranking', () => {
  it('orders by score desc, then key asc, then company_id; unscored last by key', () => {
    const a = analyze(
      makeInput([
        snap('s1', 'greenhouse', 'x', T0, 'full', [
          post('Zeta Co', 'Role', { source_posting_id: '1' }),
          post('Alpha Co', 'Role', { source_posting_id: '2' }),
          post('Mid Co', 'Role A', { source_posting_id: '3' }),
          post('Mid Co', 'Role B', { source_posting_id: '4' }),
          post('Dead Co', 'Role', { source_posting_id: '5' }),
          post('Abandoned Co', 'Role', { source_posting_id: '6' }),
        ]),
        snap('s2', 'greenhouse', 'x', '2026-08-02T00:00:00Z', 'full', [
          post('Zeta Co', 'Role', { source_posting_id: '1' }),
          post('Alpha Co', 'Role', { source_posting_id: '2' }),
          post('Mid Co', 'Role A', { source_posting_id: '3' }),
          post('Mid Co', 'Role B', { source_posting_id: '4' }),
        ]),
      ]),
    );
    expect(a.companies.map((c) => [c.name, c.rank, c.score === null ? null : 'scored'])).toEqual([
      ['Mid Co', 1, 'scored'], // two roles beat one
      ['Alpha Co', 2, 'scored'], // tie with Zeta Co -> key asc
      ['Zeta Co', 3, 'scored'],
      ['Abandoned Co', null, null],
      ['Dead Co', null, null],
    ]);
    const alpha = company(a, 'Alpha Co');
    const zeta = company(a, 'Zeta Co');
    expect(alpha.score).toBe(zeta.score);
  });
});
