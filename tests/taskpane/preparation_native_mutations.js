"use strict";
const assert = require("node:assert/strict");
const api = require("../../pbip_assistant/excel_addin/preparation_runtime.js");
// The Office boundary models literal writes, formula masks and native sheet IDs.
function host() {
  const sheets = [], writes = [];let syncCount=0;
  function add(name, values = [["Code"], [" x "]], mask = []) {
    const sheet = {id: "id" + sheets.length, name, load() {}, protection: {protected: false, load() {}},
      tables: {items: [], load() {}}, names:{items:[],load(){}}, charts:{items:[],load(){}}, shapes:{items:[],load(){}}, pivotTables:{items:[],load(){}}, visibility:"Visible",
      bold:false,rowHeight:15,columnWidth:60,values, formats: values.map(r => r.map(() => "General")), mask};
    sheet.getRangeByIndexes = (ro, co, nr, nc) => {
      const range = {rowIndex: ro, columnIndex: co, rowCount: nr, columnCount: nc, load() {},
        getMergedAreasOrNullObject: () => ({isNullObject: true, load() {}}),
        getSpecialCellsOrNullObject: () => ({isNullObject: !mask.length, load() {}, areas: {load() {}, items: mask.map(([r,c]) => ({rowIndex:r,columnIndex:c,rowCount:1,columnCount:1}))}})};
      for (const [key, source] of [["values","values"],["numberFormat","formats"],["formulas","values"]]) {
        Object.defineProperty(range,key,{get:()=>sheet[source].slice(ro,ro+nr).map(r=>r.slice(co,co+nc)),set:rows=>{
          writes.push([sheet.id,key,ro,co,rows,syncCount]);
          rows.forEach((row,r)=>row.forEach((v,c)=>{ (sheet[source][ro+r] ||= [])[co+c]=v; }));
        }});
      }
      return range;
    };
    sheet.getUsedRangeOrNullObject = () => Object.assign(sheet.getRangeByIndexes(0,0,sheet.values.length,sheet.values[0].length),{isNullObject:false});
    sheet.delete = () => { writes.push([sheet.id,"delete"]); sheets.splice(sheets.indexOf(sheet),1); };
    sheet.copy = () => {writes.push([sheet.id,"copy"]);const copied=add(sheet.name+" copy",JSON.parse(JSON.stringify(sheet.values)),JSON.parse(JSON.stringify(sheet.mask)));copied.formats=JSON.parse(JSON.stringify(sheet.formats));return copied;};
    sheets.push(sheet); return sheet;
  }
  add("Source");
  const workbook = {name:"Synthetic",load(){},functions:{date:()=>({value:1462,load(){}})},protection:{protected:false,load(){}},names:{items:[],load(){}},worksheets:{items:sheets,load(){},getItem:id=>{
    const s=sheets.find(x=>x.id===id || x.name===id); if(!s) throw Error("missing sheet"); return s;
  },add:name=>{writes.push([name,"add"]); return add(name,[[""]]);}}};
  workbook.insertWorksheetsFromBase64=(base64,options)=>{assert.equal(base64,"safe-native-package");assert.deepEqual(options,{sheetNamesToInsert:[]});writes.push(["native","insert"]);return{value:[add("Native",[["ID"],["001"]]).id,add("Rates",[["Rate"],["2"]]).id]};};
  const bytes=new Uint8Array([1,2,3]);
  const Office={FileType:{Compressed:"compressed"},context:{document:{getFileAsync(type,options,callback){callback({status:"succeeded",value:{size:3,sliceCount:1,getSliceAsync(index,cb){cb({status:"succeeded",value:{data:bytes}});},closeAsync(cb){cb({status:"succeeded"});}}});}},requirements:{isSetSupported:()=>true}}};
  const inspectPreservation=async({semanticImage})=>{const digest=await globalThis.crypto.subtle.digest("SHA-256",new TextEncoder().encode(JSON.stringify(sheets.map(s=>({name:s.name,values:s.values,formats:s.formats,bold:s.bold,rowHeight:s.rowHeight,columnWidth:s.columnWidth})))));const fingerprint="sha256:"+Buffer.from(digest).toString("hex");return{preservation:{version:1,packageFingerprint:fingerprint,evidenceId:"test-evidence"},fullFingerprint:await api.imageFullFingerprint(semanticImage,fingerprint)};};
  return {sheets,writes,add,workbook,Office,inspectPreservation, Excel:{WorksheetPositionType:{after:"After"},SpecialCellType:{formulas:"Formulas"},run:async fn=>fn({workbook,sync:async()=>{syncCount++;}})}};
}
let sequence=0;
async function attempt(runtime, operation) {
  const before = await runtime.captureAffectedScope();
  return {attemptId:"attempt"+(++sequence),writePermit:"permit"+sequence,operation,beforeFingerprint:before.fingerprint,beforePreservationFingerprint:before.fullFingerprint};
}
(async()=>{
  assert.equal(typeof api.createMutationRuntime,"function","native adapter factory must be available");
  const directHost=host();
  let directPermits=0;
  const direct=api.createMutationRuntime({...directHost,preparationBackupEnabled:false,
    inspectPreservation:async()=>{throw Error("no-backup mode must not export target packages");},
    consumeWritePermit:async request=>{directPermits++;assert(!("currentPreservationFingerprint" in request));return request;}});
  const directBefore=await direct.captureAffectedScope();
  assert.equal(directBefore.preservation,undefined);
  assert.equal(directBefore.fullFingerprint,undefined);
  const directAttempt=await attempt(direct,"cleanup");
  const directResult=await direct.applyCleanup(directAttempt,[{sheetId:"id0",row:1,column:0,before:" x ",after:"x"}]);
  assert.equal(directPermits,1);
  assert.equal(directResult.phase,"verified");
  assert.equal(directHost.sheets[0].values[1][0],"x");
  const replacedHost=host();let replacedPermits=0;
  const replacedRuntime=api.createMutationRuntime({...replacedHost,preparationBackupEnabled:false,
    consumeWritePermit:async request=>{replacedPermits++;return request;}});
  const reviewedAttempt={...await attempt(replacedRuntime,"cleanup"),beforeSheetIds:["id0"]};
  replacedHost.sheets[0].id="replacement-id";
  await assert.rejects(replacedRuntime.applyCleanup(reviewedAttempt,[{sheetId:"replacement-id",row:1,column:0,before:" x ",after:"x"}]),error=>error.code==="DP_SOURCE_STALE");
  assert.equal(replacedPermits,0,"identical data on a replacement sheet cannot consume the reviewed permit");
  assert.equal(replacedHost.writes.length,0);
  const scanHost=host();scanHost.sheets[0].mask.push([1,0]);scanHost.add("Other",[["ID"],["007"]]);scanHost.add("Notes",[[""]]);
  const progress=[];const scanned=await api.readWorkbookSources(scanHost,undefined,p=>progress.push(p));
  assert.equal(scanned.dateSystem,"1900");assert.equal(scanned.sources.length,2);
  assert.equal(scanned.sources[1].rows[0][0],"007");assert.equal(scanned.sources[1].rowOffset,1);
  assert.deepEqual(scanned.sources[0].formulaCells,[[0,0]],"whole workbook scanning uses Excel formula mask");
  assert.equal(scanned.warnings.length,1,"non-tabular sheet is explicitly reported");
  assert.equal(progress.length,3,"each processed sheet reports real progress");
  scanHost.workbook.functions.date=()=>({value:100,load(){}});
  await assert.rejects(api.readWorkbookSources(scanHost),e=>e.code==="DP_DATE_SYSTEM_REQUIRED");
  const confirmed=await api.readWorkbookSources(scanHost,"1904");assert.equal(confirmed.dateSystem,"1904");
  const numericImage={version:1,sheets:[{sheetId:"sheet",name:"Numbers",rowOffset:0,columnOffset:0,
    values:[[1e-7,1e20,-0,42]],formulas:[[1e-7,1e20,-0,"=21*2"]],formulaCells:[[0,3]],numberFormats:[["General","General","General","General"]]}]};
  const firstHash=await api.imageFingerprint(numericImage);
  numericImage.sheets[0].values[0][3]=43;
  assert.equal(await api.imageFingerprint(numericImage),firstHash,"cached formula results do not change immutable formula semantics");
  const python=require("node:child_process").spawnSync("py",["-c","import json,sys;from pbip_assistant.sources.preparation.packages import image_fingerprint;print(image_fingerprint(json.load(sys.stdin)))"],{input:JSON.stringify(numericImage),encoding:"utf8",cwd:require("node:path").join(__dirname,"../..")});
  assert.equal(python.status,0,python.stderr);
  assert.equal(firstHash,python.stdout.trim(),"native/Python fingerprints agree for numeric notation and formula caches");
  let env=host(), permits=0;
  const runtime=api.createMutationRuntime({...env,consumeWritePermit:async p=>{permits++;return p;}});
  const styledBefore=await runtime.captureAffectedScope();
  env.sheets[0].bold=true;
  const styledAfter=await runtime.captureAffectedScope();
  assert.equal(styledBefore.fingerprint,styledAfter.fingerprint);
  assert.notEqual(styledBefore.fullFingerprint,styledAfter.fullFingerprint,"manual formatting must invalidate recovery evidence");
  env.sheets[0].bold=false;
  const pyFull=require("node:child_process").spawnSync("py",["-c","import json,sys;from pbip_assistant.sources.preparation.image_model import preservation_fingerprint;print(preservation_fingerprint(json.load(sys.stdin)))"],{input:JSON.stringify(styledBefore),encoding:"utf8",cwd:require("node:path").join(__dirname,"../..")});
  assert.equal(pyFull.status,0,pyFull.stderr);assert.equal(styledBefore.fullFingerprint,pyFull.stdout.trim());
  let a=await attempt(runtime,"cleanup");
  const receipt=await runtime.applyCleanup(a,[{sheetId:"id0",row:1,column:0,before:" x ",after:"x",numberFormat:null}]);
  assert.equal(env.sheets[0].values[1][0],"x");
  assert.equal(permits,1);
  assert.equal(receipt.phase,"verified");
  assert.equal(env.writes.filter(w=>w[1]==="values").length,1,"cleanup touches only exact changed cell");
  assert(env.writes.find(w=>w[1]==="numberFormat")[5]<env.writes.find(w=>w[1]==="values")[5],"literal text format is synchronized before setting values");
  a=await attempt(runtime,"undo");
  await runtime.restoreAffectedScope(a,{kind:"cleanup",direction:"undo",changes:receipt.changes});
  assert.equal(env.sheets[0].values[1][0]," x ");
  a=await attempt(runtime,"redo");
  await runtime.restoreAffectedScope(a,{kind:"cleanup",direction:"redo",changes:receipt.changes});
  assert.equal(env.sheets[0].values[1][0],"x","redo replays only retained exact deltas");
  a=await attempt(runtime,"cleanup");
  await runtime.applyCleanup(a,[{sheetId:"id0",row:1,column:0,before:"x",after:" x "}]);
  env.sheets[0].values[1][0]="manual";
  await assert.rejects(runtime.applyCleanup(a,[{sheetId:"id0",row:1,column:0,before:" x ",after:"x"}]),e=>e.code==="DP_SOURCE_STALE");
  env=host();env.sheets[0].mask.push([1,0]);
  const formulaRuntime=api.createMutationRuntime({...env,consumeWritePermit:async p=>p});
  a=await attempt(formulaRuntime,"cleanup");
  await assert.rejects(formulaRuntime.applyCleanup(a,[{sheetId:"id0",row:1,column:0,before:" x ",after:"x"}]),e=>e.code==="DP_UNSUPPORTED_PRESERVATION");
  assert.equal(env.writes.length,0);
  env=host();const csvRuntime=api.createMutationRuntime({...env,consumeWritePermit:async p=>p});
  a=await attempt(csvRuntime,"import");
  const imported=await csvRuntime.importReviewedSources(a,[{kind:"csv",fileId:"f",sheets:[{sourceSheetId:"s",sourceName:"Data",targetName:"Data",values:[["Code"],["=1+1"],["00123"]],numberFormats:[["@"],["@"],["@"]]}]}]);
  assert.equal(env.sheets[1].formats[1][0],"@");
  assert.equal(env.sheets[1].values[1][0],"=1+1");
  assert.equal(imported.createdSheetIds.length,1);
  const typedEnv=host();const typedRuntime=api.createMutationRuntime({...typedEnv,consumeWritePermit:async p=>p});
  a=await attempt(typedRuntime,"import");
  const typedPackage={kind:"csv",fileId:"t",sheets:[{sourceSheetId:"s",sourceName:"Typed",targetName:"Typed",
    values:[["Code","Qty","Date"],["A",2,1462],["B",null,null]],
    numberFormats:[["@","@","@"],["@","General","yyyy-mm-dd"],["@","General","General"]]}]};
  const typedReceipt=await typedRuntime.importReviewedSources(a,[typedPackage]);
  assert.equal(typedEnv.sheets[1].values[1][1],2,"numbers are written as numbers, not text");
  assert.equal(typedEnv.sheets[1].formats[1][1],"General");
  assert.equal(typedEnv.sheets[1].formats[1][2],"yyyy-mm-dd");
  assert.equal(typedEnv.sheets[1].values[2][1],null,"an empty CSV cell stays blank");
  assert.equal(typedEnv.sheets[1].formats[2][1],"General");
  const formatWrite=typedEnv.writes.find(w=>w[1]==="numberFormat"),valuesWrite=typedEnv.writes.find(w=>w[1]==="values");
  assert(formatWrite[5]<valuesWrite[5],"per-cell number formats are set before typed values");
  assert.equal(typedReceipt.createdSheetIds.length,1);
  const probe1900=host(),probe1904=host(),probeUnknown=host();
  probe1904.workbook.functions.date=()=>({value:0,load(){},error:null});
  probeUnknown.workbook.functions.date=()=>({value:99,load(){},error:null});
  assert.equal(await api.probeDateSystem(probe1900),"1900");
  assert.equal(await api.probeDateSystem(probe1904),"1904");
  await assert.rejects(api.probeDateSystem(probeUnknown),e=>e.code==="DP_DATE_SYSTEM_REQUIRED");
  a=await attempt(csvRuntime,"import"); const count=env.writes.length;
  await assert.rejects(csvRuntime.importReviewedSources(a,[{kind:"csv",sheets:[{targetName:"Data",values:[["x"]]}]}]),e=>e.code==="DP_UNSUPPORTED_PRESERVATION");
  assert.equal(env.writes.length,count,"mapping collision fails before writes");
  a=await attempt(csvRuntime,"undo");
  await csvRuntime.restoreAffectedScope(a,{kind:"import",direction:"undo",createdSheetIds:imported.createdSheetIds});
  assert.equal(env.sheets.length,1,"undo deletes only owned sheets");
  env=host();env.add("Constant",[["=1+1"]],[[0,0]]);
  env.workbook.names.items.push({name:"TaxRate",formula:"=100"});
  const constantRecovery=api.createMutationRuntime({...env,consumeWritePermit:async p=>p});
  a=await attempt(constantRecovery,"import");
  const constantImported=await constantRecovery.importReviewedSources(a,[{kind:"csv",sheets:[{targetName:"Owned",values:[["ID"],["1"]],numberFormats:[["@"],["@"]]}]}]);
  a=await attempt(constantRecovery,"undo");
  await constantRecovery.restoreAffectedScope(a,{kind:"import",direction:"undo",createdSheetIds:constantImported.createdSheetIds});
  assert.equal(env.sheets.length,2,"unrelated names and constant formulas preserve safe owned-sheet undo");
  env=host();env.add("Dependent",[["=Owned!A1"]],[[0,0]]);
  const dependentRecovery=api.createMutationRuntime({...env,consumeWritePermit:async p=>p});
  a=await attempt(dependentRecovery,"import");
  const dependentImported=await dependentRecovery.importReviewedSources(a,[{kind:"csv",sheets:[{targetName:"Owned",values:[["ID"],["1"]],numberFormats:[["@"],["@"]]}]}]);
  a=await attempt(dependentRecovery,"undo");const deleteCount=env.writes.filter(w=>w[1]==="delete").length;
  await assert.rejects(dependentRecovery.restoreAffectedScope(a,{kind:"import",direction:"undo",createdSheetIds:dependentImported.createdSheetIds}),e=>e.code==="DP_UNSUPPORTED_PRESERVATION");
  assert.equal(env.writes.filter(w=>w[1]==="delete").length,deleteCount,"surviving native references block before deletion");
  env=host();const blocked=api.createMutationRuntime({...env,consumeWritePermit:async()=>{throw Error("denied");}});
  a=await attempt(blocked,"cleanup");
  await assert.rejects(blocked.applyCleanup(a,[{sheetId:"id0",row:1,column:0,before:" x ",after:"x"}]),/denied/);
  assert.equal(env.writes.length,0,"server refusal prevents native writes");
  env=host();const race=api.createMutationRuntime({...env,consumeWritePermit:async p=>{env.sheets[0].values[1][0]="edited";return p;}});
  a=await attempt(race,"cleanup");
  await assert.rejects(race.applyCleanup(a,[{sheetId:"id0",row:1,column:0,before:" x ",after:"x"}]),e=>e.code==="DP_SOURCE_STALE");
  assert.equal(env.writes.length,0,"edits during permit exchange prevent native writes");
  env=host();const styleRace=api.createMutationRuntime({...env,consumeWritePermit:async p=>{env.sheets[0].bold=true;return p;}});
  a=await attempt(styleRace,"cleanup");
  await assert.rejects(styleRace.applyCleanup(a,[{sheetId:"id0",row:1,column:0,before:" x ",after:"x"}]),e=>e.code==="DP_SOURCE_STALE");
  assert.equal(env.writes.length,0,"style edits during permit exchange prevent native writes");
  let closed=0;
  const malformed={Office:{FileType:{Compressed:"compressed"},context:{document:{getFileAsync(type,options,callback){
    callback({status:"succeeded",value:{size:2,sliceCount:1,getSliceAsync(index,cb){cb({status:"succeeded",value:{data:[1]}});},closeAsync(cb){closed++;cb({status:"succeeded"});}}});
  }}}}};
  await assert.rejects(api.exportWorkbookPackage(malformed),e=>e.code==="DP_BACKUP_FAILED");
  assert.equal(closed,1,"native export handles close after incomplete slices");
  env=host();const personal=api.createMutationRuntime({...env,consumeWritePermit:async p=>p});
  a=await attempt(personal,"cleanup");a.targetCopies=[{sourceSheetId:"id0",targetName:"Clean"}];
  const copied=await personal.applyCleanup(a,[{sheetId:"id0",row:1,column:0,before:" x ",after:"x",numberFormat:null}]);
  assert.equal(env.sheets[0].values[1][0]," x ","personal source is immutable");
  assert.equal(env.sheets[1].values[1][0],"x");
  assert.equal(copied.createdSheetIds.length,1);
  env=host();env.add("Imported",[["ID"],[" y "]]);
  const mixed=api.createMutationRuntime({...env,consumeWritePermit:async p=>p});
  a=await attempt(mixed,"cleanup");a.targetCopies=[{sourceSheetId:"id0",targetName:"Clean"}];
  const mixedReceipt=await mixed.applyCleanup(a,[{sheetId:"id0",row:1,column:0,before:" x ",after:"x"},{sheetId:"id1",row:1,column:0,before:" y ",after:"y"}]);
  assert.equal(env.sheets[0].values[1][0]," x ");assert.equal(env.sheets[1].values[1][0],"y");
  a=await attempt(mixed,"undo");
  await mixed.restoreAffectedScope(a,{kind:"cleanup",direction:"undo",changes:mixedReceipt.changes,createdSheetIds:mixedReceipt.createdSheetIds});
  assert.equal(env.sheets.length,2);assert.equal(env.sheets[1].values[1][0]," y ","mixed undo restores owned cells and removes personal result in one permit");
  env=host();const native=api.createMutationRuntime({...env,consumeWritePermit:async p=>p});
  const pkg={kind:"xlsx",fileId:"f",base64:"safe-native-package",sheets:[{sourceName:"Native",targetName:"Native"},{sourceName:"Rates",targetName:"Rates"}],preflight:{validated:true,definedNames:false,tables:false,externalLinks:false,protected:false,merges:false}};
  a=await attempt(native,"import");
  const fileProgress=[];
  const nativeReceipt=await native.importReviewedSources(a,[pkg],p=>fileProgress.push(p));
  assert.equal(nativeReceipt.createdSheetIds.length,2);
  assert.equal(env.writes.filter(w=>w[1]==="insert").length,1,"all dependent native sheets insert as one group");
  assert.deepEqual(fileProgress,[{processed:1,total:1,fileId:"f"}],"file progress follows complete native group read-back");
  const epochHost=host();epochHost.workbook.functions.date=()=>({value:0,load(){}});
  const epochRuntime=api.createMutationRuntime({...epochHost,consumeWritePermit:async p=>p});
  const epochAttempt=await attempt(epochRuntime,"import");
  await assert.rejects(epochRuntime.importReviewedSources(epochAttempt,[pkg]),e=>e.code==="DP_UNSUPPORTED_PRESERVATION");
  assert.equal(epochHost.writes.length,0,'cross-epoch XLSX cannot silently shift calendar dates');
  env=host();const unsafe=api.createMutationRuntime({...env,consumeWritePermit:async p=>p});
  a=await attempt(unsafe,"import");
  await assert.rejects(unsafe.importReviewedSources(a,[{...pkg,preflight:{...pkg.preflight,definedNames:true}}]),e=>e.code==="DP_UNSUPPORTED_PRESERVATION");
  assert.equal(env.writes.length,0,"defined-name packages fail before native insertion");
  env.workbook.protection.protected=true;
  await assert.rejects(unsafe.captureAffectedScope(),e=>e.code==="DP_UNSUPPORTED_PRESERVATION");
  env.workbook.protection.protected=false;
  a=await attempt(unsafe,"cleanup");a.expectedFingerprint="sha256:"+"0".repeat(64);
  await assert.rejects(unsafe.applyCleanup(a,[{sheetId:"id0",row:1,column:0,before:" x ",after:"x"}]),e=>e.code==="DP_PARTIAL_UNKNOWN");
  console.log("Preparation native mutation boundary checks passed");
})().catch(e=>{console.error(e);process.exitCode=1;});
