"""Bounded local folder inventory, separate from legacy CSV append behavior."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
import unicodedata
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile
import hashlib

from pbip_assistant.errors import InputError
from pbip_assistant.sources import csv_source
from pbip_assistant.sources.assistant_ingest import (
    MAX_BYTES_PER_SESSION, _bounded_bytes, _guard, _unchanged, canonical_hash,
)
from pbip_assistant.sources.xlsx import MAIN, REL, MAX_UNCOMPRESSED, _safe_member
from .model import SourceInventory


MAX_MEMBERS = 10000
MAX_SHEETS = 200


def _error(code, detail):
    return InputError(code, "preparationSources", detail)


def safe_sheet_name(name, used):
    cleaned = re.sub(r"[\x00-\x1f\[\]:*?/\\]", "_", unicodedata.normalize("NFC", str(name)))
    cleaned = cleaned.strip().strip("'") or "Sheet"
    if cleaned.casefold() == "history":
        cleaned += "_1"
    def clipped(value, units=31):
        return value.encode("utf-16-le")[:units * 2].decode("utf-16-le", errors="ignore")
    occupied = {unicodedata.normalize("NFC", value).casefold() for value in used}
    candidate, suffix = clipped(cleaned), 1
    while candidate.casefold() in occupied:
        suffix += 1
        ending = "_" + str(suffix)
        candidate = clipped(cleaned, 31 - len(ending)) + ending
    used.add(candidate.casefold())
    return candidate


def _xml(payload):
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise _error("INVALID_XLSX", "XML entities are unsupported")
    return ET.fromstring(payload)


def _xlsx_sheets(payload):
    with ZipFile(BytesIO(payload)) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if (len(members) > MAX_MEMBERS or sum(member.file_size for member in members) > MAX_UNCOMPRESSED):
            raise _error("XLSX_LIMIT", "Workbook package exceeds the bounded import limit")
        if (len(set(names)) != len(names) or any(member.flag_bits & 1 for member in members)
                or any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names)):
            raise _error("INVALID_XLSX", "Workbook package contains unsupported members")
        book = _xml(archive.read("xl/workbook.xml"))
        relations = _xml(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {relation.attrib.get("Id"): relation.attrib for relation in relations}
        sheet_names = []
        for sheet in book.findall(f"{{{MAIN}}}sheets/{{{MAIN}}}sheet"):
            target = targets.get(sheet.attrib.get(f"{{{REL}}}id"), {})
            part = _safe_member("xl/workbook.xml", target.get("Target", ""), set(names), label="worksheet")
            name = sheet.attrib.get("name")
            if not name or target.get("TargetMode") == "External" or not part.startswith("xl/") or part not in names:
                raise _error("INVALID_XLSX", "Workbook sheet mapping is invalid")
            sheet_names.append(name)
        if not sheet_names or len(sheet_names) > MAX_SHEETS or len({s.casefold() for s in sheet_names}) != len(sheet_names):
            raise _error("INVALID_XLSX", "Workbook sheet inventory is invalid or exceeds its limit")
        features = []
        for prefix, feature in (("xl/tables/", "tables"), ("xl/externalLinks/", "external_links"),
                                ("xl/pivotTables/", "pivot_tables"), ("xl/charts/", "charts")):
            if any(name.startswith(prefix) for name in names):
                features.append(feature)
        if book.find(f"{{{MAIN}}}workbookProtection") is not None:
            features.append("protected_structure")
        defined_names = []
        for item in book.findall(f"{{{MAIN}}}definedNames/{{{MAIN}}}definedName"):
            name, scope = item.attrib.get("name", ""), item.attrib.get("localSheetId")
            if not name or len(name) > 255 or scope is not None and (not scope.isdigit() or int(scope) >= len(sheet_names)):
                raise _error("INVALID_XLSX", "Workbook name metadata is invalid")
            defined_names.append({"name": name, "scope": sheet_names[int(scope)] if scope is not None else "workbook"})
        table_names = []
        for part in names:
            if part.startswith("xl/tables/") and part.endswith(".xml") and "/_rels/" not in part:
                table = _xml(archive.read(part))
                name = table.attrib.get("displayName", "")
                if not name or len(name) > 255:
                    raise _error("INVALID_XLSX", "Workbook table metadata is invalid")
                table_names.append(name)
        if len(defined_names) > 2000 or len(table_names) > 2000:
            raise _error("XLSX_LIMIT", "Workbook name inventory exceeds its bounded limit")
        if defined_names:
            features.append("defined_names")
        return sheet_names, features, defined_names, table_names


def _members(folder):
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".csv", ".xlsx"}),
                  key=lambda p: (p.name.casefold(), p.name))


def inventory_folder(root: Path, relative_path: str, *, csv_options=None) -> SourceInventory:
    try:
        boundary = Path(root).resolve(strict=True)
        relative = Path(relative_path)
        if not boundary.is_dir() or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid relative source selection")
        folder = _guard(boundary / relative, root=boundary, folder=True)
        members = _members(folder)
        if not members or len(members) > MAX_SHEETS:
            raise _error("REQUEST_LIMIT", "Select between 1 and 200 immediate CSV/XLSX files")
        if sum(p.stat().st_size for p in members) > MAX_BYTES_PER_SESSION:
            raise _error("REQUEST_LIMIT", "Source selection exceeds its existing session byte limit")
        files, sheets, errors, stamps, total, used = [], [], [], [], 0, set()
        for member in members:
            checked = _guard(member, root=boundary)
            payload, stamp = _bounded_bytes(checked)
            total += len(payload)
            if total > MAX_BYTES_PER_SESSION:
                raise _error("REQUEST_LIMIT", "Actual selection exceeds the session byte limit")
            digest = "sha256:" + hashlib.sha256(payload).hexdigest()
            file_id = "file_" + hashlib.sha256((member.name + digest).encode()).hexdigest()[:24]
            kind = checked.suffix.lower()[1:]
            entry = {"fileId": file_id, "fileName": member.name, "kind": kind,
                     "byteLength": len(payload), "sourceHash": digest, "features": []}
            files.append(entry)
            stamps.append((member.name, stamp, digest))
            try:
                if kind == "csv":
                    options = (csv_options or {}).get(member.name, {})
                    if not isinstance(options, dict) or set(options) - {"encoding", "delimiter", "header_row"}:
                        raise _error("INVALID_REQUEST", "Unsupported CSV reading options")
                    profile = csv_source.profile_csv(checked, **options)
                    if not profile["mapping_ready"]:
                        raise _error("CSV_COLUMN_COUNT", "CSV row widths require correction")
                    source_names = [None]
                    entry["csvReading"] = {key: profile[key] for key in ("encoding", "delimiter", "header_row")}
                else:
                    source_names, entry["features"], entry["definedNames"], entry["tableNames"] = _xlsx_sheets(payload)
                for source_name in source_names:
                    sheet_id = "sheet_" + hashlib.sha256((file_id + "\0" + str(source_name)).encode()).hexdigest()[:24]
                    proposed = member.stem if source_name is None else member.stem + "_" + source_name
                    sheets.append({"fileId": file_id, "sourceSheetId": sheet_id, "sourceName": source_name,
                                   "proposedName": safe_sheet_name(proposed, used)})
            except (InputError, BadZipFile, KeyError, ET.ParseError, RuntimeError) as exc:
                errors.append({"fileId": file_id, "fileName": member.name,
                               "code": exc.code if isinstance(exc, InputError) else "INVALID_XLSX"})
            _unchanged(checked, payload, stamp)
        if len(sheets) > MAX_SHEETS:
            raise _error("REQUEST_LIMIT", "Source selection exceeds 200 worksheet mappings")
        if [p.name for p in _members(folder)] != [p.name for p in members]:
            raise _error("DP_SOURCE_STALE", "Folder contents changed during inventory")
        inventory_hash = canonical_hash({"files": files, "sheets": sheets, "errors": errors})
        return SourceInventory(inventory_hash, boundary, folder, tuple(files), tuple(sheets), tuple(errors), tuple(stamps), total)
    except InputError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise _error("DP_SOURCE_STALE", "Source selection is unavailable or outside the chosen root") from exc


def propose_sheet_names(inventory: SourceInventory, existing_names):
    used = set(existing_names)
    result = []
    for sheet in inventory.public()["sheets"]:
        result.append({"fileId": sheet["fileId"], "sourceSheetId": sheet["sourceSheetId"],
                       "proposedName": safe_sheet_name(sheet["proposedName"], used)})
    return result


def verify_inventory(inventory):
    try:
        if [p.name for p in _members(inventory._folder)] != [s[0] for s in inventory._stamps]:
            raise ValueError("Selection changed")
        for name, stamp, expected in inventory._stamps:
            path = _guard(inventory._folder / name, root=inventory._root)
            data, current = _bounded_bytes(path)
            if stamp != current or "sha256:" + hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("Source changed")
    except (OSError, ValueError) as exc:
        raise _error("DP_SOURCE_STALE", "Source selection changed; review it again") from exc


def review_import(inventory, inventory_hash, mappings, existing_names):
    verify_inventory(inventory)
    if inventory.inventory_hash != inventory_hash or not isinstance(mappings, list) or not 0 < len(mappings) <= MAX_SHEETS:
        raise _error("DP_REVIEW_STALE", "Reviewed source selection is stale or invalid")
    allowed = {(s["fileId"], s["sourceSheetId"]) for s in inventory._sheets}
    chosen, used = set(), {unicodedata.normalize("NFC", n).casefold() for n in existing_names}
    for mapping in mappings:
        if not isinstance(mapping, dict) or set(mapping) != {"fileId", "sourceSheetId", "proposedName"}:
            raise _error("INVALID_REQUEST", "Invalid source sheet mapping")
        key = mapping["fileId"], mapping["sourceSheetId"]
        name = mapping["proposedName"]
        if key not in allowed or key in chosen or not isinstance(name, str) or safe_sheet_name(name, set()) != name or name.casefold() in used:
            raise _error("INVALID_REQUEST", "Source mapping is unknown or destination name collides")
        chosen.add(key)
        used.add(name.casefold())
    selected_files = {key[0] for key in chosen}
    if any(key not in chosen for key in allowed if key[0] in selected_files):
        raise _error("INVALID_REQUEST", "Each selected XLSX must import its complete sheet group")
    return {"reviewHash": canonical_hash({"inventoryHash": inventory_hash, "mappings": mappings,
                                          "existingNames": sorted(used)}),
            "mappings": deepcopy(mappings), "fileCount": len(selected_files), "sheetCount": len(mappings)}
