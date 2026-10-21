from __future__ import annotations

import base64
from pathlib import Path
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from pbip_assistant.codex_pq import propose_m
from pbip_assistant.errors import InputError
from pbip_assistant.pq_code_m import ADVANCED_M_POLICY_ID, PQPreviewStore, _static_values_payload
from tests.support.codex_excel import workbook as used_range_workbook
from tests.support.excel_plan import FIXTURE_ROOT, office_snapshot


class FakeMProposal:
    def __init__(self) -> None:
        self.payload = None

    def propose(self, payload: dict) -> dict:
        self.payload = payload
        return {
            "summary": "Bỏ dòng rỗng và dòng trùng.",
            "mCode": 'let Source = Excel.CurrentWorkbook(){[Name="PQ_Input"]}[Content] in Source',
            "warnings": [],
        }


class FakePQRunner:
    def __init__(self) -> None:
        self.requests = []

    def apply(self, request: dict) -> dict:
        self.requests.append(request)
        if "resultWorkbookPath" in request:
            with ZipFile(request["resultWorkbookPath"], "w", ZIP_DEFLATED) as archive:
                archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
                archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
                archive.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="PQ_Result_Values" sheetId="1" r:id="rId1"/></sheets></workbook>')
                archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
                archive.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>SaleID</t></is></c><c r="B1" t="inlineStr"><is><t>Region</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>S1</t></is></c><c r="B2" t="inlineStr"><is><t>North</t></is></c></row><row r="3"><c r="A3" t="inlineStr"><is><t>S2</t></is></c><c r="B3" t="inlineStr"><is><t>South</t></is></c></row><row r="4"><c r="A4" t="inlineStr"><is><t>S3</t></is></c><c r="B4" t="inlineStr"><is><t>East</t></is></c></row></sheetData></worksheet>')
        return {
            "ok": True, "sourceRows": 5, "resultRows": 3, "resultColumns": 2,
            "columns": ["SaleID", "Region"],
            "rows": [["S1", "North"], ["S2", "South"], ["S3", "East"]],
            "queryName": "PQ_Code_M_Result", "resultSheet": "PQ_Result", "excelVersion": "16.0",
        }


