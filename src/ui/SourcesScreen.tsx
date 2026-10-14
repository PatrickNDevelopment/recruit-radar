import { useEffect, useMemo, useState } from 'react';
import { TOKEN_PATTERN } from '../data/remoteSource';
import { ATS_PROVIDERS, type AtsProvider, type AtsSource, type RefreshRun } from '../data/types';
import { useApp, useWorkspace } from './AppContext';
import { Dialog, Pill, SelectField, TableRegion, TextField } from './components';
import { ERROR_KIND_TEXT, EVENT_LABELS, PROVIDER_LABELS } from './copy';
import { dateTimeOf, EM_DASH } from './format';

/** The backend starts a run's message with the provider host it called ("host: 12 postings…"). */
export function hostFromMessage(message: string): string | null {
  const match = /^([A-Za-z0-9.-]+(?::\d{1,5})?|\[[0-9A-Fa-f:]+\](?::\d{1,5})?): /u.exec(message);
  return match?.[1] ?? null;
}

function LocalExplanation() {
  const { state, store, goto } = useApp();
  const { backend, prefs } = state;
  let backendLine: string;
  switch (backend.state) {
    case 'checking':
      backendLine = 'Looking for a backend…';
      break;
    case 'offline':
      backendLine = `Backend not reachable: ${backend.message}`;
      break;
    case 'ok':
      backendLine =
        `A backend answered at ${prefs.backend_url}, but local-data mode is selected in Settings, ` +
        `so it is not being used.`;
      break;
    case 'unchecked':
      backendLine =
        'No backend has been contacted. A page opened from a public website never looks for a ' +
        'backend on your computer unless you ask it to.';
      break;
  }
  return (
    <div className="screen">
      <div className="screen-head">
        <div>
          <h1 id="screen-title" tabIndex={-1}>
            Sources
          </h1>
          <p>Live refresh of Greenhouse, Lever and Ashby job boards.</p>
        </div>
      </div>
      <section
        className="card stack"
        aria-labelledby="unavailable-title"
        data-testid="sources-local"
      >
        <h2 id="unavailable-title">Live refresh is not available in local-data mode</h2>
        <p>
          Fetching a job board needs a program running on your computer: browsers do not let a web
          page read those public JSON endpoints directly, and the app deliberately never scrapes
          HTML. The local backend does the read-only requests (one at a time, no logins) and keeps
          the history.
        </p>
        <p data-testid="backend-state">
          <strong>Backend status:</strong> {backendLine}
        </p>
        <div>
          <h3>To use live refresh</h3>
          <ol>
            <li>
              Start the local backend from this repository (its README has the exact command). By
              default it listens on <code>http://127.0.0.1:8787</code>.
            </li>
            <li>
              If this page is not served from your computer, open Settings and choose connected
              mode; the backend must list this page's origin in{' '}
              <code>RECRUIT_RADAR_CORS_ORIGINS</code>.
            </li>
            <li>Come back here and press “Check for the backend”.</li>
          </ol>
        </div>
        <div className="row">
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => void store.recheckBackend()}
          >
            Check for the backend
          </button>
          <button type="button" className="btn" onClick={() => goto('settings')}>
            Open Settings
          </button>
        </div>
        <p className="small muted">
          Meanwhile everything else works: import CSV exports of job postings on the Data tab.
        </p>
      </section>
    </div>
  );
}

function RunStatus({ run }: { run: RefreshRun }) {
  return run.status === 'ok' ? <Pill tone="ok">Succeeded</Pill> : <Pill tone="bad">Failed</Pill>;
}

function errorText(run: RefreshRun): string {
  if (run.error_kind === null) return EM_DASH;
  const base = ERROR_KIND_TEXT[run.error_kind] ?? run.error_kind;
  const extra =
    run.error_kind === 'rate_limited' && run.retry_after_s !== null
      ? ` Retry after ${run.retry_after_s} s.`
      : '';
  return `${base}${extra}`;
}

function ConnectedSources() {
  const { state, store } = useApp();
  const workspace = useWorkspace();
  const busy = state.pending > 0;

  const [sources, setSources] = useState<AtsSource[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // History is keyed by the source it belongs to, so switching sources never shows the previous
  // source's runs under the new heading while the new ones load.
  const [runsState, setRunsState] = useState<{
    id: string;
    runs: RefreshRun[] | null;
    error: string | null;
  } | null>(null);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [removing, setRemoving] = useState<AtsSource | null>(null);
  const [version, setVersion] = useState(0);

  const [provider, setProvider] = useState<AtsProvider>('greenhouse');
  const [token, setToken] = useState('');
  const [company, setCompany] = useState('');
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [companyError, setCompanyError] = useState<string | null>(null);

  const asOf = workspace.analysis.as_of;

  useEffect(() => {
    let cancelled = false;
    void store.listAtsSources().then((result) => {
      if (cancelled) return;
      if (result.ok) {
        setSources(result.value);
        setListError(null);
      } else {
        setListError(result.message);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [store, version, asOf]);

  const selected = useMemo(
    () => sources?.find((source) => source.id === selectedId) ?? sources?.[0] ?? null,
    [sources, selectedId],
  );
  const selectedKey = selected?.id ?? null;

  useEffect(() => {
    if (selectedKey === null) return;
    let cancelled = false;
    void store.listRuns(selectedKey).then((result) => {
      if (cancelled) return;
      setRunsState(
        result.ok
          ? { id: selectedKey, runs: result.value, error: null }
          : { id: selectedKey, runs: null, error: result.message },
      );
    });
    return () => {
      cancelled = true;
    };
  }, [store, selectedKey, version, asOf]);

  const current = runsState !== null && runsState.id === selectedKey ? runsState : null;
  const runs = current?.runs ?? null;
  const runsError = current?.error ?? null;
  const lastOk = runs?.find((run) => run.status === 'ok') ?? null;
  // Baseline events can only belong to a source's FIRST successful run. Matching events to a run
  // by timestamp alone would otherwise attribute them to a later run that finished in the same
  // second (possible when the refresh interval is configured to 0).
  const onlyOneOkRun = runs !== null && runs.filter((run) => run.status === 'ok').length === 1;
  const runEvents = useMemo(() => {
    if (selected === null || lastOk === null) return [];
    return workspace.analysis.events.filter(
      (event) =>
        event.source_kind === selected.provider &&
        event.source_ref === selected.token &&
        event.at === lastOk.finished_at &&
        (event.type !== 'baseline' || onlyOneOkRun),
    );
  }, [workspace.analysis.events, selected, lastOk, onlyOneOkRun]);

  const add = async () => {
    let valid = true;
    if (!TOKEN_PATTERN.test(token)) {
      setTokenError(
        'Use 1 to 100 letters, digits, dots, underscores or hyphens (the board token from the careers page address).',
      );
      valid = false;
    } else {
      setTokenError(null);
    }
    if (company.trim() === '') {
      setCompanyError('Enter the company name to show for this board.');
      valid = false;
    } else {
      setCompanyError(null);
    }
    if (!valid) return;
    const result = await store.addAtsSource({ provider, token, company_name: company.trim() });
    if (result.ok) {
      setToken('');
      setCompany('');
      setSelectedId(result.value.id);
      setVersion((v) => v + 1);
    }
  };

  const refresh = async (source: AtsSource) => {
    setRefreshingId(source.id);
    setSelectedId(source.id);
    await store.refreshAtsSource(source);
    setRefreshingId(null);
    setVersion((v) => v + 1);
  };

  return (
    <div className="screen">
      <div className="screen-head">
        <div>
          <h1 id="screen-title" tabIndex={-1}>
            Sources
          </h1>
          <p>
            Read-only boards fetched by the local backend at {state.prefs.backend_url}. One request
            per page, no parallel requests, no logins, no HTML.
          </p>
        </div>
        <button type="button" className="btn btn--small" onClick={() => setVersion((v) => v + 1)}>
          Reload list
        </button>
      </div>

      <section className="card stack" aria-labelledby="add-source-title">
        <h2 id="add-source-title">Add a source</h2>
        <form
          className="stack"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void add();
          }}
        >
          <div className="form-grid">
            <SelectField
              label="Provider"
              value={provider}
              onChange={(value) => setProvider(value as AtsProvider)}
              options={ATS_PROVIDERS.map((id) => ({ value: id, label: PROVIDER_LABELS[id] }))}
            />
            <TextField
              label="Board token"
              required
              value={token}
              onChange={setToken}
              error={tokenError}
              hint="For example the last part of boards.greenhouse.io/<token>. Never a full URL."
            />
            <TextField
              label="Company name"
              required
              value={company}
              onChange={setCompany}
              error={companyError}
              hint="Shown for every posting of this board (the provider's own name is not trusted)."
            />
          </div>
          <div>
            <button type="submit" className="btn btn--primary" disabled={busy}>
              Add source
            </button>
          </div>
        </form>
      </section>

      <section className="card stack" aria-labelledby="sources-title">
        <h2 id="sources-title">Your sources</h2>
        {listError !== null ? (
          <p className="error-summary" role="alert">
            The source list could not be loaded: {listError}
          </p>
        ) : sources === null ? (
          <p role="status">Loading sources…</p>
        ) : sources.length === 0 ? (
          <p data-testid="no-sources">
            No sources yet. Add a board above, then press Refresh to fetch it.
          </p>
        ) : (
          <TableRegion label="Sources">
            <table className="data-table" style={{ minWidth: '48rem' }}>
              <thead>
                <tr>
                  <th scope="col" className="sticky-col">
                    Company
                  </th>
                  <th scope="col">Provider</th>
                  <th scope="col">Board token</th>
                  <th scope="col">Last refresh</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((source) => (
                  <tr key={source.id} data-testid="source-row">
                    <th scope="row" className="sticky-col">
                      {source.company_name}
                    </th>
                    <td>{PROVIDER_LABELS[source.provider]}</td>
                    <td>
                      <code>{source.token}</code>
                    </td>
                    <td>
                      {source.last_run === null ? (
                        <span className="muted">Never refreshed</span>
                      ) : (
                        <>
                          <RunStatus run={source.last_run} />{' '}
                          {dateTimeOf(source.last_run.finished_at)}
                        </>
                      )}
                    </td>
                    <td>
                      <div className="row">
                        <button
                          type="button"
                          className="btn btn--small btn--primary"
                          disabled={busy || refreshingId !== null}
                          onClick={() => void refresh(source)}
                        >
                          {refreshingId === source.id ? 'Refreshing…' : 'Refresh'}
                          <span className="sr-only"> {source.company_name}</span>
                        </button>
                        <button
                          type="button"
                          className="btn btn--small"
                          aria-pressed={selected?.id === source.id}
                          onClick={() => setSelectedId(source.id)}
                        >
                          History
                          <span className="sr-only"> of {source.company_name}</span>
                        </button>
                        <button
                          type="button"
                          className="btn btn--small"
                          disabled={busy}
                          onClick={() => setRemoving(source)}
                        >
                          Remove
                          <span className="sr-only"> {source.company_name}</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableRegion>
        )}
      </section>

      {selected === null ? null : (
        <section
          className="card stack"
          aria-labelledby="history-title"
          data-testid="refresh-history"
        >
          <h2 id="history-title">Refresh history: {selected.company_name}</h2>
          <p className="small muted">
            Newest first. A failed run keeps everything already stored: it records no snapshot and
            removes no role.
          </p>
          {runsError !== null ? (
            <p className="error-summary" role="alert">
              The history could not be loaded: {runsError}
            </p>
          ) : runs === null ? (
            <p role="status">Loading history…</p>
          ) : runs.length === 0 ? (
            <p>This source has not been refreshed yet.</p>
          ) : (
            <TableRegion label="Refresh history">
              <table className="data-table" style={{ minWidth: '64rem' }}>
                <thead>
                  <tr>
                    <th scope="col">Started</th>
                    <th scope="col">Status</th>
                    <th scope="col">Error</th>
                    <th scope="col">Provider host</th>
                    <th scope="col" className="num">
                      Seen
                    </th>
                    <th scope="col" className="num">
                      Added
                    </th>
                    <th scope="col" className="num">
                      Changed
                    </th>
                    <th scope="col" className="num">
                      Removed
                    </th>
                    <th scope="col" className="num">
                      Listed again
                    </th>
                    <th scope="col" className="num">
                      Unchanged
                    </th>
                    <th scope="col">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.id} data-testid="run-row">
                      <td className="nowrap">{dateTimeOf(run.started_at)}</td>
                      <td>
                        <RunStatus run={run} />
                      </td>
                      <td>
                        {errorText(run)}
                        {run.http_status === null ? null : (
                          <div className="small muted">HTTP {run.http_status}</div>
                        )}
                      </td>
                      <td>{hostFromMessage(run.message) ?? EM_DASH}</td>
                      <td className="num">{run.items_seen}</td>
                      <td className="num">{run.added}</td>
                      <td className="num">{run.changed}</td>
                      <td className="num">{run.removed}</td>
                      <td className="num">{run.reappeared}</td>
                      <td className="num">{run.unchanged}</td>
                      <td className="small">{run.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableRegion>
          )}

          <h3>Role changes in the last successful run</h3>
          {lastOk === null ? (
            <p className="muted">No successful run yet, so there is nothing to compare.</p>
          ) : runEvents.length === 0 ? (
            <p className="muted" data-testid="no-run-events">
              The run at {dateTimeOf(lastOk.finished_at)} recorded no role events (nothing was
              added, changed or removed).
            </p>
          ) : (
            <ul className="event-list" data-testid="run-events">
              {[...runEvents]
                .sort(
                  (a, b) =>
                    ['changed', 'removed', 'added', 'reappeared', 'baseline'].indexOf(a.type) -
                      ['changed', 'removed', 'added', 'reappeared', 'baseline'].indexOf(b.type) ||
                    a.title.localeCompare(b.title),
                )
                .map((event, index) => (
                  <li key={`${event.role_id}-${event.type}-${index}`}>
                    <strong>{EVENT_LABELS[event.type]}</strong>: {event.title}
                    {event.fields === null || event.fields.length === 0 ? null : (
                      <> (changed: {event.fields.join(', ')})</>
                    )}{' '}
                    <span className="small muted">· {dateTimeOf(event.at)}</span>
                  </li>
                ))}
            </ul>
          )}
        </section>
      )}

      <Dialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title="Remove this source?"
      >
        <p>
          This removes {removing?.company_name} with its refresh history and every snapshot stored
          for it in the backend. Scores are recalculated without it.
        </p>
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={() => setRemoving(null)}>
            Keep it
          </button>
          <button
            type="button"
            className="btn btn--danger"
            onClick={() => {
              const target = removing;
              setRemoving(null);
              if (target === null) return;
              void store.removeAtsSource(target).then(() => {
                setSelectedId(null);
                setVersion((v) => v + 1);
              });
            }}
          >
            Remove source
          </button>
        </div>
      </Dialog>
    </div>
  );
}

export function SourcesScreen() {
  const workspace = useWorkspace();
  return workspace.mode === 'connected' ? <ConnectedSources /> : <LocalExplanation />;
}
