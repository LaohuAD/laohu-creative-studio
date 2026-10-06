"""Mac/Windows 共用的本地安装、就绪检查与启动入口；不结束既有进程。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import functools
import signal
import socket
import subprocess
import sys
import time
import uuid
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
LOCAL_URL = 'http://127.0.0.1:3000/'
REPO_URL = 'https://github.com/LaohuAD/laohu-creative-studio'


@functools.lru_cache(maxsize=48)
def _media_binary_works(path: str, modified: int, time_bucket: int) -> bool:
    """检查动态库是否齐全；文件存在或 which 命中不代表能运行。"""
    try:
        return subprocess.run([path, '-version'], capture_output=True, timeout=8).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def resolve_media_tool(name: str) -> str | None:
    if name not in {'ffmpeg', 'ffprobe'}:
        raise ValueError('不支持的媒体工具')
    executable = name + ('.exe' if os.name == 'nt' else '')
    candidates = [os.environ.get('LAOHU_' + name.upper() + '_PATH'), shutil.which(name),
                  str(ROOT / 'ffmpeg' / 'bin' / executable), str(ROOT / 'bin' / executable)]
    if sys.platform == 'darwin':
        for prefix in (Path('/opt/homebrew/opt'), Path('/usr/local/opt')):
            candidates.extend(str(p / 'bin' / executable) for p in sorted(prefix.glob('ffmpeg*'), reverse=True))
    for candidate in dict.fromkeys(candidates):
        if not candidate:
            continue
        try:
            stamp = Path(candidate).stat().st_mtime_ns
        except OSError:
            continue
        if _media_binary_works(candidate, stamp, int(time.monotonic() // 30)):
            return candidate
    return None


def environment_python(root: Path, platform: str | None = None) -> Path:
    platform = platform or os.name
    from canvas_update import runtime_python
    return Path(runtime_python(root, platform=platform))


def runtime_environment(root: Path) -> dict:
    env = dict(os.environ)
    for key, directory in [('TMPDIR', 'tmp'), ('TMP', 'tmp'), ('TEMP', 'tmp'), ('PIP_CACHE_DIR', 'pip')]:
        path = root / 'cache' / 'runtime' / directory
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def canvas_ready(url: str = LOCAL_URL, expected_version: str = "") -> bool:
    try:
        # 本地探测不经过系统 HTTP 代理。
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url.rstrip('/') + '/api/app-info', timeout=1) as response:
            info = json.loads(response.read(65536))
        return isinstance(info, dict) and info.get('repo_url') == REPO_URL and bool(info.get('version')) and (not expected_version or info['version'] == expected_version)
    except (OSError, ValueError):
        return False


def port_open() -> bool:
    try:
        with socket.create_connection(('127.0.0.1', 3000), timeout=0.3):
            return True
    except OSError:
        return False


def stop_owned_process(child) -> None:
    """只清理本次启动所创建的进程组，绝不按端口查杀其他程序。"""
    if child.poll() is not None:
        return
    try:
        if os.name == 'nt':
            child.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(child.pid, signal.SIGINT)
        child.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def request_restart(root: Path, delay_seconds: int = 3, update_job: str = "") -> bool:
    """请求启动器重启其自己的子进程；直接启动 main.py 时由用户手动重启。"""
    value = os.environ.get('INFINITE_CANVAS_RESTART_FILE', '')
    if not value:
        return False
    request = Path(value).resolve()
    folder = (root / 'cache' / 'runtime' / 'restarts').resolve()
    if request.parent != folder or request.suffix != '.json' or not folder.is_dir():
        return False
    temporary = request.with_suffix('.tmp')
    temporary.write_text(json.dumps({'restart_at': time.time() + max(1, int(delay_seconds or 3)), 'update_job':update_job}), encoding='utf-8')
    os.replace(temporary, request)
    return True


def launch(root: Path = ROOT, open_browser: bool = True) -> int:
    if canvas_ready():
        print('画布已运行，复用现有服务：' + LOCAL_URL, flush=True)
        if open_browser:
            webbrowser.open(LOCAL_URL)
        return 0
    if port_open():
        print('3000 端口已被其他服务占用或画布尚未就绪。请稍后重试或检查该程序；启动器不会结束它。', flush=True)
        return 1
    import canvas_update
    canvas_update.recover(root)
    env = runtime_environment(root)
    # 本地开发服务开启 Uvicorn 的 Python 自动重载；静态资源仍由
    # /api/static-revision + live-reload.js 负责无感刷新。
    env['INFINITE_CANVAS_AUTO_RELOAD'] = '1'
    env['INFINITE_CANVAS_UPDATER_PROTOCOL'] = '1'
    requests = root / 'cache' / 'runtime' / 'restarts'
    requests.mkdir(parents=True, exist_ok=True)
    request = requests / (uuid.uuid4().hex + '.json')
    env['INFINITE_CANVAS_RESTART_FILE'] = str(request)
    kwargs = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    child = None
    browser_opened = False
    upgrading = False
    try:
        while True:
            try:
                app_python = environment_python(root)
                child = subprocess.Popen([str(app_python), str(root / 'main.py')], cwd=root, env=env, **kwargs)
            except (RuntimeError, ValueError) as exc:
                if upgrading:
                    canvas_update.recover(root)
                    upgrading = False
                print(str(exc), flush=True)
                return 1
            except OSError:
                if upgrading:
                    canvas_update.recover(root)
                    upgrading = False
                    continue
                raise
            deadline = time.monotonic() + 60
            ready = False
            while True:
                code = child.poll()
                if code is not None:
                    if not ready and upgrading:
                        canvas_update.recover(root)
                        upgrading = False
                        print('新版启动失败，已恢复旧程序、依赖入口与结构化数据，正在重新启动…', flush=True)
                        break
                    if not ready:
                        print('服务启动失败，请查看上方错误，必要时运行依赖安装脚本。', flush=True)
                    return code if ready else (code or 1)
                if not ready and (canvas_ready(expected_version=(root / 'VERSION').read_text(encoding='utf-8').strip()) if upgrading else canvas_ready()):
                    ready = True
                    if upgrading:
                        canvas_update.finish(root)
                        upgrading = False
                    print('画布已就绪：' + LOCAL_URL + '（按 Ctrl+C 停止）', flush=True)
                    if open_browser and not browser_opened:
                        webbrowser.open(LOCAL_URL)
                        browser_opened = True
                if not ready and time.monotonic() >= deadline:
                    stop_owned_process(child)
                    if upgrading:
                        canvas_update.recover(root)
                        upgrading = False
                        print('新版就绪超时，已恢复旧版。', flush=True)
                        break
                    print('启动超过 60 秒仍未就绪，请查看上方错误。', flush=True)
                    return 1
                if request.exists():
                    try:
                        restart_data = json.loads(request.read_text(encoding='utf-8'))
                        restart_at = float(restart_data['restart_at'])
                    except (OSError, ValueError, KeyError, TypeError):
                        request.unlink(missing_ok=True)
                    else:
                        if time.time() >= restart_at:
                            request.unlink(missing_ok=True)
                            print('正在重启本启动器管理的画布服务…', flush=True)
                            stop_owned_process(child)
                            if restart_data.get('update_job'):
                                try:
                                    canvas_update.apply_job(root, restart_data['update_job'])
                                    upgrading = True
                                except Exception as exc:
                                    print(f'升级未完成，保留或恢复旧版：{exc}', flush=True)
                            break
                time.sleep(0.3)
    except KeyboardInterrupt:
        return 0
    finally:
        if child is not None:
            stop_owned_process(child)
        request.unlink(missing_ok=True)


def install(root: Path = ROOT) -> int:
    env = runtime_environment(root)
    import canvas_update
    try:
        target_version = canvas_update.required_python_version(root)
    except (OSError, ValueError) as exc:
        print(str(exc), flush=True)
        return 1
    created_environment = False
    try:
        python = str(environment_python(root))
    except RuntimeError:
        try:
            bootstrap = canvas_update.bootstrap_python(root, target_version)
        except (OSError, RuntimeError, ValueError) as exc:
            print(str(exc), flush=True)
            return 1
        env_root = root / 'cache' / 'update-environments' / ('install-' + target_version + '-' + uuid.uuid4().hex)
        code = subprocess.call([bootstrap, '-m', 'venv', str(env_root)], cwd=root, env=env)
        if code:
            return code
        python = str(canvas_update.venv_python(env_root))
        if canvas_update.interpreter_version(python) != target_version:
            print(f'新建运行环境版本不符合 Python {target_version}，旧环境保持不变。', flush=True)
            return 1
        created_environment = True
    except ValueError as exc:
        print(str(exc), flush=True)
        return 1
    def run(*args):
        return subprocess.call([python, *args], cwd=root, env=env)
    if run('-m', 'pip', '--version'):
        if run('-m', 'ensurepip', '--upgrade'):
            print('当前 Python 环境缺少 pip；未安装依赖，也未切换运行环境。', flush=True)
            return 1
    code = run('-m', 'pip', 'install', '--no-index', '--find-links', str(root / 'packages'), '-r', str(root / 'requirements.txt'))
    if code:
        print('离线包不完整或不适合当前 Python，转为在线安装。', flush=True)
        code = run('-m', 'pip', 'install', '-r', str(root / 'requirements.txt'))
    if code == 0:
        code = run('-m', 'pip', 'check')
    if code == 0:
        code = run('-c', 'import fastapi, uvicorn, requests, pydantic, multipart, httpx, httpcore, socksio, PIL, qrcode, websockets, watchfiles')
    if code == 0:
        if created_environment:
            canvas_update.write_state(root / 'cache/runtime/active-environment.json', {'python': python})
        print('依赖安装完成。Mac 请运行 mac-启动服务.command；Windows 请运行 run.bat。', flush=True)
    else:
        print('依赖安装失败，请处理上方错误后重试。', flush=True)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', help='安装到启动时使用的同一 Python 环境')
    parser.add_argument('--no-browser', action='store_true', help='启动但不打开浏览器')
    parser.add_argument('--check', action='store_true', help='只检查现有服务，不启动、不停止服务')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        print('此安装入口至少需要 Python 3.10；画布服务仍必须使用根目录 .python-version 指定的精确版本。')
        return 1
    if args.check:
        ready = canvas_ready()
        print('画布已就绪：' + LOCAL_URL if ready else '画布未就绪。')
        return 0 if ready else 1
    return install(ROOT) if args.install else launch(ROOT, not args.no_browser)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print('启动/安装失败：' + str(exc), file=sys.stderr)
        raise SystemExit(1)
