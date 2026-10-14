/**
 * Locale-independent formatting. Dates are shown as UTC ISO dates so what is on screen, in the
 * CSV export and in test expectations never depends on the viewer's time zone or locale.
 */
import { daysBetweenSeconds, parseTimestamp } from '../engine';

export const EM_DASH = '—';

export function plural(count: number, singular: string, pluralForm?: string): string {
  return `${count} ${count === 1 ? singular : (pluralForm ?? `${singular}s`)}`;
}

/** `2026-10-13` from a timestamp or date; an em dash for null. */
export function dateOf(value: string | null): string {
  if (value === null || value === '') return EM_DASH;
  return value.slice(0, 10);
}

/** `2026-10-13 12:00 UTC` */
export function dateTimeOf(value: string | null): string {
  if (value === null || value === '') return EM_DASH;
  return `${value.slice(0, 10)} ${value.slice(11, 16)} UTC`;
}

/** Whole days from `from` to `to` (both engine timestamps); null when either is unusable. */
export function daysBetween(from: string | null, to: string): number | null {
  if (from === null) return null;
  const a = parseTimestamp(from);
  const b = parseTimestamp(to);
  if (a === null || b === null) return null;
  return Math.max(0, daysBetweenSeconds(a, b));
}

/** "today", "1 day ago", "12 days ago". */
export function agoText(days: number | null): string {
  if (days === null) return EM_DASH;
  if (days === 0) return 'today';
  return `${plural(days, 'day')} ago`;
}

/** 0..1000 -> "64.0"; null -> "Not scored". */
export function scoreText(score: number | null): string {
  if (score === null) return 'Not scored';
  return `${Math.floor(score / 10)}.${score % 10}`;
}

/** A 0..1000 component value on the same scale: "66.7", or an em dash when missing. */
export function valueText(value: number | null): string {
  if (value === null) return EM_DASH;
  return `${Math.floor(value / 10)}.${value % 10}`;
}

/** Only http(s) URLs become links (spec 05 build-time safety); anything else stays text. */
export function safeLink(url: string | null): string | null {
  if (url === null) return null;
  if (!/^https?:\/\/[^\s/?#]/iu.test(url)) return null;
  for (let index = 0; index < url.length; index += 1) {
    const code = url.charCodeAt(index);
    if (code <= 0x1f || (code >= 0x7f && code <= 0x9f)) return null;
  }
  return url;
}

export function fileDate(timestamp: string): string {
  return timestamp.slice(0, 10);
}

/** `careers.example.com/acme/jobs/1` — a link's visible text, never longer than `max`. */
export function shortUrl(url: string, max = 44): string {
  const bare = url.replace(/^https?:\/\//iu, '').replace(/\/$/u, '');
  return bare.length <= max ? bare : `${bare.slice(0, max - 1)}…`;
}

/** `12.4 KB`, `1.0 MB`. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
