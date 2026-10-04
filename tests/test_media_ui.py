import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from PIL import Image
import main
from project_storage import ProjectStorage
import system_clipboard

ROOT = Path(__file__).resolve().parents[1]


class MediaUiTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_copy_requires_same_computer_origin_and_managed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = ProjectStorage(directory)
            storage.ensure_layout()
            path = storage.results_dir / 'image' / 'sample.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (4, 4)).save(path)
            with patch.object(main, 'PROJECT_STORAGE', storage), patch.object(main, 'local_media_reference_path', return_value=str(path)), patch('system_clipboard.write_clipboard', return_value={'ok':True,'count':1}) as writer:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app, client=('127.0.0.1',1)),base_url='http://127.0.0.1:3000') as client:
                    good=await client.post('/api/system-clipboard',json={'urls':['/api/results/test']},headers={'origin':'http://127.0.0.1:3000'})
                    self.assertEqual(good.status_code,200)
                    self.assertEqual(writer.call_args.args[0],[str(path)])
                    mixed=await client.post('/api/system-clipboard',json={'items':[{'url':'/api/results/test'},{'text':'镜头说明'},{'url':'/api/results/test'}]},headers={'origin':'http://127.0.0.1:3000'})
                    self.assertEqual(mixed.status_code,200)
                    copied=writer.call_args.args[0]
                    self.assertEqual(copied[0],str(path))
                    self.assertEqual(Path(copied[1]).read_text(),'镜头说明')
                    self.assertEqual(copied[2],str(path))
                    for url in ['/etc/passwd','file:///etc/passwd','https://example.com/a.png']:
                        self.assertEqual((await client.post('/api/system-clipboard',json={'urls':[url]},headers={'origin':'http://127.0.0.1:3000'})).status_code,400)
                    self.assertEqual((await client.post('/api/system-clipboard',json={'urls':['/api/results/test']},headers={'origin':'http://evil.test'})).status_code,403)
                    with patch.object(main,'local_media_reference_path',return_value=__file__):
                        self.assertEqual((await client.post('/api/system-clipboard',json={'urls':['/assets/../../tests/test_media_ui.py']},headers={'origin':'http://127.0.0.1:3000'})).status_code,400)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app,client=('198.51.100.4',1)),base_url='http://127.0.0.1:3000') as client:
                    self.assertEqual((await client.post('/api/system-clipboard',json={'text':'test'},headers={'origin':'http://127.0.0.1:3000'})).status_code,403)

    async def test_music_is_a_category_without_changing_audio_file_kind(self):
        with tempfile.TemporaryDirectory() as directory:
            storage=ProjectStorage(directory);storage.ensure_layout()
            source=Path(directory)/'song.wav';source.write_bytes(b'RIFF sample music')
            music=storage.store_result_file(source,'song.wav')
            source.write_bytes(b'RIFF sample voice')
            voice=storage.store_result_file(source,'voice.wav')
            storage.update_result_metadata(music['id'],media_category='music')
            with patch.object(main,'PROJECT_STORAGE',storage),patch.object(main,'sync_all_canvas_result_origins'):
                all_results=await main.list_generation_results(prune_missing=False)
                self.assertEqual(all_results['counts']['music'],1)
                self.assertEqual(all_results['counts']['audio'],1)
                self.assertEqual((await main.list_generation_results(kind='music',prune_missing=False))['items'][0]['id'],music['id'])
                self.assertEqual(storage.get_result(music['id'])['kind'],'audio')
                self.assertEqual(storage.get_result(voice['id'])['kind'],'audio')

    async def test_historical_music_migration_excludes_input_references_and_survives_promotion(self):
        from starlette.requests import Request
        with tempfile.TemporaryDirectory() as directory:
            storage=ProjectStorage(directory);storage.ensure_layout()
            source=Path(directory)/'source.wav';source.write_bytes(b'voice')
            voice=storage.store_result_file(source,'voice.wav')
            source.write_bytes(b'music')
            music=storage.store_result_file(source,'music.wav')
            canvas={'id':'music-test','nodes':[{'type':'smart-material','sourceKind':'result','runSettings':{'apiKind':'music'},'images':[], 'resultVersions':[{'images':[{'url':storage.result_url(music['id'])}], 'runInputRefs':[{'url':storage.result_url(voice['id'])}]}]}]}
            group={'id':'group','type':'media','items':[]}
            library={'libraries':[{'id':'library','categories':[group]}]}
            with patch.object(main,'PROJECT_STORAGE',storage):
                main.sync_canvas_result_origins(canvas)
                self.assertEqual(storage.get_result(music['id'])['media_category'],'music')
                self.assertNotEqual(storage.get_result(voice['id']).get('media_category'),'music')
                with patch.object(main,'load_asset_library',return_value=library),patch.object(main,'save_asset_library'):
                    request=Request({'type':'http','method':'POST','path':'/','scheme':'http','server':('127.0.0.1',3000),'headers':[(b'host',b'127.0.0.1:3000'),(b'origin',b'http://127.0.0.1:3000')]})
                    result=await main.promote_result_record(music['id'],main.ResultPromoteRequest(category_id='group',library_id='library'),request)
                    self.assertEqual(result['item']['media_category'],'music')
                    self.assertEqual(result['item']['kind'],'audio')

    def test_new_music_run_records_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            storage=ProjectStorage(directory);storage.ensure_layout()
            source=Path(directory)/'song.wav';source.write_bytes(b'music')
            result=storage.store_result_file(source,'song.wav')
            run=storage.prepare_run('canvas','music-node','operation',{'node_type':'music_generation'},{})
            storage.append_run_results(run['run_id'],[result['id']])
            self.assertEqual(storage.get_result(result['id'])['media_category'],'music')

    def test_windows_clipboard_uses_persistent_file_drop_and_encoded_data(self):
        import base64
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'中文 audio.wav';path.write_bytes(b'wave')
            with patch.object(system_clipboard.sys,'platform','win32'),patch.object(system_clipboard.subprocess,'CREATE_NO_WINDOW',0,create=True),patch.object(system_clipboard.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'ok','')) as run:
                system_clipboard.write_clipboard([path])
                command=run.call_args.args[0]
                self.assertIn('-STA',command)
                script=base64.b64decode(command[-1]).decode('utf-16le')
                self.assertIn('SetFileDropList',script)
                self.assertIn('SetDataObject($data, $true',script)
                payload=json.loads(base64.b64decode(run.call_args.kwargs['env']['LAOHU_CLIPBOARD_PAYLOAD']))
                self.assertEqual(payload['paths'],[str(path.resolve())])
                self.assertNotIn(str(path),script)

    def test_native_command_keeps_file_paths_out_of_executable_code(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"中文 $(touch forbidden) ' image.png"
            Image.new('RGB',(4,4)).save(path)
            with patch.object(system_clipboard.sys,'platform','darwin'),patch.object(system_clipboard.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'ok','')) as run:
                system_clipboard.write_clipboard([path])
                command=run.call_args.args[0]
                self.assertNotIn(str(path),command[-2])
                self.assertEqual(json.loads(command[-1])['paths'],[str(path.resolve())])
                self.assertNotIn('shell',run.call_args.kwargs)

    def test_shared_media_copy_and_selection_toggle(self):
        shared=(ROOT/'static/js/media-ui.js').read_text()
        script=(ROOT/'static/js/asset-manager.js').read_text()
        toggle=script[script.index('function toggleMaterialSelection'):script.index('async function copyLibraryMaterials')]
        code="""
const assert=require('node:assert/strict');
const calls=[];
global.window={StudioI18n:{lang:()=> 'zh'}};
global.location={origin:'http://192.168.1.253:3000'};
global.fetch=async(url,opts)=>{calls.push({url,payload:JSON.parse(opts.body)});return {ok:true,json:async()=>({ok:true})};};
"""+shared+toggle+"""
(async()=>{
 const items=[{id:'one',kind:'image',url:'/api/results/one'},{id:'two',kind:'audio',media_category:'music',url:'/api/results/two'}];
 const selection=new Set();toggleMaterialSelection(items,selection);assert.equal(selection.size,2);toggleMaterialSelection(items,selection);assert.equal(selection.size,0);
 assert.equal(window.StudioMedia.category(items[1]),'music');
 assert.equal(window.StudioMedia.category({kind:'audio',name:'song.mp3'}),'audio');
 await window.StudioMedia.copy(items);assert.deepEqual(calls[0].payload.urls,['/api/results/one','/api/results/two']);
 await assert.rejects(window.StudioMedia.copy([{url:'https://external.test/a.png'}]));
 console.log('ok');
})();
"""
        result=subprocess.run(['node','-e',code],capture_output=True,text=True,cwd=ROOT)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'ok')

    def test_numeric_parameter_input_preserves_values_for_contract_validation_and_syncs(self):
        source=(ROOT/'static/js/smart-canvas.js').read_text()
        helpers=source[source.index('function capabilityInputValue'):source.index('function renderCapabilityParameterEditor')]
        code="const assert=require('node:assert/strict');global.document={activeElement:null};\n"+helpers+"""
const control={dataset:{capabilityType:'number'},value:'0',min:'0',max:'100'};
assert.equal(capabilityInputValue(control),0);
control.value='150';assert.equal(capabilityInputValue(control),150);
control.value='';assert.equal(capabilityInputValue(control),undefined);
control.value='-5';assert.equal(capabilityInputValue(control),-5);
control.value='31.8';control.dataset.capabilityType='integer';assert.equal(capabilityInputValue(control),31.8);
const contract=require('./static/js/smart-model-capabilities.js');
assert.equal(contract.parameterIssue({type:'integer',min:0,max:100},capabilityInputValue(control)),'PARAM_INVALID');
const peer={value:'0'};control.type='number';control.closest=()=>({querySelectorAll:()=>[control,peer]});
syncCapabilityNumericControls(control,32);assert.equal(peer.value,'32');assert.equal(control.value,'32');
"""
        result=subprocess.run(['node','-e',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_import_remaps_nested_node_references_without_altering_source(self):
        source=(ROOT/'static/js/smart-canvas.js').read_text()
        helper=source[source.index('function remapImportedWorkflowNodeRefs'):source.index('function insertSmartWorkflowIntoCanvas')]
        code="const assert=require('node:assert/strict');\n"+helper+"""
const original={id:'a',resultVersions:[{runInputRefs:[{nodeId:'b',url:'/api/results/r'}]}],promptDraftHtml:'<span data-node-id="b">ref</span>',other:'ordinary prose'};
const mapped=remapImportedWorkflowNodeRefs(original,new Map([['a','new-a'],['b','new-b']]));
assert.equal(mapped.id,'new-a');assert.equal(mapped.resultVersions[0].runInputRefs[0].nodeId,'new-b');
assert.equal(mapped.resultVersions[0].runInputRefs[0].url,'/api/results/r');
assert.equal(mapped.promptDraftHtml,'<span data-node-id="new-b">ref</span>');
assert.equal(original.id,'a');assert.equal(original.resultVersions[0].runInputRefs[0].nodeId,'b');
"""
        result=subprocess.run(['node','-e',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_external_parameters_keep_schema_values_and_separate_stores(self):
        source=(ROOT/'static/js/smart-canvas.js').read_text()
        spec=source[source.index('function externalParameterSpec'):source.index('function externalParameterProfile')]
        setter=source[source.index('function setCapabilityParameter('):source.index('function generatedCapabilityParameterLabel')]
        code="const assert=require('node:assert/strict');const settings={};let writes=0;function persistActiveSmartSettings(){writes++}function scheduleSave(){}function rhFieldRole(f){return f.kind}function rhExtractFieldOptions(f){return f.options}\n"+spec+setter+"""
const field={kind:'select',fieldType:'SELECT',options:['0','1'],optionLabels:{'0':'关闭','1':'开启'},fieldValue:'0',label:'模式'};
const definition=externalParameterSpec(field,'rh');assert.equal(definition.type,'enum');assert.deepEqual(definition.options,['0','1']);assert.equal(definition.option_labels['0'],'关闭');
setCapabilityParameter({_externalEngine:'rh',parameters:{mode:definition}},'mode','0');
assert.equal(settings.rhParams.mode.value,'0');
const num={type:'number',min:0,max:10};setCapabilityParameter({_externalEngine:'comfy',parameters:{scale:num}},'scale',0);
assert.equal(settings.comfyParams.scale,0);setCapabilityParameter({_externalEngine:'comfy',parameters:{scale:num}},'scale',20);assert.equal(settings.comfyParams.scale,20);
setCapabilityParameter({_externalEngine:'comfy',parameters:{flag:{type:'boolean'}}},'flag',false);assert.equal(settings.comfyParams.flag,false);
assert.equal(settings.capabilityParameters,undefined);assert.equal(writes,4);
"""
        result=subprocess.run(['node','-e',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
