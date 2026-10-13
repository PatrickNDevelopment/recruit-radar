/**
 * CSV import and export (spec 05). Import and export are symmetric: whatever `exportPostingsCsv`
 * writes, `importCsv` reads back unchanged.
 *
 * Pure and deterministic: the import time is an explicit argument, nothing reads the clock.
 */
import { COMPONENT_NAMES, describeComponent, formatScore, REASON_TEXT } from './explain';
import { EngineInputError } from './errors';
import { trimText } from './normalize';
import { sha12 } from './sha256';
import {
  checkDate,
  checkOptionalText,
  checkOptionalTimestamp,
  checkRequiredText,
  checkTimestamp,
  checkUrl,
  checkWorkMode,
  LIMITS,
  type Check,
} from './validate';
import type {
  Analysis,
  CompanyAnalysis,
  ParsedSnapshot,
  RawPosting,
  ScoreComponent,
  WorkMode,
} from './types';

// ---------------------------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------------------------

/** Import size cap: 1 MiB of UTF-8. */
export const CSV_MAX_BYTES = 1_048_576;
/** Import row cap: data rows, excluding the header. */
export const CSV_MAX_ROWS = 5000;

/** Columns of the posting CSV, in export order. `company_name` and `title` are required. */
export const POSTING_COLUMNS = [
  'company_name',
  'title',
  'location',
  'work_mode',
  'department',
  'url',
  'posted_at',
  'source_posting_id',
  'observed_at',
] as const;
export type PostingColumn = (typeof POSTING_COLUMNS)[number];

export const SHORTLIST_COLUMNS = [
  'rank',
  'company',
  'score',
  'coverage_percent',
  'active_roles',
  'relevant_roles',
  'last_seen',
  'strongest_evidence',
  'missing_information',
  'note',
  'as_of',
] as const;

const REQUIRED_COLUMNS: readonly PostingColumn[] = ['company_name', 'title'];

// ---------------------------------------------------------------------------------------------
// Result types
// ---------------------------------------------------------------------------------------------

export type CsvFileErrorCode =
  | 'too_large'
  | 'too_many_rows'
  | 'unterminated_quote'
  | 'empty_file'
  | 'duplicate_header'
  | 'missing_required_column'
  | 'invalid_dataset_label';

/** A problem that rejects the whole file. */
export interface CsvFileError {
  code: CsvFileErrorCode;
  message: string;
  /** 1-based line of the problem, when it has one. */
  line?: number;
}

/** A problem that rejects one row (other rows are kept). */
export interface CsvRowError {
  /** 1-based line of the row's first physical line. */
  line: number;
  field?: string;
  message: string;
}

export interface CsvWarning {
  line: number;
  message: string;
}

/** A rejected row with its (trimmed, un-guarded) values, so the UI can offer in-place fixes. */
export interface CsvRejectedRow {
  line: number;
  values: Record<string, string>;
  errors: CsvRowError[];
}

export interface CsvImportResult {
  /** False when the file was rejected as a whole (see `file_error`). */
  ok: boolean;
  file_error: CsvFileError | null;
  dataset_label: string;
  accepted: number;
  rejected: number;
  errors: CsvRowError[];
  warnings: CsvWarning[];
  rejected_rows: CsvRejectedRow[];
  /**
   * One additive snapshot per distinct effective `observed_at` (ascending). Pass them to
   * `analyze()` as-is; ids are `<prefix>-<n>`.
   */
  snapshots: ParsedSnapshot[];
}

export interface CsvImportOptions {
  /** User-provided, required; becomes `source_ref` (source_kind is `csv`). */
  dataset_label: string;
  /** `YYYY-MM-DDTHH:MM:SSZ`; the observed_at of rows that leave the column blank. */
  imported_at: string;
  /** Snapshot id prefix; defaults to a hash of label, import time and file content. */
  snapshot_id_prefix?: string;
}

// ---------------------------------------------------------------------------------------------
// RFC 4180 parsing
// ---------------------------------------------------------------------------------------------

export interface CsvRecord {
  /** 1-based physical line on which the record starts. */
  line: number;
  cells: string[];
  /** Set when the record violates RFC 4180 quoting (text after a closing quote). */
  malformed?: string;
}

export type CsvParseResult =
  { ok: true; records: CsvRecord[] } | { ok: false; error: CsvFileError };

/**
 * Parse CSV text. Handles quoted fields, doubled quotes, embedded commas and newlines, CRLF / LF
 * (a lone CR also ends a record), and a leading UTF-8 BOM. Blank lines are skipped.
 */
export function parseCsv(text: string): CsvParseResult {
  const source = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  const records: CsvRecord[] = [];
  let cells: string[] = [];
  let field = '';
  let inQuotes = false;
  let fieldWasQuoted = false;
  let recordMalformed: string | undefined;
  let line = 1;
  let recordLine = 1;
  let quoteOpenedAt = 1;

  const endField = (): void => {
    cells.push(field);
    field = '';
    fieldWasQuoted = false;
  };
  const endRecord = (): void => {
    const blank = cells.length === 0 && field === '' && !fieldWasQuoted;
    if (!blank) {
      endField();
      const record: CsvRecord = { line: recordLine, cells };
      if (recordMalformed !== undefined) record.malformed = recordMalformed;
      records.push(record);
    }
    cells = [];
    field = '';
    fieldWasQuoted = false;
    recordMalformed = undefined;
    recordLine = line;
  };

  let i = 0;
  const length = source.length;
  while (i < length) {
    const ch = source.charAt(i);
    if (inQuotes) {
      if (ch === '"') {
        if (source.charAt(i + 1) === '"') {
          field += '"';
          i += 2;
        } else {
          inQuotes = false;
          i += 1;
        }
      } else if (ch === '\r') {
        // Newlines inside quotes are data and kept byte-for-byte.
        if (source.charAt(i + 1) === '\n') {
          field += '\r\n';
          i += 2;
        } else {
          field += '\r';
          i += 1;
        }
        line += 1;
      } else {
        if (ch === '\n') line += 1;
        field += ch;
        i += 1;
      }
      continue;
    }
    if (ch === ',') {
      endField();
      i += 1;
    } else if (ch === '\r' || ch === '\n') {
      i += ch === '\r' && source.charAt(i + 1) === '\n' ? 2 : 1;
      line += 1;
      endRecord();
    } else if (ch === '"' && field === '' && !fieldWasQuoted) {
      inQuotes = true;
      fieldWasQuoted = true;
      quoteOpenedAt = line;
      i += 1;
    } else {
      if (fieldWasQuoted) recordMalformed ??= 'unexpected text after a closing quote';
      field += ch;
      i += 1;
    }
  }

  if (inQuotes) {
    return {
      ok: false,
      error: {
        code: 'unterminated_quote',
        message: `A quoted field that starts on line ${quoteOpenedAt} is never closed`,
        line: quoteOpenedAt,
      },
    };
  }
  if (cells.length > 0 || field !== '' || fieldWasQuoted) endRecord();
  return { ok: true, records };
}

// ---------------------------------------------------------------------------------------------
// Formula guard
// ---------------------------------------------------------------------------------------------

const GUARD_TRIGGER = /^'*[=+\-@\t\r]/;
const GUARDED = /^'+[=+\-@\t\r]/;

/**
 * Neutralise spreadsheet formula injection on export: a cell that starts with `= + - @ TAB CR`
 * (optionally behind apostrophes already) gets one leading apostrophe. Counting existing
 * apostrophes keeps the transform reversible, so a name such as `'=x` survives a round trip.
 */
export function guardFormula(cell: string): string {
  return GUARD_TRIGGER.test(cell) ? `'${cell}` : cell;
}

/** Inverse of {@link guardFormula}: drop exactly one apostrophe from a guarded cell. */
export function unguardFormula(cell: string): string {
  return GUARDED.test(cell) ? cell.slice(1) : cell;
}

// ---------------------------------------------------------------------------------------------
// Import
// ---------------------------------------------------------------------------------------------

/** UTF-8 byte length without allocating. */
export function utf8ByteLength(text: string): number {
  let bytes = 0;
  for (let i = 0; i < text.length; i += 1) {
    const unit = text.charCodeAt(i);
    if (unit < 0x80) bytes += 1;
    else if (unit < 0x800) bytes += 2;
    else if (unit >= 0xd800 && unit <= 0xdbff && i + 1 < text.length) {
      const next = text.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        bytes += 4;
        i += 1;
      } else {
        bytes += 3;
      }
    } else bytes += 3;
  }
  return bytes;
}

/** `Company Name` / `company-name` -> `company_name`. */
export function normalizeHeader(header: string): string {
  return trimText(header).toLowerCase().replace(/[\s-]/gu, '_');
}

export type ValidatedRow =
  | { ok: true; posting: Omit<RawPosting, 'source_kind' | 'source_ref'>; observed_at: string }
  | { ok: false; errors: Array<{ field: string; message: string }> };

/**
 * Validate one row of already-trimmed, already-un-guarded values keyed by normalized column
 * name. Shared by the importer and by in-place correction of rejected rows in the UI.
 * Every invalid field is reported, not only the first.
 */
export function validateImportRow(
  values: Readonly<Record<string, string | undefined>>,
  importedAt: string,
): ValidatedRow {
  const errors: Array<{ field: string; message: string }> = [];
  const take = <T>(field: string, check: Check<T>, fallback: T): T => {
    if (check.ok) return check.value;
    errors.push({ field, message: check.message });
    return fallback;
  };

  const company_name = take(
    'company_name',
    checkRequiredText(values.company_name, 'company_name', LIMITS.company_name),
    '',
  );
  const title = take('title', checkRequiredText(values.title, 'title', LIMITS.title), '');
  const location = take(
    'location',
    checkOptionalText(values.location, 'location', LIMITS.location),
    null,
  );
  const work_mode = take('work_mode', checkWorkMode(values.work_mode), 'unknown' as WorkMode);
  const department = take(
    'department',
    checkOptionalText(values.department, 'department', LIMITS.department),
    null,
  );
  const url = take('url', checkUrl(values.url), null);
  const posted_at = take('posted_at', checkDate(values.posted_at, 'posted_at'), null);
  const source_posting_id = take(
    'source_posting_id',
    checkOptionalText(values.source_posting_id, 'source_posting_id', null),
    null,
  );
  const observed = take(
    'observed_at',
    checkOptionalTimestamp(values.observed_at, 'observed_at'),
    null,
  );

  if (errors.length > 0) return { ok: false, errors };
  return {
    ok: true,
    posting: {
      source_posting_id,
      company_name,
      title,
      location,
      work_mode,
      department,
      url,
      posted_at,
    },
    observed_at: observed ?? importedAt,
  };
}

function emptyResult(label: string, fileError: CsvFileError): CsvImportResult {
  return {
    ok: false,
    file_error: fileError,
    dataset_label: label,
    accepted: 0,
    rejected: 0,
    errors: [],
    warnings: [],
    rejected_rows: [],
    snapshots: [],
  };
}

/**
 * Import CSV text as additive `csv` snapshots (spec 05). Rows are validated one by one: invalid
 * rows are rejected with line-numbered errors and the valid rows are kept. File-level problems
 * (size, row cap, unterminated quote, duplicate or missing headers, bad dataset label) reject the
 * whole file and produce no snapshots.
 *
 * @throws EngineInputError when `imported_at` is not a valid UTC timestamp (a caller bug).
 */
export function importCsv(text: string, options: CsvImportOptions): CsvImportResult {
  const importedAt = checkTimestamp(options.imported_at, 'imported_at');
  if (!importedAt.ok) {
    throw new EngineInputError([{ path: 'imported_at', message: importedAt.message }]);
  }
  const label = checkRequiredText(options.dataset_label, 'dataset_label', LIMITS.source_ref);
  if (!label.ok) {
    return emptyResult(trimText(String(options.dataset_label ?? '')), {
      code: 'invalid_dataset_label',
      message: label.message,
    });
  }
  const datasetLabel = label.value;

  const bytes = utf8ByteLength(text);
  if (bytes > CSV_MAX_BYTES) {
    return emptyResult(datasetLabel, {
      code: 'too_large',
      message: `The file is ${bytes} bytes; the limit is ${CSV_MAX_BYTES} bytes (1 MiB)`,
    });
  }

  const parsed = parseCsv(text);
  if (!parsed.ok) return emptyResult(datasetLabel, parsed.error);
  const [header, ...rows] = parsed.records;
  if (header === undefined) {
    return emptyResult(datasetLabel, {
      code: 'empty_file',
      message: 'The file has no header row',
      line: 1,
    });
  }
  if (rows.length > CSV_MAX_ROWS) {
    return emptyResult(datasetLabel, {
      code: 'too_many_rows',
      message: `The file has ${rows.length} data rows; the limit is ${CSV_MAX_ROWS}`,
    });
  }

  // Header: normalize names, reject duplicates, ignore (and warn about) unknown columns.
  const warnings: CsvWarning[] = [];
  const columnIndex = new Map<PostingColumn, number>();
  const unknownColumns = new Set<number>();
  const seen = new Map<string, number>();
  const known = new Set<string>(POSTING_COLUMNS);
  for (let index = 0; index < header.cells.length; index += 1) {
    const name = normalizeHeader(header.cells[index] ?? '');
    if (name === '') {
      warnings.push({
        line: header.line,
        message: `Column ${index + 1} has no header name and is ignored`,
      });
      unknownColumns.add(index);
      continue;
    }
    const earlier = seen.get(name);
    if (earlier !== undefined) {
      return emptyResult(datasetLabel, {
        code: 'duplicate_header',
        message: `Column "${name}" appears more than once (columns ${earlier + 1} and ${index + 1})`,
        line: header.line,
      });
    }
    seen.set(name, index);
    if (known.has(name)) {
      columnIndex.set(name as PostingColumn, index);
    } else {
      unknownColumns.add(index);
      warnings.push({ line: header.line, message: `Unknown column "${name}" is ignored` });
    }
  }
  for (const required of REQUIRED_COLUMNS) {
    if (!columnIndex.has(required)) {
      return emptyResult(datasetLabel, {
        code: 'missing_required_column',
        message: `The required column "${required}" is missing from the header`,
        line: header.line,
      });
    }
  }

  const errors: CsvRowError[] = [];
  const rejectedRows: CsvRejectedRow[] = [];
  const byObservedAt = new Map<string, RawPosting[]>();
  let accepted = 0;

  for (const row of rows) {
    const values: Record<string, string> = {};
    for (const [column, index] of columnIndex) {
      values[column] = unguardFormula(trimText(row.cells[index] ?? ''));
    }
    const rowErrors: CsvRowError[] = [];
    if (row.malformed !== undefined) {
      rowErrors.push({ line: row.line, message: `Malformed row: ${row.malformed}` });
    }
    if (row.cells.length > header.cells.length) {
      const extra = row.cells.slice(header.cells.length);
      if (extra.some((cell) => trimText(cell) !== '')) {
        rowErrors.push({
          line: row.line,
          message:
            `Row has ${row.cells.length} fields but the header has ${header.cells.length}; ` +
            'quote any field that contains a comma',
        });
      }
    }
    const validated = validateImportRow(values, importedAt.value);
    if (!validated.ok) {
      for (const error of validated.errors) {
        rowErrors.push({ line: row.line, field: error.field, message: error.message });
      }
    }

    if (rowErrors.length > 0 || !validated.ok) {
      errors.push(...rowErrors);
      rejectedRows.push({ line: row.line, values, errors: rowErrors });
      continue;
    }
    accepted += 1;
    const posting: RawPosting = {
      source_kind: 'csv',
      source_ref: datasetLabel,
      ...validated.posting,
    };
    const group = byObservedAt.get(validated.observed_at);
    if (group === undefined) byObservedAt.set(validated.observed_at, [posting]);
    else group.push(posting);
  }

  const prefix =
    options.snapshot_id_prefix ?? `csv_${sha12(`${datasetLabel}\n${importedAt.value}\n${text}`)}`;
  const snapshots: ParsedSnapshot[] = Array.from(byObservedAt.keys())
    .sort()
    .map((observedAt, position) => ({
      snapshot_id: `${prefix}-${position + 1}`,
      source_kind: 'csv' as const,
      source_ref: datasetLabel,
      observed_at: observedAt,
      mode: 'additive' as const,
      postings: byObservedAt.get(observedAt) ?? [],
    }));

  return {
    ok: true,
    file_error: null,
    dataset_label: datasetLabel,
    accepted,
    rejected: rejectedRows.length,
    errors,
    warnings,
    rejected_rows: rejectedRows,
    snapshots,
  };
}

// ---------------------------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------------------------

export interface CsvWriteOptions {
  /** Prefix a UTF-8 BOM so spreadsheet apps detect the encoding. Default false. */
  bom?: boolean;
}

type Cell = string | number | null;

/** U+FEFF, written by code point so the source file holds no invisible character. */
const UTF8_BOM = String.fromCharCode(0xfeff);

function quoteCell(cell: string): string {
  return /[",\r\n]/u.test(cell) ? `"${cell.replace(/"/gu, '""')}"` : cell;
}

/** Serialize rows as RFC 4180 CSV (CRLF line endings, trailing CRLF). */
export function writeCsv(
  rows: ReadonlyArray<ReadonlyArray<Cell>>,
  options?: CsvWriteOptions,
): string {
  const lines = rows.map((row) =>
    row
      .map((cell) => {
        if (cell === null) return '';
        return quoteCell(typeof cell === 'number' ? String(cell) : cell);
      })
      .join(','),
  );
  const body = lines.length === 0 ? '' : `${lines.join('\r\n')}\r\n`;
  return options?.bom === true ? `${UTF8_BOM}${body}` : body;
}

/** A text cell with the formula guard applied (null stays blank). */
function guarded(value: string | null): string | null {
  return value === null ? null : guardFormula(value);
}

/** One posting as a CSV row; `observed_at` null leaves the column blank (= import time). */
export interface CsvPostingRow {
  company_name: string;
  title: string;
  location: string | null;
  work_mode: WorkMode;
  department: string | null;
  url: string | null;
  posted_at: string | null;
  source_posting_id: string | null;
  observed_at: string | null;
}

/** Export postings in the import format. `importCsv` reads the result back unchanged. */
export function exportPostingsCsv(
  rows: readonly CsvPostingRow[],
  options?: CsvWriteOptions,
): string {
  const table: Cell[][] = [Array.from(POSTING_COLUMNS)];
  for (const row of rows) {
    table.push([
      guarded(row.company_name),
      guarded(row.title),
      guarded(row.location),
      guarded(row.work_mode),
      guarded(row.department),
      guarded(row.url),
      guarded(row.posted_at),
      guarded(row.source_posting_id),
      guarded(row.observed_at),
    ]);
  }
  return writeCsv(table, options);
}

/** Flatten snapshots into export rows (each posting carries its snapshot's observed_at). */
export function snapshotsToPostingRows(
  snapshots: ReadonlyArray<Pick<ParsedSnapshot, 'observed_at' | 'postings'>>,
): CsvPostingRow[] {
  const rows: CsvPostingRow[] = [];
  for (const snapshot of snapshots) {
    for (const posting of snapshot.postings) {
      rows.push({
        company_name: posting.company_name,
        title: posting.title,
        location: posting.location,
        work_mode: posting.work_mode,
        department: posting.department,
        url: posting.url,
        posted_at: posting.posted_at,
        source_posting_id: posting.source_posting_id,
        observed_at: snapshot.observed_at,
      });
    }
  }
  return rows;
}

// ---------------------------------------------------------------------------------------------
// Shortlist export
// ---------------------------------------------------------------------------------------------

export interface ShortlistEntryInput {
  company_id: string;
  note?: string | null;
}

export interface ShortlistRow {
  rank: number | null;
  company: string;
  /** score / 10 with one decimal ("64.0"); blank when the company has no score. */
  score: string;
  coverage_percent: number;
  active_roles: number;
  relevant_roles: number | null;
  last_seen: string | null;
  strongest_evidence: string;
  missing_information: string;
  note: string;
  as_of: string;
}

function strongestEvidence(company: CompanyAnalysis): string {
  let best: ScoreComponent | null = null;
  let bestContribution = -1;
  for (const component of company.components) {
    if (component.value === null) continue;
    const contribution = component.value * component.weight;
    if (contribution > bestContribution) {
      best = component;
      bestContribution = contribution;
    }
  }
  if (best === null) return '';
  return `${COMPONENT_NAMES[best.key]}: ${describeComponent(best)}`;
}

function missingInformation(company: CompanyAnalysis): string {
  return company.components
    .filter((component) => component.value === null)
    .map((component) => {
      const reason =
        component.reason_code === null ? 'unknown' : REASON_TEXT[component.reason_code];
      return `${COMPONENT_NAMES[component.key]}: ${reason}`;
    })
    .join('; ');
}

/**
 * Join shortlisted companies with their analysis. Rows follow the analysis order (rank first).
 * Companies named by an entry but absent from the analysis are reported in `unknown_company_ids`
 * instead of being silently dropped.
 */
export function buildShortlistRows(
  analysis: Analysis,
  entries: readonly ShortlistEntryInput[],
): { rows: ShortlistRow[]; unknown_company_ids: string[] } {
  const notes = new Map<string, string>();
  for (const entry of entries) notes.set(entry.company_id, entry.note ?? '');
  const rows: ShortlistRow[] = [];
  for (const company of analysis.companies) {
    const note = notes.get(company.company_id);
    if (note === undefined) continue;
    rows.push({
      rank: company.rank,
      company: company.name,
      score: formatScore(company.score),
      coverage_percent: company.coverage,
      active_roles: company.active_roles,
      relevant_roles: company.relevant_roles,
      last_seen: company.last_seen,
      strongest_evidence: strongestEvidence(company),
      missing_information: missingInformation(company),
      note,
      as_of: analysis.as_of,
    });
  }
  const present = new Set(analysis.companies.map((company) => company.company_id));
  const unknown = entries.map((entry) => entry.company_id).filter((id) => !present.has(id));
  return { rows, unknown_company_ids: unknown };
}

/** Shortlist CSV: `rank, company, score, coverage_percent, …, note, as_of` (formula-guarded). */
export function exportShortlistCsv(
  rows: readonly ShortlistRow[],
  options?: CsvWriteOptions,
): string {
  const table: Cell[][] = [Array.from(SHORTLIST_COLUMNS)];
  for (const row of rows) {
    table.push([
      row.rank,
      guarded(row.company),
      guarded(row.score),
      row.coverage_percent,
      row.active_roles,
      row.relevant_roles,
      guarded(row.last_seen),
      guarded(row.strongest_evidence),
      guarded(row.missing_information),
      guarded(row.note),
      guarded(row.as_of),
    ]);
  }
  return writeCsv(table, options);
}
