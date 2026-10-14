"""Posting cleaning and the identity keys stored next to each observation (spec 01 sections 1-2).

This is the backend's own implementation. The analysis engine re-derives every key from the raw
fields it is given, so the keys stored here are an index for the database, never an input to
the engine. ``tests/test_normalization.py`` pins this module to the examples in the spec.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from .clock import is_valid_date

WORK_MODES: Final = ("remote", "hybrid", "onsite", "unknown")

LEGAL_SUFFIXES: Final = frozenset(
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

# What String.prototype.trim() removes. The TypeScript engine can only trim this way, so the
# whole product trims with this set (not Python's str.strip()).
_TRIM_CHARS: Final = "".join(
    chr(code_point)
    for code_point in (
        0x0009,
        0x000A,
        0x000B,
        0x000C,
        0x000D,
        0x0020,
        0x00A0,
        0x1680,
        *range(0x2000, 0x200B),
        0x2028,
        0x2029,
        0x202F,
        0x205F,
        0x3000,
        0xFEFF,
    )
)

#: The characters ``trim`` strips (public: the CSV header normalizer maps them to ``_``).
WHITESPACE_CHARS: Final = _TRIM_CHARS

_PAREN_SEGMENT: Final = re.compile(r"\([^()]*\)")
_BRACKET_SEGMENT: Final = re.compile(r"\[[^\[\]]*\]")
_HTTP_SCHEME: Final = re.compile(r"https?:", re.IGNORECASE | re.ASCII)

MAX_COMPANY_NAME: Final = 200
MAX_TITLE: Final = 300
MAX_LOCATION: Final = 300
MAX_DEPARTMENT: Final = 200


def trim(value: str) -> str:
    return value.strip(_TRIM_CHARS)


def norm_text(value: str) -> str:
    """NFKC, lowercase, every non letter/number/mark code point becomes a space, collapse."""
    lowered = unicodedata.normalize("NFKC", value).lower()
    replaced = "".join(ch if unicodedata.category(ch)[0] in "LNM" else " " for ch in lowered)
    return " ".join(token for token in replaced.split(" ") if token)


def _tokens(value: str) -> list[str]:
    text = norm_text(value)
    return text.split(" ") if text else []


def company_key(name: str) -> str:
    original = _tokens(name)
    kept = list(original)
    while kept and kept[-1] in LEGAL_SUFFIXES:
        kept.pop()
    if kept and kept[0] == "the":
        kept.pop(0)
    return " ".join(kept or original)


def title_key(title: str) -> str:
    text = title
    while True:
        stripped = _BRACKET_SEGMENT.sub("", _PAREN_SEGMENT.sub("", text))
        if stripped == text:
            break
        text = stripped
    return norm_text(text)


def location_key(location: str | None) -> str:
    return " ".join(sorted(set(_tokens(location or ""))))


def sha12(value: str) -> str:
    try:
        data = value.encode("utf-8")
    except UnicodeEncodeError:
        data = value.encode("utf-16", "surrogatepass").decode("utf-16", "replace").encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:12]


def has_http_scheme(value: str) -> bool:
    return _HTTP_SCHEME.match(value) is not None


def _is_storable(value: str) -> bool:
    """False for text SQLite cannot store: lone surrogates have no UTF-8 encoding.

    A provider can send one (``"\\ud800"`` is valid JSON). Such a field is treated as invalid
    text instead of failing the whole refresh at the database.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


# ---------------------------------------------------------------------------------------------
# Posting cleaning
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CleanPosting:
    """A RawPosting (spec 01 section 1) minus its source fields, trimmed and validated."""

    source_posting_id: str | None
    company_name: str
    title: str
    location: str | None
    work_mode: str
    department: str | None
    url: str | None
    posted_at: str | None

    @property
    def company_key(self) -> str:
        return company_key(self.company_name)

    @property
    def title_key(self) -> str:
        return title_key(self.title)

    @property
    def location_key(self) -> str:
        return location_key(self.location)

    def role_key(self) -> tuple[str, ...]:
        """Identity of the role inside one source (spec 01 section 4), without the source."""
        if self.source_posting_id is not None:
            return ("id", self.source_posting_id)
        return ("k", self.company_key, self.title_key, self.location_key)


@dataclass(frozen=True, slots=True)
class FieldProblem:
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class CleanResult:
    posting: CleanPosting | None
    problems: tuple[FieldProblem, ...]
    # Optional fields that were invalid and set to null (only in lenient mode).
    omitted: tuple[FieldProblem, ...] = ()


class _Cleaner:
    def __init__(self, raw: Mapping[str, object], lenient: bool) -> None:
        self.raw = raw
        self.lenient = lenient
        self.problems: list[FieldProblem] = []
        self.omitted: list[FieldProblem] = []

    def _read(self, name: str) -> tuple[str | None, bool]:
        """Trimmed text of ``name`` ("" and absent become ``None``); ``ok`` False if not text."""
        value = self.raw.get(name)
        if value is None:
            return None, True
        if not isinstance(value, str) or not _is_storable(value):
            return None, False
        return trim(value) or None, True

    def _fail(self, name: str, message: str, *, optional: bool) -> None:
        problem = FieldProblem(name, message)
        if optional and self.lenient:
            self.omitted.append(problem)
        else:
            self.problems.append(problem)

    def required(self, name: str, max_len: int) -> str:
        text, ok = self._read(name)
        if not ok:
            self._fail(name, f"{name} must be text", optional=False)
            return ""
        if text is None:
            self._fail(name, f"{name} is required", optional=False)
            return ""
        if len(text) > max_len:
            self._fail(
                name,
                f"{name} must be at most {max_len} characters (got {len(text)})",
                optional=False,
            )
            return ""
        return text

    def optional(self, name: str, max_len: int | None = None) -> str | None:
        text, ok = self._read(name)
        if not ok:
            self._fail(name, f"{name} must be text", optional=True)
            return None
        if text is not None and max_len is not None and len(text) > max_len:
            self._fail(
                name,
                f"{name} must be at most {max_len} characters (got {len(text)})",
                optional=True,
            )
            return None
        return text

    def work_mode(self) -> str:
        text, ok = self._read("work_mode")
        if not ok:
            self._fail("work_mode", "work_mode must be text", optional=True)
            return "unknown"
        if text is None:
            return "unknown"
        if text not in WORK_MODES:
            self._fail(
                "work_mode",
                f"work_mode must be one of {', '.join(WORK_MODES)} (lower case), got {text!r}",
                optional=True,
            )
            return "unknown"
        return text

    def url(self) -> str | None:
        text = self.optional("url")
        if text is not None and not has_http_scheme(text):
            self._fail("url", "url must start with http: or https:", optional=True)
            return None
        return text

    def posted_at(self) -> str | None:
        text = self.optional("posted_at")
        if text is not None and not is_valid_date(text):
            self._fail("posted_at", "posted_at must be a real YYYY-MM-DD date", optional=True)
            return None
        return text


def clean_posting(raw: Mapping[str, object], *, lenient: bool = False) -> CleanResult:
    """Validate and trim one posting.

    Strict mode (CSV rows, manual entry): any invalid field is a problem. Lenient mode (provider
    payloads): only a missing/invalid *required* field is a problem; an invalid optional field is
    set to null (``unknown`` for ``work_mode``) and reported in ``omitted``.
    """
    cleaner = _Cleaner(raw, lenient)
    posting_id = cleaner.optional("source_posting_id")
    company = cleaner.required("company_name", MAX_COMPANY_NAME)
    title = cleaner.required("title", MAX_TITLE)
    location = cleaner.optional("location", MAX_LOCATION)
    work_mode = cleaner.work_mode()
    department = cleaner.optional("department", MAX_DEPARTMENT)
    url = cleaner.url()
    posted_at = cleaner.posted_at()
    if cleaner.problems:
        return CleanResult(None, tuple(cleaner.problems), tuple(cleaner.omitted))
    return CleanResult(
        CleanPosting(
            source_posting_id=posting_id,
            company_name=company,
            title=title,
            location=location,
            work_mode=work_mode,
            department=department,
            url=url,
            posted_at=posted_at,
        ),
        (),
        tuple(cleaner.omitted),
    )
