import { useSyncExternalStore } from 'react';
import type { SessionState, SessionStore } from '../data/session';

/** Subscribe a component to the session store. The snapshot only changes identity on change. */
export function useSession(store: SessionStore): SessionState {
  return useSyncExternalStore(store.subscribe, store.getState, store.getState);
}
