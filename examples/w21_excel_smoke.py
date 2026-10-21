"""Run the W-21 connector against the synthetic fixture in isolated Excel.

The source and result are created inside a temporary directory by default, so
no user workbook or currently open Excel process is targeted.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile

from pbip_assistant.excel_connector import PowerShellExcelRunner, apply_export_to_copy
from pbip_assistant.excel_plan import create_fixture_plan
from pbip_assistant.xlsx import profile_workbook


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "excel"


def _snapshot(path: Path) -> dict:
    profile = profile_workbook(path, include_preview=True, preview_limit=20)
    tables = []
    for sheet in profile["sheets"]:
        preview_rows = sheet.get("preview", {}).get("rows", [])
        for table in sheet["tables"]:
            tables.append({
                "sheet": sheet["name"],
                "name": table["name"],
                "headers": table["columns"],
                "rows": preview_rows,
            })
    return {
        "name": path.name,
        "url": path.resolve().as_uri(),
        "activeSheet": "Sales",
        "tables": tables,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="Keep the isolated source/copy here for inspection")
    args = parser.parse_args()
    context = (
        nullcontext(args.output_dir.resolve())
        if args.output_dir
        else tempfile.TemporaryDirectory(prefix="w21-excel-smoke-", ignore_cleanup_errors=True)
    )
    with context as folder_value:
        folder = Path(folder_value)
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / "excel_mcp_sales_input.xlsx"
        workbook_bytes = (FIXTURE_ROOT / source.name).read_bytes()
        source.write_bytes(workbook_bytes)
        manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
        workbook = _snapshot(source)
        plan = create_fixture_plan(manifest["prompt"], workbook)
        result = apply_export_to_copy(
            workbook=workbook,
            workbook_bytes=workbook_bytes,
            plan=plan,
            runner=PowerShellExcelRunner(),
        )
        report = {
            "status": result["status"],
            "sourceSha256Unchanged": result["source"]["sha256Unchanged"],
            "copyName": result["copy"]["name"],
            "copyBytes": result["copy"]["bytes"],
            "excelVersion": result["runtime"].get("excelVersion"),
            "rowCount": len(result["runtime"].get("rows", [])),
            "formulaErrorCount": len(result["runtime"].get("formulaErrors", [])),
            "manifestMatched": result["reconciliation"]["matched"],
            "keptOutputDirectory": str(folder) if args.output_dir else None,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "excel_runtime_verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
