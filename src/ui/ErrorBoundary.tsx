import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Last line of defence: without it, one exception while drawing a screen unmounts the whole tree
 * and the page goes blank with no explanation. Stored data is never touched by rendering, so the
 * message can say truthfully that nothing was lost.
 */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Keep a trace for whoever opens the console; nothing is sent anywhere.
    console.error('RecruitRadar failed to draw a screen:', error, info.componentStack);
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (error === null) return this.props.children;
    return (
      <main className="shell" role="alert" data-testid="render-error">
        <div className="card stack">
          <h1>Something went wrong</h1>
          <p>
            RecruitRadar hit an unexpected error while drawing this screen. Nothing you stored was
            changed: your data is kept separately, in this browser or in the backend. Reload the
            page to try again.
          </p>
          <p className="small muted">
            If it fails again straight after reloading, the stored data itself may be the cause; in
            local-data mode clearing this site&apos;s data in your browser settings starts over
            (that deletes the stored datasets). The technical message below is what to report.
          </p>
          <pre className="small">{error.message === '' ? error.name : error.message}</pre>
          <div>
            <button type="button" className="btn btn--primary" onClick={() => location.reload()}>
              Reload the page
            </button>
          </div>
        </div>
      </main>
    );
  }
}
