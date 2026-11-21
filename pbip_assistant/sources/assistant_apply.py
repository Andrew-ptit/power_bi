"""Thêm sheet kết quả WL6 vào bytes XLSX; không mở file hoặc tự Save."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import io
import posixpath
import re
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr
from zipfile import BadZipFile, ZIP_STORED, ZipFile, ZipInfo

from pbip_assistant.errors import InputError
from .assistant_findings import _decimal
from .assistant_ingest import canonical_hash
from .assistant_preview import (
    RESULT_COLUMNS, _supported_recipe, _validated_spec, build_workbook,
    preview_marker, result_digest,
)


MAX_PACKAGE_BYTES = 32 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_PART_BYTES = 16 * 1024 * 1024
MAX_PARTS = 1024
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
_SHEET_TYPE = _REL + "/worksheet"
_FIXED_TIME = (2026, 1, 1, 0, 0, 0)
_PREVIEW_BASIS = ("specFingerprint", "target", "counts", "source", "sheets", "variantOf", "variantReason")
_BASIS = ("specFingerprint", "previewHash", "approval", "target", "written", "source",
          "workbookSaved", "labels", "appliedAt", "variantOf", "variantReason")
_META = {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
_HASH = re.compile(r"sha256:[a-f0-9]{64}")


def _partial(message):
    return InputError("AF_WRITE_PARTIAL", "apply", message)


def _xml(payload):
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", payload, re.I):
        raise _partial("Package XML có khai báo chưa được hỗ trợ.")
    try:
        return ET.fromstring(payload)
    except (ET.ParseError, ValueError) as exc:
        raise _partial("Package chứa XML không hợp lệ.") from exc


def _package(package_bytes):
    if not isinstance(package_bytes, bytes) or not package_bytes or len(package_bytes) > MAX_PACKAGE_BYTES:
        raise _partial("Cần bytes XLSX trong giới hạn package.")
    try:
        with ZipFile(io.BytesIO(package_bytes)) as archive:
            entries = archive.infolist()
            if (not entries or len(entries) > MAX_PARTS or
                    sum(entry.file_size for entry in entries) > MAX_EXPANDED_BYTES or
                    any(entry.file_size > MAX_PART_BYTES for entry in entries)):
                raise _partial("Package vượt giới hạn số part hoặc kích thước mở rộng.")
            names, parts = [], {}
            for entry in entries:
                name = entry.filename
                if (not name or name.startswith("/") or "\\" in name or ":" in name or
                        any(part in {"", ".", ".."} for part in name.split("/")) or
                        name in parts or entry.flag_bits & 1 or entry.is_dir()):
                    raise _partial("Tên part trùng, không an toàn hoặc package được mã hóa.")
                names.append(name)
                parts[name] = archive.read(entry)
    except (BadZipFile, OSError, RuntimeError, NotImplementedError) as exc:
        raise _partial("Không đọc được package XLSX.") from exc
    if not _META <= set(parts):
        raise _partial("Package thiếu metadata workbook cần thiết.")
    return names, parts


def _metadata(parts):
    workbook = _xml(parts["xl/workbook.xml"])
    relationships = _xml(parts["xl/_rels/workbook.xml.rels"])
    content = _xml(parts["[Content_Types].xml"])
    if (workbook.tag != "{" + _MAIN + "}workbook" or
            relationships.tag != "{" + _PKG_REL + "}Relationships" or
            content.tag != "{" + _CONTENT + "}Types"):
        raise _partial("Namespace workbook chưa được hỗ trợ.")
    by_id = {}
    for relationship in relationships:
        if relationship.tag != "{" + _PKG_REL + "}Relationship":
            raise _partial("Relationship workbook không hợp lệ.")
        identifier, target = relationship.get("Id"), relationship.get("Target")
        if (not identifier or identifier in by_id or not target or
                relationship.get("TargetMode") == "External" or "\\" in target or ":" in target):
            raise _partial("Relationship trùng, ngoài package hoặc không hợp lệ.")
        by_id[identifier] = relationship
    sheets_nodes = workbook.findall("{" + _MAIN + "}sheets")
    if len(sheets_nodes) != 1:
        raise _partial("Workbook cần đúng một danh sách sheet.")
    sheets, seen_names, seen_ids, seen_paths = [], set(), set(), set()
    for sheet in sheets_nodes[0]:
        name, identifier = sheet.get("name"), sheet.get("sheetId")
        relation = by_id.get(sheet.get("{" + _REL + "}id"))
        if (sheet.tag != "{" + _MAIN + "}sheet" or not name or name.casefold() in seen_names or
                not identifier or re.fullmatch(r"[1-9][0-9]*", identifier) is None or
                identifier in seen_ids or relation is None or relation.get("Type") != _SHEET_TYPE):
            raise _partial("Danh sách sheet hoặc liên kết sheet không hợp lệ.")
        target = relation.get("Target")
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
        if not path.startswith("xl/worksheets/") or path not in parts or path in seen_paths:
            raise _partial("Sheet không trỏ tới part worksheet duy nhất trong package.")
        seen_names.add(name.casefold())
        seen_ids.add(identifier)
        seen_paths.add(path)
        sheets.append({"name": name, "id": int(identifier), "path": path, "attributes": dict(sheet.attrib)})
    if not sheets:
        raise _partial("Workbook không có sheet nguồn.")
    return sheets, by_id


def _worksheet_rows(payload):
    root = _xml(payload)
    if root.tag != "{" + _MAIN + "}worksheet":
        raise _partial("Part không phải worksheet được hỗ trợ.")
    data = root.findall("{" + _MAIN + "}sheetData")
    if len(data) != 1:
        raise _partial("Worksheet thiếu vùng dữ liệu duy nhất.")
    return data[0].findall("{" + _MAIN + "}row")


def _marker_in_sheet(payload):
    root = _xml(payload)
    return any(node.tag == "{" + _MAIN + "}t" and
               (node.text or "").startswith("LOCAL_DATA_COPILOT|") for node in root.iter())


def verify_values_only(package_bytes) -> None:
    """Sheet có marker chỉ có giá trị; formula sheet nguồn được bảo toàn."""
    _, parts = _package(package_bytes)
    sheets, _ = _metadata(parts)
    for name, payload in parts.items():
        lower = name.lower()
        if (lower.startswith(("xl/querytables/", "xl/externallinks/", "xl/pivotcache", "xl/pivottables/")) or
                lower == "xl/connections.xml"):
            raise _partial("Package có query, connection, pivot hoặc liên kết ngoài chưa hỗ trợ.")
        if lower.endswith(".rels"):
            tree = _xml(payload)
            if any(node.get("TargetMode") == "External" for node in tree.iter()):
                raise _partial("Package có relationship ngoài chưa hỗ trợ.")
    for sheet in sheets:
        payload = parts[sheet["path"]]
        root = _xml(payload)
        marked = (_marker_in_sheet(payload) or
                  sheet["name"].casefold() in {"pnl_result", "sales_result"})
        if marked and any(node.tag.rsplit("}", 1)[-1] in {
                "f", "queryTableParts", "pivotTableParts", "tableParts"} for node in root.iter()):
            raise _partial("Sheet kết quả phải values-only, không formula/query/pivot/table.")


def _read_cell(cell):
    if cell.find("{" + _MAIN + "}f") is not None:
        raise _partial("Không đọc formula như giá trị kết quả.")
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//{" + _MAIN + "}t"))
    if kind in (None, "n"):
        value = cell.find("{" + _MAIN + "}v")
        if value is None or value.text is None:
            raise _partial("Ô numeric kết quả không có giá trị.")
        try:
            return _decimal(value.text)
        except InputError as exc:
            raise _partial("Ô numeric kết quả không hữu hạn hoặc vượt giới hạn.") from exc
    raise _partial("Kiểu ô kết quả chưa được hỗ trợ.")


def _column(index):
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(65 + remainder) + value
    return value


def read_result_sheet(package_bytes, sheet):
    """Đọc lại sheet marked độc lập bằng ZIP/XML; số giữ Decimal."""
    _, parts = _package(package_bytes)
    sheets, _ = _metadata(parts)
    matches = [item for item in sheets if item["name"] == sheet]
    if len(matches) != 1:
        raise _partial("Không tìm thấy sheet kết quả cần đọc lại.")
    rows = _worksheet_rows(parts[matches[0]["path"]])
    if len(rows) < 3:
        raise _partial("Sheet kết quả thiếu header, vùng dữ liệu hoặc marker.")
    marker_cells = rows[-1].findall("{" + _MAIN + "}c")
    if (len(marker_cells) != 1 or not isinstance(value := _read_cell(marker_cells[0]), str) or
            not value.startswith("LOCAL_DATA_COPILOT|" + sheet + "|") or
            rows[-1].get("r") != str(len(rows)) or
            marker_cells[0].get("r") != "A" + str(len(rows))):
        raise _partial("Sheet kết quả thiếu marker đúng đích.")
    if list(rows[-2]) or rows[-2].get("r") != str(len(rows) - 1):
        raise _partial("Marker phải nằm riêng sau vùng dữ liệu.")
    header_cells = rows[0].findall("{" + _MAIN + "}c")
    columns = [_read_cell(cell) for cell in header_cells]
    if (rows[0].get("r") != "1" or not columns or
            any(not isinstance(column, str) or not column for column in columns) or len(set(columns)) != len(columns)):
        raise _partial("Header kết quả không hợp lệ.")
    if any(cell.get("r") != _column(index) + "1" for index, cell in enumerate(header_cells, 1)):
        raise _partial("Read-back tọa độ header không khớp cột kết quả.")
    result = []
    for index, row in enumerate(rows[1:-2], 2):
        cells = row.findall("{" + _MAIN + "}c")
        if row.get("r") != str(index) or len(cells) != len(columns):
            raise _partial("Read-back thiếu hàng hoặc cột kết quả.")
        for column_index, cell in enumerate(cells, 1):
            if cell.get("r") != _column(column_index) + str(index):
                raise _partial("Read-back tọa độ ô không khớp vùng kết quả.")
        result.append([_read_cell(cell) for cell in cells])
    return {"columns": columns, "rows": result}


def _append_child(payload, parent_name, child):
    closing = re.compile(rb"</((?:[A-Za-z_][A-Za-z0-9_.-]*:)?" + parent_name.encode("ascii") + rb")\s*>")
    matches = list(closing.finditer(payload))
    if len(matches) == 1:
        position = matches[0].start()
        return payload[:position] + child + payload[position:]
    raise _partial("Metadata XML chưa hỗ trợ append an toàn.")


def _write_package(names, parts):
    if sum(len(value) for value in parts.values()) > MAX_EXPANDED_BYTES:
        raise _partial("Package kết quả vượt giới hạn mở rộng.")
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        for name in names:
            info = ZipInfo(name, _FIXED_TIME)
            info.compress_type = ZIP_STORED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, parts[name])
    payload = buffer.getvalue()
    if len(payload) > MAX_PACKAGE_BYTES:
        raise _partial("Package kết quả vượt giới hạn byte.")
    return payload


def _bindings(result, target_sheet, marker, labels, spec, preview):
    _validated_spec(spec)
    digest = result_digest(result)
    scenario = next((name for name, columns in RESULT_COLUMNS.items() if result["columns"] == columns), None)
    if scenario is None:
        raise _partial("Schema kết quả chưa được hỗ trợ.")
    text_indexes = (0, 1, 2, 3, 7, 8) if scenario == "tp-fin" else (0,)
    number_indexes = (4, 5, 6) if scenario == "tp-fin" else (1, 2, 3)
    for row in result["rows"]:
        if (any(not isinstance(row[index], str) for index in text_indexes) or
                any(isinstance(row[index], bool) or not isinstance(row[index], (Decimal, int))
                    for index in number_indexes)):
            raise _partial("Cột số kết quả phải là numeric, không phải chuỗi hoặc công thức.")
        if scenario == "tp-sales" and any(Decimal(row[index]) < 0 or
                Decimal(row[index]) != Decimal(row[index]).to_integral_value() for index in (2, 3)):
            raise _partial("Số đơn và khách phải là số nguyên không âm.")
    _supported_recipe(spec, scenario)
    expected_sheet = "PnL_Result" if scenario == "tp-fin" else "Sales_Result"
    preview_sheet = "PnL_Preview" if scenario == "tp-fin" else "Sales_Preview"
    if (not isinstance(labels, list) or labels != spec["labels"] or target_sheet != expected_sheet or
            not isinstance(preview, dict) or preview.get("hashBasis") != list(_PREVIEW_BASIS) or
            preview.get("previewHash") != canonical_hash({key: preview.get(key) for key in _PREVIEW_BASIS}) or
            preview.get("specFingerprint") != spec["fingerprint"] or
            preview.get("counts") != {"formulaCount": 0, "queryCount": 0, "connectionCount": 0} or
            preview.get("sheets", {}).get("after") != {"rows": len(result["rows"]), "cols": len(result["columns"])}):
        raise _partial("Kết quả, Preview, đích hoặc nhãn không khớp bản đã duyệt.")
    target = preview.get("target", {})
    if (target.get("sheet") != preview_sheet or target.get("mode") != "values_only" or
            target.get("workbook") != "temp_copy" or
            target.get("marker") != preview_marker(result, spec, sheet=preview_sheet)):
        raise _partial("Digest payload không khớp kết quả đã Preview.")
    source = preview.get("source", {})
    if (source.get("unchanged") is not True or source.get("before") != source.get("after") or
            not isinstance(source.get("before"), str) or _HASH.fullmatch(source["before"]) is None):
        raise _partial("Nguồn Preview không còn nguyên trạng.")
    expected_marker = ("LOCAL_DATA_COPILOT|" + target_sheet + "|spec=" + spec["fingerprint"] +
                       "|preview=" + preview["previewHash"] + "|labels=" + ",".join(labels))
    if marker != expected_marker:
        raise _partial("Marker Apply không bind Spec, Preview artifact hoặc nhãn.")
    return digest, expected_marker


def apply_result(workbook_bytes, *, result, target_sheet, marker, labels,
                 approval, spec, preview, fail_after_sheet=False, applied_at=None):
    """Tiêu thụ approval rồi thêm sheet trong bytes mới; lỗi không cấp lại token."""
    from .assistant_approval import consume_approval, validate_approval

    validate_approval(approval, spec, preview)
    captured = deepcopy({"spec": spec, "preview": preview, "labels": labels, "result": result})
    spec, preview, labels = captured["spec"], captured["preview"], captured["labels"]
    frozen = captured["result"]
    validate_approval(approval, spec, preview)
    try:
        if not isinstance(applied_at, str) or not applied_at:
            raise ValueError
        timestamp = datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError
    except ValueError as exc:
        raise _partial("Caller phải cung cấp applied_at tường minh dạng ISO datetime có timezone.") from exc
    try:
        digest, expected_marker = _bindings(frozen, target_sheet, marker, labels, spec, preview)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise _partial("Kết quả hoặc metadata Preview không đúng shape đã hỗ trợ.") from exc
    if type(fail_after_sheet) is not bool:
        raise _partial("Cờ mô phỏng lỗi ghi phải là boolean.")
    consumed = consume_approval(approval)
    try:
        names, original_parts = _package(workbook_bytes)
        verify_values_only(workbook_bytes)
        old_sheets, relationships = _metadata(original_parts)
        if any(sheet["name"].casefold() == target_sheet.casefold() for sheet in old_sheets):
            raise _partial("Tên sheet kết quả đã tồn tại; không ghi đè hoặc đổi tên.")
        sheet_number = max([int(match.group(1)) for name in names
                            if (match := re.fullmatch(r"xl/worksheets/sheet([1-9][0-9]*)\.xml", name))] + [0]) + 1
        new_path = "xl/worksheets/sheet" + str(sheet_number) + ".xml"
        new_sheet_id = max(sheet["id"] for sheet in old_sheets) + 1
        relation_number = 1
        while "rId" + str(relation_number) in relationships:
            relation_number += 1
        relation_id = "rId" + str(relation_number)
        minimal = build_workbook(**frozen, sheet=target_sheet, marker=expected_marker)
        with ZipFile(io.BytesIO(minimal)) as archive:
            sheet_xml = archive.read("xl/worksheets/sheet1.xml")
        parts = dict(original_parts)
        parts[new_path] = sheet_xml
        if fail_after_sheet:
            raise _partial("Lỗi ghi mô phỏng sau khi dựng sheet; không retry hoặc trả thành công.")
        new_sheet = (f'<sheet xmlns="{_MAIN}" xmlns:r="{_REL}" name={quoteattr(target_sheet)} '
                     f'sheetId="{new_sheet_id}" r:id="{relation_id}"/>').encode("utf-8")
        new_relationship = (f'<Relationship xmlns="{_PKG_REL}" Id="{relation_id}" Type="{_SHEET_TYPE}" '
                            f'Target="worksheets/sheet{sheet_number}.xml"/>').encode("utf-8")
        new_override = (f'<Override xmlns="{_CONTENT}" PartName="/{new_path}" '
                        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>').encode("utf-8")
        parts["xl/workbook.xml"] = _append_child(parts["xl/workbook.xml"], "sheets", new_sheet)
        parts["xl/_rels/workbook.xml.rels"] = _append_child(parts["xl/_rels/workbook.xml.rels"], "Relationships", new_relationship)
        parts["[Content_Types].xml"] = _append_child(parts["[Content_Types].xml"], "Types", new_override)
        output = _write_package([*names, new_path], parts)
        verify_values_only(output)
        _, after_parts = _package(output)
        after_sheets, _ = _metadata(after_parts)
        if (after_sheets[:-1] != old_sheets or after_sheets[-1]["name"] != target_sheet or
                any(after_parts[name] != payload for name, payload in original_parts.items() if name not in _META)):
            raise _partial("Read-back cho thấy sheet hoặc part nguồn đã thay đổi.")
        written_rows = _worksheet_rows(after_parts[new_path])
        marker_cells = written_rows[-1].findall("{" + _MAIN + "}c")
        if len(marker_cells) != 1 or _read_cell(marker_cells[0]) != expected_marker:
            raise _partial("Read-back marker không khớp Spec, Preview hoặc nhãn đã duyệt.")
        readback = read_result_sheet(output, target_sheet)
        if result_digest(readback) != digest:
            raise _partial("Read-back giá trị không khớp kết quả đã Preview; không được coi là ghi thành công.")
    except InputError as exc:
        if exc.code == "AF_WRITE_PARTIAL":
            raise
        raise _partial("Ghi hoặc read-back chưa được xác minh thành công; không retry.") from exc
    except (KeyError, TypeError, ValueError, OSError, BadZipFile, OverflowError) as exc:
        raise _partial("Ghi hoặc read-back không xác định thành công; không retry.") from exc
    artifact = {"schemaVersion": "1.0", "specFingerprint": spec["fingerprint"], "previewHash": preview["previewHash"],
                "approval": consumed,
                "target": {"workbook": "current", "sheet": target_sheet, "mode": "values_only",
                           "writeMode": "new_sheet_only", "marker": expected_marker},
                "written": {"rowCount": len(frozen["rows"]), "columnCount": len(frozen["columns"])},
                "source": {"before": preview["source"]["before"], "after": preview["source"]["after"],
                           "unchanged": True, "sheetsWritten": []},
                "workbookSaved": False, "labels": list(labels), "appliedAt": applied_at,
                "variantOf": None, "variantReason": None, "hashBasis": list(_BASIS)}
    artifact["hash"] = canonical_hash({key: artifact[key] for key in _BASIS})
    return {"workbook": output, "apply": artifact}
