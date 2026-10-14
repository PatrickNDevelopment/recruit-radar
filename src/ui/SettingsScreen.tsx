import { useState } from 'react';
import { normalizeKeywords } from '../data/derive';
import { DEFAULT_BACKEND_URL } from '../data/connection';
import type { ModePreference } from '../data/types';
import { useApp, useWorkspace } from './AppContext';
import { Dialog, TextAreaField, TextField } from './components';
import { dateTimeOf } from './format';

const MAX_KEYWORDS = 50;
const MAX_KEYWORD_LENGTH = 60;

function checkKeywords(label: string, lines: readonly string[]): string | null {
  if (lines.length > MAX_KEYWORDS) {
    return `${label}: at most ${MAX_KEYWORDS} keywords (you entered ${lines.length}).`;
  }
  const long = lines.find((line) => line.length > MAX_KEYWORD_LENGTH);
  if (long !== undefined) {
    return `${label}: each keyword is at most ${MAX_KEYWORD_LENGTH} characters ("${long.slice(0, 24)}…" is ${long.length}).`;
  }
  return null;
}

function KeywordsForm() {
  const { state, store } = useApp();
  const workspace = useWorkspace();
  const saved = workspace.profile;
  const [include, setInclude] = useState(saved.include_keywords.join('\n'));
  const [exclude, setExclude] = useState(saved.exclude_keywords.join('\n'));
  const [problems, setProblems] = useState<{ include: string | null; exclude: string | null }>({
    include: null,
    exclude: null,
  });

  const submit = async () => {
    const includeList = normalizeKeywords(include.split(/\r?\n/u));
    const excludeList = normalizeKeywords(exclude.split(/\r?\n/u));
    const next = {
      include: checkKeywords('Include keywords', includeList),
      exclude: checkKeywords('Exclude keywords', excludeList),
    };
    setProblems(next);
    if (next.include !== null || next.exclude !== null) return;
    const result = await store.setProfile({
      include_keywords: includeList,
      exclude_keywords: excludeList,
    });
    if (result.ok) {
      setInclude(includeList.join('\n'));
      setExclude(excludeList.join('\n'));
    }
  };

  return (
    <form
      className="stack"
      noValidate
      aria-label="Role keywords"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="form-grid">
        <TextAreaField
          label="Include keywords (one per line)"
          value={include}
          onChange={setInclude}
          rows={6}
          error={problems.include}
          hint="A role is relevant when its title contains one of these words or phrases, for example “data engineer”. Roles are matched on whole words, ignoring case and punctuation."
        />
        <TextAreaField
          label="Exclude keywords (one per line)"
          value={exclude}
          onChange={setExclude}
          rows={6}
          error={problems.exclude}
          hint="A role that contains any of these is never relevant, for example “intern”."
        />
      </div>
      <p className="small muted">
        Up to {MAX_KEYWORDS} keywords of {MAX_KEYWORD_LENGTH} characters each. Saving recalculates
        every score.
      </p>
      <div>
        <button type="submit" className="btn btn--primary" disabled={state.pending > 0}>
          Save keywords
        </button>
      </div>
    </form>
  );
}

const MODE_OPTIONS: ReadonlyArray<{ value: ModePreference; label: string; help: string }> = [
  {
    value: 'auto',
    label: 'Automatic',
    help: 'Use the backend when this page is served from your own computer and a healthy backend answers; otherwise use local-data mode.',
  },
  {
    value: 'local',
    label: 'Always local-data mode',
    help: 'Keep everything in this browser and never contact a backend.',
  },
  {
    value: 'connected',
    label: 'Use the backend',
    help: 'Contact the backend at the address above, also from a public page (your browser decides whether a public page may reach a local address). Falls back to local-data mode, with a visible warning, if it is not reachable.',
  },
];

function ConnectionForm() {
  const { state, store } = useApp();
  const [address, setAddress] = useState(state.prefs.backend_url);
  const [error, setError] = useState<string | null>(null);
  const { backend, prefs } = state;

  const save = async () => {
    const result = await store.setBackendUrl(address);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setError(null);
    setAddress(store.getState().prefs.backend_url);
    const health = store.getState().backend;
    store.announce(
      health.state === 'ok' ? 'success' : 'info',
      health.state === 'ok'
        ? `Backend address saved. The backend answered at ${store.getState().prefs.backend_url}.`
        : `Backend address saved. ${health.state === 'offline' ? health.message : ''}`,
    );
  };

  let statusText: string;
  switch (backend.state) {
    case 'ok':
      statusText =
        `Reachable (checked ${dateTimeOf(backend.checked_at)}). ` +
        `App version ${backend.app_version ?? 'unknown'}, schema ${backend.schema_version ?? 'unknown'}.`;
      break;
    case 'offline':
      statusText = `Not reachable (checked ${dateTimeOf(backend.checked_at)}): ${backend.message}`;
      break;
    case 'checking':
      statusText = 'Checking…';
      break;
    case 'unchecked':
      statusText = 'Not checked yet.';
      break;
  }

  return (
    <div className="stack">
      <form
        className="stack"
        noValidate
        aria-label="Backend address"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <TextField
          label="Backend address"
          type="url"
          inputMode="url"
          value={address}
          onChange={setAddress}
          error={error}
          hint={`http:// or https:// only. The default is ${DEFAULT_BACKEND_URL}.`}
        />
        <div className="row">
          <button type="submit" className="btn btn--primary" disabled={state.pending > 0}>
            Save and check connection
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => void store.recheckBackend()}
            disabled={backend.state === 'checking'}
          >
            Check again
          </button>
        </div>
      </form>

      <p data-testid="connection-status">
        <strong>Connection:</strong> {statusText}
      </p>
      <p data-testid="current-mode">
        <strong>Current mode:</strong>{' '}
        {state.mode === 'connected'
          ? `Connected mode (backend at ${prefs.backend_url}).`
          : 'Local-data mode (data stays in this browser).'}
      </p>

      <fieldset>
        <legend>Where should data come from?</legend>
        <div className="stack">
          {MODE_OPTIONS.map((option) => (
            <div key={option.value}>
              <label className="check">
                <input
                  type="radio"
                  name="mode-preference"
                  value={option.value}
                  checked={prefs.mode_preference === option.value}
                  onChange={() => {
                    void store.setModePreference(option.value).then(() => {
                      const now = store.getState();
                      store.announce(
                        'info',
                        now.mode === 'connected'
                          ? 'Now using the backend.'
                          : 'Now using local-data mode.',
                      );
                    });
                  }}
                />
                <span>{option.label}</span>
              </label>
              <div className="field-hint">{option.help}</div>
            </div>
          ))}
        </div>
      </fieldset>
    </div>
  );
}

function EraseData() {
  const { state, store } = useApp();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState('');
  const connected = state.mode === 'connected';
  const ready = typed.trim().toLowerCase() === 'erase';

  const close = () => {
    setOpen(false);
    setTyped('');
  };

  return (
    <div className="stack">
      <p>
        {connected
          ? 'This permanently deletes everything stored in the backend database: postings, snapshots, sources and their refresh history, merge decisions, the shortlist and the keywords. Data held in this browser in local-data mode is not touched.'
          : 'This permanently deletes everything stored in this browser: datasets, merge decisions, the shortlist with its notes, and the keywords. Saved views and the backend address are kept.'}{' '}
        It cannot be undone. Export what you need first.
      </p>
      <div>
        <button
          type="button"
          className="btn btn--danger"
          disabled={state.pending > 0}
          onClick={() => setOpen(true)}
        >
          Erase all data…
        </button>
      </div>
      <Dialog open={open} onClose={close} title="Erase all data?">
        <p>
          {connected
            ? 'Everything in the backend database will be deleted.'
            : 'Everything stored in this browser will be deleted.'}{' '}
          This cannot be undone.
        </p>
        <TextField
          label="Type erase to confirm"
          value={typed}
          onChange={setTyped}
          autoComplete="off"
        />
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={close}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn--danger"
            disabled={!ready}
            onClick={() => {
              close();
              void store.eraseAll();
            }}
          >
            Erase everything
          </button>
        </div>
      </Dialog>
    </div>
  );
}

export function SettingsScreen() {
  const workspace = useWorkspace();
  const profileKey = JSON.stringify(workspace.profile);
  return (
    <div className="screen">
      <div className="screen-head">
        <div>
          <h1 id="screen-title" tabIndex={-1}>
            Settings
          </h1>
          <p>Role keywords, the backend connection and your stored data.</p>
        </div>
      </div>

      <section className="card stack" aria-labelledby="keywords-title">
        <h2 id="keywords-title">Role keywords</h2>
        <KeywordsForm key={profileKey} />
      </section>

      <section className="card stack" aria-labelledby="connection-title">
        <h2 id="connection-title">Backend connection</h2>
        <p className="muted">
          The optional local backend adds live ATS refresh and keeps data in a SQLite file. It is
          never contacted from a public page unless you choose “Use the backend”.
        </p>
        <ConnectionForm />
      </section>

      <section className="card stack" aria-labelledby="erase-title">
        <h2 id="erase-title">Erase data</h2>
        <EraseData />
      </section>
    </div>
  );
}
