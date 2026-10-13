/**
 * Seeded randomized invariant suite (spec 02): 400 generated inputs, each checked against
 * structural invariants and against an independent re-derivation of the scoring formulas from the
 * engine's own output (so a mistake would have to be made twice, in two different shapes).
 */
import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import {
  analyze,
  parseDate,
  parseTimestamp,
  tokenSequenceMatch,
  titleKey,
  type Analysis,
  type AnalyzeInput,
  type CompanyAnalysis,
  type MergeDecision,
  type PostingInput,
  type Profile,
  type SnapshotInput,
  type SourceKind,
} from '../src/engine';
import { mulberry32 } from './helpers';

const CASES = 400;
const AS_OF_BASE = Date.parse('2026-10-13T12:00:00Z');
const DAY_MS = 86_400_000;

const COMPANY_NAMES = [
  'Acme',
  'ACME Inc.',
  'acme, inc',
  'The Acme Corporation',
  'Acme Robotics',
  'Acme Robotic',
  'DoorDash',
  'Door Dash',
  'Globex LLC',
  'Globex',
  'Initech',
  'Hooli GmbH',
  'Umbrella Co',
  'Stark Industries',
  'Wayne Enterprises',
  'Wayne Enterprise',
];
const TITLES = [
  'Software Engineer',
  'Senior Software Engineer (Remote)',
  'Engineering Manager',
  'Engineer Intern',
  'Data Analyst',
  'Recruiter',
  'Staff Engineer [US]',
  'Product Designer',
  'DevOps Engineer',
  'Sales Executive',
  'Engineer',
];
const LOCATIONS = [
  null,
  'Remote',
  'New York, NY',
  'NY - New York',
  'Berlin',
  'London, UK',
  'Paris',
];
const SOURCES: Array<[SourceKind, string]> = [
  ['greenhouse', 'acme'],
  ['lever', 'acme'],
  ['ashby', 'globex'],
  ['csv', 'list-a'],
  ['csv', 'list-b'],
  ['manual', 'manual'],
];
const KEYWORD_POOL = ['engineer', 'analyst', 'software engineer', 'manager', 'designer'];
const EXCLUDE_POOL = ['intern', 'manager', 'recruiter'];

const iso = (ms: number): string => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');

function pick<T>(random: () => number, list: readonly T[]): T {
  if (list.length === 0) throw new Error('empty pool');
  return list[Math.floor(random() * list.length)] as T;
}

function generate(random: () => number): AnalyzeInput {
  const asOfMs = AS_OF_BASE + Math.floor((random() - 0.5) * 20 * DAY_MS);
  const snapshotCount = 1 + Math.floor(random() * 6);
  const snapshots: SnapshotInput[] = [];
  for (let s = 0; s < snapshotCount; s += 1) {
    const [kind, ref] = pick(random, SOURCES);
    const ageDays = Math.floor(random() * 130) - 10; // some snapshots lie after as_of
    const observedMs = asOfMs - ageDays * DAY_MS - Math.floor(random() * 86_400) * 1000;
    const atsLike = kind === 'greenhouse' || kind === 'lever' || kind === 'ashby';
    const mode = random() < (atsLike ? 0.85 : 0.1) ? 'full' : 'additive';
    const postingCount = Math.floor(random() * 9);
    const postings: PostingInput[] = [];
    for (let p = 0; p < postingCount; p += 1) {
      const posting: PostingInput = {
        company_name: pick(random, COMPANY_NAMES),
        title: pick(random, TITLES),
        location: pick(random, LOCATIONS),
        work_mode: pick(random, ['remote', 'hybrid', 'onsite', 'unknown', undefined] as const),
      };
      if (atsLike && random() < 0.8)
        posting.source_posting_id = String(1 + Math.floor(random() * 12));
      if (random() < 0.4) {
        posting.posted_at = iso(asOfMs - Math.floor(random() * 120) * DAY_MS).slice(0, 10);
      }
      if (random() < 0.3) posting.url = `https://jobs.example/${Math.floor(random() * 99)}`;
      if (random() < 0.2) posting.department = pick(random, ['Eng', 'Ops', 'Data']);
      postings.push(posting);
    }
    snapshots.push({
      snapshot_id: `s${s}`,
      source_kind: kind,
      source_ref: ref,
      observed_at: iso(observedMs),
      mode,
      postings,
    });
  }

  const decisions: MergeDecision[] = [];
  const decisionKeys = [
    'acme',
    'acme robotic',
    'acme robotics',
    'door dash',
    'doordash',
    'globex',
    'initech',
    'wayne enterprise',
    'wayne enterprises',
    'zzz',
  ];
  const decisionCount = Math.floor(random() * 4);
  for (let d = 0; d < decisionCount; d += 1) {
    const a = pick(random, decisionKeys);
    const b = pick(random, decisionKeys);
    if (a === b) continue;
    const [lo, hi] = a < b ? [a, b] : [b, a];
    decisions.push({ a_key: lo, b_key: hi, decision: random() < 0.6 ? 'merge' : 'not_same' });
  }

  const profile: Profile = { include_keywords: [], exclude_keywords: [] };
  if (random() < 0.7) {
    const includeCount = 1 + Math.floor(random() * 2);
    for (let i = 0; i < includeCount; i += 1) {
      const keyword = pick(random, KEYWORD_POOL);
      if (!profile.include_keywords.includes(keyword)) profile.include_keywords.push(keyword);
    }
    if (random() < 0.5) profile.exclude_keywords.push(pick(random, EXCLUDE_POOL));
  }

  return { as_of: iso(asOfMs), profile, decisions, snapshots };
}

function shuffled<T>(random: () => number, list: readonly T[]): T[] {
  const copy = list.slice();
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    const a = copy[i];
    const b = copy[j];
    if (a !== undefined && b !== undefined) {
      copy[i] = b;
      copy[j] = a;
    }
  }
  return copy;
}

const sha12 = (text: string): string =>
  createHash('sha256').update(text, 'utf8').digest('hex').slice(0, 12);

/** Round half up for non-negative integers, via BigInt (a different shape from the engine's). */
function rhu(numerator: number, denominator: number): number {
  const n = BigInt(numerator);
  const d = BigInt(denominator);
  return Number((2n * n + d) / (2n * d));
}

const VOLUME = [0, 300, 480, 600, 690, 760, 820, 870, 910, 950, 1000];
const SOURCE_WEIGHT: Record<string, number> = {
  greenhouse: 1000,
  lever: 1000,
  ashby: 1000,
  csv: 600,
  manual: 400,
};
const WEIGHTS = [30, 20, 15, 10, 15, 10];
const KEYS = ['role_relevance', 'volume', 'change', 'urgency', 'source_confidence', 'freshness'];
const REASON_ORDER = ['spacing_variant', 'token_overlap', 'near_typo'];

function checkInvariants(input: AnalyzeInput, a: Analysis): void {
  const profile = input.profile ?? { include_keywords: [], exclude_keywords: [] };
  const configured = profile.include_keywords.length > 0;
  const asOf = parseTimestamp(a.as_of) ?? NaN;
  const inScope = (title: string): boolean => {
    if (!configured) return true;
    const key = titleKey(title);
    const included = profile.include_keywords.some((k) => tokenSequenceMatch(key, k));
    return included && !profile.exclude_keywords.some((k) => tokenSequenceMatch(key, k));
  };

  // --- companies ---------------------------------------------------------------------------
  const companyIds = new Set(a.companies.map((c) => c.company_id));
  expect(companyIds.size).toBe(a.companies.length);
  const scored = a.companies.filter((c) => c.score !== null);
  scored.forEach((c, i) => expect(c.rank).toBe(i + 1));
  expect(a.companies.slice(0, scored.length)).toEqual(scored); // scored come first
  for (let i = 1; i < scored.length; i += 1) {
    const prev = scored[i - 1];
    const cur = scored[i];
    if (prev === undefined || cur === undefined) continue;
    const order =
      (cur.score ?? 0) - (prev.score ?? 0) ||
      (prev.key < cur.key ? -1 : prev.key > cur.key ? 1 : 0);
    expect(order).toBeLessThanOrEqual(0);
  }
  const unscored = a.companies.slice(scored.length);
  for (const c of unscored) {
    expect(c.score).toBeNull();
    expect(c.rank).toBeNull();
    expect(c.coverage).toBe(0);
  }

  for (const c of a.companies) {
    expect(c.company_id).toBe(`c_${sha12(c.key)}`);
    expect(c.aliases).toEqual([...new Set(c.aliases)].sort());
    expect(c.aliases).toContain(c.name);
    expect(c.components.map((x) => x.key)).toEqual(KEYS);
    expect(c.components.map((x) => x.weight)).toEqual(WEIGHTS);

    let coverage = 0;
    let weighted = 0;
    for (const comp of c.components) {
      if (comp.value === null) {
        expect(comp.reason_code).not.toBeNull();
      } else {
        expect(comp.reason_code).toBeNull();
        expect(Number.isInteger(comp.value)).toBe(true);
        expect(comp.value).toBeGreaterThanOrEqual(0);
        expect(comp.value).toBeLessThanOrEqual(1000);
        coverage += comp.weight;
        weighted += comp.weight * comp.value;
      }
    }
    expect(c.coverage).toBe(coverage);
    if (coverage === 0) {
      expect(c.score).toBeNull();
    } else {
      expect(c.score).toBe(rhu(weighted, coverage));
      expect(c.score).toBeGreaterThanOrEqual(0);
      expect(c.score).toBeLessThanOrEqual(1000);
    }
    checkCompanyAgainstRoles(input, a, c, configured, asOf, inScope);
  }

  // --- roles -------------------------------------------------------------------------------
  const roleIds = new Set(a.roles.map((r) => r.role_id));
  expect(roleIds.size).toBe(a.roles.length);
  const companyOrder = new Map(a.companies.map((c, i) => [c.company_id, i]));
  let previous: (typeof a.roles)[number] | undefined;
  for (const role of a.roles) {
    expect(companyIds.has(role.company_id)).toBe(true);
    expect(role.role_id).toMatch(/^r_[0-9a-f]{12}$/);
    expect(role.first_seen <= role.last_seen).toBe(true);
    expect(role.observations.length).toBeGreaterThan(0);
    expect(Number.isInteger(role.age_days) && role.age_days >= 0).toBe(true);
    expect(role.relevant === null).toBe(!configured);
    if (role.status === 'active') {
      expect(role.removed_at).toBeNull();
      expect(role.observations.some((o) => o.status === 'active')).toBe(true);
    } else {
      expect(role.removed_at).not.toBeNull();
      expect(role.observations.every((o) => o.status === 'removed')).toBe(true);
    }
    const sortedObservations = role.observations
      .map((o) => `${o.source_kind}\u0000${o.source_ref}\u0000${o.source_posting_id ?? ''}`)
      .slice();
    expect(sortedObservations).toEqual([...sortedObservations].sort());
    const distinctSources = new Set(
      role.observations.map((o) => `${o.source_kind}|${o.source_ref}`),
    );
    expect(distinctSources.size).toBe(role.observations.length);
    if (previous !== undefined) {
      const pc = companyOrder.get(previous.company_id) ?? 0;
      const cc = companyOrder.get(role.company_id) ?? 0;
      expect(pc).toBeLessThanOrEqual(cc);
      if (pc === cc) {
        const rank = (r: typeof role): number => (r.status === 'active' ? 0 : 1);
        expect(rank(previous)).toBeLessThanOrEqual(rank(role));
        if (rank(previous) === rank(role)) {
          expect(previous.first_seen <= role.first_seen).toBe(true);
          if (previous.first_seen === role.first_seen)
            expect(previous.role_id < role.role_id).toBe(true);
        }
      }
    }
    previous = role;
  }

  // --- events ------------------------------------------------------------------------------
  const rolesById = new Map(a.roles.map((r) => [r.role_id, r]));
  let lastAt = '';
  for (const e of a.events) {
    const role = rolesById.get(e.role_id);
    expect(role, `event references unknown role ${e.role_id}`).toBeDefined();
    expect(role?.company_id).toBe(e.company_id);
    expect(e.at <= a.as_of).toBe(true);
    expect(e.at >= lastAt).toBe(true);
    lastAt = e.at;
    if (e.type === 'changed') {
      expect(e.fields).not.toBeNull();
      expect(e.fields).toEqual([...(e.fields ?? [])].sort());
      expect((e.fields ?? []).length).toBeGreaterThan(0);
    } else {
      expect(e.fields).toBeNull();
    }
  }

  // --- merge candidates --------------------------------------------------------------------
  const byKey = new Map(a.companies.map((c) => [c.key, c]));
  let lastOrder = -1;
  for (const m of a.merge_candidates) {
    expect(m.a_key < m.b_key).toBe(true);
    expect(m.candidate_id).toBe(sha12(`${m.a_key}|${m.b_key}`));
    expect(byKey.get(m.a_key)?.name).toBe(m.a_name);
    expect(byKey.get(m.b_key)?.name).toBe(m.b_name);
    const order = REASON_ORDER.indexOf(m.reason);
    expect(order).toBeGreaterThanOrEqual(lastOrder);
    lastOrder = order;
    for (const d of input.decisions ?? []) {
      if (d.decision === 'not_same') {
        expect(`${d.a_key}|${d.b_key}`).not.toBe(`${m.a_key}|${m.b_key}`);
      }
    }
  }

  // --- stats -------------------------------------------------------------------------------
  const processed = input.snapshots.filter((s) => s.observed_at <= a.as_of);
  expect(a.stats).toEqual({
    snapshots: processed.length,
    postings_observed: processed.reduce((n, s) => n + s.postings.length, 0),
    companies: a.companies.length,
    active_roles: a.companies.reduce((n, c) => n + c.active_roles, 0),
  });
}

/** Re-derive a company's counts and component values from the roles and events in `a`. */
function checkCompanyAgainstRoles(
  input: AnalyzeInput,
  a: Analysis,
  c: CompanyAnalysis,
  configured: boolean,
  asOf: number,
  inScope: (title: string) => boolean,
): void {
  const roles = a.roles.filter((r) => r.company_id === c.company_id);
  if (configured) for (const r of roles) expect(r.relevant).toBe(inScope(r.title));
  const active = roles.filter((r) => r.status === 'active');
  const relevant = active.filter((r) => r.relevant === true);
  const scope = configured ? relevant : active;
  expect(roles.length).toBeGreaterThan(0); // every company has at least one role
  expect(c.active_roles).toBe(active.length);
  expect(c.removed_roles).toBe(roles.length - active.length);
  expect(c.relevant_roles).toBe(configured ? relevant.length : null);
  expect(c.first_seen).toBe(roles.map((r) => r.first_seen).sort()[0]);
  const lastSeen =
    active
      .map((r) => r.last_seen)
      .sort()
      .at(-1) ?? null;
  expect(c.last_seen).toBe(lastSeen);

  const get = (key: string) => c.components.find((x) => x.key === key);
  const role = get('role_relevance');
  const volume = get('volume');
  const change = get('change');
  const urgency = get('urgency');
  const confidence = get('source_confidence');
  const freshness = get('freshness');
  if (
    role === undefined ||
    volume === undefined ||
    change === undefined ||
    urgency === undefined ||
    confidence === undefined ||
    freshness === undefined
  ) {
    throw new Error('missing component');
  }

  // History span, derived independently from the raw input: the distinct observed_at of every
  // `full` snapshot (<= as_of) of every source that supplied a role to this company.
  const sources = new Set(
    roles.flatMap((r) => r.observations.map((o) => `${o.source_kind}|${o.source_ref}`)),
  );
  const times = new Set(
    input.snapshots
      .filter(
        (s) =>
          s.mode === 'full' &&
          s.observed_at <= a.as_of &&
          sources.has(`${s.source_kind}|${s.source_ref.trim()}`),
      )
      .map((s) => s.observed_at),
  );
  let expectedSpan: number | null = null;
  if (times.size >= 2) {
    const seconds = [...times].map((t) => parseTimestamp(t) ?? NaN);
    expectedSpan = Math.floor((Math.max(...seconds) - Math.min(...seconds)) / 86400);
  }
  expect((change.inputs as { span_days: number | null }).span_days).toBe(expectedSpan);

  if (active.length === 0) {
    for (const comp of c.components) expect(comp.reason_code).toBe('no_active_roles');
    expect(c.score).toBeNull();
    expect(c.last_seen).toBeNull();
    return;
  }

  // role_relevance
  if (!configured) {
    expect(role).toMatchObject({ value: null, reason_code: 'no_keywords' });
  } else {
    expect(role.value).toBe(rhu(1000 * relevant.length, active.length));
    expect(role.inputs).toEqual({ relevant: relevant.length, active: active.length });
  }

  // volume
  expect(volume.value).toBe(VOLUME[Math.min(scope.length, 10)]);
  expect(volume.inputs).toEqual({ scope_roles: scope.length });

  // freshness
  const days = Math.max(0, Math.floor((asOf - (parseTimestamp(lastSeen ?? '') ?? NaN)) / 86400));
  const expectedFreshness = days <= 7 ? 1000 : days >= 60 ? 0 : rhu(1000 * (60 - days), 53);
  expect(freshness.value).toBe(expectedFreshness);

  // change
  const spanDays = (change.inputs as { span_days: number | null }).span_days;
  if (spanDays === null || spanDays < 14) {
    expect(change).toMatchObject({ value: null, reason_code: 'insufficient_history' });
  } else {
    let added = 0;
    let removed = 0;
    for (const e of a.events) {
      if (e.company_id !== c.company_id) continue;
      const at = parseTimestamp(e.at) ?? NaN;
      if (!(at > asOf - 2_592_000 && at <= asOf)) continue;
      if (!inScope(e.title)) continue;
      if (e.type === 'added' || e.type === 'reappeared') added += 1;
      if (e.type === 'removed') removed += 1;
    }
    expect(change.inputs).toEqual({
      added,
      removed,
      net: added - removed,
      span_days: spanDays,
      window_days: 30,
    });
    expect(change.value).toBe(Math.min(1000, Math.max(0, 500 + 100 * (added - removed))));
  }

  // urgency
  let known = 0;
  let aged = 0;
  for (const r of scope) {
    let age: number | null = null;
    if (r.posted_at !== null) {
      age = Math.floor((asOf - (parseDate(r.posted_at) ?? NaN)) / 86400);
    } else if (spanDays !== null && spanDays >= 45) {
      age = Math.floor((asOf - (parseTimestamp(r.first_seen) ?? NaN)) / 86400);
    }
    if (age === null) continue;
    known += 1;
    if (Math.max(0, age) >= 45) aged += 1;
  }
  if (scope.length === 0) expect(urgency.reason_code).toBe('no_scope_roles');
  else if (known === 0) expect(urgency.reason_code).toBe('no_dated_roles');
  else expect(urgency.value).toBe(rhu(1000 * aged, known));
  expect(urgency.inputs).toEqual({ aged, known, threshold_days: 45 });

  // source_confidence
  if (scope.length === 0) {
    expect(confidence).toMatchObject({ value: null, reason_code: 'no_scope_roles' });
  } else {
    let total = 0;
    let corroborated = 0;
    for (const r of scope) {
      const live = r.observations.filter((o) => o.status === 'active');
      let best = 0;
      for (const o of live) best = Math.max(best, SOURCE_WEIGHT[o.source_kind] ?? 0);
      const distinct = new Set(live.map((o) => `${o.source_kind}|${o.source_ref}`));
      if (distinct.size >= 2) {
        total += Math.min(1000, best + 100);
        corroborated += 1;
      } else {
        total += best;
      }
    }
    expect(confidence.value).toBe(rhu(total, scope.length));
    expect(confidence.inputs).toEqual({ scope_roles: scope.length, corroborated });
  }
}

describe(`randomized invariants over ${CASES} generated inputs`, () => {
  const random = mulberry32(0x5eed2026);
  const inputs = Array.from({ length: CASES }, () => generate(random));

  it('generates varied inputs (sanity check on the generator itself)', () => {
    const analyses = inputs.map((input) => analyze(input));
    expect(analyses.some((a) => a.merge_candidates.length > 0)).toBe(true);
    expect(analyses.some((a) => a.events.some((e) => e.type === 'changed'))).toBe(true);
    expect(analyses.some((a) => a.events.some((e) => e.type === 'removed'))).toBe(true);
    expect(analyses.some((a) => a.events.some((e) => e.type === 'reappeared'))).toBe(true);
    expect(analyses.some((a) => a.roles.some((r) => r.observations.length > 1))).toBe(true);
    expect(analyses.some((a) => a.companies.some((c) => c.score === null))).toBe(true);
    expect(analyses.some((a) => a.companies.some((c) => c.coverage === 100))).toBe(true);
    expect(analyses.some((a) => a.companies.length >= 4)).toBe(true);
  });

  it('satisfies every structural and scoring invariant', () => {
    inputs.forEach((input, index) => {
      const analysis = analyze(input);
      try {
        checkInvariants(input, analysis);
      } catch (error) {
        throw new Error(
          `invariant violated for generated case #${index}: ${(error as Error).message}`,
          { cause: error },
        );
      }
    });
  });

  it('is deterministic and independent of snapshot and decision order', () => {
    const shuffle = mulberry32(77);
    inputs.forEach((input, index) => {
      const first = analyze(input);
      expect(analyze(input), `case #${index} rerun`).toEqual(first);
      const reordered: AnalyzeInput = {
        ...input,
        snapshots: shuffled(shuffle, input.snapshots),
        decisions: shuffled(shuffle, input.decisions ?? []),
      };
      expect(analyze(reordered), `case #${index} reordered`).toEqual(first);
    });
  });

  it('ignores snapshots observed after as_of', () => {
    inputs.forEach((input, index) => {
      const without: AnalyzeInput = {
        ...input,
        snapshots: input.snapshots.filter((s) => s.observed_at <= input.as_of),
      };
      expect(analyze(input), `case #${index}`).toEqual(analyze(without));
    });
  });

  it('serializes to JSON without loss', () => {
    for (const input of inputs.slice(0, 100)) {
      const analysis = analyze(input);
      expect(JSON.parse(JSON.stringify(analysis))).toEqual(analysis);
    }
  });
});
