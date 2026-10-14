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
from ..normalization import CleanPosting, FieldProblem, clean_posting, trim

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
    """The file as a whole is unusable (spec 03: 422 ``invalid_csv``)."""

    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.line = line


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
def guard_cell(value: str) -> str:
    """Export: one leading apostrophe on a cell that starts with a formula trigger."""
    return "'" + value if value[:1] in FORMULA_TRIGGERS else value


def unguard_cell(value: str) -> str:
    """Import: remove exactly one leading apostrophe that precedes a formula trigger."""
    if len(value) >= 2 and value[0] == "'" and value[1] in FORMULA_TRIGGERS:
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
        raise CsvFileError("CSV contains a NUL character, which is not valid text")

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
        raise CsvFileError(f"Unterminated quoted field starting on line {quote_line}", quote_line)
    if cells or buf or record_quoted:
        cells.append("".join(buf))
        records.append(CsvRecord(record_line, tuple(cells), malformed))
    return records


def _is_blank(record: CsvRecord) -> bool:
    return len(record.cells) == 1 and trim(record.cells[0]) == "" and record.malformed is None


def normalize_header(name: str) -> str:
    """Case-insensitive; spaces and hyphens become underscores (spec 05)."""
    return trim(name).lower().replace(" ", "_").replace("-", "_")


# ---------------------------------------------------------------------------------------------
# Postings
# ---------------------------------------------------------------------------------------------
def parse_postings(text: str) -> ParsedCsv:
    """Parse and validate an import file; valid rows are kept, invalid rows are reported."""
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise CsvFileError("CSV text is not valid UTF-8") from exc
    if size > MAX_CSV_BYTES:
        raise CsvFileError(f"CSV is larger than 1 MB ({size} bytes)")

    records = [record for record in parse_records(text) if not _is_blank(record)]
    if not records:
        raise CsvFileError("CSV is empty: a header row with company_name and title is required")

    header = records[0]
    if header.malformed is not None:
        raise CsvFileError(f"Header row is malformed: {header.malformed}", header.line)
    names = [normalize_header(cell) for cell in header.cells]
    seen: dict[str, str] = {}
    for original, name in zip(header.cells, names, strict=True):
        if name and name in seen:
            raise CsvFileError(
                f"Duplicate column {name!r} (headers {seen[name]!r} and {original!r})", header.line
            )
        seen[name] = original
    missing = [column for column in REQUIRED_COLUMNS if column not in names]
    if missing:
        raise CsvFileError(f"Missing required column(s): {', '.join(missing)}", header.line)

    data = records[1:]
    if len(data) > MAX_CSV_ROWS:
        raise CsvFileError(f"CSV has {len(data)} data rows; the limit is {MAX_CSV_ROWS}")

    result = ParsedCsv()
    for original, name in zip(header.cells, names, strict=True):
        if name not in KNOWN_COLUMNS:
            label = repr(trim(original)) if trim(original) else "(unnamed)"
            result.warnings.append(RowWarning(header.line, f"Unknown column {label} ignored"))

    # A repeated role only replaces the earlier one inside one snapshot, i.e. at one instant.
    first_line_of_role: dict[tuple[str, ...], int] = {}
    for record in data:
        if record.malformed is not None:
            result.errors.append(RowError(record.line, None, f"Malformed row: {record.malformed}"))
            result.rejected += 1
            continue
        if len(record.cells) > len(names):
            result.errors.append(
                RowError(
                    record.line,
                    None,
                    f"Row has {len(record.cells)} values but the header defines {len(names)} columns",
                )
            )
            result.rejected += 1
            continue

        raw: dict[str, object] = {}
        for name, cell in zip(names, record.cells, strict=False):
            if name in KNOWN_COLUMNS:
                raw[name] = unguard_cell(cell)
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
        result.rows.append(ParsedRow(record.line, posting, observed_at or None))
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
