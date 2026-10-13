/**
 * Public API of the RecruitRadar TypeScript engine. Pure: no DOM, no React, no Node-only APIs.
 *
 * - `analyze(input)` — snapshots in, evidence-backed `Analysis` out (spec 01, 02).
 * - CSV import / export and shortlist export (spec 05).
 * - The normalization and identity primitives, exposed so UI code and tests can reuse them.
 */
export { analyze } from './analyze';
export { EngineInputError, type InputIssue } from './errors';
export { parseAnalyzeInput, LIMITS, isHttpUrl } from './validate';

export {
  companyKey,
  containsTokenSequence,
  locationKey,
  normText,
  titleKey,
  tokenSequenceMatch,
  compareCodePoints,
  codePointLength,
  trimText,
} from './normalize';
export { sha12, sha256Hex } from './sha256';
export { daysBetweenSeconds, parseDate, parseTimestamp, roundHalfUp } from './time';

export {
  COMPONENT_LABELS,
  COMPONENT_NAMES,
  REASON_TEXT,
  describeComponent,
  formatScore,
} from './explain';
export { WEIGHTS } from './scoring';

export {
  CSV_MAX_BYTES,
  CSV_MAX_ROWS,
  POSTING_COLUMNS,
  SHORTLIST_COLUMNS,
  buildShortlistRows,
  exportPostingsCsv,
  exportShortlistCsv,
  guardFormula,
  importCsv,
  normalizeHeader,
  parseCsv,
  snapshotsToPostingRows,
  unguardFormula,
  validateImportRow,
  writeCsv,
  type CsvFileError,
  type CsvFileErrorCode,
  type CsvImportOptions,
  type CsvImportResult,
  type CsvParseResult,
  type CsvPostingRow,
  type CsvRecord,
  type CsvRejectedRow,
  type CsvRowError,
  type CsvWarning,
  type CsvWriteOptions,
  type PostingColumn,
  type ShortlistEntryInput,
  type ShortlistRow,
  type ValidatedRow,
} from './csv';

export {
  COMPONENT_KEYS,
  DECISION_KINDS,
  EVENT_TYPES,
  SNAPSHOT_MODES,
  SOURCE_KINDS,
  TRACKED_FIELDS,
  WORK_MODES,
  type Analysis,
  type AnalysisEvent,
  type AnalysisStats,
  type AnalyzeInput,
  type ChangeComponent,
  type ComponentKey,
  type CompanyAnalysis,
  type DecisionKind,
  type EventType,
  type FreshnessComponent,
  type MergeCandidate,
  type MergeDecision,
  type MergeReason,
  type ParsedInput,
  type ParsedSnapshot,
  type PostingInput,
  type Profile,
  type RawPosting,
  type ReasonCode,
  type RoleAnalysis,
  type RoleObservation,
  type RoleRelevanceComponent,
  type ScoreComponent,
  type SnapshotInput,
  type SnapshotMode,
  type SourceConfidenceComponent,
  type SourceKind,
  type TrackedField,
  type UrgencyComponent,
  type VolumeComponent,
  type WorkMode,
} from './types';
