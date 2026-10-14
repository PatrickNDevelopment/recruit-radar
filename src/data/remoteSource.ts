/**
 * RemoteSource: the spec 03 HTTP API client (connected mode).
 *
 * Every response is validated; every failure becomes a `SourceError` with a kind the UI can act
 * on (offline / CORS / timeout / api error with its backend code / bad response). Nothing is
 * cached here: the backend is the source of truth, so a failed request never shows stale data as
 * if it were current.
 */
import type { ZodType } from 'zod';
import {
  importCsv as engineImportCsv,
  validateImportRow,
  type DecisionKind,
  type Profile,
} from '../engine';
import { systemClock, type Clock } from './clock';
import {
  classifyNetworkFailure,
  corsMessage,
  defaultFetch,
  offlineMessage,
  RequestTimeout,
  timedRequest,
  type FetchLike,
  type RawResponse,
} from './connection';
import { summarizeDatasets } from './derive';
import { SourceError } from './errors';
import {
  analysisSchema,
  atsSourceSchema,
  decisionSchema,
  errorEnvelopeSchema,
  importResultSchema,
  profileSchema,
  refreshRunSchema,
  shortlistEntrySchema,
} from './remoteSchemas';
import type {
  AnalysisSource,
  AtsSource,
  AtsSources,
  Capabilities,
  DecisionRecord,
  ImportReport,
  NewAtsSource,
  PostingFormValues,
  RefreshRun,
  ShortlistEntry,
  SubmitResult,
  Workspace,
} from './types';

export const REQUEST_TIMEOUT_MS = 10_000;
/** A refresh makes several upstream requests (15 s timeout each, up to 50 Lever pages). */
export const REFRESH_TIMEOUT_MS = 120_000;
export const TOKEN_PATTERN = /^[A-Za-z0-9_.-]{1,100}$/u;

export interface RemoteSourceOptions {
  /** Normalised base URL without a trailing slash (see `validateBackendUrl`). */
  baseUrl: string;
  fetchImpl?: FetchLike;
  clock?: Clock;
  timeoutMs?: number;
  refreshTimeoutMs?: number;
}

interface RequestOptions<T> {
  query?: Record<string, string>;
  body?: unknown;
  /** Validates and types the JSON body. Omit for 204 / text responses. */
  schema?: ZodType<T>;
  timeoutMs?: number;
  expect?: 'json' | 'text' | 'none';
}

const CAPABILITIES: Capabilities = {
  refresh: true,
  loadSample: false,
  removeDataset: false,
  exportPostings: false,
};

function unavailable(what: string): SourceError {
  return new SourceError('unavailable', `${what} is only available in local-data mode.`, {
    code: 'unavailable',
  });
}

function parseRetryAfter(headers: Headers): number | null {
  const value = headers.get('Retry-After');
  if (value === null) return null;
  return /^\d{1,7}$/u.test(value.trim()) ? Number(value.trim()) : null;
}

function parseJsonOrNull(text: string): unknown {
  if (text === '') return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

/** Bare array, or an object holding exactly one of the named array properties. */
function unwrapList(json: unknown, names: readonly string[]): unknown[] | null {
  if (Array.isArray(json)) return json;
  if (typeof json === 'object' && json !== null) {
    for (const name of names) {
      const value = (json as Record<string, unknown>)[name];
      if (Array.isArray(value)) return value;
    }
  }
  return null;
}

export class RemoteSource implements AnalysisSource {
  readonly mode = 'connected' as const;
  readonly capabilities = CAPABILITIES;
  readonly sources: AtsSources;
  readonly baseUrl: string;

  private readonly fetchImpl: FetchLike;
  private readonly clock: Clock;
  private readonly timeoutMs: number;
  private readonly refreshTimeoutMs: number;

  constructor(options: RemoteSourceOptions) {
    this.baseUrl = options.baseUrl;
    this.fetchImpl = options.fetchImpl ?? defaultFetch();
    this.clock = options.clock ?? systemClock;
    this.timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS;
    this.refreshTimeoutMs = options.refreshTimeoutMs ?? REFRESH_TIMEOUT_MS;
    this.sources = this.buildSources();
  }

  // ---- HTTP core ----------------------------------------------------------------------------

  private url(path: string, query?: Record<string, string>): string {
    const search =
      query === undefined || Object.keys(query).length === 0
        ? ''
        : `?${new URLSearchParams(query).toString()}`;
    return `${this.baseUrl}${path}${search}`;
  }

  private async send(
    method: string,
    path: string,
    options: { query?: Record<string, string>; body?: unknown; timeoutMs?: number },
  ): Promise<RawResponse> {
    const url = this.url(path, options.query);
    const headers: Record<string, string> = { Accept: 'application/json, text/csv' };
    let body: string | undefined;
    if (options.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(options.body);
    }
    try {
      return await timedRequest(
        this.fetchImpl,
        url,
        { method, headers, body, cache: 'no-store', credentials: 'omit' },
        options.timeoutMs ?? this.timeoutMs,
      );
    } catch (error) {
      if (error instanceof RequestTimeout) {
        throw new SourceError('timeout', error.message, { cause: error });
      }
      const kind = await classifyNetworkFailure(this.fetchImpl, `${this.baseUrl}/api/health`);
      if (kind === 'cors') {
        throw new SourceError('cors', corsMessage(this.baseUrl), { cause: error });
      }
      throw new SourceError('offline', offlineMessage(this.baseUrl), { cause: error });
    }
  }

  private failure(response: RawResponse): SourceError {
    const json = parseJsonOrNull(response.text);
    const retryAfterSeconds = parseRetryAfter(response.headers);
    const envelope = errorEnvelopeSchema.safeParse(json);
    if (envelope.success) {
      const { code, message, details } = envelope.data.error;
      return new SourceError('api', message, {
        code,
        status: response.status,
        details,
        retryAfterSeconds,
      });
    }
    const status = response.status;
    return new SourceError(
      'http',
      `The backend answered HTTP ${status}${response.text === '' ? '' : ' with an unexpected body'}.`,
      { status, retryAfterSeconds },
    );
  }

  private async request<T>(
    method: string,
    path: string,
    options: RequestOptions<T> = {},
  ): Promise<T> {
    const response = await this.send(method, path, options);
    if (!response.ok) throw this.failure(response);
    const expect = options.expect ?? 'json';
    if (expect === 'none') return undefined as T;
    if (expect === 'text') return response.text as T;
    let json: unknown;
    try {
      json = JSON.parse(response.text);
    } catch (error) {
      throw new SourceError(
        'bad_response',
        `The backend answered ${method} ${path} with something that is not JSON.`,
        { status: response.status, cause: error },
      );
    }
    if (options.schema === undefined) return json as T;
    const parsed = options.schema.safeParse(json);
    if (!parsed.success) {
      const issue = parsed.error.issues[0];
      const where =
        issue === undefined ? '' : ` (${issue.path.map(String).join('.')}: ${issue.message})`;
      throw new SourceError(
        'bad_response',
        `The backend's answer to ${method} ${path} does not match the API contract this app ` +
          `was built for${where}.`,
        { status: response.status, details: parsed.error.issues },
      );
    }
    return parsed.data;
  }

  private async requestList<T>(
    path: string,
    item: ZodType<T>,
    names: readonly string[],
  ): Promise<T[]> {
    const raw = await this.request<unknown>('GET', path);
    const list = unwrapList(raw, names);
    if (list === null) {
      throw new SourceError('bad_response', `The backend's answer to GET ${path} is not a list.`);
    }
    const out: T[] = [];
    list.forEach((value, index) => {
      const parsed = item.safeParse(value);
      if (!parsed.success) {
        const issue = parsed.error.issues[0];
        const where =
          issue === undefined ? '' : `${issue.path.map(String).join('.')}: ${issue.message}`;
        throw new SourceError(
          'bad_response',
          `The backend's answer to GET ${path} does not match the API contract (item ${index}: ${where}).`,
        );
      }
      out.push(parsed.data);
    });
    return out;
  }

  // ---- AnalysisSource -----------------------------------------------------------------------

  async load(): Promise<Workspace> {
    const [analysis, profile, shortlist, decisions] = await Promise.all([
      this.request('GET', '/api/analysis', { schema: analysisSchema }),
      this.request('GET', '/api/profile', { schema: profileSchema }),
      this.requestList('/api/shortlist', shortlistEntrySchema, ['entries', 'shortlist', 'items']),
      this.requestList('/api/merge-decisions', decisionSchema, ['decisions', 'items']),
    ]);
    const datasets = summarizeDatasets(analysis);
    const entries: ShortlistEntry[] = shortlist.map((entry) => ({
      company_id: entry.company_id,
      name: entry.name,
      note: entry.note,
      added_at: entry.added_at,
    }));
    const records: DecisionRecord[] = decisions.map((d) => ({
      id: d.id ?? `${d.a_key}|${d.b_key}`,
      a_key: d.a_key,
      b_key: d.b_key,
      decision: d.decision,
    }));
    return {
      mode: 'connected',
      analysis,
      profile,
      decisions: records,
      shortlist: entries,
      datasets,
      has_sample_data: datasets.some((d) => d.synthetic),
      notices: [],
    };
  }

  async setProfile(profile: Profile): Promise<void> {
    await this.request('PUT', '/api/profile', {
      body: {
        include_keywords: profile.include_keywords,
        exclude_keywords: profile.exclude_keywords,
      },
      schema: profileSchema,
    });
  }

  async importCsv(datasetLabel: string, csvText: string): Promise<ImportReport> {
    const response: RawResponse = await this.send('POST', '/api/imports/csv', {
      body: { dataset_label: datasetLabel, csv_text: csvText },
    });
    if (!response.ok) {
      const error = this.failure(response);
      if (error.kind === 'api' && error.code === 'invalid_csv') {
        return {
          dataset_label: datasetLabel.trim(),
          ok: false,
          file_error: { code: 'invalid_csv', message: error.message },
          accepted: 0,
          rejected: 0,
          errors: [],
          warnings: [],
          rejected_rows: [],
        };
      }
      throw error;
    }
    let json: unknown;
    try {
      json = JSON.parse(response.text);
    } catch (cause) {
      throw new SourceError(
        'bad_response',
        'The backend answered the import with something that is not JSON.',
        { cause },
      );
    }
    const parsed = importResultSchema.safeParse(json);
    if (!parsed.success) {
      throw new SourceError(
        'bad_response',
        'The backend answered the import in a shape that does not match the API contract.',
      );
    }
    const result = parsed.data;
    const errors = result.errors.map((e) => ({
      line: e.line,
      ...(e.field === null || e.field === undefined ? {} : { field: e.field }),
      message: e.message,
    }));
    // The API reports lines and messages but not the rejected rows' values. The same pure
    // validator is available here, so re-derive the values of exactly the lines the backend
    // rejected; the in-place correction form needs them.
    const rejectedLines = new Set(errors.map((e) => e.line));
    const local = engineImportCsv(csvText, {
      dataset_label: result.dataset_label,
      imported_at: this.clock(),
    });
    return {
      dataset_label: result.dataset_label,
      ok: true,
      file_error: null,
      accepted: result.accepted,
      rejected: result.rejected,
      errors,
      warnings: result.warnings,
      rejected_rows: local.rejected_rows.filter((row) => rejectedLines.has(row.line)),
    };
  }

  async addManualPosting(values: PostingFormValues): Promise<SubmitResult> {
    const trimmed: Record<string, string> = {};
    for (const [field, value] of Object.entries(values)) trimmed[field] = value.trim();
    const validated = validateImportRow(trimmed, this.clock());
    if (!validated.ok) return { ok: false, problems: validated.errors };
    const { posting } = validated;
    try {
      await this.request('POST', '/api/postings', {
        body: {
          dataset_label: 'manual',
          company_name: posting.company_name,
          title: posting.title,
          location: posting.location,
          work_mode: posting.work_mode,
          department: posting.department,
          url: posting.url,
          posted_at: posting.posted_at,
          source_posting_id: posting.source_posting_id,
        },
        expect: 'none',
      });
    } catch (error) {
      if (error instanceof SourceError && error.kind === 'api' && error.status === 422) {
        return { ok: false, problems: [{ field: 'form', message: error.message }] };
      }
      throw error;
    }
    return { ok: true };
  }

  async decide(aKey: string, bKey: string, decision: DecisionKind): Promise<void> {
    await this.request('POST', '/api/merge-decisions', {
      body: { a_key: aKey, b_key: bKey, decision },
      expect: 'none',
    });
  }

  async undoDecision(id: string): Promise<void> {
    await this.request('DELETE', `/api/merge-decisions/${encodeURIComponent(id)}`, {
      expect: 'none',
    });
  }

  async setShortlisted(companyId: string, shortlisted: boolean, note?: string): Promise<void> {
    await this.request('PUT', `/api/companies/${encodeURIComponent(companyId)}/shortlist`, {
      body: note === undefined ? { shortlisted } : { shortlisted, note },
      expect: 'none',
    });
  }

  async exportShortlistCsv(): Promise<string> {
    return this.request<string>('GET', '/api/shortlist/export.csv', { expect: 'text' });
  }

  exportPostingsCsv(): Promise<string> {
    return Promise.reject(unavailable('Exporting stored postings per dataset'));
  }

  loadSample(): Promise<{ datasets: number; postings: number; keywordsAdded: boolean }> {
    return Promise.reject(unavailable('Loading sample data'));
  }

  removeDataset(): Promise<void> {
    return Promise.reject(unavailable('Removing a single dataset'));
  }

  async eraseAll(): Promise<void> {
    await this.request('DELETE', '/api/data', {
      query: { confirm: 'erase-all' },
      expect: 'none',
    });
  }

  // ---- ATS sources --------------------------------------------------------------------------

  private buildSources(): AtsSources {
    const toSource = (raw: ReturnType<typeof atsSourceSchema.parse>): AtsSource => ({
      id: raw.id,
      provider: raw.provider,
      token: raw.token,
      company_name: raw.company_name,
      last_run: raw.last_run ?? raw.latest_run ?? raw.last_refresh ?? null,
    });
    return {
      list: async () => {
        const rows = await this.requestList('/api/sources', atsSourceSchema, ['sources', 'items']);
        return rows.map(toSource);
      },
      add: async (input: NewAtsSource) => {
        if (!TOKEN_PATTERN.test(input.token)) {
          throw new SourceError(
            'invalid_input',
            'The board token may only contain letters, digits, dot, underscore and hyphen (1 to 100 characters).',
            { code: 'invalid_token' },
          );
        }
        const created = await this.request('POST', '/api/sources', {
          body: {
            provider: input.provider,
            token: input.token,
            company_name: input.company_name,
          },
          schema: atsSourceSchema,
        });
        return toSource(created);
      },
      remove: async (id: string) => {
        await this.request('DELETE', `/api/sources/${encodeURIComponent(id)}`, { expect: 'none' });
      },
      refresh: async (id: string): Promise<RefreshRun> =>
        this.request('POST', `/api/sources/${encodeURIComponent(id)}/refresh`, {
          schema: refreshRunSchema,
          timeoutMs: this.refreshTimeoutMs,
        }),
      runs: async (id: string): Promise<RefreshRun[]> =>
        this.requestList(`/api/sources/${encodeURIComponent(id)}/runs`, refreshRunSchema, [
          'runs',
          'items',
          'history',
        ]),
    };
  }
}
