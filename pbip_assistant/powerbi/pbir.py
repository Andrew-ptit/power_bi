"""Read-only PBIR catalog and offline support gates for W-07.

The module deliberately does not fetch schemas or write report files.  It pins
the PBIR schema versions exercised by the synthetic W-03 fixture and validates
the required, patch-relevant contract for those document kinds.  A static pass
is not Power BI Desktop runtime verification.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from pbip_assistant.errors import InputError
from pbip_assistant.pbip import inventory_pbip


SCHEMA_ROOT = "https://developer.microsoft.com/json-schemas/fabric/item/report/"

# R1 is intentionally narrow.  Supporting a new schema version is an explicit
# code/test change, never an automatic network lookup at runtime.
SUPPORTED_SCHEMAS: dict[str, str] = {
    "definition_properties": SCHEMA_ROOT + "definitionProperties/2.0.0/schema.json",
    "version": SCHEMA_ROOT + "definition/versionMetadata/1.0.0/schema.json",
    "report": SCHEMA_ROOT + "definition/report/3.2.0/schema.json",
    "pages_metadata": SCHEMA_ROOT + "definition/pagesMetadata/1.0.0/schema.json",
    "page": SCHEMA_ROOT + "definition/page/2.1.0/schema.json",
    "visual": SCHEMA_ROOT + "definition/visualContainer/2.4.0/schema.json",
    "bookmarks_metadata": SCHEMA_ROOT + "definition/bookmarksMetadata/1.0.0/schema.json",
    "bookmark": SCHEMA_ROOT + "definition/bookmark/2.1.0/schema.json",
}

SUPPORTED_DEFINITION_VERSION = "4.0"
SUPPORTED_PBIR_VERSION = "2.0.0"

_OBJECT_NAME = re.compile(r"^[\w-]+$", re.UNICODE)
_KNOWN_DATA_VISUALS = frozenset({
    "barChart",
    "card",
    "cardVisual",
    "clusteredBarChart",
    "clusteredColumnChart",
    "columnChart",
    "donutChart",
    "lineChart",
    "pieChart",
    "scatterChart",
    "tableEx",
})
_PROTECTED_REPORT_PATHS = frozenset({
    ".pbi/localSettings.json",
    "definition.pbir",
    "mobileState.json",
    "report.json",  # PBIR-Legacy, not definition/report.json
    "semanticModelDiagramLayout.json",
})

_REQUIRED_FIELDS: dict[str, dict[str, type | tuple[type, ...]]] = {
    "definition_properties": {
        "$schema": str,
        "version": str,
        "datasetReference": dict,
    },
    "version": {"$schema": str, "version": str},
    "report": {"$schema": str, "themeCollection": dict},
    "pages_metadata": {"$schema": str},
    "page": {
        "$schema": str,
        "displayName": str,
        "displayOption": str,
        "name": str,
    },
    "visual": {"$schema": str, "name": str, "position": dict},
    "bookmarks_metadata": {"$schema": str, "items": list},
    "bookmark": {
        "$schema": str,
        "displayName": str,
        "explorationState": dict,
        "name": str,
    },
}


def _issue(code: str, status: str, path: str, detail: str) -> dict[str, str]:
    return {"code": code, "status": status, "path": path, "detail": detail}


def _read_json(path: Path, relative_path: str, issues: list[dict[str, str]]) -> Any | None:
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        issues.append(_issue("PBIR_INVALID_JSON", "blocked", relative_path, str(exc)))
        return None
    if not isinstance(value, dict):
        issues.append(_issue("PBIR_INVALID_DOCUMENT", "blocked", relative_path, "Expected a JSON object"))
        return None
    return value


def _validate_contract(
    kind: str,
    value: dict[str, Any],
    relative_path: str,
    issues: list[dict[str, str]],
) -> None:
    schema = value.get("$schema")
    if schema is None:
        issues.append(_issue("PBIR_SCHEMA_MISSING", "blocked", relative_path, "The $schema declaration is required"))
    elif not isinstance(schema, str):
        issues.append(_issue("PBIR_SCHEMA_INVALID", "blocked", relative_path, "$schema must be a string"))
    elif schema != SUPPORTED_SCHEMAS[kind]:
        issues.append(_issue(
            "PBIR_SCHEMA_UNSUPPORTED",
            "view_only",
            relative_path,
            f"Pinned R1 schema is {SUPPORTED_SCHEMAS[kind]}; found {schema}",
        ))

    for field, expected_type in _REQUIRED_FIELDS[kind].items():
        if field not in value:
            issues.append(_issue("PBIR_REQUIRED_FIELD_MISSING", "blocked", relative_path, f"Missing required field: {field}"))
        elif not isinstance(value[field], expected_type):
            issues.append(_issue("PBIR_FIELD_TYPE_INVALID", "blocked", relative_path, f"Invalid type for field: {field}"))


def _classify_definition_path(relative: Path) -> str | None:
    parts = relative.parts
    if parts == ("version.json",):
        return "version"
    if parts == ("report.json",):
        return "report"
    if parts == ("pages", "pages.json"):
        return "pages_metadata"
    if len(parts) == 3 and parts[0] == "pages" and parts[2] == "page.json" and _OBJECT_NAME.fullmatch(parts[1]):
        return "page"
    if (
        len(parts) == 5
        and parts[0] == "pages"
        and parts[2] == "visuals"
        and parts[4] == "visual.json"
        and _OBJECT_NAME.fullmatch(parts[1])
        and _OBJECT_NAME.fullmatch(parts[3])
    ):
        return "visual"
    if parts == ("bookmarks", "bookmarks.json"):
        return "bookmarks_metadata"
    if (
        len(parts) == 2
        and parts[0] == "bookmarks"
        and parts[1].endswith(".bookmark.json")
        and _OBJECT_NAME.fullmatch(parts[1][:-len(".bookmark.json")])
    ):
        return "bookmark"
    return None


def _field_references(value: Any) -> list[dict[str, Any]]:
    """Return model object references without copying filter literal values."""
    found: list[dict[str, Any]] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for wrapper in ("Measure", "Column", "HierarchyLevel"):
                target = item.get(wrapper)
                if not isinstance(target, dict):
                    continue
                expression = target.get("Expression")
                source_ref = expression.get("SourceRef") if isinstance(expression, dict) else None
                entity = source_ref.get("Entity") if isinstance(source_ref, dict) else None
                prop = target.get("Property") or target.get("Level")
                if isinstance(entity, str) and isinstance(prop, str):
                    found.append({"kind": wrapper.lower(), "entity": entity, "property": prop})
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for ref in found:
        unique[(ref["kind"], ref["entity"], ref["property"])] = ref
    return list(unique.values())


def _contains_filter_values(value: Any) -> bool:
    sensitive_keys = {"literal", "literals", "value", "values"}
    if isinstance(value, dict):
        return any(str(key).lower() in sensitive_keys or _contains_filter_values(nested) for key, nested in value.items())
    if isinstance(value, list):
        return any(_contains_filter_values(nested) for nested in value)
    return False


def _filter_summary(value: Any, *, scope: str, relative_path: str) -> dict[str, Any] | None:
    if not isinstance(value, dict) or "filterConfig" not in value:
        return None
    config = value["filterConfig"]
    filters = config.get("filters") if isinstance(config, dict) else None
    return {
        "scope": scope,
        "path": relative_path,
        "filter_count": len(filters) if isinstance(filters, list) else 0,
        "field_references": _field_references(config),
        "contains_literal_values": _contains_filter_values(config),
        "literal_values_redacted": True,
    }


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except ValueError:
        return False


def _catalog_dataset_reference(
    report_root: Path,
    project_root: Path,
    document: dict[str, Any],
    issues: list[dict[str, str]],
) -> dict[str, Any] | None:
    reference = document.get("datasetReference")
    if not isinstance(reference, dict):
        return None
    if set(reference) == {"byConnection"}:
        issues.append(_issue(
            "PBIR_REMOTE_MODEL_UNSUPPORTED",
            "view_only",
            f"{report_root.name}/definition.pbir",
            "R1 patches only a local semantic model referenced with byPath",
        ))
        return {"kind": "byConnection", "path": None, "target_exists": None}
    if set(reference) != {"byPath"} or not isinstance(reference.get("byPath"), dict):
        issues.append(_issue(
            "PBIR_DATASET_REFERENCE_INVALID",
            "blocked",
            f"{report_root.name}/definition.pbir",
            "Expected exactly one datasetReference.byPath object",
        ))
        return None
    raw_path = reference["byPath"].get("path")
    if not isinstance(raw_path, str) or not raw_path:
        issues.append(_issue(
            "PBIR_DATASET_PATH_INVALID",
            "blocked",
            f"{report_root.name}/definition.pbir",
            "datasetReference.byPath.path must be a non-empty relative path",
        ))
        return None
    posix = PurePosixPath(raw_path)
    windows = PureWindowsPath(raw_path)
    if "\\" in raw_path or posix.is_absolute() or windows.is_absolute() or windows.drive:
        issues.append(_issue(
            "PBIR_DATASET_PATH_UNSAFE",
            "blocked",
            f"{report_root.name}/definition.pbir",
            "byPath must use a relative path with forward-slash separators",
        ))
        return {"kind": "byPath", "path": raw_path, "target_exists": False}
    target = (report_root / Path(*posix.parts)).resolve(strict=False)
    inside = _path_is_within(target, project_root)
    exists = target.is_dir()
    if not inside:
        issues.append(_issue(
            "PBIR_DATASET_PATH_OUTSIDE_PROJECT",
            "blocked",
            f"{report_root.name}/definition.pbir",
            "The semantic model reference resolves outside the selected PBIP root",
        ))
    elif not exists or not target.name.endswith(".SemanticModel"):
        issues.append(_issue(
            "PBIR_DATASET_TARGET_INVALID",
            "blocked",
            f"{report_root.name}/definition.pbir",
            "The referenced local .SemanticModel directory does not exist",
        ))
    return {
        "kind": "byPath",
        "path": raw_path,
        "target": target.relative_to(project_root).as_posix() if inside else None,
        "target_exists": exists if inside else False,
    }


def _catalog_modern_report(
    project_root: Path,
    report_root: Path,
    definition_document: dict[str, Any] | None,
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    definition_root = report_root / "definition"
    documents, allowed_paths, out_of_allowlist = _scan_definition_files(definition_root, report_root, issues)
    _check_definition_contract(documents, report_root, issues)
    pages, visuals, bookmarks, filters = _collect_report_objects(documents, report_root, issues)
    page_order, active_page = _check_page_references(documents, pages, visuals, report_root, issues)
    return {
        "allowed_definition_paths": allowed_paths,
        "out_of_allowlist_paths": out_of_allowlist,
        "pages": pages,
        "visuals": visuals,
        "bookmarks": bookmarks,
        "filters": filters,
        "page_order": page_order,
        "active_page_name": active_page,
    }


def _scan_definition_files(
    definition_root: Path,
    report_root: Path,
    issues: list[dict[str, str]],
) -> tuple[dict[str, tuple[str, dict[str, Any]]], list[str], list[str]]:
    """Read every definition file, classifying it against the pinned allowlist."""
    documents: dict[str, tuple[str, dict[str, Any]]] = {}
    allowed_paths: list[str] = []
    out_of_allowlist: list[str] = []

    for path in sorted(item for item in definition_root.rglob("*") if item.is_file()):
        relative_definition = path.relative_to(definition_root)
        relative_report = path.relative_to(report_root).as_posix()
        kind = _classify_definition_path(relative_definition)
        if kind is None:
            out_of_allowlist.append(relative_report)
            issues.append(_issue(
                "PBIR_PATH_NOT_ALLOWED",
                "view_only",
                f"{report_root.name}/{relative_report}",
                "The file is outside the pinned R1 PBIR definition allowlist",
            ))
            continue
        allowed_paths.append(relative_report)
        document = _read_json(path, f"{report_root.name}/{relative_report}", issues)
        if document is None:
            continue
        _validate_contract(kind, document, f"{report_root.name}/{relative_report}", issues)
        documents[relative_report] = (kind, document)
    return documents, allowed_paths, out_of_allowlist


def _check_definition_contract(
    documents: dict[str, tuple[str, dict[str, Any]]],
    report_root: Path,
    issues: list[dict[str, str]],
) -> None:
    """Require the modern PBIR core files and the pinned definition version."""
    for required in ("definition/version.json", "definition/report.json", "definition/pages/pages.json"):
        if required not in documents:
            issues.append(_issue(
                "PBIR_REQUIRED_FILE_MISSING",
                "blocked",
                f"{report_root.name}/{required}",
                "Required modern PBIR file is missing or unreadable",
            ))

    version_document = documents.get("definition/version.json", (None, {}))[1]
    if version_document and version_document.get("version") != SUPPORTED_PBIR_VERSION:
        issues.append(_issue(
            "PBIR_VERSION_UNSUPPORTED",
            "view_only",
            f"{report_root.name}/definition/version.json",
            f"Pinned R1 PBIR version is {SUPPORTED_PBIR_VERSION}",
        ))


def _collect_report_objects(
    documents: dict[str, tuple[str, dict[str, Any]]],
    report_root: Path,
    issues: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Turn definition documents into pages, visuals, bookmarks and filters."""
    pages: list[dict[str, Any]] = []
    visuals: list[dict[str, Any]] = []
    bookmarks: list[dict[str, Any]] = []
    filters: list[dict[str, Any]] = []

    for relative_report, (kind, document) in sorted(documents.items()):
        if kind == "page":
            folder_name = Path(relative_report).parts[2]
            if document.get("name") != folder_name:
                issues.append(_issue("PBIR_OBJECT_NAME_MISMATCH", "blocked", f"{report_root.name}/{relative_report}", "Page name must match its folder"))
            pages.append({
                "name": document.get("name"),
                "display_name": document.get("displayName"),
                "path": relative_report,
                "display_option": document.get("displayOption"),
                "size": {"width": document.get("width"), "height": document.get("height")},
            })
            summary = _filter_summary(document, scope="page", relative_path=relative_report)
            if summary:
                filters.append(summary)
        elif kind == "visual":
            parts = Path(relative_report).parts
            visual_name = parts[4]
            if document.get("name") != visual_name:
                issues.append(_issue("PBIR_OBJECT_NAME_MISMATCH", "blocked", f"{report_root.name}/{relative_report}", "Visual name must match its folder"))
            visual = document.get("visual")
            visual_type = visual.get("visualType") if isinstance(visual, dict) else None
            bindings = _field_references(visual.get("query")) if isinstance(visual, dict) else []
            if visual_type in _KNOWN_DATA_VISUALS and not bindings:
                issues.append(_issue(
                    "PBIR_VISUAL_BINDING_MISSING",
                    "blocked",
                    f"{report_root.name}/{relative_report}",
                    f"Data visual {visual_type} has no supported semantic field binding",
                ))
            visuals.append({
                "name": document.get("name"),
                "page_name": parts[2],
                "path": relative_report,
                "visual_type": visual_type,
                "position": document.get("position"),
                "bindings": bindings,
            })
            summary = _filter_summary(document, scope="visual", relative_path=relative_report)
            if summary:
                filters.append(summary)
        elif kind == "bookmark":
            bookmark_name = Path(relative_report).name[:-len(".bookmark.json")]
            if document.get("name") != bookmark_name:
                issues.append(_issue("PBIR_OBJECT_NAME_MISMATCH", "blocked", f"{report_root.name}/{relative_report}", "Bookmark name must match its file"))
            exploration = document.get("explorationState", {})
            bookmarks.append({
                "name": document.get("name"),
                "display_name": document.get("displayName"),
                "path": relative_report,
                "field_references": _field_references(exploration),
                "contains_literal_values": _contains_filter_values(exploration),
                "literal_values_redacted": True,
            })

    report_document = documents.get("definition/report.json", (None, {}))[1]
    report_filter = _filter_summary(report_document, scope="report", relative_path="definition/report.json")
    if report_filter:
        filters.append(report_filter)
    return pages, visuals, bookmarks, filters


def _check_page_references(
    documents: dict[str, tuple[str, dict[str, Any]]],
    pages: list[dict[str, Any]],
    visuals: list[dict[str, Any]],
    report_root: Path,
    issues: list[dict[str, str]],
) -> tuple[list[str], str | None]:
    """Validate page order, the active page and every visual's owning page."""
    page_names = {page["name"] for page in pages}
    metadata = documents.get("definition/pages/pages.json", (None, {}))[1]
    page_order = metadata.get("pageOrder", []) if isinstance(metadata, dict) else []
    active_page = metadata.get("activePageName") if isinstance(metadata, dict) else None
    if isinstance(page_order, list) and any(name not in page_names for name in page_order):
        issues.append(_issue("PBIR_PAGE_REFERENCE_INVALID", "blocked", f"{report_root.name}/definition/pages/pages.json", "pageOrder references an unknown page"))
    if active_page is not None and active_page not in page_names:
        issues.append(_issue("PBIR_ACTIVE_PAGE_INVALID", "warning", f"{report_root.name}/definition/pages/pages.json", "activePageName references an unknown page"))
    for visual in visuals:
        if visual["page_name"] not in page_names:
            issues.append(_issue(
                "PBIR_VISUAL_PAGE_INVALID", "blocked", f"{report_root.name}/{visual['path']}",
                "Visual folder references a page without a valid page.json",
            ))
    return page_order, active_page


def _report_files(report_root: Path) -> Iterable[Path]:
    return sorted(path for path in report_root.rglob("*") if path.is_file())


def _catalog_report(project_root: Path, report_root: Path) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    definition_path = report_root / "definition.pbir"
    definition_document = _read_json(definition_path, f"{report_root.name}/definition.pbir", issues) if definition_path.is_file() else None
    if definition_document is None and not definition_path.is_file():
        issues.append(_issue("PBIR_DEFINITION_MISSING", "blocked", f"{report_root.name}/definition.pbir", "definition.pbir is required"))
    if definition_document is not None:
        _validate_contract("definition_properties", definition_document, f"{report_root.name}/definition.pbir", issues)

    dataset_reference = _catalog_dataset_reference(report_root, project_root, definition_document or {}, issues)
    definition_version = definition_document.get("version") if definition_document else None
    has_modern = (report_root / "definition").is_dir()
    has_legacy = (report_root / "report.json").is_file()
    is_legacy = definition_version == "1.0" or (has_legacy and not has_modern)

    protected_paths: list[str] = []
    out_of_scope_paths: list[str] = []
    for path in _report_files(report_root):
        relative = path.relative_to(report_root).as_posix()
        if relative in _PROTECTED_REPORT_PATHS:
            protected_paths.append(relative)
        elif not relative.startswith("definition/"):
            out_of_scope_paths.append(relative)

    modern_catalog = {
        "allowed_definition_paths": [],
        "out_of_allowlist_paths": [],
        "pages": [],
        "visuals": [],
        "bookmarks": [],
        "filters": [],
        "page_order": [],
        "active_page_name": None,
    }
    if is_legacy:
        issues.append(_issue(
            "PBIR_LEGACY_VIEW_ONLY",
            "view_only",
            report_root.name,
            "PBIR-Legacy can be inventoried but is outside the R1 patch allowlist",
        ))
        report_format = "PBIR-legacy"
    elif not has_modern:
        issues.append(_issue("PBIR_DEFINITION_FOLDER_MISSING", "blocked", report_root.name, "Modern PBIR requires the definition folder"))
        report_format = "unknown"
    else:
        report_format = "PBIR"
        modern_catalog = _catalog_modern_report(project_root, report_root, definition_document, issues)

    if definition_version not in {"1.0", SUPPORTED_DEFINITION_VERSION}:
        issues.append(_issue(
            "PBIR_DEFINITION_VERSION_UNSUPPORTED",
            "view_only",
            f"{report_root.name}/definition.pbir",
            f"Pinned R1 definition version is {SUPPORTED_DEFINITION_VERSION}",
        ))

    issue_statuses = {entry["status"] for entry in issues}
    if "blocked" in issue_statuses:
        status = "blocked"
    elif "view_only" in issue_statuses:
        status = "view_only"
    else:
        status = "static_pass"
    static_patch_candidate = status == "static_pass" and report_format == "PBIR"

    return {
        "name": report_root.name,
        "format": report_format,
        "definition_version": definition_version,
        "dataset_reference": dataset_reference,
        "static_validation": status,
        "schema_validation": "not_run",
        "schema_validation_method": "offline_pinned_contract_only",
        "desktop_validation": "not_run",
        "static_patch_candidate": static_patch_candidate,
        "patch_eligible": False,
        "issues": issues,
        "protected_paths": sorted(protected_paths),
        "out_of_scope_paths": sorted(out_of_scope_paths),
        **modern_catalog,
    }


def catalog_pbir(pbip_root: str | Path) -> dict[str, Any]:
    """Catalog PBIR metadata without modifying or sending project content.

    A successful pinned contract sets ``static_patch_candidate`` only.
    ``patch_eligible`` remains false until full schema validation is introduced;
    neither state means Power BI Desktop has loaded or rendered the report.
    """
    try:
        root = Path(pbip_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InputError("INVALID_PBIP", str(pbip_root), str(exc)) from exc
    inventory_pbip(root)  # Also rejects symlinks and malformed PBIP layout.
    reports = [_catalog_report(root, path) for path in sorted(root.glob("*.Report")) if path.is_dir()]
    if not reports:
        raise InputError("INVALID_PBIP", str(root), "Expected at least one .Report directory")
    return {
        "root": str(root),
        "reports": reports,
        "static_patch_candidate": all(report["static_patch_candidate"] for report in reports),
        "patch_eligible": False,
        "desktop_validation": "not_run",
        "supported_schema_uris": dict(SUPPORTED_SCHEMAS),
    }

