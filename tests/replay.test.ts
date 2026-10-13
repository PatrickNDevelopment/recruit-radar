import { describe, expect, it } from 'vitest';
import { analyze } from '../src/engine';
import { DAY, makeInput, post, rolesOf, shift, snap, company } from './helpers';

const T1 = '2026-09-01T08:00:00Z';
const T2 = '2026-09-15T08:00:00Z';
const T3 = '2026-10-01T08:00:00Z';

const simple = (events: ReturnType<typeof analyze>['events']) =>
  events.map((e) => [e.at, e.type, e.title, e.fields]);

describe('replay lifecycle', () => {
  it('emits baseline, changed, added, removed and reappeared in processing order', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
          post('Acme', 'Designer', { source_posting_id: '2' }),
        ]),
        snap('s2', 'greenhouse', 'acme', T2, 'full', [
          post('Acme', 'Senior Engineer', { source_posting_id: '1' }),
          post('Acme', 'Analyst', { source_posting_id: '3' }),
        ]),
        snap('s3', 'greenhouse', 'acme', T3, 'full', [
          post('Acme', 'Designer', { source_posting_id: '2' }),
          post('Acme', 'Senior Engineer', { source_posting_id: '1' }),
          post('Acme', 'Analyst', { source_posting_id: '3' }),
        ]),
      ]),
    );
    expect(simple(analysis.events)).toEqual([
      [T1, 'baseline', 'Engineer', null],
      [T1, 'baseline', 'Designer', null],
      [T2, 'changed', 'Senior Engineer', ['title']], // new title
      [T2, 'added', 'Analyst', null],
      [T2, 'removed', 'Designer', null], // removals come after step 2
      [T3, 'reappeared', 'Designer', null],
    ]);
    // Both the baseline and the rename of posting 1 belong to the same canonical role.
    const [baseline, , changed] = analysis.events;
    expect(changed?.role_id).toBe(baseline?.role_id);
  });

  it('tracks first_seen, last_seen and removed_at on roles', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
          post('Acme', 'Designer', { source_posting_id: '2' }),
        ]),
        snap('s2', 'greenhouse', 'acme', T2, 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
        ]),
      ]),
    );
    const roles = rolesOf(analysis, company(analysis, 'Acme'));
    const designer = roles.find((r) => r.title === 'Designer');
    const engineer = roles.find((r) => r.title === 'Engineer');
    expect(designer).toMatchObject({
      status: 'removed',
      first_seen: T1,
      last_seen: T1,
      removed_at: T2,
    });
    expect(engineer).toMatchObject({
      status: 'active',
      first_seen: T1,
      last_seen: T2,
      removed_at: null,
    });
  });

  it('clears removed_at when a role reappears and keeps first_seen', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
        ]),
        snap('s2', 'greenhouse', 'acme', T2, 'full', []),
        snap('s3', 'greenhouse', 'acme', T3, 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
        ]),
      ]),
    );
    const [role] = analysis.roles;
    expect(role).toMatchObject({
      status: 'active',
      first_seen: T1,
      last_seen: T3,
      removed_at: null,
    });
    expect(analysis.events.map((e) => e.type)).toEqual(['baseline', 'removed', 'reappeared']);
  });

  it('never removes on an additive snapshot', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'csv', 'leads', T1, 'additive', [
          post('Acme', 'Engineer', { source_posting_id: 'a' }),
          post('Acme', 'Designer', { source_posting_id: 'b' }),
        ]),
        snap('s2', 'csv', 'leads', T2, 'additive', [
          post('Acme', 'Engineer', { source_posting_id: 'a' }),
        ]),
      ]),
    );
    expect(analysis.events.map((e) => e.type)).toEqual(['baseline', 'baseline']);
    expect(rolesOf(analysis, company(analysis, 'Acme')).every((r) => r.status === 'active')).toBe(
      true,
    );
  });

  it('lets an additive import bring a removed role back', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
        ]),
        snap('s2', 'greenhouse', 'acme', T2, 'full', []),
        snap('s3', 'greenhouse', 'acme', T3, 'additive', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
        ]),
      ]),
    );
    expect(analysis.events.map((e) => e.type)).toEqual(['baseline', 'removed', 'reappeared']);
  });

  it('treats the first processed snapshot of each source as its baseline, even if additive', () => {
    const analysis = analyze(
      makeInput([
        snap('g1', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
        ]),
        snap('c1', 'csv', 'leads', T2, 'additive', [post('Acme', 'Analyst')]),
        snap('c2', 'csv', 'leads', T3, 'additive', [post('Acme', 'Analyst'), post('Acme', 'Ops')]),
      ]),
    );
    expect(simple(analysis.events)).toEqual([
      [T1, 'baseline', 'Engineer', null],
      [T2, 'baseline', 'Analyst', null],
      [T3, 'added', 'Ops', null],
    ]);
  });
});

describe('replay ordering', () => {
  it('lets the last duplicate in a snapshot win and orders by last occurrence', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'A first', { source_posting_id: '1' }),
          post('Acme', 'B', { source_posting_id: '2' }),
          post('Acme', 'A last', { source_posting_id: '1' }),
        ]),
      ]),
    );
    expect(simple(analysis.events)).toEqual([
      [T1, 'baseline', 'B', null],
      [T1, 'baseline', 'A last', null],
    ]);
    expect(analysis.stats.postings_observed).toBe(3);
    expect(analysis.roles).toHaveLength(2);
  });

  it('removes in ascending source-role-key order (id-keyed before k-keyed)', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Role without id'),
          post('Acme', 'Charlie', { source_posting_id: 'c' }),
          post('Acme', 'Alpha', { source_posting_id: 'a' }),
          post('Acme', 'Bravo', { source_posting_id: 'b' }),
        ]),
        snap('s2', 'greenhouse', 'acme', T2, 'full', []),
      ]),
    );
    const removed = analysis.events.filter((e) => e.type === 'removed').map((e) => e.title);
    expect(removed).toEqual(['Alpha', 'Bravo', 'Charlie', 'Role without id']);
  });

  it('orders snapshots by (observed_at, snapshot_id) whatever the input order', () => {
    const snapshots = [
      snap('late', 'greenhouse', 'acme', T3, 'full', [
        post('Acme', 'Engineer', { source_posting_id: '1' }),
      ]),
      snap('early', 'greenhouse', 'acme', T1, 'full', []),
      snap('mid', 'greenhouse', 'acme', T2, 'full', [
        post('Acme', 'Engineer', { source_posting_id: '1' }),
      ]),
    ];
    const forward = analyze(makeInput(snapshots));
    const reversed = analyze(makeInput([...snapshots].reverse()));
    expect(reversed).toEqual(forward);
    // `early` is the source's baseline snapshot (empty), so the role first appears as `added`.
    expect(forward.events.map((e) => [e.at, e.type])).toEqual([[T2, 'added']]);
  });

  it('breaks observed_at ties by snapshot_id (code-point order)', () => {
    const analysis = analyze(
      makeInput([
        snap('b', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'Second', { source_posting_id: '2' }),
        ]),
        snap('a', 'greenhouse', 'acme', T1, 'full', [
          post('Acme', 'First', { source_posting_id: '1' }),
        ]),
      ]),
    );
    // `a` is the baseline; `b` (same instant) removes role 1 and adds role 2.
    expect(simple(analysis.events)).toEqual([
      [T1, 'baseline', 'First', null],
      [T1, 'added', 'Second', null],
      [T1, 'removed', 'First', null],
    ]);
  });

  it('ignores snapshots observed after as_of entirely', () => {
    const base = [
      snap('s1', 'greenhouse', 'acme', T1, 'full', [
        post('Acme', 'Engineer', { source_posting_id: '1' }),
      ]),
    ];
    const withFuture = [
      ...base,
      snap('s2', 'greenhouse', 'acme', '2026-10-13T12:00:01Z', 'full', []),
      snap('s3', 'lever', 'zeta', '2027-01-01T00:00:00Z', 'full', [post('Zeta', 'Ops')]),
    ];
    const a = analyze(makeInput(base));
    const b = analyze(makeInput(withFuture));
    expect(b).toEqual(a);
    expect(b.stats.snapshots).toBe(1);
    expect(b.companies.map((c) => c.name)).toEqual(['Acme']);
  });

  it('includes a snapshot observed exactly at as_of', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'greenhouse', 'acme', '2026-10-13T12:00:00Z', 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
        ]),
      ]),
    );
    expect(analysis.stats.snapshots).toBe(1);
  });
});

describe('changed events', () => {
  it('lists differing tracked fields sorted by name', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'lever', 'acme', T1, 'full', [
          post('Acme', 'Engineer', {
            source_posting_id: 'x',
            location: 'Berlin',
            department: 'Eng',
            url: 'https://jobs.example/1',
            work_mode: 'onsite',
            posted_at: '2026-08-01',
          }),
        ]),
        snap('s2', 'lever', 'acme', T2, 'full', [
          post('Acme', 'Staff Engineer', {
            source_posting_id: 'x',
            location: 'Remote',
            department: 'Platform',
            url: 'https://jobs.example/2',
            work_mode: 'remote',
            posted_at: '2026-08-02',
          }),
        ]),
      ]),
    );
    const changed = analysis.events.find((e) => e.type === 'changed');
    expect(changed?.fields).toEqual([
      'department',
      'location',
      'posted_at',
      'title',
      'url',
      'work_mode',
    ]);
    expect(changed?.title).toBe('Staff Engineer');
  });

  it('treats null and null as equal and emits nothing for an identical re-listing', () => {
    const same = post('Acme', 'Engineer', { source_posting_id: '1' });
    const analysis = analyze(
      makeInput([
        snap('s1', 'lever', 'acme', T1, 'full', [same]),
        snap('s2', 'lever', 'acme', T2, 'full', [same]),
      ]),
    );
    expect(analysis.events.map((e) => e.type)).toEqual(['baseline']);
    // last_seen still advances.
    expect(analysis.roles[0]?.last_seen).toBe(T2);
  });

  it('does not report a company-name respelling that keeps the company key', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'lever', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
        ]),
        snap('s2', 'lever', 'acme', T2, 'full', [
          post('ACME Inc.', 'Engineer', { source_posting_id: '1' }),
        ]),
      ]),
    );
    expect(analysis.events.map((e) => e.type)).toEqual(['baseline']);
    expect(analysis.companies).toHaveLength(1);
    expect(analysis.companies[0]?.aliases).toEqual(['ACME Inc.', 'Acme']);
    expect(analysis.companies[0]?.name).toBe('Acme'); // earliest observed posting
  });

  it('reports a title change that keeps the title_key on a role without an id', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'csv', 'leads', T1, 'additive', [
          post('Acme', 'Engineer (Remote)', { location: 'New York, NY' }),
        ]),
        snap('s2', 'csv', 'leads', T2, 'additive', [
          post('Acme', 'Engineer', { location: 'NY - New York' }),
        ]),
      ]),
    );
    const changed = analysis.events.filter((e) => e.type === 'changed');
    expect(changed).toHaveLength(1);
    expect(changed[0]?.fields).toEqual(['location', 'title']);
    expect(analysis.roles).toHaveLength(1);
  });

  it('turns a rename on a role without an id into removed + added when the key changes', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'lever', 'acme', T1, 'full', [post('Acme', 'Engineer')]),
        snap('s2', 'lever', 'acme', T2, 'full', [post('Acme', 'Senior Engineer')]),
      ]),
    );
    expect(simple(analysis.events)).toEqual([
      [T1, 'baseline', 'Engineer', null],
      [T2, 'added', 'Senior Engineer', null],
      [T2, 'removed', 'Engineer', null],
    ]);
  });

  it('keeps one canonical role across a rename of an id-keyed role, with a new role_id', () => {
    const analysis = analyze(
      makeInput([
        snap('s1', 'lever', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
        ]),
      ]),
    );
    const before = analysis.roles[0]?.role_id;
    const renamed = analyze(
      makeInput([
        snap('s1', 'lever', 'acme', T1, 'full', [
          post('Acme', 'Engineer', { source_posting_id: '1' }),
        ]),
        snap('s2', 'lever', 'acme', T2, 'full', [
          post('Acme', 'Principal Engineer', { source_posting_id: '1' }),
        ]),
      ]),
    );
    expect(renamed.roles).toHaveLength(1);
    expect(renamed.roles[0]?.role_id).not.toBe(before); // identity follows title_key
    expect(renamed.roles[0]?.title).toBe('Principal Engineer');
  });
});

describe('snapshot timing helpers', () => {
  it('shift() is exact', () => {
    expect(shift(T1, DAY)).toBe('2026-09-02T08:00:00Z');
    expect(shift(T1, -1)).toBe('2026-09-01T07:59:59Z');
  });
});
