import { describe, expect, it } from 'vitest';
import {
  daysBetweenSeconds,
  daysFromCivil,
  floorDiv,
  isLeapYear,
  parseDate,
  parseTimestamp,
  roundHalfUp,
} from '../src/engine/time';
import { mulberry32 } from './helpers';

describe('parseDate', () => {
  it('accepts real calendar dates', () => {
    expect(parseDate('1970-01-01')).toBe(0);
    expect(parseDate('2026-10-13')).toBe(Date.UTC(2026, 9, 13) / 1000);
    expect(parseDate('2024-02-29')).not.toBeNull();
    expect(parseDate('2000-02-29')).not.toBeNull();
    expect(parseDate('0001-01-01')).not.toBeNull();
    expect(parseDate('9999-12-31')).not.toBeNull();
  });

  it('rejects impossible and malformed dates', () => {
    for (const text of [
      '2026-02-30',
      '2026-02-29',
      '2100-02-29',
      '2026-13-01',
      '2026-00-10',
      '2026-04-31',
      '2026-1-1',
      '26-01-01',
      '2026/01/01',
      '2026-01-01T00:00:00Z',
      ' 2026-01-01',
      '0000-01-01',
      '',
      '２０２６-01-01',
    ]) {
      expect(parseDate(text), text).toBeNull();
    }
  });
});

describe('parseTimestamp', () => {
  it('accepts UTC instants and matches Date.UTC', () => {
    expect(parseTimestamp('1970-01-01T00:00:00Z')).toBe(0);
    expect(parseTimestamp('2026-10-13T12:00:00Z')).toBe(Date.UTC(2026, 9, 13, 12) / 1000);
    expect(parseTimestamp('2026-10-13T23:59:59Z')).toBe(Date.UTC(2026, 9, 13, 23, 59, 59) / 1000);
  });

  it('rejects other shapes and impossible times', () => {
    for (const text of [
      '2026-10-13T24:00:00Z',
      '2026-10-13T12:60:00Z',
      '2026-10-13T12:00:60Z',
      '2026-02-30T12:00:00Z',
      '2026-10-13 12:00:00Z',
      '2026-10-13T12:00:00',
      '2026-10-13T12:00:00+00:00',
      '2026-10-13T12:00:00.000Z',
      '2026-10-13T12:00Z',
      '2026-10-13',
      '',
    ]) {
      expect(parseTimestamp(text), text).toBeNull();
    }
  });

  it('agrees with Date.UTC on 500 seeded random instants', () => {
    const random = mulberry32(99);
    for (let i = 0; i < 500; i += 1) {
      const ms = Math.floor(random() * 4_000_000_000_000) - 1_000_000_000_000;
      const iso = new Date(ms - (ms % 1000)).toISOString().replace(/\.\d{3}Z$/, 'Z');
      const year = Number(iso.slice(0, 4));
      if (!(year >= 1 && year <= 9999) || iso.startsWith('-') || iso.startsWith('+')) continue;
      expect(parseTimestamp(iso), iso).toBe(Date.parse(iso) / 1000);
    }
  });

  it('is correct for years below 100, which Date.UTC remaps', () => {
    expect(daysFromCivil(1, 1, 1)).toBe(-719162);
    expect(parseDate('0099-03-01')).toBe(daysFromCivil(99, 3, 1) * 86400);
    expect(isLeapYear(100)).toBe(false);
    expect(isLeapYear(400)).toBe(true);
  });
});

describe('integer helpers', () => {
  it('floorDiv floors toward negative infinity', () => {
    expect(floorDiv(7, 2)).toBe(3);
    expect(floorDiv(-7, 2)).toBe(-4);
    expect(floorDiv(-86400, 86400)).toBe(-1);
    expect(floorDiv(-1, 86400)).toBe(-1);
    expect(floorDiv(0, 5)).toBe(0);
  });

  it('daysBetweenSeconds floors whole days', () => {
    expect(daysBetweenSeconds(0, 86399)).toBe(0);
    expect(daysBetweenSeconds(0, 86400)).toBe(1);
    expect(daysBetweenSeconds(0, 86400 * 45 - 1)).toBe(44);
    expect(daysBetweenSeconds(86400, 0)).toBe(-1);
    expect(daysBetweenSeconds(100, 99)).toBe(-1);
  });

  it('roundHalfUp is floor((2n + d) / 2d)', () => {
    expect(roundHalfUp(1, 2)).toBe(1); // 0.5 rounds up
    expect(roundHalfUp(1, 3)).toBe(0);
    expect(roundHalfUp(2, 3)).toBe(1);
    expect(roundHalfUp(2000, 3)).toBe(667);
    expect(roundHalfUp(1000, 3)).toBe(333);
    expect(roundHalfUp(52000, 53)).toBe(981);
    expect(roundHalfUp(0, 7)).toBe(0);
    expect(roundHalfUp(7, 7)).toBe(1);
  });
});
