/**
 * TypeScript leg of the CSV differential fuzz in `contracts/tools/fuzz_csv.py`. Skipped unless its
 * input file is named, so it is inert in the default test run.
 *
 *   RR_CSV_FUZZ_FILE=cases.json RR_CSV_FUZZ_OUT=ts.json npx vitest run tests/fuzz-csv.test.ts
 *   input  `{ imported_at, cases: [{ id, text }] }`
 *   output `{ results: { <id>: CsvSummary | { thrown } } }`
 *
 * This file never asserts equality with the Python importer: the Python driver compares.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { importCsv } from '../src/engine/csv';
import { summarize } from './csv-summary';

const FILE = process.env['RR_CSV_FUZZ_FILE'] ?? '';
const OUT = process.env['RR_CSV_FUZZ_OUT'] ?? `${FILE}.ts.json`;

interface FuzzFile {
  imported_at: string;
  cases: Array<{ id: string; text: string }>;
}

describe.skipIf(FILE === '')('CSV importer fuzz leg (needs RR_CSV_FUZZ_FILE)', () => {
  it('imports every case and writes the summaries', () => {
    const input = JSON.parse(readFileSync(FILE, 'utf8')) as FuzzFile;
    const results: Record<string, unknown> = {};
    for (const entry of input.cases) {
      try {
        const result = importCsv(entry.text, {
          dataset_label: 'fuzz',
          imported_at: input.imported_at,
          snapshot_id_prefix: 'f',
        });
        results[entry.id] = summarize(result, input.imported_at);
      } catch (error) {
        results[entry.id] = { thrown: String(error) };
      }
    }
    writeFileSync(OUT, JSON.stringify({ results }), 'utf8');
    expect(Object.keys(results)).toHaveLength(input.cases.length);
  });
});
