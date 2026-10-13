import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { sha12, sha256Bytes, sha256Hex, utf8Encode } from '../src/engine/sha256';
import { mulberry32 } from './helpers';

const nodeSha = (text: string): string => createHash('sha256').update(text, 'utf8').digest('hex');

describe('sha256Hex — NIST vectors', () => {
  it('hashes "abc"', () => {
    expect(sha256Hex('abc')).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    );
  });

  it('hashes the empty string', () => {
    expect(sha256Hex('')).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
  });

  it('hashes the 448-bit two-block message', () => {
    expect(sha256Hex('abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq')).toBe(
      '248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1',
    );
  });

  it('hashes the 896-bit message', () => {
    const message =
      'abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu';
    expect(sha256Hex(message)).toBe(
      'cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1',
    );
  });

  it('hashes one million "a" characters', () => {
    expect(sha256Hex('a'.repeat(1_000_000))).toBe(
      'cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0',
    );
  });
});

describe('sha256Hex — unicode and padding boundaries', () => {
  const samples = [
    'é',
    'Zoë Müller GmbH',
    '日本語のテキスト',
    '😀',
    'a😀b',
    '\u0000',
    'mixed ß ǅ ﬁ İ ʻ',
    '\u{10FFFF}',
  ];
  it.each(samples)('matches node:crypto for %j', (text) => {
    expect(sha256Hex(text)).toBe(nodeSha(text));
  });

  it('matches node:crypto across every length around the 55/56/63/64-byte padding edges', () => {
    for (let length = 0; length <= 200; length += 1) {
      const text = 'x'.repeat(length);
      expect(sha256Hex(text)).toBe(nodeSha(text));
    }
  });

  it('matches node:crypto on 300 seeded random unicode strings', () => {
    const random = mulberry32(20261013);
    const alphabet = Array.from('abcXYZ 019_-éüßñ日本語한국어😀𐐀́\u{1F600}\u{20000}');
    for (let i = 0; i < 300; i += 1) {
      const length = Math.floor(random() * 120);
      let text = '';
      for (let k = 0; k < length; k += 1) {
        text += alphabet[Math.floor(random() * alphabet.length)] ?? '';
      }
      expect(sha256Hex(text)).toBe(nodeSha(text));
    }
  });
});

describe('sha12 and utf8Encode', () => {
  it('sha12 is the first 12 hex characters', () => {
    expect(sha12('abc')).toBe('ba7816bf8f01');
    expect(sha12('abc')).toHaveLength(12);
  });

  it('utf8Encode matches TextEncoder, including lone surrogates', () => {
    const encoder = new TextEncoder();
    for (const text of ['', 'abc', 'é', '日本', '😀', 'a\ud800b', '\udc00', 'x\ud83d']) {
      expect(Array.from(utf8Encode(text))).toEqual(Array.from(encoder.encode(text)));
    }
  });

  it('sha256Bytes digests raw bytes', () => {
    const digest = sha256Bytes(Uint8Array.from([0x61, 0x62, 0x63]));
    expect(Buffer.from(digest).toString('hex')).toBe(nodeSha('abc'));
  });
});
