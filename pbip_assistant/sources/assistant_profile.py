"""Deterministic WL1 table profiles and snapshots over ingested raw strings."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import re

from .assistant_ingest import canonical_hash


_PREVIEW_ROWS = 20
_DEFAULT_CREATED_AT = "2026-10-26T09:00:00Z"
_HASH_BASIS = ("snapshot", "sources", "tables")
_SOURCE_TYPES = frozenset({"csv", "xlsx", "folder", "workbook"})


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _ratio(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0.0
    return float((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP,
    ))


def _table_id(source_id: str, name: str) -> str:
    return "tbl_" + hashlib.sha256((source_id + name).encode("utf-8")).hexdigest()[:12]


def profile_table(raw_table: dict) -> dict:
    """Profile all raw rows, retaining only the first twenty sample values."""
    if not isinstance(raw_table, dict):
        raise ValueError("raw_table must be an object")
    source_id = _text(raw_table.get("sourceId"), "raw_table.sourceId")
    name = _text(raw_table.get("name"), "raw_table.name")
    header = raw_table.get("header")
    rows = raw_table.get("rows")
    locator = raw_table.get("locator")
    if not isinstance(header, list) or not header or any(not isinstance(item, str) for item in header):
        raise ValueError("raw_table.header must be a nonempty string array")
    if len(header) != len(set(header)) or any(not item for item in header):
        raise ValueError("raw_table.header must contain unique nonempty names")
    if not isinstance(rows, list):
        raise ValueError("raw_table.rows must be an array")
    if not isinstance(locator, dict):
        raise ValueError("raw_table.locator must be an object")
    for row in rows:
        if not isinstance(row, list) or len(row) != len(header):
            raise ValueError("raw_table rows must match the header width")
        if any(not isinstance(cell, str) for cell in row):
            raise ValueError("raw_table cells must remain raw strings")

    columns = []
    for index, column_name in enumerate(header):
        values = [row[index] for row in rows]
        distinct_count = len({value for value in values if value != ""})
        columns.append({
            "name": column_name,
            "type": "text",
            "nullRate": _ratio(sum(value == "" for value in values), len(rows)),
            "distinctCount": distinct_count,
            "distinctRatio": _ratio(distinct_count, len(rows)),
            "sample": values[:_PREVIEW_ROWS],
            "role": None,
            "roleStatus": "unknown",
            "evidence": [],
        })
    sample = deepcopy(rows[:_PREVIEW_ROWS])
    return {
        "id": _table_id(source_id, name),
        "sourceId": source_id,
        "name": name,
        "locator": deepcopy(locator),
        "rowCount": len(rows),
        "columnCount": len(header),
        "headerHash": canonical_hash(header),
        "sampleHash": canonical_hash(sample),
        "fingerprint": canonical_hash({"name": name, "header": header, "sample": sample}),
        "columns": columns,
    }


def snapshot_hash(snapshot: dict) -> str:
    """Hash content fields while excluding snapshot/source capture timestamps."""
    if not isinstance(snapshot, dict) or snapshot.get("hashBasis") != list(_HASH_BASIS):
        raise ValueError("snapshot.hashBasis must name snapshot, sources and tables")
    try:
        content = {key: deepcopy(snapshot[key]) for key in _HASH_BASIS}
        content["snapshot"].pop("createdAt", None)
        for source in content["sources"]:
            source.pop("addedAt", None)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("snapshot content does not match the WL1 shape") from exc
    return canonical_hash(content)


def build_snapshot(
    ingest_result: dict,
    *,
    snapshot_id: str | None = None,
    created_at: str = _DEFAULT_CREATED_AT,
) -> dict:
    """Create a sorted WL1 snapshot without changing the ingest result."""
    if not isinstance(ingest_result, dict):
        raise ValueError("ingest_result must be an object")
    if ingest_result.get("errors") or ingest_result.get("requiresRename"):
        raise ValueError("Resolve ingest blockers and duplicate table names before snapshot")
    csv_options = ingest_result.get("csvOptions", [])
    if not isinstance(csv_options, list) or any(not isinstance(option, dict) for option in csv_options):
        raise ValueError("ingest_result.csvOptions must be an array of objects")
    if any(option.get("needsClarification") for option in csv_options):
        raise ValueError("Resolve CSV interpretation before snapshot")
    sources = ingest_result.get("sources")
    tables = ingest_result.get("tables")
    if not isinstance(sources, list) or not isinstance(tables, list):
        raise ValueError("ingest_result.sources and tables must be arrays")
    _text(created_at, "created_at")
    if snapshot_id is not None and (
        not isinstance(snapshot_id, str) or re.fullmatch(r"snap_[a-f0-9]{24}", snapshot_id) is None
    ):
        raise ValueError("snapshot_id must match snap_ followed by 24 lowercase hexadecimal digits")

    source_ids = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("ingest_result.sources entries must be objects")
        identifier = _text(source.get("id"), "source.id")
        _text(source.get("name"), "source.name")
        if source.get("type") not in _SOURCE_TYPES:
            raise ValueError("source.type is not supported by WL1")
        if identifier in source_ids:
            raise ValueError("source.id must be unique")
        source_ids.add(identifier)

    profiled = [profile_table(table) for table in tables]
    if len({table["name"] for table in profiled}) != len(profiled):
        raise ValueError("Duplicate table names must be resolved before snapshot")
    if any(table["sourceId"] not in source_ids for table in profiled):
        raise ValueError("table.sourceId must refer to an ingested source")
    ordered_sources = sorted(deepcopy(sources), key=lambda source: (source["name"], source["id"]))
    ordered_tables = sorted(profiled, key=lambda table: (table["name"], table["sourceId"]))
    snapshot = {
        "schemaVersion": "1.0",
        "snapshot": {
            "snapshotId": snapshot_id or "snap_" + canonical_hash(sorted(table["id"] for table in ordered_tables))[7:31],
            "createdAt": created_at,
            "sessionId": "sess_" + canonical_hash(sorted(source_ids))[7:19],
            "sourceCount": len(ordered_sources),
            "tableCount": len(ordered_tables),
        },
        "sources": ordered_sources,
        "tables": ordered_tables,
        "hashBasis": list(_HASH_BASIS),
    }
    snapshot["snapshotHash"] = snapshot_hash(snapshot)
    return snapshot
