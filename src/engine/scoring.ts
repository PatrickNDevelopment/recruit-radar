/**
 * Per-company scoring (spec 02 §4). Integer arithmetic only: no floating point reaches a score.
 *
 * The score describes *observed hiring activity in the configured roles from the loaded sources*.
 * Components that cannot be computed are null with a reason code and are excluded from the
 * weighted mean; they are never silently scored as zero.
 */
import { containsTokenSequence, normTokens } from './normalize';
import { daysBetweenSeconds, roundHalfUp } from './time';
import type {
  ChangeComponent,
  EventType,
  FreshnessComponent,
  Profile,
  RoleRelevanceComponent,
  ScoreComponent,
  SourceConfidenceComponent,
  SourceKind,
  UrgencyComponent,
  VolumeComponent,
} from './types';

export const WEIGHTS = {
  role_relevance: 30,
  volume: 20,
  change: 15,
  urgency: 10,
  source_confidence: 15,
  freshness: 10,
} as const;

export const CHANGE_WINDOW_DAYS = 30;
export const CHANGE_WINDOW_SECONDS = CHANGE_WINDOW_DAYS * 86400; // 2,592,000
export const MIN_HISTORY_SPAN_DAYS = 14;
export const URGENCY_THRESHOLD_DAYS = 45;
export const FRESH_DAYS = 7;
export const STALE_DAYS = 60;

const VOLUME_TABLE = [0, 300, 480, 600, 690, 760, 820, 870, 910, 950, 1000] as const;

const SOURCE_WEIGHT: Record<SourceKind, number> = {
  greenhouse: 1000,
  lever: 1000,
  ashby: 1000,
  csv: 600,
  manual: 400,
};

// ---------------------------------------------------------------------------------------------
// Keyword matching
// ---------------------------------------------------------------------------------------------

export interface KeywordMatcher {
  /** True when at least one include keyword is configured. */
  readonly configured: boolean;
  /**
   * Whether a title (given as its `title_key`) is "in scope": some include keyword matches and no
   * exclude keyword does. Always true when no keywords are configured.
   */
  titleInScope(titleKeyValue: string): boolean;
}

/**
 * Keyword matching is by token sequence: `"engineer"` matches `"senior engineer"` but not
 * `"engineering manager"`. Keywords that normalize to nothing never match.
 */
export function createKeywordMatcher(profile: Profile): KeywordMatcher {
  const phrases = (list: readonly string[]): string[][] =>
    list.map((keyword) => normTokens(keyword)).filter((tokens) => tokens.length > 0);
  const include = phrases(profile.include_keywords);
  const exclude = phrases(profile.exclude_keywords);
  const configured = profile.include_keywords.length > 0;
  return {
    configured,
    titleInScope(titleKeyValue: string): boolean {
      if (!configured) return true;
      const tokens = titleKeyValue.split(' ').filter((token) => token.length > 0);
      const included = include.some((phrase) => containsTokenSequence(tokens, phrase));
      if (!included) return false;
      return !exclude.some((phrase) => containsTokenSequence(tokens, phrase));
    },
  };
}

// ---------------------------------------------------------------------------------------------
// Scoring
// ---------------------------------------------------------------------------------------------

export interface ScoringRole {
  active: boolean;
  first_seen_seconds: number;
  last_seen_seconds: number;
  posted_at_seconds: number | null;
  /** `null` when no keywords are configured. */
  relevant: boolean | null;
  /** `(source_kind, source_ref)` of every currently-active observation. */
  active_sources: ReadonlyArray<{ source_kind: SourceKind; source_ref: string }>;
}

export interface ScoringEvent {
  at_seconds: number;
  type: EventType;
  /** Whether the event's title is in scope (see {@link KeywordMatcher.titleInScope}). */
  title_in_scope: boolean;
}

export interface ScoringInput {
  roles: readonly ScoringRole[];
  /** All events of the company (any role, any status). */
  events: readonly ScoringEvent[];
  /** Distinct observed_at (epoch seconds) of `full` snapshots of the company's sources. */
  history_times: readonly number[];
  keywords_configured: boolean;
  as_of_seconds: number;
}

export interface ScoringResult {
  components: ScoreComponent[];
  score: number | null;
  coverage: number;
}

function sourceKey(source: { source_kind: SourceKind; source_ref: string }): string {
  return `${source.source_kind}|${source.source_ref}`;
}

function roleConfidence(role: ScoringRole): { value: number; corroborated: boolean } {
  let best = 0;
  const distinct = new Set<string>();
  for (const source of role.active_sources) {
    best = Math.max(best, SOURCE_WEIGHT[source.source_kind]);
    distinct.add(sourceKey(source));
  }
  if (distinct.size >= 2) return { value: Math.min(1000, best + 100), corroborated: true };
  return { value: best, corroborated: false };
}

export function scoreCompany(input: ScoringInput): ScoringResult {
  const active = input.roles.filter((role) => role.active);
  const activeCount = active.length;
  const configured = input.keywords_configured;
  const relevantRoles = configured ? active.filter((role) => role.relevant === true) : [];
  const scope = configured ? relevantRoles : active;

  // T and span_days.
  const times = new Set(input.history_times);
  let spanDays: number | null = null;
  if (times.size >= 2) {
    let min = Infinity;
    let max = -Infinity;
    for (const t of times) {
      if (t < min) min = t;
      if (t > max) max = t;
    }
    spanDays = daysBetweenSeconds(min, max);
  }

  // role_relevance (30)
  let roleRelevance: RoleRelevanceComponent;
  if (activeCount === 0) {
    roleRelevance = component('role_relevance', null, 'no_active_roles', {
      relevant: null,
      active: 0,
    });
  } else if (!configured) {
    roleRelevance = component('role_relevance', null, 'no_keywords', {
      relevant: null,
      active: activeCount,
    });
  } else {
    roleRelevance = component(
      'role_relevance',
      roundHalfUp(1000 * relevantRoles.length, activeCount),
      null,
      { relevant: relevantRoles.length, active: activeCount },
    );
  }

  // volume (20)
  const scopeCount = scope.length;
  const volume: VolumeComponent =
    activeCount === 0
      ? component('volume', null, 'no_active_roles', { scope_roles: 0 })
      : component('volume', VOLUME_TABLE[Math.min(scopeCount, 10)] ?? 0, null, {
          scope_roles: scopeCount,
        });

  // change (15)
  let change: ChangeComponent;
  if (activeCount === 0) {
    change = component('change', null, 'no_active_roles', changeInputs(null, null, spanDays));
  } else if (times.size < 2 || spanDays === null || spanDays < MIN_HISTORY_SPAN_DAYS) {
    change = component('change', null, 'insufficient_history', changeInputs(null, null, spanDays));
  } else {
    let added = 0;
    let removed = 0;
    for (const event of input.events) {
      if (!event.title_in_scope) continue;
      const inWindow =
        event.at_seconds > input.as_of_seconds - CHANGE_WINDOW_SECONDS &&
        event.at_seconds <= input.as_of_seconds;
      if (!inWindow) continue;
      if (event.type === 'added' || event.type === 'reappeared') added += 1;
      else if (event.type === 'removed') removed += 1;
    }
    const net = added - removed;
    change = component(
      'change',
      Math.min(1000, Math.max(0, 500 + 100 * net)),
      null,
      changeInputs(added, removed, spanDays),
    );
  }

  // urgency (10)
  let urgency: UrgencyComponent;
  if (activeCount === 0) {
    urgency = component('urgency', null, 'no_active_roles', {
      aged: null,
      known: null,
      threshold_days: URGENCY_THRESHOLD_DAYS,
    });
  } else {
    let known = 0;
    let aged = 0;
    for (const role of scope) {
      let age: number | null = null;
      if (role.posted_at_seconds !== null) {
        age = Math.max(0, daysBetweenSeconds(role.posted_at_seconds, input.as_of_seconds));
      } else if (spanDays !== null && spanDays >= URGENCY_THRESHOLD_DAYS) {
        age = Math.max(0, daysBetweenSeconds(role.first_seen_seconds, input.as_of_seconds));
      }
      if (age === null) continue;
      known += 1;
      if (age >= URGENCY_THRESHOLD_DAYS) aged += 1;
    }
    const inputs = { aged, known, threshold_days: URGENCY_THRESHOLD_DAYS } as const;
    if (scopeCount === 0) urgency = component('urgency', null, 'no_scope_roles', inputs);
    else if (known === 0) urgency = component('urgency', null, 'no_dated_roles', inputs);
    else urgency = component('urgency', roundHalfUp(1000 * aged, known), null, inputs);
  }

  // source_confidence (15)
  let sourceConfidence: SourceConfidenceComponent;
  if (activeCount === 0) {
    sourceConfidence = component('source_confidence', null, 'no_active_roles', {
      scope_roles: 0,
      corroborated: null,
    });
  } else if (scopeCount === 0) {
    sourceConfidence = component('source_confidence', null, 'no_scope_roles', {
      scope_roles: 0,
      corroborated: 0,
    });
  } else {
    let total = 0;
    let corroborated = 0;
    for (const role of scope) {
      const confidence = roleConfidence(role);
      total += confidence.value;
      if (confidence.corroborated) corroborated += 1;
    }
    sourceConfidence = component('source_confidence', roundHalfUp(total, scopeCount), null, {
      scope_roles: scopeCount,
      corroborated,
    });
  }

  // freshness (10)
  let freshness: FreshnessComponent;
  if (activeCount === 0) {
    freshness = component('freshness', null, 'no_active_roles', { days_since_last_seen: null });
  } else {
    let lastSeen = -Infinity;
    for (const role of active)
      if (role.last_seen_seconds > lastSeen) lastSeen = role.last_seen_seconds;
    const d = Math.max(0, daysBetweenSeconds(lastSeen, input.as_of_seconds));
    let value: number;
    if (d <= FRESH_DAYS) value = 1000;
    else if (d >= STALE_DAYS) value = 0;
    else value = roundHalfUp(1000 * (STALE_DAYS - d), STALE_DAYS - FRESH_DAYS);
    freshness = component('freshness', value, null, { days_since_last_seen: d });
  }

  const components: ScoreComponent[] = [
    roleRelevance,
    volume,
    change,
    urgency,
    sourceConfidence,
    freshness,
  ];

  let coverage = 0;
  let weighted = 0;
  for (const c of components) {
    if (c.value === null) continue;
    coverage += c.weight;
    weighted += c.weight * c.value;
  }
  const score = coverage === 0 ? null : roundHalfUp(weighted, coverage);
  return { components, score, coverage };
}

function changeInputs(added: number | null, removed: number | null, spanDays: number | null) {
  return {
    added,
    removed,
    net: added === null || removed === null ? null : added - removed,
    span_days: spanDays,
    window_days: CHANGE_WINDOW_DAYS,
  } as const;
}

function component<K extends keyof typeof WEIGHTS, I>(
  key: K,
  value: number | null,
  reasonCode: ScoreComponent['reason_code'],
  inputs: I,
): {
  key: K;
  weight: number;
  value: number | null;
  reason_code: ScoreComponent['reason_code'];
  inputs: I;
} {
  return { key, weight: WEIGHTS[key], value, reason_code: reasonCode, inputs };
}
