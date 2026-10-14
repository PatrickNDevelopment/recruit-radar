import { useMemo, useState } from 'react';
import { MAX_NOTE_LENGTH } from '../data/localSource';
import { sampleDatasetIds } from './viewModel';
import { useApp, useWorkspace } from './AppContext';
import { DataLink, Dialog, Pill, ScoreRing, TableRegion, TextAreaField } from './components';
import { COPY, EVENT_LABELS, MERGE_REASON_TEXT, WORK_MODE_LABELS } from './copy';
import { agoText, dateOf, dateTimeOf, EM_DASH, plural, scoreText } from './format';
import { ScoreBreakdown } from './ScoreBreakdown';
import { buildCompanyDetail, type CompanyDetail } from './viewModel';

function NoteEditor({ detail }: { detail: CompanyDetail }) {
  const { state, store } = useApp();
  const saved = detail.shortlist?.note ?? '';
  const [text, setText] = useState(saved);
  const shortlisted = detail.shortlist !== null;
  const tooLong = text.length > MAX_NOTE_LENGTH;
  const dirty = text !== saved;
  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        if (tooLong) return;
        void store.setShortlisted(detail.company.company_id, true, text);
      }}
    >
      <TextAreaField
        label="Qualification note"
        value={text}
        onChange={setText}
        rows={4}
        error={tooLong ? `A note can hold at most ${MAX_NOTE_LENGTH} characters.` : null}
        hint={
          shortlisted
            ? `Kept with this shortlist entry, in this ${state.mode === 'local' ? 'browser' : 'backend'} only. ${text.length} of ${MAX_NOTE_LENGTH} characters.`
            : `Notes are kept with shortlist entries, so saving one also adds this company to the shortlist. ${text.length} of ${MAX_NOTE_LENGTH} characters.`
        }
      />
      <div>
        <button
          type="submit"
          className="btn"
          disabled={state.pending > 0 || tooLong || (shortlisted && !dirty)}
        >
          {shortlisted ? 'Save note' : 'Save note and add to shortlist'}
        </button>
      </div>
    </form>
  );
}

export function CompanyScreen({ companyId }: { companyId: string }) {
  const { state, store, closeCompany, goto } = useApp();
  const workspace = useWorkspace();
  const sampleIds = useMemo(() => sampleDatasetIds(workspace.datasets), [workspace.datasets]);
  const detail = useMemo(
    () => buildCompanyDetail(workspace, companyId, sampleIds),
    [workspace, companyId, sampleIds],
  );
  const [confirmRemove, setConfirmRemove] = useState(false);

  if (detail === null) {
    return (
      <div className="screen">
        <div className="card stack" data-testid="company-missing">
          <h1 id="screen-title" tabIndex={-1}>
            Company not found
          </h1>
          <p>
            This company is no longer in the loaded data. It may have been merged into another
            company, or its dataset was removed.
          </p>
          <div>
            <button type="button" className="btn btn--primary" onClick={closeCompany}>
              Back to the radar
            </button>
          </div>
        </div>
      </div>
    );
  }

  const { company } = detail;
  const scoredCount = workspace.analysis.companies.filter((c) => c.score !== null).length;
  const note = detail.shortlist?.note ?? '';
  const asOf = workspace.analysis.as_of;

  return (
    <div className="screen">
      <div>
        <button type="button" className="btn btn--small" onClick={closeCompany}>
          <span aria-hidden="true">← </span>Back to the radar
        </button>
      </div>

      <section className="card" aria-labelledby="screen-title">
        <div className="score-hero">
          <ScoreRing score={company.score} coverage={company.coverage} />
          <div className="score-hero-body stack">
            <div>
              <h1 id="screen-title" tabIndex={-1}>
                {company.name}
              </h1>
              {company.aliases.length > 1 ? (
                <p className="muted small">Also seen as: {company.aliases.join('; ')}</p>
              ) : null}
            </div>
            <dl className="stat-row">
              <div className="stat">
                <dt>Priority score</dt>
                <dd data-testid="company-score">{scoreText(company.score)}</dd>
              </div>
              <div className="stat">
                <dt>Coverage</dt>
                <dd>{company.coverage}%</dd>
              </div>
              <div className="stat">
                <dt>Rank</dt>
                <dd>
                  {company.rank === null ? EM_DASH : `#${company.rank}`}{' '}
                  <span className="small muted">of {scoredCount} scored</span>
                </dd>
              </div>
              <div className="stat">
                <dt>Active roles</dt>
                <dd>
                  {company.active_roles}{' '}
                  <span className="small muted">
                    {company.relevant_roles === null
                      ? 'relevance not measured'
                      : `${company.relevant_roles} relevant`}
                  </span>
                </dd>
              </div>
              <div className="stat">
                <dt>Last seen</dt>
                <dd className="small">
                  {dateOf(company.last_seen)}
                  {company.last_seen === null ? '' : ` (${agoText(detail.signalAgeDays)})`}
                </dd>
              </div>
            </dl>
            <p className="score-caption" data-testid="score-caption">
              {COPY.scoreCaption}
            </p>
          </div>
        </div>
      </section>

      <section className="card stack" aria-labelledby="shortlist-title">
        <h2 id="shortlist-title">Shortlist and note</h2>
        <div className="row">
          <button
            type="button"
            className="btn"
            aria-pressed={detail.shortlist !== null}
            disabled={state.pending > 0}
            onClick={() => {
              if (detail.shortlist !== null && note.trim() !== '') {
                setConfirmRemove(true);
                return;
              }
              void store.setShortlisted(company.company_id, detail.shortlist === null);
            }}
          >
            <span aria-hidden="true">{detail.shortlist === null ? '' : '✓ '}</span>
            {detail.shortlist === null ? 'Add to shortlist' : 'On the shortlist'}
          </button>
          {detail.shortlist === null ? null : (
            <span className="small muted">Added {dateOf(detail.shortlist.added_at)}</span>
          )}
        </div>
        <NoteEditor
          key={`${company.company_id}:${detail.shortlist?.note ?? ''}:${detail.shortlist === null}`}
          detail={detail}
        />
      </section>

      <ScoreBreakdown company={company} views={detail.components} />

      <section className="card stack" aria-labelledby="roles-title">
        <h2 id="roles-title">Roles</h2>
        {detail.roles.length === 0 ? (
          <p>No roles have been observed for this company.</p>
        ) : (
          <TableRegion label="Roles of this company">
            <table className="data-table" style={{ minWidth: '60rem' }}>
              <thead>
                <tr>
                  <th scope="col" className="sticky-col">
                    Title
                  </th>
                  <th scope="col">Status</th>
                  <th scope="col">Work mode</th>
                  <th scope="col">Location</th>
                  <th scope="col">Department</th>
                  <th scope="col">First seen</th>
                  <th scope="col">Last seen</th>
                  <th scope="col">Listed for</th>
                  <th scope="col">Matches keywords</th>
                  <th scope="col">Sources</th>
                </tr>
              </thead>
              <tbody>
                {detail.roles.map(({ role, sources }) => (
                  <tr key={role.role_id} data-testid="role-row">
                    <th scope="row" className="sticky-col">
                      {role.title}
                    </th>
                    <td>
                      <Pill tone={role.status === 'active' ? 'live' : undefined}>
                        {role.status === 'active' ? 'Active' : 'No longer listed'}
                      </Pill>
                      {role.removed_at === null ? null : (
                        <div className="small muted">since {dateOf(role.removed_at)}</div>
                      )}
                    </td>
                    <td>{WORK_MODE_LABELS[role.work_mode]}</td>
                    <td>{role.location ?? EM_DASH}</td>
                    <td>{role.department ?? EM_DASH}</td>
                    <td className="nowrap">{dateOf(role.first_seen)}</td>
                    <td className="nowrap">{dateOf(role.last_seen)}</td>
                    <td>
                      {plural(role.age_days, 'day')}
                      <div className="small muted">
                        {role.posted_at === null
                          ? 'since first seen'
                          : `since posted ${role.posted_at}`}
                      </div>
                    </td>
                    <td>
                      {role.relevant === null ? 'Not measured' : role.relevant ? 'Yes' : 'No'}
                    </td>
                    <td>
                      <ul className="plain-list">
                        {sources.map((source, index) => (
                          <li key={`${source.label}-${index}`}>
                            {source.url === null ? (
                              source.label
                            ) : (
                              <DataLink url={source.url} label={source.label} />
                            )}
                            {source.status === 'removed' ? (
                              <span className="small muted"> (no longer listed)</span>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableRegion>
        )}
      </section>

      <section className="card stack" aria-labelledby="history-title">
        <h2 id="history-title">Role history</h2>
        {detail.events.length === 0 ? (
          <p>No role events have been recorded.</p>
        ) : (
          <>
            <p className="muted small">
              Newest first. “First observed” is the first time a source listed the role; later
              events need a later snapshot to compare with.
            </p>
            <ul className="event-list" data-testid="events">
              {detail.events.map((event, index) => (
                <li key={`${event.at}-${event.role_id}-${event.type}-${index}`}>
                  <span className="when">{dateTimeOf(event.at)}</span>{' '}
                  <strong>{EVENT_LABELS[event.type]}</strong>: {event.title}
                  {event.fields === null || event.fields.length === 0 ? null : (
                    <> (changed: {event.fields.join(', ')})</>
                  )}{' '}
                  <span className="small muted">
                    ·{' '}
                    {event.source_kind === 'manual'
                      ? 'manual entry'
                      : `${event.source_kind} · ${event.source_ref}`}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="card stack" aria-labelledby="provenance-title">
        <h2 id="provenance-title">Evidence provenance</h2>
        <p className="muted small">
          Every posting behind this company's numbers: where it came from and when it was observed.
          The score is only as good as these sources.
        </p>
        <TableRegion label="Evidence provenance">
          <table className="data-table" style={{ minWidth: '56rem' }}>
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">Posting ID</th>
                <th scope="col">Role</th>
                <th scope="col">Status</th>
                <th scope="col">First observed</th>
                <th scope="col">Last observed</th>
                <th scope="col">URL</th>
              </tr>
            </thead>
            <tbody>
              {detail.provenance.map((row) => (
                <tr key={row.key} data-testid="provenance-row">
                  <td>
                    {row.sourceLabel}
                    {row.synthetic ? (
                      <>
                        {' '}
                        <Pill tone="sample">sample</Pill>
                      </>
                    ) : null}
                  </td>
                  <td>{row.postingId ?? <span className="muted">none</span>}</td>
                  <td>{row.roleTitle}</td>
                  <td>{row.status === 'active' ? 'Active' : 'No longer listed'}</td>
                  <td className="nowrap">{dateTimeOf(row.firstObserved)}</td>
                  <td className="nowrap">{dateTimeOf(row.lastObserved)}</td>
                  <td>
                    <DataLink url={row.url} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableRegion>
        <p className="small muted">Analysis time: {dateTimeOf(asOf)}.</p>
      </section>

      {detail.candidates.length === 0 ? null : (
        <section className="card stack" aria-labelledby="dupes-title">
          <h2 id="dupes-title">Possible duplicates of this company</h2>
          <p className="muted small">
            These names look similar. Nothing is merged until you decide.
          </p>
          <ul>
            {detail.candidates.map((candidate) => (
              <li key={candidate.candidate_id}>
                “{candidate.a_name}” and “{candidate.b_name}”: {MERGE_REASON_TEXT[candidate.reason]}
              </li>
            ))}
          </ul>
          <div>
            <button type="button" className="btn btn--small" onClick={() => goto('data')}>
              Review on the Data tab
            </button>
          </div>
        </section>
      )}

      <Dialog
        open={confirmRemove}
        onClose={() => setConfirmRemove(false)}
        title="Remove from the shortlist?"
      >
        <p>Removing {company.name} from the shortlist also deletes its qualification note.</p>
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={() => setConfirmRemove(false)}>
            Keep it
          </button>
          <button
            type="button"
            className="btn btn--danger"
            onClick={() => {
              setConfirmRemove(false);
              void store.setShortlisted(company.company_id, false);
            }}
          >
            Remove and delete note
          </button>
        </div>
      </Dialog>
    </div>
  );
}
