import unittest
import importlib.util
import io
import hashlib
import zipfile
import ast
from pathlib import Path
from tools.publish_r2 import allowed


class ReleaseScopeTests(unittest.TestCase):
    def test_bootstrap_does_not_require_new_root_module_symbol(self):
        tree = ast.parse(Path('main.py').read_text())
        imports = [alias.name for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == 'model_capabilities' for alias in node.names]
        self.assertNotIn('normalize_laohu_model_id', imports)
    def test_runtime_package_validator_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('static.release_update'))
    def test_includes_program_and_capabilities(self):
        for path in ['main.py', 'model_capabilities.py', 'project_storage.py', 'studio_modules.py', 'requirements.txt', '.python-version', 'static/js/smart-canvas.js', 'data/model_capabilities/providers/ai-money.json', 'run.bat', 'mac-启动服务.sh']:
            self.assertTrue(allowed(path), path)

    def test_excludes_private_and_historical_files(self):
        for path in ['API/.env', 'data/api_providers.json', 'assets/output/image/a.png', '.git/config', '../main.py', '/main.py', 'static/js/smart-canvas.js.mojibake-backup', 'python/python.exe', 'python/Lib/venv/__init__.py', 'python/LICENSE.txt']:
            self.assertFalse(allowed(path), path)


class PackageValidationTests(unittest.TestCase):
    def test_backend_recognizes_r2_source(self):
        tree = ast.parse(Path('main.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'normalize_update_source')
        scope = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), scope)
        self.assertEqual(scope['normalize_update_source']('r2'), 'r2')

    def test_release_download_is_pinned_to_our_domain(self):
        from static.release_update import package_url
        self.assertEqual(package_url({'version': '2026.09.10'}), 'https://infinitecanvas.lao-hu.com/canvas-releases/2026.09.10/update.zip')
        with self.assertRaises(ValueError):
            package_url({'version': '../evil'})

    def test_package_integrity_and_private_paths(self):
        from static.release_update import validate_package
        files = {'VERSION': b'2026.09.10', '.python-version': b'3.14.5\n', 'main.py': b'pass\n',
                 'requirements.txt': b'', 'model_capabilities.py': b'pass\n',
                 'project_storage.py': b'pass\n', 'studio_modules.py': b'pass\n', 'static/release_update.py': b'pass\n',
                 'static/update-notes.json': b'{"version":"2026.09.10"}'}
        def package(items):
            out = io.BytesIO()
            with zipfile.ZipFile(out, 'w') as z:
                for name, data in items.items():
                    z.writestr(name, data)
            body = out.getvalue()
            return body, {'schema_version': 1, 'version': '2026.09.10',
                'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
                'files': [{'path': n, 'bytes': len(d), 'sha256': hashlib.sha256(d).hexdigest()} for n,d in items.items()]}
        body, manifest = package(files)
        self.assertEqual(validate_package(body, manifest), files)
        with self.assertRaises(ValueError):
            validate_package(body + b'x', manifest)
        for name in ('API/.env', '../main.py', '/main.py', 'C:/main.py', 'static/../API/.env', 'static\\x.js'):
            bad, meta = package({**files, name: b'secret'})
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_package(bad, meta)
        manifest['files'][0]['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            validate_package(body, manifest)
        bad, meta = package({**files, 'static/Example.js': b'a', 'static/example.js': b'b'})
        with self.assertRaises(ValueError):
            validate_package(bad, meta)
