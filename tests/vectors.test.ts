/**
 * Golden vectors (contracts/vectors/*.json): hand-derived, implementation-independent cases that
 * the TypeScript and Python engines must both reproduce exactly.
 *
 * - `analysis-*.json`    one case per file: `{ name, description, input, expected }`;
 *                        `analyze(input)` must equal `expected` exactly.
 * - `normalization.json` `{ cases: [{ id, fn, input, expected }] }`; each primitive must
 *                        reproduce its result.
 *
 * When no vector file exists the suite is skipped with a message, unless RR_REQUIRE_VECTORS=1, in
 * which case missing vectors fail the run (CI sets it).
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  analyze,
  companyKey,
  EngineInputError,
  locationKey,
  normText,
  sha12,
  titleKey,
  tokenSequenceMatch,
} from '../src/engine';

// RR_VECTOR_DIR overrides the location (used to exercise the skip / require paths of this file).
const DEFAULT_DIR = fileURLToPath(new URL('../contracts/vectors/', import.meta.url));
const OVERRIDE_DIR = process.env.RR_VECTOR_DIR;
const VECTOR_DIR =
  OVERRIDE_DIR === undefined || OVERRIDE_DIR === ''
    ? DEFAULT_DIR
    : OVERRIDE_DIR.replace(/[\\/]*$/u, '/');
const REQUIRED = process.env.RR_REQUIRE_VECTORS === '1';

type Json = unknown;

const isRecord = (value: Json): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

function listVectorFiles(): string[] {
  return existsSync(VECTOR_DIR)
    ? readdirSync(VECTOR_DIR)
        .filter((name) => name.endsWith('.json'))
        .sort()
    : [];
}

function readJson(file: string): Json {
  return JSON.parse(readFileSync(`${VECTOR_DIR}${file}`, 'utf8')) as Json;
}

function firstDefined(record: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) if (key in record) return record[key];
  return undefined;
}

// ---------------------------------------------------------------------------------------------
// analysis-*.json
// ---------------------------------------------------------------------------------------------

interface AnalysisCase {
  file: string;
  name: string;
  input: unknown;
  expected: Record<string, unknown> | undefined;
  expectError: boolean;
}

/** A vector file may hold one case, an array of cases, or `{ cases: [...] }`. */
function caseList(file: string, json: Json): Record<string, unknown>[] {
  if (Array.isArray(json)) return json.filter(isRecord);
  if (isRecord(json)) {
    for (const key of ['cases', 'vectors']) {
      const nested = json[key];
      if (Array.isArray(nested)) return nested.filter(isRecord);
    }
    return [json];
  }
  throw new Error(`${file}: unrecognized vector file structure`);
}

function analysisCases(): AnalysisCase[] {
  const out: AnalysisCase[] = [];
  for (const file of listVectorFiles().filter((n) => /^analysis-.*\.json$/.test(n))) {
    caseList(file, readJson(file)).forEach((entry, index) => {
      if (!('input' in entry)) throw new Error(`${file}[${index}]: no "input" property`);
      const expected = firstDefined(entry, ['expected', 'expected_output', 'output']);
      const expectError =
        firstDefined(entry, ['error', 'expected_error', 'expect_error']) !== undefined;
      if (!isRecord(expected) && !expectError) {
        throw new Error(`${file}[${index}]: no "expected" object (and no expected error)`);
      }
      const label = firstDefined(entry, ['name', 'id', 'title']);
      out.push({
        file,
        name: typeof label === 'string' ? label : `case ${index}`,
        input: entry.input,
        expected: isRecord(expected) ? expected : undefined,
        expectError,
      });
    });
  }
  return out;
}

const cases = analysisCases();

describe('golden analysis vectors', () => {
  if (cases.length === 0) {
    it('has vectors to run', (ctx) => {
      if (REQUIRED) {
        throw new Error('RR_REQUIRE_VECTORS=1 but contracts/vectors/analysis-*.json is empty');
      }
      ctx.skip(
        'no contracts/vectors/analysis-*.json present; set RR_REQUIRE_VECTORS=1 to make this fail',
      );
    });
    return;
  }

  for (const vector of cases) {
    it(`${vector.file} — ${vector.name}`, () => {
      if (vector.expectError) {
        expect(() => analyze(vector.input)).toThrow(EngineInputError);
        return;
      }
      const actual = analyze(vector.input) as unknown as Record<string, unknown>;
      const expected = vector.expected ?? {};
      // Exact comparison; a vector that lists only some top-level sections is compared on those.
      const subset = Object.fromEntries(Object.keys(expected).map((key) => [key, actual[key]]));
      expect(subset).toStrictEqual(expected);
    });
  }
});

// ---------------------------------------------------------------------------------------------
// normalization.json
// ---------------------------------------------------------------------------------------------

interface NormalizationCase {
  id: string;
  fn: string;
  input: unknown;
  expected: unknown;
}

const NORMALIZATION: Record<string, (input: unknown) => unknown> = {
  norm_text: (input) => normText(String(input)),
  company_key: (input) => companyKey(String(input)),
  title_key: (input) => titleKey(String(input)),
  location_key: (input) => locationKey(input === null ? null : String(input)),
  sha12: (input) => sha12(String(input)),
  // `title` is already a title_key in the vectors; only the phrase is normalized.
  token_sequence_match: (input) => {
    if (!isRecord(input)) throw new Error('token_sequence_match input must be an object');
    return tokenSequenceMatch(String(input.title), String(input.phrase));
  },
};

function normalizationCases(): NormalizationCase[] {
  const json = readJson('normalization.json');
  if (!isRecord(json) || !Array.isArray(json.cases)) {
    throw new Error('normalization.json: expected an object with a "cases" array');
  }
  return json.cases.filter(isRecord).map((entry, index) => {
    const fn = entry.fn;
    if (typeof fn !== 'string' || !(fn in NORMALIZATION)) {
      throw new Error(`normalization.json cases[${index}]: unknown function ${String(fn)}`);
    }
    if (!('expected' in entry) || !('input' in entry)) {
      throw new Error(`normalization.json cases[${index}]: needs "input" and "expected"`);
    }
    return {
      id: typeof entry.id === 'string' ? entry.id : `${fn}-${index}`,
      fn,
      input: entry.input,
      expected: entry.expected,
    };
  });
}

describe('golden normalization vectors', () => {
  if (!listVectorFiles().includes('normalization.json')) {
    it('has vectors to run', (ctx) => {
      if (REQUIRED) {
        throw new Error('RR_REQUIRE_VECTORS=1 but contracts/vectors/normalization.json is missing');
      }
      ctx.skip('no contracts/vectors/normalization.json present');
    });
    return;
  }
  for (const entry of normalizationCases()) {
    it(`${entry.id}: ${entry.fn}(${JSON.stringify(entry.input)})`, () => {
      const fn = NORMALIZATION[entry.fn];
      if (fn === undefined) throw new Error(`unknown function ${entry.fn}`);
      expect(fn(entry.input)).toStrictEqual(entry.expected);
    });
  }
});
