import type { CompanyAnalysis } from '../engine';
import { COPY } from './copy';
import type { ComponentView } from './viewModel';
import { coverageText, missingInformation } from './viewModel';

/**
 * The score, component by component. Each measured component shows its weight, its value and
 * the calculation in words (from the engine's `inputs`). Components that could not be measured
 * are listed separately under "Missing information" with the reason in plain language; they are
 * left out of the score and its coverage, never counted as zero.
 */
export function ScoreBreakdown({
  company,
  views,
}: {
  company: Pick<CompanyAnalysis, 'coverage' | 'components' | 'score'>;
  views: readonly ComponentView[];
}) {
  const missing = missingInformation(views);
  const measuredWeight = views.reduce(
    (sum, view) => (view.value === null ? sum : sum + view.weight),
    0,
  );

  return (
    <section className="card stack" aria-labelledby="breakdown-title" data-testid="breakdown">
      <h2 id="breakdown-title">Score breakdown</h2>
      <p className="muted">
        Priority score = Σ(weight × value) ÷ Σ(weight of the components that could be measured).
        Coverage is that measured weight out of 100: here {coverageText(company)}, which is{' '}
        {measuredWeight} of 100 weight points.
      </p>

      <ol className="breakdown">
        {views.map((view) => (
          <li
            key={view.key}
            className={[
              'breakdown-item',
              view.value === null ? 'breakdown-item--missing' : '',
              view.caution ? 'breakdown-item--caution' : '',
            ]
              .filter((name) => name !== '')
              .join(' ')}
            data-testid={`component-${view.key}`}
          >
            <div className="breakdown-head">
              <h3 className="breakdown-title">{view.title}</h3>
              <span className="breakdown-figures">
                Weight {view.weight} · Value {view.valueText}
                {view.value === null ? '' : ' of 100'}
              </span>
            </div>
            {view.value === null ? (
              <p className="breakdown-calc">
                <strong>Not measured:</strong> {view.calculation}
              </p>
            ) : (
              <>
                <div className="meter" aria-hidden="true">
                  <span style={{ width: `${Math.min(100, view.value / 10)}%` }} />
                </div>
                <p className="breakdown-calc">{view.calculation}.</p>
              </>
            )}
            <p className="breakdown-rule">How it is worked out: {view.rule}</p>
          </li>
        ))}
      </ol>

      <div className="missing-box" data-testid="missing-information">
        <h3>{COPY.missingHeading}</h3>
        {missing.length === 0 ? (
          <p>Nothing is missing: every component of the score could be measured.</p>
        ) : (
          <>
            <p>{COPY.missingExplainer}</p>
            <ul>
              {missing.map((view) => (
                <li key={view.key}>
                  <strong>{view.title}</strong>: {view.missing?.text}{' '}
                  <span className="small">{view.missing?.help}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}
