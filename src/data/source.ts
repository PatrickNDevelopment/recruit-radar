/**
 * The data layer's public surface (spec 00, "AnalysisSource").
 *
 * - `AnalysisSource` is the one interface every screen is written against.
 * - `LocalSource` implements it with the TypeScript engine plus `localStorage`.
 * - `RemoteSource` implements it with the spec 03 HTTP API.
 * - `SessionStore` is the connection manager: it owns the backend URL setting, the health check,
 *   the choice between the two sources and the current workspace.
 *
 * Importing from this one module keeps the UI free of storage and `fetch` details.
 */
export type {
  AnalysisSource,
  AtsProvider,
  AtsSource,
  AtsSources,
  Capabilities,
  DataMode,
  DataNotice,
  DatasetSummary,
  DecisionRecord,
  FieldProblem,
  ImportReport,
  ModePreference,
  NewAtsSource,
  PostingFormValues,
  RadarFilters,
  RadarSort,
  RadarSortKey,
  RefreshErrorKind,
  RefreshRun,
  SavedView,
  ShortlistEntry,
  SubmitResult,
  Workspace,
} from './types';
export { ATS_PROVIDERS, DEFAULT_FILTERS, DEFAULT_SORT, RADAR_SORT_KEYS } from './types';

export { LocalSource, MAX_NOTE_LENGTH, MAX_POSTINGS, WORKSPACE_KEY } from './localSource';
export { RemoteSource, REQUEST_TIMEOUT_MS, TOKEN_PATTERN } from './remoteSource';
export { SourceError, describeError, isSourceError } from './errors';
export type { SourceErrorKind } from './errors';
export {
  DEFAULT_BACKEND_URL,
  checkBackend,
  isLoopbackHost,
  shouldProbeBackend,
  validateBackendUrl,
} from './connection';
export type { HealthState, OfflineKind } from './connection';
export { SessionStore } from './session';
export type { OperationResult, SessionDeps, SessionState, StatusMessage } from './session';
