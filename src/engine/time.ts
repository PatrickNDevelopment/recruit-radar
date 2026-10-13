/**
 * Calendar and day arithmetic (spec 02 §1). Everything is integer arithmetic on epoch seconds;
 * nothing here reads the clock, the locale or the time zone.
 */

export const SECONDS_PER_DAY = 86400;

const MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31] as const;

export function isLeapYear(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

export function daysInMonth(year: number, month: number): number {
  if (month === 2 && isLeapYear(year)) return 29;
  return MONTH_DAYS[month - 1] ?? 0;
}

/** Floor division for integers (exact; correct for negative numerators). */
export function floorDiv(numerator: number, denominator: number): number {
  const remainder = ((numerator % denominator) + denominator) % denominator;
  return (numerator - remainder) / denominator;
}

/**
 * Days since 1970-01-01 of a proleptic-Gregorian civil date (Hinnant's `days_from_civil`).
 * Works for every year, including 1..99 which `Date.UTC` would silently remap to 19xx.
 */
export function daysFromCivil(year: number, month: number, day: number): number {
  const y = month <= 2 ? year - 1 : year;
  const era = floorDiv(y, 400);
  const yearOfEra = y - era * 400;
  const shiftedMonth = month > 2 ? month - 3 : month + 9;
  const dayOfYear = floorDiv(153 * shiftedMonth + 2, 5) + day - 1;
  const dayOfEra = yearOfEra * 365 + floorDiv(yearOfEra, 4) - floorDiv(yearOfEra, 100) + dayOfYear;
  return era * 146097 + dayOfEra - 719468;
}

const DATE_RE = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/;
const TIMESTAMP_RE = /^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z$/;

function isRealDate(year: number, month: number, day: number): boolean {
  // Year 0000 is rejected: Python's `datetime.date` has no year 0, and the two engines must agree.
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= daysInMonth(year, month);
}

/** `YYYY-MM-DD` -> epoch seconds at 00:00:00Z, or null when malformed / not a real date. */
export function parseDate(text: string): number | null {
  const m = DATE_RE.exec(text);
  if (m === null) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  if (!isRealDate(year, month, day)) return null;
  return daysFromCivil(year, month, day) * SECONDS_PER_DAY;
}

/** `YYYY-MM-DDTHH:MM:SSZ` -> epoch seconds, or null when malformed / not a real UTC instant. */
export function parseTimestamp(text: string): number | null {
  const m = TIMESTAMP_RE.exec(text);
  if (m === null) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const hour = Number(m[4]);
  const minute = Number(m[5]);
  const second = Number(m[6]);
  if (!isRealDate(year, month, day) || hour > 23 || minute > 59 || second > 59) return null;
  return daysFromCivil(year, month, day) * SECONDS_PER_DAY + hour * 3600 + minute * 60 + second;
}

/** `days_between(a, b) = floor((epoch(b) - epoch(a)) / 86400)` on epoch seconds. */
export function daysBetweenSeconds(fromSeconds: number, toSeconds: number): number {
  return floorDiv(toSeconds - fromSeconds, SECONDS_PER_DAY);
}

/** `rhu(num, den) = floor((2*num + den) / (2*den))` — round half up for non-negative integers. */
export function roundHalfUp(numerator: number, denominator: number): number {
  return floorDiv(2 * numerator + denominator, 2 * denominator);
}
