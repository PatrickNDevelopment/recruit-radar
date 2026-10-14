import { describe, expect, it } from 'vitest';
import { analyze } from '../src/engine';
import { PREFS_KEY } from '../src/data/prefs';
import { SessionStore, type SessionDeps } from '../src/data/session';
import { MemoryStorage } from '../src/data/storage';
import { DEFAULT_FILTERS, DEFAULT_SORT } from '../src/data/types';
import { WORKSPACE_KEY } from '../src/data/localSource';
import { csv, makeClock, NOW } from './data-helpers';

const BASE = 'http://127.0.0.1:8787';

const analysis = analyze({
  as_of: NOW,
  profile: { include_keywords: ['engineer'], exclude_keywords: [] },
  snapshots: [
    {
      snapshot_id: 's1',
      source_kind: 'greenhouse',
      source_ref: 'acme',
      observed_at: '2026-09-01T08:00:00Z',
      mode: 'full',
      postings: [{ company_name: 'Acme Inc.', title: 'Data Engineer', source_posting_id: '1' }],
    },
  ],
});

type Reply = Response | Error;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

interface Backend {
  up: boolean;
  /** Paths that fail with a network error while `up` is true. */
  broken: Set<string>;
  calls: string[];
}

function makeBackend(initiallyUp: boolean): {
  backend: Backend;
  fetchImpl: SessionDeps['fetchImpl'];
} {
  const backend: Backend = { up: initiallyUp, broken: new Set(), calls: [] };
  const fetchImpl = (input: string, init?: RequestInit): Promise<Response> => {
    const url = new URL(input);
    const method = init?.method ?? 'GET';
    backend.calls.push(`${method} ${url.pathname}`);
    const reply = ((): Reply => {
      if (!backend.up) return new TypeError('Failed to fetch');
      if (backend.broken.has(url.pathname)) return new TypeError('Failed to fetch');
      switch (url.pathname) {
        case '/api/health':
          return json({ status: 'ok', schema_version: 1, app_version: '0.1.0', db_ok: true });
        case '/api/analysis':
          return json(analysis);
        case '/api/profile':
          return json({ include_keywords: ['engineer'], exclude_keywords: [] });
        case '/api/shortlist':
          return json([]);
        case '/api/merge-decisions':
          return json([]);
        default:
          return json({ error: { code: 'not_found', message: 'no such route' } }, 404);
      }
    })();
    return reply instanceof Error ? Promise.reject(reply) : Promise.resolve(reply);
  };
  return { backend, fetchImpl };
}

class FakeWindow {
  private readonly handlers = new Set<(event: Event) => void>();
  addEventListener(_type: 'storage', handler: (event: Event) => void): void {
    this.handlers.add(handler);
  }
  removeEventListener(_type: 'storage', handler: (event: Event) => void): void {
    this.handlers.delete(handler);
  }
  fireStorage(key: string | null): void {
    for (const handler of this.handlers) handler({ key } as unknown as Event);
  }
  get listeners(): number {
    return this.handlers.size;
  }
}

function setup(options: {
  hostname?: string | null;
  backendUp?: boolean;
  storage?: MemoryStorage | null;
  prefs?: object;
}) {
  const storage = options.storage === undefined ? new MemoryStorage() : options.storage;
  if (options.prefs !== undefined && storage !== null) {
    storage.setItem(PREFS_KEY, JSON.stringify({ schema_version: 1, ...options.prefs }));
  }
  const { backend, fetchImpl } = makeBackend(options.backendUp ?? true);
  const events = new FakeWindow();
  let ids = 0;
  const store = new SessionStore({
    storage,
    ...(fetchImpl === undefined ? {} : { fetchImpl }),
    clock: makeClock(),
    pageHostname: options.hostname === undefined ? 'localhost' : options.hostname,
    events,
    makeId: () => `view-${(ids += 1)}`,
    requestTimeoutMs: 500,
    healthTimeoutMs: 500,
  });
  return { store, storage, backend, events };
}

describe('SessionStore: choosing a source', () => {
  it('connects when the page is local, the backend is healthy and the preference is auto', async () => {
    const { store, backend } = setup({});
    await store.start();
    const state = store.getState();
    expect(state.mode).toBe('connected');
    expect(state.backend.state).toBe('ok');
    expect(state.workspace?.mode).toBe('connected');
    expect(state.workspace?.analysis.companies).toHaveLength(1);
    expect(backend.calls[0]).toBe('GET /api/health');
    expect(state.ready).toBe(true);
    expect(state.loadError).toBeNull();
  });

  it('never probes the backend from a public host on its own', async () => {
    const { store, backend } = setup({ hostname: 'someone.github.io' });
    await store.start();
    expect(backend.calls).toEqual([]);
    const state = store.getState();
    expect(state.mode).toBe('local');
    expect(state.backend.state).toBe('unchecked');
    expect(state.workspace?.mode).toBe('local');
  });

  it('never probes when the user chose local-data mode', async () => {
    const { store, backend } = setup({
      prefs: { backend_url: BASE, mode_preference: 'local', saved_views: [] },
    });
    await store.start();
    expect(backend.calls).toEqual([]);
    expect(store.getState().mode).toBe('local');
  });

  it('falls back to local data with an explicit offline state when the backend is down', async () => {
    const { store } = setup({ backendUp: false });
    await store.start();
    const state = store.getState();
    expect(state.mode).toBe('local');
    expect(state.backend.state).toBe('offline');
    if (state.backend.state === 'offline') {
      expect(state.backend.kind).toBe('offline');
      expect(state.backend.message).toContain(BASE);
    }
    expect(state.workspace?.mode).toBe('local');
    // Still usable: add a posting locally.
    const added = await store.importCsv('mine', csv('Acme,Engineer,,,,,'));
    expect(added.ok).toBe(true);
    expect(store.getState().workspace?.analysis.companies).toHaveLength(1);
  });

  it('probes a public host only after the user opts in with "connected"', async () => {
    const { store, backend } = setup({ hostname: 'someone.github.io' });
    await store.start();
    expect(backend.calls).toEqual([]);
    await store.setModePreference('connected');
    expect(backend.calls[0]).toBe('GET /api/health');
    expect(store.getState().mode).toBe('connected');
  });

  it('start() is idempotent', async () => {
    const { store, backend } = setup({});
    await Promise.all([store.start(), store.start()]);
    await store.start();
    expect(backend.calls.filter((c) => c === 'GET /api/health')).toHaveLength(1);
  });

  it('keeps local data when switching mode and does not show it under the connected label', async () => {
    const { store } = setup({ backendUp: false });
    await store.start();
    await store.importCsv('mine', csv('Local Co,Engineer,,,,,'));
    expect(store.getState().workspace?.analysis.companies[0]?.name).toBe('Local Co');
    await store.setModePreference('local');
    expect(store.getState().workspace?.analysis.companies[0]?.name).toBe('Local Co');
  });
});

describe('SessionStore: backend address', () => {
  it('refuses a non-http address without touching the stored one', async () => {
    const { store } = setup({});
    await store.start();
    const result = await store.setBackendUrl('ftp://example.com');
    expect(result.ok).toBe(false);
    expect(store.getState().prefs.backend_url).toBe(BASE);
  });

  it('stores a valid address, normalised, and re-checks the backend', async () => {
    const { store, backend, storage } = setup({});
    await store.start();
    backend.calls.length = 0;
    const result = await store.setBackendUrl('  http://127.0.0.1:8787/  ');
    expect(result).toEqual({ ok: true });
    expect(store.getState().prefs.backend_url).toBe('http://127.0.0.1:8787');
    expect(backend.calls[0]).toBe('GET /api/health');
    expect(storage?.getItem(PREFS_KEY)).toContain('http://127.0.0.1:8787');
  });
});

describe('SessionStore: failures', () => {
  it('labels the last workspace as stale and marks the backend offline on a lost connection', async () => {
    const { store, backend } = setup({});
    await store.start();
    expect(store.getState().mode).toBe('connected');
    backend.up = false;
    const ok = await store.reload();
    expect(ok).toBe(false);
    const state = store.getState();
    expect(state.workspace).not.toBeNull();
    expect(state.stale).not.toBeNull();
    expect(state.loadError).toContain(BASE);
    expect(state.backend.state).toBe('offline');
    // Back up: reload clears the stale label.
    backend.up = true;
    expect(await store.reload()).toBe(true);
    expect(store.getState().stale).toBeNull();
    expect(store.getState().loadError).toBeNull();
  });

  it('reports a rejected operation through the status region without throwing', async () => {
    const { store } = setup({ backendUp: false });
    await store.start();
    const result = await store.loadSample();
    expect(result.ok).toBe(true);
    const again = await store.loadSample();
    expect(again.ok).toBe(false);
    expect(store.getState().status?.kind).toBe('error');
    expect(store.getState().status?.text).toContain('already loaded');
  });

  it('numbers every status message so an identical text is announced again', async () => {
    const { store } = setup({ backendUp: false });
    await store.start();
    store.announce('info', 'Same text');
    const first = store.getState().status?.id ?? 0;
    store.announce('info', 'Same text');
    expect(store.getState().status?.id).toBe(first + 1);
    store.clearStatus();
    expect(store.getState().status).toBeNull();
  });
});

describe('SessionStore: other tabs', () => {
  it('shows a notice when another tab changes the stored data, and clears it on reload', async () => {
    const { store, events } = setup({ backendUp: false });
    await store.start();
    expect(events.listeners).toBe(1);
    expect(store.getState().externalChange).toBe(false);
    events.fireStorage('unrelated-key');
    expect(store.getState().externalChange).toBe(false);
    events.fireStorage(WORKSPACE_KEY);
    expect(store.getState().externalChange).toBe(true);
    await store.reload();
    expect(store.getState().externalChange).toBe(false);
  });

  it('stops listening once connected mode takes over, and on dispose', async () => {
    const { store, events } = setup({});
    await store.start();
    expect(store.getState().mode).toBe('connected');
    expect(events.listeners).toBe(0);
    await store.setModePreference('local');
    expect(events.listeners).toBe(1);
    store.dispose();
    expect(events.listeners).toBe(0);
  });
});

describe('SessionStore: saved views and operations', () => {
  it('saves, updates and deletes views and announces each', async () => {
    const { store, storage } = setup({ backendUp: false });
    await store.start();
    const filters = { ...DEFAULT_FILTERS, work_mode: 'remote' as const };
    expect(store.saveView('Remote only', filters, DEFAULT_SORT).ok).toBe(true);
    expect(store.getState().prefs.saved_views).toHaveLength(1);
    expect(store.getState().status?.text).toBe('Saved the view "Remote only".');
    expect(store.saveView('remote ONLY', DEFAULT_FILTERS, DEFAULT_SORT).ok).toBe(true);
    expect(store.getState().prefs.saved_views).toHaveLength(1);
    expect(store.getState().status?.text).toBe('Updated the saved view "remote ONLY".');
    expect(store.saveView('  ', DEFAULT_FILTERS, DEFAULT_SORT).ok).toBe(false);
    expect(store.getState().status?.kind).toBe('error');
    const id = store.getState().prefs.saved_views[0]?.id ?? '';
    expect(storage?.getItem(PREFS_KEY)).toContain('remote ONLY');
    store.deleteView(id);
    expect(store.getState().prefs.saved_views).toEqual([]);
    expect(store.getState().status?.text).toBe('Deleted the view "remote ONLY".');
  });

  it('reports import results truthfully, including rejected rows', async () => {
    const { store } = setup({ backendUp: false });
    await store.start();
    const result = await store.importCsv(
      'jobs',
      csv('Acme,Engineer,,remote,,,', 'Bad,,,,,,', 'Other,Nurse,,sideways,,,'),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.accepted).toBe(1);
    expect(result.value.rejected).toBe(2);
    expect(store.getState().status).toMatchObject({
      kind: 'info',
      text: 'Imported 1 row into "jobs"; 2 rows were rejected, see the report.',
    });
    expect(store.getState().workspace?.analysis.companies).toHaveLength(1);

    const failed = await store.importCsv('jobs', 'title\r\nEngineer\r\n');
    expect(failed.ok).toBe(true);
    expect(store.getState().status?.kind).toBe('error');
    expect(store.getState().status?.text).toContain('Nothing was imported');
  });

  it('returns the decision id so a merge can be undone', async () => {
    const { store } = setup({ backendUp: false });
    await store.start();
    await store.importCsv('one', csv('DoorDash,Engineer,,,,,', 'Door Dash,Designer,,,,,'));
    const candidate = store.getState().workspace?.analysis.merge_candidates[0];
    if (candidate === undefined) throw new Error('expected a merge candidate');
    const decided = await store.decideCandidate(candidate, 'merge');
    expect(decided.ok).toBe(true);
    if (!decided.ok) return;
    expect(decided.value.decisionId).not.toBeNull();
    expect(store.getState().workspace?.analysis.companies).toHaveLength(1);
    await store.undoDecision(decided.value.decisionId ?? '');
    expect(store.getState().workspace?.analysis.companies).toHaveLength(2);
    expect(store.getState().workspace?.analysis.merge_candidates).toHaveLength(1);
  });

  it('shortlists with a note and erases everything on request', async () => {
    const { store } = setup({ backendUp: false });
    await store.start();
    await store.importCsv('one', csv('Acme,Engineer,,,,,'));
    const id = store.getState().workspace?.analysis.companies[0]?.company_id ?? '';
    await store.setShortlisted(id, true, 'call next week');
    expect(store.getState().workspace?.shortlist[0]?.note).toBe('call next week');
    expect(store.getState().status?.text).toBe('Saved the note for Acme.');
    const exported = await store.exportShortlistCsv();
    expect(exported.ok && exported.value.includes('call next week')).toBe(true);
    await store.eraseAll();
    expect(store.getState().workspace?.analysis.companies).toEqual([]);
    expect(store.getState().workspace?.shortlist).toEqual([]);
  });

  it('refuses ATS source calls in local mode instead of pretending', async () => {
    const { store } = setup({ backendUp: false });
    await store.start();
    const list = await store.listAtsSources();
    expect(list.ok).toBe(false);
    if (!list.ok) expect(list.message).toContain('connected mode');
    // listing is a probe: it must not raise an error banner of its own
    expect(store.getState().status?.kind).not.toBe('error');
  });
});
