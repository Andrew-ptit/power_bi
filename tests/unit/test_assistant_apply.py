"""Apply WL6 trên bytes synthetic; nguồn chỉ đọc, mọi ghi thử nằm trong temp."""

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
from pbip_assistant.sources.assistant_approval import approval_state, issue_approval
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_preview import build_preview, temp_workspace
from tests.support.paths import FIXTURES, ROOT
from tests.unit.test_assistant_preview import marker, pipeline, read_source_evidence


STAMP = "2026-10-29T10:00:00+07:00"
APPLIED = "2026-10-29T10:01:00+07:00"
SOURCE = FIXTURES / "source/orders_synthetic.xlsx"
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
META = {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"}


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


def setup(scenario="tp-fin"):
    data, spec, _, _, result = pipeline(scenario)
    sheet = "PnL_Preview" if scenario == "tp-fin" else "Sales_Preview"
    preview = build_preview(result, spec, data[1], sheet=sheet, marker=marker(spec, sheet),
                            source_evidence=read_source_evidence(scenario))
    return spec, preview, result


def request(model, **changes):
    spec, preview, result = model
    target = "PnL_Result" if len(result["columns"]) == 9 else "Sales_Result"
    values = {"result": deepcopy(result), "target_sheet": target,
              "marker": ("LOCAL_DATA_COPILOT|" + target + "|spec=" + spec["fingerprint"] +
                         "|preview=" + preview["previewHash"] + "|labels=" + ",".join(spec["labels"])),
              "labels": list(spec["labels"]), "spec": spec, "preview": preview,
              "approval": issue_approval(spec, preview, approved_at=STAMP), "applied_at": APPLIED}
    values.update(changes)
    return values


class AssistantApplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_bytes()
        cls.original = parts(cls.source)
        cls.fin = setup()
        cls.sales = setup("tp-sales")

    def assert_partial(self, action):
        with self.assertRaises(InputError) as caught:
            action()
        self.assertEqual(caught.exception.code, "AF_WRITE_PARTIAL")

    def test_fin_and_sales_numeric_readback_matches_all_preview_cells(self):
        for model, shape in ((self.fin, (23, 9)), (self.sales, (4, 4))):
            args = request(model)
            actual = apply_result(self.source, **args)
            readback = read_result_sheet(actual["workbook"], args["target_sheet"])
            self.assertEqual(readback, args["result"])
            self.assertEqual((len(readback["rows"]), len(readback["columns"])), shape)
            indexes = (4, 5, 6) if shape[1] == 9 else (1, 2, 3)
            self.assertTrue(all(isinstance(row[index], Decimal) for row in readback["rows"] for index in indexes))
            self.assertTrue(actual["apply"]["approval"]["consumed"])
            self.assertTrue(approval_state(args["approval"])["consumed"])

    def test_source_parts_and_old_sheet_order_are_byte_identical(self):
        actual = apply_result(self.source, **request(self.fin))
        written = parts(actual["workbook"])
        self.assertEqual({name: written[name] for name in self.original if name not in META},
                         {name: value for name, value in self.original.items() if name not in META})
        for name, closing in (("xl/workbook.xml", b"</sheets>"),
                              ("[Content_Types].xml", b"</Types>"),
                              ("xl/_rels/workbook.xml.rels", b"</Relationships>")):
            prefix, suffix = self.original[name].split(closing)
            self.assertTrue(written[name].startswith(prefix))
            self.assertTrue(written[name].endswith(closing + suffix))
        before = ET.fromstring(self.original["xl/workbook.xml"]).find("{" + MAIN + "}sheets")
        after = ET.fromstring(written["xl/workbook.xml"]).find("{" + MAIN + "}sheets")
        self.assertEqual([dict(node.attrib) for node in after][:-1], [dict(node.attrib) for node in before])
        self.assertEqual(after[-1].get("name"), "PnL_Result")
        self.assertEqual(self.source, SOURCE.read_bytes())

    def test_old_source_formula_is_preserved_and_new_result_is_values_only(self):
        self.assertIn(b"<f>", self.original["xl/worksheets/sheet1.xml"])
        actual = apply_result(self.source, **request(self.fin))
        verify_values_only(actual["workbook"])
        written = parts(actual["workbook"])
        self.assertEqual(written["xl/worksheets/sheet1.xml"], self.original["xl/worksheets/sheet1.xml"])
        root = ET.fromstring(written["xl/worksheets/sheet2.xml"])
        self.assertFalse(any(node.tag.rsplit("}", 1)[-1] == "f" for node in root.iter()))
        self.assertFalse(any(name.lower().startswith(("xl/querytables/", "xl/pivotcache", "xl/externallinks/"))
                             or name.lower() == "xl/connections.xml" for name in written))

    def test_artifact_golden_fields_binding_hash_basis_and_no_save(self):
        for model in (self.fin, self.sales):
            args = request(model)
            artifact = apply_result(self.source, **args)["apply"]
            self.assertEqual(artifact["specFingerprint"], args["spec"]["fingerprint"])
            self.assertEqual(artifact["previewHash"], args["preview"]["previewHash"])
            self.assertEqual(artifact["source"], {**args["preview"]["source"], "sheetsWritten": []})
            self.assertEqual(artifact["target"], {"workbook": "current", "sheet": args["target_sheet"],
                             "mode": "values_only", "writeMode": "new_sheet_only", "marker": args["marker"]})
            self.assertEqual(artifact["written"], {"rowCount": len(args["result"]["rows"]),
                                                 "columnCount": len(args["result"]["columns"])})
            self.assertFalse(artifact["workbookSaved"])
            self.assertEqual(artifact["appliedAt"], APPLIED)
            self.assertEqual(artifact["hash"], canonical_hash({key: artifact[key] for key in artifact["hashBasis"]}))
            self.assertTrue({"specFingerprint", "previewHash", "approval", "target", "written", "source",
                             "workbookSaved", "labels", "appliedAt", "variantOf", "variantReason"} <= set(artifact["hashBasis"]))

    def test_two_fresh_approvals_produce_identical_bytes_and_artifact(self):
        first = apply_result(self.source, **request(self.fin))
        second = apply_result(self.source, **request(self.fin))
        self.assertEqual(first, second)
        with ZipFile(io.BytesIO(first["workbook"])) as archive:
            self.assertTrue(all(info.date_time == (2026, 1, 1, 0, 0, 0) for info in archive.infolist()))

    def test_consumed_or_copied_approval_is_rejected_before_package_work(self):
        args = request(self.fin)
        apply_result(self.source, **args)
        with patch.object(engine, "_package", side_effect=AssertionError("Approval phải chặn trước package")):
            with self.assertRaises(InputError) as caught:
                apply_result(self.source, **{**args, "applied_at": None})
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")
        args = request(self.fin)
        args["approval"] = deepcopy(args["approval"])
        with self.assertRaises(InputError) as caught:
            apply_result(self.source, **args)
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_changed_preview_binding_is_stale_before_package_work(self):
        args = request(self.fin)
        args["preview"] = deepcopy(args["preview"])
        args["preview"]["previewHash"] = canonical_hash("changed")
        with patch.object(engine, "_package", side_effect=AssertionError("Không được chạm package")):
            with self.assertRaises(InputError) as caught:
                apply_result(self.source, **args)
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_duplicate_sheet_case_insensitive_fails_without_touching_old_sheet(self):
        first = apply_result(self.source, **request(self.fin))
        before = deepcopy(first["workbook"])
        args = request(self.fin)
        self.assert_partial(lambda: apply_result(first["workbook"], **args))
        self.assertEqual(before, first["workbook"])
        self.assertEqual(read_result_sheet(before, "PnL_Result"), self.fin[-1])
        self.assertTrue(approval_state(args["approval"])["consumed"])
        content = parts(before)
        content["xl/workbook.xml"] = content["xl/workbook.xml"].replace(b'"PnL_Result"', b'"pnl_result"')
        self.assert_partial(lambda: apply_result(package(content), **request(self.fin)))

    def test_fail_after_sheet_burns_approval_and_never_returns_or_retries(self):
        args = request(self.fin)
        with patch.object(engine, "build_workbook", wraps=engine.build_workbook) as build:
            with patch.object(engine, "_write_package", side_effect=AssertionError("Không trả bytes thành công")) as write:
                self.assert_partial(lambda: apply_result(self.source, **args, fail_after_sheet=True))
        self.assertEqual(build.call_count, 1)
        write.assert_not_called()
        self.assertTrue(approval_state(args["approval"])["consumed"])
        with self.assertRaises(InputError) as caught:
            apply_result(self.source, **args)
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_tampered_readback_is_partial_not_success(self):
        real_read = read_result_sheet
        def changed(payload, sheet):
            result = real_read(payload, sheet)
            result["rows"][0][4] += Decimal("1")
            return result
        args = request(self.fin)
        with patch.object(engine, "read_result_sheet", side_effect=changed) as read:
            self.assert_partial(lambda: apply_result(self.source, **args))
        self.assertEqual(read.call_count, 1)
        self.assertTrue(approval_state(args["approval"])["consumed"])

    def test_wrong_value_inserted_in_sheet_is_caught_by_independent_readback(self):
        real_build = engine.build_workbook
        def changed(columns, rows, **kwargs):
            rows = deepcopy(rows)
            rows[0][4] += Decimal("10")
            return real_build(columns, rows, **kwargs)
        with patch.object(engine, "build_workbook", side_effect=changed):
            self.assert_partial(lambda: apply_result(self.source, **request(self.fin)))

    def test_caller_context_mutation_cannot_change_captured_binding_or_artifact(self):
        model = tuple(deepcopy(value) for value in self.fin)
        args = request(model)
        before = deepcopy({key: args[key] for key in ("spec", "preview", "labels", "result")})
        real_write = engine._write_package
        def mutate(names, values):
            args["spec"]["fingerprint"] = canonical_hash("caller changed spec")
            args["preview"]["previewHash"] = canonical_hash("caller changed preview")
            args["labels"].append("stale")
            args["result"]["rows"][0][4] += 100
            return real_write(names, values)
        with patch.object(engine, "_write_package", side_effect=mutate):
            actual = apply_result(self.source, **args)
        artifact = actual["apply"]
        self.assertEqual(artifact["specFingerprint"], before["spec"]["fingerprint"])
        self.assertEqual(artifact["previewHash"], before["preview"]["previewHash"])
        self.assertEqual(artifact["labels"], before["labels"])
        self.assertEqual(artifact["approval"]["boundTo"], {
            "specFingerprint": artifact["specFingerprint"], "previewHash": artifact["previewHash"]})
        self.assertEqual(read_result_sheet(actual["workbook"], "PnL_Result"), before["result"])

    def test_post_consume_shared_validation_error_is_write_partial(self):
        changed = deepcopy(self.fin[-1])
        changed["rows"][0][0] = "x" * 32768
        args = request(self.fin)
        with patch.object(engine, "read_result_sheet", return_value=changed):
            self.assert_partial(lambda: apply_result(self.source, **args))
        self.assertTrue(approval_state(args["approval"])["consumed"])

    def test_tampered_marker_is_caught_by_package_readback(self):
        real_build = engine.build_workbook
        def changed(columns, rows, **kwargs):
            kwargs["marker"] = kwargs["marker"].replace("labels=", "labels=changed,")
            return real_build(columns, rows, **kwargs)
        with patch.object(engine, "build_workbook", side_effect=changed):
            self.assert_partial(lambda: apply_result(self.source, **request(self.fin)))

    def test_wrong_header_or_marker_coordinates_cannot_fake_equal_values(self):
        real_build = engine.build_workbook
        for coordinate in ("header", "marker", "blank"):
            def changed(columns, rows, **kwargs):
                content = parts(real_build(columns, rows, **kwargs))
                name = "xl/worksheets/sheet1.xml"
                if coordinate == "header":
                    content[name] = content[name].replace(b'r="A1"', b'r="Z1"', 1)
                elif coordinate == "marker":
                    index = str(len(rows) + 3).encode("ascii")
                    content[name] = content[name].replace(b'r="A' + index + b'"', b'r="Z' + index + b'"', 1)
                else:
                    index = str(len(rows) + 2).encode("ascii")
                    content[name] = content[name].replace(b'<row r="' + index + b'">', b'<row r="999">', 1)
                return package(content)
            with self.subTest(coordinate=coordinate), patch.object(engine, "build_workbook", side_effect=changed):
                self.assert_partial(lambda: apply_result(self.source, **request(self.fin)))

    def test_values_only_rejects_formula_on_result_even_if_marker_removed(self):
        actual = apply_result(self.source, **request(self.fin))
        content = parts(actual["workbook"])
        content["xl/worksheets/sheet2.xml"] = content["xl/worksheets/sheet2.xml"].replace(b"<v>", b"<f>1+1</f><v>", 1)
        content["xl/worksheets/sheet2.xml"] = content["xl/worksheets/sheet2.xml"].replace(b"LOCAL_DATA_COPILOT|", b"REMOVED|")
        self.assert_partial(lambda: verify_values_only(package(content)))

    def test_values_only_rejects_query_connection_pivot_and_external_parts(self):
        for name in ("xl/queryTables/queryTable1.xml", "xl/connections.xml", "xl/pivotCache/pivotCacheDefinition1.xml",
                     "xl/pivotTables/pivotTable1.xml", "xl/externalLinks/externalLink1.xml"):
            with self.subTest(part=name):
                content = {**self.original, name: b"<x/>"}
                self.assert_partial(lambda: verify_values_only(package(content)))

    def test_external_relationship_is_rejected_without_following_it(self):
        content = dict(self.original)
        part = "xl/_rels/workbook.xml.rels"
        content[part] = content[part].replace(b"</Relationships>",
            b'<Relationship Id="rId99" Type="external" Target="https://invalid.example" TargetMode="External"/></Relationships>')
        self.assert_partial(lambda: apply_result(package(content), **request(self.fin)))

    def test_result_tamper_after_preview_or_wrong_labels_marker_target_is_rejected(self):
        for change in ("value", "labels", "marker", "target"):
            args = request(self.fin)
            if change == "value":
                args["result"]["rows"][0][4] += Decimal("1")
            elif change == "labels":
                args["labels"] = ["verified"]
            elif change == "marker":
                args["marker"] += "|other=policy"
            else:
                args["target_sheet"] = "Other"
            with self.subTest(change=change):
                self.assert_partial(lambda: apply_result(self.source, **args))
                self.assertFalse(approval_state(args["approval"])["consumed"])

    def test_creation_time_is_explicit_and_validation_precedes_consume(self):
        for stamp in (None, "", "invalid", "2026-10-29", "2026-10-29T10:00:00", 123):
            args = request(self.fin, applied_at=stamp)
            with self.subTest(stamp=stamp):
                self.assert_partial(lambda: apply_result(self.source, **args))
                self.assertFalse(approval_state(args["approval"])["consumed"])

    def test_malformed_bytes_zip_paths_and_xml_fail_closed(self):
        for payload in (None, "bytes", b"not-zip", package({**self.original, "../unsafe.xml": b"<x/>"})):
            with self.subTest(kind=type(payload).__name__):
                self.assert_partial(lambda: apply_result(payload, **request(self.fin)))
        content = dict(self.original)
        content["xl/workbook.xml"] = b'<!DOCTYPE workbook [<!ENTITY x "test">]>' + content["xl/workbook.xml"]
        self.assert_partial(lambda: apply_result(package(content), **request(self.fin)))

    def test_package_limits_are_enforced_before_member_read(self):
        for name, limit in (("MAX_PACKAGE_BYTES", 1), ("MAX_PART_BYTES", 1), ("MAX_EXPANDED_BYTES", 1), ("MAX_PARTS", 1)):
            with self.subTest(cap=name), patch.object(engine, name, limit):
                self.assert_partial(lambda: apply_result(self.source, **request(self.fin)))

    def test_missing_or_wrong_sheet_readback_is_not_silently_accepted(self):
        self.assert_partial(lambda: read_result_sheet(self.source, "Missing"))
        self.assert_partial(lambda: read_result_sheet(self.source, "Orders"))

    def test_source_file_hash_mtime_and_no_open_write_network_during_apply(self):
        before = (hashlib.sha256(SOURCE.read_bytes()).hexdigest(), SOURCE.stat().st_mtime_ns)
        args = request(self.fin)
        with patch("builtins.open", side_effect=AssertionError("Apply không được mở file")):
            with patch.object(socket.socket, "connect", side_effect=AssertionError("Apply không được gọi mạng")):
                actual = apply_result(self.source, **args)
        self.assertEqual((hashlib.sha256(SOURCE.read_bytes()).hexdigest(), SOURCE.stat().st_mtime_ns), before)
        with temp_workspace() as directory:
            self.assertFalse(directory.resolve().is_relative_to(ROOT.resolve()))
            target = directory / "applied.xlsx"
            target.write_bytes(actual["workbook"])
            self.assertEqual(read_result_sheet(target.read_bytes(), "PnL_Result"), self.fin[-1])
        self.assertFalse(directory.exists())


if __name__ == "__main__":
    unittest.main()
