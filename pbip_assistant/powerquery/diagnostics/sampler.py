"""Deterministic, bounded source sampling for Typed Step diagnostics.

The sampler scans rows already extracted from a workbook, but only returns a
small set of raw values.  Profile metadata and samples are session-memory data;
callers must not persist them in Problem Chain Custom XML or write cell values
to logs.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import math
from threading import Lock
from typing import Any, Sequence
import unicodedata

from pbip_assistant.errors import InputError


SAMPLER_POLICY_VERSION = "pq-diagnostic-sampler-v1"
MAX_SAMPLE_ROWS = 20
MAX_SAMPLE_COLUMNS = 200
LONG_TEXT_THRESHOLD = 128

_REASON_ORDER = (
    "head", "middle", "tail", "blank", "longText", "unusualText",
    "numericExtreme", "dateExtreme", "seededRandom",
)
_HARD_REASONS = (
    "blank", "longText", "unusualText", "numericExtreme", "dateExtreme",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _seed(source_data_fingerprint: str, source_id: str) -> str:
    digest = hashlib.sha256(_canonical([
        source_data_fingerprint, source_id, SAMPLER_POLICY_VERSION,
    ])).hexdigest()
    return f"sha256:{digest}"


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _date_sort_key(value: Any, declared_type: str | None) -> tuple[int, int, int, int, int, int, int] | None:
    parsed: date | datetime | None = value if isinstance(value, (date, datetime)) else None
    if parsed is None and declared_type in {"date", "datetime", "datetimezone"} and isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else date.fromisoformat(value)
        except ValueError:
            return None
    if parsed is None:
        return None
    if isinstance(parsed, datetime):
        return (parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute, parsed.second, parsed.microsecond)
    return (parsed.year, parsed.month, parsed.day, 0, 0, 0, 0)


def _is_unusual_text(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    symbol_count = 0
    for character in value:
        category = unicodedata.category(character)
        if category in {"Cc", "Cf", "Cs", "Co", "Cn"} or character == "\ufffd":
            return True
        if category.startswith("S"):
            symbol_count += 1
    return symbol_count >= 1


def _validate_rows(rows: Sequence[Sequence[Any]]) -> tuple[list[Sequence[Any]], int]:
    if isinstance(rows, (str, bytes, bytearray)) or not isinstance(rows, Sequence):
        raise InputError("TSD_SAMPLE_INVALID", "rows", "Source rows must be an array")
    source_rows: list[Sequence[Any]] = []
    width = 0
    for row in rows:
        if isinstance(row, (str, bytes, bytearray)) or not isinstance(row, Sequence):
            raise InputError("TSD_SAMPLE_INVALID", "rows", "Each source row must be an array")
        width = max(width, len(row))
        source_rows.append(row)
    if width > MAX_SAMPLE_COLUMNS:
        raise InputError(
            "TSD_SAMPLE_COLUMN_LIMIT", "rows",
            f"Diagnostic sampling supports at most {MAX_SAMPLE_COLUMNS} columns",
        )
    # Keep rectangular input rows by reference while scanning.  A 100k x 75
    # source must not be duplicated merely to select twenty samples.
    normalized: list[Sequence[Any]] = [
        row if len(row) == width else [*row, *([None] * (width - len(row)))]
        for row in source_rows
    ]
    return normalized, width


def _column_order(width: int, selected_column_indices: Sequence[int]) -> list[int]:
    selected: list[int] = []
    seen: set[int] = set()
    for value in selected_column_indices:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value >= width:
            raise InputError(
                "TSD_SAMPLE_INVALID", "selectedColumnIndices",
                "Selected column index is outside the source schema",
            )
        if value not in seen:
            seen.add(value)
            selected.append(value)
    return selected + [index for index in range(width) if index not in seen]


def _hard_candidates(
    rows: list[Sequence[Any]], column_order: list[int], column_types: Sequence[str] | None,
) -> dict[str, list[int]]:
    candidates = {reason: [] for reason in _HARD_REASONS}
    for column in column_order:
        blank_index: int | None = None
        longest: tuple[int, int] | None = None
        unusual_index: int | None = None
        number_min: tuple[float, int] | None = None
        number_max: tuple[float, int] | None = None
        date_min: tuple[tuple[int, int, int, int, int, int, int], int] | None = None
        date_max: tuple[tuple[int, int, int, int, int, int, int], int] | None = None
        declared_type = column_types[column] if column_types is not None else None
        for row_index, row in enumerate(rows):
            value = row[column]
            if blank_index is None and _is_blank(value):
                blank_index = row_index
            if isinstance(value, str) and len(value) >= LONG_TEXT_THRESHOLD:
                item = (len(value), row_index)
                if longest is None or item > longest:
                    longest = item
            if unusual_index is None and _is_unusual_text(value):
                unusual_index = row_index
            if _is_number(value):
                item = (float(value), row_index)
                if number_min is None or item < number_min:
                    number_min = item
                if number_max is None or item > number_max:
                    number_max = item
            date_key = _date_sort_key(value, declared_type)
            if date_key is not None:
                item = (date_key, row_index)
                if date_min is None or item < date_min:
                    date_min = item
                if date_max is None or item > date_max:
                    date_max = item
        if blank_index is not None:
            candidates["blank"].append(blank_index)
        if longest is not None:
            candidates["longText"].append(longest[1])
        if unusual_index is not None:
            candidates["unusualText"].append(unusual_index)
        if number_min is not None and number_max is not None:
            candidates["numericExtreme"].append(number_min[1])
            if number_max[1] != number_min[1]:
                candidates["numericExtreme"].append(number_max[1])
        if date_min is not None and date_max is not None:
            candidates["dateExtreme"].append(date_min[1])
            if date_max[1] != date_min[1]:
                candidates["dateExtreme"].append(date_max[1])
    return candidates


def build_source_sample(
    rows: Sequence[Sequence[Any]], *, source_id: str,
    source_data_fingerprint: str, column_names: Sequence[str] | None = None,
    column_types: Sequence[str] | None = None,
    selected_column_indices: Sequence[int] = (), max_rows: int = MAX_SAMPLE_ROWS,
) -> dict[str, Any]:
    """Build a repeatable diagnostic sample without claiming representativeness.

    ``rows`` contains data rows only; returned ordinals are one-based data-row
    ordinals (the worksheet header is not counted).  No cell value is included
    in exception messages.
    """
    if not isinstance(source_id, str) or not source_id:
        raise InputError("TSD_SAMPLE_INVALID", "sourceId", "Source ID is required")
    if not isinstance(source_data_fingerprint, str) or not source_data_fingerprint:
        raise InputError("TSD_SAMPLE_INVALID", "sourceDataFingerprint", "Source fingerprint is required")
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or not 1 <= max_rows <= MAX_SAMPLE_ROWS:
        raise InputError(
            "TSD_SAMPLE_INVALID", "maxRows",
            f"Sample size must be between 1 and {MAX_SAMPLE_ROWS}",
        )
    normalized, width = _validate_rows(rows)
    if column_names is not None:
        if isinstance(column_names, (str, bytes, bytearray)) or not isinstance(column_names, Sequence):
            raise InputError("TSD_SAMPLE_INVALID", "columnNames", "Column names must be an array")
        if len(column_names) != width or any(not isinstance(value, str) for value in column_names):
            raise InputError("TSD_SAMPLE_INVALID", "columnNames", "Column names must match source width")
    if column_types is not None:
        if isinstance(column_types, (str, bytes, bytearray)) or not isinstance(column_types, Sequence):
            raise InputError("TSD_SAMPLE_INVALID", "columnTypes", "Column types must be an array")
        if len(column_types) != width or any(not isinstance(value, str) for value in column_types):
            raise InputError("TSD_SAMPLE_INVALID", "columnTypes", "Column types must match source width")
    order = _column_order(width, selected_column_indices)
    seed = _seed(source_data_fingerprint, source_id)
    reasons: dict[int, set[str]] = {}
    chosen: list[int] = []

    def choose(index: int, reason: str) -> None:
        if index < 0 or index >= len(normalized):
            return
        reasons.setdefault(index, set()).add(reason)
        if index not in chosen and len(chosen) < max_rows:
            chosen.append(index)

    row_count = len(normalized)
    for index in range(min(2, row_count)):
        choose(index, "head")
    if row_count:
        for index in sorted({(row_count - 1) // 2, row_count // 2}):
            choose(index, "middle")
    for index in range(max(0, row_count - 2), row_count):
        choose(index, "tail")

    candidates = _hard_candidates(normalized, order, column_types)
    coverage: dict[str, str] = {}
    for reason in _HARD_REASONS:
        values = candidates[reason]
        if values:
            choose(values[0], reason)
        coverage[reason] = (
            "selected" if values and values[0] in chosen
            else "foundNotSelected" if values else "notFound"
        )

    # Use the remaining budget fairly across hard-case categories/columns
    # before filling with pseudo-random rows. Candidate lists are already
    # ordered with selected-step columns first.
    offsets = {reason: 1 for reason in _HARD_REASONS}
    while len(chosen) < max_rows:
        progressed = False
        for reason in _HARD_REASONS:
            offset = offsets[reason]
            values = candidates[reason]
            if offset >= len(values):
                continue
            choose(values[offset], reason)
            offsets[reason] = offset + 1
            progressed = True
            if len(chosen) >= max_rows:
                break
        if not progressed:
            break

    # Stable digest ranking avoids reliance on process state or Math.random().
    seed_text = seed.removeprefix("sha256:")
    remaining = [index for index in range(row_count) if index not in chosen]
    remaining.sort(key=lambda index: hashlib.sha256(
        f"{seed_text}:{index + 1}".encode("ascii")
    ).digest())
    for index in remaining:
        choose(index, "seededRandom")
        if len(chosen) >= max_rows:
            break

    sample_rows = []
    for index in chosen:
        row_reasons = reasons.get(index, {"seededRandom"})
        sample_rows.append({
            "ordinal": index + 1,
            "reasonCodes": [reason for reason in _REASON_ORDER if reason in row_reasons],
            "values": deepcopy(normalized[index]),
        })
    return {
        "samplerPolicyVersion": SAMPLER_POLICY_VERSION,
        "seed": seed,
        "rowCount": row_count,
        "columnCount": width,
        "profileIncomplete": False,
        "coverage": coverage,
        "sampleRows": sample_rows,
    }


class SourceProfileCache:
    """Small FIFO session cache for source profile/sample results."""

    def __init__(self, *, max_entries: int = 20) -> None:
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple[str, str, str, int, str, tuple[int, ...]], dict[str, Any]] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def _key(
        *, workbook_identity: str, source_id: str,
        source_data_fingerprint: str, data_version: int,
        selected_column_indices: Sequence[int] = (),
    ) -> tuple[str, str, str, int, str, tuple[int, ...]]:
        if not isinstance(workbook_identity, str) or not workbook_identity:
            raise InputError("TSD_SAMPLE_INVALID", "workbookIdentity", "Workbook identity is required")
        if not isinstance(source_id, str) or not source_id:
            raise InputError("TSD_SAMPLE_INVALID", "sourceId", "Source ID is required")
        if not isinstance(source_data_fingerprint, str) or not source_data_fingerprint:
            raise InputError("TSD_SAMPLE_INVALID", "sourceDataFingerprint", "Source fingerprint is required")
        if isinstance(data_version, bool) or not isinstance(data_version, int) or data_version < 0:
            raise InputError("TSD_SAMPLE_INVALID", "dataVersion", "Data version must be a non-negative integer")
        return (
            workbook_identity, source_id, source_data_fingerprint,
            data_version, SAMPLER_POLICY_VERSION, tuple(selected_column_indices),
        )

    def get_cached(
        self, *, workbook_identity: str, source_id: str,
        source_data_fingerprint: str, data_version: int,
        selected_column_indices: Sequence[int] = (),
    ) -> dict[str, Any] | None:
        """Return a cached profile before callers perform an expensive source scan."""

        key = self._key(
            workbook_identity=workbook_identity, source_id=source_id,
            source_data_fingerprint=source_data_fingerprint, data_version=data_version,
            selected_column_indices=selected_column_indices,
        )
        with self._lock:
            cached = self._entries.get(key)
            return deepcopy(cached) if cached is not None else None

    def get_or_build(
        self, *, workbook_identity: str, source_id: str,
        source_data_fingerprint: str, data_version: int,
        rows: Sequence[Sequence[Any]], column_names: Sequence[str] | None = None,
        column_types: Sequence[str] | None = None,
        selected_column_indices: Sequence[int] = (),
    ) -> tuple[dict[str, Any], bool]:
        key = self._key(
            workbook_identity=workbook_identity, source_id=source_id,
            source_data_fingerprint=source_data_fingerprint, data_version=data_version,
            selected_column_indices=selected_column_indices,
        )
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                return deepcopy(cached), True
        built = build_source_sample(
            rows, source_id=source_id,
            source_data_fingerprint=source_data_fingerprint,
            column_names=column_names, column_types=column_types,
            selected_column_indices=selected_column_indices,
        )
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                return deepcopy(cached), True
            self._entries[key] = deepcopy(built)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return deepcopy(built), False

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
