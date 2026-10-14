/**
 * Safe, versioned persistence on top of `localStorage` (or anything shaped like it).
 *
 * Rules every caller relies on:
 *  - reading never throws: unavailable storage, bad JSON and schema violations are *outcomes*;
 *  - an unreadable value is never silently discarded: the raw text is copied to a backup key first;
 *  - data written by a NEWER schema is never overwritten (`status: 'newer'`);
 *  - writes report quota/unavailability instead of pretending to succeed.
 */
import type { ZodType } from 'zod';
import { SourceError } from './errors';

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** In-memory storage: used by tests and as the fallback when the browser blocks storage. */
export class MemoryStorage implements StorageLike {
  private readonly items = new Map<string, string>();
  getItem(key: string): string | null {
    return this.items.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.items.set(key, value);
  }
  removeItem(key: string): void {
    this.items.delete(key);
  }
  keys(): string[] {
    return Array.from(this.items.keys());
  }
}

/**
 * The browser's `localStorage`, or null when it is missing or blocked (private mode, disabled
 * site data, sandboxed iframe). Probed with a real write because some browsers only fail there.
 */
export function browserStorage(): StorageLike | null {
  try {
    if (typeof window === 'undefined') return null;
    const storage = window.localStorage;
    const probe = '__recruit_radar_probe__';
    storage.setItem(probe, '1');
    storage.removeItem(probe);
    return storage;
  } catch {
    return null;
  }
}

/** True for the many spellings of "the storage quota is exhausted". */
export function isQuotaError(error: unknown): boolean {
  if (typeof error !== 'object' || error === null) return false;
  const { name, code } = error as { name?: unknown; code?: unknown };
  return (
    name === 'QuotaExceededError' ||
    name === 'NS_ERROR_DOM_QUOTA_REACHED' ||
    code === 22 ||
    code === 1014
  );
}

export type VersionedRead<T> =
  | { status: 'empty' }
  | { status: 'ok'; data: T; raw: string }
  | { status: 'newer'; found: number; raw: string }
  | { status: 'corrupt'; reason: string; raw: string }
  | { status: 'unavailable'; reason: string };

export interface VersionedSpec<T> {
  /** Highest schema version this build understands (and the one it writes). */
  current: number;
  /** `migrations[v]` upgrades a version-`v` object to version `v + 1`. */
  migrations?: Readonly<
    Record<number, (value: Record<string, unknown>) => Record<string, unknown>>
  >;
  schema: ZodType<T>;
}

function describeIssues(error: {
  issues: ReadonlyArray<{ path: PropertyKey[]; message: string }>;
}) {
  const first = error.issues[0];
  if (first === undefined) return 'does not match the expected shape';
  const path = first.path.map(String).join('.');
  return path === '' ? first.message : `${path}: ${first.message}`;
}

/** Read, parse, migrate and validate a stored object that carries `schema_version`. */
export function readVersioned<T>(
  storage: StorageLike,
  key: string,
  spec: VersionedSpec<T>,
): VersionedRead<T> {
  let raw: string | null;
  try {
    raw = storage.getItem(key);
  } catch (error) {
    return {
      status: 'unavailable',
      reason: error instanceof Error ? error.message : 'storage is not available',
    };
  }
  if (raw === null) return { status: 'empty' };

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { status: 'corrupt', reason: 'the stored text is not valid JSON', raw };
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { status: 'corrupt', reason: 'the stored value is not an object', raw };
  }
  let value = parsed as Record<string, unknown>;
  const version = value.schema_version;
  if (typeof version !== 'number' || !Number.isInteger(version) || version < 1) {
    return { status: 'corrupt', reason: 'the stored value has no valid schema_version', raw };
  }
  if (version > spec.current) return { status: 'newer', found: version, raw };

  let at = version;
  while (at < spec.current) {
    const migrate = spec.migrations?.[at];
    if (migrate === undefined) {
      return { status: 'corrupt', reason: `no migration from schema ${at}`, raw };
    }
    try {
      value = { ...migrate(value), schema_version: at + 1 };
    } catch {
      return { status: 'corrupt', reason: `migration from schema ${at} failed`, raw };
    }
    at += 1;
  }

  const result = spec.schema.safeParse(value);
  if (!result.success) {
    return { status: 'corrupt', reason: describeIssues(result.error), raw };
  }
  return { status: 'ok', data: result.data, raw };
}

/**
 * Write text to storage, translating failures into `SourceError`. The previous value is left
 * untouched when the write fails (the platform's `setItem` is all-or-nothing).
 */
export function writeText(storage: StorageLike, key: string, text: string): void {
  try {
    storage.setItem(key, text);
  } catch (error) {
    if (isQuotaError(error)) {
      throw new SourceError(
        'storage_full',
        'Browser storage is full, so this change was not saved. Remove a dataset, export your ' +
          'data, or erase data you no longer need, then try again.',
        { cause: error },
      );
    }
    throw new SourceError(
      'storage_unavailable',
      'Browser storage is not available, so this change could not be saved.',
      { cause: error },
    );
  }
}

/** Remove a key; never throws. Returns false when storage refused. */
export function removeKey(storage: StorageLike, key: string): boolean {
  try {
    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

/** Best-effort copy of unreadable raw text to a backup key. Returns whether it was kept. */
export function backupRaw(storage: StorageLike, backupKey: string, raw: string): boolean {
  try {
    storage.setItem(backupKey, raw);
    return true;
  } catch {
    return false;
  }
}
