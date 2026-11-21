"""Suy luận kiểu cột cho CSV (spec 003 §6): thuần, tất định, không I/O.

``build_typed_frame`` nhận header + các dòng dữ liệu và trả frame đã định kiểu
(values/numberFormats/decisions/issues) để ``packages.py`` ghi thẳng vào Excel.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal

__all__ = ["build_typed_frame", "describe_columns"]

TEXT_FORMAT = "@"
DATE_FORMAT = "yyyy-mm-dd"
NUMBER_FORMAT = "General"

MAX_DECISIONS = 200
MAX_SAMPLES = 2
MAX_SAMPLE_CHARS = 40
MAX_SIGNIFICANT_DIGITS = 15
MIN_NORMAL = Decimal("2.2250738585072014e-308")

_RE_NUMBER_DOT = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")
_RE_NUMBER_COMMA = re.compile(r"^[+-]?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$")
_RE_DATE = re.compile(r"^(\d{1,4})[/.-](\d{1,2})[/.-](\d{1,4})$")
_RE_LEADING_ZERO = re.compile(r"^0\d+$")
_RE_GROUPED = re.compile(r"[+-]?\d{1,3}([.,])\d{3}(?:\1\d{3})*")
_RE_DATETIME = re.compile(r"^\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}[T ]\d{1,2}:\d{2}")
_FORMULA_PREFIXES = ("=", "+", "@")


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _formula_like(value: str) -> bool:
    if not value:
        return False
    if value[0] in _FORMULA_PREFIXES:
        return True
    if value[0] == "-":
        return not (_RE_NUMBER_DOT.fullmatch(value) or _RE_NUMBER_COMMA.fullmatch(value))
    return False


def _significant_digits(value: str) -> int:
    digits = [char for char in value if char.isdigit()]
    while digits and digits[0] == "0":
        digits.pop(0)
    return len(digits)


def _numeric_or_date_like(value: str) -> bool:
    if (_RE_NUMBER_DOT.fullmatch(value) or _RE_NUMBER_COMMA.fullmatch(value)
            or _RE_DATE.fullmatch(value) or _RE_DATETIME.match(value)):
        return True
    # Unsupported percentage and currency values are retained as text and reported.
    token = value
    if value.endswith("%") or unicodedata.category(value[-1]) == "Sc":
        token = value[:-1].strip()
    elif unicodedata.category(value[0]) == "Sc":
        token = value[1:].strip()
    return token != value and bool(_RE_NUMBER_DOT.fullmatch(token) or _RE_NUMBER_COMMA.fullmatch(token))


def _decimal_dot(value: str) -> Decimal:
    return Decimal(value.replace(",", ""))


def _decimal_comma(value: str) -> Decimal:
    return Decimal(value.replace(".", "").replace(",", "."))


def _number_cells(values: list[str]):
    """Trả (cells, reason) hoặc None nếu cột không phải số."""
    dot_ok = all(_RE_NUMBER_DOT.match(value) for value in values)
    comma_ok = all(_RE_NUMBER_COMMA.match(value) for value in values)
    if not dot_ok and not comma_ok:
        return None
    punctuated = [value for value in values if "." in value or "," in value]
    if punctuated and all(_RE_GROUPED.fullmatch(value) for value in punctuated):
        integers = [Decimal(value.replace(".", "").replace(",", "")) for value in values]
        return integers, "GROUP_SEPARATOR"
    if dot_ok:
        return [_decimal_dot(value) for value in values], "DECIMAL_DOT"
    return [_decimal_comma(value) for value in values], "DECIMAL_COMMA"


def _date_order(parts: list[tuple[str, str, str]]) -> str | None:
    if all(len(first) == 4 for first, _, _ in parts):
        return "YMD"
    if any(len(first) != 4 and len(last) != 4 for first, _, last in parts):
        return None
    if any(len(last) != 4 for _, _, last in parts):
        return None
    firsts = [int(first) for first, _, _ in parts]
    seconds = [int(second) for _, second, _ in parts]
    first_over = any(value > 12 for value in firsts)
    second_over = any(value > 12 for value in seconds)
    if first_over and second_over:
        return None
    if first_over:
        return "DMY"
    if second_over:
        return "MDY"
    return "DMY"


def _parse_dates(values: list[str]):
    """Trả (order, dates, reason) hoặc None."""
    matches = [_RE_DATE.match(value) for value in values]
    if any(match is None for match in matches):
        return None
    parts = [(match.group(1), match.group(2), match.group(3)) for match in matches]
    order = _date_order(parts)
    if order is None:
        return None
    dates = []
    for first, second, last in parts:
        try:
            if order == "YMD":
                dates.append(date(int(first), int(second), int(last)))
            elif order == "DMY":
                dates.append(date(int(last), int(second), int(first)))
            else:
                dates.append(date(int(last), int(first), int(second)))
        except ValueError:
            return None
    firsts = [int(first) for first, _, _ in parts]
    seconds = [int(second) for _, second, _ in parts]
    detected = order == "YMD" or any(value > 12 for value in firsts) or any(
        value > 12 for value in seconds
    )
    return order, dates, ("DATE_ORDER_DETECTED" if detected else "DATE_DMY_DEFAULT")


def _serial(value: date, date_system: str) -> int:
    if str(date_system) == "1904":
        return (value - date(1904, 1, 1)).days
    origin = date(1899, 12, 31) if value < date(1900, 3, 1) else date(1899, 12, 30)
    return (value - origin).days


def _sample(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value[:MAX_SAMPLE_CHARS])
        if len(seen) >= MAX_SAMPLES:
            break
    return seen


def _decision(column: str, index: int, kind: str, number_format: str, reason: str,
              rows: int, samples: list[str]) -> dict:
    return {"column": column, "columnIndex": index, "kind": kind,
            "numberFormat": number_format, "reasonCode": reason,
            "affectedRows": rows, "samples": samples}


def _decide(column: str, index: int, cells: list[str], date_system: str):
    """Trả (kind, numberFormat, reasonCode, converted cells, decision|None)."""
    filled = [value for value in cells if value]
    if not filled:
        return "text", NUMBER_FORMAT, "EMPTY_COLUMN", [], True
    if any(_formula_like(value) for value in filled):
        return "text", TEXT_FORMAT, "FORMULA_LIKE_TEXT", list(filled), True
    if any(_RE_LEADING_ZERO.match(value) for value in filled):
        return "text", TEXT_FORMAT, "LEADING_ZERO_TEXT", list(filled), True

    numbers = _number_cells(filled)
    if numbers is not None:
        cells_out, reason = numbers
        if any(_significant_digits(value) > MAX_SIGNIFICANT_DIGITS
               or (cell != 0 and abs(cell) < MIN_NORMAL)
               for value, cell in zip(filled, cells_out)):
            return "text", TEXT_FORMAT, "PRECISION_TEXT", list(filled), True
        typed = [int(cell) if cell == cell.to_integral_value() else float(cell)
                 for cell in cells_out]
        report = reason != "DECIMAL_DOT" or any("," in value for value in filled)
        return "number", NUMBER_FORMAT, reason, typed, report

    parsed = _parse_dates(filled)
    if parsed is not None:
        _order, dates, reason = parsed
        return "date", DATE_FORMAT, reason, [_serial(day, date_system) for day in dates], True

    date_matches = [_RE_DATE.match(value) for value in filled]
    if all(match is not None for match in date_matches):
        unsupported = all(len(match.group(1)) != 4 and len(match.group(3)) != 4
                          for match in date_matches)
        reason = "DATE_UNSUPPORTED_TEXT" if unsupported else "INVALID_DATE_TEXT"
        return "text", TEXT_FORMAT, reason, list(filled), True

    mixed = any(_numeric_or_date_like(value) for value in filled)
    return "text", TEXT_FORMAT, "MIXED_TYPE_TEXT", list(filled), mixed


def build_typed_frame(headers, rows, *, date_system) -> dict:
    """Dựng frame đã định kiểu, gồm dòng header (luôn text) và các dòng dữ liệu."""
    headers = [_text(value) for value in headers]
    data = [[_text(cell) for cell in list(row)] for row in rows]
    width = len(headers)
    for row in data:
        if len(row) < width:
            row.extend([""] * (width - len(row)))

    values: list[list] = [list(headers)]
    formats: list[list[str]] = [[TEXT_FORMAT] * width]
    decisions: list[dict] = []

    for index, column in enumerate(headers):
        cells = [row[index] for row in data]
        kind, number_format, reason, converted, report = _decide(column, index, cells, date_system)
        filled = [value for value in cells if value]
        if report and len(decisions) < MAX_DECISIONS:
            decisions.append(_decision(column, index, kind, number_format, reason,
                                       len(filled), _sample(filled)))
        # Ô CSV rỗng ở lại rỗng (null) với numberFormat General, không ghi text.
        iterator = iter(converted)
        column_values = [None if cell == "" else next(iterator) for cell in cells]
        for row_index, value in enumerate(column_values, start=1):
            if row_index >= len(values):
                values.append([None] * width)
                formats.append([NUMBER_FORMAT] * width)
            values[row_index][index] = value
            formats[row_index][index] = NUMBER_FORMAT if value is None else number_format

    return {"values": values, "numberFormats": formats,
            "decisions": decisions, "issues": []}


def describe_columns(headers, rows) -> dict:
    """Đếm nhanh số cột theo kiểu dự kiến cho FileSummary (không dựng cả frame)."""
    headers = [_text(value) for value in headers]
    data = [[_text(cell) for cell in list(row)] for row in rows]
    kinds = {"number": 0, "date": 0, "text": 0}
    for index in range(len(headers)):
        cells = [row[index] if index < len(row) else "" for row in data]
        kind, _format, _reason, _converted, _report = _decide(
            headers[index], index, cells, "1900")
        kinds[kind] += 1
    return {"columnCount": len(headers), "kinds": kinds}
