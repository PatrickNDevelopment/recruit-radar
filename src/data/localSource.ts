/**
 * LocalSource: the browser-only data source (spec 00, "Local-data mode").
 *
 * The TypeScript engine does all analysis; `localStorage` (or any `StorageLike`) holds the
 * snapshots, decisions, keywords and shortlist as one versioned JSON document.
 *
 * Safety properties, each covered by tests:
 *  - every mutation re-reads storage first (read-modify-write), so two tabs never overwrite each
 *    other with a stale copy; a `storage` event only needs to *refresh* the UI;
 *  - unreadable data is copied to a backup key before the app starts empty, never discarded;
 *  - data from a NEWER schema is never overwritten (every write is refused until the user erases);
 *  - storage that is unavailable degrades to memory-only with a visible notice;
 *  - a full quota rejects the change instead of losing it silently;
 *  - at most 5,000 postings are held (spec 05's import cap, applied to the whole workspace).
 */
import { z } from 'zod';
import {
  analyze,
  buildShortlistRows,
  compareCodePoints,
  EngineInputError,
  exportPostingsCsv,
  exportShortlistCsv,
  importCsv as engineImportCsv,
  snapshotsToPostingRows,
  SNAPSHOT_MODES,
  SOURCE_KINDS,
  validateImportRow,
  WORK_MODES,
  DECISION_KINDS,
  type Analysis,
  type DecisionKind,
  type MergeDecision,
  type ParsedSnapshot,
  type Profile,
} from '../engine';
import { systemClock, type Clock } from './clock';
import {
  datasetId,
  findCompanyByKey,
  isSampleLabel,
  parseDatasetId,
  summarizeDatasets,
} from './derive';
import { SourceError } from './errors';
import { buildSampleDatasets, SAMPLE_PROFILE } from './sample';
import {
  backupRaw,
  readVersioned,
  removeKey,
  writeText,
  type StorageLike,
  type VersionedRead,
} from './storage';
import type {
  AnalysisSource,
  Capabilities,
  DataNotice,
  DatasetSummary,
  DecisionRecord,
  ImportReport,
  PostingFormValues,
  ShortlistEntry,
  SubmitResult,
  Workspace,
} from './types';

export const WORKSPACE_KEY = 'recruit-radar.workspace';
export const WORKSPACE_BACKUP_KEY = 'recruit-radar.workspace.unreadable-backup';
export const SCHEMA_VERSION = 1;
export const MAX_POSTINGS = 5000;
export const MAX_NOTE_LENGTH = 2000;

// ---------------------------------------------------------------------------------------------
// Stored shape
// ---------------------------------------------------------------------------------------------

const postingSchema = z.object({
  source_kind: z.enum(SOURCE_KINDS),
  source_ref: z.string(),
  source_posting_id: z.string().nullable(),
  company_name: z.string(),
  title: z.string(),
  location: z.string().nullable(),
  work_mode: z.enum(WORK_MODES),
  department: z.string().nullable(),
  url: z.string().nullable(),
  posted_at: z.string().nullable(),
});

const snapshotSchema = z.object({
  snapshot_id: z.string().min(1),
  source_kind: z.enum(SOURCE_KINDS),
  source_ref: z.string(),
  observed_at: z.string(),
  mode: z.enum(SNAPSHOT_MODES),
  postings: z.array(postingSchema),
  synthetic: z.boolean().optional(),
});

const workspaceSchema = z.object({
  schema_version: z.literal(SCHEMA_VERSION),
  revision: z.number().int().nonnegative(),
  saved_at: z.string().nullable(),
  seq: z.number().int().nonnegative(),
  profile: z.object({
    include_keywords: z.array(z.string()),
    exclude_keywords: z.array(z.string()),
  }),
  decisions: z.array(
    z.object({
      a_key: z.string(),
      b_key: z.string(),
      decision: z.enum(DECISION_KINDS),
    }),
  ),
  snapshots: z.array(snapshotSchema),
  shortlist: z.array(
    z.object({
      key: z.string(),
      name: z.string(),
      note: z.string(),
      added_at: z.string(),
    }),
  ),
});

export type StoredWorkspace = z.infer<typeof workspaceSchema>;
export type StoredSnapshot = StoredWorkspace['snapshots'][number];

function emptyWorkspace(): StoredWorkspace {
  return {
    schema_version: SCHEMA_VERSION,
    revision: 0,
    saved_at: null,
    seq: 0,
    profile: { include_keywords: [], exclude_keywords: [] },
    decisions: [],
    snapshots: [],
    shortlist: [],
  };
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function countPostings(workspace: StoredWorkspace): number {
  let total = 0;
  for (const snapshot of workspace.snapshots) total += snapshot.postings.length;
  return total;
}

function toParsed(snapshot: StoredSnapshot): ParsedSnapshot {
  return {
    snapshot_id: snapshot.snapshot_id,
    source_kind: snapshot.source_kind,
    source_ref: snapshot.source_ref,
    observed_at: snapshot.observed_at,
    mode: snapshot.mode,
    postings: snapshot.postings,
  };
}

function decisionId(decision: MergeDecision): string {
  return `${decision.a_key}|${decision.b_key}`;
}

// ---------------------------------------------------------------------------------------------
// LocalSource
// ---------------------------------------------------------------------------------------------

export interface LocalSourceOptions {
  /** Null = no persistent storage available: the workspace lives in memory only. */
  storage: StorageLike | null;
  clock?: Clock;
  key?: string;
  backupKey?: string;
}

export interface ExternalChangeTarget {
  addEventListener(type: 'storage', listener: (event: Event) => void): void;
  removeEventListener(type: 'storage', listener: (event: Event) => void): void;
}

const CAPABILITIES: Capabilities = {
  refresh: false,
  loadSample: true,
  removeDataset: true,
  exportPostings: true,
};

export class LocalSource implements AnalysisSource {
  readonly mode = 'local' as const;
  readonly capabilities = CAPABILITIES;
  readonly sources = null;

  private readonly storage: StorageLike | null;
  private readonly clock: Clock;
  private readonly key: string;
  private readonly backupKey: string;
  /** Authoritative copy when storage is absent or blocked. */
  private memory: StoredWorkspace = emptyWorkspace();
  private storageBlocked = false;
  /** Set when stored data cannot be overwritten (newer schema, or unreadable and not backed up). */
  private locked: { message: string; kind: 'newer_schema' | 'corrupt_recovered' } | null = null;
  private recovery: DataNotice | null = null;

  constructor(options: LocalSourceOptions) {
    this.storage = options.storage;
    this.clock = options.clock ?? systemClock;
    this.key = options.key ?? WORKSPACE_KEY;
    this.backupKey = options.backupKey ?? WORKSPACE_BACKUP_KEY;
  }

  // ---- storage ------------------------------------------------------------------------------

  /** True when changes survive a reload. */
  get persistent(): boolean {
    return this.storage !== null && !this.storageBlocked && this.locked === null;
  }

  /** The raw text of the most recent unreadable workspace, if one was backed up. */
  readCorruptBackup(): string | null {
    if (this.storage === null) return null;
    try {
      return this.storage.getItem(this.backupKey);
    } catch {
      return null;
    }
  }

  /** Subscribe to changes made by another tab (the `storage` event). Returns an unsubscribe. */
  watchExternalChanges(target: ExternalChangeTarget, onChange: () => void): () => void {
    const handler = (event: Event): void => {
      const key = (event as { key?: string | null }).key;
      if (key === undefined || key === null || key === this.key) onChange();
    };
    target.addEventListener('storage', handler);
    return () => target.removeEventListener('storage', handler);
  }

  private read(): StoredWorkspace {
    if (this.storage === null) return clone(this.memory);
    const result: VersionedRead<StoredWorkspace> = readVersioned(this.storage, this.key, {
      current: SCHEMA_VERSION,
      schema: workspaceSchema,
    });
    switch (result.status) {
      case 'empty':
        // Another tab (or the user) cleared the key: nothing is left to protect.
        this.locked = null;
        return emptyWorkspace();
      case 'ok':
        this.storageBlocked = false;
        this.locked = null;
        return result.data;
      case 'newer':
        this.locked = {
          kind: 'newer_schema',
          message:
            `The data in this browser was saved by a newer version of RecruitRadar (data format ` +
            `${result.found}; this version understands ${SCHEMA_VERSION}). It is left untouched and ` +
            `this version will not change it. Open the newer version, or erase data in Settings ` +
            `to start over.`,
        };
        return emptyWorkspace();
      case 'corrupt':
        return this.recoverFromUnreadable(result.raw, result.reason);
      case 'unavailable':
        this.storageBlocked = true;
        return clone(this.memory);
    }
  }

  private recoverFromUnreadable(raw: string, reason: string): StoredWorkspace {
    const kept = this.storage !== null && backupRaw(this.storage, this.backupKey, raw);
    if (kept && this.storage !== null) {
      // The unreadable value is safe in the backup; clear it so later reads start clean.
      removeKey(this.storage, this.key);
      this.recovery = {
        kind: 'corrupt_recovered',
        message:
          `The data saved in this browser could not be read (${reason}). A copy of it was kept ` +
          `under the storage key "${this.backupKey}" and the app started with an empty ` +
          `workspace.`,
      };
      this.locked = null;
    } else {
      this.locked = {
        kind: 'corrupt_recovered',
        message:
          `The data saved in this browser could not be read (${reason}) and could not be ` +
          `backed up, so it is left untouched and nothing new will be saved over it. Erase data ` +
          `in Settings to start over.`,
      };
    }
    return emptyWorkspace();
  }

  private assertWritable(): void {
    if (this.locked !== null) {
      throw new SourceError('read_only', this.locked.message);
    }
  }

  private commit(workspace: StoredWorkspace): void {
    workspace.revision += 1;
    workspace.saved_at = this.clock();
    if (this.storage === null || this.storageBlocked) {
      this.memory = workspace;
      return;
    }
    writeText(this.storage, this.key, JSON.stringify(workspace));
    this.memory = workspace;
  }

  /** Read fresh state, apply `change`, validate with the engine, persist. */
  private mutate<T>(change: (workspace: StoredWorkspace, now: string) => T): T {
    const workspace = this.read();
    this.assertWritable();
    const now = this.clock();
    const result = change(workspace, now);
    this.analyseState(workspace, now);
    this.commit(workspace);
    return result;
  }

  private analyseState(workspace: StoredWorkspace, asOf: string): Analysis {
    try {
      return analyze({
        as_of: asOf,
        profile: workspace.profile,
        decisions: workspace.decisions,
        snapshots: workspace.snapshots.map(toParsed),
      });
    } catch (error) {
      if (error instanceof EngineInputError) {
        const first = error.issues[0];
        throw new SourceError(
          'invalid_input',
          first === undefined
            ? 'The change was refused because it is not valid.'
            : `The change was refused: ${first.path} ${first.message}`,
          { details: error.issues, cause: error },
        );
      }
      throw error;
    }
  }

  private requireCapacity(workspace: StoredWorkspace, adding: number): void {
    const total = countPostings(workspace) + adding;
    if (total > MAX_POSTINGS) {
      throw new SourceError(
        'limit',
        `Local-data mode holds at most ${MAX_POSTINGS} postings; this change would bring it to ` +
          `${total}. Nothing was stored. Remove a dataset first.`,
        { code: 'too_many_postings' },
      );
    }
  }

  // ---- reads --------------------------------------------------------------------------------

  async load(): Promise<Workspace> {
    const workspace = this.read();
    const asOf = this.clock();
    let analysis: Analysis;
    try {
      analysis = this.analyseState(workspace, asOf);
    } catch (error) {
      if (error instanceof SourceError && error.kind === 'invalid_input') {
        // Structurally valid JSON whose content the engine rejects: treat as unreadable.
        const raw = this.storage === null ? null : this.safeGet();
        const recovered =
          raw === null
            ? emptyWorkspace()
            : this.recoverFromUnreadable(raw, `its content is invalid (${error.message})`);
        analysis = this.analyseState(recovered, asOf);
        return this.assemble(recovered, analysis);
      }
      throw error;
    }
    return this.assemble(workspace, analysis);
  }

  private safeGet(): string | null {
    try {
      return this.storage === null ? null : this.storage.getItem(this.key);
    } catch {
      return null;
    }
  }

  private assemble(workspace: StoredWorkspace, analysis: Analysis): Workspace {
    const datasets = this.datasetsOf(workspace, analysis);
    const notices: DataNotice[] = [];
    if (this.locked !== null)
      notices.push({ kind: this.locked.kind, message: this.locked.message });
    if (this.recovery !== null) notices.push(this.recovery);
    if (this.storage === null || this.storageBlocked) {
      notices.push({
        kind: 'storage_unavailable',
        message:
          'Browser storage is not available here (private window or blocked site data). Your ' +
          'data is kept in memory only and will be lost when this tab closes. Export CSV to keep it.',
      });
    }
    return {
      mode: 'local',
      analysis,
      profile: workspace.profile,
      decisions: workspace.decisions.map((d): DecisionRecord => ({ ...d, id: decisionId(d) })),
      shortlist: this.resolveShortlist(workspace, analysis),
      datasets,
      has_sample_data: datasets.some((d) => d.synthetic),
      notices,
    };
  }

  private datasetsOf(workspace: StoredWorkspace, analysis: Analysis): DatasetSummary[] {
    const fromAnalysis = new Map(summarizeDatasets(analysis).map((d) => [d.id, d]));
    interface Counts {
      kind: StoredSnapshot['source_kind'];
      ref: string;
      postings: number;
      snapshots: number;
      ignored: number;
      synthetic: boolean;
    }
    const counts = new Map<string, Counts>();
    for (const snapshot of workspace.snapshots) {
      const id = datasetId(snapshot.source_kind, snapshot.source_ref);
      let entry = counts.get(id);
      if (entry === undefined) {
        entry = {
          kind: snapshot.source_kind,
          ref: snapshot.source_ref,
          postings: 0,
          snapshots: 0,
          ignored: 0,
          synthetic: false,
        };
        counts.set(id, entry);
      }
      entry.postings += snapshot.postings.length;
      entry.snapshots += 1;
      if (snapshot.observed_at > analysis.as_of) entry.ignored += 1;
      if (snapshot.synthetic === true) entry.synthetic = true;
    }
    const result: DatasetSummary[] = [];
    for (const [id, entry] of counts) {
      const derived = fromAnalysis.get(id);
      result.push({
        id,
        source_kind: entry.kind,
        source_ref: entry.ref,
        synthetic: entry.synthetic || isSampleLabel(entry.ref),
        postings: entry.postings,
        snapshots: entry.snapshots,
        ignored_snapshots: entry.ignored,
        roles: derived?.roles ?? 0,
        active_roles: derived?.active_roles ?? 0,
        first_seen: derived?.first_seen ?? null,
        last_seen: derived?.last_seen ?? null,
      });
    }
    return result.sort(
      (a, b) =>
        compareCodePoints(a.source_kind, b.source_kind) ||
        compareCodePoints(a.source_ref, b.source_ref),
    );
  }

  /** Stored entries resolved against the analysis; merged duplicates collapse to one entry. */
  private resolveShortlist(workspace: StoredWorkspace, analysis: Analysis): ShortlistEntry[] {
    const byCompany = new Map<string, ShortlistEntry>();
    for (const entry of workspace.shortlist) {
      const company = findCompanyByKey(analysis, entry.key);
      if (company === null) continue;
      const existing = byCompany.get(company.company_id);
      if (existing === undefined) {
        byCompany.set(company.company_id, {
          company_id: company.company_id,
          name: company.name,
          note: entry.note,
          added_at: entry.added_at,
        });
      } else {
        if (entry.added_at < existing.added_at) existing.added_at = entry.added_at;
        if (entry.note !== '' && !existing.note.includes(entry.note)) {
          existing.note = existing.note === '' ? entry.note : `${existing.note}\n${entry.note}`;
        }
      }
    }
    return Array.from(byCompany.values()).sort(
      (a, b) => compareCodePoints(a.added_at, b.added_at) || compareCodePoints(a.name, b.name),
    );
  }

  // ---- writes -------------------------------------------------------------------------------

  async setProfile(profile: Profile): Promise<void> {
    this.mutate((workspace) => {
      workspace.profile = {
        include_keywords: [...profile.include_keywords],
        exclude_keywords: [...profile.exclude_keywords],
      };
    });
  }

  async importCsv(datasetLabel: string, csvText: string): Promise<ImportReport> {
    const workspace = this.read();
    this.assertWritable();
    const now = this.clock();
    const result = engineImportCsv(csvText, {
      dataset_label: datasetLabel,
      imported_at: now,
      snapshot_id_prefix: `csv-${workspace.seq + 1}`,
    });
    const report: ImportReport = {
      dataset_label: result.dataset_label,
      ok: result.ok,
      file_error: result.file_error,
      accepted: result.accepted,
      rejected: result.rejected,
      errors: result.errors,
      warnings: result.warnings,
      rejected_rows: result.rejected_rows,
    };
    if (!result.ok || result.accepted === 0) return report;
    this.requireCapacity(workspace, result.accepted);
    workspace.snapshots.push(...result.snapshots);
    workspace.seq += 1;
    this.analyseState(workspace, now);
    this.commit(workspace);
    return report;
  }

  async addManualPosting(values: PostingFormValues): Promise<SubmitResult> {
    const workspace = this.read();
    this.assertWritable();
    const now = this.clock();
    const trimmed: Record<string, string> = {};
    for (const [field, value] of Object.entries(values)) trimmed[field] = value.trim();
    const validated = validateImportRow(trimmed, now);
    if (!validated.ok) return { ok: false, problems: validated.errors };
    this.requireCapacity(workspace, 1);
    workspace.seq += 1;
    workspace.snapshots.push({
      snapshot_id: `manual-${workspace.seq}`,
      source_kind: 'manual',
      source_ref: 'manual',
      observed_at: now,
      mode: 'additive',
      postings: [{ source_kind: 'manual', source_ref: 'manual', ...validated.posting }],
    });
    this.analyseState(workspace, now);
    this.commit(workspace);
    return { ok: true };
  }

  async decide(aKey: string, bKey: string, decision: DecisionKind): Promise<void> {
    const order = compareCodePoints(aKey, bKey);
    if (order === 0) {
      throw new SourceError('invalid_input', 'A company cannot be merged with itself.');
    }
    const [a, b] = order < 0 ? [aKey, bKey] : [bKey, aKey];
    this.mutate((workspace) => {
      workspace.decisions = workspace.decisions.filter((d) => !(d.a_key === a && d.b_key === b));
      workspace.decisions.push({ a_key: a, b_key: b, decision });
    });
  }

  async undoDecision(id: string): Promise<void> {
    this.mutate((workspace) => {
      const before = workspace.decisions.length;
      workspace.decisions = workspace.decisions.filter((d) => decisionId(d) !== id);
      if (workspace.decisions.length === before) {
        throw new SourceError('not_found', 'That decision no longer exists.', {
          code: 'not_found',
        });
      }
    });
  }

  async setShortlisted(companyId: string, shortlisted: boolean, note?: string): Promise<void> {
    if (note !== undefined && note.length > MAX_NOTE_LENGTH) {
      throw new SourceError(
        'invalid_input',
        `A note can hold at most ${MAX_NOTE_LENGTH} characters (this one has ${note.length}).`,
      );
    }
    this.mutate((workspace, now) => {
      const analysis = this.analyseState(workspace, now);
      const company = analysis.companies.find((c) => c.company_id === companyId);
      if (company === undefined) {
        throw new SourceError('not_found', 'That company is not in the loaded data.', {
          code: 'unknown_company',
        });
      }
      const resolved = this.resolveShortlist(workspace, analysis).find(
        (entry) => entry.company_id === companyId,
      );
      workspace.shortlist = workspace.shortlist.filter(
        (entry) => findCompanyByKey(analysis, entry.key)?.company_id !== companyId,
      );
      if (shortlisted) {
        workspace.shortlist.push({
          key: company.key,
          name: company.name,
          note: note ?? resolved?.note ?? '',
          added_at: resolved?.added_at ?? now,
        });
      }
    });
  }

  async exportShortlistCsv(): Promise<string> {
    const workspace = this.read();
    const analysis = this.analyseState(workspace, this.clock());
    const entries = this.resolveShortlist(workspace, analysis);
    const { rows } = buildShortlistRows(
      analysis,
      entries.map((entry) => ({ company_id: entry.company_id, note: entry.note })),
    );
    return exportShortlistCsv(rows, { bom: true });
  }

  async exportPostingsCsv(id: string | null): Promise<string> {
    const workspace = this.read();
    const wanted = id === null ? null : parseDatasetId(id);
    if (id !== null && wanted === null) {
      throw new SourceError('not_found', 'Unknown dataset.', { code: 'not_found' });
    }
    const snapshots = workspace.snapshots.filter(
      (s) => wanted === null || (s.source_kind === wanted.kind && s.source_ref === wanted.ref),
    );
    return exportPostingsCsv(snapshotsToPostingRows(snapshots), { bom: true });
  }

  async loadSample(): Promise<{ datasets: number; postings: number; keywordsAdded: boolean }> {
    return this.mutate((workspace, now) => {
      const samples = buildSampleDatasets(now);
      const present = workspace.snapshots.some((s) =>
        samples.some((sample) => s.source_kind === 'csv' && s.source_ref === sample.label),
      );
      if (present) {
        throw new SourceError(
          'invalid_input',
          'The sample data is already loaded. Remove it from the dataset list first to load it again.',
          { code: 'sample_exists' },
        );
      }
      let postings = 0;
      for (const sample of samples) postings += sample.postings;
      this.requireCapacity(workspace, postings);
      workspace.seq += 1;
      samples.forEach((sample, index) => {
        const result = engineImportCsv(sample.csv, {
          dataset_label: sample.label,
          imported_at: now,
          snapshot_id_prefix: `sample-${workspace.seq}-${index + 1}`,
        });
        if (!result.ok || result.rejected > 0) {
          throw new SourceError('invalid_input', 'The built-in sample data failed validation.');
        }
        for (const snapshot of result.snapshots) {
          workspace.snapshots.push({ ...snapshot, synthetic: true });
        }
      });
      const keywordsAdded =
        workspace.profile.include_keywords.length === 0 &&
        workspace.profile.exclude_keywords.length === 0;
      if (keywordsAdded) {
        workspace.profile = {
          include_keywords: [...SAMPLE_PROFILE.include_keywords],
          exclude_keywords: [...SAMPLE_PROFILE.exclude_keywords],
        };
      }
      return { datasets: samples.length, postings, keywordsAdded };
    });
  }

  async removeDataset(id: string): Promise<void> {
    const wanted = parseDatasetId(id);
    if (wanted === null) {
      throw new SourceError('not_found', 'Unknown dataset.', { code: 'not_found' });
    }
    this.mutate((workspace, now) => {
      const before = workspace.snapshots.length;
      workspace.snapshots = workspace.snapshots.filter(
        (s) => !(s.source_kind === wanted.kind && s.source_ref === wanted.ref),
      );
      if (workspace.snapshots.length === before) {
        throw new SourceError('not_found', 'That dataset no longer exists.', {
          code: 'not_found',
        });
      }
      // Shortlist entries for companies that no longer exist go with the data they came from.
      const analysis = this.analyseState(workspace, now);
      workspace.shortlist = workspace.shortlist.filter(
        (entry) => findCompanyByKey(analysis, entry.key) !== null,
      );
    });
  }

  async eraseAll(): Promise<void> {
    this.memory = emptyWorkspace();
    if (this.storage !== null) {
      const removed = removeKey(this.storage, this.key);
      removeKey(this.storage, this.backupKey);
      if (!removed && !this.storageBlocked) {
        throw new SourceError(
          'storage_unavailable',
          'Browser storage refused to erase the data. Clear this site’s data in the browser settings.',
        );
      }
    }
    this.locked = null;
    this.recovery = null;
  }
}
