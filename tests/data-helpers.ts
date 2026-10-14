import { MemoryStorage, type StorageLike } from '../src/data/storage';

export const NOW = '2026-10-13T12:00:00Z';

/** A settable clock that returns UTC timestamps in the engine's wire format. */
export function makeClock(start: string = NOW) {
  let current = Date.parse(start);
  const clock = () => new Date(current).toISOString().replace(/\.\d{3}Z$/, 'Z');
  return Object.assign(clock, {
    advance(seconds: number) {
      current += seconds * 1000;
    },
    set(timestamp: string) {
      current = Date.parse(timestamp);
    },
  });
}

/** Storage that fails writes with a quota error once `armed`. */
export class QuotaStorage extends MemoryStorage {
  armed = false;
  override setItem(key: string, value: string): void {
    if (this.armed) {
      const error = new Error('quota') as Error & { name: string };
      error.name = 'QuotaExceededError';
      throw error;
    }
    super.setItem(key, value);
  }
}

/** Storage whose every call throws (blocked site data). */
export class BlockedStorage implements StorageLike {
  getItem(): string | null {
    throw new Error('SecurityError');
  }
  setItem(): void {
    throw new Error('SecurityError');
  }
  removeItem(): void {
    throw new Error('SecurityError');
  }
}

export const CSV_HEADER = 'company_name,title,location,work_mode,department,url,posted_at';

export function csv(...rows: string[]): string {
  return [CSV_HEADER, ...rows].join('\r\n') + '\r\n';
}

export const FORM_DEFAULTS = {
  company_name: '',
  title: '',
  location: '',
  work_mode: '',
  department: '',
  url: '',
  posted_at: '',
  source_posting_id: '',
};
