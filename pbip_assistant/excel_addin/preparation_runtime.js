/* Local bounded Office adapter. Every mutation needs a fresh server permit. */
(function (root) {
  "use strict";
  async function describeWorkbook({Excel}) {
    if (!Excel) throw new Error("Hãy mở add-in trong Excel.");
    return Excel.run(async context => {
      const workbook = context.workbook, sheet = workbook.worksheets.getActiveWorksheet();
      workbook.load("name"); sheet.load("id"); await context.sync();
      return {workbookName: workbook.name, sheetId: sheet.id};
    });
  }
  async function readSelection(environment, dateSystem) {
    const {Office, Excel} = environment;
    if (!Office || !Excel || !Office.context.requirements.isSetSupported("ExcelApi", "1.9")) {
      throw new Error("Cần ExcelApi 1.9 để nhận diện chính xác ô công thức.");
    }
    if (!["1900", "1904"].includes(dateSystem)) throw new Error("Hãy xác nhận hệ ngày 1900 hoặc 1904 của workbook.");
    return Excel.run(async context => {
      const workbook = context.workbook;
      workbook.load("name");
      const sheet = workbook.worksheets.getActiveWorksheet();
      sheet.load("id,name");
      const range = workbook.getSelectedRange();
      range.load("rowIndex,columnIndex,rowCount,columnCount");
      await context.sync();
      if (range.rowCount < 2 || range.rowCount > 100001 || range.columnCount > 200 ||
          (range.rowCount - 1) * range.columnCount > 400000) {
        throw new Error("Chọn vùng có tiêu đề và dữ liệu, trong giới hạn 100.000 dòng, 200 cột, 400.000 ô.");
      }
      // Read the formula mask from Excel, never from a string's leading '='.
      const formulas = range.getSpecialCellsOrNullObject(Excel.SpecialCellType.formulas);
      formulas.load("isNullObject");
      range.load("values,numberFormat");
      await context.sync();
      const formulaCells = [];
      if (!formulas.isNullObject) {
        formulas.areas.load("items/rowIndex,items/columnIndex,items/rowCount,items/columnCount");
        await context.sync();
        for (const area of formulas.areas.items) {
          for (let row = area.rowIndex; row < area.rowIndex + area.rowCount; row++) {
            for (let col = area.columnIndex; col < area.columnIndex + area.columnCount; col++) {
              const r = row - range.rowIndex - 1, c = col - range.columnIndex;
              if (r >= 0 && r < range.rowCount - 1 && c >= 0 && c < range.columnCount) formulaCells.push([r, c]);
            }
          }
        }
      }
      const headers = range.values[0];
      if (headers.some(h => typeof h !== "string" || !h.trim()) || new Set(headers).size !== headers.length) {
        throw new Error("Dòng đầu phải là tên cột dạng chữ, không trống và không trùng.");
      }
      const snapshot = {sourceId: "selected_source", sheetId: sheet.id, headers,
        rows: range.values.slice(1), formulaCells, columnKinds: headers.map(() => "unknown"),
        numberFormats: range.numberFormat.slice(1), dateSystem,
        rowOffset: range.rowIndex + 1, columnOffset: range.columnIndex};
      if (new TextEncoder().encode(JSON.stringify(snapshot)).length > 8 * 1024 * 1024) {
        throw new Error("Vùng đã chọn vượt giới hạn 8 MiB; hãy chọn vùng nhỏ hơn.");
      }
      return {workbookName: workbook.name, sheetName: sheet.name, snapshot};
    });
  }
  async function selectActiveSource({Excel}) {
    if (!Excel) throw new Error("Hãy mở add-in trong Excel.");
    return Excel.run(async context => {
      const range = context.workbook.worksheets.getActiveWorksheet().getUsedRangeOrNullObject(true);
      range.load("isNullObject"); await context.sync();
      if (range.isNullObject) return false;
      range.load("rowCount,columnCount"); await context.sync();
      if (range.rowCount < 2 || range.columnCount < 1) return false;
      range.select(); await context.sync();
      return true;
    });
  }
  async function readWorkbookSources({Office,Excel},dateSystem,onProgress) {
    if(!Office||!Excel||!Office.context.requirements.isSetSupported("ExcelApi","1.9"))throw failure("DP_UNSUPPORTED_PRESERVATION","ExcelApi 1.9 is required for native formula masks.");
    return Excel.run(async context=>{
      const workbook=context.workbook,collection=workbook.worksheets;
      workbook.load("name");collection.load("items/id,items/name");await context.sync();
      if(!["1900","1904"].includes(dateSystem)){
        try {
          const probe=workbook.functions.date(1904,1,1);probe.load("value");await context.sync();
          dateSystem=probe.value===0?"1904":probe.value===1462?"1900":null;
        }catch(_){dateSystem=null;}
        if(!dateSystem)throw failure("DP_DATE_SYSTEM_REQUIRED","Confirm the workbook 1900/1904 date system before scanning.");
      }
      if(collection.items.length>200)throw failure("DP_BACKUP_LIMIT","Workbook contains more than 200 sheets.");
      const sources=[],sourceLabels={},warnings=[];let cells=0,processed=0;
      for(const sheet of collection.items){
        const warn=(code,message)=>warnings.push({sheetId:sheet.id,sheetName:sheet.name,code,message});
        const range=sheet.getUsedRangeOrNullObject(true);range.load("isNullObject");await context.sync();
        if(range.isNullObject){warn("DP_EMPTY_SHEET","Empty worksheet has no tabular data.");}
        else {
          range.load("rowIndex,columnIndex,rowCount,columnCount");await context.sync();
          cells+=range.rowCount*range.columnCount;
          if(cells>400000||range.rowCount>100001||range.columnCount>200)throw failure("DP_BACKUP_LIMIT","All selected worksheet data exceeds the bounded scan.");
          if(range.rowCount<2||range.columnCount<1)warn("DP_NON_TABULAR_SHEET","Worksheet needs a header row and at least one data row.");
          else {
            const formulas=range.getSpecialCellsOrNullObject(Excel.SpecialCellType.formulas);formulas.load("isNullObject");range.load("values,numberFormat");await context.sync();
            const headers=range.values[0],keys=headers.map(h=>typeof h==="string"?h.toLocaleLowerCase("en-US"):null);
            if(headers.some(h=>typeof h!=="string"||!h.trim())||new Set(keys).size!==headers.length)warn("DP_INVALID_HEADERS","Worksheet headers are empty, duplicated or non-text; choose a valid table explicitly.");
            else {
              const formulaCells=[];
              if(!formulas.isNullObject){
                formulas.areas.load("items/rowIndex,items/columnIndex,items/rowCount,items/columnCount");await context.sync();
                for(const area of formulas.areas.items)for(let r=area.rowIndex;r<area.rowIndex+area.rowCount;r++)for(let c=area.columnIndex;c<area.columnIndex+area.columnCount;c++){
                  const rr=r-range.rowIndex-1,cc=c-range.columnIndex;
                  if(rr>=0&&cc>=0&&rr<range.rowCount-1&&cc<range.columnCount)formulaCells.push([rr,cc]);
                }
              }
              const digest=await globalThis.crypto.subtle.digest("SHA-256",new TextEncoder().encode(sheet.id));
              const sourceId="sheet_"+Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,"0")).join("").slice(0,32);
              sources.push({sourceId,sheetId:sheet.id,headers:clone(headers),rows:clone(range.values.slice(1)),formulaCells,
                columnKinds:headers.map(()=>"unknown"),numberFormats:clone(range.numberFormat.slice(1)),dateSystem,
                rowOffset:range.rowIndex+1,columnOffset:range.columnIndex});sourceLabels[sourceId]=sheet.name;
              if(new TextEncoder().encode(JSON.stringify(sources)).length>8*1024*1024)throw failure("DP_BACKUP_LIMIT","Workbook scan exceeds 8 MiB.");
            }
          }
        }
        processed++;if(typeof onProgress==="function")onProgress({processed,total:collection.items.length,sheetName:sheet.name});
      }
      if(!sources.length){const error=failure("DP_NO_TABULAR_SOURCES","No tabular worksheet could be scanned; review the sheet warnings.");error.warnings=warnings;throw error;}
      return {workbookName:workbook.name,dateSystem,sources,sourceLabels,warnings};
    });
  }
  function failure(code, message) { const error = new Error(message); error.code = code; return error; }
  const clone = value => JSON.parse(JSON.stringify(value));
  function canonical(value) {
    if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
    if (value && typeof value === "object") return "{" + Object.keys(value).sort().map(k => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
    return JSON.stringify(value);
  }
  async function imageFingerprint(image) {
    const numberTag=value=>{
      if(typeof value!=="number")return value;
      if(!Number.isFinite(value))throw failure("DP_UNSUPPORTED_PRESERVATION","Non-finite image number.");
      const buffer=new ArrayBuffer(8);new DataView(buffer).setFloat64(0,value===0?0:value,false);
      return {$number:Array.from(new Uint8Array(buffer),b=>b.toString(16).padStart(2,"0")).join("")};
    };
    const compareNames=(a,b)=>{
      const left=Array.from(a.name),right=Array.from(b.name);
      for(let i=0;i<Math.min(left.length,right.length);i++)if(left[i]!==right[i])return left[i].codePointAt(0)-right[i].codePointAt(0);
      return left.length-right.length;
    };
    const sheets = image.sheets.map(sheet => {
      const item = clone(sheet); delete item.sheetId; delete item.preservation;
      for(const [r,c] of item.formulaCells)item.values[r][c]=null;
      for(const key of ["values","formulas"])item[key]=item[key].map(row=>row.map(numberTag));
      return item;
    }).sort(compareNames);
    const bytes = new TextEncoder().encode(canonical({version:1,sheets}));
    const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
    return "sha256:" + Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2,"0")).join("");
  }
  async function exportWorkbookPackage({Office}) {
    const document=Office&&Office.context&&Office.context.document;
    if(!document||typeof document.getFileAsync!=="function")throw failure("DP_UNSUPPORTED_PRESERVATION","Native compressed workbook evidence is required.");
    const call=(owner,method,args)=>new Promise((resolve,reject)=>owner[method](...args,result=>{
      if(result.status==="succeeded"||(Office.AsyncResultStatus&&result.status===Office.AsyncResultStatus.Succeeded))resolve(result.value);
      else reject(failure("DP_BACKUP_FAILED","Native compressed workbook export failed."));
    }));
    const file=await call(document,"getFileAsync",[Office.FileType.Compressed,{sliceSize:1024*1024}]);
    try {
      if(!Number.isInteger(file.size)||file.size<1||file.size>64*1024*1024||!Number.isInteger(file.sliceCount)||file.sliceCount<1||file.sliceCount>64)throw failure("DP_BACKUP_LIMIT","Compressed workbook exceeds 64 MiB evidence bound.");
      const bytes=new Uint8Array(file.size);let offset=0;
      for(let index=0;index<file.sliceCount;index++){
        const slice=await call(file,"getSliceAsync",[index]);
        const data=Uint8Array.from(slice.data);
        if(data.length>1024*1024||offset+data.length>bytes.length)throw failure("DP_BACKUP_FAILED","Native workbook export slice is inconsistent.");
        bytes.set(data,offset);offset+=data.length;
      }
      if(offset!==bytes.length)throw failure("DP_BACKUP_FAILED","Native workbook export is incomplete.");
      return bytes;
    } finally {await call(file,"closeAsync",[]);}
  }
  async function imageFullFingerprint(image,packageFingerprint) {
    const bytes=new TextEncoder().encode(canonical({version:1,semanticFingerprint:await imageFingerprint(image),packageFingerprint}));
    const digest=await globalThis.crypto.subtle.digest("SHA-256",bytes);
    return "sha256:"+Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,"0")).join("");
  }
  function createMutationRuntime(environment) {
    const {Office, Excel, consumeWritePermit,inspectPreservation} = environment;
    const spent = new Set();
    const unsupported = message => failure("DP_UNSUPPORTED_PRESERVATION", message);
    function supported() {
      if (!Office || !Excel || !Office.context.requirements.isSetSupported("ExcelApi","1.13")) throw unsupported("ExcelApi 1.13 is required for preparation mutations.");
    }
    async function capture(context) {
      const workbook = context.workbook, collection = workbook.worksheets;
      collection.load("items/id,items/name"); workbook.protection.load("protected");
      await context.sync();
      if (workbook.protection.protected || collection.items.length > 200) throw unsupported("Protected structure or excessive sheet count.");
      const sheets = []; let cells = 0;
      for (const sheet of collection.items) {
        sheet.protection.load("protected"); sheet.tables.load("items/id");
        const range = sheet.getUsedRangeOrNullObject(false);
        range.load("isNullObject"); await context.sync();
        if (sheet.protection.protected) throw unsupported("Protected worksheets are outside the supported mutation subset.");
        if (range.isNullObject) {
          sheets.push({sheetId:sheet.id,name:sheet.name,rowOffset:0,columnOffset:0,values:[],formulas:[],formulaCells:[],numberFormats:[]}); continue;
        }
        range.load("rowIndex,columnIndex,rowCount,columnCount"); await context.sync();
        cells += range.rowCount * range.columnCount;
        if (cells > 400000 || range.rowCount > 100001 || range.columnCount > 200) throw failure("DP_BACKUP_LIMIT","Workbook exceeds bounded semantic capture.");
        const merged = range.getMergedAreasOrNullObject(); merged.load("isNullObject");
        const formulas = range.getSpecialCellsOrNullObject(Excel.SpecialCellType.formulas); formulas.load("isNullObject");
        range.load("values,formulas,numberFormat"); await context.sync();
        const formulaCells = [], formulaValues = clone(range.formulas);
        if (!formulas.isNullObject) {
          formulas.areas.load("items/rowIndex,items/columnIndex,items/rowCount,items/columnCount"); await context.sync();
          for (const area of formulas.areas.items) for (let r=area.rowIndex;r<area.rowIndex+area.rowCount;r++) for(let c=area.columnIndex;c<area.columnIndex+area.columnCount;c++) {
            const rr=r-range.rowIndex,cc=c-range.columnIndex;
            if (rr>=0 && cc>=0 && rr<range.rowCount && cc<range.columnCount) {formulaCells.push([rr,cc]);formulaValues[rr][cc]=range.formulas[rr][cc];}
          }
        }
        sheets.push({sheetId:sheet.id,name:sheet.name,rowOffset:range.rowIndex,columnOffset:range.columnIndex,
          values:clone(range.values),formulas:formulaValues,formulaCells:formulaCells.sort((a,b)=>a[0]-b[0]||a[1]-b[1]),numberFormats:clone(range.numberFormat)});
      }
      const image = {version:1,sheets};
      if (new TextEncoder().encode(canonical(image)).length > 8*1024*1024) throw failure("DP_BACKUP_LIMIT","Semantic image exceeds 8 MiB.");
      image.fingerprint = await imageFingerprint(image);
      if (environment.preparationBackupEnabled === false) return image;
      if(typeof inspectPreservation!=="function")throw unsupported("Complete native package evidence inspection is required.");
      const evidence=await inspectPreservation({bytes:await exportWorkbookPackage(environment),semanticImage:clone(image)});
      if(!evidence||!evidence.preservation||evidence.preservation.version!==1||typeof evidence.preservation.evidenceId!=="string"||!/^sha256:[a-f0-9]{64}$/.test(evidence.preservation.packageFingerprint)||evidence.fullFingerprint!==await imageFullFingerprint(image,evidence.preservation.packageFingerprint))throw failure("DP_BACKUP_FAILED","Native package evidence was not independently validated.");
      image.preservation=clone(evidence.preservation);image.fullFingerprint=evidence.fullFingerprint;
      return image;
    }
    async function captureAffectedScope() { supported(); return Excel.run(capture); }
    async function authorize(context, attempt, operation, before) {
      if (!attempt || (attempt.operation || attempt.kind) !== operation || !attempt.attemptId || !attempt.writePermit || typeof consumeWritePermit !== "function") throw failure("DP_BINDING_REQUIRED","An authenticated single-use write permit is required.");
      if (attempt.beforeFingerprint !== before.fingerprint) throw failure("DP_SOURCE_STALE","Workbook changed since the reviewed before image.");
      if (Array.isArray(attempt.beforeSheetIds) &&
          (attempt.beforeSheetIds.length !== before.sheets.length ||
           before.sheets.some(sheet => !attempt.beforeSheetIds.includes(sheet.sheetId)))) {
        throw failure("DP_SOURCE_STALE","Worksheet identities changed since review.");
      }
      if(attempt.beforePreservationFingerprint!==before.fullFingerprint)throw failure("DP_SOURCE_STALE","Workbook presentation or structure changed since review.");
      const key = attempt.attemptId + ":" + attempt.writePermit;
      if (spent.has(key)) throw failure("DP_REVIEW_STALE","Write permit has already been consumed.");
      spent.add(key);
      const request={attemptId:attempt.attemptId,writePermit:attempt.writePermit,currentFingerprint:before.fingerprint,operation};
      if (environment.preparationBackupEnabled !== false) request.currentPreservationFingerprint = before.fullFingerprint;
      const permit=await consumeWritePermit(request);
      if (!permit || Object.keys(request).some(k=>permit[k]!==request[k])) throw failure("DP_BINDING_REQUIRED","Server did not authorize the exact operation.");
      // The HTTP round trip may have allowed a user edit; re-read before queuing writes.
      const fresh=await capture(context);
      if (fresh.fingerprint!==before.fingerprint || fresh.fullFingerprint!==before.fullFingerprint || fresh.sheets.some((s,i)=>s.sheetId!==before.sheets[i].sheetId)) throw failure("DP_SOURCE_STALE","Workbook changed while obtaining the permit.");
    }
    function cell(sheet,row,column) {
      const r=row-sheet.rowOffset,c=column-sheet.columnOffset;
      if(r<0||c<0||r>=sheet.values.length||c>=sheet.values[r].length) throw unsupported("Cleanup is outside the reviewed source frame.");
      if(sheet.formulaCells.some(([rr,cc])=>rr===r&&cc===c)) throw unsupported("Formula cells cannot be cleaned or restored.");
      return {r,c};
    }
    async function delta(attempt, changes, operation) {
      supported(); if(!Array.isArray(changes)||!changes.length||changes.length>400000) throw unsupported("A bounded exact-cell delta is required.");
      return Excel.run(async context=>{
        const before=await capture(context), seen=new Set(), retained=[];
        const copies=attempt.targetCopies||[],occupied=new Set(before.sheets.map(s=>s.name.toLowerCase())),copySources=new Set();
        for(const copy of copies){
          if(!["cleanup","restore","redo"].includes(operation)||copySources.has(copy.sourceSheetId)||!before.sheets.some(s=>s.sheetId===copy.sourceSheetId)||typeof copy.targetName!=="string"||!copy.targetName||copy.targetName.length>31||/[\x00-\x1f\[\]:*?/\\]/.test(copy.targetName)||/^'|'$/.test(copy.targetName)||copy.targetName.toLowerCase()==="history"||occupied.has(copy.targetName.toLowerCase()))throw unsupported("Personal copy requires unique reviewed sources and target names.");
          copySources.add(copy.sourceSheetId);occupied.add(copy.targetName.toLowerCase());
        }
        if (environment.preparationBackupEnabled === false && copies.length) {
          const sources = copies.map(copy => context.workbook.worksheets.getItem(copy.sourceSheetId));
          for (const source of sources) {
            source.tables.load("items/id");
            if (source.names) source.names.load("items/name");
          }
          await context.sync();
          if (sources.some(source => source.tables.items.length || source.names?.items?.length)) {
            throw unsupported("Personal result copies with Tables or scoped names require separate support.");
          }
        }
        for(const change of changes) {
          const sheet=before.sheets.find(s=>s.sheetId===change.sheetId);
          if(!sheet||!Number.isInteger(change.row)||!Number.isInteger(change.column)) throw unsupported("Unknown delta sheet or cell.");
          const {r,c}=cell(sheet,change.row,change.column), key=change.sheetId+":"+r+":"+c;
          if(seen.has(key)) throw unsupported("Duplicate cleanup cell."); seen.add(key);
          if(canonical(sheet.values[r][c])!==canonical(change.before)) throw failure("DP_SOURCE_STALE","Cleanup cell no longer matches review.");
          if(change.after!==null && !["string","number","boolean"].includes(typeof change.after) || typeof change.after==="number"&&!Number.isFinite(change.after)) throw unsupported("Unsupported literal delta.");
          const format=change.numberFormat == null ? sheet.numberFormats[r][c] : change.numberFormat;
          if(typeof format!=="string"||format.length>256) throw unsupported("Unsupported number format.");
          retained.push({...clone(change),beforeNumberFormat:sheet.numberFormats[r][c],numberFormat:format});
        }
        // Capture may preserve merged source sheets for import/copy, but literal
        // cleanup must never implicitly redirect a merged-cell assignment.
        const mergedTargets=retained.map(change=>{
          const target=context.workbook.worksheets.getItem(change.sheetId).getRangeByIndexes(change.row,change.column,1,1).getMergedAreasOrNullObject();
          target.load("isNullObject");return target;
        });
        await context.sync();
        if(mergedTargets.some(target=>!target.isNullObject))throw unsupported("Cleanup cannot write a merged cell.");
        await authorize(context,attempt,operation,before);
        let started=false;const created=[],idMap=new Map();
        try {
          for(const copy of copies){
            const source=context.workbook.worksheets.getItem(copy.sourceSheetId);
            started=true;const result=source.copy(Excel.WorksheetPositionType.after,source);result.name=copy.targetName;result.load("id");
            await context.sync();created.push(result.id);idMap.set(copy.sourceSheetId,result.id);
          }
          const ranges=retained.map(change=>{
            change.sheetId=idMap.get(change.sheetId)||change.sheetId;
            const range=context.workbook.worksheets.getItem(change.sheetId).getRangeByIndexes(change.row,change.column,1,1);
            started=true;
            // Text format prevents '=...' literals becoming formulas; restore chosen display format afterwards.
            if(typeof change.after==="string") range.numberFormat=[["@"]];
            return range;
          });
          await context.sync();
          ranges.forEach((range,index)=>{range.values=[[retained[index].after]];});
          await context.sync();
          ranges.forEach((range,index)=>{range.numberFormat=[[retained[index].numberFormat]];});
          await context.sync(); const after=await capture(context);
          for(const sourceId of copySources){
            if(canonical(before.sheets.find(s=>s.sheetId===sourceId))!==canonical(after.sheets.find(s=>s.sheetId===sourceId)))throw Error("Personal source was changed");
          }
          for(const change of retained) {
            const s=after.sheets.find(x=>x.sheetId===change.sheetId),{r,c}=cell(s,change.row,change.column);
            if(canonical(s.values[r][c])!==canonical(change.after)||s.numberFormats[r][c]!==change.numberFormat) throw Error("Delta read-back mismatch");
          }
          if(attempt.expectedFingerprint && after.fingerprint!==attempt.expectedFingerprint)throw Error("Expected semantic fingerprint mismatch");
          if(attempt.expectedPreservationFingerprint&&after.fullFingerprint!==attempt.expectedPreservationFingerprint)throw Error("Expected preservation fingerprint mismatch");
          return {phase:"verified",operation,before,after,changes:retained,createdSheetIds:created};
        } catch(error) { if(started) throw failure("DP_PARTIAL_UNKNOWN","Excel write or read-back failed; recovery must inspect the pending attempt."); throw error; }
      });
    }
    const applyCleanup=(attempt,changes)=>delta(attempt,changes,"cleanup");
    async function importReviewedSources(attempt, packages, onProgress) {
      supported(); if(!Array.isArray(packages)||!packages.length) throw unsupported("Reviewed source packages are required.");
      return Excel.run(async context=>{
        const before=await capture(context), used=new Set(before.sheets.map(s=>s.name.toLowerCase())), plans=[];
        context.workbook.names.load("items/name");
        for(const sheet of context.workbook.worksheets.items){sheet.tables.load("items/name");if(sheet.names)sheet.names.load("items/name");}
        await context.sync();
        const namespaceNames=new Set(context.workbook.names.items.map(n=>n.name.split("!").pop().toLowerCase()));
        for(const sheet of context.workbook.worksheets.items)for(const name of (sheet.names&&sheet.names.items)||[])namespaceNames.add(name.name.split("!").pop().toLowerCase());
        const tableNames=new Set(context.workbook.worksheets.items.flatMap(s=>s.tables.items.map(t=>t.name.toLowerCase())));
        for(const pkg of packages) {
          if(!["csv","xlsx"].includes(pkg.kind)||!Array.isArray(pkg.sheets)||!pkg.sheets.length) throw unsupported("Unknown import package.");
          if(pkg.kind==="xlsx"){
            const epoch=context.workbook.functions.date(1904,1,1);epoch.load("value,error");await context.sync();
            if(epoch.error||epoch.value!==1462)throw unsupported("Chưa hỗ trợ nhập XLSX vào workbook dùng hệ ngày 1904 hoặc chưa xác định được hệ ngày.");
            if(!pkg.base64||!pkg.preflight||pkg.preflight.validated!==true||["externalLinks","protected"].some(k=>pkg.preflight[k]!==false))throw unsupported("Protected or externally linked XLSX cannot be safely imported.");
            const ns=pkg.namespace;
            if(ns){
              if(!/^[a-f0-9]{16}$/.test(ns.namespaceId)||!/^[a-f0-9]{64}$/.test(ns.sourceSha256)||!Array.isArray(ns.sheets)||canonical(ns.sheets)!==canonical(pkg.sheets.map(s=>({sourceName:s.sourceName,targetName:s.targetName})))||!Array.isArray(ns.names)||!Array.isArray(ns.tables)||!pkg.nativePreservation||!/^sha256:[a-f0-9]{64}$/.test(pkg.nativePreservation.packageFingerprint))throw unsupported("XLSX native namespace does not match the reviewed sheet group.");
              for(const [entries,occupied,suffix] of [[ns.names,namespaceNames,"n"],[ns.tables,tableNames,"t"]])for(let i=0;i<entries.length;i++){
                const name=entries[i].targetName;
                if(name!=="_dp_"+ns.namespaceId+"_"+suffix+i||occupied.has(name.toLowerCase()))throw unsupported("XLSX reviewed native namespace collides with the target workbook.");
                occupied.add(name.toLowerCase());
              }
            }else if(["definedNames","tables","merges"].some(k=>pkg.preflight[k]!==false)||pkg.sheets.some(s=>s.sourceName!==s.targetName))throw unsupported("Structured or renamed XLSX requires independently reviewed native normalization.");
          }
          for(const s of pkg.sheets) {
            if(typeof s.targetName!=="string" || !s.targetName || s.targetName.length>31 || /[\x00-\x1f\[\]:*?/\\]/.test(s.targetName) || /^'|'$/.test(s.targetName) || s.targetName.toLowerCase()==="history" || used.has(s.targetName.toLowerCase())) throw unsupported("Reviewed target sheet name conflicts or is invalid.");
            used.add(s.targetName.toLowerCase());
            if(pkg.kind==="csv" && (!Array.isArray(s.values)||!s.values.length||!s.values[0].length||s.values.length*s.values[0].length>400000||s.values.some(r=>r.length!==s.values[0].length||r.some(v=>typeof v!=="string")))) throw unsupported("CSV requires rectangular bounded literal text.");
          }
          plans.push(pkg);
        }
        await authorize(context,attempt,attempt.operation||attempt.kind,before);
        const created=[];let started=false,processed=0;
        try {
          for(const pkg of plans) {
            const group=[];
            if(pkg.kind==="csv") for(const s of pkg.sheets) {
              started=true;const sheet=context.workbook.worksheets.add(s.targetName);
              const range=sheet.getRangeByIndexes(0,0,s.values.length,s.values[0].length);
              range.numberFormat=s.values.map(r=>r.map(()=>"@"));await context.sync();
              range.values=clone(s.values);sheet.load("id");
              await context.sync();created.push(sheet.id);group.push(sheet.id);
            } else {
              started=true;const inserted=context.workbook.insertWorksheetsFromBase64(pkg.base64,{sheetNamesToInsert:[]});await context.sync();
              if(!Array.isArray(inserted.value)||inserted.value.length!==pkg.sheets.length) throw Error("Incomplete native insertion");
              created.push(...inserted.value);group.push(...inserted.value);
            }
            // Count a file only after Excel returned every exact reviewed
            // worksheet identity/name; progress never advances on a timer.
            const insertedSheets=group.map(id=>context.workbook.worksheets.getItem(id));
            for(const sheet of insertedSheets)sheet.load("id,name");
            await context.sync();
            if(new Set(group).size!==pkg.sheets.length||insertedSheets.some(sheet=>!pkg.sheets.some(plan=>plan.targetName===sheet.name)))throw Error("Native insertion differs from reviewed target group");
            processed++;if(typeof onProgress==="function")onProgress({processed,total:plans.length,fileId:pkg.fileId});
          }
          const after=await capture(context);
          if(created.some(id=>!after.sheets.some(s=>s.sheetId===id))) throw Error("Inserted sheet read-back missing");
          if(attempt.expectedFingerprint && after.fingerprint!==attempt.expectedFingerprint)throw Error("Expected semantic fingerprint mismatch");
          return {phase:"verified",operation:"import",before,after,createdSheetIds:created};
        }catch(error){if(started)throw failure("DP_PARTIAL_UNKNOWN","Import may have partially written; retained attempt needs recovery.");throw error;}
      });
    }
    async function copyPersonalResult(attempt, sources) {
      supported();if(!Array.isArray(sources)||!sources.length)throw unsupported("Reviewed personal sources are required.");
      return Excel.run(async context=>{
        const before=await capture(context),used=new Set(before.sheets.map(s=>s.name.toLowerCase()));
        sources=sources.map(s=>({...s,sheetId:s.sheetId||s.sourceSheetId}));
        for(const source of sources) {
          if(!before.sheets.some(s=>s.sheetId===source.sheetId)||typeof source.targetName!=="string"||!source.targetName||source.targetName.length>31||/[\[\]:*?/\\\x00-\x1f]/.test(source.targetName)||used.has(source.targetName.toLowerCase()))throw unsupported("Personal result requires a unique reviewed target.");
          used.add(source.targetName.toLowerCase());
        }
        await authorize(context,attempt,"copy",before);const created=[];
        try {
          for(const source of sources){const sheet=context.workbook.worksheets.getItem(source.sheetId);const copy=sheet.copy(Excel.WorksheetPositionType.after,sheet);copy.name=source.targetName;copy.load("id");await context.sync();created.push(copy.id);}
          const after=await capture(context);
          for(const source of before.sheets)if(canonical(source)!==canonical(after.sheets.find(s=>s.sheetId===source.sheetId)))throw Error("Personal source changed");
          return {phase:"verified",operation:"copy",before,after,createdSheetIds:created};
        }catch(error){throw failure("DP_PARTIAL_UNKNOWN","Native copy or verification failed.");}
      });
    }
    async function restoreAffectedScope(attempt, image) {
      image=image||attempt;
      if(image.kind==="cleanup"&&image.direction==="undo"&&image.createdSheetIds&&image.createdSheetIds.length){
        image={...image,kind:"copy",inverseChanges:image.changes.filter(c=>!image.createdSheetIds.includes(c.sheetId)).map(c=>({...c,before:c.after,after:c.before,numberFormat:c.beforeNumberFormat}))};
      }
      if(image.kind==="cleanup") {
        const changes=image.direction==="undo" ? image.changes.map(c=>({...c,before:c.after,after:c.before,numberFormat:c.beforeNumberFormat})) : image.changes;
        return delta(attempt,changes,attempt.operation==="restore"?"restore":image.direction);
      }
      if(image.kind==="import" && image.direction==="redo" && image.packages) {
        return importReviewedSources(attempt,image.packages);
      }
      if(["import","copy"].includes(image.kind) && image.direction==="undo") {
        supported();
        return Excel.run(async context=>{
          const before=await capture(context),ids=image.createdSheetIds;
          if(!Array.isArray(ids)||!ids.length||new Set(ids).size!==ids.length||ids.some(id=>!before.sheets.some(s=>s.sheetId===id))||ids.length>=before.sheets.length)throw unsupported("Recovery requires the exact created native sheet group.");
          const inverse=image.inverseChanges||[],seen=new Set(),inverseRanges=[];
          for(const change of inverse){
            const sheet=before.sheets.find(s=>s.sheetId===change.sheetId);
            if(!sheet||ids.includes(change.sheetId)||!Number.isInteger(change.row)||!Number.isInteger(change.column))throw unsupported("Inverse cleanup must target surviving reviewed cells.");
            const {r,c}=cell(sheet,change.row,change.column),key=change.sheetId+":"+r+":"+c;
            if(seen.has(key)||canonical(sheet.values[r][c])!==canonical(change.before))throw failure("DP_SOURCE_STALE","Inverse cleanup differs from retained cell evidence.");
            seen.add(key);
            if(change.after!==null&&!["string","number","boolean"].includes(typeof change.after)||typeof change.after==="number"&&!Number.isFinite(change.after)||typeof change.numberFormat!=="string"||change.numberFormat.length>256)throw unsupported("Invalid inverse literal or format.");
            const range=context.workbook.worksheets.getItem(change.sheetId).getRangeByIndexes(change.row,change.column,1,1),merged=range.getMergedAreasOrNullObject();merged.load("isNullObject");inverseRanges.push({range,merged,change});
          }
          await context.sync();if(inverseRanges.some(x=>!x.merged.isNullObject))throw unsupported("Inverse cleanup cannot write a merged cell.");
          const names=image.ownedDefinedNames||attempt.ownedDefinedNames||[];
          if(!Array.isArray(names))throw unsupported("Owned namespace provenance is required.");
          const owned=names.filter(n=>typeof n==="string"||n.scope==="workbook").map(n=>typeof n==="string"?n:n.targetName);
          if(new Set(owned).size!==owned.length||owned.some(n=>typeof n!=="string"||!/^_dp_[a-f0-9]{16}_n\d+$/.test(n)))throw unsupported("Only exact reviewed native namespace names can be removed.");
          context.workbook.names.load("items/name,items/formula");
          for(const s of context.workbook.worksheets.items)if(!ids.includes(s.id)&&s.names)s.names.load("items/name,items/formula");
          await context.sync();
          if(owned.some(name=>!context.workbook.names.items.some(n=>n.name===name)))throw unsupported("Owned namespace name is missing or changed.");
          const removedNames=before.sheets.filter(s=>ids.includes(s.sheetId)).map(s=>s.name.toLowerCase());
          const dependent=expression=>{
            if(typeof expression!=="string")return true;
            // String indirection can conceal a dependency; never guess through it.
            if(/\b(?:INDIRECT|OFFSET|EVALUATE|CALL|REGISTER\.ID)\s*\(/i.test(expression)||/[\[\]]/.test(expression))return true;
            const folded=expression.toLowerCase();
            if(owned.some(name=>new RegExp("(^|[^a-z0-9_.])"+name.toLowerCase()+"([^a-z0-9_.]|$)").test(folded)))return true;
            // Quoted and unquoted sheet tokens are decoded without rewriting.
            const tokens=Array.from(expression.matchAll(/(?:'((?:[^']|'')+)'|([A-Za-z_\u0080-\uffff][A-Za-z0-9_.\u0080-\uffff]*))!/g),m=>(m[1]?m[1].replace(/''/g,"'"):m[2]).toLowerCase());
            return tokens.some(name=>name.includes(":")||removedNames.includes(name))||/[^'\s]+:[^'\s]+!/.test(expression);
          };
          const survivingNames=context.workbook.names.items.filter(n=>!owned.includes(n.name));
          for(const s of context.workbook.worksheets.items)if(!ids.includes(s.id)&&s.names)survivingNames.push(...s.names.items);
          if(survivingNames.some(n=>dependent(n.formula))||before.sheets.some(s=>!ids.includes(s.sheetId)&&s.formulaCells.some(([r,c])=>dependent(s.formulas[r][c]))))throw unsupported("Surviving formulas or names may depend on the owned sheet group.");
          await authorize(context,attempt,attempt.operation==="restore"?"restore":"undo",before);
          try {
            for(const {range,change} of inverseRanges)if(typeof change.after==="string")range.numberFormat=[["@"]];
            if(inverseRanges.length)await context.sync();
            for(const {range,change} of inverseRanges)range.values=[[change.after]];
            if(inverseRanges.length)await context.sync();
            for(const {range,change} of inverseRanges)range.numberFormat=[[change.numberFormat]];
            for(const name of owned)context.workbook.names.getItem(name).delete();
            for(const id of ids)context.workbook.worksheets.getItem(id).delete();
            await context.sync();const after=await capture(context);
            if(ids.some(id=>after.sheets.some(s=>s.sheetId===id)))throw Error("Created sheet remains");
            if(attempt.expectedFingerprint && after.fingerprint!==attempt.expectedFingerprint)throw Error("Expected semantic fingerprint mismatch");
            if(attempt.expectedPreservationFingerprint&&after.fullFingerprint!==attempt.expectedPreservationFingerprint)throw Error("Expected preservation fingerprint mismatch");
            return {phase:"verified",operation:"undo",before,after,createdSheetIds:[]};
          }catch(error){throw failure("DP_PARTIAL_UNKNOWN","Created-sheet undo requires inspection after a write failure.");}
        });
      }
      // Generic delete/reinsert restoration cannot preserve stable worksheet references.
      throw unsupported("Created-sheet recovery requires dependency-qualified native proof; generic staging restore is disabled.");
    }
    async function verifyAffectedScope(expected) {
      const actual=await captureAffectedScope();
      if(actual.fingerprint!==expected.fingerprint)throw failure("DP_RESTORE_CONFLICT","Affected workbook semantics changed.");
      if(actual.fullFingerprint!==expected.fullFingerprint)throw failure("DP_RESTORE_CONFLICT","Workbook presentation or structure changed.");
      if(expected.sheets.some(s=>!actual.sheets.some(a=>a.sheetId===s.sheetId&&a.name===s.name)))throw failure("DP_RESTORE_CONFLICT","Native sheet identity changed.");
      return actual;
    }
    return {captureAffectedScope,importReviewedSources,copyPersonalResult,applyCleanup,restoreAffectedScope,verifyAffectedScope};
  }
  const api = {readSelection, describeWorkbook, selectActiveSource,readWorkbookSources,createMutationRuntime,imageFingerprint,imageFullFingerprint,exportWorkbookPackage};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReqwisePreparationRuntime = api;
})(typeof window !== "undefined" ? window : globalThis);
