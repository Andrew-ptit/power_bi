import base64
from io import BytesIO
import unittest
from zipfile import ZipFile
from pbip_assistant.sources.preparation.package_preservation import inspect_package, verify_package_delta, verify_package_group,verify_package_copy_delta,verify_package_csv_import,verify_package_image,verify_package_import


def package(value=" x ", bold=False, height="15", cache="2"):
    parts = {"xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" sheetId="1" r:id="r1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/styles.xml": '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts><font>'+ ('<b/>' if bold else '')+'</font></fonts><fills><fill/></fills><borders><border/></borders><cellStyleXfs><xf/></cellStyleXfs><cellXfs><xf fontId="0" fillId="0" borderId="0" numFmtId="0"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1" ht="{height}"><c r="A1" t="inlineStr"><is><t>{value}</t></is></c><c r="B1"><f>1+1</f><v>{cache}</v></c></row></sheetData></worksheet>'}
    output=BytesIO()
    with ZipFile(output,"w") as z:
        for path, data in parts.items(): z.writestr(path,data)
    return base64.b64encode(output.getvalue()).decode()


class PackagePreservationTests(unittest.TestCase):
    def test_excel_runtime_revision_stamp_does_not_masquerade_as_workbook_edit(self):
        def stamped(document_id, extra="", namespace="http://schemas.microsoft.com/office/spreadsheetml/2014/revision", bold=False):
            output = BytesIO()
            with ZipFile(BytesIO(base64.b64decode(package(bold=bold)))) as source, ZipFile(output,"w") as target:
                for member in source.namelist():
                    data = source.read(member)
                    if member == "xl/workbook.xml":
                        stamp = ('<xr:revisionPtr xmlns:xr="' + namespace + '" revIDLastSave="0" documentId="'
                                 + document_id + '"' + extra + '/>')
                        data = data.replace(b'</workbook>', stamp.encode() + b'</workbook>')
                    target.writestr(member, data)
            return inspect_package(output.getvalue())["fingerprint"]
        original = inspect_package(package())["fingerprint"]
        self.assertEqual(original, stamped("export_one"))
        self.assertEqual(stamped("export_one"), stamped("export_two"))
        self.assertNotEqual(stamped("export_one"), stamped("export_two", bold=True))
        self.assertNotEqual(stamped("export_one", extra=' futureData="one"'), stamped("export_two", extra=' futureData="two"'))
        self.assertNotEqual(stamped("export_one", namespace="urn:unrelated"), stamped("export_two", namespace="urn:unrelated"))

    def test_personal_copy_preserves_ordinary_formulas_but_blocks_self_retargeting(self):
        from pbip_assistant.sources.preparation.package_preservation import validate_copy_targets
        self.assertTrue(validate_copy_targets(inspect_package(package()), ["Data"]))
        output=BytesIO()
        with ZipFile(BytesIO(base64.b64decode(package()))) as source,ZipFile(output,"w") as target:
            for path in source.namelist():
                target.writestr(path,source.read(path).replace(b'<f>1+1</f>',b'<f>Data!A1</f>'))
        with self.assertRaises(Exception) as caught:
            validate_copy_targets(inspect_package(output.getvalue()),["Data"])
        self.assertEqual(caught.exception.code,"DP_UNSUPPORTED_PRESERVATION")

    def marker_package(self, marker, other="kept"):
        output=BytesIO()
        with ZipFile(BytesIO(base64.b64decode(package()))) as source,ZipFile(output,"w") as target:
            for path in source.namelist():
                data=source.read(path)
                if path=="xl/_rels/workbook.xml.rels" and marker is not None:
                    data=data.replace(b'</Relationships>',b'<Relationship Id="marker" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="../customXml/item1.xml"/></Relationships>')
                target.writestr(path,data)
            target.writestr("customXml/item2.xml",'<other xmlns="urn:other">'+other+'</other>')
            if marker is not None:
                target.writestr("customXml/item1.xml",'<session xmlns="urn:local-data-copilot:preparation-session:v1" marker="'+marker+'"/>')
                target.writestr("customXml/_rels/item1.xml.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="p" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps" Target="itemProps1.xml"/></Relationships>')
                target.writestr("customXml/itemProps1.xml",'<datastoreItem xmlns="http://schemas.openxmlformats.org/officeDocument/2006/customXml" itemID="marker"/>')
        return output.getvalue()

    def test_only_owned_session_marker_is_excluded_from_conflict_hash(self):
        original=inspect_package(self.marker_package(None))["fingerprint"]
        self.assertEqual(original,inspect_package(self.marker_package("first"))["fingerprint"])
        self.assertEqual(original,inspect_package(self.marker_package("rotated"))["fingerprint"])
        self.assertNotEqual(original,inspect_package(self.marker_package("rotated",other="edited"))["fingerprint"])

    def test_unused_storage_rows_cannot_hide_unapproved_changes(self):
        def with_style(extra):
            output=BytesIO()
            with ZipFile(BytesIO(base64.b64decode(package()))) as source,ZipFile(output,"w") as target:
                for path in source.namelist():
                    data=source.read(path)
                    if path=="xl/styles.xml":data=data.replace(b'</cellXfs>',extra+b'</cellXfs>')
                    target.writestr(path,data)
            return inspect_package(output.getvalue())
        before=with_style(b'<xf numFmtId="0"/>')
        after=with_style(b'<xf numFmtId="49"/>')
        with self.assertRaises(Exception):verify_package_delta(before,after,[])

    def test_reviewed_number_format_allocation_keeps_other_style_resources_exact(self):
        output=BytesIO()
        with ZipFile(BytesIO(base64.b64decode(package(value="x")))) as source,ZipFile(output,"w") as target:
            for path in source.namelist():
                data=source.read(path)
                if path=="xl/styles.xml":
                    data=data.replace(b'<fonts>',b'<numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy-mm-dd"/></numFmts><fonts>')
                    data=data.replace(b'</cellXfs>',b'<xf fontId="0" fillId="0" borderId="0" numFmtId="164" applyNumberFormat="1"/></cellXfs>')
                if path=="xl/worksheets/sheet1.xml":data=data.replace(b'r="A1"',b'r="A1" s="1"')
                target.writestr(path,data)
        verify_package_delta(inspect_package(package()),inspect_package(output.getvalue()),[{"sheetName":"Data","row":0,"column":0,"before":" x ","after":"x","numberFormat":"yyyy-mm-dd"}])

    def test_mixed_personal_and_imported_cleanup_and_inverse_are_exact(self):
        from pbip_assistant.sources.preparation.package_preservation import verify_package_copy_undo
        before=inspect_package(self.group())
        output=BytesIO()
        with ZipFile(BytesIO(self.group(trim=True))) as source,ZipFile(output,"w") as target:
            for path in source.namelist():
                data=source.read(path)
                if path=="xl/workbook.xml":data=data.replace(b'</sheets>',b'<sheet name="Clean" sheetId="3" r:id="r3"/></sheets>')
                if path=="xl/_rels/workbook.xml.rels":data=data.replace(b'</Relationships>',b'<Relationship Id="r3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/></Relationships>')
                target.writestr(path,data)
            target.writestr("xl/worksheets/sheet3.xml",source.read("xl/worksheets/sheet2.xml"))
        after=inspect_package(output.getvalue())
        common={"row":0,"column":0,"before":" x ","after":"x","numberFormat":"General"}
        verify_package_copy_delta(before,after,[{"sourceName":"Data","targetName":"Clean"}],[{"sheetName":"Copy",**common},{"sheetName":"Clean",**common}])
        verify_package_copy_undo(after,before,["Clean"],[{"sheetName":"Copy",**common,"before":"x","after":" x "}])

    def group(self, altered=False,trim=False,csv=False):
        original=BytesIO(base64.b64decode(package()))
        output=BytesIO()
        with ZipFile(original) as source,ZipFile(output,"w") as target:
            for name in source.namelist():
                data=source.read(name)
                if name=="xl/workbook.xml":data=data.replace(b'</sheets>',b'<sheet name="Copy" sheetId="2" r:id="r2"/></sheets>')
                if name=="xl/_rels/workbook.xml.rels":data=data.replace(b'</Relationships>',b'<Relationship Id="r2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>')
                if name=="xl/styles.xml" and csv:data=data.replace(b'</cellXfs>',b'<xf fontId="0" fillId="0" borderId="0" numFmtId="49"/></cellXfs>')
                target.writestr(name,data)
            data=source.read("xl/worksheets/sheet1.xml")
            if altered:data=data.replace(b'ht="15"',b'ht="20"')
            if trim:data=data.replace(b'> x <',b'>x<')
            if csv:data=b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" s="1" t="inlineStr"><is><t>ID</t></is></c></row><row r="2"><c r="A2" s="1" t="inlineStr"><is><t>=literal</t></is></c></row></sheetData></worksheet>'
            target.writestr("xl/worksheets/sheet2.xml",data)
        return output.getvalue()

    def test_owned_group_requires_independent_source_and_preserves_survivors(self):
        before=inspect_package(package());after=inspect_package(self.group())
        source={"Copy":(before,"Data")}
        verify_package_group(before,after,created_sheet_names=["Copy"],expected_sources=source)
        verify_package_group(after,before,deleted_sheet_names=["Copy"])
        with self.assertRaises(Exception):verify_package_group(before,inspect_package(self.group(True)),created_sheet_names=["Copy"],expected_sources=source)
        with self.assertRaises(Exception):verify_package_group(before,after,created_sheet_names=["Copy"],expected_sources={})

    def test_personal_copy_delta_uses_original_independent_styles_and_values(self):
        before=inspect_package(package());after=inspect_package(self.group(trim=True))
        changes=[{"sheetName":"Copy","row":0,"column":0,"before":" x ","after":"x","numberFormat":"General"}]
        verify_package_copy_delta(before,after,[{"sourceName":"Data","targetName":"Copy"}],changes)
        with self.assertRaises(Exception):verify_package_copy_delta(before,inspect_package(self.group(True,True)),[{"sourceName":"Data","targetName":"Copy"}],changes)

    def test_csv_creation_preserves_literals_and_surviving_full_package(self):
        before=inspect_package(package());after=inspect_package(self.group(csv=True))
        plan=[{"targetName":"Copy","values":[["ID"],["=literal"]],"numberFormats":[["@"],["@"]]}]
        verify_package_csv_import(before,after,plan)
        verify_package_import(before,after,[{"kind":"csv","sheets":plan}])
        with self.assertRaises(Exception):verify_package_csv_import(before,after,[{"targetName":"Copy","values":[["ID"],["wrong"]],"numberFormats":[["@"],["@"]]}])

    def test_csv_native_row_storage_and_default_geometry_are_accepted_without_custom_heights(self):
        def native_rows(extra=""):
            output=BytesIO()
            with ZipFile(BytesIO(self.group(csv=True))) as source, ZipFile(output,"w") as target:
                for member in source.namelist():
                    data=source.read(member)
                    if member=="xl/worksheets/sheet2.xml":
                        data=data.replace(b'<sheetData>', b'<sheetFormatPr xmlns:ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac" defaultRowHeight="15" ac:dyDescent="0.25"/><sheetData>')
                        data=data.replace(b'<row r="1">', ('<row xmlns:ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac" r="1" spans="1:1" ac:dyDescent="0.25"'+extra+'>').encode())
                    target.writestr(member,data)
            return inspect_package(output.getvalue())
        before=inspect_package(package())
        plan=[{"targetName":"Copy","values":[["ID"],["=literal"]],"numberFormats":[["@"],["@"]]}]
        verify_package_csv_import(before,native_rows(),plan)
        with self.assertRaises(Exception):
            verify_package_csv_import(before,native_rows(' ht="25" customHeight="1"'),plan)

    def test_native_image_must_match_exported_values_and_formula_mask(self):
        evidence=inspect_package(package())
        image={"version":1,"sheets":[{"sheetId":"id","name":"Data","rowOffset":0,"columnOffset":0,"values":[[" x ",2]],"formulas":[[" x ","=1+1"]],"formulaCells":[[0,1]],"numberFormats":[["General","General"]]}]}
        verify_package_image(evidence,image)
        image["sheets"][0]["values"][0][0]="raced"
        with self.assertRaises(Exception):verify_package_image(evidence,image)

    def test_complete_style_and_geometry_conflicts_but_formula_cache_does_not(self):
        original=inspect_package(package())
        self.assertEqual(original["fingerprint"],inspect_package(package(cache="3"))["fingerprint"])
        self.assertNotEqual(original["fingerprint"],inspect_package(package(bold=True))["fingerprint"])
        self.assertNotEqual(original["fingerprint"],inspect_package(package(height="18"))["fingerprint"])

    def test_delta_allows_only_approved_literal_and_preserves_formula_style_geometry(self):
        before,after=inspect_package(package()),inspect_package(package(value="x"))
        changes=[{"sheetName":"Data","row":0,"column":0,"before":" x ","after":"x","numberFormat":"General"}]
        verify_package_delta(before,after,changes)
        for altered in (package(value="x",bold=True),package(value="x",height="18"),package(value="other")):
            with self.assertRaises(Exception): verify_package_delta(before,inspect_package(altered),changes)
