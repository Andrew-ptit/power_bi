"""Hand-written oracle for the derived `modelView` (feature 004).

Independent reimplementation of spec 004 §6 and contracts/model-view.md.
It never imports the module under test (`assistant_model_view`); it reuses
the pre-existing WL2 probes (`_iso_date`, `column_roles`, `key_report`) and
`canonical_hash`, and re-derives every modelView field from raw inputs.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import json
import re

from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_keys import key_report
from pbip_assistant.sources.assistant_roles import _iso_date, column_roles


def iso_value(value) -> str | None:
    """Normalize any ISO date/time value the WL2 probe accepts to YYYY-MM-DD."""
    candidate = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}", candidate):
            return date.fromisoformat(candidate + "-01").isoformat()
        if "T" in candidate:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date().isoformat()
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def date_columns(raw: dict) -> list[tuple[int, str]]:
    """Columns with >= 95% non-empty ISO values and at least one value."""
    result = []
    for index, name in enumerate(raw["header"]):
        values = [row[index] for row in raw["rows"] if row[index] != ""]
        if values and Decimal(sum(_iso_date(value) for value in values)) / Decimal(len(values)) >= Decimal("0.95"):
            result.append((index, name))
    return result


def grain_kind_oracle(raw: dict, keys: list[dict]) -> tuple[str, dict | None]:
    if not raw["rows"]:
        return "unknown", None
    dates = date_columns(raw)
    if not dates:
        return "unknown", None
    first_index, first_name = dates[0]
    distinct_dates = len({iso_value(row[first_index]) for row in raw["rows"]} - {None})
    names = {name for _, name in dates}
    candidates = [key for key in keys
                  if key.get("unique") is True and key.get("nullCount") == 0
                  and len(key.get("columns", [])) >= 2
                  and sum(column in names for column in key["columns"]) == 1]
    candidates.sort(key=lambda key: (len(key["columns"]), key["columns"]))
    for key in candidates:
        date_column = next(column for column in key["columns"] if column in names)
        entity_columns = [column for column in key["columns"] if column != date_column]
        date_index = raw["header"].index(date_column)
        entity_indexes = [raw["header"].index(column) for column in entity_columns]
        seen_dates: dict[tuple, set[str]] = {}
        for row in raw["rows"]:
            value = iso_value(row[date_index])
            if value is None:
                continue
            seen_dates.setdefault(tuple(row[index] for index in entity_indexes), set()).add(value)
        entities = len(seen_dates)
        repeated = sum(len(values) >= 2 for values in seen_dates.values())
        evidence = {"dateColumn": date_column, "entityColumns": entity_columns,
                    "distinctDates": distinct_dates, "repeatedEntities": repeated, "entities": entities}
        if distinct_dates >= 3 and entities and Decimal(repeated) / Decimal(entities) >= Decimal("0.50"):
            return "snapshot", evidence
        return "event", {"dateColumn": date_column, "entityColumns": [], "distinctDates": distinct_dates,
                         "repeatedEntities": 0, "entities": 0}
    return "event", {"dateColumn": first_name, "entityColumns": [], "distinctDates": distinct_dates,
                     "repeatedEntities": 0, "entities": 0}


def _question_ids(questions: list[dict], topic: str, ref: str) -> str | None:
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


def build_model_view_oracle(raw_tables, snapshot, understand, questions) -> dict:
    """Re-derive the whole modelView shape without touching the module under test."""
    by_name = {table["name"]: table for table in snapshot["tables"]}
    bound = []
    for raw in raw_tables:
        copied = deepcopy(raw)
        copied["id"] = by_name[copied["name"]]["id"]
        bound.append(copied)
    bound.sort(key=lambda table: table["id"])
    report = key_report(bound)
    roles_by_table = {role["tableId"]: role for role in understand["roles"]}
    proposals = column_roles(snapshot, bound)
    role_by_column = {(p["tableId"], p["name"]): ("unknown" if p.get("role") is None else p["role"]) for p in proposals}
    keys_by_table = {}
    for key in report["keys"]:
        if key.get("unique") is True and key.get("nullCount") == 0 and key.get("columns"):
            keys_by_table.setdefault(key["tableId"], []).append(key["columns"])
    link_columns = set()
    for link in understand["relationships"]:
        link_columns.update(link["fromColumns"])
        link_columns.update(link["toColumns"])

    tables = []
    for table in sorted(snapshot["tables"], key=lambda item: item["id"]):
        raw = next(item for item in bound if item["id"] == table["id"])
        kind, evidence = grain_kind_oracle(raw, [k for k in report["keys"] if k["tableId"] == table["id"]])
        keys = [list(columns) for columns in keys_by_table.get(table["id"], [])[:3]]
        flattened = {column for key in keys for column in key}
        snapshot_columns = {column["name"]: column for column in table["columns"]}
        role = roles_by_table.get(table["id"])
        date_range = None
        for index, name in date_columns(raw):
            values = sorted({iso_value(row[index]) for row in raw["rows"]} - {None})
            if values:
                date_range = {"column": name, "min": values[0], "max": values[-1]}
                break
        columns = []
        for name in raw["header"][:200]:
            column = snapshot_columns[name]
            columns.append({"name": name, "type": column["type"], "role": role_by_column.get((table["id"], name), "unknown"),
                            "isKey": name in flattened, "isLink": name in link_columns,
                            "nullRate": column["nullRate"], "distinctCount": column["distinctCount"]})
        tables.append({"tableId": table["id"], "name": table["name"],
                       "rowCount": table.get("totalRows", table["rowCount"]),
                       "measuredRows": len(raw["rows"]),
                       "structural": role["structural"] if role else "unclassified",
                       "confidence": role["confidence"] if role else None,
                       "roleQuestionId": _role_question_id(questions, table["id"]) if role else None,
                       "grainKind": kind, "grainEvidence": evidence,
                       "grainQuestionId": _question_ids(questions, "grain", table["id"]),
                       "keys": keys, "dateRange": date_range,
                       "columnCount": len(raw["header"]), "columns": columns})

    relationships = []
    for link in understand["relationships"]:
        fan_out = link.get("fanOutEvidence")
        relationships.append({"id": link["id"], "fromTable": link["fromTable"], "fromColumns": list(link["fromColumns"]),
                              "toTable": link["toTable"], "toColumns": list(link["toColumns"]),
                              "cardinality": link["cardinality"], "status": link["status"],
                              "fanOutRisk": link["fanOutRisk"], "overlap": link["evidence"]["overlap"],
                              "orphan": link["evidence"]["orphan"],
                              "rowsBefore": fan_out.get("rowsBefore") if fan_out else None,
                              "rowsAfter": fan_out.get("rowsAfter") if fan_out else None,
                              "wireState": "fanout" if link["fanOutRisk"] == "high"
                                          else "orphan" if link["evidence"]["orphan"] > 0 else "safe",
                              "questionId": _question_ids(questions, "relationship", link["id"])})

    warnings = [{"code": warning["code"], "severity": warning["severity"],
                 "questionId": _warning_question_id(warning, questions)} for warning in understand["warnings"]]

    counts = {"tables": len(tables), "fact": 0, "dim": 0, "lookup": 0, "bridge": 0, "unclassified": 0,
              "relationships": len(relationships), "needsConfirm": 0, "warnings": len(warnings)}
    for table in tables:
        counts[table["structural"] if table["structural"] in counts else "unclassified"] += 1
    counts["needsConfirm"] = sum(question.get("topic") in {"relationship", "role", "grain"} for question in questions)

    model_view = {"schemaVersion": "1.0", "understandHash": understand["understandHash"],
                  "mode": "model" if understand["roles"] else "per_sheet",
                  "measuredOn": "sample" if snapshot.get("snapshot", {}).get("mode") == "discover" else "full",
                  "counts": counts, "tables": tables, "relationships": relationships, "warnings": warnings}
    model_view["modelViewHash"] = canonical_hash({key: value for key, value in model_view.items() if key != "modelViewHash"})
    return model_view