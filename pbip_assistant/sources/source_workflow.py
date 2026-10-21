"""Source-only orchestration for the local raw-data UI.

This slice profiles uploaded copies of .xlsx/.csv files and deliberately has
no PBIP, AI, patch, or Power BI Desktop dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pbip_assistant.csv_source import profile_csv
from pbip_assistant.errors import InputError
from pbip_assistant.schema import compare_source_schemas
from pbip_assistant.xlsx import profile_workbook


def profile_sources_only(
    source_paths: list[str | Path],
    *,
    source_options: dict[str, dict[str, Any]] | None = None,
    include_preview: bool = False,
    preview_limit: int = 20,
) -> dict[str, Any]:
    """Profile Excel/CSV sources without requiring a PBIP project."""
    if not source_paths:
        return {
            "state": "needs_input",
            "errors": [{
                "code": "NO_SOURCES",
                "path": "",
                "detail": "Choose at least one .xlsx or .csv file",
            }],
            "workbooks": [],
            "csv_files": [],
            "schema_comparison": {
                "status": "insufficient_data",
                "baseline": None,
                "comparisons": [],
            },
        }

    options_by_path = source_options or {}
    workbooks: list[dict[str, Any]] = []
    csv_files: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for supplied in source_paths:
        path = Path(supplied)
        options = options_by_path.get(str(supplied), {})
        try:
            if path.suffix.lower() == ".xlsx":
                profile = profile_workbook(
                    path,
                    sheet_names=options.get("sheet_names"),
                    table_name=options.get("table_name"),
                    include_preview=include_preview,
                    preview_limit=preview_limit,
                )
                workbooks.append(profile)
                if not profile["sheets"] or any(
                    not sheet.get("mapping_ready", False)
                    for sheet in profile["sheets"]
                ):
                    errors.append({
                        "path": str(path),
                        "code": "XLSX_READING_NEEDS_CONFIRMATION",
                        "detail": (
                            "Workbook has an empty/invalid header or cells "
                            "beyond its header; correct the source before mapping"
                        ),
                    })
            elif path.suffix.lower() == ".csv":
                profile = profile_csv(
                    path,
                    encoding=options.get("encoding"),
                    delimiter=options.get("delimiter"),
                    header_row=options.get("header_row", 1),
                    include_preview=include_preview,
                    preview_limit=preview_limit,
                )
                csv_files.append(profile)
                if not profile["mapping_ready"]:
                    errors.append({
                        "path": str(path),
                        "code": "CSV_READING_NEEDS_CONFIRMATION",
                        "detail": (
                            "CSV contains row errors; correct or explicitly "
                            "confirm its reading before mapping"
                        ),
                    })
            else:
                raise InputError(
                    "UNSUPPORTED_SOURCE",
                    str(path),
                    "Only .xlsx and .csv sources are supported",
                )
        except (InputError, OSError) as exc:
            errors.append({
                "path": str(path),
                "code": getattr(exc, "code", "IO_ERROR"),
                "detail": getattr(exc, "detail", str(exc)),
            })

    schema_comparison = compare_source_schemas(workbooks, csv_files)
    column_count = sum(
        len(sheet.get("columns", []))
        for workbook in workbooks
        for sheet in workbook.get("sheets", [])
    ) + sum(len(item.get("columns", [])) for item in csv_files)
    row_count = sum(
        sheet.get("row_count", 0)
        for workbook in workbooks
        for sheet in workbook.get("sheets", [])
    ) + sum(item.get("row_count", 0) for item in csv_files)
    issue_count = len(errors) + sum(
        len(workbook.get("issues", []))
        + sum(
            len(sheet.get("issues", []))
            + sum(len(column.get("issues", [])) for column in sheet.get("columns", []))
            for sheet in workbook.get("sheets", [])
        )
        for workbook in workbooks
    ) + sum(len(item.get("issues", [])) for item in csv_files)

    return {
        "state": "needs_input_fix" if errors else "profile_ready",
        "errors": errors,
        "workbooks": workbooks,
        "csv_files": csv_files,
        "schema_comparison": schema_comparison,
        "summary": {
            "file_count": len(workbooks) + len(csv_files),
            "row_count": row_count,
            "column_count": column_count,
            "issue_count": issue_count,
            "mapping_ready": not errors,
        },
        "validation": {
            "source_profile": "static_pass" if not errors else "needs_input_fix",
            "ai": "not_run",
            "pbip": "not_run",
            "desktop": "not_run",
        },
    }
