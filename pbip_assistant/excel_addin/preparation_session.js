/* Non-authorizing, bounded reopen metadata. No token, approval, cells or path.
 * Custom XML writes never call Save. Office.js cannot provide inter-pane CAS;
 * final byte recheck and read-back detect conflicts and fail closed.
 */
(function(root){
  "use strict";
  const NS="urn:local-data-copilot:preparation-session:v1";
  const HASH=/^sha256:[a-f0-9]{64}$/; const ID=/^[A-Za-z0-9_-]{1,128}$/;
  const fail=(code,message)=>Object.assign(new Error(message),{code});
  let tail=Promise.resolve();
  function validate(value){
    const fields=["schemaVersion","marker","claimVersion","lastFullSourceFingerprint","nativeIdentityHash","locationHash"];
    if(!value||typeof value!=="object"||JSON.stringify(Object.keys(value).sort())!==JSON.stringify(fields.sort())
      ||value.schemaVersion!==1||!ID.test(value.marker)||!Number.isSafeInteger(value.claimVersion)||value.claimVersion<1
      ||!HASH.test(value.lastFullSourceFingerprint)||!HASH.test(value.nativeIdentityHash)
      ||value.locationHash!==null&&!HASH.test(value.locationHash))throw fail("DP_BINDING_REQUIRED","Invalid preparation metadata.");
    return value;
  }
  function encode(value){
    validate(value);
    return `<dp:session xmlns:dp="${NS}" version="1" marker="${value.marker}" claimVersion="${value.claimVersion}" fingerprint="${value.lastFullSourceFingerprint}" native="${value.nativeIdentityHash}" location="${value.locationHash||""}"/>`;
  }
  function decode(xml){
    if(typeof xml!=="string"||xml.length>2048)throw fail("DP_BINDING_REQUIRED","Invalid preparation metadata.");
    xml=xml.replace(/^<\?xml version="1\.0"(?: encoding="[Uu][Tt][Ff]-(?:8|16)")?(?: standalone="(?:yes|no)")?\?>\s*/,"");
    const match=xml.match(/^\s*<((?:[A-Za-z_][\w.-]*:)?session)\s+([^<>]*)\/\s*>\s*$/);
    if(!match)throw fail("DP_BINDING_REQUIRED","Invalid preparation metadata.");
    const attributes={},pattern=/([A-Za-z_][\w:.-]*)\s*=\s*(?:"([^"<>&]*)"|'([^'<>&]*)')/g;
    let cursor=0,attribute;
    while((attribute=pattern.exec(match[2]))){
      if(match[2].slice(cursor,attribute.index).trim()||Object.prototype.hasOwnProperty.call(attributes,attribute[1]))
        throw fail("DP_BINDING_REQUIRED","Invalid preparation metadata.");
      attributes[attribute[1]]=attribute[2]??attribute[3];cursor=pattern.lastIndex;
    }
    const prefix=match[1].includes(":")?match[1].split(":")[0]:null,xmlns=prefix?"xmlns:"+prefix:"xmlns";
    if(match[2].slice(cursor).trim()||attributes[xmlns]!==NS||attributes.version!=="1"
      ||Object.keys(attributes).sort().join("|")!==[xmlns,"version","marker","claimVersion","fingerprint","native","location"].sort().join("|")
      ||!/^([1-9][0-9]{0,15})$/.test(attributes.claimVersion))throw fail("DP_BINDING_REQUIRED","Invalid preparation metadata.");
    return validate({schemaVersion:1,marker:attributes.marker,claimVersion:Number(attributes.claimVersion),lastFullSourceFingerprint:attributes.fingerprint,nativeIdentityHash:attributes.native,locationHash:attributes.location||null});
  }
  const serial=fn=>{const result=tail.then(fn,fn);tail=result.catch(()=>{});return result;};
  function create({post,environment,captureBinding,getState,setState}){
    let expected=null,lastBinding=null,inflight=null,retired=false;
    const binding=async()=>{
      const value=await captureBinding();
      if(!value||!HASH.test(value.semanticFingerprint)||!HASH.test(value.nativeIdentityHash)
        ||value.preservationFingerprint!=null&&!HASH.test(value.preservationFingerprint)
        ||value.locationHash!==null&&!HASH.test(value.locationHash)||typeof value.workbookName!=="string"||!value.workbookName||value.workbookName.length>255)
        throw fail("DP_BINDING_REQUIRED","Fresh full workbook and native identity evidence is required.");
      return value;
    };
    async function access(change){
      const {Excel,Office}=environment;
      if(!Excel?.run||!Office?.context?.requirements?.isSetSupported("ExcelApi","1.5"))
        throw fail("DP_BINDING_REQUIRED","Preparation recovery metadata requires ExcelApi 1.5.");
      return serial(()=>Excel.run(async context=>{
        const wb=context.workbook, url=Office.context.document?.url||"";
        wb.load("name");await context.sync();const name=wb.name;
        const check=async()=>{wb.load("name");await context.sync();if(wb.name!==name||(Office.context.document?.url||"")!==url||lastBinding&&lastBinding.workbookName!==wb.name)
          throw fail("DP_BINDING_REQUIRED","Workbook changed during preparation metadata access.");};
        const read=async()=>{const parts=wb.customXmlParts.getByNamespace(NS);parts.load("items/id");await context.sync();
          if(parts.items.length>1)throw fail("DP_BINDING_REQUIRED","Multiple preparation metadata parts exist.");
          if(!parts.items.length)return {part:null,xml:null,node:null};
          const part=parts.items[0],result=part.getXml();await context.sync();return {part,xml:result.value,node:decode(result.value)};};
        const current=await read();await check();
        if(!change)return current.node;
        const expectedXml=expected===null?null:encode(expected);
        if((current.node===null?null:encode(current.node))!==expectedXml)throw fail("DP_RESTORE_CONFLICT","Preparation metadata changed in another pane.");
        const fresh=await read();await check();
        if(fresh.xml!==current.xml)throw fail("DP_RESTORE_CONFLICT","Preparation metadata changed before persistence.");
        const xml=encode(change);
        if(fresh.part)fresh.part.setXml(xml);else wb.customXmlParts.add(xml);
        await context.sync();await check();
        const after=await read();
        if(!after.node||encode(after.node)!==xml)throw fail("DP_BINDING_REQUIRED","Preparation metadata read-back failed; reload before continuing.");
        expected=after.node;return after.node;
      }));
    }
    async function persist(state){
      if(retired)throw fail("DP_BINDING_REQUIRED","Preparation transport is retired.");
      const fresh=await binding();
      if(lastBinding&&fresh.locationHash!==lastBinding.locationHash)throw fail("DP_RESTORE_CONFLICT","Workbook location changed; start a separate preparation.");
      lastBinding=fresh;
      await access({schemaVersion:1,marker:state.marker,claimVersion:state.claimVersion,lastFullSourceFingerprint:fresh.preservationFingerprint||fresh.semanticFingerprint,nativeIdentityHash:fresh.nativeIdentityHash,locationHash:fresh.locationHash});
      return state;
    }
    async function attach({confirmTarget=false,fork=false}={}){
      if(retired||inflight)throw fail("DP_BINDING_REQUIRED","Preparation attachment is retired or already in progress.");
      inflight=(async()=>{
        lastBinding=await binding();expected=await access();
        if(expected&&!fork&&(expected.lastFullSourceFingerprint!==(lastBinding.preservationFingerprint||lastBinding.semanticFingerprint)||expected.nativeIdentityHash!==lastBinding.nativeIdentityHash||expected.locationHash!==lastBinding.locationHash))
          throw fail("DP_RESTORE_CONFLICT","Workbook differs from retained recovery; start a separate preparation.");
        if(fork&&!confirmTarget)throw fail("DP_BINDING_REQUIRED","Starting a separate preparation requires explicit target confirmation.");
        const state=await post("attach",{claim:{marker:fork?null:expected?.marker||null,expectedClaimVersion:fork?0:expected?.claimVersion||0,
          semanticFingerprint:lastBinding.semanticFingerprint,...(lastBinding.preservationFingerprint?{preservationFingerprint:lastBinding.preservationFingerprint}:{}),nativeIdentityHash:lastBinding.nativeIdentityHash,locationHash:lastBinding.locationHash,
          workbookName:lastBinding.workbookName,targetConfirmed:confirmTarget===true}});
        if(state.status==="needs_target_confirmation")return state;
        try{await persist(state);}catch(error){try{await post("detach",{preparationId:state.preparationId,expectedClaimVersion:state.claimVersion});}catch(_){}throw error;}
        setState(state);return state;
      })();
      try{return await inflight;}finally{inflight=null;}
    }
    async function detach(){
      if(retired)return {status:"detached"};
      if(inflight)try{await inflight;}catch(_){}
      retired=true;const state=getState();
      if(!state?.preparationId)return {status:"detached"};
      return post("detach",{preparationId:state.preparationId,expectedClaimVersion:state.claimVersion});
    }
    return {attach,persist,detach};
  }
  const api={create};if(typeof module!=="undefined"&&module.exports)module.exports=api;else root.ReqwisePreparationSession=api;
})(typeof window!=="undefined"?window:globalThis);
