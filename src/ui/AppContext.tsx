import { createContext, useContext } from 'react';
import type { SessionState, SessionStore } from '../data/session';
import type { RadarFilters, RadarSort, Workspace } from '../data/types';

export type TabId = 'radar' | 'data' | 'sources' | 'settings' | 'about';

export const TABS: ReadonlyArray<{ id: TabId; label: string }> = [
  { id: 'radar', label: 'Radar' },
  { id: 'data', label: 'Data' },
  { id: 'sources', label: 'Sources' },
  { id: 'settings', label: 'Settings' },
  { id: 'about', label: 'About' },
];

export interface AppContextValue {
  store: SessionStore;
  state: SessionState;
  tab: TabId;
  goto: (tab: TabId) => void;
  companyId: string | null;
  openCompany: (companyId: string) => void;
  closeCompany: () => void;
  radar: {
    filters: RadarFilters;
    setFilters: (filters: RadarFilters) => void;
    sort: RadarSort;
    setSort: (sort: RadarSort) => void;
  };
}

export const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const value = useContext(AppContext);
  if (value === null) throw new Error('useApp must be used inside <App>.');
  return value;
}

/** The loaded workspace; screens are only rendered once one exists. */
export function useWorkspace(): Workspace {
  const { state } = useApp();
  if (state.workspace === null) throw new Error('No workspace is loaded.');
  return state.workspace;
}
