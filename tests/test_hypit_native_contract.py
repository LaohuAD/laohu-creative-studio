"""原生 Hypit 契约回归：仅显式启用，在本地假供应商完成一次生成，不调用付费 API。"""
import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from canvas_core.json_store import read_json, write_json
from hypit_runtime import HypitRuntime

ROOT = Path(__file__).resolve().parents[1]


class NativeThemeAssetTests(unittest.TestCase):
    def test_native_theme_asset_covers_light_dark_and_internal_surfaces(self):
        theme = (ROOT / 'static/css/hypit-native-theme.css').read_text(encoding='utf-8')
        self.assertIn(':root[data-laohu-theme="dark"]', theme)
        self.assertIn('--app: #f7f3eb', theme)
        self.assertIn('--interaction-accent: #7891a4', theme)
        self.assertIn('.topbar', theme)
        self.assertIn('.timeline-panel', theme)
        self.assertIn('.parameter-select-menu', theme)
        self.assertIn('@media (prefers-reduced-motion: reduce)', theme)


@unittest.skipUnless(os.environ.get('STUDIO_NATIVE_HYPIT_TESTS') == '1', '原生 Hypit 验收需要显式启用')
class NativeHypitContractTests(unittest.TestCase):
    def test_native_author_http_endpoint_and_media_result_contract(self):
        self.check_media_contract('Image', 'image', 'png')

    def test_native_music_uses_music_capability_and_collects_audio(self):
        self.check_media_contract('Music', 'audio', 'wav')

    def check_media_contract(self, tag, media_kind, extension):
        distribution = HypitRuntime(ROOT).distribution
        self.assertTrue((distribution / 'bin/hypit.mjs').is_file(), '先准备已审核的 Hypit 运行环境')
        cache = ROOT / 'cache/hypit-tests'
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as folder:
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
