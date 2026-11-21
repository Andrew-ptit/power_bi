"""Golden chọn lọc, đối soát thật và nguồn bất biến của WL5."""

import ast
from copy import deepcopy
from decimal import Decimal
import hashlib
import io
from pathlib import Path
import socket
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_preview import (
    build_preview, build_workbook, preview_marker, result_digest, result_rows, temp_workspace,
)
from pbip_assistant.sources.assistant_reconcile import assert_approvable, build_reconciliation
from tests.support.paths import ROOT
from tests.unit.test_assistant_preview import marker, pipeline, read_source_evidence
from tests.unit.test_assistant_reconcile import add_eur, replace_rate
from tests.unit.test_assistant_spec import create, load, model


FIELDS = ("rowsIn", "rowsInDeduped", "rowsOut", "colsIn", "colsOut", "controlTotalRawSource",
          "droppedByDedupe", "controlTotalSource", "controlTotalResult", "controlTotalTolerance",
          "controlTotalPassed", "passed", "bridge")


def inspect_files(paths):
    return {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns,
                   path.stat().st_size) for path in paths}


def preview_for(data, scenario):
    ingested, spec, _, _, result = data
    sheet = "PnL_Preview" if scenario == "tp-fin" else "Sales_Preview"
    return build_preview(result, spec, ingested[1], sheet=sheet, marker=marker(spec, sheet))


class AssistantWL5ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = {scenario: pipeline(scenario) for scenario in ("tp-fin", "tp-sales")}
        cls.previews = {scenario: preview_for(data, scenario) for scenario, data in cls.models.items()}
        cls.reconciliations = {
            scenario: build_reconciliation(cls.previews[scenario], data[1], data[0][0]["tables"], data[-1])
            for scenario, data in cls.models.items()
        }

    def assert_baseline(self, scenario, dimensions):
        data = self.models[scenario]
        preview = self.previews[scenario]
        expected = load(scenario, "wl5_preview.json")
        self.assertEqual(set(preview), set(expected))
        self.assertEqual(preview["sheets"], expected["sheets"])
        self.assertEqual(preview["counts"], expected["counts"])
        for field in ("sheet", "mode", "workbook"):
            self.assertEqual(preview["target"][field], expected["target"][field])
        self.assertEqual(preview["specFingerprint"], data[1]["fingerprint"])
        self.assertEqual((len(data[-1]["rows"]), len(data[-1]["columns"])), dimensions)
        self.assertIn("|spec=" + data[1]["fingerprint"], preview["target"]["marker"])
        self.assertIn("|preview=" + result_digest(data[-1]), preview["target"]["marker"])
        self.assertIn("|labels=" + ",".join(data[1]["labels"]), preview["target"]["marker"])
        self.assertEqual(set(data[1]["labels"]), set(load(scenario, "wl5_reconciliation.json")["labels"]))
        actual = self.reconciliations[scenario]
        golden = load(scenario, "wl5_reconciliation.json")
        for field in FIELDS:
            self.assertEqual(actual[field], golden[field], scenario + ": " + field)
        self.assertEqual([check["id"] for check in actual["checks"]],
                         [check["id"] for check in golden["checks"]])
        self.assertEqual(set(actual["labels"]), set(golden["labels"]))
        self.assertEqual(actual["blockers"], [])
        assert_approvable(actual)

    def test_golden_fin_preview_and_all_reconciliation_numeric_fields(self):
        self.assert_baseline("tp-fin", (23, 9))

    def test_golden_sales_preview_and_all_reconciliation_numeric_fields(self):
        self.assert_baseline("tp-sales", (4, 4))

    def test_golden_source_fingerprints_from_verified_original_evidence(self):
        for scenario, data in self.models.items():
            snapshot = load(scenario, "wl1_snapshot.json")
            brief = load(scenario, "wl3_brief.json")
            decision_model = model(scenario, brief=brief)
            spec = create(decision_model, scenario)
            result = result_rows(data[0][0]["tables"], spec, decision_model[1], decision_model[2])
            sheet = self.previews[scenario]["target"]["sheet"]
            evidence = read_source_evidence(scenario)
            preview = build_preview(result, spec, snapshot, sheet=sheet, marker=marker(spec, sheet),
                                    source_evidence=evidence)
            self.assertEqual(preview["source"], load(scenario, "wl5_preview.json")["source"])
            self.assertEqual(preview["specFingerprint"], spec["fingerprint"])

    def test_af_ex_001_source_bytes_mtime_and_temp_cleanup_success_and_error(self):
        fixture = ROOT / "tests/fixtures/assistant"
        paths = [p for scenario in self.models for p in (fixture / scenario / "source").rglob("*.csv")]
        paths += [fixture / scenario / "wl1_snapshot.json" for scenario in self.models]
        before = inspect_files(paths)
        evidence = {scenario: read_source_evidence(scenario) for scenario in self.models}
        original_open = Path.open
        def guarded(path, *args, **kwargs):
            if path in paths:
                raise AssertionError("Engine WL5 không được mở lại nguồn")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", guarded):
            for scenario, data in self.models.items():
                result = result_rows(data[0][0]["tables"], data[1], data[2], data[3])
                sheet = self.previews[scenario]["target"]["sheet"]
                preview = build_preview(result, data[1], data[0][1], sheet=sheet,
                                        marker=marker(data[1], sheet), source_evidence=evidence[scenario])
                with temp_workspace() as directory:
                    self.assertFalse(directory.resolve().is_relative_to(ROOT.resolve()))
                    target = directory / "preview.xlsx"
                    payload = build_workbook(**result, sheet=sheet, marker=preview["target"]["marker"])
                    target.write_bytes(payload)
                    self.assertEqual(target.read_bytes(), payload)
                self.assertFalse(directory.exists())
                with self.assertRaisesRegex(RuntimeError, "synthetic"):
                    with temp_workspace() as failed:
                        (failed / "preview.xlsx").write_bytes(payload)
                        raise RuntimeError("synthetic")
                self.assertFalse(failed.exists())
        self.assertEqual(inspect_files(paths), before)

    def test_af_ex_002_workbook_values_only_header_marker_fixed_zip_timestamps(self):
        for scenario, data in self.models.items():
            preview = self.previews[scenario]
            payload = build_workbook(**data[-1], sheet=preview["target"]["sheet"], marker=preview["target"]["marker"])
            with ZipFile(io.BytesIO(payload)) as archive:
                names = archive.namelist()
                self.assertTrue(all(info.date_time == (2026, 1, 1, 0, 0, 0) for info in archive.infolist()))
                self.assertFalse(any(name.lower().startswith(("xl/querytables/", "xl/externallinks/"))
                                     or name.lower() == "xl/connections.xml" for name in names))
                roots = [ET.fromstring(archive.read(name)) for name in names if name.endswith(".xml")]
                self.assertFalse(any(node.tag.rsplit("}", 1)[-1] == "f" for root in roots for node in root.iter()))
                worksheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
                ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                header = worksheet.find("m:sheetData/m:row", ns)
                self.assertEqual(header.get("r"), "1")
                self.assertEqual([node.text for node in header.findall(".//m:t", ns)], data[-1]["columns"])
                texts = [node.text for root in roots for node in root.iter()]
                self.assertIn(preview["target"]["marker"], texts)
                self.assertEqual(self.previews[scenario]["counts"],
                                 {"formulaCount": 0, "queryCount": 0, "connectionCount": 0})

    def test_af_ex_003_row_and_column_changes_are_numeric_and_checked(self):
        for scenario, actual in self.reconciliations.items():
            self.assertTrue(all(type(actual[key]) is int for key in ("rowsIn", "rowsInDeduped", "rowsOut", "colsIn", "colsOut")))
            row_check = actual["checks"][0]
            self.assertEqual(row_check["id"], "row_count")
            self.assertTrue(row_check["passed"])
            for count in (actual["rowsIn"], actual["rowsInDeduped"], actual["rowsOut"], actual["colsIn"], actual["colsOut"]):
                self.assertIn(str(count), row_check["detail"])

    def test_temp_workbook_readback_cells_and_money_match_reconciled_result(self):
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for scenario, data in self.models.items():
            preview = self.previews[scenario]
            payload = build_workbook(**data[-1], sheet=preview["target"]["sheet"],
                                     marker=preview["target"]["marker"])
            with temp_workspace() as directory:
                target = directory / "readback.xlsx"
                target.write_bytes(payload)
                with ZipFile(target) as archive:
                    root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
                    xml_rows = root.findall("m:sheetData/m:row", ns)
                    readback = []
                    for xml_row, expected in zip(xml_rows[1:1 + len(data[-1]["rows"])], data[-1]["rows"], strict=True):
                        cells = xml_row.findall("m:c", ns)
                        self.assertEqual(len(cells), len(expected))
                        values = []
                        for cell, value in zip(cells, expected, strict=True):
                            if isinstance(value, (Decimal, int)):
                                self.assertIsNone(cell.get("t"))
                                values.append(Decimal(cell.find("m:v", ns).text))
                            else:
                                self.assertEqual(cell.get("t"), "inlineStr")
                                values.append(cell.find("m:is/m:t", ns).text)
                        self.assertEqual(values, expected)
                        readback.append(values)
                    index = 4 if scenario == "tp-fin" else 1
                    self.assertEqual(sum((row[index] for row in readback), Decimal("0")),
                                     Decimal(self.reconciliations[scenario]["controlTotalResult"]))
            self.assertFalse(directory.exists())

    def test_af_ex_004_control_source_raw_dedupe_result_identity_is_exact(self):
        for actual in self.reconciliations.values():
            self.assertEqual(Decimal(actual["controlTotalRawSource"]) - Decimal(actual["droppedByDedupe"]),
                             Decimal(actual["controlTotalSource"]))
            self.assertEqual(Decimal(actual["controlTotalSource"]), Decimal(actual["controlTotalResult"]))
            self.assertEqual(actual["controlTotalTolerance"], "0.01")
            self.assertTrue(actual["controlTotalPassed"])

    def test_af_ex_005_bridge_decimal_identity_and_sales_not_applicable(self):
        bridge = self.reconciliations["tp-fin"]["bridge"]
        self.assertEqual(Decimal(bridge["op"]) + Decimal(bridge["fx"]), Decimal(bridge["total"]))
        self.assertEqual(Decimal(bridge["total"]), Decimal(bridge["variance"]))
        self.assertEqual(self.reconciliations["tp-sales"]["bridge"], load("tp-sales", "wl5_reconciliation.json")["bridge"])

    def test_af_ex_006_injected_drift_matches_variant_and_blocks_approval(self):
        data = self.models["tp-fin"]
        actual = build_reconciliation(self.previews["tp-fin"], data[1], data[0][0]["tables"], data[-1],
                                      injected_drift=Decimal("1234560"))
        variant = load("variants", "fin_reconcile_control_drift.json")
        for field in FIELDS:
            self.assertEqual(actual[field], variant[field], field)
        self.assertFalse(actual["checks"][1]["passed"])
        self.assertEqual(actual["blockers"][0]["code"], variant["blockers"][0]["code"])
        with self.assertRaises(InputError) as caught:
            assert_approvable(actual)
        self.assertEqual(caught.exception.code, "AF_RECONCILE_FAILED")

    def test_af_ex_007_preview_reconcile_and_workbook_determinism_with_recompute(self):
        for scenario, data in self.models.items():
            repeated = preview_for(data, scenario)
            self.assertEqual(repeated, self.previews[scenario])
            for artifact, field in ((repeated, "previewHash"), (self.reconciliations[scenario], "reconcileHash")):
                self.assertEqual(artifact[field], canonical_hash({k: artifact[k] for k in artifact["hashBasis"]}))
            again = build_reconciliation(repeated, data[1], data[0][0]["tables"], data[-1])
            self.assertEqual(again, self.reconciliations[scenario])
            args = {**data[-1], "sheet": repeated["target"]["sheet"], "marker": repeated["target"]["marker"]}
            self.assertEqual(build_workbook(**args), build_workbook(**args))

    def test_antifake_deleting_result_row_fails_real_control_and_approval(self):
        data = self.models["tp-fin"]
        result = deepcopy(data[-1])
        index = next(i for i, row in enumerate(result["rows"]) if row[4] != 0)
        result["rows"].pop(index)
        actual = build_reconciliation(self.previews["tp-fin"], data[1], data[0][0]["tables"], result)
        self.assertFalse(actual["passed"])
        self.assertFalse(actual["controlTotalPassed"])
        self.assertFalse(actual["checks"][0]["passed"])
        with self.assertRaises(InputError):
            assert_approvable(actual)

    def test_antifake_rate_mutation_changes_fx_total_payload_hash_and_keeps_bridge_closed(self):
        data, spec, decisions, pack, original = self.models["tp-fin"]
        raw = deepcopy(data[0]["tables"])
        replace_rate(raw)
        changed = result_rows(raw, spec, decisions, pack)
        preview = build_preview(changed, spec, data[1], sheet="PnL_Preview", marker=marker(spec, "PnL_Preview"))
        actual = build_reconciliation(preview, spec, raw, changed)
        baseline = self.reconciliations["tp-fin"]["bridge"]
        bridge = actual["bridge"]
        expected_delta = Decimal(baseline["actualUsd"]) * Decimal("-300")
        self.assertEqual(Decimal(bridge["fx"]) - Decimal(baseline["fx"]), expected_delta)
        self.assertEqual(Decimal(bridge["total"]) - Decimal(baseline["total"]), expected_delta)
        self.assertEqual(bridge["op"], baseline["op"])
        self.assertEqual(Decimal(bridge["op"]) + Decimal(bridge["fx"]), Decimal(bridge["total"]))
        self.assertEqual(bridge["total"], bridge["variance"])
        self.assertNotEqual(preview["previewHash"], self.previews["tp-fin"]["previewHash"])
        self.assertNotEqual(result_digest(changed), result_digest(original))
        self.assertTrue(actual["passed"])

    def test_antifake_used_missing_average_rate_is_blocker_even_when_eur_nets_zero(self):
        data = self.models["tp-fin"]
        raw = deepcopy(data[0][0]["tables"])
        add_eur(raw)
        actual = build_reconciliation(self.previews["tp-fin"], data[1], raw, data[-1])
        variant = load("variants", "fin_rate_missing_blocker.json")
        self.assertEqual(actual["passed"], variant["passed"])
        self.assertTrue(any(item["code"] == variant["blockers"][0]["code"] and item["severity"] == "blocker"
                            for item in actual["blockers"]))
        self.assertIsNone(actual["controlTotalSource"])
        with self.assertRaises(InputError):
            assert_approvable(actual)

    def test_antifake_unused_average_and_missing_closing_are_warnings_only(self):
        data = self.models["tp-fin"]
        raw = deepcopy(data[0][0]["tables"])
        rates = next(t for t in raw if "RateType" in t["header"])
        fields = rates["header"]
        rates["rows"] = [row for row in rates["rows"] if row[fields.index("RateType")] != "closing"]
        actual = build_reconciliation(self.previews["tp-fin"], data[1], raw, data[-1])
        variant = load("variants", "fin_rate_closing_missing_warning.json")
        self.assertEqual(actual["passed"], variant["passed"])
        self.assertEqual(actual["blockers"], variant["blockers"])
        self.assertTrue(any("average" in w["message"] for w in actual["warnings"]))
        self.assertTrue(any("closing" in w["message"] for w in actual["warnings"]))
        self.assertTrue(all(w["severity"] == "warning" for w in actual["warnings"]))
        assert_approvable(actual)

    def test_payload_and_source_evidence_tampering_cannot_pass_unchanged_preview(self):
        data = self.models["tp-sales"]
        changed = deepcopy(data[-1])
        changed["rows"][0][2] += 1
        actual = build_reconciliation(self.previews["tp-sales"], data[1], data[0][0]["tables"], changed)
        self.assertFalse(actual["passed"])
        evidence = read_source_evidence("tp-sales")
        evidence[next(iter(evidence))] += "\n"
        with self.assertRaises(InputError) as caught:
            build_preview(data[-1], data[1], data[0][1], sheet="Sales_Preview", marker=marker(data[1], "Sales_Preview"),
                          source_evidence=evidence)
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_engine_offline_no_ai_com_or_source_open_and_no_raw_evidence_in_artifact(self):
        forbidden = {"openai", "requests", "http", "urllib", "socket", "subprocess", "win32com", "ctypes"}
        for name in ("assistant_preview", "assistant_reconcile"):
            source = (ROOT / "pbip_assistant/sources" / (name + ".py")).read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Import):
                    self.assertFalse({a.name.split(".")[0] for a in node.names} & forbidden)
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or "").split(".")[0], forbidden)
            self.assertNotIn(".artifacts", source)
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Không được gọi network")):
            for scenario, data in self.models.items():
                preview = preview_for(data, scenario)
                actual = build_reconciliation(preview, data[1], data[0][0]["tables"], data[-1])
                self.assertTrue(actual["passed"])
                self.assertNotIn("source_evidence", preview)


if __name__ == "__main__":
    unittest.main()
