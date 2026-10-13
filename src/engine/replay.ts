/**
 * Snapshot replay (spec 02 §2): turns an ordered list of snapshots into per-source role records
 * and a chronological event log. Company / canonical-role identity is NOT resolved here; that
 * happens afterwards (identity.ts) so that merge decisions apply to history.
 */
import { companyKey, compareCodePoints, locationKey, titleKey } from './normalize';
import {
  TRACKED_FIELDS,
  type EventType,
  type ParsedSnapshot,
  type RawPosting,
  type SourceKind,
  type TrackedField,
  type WorkMode,
} from './types';

/** Memoizes the three key derivations; one instance lives for a single `analyze()` call. */
export class KeyCache {
  private readonly companies = new Map<string, string>();
  private readonly titles = new Map<string, string>();
  private readonly locations = new Map<string, string>();

  company(name: string): string {
    let key = this.companies.get(name);
    if (key === undefined) {
      key = companyKey(name);
      this.companies.set(name, key);
    }
    return key;
  }

  title(title: string): string {
    let key = this.titles.get(title);
    if (key === undefined) {
      key = titleKey(title);
      this.titles.set(title, key);
    }
    return key;
  }

  location(location: string | null): string {
    const text = location ?? '';
    let key = this.locations.get(text);
    if (key === undefined) {
      key = locationKey(text);
      this.locations.set(text, key);
    }
    return key;
  }
}

/** A role as one source sees it, tracked across snapshots. */
export interface SourceRoleRecord {
  /** The "source role key string": key parts joined with `|` (see ambiguities doc). */
  readonly key: string;
  readonly source_kind: SourceKind;
  readonly source_ref: string;
  readonly source_posting_id: string | null;
  /** Latest raw (trimmed) company name; company assignment uses this. */
  company_name: string;
  title: string;
  location: string | null;
  work_mode: WorkMode;
  department: string | null;
  url: string | null;
  posted_at: string | null;
  status: 'active' | 'removed';
  first_seen: string;
  last_seen: string;
  removed_at: string | null;
  /** Every distinct raw company name this role was ever observed under. */
  names: Set<string>;
  /** Earliest observation of this role (by snapshot time, then raw name). */
  earliest_at: string;
  earliest_name: string;
}

export interface ReplayEvent {
  at: string;
  type: EventType;
  record: SourceRoleRecord;
  /** Title at event time (the new title for `changed`). */
  title: string;
  fields: TrackedField[] | null;
}

export interface ReplayResult {
  /** All source roles, in creation order. */
  records: SourceRoleRecord[];
  /** Events in processing order. */
  events: ReplayEvent[];
  postings_observed: number;
  /** `sourceId` -> distinct observed_at values of the processed `full` snapshots. */
  full_times: Map<string, Set<string>>;
}

/** Stable id of a `(source_kind, source_ref)` pair; `source_kind` never contains `|`. */
export function sourceId(kind: SourceKind, ref: string): string {
  return `${kind}|${ref}`;
}

/** Spec 01 §4 "source role key", rendered as a single comparable string. */
export function sourceRoleKey(posting: RawPosting, keys: KeyCache): string {
  if (posting.source_posting_id !== null) {
    return [posting.source_kind, posting.source_ref, 'id', posting.source_posting_id].join('|');
  }
  return [
    posting.source_kind,
    posting.source_ref,
    'k',
    keys.company(posting.company_name),
    keys.title(posting.title),
    keys.location(posting.location),
  ].join('|');
}

function changedFields(record: SourceRoleRecord, posting: RawPosting): TrackedField[] {
  const fields: TrackedField[] = [];
  for (const field of TRACKED_FIELDS) {
    if (record[field] !== posting[field]) fields.push(field);
  }
  return fields;
}

function noteObservation(record: SourceRoleRecord, at: string, name: string): void {
  record.names.add(name);
  if (
    at < record.earliest_at ||
    (at === record.earliest_at && compareCodePoints(name, record.earliest_name) < 0)
  ) {
    record.earliest_at = at;
    record.earliest_name = name;
  }
}

/**
 * Replay `snapshots`, which must already be filtered to `observed_at <= as_of` and sorted by
 * `(observed_at, snapshot_id)`.
 */
export function replay(snapshots: readonly ParsedSnapshot[], keys: KeyCache): ReplayResult {
  const rolesBySource = new Map<string, Map<string, SourceRoleRecord>>();
  const seenSources = new Set<string>();
  const fullTimes = new Map<string, Set<string>>();
  const records: SourceRoleRecord[] = [];
  const events: ReplayEvent[] = [];
  let postingsObserved = 0;

  for (const snapshot of snapshots) {
    const sid = sourceId(snapshot.source_kind, snapshot.source_ref);
    const isBaseline = !seenSources.has(sid);
    seenSources.add(sid);
    let roles = rolesBySource.get(sid);
    if (roles === undefined) {
      roles = new Map<string, SourceRoleRecord>();
      rolesBySource.set(sid, roles);
    }
    if (snapshot.mode === 'full') {
      let times = fullTimes.get(sid);
      if (times === undefined) {
        times = new Set<string>();
        fullTimes.set(sid, times);
      }
      times.add(snapshot.observed_at);
    }

    // Step 1: duplicate keys inside one snapshot — the last posting wins, ordered by last index.
    const latest = new Map<string, { index: number; posting: RawPosting }>();
    const observedNames = new Map<string, string[]>();
    snapshot.postings.forEach((posting, index) => {
      postingsObserved += 1;
      const key = sourceRoleKey(posting, keys);
      latest.set(key, { index, posting });
      const names = observedNames.get(key);
      if (names === undefined) observedNames.set(key, [posting.company_name]);
      else names.push(posting.company_name);
    });
    const ordered = Array.from(latest.entries()).sort((a, b) => a[1].index - b[1].index);

    // Step 2: apply each distinct key.
    for (const [key, { posting }] of ordered) {
      let record = roles.get(key);
      if (record === undefined) {
        record = {
          key,
          source_kind: snapshot.source_kind,
          source_ref: snapshot.source_ref,
          source_posting_id: posting.source_posting_id,
          company_name: posting.company_name,
          title: posting.title,
          location: posting.location,
          work_mode: posting.work_mode,
          department: posting.department,
          url: posting.url,
          posted_at: posting.posted_at,
          status: 'active',
          first_seen: snapshot.observed_at,
          last_seen: snapshot.observed_at,
          removed_at: null,
          names: new Set<string>(),
          earliest_at: snapshot.observed_at,
          earliest_name: posting.company_name,
        };
        roles.set(key, record);
        records.push(record);
        events.push({
          at: snapshot.observed_at,
          type: isBaseline ? 'baseline' : 'added',
          record,
          title: posting.title,
          fields: null,
        });
      } else if (record.status === 'active') {
        const fields = changedFields(record, posting);
        applyPosting(record, posting);
        record.last_seen = snapshot.observed_at;
        if (fields.length > 0) {
          events.push({
            at: snapshot.observed_at,
            type: 'changed',
            record,
            title: posting.title,
            fields,
          });
        }
      } else {
        applyPosting(record, posting);
        record.status = 'active';
        record.removed_at = null;
        record.last_seen = snapshot.observed_at;
        events.push({
          at: snapshot.observed_at,
          type: 'reappeared',
          record,
          title: posting.title,
          fields: null,
        });
      }
      for (const name of observedNames.get(key) ?? []) {
        noteObservation(record, snapshot.observed_at, name);
      }
    }

    // Step 3: a `full` snapshot removes every active role of its source that it did not list.
    if (snapshot.mode === 'full') {
      const missing: SourceRoleRecord[] = [];
      for (const record of roles.values()) {
        if (record.status === 'active' && !latest.has(record.key)) missing.push(record);
      }
      missing.sort((a, b) => compareCodePoints(a.key, b.key));
      for (const record of missing) {
        record.status = 'removed';
        record.removed_at = snapshot.observed_at;
        events.push({
          at: snapshot.observed_at,
          type: 'removed',
          record,
          title: record.title,
          fields: null,
        });
      }
    }
  }

  return { records, events, postings_observed: postingsObserved, full_times: fullTimes };
}

/** Copy the mutable, tracked fields and the latest company name onto the record. */
function applyPosting(record: SourceRoleRecord, posting: RawPosting): void {
  record.company_name = posting.company_name;
  record.title = posting.title;
  record.location = posting.location;
  record.work_mode = posting.work_mode;
  record.department = posting.department;
  record.url = posting.url;
  record.posted_at = posting.posted_at;
}
