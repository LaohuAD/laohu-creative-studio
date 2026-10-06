"""工作台受管 Hypit：工程与程序分离，原生 CLI 保持原样，不使用符号链接。"""
from __future__ import annotations

import os
import json
import re
import shutil
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.request import urlopen

from canvas_core.json_store import read_json, write_json

HYPIT_VERSION = '0.2.7'
HYPIT_COMMIT = 'a45224c32da6e25bd641e403920ab17d48838417'
HYPIT_INTEGRITY = 'sha512-nUUkzZ9rhnN8BT/G2OXDNu+ktHkn04RE3i/KxXvrHeaqd72AVaGzoPpsYQI7mYOWkCo6zAxeU9711tGzyxJxUw=='
NATIVE_THEME_START = '/* laohu-native-theme:start */'
NATIVE_THEME_END = '/* laohu-native-theme:end */'
NATIVE_THEME_HTML_START = '<!-- laohu-native-theme:start -->'
NATIVE_THEME_HTML_END = '<!-- laohu-native-theme:end -->'


class HypitRuntime:
    def __init__(self, root, profile_provider=None):
        self.root = Path(root).resolve()
        self.home = self.root / 'runtime' / 'hypit'
        self.cache = self.root / 'cache' / 'hypit'
        self.lock = threading.RLock()
        self.sessions = {}
        self.profile_provider = profile_provider
        self.base_url = None

    def project(self, project_id):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', str(project_id)):
            raise ValueError('无效项目 ID')
        path = self.root / 'workflows' / 'hypit' / project_id
        if not path.is_dir() or not path.resolve().is_relative_to((self.root / 'workflows' / 'hypit').resolve()):
            raise ValueError('Hypit 项目不存在')
        return path

    def source(self, project_id, relative):
        base = self.project(project_id)
        if '\\' in relative or ':' in relative or Path(relative).is_absolute():
            raise ValueError('必须使用项目内相对路径')
        path = base / relative
        if not path.resolve().is_relative_to(base.resolve()) or path == base:
            raise ValueError('路径超出当前项目')
        if path.suffix.lower() not in {'.svml', '.svrun', '.svs', '.json', '.md', '.ts', '.js'}:
            raise ValueError('不支持此工程文件类型')
        return path

    @property
    def distribution(self):
        return self.home / HYPIT_VERSION / 'node_modules' / '@hypit' / 'hypit'

    def environment(self):
        env = os.environ.copy()
        for folder in (self.home / 'state', self.cache / 'tmp', self.cache / 'npm', self.home / 'browsers'):
            folder.mkdir(parents=True, exist_ok=True)
        env.update(HYPIT_STATE_HOME=str(self.home / 'state'), TMPDIR=str(self.cache / 'tmp'),
                   TMP=str(self.cache / 'tmp'), TEMP=str(self.cache / 'tmp'),
                   npm_config_cache=str(self.cache / 'npm'), PUPPETEER_CACHE_DIR=str(self.home / 'browsers'),
                   PLAYWRIGHT_BROWSERS_PATH=str(self.home / 'browsers'))
        return env

    def command(self):
        node = shutil.which('node')
        entry = self.distribution / 'bin' / 'hypit.mjs'
        if not node or not entry.is_file():
            raise RuntimeError('Hypit 运行环境未准备，请先安装 Node.js 22.15+ 并准备 Hypit')
        return [node, str(entry)]

    def status(self):
        try:
            result = subprocess.run(self.command() + ['--version'], env=self.environment(),
                                    capture_output=True, text=True, timeout=20)
            ready = result.returncode == 0 and result.stdout.strip() == HYPIT_VERSION
            error = '' if ready else (result.stderr or '运行版本不匹配')[-2000:]
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            ready, error = False, str(exc)
        return {'ready': ready, 'version': HYPIT_VERSION, 'upstream_commit': HYPIT_COMMIT,
                'error': error, 'distribution': str(self.distribution)}

    def install(self):
        """仅显式准备时下载固定版本；不覆盖已有版本或用户 Agent 环境。"""
        with self.lock:
            if self.status()['ready']:
                return self.status()
            node, npm = shutil.which('node'), shutil.which('npm')
            if not node or not npm:
                raise RuntimeError('请先安装 Node.js 22.15+（包含 npm）')
            version = subprocess.check_output([node, '--version'], text=True).strip().lstrip('v')
            parts = tuple(int(x) for x in version.split('.')[:2])
            if parts < (22, 15):
                raise RuntimeError('Hypit 需要 Node.js 22.15 或更高版本')
            # Windows npm.cmd 不能通过 shell 拼接；直接调用其 JavaScript 入口。
            candidates = [Path(npm).resolve().parent / 'node_modules/npm/bin/npm-cli.js',
                          Path(node).resolve().parent / 'node_modules/npm/bin/npm-cli.js',
                          Path(npm).resolve().parent / 'npm-cli.js']
            npm_js = next((p for p in candidates if p.is_file()), None)
            runner = [node, str(npm_js)] if npm_js else [npm]
            if os.name == 'nt' and not npm_js:
                raise RuntimeError('找不到 npm-cli.js，请修复 Node.js 安装')
            target = self.home / ('.prepare-' + uuid.uuid4().hex)
            target.mkdir(parents=True, exist_ok=True)
            write_json(target / 'package.json', {'private': True, 'name': 'laohu-hypit-runtime',
                                                 'version': '1.0.0'})
            env = self.environment()
            env['PUPPETEER_SKIP_DOWNLOAD'] = 'true'
            log = self.cache / 'install.log'
            with log.open('w', encoding='utf-8') as output:
                proc = subprocess.run(runner + ['install', '--prefix', str(target), '--omit=dev',
                                      '--bin-links=false', '--no-audit', '--no-fund',
                                      f'@hypit/hypit@{HYPIT_VERSION}'], env=env,
                                      stdout=output, stderr=subprocess.STDOUT, timeout=900)
            if proc.returncode:
                raise RuntimeError(f'Hypit 安装失败，详情：{log}')
            lockfile = read_json(target / 'package-lock.json')
            package = lockfile.get('packages', {}).get('node_modules/@hypit/hypit', {})
            if package.get('integrity') != HYPIT_INTEGRITY:
                raise RuntimeError('Hypit 安装包校验值与已审核版本不一致，未启用新程序')
            probe = subprocess.run([node, str(target / 'node_modules/@hypit/hypit/bin/hypit.mjs'), '--version'],
                                   env=env, capture_output=True, text=True, timeout=20)
            if probe.returncode or probe.stdout.strip() != HYPIT_VERSION:
                raise RuntimeError('Hypit 新程序启动验证失败，未替换原程序')
            installed = self.home / HYPIT_VERSION
            backup = self.home / ('.previous-' + uuid.uuid4().hex)
            if installed.exists():
                installed.replace(backup)
            try:
                target.replace(installed)
            except OSError:
                if backup.exists():
                    backup.replace(installed)
                raise
            state = self.status()
            if not state['ready']:
                raise RuntimeError(state['error'])
            write_json(self.home / 'installed.json', state)
            return state

    def configure(self, project_id):
        project = self.project(project_id)
        destination = self.root / 'assets' / 'output' / 'hypit' / project_id
        destination.mkdir(parents=True, exist_ok=True)
        path = project / 'hypit.results.json'
        config = {'format': 'hypit.build-results@1', 'use': '@hypit/build-result-fs',
                  'config': {'path': str(destination)}}
        if path.exists() and read_json(path) != config:
            raise RuntimeError('工程已有不同结果仓库配置；需先迁移历史结果，不能覆盖')
        write_json(path, config)
        self.configure_profile(project_id)
        return project

    def configure_profile(self, project_id):
        """显式配置本地媒体与渲染，避免原生默认档案引入另一套账号和推理环境。"""
        from local_runtime import resolve_media_tool
        media = {key: value for key, name in [('ffmpegPath', 'ffmpeg'), ('ffprobePath', 'ffprobe')]
                 if (value := resolve_media_tool(name))}
        profile = {'format': 'hypit.runtime-local@1',
                   'dataRoot': str(self.home / 'projects' / project_id),
                   'credentials': {}, 'bindings': {}, 'endpoints': {
                       'media.local': {'use': '@hypit/provider-media-local', 'config': media},
                       'hyperframes.local': {'use': '@hypit/provider-hyperframes-local',
                           'config': {**media, 'browserCacheDirectory': str(self.home / 'browsers'),
                                      'defaultConcurrency': 1, 'workers': 'auto'}}}}
        if self.base_url:
            # 使用真实文件的轻量包，复用受管发行版提供的 SDK，不安装第二套程序。
            package = self.project(project_id) / 'node_modules' / '@laohu' / 'studio-models'
            package.mkdir(parents=True, exist_ok=True)
            for filename in ('hypit-models.mjs', 'hypit-endpoint.mjs'):
                source = self.root / 'static' / filename
                destination = package / filename
                if not destination.exists() or destination.read_bytes() != source.read_bytes():
                    shutil.copyfile(source, destination)
            write_json(package / 'package.json', {'name': '@laohu/studio-models', 'version': '1.0.0',
                       'type': 'module', 'hypit': {'activation': './hypit-models.mjs'}})
            profile['endpoints']['studio.models'] = {'use': '@laohu/studio-models',
                'config': {'projectId': project_id, 'baseURL': self.base_url, 'pollIntervalMs': 1000}}
            profile['bindings'].update({f'@laohu/studio-models@1#{name}': 'studio.models'
                for name in ('text-generation', 'image-generation', 'video-generation', 'speech-generation', 'audio-generation', 'music-generation')})
        if self.profile_provider:
            extra = self.profile_provider(project_id)
            profile['endpoints'].update(extra.get('endpoints', {}))
            profile['bindings'].update(extra.get('bindings', {}))
        path = self.project(project_id) / '.hypit' / 'workbench.runtime.json'
        write_json(path, profile)
        pointer = self.project(project_id) / '.hypit' / 'runtime'
        pointer.parent.mkdir(parents=True, exist_ok=True)
        previous = pointer.read_text(encoding='utf-8') if pointer.exists() else ''
        if previous and previous.strip() != '.hypit/workbench.runtime.json':
            backup = self.root / 'backups' / 'hypit' / project_id / 'runtime-selection.json'
            if not backup.exists():
                write_json(backup, {'selection': previous})
        pointer.write_text('.hypit/workbench.runtime.json\n', encoding='utf-8')
        return path

    def execute(self, project_id, operation, source='', build_id=''):
        """明确操作清单；不接受任意 CLI 参数、Shell 或工作台外路径。"""
        project = self.configure(project_id)
        if operation in {'check', 'plan', 'build'}:
            target = self.source(project_id, source)
            if not target.is_file():
                raise ValueError('工程文件不存在')
            args = [operation, str(target)]
        elif operation == 'builds':
            args = [operation]
        elif operation == 'history':
            if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,180}', source):
                raise ValueError('history 需要 source 指定输出名称，例如 final.video')
            args = [operation, source]
        elif operation in {'status', 'cancel', 'inspect'}:
            if not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,180}', build_id):
                raise ValueError('无效 Build ID')
            args = [operation, build_id]
        elif operation in {'runtime-init', 'runtime-up', 'runtime-status'}:
            if operation == 'runtime-init':
                return {'operation': operation, 'output': str(project / '.hypit/workbench.runtime.json')}
            args = ['runtime', operation.split('-')[1]]
        else:
            raise ValueError('不支持的 Hypit 操作')
        proc = subprocess.run(self.command() + args + ['--workspace', str(project), '--json'], cwd=project, env=self.environment(),
                              capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=900)
        if proc.returncode and operation not in {'status', 'inspect'}:
            raise RuntimeError((proc.stdout + '\n' + proc.stderr)[-12000:])
        output = proc.stdout[-100000:]
        try:
            output = json.loads(output)
        except ValueError:
            pass
        return {'output': output, 'operation': operation}

    @staticmethod
    def _without_native_theme(content, start, end):
        pattern = re.compile(r'\n?' + re.escape(start) + r'.*?' + re.escape(end) + r'\n?', re.S)
        return pattern.sub('', content)

    def _ensure_native_theme(self):
        """把工作台主题以可重复的受管补丁注入原生 Studio，不改制作流程。"""
        theme_path = self.root / 'static' / 'css' / 'hypit-native-theme.css'
        palette_path = self.root / 'static' / 'css' / 'studio-theme-palettes.css'
        distribution = self.distribution
        style_path = distribution / 'packages' / 'studio' / 'src' / 'style.css'
        index_path = distribution / 'packages' / 'studio' / 'index.html'
        if not theme_path.is_file() or not palette_path.is_file() or not style_path.is_file() or not index_path.is_file():
            raise RuntimeError('Hypit 原生 Studio 主题资源不完整，未启动 Studio')
        if any(path.is_symlink() for path in (theme_path, palette_path, style_path, index_path)):
            raise RuntimeError('Hypit 原生 Studio 主题资源不允许使用符号链接')

        backup_dir = self.root / 'backups' / 'hypit' / 'native-studio' / HYPIT_VERSION
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_style = backup_dir / 'style.css'
        backup_index = backup_dir / 'index.html'
        if not backup_style.exists():
            shutil.copyfile(style_path, backup_style)
        if not backup_index.exists():
            shutil.copyfile(index_path, backup_index)

        theme = '\n\n'.join(path.read_text(encoding='utf-8').strip() for path in (palette_path, theme_path))
        original_style = style_path.read_text(encoding='utf-8')
        base_style = self._without_native_theme(original_style, NATIVE_THEME_START, NATIVE_THEME_END).rstrip()
        patched_style = f'{base_style}\n\n{NATIVE_THEME_START}\n{theme}\n{NATIVE_THEME_END}\n'
        if original_style != patched_style:
            style_path.write_text(patched_style, encoding='utf-8')

        theme_script = '''<script>
(() => {
  const ids = new Set(['studio-violet', 'sunlit', 'vermilion', 'forest', 'classic']);
  const appearances = new Set(['light', 'dark', 'system']);
  const isResolved = value => value === 'dark' || value === 'light' ? value : '';
  const params = new URLSearchParams(location.search);
  const root = document.documentElement;
  const systemScheme = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  let parentOrigin = '';
  try {
    const origin = new URL(params.get('laohu_parent_origin') || '').origin;
    if (origin !== 'null') parentOrigin = origin;
  } catch(e) {}
  let preference = {
    themeId: ids.has(params.get('laohu_theme_id')) ? params.get('laohu_theme_id') : 'studio-violet',
    appearance: appearances.has(params.get('laohu_appearance')) ? params.get('laohu_appearance') : (isResolved(params.get('laohu_theme')) || 'system')
  };
  const resolve = mode => mode === 'system' ? (systemScheme && systemScheme.matches ? 'dark' : 'light') : mode;
  const apply = value => {
    const themeId = ids.has(value && value.themeId) ? value.themeId : preference.themeId;
    const appearance = appearances.has(value && value.appearance) ? value.appearance : preference.appearance;
    const theme = isResolved(value && value.resolvedAppearance) || isResolved(value && value.theme) || resolve(appearance);
    preference = {themeId, appearance};
    root.dataset.laohuTheme = theme;
    root.dataset.laohuThemeId = themeId;
    root.dataset.laohuAppearanceMode = appearance;
    root.style.colorScheme = theme;
  };
  const queryResolved = isResolved(params.get('laohu_resolved_appearance')) || isResolved(params.get('laohu_theme'));
  apply({...preference, resolvedAppearance:queryResolved});
  if (systemScheme && systemScheme.addEventListener) systemScheme.addEventListener('change', () => {
    if (preference.appearance === 'system') apply(preference);
  });
  window.addEventListener('message', event => {
    if (event.source !== window.parent || !event.data || event.data.type !== 'laohu-theme') return;
    if (parentOrigin && event.origin !== parentOrigin) return;
    const incoming = event.data;
    const saved = incoming.preference && typeof incoming.preference === 'object' ? incoming.preference : {};
    apply({
      themeId: incoming.themeId || saved.themeId,
      appearance: incoming.appearance || saved.appearance,
      resolvedAppearance: incoming.resolvedAppearance || incoming.theme || saved.resolvedAppearance
    });
  });
})();
</script>'''
        original_index = index_path.read_text(encoding='utf-8')
        base_index = self._without_native_theme(original_index, NATIVE_THEME_HTML_START, NATIVE_THEME_HTML_END).rstrip()
        marker = f'{NATIVE_THEME_HTML_START}\n{theme_script}\n{NATIVE_THEME_HTML_END}'
        if '</head>' not in base_index:
            raise RuntimeError('Hypit 原生 Studio index.html 缺少 head，未启动 Studio')
        patched_index = base_index.replace('</head>', f'\n{marker}\n</head>', 1).rstrip() + '\n'
        if original_index != patched_index:
            index_path.write_text(patched_index, encoding='utf-8')
        return {'style': str(style_path), 'index': str(index_path), 'backup': str(backup_dir)}

    def studio(self, project_id, source):
        with self.lock:
            project = self.configure(project_id)
            run = self.source(project_id, source)
            if not run.is_file() or run.suffix != '.svrun':
                raise ValueError('请选择存在的 .svrun 文件')
            self._ensure_native_theme()
            key = (project_id, str(run))
            existing = self.sessions.get(key)
            if existing and existing['process'].poll() is None:
                return {'url': existing['url']}
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            log = self.cache / f'studio-{project_id}.log'
            self.environment()
            with log.open('w', encoding='utf-8') as output:
                process = subprocess.Popen(self.command() + ['studio', '--run', str(run), '--workspace',
                                           str(project), '--runtime', str(project / '.hypit/workbench.runtime.json'),
                                           '--port', str(port)], cwd=project,
                                           env=self.environment(), stdout=output, stderr=subprocess.STDOUT)
            # Vite 可能因端口竞争自动换端口，必须读取真实 URL 再检查 HTTP。
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline and process.poll() is None:
                content = log.read_text(encoding='utf-8', errors='replace')
                match = re.search(r'http://(?:localhost|127\.0\.0\.1):([0-9]+)/', content)
                if match:
                    url = f'http://localhost:{match.group(1)}/'
                    try:
                        with urlopen(url, timeout=1) as response:
                            if response.status == 200:
                                self.sessions[key] = {'process': process, 'url': url}
                                return {'url': url}
                    except OSError:
                        pass
                time.sleep(.15)
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            raise RuntimeError('Hypit Studio 未就绪：' + log.read_text(encoding='utf-8', errors='replace')[-4000:])

    def close(self):
        with self.lock:
            for session in self.sessions.values():
                process = session['process']
                if process.poll() is None:
                    process.terminate()
            self.sessions.clear()
