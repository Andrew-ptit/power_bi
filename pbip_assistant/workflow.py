"""First BPMN slice: N-002 -> N-003, with BE-004 on invalid input."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .csv_source import profile_csv
from .errors import InputError
from .pbip import create_snapshot, inventory_pbip, snapshot_matches
from .schema import compare_source_schemas
from .xlsx import profile_workbook


def import_sources(
    pbip_root: str | Path,
    source_paths: list[str | Path],
    insight: str = "",
    *,
    csv_options: dict[str, dict[str, Any]] | None = None,
    xlsx_options: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not source_paths:
        return {"state": "needs_input_fix", "errors": [{"code": "NO_SOURCES", "detail": "Choose at least one .xlsx or .csv file"}]}
    errors = []
    workbook_profiles = []
    csv_profiles = []
    try:
        snapshot = create_snapshot(pbip_root, source_paths)
        inventory = inventory_pbip(pbip_root)
    except (InputError, OSError) as exc:
        inventory = None
        snapshot = None
        errors.append({"path": str(pbip_root), "code": getattr(exc, "code", "IO_ERROR"), "detail": str(exc)})
    for supplied in source_paths:
        path = Path(supplied)
        try:
            if path.suffix.lower() == ".xlsx":
                options = (xlsx_options or {}).get(str(supplied), {})
                profile = profile_workbook(path, **options)
                workbook_profiles.append(profile)
                if not profile["sheets"] or any(not sheet.get("mapping_ready", False) for sheet in profile["sheets"]):
                    errors.append({
                        "path": str(path),
                        "code": "XLSX_READING_NEEDS_CONFIRMATION",
                        "detail": "Workbook has an empty/invalid header or cells beyond its header; correct the source before mapping",
                    })
            elif path.suffix.lower() == ".csv":
                options = (csv_options or {}).get(str(supplied), {})
                profile = profile_csv(path, **options)
                csv_profiles.append(profile)
                if not profile["mapping_ready"]:
                    errors.append({
                        "path": str(path),
                        "code": "CSV_READING_NEEDS_CONFIRMATION",
                        "detail": "CSV contains row errors; correct or explicitly confirm its reading before mapping",
                    })
            else:
                raise InputError("UNSUPPORTED_SOURCE", str(path), "Only .xlsx and .csv sources are supported")
        except (InputError, OSError) as exc:
            errors.append({"path": str(path), "code": getattr(exc, "code", "IO_ERROR"), "detail": str(exc)})
    if errors:
        schema_comparison = compare_source_schemas(workbook_profiles, csv_profiles)
        return {
            "state": "needs_input_fix",
            "bpmn_end": "N-005",
            "errors": errors,
            "workbooks": workbook_profiles,
            "csv_files": csv_profiles,
            "schema_comparison": schema_comparison,
            "pbip": inventory,
            "insight": {"text": insight, "status": "hypothesis"} if insight else None,
        }
    if not snapshot_matches(snapshot):
        return {
            "state": "needs_input_fix",
            "bpmn_end": "N-005",
            "errors": [{"code": "SOURCE_CHANGED", "detail": "An input changed during import; rerun to create a consistent snapshot"}],
            "workbooks": workbook_profiles,
            "csv_files": csv_profiles,
            "schema_comparison": compare_source_schemas(workbook_profiles, csv_profiles),
            "pbip": inventory,
        }
    return {
        "state": "imported_needs_proposal",
        "bpmn_next": "N-006",
        "workbooks": workbook_profiles,
        "csv_files": csv_profiles,
        "schema_comparison": compare_source_schemas(workbook_profiles, csv_profiles),
        "pbip": inventory,
        "snapshot": snapshot,
        "insight": {"text": insight, "status": "hypothesis"} if insight else None,
        "validation": {"import": "static_pass", "tmdl": "not_run", "pbir": "not_run", "desktop": "not_run"},
    }
