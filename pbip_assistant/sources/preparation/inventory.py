"""Bounded local folder inventory, separate from legacy CSV append behavior."""
from copy import deepcopy
import csv
from datetime import datetime, timezone
from heapq import nsmallest
from io import BytesIO
from pathlib import Path, PurePosixPath
import ntpath
import os
import re
import stat
import unicodedata
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile
from zlib import error as DeflateError
import hashlib

from pbip_assistant.errors import InputError
from pbip_assistant.sources import csv_source
from pbip_assistant.sources.assistant_ingest import (
    ALLOWED_EXTENSIONS, MAX_BYTES_PER_FILE, MAX_BYTES_PER_SESSION,
    _bounded_bytes, _guard, _unchanged, canonical_hash,
)
from pbip_assistant.sources.xlsx import MAIN, REL, MAX_UNCOMPRESSED, _column_index, _format_kind, _safe_member
from .csv_typing import describe_columns
from .model import SourceInventory


MAX_MEMBERS = 10000
MAX_SHEETS = 200
MAX_SELECTION_FILES = 200
MAX_BROWSE_ENTRIES = 500
MAX_CSV_COLUMNS = 200
MAX_CELLS = 400_000
_XLSX_READ_ERRORS = (BadZipFile, DeflateError, KeyError, ET.ParseError, RuntimeError)


class SelectedSourceInventory(SourceInventory):
    """Inventory whose stamps are bound to explicit root-relative paths."""

    def public(self):
        return {**super().public(), "folderName": _folder_name(self._root)}


def _error(code, detail):
    return InputError(code, "preparationSources", detail)


def _folder_name(path):
    return path.name or "Root"


def _relative_parts(path):
    parts = tuple(re.split(r"[/\\]", path)) if path else ()
    if any(not part or ":" in part or part in {".", ".."} or ntpath.isreserved(part) for part in parts):
        raise _error("DP_BROWSE_ESCAPE", "Path must stay inside the selected root")
    return parts


def _is_reparse(metadata):
    return (stat.S_ISLNK(metadata.st_mode)
            or bool(getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def _without_reparse(path):
    metadata = path.lstat()
    if _is_reparse(metadata):
        raise _error("DP_BROWSE_ESCAPE", "Symbolic links and reparse points are unsupported")
    return metadata


def _selected_root(root):
    try:
        path = Path(root)
        if not path.is_absolute() or ".." in path.parts:
            raise _error("DP_BROWSE_ESCAPE", "Choose an absolute source root")
        for part in reversed(path.parents):
            _without_reparse(part)
        if not stat.S_ISDIR(_without_reparse(path).st_mode):
            raise ValueError("Root is not a directory")
        return path.resolve(strict=True)
    except (OSError, TypeError, ValueError) as exc:
        raise _error("DP_SOURCE_STALE", "The selected source root is unavailable") from exc


def _selection_path(root, parts):
    path = root
    for part in parts:
        path = path / part
        metadata = _without_reparse(path)
    return path, metadata


def _checked_selection_path(root, parts, *, folder=False):
    path = _selection_path(root, parts)[0] if parts else root
    checked = _guard(path, root=root, folder=folder)
    if checked != path:
        raise _error("DP_BROWSE_ESCAPE", "Path must stay inside the selected root without following links")
    return checked


def _browse_entries(folder):
    with os.scandir(folder) as children:
        for child in children:
            if child.name.startswith(".") or ntpath.isreserved(child.name):
                continue
            try:
                metadata = child.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if (_is_reparse(metadata)
                    or getattr(metadata, "st_file_attributes", 0) & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM)):
                continue
            if stat.S_ISDIR(metadata.st_mode):
                yield {"name": child.name, "kind": "folder"}
            else:
                suffix = Path(child.name).suffix.lower()
                if stat.S_ISREG(metadata.st_mode) and suffix in ALLOWED_EXTENSIONS:
                    yield {"name": child.name, "kind": "file", "extension": suffix[1:],
                           "size": metadata.st_size,
                           "modified": datetime.fromtimestamp(metadata.st_mtime, timezone.utc).isoformat()}


def browse_folder(root: Path, relative_path: str) -> dict:
    boundary = _selected_root(root)
    parts = _relative_parts(relative_path)
    try:
        folder = _checked_selection_path(boundary, parts, folder=True)
        entries = nsmallest(MAX_BROWSE_ENTRIES + 1, _browse_entries(folder),
                            key=lambda item: (item["kind"] != "folder", item["name"].casefold(), item["name"]))
    except (OSError, ValueError) as exc:
        raise _error("DP_SOURCE_STALE", "The selected source folder is unavailable") from exc
    root_name = _folder_name(boundary)
    breadcrumb = [{"name": root_name, "relativePath": ""}]
    breadcrumb.extend({"name": name, "relativePath": "/".join(parts[:index])}
                      for index, name in enumerate(parts, start=1))
    return {"rootName": root_name, "relativePath": "/".join(parts), "breadcrumb": breadcrumb,
            "parentRelativePath": "/".join(parts[:-1]) if parts else None,
            "entries": entries[:MAX_BROWSE_ENTRIES], "truncated": len(entries) > MAX_BROWSE_ENTRIES}


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


def _xlsx_sheets(payload, *, summary_entry=None):
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
        sheet_parts = []
        for sheet in book.findall(f"{{{MAIN}}}sheets/{{{MAIN}}}sheet"):
            target = targets.get(sheet.attrib.get(f"{{{REL}}}id"), {})
            part = _safe_member("xl/workbook.xml", target.get("Target", ""), set(names), label="worksheet")
            name = sheet.attrib.get("name")
            if not name or target.get("TargetMode") == "External" or not part.startswith("xl/") or part not in names:
                raise _error("INVALID_XLSX", "Workbook sheet mapping is invalid")
            sheet_names.append(name)
            sheet_parts.append(part)
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
            if not name or len(name) > 255 or scope is not None and (
                    not re.fullmatch(r"[0-9]{1,10}", scope) or int(scope) >= len(sheet_names)):
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
        if summary_entry is not None:
            summary_entry["fileSummary"] = _xlsx_summary(archive, set(names), sheet_parts)
        return sheet_names, features, defined_names, table_names


def _xlsx_date_styles(archive, names):
    if "xl/styles.xml" not in names:
        return set()
    styles = _xml(archive.read("xl/styles.xml"))
    try:
        custom = {int(item.get("numFmtId", "0")): item.get("formatCode")
                  for item in styles.iterfind(f"{{{MAIN}}}numFmts/{{{MAIN}}}numFmt")}
        formats = (int(item.get("numFmtId", "0")) for item in styles.iterfind(f"{{{MAIN}}}cellXfs/{{{MAIN}}}xf"))
        return {index for index, fmt in enumerate(formats) if _format_kind(fmt, custom.get(fmt)) == "date"}
    except ValueError as exc:
        raise _error("INVALID_XLSX", "Workbook style metadata is invalid") from exc


def _xlsx_cell_kind(cell, date_styles):
    native_type = cell.get("t", "n")
    if native_type == "inlineStr":
        return "text" if cell.find(f"{{{MAIN}}}is") is not None else None
    if not cell.findtext(f"{{{MAIN}}}v"):
        return "text" if cell.find(f"{{{MAIN}}}f") is not None else None
    if native_type == "d":
        return "date"
    if native_type != "n":
        return "text"
    try:
        return "date" if int(cell.get("s", "0")) in date_styles else "number"
    except ValueError as exc:
        raise _error("INVALID_XLSX", "Workbook cell style is invalid") from exc


def _xlsx_summary(archive, names, sheet_parts):
    date_styles = _xlsx_date_styles(archive, names)
    kinds = {"number": 0, "date": 0, "text": 0}
    cells_seen = 0
    for part in sheet_parts:
        root = _xml(archive.read(part))
        first_row = None
        columns = {}
        for row in root.iterfind(f"{{{MAIN}}}sheetData/{{{MAIN}}}row"):
            column = -1
            row_kinds = {}
            for cell in row.iterfind(f"{{{MAIN}}}c"):
                cells_seen += 1
                if cells_seen > MAX_CELLS:
                    raise _error("REQUEST_LIMIT", "Workbook summary exceeds the bounded cell limit")
                ref = cell.get("r")
                try:
                    column = _column_index(ref) if ref else column + 1
                except ValueError as exc:
                    raise _error("INVALID_XLSX", "Workbook cell reference is invalid") from exc
                if not 0 <= column < 16_384:
                    raise _error("INVALID_XLSX", "Workbook cell reference is invalid")
                kind = _xlsx_cell_kind(cell, date_styles)
                if kind is not None:
                    row_kinds[column] = kind
            if not row_kinds:
                continue
            if first_row is None:
                first_row = row_kinds
                if set(first_row.values()) == {"text"}:
                    continue
            for column, kind in row_kinds.items():
                previous = columns.setdefault(column, kind)
                if previous != kind:
                    columns[column] = "text"
        if first_row is not None:
            for column in first_row:
                columns.setdefault(column, "text")
        for kind in columns.values():
            kinds[kind] += 1
    return {"columnCount": sum(kinds.values()), "kinds": kinds,
            "encoding": None, "delimiter": None, "headerRow": None}


def _members(folder):
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".csv", ".xlsx"}),
                  key=lambda p: (p.name.casefold(), p.name))


def _selected_csv_summary(path, payload, entry):
    encoding = csv_source._select_encoding(payload, None, path)
    try:
        source = payload.decode(encoding)
    except UnicodeDecodeError as initial_error:
        if encoding != "utf-8":
            raise _error("CSV_ENCODING", "CSV content does not match its encoding marker") from initial_error
        encoding = "cp1252"
        try:
            source = payload.decode(encoding)
        except UnicodeDecodeError as exc:
            raise _error("CSV_ENCODING", "CSV content is not in a supported encoding") from exc
    if "\0" in source:
        raise _error("CSV_ENCODING", "CSV content contains a NUL character")
    header_row = 1
    try:
        delimiter = csv_source._select_delimiter(source, None, header_row, path)
    except InputError as exc:
        if exc.code != "CSV_DELIMITER_NOT_FOUND":
            raise
        delimiter = ","
    reader = csv_source._reader(source, delimiter)
    try:
        headers = [cell.strip() for cell in next(reader, [])]
        if not headers or any(not header for header in headers):
            raise _error("CSV_HEADER", "The CSV header contains an empty column name")
        if len(headers) > MAX_CSV_COLUMNS or any(len(header) > csv_source.MAX_CELL_CHARS for header in headers):
            raise _error("CSV_LIMIT", "CSV header exceeds the supported column or cell length limit")
        if len({header.casefold() for header in headers}) != len(headers):
            raise _error("CSV_DUPLICATE_HEADER", "The CSV header contains duplicate column names")
        rows = []
        for row in reader:
            if len(row) != len(headers):
                raise _error("CSV_COLUMN_COUNT", "CSV row widths require correction")
            if len(rows) >= csv_source.MAX_ROWS or any(len(cell) > csv_source.MAX_CELL_CHARS for cell in row):
                raise _error("CSV_LIMIT", "CSV exceeds the supported row or cell length limit")
            if (len(rows) + 2) * len(headers) > MAX_CELLS:
                raise _error("REQUEST_LIMIT", "CSV exceeds the bounded import cell limit")
            rows.append(row)
    except csv.Error as exc:
        raise _error("INVALID_CSV", "CSV records could not be read") from exc
    entry["csvReading"] = {"encoding": encoding, "delimiter": delimiter, "header_row": header_row}
    entry["fileSummary"] = {**describe_columns(headers, rows), "encoding": encoding,
                            "delimiter": delimiter, "headerRow": header_row}


def _source_sheets(path, payload, entry, options, *, summarize=False):
    if entry["kind"] == "xlsx":
        summary_entry = entry if summarize else None
        source_names, entry["features"], entry["definedNames"], entry["tableNames"] = _xlsx_sheets(
            payload, summary_entry=summary_entry)
        return source_names
    if summarize:
        _selected_csv_summary(path, payload, entry)
        return [None]
    if not isinstance(options, dict) or set(options) - {"encoding", "delimiter", "header_row"}:
        raise _error("INVALID_REQUEST", "Unsupported CSV reading options")
    profile = csv_source.profile_csv(path, **options)
    if profile["source_sha256"] != entry["sourceHash"].removeprefix("sha256:"):
        raise _error("DP_SOURCE_STALE", "Source changed during inventory")
    if not profile["mapping_ready"]:
        raise _error("CSV_COLUMN_COUNT", "CSV row widths require correction")
    entry["csvReading"] = {key: profile[key] for key in ("encoding", "delimiter", "header_row")}
    return [None]


def _sheet_mappings(member, file_id, source_names, used):
    for source_name in source_names:
        sheet_id = "sheet_" + hashlib.sha256((file_id + "\0" + str(source_name)).encode()).hexdigest()[:24]
        proposed = member.stem if source_name is None else member.stem + "_" + source_name
        yield {"fileId": file_id, "sourceSheetId": sheet_id, "sourceName": source_name,
               "proposedName": safe_sheet_name(proposed, used)}


def _selection_keys(items):
    if not isinstance(items, list) or not 0 < len(items) <= MAX_SELECTION_FILES:
        raise _error("REQUEST_LIMIT", "Select between 1 and 200 CSV/XLSX files")
    paths, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"relativePath", "fileName"} or any(
                not isinstance(value, str) for value in item.values()):
            raise _error("INVALID_REQUEST", "Invalid source selection")
        name = item["fileName"]
        if _relative_parts(name) != (name,):
            raise _error("DP_BROWSE_ESCAPE", "Choose a file name inside the selected folder")
        parts = (*_relative_parts(item["relativePath"]), name)
        key = os.path.normcase("/".join(parts))
        if key in seen:
            raise _error("INVALID_REQUEST", "The same file was selected more than once")
        seen.add(key)
        paths.append(parts)
    return paths


def _selection_candidates(boundary, paths, errors):
    candidates = []
    total_size = 0
    for parts in paths:
        name = parts[-1]
        try:
            member, metadata = _selection_path(boundary, parts)
            if not stat.S_ISREG(metadata.st_mode) or member.suffix.lower() not in ALLOWED_EXTENSIONS:
                errors.append({"fileName": name, "code": "DP_UNSUPPORTED_SOURCE"})
                continue
        except OSError:
            errors.append({"fileName": name, "code": "DP_SOURCE_STALE"})
            continue
        total_size += metadata.st_size
        if metadata.st_size > MAX_BYTES_PER_FILE:
            errors.append({"fileName": name, "code": "REQUEST_LIMIT"})
            continue
        candidates.append(parts)
    if total_size > MAX_BYTES_PER_SESSION:
        raise _error("REQUEST_LIMIT", "Source selection exceeds its existing session byte limit")
    return candidates


def inventory_selection(root: Path, items: list[dict]) -> SourceInventory:
    boundary = _selected_root(root)
    paths = _selection_keys(items)
    files, sheets, errors, stamps, used = [], [], [], [], set()
    total = 0
    for parts in _selection_candidates(boundary, paths, errors):
        name = parts[-1]
        try:
            checked = _checked_selection_path(boundary, parts)
            payload, stamp = _bounded_bytes(checked)
        except (OSError, ValueError):
            errors.append({"fileName": name, "code": "DP_SOURCE_STALE"})
            continue
        total += len(payload)
        if total > MAX_BYTES_PER_SESSION:
            raise _error("REQUEST_LIMIT", "Actual selection exceeds the session byte limit")
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        relative = "/".join(parts)
        file_id = "file_" + hashlib.sha256((relative + "\0" + digest).encode()).hexdigest()[:24]
        entry = {"fileId": file_id, "fileName": name, "kind": checked.suffix.lower()[1:],
                 "byteLength": len(payload), "sourceHash": digest, "features": []}
        files.append(entry)
        stamps.append((relative, stamp, digest))
        try:
            source_names = _source_sheets(checked, payload, entry, {}, summarize=True)
            sheets.extend(_sheet_mappings(checked, file_id, source_names, used))
        except (InputError, OSError, *_XLSX_READ_ERRORS) as exc:
            if isinstance(exc, InputError) and exc.code in {"DP_SOURCE_STALE", "SOURCE_CHANGED"}:
                raise _error("DP_SOURCE_STALE", "Source changed during inventory") from exc
            if isinstance(exc, InputError):
                code = exc.code
            else:
                code = "DP_SOURCE_STALE" if isinstance(exc, OSError) else "INVALID_XLSX"
            errors.append({"fileId": file_id, "fileName": name, "code": code})
        try:
            current = _checked_selection_path(boundary, parts)
            _unchanged(current, payload, stamp)
        except (InputError, OSError, ValueError) as exc:
            raise _error("DP_SOURCE_STALE", "Source changed during inventory") from exc
    if len(sheets) > MAX_SHEETS:
        raise _error("REQUEST_LIMIT", "Source selection exceeds 200 worksheet mappings")
    inventory_hash = canonical_hash({"files": files, "sheets": sheets, "errors": errors, "selection": paths})
    return SelectedSourceInventory(inventory_hash, boundary, boundary, tuple(files), tuple(sheets),
                                   tuple(errors), tuple(stamps), total)


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
                source_names = _source_sheets(checked, payload, entry, (csv_options or {}).get(member.name, {}))
                sheets.extend(_sheet_mappings(member, file_id, source_names, used))
            except (InputError, *_XLSX_READ_ERRORS) as exc:
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
        selected = isinstance(inventory, SelectedSourceInventory)
        if selected:
            _selected_root(inventory._root)
        elif [p.name for p in _members(inventory._folder)] != [s[0] for s in inventory._stamps]:
            raise ValueError("Selection changed")
        for name, stamp, expected in inventory._stamps:
            path = _inventory_stamp_path(inventory, name)
            data, current = _bounded_bytes(path)
            if stamp != current or "sha256:" + hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("Source changed")
    except (InputError, OSError, ValueError) as exc:
        raise _error("DP_SOURCE_STALE", "Source selection changed; review it again") from exc


def _inventory_stamp_path(inventory, name):
    if isinstance(inventory, SelectedSourceInventory):
        return _checked_selection_path(inventory._root, tuple(name.split("/")))
    return _guard(inventory._folder / name, root=inventory._root)


def inventory_file_path(inventory, file_id):
    """Resolve a reviewed file ID without using its public display name as a locator."""
    for entry, (name, _, _) in zip(inventory._files, inventory._stamps, strict=True):
        if entry["fileId"] == file_id:
            try:
                if isinstance(inventory, SelectedSourceInventory):
                    _selected_root(inventory._root)
                return _inventory_stamp_path(inventory, name)
            except (InputError, OSError, ValueError) as exc:
                raise _error("DP_SOURCE_STALE", "Source selection changed; review it again") from exc
    raise _error("DP_REVIEW_STALE", "Source file is no longer in the reviewed inventory")


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
