from __future__ import annotations

import base64
from pathlib import Path
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from pbip_assistant.codex_pq import propose_m
from pbip_assistant.errors import InputError
from pbip_assistant.pq_code_m import ADVANCED_M_POLICY_ID, PQPreviewStore, _static_values_payload
from tests.test_codex_excel import workbook as used_range_workbook
from tests.test_excel_plan import FIXTURE_ROOT, office_snapshot


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


class PQCodeMTests(unittest.TestCase):
    def test_static_result_rejects_formula_and_connection(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "values.xlsx"
            FakePQRunner().apply({"resultWorkbookPath": str(path)})
            self.assertTrue(_static_values_payload(path, 3, 2))
            with ZipFile(path) as archive:
                package = {name: archive.read(name) for name in archive.namelist()}
            sheet_name = "xl/worksheets/sheet1.xml"
            package[sheet_name] = package[sheet_name].replace(
                b"<c r=\"A2\" t=\"inlineStr\"><is><t>S1</t></is></c>",
                b"<c r=\"A2\"><f>1+1</f><v>2</v></c>",
            )
            with ZipFile(path, "w", ZIP_DEFLATED) as archive:
                for name, payload in package.items():
                    archive.writestr(name, payload)
            with self.assertRaises(InputError) as error:
                _static_values_payload(path, 3, 2)
            self.assertEqual(error.exception.code, "PQ_RESULT_INVALID")
            package[sheet_name] = package[sheet_name].replace(
                b"<c r=\"A2\"><f>1+1</f><v>2</v></c>",
                b"<c r=\"A2\" t=\"inlineStr\"><is><t>S1</t></is></c>",
            )
            package["xl/connections.xml"] = b"<connections/>"
            with ZipFile(path, "w", ZIP_DEFLATED) as archive:
                for name, payload in package.items():
                    archive.writestr(name, payload)
            with self.assertRaises(InputError) as error:
                _static_values_payload(path, 3, 2)
            self.assertEqual(error.exception.code, "PQ_RESULT_INVALID")

    def test_open_workbook_sheet_receives_only_static_values(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            fixture = FIXTURE_ROOT / "excel_mcp_sales_input.xlsx"
            source_path = Path(folder) / fixture.name
            payload = fixture.read_bytes()
            source_path.write_bytes(payload)
            runner = FakePQRunner()
            store = PQPreviewStore(runner)
            try:
                result = store.preview(
                    workbook=office_snapshot(source_path),
                    selection={"kind": "table", "sheet": "Sales", "name": "SalesTable"},
                    m_code='let Source = Excel.CurrentWorkbook(){[Name="SalesTable"]}[Content] in Source',
                    risk_accepted=True, risk_policy_id=ADVANCED_M_POLICY_ID,
                    workbook_base64=base64.b64encode(payload).decode("ascii"),
                    values_for_open_workbook=True,
                )
                self.assertEqual(result["status"], "ready_for_open_workbook")
                self.assertEqual(result["resultWorkbookSheetName"], "PQ_Result_Values")
                self.assertNotIn("destination", result)
                self.assertFalse(list(Path(folder).glob("*_PQ_clean_*.xlsx")))
                self.assertEqual(source_path.read_bytes(), payload)
                self.assertFalse(list(Path(store._temp.name).glob("*.xlsx")))
                self.assertTrue(result["resultWorkbookBase64"])
            finally:
                store.close()

    def test_unsaved_and_invalid_url_do_not_become_remote_workbooks(self) -> None:
        from pbip_assistant.pq_code_m import _destination

        for url, expected in [("", "WORKBOOK_UNSAVED"), ("ftp://example.com/a.xlsx", "REMOTE_WORKBOOK_UNSUPPORTED"), ("https:///a.xlsx", "INVALID_WORKBOOK")]:
            with self.subTest(url=url), self.assertRaises(InputError) as error:
                _destination({"name": "a.xlsx", "url": url})
            self.assertEqual(error.exception.code, expected)
        destination, source = _destination({"name": "a.xlsx", "url": "https://tenant.sharepoint.com/a.xlsx"})
        self.assertIsNone(source)
        self.assertEqual(destination.parent.name, "LocalDataCopilot")

    def test_proposal_uses_selected_bounded_source_and_does_not_run_m(self) -> None:
        runner = FakeMProposal()
        source = {"kind": "sheet", "sheet": "Raw_Orders"}
        result = propose_m("Bỏ dòng rỗng", used_range_workbook(), source, runner)
        self.assertIn("PQ_Input", result["mCode"])
        self.assertEqual(runner.payload["sourceAlias"], "PQ_Input")
        self.assertEqual(len(runner.payload["selectedSource"]["rows"]), 1)
        self.assertNotIn("url", str(runner.payload))
        self.assertFalse(result["canRunWithoutRiskAcknowledgement"])

    def test_preview_requires_risk_ack_and_save_requires_exact_revision(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            fixture = FIXTURE_ROOT / "excel_mcp_sales_input.xlsx"
            source_path = Path(folder) / fixture.name
            payload = fixture.read_bytes()
            source_path.write_bytes(payload)
            workbook = office_snapshot(source_path)
            encoded = base64.b64encode(payload).decode("ascii")
            selection = {"kind": "table", "sheet": "Sales", "name": "SalesTable"}
            code = 'let Source = Excel.CurrentWorkbook(){[Name="SalesTable"]}[Content] in Source'
            runner = FakePQRunner()
            store = PQPreviewStore(runner)
            try:
                with self.assertRaises(InputError) as error:
                    store.preview(
                        workbook=workbook, selection=selection, m_code=code,
                        risk_accepted=False, risk_policy_id=ADVANCED_M_POLICY_ID,
                        workbook_base64=encoded,
                    )
                self.assertEqual(error.exception.code, "PQ_RISK_ACK_REQUIRED")
                self.assertEqual(runner.requests, [])
                with self.assertRaises(InputError) as error:
                    store.preview(
                        workbook=workbook, selection=selection, m_code=code,
                        risk_accepted=True, risk_policy_id="advanced-m-trusted-v0",
                        workbook_base64=encoded,
                    )
                self.assertEqual(error.exception.code, "PQ_RISK_POLICY_STALE")
                self.assertEqual(runner.requests, [])
                preview = store.preview(
                    workbook=workbook, selection=selection, m_code=code,
                    risk_accepted=True, risk_policy_id=ADVANCED_M_POLICY_ID,
                    workbook_base64=encoded,
                )
                self.assertEqual(preview["status"], "excel_preview")
                self.assertEqual(preview["resultRows"], 3)
                self.assertTrue(preview["sourceUnchanged"])
                destination = Path(preview["destination"])
                self.assertFalse(destination.exists())
                with self.assertRaises(InputError) as error:
                    store.save(
                        preview_id=preview["previewId"], m_code=code + " ",
                        selection=selection, workbook_base64=encoded,
                    )
                self.assertEqual(error.exception.code, "PREVIEW_STALE")
                self.assertFalse(destination.exists())
                saved = store.save(
                    preview_id=preview["previewId"], m_code=code,
                    selection=selection, workbook_base64=encoded,
                )
                self.assertEqual(saved["status"], "saved_copy")
                self.assertTrue(destination.is_file())
                self.assertEqual(source_path.read_bytes(), payload)
                with self.assertRaises(InputError) as error:
                    store.save(
                        preview_id=preview["previewId"], m_code=code,
                        selection=selection, workbook_base64=encoded,
                    )
                self.assertEqual(error.exception.code, "PREVIEW_STALE")
                later = store.preview(
                    workbook=workbook, selection=selection, m_code=code,
                    risk_accepted=True, risk_policy_id=ADVANCED_M_POLICY_ID,
                    workbook_base64=encoded,
                )
                source_path.write_bytes(payload + b"changed")
                with self.assertRaises(InputError) as error:
                    store.save(
                        preview_id=later["previewId"], m_code=code,
                        selection=selection, workbook_base64=encoded,
                    )
                self.assertEqual(error.exception.code, "PREVIEW_STALE")
                self.assertFalse(Path(later["destination"]).exists())
            finally:
                store.close()

    def test_old_preview_is_evicted_without_blocking_new_previews(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            fixture = FIXTURE_ROOT / "excel_mcp_sales_input.xlsx"
            source_path = Path(folder) / fixture.name
            payload = fixture.read_bytes()
            source_path.write_bytes(payload)
            workbook = office_snapshot(source_path)
            encoded = base64.b64encode(payload).decode("ascii")
            selection = {"kind": "table", "sheet": "Sales", "name": "SalesTable"}
            code = 'let Source = Excel.CurrentWorkbook(){[Name="SalesTable"]}[Content] in Source'
            store = PQPreviewStore(FakePQRunner())
            try:
                previews = [store.preview(
                    workbook=workbook, selection=selection, m_code=code,
                    risk_accepted=True, risk_policy_id=ADVANCED_M_POLICY_ID,
                    workbook_base64=encoded,
                ) for _ in range(6)]
                with self.assertRaises(InputError) as error:
                    store.save(
                        preview_id=previews[0]["previewId"], m_code=code,
                        selection=selection, workbook_base64=encoded,
                    )
                self.assertEqual(error.exception.code, "PREVIEW_STALE")
                self.assertEqual(len(store._sessions), 5)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
