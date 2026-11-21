"""Small invented native packages for preparation service journeys; no Office IO."""
import base64
from copy import deepcopy
import hashlib
from io import BytesIO
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZipFile, ZIP_DEFLATED


def native_package(image):
    main='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    pkg='http://schemas.openxmlformats.org/package/2006/relationships'
    content='http://schemas.openxmlformats.org/package/2006/content-types'
    sheets=image['sheets']
    sheet_entries=[];relationships=[];members={};overrides=[]
    for index,sheet in enumerate(sheets,1):
        sheet_entries.append(f'<sheet name={quoteattr(sheet["name"])} sheetId="{index}" r:id="rId{index}"/>')
        relationships.append(f'<Relationship Id="rId{index}" Type="{rel}/worksheet" Target="worksheets/sheet{index}.xml"/>')
        overrides.append(f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        rows=[]
        for r,row in enumerate(sheet['values']):
            cells=[]
            for c,value in enumerate(row):
                rr=r+sheet['rowOffset']+1;cc=c+sheet['columnOffset'];column=''
                while cc>=0:cc,rem=divmod(cc,26);column=chr(65+rem)+column;cc-=1
                address=column+str(rr);style='1' if sheet['numberFormats'][r][c]=='@' else '0'
                if [r,c] in sheet['formulaCells']:
                    body='<f>'+escape(str(sheet['formulas'][r][c]).lstrip('='))+'</f>';kind=''
                elif isinstance(value,str):
                    body='<is><t xml:space="preserve">'+escape(value)+'</t></is>';kind=' t="inlineStr"'
                elif value is None:body='';kind=''
                elif isinstance(value,bool):body='<v>'+('1' if value else '0')+'</v>';kind=' t="b"'
                else:body='<v>'+str(value)+'</v>';kind=''
                cells.append(f'<c r="{address}" s="{style}"{kind}>{body}</c>')
            rows.append(f'<row r="{r+sheet["rowOffset"]+1}">'+''.join(cells)+'</row>')
        members[f'xl/worksheets/sheet{index}.xml']=f'<worksheet xmlns="{main}"><sheetData>'+''.join(rows)+'</sheetData></worksheet>'
    members['xl/workbook.xml']=f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>'+''.join(sheet_entries)+'</sheets></workbook>'
    members['xl/_rels/workbook.xml.rels']=f'<Relationships xmlns="{pkg}">'+''.join(relationships)+f'<Relationship Id="style" Type="{rel}/styles" Target="styles.xml"/></Relationships>'
    members['[Content_Types].xml']=f'<Types xmlns="{content}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'+''.join(overrides)+'</Types>'
    members['_rels/.rels']=f'<Relationships xmlns="{pkg}"><Relationship Id="book" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    members['xl/styles.xml']=f'<styleSheet xmlns="{main}"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>'
    output=BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for name,text in members.items():archive.writestr(name,text)
    return output.getvalue()


def capture_image(store,transport,image,package_bytes=None):
    from pbip_assistant.sources.preparation.packages import image_fingerprint
    result=deepcopy(image)
    result.pop('_nativeEvidence',None);result.pop('preservation',None);result.pop('fullFingerprint',None)
    result['fingerprint']=image_fingerprint(result)
    data=package_bytes if package_bytes is not None else native_package(result)
    digest=lambda payload:'sha256:'+hashlib.sha256(payload).hexdigest()
    upload=store.begin(transport,len(data),digest(data))
    for index,offset in enumerate(range(0,len(data),1048576)):
        chunk=data[offset:offset+1048576]
        store.chunk(transport,upload['uploadId'],index,offset,digest(chunk),base64.b64encode(chunk).decode())
    evidence=store.finish(transport,upload['uploadId'],result)
    result.update(preservation=evidence['preservation'],fullFingerprint=evidence['fullFingerprint'])
    return result
