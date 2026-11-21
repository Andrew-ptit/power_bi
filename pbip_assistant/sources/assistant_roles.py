"""Deterministic, local WL2 role proposals over measured source data."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from .assistant_ingest import canonical_hash
from .assistant_profile import profile_table


_CURRENCY_CODES = frozenset({
    "AED", "ARS", "AUD", "BDT", "BGN", "BHD", "BRL", "CAD", "CHF", "CLP", "CNY",
    "COP", "CZK", "DKK", "EGP", "EUR", "GBP", "HKD", "HUF", "IDR", "ILS", "INR",
    "ISK", "JPY", "KES", "KRW", "KWD", "LKR", "MAD", "MMK", "MXN", "MYR", "NGN",
    "NOK", "NPR", "NZD", "OMR", "PEN", "PHP", "PKR", "PLN", "QAR", "RON", "RSD",
    "RUB", "SAR", "SEK", "SGD", "THB", "TRY", "TWD", "UAH", "USD", "VND", "XAF",
    "XOF", "ZAR",
})


def _ratio(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0.0
    return float((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP,
    ))


def _evidence(kind: str, value: int | float | str, ref: str) -> dict:
    return {"kind": kind, "value": str(value), "ref": ref, "formulaId": None}


def _tables(snapshot: dict) -> list[dict]:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("tables"), list):
        raise ValueError("WL2 requires a snapshot with tables")
    tables = snapshot["tables"]
    identifiers = []
    for table in tables:
        if not isinstance(table, dict) or not isinstance(table.get("id"), str):
            raise ValueError("Snapshot tables require text identifiers")
        rows = table.get("rowCount")
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
            raise ValueError("Snapshot row counts must be nonnegative integers")
        if not isinstance(table.get("columns"), list):
            raise ValueError("Snapshot tables require columns")
        identifiers.append(table["id"])
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Snapshot table identifiers must be unique")
    return sorted(tables, key=lambda table: table["id"])


def _unique_keys(report: dict) -> dict[str, set[frozenset[str]]]:
    if not isinstance(report, dict):
        raise ValueError("key_report must be an object")
    result: dict[str, set[frozenset[str]]] = {}
    for key in report.get("keys", []):
        if key.get("unique") is True and key.get("nullCount") == 0 and key.get("columns"):
            result.setdefault(key["tableId"], set()).add(frozenset(key["columns"]))
    return result


def _is_unique(keys: set[frozenset[str]], columns: list[str]) -> bool:
    selected = frozenset(columns)
    return any(key <= selected for key in keys)


def _positive_link(link: dict) -> bool:
    overlap = link.get("evidence", {}).get("overlap", link.get("score", 0))
    return (isinstance(overlap, (int, float)) and not isinstance(overlap, bool)
            and Decimal(str(overlap)).is_finite() and 0 < overlap <= 1)


def structural_roles(snapshot: dict, key_report: dict) -> list[dict]:
    """Propose a fact from repeated foreign-key grain, never from table names."""
    tables = _tables(snapshot)
    if not tables:
        raise ValueError("No tables satisfy the fact criteria")
    keys = _unique_keys(key_report)
    table_ids = {table["id"] for table in tables}
    candidates = key_report.get("relationships", [])
    if any(link.get("fromTable") not in table_ids or link.get("toTable") not in table_ids for link in candidates):
        raise ValueError("Relationships must refer to snapshot tables")
    # A zero-overlap proposal is useful diagnostic evidence, not a real graph edge.
    links = [link for link in candidates if _positive_link(link)]
    maximum_rows = max(table["rowCount"] for table in tables)
    fact_candidates = []
    for table in tables:
        outgoing = [link for link in links if link["fromTable"] == table["id"] and link["toTable"] != table["id"]]
        target_count = len({link["toTable"] for link in outgoing})
        repeated = [link for link in outgoing if not _is_unique(keys.get(table["id"], set()), link["fromColumns"])]
        if table["rowCount"] == maximum_rows and maximum_rows > 0 and target_count >= 2 and repeated:
            fact_candidates.append((table, target_count, len(repeated), len(outgoing)))
    if not fact_candidates:
        raise ValueError("No largest table has repeated foreign keys and at least two targets")
    # Ties stay reproducible. The proposal is still inference, never verified.
    fact, fact_targets, fact_repeated, fact_links = sorted(fact_candidates, key=lambda item: item[0]["id"])[0]
    result = []
    for table in tables:
        identifier = table["id"]
        incoming = [link for link in links if link["toTable"] == identifier]
        fact_incoming = [link for link in incoming if link["fromTable"] == fact["id"]]
        unique_incoming = [link for link in fact_incoming if _is_unique(keys.get(identifier, set()), link["toColumns"])]
        partial_lookup = [link for link in fact_incoming
                          if link["cardinality"] in {"N:1", "1:1"}
                          and not _is_unique(keys.get(identifier, set()), link["toColumns"])]
        many_to_many = [link for link in links if link["cardinality"] == "N:N" and identifier in (link["fromTable"], link["toTable"])]
        measured = [_evidence("row_count", table["rowCount"], identifier)]
        if identifier == fact["id"]:
            structural = "fact"
            measured.extend([_evidence("outgoing_table_count", fact_targets, identifier),
                             _evidence("non_unique_fk_count", fact_repeated, identifier)])
            confidence = _ratio(fact_repeated, fact_links)
        elif unique_incoming:
            structural = "dim"
            measured.append(_evidence("unique_fact_reference_count", len(unique_incoming), identifier))
            confidence = _ratio(len(unique_incoming), len(fact_incoming))
        elif partial_lookup:
            structural = "lookup"
            measured.append(_evidence("partial_key_reference_count", len(partial_lookup), identifier))
            confidence = _ratio(len(partial_lookup), len(fact_incoming))
        elif many_to_many:
            structural = "bridge"
            measured.append(_evidence("many_to_many_relationship_count", len(many_to_many), identifier))
            confidence = _ratio(len(many_to_many), len([link for link in links if identifier in (link["fromTable"], link["toTable"])]))
        else:
            structural = "lookup"
            measured.append(_evidence("partial_key_reference_count", len(incoming), identifier))
            confidence = _ratio(maximum_rows - table["rowCount"], maximum_rows)
        result.append({"tableId": identifier, "structural": structural,
                       "domainLabel": "Đề xuất vai cấu trúc từ số đo nguồn",
                       "confidence": confidence, "evidence": measured})
    return result


def _key_report(raw_tables: list[dict]) -> dict:
    # Agent A owns all key logic; defer this import to keep the modules independent.
    from .assistant_keys import key_report
    return key_report(raw_tables)


def _raw_tables(snapshot: dict, raw_tables: list[dict]) -> dict[str, dict]:
    expected = {table["id"]: table for table in _tables(snapshot)}
    if not isinstance(raw_tables, list):
        raise ValueError("raw_tables must be an array")
    result = {}
    for raw in raw_tables:
        profile = profile_table(raw)
        identifier = raw.get("id", profile["id"])
        if identifier not in expected or identifier in result:
            raise ValueError("Raw tables must match the snapshot exactly")
        table = expected[identifier]
        if (profile["rowCount"] != table["rowCount"] or
                [column["name"] for column in table["columns"]] != raw["header"] or
                any(profile[field] != table.get(field) for field in ("headerHash", "sampleHash", "fingerprint"))):
            raise ValueError("Raw table counts, headers and fingerprints must match the snapshot")
        result[identifier] = raw
    if set(result) != set(expected):
        raise ValueError("Raw tables must cover every snapshot table")
    return result


def _iso_date(value: str) -> bool:
    candidate = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}", candidate):
            date.fromisoformat(candidate + "-01")
        elif "T" in candidate:
            datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        else:
            date.fromisoformat(candidate)
        return True
    except ValueError:
        return False


def _numeric(value: str) -> bool:
    try:
        return Decimal(value.strip()).is_finite()
    except InvalidOperation:
        return False


def column_roles(snapshot: dict, raw_tables: list[dict]) -> list[dict]:
    """Return flat column proposals, keeping semantic currency and key evidence."""
    raw_by_id = _raw_tables(snapshot, raw_tables)
    report = _key_report(raw_tables)
    key_columns: dict[str, set[str]] = {}
    for key in report.get("keys", []):
        if key.get("unique") is True and key.get("nullCount") == 0:
            key_columns.setdefault(key["tableId"], set()).update(key["columns"])
    for relation in report.get("relationships", []):
        if _positive_link(relation):
            key_columns.setdefault(relation["fromTable"], set()).update(relation["fromColumns"])
            key_columns.setdefault(relation["toTable"], set()).update(relation["toColumns"])
    result = []
    for identifier, raw in sorted(raw_by_id.items()):
        for index, name in enumerate(raw["header"]):
            values = [row[index] for row in raw["rows"]]
            numeric_count = sum(_numeric(value) for value in values)
            date_count = sum(_iso_date(value) for value in values)
            code_count = sum(value in _CURRENCY_CODES for value in values)
            distinct_count = len({value for value in values if value != ""})
            folded = name.casefold()
            is_key = name in key_columns.get(identifier, set())
            currency_hint = "currency" in folded or folded in {"ccy", "currcode"}
            currency = currency_hint or bool(values) and Decimal(code_count) / len(values) >= Decimal("0.95")
            measured = [_evidence("row_count", len(values), identifier),
                        _evidence("numeric_count", numeric_count, identifier),
                        _evidence("iso_date_count", date_count, identifier)]
            if is_key:
                measured.append(_evidence("detected_key", 1, identifier))
            if currency:
                role = "currency"
                measured.append(_evidence("currency_code_count", code_count, identifier))
                confidence = _ratio(code_count, len(values))
            elif is_key:
                role, confidence = "key", 1.0
            elif values and Decimal(date_count) / len(values) >= Decimal("0.95"):
                role, confidence = "date", _ratio(date_count, len(values))
            elif any(token in folded for token in ("pct", "percent", "discount")):
                role, confidence = "percent", _ratio(numeric_count, len(values))
            elif values and any(token in folded for token in ("amount", "amt", "rate", "price", "qty", "quantity", "value")) and Decimal(numeric_count) / len(values) >= Decimal("0.95"):
                role, confidence = "amount", _ratio(numeric_count, len(values))
            elif values and Decimal(distinct_count) / len(values) >= Decimal("0.5"):
                role, confidence = "text", _ratio(distinct_count, len(values))
            else:
                role, confidence = None, 0.0
            result.append({"tableId": identifier, "name": name, "role": role,
                           "roleStatus": "unknown" if role is None else "inferred",
                           "confidence": confidence, "evidence": measured})
    return result


def assumption_ledger(snapshot: dict, key_report: dict) -> list[dict]:
    """Record only sources actually consumed; no fabricated user/history/LLM policy."""
    tables = _tables(snapshot)
    measured_rows = sum(table["rowCount"] for table in tables)
    entries = [{"statement": "Vai và quan hệ là đề xuất từ số đo cấu trúc nguồn; chưa xác nhận policy nghiệp vụ.",
                "source": "data", "confidence": 1.0, "risk": "medium",
                "evidence": [_evidence("row_count", measured_rows, "snapshot"),
                             _evidence("relationship_count", len(key_report.get("relationships", [])), "key_report")]}]
    pack = snapshot.get("pack")
    if isinstance(pack, dict) and pack.get("genericMode") is False and isinstance(pack.get("id"), str):
        entries.append({"statement": "Mô hình đã chọn bộ quy tắc ngành được khai báo; policy nghiệp vụ vẫn cần người dùng chốt.",
                        "source": "pack", "confidence": 1.0, "risk": "high",
                        "evidence": [_evidence("selected_pack_count", 1, pack["id"])]})
    return [{"id": "asm_" + canonical_hash(entry)[7:19], **entry} for entry in entries]


def _period(value: str) -> str | None:
    candidate = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}", candidate):
        return candidate if _iso_date(candidate) else None
    try:
        parsed = (datetime.fromisoformat(candidate.replace("Z", "+00:00"))
                  if "T" in candidate else date.fromisoformat(candidate))
        return f"{parsed.year:04d}-{parsed.month:02d}"
    except ValueError:
        return None


def warning_classification(snapshot: dict, raw_tables: list[dict]) -> list[dict]:
    """Classify absent FX rates against measured usage, without choosing policies."""
    raw_by_id = _raw_tables(snapshot, raw_tables)
    catalogs = []
    used = set()
    currencies = set()
    periods = set()
    available = set()
    unknown_used = 0
    invalid_catalog = 0
    for raw in raw_by_id.values():
        fields = {name.casefold(): index for index, name in enumerate(raw["header"])}
        ccy = next((fields[name] for name in ("currencycode", "currency", "ccy") if name in fields), None)
        month = next((fields[name] for name in ("month", "postingdate", "orderdate", "date") if name in fields), None)
        catalog = ccy is not None and "month" in fields and "ratetype" in fields and "rate" in fields
        if catalog:
            catalogs.append(raw)
        for row in raw["rows"]:
            currency = row[ccy].strip() if ccy is not None else ""
            period = _period(row[month]) if month is not None else None
            valid_currency = re.fullmatch(r"[A-Z]{3}", currency) is not None
            if valid_currency:
                currencies.add(currency)
            if period:
                periods.add(period)
            if catalog and valid_currency and period:
                rate = row[fields["rate"]]
                if _numeric(rate) and Decimal(rate) > 0:
                    available.add((currency, period, row[fields["ratetype"]].strip().casefold()))
            elif catalog:
                invalid_catalog += 1
            elif ccy is not None and period:
                if valid_currency:
                    used.add((currency, period))
                else:
                    unknown_used += 1
    if not catalogs:
        return []
    result = []
    if unknown_used:
        result.append({"code": "AF_MISSING_DATA", "severity": "blocker",
                       "message": f"Có {unknown_used} dòng phát sinh chưa có mã tiền tệ hợp lệ; phải dừng trước quy đổi."})
    if invalid_catalog:
        result.append({"code": "AF_MISSING_DATA", "severity": "warning",
                       "message": f"Có {invalid_catalog} dòng danh mục tỷ giá chưa xác định được mã tiền tệ hoặc kỳ hợp lệ."})
    for currency in sorted(currencies):
        for period in sorted(periods):
            for kind in ("average", "closing"):
                if (currency, period, kind) not in available:
                    blocking = kind == "average" and (currency, period) in used
                    result.append({"code": "AF_MISSING_DATA", "severity": "blocker" if blocking else "warning",
                                   "message": f"Thiếu tỷ giá {currency} {kind} kỳ {period}; " +
                                   ("có phát sinh nên phải dừng trước quy đổi." if blocking else "tỷ giá không được dùng trong quy đổi bình quân của dữ liệu hiện tại.")})
    return result
