/**
 * Pure derivations from an `Analysis` that both sources (and the UI) share. Nothing here reads
 * the clock, storage or the network.
 */
import { companyKey, compareCodePoints, type Analysis, type CompanyAnalysis } from '../engine';
import type { CsvPostingRow, Profile, SourceKind } from '../engine';
import type { DatasetSummary } from './types';

/** Dataset labels of the built-in synthetic data start with this reserved prefix. */
export const SAMPLE_LABEL_PREFIX = 'SAMPLE-';

export function isSampleLabel(label: string): boolean {
  return label.startsWith(SAMPLE_LABEL_PREFIX);
}

export function datasetId(kind: SourceKind, ref: string): string {
  return `${kind}:${ref}`;
}

export function parseDatasetId(id: string): { kind: SourceKind; ref: string } | null {
  const at = id.indexOf(':');
  if (at <= 0) return null;
  const kind = id.slice(0, at);
  if (!(['greenhouse', 'lever', 'ashby', 'csv', 'manual'] as const).some((k) => k === kind)) {
    return null;
  }
  return { kind: kind as SourceKind, ref: id.slice(at + 1) };
}

/** Human label for a source: `csv · SAMPLE-A Board export`. */
export function sourceLabel(kind: SourceKind, ref: string): string {
  return kind === 'manual' ? 'manual entry' : `${kind} · ${ref}`;
}

/**
 * Datasets as the analysis sees them: one per `(source_kind, source_ref)` that has at least one
 * observation. Counts are distinct canonical roles, so two datasets that corroborate one role
 * both count it.
 */
export function summarizeDatasets(analysis: Analysis): DatasetSummary[] {
  interface Acc {
    kind: SourceKind;
    ref: string;
    roles: Set<string>;
    active: Set<string>;
    first: string | null;
    last: string | null;
  }
  const byId = new Map<string, Acc>();
  for (const role of analysis.roles) {
    for (const observation of role.observations) {
      const id = datasetId(observation.source_kind, observation.source_ref);
      let acc = byId.get(id);
      if (acc === undefined) {
        acc = {
          kind: observation.source_kind,
          ref: observation.source_ref,
          roles: new Set(),
          active: new Set(),
          first: null,
          last: null,
        };
        byId.set(id, acc);
      }
      acc.roles.add(role.role_id);
      if (observation.status === 'active') acc.active.add(role.role_id);
      if (acc.first === null || observation.first_seen < acc.first)
        acc.first = observation.first_seen;
      if (acc.last === null || observation.last_seen > acc.last) acc.last = observation.last_seen;
    }
  }
  return Array.from(byId.entries())
    .map(([id, acc]): DatasetSummary => ({
      id,
      source_kind: acc.kind,
      source_ref: acc.ref,
      synthetic: isSampleLabel(acc.ref),
      postings: null,
      snapshots: null,
      ignored_snapshots: 0,
      roles: acc.roles.size,
      active_roles: acc.active.size,
      first_seen: acc.first,
      last_seen: acc.last,
    }))
    .sort(
      (a, b) =>
        compareCodePoints(a.source_kind, b.source_kind) ||
        compareCodePoints(a.source_ref, b.source_ref),
    );
}

/**
 * One import-format row per role observation, so the current analysis can be exported (and
 * re-imported) in either mode. `company_name` is the company's display name.
 */
export function rolesToPostingRows(
  analysis: Analysis,
  options: { activeOnly: boolean },
): CsvPostingRow[] {
  const names = new Map(analysis.companies.map((c) => [c.company_id, c.name]));
  const rows: CsvPostingRow[] = [];
  for (const role of analysis.roles) {
    if (options.activeOnly && role.status !== 'active') continue;
    const name = names.get(role.company_id) ?? '';
    for (const observation of role.observations) {
      if (options.activeOnly && observation.status !== 'active') continue;
      rows.push({
        company_name: name,
        title: role.title,
        location: role.location,
        work_mode: role.work_mode,
        department: role.department,
        url: observation.url,
        posted_at: role.posted_at,
        source_posting_id: observation.source_posting_id,
        observed_at: observation.last_seen,
      });
    }
  }
  return rows;
}

/**
 * The company that currently contains a (possibly merged-away) company key. Shortlist entries
 * are stored by key, so a merge — or its undo — never orphans them.
 */
export function findCompanyByKey(analysis: Analysis, key: string): CompanyAnalysis | null {
  const direct = analysis.companies.find((company) => company.key === key);
  if (direct !== undefined) return direct;
  for (const company of analysis.companies) {
    if (company.aliases.some((alias) => companyKey(alias) === key)) return company;
  }
  return null;
}

/** Trim, drop blanks and case-insensitive duplicates, keep first-seen order. */
export function normalizeKeywords(lines: readonly string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const line of lines) {
    const value = line.trim().replace(/\s+/gu, ' ');
    if (value === '') continue;
    const folded = value.toLowerCase();
    if (seen.has(folded)) continue;
    seen.add(folded);
    result.push(value);
  }
  return result;
}

export function sameProfile(a: Profile, b: Profile): boolean {
  const eq = (x: readonly string[], y: readonly string[]) =>
    x.length === y.length && x.every((value, index) => value === y[index]);
  return eq(a.include_keywords, b.include_keywords) && eq(a.exclude_keywords, b.exclude_keywords);
}
