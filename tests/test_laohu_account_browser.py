"""Isolated browser coverage for the laohu account panel and the existing API-key editor."""
from __future__ import annotations

import base64
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

from studio_laohu_account import _callback_response


ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / ".cache" / "validation" / "laohu-account-implementation"
TEMP = VALIDATION / "tmp"
CHROME = next((path for path in (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
) if path.is_file()), None) or (Path(shutil.which("google-chrome")) if shutil.which("google-chrome") else None)
NODE = shutil.which("node")


def provider_payload():
    common = {
        "enabled": True,
        "image_models": [],
        "chat_models": ["chat-fixture"],
        "video_models": [],
        "audio_models": [],
        "music_models": [],
        "model_names": {},
        "model_protocols": {},
        "has_key": False,
        "key_preview": "",
        "api_key": "",
    }
    laohu = {**common, "id": "ai-money", "name": "laohu", "base_url": "https://api.lao-hu.com", "protocol": "openai"}
    alpha = {**common, "id": "alpha", "name": "Alpha", "base_url": "https://alpha.example", "protocol": "openai", "chat_models": []}
    return [laohu, alpha]


class FixtureState:
    def __init__(self):
        self.lock = threading.Lock()
        self.providers = provider_payload()
        self.saved_providers = provider_payload()
        self.put_calls = []
        self.model_calls = []
        self.events = []
        self.put_status_code = 200
        self.put_delay_seconds = 0
        self.put_request_count = 0
        self.manual_mode_code = 200
        self.refresh_code = 200
        self.refresh_status_after = None
        self.status_code = 200
        self.status_payload = self.manual_status()
        self.login_code = 503
        self.login_payload = {"detail": "OAuth client is not configured"}
        self.flow_payload = {"status": "pending"}
        self.flow_sequence = None
        self.flow_calls = 0
        self.flow_delay_seconds = 0
        self.status_after_flow = None
        self.mutations = []
        self.delete_calls = []
        self.provider_get_calls = 0
        self.status_get_calls = 0
        self.provider_started = threading.Event()
        self.put_started = threading.Event()

    @staticmethod
    def manual_status(**overrides):
        result = {
            "mode": "manual",
            "connected": False,
            "login_available": False,
            "login_unavailable_reason": "登录服务尚未接入，请先使用手动 Key",
            "account": None,
            "links": {
                "console": "https://api.lao-hu.com/keys",
                "wallet": "https://api.lao-hu.com/wallet",
                "usage": "https://api.lao-hu.com/usage-logs",
            },
            "has_manual_key": False,
            "active_credential": {"kind": "none", "configured": False, "label": "", "preview": ""},
        }
        result.update(overrides)
        if "active_credential" not in overrides:
            if result.get("mode") == "account" and result.get("connected") is True and result.get("model_authorized") is not False:
                result["active_credential"] = {"kind":"account", "configured":True, "label":"登录自动配置", "preview":"PRIVATE-OAUTH-TOKEN-MUST-NOT-APPEAR"}
            elif result.get("mode") == "manual" and result.get("has_manual_key") is True:
                result["active_credential"] = {"kind":"manual", "configured":True, "label":"手动 API Key", "preview":"••••••••key1"}
        return result

    def reset(self, *, status_code=200, status=None, login_code=503, login_payload=None, flow_payload=None, put_status_code=200, put_delay_seconds=0, manual_mode_code=200, refresh_code=200, refresh_status_after=None, provider_has_key=False, flow_sequence=None, flow_delay_seconds=0, status_after_flow=None):
        with self.lock:
            self.providers = provider_payload()
            self.saved_providers = provider_payload()
            if provider_has_key:
                for providers in (self.providers, self.saved_providers):
                    item = next(candidate for candidate in providers if candidate["id"] == "ai-money")
                    item["has_key"] = True
                    item["key_preview"] = "fixture…key"
            self.put_calls = []
            self.model_calls = []
            self.events = []
            self.put_status_code = put_status_code
            self.put_delay_seconds = float(put_delay_seconds)
            self.put_request_count = 0
            self.manual_mode_code = manual_mode_code
            self.refresh_code = refresh_code
            self.refresh_status_after = json.loads(json.dumps(refresh_status_after)) if refresh_status_after is not None else None
            self.status_code = status_code
            self.status_payload = json.loads(json.dumps(status if status is not None else self.manual_status()))
            self.login_code = login_code
            self.login_payload = json.loads(json.dumps(login_payload if login_payload is not None else {"detail": "OAuth client is not configured"}))
            self.flow_payload = json.loads(json.dumps(flow_payload if flow_payload is not None else {"status": "pending"}))
            self.flow_sequence = json.loads(json.dumps(flow_sequence)) if flow_sequence is not None else None
            self.flow_calls = 0
            self.flow_delay_seconds = float(flow_delay_seconds)
            self.status_after_flow = json.loads(json.dumps(status_after_flow)) if status_after_flow is not None else None
            self.mutations = []
            self.delete_calls = []
            self.provider_get_calls = 0
            self.status_get_calls = 0
            self.provider_started.clear()
            self.put_started.clear()


class LaohuAccountBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CHROME or not NODE:
            raise unittest.SkipTest("需要本机 Chrome/Chromium 和 Node.js 执行隔离浏览器验收")
        VALIDATION.mkdir(parents=True, exist_ok=True)
        TEMP.mkdir(parents=True, exist_ok=True)
        cls.state = FixtureState()

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT), **kwargs)

            def log_message(self, *_args):
                pass

            def _json(self, code, payload):
                body = json.dumps(payload).encode("utf-8")
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _read_json(self):
                try:
                    return json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                except Exception:
                    return {}

            def do_GET(self):
                path = urlsplit(self.path).path
                callback_paths = {
                    "/__isolated__/callback-close-allowed": True,
                    "/__isolated__/callback-close-denied": False,
                }
                if path in callback_paths:
                    response = _callback_response(close_allowed=callback_paths[path])
                    body = response.body
                    self.send_response(response.status_code)
                    for key, value in response.headers.items():
                        if key.lower() != "content-length":
                            self.send_header(key, value)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/api/providers":
                    with cls.state.lock:
                        payload = json.loads(json.dumps(cls.state.providers))
                        cls.state.provider_get_calls += 1
                    cls.state.provider_started.set()
                    self._json(200, {"providers": payload})
                    return
                if path == "/api/model-capabilities":
                    self._json(200, {"providers": []})
                    return
                if path == "/api/laohu/account/status":
                    with cls.state.lock:
                        code = cls.state.status_code
                        payload = json.loads(json.dumps(cls.state.status_payload))
                        cls.state.status_get_calls += 1
                    self._json(code, payload)
                    return
                if path.startswith("/api/laohu/account/login/"):
                    with cls.state.lock:
                        index = cls.state.flow_calls
                        cls.state.flow_calls += 1
                        sequence = cls.state.flow_sequence
                        payload = json.loads(json.dumps(sequence[min(index, len(sequence) - 1)] if sequence else cls.state.flow_payload))
                        delay = cls.state.flow_delay_seconds
                        status_after_flow = json.loads(json.dumps(cls.state.status_after_flow)) if cls.state.status_after_flow is not None else None
                    if delay:
                        time.sleep(delay)
                    if payload.get("status") == "succeeded" and status_after_flow is not None:
                        with cls.state.lock:
                            cls.state.status_payload = status_after_flow
                    self._json(200, payload)
                    return
                super().do_GET()

            def do_POST(self):
                path = urlsplit(self.path).path
                body = self._read_json()
                if path == "/api/providers/fetch-models":
                    with cls.state.lock:
                        cls.state.model_calls.append(json.loads(json.dumps(body)))
                    self._json(200, {"image_models": [], "chat_models": ["chat-fixture"], "video_models": [], "audio_models": [], "all": ["chat-fixture"]})
                    return
                if path.startswith("/api/laohu/account/"):
                    with cls.state.lock:
                        cls.state.mutations.append({"path": path, "body": body, "action": self.headers.get("X-Laohu-Account-Action")})
                        cls.state.events.append({"method": "POST", "path": path})
                        if path == "/api/laohu/account/login":
                            code = cls.state.login_code
                            payload = json.loads(json.dumps(cls.state.login_payload))
                        elif path == "/api/laohu/account/refresh":
                            code = cls.state.refresh_code
                            if cls.state.refresh_status_after is not None:
                                cls.state.status_payload = json.loads(json.dumps(cls.state.refresh_status_after))
                            payload = json.loads(json.dumps(cls.state.status_payload)) if code < 400 else {"detail": "Account refresh failed"}
                        elif path == "/api/laohu/account/mode" and body.get("mode") == "account":
                            if cls.state.status_payload.get("connected") is True:
                                code = 200
                                payload = json.loads(json.dumps(cls.state.status_payload))
                                payload["mode"] = "account"
                                cls.state.status_payload = json.loads(json.dumps(payload))
                            else:
                                code, payload = 409, {"detail": "Account mode is unavailable"}
                        elif path == "/api/laohu/account/mode" and body.get("mode") == "manual":
                            code = cls.state.manual_mode_code
                            if code >= 400:
                                payload = {"detail": "Manual mode activation failed"}
                            else:
                                payload = json.loads(json.dumps(cls.state.status_payload))
                                payload["mode"] = "manual"
                                payload["has_manual_key"] = True
                                payload["active_credential"] = {"kind":"manual", "configured":True, "label":"手动 API Key", "preview":"••••••••key1"}
                                cls.state.status_payload = json.loads(json.dumps(payload))
                        else:
                            code, payload = 200, cls.state.manual_status()
                    self._json(code, payload)
                    return
                self._json(404, {"detail": "fixture route not found"})

            def do_PUT(self):
                if urlsplit(self.path).path != "/api/providers":
                    self._json(404, {"detail": "fixture route not found"})
                    return
                body = self._read_json()
                with cls.state.lock:
                    delay = cls.state.put_delay_seconds
                    cls.state.put_request_count += 1
                cls.state.put_started.set()
                if delay:
                    time.sleep(delay)
                with cls.state.lock:
                    cls.state.put_calls.append(json.loads(json.dumps(body)))
                    cls.state.events.append({"method": "PUT", "path": "/api/providers"})
                    code = cls.state.put_status_code
                    if code >= 400:
                        response_providers = None
                    else:
                        previous_by_id = {item.get("id"): item for item in cls.state.saved_providers}
                        response_providers = []
                        for requested in body:
                            saved_item = json.loads(json.dumps(previous_by_id.get(requested.get("id"), {})))
                            saved_item.update(json.loads(json.dumps(requested)))
                            if requested.get("clear_key") is True:
                                saved_item.pop("api_key", None)
                            response_providers.append(saved_item)
                        cls.state.saved_providers = json.loads(json.dumps(response_providers))
                        laohu = next((item for item in body if item.get("id") == "ai-money"), {})
                        if laohu.get("clear_key") is True:
                            cls.state.status_payload["has_manual_key"] = False
                        elif laohu.get("api_key"):
                            cls.state.status_payload["has_manual_key"] = True
                            if cls.state.status_payload.get("mode") == "manual":
                                cls.state.status_payload["active_credential"] = {"kind":"manual", "configured":True, "label":"手动 API Key", "preview":"••••••••key1"}
                if code >= 400:
                    self._json(code, {"detail": "fixture provider save failed"})
                    return
                for item in response_providers:
                    if item.get("clear_key"):
                        item["has_key"] = False
                        item["key_preview"] = ""
                    elif item.get("api_key"):
                        item["has_key"] = True
                        item["key_preview"] = "fixture…key"
                    item.pop("api_key", None)
                    item.pop("clear_key", None)
                with cls.state.lock:
                    cls.state.providers = json.loads(json.dumps(response_providers))
                self._json(200, {"providers": response_providers})

            def do_DELETE(self):
                with cls.state.lock:
                    cls.state.delete_calls.append(urlsplit(self.path).path)
                self._json(405, {"detail": "DELETE is not supported by this fixture"})

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.http_port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.debug_port = probe.getsockname()[1]
        cls.profile = TEMP / f"laohu-account-chrome-{int(time.time())}"
        env = dict(os.environ)
        env["TMPDIR"] = str(TEMP)
        cls.chrome = subprocess.Popen([
            str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--no-sandbox", f"--user-data-dir={cls.profile}",
            f"--remote-debugging-port={cls.debug_port}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
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
        for _ in range(60):
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
        result = subprocess.run([NODE, "-e", script, cls.target["webSocketDebuggerUrl"], method, json.dumps(params or {})],
                                capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise AssertionError(f"CDP 调用失败：{result.stderr[:400]}")
        return json.loads(result.stdout or "{}")

    @classmethod
    def cdp_session(cls, commands):
        script = """(async()=>{
          const ws=new WebSocket(process.argv[1]);
          await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
          let nextId=0;
          const send=(method,params)=>new Promise((resolve,reject)=>{
            const id=++nextId;
            const onMessage=event=>{const msg=JSON.parse(event.data);if(msg.id!==id)return;ws.removeEventListener('message',onMessage);if(msg.error)reject(msg.error);else resolve(msg.result||{});};
            ws.addEventListener('message',onMessage);
            ws.send(JSON.stringify({id,method,params:params||{}}));
          });
          const commands=JSON.parse(process.argv[2]);
          const results=[];
          for(const command of commands){results.push(await send(command.method,command.params));await new Promise(resolve=>setTimeout(resolve,120));}
          console.log(JSON.stringify(results));ws.close();
        })().catch(error=>{console.error(String(error));process.exit(2);});"""
        result = subprocess.run([NODE, "-e", script, cls.target["webSocketDebuggerUrl"], json.dumps(commands)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(f"CDP session failed: {result.stderr[:500]}")
        return json.loads(result.stdout or "[]")

    def evaluate_with_user_gesture(self, expression):
        result = self.cdp("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
            "userGesture": True,
        })
        if result.get("exceptionDetails"):
            raise AssertionError(f"页面脚本异常：{result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    @classmethod
    def evaluate(cls, expression):
        result = cls.cdp("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if result.get("exceptionDetails"):
            raise AssertionError(f"页面脚本异常：{result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def open_page(self, *, lang="zh", status_code=200, status=None, login_code=503, login_payload=None, flow_payload=None, put_status_code=200, put_delay_seconds=0, manual_mode_code=200, refresh_code=200, refresh_status_after=None, provider_has_key=False, flow_sequence=None, flow_delay_seconds=0, status_after_flow=None):
        self.state.reset(status_code=status_code, status=status, login_code=login_code, login_payload=login_payload, flow_payload=flow_payload, put_status_code=put_status_code, put_delay_seconds=put_delay_seconds, manual_mode_code=manual_mode_code, refresh_code=refresh_code, refresh_status_after=refresh_status_after, provider_has_key=provider_has_key, flow_sequence=flow_sequence, flow_delay_seconds=flow_delay_seconds, status_after_flow=status_after_flow)
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}/"})
        ready = self.evaluate(f"""(async()=>{{
          for(let i=0;i<100;i++){{if(location.origin==='http://127.0.0.1:{self.http_port}'){{
            localStorage.clear();
            localStorage.setItem('studio_theme_preference_v1',JSON.stringify({{version:1,themeId:'studio-violet',appearance:'light'}}));
            localStorage.setItem('studio_theme','light');localStorage.setItem('studio_lang',{json.dumps(lang)});return true;
          }}await new Promise(resolve=>setTimeout(resolve,20));}}return false;
        }})()""")
        self.assertTrue(ready, "测试源站未就绪")
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}/static/api-settings.html?lang={lang}&theme=light"})
        self.assertTrue(self.state.provider_started.wait(10), "页面没有读取平台配置")
        loaded = self.evaluate("""(async()=>{for(let i=0;i<200;i++){
          if(!document.getElementById('settingsContent')?.hasAttribute('data-api-startup')&&document.getElementById('settingsContent')?.getAttribute('aria-busy')==='false') return true;
          await new Promise(resolve=>setTimeout(resolve,40));}return false;})()""")
        if not loaded:
            diagnostic = self.evaluate("({url:location.href,title:document.title,startup:document.getElementById('settingsContent')?.dataset.apiStartup,boot:document.querySelector('.api-settings-boot')?.textContent.slice(0,240),laohu:document.getElementById('laohuAccountConnection')?.textContent})")
            self.fail(f"API 设置首屏没有完成读取：{diagnostic}")
        self.evaluate("""(async()=>{for(let i=0;i<100;i++){
          const card=document.getElementById('laohuAccountCard');
          if(card&&!card.hidden&&document.getElementById('laohuAccountConnection')?.dataset.state!=='loading') return true;
          await new Promise(resolve=>setTimeout(resolve,30));}return false;})()""")
        self.evaluate("setApiSettingsSection('connections');selectProvider('ai-money')")
        self.wait_for("!document.getElementById('providerSettingsView').hidden && !document.getElementById('laohuAccountCard').hidden", "laohu 平台连接卡片没有进入可见状态")

    def wait_for(self, expression, message="页面条件未满足"):
        result = self.evaluate(f"""(async()=>{{for(let i=0;i<120;i++){{if({expression})return true;await new Promise(resolve=>setTimeout(resolve,50));}}return false;}})()""")
        self.assertTrue(result, message)

    def wait_for_saved_key(self, value):
        self.wait_for_saved_provider_key("ai-money", value)

    def wait_for_saved_provider_key(self, provider_id, value):
        for _ in range(120):
            with self.state.lock:
                saved = next((item for item in self.state.saved_providers if item.get("id") == provider_id), {})
                if saved.get("api_key") == value:
                    return
            time.sleep(0.05)
        self.fail(f"{provider_id} API Key 未按预期保存")

    def wait_for_model_call_count(self, count):
        deadline = time.time() + 10
        while time.time() < deadline:
            with self.state.lock:
                if len(self.state.model_calls) >= count:
                    return
            time.sleep(0.05)
        self.fail(f"模型请求数量未达到 {count}")

    def wait_for_put_requests(self, count):
        deadline = time.time() + 10
        while time.time() < deadline:
            with self.state.lock:
                if self.state.put_request_count >= count:
                    return
            time.sleep(0.05)
        self.fail(f"PUT 请求启动数未达到 {count}")

    def wait_for_flow_calls(self, count):
        deadline = time.time() + 10
        while time.time() < deadline:
            with self.state.lock:
                if self.state.flow_calls >= count:
                    return
            time.sleep(0.05)
        self.fail(f"登录流程轮询次数未达到 {count}")

    def screenshot(self, width, height, name, *, dark=False, advanced=False):
        setup = (
            "window.StudioTheme?.apply('" + ("dark" if dark else "light") + "');"
            + ("beginLaohuKeyEdit();" if advanced else "")
        )
        measure = """(() => {
          const title=document.getElementById('laohuAccountTitle');
          const key=document.getElementById('keyInput');
          const card=document.getElementById('laohuAccountCard');
          const usage=document.getElementById('laohuAccountUsage');
          const consoleLink=document.getElementById('laohuAccountConsole');
          const rgb=c=>c.match(/[\\d.]+/g).slice(0,3).map(v=>{v=Number(v)/255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});
          const contrast=(a,b)=>{const x=rgb(a),y=rgb(b),L=c=>.2126*c[0]+.7152*c[1]+.0722*c[2],u=L(x),v=L(y);return (Math.max(u,v)+.05)/(Math.min(u,v)+.05);};
          const bg=getComputedStyle(card).backgroundColor;
          return {
            width:innerWidth,height:innerHeight,docWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,
            title:title.textContent,titleRect:title.getBoundingClientRect().toJSON(),keyVisible:Boolean(key.getClientRects().length),
            keyValue:key.value,keyType:key.type,keyReadOnly:key.readOnly,keyHint:document.getElementById('keyHint').textContent,
            keyPlaceholder:key.placeholder,keyWidth:key.getBoundingClientRect().width,
            keyLabel:document.querySelector('.api-key-label').textContent,clearText:document.querySelector('.laohu-key-clear').textContent.trim(),
            saveText:document.getElementById('laohuSaveKeyButton').textContent.trim(),saveVisible:Boolean(document.getElementById('laohuSaveKeyButton').getClientRects().length),
            cancelVisible:Boolean(document.getElementById('laohuCancelKeyButton').getClientRects().length),
            headWrap:getComputedStyle(document.querySelector('.laohu-account-head')).flexWrap,message:document.getElementById('laohuAccountModeMessage').textContent,
            balance:document.getElementById('laohuAccountBalance').textContent,balanceLabel:document.querySelector('.laohu-account-balance > span').textContent,
            signInVisible:Boolean(document.getElementById('laohuAccountSignIn').getClientRects().length),
            consoleVisible:Boolean(consoleLink.getClientRects().length),usageVisible:Boolean(usage.getClientRects().length),
            cardBackground:bg,usageColor:getComputedStyle(usage).color,consoleColor:getComputedStyle(consoleLink).color,
            usageContrast:contrast(getComputedStyle(usage).color,bg),consoleContrast:contrast(getComputedStyle(consoleLink).color,bg),
            connectionVisible:Boolean(document.getElementById('laohuAccountConnection').getClientRects().length),
            accountDescriptionVisible:Boolean(document.querySelector('.laohu-account-desc')),
            canvasContextVisible:Boolean(document.querySelector('.canvas-models-context').getClientRects().length),
            modelsDescriptionVisible:Boolean(document.querySelector('#modelsHead [data-i18n="api.modelsDesc"]').getClientRects().length),
            purposeDescriptionCount:Array.from(document.querySelectorAll('.model-grid > .canvas-model-category > .block-head .block-desc')).filter(el=>el.getClientRects().length).length,
            modelsTitleRect:document.querySelector('#modelsHead .block-title').getBoundingClientRect().toJSON(),
            hasExternalCredentialPreview:Boolean(document.getElementById('laohuCredentialPreview'))
          };
        })()"""
        results = self.cdp_session([
            {"method": "Emulation.setDeviceMetricsOverride", "params": {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False}},
            {"method": "Runtime.evaluate", "params": {"expression": setup + "document.getElementById('laohuAccountCard').scrollIntoView({block:'start'});", "returnByValue": True}},
            {"method": "Runtime.evaluate", "params": {"expression": "new Promise(resolve=>setTimeout(resolve,220))", "awaitPromise": True}},
            {"method": "Runtime.evaluate", "params": {"expression": measure, "returnByValue": True}},
            {"method": "Page.captureScreenshot", "params": {"format": "png", "captureBeyondViewport": False}},
        ])
        path = VALIDATION / name
        path.write_bytes(base64.b64decode(results[4]["data"]))
        return path, results[3].get("result", {}).get("value")

    def open_advanced_settings(self):
        self.evaluate("beginLaohuKeyEdit()")
        self.wait_for("document.getElementById('keyInput').type==='password' && document.getElementById('keyInput').readOnly===false", "API Key 编辑态没有打开")

    def test_status_404_is_an_error_and_card_has_no_fake_account_controls(self):
        self.open_page(status_code=404, status={"detail": "account routes not found"})
        self.assertEqual(self.evaluate("document.getElementById('laohuAccountConnection').dataset.state"), "error")
        self.assertEqual(self.evaluate("document.getElementById('laohuAccountConnection').textContent"), "暂时无法连接，请稍后重试。")
        self.assertTrue(self.evaluate("document.getElementById('laohuAccountCard').hidden === false"))
        self.assertTrue(self.evaluate("document.getElementById('laohuAccountLogin').hidden"))
        self.assertTrue(self.evaluate("document.getElementById('laohuAccountRefresh').hidden"))
        self.assertTrue(self.evaluate("!document.getElementById('laohuAccountModeSwitch') && !document.getElementById('laohuAccountModeBadge')"))
        self.assertTrue(self.evaluate("document.getElementById('laohuAccountProfile').hidden"))

    def test_links_and_manual_key_use_fixed_targets_and_one_explicit_save_input(self):
        hostile = FixtureState.manual_status(links={
            "console": "https://evil.example/keys", "wallet": "http://api.lao-hu.com/wallet", "usage": "https://api.lao-hu.com/elsewhere",
        })
        self.open_page(status=hostile)
        snapshot = self.evaluate("""(() => ({
          cardVisible:!document.getElementById('laohuAccountCard').hidden,
          loginHidden:document.getElementById('laohuAccountLogin').hidden,
          refreshHidden:document.getElementById('laohuAccountRefresh').hidden,
          profileHidden:document.getElementById('laohuAccountProfile').hidden,
          balance:document.getElementById('laohuAccountBalance').textContent,
          keyCount:document.querySelectorAll('#keyInput').length,
          keyParent:document.getElementById('keyInput').closest('.api-key-field').parentElement.id,
          keyVisible:Boolean(document.getElementById('keyInput').getClientRects().length),
          keyType:document.getElementById('keyInput').type,
          keyReadOnly:document.getElementById('keyInput').readOnly,
          keyValue:document.getElementById('keyInput').value,
          keyHint:document.getElementById('keyHint').textContent,
          updateText:document.getElementById('laohuSaveKeyButton').textContent.trim(),
          cancelHidden:document.getElementById('laohuCancelKeyButton').hidden,
          consoleVisible:Boolean(document.getElementById('laohuAccountConsole').getClientRects().length),
          signInVisible:Boolean(document.getElementById('laohuAccountSignIn').getClientRects().length),
          modeControlsPresent:Boolean(document.getElementById('laohuAccountModeBadge')||document.getElementById('laohuAccountModeSwitch')),
          keyLabel:document.querySelector('.api-key-label').textContent,
          clearHidden:document.querySelector('.laohu-key-clear').hidden,
          saveButtonExists:Boolean(document.getElementById('laohuSaveKeyButton')),
          links:['laohuAccountConsole','laohuAccountWallet','laohuAccountUsage'].map(id=>document.getElementById(id).href)
        }))()""")
        self.assertEqual(snapshot["cardVisible"], True)
        self.assertEqual(snapshot["loginHidden"], True)
        self.assertEqual(snapshot["refreshHidden"], True)
        self.assertEqual(snapshot["profileHidden"], True)
        self.assertEqual(snapshot["balance"], "")
        self.assertEqual(snapshot["keyCount"], 1)
        self.assertEqual(snapshot["keyParent"], "laohuManualKeySlot")
        self.assertFalse(snapshot["modeControlsPresent"])
        self.assertEqual(snapshot["keyLabel"], "API Key")
        self.assertTrue(snapshot["clearHidden"], "laohu 不再提供清除 Key 操作")
        self.assertEqual(snapshot["keyValue"], "未配置")
        self.assertEqual(snapshot["keyType"], "text")
        self.assertTrue(snapshot["keyReadOnly"])
        self.assertEqual(snapshot["keyHint"], "未配置")
        self.assertEqual(snapshot["updateText"], "更新")
        self.assertTrue(snapshot["cancelHidden"])
        self.assertTrue(snapshot["saveButtonExists"])
        self.assertTrue(snapshot["keyVisible"])
        self.assertTrue(snapshot["consoleVisible"])
        self.assertFalse(snapshot["signInVisible"])
        self.assertEqual(snapshot["links"], [
            "https://api.lao-hu.com/keys", "https://api.lao-hu.com/wallet", "https://api.lao-hu.com/usage-logs",
        ])

        saved_element = self.evaluate("window.__testKeyElement=document.getElementById('keyInput'); true")
        self.assertTrue(saved_element)
        self.evaluate("""(() => {const links=['laohuAccountSignIn','laohuAccountSignUp','laohuAccountConsole','laohuAccountWallet','laohuAccountUsage'];
          window.__clickedAccountLinks=[];links.forEach(id=>{const a=document.getElementById(id);a.addEventListener('click',e=>{e.preventDefault();window.__clickedAccountLinks.push(a.href);},{once:true});a.click();});})()""")
        clicked = self.evaluate("window.__clickedAccountLinks")
        self.assertEqual(clicked, [
            "https://api.lao-hu.com/sign-in", "https://api.lao-hu.com/sign-up?aff=460d", *snapshot["links"],
        ], "account links only open fixed laohu website pages")

        self.evaluate("document.getElementById('keyInput').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}))")
        time.sleep(0.1)
        with self.state.lock:
            self.assertEqual(self.state.events, [], "只读显示态按 Enter 不能提交")
        self.open_advanced_settings()
        self.assertEqual(self.evaluate("document.getElementById('keyInput').value"), "", "点击更新后应清空同一输入框")
        self.assertEqual(self.evaluate("document.getElementById('keyHint').textContent"), "未保存", "编辑态的空白输入不能继续标成已加载")
        self.assertEqual(self.evaluate("document.getElementById('laohuSaveKeyButton').textContent.trim()"), "保存")
        self.evaluate("""(() => {const input=document.getElementById('keyInput');input.value='fixture-manual-key';input.dispatchEvent(new Event('input',{bubbles:true}));})()""")
        self.evaluate("document.getElementById('keyInput').blur()")
        time.sleep(0.5)
        with self.state.lock:
            writes = len(self.state.put_calls)
            events_before_save = list(self.state.events)
        self.assertEqual(writes, 0, "输入和失焦均不得自动保存 laohu Key")
        self.assertEqual(events_before_save, [], "保存前不得发送 PUT 或 mode 请求")

        self.evaluate("selectProvider('alpha')")
        self.wait_for("document.getElementById('laohuAccountCard').hidden", "切换其他平台后账户卡片仍显示")
        self.assertTrue(self.evaluate("document.getElementById('keyInput')===window.__testKeyElement"))
        self.assertTrue(self.evaluate("Boolean(document.getElementById('keyInput').closest('#providerSettingsView'))"))
        self.evaluate("const input=document.getElementById('keyInput');input.value='alpha-key';input.dispatchEvent(new Event('input',{bubbles:true}))")
        self.wait_for_saved_provider_key("alpha", "alpha-key")
        with self.state.lock:
            alpha_autosave = json.loads(json.dumps(self.state.put_calls[-1]))
        laohu_autosave_item = next(item for item in alpha_autosave if item.get("id") == "ai-money")
        self.assertNotIn("api_key", laohu_autosave_item, "其他平台自动保存快照不能带 laohu 草稿")
        self.assertFalse(laohu_autosave_item.get("clear_key"), "其他平台自动保存不得清理当前 laohu Key")
        self.evaluate("selectProvider('ai-money')")
        self.wait_for("!document.getElementById('laohuAccountCard').hidden", "切回 laohu 后账户卡片没有显示")
        self.assertTrue(self.evaluate("document.getElementById('keyInput')===window.__testKeyElement"))
        self.assertEqual(self.evaluate("document.getElementById('keyInput').value"), "fixture-manual-key", "未提交的草稿在平台切换后保留")
        self.evaluate("fetchModels()")
        self.wait_for_model_call_count(1)
        with self.state.lock:
            model_payloads = json.loads(json.dumps(self.state.model_calls))
        self.assertEqual(model_payloads[-1].get("provider_id"), "ai-money")
        self.assertEqual(model_payloads[-1].get("api_key"), "", "模型操作必须使用服务端当前凭据，不能读取未提交草稿")
        self.evaluate("document.getElementById('laohuSaveKeyButton').click()")
        self.wait_for("window.LaohuAccount.getStatus()?.mode==='manual' && document.getElementById('keyInput').readOnly && document.getElementById('keyInput').value==='••••••••key1'", "显式保存后没有显示当前 API Key 遮罩")
        self.assertEqual(self.evaluate("document.getElementById('keyHint').textContent"), "已保存并启用")
        with self.state.lock:
            saved = json.loads(json.dumps(self.state.saved_providers))
            writes = json.loads(json.dumps(self.state.put_calls))
            events = list(self.state.events)
            mutations = json.loads(json.dumps(self.state.mutations))
        self.assertEqual(next(item for item in saved if item["id"] == "ai-money")["api_key"], "fixture-manual-key")
        self.assertEqual(writes[-1][next(i for i, item in enumerate(writes[-1]) if item.get("id") == "ai-money")]["api_key"], "fixture-manual-key")
        self.assertEqual([event["method"] for event in events[-2:]], ["PUT", "POST"], "显式保存先 PUT Key，再 POST mode manual")
        self.assertEqual(mutations[-1]["body"], {"mode":"manual"})
        self.assertEqual(mutations[-1]["action"], "1")
        self.assertTrue(self.evaluate("Boolean(document.getElementById('canvasModelSettingsBlock')&&document.getElementById('imageModelList')&&document.getElementById('chatModelList'))"))

    def test_laohu_hides_basic_info_but_other_provider_keeps_it(self):
        self.open_page()
        laohu = self.evaluate("""(() => ({
          section:document.querySelector('.connection-details').getClientRects().length,
          heading:document.querySelector('.connection-details > .block-head').getClientRects().length,
          name:document.querySelector('.connection-details .platform-name-field').getClientRects().length,
          url:document.querySelector('.connection-details .api-base-url-field').getClientRects().length,
          verify:document.querySelector('.connection-details .verify-action-row').getClientRects().length,
          key:document.getElementById('keyInput').getClientRects().length,
          context:document.querySelector('.canvas-models-context').getClientRects().length,
          modelsDescription:document.querySelector('#modelsHead [data-i18n="api.modelsDesc"]').getClientRects().length,
          purposeDescriptions:Array.from(document.querySelectorAll('.model-grid > .canvas-model-category > .block-head .block-desc')).filter(el=>el.getClientRects().length).length
        }))()""")
        self.assertEqual(laohu["section"], 0)
        self.assertEqual(laohu["heading"], 0)
        self.assertEqual(laohu["name"], 0)
        self.assertEqual(laohu["url"], 0)
        self.assertEqual(laohu["verify"], 0)
        self.assertGreater(laohu["key"], 0, "只读凭据输入框在 laohu 卡片中常显")
        self.assertEqual(laohu["context"], 0, "laohu 没有站点选项时隐藏空上下文栏")
        self.assertEqual(laohu["modelsDescription"], 0, "laohu 隐藏启用清单说明")
        self.assertEqual(laohu["purposeDescriptions"], 0, "laohu 隐藏固定用途说明，保留模型本身信息")
        self.evaluate("selectProvider('alpha')")
        self.wait_for("document.getElementById('laohuAccountCard').hidden", "切换其他平台后账户卡片仍显示")
        other = self.evaluate("""(() => ({
          heading:document.querySelector('.connection-details > .block-head').getClientRects().length,
          name:document.querySelector('.connection-details .platform-name-field').getClientRects().length,
          url:document.querySelector('.connection-details .api-base-url-field').getClientRects().length,
          verify:document.querySelector('.connection-details .verify-action-row').getClientRects().length,
          clearHidden:document.querySelector('.laohu-key-clear').hidden,
          context:document.querySelector('.canvas-models-context').getClientRects().length,
          modelsDescription:document.querySelector('#modelsHead [data-i18n="api.modelsDesc"]').getClientRects().length,
          purposeDescriptions:Array.from(document.querySelectorAll('.model-grid > .canvas-model-category > .block-head .block-desc')).filter(el=>el.getClientRects().length).length
        }))()""")
        self.assertTrue(all(other[key] > 0 for key in ("heading", "name", "url", "verify")), f"其他平台基本信息应保持可见：{other}")
        self.assertFalse(other["clearHidden"], "切到其他平台时要恢复通用 Key 清除入口")
        self.assertGreater(other["context"], 0, "其他供应商仍显示模型上下文说明")
        self.assertGreater(other["modelsDescription"], 0, "其他供应商仍显示模型目录说明")
        self.assertGreater(other["purposeDescriptions"], 0, "其他供应商仍显示用途说明")

    def test_laohu_has_no_clear_key_action_and_unsaved_draft_never_calls_clear_or_delete(self):
        self.open_page()
        self.open_advanced_settings()
        self.evaluate("""(() => {const input=document.getElementById('keyInput');input.value='local-only-draft';input.dispatchEvent(new Event('input',{bubbles:true}));clearKeyOnly();})()""")
        time.sleep(0.25)
        with self.state.lock:
            writes = json.loads(json.dumps(self.state.put_calls))
            delete_calls = list(self.state.delete_calls)
            account_mutations = list(self.state.mutations)
        self.assertEqual(writes, [], "laohu 不提供清除按钮，草稿不能生成清除 PUT")
        self.assertEqual(delete_calls, [], "清除本地 Key 不应调用远程 DELETE")
        self.assertEqual(account_mutations, [], "不能对账户接口发清除请求")
        self.assertEqual(self.evaluate("document.getElementById('keyInput').value"), "local-only-draft")

    def test_bilingual_layout_fits_narrow_viewport_and_saves_screenshots(self):
        status = FixtureState.manual_status(
            connected=True,
            mode="account",
            login_available=False,
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=True,
            model_authorized=True,
            execution_ready=True,
        )
        self.open_page(lang="zh", status=status, provider_has_key=True)
        wide, wide_metrics = self.screenshot(1440, 520, "laohu-account-wide-default.png")
        self.assertTrue(wide.is_file())
        self.assertEqual(wide_metrics["width"], 1440)
        narrow, metrics = self.screenshot(390, 560, "laohu-account-390-default.png")
        self.assertTrue(narrow.is_file())
        self.assertEqual(metrics["width"], 390)
        self.assertLessEqual(metrics["docWidth"], metrics["width"], f"document horizontal overflow: {metrics}")
        self.assertLessEqual(metrics["bodyWidth"], metrics["width"], f"body horizontal overflow: {metrics}")
        self.assertEqual(metrics["title"], "laohu 账户")
        self.assertEqual(metrics["message"], "正在使用登录账户，可直接调用模型。")
        self.assertEqual(metrics["balance"], "¥19.35")
        self.assertEqual(metrics["balanceLabel"], "登录账户余额")
        self.assertTrue(metrics["keyVisible"], "当前凭据必须在同一个输入框内常显")
        self.assertEqual(metrics["keyValue"], "••••••••", "账户凭据只显示固定安全遮罩")
        self.assertEqual(metrics["keyType"], "text")
        self.assertTrue(metrics["keyReadOnly"])
        self.assertEqual(metrics["keyHint"], "已自动加载")
        self.assertEqual(metrics["saveText"], "更新")
        self.assertFalse(metrics["cancelVisible"])
        self.assertEqual(metrics["keyLabel"], "API Key")
        self.assertFalse(metrics["hasExternalCredentialPreview"], "遮罩只出现于唯一的 Key 输入框")
        self.assertFalse(metrics["signInVisible"])
        self.assertTrue(metrics["consoleVisible"])
        self.assertTrue(metrics["usageVisible"])
        self.assertEqual(metrics["purposeDescriptionCount"], 0, "laohu 不显示重复的模型用途说明")
        self.assertGreater(metrics["modelsTitleRect"]["width"], 50, f"窄屏模型列表标题不能缩成竖排：{metrics['modelsTitleRect']}")
        self.assertLess(metrics["modelsTitleRect"]["height"], 24, f"窄屏模型列表标题保持单行：{metrics['modelsTitleRect']}")
        dark, dark_metrics = self.screenshot(390, 640, "laohu-account-390-dark-edit.png", dark=True, advanced=True)
        advanced, advanced_metrics = self.screenshot(390, 640, "laohu-account-390-light-edit.png", dark=False, advanced=True)
        self.assertTrue(dark.is_file() and advanced.is_file())
        self.assertEqual(dark_metrics["width"], 390)
        self.assertTrue(dark_metrics["keyVisible"] and dark_metrics["consoleVisible"])
        self.assertEqual(dark_metrics["keyValue"], "", "编辑态不能把遮罩复制进输入值")
        self.assertEqual(dark_metrics["keyType"], "password")
        self.assertFalse(dark_metrics["keyReadOnly"])
        self.assertEqual(dark_metrics["keyHint"], "未保存")
        self.assertEqual(dark_metrics["saveText"], "保存")
        self.assertTrue(dark_metrics["cancelVisible"])
        self.assertGreaterEqual(dark_metrics["usageContrast"], 4.5, f"dark usage link contrast below 4.5:1: {dark_metrics}")
        self.assertGreaterEqual(dark_metrics["consoleContrast"], 4.5, f"dark developer-console link contrast below 4.5:1: {dark_metrics}")
        self.assertTrue(advanced_metrics["keyVisible"])
        self.assertTrue(advanced_metrics["consoleVisible"])
        self.assertEqual(advanced_metrics["keyHint"], "未保存")
        self.assertLessEqual(dark_metrics["docWidth"], 390, f"dark narrow document overflow: {dark_metrics}")
        self.assertLessEqual(advanced_metrics["docWidth"], 390, f"edit narrow document overflow: {advanced_metrics}")
        narrow375 = self.cdp_session([
            {"method": "Emulation.setDeviceMetricsOverride", "params": {"width": 375, "height": 812, "deviceScaleFactor": 1, "mobile": False}},
            {"method": "Runtime.evaluate", "params": {"expression": "({width:innerWidth,docWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,titleRect:document.querySelector('#modelsHead .block-title').getBoundingClientRect().toJSON()})", "returnByValue": True}},
        ])[1].get("result", {}).get("value")
        self.assertLessEqual(narrow375["docWidth"], 375, f"375px document horizontal overflow: {narrow375}")
        self.assertLessEqual(narrow375["bodyWidth"], 375, f"375px body horizontal overflow: {narrow375}")
        self.assertGreater(narrow375["titleRect"]["width"], 50, f"375px 标题不能竖排：{narrow375}")
        self.assertLess(narrow375["titleRect"]["height"], 24, f"375px 标题保持单行：{narrow375}")
        self.evaluate("window.StudioI18n.set('en')")
        english = self.evaluate("({title:document.getElementById('laohuAccountTitle').textContent, saveText:document.getElementById('laohuSaveKeyButton').textContent.trim(), keyHint:document.getElementById('keyHint').textContent, keyType:document.getElementById('keyInput').type, keyReadOnly:document.getElementById('keyInput').readOnly})")
        self.assertEqual(english["title"], "laohu Account")
        self.assertEqual(english["saveText"], "Save")
        self.assertEqual(english["keyHint"], "Not saved")
        self.assertEqual(english["keyType"], "password")
        self.assertFalse(english["keyReadOnly"])
        self.evaluate("cancelLaohuKeyEdit()")
        self.assertEqual(self.evaluate("document.getElementById('laohuSaveKeyButton').textContent.trim()"), "Update")
        self.assertEqual(self.evaluate("document.getElementById('keyHint').textContent"), "Loaded automatically")
        self.assertIn("Using the signed-in account", self.evaluate("document.getElementById('laohuAccountModeMessage').textContent"))
        self.evaluate("window.StudioI18n.set('zh')")
        self.assertEqual(self.evaluate("document.getElementById('laohuAccountTitle').textContent"), "laohu 账户")

        manual = FixtureState.manual_status(
            connected=True,
            mode="manual",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=True,
            model_authorized=False,
            execution_ready=False,
            active_credential={"kind":"manual", "configured":True, "label":"手动 API Key", "preview":"••••••••ABCD"},
        )
        self.open_page(lang="zh", status=manual, provider_has_key=True)
        manual_path, manual_metrics = self.screenshot(390, 560, "laohu-account-390-manual-default.png")
        self.assertTrue(manual_path.is_file())
        self.assertEqual(manual_metrics["keyValue"], "••••••••ABCD", "手动 Key 尾四位必须显示在输入框中")
        self.assertEqual(manual_metrics["keyHint"], "已保存并启用")
        self.assertEqual(manual_metrics["keyType"], "text")
        self.assertTrue(manual_metrics["keyReadOnly"])
        self.assertFalse(manual_metrics["hasExternalCredentialPreview"])
        self.assertGreaterEqual(manual_metrics["keyWidth"], 100, f"手动 Key 掩码尾号应在窄屏有足够输入框宽度：{manual_metrics}")
        self.assertLessEqual(manual_metrics["docWidth"], 390, f"manual Key narrow document overflow: {manual_metrics}")

    def test_login_unavailable_does_not_start_a_flow_or_discard_manual_key_draft(self):
        self.open_page()
        self.open_advanced_settings()
        login_state = self.evaluate("({hidden:document.getElementById('laohuAccountLogin').hidden,available:window.LaohuAccount.getStatus()?.login_available,connected:window.LaohuAccount.getStatus()?.connected})")
        self.assertEqual(login_state, {"hidden": True, "available": False, "connected": False})
        self.evaluate("""window.__popupOpenCount=0;window.open=()=>{window.__popupOpenCount++;return null;};
          const input=document.getElementById('keyInput');input.value='draft-survives-unavailable-login';input.dispatchEvent(new Event('input',{bubbles:true}));window.LaohuAccount.login();""")
        self.assertEqual(self.evaluate("document.getElementById('keyInput').value"), "draft-survives-unavailable-login")
        self.assertEqual(self.evaluate("window.__popupOpenCount"), 0, "服务器未确认登录可用时不打开窗口")
        with self.state.lock:
            self.assertFalse(any(call["path"] == "/api/laohu/account/login" for call in self.state.mutations))
        self.assertIn("账户登录尚未接入", self.evaluate("document.getElementById('laohuAccountMessage').textContent"))
        time.sleep(0.25)
        with self.state.lock:
            self.assertEqual(self.state.put_calls, [], "登录失败或输入草稿不能触发 Key 保存")
        self.assertEqual(self.evaluate("document.getElementById('keyInput').value"), "draft-survives-unavailable-login")

    def test_login_control_only_appears_when_backend_marks_it_available(self):
        self.open_page(status=FixtureState.manual_status(login_available=True, login_unavailable_reason=""))
        login = self.evaluate("({hidden:document.getElementById('laohuAccountLogin').hidden,disabled:document.getElementById('laohuAccountLogin').disabled,connected:window.LaohuAccount.getStatus()?.connected})")
        self.assertEqual(login, {"hidden": False, "disabled": False, "connected": False})
        self.assertTrue(self.evaluate("document.getElementById('laohuAccountLogin').classList.contains('primary-btn')"))
        self.assertFalse(self.evaluate("document.getElementById('laohuAccountWallet').classList.contains('primary-btn')"), "登录按钮可用时，充值链接作为次要动作显示")
        self.assertTrue(self.evaluate("!document.getElementById('laohuAccountModeBadge') && !document.getElementById('laohuAccountModeSwitch')"))

    def test_transient_status_read_failure_preserves_last_connected_account(self):
        status = FixtureState.manual_status(
            connected=True,
            mode="account",
            login_available=True,
            login_unavailable_reason="",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=True,
            execution_ready=True,
        )
        self.open_page(status=status)
        with self.state.lock:
            self.state.status_code = 503
        self.evaluate("window.LaohuAccount.refreshStatus({refreshProvider:false})")
        self.wait_for("document.getElementById('laohuAccountMessage').textContent==='暂时无法连接，请稍后重试。'", "暂时读取失败未显示简短重试提示")
        screenshot, _metrics = self.screenshot(390, 560, "laohu-account-390-status-read-error.png")
        self.assertTrue(screenshot.is_file())
        view = self.evaluate("""(() => ({
          connected:window.LaohuAccount.getStatus()?.connected,
          loginHidden:document.getElementById('laohuAccountLogin').hidden,
          profileHidden:document.getElementById('laohuAccountProfile').hidden,
          modeMessage:document.getElementById('laohuAccountModeMessage').textContent,
          keyValue:document.getElementById('keyInput').value,
          keyHint:document.getElementById('keyHint').textContent,
          actionMessage:document.getElementById('laohuAccountMessage').textContent
        }))()""")
        self.assertTrue(view["connected"], "status 读取失败不能把最近一次确认的连接改成退出")
        self.assertTrue(view["loginHidden"], "暂时读取失败不能诱导用户重新登录")
        self.assertFalse(view["profileHidden"], "暂时读取失败时保留最近一次安全账户摘要")
        self.assertEqual(view["modeMessage"], "正在使用登录账户，可直接调用模型。")
        self.assertEqual(view["keyValue"], "••••••••")
        self.assertEqual(view["keyHint"], "已自动加载")
        self.assertEqual(view["actionMessage"], "暂时无法连接，请稍后重试。")

    def test_refresh_unavailable_keeps_account_summary_without_relogin_prompt(self):
        status = FixtureState.manual_status(
            connected=True,
            mode="account",
            login_available=True,
            login_unavailable_reason="",
            connection_state="refresh_unavailable",
            reauth_required=False,
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=True,
            execution_ready=True,
            active_credential={"kind": "account", "configured": True, "label": "登录自动配置", "preview": "PRIVATE-OAUTH-TOKEN-MUST-NOT-APPEAR"},
        )
        self.open_page(status=status)
        view = self.evaluate("""(() => ({
          loginHidden:document.getElementById('laohuAccountLogin').hidden,
          modeMessage:document.getElementById('laohuAccountModeMessage').textContent,
          actionMessage:document.getElementById('laohuAccountMessage').textContent,
          profileHidden:document.getElementById('laohuAccountProfile').hidden,
          username:document.getElementById('laohuAccountUsername').textContent,
          balance:document.getElementById('laohuAccountBalance').textContent,
          keyValue:document.getElementById('keyInput').value,
          keyHint:document.getElementById('keyHint').textContent
        }))()""")
        self.assertTrue(view["loginHidden"], "临时账户状态读取失败不能显示重新连接入口")
        self.assertEqual(view["modeMessage"], "正在使用登录账户，可直接调用模型。", "状态查询未完成不能改变有效调用方式")
        self.assertEqual(view["actionMessage"], "账户状态暂时未更新。")
        self.assertFalse(view["profileHidden"], "后端给出的安全账户摘要应保留")
        self.assertEqual(view["username"], "Fixture User")
        self.assertEqual(view["balance"], "¥19.35")
        self.assertEqual(view["keyValue"], "••••••••", "后端确认旧凭据仍有效时保留固定安全遮罩")
        self.assertEqual(view["keyHint"], "已自动加载")

    def test_expired_account_offers_reconnect_and_success_restores_account_credential(self):
        expired = FixtureState.manual_status(
            connected=False,
            mode="account",
            login_available=True,
            login_unavailable_reason="",
            connection_state="reauth_required",
            reauth_required=True,
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "请在充值页查看"},
            has_manual_key=False,
            model_authorized=False,
            active_credential={"kind": "none", "configured": False, "label": "", "preview": ""},
        )
        connected = FixtureState.manual_status(
            connected=True,
            mode="account",
            login_available=True,
            login_unavailable_reason="",
            connection_state="connected",
            reauth_required=False,
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=True,
            execution_ready=True,
        )
        authorization = {
            "authorization_url": "https://api.lao-hu.com/authorize?state=reauth-fixture",
            "flow_id": "fixture-flow-reauth",
            "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60)),
        }
        self.open_page(
            status=expired,
            login_code=200,
            login_payload=authorization,
            flow_sequence=[{"status": "succeeded"}],
            status_after_flow=connected,
        )
        expired_view = self.evaluate("""(() => ({
          message:document.getElementById('laohuAccountModeMessage').textContent,
          loginHidden:document.getElementById('laohuAccountLogin').hidden,
          loginText:document.getElementById('laohuAccountLogin').textContent.trim(),
          keyValue:document.getElementById('keyInput').value,
          keyHint:document.getElementById('keyHint').textContent
        }))()""")
        self.assertEqual(expired_view["message"], "登录已失效，请重新连接。")
        self.assertFalse(expired_view["loginHidden"])
        self.assertEqual(expired_view["loginText"], "重新连接")
        self.assertEqual(expired_view["keyValue"], "未配置", "过期账户不得显示旧 token 遮罩或可用凭据")
        self.assertEqual(expired_view["keyHint"], "未配置")
        screenshot, _metrics = self.screenshot(390, 560, "laohu-account-390-reauth-required.png")
        self.assertTrue(screenshot.is_file())
        self.evaluate_with_user_gesture("""(() => {
          window.__fakePopup={closed:false,document:{},opener:window,location:{replace(url){window.__popupUrl=url;}},close(){this.closed=true;}};
          window.open=()=>window.__fakePopup;
          document.getElementById('laohuAccountLogin').click();
        })()""")
        self.wait_for(f"window.__fakePopup && window.__popupUrl==={json.dumps(authorization['authorization_url'])}", "重新连接按钮没有打开服务端提供的授权地址")
        self.wait_for("window.LaohuAccount.getStatus()?.connected===true && window.__fakePopup.closed", "重新授权后账户凭据没有恢复")
        restored = self.evaluate("({message:document.getElementById('laohuAccountModeMessage').textContent,keyValue:document.getElementById('keyInput').value,keyHint:document.getElementById('keyHint').textContent,loginHidden:document.getElementById('laohuAccountLogin').hidden})")
        self.assertEqual(restored["message"], "正在使用登录账户，可直接调用模型。")
        self.assertEqual(restored["keyValue"], "••••••••", "重新授权后只显示固定安全遮罩")
        self.assertEqual(restored["keyHint"], "已自动加载")
        self.assertTrue(restored["loginHidden"])

    def test_refresh_401_rereads_reauth_state_and_shows_reconnect_immediately(self):
        connected = FixtureState.manual_status(
            connected=True,
            mode="account",
            login_available=True,
            login_unavailable_reason="",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=True,
            execution_ready=True,
        )
        expired = FixtureState.manual_status(
            connected=False,
            mode="account",
            login_available=True,
            login_unavailable_reason="",
            connection_state="reauth_required",
            reauth_required=True,
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "请在充值页查看"},
            has_manual_key=False,
            model_authorized=False,
            active_credential={"kind": "none", "configured": False, "label": "", "preview": ""},
        )
        self.open_page(status=connected, refresh_code=401, refresh_status_after=expired)
        with self.state.lock:
            status_reads_before_refresh = self.state.status_get_calls
        self.evaluate("document.getElementById('laohuAccountRefresh').click()")
        self.wait_for("window.LaohuAccount.getStatus()?.reauth_required===true && document.getElementById('laohuAccountLogin').textContent.trim()==='重新连接'", "刷新401后未立即重读并显示重新连接")
        view = self.evaluate("({modeMessage:document.getElementById('laohuAccountModeMessage').textContent,keyValue:document.getElementById('keyInput').value,keyHint:document.getElementById('keyHint').textContent,message:document.getElementById('laohuAccountMessage').textContent})")
        self.assertEqual(view["modeMessage"], "登录已失效，请重新连接。")
        self.assertEqual(view["keyValue"], "未配置", "refresh 401 后不能保留旧的账户凭据遮罩")
        self.assertEqual(view["keyHint"], "未配置")
        self.assertEqual(view["message"], "", "重新连接提示已就近显示，不再叠加401长错误")
        with self.state.lock:
            status_reads = self.state.status_get_calls
            mutations = json.loads(json.dumps(self.state.mutations))
        self.assertEqual(status_reads, status_reads_before_refresh + 1, "刷新失败后仅重读一次权威状态")
        self.assertEqual([call["path"] for call in mutations], ["/api/laohu/account/refresh"])

    def test_refresh_502_rereads_temporary_state_and_keeps_model_account_active(self):
        connected = FixtureState.manual_status(
            connected=True,
            mode="account",
            login_available=True,
            login_unavailable_reason="",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=True,
            execution_ready=True,
        )
        refresh_unavailable = FixtureState.manual_status(
            connected=True,
            mode="account",
            login_available=True,
            login_unavailable_reason="",
            connection_state="refresh_unavailable",
            reauth_required=False,
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=True,
            execution_ready=True,
        )
        self.open_page(status=connected, refresh_code=502, refresh_status_after=refresh_unavailable)
        with self.state.lock:
            status_reads_before_refresh = self.state.status_get_calls
        self.evaluate("document.getElementById('laohuAccountRefresh').click()")
        self.wait_for("window.LaohuAccount.getStatus()?.connection_state==='refresh_unavailable' && document.getElementById('laohuAccountMessage').textContent==='账户状态暂时未更新。'", "刷新502后未重读暂时未更新状态")
        view = self.evaluate("({connected:window.LaohuAccount.getStatus()?.connected,modeMessage:document.getElementById('laohuAccountModeMessage').textContent,loginHidden:document.getElementById('laohuAccountLogin').hidden,keyValue:document.getElementById('keyInput').value,keyHint:document.getElementById('keyHint').textContent,message:document.getElementById('laohuAccountMessage').textContent})")
        self.assertTrue(view["connected"], "暂时无法读取状态不能把仍有效的账户切成退出")
        self.assertEqual(view["modeMessage"], "正在使用登录账户，可直接调用模型。")
        self.assertTrue(view["loginHidden"], "refresh 502 不应要求重新连接")
        self.assertEqual(view["keyValue"], "••••••••")
        self.assertEqual(view["keyHint"], "已自动加载")
        self.assertEqual(view["message"], "账户状态暂时未更新。")
        with self.state.lock:
            self.assertEqual(self.state.status_get_calls, status_reads_before_refresh + 1, "刷新失败后仅重读一次权威状态")

    def test_connected_identity_without_model_authorization_is_not_presented_as_ready(self):
        status = FixtureState.manual_status(
            connected=True,
            login_available=False,
            mode="account",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=False,
        )
        self.open_page(status=status)
        view = self.evaluate("""(() => ({
          connection:document.getElementById('laohuAccountConnection').textContent,
          connectionHidden:document.getElementById('laohuAccountConnection').hidden,
          message:document.getElementById('laohuAccountModeMessage').textContent,
          profileHidden:document.getElementById('laohuAccountProfile').hidden,
          balance:document.getElementById('laohuAccountBalance').textContent,
          loginHidden:document.getElementById('laohuAccountLogin').hidden,
          refreshHidden:document.getElementById('laohuAccountRefresh').hidden,
          logoutHidden:document.getElementById('laohuAccountLogout').hidden,
          keyVisible:Boolean(document.getElementById('keyInput').getClientRects().length),
          balanceLabel:document.querySelector('.laohu-account-balance > span').textContent
        }))()""")
        self.assertEqual(view["connection"], "")
        self.assertTrue(view["connectionHidden"], "账户连接成功由当前调用方式表达，不再重复显示已连接")
        self.assertIn("账户已登录，但暂不能用登录账户调用模型", view["message"])
        self.assertEqual(view["profileHidden"], False)
        self.assertEqual(view["balance"], "¥19.35")
        self.assertEqual(view["loginHidden"], True)
        self.assertEqual(view["refreshHidden"], False)
        self.assertEqual(view["logoutHidden"], False)
        self.assertTrue(view["keyVisible"])
        self.assertEqual(view["balanceLabel"], "登录账户余额")
        with self.state.lock:
            provider_get_calls = self.state.provider_get_calls
        self.assertEqual(provider_get_calls, 1, "模型未授权时不能按 connected 状态刷新模型候选")

    def test_unavailable_balance_uses_backend_message_without_rendering_raw_quota(self):
        status = FixtureState.manual_status(
            connected=True,
            mode="account",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "请在充值页查看", "quota": 9999},
            model_authorized=True,
            execution_ready=True,
        )
        self.open_page(status=status)
        view = self.evaluate("({balance:document.getElementById('laohuAccountBalance').textContent,profile:document.getElementById('laohuAccountProfile').textContent,wallet:document.getElementById('laohuAccountWallet').href})")
        self.assertEqual(view["balance"], "请在充值页查看")
        self.assertNotIn("9999", view["profile"], "余额不可用时不得展示原始额度数值")
        self.assertEqual(view["wallet"], "https://api.lao-hu.com/wallet")

    def test_model_authorized_but_execution_not_ready_is_not_presented_as_callable(self):
        status = FixtureState.manual_status(
            connected=True,
            login_available=False,
            mode="account",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=True,
            execution_ready=False,
            model_unavailable_reason="共享模型执行凭据尚未接入",
        )
        self.open_page(status=status)
        message = self.evaluate("document.getElementById('laohuAccountModeMessage').textContent")
        self.assertIn("账户已登录，但暂不能用登录账户调用模型", message)
        self.assertFalse(self.evaluate("document.getElementById('laohuAccountProfile').hidden"))
        with self.state.lock:
            provider_get_calls = self.state.provider_get_calls
        self.assertEqual(provider_get_calls, 1, "execution_ready 明确为 false 时不刷新模型候选")

    def test_explicit_save_puts_new_key_then_switches_to_manual_mode(self):
        status = FixtureState.manual_status(
            connected=True,
            mode="account",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=True,
            execution_ready=True,
        )
        self.open_page(status=status)
        self.open_advanced_settings()
        started = self.evaluate("""(() => {
          const input=document.getElementById('keyInput');
          input.value='manual-key-draft';
          input.dispatchEvent(new Event('input',{bubbles:true}));
          const button=document.getElementById('laohuSaveKeyButton');
          const visible=Boolean(button.getClientRects().length);
          button.click();
          return {visible,inputLocked:input.disabled,buttonLocked:button.disabled};
        })()""")
        self.assertTrue(started["visible"], "展开设置后应显示唯一保存按钮")
        self.assertTrue(started["inputLocked"], "保存期间锁定 Key 输入，避免快照中途被改写")
        self.assertTrue(started["buttonLocked"], "保存入口应在任何异步等待前同步锁定")
        self.wait_for("window.LaohuAccount.getStatus()?.mode==='manual' && document.getElementById('keyInput').readOnly && document.getElementById('keyInput').value==='••••••••key1'", "Key 保存后没有切回手动 API Key 并显示安全遮罩")
        self.wait_for("document.getElementById('laohuAccountModeMessage').textContent.includes('正在使用 API Key')", "手动认证状态没有明确显示当前 API Key")
        with self.state.lock:
            events = list(self.state.events)
            mutations = json.loads(json.dumps(self.state.mutations))
            saved = json.loads(json.dumps(self.state.saved_providers))
        key_record = next(item for item in saved if item["id"] == "ai-money")
        self.assertEqual(key_record["api_key"], "manual-key-draft")
        self.assertFalse(key_record["clear_key"])
        self.assertEqual([event["method"] for event in events], ["PUT", "POST"], "必须先完成原有 API Key PUT，再切换认证")
        self.assertEqual(events[1]["path"], "/api/laohu/account/mode")
        self.assertEqual([call["body"] for call in mutations if call["path"] == "/api/laohu/account/mode"], [{"mode": "manual"}])
        self.assertTrue(all(call["action"] == "1" for call in mutations))
        self.assertEqual(self.evaluate("document.getElementById('keyInput').value"), "••••••••key1")
        self.assertEqual(self.evaluate("document.getElementById('keyHint').textContent"), "已保存并启用")
        self.assertTrue(self.evaluate("document.getElementById('keyInput').readOnly"))
        self.assertFalse(self.evaluate("Boolean(document.getElementById('laohuCredentialPreview'))"))
        self.wait_for("provider().has_key===true", "切到手动调用后服务端 Key 状态未刷新")

    def test_empty_save_is_noop_and_enter_uses_the_same_explicit_save_path(self):
        self.open_page()
        self.open_advanced_settings()
        self.evaluate("saveLaohuKey()")
        with self.state.lock:
            self.assertEqual(self.state.put_calls, [])
            self.assertFalse(any(call["path"] == "/api/laohu/account/mode" for call in self.state.mutations))
        self.evaluate("""(() => {const input=document.getElementById('keyInput');input.value='enter-key';input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));})()""")
        self.wait_for("window.LaohuAccount.getStatus()?.mode==='manual' && document.getElementById('keyInput').readOnly && document.getElementById('keyInput').value==='••••••••key1'", "模式切换重试成功后应恢复当前手动 Key 遮罩")
        with self.state.lock:
            events = list(self.state.events)
        self.assertEqual(events, [{"method": "PUT", "path": "/api/providers"}, {"method": "POST", "path": "/api/laohu/account/mode"}])

    def test_platform_change_during_key_put_keeps_other_input_and_reports_pending_mode(self):
        status = FixtureState.manual_status(
            connected=True,
            mode="account",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=True,
            execution_ready=True,
        )
        self.open_page(status=status, put_delay_seconds=0.6)
        self.open_advanced_settings()
        self.evaluate("""(() => {const input=document.getElementById('keyInput');input.value='laohu-captured-key';input.dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('laohuSaveKeyButton').click()})()""")
        self.assertTrue(self.state.put_started.wait(5), "laohu Key PUT 没有启动")
        self.evaluate("selectProvider('alpha')")
        self.wait_for("document.getElementById('keyInput').placeholder.includes('API Key')", "其他平台 Key 输入未显示")
        self.evaluate("""(() => {const input=document.getElementById('keyInput');input.value='alpha-key';input.dispatchEvent(new Event('input',{bubbles:true}))})()""")
        self.wait_for_put_requests(2)
        self.wait_for("document.getElementById('keyInput').value==='alpha-key' && !document.getElementById('keyInput').disabled")
        self.wait_for_saved_provider_key("alpha", "alpha-key")
        with self.state.lock:
            mode_calls = [call for call in self.state.mutations if call["path"] == "/api/laohu/account/mode"]
            saved = json.loads(json.dumps(self.state.saved_providers))
            latest_request = json.loads(json.dumps(self.state.put_calls[-1]))
        self.assertEqual(mode_calls, [], "用户已切到其他平台时先保留原调用方式，不应静默改 mode")
        alpha = next(item for item in saved if item["id"] == "alpha")
        self.assertEqual(alpha["api_key"], "alpha-key", "异步 Key 保存不得清空或覆盖其他平台输入")
        alpha_autosave_laohu = next(item for item in latest_request if item.get("id") == "ai-money")
        self.assertNotIn("api_key", alpha_autosave_laohu, "Alpha 的自动保存请求不得重发捕获的 laohu Key 草稿")

        self.evaluate("selectProvider('ai-money')")
        self.wait_for("!document.getElementById('laohuAccountCard').hidden && document.getElementById('laohuAccountMessage').textContent.includes('Key 已保存')", "返回 laohu 后应保留已保存但尚未切换的明确提示")
        self.assertEqual(self.evaluate("document.getElementById('keyInput').value"), "laohu-captured-key", "未完成的 laohu draft 应独立保留，不能写入其他平台字段")
        with self.state.lock:
            saved = json.loads(json.dumps(self.state.saved_providers))
        self.assertEqual(next(item for item in saved if item["id"] == "ai-money")["api_key"], "laohu-captured-key")

    def test_failed_manual_key_save_preserves_draft_and_does_not_switch(self):
        status = FixtureState.manual_status(
            connected=True,
            mode="account",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=True,
            execution_ready=True,
        )
        self.open_page(status=status, put_status_code=500)
        self.open_advanced_settings()
        self.evaluate("""(() => {
          const input=document.getElementById('keyInput');
          input.value='unsaved-key-draft';
          input.dispatchEvent(new Event('input',{bubbles:true}));
          document.getElementById('laohuSaveKeyButton').click();
        })()""")
        self.wait_for("document.getElementById('laohuAccountMessage').textContent.includes('保存失败')", "保存失败后没有给出明确错误")
        self.assertEqual(self.evaluate("window.LaohuAccount.getStatus()?.mode"), "account")
        self.assertEqual(self.evaluate("document.getElementById('keyInput').value"), "unsaved-key-draft", "保存失败必须保留用户草稿")
        self.assertFalse(self.evaluate("document.getElementById('keyInput').disabled"), "失败后应恢复 Key 编辑")
        with self.state.lock:
            mutations = json.loads(json.dumps(self.state.mutations))
            events = list(self.state.events)
        self.assertFalse(any(call["path"] == "/api/laohu/account/mode" for call in mutations), "Key 保存失败不得调用 mode API")
        self.assertEqual(events, [{"method": "PUT", "path": "/api/providers"}])

    def test_mode_failure_after_put_reports_saved_but_keeps_draft_for_retry(self):
        status = FixtureState.manual_status(
            connected=True,
            mode="account",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=True,
            execution_ready=True,
        )
        self.open_page(status=status, manual_mode_code=409)
        self.open_advanced_settings()
        self.evaluate("""(() => {const input=document.getElementById('keyInput');input.value='retryable-key';input.dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('laohuSaveKeyButton').click()})()""")
        self.wait_for("document.getElementById('laohuAccountMessage').textContent.includes('Key 已保存')", "mode 失败后没有说明 Key 已保存")
        self.assertEqual(self.evaluate("window.LaohuAccount.getStatus()?.mode"), "account", "mode 请求失败时仍应保留原账户调用方式")
        self.assertEqual(self.evaluate("document.getElementById('keyInput').value"), "retryable-key", "mode 失败需保留 Key 草稿，允许重试同一保存操作")
        with self.state.lock:
            first_events = list(self.state.events)
        self.assertEqual(first_events, [{"method": "PUT", "path": "/api/providers"}, {"method": "POST", "path": "/api/laohu/account/mode"}])
        with self.state.lock:
            self.state.manual_mode_code = 200
        self.evaluate("document.getElementById('laohuSaveKeyButton').click()")
        self.wait_for("window.LaohuAccount.getStatus()?.mode==='manual' && document.getElementById('keyInput').readOnly && document.getElementById('keyInput').value==='••••••••key1'", "Enter 应通过同一保存动作返回当前凭据显示")
        with self.state.lock:
            all_events = list(self.state.events)
        self.assertEqual([event["method"] for event in all_events], ["PUT", "POST", "PUT", "POST"], "同一保存操作重试应再次先写 Key 再切 mode")

    def test_manual_mode_keeps_key_active_until_user_switches_to_connected_account(self):
        status = FixtureState.manual_status(
            connected=True,
            mode="manual",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=True,
            model_authorized=True,
            execution_ready=True,
        )
        self.open_page(status=status, provider_has_key=True)
        before = self.evaluate("({message:document.getElementById('laohuAccountModeMessage').textContent,buttonHidden:document.getElementById('laohuAccountUseAccount').hidden,balance:document.getElementById('laohuAccountBalance').textContent,balanceLabel:document.querySelector('.laohu-account-balance > span').textContent,keyValue:document.getElementById('keyInput').value,keyHint:document.getElementById('keyHint').textContent,keyType:document.getElementById('keyInput').type,keyReadOnly:document.getElementById('keyInput').readOnly})")
        self.assertEqual(before["message"], "正在使用 API Key。")
        self.assertFalse(before["buttonHidden"], "已有登录账户时，手动 Key 模式应提供明确切回入口")
        self.assertEqual(before["balance"], "¥19.35")
        self.assertEqual(before["balanceLabel"], "登录账户余额", "账户额度必须标明属于登录账户")
        self.assertEqual(before["keyValue"], "••••••••key1")
        self.assertEqual(before["keyHint"], "已保存并启用")
        self.assertEqual(before["keyType"], "text")
        self.assertTrue(before["keyReadOnly"])
        self.evaluate("document.getElementById('laohuAccountUseAccount').click()")
        self.wait_for("window.LaohuAccount.getStatus()?.mode==='account'", "没有切换到登录账户模式")
        self.wait_for("document.getElementById('laohuAccountModeMessage').textContent.includes('正在使用登录账户')", "账户切换后当前调用方式没有持续显示")
        self.assertTrue(self.evaluate("document.getElementById('laohuAccountUseAccount').hidden"))
        with self.state.lock:
            events = list(self.state.events)
            mutations = json.loads(json.dumps(self.state.mutations))
        self.assertEqual(events, [{"method": "POST", "path": "/api/laohu/account/mode"}], "切换方式只调用现有 mode API，不重写 Key")
        self.assertEqual([call["body"] for call in mutations if call["path"] == "/api/laohu/account/mode"], [{"mode": "account"}])

    def test_account_provider_has_key_does_not_masquerade_as_saved_manual_key(self):
        status = FixtureState.manual_status(
            connected=True,
            mode="account",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=True,
            execution_ready=True,
        )
        self.open_page(status=status, provider_has_key=True)
        self.wait_for("window.LaohuAccount.getStatus()?.connected===true", "账户状态没有完成读取")
        state = self.evaluate("""(() => ({
          keyPreview:provider().key_preview,
          clearButtonHidden:document.querySelector('.laohu-key-clear').hidden,
          keyHint:document.getElementById('keyHint').textContent,
          keyPlaceholder:document.getElementById('keyInput').placeholder,
          keyValue:document.getElementById('keyInput').value,
          keyType:document.getElementById('keyInput').type,
          keyReadOnly:document.getElementById('keyInput').readOnly,
          updateText:document.getElementById('laohuSaveKeyButton').textContent.trim(),
          cancelHidden:document.getElementById('laohuCancelKeyButton').hidden,
          externalPreview:Boolean(document.getElementById('laohuCredentialPreview'))
        }))()""")
        self.assertEqual(state["keyPreview"], "fixture…key")
        self.assertEqual(state["keyValue"], "••••••••", "账户凭据必须在 Key 输入框显示固定遮罩，不得显示 token 片段")
        self.assertEqual(state["keyHint"], "已自动加载")
        self.assertEqual(state["keyType"], "text")
        self.assertTrue(state["keyReadOnly"])
        self.assertEqual(state["updateText"], "更新")
        self.assertTrue(state["cancelHidden"])
        self.assertFalse(state["externalPreview"], "不能重复在输入框外显示 credential preview")
        self.assertNotIn("PRIVATE-OAUTH-TOKEN-MUST-NOT-APPEAR", self.evaluate("document.body.innerText"), "账户 token sentinel 不得进入任何可见文案")
        self.assertTrue(state["clearButtonHidden"], "账户授权不能显示成可移除的本机手动 Key")
        self.assertNotIn("fixture…key", state["keyPlaceholder"])
        self.evaluate("document.getElementById('keyInput').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}))")
        time.sleep(0.1)
        with self.state.lock:
            self.assertEqual(self.state.events, [], "只读遮罩按 Enter 不得进入保存逻辑")
        self.evaluate("beginLaohuKeyEdit()")
        self.assertEqual(self.evaluate("document.getElementById('keyInput').value"), "", "进入编辑后必须清空显示遮罩，不带入草稿")
        self.assertEqual(self.evaluate("document.getElementById('keyInput').type"), "password")
        self.assertEqual(self.evaluate("document.getElementById('keyHint').textContent"), "未保存")
        self.evaluate("document.getElementById('keyInput').value='account-mode-unsaved';document.getElementById('keyInput').dispatchEvent(new Event('input',{bubbles:true}));window.LaohuAccount.refreshStatus({refreshProvider:false})")
        self.wait_for("window.LaohuAccount.getStatus()?.connected===true", "编辑期间状态刷新失败")
        self.assertEqual(self.evaluate("document.getElementById('keyInput').value"), "account-mode-unsaved", "状态刷新不能覆盖正在编辑的草稿")
        self.assertEqual(self.evaluate("document.getElementById('keyHint').textContent"), "未保存")
        self.evaluate("cancelLaohuKeyEdit()")
        self.assertEqual(self.evaluate("document.getElementById('keyInput').value"), "••••••••", "取消应恢复同框账户遮罩")
        self.assertEqual(self.evaluate("document.getElementById('keyHint').textContent"), "已自动加载")
        self.assertEqual(self.evaluate("document.getElementById('laohuSaveKeyButton').textContent.trim()"), "更新")
        self.evaluate("clearKeyOnly()")
        time.sleep(0.1)
        with self.state.lock:
            events = list(self.state.events)
        self.assertEqual(events, [], "没有手动 Key 时不能切换模式或提交清除请求")

    def test_hidden_parent_keeps_login_polling_closes_popup_and_updates_original_tab(self):
        connected = FixtureState.manual_status(
            connected=True,
            mode="account",
            account={"id": "fixture-account", "username": "Fixture User", "balance_display": "¥19.35"},
            has_manual_key=False,
            model_authorized=True,
            execution_ready=False,
            model_unavailable_reason="共享模型执行尚未接入",
        )
        authorization = {
            "authorization_url": "https://api.lao-hu.com/authorize?state=fixture-state",
            "flow_id": "fixture-flow-hidden-parent",
            "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60)),
        }
        self.open_page(
            status=FixtureState.manual_status(login_available=True, login_unavailable_reason=""),
            login_code=200,
            login_payload=authorization,
            flow_sequence=[{"status": "pending"}, {"status": "succeeded"}],
            status_after_flow=connected,
        )
        self.evaluate("""(() => {
          window.__fakeHidden=true;
          Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>window.__fakeHidden?'hidden':'visible'});
          window.__popupOpenCount=0;
          window.__popupLocations=[];
          window.__fakePopup={closed:false,document:{},opener:window,location:{replace(url){window.__popupLocations.push(url);}},close(){this.closed=true;}};
          window.open=()=>{window.__popupOpenCount++;return window.__fakePopup;};
          document.dispatchEvent(new Event('visibilitychange'));
          document.getElementById('laohuAccountLogin').click();
        })()""")
        self.wait_for_flow_calls(1)
        self.evaluate("window.LaohuAccount.login()")
        self.assertEqual(self.evaluate("window.__popupOpenCount"), 1, "在途授权期间不得重复创建 flow")
        with self.state.lock:
            login_posts = [call for call in self.state.mutations if call["path"] == "/api/laohu/account/login"]
        self.assertEqual(len(login_posts), 1, "在途授权期间不得重复 POST 登录")
        self.wait_for_flow_calls(2)
        self.wait_for("window.LaohuAccount.getStatus()?.connected===true && window.__fakePopup.closed", "父页隐藏时应完成轮询、关闭授权弹窗并更新原标签状态")
        self.assertEqual(self.evaluate("document.visibilityState"), "hidden", "验收期间父页保持隐藏")
        self.assertEqual(self.evaluate("document.getElementById('laohuAccountMessage').textContent"), "", "正常登录成功不重复占据操作提示行")
        self.assertIn("账户已登录，但暂不能用登录账户调用模型", self.evaluate("document.getElementById('laohuAccountModeMessage').textContent"), "临时成功提示不能覆盖当前调用状态")
        self.assertIsNone(self.evaluate("window.__fakePopup.opener"), "保留 opener=null 安全设置")
        self.assertEqual(self.evaluate("window.__popupLocations"), [authorization["authorization_url"]])
        self.assertIn("api-settings.html", self.evaluate("location.href"), "原标签继续停留在 API 设置，不导航到完成页")
        with self.state.lock:
            provider_get_calls = self.state.provider_get_calls
            login_posts = [call for call in self.state.mutations if call["path"] == "/api/laohu/account/login"]
        self.assertEqual(provider_get_calls, 1, "execution_ready=false 时不刷新模型目录")
        self.assertEqual(len(login_posts), 1)

    def test_actual_callback_response_closes_only_a_script_opened_severed_popup(self):
        self.open_page(status=FixtureState.manual_status(login_available=True, login_unavailable_reason=""))

        allowed_url = f"http://127.0.0.1:{self.http_port}/__isolated__/callback-close-allowed"
        opened = self.evaluate_with_user_gesture(f"""(() => {{
          window.__callbackPopup = window.open('about:blank', 'actual-callback-close-allowed');
          if (!window.__callbackPopup) return false;
          window.__callbackPopup.opener = null;
          window.__callbackPopupOpenerWasNull = window.__callbackPopup.opener === null;
          window.__callbackPopup.location.replace({json.dumps(allowed_url)});
          return true;
        }})()""")
        self.assertTrue(opened, "测试脚本必须成功创建 popup")
        self.wait_for("window.__callbackPopup.closed", "真实 close_allowed 回调页未自动关闭 popup")
        self.assertTrue(self.evaluate("window.__callbackPopupOpenerWasNull"), "popup 必须在导航前切断 opener")

        denied_url = f"http://127.0.0.1:{self.http_port}/__isolated__/callback-close-denied"
        opened = self.evaluate_with_user_gesture(f"""(() => {{
          window.__callbackPopup = window.open('about:blank', 'actual-callback-close-denied');
          if (!window.__callbackPopup) return false;
          window.__callbackPopup.opener = null;
          window.__callbackPopupOpenerWasNull = window.__callbackPopup.opener === null;
          window.__callbackPopup.location.replace({json.dumps(denied_url)});
          return true;
        }})()""")
        self.assertTrue(opened, "close_allowed=false 用例必须成功创建 popup")
        self.wait_for(
            "window.__callbackPopup && !window.__callbackPopup.closed && window.__callbackPopup.location.pathname === '/api/laohu/account/callback/complete'",
            "close_allowed=false 回调页没有完成加载",
        )
        self.assertTrue(self.evaluate("window.__callbackPopupOpenerWasNull"), "第二个 popup 也必须切断 opener")
        time.sleep(0.75)
        self.assertFalse(self.evaluate("window.__callbackPopup.closed"), "close_allowed=false 不得自动关闭 popup")
        self.evaluate("window.__callbackPopup.close()")

    def test_late_flow_response_is_ignored_after_leaving_laohu_provider(self):
        authorization = {
            "authorization_url": "https://api.lao-hu.com/authorize?state=late-fixture",
            "flow_id": "fixture-flow-late-response",
            "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60)),
        }
        self.open_page(
            status=FixtureState.manual_status(login_available=True, login_unavailable_reason=""),
            login_code=200,
            login_payload=authorization,
            flow_sequence=[{"status": "succeeded"}],
            flow_delay_seconds=1.1,
        )
        self.evaluate("""(() => {
          window.__fakePopup={closed:false,document:{},opener:window,location:{replace(){}},close(){this.closed=true;}};
          window.open=()=>window.__fakePopup;
          document.getElementById('laohuAccountLogin').click();
        })()""")
        self.wait_for_flow_calls(1)
        with self.state.lock:
            status_reads_before_leaving = self.state.status_get_calls
        self.evaluate("selectProvider('alpha')")
        self.wait_for("document.getElementById('laohuAccountCard').hidden", "离开 laohu 后账户卡片应隐藏")
        time.sleep(1.3)
        self.assertTrue(self.evaluate("window.__fakePopup.closed"), "离开平台时应关闭登录弹窗")
        self.assertFalse(self.evaluate("window.LaohuAccount.getStatus()?.connected"), "迟到的登录响应不得更新已离开平台的状态")
        self.assertEqual(self.evaluate("document.getElementById('editorTitle').textContent"), "Alpha")
        with self.state.lock:
            status_reads = self.state.status_get_calls
            login_posts = [call for call in self.state.mutations if call["path"] == "/api/laohu/account/login"]
        self.assertEqual(status_reads, status_reads_before_leaving, "旧 epoch 的迟到成功不能在离开平台后强制读取账户状态")
        self.assertEqual(len(login_posts), 1)


if __name__ == "__main__":
    unittest.main()
