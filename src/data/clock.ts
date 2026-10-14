/**
 * The engine never reads the clock; the data layer does, and only here. A `Clock` returns a UTC
 * timestamp in the engine's wire format (`YYYY-MM-DDTHH:MM:SSZ`, whole seconds).
 */
export type Clock = () => string;

export function toUtcTimestamp(date: Date): string {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export const systemClock: Clock = () => toUtcTimestamp(new Date());

/** `YYYY-MM-DD` of the given timestamp shifted back by `days` whole days (UTC). */
export function dateDaysBefore(timestamp: string, days: number): string {
  const ms = Date.parse(timestamp) - days * 86_400_000;
  return new Date(ms).toISOString().slice(0, 10);
}

/** The timestamp shifted back by `days` whole days (UTC). */
export function timestampDaysBefore(timestamp: string, days: number): string {
  return toUtcTimestamp(new Date(Date.parse(timestamp) - days * 86_400_000));
}
