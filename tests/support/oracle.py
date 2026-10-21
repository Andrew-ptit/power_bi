from __future__ import annotations

import base64
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from pathlib import Path
import posixpath
import re
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


PROBLEM_CHAIN_NAMESPACE = "urn:local-data-copilot:pq-problem-chain:v1"
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_REVISIONS = 50

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPE_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_CUSTOM_XML_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml"
_CUSTOM_XML_PROPS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps"
_CUSTOM_XML_PROPS_TYPE = "application/vnd.openxmlformats-officedocument.customXmlProperties+xml"
_CUSTOM_XML_DATASTORE_NS = "http://schemas.openxmlformats.org/officeDocument/2006/customXml"
_ITEM_RE = re.compile(r"^customXml/item\d+\.xml$", re.IGNORECASE)


class PackageOracleError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def validate_document_limits(document: dict[str, Any]) -> bytes:
    revisions = document.get("revisions")
    if not isinstance(revisions, list):
        raise PackageOracleError("PQPC_DOCUMENT_INVALID", "revisions must be an array")
    if len(revisions) > MAX_REVISIONS:
        raise PackageOracleError("PQPC_HISTORY_LIMIT", "revision count exceeds 50")
    payload = canonical_json_bytes(document)
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise PackageOracleError("PQPC_HISTORY_LIMIT", "canonical JSON exceeds 2 MiB")
    return payload


def build_problem_chain_xml(document: dict[str, Any]) -> tuple[str, str]:
    payload = validate_document_limits(document)
    history_hash = sha256_bytes(payload)
    ET.register_namespace("ldc", PROBLEM_CHAIN_NAMESPACE)
    root = ET.Element(
        f"{{{PROBLEM_CHAIN_NAMESPACE}}}problemChain",
        {"schemaVersion": "1.0", "historyHash": history_hash},
    )
    child = ET.SubElement(
        root,
        f"{{{PROBLEM_CHAIN_NAMESPACE}}}payload",
        {"encoding": "base64"},
    )
    child.text = base64.b64encode(payload).decode("ascii")
    return ET.tostring(root, encoding="unicode", short_empty_elements=False), history_hash


def parse_problem_chain_xml(xml: str | bytes) -> dict[str, Any]:
    raw = xml.encode("utf-8") if isinstance(xml, str) else bytes(xml)
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise PackageOracleError("PQPC_DOCUMENT_INVALID", "DTD and entities are forbidden")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PackageOracleError("PQPC_DOCUMENT_INVALID", "Custom XML is not well formed") from exc
    if root.tag != f"{{{PROBLEM_CHAIN_NAMESPACE}}}problemChain":
        raise PackageOracleError("PQPC_DOCUMENT_INVALID", "unexpected Custom XML namespace or root")
    if root.attrib.get("schemaVersion") != "1.0":
        raise PackageOracleError("PQPC_DOCUMENT_INVALID", "unsupported schemaVersion")
    children = list(root)
    if len(children) != 1 or children[0].tag != f"{{{PROBLEM_CHAIN_NAMESPACE}}}payload":
        raise PackageOracleError("PQPC_DOCUMENT_INVALID", "exactly one payload element is required")
    child = children[0]
    if child.attrib != {"encoding": "base64"} or child.text is None:
        raise PackageOracleError("PQPC_DOCUMENT_INVALID", "payload must use base64 encoding")
    try:
        payload = base64.b64decode(child.text, validate=True)
    except (ValueError, TypeError) as exc:
        raise PackageOracleError("PQPC_DOCUMENT_INVALID", "payload is not valid base64") from exc
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise PackageOracleError("PQPC_HISTORY_LIMIT", "canonical JSON exceeds 2 MiB")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageOracleError("PQPC_DOCUMENT_INVALID", "payload is not UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise PackageOracleError("PQPC_DOCUMENT_INVALID", "payload root must be an object")
    canonical = validate_document_limits(document)
    if payload != canonical:
        raise PackageOracleError("PQPC_DOCUMENT_INVALID", "payload JSON is not canonical")
    if root.attrib.get("historyHash") != sha256_bytes(canonical):
        raise PackageOracleError("PQPC_HASH_MISMATCH", "historyHash does not match payload")
    return {
        "document": document,
        "historyHash": root.attrib["historyHash"],
        "canonicalBytes": len(canonical),
    }


def _looks_like_problem_chain(raw: bytes) -> bool:
    return PROBLEM_CHAIN_NAMESPACE.encode("utf-8") in raw


def inspect_problem_chain_parts(path: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    try:
        with ZipFile(path) as archive:
            item_names = sorted(name for name in archive.namelist() if _ITEM_RE.match(name))
            for name in item_names:
                raw = archive.read(name)
                try:
                    root = ET.fromstring(raw)
                except ET.ParseError as exc:
                    if _looks_like_problem_chain(raw):
                        raise PackageOracleError(
                            "PQPC_DOCUMENT_INVALID", f"{name} is malformed"
                        ) from exc
                    continue
                if root.tag != f"{{{PROBLEM_CHAIN_NAMESPACE}}}problemChain":
                    continue
                parsed = parse_problem_chain_xml(raw)
                records.append({"partName": name, **parsed})
            if len(records) > 1:
                raise PackageOracleError(
                    "PQPC_DUPLICATE_XML_PART",
                    "workbook contains more than one Problem Chain Custom XML part",
                )
            if records:
                record = records[0]
                item_name = record["partName"]
                workbook_rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
                linked_items = {
                    posixpath.normpath(posixpath.join("xl", relation.attrib.get("Target", "")))
                    for relation in workbook_rels.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
                    if relation.attrib.get("Type") == _CUSTOM_XML_REL
                    and relation.attrib.get("TargetMode", "Internal") == "Internal"
                }
                if item_name not in linked_items:
                    raise PackageOracleError(
                        "PQPC_DOCUMENT_INVALID",
                        f"{item_name} is orphaned from the workbook relationships",
                    )
                suffix = item_name.removeprefix("customXml/item").removesuffix(".xml")
                rels_name = f"customXml/_rels/item{suffix}.xml.rels"
                if rels_name not in archive.namelist():
                    raise PackageOracleError(
                        "PQPC_DOCUMENT_INVALID", f"{item_name} has no Custom XML properties relationship",
                    )
                item_rels = ET.fromstring(archive.read(rels_name))
                props_targets = [
                    posixpath.normpath(posixpath.join("customXml", relation.attrib.get("Target", "")))
                    for relation in item_rels.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
                    if relation.attrib.get("Type") == _CUSTOM_XML_PROPS_REL
                    and relation.attrib.get("TargetMode", "Internal") == "Internal"
                ]
                if len(props_targets) != 1 or props_targets[0] not in archive.namelist():
                    raise PackageOracleError(
                        "PQPC_DOCUMENT_INVALID", f"{item_name} has an invalid Custom XML properties target",
                    )
                props_name = props_targets[0]
                content_types = ET.fromstring(archive.read("[Content_Types].xml"))
                overrides = {
                    node.attrib.get("PartName"): node.attrib.get("ContentType")
                    for node in content_types.findall(f"{{{_CONTENT_TYPE_NS}}}Override")
                }
                if overrides.get("/" + props_name) != _CUSTOM_XML_PROPS_TYPE:
                    raise PackageOracleError(
                        "PQPC_DOCUMENT_INVALID", f"{props_name} has no valid content-type override",
                    )
                props = ET.fromstring(archive.read(props_name))
                schema_uris = {
                    node.attrib.get(f"{{{_CUSTOM_XML_DATASTORE_NS}}}uri")
                    for node in props.findall(f".//{{{_CUSTOM_XML_DATASTORE_NS}}}schemaRef")
                }
                if PROBLEM_CHAIN_NAMESPACE not in schema_uris:
                    raise PackageOracleError(
                        "PQPC_DOCUMENT_INVALID", f"{props_name} does not declare the Problem Chain namespace",
                    )
            return {
                "count": len(records),
                "parts": records,
                "allCustomXmlParts": item_names,
                "packageParts": sorted(archive.namelist()),
            }
    except PackageOracleError:
        raise
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise PackageOracleError("PQPC_DOCUMENT_INVALID", "workbook is not valid OOXML") from exc


def _relationship_targets(archive: ZipFile, rel_path: str) -> dict[str, str]:
    root = ET.fromstring(archive.read(rel_path))
    return {
        item.attrib["Id"]: item.attrib["Target"]
        for item in root.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
    }


def _shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(item.itertext()) for item in root.findall(f"{{{_MAIN_NS}}}si")]


def _worksheet_cells(root: ET.Element, shared_strings: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for cell in root.findall(f".//{{{_MAIN_NS}}}c"):
        formula = cell.find(f"{{{_MAIN_NS}}}f")
        value = cell.find(f"{{{_MAIN_NS}}}v")
        inline = cell.find(f"{{{_MAIN_NS}}}is")
        storage_type = cell.attrib.get("t")
        raw_value = None if value is None else value.text
        inline_value = None if inline is None else "".join(inline.itertext())
        if storage_type == "inlineStr":
            semantic_type = "text"
            semantic_value = inline_value or ""
        elif storage_type == "s":
            try:
                semantic_value = shared_strings[int(raw_value or "")]
            except (ValueError, IndexError) as exc:
                raise PackageOracleError(
                    "PQPC_DOCUMENT_INVALID", "worksheet contains an invalid shared-string index"
                ) from exc
            semantic_type = "text"
        else:
            semantic_type = storage_type
            semantic_value = raw_value
            if raw_value is not None and storage_type in (None, "n"):
                try:
                    with localcontext() as context:
                        # Excel values have at most 15 significant decimal digits. Saving may
                        # expose a longer binary floating-point spelling without changing the cell.
                        context.prec = 15
                        number = +Decimal(raw_value)
                        if not number.is_finite():
                            raise InvalidOperation
                        if number == 0:
                            number = Decimal(0)
                        semantic_value = str(number.normalize())
                except InvalidOperation as exc:
                    raise PackageOracleError(
                        "PQPC_DOCUMENT_INVALID", "worksheet contains an invalid numeric value"
                    ) from exc
        result.append({
            "ref": cell.attrib.get("r"),
            "type": semantic_type,
            "formula": None if formula is None else {
                "text": formula.text or "",
                "attrs": dict(sorted(formula.attrib.items())),
            },
            "value": semantic_value,
        })
    return result


def semantic_workbook_snapshot(path: Path) -> dict[str, Any]:
    """Capture user data/schema while ignoring Excel's package serialization churn."""
    try:
        with ZipFile(path) as archive:
            shared_strings = _shared_strings(archive)
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            relations = _relationship_targets(archive, "xl/_rels/workbook.xml.rels")
            sheets: list[dict[str, Any]] = []
            for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
                relation_id = sheet.attrib[f"{{{_REL_NS}}}id"]
                target = relations[relation_id].replace("\\", "/")
                part = target.lstrip("/") if target.startswith("/") else "xl/" + target
                root = ET.fromstring(archive.read(part))
                sheets.append({
                    "name": sheet.attrib.get("name"),
                    "state": sheet.attrib.get("state", "visible"),
                    "cells": _worksheet_cells(root, shared_strings),
                })

            tables: list[dict[str, Any]] = []
            for name in sorted(n for n in archive.namelist() if n.startswith("xl/tables/") and n.endswith(".xml")):
                table = ET.fromstring(archive.read(name))
                columns = table.find(f"{{{_MAIN_NS}}}tableColumns")
                tables.append({
                    "name": table.attrib.get("name"),
                    "displayName": table.attrib.get("displayName"),
                    "ref": table.attrib.get("ref"),
                    "headerRowCount": table.attrib.get("headerRowCount", "1"),
                    "totalsRowCount": table.attrib.get("totalsRowCount", "0"),
                    "columns": [] if columns is None else [
                        {
                            key: column.attrib.get(key)
                            for key in ("id", "name", "totalsRowFunction", "totalsRowLabel")
                            if key in column.attrib
                        }
                        for column in columns.findall(f"{{{_MAIN_NS}}}tableColumn")
                    ],
                })

            defined_names = workbook.find(f"{{{_MAIN_NS}}}definedNames")
            return {
                "sheets": sheets,
                "tables": tables,
                "definedNames": [] if defined_names is None else [
                    {"attrs": dict(sorted(item.attrib.items())), "text": item.text or ""}
                    for item in list(defined_names)
                ],
            }
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise PackageOracleError("PQPC_DOCUMENT_INVALID", "cannot inspect workbook semantics") from exc


def package_part_delta(before: Path, after: Path) -> dict[str, list[str]]:
    with ZipFile(before) as left, ZipFile(after) as right:
        before_names = set(left.namelist())
        after_names = set(right.namelist())
    return {
        "added": sorted(after_names - before_names),
        "removed": sorted(before_names - after_names),
    }
