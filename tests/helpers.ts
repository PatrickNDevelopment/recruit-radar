import type {
  Analysis,
  AnalyzeInput,
  CompanyAnalysis,
  PostingInput,
  RoleAnalysis,
  ScoreComponent,
  SnapshotInput,
  SnapshotMode,
  SourceKind,
} from '../src/engine';

export const AS_OF = '2026-10-13T12:00:00Z';

/** Test-side timestamp arithmetic (the engine itself never uses `Date`). */
export function shift(timestamp: string, seconds: number): string {
  const ms = Date.parse(timestamp) + seconds * 1000;
  return new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export const DAY = 86400;

export function post(
  company_name: string,
  title: string,
  extra: Partial<PostingInput> = {},
): PostingInput {
  return { company_name, title, ...extra };
}

export function snap(
  snapshot_id: string,
  source_kind: SourceKind,
  source_ref: string,
  observed_at: string,
  mode: SnapshotMode,
  postings: PostingInput[],
): SnapshotInput {
  return { snapshot_id, source_kind, source_ref, observed_at, mode, postings };
}

export function makeInput(
  snapshots: SnapshotInput[],
  extra: Partial<AnalyzeInput> = {},
): AnalyzeInput {
  return { as_of: AS_OF, snapshots, ...extra };
}

export function company(analysis: Analysis, name: string): CompanyAnalysis {
  const found = analysis.companies.find((c) => c.name === name);
  if (found === undefined) {
    throw new Error(
      `no company named ${name}; have ${analysis.companies.map((c) => c.name).join(', ')}`,
    );
  }
  return found;
}

export function component<K extends ScoreComponent['key']>(
  c: CompanyAnalysis,
  key: K,
): Extract<ScoreComponent, { key: K }> {
  const found = c.components.find((x) => x.key === key);
  if (found === undefined) throw new Error(`no component ${key}`);
  return found as Extract<ScoreComponent, { key: K }>;
}

export function rolesOf(analysis: Analysis, c: CompanyAnalysis): RoleAnalysis[] {
  return analysis.roles.filter((r) => r.company_id === c.company_id);
}

/** A small seedable PRNG (mulberry32) so randomized suites are reproducible. */
export function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
