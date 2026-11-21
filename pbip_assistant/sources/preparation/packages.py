"""Bounded, read-only transfer packages and independently derived image hashes."""
import base64
import csv
import hashlib
from copy import deepcopy
from io import BytesIO, StringIO
import json
import math
import re
import struct
from zipfile import ZipFile

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_ingest import canonical_hash, _bounded_bytes, _unchanged
from pbip_assistant.sources.xlsx import MAIN, REL, _safe_member
from .csv_typing import build_typed_frame
from .inventory import inventory_file_path, review_import, verify_inventory, _xml


MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_CELLS = 400000
PREFLIGHT = {"validated": True, "definedNames": False, "tables": False, "externalLinks": False,
             "protected": False, "merges": False}


def _fail(detail):
    return InputError("DP_UNSUPPORTED_PRESERVATION", "preparation", detail)


def image_fingerprint(image):
    """IDs are retained as identity evidence but unknown IDs cannot affect planned import hashes."""
    if (not isinstance(image, dict) or set(image) - {"version", "sheets", "fingerprint", "preservation", "fullFingerprint"}
            or image.get("version") != 1 or not isinstance(image.get("sheets"), list)
            or not 0 < len(image["sheets"]) <= 200):
        raise _fail("Invalid bounded semantic image")
    names, ids, cells, projected = set(), set(), 0, []
    for sheet in image["sheets"]:
        fields = {"sheetId", "name", "rowOffset", "columnOffset", "values", "formulas", "formulaCells", "numberFormats"}
        if not isinstance(sheet, dict) or set(sheet) - {"preservation"} != fields:
            raise _fail("Unsupported worksheet image fields")
        name, sid = sheet["name"], sheet["sheetId"]
        if (not isinstance(name, str) or not 0 < len(name) <= 31 or name.casefold() in names
                or not isinstance(sid, str) or not 0 < len(sid) <= 128 or sid in ids):
            raise _fail("Duplicate or invalid worksheet identity")
        names.add(name.casefold()); ids.add(sid)
        values = sheet["values"]
        if not isinstance(values, list) or len(values) > 100000:
            raise _fail("Invalid worksheet dimensions")
        width = len(values[0]) if values else 0
        if width > 200 or (values and not width):
            raise _fail("Worksheet exceeds the supported frame")
        for key in ("values", "formulas", "numberFormats"):
            matrix = sheet[key]
            if not isinstance(matrix, list) or len(matrix) != len(values) or any(not isinstance(r, list) or len(r) != width for r in matrix):
                raise _fail("Image matrices have inconsistent dimensions")
            for row in matrix:
                for value in row:
                    if key == "numberFormats":
                        valid = isinstance(value, str) and len(value) <= 256
                    else:
                        valid = (value is None or type(value) in (str, bool, int, float)) and not (isinstance(value, str) and len(value) > 10000) and not (isinstance(value, float) and not math.isfinite(value))
                    if not valid:
                        raise _fail("Image contains unsupported cell data")
        for key, maximum, size in (("rowOffset", 1048576, len(values)), ("columnOffset", 16384, width)):
            if type(sheet[key]) is not int or sheet[key] < 0 or sheet[key] + size > maximum:
                raise _fail("Image frame is outside worksheet bounds")
        mask = sheet["formulaCells"]
        if (not isinstance(mask, list) or len(mask) > len(values) * width
                or any(not isinstance(pair, list) or len(pair) != 2 or any(type(v) is not int for v in pair)
                       or not 0 <= pair[0] < len(values) or not 0 <= pair[1] < width for pair in mask)
                or len({tuple(p) for p in mask}) != len(mask)):
            raise _fail("Invalid native formula mask")
        cells += len(values) * width
        semantic = deepcopy({k: v for k, v in sheet.items() if k not in {"sheetId", "preservation"}})
        # Formula results may recalculate after a native edit; the expression
        # and mask, rather than cached results, define its semantic identity.
        for r, c in mask:
            semantic["values"][r][c] = None
        for key in ("values", "formulas"):
            for row in semantic[key]:
                for c, value in enumerate(row):
                    if type(value) in (int, float):
                        try:
                            number = float(value) if value else 0.0
                            if not math.isfinite(number): raise ValueError("Nonfinite native double")
                            row[c] = {"$number": struct.pack(">d", number).hex()}
                        except (OverflowError, ValueError) as exc:
                            raise _fail("Image cell is outside native double bounds") from exc
        projected.append(semantic)
    if cells > MAX_CELLS or len(json.dumps(image, ensure_ascii=False).encode()) > MAX_IMAGE_BYTES:
        raise InputError("REQUEST_LIMIT", "image", "Full affected workbook exceeds the supported recovery envelope")
    fingerprint = canonical_hash({"version": 1, "sheets": sorted(projected, key=lambda s: s["name"])})
    if image.get("fingerprint", fingerprint) != fingerprint:
        raise InputError("DP_BACKUP_FAILED", "image", "Semantic image fingerprint does not match its contents")
    return fingerprint


def _xlsx_frames(payload):
    with ZipFile(BytesIO(payload)) as archive:
        names = set(archive.namelist())
        # Native copying of these structures is not yet preservation qualified.
        allowed = re.compile(r"(?:\[Content_Types\]\.xml|_rels/\.rels|docProps/[^/]+\.xml|xl/(?:workbook\.xml|_rels/workbook\.xml\.rels|styles\.xml|sharedStrings\.xml|theme/[^/]+\.xml|worksheets/sheet\d+\.xml))$")
        if any(not allowed.fullmatch(name) for name in names):
            raise _fail("Workbook contains unsupported package structures")
        book = _xml(archive.read("xl/workbook.xml"))
        if any(book.find(f"{{{MAIN}}}{tag}") is not None for tag in ("definedNames", "workbookProtection", "externalReferences")):
            raise _fail("Names, protection and external links require additional preservation support")
        props = book.find(f"{{{MAIN}}}workbookPr")
        if props is not None and props.get("date1904") in {"1", "true"}:
            raise _fail("Cross-workbook 1904 date conversion is not supported")
        relations = _xml(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r for r in relations}
        if any(r.get("TargetMode") == "External" for r in relations):
            raise _fail("External workbook relationships are unsupported")
        strings = []
        if "xl/sharedStrings.xml" in names:
            strings = ["".join(node.itertext()) for node in _xml(archive.read("xl/sharedStrings.xml"))]
        formats = ["General"]
        if "xl/styles.xml" in names:
            styles = _xml(archive.read("xl/styles.xml"))
            custom = {n.get("numFmtId"): n.get("formatCode") for n in styles.findall(f"{{{MAIN}}}numFmts/{{{MAIN}}}numFmt")}
            builtins = {"0": "General", "1": "0", "2": "0.00", "9": "0%", "10": "0.00%", "49": "@"}
            formats = []
            for style in styles.findall(f"{{{MAIN}}}cellXfs/{{{MAIN}}}xf"):
                fmt = custom.get(style.get("numFmtId"), builtins.get(style.get("numFmtId", "0")))
                if fmt is None:
                    raise _fail("Locale-dependent built-in number format is unsupported")
                formats.append(fmt)
            formats = formats or ["General"]
        result = {}
        for entry in book.findall(f"{{{MAIN}}}sheets/{{{MAIN}}}sheet"):
            if entry.get("state", "visible") != "visible":
                raise _fail("Hidden worksheet preservation is unsupported")
            relation = targets.get(entry.get(f"{{{REL}}}id"))
            if relation is None:
                raise _fail("Worksheet relationship is missing")
            part = _safe_member("xl/workbook.xml", relation.get("Target", ""), names, label="worksheet")
            sheet = _xml(archive.read(part))
            if any(child.tag.rsplit("}", 1)[-1] not in {"dimension", "sheetViews", "sheetFormatPr", "cols", "sheetData", "pageMargins", "pageSetup", "printOptions"} for child in sheet):
                raise _fail("Worksheet contains unsupported structures, merges or protection")
            entries = []
            for cell in sheet.findall(f"{{{MAIN}}}sheetData/{{{MAIN}}}row/{{{MAIN}}}c"):
                match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*)", cell.get("r", ""))
                if not match:
                    raise _fail("Worksheet cell address is invalid")
                col = 0
                for char in match[1]: col = col * 26 + ord(char) - 64
                row, col = int(match[2]) - 1, col - 1
                if row >= 100000 or col >= 200:
                    raise _fail("Worksheet exceeds the supported semantic recovery frame")
                raw = cell.findtext(f"{{{MAIN}}}v")
                typ = cell.get("t")
                if typ == "s": value = strings[int(raw)]
                elif typ == "inlineStr": value = "".join(cell.find(f"{{{MAIN}}}is").itertext())
                elif typ == "b": value = raw == "1"
                elif typ in {"str", "e"}: value = raw or ""
                elif typ in {None, "n"}:
                    value = float(raw) if raw is not None else ""
                    if isinstance(value, float) and value.is_integer(): value = int(value)
                else: raise _fail("Unsupported workbook cell type")
                formula = cell.find(f"{{{MAIN}}}f")
                if formula is not None and (formula.attrib or not formula.text or any(token in formula.text for token in ("[", "]", "#", "_xlfn.", "_xlws."))):
                    raise _fail("Shared, external or dynamic formulas are unsupported")
                style = int(cell.get("s", "0"))
                if not 0 <= style < len(formats): raise _fail("Invalid cell format index")
                entries.append((row, col, value, "=" + formula.text if formula is not None else value, formula is not None, formats[style]))
            row_origin = min((e[0] for e in entries), default=0)
            col_origin = min((e[1] for e in entries), default=0)
            height = max((e[0] for e in entries), default=-1) + 1 - row_origin
            width = max((e[1] for e in entries), default=-1) + 1 - col_origin
            if height * width > MAX_CELLS: raise _fail("Workbook exceeds semantic cell limit")
            frame = {"rowOffset": row_origin, "columnOffset": col_origin, "values": [[""] * width for _ in range(height)],
                     "formulas": [[""] * width for _ in range(height)], "formulaCells": [],
                     "numberFormats": [["General"] * width for _ in range(height)]}
            for r, c, value, formula, is_formula, fmt in entries:
                r, c = r - row_origin, c - col_origin
                frame["values"][r][c], frame["formulas"][r][c], frame["numberFormats"][r][c] = value, formula, fmt
                if is_formula: frame["formulaCells"].append([r, c])
            result[entry.get("name")] = frame
        return result


_SKIP_MESSAGES = {
    "CSV_COLUMN_COUNT": "CSV rows have inconsistent column counts.",
    "CSV_HEADER": "CSV header is missing or invalid.",
    "CSV_DUPLICATE_HEADER": "CSV headers are duplicated.",
    "CSV_ENCODING": "CSV encoding could not be read.",
    "CSV_LIMIT": "CSV exceeds the supported import limits.",
    "REQUEST_LIMIT": "File exceeds the supported import limits.",
    "INVALID_CSV": "CSV records could not be read.",
    "INVALID_XLSX": "Workbook could not be read.",
    "DP_SOURCE_STALE": "Selected file is unavailable.",
    "DP_UNSUPPORTED_SOURCE": "Selected file type is unsupported.",
}


def _skipped(file_id, file_name, code):
    return {"fileId": file_id, "fileName": file_name, "status": "skipped", "reading": None,
            "sheets": [], "decisions": [], "readingDecisions": [], "issues": [
                {"code": code, "message": _SKIP_MESSAGES.get(code, "File could not be imported.")}]}


def _csv_frame(payload, reading, date_system):
    reader = csv.reader(StringIO(payload.decode(reading["encoding"]), newline=""),
                        delimiter=reading["delimiter"], strict=True)
    for _ in range(reading["header_row"] - 1):
        next(reader, None)
    headers = next(reader, [])
    if not headers or len(headers) > 200:
        raise InputError("REQUEST_LIMIT", "packages", "CSV exceeds the supported column limit")
    rows = []
    for row in reader:
        if len(row) != len(headers):
            raise InputError("CSV_COLUMN_COUNT", "packages", "CSV row widths require correction")
        if len(rows) + 2 > 100000 or (len(rows) + 2) * len(headers) > MAX_CELLS:
            raise InputError("REQUEST_LIMIT", "packages", "CSV exceeds the supported frame size")
        rows.append(row)
    metadata = {"encoding": reading["encoding"], "delimiter": reading["delimiter"],
                "headerRow": reading["header_row"], "columns": len(headers)}
    typed = build_typed_frame(headers, rows, date_system=date_system or "1900")
    values, formats, decisions = typed["values"], typed["numberFormats"], typed["decisions"]
    if date_system is None and any("yyyy-mm-dd" in row for row in formats):
        raise InputError("DP_DATE_SYSTEM_REQUIRED", "dateSystem", "Dated CSV columns require the workbook date system")
    frame = {"rowOffset": 0, "columnOffset": 0, "values": values, "formulas": deepcopy(values),
             "formulaCells": [], "numberFormats": formats}
    return frame, decisions, metadata


def _imported(entry, package, reading=None, decisions=None):
    reading_decisions = []
    if reading and "fileSummary" in entry:  # Selection inventory infers its codec and delimiter.
        if reading["encoding"] == "cp1252":
            reading_decisions.append({"reasonCode": "ENCODING_FALLBACK"})
        if reading["delimiter"] != ",":
            reading_decisions.append({"reasonCode": "DELIMITER_INFERRED"})
    return {"fileId": entry["fileId"], "fileName": entry["fileName"], "status": "imported",
            "reading": reading, "decisions": decisions or [], "readingDecisions": reading_decisions, "issues": [],
            "sheets": [{k: s[k] for k in ("sourceSheetId", "targetName")} for s in package["sheets"]]}


def build_packages(inventory, inventory_hash, mappings, existing_names, *, native_runner=None, workspace_manager=None,
                   date_system=None, report=None, reviewed_xlsx=None):
    review_import(inventory, inventory_hash, mappings, existing_names)
    if date_system not in (None, "1900", "1904"):
        raise InputError("INVALID_REQUEST", "dateSystem", "Unknown workbook date system")
    selected = {m["fileId"] for m in mappings}
    files = []
    for index, error in enumerate(inventory._errors):
        # A file rejected before reading has no content-derived ID.
        file_id = error.get("fileId") or "file_" + hashlib.sha256(
            f"{inventory_hash}:{index}".encode()).hexdigest()[:24]
        files.append(_skipped(file_id, error["fileName"], error["code"]))
    result = []
    for entry in inventory._files:
        if entry["fileId"] not in selected: continue
        if reviewed_xlsx and entry["fileId"] in reviewed_xlsx:
            package = reviewed_xlsx[entry["fileId"]]
            result.append(package)
            files.append(_imported(entry, package))
            continue
        path = inventory_file_path(inventory, entry["fileId"])
        try:
            payload, stamp = _bounded_bytes(path)
        except (OSError, ValueError) as exc:
            raise InputError("DP_SOURCE_STALE", "packages", "Reviewed source is unavailable") from exc
        if "sha256:" + hashlib.sha256(payload).hexdigest() != entry["sourceHash"]:
            raise InputError("DP_SOURCE_STALE", "packages", "Reviewed source content changed")
        decisions, reading_metadata = [], None
        package = {"kind": entry["kind"], "fileId": entry["fileId"], "sheets": [], "preflight": dict(PREFLIGHT)}
        frames = None
        if entry["kind"] == "xlsx":
            from .xlsx_preservation import normalize_workbook
            selected_sources = {s["sourceSheetId"]: s for s in inventory._sheets if s["fileId"] == entry["fileId"]}
            renamed = {selected_sources[m["sourceSheetId"]]["sourceName"]: m["proposedName"]
                       for m in mappings if m["fileId"] == entry["fileId"]}
            normalized = normalize_workbook(payload, renamed, runner=native_runner, workspace_manager=workspace_manager)
            frames = {s["name"]: {k: v for k, v in s.items() if k != "name"} for s in normalized["nativeEvidence"]}
            package["base64"] = normalized["base64"]
            package["namespace"] = normalized["namespace"]
            package["nativePreservation"] = {"packageFingerprint": normalized["packageFingerprint"]}
            package["preflight"].update({"definedNames": bool(normalized["namespace"]["names"]),
                                         "tables": bool(normalized["namespace"]["tables"]), "merges": normalized["merges"]})
        for mapping in mappings:
            if mapping["fileId"] != entry["fileId"]: continue
            source = next(s for s in inventory._sheets if s["sourceSheetId"] == mapping["sourceSheetId"])
            if frames is not None:
                frame = deepcopy(frames[mapping["proposedName"]])
            else:
                try:
                    frame, decisions, reading_metadata = _csv_frame(payload, entry["csvReading"], date_system)
                except InputError as exc:
                    if exc.code not in {"REQUEST_LIMIT", "CSV_COLUMN_COUNT"}:
                        raise
                    files.append(_skipped(entry["fileId"], entry["fileName"], exc.code))
                    continue
            package["sheets"].append({"sourceSheetId": source["sourceSheetId"], "sourceName": source["sourceName"],
                                      "targetName": mapping["proposedName"], **frame})
        try:
            _unchanged(inventory_file_path(inventory, entry["fileId"]), payload, stamp)
        except (OSError, ValueError) as exc:
            raise InputError("DP_SOURCE_STALE", "packages", "Reviewed source changed during transfer") from exc
        if package["sheets"]:
            result.append(package)
            files.append(_imported(entry, package, reading_metadata, decisions))
    verify_inventory(inventory)
    summary = {"files": files, "totals": {"files": len(result), "skipped": len(files) - len(result),
               "sheets": sum(len(p["sheets"]) for p in result), "decisions": sum(len(f["decisions"]) + len(f["readingDecisions"]) for f in files)}}
    transfer = {"packages": result, "importReport": summary}
    if len(json.dumps(transfer, ensure_ascii=False).encode()) > MAX_IMAGE_BYTES:
        raise InputError("REQUEST_LIMIT", "packages", "Reviewed package exceeds the bounded transfer envelope")
    if report is not None:
        report.update(summary)
    return result
