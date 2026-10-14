/**
 * Company identity, merge candidates and canonical-role dedup (spec 01 §3–§4).
 * Runs after replay, so user merge decisions apply to the whole history.
 */
import { compareCodePoints, sortCodePoints } from './normalize';
import { KeyCache, sourceId, type SourceRoleRecord } from './replay';
import { sha12 } from './sha256';
import type { MergeCandidate, MergeDecision, MergeReason, SourceKind } from './types';

// ---------------------------------------------------------------------------------------------
// Merge decisions (union-find over company keys)
// ---------------------------------------------------------------------------------------------

/**
 * Union-find over company keys whose root is always the group's smallest key (code-point order),
 * which is exactly the canonical key of spec 01 §3.3. Keys named by a decision but absent from
 * the data still take part, so merges are transitive through them.
 */
export class MergeIndex {
  private readonly parent = new Map<string, string>();

  find(key: string): string {
    let root = key;
    for (;;) {
      const up = this.parent.get(root);
      if (up === undefined || up === root) break;
      root = up;
    }
    // Path compression.
    let node = key;
    while (node !== root) {
      const up = this.parent.get(node) ?? root;
      this.parent.set(node, root);
      node = up;
    }
    return root;
  }

  union(a: string, b: string): void {
    const rootA = this.find(a);
    const rootB = this.find(b);
    if (rootA === rootB) return;
    if (compareCodePoints(rootA, rootB) < 0) this.parent.set(rootB, rootA);
    else this.parent.set(rootA, rootB);
  }
}

export function buildMergeIndex(decisions: readonly MergeDecision[]): MergeIndex {
  const index = new MergeIndex();
  for (const decision of decisions) {
    if (decision.decision === 'merge') index.union(decision.a_key, decision.b_key);
  }
  return index;
}

// ---------------------------------------------------------------------------------------------
// Canonical roles and companies
// ---------------------------------------------------------------------------------------------

export interface CanonicalRole {
  role_id: string;
  company_id: string;
  title_key: string;
  location_key: string;
  /** One member per source, ordered by `(source_kind, source_ref)`. */
  members: SourceRoleRecord[];
  status: 'active' | 'removed';
  first_seen: string;
  last_seen: string;
  removed_at: string | null;
  posted_at: string | null;
  title: string;
  location: string | null;
  work_mode: SourceRoleRecord['work_mode'];
  department: string | null;
}

export interface Company {
  company_id: string;
  /** Canonical key (smallest member key of the merged group). */
  key: string;
  name: string;
  aliases: string[];
  records: SourceRoleRecord[];
  roles: CanonicalRole[];
  source_ids: Set<string>;
}

function compareSources(
  a: { kind: SourceKind; ref: string },
  b: { kind: SourceKind; ref: string },
): number {
  return compareCodePoints(a.kind, b.kind) || compareCodePoints(a.ref, b.ref);
}

function buildRoles(
  companyId: string,
  records: readonly SourceRoleRecord[],
  keys: KeyCache,
): CanonicalRole[] {
  // Group by (title_key, location_key), then by source.
  const groups = new Map<
    string,
    { title_key: string; location_key: string; sources: Map<string, SourceRoleRecord[]> }
  >();
  for (const record of records) {
    const tKey = keys.title(record.title);
    const lKey = keys.location(record.location);
    const groupKey = `${tKey}|${lKey}`; // keys hold only letters, numbers, marks and spaces
    let group = groups.get(groupKey);
    if (group === undefined) {
      group = { title_key: tKey, location_key: lKey, sources: new Map() };
      groups.set(groupKey, group);
    }
    const sid = sourceId(record.source_kind, record.source_ref);
    const list = group.sources.get(sid);
    if (list === undefined) group.sources.set(sid, [record]);
    else list.push(record);
  }

  const roles: CanonicalRole[] = [];
  for (const group of groups.values()) {
    const perSource = Array.from(group.sources.values())
      .map((list) => list.slice().sort((a, b) => compareCodePoints(a.key, b.key)))
      .sort((a, b) => {
        const first = a[0];
        const second = b[0];
        if (first === undefined || second === undefined) return 0;
        return compareSources(
          { kind: first.source_kind, ref: first.source_ref },
          { kind: second.source_kind, ref: second.source_ref },
        );
      });
    const count = perSource.reduce((max, list) => Math.max(max, list.length), 0);
    for (let i = 0; i < count; i += 1) {
      const members: SourceRoleRecord[] = [];
      for (const list of perSource) {
        const member = list[i];
        if (member !== undefined) members.push(member);
      }
      const roleId = `r_${sha12(`${companyId}|${group.title_key}|${group.location_key}|${i}`)}`;
      roles.push(canonicalRole(roleId, companyId, group.title_key, group.location_key, members));
    }
  }
  return roles;
}

function canonicalRole(
  roleId: string,
  companyId: string,
  titleKeyValue: string,
  locationKeyValue: string,
  members: SourceRoleRecord[],
): CanonicalRole {
  const active = members.filter((m) => m.status === 'active');
  const lastSeenPool = active.length > 0 ? active : members;
  let firstSeen = members[0]?.first_seen ?? '';
  for (const m of members) if (m.first_seen < firstSeen) firstSeen = m.first_seen;
  let lastSeen = lastSeenPool[0]?.last_seen ?? '';
  for (const m of lastSeenPool) if (m.last_seen > lastSeen) lastSeen = m.last_seen;

  let removedAt: string | null = null;
  if (active.length === 0) {
    for (const m of members) {
      if (m.removed_at !== null && (removedAt === null || m.removed_at > removedAt)) {
        removedAt = m.removed_at;
      }
    }
  }

  let postedAt: string | null = null;
  for (const m of members) {
    if (m.posted_at !== null && (postedAt === null || m.posted_at < postedAt))
      postedAt = m.posted_at;
  }

  // Display fields come from the member seen most recently (ties: smallest source role key).
  let display = members[0];
  for (const m of members) {
    if (display === undefined) {
      display = m;
    } else if (
      m.last_seen > display.last_seen ||
      (m.last_seen === display.last_seen && compareCodePoints(m.key, display.key) < 0)
    ) {
      display = m;
    }
  }
  if (display === undefined) throw new Error('canonical role without members');

  return {
    role_id: roleId,
    company_id: companyId,
    title_key: titleKeyValue,
    location_key: locationKeyValue,
    members,
    status: active.length > 0 ? 'active' : 'removed',
    first_seen: firstSeen,
    last_seen: lastSeen,
    removed_at: removedAt,
    posted_at: postedAt,
    title: display.title,
    location: display.location,
    work_mode: display.work_mode,
    department: display.department,
  };
}

/**
 * Group source roles into companies (via merge decisions) and canonical roles.
 * Every source role belongs to exactly one canonical role and every company has >= 1 role.
 */
export function buildCompanies(
  records: readonly SourceRoleRecord[],
  index: MergeIndex,
  keys: KeyCache,
): Company[] {
  const byKey = new Map<string, SourceRoleRecord[]>();
  for (const record of records) {
    const canonical = index.find(keys.company(record.company_name));
    const list = byKey.get(canonical);
    if (list === undefined) byKey.set(canonical, [record]);
    else list.push(record);
  }

  const companies: Company[] = [];
  for (const [key, group] of byKey) {
    const companyId = `c_${sha12(key)}`;
    const names = new Set<string>();
    const sourceIds = new Set<string>();
    let earliestAt = '';
    let name = '';
    for (const record of group) {
      for (const n of record.names) names.add(n);
      sourceIds.add(sourceId(record.source_kind, record.source_ref));
      if (
        name === '' ||
        record.earliest_at < earliestAt ||
        (record.earliest_at === earliestAt && compareCodePoints(record.earliest_name, name) < 0)
      ) {
        earliestAt = record.earliest_at;
        name = record.earliest_name;
      }
    }
    companies.push({
      company_id: companyId,
      key,
      name,
      aliases: sortCodePoints(names),
      records: group,
      roles: buildRoles(companyId, group, keys),
      source_ids: sourceIds,
    });
  }
  return companies;
}

// ---------------------------------------------------------------------------------------------
// Merge candidates
// ---------------------------------------------------------------------------------------------

/** Joins two company keys into one set member; company keys never contain NUL. */
const PAIR_SEPARATOR = '\u0000';

const REASON_ORDER: Record<MergeReason, number> = {
  spacing_variant: 0,
  token_overlap: 1,
  near_typo: 2,
};

/** True when the edit distance (insert / delete / substitute one code point) is at most 1. */
export function withinOneEdit(a: readonly string[], b: readonly string[]): boolean {
  const lengthDifference = a.length - b.length;
  if (lengthDifference > 1 || lengthDifference < -1) return false;
  const shorter = a.length <= b.length ? a : b;
  const longer = a.length <= b.length ? b : a;
  let i = 0;
  while (i < shorter.length && shorter[i] === longer[i]) i += 1;
  if (i === shorter.length) return true; // identical, or one trailing insertion
  if (shorter.length === longer.length) {
    // One substitution: everything after position i must match.
    for (let k = i + 1; k < shorter.length; k += 1) if (shorter[k] !== longer[k]) return false;
    return true;
  }
  // One insertion in `longer` at position i.
  for (let k = i; k < shorter.length; k += 1) if (shorter[k] !== longer[k + 1]) return false;
  return true;
}

interface CandidateSide {
  key: string;
  name: string;
  tokens: string[];
  tokenSet: Set<string>;
  compact: string;
  points: string[];
}

/**
 * Pairs of distinct companies that look alike but are never merged automatically. Uses inverted
 * indexes (compact key, token, one-deletion variants) instead of an all-pairs scan.
 */
export function findMergeCandidates(
  companies: readonly Company[],
  decisions: readonly MergeDecision[],
): MergeCandidate[] {
  const sides: CandidateSide[] = companies
    .map((company) => {
      const tokens = company.key.split(' ').filter((t) => t.length > 0);
      return {
        key: company.key,
        name: company.name,
        tokens,
        tokenSet: new Set(tokens),
        compact: company.key.split(' ').join(''),
        points: Array.from(company.key),
      };
    })
    .sort((a, b) => compareCodePoints(a.key, b.key));

  // A `not_same` decision suppresses exactly the pair of keys it names (spec 01 §3.4: a candidate
  // is emitted for a pair of group canonical keys "not marked not_same"; decisions and candidates
  // share the `a_key`/`b_key` vocabulary and decisions are created from a candidate's own keys).
  // A decision that names a non-canonical member of a merged group therefore does not hide the
  // candidate between the groups' canonical keys. docs/spec/ambiguities/differential.md D-4.
  const separated = new Set<string>();
  for (const decision of decisions) {
    if (decision.decision !== 'not_same') continue;
    separated.add(`${decision.a_key}${PAIR_SEPARATOR}${decision.b_key}`);
  }

  const found = new Map<string, { i: number; j: number; order: number }>();
  const note = (i: number, j: number, reason: MergeReason): void => {
    const a = Math.min(i, j);
    const b = Math.max(i, j);
    const id = `${a}:${b}`;
    const order = REASON_ORDER[reason];
    const existing = found.get(id);
    if (existing === undefined || order < existing.order) found.set(id, { i: a, j: b, order });
  };

  // spacing_variant: equal after removing all spaces.
  const byCompact = new Map<string, number[]>();
  sides.forEach((side, i) => {
    const list = byCompact.get(side.compact);
    if (list === undefined) byCompact.set(side.compact, [i]);
    else list.push(i);
  });
  for (const list of byCompact.values()) {
    for (let x = 0; x < list.length; x += 1) {
      for (let y = x + 1; y < list.length; y += 1) {
        note(list[x] ?? 0, list[y] ?? 0, 'spacing_variant');
      }
    }
  }

  // token_overlap: both >= 2 tokens and |A∩B| * 100 >= 75 * |A∪B| (token sets).
  const byToken = new Map<string, number[]>();
  sides.forEach((side, i) => {
    if (side.tokens.length < 2) return;
    for (const token of side.tokenSet) {
      const list = byToken.get(token);
      if (list === undefined) byToken.set(token, [i]);
      else list.push(i);
    }
  });
  sides.forEach((side, i) => {
    if (side.tokens.length < 2) return;
    const shared = new Map<number, number>();
    for (const token of side.tokenSet) {
      for (const j of byToken.get(token) ?? []) {
        if (j > i) shared.set(j, (shared.get(j) ?? 0) + 1);
      }
    }
    for (const [j, intersection] of shared) {
      const other = sides[j];
      if (other === undefined) continue;
      const union = side.tokenSet.size + other.tokenSet.size - intersection;
      if (intersection * 100 >= 75 * union) note(i, j, 'token_overlap');
    }
  });

  // near_typo: both keys >= 6 code points and Levenshtein distance <= 1. Two such keys always
  // share either the key itself or a one-deletion variant, so bucket on those and verify.
  const buckets = new Map<string, number[]>();
  sides.forEach((side, i) => {
    if (side.points.length < 6) return;
    const variants = new Set<string>([side.key]);
    for (let drop = 0; drop < side.points.length; drop += 1) {
      variants.add(side.points.slice(0, drop).join('') + side.points.slice(drop + 1).join(''));
    }
    for (const variant of variants) {
      const list = buckets.get(variant);
      if (list === undefined) buckets.set(variant, [i]);
      else list.push(i);
    }
  });
  const verified = new Set<string>();
  for (const list of buckets.values()) {
    for (let x = 0; x < list.length; x += 1) {
      for (let y = x + 1; y < list.length; y += 1) {
        const i = list[x] ?? 0;
        const j = list[y] ?? 0;
        const id = `${i}:${j}`;
        if (verified.has(id)) continue;
        verified.add(id);
        const a = sides[i];
        const b = sides[j];
        if (a !== undefined && b !== undefined && withinOneEdit(a.points, b.points)) {
          note(i, j, 'near_typo');
        }
      }
    }
  }

  const reasons: MergeReason[] = ['spacing_variant', 'token_overlap', 'near_typo'];
  const ranked: Array<{ order: number; candidate: MergeCandidate }> = [];
  for (const { i, j, order } of found.values()) {
    const a = sides[i];
    const b = sides[j];
    if (a === undefined || b === undefined) continue;
    if (separated.has(`${a.key}${PAIR_SEPARATOR}${b.key}`)) continue;
    ranked.push({
      order,
      candidate: {
        candidate_id: sha12(`${a.key}|${b.key}`),
        a_key: a.key,
        b_key: b.key,
        a_name: a.name,
        b_name: b.name,
        reason: reasons[order] ?? 'near_typo',
      },
    });
  }
  ranked.sort(
    (x, y) =>
      x.order - y.order ||
      compareCodePoints(x.candidate.a_key, y.candidate.a_key) ||
      compareCodePoints(x.candidate.b_key, y.candidate.b_key),
  );
  return ranked.map((entry) => entry.candidate);
}
