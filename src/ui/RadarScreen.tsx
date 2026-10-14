import { useMemo, useState } from 'react';
import type { RadarFilters, RadarSortKey, SavedView } from '../data/types';
import { DEFAULT_FILTERS } from '../data/types';
import { useApp, useWorkspace } from './AppContext';
import {
  CheckboxField,
  Dialog,
  Pill,
  ScoreMeter,
  SelectField,
  TableRegion,
  TextField,
} from './components';
import { COPY } from './copy';
import { dateOf, EM_DASH, plural, scoreText as formatScore } from './format';
import {
  ariaSortFor,
  datasetTitle,
  filtersAreDefault,
  nextSort,
  radarView,
  reconcileFilters,
  roleMixText,
  signalText,
  SORT_LABELS,
  viewMatches,
  type RadarRow,
} from './viewModel';

const WORK_MODE_OPTIONS = [
  { value: 'any', label: 'Any work mode' },
  { value: 'remote', label: 'Remote' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'onsite', label: 'Onsite' },
  { value: 'unknown', label: 'Unknown' },
];

function SortHeader({
  label,
  sortKey,
  numeric,
  sticky,
}: {
  label: string;
  sortKey: RadarSortKey;
  numeric?: boolean;
  sticky?: boolean;
}) {
  const { radar } = useApp();
  const aria = ariaSortFor(radar.sort, sortKey);
  const arrow = aria === 'ascending' ? '▲' : aria === 'descending' ? '▼' : '↕';
  const classes = [numeric === true ? 'num' : '', sticky === true ? 'sticky-col' : '']
    .filter((name) => name !== '')
    .join(' ');
  return (
    <th scope="col" aria-sort={aria} className={classes === '' ? undefined : classes}>
      <button
        type="button"
        className="sort-button"
        onClick={() => radar.setSort(nextSort(radar.sort, sortKey))}
      >
        {label}
        <span className="arrow" aria-hidden="true">
          {arrow}
        </span>
        <span className="sr-only">
          {aria === 'none'
            ? ', not sorted; activate to sort'
            : aria === 'ascending'
              ? ', sorted ascending; activate to reverse'
              : ', sorted descending; activate to reverse'}
        </span>
      </button>
    </th>
  );
}

function EmptyState() {
  const { state, store, goto } = useApp();
  const workspace = useWorkspace();
  const local = workspace.mode === 'local';
  return (
    <section className="empty-state" aria-labelledby="empty-title" data-testid="empty-state">
      <h2 id="empty-title">No hiring data yet</h2>
      <p>
        The radar shows companies once you give it job-posting data. Everything is computed from
        what you load; nothing is invented.
      </p>
      <ul>
        <li>
          <button type="button" className="link-button" onClick={() => goto('data')}>
            Add a posting by hand or import a CSV file
          </button>{' '}
          on the Data tab.
        </li>
        {local ? (
          <li>
            Live ATS refresh is not available in local-data mode; it needs the local backend (see
            the Sources tab).
          </li>
        ) : (
          <li>
            <button type="button" className="link-button" onClick={() => goto('sources')}>
              Add a Greenhouse, Lever or Ashby board
            </button>{' '}
            on the Sources tab and refresh it.
          </li>
        )}
      </ul>
      {local ? (
        <div className="row">
          <button
            type="button"
            className="btn btn--primary"
            disabled={state.pending > 0}
            onClick={() => void store.loadSample()}
          >
            Load sample data
          </button>
          <span className="small muted">
            Two overlapping synthetic datasets of invented companies, to try the app.
          </span>
        </div>
      ) : null}
    </section>
  );
}

function SavedViews({ resultCount }: { resultCount: number }) {
  const { state, store, radar } = useApp();
  const workspace = useWorkspace();
  const views = state.prefs.saved_views;
  const [selected, setSelected] = useState('');
  const [name, setName] = useState('');
  const active = views.find((view) => viewMatches(view, radar.filters, radar.sort)) ?? null;
  const chosen: SavedView | null = views.find((view) => view.id === selected) ?? null;

  const apply = () => {
    if (chosen === null) return;
    const { filters, dropped } = reconcileFilters(chosen.filters, workspace.datasets);
    radar.setFilters(filters);
    radar.setSort(chosen.sort);
    store.announce(
      dropped.length === 0 ? 'success' : 'info',
      dropped.length === 0
        ? `Applied the saved view "${chosen.name}".`
        : `Applied the saved view "${chosen.name}", except that ${dropped.join(' and ')}.`,
    );
  };

  return (
    <fieldset className="panel">
      <legend>Saved views</legend>
      <p className="small muted">
        A view is a name plus the filters and sort order shown now. Views are stored in this browser
        only.
      </p>
      <div className="form-grid">
        <div className="stack">
          <SelectField
            label="Saved view"
            value={selected}
            onChange={setSelected}
            options={[
              { value: '', label: views.length === 0 ? 'No saved views yet' : 'Choose a view' },
              ...views.map((view) => ({ value: view.id, label: view.name })),
            ]}
            disabled={views.length === 0}
          />
          <div className="row">
            <button
              type="button"
              className="btn btn--small"
              disabled={chosen === null}
              onClick={apply}
            >
              Apply view
            </button>
            <button
              type="button"
              className="btn btn--small"
              disabled={chosen === null}
              onClick={() => {
                if (chosen !== null) {
                  store.deleteView(chosen.id);
                  setSelected('');
                }
              }}
            >
              Delete view
            </button>
          </div>
        </div>
        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            if (store.saveView(name, radar.filters, radar.sort).ok) setName('');
          }}
        >
          <TextField
            label="Name for the current view"
            value={name}
            onChange={setName}
            maxLength={60}
            hint={`Saves the filters and sort shown now (${resultCount} ${resultCount === 1 ? 'company' : 'companies'}). An existing name is updated.`}
          />
          <div>
            <button type="submit" className="btn btn--small">
              Save current view
            </button>
          </div>
        </form>
      </div>
      {active === null ? null : (
        <p className="small" data-testid="active-view">
          Showing the saved view “{active.name}”.
        </p>
      )}
    </fieldset>
  );
}

function formatMinimum(value: number | null): string {
  return value === null ? '' : String(value);
}

function FilterBar() {
  const { radar } = useApp();
  const workspace = useWorkspace();
  const { filters, setFilters } = radar;
  const update = (change: Partial<RadarFilters>) => setFilters({ ...filters, ...change });

  // The number box holds text; the filter holds a number. When the filter changes from outside
  // (a saved view, "Clear filters") the text follows it; typing never gets overwritten.
  const [scoreText, setScoreText] = useState(formatMinimum(filters.min_score));
  const [syncedFrom, setSyncedFrom] = useState(filters.min_score);
  if (syncedFrom !== filters.min_score) {
    setSyncedFrom(filters.min_score);
    setScoreText(formatMinimum(filters.min_score));
  }

  const typed = scoreText.trim();
  const scoreError =
    typed !== '' && (Number.isNaN(Number(typed)) || Number(typed) < 0 || Number(typed) > 100)
      ? 'Enter a number from 0 to 100, or leave it empty.'
      : null;

  return (
    <form
      className="card stack"
      aria-label="Filter companies"
      onSubmit={(event) => event.preventDefault()}
    >
      <div className="form-grid">
        <TextField
          label="Search companies, roles or locations"
          type="search"
          value={filters.text}
          onChange={(text) => update({ text })}
          maxLength={200}
        />
        <SelectField
          label="Work mode"
          value={filters.work_mode}
          onChange={(value) => update({ work_mode: value as RadarFilters['work_mode'] })}
          options={WORK_MODE_OPTIONS}
          hint="Companies with at least one active role in this mode."
        />
        <SelectField
          label="Source"
          value={filters.source}
          onChange={(source) => update({ source })}
          options={[
            { value: 'any', label: 'Any source' },
            ...workspace.datasets.map((dataset) => ({
              value: dataset.id,
              label: `${datasetTitle(dataset)}${dataset.synthetic ? ' (sample)' : ''}`,
            })),
          ]}
        />
        <TextField
          label="Minimum priority score (0–100)"
          type="number"
          inputMode="decimal"
          min={0}
          max={100}
          step={1}
          value={scoreText}
          error={scoreError}
          onChange={(value) => {
            setScoreText(value);
            const text = value.trim();
            if (text === '') {
              setSyncedFrom(null);
              update({ min_score: null });
              return;
            }
            const number = Number(text);
            if (!Number.isNaN(number) && number >= 0 && number <= 100) {
              setSyncedFrom(number);
              update({ min_score: number });
            }
          }}
          hint="Unscored companies are hidden while a minimum is set."
        />
      </div>
      <div className="row">
        <CheckboxField
          label="Shortlisted only"
          checked={filters.shortlisted_only}
          onChange={(shortlisted_only) => update({ shortlisted_only })}
        />
        <button
          type="button"
          className="btn btn--small"
          disabled={filtersAreDefault(filters)}
          onClick={() => setFilters(DEFAULT_FILTERS)}
        >
          Clear filters
        </button>
      </div>
    </form>
  );
}

function ShortlistToggle({
  row,
  onRemoveWithNote,
}: {
  row: RadarRow;
  onRemoveWithNote: (row: RadarRow) => void;
}) {
  const { state, store } = useApp();
  const workspace = useWorkspace();
  const note = workspace.shortlist.find((entry) => entry.company_id === row.companyId)?.note ?? '';
  return (
    <button
      type="button"
      className="btn btn--small"
      aria-pressed={row.shortlisted}
      aria-label={`Shortlist ${row.name}`}
      disabled={state.pending > 0}
      onClick={() => {
        if (row.shortlisted && note.trim() !== '') {
          onRemoveWithNote(row);
          return;
        }
        void store.setShortlisted(row.companyId, !row.shortlisted);
      }}
    >
      <span aria-hidden="true">{row.shortlisted ? '✓ ' : ''}</span>
      Shortlist
    </button>
  );
}

function RadarTable({ rows }: { rows: RadarRow[] }) {
  const { openCompany, store } = useApp();
  const workspace = useWorkspace();
  const sampleIds = new Set(workspace.datasets.filter((d) => d.synthetic).map((d) => d.id));
  const [removing, setRemoving] = useState<RadarRow | null>(null);

  return (
    <>
      <TableRegion label="Companies">
        <table className="data-table data-table--radar">
          <caption className="sr-only">
            Companies with observed hiring activity, with role counts, sources, last-seen date and
            priority score. Column headers with buttons sort the table.
          </caption>
          <thead>
            <tr>
              <SortHeader label={SORT_LABELS.name} sortKey="name" sticky />
              <SortHeader label="Rank" sortKey="rank" numeric />
              <SortHeader label="Active roles" sortKey="active_roles" numeric />
              <SortHeader label="Relevant roles" sortKey="relevant_roles" numeric />
              <th scope="col">Role mix</th>
              <th scope="col">Locations</th>
              <th scope="col">Sources</th>
              <SortHeader label="Last seen" sortKey="last_seen" />
              <th scope="col">Signal age</th>
              <SortHeader label="Priority score" sortKey="score" />
              <th scope="col">Shortlist</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.companyId} data-testid="radar-row">
                <th scope="row" className="sticky-col">
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => openCompany(row.companyId)}
                  >
                    {row.name}
                  </button>
                  {row.removedRoles > 0 ? (
                    <div className="small muted">
                      {plural(row.removedRoles, 'role')} no longer listed
                    </div>
                  ) : null}
                  {/* Phones show a table that scrolls sideways, and the score column is far to
                      the right: repeat the score under the name there. Hidden from assistive
                      technology (the score column has it) and from wide screens (CSS). */}
                  <div className="row-score small" aria-hidden="true">
                    {row.score === null ? 'Not scored' : `Score ${formatScore(row.score)}`}
                  </div>
                </th>
                <td className="num">{row.rank ?? EM_DASH}</td>
                <td className="num">{row.activeRoles}</td>
                <td className="num">
                  {row.relevantRoles === null ? (
                    <>
                      <span aria-hidden="true">{EM_DASH}</span>
                      <span className="sr-only">Not measured: no role keywords are set</span>
                    </>
                  ) : (
                    row.relevantRoles
                  )}
                </td>
                <td>{roleMixText(row.roleMix)}</td>
                <td>
                  {row.locations.length === 0 ? (
                    <span className="muted">None listed</span>
                  ) : (
                    <>
                      {row.locations.slice(0, 3).join('; ')}
                      {row.locations.length > 3 ? ` +${row.locations.length - 3} more` : ''}
                    </>
                  )}
                </td>
                <td>
                  <ul className="chip-list">
                    {row.sourceIds.map((id, index) => (
                      <li key={id}>
                        <Pill tone={sampleIds.has(id) ? 'sample' : undefined}>
                          {row.sourceLabels[index] ?? id}
                        </Pill>
                      </li>
                    ))}
                  </ul>
                </td>
                <td className="nowrap">{dateOf(row.lastSeen)}</td>
                <td>{signalText(row)}</td>
                <td>
                  <ScoreMeter score={row.score} coverage={row.coverage} />
                </td>
                <td>
                  <ShortlistToggle row={row} onRemoveWithNote={setRemoving} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableRegion>
      <Dialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title="Remove from the shortlist?"
      >
        <p>
          {removing?.name} has a qualification note. Removing it from the shortlist also deletes
          that note.
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
              if (target !== null) void store.setShortlisted(target.companyId, false);
            }}
          >
            Remove and delete note
          </button>
        </div>
      </Dialog>
    </>
  );
}

export function RadarScreen() {
  const { radar, goto } = useApp();
  const workspace = useWorkspace();
  const { all, rows } = useMemo(
    () => radarView(workspace, radar.filters, radar.sort),
    [workspace, radar.filters, radar.sort],
  );
  const { analysis } = workspace;
  const scored = all.filter((row) => row.score !== null).length;
  const keywords = workspace.profile.include_keywords;

  return (
    <div className="screen">
      <div className="screen-head">
        <div>
          <h1 id="screen-title" tabIndex={-1}>
            Radar
          </h1>
          <p>Companies with observed hiring activity in the roles you configured.</p>
        </div>
      </div>

      {all.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          <dl className="stat-row" aria-label="Summary">
            <div className="stat">
              <dt>Companies</dt>
              <dd>{all.length}</dd>
            </div>
            <div className="stat">
              <dt>Active roles</dt>
              <dd>{analysis.stats.active_roles}</dd>
            </div>
            <div className="stat">
              <dt>Scored</dt>
              <dd>
                {scored} <span className="small muted">of {all.length}</span>
              </dd>
            </div>
            <div className="stat">
              <dt>Shortlisted</dt>
              <dd>{workspace.shortlist.length}</dd>
            </div>
            <div className="stat">
              <dt>Analysis time (UTC)</dt>
              <dd className="small">{analysis.as_of.replace('T', ' ').replace('Z', '')}</dd>
            </div>
          </dl>

          <p className="score-caption" data-testid="score-caption">
            {COPY.scoreCaption}
          </p>

          {keywords.length === 0 ? (
            <div className="banner banner--warn" data-testid="no-keywords-notice">
              <p>
                No role keywords are set, so role relevance cannot be measured and every active role
                counts toward volume.
              </p>
              <button type="button" className="btn btn--small" onClick={() => goto('settings')}>
                Set keywords in Settings
              </button>
            </div>
          ) : null}

          <FilterBar />
          <SavedViews resultCount={rows.length} />

          <p className="muted" role="status" data-testid="result-count">
            Showing {rows.length} of {all.length} {all.length === 1 ? 'company' : 'companies'}
            {filtersAreDefault(radar.filters) ? '' : ' (filters on)'}, sorted by{' '}
            {SORT_LABELS[radar.sort.key].toLowerCase()}{' '}
            {radar.sort.direction === 'asc' ? 'ascending' : 'descending'}.
          </p>

          {rows.length === 0 ? (
            <div className="empty-state" data-testid="no-matches">
              <h2>No company matches these filters</h2>
              <p>Loosen a filter or clear them all to see every company again.</p>
              <div>
                <button
                  type="button"
                  className="btn"
                  onClick={() => radar.setFilters(DEFAULT_FILTERS)}
                >
                  Clear filters
                </button>
              </div>
            </div>
          ) : (
            <RadarTable rows={rows} />
          )}
        </>
      )}
    </div>
  );
}
