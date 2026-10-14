/**
 * Shared contract between the UI and the two data sources (spec 00: "AnalysisSource").
 *
 * `LocalSource` (engine + localStorage) and `RemoteSource` (spec 03 HTTP API) both implement
 * `AnalysisSource`, so every screen is written once. What only one mode can do is declared in
 * `capabilities`; calling an unavailable operation throws `SourceError('unavailable')`.
 */
import type {
  Analysis,
  CsvRejectedRow,
  CsvRowError,
  CsvWarning,
  DecisionKind,
  MergeDecision,
  Profile,
  SourceKind,
  WorkMode,
} from '../engine';

export type DataMode = 'local' | 'connected';

/** Where the user wants data to come from. `auto` = the backend, but only when it is local. */
export type ModePreference = 'auto' | 'local' | 'connected';

// ---------------------------------------------------------------------------------------------
// Workspace (everything a screen needs, loaded together)
// ---------------------------------------------------------------------------------------------

export interface DecisionRecord extends MergeDecision {
  /** Stable handle for undo: `a_key|b_key` locally, the server id when connected. */
  id: string;
}

export interface ShortlistEntry {
  company_id: string;
  name: string;
  note: string;
  added_at: string;
}

export interface DatasetSummary {
  /** `<source_kind>:<source_ref>` */
  id: string;
  source_kind: SourceKind;
  source_ref: string;
  /** True for the built-in synthetic sample datasets. */
  synthetic: boolean;
  /** Postings held (local mode only; the backend API does not report it). */
  postings: number | null;
  snapshots: number | null;
  /** Snapshots dated after the analysis time; the engine ignores them entirely. */
  ignored_snapshots: number;
  /** Distinct canonical roles this dataset has an observation for. */
  roles: number;
  active_roles: number;
  first_seen: string | null;
  last_seen: string | null;
}

export type NoticeKind = 'corrupt_recovered' | 'newer_schema' | 'storage_unavailable';

export interface DataNotice {
  kind: NoticeKind;
  message: string;
}

export interface Workspace {
  mode: DataMode;
  analysis: Analysis;
  profile: Profile;
  decisions: DecisionRecord[];
  /** Entries that resolve to a company in `analysis` (local) or as stored by the backend. */
  shortlist: ShortlistEntry[];
  datasets: DatasetSummary[];
  has_sample_data: boolean;
  notices: DataNotice[];
}

// ---------------------------------------------------------------------------------------------
// Operations
// ---------------------------------------------------------------------------------------------

export interface FileProblem {
  code: string;
  message: string;
  line?: number;
}

export interface ImportReport {
  dataset_label: string;
  /** False when the file as a whole was rejected (see `file_error`); nothing was stored. */
  ok: boolean;
  file_error: FileProblem | null;
  accepted: number;
  rejected: number;
  errors: CsvRowError[];
  warnings: CsvWarning[];
  /** Rejected rows with their values, for in-place correction. */
  rejected_rows: CsvRejectedRow[];
}

/** Raw string values of the manual-entry form (and of one CSV row being corrected). */
export interface PostingFormValues {
  company_name: string;
  title: string;
  location: string;
  work_mode: string;
  department: string;
  url: string;
  posted_at: string;
  source_posting_id: string;
}

export interface FieldProblem {
  field: string;
  message: string;
}

export type SubmitResult = { ok: true } | { ok: false; problems: FieldProblem[] };

export interface Capabilities {
  /** Read-only ATS refresh (connected mode only). */
  refresh: boolean;
  /** "Load sample data" (local mode only). */
  loadSample: boolean;
  /** Remove one dataset (local mode only; the API has no such endpoint). */
  removeDataset: boolean;
  /** Export stored postings per dataset (local mode only). */
  exportPostings: boolean;
}

export type AtsProvider = 'greenhouse' | 'lever' | 'ashby';
export const ATS_PROVIDERS: readonly AtsProvider[] = ['greenhouse', 'lever', 'ashby'];

export type RefreshErrorKind =
  | 'not_found'
  | 'unauthorized'
  | 'rate_limited'
  | 'server_error'
  | 'network'
  | 'timeout'
  | 'malformed'
  | 'too_large';

/** Spec 03 `RefreshRun`. */
export interface RefreshRun {
  id: string;
  source_id: string;
  started_at: string;
  finished_at: string;
  status: 'ok' | 'failed';
  error_kind: RefreshErrorKind | null;
  http_status: number | null;
  retry_after_s: number | null;
  items_seen: number;
  added: number;
  changed: number;
  removed: number;
  reappeared: number;
  unchanged: number;
  message: string;
}

export interface AtsSource {
  id: string;
  provider: AtsProvider;
  token: string;
  company_name: string;
  last_run: RefreshRun | null;
}

export interface NewAtsSource {
  provider: AtsProvider;
  token: string;
  company_name: string;
}

export interface AtsSources {
  list(): Promise<AtsSource[]>;
  add(input: NewAtsSource): Promise<AtsSource>;
  remove(id: string): Promise<void>;
  refresh(id: string): Promise<RefreshRun>;
  runs(id: string): Promise<RefreshRun[]>;
}

export interface AnalysisSource {
  readonly mode: DataMode;
  readonly capabilities: Capabilities;
  /** ATS source management; null in local mode. */
  readonly sources: AtsSources | null;
  /** Everything the screens show, computed at the current time. */
  load(): Promise<Workspace>;
  setProfile(profile: Profile): Promise<void>;
  importCsv(datasetLabel: string, csvText: string): Promise<ImportReport>;
  addManualPosting(values: PostingFormValues): Promise<SubmitResult>;
  decide(aKey: string, bKey: string, decision: DecisionKind): Promise<void>;
  undoDecision(id: string): Promise<void>;
  setShortlisted(companyId: string, shortlisted: boolean, note?: string): Promise<void>;
  exportShortlistCsv(): Promise<string>;
  /** Stored postings of one dataset (or all) in the import format. Local mode only. */
  exportPostingsCsv(datasetId: string | null): Promise<string>;
  /** Loads the synthetic sample datasets. Local mode only. */
  loadSample(): Promise<{ datasets: number; postings: number; keywordsAdded: boolean }>;
  /** Removes one dataset and its snapshots. Local mode only. */
  removeDataset(datasetId: string): Promise<void>;
  /** Wipes all data held by this source. */
  eraseAll(): Promise<void>;
}

// ---------------------------------------------------------------------------------------------
// Radar view state (persisted as saved views)
// ---------------------------------------------------------------------------------------------

export interface RadarFilters {
  text: string;
  work_mode: WorkMode | 'any';
  /** `'any'` or a dataset id (`<source_kind>:<source_ref>`). */
  source: string;
  /** 0..100 on the displayed scale; null = no minimum. */
  min_score: number | null;
  shortlisted_only: boolean;
}

export const RADAR_SORT_KEYS = [
  'rank',
  'name',
  'active_roles',
  'relevant_roles',
  'last_seen',
  'score',
  'coverage',
] as const;
export type RadarSortKey = (typeof RADAR_SORT_KEYS)[number];

export interface RadarSort {
  key: RadarSortKey;
  direction: 'asc' | 'desc';
}

export interface SavedView {
  id: string;
  name: string;
  filters: RadarFilters;
  sort: RadarSort;
  created_at: string;
}

export const DEFAULT_FILTERS: RadarFilters = {
  text: '',
  work_mode: 'any',
  source: 'any',
  min_score: null,
  shortlisted_only: false,
};

export const DEFAULT_SORT: RadarSort = { key: 'rank', direction: 'asc' };
