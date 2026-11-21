"""Dựng kết quả và workbook tạm WL5 thuần bộ nhớ, không mở nguồn."""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from copy import deepcopy
from decimal import localcontext, Decimal, ROUND_HALF_UP
import io
from pathlib import Path
import re
import tempfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZipFile, ZipInfo, ZIP_STORED

from pbip_assistant.errors import InputError
from .assistant_decisions import decisions_hash
from .assistant_execution import _FIN, _SALES
from .assistant_findings import (
    _account, _ARITHMETIC_CONTEXT, _decimal, _period, _records, _select, _unique,
    CENT, FROZEN_BUDGET_RATE_USD, ZERO, number,
)
from .assistant_ingest import canonical_hash
from .assistant_pack import validate_pack
from .assistant_profile import profile_table, snapshot_hash
from .assistant_spec import spec_fingerprint


RESULT_COLUMNS = {
    "tp-fin": ["pnlLine", "accountCode", "costCenter", "entityCode", "actualVnd",
               "budgetVnd", "varianceVnd", "period", "currency"],
    "tp-sales": ["region", "revenueVnd", "orderCount", "customerCount"],
}
MAX_ROWS = 100_000
MAX_COLUMNS = 256
MAX_WORKBOOK_BYTES = 16 * 1024 * 1024
MAX_SOURCE_EVIDENCE_BYTES = 16 * 1024 * 1024
MAX_SOURCE_EVIDENCE_FILES = 128
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
_HASH = re.compile(r"sha256:[a-f0-9]{64}")
_BASIS = ("specFingerprint", "target", "counts", "source", "sheets", "variantOf", "variantReason")


def _invalid(message, code="AF_PREVIEW_INVALID"):
    return InputError(code, "preview", message)


def _validated_raw(raw_tables):
    if not isinstance(raw_tables, list) or not raw_tables or len(raw_tables) > 128:
        raise _invalid("Cần danh sách bảng nguồn trong giới hạn hỗ trợ.")
    try:
        if sum(len(t.get("rows", [])) for t in raw_tables) > MAX_ROWS:
            raise _invalid("Nguồn vượt giới hạn số dòng preview.")
        for table in raw_tables:
            if len(table.get("header", [])) > MAX_COLUMNS:
                raise _invalid("Nguồn vượt giới hạn số cột preview.")
            profile_table(table)
    except (AttributeError, TypeError, ValueError) as exc:
        raise _invalid("Bảng nguồn không đúng shape WL1.") from exc
    return raw_tables


def _validated_spec(spec):
    if not isinstance(spec, dict) or spec.get("fingerprint") != spec_fingerprint(spec):
        raise _invalid("Fingerprint Spec không khớp nội dung.", "AF_SPEC_STALE")
    if spec["stale"] or "stale" in spec["labels"]:
        raise _invalid("Spec đã stale; cần chốt lại trước preview.", "AF_SPEC_STALE")
    if any(step["status"] != "ok" or step["guard"] is not None for step in spec["steps"]):
        raise _invalid("Spec còn step pending hoặc blocked.")


def _bound_choices(spec, decisions, pack):
    _validated_spec(spec)
    validate_pack(pack)
    if not isinstance(decisions, dict) or decisions.get("decisionsHash") != decisions_hash(decisions):
        raise _invalid("Hash quyết định không khớp nội dung.", "AF_SPEC_STALE")
    if (spec["decisionsHash"] != decisions["decisionsHash"] or
            any(spec[field] != decisions[field] for field in ("snapshotHash", "briefHash"))):
        raise _invalid("Quyết định không thuộc revision Spec.", "AF_SPEC_STALE")
    if decisions["freezeBlocked"]:
        raise _invalid("Quyết định chưa đủ điều kiện preview.", "AF_MISSING_DATA")
    selected = {entry["subProblemId"]: entry for entry in decisions["decisions"]}
    acks = {entry["subProblemId"]: entry for entry in decisions["acknowledgements"]}
    policies = {entry["subProblemId"]: entry for entry in pack["policies"]}
    required = {key for key, entry in policies.items() if entry["status"] != "missing_data"}
    missing = set(policies) - required
    if (len(selected) != len(decisions["decisions"]) or len(acks) != len(decisions["acknowledgements"])
            or set(selected) != required or set(acks) != missing or
            any(entry["acknowledged"] != "out_of_scope" for entry in acks.values()) or
            any(entry["decidedBy"] != "user" or entry["decidedAt"] is None for entry in selected.values())):
        raise _invalid("Cần đủ lựa chọn và metadata xác nhận tường minh.", "AF_MISSING_DATA")
    if any(entry["optionId"] != "A" for entry in selected.values()):
        raise _invalid("Slice preview hiện chỉ thực thi policy A; không tự thay lựa chọn khác.",
                       "AF_POLICY_UNSUPPORTED")
    seen = set()
    for step in spec["steps"]:
        expected = {key: selected[key]["optionId"] for key in step["decisionRefs"] if key in selected}
        if len(expected) != len(step["decisionRefs"]) or step["params"].get("chosenOptions") != expected:
            raise _invalid("Step không bind lựa chọn đã chốt.")
        seen.update(expected)
    if seen != required:
        raise _invalid("Spec thiếu ánh xạ quyết định thực thi.")
    scenario = "tp-fin" if pack["id"] == "fin-pl-v1" else "tp-sales"
    _supported_recipe(spec, scenario)
    return scenario


def _supported_recipe(spec, scenario):
    grain = RESULT_COLUMNS["tp-fin"][:4] if scenario == "tp-fin" else ["region"]
    definitions = _FIN if scenario == "tp-fin" else _SALES
    if len(spec["steps"]) != len(definitions):
        raise _invalid("Slice preview cần đúng recipe đã hỗ trợ.", "AF_POLICY_UNSUPPORTED")
    for step, (kind, operation, refs, source, columns) in zip(spec["steps"], definitions, strict=True):
        expected_columns = grain if columns == "grain" else list(columns) if columns else None
        params = step["params"]
        if (step["kind"] != kind or params["operation"] != operation or step["decisionRefs"] != list(refs)
                or params.get("columns") != expected_columns or params.get("sourceAlias") != source
                or params.get("rightGrain") != (grain if operation == "join_budget" else None)
                or params.get("tableId") is not None or params.get("formulaId") is not None
                or params.get("chosenOptions") != {key: "A" for key in refs}):
            raise _invalid("Plan hoặc grain chưa có cách thực thi trong slice preview.", "AF_POLICY_UNSUPPORTED")


def _finance_rows(tables):
    ledger = _select(tables, {"DocNo", "LineNo", "PostingDate", "DebitCredit", "Amount",
                              "AccountCode", "CostCenter", "Currency", "PartnerEntity", "EntityCode", "Ledger"})
    accounts = _unique(_records(_select(tables, {"AccountCode", "AccountType", "PnlGroup"})), "AccountCode")
    centers = _unique(_records(_select(tables, {"CostCenter", "EntityCode"}, excluded={"AccountCode"})), "CostCenter")
    rates = {}
    for row in _records(_select(tables, {"CurrencyCode", "Month", "RateType", "Rate"})):
        key = (row["CurrencyCode"], row["Month"], row["RateType"].strip().casefold())
        value = _decimal(row["Rate"])
        if value <= ZERO or key in rates and rates[key] != value:
            raise _invalid("Tỷ giá phải dương và không xung đột.", "AF_MISSING_DATA")
        rates[key] = value
    months = {_period(row["PostingDate"]) for row in _records(ledger)}
    if len(months) != 1:
        raise _invalid("Preview FIN hiện cần một tháng phát sinh duy nhất.", "AF_MISSING_DATA")
    period = next(iter(months))
    grouped, budget_grouped = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    seen = set()
    for row in _records(ledger):
        key = tuple(row[field] for field in ledger["header"])
        if key in seen:
            continue
        seen.add(key)
        info = _account(row["AccountCode"], accounts)
        if row["DebitCredit"] not in {"C", "D"}:
            raise _invalid("Dấu nguồn phải khai báo bằng C hoặc D.", "AF_MISSING_DATA")
        rate = rates.get((row["Currency"], period, "average"))
        if rate is None and row["Currency"] == "VND":
            rate = Decimal("1")
        if rate is None:
            raise _invalid("Thiếu average rate cho tiền tệ có phát sinh.", "AF_MISSING_DATA")
        line = "IntercompanyReconciliation" if row["PartnerEntity"].strip() else info["PnlGroup"]
        group = (line, info["AccountCode"], row["CostCenter"], row["EntityCode"])
        grouped[group] += _decimal(row["Amount"]) * (1 if row["DebitCredit"] == "C" else -1) * rate
    plan_rates = {"USD": FROZEN_BUDGET_RATE_USD, "VND": Decimal("1")}
    budget = _select(tables, {"Month", "AccountCode", "CostCenter", "Currency", "Amount"}, excluded={"DebitCredit"})
    for row in _records(budget):
        if row["Month"] != period:
            continue
        if row["AccountCode"] not in accounts or row["Currency"] not in plan_rates:
            raise _invalid("Budget có tài khoản hoặc tiền tệ chưa hỗ trợ.", "AF_MISSING_DATA")
        info = accounts[row["AccountCode"]]
        sign = -1 if info["AccountType"] == "ContraRevenue" or info["PnlGroup"] in {"COGS", "Opex"} else 1
        entity = centers.get(row["CostCenter"], {}).get("EntityCode", "UNKNOWN")
        key = (info["PnlGroup"], row["AccountCode"], row["CostCenter"], entity)
        budget_grouped[key] += _decimal(row["Amount"]) * sign * plan_rates[row["Currency"]]
    return [[*key, grouped.get(key, ZERO), budget_grouped.get(key, ZERO),
             grouped.get(key, ZERO) - budget_grouped.get(key, ZERO), period, "VND"]
            for key in sorted(set(grouped) | set(budget_grouped))]


def _sales_rows(tables):
    orders = _unique(_records(_select(tables, {"OrderID", "OrderDate", "CustomerID", "TerritoryID", "Status"})), "OrderID")
    customers = _unique(_records(_select(tables, {"CustomerID", "TerritoryID"}, excluded={"OrderID"})), "CustomerID")
    territories = _unique(_records(_select(tables, {"TerritoryID", "Region"})), "TerritoryID")
    amounts = defaultdict(lambda: ZERO)
    for item in _records(_select(tables, {"OrderID", "ProductID", "Quantity", "UnitPrice", "DiscountPct"})):
        if item["OrderID"] not in orders:
            raise _invalid("Dòng chi tiết không có Order tương ứng.", "AF_MISSING_DATA")
        discount = _decimal(item["DiscountPct"])
        if not ZERO <= discount <= Decimal("100"):
            raise _invalid("Chiết khấu phải nằm trong khoảng 0 đến 100.", "AF_MISSING_DATA")
        amounts[item["OrderID"]] += (_decimal(item["Quantity"]) * _decimal(item["UnitPrice"]) *
            (Decimal("1") - discount / Decimal("100"))).quantize(CENT, ROUND_HALF_UP)
    groups = {}
    for order in orders.values():
        if order["Status"] == "Cancelled":
            continue
        territory = order["TerritoryID"].strip() or customers.get(order["CustomerID"], {}).get("TerritoryID", "")
        region = territories.get(territory, {}).get("Region", "UNKNOWN") or "UNKNOWN"
        group = groups.setdefault(region, [ZERO, set(), set()])
        group[0] += amounts[order["OrderID"]]
        group[1].add(order["OrderID"])
        group[2].add(order["CustomerID"] if order["CustomerID"] in customers else "UNKNOWN_CUSTOMER")
    return [[region, amount, len(order_ids), len(customer_ids)]
            for region, (amount, order_ids, customer_ids) in sorted(groups.items())]


def result_rows(raw_tables, spec, decisions, pack):
    """Tính lại kết quả từ nguồn đã nạp; policy chưa thực thi được bị chặn tường minh."""
    scenario = _bound_choices(spec, decisions, pack)
    tables = _validated_raw(raw_tables)
    with localcontext(_ARITHMETIC_CONTEXT):
        rows = _finance_rows(tables) if scenario == "tp-fin" else _sales_rows(tables)
    return {"columns": list(RESULT_COLUMNS[scenario]), "rows": rows}


def _text(value):
    if (not isinstance(value, str) or len(value) > 32767 or
            any(not (char in "\t\n\r" or 0x20 <= ord(char) <= 0xD7FF or
                     0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF) for char in value)):
        raise _invalid("Chuỗi ô không hợp lệ hoặc vượt giới hạn workbook.")
    return value


def _matrix(columns, rows):
    if (not isinstance(columns, list) or not columns or len(columns) > MAX_COLUMNS or
            any(not isinstance(name, str) or not name for name in columns) or len(set(columns)) != len(columns)
            or not isinstance(rows, list) or len(rows) > MAX_ROWS):
        raise _invalid("Kết quả phải có cột duy nhất và số dòng/cột trong giới hạn.")
    # Dự trù XML trước khi dựng chuỗi lớn: overhead ô/row được chặn trên có dư.
    estimated = 4096 + (len(rows) + 3) * 80
    for row in [columns, *rows]:
        if not isinstance(row, list) or len(row) != len(columns):
            raise _invalid("Mỗi hàng kết quả phải có đủ số cột.")
        for cell in row:
            if isinstance(cell, str):
                _text(cell)
                estimated += (len(cell.encode("utf-8")) + cell.count("&") * 4 +
                              (cell.count("<") + cell.count(">")) * 3 + 160)
            elif cell is not None and (isinstance(cell, bool) or not isinstance(cell, (Decimal, int)) or
                                      not Decimal(cell).is_finite()):
                raise _invalid("Ô chỉ nhận chuỗi, số nguyên, Decimal hữu hạn hoặc null.")
            elif isinstance(cell, (Decimal, int)):
                _decimal(str(cell))
                estimated += 320
            else:
                estimated += 80
            if estimated > MAX_WORKBOOK_BYTES:
                raise _invalid("Workbook preview vượt giới hạn byte trước khi dựng XML.")
    return estimated


def result_digest(result):
    """Digest payload ô có kiểu; Decimal/int được chuẩn hóa, không log dữ liệu."""
    if not isinstance(result, dict) or set(result) != {"columns", "rows"}:
        raise _invalid("Kết quả preview chỉ nhận columns và rows.")
    _matrix(result["columns"], result["rows"])
    normalized = [[{"number": number(value, "scalar")} if isinstance(value, (Decimal, int)) else value
                   for value in row] for row in result["rows"]]
    return canonical_hash({"columns": result["columns"], "rows": normalized})


def _snapshot_info(snapshot, spec, scenario):
    if not isinstance(snapshot, dict) or snapshot.get("snapshotHash") != spec["snapshotHash"]:
        raise _invalid("Snapshot không thuộc revision Spec.", "AF_SPEC_STALE")
    basis = snapshot.get("hashBasis")
    if basis not in (["snapshot", "sources", "tables"],
                     ["snapshot", "sources", "tables", "variantOf", "variantReason"]):
        raise _invalid("Snapshot có hash basis không hỗ trợ.")
    try:
        full = canonical_hash({key: snapshot[key] for key in basis})
        runtime = snapshot_hash(snapshot) if len(basis) == 3 else None
        if snapshot["snapshotHash"] not in {full, runtime}:
            raise _invalid("Hash snapshot không khớp nội dung.", "AF_SPEC_STALE")
        sources = snapshot["sources"]
        if not isinstance(sources, list) or not sources or any(
                not isinstance(source, dict) or not isinstance(source.get("hash"), str) or
                _HASH.fullmatch(source["hash"]) is None for source in sources):
            raise _invalid("Snapshot thiếu fingerprint nguồn hợp lệ.")
        required = {"DebitCredit", "PostingDate", "Amount"} if scenario == "tp-fin" else {
            "OrderID", "ProductID", "Quantity", "UnitPrice", "DiscountPct"}
        candidates = [table for table in snapshot["tables"] if required <= {
            column["name"] for column in table["columns"]}]
        if len(candidates) != 1:
            raise _invalid("Snapshot cần đúng một bảng đầu vào chính cho preview.")
        primary = candidates[0]
        if (type(primary["rowCount"]) is not int or not 0 <= primary["rowCount"] <= MAX_ROWS or
                type(primary["columnCount"]) is not int or not 0 < primary["columnCount"] <= MAX_COLUMNS):
            raise _invalid("Số dòng/cột nguồn ngoài giới hạn preview.")
        source_hash = canonical_hash([source["hash"] for source in sources])
        return source_hash, {"rows": primary["rowCount"], "cols": primary["columnCount"]}
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid("Snapshot không đúng shape để dựng preview.") from exc


def _evidence_key(value):
    if (not isinstance(value, str) or not value or len(value) > 255 or
            value.startswith("/") or "\\" in value or ":" in value or
            any(part in {"", ".", ".."} for part in value.split("/")) or
            any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise _invalid("Source evidence cần đường dẫn tương đối an toàn.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _invalid("Tên file evidence phải là text UTF-8 hợp lệ.") from exc
    return value


def _verified_source_fingerprint(snapshot, evidence, scenario, default):
    """Kiểm original UTF-8 text đã nạp với hash nguồn; không đọc file hoặc log text."""
    if evidence is None:
        return default
    if not isinstance(evidence, dict) or not 0 < len(evidence) <= MAX_SOURCE_EVIDENCE_FILES:
        raise _invalid("Source evidence phải là map đầy đủ trong giới hạn số file.")
    total_bytes = 0
    for key, content in evidence.items():
        _evidence_key(key)
        if not key.lower().endswith(".csv") or not isinstance(content, str):
            raise _invalid("Source evidence chỉ nhận CSV original fullText.")
        # Số ký tự là cận dưới byte UTF-8: chặn trước khi encode chuỗi quá lớn.
        total_bytes += len(content)
        if total_bytes > MAX_SOURCE_EVIDENCE_BYTES:
            raise _invalid("Source evidence vượt giới hạn byte.")
        try:
            total_bytes += len(content.encode("utf-8")) - len(content)
        except UnicodeEncodeError as exc:
            raise _invalid("Source evidence phải là text UTF-8 hợp lệ.") from exc
        if total_bytes > MAX_SOURCE_EVIDENCE_BYTES:
            raise _invalid("Source evidence vượt giới hạn byte.")
    used = set()
    for source in snapshot["sources"]:
        origin = _evidence_key(source.get("origin"))
        key = origin.removeprefix("source/")
        if source.get("type") == "csv":
            if key not in evidence or key in used:
                raise _invalid("Source evidence thiếu hoặc chồng ánh xạ CSV nguồn.")
            text = evidence[key]
            expected = {canonical_hash(text.encode("utf-8").hex()), canonical_hash(text)}
            members = [key]
        elif source.get("type") == "folder":
            members = sorted(name for name in evidence if name.startswith(key + "/") and
                             "/" not in name[len(key) + 1:])
            if not members or used.intersection(members):
                raise _invalid("Source evidence thiếu hoặc chồng thành viên thư mục.")
            runtime = [{"name": name.rsplit("/", 1)[-1],
                        "hash": canonical_hash(evidence[name].encode("utf-8").hex())} for name in members]
            legacy = [{"name": name.rsplit("/", 1)[-1], "content": evidence[name]} for name in members]
            expected = {canonical_hash(runtime), canonical_hash(legacy)}
        else:
            raise _invalid("Source evidence hiện chỉ kiểm chứng nguồn CSV hoặc folder CSV.")
        if source["hash"] not in expected:
            raise _invalid("Source evidence không khớp fingerprint nguồn trong snapshot.", "AF_SPEC_STALE")
        used.update(members)
    if used != set(evidence):
        raise _invalid("Source evidence có file ngoài tập nguồn đã chốt.")
    # Oracle SALES định danh toàn tập original file texts; FIN giữ hash-list đã công bố.
    return canonical_hash([{name: evidence[name]} for name in sorted(evidence)]) if scenario == "tp-sales" else default


def _column(index):
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _cell(ref, value):
    if value is None:
        return ""
    if isinstance(value, (Decimal, int)):
        return f'<c r="{ref}"><v>{format(value, "f")}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'


def _verify_workbook(payload):
    counts = {"formulaCount": 0, "queryCount": 0, "connectionCount": 0}
    with ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            lower = name.lower()
            counts["queryCount"] += int(lower.startswith("xl/querytables/"))
            counts["connectionCount"] += int(lower == "xl/connections.xml")
            if (counts["queryCount"] or counts["connectionCount"] or lower.startswith("xl/externallinks/")):
                raise _invalid("Workbook preview không được có query, connection hoặc liên kết ngoài.")
            if lower.endswith(".xml"):
                tree = ET.fromstring(archive.read(name))
                counts["formulaCount"] += sum(node.tag.rsplit("}", 1)[-1] == "f" for node in tree.iter())
                if counts["formulaCount"]:
                    raise _invalid("Workbook preview không được có formula.")
    return counts


def build_workbook(columns, rows, *, sheet: str, marker: str) -> bytes:
    """XLSX tối thiểu có values-only, header hàng 1, marker riêng sau dữ liệu."""
    estimated = _matrix(columns, rows)
    _text(sheet)
    _text(marker)
    if not sheet or len(sheet) > 31 or re.search(r"[\[\]:*?/\\]", sheet) or sheet.startswith("'") or sheet.endswith("'"):
        raise _invalid("Tên sheet preview không hợp lệ.")
    if not marker or not marker.startswith("LOCAL_DATA_COPILOT|"):
        raise _invalid("Workbook preview phải có marker nhận diện.")
    if estimated + len(marker.encode("utf-8")) * 5 + len(sheet.encode("utf-8")) * 5 > MAX_WORKBOOK_BYTES:
        raise _invalid("Workbook preview vượt giới hạn byte trước khi dựng XML.")
    matrix = [columns, *rows, [], [marker]]
    body = []
    for index, row in enumerate(matrix, 1):
        body.append(f'<row r="{index}">' + "".join(_cell(f"{_column(col)}{index}", value)
                    for col, value in enumerate(row, 1)) + "</row>")
    parts = (
        ("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
         '<Default Extension="xml" ContentType="application/xml"/>'
         '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
         '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'),
        ("_rels/.rels", f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId1" Type="{_REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>'),
        ("xl/workbook.xml", f'<workbook xmlns="{_MAIN}" xmlns:r="{_REL}"><sheets><sheet name={quoteattr(sheet)} sheetId="1" r:id="rId1"/></sheets></workbook>'),
        ("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId1" Type="{_REL}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'),
        ("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{_MAIN}"><sheetData>{"".join(body)}</sheetData></worksheet>'),
    )
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        for name, content in parts:
            entry = ZipInfo(name, _ZIP_TIME)
            entry.compress_type = ZIP_STORED
            entry.create_system = 0
            entry.external_attr = 0
            archive.writestr(entry, content.encode("utf-8"))
    payload = stream.getvalue()
    if len(payload) > MAX_WORKBOOK_BYTES:
        raise _invalid("Workbook preview vượt giới hạn byte.")
    _verify_workbook(payload)
    return payload


def preview_marker(result, spec, *, sheet):
    """preview= là digest payload kết quả, không phải previewHash của artifact."""
    _validated_spec(spec)
    _text(sheet)
    return ("LOCAL_DATA_COPILOT|" + sheet + "|spec=" + spec["fingerprint"] +
            "|preview=" + result_digest(result) + "|labels=" + ",".join(spec["labels"]))


def build_preview(result, spec, snapshot, *, sheet, marker, source_evidence=None):
    """Artifact bind Spec/snapshot và nội dung kết quả; không mở lại file nguồn."""
    _validated_spec(spec)
    digest = result_digest(result)
    scenario = next((name for name, columns in RESULT_COLUMNS.items() if result["columns"] == columns), None)
    if scenario is None:
        raise _invalid("Kết quả không thuộc schema preview đã hỗ trợ.")
    _supported_recipe(spec, scenario)
    expected_sheet = "PnL_Preview" if scenario == "tp-fin" else "Sales_Preview"
    if sheet != expected_sheet:
        raise _invalid("Sheet preview không khớp loại báo cáo.")
    source_hash, before = _snapshot_info(snapshot, spec, scenario)
    source_hash = _verified_source_fingerprint(snapshot, source_evidence, scenario, source_hash)
    full_marker = ("LOCAL_DATA_COPILOT|" + sheet + "|spec=" + spec["fingerprint"] +
                   "|preview=" + digest + "|labels=" + ",".join(spec["labels"]))
    base_marker = ("LOCAL_DATA_COPILOT|" + sheet + "|spec=" + spec["fingerprint"] +
                   "|labels=" + ",".join(spec["labels"]))
    if not isinstance(marker, str) or marker not in (base_marker, full_marker):
        raise _invalid("Marker không bind đúng Spec, payload hoặc nhãn hiện tại.", "AF_SPEC_STALE")
    payload = build_workbook(result["columns"], result["rows"], sheet=sheet, marker=full_marker)
    artifact = {"schemaVersion": "1.0", "specFingerprint": spec["fingerprint"],
                "target": {"workbook": "temp_copy", "sheet": sheet, "mode": "values_only", "marker": full_marker},
                "counts": _verify_workbook(payload),
                "source": {"before": source_hash, "after": source_hash, "unchanged": True},
                "sheets": {"before": before, "after": {"rows": len(result["rows"]), "cols": len(result["columns"])}},
                "variantOf": None, "variantReason": None, "hashBasis": list(_BASIS)}
    artifact["previewHash"] = canonical_hash({key: artifact[key] for key in _BASIS})
    return deepcopy(artifact)


@contextmanager
def temp_workspace():
    """Workspace nằm ngoài repository, được xóa cả khi caller gặp lỗi."""
    parent = Path(tempfile.gettempdir()).resolve()
    repository = Path(__file__).resolve().parents[2]
    if parent.is_relative_to(repository):
        raise _invalid("Thư mục temp phải nằm ngoài repository.")
    with tempfile.TemporaryDirectory(prefix="assistant-wl5-", dir=parent) as directory:
        yield Path(directory)
