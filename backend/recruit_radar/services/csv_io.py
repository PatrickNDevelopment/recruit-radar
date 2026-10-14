"""CSV import parsing and export writing (spec 05).

The parser is deliberately small and explicit rather than ``csv``-module based, because the
spec needs three things the stdlib reader does not give together: the 1-based line on which
each *record starts* (quoted fields may span lines), row-level rejection of a badly quoted row
without losing the rest of the file, and a file-level error for an unterminated quote.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from ..clock import is_valid_ts
from ..normalization import WHITESPACE_CHARS, CleanPosting, FieldProblem, clean_posting, trim

_BOM: Final = chr(0xFEFF)
MAX_CSV_BYTES: Final = 1024 * 1024
MAX_CSV_ROWS: Final = 5000
KNOWN_COLUMNS: Final = (
    "company_name",
    "title",
    "location",
    "work_mode",
    "department",
    "url",
    "posted_at",
    "source_posting_id",
    "observed_at",
)
REQUIRED_COLUMNS: Final = ("company_name", "title")
# A text cell starting with one of these is a spreadsheet-formula risk (spec 05).
FORMULA_TRIGGERS: Final = ("=", "+", "-", "@", "\t", "\r")


class CsvFileError(Exception):
    """The file as a whole is unusable (spec 03: 422 ``invalid_csv``).

    ``code`` is the same vocabulary the TypeScript importer uses (``too_large``,
    ``too_many_rows``, ``contains_nul``, ``unterminated_quote``, ``empty_file``,
    ``malformed_header``, ``duplicate_header``, ``missing_required_column``), pinned by
    ``contracts/vectors/csv-import.json``.
    """

    def __init__(self, message: str, line: int | None = None, *, code: str = "invalid_csv") -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.code = code


@dataclass(frozen=True, slots=True)
class CsvRecord:
    line: int  # 1-based physical line on which the record starts
    cells: tuple[str, ...]
    malformed: str | None = None


@dataclass(frozen=True, slots=True)
class RowError:
    line: int
    field: str | None
    message: str


@dataclass(frozen=True, slots=True)
class RowWarning:
    line: int
    message: str


@dataclass(frozen=True, slots=True)
class ParsedRow:
    line: int
    posting: CleanPosting
    observed_at: str | None


@dataclass(slots=True)
class ParsedCsv:
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    warnings: list[RowWarning] = field(default_factory=list)
    rejected: int = 0


# ---------------------------------------------------------------------------------------------
# Formula guard
# ---------------------------------------------------------------------------------------------
def _leading_apostrophes(value: str) -> int:
    count = 0
    while count < len(value) and value[count] == "'":
        count += 1
    return count


def guard_cell(value: str) -> str:
    """Export: one more leading apostrophe on a cell that is a formula trigger, optionally
    already behind apostrophes (``'=x`` becomes ``''=x``), so the transform is a bijection."""
    lead = _leading_apostrophes(value)
    return "'" + value if value[lead : lead + 1] in FORMULA_TRIGGERS else value


def unguard_cell(value: str) -> str:
    """Import: remove exactly one leading apostrophe when apostrophes precede a trigger."""
    lead = _leading_apostrophes(value)
    if lead >= 1 and value[lead : lead + 1] in FORMULA_TRIGGERS:
        return value[1:]
    return value


# ---------------------------------------------------------------------------------------------
# Record parser
# ---------------------------------------------------------------------------------------------
def parse_records(text: str) -> list[CsvRecord]:
    """Split RFC 4180 text into records, keeping each record's starting line number.

    Handles CRLF/LF/CR terminators, quoted fields with embedded delimiters, quotes and line
    breaks, and a leading BOM. Raises :class:`CsvFileError` for an unterminated quote. A record
    whose quoting is broken (text after a closing quote) is returned with ``malformed`` set.
    """
    if text.startswith(_BOM):
        text = text[1:]
    if "\x00" in text:
        raise CsvFileError(
            "CSV contains a NUL character, which is not valid text", code="contains_nul"
        )

    records: list[CsvRecord] = []
    cells: list[str] = []
    buf: list[str] = []
    line = 1
    record_line = 1
    in_quotes = False
    quote_line = 0
    after_quote = False
    field_blank = True  # every char of the current unquoted field so far is a space or tab
    record_quoted = False
    malformed: str | None = None
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    buf.append('"')
                    i += 2
                else:
                    in_quotes = False
                    after_quote = True
                    i += 1
            elif ch == "\r":
                if i + 1 < n and text[i + 1] == "\n":
                    buf.append("\r\n")
                    i += 2
                else:
                    buf.append("\r")
                    i += 1
                line += 1
            else:
                if ch == "\n":
                    line += 1
                buf.append(ch)
                i += 1
            continue

        if ch == ",":
            cells.append("".join(buf))
            buf = []
            after_quote = False
            field_blank = True
            i += 1
        elif ch in "\r\n":
            i += 2 if ch == "\r" and i + 1 < n and text[i + 1] == "\n" else 1
            cells.append("".join(buf))
            records.append(CsvRecord(record_line, tuple(cells), malformed))
            cells, buf = [], []
            after_quote = False
            field_blank = True
            record_quoted = False
            malformed = None
            line += 1
            record_line = line
        elif ch == '"':
            if after_quote:
                malformed = malformed or "a quote follows a closing quote"
            elif field_blank:
                in_quotes = True
                quote_line = line
                record_quoted = True
                buf = []
                field_blank = False
            else:
                buf.append('"')  # a quote inside an unquoted field is kept literally
            i += 1
        elif after_quote:
            if ch not in " \t":
                malformed = malformed or "text follows a closing quote"
            i += 1
        else:
            buf.append(ch)
            if ch not in " \t":
                field_blank = False
            i += 1

    if in_quotes:
        raise CsvFileError(
            f"Unterminated quoted field starting on line {quote_line}",
            quote_line,
            code="unterminated_quote",
        )
    if cells or buf or record_quoted:
        cells.append("".join(buf))
        records.append(CsvRecord(record_line, tuple(cells), malformed))
    return records


def _is_blank(record: CsvRecord) -> bool:
    return len(record.cells) == 1 and trim(record.cells[0]) == "" and record.malformed is None


_HEADER_SEPARATORS: Final = str.maketrans({ch: "_" for ch in WHITESPACE_CHARS + "-"})


def normalize_header(name: str) -> str:
    """Case-insensitive; every whitespace character (the spec trim set: a tab and a no-break
    space count) and every hyphen becomes an underscore (spec 05 "CSV details")."""
    return trim(name).lower().translate(_HEADER_SEPARATORS)


# ---------------------------------------------------------------------------------------------
# Postings
# ---------------------------------------------------------------------------------------------
def parse_postings(
    text: str, *, default_observed: str | None = None, now: str | None = None
) -> ParsedCsv:
    """Parse and validate an import file; valid rows are kept, invalid rows are reported.

    ``now`` is the import time and ``default_observed`` the instant of rows that leave
    ``observed_at`` blank (``now`` when omitted). With ``now`` given, a row whose instant is
    later than ``now`` gets a warning: the analysis ignores it until then.
    """
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise CsvFileError("CSV text is not valid UTF-8", code="invalid_text") from exc
    if size > MAX_CSV_BYTES:
        raise CsvFileError(f"CSV is larger than 1 MB ({size} bytes)", code="too_large")

    records = [record for record in parse_records(text) if not _is_blank(record)]
    if not records:
        raise CsvFileError(
            "CSV is empty: a header row with company_name and title is required",
            code="empty_file",
        )

    header = records[0]
    if header.malformed is not None:
        raise CsvFileError(
            f"Header row is malformed: {header.malformed}", header.line, code="malformed_header"
        )
    names = [normalize_header(cell) for cell in header.cells]
    seen: dict[str, str] = {}
    for original, name in zip(header.cells, names, strict=True):
        if name and name in seen:
            raise CsvFileError(
                f"Duplicate column {name!r} (headers {seen[name]!r} and {original!r})",
                header.line,
                code="duplicate_header",
            )
        seen[name] = original
    missing = [column for column in REQUIRED_COLUMNS if column not in names]
    if missing:
        raise CsvFileError(
            f"Missing required column(s): {', '.join(missing)}",
            header.line,
            code="missing_required_column",
        )

    data = records[1:]
    if len(data) > MAX_CSV_ROWS:
        raise CsvFileError(
            f"CSV has {len(data)} data rows; the limit is {MAX_CSV_ROWS}", code="too_many_rows"
        )

    result = ParsedCsv()
    for index, name in enumerate(names):
        if not name:
            result.warnings.append(
                RowWarning(header.line, f"Column {index + 1} has no header name and is ignored")
            )
        elif name not in KNOWN_COLUMNS:
            result.warnings.append(RowWarning(header.line, f'Unknown column "{name}" is ignored'))

    # A repeated role only replaces the earlier one inside one snapshot, i.e. at one instant.
    first_line_of_role: dict[tuple[str, ...], int] = {}
    for record in data:
        if record.malformed is not None:
            result.errors.append(RowError(record.line, None, f"Malformed row: {record.malformed}"))
            result.rejected += 1
            continue
        if len(record.cells) > len(names) and any(
            trim(cell) for cell in record.cells[len(names) :]
        ):
            # Extra *empty* cells (a trailing comma) are tolerated; extra values would shift
            # columns and corrupt data, so that row is refused (spec 05 "CSV details").
            result.errors.append(
                RowError(
                    record.line,
                    None,
                    f"Row has {len(record.cells)} values but the header defines {len(names)} "
                    "columns; quote any field that contains a comma",
                )
            )
            result.rejected += 1
            continue

        raw: dict[str, object] = {}
        for name, cell in zip(names, record.cells, strict=False):
            if name in KNOWN_COLUMNS:
                raw[name] = unguard_cell(trim(cell))
        observed_text = raw.pop("observed_at", None)
        observed_at = trim(observed_text) if isinstance(observed_text, str) else ""

        cleaned = clean_posting(raw)
        problems: list[FieldProblem] = list(cleaned.problems)
        if observed_at and not is_valid_ts(observed_at):
            problems.append(
                FieldProblem("observed_at", "observed_at must be YYYY-MM-DDTHH:MM:SSZ (UTC)")
            )
        if problems or cleaned.posting is None:
            for problem in problems:
                result.errors.append(RowError(record.line, problem.field, problem.message))
            result.rejected += 1
            continue

        posting = cleaned.posting
        role = (*posting.role_key(), observed_at)
        earlier = first_line_of_role.get(role)
        if earlier is None:
            first_line_of_role[role] = record.line
        else:
            result.warnings.append(
                RowWarning(
                    record.line,
                    f"Same posting as line {earlier}; the later row replaces the earlier one",
                )
            )
        if now is not None:
            effective = observed_at or default_observed or now
            if effective > now:
                result.warnings.append(
                    RowWarning(
                        record.line,
                        f"observed_at {effective} is after the import time {now}; "
                        "the analysis ignores this row until then",
                    )
                )
        result.rows.append(ParsedRow(record.line, posting, observed_at or None))
    result.warnings.sort(key=lambda warning: warning.line)
    return result


# ---------------------------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------------------------
def _quote(cell: str) -> str:
    needs_quotes = any(c in cell for c in (",", '"', "\r", "\n")) or cell != trim(cell)
    if not needs_quotes:
        return cell
    return '"' + cell.replace('"', '""') + '"'


def write_csv(rows: Iterable[Sequence[str]]) -> str:
    """RFC 4180 text (CRLF). Every cell passes through the formula guard."""
    return "".join(",".join(_quote(guard_cell(cell)) for cell in row) + "\r\n" for row in rows)
