"""Oracle độc lập cho csv_typing (feature 003, T302).

Viết tay từ spec §6 và contract; KHÔNG import module đang được kiểm
(``pbip_assistant.sources.preparation.csv_typing``) để tránh kiểm tra vòng tròn.
Chỉ cung cấp hằng số + phép tính serial tham chiếu.
"""

from __future__ import annotations

from datetime import date

TEXT = "@"
DATE = "yyyy-mm-dd"
NUMBER = "General"

MAX_DECISIONS = 200
MAX_SAMPLES = 2
MAX_SAMPLE_CHARS = 40

FORMULA_LIKE_TEXT = "FORMULA_LIKE_TEXT"
LEADING_ZERO_TEXT = "LEADING_ZERO_TEXT"
GROUP_SEPARATOR = "GROUP_SEPARATOR"
DECIMAL_DOT = "DECIMAL_DOT"
DECIMAL_COMMA = "DECIMAL_COMMA"
PRECISION_TEXT = "PRECISION_TEXT"
DATE_ORDER_DETECTED = "DATE_ORDER_DETECTED"
DATE_DMY_DEFAULT = "DATE_DMY_DEFAULT"
INVALID_DATE_TEXT = "INVALID_DATE_TEXT"
DATE_UNSUPPORTED_TEXT = "DATE_UNSUPPORTED_TEXT"
MIXED_TYPE_TEXT = "MIXED_TYPE_TEXT"
EMPTY_COLUMN = "EMPTY_COLUMN"


def serial(year: int, month: int, day: int, date_system) -> int:
    """Serial Excel độc lập: 1900 dùng gốc 1899-12-30 (và 1899-12-31 trước 1900-03-01)."""
    value = date(year, month, day)
    if str(date_system) == "1904":
        return (value - date(1904, 1, 1)).days
    origin = date(1899, 12, 31) if value < date(1900, 3, 1) else date(1899, 12, 30)
    return (value - origin).days


def column(frame: dict, index: int) -> list:
    """Lấy một cột từ frame (bỏ dòng header)."""
    return [row[index] for row in frame["values"][1:]]


def formats(frame: dict, index: int) -> list:
    return [row[index] for row in frame["numberFormats"][1:]]


def reason_of(frame: dict, name: str) -> str | None:
    for decision in frame["decisions"]:
        if decision["column"] == name:
            return decision["reasonCode"]
    return None
