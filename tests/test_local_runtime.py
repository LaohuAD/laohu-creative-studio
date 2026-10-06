"""启动与安装使用同一个入口；测试不得结束用户正在运行的服务。"""
import ast
import importlib.util
import json
import tempfile
import threading
import unittest
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class LocalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'local_runtime.py').exists(), '需要统一的跨平台启动入口')
        import local_runtime
        self.runtime = local_runtime
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / '.python-version').write_text('3.14.5\n', encoding='utf-8')

    def test_windows_qualified_venv_wins_over_stale_bundled_runtime(self):
        venv = self.root / '.venv' / 'Scripts' / 'python.exe'
        venv.parent.mkdir(parents=True)
        venv.touch()
        bundled = self.root / 'python' / 'python.exe'
        bundled.parent.mkdir()
        bundled.touch()
        with patch('canvas_update.interpreter_version', side_effect=lambda path: {
            str(venv): '3.14.5', str(bundled): '3.10.11'
        }.get(str(path))):
            self.assertEqual(self.runtime.environment_python(self.root, 'nt'), venv)

    def test_stale_project_interpreter_is_not_selected(self):
        venv = self.root / '.venv' / 'bin' / 'python'
        venv.parent.mkdir(parents=True)
        venv.touch()
        with patch('canvas_update.interpreter_version', return_value='3.10.11'):
            with self.assertRaisesRegex(RuntimeError, '3.14.5'):
                self.runtime.environment_python(self.root, 'posix')

    def test_direct_main_entry_requires_exact_pinned_python_without_affecting_imports(self):
        import types

        tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
        entry = next(
            node for node in tree.body
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == '__name__'
        )
        isolated = ast.Module(body=[entry], type_ignores=[])
        code = compile(ast.fix_missing_locations(isolated), str(ROOT / 'main.py'), 'exec')
        updater = types.ModuleType('canvas_update')
        updater.required_python_version = lambda _root: '3.14.5'
        uvicorn = types.ModuleType('uvicorn')
        uvicorn.run = Mock()
        namespace = {
            '__name__': '__main__',
            'BASE_DIR': self.root,
            'sys': SimpleNamespace(version_info=(3, 10, 11)),
            'local_server_uvicorn_options': Mock(return_value={'app': 'main:app', 'kwargs': {'reload': False}}),
        }
        updater.required_python_version = Mock(side_effect=ValueError('缺少 .python-version'))
        with patch.dict(sys.modules, {'canvas_update': updater, 'uvicorn': uvicorn}):
            with self.assertRaisesRegex(SystemExit, '安装依赖'):
                exec(code, namespace)
        uvicorn.run.assert_not_called()

        updater.required_python_version = lambda _root: '3.14.5'
        with patch.dict(sys.modules, {'canvas_update': updater, 'uvicorn': uvicorn}):
            with self.assertRaisesRegex(SystemExit, '项目要求 3.14.5'):
                exec(code, namespace)
        uvicorn.run.assert_not_called()

        namespace['sys'] = SimpleNamespace(version_info=(3, 14, 5))
        with patch.dict(sys.modules, {'canvas_update': updater, 'uvicorn': uvicorn}):
            exec(code, namespace)
        uvicorn.run.assert_called_once_with('main:app', reload=False)

    def test_mac_uses_project_environment_and_same_disk_cache(self):
        python = self.root / '.venv' / 'bin' / 'python'
        python.parent.mkdir(parents=True)
        python.touch()
        with patch('canvas_update.interpreter_version', return_value='3.14.5'):
            self.assertEqual(self.runtime.environment_python(self.root, 'posix'), python)
        env = self.runtime.runtime_environment(self.root)
        for key in ('TMPDIR', 'TMP', 'TEMP', 'PIP_CACHE_DIR'):
            self.assertTrue(Path(env[key]).is_relative_to(self.root / 'cache'))
            self.assertTrue(Path(env[key]).is_dir())

    def test_probe_recognizes_own_service_and_rejects_other_http_server(self):
        class Handler(BaseHTTPRequestHandler):
            repo = 'https://github.com/LaohuAD/laohu-creative-studio'
            def log_message(self, *args):
                pass
            def do_GET(self):
                body = json.dumps({'repo_url': self.repo, 'version': 'fixture'}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/'
            self.assertTrue(self.runtime.canvas_ready(url))
            Handler.repo = 'another-program'
            self.assertFalse(self.runtime.canvas_ready(url))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_canvas_ready_returns_false_when_opener_cannot_connect(self):
        with patch('urllib.request.build_opener') as build_opener:
            build_opener.return_value.open.side_effect = OSError('connection refused')
            self.assertFalse(self.runtime.canvas_ready('http://127.0.0.1:3000/'))
        build_opener.return_value.open.assert_called_once()

    def test_running_canvas_is_reused_without_spawning_or_stopping_any_process(self):
        with patch.object(self.runtime, 'canvas_ready', return_value=True), patch.object(self.runtime.subprocess, 'Popen') as spawn:
            self.assertEqual(self.runtime.launch(self.root, open_browser=False), 0)
        spawn.assert_not_called()

    def test_other_occupied_port_fails_without_spawning_or_stopping(self):
        with patch.object(self.runtime, 'canvas_ready', return_value=False), patch.object(self.runtime, 'port_open', return_value=True), patch.object(self.runtime.subprocess, 'Popen') as spawn:
            self.assertEqual(self.runtime.launch(self.root, open_browser=False), 1)
        spawn.assert_not_called()

    def test_browser_waits_for_readiness_and_start_failure_is_returned(self):
        child = Mock()
        child.poll.return_value = 7
        with patch.object(self.runtime, 'canvas_ready', return_value=False), patch.object(self.runtime, 'port_open', return_value=False), patch.object(self.runtime, 'environment_python', return_value=Path(sys.executable)), patch.object(self.runtime.subprocess, 'Popen', return_value=child), patch.object(self.runtime.webbrowser, 'open') as browser:
            self.assertEqual(self.runtime.launch(self.root), 7)
        browser.assert_not_called()

    def test_failed_dependency_install_propagates_status(self):
        python = self.root / '.venv' / ('Scripts/python.exe' if self.runtime.os.name == 'nt' else 'bin/python')
        python.parent.mkdir(parents=True)
        python.touch()
        with patch('canvas_update.interpreter_version', side_effect=lambda value: '3.14.5' if Path(value)==python else '3.14.5'), \
             patch.object(self.runtime.subprocess, 'call', side_effect=[0, 1, 9]) as call:
            self.assertEqual(self.runtime.install(self.root), 9)
        self.assertTrue(all(str(python) == args.args[0][0] for args in call.call_args_list))

    def test_install_migrates_old_venv_side_by_side_and_switches_only_after_checks(self):
        import canvas_update
        old_python = canvas_update.venv_python(self.root / '.venv', self.runtime.os.name)
        old_python.parent.mkdir(parents=True)
        old_python.write_text('old environment')
        old_env = canvas_update.venv_python(self.root / 'cache' / 'update-environments' / 'old', self.runtime.os.name)
        old_env.parent.mkdir(parents=True)
        old_env.write_text('old active environment')
        pointer = self.root / 'cache' / 'runtime' / 'active-environment.json'
        canvas_update.write_state(pointer, {'python': str(old_env)})

        created = []
        def call(args, **_kwargs):
            if args[1:3] == ['-m', 'venv']:
                env_python = canvas_update.venv_python(args[-1], self.runtime.os.name)
                env_python.parent.mkdir(parents=True)
                env_python.touch()
                created.append(env_python)
                return 0
            if args[-2:] == ['install', '-r']:
                return 0
            if args[-2:] == ['pip', 'check']:
                return 1 if len(created) == 1 else 0
            return 0

        def version(path):
            return '3.14.5' if Path(path) in created or Path(path) == Path(sys.executable) else '3.10.11'
        with patch.object(canvas_update, 'bootstrap_python', return_value=sys.executable), \
             patch.object(canvas_update, 'interpreter_version', side_effect=version), \
             patch.object(self.runtime.subprocess, 'call', side_effect=call):
            self.assertEqual(self.runtime.install(self.root), 1)
            self.assertEqual(json.loads(pointer.read_text())['python'], str(old_env))
            self.assertEqual(self.runtime.install(self.root), 0)

        new_python = Path(json.loads(pointer.read_text())['python'])
        self.assertTrue(new_python.is_relative_to(self.root / 'cache' / 'update-environments'))
        self.assertEqual(version(new_python), '3.14.5')
        self.assertEqual(old_python.read_text(), 'old environment')
        self.assertEqual(old_env.read_text(), 'old active environment')

    def test_restart_is_only_requested_through_this_launchers_private_channel(self):
        self.assertTrue(hasattr(self.runtime, 'request_restart'))
        with patch.dict(self.runtime.os.environ, {}, clear=True):
            self.assertFalse(self.runtime.request_restart(self.root, 3))
        folder = self.root / 'cache' / 'runtime' / 'restarts'
        folder.mkdir(parents=True)
        request = folder / 'session.json'
        with patch.dict(self.runtime.os.environ, {'INFINITE_CANVAS_RESTART_FILE': str(request)}):
            self.assertTrue(self.runtime.request_restart(self.root, 3))
        self.assertIn('restart_at', json.loads(request.read_text()))
        outside = self.root / 'not-a-restart.json'
        with patch.dict(self.runtime.os.environ, {'INFINITE_CANVAS_RESTART_FILE': str(outside)}):
            self.assertFalse(self.runtime.request_restart(self.root, 3))
        self.assertFalse(outside.exists())

    def test_real_child_readiness_and_restart_round_trip(self):
        # 使用随机端口的临时服务验证完整生命周期，不触碰用户的 3000 端口。
        (self.root / 'main.py').write_text('''import json, os, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
root = Path(__file__).parent
counter = root / 'count.txt'
count = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(count))
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({'repo_url': 'https://github.com/LaohuAD/laohu-creative-studio', 'version': 'fixture'}).encode())
        if count == 2 and not getattr(self.server, 'stopping', False):
            self.server.stopping = True
            threading.Timer(1.2, self.server.shutdown).start()
server = HTTPServer(('127.0.0.1', 0), Handler)
(root / 'url.txt').write_text('http://127.0.0.1:' + str(server.server_port) + '/')
if count == 1:
    Path(os.environ['INFINITE_CANVAS_RESTART_FILE']).write_text(json.dumps({'restart_at': time.time() + 1}))
try:
    server.serve_forever(poll_interval=0.05)
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
''', encoding='utf-8')
        probe = self.runtime.canvas_ready
        def ready():
            path = self.root / 'url.txt'
            return path.exists() and probe(path.read_text())
        with patch.object(self.runtime, 'canvas_ready', side_effect=ready), patch.object(self.runtime, 'port_open', return_value=False), patch.object(self.runtime, 'environment_python', return_value=Path(sys.executable)), patch.object(self.runtime.webbrowser, 'open') as browser:
            self.assertEqual(self.runtime.launch(self.root), 0)
        self.assertEqual((self.root / 'count.txt').read_text(), '2')
        browser.assert_called_once()
        self.assertEqual(list((self.root / 'cache/runtime/restarts').glob('*.json')), [])

    def test_real_upgrade_start_failure_restores_old_service(self):
        import canvas_update
        from test_canvas_update import package
        job=canvas_update.stage_release(self.root,*package({'main.py':b'raise RuntimeError("startup failed")'}))
        canvas_update.write_state(job/'prepared.json',{'python':__import__('sys').executable,'python_version':'3.14.5','new_environment':False})
        (self.root/'VERSION').write_text('1.0')
        (self.root/'main.py').write_text('''import json, os, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
root=Path(__file__).parent
counter=root/'count.txt'
count=int(counter.read_text())+1 if counter.exists() else 1
counter.write_text(str(count))
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(json.dumps({'repo_url':'https://github.com/LaohuAD/laohu-creative-studio','version':'1.0'}).encode())
        if count == 2 and not getattr(self.server, 'stopping', False):
            self.server.stopping = True
            threading.Timer(1.2, self.server.shutdown).start()
server=HTTPServer(('127.0.0.1',0),Handler)
(root/'url.txt').write_text('http://127.0.0.1:'+str(server.server_port)+'/')
if count==1:
    job=next((root/'cache/update-jobs').iterdir())
    Path(os.environ['INFINITE_CANVAS_RESTART_FILE']).write_text(json.dumps({'restart_at':time.time()+1,'update_job':str(job)}))
try: server.serve_forever(poll_interval=.05)
except KeyboardInterrupt: pass
finally: server.server_close()
''',encoding='utf-8')
        probe=self.runtime.canvas_ready
        def ready(expected_version=''):
            url=self.root/'url.txt'
            return url.exists() and probe(url.read_text(),expected_version=expected_version)
        with patch.object(self.runtime,'canvas_ready',side_effect=ready),patch.object(self.runtime,'port_open',return_value=False),patch.object(self.runtime,'environment_python',return_value=Path(sys.executable)):
            self.assertEqual(self.runtime.launch(self.root,open_browser=False),0)
        self.assertEqual((self.root/'VERSION').read_text(),'1.0')
        self.assertEqual((self.root/'count.txt').read_text(),'2')
        self.assertEqual(json.loads((self.root/'cache/runtime/last-update.json').read_text())['status'],'rolled_back')


class MediaToolResolutionTests(unittest.TestCase):
    def test_broken_binary_is_rejected_even_when_installed(self):
        from local_runtime import _media_binary_works
        _media_binary_works.cache_clear()
        with patch('local_runtime.subprocess.run', return_value=SimpleNamespace(returncode=-6)):
            self.assertFalse(_media_binary_works('/installed/ffmpeg', 1, 1))

    def test_resolution_skips_broken_path_and_uses_valid_candidate(self):
        from local_runtime import resolve_media_tool
        import local_runtime
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            broken = root / 'broken-ffmpeg'
            broken.touch()
            valid = root / 'bin' / ('ffmpeg.exe' if local_runtime.os.name == 'nt' else 'ffmpeg')
            valid.parent.mkdir()
            valid.touch()
            # 使用真实文件属性，避免模拟 stat 破坏 Python 3.10 的 glob/is_dir。
            with patch('local_runtime.ROOT', root), \
                 patch.dict(local_runtime.os.environ, {'LAOHU_FFMPEG_PATH': ''}), \
                 patch('local_runtime.shutil.which', return_value=str(broken)), \
                 patch('local_runtime.Path.glob', return_value=[]), \
                 patch('local_runtime._media_binary_works', side_effect=lambda path, *_: path == str(valid)):
                self.assertEqual(resolve_media_tool('ffmpeg'), str(valid))
