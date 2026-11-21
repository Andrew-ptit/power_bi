"""Read-only adapters for the Assistant WL1 ingestion contract."""

from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path
from typing import Any

from pbip_assistant.errors import InputError
from pbip_assistant.sources import csv_source, xlsx


MAX_BYTES_PER_FILE = 64 * 1024 * 1024
MAX_BYTES_PER_SESSION = 128 * 1024 * 1024
MAX_PREVIEW_ROWS = 20
ALLOWED_EXTENSIONS = frozenset({".csv", ".xlsx"})
_STAMP = "2026-10-26T09:00:00Z"


def canonical_hash(value: object) -> str:
    """Hash canonical JSON using the shared Assistant recipe."""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _empty() -> dict:
    return {"sources": [], "tables": [], "csvOptions": [], "errors": [],
            "warnings": [], "sessionBytes": 0, "requiresRename": []}


def _label(path: object) -> str:
    """Diagnostics expose only an inert filename, never a private local path."""
    try:
        return Path(path).name if isinstance(path, (str, Path)) else "source"
    except (TypeError, ValueError):
        return "source"


def _fail(result: dict, path: object, detail: str) -> dict:
    result["errors"].append({"code": "AF_INGEST_FAILED", "severity": "blocker",
                             "path": _label(path), "detail": detail})
    return result


def _guard(path: str | Path, *, root: Path | None = None, folder: bool = False) -> Path:
    requested = Path(path)
    if ".." in requested.parts:
        raise ValueError("Path traversal is not permitted")
    boundary = root.resolve(strict=True) if root is not None else (
        requested.parent.resolve(strict=True) if requested.is_absolute() else Path.cwd().resolve())
    resolved = requested.resolve(strict=True)
    if not resolved.is_relative_to(boundary):
        raise ValueError("Source is outside the selected root")
    if folder:
        if not resolved.is_dir():
            raise ValueError("Source must be a folder")
    else:
        if not resolved.is_file() or resolved.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError("Only regular CSV/XLSX sources are supported")
        if resolved.stat().st_size > MAX_BYTES_PER_FILE:
            raise ValueError("Source exceeds the per-file byte limit")
    return resolved


def _origin(path: Path) -> str:
    return path.name


def _source(path: Path, kind: str, *, display_name: str | None = None,
            payload: bytes | None = None) -> dict:
    name = display_name if display_name is not None else path.name
    origin = _origin(path)
    return {"id": "src_" + hashlib.sha256((name + origin).encode("utf-8")).hexdigest()[:12],
            "name": name, "type": kind, "origin": origin,
            "hash": canonical_hash((payload or b"").hex()), "addedAt": _STAMP}


def _bounded_bytes(path: Path) -> tuple[bytes, tuple[int, int]]:
    before = path.stat()
    with path.open("rb") as handle:
        payload = handle.read(MAX_BYTES_PER_FILE + 1)
    if len(payload) > MAX_BYTES_PER_FILE:
        raise ValueError("Source exceeds the per-file byte limit")
    return payload, (before.st_size, before.st_mtime_ns)


def _unchanged(path: Path, payload: bytes, stamp: tuple[int, int]) -> None:
    after, current_stamp = _bounded_bytes(path)
    if current_stamp != stamp or after != payload:
        raise ValueError("Source changed during ingestion; retry with a stable source")


def _raw_table(source: dict, name: str, header: list[str], rows: list[list[str]],
               *, kind: str = "file", sheet: str | None = None,
               cell_range: str | None = None, file_count: int = 1) -> dict:
    return {"sourceId": source["id"], "name": name,
            "locator": {"kind": kind, "sheet": sheet, "range": cell_range,
                        "path": source["origin"], "fileCount": file_count},
            "header": header, "rows": rows}


def add_csv(path, *, name=None, encoding=None, delimiter=None, header_row=1) -> dict:
    """Adapt the existing CSV validator and reader without changing raw values."""
    result = _empty()
    try:
        source_path = _guard(path)
        if source_path.suffix.lower() != ".csv":
            raise ValueError("CSV connector requires a .csv source")
        payload, stamp = _bounded_bytes(source_path)
        source = _source(source_path, "csv", payload=payload)
        selected_encoding = csv_source._select_encoding(payload, encoding, source_path)
        text = payload.decode(selected_encoding, errors="strict")
        try:
            profile = csv_source.profile_csv(source_path, encoding=encoding, delimiter=delimiter,
                                             header_row=header_row)
        except InputError as exc:
            if exc.code != "CSV_AMBIGUOUS_DELIMITER" or delimiter is not None:
                raise
            candidates = [{"encoding": selected_encoding, "delimiter": candidate}
                          for candidate in csv_source.DELIMITER_CANDIDATES
                          if (shape := csv_source._delimiter_shape(text, candidate, header_row))
                          is not None and shape[0] > 1 and shape[1]]
            result["csvOptions"].append({"sourceId": source["id"], "encoding": selected_encoding,
                                         "delimiter": None, "headerRow": header_row,
                                         "needsClarification": True, "candidates": candidates})
            result["warnings"].append({"code": "AF_MISSING_DATA", "severity": "warning",
                                        "path": source_path.name,
                                        "detail": "CSV has multiple plausible delimiters; choose one before ingestion"})
            _unchanged(source_path, payload, stamp)
            return result
        if not profile["mapping_ready"]:
            raise ValueError("CSV contains inconsistent row widths; no rows were admitted")
        parsed = list(csv_source._reader(text, profile["delimiter"]))
        header = parsed[header_row - 1]
        rows = parsed[header_row:]
        _unchanged(source_path, payload, stamp)
        result["sources"].append(source)
        result["tables"].append(_raw_table(source, str(name) if name is not None else source_path.stem,
                                            header, rows))
        result["csvOptions"].append({"sourceId": source["id"], "encoding": profile["encoding"],
                                     "delimiter": profile["delimiter"], "headerRow": header_row,
                                     "needsClarification": False,
                                     "candidates": [{"encoding": profile["encoding"],
                                                     "delimiter": profile["delimiter"]}]})
        result["sessionBytes"] = len(payload)
    except (InputError, OSError, ValueError, TypeError, IndexError) as exc:
        # Reader exceptions can contain cells or private paths. Return only a
        # stable category; callers still receive a deterministic blocker.
        result = _fail(_empty(), path, "CSV ingestion failed: " + getattr(exc, "code", "INVALID_SOURCE"))
    return result


def add_excel(path, *, name=None, sheet=None, table=None) -> dict:
    """Adapt the existing read-only workbook reader for one selected sheet/table."""
    result = _empty()
    try:
        source_path = _guard(path)
        if source_path.suffix.lower() != ".xlsx":
            raise ValueError("Excel connector requires a .xlsx source")
        payload, stamp = _bounded_bytes(source_path)
        profile = xlsx.profile_workbook(source_path, sheet_names=[sheet] if sheet is not None else None,
                                        table_name=table, include_preview=True, preview_limit=None)
        sheets = profile["sheets"]
        if len(sheets) != 1:
            raise ValueError("Select exactly one worksheet or table")
        selected = sheets[0]
        if not selected["mapping_ready"]:
            raise ValueError("Workbook selection has an invalid header or row width")
        preview = selected["preview"]
        source = _source(source_path, "xlsx", payload=payload)
        rows = [["" if cell is None else str(cell) for cell in row] for row in preview["rows"]]
        selected_table = selected["tables"][0] if table is not None else None
        selected_name = str(name) if name is not None else (selected_table["name"] if selected_table else selected["name"])
        _unchanged(source_path, payload, stamp)
        result["sources"].append(source)
        result["tables"].append(_raw_table(source, selected_name, preview["columns"], rows,
                                            kind="table" if table is not None else "sheet",
                                            sheet=selected["name"],
                                            cell_range=selected_table["ref"] if selected_table else None))
        if selected["formula_cache"]["missing_cached_count"]:
            result["warnings"].append({"code": "AF_MISSING_DATA", "severity": "warning",
                                        "path": source_path.name,
                                        "detail": "Some formulas lack cached values; no calculation was performed"})
        result["sessionBytes"] = len(payload)
    except (InputError, OSError, ValueError, TypeError, KeyError) as exc:
        result = _fail(_empty(), path, "Excel ingestion failed: " + getattr(exc, "code", "INVALID_SOURCE"))
    return result


def _folder_files(path: Path, pattern: str) -> list[Path]:
    if not isinstance(pattern, str) or not pattern or any(part in pattern for part in ("/", "\\", "..")):
        raise ValueError("Folder pattern must select immediate files only")
    files = sorted(path.glob(pattern), key=lambda item: item.name)
    if not files:
        raise ValueError("Folder selection contains no matching CSV files")
    checked = [_guard(item, root=path) for item in files]
    if any(item.suffix.lower() != ".csv" for item in checked):
        raise ValueError("Folder connector accepts CSV files only")
    return checked


def add_folder(path, *, name=None, pattern="*.csv") -> dict:
    """Append matching CSV files in filename order, with one exact header."""
    result = _empty()
    try:
        folder = _guard(path, folder=True)
        files = _folder_files(folder, pattern)
        if sum(item.stat().st_size for item in files) > MAX_BYTES_PER_SESSION:
            raise ValueError("Folder exceeds the session byte limit")
        combined_header, combined_rows, member_hashes = None, [], []
        all_options, member_stamps = [], []
        for member in files:
            before = member.stat()
            member_stamps.append((before.st_size, before.st_mtime_ns))
            part = add_csv(member)
            if part["errors"] or not part["tables"]:
                return _fail(_empty(), path, "Folder member requires correction or an explicit CSV reading")
            raw = part["tables"][0]
            if combined_header is None:
                combined_header = raw["header"]
            elif raw["header"] != combined_header:
                raise ValueError("Folder member headers differ")
            combined_rows.extend(raw["rows"])
            member_hashes.append({"name": member.name, "hash": part["sources"][0]["hash"]})
            all_options.extend(part["csvOptions"])
            result["sessionBytes"] += part["sessionBytes"]
            if result["sessionBytes"] > MAX_BYTES_PER_SESSION:
                raise ValueError("Actual folder payload exceeds the session byte limit")
        if [p.name for p in _folder_files(folder, pattern)] != [p.name for p in files]:
            raise ValueError("Folder selection changed during ingestion")
        for member, expected, expected_stamp in zip(files, member_hashes, member_stamps, strict=True):
            current, current_stamp = _bounded_bytes(member)
            if current_stamp != expected_stamp or canonical_hash(current.hex()) != expected["hash"]:
                raise ValueError("Folder member changed during ingestion")
        display_name = str(name) if name is not None else folder.name
        source = _source(folder, "folder", display_name=display_name)
        source["hash"] = canonical_hash(member_hashes)
        result["sources"].append(source)
        result["tables"].append(_raw_table(source, display_name, combined_header or [], combined_rows,
                                            kind="folder", file_count=len(files)))
        result["csvOptions"] = [{**option, "sourceId": source["id"]} for option in all_options]
    except (OSError, ValueError, TypeError) as exc:
        result = _fail(_empty(), path, "Folder ingestion failed: " + getattr(exc, "code", "INVALID_SOURCE"))
    return result


def add_open_workbook(payload) -> dict:
    """Accept a submitted local values selection, without invoking Office or AI."""
    result = _empty()
    try:
        if not isinstance(payload, dict):
            raise ValueError("Workbook selection must be an object")
        header, rows = payload.get("header"), payload.get("rows")
        if header is None and isinstance(payload.get("values"), list) and payload["values"]:
            header, rows = payload["values"][0], payload["values"][1:]
        if not isinstance(header, list) or not header or not all(isinstance(v, str) and v for v in header):
            raise ValueError("Workbook selection requires a nonempty string header")
        if len(set(header)) != len(header) or len(header) > csv_source.MAX_COLUMNS:
            raise ValueError("Workbook selection header is invalid")
        if not isinstance(rows, list) or len(rows) > csv_source.MAX_ROWS:
            raise ValueError("Workbook selection rows are invalid")
        if (payload.get("sampleOnly") is True or payload.get("totalRows", len(rows)) != len(rows)
                or payload.get("totalColumns", len(header)) != len(header)):
            raise ValueError("A bounded sample cannot stand in for the complete selection")
        raw_rows = []
        for row in rows:
            if not isinstance(row, list) or len(row) != len(header):
                raise ValueError("Workbook selection row widths differ")
            if any(cell is not None and not isinstance(cell, (str, int, float, bool)) for cell in row):
                raise ValueError("Workbook selection contains unsupported values")
            # Canonical JSON rejects nonfinite numeric payloads without evaluating text.
            canonical_hash(row)
            raw_rows.append(["" if cell is None else str(cell) for cell in row])
        if any(len(cell) > csv_source.MAX_CELL_CHARS for row in [header, *raw_rows] for cell in row):
            raise ValueError("Workbook selection contains an oversized cell")
        name = str(payload.get("name", "Workbook"))
        origin = str(payload.get("origin", name))
        if Path(origin).is_absolute() or ".." in Path(origin).parts:
            raise ValueError("Workbook selection origin must be a public relative locator")
        source = {"id": "src_" + hashlib.sha256((name + origin).encode("utf-8")).hexdigest()[:12],
                  "name": name, "type": "workbook", "origin": origin,
                  "hash": canonical_hash({"header": header, "rows": raw_rows}), "addedAt": _STAMP}
        encoded = json.dumps({"header": header, "rows": raw_rows}, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_BYTES_PER_FILE:
            raise ValueError("Workbook selection exceeds the per-file byte limit")
        result["sources"].append(source)
        result["tables"].append(_raw_table(source, name, list(header), raw_rows,
                                            kind="table" if payload.get("table") else "range",
                                            sheet=payload.get("sheet"), cell_range=payload.get("range"), file_count=0))
        result["sessionBytes"] = len(encoded)
    except (ValueError, TypeError, OverflowError) as exc:
        result = _fail(_empty(), "workbook", "Workbook values selection is invalid or exceeds a bound")
    return result


def _rename_entries(tables: list[dict]) -> list[dict]:
    names: dict[str, list[str]] = {}
    for table in tables:
        names.setdefault(table["name"], []).append(table["sourceId"])
    return [{"tableName": name, "sources": ids} for name, ids in sorted(names.items()) if len(ids) > 1]


def resolve(session, requests) -> dict:
    """Resolve an explicit selection into an in-memory, bounded session.

    A caller may bind ``session['root']`` to the selected filesystem root.
    No directory or temporary copy is created. Session state is confined to
    ``_assistant_ingest``; other caller-owned keys are retained.
    """
    if not isinstance(session, dict):
        return _fail(_empty(), "session", "Session must be a mutable dictionary")
    if session.get("_assistant_ingest_closed"):
        return _fail(_empty(), "session", "Session has been closed")
    result = copy.deepcopy(session.get("_assistant_ingest", _empty()))
    if not isinstance(requests, (list, tuple)):
        return _fail(result, "requests", "Requests must be a list")
    for request in requests:
        try:
            if not isinstance(request, dict):
                raise ValueError("Request must be an object")
            kind, options = request.get("kind"), request.get("options", {})
            if not isinstance(options, dict):
                raise ValueError("Request options must be an object")
            if kind == "workbook":
                part = add_open_workbook(request.get("payload"))
                if request.get("name") is not None and part["tables"]:
                    part["tables"][0]["name"] = str(request["name"])
            else:
                path = Path(request.get("path", ""))
                root = Path(session["root"]) if session.get("root") is not None else None
                if root is not None and not path.is_absolute():
                    path = root / path
                checked = _guard(path, root=root, folder=kind == "folder")
                if kind == "folder":
                    estimate = sum(p.stat().st_size for p in _folder_files(checked, options.get("pattern", "*.csv")))
                else:
                    estimate = checked.stat().st_size
                if result["sessionBytes"] + estimate > MAX_BYTES_PER_SESSION:
                    raise ValueError("Session byte limit exceeded before reading source")
                handlers = {"csv": add_csv, "xlsx": add_excel, "folder": add_folder}
                if kind not in handlers:
                    raise ValueError("Unsupported connector kind")
                part = handlers[kind](checked, name=request.get("name"), **options)
                if root is not None:
                    origin = checked.relative_to(root.resolve(strict=True)).as_posix()
                    for source in part["sources"]:
                        previous_id = source["id"]
                        source["origin"] = origin
                        source["id"] = "src_" + hashlib.sha256((source["name"] + origin).encode("utf-8")).hexdigest()[:12]
                        for raw_table in part["tables"]:
                            if raw_table["sourceId"] == previous_id:
                                raw_table["sourceId"] = source["id"]
                                raw_table["locator"]["path"] = origin
                        for reading in part["csvOptions"]:
                            if reading["sourceId"] == previous_id:
                                reading["sourceId"] = source["id"]
                    if kind == "csv" and not part["sources"]:
                        pending_id = "src_" + hashlib.sha256((checked.name + origin).encode("utf-8")).hexdigest()[:12]
                        for reading in part["csvOptions"]:
                            reading["sourceId"] = pending_id
            if result["sessionBytes"] + part["sessionBytes"] > MAX_BYTES_PER_SESSION:
                raise ValueError("Session byte limit exceeded")
            if part["csvOptions"]:
                # Pending profiles have no admitted table. Resolving a reading
                # replaces only its pending metadata, never an accepted table.
                updated_ids = {option["sourceId"] for option in part["csvOptions"]}
                result["csvOptions"] = [option for option in result["csvOptions"]
                                        if not (option["sourceId"] in updated_ids and option["needsClarification"])]
                if not any(option["needsClarification"] for option in part["csvOptions"]):
                    selected_labels = {source["name"] for source in part["sources"]}
                    result["warnings"] = [warning for warning in result["warnings"]
                        if not (warning["path"] in selected_labels and
                                warning["detail"].startswith("CSV has multiple plausible delimiters"))]
            for key in ("sources", "tables", "csvOptions", "errors", "warnings"):
                result[key].extend(part[key])
            result["sessionBytes"] += part["sessionBytes"]
        except (OSError, ValueError, TypeError) as exc:
            _fail(result, request.get("path", "request") if isinstance(request, dict) else "request",
                  "Source selection is outside the root, unsupported, invalid, or exceeds a byte limit")
    result["sources"].sort(key=lambda item: (item["name"], item["id"]))
    result["tables"].sort(key=lambda item: (item["name"], item["sourceId"]))
    result["requiresRename"] = _rename_entries(result["tables"])
    session["_assistant_ingest"] = copy.deepcopy(result)
    return result


def close(session) -> None:
    """Discard only owned in-memory state; never touch any filesystem path."""
    if isinstance(session, dict):
        session.pop("_assistant_ingest", None)
        session["_assistant_ingest_closed"] = True


MODE_DISCOVER = "discover"
MODE_COMPUTE = "compute"


def add_workbook_selection(payload) -> dict:
    """Validate an explicitly sampled/full v2 selection, preserving the v1 reader."""
    try:
        if not isinstance(payload, dict):
            raise ValueError("Selection must be an object")
        mode = payload.get("mode")
        rows, header = payload.get("rows"), payload.get("header")
        total, ordinals = payload.get("totalRows"), payload.get("sampleOrdinals")
        if mode not in (MODE_DISCOVER, MODE_COMPUTE):
            raise ValueError("Unsupported selection mode")
        if (not isinstance(total, int) or isinstance(total, bool) or total <= 0
                or total > csv_source.MAX_ROWS or not isinstance(rows, list)
                or not isinstance(header, list) or not isinstance(ordinals, list)):
            raise ValueError("Selection dimensions are invalid")
        if (any(not isinstance(n, int) or isinstance(n, bool) or not 0 <= n < total for n in ordinals)
                or any(a >= b for a, b in zip(ordinals, ordinals[1:]))):
            raise ValueError("Sample ordinals must be ordered, unique and within the source")
        if mode == MODE_DISCOVER and (len(rows) != len(ordinals) or len(rows) > MAX_PREVIEW_ROWS):
            raise ValueError("Discovery requires at most twenty indexed rows")
        if mode == MODE_COMPUTE and len(rows) != total:
            raise ValueError("Compute requires the complete source")
        # The v1 reader checks all cell, header, locator and byte bounds on the
        # submitted rows. Only its sample/full-row guard is adapted here.
        bounded = {**payload, "sampleOnly": False, "totalRows": len(rows)}
        result = add_open_workbook(bounded)
        if result["errors"]:
            return result
        raw = result["tables"][0]
        raw.update(mode=mode, sampleOrdinals=list(ordinals), totalRows=total)
        result["sources"][0]["hash"] = canonical_hash({
            "header": raw["header"], "rows": raw["rows"], "mode": mode,
            "totalRows": total, "sampleOrdinals": ordinals,
        })
        return result
    except (ValueError, TypeError, OverflowError):
        return _fail(_empty(), "workbook", "Workbook selection mode, dimensions or ordinals are invalid")
