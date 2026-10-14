import { describe, expect, it } from 'vitest';
import {
  checkBackend,
  DEFAULT_BACKEND_URL,
  isLoopbackHost,
  shouldProbeBackend,
  validateBackendUrl,
} from '../src/data/connection';
import { makeClock } from './data-helpers';

describe('validateBackendUrl', () => {
  it('accepts http and https and normalises the result', () => {
    expect(validateBackendUrl('http://127.0.0.1:8787')).toEqual({
      ok: true,
      url: 'http://127.0.0.1:8787',
    });
    expect(validateBackendUrl('  https://rr.example.org/base/  ')).toEqual({
      ok: true,
      url: 'https://rr.example.org/base',
    });
    expect(validateBackendUrl('http://localhost:8787/')).toEqual({
      ok: true,
      url: 'http://localhost:8787',
    });
    expect(DEFAULT_BACKEND_URL).toBe('http://127.0.0.1:8787');
  });

  it.each([
    ['', 'Enter the backend address'],
    ['localhost:8787', 'http:// or https://'],
    ['ftp://example.org', 'http:// or https://'],
    ['javascript:alert(1)', 'http:// or https://'],
    ['file:///etc/passwd', 'http:// or https://'],
    ['http://user:pw@example.org', 'user name or password'],
    ['http://example.org/?x=1', 'query or fragment'],
    ['http://example.org/#frag', 'query or fragment'],
    ['not a url', 'valid address'],
  ])('rejects %j', (input, fragment) => {
    const result = validateBackendUrl(input);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.message).toContain(fragment);
  });
});

describe('probe policy', () => {
  it('recognises loopback hosts only', () => {
    for (const host of ['localhost', '127.0.0.1', '[::1]', '::1', 'app.localhost', '127.4.5.6']) {
      expect(isLoopbackHost(host)).toBe(true);
    }
    for (const host of ['example.github.io', '192.168.1.5', 'localhost.evil.com', '10.0.0.1']) {
      expect(isLoopbackHost(host)).toBe(false);
    }
  });

  it('never probes on its own from a public page, and always when the user chose it', () => {
    expect(shouldProbeBackend('auto', 'user.github.io')).toBe(false);
    expect(shouldProbeBackend('auto', null)).toBe(false);
    expect(shouldProbeBackend('auto', 'localhost')).toBe(true);
    expect(shouldProbeBackend('auto', '127.0.0.1')).toBe(true);
    expect(shouldProbeBackend('connected', 'user.github.io')).toBe(true);
    expect(shouldProbeBackend('local', 'localhost')).toBe(false);
  });
});

describe('checkBackend', () => {
  const clock = makeClock();
  const health = { status: 'ok', schema_version: 1, app_version: '0.1.0', db_ok: true };

  it('reports ok with versions', async () => {
    const result = await checkBackend('http://127.0.0.1:8787', {
      clock,
      fetchImpl: () => Promise.resolve(new Response(JSON.stringify(health))),
    });
    expect(result).toMatchObject({ state: 'ok', app_version: '0.1.0', schema_version: 1 });
  });

  it('reports offline when nothing answers', async () => {
    const result = await checkBackend('http://127.0.0.1:8787', {
      clock,
      fetchImpl: () => Promise.reject(new TypeError('Failed to fetch')),
    });
    expect(result).toMatchObject({ state: 'offline', kind: 'offline' });
  });

  it('reports a CORS failure when a no-cors probe is answered', async () => {
    const result = await checkBackend('http://127.0.0.1:8787', {
      clock,
      fetchImpl: (_url, init) =>
        init?.mode === 'no-cors'
          ? Promise.resolve(new Response(null))
          : Promise.reject(new TypeError('Failed to fetch')),
    });
    expect(result).toMatchObject({ state: 'offline', kind: 'cors' });
  });

  it('reports a timeout', async () => {
    const result = await checkBackend('http://127.0.0.1:8787', {
      clock,
      timeoutMs: 20,
      fetchImpl: (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new Error('aborted')));
        }),
    });
    expect(result).toMatchObject({ state: 'offline', kind: 'timeout' });
  });

  it('reports an HTTP error, a non-health answer and an unhealthy database', async () => {
    const answer = (body: string, status = 200) => ({
      clock,
      fetchImpl: () => Promise.resolve(new Response(body, { status })),
    });
    expect(await checkBackend('http://x.test', answer('', 503))).toMatchObject({ kind: 'http' });
    expect(await checkBackend('http://x.test', answer('<html></html>'))).toMatchObject({
      kind: 'bad_response',
    });
    expect(await checkBackend('http://x.test', answer('{}'))).toMatchObject({
      kind: 'bad_response',
    });
    expect(
      await checkBackend('http://x.test', answer(JSON.stringify({ ...health, db_ok: false }))),
    ).toMatchObject({ kind: 'unhealthy' });
  });
});
