"""Deterministic, local-only candidate keys and relationship arithmetic for WL2.

Key uniqueness is measured against every raw row.  Relationship arithmetic uses
an analytical ledger view of exact distinct records, a data-derived month, and average
rate rows for a rate lookup.  None of those views changes the supplied source.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
from math import comb
import re

from .assistant_ingest import canonical_hash
from .assistant_profile import profile_table


MIN_AUTO_OVERLAP = Decimal("0.5")
MAX_KEY_SEARCH_COMBINATIONS = 100_000
MAX_KEY_ROW_EVALUATIONS = 5_000_000
MAX_COMPOSITE_KEY_COLUMNS = 16
MAX_RELATIONSHIP_COLUMNS = 3
MAX_RELATIONSHIP_CANDIDATES = 10_000
MAX_RELATIONSHIP_ROW_EVALUATIONS = 5_000_000


def _ratio(part: int, whole: int) -> float:
    return float((Decimal(part) / Decimal(whole)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP,
    )) if whole else 0.0


def _semantic_name(name: str) -> str:
    value = re.sub(r"[^a-z0-9]", "", name.casefold())
    return re.sub(r"(?:code|id)$", "", value)


def _identifier(name: str) -> bool:
    folded = re.sub(r"[^a-z0-9]", "", name.casefold())
    return folded.endswith(("code", "id", "no")) or folded in {
        "key", "costcenter", "currency", "month", "entity", "partnerentity",
    }


def _catalog(raw_tables: list[dict]) -> list[dict]:
    if not isinstance(raw_tables, list):
        raise ValueError("raw_tables must be an array")
    result, identifiers = [], set()
    for raw in raw_tables:
        profile = profile_table(raw)
        identifier = raw.get("id", profile["id"])
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("Raw table identifiers must be nonempty and unique")
        identifiers.add(identifier)
        records = []
        seen = set()
        ledger_view = {"DocNo", "LineNo", "PostingDate", "DebitCredit", "Amount"} <= set(raw["header"])
        for row in raw["rows"]:
            marker = tuple(row)
            if not ledger_view or marker not in seen:
                seen.add(marker)
                records.append(dict(zip(raw["header"], row, strict=True)))
        # A virtual month is safe only when every usable ISO-date column agrees.
        if "Month" not in raw["header"] and records:
            month_columns = []
            for column in raw["header"]:
                if not column.casefold().endswith("date"):
                    continue
                try:
                    months = [date.fromisoformat(row[column]).isoformat()[:7] for row in records]
                except ValueError:
                    continue
                month_columns.append(months)
            if month_columns and all(values == month_columns[0] for values in month_columns):
                for record, month in zip(records, month_columns[0], strict=True):
                    record["Month"] = month
        available = [*raw["header"]]
        if records and "Month" in records[0] and "Month" not in available:
            available.append("Month")
        result.append({"id": identifier, "raw": raw, "records": records,
                       "columns": available,
                       "rateLookup": {"RateType", "Rate", "Month"} <= set(raw["header"])
                       and any(_semantic_name(name) == "currency" for name in raw["header"])})
    return sorted(result, key=lambda item: item["id"])


def _candidate_keys(tables: list[dict]) -> list[dict]:
    result = []
    for table in tables:
        raw, minimal = table["raw"], []
        rows = raw["rows"]
        if not rows:
            continue
        eligible = [index for index in range(len(raw["header"]))
                    if all(row[index] != "" for row in rows)
                    and (len(rows) == 1 or len({row[index] for row in rows}) > 1)]
        # Duplicate complete eligible records preclude every candidate key.
        if len({tuple(row[index] for index in eligible) for row in rows}) != len(rows):
            continue
        attempts, row_evaluations = 0, 0
        for size in range(1, len(eligible) + 1):
            for indices in combinations(eligible, size):
                attempts += 1
                if attempts > MAX_KEY_SEARCH_COMBINATIONS:
                    raise ValueError("Candidate-key search exceeds the bounded work limit")
                chosen = frozenset(indices)
                if any(found <= chosen for found in minimal):
                    continue
                row_evaluations += len(rows) * len(indices)
                if row_evaluations > MAX_KEY_ROW_EVALUATIONS:
                    raise ValueError("Candidate-key search exceeds the bounded row-evaluation limit")
                distinct = len({tuple(row[index] for index in indices) for row in rows})
                if distinct == len(rows):
                    minimal.append(chosen)
                    result.append({"tableId": table["id"],
                                   "columns": [raw["header"][index] for index in indices],
                                   "kind": "single" if size == 1 else "composite",
                                   "distinctRatio": _ratio(distinct, len(rows)),
                                   "nullCount": 0, "unique": True})
            if size == 1:
                # Minimal composite keys cannot contain an already unique column.
                eligible = [index for index in eligible if frozenset({index}) not in minimal]
                if not eligible:
                    break
                row_evaluations += len(rows) * len(eligible)
                if row_evaluations > MAX_KEY_ROW_EVALUATIONS:
                    raise ValueError("Candidate-key search exceeds the bounded row-evaluation limit")
                if len({tuple(row[index] for index in eligible) for row in rows}) != len(rows):
                    break
                if len(eligible) > MAX_COMPOSITE_KEY_COLUMNS:
                    raise ValueError("Composite-key search exceeds the bounded column pool")
    return sorted(result, key=lambda item: (item["tableId"], len(item["columns"]), item["columns"]))


def candidate_keys(raw_tables: list[dict]) -> list[dict]:
    """Return exact minimal non-null single and composite keys of raw rows."""
    return _candidate_keys(_catalog(raw_tables))


def _has_finance_schema(tables: list[dict]) -> bool:
    account = any({"AccountCode", "AccountType", "PnlGroup"} <= set(table["raw"]["header"])
                  for table in tables)
    return account and any(table["rateLookup"] for table in tables)


def has_finance_schema(raw_tables: list[dict]) -> bool:
    """Detect the supported finance structure from columns, never table names."""
    return _has_finance_schema(_catalog(raw_tables))


def _right_records(table: dict) -> list[dict]:
    records = table["records"]
    return [row for row in records if row["RateType"].casefold() == "average"] if table["rateLookup"] else records


def _mapped_column(columns: list[str], target: str) -> str | None:
    if target in columns:
        return target
    possible = [column for column in columns if _semantic_name(column) == _semantic_name(target)]
    return possible[0] if len(possible) == 1 else None


def _join_columns(left: dict, right: dict, keys: list[dict]) -> list[tuple[list[str], list[str]]]:
    mapping = {column: mapped for column in right["columns"]
               if (mapped := _mapped_column(left["columns"], column)) is not None}
    target_sets: set[tuple[str, ...]] = set()
    for key in keys:
        columns = tuple(key["columns"])
        measures = ("amount", "amt", "price", "qty", "quantity", "value", "percent", "pct", "discount")
        if (key["tableId"] == right["id"] and all(column in mapping for column in columns)
                and not any(any(token in column.casefold() for token in measures) for column in columns)):
            target_sets.add(columns)
    identifiers = [column for column in right["columns"] if column in mapping and _identifier(column)]
    possibilities = sum(comb(len(identifiers), size)
                        for size in range(1, min(MAX_RELATIONSHIP_COLUMNS, len(identifiers)) + 1))
    if possibilities + len(target_sets) > MAX_RELATIONSHIP_CANDIDATES:
        raise ValueError("Relationship candidate search exceeds the bounded candidate limit")
    for size in range(1, min(MAX_RELATIONSHIP_COLUMNS, len(identifiers)) + 1):
        target_sets.update(combinations(identifiers, size))
    return [([mapping[column] for column in columns], list(columns))
            for columns in sorted(target_sets, key=lambda columns: (len(columns), columns))]


def _foreign_keys(tables: list[dict], keys: list[dict]) -> list[dict]:
    result, row_evaluations = [], 0
    for left in tables:
        if not left["records"]:
            continue
        for right in tables:
            if left["id"] == right["id"]:
                continue
            rows_right = _right_records(right)
            for from_columns, to_columns in _join_columns(left, right, keys):
                row_evaluations += (len(left["records"]) + len(rows_right)) * len(from_columns)
                if row_evaluations > MAX_RELATIONSHIP_ROW_EVALUATIONS:
                    raise ValueError("Relationship search exceeds the bounded row-evaluation limit")
                if len(result) >= MAX_RELATIONSHIP_CANDIDATES:
                    raise ValueError("Relationship report exceeds the bounded candidate limit")
                right_values = {tuple(row[column] for column in to_columns) for row in rows_right
                                if all(row[column] != "" for column in to_columns)}
                orphan = sum(any(row[column] == "" for column in from_columns)
                             or tuple(row[column] for column in from_columns) not in right_values
                             for row in left["records"])
                result.append({"fromTable": left["id"], "fromColumns": from_columns,
                               "toTable": right["id"], "toColumns": to_columns,
                               "overlap": _ratio(len(left["records"]) - orphan, len(left["records"])),
                               "orphan": orphan})
    return sorted(result, key=_relation_sort)


def _relation_sort(item: dict) -> tuple:
    return item["fromTable"], item["toTable"], item["fromColumns"], item["toColumns"]


def foreign_key_candidates(raw_tables, keys) -> list[dict]:
    """Measure compatible name/key candidates without joining or changing rows."""
    return _foreign_keys(_catalog(raw_tables), keys)


def _relationships(tables: list[dict], fks: list[dict]) -> list[dict]:
    by_id = {table["id"]: table for table in tables}
    result, row_evaluations = [], 0
    finance = _has_finance_schema(tables)
    if len(fks) > MAX_RELATIONSHIP_CANDIDATES:
        raise ValueError("Relationship report exceeds the bounded candidate limit")
    for candidate in sorted(fks, key=_relation_sort):
        left, right = by_id[candidate["fromTable"]], by_id[candidate["toTable"]]
        from_columns, to_columns = candidate["fromColumns"], candidate["toColumns"]
        rows_left, rows_right = left["records"], _right_records(right)
        row_evaluations += (len(rows_left) + len(rows_right)) * len(from_columns)
        if row_evaluations > MAX_RELATIONSHIP_ROW_EVALUATIONS:
            raise ValueError("Relationship simulation exceeds the bounded row-evaluation limit")
        left_values = [tuple(row[column] for column in from_columns) for row in rows_left]
        right_values = [tuple(row[column] for column in to_columns) for row in rows_right]
        multiplicity = Counter(value for value in right_values if all(cell != "" for cell in value))
        rows_after = sum(max(1, multiplicity[value]) if all(cell != "" for cell in value) else 1
                         for value in left_values)
        high = rows_after > len(rows_left)
        left_unique = len(set(left_values)) == len(left_values) and all(all(v != "" for v in value) for value in left_values)
        right_unique = len(set(right_values)) == len(right_values) and all(all(v != "" for v in value) for value in right_values)
        cardinality = ("1:1" if left_unique and right_unique else "N:1" if right_unique
                       else "1:N" if left_unique else "N:N")
        orphan = sum(any(cell == "" for cell in value) or value not in multiplicity for value in left_values)
        overlap = _ratio(len(rows_left) - orphan, len(rows_left))
        exact_overlap = Decimal(len(rows_left) - orphan) / Decimal(len(rows_left)) if rows_left else Decimal(0)
        compatible_types = sum(
            bool(left_types := {type(row[a]) for row in rows_left})
            and left_types == {type(row[b]) for row in rows_right}
            for a, b in zip(from_columns, to_columns, strict=True)
        )
        result.append({"id": "rel_" + canonical_hash({key: candidate[key] for key in (
            "fromTable", "toTable", "fromColumns", "toColumns")})[7:19],
            "fromTable": left["id"], "fromColumns": list(from_columns),
            "toTable": right["id"], "toColumns": list(to_columns),
            "cardinality": cardinality, "score": overlap,
            "evidence": {"name": _ratio(sum(a == b for a, b in zip(from_columns, to_columns, strict=True)), len(from_columns)),
                         "type": _ratio(compatible_types, len(from_columns)), "overlap": overlap, "orphan": orphan},
            "status": "needs_confirm" if high or (orphan > 0 and not finance)
                      or exact_overlap < MIN_AUTO_OVERLAP else "auto",
            "fanOutRisk": "high" if high else "none",
            "fanOutEvidence": {"rowsBefore": len(rows_left), "rowsAfter": rows_after,
                               "inflationFactor": _ratio(rows_after, len(rows_left)),
                               "blockedBy": "AF_FANOUT_RISK"} if high else None})
    return result


def relationships(raw_tables, keys, fks) -> list[dict]:
    """Simulate left-outer-join multiplicities; no joined row payload is built."""
    return _relationships(_catalog(raw_tables), fks)


def key_report(raw_tables) -> dict:
    """Return the shared WL2 key, FK, relationship and fan-out report."""
    tables = _catalog(raw_tables)
    keys = _candidate_keys(tables)
    fks = _foreign_keys(tables, keys)
    relations = _relationships(tables, fks)
    fan_out = [{"fromTable": item["fromTable"], "toTable": item["toTable"],
                **item["fanOutEvidence"], "risk": "high"}
               for item in relations if item["fanOutEvidence"] is not None]
    return {"keys": keys, "foreignKeys": fks, "relationships": relations, "fanOut": fan_out}
