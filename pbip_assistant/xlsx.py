"""Read-only OOXML workbook profiling for the R1 import slice.

The reader intentionally does not calculate formulas or mutate workbooks. It
interprets only date formats explicitly assigned to cells; date-looking text
remains text and ambiguous locale forms are reported.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from posixpath import basename, dirname, join, normpath
import re
from typing import Any, Iterable
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from .errors import InputError


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
MAX_UNCOMPRESSED = 64 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 512
MAX_CELL_CHARS = 10_000
MAX_PREVIEW_ROWS = 50

_ENCRYPTED_OFFICE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
_BUILTIN_DATE_FORMATS = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))
_BUILTIN_PERCENT_FORMATS = {9, 10}
_AMBIGUOUS_DATE = re.compile(r"^\s*(\d{1,2})[/-](\d{1,2})[/-](\d{2}|\d{4})\s*$")


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    data_types: dict[str, int]
    null_count: int
    duplicate_count: int
    sample: list[Any]
    issues: list[str]


@dataclass(frozen=True)
class TableProfile:
    name: str
    display_name: str
    ref: str
    columns: list[str]


@dataclass(frozen=True)
class FormulaProfile:
    cell_count: int
    missing_cached_count: int


@dataclass(frozen=True)
class SheetProfile:
    name: str
    row_count: int
    columns: list[ColumnProfile]
    tables: list[TableProfile]
    formula_cache: FormulaProfile
    issues: list[str]
    row_errors: list[dict[str, int | str]]
    mapping_ready: bool


@dataclass(frozen=True)
class _Cell:
    value: Any
    kind: str
    formula: bool
    missing_formula_cache: bool
    issue: str | None = None


def _read_xml(archive: ZipFile, member: str) -> ET.Element:
    try:
        return ET.fromstring(archive.read(member))
    except (KeyError, ET.ParseError, RuntimeError) as exc:
        raise InputError("INVALID_XLSX", member, "Missing or invalid OOXML part") from exc


def _text(node: ET.Element) -> str:
    return "".join(part.text or "" for part in node.iter(f"{{{MAIN}}}t"))


def _column_index(cell_ref: str) -> int:
    letters = "".join(char for char in cell_ref if char.isalpha()).upper()
    if not letters:
        raise ValueError("Missing column reference")
    result = 0
    for letter in letters:
        if not "A" <= letter <= "Z":
            raise ValueError("Invalid column reference")
        result = result * 26 + ord(letter) - ord("A") + 1
    return result - 1


def _safe_member(base_member: str, target: str, names: set[str], *, label: str) -> str:
    member = normpath(target.lstrip("/")) if target.startswith("/") else normpath(join(dirname(base_member), target))
    if not member.startswith("xl/") or member not in names:
        raise InputError("INVALID_XLSX", base_member, f"Invalid {label} path")
    return member


def _format_kind(num_fmt_id: int, format_code: str | None) -> str:
    if num_fmt_id in _BUILTIN_DATE_FORMATS:
        return "date"
    if num_fmt_id in _BUILTIN_PERCENT_FORMATS:
        return "percentage"
    if not format_code:
        return "number"
    cleaned = re.sub(r'"[^"]*"', "", format_code.lower())
    cleaned = re.sub(r"\\.", "", cleaned)
    cleaned = re.sub(r"\[(?!h\]|m\]|s\])[^]]*\]", "", cleaned)
    if "%" in cleaned:
        return "percentage"
    if re.search(r"[dy]", cleaned) or re.search(r"m{2,}", cleaned) or ("m" in cleaned and re.search(r"[hs]", cleaned)):
        return "date"
    return "number"


def _read_styles(archive: ZipFile, names: set[str]) -> dict[int, str]:
    if "xl/styles.xml" not in names:
        return {}
    root = _read_xml(archive, "xl/styles.xml")
    try:
        custom = {
            int(item.get("numFmtId", "0")): item.get("formatCode", "")
            for item in root.findall(f"{{{MAIN}}}numFmts/{{{MAIN}}}numFmt")
        }
    except ValueError as exc:
        raise InputError("INVALID_XLSX", "xl/styles.xml", "Invalid custom number format id") from exc
    result: dict[int, str] = {}
    for index, item in enumerate(root.findall(f"{{{MAIN}}}cellXfs/{{{MAIN}}}xf")):
        try:
            num_fmt_id = int(item.get("numFmtId", "0"))
        except ValueError as exc:
            raise InputError("INVALID_XLSX", "xl/styles.xml", "Invalid number format id") from exc
        result[index] = _format_kind(num_fmt_id, custom.get(num_fmt_id))
    return result


def _excel_date(value: float, date_1904: bool) -> tuple[str | None, str | None]:
    if value < 0:
        return None, "Negative Excel date serial was kept as a number"
    whole = int(value)
    fraction = value - whole
    if not date_1904 and whole == 60:
        return None, "Excel date serial 60 is the fictitious 1900-02-29 and was kept as a number"
    if date_1904:
        epoch, days = datetime(1904, 1, 1), whole
    else:
        epoch = datetime(1899, 12, 31) if whole < 60 else datetime(1899, 12, 30)
        days = whole
    try:
        parsed = epoch + timedelta(days=days, seconds=round(fraction * 86_400))
    except (OverflowError, ValueError):
        return None, "Excel date serial was outside the supported range and was kept as a number"
    if parsed.time() == datetime.min.time():
        return parsed.date().isoformat(), None
    return parsed.isoformat(timespec="seconds"), None


def _cell_value(cell: ET.Element, strings: list[str], styles: dict[int, str], date_1904: bool) -> _Cell:
    cell_type = cell.get("t")
    formula = cell.find(f"{{{MAIN}}}f") is not None
    value_node = cell.find(f"{{{MAIN}}}v")
    value = value_node.text if value_node is not None else None
    missing_formula_cache = formula and (value is None or value == "")
    if cell_type == "inlineStr":
        inline = cell.find(f"{{{MAIN}}}is")
        text = _text(inline) if inline is not None else ""
        if len(text) > MAX_CELL_CHARS:
            raise ValueError("Cell value exceeds size limit")
        return _Cell(text, "text", formula, missing_formula_cache)
    if value is None or value == "":
        return _Cell(None, "empty", formula, missing_formula_cache)
    if len(value) > MAX_CELL_CHARS:
        raise ValueError("Cell value exceeds size limit")
    if cell_type == "s":
        try:
            return _Cell(strings[int(value)], "text", formula, missing_formula_cache)
        except (ValueError, IndexError) as exc:
            raise ValueError("Invalid shared-string index") from exc
    if cell_type == "b":
        return _Cell(value == "1", "boolean", formula, missing_formula_cache)
    if cell_type == "e":
        return _Cell(value, "error", formula, missing_formula_cache)
    if cell_type == "d":
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return _Cell(value, "text", formula, missing_formula_cache, "Invalid ISO date cell was kept as text")
        return _Cell(value, "date", formula, missing_formula_cache)
    if cell_type == "str":
        return _Cell(value, "text", formula, missing_formula_cache)
    try:
        number = float(value)
    except ValueError:
        return _Cell(value, "text", formula, missing_formula_cache)
    style_index_text = cell.get("s")
    if style_index_text is not None:
        try:
            style_index = int(style_index_text)
        except ValueError as exc:
            raise ValueError("Invalid cell style index") from exc
        if style_index not in styles:
            raise ValueError("Cell references a missing style")
        if styles[style_index] == "date":
            parsed, issue = _excel_date(number, date_1904)
            if parsed is not None:
                return _Cell(parsed, "date", formula, missing_formula_cache)
            number_value = int(number) if number.is_integer() else number
            return _Cell(number_value, "number", formula, missing_formula_cache, issue)
        if styles[style_index] == "percentage":
            return _Cell(int(number) if number.is_integer() else number, "percentage", formula, missing_formula_cache)
    return _Cell(int(number) if number.is_integer() else number, "number", formula, missing_formula_cache)


def _sheet_rows(archive: ZipFile, member: str, strings: list[str], styles: dict[int, str], date_1904: bool) -> tuple[list[list[Any]], list[list[str]], list[int], int, int, list[str], ET.Element]:
    root = _read_xml(archive, member)
    rows: list[list[Any]] = []
    types: list[list[str]] = []
    row_numbers: list[int] = []
    formula_count = 0
    missing_cache_count = 0
    issues: list[str] = []
    sheet_data = root.find(f"{{{MAIN}}}sheetData")
    if sheet_data is None:
        return rows, types, row_numbers, formula_count, missing_cache_count, issues, root
    for row in sheet_data.findall(f"{{{MAIN}}}row"):
        if len(rows) >= MAX_ROWS + 1:
            raise InputError("XLSX_LIMIT", member, f"More than {MAX_ROWS} data rows")
        values: list[Any] = []
        value_types: list[str] = []
        for cell in row.findall(f"{{{MAIN}}}c"):
            try:
                index = _column_index(cell.get("r", ""))
                if index >= MAX_COLUMNS:
                    raise ValueError("Too many columns")
                parsed = _cell_value(cell, strings, styles, date_1904)
            except ValueError as exc:
                raise InputError("INVALID_XLSX", member, str(exc)) from exc
            while len(values) <= index:
                values.append(None)
                value_types.append("empty")
            values[index] = parsed.value
            value_types[index] = parsed.kind
            formula_count += int(parsed.formula)
            missing_cache_count += int(parsed.missing_formula_cache)
            if parsed.issue and parsed.issue not in issues:
                issues.append(parsed.issue)
        if any(value is not None for value in values):
            rows.append(values)
            types.append(value_types)
            try:
                row_numbers.append(int(row.get("r", str(len(row_numbers) + 1))))
            except ValueError as exc:
                raise InputError("INVALID_XLSX", member, "Invalid worksheet row number") from exc
    return rows, types, row_numbers, formula_count, missing_cache_count, issues, root


def _table_bounds(ref: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"\$?([A-Za-z]+)\$?(\d+):\$?([A-Za-z]+)\$?(\d+)", ref)
    if not match:
        raise InputError("INVALID_XLSX", ref, "Invalid table range")
    start_col = _column_index(match.group(1))
    end_col = _column_index(match.group(3))
    start_row, end_row = int(match.group(2)), int(match.group(4))
    if start_col > end_col or start_row > end_row:
        raise InputError("INVALID_XLSX", ref, "Invalid reversed table range")
    return start_col, start_row, end_col, end_row


def _slice_table(rows: list[list[Any]], types: list[list[str]], row_numbers: list[int], ref: str) -> tuple[list[list[Any]], list[list[str]]]:
    start_col, start_row, end_col, end_row = _table_bounds(ref)
    width = end_col - start_col + 1
    value_by_row = dict(zip(row_numbers, rows, strict=True))
    type_by_row = dict(zip(row_numbers, types, strict=True))
    selected_rows: list[list[Any]] = []
    selected_types: list[list[str]] = []
    for row_number in range(start_row, end_row + 1):
        values = value_by_row.get(row_number, [])
        kinds = type_by_row.get(row_number, [])
        selected_rows.append((values[start_col:end_col + 1] + [None] * width)[:width])
        selected_types.append((kinds[start_col:end_col + 1] + ["empty"] * width)[:width])
    return selected_rows, selected_types


def _sheet_tables(archive: ZipFile, names: set[str], sheet_member: str, sheet_root: ET.Element) -> list[TableProfile]:
    parts = sheet_root.findall(f"{{{MAIN}}}tableParts/{{{MAIN}}}tablePart")
    if not parts:
        return []
    rels_member = join(dirname(sheet_member), "_rels", f"{basename(sheet_member)}.rels")
    if rels_member not in names:
        raise InputError("INVALID_XLSX", sheet_member, "Table relationships are missing")
    relationships = {
        item.get("Id"): item.get("Target")
        for item in _read_xml(archive, rels_member).findall(f"{{{PKG_REL}}}Relationship")
    }
    tables: list[TableProfile] = []
    for part in parts:
        target = relationships.get(part.get(f"{{{REL}}}id"))
        if not target:
            raise InputError("INVALID_XLSX", sheet_member, "Table has no relationship")
        member = _safe_member(sheet_member, target, names, label="table")
        table = _read_xml(archive, member)
        name = table.get("name", "")
        display_name = table.get("displayName", name)
        ref = table.get("ref", "")
        columns = [item.get("name", "") for item in table.findall(f"{{{MAIN}}}tableColumns/{{{MAIN}}}tableColumn")]
        if not name or not ref:
            raise InputError("INVALID_XLSX", member, "Table name or range is missing")
        tables.append(TableProfile(name, display_name, ref, columns))
    return tables


def _is_ambiguous_locale_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = _AMBIGUOUS_DATE.match(value)
    if not match:
        return False
    first, second = int(match.group(1)), int(match.group(2))
    return first != second and 1 <= first <= 12 and 1 <= second <= 12


def _profile_sheet(name: str, rows: list[list[Any]], types: list[list[str]], tables: list[TableProfile], formula_count: int, missing_cache_count: int, parse_issues: list[str]) -> SheetProfile:
    issues = list(parse_issues)
    if formula_count:
        issues.append("Formula cells use cached results; Excel calculation was not run")
    if missing_cache_count:
        issues.append(f"{missing_cache_count} formula cell(s) have no cached result")
    formula_profile = FormulaProfile(formula_count, missing_cache_count)
    if not rows:
        return SheetProfile(name, 0, [], tables, formula_profile, [*issues, "Sheet is empty"], [], False)
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    header_valid = all(headers) and len(headers) == len(set(headers))
    if not all(headers):
        issues.append("Header contains an empty column name")
    if len(headers) != len(set(headers)):
        issues.append("Header contains duplicate column names")
    data_rows = rows[1:]
    data_types = types[1:]
    row_errors = [
        {
            "code": "XLSX_COLUMN_COUNT",
            "row_number": row_number,
            "expected_columns": len(headers),
            "actual_columns": len(row),
        }
        for row_number, row in enumerate(data_rows, start=2)
        if len(row) > len(headers)
    ]
    if row_errors:
        issues.append(f"{len(row_errors)} row(s) contain cells beyond the header and require correction")
    columns: list[ColumnProfile] = []
    for index, header in enumerate(headers):
        values = [row[index] if index < len(row) else None for row in data_rows]
        kinds = [row[index] if index < len(row) else "empty" for row in data_types]
        non_null = [value for value in values if value is not None and value != ""]
        counts = Counter((type(value).__name__, str(value)) for value in non_null)
        column_issues: list[str] = []
        if any(_is_ambiguous_locale_date(value) for value in non_null):
            column_issues.append("Ambiguous locale date text was kept as text; choose day/month order")
        numeric = [float(value) for value in non_null if isinstance(value, (int, float)) and not isinstance(value, bool)]
        normalized_name = re.sub(r"[^a-z]", "", header.lower())
        if ("discount" in normalized_name or "percent" in normalized_name or "pct" in normalized_name) and any(0 < value <= 1 for value in numeric) and any(value > 1 for value in numeric):
            column_issues.append("Percentage scale is ambiguous: values mix fractions (0..1) and whole percentages (>1)")
        columns.append(ColumnProfile(
            name=header,
            data_types=dict(Counter(kind for kind in kinds if kind != "empty")),
            null_count=len(values) - len(non_null),
            duplicate_count=sum(count - 1 for count in counts.values()),
            sample=list(dict.fromkeys(non_null))[:5],
            issues=column_issues,
        ))
    return SheetProfile(name, len(data_rows), columns, tables, formula_profile, issues, row_errors, header_valid and not row_errors)


def profile_workbook(
    path: str | Path,
    *,
    sheet_names: Iterable[str] | None = None,
    table_name: str | None = None,
    include_preview: bool = False,
    preview_limit: int | None = 20,
) -> dict[str, Any]:
    """Profile one workbook without calculating formulas or writing the file.

    Raw rows remain absent by default. The local UI may request a bounded
    preview of valid-width rows with ``include_preview=True``. ``None`` is an
    internal-only full-source read used by the local diagnostic profiler; the
    caller must keep the resulting values local and discard them after sampling.
    """
    if preview_limit is not None and (preview_limit < 1 or preview_limit > MAX_PREVIEW_ROWS):
        raise InputError(
            "PREVIEW_LIMIT",
            str(path),
            f"preview_limit must be between 1 and {MAX_PREVIEW_ROWS}",
        )
    try:
        resolved = Path(path).resolve(strict=True)
    except OSError as exc:
        raise InputError("XLSX_UNREADABLE", str(path), "Workbook cannot be accessed") from exc
    if resolved.suffix.lower() != ".xlsx":
        raise InputError("UNSUPPORTED_EXCEL", str(resolved), "Only .xlsx is supported in this slice")
    if not resolved.is_file():
        raise InputError("INVALID_XLSX", str(resolved), "Not a regular file")
    try:
        with resolved.open("rb") as source:
            signature = source.read(8)
    except PermissionError as exc:
        raise InputError("XLSX_LOCKED", str(resolved), "Workbook is locked or permission was denied") from exc
    if signature == _ENCRYPTED_OFFICE_SIGNATURE:
        raise InputError("ENCRYPTED_XLSX", str(resolved), "Password-protected workbook is not supported")
    try:
        with ZipFile(resolved) as archive:
            members = archive.infolist()
            if any(item.flag_bits & 0x1 for item in members):
                raise InputError("ENCRYPTED_XLSX", str(resolved), "Password-protected workbook is not supported")
            if sum(item.file_size for item in members) > MAX_UNCOMPRESSED:
                raise InputError("XLSX_LIMIT", str(resolved), "Workbook exceeds uncompressed size limit")
            if len({item.filename for item in members}) != len(members):
                raise InputError("INVALID_XLSX", str(resolved), "Duplicate ZIP member names")
            names = set(archive.namelist())
            if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
                raise InputError("INVALID_XLSX", str(resolved), "Workbook metadata is missing")
            strings: list[str] = []
            if "xl/sharedStrings.xml" in names:
                strings = [_text(item) for item in _read_xml(archive, "xl/sharedStrings.xml").findall(f"{{{MAIN}}}si")]
                if any(len(value) > MAX_CELL_CHARS for value in strings):
                    raise InputError("XLSX_LIMIT", str(resolved), "Shared string exceeds cell size limit")
            styles = _read_styles(archive, names)
            relationships = {
                item.get("Id"): item.get("Target")
                for item in _read_xml(archive, "xl/_rels/workbook.xml.rels").findall(f"{{{PKG_REL}}}Relationship")
            }
            workbook = _read_xml(archive, "xl/workbook.xml")
            workbook_pr = workbook.find(f"{{{MAIN}}}workbookPr")
            date_1904 = workbook_pr is not None and workbook_pr.get("date1904", "0").lower() in {"1", "true"}
            workbook_issues: list[str] = []
            if workbook.find(f"{{{MAIN}}}workbookProtection") is not None:
                workbook_issues.append("Workbook structure is protected; profiling remained read-only")
            sheet_nodes = workbook.findall(f"{{{MAIN}}}sheets/{{{MAIN}}}sheet")
            if not sheet_nodes:
                workbook_issues.append("Workbook contains no worksheets")
            requested_sheets = set(sheet_names) if sheet_names is not None else None
            available_sheets = {sheet.get("name", "") for sheet in sheet_nodes}
            if requested_sheets is not None:
                missing_sheets = sorted(requested_sheets - available_sheets)
                if missing_sheets:
                    raise InputError("XLSX_SHEET_NOT_FOUND", str(resolved), f"Worksheet(s) not found: {', '.join(missing_sheets)}")
                sheet_nodes = [sheet for sheet in sheet_nodes if sheet.get("name", "") in requested_sheets]
            sheets: list[dict[str, Any]] = []
            selected_table_found = False
            for sheet in sheet_nodes:
                name = sheet.get("name", "")
                target = relationships.get(sheet.get(f"{{{REL}}}id"))
                if not target:
                    raise InputError("INVALID_XLSX", str(resolved), f"Sheet {name!r} has no relationship")
                member = _safe_member("xl/workbook.xml", target, names, label=f"sheet for {name!r}")
                rows, types, row_numbers, formula_count, missing_cache_count, parse_issues, sheet_root = _sheet_rows(archive, member, strings, styles, date_1904)
                tables = _sheet_tables(archive, names, member, sheet_root)
                if table_name is not None:
                    selected = next((table for table in tables if table.name == table_name or table.display_name == table_name), None)
                    if selected is None:
                        continue
                    rows, types = _slice_table(rows, types, row_numbers, selected.ref)
                    tables = [selected]
                    selected_table_found = True
                sheet_profile = asdict(
                    _profile_sheet(
                        name,
                        rows,
                        types,
                        tables,
                        formula_count,
                        missing_cache_count,
                        parse_issues,
                    )
                )
                if include_preview:
                    headers = [
                        str(value).strip() if value is not None else ""
                        for value in (rows[0] if rows else [])
                    ]
                    valid_rows = [
                        (row + [None] * len(headers))[:len(headers)]
                        for row in rows[1:]
                        if len(row) <= len(headers)
                    ]
                    sheet_profile["preview"] = {
                        "columns": headers,
                        "rows": valid_rows if preview_limit is None else valid_rows[:preview_limit],
                        "limit": preview_limit,
                        "truncated": preview_limit is not None and len(valid_rows) > preview_limit,
                        "excluded_error_rows": len(sheet_profile["row_errors"]),
                    }
                sheets.append(sheet_profile)
            if table_name is not None and not selected_table_found:
                raise InputError("XLSX_TABLE_NOT_FOUND", str(resolved), f"Table not found: {table_name}")
            return {
                "path": str(resolved), "date_system": "1904" if date_1904 else "1900",
                "selected_sheets": sorted(requested_sheets) if requested_sheets is not None else None,
                "selected_table": table_name,
                "sheets": sheets, "issues": workbook_issues,
            }
    except BadZipFile as exc:
        raise InputError("INVALID_XLSX", str(resolved), "Not a valid .xlsx ZIP archive") from exc
    except PermissionError as exc:
        raise InputError("XLSX_LOCKED", str(resolved), "Workbook is locked or permission was denied") from exc


def compare_workbook_schemas(profiles: Iterable[dict[str, Any]], *, sheet_name: str | None = None) -> dict[str, Any]:
    """Compare selected sheets across already-read workbook profiles."""
    selected: list[dict[str, Any]] = []
    for profile in profiles:
        sheets = profile.get("sheets", [])
        sheet = next((item for item in sheets if item.get("name") == sheet_name), None) if sheet_name else (sheets[0] if sheets else None)
        selected.append({"path": profile.get("path", ""), "sheet": sheet})
    baseline_entry = next((entry for entry in selected if entry["sheet"] is not None), None)
    if baseline_entry is None:
        return {"status": "insufficient_data", "baseline": None, "comparisons": []}
    baseline_sheet = baseline_entry["sheet"]
    baseline_names = [column["name"] for column in baseline_sheet.get("columns", [])]
    baseline_types = {column["name"]: set(column.get("data_types", {})) for column in baseline_sheet.get("columns", [])}
    comparisons: list[dict[str, Any]] = []
    has_drift = False
    for entry in selected:
        sheet = entry["sheet"]
        if sheet is None:
            comparison = {"path": entry["path"], "sheet": sheet_name, "missing_sheet": True, "missing_columns": baseline_names, "added_columns": [], "order_changed": False, "type_changes": {}}
        else:
            names = [column["name"] for column in sheet.get("columns", [])]
            current_types = {column["name"]: set(column.get("data_types", {})) for column in sheet.get("columns", [])}
            shared = set(baseline_names) & set(names)
            type_changes = {
                name: {"baseline": sorted(baseline_types[name]), "current": sorted(current_types[name])}
                for name in sorted(shared) if baseline_types[name] != current_types[name]
            }
            comparison = {
                "path": entry["path"], "sheet": sheet.get("name"), "missing_sheet": False,
                "missing_columns": [name for name in baseline_names if name not in names],
                "added_columns": [name for name in names if name not in baseline_names],
                "order_changed": [name for name in names if name in shared] != [name for name in baseline_names if name in shared],
                "type_changes": type_changes,
            }
        if comparison["missing_sheet"] or comparison["missing_columns"] or comparison["added_columns"] or comparison["order_changed"] or comparison["type_changes"]:
            has_drift = True
        comparisons.append(comparison)
    return {
        "status": "schema_drift" if has_drift else "consistent",
        "baseline": {"path": baseline_entry["path"], "sheet": baseline_sheet.get("name"), "columns": baseline_names},
        "comparisons": comparisons,
    }


def profile_workbooks(paths: Iterable[str | Path], *, sheet_name: str | None = None) -> dict[str, Any]:
    """Profile multiple workbooks and include a deterministic schema comparison."""
    workbooks = [profile_workbook(path) for path in paths]
    return {"workbooks": workbooks, "schema_comparison": compare_workbook_schemas(workbooks, sheet_name=sheet_name)}
