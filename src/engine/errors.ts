/** One validation problem, located by a JSON-ish path such as `snapshots[0].postings[2].url`. */
export interface InputIssue {
  path: string;
  message: string;
}

/**
 * Thrown by `analyze()` when its input violates the contract of spec 01/02. It is a typed,
 * recoverable error: nothing about the engine's state is left half-updated because `analyze` is
 * a pure function that validates before it computes.
 */
export class EngineInputError extends Error {
  readonly issues: readonly InputIssue[];

  constructor(issues: readonly InputIssue[]) {
    const first = issues[0];
    const head =
      first === undefined
        ? 'Invalid analyze() input'
        : `Invalid analyze() input: ${first.path === '' ? '(root)' : first.path}: ${first.message}`;
    const rest = issues.length > 1 ? ` (and ${issues.length - 1} more)` : '';
    super(head + rest);
    this.name = 'EngineInputError';
    this.issues = issues;
  }
}

/** Render a Zod issue path (`PropertyKey[]`) as `a.b[0].c`. */
export function formatPath(path: readonly PropertyKey[]): string {
  let out = '';
  for (const segment of path) {
    if (typeof segment === 'number') out += `[${segment}]`;
    else out += out === '' ? String(segment) : `.${String(segment)}`;
  }
  return out;
}
