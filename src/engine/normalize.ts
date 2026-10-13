/**
 * Text normalization and key derivation (spec 01 §2).
 *
 * Every operation here is code-point correct: strings are compared, counted and sorted by Unicode
 * code point (never by UTF-16 code unit) so this module agrees with the Python engine, whose
 * `str` comparison and `len` are code-point based.
 */

// ---------------------------------------------------------------------------------------------
// Code-point helpers
// ---------------------------------------------------------------------------------------------

/**
 * True for the characters Python's `str.isspace()` treats as whitespace. "Strings are trimmed"
 * (spec 01 §1) is defined as stripping exactly this set, so both engines trim identically.
 * (JS `trim()` differs: it also strips U+FEFF and keeps U+001C..U+001F and U+0085.)
 */
export function isSpecWhitespace(codeUnit: number): boolean {
  return (
    (codeUnit >= 0x09 && codeUnit <= 0x0d) ||
    (codeUnit >= 0x1c && codeUnit <= 0x20) ||
    codeUnit === 0x85 ||
    codeUnit === 0xa0 ||
    codeUnit === 0x1680 ||
    (codeUnit >= 0x2000 && codeUnit <= 0x200a) ||
    codeUnit === 0x2028 ||
    codeUnit === 0x2029 ||
    codeUnit === 0x202f ||
    codeUnit === 0x205f ||
    codeUnit === 0x3000
  );
}

/** Strip leading and trailing whitespace (see {@link isSpecWhitespace}). */
export function trimText(text: string): string {
  let start = 0;
  let end = text.length;
  while (start < end && isSpecWhitespace(text.charCodeAt(start))) start += 1;
  while (end > start && isSpecWhitespace(text.charCodeAt(end - 1))) end -= 1;
  return start === 0 && end === text.length ? text : text.slice(start, end);
}

/** Number of Unicode code points in `text`. */
export function codePointLength(text: string): number {
  let count = 0;
  for (let i = 0; i < text.length; i += 1) {
    const unit = text.charCodeAt(i);
    if (unit >= 0xd800 && unit <= 0xdbff && i + 1 < text.length) {
      const next = text.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) i += 1;
    }
    count += 1;
  }
  return count;
}

/** Compare two strings by Unicode code point (not UTF-16 code unit). Returns -1, 0 or 1. */
export function compareCodePoints(a: string, b: string): number {
  if (a === b) return 0;
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    const ca = a.codePointAt(i) ?? 0;
    const cb = b.codePointAt(j) ?? 0;
    if (ca !== cb) return ca < cb ? -1 : 1;
    const width = ca > 0xffff ? 2 : 1;
    i += width;
    j += width;
  }
  if (i < a.length) return 1;
  if (j < b.length) return -1;
  return 0;
}

/** Sort a copy of `values` ascending by code point. */
export function sortCodePoints(values: Iterable<string>): string[] {
  return Array.from(values).sort(compareCodePoints);
}

// ---------------------------------------------------------------------------------------------
// norm_text and the keys built on it
// ---------------------------------------------------------------------------------------------

/** Code points whose general category does not start with L, N or M. */
const NOT_LETTER_NUMBER_MARK = /[^\p{L}\p{N}\p{M}]/gu;

/**
 * `norm_text(s)`: NFKC, default lowercase, every non-L/N/M code point to a space, whitespace
 * collapsed. Returned as tokens; `normText` joins them.
 */
export function normTokens(text: string): string[] {
  const folded = text.normalize('NFKC').toLowerCase().replace(NOT_LETTER_NUMBER_MARK, ' ');
  const tokens: string[] = [];
  for (const token of folded.split(' ')) {
    if (token.length > 0) tokens.push(token);
  }
  return tokens;
}

export function normText(text: string): string {
  return normTokens(text).join(' ');
}

const LEGAL_SUFFIXES: ReadonlySet<string> = new Set([
  'inc',
  'incorporated',
  'llc',
  'ltd',
  'limited',
  'corp',
  'corporation',
  'co',
  'company',
  'gmbh',
  'plc',
  'ag',
  'sa',
  'bv',
  'nv',
  'llp',
  'lp',
  'pte',
  'pty',
]);

/**
 * `company_key(name)`: drop trailing legal-suffix tokens (repeatedly), then one leading `the`;
 * if that would leave nothing, keep the original tokens.
 */
export function companyKey(name: string): string {
  const original = normTokens(name);
  const tokens = original.slice();
  for (;;) {
    const last = tokens[tokens.length - 1];
    if (last === undefined || !LEGAL_SUFFIXES.has(last)) break;
    tokens.pop();
  }
  if (tokens[0] === 'the') tokens.shift();
  return (tokens.length === 0 ? original : tokens).join(' ');
}

const PARENTHESIZED = /\([^()]*\)/gu;
const BRACKETED = /\[[^[\]]*\]/gu;

/**
 * `title_key(title)`: repeatedly remove `(…)` and `[…]` segments (innermost first, until none
 * remain), then `norm_text`. Segments are removed outright, not replaced by a space.
 */
export function titleKey(title: string): string {
  let current = title;
  for (;;) {
    const next = current.replace(PARENTHESIZED, '').replace(BRACKETED, '');
    if (next === current) break;
    current = next;
  }
  return normText(current);
}

/** `location_key(loc)`: unique `norm_text` tokens, sorted by code point, joined by one space. */
export function locationKey(location: string | null | undefined): string {
  const tokens = new Set(normTokens(location ?? ''));
  return sortCodePoints(tokens).join(' ');
}

/** True when `needle` appears as a contiguous run inside `haystack` (both token arrays). */
export function containsTokenSequence(
  haystack: readonly string[],
  needle: readonly string[],
): boolean {
  if (needle.length === 0 || needle.length > haystack.length) return false;
  const last = haystack.length - needle.length;
  for (let start = 0; start <= last; start += 1) {
    let matched = true;
    for (let offset = 0; offset < needle.length; offset += 1) {
      if (haystack[start + offset] !== needle[offset]) {
        matched = false;
        break;
      }
    }
    if (matched) return true;
  }
  return false;
}

/**
 * `token_sequence_match(title_key, phrase)`: the tokens of `norm_text(phrase)` (non-empty) appear
 * as a contiguous sub-sequence of the tokens of `titleKeyValue`.
 */
export function tokenSequenceMatch(titleKeyValue: string, phrase: string): boolean {
  const phraseTokens = normTokens(phrase);
  if (phraseTokens.length === 0) return false;
  const titleTokens = titleKeyValue.split(' ').filter((token) => token.length > 0);
  return containsTokenSequence(titleTokens, phraseTokens);
}
