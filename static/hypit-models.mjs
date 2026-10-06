/** 工作台项目模型表面：只声明输入语义，参数和真实平台由项目绑定的精确档案验证。 */
import { defineExactModelModule, createExactModelPrimaryGenerationFragment, exactModelTextInputName, exactModelMediaInputNames } from '@hypit/hypit/model-kit';
import { sealGenerationPortTable, sealGenerationMediaBinding, sealGenerationRequestDraft } from '@hypit/hypit/generation';
import { canonicalize, createMarkupSurfaceHostFacet, sealGraphFragment } from '@hypit/hypit/author-kit';
import { artifactTypes } from '@hypit/hypit/artifact';
import { sealText, textTypes } from '@hypit/hypit/text';
import endpointPackage from './hypit-endpoint.mjs';

const moduleRef = {name:'@laohu/studio-models',version:'1'};
const modes = [
  {key:'image',tag:'Image',capability:'image-generation',result:'image',media:[['images','image'],]},
  {key:'video',tag:'Video',capability:'video-generation',result:'video',media:[['referenceImage','image'],['referenceVideo','video'],['referenceAudio','audio'],['firstFrame','image'],['lastFrame','image']]},
  {key:'audio',tag:'Audio',capability:'audio-generation',result:'audio',media:[['referenceAudio','audio']]},
  {key:'music',tag:'Music',capability:'music-generation',result:'audio',media:[['referenceAudio','audio']]},
  {key:'speech',tag:'Speech',capability:'speech-generation',result:'audio',media:[['referenceAudio','audio']]},
];
const definitions = modes.map(mode => ({...mode, ports:sealGenerationPortTable({
  model:mode.capability,result:mode.result,
  ports:[{name:'prompt',value:{kind:'text'},minItems:1,maxItems:1},
    {name:'parameters',value:{kind:'text'},minItems:0,maxItems:1},
    ...mode.media.map(([name,role])=>({name,value:{kind:'media',accepts:[role]},minItems:0,maxItems:name==='firstFrame'||name==='lastFrame'?1:1000}))], requires:[]
})}));
// 这里的上限仅保护工程规模；真实模型更小的限制仍由工作台运行前校验执行。
const model = defineExactModelModule({module:moduleRef,endpoints:definitions.map(mode=>({
  key:mode.key, requestTypeName:mode.tag+'Request',producerName:'request-'+mode.key,ports:mode.ports
}))});
const sameType=(a,b)=>a?.module?.name===b.module.name&&a?.module?.version===b.module.version&&a?.name===b.name;
function reference(element,key,type,resolve){
  const value=element.attributes[key];
  if(!value||value.kind!=='reference')throw new Error(`${element.name}.${key} requires a reference`);
  const result=resolve(value.path);
  if(!result||!sameType(result.type,type))throw new Error(`${element.name}.${key} has an incompatible input`);
  return result;
}
const facets=definitions.map(mode=>{
  const endpoint=model.endpoints[mode.key];
  const declaration={name:mode.key,tag:mode.tag,mode:'structured',
    outputs:[endpoint.draftType,...Object.values(endpoint.mediaBindings).map(x=>x.type)],
    vocabulary:{summary:`Generate ${mode.result} using this workbench project's configured model.`,
      attributes:[{name:'id',kind:'identifier',required:true,summary:'Output name'},
                  {name:'prompt',kind:'reference',required:true,accepts:[textTypes.text],summary:'Text input'},
                  {name:'parameters',kind:'literal',required:false,summary:'JSON object of parameters for this task; validated against the selected model'}],
      children:mode.media.map(([port,role])=>({tag:port,cardinality:port==='firstFrame'||port==='lastFrame'?'optional':'many',
        summary:`${role} reference`,attributes:[{name:'source',kind:'reference',required:true,accepts:[artifactTypes.blob],summary:'Media input'}]})),
      ports:[{name:mode.result,type:artifactTypes.blob,summary:'Generated media'}],
      notes:['Model and provider come from shared workbench settings. Parameters belong to this task; omitted values follow the model contract. Preparation and plan do not generate.']}};
  return createMarkupSurfaceHostFacet({module:moduleRef,declaration,handler:({element,resolveReference})=>{
    const id=element.attributes.id;
    if(typeof id!=='string'||!id.trim())throw new Error('id is required');
    for(const key of Object.keys(element.attributes))if(!['id','prompt','parameters'].includes(key))throw new Error(`Unknown attribute: ${key}`);
    const prompt=reference(element,'prompt',textTypes.text,resolveReference);
    const ports={};
    if(element.attributes.parameters!==undefined){
      const raw=element.attributes.parameters;
      if(typeof raw!=='string')throw new Error('parameters must be a JSON object literal');
      const parameters=JSON.parse(raw);
      if(!parameters||typeof parameters!=='object'||Array.isArray(parameters))throw new Error('parameters must be a JSON object');
      ports.parameters=[JSON.stringify(parameters)];
    }
    const records=[{id:id+'.draft',type:endpoint.draftType,value:{kind:'inline',value:sealGenerationRequestDraft(mode.ports,ports)},range:element.range}];
    const inputs={draft:{kind:'record',id:id+'.draft'},[exactModelTextInputName('prompt')]:prompt.ref};
    const mediaInputs=[];
    for(const child of element.children){
      if(child.kind==='text'){if(child.value.trim())throw new Error('Use a Text reference for the prompt');continue;}
      const port=child.name.split(':').pop();
      const media=mode.media.find(([name])=>name===port);
      if(!media)throw new Error(`Unsupported reference: ${port}`);
      if(Object.keys(child.attributes).some(k=>k!=='source')||child.children.some(c=>c.kind!=='text'||c.value.trim()))throw new Error('Media reference must only contain source');
      const source=reference(child,'source',artifactTypes.blob,resolveReference);
      const name=`input-${mediaInputs.length+1}`, bindingId=`${id}.${name}.binding`;
      const specification=mode.ports.ports.find(p=>p.name===port);
      records.push({id:bindingId,type:endpoint.mediaBindings[port].type,
        value:{kind:'inline',value:sealGenerationMediaBinding(specification,{role:media[1]})},range:child.range});
      const names=exactModelMediaInputNames(name);
      inputs[names.binding]={kind:'record',id:bindingId};inputs[names.artifact]=source.ref;
      mediaInputs.push({name,port});
    }
    const fragment=createExactModelPrimaryGenerationFragment(endpoint,mediaInputs,[{name:'prompt',port:'prompt'}]);
    return {records,components:[{id,fragment:fragment.id,inputs,outputs:{[mode.result]:`${id}.${mode.result}`},range:element.range}],fragments:[fragment]};
  }});
});
export const hypitPackage={format:'hypit.node-package@1',modules:[{manifest:model.manifest}],
  components:[model.component],hostFacets:[model.hostFacet,...facets,...endpointPackage.hostFacets]};

// Text 结果属于 @hypit/text 的 Text 类型，不是图片/视频/音频 Blob。
const textCapability = {module:moduleRef,name:'text-generation'};
const textRequestProducer = {module:moduleRef,name:'request-text-generation'};
const textGenerationFacet = createMarkupSurfaceHostFacet({
  module:moduleRef,
  declaration:{name:'text',tag:'Text',mode:'structured',outputs:[textTypes.text],
    vocabulary:{summary:'Generate Text using the model selected for this Hypit project.',
      attributes:[{name:'id',kind:'identifier',required:true,summary:'Output name'},
        {name:'prompt',kind:'reference',required:true,accepts:[textTypes.text],summary:'Text input'},
        {name:'parameters',kind:'literal',required:false,summary:'JSON object of per-request parameters'}],
      ports:[{name:'text',type:textTypes.text,summary:'Generated Text'}],
      notes:['The project’s shared Hypit text model and configured workflow provide the output.'] }},
  handler:({element,resolveReference})=>{
    const id=element.attributes.id;
    if(typeof id!=='string'||!id.trim())throw new Error('id is required');
    for(const key of Object.keys(element.attributes))if(!['id','prompt','parameters'].includes(key))throw new Error(`Unknown attribute: ${key}`);
    const prompt=reference(element,'prompt',textTypes.text,resolveReference);
    let parameters={};
    if(element.attributes.parameters!==undefined){
      if(typeof element.attributes.parameters!=='string')throw new Error('parameters must be a JSON object literal');
      parameters=JSON.parse(element.attributes.parameters);
      if(!parameters||typeof parameters!=='object'||Array.isArray(parameters))throw new Error('parameters must be a JSON object');
    }
    const parameterRecord=`${id}.parameters`;
    const fragment=sealGraphFragment({
      inputs:[{name:'prompt',type:textTypes.text},{name:'parameters',type:textTypes.text}],
      operations:[{id:'generate',producer:textRequestProducer,
        inputs:{prompt:{kind:'fragment-input',name:'prompt'},parameters:{kind:'fragment-input',name:'parameters'}},
        result:{kind:'need',name:'generation'}}],
      exports:[{name:'text',type:textTypes.text,root:{kind:'fragment-operation',operation:'generate'}}],
    });
    return {records:[{id:parameterRecord,type:textTypes.text,
        value:{kind:'inline',value:sealText(JSON.stringify(parameters))},range:element.range}],
      components:[{id,fragment:fragment.id,inputs:{prompt:prompt.ref,parameters:{kind:'record',id:parameterRecord}},
        outputs:{text:`${id}.text`},range:element.range}],fragments:[fragment]};
  },
});

const textManifest={...model.manifest,
  capabilities:[...model.manifest.capabilities,{name:textCapability.name,returns:textTypes.text}],
  producers:[...model.manifest.producers,{name:textRequestProducer.name,
    inputs:[{name:'prompt',type:textTypes.text},{name:'parameters',type:textTypes.text}],outputs:[],
    needs:[{name:'generation',capability:textCapability,returns:textTypes.text}]}]};
const textProducerFacet={producer:textRequestProducer,handler:({inputs})=>{
  const inlineText=(name)=>{
    const stored=inputs[name]?.value;
    if(!stored||stored.kind!=='inline'||typeof stored.value?.value!=='string')throw new Error(`${name} must be inline Text`);
    return stored.value.value;
  };
  const prompt=inlineText('prompt');
  let parameters;
  try{parameters=JSON.parse(inlineText('parameters'));}
  catch(error){throw new Error(`parameters must be JSON: ${error instanceof Error?error.message:String(error)}`);}
  if(!parameters||typeof parameters!=='object'||Array.isArray(parameters))throw new Error('parameters must be a JSON object');
  return {outputs:{},needs:{generation:canonicalize({ports:{prompt:[prompt],parameters:[JSON.stringify(parameters)]}})}};
}};
const textPlannedNeed={producer:textRequestProducer,port:'generation',capability:textCapability,
  plan:({state,step})=>{
    const current=state.plan.steps.find(item=>item.id===step);
    if(!current)return undefined;
    const records=new Map(state.records.map(record=>[record.id,record]));
    const textValue=(id)=>{
      const stored=records.get(id)?.value;
      return stored?.kind==='inline'&&typeof stored.value?.value==='string'?stored.value.value:undefined;
    };
    const ports={};
    const parameterText=textValue(current.inputs.parameters);
    if(parameterText===undefined)return undefined;
    ports.parameters=[parameterText];
    const prompt=textValue(current.inputs.prompt);
    const pendingInputs=[];
    if(prompt===undefined){
      const producedBy=new Map(state.plan.steps.flatMap(item=>Object.values(item.outputs).map(record=>[record,item.id])));
      pendingInputs.push({input:'prompt',record:current.inputs.prompt,
        ...(producedBy.get(current.inputs.prompt)?{sourceStep:producedBy.get(current.inputs.prompt)}:{})});
    }else ports.prompt=[prompt];
    return {constraints:canonicalize({ports}),pendingInputs};
  },
  present:(specification)=>{
    const ports=specification.constraints?.ports||{};
    const fields={};
    for(const [key,values] of Object.entries(ports))if(values.length)fields[key]=values;
    return {fields,references:{}};
  }};

// 用 Text capability 声明更新包清单，并把返回真实 Text 类型的 producer 与原媒体生成 surface 并列注册。
hypitPackage.modules[0].manifest=textManifest;
hypitPackage.components.push({producers:[textProducerFacet],plannedNeeds:[textPlannedNeed]});
hypitPackage.hostFacets.push(textGenerationFacet);
export default hypitPackage;
