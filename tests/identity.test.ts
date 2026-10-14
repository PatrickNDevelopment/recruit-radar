import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { analyze, EngineInputError, type MergeDecision } from '../src/engine';
import { findMergeCandidates, withinOneEdit, type Company } from '../src/engine/identity';
import { compareCodePoints } from '../src/engine/normalize';
import { company, makeInput, mulberry32, post, rolesOf, snap } from './helpers';

const T1 = '2026-09-01T08:00:00Z';
const T2 = '2026-09-15T08:00:00Z';

const sha12 = (text: string): string =>
  createHash('sha256').update(text, 'utf8').digest('hex').slice(0, 12);

describe('company identity (spec 01 §3, §5)', () => {
  it('collapses Acme / ACME Inc. / acme, inc into one company and dedups the role', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { location: 'Remote' }),
          post('ACME Inc.', 'Engineer', { location: 'Remote' }),
          post('acme, inc', 'Engineer', { location: 'Remote' }),
        ]),
      ]),
    );
    expect(analysis.companies).toHaveLength(1);
    const [c] = analysis.companies;
    expect(c?.key).toBe('acme');
    expect(c?.company_id).toBe(`c_${sha12('acme')}`);
    expect(c?.aliases).toEqual(['ACME Inc.', 'Acme', 'acme, inc']);
    expect(c?.name).toBe('ACME Inc.'); // ties on observed_at: smallest raw name
    expect(analysis.stats.postings_observed).toBe(3);
    expect(analysis.roles).toHaveLength(1);
    expect(analysis.merge_candidates).toEqual([]);
  });

  it('uses the earliest observed posting for the display name', () => {
    const analysis = analyze(
      makeInput([
        snap('s2', 'csv', 'later', T2, 'additive', [post('ACME', 'Engineer')]),
        snap('s1', 'csv', 'earlier', T1, 'additive', [post('Acme Inc', 'Engineer')]),
      ]),
    );
    expect(analysis.companies[0]?.name).toBe('Acme Inc');
    expect(analysis.companies[0]?.aliases).toEqual(['ACME', 'Acme Inc']);
  });

  it('keeps DoorDash and Door Dash apart and proposes a spacing_variant merge', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'csv', 'x', T1, 'additive', [
          post('DoorDash', 'Engineer'),
          post('Door Dash', 'Engineer'),
        ]),
      ]),
    );
    expect(analysis.companies).toHaveLength(2);
    expect(analysis.merge_candidates).toEqual([
      {
        candidate_id: sha12('door dash|doordash'),
        a_key: 'door dash',
        b_key: 'doordash',
        a_name: 'Door Dash',
        b_name: 'DoorDash',
        reason: 'spacing_variant',
      },
    ]);
  });

  it('proposes near_typo for Acme Robotics / Acme Robotic', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'csv', 'x', T1, 'additive', [
          post('Acme Robotics', 'Engineer'),
          post('Acme Robotic', 'Engineer'),
        ]),
      ]),
    );
    expect(analysis.merge_candidates).toHaveLength(1);
    expect(analysis.merge_candidates[0]).toMatchObject({
      a_key: 'acme robotic',
      b_key: 'acme robotics',
      reason: 'near_typo',
    });
  });

  it('applies a merge decision to the whole history and uses the smallest key', () => {
    const decisions: MergeDecision[] = [
      { a_key: 'door dash', b_key: 'doordash', decision: 'merge' },
    ];
    const analysis = analyze(
      makeInput(
        [
          snap('s1', 'csv', 'x', T1, 'additive', [post('DoorDash', 'Engineer')]),
          snap('s2', 'csv', 'x', T2, 'additive', [post('Door Dash', 'Analyst')]),
        ],
        { decisions },
      ),
    );
    expect(analysis.companies).toHaveLength(1);
    const [c] = analysis.companies;
    expect(c?.key).toBe('door dash');
    expect(c?.company_id).toBe(`c_${sha12('door dash')}`);
    expect(c?.name).toBe('DoorDash'); // earliest posting
    expect(c?.aliases).toEqual(['Door Dash', 'DoorDash']);
    expect(analysis.merge_candidates).toEqual([]);
    // Events of both source roles now point at the merged company.
    expect(new Set(analysis.events.map((e) => e.company_id))).toEqual(new Set([c?.company_id]));
  });

  it('makes merges transitive, including through a key that has no postings', () => {
    const analysis = analyze(
      makeInput(
        [
          snap('s1', 'csv', 'x', T1, 'additive', [
            post('Alpha', 'Engineer'),
            post('Gamma', 'Engineer'),
            post('Zulu', 'Engineer'),
          ]),
        ],
        {
          decisions: [
            { a_key: 'alpha', b_key: 'beta', decision: 'merge' },
            { a_key: 'beta', b_key: 'gamma', decision: 'merge' },
          ],
        },
      ),
    );
    expect(analysis.companies.map((c) => c.key).sort()).toEqual(['alpha', 'zulu']);
    const merged = analysis.companies.find((c) => c.key === 'alpha');
    expect(merged?.aliases).toEqual(['Alpha', 'Gamma']);
  });

  it('suppresses a candidate that the user marked not_same, without merging', () => {
    const analysis = analyze(
      makeInput(
        [
          snap('s1', 'csv', 'x', T1, 'additive', [
            post('DoorDash', 'Engineer'),
            post('Door Dash', 'Engineer'),
          ]),
        ],
        { decisions: [{ a_key: 'door dash', b_key: 'doordash', decision: 'not_same' }] },
      ),
    );
    expect(analysis.companies).toHaveLength(2);
    expect(analysis.merge_candidates).toEqual([]);
  });

  it('applies a not_same decision to exactly the pair of canonical keys it names', () => {
    // docs/spec/ambiguities/differential.md D-4. Spec 01 section 3.4 emits a candidate for a pair
    // of group canonical keys "not marked not_same", and a decision marks the pair `a_key`/`b_key`
    // it names. "alpha groupy" was merged into "alpha group", so the candidate is reported for
    // ("alpha group", "alpha groupz"): a not_same recorded against the *member* "alpha groupy"
    // does not name that pair and so does not hide it; the same decision against the canonical
    // pair does. (Both engines and the oracle agree; the earlier "any member" reading was the
    // TypeScript engine's alone.)
    const postings = [
      post('Alpha Group', 'Engineer'),
      post('Alpha Groupy', 'Engineer'),
      post('Alpha Groupz', 'Engineer'),
    ];
    const merge: MergeDecision = { a_key: 'alpha group', b_key: 'alpha groupy', decision: 'merge' };
    const memberNotSame: MergeDecision = {
      a_key: 'alpha groupy',
      b_key: 'alpha groupz',
      decision: 'not_same',
    };
    const canonicalNotSame: MergeDecision = {
      a_key: 'alpha group',
      b_key: 'alpha groupz',
      decision: 'not_same',
    };
    const run = (decisions: MergeDecision[]) =>
      analyze(makeInput([snap('s1', 'csv', 'x', T1, 'additive', postings)], { decisions }));

    const expected = [{ a_key: 'alpha group', b_key: 'alpha groupz', reason: 'near_typo' }];
    expect(run([merge]).merge_candidates).toMatchObject(expected);
    const viaMember = run([merge, memberNotSame]);
    expect(viaMember.companies.map((c) => c.key).sort()).toEqual(['alpha group', 'alpha groupz']);
    expect(viaMember.merge_candidates).toMatchObject(expected);
    const viaCanonical = run([merge, canonicalNotSame]);
    expect(viaCanonical.companies.map((c) => c.key).sort()).toEqual([
      'alpha group',
      'alpha groupz',
    ]);
    expect(viaCanonical.merge_candidates).toEqual([]);
  });

  it('lets a merge through a key that has no postings make that key canonical', () => {
    // D-3: the canonical key is the smallest *member* key; a decision names members, including a
    // key no posting currently has, so "aardvark" (absent) becomes the key of the merged group.
    const analysis = analyze(
      makeInput(
        [
          snap('s1', 'csv', 'x', T1, 'additive', [
            post('Beta', 'Engineer'),
            post('Gamma', 'Engineer'),
          ]),
        ],
        {
          decisions: [
            { a_key: 'aardvark', b_key: 'beta', decision: 'merge' },
            { a_key: 'aardvark', b_key: 'gamma', decision: 'merge' },
          ],
        },
      ),
    );
    expect(analysis.companies).toHaveLength(1);
    expect(analysis.companies[0]?.key).toBe('aardvark');
    expect(analysis.companies[0]?.company_id).toBe(`c_${sha12('aardvark')}`);
    expect(analysis.companies[0]?.aliases).toEqual(['Beta', 'Gamma']);
  });

  it('rejects decisions whose keys are not in ascending order', () => {
    expect(() =>
      analyze(makeInput([], { decisions: [{ a_key: 'b', b_key: 'a', decision: 'merge' }] })),
    ).toThrow(EngineInputError);
    expect(() =>
      analyze(makeInput([], { decisions: [{ a_key: 'a', b_key: 'a', decision: 'merge' }] })),
    ).toThrow(EngineInputError);
  });

  it('assigns a role to the company of its latest company_name', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'lever', 'x', T1, 'full', [
          post('Old Name', 'Engineer', { source_posting_id: '1' }),
        ]),
        snap('s2', 'lever', 'x', T2, 'full', [
          post('New Name', 'Engineer', { source_posting_id: '1' }),
        ]),
      ]),
    );
    expect(analysis.companies.map((c) => c.name)).toEqual(['Old Name']);
    expect(analysis.companies[0]?.key).toBe('new name');
    expect(analysis.companies[0]?.aliases).toEqual(['New Name', 'Old Name']);
  });
});

describe('merge candidate rules', () => {
  const names = (...list: string[]) =>
    analyze(
      makeInput([
        snap(
          's',
          'csv',
          'x',
          T1,
          'additive',
          list.map((n) => post(n, 'Engineer')),
        ),
      ]),
    ).merge_candidates;

  it('token_overlap triggers at 75% Jaccard and not below', () => {
    // {a,b,c} vs {a,b,c,d}: 3/4 = 75%
    expect(names('Alpha Beta Gamma', 'Alpha Beta Gamma Delta')).toMatchObject([
      { reason: 'token_overlap', a_key: 'alpha beta gamma', b_key: 'alpha beta gamma delta' },
    ]);
    // {a,b,c,d} vs {a,b,c,e}: 3/5 = 60%
    expect(names('Alpha Beta Gamma Delta', 'Alpha Beta Gamma Epsilon')).toEqual([]);
  });

  it('token_overlap needs both keys to have two or more tokens', () => {
    expect(names('Acme', 'Acme Labs')).toEqual([]);
  });

  it('near_typo needs both keys of at least six code points', () => {
    expect(names('abcdef', 'abcdeg')).toMatchObject([{ reason: 'near_typo' }]);
    expect(names('abcde', 'abcdf')).toEqual([]);
    expect(names('abcde', 'abcdef')).toEqual([]);
    expect(names('abcdefg', 'abcdefgh')).toMatchObject([{ reason: 'near_typo' }]); // insertion
    expect(names('abcdef', 'abcdfe')).toEqual([]); // a transposition is distance 2
  });

  it('reports the first matching reason and sorts by (reason, a_key, b_key)', () => {
    const result = names(
      'Door Dash',
      'DoorDash',
      'Acme Robotics',
      'Acme Robotic',
      'Zed Co Labs',
      'Zed Labs X',
    );
    expect(result.map((c) => [c.reason, c.a_key, c.b_key])).toEqual([
      ['spacing_variant', 'door dash', 'doordash'],
      ['near_typo', 'acme robotic', 'acme robotics'],
    ]);
  });

  it('prefers spacing_variant over near_typo for the same pair', () => {
    // "door dash"/"doordash": distance 1 as well, but spacing_variant comes first.
    expect(names('Door Dash', 'DoorDash')[0]?.reason).toBe('spacing_variant');
  });

  it('never proposes a pair that merge decisions already joined', () => {
    const result = analyze(
      makeInput(
        [snap('s', 'csv', 'x', T1, 'additive', [post('Door Dash', 'E'), post('DoorDash', 'E')])],
        {
          decisions: [{ a_key: 'door dash', b_key: 'doordash', decision: 'merge' }],
        },
      ),
    );
    expect(result.merge_candidates).toEqual([]);
  });
});

describe('withinOneEdit', () => {
  const levenshtein = (a: string[], b: string[]): number => {
    const row = Array.from({ length: b.length + 1 }, (_, i) => i);
    for (let i = 1; i <= a.length; i += 1) {
      let previous = row[0] ?? 0;
      row[0] = i;
      for (let j = 1; j <= b.length; j += 1) {
        const current = row[j] ?? 0;
        row[j] = Math.min(
          (row[j] ?? 0) + 1,
          (row[j - 1] ?? 0) + 1,
          previous + (a[i - 1] === b[j - 1] ? 0 : 1),
        );
        previous = current;
      }
    }
    return row[b.length] ?? 0;
  };

  it('agrees with a reference Levenshtein on 2000 seeded random pairs', () => {
    const random = mulberry32(31337);
    const alphabet = ['a', 'b', 'c', 'é', '日'];
    const make = (): string[] => {
      const length = Math.floor(random() * 6);
      return Array.from({ length }, () => alphabet[Math.floor(random() * alphabet.length)] ?? 'a');
    };
    for (let i = 0; i < 2000; i += 1) {
      const a = make();
      const b = random() < 0.5 ? make() : mutate(a, random);
      expect(withinOneEdit(a, b), `${a.join('')} / ${b.join('')}`).toBe(levenshtein(a, b) <= 1);
    }
  });

  function mutate(source: string[], random: () => number): string[] {
    const copy = source.slice();
    const kind = Math.floor(random() * 3);
    const at = Math.floor(random() * (copy.length + 1));
    if (kind === 0) copy.splice(at, 0, 'z');
    else if (kind === 1 && copy.length > 0) copy.splice(Math.min(at, copy.length - 1), 1);
    else if (copy.length > 0) copy[Math.min(at, copy.length - 1)] = 'q';
    return copy;
  }
});

describe('findMergeCandidates against a brute-force reference', () => {
  const suffixes = ['', ' labs', ' group', ' robotics', 's'];
  const roots = ['acme', 'door dash', 'doordash', 'northwind', 'north wind', 'blue sky', 'bluesky'];

  it('matches an all-pairs scan on 150 seeded random company sets', () => {
    const random = mulberry32(424242);
    const reference = (keys: string[]): Array<[string, string, string]> => {
      const out: Array<[number, string, string, string]> = [];
      const sorted = Array.from(new Set(keys)).sort(compareCodePoints);
      for (let i = 0; i < sorted.length; i += 1) {
        for (let j = i + 1; j < sorted.length; j += 1) {
          const a = sorted[i] ?? '';
          const b = sorted[j] ?? '';
          const ta = a.split(' ').filter(Boolean);
          const tb = b.split(' ').filter(Boolean);
          const sa = new Set(ta);
          const sb = new Set(tb);
          const inter = [...sa].filter((t) => sb.has(t)).length;
          const union = new Set([...sa, ...sb]).size;
          const pa = Array.from(a);
          const pb = Array.from(b);
          let reason = '';
          let order = -1;
          if (a.split(' ').join('') === b.split(' ').join('')) {
            reason = 'spacing_variant';
            order = 0;
          } else if (ta.length >= 2 && tb.length >= 2 && inter * 100 >= 75 * union) {
            reason = 'token_overlap';
            order = 1;
          } else if (pa.length >= 6 && pb.length >= 6 && withinOneEdit(pa, pb)) {
            reason = 'near_typo';
            order = 2;
          }
          if (order >= 0) out.push([order, a, b, reason]);
        }
      }
      return out
        .sort(
          (x, y) => x[0] - y[0] || compareCodePoints(x[1], y[1]) || compareCodePoints(x[2], y[2]),
        )
        .map(([, a, b, reason]) => [a, b, reason]);
    };

    for (let round = 0; round < 150; round += 1) {
      const count = 2 + Math.floor(random() * 12);
      const keys: string[] = [];
      for (let i = 0; i < count; i += 1) {
        const root = roots[Math.floor(random() * roots.length)] ?? 'acme';
        const suffix = suffixes[Math.floor(random() * suffixes.length)] ?? '';
        keys.push(`${root}${suffix}`);
      }
      const unique = Array.from(new Set(keys));
      const companies = unique.map(
        (key) => ({ key, name: key.toUpperCase() }) as unknown as Company,
      );
      const actual = findMergeCandidates(companies, []).map((c) => [c.a_key, c.b_key, c.reason]);
      expect(actual, unique.join(' | ')).toEqual(reference(unique));
    }
  });
});

describe('role identity and dedup (spec 01 §4, §5)', () => {
  it('keeps two headcounts of the same title and location in one source as two roles', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { location: 'Remote', source_posting_id: '10' }),
          post('Acme', 'Engineer', { location: 'Remote', source_posting_id: '11' }),
        ]),
      ]),
    );
    const roles = rolesOf(analysis, company(analysis, 'Acme'));
    expect(roles).toHaveLength(2);
    expect(new Set(roles.map((r) => r.role_id)).size).toBe(2);
    expect(roles.every((r) => r.observations.length === 1)).toBe(true);
  });

  it('merges the same title and location across sources into one canonical role', () => {
    const analysis = analyze(
      makeInput([
        snap('g', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Engineer (Remote)', {
            location: 'New York, NY',
            source_posting_id: '9',
            url: 'https://boards.example/9',
          }),
        ]),
        snap('c', 'csv', 'conference-list', T2, 'additive', [
          post('ACME Inc', 'Engineer', { location: 'NY - New York' }),
        ]),
      ]),
    );
    expect(analysis.roles).toHaveLength(1);
    const [role] = analysis.roles;
    expect(
      role?.observations.map((o) => [o.source_kind, o.source_ref, o.source_posting_id]),
    ).toEqual([
      ['csv', 'conference-list', null],
      ['greenhouse', 'acme', '9'],
    ]);
    const c = analysis.companies[0];
    expect(role?.role_id).toBe(`r_${sha12(`${c?.company_id}|engineer|new ny york|0`)}`);
  });

  it('matches one-to-one by sorted source role key and strands the surplus', () => {
    const analysis = analyze(
      makeInput([
        snap('g', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { source_posting_id: 'b' }),
          post('Acme', 'Engineer', { source_posting_id: 'a' }),
        ]),
        snap('c', 'csv', 'leads', T1, 'additive', [post('Acme', 'Engineer')]),
      ]),
    );
    expect(analysis.roles).toHaveLength(2);
    const corroborated = analysis.roles.filter((r) => r.observations.length === 2);
    expect(corroborated).toHaveLength(1);
    // Index 0 of greenhouse (sorted keys: a < b) pairs with the csv role.
    expect(
      corroborated[0]?.observations.find((o) => o.source_kind === 'greenhouse')?.source_posting_id,
    ).toBe('a');
    const c = analysis.companies[0];
    expect(corroborated[0]?.role_id).toBe(`r_${sha12(`${c?.company_id}|engineer||0`)}`);
    const single = analysis.roles.find((r) => r.observations.length === 1);
    expect(single?.role_id).toBe(`r_${sha12(`${c?.company_id}|engineer||1`)}`);
  });

  it('does not match across sources when title_key or location_key differ', () => {
    const analysis = analyze(
      makeInput([
        snap('g', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { location: 'Paris' }),
        ]),
        snap('c', 'csv', 'x', T1, 'additive', [post('Acme', 'Engineer', { location: 'Berlin' })]),
        snap('d', 'csv', 'y', T1, 'additive', [
          post('Acme', 'Senior Engineer', { location: 'Paris' }),
        ]),
      ]),
    );
    expect(analysis.roles).toHaveLength(3);
  });

  it('merges roles across sources after a company merge', () => {
    const base = [
      snap('g', 'greenhouse', 'a', T1, 'full', [
        post('DoorDash', 'Engineer', { source_posting_id: '1' }),
      ]),
      snap('c', 'csv', 'b', T1, 'additive', [post('Door Dash', 'Engineer')]),
    ];
    expect(analyze(makeInput(base)).roles).toHaveLength(2);
    const merged = analyze(
      makeInput(base, {
        decisions: [{ a_key: 'door dash', b_key: 'doordash', decision: 'merge' }],
      }),
    );
    expect(merged.roles).toHaveLength(1);
    expect(merged.roles[0]?.observations).toHaveLength(2);
  });

  it('takes display fields from the member seen most recently, ties by smallest key', () => {
    const analysis = analyze(
      makeInput([
        snap('g', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Engineer', {
            location: 'Paris',
            work_mode: 'onsite',
            department: 'Eng',
            source_posting_id: '1',
          }),
        ]),
        snap('c', 'csv', 'leads', T2, 'additive', [
          post('Acme', 'Engineer (Platform)', { location: 'paris', work_mode: 'hybrid' }),
        ]),
      ]),
    );
    const [role] = analysis.roles;
    expect(role).toMatchObject({
      title: 'Engineer (Platform)',
      location: 'paris',
      work_mode: 'hybrid',
      department: null,
      first_seen: T1,
      last_seen: T2,
    });
  });

  it('takes the earliest posted_at among members and the latest last_seen among active members', () => {
    const analysis = analyze(
      makeInput([
        snap('g', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1', posted_at: '2026-08-20' }),
        ]),
        snap('c', 'csv', 'leads', T2, 'additive', [
          post('Acme', 'Engineer', { posted_at: '2026-08-10' }),
        ]),
        snap('g2', 'greenhouse', 'acme', T2, 'full', []),
      ]),
    );
    const [role] = analysis.roles;
    expect(role?.posted_at).toBe('2026-08-10');
    // greenhouse member removed at T2; csv member still active, last seen T2.
    expect(role).toMatchObject({ status: 'active', last_seen: T2, removed_at: null });
    expect(role?.observations.map((o) => [o.source_kind, o.status])).toEqual([
      ['csv', 'active'],
      ['greenhouse', 'removed'],
    ]);
  });

  it('marks a canonical role removed only when every member is removed', () => {
    const analysis = analyze(
      makeInput([
        snap('g', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
        ]),
        snap('l', 'lever', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { source_posting_id: 'x' }),
        ]),
        snap('g2', 'greenhouse', 'acme', T2, 'full', []),
        snap('l2', 'lever', 'acme', '2026-09-20T08:00:00Z', 'full', []),
      ]),
    );
    const [role] = analysis.roles;
    expect(role).toMatchObject({
      status: 'removed',
      removed_at: '2026-09-20T08:00:00Z',
      last_seen: T1,
    });
  });
});
