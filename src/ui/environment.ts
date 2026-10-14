/** The few browser facts the app needs, read defensively (they may be missing in tests). */

export function pageHostname(): string | null {
  try {
    const host = globalThis.location?.hostname;
    return typeof host === 'string' && host !== '' ? host : null;
  } catch {
    return null;
  }
}
