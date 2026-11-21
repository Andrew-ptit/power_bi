"""Bounded native namespace normalization of an owned, disposable source copy.

Excel performs every formula/name update. No source OOXML expression is edited.
Normalization alone is not import or recovery qualification.
"""
import base64
import hashlib
import re
import secrets
from io import BytesIO
from zipfile import ZipFile

from pbip_assistant.errors import InputError
from pbip_assistant.core.resources import repository_path
from pbip_assistant.coordinator_runtime import operation_workspace
from pbip_assistant.excel.connector import PowerShellExcelRunner
from pbip_assistant.sources.xlsx import MAIN, MAX_UNCOMPRESSED
from .inventory import _xlsx_sheets, _xml, safe_sheet_name


def _unsupported(detail):
    return InputError("DP_UNSUPPORTED_PRESERVATION", "preparation", detail)


def namespace_plan(payload, sheet_names, namespace_id):
    if not isinstance(payload, bytes) or not payload or len(payload) > 64 * 1024 * 1024:
        raise _unsupported("Source exceeds the bounded XLSX limit")
    if not isinstance(namespace_id, str) or not re.fullmatch("[a-f0-9]{16}", namespace_id):
        raise _unsupported("Invalid native namespace identifier")
    names, features, defined, tables = _xlsx_sheets(payload)
    if set(features) - {"tables", "defined_names"}:
        raise _unsupported("External links, protected workbooks, charts and pivots are unsupported")
    if not isinstance(sheet_names, dict) or set(sheet_names) != set(names):
        raise _unsupported("Native normalization requires the complete reviewed sheet group")
    if "workbook" in names and any(n["scope"] == "workbook" for n in defined):
        raise _unsupported("A worksheet named workbook creates an ambiguous name scope")
    used = set()
    for target in sheet_names.values():
        if not isinstance(target, str) or safe_sheet_name(target, set()) != target or target.casefold() in used:
            raise _unsupported("Reviewed worksheet names are invalid or collide")
        used.add(target.casefold())
    with ZipFile(BytesIO(payload)) as archive:
        if sum(m.file_size for m in archive.infolist()) > MAX_UNCOMPRESSED:
            raise _unsupported("Expanded source exceeds the package bound")
        book = _xml(archive.read("xl/workbook.xml"))
        properties = book.find(f"{{{MAIN}}}workbookPr")
        if properties is not None and properties.get("date1904") in {"1", "true"}:
            raise _unsupported("Cross-workbook 1904 date conversion remains unqualified")
        for member in archive.namelist():
            if any(token in member.lower() for token in ("vbaproject", "external", "connections", "querytable", "activex", "embeddings")):
                raise _unsupported("Source contains unsupported executable or external dependencies")
            if member.startswith("xl/worksheets/") and member.endswith(".xml"):
                sheet = _xml(archive.read(member))
                if sheet.find(f"{{{MAIN}}}sheetProtection") is not None:
                    raise _unsupported("Protected worksheets cannot be normalized")
    prefix = "_dp_" + namespace_id
    return {"namespaceId": namespace_id, "sourceSha256": hashlib.sha256(payload).hexdigest(),
            "sheets": [{"sourceName": name, "targetName": sheet_names[name]} for name in names],
            "names": [{**name, "targetName": prefix + "_n" + str(i)} for i, name in enumerate(defined)],
            "tables": [{"name": name, "targetName": prefix + "_t" + str(i)} for i, name in enumerate(tables)]}


def normalize_workbook(payload, sheet_names, *, runner=None, workspace_manager=None):
    plan = namespace_plan(payload, sheet_names, secrets.token_hex(8))
    runner = runner or PowerShellExcelRunner(
        script=repository_path("tools", "excel_connector", "Invoke-PreparationNamespace.ps1"),
        workspace_manager=workspace_manager)
    with operation_workspace(workspace_manager, legacy_prefix="pbip-preparation-namespace-") as folder:
        source, output = folder / "source.xlsx", folder / "normalized.xlsx"
        source.write_bytes(payload)
        result = runner.apply({"version": 1, "mode": "preparation-namespace-v1", "workbookPath": str(source),
                               "outputPath": str(output), **plan})
        if source.read_bytes() != payload:
            raise _unsupported("Native normalization changed its read-only input copy")
        if not output.is_file() or not isinstance(result, dict) or result.get("namespaceId") != plan["namespaceId"]:
            raise _unsupported("Native normalization did not return a verified output")
        if output.stat().st_size > 64 * 1024 * 1024:
            raise _unsupported("Normalized source exceeds the bounded XLSX limit")
        normalized = output.read_bytes()
        normalized_names, _, normalized_defined, normalized_tables = _xlsx_sheets(normalized)
        if normalized_names != [s["targetName"] for s in plan["sheets"]]:
            raise _unsupported("Native worksheet namespace read-back differs from review")
        if ({n["name"] for n in normalized_defined} != {n["targetName"] for n in plan["names"]}
                or set(normalized_tables) != {t["targetName"] for t in plan["tables"]}):
            raise _unsupported("Native names or Tables were not normalized completely")
        from .packages import image_fingerprint
        from .package_preservation import inspect_package,verify_package_image
        frames = result.get("sheets")
        if not isinstance(frames, list) or [s.get("name") for s in frames] != normalized_names:
            raise _unsupported("Native source semantic frames are incomplete")
        # Validate all native matrices before exposing them to package planning.
        image_fingerprint({"version": 1, "sheets": [{"sheetId": str(i), **s} for i, s in enumerate(frames)]})
        evidence = inspect_package(normalized)
        verify_package_image(evidence,{"version":1,"sheets":[{"sheetId":str(i),**s} for i,s in enumerate(frames)]})
        merges = any(child[0] == f"{{{MAIN}}}mergeCells" for part in evidence["sheets"].values()
                     for child in evidence["parts"][part][3])
        return {"base64": base64.b64encode(normalized).decode("ascii"), "namespace": plan,
                "nativeEvidence": frames, "packageFingerprint": evidence["fingerprint"],
                "merges": merges,
                "sha256": hashlib.sha256(normalized).hexdigest()}
