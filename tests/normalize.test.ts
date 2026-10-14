import { describe, expect, it } from 'vitest';
import {
  codePointLength,
  companyKey,
  compareCodePoints,
  containsTokenSequence,
  locationKey,
  normText,
  sortCodePoints,
  titleKey,
  tokenSequenceMatch,
  trimText,
} from '../src/engine/normalize';
import { mulberry32 } from './helpers';

describe('normText', () => {
  it('lowercases, drops punctuation and collapses whitespace', () => {
    expect(normText('  Senior   Software-Engineer, II!  ')).toBe('senior software engineer ii');
  });

  it('applies NFKC before anything else', () => {
    expect(normText('ＡＢＣ\u3000１２３')).toBe('abc 123');
    expect(normText('ﬁnance ①')).toBe('finance 1');
    expect(normText('Ⅻ')).toBe('xii');
    expect(normText('école')).toBe('école'); // composed to é
  });

  it('keeps letters, numbers and marks of every script; replaces everything else', () => {
    expect(normText('日本語-テキスト')).toBe('日本語 テキスト');
    expect(normText('AT&T')).toBe('at t');
    expect(normText("O'Brien_&_Co")).toBe('o brien co');
    expect(normText('c++ / c# \u{1F600} dev')).toBe('c c dev');
    expect(normText('नमस्ते')).toBe('नमस्ते'); // combining marks (M) are kept
  });

  it('uses the default, non-locale lowercase (İ becomes i + combining dot)', () => {
    expect(normText('İstanbul')).toBe('i̇stanbul');
    expect(normText('ΟΔΟΣ')).toBe('οδος'); // final sigma handled by default casing
  });

  it('returns "" for input without letters, numbers or marks', () => {
    expect(normText('')).toBe('');
    expect(normText(' - ! ? ')).toBe('');
    expect(normText('\u{1F600}')).toBe('');
  });

  it('treats a lone surrogate as a non-letter', () => {
    expect(normText('a\ud800b')).toBe('a b');
  });
});

describe('companyKey', () => {
  it.each([
    ['Acme, Inc.', 'acme'],
    ['The Acme Corporation', 'acme'],
    ['Inc', 'inc'],
    ['AT&T', 'at t'],
    ['Acme', 'acme'],
    ['ACME Inc.', 'acme'],
    ['acme, inc', 'acme'],
  ])('%j -> %j (spec 01 examples)', (name, key) => {
    expect(companyKey(name)).toBe(key);
  });

  it('drops legal suffixes repeatedly and only from the end', () => {
    expect(companyKey('Acme Co. Ltd.')).toBe('acme');
    expect(companyKey('Acme Company LLC')).toBe('acme');
    expect(companyKey('Inc Acme')).toBe('inc acme');
    expect(companyKey('Gmbh Acme GmbH')).toBe('gmbh acme');
    expect(companyKey('Acme Holdings Pte Ltd')).toBe('acme holdings');
  });

  it('drops a single leading "the" after the suffixes', () => {
    expect(companyKey('The The')).toBe('the');
    expect(companyKey('The Acme')).toBe('acme');
    expect(companyKey('Acme The')).toBe('acme the');
  });

  it('falls back to the original tokens when stripping would leave nothing', () => {
    expect(companyKey('Co')).toBe('co');
    expect(companyKey('The Inc')).toBe('the inc');
    expect(companyKey('Inc. Co. Ltd.')).toBe('inc co ltd');
    expect(companyKey('The')).toBe('the');
  });

  it('is "" for a name with no letters or digits', () => {
    expect(companyKey('!!!')).toBe('');
  });
});

describe('titleKey', () => {
  it('removes parenthesised and bracketed segments', () => {
    expect(titleKey('Senior Engineer (Remote) [US]')).toBe('senior engineer');
    expect(titleKey('[Hybrid] Staff SWE (Platform)')).toBe('staff swe');
  });

  it('removes nested segments until none remain', () => {
    expect(titleKey('Engineer (Platform (Core))')).toBe('engineer');
    expect(titleKey('Engineer [Team [Core]] (L5 (Staff))')).toBe('engineer');
    expect(titleKey('Engineer ([a] b)')).toBe('engineer');
  });

  it('leaves unbalanced brackets in place (they normalize to spaces)', () => {
    expect(titleKey('Engineer (Remote')).toBe('engineer remote');
    expect(titleKey('Engineer Remote)')).toBe('engineer remote');
  });

  it('removes a segment outright rather than replacing it with a space', () => {
    expect(titleKey('Foo(bar)Baz')).toBe('foobaz');
  });
});

describe('locationKey', () => {
  it('makes word order and punctuation irrelevant (spec 01 example)', () => {
    expect(locationKey('New York, NY')).toBe('new ny york');
    expect(locationKey('NY - New York')).toBe('new ny york');
  });

  it('is "" for null, empty and punctuation-only locations', () => {
    expect(locationKey(null)).toBe('');
    expect(locationKey('')).toBe('');
    expect(locationKey(' - ')).toBe('');
  });

  it('keeps unique tokens only', () => {
    expect(locationKey('Berlin Berlin, Germany')).toBe('berlin germany');
  });

  it('sorts by code point, not by UTF-16 code unit', () => {
    // U+20000 is a surrogate pair (starts 0xD840) and U+FE0F is a single unit above it.
    const key = locationKey('\u{20000} ️ a');
    expect(key).toBe('a ️ \u{20000}');
    expect(['\u{20000}', '️'].sort()).toEqual(['\u{20000}', '️']); // naive sort differs
  });
});

describe('tokenSequenceMatch / containsTokenSequence', () => {
  it('requires a contiguous run of whole tokens', () => {
    expect(tokenSequenceMatch('senior software engineer ii', 'software engineer')).toBe(true);
    expect(tokenSequenceMatch('senior software engineer ii', 'engineer software')).toBe(false);
    expect(tokenSequenceMatch('senior software engineer ii', 'senior engineer')).toBe(false);
  });

  it('matches tokens, not substrings', () => {
    expect(tokenSequenceMatch('engineering manager', 'engineer')).toBe(false);
    expect(tokenSequenceMatch('reengineer', 'engineer')).toBe(false);
    expect(tokenSequenceMatch('engineer', 'engineer')).toBe(true);
  });

  it('normalizes the phrase and never matches an empty phrase', () => {
    expect(tokenSequenceMatch('senior engineer', '  ENGINEER! ')).toBe(true);
    expect(tokenSequenceMatch('senior engineer', '')).toBe(false);
    expect(tokenSequenceMatch('senior engineer', '---')).toBe(false);
    expect(tokenSequenceMatch('', 'engineer')).toBe(false);
  });

  it('containsTokenSequence handles the edges', () => {
    expect(containsTokenSequence(['a', 'b'], [])).toBe(false);
    expect(containsTokenSequence(['a'], ['a', 'b'])).toBe(false);
    expect(containsTokenSequence(['a', 'b', 'c'], ['b', 'c'])).toBe(true);
    expect(containsTokenSequence(['a', 'b', 'c'], ['a', 'c'])).toBe(false);
  });
});

describe('code-point helpers', () => {
  it('trimText strips exactly the ECMAScript WhiteSpace + LineTerminator set', () => {
    // docs/spec/ambiguities/differential.md D-1: the set String.prototype.trim() removes, written
    // out as a table; the Python engine carries the identical one (its str.strip() differs).
    expect(trimText('  \t\n x y \u00a0\u3000')).toBe('x y');
    expect(trimText('\u0085x\u2028')).toBe('\u0085x');
    expect(trimText('\u001c\u001dx\u001f')).toBe('\u001c\u001dx\u001f');
    // A BOM is tolerated (spec 05), so U+FEFF is whitespace for trimming.
    expect(trimText('\ufeffx\ufeff')).toBe('x');
    expect(trimText('a  b')).toBe('a  b');
    expect(trimText('   ')).toBe('');
  });

  it('trimText agrees with String.prototype.trim for every code unit', () => {
    for (let unit = 0; unit <= 0xffff; unit += 1) {
      if (unit >= 0xd800 && unit <= 0xdfff) continue;
      const text = `${String.fromCharCode(unit)}x${String.fromCharCode(unit)}`;
      expect(trimText(text) === 'x', `U+${unit.toString(16).padStart(4, '0')}`).toBe(
        text.trim() === 'x',
      );
    }
  });

  it('codePointLength counts astral characters once', () => {
    expect(codePointLength('abc')).toBe(3);
    expect(codePointLength('a😀b')).toBe(3);
    expect(codePointLength('\u{20000}\u{20001}')).toBe(2);
    expect(codePointLength('a\ud800')).toBe(2);
    expect(codePointLength('')).toBe(0);
  });

  it('compareCodePoints orders by code point', () => {
    expect(compareCodePoints('a', 'b')).toBe(-1);
    expect(compareCodePoints('b', 'a')).toBe(1);
    expect(compareCodePoints('a', 'a')).toBe(0);
    expect(compareCodePoints('a', 'ab')).toBe(-1);
    expect(compareCodePoints('ab', 'a')).toBe(1);
    // astral vs BMP-above-surrogates: code-point order differs from UTF-16 order.
    expect(compareCodePoints('\u{10000}', '￿')).toBe(1);
    expect('\u{10000}' < '￿').toBe(true);
  });

  it('compareCodePoints is a consistent total order on random strings', () => {
    const random = mulberry32(7);
    const alphabet = Array.from('abé️￿\u{10000}\u{20000}\u{1F600}');
    const make = (): string => {
      let text = '';
      const length = Math.floor(random() * 4);
      for (let i = 0; i < length; i += 1) {
        text += alphabet[Math.floor(random() * alphabet.length)] ?? '';
      }
      return text;
    };
    const asPoints = (text: string): number[] => Array.from(text, (c) => c.codePointAt(0) ?? 0);
    for (let i = 0; i < 500; i += 1) {
      const a = make();
      const b = make();
      const pa = asPoints(a);
      const pb = asPoints(b);
      let expected = 0;
      for (let k = 0; k < Math.min(pa.length, pb.length) && expected === 0; k += 1) {
        expected = Math.sign((pa[k] ?? 0) - (pb[k] ?? 0));
      }
      if (expected === 0) expected = Math.sign(pa.length - pb.length);
      expect(compareCodePoints(a, b)).toBe(expected);
    }
  });

  it('sortCodePoints returns a sorted copy', () => {
    const input = ['b', '\u{20000}', 'a', '️'];
    expect(sortCodePoints(input)).toEqual(['a', 'b', '️', '\u{20000}']);
    expect(input).toEqual(['b', '\u{20000}', 'a', '️']);
  });
});
