"""Complete bounded OOXML conflict evidence; no workbook mutation or formula rewriting.

All ZIP members participate, including unsupported metadata. Only formula result
caches and documented volatile core properties are excluded. Unknown differences
fail closed. This does not make an arbitrary package safe to import.
"""
import base64
from copy import deepcopy
from io import BytesIO
import math
import posixpath
import re
from zipfile import ZipFile, BadZipFile

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_ingest import canonical_hash
from .inventory import _xml

MAIN="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAX_PACKAGE_BYTES=64*1024*1024
SESSION_NS="urn:local-data-copilot:preparation-session:v1"


def _exclude_session_marker(files, roots):
    """Exclude only our recovery transport metadata, never other custom XML."""
    removed=set()
    for path,node in list(roots.items()):
        if re.fullmatch(r"customXml/item[0-9]+\.xml",path) and node.tag==f"{{{SESSION_NS}}}session":
            removed.add(path)
            relpath=_relationships_path(path)
            if relpath in roots:
                for relation in roots[relpath]:
                    if relation.get("TargetMode")=="External" or not relation.get("Type","").endswith("/customXmlProps"):
                        _fail("Unexpected session marker relationship")
                    target=_target(path,relation.get("Target",""))
                    props=roots.get(target)
                    if (not re.fullmatch(r"customXml/itemProps[0-9]+\.xml",target) or props is None
                            or props.tag!="{http://schemas.openxmlformats.org/officeDocument/2006/customXml}datastoreItem"):
                        _fail("Invalid session marker properties")
                    removed.add(target)
                removed.add(relpath)
    if not removed:return
    # A properties part shared with unrelated XML is not owned by the marker.
    for path,node in roots.items():
        if not path.endswith(".rels") or path in removed:continue
        folder,filename=posixpath.split(path)
        owner=posixpath.join(posixpath.dirname(folder),filename[:-5])
        for relation in list(node):
            target=_target(owner,relation.get("Target",""))
            if target in removed:
                if not relation.get("Type","").endswith("/customXml") or target not in removed or not re.fullmatch(r"customXml/item[0-9]+\.xml",target):
                    _fail("Session marker dependency is shared with unrelated content")
                node.remove(relation)
    types=roots.get("[Content_Types].xml")
    if types is not None:
        for child in list(types):
            if child.get("PartName","").lstrip("/") in removed:types.remove(child)
    for path in removed:files.pop(path,None);roots.pop(path,None)


def _fail(message):
    raise InputError("DP_UNSUPPORTED_PRESERVATION", "packageEvidence", message)


def _tree(node):
    text=node.text or ""
    if len(node) and not text.strip(): text=""
    tail=node.tail or ""
    if not tail.strip():tail=""
    return [node.tag, dict(sorted(node.attrib.items())), text, [_tree(child) for child in node],tail]


def _column(index):
    result=""
    while index>=0:
        index,remainder=divmod(index,26);result=chr(65+remainder)+result;index-=1
    return result


def inspect_package(encoded):
    """Return server-retained normalized evidence and its complete fingerprint."""
    try:
        payload=base64.b64decode(encoded,validate=True) if isinstance(encoded,str) else bytes(encoded)
        if len(payload)>MAX_PACKAGE_BYTES: _fail("Compressed workbook exceeds 64 MiB")
        with ZipFile(BytesIO(payload)) as archive:
            entries=archive.infolist()
            if (len(entries)>10000 or len({e.filename for e in entries})!=len(entries)
                    or sum(e.file_size for e in entries)>MAX_PACKAGE_BYTES):
                _fail("Workbook evidence exceeds expanded package bound")
            files={}
            for entry in entries:
                if entry.is_dir(): continue
                path=entry.filename
                if path.startswith("/") or "\\" in path or any(p in {"..",""} for p in path.split("/")):
                    _fail("Unsafe package member")
                files[path]=archive.read(entry)
    except (ValueError,TypeError,BadZipFile,OverflowError) as exc:
        _fail("Invalid compressed workbook evidence")
    if "xl/workbook.xml" not in files or "xl/_rels/workbook.xml.rels" not in files:
        _fail("Missing workbook relationships")
    roots={path:_xml(data) for path,data in files.items() if path.endswith((".xml",".rels"))}
    _exclude_session_marker(files,roots)
    workbook=roots["xl/workbook.xml"]
    # MS-XLSX 2.4.72/2.6.155: revisionPtr is Excel runtime bookkeeping,
    # not document identity. Compressed exports can rotate documentId without
    # editing a cell. Normalize only the documented attributes in this exact
    # namespace; retain unknown attributes/children as preservation evidence.
    revision_ns = "http://schemas.microsoft.com/office/spreadsheetml/2014/revision"
    runtime_attributes = {
        "documentId", "revIDLastSave",
        "{http://schemas.microsoft.com/office/spreadsheetml/2016/revision6}coauthVersionLast",
        "{http://schemas.microsoft.com/office/spreadsheetml/2016/revision6}coauthVersionMax",
        "{http://schemas.microsoft.com/office/spreadsheetml/2016/revision10}uidLastSave",
    }
    for stamp in workbook.findall(f"{{{revision_ns}}}revisionPtr"):
        for attribute in runtime_attributes:
            stamp.attrib.pop(attribute, None)
        if not stamp.attrib and not len(stamp) and not (stamp.text or "").strip() and not (stamp.tail or "").strip():
            workbook.remove(stamp)
    relationships={n.get("Id"):n for n in roots["xl/_rels/workbook.xml.rels"]}
    strings=[]
    string_nodes=[]
    if "xl/sharedStrings.xml" in roots:
        string_nodes=list(roots["xl/sharedStrings.xml"])
        strings=["".join(n.itertext()) for n in roots["xl/sharedStrings.xml"]]
    styles=roots.get("xl/styles.xml")
    xfs=list(styles.find(f"{{{MAIN}}}cellXfs")) if styles is not None and styles.find(f"{{{MAIN}}}cellXfs") is not None else []
    custom_formats={n.get("numFmtId"):n.get("formatCode") for n in styles.findall(f"{{{MAIN}}}numFmts/{{{MAIN}}}numFmt")} if styles is not None else {}
    if styles is not None and len(custom_formats)!=len(styles.findall(f"{{{MAIN}}}numFmts/{{{MAIN}}}numFmt")):_fail("Duplicate number-format resource identifier")
    def resolved_style(index):
        if not isinstance(index,str) or not re.fullmatch(r"[0-9]+",index):_fail("Invalid cell style index")
        if not xfs:
            if index!="0": _fail("Missing cell style")
            return {"numFmt":"General"}
        try: xf=deepcopy(xfs[int(index)])
        except (IndexError,ValueError): _fail("Invalid cell style index")
        result={}
        for key,tag in (("fontId","fonts"),("fillId","fills"),("borderId","borders"),("xfId","cellStyleXfs")):
            if key in xf.attrib:
                container=styles.find(f"{{{MAIN}}}{tag}")
                try: result[tag]=_tree(list(container)[int(xf.attrib.pop(key))])
                except (IndexError,ValueError,TypeError): _fail("Invalid style resource reference")
        fmt=xf.attrib.pop("numFmtId","0")
        result["numFmt"]=custom_formats.get(fmt,{"0":"General","1":"0","2":"0.00","9":"0%","10":"0.00%","49":"@"}.get(fmt,"builtin:"+fmt))
        result["xf"]=_tree(xf)
        return result
    sheets={};cells={};used_strings=set();used_styles=set()
    for entry in workbook.findall(f"{{{MAIN}}}sheets/{{{MAIN}}}sheet"):
        relation=relationships.get(entry.get(f"{{{REL}}}id"))
        if relation is None or relation.get("TargetMode")=="External": _fail("Invalid worksheet relationship")
        target=relation.get("Target","")
        path=target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl",target))
        if path not in roots or path.startswith("../"): _fail("Missing worksheet evidence")
        name=entry.get("name")
        if not name or name in sheets: _fail("Invalid worksheet names")
        sheets[name]=path;cells[name]={}
        for cell in roots[path].findall(f"{{{MAIN}}}sheetData/{{{MAIN}}}row/{{{MAIN}}}c"):
            address=cell.get("r","")
            if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]*",address): _fail("Invalid worksheet cell address")
            formula=cell.find(f"{{{MAIN}}}f");raw=cell.findtext(f"{{{MAIN}}}v")
            typ=cell.get("t")
            if formula is not None:
                value={"formula":_tree(formula)}
                cached=cell.find(f"{{{MAIN}}}v")
                if cached is not None: cell.remove(cached)
            elif typ=="s":
                try: value=strings[int(raw)]
                except (ValueError,TypeError,IndexError): _fail("Invalid shared string index")
                if int(raw)<0:_fail("Invalid shared string index")
                used_strings.add(int(raw))
                node=deepcopy(string_nodes[int(raw)]);node.tag=f"{{{MAIN}}}is"
                for child in list(cell):cell.remove(child)
                cell.set("t","inlineStr");cell.append(node)
            elif typ=="inlineStr": value="".join(cell.find(f"{{{MAIN}}}is").itertext())
            elif typ=="b": value=raw=="1"
            elif typ in {None,"n"}:
                try: value=float(raw) if raw is not None else ""
                except ValueError: _fail("Invalid numeric cell")
                if isinstance(value,float) and not math.isfinite(value): _fail("Nonfinite cell")
            else: value={"type":typ,"value":raw}
            used_styles.add(int(cell.get("s","0")))
            style=resolved_style(cell.get("s","0"));cell.attrib.pop("s",None)
            cells[name][address]={"value":value,"style":style,"xml":_tree(cell)}
    # Core modified/last-author fields are host bookkeeping, never workbook data.
    if "docProps/core.xml" in roots:
        core=roots["docProps/core.xml"]
        for node in list(core):
            if node.tag.rsplit("}",1)[-1] in {"modified","lastModifiedBy","revision"}: core.remove(node)
    parts={path:(_tree(roots[path]) if path in roots else {"binaryHash":canonical_hash(base64.b64encode(data).decode())}) for path,data in files.items()}
    # Shared strings and XF allocations are storage indirections. Every used
    # string/style is materialized per cell above. The complete raw style part
    # still participates in the conflict fingerprint, while operation proofs
    # may compare the materialized representation below.
    comparison=deepcopy(parts)
    comparison.pop("xl/sharedStrings.xml",None)
    if "xl/styles.xml" in comparison:
        comparison["xl/styles.xml"][3]=[n for n in comparison["xl/styles.xml"][3] if n[0]!=f"{{{MAIN}}}cellXfs"]
    result={"version":1,"parts":parts,"comparisonParts":comparison,"sheets":sheets,"cells":cells,"defaultStyle":resolved_style("0"),
            "storageAllocations":{"strings":[_tree(n) for n in string_nodes],"styles":[_tree(n) for n in xfs],
                                  "usedStrings":sorted(used_strings),"usedStyles":sorted(used_styles)}}
    result["fingerprint"]=canonical_hash(result)
    return result


def _verify_storage_allocations(before,after):
    """Indirection normalization cannot conceal edits to unused resource rows."""
    for kind,used in (("strings","usedStrings"),("styles","usedStyles")):
        old=before["storageAllocations"][kind];new=after["storageAllocations"][kind]
        if new[:len(old)]!=old:_fail("Existing native storage allocation changed")
        if any(index not in after["storageAllocations"][used] for index in range(len(old),len(new))):
            _fail("Unreferenced native storage allocation was added")


def verify_package_delta(before, after, changes):
    """Prove an in-place literal delta without deleting/recreating native sheets.

    Every unrelated part and cell attribute must remain byte-semantically equal.
    Newly allocated OOXML style records require separate native proof; they are
    deliberately not silently ignored here.
    """
    if before["sheets"]!=after["sheets"]: _fail("Worksheet structure changed during delta")
    _verify_storage_allocations(before,after)
    left,right=deepcopy(before),deepcopy(after)
    for record in (left,right):
        record.pop("fingerprint",None);record.pop("storageAllocations",None);record["parts"]=record.pop("comparisonParts",record["parts"])
    seen=set()
    for change in changes:
        name=change.get("sheetName")
        if name not in before["sheets"]: _fail("Unknown approved delta worksheet")
        r,c=change.get("row"),change.get("column")
        if type(r) is not int or type(c) is not int or not 0<=r<1048576 or not 0<=c<16384: _fail("Invalid approved delta coordinate")
        address=_column(c)+str(r+1)
        if (name,address) in seen: _fail("Duplicate approved delta")
        seen.add((name,address))
        old=left["cells"][name].get(address);new=right["cells"][name].get(address)
        if not old or not new or old["value"]!=change["before"] or new["value"]!=change["after"]:
            _fail("Native package cell differs from approved delta")
        if isinstance(old["value"],dict) or isinstance(new["value"],dict): _fail("Formula/type mutation is unsupported")
        if _rich_text(old["xml"]):_fail("Literal cleanup cannot preserve rich text runs")
        desired_format=change.get("numberFormat",old["style"]["numFmt"])
        if desired_format is None:desired_format=old["style"]["numFmt"]
        if new["style"]["numFmt"]!=desired_format:_fail("Native number format differs from approved delta")
        old_format=old["style"].pop("numFmt");new["style"].pop("numFmt")
        if desired_format!=old_format:
            for item in (old,new):
                xf=item["style"].get("xf")
                if xf is not None:
                    flag=xf[1].pop("applyNumberFormat",None)
                    if item is new and flag not in {None,"1","true"}:_fail("Reviewed number format was not applied")
        if old["style"]!=new["style"]: _fail("Unproved style allocation during literal delta")
        for image in (left,right):
            image["cells"][name][address]["value"]={"approvedDelta":True}
            node=image["cells"][name][address]["xml"]
            node[1].pop("t",None);node[2]="";node[3]=[]
            part=image["parts"][image["sheets"][name]]
            def redact(tree):
                if tree[0]==f"{{{MAIN}}}c" and tree[1].get("r")==address:
                    tree[1].pop("t",None);tree[2]="";tree[3]=[]
                else:
                    for child in tree[3]: redact(child)
            redact(part)
    # Number formats may be allocated during a reviewed literal write. Existing
    # custom definitions must remain exact; only the approved codes may appear.
    allowed_formats={c.get("numberFormat") for c in changes if c.get("numberFormat") is not None}
    _allow_style_extensions(left,right,allowed_formats=allowed_formats)
    if canonical_hash(left)!=canonical_hash(right): _fail("Native package changed outside the approved cell delta")
    return True


def _rich_text(node):
    return node[0]==f"{{{MAIN}}}r" or any(_rich_text(child) for child in node[3])


def validate_delta_targets(evidence,changes):
    """Prewrite target guard for features a value assignment cannot preserve."""
    for change in changes:
        name=change["sheetName"];address=_column(change["column"])+str(change["row"]+1)
        cell=evidence["cells"].get(name,{}).get(address)
        if not cell or isinstance(cell["value"],dict) or _rich_text(cell["xml"]):_fail("Cleanup target is formula, rich text or absent")
    return True


def validate_copy_targets(evidence,sheet_names):
    """Reject known native-copy rewrites before allocating a result sheet."""
    for name in sheet_names:
        if name not in evidence["sheets"]:_fail("Unknown personal-copy source worksheet")
        graph,owned=_sheet_graph(evidence,name)
        if graph["localNames"] or len(owned)!=1:
            _fail("Personal copies with scoped names or native dependency parts require separate preservation support")
        for cell in evidence["cells"][name].values():
            value=cell["value"]
            if not isinstance(value,dict):continue
            formula=value.get("formula")
            if not formula or formula[1] or formula[3]:
                _fail("Personal copy contains a special formula or cell type")
            expression=formula[2]
            quoted="'"+name.replace("'","''")+"'"
            if any(re.search(re.escape(token)+r"\s*!",expression,re.IGNORECASE) for token in (name,quoted)):
                _fail("Personal copy would retarget an explicit self-sheet formula")
    return True


def verify_package_copy_delta(before,after,copies,changes):
    expected_sources={};targets=set()
    for copy in copies:
        source,target=copy["sourceName"],copy["targetName"]
        if target in targets:_fail("Duplicate personal-copy target")
        targets.add(target)
        if source not in before["sheets"] or target not in after["sheets"]:_fail("Unknown personal-copy source or target")
        proposed=deepcopy(before);mapped=[]
        for change in changes:
            if change["sheetName"]!=target:continue
            r,c=change["row"],change["column"];address=_column(c)+str(r+1)
            actual=after["cells"][target].get(address)
            if not actual:_fail("Personal-copy delta read-back is absent")
            proposed["cells"][source][address]=deepcopy(actual)
            path=proposed["sheets"][source]
            def replace(tree):
                for i,child in enumerate(tree[3]):
                    if child[0]==f"{{{MAIN}}}c" and child[1].get("r")==address:tree[3][i]=deepcopy(actual["xml"])
                    else:replace(child)
            replace(proposed["comparisonParts"][path])
            mapped.append({**change,"sheetName":source})
        verify_package_delta(before,proposed,mapped)
        expected_sources[target]=(proposed,source)
    inplace=[c for c in changes if c["sheetName"] not in targets]
    baseline=deepcopy(before)
    if inplace:
        # Build the independently approved in-place image from actual cell
        # records, then prove those exact edits before comparing survivors.
        for change in inplace:
            name=change["sheetName"]
            if name not in before["sheets"]:_fail("Delta contains an unknown in-place sheet")
            address=_column(change["column"])+str(change["row"]+1)
            actual=after["cells"][name].get(address)
            if actual is None:_fail("In-place read-back is absent")
            baseline["cells"][name][address]=deepcopy(actual)
            def replace(tree):
                for i,child in enumerate(tree[3]):
                    if child[0]==f"{{{MAIN}}}c" and child[1].get("r")==address:tree[3][i]=deepcopy(actual["xml"])
                    else:replace(child)
            replace(baseline["comparisonParts"][baseline["sheets"][name]])
        verify_package_delta(before,baseline,inplace)
    return verify_package_group(baseline,after,created_sheet_names=list(expected_sources),expected_sources=expected_sources)


def verify_package_copy_undo(before,after,deleted_sheet_names,changes):
    """Undo the exact in-place cells and delete only owned personal results."""
    baseline=deepcopy(before)
    for change in changes:
        name=change["sheetName"]
        if name in deleted_sheet_names or name not in after["sheets"]:_fail("Inverse cleanup must target a surviving owned sheet")
        address=_column(change["column"])+str(change["row"]+1)
        actual=after["cells"][name].get(address)
        if actual is None:_fail("Inverse cleanup read-back is absent")
        baseline["cells"][name][address]=deepcopy(actual)
        def replace(tree):
            for i,child in enumerate(tree[3]):
                if child[0]==f"{{{MAIN}}}c" and child[1].get("r")==address:tree[3][i]=deepcopy(actual["xml"])
                else:replace(child)
        replace(baseline["comparisonParts"][baseline["sheets"][name]])
    verify_package_delta(before,baseline,changes)
    return verify_package_group(baseline,after,deleted_sheet_names=deleted_sheet_names)


def _allow_style_extensions(left,right,*,allowed_formats=(),sources=()):
    before=left["parts"].get("xl/styles.xml");after=right["parts"].get("xl/styles.xml")
    if before is None or after is None:
        if before!=after:_fail("Unproved new style resource table")
        return
    for tag in ("numFmts","fonts","fills","borders","cellStyleXfs","cellStyles"):
        fulltag=f"{{{MAIN}}}{tag}"
        old=next((n for n in before[3] if n[0]==fulltag),None)
        new=next((n for n in after[3] if n[0]==fulltag),None)
        old_entries=old[3] if old else [];new_entries=new[3] if new else []
        if new_entries[:len(old_entries)]!=old_entries:_fail("Existing workbook style resources changed")
        expected=[]
        for source in sources:
            style=source["parts"].get("xl/styles.xml")
            node=next((n for n in style[3] if n[0]==fulltag),None) if style else None
            expected.extend(node[3] if node else [])
        for entry in new_entries[len(old_entries):]:
            if tag=="numFmts" and entry[1].get("formatCode") in allowed_formats:continue
            if entry not in expected:_fail("New style resource is absent from approved native sources")
        # Counts and new resource rows are independently checked above. Compare
        # the original content on both sides for the remainder of the proof.
        before[3]=[n for n in before[3] if n[0]!=fulltag]
        after[3]=[n for n in after[3] if n[0]!=fulltag]


def _relationships_path(path):
    folder,name=posixpath.split(path)
    return posixpath.join(folder,"_rels",name+".rels")


def verify_package_image(evidence,image):
    """Bind native range reads to the exported package, preventing mixed captures."""
    from .packages import image_fingerprint
    image_fingerprint(image)
    if set(evidence["sheets"])!={s["name"] for s in image["sheets"]}:_fail("Native image and compressed workbook sheet inventory differ")
    for sheet in image["sheets"]:
        captured=evidence["cells"][sheet["name"]];mask={tuple(p) for p in sheet["formulaCells"]}
        visited=set()
        for r,row in enumerate(sheet["values"]):
            for c,value in enumerate(row):
                address=_column(sheet["columnOffset"]+c)+str(sheet["rowOffset"]+r+1)
                visited.add(address);cell=captured.get(address)
                actual=cell["value"] if cell else ""
                if (r,c) in mask:
                    formula=actual.get("formula") if isinstance(actual,dict) else None
                    if not formula or formula[1] or "="+formula[2]!=sheet["formulas"][r][c]:_fail("Native formula mask/expression differs from compressed workbook")
                elif isinstance(actual,dict) or actual!=("" if value is None else value):_fail("Native literal value differs from compressed workbook")
                if cell and cell["style"]["numFmt"]!=sheet["numberFormats"][r][c]:_fail("Native number format differs from compressed workbook")
        if any(address not in visited and cell["value"]!="" for address,cell in captured.items()):_fail("Compressed workbook has data outside the captured native frame")
    return True


def _target(path,target):
    return target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(path),target))


def _sheet_graph(evidence,name):
    """Resolve relationship indirections, retaining all dependent part content."""
    parts=evidence["comparisonParts"]
    visiting=set();owned=set()
    def resolve(path):
        if path in visiting:_fail("Cyclic worksheet dependency requires separate preservation support")
        if path not in parts:_fail("Missing worksheet dependency")
        visiting.add(path);owned.add(path)
        node=deepcopy(parts[path]);rels={}
        relpath=_relationships_path(path)
        if relpath in parts:
            owned.add(relpath)
            for relation in parts[relpath][3]:
                attrs=relation[1]
                if attrs.get("TargetMode")=="External":_fail("External worksheet dependencies are unsupported")
                rels[attrs["Id"]]={"type":attrs.get("Type"),"part":resolve(_target(path,attrs.get("Target","")))}
        def walk(tree):
            if not isinstance(tree,list):return
            if tree[0]==f"{{{MAIN}}}table":tree[1].pop("id",None)
            for key,value in list(tree[1].items()):
                if key.startswith("{"+REL+"}"):
                    if value not in rels:_fail("Unresolved worksheet relationship")
                    tree[1][key]=rels[value]
            for child in tree[3]:walk(child)
        if isinstance(node,list):walk(node)
        visiting.remove(path)
        return {"part":node,"relationships":sorted(rels.values(),key=canonical_hash)}
    graph=resolve(evidence["sheets"][name])
    scoped=[]
    index=str(list(evidence["sheets"]).index(name))
    for container in evidence["parts"]["xl/workbook.xml"][3]:
        if container[0]==f"{{{MAIN}}}definedNames":
            for definition in container[3]:
                if definition[1].get("localSheetId")==index:
                    item=deepcopy(definition);item[1].pop("localSheetId",None);scoped.append(item)
    return {"graph":graph,"cells":evidence["cells"][name],"localNames":sorted(scoped,key=canonical_hash)},owned


def _without_group(evidence,names,owned_names=()):
    result=deepcopy(evidence);result.pop("fingerprint",None)
    result.pop("storageAllocations",None)
    parts=result.pop("comparisonParts");result["parts"]=parts
    removed=set()
    for name in names:
        _,owned=_sheet_graph(evidence,name);removed.update(owned)
        result["sheets"].pop(name);result["cells"].pop(name)
    for path in removed:parts.pop(path,None)
    workbook=parts["xl/workbook.xml"]
    removed_ids=set();removed_indexes=set()
    for node in workbook[3]:
        if node[0]==f"{{{MAIN}}}sheets":
            for index,entry in enumerate(node[3]):
                if entry[1].get("name") in names:
                    removed_ids.add(entry[1].get(f"{{{REL}}}id"));removed_indexes.add(str(index))
            node[3]=[entry for entry in node[3] if entry[1].get("name") not in names]
        if node[0]==f"{{{MAIN}}}definedNames":
            # Workbook-global names cannot be guessed to belong to the group.
            # Only names scoped to a removed worksheet are naturally owned.
            node[3]=[entry for entry in node[3] if entry[1].get("localSheetId") not in removed_indexes and entry[1].get("name") not in owned_names]
            for definition in node[3]:
                index=definition[1].pop("localSheetId",None)
                if index is not None:
                    try:definition[1]["localSheetName"]=list(evidence["sheets"])[int(index)]
                    except (ValueError,IndexError):_fail("Invalid scoped name worksheet index")
    workbook[3]=[node for node in workbook[3] if node[0]!=f"{{{MAIN}}}definedNames" or node[3]]
    rels=parts["xl/_rels/workbook.xml.rels"]
    rels[3]=[entry for entry in rels[3] if entry[1].get("Id") not in removed_ids]
    types=parts.get("[Content_Types].xml")
    if types:
        types[3]=[entry for entry in types[3] if entry[1].get("PartName","").lstrip("/") not in removed]
    # These two app properties are a derived sheet inventory. Retain all other
    # app metadata rather than ignoring the complete property document.
    app=parts.get("docProps/app.xml")
    if app:app[3]=[entry for entry in app[3] if entry[0].rsplit("}",1)[-1] not in {"TitlesOfParts","HeadingPairs"}]
    return result


def verify_package_group(before,after,*,created_sheet_names=(),deleted_sheet_names=(),expected_sources=None,owned_defined_names=()):
    """Verify exactly owned sheet insertion/deletion and independent source content.

    Unexpected global metadata, named-range or style-table changes fail closed.
    Source-specific extensions must supply explicit evidence rather than blanket
    whitelisting arbitrary newly appearing ZIP parts.
    """
    created=list(created_sheet_names);deleted=list(deleted_sheet_names)
    if (set(created)&set(deleted) or len(set(created))!=len(created) or len(set(deleted))!=len(deleted)
            or set(after["sheets"])-set(before["sheets"])!=set(created)
            or set(before["sheets"])-set(after["sheets"])!=set(deleted)):
        _fail("Native worksheet group differs from exact owned operation")
    sources=[];approved_names={}
    # Undo may retain allocated style/string rows; existing rows must still be
    # unchanged, while additions must be used by a verified created sheet.
    _verify_storage_allocations(before,after)
    for name in created:
        source=(expected_sources or {}).get(name)
        if not source or len(source)!=2:_fail("Created worksheet lacks independent source evidence")
        expected,source_name=source
        sources.append(expected)
        if source_name not in expected["sheets"]:_fail("Independent source worksheet is absent")
        actual_view,_=_sheet_graph(after,name);expected_view,_=_sheet_graph(expected,source_name)
        if canonical_hash(actual_view)!=canonical_hash(expected_view):_fail("Created worksheet content or dependencies differ from reviewed native source")
        for node in expected["parts"]["xl/workbook.xml"][3]:
            if node[0]==f"{{{MAIN}}}definedNames":
                for definition in node[3]:
                    if "localSheetId" not in definition[1]:approved_names[definition[1]["name"]]=definition
    def names(evidence):
        return {entry[1]["name"]:entry for node in evidence["parts"]["xl/workbook.xml"][3] if node[0]==f"{{{MAIN}}}definedNames" for entry in node[3] if "localSheetId" not in entry[1]}
    before_names,after_names=names(before),names(after)
    for name,definition in list(approved_names.items()):
        if after_names.get(name)!=definition or name in before_names and before_names[name]!=definition:_fail("Native global name differs from reviewed source namespace")
        # A personal worksheet copy reuses existing workbook-global names;
        # these remain surviving content rather than newly owned names.
        if name in before_names:approved_names.pop(name)
    for name in owned_defined_names:
        if name not in before_names or name in after_names:_fail("Owned namespace name deletion did not match provenance")
    left=_without_group(before,deleted,owned_defined_names);right=_without_group(after,created,approved_names)
    if created:_allow_style_extensions(left,right,sources=sources,allowed_formats={cell["style"]["numFmt"] for source in sources for cells in source["cells"].values() for cell in cells.values()})
    # Strip derived app inventory symmetrically even on the no-group side.
    if canonical_hash(left)!=canonical_hash(right):_fail("Native sheet operation changed surviving workbook metadata or content")
    return True


def verify_package_csv_import(before,after,sheets,*,_validate_only=False):
    """Qualify newly allocated ordinary CSV sheets against a closed native subset."""
    targets=[sheet["targetName"] for sheet in sheets]
    if (len(set(targets))!=len(targets) or (not _validate_only and set(after["sheets"])-set(before["sheets"])!=set(targets))
            or any(name in before["sheets"] or name not in after["sheets"] for name in targets)
            or set(before["sheets"])-set(after["sheets"])):_fail("CSV worksheet group differs from reviewed targets")
    expected_style=deepcopy(before["defaultStyle"]);expected_style["numFmt"]="@"
    descent = "{http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac}dyDescent"
    for plan in sheets:
        name=plan["targetName"];rows=plan["values"];cells=after["cells"][name]
        if not rows or not rows[0] or any(len(row)!=len(rows[0]) for row in rows):_fail("CSV expected rows are not rectangular")
        expected={_column(c)+str(r+1):value for r,row in enumerate(rows) for c,value in enumerate(row)}
        for address,value in expected.items():
            cell=cells.get(address)
            if not cell or cell["value"]!=value or cell["style"]!=expected_style or _rich_text(cell["xml"]):_fail("CSV literal, format or presentation differs from reviewed rows")
        if set(cells)-set(expected):_fail("CSV created data outside reviewed rows")
        graph,owned=_sheet_graph(after,name)
        if len(owned)!=1 or graph["localNames"]:_fail("CSV sheet acquired unreviewed dependencies or names")
        root=graph["graph"]["part"]
        for node in root[3]:
            tag=node[0].rsplit("}",1)[-1]
            if tag not in {"dimension","sheetViews","sheetFormatPr","sheetData","pageMargins"}:_fail("CSV sheet acquired unreviewed worksheet structures")
            if tag=="sheetData" and any("r" not in row[1] or set(row[1])-{ "r", "spans", descent} for row in node[3]):_fail("CSV sheet acquired row geometry or formatting")
            if tag=="sheetFormatPr" and set(node[1])-{ "defaultRowHeight", "baseColWidth", "defaultColWidth", descent}:_fail("CSV sheet acquired unreviewed default geometry")
            if tag=="sheetViews":
                for view in node[3]:
                    if set(view[1])-{ "workbookViewId","tabSelected","zoomScale","zoomScaleNormal"}:_fail("CSV sheet acquired nondefault view state")
    if _validate_only:return True
    left=_without_group(before,());right=_without_group(after,targets)
    _allow_style_extensions(left,right,allowed_formats={"@"})
    if canonical_hash(left)!=canonical_hash(right):_fail("CSV insertion changed surviving workbook metadata or content")
    return True


def verify_package_import(before,after,packages):
    """Compose mixed reviewed packages into one complete survivor proof."""
    expected={}
    for package in packages:
        if package["kind"]=="csv":
            verify_package_csv_import(before,after,package["sheets"],_validate_only=True)
            source=deepcopy(after)
            # A validated CSV contributes only its ordinary worksheet, never
            # arbitrary resources or workbook-global names from the output.
            source["parts"]["xl/workbook.xml"][3]=[n for n in source["parts"]["xl/workbook.xml"][3] if n[0]!=f"{{{MAIN}}}definedNames"]
            if "xl/styles.xml" in before["parts"]:source["parts"]["xl/styles.xml"]=deepcopy(before["parts"]["xl/styles.xml"])
            else:source["parts"].pop("xl/styles.xml",None)
        elif package["kind"]=="xlsx":source=inspect_package(package["base64"])
        else:_fail("Unknown reviewed import package")
        for sheet in package["sheets"]:
            target=sheet["targetName"]
            if target in expected:_fail("Duplicate reviewed import target")
            expected[target]=(source,target)
    return verify_package_group(before,after,created_sheet_names=list(expected),expected_sources=expected)
