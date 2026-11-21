/* Authenticated preparation handshake; navigation never grants native writes. */
(function(root){
  "use strict";
  const fail=(code,message)=>Object.assign(new Error(message),{code});
  function create({post,runtime,environment,getState,setState,backupEnabled=true}){
    let busy=false, active=null, confirmedDateSystem=null, currentSheetNames=[], scannedReview=null;
    const digest=async bytes=>"sha256:"+Array.from(new Uint8Array(await environment.crypto.subtle.digest("SHA-256",bytes)),v=>v.toString(16).padStart(2,"0")).join("");
    const base64=bytes=>{let text="";for(let i=0;i<bytes.length;i+=8192)text+=String.fromCharCode(...bytes.subarray(i,i+8192));return environment.btoa(text);};
    const send=(action,fields)=>post(action,{preparationId:getState().preparationId,...fields});
    async function inspectPreservation({bytes,semanticImage}){
      if(!(bytes instanceof Uint8Array)||!bytes.length||bytes.length>64*1024*1024)
        throw fail("DP_BACKUP_LIMIT","Gói workbook vượt giới hạn kiểm tra bảo toàn 64 MiB.");
      const declaration=await post("preservation-begin",{byteLength:bytes.length,packageHash:await digest(bytes)});
      const size=Math.min(1048576,declaration.maxChunkBytes||1048576);
      if(!Number.isInteger(size)||size<=0)throw fail("DP_BACKUP_FAILED","Giới hạn truyền gói workbook không hợp lệ.");
      for(let offset=0,index=0;offset<bytes.length;offset+=size,index++){
        const chunk=bytes.subarray(offset,Math.min(offset+size,bytes.length));
        await post("preservation-chunk",{uploadId:declaration.uploadId,index,offset,chunkHash:await digest(chunk),dataBase64:base64(chunk)});
      }
      return post("preservation-finish",{uploadId:declaration.uploadId,semanticImage});
    }
    const native=runtime.createMutationRuntime({...environment,preparationBackupEnabled:backupEnabled,inspectPreservation,consumeWritePermit:async request=>{
      if(!active||request.attemptId!==active.attempt.attemptId||request.writePermit!==active.attempt.writePermit)
        throw fail("DP_BINDING_REQUIRED","Thao tác không còn thuộc phiên hiện tại.");
      // A lost response may still have consumed authority; never classify it as safe to retry.
      active.permitRequested=true;
      if (!backupEnabled) return send("direct-write-ready", {attemptId:request.attemptId,
        writePermit:request.writePermit,currentFingerprint:request.currentFingerprint});
      return send("write-ready",{attemptId:request.attemptId,beforeImageId:active.beforeImageId,expectedFingerprint:request.currentFingerprint,
        expectedPreservationFingerprint:request.currentPreservationFingerprint});
    }});
    const session=backupEnabled && environment.ReqwisePreparationSession?.create({post,environment,getState,setState,
      captureBinding:async()=>{
        const image=await native.captureAffectedScope(),description=await runtime.describeWorkbook(environment);
        currentSheetNames=image.sheets.map(sheet=>sheet.name);
        const url=environment.Office?.context?.document?.url||"";
        return {semanticFingerprint:image.fingerprint,preservationFingerprint:image.fullFingerprint,
          nativeIdentityHash:await digest(new TextEncoder().encode(JSON.stringify(image.sheets.map(s=>s.sheetId).sort()))),
          workbookName:description.workbookName,locationHash:url?await digest(new TextEncoder().encode(url)):null};
      }});
    function requireWrite(){
      if(!getState()?.writeEnabled)throw fail("DP_UNSUPPORTED_PRESERVATION","Chưa xác nhận nguồn và quyền ghi. Hãy đọc lại workbook.");
    }
    async function upload(attempt,image,purpose){
      const bytes=new TextEncoder().encode(JSON.stringify(image));
      if(bytes.length>8*1024*1024)throw fail("DP_BACKUP_LIMIT","Bản khôi phục vượt giới hạn 8 MiB.");
      const declaration=await send("image-begin",{attemptId:attempt.attemptId,purpose,byteLength:bytes.length,imageHash:await digest(bytes)});
      const chunkSize=Math.min(1048576,declaration.maxChunkBytes||1048576);
      if(!Number.isInteger(chunkSize)||chunkSize<=0)throw fail("DP_BACKUP_FAILED","Giới hạn truyền backup không hợp lệ.");
      for(let offset=0,index=0;offset<bytes.length;offset+=chunkSize,index++){
        const chunk=bytes.subarray(offset,Math.min(offset+chunkSize,bytes.length));
        await send("image-chunk",{attemptId:attempt.attemptId,uploadId:declaration.uploadId,index,offset,chunkHash:await digest(chunk),dataBase64:base64(chunk)});
      }
      return send("image-finish",{attemptId:attempt.attemptId,uploadId:declaration.uploadId});
    }
    function receipt(result,imageId){
      const sheets=result.after?.sheets||[];
      return {phase:result.phase,actualSheetIds:result.createdSheetIds||[],observedFingerprint:result.after?.fingerprint||null,imageId,
        rows:sheets.reduce((sum,s)=>sum+s.values.length,0),columns:sheets.reduce((max,s)=>Math.max(max,s.values[0]?.length||0),0)};
    }
    async function transaction(work){
      if(busy)throw fail("COORDINATOR_BUSY","Đang có thao tác chuẩn bị dữ liệu. Hãy chờ hoàn tất.");
      requireWrite();busy=true;
      try{return await work();}
      catch(error){
        if(active){
          const unknown=active.permitRequested||error.code==="DP_PARTIAL_UNKNOWN";
          try{setState(await send(!backupEnabled?"direct-complete":active.restore?"restore-complete":"complete",{attemptId:active.attempt.attemptId,
            ...(!backupEnabled?{afterImage:null}:{}),
            receipt:{phase:unknown?"partial_unknown":"prewrite_failed",actualSheetIds:[],observedFingerprint:null,imageId:null,rows:0,columns:0}}));}
          catch(_){} // Preserve the original error; no replay after lost authority/receipt.
          if(unknown)throw fail("DP_PARTIAL_UNKNOWN",backupEnabled
            ? "Thao tác có thể đã ghi một phần. Kiểm tra workbook và lịch sử; không tự chạy lại."
            : "Thao tác đã được gửi tới Excel nhưng chưa xác minh hoàn tất. Kiểm tra các sheet hiện có và bắt đầu phiên mới để đọc lại dữ liệu.");
        }
        throw error;
      }finally{active=null;busy=false;}
    }
    async function performImport(reviewHash,target,onProgress){
      const before=await native.captureAffectedScope();
      const grant=await send("approve",{kind:"import",reviewHash,target:{...target,sheetIds:target.sheetIds.length?target.sheetIds:before.sheets.map(s=>s.sheetId)}});
      let attempt;
      try {
        attempt=backupEnabled
          ? await send("begin",{grantId:grant.grantId,expectedFingerprint:before.fingerprint,expectedPreservationFingerprint:before.fullFingerprint})
          : await send("direct-begin",{grantId:grant.grantId,beforeImage:before});
      } catch (error) {
        if (!backupEnabled && (!error.code || ["COORDINATOR_RESPONSE_INVALID", "COORDINATOR_TIMEOUT", "REQUEST_FAILED", "REQUEST_TIMEOUT"].includes(error.code))) throw fail("DP_PARTIAL_UNKNOWN",
          "Mất phản hồi khi chuẩn bị nhập. Chưa gửi lệnh ghi tới Excel. Bắt đầu phiên mới để đọc lại workbook và duyệt lại.");
        throw error;
      }
      active={attempt,permitRequested:false,restore:false};
      if (backupEnabled) {
        onProgress("Đang tạo và kiểm tra điểm khôi phục…");
        const saved=await upload(attempt,before,"before");active.beforeImageId=saved.imageId;
        Object.assign(attempt,{expectedFingerprint:saved.expectedFingerprint,targetCopies:saved.targetCopies||[]});
      }
      onProgress("Đang chuyển file thành sheet trong workbook…");
      const result=await native.importReviewedSources(attempt,attempt.packages,value=>onProgress(
        value.processed===value.total
          ? `Đã chèn ${value.total}/${value.total} file. Đang đọc lại và xác minh workbook…`
          : `Đang nhập: ${value.processed}/${value.total} file…`));
      if(result.phase!=="verified")throw fail("DP_PARTIAL_UNKNOWN","Excel chưa xác minh được kết quả ghi.");
      onProgress("Đang đọc lại và đối chiếu kết quả…");
      let state;
      if (backupEnabled) {
        const after=await upload(attempt,result.after,"after");
        state=await send("complete",{attemptId:attempt.attemptId,receipt:receipt(result,after.imageId)});
      } else {
        state=await send("direct-complete",{attemptId:attempt.attemptId,receipt:receipt(result,null),afterImage:result.after});
      }
      setState(state);
      if(state.status!=="verified")throw fail("DP_PARTIAL_UNKNOWN","Kết quả đọc lại chưa khớp bản đã duyệt.");
      if(session)await session.persist(state);
      active=null;return {status:"verified",state};
    }
    async function attach(read){
      if(getState())return getState();
      if (!backupEnabled) {
        const image=await native.captureAffectedScope();
        const description=read||await runtime.describeWorkbook(environment);
        const nativeIdentityHash=await digest(new TextEncoder().encode(JSON.stringify(image.sheets.map(s=>s.sheetId).sort())));
        const state=await post("attach",{claim:{marker:null,semanticFingerprint:image.fingerprint,nativeIdentityHash,
          targetConfirmed:true,expectedClaimVersion:0,workbookName:description.workbookName,locationHash:null}});
        setState(state);return state;
      }
      if(session){
        const state=await session.attach({confirmTarget:true});
        if(state.status==="needs_target_confirmation")throw fail("DP_BINDING_REQUIRED","Hãy chọn workbook đích để bắt đầu phiên chuẩn bị dữ liệu.");
        return state;
      }
      const description=read||await runtime.describeWorkbook(environment);
      let semanticFingerprint;
      try{semanticFingerprint=(await native.captureAffectedScope()).fingerprint;}
      catch(error){
        if(!["DP_UNSUPPORTED_PRESERVATION","DP_BACKUP_LIMIT"].includes(error.code))throw error;
        semanticFingerprint=await digest(new TextEncoder().encode(JSON.stringify({name:description.workbookName,sheetId:description.sheetId||description.sources?.[0]?.sheetId})));
      }
      const state=await post("attach",{claim:{marker:null,semanticFingerprint,targetConfirmed:true,expectedClaimVersion:0,workbookName:description.workbookName,locationHash:null}});
      setState(state);return state;
    }
    async function mapInventory(inventory){
      if(!currentSheetNames.length)currentSheetNames=(await native.captureAffectedScope()).sheets.map(sheet=>sheet.name);
      const key=value=>String(value).normalize("NFC").toLowerCase();
      const occupied=new Set(currentSheetNames.map(key));
      const trim=(value,length)=>{let result=value.slice(0,length);if(/[\uD800-\uDBFF]$/.test(result))result=result.slice(0,-1);return result;};
      const sheets=(inventory.sheets||[]).map(sheet=>{
        const base=sheet.proposedName;let name=base,index=2;
        while(occupied.has(key(name))){const suffix="_"+index++;name=trim(base,31-suffix.length)+suffix;}
        occupied.add(key(name));return {...sheet,proposedName:name};
      });
      return {...inventory,sheets};
    }
    async function scanWorkbook({dateSystem=null,onProgress=()=>{}}={}){
      const read=await runtime.readWorkbookSources(environment,dateSystem,value=>onProgress({message:`Đang quét sheet ${value.processed}/${value.total}: ${value.sheetName}`}));
      confirmedDateSystem=read.dateSystem;
      await attach(read);
      let state=await send("source-set",{snapshots:read.sources,expectedSourceRevision:getState().sourceRevision});setState(state);
      state=await send("scan",{sourceRevision:state.sourceRevision,expectedFingerprint:state.sourceHash,
        sources:state.sources.map(s=>({sourceId:s.sourceId,sheetId:s.sheetId,fingerprint:s.fingerprint,kind:"usedRange"}))});setState(state);
      scannedReview={sources:read.sources,sourceLabels:read.sourceLabels,dateSystem:read.dateSystem};
      return {state,sourceLabels:read.sourceLabels,warnings:read.warnings,dateSystem:read.dateSystem};
    }
    async function importFiles({inventory,fileIds,mappings,dateSystem=null,onProgress=()=>{}}){
      return transaction(async()=>{
        const before=await native.captureAffectedScope();
        const chosen=new Set(fileIds);
        const selected=mappings.filter(m=>chosen.has(m.fileId)).map(({fileId,sourceSheetId,proposedName})=>({fileId,sourceSheetId,proposedName}));
        if(!chosen.size||!selected.length)throw fail("INVALID_REQUEST","Chọn ít nhất một file có sheet được hỗ trợ.");
        onProgress("Đang kiểm tra file và tên sheet trước khi nhập…");
        const review=await send("review-import",{inventoryHash:inventory.inventoryHash,mappings:selected,existingNames:before.sheets.map(s=>s.name)});
        const transfer=await send("packages",{reviewHash:review.reviewHash,...(dateSystem?{dateSystem}:{})});
        const result=await performImport(transfer.reviewHash,{strategy:"import_new",sheetIds:[]},onProgress);
        return {...result,report:transfer.importReport};
      });
    }
    let sourceRoot=null,sourceRootName="",probedDateSystem=null;
    async function pickRoot(){
      const chosen=await post("pick-folder",{});
      if(!chosen||chosen.cancelled||!chosen.path)return {cancelled:true};
      sourceRoot=chosen.path;sourceRootName=chosen.name||"";probedDateSystem=null;
      return {cancelled:false,rootName:sourceRootName};
    }
    async function browse(relativePath=""){
      if(!sourceRoot)throw fail("INVALID_REQUEST","Chọn thư mục nguồn trước.");
      await attach();
      return send("browse",{root:sourceRoot,relativePath:relativePath||"",expectedClaimVersion:getState()?.claimVersion});
    }
    async function inventorySelection(items){
      if(!sourceRoot)throw fail("INVALID_REQUEST","Chọn thư mục nguồn trước.");
      await attach();
      const state=await send("inventory",{root:sourceRoot,items,expectedClaimVersion:getState()?.claimVersion});
      return state.inventory;
    }
    async function probeDateSystem(){
      if(probedDateSystem)return probedDateSystem;
      const value=await runtime.probeDateSystem(environment);
      if(!["1900","1904"].includes(value))throw fail("DP_DATE_SYSTEM_REQUIRED","Không xác định được hệ ngày của workbook (1900/1904). Không nhập để tránh sai ngày.");
      probedDateSystem=value;return value;
    }
    async function importSelection({items,dateSystem,onProgress=()=>{}}){
      if(!Array.isArray(items)||!items.length)throw fail("INVALID_REQUEST","Chọn ít nhất một file trước khi nhập.");
      await attach();
      return transaction(async()=>{
        const before=await native.captureAffectedScope();
        onProgress({fileName:"đang đọc file đã chọn"});
        const inventory=await inventorySelection(items);
        const names=new Map((inventory.files||[]).map(entry=>[entry.fileId,entry.fileName]));
        const mappings=(inventory.sheets||[]).map(({fileId,sourceSheetId,proposedName})=>({fileId,sourceSheetId,proposedName}));
        if(!mappings.length)throw fail("INVALID_REQUEST","Không có sheet nào đọc được từ file đã chọn.");
        const review=await send("review-import",{inventoryHash:inventory.inventoryHash,mappings,existingNames:before.sheets.map(s=>s.name)});
        const transfer=await send("packages",{reviewHash:review.reviewHash,...(dateSystem?{dateSystem}:{})});
        const result=await performImport(transfer.reviewHash,{strategy:"import_new",sheetIds:[]},
          value=>onProgress({...value,fileName:names.get(value.fileId)||""}));
        return {...result,report:transfer.importReport,inventory};
      });
    }
    async function businessSourcesFromScan(){
      const review=scannedReview;
      if(!review)throw fail("DP_REVIEW_STALE","Đọc lại nguồn trước khi mở đề bài.");
      const evidence=JSON.stringify({sources:review.sources,sourceLabels:review.sourceLabels});
      const observedHash=await digest(new TextEncoder().encode(evidence));
      return {sources:review.sources,sourceLabels:review.sourceLabels,observedHash,
        async validate(){
          const fresh=await runtime.readWorkbookSources(environment,review.dateSystem);
          if(JSON.stringify(fresh.sources)!==JSON.stringify(review.sources)
            ||JSON.stringify(fresh.sourceLabels)!==JSON.stringify(review.sourceLabels))
            throw fail("DP_SOURCE_STALE","Dữ liệu hoặc sheet đã đổi sau khi đọc lại. Hãy đọc lại nguồn.");
          return {sources:review.sources,sourceLabels:review.sourceLabels,observedHash};
        }};
    }
    return {importFiles,importSelection,scanWorkbook,attach,mapInventory,businessSourcesFromScan,pickRoot,browse,inventorySelection,probeDateSystem,
      async restart(){
        if(busy||active)throw fail("COORDINATOR_BUSY","Chờ thao tác hiện tại kết thúc trước khi mở phiên mới.");
        if (!backupEnabled) {
          setState(null);scannedReview=null;currentSheetNames=[];
          return attach();
        }
        if(!session)throw fail("DP_BINDING_REQUIRED","Hãy đóng và mở lại panel để bắt đầu phiên mới.");
        const state=await session.attach({confirmTarget:true,fork:true});
        scannedReview=null;currentSheetNames=[];return state;
      },
      detach:()=>session?session.detach():getState()?send("detach",{expectedClaimVersion:getState().claimVersion}):Promise.resolve({status:"detached"})};
  }
  const api={create};if(typeof module!=="undefined"&&module.exports)module.exports=api;else root.ReqwisePreparationBridge=api;
})(typeof window!=="undefined"?window:globalThis);
