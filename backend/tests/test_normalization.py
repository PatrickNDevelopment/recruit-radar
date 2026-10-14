"""The backend's own normalization and posting cleaning, pinned to the spec 01 examples."""

from __future__ import annotations

import pytest

from recruit_radar.normalization import (
    clean_posting,
    company_key,
    has_http_scheme,
    location_key,
    norm_text,
    sha12,
    title_key,
    trim,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Acme, Inc.", "acme"),
        ("The Acme Corporation", "acme"),
        ("Inc", "inc"),
        ("AT&T", "at t"),
        ("ACME Inc.", "acme"),
        ("acme, inc", "acme"),
        ("Acme Holdings Co. Ltd", "acme holdings"),
        ("The", "the"),
        ("  Door  Dash  ", "door dash"),
        ("DoorDash", "doordash"),
        ("Müller GmbH", "müller"),
        ("", ""),
    ],
)
def test_company_key(raw: str, expected: str) -> None:
    assert company_key(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Senior Engineer (Remote) [US]", "senior engineer"),
        ("Engineer (Backend (Python))", "engineer"),
        ("Staff  Engineer – Data/ML", "staff engineer data ml"),
        ("[Remote] Designer", "designer"),
        ("Engineer ()", "engineer"),
        ("ＳＥＮＩＯＲ Engineer", "senior engineer"),
    ],
)
def test_title_key(raw: str, expected: str) -> None:
    assert title_key(raw) == expected


def test_location_key_is_a_sorted_set_of_tokens() -> None:
    assert location_key("New York, NY") == "new ny york"
    assert location_key("NY - New York") == "new ny york"
    assert location_key(None) == ""
    assert location_key("") == ""
    assert location_key("Remote Remote") == "remote"


def test_norm_text_keeps_letters_numbers_and_marks() -> None:
    assert norm_text("C++ / C#") == "c c"
    assert norm_text("Zoë  Ünal") == "zoë ünal"
    assert norm_text("ﬁnance") == "finance"  # NFKC


def test_sha12_is_the_first_twelve_hex_digits_of_sha256() -> None:
    assert sha12("abc") == "ba7816bf8f01"
    assert len(sha12("")) == 12
    # lone surrogate does not raise (same as TextEncoder: replaced by U+FFFD)
    assert sha12("a\ud800b") == sha12("a�b")


def test_trim_uses_ecmascript_whitespace() -> None:
    assert trim("﻿  x  　") == "x"
    assert trim("\x1fx\x1f") == "\x1fx\x1f"  # U+001F is not ECMAScript whitespace
    assert trim("\x85x") == "\x85x"  # nor is U+0085


def test_has_http_scheme() -> None:
    assert has_http_scheme("https://example.org/a")
    assert has_http_scheme("HTTP://example.org")
    assert not has_http_scheme("ftp://example.org")
    assert not has_http_scheme("javascript:alert(1)")
    assert not has_http_scheme("httpſ://x")  # long s must not pose as the s of https


def _raw(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {"company_name": "Acme", "title": "Engineer"}
    base.update(overrides)
    return base


def test_clean_posting_trims_and_nulls_empty_optionals() -> None:
    result = clean_posting(
        _raw(
            company_name="  Acme  Inc ",
            title="\tEngineer\n",
            location="",
            department="   ",
            url="",
            posted_at="",
            work_mode="",
            source_posting_id="",
        )
    )
    assert result.posting is not None
    posting = result.posting
    assert (posting.company_name, posting.title) == ("Acme  Inc", "Engineer")
    assert posting.location is None
    assert posting.department is None
    assert posting.url is None
    assert posting.posted_at is None
    assert posting.work_mode == "unknown"
    assert posting.source_posting_id is None
    assert posting.role_key() == ("k", "acme", "engineer", "")


def test_role_key_prefers_the_posting_id() -> None:
    result = clean_posting(_raw(source_posting_id="  42 "))
    assert result.posting is not None
    assert result.posting.role_key() == ("id", "42")


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"company_name": ""}, "company_name"),
        ({"company_name": "x" * 201}, "company_name"),
        ({"title": "   "}, "title"),
        ({"title": "t" * 301}, "title"),
        ({"location": "l" * 301}, "location"),
        ({"department": "d" * 201}, "department"),
        ({"work_mode": "Remote"}, "work_mode"),
        ({"work_mode": "office"}, "work_mode"),
        ({"url": "ftp://example.org/x"}, "url"),
        ({"url": "javascript:alert(1)"}, "url"),
        ({"url": "example.org"}, "url"),
        ({"posted_at": "2026-02-30"}, "posted_at"),
        ({"posted_at": "13/10/2026"}, "posted_at"),
        ({"posted_at": "2026-1-5"}, "posted_at"),
        ({"posted_at": "２０２６-10-13"}, "posted_at"),
        ({"title": 7}, "title"),
        ({"location": ["x"]}, "location"),
    ],
)
def test_strict_mode_reports_every_invalid_field(overrides: dict[str, object], field: str) -> None:
    result = clean_posting(_raw(**overrides))
    assert result.posting is None
    assert field in {problem.field for problem in result.problems}


def test_strict_mode_reports_all_problems_at_once() -> None:
    result = clean_posting({"company_name": "", "title": "", "url": "ftp://x", "work_mode": "x"})
    assert {p.field for p in result.problems} == {"company_name", "title", "url", "work_mode"}


def test_missing_required_fields_are_reported() -> None:
    result = clean_posting({})
    assert {p.field for p in result.problems} == {"company_name", "title"}


def test_lenient_mode_nulls_bad_optionals_but_still_rejects_bad_required_fields() -> None:
    result = clean_posting(
        _raw(url="ftp://x", posted_at="nope", work_mode="remoteish", location="l" * 400),
        lenient=True,
    )
    assert result.posting is not None
    assert result.posting.url is None
    assert result.posting.posted_at is None
    assert result.posting.work_mode == "unknown"
    assert result.posting.location is None
    assert {p.field for p in result.omitted} == {"url", "posted_at", "work_mode", "location"}

    dropped = clean_posting(_raw(title=None, url="ftp://x"), lenient=True)
    assert dropped.posting is None
    assert [p.field for p in dropped.problems] == ["title"]


def test_text_that_cannot_be_stored_is_invalid_not_a_crash() -> None:
    result = clean_posting(_raw(title="bad \ud800 title"), lenient=True)
    assert result.posting is None
    assert result.problems[0].field == "title"
    lenient_optional = clean_posting(_raw(location="\udfff"), lenient=True)
    assert lenient_optional.posting is not None
    assert lenient_optional.posting.location is None
