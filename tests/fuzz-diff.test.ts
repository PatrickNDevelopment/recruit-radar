/**
 * TypeScript legs of the cross-implementation differential tools in
 * `contracts/tools/fuzz_diff.py`. Both suites are skipped unless their input file is named, so
 * they are inert in the default test run.
 *
 * analyze fuzz:
 *   RR_FUZZ_FILE=cases.json RR_FUZZ_OUT=ts.json npx vitest run tests/fuzz-diff.test.ts
 *   input  `{ cases: [{ id, input }] }`
 *   output `{ results: { <id>: { ok, output | error, mutated } } }`
 *
 * normalization sweep:
 *   RR_NORM_FILE=inputs.json RR_NORM_OUT=ts.json npx vitest run tests/fuzz-diff.test.ts
 *   input  `{ inputs: string[] }`
 *   output `{ rows: [normText, titleKey, locationKey][] }` in input order
 *
 * This file never asserts equality with the other engines: the Python driver compares the three
 * artifacts and reports.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { analyze, locationKey, normText, titleKey } from '../src/engine';

const FUZZ_FILE = process.env.RR_FUZZ_FILE ?? '';
const FUZZ_OUT = process.env.RR_FUZZ_OUT ?? `${FUZZ_FILE}.ts.json`;
const NORM_FILE = process.env.RR_NORM_FILE ?? '';
const NORM_OUT = process.env.RR_NORM_OUT ?? `${NORM_FILE}.ts.json`;

interface FuzzCase {
  id: string;
  input: unknown;
}

type FuzzResult =
  { ok: true; output: unknown; mutated: boolean } | { ok: false; error: string; mutated: boolean };

function loadCases(file: string): FuzzCase[] {
  const parsed: unknown = JSON.parse(readFileSync(file, 'utf8'));
  if (typeof parsed !== 'object' || parsed === null || !('cases' in parsed)) {
    throw new Error(`${file}: expected an object with a "cases" array`);
  }
  const cases = (parsed as { cases: unknown }).cases;
  if (!Array.isArray(cases)) throw new Error(`${file}: "cases" is not an array`);
  return cases.map((entry, index): FuzzCase => {
    if (typeof entry !== 'object' || entry === null) {
      throw new Error(`${file}: cases[${index}] is not an object`);
    }
    const record = entry as { id?: unknown; input?: unknown };
    if (typeof record.id !== 'string') throw new Error(`${file}: cases[${index}] has no id`);
    return { id: record.id, input: record.input };
  });
}

function runCase(input: unknown): FuzzResult {
  const before = JSON.stringify(input);
  try {
    const output = analyze(input);
    return { ok: true, output, mutated: JSON.stringify(input) !== before };
  } catch (error) {
    const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    return { ok: false, error: message, mutated: JSON.stringify(input) !== before };
  }
}

function loadInputs(file: string): string[] {
  const parsed: unknown = JSON.parse(readFileSync(file, 'utf8'));
  if (typeof parsed !== 'object' || parsed === null || !('inputs' in parsed)) {
    throw new Error(`${file}: expected an object with an "inputs" array`);
  }
  const inputs = (parsed as { inputs: unknown }).inputs;
  if (!Array.isArray(inputs) || inputs.some((item) => typeof item !== 'string')) {
    throw new Error(`${file}: "inputs" must be an array of strings`);
  }
  return inputs as string[];
}

describe.skipIf(FUZZ_FILE === '')('cross-implementation fuzz (needs RR_FUZZ_FILE)', () => {
  it('runs every case and writes the outcomes', () => {
    const cases = loadCases(FUZZ_FILE);
    const results: Record<string, FuzzResult> = {};
    for (const entry of cases) results[entry.id] = runCase(entry.input);
    writeFileSync(FUZZ_OUT, JSON.stringify({ engine: 'typescript', results }), 'utf8');
    expect(Object.keys(results)).toHaveLength(cases.length);
  });
});

describe.skipIf(NORM_FILE === '')('normalization sweep (needs RR_NORM_FILE)', () => {
  it('normalizes every input and writes the keys', () => {
    const inputs = loadInputs(NORM_FILE);
    const rows = inputs.map((text) => [normText(text), titleKey(text), locationKey(text)]);
    writeFileSync(NORM_OUT, JSON.stringify({ engine: 'typescript', rows }), 'utf8');
    expect(rows).toHaveLength(inputs.length);
  });
});
