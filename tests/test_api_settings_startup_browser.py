"""API 设置首屏启动状态回归；使用隔离 HTTP 桩，不读取或写入用户配置。"""
from __future__ import annotations

import json
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
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    return next((item for item in candidates if item and Path(item).is_file()), None)


CHROME = chrome_binary()
NODE = shutil.which("node")


class ApiState:
    def __init__(self):
        self.lock = threading.Lock()
        self.mode = "delay"
        self.delay = 1.4
        self.provider_calls = 0
        self.fetch_model_calls = 0
        self.provider_put_calls = 0
        self.providers_payload = []
        self.saved_providers = []
        self.model_payload = {"all": [], "image_models": [], "chat_models": [], "video_models": [], "audio_models": [], "total": 0}
        self.provider_put_delay = 0
        self.provider_put_started = threading.Event()
        self.provider_put_finished = threading.Event()
        self.provider_started = threading.Event()

    def reset(self, mode="delay", delay=1.4, providers=None, models=None, provider_put_delay=0):
        with self.lock:
            self.mode = mode
            self.delay = delay
            self.provider_calls = 0
            self.fetch_model_calls = 0
            self.provider_put_calls = 0
            self.providers_payload = json.loads(json.dumps(providers or []))
            self.saved_providers = json.loads(json.dumps(self.providers_payload))
            self.model_payload = json.loads(json.dumps(models or {"all": [], "image_models": [], "chat_models": [], "video_models": [], "audio_models": [], "total": 0}))
            self.provider_put_delay = provider_put_delay
            self.provider_put_started.clear()
            self.provider_put_finished.clear()
            self.provider_started.clear()


class ApiSettingsStartupBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CHROME or not NODE:
            raise unittest.SkipTest("需要本机 Chrome/Chromium 和 Node.js 执行浏览器回归")
        cls.state = ApiState()

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
                self.wfile.write(body)

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/api/model-capabilities":
                    self._json(200, {"providers": []})
                    return
                if path == "/api/providers":
                    with cls.state.lock:
                        cls.state.provider_calls += 1
                        call = cls.state.provider_calls
                        mode = cls.state.mode
                        delay = cls.state.delay
                        providers = json.loads(json.dumps(cls.state.providers_payload))
                    cls.state.provider_started.set()
                    if mode == "fail-first" and call == 1:
                        self._json(503, {"detail": "isolated test failure"})
                        return
                    if mode == "delay":
                        time.sleep(delay)
                    elif mode == "fail-first":
                        time.sleep(0.15)
                    self._json(200, {"providers": providers})
                    return
                super().do_GET()

            def do_POST(self):
                path = urlsplit(self.path).path
                if path == "/api/providers/fetch-models":
                    self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    with cls.state.lock:
                        cls.state.fetch_model_calls += 1
                        models = json.loads(json.dumps(cls.state.model_payload))
                    self._json(200, models)
                    return
                self._json(404, {"detail": "not found in isolated fixture"})

            def do_PUT(self):
                path = urlsplit(self.path).path
                if path == "/api/providers":
                    try:
                        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"[]")
                    except Exception:
                        self._json(400, {"detail": "invalid fixture payload"})
                        return
                    with cls.state.lock:
                        cls.state.provider_put_calls += 1
                        cls.state.saved_providers = json.loads(json.dumps(payload))
                        delay = cls.state.provider_put_delay
                    cls.state.provider_put_started.set()
                    if delay:
                        time.sleep(delay)
                    self._json(200, {"providers": payload})
                    cls.state.provider_put_finished.set()
                    return
                self._json(404, {"detail": "not found in isolated fixture"})

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.http_port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.debug_port = probe.getsockname()[1]
        cls.profile = ROOT / "cache" / "studio-tests" / "tmp" / f"api-settings-startup-{int(time.time())}"
        cls.profile.mkdir(parents=True, exist_ok=True)
        cls.chrome = subprocess.Popen(
            [
                CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", f"--user-data-dir={cls.profile}",
                f"--remote-debugging-port={cls.debug_port}", "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.target = cls._wait_for_target()
        if not cls.target:
            cls.tearDownClass()
            raise unittest.SkipTest("Chrome 未能暴露调试目标")
        cls.cdp("Page.enable")
        cls.cdp("Runtime.enable")

    @classmethod
    def tearDownClass(cls):
        try:
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
        script = """(async()=>{
          const ws=new WebSocket(process.argv[1]);
          await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
          const id=1;
          ws.onmessage=event=>{const message=JSON.parse(event.data);if(message.id!==id)return;
            console.log(JSON.stringify(message.result||message.error||{}));ws.close();};
          ws.send(JSON.stringify({id,method:process.argv[2],params:JSON.parse(process.argv[3]||'{}')}));
        })().catch(error=>{console.error(String(error));process.exit(2);});"""
        result = subprocess.run(
            [NODE, "-e", script, cls.target["webSocketDebuggerUrl"], method, json.dumps(params or {})],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode:
            raise AssertionError(f"CDP 调用失败：{result.stderr[:400]}")
        return json.loads(result.stdout or "{}")

    @classmethod
    def evaluate(cls, expression):
        result = cls.cdp("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        })
        if result.get("exceptionDetails"):
            raise AssertionError(f"页面断言脚本异常：{result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def open_page(self, lang="zh", theme="light", *, mode="delay", delay=1.4, providers=None, models=None, provider_put_delay=0):
        self.state.reset(mode, delay, providers, models, provider_put_delay)
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}/"})
        self.assertEqual(self.evaluate(f"""(async()=>{{
          for(let i=0;i<100;i++){{
            if(location.origin==='http://127.0.0.1:{self.http_port}'){{
              localStorage.clear();
              localStorage.setItem('studio_theme_preference_v1',JSON.stringify({{version:1,themeId:'studio-violet',appearance:{json.dumps(theme)}}}));
              localStorage.setItem('studio_theme',{json.dumps(theme)});
              localStorage.setItem('studio_lang',{json.dumps(lang)});
              return true;
            }}
            await new Promise(resolve=>setTimeout(resolve,20));
          }}
          return false;
        }})()"""), True, "测试页源站未就绪，无法隔离设置主题和语言")
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}/static/api-settings.html?lang={lang}&theme={theme}"})
        self.assertTrue(self.state.provider_started.wait(10), "页面没有请求平台配置")

    def wait_for_state(self, state):
        return self.evaluate(f"""(async()=>{{
          for(let i=0;i<100;i++){{
            if(document.getElementById('settingsContent')?.dataset.apiStartup==='{state}') return true;
            await new Promise(resolve=>setTimeout(resolve,50));
          }}
          return false;
        }})()""")

    def test_first_frame_shell_keeps_language_and_theme_during_slow_read(self):
        for lang in ("zh", "en"):
            for theme in ("light", "dark"):
                with self.subTest(lang=lang, theme=theme):
                    self.open_page(lang, theme)
                    first = self.evaluate("""(() => {
                      const visible = selector => getComputedStyle(document.querySelector(selector)).display !== 'none';
                      return {
                        lang: document.documentElement.lang,
                        storedLang: localStorage.getItem('studio_lang'),
                        storedTheme: localStorage.getItem('studio_theme'),
                        startup: document.getElementById('settingsContent').dataset.apiStartup,
                        ariaBusy: document.getElementById('settingsContent').getAttribute('aria-busy'),
                        providerHidden: document.getElementById('providerSettingsView').hidden,
                        headingHidden: document.querySelector('.content-head').hidden,
                        credentialVisible: getComputedStyle(document.getElementById('keyInput')).display !== 'none'
                          && !document.getElementById('keyInput').closest('#providerSettingsView').hidden,
                        dark: document.documentElement.classList.contains('studio-theme-dark')
                          && document.body.classList.contains('studio-theme-dark'),
                        zhVisible: visible('.api-settings-boot-title .api-settings-boot-zh'),
                        enVisible: visible('.api-settings-boot-title .api-settings-boot-en')
                      };
                    })()""")
                    self.assertEqual(first["startup"], "loading", first)
                    self.assertEqual(first["ariaBusy"], "true", first)
                    self.assertTrue(first["providerHidden"], first)
                    self.assertTrue(first["headingHidden"], first)
                    self.assertFalse(first["credentialVisible"], first)
                    self.assertEqual(first["dark"], theme == "dark", first)
                    self.assertEqual(first["zhVisible"], lang == "zh", first)
                    self.assertEqual(first["enVisible"], lang == "en", first)
                    self.assertTrue(self.wait_for_state("empty"), "慢请求完成后应进入中性空平台状态")
                    final = self.evaluate("""(() => ({
                      state: document.getElementById('settingsContent').dataset.apiStartup,
                      busy: document.getElementById('settingsContent').getAttribute('aria-busy'),
                      emptyVisible: !document.querySelector('.api-settings-boot-empty').hidden,
                      title: document.querySelector('.api-settings-boot-title')?.innerText.trim() || '',
                      spinnerDisplay: getComputedStyle(document.querySelector('.api-settings-boot-mark')).display,
                      retryVisible: !document.getElementById('apiSettingsBootRetry').hidden,
                      dark: document.documentElement.classList.contains('studio-theme-dark')
                        && document.body.classList.contains('studio-theme-dark')
                    }))()""")
                    self.assertEqual(final["state"], "empty", final)
                    self.assertEqual(final["busy"], "false", final)
                    self.assertTrue(final["emptyVisible"], final)
                    self.assertEqual(final["title"], "API 设置已读取" if lang == "zh" else "API settings loaded", final)
                    self.assertEqual(final["spinnerDisplay"], "none", final)
                    self.assertFalse(final["retryVisible"], final)
                    self.assertEqual(final["dark"], theme == "dark", final)

    def test_empty_state_can_open_canvas_models(self):
        self.open_page()
        self.assertTrue(self.wait_for_state("empty"))
        result = self.evaluate("""(() => {
          document.getElementById('canvasModelsNav').click();
          return {
            startup: document.getElementById('settingsContent').dataset.apiStartup || '',
            bootHidden: document.getElementById('apiSettingsBootState').hidden,
            canvasHidden: document.getElementById('canvasModelSettingsBlock').hidden,
            title: document.getElementById('editorTitle').textContent
          };
        })()""")
        self.assertEqual(result["startup"], "", result)
        self.assertTrue(result["bootHidden"], result)
        self.assertFalse(result["canvasHidden"], result)
        self.assertTrue(result["title"], result)

    def test_model_selection_does_not_rebuild_or_reset_the_open_catalog_list(self):
        model_ids = [f"fixture-image-{index:03d}" for index in range(100)]
        provider = {
            "id": "fixture-openai", "name": "Fixture API", "protocol": "openai",
            "base_url": "https://fixture.invalid/v1", "enabled": True,
            "image_models": [], "chat_models": [], "video_models": [], "audio_models": [],
            "model_names": {}, "model_protocols": {}
        }
        model_response = {
            "all": model_ids, "image_models": model_ids, "chat_models": [], "video_models": [],
            "audio_models": [], "model_names": {}, "model_availability": {}, "total": len(model_ids)
        }
        self.open_page(mode="ready", providers=[provider], models=model_response, provider_put_delay=0.8)
        self.assertTrue(self.evaluate("""(async()=>{for(let i=0;i<100;i++){
          const settings=document.getElementById('settingsContent');
          if(settings && !settings.hasAttribute('data-api-startup') && document.getElementById('providerList')?.textContent.includes('Fixture API')) return true;
          await new Promise(resolve=>setTimeout(resolve,30));
        }return false;})()"""), "隔离平台配置应加载完成")
        self.evaluate("document.getElementById('canvasModelsNav').click()")
        self.evaluate("document.getElementById('fetchModelsBtn').click()")
        picker_open = self.evaluate("""(async()=>{for(let i=0;i<100;i++){
          const overlay=document.getElementById('modelPickerOverlay');
          if(overlay && getComputedStyle(overlay).display!=='none' && document.querySelectorAll('#pickerList .picker-row').length===100) return true;
          await new Promise(resolve=>setTimeout(resolve,30));
        }return false;})()""")
        self.assertTrue(picker_open, {"fetchCalls":self.state.fetch_model_calls, **self.evaluate("""(() => ({
          status:document.getElementById('status')?.textContent,
          modelRows:document.querySelectorAll('#pickerList .picker-row').length,
          overlayDisplay:getComputedStyle(document.getElementById('modelPickerOverlay')).display
        }))()""")})
        before = self.evaluate("""(() => {
          const list=document.getElementById('pickerList');
          const row=[...list.querySelectorAll('.picker-row')].find(item=>item.textContent.includes('fixture-image-060'));
          if(!row) throw new Error('fixture model row was not rendered');
          row.scrollIntoView({block:'center'});
          return {scrollTop:list.scrollTop, rowText:row.textContent, rowId:row.getAttribute('data-model-id'), rowIndex:[...list.children].indexOf(row)};
        })()""")
        self.assertGreater(before["scrollTop"], 0, before)
        self.evaluate(f"""(() => {{
          const list=document.getElementById('pickerList');
          const row=list.children[{before['rowIndex']}];
          window.__pickerRowBeforeRefresh=row;
          row.click();
        }})()""")
        self.assertTrue(self.state.provider_put_started.wait(5), "勾选后应进入隔离的配置 PUT")
        self.assertTrue(self.evaluate("""(async()=>{for(let i=0;i<100;i++){
          if(window.__pickerRowBeforeRefresh && document.querySelector('#pickerList .picker-row.has-sel')) return true;
          await new Promise(resolve=>setTimeout(resolve,25));
        }return false;})()"""), "模型勾选后应进入本地自动保存链")
        self.evaluate("""(() => {
          window.__modelListRowBeforeSaveResponse=document.getElementById('imageModelList')?.firstElementChild || null;
        })()""")
        self.assertTrue(self.state.provider_put_finished.wait(5), "隔离自动保存应返回模拟成功响应")
        result = self.evaluate("""(() => {
          const list=document.getElementById('pickerList');
          const row=window.__pickerRowBeforeRefresh;
          return {
            overlayOpen:getComputedStyle(document.getElementById('modelPickerOverlay')).display!=='none',
            sameRow:!!row && row.isConnected && row===list.children[[...list.children].findIndex(item=>item.textContent===row.textContent)],
            selected:!!row?.classList.contains('has-sel'),
            checked:!!row?.querySelector('.picker-checkbox')?.classList.contains('checked'),
            modelListRowPreserved:!!window.__modelListRowBeforeSaveResponse
              && window.__modelListRowBeforeSaveResponse===document.getElementById('imageModelList')?.firstElementChild,
            scrollTop:list.scrollTop,
            providerGetCalls:window.__fixtureProviderGetCalls || null,
            fetchCount:document.getElementById('pickerCount')?.textContent || ''
          };
        })()""")
        self.assertTrue(result["overlayOpen"], result)
        self.assertTrue(result["sameRow"], result)
        self.assertTrue(result["selected"], result)
        self.assertTrue(result["checked"], result)
        self.assertTrue(result["modelListRowPreserved"], result)
        self.assertEqual(result["scrollTop"], before["scrollTop"], result)
        flushed = self.evaluate("""(() => {
          const previous=window.__modelListRowBeforeSaveResponse;
          closeModelPicker();
          const current=document.getElementById('imageModelList')?.firstElementChild || null;
          return {
            overlayClosed:getComputedStyle(document.getElementById('modelPickerOverlay')).display==='none',
            editorRefreshApplied:!!previous && !!current && previous!==current,
            enabledModelVisible:[...(document.getElementById('imageModelList')?.querySelectorAll('input') || [])]
              .some(input=>input.value==='fixture-image-060')
          };
        })()""")
        self.assertTrue(flushed["overlayClosed"], flushed)
        self.assertTrue(flushed["editorRefreshApplied"], flushed)
        self.assertTrue(flushed["enabledModelVisible"], flushed)
        self.assertTrue(self.state.provider_started.is_set())
        self.assertEqual(self.state.provider_calls, 1, "浏览目录时不应重新拉取平台配置")
        self.assertEqual(self.state.fetch_model_calls, 1, "只有显式点击拉取才请求上游模型目录")
        self.assertGreaterEqual(self.state.provider_put_calls, 1, "显式勾选仍需经真实 autosave PUT")
        saved = next(item for item in self.state.saved_providers if item.get("id") == "fixture-openai")
        self.assertIn("fixture-image-060", saved.get("image_models", []), "只有用户勾选才进入启用白名单")

    def test_failed_read_shows_retry_then_empty_state(self):
        self.state.reset("fail-first", 0.15)
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}/"})
        self.assertTrue(self.evaluate(f"""(async()=>{{
          for(let i=0;i<100;i++){{
            if(location.origin==='http://127.0.0.1:{self.http_port}'){{
              localStorage.clear();
              localStorage.setItem('studio_theme_preference_v1',JSON.stringify({{version:1,themeId:'studio-violet',appearance:'dark'}}));
              localStorage.setItem('studio_theme','dark');
              localStorage.setItem('studio_lang','en');
              return true;
            }}
            await new Promise(resolve=>setTimeout(resolve,20));
          }}
          return false;
        }})()"""), "测试页源站未就绪")
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}/static/api-settings.html?lang=en&theme=dark"})
        self.assertTrue(self.state.provider_started.wait(10), "页面没有请求平台配置")
        self.assertTrue(self.wait_for_state("error"), "失败时应显示可操作错误状态")
        failure = self.evaluate("""(() => ({
          errorVisible: !document.querySelector('.api-settings-boot-error').hidden,
          retryVisible: !document.getElementById('apiSettingsBootRetry').hidden,
          title: document.querySelector('.api-settings-boot-title')?.innerText.trim() || '',
          credentialVisible: getComputedStyle(document.getElementById('keyInput')).display !== 'none'
            && !document.getElementById('keyInput').closest('#providerSettingsView').hidden,
          dark: document.documentElement.classList.contains('studio-theme-dark')
            && document.body.classList.contains('studio-theme-dark')
        }))()""")
        self.assertTrue(failure["errorVisible"], failure)
        self.assertTrue(failure["retryVisible"], failure)
        self.assertEqual(failure["title"], "Could not read API settings")
        self.assertFalse(failure["credentialVisible"], failure)
        self.assertTrue(failure["dark"], failure)
        self.evaluate("document.getElementById('apiSettingsBootRetry').click()")
        self.assertTrue(self.state.provider_started.wait(10), "重试没有再次请求平台配置")
        self.assertTrue(self.wait_for_state("empty"), "重试成功的空列表应进入中性空状态")
        self.assertEqual(self.state.provider_calls, 2)
        final = self.evaluate("""(() => ({
          title: document.querySelector('.api-settings-boot-title')?.innerText.trim() || '',
          spinnerDisplay: getComputedStyle(document.querySelector('.api-settings-boot-mark')).display
        }))()""")
        self.assertEqual(final["title"], "API settings loaded", final)
        self.assertEqual(final["spinnerDisplay"], "none", final)


if __name__ == "__main__":
    unittest.main()
