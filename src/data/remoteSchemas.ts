/**
 * Zod schemas for what the backend returns (spec 03). Responses are validated before the UI sees
 * them, so a backend/frontend mismatch becomes one explicit "bad response" error instead of a
 * crash deep inside a component.
 *
 * Shapes the spec does not pin down (list wrappers, source rows) are read tolerantly; every such
 * reading is recorded in docs/spec/ambiguities/frontend.md.
 */
import { z } from 'zod';
import {
  DECISION_KINDS,
  EVENT_TYPES,
  SOURCE_KINDS,
  TRACKED_FIELDS,
  WORK_MODES,
  type Analysis,
} from '../engine';
import type { RefreshRun } from './types';

const int = z.number().int();
const intOrNull = int.nullable();
const text = z.string();
const textOrNull = z.string().nullable();

const reasonCode = z.enum([
  'no_active_roles',
  'no_keywords',
  'insufficient_history',
  'no_scope_roles',
  'no_dated_roles',
]);

const componentBase = { weight: int, value: intOrNull, reason_code: reasonCode.nullable() };

const component = z.discriminatedUnion('key', [
  z.object({
    key: z.literal('role_relevance'),
    ...componentBase,
    inputs: z.object({ relevant: intOrNull, active: int }),
  }),
  z.object({
    key: z.literal('volume'),
    ...componentBase,
    inputs: z.object({ scope_roles: int }),
  }),
  z.object({
    key: z.literal('change'),
    ...componentBase,
    inputs: z.object({
      added: intOrNull,
      removed: intOrNull,
      net: intOrNull,
      span_days: intOrNull,
      window_days: z.literal(30),
    }),
  }),
  z.object({
    key: z.literal('urgency'),
    ...componentBase,
    inputs: z.object({ aged: intOrNull, known: intOrNull, threshold_days: z.literal(45) }),
  }),
  z.object({
    key: z.literal('source_confidence'),
    ...componentBase,
    inputs: z.object({ scope_roles: int, corroborated: intOrNull }),
  }),
  z.object({
    key: z.literal('freshness'),
    ...componentBase,
    inputs: z.object({ days_since_last_seen: intOrNull }),
  }),
]);

const company = z.object({
  company_id: text,
  key: text,
  name: text,
  aliases: z.array(text),
  first_seen: text,
  last_seen: textOrNull,
  active_roles: int,
  relevant_roles: intOrNull,
  removed_roles: int,
  score: intOrNull,
  coverage: int,
  rank: intOrNull,
  components: z.array(component),
});

const observation = z.object({
  source_kind: z.enum(SOURCE_KINDS),
  source_ref: text,
  source_posting_id: textOrNull,
  url: textOrNull,
  status: z.enum(['active', 'removed']),
  first_seen: text,
  last_seen: text,
});

const role = z.object({
  role_id: text,
  company_id: text,
  title: text,
  location: textOrNull,
  work_mode: z.enum(WORK_MODES),
  department: textOrNull,
  posted_at: textOrNull,
  status: z.enum(['active', 'removed']),
  first_seen: text,
  last_seen: text,
  removed_at: textOrNull,
  relevant: z.boolean().nullable(),
  age_days: int,
  observations: z.array(observation),
});

const event = z.object({
  at: text,
  type: z.enum(EVENT_TYPES),
  company_id: text,
  role_id: text,
  source_kind: z.enum(SOURCE_KINDS),
  source_ref: text,
  title: text,
  fields: z.array(z.enum(TRACKED_FIELDS)).nullable(),
});

const mergeCandidate = z.object({
  candidate_id: text,
  a_key: text,
  b_key: text,
  a_name: text,
  b_name: text,
  reason: z.enum(['spacing_variant', 'token_overlap', 'near_typo']),
});

export const analysisSchema: z.ZodType<Analysis> = z.object({
  as_of: text,
  companies: z.array(company),
  roles: z.array(role),
  events: z.array(event),
  merge_candidates: z.array(mergeCandidate),
  stats: z.object({
    snapshots: int,
    postings_observed: int,
    companies: int,
    active_roles: int,
  }),
});

export const profileSchema = z.object({
  include_keywords: z.array(text),
  exclude_keywords: z.array(text),
});

export const healthSchema = z
  .object({
    status: z.string().nullable().optional(),
    schema_version: z.union([z.number(), z.string()]).nullable().optional(),
    app_version: z.string().nullable().optional(),
    db_ok: z.boolean().nullable().optional(),
  })
  // `{}` is what plenty of unrelated servers answer; require at least one health field.
  .refine(
    (v) => v.status != null || v.schema_version != null || v.app_version != null || v.db_ok != null,
    { message: 'not a health response' },
  );

const id = z.union([z.string(), z.number()]).transform(String);

export const shortlistEntrySchema = z.object({
  company_id: text,
  name: text,
  note: z
    .string()
    .nullable()
    .optional()
    .transform((value) => value ?? ''),
  added_at: text,
});

export const decisionSchema = z.object({
  id: id.optional(),
  a_key: text,
  b_key: text,
  decision: z.enum(DECISION_KINDS),
});

export const refreshRunSchema: z.ZodType<RefreshRun, unknown> = z.object({
  id,
  source_id: id,
  started_at: text,
  finished_at: text,
  status: z.enum(['ok', 'failed']),
  error_kind: z
    .enum([
      'not_found',
      'unauthorized',
      'rate_limited',
      'server_error',
      'network',
      'timeout',
      'malformed',
      'too_large',
    ])
    .nullable(),
  http_status: intOrNull,
  retry_after_s: intOrNull,
  items_seen: int,
  added: int,
  changed: int,
  removed: int,
  reappeared: int,
  unchanged: int,
  message: z
    .string()
    .nullable()
    .transform((value) => value ?? ''),
});

export const atsSourceSchema = z.object({
  id,
  provider: z.enum(['greenhouse', 'lever', 'ashby']),
  token: text,
  company_name: text,
  last_run: refreshRunSchema.nullable().optional(),
  latest_run: refreshRunSchema.nullable().optional(),
  last_refresh: refreshRunSchema.nullable().optional(),
});

export const importResultSchema = z.object({
  snapshot_id: z.union([z.string(), z.number()]).nullable().optional(),
  dataset_label: text,
  accepted: int,
  rejected: int,
  errors: z.array(
    z.object({
      line: int,
      field: z.string().nullable().optional(),
      message: text,
    }),
  ),
  warnings: z
    .array(z.object({ line: int, message: text }))
    .optional()
    .default([]),
});

export const errorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.unknown().optional(),
  }),
});
