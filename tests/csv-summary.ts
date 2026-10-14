/**
 * Shared by the CSV vector test and the CSV differential fuzz leg: turns an importCsv result into
 * the implementation-independent summary that contracts/vectors/csv-import.json is written in,
 * and expands the vectors' generated texts.
 */
import type { CsvImportResult } from '../src/engine/csv';

export type TextSpec =
  | string
  | { repeat: { head: string; row: string; count: number } }
  | { pad: { head: string; fill: string; total_bytes: number; bom: boolean } }
  | { parts: Array<string | { fill: string; count: number }> };

export interface CsvSummary {
  file_error: string | null;
  accepted: number;
  rejected: number;
  rows: Array<Array<string | null>>;
  errors: Array<[number, string | null]>;
  warnings: Array<[number, string]>;
}

export function expand(spec: TextSpec): string {
  if (typeof spec === 'string') return spec;
  if ('repeat' in spec) {
    const { head, row, count } = spec.repeat;
    let text = head;
    for (let i = 0; i < count; i += 1) text += row.replace('{i}', String(i));
    return text;
  }
  if ('pad' in spec) {
    const { head, fill, total_bytes, bom } = spec.pad;
    const prefix = `${bom ? '﻿' : ''}${head}`;
    const encoder = new TextEncoder();
    const remaining = total_bytes - encoder.encode(prefix).length;
    const unit = encoder.encode(fill).length;
    const count = Math.floor(remaining / unit);
    return prefix + fill.repeat(count) + 'x'.repeat(remaining - count * unit);
  }
  return spec.parts
    .map((part) => (typeof part === 'string' ? part : part.fill.repeat(part.count)))
    .join('');
}

function warningKind(message: string): string {
  if (message.includes('has no header name')) return 'blank_header';
  if (message.startsWith('Unknown column')) return 'unknown_column';
  if (message.startsWith('Same posting as')) return 'duplicate_row';
  if (message.includes('is after the import time')) return 'future_observed';
  throw new Error(`unclassified warning: ${message}`);
}

function compare(a: string | number, b: string | number): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Rows are in effective-instant order then file order; a blank observed_at reads as null. */
export function summarize(result: CsvImportResult, importedAt: string): CsvSummary {
  const rows = result.snapshots.flatMap((snapshot) =>
    snapshot.postings.map((p) => [
      snapshot.observed_at === importedAt ? null : snapshot.observed_at,
      p.company_name,
      p.title,
      p.location,
      p.work_mode,
      p.department,
      p.url,
      p.posted_at,
      p.source_posting_id,
    ]),
  );
  const unique = new Map<string, [number, string | null]>();
  for (const error of result.errors) {
    unique.set(`${error.line}\u0000${error.field ?? ''}`, [error.line, error.field ?? null]);
  }
  const errors = Array.from(unique.values()).sort(
    (a, b) => compare(a[0], b[0]) || compare(a[1] ?? '', b[1] ?? ''),
  );
  const warnings = result.warnings
    .map((warning): [number, string] => [warning.line, warningKind(warning.message)])
    .sort((a, b) => compare(a[0], b[0]) || compare(a[1], b[1]));
  return {
    file_error: result.file_error?.code ?? null,
    accepted: result.accepted,
    rejected: result.rejected,
    rows,
    errors,
    warnings,
  };
}
