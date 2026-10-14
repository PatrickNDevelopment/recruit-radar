import { describe, expect, it } from 'vitest';
import { SourceError } from '../src/data/errors';
import {
  LocalSource,
  MAX_POSTINGS,
  WORKSPACE_BACKUP_KEY,
  WORKSPACE_KEY,
} from '../src/data/localSource';
import { MemoryStorage } from '../src/data/storage';
import { BlockedStorage, csv, FORM_DEFAULTS, makeClock, NOW, QuotaStorage } from './data-helpers';

function setup() {
  const storage = new MemoryStorage();
  const clock = makeClock();
  const source = new LocalSource({ storage, clock });
  return { storage, clock, source };
}

const manual = (company: string, title: string, extra: Record<string, string> = {}) => ({
  ...FORM_DEFAULTS,
  company_name: company,
  title,
  ...extra,
});

async function failure(promise: Promise<unknown>): Promise<SourceError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof SourceError) return error;
    throw error;
  }
  throw new Error('expected a SourceError but the call succeeded');
}

describe('LocalSource: basics and persistence', () => {
  it('starts empty, persistent, with no notices', async () => {
    const { source } = setup();
    const ws = await source.load();
    expect(ws.mode).toBe('local');
    expect(ws.analysis.companies).toEqual([]);
    expect(ws.datasets).toEqual([]);
    expect(ws.notices).toEqual([]);
    expect(ws.has_sample_data).toBe(false);
    expect(source.persistent).toBe(true);
  });

  it('keeps a manual posting across a fresh instance on the same storage', async () => {
    const { storage, clock, source } = setup();
    const result = await source.addManualPosting(
      manual('Acme Inc.', 'Data Engineer', { location: 'Remote', work_mode: 'remote' }),
    );
    expect(result).toEqual({ ok: true });
    const reopened = new LocalSource({ storage, clock });
    const ws = await reopened.load();
    expect(ws.analysis.companies.map((c) => c.name)).toEqual(['Acme Inc.']);
    expect(ws.analysis.roles[0]?.title).toBe('Data Engineer');
    expect(ws.datasets).toMatchObject([
      { source_kind: 'manual', source_ref: 'manual', postings: 1, snapshots: 1, active_roles: 1 },
    ]);
  });

  it('rejects an invalid manual posting field by field and stores nothing', async () => {
    const { storage, source } = setup();
    const result = await source.addManualPosting(
      manual('', 'Engineer', { url: 'javascript:alert(1)', work_mode: 'sometimes' }),
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    const fields = result.problems.map((p) => p.field).sort();
    expect(fields).toEqual(['company_name', 'url', 'work_mode']);
    expect(storage.getItem(WORKSPACE_KEY)).toBeNull();
  });

  it('saves keywords and applies them to the analysis', async () => {
    const { source } = setup();
    await source.addManualPosting(manual('Acme', 'Data Engineer'));
    await source.addManualPosting(manual('Acme', 'Office Manager'));
    await source.setProfile({ include_keywords: ['engineer'], exclude_keywords: [] });
    const ws = await source.load();
    expect(ws.profile.include_keywords).toEqual(['engineer']);
    expect(ws.analysis.companies[0]?.relevant_roles).toBe(1);
  });

  it('refuses keywords the engine rejects without changing anything', async () => {
    const { source } = setup();
    const error = await failure(
      source.setProfile({ include_keywords: ['x'.repeat(61)], exclude_keywords: [] }),
    );
    expect(error.kind).toBe('invalid_input');
    expect((await source.load()).profile.include_keywords).toEqual([]);
  });
});

describe('LocalSource: CSV import', () => {
  it('stores valid rows, reports rejected rows with values, and keeps line numbers', async () => {
    const { source } = setup();
    const report = await source.importCsv(
      'Board A',
      csv(
        'Acme,Engineer,Austin,remote,Eng,https://acme.example/1,2026-09-01',
        'Acme,,Austin,remote,Eng,https://acme.example/2,2026-09-02',
        'Beta,Analyst,,sometimes,,ftp://beta.example/3,2026-13-40',
      ),
    );
    expect(report.ok).toBe(true);
    expect(report.accepted).toBe(1);
    expect(report.rejected).toBe(2);
    expect(report.errors.map((e) => [e.line, e.field])).toEqual([
      [3, 'title'],
      [4, 'work_mode'],
      [4, 'url'],
      [4, 'posted_at'],
    ]);
    expect(report.rejected_rows.map((r) => r.line)).toEqual([3, 4]);
    expect(report.rejected_rows[0]?.values.company_name).toBe('Acme');
    const ws = await source.load();
    expect(ws.analysis.companies.map((c) => c.name)).toEqual(['Acme']);
  });

  it('stores nothing when the file is rejected as a whole', async () => {
    const { storage, source } = setup();
    const report = await source.importCsv('Board A', 'company_name,title\r\n"Acme,Engineer\r\n');
    expect(report.ok).toBe(false);
    expect(report.file_error?.code).toBe('unterminated_quote');
    expect(storage.getItem(WORKSPACE_KEY)).toBeNull();
  });

  it('requires a dataset label', async () => {
    const { source } = setup();
    const report = await source.importCsv('   ', csv('Acme,Engineer,,,,,'));
    expect(report.ok).toBe(false);
    expect(report.file_error?.code).toBe('invalid_dataset_label');
  });

  it('collapses duplicates across two datasets into one company and one corroborated role', async () => {
    const { source } = setup();
    await source.importCsv('Board A', csv('Acme Inc.,Data Engineer,Austin TX,hybrid,,,'));
    await source.importCsv('Feed B', csv('ACME,Data Engineer,Austin  TX,hybrid,,,'));
    const ws = await source.load();
    expect(ws.analysis.companies).toHaveLength(1);
    expect(ws.analysis.roles).toHaveLength(1);
    expect(ws.analysis.roles[0]?.observations.map((o) => o.source_ref)).toEqual([
      'Board A',
      'Feed B',
    ]);
    expect(ws.datasets.map((d) => d.source_ref)).toEqual(['Board A', 'Feed B']);
  });

  it('refuses an import that would exceed the 5,000-posting workspace cap, storing nothing', async () => {
    const { source } = setup();
    const big = (prefix: string, n: number) =>
      csv(...Array.from({ length: n }, (_, i) => `${prefix}${i},Engineer ${i},,,,,`));
    const first = await source.importCsv('Big one', big('A', 3000));
    expect(first.accepted).toBe(3000);
    const error = await failure(source.importCsv('Big two', big('B', 2500)));
    expect(error.kind).toBe('limit');
    expect(error.code).toBe('too_many_postings');
    const ws = await source.load();
    expect(ws.datasets).toHaveLength(1);
    expect(MAX_POSTINGS).toBe(5000);
  });

  it('flags snapshots dated after the analysis time as ignored', async () => {
    const { source } = setup();
    const text = [
      'company_name,title,observed_at',
      'Acme,Engineer,2026-10-13T12:00:00Z',
      'Acme,Designer,2027-01-01T00:00:00Z',
    ].join('\r\n');
    const report = await source.importCsv('Future', text);
    expect(report.accepted).toBe(2);
    const ws = await source.load();
    expect(ws.datasets[0]).toMatchObject({ snapshots: 2, ignored_snapshots: 1, active_roles: 1 });
  });

  it('exports stored postings in the import format, and they import back unchanged', async () => {
    const { source } = setup();
    await source.importCsv(
      'Board A',
      csv(
        '"Acme, Inc.",Senior Engineer (Remote),"Austin, TX",remote,Eng,https://acme.example/1,2026-09-01',
        '=HYPERLINK(),Analyst,,,,,',
      ),
    );
    const exported = await source.exportPostingsCsv('csv:Board A');
    const other = setup().source;
    const report = await other.importCsv('Copy', exported);
    expect(report.accepted).toBe(2);
    expect(report.rejected).toBe(0);
    const names = (await other.load()).analysis.companies.map((c) => c.name).sort();
    expect(names).toEqual(['=HYPERLINK()', 'Acme, Inc.']);
  });
});

describe('LocalSource: corruption, versions, storage failures', () => {
  it('backs up unreadable JSON, starts empty, keeps working, and reports it', async () => {
    const { storage, clock } = setup();
    storage.setItem(WORKSPACE_KEY, '{"schema_version":1,"snapsh');
    const source = new LocalSource({ storage, clock });
    const ws = await source.load();
    expect(ws.analysis.companies).toEqual([]);
    expect(ws.notices.map((n) => n.kind)).toEqual(['corrupt_recovered']);
    expect(ws.notices[0]?.message).toContain(WORKSPACE_BACKUP_KEY);
    expect(storage.getItem(WORKSPACE_BACKUP_KEY)).toBe('{"schema_version":1,"snapsh');
    expect(source.readCorruptBackup()).toBe('{"schema_version":1,"snapsh');

    expect(await source.addManualPosting(manual('Acme', 'Engineer'))).toEqual({ ok: true });
    const after = await source.load();
    expect(after.analysis.companies).toHaveLength(1);
    // The original unreadable text is still preserved.
    expect(storage.getItem(WORKSPACE_BACKUP_KEY)).toBe('{"schema_version":1,"snapsh');
  });

  it('treats valid JSON of the wrong shape as unreadable', async () => {
    const { storage, clock } = setup();
    storage.setItem(WORKSPACE_KEY, JSON.stringify({ schema_version: 1, snapshots: 'nope' }));
    const ws = await new LocalSource({ storage, clock }).load();
    expect(ws.notices[0]?.kind).toBe('corrupt_recovered');
    expect(storage.getItem(WORKSPACE_BACKUP_KEY)).toContain('"snapshots":"nope"');
  });

  it('treats a stored posting the engine rejects as unreadable and keeps a backup', async () => {
    const { storage, clock } = setup();
    const bad = {
      schema_version: 1,
      revision: 3,
      saved_at: NOW,
      seq: 1,
      profile: { include_keywords: [], exclude_keywords: [] },
      decisions: [],
      shortlist: [],
      snapshots: [
        {
          snapshot_id: 's1',
          source_kind: 'csv',
          source_ref: 'X',
          observed_at: 'yesterday',
          mode: 'additive',
          postings: [],
        },
      ],
    };
    storage.setItem(WORKSPACE_KEY, JSON.stringify(bad));
    const source = new LocalSource({ storage, clock });
    const ws = await source.load();
    expect(ws.notices[0]?.kind).toBe('corrupt_recovered');
    expect(storage.getItem(WORKSPACE_BACKUP_KEY)).toBe(JSON.stringify(bad));
    expect(await source.addManualPosting(manual('Acme', 'Engineer'))).toEqual({ ok: true });
  });

  it('never overwrites data written by a newer schema', async () => {
    const { storage, clock } = setup();
    const newer = JSON.stringify({ schema_version: 99, future: { anything: true } });
    storage.setItem(WORKSPACE_KEY, newer);
    const source = new LocalSource({ storage, clock });
    const ws = await source.load();
    expect(ws.notices.map((n) => n.kind)).toEqual(['newer_schema']);
    expect(ws.notices[0]?.message).toContain('99');

    const error = await failure(source.importCsv('A', csv('Acme,Engineer,,,,,')));
    expect(error.kind).toBe('read_only');
    const profileError = await failure(
      source.setProfile({ include_keywords: ['x'], exclude_keywords: [] }),
    );
    expect(profileError.kind).toBe('read_only');
    expect((await failure(source.loadSample())).kind).toBe('read_only');
    expect(storage.getItem(WORKSPACE_KEY)).toBe(newer);

    // The user can still choose to erase.
    await source.eraseAll();
    expect(storage.getItem(WORKSPACE_KEY)).toBeNull();
    expect(await source.addManualPosting(manual('Acme', 'Engineer'))).toEqual({ ok: true });
  });

  it('degrades to memory-only when there is no storage, and says so', async () => {
    const source = new LocalSource({ storage: null, clock: makeClock() });
    expect(await source.addManualPosting(manual('Acme', 'Engineer'))).toEqual({ ok: true });
    const ws = await source.load();
    expect(ws.analysis.companies).toHaveLength(1);
    expect(ws.notices.map((n) => n.kind)).toEqual(['storage_unavailable']);
    expect(source.persistent).toBe(false);
  });

  it('degrades to memory-only when every storage call throws', async () => {
    const source = new LocalSource({ storage: new BlockedStorage(), clock: makeClock() });
    expect(await source.addManualPosting(manual('Acme', 'Engineer'))).toEqual({ ok: true });
    const ws = await source.load();
    expect(ws.analysis.companies).toHaveLength(1);
    expect(ws.notices.some((n) => n.kind === 'storage_unavailable')).toBe(true);
  });

  it('rejects a write when the quota is exhausted and leaves earlier data intact', async () => {
    const storage = new QuotaStorage();
    const source = new LocalSource({ storage, clock: makeClock() });
    await source.addManualPosting(manual('Acme', 'Engineer'));
    storage.armed = true;
    const error = await failure(source.importCsv('B', csv('Beta,Analyst,,,,,')));
    expect(error.kind).toBe('storage_full');
    storage.armed = false;
    const ws = await source.load();
    expect(ws.analysis.companies.map((c) => c.name)).toEqual(['Acme']);
  });
});

describe('LocalSource: two tabs', () => {
  it('does not lose another tab’s write (every mutation re-reads storage)', async () => {
    const storage = new MemoryStorage();
    const clock = makeClock();
    const tabA = new LocalSource({ storage, clock });
    const tabB = new LocalSource({ storage, clock });
    await tabA.load();
    await tabB.load();
    await tabA.addManualPosting(manual('Acme', 'Engineer'));
    clock.advance(5);
    // tabB never reloaded, yet its write must keep tabA's posting.
    await tabB.addManualPosting(manual('Beta', 'Analyst'));
    const ws = await tabA.load();
    expect(ws.analysis.companies.map((c) => c.name).sort()).toEqual(['Acme', 'Beta']);
  });

  it('notifies on storage events for its key (and on clear), not for other keys', () => {
    const { source } = setup();
    const target = new EventTarget();
    let calls = 0;
    const stop = source.watchExternalChanges(target, () => {
      calls += 1;
    });
    const fire = (key: string | null) => {
      const event = new Event('storage');
      Object.assign(event, { key });
      target.dispatchEvent(event);
    };
    fire('something-else');
    expect(calls).toBe(0);
    fire(WORKSPACE_KEY);
    fire(null);
    expect(calls).toBe(2);
    stop();
    fire(WORKSPACE_KEY);
    expect(calls).toBe(2);
  });
});

describe('LocalSource: decisions and shortlist', () => {
  async function twoSpellings() {
    const ctx = setup();
    await ctx.source.importCsv(
      'Board A',
      csv('DoorDash,Engineer,,,,,', 'Zeta Works,Designer,,,,,', 'Door Dash,Analyst,,,,,'),
    );
    return ctx;
  }

  it('offers a candidate, merges on accept, and restores on undo', async () => {
    const { source } = await twoSpellings();
    let ws = await source.load();
    expect(ws.analysis.companies).toHaveLength(3);
    const candidate = ws.analysis.merge_candidates[0];
    expect(candidate).toMatchObject({
      reason: 'spacing_variant',
      a_key: 'door dash',
      b_key: 'doordash',
    });

    await source.decide('door dash', 'doordash', 'merge');
    ws = await source.load();
    expect(ws.analysis.companies).toHaveLength(2);
    expect(ws.analysis.merge_candidates).toEqual([]);
    expect(ws.decisions).toMatchObject([
      { a_key: 'door dash', b_key: 'doordash', decision: 'merge' },
    ]);

    const id = ws.decisions[0]?.id ?? '';
    await source.undoDecision(id);
    ws = await source.load();
    expect(ws.analysis.companies).toHaveLength(3);
    expect(ws.analysis.merge_candidates).toHaveLength(1);
  });

  it('suppresses a rejected candidate and lets the user undo that too', async () => {
    const { source } = await twoSpellings();
    await source.decide('door dash', 'doordash', 'not_same');
    let ws = await source.load();
    expect(ws.analysis.merge_candidates).toEqual([]);
    expect(ws.analysis.companies).toHaveLength(3);
    await source.undoDecision(ws.decisions[0]?.id ?? '');
    ws = await source.load();
    expect(ws.analysis.merge_candidates).toHaveLength(1);
  });

  it('normalises key order and refuses a self-merge', async () => {
    const { source } = await twoSpellings();
    await source.decide('doordash', 'door dash', 'merge');
    expect((await source.load()).decisions[0]).toMatchObject({
      a_key: 'door dash',
      b_key: 'doordash',
    });
    expect((await failure(source.decide('x', 'x', 'merge'))).kind).toBe('invalid_input');
  });

  it('shortlists with a note, survives a merge and its undo, and unshortlists', async () => {
    const { source } = await twoSpellings();
    let ws = await source.load();
    const doordash = ws.analysis.companies.find((c) => c.key === 'doordash');
    expect(doordash).toBeDefined();
    await source.setShortlisted(doordash?.company_id ?? '', true, 'Looks active in data roles');
    ws = await source.load();
    expect(ws.shortlist).toMatchObject([{ name: 'DoorDash', note: 'Looks active in data roles' }]);

    await source.decide('door dash', 'doordash', 'merge');
    ws = await source.load();
    expect(ws.shortlist).toHaveLength(1);
    expect(ws.shortlist[0]?.note).toBe('Looks active in data roles');
    const merged = ws.analysis.companies.find((c) => c.company_id === ws.shortlist[0]?.company_id);
    expect(merged?.aliases).toEqual(['Door Dash', 'DoorDash']);

    await source.undoDecision(ws.decisions[0]?.id ?? '');
    ws = await source.load();
    expect(ws.shortlist).toHaveLength(1);
    expect(ws.shortlist[0]?.name).toBe('DoorDash');

    await source.setShortlisted(ws.shortlist[0]?.company_id ?? '', false);
    expect((await source.load()).shortlist).toEqual([]);
  });

  it('updates a note without changing added_at, and enforces the note limit', async () => {
    const { source, clock } = await twoSpellings();
    const id = (await source.load()).analysis.companies[0]?.company_id ?? '';
    await source.setShortlisted(id, true, 'first');
    const added = (await source.load()).shortlist[0]?.added_at;
    clock.advance(3600);
    await source.setShortlisted(id, true, 'second');
    const entry = (await source.load()).shortlist[0];
    expect(entry).toMatchObject({ note: 'second', added_at: added });
    const tooLong = await failure(source.setShortlisted(id, true, 'x'.repeat(2001)));
    expect(tooLong.kind).toBe('invalid_input');
  });

  it('rejects an unknown company', async () => {
    const { source } = await twoSpellings();
    const error = await failure(source.setShortlisted('c_000000000000', true));
    expect(error.kind).toBe('not_found');
    expect(error.code).toBe('unknown_company');
  });

  it('exports the shortlist as CSV with score, coverage and missing information', async () => {
    const { source } = await twoSpellings();
    await source.setProfile({ include_keywords: ['engineer'], exclude_keywords: [] });
    const ws = await source.load();
    const id = ws.analysis.companies.find((c) => c.key === 'doordash')?.company_id ?? '';
    await source.setShortlisted(id, true, 'call, "later"');
    const text = await source.exportShortlistCsv();
    const lines = text.replace(/^\uFEFF/u, '').split('\r\n');
    expect(lines[0]).toBe(
      'rank,company,score,coverage_percent,active_roles,relevant_roles,last_seen,strongest_evidence,missing_information,note,as_of',
    );
    expect(lines[1]).toContain('DoorDash');
    expect(lines[1]).toContain('"call, ""later"""');
    // CSV-only data has no full-list history, so "change" is reported as missing information.
    expect(lines[1]).toContain('Change in the last 30 days');
    expect(lines[1]).toContain(ws.analysis.as_of);
  });
});

describe('LocalSource: sample data', () => {
  it('loads two overlapping datasets, flags them, sets keywords only when none exist', async () => {
    const { source } = setup();
    const summary = await source.loadSample();
    expect(summary).toMatchObject({ datasets: 2, keywordsAdded: true });
    const ws = await source.load();
    expect(ws.has_sample_data).toBe(true);
    expect(ws.datasets.every((d) => d.synthetic)).toBe(true);
    expect(ws.datasets).toHaveLength(2);
    expect(ws.profile.include_keywords.length).toBeGreaterThan(0);
    // Overlap: some canonical roles are observed by both datasets.
    const corroborated = ws.analysis.roles.filter(
      (r) => new Set(r.observations.map((o) => o.source_ref)).size === 2,
    );
    expect(corroborated.length).toBeGreaterThanOrEqual(2);
    expect(ws.analysis.merge_candidates.map((c) => c.reason).sort()).toEqual([
      'near_typo',
      'spacing_variant',
      'token_overlap',
    ]);
  });

  it('keeps the user’s own keywords and refuses a second load', async () => {
    const { source } = setup();
    await source.setProfile({ include_keywords: ['designer'], exclude_keywords: [] });
    const summary = await source.loadSample();
    expect(summary.keywordsAdded).toBe(false);
    expect((await source.load()).profile.include_keywords).toEqual(['designer']);
    const again = await failure(source.loadSample());
    expect(again.code).toBe('sample_exists');
  });

  it('removes one dataset at a time and clears the sample banner when none is left', async () => {
    const { source } = setup();
    await source.loadSample();
    let ws = await source.load();
    const [first, second] = ws.datasets;
    await source.removeDataset(first?.id ?? '');
    ws = await source.load();
    expect(ws.datasets).toHaveLength(1);
    expect(ws.has_sample_data).toBe(true);
    await source.removeDataset(second?.id ?? '');
    ws = await source.load();
    expect(ws.datasets).toEqual([]);
    expect(ws.has_sample_data).toBe(false);
    expect((await failure(source.removeDataset('csv:nope'))).kind).toBe('not_found');
  });

  it('drops shortlist entries whose company disappears with a removed dataset', async () => {
    const { source } = setup();
    await source.loadSample();
    const ws = await source.load();
    const ashgrove = ws.analysis.companies.find((c) => c.name === 'Ashgrove Games');
    expect(ashgrove).toBeDefined();
    await source.setShortlisted(ashgrove?.company_id ?? '', true, 'note');
    const sampleB = ws.datasets.find((d) => d.source_ref.startsWith('SAMPLE-B'));
    await source.removeDataset(sampleB?.id ?? '');
    expect((await source.load()).shortlist).toEqual([]);
  });

  it('erases everything including the backup key', async () => {
    const { storage, source } = setup();
    await source.loadSample();
    storage.setItem(WORKSPACE_BACKUP_KEY, 'old');
    await source.eraseAll();
    expect(storage.getItem(WORKSPACE_KEY)).toBeNull();
    expect(storage.getItem(WORKSPACE_BACKUP_KEY)).toBeNull();
    expect((await source.load()).analysis.companies).toEqual([]);
  });
});
