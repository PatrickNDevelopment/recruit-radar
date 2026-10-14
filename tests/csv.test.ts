import { describe, expect, it } from 'vitest';
import {
  analyze,
  buildShortlistRows,
  CSV_MAX_BYTES,
  CSV_MAX_ROWS,
  EngineInputError,
  exportPostingsCsv,
  exportShortlistCsv,
  guardFormula,
  importCsv,
  normalizeHeader,
  parseCsv,
  snapshotsToPostingRows,
  trimText,
  unguardFormula,
  validateImportRow,
  type CsvImportOptions,
  type CsvPostingRow,
} from '../src/engine';
import { utf8ByteLength } from '../src/engine/csv';
import { AS_OF, company, makeInput, mulberry32, post, snap } from './helpers';

const IMPORTED_AT = '2026-10-13T12:00:00Z';
const OPTIONS: CsvImportOptions = {
  dataset_label: 'Conf list',
  imported_at: IMPORTED_AT,
  snapshot_id_prefix: 'imp',
};

function cells(text: string): string[][] {
  const parsed = parseCsv(text);
  if (!parsed.ok) throw new Error(`parse failed: ${parsed.error.message}`);
  return parsed.records.map((record) => record.cells);
}

describe('parseCsv (RFC 4180)', () => {
  it('parses plain records', () => {
    expect(cells('a,b,c\n1,2,3\n')).toEqual([
      ['a', 'b', 'c'],
      ['1', '2', '3'],
    ]);
  });

  it('handles quoted commas, embedded newlines and doubled quotes', () => {
    expect(cells('a,"b,c","line1\nline2"\n')).toEqual([['a', 'b,c', 'line1\nline2']]);
    expect(cells('"say ""hi"""')).toEqual([['say "hi"']]);
    expect(cells('"x\r\ny",z')).toEqual([['x\r\ny', 'z']]);
    expect(cells('""')).toEqual([]); // a line holding only a quoted empty field is a blank line
    expect(cells('"",x')).toEqual([['', 'x']]);
    expect(cells('"""",x')).toEqual([['"', 'x']]);
  });

  it('accepts CRLF, LF, mixed and lone-CR record separators', () => {
    const expected = [['a'], ['b'], ['c']];
    expect(cells('a\r\nb\r\nc\r\n')).toEqual(expected);
    expect(cells('a\nb\nc')).toEqual(expected);
    expect(cells('a\r\nb\nc\r')).toEqual(expected);
    expect(cells('a\rb\rc')).toEqual(expected);
  });

  it('tolerates a UTF-8 BOM', () => {
    expect(cells('\ufeffcompany_name,title\r\nA,B')).toEqual([
      ['company_name', 'title'],
      ['A', 'B'],
    ]);
  });

  it('keeps empty fields and skips blank lines', () => {
    expect(cells(',,')).toEqual([['', '', '']]);
    expect(cells('a\n\n\nb\n')).toEqual([['a'], ['b']]);
    expect(cells('')).toEqual([]);
    expect(cells('\n\r\n')).toEqual([]);
  });

  it('numbers records by their first physical line, counting embedded newlines', () => {
    const parsed = parseCsv('h1,h2\n"a\nb",c\n\nd,e\n');
    expect(parsed.ok && parsed.records.map((r) => r.line)).toEqual([1, 2, 5]);
  });

  it('treats a quote inside an unquoted field literally', () => {
    expect(cells('ab"c,d')).toEqual([['ab"c', 'd']]);
  });

  it('flags text after a closing quote as a malformed record', () => {
    const parsed = parseCsv('"a"b,c');
    expect(parsed.ok && parsed.records[0]).toMatchObject({
      cells: ['a', 'c'],
      malformed: 'text follows a closing quote',
    });
    const second = parseCsv('"a""b" "c",d');
    expect(second.ok && second.records[0]?.malformed).toBe('a quote follows a closing quote');
  });

  it('ignores spaces and tabs around a quoted field (spec 05, CSV details)', () => {
    expect(cells('a, "b, c" ,d')).toEqual([['a', 'b, c', 'd']]);
    expect(cells('  "x"\t,"y"  \n')).toEqual([['x', 'y']]);
    // ...but not other characters, and not inside a field that already has text.
    expect(cells('a,\u00a0"b"')).toEqual([['a', '\u00a0"b"']]);
    expect(cells('a, x"y",z')).toEqual([['a', ' x"y"', 'z']]);
  });

  it('skips records whose only cell is blank, quoted or not, and still counts their lines', () => {
    expect(cells('a\n   \n\t\nb\n""\n  ""  \nc')).toEqual([['a'], ['b'], ['c']]);
    const parsed = parseCsv('h\n \n"  "\nx\n');
    expect(parsed.ok && parsed.records.map((r) => [r.line, r.cells[0]])).toEqual([
      [1, 'h'],
      [4, 'x'],
    ]);
    // A record with two empty cells is a row, not a blank line.
    expect(cells(' ,')).toEqual([[' ', '']]);
  });

  it('reports an unterminated quote as a file-level error with its line', () => {
    const parsed = parseCsv('a,b\n1,"oops,2\n3,4\n');
    expect(parsed.ok).toBe(false);
    expect(!parsed.ok && parsed.error).toMatchObject({ code: 'unterminated_quote', line: 2 });
  });
});

describe('formula guard', () => {
  it('prefixes one apostrophe on =, +, -, @, tab and CR', () => {
    for (const lead of ['=', '+', '-', '@', '\t', '\r']) {
      expect(guardFormula(`${lead}x`)).toBe(`'${lead}x`);
    }
    expect(guardFormula('plain')).toBe('plain');
    expect(guardFormula("'quoted")).toBe("'quoted");
    expect(guardFormula('')).toBe('');
    expect(guardFormula('a=b')).toBe('a=b');
  });

  it('removes exactly one apostrophe in front of a trigger character', () => {
    expect(unguardFormula("'=SUM(A1)")).toBe('=SUM(A1)');
    expect(unguardFormula("'-5")).toBe('-5');
    expect(unguardFormula("'abc")).toBe("'abc");
    expect(unguardFormula("'")).toBe("'");
    expect(unguardFormula('=x')).toBe('=x');
  });

  it('round-trips every string, including apostrophes before trigger characters', () => {
    const samples = [
      '',
      "'",
      "''",
      "'=x",
      "''=x",
      "'''+1",
      "'@home",
      "'abc",
      '=SUM(A1)',
      '+1',
      '-1',
      '@a',
      '\tx',
      '\rx',
      "'\tx",
      'plain',
      "O'Brien",
      "'t Hooft",
    ];
    for (const sample of samples) {
      expect(unguardFormula(guardFormula(sample)), JSON.stringify(sample)).toBe(sample);
    }
  });
});

describe('importCsv — happy path', () => {
  const csv = [
    'company_name,title,location,work_mode,department,url,posted_at,source_posting_id,observed_at',
    'Acme Inc.,Engineer,"New York, NY",remote,Platform,https://acme.example/jobs/1,2026-09-01,42,2026-10-01T09:00:00Z',
    'Globex,Analyst,,,,,,,',
    '',
  ].join('\r\n');
  const result = importCsv(csv, OPTIONS);

  it('accepts both rows and keeps the dataset label', () => {
    expect(result).toMatchObject({
      ok: true,
      file_error: null,
      dataset_label: 'Conf list',
      accepted: 2,
      rejected: 0,
      errors: [],
      warnings: [],
      rejected_rows: [],
    });
  });

  it('builds additive csv snapshots, one per effective observed_at, ascending', () => {
    expect(
      result.snapshots.map((s) => [
        s.snapshot_id,
        s.observed_at,
        s.mode,
        s.source_kind,
        s.source_ref,
      ]),
    ).toEqual([
      ['imp-1', '2026-10-01T09:00:00Z', 'additive', 'csv', 'Conf list'],
      ['imp-2', IMPORTED_AT, 'additive', 'csv', 'Conf list'], // blank observed_at = import time
    ]);
    expect(result.snapshots[0]?.postings).toEqual([
      {
        source_kind: 'csv',
        source_ref: 'Conf list',
        source_posting_id: '42',
        company_name: 'Acme Inc.',
        title: 'Engineer',
        location: 'New York, NY',
        work_mode: 'remote',
        department: 'Platform',
        url: 'https://acme.example/jobs/1',
        posted_at: '2026-09-01',
      },
    ]);
    expect(result.snapshots[1]?.postings[0]).toMatchObject({
      company_name: 'Globex',
      location: null,
      work_mode: 'unknown',
      department: null,
      url: null,
      posted_at: null,
      source_posting_id: null,
    });
  });

  it('produces snapshots that analyze() accepts', () => {
    const analysis = analyze(makeInput(result.snapshots));
    expect(analysis.companies.map((c) => c.name).sort()).toEqual(['Acme Inc.', 'Globex']);
  });

  it('derives a deterministic default snapshot id prefix', () => {
    const a = importCsv(csv, { dataset_label: 'Conf list', imported_at: IMPORTED_AT });
    const b = importCsv(csv, { dataset_label: 'Conf list', imported_at: IMPORTED_AT });
    expect(a.snapshots[0]?.snapshot_id).toBe(b.snapshots[0]?.snapshot_id);
    expect(a.snapshots[0]?.snapshot_id).toMatch(/^csv_[0-9a-f]{12}-1$/);
  });
});

describe('importCsv — headers', () => {
  it('normalizes header names: case, spaces and hyphens', () => {
    expect(normalizeHeader('  Company Name ')).toBe('company_name');
    expect(normalizeHeader('Source-Posting ID')).toBe('source_posting_id');
    const r = importCsv('Company Name,TITLE,Work-Mode\nA,B,hybrid\n', OPTIONS);
    expect(r.accepted).toBe(1);
    expect(r.snapshots[0]?.postings[0]?.work_mode).toBe('hybrid');
  });

  it('ignores unknown columns with a line-numbered warning', () => {
    const r = importCsv('company_name,title,notes\nA,B,secret\n', OPTIONS);
    expect(r.ok).toBe(true);
    expect(r.accepted).toBe(1);
    expect(r.warnings).toEqual([{ line: 1, message: 'Unknown column "notes" is ignored' }]);
  });

  it('rejects the file when a header repeats, even after normalization', () => {
    const r = importCsv('company_name,title,Company Name\nA,B,C\n', OPTIONS);
    expect(r.ok).toBe(false);
    expect(r.file_error).toMatchObject({ code: 'duplicate_header', line: 1 });
    expect(r.snapshots).toEqual([]);
    const exact = importCsv('title,title,company_name\nA,B,C\n', OPTIONS);
    expect(exact.file_error?.code).toBe('duplicate_header');
  });

  it('rejects the file when a required column is missing', () => {
    const r = importCsv('company_name,location\nA,B\n', OPTIONS);
    expect(r.file_error).toMatchObject({ code: 'missing_required_column', line: 1 });
    expect(r.file_error?.message).toContain('title');
  });

  it('rejects an empty file but accepts a header-only file', () => {
    expect(importCsv('', OPTIONS).file_error?.code).toBe('empty_file');
    expect(importCsv('\n\r\n', OPTIONS).file_error?.code).toBe('empty_file');
    const headerOnly = importCsv('company_name,title\n', OPTIONS);
    expect(headerOnly).toMatchObject({ ok: true, accepted: 0, rejected: 0, snapshots: [] });
  });

  it('warns about a nameless header cell instead of failing on duplicates', () => {
    const r = importCsv('company_name,title,,\nA,B,,\n', OPTIONS);
    expect(r.ok).toBe(true);
    expect(r.accepted).toBe(1);
    expect(r.warnings).toHaveLength(2);
  });

  it('tolerates a BOM and CRLF line endings', () => {
    const r = importCsv('\ufeffcompany_name,title\r\nA,B\r\nC,D\r\n', OPTIONS);
    expect(r.accepted).toBe(2);
  });
});

describe('importCsv — row validation', () => {
  const csv = [
    'company_name,title,work_mode,url,posted_at', // line 1
    'Acme,Engineer,remote,https://a.example,2026-09-01', // line 2 ok
    ',Engineer,remote,,', // line 3 missing company_name
    'Acme,Engineer,office,javascript:alert(1),2026-02-30', // line 4 three problems
    '"Multi', // line 5 (starts a quoted field that spans 5-6)
    'line",Designer,,,', // line 6 ok
    'Zed', // line 7 missing title
  ].join('\n');
  const r = importCsv(csv, OPTIONS);

  it('keeps valid rows and rejects invalid ones with 1-based line numbers', () => {
    expect(r.ok).toBe(true);
    expect(r.accepted).toBe(2);
    expect(r.rejected).toBe(3);
    expect(r.errors.map((e) => [e.line, e.field])).toEqual([
      [3, 'company_name'],
      [4, 'work_mode'],
      [4, 'url'],
      [4, 'posted_at'],
      [7, 'title'],
    ]);
    expect(r.snapshots[0]?.postings.map((p) => p.company_name)).toEqual(['Acme', 'Multi\nline']);
  });

  it('describes each problem specifically', () => {
    const byField = Object.fromEntries(r.errors.map((e) => [`${e.line}:${e.field}`, e.message]));
    expect(byField['3:company_name']).toBe('company_name is required');
    expect(byField['4:work_mode']).toContain('remote, hybrid, onsite, unknown');
    expect(byField['4:url']).toBe('url must be an http:// or https:// URL');
    expect(byField['4:posted_at']).toContain('real calendar date');
    expect(byField['7:title']).toBe('title is required');
  });

  it('returns rejected rows with their values for in-place correction', () => {
    const second = r.rejected_rows.find((row) => row.line === 4);
    expect(second?.values).toMatchObject({
      company_name: 'Acme',
      work_mode: 'office',
      url: 'javascript:alert(1)',
      posted_at: '2026-02-30',
    });
    expect(second?.errors).toHaveLength(3);
    // Fix the values and revalidate with the same rules.
    const fixed = validateImportRow(
      {
        ...second?.values,
        work_mode: 'onsite',
        url: 'https://a.example/1',
        posted_at: '2026-02-28',
      },
      IMPORTED_AT,
    );
    expect(fixed.ok).toBe(true);
  });

  it('enforces the length limits at exactly 200 / 300 / 300 / 200', () => {
    const row = (company: string, title: string, location: string, department: string): string =>
      `company_name,title,location,department\n${company},${title},${location},${department}\n`;
    expect(
      importCsv(row('x'.repeat(200), 't'.repeat(300), 'l'.repeat(300), 'd'.repeat(200)), OPTIONS)
        .accepted,
    ).toBe(1);
    const over = importCsv(
      row('x'.repeat(201), 't'.repeat(301), 'l'.repeat(301), 'd'.repeat(201)),
      OPTIONS,
    );
    expect(over.errors.map((e) => e.field)).toEqual([
      'company_name',
      'title',
      'location',
      'department',
    ]);
    expect(over.errors[0]?.message).toBe('company_name must be at most 200 characters (got 201)');
  });

  it('counts characters, not bytes, for the length limits', () => {
    const r2 = importCsv(`company_name,title\n${'日'.repeat(200)},${'😀'.repeat(300)}\n`, OPTIONS);
    expect(r2.accepted).toBe(1);
  });

  it('rejects every non-http(s) URL form', () => {
    const urls = [
      'javascript:alert(1)',
      'JAVASCRIPT:alert(1)',
      'data:text/html,<script>1</script>',
      'ftp://example.com/x',
      'mailto:someone@example.com',
      '//example.com',
      'example.com/jobs',
      '/relative/path',
      'vbscript:msgbox(1)',
      'file:///etc/passwd',
    ];
    for (const url of urls) {
      const rr = importCsv(`company_name,title,url\nA,B,"${url}"\n`, OPTIONS);
      expect(rr.rejected, url).toBe(1);
      expect(rr.errors[0]?.field).toBe('url');
    }
    for (const url of ['http://example.com', 'HTTPS://Example.com/a?b=c#d']) {
      expect(importCsv(`company_name,title,url\nA,B,${url}\n`, OPTIONS).accepted, url).toBe(1);
    }
  });

  it('rejects impossible and malformed dates and timestamps', () => {
    const dates = importCsv(
      'company_name,title,posted_at\nA,B,2026-02-30\nA,B,2026-13-01\nA,B,13/10/2026\nA,B,2024-02-29\n',
      OPTIONS,
    );
    expect(dates.accepted).toBe(1);
    expect(dates.errors.map((e) => e.line)).toEqual([2, 3, 4]);
    const stamps = importCsv(
      'company_name,title,observed_at\nA,B,2026-10-01 09:00:00\nA,B,2026-10-01T25:00:00Z\nA,B,2026-10-01T09:00:00.000Z\n',
      OPTIONS,
    );
    expect(stamps.rejected).toBe(3);
    expect(stamps.errors.every((e) => e.field === 'observed_at')).toBe(true);
  });

  it('rejects a row with extra non-empty fields but tolerates trailing empty cells', () => {
    const r2 = importCsv('company_name,title\nA,B,,,\nC,D,oops\nE\n', OPTIONS);
    expect(r2.accepted).toBe(1);
    expect(r2.errors.map((e) => [e.line, e.field])).toEqual([
      [3, undefined],
      [4, 'title'],
    ]);
    expect(r2.errors[0]?.message).toContain('3 values but the header defines 2 columns');
  });

  it('does not validate the fields of a structurally broken row', () => {
    // The columns of a shifted or badly quoted row cannot be trusted: one row-level error only.
    const r2 = importCsv('company_name,title,url\n"A"x,B,ftp://nope\n,B,C,D\n', OPTIONS);
    expect(r2.rejected).toBe(2);
    expect(r2.errors.map((e) => [e.line, e.field])).toEqual([
      [2, undefined],
      [3, undefined],
    ]);
  });

  it('refuses a file whose header row is malformed, or that contains a NUL', () => {
    const header = importCsv('"company_name"x,title\nA,B\n', OPTIONS);
    expect(header.file_error).toMatchObject({ code: 'malformed_header', line: 1 });
    const nul = importCsv('company_name,title\nA\u0000B,C\n', OPTIONS);
    expect(nul.ok).toBe(false);
    expect(nul.file_error?.code).toBe('contains_nul');
    expect(nul.snapshots).toEqual([]);
  });

  it('maps tabs and no-break spaces in header names like spaces', () => {
    const ok = importCsv('Company\tName,TITLE,Posted\u00a0At\nA,B,2026-09-01\n', OPTIONS);
    expect(ok.accepted).toBe(1);
    expect(ok.snapshots[0]?.postings[0]).toMatchObject({
      company_name: 'A',
      posted_at: '2026-09-01',
    });
  });

  it('warns about a row that replaces an earlier one and about a future observed_at', () => {
    const r2 = importCsv(
      [
        'company_name,title,location,observed_at',
        'Acme,Engineer,Berlin,',
        'ACME Inc.,Engineer (Remote),berlin,',
        'Acme,Engineer,Berlin,2030-01-01T00:00:00Z',
      ].join('\n'),
      OPTIONS,
    );
    expect(r2.accepted).toBe(3);
    expect(r2.warnings.map((w) => [w.line, w.message.slice(0, 22)])).toEqual([
      [3, 'Same posting as line 2'],
      [4, 'observed_at 2030-01-01'],
    ]);
  });

  it('reports a malformed quote as a row error', () => {
    const r2 = importCsv('company_name,title\n"A"x,B\nC,D\n', OPTIONS);
    expect(r2.accepted).toBe(1);
    expect(r2.errors[0]).toMatchObject({ line: 2 });
    expect(r2.errors[0]?.message).toContain('closing quote');
  });

  it('treats an unterminated quote as a file-level error', () => {
    const r2 = importCsv('company_name,title\nA,"B\nC,D\n', OPTIONS);
    expect(r2.ok).toBe(false);
    expect(r2.file_error).toMatchObject({ code: 'unterminated_quote', line: 2 });
    expect(r2.accepted).toBe(0);
    expect(r2.snapshots).toEqual([]);
  });

  it('removes one apostrophe from guarded cells on import', () => {
    const r2 = importCsv(`company_name,title\n'=Evil Corp,'-Lead\n'Quoted Co,'''+x\n`, OPTIONS);
    expect(r2.snapshots[0]?.postings.map((p) => [p.company_name, p.title])).toEqual([
      ['=Evil Corp', '-Lead'],
      ["'Quoted Co", "''+x"],
    ]);
  });

  it('trims every cell and reads blank optional cells as null', () => {
    const r2 = importCsv('company_name,title,location\n  A  ,\tB\t,   \n', OPTIONS);
    expect(r2.snapshots[0]?.postings[0]).toMatchObject({
      company_name: 'A',
      title: 'B',
      location: null,
    });
  });
});

describe('importCsv — dataset label and caps', () => {
  it('requires a dataset label of 1..200 characters', () => {
    for (const label of ['', '   ', 'x'.repeat(201)]) {
      const r = importCsv('company_name,title\nA,B\n', { ...OPTIONS, dataset_label: label });
      expect(r.ok).toBe(false);
      expect(r.file_error?.code).toBe('invalid_dataset_label');
    }
    const ok = importCsv('company_name,title\nA,B\n', { ...OPTIONS, dataset_label: '  Trim me  ' });
    expect(ok.dataset_label).toBe('Trim me');
    expect(ok.snapshots[0]?.source_ref).toBe('Trim me');
  });

  it('throws for an invalid import time (a caller bug, not user data)', () => {
    expect(() =>
      importCsv('company_name,title\nA,B\n', { ...OPTIONS, imported_at: 'now' }),
    ).toThrow(EngineInputError);
  });

  it('enforces the 1 MiB size cap on UTF-8 bytes', () => {
    const head = 'company_name,title,notes\nA,B,';
    const exact = head + 'x'.repeat(CSV_MAX_BYTES - head.length);
    expect(utf8ByteLength(exact)).toBe(CSV_MAX_BYTES);
    expect(importCsv(exact, OPTIONS)).toMatchObject({ ok: true, accepted: 1 });
    const over = importCsv(`${exact}x`, OPTIONS);
    expect(over.ok).toBe(false);
    expect(over.file_error?.code).toBe('too_large');
    expect(over.accepted).toBe(0);
    // 'é' is two bytes: under the cap in characters, over it in bytes.
    const wide = head + 'é'.repeat(CSV_MAX_BYTES / 2);
    expect(wide.length).toBeLessThan(CSV_MAX_BYTES);
    expect(importCsv(wide, OPTIONS).file_error?.code).toBe('too_large');
  });

  it('enforces the 5,000 data-row cap', () => {
    const body = (count: number): string =>
      'company_name,title\n' + Array.from({ length: count }, (_, i) => `Co ${i},Role`).join('\n');
    const atCap = importCsv(body(CSV_MAX_ROWS), OPTIONS);
    expect(atCap).toMatchObject({ ok: true, accepted: CSV_MAX_ROWS });
    const over = importCsv(body(CSV_MAX_ROWS + 1), OPTIONS);
    expect(over.ok).toBe(false);
    expect(over.file_error?.code).toBe('too_many_rows');
    expect(over.snapshots).toEqual([]);
  });

  it('does not count blank lines against the row cap', () => {
    const body =
      'company_name,title\n' +
      Array.from({ length: CSV_MAX_ROWS }, (_, i) => `Co ${i},Role\n\n`).join('');
    expect(importCsv(body, OPTIONS).accepted).toBe(CSV_MAX_ROWS);
  });

  it('groups rows into one snapshot per observed_at and keeps file order within each', () => {
    const r = importCsv(
      [
        'company_name,title,observed_at',
        'A,One,2026-10-02T00:00:00Z',
        'B,Two,2026-10-01T00:00:00Z',
        'C,Three,2026-10-02T00:00:00Z',
        'D,Four,',
      ].join('\n'),
      OPTIONS,
    );
    expect(r.snapshots.map((s) => [s.observed_at, s.postings.map((p) => p.title)])).toEqual([
      ['2026-10-01T00:00:00Z', ['Two']],
      ['2026-10-02T00:00:00Z', ['One', 'Three']],
      [IMPORTED_AT, ['Four']],
    ]);
  });
});

describe('export', () => {
  const row = (extra: Partial<CsvPostingRow> = {}): CsvPostingRow => ({
    company_name: 'Acme',
    title: 'Engineer',
    location: null,
    work_mode: 'unknown',
    department: null,
    url: null,
    posted_at: null,
    source_posting_id: null,
    observed_at: null,
    ...extra,
  });

  it('writes the header, CRLF line endings and blanks for null', () => {
    expect(exportPostingsCsv([row()])).toBe(
      'company_name,title,location,work_mode,department,url,posted_at,source_posting_id,observed_at\r\n' +
        'Acme,Engineer,,unknown,,,,,\r\n',
    );
  });

  it('quotes cells that contain commas, quotes or line breaks', () => {
    const text = exportPostingsCsv([row({ title: 'Eng, "Sr"\nplatform', location: 'a\r\nb' })]);
    expect(text).toContain('"Eng, ""Sr""\nplatform"');
    expect(text).toContain('"a\r\nb"');
  });

  it('adds an apostrophe to cells that start with a formula character', () => {
    const text = exportPostingsCsv([
      row({ company_name: '=HYPERLINK("x")', title: '+1', location: '-2', department: '@sum' }),
    ]);
    expect(text).toContain(`"'=HYPERLINK(""x"")",'+1,'-2,unknown,'@sum`);
  });

  it('can prefix a BOM', () => {
    expect(exportPostingsCsv([], { bom: true })).toBe(
      '\ufeffcompany_name,title,location,work_mode,department,url,posted_at,source_posting_id,observed_at\r\n',
    );
    expect(exportPostingsCsv([])).not.toContain('\ufeff');
  });

  it('round-trips hostile and unusual values exactly', () => {
    const rows: CsvPostingRow[] = [
      row({ company_name: "'Quoted Co", title: "'=cmd|' /C calc'!A0", location: "'+1" }),
      row({ company_name: '=SUM(A1:A9)', title: '+x', location: '-y', department: '@z' }),
      row({ company_name: 'He said "hi", then left', title: 'Line1\nLine2', location: 'a\r\nb' }),
      row({
        company_name: "O'Brien & Sons",
        title: "''double",
        url: 'https://x.example/a?b=1&c=2',
      }),
      row({
        company_name: '日本の会社',
        title: '😀 Engineer',
        posted_at: '2026-01-31',
        work_mode: 'hybrid',
        source_posting_id: "'=id",
        observed_at: '2026-10-01T00:00:00Z',
      }),
    ];
    const result = importCsv(exportPostingsCsv(rows), OPTIONS);
    expect(result.errors).toEqual([]);
    const back = snapshotsToPostingRows(result.snapshots);
    // Rows are regrouped by observed_at; compare as sets keyed by company.
    const key = (r: CsvPostingRow): string => r.company_name;
    const expected = rows.map((r) => ({ ...r, observed_at: r.observed_at ?? IMPORTED_AT }));
    expect(back.map(key).sort()).toEqual(expected.map(key).sort());
    for (const want of expected) {
      expect(back.find((b) => b.company_name === want.company_name)).toEqual(want);
    }
  });

  it('round-trips 300 seeded random rows over a hostile alphabet', () => {
    const random = mulberry32(8675309);
    const alphabet = [
      '=',
      '+',
      '-',
      '@',
      "'",
      '\t',
      '\r',
      '\n',
      ' ',
      ',',
      '"',
      'a',
      'B',
      '1',
      'é',
      '日',
      '😀',
    ];
    const make = (): string => {
      let text = '';
      const length = 1 + Math.floor(random() * 8);
      for (let i = 0; i < length; i += 1)
        text += alphabet[Math.floor(random() * alphabet.length)] ?? '';
      return text;
    };
    const rows: CsvPostingRow[] = [];
    while (rows.length < 300) {
      const company = trimText(make());
      const title = trimText(make());
      if (company === '' || title === '') continue;
      const optional = (): string | null => {
        const value = trimText(make());
        return random() < 0.3 || value === '' ? null : value;
      };
      rows.push(
        row({
          company_name: company,
          title,
          location: optional(),
          department: optional(),
          source_posting_id: optional(),
          observed_at: IMPORTED_AT,
        }),
      );
    }
    const result = importCsv(exportPostingsCsv(rows), OPTIONS);
    expect(result.errors).toEqual([]);
    expect(result.rejected).toBe(0);
    expect(snapshotsToPostingRows(result.snapshots)).toEqual(rows);
  });
});

describe('shortlist export', () => {
  const acmeAnalysis = analyze(
    makeInput(
      [
        snap('s1', 'greenhouse', 'acme', '2026-08-01T00:00:00Z', 'full', [
          post('Acme', 'Software Engineer', { source_posting_id: '1', posted_at: '2026-06-01' }),
          post('Acme', 'Engineering Manager', { source_posting_id: '2' }),
          post('Acme', 'Engineer Intern', { source_posting_id: '3' }),
        ]),
        snap('s2', 'greenhouse', 'acme', '2026-09-30T00:00:00Z', 'full', [
          post('Acme', 'Software Engineer', { source_posting_id: '1', posted_at: '2026-06-01' }),
          post('Acme', 'Engineering Manager', { source_posting_id: '2' }),
          post('Acme', 'Engineer Intern', { source_posting_id: '3' }),
          post('Acme', 'Staff Engineer', { source_posting_id: '4' }),
        ]),
      ],
      { profile: { include_keywords: ['engineer'], exclude_keywords: ['intern'] } },
    ),
  );

  const betaAnalysis = analyze(
    makeInput([
      snap('g', 'greenhouse', 'beta', '2026-10-10T00:00:00Z', 'full', [
        post('Beta', 'Data Analyst', { location: 'Remote', source_posting_id: '7' }),
      ]),
      snap('c', 'csv', 'leads', '2026-10-10T00:00:00Z', 'additive', [
        post('Beta', 'Data Analyst', { location: 'Remote' }),
      ]),
    ]),
  );

  it('summarises a fully-scored company', () => {
    const acme = company(acmeAnalysis, 'Acme');
    const { rows, unknown_company_ids } = buildShortlistRows(acmeAnalysis, [
      { company_id: acme.company_id, note: 'Call Monday' },
    ]);
    expect(unknown_company_ids).toEqual([]);
    expect(rows).toEqual([
      {
        rank: 1,
        company: 'Acme',
        score: '62.5',
        coverage_percent: 100,
        active_roles: 4,
        relevant_roles: 2,
        last_seen: '2026-09-30T00:00:00Z',
        strongest_evidence: 'Role relevance: 2 of 4 active roles match the role keywords',
        missing_information: '',
        note: 'Call Monday',
        as_of: AS_OF,
      },
    ]);
  });

  it('lists missing information instead of scoring it as zero', () => {
    const beta = company(betaAnalysis, 'Beta');
    const { rows } = buildShortlistRows(betaAnalysis, [{ company_id: beta.company_id }]);
    expect(rows[0]).toMatchObject({
      rank: 1,
      score: '68.9',
      coverage_percent: 45,
      relevant_roles: null,
      note: '',
      strongest_evidence: 'Source confidence: 1 role in scope, 1 confirmed by two or more sources',
    });
    expect(rows[0]?.missing_information).toBe(
      'Role relevance: no role keywords are configured; ' +
        'Change in the last 30 days: needs full-list snapshots at least 14 days apart (change cannot be measured yet); ' +
        'Possible urgency signal (aged postings): none of the roles has a posting date or enough history to estimate its age',
    );
  });

  it('reports shortlisted companies that are no longer in the analysis', () => {
    const { rows, unknown_company_ids } = buildShortlistRows(betaAnalysis, [
      { company_id: 'c_000000000000', note: 'gone' },
    ]);
    expect(rows).toEqual([]);
    expect(unknown_company_ids).toEqual(['c_000000000000']);
  });

  it('writes the documented columns with guarded cells and blanks for null', () => {
    const beta = company(betaAnalysis, 'Beta');
    const { rows } = buildShortlistRows(betaAnalysis, [
      { company_id: beta.company_id, note: '=HYPERLINK("http://x")' },
    ]);
    const text = exportShortlistCsv(rows);
    const lines = text.split('\r\n');
    expect(lines[0]).toBe(
      'rank,company,score,coverage_percent,active_roles,relevant_roles,last_seen,strongest_evidence,missing_information,note,as_of',
    );
    expect(lines[1]?.startsWith('1,Beta,68.9,45,1,,2026-10-10T00:00:00Z,')).toBe(true);
    expect(lines[1]?.endsWith(`,"'=HYPERLINK(""http://x"")",${AS_OF}`)).toBe(true);
    expect(text.endsWith('\r\n')).toBe(true);
  });

  it('shortlist export can be re-read as plain CSV', () => {
    const { rows } = buildShortlistRows(acmeAnalysis, [
      { company_id: company(acmeAnalysis, 'Acme').company_id, note: 'a, "b"\nc' },
    ]);
    const parsed = cells(exportShortlistCsv(rows));
    expect(parsed).toHaveLength(2);
    expect(parsed[1]?.[9]).toBe('a, "b"\nc');
    expect(parsed[1]).toHaveLength(11);
  });
});

describe('export helpers', () => {
  it('snapshotsToPostingRows carries each snapshot time onto its postings', () => {
    const rows = snapshotsToPostingRows([
      {
        observed_at: '2026-10-01T00:00:00Z',
        postings: [
          {
            source_kind: 'csv',
            source_ref: 'x',
            source_posting_id: null,
            company_name: 'A',
            title: 'T',
            location: null,
            work_mode: 'unknown',
            department: null,
            url: null,
            posted_at: null,
          },
        ],
      },
    ]);
    expect(rows).toEqual([
      {
        company_name: 'A',
        title: 'T',
        location: null,
        work_mode: 'unknown',
        department: null,
        url: null,
        posted_at: null,
        source_posting_id: null,
        observed_at: '2026-10-01T00:00:00Z',
      },
    ]);
  });
});
