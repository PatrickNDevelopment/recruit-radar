import { describe, expect, it, vi } from 'vitest';
import {
  analyze,
  COMPONENT_KEYS,
  EngineInputError,
  type Analysis,
  type AnalyzeInput,
} from '../src/engine';
import { AS_OF, makeInput, post, snap } from './helpers';

const T1 = '2026-09-01T08:00:00Z';
const T2 = '2026-09-15T08:00:00Z';

function sample(): AnalyzeInput {
  return makeInput(
    [
      snap('s1', 'greenhouse', 'acme', T1, 'full', [
        post('Acme Inc.', 'Senior Engineer (Remote)', {
          source_posting_id: '123',
          location: 'New York, NY',
          department: 'Platform',
          url: 'https://boards.example/acme/123',
          work_mode: 'remote',
          posted_at: '2026-08-20',
        }),
        post('Acme Inc.', 'Recruiter', { source_posting_id: '124' }),
      ]),
      snap('s2', 'csv', 'conf-list', T2, 'additive', [
        post('ACME', 'Senior Engineer', { location: 'NY - New York' }),
        post('Globex', 'Analyst'),
      ]),
    ],
    {
      profile: { include_keywords: ['engineer'], exclude_keywords: [] },
      decisions: [{ a_key: 'acme', b_key: 'acme robotics', decision: 'merge' }],
    },
  );
}

describe('Analysis shape (spec 02 §5)', () => {
  const analysis = analyze(sample());

  it('has exactly the documented top-level keys', () => {
    expect(Object.keys(analysis).sort()).toEqual(
      ['as_of', 'companies', 'events', 'merge_candidates', 'roles', 'stats'].sort(),
    );
    expect(analysis.as_of).toBe(AS_OF);
  });

  it('has exactly the documented keys on every object', () => {
    expect(Object.keys(analysis.companies[0] ?? {}).sort()).toEqual(
      [
        'active_roles',
        'aliases',
        'company_id',
        'components',
        'coverage',
        'first_seen',
        'key',
        'last_seen',
        'name',
        'rank',
        'relevant_roles',
        'removed_roles',
        'score',
      ].sort(),
    );
    expect(Object.keys(analysis.roles[0] ?? {}).sort()).toEqual(
      [
        'age_days',
        'company_id',
        'department',
        'first_seen',
        'last_seen',
        'location',
        'observations',
        'posted_at',
        'relevant',
        'removed_at',
        'role_id',
        'status',
        'title',
        'work_mode',
      ].sort(),
    );
    expect(Object.keys(analysis.roles[0]?.observations[0] ?? {}).sort()).toEqual(
      [
        'first_seen',
        'last_seen',
        'source_kind',
        'source_posting_id',
        'source_ref',
        'status',
        'url',
      ].sort(),
    );
    expect(Object.keys(analysis.events[0] ?? {}).sort()).toEqual(
      [
        'at',
        'company_id',
        'fields',
        'role_id',
        'source_kind',
        'source_ref',
        'title',
        'type',
      ].sort(),
    );
    expect(Object.keys(analysis.stats).sort()).toEqual(
      ['active_roles', 'companies', 'postings_observed', 'snapshots'].sort(),
    );
  });

  it('lists all six components, in fixed order, with the spec weights and input keys', () => {
    for (const c of analysis.companies) {
      expect(c.components.map((x) => x.key)).toEqual([...COMPONENT_KEYS]);
      expect(c.components.map((x) => x.weight)).toEqual([30, 20, 15, 10, 15, 10]);
      expect(c.components.map((x) => Object.keys(x.inputs).sort())).toEqual([
        ['active', 'relevant'],
        ['scope_roles'],
        ['added', 'net', 'removed', 'span_days', 'window_days'],
        ['aged', 'known', 'threshold_days'],
        ['corroborated', 'scope_roles'],
        ['days_since_last_seen'],
      ]);
      for (const component of c.components) {
        expect(Object.keys(component).sort()).toEqual(
          ['inputs', 'key', 'reason_code', 'value', 'weight'].sort(),
        );
      }
    }
  });

  it('reports stats consistently', () => {
    expect(analysis.stats).toEqual({
      snapshots: 2,
      postings_observed: 4,
      companies: analysis.companies.length,
      active_roles: analysis.companies.reduce((sum, c) => sum + c.active_roles, 0),
    });
  });

  it('is plain JSON (no undefined, no class instances)', () => {
    expect(JSON.parse(JSON.stringify(analysis))).toEqual(analysis);
  });

  it('computes age_days from posted_at, else from first_seen, never null, clamped at 0', () => {
    const dated = analysis.roles.find((r) => r.posted_at === '2026-08-20');
    // 2026-08-20T00:00Z -> 2026-10-13T12:00Z = 54 days 12h
    expect(dated?.age_days).toBe(54);
    const undated = analysis.roles.find((r) => r.title === 'Recruiter');
    // first_seen 2026-09-01T08:00Z -> as_of = 42 days 4h
    expect(undated?.age_days).toBe(42);
    expect(analysis.roles.every((r) => Number.isInteger(r.age_days) && r.age_days >= 0)).toBe(true);
  });

  it('sorts observations by (source_kind, source_ref, source_posting_id)', () => {
    const merged = analysis.roles.find((r) => r.observations.length === 2);
    expect(merged?.observations.map((o) => o.source_kind)).toEqual(['csv', 'greenhouse']);
  });
});

describe('empty and degenerate inputs', () => {
  it('analyzes no snapshots', () => {
    expect(analyze({ as_of: AS_OF, snapshots: [] })).toEqual({
      as_of: AS_OF,
      companies: [],
      roles: [],
      events: [],
      merge_candidates: [],
      stats: { snapshots: 0, postings_observed: 0, companies: 0, active_roles: 0 },
    });
  });

  it('defaults profile and decisions', () => {
    const a = analyze({
      as_of: AS_OF,
      snapshots: [snap('s', 'csv', 'x', T1, 'additive', [post('A', 'T')])],
    });
    expect(a.companies[0]?.relevant_roles).toBeNull();
  });

  it('accepts a snapshot with no postings', () => {
    const a = analyze(makeInput([snap('s', 'greenhouse', 'x', T1, 'full', [])]));
    expect(a.stats.snapshots).toBe(1);
    expect(a.companies).toEqual([]);
  });

  it('handles a company name with no letters or digits (empty key)', () => {
    const a = analyze(
      makeInput([
        snap('s', 'csv', 'x', T1, 'additive', [post('!!!', 'Engineer'), post('???', 'Engineer')]),
      ]),
    );
    // Both normalize to the empty key, so they are one company by exact_name equality.
    expect(a.companies).toHaveLength(1);
    expect(a.companies[0]?.key).toBe('');
    expect(a.companies[0]?.name).toBe('!!!');
  });
});

describe('purity', () => {
  it('does not mutate its input', () => {
    const input = sample();
    const deepFreeze = (value: unknown): void => {
      if (typeof value === 'object' && value !== null && !Object.isFrozen(value)) {
        Object.freeze(value);
        for (const child of Object.values(value)) deepFreeze(child);
      }
    };
    deepFreeze(input);
    expect(() => analyze(input)).not.toThrow();
  });

  it('is deterministic and independent of decision order', () => {
    const input = sample();
    input.decisions = [
      { a_key: 'a', b_key: 'b', decision: 'merge' },
      { a_key: 'b', b_key: 'c', decision: 'not_same' },
      { a_key: 'c', b_key: 'd', decision: 'merge' },
    ];
    const first = analyze(input);
    expect(analyze(input)).toEqual(first);
    const reversed = { ...input, decisions: [...(input.decisions ?? [])].reverse() };
    expect(analyze(reversed)).toEqual(first);
  });

  it('never reads the clock or randomness', () => {
    const input = sample();
    const expected = analyze(input);
    const RealDate = Date;
    const trap = (): never => {
      throw new Error('analyze() touched the clock or randomness');
    };
    class TrapDate extends RealDate {
      constructor(...args: unknown[]) {
        super();
        void args;
        trap();
      }
      static override now(): number {
        return trap();
      }
    }
    vi.stubGlobal('Date', TrapDate);
    const random = vi.spyOn(Math, 'random').mockImplementation(trap);
    try {
      expect(analyze(input)).toEqual(expected);
    } finally {
      random.mockRestore();
      vi.unstubAllGlobals();
    }
  });
});

describe('input validation (EngineInputError)', () => {
  const base = (): AnalyzeInput =>
    makeInput([snap('s', 'greenhouse', 'x', T1, 'full', [post('A', 'T')])]);

  const issuesOf = (input: unknown): Array<{ path: string; message: string }> => {
    try {
      analyze(input);
    } catch (error) {
      expect(error).toBeInstanceOf(EngineInputError);
      expect(error).toBeInstanceOf(Error);
      return [...(error as EngineInputError).issues];
    }
    throw new Error('expected analyze() to throw');
  };

  const withPosting = (extra: Record<string, unknown>): unknown => ({
    as_of: AS_OF,
    snapshots: [
      {
        snapshot_id: 's',
        source_kind: 'greenhouse',
        source_ref: 'x',
        observed_at: T1,
        mode: 'full',
        postings: [{ company_name: 'A', title: 'T', ...extra }],
      },
    ],
  });

  it('throws a typed, named error with a readable message', () => {
    try {
      analyze({});
    } catch (error) {
      expect(error).toBeInstanceOf(EngineInputError);
      expect((error as EngineInputError).name).toBe('EngineInputError');
      expect((error as Error).message).toMatch(/^Invalid analyze\(\) input: /);
      return;
    }
    throw new Error('expected a throw');
  });

  it.each([null, undefined, 'x', 3, []])('rejects a non-object input (%j)', (input) => {
    expect(() => analyze(input)).toThrow(EngineInputError);
  });

  it('requires as_of in YYYY-MM-DDTHH:MM:SSZ form and a real instant', () => {
    for (const as_of of [
      undefined,
      '2026-10-13',
      '2026-10-13T12:00:00',
      '2026-10-13T12:00:00.000Z',
      '2026-02-30T00:00:00Z',
      1,
    ]) {
      const issues = issuesOf({ ...base(), as_of });
      expect(issues[0]?.path).toBe('as_of');
    }
  });

  it('rejects duplicate snapshot ids', () => {
    const input = makeInput([
      snap('dup', 'greenhouse', 'x', T1, 'full', []),
      snap('dup', 'lever', 'y', T2, 'full', []),
    ]);
    const issues = issuesOf(input);
    expect(issues).toHaveLength(1);
    expect(issues[0]?.path).toBe('snapshots[1].snapshot_id');
  });

  it('rejects unknown source kinds, modes and bad observed_at', () => {
    const bad = {
      as_of: AS_OF,
      snapshots: [
        {
          snapshot_id: 'a',
          source_kind: 'linkedin',
          source_ref: 'x',
          observed_at: T1,
          mode: 'full',
          postings: [],
        },
        {
          snapshot_id: 'b',
          source_kind: 'csv',
          source_ref: 'x',
          observed_at: T1,
          mode: 'partial',
          postings: [],
        },
        {
          snapshot_id: 'c',
          source_kind: 'csv',
          source_ref: ' ',
          observed_at: 'yesterday',
          mode: 'full',
          postings: [],
        },
      ],
    };
    const paths = issuesOf(bad)
      .map((i) => i.path)
      .sort();
    expect(paths).toEqual([
      'snapshots[0].source_kind',
      'snapshots[1].mode',
      'snapshots[2].observed_at',
      'snapshots[2].source_ref',
    ]);
  });

  it('enforces posting field rules with the offending path', () => {
    const cases: Array<[Record<string, unknown>, string]> = [
      [{ company_name: '   ' }, 'company_name'],
      [{ company_name: 'x'.repeat(201) }, 'company_name'],
      [{ title: '' }, 'title'],
      [{ title: 'y'.repeat(301) }, 'title'],
      [{ location: 'z'.repeat(301) }, 'location'],
      [{ department: 'd'.repeat(201) }, 'department'],
      [{ work_mode: 'office' }, 'work_mode'],
      [{ work_mode: 'Remote' }, 'work_mode'],
      [{ url: 'javascript:alert(1)' }, 'url'],
      [{ url: 'ftp://example.com/x' }, 'url'],
      [{ url: '//example.com/x' }, 'url'],
      [{ url: 'example.com/jobs' }, 'url'],
      [{ url: 'java\tscript:alert(1)' }, 'url'],
      [{ url: 'https://' }, 'url'],
      [{ url: 'https://example.com/a\nb' }, 'url'],
      [{ posted_at: '2026-02-30' }, 'posted_at'],
      [{ posted_at: '2026-13-01' }, 'posted_at'],
      [{ posted_at: '10/13/2026' }, 'posted_at'],
      [{ posted_at: '2026-10-13T00:00:00Z' }, 'posted_at'],
      [{ source_posting_id: 7 }, 'source_posting_id'],
      [{ title: 5 }, 'title'],
    ];
    for (const [extra, field] of cases) {
      const issues = issuesOf(withPosting(extra));
      expect(
        issues.map((i) => i.path),
        JSON.stringify(extra),
      ).toEqual([`snapshots[0].postings[0].${field}`]);
    }
  });

  it('requires the required fields to be present', () => {
    const input = withPosting({});
    const posting = (input as { snapshots: Array<{ postings: Array<Record<string, unknown>> }> })
      .snapshots[0]?.postings[0];
    if (posting !== undefined) {
      delete posting.company_name;
      delete posting.title;
    }
    expect(
      issuesOf(input)
        .map((i) => i.path)
        .sort(),
    ).toEqual(['snapshots[0].postings[0].company_name', 'snapshots[0].postings[0].title']);
  });

  it('reports every problem, not just the first', () => {
    const issues = issuesOf(
      withPosting({ url: 'ftp://x', posted_at: '2026-02-30', work_mode: 'nope' }),
    );
    expect(issues).toHaveLength(3);
  });

  it('counts length in code points, not UTF-16 units', () => {
    expect(() => analyze(withPosting({ company_name: '😀'.repeat(200) }))).not.toThrow();
    expect(() => analyze(withPosting({ company_name: '😀'.repeat(201) }))).toThrow(
      EngineInputError,
    );
    expect(() => analyze(withPosting({ title: '日'.repeat(300) }))).not.toThrow();
  });

  it('rejects a posting that contradicts its snapshot source, and allows one that repeats it', () => {
    const issues = issuesOf(withPosting({ source_kind: 'lever' }));
    expect(issues[0]?.path).toBe('snapshots[0].postings[0].source_kind');
    expect(issuesOf(withPosting({ source_ref: 'other' }))[0]?.path).toBe(
      'snapshots[0].postings[0].source_ref',
    );
    expect(() =>
      analyze(withPosting({ source_kind: 'greenhouse', source_ref: ' x ' })),
    ).not.toThrow();
  });

  it('validates the profile and decisions', () => {
    const tooMany = {
      ...base(),
      profile: {
        include_keywords: Array.from({ length: 51 }, (_, i) => `k${i}`),
        exclude_keywords: [],
      },
    };
    expect(issuesOf(tooMany)[0]?.path).toBe('profile.include_keywords');
    const tooLong = {
      ...base(),
      profile: { include_keywords: ['k'.repeat(61)], exclude_keywords: [] },
    };
    expect(issuesOf(tooLong)[0]?.path).toBe('profile.include_keywords[0]');
    const notString = { ...base(), profile: { include_keywords: [1], exclude_keywords: [] } };
    expect(issuesOf(notString)[0]?.path).toBe('profile.include_keywords[0]');
    const badDecision = { ...base(), decisions: [{ a_key: 'a', b_key: 'b', decision: 'maybe' }] };
    expect(issuesOf(badDecision)[0]?.path).toBe('decisions[0].decision');
    const unordered = { ...base(), decisions: [{ a_key: 'b', b_key: 'a', decision: 'merge' }] };
    expect(issuesOf(unordered)[0]?.path).toBe('decisions[0].a_key');
  });

  it('trims strings, nulls empty optionals and defaults work_mode', () => {
    const a = analyze(
      withPosting({
        company_name: '  Acme  ',
        title: '\tEngineer  II ',
        location: '   ',
        department: '',
        url: ' https://example.com/j ',
        posted_at: ' 2026-08-01 ',
        work_mode: null,
        source_posting_id: ' 42 ',
      }),
    );
    expect(a.companies[0]?.name).toBe('Acme');
    expect(a.roles[0]).toMatchObject({
      title: 'Engineer  II', // internal whitespace is preserved
      location: null,
      department: null,
      posted_at: '2026-08-01',
      work_mode: 'unknown',
    });
    expect(a.roles[0]?.observations[0]).toMatchObject({
      url: 'https://example.com/j',
      source_posting_id: '42',
    });
  });

  it('is exposed as a pure value type for Analysis consumers', () => {
    const a: Analysis = analyze(sample());
    expect(a.companies.length).toBeGreaterThan(0);
  });
});
