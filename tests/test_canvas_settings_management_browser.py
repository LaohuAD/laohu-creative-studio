"""画布模型管理入口的隔离 Chromium 回归。"""
from __future__ import annotations

import base64
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


def browser_binary():
    candidates = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    )
    return next((path for path in candidates if path and Path(path).is_file()), None)


CHROME = browser_binary()
NODE = shutil.which("node")


@unittest.skipUnless(CHROME and NODE, "需要本机 Chrome/Chromium 和 Node.js 执行隔离浏览器回归")
class CanvasSettingsManagementBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reset_state()

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
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    pass

            def _body(self):
                return json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/api/studio/canvas/settings-canvas":
                    type(self).owner.state["bootstrap_gets"] += 1
                    self._json(200, {
                        "id": "canvas-settings", "canvas": type(self).owner.state["canvas"],
                        "url": "/static/smart-canvas.html?id=canvas-settings&mode=canvas-settings",
                    })
                    return
                if path == "/api/canvases/canvas-settings":
                    type(self).owner.state["canvas_gets"] += 1
                    self._json(200, {"canvas": type(self).owner.state["canvas"]})
                    return
                if path == "/api/canvases/canvas-settings/meta":
                    canvas = type(self).owner.state["canvas"]
                    self._json(200, {"id": canvas["id"], "revision": canvas["revision"], "updated_at": canvas["updated_at"]})
                    return
                if path == "/api/studio/canvas/model-management-catalog":
                    type(self).owner.state["catalog_gets"] += 1
                    self._json(200, type(self).owner.catalog_payload())
                    return
                if path.startswith("/api/studio/model-options"):
                    self._json(200, type(self).owner.enabled_options_payload())
                    return
                if path == "/api/smart-canvas/personalization":
                    self._json(200, type(self).owner.state["personalization"])
                    return
                if path == "/api/providers":
                    self._json(200, {"providers": type(self).owner.state["providers"]})
                    return
                if path == "/api/config":
                    self._json(200, {"api_providers": type(self).owner.state["providers"], "comfy_instances": []})
                    return
                if path == "/api/model-capabilities":
                    self._json(200, type(self).owner.capability_payload())
                    return
                if path == "/api/app-info":
                    self._json(200, {"version": "fixture"})
                    return
                if path.startswith("/api/"):
                    type(self).owner.state["api_reads"].append(path)
                    self._json(200, {})
                    return
                super().do_GET()

            def do_PATCH(self):
                path = urlsplit(self.path).path
                body = self._body()
                type(self).owner.state["writes"].append(("PATCH", path, body))
                if path != "/api/studio/canvas/model-enablement":
                    self._json(403, {"detail": "isolated browser fixture blocks this PATCH"})
                    return
                if set(body) != {"option_id", "enabled", "catalog_revision"}:
                    self._json(400, {"detail": "expected exact-option patch"})
                    return
                option = next((item for item in type(self).owner.state["options"]
                               if item["option_id"] == body["option_id"]), None)
                if option is None or body["catalog_revision"] != type(self).owner.state["catalog_revision"]:
                    self._json(409, {"detail": "fixture option or revision mismatch"})
                    return
                option["enabled"] = body["enabled"]
                provider = next((item for item in type(self).owner.state["providers"]
                                 if item["id"] == option["connection_id"]), None)
                if provider is not None:
                    model_id = option["catalog_model_id"]
                    if body["enabled"] and model_id not in provider["image_models"]:
                        provider["image_models"].append(model_id)
                    elif not body["enabled"] and not any(
                        sibling["enabled"] and sibling["catalog_model_id"] == model_id
                        and sibling["connection_id"] == option["connection_id"]
                        and sibling["region_id"] == option["region_id"]
                        for sibling in type(self).owner.state["options"]
                    ):
                        provider["image_models"] = [value for value in provider["image_models"] if value != model_id]
                type(self).owner.state["catalog_revision"] = "fixture-catalog-next"
                self._json(200, {"option_id": option["option_id"], "enabled": option["enabled"],
                                 "catalog_revision": type(self).owner.state["catalog_revision"]})

            def do_PUT(self):
                path = urlsplit(self.path).path
                body = self._body()
                type(self).owner.state["writes"].append(("PUT", path, body))
                if path == "/api/smart-canvas/personalization":
                    type(self).owner.state["personalization"] = body
                    self._json(200, body)
                    return
                if path == "/api/canvases/canvas-settings":
                    canvas = type(self).owner.state["canvas"]
                    if body.get("base_revision") != canvas["revision"]:
                        self._json(409, {"detail": {"canvas": canvas}})
                        return
                    graph = {key: value for key, value in body.items()
                             if key not in {"base_revision", "base_updated_at", "client_id", "migration_version"}}
                    migration_version = int(body.get("migration_version") or 0)
                    if migration_version:
                        graph["node_schema_version"] = max(
                            int(canvas.get("node_schema_version") or 0), migration_version,
                        )
                    type(self).owner.state["canvas"] = {
                        **canvas, **graph, "revision": canvas["revision"] + 1,
                        "updated_at": canvas["updated_at"] + 1,
                    }
                    self._json(200, {"canvas": type(self).owner.state["canvas"]})
                    return
                self._json(403, {"detail": "isolated fixture blocks provider/config writes"})

            def do_POST(self):
                path = urlsplit(self.path).path
                body = self._body()
                type(self).owner.state["writes"].append(("POST", path, body))
                if path == "/api/studio/canvas/settings-canvas/reset":
                    canvas = type(self).owner.state["canvas"]
                    if body.get("base_revision") != canvas["revision"]:
                        self._json(409, {"detail": {"canvas": canvas}})
                        return
                    type(self).owner.state["canvas"] = {
                        **canvas, "nodes": [], "connections": [], "logs": [], "settings": {},
                        "viewport": {"x": 0, "y": 0, "scale": 1},
                        "revision": canvas["revision"] + 1, "updated_at": canvas["updated_at"] + 1,
                    }
                    self._json(200, {"id": "canvas-settings", "canvas": type(self).owner.state["canvas"], "reset": True})
                    return
                if path == "/api/smart-canvas/personalization/reset":
                    preferences = type(self).owner.state["personalization"]
                    if body.get("scope") != "node" or not body.get("option_id") or not body.get("node_type"):
                        self._json(400, {"detail": "expected exact node reset"})
                        return
                    option_id = body["option_id"]
                    option = next((item for item in type(self).owner.state["options"]
                                   if item["option_id"] == option_id and item["node_type"] == body["node_type"]), None)
                    if option is None:
                        self._json(409, {"detail": "unknown exact option"})
                        return
                    preferences["parameterPresentation"].pop(option_id, None)
                    provider_id = option["connection_id"]
                    family_id = option["canonical_family_id"]
                    node_type = option["node_type"]
                    layout_key = "::".join((node_type, provider_id, family_id, option["catalog_model_id"]))
                    for key in list(preferences["parameterOptionOrder"]):
                        if key.startswith(f"parameter-options::{layout_key}::"):
                            preferences["parameterOptionOrder"].pop(key, None)
                    preferences["executionLayouts"].pop(layout_key, None)
                    for key in list(preferences["modelOrder"]):
                        if key in {f"families::{node_type}", f"platforms::{node_type}"} or key.startswith(f"families::{node_type}::"):
                            preferences["modelOrder"].pop(key, None)
                    preferences["reset_epoch"] += 1
                    self._json(200, {"ok": True, "personalization": preferences})
                    return
                if path == "/api/agent/canvases/canvas-settings/commands":
                    type(self).owner.state["agent_commands"].append(body)
                    self._json(200, {"id": "fixture-command", "status": "succeeded", "result": {}})
                    return
                self._json(403, {"detail": "isolated fixture blocks generation/provider submissions"})

        Handler.owner = cls
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.debug_port = probe.getsockname()[1]
        cache = ROOT / "cache" / "studio-tests" / "tmp"
        cache.mkdir(parents=True, exist_ok=True)
        cls.profile = cache / f"canvas-settings-management-browser-{int(time.time())}"
        cls.profile.mkdir(parents=True, exist_ok=True)
        cls.chrome = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--window-size=1440,1000", "--force-device-scale-factor=1",
            f"--user-data-dir={cls.profile}", f"--remote-debugging-port={cls.debug_port}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.target = cls._wait_target()
        if not cls.target:
            cls.tearDownClass()
            raise unittest.SkipTest("Chrome 未能暴露隔离调试目标")
        script = r"""const readline=require('readline');const ws=new WebSocket(process.argv[1]);const input=readline.createInterface({input:process.stdin});ws.onopen=()=>{console.log(JSON.stringify({ready:true}));input.on('line',line=>{const q=JSON.parse(line);ws.send(JSON.stringify({id:q.id,method:q.method,params:q.params||{}}));});};ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id!==undefined)console.log(JSON.stringify({id:m.id,result:m.result||{},error:m.error||null}));};"""
        cls.cdp_process = subprocess.Popen([NODE, "-e", script, cls.target["webSocketDebuggerUrl"]],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL, text=True, bufsize=1)
        if not json.loads(cls.cdp_process.stdout.readline() or "{}").get("ready"):
            cls.tearDownClass()
            raise unittest.SkipTest("无法建立 CDP 会话")
        cls.request_id = 0
        cls.cdp("Page.enable")
        cls.cdp("Runtime.enable")

    @classmethod
    def reset_state(cls):
        cls.state = {
            "canvas": {
                "id": "canvas-settings", "title": "画布模型设置", "project": "__canvas_settings__",
                "revision": 1, "updated_at": 1791158400000, "node_schema_version": 6,
                "nodes": [], "connections": [],
                "viewport": {"x": 0, "y": 0, "scale": 1}, "logs": [], "settings": {},
            },
            "providers": [{
                "id": "fixture-provider", "name": "Fixture API", "protocol": "openai",
                "enabled": True, "image_models": ["fixture-image-a"], "chat_models": [],
                "video_models": [], "audio_models": [], "disabled_model_options": [],
            }, {
                "id": "runninghub", "name": "RunningHub", "protocol": "runninghub",
                "enabled": True, "image_models": [], "chat_models": [], "video_models": [],
                "audio_models": [], "rh_regions": {
                    "global": {"enabled": True, "image_models": [], "chat_models": [], "video_models": [], "audio_models": [], "rh_apps": [], "rh_workflows": []},
                    "cn": {"enabled": False, "image_models": [], "chat_models": [], "video_models": [], "audio_models": [], "rh_apps": [], "rh_workflows": []},
                },
            }], "personalization": {
                "version": 1, "reset_epoch": 0, "executionLayouts": {}, "parameterOptionOrder": {}, "modelOrder": {},
                "parameterPresentation": {},
            },
            "options": [
                {"option_id": "fixture-option-enabled", "catalog_model_id": "fixture-image-a",
                 "node_type": "image_generation", "enabled": True, "readiness": "ready", "runnable": True,
                 "selectable": True, "validation_mode": "strict", "operation": "text_to_image",
                 "canonical_family_id": "fixture-image-family",
                 "canonical_family_label": {"zh": "测试图片模型", "en": "Fixture Image"},
                 "display_mode": "A 标准模式", "variant_id": "fixture-image-a-v1",
                 "connection_id": "fixture-provider", "capability_provider_id": "fixture-provider",
                 "platform_label": "Fixture API", "region_id": "", "inputs": {
                     "prompt": {"media_type": "text", "role": "prompt", "min": 1, "max": 1},
                 }, "output": {"media_type": "image", "min": 1, "max": 1}, "parameters": {
                     "quality": {"type": "enum", "options": ["standard", "high"], "default": "standard", "required": True},
                     "seed": {"type": "integer", "min": 0, "max": 99, "required": True},
                 }},
                {"option_id": "fixture-option-disabled", "catalog_model_id": "fixture-image-a",
                 "node_type": "image_generation", "enabled": False, "readiness": "ready", "runnable": True,
                 "selectable": True, "validation_mode": "strict", "operation": "text_or_reference_to_image",
                 "canonical_family_id": "fixture-image-family",
                 "canonical_family_label": {"zh": "测试图片模型", "en": "Fixture Image"},
                 "display_mode": "A 图生图", "variant_id": "fixture-image-a-i2i",
                 "connection_id": "fixture-provider", "capability_provider_id": "fixture-provider",
                 "platform_label": "Fixture API", "region_id": "", "inputs": {
                     "prompt": {"media_type": "text", "role": "prompt", "min": 1, "max": 1},
                     "reference": {"media_type": "image", "role": "reference", "min": 0, "max": 1},
                 }, "output": {"media_type": "image", "min": 1, "max": 1}, "parameters": {
                     "quality": {"type": "enum", "options": ["standard", "high"], "default": "high", "required": True},
                     "seed": {"type": "integer", "min": 0, "max": 99, "required": True},
                 }},
            ],
            "catalog_revision": "fixture-catalog-1", "bootstrap_gets": 0, "canvas_gets": 0,
            "catalog_gets": 0, "api_reads": [], "writes": [], "agent_commands": [],
        }

    @classmethod
    def catalog_payload(cls):
        return {"options": json.loads(json.dumps(cls.state["options"])),
                # 生产管理端点同时返回完整的严格能力投影；它与普通启用候选分开，
                # 让管理画布能选择未启用项，而普通候选接口仍只返回 A。
                "catalog": cls.capability_payload(),
                "catalog_revision": cls.state["catalog_revision"], "selection_contract_version": 1}

    @classmethod
    def capability_payload(cls):
        profiles = []
        for option in cls.state["options"]:
            profiles.append({
                **option,
                "provider_id": option["connection_id"],
                "provider_name": "Fixture API",
                "model_id": option["catalog_model_id"],
                "family_id": option["canonical_family_id"],
                "family_name": option["canonical_family_label"]["zh"],
                "family_name_en": option["canonical_family_label"]["en"],
                "variant_name": option["display_mode"],
                "variant_name_en": option["display_mode"],
            })
        families_by_key = {}
        for profile in profiles:
            key = (profile["canonical_family_id"], profile["node_type"])
            family = families_by_key.setdefault(key, {
                "family_id": key[0],
                "display_name": profile["canonical_family_label"]["zh"],
                "display_name_en": profile["canonical_family_label"]["en"],
                "family_name": profile["canonical_family_label"]["zh"],
                "family_name_en": profile["canonical_family_label"]["en"],
                "canonical_family_label": profile["canonical_family_label"],
                "node_type": key[1],
                "variants": [],
            })
            family["variants"].append(profile)
        return {"schema_version": 1, "providers": [{
            "id": "fixture-provider", "name": "Fixture API", "protocol": "openai",
            "models": profiles, "families": list(families_by_key.values()),
        }]}

    @classmethod
    def enabled_options_payload(cls):
        return {"module_id": "canvas", "selection_policy": "multiple", "options": [
            option for option in json.loads(json.dumps(cls.state["options"])) if option["enabled"]
        ], "catalog_revision": cls.state["catalog_revision"]}

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
        profile = getattr(cls, "profile", None)
        if profile:
            shutil.rmtree(profile, ignore_errors=True)

    @classmethod
    def _wait_target(cls):
        import urllib.request
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cls.debug_port}/json/list", timeout=2) as response:
                    for target in json.loads(response.read().decode("utf-8")):
                        if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                            return target
            except Exception:
                time.sleep(0.2)
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
            raise AssertionError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    def setUp(self):
        self.cdp("Page.navigate", {"url": "about:blank"})
        self.assertTrue(self.evaluate("(async()=>{for(let i=0;i<80;i++){if(location.href==='about:blank')return true;await new Promise(r=>setTimeout(r,10));}return false;})()"))
        type(self).reset_state()

    def wait_for(self, expression, message, timeout=12):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.evaluate(expression):
                    return
            except AssertionError:
                pass
            time.sleep(0.05)
        self.fail(message() if callable(message) else message)

    def open_settings_canvas(self):
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/static/api-settings.html"})
        self.wait_for("document.readyState==='complete'&&!!document.getElementById('canvasModelsNav')",
                      "API 设置页没有加载")
        self.evaluate("document.getElementById('canvasModelsNav').click(); true")
        self.wait_for("(()=>{const f=document.getElementById('canvasSettingsCanvasFrame');return !!f&&!f.hidden&&f.contentWindow?.location?.pathname==='/static/smart-canvas.html'&&!!f.contentWindow.document.getElementById('world')})()",
                      "画布模型入口没有加载共享 settings canvas")
        deadline = time.time() + 8
        while time.time() < deadline and type(self).state["canvas_gets"] == 0:
            time.sleep(0.03)
        self.assertGreater(type(self).state["canvas_gets"], 0, "共享画布加载后必须读取标准 canvas GET")

    def frame_eval(self, expression):
        return self.evaluate(
            "document.getElementById('canvasSettingsCanvasFrame').contentWindow.eval(" + json.dumps(expression) + ")"
        )

    def scroll_frame_into_outer_view(self):
        """用真实滚轮把嵌入画布移入外层窗口，避免离屏坐标制造假失败。"""
        for _ in range(4):
            metrics = json.loads(self.evaluate(
                "JSON.stringify((()=>{const frame=document.getElementById('canvasSettingsCanvasFrame');"
                "const rect=frame.getBoundingClientRect();return {viewport:innerHeight,scrollY,"
                "frame:{top:rect.top,bottom:rect.bottom,height:rect.height}}})())"
            ))
            if metrics["frame"]["top"] >= 0 and metrics["frame"]["bottom"] <= metrics["viewport"]:
                return metrics
            # API 页的右侧留白在 iframe 之外，滚轮事件会滚动外层文档。
            x = max(8, self.evaluate("innerWidth") - 8)
            y = max(8, min(metrics["viewport"] - 8, metrics["frame"]["bottom"] - 24))
            delta = 100 if metrics["frame"]["bottom"] > metrics["viewport"] else -100
            previous = metrics["scrollY"]
            self.cdp("Input.dispatchMouseEvent", {
                "type": "mouseMoved", "x": x, "y": y,
            })
            self.cdp("Input.dispatchMouseEvent", {
                "type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": delta,
            })
            self.wait_for(
                f"document.getElementById('canvasSettingsCanvasFrame').getBoundingClientRect().bottom<={metrics['viewport']}"
                if delta > 0 else
                f"document.getElementById('canvasSettingsCanvasFrame').getBoundingClientRect().top>=0",
                lambda: f"真实滚轮没有滚动外层设置页：before={metrics}", timeout=2,
            )
            current = self.evaluate("scrollY")
            self.assertNotEqual(current, previous, f"外层滚轮没有移动页面：{metrics}")
        metrics = json.loads(self.evaluate(
            "JSON.stringify((()=>{const r=document.getElementById('canvasSettingsCanvasFrame').getBoundingClientRect();"
            "return {viewport:innerHeight,scrollY,top:r.top,bottom:r.bottom}})())"
        ))
        self.assertGreaterEqual(metrics["top"], 0, metrics)
        self.assertLessEqual(metrics["bottom"], metrics["viewport"], metrics)
        return metrics

    def pointer_click_in_frame(self, selector):
        """按子文档真实命中点点击，并返回坐标与命中元素供回归诊断。"""
        point = json.loads(self.evaluate(
            "JSON.stringify((()=>{const frame=document.getElementById('canvasSettingsCanvasFrame');const doc=frame?.contentDocument;"
            f"const target=doc?.querySelector({json.dumps(selector)});"
            "if(!frame||!target)return null;const fr=frame.getBoundingClientRect(),r=target.getBoundingClientRect();"
            "const x=r.left+r.width/2,y=r.top+r.height/2,hit=doc.elementFromPoint(x,y);"
            "return {x:fr.left+x*(fr.width/frame.clientWidth),y:fr.top+y*(fr.height/frame.clientHeight),"
            "frame:fr.toJSON(),target:r.toJSON(),hit:hit?.outerHTML?.slice(0,180)||'',"
            "targetHit:!!hit&&(target===hit||target.contains(hit)),viewport:{width:innerWidth,height:innerHeight}}})())"
        ))
        self.assertIsNotNone(point, f"找不到点击目标：{selector}")
        self.assertTrue(point["targetHit"], f"目标被画布内其他浮层遮挡：{selector}，{point}")
        self.assertGreaterEqual(point["y"], 0, point)
        self.assertLess(point["y"], point["viewport"]["height"], point)
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": point["x"], "y": point["y"]})
        self.cdp("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": point["x"], "y": point["y"],
            "button": "left", "buttons": 1, "clickCount": 1,
        })
        self.cdp("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": point["x"], "y": point["y"],
            "button": "left", "buttons": 0, "clickCount": 1,
        })
        return point

    def capture_acceptance_screenshot(self, name):
        destination = ROOT / "cache" / "studio-tests" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = self.cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        destination.write_bytes(base64.b64decode(result["data"]))
        return destination

    def drag_in_frame(self, source_selector, target_selector, target_x_ratio=0.5, target_y_ratio=0.5):
        coordinates = self.evaluate("(() => {\n"
            "const frame=document.getElementById('canvasSettingsCanvasFrame');"
            "const doc=frame?.contentDocument;"
            f"const source=doc?.querySelector({json.dumps(source_selector)});"
            f"const target=doc?.querySelector({json.dumps(target_selector)});"
            f"const targetXRatio={float(target_x_ratio)!r},targetYRatio={float(target_y_ratio)!r};"
            "if(!frame||!source||!target)return null;"
            "const fr=frame.getBoundingClientRect(),sr=source.getBoundingClientRect(),tr=target.getBoundingClientRect();"
            "const sx=fr.left+(sr.left+sr.width/2)*(fr.width/frame.clientWidth);"
            "const sy=fr.top+(sr.top+sr.height/2)*(fr.height/frame.clientHeight);"
            "const tx=fr.left+(tr.left+tr.width*targetXRatio)*(fr.width/frame.clientWidth);"
            "const ty=fr.top+(tr.top+tr.height*targetYRatio)*(fr.height/frame.clientHeight);"
            "const hit=doc.elementFromPoint(sr.left+sr.width/2,sr.top+sr.height/2);"
            "return {sx,sy,tx,ty,frame:fr.toJSON(),frameClient:{width:frame.clientWidth,height:frame.clientHeight},source:sr.toJSON(),target:tr.toJSON(),sourceHit:hit?.outerHTML?.slice(0,180)||''};})()")
        self.assertIsNotNone(coordinates, f"未找到拖动柄：{source_selector} -> {target_selector}")
        sx, sy, tx, ty = (coordinates[key] for key in ("sx", "sy", "tx", "ty"))
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": sx, "y": sy})
        # hover 可能切换预览标签或收到并发画布快照；按实际 pointerdown 前的 DOM 再校准一次坐标。
        after_hover = self.evaluate("(() => {"
            "const frame=document.getElementById('canvasSettingsCanvasFrame');const doc=frame?.contentDocument;"
            f"const source=doc?.querySelector({json.dumps(source_selector)});"
            f"const target=doc?.querySelector({json.dumps(target_selector)});"
            f"const targetXRatio={float(target_x_ratio)!r},targetYRatio={float(target_y_ratio)!r};"
            "if(!frame||!source||!target)return null;const fr=frame.getBoundingClientRect();"
            "const sr=source.getBoundingClientRect(),tr=target.getBoundingClientRect();"
            "const hit=doc.elementFromPoint(sr.left+sr.width/2,sr.top+sr.height/2);"
            "return {sx:fr.left+(sr.left+sr.width/2)*(fr.width/frame.clientWidth),"
            "sy:fr.top+(sr.top+sr.height/2)*(fr.height/frame.clientHeight),"
            "tx:fr.left+(tr.left+tr.width*targetXRatio)*(fr.width/frame.clientWidth),"
            "ty:fr.top+(tr.top+tr.height*targetYRatio)*(fr.height/frame.clientHeight),"
            "source:sr.toJSON(),target:tr.toJSON(),sourceHit:hit?.outerHTML?.slice(0,180)||'',"
            "sourceHitRect:hit?.getBoundingClientRect?.().toJSON()||null,sourceHitMatches:!!hit&&(source===hit||source.contains(hit)),"
            "sourceConnected:source.isConnected,scope:source.dataset.preferenceScope||''};})()")
        self.assertIsNotNone(after_hover, f"hover 后排序柄或目标被重绘移除：{source_selector} -> {target_selector}")
        self.assertTrue(after_hover["sourceHitMatches"],
                        f"真实指针命中点被其他浮层覆盖：{source_selector}，{after_hover}")
        sx, sy, tx, ty = (after_hover[key] for key in ("sx", "sy", "tx", "ty"))
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": sx, "y": sy})
        self.cdp("Input.dispatchMouseEvent", {"type": "mousePressed", "x": sx, "y": sy,
                                               "button": "left", "buttons": 1, "clickCount": 1})
        after_press = self.frame_eval("JSON.stringify({preference:typeof smartPreferencePointerDragState==='undefined'?null:smartPreferencePointerDragState&&{scope:smartPreferencePointerDragState.scope,button:smartPreferencePointerDragState.button?.dataset.preferenceId,order:smartPreferencePointerDragState.originalOrder.map(item=>item.dataset.preferenceId)},parameter:typeof smartParameterPresentationDragState==='undefined'?null:smartParameterPresentationDragState&&{optionId:smartParameterPresentationDragState.optionId,key:smartParameterPresentationDragState.row?.dataset.parameterKey,pointerId:smartParameterPresentationDragState.pointerId,moved:smartParameterPresentationDragState.moved,original:smartParameterPresentationDragState.originalOrder.map(item=>item.dataset.parameterKey),current:capabilityPresentationRows(smartParameterPresentationDragState.container,smartParameterPresentationDragState.optionId).map(item=>item.dataset.parameterKey)}})")
        for fraction in (0.25, 0.5, 0.75, 1.0):
            self.cdp("Input.dispatchMouseEvent", {
                "type": "mouseMoved", "x": sx + (tx - sx) * fraction,
                "y": sy + (ty - sy) * fraction, "button": "left", "buttons": 1,
            })
            time.sleep(0.035)
        before_release = self.frame_eval("JSON.stringify({preference:typeof smartPreferencePointerDragState==='undefined'?null:smartPreferencePointerDragState&&{moved:smartPreferencePointerDragState.moved,order:smartPreferencePointerDragState.list&&[...smartPreferencePointerDragState.list.children].map(item=>item.dataset.preferenceId)},parameter:typeof smartParameterPresentationDragState==='undefined'?null:smartParameterPresentationDragState&&{optionId:smartParameterPresentationDragState.optionId,key:smartParameterPresentationDragState.row?.dataset.parameterKey,pointerId:smartParameterPresentationDragState.pointerId,moved:smartParameterPresentationDragState.moved,original:smartParameterPresentationDragState.originalOrder.map(item=>item.dataset.parameterKey),current:capabilityPresentationRows(smartParameterPresentationDragState.container,smartParameterPresentationDragState.optionId).map(item=>item.dataset.parameterKey)}})")
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": tx, "y": ty,
                                               "button": "left", "buttons": 0, "clickCount": 1})
        after_release = self.frame_eval("JSON.stringify({preference:typeof smartPreferencePointerDragState==='undefined'?null:smartPreferencePointerDragState,parameter:typeof smartParameterPresentationDragState==='undefined'?null:smartParameterPresentationDragState,rows:[...document.querySelectorAll('.capability-summary-popover [data-parameter-option-id][data-parameter-key]')].map(item=>item.dataset.parameterKey)})")
        return {"coordinates": coordinates, "after_hover": after_hover, "after_press": after_press,
                "before_release": before_release, "after_release": after_release}

    def test_api_settings_opens_dedicated_graph_in_shared_canvas_shell(self):
        self.open_settings_canvas()
        details = self.evaluate("(() => {const frame=document.getElementById('canvasSettingsCanvasFrame');return {src:frame.src, hidden:frame.hidden, status:document.getElementById('canvasSettingsStatus')?.textContent||''}})()")
        self.assertIn("id=canvas-settings", details["src"], details)
        self.assertIn("mode=canvas-settings", details["src"], details)
        self.assertIn("embedded=1", details["src"], details)
        self.assertFalse(details["hidden"], details)
        self.assertEqual(self.frame_eval("document.documentElement.dataset.canvasMode"), "canvas-settings")
        self.assertEqual(type(self).state["bootstrap_gets"], 1)
        self.assertEqual(type(self).state["canvas_gets"], 1)
        self.assertEqual(type(self).state["canvas"]["nodes"], [])
        self.assertEqual(type(self).state["canvas"]["connections"], [])
        self.assertFalse(type(self).state["agent_commands"], "只打开管理画布不能运行节点")

    def test_runninghub_site_switches_show_red_off_green_on_without_saving_changes(self):
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/static/api-settings.html"})
        self.wait_for("document.readyState==='complete'&&!!document.getElementById('providerList')",
                      "API 设置页没有加载 RunningHub 假数据")
        self.wait_for("!!document.querySelector('.runninghub-provider-card .provider-card-main')",
                      lambda: "RunningHub 左栏入口未加载：" + str(self.evaluate("JSON.stringify({url:location.href,providers:document.getElementById('providerList')?.innerHTML,body:document.body.innerText.slice(0,500)})")))
        self.evaluate("document.querySelector('.runninghub-provider-card .provider-card-main').click();true")
        self.wait_for("!!document.getElementById('rhGlobalEnabledInput')&&!!document.getElementById('rhCnEnabledInput')",
                      lambda: "RunningHub 站点开关没有渲染：" + str(self.evaluate("JSON.stringify({url:location.href,global:!!document.getElementById('rhGlobalEnabledInput'),cn:!!document.getElementById('rhCnEnabledInput'),content:document.getElementById('settingsContent')?.innerText.slice(0,500)})")))
        state = self.evaluate("JSON.stringify(['global','cn'].map(region=>{const input=document.getElementById(region==='global'?'rhGlobalEnabledInput':'rhCnEnabledInput');return {region,checked:input.checked,label:input.closest('.rh-region-switch')?.innerText.trim(),track:getComputedStyle(input.nextElementSibling).backgroundColor}}))")
        observed = json.loads(state)
        self.assertEqual([(item["region"], item["checked"], item["track"]) for item in observed], [
            ("global", True, "rgb(22, 163, 74)"),
            ("cn", False, "rgb(220, 38, 38)"),
        ], observed)
        self.assertFalse(type(self).state["writes"], "只读核对站点状态不能触发保存")

    def test_formal_canvas_picker_keeps_model_and_parameter_order_read_only(self):
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/static/smart-canvas.html?id=canvas-settings"})
        self.wait_for("document.readyState==='complete'&&!!document.getElementById('world')",
                      "普通画布页没有加载")
        self.wait_for("document.documentElement.dataset.canvasSettings!=='true'",
                      "正式画布不能进入设置管理模式")
        self.evaluate("document.getElementById('shell').dispatchEvent(new MouseEvent('dblclick',{bubbles:true,clientX:760,clientY:320}));true")
        self.wait_for("!!document.querySelector('.create-menu.open')", "空白画布双击没有打开添加菜单")
        self.evaluate("document.querySelector('[data-create-type=\\\"image-generator\\\"]').click();true")
        self.wait_for("!!document.querySelector('.image-node')", "添加菜单没有创建图片节点")
        self.wait_for("!!document.querySelector('[data-capability-model-picker] .capability-model-picker-pill')",
                      lambda: "正式图片节点选择器未挂载：" + str(self.evaluate("JSON.stringify({node:document.querySelector('.image-node')?.outerHTML?.slice(0,1200),body:document.body.innerText.slice(0,300)})")))
        self.evaluate("document.querySelector('[data-capability-model-picker] .capability-model-picker-pill').click();true")
        self.wait_for("!!document.querySelector('[data-capability-picker-stage=variant] [data-capability-picker-option]')",
                      "正式候选模式没有渲染")
        self.assertEqual(self.evaluate("JSON.stringify({canvasSettings:document.documentElement.dataset.canvasSettings||'',handles:document.querySelectorAll('[data-preference-sort-handle],[data-capability-option-sort-handle],[data-parameter-presentation-order-handle]').length,stages:[...new Set([...document.querySelectorAll('[data-capability-picker-stage]')].map(item=>item.dataset.capabilityPickerStage))]})"),
                         '{"canvasSettings":"","handles":0,"stages":["family","platform","variant"]}')
        self.assertFalse(type(self).state["writes"], "正式候选只读展示不应保存展示排序偏好")

    def test_display_order_and_parameter_presentation_do_not_toggle_global_enablement(self):
        self.open_settings_canvas()
        self.wait_for("typeof document.getElementById('canvasSettingsCanvasFrame').contentWindow.saveSmartCanvasPersonalization==='function'",
                      "共享画布个性化函数没有加载")
        before = [item["enabled"] for item in type(self).state["options"]]
        self.frame_eval("smartCanvasPersonalizationStore().modelOrder['image_generation']=['fixture-option-disabled','fixture-option-enabled'];smartCanvasPersonalizationStore().parameterPresentation={'fixture-option-enabled':{'quality':{visible:false,width:'half'}}};saveSmartCanvasPersonalization();true")
        self.wait_for("true", "偏好请求完成", timeout=0.2)
        deadline = time.time() + 4
        while time.time() < deadline and not any(path == "/api/smart-canvas/personalization" for _method, path, _body in type(self).state["writes"]):
            time.sleep(0.03)
        writes = type(self).state["writes"]
        prefs = [body for method, path, body in writes if method == "PUT" and path == "/api/smart-canvas/personalization"]
        self.assertTrue(prefs, writes)
        self.assertEqual(prefs[-1]["modelOrder"]["image_generation"], ["fixture-option-disabled", "fixture-option-enabled"])
        self.assertEqual(prefs[-1]["reset_epoch"], 0)
        self.assertEqual(prefs[-1]["parameterPresentation"]["fixture-option-enabled"]["quality"], {"width": "half"})
        self.assertNotIn("visible", prefs[-1]["parameterPresentation"]["fixture-option-enabled"]["quality"])
        self.assertEqual([item["enabled"] for item in type(self).state["options"]], before)
        self.assertFalse(any(path == "/api/studio/canvas/model-enablement" for _method, path, _body in writes))

    def test_management_picker_enables_one_exact_option_and_updates_normal_candidates(self):
        extra = json.loads(json.dumps(type(self).state["options"][0]))
        extra.update({
            "option_id": "fixture-option-sort-extra", "catalog_model_id": "fixture-image-c",
            "enabled": False, "display_mode": "C 标准模式", "variant_id": "fixture-image-c-v1",
        })
        type(self).state["options"].append(extra)
        type(self).state["personalization"]["parameterPresentation"]["fixture-option-disabled"] = {
            "quality": {"visible": False, "width": "half", "order": 0},
        }
        self.open_settings_canvas()
        outer_frame = self.scroll_frame_into_outer_view()
        deadline = time.time() + 8
        while time.time() < deadline and type(self).state["catalog_gets"] == 0:
            time.sleep(0.03)
        self.assertGreater(type(self).state["catalog_gets"], 0, "管理模式没有请求精确目录")
        self.assertEqual(self.frame_eval("canvasModelManagementCatalog.options.length"), 3)
        frame = "document.getElementById('canvasSettingsCanvasFrame').contentWindow"
        self.frame_eval("fetch('/api/studio/model-options?module_id=canvas&slot_id=image').then(r=>r.json()).then(v=>window.__beforeEnablement=v);true")
        self.wait_for(f"{frame}.__beforeEnablement?.options?.length===1", "普通候选初始状态未排除禁用项")
        before_offered = self.frame_eval("window.__beforeEnablement.options.map(item=>item.catalog_model_id)")
        self.assertEqual(before_offered, ["fixture-image-a"])

        # 通过真实添加菜单创建节点，再按模型、平台、运行模式打开管理第四栏。
        self.frame_eval("document.getElementById('shell').dispatchEvent(new MouseEvent('dblclick',{bubbles:true,clientX:760,clientY:320}));true")
        self.wait_for(f"{frame}.document.querySelector('.create-menu.open')!==null", "空白画布双击没有打开添加菜单")
        self.frame_eval("document.querySelector('[data-create-type=\\\"image-generator\\\"]').click();true")
        self.wait_for(f"{frame}.document.querySelector('.image-node')!==null", "添加菜单没有创建图片生成节点")
        self.wait_for(f"{frame}.document.querySelector('[data-capability-model-picker] .capability-model-picker-pill')!==null",
                      "图片节点没有展示共享模型选择器")
        self.frame_eval("document.querySelector('[data-capability-model-picker] .capability-model-picker-pill').click();true")
        self.wait_for(f"{frame}.document.querySelector('[data-capability-picker-stage=family] [data-capability-picker-option]')!==null",
                      lambda: "管理目录没有渲染模型家族：" + str(self.frame_eval("JSON.stringify({picker:document.querySelector('[data-capability-model-picker]')?.outerHTML,stages:[...document.querySelectorAll('[data-capability-picker-stage]')].map(item=>({stage:item.dataset.capabilityPickerStage,html:item.innerHTML.slice(0,800)})),selected:document.querySelector('.image-node')?.innerText})")))
        self.frame_eval("document.querySelector('[data-capability-picker-stage=family] [data-capability-picker-option]').click();true")
        self.wait_for(f"{frame}.document.querySelector('[data-capability-picker-stage=platform] [data-capability-picker-option]')!==null",
                      "选择家族后没有渲染平台")
        self.frame_eval("document.querySelector('[data-capability-picker-stage=platform] [data-capability-picker-option]').click();true")
        self.wait_for(f"{frame}.document.querySelector('[data-capability-picker-stage=variant] [data-capability-picker-option]')!==null",
                      "选择平台后没有渲染运行模式")
        stage_handles = self.frame_eval("JSON.stringify(Object.fromEntries(['family','platform','variant'].map(stage=>[stage,document.querySelectorAll(`[data-capability-picker-stage=\\\"${stage}\\\"] [data-preference-sort-handle]`).length])))")
        counts = json.loads(stage_handles)
        self.assertEqual((counts["family"], counts["platform"]), (1, 1), counts)
        self.assertGreaterEqual(counts["variant"], 2,
                         self.frame_eval("JSON.stringify({options:[...document.querySelectorAll('[data-capability-picker-stage=variant] button[data-preference-id]')].map(item=>({id:item.dataset.capabilityPickerOptionId,operation:item.dataset.capabilityPickerOperation,text:item.innerText})),models:canvasModelManagementCatalog.catalog.providers.flatMap(p=>p.models).map(p=>({id:p.option_id,model:p.model_id,operation:p.operation}))})"))
        variant_scope = self.frame_eval("document.querySelector('[data-capability-picker-stage=variant] [data-preference-sort-handle]')?.dataset.preferenceScope||''")
        before_variant_order = self.frame_eval("JSON.stringify([...document.querySelectorAll('[data-capability-picker-stage=variant] button[data-preference-id]')].map(item=>item.dataset.preferenceId))")
        before_order = json.loads(before_variant_order)
        self.assertTrue(variant_scope.startswith("variants::image_generation::"), variant_scope)
        self.assertGreaterEqual(len(before_order), 2)
        self.assertEqual(self.frame_eval("document.querySelectorAll('[data-model-order-move],[data-parameter-order-move]').length"), 0)
        self.frame_eval("window.__dragEvents=[];['pointerdown','pointermove','pointerup','pointercancel'].forEach(t=>document.addEventListener(t,e=>window.__dragEvents.push({type:t,x:e.clientX,y:e.clientY,pointerId:e.pointerId,button:e.button,defaultPrevented:e.defaultPrevented,handleScope:e.target?.closest?.('[data-preference-sort-handle]')?.dataset.preferenceScope||'',target:e.target?.outerHTML?.slice(0,100),hit:document.elementFromPoint(e.clientX,e.clientY)?.outerHTML?.slice(0,100)}),true));true")
        drag_coords = self.drag_in_frame(
            '[data-capability-picker-stage="variant"] button[data-preference-id]:first-of-type [data-preference-sort-handle]',
            '[data-capability-picker-stage="variant"] button[data-preference-id]:last-of-type [data-preference-sort-handle]',
        )
        self.wait_for("true", "模式顺序写回完成", timeout=0.2)
        expected_order = before_order[1:] + before_order[:1]
        deadline = time.time() + 4
        while time.time() < deadline:
            saved_orders = [body.get("modelOrder", {}).get(variant_scope)
                            for method, path, body in type(self).state["writes"]
                            if method == "PUT" and path == "/api/smart-canvas/personalization"]
            if saved_orders and saved_orders[-1] == expected_order:
                break
            time.sleep(0.03)
        drag_debug = {
            "coords": drag_coords,
            "events": self.frame_eval("JSON.stringify(window.__dragEvents||[])") ,
            "order": self.frame_eval("JSON.stringify([...document.querySelectorAll('[data-capability-picker-stage=variant] button[data-preference-id]')].map(item=>item.dataset.preferenceId))"),
        }
        self.assertTrue(saved_orders and saved_orders[-1] == expected_order,
                        "候选拖动后未按实际移动顺序保存：" + str(drag_debug))
        clicked = self.frame_eval("(()=>{const option=document.querySelector('[data-capability-picker-stage=variant] [data-capability-picker-option-id=\\\"fixture-option-disabled\\\"]');if(!option)return false;option.click();return true})()")
        self.assertTrue(clicked, "管理目录里的同模型图生图 operation 必须能按 option_id 精确选择试跑")
        toggle_selector = "[data-capability-picker-stage=management] input[data-model-enablement-toggle][data-model-enablement-option-id='fixture-option-disabled']"
        deadline = time.time() + 8
        selected_identity = {}
        while time.time() < deadline:
            selected_identity = json.loads(self.frame_eval("JSON.stringify(nodes.find(n=>n.type==='smart-image-generator')?.modelSelection||{})"))
            persisted = next((item for item in type(self).state["canvas"]["nodes"]
                              if item.get("type") == "smart-image-generator"), {})
            persisted_identity = persisted.get("modelSelection") or {}
            if (selected_identity.get("option_id") == "fixture-option-disabled"
                    and selected_identity.get("operation") == "text_or_reference_to_image"
                    and persisted_identity.get("option_id") == "fixture-option-disabled"
                    and persisted_identity.get("operation") == "text_or_reference_to_image"):
                break
            time.sleep(0.05)
        self.assertEqual((selected_identity.get("option_id"), selected_identity.get("operation")),
                         ("fixture-option-disabled", "text_or_reference_to_image"),
                         "选中运行模式后必须把精确身份写入真实节点对象：" + str(selected_identity))
        persisted = next((item for item in type(self).state["canvas"]["nodes"]
                          if item.get("type") == "smart-image-generator"), {})
        self.assertEqual((persisted.get("modelSelection", {}).get("option_id"),
                          persisted.get("modelSelection", {}).get("operation")),
                         ("fixture-option-disabled", "text_or_reference_to_image"),
                         "精确运行模式身份必须经标准画布 PUT 持久化：" + str(persisted.get("modelSelection")))
        self.assertGreaterEqual(type(self).state["canvas"].get("node_schema_version", 0), 7,
                                "fixture 的画布 PUT 必须按服务端迁移契约确认节点 schema 版本")
        self.assertFalse(self.frame_eval("(()=>{const t=document.getElementById('toast');return !!t?.classList.contains('show')&&t.innerText.includes('画布结构已更新')})()"),
                         "真实 schema migration_version 已确认后不能显示要求重启服务的误导提示")
        self.frame_eval("(()=>{const pill=document.querySelector('[data-capability-model-picker] .capability-model-picker-pill');if(pill?.getAttribute('aria-expanded')!=='true')pill?.click();return pill?.getAttribute('aria-expanded')})()")
        self.wait_for(f"{frame}.document.querySelector('[data-capability-picker-stage=management] input[data-model-enablement-toggle]')?.getBoundingClientRect().width>0",
                      "重新打开模型选择后管理第四栏没有可见开关")
        self.wait_for(
            f"{frame}.document.querySelector('[data-capability-model-picker]')?.classList.contains('pinned')"
            f"&&{frame}.getComputedStyle({frame}.document.querySelector('.capability-model-picker-popover')).visibility==='visible'"
            f"&&Number({frame}.getComputedStyle({frame}.document.querySelector('.capability-model-picker-popover')).opacity)>=0.99",
            "四栏模型选择浮层尚未完整显示",
        )
        toggle_js = json.dumps(toggle_selector)
        self.wait_for(f"{frame}.document.querySelector({toggle_js})!==null", "选中精确运行模式后未出现管理开关")
        self.assertFalse(self.frame_eval(f"document.querySelector({toggle_js}).checked"))
        self.assertEqual(self.frame_eval(f"getComputedStyle(document.querySelector({toggle_js}).nextElementSibling).backgroundColor"), "rgb(220, 38, 38)")
        self.capture_acceptance_screenshot("canvas-settings-management-fourth-column-off.png")
        switch_track = toggle_selector + " + .rh-switch-track"
        switch_hit = self.pointer_click_in_frame(switch_track)
        deadline = time.time() + 5
        while time.time() < deadline and not any(
            method == "PATCH" and path == "/api/studio/canvas/model-enablement"
            for method, path, _body in type(self).state["writes"]
        ):
            time.sleep(0.03)
        patches = [body for method, path, body in type(self).state["writes"]
                   if method == "PATCH" and path == "/api/studio/canvas/model-enablement"]
        self.assertEqual(patches, [{
            "option_id": "fixture-option-disabled", "enabled": True,
            "catalog_revision": "fixture-catalog-1",
        }])
        self.assertTrue(self.frame_eval(f"document.querySelector({toggle_js}).checked"))
        self.wait_for(
            f"getComputedStyle({frame}.document.querySelector({toggle_js}).nextElementSibling).backgroundColor==='rgb(22, 163, 74)'",
            "启用状态的绿色轨道没有完成状态更新",
        )
        self.assertEqual(self.frame_eval(f"getComputedStyle(document.querySelector({toggle_js}).nextElementSibling).backgroundColor"), "rgb(22, 163, 74)")
        self.frame_eval("(()=>{const pill=document.querySelector('[data-capability-model-picker] .capability-model-picker-pill');if(pill?.getAttribute('aria-expanded')!=='true')pill?.click();return pill?.getAttribute('aria-expanded')})()")
        self.wait_for(
            f"{frame}.document.querySelector('[data-capability-model-picker]')?.classList.contains('pinned')"
            f"&&{frame}.getComputedStyle({frame}.document.querySelector('.capability-model-picker-popover')).visibility==='visible'"
            f"&&Number({frame}.getComputedStyle({frame}.document.querySelector('.capability-model-picker-popover')).opacity)>=0.99",
            "启用后第四栏没有稳定显示",
        )
        self.capture_acceptance_screenshot("canvas-settings-management-fourth-column-on.png")
        self.assertEqual(type(self).state["providers"][0]["image_models"], ["fixture-image-a"])

        self.frame_eval("fetch('/api/studio/model-options?module_id=canvas&slot_id=image').then(r=>r.json()).then(v=>window.__afterEnablement=v);true")
        self.wait_for(f"{frame}.__afterEnablement?.options?.length===2", "启用后正式画布候选没有更新")
        offered = self.frame_eval("window.__afterEnablement.options.map(item=>item.catalog_model_id)")
        self.assertEqual(set(offered), {"fixture-image-a"})
        self.assertEqual({item["operation"] for item in self.frame_eval("window.__afterEnablement.options")},
                         {"text_to_image", "text_or_reference_to_image"})
        self.assertFalse(type(self).state["agent_commands"], "模型管理开关不能提交运行命令")
        self.assertFalse(any(path == "/api/config" for _method, path, _body in type(self).state["writes"]))
        self.assertFalse(any(path == "/api/providers" for _method, path, _body in type(self).state["writes"]))

        self.frame_eval("(()=>{const pill=document.querySelector('[data-capability-model-picker] .capability-model-picker-pill');if(pill?.getAttribute('aria-expanded')==='true')pill.click();return pill?.getAttribute('aria-expanded')})()")
        self.wait_for(f"{frame}.document.querySelector('[data-capability-model-picker] .capability-model-picker-pill')?.getAttribute('aria-expanded')==='false'",
                      "关闭四栏菜单后仍有浮层遮挡节点参数柄")
        self.wait_for(f"{frame}.document.querySelector('.capability-summary-pill')!==null", "严格模型参数面板没有显示")
        self.frame_eval("document.querySelector('.capability-summary-pill').click();true")
        self.wait_for(
            f"{frame}.document.querySelector('.capability-summary-control')?.classList.contains('pinned')"
            f"&&{frame}.getComputedStyle({frame}.document.querySelector('.capability-summary-popover')).visibility==='visible'"
            f"&&Number({frame}.getComputedStyle({frame}.document.querySelector('.capability-summary-popover')).opacity)>=0.99",
            "参数popover没有完全显示，不能用其隐藏DOM模拟拖动",
        )
        self.wait_for(f"{frame}.document.querySelector('[data-parameter-option-id=\\\"fixture-option-disabled\\\"][data-parameter-key=\\\"seed\\\"]')!==null",
                      "必填且没有默认值的 Schema 参数没有显示")
        parameter_state = self.frame_eval("JSON.stringify({keys:[...document.querySelectorAll('.capability-summary-popover [data-parameter-key]')].map(item=>item.dataset.parameterKey),visibleControls:document.querySelectorAll('[data-parameter-presentation-visible]').length,required:document.querySelector('[data-parameter-key=\\\"seed\\\"]')?.closest('[data-required-parameter-guard=\\\"visible\\\"]')!==null,width:[...document.querySelectorAll('[data-parameter-presentation-width][data-parameter-presentation-key=\\\"quality\\\"]')].map(item=>({width:item.dataset.parameterPresentationWidth,pressed:item.getAttribute('aria-pressed')}))})")
        state_data = json.loads(parameter_state)
        self.assertIn("quality", state_data["keys"])
        self.assertIn("seed", state_data["keys"], "旧 visible:false 不得隐藏参数")
        self.assertEqual(state_data["visibleControls"], 0)
        self.assertTrue(state_data["required"])
        self.assertEqual({item["width"] for item in state_data["width"]}, {"half", "full"})
        self.assertEqual(next(item["pressed"] for item in state_data["width"] if item["width"] == "half"), "true")

        seed_selector = '.capability-summary-popover [data-parameter-presentation-order-handle][data-parameter-presentation-key="seed"]'
        quality_selector = '.capability-summary-popover [data-parameter-presentation-order-handle][data-parameter-presentation-key="quality"]'
        # 字段按行内位置决定先后；把种子字段拖到目标行上部，明确表示插入质量字段之前。
        parameter_drag = self.drag_in_frame(
            seed_selector,
            '.capability-summary-popover .capability-summary-field[data-parameter-key="quality"]',
            target_x_ratio=0.1,
            target_y_ratio=0.15,
        )
        deadline = time.time() + 4
        latest_presentation = None
        while time.time() < deadline:
            writes = [body for method, path, body in type(self).state["writes"]
                      if method == "PUT" and path == "/api/smart-canvas/personalization"]
            if writes and writes[-1].get("parameterPresentation", {}).get("fixture-option-disabled", {}).get("seed", {}).get("order") == 0:
                latest_presentation = writes[-1]["parameterPresentation"]["fixture-option-disabled"]
                break
            time.sleep(0.03)
        self.assertIsNotNone(latest_presentation, "参数字段 pointer drag 没有保存新顺序：" + str({
            "drag": parameter_drag,
            "events": self.frame_eval("JSON.stringify(window.__dragEvents||[])") ,
            "rows": self.frame_eval("JSON.stringify([...document.querySelectorAll('.capability-summary-popover [data-parameter-key]')].map(item=>({key:item.dataset.parameterKey,order:item.dataset.parameterPresentationOrder,rect:item.getBoundingClientRect().toJSON()})))") ,
            "prefs": type(self).state["personalization"].get("parameterPresentation", {}).get("fixture-option-disabled"),
        }))
        self.assertLess(latest_presentation["seed"]["order"], latest_presentation["quality"]["order"])

        self.frame_eval("document.querySelector('[data-parameter-presentation-width=\\\"full\\\"][data-parameter-presentation-key=\\\"quality\\\"]').click();true")
        deadline = time.time() + 4
        while time.time() < deadline:
            writes = [body for method, path, body in type(self).state["writes"]
                      if method == "PUT" and path == "/api/smart-canvas/personalization"]
            if writes and writes[-1].get("parameterPresentation", {}).get("fixture-option-disabled", {}).get("quality", {}).get("width") == "full":
                break
            time.sleep(0.03)
        self.assertEqual(writes[-1]["parameterPresentation"]["fixture-option-disabled"]["quality"]["width"], "full")

        self.wait_for(f"{frame}.document.querySelector('[data-canvas-settings-reset-node=\\\"1\\\"]')!==null",
                      "精确、严格可运行节点没有显示重置设置")
        before_reset = self.frame_eval("JSON.stringify((()=>{const n=nodes.find(item=>item.type==='smart-image-generator');return {id:n?.id,type:n?.type,provider:n?.runSettings?.imageProvider,model:n?.runSettings?.imageModel,selection:n?.modelSelection||n?.runSettings?.modelSelection||{},images:n?.images||[],inputs:n?.inputRefs||[],connections:canvas.connections||[]}})())")
        before_reset_state = json.loads(before_reset)
        self.frame_eval("document.querySelector('[data-canvas-settings-reset-node=\\\"1\\\"]').click();true")
        deadline = time.time() + 6
        while time.time() < deadline and not any(
            method == "POST" and path == "/api/smart-canvas/personalization/reset"
            for method, path, _body in type(self).state["writes"]
        ):
            time.sleep(0.03)
        resets = [body for method, path, body in type(self).state["writes"]
                  if method == "POST" and path == "/api/smart-canvas/personalization/reset"]
        self.assertEqual(resets[-1], {"scope": "node", "option_id": "fixture-option-disabled", "node_type": "image_generation"})
        deadline = time.time() + 6
        while time.time() < deadline:
            current = type(self).state["personalization"]
            if (current.get("reset_epoch") == 1 and
                    "fixture-option-disabled" not in current.get("parameterPresentation", {})):
                break
            time.sleep(0.03)
        self.assertEqual(type(self).state["personalization"].get("reset_epoch"), 1)
        self.assertNotIn("fixture-option-disabled",
                         type(self).state["personalization"].get("parameterPresentation", {}),
                         "精准模型显示偏好重置没有生效")
        deadline = time.time() + 6
        while time.time() < deadline and not type(self).state["canvas"]["nodes"]:
            time.sleep(0.03)
        saved_node = next(item for item in type(self).state["canvas"]["nodes"] if item.get("id") == before_reset_state["id"])
        self.assertEqual(saved_node["type"], before_reset_state["type"])
        saved_selection = saved_node.get("modelSelection") or saved_node["runSettings"].get("modelSelection") or {}
        for identity_key in ("connection_id", "option_id", "operation", "region_id", "schema_version"):
            self.assertEqual(saved_selection.get(identity_key), before_reset_state["selection"].get(identity_key),
                             f"重置展示设置不得改变模型身份字段 {identity_key}")
        self.assertEqual(saved_selection.get("option_id"), "fixture-option-disabled")
        self.assertEqual(saved_selection.get("operation"), "text_or_reference_to_image")
        model_params = saved_node["runSettings"].get("capabilityParameters", {}).get("fixture-image-a", {})
        self.assertEqual(model_params.get("quality"), "high")
        self.assertNotIn("seed", model_params, "无 schema default 的必填参数不能凭空补值")
        self.assertEqual(saved_node.get("images", []), before_reset_state["images"])
        self.assertEqual(type(self).state["canvas"].get("connections", []), before_reset_state["connections"])
        self.assertEqual(type(self).state["providers"][0]["image_models"], ["fixture-image-a"])

    def test_required_schema_parameter_cannot_be_hidden_behind_advanced_display(self):
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/tests/browser/model-config-demo.html"})
        self.wait_for("document.readyState==='complete'&&!!window.__demo", "公共模型控件测试页未加载")
        self.evaluate("""(() => {
          const option={option_id:'fixture-required-option',canonical_family_id:'fixture-family',canonical_family_label:{zh:'假模型',en:'Fixture'},catalog_model_id:'fixture-required-model',node_type:'image_generation',operation:'text_to_image',connection_id:'fixture',region_id:'',selectable:true,runnable:true,parameters:{required_quality:{type:'enum',label:'必填质量',required:true,level:'advanced',ui:{level:'advanced'},options:['standard','high']}}};
          const catalog={options:[option],profiles:[]};
          window.__requiredFixture=window.__demo.mountInline('host',{catalog,selection:{optionId:option.option_id,parameters:{}}});
          return true;
        })()""")
        self.wait_for("!!document.querySelector('[data-param-key=required_quality]')",
                      lambda: "必填参数不应因为 advanced 展示级别或 presentation 偏好被隐藏：" + str(
                          self.evaluate("JSON.stringify({host:document.getElementById('host')?.innerHTML, errors:window.__modelConfigErrors||[]})")
                      ))
        shown = self.evaluate("(() => ({row:document.querySelector('[data-param-key=required_quality]')?.textContent||'',guard:document.querySelector('[data-required-parameter-guard=visible]')!==null}))()")
        self.assertIn("必填质量", shown["row"], shown)
        self.assertTrue(shown["guard"], shown)


if __name__ == "__main__":
    unittest.main()
