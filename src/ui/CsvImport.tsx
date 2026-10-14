import { useState } from 'react';
import {
  CSV_MAX_BYTES,
  exportPostingsCsv,
  validateImportRow,
  type CsvRejectedRow,
} from '../engine';
import type { ImportReport, PostingFormValues } from '../data/types';
import { useApp, useWorkspace } from './AppContext';
import { ErrorSummary, TableRegion, TextAreaField, TextField } from './components';
import { FIELD_LABELS } from './copy';
import { formatBytes } from './format';
import { PostingFields } from './ManualEntry';

const MAX_LISTED_ERRORS = 200;
const MAX_FIX_FORMS = 50;

const WORK_MODE_VALUES = ['remote', 'hybrid', 'onsite', 'unknown'];

function toForm(values: Readonly<Record<string, string>>): PostingFormValues {
  const mode = (values.work_mode ?? '').trim().toLowerCase();
  return {
    company_name: values.company_name ?? '',
    title: values.title ?? '',
    location: values.location ?? '',
    work_mode: WORK_MODE_VALUES.includes(mode) ? mode : 'unknown',
    department: values.department ?? '',
    url: values.url ?? '',
    posted_at: values.posted_at ?? '',
    source_posting_id: values.source_posting_id ?? '',
  };
}

function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

function FixRow({
  row,
  datasetLabel,
  open,
  onFixed,
}: {
  row: CsvRejectedRow;
  datasetLabel: string;
  open: boolean;
  onFixed: (line: number) => void;
}) {
  const { store, state } = useApp();
  const workspace = useWorkspace();
  const [values, setValues] = useState<PostingFormValues>(() => toForm(row.values));
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState<Array<{ label: string; message: string }>>([]);

  const submit = async () => {
    const trimmed: Record<string, string> = {};
    for (const [field, value] of Object.entries(values)) trimmed[field] = value.trim();
    if (row.values.observed_at !== undefined) trimmed.observed_at = row.values.observed_at;
    const checked = validateImportRow(trimmed, workspace.analysis.as_of);
    if (!checked.ok) {
      const byField: Record<string, string> = {};
      for (const problem of checked.errors) {
        if (byField[problem.field] === undefined) byField[problem.field] = problem.message;
      }
      setProblems(byField);
      setSummary(
        checked.errors.map((problem) => ({
          label: FIELD_LABELS[problem.field] ?? problem.field,
          message: problem.message,
        })),
      );
      return;
    }
    setProblems({});
    setSummary([]);
    const observed = (row.values.observed_at ?? '').trim();
    const text = exportPostingsCsv([
      {
        ...checked.posting,
        observed_at: observed === '' ? null : observed,
      },
    ]);
    const result = await store.importCsv(datasetLabel, text);
    if (result.ok && result.value.ok && result.value.accepted === 1) onFixed(row.line);
  };

  return (
    <details className="fix" open={open} data-testid="fix-row">
      <summary>
        Line {row.line}: {row.values.company_name || 'no company'} —{' '}
        {row.values.title || 'no title'} ({row.errors.length}{' '}
        {row.errors.length === 1 ? 'problem' : 'problems'})
      </summary>
      <form
        className="fix-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <ul>
          {row.errors.map((error, index) => (
            <li key={`${error.field ?? 'row'}-${index}`}>
              {error.field === undefined ? 'Row' : (FIELD_LABELS[error.field] ?? error.field)}:{' '}
              {error.message}
            </li>
          ))}
        </ul>
        <ErrorSummary title="Still not valid:" problems={summary} />
        <PostingFields
          values={values}
          onChange={setValues}
          problems={problems}
          idPrefix={`Line ${row.line}`}
        />
        <div>
          <button
            type="submit"
            className="btn btn--primary btn--small"
            disabled={state.pending > 0}
          >
            Add corrected line {row.line}
          </button>
        </div>
      </form>
    </details>
  );
}

function Report({
  report,
  corrected,
  onFixed,
}: {
  report: ImportReport;
  corrected: ReadonlySet<number>;
  onFixed: (line: number) => void;
}) {
  const fixable = report.rejected_rows.filter((row) => !corrected.has(row.line));
  const listedErrors = report.errors.filter((error) => !corrected.has(error.line));
  const extraErrors = Math.max(0, listedErrors.length - MAX_LISTED_ERRORS);
  const stillRejected = fixable.length;

  if (!report.ok) {
    return (
      <div className="error-summary" role="alert" data-testid="import-report">
        <strong>Nothing was imported: the file was rejected.</strong>
        <p>
          {report.file_error?.message ?? 'The file could not be read.'}
          {report.file_error?.line === undefined ? '' : ` (line ${report.file_error.line})`}
        </p>
      </div>
    );
  }

  return (
    <section className="stack" aria-label="Import report" data-testid="import-report">
      <p className="report-summary" role="status">
        <span>Dataset: {report.dataset_label}</span>
        <span>Accepted: {report.accepted + corrected.size}</span>
        <span>Rejected: {stillRejected}</span>
        {report.warnings.length > 0 ? <span>Warnings: {report.warnings.length}</span> : null}
      </p>

      {report.warnings.length > 0 ? (
        <ul className="small" aria-label="Warnings">
          {report.warnings.map((warning, index) => (
            <li key={`${warning.line}-${index}`}>
              Line {warning.line}: {warning.message}
            </li>
          ))}
        </ul>
      ) : null}

      {listedErrors.length === 0 ? (
        report.rejected === 0 ? (
          <p>Every row was valid.</p>
        ) : (
          <p>All rejected rows have been corrected and added.</p>
        )
      ) : (
        <>
          <h3>Rejected rows</h3>
          <p className="small muted">
            These rows were not imported; all other rows were. Open a line below to correct it and
            add it to “{report.dataset_label}”.
          </p>
          <TableRegion label="Rejected rows and their problems">
            <table className="data-table" style={{ minWidth: '34rem' }}>
              <thead>
                <tr>
                  <th scope="col">CSV line</th>
                  <th scope="col">Field</th>
                  <th scope="col">Problem</th>
                </tr>
              </thead>
              <tbody>
                {listedErrors.slice(0, MAX_LISTED_ERRORS).map((error, index) => (
                  <tr
                    key={`${error.line}-${error.field ?? ''}-${index}`}
                    data-testid="import-error"
                  >
                    <td className="num">{error.line}</td>
                    <td>
                      {error.field === undefined ? '—' : (FIELD_LABELS[error.field] ?? error.field)}
                    </td>
                    <td>{error.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableRegion>
          {extraErrors > 0 ? (
            <p className="small muted">…and {extraErrors} more problems not listed here.</p>
          ) : null}

          <h3>Correct in place</h3>
          <div className="stack">
            {fixable.slice(0, MAX_FIX_FORMS).map((row, index) => (
              <FixRow
                key={row.line}
                row={row}
                datasetLabel={report.dataset_label}
                open={index === 0}
                onFixed={onFixed}
              />
            ))}
          </div>
          {fixable.length > MAX_FIX_FORMS ? (
            <p className="small muted">
              {fixable.length - MAX_FIX_FORMS} more rejected rows are not shown as forms. Fix them
              in the file and import it again.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

export function CsvImport() {
  const { state, store } = useApp();
  const [label, setLabel] = useState('');
  const [text, setText] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [corrected, setCorrected] = useState<ReadonlySet<number>>(new Set());
  const [labelError, setLabelError] = useState<string | null>(null);
  const [textError, setTextError] = useState<string | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);

  const onFile = async (file: File | undefined) => {
    setTextError(null);
    if (file === undefined) return;
    if (file.size > CSV_MAX_BYTES) {
      setTextError(
        `This file is ${formatBytes(file.size)}; the limit is ${formatBytes(CSV_MAX_BYTES)}. Split it into smaller files.`,
      );
      setFileInputKey((key) => key + 1);
      return;
    }
    try {
      const content = await file.text();
      setText(content);
      setFileName(file.name);
      if (label.trim() === '') setLabel(file.name.replace(/\.[A-Za-z0-9]{1,5}$/u, ''));
    } catch {
      setTextError('The file could not be read. Try again, or paste its content instead.');
    }
  };

  const submit = async () => {
    let valid = true;
    if (label.trim() === '') {
      setLabelError('Give this dataset a label so you can tell it apart later.');
      valid = false;
    } else {
      setLabelError(null);
    }
    if (text.trim() === '') {
      setTextError('Choose a CSV file or paste CSV text first.');
      valid = false;
    } else if (byteLength(text) > CSV_MAX_BYTES) {
      setTextError(`The text is larger than ${formatBytes(CSV_MAX_BYTES)}.`);
      valid = false;
    } else {
      setTextError(null);
    }
    if (!valid) return;
    const result = await store.importCsv(label, text);
    if (!result.ok) return;
    setReport(result.value);
    setCorrected(new Set());
    if (result.value.ok && result.value.accepted > 0) {
      setText('');
      setFileName(null);
      setFileInputKey((key) => key + 1);
    }
  };

  return (
    <div className="stack">
      <form
        className="stack"
        noValidate
        aria-label="Import a CSV file"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <TextField
          label="Dataset label"
          required
          value={label}
          onChange={setLabel}
          error={labelError}
          hint="Names this import (for example “Board export 2026-10”). Importing again with the same label adds to that dataset. Labels starting with SAMPLE- are reserved for the synthetic sample data."
        />
        <div className="field">
          <label className="field-label" htmlFor="csv-file">
            CSV file
          </label>
          <input
            key={fileInputKey}
            id="csv-file"
            type="file"
            accept=".csv,text/csv,text/plain"
            onChange={(event) => void onFile(event.target.files?.[0])}
          />
          <div className="field-hint">
            UTF-8, up to 1 MB and 5,000 rows. Required columns: company_name and title. Optional:
            location, work_mode, department, url, posted_at, source_posting_id, observed_at.
          </div>
        </div>
        <TextAreaField
          label="Or paste CSV text"
          value={text}
          onChange={(value) => {
            setText(value);
            setFileName(null);
          }}
          rows={7}
          mono
          error={textError}
          placeholder={
            'company_name,title,location,work_mode\r\nAcme Robotics,Robotics Engineer,"Denver, CO",onsite'
          }
          hint={
            text === ''
              ? undefined
              : `${fileName === null ? 'Pasted text' : fileName}: ${formatBytes(byteLength(text))}.`
          }
        />
        <div>
          <button type="submit" className="btn btn--primary" disabled={state.pending > 0}>
            Import CSV
          </button>
        </div>
      </form>
      {report === null ? null : (
        <Report
          report={report}
          corrected={corrected}
          onFixed={(line) => setCorrected((current) => new Set(current).add(line))}
        />
      )}
    </div>
  );
}
