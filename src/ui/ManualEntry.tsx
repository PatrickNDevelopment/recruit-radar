import { useState } from 'react';
import type { PostingFormValues } from '../data/types';
import { useApp } from './AppContext';
import { ErrorSummary, SelectField, TextField } from './components';
import { FIELD_LABELS } from './copy';

const EMPTY: PostingFormValues = {
  company_name: '',
  title: '',
  location: '',
  work_mode: 'unknown',
  department: '',
  url: '',
  posted_at: '',
  source_posting_id: '',
};

const WORK_MODES = [
  { value: 'unknown', label: 'Unknown (not stated)' },
  { value: 'remote', label: 'Remote' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'onsite', label: 'Onsite' },
];

/** The fields of one posting, shared by manual entry and by in-place CSV correction. */
export function PostingFields({
  values,
  onChange,
  problems,
  idPrefix,
}: {
  values: PostingFormValues;
  onChange: (next: PostingFormValues) => void;
  problems: Readonly<Record<string, string>>;
  idPrefix?: string;
}) {
  const set = (field: keyof PostingFormValues) => (value: string) =>
    onChange({ ...values, [field]: value });
  const prefix = idPrefix === undefined ? '' : `${idPrefix} `;
  return (
    <div className="form-grid">
      <TextField
        label={`${prefix}Company name`}
        required
        value={values.company_name}
        onChange={set('company_name')}
        error={problems.company_name}
        autoComplete="organization"
      />
      <TextField
        label={`${prefix}Job title`}
        required
        value={values.title}
        onChange={set('title')}
        error={problems.title}
      />
      <TextField
        label={`${prefix}Location`}
        value={values.location}
        onChange={set('location')}
        error={problems.location}
      />
      <SelectField
        label={`${prefix}Work mode`}
        value={values.work_mode === '' ? 'unknown' : values.work_mode}
        onChange={set('work_mode')}
        options={WORK_MODES}
        error={problems.work_mode}
      />
      <TextField
        label={`${prefix}Department`}
        value={values.department}
        onChange={set('department')}
        error={problems.department}
      />
      <TextField
        label={`${prefix}Posting URL`}
        type="url"
        inputMode="url"
        value={values.url}
        onChange={set('url')}
        error={problems.url}
        hint="Only http:// or https:// addresses are accepted."
      />
      <TextField
        label={`${prefix}Posted date`}
        value={values.posted_at}
        onChange={set('posted_at')}
        placeholder="YYYY-MM-DD"
        inputMode="numeric"
        error={problems.posted_at}
        hint="Optional. A real calendar date, for example 2026-09-30."
      />
      <TextField
        label={`${prefix}Posting ID`}
        value={values.source_posting_id}
        onChange={set('source_posting_id')}
        error={problems.source_posting_id}
        hint="Optional. Only needed to tell two identical openings apart."
      />
    </div>
  );
}

export function ManualEntry() {
  const { state, store } = useApp();
  const [values, setValues] = useState<PostingFormValues>(EMPTY);
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState<Array<{ label: string; message: string }>>([]);

  const submit = async () => {
    const result = await store.addManualPosting(values);
    if (!result.ok) {
      // The status region already carries the failure; the form keeps what was typed.
      return;
    }
    if (result.value.ok) {
      setValues(EMPTY);
      setProblems({});
      setSummary([]);
      return;
    }
    const byField: Record<string, string> = {};
    for (const problem of result.value.problems) {
      if (byField[problem.field] === undefined) byField[problem.field] = problem.message;
    }
    setProblems(byField);
    setSummary(
      result.value.problems.map((problem) => ({
        label: FIELD_LABELS[problem.field] ?? problem.field,
        message: problem.message,
      })),
    );
  };

  return (
    <form
      className="stack"
      noValidate
      aria-label="Add a posting"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <ErrorSummary title="The posting was not added. Please fix:" problems={summary} />
      <PostingFields values={values} onChange={setValues} problems={problems} />
      <div>
        <button type="submit" className="btn btn--primary" disabled={state.pending > 0}>
          Add posting
        </button>
      </div>
    </form>
  );
}
