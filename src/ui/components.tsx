/** Small shared building blocks. Every control here is a real, labelled HTML element. */
import { useEffect, useId, useRef, type ReactNode } from 'react';
import { safeLink, scoreText, shortUrl } from './format';

// ---------------------------------------------------------------------------------------------
// Links
// ---------------------------------------------------------------------------------------------

/**
 * A link to a URL that came from data. Only http(s) URLs become links; anything else is shown
 * as plain text so a `javascript:` or `data:` value can never be clicked.
 */
export function DataLink({ url, label }: { url: string | null; label?: string }) {
  const safe = safeLink(url);
  if (url === null) return <span className="muted">No URL</span>;
  if (safe === null) return <span>{url}</span>;
  return (
    <a href={safe} target="_blank" rel="noopener noreferrer">
      {label ?? shortUrl(safe)}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

// ---------------------------------------------------------------------------------------------
// Form fields
// ---------------------------------------------------------------------------------------------

interface FieldBase {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  required?: boolean;
}

function describedBy(...ids: Array<string | null>): string | undefined {
  const present = ids.filter((id): id is string => id !== null);
  return present.length === 0 ? undefined : present.join(' ');
}

function FieldFrame({
  id,
  label,
  hint,
  error,
  required,
  hintId,
  errorId,
  children,
}: FieldBase & { id: string; hintId: string; errorId: string; children: ReactNode }) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
        {required === true ? <span className="req"> (required)</span> : null}
      </label>
      {children}
      {hint === undefined ? null : (
        <div id={hintId} className="field-hint">
          {hint}
        </div>
      )}
      {error === undefined || error === null ? null : (
        <div id={errorId} className="field-error">
          Error: {error}
        </div>
      )}
    </div>
  );
}

export function TextField(
  props: FieldBase & {
    value: string;
    onChange: (value: string) => void;
    type?: 'text' | 'search' | 'number' | 'url';
    name?: string;
    placeholder?: string;
    maxLength?: number;
    inputMode?: 'text' | 'numeric' | 'decimal' | 'url' | 'search';
    autoComplete?: string;
    disabled?: boolean;
    min?: number;
    max?: number;
    step?: number;
  },
) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const hasError = props.error !== undefined && props.error !== null;
  return (
    <FieldFrame {...props} id={id} hintId={hintId} errorId={errorId}>
      <input
        id={id}
        name={props.name}
        type={props.type ?? 'text'}
        value={props.value}
        placeholder={props.placeholder}
        maxLength={props.maxLength}
        inputMode={props.inputMode}
        autoComplete={props.autoComplete ?? 'off'}
        disabled={props.disabled}
        min={props.min}
        max={props.max}
        step={props.step}
        aria-required={props.required === true ? true : undefined}
        aria-invalid={hasError ? true : undefined}
        aria-describedby={describedBy(
          props.hint === undefined ? null : hintId,
          hasError ? errorId : null,
        )}
        spellCheck={false}
        onChange={(event) => props.onChange(event.target.value)}
      />
    </FieldFrame>
  );
}

export function SelectField(
  props: FieldBase & {
    value: string;
    onChange: (value: string) => void;
    options: ReadonlyArray<{ value: string; label: string }>;
    name?: string;
    disabled?: boolean;
  },
) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const hasError = props.error !== undefined && props.error !== null;
  return (
    <FieldFrame {...props} id={id} hintId={hintId} errorId={errorId}>
      <select
        id={id}
        name={props.name}
        value={props.value}
        disabled={props.disabled}
        aria-invalid={hasError ? true : undefined}
        aria-describedby={describedBy(
          props.hint === undefined ? null : hintId,
          hasError ? errorId : null,
        )}
        onChange={(event) => props.onChange(event.target.value)}
      >
        {props.options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </FieldFrame>
  );
}

export function TextAreaField(
  props: FieldBase & {
    value: string;
    onChange: (value: string) => void;
    rows?: number;
    mono?: boolean;
    maxLength?: number;
    name?: string;
    placeholder?: string;
    disabled?: boolean;
  },
) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const hasError = props.error !== undefined && props.error !== null;
  return (
    <FieldFrame {...props} id={id} hintId={hintId} errorId={errorId}>
      <textarea
        id={id}
        name={props.name}
        className={props.mono === true ? 'mono' : undefined}
        value={props.value}
        rows={props.rows ?? 5}
        maxLength={props.maxLength}
        placeholder={props.placeholder}
        disabled={props.disabled}
        spellCheck={false}
        aria-required={props.required === true ? true : undefined}
        aria-invalid={hasError ? true : undefined}
        aria-describedby={describedBy(
          props.hint === undefined ? null : hintId,
          hasError ? errorId : null,
        )}
        onChange={(event) => props.onChange(event.target.value)}
      />
    </FieldFrame>
  );
}

export function CheckboxField({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="check">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <label htmlFor={id}>{label}</label>
    </div>
  );
}

/** A list of problems shown above a form after a failed submit. */
export function ErrorSummary({
  id,
  title,
  problems,
}: {
  id?: string;
  title: string;
  problems: ReadonlyArray<{ label: string; message: string }>;
}) {
  if (problems.length === 0) return null;
  return (
    <div className="error-summary" role="alert" id={id}>
      <strong>{title}</strong>
      <ul>
        {problems.map((problem) => (
          <li key={`${problem.label}:${problem.message}`}>
            {problem.label}: {problem.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Dialog (native <dialog>: focus trap, Escape and focus return come from the platform)
// ---------------------------------------------------------------------------------------------

export function Dialog({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = ref.current;
    if (element === null) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);
  return (
    <dialog ref={ref} aria-labelledby={titleId} onClose={onClose}>
      {open ? (
        <div className="dialog-body">
          <h2 id={titleId}>{title}</h2>
          {children}
        </div>
      ) : null}
    </dialog>
  );
}

// ---------------------------------------------------------------------------------------------
// Tables and scores
// ---------------------------------------------------------------------------------------------

/**
 * Wide tables scroll inside their own labelled, keyboard-focusable region, so the page itself
 * never scrolls sideways (WCAG 1.4.10).
 */
export function TableRegion({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="table-scroll" role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}

export function ScoreMeter({ score, coverage }: { score: number | null; coverage: number }) {
  return (
    <div className="score-cell">
      <span className="score-number">{scoreText(score)}</span>
      {score === null ? null : (
        <div className="meter" aria-hidden="true">
          <span style={{ width: `${Math.min(100, score / 10)}%` }} />
        </div>
      )}
      <span className="small muted">Coverage {coverage}%</span>
    </div>
  );
}

const RING_SCORE_RADIUS = 48;
const RING_COVERAGE_RADIUS = 38;

/** Score on the outer ring, coverage on the thin inner ring; the numbers repeat in text. */
export function ScoreRing({ score, coverage }: { score: number | null; coverage: number }) {
  const outer = 2 * Math.PI * RING_SCORE_RADIUS;
  const inner = 2 * Math.PI * RING_COVERAGE_RADIUS;
  const scoreFraction = score === null ? 0 : Math.max(0, Math.min(1, score / 1000));
  const coverageFraction = Math.max(0, Math.min(1, coverage / 100));
  return (
    <svg
      className="score-ring"
      width="132"
      height="132"
      viewBox="0 0 120 120"
      aria-hidden="true"
      focusable="false"
    >
      <circle className="track" cx="60" cy="60" r={RING_SCORE_RADIUS} />
      <circle
        className="value"
        cx="60"
        cy="60"
        r={RING_SCORE_RADIUS}
        strokeDasharray={`${outer * scoreFraction} ${outer}`}
        transform="rotate(-90 60 60)"
      />
      <circle className="coverage-track" cx="60" cy="60" r={RING_COVERAGE_RADIUS} />
      <circle
        className="coverage-value"
        cx="60"
        cy="60"
        r={RING_COVERAGE_RADIUS}
        strokeDasharray={`${inner * coverageFraction} ${inner}`}
        transform="rotate(-90 60 60)"
      />
      <text x="60" y="62" textAnchor="middle" fontSize={score === null ? 14 : 24}>
        {score === null ? 'Not scored' : scoreText(score)}
      </text>
      <text className="sub" x="60" y="80" textAnchor="middle" fontSize="10">
        {score === null ? '' : 'of 100'}
      </text>
    </svg>
  );
}

export function Pill({
  tone,
  children,
}: {
  tone?: 'sample' | 'live' | 'bad' | 'ok';
  children: ReactNode;
}) {
  return <span className={tone === undefined ? 'pill' : `pill pill--${tone}`}>{children}</span>;
}
