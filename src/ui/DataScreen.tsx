import { CsvImport } from './CsvImport';
import { DatasetsPanel } from './DatasetsPanel';
import { ExportPanel, SamplePanel } from './ExportPanel';
import { ManualEntry } from './ManualEntry';
import { MergeReview } from './MergeReview';
import { useApp, useWorkspace } from './AppContext';

const SECTIONS = [
  { id: 'data-manual', label: 'Add a posting' },
  { id: 'data-import', label: 'Import a CSV file' },
  { id: 'data-datasets', label: 'Datasets' },
  { id: 'data-merge', label: 'Merge review' },
  { id: 'data-export', label: 'Export' },
  { id: 'data-sample', label: 'Sample data' },
];

export function DataScreen() {
  const workspace = useWorkspace();
  const { state } = useApp();
  const candidates = workspace.analysis.merge_candidates.length;
  return (
    <div className="screen">
      <div className="screen-head">
        <div>
          <h1 id="screen-title" tabIndex={-1}>
            Data
          </h1>
          <p>
            Add postings, import CSV files, review possible duplicate companies and export what you
            have.{' '}
            {workspace.mode === 'local'
              ? 'Everything is stored in this browser.'
              : 'Everything is stored by the local backend.'}
          </p>
        </div>
      </div>

      <nav aria-label="On this page">
        <ul className="toc">
          {SECTIONS.map((section) => (
            <li key={section.id}>
              <a href={`#${section.id}`}>
                {section.label}
                {section.id === 'data-merge' && candidates > 0 ? ` (${candidates})` : ''}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <section className="card stack" id="data-manual" aria-labelledby="manual-title">
        <h2 id="manual-title">Add a posting</h2>
        <p className="muted">
          One job posting you saw on a public careers page. It is stored as manual entry. Company
          name and title are required.
        </p>
        <ManualEntry />
      </section>

      <section className="card stack" id="data-import" aria-labelledby="import-title">
        <h2 id="import-title">Import a CSV file</h2>
        <p className="muted">
          Each import is stored as a dataset under the label you choose. Rows are checked one by
          one: valid rows are kept, invalid rows are reported with their line number so you can
          correct them here.
        </p>
        <CsvImport />
      </section>

      <section className="card stack" id="data-datasets" aria-labelledby="datasets-title">
        <h2 id="datasets-title">Datasets</h2>
        <DatasetsPanel />
      </section>

      <section className="card stack" id="data-merge" aria-labelledby="merge-title">
        <h2 id="merge-title">Merge review</h2>
        <MergeReview />
      </section>

      <section className="card stack" id="data-export" aria-labelledby="export-title">
        <h2 id="export-title">Export</h2>
        <p className="muted">
          {state.mode === 'connected'
            ? 'The shortlist CSV is produced by the local backend and saved by your browser.'
            : 'Files are generated in your browser and saved by your browser; nothing is uploaded.'}
        </p>
        <ExportPanel />
      </section>

      <section className="card stack" id="data-sample" aria-labelledby="sample-title">
        <h2 id="sample-title">Sample data</h2>
        <SamplePanel />
      </section>
    </div>
  );
}
