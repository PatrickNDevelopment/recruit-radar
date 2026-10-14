/**
 * Regression tests for the readings fixed by the differential review (D-1 .. D-10).
 *
 * The Python engine, this engine and the oracle were written independently from the same spec and
 * disagreed on each of these points while every golden vector still passed. The decisions and the
 * spec text they rest on: docs/spec/ambiguities/differential.md. Python twin:
 * backend/tests/engine/test_engine_differential.py. D-2, D-3 and D-4 are pinned by vectors 45-47.
 */
import { describe, expect, it } from 'vitest';
import { analyze, EngineInputError, type AnalyzeInput, type PostingInput } from '../src/engine';
import { trimText } from '../src/engine/normalize';
import { AS_OF, company, makeInput, post, snap } from './helpers';

const T1 = '2026-10-01T00:00:00Z';

function oneSnapshot(postings: PostingInput[], ref = 'acme', mode: 'full' | 'additive' = 'full') {
  return snap('s1', 'greenhouse', ref, T1, mode, postings);
}

function rejected(payload: unknown): boolean {
  try {
    analyze(payload as AnalyzeInput);
  } catch (error) {
    return error instanceof EngineInputError;
  }
  return false;
}

// ECMA-262 WhiteSpace + LineTerminator: exactly what String.prototype.trim removes.
const ECMASCRIPT_TRIMMED = new Set<number>([
  0x09,
  0x0a,
  0x0b,
  0x0c,
  0x0d,
  0x20,
  0xa0,
  0x1680,
  0x2028,
  0x2029,
  0x202f,
  0x205f,
  0x3000,
  0xfeff,
  ...Array.from({ length: 0x0b }, (_, i) => 0x2000 + i),
]);

describe('D-1 trim is the ECMAScript set', () => {
  it('trimText agrees with the set over the whole BMP', () => {
    const disagreements: number[] = [];
    for (let cp = 0; cp < 0x10000; cp += 1) {
      if (cp >= 0xd800 && cp <= 0xdfff) continue;
      const c = String.fromCodePoint(cp);
      if ((trimText(`${c}x${c}`) === 'x') !== ECMASCRIPT_TRIMMED.has(cp)) disagreements.push(cp);
    }
    expect(disagreements).toEqual([]);
  });

  it('a BOM is trimmed but NEL and the C0 separators are not', () => {
    expect(trimText('\ufeffAcme\ufeff')).toBe('Acme');
    expect(trimText('\u0085Acme')).toBe('\u0085Acme');
    expect(trimText('\u001cAcme\u001f')).toBe('\u001cAcme\u001f');
  });

  it('analyze trims with the same set', () => {
    const raw = post('\ufeff Acme \u3000', '\u0085Engineer\u0085', {
      location: '\u00a0Berlin\u00a0',
    });
    const result = analyze(makeInput([oneSnapshot([raw])]));
    expect(company(result, 'Acme').name).toBe('Acme');
    expect(result.roles[0]?.title).toBe('\u0085Engineer\u0085');
    expect(result.roles[0]?.location).toBe('Berlin');
  });
});

describe('D-4 not_same names the canonical pair', () => {
  const postings = [
    post('Alpha Group', 'Engineer'),
    post('Alpha Groupy', 'Engineer'),
    post('Alpha Groupz', 'Engineer'),
  ];
  const merge = { a_key: 'alpha group', b_key: 'alpha groupy', decision: 'merge' as const };

  function candidates(...extra: NonNullable<AnalyzeInput['decisions']>) {
    const result = analyze(
      makeInput([snap('s1', 'csv', 'x', T1, 'additive', postings)], {
        decisions: [merge, ...extra],
      }),
    );
    return result.merge_candidates.map((c) => [c.a_key, c.b_key, c.reason]);
  }

  it('reports the candidate between canonical keys', () => {
    expect(candidates()).toEqual([['alpha group', 'alpha groupz', 'near_typo']]);
  });

  it('a decision naming a non-canonical member does not hide it', () => {
    const member = { a_key: 'alpha groupy', b_key: 'alpha groupz', decision: 'not_same' as const };
    expect(candidates(...[member])).toEqual([['alpha group', 'alpha groupz', 'near_typo']]);
  });

  it('a decision naming the canonical pair hides it', () => {
    const pair = { a_key: 'alpha group', b_key: 'alpha groupz', decision: 'not_same' as const };
    expect(candidates(...[pair])).toEqual([]);
  });
});

describe('D-6 instants are not trimmed', () => {
  it.each([
    ' 2026-10-13T12:00:00Z',
    '2026-10-13T12:00:00Z ',
    '\t2026-10-13T12:00:00Z',
    '2026-10-13T12:00:00Z\n',
    '\ufeff2026-10-13T12:00:00Z',
  ])('rejects padded as_of %j', (bad) => {
    expect(rejected(makeInput([], { as_of: bad }))).toBe(true);
  });

  it.each([' 2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z\t'])(
    'rejects padded observed_at %j',
    (bad) => {
      expect(rejected(makeInput([snap('s', 'greenhouse', 'a', bad, 'full', [])]))).toBe(true);
    },
  );

  it('accepts the exact form', () => {
    expect(analyze(makeInput([snap('s', 'greenhouse', 'a', T1, 'full', [])])).as_of).toBe(AS_OF);
  });
});

describe('D-7 omitted collections are empty; null is not an omission', () => {
  it('missing snapshots is an empty analysis', () => {
    const result = analyze({ as_of: AS_OF } as unknown as AnalyzeInput);
    expect(result.companies).toEqual([]);
    expect(result.stats.snapshots).toBe(0);
  });

  it('missing postings is an empty snapshot', () => {
    const s = snap('s', 'greenhouse', 'a', T1, 'full', []) as unknown as Record<string, unknown>;
    delete s['postings'];
    expect(analyze(makeInput([s as never])).stats).toEqual({
      snapshots: 1,
      postings_observed: 0,
      companies: 0,
      active_roles: 0,
    });
  });

  it('null is rejected', () => {
    expect(rejected({ as_of: AS_OF, snapshots: null })).toBe(true);
    const s = snap('s', 'greenhouse', 'a', T1, 'full', []) as unknown as Record<string, unknown>;
    s['postings'] = null;
    expect(rejected(makeInput([s as never]))).toBe(true);
  });
});

describe('D-8 url constrains the scheme only', () => {
  it.each([
    'https://example.com/jobs/1',
    'http://example.com',
    'HTTPS://EXAMPLE.COM',
    'Http://x',
    'https:',
    'https://',
    'http:example.com',
    'https://exa mple.com/a b',
    'https://example.com/\u0001',
    'https://example.com/a\nb',
  ])('accepts %j', (value) => {
    const result = analyze(makeInput([oneSnapshot([post('Acme', 'Engineer', { url: value })])]));
    expect(result.roles[0]?.observations[0]?.url).toBe(value);
  });

  it.each([
    'ftp://example.com/x',
    'javascript:alert(1)',
    'data:text/html,hi',
    'mailto:someone@example.com',
    '//example.com/x',
    'example.com/jobs',
    '/jobs/1',
    'ht\ttps://example.com',
    '\u0001https://example.com',
    'http\u017f://example.com',
    'https\uff1a//example.com',
  ])('rejects %j', (value) => {
    expect(rejected(makeInput([oneSnapshot([post('Acme', 'Engineer', { url: value })])]))).toBe(
      true,
    );
  });
});

describe('D-9 keyword limits are enforced at the engine boundary', () => {
  const kw = (include: string[], exclude: string[] = []) =>
    makeInput([], { profile: { include_keywords: include, exclude_keywords: exclude } });

  it('accepts 50 keywords of 60 code points', () => {
    analyze(kw(Array(50).fill('k'.repeat(60)), Array(50).fill('\u{1f600}'.repeat(60))));
  });

  it('rejects 51 keywords', () => {
    expect(rejected(kw(Array.from({ length: 51 }, (_, i) => `k${i}`)))).toBe(true);
    expect(
      rejected(
        kw(
          ['a'],
          Array.from({ length: 51 }, (_, i) => `k${i}`),
        ),
      ),
    ).toBe(true);
  });

  it('rejects a 61 code point keyword (code points, not UTF-16 units)', () => {
    expect(rejected(kw(['k'.repeat(61)]))).toBe(true);
    expect(rejected(kw(['\u{1f600}'.repeat(61)]))).toBe(true);
  });

  it('applies the limit after trimming', () => {
    analyze(kw([`  ${'k'.repeat(60)}  `]));
    expect(rejected(kw([`  ${'k'.repeat(61)}  `]))).toBe(true);
  });

  it('a blank keyword is allowed and never matches', () => {
    const result = analyze(
      makeInput([oneSnapshot([post('Acme', 'Engineer')])], {
        profile: { include_keywords: ['', '   '], exclude_keywords: [] },
      }),
    );
    expect(result.roles[0]?.relevant).toBe(false);
  });
});

describe('D-10 posting-level source_ref', () => {
  it('a present but empty source_ref is invalid', () => {
    for (const value of ['', '   ', '\t']) {
      const raw = { ...post('Acme', 'Engineer'), source_ref: value } as PostingInput;
      expect(rejected(makeInput([oneSnapshot([raw])])), JSON.stringify(value)).toBe(true);
    }
  });

  it('null and absent inherit the snapshot source', () => {
    const withNull = { ...post('Acme', 'Engineer'), source_ref: null } as unknown as PostingInput;
    for (const raw of [withNull, post('Acme', 'Engineer')]) {
      analyze(makeInput([oneSnapshot([raw])]));
    }
  });

  it('a padded copy of the snapshot source agrees', () => {
    const raw = { ...post('Acme', 'Engineer'), source_ref: '  acme  ' } as PostingInput;
    analyze(makeInput([oneSnapshot([raw], 'acme')]));
  });
});
