"""Cross-source schema comparison for already-profiled Excel and CSV inputs."""

from __future__ import annotations

from typing import Any


def _types(column: dict[str, Any]) -> list[str]:
    normalized = {"number" if value == "integer" else value for value in column.get("data_types", {})}
    return sorted(normalized)


def compare_source_schemas(
    workbooks: list[dict[str, Any]], csv_files: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare every sheet/CSV with the first available source schema."""
    entries: list[dict[str, Any]] = []
    for workbook in workbooks:
        for sheet in workbook.get("sheets", []):
            entries.append({
                "kind": "xlsx", "path": workbook.get("path", ""), "name": sheet.get("name", ""),
                "columns": sheet.get("columns", []),
            })
    for csv_file in csv_files:
        entries.append({
            "kind": "csv", "path": csv_file.get("path", ""), "name": None,
            "columns": csv_file.get("columns", []),
        })
    if not entries:
        return {"status": "insufficient_data", "baseline": None, "comparisons": []}

    baseline = entries[0]
    baseline_names = [column.get("name", "") for column in baseline["columns"]]
    baseline_types = {column.get("name", ""): _types(column) for column in baseline["columns"]}
    comparisons: list[dict[str, Any]] = []
    has_drift = False
    for entry in entries:
        names = [column.get("name", "") for column in entry["columns"]]
        current_types = {column.get("name", ""): _types(column) for column in entry["columns"]}
        shared = set(baseline_names) & set(names)
        comparison = {
            "kind": entry["kind"], "path": entry["path"], "name": entry["name"],
            "missing_columns": [name for name in baseline_names if name not in names],
            "added_columns": [name for name in names if name not in baseline_names],
            "order_changed": [name for name in names if name in shared] != [name for name in baseline_names if name in shared],
            "type_changes": {
                name: {"baseline": baseline_types[name], "current": current_types[name]}
                for name in sorted(shared) if baseline_types[name] != current_types[name]
            },
        }
        has_drift |= any((
            comparison["missing_columns"], comparison["added_columns"],
            comparison["order_changed"], comparison["type_changes"],
        ))
        comparisons.append(comparison)
    return {
        "status": "schema_drift" if has_drift else "consistent",
        "baseline": {
            "kind": baseline["kind"], "path": baseline["path"], "name": baseline["name"],
            "columns": baseline_names,
        },
        "comparisons": comparisons,
    }
