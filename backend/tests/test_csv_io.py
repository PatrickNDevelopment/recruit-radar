"""CSV parsing/validation/writing (spec 05)."""

from __future__ import annotations

import pytest

from recruit_radar.services.csv_io import (
    CsvFileError,
    ParsedCsv,
    guard_cell,
    normalize_header,
    parse_postings,
    parse_records,
    unguard_cell,
    write_csv,
)

HEADER = "company_name,title,location,work_mode,department,url,posted_at,source_posting_id"


def parse(text: str) -> ParsedCsv:
    return parse_postings(text)


# -- record splitting --------------------------------------------------------------------------
def test_records_keep_their_starting_line_across_multiline_quoted_fields() -> None:
    text = 'a,b\n"line one\nline two",x\nlast,row\n'
    records = parse_records(text)
    assert [(r.line, r.cells) for r in records] == [
        (1, ("a", "b")),
        (2, ("line one\nline two", "x")),
        (4, ("last", "row")),
    ]


@pytest.mark.parametrize("terminator", ["\n", "\r\n", "\r"])
def test_every_line_terminator_is_understood(terminator: str) -> None:
    text = terminator.join(["a,b", "1,2", "3,4"]) + terminator
    assert [r.cells for r in parse_records(text)] == [("a", "b"), ("1", "2"), ("3", "4")]
    assert [r.line for r in parse_records(text)] == [1, 2, 3]


def test_bom_is_tolerated() -> None:
    result = parse("\ufeffcompany_name,title\nAcme,Engineer\n")
    assert [r.posting.company_name for r in result.rows] == ["Acme"]


def test_quotes_escaped_quotes_and_embedded_commas() -> None:
    result = parse('company_name,title\n"Acme, Inc.","The ""Best"" Engineer, Staff"\n')
    posting = result.rows[0].posting
    assert posting.company_name == "Acme, Inc."
    assert posting.title == 'The "Best" Engineer, Staff'


def test_unterminated_quote_is_a_file_level_error_with_its_line() -> None:
    with pytest.raises(CsvFileError) as error:
        parse('company_name,title\nAcme,Engineer\n"Broken,Row\nnext,line\n')
    assert error.value.line == 3
    assert "Unterminated" in error.value.message


def test_text_after_a_closing_quote_rejects_only_that_row() -> None:
    result = parse('company_name,title\nAcme,"Engineer"x\nOther,Designer\n')
    assert [r.posting.company_name for r in result.rows] == ["Other"]
    assert result.rejected == 1
    assert [(e.line, e.field) for e in result.errors] == [(2, None)]


def test_nul_character_is_a_file_error() -> None:
    with pytest.raises(CsvFileError):
        parse("company_name,title\nAcme,Eng\x00ineer\n")


# -- headers -----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Company Name", "company_name"),
        ("COMPANY-NAME", "company_name"),
        ("  posted-at ", "posted_at"),
        ("Source Posting-ID", "source_posting_id"),
    ],
)
def test_header_normalization(raw: str, expected: str) -> None:
    assert normalize_header(raw) == expected


def test_headers_are_case_insensitive_and_unknown_columns_warn() -> None:
    result = parse("Company Name,TITLE,Salary,Posted-At\nAcme,Engineer,100k,2026-10-01\n")
    assert result.rows[0].posting.posted_at == "2026-10-01"
    # the warning names the column as normalized, the same way the TypeScript importer does
    assert [(w.line, w.message) for w in result.warnings] == [
        (1, 'Unknown column "salary" is ignored')
    ]


def test_duplicate_headers_are_a_file_error() -> None:
    with pytest.raises(CsvFileError, match="Duplicate column"):
        parse("company_name,title,Company Name\nAcme,Engineer,Acme\n")


@pytest.mark.parametrize(
    "text",
    ["", "\n\n  \n", "title\nEngineer\n", "company_name\nAcme\n", "location,url\nx,y\n"],
)
def test_empty_file_and_missing_required_columns_are_file_errors(text: str) -> None:
    with pytest.raises(CsvFileError):
        parse(text)


def test_a_header_only_file_is_valid_and_empty() -> None:
    result = parse("company_name,title\n")
    assert result.rows == []
    assert result.rejected == 0


# -- row validation ----------------------------------------------------------------------------
def test_row_errors_carry_line_number_and_field_and_valid_rows_are_kept() -> None:
    long_title = "T" * 301
    text = "\n".join(
        [
            HEADER,
            "Acme,Engineer,NYC,remote,Eng,https://a.example/1,2026-10-01,1",  # line 2 ok
            ",Missing company,,,,,,",  # line 3
            f"Acme,{long_title},,,,,,",  # line 4
            "Acme,Designer,,office,,,,",  # line 5
            "Acme,Analyst,,,,ftp://a.example,,",  # line 6
            "Acme,Writer,,,,,2026-02-30,",  # line 7
            "Acme,Manager,,,,,,9",  # line 8 ok
        ]
    )
    result = parse(text)
    assert [r.line for r in result.rows] == [2, 8]
    assert result.rejected == 5
    by_line = {(e.line, e.field) for e in result.errors}
    assert by_line == {
        (3, "company_name"),
        (4, "title"),
        (5, "work_mode"),
        (6, "url"),
        (7, "posted_at"),
    }


def test_one_row_can_have_several_errors() -> None:
    result = parse("company_name,title,url,work_mode\n,,ftp://x,nope\n")
    assert result.rejected == 1
    assert {e.field for e in result.errors} == {"company_name", "title", "url", "work_mode"}
    assert {e.line for e in result.errors} == {2}


def test_errors_use_the_line_a_multiline_record_starts_on() -> None:
    result = parse('company_name,title\nAcme,"Eng\nineer"\n,"two\nlines"\n')
    assert [r.line for r in result.rows] == [2]
    assert [(e.line, e.field) for e in result.errors] == [(4, "company_name")]


def test_row_with_too_many_values_is_rejected_and_short_rows_are_missing_fields() -> None:
    result = parse("company_name,title\nAcme,Engineer,extra\nOnlyCompany\n")
    assert result.rejected == 2
    messages = {e.line: e.message for e in result.errors}
    assert "3 values" in messages[2]
    assert (3, "title") in {(e.line, e.field) for e in result.errors}


def test_observed_at_is_validated_and_kept_per_row() -> None:
    result = parse(
        "company_name,title,observed_at\n"
        "A,One,2026-10-01T08:00:00Z\n"
        "B,Two,\n"
        "C,Three,2026-10-01 08:00\n"
    )
    assert [(r.posting.company_name, r.observed_at) for r in result.rows] == [
        ("A", "2026-10-01T08:00:00Z"),
        ("B", None),
    ]
    assert [(e.line, e.field) for e in result.errors] == [(4, "observed_at")]


def test_blank_lines_are_skipped_and_do_not_shift_line_numbers() -> None:
    result = parse("company_name,title\n\nAcme,Engineer\n\n,Broken\n")
    assert [r.line for r in result.rows] == [3]
    assert [e.line for e in result.errors] == [5]


def test_a_repeated_role_at_the_same_instant_warns_that_the_later_row_wins() -> None:
    result = parse(
        "company_name,title,location\nAcme,Engineer,NYC\nAcme Inc,Engineer (Remote),NYC\n"
    )
    assert len(result.rows) == 2
    assert [(w.line, "line 2" in w.message) for w in result.warnings] == [(3, True)]


def test_the_same_role_at_different_instants_is_not_a_duplicate() -> None:
    result = parse(
        "company_name,title,observed_at\n"
        "Acme,Engineer,2026-10-01T00:00:00Z\n"
        "Acme,Engineer,2026-10-02T00:00:00Z\n"
    )
    assert result.warnings == []


def test_row_and_size_limits() -> None:
    rows = "".join(f"Acme,Role {i}\n" for i in range(5001))
    with pytest.raises(CsvFileError, match="5000"):
        parse("company_name,title\n" + rows)
    ok_rows = "".join(f"Acme,Role {i}\n" for i in range(5000))
    assert len(parse("company_name,title\n" + ok_rows).rows) == 5000
    with pytest.raises(CsvFileError, match="1 MB"):
        parse("company_name,title\nAcme," + "x" * (1024 * 1024) + "\n")


def test_text_that_is_not_utf8_encodable_is_a_file_error() -> None:
    with pytest.raises(CsvFileError):
        parse("company_name,title\nAcme,bad\ud800\n")


# -- formula guard -----------------------------------------------------------------------------
@pytest.mark.parametrize("trigger", ["=", "+", "-", "@", "\t", "\r"])
def test_guard_and_unguard_are_inverse_for_every_trigger(trigger: str) -> None:
    cell = f"{trigger}SUM(A1)"
    guarded = guard_cell(cell)
    assert guarded == "'" + cell
    assert unguard_cell(guarded) == cell


def test_guard_leaves_ordinary_text_alone() -> None:
    assert guard_cell("Acme") == "Acme"
    assert guard_cell("") == ""
    assert guard_cell("'quoted") == "'quoted"
    assert unguard_cell("'quoted") == "'quoted"  # apostrophe not followed by a trigger
    assert unguard_cell("'") == "'"


def test_guard_is_a_bijection_even_for_apostrophes_in_front_of_a_trigger() -> None:
    # Spec 05 "CSV details": a cell matching ^'*[=+\-@\t\r] gains one apostrophe on export and a
    # cell matching ^'+[=+\-@\t\r] loses exactly one on import (same rule as the TypeScript side).
    assert guard_cell("'=x") == "''=x"
    assert guard_cell("''=x") == "'''=x"
    assert unguard_cell("''=1+1") == "'=1+1"
    assert unguard_cell("'=1+1") == "=1+1"
    assert unguard_cell("'''+x") == "''+x"
    for sample in [
        "",
        "'",
        "''",
        "'=x",
        "''=x",
        "'@a",
        "'\tx",
        "'abc",
        "O'Brien",
        "=SUM(A1)",
        "-1",
    ]:
        assert unguard_cell(guard_cell(sample)) == sample, sample
    result = parse("company_name,title\n'=Evil Corp,'-Lead\n")
    posting = result.rows[0].posting
    assert (posting.company_name, posting.title) == ("=Evil Corp", "-Lead")


def test_import_trims_a_cell_before_removing_its_guard_apostrophe() -> None:
    result = parse("company_name,title\n  '=x  ,\t'-y\n")
    posting = result.rows[0].posting
    assert (posting.company_name, posting.title) == ("=x", "-y")


def test_extra_empty_cells_are_tolerated_but_extra_values_are_not() -> None:
    result = parse('company_name,title\nA,B,,\nC,D, ,""\nE,F,oops\n')
    assert [r.posting.company_name for r in result.rows] == ["A", "C"]
    assert [(e.line, e.field) for e in result.errors] == [(4, None)]


def test_spaces_and_tabs_around_a_quoted_field_are_ignored() -> None:
    result = parse('company_name,title\nAcme, "Senior, Engineer" \n  "Beta"\t,\t"D"\n')
    assert [(r.posting.company_name, r.posting.title) for r in result.rows] == [
        ("Acme", "Senior, Engineer"),
        ("Beta", "D"),
    ]


def test_whitespace_only_and_quoted_empty_lines_are_blank_lines() -> None:
    result = parse('company_name,title\n   \n\t\n""\nAcme,Engineer\n  ""  \n,Broken\n')
    assert [r.line for r in result.rows] == [5]
    assert [e.line for e in result.errors] == [7]


def test_header_names_treat_tabs_and_no_break_spaces_like_spaces() -> None:
    result = parse("Company\tName,TITLE,Posted\u00a0At\nAcme,Engineer,2026-09-01\n")
    posting = result.rows[0].posting
    assert (posting.company_name, posting.posted_at) == ("Acme", "2026-09-01")


def test_export_import_round_trip_preserves_formula_looking_text() -> None:
    cells = ["=cmd|' /C calc'!A0", "+1", "-1", "@sum", "\tTabbed", "plain", 'He said "hi", ok']
    text = write_csv(
        [["company_name", "title"], cells[:2], cells[2:4], cells[4:6], [cells[6], "x"]]
    )
    assert text.endswith("\r\n")
    result = parse(text)
    assert [(r.posting.company_name, r.posting.title) for r in result.rows] == [
        (cells[0], cells[1]),
        (cells[2], cells[3]),
        ("Tabbed", cells[5]),  # a leading tab is whitespace and is trimmed by the cleaner
        (cells[6], "x"),
    ]


def test_writer_quotes_commas_quotes_newlines_and_edge_whitespace() -> None:
    text = write_csv([["a", "b,c", 'd"e', "f\ng", " h "]])
    assert text == 'a,"b,c","d""e","f\ng"," h "\r\n'
