import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hypit_runtime import HypitRuntime
from project_storage import ProjectStorage, StorageError
from studio_hypit import create_hypit_router


class HypitTests(unittest.TestCase):
    def setUp(self):
        cache = Path(__file__).resolve().parents[1] / 'cache' / 'hypit-tests'
        cache.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'workflows/hypit/project').mkdir(parents=True)
        self.runtime = HypitRuntime(self.root)

    def test_project_paths_results_config_and_original_files(self):
        self.runtime.configure('project')
        config = json.loads((self.root / 'workflows/hypit/project/hypit.results.json').read_text())
        self.assertEqual(config['config']['path'], str(self.root / 'assets/output/hypit/project'))
        for bad in ('../outside.svml', '/outside.svml', 'C:\\outside.svml'):
            with self.assertRaises(ValueError):
                self.runtime.source('project', bad)
        target = self.root / 'workflows/hypit/project/hypit.results.json'
        target.write_text('{"old":true}')
        with self.assertRaises(RuntimeError):
            self.runtime.configure('project')
        self.assertEqual(target.read_text(), '{"old":true}')

    def test_native_theme_patch_is_idempotent_and_backed_up(self):
        distribution = self.runtime.distribution
        style = distribution / 'packages/studio/src/style.css'
        index = distribution / 'packages/studio/index.html'
        style.parent.mkdir(parents=True)
        index.parent.mkdir(parents=True, exist_ok=True)
        style.write_text(':root { --brand-500: #e3406a; }\n', encoding='utf-8')
        index.write_text('<!doctype html><html><head></head><body><div id="app"></div></body></html>\n', encoding='utf-8')
        theme = self.root / 'static/css/hypit-native-theme.css'
        theme.parent.mkdir(parents=True)
        theme.write_text(':root { --brand-500: #b48a5a; }', encoding='utf-8')

        first = self.runtime._ensure_native_theme()
        style_after_first = style.read_text(encoding='utf-8')
        index_after_first = index.read_text(encoding='utf-8')
        second = self.runtime._ensure_native_theme()

        self.assertEqual(first, second)
        self.assertEqual(style.read_text(encoding='utf-8'), style_after_first)
        self.assertEqual(index.read_text(encoding='utf-8'), index_after_first)
        self.assertEqual(style_after_first.count('laohu-native-theme:start'), 1)
        self.assertEqual(index_after_first.count('laohu-native-theme:start'), 1)
        self.assertIn('dataset.laohuTheme', index_after_first)
        self.assertIn('event.source !== window.parent', index_after_first)
        backup = self.root / 'backups/hypit/native-studio/0.2.7'
        self.assertTrue((backup / 'style.css').is_file())
        self.assertTrue((backup / 'index.html').is_file())
        self.assertFalse(style.is_symlink())
        self.assertFalse(index.is_symlink())

    def test_managed_result_index_keeps_native_path_and_deduplicates(self):
        store = ProjectStorage(self.root)
        native = self.root / 'assets/output/hypit/project/date/build/movie.mp4'
        native.parent.mkdir(parents=True)
        native.write_bytes(b'fixture-video')
        a = store.register_managed_result(native, source_module='hypit')
        b = store.register_managed_result(native)
        self.assertEqual(a['id'], b['id'])
        self.assertEqual(store.result_path(a['id']).resolve(), native.resolve())
        self.assertEqual(len(list((self.root/'assets/output').rglob('*.mp4'))), 1)
        external = self.root / 'outside.mp4'
        external.write_bytes(b'outside')
        with self.assertRaises(StorageError):
            store.register_managed_result(external)

    def test_interrupted_operation_becomes_recoverable_without_resubmission(self):
        import hashlib
        from canvas_core.json_store import write_json
        request_id = 'interrupted-build'
        record = self.root / 'data/hypit_operations/project' / (hashlib.sha256(request_id.encode()).hexdigest()+'.json')
        write_json(record, {'request_id': request_id, 'status': 'running', 'operation': 'build'})
        app = FastAPI()
        app.include_router(create_hypit_router(self.root, lambda *_: {'id': 'project'}, self.runtime))
        with TestClient(app) as client:
            value = client.get('/api/studio/hypit/projects/project/operations/'+request_id)
            self.assertEqual(value.status_code, 200)
            self.assertEqual(value.json()['status'], 'recoverable')
        self.assertEqual(json.loads(record.read_text())['status'], 'recoverable')

    def test_files_conflict_and_operations_survive_http_response(self):
        gate = threading.Event()
        calls = []
        def execute(*args):
            calls.append(args)
            gate.wait(3)
            return {'output': 'checked'}
        self.runtime.execute = execute
        app = FastAPI()
        app.include_router(create_hypit_router(self.root, lambda *_: {'id': 'project'}, self.runtime))
        with TestClient(app) as client:
            url = '/api/studio/hypit/projects/project'
            saved = client.put(url+'/files', json={'path': 'main.svml', 'content': 'source', 'expected_sha256': ''})
            self.assertEqual(saved.status_code, 200)
            conflict = client.put(url+'/files', json={'path': 'main.svml', 'content': 'lost', 'expected_sha256': ''})
            self.assertEqual(conflict.status_code, 409)
            payload = {'request_id': 'check-one', 'operation': 'check', 'source': 'main.svml'}
            first = client.post(url+'/operations', json=payload)
            self.assertEqual(first.json()['status'], 'running')
            self.assertEqual(client.post(url+'/operations', json=payload).status_code, 200)
            self.assertEqual(client.post(url+'/operations', json={**payload, 'operation': 'build'}).status_code, 409)
            gate.set()
            deadline = time.monotonic()+3
            while time.monotonic() < deadline:
                state = client.get(url+'/operations/check-one').json()
                if state['status'] != 'running':
                    break
                time.sleep(.01)
            self.assertEqual(state['status'], 'succeeded')
            self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
