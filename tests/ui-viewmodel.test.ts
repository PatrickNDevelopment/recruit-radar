import { describe, expect, it } from 'vitest';
import { analyze, type AnalyzeInput, type Profile, type SnapshotInput } from '../src/engine';
import { summarizeDatasets } from '../src/data/derive';
import { LocalSource } from '../src/data/localSource';
import { MemoryStorage } from '../src/data/storage';
import { DEFAULT_FILTERS, DEFAULT_SORT, type Workspace } from '../src/data/types';
import { COPY } from '../src/ui/copy';
import {
  ariaSortFor,
  buildCompanyDetail,
  buildRadarRows,
  componentViews,
  coverageText,
  decisionRows,
  describeInputs,
  exportFileName,
  filterRows,
  filtersAreDefault,
  missingInformation,
  nextSort,
  radarView,
  reconcileFilters,
  roleMixText,
  signalText,
  sortRows,
  viewMatches,
} from '../src/ui/viewModel';
import { csv, makeClock, NOW } from './data-helpers';

const NO_PROFILE: Profile = { include_keywords: [], exclude_keywords: [] };

function workspaceFrom(input: AnalyzeInput, extras: Partial<Workspace> = {}): Workspace {
  const analysis = analyze(input);
  return {
    mode: 'local',
    analysis,
    profile: input.profile ?? NO_PROFILE,
    decisions: [],
    shortlist: [],
    datasets: summarizeDatasets(analysis),
    has_sample_data: false,
    notices: [],
    ...extras,
  };
}

async function sampleWorkspace(): Promise<{ source: LocalSource; ws: Workspace }> {
  const source = new LocalSource({ storage: new MemoryStorage(), clock: makeClock() });
  await source.loadSample();
  return { source, ws: await source.load() };
}

function row(rows: ReturnType<typeof buildRadarRows>, name: string) {
  const found = rows.find((candidate) => candidate.name === name);
  if (found === undefined) throw new Error(`no row for ${name}`);
  return found;
}

describe('buildRadarRows (sample data)', () => {
  it('summarises role mix, locations, sources and signal age per company', async () => {
    const { ws } = await sampleWorkspace();
    const rows = buildRadarRows(ws);
    const brightwater = row(rows, 'Brightwater Labs');
    expect(brightwater.activeRoles).toBe(4);
    // Two sample datasets both list Brightwater: one company, two sources.
    expect(brightwater.sourceIds).toHaveLength(2);
    expect(brightwater.sourceLabels.every((label) => label.startsWith('csv · SAMPLE-'))).toBe(true);
    expect(brightwater.locations).toEqual(['Austin, TX', 'Remote - US']);
    expect(roleMixText(brightwater.roleMix)).toBe('2 remote · 2 hybrid');
    expect(brightwater.signalAgeDays).toBe(0);
    expect(signalText(brightwater)).toBe('Last seen today');
  });

  it('flags shortlisted companies', async () => {
    const { source } = await sampleWorkspace();
    let ws = await source.load();
    const id = ws.analysis.companies[0]?.company_id ?? '';
    await source.setShortlisted(id, true);
    ws = await source.load();
    const rows = buildRadarRows(ws);
    expect(rows.filter((r) => r.shortlisted).map((r) => r.companyId)).toEqual([id]);
  });

  it('keeps the engine order (ranked first, then unscored)', async () => {
    const { ws } = await sampleWorkspace();
    const rows = buildRadarRows(ws);
    expect(rows.map((r) => r.companyId)).toEqual(ws.analysis.companies.map((c) => c.company_id));
  });
});

describe('filterRows', () => {
  it('matches company names, aliases, role titles and locations; ignores punctuation and case', async () => {
    const { ws } = await sampleWorkspace();
    const rows = buildRadarRows(ws);
    const names = (text: string) =>
      filterRows(rows, { ...DEFAULT_FILTERS, text })
        .map((r) => r.name)
        .sort();
    expect(names('BRIGHTWATER')).toEqual(['Brightwater Labs']);
    expect(names('brightwater labs, inc')).toEqual(['Brightwater Labs']);
    expect(names('machine learning')).toContain('Brightwater Labs');
    expect(names('montreal')).toEqual(['Ashgrove Games']);
    expect(names('zzzz')).toEqual([]);
  });

  it('treats several words as AND', async () => {
    const { ws } = await sampleWorkspace();
    const rows = buildRadarRows(ws);
    const hit = filterRows(rows, { ...DEFAULT_FILTERS, text: 'robotics denver' });
    // The typo spelling is still a separate company until the user merges the two.
    expect(hit.map((r) => r.name).sort()).toEqual(['Cedar Point Robotic', 'Cedar Point Robotics']);
    expect(filterRows(rows, { ...DEFAULT_FILTERS, text: 'robotics montreal' })).toEqual([]);
  });

  it('filters by work mode, source, minimum score and shortlist', async () => {
    const { source } = await sampleWorkspace();
    let ws = await source.load();
    const rows = buildRadarRows(ws);
    const remote = filterRows(rows, { ...DEFAULT_FILTERS, work_mode: 'remote' });
    expect(remote.length).toBeGreaterThan(0);
    expect(remote.every((r) => r.roleMix.some((m) => m.mode === 'remote'))).toBe(true);

    const onlyB = filterRows(rows, {
      ...DEFAULT_FILTERS,
      source: 'csv:SAMPLE-B Job feed',
    });
    expect(onlyB.every((r) => r.sourceIds.includes('csv:SAMPLE-B Job feed'))).toBe(true);
    expect(onlyB.length).toBeLessThan(rows.length);

    const scored = rows.filter((r) => r.score !== null);
    const best = Math.max(...scored.map((r) => r.score ?? 0));
    const top = filterRows(rows, { ...DEFAULT_FILTERS, min_score: best / 10 });
    expect(top.length).toBeGreaterThan(0);
    expect(top.every((r) => (r.score ?? -1) >= best)).toBe(true);

    const id = rows[0]?.companyId ?? '';
    await source.setShortlisted(id, true);
    ws = await source.load();
    const listed = filterRows(buildRadarRows(ws), { ...DEFAULT_FILTERS, shortlisted_only: true });
    expect(listed.map((r) => r.companyId)).toEqual([id]);
  });

  it('never lets an unscored company pass a minimum score', () => {
    const ws = workspaceFrom({
      as_of: NOW,
      snapshots: [
        {
          snapshot_id: 's1',
          source_kind: 'manual',
          source_ref: 'manual',
          observed_at: '2026-10-01T00:00:00Z',
          mode: 'additive',
          postings: [{ company_name: 'Acme', title: 'Engineer' }],
        },
      ],
    });
    const rows = buildRadarRows(ws);
    expect(filterRows(rows, { ...DEFAULT_FILTERS, min_score: 0 })).toHaveLength(1);
  });

  it('knows when filters are at their defaults', () => {
    expect(filtersAreDefault(DEFAULT_FILTERS)).toBe(true);
    expect(filtersAreDefault({ ...DEFAULT_FILTERS, text: '  ' })).toBe(true);
    expect(filtersAreDefault({ ...DEFAULT_FILTERS, min_score: 0 })).toBe(false);
  });
});

describe('sortRows', () => {
  it('sorts by score descending with unscored companies last in both directions', async () => {
    const { ws } = await sampleWorkspace();
    const rows = buildRadarRows(ws);
    for (const direction of ['asc', 'desc'] as const) {
      const sorted = sortRows(rows, { key: 'score', direction });
      const scores = sorted.map((r) => r.score);
      const firstNull = scores.indexOf(null);
      if (firstNull >= 0) expect(scores.slice(firstNull).every((s) => s === null)).toBe(true);
      const numeric = scores.filter((s): s is number => s !== null);
      const expected = [...numeric].sort((a, b) => (direction === 'asc' ? a - b : b - a));
      expect(numeric).toEqual(expected);
    }
  });

  it('sorts by name case-insensitively and breaks ties by name', async () => {
    const { ws } = await sampleWorkspace();
    const rows = buildRadarRows(ws);
    const sorted = sortRows(rows, { key: 'name', direction: 'asc' });
    const names = sorted.map((r) => r.name.toLowerCase());
    expect(names).toEqual([...names].sort());
    const byRoles = sortRows(rows, { key: 'active_roles', direction: 'desc' });
    for (let i = 1; i < byRoles.length; i += 1) {
      const prev = byRoles[i - 1];
      const cur = byRoles[i];
      if (prev === undefined || cur === undefined) continue;
      expect(prev.activeRoles).toBeGreaterThanOrEqual(cur.activeRoles);
      if (prev.activeRoles === cur.activeRoles) {
        expect(prev.name.toLowerCase() <= cur.name.toLowerCase()).toBe(true);
      }
    }
  });

  it('does not mutate its input', async () => {
    const { ws } = await sampleWorkspace();
    const rows = buildRadarRows(ws);
    const before = rows.map((r) => r.companyId);
    sortRows(rows, { key: 'name', direction: 'desc' });
    expect(rows.map((r) => r.companyId)).toEqual(before);
  });

  it('radarView composes filter then sort', async () => {
    const { ws } = await sampleWorkspace();
    const { all, rows } = radarView(
      ws,
      { ...DEFAULT_FILTERS, work_mode: 'onsite' },
      { key: 'name', direction: 'asc' },
    );
    expect(rows.length).toBeLessThan(all.length);
    expect(rows.map((r) => r.name.toLowerCase())).toEqual(
      rows.map((r) => r.name.toLowerCase()).sort(),
    );
  });

  it('flips direction on the same column and picks a natural order for a new one', () => {
    expect(nextSort(DEFAULT_SORT, 'rank')).toEqual({ key: 'rank', direction: 'desc' });
    expect(nextSort(DEFAULT_SORT, 'score')).toEqual({ key: 'score', direction: 'desc' });
    expect(nextSort(DEFAULT_SORT, 'name')).toEqual({ key: 'name', direction: 'asc' });
    expect(nextSort({ key: 'score', direction: 'desc' }, 'score')).toEqual({
      key: 'score',
      direction: 'asc',
    });
  });

  it('reports aria-sort for exactly one column', () => {
    const sort = { key: 'score', direction: 'desc' } as const;
    expect(ariaSortFor(sort, 'score')).toBe('descending');
    expect(ariaSortFor({ key: 'score', direction: 'asc' }, 'score')).toBe('ascending');
    expect(ariaSortFor(sort, 'name')).toBe('none');
  });
});

describe('saved views', () => {
  it('drops a source filter whose dataset no longer exists, and says so', async () => {
    const { source } = await sampleWorkspace();
    await source.removeDataset('csv:SAMPLE-B Job feed');
    const ws = await source.load();
    const result = reconcileFilters(
      { ...DEFAULT_FILTERS, source: 'csv:SAMPLE-B Job feed', text: 'labs' },
      ws.datasets,
    );
    expect(result.filters.source).toBe('any');
    expect(result.filters.text).toBe('labs');
    expect(result.dropped).toHaveLength(1);
    const kept = reconcileFilters(
      { ...DEFAULT_FILTERS, source: 'csv:SAMPLE-A Board export' },
      ws.datasets,
    );
    expect(kept.dropped).toEqual([]);
  });

  it('recognises when the current state equals a saved view', () => {
    const view = {
      id: 'v1',
      name: 'Remote',
      filters: { ...DEFAULT_FILTERS, work_mode: 'remote' as const },
      sort: { key: 'score' as const, direction: 'desc' as const },
      created_at: NOW,
    };
    expect(viewMatches(view, view.filters, view.sort)).toBe(true);
    expect(viewMatches(view, { ...view.filters, text: 'x' }, view.sort)).toBe(false);
    expect(viewMatches(view, view.filters, DEFAULT_SORT)).toBe(false);
  });
});

// ---------------------------------------------------------------------------------------------
// Score breakdown
// ---------------------------------------------------------------------------------------------

const FULL_HISTORY: SnapshotInput[] = [
  {
    snapshot_id: 's1',
    source_kind: 'greenhouse',
    source_ref: 'acme',
    observed_at: '2026-09-01T08:00:00Z',
    mode: 'full',
    postings: [
      {
        company_name: 'Acme',
        title: 'Software Engineer',
        source_posting_id: '1',
        posted_at: '2026-07-01',
      },
      {
        company_name: 'Acme',
        title: 'Data Engineer',
        source_posting_id: '2',
        posted_at: '2026-09-01',
      },
      {
        company_name: 'Acme',
        title: 'Office Manager',
        source_posting_id: '3',
        posted_at: '2026-08-20',
      },
    ],
  },
  {
    snapshot_id: 's2',
    source_kind: 'greenhouse',
    source_ref: 'acme',
    observed_at: '2026-09-25T08:00:00Z',
    mode: 'full',
    postings: [
      {
        company_name: 'Acme',
        title: 'Software Engineer',
        source_posting_id: '1',
        posted_at: '2026-07-01',
      },
      {
        company_name: 'Acme',
        title: 'Office Manager',
        source_posting_id: '3',
        posted_at: '2026-08-20',
      },
      {
        company_name: 'Acme',
        title: 'Platform Engineer',
        source_posting_id: '4',
        posted_at: '2026-09-24',
      },
    ],
  },
];

function acme(profile: Profile = { include_keywords: ['engineer'], exclude_keywords: [] }) {
  const ws = workspaceFrom({ as_of: NOW, profile, snapshots: FULL_HISTORY });
  const company = ws.analysis.companies[0];
  if (company === undefined) throw new Error('no company');
  return { ws, company };
}

describe('score breakdown', () => {
  it('turns inputs into human-readable calculations', () => {
    const { ws, company } = acme();
    const views = componentViews(company, ws.profile);
    const by = Object.fromEntries(views.map((v) => [v.key, v]));
    // Active now: Software Engineer, Office Manager, Platform Engineer; relevant: 2.
    expect(by.role_relevance?.calculation).toBe('2 of 3 active roles match your keywords');
    expect(by.volume?.calculation).toBe('2 active roles in scope (matching your keywords)');
    // Platform Engineer was added and Data Engineer dropped out of the second full list.
    expect(by.change?.calculation).toBe(
      '1 added or listed again and 1 no longer listed in the last 30 days (net 0, counting roles that match your keywords); the full-list history spans 24 days',
    );
    expect(by.urgency?.calculation).toBe('1 of 2 dated roles have been listed for 45 or more days');
    expect(by.source_confidence?.calculation).toBe(
      '2 roles in scope; 0 listed by two or more different sources',
    );
    expect(by.freshness?.calculation).toBe('Newest active role was last seen 18 days ago');
  });

  it('keeps weights, fixed order and the urgency honesty label', () => {
    const { ws, company } = acme();
    const views = componentViews(company, ws.profile);
    expect(views.map((v) => v.key)).toEqual([
      'role_relevance',
      'volume',
      'change',
      'urgency',
      'source_confidence',
      'freshness',
    ]);
    expect(views.map((v) => v.weight)).toEqual([30, 20, 15, 10, 15, 10]);
    const urgency = views.find((v) => v.key === 'urgency');
    expect(urgency?.title).toBe(COPY.urgencyLabel);
    expect(urgency?.caution).toBe(true);
    expect(views.filter((v) => v.caution)).toHaveLength(1);
  });

  it('lists missing components with a plain-language reason, never as zero', () => {
    const { ws, company } = acme(NO_PROFILE);
    const views = componentViews(company, ws.profile);
    const missing = missingInformation(views);
    const relevance = missing.find((v) => v.key === 'role_relevance');
    expect(relevance?.valueText).toBe('Not measured');
    expect(relevance?.missing?.text).toBe('No role keywords are configured.');
    expect(relevance?.calculation).toBe('No role keywords are configured.');
    expect(relevance?.value).toBeNull();
    // Volume with no keywords counts every active role and says why.
    const volume = views.find((v) => v.key === 'volume');
    expect(volume?.calculation).toBe(
      '3 active roles in scope (no keywords are set, so every active role counts)',
    );
    // Role relevance (weight 30) is the only unmeasured component: 70 of 100 weight points.
    expect(company.coverage).toBe(70);
    expect(coverageText(company)).toBe('70% (5 of 6 components measured)');
  });

  it('explains insufficient history for CSV-only data', () => {
    const ws = workspaceFrom({
      as_of: NOW,
      profile: { include_keywords: ['engineer'], exclude_keywords: [] },
      snapshots: [
        {
          snapshot_id: 'c1',
          source_kind: 'csv',
          source_ref: 'list',
          observed_at: '2026-10-01T00:00:00Z',
          mode: 'additive',
          postings: [{ company_name: 'Acme', title: 'Engineer', posted_at: '2026-10-01' }],
        },
      ],
    });
    const company = ws.analysis.companies[0];
    if (company === undefined) throw new Error('no company');
    const change = componentViews(company, ws.profile).find((v) => v.key === 'change');
    expect(change?.value).toBeNull();
    expect(change?.missing?.text).toBe('Not enough history to measure change.');
    expect(change?.missing?.help).toContain('14 or more days');
  });

  it('describes a company with no active roles as missing everything', () => {
    const ws = workspaceFrom({
      as_of: NOW,
      profile: { include_keywords: ['engineer'], exclude_keywords: [] },
      snapshots: [
        {
          snapshot_id: 's1',
          source_kind: 'greenhouse',
          source_ref: 'acme',
          observed_at: '2026-09-01T08:00:00Z',
          mode: 'full',
          postings: [{ company_name: 'Acme', title: 'Engineer', source_posting_id: '1' }],
        },
        {
          snapshot_id: 's2',
          source_kind: 'greenhouse',
          source_ref: 'acme',
          observed_at: '2026-09-20T08:00:00Z',
          mode: 'full',
          postings: [],
        },
      ],
    });
    const company = ws.analysis.companies[0];
    if (company === undefined) throw new Error('no company');
    expect(company.score).toBeNull();
    const views = componentViews(company, ws.profile);
    expect(views.every((v) => v.value === null)).toBe(true);
    expect(views.every((v) => v.missing?.text === 'No active roles in the loaded data.')).toBe(
      true,
    );
    const direct = describeInputs(company.components[0]!, { keywordsConfigured: true });
    expect(direct).toBe('No active roles in the loaded data.');
  });

  it('handles singular wording', () => {
    const ws = workspaceFrom({
      as_of: NOW,
      profile: { include_keywords: ['engineer'], exclude_keywords: [] },
      snapshots: [
        {
          snapshot_id: 's1',
          source_kind: 'manual',
          source_ref: 'manual',
          observed_at: '2026-10-12T00:00:00Z',
          mode: 'additive',
          postings: [{ company_name: 'Solo', title: 'Engineer', posted_at: '2026-01-01' }],
        },
      ],
    });
    const company = ws.analysis.companies[0];
    if (company === undefined) throw new Error('no company');
    const by = Object.fromEntries(
      componentViews(company, ws.profile).map((v) => [v.key, v.calculation]),
    );
    expect(by.role_relevance).toBe('1 of 1 active role matches your keywords');
    expect(by.volume).toBe('1 active role in scope (matching your keywords)');
    expect(by.urgency).toBe('1 of 1 dated role has been listed for 45 or more days');
    expect(by.freshness).toBe('Newest active role was last seen 1 day ago');
  });
});

// ---------------------------------------------------------------------------------------------
// Company detail
// ---------------------------------------------------------------------------------------------

describe('buildCompanyDetail', () => {
  it('collects roles, newest-first events, provenance and the breakdown', () => {
    const { ws, company } = acme();
    const detail = buildCompanyDetail(ws, company.company_id);
    expect(detail).not.toBeNull();
    if (detail === null) return;
    expect(detail.roles.map((r) => r.role.title).sort()).toEqual([
      'Data Engineer',
      'Office Manager',
      'Platform Engineer',
      'Software Engineer',
    ]);
    const times = detail.events.map((e) => e.at);
    expect(times).toEqual([...times].sort().reverse());
    expect(detail.events.map((e) => e.type)).toContain('removed');
    expect(detail.provenance).toHaveLength(4);
    expect(detail.provenance.every((p) => p.sourceLabel === 'greenhouse · acme')).toBe(true);
    expect(detail.components).toHaveLength(6);
    expect(detail.missing).toEqual([]);
    expect(detail.shortlist).toBeNull();
    expect(detail.signalAgeDays).toBe(18);
  });

  it('returns null for an unknown company', () => {
    const { ws } = acme();
    expect(buildCompanyDetail(ws, 'c_000000000000')).toBeNull();
  });

  it('marks provenance rows that come from synthetic datasets', async () => {
    const { ws } = await sampleWorkspace();
    const company = ws.analysis.companies.find((c) => c.name === 'Brightwater Labs');
    const detail = buildCompanyDetail(
      ws,
      company?.company_id ?? '',
      new Set(ws.datasets.filter((d) => d.synthetic).map((d) => d.id)),
    );
    expect(detail?.provenance.length).toBeGreaterThan(0);
    expect(detail?.provenance.every((p) => p.synthetic)).toBe(true);
  });

  it('finds pending merge candidates that involve the company', async () => {
    const { ws } = await sampleWorkspace();
    const north = ws.analysis.companies.find((c) => c.name === 'North Harbor Analytics');
    const detail = buildCompanyDetail(ws, north?.company_id ?? '');
    expect(detail?.candidates.some((c) => c.reason === 'spacing_variant')).toBe(true);
    const brightwater = ws.analysis.companies.find((c) => c.name === 'Brightwater Labs');
    expect(buildCompanyDetail(ws, brightwater?.company_id ?? '')?.candidates).toEqual([]);
  });
});

describe('merge review and files', () => {
  it('names the companies in a decision, falling back to the key', async () => {
    const source = new LocalSource({ storage: new MemoryStorage(), clock: makeClock() });
    await source.importCsv('one', csv('DoorDash,Engineer,,,,,', 'Door Dash,Designer,,,,,'));
    let ws = await source.load();
    const candidate = ws.analysis.merge_candidates[0];
    if (candidate === undefined) throw new Error('expected a candidate');
    await source.decide(candidate.a_key, candidate.b_key, 'merge');
    ws = await source.load();
    const rows = decisionRows(ws);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.kind).toBe('merge');
    expect(rows[0]?.aName).toBeTruthy();
    expect(rows[0]?.bName).toBeTruthy();
    expect(ws.analysis.merge_candidates).toEqual([]);
  });

  it('builds safe export file names', () => {
    expect(exportFileName('Shortlist', '2026-10-13T12:00:00Z')).toBe(
      'recruit-radar-shortlist-2026-10-13.csv',
    );
    expect(exportFileName('csv: SAMPLE-A Board export', NOW)).toBe(
      'recruit-radar-csv-sample-a-board-export-2026-10-13.csv',
    );
    expect(exportFileName('???', NOW)).toBe('recruit-radar-export-2026-10-13.csv');
  });
});
