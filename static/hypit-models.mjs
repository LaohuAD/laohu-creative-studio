/** 工作台项目模型表面：只声明输入语义，参数和真实平台由项目绑定的精确档案验证。 */
import { defineExactModelModule, createExactModelPrimaryGenerationFragment, exactModelTextInputName, exactModelMediaInputNames } from '@hypit/hypit/model-kit';
import { sealGenerationPortTable, sealGenerationMediaBinding, sealGenerationRequestDraft } from '@hypit/hypit/generation';
import { createMarkupSurfaceHostFacet } from '@hypit/hypit/author-kit';
import { artifactTypes } from '@hypit/hypit/artifact';
import { textTypes } from '@hypit/hypit/text';
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
export default hypitPackage;
