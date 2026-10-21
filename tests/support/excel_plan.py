from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.excel_plan import OPERATIONS, create_fixture_plan, local_source_path, validate_current_plan
from pbip_assistant.xlsx import profile_workbook


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "excel"


def office_snapshot(path: Path) -> dict:
    profile = profile_workbook(path, include_preview=True, preview_limit=20)
    tables = []
    for sheet in profile["sheets"]:
        rows = sheet.get("preview", {}).get("rows", [])
        for table in sheet["tables"]:
            tables.append({
                "sheet": sheet["name"],
                "name": table["name"],
                "headers": table["columns"],
                "rows": rows,
            })
    return {
        "name": path.name,
        "url": path.resolve().as_uri(),
        "activeSheet": "Sales",
        "tables": tables,
    }


