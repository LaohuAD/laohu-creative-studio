"""真实 Chromium 回归：Hypit 共享设置画布的启动预取与单画布复用。"""
from __future__ import annotations

import json
import os
import re
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


def smart_node_schema_version():
    """从共享节点契约源码读取画布当前 schema，避免测试夹具落后于正式结构。"""
    source = (ROOT / "static" / "js" / "smart-node-contract.js").read_text(encoding="utf-8")
    match = re.search(r"^\s*const\s+SCHEMA_VERSION\s*=\s*(\d+)\s*;", source, re.MULTILINE)
    if not match:
        raise RuntimeError("SmartNodeContract 源码没有可识别的 SCHEMA_VERSION")
    return int(match.group(1))


SMART_NODE_SCHEMA_VERSION = smart_node_schema_version()


def chrome_binary():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    ]
    return next((item for item in candidates if item and Path(item).is_file()), None)


CHROME = chrome_binary()
NODE = shutil.which("node")
KEY_SENTINEL = "fixture-secret-must-not-be-cached"


def empty_defaults():
    return {
        slot: {"provider": "", "model": "", "region": "", "parameters": {}}
        for slot in ("text", "image", "video", "audio", "music", "voice")
    }


def image_option(model_id):
    return {
        "option_id": f"option-{model_id}",
        "node_type": "image_generation",
        "operation": "text_to_image",
        "connection_id": "fixture-provider",
        "capability_provider_id": "fixture-provider",
        "platform_label": "Fixture Provider",
        "catalog_model_id": model_id,
        "canonical_family_id": "fixture-family",
        "canonical_family_label": {"zh": "测试系列", "en": "Fixture family"},
        "region_id": "",
        "readiness": "ready",
        "runnable": True,
        "selectable": True,
        "validation_mode": "strict",
        "parameters": {},
        "inputs": {},
        "capability_tags": ["文生图"],
        "capability_tags_en": ["Text to image"],
    }


class HypitApiState:
    def __init__(self):
        self.condition = threading.Condition()
        self.reset()

    def reset(self, *, hold_capabilities=False, hold_settings=False, fail_first_capabilities=False,
              hold_first_canvas_bootstrap=False):
        with getattr(self, "condition", threading.Condition()):
            self.capability_calls = 0
            self.settings_calls = 0
            self.settings_canvas_calls = 0
            self.canvas_get_calls = 0
            self.canvas_get_responses = 0
            self.canvas_put_calls = 0
            self.canvas_reset_calls = 0
            self.provider_get_calls = 0
            self.model_catalog_calls = 0
            self.provider_put_calls = 0
            self.settings_put_calls = 0
            self.catalog_revision = 1
            self.selected_image_model = "fixture-image-old"
            self.saved_defaults = empty_defaults()
            self.saved_defaults["image"] = {
                "provider": "fixture-provider", "model": "fixture-image-old", "region": "", "parameters": {}
            }
            self.settings_revision = 2
            self.hold_capabilities = hold_capabilities
            self.hold_settings = hold_settings
            self.fail_first_capabilities = fail_first_capabilities
            self.fail_next_canvas_bootstrap = 0
            self.hold_first_canvas_bootstrap = hold_first_canvas_bootstrap
            self.fail_next_capabilities = 0
            self.capability_release = threading.Event()
            self.settings_release = threading.Event()
            self.canvas_bootstrap_release = threading.Event()
            if not hold_capabilities:
                self.capability_release.set()
            if not hold_settings:
                self.settings_release.set()
            if not hold_first_canvas_bootstrap:
                self.canvas_bootstrap_release.set()
            self.condition.notify_all()

    def wait_for(self, name, target=1, timeout=5):
        deadline = time.monotonic() + timeout
        with self.condition:
            while getattr(self, name) < target:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self.condition.wait(remaining)
            return True

    def notify(self):
        with self.condition:
            self.condition.notify_all()

    def capability_payload(self, revision, selected_model):
        option = image_option(selected_model)
        empty = []
        slots = {
            "text": empty, "image": [option], "video": empty,
            "audio": empty, "music": empty, "voice": empty,
        }
        supported = [
            {"slot": slot, "kind": slot, "node_type": node_type, "models": []}
            for slot, node_type in (
                ("text", "text_generation"), ("image", "image_generation"),
                ("video", "video_generation"), ("audio", "audio_generation"),
                ("music", "music_generation"), ("voice", "audio_generation"),
            )
        ]
        return {
            "schema_version": 1,
            "catalog_revision": f"catalog-{revision}",
            "providers": [{"id": "fixture-provider", "name": "Fixture Provider", "enabled": True, "models": []}],
            "options": [option],
            "slot_options": slots,
            "supported_capabilities": supported,
            "unsupported_capabilities": [],
            "defaults": json.loads(json.dumps(self.saved_defaults)),
        }

    def provider_payload(self):
        return [{
            "id": "fixture-provider", "name": "Fixture Provider", "base_url": "https://fixture.invalid/v1",
            "protocol": "openai", "enabled": True,
            "image_models": ["fixture-image-old"], "chat_models": [], "video_models": [], "audio_models": [],
            "model_names": {}, "model_protocols": {}, "has_key": True,
            "key_preview": KEY_SENTINEL, "key_env": "FIXTURE_API_KEY",
        }]


@unittest.skipUnless(CHROME and NODE, "需要本机 Chrome/Chromium 和 Node.js 执行真实浏览器回归")
class HypitSettingsPrefetchBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = HypitApiState()

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
                if path == "/static/smart-canvas.html":
                    body = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")
                    marker = "<head>"
                    if marker not in body:
                        self.send_error(500, "smart-canvas fixture head is missing")
                        return
                    ready_listener = (
                        '<script>window.__hypitCanvasReadyListenerInstalled=true;'
                        'window.addEventListener("canvas-ready",()=>{'
                        'window.__hypitCanvasReadyForTest=true;},{once:true});</script>'
                    )
                    payload = body.replace(marker, marker + ready_listener, 1).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if path == "/api/hypit/settings-canvas":
                    with cls.state.condition:
                        cls.state.settings_canvas_calls += 1
                        call = cls.state.settings_canvas_calls
                        fail = cls.state.fail_next_canvas_bootstrap > 0
                        if fail:
                            cls.state.fail_next_canvas_bootstrap -= 1
                        held = cls.state.hold_first_canvas_bootstrap and call == 1
                        release = cls.state.canvas_bootstrap_release
                        cls.state.condition.notify_all()
                    if held:
                        release.wait(10)
                    if fail:
                        self._json(503, {"detail": "isolated Hypit canvas bootstrap failure"})
                        return
                    self._json(200, {"id": "hypit-settings", "canvas": {
                        "id": "hypit-settings", "title": "Hypit settings", "revision": 1,
                        "node_schema_version": SMART_NODE_SCHEMA_VERSION,
                        "nodes": [], "connections": [], "logs": [], "settings": {},
                        "viewport": {"x": 0, "y": 0, "scale": 1}, "test_statuses": {},
                    }, "url": "/static/smart-canvas.html?id=hypit-settings&mode=hypit-settings"})
                    return
                if path == "/api/canvases/hypit-settings":
                    with cls.state.condition:
                        cls.state.canvas_get_calls += 1
                        cls.state.condition.notify_all()
                    self._json(200, {"canvas": {
                        "id": "hypit-settings", "title": "Hypit settings", "revision": 1,
                        "node_schema_version": SMART_NODE_SCHEMA_VERSION,
                        "nodes": [], "connections": [], "logs": [], "settings": {},
                        "viewport": {"x": 0, "y": 0, "scale": 1}, "test_statuses": {},
                    }})
                    with cls.state.condition:
                        cls.state.canvas_get_responses += 1
                        cls.state.condition.notify_all()
                    return
                if path == "/api/studio/hypit/models/capabilities":
                    with cls.state.condition:
                        cls.state.capability_calls += 1
                        call = cls.state.capability_calls
                        revision = cls.state.catalog_revision
                        model_id = cls.state.selected_image_model
                        held = cls.state.hold_capabilities
                        release = cls.state.capability_release
                        fail = cls.state.fail_first_capabilities and call == 1
                        if cls.state.fail_next_capabilities:
                            cls.state.fail_next_capabilities -= 1
                            fail = True
                        cls.state.condition.notify_all()
                    if held:
                        release.wait(10)
                    if fail:
                        self._json(503, {"detail": "isolated Hypit read failure"})
                        return
                    self._json(200, cls.state.capability_payload(revision, model_id))
                    return
                if path == "/api/studio/hypit/models/settings":
                    with cls.state.condition:
                        cls.state.settings_calls += 1
                        settings_revision = cls.state.settings_revision
                        defaults = json.loads(json.dumps(cls.state.saved_defaults))
                        held = cls.state.hold_settings
                        release = cls.state.settings_release
                        cls.state.condition.notify_all()
                    if held:
                        release.wait(10)
                    self._json(200, {"version": 1, "revision": settings_revision, "defaults": defaults})
                    return
                if path == "/api/providers":
                    with cls.state.condition:
                        cls.state.provider_get_calls += 1
                        cls.state.condition.notify_all()
                    self._json(200, {"providers": cls.state.provider_payload()})
                    return
                if path == "/api/model-capabilities":
                    with cls.state.condition:
                        cls.state.model_catalog_calls += 1
                        cls.state.condition.notify_all()
                    self._json(200, {"schema_version": 1, "providers": [], "options": [], "catalog_revision": "api-catalog"})
                    return
                super().do_GET()

            def do_PUT(self):
                path = urlsplit(self.path).path
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                if path == "/api/canvases/hypit-settings":
                    with cls.state.condition:
                        cls.state.canvas_put_calls += 1
                        cls.state.condition.notify_all()
                    self._json(200, {"canvas": payload})
                    return
                if path == "/api/providers":
                    with cls.state.condition:
                        cls.state.provider_put_calls += 1
                        providers = payload if isinstance(payload, list) else []
                        first = next((item for item in providers if item.get("id") == "fixture-provider"), {})
                        models = first.get("image_models") or []
                        if models:
                            cls.state.selected_image_model = str(models[0])
                        cls.state.catalog_revision += 1
                        cls.state.condition.notify_all()
                    self._json(200, {"providers": providers})
                    return
                if path == "/api/studio/hypit/models/settings":
                    with cls.state.condition:
                        cls.state.settings_put_calls += 1
                        cls.state.settings_revision += 1
                        cls.state.saved_defaults = payload.get("defaults") or empty_defaults()
                        revision = cls.state.settings_revision
                        self._json(200, {"version": 1, "revision": revision, "defaults": cls.state.saved_defaults})
                    return
                    self._json(404, {"detail": "unknown test endpoint"})

            def do_POST(self):
                path = urlsplit(self.path).path
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if path == "/api/hypit/settings-canvas/reset":
                    with cls.state.condition:
                        cls.state.canvas_reset_calls += 1
                        cls.state.condition.notify_all()
                    self._json(200, {"id": "hypit-settings", "reset": True, "canvas": {
                        "id": "hypit-settings", "title": "Hypit settings", "revision": 2,
                        "nodes": [], "connections": [], "logs": [], "settings": {},
                        "viewport": {"x": 0, "y": 0, "scale": 1}, "test_statuses": {},
                    }})
                    return
                self._json(404, {"detail": "unknown test endpoint"})

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.http_port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.debug_port = probe.getsockname()[1]
        cls.profile = ROOT / "cache" / "studio-tests" / "tmp" / f"hypit-prefetch-{int(time.time())}"
        cls.profile.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        task_tmp = ROOT / "cache" / "runtime" / "tmp"
        task_tmp.mkdir(parents=True, exist_ok=True)
        env.update({"TMPDIR": str(task_tmp), "TMP": str(task_tmp), "TEMP": str(task_tmp)})
        cls.chrome = subprocess.Popen(
            [
                CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", f"--user-data-dir={cls.profile}",
                f"--remote-debugging-port={cls.debug_port}", "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
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
            raise AssertionError(f"页面脚本异常：{result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def open_page(self, *, hold_capabilities=False, hold_settings=False, fail_first_capabilities=False,
                  fail_first_canvas_bootstrap=False, hold_first_canvas_bootstrap=False):
        self.state.reset(
            hold_capabilities=hold_capabilities,
            hold_settings=hold_settings,
            fail_first_capabilities=fail_first_capabilities,
            hold_first_canvas_bootstrap=hold_first_canvas_bootstrap,
        )
        if fail_first_canvas_bootstrap:
            with self.state.condition:
                self.state.fail_next_canvas_bootstrap = 1
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}/"})
        ready = self.evaluate(f"""(async()=>{{
          for(let i=0;i<100;i++){{
            if(location.origin==='http://127.0.0.1:{self.http_port}'){{
              localStorage.clear(); sessionStorage.clear();
              localStorage.setItem('studio_theme','light'); localStorage.setItem('studio_lang','zh');
              return true;
            }}
            await new Promise(resolve=>setTimeout(resolve,20));
          }}
          return false;
        }})()""")
        self.assertTrue(ready, "本地隔离测试源站未就绪")
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}/static/api-settings.html"})
        self.assertTrue(self.state.wait_for("provider_get_calls", timeout=8), "API 设置页没有读取假平台配置")

    def wait_for_canvas(self, timeout=8):
        return self.evaluate(f"""(async()=>{{
          for(let i=0;i<{int(timeout * 20)};i++){{
            const frame=document.getElementById('hypitSettingsCanvasFrame');
            if(frame?.contentWindow?.document?.getElementById('world')) return true;
            await new Promise(resolve=>setTimeout(resolve,50));
          }}
          return false;
        }})()""")

    def wait_for_canvas_sync(self, timeout=12, quiet_ms=500):
        return self.evaluate(f"""(async()=>{{
          const deadline=Date.now()+{int(timeout * 1000)};
          let previous='';
          let stableSince=0;
          let last=null;
          while(Date.now()<deadline){{
            const frame=document.getElementById('hypitSettingsCanvasFrame');
            let state=null;
            try{{
              const raw=frame?.contentWindow?.eval(`JSON.stringify({{
                ready:window.__hypitCanvasReadyForTest===true,
                listenerInstalled:window.__hypitCanvasReadyListenerInstalled===true,
                settingsMode:typeof isSettingsCanvasMode==='boolean'&&isSettingsCanvasMode,
                canvasPath:location.pathname+location.search,
                documentReady:document.readyState==='complete',
                inFlight:Boolean(canvasSyncInFlight),
                queued:Boolean(canvasSyncSaveQueued),
                blocked:Boolean(canvasSyncSaveBlocked),
                revision:Number(canvas?.revision||0),
                baseRevision:Number(canvasSyncBase?.revision||0)
              }})`);
              state=raw?JSON.parse(raw):null;
            }}catch(error){{state={{readError:String(error)}};}}
            last=state;
            const settled=Boolean(state?.ready&&state.documentReady&&!state.inFlight&&!state.queued
              &&!state.blocked&&state.revision===state.baseRevision);
            const signature=settled?JSON.stringify(state):'';
            if(settled&&signature===previous){{
              if(Date.now()-stableSince>={int(quiet_ms)})return JSON.stringify({{ok:true,state}});
            }}else{{
              stableSince=settled?Date.now():0;
              previous=signature;
            }}
            await new Promise(resolve=>setTimeout(resolve,25));
          }}
          return JSON.stringify({{ok:false,state:last}});
        }})()""")

    def test_api_startup_prefetches_canvas_bootstrap_and_entry_reuses_one_iframe(self):
        self.open_page()
        self.assertTrue(self.state.wait_for("settings_canvas_calls", timeout=3),
                        "API 设置页启动应预取专用画布 bootstrap，而不是读取旧六槽 defaults")
        self.assertEqual(self.state.canvas_get_calls, 0, "启动预取只读取 bootstrap，不应提前挂载隐藏编辑器")
        self.assertEqual(self.state.capability_calls, 0, "新版入口不得后台读取旧六槽能力目录")
        self.assertEqual(self.state.settings_calls, 0, "新版入口不得后台读取旧六槽已保存选择")
        self.assertEqual(self.state.settings_put_calls, 0)
        self.assertTrue(self.evaluate("window.prefetchHypitSettings()"), "启动预取请求应完成并缓存专用画布 bootstrap")
        self.assertEqual(self.state.settings_canvas_calls, 1, "重复预取必须复用已完成的 bootstrap")

        self.evaluate("window.openHypitSettings(); true")
        self.assertTrue(self.wait_for_canvas(), "点击 Hypit 后应挂载共享智能画布")
        self.assertTrue(self.state.wait_for("canvas_get_calls", timeout=3), "iframe 应通过标准画布 GET 读取唯一图")
        self.assertEqual(self.state.settings_canvas_calls, 1, "首次进入应复用启动预取的 bootstrap 响应")
        bootstrap_calls_after_open = self.state.settings_canvas_calls
        canvas_gets_after_open = self.state.canvas_get_calls
        first = self.evaluate("JSON.stringify({src:document.getElementById('hypitSettingsCanvasFrame').getAttribute('src'),sameId:new URL(document.getElementById('hypitSettingsCanvasFrame').src).searchParams.get('id'),mode:new URL(document.getElementById('hypitSettingsCanvasFrame').src).searchParams.get('mode'),element:(document.getElementById('hypitSettingsCanvasFrame').dataset.fixtureIdentity='same-frame','same-frame')})")
        self.assertEqual(json.loads(first)["sameId"], "hypit-settings", first)
        self.assertEqual(json.loads(first)["mode"], "hypit-settings", first)
        self.evaluate("window.closeHypitSettings(); window.openHypitSettings(); true")
        time.sleep(0.1)
        second = self.evaluate("JSON.stringify({src:document.getElementById('hypitSettingsCanvasFrame').getAttribute('src'),identity:document.getElementById('hypitSettingsCanvasFrame').dataset.fixtureIdentity})")
        self.assertEqual(json.loads(second)["src"], json.loads(first)["src"])
        self.assertEqual(json.loads(second)["identity"], "same-frame")
        self.assertEqual(self.state.settings_canvas_calls, bootstrap_calls_after_open, "重复进入应复用同一个 bootstrap 响应")
        self.assertEqual(self.state.canvas_get_calls, canvas_gets_after_open, "重复进入不能重载 iframe 或读取第二份图")
        self.assertEqual(self.state.settings_put_calls, 0, "预取和进入都不能 PUT 旧 defaults")

    def test_failed_canvas_bootstrap_can_retry_without_legacy_defaults(self):
        self.open_page(fail_first_canvas_bootstrap=True, hold_first_canvas_bootstrap=True)
        self.assertTrue(self.state.wait_for("settings_canvas_calls", timeout=3), "API 启动应尝试读取专用画布 bootstrap")
        # 等待网络响应前先挂接同一预取 Promise，避免测试因启动快慢而
        # 把显式预取误当成新的第二次请求。
        self.assertTrue(self.evaluate("window.__hypitPrefetchForTest = window.prefetchHypitSettings(); true"))
        with self.state.condition:
            self.state.canvas_bootstrap_release.set()
            self.state.condition.notify_all()
        prefetch_result = self.evaluate("window.__hypitPrefetchForTest")
        self.assertFalse(prefetch_result, "首次后台预取失败应返回 false，不写入旧 defaults")
        self.assertEqual(self.state.settings_canvas_calls, 1, "显式等待应复用启动中的预取请求")
        self.assertEqual(self.state.canvas_get_calls, 0, "失败的后台预取不应挂载标准画布")
        self.evaluate("window.openHypitSettings(); true")
        self.assertTrue(self.wait_for_canvas(), "bootstrap 失败后点击 Hypit 应重试并打开共享画布")
        self.assertTrue(self.state.wait_for("settings_canvas_calls", target=2, timeout=3), "失败 bootstrap 必须允许新请求重试")
        self.assertTrue(self.state.wait_for("canvas_get_responses", target=1, timeout=3),
                        "重试后的共享画布 GET 必须完整返回后再检查读取次数")
        self.assertTrue(self.evaluate("!document.getElementById('hypitSettingsCanvasFrame')?.hidden"),
                        "成功重试后应显示共享画布")
        self.assertEqual(self.state.canvas_get_calls, 1)
        self.assertEqual(self.state.capability_calls, 0)
        self.assertEqual(self.state.settings_calls, 0)
        self.assertEqual(self.state.settings_put_calls, 0)

    def test_provider_change_does_not_restart_canvas_or_write_legacy_defaults(self):
        self.open_page()
        self.assertTrue(self.state.wait_for("settings_canvas_calls", timeout=3), "API 启动应读取专用画布 bootstrap")
        self.evaluate("window.openHypitSettings(); true")
        self.assertTrue(self.wait_for_canvas(), "专用画布未加载")
        self.assertTrue(self.state.wait_for("canvas_get_calls", timeout=3))
        before = (self.state.settings_canvas_calls, self.state.canvas_get_calls)
        result = self.evaluate("""(async()=>{
          const provider=providers.find(item=>item.id==='fixture-provider');
          provider.image_models=['fixture-image-new'];
          return await scheduleProviderAutosave({providerId:provider.id,immediate:true,sync:false});
        })()""")
        self.assertTrue(result, "假服务端必须确认平台设置保存")
        self.evaluate("window.dispatchEvent(new CustomEvent('studio-api-change',{detail:{type:'providers-changed',updated_at:'fixture'}})); true")
        time.sleep(0.15)
        self.assertEqual((self.state.settings_canvas_calls,self.state.canvas_get_calls),before,
                         "平台变更不应重建专用画布或覆盖当前编辑会话")
        self.assertEqual(self.state.capability_calls,0,"平台变更不能唤起废弃的六槽目录读取")
        self.assertEqual(self.state.settings_calls,0,"平台变更不能读取废弃的六槽 defaults")
        self.assertEqual(self.state.settings_put_calls,0,"平台变更不能 PUT 废弃的六槽 defaults")

    def test_legacy_save_hook_cannot_write_defaults_in_shared_canvas_mode(self):
        self.open_page()
        self.evaluate("window.openHypitSettings(); true")
        self.assertTrue(self.wait_for_canvas(), "专用画布未加载")
        sync = json.loads(self.wait_for_canvas_sync(quiet_ms=500))
        self.assertTrue(sync["ok"], f"旧 hook 检查前画布初始化/同步未结束：{sync}")
        self.assertEqual(self.state.canvas_put_calls, 0, f"旧 hook 调用前不应混入启动迁移 PUT：{sync}")
        result = self.evaluate("window.saveHypitSettings()")
        self.assertFalse(result, "真实页面的旧六槽 save hook 必须拒绝写入")
        self.assertEqual(self.state.settings_put_calls,0)
        sync = json.loads(self.wait_for_canvas_sync(timeout=4, quiet_ms=500))
        self.assertTrue(sync["ok"], f"旧 hook 调用后画布同步状态未稳定：{sync}")
        self.assertEqual(self.state.canvas_put_calls,0,"旧 hook 在超过 450ms 的静默观察期内不能写入共享图")


if __name__ == "__main__":
    unittest.main()
