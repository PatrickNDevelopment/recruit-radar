import type { MergeCandidate } from '../engine';
import { findCompanyByKey } from '../data/derive';
import { useApp, useWorkspace } from './AppContext';
import { MERGE_REASON_TEXT } from './copy';
import { plural } from './format';
import { decisionRows } from './viewModel';

function CompanySummary({ name, companyKey }: { name: string; companyKey: string }) {
  const workspace = useWorkspace();
  const company = findCompanyByKey(workspace.analysis, companyKey);
  return (
    <span>
      {name}
      {company === null ? null : (
        <span className="small muted"> ({plural(company.active_roles, 'active role')})</span>
      )}
    </span>
  );
}

function Candidate({ candidate }: { candidate: MergeCandidate }) {
  const { state, store } = useApp();
  const busy = state.pending > 0;
  return (
    <li className="card candidate" data-testid="merge-candidate">
      <div className="candidate-names">
        <CompanySummary name={candidate.a_name} companyKey={candidate.a_key} />
        <span className="vs" aria-hidden="true">
          vs
        </span>
        <span className="sr-only"> and </span>
        <CompanySummary name={candidate.b_name} companyKey={candidate.b_key} />
      </div>
      <p className="muted">
        {MERGE_REASON_TEXT[candidate.reason]} Nothing is merged unless you accept.
      </p>
      <div className="row">
        <button
          type="button"
          className="btn btn--primary btn--small"
          disabled={busy}
          onClick={() => void store.decideCandidate(candidate, 'merge')}
        >
          Merge as one company
          <span className="sr-only">
            : {candidate.a_name} and {candidate.b_name}
          </span>
        </button>
        <button
          type="button"
          className="btn btn--small"
          disabled={busy}
          onClick={() => void store.decideCandidate(candidate, 'not_same')}
        >
          Not the same company
          <span className="sr-only">
            : {candidate.a_name} and {candidate.b_name}
          </span>
        </button>
      </div>
    </li>
  );
}

export function MergeReview() {
  const { state, store } = useApp();
  const workspace = useWorkspace();
  const candidates = workspace.analysis.merge_candidates;
  const decisions = decisionRows(workspace);

  return (
    <div className="stack">
      <p className="muted">
        Companies are only combined automatically when their names are equal after ignoring case,
        punctuation and legal suffixes such as “Inc.”. Names that merely look alike are listed here
        for you to decide.
      </p>

      <h3>Candidates ({candidates.length})</h3>
      {candidates.length === 0 ? (
        <p data-testid="no-candidates">No similar company names need a decision.</p>
      ) : (
        <ul className="plain-list stack">
          {candidates.map((candidate) => (
            <Candidate key={candidate.candidate_id} candidate={candidate} />
          ))}
        </ul>
      )}

      <h3>Your decisions ({decisions.length})</h3>
      {decisions.length === 0 ? (
        <p className="muted">You have not made any decisions yet.</p>
      ) : (
        <ul className="plain-list stack">
          {decisions.map((row) => (
            <li key={row.record.id} className="card" data-testid="merge-decision">
              <div className="row">
                <span>
                  {row.kind === 'merge' ? 'Merged' : 'Kept apart'}: {row.aName} and {row.bName}
                </span>
                <button
                  type="button"
                  className="btn btn--small"
                  disabled={state.pending > 0}
                  onClick={() => void store.undoDecision(row.record.id)}
                >
                  Undo
                  <span className="sr-only">
                    {' '}
                    decision about {row.aName} and {row.bName}
                  </span>
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
