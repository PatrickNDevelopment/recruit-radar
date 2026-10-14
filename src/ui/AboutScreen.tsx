import { COMPONENT_KEYS, WEIGHTS, type ComponentKey, type ReasonCode } from '../engine';
import { TableRegion } from './components';
import { COMPONENT_RULES, COMPONENT_TITLES, COPY, REASONS } from './copy';

const MISSING_WHEN: Readonly<Record<ComponentKey, readonly ReasonCode[]>> = {
  role_relevance: ['no_active_roles', 'no_keywords'],
  volume: ['no_active_roles'],
  change: ['no_active_roles', 'insufficient_history'],
  urgency: ['no_active_roles', 'no_scope_roles', 'no_dated_roles'],
  source_confidence: ['no_active_roles', 'no_scope_roles'],
  freshness: ['no_active_roles'],
};

export function AboutScreen() {
  return (
    <div className="screen">
      <div className="screen-head">
        <div>
          <h1 id="screen-title" tabIndex={-1}>
            About
          </h1>
          <p>The method, the formulas and the limits of what this app can tell you.</p>
        </div>
      </div>

      <section className="card prose stack" aria-labelledby="what-title">
        <h2 id="what-title">What RecruitRadar does</h2>
        <p>
          RecruitRadar turns public job-posting data into an evidence-backed, explainable view of
          which companies show hiring activity in the roles you care about. Every number on screen
          can be traced to the postings it came from.
        </p>
        <h3>What it is not</h3>
        <ul>
          <li>
            It is not a candidate tool: there are no candidate records, no candidate scoring, no
            outreach and no e-mail addresses, guessed or real.
          </li>
          <li>
            It never says or implies that a company needs, is struggling with, or will pay for an
            outside recruiter. A posting is a posting; the score describes{' '}
            <em>observed hiring activity</em>.
          </li>
          <li>
            It does not scrape web pages, use logins or work around CAPTCHAs. Data comes only from
            files and entries you provide and, in connected mode, from the three documented public
            job-board JSON APIs (Greenhouse, Lever, Ashby).
          </li>
          <li>It needs no account, no secret and no paid service.</li>
        </ul>
      </section>

      <section className="card prose stack" aria-labelledby="method-title">
        <h2 id="method-title">Method</h2>
        <ol>
          <li>
            <strong>Collect.</strong> Postings arrive as manual entries, CSV imports, or (connected
            mode) full lists fetched from a job board. Each load is kept as a dated snapshot with
            its source.
          </li>
          <li>
            <strong>Normalize.</strong> Company names are compared after lower-casing, removing
            punctuation and trailing legal suffixes such as “Inc.” or “GmbH”. Titles ignore text in
            brackets. Locations are compared as sorted word sets.
          </li>
          <li>
            <strong>Resolve identity.</strong> Equal normalized names are one company. Similar names
            (spacing variants, near typos, heavy word overlap) are only <em>suggested</em>; nothing
            is merged until you decide on the Data tab, and you can undo it.
          </li>
          <li>
            <strong>De-duplicate roles.</strong> The same title and location from different sources
            is one role with several observations. Two identical postings inside one source stay two
            roles (two headcounts).
          </li>
          <li>
            <strong>Replay history.</strong> Snapshots are replayed in time order to find roles that
            were added, changed, no longer listed, or listed again. Only a <em>full-list</em>{' '}
            snapshot can show that a role disappeared; CSV imports and manual entries cannot.
          </li>
          <li>
            <strong>Score.</strong> Six components are measured per company (below). Components that
            cannot be measured are reported as missing information and left out.
          </li>
        </ol>
      </section>

      <section className="card prose stack" aria-labelledby="scoring-title">
        <h2 id="scoring-title">Scoring formulas</h2>
        <p data-testid="about-score-caption">{COPY.scoreCaption}</p>
        <p>
          Scores are whole numbers from 0 to 1000 internally and are shown divided by ten, from 0 to
          100 with one decimal. There is no floating-point arithmetic: halves round up.
        </p>
        <p className="formula">
          priority score = Σ(weight × value) ÷ Σ(weight of the components that were measured)
        </p>
        <p>
          <strong>Coverage</strong> is the sum of the weights of the measured components (0 to 100).
          A score with low coverage rests on little evidence; read it together with the list of
          missing information.
        </p>
        <TableRegion label="Score components, weights and formulas">
          <table className="data-table" style={{ minWidth: '48rem' }}>
            <thead>
              <tr>
                <th scope="col">Component</th>
                <th scope="col" className="num">
                  Weight
                </th>
                <th scope="col">How the value is worked out</th>
                <th scope="col">Missing information when</th>
              </tr>
            </thead>
            <tbody>
              {COMPONENT_KEYS.map((key) => (
                <tr key={key}>
                  <th scope="row">{COMPONENT_TITLES[key]}</th>
                  <td className="num">{WEIGHTS[key]}</td>
                  <td>{COMPONENT_RULES[key]}</td>
                  <td>
                    <ul className="plain-list">
                      {MISSING_WHEN[key].map((code) => (
                        <li key={code}>{REASONS[code].text}</li>
                      ))}
                    </ul>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableRegion>
        <p>
          “In scope” means active roles that match your include keywords and none of your exclude
          keywords; with no keywords set, every active role is in scope and role relevance is
          missing information.
        </p>
        <p data-testid="about-urgency">{COPY.urgencyLabel}</p>
        <p>
          The urgency component only asks how many dated roles have been listed for 45 days or more.
          Long-listed roles can mean many things (a hard search, a stale listing, a perpetual
          requisition); the app cannot tell which.
        </p>
      </section>

      <section className="card prose stack" aria-labelledby="modes-title">
        <h2 id="modes-title">Two ways to run</h2>
        <h3>Local-data mode</h3>
        <p>
          The default for the static demo and when no backend is found. The same analysis engine
          runs in your browser and data is stored in this browser (<code>localStorage</code>). It
          works offline. Live ATS refresh is not available. Clearing site data erases it, and a
          private window may not be able to keep it at all (the app tells you when that is the
          case).
        </p>
        <h3>Connected mode</h3>
        <p>
          A local FastAPI backend stores data in SQLite and adds read-only refresh of Greenhouse,
          Lever and Ashby boards, with a history of every run. The page only contacts the backend
          address you set in Settings, and a page served from a public host never looks for one on
          its own.
        </p>
      </section>

      <section className="card prose stack" aria-labelledby="limits-title">
        <h2 id="limits-title">Limitations</h2>
        <ul>
          <li>
            Postings are what companies publish. They can be stale, duplicated across boards,
            reposted, or left open without active hiring. A score is evidence of listing activity,
            not of intent or need.
          </li>
          <li>
            Scores compare companies <em>within the data you loaded</em>. Changing keywords or
            adding a dataset changes every score; scores from different datasets are not comparable.
          </li>
          <li>
            Change over time needs at least two full-list snapshots taken 14 or more days apart.
            Without them the change component is reported as missing, not as “no change”.
          </li>
          <li>
            Role age uses the posting date when there is one. Without it, age is only estimated when
            the history covers at least 45 days.
          </li>
          <li>
            Ashby's public API lists no job id, so ids are derived from the job link; a changed link
            looks like a different role.
          </li>
          <li>
            Name matching is deliberately conservative: different spellings of one company can stay
            separate until you merge them, and similar-looking names are never merged for you.
          </li>
          <li>
            Local-data mode holds at most 5,000 postings in total, and a CSV import is limited to 1
            MB and 5,000 rows.
          </li>
          <li>
            All times are UTC. The sample data is invented and exists only to demonstrate the app.
          </li>
          <li>
            Each ATS provider's terms and rate limits are not documented publicly; the backend is
            deliberately conservative (one request at a time, at least a minute between refreshes of
            one source).
          </li>
        </ul>
      </section>

      <section className="card prose stack" aria-labelledby="privacy-title">
        <h2 id="privacy-title">Your data</h2>
        <p>
          The app has no analytics, no tracking, no accounts and loads no fonts, scripts or images
          from other sites. Exports are files generated on your machine. In local-data mode nothing
          is sent anywhere; in connected mode requests go only to the backend address you set.
        </p>
      </section>
    </div>
  );
}
