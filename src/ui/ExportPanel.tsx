import { useMemo } from 'react';
import { buildSampleDatasets } from '../data/sample';
import { useApp, useWorkspace } from './AppContext';
import { downloadText } from './download';
import { exportFileName } from './viewModel';

export function ExportPanel() {
  const { state, store } = useApp();
  const workspace = useWorkspace();
  const local = workspace.mode === 'local';
  const empty = workspace.shortlist.length === 0;

  const exportShortlist = async () => {
    const result = await store.exportShortlistCsv();
    if (!result.ok) return;
    downloadText(exportFileName('shortlist', workspace.analysis.as_of), result.value);
    store.announce(
      'success',
      `Exported the shortlist (${workspace.shortlist.length} ${workspace.shortlist.length === 1 ? 'company' : 'companies'}).`,
    );
  };

  const exportAll = async () => {
    const result = await store.exportPostingsCsv(null);
    if (!result.ok) return;
    downloadText(exportFileName('all postings', workspace.analysis.as_of), result.value);
    store.announce('success', 'Exported every stored posting in the import format.');
  };

  return (
    <div className="stack">
      <div className="stack">
        <div className="row">
          <button
            type="button"
            className="btn btn--primary"
            disabled={state.pending > 0 || empty}
            onClick={() => void exportShortlist()}
          >
            Export shortlist CSV
          </button>
          <span className="small muted">
            {empty
              ? 'The shortlist is empty. Add companies from the Radar first.'
              : `${workspace.shortlist.length} ${workspace.shortlist.length === 1 ? 'company' : 'companies'}: rank, company, score, coverage, roles, last seen, strongest evidence, missing information, note, analysis time.`}
          </span>
        </div>
      </div>
      <div className="row">
        <button
          type="button"
          className="btn"
          disabled={state.pending > 0 || !local || workspace.datasets.length === 0}
          onClick={() => void exportAll()}
        >
          Export all postings CSV
        </button>
        <span className="small muted">
          {local
            ? 'Every stored posting in the import format, so it can be imported again.'
            : 'Available in local-data mode only; the backend API does not export stored postings.'}
        </span>
      </div>
    </div>
  );
}

export function SamplePanel() {
  const { state, store } = useApp();
  const workspace = useWorkspace();
  const local = workspace.mode === 'local';
  const samples = useMemo(
    () => buildSampleDatasets(workspace.analysis.as_of),
    [workspace.analysis.as_of],
  );
  const loaded = workspace.datasets.some(
    (dataset) =>
      dataset.source_kind === 'csv' && samples.some((s) => s.label === dataset.source_ref),
  );

  return (
    <div className="stack">
      <p>
        The sample data is two overlapping datasets of <strong>invented</strong> companies (names
        such as “Brightwater Labs”). It exists so you can try the radar, the score breakdown and
        merge review without your own data. It is not real hiring data.
      </p>
      <div className="row">
        <button
          type="button"
          className="btn btn--primary"
          disabled={state.pending > 0 || !local || loaded}
          onClick={() => void store.loadSample()}
        >
          Load sample data
        </button>
        <span className="small muted">
          {!local
            ? 'Loading sample data is only available in local-data mode, so synthetic rows never end up in the backend by accident.'
            : loaded
              ? 'The sample datasets are loaded. Remove them from the dataset list to load them again.'
              : 'Adds both datasets to this browser and, if you have none, example keywords.'}
        </span>
      </div>
      <div>
        <h3>Download the sample CSV files</h3>
        <p className="small muted">
          Plain CSV text in the import format. Import both (with different dataset labels) to see
          duplicates collapse into one company.
        </p>
        <ul className="plain-list stack">
          {samples.map((sample) => (
            <li key={sample.label} className="row">
              <button
                type="button"
                className="btn btn--small"
                onClick={() => downloadText(sample.filename, sample.csv)}
              >
                Download {sample.filename}
              </button>
              <span className="small muted">{sample.description}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
