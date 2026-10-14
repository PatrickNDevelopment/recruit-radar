import { useState } from 'react';
import type { DatasetSummary } from '../data/types';
import { useApp, useWorkspace } from './AppContext';
import { Dialog, Pill, TableRegion } from './components';
import { dateOf, EM_DASH } from './format';
import { datasetTitle, exportFileName } from './viewModel';
import { downloadText } from './download';

export function DatasetsPanel() {
  const { state, store } = useApp();
  const workspace = useWorkspace();
  const local = workspace.mode === 'local';
  const [removing, setRemoving] = useState<DatasetSummary | null>(null);

  if (workspace.datasets.length === 0) {
    return <p>No datasets yet. Add a posting or import a CSV file above.</p>;
  }

  const exportOne = async (dataset: DatasetSummary) => {
    const result = await store.exportPostingsCsv(dataset.id);
    if (!result.ok) return;
    downloadText(
      exportFileName(`dataset ${datasetTitle(dataset)}`, workspace.analysis.as_of),
      result.value,
    );
    store.announce(
      'success',
      `Exported ${dataset.postings ?? 0} postings of ${datasetTitle(dataset)}.`,
    );
  };

  return (
    <>
      {local ? null : (
        <p className="small muted">
          In connected mode the backend holds the data. Counts below are derived from the current
          analysis; removing a single dataset or exporting its raw postings is available in
          local-data mode only. Use “Erase all data” in Settings to wipe the backend.
        </p>
      )}
      <TableRegion label="Datasets">
        <table className="data-table" style={{ minWidth: '56rem' }}>
          <thead>
            <tr>
              <th scope="col" className="sticky-col">
                Dataset
              </th>
              <th scope="col">Kind</th>
              <th scope="col" className="num">
                Postings
              </th>
              <th scope="col" className="num">
                Snapshots
              </th>
              <th scope="col" className="num">
                Roles
              </th>
              <th scope="col" className="num">
                Active
              </th>
              <th scope="col">First observed</th>
              <th scope="col">Last observed</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {workspace.datasets.map((dataset) => (
              <tr key={dataset.id} data-testid="dataset-row">
                <th scope="row" className="sticky-col">
                  {datasetTitle(dataset)}
                </th>
                <td>
                  {dataset.synthetic ? (
                    <Pill tone="sample">Sample (synthetic)</Pill>
                  ) : dataset.source_kind === 'csv' ? (
                    <Pill>CSV import</Pill>
                  ) : dataset.source_kind === 'manual' ? (
                    <Pill>Manual entry</Pill>
                  ) : (
                    <Pill tone="live">Live ATS</Pill>
                  )}
                </td>
                <td className="num">{dataset.postings ?? EM_DASH}</td>
                <td className="num">
                  {dataset.snapshots ?? EM_DASH}
                  {dataset.ignored_snapshots > 0 ? (
                    <div className="small muted">
                      {dataset.ignored_snapshots} ignored (dated later)
                    </div>
                  ) : null}
                </td>
                <td className="num">{dataset.roles}</td>
                <td className="num">{dataset.active_roles}</td>
                <td className="nowrap">{dateOf(dataset.first_seen)}</td>
                <td className="nowrap">{dateOf(dataset.last_seen)}</td>
                <td>
                  <div className="row">
                    {workspace.mode === 'local' ? (
                      <>
                        <button
                          type="button"
                          className="btn btn--small"
                          disabled={state.pending > 0}
                          onClick={() => void exportOne(dataset)}
                        >
                          Export CSV
                          <span className="sr-only"> of {datasetTitle(dataset)}</span>
                        </button>
                        <button
                          type="button"
                          className="btn btn--small"
                          disabled={state.pending > 0}
                          onClick={() => setRemoving(dataset)}
                        >
                          Remove
                          <span className="sr-only"> {datasetTitle(dataset)}</span>
                        </button>
                      </>
                    ) : (
                      <span className="small muted">Local mode only</span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableRegion>

      <Dialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title="Remove this dataset?"
      >
        <p>
          This removes {removing === null ? '' : datasetTitle(removing)} and its{' '}
          {removing?.postings ?? 0} postings from this browser, then recalculates every score.
          Shortlist entries for companies that only appear in it are removed too. Export the dataset
          first if you may need it again.
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
              if (target !== null) void store.removeDataset(target.id);
            }}
          >
            Remove dataset
          </button>
        </div>
      </Dialog>
    </>
  );
}
