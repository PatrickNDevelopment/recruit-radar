"""Text normalization primitives (spec 01 section 2).

All functions here are pure and total. They are re-implemented independently in TypeScript and
must agree on every golden vector, so each one follows the spec wording literally.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from typing import Final

LEGAL_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "co",
        "company",
        "gmbh",
        "plc",
        "ag",
        "sa",
        "bv",
        "nv",
        "llp",
        "lp",
        "pte",
        "pty",
    }
)

# ECMAScript WhiteSpace + LineTerminator, i.e. exactly what String.prototype.trim() removes.
# Python's str.strip() differs (it strips U+001C..U+001F and U+0085, and does not strip U+FEFF),
# and the TypeScript engine trims with trim(), so this set is the one both engines share.
_JS_WHITESPACE: Final = "".join(
    chr(code_point)
    for code_point in (
        0x0009,  # tab
        0x000A,  # line feed
        0x000B,  # vertical tab
        0x000C,  # form feed
        0x000D,  # carriage return
        0x0020,  # space
        0x00A0,  # no-break space
        0x1680,  # ogham space mark
        *range(0x2000, 0x200B),  # en quad .. hair space
        0x2028,  # line separator
        0x2029,  # paragraph separator
        0x202F,  # narrow no-break space
        0x205F,  # medium mathematical space
        0x3000,  # ideographic space
        0xFEFF,  # zero width no-break space (byte order mark)
    )
)

_KEPT_CATEGORIES: Final = frozenset("LNM")
_PAREN_SEGMENT: Final = re.compile(r"\([^()]*\)")
_BRACKET_SEGMENT: Final = re.compile(r"\[[^\[\]]*\]")


def trim(value: str) -> str:
    """Strip leading and trailing whitespace the way ``String.prototype.trim`` does."""
    return value.strip(_JS_WHITESPACE)


def norm_text(s: str) -> str:
    """NFKC, lowercase, non letter/number/mark code points become spaces, collapse spaces.

    Steps (spec 01 section 2): (1) Unicode NFKC; (2) default (non-locale) lowercasing;
    (3) every code point whose general category does not start with ``L``, ``N`` or ``M`` is
    replaced by one space; (4) split on whitespace, drop empties, join with one space.
    """
    lowered = unicodedata.normalize("NFKC", s).lower()
    replaced = "".join(
        ch if unicodedata.category(ch)[0] in _KEPT_CATEGORIES else " " for ch in lowered
    )
    # Every remaining non-letter/number/mark code point is already a plain U+0020.
    return " ".join(token for token in replaced.split(" ") if token)


def tokens(s: str) -> list[str]:
    """Tokens of ``norm_text(s)`` (empty list when the normalized text is empty)."""
    return [token for token in norm_text(s).split(" ") if token]


def company_key(name: str) -> str:
    """Normalized company identity key (spec 01 section 2).

    Repeatedly drops a trailing legal-suffix token, then drops a single leading ``the``. When
    that would leave nothing, the original token list is used instead.
    """
    original = tokens(name)
    kept = list(original)
    while kept and kept[-1] in LEGAL_SUFFIXES:
        kept.pop()
    if kept and kept[0] == "the":
        kept.pop(0)
    if not kept:
        kept = original
    return " ".join(kept)


def title_key(title: str) -> str:
    """Role-title key: parenthesised and bracketed segments removed, then ``norm_text``.

    Segments are deleted (replaced by nothing) and the removal is repeated until neither
    ``\\([^()]*\\)`` nor ``\\[[^\\[\\]]*\\]`` matches any more, so nested segments disappear too.
    """
    text = title
    while True:
        stripped = _BRACKET_SEGMENT.sub("", _PAREN_SEGMENT.sub("", text))
        if stripped == text:
            break
        text = stripped
    return norm_text(text)


def location_key(loc: str | None) -> str:
    """Order-insensitive location key: unique tokens, ascending by code point, space-joined."""
    return " ".join(sorted(set(tokens(loc or ""))))


def contains_token_sequence(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    """True iff ``needle`` is non-empty and appears contiguously inside ``haystack``."""
    width = len(needle)
    if width == 0:
        return False
    first = needle[0]
    for start in range(len(haystack) - width + 1):
        if haystack[start] == first and list(haystack[start : start + width]) == list(needle):
            return True
    return False


def token_sequence_match(title_key: str, phrase: str) -> bool:
    """True iff the normalized ``phrase`` is a contiguous token run of ``title_key``.

    ``title_key`` is expected to be an already normalized key (space separated tokens). A phrase
    that normalizes to the empty string never matches.
    """
    return contains_token_sequence(title_key.split(" "), tokens(phrase))


def sha12(s: str) -> str:
    """First 12 lowercase hex characters of the SHA-256 of the UTF-8 bytes of ``s``.

    Lone surrogates (which no UTF-8 encoder may emit) become U+FFFD, the same replacement
    ``TextEncoder`` and Node's ``Buffer.from(str, "utf8")`` apply, so both engines hash the
    same bytes even for degenerate input.
    """
    try:
        data = s.encode("utf-8")
    except UnicodeEncodeError:
        data = s.encode("utf-16", "surrogatepass").decode("utf-16", "replace").encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:12]


def levenshtein(a: str, b: str) -> int:
    """Classic edit distance (insert, delete, substitute; each cost 1) over code points."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (0 if ca == cb else 1),  # substitution
                )
            )
        previous = current
    return previous[-1]
