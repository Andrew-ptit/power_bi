"""Fingerprint workbook data without depending on ZIP timestamps or compression bytes."""

from __future__ import annotations

from io import BytesIO
import hashlib
import json
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

from .errors import InputError


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024


def _update(digest: hashlib._Hash, *parts: object) -> None:
    digest.update(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    digest.update(b"\n")


def _member_path(target: str) -> str:
    if target.startswith("/"):
        path = target.lstrip("/")
    elif target.startswith("xl/"):
        path = target
    else:
        path = posixpath.normpath(posixpath.join("xl", target))
    if not path.startswith("xl/") or ".." in path.split("/"):
        raise ValueError("Workbook relationship points outside xl")
    return path


def _shared_strings(archive: zipfile.ZipFile) -> list[bytes]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    strings: list[bytes] = []
    with archive.open("xl/sharedStrings.xml") as stream:
        for _, element in ET.iterparse(stream, events=("end",)):
            if element.tag == f"{{{MAIN}}}si":
                value = "".join(node.text or "" for node in element.iter(f"{{{MAIN}}}t"))
                strings.append(hashlib.sha256(value.encode("utf-8")).digest())
                element.clear()
    return strings


def _sheet_digest(archive: zipfile.ZipFile, path: str, strings: list[bytes]) -> str:
    digest = hashlib.sha256()
    with archive.open(path) as stream:
        for _, element in ET.iterparse(stream, events=("end",)):
            if element.tag != f"{{{MAIN}}}row":
                continue
            for cell in element.findall(f"{{{MAIN}}}c"):
                cell_type = cell.get("t", "")
                value = cell.findtext(f"{{{MAIN}}}v")
                if cell_type == "s" and value is not None:
                    value = strings[int(value)].hex()
                    cell_type = "text"
                elif cell_type == "inlineStr":
                    value = hashlib.sha256("".join(node.text or "" for node in cell.iter(f"{{{MAIN}}}t")).encode("utf-8")).hexdigest()
                    cell_type = "text"
                formula = cell.findtext(f"{{{MAIN}}}f")
                _update(digest, cell.get("r"), cell_type, cell.get("s", ""), formula, value)
            element.clear()
    return digest.hexdigest()


def workbook_data_fingerprint(
    payload: bytes,
    *,
    ignored_sheet_names: frozenset[str] = frozenset(),
    include_styles: bool = True,
    typed_result_source_sheets: frozenset[str] | None = None,
) -> str:
    """Hash all worksheet cell values/formulas and PQ-visible workbook structure.

    This is a stale-input guard, not a cryptographic attestation of Excel runtime.
    """
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            members = archive.infolist()
            names = {item.filename for item in members}
            if len(names) != len(members) or sum(item.file_size for item in members) > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Workbook package is too large or has duplicate entries")
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            targets = {
                node.get("Id"): _member_path(node.get("Target", ""))
                for node in relationships.findall(f"{{{PKG_REL}}}Relationship")
                if node.get("TargetMode") != "External" and node.get("Type", "").endswith("/worksheet")
            }
            strings = _shared_strings(archive)
            digest = hashlib.sha256()
            sheets = workbook.findall(f"{{{MAIN}}}sheets/{{{MAIN}}}sheet")
            if typed_result_source_sheets is not None:
                ignored_sheet_names = ignored_sheet_names | frozenset(
                    name for sheet in sheets
                    if (name := sheet.get("name")) is not None
                    and re.fullmatch(r"PQ_Typed_Result(?:_[2-9][0-9]*)?", name)
                    and name not in typed_result_source_sheets
                )
            for sheet in sheets:
                if sheet.get("name") in ignored_sheet_names:
                    continue
                path = targets[sheet.get(f"{{{REL}}}id")]
                _update(digest, "sheet", sheet.get("name"), _sheet_digest(archive, path, strings))
            for name in workbook.findall(f"{{{MAIN}}}definedNames/{{{MAIN}}}definedName"):
                local_sheet_id = name.get("localSheetId")
                if local_sheet_id is not None and sheets[int(local_sheet_id)].get("name") in ignored_sheet_names:
                    continue
                _update(digest, "name", name.get("name"), name.get("localSheetId"), name.text)
            for path in sorted(name for name in names if re.fullmatch(r"xl/tables/table\d+\.xml", name)):
                table = ET.fromstring(archive.read(path))
                _update(digest, "table", table.get("name"), table.get("displayName"), table.get("ref"))
                for column in table.findall(f"{{{MAIN}}}tableColumns/{{{MAIN}}}tableColumn"):
                    _update(digest, "column", column.get("id"), column.get("name"))
            if include_styles and "xl/styles.xml" in names:
                _update(digest, "styles", hashlib.sha256(ET.canonicalize(archive.read("xl/styles.xml").decode("utf-8")).encode("utf-8")).hexdigest())
            return digest.hexdigest()
    except (KeyError, ValueError, IndexError, ET.ParseError, zipfile.BadZipFile, OSError) as exc:
        raise InputError("WORKBOOK_FINGERPRINT_FAILED", "workbookBase64", "Cannot inspect the exported workbook data safely") from exc
