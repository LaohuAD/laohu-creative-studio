"""R2 发布包校验。只接收程序文件，不接收用户数据。"""
import hashlib
import io
import json
from pathlib import PurePosixPath
import re
import stat
import zipfile


PUBLIC_ROOT = 'https://infinitecanvas.lao-hu.com'
LATEST_URL = PUBLIC_ROOT + '/canvas-releases/latest.json'
MAX_PACKAGE_BYTES = 100 * 1024 * 1024
MAX_EXPANDED_BYTES = 500 * 1024 * 1024


def package_url(manifest):
    version = manifest.get('version', '')
    if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9._-]{0,79}', version):
        raise ValueError('更新版本号无效')
    return PUBLIC_ROOT + '/canvas-releases/' + version + '/update.zip'


def allowed_file(path):
    if not isinstance(path, str) or '\\' in path or ':' in path:
        return False
    parts = path.split('/')
    if any(p in {'', '.', '..'} for p in parts):
        return False
    if any(token in path.lower() for token in ('backup', 'broken-before', 'stable-before', '__pycache__')):
        return False
    if path.startswith('canvas_core/'):
        return PurePosixPath(path).suffix == '.py'
    if path.startswith(('static/', 'data/model_capabilities/')):
        return True
    return len(parts) == 1 and (PurePosixPath(path).suffix in {'.py', '.sh', '.bat', '.command'} or path in {'VERSION', 'requirements.txt'}) and path != 'get-pip.py'


def validate_package(body, manifest):
    """全部校验成功才返回文件；调用方不得边解包边覆盖正在运行的程序。"""
    if manifest.get('schema_version') != 1:
        raise ValueError('不支持的更新包格式')
    version = manifest.get('version', '')
    if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', version):
        raise ValueError('更新版本号无效')
    if len(body) > MAX_PACKAGE_BYTES or len(body) != manifest.get('bytes') or hashlib.sha256(body).hexdigest() != manifest.get('sha256'):
        raise ValueError('更新包大小或 SHA-256 校验失败')
    records = manifest.get('files')
    if not isinstance(records, list) or not records or len(records) > 20000:
        raise ValueError('更新文件清单无效')
    expected = {}
    folded = set()
    for record in records:
        name = record.get('path')
        if not allowed_file(name) or name.casefold() in folded:
            raise ValueError(f'不允许或重复的更新路径：{name}')
        folded.add(name.casefold())
        expected[name] = record
    required = {'VERSION', 'main.py', 'requirements.txt', 'model_capabilities.py', 'project_storage.py', 'static/release_update.py', 'static/update-notes.json'}
    if not required.issubset(expected):
        raise ValueError('更新包缺少必要程序文件')
    result = {}
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        infos = archive.infolist()
        if len(infos) != len(expected) or sum(i.file_size for i in infos) > MAX_EXPANDED_BYTES:
            raise ValueError('更新包文件数量或解压大小异常')
        for info in infos:
            name = info.filename
            if name not in expected or name in result or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('更新包含额外文件、重复文件或符号链接')
            data = archive.read(info)
            record = expected[name]
            if len(data) != record.get('bytes') or hashlib.sha256(data).hexdigest() != record.get('sha256'):
                raise ValueError(f'文件校验失败：{name}')
            if name.endswith('.py'):
                compile(data, name, 'exec')
            result[name] = data
    if result['VERSION'].decode('utf-8').strip() != version or json.loads(result['static/update-notes.json']).get('version') != version:
        raise ValueError('更新包版本与清单不一致')
    return result


# 单文件升级入口可放入旧安装目录直接运行，不依赖旧版本更新器。
import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
import urllib.request
from pathlib import Path


def write_state(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)


def runtime_python(root):
    root = Path(root).resolve()
    pointer = root / 'cache/runtime/active-environment.json'
    if pointer.exists():
        env = Path(json.loads(pointer.read_text(encoding='utf-8'))['python']).absolute()
        if not env.parent.resolve().is_relative_to(root / 'cache/update-environments') or not env.is_file():
            raise ValueError('升级运行环境无效，请运行 canvas_update.py --recover 或恢复安装')
        return str(env)
    choices = [root / 'python/python.exe'] if os.name == 'nt' else []
    choices += [root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')]
    return str(next((p for p in choices if p.is_file()), Path(sys.executable)))


def environment(root):
    env = dict(os.environ)
    for key, folder in [('TMPDIR','tmp'),('TMP','tmp'),('TEMP','tmp'),('PIP_CACHE_DIR','pip')]:
        dest = Path(root) / 'cache/runtime' / folder
        dest.mkdir(parents=True, exist_ok=True)
        env[key] = str(dest)
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', INFINITE_CANVAS_AUTO_RELOAD='0')
    return env


def requirements_key(path):
    return '\n'.join(line.strip() for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line.strip() and not line.lstrip().startswith('#'))


def run_checked(command, root, log, timeout=900):
    with Path(log).open('ab') as output:
        result = subprocess.run(command, cwd=root, env=environment(root), stdout=output, stderr=output, timeout=timeout)
    if result.returncode:
        raise RuntimeError('升级检查失败，当前版本未切换。详细日志：' + str(log))


def fetch_bytes(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'LaohuInfiniteCanvas-Updater/1.0'})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('升级下载超过大小限制')
    return data


def github_release():
    """固定同一个提交和 Git blob 校验，避免下载过程中主分支变化。"""
    from concurrent.futures import ThreadPoolExecutor
    commit = json.loads(fetch_bytes('https://api.github.com/repos/LaohuAD/laohu-creative-studio/commits/main', 4 * 1024 * 1024))['sha']
    tree = json.loads(fetch_bytes(f'https://api.github.com/repos/LaohuAD/laohu-creative-studio/git/trees/{commit}?recursive=1', 8 * 1024 * 1024))
    if tree.get('truncated'):
        raise ValueError('GitHub 文件目录不完整')
    entries = [e for e in tree['tree'] if e['type']=='blob' and allowed_file(e['path'])]
    if sum(e.get('size',0) for e in entries) > MAX_EXPANDED_BYTES:
        raise ValueError('GitHub 程序超过大小限制')
    def read(entry):
        import urllib.parse
        data = fetch_bytes(f'https://raw.githubusercontent.com/LaohuAD/laohu-creative-studio/{commit}/' + urllib.parse.quote(entry['path']), MAX_PACKAGE_BYTES)
        if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != entry['sha']:
            raise ValueError('GitHub 文件校验失败：' + entry['path'])
        return entry['path'], data
    with ThreadPoolExecutor(max_workers=4) as pool:
        files = dict(pool.map(read, entries))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    body = archive.getvalue()
    manifest = {'schema_version':1,'version':files['VERSION'].decode().strip(),'commit':commit,
                'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body),
                'files':[{'path':n,'bytes':len(d),'sha256':hashlib.sha256(d).hexdigest()} for n,d in files.items()],
                'update_notes':json.loads(files['static/update-notes.json'])}
    return manifest, body


def stage_release(root, manifest=None, body=None):
    root = Path(root).resolve()
    if manifest is None:
        manifest = json.loads(fetch_bytes(LATEST_URL, 4 * 1024 * 1024))
    if body is None:
        body = fetch_bytes(package_url(manifest), MAX_PACKAGE_BYTES)
    files = validate_package(body, manifest)
    current = root / 'VERSION'
    if current.exists():
        parts = lambda v: tuple(int(x) for x in re.findall(r'\d+', v))
        if parts(manifest['version']) <= parts(current.read_text(encoding='utf-8').strip()):
            raise ValueError('目标版本不高于当前版本，未进行覆盖或降级')
    job = root / 'cache/update-jobs' / uuid.uuid4().hex
    stage = job / 'program'
    stage.mkdir(parents=True)
    for name, content in files.items():
        target = stage.joinpath(*name.split('/'))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    write_state(job / 'release.json', manifest)
    return job


def probe_program(stage, python, log):
    # 在独立程序目录启动实际 HTTP 服务；不读取用户作品、密钥或素材。
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    expected = (Path(stage) / 'VERSION').read_text(encoding='utf-8').strip()
    with Path(log).open('ab') as output:
        process = subprocess.Popen([python, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', str(port)], cwd=stage, env=environment(stage), stdout=output, stderr=output)
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline = time.monotonic() + 60
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    with opener.open(f'http://127.0.0.1:{port}/api/app-info', timeout=1) as response:
                        info = json.load(response)
                    if info.get('version') == expected and info.get('repo_url') == 'https://github.com/LaohuAD/laohu-creative-studio':
                        return
                except (OSError, ValueError):
                    pass
                time.sleep(.2)
            raise RuntimeError('新版启动验证失败，当前版本未切换。日志：' + str(log))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def prepare_job(root, job):
    root, job = Path(root).resolve(), Path(job).resolve()
    if not job.is_relative_to(root / 'cache/update-jobs'):
        raise ValueError('升级任务目录无效')
    stage = job / 'program'
    manifest = json.loads((job / 'release.json').read_text(encoding='utf-8'))
    log = job / 'prepare.log'
    python = runtime_python(root)
    changed = not (root / 'requirements.txt').exists() or requirements_key(root / 'requirements.txt') != requirements_key(stage / 'requirements.txt')
    if changed:
        # 不对正在使用的 Python 环境执行 pip；失败不会破坏原环境。
        env_root = root / 'cache/update-environments' / job.name
        run_checked([python, '-m', 'venv', str(env_root)], root, log)
        python = str(env_root / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
        run_checked([python, '-m', 'pip', 'install', '-r', str(stage / 'requirements.txt')], root, log)
    run_checked([python, '-m', 'pip', 'check'], root, log, 60)
    for record in manifest['files']:
        path = stage.joinpath(*record['path'].split('/'))
        if path.suffix == '.py':
            compile(path.read_bytes(), str(path), 'exec')
    probe_program(stage, python, log)
    write_state(job / 'prepared.json', {'python':python, 'new_environment':changed})
    return manifest


def safe_target(root, name):
    if not allowed_file(name):
        raise ValueError('升级路径不允许：' + str(name))
    target = Path(root).joinpath(*name.split('/'))
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('升级路径越界：' + name)
    return target


def program_inventory(root):
    root = Path(root)
    paths = list(root.glob('*'))
    for folder in ('static', 'canvas_core', 'data/model_capabilities'):
        paths.extend((root / folder).rglob('*'))
    return {p.relative_to(root).as_posix() for p in paths if p.is_file() and allowed_file(p.relative_to(root).as_posix())}


def recover(root):
    root = Path(root).resolve()
    journal = root / 'cache/runtime/update-transaction.json'
    if not journal.exists():
        return False
    state = json.loads(journal.read_text(encoding='utf-8'))
    backup = root / 'backups/application-updates' / state['id']
    if not backup.resolve().is_relative_to(root / 'backups/application-updates'):
        raise ValueError('升级恢复目录无效')
    for name in state['files']:
        target = safe_target(root, name)
        target.with_name(target.name + '.upgrade-tmp').unlink(missing_ok=True)
        saved = backup / 'program' / name
        if saved.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, target)
        else:
            target.unlink(missing_ok=True)
    pointer = root / 'cache/runtime/active-environment.json'
    saved_pointer = backup / 'environment.json'
    if saved_pointer.exists():
        shutil.copy2(saved_pointer, pointer)
    else:
        pointer.unlink(missing_ok=True)
    # 仅恢复本轮备份的结构化数据，不触碰用户媒体文件。
    saved_data = backup / 'data'
    if saved_data.exists():
        for path in (root / 'data').rglob('*'):
            relative = path.relative_to(root / 'data')
            if path.is_file() and relative.parts[0] not in {'model_capabilities','update_backups','update_staging'} and relative.as_posix() not in state.get('data_files', []):
                path.unlink()
        for path in saved_data.rglob('*'):
            if path.is_file():
                target = root / 'data' / path.relative_to(saved_data)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    write_state(root / 'cache/runtime/last-update.json', {'status':'rolled_back','version':state['version'],'backup':str(backup)})
    journal.unlink()
    return True


def apply_job(root, job):
    # 调用方必须先停止自己管理的服务，不能在线替换正在加载的模块。
    root, job = Path(root).resolve(), Path(job).resolve()
    if not job.is_relative_to(root / 'cache/update-jobs'):
        raise ValueError('升级任务目录无效')
    if (root / 'cache/runtime/update-transaction.json').exists():
        raise RuntimeError('已有未完成升级，请先恢复')
    manifest = json.loads((job / 'release.json').read_text(encoding='utf-8'))
    prepared = json.loads((job / 'prepared.json').read_text(encoding='utf-8'))
    stage = job / 'program'
    for record in manifest['files']:
        path = safe_target(stage, record['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('暂存文件已改变，取消升级')
    current = program_inventory(root)
    incoming = {r['path'] for r in manifest['files']}
    affected = sorted(current | incoming)
    backup = root / 'backups/application-updates' / job.name
    backup.mkdir(parents=True, exist_ok=False)
    for name in current:
        source = safe_target(root, name)
        dest = backup / 'program' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    data = root / 'data'
    if data.exists():
        shutil.copytree(data, backup / 'data', ignore=shutil.ignore_patterns('update_backups','update_staging','model_capabilities'))
    pointer = root / 'cache/runtime/active-environment.json'
    if pointer.exists():
        shutil.copy2(pointer, backup / 'environment.json')
    state = {'id':job.name,'files':affected,'version':manifest['version'],
             'data_files':[p.relative_to(backup / 'data').as_posix() for p in (backup / 'data').rglob('*') if p.is_file()]}
    write_state(root / 'cache/runtime/update-transaction.json', state)
    try:
        for name in affected:
            target = safe_target(root, name)
            if name in incoming:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + '.upgrade-tmp')
                shutil.copy2(stage / name, temporary)
                os.replace(temporary, target)
                if os.name != 'nt' and target.suffix in {'.sh','.command'}:
                    target.chmod(target.stat().st_mode | 0o111)
            elif name.startswith(('static/', 'canvas_core/')):
                target.unlink(missing_ok=True)
        if prepared['new_environment']:
            write_state(pointer, {'python':prepared['python']})
    except BaseException:
        recover(root)
        raise
    return state


def finish(root):
    root = Path(root)
    journal = root / 'cache/runtime/update-transaction.json'
    if journal.exists():
        state = json.loads(journal.read_text(encoding='utf-8'))
        write_state(root / 'cache/runtime/last-update.json', {'status':'succeeded','version':state['version']})
        journal.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='老胡无限画布安全升级。旧安装请先关闭画布服务，再运行此文件。')
    parser.add_argument('--root', default=str(Path(__file__).resolve().parent))
    parser.add_argument('--recover', action='store_true')
    parser.add_argument('--source', choices=['r2','github'], default='r2')
    args = parser.parse_args()
    root = Path(args.root).resolve()
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',3000)) == 0:
            raise SystemExit('请先关闭画布服务再升级；升级器不会结束其他进程。')
    try:
        if args.recover:
            print('已恢复上次未完成升级' if recover(root) else '没有未完成升级')
        else:
            if (root / 'cache/runtime/update-transaction.json').exists():
                recover(root)
            print('正在下载、准备依赖并验证新版，请稍候…', flush=True)
            job = stage_release(root, *github_release()) if args.source == 'github' else stage_release(root)
            prepare_job(root, job)
            apply_job(root, job)
            try:
                probe_program(root, runtime_python(root), job / 'installed-check.log')
            except BaseException:
                recover(root)
                raise
            finish(root)
            print('升级完成。请使用原启动脚本打开画布。')
    except Exception as exc:
        raise SystemExit(str(exc))
