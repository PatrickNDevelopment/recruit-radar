/**
 * Per-browser preferences: backend address, data-location preference and saved Radar views.
 *
 * These are conveniences, not workspace data: they live under their own key, survive "erase
 * data", and are always readable even when the workspace key is locked or corrupt. A corrupt
 * value falls back to defaults (and keeps a backup of the raw text, like the workspace does).
 */
import { z } from 'zod';
import { DEFAULT_BACKEND_URL, validateBackendUrl } from './connection';
import { backupRaw, readVersioned, writeText, type StorageLike } from './storage';
import {
  DEFAULT_FILTERS,
  DEFAULT_SORT,
  RADAR_SORT_KEYS,
  type ModePreference,
  type RadarFilters,
  type RadarSort,
  type SavedView,
} from './types';

export const PREFS_KEY = 'recruit-radar.prefs';
export const PREFS_BACKUP_KEY = 'recruit-radar.prefs.unreadable-backup';
export const PREFS_VERSION = 1;
export const MAX_SAVED_VIEWS = 50;
export const MAX_VIEW_NAME = 60;

const filtersSchema = z.object({
  text: z.string().max(200),
  work_mode: z.enum(['any', 'remote', 'hybrid', 'onsite', 'unknown']),
  source: z.string().max(400),
  min_score: z.number().min(0).max(100).nullable(),
  shortlisted_only: z.boolean(),
});

const sortSchema = z.object({
  key: z.enum(RADAR_SORT_KEYS),
  direction: z.enum(['asc', 'desc']),
});

const viewSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1).max(MAX_VIEW_NAME),
  filters: filtersSchema,
  sort: sortSchema,
  created_at: z.string(),
});

const prefsSchema = z.object({
  schema_version: z.literal(PREFS_VERSION),
  backend_url: z.string(),
  mode_preference: z.enum(['auto', 'local', 'connected']),
  saved_views: z.array(viewSchema).max(MAX_SAVED_VIEWS),
});

export interface Prefs {
  backend_url: string;
  mode_preference: ModePreference;
  saved_views: SavedView[];
}

export function defaultPrefs(): Prefs {
  return { backend_url: DEFAULT_BACKEND_URL, mode_preference: 'auto', saved_views: [] };
}

export interface PrefsLoad {
  prefs: Prefs;
  /** Present when stored preferences were unreadable or newer and defaults are in use. */
  problem: string | null;
  /** False when preferences must not be written (newer schema in storage). */
  writable: boolean;
}

export class PrefsStore {
  private readonly storage: StorageLike | null;
  private memory: Prefs = defaultPrefs();
  private writable = true;

  constructor(storage: StorageLike | null) {
    this.storage = storage;
  }

  load(): PrefsLoad {
    if (this.storage === null) {
      return { prefs: this.memory, problem: null, writable: true };
    }
    const result = readVersioned(this.storage, PREFS_KEY, {
      current: PREFS_VERSION,
      schema: prefsSchema,
    });
    switch (result.status) {
      case 'ok': {
        this.writable = true;
        const checked = validateBackendUrl(result.data.backend_url);
        this.memory = {
          backend_url: checked.ok ? checked.url : DEFAULT_BACKEND_URL,
          mode_preference: result.data.mode_preference,
          saved_views: result.data.saved_views,
        };
        return { prefs: this.memory, problem: null, writable: true };
      }
      case 'empty':
        this.writable = true;
        return { prefs: this.memory, problem: null, writable: true };
      case 'newer':
        this.writable = false;
        return {
          prefs: defaultPrefs(),
          problem:
            `Settings in this browser were saved by a newer version (format ${result.found}); ` +
            `defaults are used and the saved settings are left untouched.`,
          writable: false,
        };
      case 'corrupt': {
        backupRaw(this.storage, PREFS_BACKUP_KEY, result.raw);
        this.writable = true;
        this.memory = defaultPrefs();
        return {
          prefs: this.memory,
          problem: `Saved settings could not be read (${result.reason}); defaults are used.`,
          writable: true,
        };
      }
      case 'unavailable':
        return { prefs: this.memory, problem: null, writable: true };
    }
  }

  /** Merge `patch` into the current preferences and persist. Throws `SourceError` on failure. */
  save(patch: Partial<Prefs>): Prefs {
    const next: Prefs = { ...this.memory, ...patch };
    if (!this.writable) {
      this.memory = next;
      return next;
    }
    if (this.storage !== null) {
      writeText(
        this.storage,
        PREFS_KEY,
        JSON.stringify({ schema_version: PREFS_VERSION, ...next }),
      );
    }
    this.memory = next;
    return next;
  }
}

// ---------------------------------------------------------------------------------------------
// Saved views
// ---------------------------------------------------------------------------------------------

export function cloneFilters(filters: RadarFilters): RadarFilters {
  return { ...filters };
}

export function cloneSort(sort: RadarSort): RadarSort {
  return { ...sort };
}

export type SaveViewResult =
  { ok: true; views: SavedView[]; replaced: boolean } | { ok: false; message: string };

/**
 * Add or update a saved view by name (case-insensitive: saving "Remote" over "remote" updates it
 * rather than creating a near-duplicate).
 */
export function upsertView(
  views: readonly SavedView[],
  name: string,
  filters: RadarFilters,
  sort: RadarSort,
  now: string,
  makeId: () => string,
): SaveViewResult {
  const trimmed = name.trim().replace(/\s+/gu, ' ');
  if (trimmed === '') return { ok: false, message: 'Give the view a name.' };
  if (trimmed.length > MAX_VIEW_NAME) {
    return { ok: false, message: `View names are at most ${MAX_VIEW_NAME} characters.` };
  }
  const folded = trimmed.toLowerCase();
  const index = views.findIndex((view) => view.name.toLowerCase() === folded);
  if (index >= 0) {
    const existing = views[index];
    if (existing === undefined) return { ok: false, message: 'Unknown view.' };
    const next = views.slice();
    next[index] = {
      ...existing,
      name: trimmed,
      filters: cloneFilters(filters),
      sort: cloneSort(sort),
    };
    return { ok: true, views: next, replaced: true };
  }
  if (views.length >= MAX_SAVED_VIEWS) {
    return {
      ok: false,
      message: `You can keep at most ${MAX_SAVED_VIEWS} saved views. Delete one first.`,
    };
  }
  const view: SavedView = {
    id: makeId(),
    name: trimmed,
    filters: cloneFilters(filters),
    sort: cloneSort(sort),
    created_at: now,
  };
  return { ok: true, views: [...views, view], replaced: false };
}

export function removeView(views: readonly SavedView[], id: string): SavedView[] {
  return views.filter((view) => view.id !== id);
}

export { DEFAULT_FILTERS, DEFAULT_SORT };
