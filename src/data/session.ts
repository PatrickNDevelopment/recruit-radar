/**
 * SessionStore: the connection manager and the single place the UI talks to.
 *
 * It owns
 *  - the preferences (backend address, data-location preference, saved views),
 *  - the backend health check and the choice between `LocalSource` and `RemoteSource`,
 *  - the current `Workspace` and the load / stale / error state around it,
 *  - the status message announced to assistive technology after every action.
 *
 * It is plain TypeScript (no React, no DOM globals): the browser objects it needs are injected,
 * so every rule below is unit-tested in node. React reads it through `useSyncExternalStore`.
 *
 * Honesty rules enforced here:
 *  - a failed backend request never turns into silently-empty data: the last workspace is kept
 *    and labelled stale, or an explicit error is shown;
 *  - connected mode is entered only after a successful health check;
 *  - local mode is announced as such, whatever the reason for being in it.
 */
import type { DecisionKind, MergeCandidate, Profile } from '../engine';
import { systemClock, type Clock } from './clock';
import {
  checkBackend,
  shouldProbeBackend,
  validateBackendUrl,
  type FetchLike,
  type HealthState,
} from './connection';
import { describeError, SourceError } from './errors';
import { LocalSource, type ExternalChangeTarget } from './localSource';
import { PrefsStore, removeView, upsertView, type Prefs } from './prefs';
import { RemoteSource } from './remoteSource';
import type { StorageLike } from './storage';
import type {
  AnalysisSource,
  AtsSource,
  DataMode,
  ImportReport,
  ModePreference,
  NewAtsSource,
  PostingFormValues,
  RadarFilters,
  RadarSort,
  RefreshRun,
  SubmitResult,
  Workspace,
} from './types';

export interface StatusMessage {
  /** Increases with every message so an identical text is announced again. */
  id: number;
  kind: 'success' | 'info' | 'error';
  text: string;
}

export interface SessionState {
  /** True once the first load finished, successfully or not. */
  ready: boolean;
  prefs: Prefs;
  prefsProblem: string | null;
  backend: HealthState;
  mode: DataMode;
  workspace: Workspace | null;
  loading: boolean;
  loadError: string | null;
  /** Set when the workspace shown is older than what the source can currently answer. */
  stale: { asOf: string; reason: string } | null;
  /** Another tab changed the stored data after this tab loaded it. */
  externalChange: boolean;
  /** Mutations in flight. */
  pending: number;
  status: StatusMessage | null;
}

export type OperationResult<T> =
  { ok: true; value: T } | { ok: false; message: string; error: unknown };

export interface SessionDeps {
  /** `localStorage`, or null when it is unavailable (data then lives in memory only). */
  storage: StorageLike | null;
  /** Defaults to `storage`. */
  prefsStorage?: StorageLike | null;
  fetchImpl?: FetchLike;
  clock?: Clock;
  /** `location.hostname` of the page; null when unknown (never probes automatically). */
  pageHostname: string | null;
  /** `window`, for the cross-tab `storage` event. */
  events?: ExternalChangeTarget | null;
  makeId?: () => string;
  requestTimeoutMs?: number;
  healthTimeoutMs?: number;
}

type Listener = () => void;

function defaultMakeId(): string {
  const cryptoApi = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (cryptoApi?.randomUUID !== undefined) return cryptoApi.randomUUID();
  return `v_${Date.now().toString(36)}${Math.floor(Math.random() * 1e9).toString(36)}`;
}

export class SessionStore {
  private state: SessionState;
  private readonly listeners = new Set<Listener>();
  private readonly deps: SessionDeps;
  private readonly clock: Clock;
  private readonly prefsStore: PrefsStore;
  private readonly makeId: () => string;
  private source: AnalysisSource;
  private local: LocalSource;
  private unwatch: (() => void) | null = null;
  private starting: Promise<void> | null = null;
  private statusCounter = 0;
  /** Bumped whenever the source changes, so a slow answer from an old source is dropped. */
  private generation = 0;

  constructor(deps: SessionDeps) {
    this.deps = deps;
    this.clock = deps.clock ?? systemClock;
    this.makeId = deps.makeId ?? defaultMakeId;
    this.prefsStore = new PrefsStore(
      deps.prefsStorage === undefined ? deps.storage : deps.prefsStorage,
    );
    this.local = new LocalSource({ storage: deps.storage, clock: this.clock });
    this.source = this.local;
    const loaded = this.prefsStore.load();
    this.state = {
      ready: false,
      prefs: loaded.prefs,
      prefsProblem: loaded.problem,
      backend: { state: 'unchecked' },
      mode: 'local',
      workspace: null,
      loading: false,
      loadError: null,
      stale: null,
      externalChange: false,
      pending: 0,
      status: null,
    };
  }

  // ---- subscription (useSyncExternalStore) ------------------------------------------------------

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  readonly getState = (): SessionState => this.state;

  private patch(change: Partial<SessionState>): void {
    this.state = { ...this.state, ...change };
    for (const listener of Array.from(this.listeners)) listener();
  }

  dispose(): void {
    this.unwatch?.();
    this.unwatch = null;
    this.listeners.clear();
  }

  // ---- status ----------------------------------------------------------------------------------

  announce(kind: StatusMessage['kind'], text: string): void {
    this.statusCounter += 1;
    this.patch({ status: { id: this.statusCounter, kind, text } });
  }

  clearStatus(): void {
    if (this.state.status !== null) this.patch({ status: null });
  }

  // ---- connection ------------------------------------------------------------------------------

  /** First load: preferences, backend probe (when the policy allows), then the workspace. */
  start(): Promise<void> {
    if (this.starting === null) this.starting = this.connect(false);
    return this.starting;
  }

  /** Re-run the health check (always) and reload the data from whichever source applies. */
  async recheckBackend(): Promise<void> {
    await this.connect(true);
  }

  private async connect(forceProbe: boolean): Promise<void> {
    const { prefs } = this.state;
    const probe = forceProbe || shouldProbeBackend(prefs.mode_preference, this.deps.pageHostname);
    this.generation += 1;
    const generation = this.generation;
    let chosen: AnalysisSource = this.local;
    let health: HealthState = { state: 'unchecked' };

    if (probe) {
      this.patch({ backend: { state: 'checking' }, loading: true });
      health = await checkBackend(prefs.backend_url, {
        ...(this.deps.fetchImpl === undefined ? {} : { fetchImpl: this.deps.fetchImpl }),
        ...(this.deps.healthTimeoutMs === undefined
          ? {}
          : { timeoutMs: this.deps.healthTimeoutMs }),
        clock: this.clock,
      });
      if (generation !== this.generation) return;
      if (health.state === 'ok' && prefs.mode_preference !== 'local') {
        chosen = new RemoteSource({
          baseUrl: prefs.backend_url,
          ...(this.deps.fetchImpl === undefined ? {} : { fetchImpl: this.deps.fetchImpl }),
          clock: this.clock,
          ...(this.deps.requestTimeoutMs === undefined
            ? {}
            : { timeoutMs: this.deps.requestTimeoutMs }),
        });
      }
    }

    // Data from the other mode must never be shown under this mode's label: drop it on a switch.
    const switched = chosen.mode !== this.source.mode;
    this.source = chosen;
    this.patch({
      backend: health,
      mode: chosen.mode,
      ...(switched ? { workspace: null } : {}),
      stale: null,
    });
    this.rewatch();
    await this.refreshWorkspace();
  }

  private rewatch(): void {
    this.unwatch?.();
    this.unwatch = null;
    const target = this.deps.events;
    if (this.source === this.local && target !== undefined && target !== null) {
      this.unwatch = this.local.watchExternalChanges(target, () => {
        this.patch({ externalChange: true });
      });
    }
  }

  /** Re-read the workspace from the current source. Returns whether it succeeded. */
  async reload(): Promise<boolean> {
    return this.refreshWorkspace();
  }

  private async refreshWorkspace(): Promise<boolean> {
    const source = this.source;
    const generation = this.generation;
    this.patch({ loading: true });
    try {
      const workspace = await source.load();
      if (generation !== this.generation) return false;
      this.patch({
        workspace,
        mode: source.mode,
        loading: false,
        loadError: null,
        stale: null,
        externalChange: false,
        ready: true,
      });
      return true;
    } catch (error) {
      if (generation !== this.generation) return false;
      const message = describeError(error);
      this.noteConnectivity(error);
      const previous = this.state.workspace;
      this.patch({
        loading: false,
        loadError: message,
        ready: true,
        stale: previous === null ? null : { asOf: previous.analysis.as_of, reason: message },
      });
      return false;
    }
  }

  /** A connectivity failure in connected mode means the backend can no longer be reached. */
  private noteConnectivity(error: unknown): void {
    if (!(error instanceof SourceError) || !error.isConnectivity) return;
    if (this.source.mode !== 'connected') return;
    this.patch({
      backend: {
        state: 'offline',
        kind: error.kind === 'cors' ? 'cors' : error.kind === 'timeout' ? 'timeout' : 'offline',
        message: error.message,
        checked_at: this.clock(),
      },
    });
  }

  // ---- preferences -----------------------------------------------------------------------------

  /** Validate, store and re-check the backend address. Returns a message when it is refused. */
  async setBackendUrl(input: string): Promise<{ ok: true } | { ok: false; message: string }> {
    const checked = validateBackendUrl(input);
    if (!checked.ok) return { ok: false, message: checked.message };
    try {
      const prefs = this.prefsStore.save({ backend_url: checked.url });
      this.patch({ prefs });
    } catch (error) {
      return { ok: false, message: describeError(error) };
    }
    await this.connect(true);
    return { ok: true };
  }

  async setModePreference(preference: ModePreference): Promise<void> {
    try {
      this.patch({ prefs: this.prefsStore.save({ mode_preference: preference }) });
    } catch (error) {
      this.announce('error', describeError(error));
      return;
    }
    // "auto" follows the probing policy (never a public host); "connected" is an explicit opt-in.
    await this.connect(preference === 'connected');
  }

  saveView(name: string, filters: RadarFilters, sort: RadarSort): { ok: boolean; message: string } {
    const result = upsertView(
      this.state.prefs.saved_views,
      name,
      filters,
      sort,
      this.clock(),
      this.makeId,
    );
    if (!result.ok) {
      this.announce('error', result.message);
      return { ok: false, message: result.message };
    }
    try {
      this.patch({ prefs: this.prefsStore.save({ saved_views: result.views }) });
    } catch (error) {
      const message = describeError(error);
      this.announce('error', message);
      return { ok: false, message };
    }
    const label = name.trim().replace(/\s+/gu, ' ');
    const message = result.replaced
      ? `Updated the saved view "${label}".`
      : `Saved the view "${label}".`;
    this.announce('success', message);
    return { ok: true, message };
  }

  deleteView(id: string): void {
    const view = this.state.prefs.saved_views.find((candidate) => candidate.id === id);
    try {
      this.patch({
        prefs: this.prefsStore.save({ saved_views: removeView(this.state.prefs.saved_views, id) }),
      });
    } catch (error) {
      this.announce('error', describeError(error));
      return;
    }
    this.announce(
      'success',
      view === undefined ? 'Deleted the view.' : `Deleted the view "${view.name}".`,
    );
  }

  // ---- operations ------------------------------------------------------------------------------

  /**
   * Run one source call: track it as pending, reload the workspace afterwards, and report the
   * outcome through the status region. Failures never throw out of here.
   */
  private async operate<T>(
    work: (source: AnalysisSource) => Promise<T>,
    options: {
      reload?: (value: T) => boolean;
      success?: (value: T) => { kind: StatusMessage['kind']; text: string } | null;
      silentFailure?: boolean;
    } = {},
  ): Promise<OperationResult<T>> {
    this.patch({ pending: this.state.pending + 1 });
    try {
      const value = await work(this.source);
      const shouldReload = options.reload === undefined ? true : options.reload(value);
      if (shouldReload) await this.refreshWorkspace();
      const status = options.success?.(value) ?? null;
      if (status !== null) this.announce(status.kind, status.text);
      return { ok: true, value };
    } catch (error) {
      const message = describeError(error);
      this.noteConnectivity(error);
      if (options.silentFailure !== true) this.announce('error', message);
      return { ok: false, message, error };
    } finally {
      this.patch({ pending: this.state.pending - 1 });
    }
  }

  private requireWorkspace(): Workspace | null {
    return this.state.workspace;
  }

  setProfile(profile: Profile): Promise<OperationResult<void>> {
    return this.operate((source) => source.setProfile(profile), {
      success: () => ({
        kind: 'success',
        text: 'Keywords saved. Scores were recalculated with the new keywords.',
      }),
    });
  }

  importCsv(datasetLabel: string, csvText: string): Promise<OperationResult<ImportReport>> {
    return this.operate((source) => source.importCsv(datasetLabel, csvText), {
      reload: (report) => report.ok && report.accepted > 0,
      success: (report) => {
        if (!report.ok) {
          return {
            kind: 'error',
            text: `Nothing was imported: ${report.file_error?.message ?? 'the file was rejected.'}`,
          };
        }
        if (report.accepted === 0) {
          return {
            kind: 'error',
            text: `Nothing was imported: all ${report.rejected} rows were rejected. See the line-by-line report.`,
          };
        }
        const rows = report.accepted === 1 ? '1 row' : `${report.accepted} rows`;
        const rejected =
          report.rejected === 0
            ? ''
            : `; ${report.rejected} ${report.rejected === 1 ? 'row was' : 'rows were'} rejected, see the report`;
        return {
          kind: report.rejected === 0 ? 'success' : 'info',
          text: `Imported ${rows} into "${report.dataset_label}"${rejected}.`,
        };
      },
    });
  }

  addManualPosting(values: PostingFormValues): Promise<OperationResult<SubmitResult>> {
    return this.operate((source) => source.addManualPosting(values), {
      reload: (result) => result.ok,
      success: (result) =>
        result.ok
          ? {
              kind: 'success',
              text: `Added "${values.title.trim()}" at ${values.company_name.trim()}.`,
            }
          : {
              kind: 'error',
              text:
                result.problems.length === 1
                  ? 'The posting was not added: 1 field needs attention.'
                  : `The posting was not added: ${result.problems.length} fields need attention.`,
            },
    });
  }

  /** Accept (`merge`) or reject (`not_same`) a merge candidate. Returns the id to undo it with. */
  async decideCandidate(
    candidate: MergeCandidate,
    decision: DecisionKind,
  ): Promise<OperationResult<{ decisionId: string | null }>> {
    const aKey = candidate.a_key;
    const bKey = candidate.b_key;
    const result = await this.operate(
      async (source) => {
        await source.decide(aKey, bKey, decision);
      },
      {
        success: () => ({
          kind: 'success',
          text:
            decision === 'merge'
              ? `Merged "${candidate.a_name}" and "${candidate.b_name}" into one company. You can undo this below.`
              : `Marked "${candidate.a_name}" and "${candidate.b_name}" as different companies. You can undo this below.`,
        }),
      },
    );
    if (!result.ok) return result;
    const found = this.state.workspace?.decisions.find(
      (record) => record.a_key === aKey && record.b_key === bKey,
    );
    return { ok: true, value: { decisionId: found?.id ?? null } };
  }

  undoDecision(id: string): Promise<OperationResult<void>> {
    return this.operate((source) => source.undoDecision(id), {
      success: () => ({
        kind: 'success',
        text: 'Decision undone. The companies are re-evaluated.',
      }),
    });
  }

  setShortlisted(
    companyId: string,
    shortlisted: boolean,
    note?: string,
  ): Promise<OperationResult<void>> {
    const name =
      this.requireWorkspace()?.analysis.companies.find((c) => c.company_id === companyId)?.name ??
      'The company';
    return this.operate((source) => source.setShortlisted(companyId, shortlisted, note), {
      success: () => ({
        kind: 'success',
        text: shortlisted
          ? note === undefined
            ? `${name} was added to the shortlist.`
            : `Saved the note for ${name}.`
          : `${name} was removed from the shortlist.`,
      }),
    });
  }

  exportShortlistCsv(): Promise<OperationResult<string>> {
    return this.operate((source) => source.exportShortlistCsv(), { reload: () => false });
  }

  exportPostingsCsv(datasetId: string | null): Promise<OperationResult<string>> {
    return this.operate((source) => source.exportPostingsCsv(datasetId), { reload: () => false });
  }

  loadSample(): Promise<
    OperationResult<{ datasets: number; postings: number; keywordsAdded: boolean }>
  > {
    return this.operate((source) => source.loadSample(), {
      success: (summary) => ({
        kind: 'success',
        text:
          `Loaded ${summary.datasets} synthetic sample datasets (${summary.postings} postings). ` +
          (summary.keywordsAdded
            ? 'Example role keywords were set because none were configured.'
            : 'Your role keywords were left unchanged.'),
      }),
    });
  }

  removeDataset(datasetId: string): Promise<OperationResult<void>> {
    return this.operate((source) => source.removeDataset(datasetId), {
      success: () => ({ kind: 'success', text: 'Dataset removed. Scores were recalculated.' }),
    });
  }

  eraseAll(): Promise<OperationResult<void>> {
    return this.operate((source) => source.eraseAll(), {
      success: () => ({
        kind: 'success',
        text: 'All data was erased. Saved views and the backend address were kept.',
      }),
    });
  }

  // ---- ATS sources (connected mode) --------------------------------------------------------------

  private requireSources(): NonNullable<AnalysisSource['sources']> {
    const sources = this.source.sources;
    if (sources === null) {
      throw new SourceError(
        'unavailable',
        'ATS sources are only available in connected mode (the local backend is not connected).',
        { code: 'unavailable' },
      );
    }
    return sources;
  }

  listAtsSources(): Promise<OperationResult<AtsSource[]>> {
    return this.operate(() => this.requireSources().list(), {
      reload: () => false,
      silentFailure: true,
    });
  }

  listRuns(sourceId: string): Promise<OperationResult<RefreshRun[]>> {
    return this.operate(() => this.requireSources().runs(sourceId), {
      reload: () => false,
      silentFailure: true,
    });
  }

  addAtsSource(input: NewAtsSource): Promise<OperationResult<AtsSource>> {
    return this.operate(() => this.requireSources().add(input), {
      reload: () => false,
      success: (created) => ({
        kind: 'success',
        text: `Added the source "${created.company_name}". Nothing is fetched until you refresh it.`,
      }),
    });
  }

  removeAtsSource(source: AtsSource): Promise<OperationResult<void>> {
    return this.operate(() => this.requireSources().remove(source.id), {
      success: () => ({
        kind: 'success',
        text: `Removed the source "${source.company_name}" with its refresh history and snapshots.`,
      }),
    });
  }

  refreshAtsSource(source: AtsSource): Promise<OperationResult<RefreshRun>> {
    return this.operate(() => this.requireSources().refresh(source.id), {
      success: (run) =>
        run.status === 'ok'
          ? {
              kind: 'success',
              text:
                `Refreshed "${source.company_name}": ${run.items_seen} postings seen, ` +
                `${run.added} added, ${run.changed} changed, ${run.removed} removed, ` +
                `${run.reappeared} listed again.`,
            }
          : {
              kind: 'error',
              text:
                `Refresh of "${source.company_name}" failed (${run.error_kind ?? 'unknown error'}). ` +
                `Nothing was removed and no snapshot was stored.`,
            },
    });
  }
}
