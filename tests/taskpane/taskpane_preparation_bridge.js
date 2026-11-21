"use strict";
const assert=require('node:assert/strict');
const crypto=require('node:crypto').webcrypto;
const api=require('../../pbip_assistant/excel_addin/preparation_bridge.js');
(async()=>{
 const calls=[]; let current={preparationId:'p',sourceHash:'hash',sources:[],writeEnabled:true};
 const image={version:1,sheets:[{sheetId:'existing',name:'Book',values:[['ID'],['A']],formulas:[['ID'],['A']],formulaCells:[],numberFormats:[['General'],['General']],rowOffset:0,columnOffset:0}],fingerprint:'before',fullFingerprint:'full-before'};
 let permit;
 const adapter={captureAffectedScope:async()=>image,importReviewedSources:async(attempt,packages)=>{
   calls.push('native'); assert(calls.includes('image-finish:before')); assert.equal(packages.length,1);
   const result=await permit({attemptId:attempt.attemptId,writePermit:attempt.writePermit,currentFingerprint:'before',currentPreservationFingerprint:'full-before',operation:'import'});
   assert.equal(result.operation,'import'); return {phase:'verified',after:{...image,fingerprint:'after'},createdSheetIds:['new']};
 }};
 let purpose, failPurpose=null; const receipts=[];
 const bridge=api.create({environment:{crypto,btoa:s=>Buffer.from(s,'binary').toString('base64')},
   runtime:{createMutationRuntime:env=>{assert.equal(typeof env.inspectPreservation,'function');permit=env.consumeWritePermit;return adapter;}},
   getState:()=>current,setState:s=>{current=s;},post:async(action,body)=>{
     calls.push(action+(action==='image-finish'?':'+purpose:''));
     if(action==='attach')return {...current,preparationId:'p',claimVersion:0,writeEnabled:true};
     if(action==='pick-folder')return {cancelled:false,path:'root',name:'root'};
     if(action==='browse')return {rootName:'root',relativePath:'',parentRelativePath:null,breadcrumb:[],entries:[],truncated:false};
     if(action==='inventory')return {inventory:{inventoryHash:'inv',files:[{fileId:'f',fileName:'a.csv'}],sheets:[{fileId:'f',sourceSheetId:'csv',proposedName:'Data'}],errors:[]}};
     if(action==='review-import')return {reviewHash:'review'};
     if(action==='packages')return {reviewHash:'review',packages:[{kind:'csv',sheets:[]}],importReport:{totals:{files:1,sheets:1,skipped:0,decisions:0},files:[]}};
     if(action==='approve')return {grantId:'g'};
     if(action==='begin'){assert.equal(body.expectedPreservationFingerprint,'full-before');return {attemptId:'a',writePermit:'nonce',kind:'import',operation:'import',beforeFingerprint:'before',packages:[{kind:'csv',sheets:[]}]};}
     if(action==='image-begin'){purpose=body.purpose;if(purpose===failPurpose)throw Object.assign(new Error('image unavailable'),{code:'DP_BACKUP_FAILED'});return {uploadId:'u',maxChunkBytes:1048576};}
     if(action==='image-finish')return {imageId:'i',fingerprint:purpose==='before'?'before':'after',expectedFingerprint:'after',targetCopies:[]};
     if(action==='write-ready'){assert.equal(body.expectedFingerprint,'before');assert.equal(body.expectedPreservationFingerprint,'full-before');return {attemptId:'a',writePermit:'nonce',currentFingerprint:'before',currentPreservationFingerprint:'full-before',operation:'import'};}
     if(action==='complete'){receipts.push(body.receipt);if(body.receipt.phase!=='verified')return {...current,status:body.receipt.phase};assert.equal(body.receipt.observedFingerprint,'after');return {...current,status:'verified',journal:{status:'ready'}};}
     return {};
   }});
 await bridge.pickRoot();
 const doImport=()=>bridge.importSelection({items:[{relativePath:'',fileName:'a.csv'}],dateSystem:'1900'});
 const receipt=await doImport();
 assert.equal(receipt.status,'verified'); assert.equal(receipt.report.totals.files,1);
 assert(calls.indexOf('write-ready')>calls.indexOf('image-finish:before'));
 const mapped=await bridge.mapInventory({sheets:[{fileId:'f',sourceSheetId:'a',proposedName:'Book'},{fileId:'g',sourceSheetId:'b',proposedName:'Book_2'}]});
 assert.deepEqual(mapped.sheets.map(sheet=>sheet.proposedName),['Book_2','Book_2_2']);
 assert.equal(image.sheets[0].name,'Book','mapping does not rename existing worksheets');
 current={...current,writeEnabled:false};
 const count=calls.length;
 await assert.rejects(doImport,e=>e.code==='DP_UNSUPPORTED_PRESERVATION');
 assert.equal(calls.length,count,'unqualified capability cannot start mutation or uploads');
 current={...current,writeEnabled:true};failPurpose='before';
 await assert.rejects(doImport,e=>e.code==='DP_BACKUP_FAILED');
 assert.equal(receipts.at(-1).phase,'prewrite_failed');
 current={...current,writeEnabled:true};failPurpose='after';
 await assert.rejects(doImport,e=>e.code==='DP_PARTIAL_UNKNOWN');
 assert.equal(receipts.at(-1).phase,'partial_unknown','upload failure after native write freezes authority rather than retrying');
 // Explicit epoch survives approval rereads; native identity and exact rows remain bound.
 for (const epoch of ['1900','1904']) {
   const original={sourceId:'s',sheetId:'native-id',headers:['ID'],rows:[['kept']],formulaCells:[],numberFormats:[['General']],dateSystem:epoch,rowOffset:1,columnOffset:0};
   let live=structuredClone(original), state=null;
   const reader=async (_env,date)=>{if(date!==epoch)throw Object.assign(new Error('epoch lost'),{code:'DP_DATE_SYSTEM_REQUIRED'});return {workbookName:'Book',dateSystem:epoch,sources:[structuredClone(live)],sourceLabels:{s:'Same name'},warnings:[]};};
   const b=api.create({environment:{crypto},runtime:{createMutationRuntime:()=>({captureAffectedScope:async()=>image}),readWorkbookSources:reader},getState:()=>state,setState:value=>{state=value;},post:async(action,body)=>{
     if(action==='attach')return {preparationId:'p',sourceRevision:0};
     if(action==='source-set')return {...state,sourceRevision:1,sourceHash:'reviewed',answerRevision:1,sources:body.snapshots};
     if(action==='scan')return {...state,preview:{reviewHash:'r',changeCount:0}};
   }});
   await assert.rejects(()=>b.businessSourcesFromScan(),e=>e.code==='DP_REVIEW_STALE');
   await b.scanWorkbook({dateSystem:epoch});
   const handoff=await b.businessSourcesFromScan();
   assert.equal(handoff.sources[0].sheetId,'native-id');
   assert.deepEqual(handoff.sources[0].rows,[['kept']]);
   const validated=await handoff.validate();
   assert.equal(validated.observedHash,handoff.observedHash,'the handoff validator returns the reviewed hash so the business gate can compare it');
   live.rows[0][0]='edited';
   await assert.rejects(()=>handoff.validate(),e=>e.code==='DP_SOURCE_STALE');
   live=structuredClone(original); live.sheetId='replacement-same-name';
   await assert.rejects(()=>handoff.validate(),e=>e.code==='DP_SOURCE_STALE','a replacement sheet with the same name cannot pass the re-read');
 }
 // Browsing a freshly picked folder must attach the workbook first, otherwise
 // the request has no preparationId and the panel shows a null-property error.
 {
   let browseState = null; const browseCalls = [];
   const readBridge = api.create({environment: {crypto}, backupEnabled: false,
     runtime: {createMutationRuntime: () => ({captureAffectedScope: async () => image}),
       describeWorkbook: async () => ({workbookName: 'Book'})},
     getState: () => browseState, setState: value => { browseState = value; },
     post: async (action, body) => {
       browseCalls.push(action);
       if (action === 'attach') return {preparationId: 'p', claimVersion: 0, writeEnabled: true};
       if (action === 'pick-folder') return {cancelled: false, path: 'root', name: 'root'};
       if (action === 'browse') {
         assert.equal(body.preparationId, 'p', 'browse carries the attached preparationId');
         return {rootName: 'root', relativePath: '', parentRelativePath: null, breadcrumb: [], entries: [], truncated: false};
       }
       throw Error('unexpected action ' + action);
     }});
   await readBridge.pickRoot();
   const listing = await readBridge.browse('');
   assert.equal(listing.rootName, 'root');
   assert(browseCalls.indexOf('attach') >= 0, 'browse attaches the workbook');
   assert(browseCalls.indexOf('browse') > browseCalls.indexOf('attach'), 'attach happens before browse');
   assert.equal(browseState.preparationId, 'p');
 }
 console.log('Preparation bridge handshake passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
