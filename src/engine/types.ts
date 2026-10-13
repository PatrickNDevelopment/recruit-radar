/**
 * Types for the pure RecruitRadar analysis engine (spec 01, 02 and 05).
 *
 * Field names are snake_case on purpose: they mirror the JSON contract that the Python engine and
 * `contracts/vectors/*.json` share, so objects can be compared and persisted without renaming.
 */

export const SOURCE_KINDS = ['greenhouse', 'lever', 'ashby', 'csv', 'manual'] as const;
export type SourceKind = (typeof SOURCE_KINDS)[number];

export const WORK_MODES = ['remote', 'hybrid', 'onsite', 'unknown'] as const;
export type WorkMode = (typeof WORK_MODES)[number];

export const SNAPSHOT_MODES = ['full', 'additive'] as const;
export type SnapshotMode = (typeof SNAPSHOT_MODES)[number];

export const DECISION_KINDS = ['merge', 'not_same'] as const;
export type DecisionKind = (typeof DECISION_KINDS)[number];

export const EVENT_TYPES = ['baseline', 'added', 'changed', 'removed', 'reappeared'] as const;
export type EventType = (typeof EVENT_TYPES)[number];

/** Tracked posting fields, in the (code-point sorted) order used by `changed` events. */
export const TRACKED_FIELDS = [
  'department',
  'location',
  'posted_at',
  'title',
  'url',
  'work_mode',
] as const;
export type TrackedField = (typeof TRACKED_FIELDS)[number];

export const COMPONENT_KEYS = [
  'role_relevance',
  'volume',
  'change',
  'urgency',
  'source_confidence',
  'freshness',
] as const;
export type ComponentKey = (typeof COMPONENT_KEYS)[number];

export type ReasonCode =
  'no_active_roles' | 'no_keywords' | 'insufficient_history' | 'no_scope_roles' | 'no_dated_roles';

export type MergeReason = 'spacing_variant' | 'token_overlap' | 'near_typo';

// ---------------------------------------------------------------------------------------------
// Input (wire shape, before validation)
// ---------------------------------------------------------------------------------------------

/** One posting inside a snapshot. `source_kind`/`source_ref` default to the snapshot's. */
export interface PostingInput {
  source_kind?: SourceKind;
  source_ref?: string;
  source_posting_id?: string | null;
  company_name: string;
  title: string;
  location?: string | null;
  work_mode?: WorkMode | null;
  department?: string | null;
  url?: string | null;
  posted_at?: string | null;
}

export interface SnapshotInput {
  snapshot_id: string;
  source_kind: SourceKind;
  source_ref: string;
  /** `YYYY-MM-DDTHH:MM:SSZ` (UTC). */
  observed_at: string;
  mode: SnapshotMode;
  postings: PostingInput[];
}

export interface Profile {
  include_keywords: string[];
  exclude_keywords: string[];
}

export interface MergeDecision {
  /** Company key; must sort before `b_key` in code-point order. */
  a_key: string;
  b_key: string;
  decision: DecisionKind;
}

export interface AnalyzeInput {
  /** `YYYY-MM-DDTHH:MM:SSZ` (UTC). The only clock the engine ever sees. */
  as_of: string;
  profile?: Profile;
  decisions?: MergeDecision[];
  snapshots: SnapshotInput[];
}

// ---------------------------------------------------------------------------------------------
// Validated, normalized input
// ---------------------------------------------------------------------------------------------

/** RawPosting (spec 01 §1) after validation: trimmed, empty optional fields are null. */
export interface RawPosting {
  source_kind: SourceKind;
  source_ref: string;
  source_posting_id: string | null;
  company_name: string;
  title: string;
  location: string | null;
  work_mode: WorkMode;
  department: string | null;
  url: string | null;
  posted_at: string | null;
}

export interface ParsedSnapshot {
  snapshot_id: string;
  source_kind: SourceKind;
  source_ref: string;
  observed_at: string;
  mode: SnapshotMode;
  postings: RawPosting[];
}

export interface ParsedInput {
  as_of: string;
  profile: Profile;
  decisions: MergeDecision[];
  snapshots: ParsedSnapshot[];
}

// ---------------------------------------------------------------------------------------------
// Output (spec 02 §5)
// ---------------------------------------------------------------------------------------------

export interface RoleRelevanceInputs {
  relevant: number | null;
  active: number;
}
export interface VolumeInputs {
  scope_roles: number;
}
export interface ChangeInputs {
  added: number | null;
  removed: number | null;
  net: number | null;
  span_days: number | null;
  window_days: 30;
}
export interface UrgencyInputs {
  aged: number | null;
  known: number | null;
  threshold_days: 45;
}
export interface SourceConfidenceInputs {
  scope_roles: number;
  corroborated: number | null;
}
export interface FreshnessInputs {
  days_since_last_seen: number | null;
}

export interface ComponentBase<K extends ComponentKey, I> {
  key: K;
  weight: number;
  /** 0..1000, or null when the component cannot be computed (see `reason_code`). */
  value: number | null;
  reason_code: ReasonCode | null;
  inputs: I;
}

export type RoleRelevanceComponent = ComponentBase<'role_relevance', RoleRelevanceInputs>;
export type VolumeComponent = ComponentBase<'volume', VolumeInputs>;
export type ChangeComponent = ComponentBase<'change', ChangeInputs>;
export type UrgencyComponent = ComponentBase<'urgency', UrgencyInputs>;
export type SourceConfidenceComponent = ComponentBase<'source_confidence', SourceConfidenceInputs>;
export type FreshnessComponent = ComponentBase<'freshness', FreshnessInputs>;

export type ScoreComponent =
  | RoleRelevanceComponent
  | VolumeComponent
  | ChangeComponent
  | UrgencyComponent
  | SourceConfidenceComponent
  | FreshnessComponent;

export interface CompanyAnalysis {
  company_id: string;
  key: string;
  name: string;
  aliases: string[];
  first_seen: string;
  /** Latest `last_seen` among active roles; null when the company has no active role. */
  last_seen: string | null;
  active_roles: number;
  relevant_roles: number | null;
  removed_roles: number;
  /** 0..1000, or null when no component could be computed. */
  score: number | null;
  /** Sum of the weights of the computable components (0..100). */
  coverage: number;
  rank: number | null;
  components: ScoreComponent[];
}

export interface RoleObservation {
  source_kind: SourceKind;
  source_ref: string;
  source_posting_id: string | null;
  url: string | null;
  status: 'active' | 'removed';
  first_seen: string;
  last_seen: string;
}

export interface RoleAnalysis {
  role_id: string;
  company_id: string;
  title: string;
  location: string | null;
  work_mode: WorkMode;
  department: string | null;
  posted_at: string | null;
  status: 'active' | 'removed';
  first_seen: string;
  last_seen: string;
  removed_at: string | null;
  relevant: boolean | null;
  age_days: number;
  observations: RoleObservation[];
}

export interface AnalysisEvent {
  at: string;
  type: EventType;
  company_id: string;
  role_id: string;
  source_kind: SourceKind;
  source_ref: string;
  title: string;
  fields: TrackedField[] | null;
}

export interface MergeCandidate {
  candidate_id: string;
  a_key: string;
  b_key: string;
  a_name: string;
  b_name: string;
  reason: MergeReason;
}

export interface AnalysisStats {
  snapshots: number;
  postings_observed: number;
  companies: number;
  active_roles: number;
}

export interface Analysis {
  as_of: string;
  companies: CompanyAnalysis[];
  roles: RoleAnalysis[];
  events: AnalysisEvent[];
  merge_candidates: MergeCandidate[];
  stats: AnalysisStats;
}
