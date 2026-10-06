"""主题身份、外观偏好与工作区消息同步的真实浏览器回归。"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def chrome_binary():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"), shutil.which("chromium"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    return next((item for item in candidates if item and Path(item).is_file()), None)


CHROME = chrome_binary()
NODE = shutil.which("node")


@unittest.skipUnless(CHROME and NODE, "需要本机 Chrome/Chromium 和 Node.js 执行主题浏览器回归")
class StudioThemePreferencesBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT), **kwargs)

            def log_message(self, *_args):
                pass

            def copyfile(self, source, outputfile):
                try:
                    super().copyfile(source, outputfile)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _json(self, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
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
                if path == "/theme-probe":
                    self._html("""<!doctype html><html><body><script>
                      const params=new URLSearchParams(location.search);
                      window.addEventListener('message',event=>parent.postMessage({type:'theme-probe-ack',origin:event.origin},'*'));
                      if(params.has('attack')) parent.postMessage({type:'studio-theme',theme:'dark',themeId:'vermilion',appearance:'dark'},'*');
                    </script></body></html>""")
                    return
                if path == "/api/studio/projects":
                    self._json({"projects": []})
                elif path == "/api/canvases/trash":
                    self._json({"items": []})
                elif path == "/api/providers":
                    self._json({"providers": []})
                elif path == "/api/model-capabilities":
                    self._json({"schema_version": 1, "providers": [], "options": []})
                elif path == "/api/config":
                    self._json({"api_providers": [], "comfy_instances": []})
                elif path == "/api/studio/hypit/models/capabilities":
                    self._json({"providers": [], "options": [], "supported_capabilities": [], "unsupported_capabilities": []})
                elif path == "/api/studio/hypit/models/settings":
                    self._json({"defaults": {}, "revision": 1, "parameter_mode": "per_request"})
                elif path == "/api/model-pricing":
                    self._json({"schema_version": 1, "entries": {}, "unit_definitions": {}})
                elif path == "/api/workflows":
                    self._json({"workflows": []})
                elif path == "/api/prompt-libraries":
                    self._json({"library": {"active_library_id": "system", "libraries": [{"id": "system", "items": [], "categories": []}]}})
                elif path == "/api/asset-library":
                    self._json({"library": {"libraries": []}})
                elif path == "/api/local-assets":
                    self._json({"items": [], "tree": None})
                elif path == "/api/results":
                    self._json({"items": [], "canvases": [], "counts": {}})
                elif path == "/api/shared-folders":
                    self._json({"folders": []})
                elif path == "/api/smart-canvas/personalization":
                    self._json({})
                elif path == "/api/canvases":
                    self._json({"canvases": []})
                elif path == "/api/canvases/trash":
                    self._json({"items": []})
                elif path == "/api/queue_status":
                    self._json({"total": 0, "position": 0})
                elif path == "/api/app-info":
                    self._json({"version": "test", "repo_url": ""})
                elif path.startswith("/api/"):
                    self._json({})
                else:
                    super().do_GET()

            def do_POST(self):
                self._json({})

        cls.server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        cls.http_port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.debug_port = probe.getsockname()[1]
        cls.cache = ROOT / "cache" / "studio-tests"
        cls.tmp = cls.cache / "tmp"
        cls.tmp.mkdir(parents=True, exist_ok=True)
        cls.profile = cls.tmp / f"theme-preferences-{int(time.time())}"
        cls.profile.mkdir(parents=True, exist_ok=True)
        task_tmp = ROOT / "cache" / "runtime" / "tmp"
        task_tmp.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update({"TMPDIR": str(task_tmp), "TMP": str(task_tmp), "TEMP": str(task_tmp)})
        cls.chrome = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", f"--user-data-dir={cls.profile}",
            f"--remote-debugging-port={cls.debug_port}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        cls.target = cls._wait_for_target()
        if not cls.target:
            cls.tearDownClass()
            raise unittest.SkipTest("Chrome 未能暴露隔离调试目标")
        node_script = r"""const readline=require('readline');
const ws=new WebSocket(process.argv[1]);let nextId=0;
ws.onopen=()=>process.stdout.write(JSON.stringify({ready:true})+'\n');
ws.onmessage=event=>{const message=JSON.parse(event.data);if(message.id!==undefined)
 process.stdout.write(JSON.stringify({id:message.id,result:message.result||{},error:message.error||null})+'\n');};
readline.createInterface({input:process.stdin}).on('line',line=>{
 const request=JSON.parse(line);ws.send(JSON.stringify({id:request.id||++nextId,method:request.method,params:request.params||{}}));
});"""
        cls.cdp_process = subprocess.Popen([
            NODE, "-e", node_script, cls.target["webSocketDebuggerUrl"],
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1)
        ready = json.loads(cls.cdp_process.stdout.readline() or "{}")
        if not ready.get("ready"):
            cls.tearDownClass()
            raise unittest.SkipTest("无法建立持久 CDP 会话")
        cls.request_id = 0
        cls.cdp("Page.enable")
        cls.cdp("Runtime.enable")
        cls.cdp("Page.addScriptToEvaluateOnNewDocument", {"source": r"""(() => {
          const state=window.__themeBrowserDiagnostics={errors:[],apiFetches:[]};
          const pathOf=value=>{try{return new URL(value,location.href).pathname;}catch(_){return String(value||'');}};
          addEventListener('error',event=>state.errors.push({type:'error',message:String(event.message||''),source:pathOf(event.filename||event.target?.src||''),line:Number(event.lineno||0)}));
          addEventListener('unhandledrejection',event=>{const reason=event.reason;state.errors.push({type:'unhandledrejection',message:String(reason?.stack||reason?.message||reason||'')});});
          const originalFetch=window.fetch;
          if(typeof originalFetch==='function')window.fetch=function(input,init){
            const path=pathOf(typeof input==='string'?input:input?.url||'');
            if(!path.startsWith('/api/'))return originalFetch.apply(this,arguments);
            const entry={path,state:'pending',status:null};state.apiFetches.push(entry);
            return originalFetch.apply(this,arguments).then(response=>{entry.state='complete';entry.status=response.status;return response;},error=>{entry.state='error';entry.error=String(error?.message||error);throw error;});
          };
        })();"""})

    @classmethod
    def tearDownClass(cls):
        process = getattr(cls, "cdp_process", None)
        if process:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        chrome = getattr(cls, "chrome", None)
        if chrome:
            chrome.terminate()
            try:
                chrome.wait(timeout=10)
            except subprocess.TimeoutExpired:
                chrome.kill()
        server = getattr(cls, "server", None)
        if server:
            server.shutdown()
            server.server_close()
        thread = getattr(cls, "server_thread", None)
        if thread:
            thread.join(timeout=2)
        shutil.rmtree(getattr(cls, "profile", ""), ignore_errors=True)

    @classmethod
    def _wait_for_target(cls):
        import urllib.request
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cls.debug_port}/json/list", timeout=2) as response:
                    targets = json.loads(response.read().decode("utf-8"))
                target = next((item for item in targets if item.get("type") == "page" and item.get("webSocketDebuggerUrl")), None)
                if target:
                    return target
            except Exception:
                time.sleep(.15)
        return None

    @classmethod
    def cdp(cls, method, params=None):
        cls.request_id += 1
        request_id = cls.request_id
        cls.cdp_process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params or {}}) + "\n")
        cls.cdp_process.stdin.flush()
        response = json.loads(cls.cdp_process.stdout.readline() or "{}")
        if response.get("id") != request_id or response.get("error"):
            raise AssertionError(f"CDP 调用失败：{response.get('error') or response}")
        return response.get("result", {})

    @classmethod
    def evaluate(cls, expression):
        result = cls.cdp("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if result.get("exceptionDetails"):
            raise AssertionError(f"页面脚本异常：{result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def navigate(self, path="/static/api-settings.html"):
        url = f"http://127.0.0.1:{self.http_port}{path}"
        navigation = self.cdp("Page.navigate", {"url": url})
        self.assertFalse(navigation.get("errorText"), f"主题页面导航失败：{navigation}")
        deadline = time.monotonic() + 12
        last_state = None
        while time.monotonic() < deadline:
            try:
                last_state = self.evaluate("({url:location.href,readyState:document.readyState,hasStudioTheme:!!window.StudioTheme})")
            except AssertionError:
                # 导航期间旧执行上下文会被销毁；继续轮询目标文档，不重新导航。
                time.sleep(0.05)
                continue
            if last_state and last_state.get("url") == url and last_state.get("readyState") == "complete" and last_state.get("hasStudioTheme"):
                return
            time.sleep(0.05)
        try:
            diagnostics = self.evaluate("""(() => ({
              url:location.href,readyState:document.readyState,title:document.title,
              hasStudioTheme:!!window.StudioTheme,themeType:typeof window.StudioTheme,
              themeId:document.documentElement.dataset.studioTheme||null,
              appearance:document.documentElement.dataset.studioAppearance||null,
              navigation:performance.getEntriesByType('navigation').map(item=>({name:item.name,type:item.type,domComplete:Math.round(item.domComplete),loadEventEnd:Math.round(item.loadEventEnd)})),
              scripts:performance.getEntriesByType('resource').filter(item=>item.initiatorType==='script'||item.name.split('?')[0].toLowerCase().endsWith('.js')).map(item=>({name:item.name,status:item.responseStatus,duration:Math.round(item.duration)})),
              apiResources:performance.getEntriesByType('resource').filter(item=>item.name.includes('/api/')).map(item=>({name:item.name,status:item.responseStatus,duration:Math.round(item.duration)})),
              apiFetches:window.__themeBrowserDiagnostics?.apiFetches||[],browserErrors:window.__themeBrowserDiagnostics?.errors||[]
            }))()""")
        except AssertionError as error:
            diagnostics = {"evaluationError": str(error), "lastState": last_state}
        self.fail(f"主题页面未在12秒内完成目标文档初始化：期望={url!r}，最近状态={last_state!r}，诊断={diagnostics!r}")

    def set_local_storage(self, values):
        items = json.dumps(values, ensure_ascii=False)
        return self.evaluate(f"(() => {{ localStorage.clear(); for (const [k,v] of Object.entries({items})) localStorage.setItem(k,v); return true; }})()")

    def test_legacy_mode_migrates_to_default_identity_and_bootstrap_attributes(self):
        self.navigate()
        self.set_local_storage({"studio_theme": "dark", "canvas_theme": "light"})
        self.cdp("Page.reload", {"ignoreCache": True})
        self.assertTrue(self.evaluate("(async()=>{for(let i=0;i<100;i++){if(window.StudioTheme?.getPreference)return true;await new Promise(r=>setTimeout(r,20));}return false;})()"), "偏好接口缺失，不能迁移旧主题")
        state = self.evaluate("({preference:StudioTheme.getPreference(),identity:document.documentElement.dataset.studioTheme,appearance:document.documentElement.dataset.studioAppearance,dark:document.documentElement.classList.contains('studio-theme-dark')})")
        self.assertEqual(state["preference"], {"version": 1, "themeId": "studio-violet", "appearance": "dark"}, state)
        self.assertEqual(state["identity"], "studio-violet", state)
        self.assertEqual(state["appearance"], "dark", state)
        self.assertTrue(state["dark"], state)

    def test_identity_and_appearance_persist_independently_of_manual_scale(self):
        self.navigate()
        self.assertTrue(self.evaluate("typeof StudioTheme?.setPreference === 'function'"), "缺少主题身份/外观持久化 API")
        self.evaluate("StudioTheme.setPreference({themeId:'forest',appearance:'dark'}); StudioScale.set('75')")
        self.cdp("Page.reload", {"ignoreCache": True})
        state = self.evaluate("(async()=>{for(let i=0;i<80;i++){if(window.StudioTheme?.getPreference)return {p:StudioTheme.getPreference(),scale:StudioScale.getMode(),id:document.documentElement.dataset.studioTheme,appearance:document.documentElement.dataset.studioAppearance};await new Promise(r=>setTimeout(r,20));}return null;})()")
        self.assertEqual(state["p"], {"version": 1, "themeId": "forest", "appearance": "dark"}, state)
        self.assertEqual(state["scale"], "75", state)
        self.assertEqual(state["id"], "forest", state)
        self.assertEqual(state["appearance"], "dark", state)

    def test_system_mode_reconciles_on_focus_after_emulated_media_change(self):
        registration = self.cdp("Page.addScriptToEvaluateOnNewDocument", {"source": "(() => { const original=window.matchMedia.bind(window); const prototype=Object.getPrototypeOf(original('(prefers-color-scheme: dark)')); const add=prototype.addEventListener; prototype.addEventListener=function(type,listener,options){ if(type==='change'&&this.media==='(prefers-color-scheme: dark)') window.__themeTestChangeListenerRegistered=true; return add.call(this,type,listener,options); }; window.matchMedia=query => { const list=original(query); if(query==='(prefers-color-scheme: dark)') window.__themeTestMediaQuery=list; return list; }; })();"})
        self.cdp("Emulation.setEmulatedMedia", {"media": "screen", "features": [{"name": "prefers-color-scheme", "value": "dark"}]})
        self.navigate("/static/canvas-list.html")
        self.cdp("Page.bringToFront")
        self.cdp("Page.setWebLifecycleState", {"state": "active"})
        self.evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
        self.assertTrue(self.evaluate("typeof StudioTheme?.setPreference === 'function'"), "缺少 system 外观设置 API")
        self.evaluate("StudioTheme.setPreference({themeId:'sunlit',appearance:'system'})")
        self.assertEqual(self.evaluate("StudioTheme.get()"), "dark")
        self.assertTrue(self.evaluate("document.documentElement.classList.contains('studio-theme-dark')"))
        self.assertTrue(self.evaluate("!!window.__themeTestChangeListenerRegistered"), "system 模式未向真实 MediaQueryList 注册 change 监听")
        self.evaluate("window.__themeTestSubscribedMediaQuery=window.__themeTestMediaQuery; window.__themeTestMediaChanged=false; window.__themeTestSubscribedMediaQuery.addEventListener('change',()=>window.__themeTestMediaChanged=true)")
        self.cdp("Emulation.setEmulatedMedia", {"media": "screen", "features": [{"name": "prefers-color-scheme", "value": "light"}]})
        media_changed = self.evaluate("(async()=>{for(let i=0;i<80;i++){if(!window.__themeTestSubscribedMediaQuery.matches)return {matches:false,eventObserved:window.__themeTestMediaChanged};await new Promise(r=>setTimeout(r,25));}return {matches:window.__themeTestSubscribedMediaQuery.matches,eventObserved:window.__themeTestMediaChanged};})()")
        self.assertFalse(media_changed["matches"], f"CDP 的媒体偏好未实际改变：{media_changed}")
        # Chromium headless 更新 MQL.matches，但不总是发出 change。焦点恢复是独立的生产兜底路径。
        self.evaluate("window.dispatchEvent(new Event('focus'))")
        changed = self.evaluate("({theme:StudioTheme.get(),darkClass:document.documentElement.classList.contains('studio-theme-dark'),mode:document.documentElement.dataset.studioAppearanceMode,appearance:document.documentElement.dataset.studioAppearance,eventObserved:window.__themeTestMediaChanged})")
        self.assertEqual(changed, {"theme":"light","darkClass":False,"mode":"system","appearance":"light","eventObserved":media_changed["eventObserved"]}, changed)
        state = self.evaluate("({preference:StudioTheme.getPreference(),mode:document.documentElement.dataset.studioAppearanceMode,appearance:document.documentElement.dataset.studioAppearance})")
        self.assertEqual(state, {"preference": {"version": 1, "themeId": "sunlit", "appearance": "system"}, "mode": "system", "appearance": "light"})
        if registration.get("identifier"):
            self.cdp("Page.removeScriptToEvaluateOnNewDocument", {"identifier": registration["identifier"]})

    def test_shell_picker_applies_theme_and_syncs_only_to_same_origin_frame(self):
        self.navigate("/static/index.html")
        self.assertTrue(self.evaluate("typeof window.syncThemeToFrame === 'function'"), "工作台主题同步入口缺失")
        self.assertTrue(self.evaluate("!!document.getElementById('theme-toggle-btn') && !!document.getElementById('studioThemePanel')"), "工作台主题选择面板缺失")
        self.evaluate("document.getElementById('theme-toggle-btn').click()")
        state = self.evaluate("({open:!document.getElementById('studioThemePanel').hidden,cards:document.querySelectorAll('#studioThemePanel [data-theme-id]').length,modes:document.querySelectorAll('#studioThemePanel [data-theme-appearance]').length})")
        self.assertEqual(state, {"open": True, "cards": 5, "modes": 2}, state)
        self.assertFalse(self.evaluate("!!document.querySelector('#studioThemePanel [data-theme-appearance=system]')"),
                         "面板仅提供浅色与深色；旧 system 偏好仍由主题底层兼容读取")
        self.evaluate("document.querySelector('#studioThemePanel [data-theme-id=forest]').click()")
        self.evaluate("document.querySelector('#studioThemePanel [data-theme-appearance=dark]').click()")
        preference = self.evaluate("StudioTheme.getPreference()")
        self.assertEqual(preference, {"version": 1, "themeId": "forest", "appearance": "dark"}, preference)
        self.assertFalse(self.evaluate("!!document.getElementById('studioThemeUndo')"), "主题面板不应提供撤销入口")
        same_origin = self.evaluate(f"""(async()=>{{
          const frame=document.createElement('iframe');frame.id='themeSameOriginFrame';
          frame.src='/static/canvas-list.html?theme-message-test=1';document.body.append(frame);
          for(let i=0;i<160;i++){{if(frame.contentWindow?.StudioTheme?.getPreference)break;await new Promise(r=>setTimeout(r,25));}}
          if(!frame.contentWindow?.StudioTheme?.getPreference)return null;
          window.__sameOriginThemeMessage=null;
          frame.contentWindow.addEventListener('message',event=>window.__sameOriginThemeMessage=event.data);
          syncThemeToFrame(frame);
          for(let i=0;i<80;i++){{if(window.__sameOriginThemeMessage)break;await new Promise(r=>setTimeout(r,20));}}
          return {{message:window.__sameOriginThemeMessage,id:frame.contentDocument.documentElement.dataset.studioTheme,
            appearance:frame.contentDocument.documentElement.dataset.studioAppearance}};
        }})()""")
        self.assertIsNotNone(same_origin, "同源工作区 iframe 未加载")
        self.assertEqual(same_origin["message"]["themeId"], "forest", same_origin)
        self.assertEqual(same_origin["message"]["appearance"], "dark", same_origin)
        self.assertEqual(same_origin["id"], "forest", same_origin)
        self.assertIn(same_origin["appearance"], ("light", "dark"), same_origin)
        cross_origin = self.evaluate(f"""(async()=>{{
          window.__themeProbeAcks=0;
          window.addEventListener('message',event=>{{if(event.data?.type==='theme-probe-ack')window.__themeProbeAcks++;}});
          const frame=document.createElement('iframe');
          const loaded=new Promise(resolve=>frame.addEventListener('load',resolve,{{once:true}}));
          frame.src='http://127.0.0.2:{self.http_port}/theme-probe';document.body.append(frame);
          await Promise.race([loaded,new Promise(resolve=>setTimeout(resolve,1500))]);
          syncThemeToFrame(frame);
          await new Promise(resolve=>setTimeout(resolve,200));
          return window.__themeProbeAcks;
        }})()""")
        self.assertEqual(cross_origin, 0, "主题偏好不应广播到跨源 iframe")
        host_before = self.evaluate("StudioTheme.getPreference()")
        self.evaluate(f"""(() => {{const attack=document.createElement('iframe');
          attack.src='http://127.0.0.2:{self.http_port}/theme-probe?attack=1';document.body.append(attack);}})()""")
        self.evaluate("new Promise(resolve=>setTimeout(resolve,120))")
        self.assertEqual(self.evaluate("StudioTheme.getPreference()"), host_before, "跨源 iframe 伪造主题消息不应修改宿主偏好")
        self.evaluate("StudioI18n.set('en')")
        english = self.evaluate("({title:document.getElementById('studioThemePanelTitle').textContent,card:document.querySelector('#studioThemePanel [data-theme-id=forest] .studio-theme-card__name').textContent,palette:document.querySelector('#studioThemePanel [data-theme-id=forest] .studio-theme-card__palette').textContent,close:document.getElementById('studioThemePanelClose').getAttribute('aria-label'),modes:[...document.querySelectorAll('[data-theme-appearance]')].map(node=>node.textContent),group:document.querySelector('.studio-theme-panel__appearance').dataset.label})")
        self.assertEqual(english, {"title":"Choose a theme","card":"Forest Workshop","palette":"Sage · forest green · wheat","close":"Close theme panel","modes":["Light","Dark"],"group":"Appearance"}, english)

    def test_project_list_header_keeps_heading_actions_together_and_preserves_controls(self):
        for page in ("/static/canvas-list.html", "/static/hypit-list.html"):
            with self.subTest(page=page):
                self.navigate(page)
                structure = self.evaluate("""(() => ({
                  top:!!document.querySelector('.studio-project-toolbar-top'),
                  heading:!!document.querySelector('.studio-project-toolbar-top .studio-project-toolbar-heading'),
                  actions:!!document.querySelector('.studio-project-toolbar-top .studio-project-toolbar-actions'),
                  sameGroup:document.querySelector('.studio-project-toolbar-heading')?.parentElement===document.querySelector('.studio-project-toolbar-actions')?.parentElement,
                  search:!!document.getElementById('studioProjectSearch'),
                  create:!!document.getElementById('studioNewProjectButton'),
                  art:!!document.querySelector('.studio-project-toolbar-art'),
                  separateActions:!!document.querySelector('.studio-project-toolbar-bottom .studio-project-toolbar-actions'),
                  import:!!document.getElementById('studioImportGuide'),
                  trash:!!document.getElementById('studioTrashButton'),
                  prepare:!!document.getElementById('studioPrepareButton')
                }))()""")
                expected = {
                    "top": True, "heading": True, "actions": True, "sameGroup": True,
                    "search": True, "create": True, "art": False, "separateActions": False,
                    "import": page.endswith("canvas-list.html"),
                    "trash": page.endswith("canvas-list.html"),
                    "prepare": True,
                }
                self.assertEqual(structure, expected, structure)


if __name__ == "__main__":
    unittest.main()
