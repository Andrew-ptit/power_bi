"""Read-only CSV import and structural profiling for the W-04 slice.

The importer never evaluates cell text. Raw records are omitted by default;
the local UI can explicitly request a small, bounded preview. Rows whose width
differs from the selected header are counted and reported so a caller cannot
silently lose malformed input.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import codecs
import csv
import hashlib
import io
from pathlib import Path
from typing import Any

from .errors import InputError


MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 512
MAX_CELL_CHARS = 10_000
MAX_PREVIEW_ROWS = 50
DELIMITER_CANDIDATES = (",", ";", "\t", "|")
SUPPORTED_ENCODINGS = frozenset(
    {"utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1252", "iso8859-1"}
)


@dataclass(frozen=True)
class CsvColumnProfile:
    name: str
    data_types: dict[str, int]
    null_count: int
    duplicate_count: int
    formula_like_count: int
    sample: list[str]


@dataclass(frozen=True)
class CsvRowError:
    code: str
    record_number: int
    line_number: int
    expected_columns: int
    actual_columns: int


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _normalise_encoding(name: str) -> str:
    try:
        canonical = codecs.lookup(name).name
    except LookupError as exc:
        raise InputError("CSV_ENCODING", name, "Unknown encoding") from exc
    aliases = {"utf-8-sig": "utf-8-sig", "latin-1": "iso8859-1"}
    canonical = aliases.get(name.lower().replace("_", "-"), canonical)
    if canonical not in SUPPORTED_ENCODINGS:
        raise InputError(
            "CSV_ENCODING",
            name,
            "Encoding is not in the supported local CSV allowlist",
        )
    return canonical


def _select_encoding(payload: bytes, requested: str | None, path: Path) -> str:
    if requested:
        return _normalise_encoding(requested)
    if payload.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if payload.startswith(codecs.BOM_UTF16_LE) or payload.startswith(codecs.BOM_UTF16_BE):
        return "utf-16"
    return "utf-8"


def _reader(text: str, delimiter: str) -> csv.reader:
    return csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)


def _delimiter_shape(text: str, delimiter: str, header_row: int) -> tuple[int, bool] | None:
    try:
        header_width: int | None = None
        checked = 0
        consistent = True
        for record_number, row in enumerate(_reader(text, delimiter), start=1):
            if record_number == header_row:
                header_width = len(row)
                continue
            if record_number > header_row and header_width is not None:
                consistent &= len(row) == header_width
                checked += 1
                if checked >= 100:
                    break
    except csv.Error:
        return None
    return (header_width, consistent) if header_width is not None else None


def _select_delimiter(text: str, requested: str | None, header_row: int, path: Path) -> str:
    if requested is not None:
        if requested not in DELIMITER_CANDIDATES:
            raise InputError(
                "CSV_DELIMITER",
                str(path),
                "Delimiter must be one of comma, semicolon, tab, or pipe",
            )
        return requested
    shapes = {
        candidate: shape
        for candidate in DELIMITER_CANDIDATES
        if (shape := _delimiter_shape(text, candidate, header_row)) is not None and shape[0] > 1
    }
    if not shapes:
        raise InputError(
            "CSV_DELIMITER_NOT_FOUND",
            str(path),
            "Could not infer a multi-column delimiter; select one explicitly",
        )
    consistent = [candidate for candidate, (_, is_consistent) in shapes.items() if is_consistent]
    viable = consistent if consistent else list(shapes)
    if len(viable) != 1:
        labels = ["tab" if value == "\t" else value for value in viable]
        raise InputError(
            "CSV_AMBIGUOUS_DELIMITER",
            str(path),
            f"Records are structurally plausible with multiple delimiters: {', '.join(labels)}; select one explicitly",
        )
    return viable[0]


def _is_formula_like(value: str) -> bool:
    stripped = value.lstrip()
    if not stripped or stripped[0] not in "=+@-":
        return False
    if stripped[0] == "-":
        try:
            Decimal(stripped)
            return False
        except InvalidOperation:
            pass
    return True


def _value_kind(value: str) -> str:
    if value == "":
        return "empty"
    if _is_formula_like(value):
        return "formula_like_text"
    lowered = value.casefold()
    if lowered in {"true", "false"}:
        return "boolean"
    try:
        number = Decimal(value)
        return "integer" if number == number.to_integral_value() else "number"
    except InvalidOperation:
        pass
    try:
        date.fromisoformat(value)
        return "date"
    except ValueError:
        return "text"


def _profile_columns(headers: list[str], rows: list[list[str]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, header in enumerate(headers):
        values = [row[index] for row in rows]
        non_null = [value for value in values if value != ""]
        counts = Counter(non_null)
        profile = CsvColumnProfile(
            name=header,
            data_types=dict(Counter(_value_kind(value) for value in non_null)),
            null_count=len(values) - len(non_null),
            duplicate_count=sum(count - 1 for count in counts.values()),
            formula_like_count=sum(_is_formula_like(value) for value in non_null),
            sample=list(dict.fromkeys(non_null))[:5],
        )
        result.append(asdict(profile))
    return result


def profile_csv(
    path: str | Path,
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
    header_row: int = 1,
    include_preview: bool = False,
    preview_limit: int = 20,
) -> dict[str, Any]:
    """Profile a CSV without changing it.

    ``header_row`` is the one-based logical CSV record number, so a quoted
    newline inside a field does not increment it. Malformed-width records are
    included in ``row_count`` and ``row_errors`` but excluded from column
    aggregates. ``include_preview`` is intended only for a local, interactive
    UI and is capped by ``MAX_PREVIEW_ROWS``.
    """

    requested_path = Path(path)
    if requested_path.suffix.lower() != ".csv":
        raise InputError("UNSUPPORTED_CSV", str(requested_path), "Only .csv is supported")
    if header_row < 1:
        raise InputError("CSV_HEADER", str(requested_path), "header_row must be at least 1")
    if preview_limit < 1 or preview_limit > MAX_PREVIEW_ROWS:
        raise InputError(
            "PREVIEW_LIMIT",
            str(requested_path),
            f"preview_limit must be between 1 and {MAX_PREVIEW_ROWS}",
        )
    try:
        resolved = requested_path.resolve(strict=True)
    except OSError as exc:
        raise InputError("INVALID_CSV", str(requested_path), "CSV file does not exist") from exc
    if not resolved.is_file():
        raise InputError("INVALID_CSV", str(resolved), "Not a regular file")
    before = resolved.stat()
    if before.st_size > MAX_BYTES:
        raise InputError("CSV_LIMIT", str(resolved), f"CSV exceeds {MAX_BYTES} byte limit")
    payload = resolved.read_bytes()
    if len(payload) > MAX_BYTES:
        raise InputError("CSV_LIMIT", str(resolved), f"CSV exceeds {MAX_BYTES} byte limit")
    selected_encoding = _select_encoding(payload, encoding, resolved)
    try:
        text = payload.decode(selected_encoding, errors="strict")
    except UnicodeDecodeError as exc:
        raise InputError(
            "CSV_ENCODING",
            str(resolved),
            f"Content is not valid {selected_encoding}; select the correct encoding",
        ) from exc
    selected_delimiter = _select_delimiter(text, delimiter, header_row, resolved)

    headers: list[str] | None = None
    valid_rows: list[list[str]] = []
    row_errors: list[CsvRowError] = []
    row_count = 0
    formula_like_cells = 0
    try:
        reader = _reader(text, selected_delimiter)
        for record_number, row in enumerate(reader, start=1):
            if record_number < header_row:
                continue
            if record_number == header_row:
                if len(row) > MAX_COLUMNS:
                    raise InputError("CSV_LIMIT", str(resolved), f"Header exceeds {MAX_COLUMNS} columns")
                headers = [value.strip() for value in row]
                if any(len(value) > MAX_CELL_CHARS for value in headers):
                    raise InputError(
                        "CSV_LIMIT", str(resolved),
                        f"Header contains a cell over {MAX_CELL_CHARS} characters",
                    )
                if not headers or all(value == "" for value in headers):
                    raise InputError("CSV_HEADER", str(resolved), "Selected header is empty")
                if any(value == "" for value in headers):
                    raise InputError("CSV_HEADER", str(resolved), "Header contains an empty column name")
                folded = Counter(value.casefold() for value in headers)
                duplicates = sorted({value for value in headers if folded[value.casefold()] > 1})
                if duplicates:
                    raise InputError(
                        "CSV_DUPLICATE_HEADER",
                        str(resolved),
                        f"Duplicate column names: {', '.join(duplicates)}",
                    )
                continue
            row_count += 1
            if row_count > MAX_ROWS:
                raise InputError("CSV_LIMIT", str(resolved), f"CSV exceeds {MAX_ROWS} data rows")
            if any(len(value) > MAX_CELL_CHARS for value in row):
                raise InputError(
                    "CSV_LIMIT",
                    str(resolved),
                    f"Record {record_number} contains a cell over {MAX_CELL_CHARS} characters",
                )
            assert headers is not None
            if len(row) != len(headers):
                row_errors.append(
                    CsvRowError(
                        code="CSV_COLUMN_COUNT",
                        record_number=record_number,
                        line_number=reader.line_num,
                        expected_columns=len(headers),
                        actual_columns=len(row),
                    )
                )
                continue
            formula_like_cells += sum(_is_formula_like(value) for value in row)
            valid_rows.append(row)
    except csv.Error as exc:
        raise InputError("INVALID_CSV", str(resolved), f"CSV syntax error near line {reader.line_num}: {exc}") from exc
    if headers is None:
        raise InputError("CSV_HEADER", str(resolved), "Selected header row does not exist")

    after_payload = resolved.read_bytes()
    after = resolved.stat()
    source_hash = _hash_bytes(payload)
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or source_hash != _hash_bytes(after_payload)
    ):
        raise InputError("SOURCE_CHANGED", str(resolved), "CSV changed while it was being profiled")

    issues: list[str] = []
    if row_errors:
        issues.append(f"{len(row_errors)} record(s) have a different column count and require correction")
    if formula_like_cells:
        issues.append(
            f"{formula_like_cells} cell(s) look like spreadsheet formulas; values remain inert CSV text"
        )
    result = {
        "path": str(resolved),
        "encoding": selected_encoding,
        "delimiter": selected_delimiter,
        "header_row": header_row,
        "row_count": row_count,
        "valid_row_count": len(valid_rows),
        "invalid_row_count": len(row_errors),
        "columns": _profile_columns(headers, valid_rows),
        "row_errors": [asdict(error) for error in row_errors],
        "issues": issues,
        "source_sha256": source_hash,
        "source_unchanged": True,
        "mapping_ready": not row_errors,
    }
    if include_preview:
        result["preview"] = {
            "columns": headers,
            "rows": valid_rows[:preview_limit],
            "limit": preview_limit,
            "truncated": len(valid_rows) > preview_limit,
            "excluded_error_rows": len(row_errors),
        }
    return result
