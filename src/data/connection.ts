/**
 * Connection manager helpers: backend URL validation, the health check, and the policy that
 * decides when the app may talk to a backend at all.
 *
 * Policy (documented in the About/Settings copy): a page served from a public host never probes
 * `127.0.0.1` on its own. Only pages served from this machine (dev server, preview, e2e) probe
 * automatically; anywhere else the user opts in from Settings.
 */
import { systemClock, type Clock } from './clock';
import { healthSchema } from './remoteSchemas';
import type { ModePreference } from './types';

export const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8787';
export const HEALTH_TIMEOUT_MS = 4000;

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

/** `fetch` bound so it never loses its `this` (browsers throw "Illegal invocation"). */
export function defaultFetch(): FetchLike {
  return (input, init) => fetch(input, init);
}

// ---------------------------------------------------------------------------------------------
// URL validation
// ---------------------------------------------------------------------------------------------

export type BackendUrlCheck = { ok: true; url: string } | { ok: false; message: string };

/**
 * Accept only an absolute http(s) URL. The result is normalised to `scheme://host[:port][/path]`
 * with no trailing slash, so `url + '/api/health'` is always well formed.
 */
export function validateBackendUrl(input: string): BackendUrlCheck {
  const value = input.trim();
  if (value === '')
    return { ok: false, message: 'Enter the backend address, for example http://127.0.0.1:8787.' };
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return {
      ok: false,
      message:
        'This is not a valid address. Start with http:// or https://, for example http://127.0.0.1:8787.',
    };
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return { ok: false, message: 'The backend address must start with http:// or https://.' };
  }
  if (parsed.hostname === '')
    return { ok: false, message: 'The backend address needs a host name.' };
  if (parsed.username !== '' || parsed.password !== '') {
    return { ok: false, message: 'The backend address must not contain a user name or password.' };
  }
  if (parsed.search !== '' || parsed.hash !== '') {
    return { ok: false, message: 'The backend address must not contain a query or fragment.' };
  }
  const path = parsed.pathname.replace(/\/+$/u, '');
  return { ok: true, url: `${parsed.protocol}//${parsed.host}${path}` };
}

export function isLoopbackHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/gu, '');
  return (
    host === 'localhost' ||
    host.endsWith('.localhost') ||
    host === '::1' ||
    /^127(?:\.\d{1,3}){3}$/u.test(host)
  );
}

/** May the app contact the backend without the user asking? */
export function shouldProbeBackend(
  preference: ModePreference,
  pageHostname: string | null,
): boolean {
  if (preference === 'local') return false;
  if (preference === 'connected') return true;
  return pageHostname !== null && isLoopbackHost(pageHostname);
}

// ---------------------------------------------------------------------------------------------
// Timed requests
// ---------------------------------------------------------------------------------------------

export class RequestTimeout extends Error {
  constructor(readonly timeoutMs: number) {
    super(`The request did not finish within ${Math.round(timeoutMs / 1000)} seconds.`);
    this.name = 'RequestTimeout';
  }
}

export interface RawResponse {
  status: number;
  ok: boolean;
  headers: Headers;
  text: string;
}

/** One request whose whole lifetime (headers and body) is bounded by `timeoutMs`. */
export async function timedRequest(
  fetchImpl: FetchLike,
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<RawResponse> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const response = await fetchImpl(url, { ...init, signal: controller.signal });
    const text = await response.text();
    return { status: response.status, ok: response.ok, headers: response.headers, text };
  } catch (error) {
    if (timedOut) throw new RequestTimeout(timeoutMs);
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * A failed `fetch` looks the same whether the server is down or the browser refused to expose a
 * cross-origin answer. A `no-cors` request settles it: it resolves (opaque) iff something
 * answered.
 */
export async function classifyNetworkFailure(
  fetchImpl: FetchLike,
  url: string,
  timeoutMs = HEALTH_TIMEOUT_MS,
): Promise<'cors' | 'offline'> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    await fetchImpl(url, {
      method: 'GET',
      mode: 'no-cors',
      cache: 'no-store',
      credentials: 'omit',
      signal: controller.signal,
    });
    return 'cors';
  } catch {
    return 'offline';
  } finally {
    clearTimeout(timer);
  }
}

export function pageOrigin(): string | null {
  try {
    const origin = globalThis.location?.origin;
    return typeof origin === 'string' && origin !== 'null' ? origin : null;
  } catch {
    return null;
  }
}

export function offlineMessage(baseUrl: string): string {
  return (
    `Cannot reach the backend at ${baseUrl}. It may not be running, or the browser blocked the ` +
    `request (for example a secure page calling an insecure address).`
  );
}

export function corsMessage(baseUrl: string): string {
  const origin = pageOrigin();
  return (
    `The backend at ${baseUrl} answered, but its CORS settings do not allow this page` +
    (origin === null ? '' : ` (${origin})`) +
    `. Add this origin to RECRUIT_RADAR_CORS_ORIGINS and restart the backend.`
  );
}

// ---------------------------------------------------------------------------------------------
// Health check
// ---------------------------------------------------------------------------------------------

export type OfflineKind = 'offline' | 'cors' | 'timeout' | 'bad_response' | 'http' | 'unhealthy';

export type HealthState =
  | { state: 'unchecked' }
  | { state: 'checking' }
  | {
      state: 'ok';
      app_version: string | null;
      schema_version: string | number | null;
      checked_at: string;
    }
  | { state: 'offline'; kind: OfflineKind; message: string; checked_at: string };

export type HealthResult = Extract<HealthState, { state: 'ok' | 'offline' }>;

export interface HealthCheckOptions {
  fetchImpl?: FetchLike;
  timeoutMs?: number;
  clock?: Clock;
}

/** `GET <baseUrl>/api/health`, classified into ok / offline / CORS / timeout / bad response. */
export async function checkBackend(
  baseUrl: string,
  options: HealthCheckOptions = {},
): Promise<HealthResult> {
  const fetchImpl = options.fetchImpl ?? defaultFetch();
  const clock = options.clock ?? systemClock;
  const timeoutMs = options.timeoutMs ?? HEALTH_TIMEOUT_MS;
  const url = `${baseUrl}/api/health`;
  const offline = (kind: OfflineKind, message: string): HealthResult => ({
    state: 'offline',
    kind,
    message,
    checked_at: clock(),
  });

  let response: RawResponse;
  try {
    response = await timedRequest(
      fetchImpl,
      url,
      {
        method: 'GET',
        headers: { Accept: 'application/json' },
        cache: 'no-store',
        credentials: 'omit',
      },
      timeoutMs,
    );
  } catch (error) {
    if (error instanceof RequestTimeout) {
      return offline(
        'timeout',
        `The backend at ${baseUrl} did not answer within ${Math.round(timeoutMs / 1000)} seconds.`,
      );
    }
    const kind = await classifyNetworkFailure(fetchImpl, url, timeoutMs);
    return offline(kind, kind === 'cors' ? corsMessage(baseUrl) : offlineMessage(baseUrl));
  }

  if (!response.ok) {
    return offline(
      'http',
      `The backend at ${baseUrl} answered HTTP ${response.status} on /api/health.`,
    );
  }
  let json: unknown;
  try {
    json = JSON.parse(response.text);
  } catch {
    return offline(
      'bad_response',
      `The address ${baseUrl} answered, but not with the RecruitRadar health response.`,
    );
  }
  const parsed = healthSchema.safeParse(json);
  if (!parsed.success) {
    return offline(
      'bad_response',
      `The address ${baseUrl} answered, but not with the RecruitRadar health response.`,
    );
  }
  if (parsed.data.db_ok === false) {
    return offline(
      'unhealthy',
      `The backend at ${baseUrl} is running but reports that its database is not usable.`,
    );
  }
  return {
    state: 'ok',
    app_version: parsed.data.app_version ?? null,
    schema_version: parsed.data.schema_version ?? null,
    checked_at: clock(),
  };
}
