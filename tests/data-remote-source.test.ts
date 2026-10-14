import { describe, expect, it } from 'vitest';
import { analyze } from '../src/engine';
import { SourceError } from '../src/data/errors';
import { RemoteSource } from '../src/data/remoteSource';
import { csv, FORM_DEFAULTS, makeClock, NOW } from './data-helpers';

const BASE = 'http://127.0.0.1:8787';

interface Call {
  method: string;
  url: URL;
  body: unknown;
  mode: string | undefined;
}

type Reply = Response | Error | 'hang';
type Handler = (call: Call) => Reply;

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

function envelope(status: number, code: string, message: string, headers = {}): Response {
  return json({ error: { code, message } }, status, headers);
}

function makeFetch(handler: Handler) {
  const calls: Call[] = [];
  const fetchImpl = (input: string, init?: RequestInit): Promise<Response> => {
    const call: Call = {
      method: init?.method ?? 'GET',
      url: new URL(input),
      body: typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : undefined,
      mode: init?.mode,
    };
    calls.push(call);
    const reply = handler(call);
    if (reply instanceof Error) return Promise.reject(reply);
    if (reply === 'hang') {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new Error('aborted')));
      });
    }
    return Promise.resolve(reply);
  };
  return { fetchImpl, calls };
}

function source(handler: Handler, extra: { timeoutMs?: number } = {}) {
  const stub = makeFetch(handler);
  const remote = new RemoteSource({
    baseUrl: BASE,
    fetchImpl: stub.fetchImpl,
    clock: makeClock(),
    ...extra,
  });
  return { remote, calls: stub.calls };
}

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
      postings: [
        { company_name: 'Acme Inc.', title: 'Data Engineer', source_posting_id: '1' },
        { company_name: 'Acme Inc.', title: 'Designer', source_posting_id: '2' },
      ],
    },
    {
      snapshot_id: 's2',
      source_kind: 'csv',
      source_ref: 'SAMPLE-A Board',
      observed_at: '2026-10-01T08:00:00Z',
      mode: 'additive',
      postings: [{ company_name: 'ACME', title: 'Data Engineer' }],
    },
  ],
});

async function failure(promise: Promise<unknown>): Promise<SourceError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof SourceError) return error;
    throw error;
  }
  throw new Error('expected a SourceError');
}

function fullRoutes(call: Call): Reply {
  switch (`${call.method} ${call.url.pathname}`) {
    case 'GET /api/analysis':
      return json(analysis);
    case 'GET /api/profile':
      return json({ include_keywords: ['engineer'], exclude_keywords: [] });
    case 'GET /api/shortlist':
      return json([
        {
          company_id: analysis.companies[0]?.company_id,
          name: 'Acme Inc.',
          note: null,
          added_at: NOW,
        },
      ]);
    case 'GET /api/merge-decisions':
      return json({ decisions: [{ id: 7, a_key: 'a', b_key: 'b', decision: 'not_same' }] });
    default:
      return envelope(404, 'not_found', `no route for ${call.method} ${call.url.pathname}`);
  }
}

describe('RemoteSource.load', () => {
  it('reads the four documented endpoints and derives datasets from the analysis', async () => {
    const { remote, calls } = source(fullRoutes);
    const ws = await remote.load();
    expect(calls.map((c) => `${c.method} ${c.url.pathname}`).sort()).toEqual([
      'GET /api/analysis',
      'GET /api/merge-decisions',
      'GET /api/profile',
      'GET /api/shortlist',
    ]);
    expect(ws.mode).toBe('connected');
    expect(ws.analysis.companies[0]?.name).toBe('Acme Inc.');
    expect(ws.profile.include_keywords).toEqual(['engineer']);
    expect(ws.shortlist).toEqual([
      { company_id: analysis.companies[0]?.company_id, name: 'Acme Inc.', note: '', added_at: NOW },
    ]);
    expect(ws.decisions).toEqual([{ id: '7', a_key: 'a', b_key: 'b', decision: 'not_same' }]);
    expect(ws.datasets.map((d) => d.id)).toEqual(['csv:SAMPLE-A Board', 'greenhouse:acme']);
    expect(ws.has_sample_data).toBe(true);
    expect(ws.notices).toEqual([]);
  });

  it('sends no credentials and no as_of unless asked', async () => {
    const { remote, calls } = source(fullRoutes);
    await remote.load();
    expect(calls.every((c) => c.url.search === '')).toBe(true);
  });

  it('reports a response that does not match the contract as bad_response', async () => {
    const { remote } = source((call) =>
      call.url.pathname === '/api/analysis'
        ? json({ ...analysis, companies: [{ company_id: 1 }] })
        : fullRoutes(call),
    );
    const error = await failure(remote.load());
    expect(error.kind).toBe('bad_response');
    expect(error.message).toContain('companies');
  });

  it('reports non-JSON as bad_response', async () => {
    const { remote } = source((call) =>
      call.url.pathname === '/api/profile' ? new Response('<html>nope</html>') : fullRoutes(call),
    );
    expect((await failure(remote.load())).kind).toBe('bad_response');
  });
});

describe('RemoteSource error mapping', () => {
  it('parses the error envelope: code, message, status', async () => {
    const { remote } = source(() =>
      envelope(422, 'invalid_profile', 'include_keywords has too many entries'),
    );
    const error = await failure(remote.setProfile({ include_keywords: [], exclude_keywords: [] }));
    expect(error).toMatchObject({
      kind: 'api',
      code: 'invalid_profile',
      status: 422,
      message: 'include_keywords has too many entries',
    });
  });

  it('records Retry-After on 429 too_soon', async () => {
    const { remote } = source(() =>
      envelope(429, 'too_soon', 'Wait before refreshing again', { 'Retry-After': '42' }),
    );
    const error = await failure(remote.sources.refresh('3'));
    expect(error).toMatchObject({
      kind: 'api',
      code: 'too_soon',
      status: 429,
      retryAfterSeconds: 42,
    });
  });

  it('maps a non-envelope error to kind http without echoing the body', async () => {
    const { remote } = source(() => new Response('<h1>502 Bad Gateway</h1>', { status: 502 }));
    const error = await failure(remote.load());
    expect(error.kind).toBe('http');
    expect(error.status).toBe(502);
    expect(error.message).not.toContain('Bad Gateway');
  });

  it('classifies a failed fetch as offline when nothing answers', async () => {
    const { remote, calls } = source(() => new TypeError('Failed to fetch'));
    const error = await failure(remote.load());
    expect(error.kind).toBe('offline');
    expect(error.isConnectivity).toBe(true);
    expect(error.message).toContain(BASE);
    // A no-cors probe was made to tell "down" from "CORS".
    expect(calls.some((c) => c.mode === 'no-cors')).toBe(true);
  });

  it('classifies a failed CORS read as cors when a no-cors probe is answered', async () => {
    const { remote } = source((call) =>
      call.mode === 'no-cors'
        ? new Response(null, { status: 200 })
        : new TypeError('Failed to fetch'),
    );
    const error = await failure(remote.load());
    expect(error.kind).toBe('cors');
    expect(error.message).toContain('RECRUIT_RADAR_CORS_ORIGINS');
  });

  it('times out a request that never completes', async () => {
    const { remote } = source(() => 'hang', { timeoutMs: 25 });
    const error = await failure(remote.load());
    expect(error.kind).toBe('timeout');
    expect(error.isConnectivity).toBe(true);
  });
});

describe('RemoteSource writes', () => {
  it('imports CSV: maps ImportResult and recovers rejected row values for correction', async () => {
    const text = csv(
      'Acme,Engineer,Austin,remote,,,',
      'Acme,,Austin,remote,,,',
      'Beta,Analyst,,teleport,,,',
    );
    const { remote, calls } = source((call) =>
      json(
        {
          snapshot_id: 'snap_9',
          dataset_label: 'Board A',
          accepted: 1,
          rejected: 2,
          errors: [
            { line: 3, field: 'title', message: 'title is required' },
            { line: 4, field: 'work_mode', message: 'bad work_mode' },
          ],
          warnings: [{ line: 1, message: 'Unknown column "x" is ignored' }],
        },
        call.method === 'POST' ? 201 : 200,
      ),
    );
    const report = await remote.importCsv('Board A', text);
    expect(calls[0]).toMatchObject({ method: 'POST' });
    expect(calls[0]?.url.pathname).toBe('/api/imports/csv');
    expect(calls[0]?.body).toEqual({ dataset_label: 'Board A', csv_text: text });
    expect(report).toMatchObject({ ok: true, accepted: 1, rejected: 2 });
    expect(report.errors.map((e) => [e.line, e.field])).toEqual([
      [3, 'title'],
      [4, 'work_mode'],
    ]);
    expect(report.warnings).toEqual([{ line: 1, message: 'Unknown column "x" is ignored' }]);
    expect(report.rejected_rows.map((r) => [r.line, r.values.company_name])).toEqual([
      [3, 'Acme'],
      [4, 'Beta'],
    ]);
  });

  it('turns 422 invalid_csv into a file-level report instead of throwing', async () => {
    const { remote } = source(() => envelope(422, 'invalid_csv', 'A quoted field is never closed'));
    const report = await remote.importCsv('Board A', '"x');
    expect(report.ok).toBe(false);
    expect(report.file_error).toEqual({
      code: 'invalid_csv',
      message: 'A quoted field is never closed',
    });
    expect(report.accepted).toBe(0);
  });

  it('validates a manual posting locally and posts exactly the documented fields', async () => {
    const { remote, calls } = source(() => json({ id: 1 }, 201));
    const bad = await remote.addManualPosting({ ...FORM_DEFAULTS, company_name: 'Acme' });
    expect(bad.ok).toBe(false);
    expect(calls).toHaveLength(0);

    const good = await remote.addManualPosting({
      ...FORM_DEFAULTS,
      company_name: '  Acme ',
      title: 'Engineer',
      work_mode: 'remote',
      posted_at: '2026-09-01',
    });
    expect(good).toEqual({ ok: true });
    expect(calls[0]?.url.pathname).toBe('/api/postings');
    expect(calls[0]?.body).toEqual({
      dataset_label: 'manual',
      company_name: 'Acme',
      title: 'Engineer',
      location: null,
      work_mode: 'remote',
      department: null,
      url: null,
      posted_at: '2026-09-01',
      source_posting_id: null,
    });
  });

  it('returns a backend 422 for a posting as a form-level problem', async () => {
    const { remote } = source(() => envelope(422, 'invalid_posting', 'title is too long'));
    const result = await remote.addManualPosting({
      ...FORM_DEFAULTS,
      company_name: 'Acme',
      title: 'Engineer',
    });
    expect(result).toEqual({
      ok: false,
      problems: [{ field: 'form', message: 'title is too long' }],
    });
  });

  it('puts shortlist state at the encoded company path and omits an absent note', async () => {
    const { remote, calls } = source(() => json({ ok: true }));
    await remote.setShortlisted('c_ab12', true);
    await remote.setShortlisted('c_ab12', true, 'note');
    expect(calls[0]).toMatchObject({ method: 'PUT', body: { shortlisted: true } });
    expect(calls[0]?.url.pathname).toBe('/api/companies/c_ab12/shortlist');
    expect(calls[1]?.body).toEqual({ shortlisted: true, note: 'note' });
  });

  it('posts and deletes merge decisions', async () => {
    const { remote, calls } = source(() => new Response(null, { status: 204 }));
    await remote.decide('a', 'b', 'merge');
    await remote.undoDecision('12');
    expect(calls[0]).toMatchObject({
      method: 'POST',
      body: { a_key: 'a', b_key: 'b', decision: 'merge' },
    });
    expect(calls[1]).toMatchObject({ method: 'DELETE' });
    expect(calls[1]?.url.pathname).toBe('/api/merge-decisions/12');
  });

  it('erases with the documented confirmation parameter', async () => {
    const { remote, calls } = source(() => new Response(null, { status: 204 }));
    await remote.eraseAll();
    expect(calls[0]?.method).toBe('DELETE');
    expect(calls[0]?.url.pathname).toBe('/api/data');
    expect(calls[0]?.url.searchParams.get('confirm')).toBe('erase-all');
  });

  it('downloads the shortlist CSV as text', async () => {
    const { remote } = source(
      () => new Response('rank,company\r\n1,Acme\r\n', { headers: { 'Content-Type': 'text/csv' } }),
    );
    expect(await remote.exportShortlistCsv()).toBe('rank,company\r\n1,Acme\r\n');
  });

  it('refuses local-only operations without making a request', async () => {
    const { remote, calls } = source(() => json({}));
    expect((await failure(remote.loadSample())).kind).toBe('unavailable');
    expect((await failure(remote.removeDataset())).kind).toBe('unavailable');
    expect((await failure(remote.exportPostingsCsv())).kind).toBe('unavailable');
    expect(calls).toHaveLength(0);
    expect(remote.capabilities).toEqual({
      refresh: true,
      loadSample: false,
      removeDataset: false,
      exportPostings: false,
    });
  });
});

describe('RemoteSource ATS sources', () => {
  const run = {
    id: 5,
    source_id: 2,
    started_at: '2026-10-13T11:00:00Z',
    finished_at: '2026-10-13T11:00:02Z',
    status: 'ok',
    error_kind: null,
    http_status: 200,
    retry_after_s: null,
    items_seen: 4,
    added: 1,
    changed: 1,
    removed: 1,
    reappeared: 0,
    unchanged: 1,
    message: '',
  };

  it('lists sources from a bare array or a wrapped list, with the last run', async () => {
    const row = {
      id: 2,
      provider: 'greenhouse',
      token: 'acme',
      company_name: 'Acme',
      last_run: run,
    };
    const wrapped = source(() => json({ sources: [row] }));
    const bare = source(() => json([row]));
    for (const { remote } of [wrapped, bare]) {
      const list = await remote.sources.list();
      expect(list).toHaveLength(1);
      expect(list[0]).toMatchObject({ id: '2', provider: 'greenhouse', token: 'acme' });
      expect(list[0]?.last_run).toMatchObject({ id: '5', source_id: '2', status: 'ok', added: 1 });
    }
  });

  it('rejects an invalid board token without a request', async () => {
    const { remote, calls } = source(() => json({}));
    const error = await failure(
      remote.sources.add({ provider: 'lever', token: 'bad token/../x', company_name: 'Acme' }),
    );
    expect(error).toMatchObject({ kind: 'invalid_input', code: 'invalid_token' });
    expect(calls).toHaveLength(0);
  });

  it('adds a source, refreshes it and reads history', async () => {
    const created = {
      id: 9,
      provider: 'ashby',
      token: 'beta',
      company_name: 'Beta',
      last_run: null,
    };
    const { remote, calls } = source((call) => {
      if (call.method === 'POST' && call.url.pathname === '/api/sources') return json(created, 201);
      if (call.url.pathname.endsWith('/refresh')) return json({ ...run, source_id: 9 });
      if (call.url.pathname.endsWith('/runs')) {
        return json([
          {
            ...run,
            status: 'failed',
            error_kind: 'rate_limited',
            http_status: 429,
            retry_after_s: 30,
            message: 'slow down',
          },
        ]);
      }
      return envelope(404, 'not_found', 'nope');
    });
    const added = await remote.sources.add({
      provider: 'ashby',
      token: 'beta',
      company_name: 'Beta',
    });
    expect(added).toMatchObject({ id: '9', last_run: null });
    expect(calls[0]?.body).toEqual({ provider: 'ashby', token: 'beta', company_name: 'Beta' });
    const refreshed = await remote.sources.refresh('9');
    expect(refreshed).toMatchObject({ source_id: '9', added: 1, removed: 1 });
    const runs = await remote.sources.runs('9');
    expect(runs[0]).toMatchObject({
      status: 'failed',
      error_kind: 'rate_limited',
      retry_after_s: 30,
    });
  });

  it('maps a duplicate source to the 409 code', async () => {
    const { remote } = source(() => envelope(409, 'source_exists', 'That source already exists'));
    const error = await failure(
      remote.sources.add({ provider: 'greenhouse', token: 'acme', company_name: 'Acme' }),
    );
    expect(error).toMatchObject({ kind: 'api', code: 'source_exists', status: 409 });
  });
});
