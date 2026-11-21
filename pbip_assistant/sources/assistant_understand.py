"""Assemble deterministic WL2 proposals without I/O or execution authority."""

from __future__ import annotations

from copy import deepcopy
import re

from .assistant_ingest import canonical_hash
from .assistant_keys import has_finance_schema, key_report
from .assistant_profile import profile_table, snapshot_hash
from .assistant_roles import assumption_ledger, structural_roles, warning_classification


_HASH_BASIS = ("snapshotHash", "pack", "roles", "relationships", "assumptions", "warnings",
               "variantOf", "variantReason")
_PROFILE_FIELDS = ("name", "rowCount", "columnCount", "headerHash", "sampleHash", "fingerprint")
_COLUMN_FIELDS = ("name", "nullRate", "distinctCount", "distinctRatio", "sample")


def _bind_raw(raw_tables: list[dict], snapshot: dict) -> list[dict]:
    """Validate owned WL1 fields, then bind copies to the supplied snapshot IDs."""
    if not isinstance(raw_tables, list) or not isinstance(snapshot, dict):
        raise ValueError("WL2 requires raw tables and a WL1 snapshot")
    tables, sources = snapshot.get("tables"), snapshot.get("sources")
    if not isinstance(tables, list) or not isinstance(sources, list):
        raise ValueError("WL1 snapshot requires table and source arrays")
    basis = snapshot.get("hashBasis")
    if (not isinstance(basis, list) or any(not isinstance(key, str) for key in basis)
            or len(basis) != len(set(basis)) or
            set(basis) not in ({"snapshot", "sources", "tables"},
                               {"snapshot", "sources", "tables", "variantOf", "variantReason"})):
        raise ValueError("WL1 snapshot hash basis is unsupported")
    declared = snapshot.get("snapshotHash")
    if not isinstance(declared, str) or re.fullmatch(r"sha256:[a-f0-9]{64}", declared) is None:
        raise ValueError("WL1 snapshot requires a canonical snapshot hash")
    try:
        full_hash = canonical_hash({key: snapshot[key] for key in basis})
        runtime_hash = snapshot_hash(snapshot) if basis == ["snapshot", "sources", "tables"] else None
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("WL1 snapshot cannot be hashed") from exc
    if declared not in {full_hash, runtime_hash}:
        raise ValueError("WL1 snapshot hash does not match its content")
    if any(not isinstance(table, dict) for table in tables) or any(not isinstance(source, dict) for source in sources):
        raise ValueError("WL1 table and source entries must be objects")
    names, identifiers = [table.get("name") for table in tables], [table.get("id") for table in tables]
    source_ids = [source.get("id") for source in sources]
    if (any(not isinstance(name, str) or not name for name in names) or
            len(names) != len(set(names)) or
            any(not isinstance(identifier, str) or re.fullmatch(r"tbl_[a-f0-9]{12}", identifier) is None for identifier in identifiers) or
            len(identifiers) != len(set(identifiers)) or
            any(not isinstance(identifier, str) or re.fullmatch(r"src_[a-f0-9]{12}", identifier) is None for identifier in source_ids) or
            len(source_ids) != len(set(source_ids))):
        raise ValueError("WL1 table names and identifiers must be valid and unique")
    metadata = snapshot.get("snapshot")
    if (not isinstance(metadata, dict) or isinstance(metadata.get("tableCount"), bool)
            or isinstance(metadata.get("sourceCount"), bool) or metadata.get("tableCount") != len(tables)
            or metadata.get("sourceCount") != len(sources)):
        raise ValueError("WL1 snapshot counts must match the source and table arrays")
    if any(table.get("sourceId") not in source_ids for table in tables):
        raise ValueError("WL1 tables must refer to snapshot sources")
    by_name = dict(zip(names, tables, strict=True))
    bound, found = [], set()
    for raw in raw_tables:
        profile = profile_table(raw)
        name = profile["name"]
        if name not in by_name or name in found:
            raise ValueError("Raw tables must cover snapshot names exactly once")
        expected = by_name[name]
        if any(profile[field] != expected.get(field) for field in _PROFILE_FIELDS):
            raise ValueError("Raw table profiles do not match the supplied snapshot")
        columns = expected.get("columns")
        if not isinstance(columns, list) or len(columns) != len(profile["columns"]):
            raise ValueError("Raw table columns do not match the supplied snapshot")
        for actual, column in zip(profile["columns"], columns, strict=True):
            if not isinstance(column, dict) or any(actual[field] != column.get(field) for field in _COLUMN_FIELDS):
                raise ValueError("Raw column statistics do not match the supplied snapshot")
        copied = deepcopy(raw)
        copied["id"] = expected["id"]
        bound.append(copied)
        found.add(name)
    if found != set(names):
        raise ValueError("Raw tables must cover every snapshot table")
    return sorted(bound, key=lambda table: table["id"])


def understand_hash(understand: dict) -> str:
    """Recompute the complete, declared WL2 content projection."""
    if not isinstance(understand, dict) or understand.get("hashBasis") != list(_HASH_BASIS):
        raise ValueError("WL2 hash basis does not match the supported content fields")
    if not set(understand) <= {"schemaVersion", "hashBasis", "understandHash", *_HASH_BASIS}:
        raise ValueError("WL2 contains content outside its hash basis")
    try:
        return canonical_hash({key: understand[key] for key in _HASH_BASIS})
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("WL2 content cannot be hashed") from exc


def build_understand(raw_tables, snapshot, *, pack_id="generic", created_from="wl1") -> dict:
    """Assemble measured proposals bound to the caller's validated WL1 snapshot."""
    if not isinstance(pack_id, str) or pack_id not in {"generic", "fin-pl-v1"} or created_from != "wl1":
        raise ValueError("Unsupported WL2 pack or source layer")
    bound = _bind_raw(raw_tables, snapshot)
    finance = has_finance_schema(bound)
    if pack_id == "fin-pl-v1" and not finance:
        raise ValueError("Finance pack requires account and FX schemas")
    pack = {"id": "fin-pl-v1" if finance else "generic", "version": "1.0",
            "genericMode": not finance,
            "notice": None if finance else "Không có domain pack: mô hình generic kém chính xác hơn; cần người dùng rà soát nghĩa nghiệp vụ."}
    report = key_report(bound)
    context = deepcopy(snapshot)
    context["pack"] = deepcopy(pack)
    result = {"schemaVersion": "1.0", "snapshotHash": snapshot["snapshotHash"],
              "pack": pack, "roles": structural_roles(context, report),
              "relationships": report["relationships"],
              "assumptions": assumption_ledger(context, report),
              "warnings": warning_classification(context, bound),
              "variantOf": None, "variantReason": None, "hashBasis": list(_HASH_BASIS)}
    result["understandHash"] = understand_hash(result)
    return result
