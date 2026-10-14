/**
 * `analyze(input) -> Analysis`: the pure function at the centre of RecruitRadar (spec 02 §1).
 *
 * It never reads the clock, the locale, randomness or the environment; `as_of` is an input.
 * The pipeline is: validate -> filter/sort snapshots -> replay -> resolve identity -> score.
 */
import {
  buildCompanies,
  buildMergeIndex,
  findMergeCandidates,
  type CanonicalRole,
} from './identity';
import type { Company } from './identity';
import { compareCodePoints } from './normalize';
import { KeyCache, replay, type SourceRoleRecord } from './replay';
import { createKeywordMatcher, scoreCompany, type ScoringEvent, type ScoringRole } from './scoring';
import { daysBetweenSeconds, parseDate, parseTimestamp } from './time';
import type {
  Analysis,
  AnalysisEvent,
  CompanyAnalysis,
  RoleAnalysis,
  RoleObservation,
} from './types';
import { parseAnalyzeInput } from './validate';

/** Epoch seconds of a string that was validated at the boundary. */
function seconds(timestamp: string): number {
  const value = parseTimestamp(timestamp);
  if (value === null) throw new Error(`internal: invalid timestamp ${timestamp}`);
  return value;
}

function dateSeconds(date: string): number {
  const value = parseDate(date);
  if (value === null) throw new Error(`internal: invalid date ${date}`);
  return value;
}

function compareObservations(a: RoleObservation, b: RoleObservation): number {
  return (
    compareCodePoints(a.source_kind, b.source_kind) ||
    compareCodePoints(a.source_ref, b.source_ref) ||
    compareCodePoints(a.source_posting_id ?? '', b.source_posting_id ?? '')
  );
}

function observationOf(member: SourceRoleRecord): RoleObservation {
  return {
    source_kind: member.source_kind,
    source_ref: member.source_ref,
    source_posting_id: member.source_posting_id,
    url: member.url,
    status: member.status,
    first_seen: member.first_seen,
    last_seen: member.last_seen,
  };
}

/**
 * Run the full analysis. `input` is validated first (see {@link parseAnalyzeInput}).
 * @throws EngineInputError when the input violates the contract.
 */
export function analyze(input: unknown): Analysis {
  const parsed = parseAnalyzeInput(input);
  const asOf = parsed.as_of;
  const asOfSeconds = seconds(asOf);

  // Snapshots observed after `as_of` are ignored entirely; the rest replay in a fixed order.
  const snapshots = parsed.snapshots
    .filter((snapshot) => snapshot.observed_at <= asOf)
    .sort(
      (a, b) =>
        compareCodePoints(a.observed_at, b.observed_at) ||
        compareCodePoints(a.snapshot_id, b.snapshot_id),
    );

  const keys = new KeyCache();
  const replayed = replay(snapshots, keys);

  const index = buildMergeIndex(parsed.decisions);
  const companies = buildCompanies(replayed.records, index, keys);
  const matcher = createKeywordMatcher(parsed.profile);

  // source role -> canonical role (for event attribution)
  const roleOfRecord = new Map<SourceRoleRecord, CanonicalRole>();
  for (const company of companies) {
    for (const role of company.roles) {
      for (const member of role.members) roleOfRecord.set(member, role);
    }
  }

  // Events grouped by company, as scoring inputs.
  const scoringEventsByCompany = new Map<string, ScoringEvent[]>();
  for (const event of replayed.events) {
    const role = roleOfRecord.get(event.record);
    if (role === undefined) continue;
    let list = scoringEventsByCompany.get(role.company_id);
    if (list === undefined) {
      list = [];
      scoringEventsByCompany.set(role.company_id, list);
    }
    list.push({
      at_seconds: seconds(event.at),
      type: event.type,
      title_in_scope: matcher.titleInScope(keys.title(event.title)),
    });
  }

  interface Built {
    company: Company;
    analysis: CompanyAnalysis;
  }

  const built: Built[] = companies.map((company) => {
    const scoringRoles: ScoringRole[] = company.roles.map((role) => ({
      active: role.status === 'active',
      first_seen_seconds: seconds(role.first_seen),
      last_seen_seconds: seconds(role.last_seen),
      posted_at_seconds: role.posted_at === null ? null : dateSeconds(role.posted_at),
      relevant: matcher.configured ? matcher.titleInScope(role.title_key) : null,
      active_sources: role.members
        .filter((member) => member.status === 'active')
        .map((member) => ({ source_kind: member.source_kind, source_ref: member.source_ref })),
    }));

    const historyTimes: number[] = [];
    for (const sid of company.source_ids) {
      for (const observedAt of replayed.full_times.get(sid) ?? []) {
        historyTimes.push(seconds(observedAt));
      }
    }

    const result = scoreCompany({
      roles: scoringRoles,
      events: scoringEventsByCompany.get(company.company_id) ?? [],
      history_times: historyTimes,
      keywords_configured: matcher.configured,
      as_of_seconds: asOfSeconds,
    });

    let firstSeen = '';
    let lastSeenActive: string | null = null;
    let activeRoles = 0;
    let relevantRoles = 0;
    let removedRoles = 0;
    for (const role of company.roles) {
      if (firstSeen === '' || role.first_seen < firstSeen) firstSeen = role.first_seen;
      if (role.status === 'active') {
        activeRoles += 1;
        if (matcher.configured && matcher.titleInScope(role.title_key)) relevantRoles += 1;
        if (lastSeenActive === null || role.last_seen > lastSeenActive) {
          lastSeenActive = role.last_seen;
        }
      } else {
        removedRoles += 1;
      }
    }

    const analysis: CompanyAnalysis = {
      company_id: company.company_id,
      key: company.key,
      name: company.name,
      aliases: company.aliases,
      first_seen: firstSeen,
      last_seen: lastSeenActive,
      active_roles: activeRoles,
      relevant_roles: matcher.configured ? relevantRoles : null,
      removed_roles: removedRoles,
      score: result.score,
      coverage: result.coverage,
      rank: null,
      components: result.components,
    };
    return { company, analysis };
  });

  // Rank: scored companies by (score desc, key asc, company_id asc); the rest by (key, id).
  const scored = built
    .filter((b) => b.analysis.score !== null)
    .sort(
      (a, b) =>
        (b.analysis.score ?? 0) - (a.analysis.score ?? 0) ||
        compareCodePoints(a.analysis.key, b.analysis.key) ||
        compareCodePoints(a.analysis.company_id, b.analysis.company_id),
    );
  scored.forEach((entry, position) => {
    entry.analysis.rank = position + 1;
  });
  const unscored = built
    .filter((b) => b.analysis.score === null)
    .sort(
      (a, b) =>
        compareCodePoints(a.analysis.key, b.analysis.key) ||
        compareCodePoints(a.analysis.company_id, b.analysis.company_id),
    );
  const ordered = [...scored, ...unscored];

  // Roles: company order, then active first, then first_seen, then role_id.
  const roles: RoleAnalysis[] = [];
  let activeRoleTotal = 0;
  for (const { company, analysis } of ordered) {
    activeRoleTotal += analysis.active_roles;
    const companyRoles = company.roles
      .map((role): RoleAnalysis => {
        const reference =
          role.posted_at !== null ? dateSeconds(role.posted_at) : seconds(role.first_seen);
        return {
          role_id: role.role_id,
          company_id: role.company_id,
          title: role.title,
          location: role.location,
          work_mode: role.work_mode,
          department: role.department,
          posted_at: role.posted_at,
          status: role.status,
          first_seen: role.first_seen,
          last_seen: role.last_seen,
          removed_at: role.removed_at,
          relevant: matcher.configured ? matcher.titleInScope(role.title_key) : null,
          age_days: Math.max(0, daysBetweenSeconds(reference, asOfSeconds)),
          observations: role.members.map(observationOf).sort(compareObservations),
        };
      })
      .sort(
        (a, b) =>
          (a.status === b.status ? 0 : a.status === 'active' ? -1 : 1) ||
          compareCodePoints(a.first_seen, b.first_seen) ||
          compareCodePoints(a.role_id, b.role_id),
      );
    roles.push(...companyRoles);
  }

  const events: AnalysisEvent[] = [];
  for (const event of replayed.events) {
    const role = roleOfRecord.get(event.record);
    if (role === undefined) continue;
    events.push({
      at: event.at,
      type: event.type,
      company_id: role.company_id,
      role_id: role.role_id,
      source_kind: event.record.source_kind,
      source_ref: event.record.source_ref,
      title: event.title,
      fields: event.fields,
    });
  }

  return {
    as_of: asOf,
    companies: ordered.map((entry) => entry.analysis),
    roles,
    events,
    merge_candidates: findMergeCandidates(companies, parsed.decisions),
    stats: {
      snapshots: snapshots.length,
      postings_observed: replayed.postings_observed,
      companies: companies.length,
      active_roles: activeRoleTotal,
    },
  };
}
