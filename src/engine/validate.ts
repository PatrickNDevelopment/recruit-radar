/**
 * Boundary validation (spec 01 §1). Two layers share one set of field checks:
 *
 * - the `check*` functions are plain, throw-free and reused by the CSV importer so that a CSV row
 *   and an `analyze()` posting are accepted or rejected for exactly the same reasons;
 * - the Zod schemas wrap them to validate a whole `analyze()` input and report every problem with
 *   its path.
 */
import { z } from 'zod';
import { EngineInputError, formatPath, type InputIssue } from './errors';
import { codePointLength, compareCodePoints, trimText } from './normalize';
import { parseDate, parseTimestamp } from './time';
import {
  DECISION_KINDS,
  SNAPSHOT_MODES,
  SOURCE_KINDS,
  WORK_MODES,
  type ParsedInput,
  type ParsedSnapshot,
  type RawPosting,
  type SnapshotMode,
  type SourceKind,
  type WorkMode,
} from './types';

export type Check<T> = { ok: true; value: T } | { ok: false; message: string };

const ok = <T>(value: T): Check<T> => ({ ok: true, value });
const fail = <T>(message: string): Check<T> => ({ ok: false, message });

/** Length limits from spec 01 §1 (counted in code points, after trimming). */
export const LIMITS = {
  source_ref: 200,
  company_name: 200,
  title: 300,
  location: 300,
  department: 200,
  keyword: 60,
  keywords: 50,
} as const;

// ---------------------------------------------------------------------------------------------
// Field checks
// ---------------------------------------------------------------------------------------------

function overLength(field: string, max: number, length: number): string {
  return `${field} must be at most ${max} characters (got ${length})`;
}

/** Required text: trimmed, 1..max code points. */
export function checkRequiredText(raw: unknown, field: string, max: number): Check<string> {
  if (raw === undefined || raw === null) return fail(`${field} is required`);
  if (typeof raw !== 'string') return fail(`${field} must be a string`);
  const value = trimText(raw);
  if (value === '') return fail(`${field} is required`);
  // UTF-16 length is an upper bound on code-point length, so the common case needs no counting.
  if (value.length > max) {
    const length = codePointLength(value);
    if (length > max) return fail(overLength(field, max, length));
  }
  return ok(value);
}

/** Optional text: trimmed; empty or missing means null; at most `max` code points. */
export function checkOptionalText(
  raw: unknown,
  field: string,
  max: number | null,
): Check<string | null> {
  if (raw === undefined || raw === null) return ok(null);
  if (typeof raw !== 'string') return fail(`${field} must be a string or null`);
  const value = trimText(raw);
  if (value === '') return ok(null);
  if (max !== null && value.length > max) {
    const length = codePointLength(value);
    if (length > max) return fail(overLength(field, max, length));
  }
  return ok(value);
}

export function checkWorkMode(raw: unknown, field = 'work_mode'): Check<WorkMode> {
  if (raw === undefined || raw === null) return ok('unknown');
  if (typeof raw !== 'string') return fail(`${field} must be one of ${WORK_MODES.join(', ')}`);
  const value = trimText(raw);
  if (value === '') return ok('unknown');
  if ((WORK_MODES as readonly string[]).includes(value)) return ok(value as WorkMode);
  return fail(`${field} must be one of ${WORK_MODES.join(', ')} (got "${truncate(value)}")`);
}

function truncate(value: string): string {
  const points = Array.from(value);
  return points.length > 40 ? `${points.slice(0, 40).join('')}…` : value;
}

// No `u` flag on purpose: with it, `i` would use Unicode case folding and let U+017F (long s)
// pose as the "s" of "https". ASCII case-insensitivity only, exactly like the Python engine's
// `re.ASCII | re.IGNORECASE`.
const HTTP_SCHEME = /^https?:/i;

/**
 * True when `value` starts with the `http:` or `https:` scheme (ASCII case-insensitive).
 *
 * Spec 01 section 1 constrains the *scheme* only ("only http:/https: schemes; anything else is
 * rejected"), so that is all this checks: `javascript:`, `data:`, `ftp:`, relative and scheme-less
 * values, and a scheme smuggled past a filter with an embedded tab (`ht\ttps:`) are all not
 * http(s); no further URL grammar is enforced. The Python engine and the backend intake apply the
 * identical rule (docs/spec/ambiguities/differential.md D-8). Whether a value is also a *usable
 * link* is a presentation decision (`src/ui/format.ts`), not a validity one.
 */
export function isHttpUrl(value: string): boolean {
  return HTTP_SCHEME.test(value);
}

export function checkUrl(raw: unknown, field = 'url'): Check<string | null> {
  if (raw === undefined || raw === null) return ok(null);
  if (typeof raw !== 'string') return fail(`${field} must be a string or null`);
  const value = trimText(raw);
  if (value === '') return ok(null);
  if (!isHttpUrl(value)) return fail(`${field} must be an http:// or https:// URL`);
  return ok(value);
}

/** Optional `YYYY-MM-DD` that must be a real calendar date. */
export function checkDate(raw: unknown, field: string): Check<string | null> {
  if (raw === undefined || raw === null) return ok(null);
  if (typeof raw !== 'string') return fail(`${field} must be a YYYY-MM-DD date or null`);
  const value = trimText(raw);
  if (value === '') return ok(null);
  if (parseDate(value) === null) {
    return fail(
      `${field} must be a real calendar date in YYYY-MM-DD format (got "${truncate(value)}")`,
    );
  }
  return ok(value);
}

/**
 * Required `YYYY-MM-DDTHH:MM:SSZ` that must be a real UTC instant, taken exactly as written.
 *
 * `as_of` and `observed_at` are not `RawPosting` strings, so the "strings are trimmed" rule of
 * spec 01 section 1 does not reach them: spec 02 section 1 fixes their format and padding
 * violates it. The Python engine is identical (docs/spec/ambiguities/differential.md D-6).
 */
export function checkInstant(raw: unknown, field: string): Check<string> {
  if (raw === undefined || raw === null) return fail(`${field} is required`);
  if (typeof raw !== 'string') return fail(`${field} must be a YYYY-MM-DDTHH:MM:SSZ timestamp`);
  if (parseTimestamp(raw) === null) {
    return fail(
      `${field} must be a real UTC time in YYYY-MM-DDTHH:MM:SSZ format (got "${truncate(raw)}")`,
    );
  }
  return ok(raw);
}

/**
 * Like {@link checkInstant} but the text is trimmed first. For values that originate in a CSV
 * cell or a form field, where every string is a `RawPosting`-style string and is trimmed.
 */
export function checkTimestamp(raw: unknown, field: string): Check<string> {
  return checkInstant(typeof raw === 'string' ? trimText(raw) : raw, field);
}

/** Optional timestamp: blank or missing means null. */
export function checkOptionalTimestamp(raw: unknown, field: string): Check<string | null> {
  if (raw === undefined || raw === null) return ok(null);
  if (typeof raw === 'string' && trimText(raw) === '') return ok(null);
  const result = checkTimestamp(raw, field);
  return result.ok ? ok(result.value) : fail(result.message);
}

export function checkEnum<T extends string>(
  raw: unknown,
  field: string,
  allowed: readonly T[],
): Check<T> {
  if (typeof raw === 'string' && (allowed as readonly string[]).includes(raw)) {
    return ok(raw as T);
  }
  return fail(`${field} must be one of ${allowed.join(', ')}`);
}

// ---------------------------------------------------------------------------------------------
// Zod schemas for the analyze() input
// ---------------------------------------------------------------------------------------------

/**
 * Wrap a throw-free check so Zod reports its message at the field's path. `.optional()` is what
 * lets a missing key reach the check as `undefined` (Zod 4 otherwise reports "expected
 * nonoptional" before the check runs), so each check decides for itself whether a field is
 * required.
 */
function fromCheck<T>(check: (raw: unknown) => Check<T>) {
  return z
    .unknown()
    .optional()
    .transform((raw, ctx): T => {
      const result = check(raw);
      if (!result.ok) {
        ctx.issues.push({ code: 'custom', message: result.message, input: raw });
        return z.NEVER;
      }
      return result.value;
    });
}

const sourceKindField = (field: string) => fromCheck((raw) => checkEnum(raw, field, SOURCE_KINDS));

const postingSchema = z.object({
  source_kind: z.unknown().optional(),
  source_ref: z.unknown().optional(),
  source_posting_id: fromCheck((raw) => checkOptionalText(raw, 'source_posting_id', null)),
  company_name: fromCheck((raw) => checkRequiredText(raw, 'company_name', LIMITS.company_name)),
  title: fromCheck((raw) => checkRequiredText(raw, 'title', LIMITS.title)),
  location: fromCheck((raw) => checkOptionalText(raw, 'location', LIMITS.location)),
  work_mode: fromCheck((raw) => checkWorkMode(raw)),
  department: fromCheck((raw) => checkOptionalText(raw, 'department', LIMITS.department)),
  url: fromCheck((raw) => checkUrl(raw)),
  posted_at: fromCheck((raw) => checkDate(raw, 'posted_at')),
});

const snapshotSchema = z
  .object({
    snapshot_id: fromCheck((raw) =>
      typeof raw === 'string' && raw.length > 0
        ? ok(raw)
        : fail<string>('snapshot_id must be a non-empty string'),
    ),
    source_kind: sourceKindField('source_kind'),
    source_ref: fromCheck((raw) => checkRequiredText(raw, 'source_ref', LIMITS.source_ref)),
    observed_at: fromCheck((raw) => checkInstant(raw, 'observed_at')),
    mode: fromCheck((raw) => checkEnum<SnapshotMode>(raw, 'mode', SNAPSHOT_MODES)),
    // Omitted means empty, like `profile` and `decisions` (D-7); `null` is still an error.
    postings: z.array(postingSchema).default([]),
  })
  .superRefine((snapshot, ctx) => {
    // A posting may repeat its snapshot's source, but must never contradict it.
    snapshot.postings.forEach((posting, index) => {
      const kind = posting.source_kind;
      if (kind !== undefined && kind !== null && kind !== snapshot.source_kind) {
        ctx.addIssue({
          code: 'custom',
          message: `source_kind "${String(kind)}" contradicts snapshot source_kind "${snapshot.source_kind}"`,
          path: ['postings', index, 'source_kind'],
        });
      }
      const ref = posting.source_ref;
      if (ref !== undefined && ref !== null) {
        const trimmed = typeof ref === 'string' ? trimText(ref) : ref;
        if (trimmed !== snapshot.source_ref) {
          ctx.addIssue({
            code: 'custom',
            message: `source_ref "${String(ref)}" contradicts snapshot source_ref "${snapshot.source_ref}"`,
            path: ['postings', index, 'source_ref'],
          });
        }
      }
    });
  });

const keywordList = (field: string) =>
  z.array(fromCheck((raw) => checkKeyword(raw, field))).max(LIMITS.keywords, {
    message: `${field} may hold at most ${LIMITS.keywords} keywords`,
  });

function checkKeyword(raw: unknown, field: string): Check<string> {
  if (typeof raw !== 'string') return fail(`${field} entries must be strings`);
  const value = trimText(raw);
  const length = value.length > LIMITS.keyword ? codePointLength(value) : value.length;
  if (length > LIMITS.keyword) return fail(overLength(`${field} entry`, LIMITS.keyword, length));
  return ok(value);
}

const decisionSchema = z
  .object({
    a_key: z.string(),
    b_key: z.string(),
    decision: fromCheck((raw) => checkEnum(raw, 'decision', DECISION_KINDS)),
  })
  .superRefine((decision, ctx) => {
    if (compareCodePoints(decision.a_key, decision.b_key) >= 0) {
      ctx.addIssue({
        code: 'custom',
        message: 'a_key must sort strictly before b_key (code-point order)',
        path: ['a_key'],
      });
    }
  });

const inputSchema = z
  .object({
    as_of: fromCheck((raw) => checkInstant(raw, 'as_of')),
    profile: z
      .object({
        include_keywords: keywordList('include_keywords').default([]),
        exclude_keywords: keywordList('exclude_keywords').default([]),
      })
      .default({ include_keywords: [], exclude_keywords: [] }),
    decisions: z.array(decisionSchema).default([]),
    snapshots: z.array(snapshotSchema).default([]),
  })
  .superRefine((input, ctx) => {
    const seen = new Map<string, number>();
    input.snapshots.forEach((snapshot, index) => {
      const earlier = seen.get(snapshot.snapshot_id);
      if (earlier !== undefined) {
        ctx.addIssue({
          code: 'custom',
          message: `snapshot_id "${snapshot.snapshot_id}" duplicates snapshots[${earlier}]`,
          path: ['snapshots', index, 'snapshot_id'],
        });
      } else {
        seen.set(snapshot.snapshot_id, index);
      }
    });
  });

/**
 * Validate and normalize an `analyze()` input: strings trimmed, empty optional fields null,
 * `work_mode` defaulted, every constraint of spec 01 §1 enforced.
 *
 * Unknown object properties are ignored (Zod's default), so callers may attach extra context.
 * @throws EngineInputError listing every problem found.
 */
export function parseAnalyzeInput(raw: unknown): ParsedInput {
  const result = inputSchema.safeParse(raw);
  if (!result.success) {
    const issues: InputIssue[] = result.error.issues.map((issue) => ({
      path: formatPath(issue.path),
      message: issue.message,
    }));
    throw new EngineInputError(issues);
  }
  const data = result.data;
  const snapshots: ParsedSnapshot[] = data.snapshots.map((snapshot) => {
    const sourceKind: SourceKind = snapshot.source_kind;
    const postings: RawPosting[] = snapshot.postings.map((posting) => ({
      source_kind: sourceKind,
      source_ref: snapshot.source_ref,
      source_posting_id: posting.source_posting_id,
      company_name: posting.company_name,
      title: posting.title,
      location: posting.location,
      work_mode: posting.work_mode,
      department: posting.department,
      url: posting.url,
      posted_at: posting.posted_at,
    }));
    return {
      snapshot_id: snapshot.snapshot_id,
      source_kind: sourceKind,
      source_ref: snapshot.source_ref,
      observed_at: snapshot.observed_at,
      mode: snapshot.mode,
      postings,
    };
  });
  return {
    as_of: data.as_of,
    profile: {
      include_keywords: data.profile.include_keywords,
      exclude_keywords: data.profile.exclude_keywords,
    },
    decisions: data.decisions.map((d) => ({
      a_key: d.a_key,
      b_key: d.b_key,
      decision: d.decision,
    })),
    snapshots,
  };
}
