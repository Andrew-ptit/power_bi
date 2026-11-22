"""Derived, deterministic `modelView` for the understand-data-step (feature 004).

Pure module: no I/O, no AI, no network. It reuses the existing WL2 probes by
import (`key_report`, `column_roles`, the ISO date test) and never recomputes
key combinations, never mutates its inputs, and never changes `understand` or
`understandHash`. The only cell values that ever reach the view are the two
ISO dates of `dateRange` (contract §4).
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import json
import re

from .assistant_ingest import canonical_hash
from .assistant_keys import key_report
from .assistant_roles import _iso_date, column_roles


# Named thresholds from spec 004 §6; tests exercise each boundary.
DATE_COLUMN_MIN_RATIO = Decimal("0.95")
SNAPSHOT_MIN_DISTINCT_DATES = 3
SNAPSHOT_MIN_REPEATED_RATIO = Decimal("0.50")
MAX_MODEL_VIEW_COLUMNS = 200
MAX_KEYS_PER_TABLE = 3


def _date_columns(raw_table: dict) -> list[tuple[int, str]]:
    """Columns where >= 95% of non-empty values are ISO dates (§6.1)."""
    result = []
    for index, name in enumerate(raw_table["header"]):
        values = [row[index] for row in raw_table["rows"] if row[index] != ""]
        if not values:
            continue
        iso_count = sum(1 for value in values if _iso_date(value))
        if Decimal(iso_count) / Decimal(len(values)) >= DATE_COLUMN_MIN_RATIO:
            result.append((index, name))
    return result


def _iso_value(value) -> str | None:
    """Normalize any value the WL2 probe accepts to an ISO date string."""
    candidate = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}", candidate):
            return date.fromisoformat(candidate + "-01").isoformat()
        if "T" in candidate:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date().isoformat()
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def grain_kind(raw_table: dict, candidate_keys: list[dict]) -> tuple[str, dict | None]:
    """→ ("event" | "snapshot" | "unknown", grainEvidence | None) per spec §6."""
    if not isinstance(raw_table, dict) or not isinstance(raw_table.get("header"), list) \
            or not isinstance(raw_table.get("rows"), list):
        raise ValueError("raw_table must carry header and rows")
    if not raw_table["rows"]:
        return "unknown", None
    dates = _date_columns(raw_table)
    if not dates:
        return "unknown", None
    first_index, first_name = dates[0]
    distinct_dates = len({value for value in (_iso_value(row[first_index]) for row in raw_table["rows"]) if value})
    date_names = {name for _, name in dates}
    keys = sorted((key for key in candidate_keys
                   if key.get("unique") is True and key.get("nullCount") == 0
                   and isinstance(key.get("columns"), list) and len(key["columns"]) >= 2
                   and sum(1 for column in key["columns"] if column in date_names) == 1),
                  key=lambda key: (len(key["columns"]), key["columns"]))
    for key in keys:
        date_column = next(column for column in key["columns"] if column in date_names)
        entity_columns = [column for column in key["columns"] if column != date_column]
        date_index = raw_table["header"].index(date_column)
        entity_indexes = [raw_table["header"].index(column) for column in entity_columns]
        entity_dates: dict[tuple, set[str]] = defaultdict(set)
        for row in raw_table["rows"]:
            value = _iso_value(row[date_index])
            if value is None:
                continue
            entity_dates[tuple(row[index] for index in entity_indexes)].add(value)
        entities = len(entity_dates)
        repeated = sum(1 for values in entity_dates.values() if len(values) >= 2)
        evidence = {"dateColumn": date_column, "entityColumns": entity_columns,
                    "distinctDates": distinct_dates, "repeatedEntities": repeated, "entities": entities}
        if (distinct_dates >= SNAPSHOT_MIN_DISTINCT_DATES and entities
                and Decimal(repeated) / Decimal(entities) >= SNAPSHOT_MIN_REPEATED_RATIO):
            return "snapshot", evidence
        return "event", {"dateColumn": date_column, "entityColumns": [], "distinctDates": distinct_dates,
                         "repeatedEntities": 0, "entities": 0}
    return "event", {"dateColumn": first_name, "entityColumns": [], "distinctDates": distinct_dates,
                     "repeatedEntities": 0, "entities": 0}


def _question_id(questions: list[dict], topic: str, ref: str) -> str | None:
    for question in questions:
        if question.get("topic") != topic:
            continue
        for entry in question.get("evidence", []):
            if entry.get("ref") == ref:
                return question["id"]
    return None


def _role_question_id(questions: list[dict], table_id: str) -> str | None:
    for question in questions:
        if question.get("topic") != "role":
            continue
        value = question.get("evidence", [{}])[0].get("value")
        if isinstance(value, dict) and value.get("tableId") == table_id:
            return question["id"]
    return None


def _warning_question_id(warning: dict, questions: list[dict]) -> str | None:
    wanted = json.dumps(warning, sort_keys=True, ensure_ascii=False)
    for question in questions:
        if question.get("topic") != "warning":
            continue
        value = question.get("evidence", [{}])[0].get("value")
        if isinstance(value, dict) and json.dumps(value, sort_keys=True, ensure_ascii=False) == wanted:
            return question["id"]
    return None


def _bind(raw_tables: list[dict], snapshot: dict) -> list[dict]:
    """Bind snapshot identifiers to raw copies, validating exact name coverage."""
    tables = snapshot.get("tables")
    if not isinstance(tables, list):
        raise ValueError("Snapshot requires a table array")
    by_name: dict[str, dict] = {}
    for table in tables:
        name = table.get("name")
        if not isinstance(name, str) or not name or name in by_name:
            raise ValueError("Snapshot table names must be unique")
        by_name[name] = table
    bound, seen = [], set()
    for raw in raw_tables:
        name = raw.get("name")
        if not isinstance(name, str) or name not in by_name or name in seen:
            raise ValueError("Raw tables must cover snapshot names exactly once")
        seen.add(name)
        copied = deepcopy(raw)
        copied["id"] = by_name[name]["id"]
        bound.append(copied)
    if seen != set(by_name):
        raise ValueError("Raw tables must cover every snapshot table")
    return sorted(bound, key=lambda table: table["id"])


def build_model_view(raw_tables, snapshot, understand, questions) -> dict:
    """→ modelView per contracts/model-view.md, with `modelViewHash`."""
    if not isinstance(raw_tables, list) or not isinstance(snapshot, dict) \
            or not isinstance(understand, dict) or not isinstance(questions, list):
        raise ValueError("modelView requires raw tables, snapshot, understand and questions")
    roles = understand.get("roles")
    relationships = understand.get("relationships")
    warnings = understand.get("warnings")
    understand_hash_value = understand.get("understandHash")
    if not isinstance(roles, list) or not isinstance(relationships, list) or not isinstance(warnings, list) \
            or not isinstance(understand_hash_value, str):
        raise ValueError("Understand content is inconsistent with the modelView contract")
    bound = _bind(raw_tables, snapshot)
    report = key_report(bound)
    roles_by_table = {role["tableId"]: role for role in roles}
    proposals = column_roles(snapshot, bound)
    role_by_column = {(proposal["tableId"], proposal["name"]):
                      ("unknown" if proposal.get("role") is None else proposal["role"]) for proposal in proposals}
    keys_by_table: dict[str, list[list[str]]] = {}
    for key in report["keys"]:
        if key.get("unique") is True and key.get("nullCount") == 0 and isinstance(key.get("columns"), list) \
                and key["columns"]:
            keys_by_table.setdefault(key["tableId"], []).append(list(key["columns"]))
    link_columns: set[str] = set()
    for link in relationships:
        link_columns.update(link.get("fromColumns", []))
        link_columns.update(link.get("toColumns", []))
    by_id = {table["id"]: table for table in bound}

    tables = []
    for table in sorted(snapshot["tables"], key=lambda item: item["id"]):
        raw = by_id[table["id"]]
        kind, evidence = grain_kind(raw, [key for key in report["keys"] if key["tableId"] == table["id"]])
        keys = [list(columns) for columns in keys_by_table.get(table["id"], [])[:MAX_KEYS_PER_TABLE]]
        flattened_keys = {column for key in keys for column in key}
        snapshot_columns = {column["name"]: column for column in table.get("columns", [])}
        if set(raw["header"]) != set(snapshot_columns):
            raise ValueError("Raw headers must match the snapshot columns")
        role = roles_by_table.get(table["id"])
        date_range = None
        for index, name in _date_columns(raw):
            values = sorted({value for value in (_iso_value(row[index]) for row in raw["rows"]) if value})
            if values:
                date_range = {"column": name, "min": values[0], "max": values[-1]}
                break
        columns = []
        for name in raw["header"][:MAX_MODEL_VIEW_COLUMNS]:
            column = snapshot_columns[name]
            if not isinstance(column, dict) or not isinstance(column.get("type"), str):
                raise ValueError("Snapshot columns must carry a type")
            columns.append({"name": name, "type": column["type"],
                            "role": role_by_column.get((table["id"], name), "unknown"),
                            "isKey": name in flattened_keys, "isLink": name in link_columns,
                            "nullRate": column.get("nullRate", 0), "distinctCount": column.get("distinctCount", 0)})
        tables.append({"tableId": table["id"], "name": table["name"],
                       "rowCount": table.get("totalRows", table.get("rowCount", 0)),
                       "measuredRows": len(raw["rows"]),
                       "structural": role["structural"] if role else "unclassified",
                       "confidence": role["confidence"] if role else None,
                       "roleQuestionId": _role_question_id(questions, table["id"]) if role else None,
                       "grainKind": kind, "grainEvidence": evidence,
                       "grainQuestionId": _question_id(questions, "grain", table["id"]),
                       "keys": keys, "dateRange": date_range,
                       "columnCount": len(raw["header"]), "columns": columns})

    model_relationships = []
    for link in relationships:
        fan_out = link.get("fanOutEvidence")
        overlap = link.get("evidence", {}).get("overlap", 0)
        orphan = link.get("evidence", {}).get("orphan", 0)
        fan_out_risk = link.get("fanOutRisk", "none")
        wire_state = "fanout" if fan_out_risk == "high" else "orphan" if orphan > 0 else "safe"
        model_relationships.append({
            "id": link["id"], "fromTable": link["fromTable"], "fromColumns": list(link["fromColumns"]),
            "toTable": link["toTable"], "toColumns": list(link["toColumns"]),
            "cardinality": link["cardinality"], "status": link["status"],
            "fanOutRisk": fan_out_risk, "overlap": overlap, "orphan": orphan,
            "rowsBefore": fan_out.get("rowsBefore") if fan_out else None,
            "rowsAfter": fan_out.get("rowsAfter") if fan_out else None,
            "wireState": wire_state,
            "questionId": _question_id(questions, "relationship", link["id"])})

    model_warnings = [{"code": warning["code"], "severity": warning["severity"],
                       "questionId": _warning_question_id(warning, questions)} for warning in warnings]

    counts = {"tables": len(tables), "fact": 0, "dim": 0, "lookup": 0, "bridge": 0, "unclassified": 0,
              "relationships": len(model_relationships), "needsConfirm": 0, "warnings": len(model_warnings)}
    for table in tables:
        structural = table["structural"]
        counts[structural if structural in counts else "unclassified"] += 1
    counts["needsConfirm"] = sum(question.get("topic") in {"relationship", "role", "grain"} for question in questions)

    model_view = {"schemaVersion": "1.0", "understandHash": understand_hash_value,
                  "mode": "model" if roles else "per_sheet",
                  "measuredOn": "sample" if snapshot.get("snapshot", {}).get("mode") == "discover" else "full",
                  "counts": counts, "tables": tables,
                  "relationships": model_relationships, "warnings": model_warnings}
    model_view["modelViewHash"] = model_view_hash(model_view)
    return model_view


def model_view_hash(model_view: dict) -> str:
    """Canonical hash of the whole view except the hash field itself."""
    if not isinstance(model_view, dict):
        raise ValueError("modelView must be an object")
    return canonical_hash({key: value for key, value in model_view.items() if key != "modelViewHash"})