"""Golden WL6 và bảy phép kiểm chống ghi giả trên workbook bytes synthetic."""

import ast
import builtins
from copy import deepcopy
from decimal import Decimal
import hashlib
import io
import socket
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZipInfo, ZIP_STORED

from pbip_assistant.errors import InputError
from pbip_assistant.sources import assistant_apply as engine
from pbip_assistant.sources.assistant_apply import apply_result, read_result_sheet, verify_values_only
from pbip_assistant.sources.assistant_approval import (
    approval_state, consume_approval, issue_approval, validate_approval,
)
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_preview import build_preview, temp_workspace
from pbip_assistant.sources.assistant_reconcile import assert_approvable, build_reconciliation
from tests.support.paths import FIXTURES, ROOT
from tests.unit.test_assistant_preview import marker, pipeline, read_source_evidence
from tests.unit.test_assistant_spec import load


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
META = {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
SOURCE = FIXTURES / "source/orders_synthetic.xlsx"
BASIS = {"specFingerprint", "previewHash", "approval", "target", "written", "source",
         "workbookSaved", "labels", "appliedAt", "variantOf", "variantReason"}


def parts(payload):
    with ZipFile(io.BytesIO(payload)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def package(values):
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        for name, value in values.items():
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            archive.writestr(info, value)
    return stream.getvalue()


def file_state(paths):
    return {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns,
                   path.stat().st_size) for path in paths}


class AssistantWL6ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_bytes()
        cls.original = parts(cls.source)
        cls.models = {}
        for scenario in ("tp-fin", "tp-sales"):
            data, spec, decisions, pack, result = pipeline(scenario)
            evidence = read_source_evidence(scenario)
            sheet = "PnL_Preview" if scenario == "tp-fin" else "Sales_Preview"
            preview = build_preview(result, spec, data[1], sheet=sheet,
                                    marker=marker(spec, sheet), source_evidence=evidence)
            reconciliation = build_reconciliation(preview, spec, data[0]["tables"], result)
            assert_approvable(reconciliation)
            cls.models[scenario] = {"data": data, "spec": spec, "preview": preview,
                                    "result": result, "reconciliation": reconciliation}

    def request(self, scenario="tp-fin", **changes):
        data = self.models[scenario]
        golden = load(scenario, "wl6_apply.json")
        spec, preview = data["spec"], data["preview"]
        target = golden["target"]["sheet"]
        approval = issue_approval(spec, preview, approved_by="user",
                                  approved_at=golden["approval"]["approvedAt"])
        values = {"result": deepcopy(data["result"]), "target_sheet": target,
                  "marker": ("LOCAL_DATA_COPILOT|" + target + "|spec=" + spec["fingerprint"] +
                             "|preview=" + preview["previewHash"] + "|labels=" + ",".join(spec["labels"])),
                  "labels": list(spec["labels"]), "approval": approval,
                  "spec": spec, "preview": preview, "applied_at": golden["appliedAt"]}
        values.update(changes)
        return values

    def assert_partial(self, action):
        with self.assertRaises(InputError) as caught:
            action()
        self.assertEqual(caught.exception.code, "AF_WRITE_PARTIAL")

    def assert_golden(self, scenario, shape):
        request = self.request(scenario)
        actual = apply_result(self.source, **request)["apply"]
        golden = load(scenario, "wl6_apply.json")
        self.assertEqual(set(actual), set(golden))
        for key in ("approvedBy", "singleUse", "consumed"):
            self.assertEqual(actual["approval"][key], golden["approval"][key])
        self.assertEqual(actual["approval"]["boundTo"],
                         {"specFingerprint": request["spec"]["fingerprint"],
                          "previewHash": request["preview"]["previewHash"]})
        self.assertRegex(actual["approval"]["approvalId"], r"^apr_[a-f0-9]{12}$")
        for key in ("workbook", "sheet", "mode", "writeMode"):
            self.assertEqual(actual["target"][key], golden["target"][key])
        self.assertEqual(actual["target"]["marker"], request["marker"])
        self.assertEqual(actual["written"], golden["written"])
        self.assertEqual(actual["written"], {"rowCount": shape[0], "columnCount": shape[1]})
        self.assertEqual(actual["source"], golden["source"])
        self.assertEqual(actual["source"], {**request["preview"]["source"], "sheetsWritten": []})
        self.assertIs(actual["workbookSaved"], False)
        self.assertEqual(set(actual["labels"]), set(golden["labels"]))
        self.assertEqual(actual["specFingerprint"], request["spec"]["fingerprint"])
        self.assertEqual(actual["previewHash"], request["preview"]["previewHash"])
        self.assertEqual(actual["appliedAt"], request["applied_at"])

    def test_golden_fin_apply_fields_from_full_runtime_flow(self):
        self.assert_golden("tp-fin", (23, 9))

    def test_golden_sales_apply_fields_from_full_runtime_flow(self):
        self.assert_golden("tp-sales", (4, 4))

    def test_af_ap_001_explicit_approval_binds_current_spec_and_preview(self):
        for scenario in self.models:
            request = self.request(scenario)
            approval = request["approval"]
            self.assertEqual(approval_state(approval), {"consumed": False, "singleUse": True})
            validate_approval(approval, request["spec"], request["preview"])
            changed_result = deepcopy(request["result"])
            if scenario == "tp-fin":
                changed_result["rows"][0][4] += Decimal("1")
                changed_result["rows"][0][6] += Decimal("1")
            else:
                changed_result["rows"][0][1] += Decimal("1")
            spec = request["spec"]
            changed = build_preview(changed_result, spec, self.models[scenario]["data"][1],
                                    sheet=request["preview"]["target"]["sheet"],
                                    marker=marker(spec, request["preview"]["target"]["sheet"]),
                                    source_evidence=read_source_evidence(scenario))
            self.assertNotEqual(changed["previewHash"], request["preview"]["previewHash"])
            fresh = issue_approval(spec, changed, approved_at=approval["approvedAt"])
            validate_approval(fresh, spec, changed)
            with patch.object(engine, "_package", side_effect=AssertionError("Không được xử lý package")):
                with self.assertRaises(InputError) as caught:
                    apply_result(self.source, **{**request, "preview": changed})
            self.assertEqual(caught.exception.code, "AF_SPEC_STALE")
            self.assertIn("preview lại", caught.exception.detail)

    def test_af_ap_002_readback_matches_preview_with_decimal_numeric_cells(self):
        for scenario, model in self.models.items():
            request = self.request(scenario)
            output = apply_result(self.source, **request)
            result = read_result_sheet(output["workbook"], request["target_sheet"])
            self.assertEqual(result, model["result"])
            indexes = (4, 5, 6) if scenario == "tp-fin" else (1, 2, 3)
            self.assertTrue(all(isinstance(row[index], Decimal) for row in result["rows"] for index in indexes))
            index = 4 if scenario == "tp-fin" else 1
            self.assertEqual(sum((row[index] for row in result["rows"]), Decimal("0")),
                             Decimal(model["reconciliation"]["controlTotalResult"]))

    def test_af_ap_003_source_parts_metadata_order_and_no_auto_save(self):
        for scenario in self.models:
            actual = apply_result(self.source, **self.request(scenario))
            written = parts(actual["workbook"])
            self.assertEqual({key: written[key] for key in self.original if key not in META},
                             {key: value for key, value in self.original.items() if key not in META})
            for name, closing in (("xl/workbook.xml", b"</sheets>"),
                                  ("[Content_Types].xml", b"</Types>"),
                                  ("xl/_rels/workbook.xml.rels", b"</Relationships>")):
                prefix, suffix = self.original[name].split(closing)
                self.assertTrue(written[name].startswith(prefix))
                self.assertTrue(written[name].endswith(closing + suffix))
            before = ET.fromstring(self.original["xl/workbook.xml"]).find("{" + MAIN + "}sheets")
            after = ET.fromstring(written["xl/workbook.xml"]).find("{" + MAIN + "}sheets")
            self.assertEqual([dict(node.attrib) for node in after][:-1], [dict(node.attrib) for node in before])
            self.assertEqual(len(after), len(before) + 1)
            self.assertFalse(actual["apply"]["workbookSaved"])
            self.assertEqual(actual["apply"]["source"]["sheetsWritten"], [])

    def test_af_ap_004_consumed_token_copy_and_replay_cannot_reach_package(self):
        request = self.request()
        copy_before = deepcopy(request["approval"])
        consumed = consume_approval(request["approval"])
        self.assertEqual(approval_state(consumed), {"consumed": True, "singleUse": True})
        for token in (request["approval"], consumed, copy_before):
            with patch.object(engine, "_package", side_effect=AssertionError("Replay phải chặn trước package")):
                with self.assertRaises(InputError) as caught:
                    apply_result(self.source, **{**request, "approval": token})
            self.assertEqual(caught.exception.code, "AF_SPEC_STALE")
        with self.assertRaises(InputError) as caught:
            consume_approval(request["approval"])
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_af_ap_005_result_sheet_marker_and_labels_are_read_back_exactly(self):
        for scenario in self.models:
            request = self.request(scenario)
            output = apply_result(self.source, **request)
            written = parts(output["workbook"])
            new_names = set(written) - set(self.original)
            self.assertEqual(len(new_names), 1)
            root = ET.fromstring(written[new_names.pop()])
            rows = root.find("{" + MAIN + "}sheetData")
            texts = [node.text for node in rows[-1].iter() if node.tag == "{" + MAIN + "}t"]
            self.assertEqual(texts, [request["marker"]])
            self.assertIn("|preview=" + request["preview"]["previewHash"], texts[0])
            self.assertIn("|labels=" + ",".join(output["apply"]["labels"]), texts[0])

    def test_antifake_source_file_sha_mtime_unchanged_and_engine_has_no_file_io(self):
        fixture = FIXTURES / "assistant"
        paths = [SOURCE, *(fixture / scenario / "wl1_snapshot.json" for scenario in self.models)]
        paths += [p for scenario in self.models for p in (fixture / scenario / "source").rglob("*.csv")]
        before = file_state(paths)
        request = self.request()
        with patch.object(builtins, "open", side_effect=AssertionError("Engine không được mở file")):
            with patch("pathlib.Path.open", side_effect=AssertionError("Engine không được mở file")):
                output = apply_result(self.source, **request)
        with temp_workspace() as directory:
            target = directory / "result.xlsx"
            target.write_bytes(output["workbook"])
            self.assertEqual(read_result_sheet(target.read_bytes(), request["target_sheet"]), request["result"])
        self.assertFalse(directory.exists())
        self.assertEqual(file_state(paths), before)

    def test_antifake_result_values_only_and_existing_source_formula_preserved(self):
        output = apply_result(self.source, **self.request())
        verify_values_only(output["workbook"])
        written = parts(output["workbook"])
        self.assertIn(b"<f>", self.original["xl/worksheets/sheet1.xml"])
        self.assertEqual(written["xl/worksheets/sheet1.xml"], self.original["xl/worksheets/sheet1.xml"])
        root = ET.fromstring(written["xl/worksheets/sheet2.xml"])
        self.assertFalse(any(node.tag.rsplit("}", 1)[-1] == "f" for node in root.iter()))
        self.assertFalse(any(name.lower().startswith(("xl/querytables/", "xl/pivotcache",
                                                     "xl/pivottables/", "xl/externallinks/"))
                             or name.lower() == "xl/connections.xml" for name in written))
        for name in ("xl/queryTables/query1.xml", "xl/connections.xml",
                     "xl/pivotCache/pivotCacheDefinition1.xml", "xl/externalLinks/externalLink1.xml"):
            with self.subTest(part=name):
                self.assert_partial(lambda: verify_values_only(package({**written, name: b"<blocked/>"})))
        corrupted = dict(written)
        root.find(".//{" + MAIN + "}c").append(ET.Element("{" + MAIN + "}f"))
        corrupted["xl/worksheets/sheet2.xml"] = ET.tostring(root, encoding="utf-8")
        self.assert_partial(lambda: verify_values_only(package(corrupted)))

    def test_antifake_duplicate_sheet_is_partial_and_existing_sheet_stays_identical(self):
        first = apply_result(self.source, **self.request())
        before = parts(first["workbook"])
        second = self.request()
        self.assert_partial(lambda: apply_result(first["workbook"], **second))
        self.assertEqual(parts(first["workbook"]), before)
        self.assertTrue(approval_state(second["approval"])["consumed"])
        with self.assertRaises(InputError) as caught:
            apply_result(first["workbook"], **second)
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_antifake_fail_after_sheet_has_no_retry_or_success_bytes(self):
        request = self.request(fail_after_sheet=True)
        original_writer = engine._write_package
        with patch.object(engine, "_write_package", wraps=original_writer) as writer:
            self.assert_partial(lambda: apply_result(self.source, **request))
        self.assertEqual(writer.call_count, 0)
        self.assertTrue(approval_state(request["approval"])["consumed"])
        self.assertEqual(parts(self.source), self.original)
        with self.assertRaises(InputError) as caught:
            apply_result(self.source, **request)
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_antifake_tampered_written_value_fails_real_readback_once(self):
        original_writer = engine._write_package
        request = self.request()
        def altered(names, values):
            changed = dict(values)
            root = ET.fromstring(changed["xl/worksheets/sheet2.xml"])
            node = root.find(".//{" + MAIN + "}v")
            node.text = str(Decimal(node.text) + Decimal("1"))
            changed["xl/worksheets/sheet2.xml"] = ET.tostring(root, encoding="utf-8")
            return original_writer(names, changed)
        with patch.object(engine, "_write_package", side_effect=altered) as writer:
            self.assert_partial(lambda: apply_result(self.source, **request))
        self.assertEqual(writer.call_count, 1)
        self.assertTrue(approval_state(request["approval"])["consumed"])
        self.assertEqual(parts(self.source), self.original)

    def test_marker_or_coordinates_tamper_is_not_accepted_as_success(self):
        original_writer = engine._write_package
        for field in ("marker", "coordinate"):
            request = self.request()
            def altered(names, values):
                changed = dict(values)
                root = ET.fromstring(changed["xl/worksheets/sheet2.xml"])
                rows = root.find("{" + MAIN + "}sheetData")
                if field == "marker":
                    node = rows[-1].find(".//{" + MAIN + "}t")
                    node.text += "|changed"
                else:
                    rows[0].find("{" + MAIN + "}c").set("r", "Z1")
                changed["xl/worksheets/sheet2.xml"] = ET.tostring(root, encoding="utf-8")
                return original_writer(names, changed)
            with self.subTest(field=field), patch.object(engine, "_write_package", side_effect=altered):
                self.assert_partial(lambda: apply_result(self.source, **request))

    def test_hash_basis_covers_all_artifact_fields_and_recomputes(self):
        for scenario in self.models:
            artifact = apply_result(self.source, **self.request(scenario))["apply"]
            self.assertEqual(set(artifact["hashBasis"]), BASIS)
            self.assertEqual(len(artifact["hashBasis"]), len(BASIS))
            self.assertEqual(artifact["hash"], canonical_hash({key: artifact[key] for key in artifact["hashBasis"]}))
            changed = deepcopy(artifact)
            changed["source"]["unchanged"] = False
            self.assertNotEqual(changed["hash"], canonical_hash({key: changed[key] for key in changed["hashBasis"]}))

    def test_two_fresh_explicit_approvals_keep_bytes_and_artifact_deterministic(self):
        for scenario in self.models:
            first = apply_result(self.source, **self.request(scenario))
            second = apply_result(self.source, **self.request(scenario))
            self.assertEqual(first, second)
            with ZipFile(io.BytesIO(first["workbook"])) as archive:
                self.assertTrue(all(info.date_time == (2026, 1, 1, 0, 0, 0) for info in archive.infolist()))

    def test_missing_explicit_metadata_blocks_before_consume_and_apply(self):
        model = self.models["tp-fin"]
        with self.assertRaises(InputError) as caught:
            issue_approval(model["spec"], model["preview"])
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")
        request = self.request(applied_at=None)
        self.assert_partial(lambda: apply_result(self.source, **request))
        self.assertFalse(approval_state(request["approval"])["consumed"])

    def test_engine_offline_no_ai_com_or_disk_calls(self):
        forbidden = {"openai", "requests", "http", "urllib", "socket", "subprocess", "win32com", "ctypes"}
        for name in ("assistant_approval", "assistant_apply"):
            source = (ROOT / "pbip_assistant/sources" / (name + ".py")).read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Import):
                    self.assertFalse({alias.name.split(".")[0] for alias in node.names} & forbidden)
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or "").split(".")[0], forbidden)
            self.assertNotIn(".artifacts", source)
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Không được gọi network")):
            for scenario in self.models:
                output = apply_result(self.source, **self.request(scenario))
                self.assertFalse(output["apply"]["workbookSaved"])


if __name__ == "__main__":
    unittest.main()

