"""画梦枋品牌主题跨模块浏览器回归；只使用本地静态页和隔离浏览器配置。"""
from __future__ import annotations

import base64
import json
import re
import shutil
import socket
import subprocess
import threading
import time
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def chrome_binary():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    return next((item for item in candidates if item and Path(item).is_file()), None)


CHROME = chrome_binary()
NODE = shutil.which("node")
PAGES = {
    "shell": "/static/index.html",
    "projects": "/static/canvas-list.html",
    "canvas": "/static/smart-canvas.html",
    "api": "/static/api-settings.html",
    "assets": "/static/asset-manager.html",
    "hypit": "/static/hypit.html",
}
THEME_IDENTITIES = ("studio-violet", "sunlit", "vermilion", "forest", "classic")


@unittest.skipUnless(CHROME and NODE, "需要本机 Chrome/Chromium 和 Node.js 执行隔离浏览器回归")
class StudioBrandBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        contract_source = (ROOT / "static" / "js" / "smart-node-contract.js").read_text(encoding="utf-8")
        schema_match = re.search(r"\bconst\s+SCHEMA_VERSION\s*=\s*(\d+)\s*;", contract_source)
        if not schema_match:
            raise AssertionError("无法从 SmartNodeContract 读取当前画布 schema 版本")
        cls.canvas_schema_version = int(schema_match.group(1))

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT), **kwargs)

            def log_message(self, *_args):
                pass

            def _json(self, status, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    # 浏览器切页时会取消旧读请求；这属于测试客户端正常行为。
                    pass

            def _html(self, body):
                encoded = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self):
                parsed = urlsplit(self.path)
                path = parsed.path
                query = parse_qs(parsed.query)
                if path == "/fixture/brand-storage-ready.html":
                    # 只用于建立同源 localStorage；不加载任何产品脚本，避免预热导航启动画布。
                    self._html("<!doctype html><html><head><meta charset='utf-8'><title>fixture ready</title></head><body></body></html>")
                    return
                if path == "/api/studio/projects":
                    module = query.get("module", ["canvas"])[0]
                    project_id = "safe-hypit" if module == "hypit" else "safe-canvas"
                    self._json(200, {"projects": [{
                        "id": project_id, "module": module, "name": "安全视觉验收样例",
                        "updated_at": 1791060000, "revision": 1,
                        "url": f"/static/smart-canvas.html?id=brand-fixture",
                    }]})
                    return
                if path == "/api/canvases/trash":
                    self._json(200, {"items": []})
                    return
                if path == "/api/providers":
                    self._json(200, {"providers": []})
                    return
                if path == "/api/model-capabilities":
                    self._json(200, {"schema_version": 1, "providers": []})
                    return
                if path == "/api/config":
                    self._json(200, {"api_providers": [], "comfy_instances": []})
                    return
                if path == "/api/studio/hypit/models/capabilities":
                    self._json(200, {
                        "providers": [], "options": [], "supported_capabilities": [],
                        "unsupported_capabilities": [], "catalog_revision": "safe-fixture",
                    })
                    return
                if path == "/api/studio/hypit/models/settings":
                    self._json(200, {"defaults": {}, "revision": 1, "parameter_mode": "per_request"})
                    return
                if path == "/api/hypit/settings-canvas":
                    canvas = {
                        "id": "hypit-settings", "title": "Hypit settings", "project": "__hypit_settings__",
                        "revision": 1, "updated_at": 1791060000, "node_schema_version": 9999,
                        "hypit_flow_schema_version": 1, "nodes": [], "connections": [], "logs": [],
                        "settings": {}, "viewport": {"x": 0, "y": 0, "scale": 1}, "test_statuses": {},
                    }
                    self._json(200, {"id": "hypit-settings", "canvas": canvas,
                                     "url": "/static/smart-canvas.html?id=hypit-settings&mode=hypit-settings"})
                    return
                if path == "/api/canvases/hypit-settings":
                    self._json(200, {"canvas": {
                        "id": "hypit-settings", "title": "Hypit settings", "project": "__hypit_settings__",
                        "revision": 1, "updated_at": 1791060000, "node_schema_version": 9999,
                        "hypit_flow_schema_version": 1, "nodes": [], "connections": [], "logs": [],
                        "settings": {}, "viewport": {"x": 0, "y": 0, "scale": 1}, "test_statuses": {},
                    }})
                    return
                if path == "/api/canvases/hypit-settings/meta":
                    self._json(200, {"id": "hypit-settings", "revision": 1, "updated_at": 1791060000})
                    return
                if path == "/api/model-pricing":
                    self._json(200, {"schema_version": 1, "entries": {}, "unit_definitions": {}})
                    return
                if path == "/api/workflows":
                    self._json(200, {"workflows": []})
                    return
                if path == "/api/canvases/brand-fixture":
                    self._json(200, {"canvas": {
                        "id": "brand-fixture", "title": "安全画布样例", "project": "safe-canvas",
                        "node_schema_version": cls.canvas_schema_version, "nodes": [], "connections": [], "settings": {},
                    }})
                    return
                if path == "/api/canvas-runs":
                    self._json(200, {"runs": []})
                    return
                if path == "/api/smart-canvas/personalization":
                    self._json(200, {})
                    return
                if path == "/api/asset-library":
                    svg = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16'%3E%3Crect width='16' height='16' fill='%23f15b49'/%3E%3C/svg%3E"
                    self._json(200, {"library": {"libraries": [{
                        "id": "default", "name": "安全素材库", "categories": [{
                            "id": "safe-gallery", "name": "安全样例", "type": "image", "items": [{
                                "id": "safe-image", "name": "safe-sample.svg", "url": svg,
                                "kind": "image", "created_at": 1791060000,
                            }],
                        }],
                    }]}})
                    return
                if path == "/api/prompt-libraries":
                    self._json(200, {"library": {"active_library_id": "system", "libraries": [
                        {"id": "system", "name": "安全系统库", "system": True, "items": [], "categories": []}
                    ]}})
                    return
                if path == "/api/results":
                    self._json(200, {"counts": {"all": 0, "image": 0, "video": 0, "audio": 0, "text": 0}, "items": []})
                    return
                if path == "/api/shared-folders":
                    self._json(200, {"folders": []})
                    return
                if path == "/api/local-assets":
                    self._json(200, {"items": [], "tree": {"id": "__root__", "path": "", "name": "全部上传", "count": 0, "items": [], "children": []}})
                    return
                if path == "/api/studio/projects/safe-hypit":
                    self._json(200, {"project": {"id": "safe-hypit", "name": "安全 Hypit 样例", "module": "hypit"}})
                    return
                if path == "/api/studio/hypit/projects/safe-hypit/files":
                    self._json(200, {"files": ["安全视觉样例.svrun"]})
                    return
                if path == "/api/studio/hypit/runtime":
                    self._json(200, {"ready": True})
                    return
                if path == "/fixture/hypit-studio.html":
                    self._html("""<!doctype html><html><head><meta charset='utf-8'>
                      <meta name='viewport' content='width=device-width,initial-scale=1'>
                      <link rel='stylesheet' href='/static/css/hypit-native-theme.css'></head>
                      <body><div id='app'><div class='topbar'>Hypit 安全预览</div>
                      <section class='preview-panel'><img class='brand-regression-media' alt='安全颜色样例'
                      src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2216%22 height=%2216%22%3E%3Crect width=%2216%22 height=%2216%22 fill=%22%23f15b49%22/%3E%3C/svg%3E'></section>
                      <button class='parameter-select-trigger'>参数</button></div>
                      <script>document.documentElement.dataset.laohuTheme=new URLSearchParams(location.search).get('laohu_theme')||'light';
                      document.documentElement.dataset.fixtureReady='true';</script></body></html>""")
                    return
                if path.startswith("/api/"):
                    self._json(404, {"detail": "安全浏览器测试未实现此只读路由"})
                    return
                super().do_GET()

            def do_POST(self):
                if urlsplit(self.path).path == "/api/studio/hypit/projects/safe-hypit/studio":
                    length = int(self.headers.get("Content-Length", "0"))
                    self.rfile.read(length)
                    self._json(200, {"url": f"http://127.0.0.1:{cls.http_port}/fixture/hypit-studio.html"})
                    return
                self._json(403, {"detail": "隔离视觉测试只允许 Hypit 本地预览样例"})


        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.http_port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.debug_port = probe.getsockname()[1]
        cls.cache = ROOT / "cache" / "studio-tests"
        cls.cache.mkdir(parents=True, exist_ok=True)
        cls.profile = cls.cache / "tmp" / f"brand-browser-{int(time.time())}"
        cls.profile.mkdir(parents=True, exist_ok=True)
        cls.chrome = subprocess.Popen(
            [
                CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--window-size=1440,1000", "--force-device-scale-factor=1",
                f"--user-data-dir={cls.profile}",
                f"--remote-debugging-port={cls.debug_port}", "about:blank",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.target = cls._wait_for_target()
        if not cls.target:
            cls.tearDownClass()
            raise unittest.SkipTest("Chrome 未能暴露调试目标")
        node_script = r"""const readline=require('readline');
const ws=new WebSocket(process.argv[1]);
const input=readline.createInterface({input:process.stdin});
ws.onopen=()=>{console.log(JSON.stringify({ready:true}));input.on('line',line=>{
  const request=JSON.parse(line);ws.send(JSON.stringify({id:request.id,method:request.method,params:request.params||{}}));
});};
ws.onmessage=event=>{const message=JSON.parse(event.data);if(message.id!==undefined){
  console.log(JSON.stringify({id:message.id,result:message.result||{},error:message.error||null}));
}};"""
        cls.cdp_process = subprocess.Popen(
            [NODE, "-e", node_script, cls.target["webSocketDebuggerUrl"]],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        ready = json.loads(cls.cdp_process.stdout.readline() or "{}")
        if not ready.get("ready"):
            cls.tearDownClass()
            raise unittest.SkipTest("未能建立持久 CDP 会话")
        cls.cdp("Page.enable")
        cls.cdp("Runtime.enable")
        cls.cdp("Page.addScriptToEvaluateOnNewDocument", {"source": r"""(() => {
          const state = window.__brandBrowserDiagnostics = {errors:[], apiFetches:[]};
          const pathOf = value => { try { return new URL(value, location.href).pathname; } catch (_) { return String(value || ''); } };
          addEventListener('error', event => {
            state.errors.push({type:'error', message:String(event.message || ''), source:pathOf(event.filename || event.target?.src || ''), line:Number(event.lineno || 0)});
          });
          addEventListener('unhandledrejection', event => {
            const reason=event.reason;
            state.errors.push({type:'unhandledrejection', message:String(reason?.stack || reason?.message || reason || '')});
          });
          const originalFetch=window.fetch;
          if(typeof originalFetch==='function') window.fetch=function(input, init){
            const path=pathOf(typeof input==='string' ? input : input?.url || '');
            if(!path.startsWith('/api/')) return originalFetch.apply(this, arguments);
            const entry={path, state:'pending', status:null};
            state.apiFetches.push(entry);
            return originalFetch.apply(this, arguments).then(response=>{
              entry.state='complete'; entry.status=response.status; return response;
            }, error=>{
              entry.state='error'; entry.error=String(error?.message || error); throw error;
            });
          };
        })();"""})

    @classmethod
    def tearDownClass(cls):
        try:
            if getattr(cls, "cdp_process", None):
                cls.cdp_process.terminate()
                cls.cdp_process.wait(timeout=5)
            if getattr(cls, "chrome", None):
                cls.chrome.terminate()
                cls.chrome.wait(timeout=10)
        except Exception:
            pass
        if getattr(cls, "server", None):
            cls.server.shutdown()
            cls.server.server_close()
        shutil.rmtree(getattr(cls, "profile", ""), ignore_errors=True)

    @classmethod
    def _wait_for_target(cls):
        import urllib.request

        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cls.debug_port}/json/list", timeout=2) as response:
                    targets = json.loads(response.read().decode("utf-8"))
                for target in targets:
                    if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                        return target
            except Exception:
                time.sleep(0.2)
        return None

    @classmethod
    def cdp(cls, method, params=None):
        request_id = getattr(cls, "cdp_request_id", 0) + 1
        cls.cdp_request_id = request_id
        cls.cdp_process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params or {}}) + "\n")
        cls.cdp_process.stdin.flush()
        response = json.loads(cls.cdp_process.stdout.readline() or "{}")
        if response.get("id") != request_id or response.get("error"):
            raise AssertionError(f"CDP 调用失败：{response.get('error') or response}")
        return response.get("result", {})

    @classmethod
    def evaluate(cls, expression):
        result = cls.cdp("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        })
        if result.get("exceptionDetails"):
            raise AssertionError(f"页面断言脚本异常：{result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def wait_for_document(self, url, timeout=12):
        """等指定 URL 的文档本身完成，忽略前一次导航留下的 complete 状态。"""
        deadline = time.monotonic() + timeout
        last_state = None
        while time.monotonic() < deadline:
            try:
                last_state = self.evaluate("({url:location.href,readyState:document.readyState})")
            except AssertionError:
                # 导航切换期间旧执行上下文可能被销毁；继续读取新文档。
                time.sleep(0.05)
                continue
            if last_state and last_state.get("url") == url and last_state.get("readyState") == "complete":
                return last_state
            time.sleep(0.05)
        self.fail(f"文档未在期限内完成导航：期望={url!r}，最近状态={last_state!r}")

    def set_viewport(self, width, height=1000):
        # 持久 CDP 会话保留设备仿真视口，使 390px 真正通过窄屏断点。
        self.cdp("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600,
        })

    def navigate(self, page, theme, width, theme_id="studio-violet", exercise_api_nav=True):
        self.set_viewport(width)
        page_path = PAGES[page]
        if page == "canvas":
            page_path += "?id=brand-fixture"
        elif page == "hypit":
            page_path += "?id=safe-hypit"
        elif page in ("projects",):
            page_path += "?id=safe-canvas"
        url = f"http://127.0.0.1:{self.http_port}{page_path}"
        prep_url = f"http://127.0.0.1:{self.http_port}/fixture/brand-storage-ready.html"
        prep_navigation = self.cdp("Page.navigate", {"url": prep_url})
        self.assertFalse(prep_navigation.get("errorText"), f"同源准备页导航失败：{prep_navigation}")
        self.wait_for_document(prep_url)
        self.assertEqual(self.evaluate(f"""(() => {{
          if(location.origin!=='http://127.0.0.1:{self.http_port}') return false;
          localStorage.setItem('studio_theme',{json.dumps(theme)});
          localStorage.setItem('canvas_theme',{json.dumps(theme)});
          return true;
        }})()"""), True, "隔离测试源站未就绪")
        delimiter = "&" if "?" in url else "?"
        final_url = url + f"{delimiter}brand-test=1&theme={theme}"
        final_navigation = self.cdp("Page.navigate", {"url": final_url})
        self.assertFalse(final_navigation.get("errorText"), f"最终页面导航失败：{final_navigation}")
        self.wait_for_document(final_url)
        ready_checks = {
            "shell": "(() => { const frame=document.querySelector('iframe.active'); const style=frame&&getComputedStyle(frame); return document.querySelectorAll('.side-pill').length >= 4 && getComputedStyle(document.body).visibility === 'visible' && frame?.contentDocument?.readyState === 'complete' && frame.contentDocument.querySelector('[data-project-id=\"safe-canvas\"]') && Number(style.opacity) >= .99 && style.filter === 'blur(0px)'; })()",
            "projects": "document.querySelector('[data-project-id=\"safe-canvas\"]') !== null",
            "canvas": "document.getElementById('smartTitle')?.textContent === '安全画布样例'",
            "api": "document.getElementById('settingsContent')?.dataset.apiStartup === 'empty'",
            "assets": "document.getElementById('assetStatus')?.textContent === '准备就绪' && !!document.querySelector('.asset-nav .nav-tree') && !!document.querySelector('[data-asset-card=\"safe-image\"]')",
            "hypit": "(() => { const frame = document.getElementById('nativeStudio'); const target = frame?.contentDocument; return frame?.hidden === false && target?.readyState === 'complete' && target.documentElement?.dataset?.fixtureReady === 'true' && frame.contentWindow?.location?.pathname === '/fixture/hypit-studio.html'; })()",
        }
        canvas_ready = self.evaluate(f"""(async()=>{{
          for(let i=0;i<120;i++){{if({ready_checks[page]})return true;await new Promise(r=>setTimeout(r,50));}}
          return false;
        }})()""")
        if not canvas_ready:
            diagnostics = self.evaluate("""(() => ({
              url: location.href,
              readyState: document.readyState,
              title: document.title,
              smartTitle: document.getElementById('smartTitle')?.textContent?.trim() || null,
              canvasId: typeof canvasId === 'string' ? canvasId : null,
              canvasMode: document.documentElement.dataset.canvasMode || null,
              loadCanvasType: typeof loadCanvas,
              onloadType: typeof window.onload,
              navigation: performance.getEntriesByType('navigation').map(item=>({name:item.name,type:item.type,domComplete:Math.round(item.domComplete),loadEventEnd:Math.round(item.loadEventEnd)})),
              scripts: performance.getEntriesByType('resource').filter(item=>item.initiatorType==='script'||item.name.split('?')[0].toLowerCase().endsWith('.js')).map(item=>({name:item.name,status:item.responseStatus,duration:Math.round(item.duration)})),
              apiResources: performance.getEntriesByType('resource').filter(item=>item.name.includes('/api/')).map(item=>({name:item.name,status:item.responseStatus,duration:Math.round(item.duration)})),
              apiFetches: window.__brandBrowserDiagnostics?.apiFetches || [],
              browserErrors: window.__brandBrowserDiagnostics?.errors || [],
              canvasRoot: !!document.getElementById('world'),
              nodeCount: document.querySelectorAll('.smart-node').length,
              startupText: document.querySelector('.canvas-status,.canvas-empty-state,[role="alert"]')?.textContent?.trim() || null,
              canvasRequest: performance.getEntriesByType('resource')
                .filter(item => item.name.includes('/api/canvases/brand-fixture'))
                .map(item => ({name:item.name,responseStatus:item.responseStatus,duration:Math.round(item.duration)}))
            }))()""")
            self.fail(f"{page} 页面未完成隔离真实数据路径的业务初始化：{diagnostics}")
        preference = json.dumps({"themeId": theme_id, "appearance": theme}, ensure_ascii=False)
        self.assertEqual(self.evaluate(f"""(() => {{
          if(typeof StudioTheme?.setPreference !== 'function') return false;
          StudioTheme.setPreference({preference});
          const frame=document.querySelector('iframe.active');
          if(frame && typeof window.syncThemeToFrame === 'function') syncThemeToFrame(frame);
          return true;
        }})()"""), True, "主题身份与外观偏好接口不可用")
        self.assertEqual(self.evaluate(f"""(async()=>{{
          for(let i=0;i<80;i++){{
            const p=StudioTheme.getPreference();
            if(p.themeId==={json.dumps(theme_id)}&&p.appearance==={json.dumps(theme)}&&
               document.documentElement.dataset.studioTheme==={json.dumps(theme_id)}&&
               document.documentElement.dataset.studioAppearance==={json.dumps(theme)}) return true;
            await new Promise(r=>setTimeout(r,20));
          }}
          return false;
        }})()"""), True, "主题身份或外观没有应用到当前页面")
        if page == "api" and exercise_api_nav:
            boot = self.evaluate("""(() => ({
              state:document.getElementById('apiSettingsBootState')?.dataset.state,
              title:document.querySelector('#apiSettingsBootState .api-settings-boot-title')?.textContent?.trim(),
              spinner:document.querySelector('#apiSettingsBootState .api-settings-boot-mark')
                ? getComputedStyle(document.querySelector('#apiSettingsBootState .api-settings-boot-mark')).display : null
            }))()""")
            self.assertEqual(boot["state"], "empty", boot)
            self.assertTrue(any(token in (boot["title"] or "") for token in ("API 设置已读取", "API settings loaded")), boot)
            self.assertEqual(boot["spinner"], "none", boot)
            self.evaluate("""window.__brandStyle = (el) => {
              const parse=(value)=>{
                const values=value.match(/[\\d.]+/g)?.map(Number);
                return values?.length>=3 ? [values[0],values[1],values[2],values.length>3?values[3]:1] : null;
              };
              const paintedBackground=(element)=>{
                const layers=[];
                for(let node=element;node;node=node.parentElement){
                  const color=parse(getComputedStyle(node).backgroundColor);
                  if(color && color[3]>0) layers.push(color);
                }
                let result=[255,255,255,1];
                for(const [r,g,b,a] of layers.reverse()) result=[r*a+result[0]*(1-a),g*a+result[1]*(1-a),b*a+result[2]*(1-a),1];
                return `rgb(${result.slice(0,3).map(v=>Math.round(v)).join(', ')})`;
              };
              const luminance=(value)=>{const [r,g,b]=value.match(/[\\d.]+/g).map(Number).slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});return .2126*r+.7152*g+.0722*b;};
              const style=getComputedStyle(el),background=paintedBackground(el);
              const a=luminance(style.color),b=luminance(background);
              return {background,color:style.color,contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
            };""")
            self.evaluate("document.getElementById('canvasModelsNav').click()")
            self.assertEqual(self.evaluate("document.getElementById('canvasModelsNav').classList.contains('active')"), True,
                             "API 左导航点击后没有选中模块模型")
            self.assertEqual(self.evaluate("""(async()=>{for(let i=0;i<80;i++){
              const report=window.__brandStyle(document.getElementById('canvasModelsNav'));
              if(report.contrast>=4.5) return true;
              await new Promise(r=>setTimeout(r,20));
            }return false;})()"""), True, "画布模块选中样式没有完成过渡")
            self.evaluate("window.__brandCanvasActive = window.__brandStyle(document.getElementById('canvasModelsNav'))")
            self.evaluate("document.getElementById('hypitSettingsNav').click()")
            self.assertEqual(self.evaluate("document.getElementById('hypitSettingsNav').classList.contains('active')"), True,
                             "API 左导航点击后没有选中 Hypit")
            self.assertEqual(self.evaluate("document.querySelector('.layout').classList.contains('hypit-settings-mode')"), True,
                             "Hypit active 样式断言未经过真实模块切换")
            self.assertEqual(self.evaluate("""(async()=>{for(let i=0;i<160;i++){
              const style=getComputedStyle(document.getElementById('hypitSettingsNav'));
              const frame=document.getElementById('hypitSettingsCanvasFrame');
              const target=frame?.contentDocument;
              const route=new URL(frame?.src||'about:blank',location.href);
              const status=document.getElementById('hypitSettingsStatus')?.textContent || '';
              const report=window.__brandStyle(document.getElementById('hypitSettingsNav'));
              const sharedCanvas=frame?.hidden===false && route.pathname==='/static/smart-canvas.html'
                && route.searchParams.get('id')==='hypit-settings'
                && route.searchParams.get('mode')==='hypit-settings'
                && target?.documentElement?.dataset?.canvasMode==='hypit-settings'
                && !!target?.getElementById('world');
              if(report.contrast>=4.5 && sharedCanvas && !/无法读取|failed|error/i.test(status)) return true;
              await new Promise(r=>setTimeout(r,25));
            }return false;})()"""), True, "Hypit active 样式或隔离共享画布未完成")
            self.evaluate("window.__brandHypitActive = window.__brandStyle(document.getElementById('hypitSettingsNav'))")

    def snapshot(self, page, theme, width, theme_id="studio-violet"):
        self.navigate(page, theme, width, theme_id=theme_id)
        theme_panel_languages = None
        if page == "shell":
            self.evaluate("document.getElementById('theme-toggle-btn').click()")
            self.assertTrue(self.evaluate("""(async()=>{for(let i=0;i<80;i++){
              const panel=document.getElementById('studioThemePanel');
              if(panel&&!panel.hidden&&panel.querySelectorAll('[data-theme-id]').length===5)return true;
              await new Promise(r=>setTimeout(r,20));
            }return false;})()"""), "主题卡片面板未打开")
            theme_panel_languages = {}
            for language in ("zh", "en"):
                self.evaluate(f"StudioI18n.set({json.dumps(language)})")
                theme_panel_languages[language] = self.evaluate("""(() => ({
                  cards:[...document.querySelectorAll('#studioThemePanel [data-theme-id]')].map(card=>({
                    id:card.dataset.themeId,
                    name:card.querySelector('.studio-theme-card__name')?.textContent.trim(),
                    nameZh:card.querySelector('.studio-theme-card__name')?.dataset.themeCopyZh,
                    nameEn:card.querySelector('.studio-theme-card__name')?.dataset.themeCopyEn,
                    palette:card.querySelector('.studio-theme-card__palette')?.textContent.trim(),
                    paletteZh:card.querySelector('.studio-theme-card__palette')?.dataset.themeCopyZh,
                    paletteEn:card.querySelector('.studio-theme-card__palette')?.dataset.themeCopyEn
                  })),
                  appearance:[...document.querySelectorAll('#studioThemePanel [data-theme-appearance]')].map(button=>({
                    id:button.dataset.themeAppearance,
                    text:button.textContent.trim(),
                    zh:button.dataset.themeCopyZh,
                    en:button.dataset.themeCopyEn
                  }))
                }))()""")
            self.evaluate("StudioI18n.set('zh')")
        report = self.evaluate("""(() => {
          const css = (selector, property) => {
            const el = document.querySelector(selector);
            return el ? getComputedStyle(el).getPropertyValue(property).trim() : null;
          };
          const apiSidebar = document.getElementById('hypitSettingsNav')?.closest('.sidebar')
            || document.querySelector('.layout > .sidebar');
          const apiActive = document.querySelector('#canvasModelsNav');
          const hypitActive = document.querySelector('#hypitSettingsNav');
          const create = document.querySelector('#studioNewProjectButton');
          const assetsActive = document.querySelector('#assetTabAssets');
          const assetsInactive = document.querySelector('#assetTabWorkflows');
          let media;
          if (document.getElementById('world')) {
            const node = document.createElement('div');
            node.className = 'image-node selected';
            node.innerHTML = '<div class="image-wrap"><img class="brand-regression-media" alt="safe canvas preview" src="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2216%22 height=%2216%22%3E%3Crect width=%2216%22 height=%2216%22 fill=%22%23f15b49%22/%3E%3C/svg%3E"></div>';
            document.getElementById('world').append(node);
            media = node.querySelector('img');
          } else {
            media = document.querySelector('.asset-thumb img, .preview-panel img');
          }
          const nativeFrame = document.getElementById('nativeStudio');
          const nativeMedia = nativeFrame?.contentDocument?.querySelector('.preview-panel img');
          const focusTarget = create || document.querySelector('button:not([disabled])');
          if (focusTarget) focusTarget.focus({focusVisible:true});
          const buttonBox = create ? create.getBoundingClientRect() : null;
          const focus = focusTarget ? getComputedStyle(focusTarget) : null;
          const parseColor = (value) => {
            const values=value.match(/[\\d.]+/g)?.map(Number);
            return values?.length>=3 ? [values[0],values[1],values[2],values.length>3?values[3]:1] : null;
          };
          const paintedBackground = (element) => {
            const layers=[];
            for(let node=element;node;node=node.parentElement){
              const color=parseColor(getComputedStyle(node).backgroundColor);
              if(color && color[3]>0) layers.push(color);
            }
            let result=[255,255,255,1];
            for(const [r,g,b,a] of layers.reverse()) result=[r*a+result[0]*(1-a),g*a+result[1]*(1-a),b*a+result[2]*(1-a),1];
            return `rgb(${result.slice(0,3).map(v=>Math.round(v)).join(', ')})`;
          };
          const activeStyle = (el) => {
            if (!el) return null;
            const style = getComputedStyle(el);
            const rgb = style.color.match(/[\\d.]+/g)?.map(Number) || [0,0,0];
            const background = paintedBackground(el);
            const bg = background.match(/[\\d.]+/g)?.map(Number) || [255,255,255];
            const luminance = ([r,g,b]) => {
              const linear = [r,g,b].map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; });
              return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2];
            };
            const [lighter, darker] = [luminance(rgb), luminance(bg)].sort((a,b)=>b-a);
            return {background, color:style.color, contrast:(lighter+.05)/(darker+.05)};
          };
          const activeBg = assetsActive ? getComputedStyle(assetsActive).backgroundColor : null;
          const inactiveBg = assetsInactive ? getComputedStyle(assetsInactive).backgroundColor : null;
          const resolveCssColor = (value) => {
            const probe=document.createElement('span');
            probe.style.color=value;
            document.body.append(probe);
            const resolved=getComputedStyle(probe).color;
            probe.remove();
            return resolved;
          };
          const themeCards = [...document.querySelectorAll('#studioThemePanel [data-theme-id]')].map(card => {
            const style=getComputedStyle(card);
            const preview=card.querySelector('.studio-theme-card__preview');
            const node=card.querySelector('.studio-theme-card__node');
            const previewStyle=getComputedStyle(preview);
            return {
              id:card.dataset.themeId,
              selected:card.getAttribute('aria-pressed')==='true',
              canonicalBackground:resolveCssColor(style.getPropertyValue('--studio-bg').trim()),
              canonicalAccent:resolveCssColor(style.getPropertyValue('--studio-accent').trim()),
              previewBackground:previewStyle.backgroundColor,
              previewAccent:getComputedStyle(node).backgroundColor
            };
          });
          const report = {
            title: document.title,
            preference: window.StudioTheme?.getPreference?.() || null,
            themeId: document.documentElement.dataset.studioTheme || null,
            appearance: document.documentElement.dataset.studioAppearance || null,
            appearanceMode: document.documentElement.dataset.studioAppearanceMode || null,
            registeredThemes: window.StudioTheme?.listThemes?.().map(theme=>theme.id) || [],
            themeCards,
            primaryPair: create ? activeStyle(create) : null,
            primaryColor: create ? getComputedStyle(create).color : null,
            primaryHeight: buttonBox ? buttonBox.height : null,
            focusWidth: focus ? parseFloat(focus.outlineWidth) : null,
            activeBg,
            inactiveBg,
            apiSidebar: apiSidebar ? {
              position: getComputedStyle(apiSidebar).position,
              maxHeight: getComputedStyle(apiSidebar).maxHeight,
              overflowY: getComputedStyle(apiSidebar).overflowY,
              scrolls: apiSidebar.scrollHeight > apiSidebar.clientHeight + 1
            } : null,
            apiActive: window.__brandCanvasActive || activeStyle(apiActive),
            hypitActive: window.__brandHypitActive || activeStyle(hypitActive),
            startupTitle: document.querySelector('#apiSettingsBootState .api-settings-boot-title')?.textContent?.trim() || null,
            startupSpinner: document.querySelector('#apiSettingsBootState .api-settings-boot-mark')
              ? getComputedStyle(document.querySelector('#apiSettingsBootState .api-settings-boot-mark')).display : null,
            viewportWidth: document.documentElement.clientWidth,
            pageScrollWidth: document.documentElement.scrollWidth,
            bodyScrollWidth: document.body.scrollWidth,
            bodyVisualRight: document.body.getBoundingClientRect().right,
            mediaFilter: media ? getComputedStyle(media).filter : null,
            nativeMediaFilter: nativeMedia ? getComputedStyle(nativeMedia).filter : null,
            themeDark: document.documentElement.classList.contains('studio-theme-dark')
              || document.documentElement.classList.contains('theme-dark')
          };
          media?.closest('.image-node')?.remove();
          return report;
        })()""")
        if theme_panel_languages is not None:
            report["themePanelLanguages"] = theme_panel_languages
        return report

    def test_shared_brand_theme_and_interaction_states_across_product_pages(self):
        selected_backgrounds = {theme: set() for theme in ("light", "dark")}
        card_previews = {theme_id: {} for theme_id in THEME_IDENTITIES}
        for theme_id in THEME_IDENTITIES:
            for theme in ("light", "dark"):
                widths = (1440, 390) if theme_id == "studio-violet" else (1440,)
                for width in widths:
                    for page in PAGES:
                        with self.subTest(theme_id=theme_id, theme=theme, width=width, page=page):
                            result = self.snapshot(page, theme, width, theme_id)
                            self.assertEqual(result["registeredThemes"], list(THEME_IDENTITIES), result)
                            self.assertEqual(result["preference"], {"version": 1, "themeId": theme_id, "appearance": theme}, result)
                            self.assertEqual(result["themeId"], theme_id, result)
                            self.assertEqual(result["appearance"], theme, result)
                            self.assertEqual(result["appearanceMode"], theme, result)
                        self.assertLessEqual(result["pageScrollWidth"], result["viewportWidth"] + 1, result)
                        self.assertLessEqual(result["bodyVisualRight"], result["viewportWidth"] + 1, result)
                        if page in ("canvas", "assets"):
                            self.assertEqual(result["mediaFilter"], "none", result)
                        if page == "hypit":
                            self.assertEqual(result["nativeMediaFilter"], "none", result)
                        self.assertEqual(result["themeDark"], theme == "dark", result)
                        if page == "projects":
                            self.assertIsNotNone(result["primaryPair"], result)
                            self.assertGreaterEqual(result["primaryPair"]["contrast"], 4.5, result)
                            self.assertTrue(result["primaryColor"], result)
                            self.assertGreaterEqual(result["primaryHeight"], 40, result)
                            self.assertGreaterEqual(result["focusWidth"], 2, result)
                        if page == "assets":
                            self.assertNotEqual(result["activeBg"], result["inactiveBg"], result)
                        if page == "shell":
                            cards = result["themeCards"]
                            self.assertEqual([card["id"] for card in cards], list(THEME_IDENTITIES), result)
                            self.assertTrue(any(card["selected"] and card["id"] == theme_id for card in cards), result)
                            for card in cards:
                                self.assertEqual(card["previewBackground"], card["canonicalBackground"], {"host": result, "card": card})
                                self.assertEqual(card["previewAccent"], card["canonicalAccent"], {"host": result, "card": card})
                            self.assertGreater(len({card["canonicalAccent"] for card in cards}), 1,
                                               f"{theme} 下五张卡片仍显示同一强调色: {cards}")
                            card_previews[theme_id][theme] = cards
                            labels = result["themePanelLanguages"]
                            self.assertEqual(len(labels["zh"]["cards"]), len(THEME_IDENTITIES), labels)
                            self.assertEqual(len(labels["en"]["cards"]), len(THEME_IDENTITIES), labels)
                            for language, suffix in (("zh", "Zh"), ("en", "En")):
                                for card in labels[language]["cards"]:
                                    self.assertTrue(card["name"], {"language": language, "card": card})
                                    self.assertTrue(card["palette"], {"language": language, "card": card})
                                    self.assertEqual(card["name"], card[f"name{suffix}"], {"language": language, "card": card})
                                    self.assertEqual(card["palette"], card[f"palette{suffix}"], {"language": language, "card": card})
                                for mode in labels[language]["appearance"]:
                                    self.assertEqual(mode["text"], mode[language], {"language": language, "mode": mode})
                        if page == "api":
                            self.assertIsNotNone(result["apiSidebar"], result)
                            self.assertEqual(result["apiSidebar"]["position"], "static", result)
                            self.assertEqual(result["apiSidebar"]["maxHeight"], "none", result)
                            self.assertEqual(result["apiSidebar"]["overflowY"], "visible", result)
                            self.assertGreaterEqual(result["apiActive"]["contrast"], 4.5, result)
                            self.assertGreaterEqual(result["hypitActive"]["contrast"], 4.5, result)
                            selected_backgrounds[theme].add(result["apiActive"]["background"])
        for theme, backgrounds in selected_backgrounds.items():
            self.assertGreater(len(backgrounds), 1,
                               f"{theme} 外观下各配色身份的 API 选中角色没有体现身份差异")
        for theme_id, previews in card_previews.items():
            self.assertEqual(set(previews), {"light", "dark"}, {"theme_id": theme_id, "appearances": list(previews)})
            light = next(card for card in previews["light"] if card["id"] == theme_id)
            dark = next(card for card in previews["dark"] if card["id"] == theme_id)
            self.assertNotEqual(light["previewBackground"], dark["previewBackground"],
                                f"{theme_id} 主题卡片没有随浅/深外观切换预览: {light} / {dark}")

    def test_native_hypit_theme_roles_keep_button_pair_readable_for_each_identity(self):
        probe = self.cache / "tmp" / "hypit-native-brand-probe.html"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("""<!doctype html><html><head><meta charset='utf-8'>
          <link rel='stylesheet' href='/static/css/studio-theme-palettes.css'>
          <link rel='stylesheet' href='/static/css/hypit-native-theme.css'></head>
          <body><div class='topbar'>Hypit Studio</div><button class='parameter-select-trigger'>选择</button>
          <div class='library-tab' aria-selected='true'>素材</div></body></html>""", encoding="utf-8")
        try:
            for theme_id in THEME_IDENTITIES:
                for theme in ("light", "dark"):
                    with self.subTest(theme_id=theme_id, appearance=theme):
                        self.set_viewport(1440)
                        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}/cache/studio-tests/tmp/hypit-native-brand-probe.html"})
                        self.evaluate("(async()=>{for(let i=0;i<60;i++){if(document.readyState==='complete')return true;await new Promise(r=>setTimeout(r,25));}return false;})()")
                        self.evaluate(f"""(() => {{
                          const root=document.documentElement;
                          root.dataset.studioTheme={json.dumps(theme_id)};
                          root.dataset.studioAppearance={json.dumps(theme)};
                          root.dataset.laohuThemeId={json.dumps(theme_id)};
                          root.dataset.laohuTheme={json.dumps(theme)};
                        }})()""")
                        result = self.evaluate("""(() => {
                          const luminance=(value)=>{
                            const [r,g,b]=value.match(/[\\d.]+/g).map(Number).slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2;});
                            return .2126*r+.7152*g+.0722*b;
                          };
                          const pair=(element)=>{
                            const style=getComputedStyle(element),background=style.backgroundColor;
                            const a=luminance(style.color),b=luminance(background);
                            return {foreground:style.color,background,contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
                          };
                          return {
                            identity:document.documentElement.dataset.studioTheme,
                            appearance:document.documentElement.dataset.studioAppearance,
                            app:getComputedStyle(document.documentElement).getPropertyValue('--app').trim(),
                            brand:getComputedStyle(document.documentElement).getPropertyValue('--brand-500').trim(),
                            active:pair(document.querySelector('.library-tab')),
                            button:pair(document.querySelector('button'))
                          };
                        })()""")
                        self.assertEqual(result["identity"], theme_id, result)
                        self.assertEqual(result["appearance"], theme, result)
                        self.assertGreaterEqual(result["active"]["contrast"], 4.5, result)
                        self.assertGreaterEqual(result["button"]["contrast"], 4.5, result)
        finally:
            probe.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
