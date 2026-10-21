from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.excel_connector import PowerShellExcelRunner, apply_export_to_copy, decode_workbook_export
from pbip_assistant.excel_plan import create_fixture_plan
from tests.support.excel_plan import FIXTURE_ROOT, office_snapshot


class FakeExcelRunner:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.requests: list[dict] = []

    def apply(self, request: dict) -> dict:
        self.requests.append(request)
        return {
            "ok": True,
            "connector": "fake",
            "excelVersion": "test",
            "calculationState": "done",
            "changedTargets": [operation["target"] for operation in request["operations"]],
            "formulas": {operation["targetColumn"]: operation["formula"] for operation in request["operations"]},
            "rows": self.rows,
            "formulaErrors": [],
        }


