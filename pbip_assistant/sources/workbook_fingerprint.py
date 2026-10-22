"""Fingerprint workbook data without depending on ZIP timestamps or compression bytes."""

from __future__ import annotations

from io import BytesIO
import hashlib
import json
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

from pbip_assistant.errors import InputError


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


def _canonical_style_node(element: ET.Element, *, omit_attributes: frozenset[str] = frozenset()) -> tuple:
    """Keep opaque style content without depending on XML namespace prefixes."""
    return (
        element.tag,
        tuple(sorted((key, value) for key, value in element.attrib.items() if key not in omit_attributes)),
        element.text if element.text and element.text.strip() else "",
        tuple(_canonical_style_node(child) for child in element),
    )


class _StyleCatalog:
    """Resolve source formatting independently of package-wide style indices.

    Importing a result sheet may append/reindex fonts and XFs. Only referenced
    cell/base XFs and their resolved components affect source cell formatting.
    Unmodeled global containers remain opaque and conservatively guarded.
    """

    _INDEXED_COLLECTIONS = frozenset({
        "numFmts", "fonts", "fills", "borders", "cellStyleXfs", "cellXfs", "cellStyles",
    })

    def __init__(self, archive: zipfile.ZipFile, names: set[str]) -> None:
        self.root = ET.fromstring(archive.read("xl/styles.xml")) if "xl/styles.xml" in names else None
        self.collections: dict[str, list[ET.Element]] = {}
        self.custom_formats: dict[int, ET.Element] = {}
        self._cell_cache: dict[int, str] = {}
        self._base_cache: dict[int, tuple] = {}
        self._component_cache: dict[tuple[str, int], tuple] = {}
        if self.root is not None:
            for collection in self.root:
                local_name = collection.tag.removeprefix(f"{{{MAIN}}}")
                if local_name in self._INDEXED_COLLECTIONS:
                    if local_name in self.collections:
                        raise ValueError("Duplicate style collection")
                    self.collections[local_name] = list(collection)
            for number_format in self.collections.get("numFmts", []):
                index = self._index(number_format.get("numFmtId"))
                if index in self.custom_formats or number_format.get("formatCode") is None:
                    raise ValueError("Invalid custom number format")
                self.custom_formats[index] = number_format

    @staticmethod
    def _index(value: str | None) -> int:
        index = int(value) if value is not None else 0
        if index < 0:
            raise ValueError("Negative style index")
        return index

    def _record(self, collection: str, index: int) -> ET.Element:
        records = self.collections.get(collection, [])
        if index >= len(records):
            raise ValueError("Style reference is outside its collection")
        return records[index]

    def _component(self, collection: str, value: str | None) -> tuple:
        index = self._index(value)
        key = (collection, index)
        if key not in self._component_cache:
            self._component_cache[key] = _canonical_style_node(self._record(collection, index))
        return self._component_cache[key]

    def _number_format(self, value: str | None) -> tuple:
        index = self._index(value)
        if index in self.custom_formats:
            return ("custom", _canonical_style_node(self.custom_formats[index], omit_attributes=frozenset({"numFmtId"})))
        if index >= 164:
            raise ValueError("Custom number format reference is missing")
        return ("builtin", index)

    def _xf(self, record: ET.Element, *, cell: bool) -> tuple:
        references = {"numFmtId", "fontId", "fillId", "borderId"}
        resolved = (
            self._number_format(record.get("numFmtId")),
            self._component("fonts", record.get("fontId")),
            self._component("fills", record.get("fillId")),
            self._component("borders", record.get("borderId")),
        )
        base = None
        if cell:
            references.add("xfId")
            if record.get("xfId") is not None or self.collections.get("cellStyleXfs"):
                base_index = self._index(record.get("xfId"))
                if base_index not in self._base_cache:
                    self._base_cache[base_index] = self._xf(self._record("cellStyleXfs", base_index), cell=False)
                base = self._base_cache[base_index]
        return (_canonical_style_node(record, omit_attributes=frozenset(references)), resolved, base)

    def cell_style(self, value: str | None) -> str:
        index = self._index(value)
        if index not in self._cell_cache:
            if self.root is None:
                if index:
                    raise ValueError("Cell references absent styles")
                semantic = ("implicit-default-style",)
            else:
                semantic = self._xf(self._record("cellXfs", index), cell=True)
            self._cell_cache[index] = hashlib.sha256(json.dumps(semantic, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        return self._cell_cache[index]

    def opaque_globals(self) -> tuple:
        if self.root is None:
            return ()
        return (
            tuple(sorted(self.root.attrib.items())),
            tuple(_canonical_style_node(node) for node in self.root
                  if node.tag.removeprefix(f"{{{MAIN}}}") not in self._INDEXED_COLLECTIONS),
        )


def _sheet_digest(
    archive: zipfile.ZipFile, path: str, strings: list[bytes], styles: _StyleCatalog | None = None,
) -> str:
    digest = hashlib.sha256()
    with archive.open(path) as stream:
        for _, element in ET.iterparse(stream, events=("end",)):
            if element.tag == f"{{{MAIN}}}col" and styles is not None and element.get("style") is not None:
                _update(digest, "columnStyle", element.get("min"), element.get("max"), styles.cell_style(element.get("style")))
            if element.tag != f"{{{MAIN}}}row":
                continue
            if styles is not None and element.get("s") is not None:
                _update(digest, "rowStyle", element.get("r"), styles.cell_style(element.get("s")))
            for cell in element.findall(f"{{{MAIN}}}c"):
                cell_type = cell.get("t", "n")
                value = cell.findtext(f"{{{MAIN}}}v")
                if cell_type == "s" and value is not None:
                    value = strings[int(value)].hex()
                    cell_type = "text"
                elif cell_type == "inlineStr":
                    value = hashlib.sha256("".join(node.text or "" for node in cell.iter(f"{{{MAIN}}}t")).encode("utf-8")).hexdigest()
                    cell_type = "text"
                formula = cell.findtext(f"{{{MAIN}}}f")
                _update(digest, cell.get("r"), cell_type, styles.cell_style(cell.get("s")) if styles is not None else None, formula, value)
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

    Referenced cell/row/column formatting is always guarded. ``include_styles``
    retains the legacy distinction for conservative global style containers;
    disabling it does not disable the source number/date-format guard.
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
            styles = _StyleCatalog(archive, names)
            digest = hashlib.sha256()
            sheets = workbook.findall(f"{{{MAIN}}}sheets/{{{MAIN}}}sheet")
            if typed_result_source_sheets is not None:
                ignored_sheet_names = ignored_sheet_names | frozenset(
                    name for sheet in sheets
                    if (name := sheet.get("name")) is not None
                    and re.fullmatch(r"PQ_Typed_Result(?:_(?:[2-9]|[1-9][0-9]+))?", name)
                    and name not in typed_result_source_sheets
                )
            for sheet in sheets:
                if sheet.get("name") in ignored_sheet_names:
                    continue
                path = targets[sheet.get(f"{{{REL}}}id")]
                _update(digest, "sheet", sheet.get("name"), _sheet_digest(archive, path, strings, styles))
            defined_names = []
            for name in workbook.findall(f"{{{MAIN}}}definedNames/{{{MAIN}}}definedName"):
                local_sheet_id = name.get("localSheetId")
                scope = None
                if local_sheet_id is not None:
                    scope_index = int(local_sheet_id)
                    if not 0 <= scope_index < len(sheets):
                        raise ValueError("Defined name has an invalid worksheet scope")
                    scope = sheets[scope_index].get("name")
                    if scope in ignored_sheet_names:
                        continue
                defined_names.append((name.get("name"), scope, name.text))
            for name, scope, expression in sorted(defined_names, key=lambda item: tuple(part or "" for part in item)):
                _update(digest, "name", name, scope, expression)
            for path in sorted(name for name in names if re.fullmatch(r"xl/tables/table\d+\.xml", name)):
                table = ET.fromstring(archive.read(path))
                _update(digest, "table", table.get("name"), table.get("displayName"), table.get("ref"))
                for column in table.findall(f"{{{MAIN}}}tableColumns/{{{MAIN}}}tableColumn"):
                    _update(digest, "column", column.get("id"), column.get("name"))
            if include_styles:
                _update(digest, "styles", styles.opaque_globals())
            return digest.hexdigest()
    except (KeyError, ValueError, IndexError, ET.ParseError, zipfile.BadZipFile, OSError) as exc:
        raise InputError("WORKBOOK_FINGERPRINT_FAILED", "workbookBase64", "Cannot inspect the exported workbook data safely") from exc
