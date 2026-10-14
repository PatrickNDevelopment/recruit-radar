import type { ReactNode } from 'react';
import { useApp } from './AppContext';
import { COPY } from './copy';
import { dateTimeOf } from './format';

/**
 * Honest state banners, in the order a reader needs them: which mode the data is in, whether any
 * of it is synthetic, and anything that makes the data older or less reliable than it looks.
 */
export function Banners() {
  const { state, store, goto } = useApp();
  const workspace = state.workspace;
  const items: ReactNode[] = [];

  if (state.prefsProblem !== null) {
    items.push(
      <div key="prefs" className="banner banner--warn">
        <p>{state.prefsProblem}</p>
      </div>,
    );
  }

  if (workspace !== null) {
    if (workspace.mode === 'local') {
      items.push(
        <div key="local" className="banner banner--local" data-testid="local-banner">
          <p>{COPY.localBanner}</p>
        </div>,
      );
    } else {
      items.push(
        <div key="connected" className="banner banner--ok" data-testid="connected-banner">
          <p>
            Connected mode: data comes from the local backend at {state.prefs.backend_url} and is
            stored in its SQLite database.
          </p>
        </div>,
      );
    }

    if (workspace.has_sample_data) {
      items.push(
        <div key="sample" className="banner banner--sample" data-testid="sample-banner">
          <p>{COPY.sampleBanner}</p>
        </div>,
      );
    }

    for (const notice of workspace.notices) {
      items.push(
        <div
          key={`notice-${notice.kind}`}
          className={
            notice.kind === 'newer_schema' ? 'banner banner--error' : 'banner banner--warn'
          }
          data-testid={`notice-${notice.kind}`}
        >
          <p>{notice.message}</p>
        </div>,
      );
    }
  }

  if (state.backend.state === 'offline' && state.prefs.mode_preference === 'connected') {
    items.push(
      <div key="offline" className="banner banner--warn" data-testid="offline-banner">
        <p>
          You asked for connected mode, but the backend is not reachable: {state.backend.message}{' '}
          The app is using local-data mode meanwhile.
        </p>
        <button
          type="button"
          className="btn btn--small"
          onClick={() => void store.recheckBackend()}
        >
          Check connection again
        </button>
        <button type="button" className="btn btn--small" onClick={() => goto('settings')}>
          Open Settings
        </button>
      </div>,
    );
  }

  if (state.stale !== null) {
    items.push(
      <div key="stale" className="banner banner--warn" data-testid="stale-banner">
        <p>
          Showing the last data received (analysis time {dateTimeOf(state.stale.asOf)}). It could
          not be refreshed: {state.stale.reason}
        </p>
        <button
          type="button"
          className="btn btn--small"
          onClick={() => void store.recheckBackend()}
        >
          Try again
        </button>
      </div>,
    );
  }

  if (state.externalChange) {
    items.push(
      <div key="external" className="banner banner--warn" data-testid="external-change-banner">
        <p>
          Another browser tab changed the saved data, so what you see here may be out of date.
          Changes you make here are applied on top of the saved data, not over it.
        </p>
        <button type="button" className="btn btn--small" onClick={() => void store.reload()}>
          Refresh data
        </button>
      </div>,
    );
  }

  if (items.length === 0) return null;
  return <div className="banners">{items}</div>;
}
