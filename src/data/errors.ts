/**
 * One error type for everything an `AnalysisSource` can refuse or fail at, so the UI can show a
 * specific, honest message and decide whether a retry makes sense.
 */
export type SourceErrorKind =
  /** Nothing answered (backend not running, or the browser blocked the request). */
  | 'offline'
  /** The backend answered, but the browser would not let this origin read the response. */
  | 'cors'
  | 'timeout'
  /** A 2xx response that is not valid JSON, or does not match the documented shape. */
  | 'bad_response'
  /** The backend returned the documented error envelope. */
  | 'api'
  /** A non-2xx response without the envelope. */
  | 'http'
  /** The operation does not exist in this mode (e.g. ATS refresh in local mode). */
  | 'unavailable'
  /** The input was refused before anything was stored. */
  | 'invalid_input'
  | 'not_found'
  /** A documented size cap would be exceeded. */
  | 'limit'
  | 'storage_full'
  | 'storage_unavailable'
  /** Browser data was written by a newer schema; this version will not overwrite it. */
  | 'read_only';

export interface SourceErrorInit {
  code?: string | null;
  status?: number | null;
  details?: unknown;
  retryAfterSeconds?: number | null;
  cause?: unknown;
}

export class SourceError extends Error {
  readonly kind: SourceErrorKind;
  /** Backend error code (`snake_case`), when the envelope carried one. */
  readonly code: string | null;
  readonly status: number | null;
  readonly details: unknown;
  readonly retryAfterSeconds: number | null;

  constructor(kind: SourceErrorKind, message: string, init: SourceErrorInit = {}) {
    super(message, init.cause === undefined ? undefined : { cause: init.cause });
    this.name = 'SourceError';
    this.kind = kind;
    this.code = init.code ?? null;
    this.status = init.status ?? null;
    this.details = init.details ?? null;
    this.retryAfterSeconds = init.retryAfterSeconds ?? null;
  }

  /** True when the backend could not be reached at all (as opposed to refusing a request). */
  get isConnectivity(): boolean {
    return this.kind === 'offline' || this.kind === 'cors' || this.kind === 'timeout';
  }
}

export function isSourceError(value: unknown): value is SourceError {
  return value instanceof SourceError;
}

/** A user-presentable message for anything thrown by a source call. */
export function describeError(error: unknown): string {
  if (error instanceof SourceError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Something went wrong.';
}
