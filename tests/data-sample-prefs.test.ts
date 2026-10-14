import { describe, expect, it } from 'vitest';
import { analyze, importCsv } from '../src/engine';
import { isSampleLabel, SAMPLE_LABEL_PREFIX } from '../src/data/derive';
import {
  defaultPrefs,
  MAX_SAVED_VIEWS,
  PREFS_BACKUP_KEY,
  PREFS_KEY,
  PrefsStore,
  removeView,
  upsertView,
} from '../src/data/prefs';
import { buildSampleDatasets, SAMPLE_LABEL_A, SAMPLE_LABEL_B } from '../src/data/sample';
import { MemoryStorage } from '../src/data/storage';
import { DEFAULT_FILTERS, DEFAULT_SORT } from '../src/data/types';
import { NOW } from './data-helpers';

describe('sample data', () => {
  const datasets = buildSampleDatasets(NOW);

  it('has two labelled synthetic datasets that import with no rejected rows', () => {
    expect(datasets.map((d) => d.label)).toEqual([SAMPLE_LABEL_A, SAMPLE_LABEL_B]);
    for (const dataset of datasets) {
      expect(isSampleLabel(dataset.label)).toBe(true);
      expect(dataset.label.startsWith(SAMPLE_LABEL_PREFIX)).toBe(true);
      const result = importCsv(dataset.csv, { dataset_label: dataset.label, imported_at: NOW });
      expect(result.ok).toBe(true);
      expect(result.rejected).toBe(0);
      expect(result.accepted).toBe(dataset.postings);
      expect(result.warnings).toEqual([]);
    }
  });

  it('is deterministic for a given time and relative to it', () => {
    expect(buildSampleDatasets(NOW)).toEqual(datasets);
    const later = buildSampleDatasets('2027-03-01T00:00:00Z');
    expect(later[0]?.csv).not.toBe(datasets[0]?.csv);
  });

  it('uses only invented names and reserved example URLs', () => {
    const text = datasets.map((d) => d.csv).join('\n');
    expect(text).toContain('Brightwater Labs');
    const urls = text.match(/https?:\/\/[^,\s"]+/gu) ?? [];
    expect(urls.length).toBeGreaterThan(10);
    for (const url of urls) expect(url.startsWith('https://careers.example.com/')).toBe(true);
  });

  it('overlaps: duplicates collapse and every merge-candidate reason appears', () => {
    const snapshots = datasets.flatMap((dataset, index) => {
      const result = importCsv(dataset.csv, {
        dataset_label: dataset.label,
        imported_at: NOW,
        snapshot_id_prefix: `s${index}`,
      });
      return result.snapshots;
    });
    const analysis = analyze({
      as_of: NOW,
      profile: { include_keywords: ['engineer'], exclude_keywords: ['intern'] },
      snapshots,
    });
    const postings = datasets.reduce((n, d) => n + d.postings, 0);
    expect(analysis.stats.postings_observed).toBe(postings);
    // Fewer canonical roles than postings proves duplicates were collapsed.
    expect(analysis.roles.length).toBeLessThan(postings);
    const brightwater = analysis.companies.find((c) => c.name === 'Brightwater Labs');
    expect(brightwater?.aliases).toEqual(['Brightwater Labs', 'Brightwater Labs, Inc.']);
    expect(analysis.merge_candidates.map((c) => c.reason).sort()).toEqual([
      'near_typo',
      'spacing_variant',
      'token_overlap',
    ]);
    // Some sample roles are old enough for the urgency signal to be computable.
    const tidewater = analysis.companies.find((c) => c.name === 'Tidewater Systems');
    const urgency = tidewater?.components.find((c) => c.key === 'urgency');
    expect(urgency?.value).not.toBeNull();
  });
});

describe('PrefsStore', () => {
  it('returns defaults, then persists and reloads changes', () => {
    const storage = new MemoryStorage();
    const store = new PrefsStore(storage);
    expect(store.load().prefs).toEqual(defaultPrefs());
    store.save({ backend_url: 'http://localhost:9000', mode_preference: 'connected' });
    const reloaded = new PrefsStore(storage).load();
    expect(reloaded.prefs).toMatchObject({
      backend_url: 'http://localhost:9000',
      mode_preference: 'connected',
    });
    expect(reloaded.problem).toBeNull();
  });

  it('falls back to defaults on corrupt data and keeps a backup', () => {
    const storage = new MemoryStorage();
    storage.setItem(PREFS_KEY, '{not json');
    const result = new PrefsStore(storage).load();
    expect(result.prefs).toEqual(defaultPrefs());
    expect(result.problem).toContain('could not be read');
    expect(storage.getItem(PREFS_BACKUP_KEY)).toBe('{not json');
  });

  it('does not overwrite preferences written by a newer version', () => {
    const storage = new MemoryStorage();
    const newer = JSON.stringify({ schema_version: 7, anything: 1 });
    storage.setItem(PREFS_KEY, newer);
    const store = new PrefsStore(storage);
    const result = store.load();
    expect(result.writable).toBe(false);
    store.save({ mode_preference: 'local' });
    expect(storage.getItem(PREFS_KEY)).toBe(newer);
  });

  it('drops a stored backend URL that is no longer valid', () => {
    const storage = new MemoryStorage();
    storage.setItem(
      PREFS_KEY,
      JSON.stringify({
        schema_version: 1,
        backend_url: 'javascript:alert(1)',
        mode_preference: 'auto',
        saved_views: [],
      }),
    );
    expect(new PrefsStore(storage).load().prefs.backend_url).toBe('http://127.0.0.1:8787');
  });
});

describe('saved views', () => {
  let counter = 0;
  const makeId = () => `v${(counter += 1)}`;
  const filters = { ...DEFAULT_FILTERS, text: 'robot', work_mode: 'remote' as const };
  const sort = { ...DEFAULT_SORT, key: 'score' as const, direction: 'desc' as const };

  it('adds, updates case-insensitively, and removes', () => {
    const first = upsertView([], '  Remote  robots ', filters, sort, NOW, makeId);
    expect(first.ok).toBe(true);
    if (!first.ok) return;
    expect(first.replaced).toBe(false);
    expect(first.views[0]).toMatchObject({ name: 'Remote robots', filters, sort });

    const again = upsertView(
      first.views,
      'remote ROBOTS',
      DEFAULT_FILTERS,
      DEFAULT_SORT,
      NOW,
      makeId,
    );
    expect(again.ok).toBe(true);
    if (!again.ok) return;
    expect(again.replaced).toBe(true);
    expect(again.views).toHaveLength(1);
    expect(again.views[0]?.filters).toEqual(DEFAULT_FILTERS);
    expect(again.views[0]?.id).toBe(first.views[0]?.id);

    expect(removeView(again.views, again.views[0]?.id ?? '')).toEqual([]);
  });

  it('refuses empty names, long names and too many views', () => {
    expect(upsertView([], '   ', filters, sort, NOW, makeId)).toMatchObject({ ok: false });
    expect(upsertView([], 'x'.repeat(61), filters, sort, NOW, makeId)).toMatchObject({ ok: false });
    let views: ReturnType<typeof removeView> = [];
    for (let i = 0; i < MAX_SAVED_VIEWS; i += 1) {
      const result = upsertView(views, `view ${i}`, filters, sort, NOW, makeId);
      if (!result.ok) throw new Error('unexpected');
      views = result.views;
    }
    expect(upsertView(views, 'one more', filters, sort, NOW, makeId)).toMatchObject({ ok: false });
  });
});
