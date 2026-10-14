import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { SessionState, SessionStore } from './data/session';
import { DEFAULT_FILTERS, DEFAULT_SORT, type RadarFilters, type RadarSort } from './data/types';
import { AboutScreen } from './ui/AboutScreen';
import { AppContext, TABS, useApp, type AppContextValue, type TabId } from './ui/AppContext';
import { Banners } from './ui/Banners';
import { BrandMark } from './ui/Brand';
import { CompanyScreen } from './ui/CompanyScreen';
import { COPY } from './ui/copy';
import { DataScreen } from './ui/DataScreen';
import { RadarScreen } from './ui/RadarScreen';
import { SettingsScreen } from './ui/SettingsScreen';
import { SourcesScreen } from './ui/SourcesScreen';
import { useSession } from './ui/useSession';
import { reconcileFilters } from './ui/viewModel';

const SCREEN_TITLES: Record<TabId, string> = {
  radar: 'Radar',
  data: 'Data',
  sources: 'Sources',
  settings: 'Settings',
  about: 'About',
};

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function ModeChip({ state }: { state: SessionState }) {
  if (state.mode === 'connected') {
    return (
      <p className="mode-chip mode-chip--connected" data-testid="mode-chip">
        <span className="dot" aria-hidden="true" />
        <strong>Connected mode</strong>
        <span>backend {hostOf(state.prefs.backend_url)}</span>
      </p>
    );
  }
  let detail = 'no backend connected';
  let warn = false;
  switch (state.backend.state) {
    case 'checking':
      detail = 'checking for a backend';
      break;
    case 'offline':
      detail = 'backend not reachable';
      warn = state.prefs.mode_preference === 'connected';
      break;
    case 'ok':
      detail = 'backend found, local data selected';
      break;
    case 'unchecked':
      break;
  }
  return (
    <p
      className={`mode-chip mode-chip--local${warn ? ' mode-chip--warn' : ''}`}
      data-testid="mode-chip"
    >
      <span className="dot" aria-hidden="true" />
      <strong>Local-data mode</strong>
      <span>{detail}</span>
    </p>
  );
}

function StatusArea() {
  const { state, store } = useApp();
  const { status } = state;
  const message =
    status === null ? null : (
      <div key={status.id} className={`status-message status-message--${status.kind}`}>
        <p data-testid="status-text">{status.text}</p>
        <button type="button" className="btn btn--small" onClick={() => store.clearStatus()}>
          Dismiss
        </button>
      </div>
    );
  return (
    <>
      <div role="status" aria-live="polite" aria-atomic="true">
        {status !== null && status.kind !== 'error' ? message : null}
      </div>
      <div role="alert">{status !== null && status.kind === 'error' ? message : null}</div>
    </>
  );
}

function Loading() {
  return (
    <div className="card" role="status" data-testid="loading">
      <h1 id="screen-title" tabIndex={-1}>
        Loading
      </h1>
      <p>Loading your data…</p>
    </div>
  );
}

function LoadFailed() {
  const { state, store } = useApp();
  return (
    <div className="card stack" data-testid="load-failed">
      <h1 id="screen-title" tabIndex={-1}>
        The data could not be loaded
      </h1>
      <p>{state.loadError}</p>
      <div className="row">
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => void store.recheckBackend()}
        >
          Try again
        </button>
        {state.mode === 'connected' ? (
          <button
            type="button"
            className="btn"
            onClick={() => void store.setModePreference('local')}
          >
            Use local-data mode instead
          </button>
        ) : null}
      </div>
    </div>
  );
}

function Screen() {
  const { state, tab, companyId } = useApp();
  if (state.workspace === null) {
    if (!state.ready || state.loading) return <Loading />;
    return <LoadFailed />;
  }
  switch (tab) {
    case 'radar':
      return companyId === null ? <RadarScreen /> : <CompanyScreen companyId={companyId} />;
    case 'data':
      return <DataScreen />;
    case 'sources':
      return <SourcesScreen />;
    case 'settings':
      return <SettingsScreen />;
    case 'about':
      return <AboutScreen />;
  }
}

export function App({ store }: { store: SessionStore }) {
  const state = useSession(store);
  const [tab, setTab] = useState<TabId>('radar');
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [filters, setFilters] = useState<RadarFilters>(DEFAULT_FILTERS);
  const [sort, setSort] = useState<RadarSort>(DEFAULT_SORT);

  useEffect(() => {
    void store.start();
  }, [store]);

  // A status message belongs to the screen it was produced on; leaving the screen clears it.
  const goto = useCallback(
    (next: TabId) => {
      store.clearStatus();
      setTab(next);
      setCompanyId(null);
    },
    [store],
  );
  const openCompany = useCallback(
    (id: string) => {
      store.clearStatus();
      setTab('radar');
      setCompanyId(id);
    },
    [store],
  );
  const closeCompany = useCallback(() => {
    store.clearStatus();
    setCompanyId(null);
  }, [store]);

  // Move focus to the new screen's heading so keyboard and screen-reader users land on it.
  const screenKey = `${tab}:${companyId ?? ''}`;
  const lastKey = useRef(screenKey);
  useEffect(() => {
    if (lastKey.current === screenKey) return;
    lastKey.current = screenKey;
    document.getElementById('screen-title')?.focus();
    window.scrollTo(0, 0);
  }, [screenKey]);

  useEffect(() => {
    document.title = `${SCREEN_TITLES[tab]} · RecruitRadar`;
  }, [tab]);

  // A filter that names a dataset which has since been removed would hide every company without
  // explanation; fall back to "any source" instead.
  const datasets = state.workspace?.datasets;
  const effectiveFilters = useMemo(
    () => (datasets === undefined ? filters : reconcileFilters(filters, datasets).filters),
    [filters, datasets],
  );

  const value = useMemo<AppContextValue>(
    () => ({
      store,
      state,
      tab,
      goto,
      companyId,
      openCompany,
      closeCompany,
      radar: { filters: effectiveFilters, setFilters, sort, setSort },
    }),
    [store, state, tab, goto, companyId, openCompany, closeCompany, effectiveFilters, sort],
  );

  return (
    <AppContext.Provider value={value}>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="app-header">
        <div className="header-inner">
          <div className="header-top">
            <div className="brand">
              <BrandMark />
              <div>
                <p className="brand-name">RecruitRadar</p>
                <p className="brand-tagline">{COPY.appTagline}</p>
              </div>
            </div>
            <ModeChip state={state} />
          </div>
          <nav className="main-nav" aria-label="Main">
            <ul>
              {TABS.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className="nav-button"
                    aria-current={tab === item.id ? 'page' : undefined}
                    onClick={() => goto(item.id)}
                  >
                    {item.label}
                  </button>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </header>
      <main id="main" className="shell" tabIndex={-1}>
        <Banners />
        <StatusArea />
        <Screen />
      </main>
      <footer className="app-footer">
        <p>
          RecruitRadar is a read-only view of public job-posting data. It stores no candidate
          records, sends no messages and never scrapes web pages. See the About tab for the method
          and its limits.
        </p>
      </footer>
    </AppContext.Provider>
  );
}
