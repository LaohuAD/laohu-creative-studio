"""升级事务验收：隔离目录、真实启动探测和失败恢复，不更新当前工作区。"""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import zipfile

import canvas_update as updater


def package(extra=None):
    files = {'VERSION':b'2.0', 'requirements.txt':b'fastapi\n', 'main.py':b'pass\n',
             'project_storage.py':b'pass\n','model_capabilities.py':b'pass\n',
             'static/release_update.py':b'pass\n','static/update-notes.json':b'{"version":"2.0"}',
             'canvas_core/new_module.py':b'VALUE=2\n'}
    files.update(extra or {})
    archive = io.BytesIO()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for n,d in files.items(): z.writestr(n,d)
    body=archive.getvalue()
    manifest={'schema_version':1,'version':'2.0','bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),
              'files':[{'path':n,'bytes':len(d),'sha256':hashlib.sha256(d).hexdigest()} for n,d in files.items()]}
    return manifest,body


class UpgradeTests(unittest.TestCase):
    def test_download_identifies_application_and_enforces_size_limit(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.send_response(200 if self.headers.get('User-Agent') == 'LaohuInfiniteCanvas-Updater/1.0' else 403)
                self.end_headers()
                self.wfile.write(b'fixture')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/'
            self.assertEqual(updater.fetch_bytes(url, 7), b'fixture')
            with self.assertRaises(ValueError):
                updater.fetch_bytes(url, 6)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name,data in {'main.py':'OLD','VERSION':'1.0','requirements.txt':'fastapi\n',
                          'static/obsolete.js':'OLD','data/canvas.json':'{"old":true}',
                          'assets/output/keep.png':'MEDIA','API/.env':'KEY'}.items():
            dest=self.root/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(data)

    def job(self, extra=None):
        job=updater.stage_release(self.root,*package(extra))
        updater.write_state(job/'prepared.json',{'python':sys.executable,'new_environment':False})
        return job

    def test_full_apply_and_recovery_preserve_original_data_media_and_keys(self):
        job=self.job();updater.apply_job(self.root,job)
        self.assertEqual((self.root/'VERSION').read_text(),'2.0')
        self.assertFalse((self.root/'static/obsolete.js').exists())
        self.assertTrue((self.root/'canvas_core/new_module.py').exists())
        (self.root/'data/canvas.json').write_text('changed')
        (self.root/'data/new-index.json').write_text('{}')
        self.assertTrue(updater.recover(self.root))
        self.assertEqual((self.root/'main.py').read_text(),'OLD')
        self.assertTrue((self.root/'static/obsolete.js').exists())
        self.assertFalse((self.root/'canvas_core/new_module.py').exists())
        self.assertFalse((self.root/'data/new-index.json').exists())
        self.assertEqual((self.root/'data/canvas.json').read_text(),'{"old":true}')
        self.assertEqual((self.root/'assets/output/keep.png').read_text(),'MEDIA')
        self.assertEqual((self.root/'API/.env').read_text(),'KEY')
        self.assertFalse(updater.recover(self.root))

    def test_reject_changed_staged_code_before_touching_original(self):
        job=self.job();(job/'program/main.py').write_text('changed')
        with self.assertRaises(ValueError): updater.apply_job(self.root,job)
        self.assertEqual((self.root/'main.py').read_text(),'OLD')

    def test_partial_file_replacement_failure_rolls_back(self):
        job=self.job();original=os.replace
        def replace(source,target):
            if str(source).endswith('.upgrade-tmp') and Path(target).name=='main.py':
                raise OSError('disk full')
            return original(source,target)
        with patch.object(updater.os,'replace',side_effect=replace),self.assertRaises(OSError):
            updater.apply_job(self.root,job)
        self.assertEqual((self.root/'VERSION').read_text(),'1.0')
        self.assertEqual((self.root/'main.py').read_text(),'OLD')
        self.assertFalse((self.root/'canvas_core/new_module.py').exists())

    def test_failed_dependency_install_never_changes_live_environment(self):
        job=self.job({'requirements.txt':b'new-dependency==1\n'})
        calls=[]
        def run(command,*args):
            calls.append(command)
            if 'install' in command: raise RuntimeError('offline')
        with patch.object(updater,'run_checked',side_effect=run),self.assertRaises(RuntimeError):
            updater.prepare_job(self.root,job)
        self.assertIn('venv',calls[0])
        self.assertIn(str(self.root/'cache/update-environments'),calls[1][0])
        self.assertFalse((self.root/'cache/runtime/active-environment.json').exists())
        self.assertEqual((self.root/'VERSION').read_text(),'1.0')

    def test_equivalent_requirements_do_not_reinstall(self):
        job=self.job({'requirements.txt':b'# explanation\nfastapi\n\n'})
        with patch.object(updater,'run_checked') as run,patch.object(updater,'probe_program'):
            updater.prepare_job(self.root,job)
        self.assertEqual(run.call_count,1)
        self.assertEqual(run.call_args.args[0][-2:],['pip','check'])

    def test_pointer_supports_normal_venv_python_symlink(self):
        dest=self.root/'cache/update-environments/example/bin/python'
        dest.parent.mkdir(parents=True)
        try: dest.symlink_to(sys.executable)
        except OSError: self.skipTest('本机不允许符号链接')
        updater.write_state(self.root/'cache/runtime/active-environment.json',{'python':str(dest)})
        self.assertEqual(updater.runtime_python(self.root),str(dest))

    def test_success_is_only_marked_after_finish(self):
        job=self.job();updater.apply_job(self.root,job)
        self.assertFalse((self.root/'cache/runtime/last-update.json').exists())
        updater.finish(self.root)
        state=json.loads((self.root/'cache/runtime/last-update.json').read_text())
        self.assertEqual(state['status'],'succeeded')
        self.assertFalse(updater.recover(self.root))

    def test_real_http_probe_checks_version_and_leaves_user_data_alone(self):
        source=b'''from fastapi import FastAPI
app=FastAPI()
@app.get('/api/app-info')
def info(): return {'version':'2.0','repo_url':'https://github.com/LaohuAD/laohu-creative-studio'}
'''
        job=self.job({'main.py':source})
        updater.probe_program(job/'program',sys.executable,job/'probe.log')
        self.assertEqual((self.root/'data/canvas.json').read_text(),'{"old":true}')
        (job/'program/main.py').write_text('raise RuntimeError("broken startup")')
        with self.assertRaises(RuntimeError): updater.probe_program(job/'program',sys.executable,job/'failure.log')

    def test_same_or_older_version_cannot_overwrite_current(self):
        (self.root/'VERSION').write_text('2.0')
        with self.assertRaises(ValueError):updater.stage_release(self.root,*package())
        (self.root/'VERSION').write_text('3.0')
        with self.assertRaises(ValueError):updater.stage_release(self.root,*package())

    def test_invalid_job_path_rejected(self):
        with self.assertRaises(ValueError):updater.apply_job(self.root,self.root.parent)

    def test_interrupted_new_environment_is_restored(self):
        job=self.job();env=self.root/'cache/update-environments/new/bin/python';env.parent.mkdir(parents=True);env.touch()
        updater.write_state(job/'prepared.json',{'python':str(env),'new_environment':True})
        updater.apply_job(self.root,job)
        self.assertEqual(updater.runtime_python(self.root),str(env))
        updater.recover(self.root)
        self.assertFalse((self.root/'cache/runtime/active-environment.json').exists())
