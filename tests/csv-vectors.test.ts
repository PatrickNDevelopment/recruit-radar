/**
 * Golden CSV import vectors (contracts/vectors/csv-import.json). The Python importer is held to
 * the same file by backend/tests/test_csv_vectors.py, so the two implementations cannot drift apart.
 */
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { importCsv } from '../src/engine/csv';
import { expand, summarize, type CsvSummary, type TextSpec } from './csv-summary';

const VECTOR_FILE = resolve(import.meta.dirname, '..', 'contracts', 'vectors', 'csv-import.json');
const REQUIRED = process.env['RR_REQUIRE_VECTORS'] === '1';

interface VectorCase {
  id: string;
  description: string;
  text: TextSpec;
  expected: Omit<CsvSummary, 'rows'> & { rows: CsvSummary['rows'] | null };
}

interface VectorFile {
  kind: string;
  imported_at: string;
  cases: VectorCase[];
}

if (!existsSync(VECTOR_FILE)) {
  describe('CSV import vectors', () => {
    it.skipIf(!REQUIRED)('vector file is present', () => {
      throw new Error(`RR_REQUIRE_VECTORS=1 but ${VECTOR_FILE} is missing`);
    });
  });
} else {
  const vectors = JSON.parse(readFileSync(VECTOR_FILE, 'utf8')) as VectorFile;

  describe('CSV import vectors (contracts/vectors/csv-import.json)', () => {
    it('the file is the one the Python importer is tested against', () => {
      expect(vectors.kind).toBe('csv-import');
      expect(vectors.cases.length).toBeGreaterThanOrEqual(40);
      expect(new Set(vectors.cases.map((c) => c.id)).size).toBe(vectors.cases.length);
    });

    for (const vector of vectors.cases) {
      it(`${vector.id}: ${vector.description.slice(0, 80)}`, () => {
        const result = importCsv(expand(vector.text), {
          dataset_label: 'vectors',
          imported_at: vectors.imported_at,
          snapshot_id_prefix: 'v',
        });
        const got = summarize(result, vectors.imported_at);
        const want = vector.expected;
        expect(got.file_error).toBe(want.file_error);
        expect(got.accepted).toBe(want.accepted);
        expect(got.rejected).toBe(want.rejected);
        expect(got.errors).toEqual(want.errors);
        expect(got.warnings).toEqual(want.warnings);
        if (want.rows !== null) expect(got.rows).toEqual(want.rows);
      });
    }
  });
}
