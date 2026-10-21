"""Bounded workbook metadata contract shared by planners and adapters.

This normalization only reads the supplied Office.js snapshot; it cannot grant
runtime or write authority and never accesses the workbook file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pbip_assistant.errors import InputError

MAX_SHEETS = 20
MAX_COLUMNS = 200
MAX_ROWS = 20
MAX_CELL_CHARS = 1_000


def _text(value: Any, target: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise InputError("INVALID_WORKBOOK", target, "Expected a non-empty text value of at most 200 characters")
    return value


def _cell(value: Any, target: str) -> str | int | float | bool | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str) and len(value) <= MAX_CELL_CHARS:
        return value
    raise InputError("INVALID_WORKBOOK", target, "Cell is not a bounded JSON scalar")


def _bounded_source(source: Any, index: int, *, table: bool) -> dict[str, Any]:
    path = f"workbook.{'tables' if table else 'sheets'}[{index}]"
    if not isinstance(source, dict):
        raise InputError("INVALID_WORKBOOK", path, "Sheet/table metadata must be an object")
    sheet = _text(source.get("sheet") if table else source.get("name"), path + ".sheet")
    headers = source.get("headers")
    rows = source.get("rows")
    if not isinstance(headers, list) or not 0 < len(headers) <= MAX_COLUMNS:
        raise InputError("INVALID_WORKBOOK", path + ".headers", "Headers are missing or exceed limit")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise InputError("INVALID_WORKBOOK", path + ".rows", "Preview rows exceed limit")
    clean_headers = [_text(value, path + ".headers") for value in headers]
    clean_rows = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(clean_headers):
            raise InputError("INVALID_WORKBOOK", path + ".rows", "Row width must match headers")
        clean_rows.append([_cell(value, f"{path}.rows[{row_index}]") for value in row])
    result = {"sheet": sheet, "headers": clean_headers, "rows": clean_rows}
    inferred_types = source.get("inferredTypes")
    allowed_types = {"any", "text", "integer", "number", "logical", "date", "datetime"}
    if inferred_types is not None:
        if (
            not isinstance(inferred_types, list) or len(inferred_types) != len(clean_headers)
            or any(value not in allowed_types for value in inferred_types)
        ):
            raise InputError("INVALID_WORKBOOK", path + ".inferredTypes", "Inferred types must match the source columns")
        result["inferredTypes"] = list(inferred_types)
    total_rows = source.get("totalRows", len(clean_rows))
    total_columns = source.get("totalColumns", len(clean_headers))
    if (
        not isinstance(total_rows, int) or total_rows < len(clean_rows) or total_rows > 1_048_576
        or not isinstance(total_columns, int) or total_columns < len(clean_headers) or total_columns > 16_384
    ):
        raise InputError("INVALID_WORKBOOK", path, "Total row/column counts are invalid")
    result["totalRows"] = total_rows
    result["totalColumns"] = total_columns
    result["sampleOnly"] = total_rows > len(clean_rows) or total_columns > len(clean_headers)
    if table:
        result["table"] = _text(source.get("name"), path + ".name")
    else:
        letters = source.get("columnLetters")
        if not isinstance(letters, list) or len(letters) != len(clean_headers) or not all(
            isinstance(value, str) and value.isalpha() and len(value) <= 3 for value in letters
        ):
            raise InputError("INVALID_WORKBOOK", path + ".columnLetters", "Column letters are invalid")
        result["columnLetters"] = [value.upper() for value in letters]
        header_row = source.get("headerRow")
        if not isinstance(header_row, int) or not 1 <= header_row <= 1_048_576:
            raise InputError("INVALID_WORKBOOK", path + ".headerRow", "Header row is invalid")
        result["headerRow"] = header_row
    return result


def snapshot_workbook(workbook: Any) -> dict[str, Any]:
    if not isinstance(workbook, dict):
        raise InputError("INVALID_WORKBOOK", "workbook", "Workbook metadata must be an object")
    name = _text(workbook.get("name"), "workbook.name")
    if Path(name).name != name:
        raise InputError("INVALID_WORKBOOK", "workbook.name", "Workbook name must not contain a path")
    tables = workbook.get("tables", [])
    sheets = workbook.get("sheets", [])
    if not isinstance(tables, list) or not isinstance(sheets, list) or len(tables) + len(sheets) > MAX_SHEETS:
        raise InputError("INVALID_WORKBOOK", "workbook", "Too many sheets/tables")
    sources = [
        *[_bounded_source(value, index, table=True) for index, value in enumerate(tables)],
        *[_bounded_source(value, index, table=False) for index, value in enumerate(sheets)],
    ]
    if not sources:
        raise InputError("EMPTY_WORKBOOK", "workbook", "No readable table or used range was found")
    return {"name": name, "activeSheet": str(workbook.get("activeSheet", ""))[:200], "sources": sources}

