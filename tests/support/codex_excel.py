from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pbip_assistant.codex_excel import analyze_workbook, find_codex_executable
from pbip_assistant.errors import InputError


class FakeCodex:
    def __init__(self, response: dict | None = None) -> None:
        self.payload = None
        self.response = response or {
            "summary": "Tách mã theo dấu gạch ngang sau khi kiểm tra cấu trúc.",
            "questions": [],
            "assumptions": ["Dấu gạch ngang phân tách ba thành phần."],
            "warnings": ["Một số dòng có thể chứa nhiều dấu gạch ngang."],
            "codeBlocks": [{
                "language": "m", "label": "Làm sạch đơn hàng",
                "code": "let Source = Excel.CurrentWorkbook(){[Name=\"PQ_Input\"]}[Content] in Source",
            }],
            "operations": [{
                "targetSheet": "Raw_Orders",
                "targetColumn": "Mã Phân Bổ (Prefix)",
                "formula": "=TEXTBEFORE(B2;\"-\")",
                "reason": "Lấy thành phần đầu.",
            }],
        }

    def analyze(self, payload: dict) -> dict:
        self.payload = payload
        return self.response


def workbook() -> dict:
    return {
        "name": "logistics.xlsx",
        "url": "https://tenant.sharepoint.com/private/workbook.xlsx",
        "activeSheet": "Raw_Orders",
        "tables": [],
        "sheets": [{
            "name": "Raw_Orders",
            "headerRow": 1,
            "columnLetters": ["A", "B", "D"],
            "headers": ["Ngày Giao", "Mã đơn hàng thô", "Mã Phân Bổ (Prefix)"],
            "rows": [["15/10/2024", "SPENTA-123", ""]],
        }],
    }


