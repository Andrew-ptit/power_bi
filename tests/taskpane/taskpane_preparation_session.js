"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),vm=require("node:vm");
const modulePath="pbip_assistant/excel_addin/preparation_session.js";
assert.ok(fs.existsSync(modulePath),"Preparation reopen lifecycle module is missing");
const api=require("../../"+modulePath);
const H=n=>"sha256:"+String(n).repeat(64);
function harness(){
  const parts=[];let state=null,seq=0,captures=0;
  let binding={semanticFingerprint:H(1),nativeIdentityHash:H(2),locationHash:H(3),workbookName:"Synthetic.xlsx"};
  const calls=[];
  const workbook={name:"Synthetic.xlsx",load(){},customXmlParts:{
    getByNamespace(ns){return {items:parts.filter(p=>p.xml.includes(ns)),load(){}};},
    add(xml){const p={xml,getXml(){return {value:this.xml};},setXml(x){this.xml=x;},delete(){parts.splice(parts.indexOf(this),1);}};parts.push(p);return p;}
  },save(){throw Error("No Save allowed");}};
  const environment={Office:{context:{document:{url:"file:///synthetic.xlsx"},requirements:{isSetSupported(){return true;}}}},Excel:{async run(fn){return fn({workbook,async sync(){}});}}};
  async function post(action,payload){calls.push({action,payload});if(action==="attach"){
    if(!payload.claim.targetConfirmed&&payload.claim.locationHash===null)return {status:"needs_target_confirmation",writeEnabled:false};
    return {preparationId:"prep",marker:"marker_"+(++seq),claimVersion:seq,claimFingerprint:binding.semanticFingerprint,status:"needs_source_read",writeEnabled:false};
  }return {status:"detached"};}
  const create=()=>api.create({environment,post,captureBinding:async()=>{captures++;return {...binding};},getState:()=>state,setState:s=>{state=s;}});
  return {create,parts,calls,workbook,get state(){return state;},get captures(){return captures;},setBinding(v){binding={...binding,...v};}};
}
(async()=>{
  const h=harness();let session=h.create();
  await session.attach();assert.equal(h.parts.length,1,"marker must be persisted before attach resolves");
  assert.equal(h.calls[0].payload.claim.targetConfirmed,false,"background attach cannot impersonate confirmation");
  const text=h.parts[0].xml;assert(!text.includes("Synthetic")&&!text.includes("file:")&&!text.includes("token"));
  h.parts[0].xml=text.replace(/dp:/g,'r:').replace('xmlns:dp','xmlns:r').replace('version="1"',"version='1'").replace('/>',' />');
  await session.detach();assert.equal(h.calls.at(-1).action,"detach");assert.equal(h.parts.length,1);
  session=h.create();await session.attach();assert(h.captures>=2,"reopen must obtain fresh full evidence");
  assert.equal(h.calls.at(-1).payload.claim.marker,"marker_1");assert.equal(h.state.marker,"marker_2");assert.notEqual(h.parts[0].xml,text);
  h.setBinding({locationHash:null});session=h.create();
  await assert.rejects(()=>session.attach(),e=>e.code==="DP_RESTORE_CONFLICT");
  const u=harness();u.setBinding({locationHash:null});session=u.create();
  const pending=await session.attach();assert.equal(pending.status,"needs_target_confirmation");assert.equal(u.parts.length,0);
  await session.attach({confirmTarget:true});assert.equal(u.calls.at(-1).payload.claim.targetConfirmed,true);assert.equal(u.parts.length,1);
  // A copied marker with different native sheet identity never inherits the cursor.
  u.setBinding({nativeIdentityHash:H(4)});session=u.create();
  await assert.rejects(()=>session.attach({confirmTarget:true}),e=>e.code==="DP_RESTORE_CONFLICT");
  await session.attach({confirmTarget:true,fork:true});assert.equal(u.calls.at(-1).payload.claim.marker,null);
  // Conflicting duplicate parts fail closed; unrelated metadata is preserved.
  h.parts.push({...h.parts[0]});session=h.create();
  await assert.rejects(()=>session.attach(),e=>e.code==="DP_BINDING_REQUIRED");
  // Persistence failure retires the new authority and never publishes state.
  const broken=harness();broken.workbook.customXmlParts.add=()=>{throw Error("metadata write failed");};
  await assert.rejects(()=>broken.create().attach(),/metadata write failed/);
  assert.equal(broken.state,null);assert.equal(broken.calls.at(-1).action,"detach");
  // Teardown racing the first capture retires the newly attached transport once.
  const race=harness(),r=race.create();const opening=r.attach(),closing=r.detach();
  await assert.rejects(()=>r.attach(),e=>e.code==="DP_BINDING_REQUIRED");
  await opening;await closing;assert.deepEqual(race.calls.map(c=>c.action),["attach","detach"]);
  await r.detach();assert.equal(race.calls.length,2);
  await assert.rejects(()=>r.persist(race.state),e=>e.code==="DP_BINDING_REQUIRED");
  console.log("preparation session lifecycle: 10 checks passed");
})().catch(error=>{console.error(error);process.exitCode=1;});

