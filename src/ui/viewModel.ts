/**
 * View-model code: everything the screens compute from a `Workspace` that is more than
 * formatting. Pure (no DOM, no React, no clock, no storage), so every rule is unit-tested.
 */
import {
  COMPONENT_KEYS,
  companyKey,
  compareCodePoints,
  normText,
  WORK_MODES,
  type AnalysisEvent,
  type CompanyAnalysis,
  type MergeCandidate,
  type Profile,
  type RoleAnalysis,
  type ScoreComponent,
  type SourceKind,
  type WorkMode,
} from '../engine';
import { datasetId, findCompanyByKey, sourceLabel } from '../data/derive';
import {
  DEFAULT_FILTERS,
  DEFAULT_SORT,
  type DatasetSummary,
  type DecisionRecord,
  type RadarFilters,
  type RadarSort,
  type RadarSortKey,
  type SavedView,
  type ShortlistEntry,
  type Workspace,
} from '../data/types';
import { COMPONENT_RULES, COMPONENT_TITLES, REASONS, WORK_MODE_LABELS } from './copy';
import { agoText, daysBetween, plural, valueText } from './format';

// ---------------------------------------------------------------------------------------------
// Radar rows
// ---------------------------------------------------------------------------------------------

export interface RoleMixEntry {
  mode: WorkMode;
  count: number;
}

export interface RadarRow {
  companyId: string;
  key: string;
  name: string;
  rank: number | null;
  /** 0..1000 or null. */
  score: number | null;
  coverage: number;
  activeRoles: number;
  relevantRoles: number | null;
  removedRoles: number;
  roleMix: RoleMixEntry[];
  locations: string[];
  sourceIds: string[];
  sourceLabels: string[];
  lastSeen: string | null;
  signalAgeDays: number | null;
  shortlisted: boolean;
  /** Components that could not be measured (never scored as zero). */
  missing: number;
  searchText: string;
}

function distinctSorted(values: Iterable<string>): string[] {
  const byFolded = new Map<string, string>();
  for (const value of values) {
    const folded = value.toLowerCase();
    if (!byFolded.has(folded)) byFolded.set(folded, value);
  }
  return Array.from(byFolded.values()).sort(compareCodePoints);
}

/** One row per company in analysis order (ranked first). */
export function buildRadarRows(workspace: Workspace): RadarRow[] {
  const { analysis } = workspace;
  const rolesByCompany = new Map<string, RoleAnalysis[]>();
  for (const role of analysis.roles) {
    const list = rolesByCompany.get(role.company_id);
    if (list === undefined) rolesByCompany.set(role.company_id, [role]);
    else list.push(role);
  }
  const shortlisted = new Set(workspace.shortlist.map((entry) => entry.company_id));

  return analysis.companies.map((company): RadarRow => {
    const roles = rolesByCompany.get(company.company_id) ?? [];
    const active = roles.filter((role) => role.status === 'active');
    const counts = new Map<WorkMode, number>();
    const locations: string[] = [];
    const sources = new Map<string, { kind: SourceKind; ref: string }>();
    for (const role of active) {
      counts.set(role.work_mode, (counts.get(role.work_mode) ?? 0) + 1);
      if (role.location !== null && role.location !== '') locations.push(role.location);
      for (const observation of role.observations) {
        if (observation.status !== 'active') continue;
        sources.set(datasetId(observation.source_kind, observation.source_ref), {
          kind: observation.source_kind,
          ref: observation.source_ref,
        });
      }
    }
    const roleMix: RoleMixEntry[] = WORK_MODES.flatMap((mode) => {
      const count = counts.get(mode) ?? 0;
      return count > 0 ? [{ mode, count }] : [];
    });
    const sourceIds = Array.from(sources.keys()).sort(compareCodePoints);
    const sourceLabels = sourceIds.map((id) => {
      const source = sources.get(id);
      return source === undefined ? id : sourceLabel(source.kind, source.ref);
    });
    const searchable = [
      company.name,
      ...company.aliases,
      ...active.map((role) => role.title),
      ...locations,
    ]
      .map((text) => normText(text))
      .join(' ');
    return {
      companyId: company.company_id,
      key: company.key,
      name: company.name,
      rank: company.rank,
      score: company.score,
      coverage: company.coverage,
      activeRoles: company.active_roles,
      relevantRoles: company.relevant_roles,
      removedRoles: company.removed_roles,
      roleMix,
      locations: distinctSorted(locations),
      sourceIds,
      sourceLabels,
      lastSeen: company.last_seen,
      signalAgeDays: daysBetween(company.last_seen, analysis.as_of),
      shortlisted: shortlisted.has(company.company_id),
      missing: company.components.filter((component) => component.value === null).length,
      searchText: searchable,
    };
  });
}

// ---------------------------------------------------------------------------------------------
// Filters and sorting
// ---------------------------------------------------------------------------------------------

export function filtersAreDefault(filters: RadarFilters): boolean {
  return (
    filters.text.trim() === '' &&
    filters.work_mode === DEFAULT_FILTERS.work_mode &&
    filters.source === DEFAULT_FILTERS.source &&
    filters.min_score === DEFAULT_FILTERS.min_score &&
    filters.shortlisted_only === DEFAULT_FILTERS.shortlisted_only
  );
}

export function filterRows(rows: readonly RadarRow[], filters: RadarFilters): RadarRow[] {
  const tokens = normText(filters.text)
    .split(' ')
    .filter((token) => token !== '');
  const minimum = filters.min_score === null ? null : Math.round(filters.min_score * 10);
  return rows.filter((row) => {
    if (tokens.some((token) => !row.searchText.includes(token))) return false;
    if (filters.work_mode !== 'any' && !row.roleMix.some((e) => e.mode === filters.work_mode)) {
      return false;
    }
    if (filters.source !== 'any' && !row.sourceIds.includes(filters.source)) return false;
    if (minimum !== null && (row.score === null || row.score < minimum)) return false;
    if (filters.shortlisted_only && !row.shortlisted) return false;
    return true;
  });
}

function sortValue(row: RadarRow, key: RadarSortKey): number | string | null {
  switch (key) {
    case 'rank':
      return row.rank;
    case 'name':
      return row.name.toLowerCase();
    case 'active_roles':
      return row.activeRoles;
    case 'relevant_roles':
      return row.relevantRoles;
    case 'last_seen':
      return row.lastSeen;
    case 'score':
      return row.score;
    case 'coverage':
      return row.coverage;
  }
}

/**
 * Stable sort. Missing values (no score, no last-seen date, no keywords) always go last, in
 * either direction, so an unscored company never looks like the lowest score.
 */
export function sortRows(rows: readonly RadarRow[], sort: RadarSort): RadarRow[] {
  const direction = sort.direction === 'asc' ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      const a = sortValue(left.row, sort.key);
      const b = sortValue(right.row, sort.key);
      if (a === null && b !== null) return 1;
      if (a !== null && b === null) return -1;
      if (a !== null && b !== null && a !== b) {
        const order =
          typeof a === 'number' && typeof b === 'number'
            ? a - b
            : compareCodePoints(String(a), String(b));
        if (order !== 0) return order * direction;
      }
      return (
        compareCodePoints(left.row.name.toLowerCase(), right.row.name.toLowerCase()) ||
        compareCodePoints(left.row.companyId, right.row.companyId) ||
        left.index - right.index
      );
    })
    .map((entry) => entry.row);
}

export function radarView(workspace: Workspace, filters: RadarFilters, sort: RadarSort) {
  const all = buildRadarRows(workspace);
  const rows = sortRows(filterRows(all, filters), sort);
  return { all, rows };
}

/** Clicking a column header: the same column flips, a new column starts in its natural order. */
export function nextSort(current: RadarSort, key: RadarSortKey): RadarSort {
  if (current.key === key) {
    return { key, direction: current.direction === 'asc' ? 'desc' : 'asc' };
  }
  return { key, direction: key === 'name' || key === 'rank' ? 'asc' : 'desc' };
}

export function ariaSortFor(
  current: RadarSort,
  key: RadarSortKey,
): 'ascending' | 'descending' | 'none' {
  if (current.key !== key) return 'none';
  return current.direction === 'asc' ? 'ascending' : 'descending';
}

export const SORT_LABELS: Readonly<Record<RadarSortKey, string>> = {
  rank: 'Rank',
  name: 'Company',
  active_roles: 'Active roles',
  relevant_roles: 'Relevant roles',
  last_seen: 'Last seen',
  score: 'Priority score',
  coverage: 'Coverage',
};

/** Reset what no longer exists: a view saved against a dataset that has since been removed. */
export function reconcileFilters(
  filters: RadarFilters,
  datasets: readonly DatasetSummary[],
): { filters: RadarFilters; dropped: string[] } {
  const dropped: string[] = [];
  let result = filters;
  if (filters.source !== 'any' && !datasets.some((dataset) => dataset.id === filters.source)) {
    dropped.push(`the source "${filters.source}" is not loaded any more`);
    result = { ...result, source: 'any' };
  }
  return { filters: result, dropped };
}

export function viewMatches(view: SavedView, filters: RadarFilters, sort: RadarSort): boolean {
  return (
    view.sort.key === sort.key &&
    view.sort.direction === sort.direction &&
    view.filters.text === filters.text &&
    view.filters.work_mode === filters.work_mode &&
    view.filters.source === filters.source &&
    view.filters.min_score === filters.min_score &&
    view.filters.shortlisted_only === filters.shortlisted_only
  );
}

export { DEFAULT_FILTERS, DEFAULT_SORT };

/** "2 remote · 1 hybrid", or an em-dash-free fallback when there are no active roles. */
export function roleMixText(mix: readonly RoleMixEntry[]): string {
  if (mix.length === 0) return 'No active roles';
  return mix
    .map((entry) => `${entry.count} ${WORK_MODE_LABELS[entry.mode].toLowerCase()}`)
    .join(' · ');
}

export function signalText(row: Pick<RadarRow, 'lastSeen' | 'signalAgeDays'>): string {
  if (row.lastSeen === null) return 'No active roles';
  return `Last seen ${agoText(row.signalAgeDays)}`;
}

// ---------------------------------------------------------------------------------------------
// Score breakdown
// ---------------------------------------------------------------------------------------------

export interface ComponentView {
  key: ScoreComponent['key'];
  title: string;
  weight: number;
  /** 0..1000 or null. */
  value: number | null;
  /** "66.7" on the 0-100 display scale, or "Not measured". */
  valueText: string;
  /** What was counted, in words, from the engine's `inputs`; the missing reason when null. */
  calculation: string;
  /** The formula, in words. */
  rule: string;
  missing: { text: string; help: string } | null;
  /** The urgency component is only ever a possible signal. */
  caution: boolean;
}

function signed(value: number): string {
  return value > 0 ? `+${value}` : String(value);
}

/** Human-readable calculation for one component, built from its `inputs`. */
export function describeInputs(
  component: ScoreComponent,
  context: { keywordsConfigured: boolean },
): string {
  if (component.value === null) {
    const reason = component.reason_code;
    return reason === null ? 'Not measured.' : REASONS[reason].text;
  }
  switch (component.key) {
    case 'role_relevance': {
      const { relevant, active } = component.inputs;
      const count = relevant ?? 0;
      return `${count} of ${plural(active, 'active role')} ${count === 1 ? 'matches' : 'match'} your keywords`;
    }
    case 'volume': {
      const { scope_roles } = component.inputs;
      return context.keywordsConfigured
        ? `${plural(scope_roles, 'active role')} in scope (matching your keywords)`
        : `${plural(scope_roles, 'active role')} in scope (no keywords are set, so every active role counts)`;
    }
    case 'change': {
      const { added, removed, net, span_days } = component.inputs;
      const scope = context.keywordsConfigured ? ', counting roles that match your keywords' : '';
      return (
        `${added ?? 0} added or listed again and ${removed ?? 0} no longer listed in the last ` +
        `30 days (net ${signed(net ?? 0)}${scope}); the full-list history spans ` +
        `${plural(span_days ?? 0, 'day')}`
      );
    }
    case 'urgency': {
      const { aged, known, threshold_days } = component.inputs;
      const knownRoles = known ?? 0;
      return (
        `${aged ?? 0} of ${plural(knownRoles, 'dated role')} ` +
        `${(aged ?? 0) === 1 && knownRoles === 1 ? 'has' : 'have'} been listed for ` +
        `${threshold_days} or more days`
      );
    }
    case 'source_confidence': {
      const { scope_roles, corroborated } = component.inputs;
      return (
        `${plural(scope_roles, 'role')} in scope; ` +
        `${corroborated ?? 0} listed by two or more different sources`
      );
    }
    case 'freshness': {
      const days = component.inputs.days_since_last_seen ?? 0;
      return days === 0
        ? 'Newest active role was seen today'
        : `Newest active role was last seen ${plural(days, 'day')} ago`;
    }
  }
}

export function componentViews(company: CompanyAnalysis, profile: Profile): ComponentView[] {
  const keywordsConfigured = profile.include_keywords.length > 0;
  return company.components.map((component): ComponentView => {
    const reason = component.reason_code === null ? null : REASONS[component.reason_code];
    return {
      key: component.key,
      title: COMPONENT_TITLES[component.key],
      weight: component.weight,
      value: component.value,
      valueText: component.value === null ? 'Not measured' : valueText(component.value),
      calculation: describeInputs(component, { keywordsConfigured }),
      rule: COMPONENT_RULES[component.key],
      missing: component.value === null ? (reason ?? { text: 'Not measured.', help: '' }) : null,
      caution: component.key === 'urgency',
    };
  });
}

/** The components that could not be measured, in the engine's fixed order. */
export function missingInformation(views: readonly ComponentView[]): ComponentView[] {
  return views.filter((view) => view.value === null);
}

/** `Σ weight` of the measured components, as the share of the 100 weight points. */
export function coverageText(company: Pick<CompanyAnalysis, 'coverage' | 'components'>): string {
  const measured = company.components.filter((component) => component.value !== null).length;
  return `${company.coverage}% (${measured} of ${COMPONENT_KEYS.length} components measured)`;
}

// ---------------------------------------------------------------------------------------------
// Company detail
// ---------------------------------------------------------------------------------------------

export interface RoleSourceLink {
  label: string;
  url: string | null;
  status: 'active' | 'removed';
}

export interface RoleRow {
  role: RoleAnalysis;
  sources: RoleSourceLink[];
}

export interface ProvenanceRow {
  key: string;
  sourceKind: SourceKind;
  sourceRef: string;
  sourceLabel: string;
  postingId: string | null;
  roleTitle: string;
  status: 'active' | 'removed';
  firstObserved: string;
  lastObserved: string;
  url: string | null;
  synthetic: boolean;
}

export interface CompanyDetail {
  company: CompanyAnalysis;
  roles: RoleRow[];
  events: AnalysisEvent[];
  components: ComponentView[];
  missing: ComponentView[];
  provenance: ProvenanceRow[];
  shortlist: ShortlistEntry | null;
  candidates: MergeCandidate[];
  signalAgeDays: number | null;
}

export function buildCompanyDetail(
  workspace: Workspace,
  companyId: string,
  sampleLabels: ReadonlySet<string> = new Set(),
): CompanyDetail | null {
  const { analysis } = workspace;
  const company = analysis.companies.find((candidate) => candidate.company_id === companyId);
  if (company === undefined) return null;

  const roles = analysis.roles
    .filter((role) => role.company_id === companyId)
    .map((role): RoleRow => ({
      role,
      sources: role.observations.map((observation) => ({
        label: sourceLabel(observation.source_kind, observation.source_ref),
        url: observation.url,
        status: observation.status,
      })),
    }));

  // Newest first; for equal times the engine's processing order is kept, reversed.
  const events = analysis.events
    .map((event, index) => ({ event, index }))
    .filter((entry) => entry.event.company_id === companyId)
    .sort((a, b) => compareCodePoints(b.event.at, a.event.at) || b.index - a.index)
    .map((entry) => entry.event);

  const provenance: ProvenanceRow[] = [];
  for (const { role } of roles) {
    for (const observation of role.observations) {
      provenance.push({
        key: `${role.role_id}|${observation.source_kind}|${observation.source_ref}|${observation.source_posting_id ?? ''}`,
        sourceKind: observation.source_kind,
        sourceRef: observation.source_ref,
        sourceLabel: sourceLabel(observation.source_kind, observation.source_ref),
        postingId: observation.source_posting_id,
        roleTitle: role.title,
        status: observation.status,
        firstObserved: observation.first_seen,
        lastObserved: observation.last_seen,
        url: observation.url,
        synthetic: sampleLabels.has(datasetId(observation.source_kind, observation.source_ref)),
      });
    }
  }
  provenance.sort(
    (a, b) =>
      compareCodePoints(a.sourceLabel, b.sourceLabel) ||
      compareCodePoints(a.roleTitle, b.roleTitle) ||
      compareCodePoints(a.key, b.key),
  );

  const components = componentViews(company, workspace.profile);
  const names = new Set([company.key, ...company.aliases.map((alias) => normText(alias))]);
  const candidates = analysis.merge_candidates.filter(
    (candidate) =>
      names.has(candidate.a_key) ||
      names.has(candidate.b_key) ||
      findCompanyByKey(analysis, candidate.a_key)?.company_id === companyId ||
      findCompanyByKey(analysis, candidate.b_key)?.company_id === companyId,
  );

  return {
    company,
    roles,
    events,
    components,
    missing: missingInformation(components),
    provenance,
    shortlist: workspace.shortlist.find((entry) => entry.company_id === companyId) ?? null,
    candidates,
    signalAgeDays: daysBetween(company.last_seen, analysis.as_of),
  };
}

// ---------------------------------------------------------------------------------------------
// Merge review
// ---------------------------------------------------------------------------------------------

export interface DecisionRow {
  record: DecisionRecord;
  aName: string;
  bName: string;
  kind: 'merge' | 'not_same';
}

export function decisionRows(workspace: Workspace): DecisionRow[] {
  // A merged company has one display name, but a decision is about two spellings: prefer the
  // raw name that produced each key so "DoorDash and Door Dash" does not read "DoorDash and DoorDash".
  const nameOf = (key: string): string => {
    for (const company of workspace.analysis.companies) {
      const alias = company.aliases.find((candidate) => companyKey(candidate) === key);
      if (alias !== undefined) return alias;
    }
    return findCompanyByKey(workspace.analysis, key)?.name ?? key;
  };
  return workspace.decisions.map((record) => ({
    record,
    aName: nameOf(record.a_key),
    bName: nameOf(record.b_key),
    kind: record.decision,
  }));
}

// ---------------------------------------------------------------------------------------------
// Datasets and files
// ---------------------------------------------------------------------------------------------

export function sampleDatasetIds(datasets: readonly DatasetSummary[]): Set<string> {
  return new Set(datasets.filter((dataset) => dataset.synthetic).map((dataset) => dataset.id));
}

/** `recruit-radar-shortlist-2026-10-13.csv` */
export function exportFileName(kind: string, asOf: string): string {
  const safe = kind
    .toLowerCase()
    .replace(/[^a-z0-9]+/gu, '-')
    .replace(/^-+|-+$/gu, '');
  return `recruit-radar-${safe === '' ? 'export' : safe}-${asOf.slice(0, 10)}.csv`;
}

export function datasetTitle(dataset: Pick<DatasetSummary, 'source_kind' | 'source_ref'>): string {
  return sourceLabel(dataset.source_kind, dataset.source_ref);
}
