"""Unit tests for normalize.py, written from the spec examples (01 section 2)."""

from __future__ import annotations

import hashlib

import pytest

from recruit_radar.engine.normalize import (
    company_key,
    levenshtein,
    location_key,
    norm_text,
    sha12,
    title_key,
    token_sequence_match,
    tokens,
    trim,
)

# Written with chr() so the source never depends on invisible or escaped characters.
NBSP = chr(0xA0)
ZWSP = chr(0x200B)
BOM = chr(0xFEFF)
IDEOGRAPHIC_SPACE = chr(0x3000)
NEL = chr(0x85)
COMBINING_ACUTE = chr(0x301)


class TestNormText:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Acme, Inc.", "acme inc"),
            ("  Hello---World  ", "hello world"),
            ("AT&T", "at t"),
            ("", ""),
            ("   ", ""),
            ("!!! --- ???", ""),
            ("C3PO", "c3po"),
            ("a_b", "a b"),  # underscore is Pc, not L/N/M
            ("go \U0001f680 now", "go now"),  # emoji is So
            ("line1\nline2\tline3", "line1 line2 line3"),
            ("Tom's Hardware", "tom s hardware"),
            ("R&D / Platform", "r d platform"),
        ],
    )
    def test_examples(self, raw: str, expected: str) -> None:
        assert norm_text(raw) == expected

    def test_nfkc_folds_compatibility_forms(self) -> None:
        assert norm_text("ＡＣＭＥ") == "acme"  # fullwidth ACME
        assert norm_text("ﬁnance") == "finance"  # fi ligature
        assert norm_text("③") == "3"  # circled digit three

    def test_nfkc_composes_before_lowercasing(self) -> None:
        # "e" + combining acute composes to a single precomposed letter under NFKC.
        assert norm_text("Cafe" + COMBINING_ACUTE) == "café"

    def test_combining_marks_are_kept(self) -> None:
        # x + U+0301 has no precomposed form, so the mark (category Mn) survives as-is.
        assert norm_text("X" + COMBINING_ACUTE) == "x" + COMBINING_ACUTE

    def test_default_lowercasing_is_not_locale_specific(self) -> None:
        # U+0130 lowercases to "i" + U+0307 (dotted i), not to a bare "i" or Turkish "i".
        assert norm_text(chr(0x130)) == "i" + chr(0x307)
        # Final sigma is context dependent in the default mapping.
        assert norm_text("ΟΔΥΣΣΕΥΣ") == ("οδυσσευς")
        assert norm_text(chr(0x1E9E)) == "ß"  # capital sharp s -> sharp s

    def test_non_ascii_letters_and_digits_are_kept(self) -> None:
        assert norm_text("東京 ٣ Über") == "東京 ٣ über"

    def test_format_and_separator_characters_become_spaces(self) -> None:
        assert norm_text("a" + ZWSP + "b") == "a b"  # Cf
        assert norm_text("a" + NBSP + "b") == "a b"  # NFKC maps NBSP to a plain space
        assert norm_text("a" + IDEOGRAPHIC_SPACE + "b") == "a b"
        assert norm_text(BOM + "a" + BOM) == "a"

    def test_surrogates_and_unassigned_code_points_become_spaces(self) -> None:
        assert norm_text("a" + chr(0xD800) + "b") == "a b"  # Cs
        assert norm_text("a" + chr(0x378) + "b") == "a b"  # Cn (unassigned)

    def test_idempotent(self) -> None:
        for raw in ["Acme, Inc.", "AT&T", "Ａ b③", "x" + COMBINING_ACUTE, ""]:
            once = norm_text(raw)
            assert norm_text(once) == once

    def test_tokens(self) -> None:
        assert tokens("  Senior   Engineer!! ") == ["senior", "engineer"]
        assert tokens("---") == []


class TestCompanyKey:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Acme, Inc.", "acme"),
            ("The Acme Corporation", "acme"),
            ("Inc", "inc"),
            ("AT&T", "at t"),
            ("ACME Inc.", "acme"),
            ("acme, inc", "acme"),
            ("Acme", "acme"),
            ("Acme Co Inc", "acme"),  # repeated trailing suffixes
            ("Acme Inc Holdings", "acme inc holdings"),  # suffix only counts at the end
            ("The Inc", "the inc"),  # nothing left -> original tokens
            ("The", "the"),
            ("Co", "co"),
            ("The The Acme", "the acme"),  # only a single leading "the" is dropped
            ("Acme The Company", "acme the"),  # "the" is only dropped when leading
            ("Siemens AG", "siemens"),
            ("Foo GmbH", "foo"),
            ("Foo Pty Ltd", "foo"),
            ("Bar Limited Liability Partnership LLP", "bar limited liability partnership"),
            ("***", ""),
        ],
    )
    def test_examples(self, name: str, expected: str) -> None:
        assert company_key(name) == expected

    def test_spacing_variants_are_distinct_keys(self) -> None:
        assert company_key("DoorDash") == "doordash"
        assert company_key("Door Dash") == "door dash"


class TestTitleKey:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Senior Engineer (Remote) [US]", "senior engineer"),
            ("Engineer", "engineer"),
            ("Engineer ((Remote))", "engineer"),  # nested parentheses
            ("Engineer [(US)]", "engineer"),  # bracket containing parentheses
            ("Engineer (a) (b) [c]", "engineer"),
            ("Engineer (unclosed", "engineer unclosed"),
            ("Engineer ) stray", "engineer stray"),
            ("(Remote) Engineer", "engineer"),
            ("Sr.(Eng)ineer", "sr ineer"),  # segments are deleted, not replaced by a space
            ("C++ Developer", "c developer"),
            ("", ""),
            ("(only)", ""),
        ],
    )
    def test_examples(self, title: str, expected: str) -> None:
        assert title_key(title) == expected


class TestLocationKey:
    def test_spec_example(self) -> None:
        assert location_key("New York, NY") == "new ny york"
        assert location_key("NY - New York") == "new ny york"

    def test_none_and_empty(self) -> None:
        assert location_key(None) == ""
        assert location_key("") == ""
        assert location_key("???") == ""

    def test_unique_tokens_sorted_by_code_point(self) -> None:
        assert location_key("b a b A") == "a b"
        assert location_key("Zurich, Älvsjö") == "zurich älvsjö"
        assert location_key("10 Downing 2") == "10 2 downing"


class TestTokenSequenceMatch:
    @pytest.mark.parametrize(
        ("key", "phrase", "expected"),
        [
            ("senior software engineer", "software engineer", True),
            ("senior software engineer", "Software  ENGINEER!", True),
            ("senior software engineer", "senior engineer", False),  # not contiguous
            ("senior software engineer", "engineer", True),
            ("senior software engineer", "engine", False),  # whole tokens only
            ("senior software engineer", "engineering", False),
            ("senior software engineer", "", False),
            ("senior software engineer", "---", False),
            ("engineer", "senior engineer", False),  # phrase longer than the key
            ("", "engineer", False),
            ("c developer", "c++", True),  # phrase normalizes to "c"
            ("senior software engineer", "senior software engineer", True),
        ],
    )
    def test_examples(self, key: str, phrase: str, expected: bool) -> None:
        assert token_sequence_match(key, phrase) is expected


class TestSha12:
    def test_known_digests(self) -> None:
        assert sha12("abc") == "ba7816bf8f01"
        assert sha12("") == "e3b0c44298fc"

    def test_is_prefix_of_sha256_of_utf8(self) -> None:
        text = "café 東京"
        assert sha12(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    def test_twelve_lowercase_hex_chars(self) -> None:
        digest = sha12("anything")
        assert len(digest) == 12
        assert digest == digest.lower()
        int(digest, 16)

    def test_lone_surrogate_hashes_as_replacement_character(self) -> None:
        assert sha12("a" + chr(0xD800) + "b") == sha12("a" + chr(0xFFFD) + "b")


class TestLevenshtein:
    @pytest.mark.parametrize(
        ("a", "b", "expected"),
        [
            ("", "", 0),
            ("abc", "", 3),
            ("", "abc", 3),
            ("kitten", "sitting", 3),
            ("flaw", "lawn", 2),
            ("acme robotics", "acme robotic", 1),
            ("abcdef", "abcdeg", 1),
            ("ab", "ba", 2),
            ("same", "same", 0),
            ("éa", "ea", 1),  # code points, not bytes
        ],
    )
    def test_examples(self, a: str, b: str, expected: int) -> None:
        assert levenshtein(a, b) == expected
        assert levenshtein(b, a) == expected


class TestTrim:
    def test_strips_ecmascript_whitespace(self) -> None:
        assert trim(" \t\n" + NBSP + BOM + "x" + IDEOGRAPHIC_SPACE + "\r") == "x"

    def test_does_not_strip_what_ecmascript_keeps(self) -> None:
        # String.prototype.trim keeps U+0085 and zero width space; Python's str.strip differs.
        assert trim(NEL + "x" + NEL) == NEL + "x" + NEL
        assert trim(ZWSP + "x") == ZWSP + "x"

    def test_preserves_internal_whitespace(self) -> None:
        assert trim("  a   b  ") == "a   b"
