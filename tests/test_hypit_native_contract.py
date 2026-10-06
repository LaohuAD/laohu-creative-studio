"""原生 Hypit 契约回归：仅显式启用，在本地假供应商完成一次生成，不调用付费 API。"""
import base64
import asyncio
import copy
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import unittest
import wave
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response

from canvas_core.json_store import read_json, write_json
from canvas_core.hypit_config import (
    HYPIT_FLOW_SCHEMA_VERSION,
    HYPIT_SETTINGS_CANVAS_ID,
    plan_hypit_slot,
    validate_hypit_settings_canvas,
)
from hypit_runtime import HypitRuntime
from project_storage import ProjectStorage
from studio_hypit_flow import HypitFlowRunner
from studio_hypit_models import create_hypit_models_router

ROOT = Path(__file__).resolve().parents[1]
CACHE_TMP = ROOT / 'cache' / 'studio-tests' / 'tmp'


def _native_temp_root(prefix):
    CACHE_TMP.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=CACHE_TMP)


@contextmanager
def local_asgi_server(app):
    """在本机临时端口运行真实 FastAPI router，停止时只关闭本测试创建的 server。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
        log_level='critical', access_log=False, lifespan='off'))
    thread = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[sock])), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not server.started and thread.is_alive():
        time.sleep(.02)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=2)
        sock.close()
        raise RuntimeError('隔离 Hypit workflow 测试 HTTP server 未就绪')
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


def json_http(base_url, path, method='GET', payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(base_url + path, data=data, method=method,
        headers={'content-type': 'application/json'} if data is not None else {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        body=exc.read()
        raise AssertionError(f'{method} {path} returned HTTP {exc.code}: {body.decode("utf-8",errors="replace")}') from exc
    return json.loads(body.decode('utf-8'))


class NativeThemeAssetTests(unittest.TestCase):
    def test_native_theme_asset_covers_light_dark_and_internal_surfaces(self):
        theme = (ROOT / 'static/css/hypit-native-theme.css').read_text(encoding='utf-8')
        palettes = (ROOT / 'static/css/studio-theme-palettes.css').read_text(encoding='utf-8')
        self.assertIn(':root[data-laohu-theme="dark"]', theme)
        self.assertIn('--app: var(--studio-bg)', theme)
        self.assertIn('--interaction-accent: var(--studio-focus)', theme)
        self.assertIn('--subtab-active-surface: var(--studio-accent)', theme)
        self.assertIn('--subtab-active-text: var(--studio-strong-text)', theme)
        self.assertIn('--brand-foreground: var(--studio-strong-text)', theme)
        self.assertIn('--native-code-line-number: var(--studio-muted)', theme)

        def rule_body(selector):
            start = palettes.index(selector)
            opening = palettes.index('{', start)
            closing = palettes.index('}', opening)
            return palettes[opening + 1:closing]

        identities = ('studio-violet', 'sunlit', 'vermilion', 'forest', 'classic')
        for identity in identities:
            light_selector = f':root[data-laohu-theme-id="{identity}"]'
            dark_selector = f':root[data-laohu-theme-id="{identity}"][data-laohu-theme="dark"]'
            self.assertIn(light_selector, palettes)
            self.assertIn(dark_selector, palettes)
            light_roles = rule_body(light_selector)
            dark_roles = rule_body(dark_selector)
            for role in ('--studio-bg:', '--studio-surface:', '--studio-accent:'):
                self.assertIn(role, light_roles, f'{identity} light palette must define {role}')
                self.assertIn(role, dark_roles, f'{identity} dark palette must define {role}')
            self.assertIn('--studio-strong-text:', light_roles, f'{identity} must define its strong foreground role')

        self.assertIn('.topbar', theme)
        self.assertIn('.timeline-panel', theme)
        self.assertIn('.parameter-select-menu', theme)
        self.assertIn('@media (prefers-reduced-motion: reduce)', theme)


@unittest.skipUnless(os.environ.get('STUDIO_NATIVE_HYPIT_TESTS') == '1', '原生 Hypit 验收需要显式启用')
class NativeHypitContractTests(unittest.TestCase):
    def test_native_text_surface_is_a_real_text_output(self):
        """先让真实 Hypit CLI 解析 Text author surface，不能把文本伪装成媒体。"""
        distribution = HypitRuntime(ROOT).distribution
        self.assertTrue((distribution / 'bin/hypit.mjs').is_file(), '先准备已审核的 Hypit 运行环境')
        with _native_temp_root('hypit-native-text-') as folder:
            root = Path(folder)
            (root / 'static').mkdir()
            for name in ('hypit-models.mjs', 'hypit-endpoint.mjs'):
                shutil.copyfile(ROOT / 'static' / name, root / 'static' / name)
            project = root / 'workflows/hypit/native-text'
            project.mkdir(parents=True)
            (project / 'main.svml').write_text('''<?svml using="@hypit/markup@1"?>
<svml><import as="studio" from="@laohu/studio-models@1"/><import as="text" from="@hypit/text@1"/>
<text:Value id="prompt">Native text contract fixture</text:Value>
<studio:Text id="generated" prompt={prompt}/>
<studio:Text id="derived" prompt={generated.text}/></svml>''', encoding='utf-8')
            (project / 'main.svrun').write_text('''<?svml using="@hypit/run-markup@1"?>
<svrun version="1"><author source="./main.svml"/><target output="derived.text"/></svrun>''', encoding='utf-8')

            class Runtime(HypitRuntime):
                @property
                def distribution(self):
                    return distribution

                def configure_profile(self, project_id):
                    path = super().configure_profile(project_id)
                    value = read_json(path)
                    value['endpoints'] = {'studio.models': value['endpoints']['studio.models']}
                    write_json(path, value)
                    return path

            runtime = Runtime(root)
            # check 不发请求；非空 loopback 地址只让受管 runtime 安装本地 Endpoint package。
            runtime.base_url = 'http://127.0.0.1:1'
            try:
                result = runtime.execute('native-text', 'check', 'main.svrun')['output']
                self.assertTrue(result['ok'], result)
                plan = runtime.execute('native-text', 'plan', 'main.svrun')['output']
                self.assertEqual(plan['unresolvedRequestCount'], 0, plan)
            finally:
                runtime.close()

    def test_native_workflow_sources_route_through_real_models_router_and_collect_results(self):
        """真实 Hypit check/plan/build 穿过真实 router 与隔离 workflow callbacks。"""
        distribution = HypitRuntime(ROOT).distribution
        self.assertTrue((distribution / 'bin/hypit.mjs').is_file(), '先准备已审核的 Hypit 运行环境')
        cases = [
            {'slot':'image','tag':'Image','request_kind':'image','expected_kind':'image','output':'image',
             'source':'runninghub_app','provider_id':'runninghub',
             'region':'global','item_id':'fixture-ai-app','mime_type':'image/png','extension':'png'},
            {'slot':'video','tag':'Video','request_kind':'video','expected_kind':'video','output':'video',
             'source':'runninghub_workflow','provider_id':'runninghub',
             'region':'cn','item_id':'fixture-cn-workflow','mime_type':'video/mp4','extension':'mp4'},
            {'slot':'audio','tag':'Audio','request_kind':'audio','expected_kind':'audio','output':'audio',
             'source':'local_comfy_workflow','provider_id':'local-comfyui',
             'region':'','item_id':'fixture-local-workflow','mime_type':'audio/wav','extension':'wav'},
            {'slot':'text','tag':'Text','request_kind':'text','expected_kind':'text','output':'text',
             'source':'runninghub_app','provider_id':'runninghub',
             'region':'global','item_id':'fixture-text-app','mime_type':'text/plain','extension':'text'},
            {'slot':'music','tag':'Music','request_kind':'music','expected_kind':'audio','output':'audio',
             'source':'runninghub_workflow','provider_id':'runninghub',
             'region':'global','item_id':'fixture-music-workflow','mime_type':'audio/wav','extension':'wav'},
            {'slot':'voice','tag':'Speech','request_kind':'audio','expected_kind':'audio','output':'audio',
             'source':'runninghub_app','provider_id':'runninghub',
             'region':'cn','item_id':'fixture-speech-app','mime_type':'audio/wav','extension':'wav'},
        ]
        schema_fields=[{'key':'prompt','label':'Prompt','type':'text','required':True}]
        comfy_schema_fields=[{'key':'prompt','label':'Prompt','name':'text','type':'STRING','required':True}]
        fingerprint=hashlib.sha256(json.dumps({'fields':schema_fields},ensure_ascii=False,sort_keys=True,
            separators=(',',':')).encode()).hexdigest()
        fingerprints={case['slot']:fingerprint for case in cases}
        options=[]
        for case in cases:
            fields=comfy_schema_fields if case['source']=='local_comfy_workflow' else schema_fields
            options.append({**{key:case[key] for key in ('source','provider_id','region','item_id')},
                'name':case['item_id'],'enabled':True,'schema_status':'ready','schema_fingerprint':fingerprints[case['slot']],
                'fields':copy.deepcopy(fields)+[{'key':'api_key','label':'API Key','type':'text',
                    'default':'ISOLATED_FIXTURE_SECRET_VALUE','required':False}]})
        private_marker='PRIVATE_FIXTURE_WORKFLOW_MUST_NOT_ESCAPE'
        projects={f"native-{case['slot']}":{'id':f"native-{case['slot']}"} for case in cases}
        callback_events=[]
        execution_snapshots=[]

        def get_project(project_id,module):
            if module!='hypit' or project_id not in projects: raise KeyError(project_id)
            return copy.deepcopy(projects[project_id])

        def get_capabilities():
            # workflow 槽位不读取用户 API catalog；固定为空目录以证明测试未依赖本机平台设置。
            return {'schema_version':1,'providers':[]}

        async def validate(_request):
            raise AssertionError('workflow request must not fall back to API model validation')

        async def generate(_request):
            raise AssertionError('workflow request must not fall back to API model generation')

        def get_workflow_options():
            return copy.deepcopy(options)

        def resolve_workflow(selection):
            identity={key:selection.get(key) for key in ('source','provider_id','region','item_id')}
            item=next((entry for entry in options if all(entry.get(key)==value for key,value in identity.items())),None)
            if item is None: raise LookupError('unknown isolated workflow identity')
            return {**copy.deepcopy(item),'workflow_json':{'fixture_private_marker':private_marker},
                'config':{'fixture_private_marker':private_marker}}

        async def validate_workflow(request,execution_snapshot):
            callback_events.append({'stage':'validate','request':copy.deepcopy(request),
                'private_snapshot':copy.deepcopy(execution_snapshot)})
            execution_snapshots.append(copy.deepcopy(execution_snapshot))
            return {'ok':True}

        async def generate_workflow(request,execution_snapshot):
            # 这三步是 fake provider adapter：验证 router 传来的来源和站点，模拟提交、查询、收结果。
            ticket=f"fake-{len(callback_events)+1}"
            base={'source':request['source'],'provider_id':request['provider_id'],
                'region':request['region'],'item_id':request['item_id'],'slot':request['slot']}
            callback_events.extend([{'stage':'submit',**base,'ticket':ticket},
                {'stage':'query',**base,'ticket':ticket,'status':'succeeded'},
                {'stage':'result',**base,'ticket':ticket}])
            if request['expected_kind']=='text':
                return {'text':'Generated workflow text fixture'}
            key={'image':'images','video':'videos','audio':'audios'}[request['expected_kind']]
            result={key:[{'url':f"/fixture/{request['expected_kind']}.{request['expected_kind']}",
                'kind':request['expected_kind'],'mime_type':{'image':'image/png','video':'video/mp4','audio':'audio/wav'}[request['expected_kind']]}]}
            if request['expected_kind']=='video':
                result['images']=[{'url':'/fixture/video-cover.image','kind':'image','mime_type':'image/png'}]
                result['files']=[{'url':'/fixture/unknown.bin'}]
            return result

        app=FastAPI()
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1cAAAAASUVORK5CYII=')
        wav=io.BytesIO()
        with wave.open(wav,'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(8000); output.writeframes(b'\0\0'*800)
        media={'image':(png,'image/png'),'video':(b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom','video/mp4'),
            'audio':(wav.getvalue(),'audio/wav')}
        @app.get('/fixture/{filename}')
        def fixture_media(filename):
            key=filename.split('.',1)[0]
            if key not in media: return Response(status_code=404)
            data,mime=media[key]
            return Response(data,media_type=mime)

        with _native_temp_root('hypit-native-workflows-') as folder:
            root=Path(folder)
            app.include_router(create_hypit_models_router(root,
                get_project,get_capabilities,validate,generate,
                get_workflow_options=get_workflow_options,resolve_workflow=resolve_workflow,
                validate_workflow=validate_workflow,generate_workflow=generate_workflow))
            for filename in ('hypit-models.mjs','hypit-endpoint.mjs'):
                (root/'static').mkdir(exist_ok=True)
                shutil.copyfile(ROOT/'static'/filename,root/'static'/filename)
            class Runtime(HypitRuntime):
                @property
                def distribution(self): return distribution
                def configure_profile(self,project_id):
                    path=super().configure_profile(project_id)
                    value=read_json(path)
                    value['endpoints']={'studio.models':value['endpoints']['studio.models']}
                    write_json(path,value)
                    return path
            runtime=Runtime(root)
            adapter_events=[]
            # Events and settings remain in this temporary test process/root only.
            with local_asgi_server(app) as base_url:
                runtime.base_url=base_url
                initial=json_http(base_url,'/api/studio/hypit/models/settings')
                self.assertNotIn('ISOLATED_FIXTURE_SECRET_VALUE',json.dumps(initial))
                self.assertNotIn('api_key',json.dumps(initial))
                revision=initial['revision']
                for case in cases:
                    slot=case['slot']
                    public_options=json_http(base_url,f'/api/studio/hypit/models/workflow-options?slot={slot}')
                    options_text=json.dumps(public_options)
                    self.assertNotIn(private_marker,options_text)
                    self.assertNotIn('workflow_json',options_text)
                    self.assertNotIn('config',options_text)
                    self.assertNotIn('ISOLATED_FIXTURE_SECRET_VALUE',options_text)
                    self.assertNotIn('api_key',options_text)
                    selected={'selection_kind':'workflow','source':case['source'],
                        'provider_id':case['provider_id'],'region':case['region'],'item_id':case['item_id'],
                        'expected_slot':slot,'expected_kind':case['expected_kind'],'confirmed_for_slot':True,
                        'schema_fingerprint':fingerprints[slot],'input_bindings':{'prompt':'prompt'},
                        'field_values':{},'provider':'','model':'','parameters':{}}
                    saved=json_http(base_url,'/api/studio/hypit/models/settings','PUT',
                        {'expected_revision':revision,'defaults':{slot:selected}})
                    revision=saved['revision']
                    self.assertNotIn('ISOLATED_FIXTURE_SECRET_VALUE',json.dumps(saved))
                    self.assertNotIn('api_key',json.dumps(saved))
                    self.assertEqual(saved['defaults'][slot]['selection_kind'],'workflow')
                    project_id=f'native-{slot}'
                    project=root/'workflows/hypit'/project_id
                    project.mkdir(parents=True)
                    prompt='Native '+slot+' workflow fixture'
                    if slot=='text':
                        source=f'''<?svml using="@hypit/markup@1"?>\n<svml><import as="studio" from="@laohu/studio-models@1"/><import as="text" from="@hypit/text@1"/>\n<text:Value id="prompt">{prompt}</text:Value>\n<studio:Text id="generated" prompt={{prompt}}/><studio:Text id="derived" prompt={{generated.text}}/></svml>'''
                        target='derived.text'
                    else:
                        source=f'''<?svml using="@hypit/markup@1"?>\n<svml><import as="studio" from="@laohu/studio-models@1"/><import as="text" from="@hypit/text@1"/>\n<text:Value id="prompt">{prompt}</text:Value>\n<studio:{case['tag']} id="generated" prompt={{prompt}}/></svml>'''
                        target=f'generated.{case["output"]}'
                    (project/'main.svml').write_text(source,encoding='utf-8')
                    (project/'main.svrun').write_text(f'''<?svml using="@hypit/run-markup@1"?>\n<svrun version="1"><author source="./main.svml"/><target output="{target}"/></svrun>''',encoding='utf-8')

                    expected_callback_count=2 if slot=='text' else 1
                    try:
                        check=runtime.execute(project_id,'check','main.svrun')['output']
                        self.assertTrue(check['ok'],check)
                        plan=runtime.execute(project_id,'plan','main.svrun')['output']
                        self.assertEqual(plan['unresolvedRequestCount'],0,plan)
                        runtime.execute(project_id,'runtime-up')
                        build=runtime.execute(project_id,'build','main.svrun')['output']['build']['id']
                        deadline=time.monotonic()+45
                        while time.monotonic()<deadline:
                            status=runtime.execute(project_id,'status',build_id=build)['output']['build']
                            if status['work']['state']=='done': break
                            time.sleep(.15)
                        self.assertEqual(status['work'].get('outcome'),'complete',status)
                        self.assertEqual(status['result']['outputCount'],expected_callback_count)
                        requests=[event['request'] for event in callback_events if event['stage']=='validate']
                        self.assertEqual(len(requests),expected_callback_count)
                        self.assertTrue(all(item.get('selection_kind')=='workflow' for item in requests))
                        self.assertTrue(all(item.get('source')==case['source'] and item.get('region')==case['region'] for item in requests))
                        self.assertTrue(all(item.get('slot')==slot and item.get('expected_slot')==slot for item in requests))
                        self.assertTrue(all(item.get('kind')==case['request_kind'] for item in requests))
                        self.assertTrue(all(item.get('expected_kind')==case['expected_kind'] and item.get('provider_id')==case['provider_id'] for item in requests))
                        self.assertEqual(requests[0]['prompt'],prompt)
                        if slot=='text': self.assertEqual(requests[1]['prompt'],'Generated workflow text fixture')
                        adapter_stages=[event['stage'] for event in callback_events if event['stage'] in {'submit','query','result'}]
                        self.assertEqual(adapter_stages,['submit','query','result']*expected_callback_count)
                        task_files=list((root/'data/hypit_model_tasks'/project_id).glob('*.json'))
                        self.assertEqual(len(task_files),expected_callback_count)
                        task_records=[read_json(path) for path in task_files]
                        self.assertTrue(all(record.get('execution_snapshot',{}).get('workflow_json',{}).get('fixture_private_marker')==private_marker
                            for record in task_records))
                        self.assertTrue(all('api_key' not in json.dumps(record.get('execution_snapshot',{}))
                            and 'ISOLATED_FIXTURE_SECRET_VALUE' not in json.dumps(record.get('execution_snapshot',{}))
                            for record in task_records))
                        current_snapshots=execution_snapshots[-expected_callback_count:]
                        self.assertEqual(len(current_snapshots),expected_callback_count)
                        self.assertTrue(all(snapshot.get('workflow_json',{}).get('fixture_private_marker')==private_marker
                            for snapshot in current_snapshots))
                        request_id=task_records[0].get('request_id') if task_records else None
                        if slot=='video':
                            self.assertEqual(len(task_records[0]['result']['videos']),1)
                            self.assertNotIn('images', task_records[0]['result'],
                                'Hypit video 请求只公开匹配的视频槽结果，辅助封面不属于该槽结果')
                        if case['expected_kind']!='text':
                            self.assertTrue(list((root/'assets/output/hypit'/project_id).rglob('*.'+case['extension'])))
                        if request_id:
                            public_task=json_http(base_url,f'/api/studio/hypit/models/projects/{project_id}/requests/{request_id}')
                            self.assertNotIn(private_marker,json.dumps(public_task))
                            self.assertNotIn('execution_snapshot',public_task)
                    finally:
                        stopped=subprocess.run(runtime.command()+['runtime','down','--workspace',str(project),'--json'],
                            cwd=project,env=runtime.environment(),capture_output=True,timeout=30)
                        self.assertEqual(stopped.returncode,0,stopped.stderr.decode('utf-8',errors='replace'))
                    callback_events.clear()
                runtime.close()

    def test_native_requests_use_settings_canvas_graph_runner_and_managed_collection(self):
        """真实 Hypit check/plan/build 通过新设置图、持久 Runner 与隔离受管结果存储。"""
        from studio_hypit_models import create_hypit_models_router

        distribution = HypitRuntime(ROOT).distribution
        self.assertTrue((distribution / 'bin/hypit.mjs').is_file(), '先准备已审核的 Hypit 运行环境')
        with _native_temp_root('hypit-native-settings-graph-') as folder:
            root = Path(folder)
            storage = ProjectStorage(root)
            storage.ensure_layout()

            # 测试图直接代表新版设置画布；旧 JSON 仅放入隔离根作为反向哨兵，
            # 其模型 ID 不得成为原生请求来源。
            canvas = {
                'id': HYPIT_SETTINGS_CANVAS_ID,
                'title': '隔离 Hypit 配置图', 'icon': 'sparkles', 'kind': 'smart',
                'owner': '', 'color': '', 'pinned': False, 'project': '__hypit_settings__',
                'created_at': 10, 'updated_at': 10, 'revision': 7,
                'node_schema_version': 1,
                'hypit_flow_schema_version': HYPIT_FLOW_SCHEMA_VERSION,
                'hypit_legacy_migration_done': True,
                'nodes': [
                    {'id': 'prompt-input', 'type': 'smart-material', 'title': '本次提示词',
                     'sourceKind': 'input', 'hypitInputLocked': False, 'images': [], 'x': 20, 'y': 40},
                    {'id': 'image-generator', 'type': 'smart-image-generator', 'title': '隔离图片生成',
                     'promptDraftText': '', 'runSettings': {
                         'engine': 'api', 'apiKind': 'image', 'provider_id': 'fixture-provider',
                         'model': 'fixture-image-model', 'region': '',
                         'capabilityParameters': {'fixture-image-model': {'count': 2}},
                     }},
                    {'id': 'image-output', 'type': 'smart-hypit-output',
                     'hypitSlot': 'image', 'outputKind': 'image'},
                ],
                'connections': [
                    {'id': 'prompt-to-generator', 'from': 'prompt-input', 'to': 'image-generator', 'kind': 'input'},
                    {'id': 'generator-to-output', 'from': 'image-generator', 'to': 'image-output', 'kind': 'flow'},
                ],
                'viewport': {'x': 0, 'y': 0, 'scale': 1}, 'logs': [], 'settings': {},
            }
            validate_hypit_settings_canvas(canvas)
            initial_plan = plan_hypit_slot(canvas, 'image', 'image-output')
            self.assertEqual(initial_plan['node_ids'], ['prompt-input', 'image-generator', 'image-output'])
            legacy_path = root / 'data' / 'hypit_settings.json'
            legacy_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_path.write_text(json.dumps({
                'version': 2, 'defaults': {'image': {
                    'selection_kind': 'api_model', 'provider': 'legacy-provider-must-not-run',
                    'model': 'legacy-model-must-not-run',
                }},
            }), encoding='utf-8')
            legacy_digest = hashlib.sha256(legacy_path.read_bytes()).hexdigest()

            provider_events = []
            collection_events = []
            projection_events = []
            runner_notifications = []
            runner_submissions = []
            base_url = {'value': ''}
            png = base64.b64decode(
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1cAAAAASUVORK5CYII='
            )

            def connected_prompt(graph, node):
                by_id = {str(item.get('id') or ''): item for item in graph.get('nodes', [])}
                prompt_nodes = [by_id.get(str(edge.get('from') or '')) for edge in graph.get('connections', [])
                                if str(edge.get('to') or '') == str(node.get('id') or '')]
                values = []
                for source in prompt_nodes:
                    if not isinstance(source, dict) or source.get('type') != 'smart-material':
                        continue
                    for item in source.get('images') or []:
                        if isinstance(item, dict) and item.get('kind') == 'text':
                            values.append(str(item.get('text') or item.get('content') or ''))
                return '\n'.join(value for value in values if value.strip())

            async def prepare_node_request(graph, node, operation_id, upstream_results, payload, *, preflight):
                del operation_id, upstream_results, preflight
                settings = node.get('runSettings') if isinstance(node.get('runSettings'), dict) else {}
                prompt = connected_prompt(graph, node)
                self.assertTrue(prompt.strip(), '原生 prompt 必须映射进设置图的提示词素材节点')
                request = {
                    'kind': 'image', 'provider_id': settings.get('provider_id'),
                    'model': settings.get('model'), 'region': settings.get('region') or '',
                    'prompt': prompt,
                    'parameters': copy.deepcopy(payload.get('parameters') or {}),
                }
                self.assertEqual(request['parameters'], {'count': 1}, '本次原生请求参数应覆盖图内默认值')
                provider_events.append(('prepare', request['provider_id'], request['model'], prompt))
                return request

            async def preflight_node(_graph, _node, request, operation_id):
                del operation_id
                self.assertEqual(request['provider_id'], 'fixture-provider')
                self.assertEqual(request['model'], 'fixture-image-model')
                self.assertNotIn('legacy-model-must-not-run', json.dumps(request))
                provider_events.append(('preflight', request['provider_id'], request['model']))
                return {'validated': True, 'provider_id': request['provider_id'], 'model': request['model']}

            async def execute_node(_graph, _node, request, operation_id, resolved, on_submitted):
                del operation_id
                self.assertTrue(resolved['validated'])
                provider_events.append(('submit', request['provider_id'], request['model'], request['prompt']))
                on_submitted({'provider_task_id': 'fake-provider-task-1'})
                return {'images': [{
                    'kind': 'image', 'mime_type': 'image/png',
                    'url': base_url['value'] + '/fake-provider/result.png',
                }]}

            async def collect_results(result, request, task):
                self.assertEqual(request['kind'], 'image')
                self.assertEqual(task['test'], False)
                items = result.get('images') if isinstance(result, dict) else None
                self.assertEqual(len(items or []), 1)

                def read_provider_result():
                    with urllib.request.urlopen(items[0]['url'], timeout=10) as response:
                        return response.headers.get_content_type(), response.read()

                mime_type, content = await asyncio.to_thread(read_provider_result)
                self.assertEqual(mime_type, 'image/png')
                self.assertEqual(content, png)
                source = root / 'cache' / 'studio-tests' / 'fake-provider-result.png'
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(content)
                stored = await asyncio.to_thread(storage.store_result_file, source, 'native-settings-graph-result.png')
                collection_events.append({'task_id': task['id'], 'result_id': stored['id'], 'kind': stored['kind']})
                return [{
                    'kind': 'image', 'mime_type': 'image/png', 'name': stored['display_name'],
                    'url': stored['url'], 'resultId': stored['id'],
                }]

            async def notify(canvas_id, run_id, status):
                runner_notifications.append((canvas_id, run_id, status))

            runner = HypitFlowRunner(
                load_canvas=lambda canvas_id: copy.deepcopy(canvas) if canvas_id == HYPIT_SETTINGS_CANVAS_ID else None,
                storage=storage,
                prepare_node_request=prepare_node_request,
                preflight_node=preflight_node,
                execute_node=execute_node,
                collect_results=collect_results,
                notify=notify,
                lock=threading.RLock(),
                now_ms=lambda: int(time.time() * 1000),
            )

            def get_settings_canvas_projection():
                projection_events.append('settings')
                plan = plan_hypit_slot(canvas, 'image', 'image-output')
                return {
                    'canvas_id': HYPIT_SETTINGS_CANVAS_ID, 'revision': canvas['revision'],
                    'defaults': {'image': {
                        'selection_kind': 'settings_canvas', 'status': 'connected', 'connected': True,
                        'expected_kind': 'image', 'output_node_id': 'image-output',
                        'source_node_id': 'image-generator', 'source_node_type': 'smart-image-generator',
                        'node_ids': plan['node_ids'], 'recipe_fingerprint': plan['recipe_fingerprint'],
                        'node_source': {'kind': 'api_model', 'provider_id': 'fixture-provider',
                                        'model_id': 'fixture-image-model'},
                    }},
                }

            async def submit_settings_canvas_request(slot, output_node_id, request_id, payload, test=False):
                resolved_output_id = output_node_id or str(
                    plan_hypit_slot(canvas, slot)['output_node'].get('id') or ''
                )
                runner_submissions.append((request_id, copy.deepcopy(payload), resolved_output_id, test))
                return await runner.submit(slot, resolved_output_id, request_id, payload, test=test)

            def get_settings_canvas_request(run_id):
                flow = runner.get(run_id)
                if flow is None:
                    return None
                result = {'images': [], 'videos': [], 'audios': [], 'texts': [], 'files': []}
                for item in flow.get('media') or []:
                    key = {'image': 'images', 'video': 'videos', 'audio': 'audios', 'text': 'texts'}.get(
                        str(item.get('kind') or ''), 'files'
                    )
                    result[key].append(copy.deepcopy(item))
                return {**flow, 'result': result}

            project_id = 'native-settings-graph'
            projects = {project_id: {'id': project_id, 'module': 'hypit'}}

            def get_project(requested_project_id, module):
                if module != 'hypit' or requested_project_id not in projects:
                    raise KeyError(requested_project_id)
                return copy.deepcopy(projects[requested_project_id])

            app = FastAPI()
            app.include_router(create_hypit_models_router(
                root, get_project, lambda: {'schema_version': 1, 'providers': []},
                lambda _request: {'ok': True}, lambda _request: {'images': []},
                get_settings_canvas_projection=get_settings_canvas_projection,
                submit_settings_canvas_request=submit_settings_canvas_request,
                get_settings_canvas_request=get_settings_canvas_request,
            ))

            @app.get('/fake-provider/result.png')
            def fake_provider_result():
                return Response(png, media_type='image/png')

            @app.get('/api/results/{result_id}')
            def managed_result(result_id):
                record = storage.get_result(result_id)
                path = storage.result_path(result_id)
                if not record or not path or not path.is_file():
                    return Response(status_code=404)
                return Response(path.read_bytes(), media_type=record.get('mime') or 'application/octet-stream')

            (root / 'static').mkdir(parents=True, exist_ok=True)
            for name in ('hypit-models.mjs', 'hypit-endpoint.mjs'):
                shutil.copyfile(ROOT / 'static' / name, root / 'static' / name)
            project = root / 'workflows' / 'hypit' / project_id
            project.mkdir(parents=True)
            prompt = 'Native prompt routed through the saved settings graph'
            (project / 'main.svml').write_text(f'''<?svml using="@hypit/markup@1"?>
<svml><import as="studio" from="@laohu/studio-models@1"/><import as="text" from="@hypit/text@1"/>
<text:Value id="prompt">{prompt}</text:Value>
<studio:Image id="generated" prompt={{prompt}} parameters='{{"count":1}}'/></svml>''', encoding='utf-8')
            (project / 'main.svrun').write_text('''<?svml using="@hypit/run-markup@1"?>
<svrun version="1"><author source="./main.svml"/><target output="generated.image"/></svrun>''', encoding='utf-8')

            class Runtime(HypitRuntime):
                @property
                def distribution(self):
                    return distribution

                def configure_profile(self, configured_project_id):
                    path = super().configure_profile(configured_project_id)
                    value = read_json(path)
                    value['endpoints'] = {'studio.models': value['endpoints']['studio.models']}
                    write_json(path, value)
                    return path

            runtime = Runtime(root)
            runtime.base_url = 'http://127.0.0.1:1'
            runtime_started = False
            try:
                with local_asgi_server(app) as local_url:
                    base_url['value'] = local_url
                    runtime.base_url = local_url
                    settings = json_http(local_url, '/api/studio/hypit/models/settings')
                    self.assertEqual(settings['source'], 'settings_canvas')
                    self.assertEqual(settings['canvas_id'], HYPIT_SETTINGS_CANVAS_ID)
                    self.assertEqual(settings['defaults']['image']['node_source']['provider_id'], 'fixture-provider')
                    self.assertNotIn('legacy-provider-must-not-run', json.dumps(settings))
                    self.assertNotIn('legacy-model-must-not-run', json.dumps(settings))

                    check = runtime.execute(project_id, 'check', 'main.svrun')['output']
                    self.assertTrue(check['ok'], check)
                    plan = runtime.execute(project_id, 'plan', 'main.svrun')['output']
                    self.assertEqual(plan['unresolvedRequestCount'], 0, plan)
                    runtime.execute(project_id, 'runtime-up')
                    runtime_started = True
                    build = runtime.execute(project_id, 'build', 'main.svrun')['output']['build']['id']
                    deadline = time.monotonic() + 45
                    while time.monotonic() < deadline:
                        status = runtime.execute(project_id, 'status', build_id=build)['output']['build']
                        if status['work']['state'] == 'done':
                            break
                        time.sleep(.15)
                    self.assertEqual(status['work'].get('outcome'), 'complete', status)
                    self.assertEqual(status['result']['outputCount'], 1)

                    task_records = list((root / 'data' / 'hypit_model_tasks' / project_id).glob('*.json'))
                    self.assertEqual(len(task_records), 1)
                    task = read_json(task_records[0])
                    self.assertEqual(task['status'], 'succeeded', task)
                    request_id = task['request_id']
                    public_task = json_http(
                        local_url,
                        f'/api/studio/hypit/models/projects/{project_id}/requests/{request_id}',
                    )
                    self.assertEqual(public_task['request']['selection_kind'], 'settings_canvas')
                    self.assertEqual(public_task['status'], 'succeeded', public_task)
                    self.assertNotIn('legacy-model-must-not-run', json.dumps(public_task))
                    self.assertNotIn('private_snapshot', public_task)

                    runs = storage.list_runs(canvas_id=HYPIT_SETTINGS_CANVAS_ID, node_id='image-output')
                    self.assertEqual(len(runs), 1)
                    run_id = runs[0]['run_id']
                    self.assertEqual(runs[0]['attempts'][-1]['status'], 'succeeded')
                    stored_task = storage.get_canvas_task(run_id)
                    self.assertEqual(stored_task['result']['output_kind'], 'image')
                    self.assertEqual(len(stored_task['result']['media']), 1)
                    result_id = stored_task['result']['media'][0]['resultId']
                    result_path = storage.result_path(result_id)
                    self.assertTrue(result_path and result_path.is_file())
                    self.assertTrue(result_path.is_relative_to(root))
                    self.assertEqual(storage.get_result(result_id)['kind'], 'image')
                    self.assertEqual(len(collection_events), 1)
                    self.assertEqual(collection_events[0]['result_id'], result_id)
                    self.assertEqual([item[0] for item in provider_events].count('submit'), 1)
                    self.assertTrue(any(item[0] == 'preflight' for item in provider_events))
                    self.assertIn(('hypit-settings', run_id, 'succeeded'), runner_notifications)
                    self.assertEqual(len(runner_submissions), 1)
                    request_id, payload, output_id, test_flag = runner_submissions[0]
                    self.assertEqual((output_id, test_flag), ('image-output', False))
                    duplicate = asyncio.run(runner.submit(
                        'image', output_id, request_id, payload, test=test_flag,
                    ))
                    self.assertEqual(duplicate['run_id'], run_id)
                    self.assertEqual([item[0] for item in provider_events].count('submit'), 1,
                                     '相同 native operation 不能再次提交假供应商')
                    saved_generator = next(item for item in canvas['nodes'] if item['id'] == 'image-generator')
                    self.assertEqual(saved_generator['runSettings']['capabilityParameters']['fixture-image-model']['count'], 2)
                    self.assertTrue(projection_events)
                    self.assertTrue(legacy_path.is_file(), '新版图执行不得迁移、删除或改写旧设置文件')
                    self.assertEqual(hashlib.sha256(legacy_path.read_bytes()).hexdigest(), legacy_digest)
            finally:
                if runtime_started:
                    project = root / 'workflows' / 'hypit' / project_id
                    stopped = subprocess.run(
                        runtime.command() + ['runtime', 'down', '--workspace', str(project), '--json'],
                        cwd=project, env=runtime.environment(), capture_output=True, timeout=30,
                    )
                    self.assertEqual(stopped.returncode, 0, stopped.stderr.decode('utf-8', errors='replace'))
                runtime.close()

    def test_native_author_http_endpoint_and_media_result_contract(self):
        self.check_media_contract('Image', 'image', 'png')

    def test_native_music_uses_music_capability_and_collects_audio(self):
        self.check_media_contract('Music', 'audio', 'wav')

    def check_media_contract(self, tag, media_kind, extension):
        distribution = HypitRuntime(ROOT).distribution
        self.assertTrue((distribution / 'bin/hypit.mjs').is_file(), '先准备已审核的 Hypit 运行环境')
        with _native_temp_root('hypit-native-media-') as folder:
            root = Path(folder)
            (root / 'static').mkdir()
            for name in ('hypit-models.mjs', 'hypit-endpoint.mjs'):
                shutil.copyfile(ROOT / 'static' / name, root / 'static' / name)
            project = root / 'workflows/hypit/native-check'
            project.mkdir(parents=True)
            parameters = {'count': 1} if media_kind == 'image' else {'instrumental': True}
            (project / 'main.svml').write_text(f'''<?svml using="@hypit/markup@1"?>
<svml><import as="studio" from="@laohu/studio-models@1"/><import as="text" from="@hypit/text@1"/>
<text:Value id="prompt">Native contract fixture</text:Value>
<studio:{tag} id="generated" prompt={{prompt}} parameters='{json.dumps(parameters)}'/></svml>''')
            (project / 'main.svrun').write_text(f'''<?svml using="@hypit/run-markup@1"?>
<svrun version="1"><author source="./main.svml"/><target output="generated.{media_kind}"/></svrun>''')
            class Runtime(HypitRuntime):
                @property
                def distribution(self):
                    return distribution
                def configure_profile(self, project_id):
                    path = super().configure_profile(project_id)
                    value = read_json(path)
                    value['endpoints'] = {'studio.models': value['endpoints']['studio.models']}
                    write_json(path, value)
                    return path
            calls = []
            png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1cAAAAASUVORK5CYII=')
            wav = io.BytesIO()
            with wave.open(wav, 'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes(b'\0\0' * 800)
            media = png if media_kind == 'image' else wav.getvalue()
            media_path = f'/fixture.{extension}'
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass
                def reply(self, value):
                    self.send_response(200)
                    self.send_header('content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(value).encode())
                def do_POST(self):
                    payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    calls.append((self.path, payload))
                    self.reply({'task_id': 'fixture', 'status': 'queued'})
                def do_GET(self):
                    if self.path == media_path:
                        self.send_response(200)
                        self.send_header('content-type', f'{media_kind}/{extension}')
                        self.end_headers()
                        self.wfile.write(media)
                    else:
                        self.reply({'task_id': 'fixture', 'status': 'succeeded', 'result': {media_kind + 's': [{'url': media_path}]}})
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            runtime = Runtime(root)
            runtime.base_url = f'http://127.0.0.1:{server.server_port}'
            try:
                self.assertTrue(runtime.execute('native-check', 'check', 'main.svrun')['output']['ok'])
                plan = runtime.execute('native-check', 'plan', 'main.svrun')['output']
                self.assertEqual(plan['unresolvedRequestCount'], 0)
                self.assertNotEqual(plan['providers'][0].get('pricing', {}).get('kind'), 'local')
                runtime.execute('native-check', 'runtime-up')
                build = runtime.execute('native-check', 'build', 'main.svrun')['output']['build']['id']
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    status = runtime.execute('native-check', 'status', build_id=build)['output']['build']
                    if status['work']['state'] == 'done':
                        break
                    time.sleep(.25)
                self.assertEqual(status['work'].get('outcome'), 'complete', status)
                self.assertEqual(status['result']['outputCount'], 1)
                self.assertEqual(len(calls), 1)
                path, payload = calls[0]
                self.assertEqual(path, '/api/studio/hypit/models/projects/native-check/requests')
                self.assertLessEqual(len(payload['request_id']), 160)
                self.assertEqual(payload['constraints']['prompt'], 'Native contract fixture')
                self.assertEqual(payload['capability']['name'], tag.lower() + '-generation')
                self.assertEqual(payload['constraints']['kind'], tag.lower())
                self.assertEqual(payload['constraints']['parameters'], parameters)
                self.assertTrue(list((root / 'assets/output/hypit/native-check').rglob('*.' + extension)))
            finally:
                subprocess.run(runtime.command() + ['runtime', 'down', '--workspace', str(project), '--json'],
                               cwd=project, env=runtime.environment(), capture_output=True, timeout=30)
                runtime.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
