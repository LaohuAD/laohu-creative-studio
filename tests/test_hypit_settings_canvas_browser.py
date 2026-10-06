"""Hypit 设置复用真实智能画布的隔离浏览器回归。"""
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
CHROME = next((path for path in (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("google-chrome"), shutil.which("chromium"),
) if path and Path(path).is_file()), None)
NODE = shutil.which("node")


@unittest.skipUnless(CHROME and NODE, "需要本机 Chrome/Chromium 和 Node.js 执行隔离浏览器回归")
class HypitSettingsCanvasBrowserTests(unittest.TestCase):
    @staticmethod
    def _empty_canvas():
        return {
            "id": "hypit-settings", "title": "Hypit 设置画布", "icon": "sparkles", "project": "__hypit_settings__",
            "revision": 1, "updated_at": 1791158400, "node_schema_version": 9999,
            "hypit_flow_schema_version": 1, "nodes": [], "connections": [], "logs": [],
            "settings": {}, "viewport": {"x": 0, "y": 0, "scale": 1},
        }

    @classmethod
    def setUpClass(cls):
        cls.canvas = cls._empty_canvas()
        cls.canvas_gets = 0
        cls.canvas_puts = []
        cls.canvas_put_attempts = 0
        cls.canvas_put_attempt_log = []
        cls.fail_canvas_puts = 0
        cls.reset_posts = []
        cls.test_posts = []
        cls.test_polls = 0
        cls.agent_commands = {}
        cls.agent_command_posts = []
        cls.agent_command_list_gets = 0
        cls.agent_cancel_posts = []
        cls.agent_task_counter = 0
        cls.agent_task_count = 1
        cls.studio_task_statuses = {}
        cls.write_paths = []
        cls.legacy_get_paths = []
        cls.model_option_requests = []
        cls.module_model_options = {}
        cls.api_providers_payload = []
        cls.model_capabilities_payload = {"schema_version": 1, "providers": [], "options": []}
        cls.poll_state = {"status": "succeeded", "current_recipe_matches": True, "output_kind": "image"}

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
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(body)
                    self.wfile.flush()
                except BrokenPipeError:
                    pass
                self.close_connection = True

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/api/hypit/settings-canvas":
                    self._json(200, {
                        "id": "hypit-settings", "canvas": cls.canvas,
                        "url": "/static/smart-canvas.html?id=hypit-settings&mode=hypit-settings",
                    })
                elif path == "/api/canvases/hypit-settings":
                    cls.canvas_gets += 1
                    self._json(200, {"canvas": {**cls.canvas, "test_statuses": cls.test_statuses}})
                elif path == "/api/canvases/hypit-settings/meta":
                    self._json(200, {"id": "hypit-settings", "revision": cls.canvas["revision"], "updated_at": cls.canvas["updated_at"]})
                elif path.startswith("/api/studio/tasks/"):
                    task_id = path.rsplit("/", 1)[-1]
                    status = cls.studio_task_statuses.get(task_id)
                    self._json(200 if status else 404, {"id": task_id, "status": status or "missing"})
                elif path == "/api/agent/canvases/hypit-settings/commands":
                    cls.agent_command_list_gets += 1
                    self._json(200, {"commands": list(cls.agent_commands.values())})
                elif path.startswith("/api/agent/canvases/hypit-settings/commands/"):
                    command_id = path.rsplit("/", 1)[-1]
                    command = next((item for item in cls.agent_commands.values() if item.get("id") == command_id), None)
                    self._json(200 if command else 404, command or {"detail": "fixture command not found"})
                elif path.startswith("/api/hypit/settings-canvas/test/"):
                    cls.test_polls += 1
                    run_id = path.rsplit("/", 1)[-1]
                    self._json(200, {"run_id": run_id, **cls.poll_state})
                elif path == "/api/providers":
                    self._json(200, {"providers": []})
                elif path == "/api/model-capabilities":
                    self._json(200, cls.model_capabilities_payload)
                elif path == "/api/studio/model-options":
                    from urllib.parse import parse_qs
                    query = parse_qs(urlsplit(self.path).query)
                    module_id = (query.get("module_id") or [""])[0]
                    slot_id = (query.get("slot_id") or [""])[0]
                    cls.model_option_requests.append((module_id, slot_id))
                    self._json(200, {
                        "module_id": module_id,
                        "slots": [{"id": slot_id}] if slot_id else [],
                        "catalog_revision": "fixture-revision",
                        "options": list(cls.module_model_options.get(slot_id, [])),
                    })
                elif path == "/api/config":
                    self._json(200, {"api_providers": cls.api_providers_payload, "comfy_instances": []})
                elif path == "/api/model-pricing":
                    self._json(200, {"schema_version": 1, "entries": {}, "unit_definitions": {}})
                elif path == "/api/workflows":
                    self._json(200, {"workflows": []})
                elif path == "/api/prompt-libraries":
                    self._json(200, {"library": {"active_library_id": "system", "libraries": [{"id": "system", "items": [], "categories": []}]}})
                elif path == "/api/smart-canvas/personalization":
                    self._json(200, {"version": 1, "executionLayouts": {}, "parameterOptionOrder": {}, "modelOrder": {}, "parameterPresentation": {}})
                elif path == "/api/asset-library":
                    self._json(200, {"library": {"libraries": []}})
                elif path == "/api/local-assets":
                    self._json(200, {"items": [], "tree": {"id": "__root__", "items": [], "children": []}})
                elif path == "/api/results":
                    self._json(200, {"items": [], "counts": {}})
                elif path == "/api/canvases/trash":
                    self._json(200, {"items": []})
                elif path == "/api/canvas-runs":
                    self._json(200, {"runs": []})
                elif path == "/api/studio/hypit/models/capabilities":
                    cls.legacy_get_paths.append(path)
                    self._json(200, {"providers": [], "options": [], "supported_capabilities": [], "unsupported_capabilities": []})
                elif path == "/api/studio/hypit/models/settings":
                    cls.legacy_get_paths.append(path)
                    self._json(200, {"defaults": {}, "revision": 1, "parameter_mode": "per_request"})
                elif path.startswith("/api/"):
                    self._json(404, {"detail": "隔离 Hypit 画布 fixture 未实现此只读路由"})
                else:
                    super().do_GET()

            def do_PUT(self):
                path = urlsplit(self.path).path
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                cls.write_paths.append(path)
                if path == "/api/canvases/hypit-settings":
                    cls.canvas_put_attempts += 1
                    previous_nodes = {str(node.get("id") or ""): node for node in cls.canvas.get("nodes", [])
                                      if isinstance(node, dict)}
                    submitted_nodes = {str(node.get("id") or ""): node for node in body.get("nodes", [])
                                       if isinstance(node, dict)}
                    cls.canvas_put_attempt_log.append({
                        "path": path,
                        "base_revision": body.get("base_revision"),
                        "server_revision": cls.canvas.get("revision"),
                        "migration_version": body.get("migration_version"),
                        "node_schema_version": cls.canvas.get("node_schema_version"),
                        "nodes": [{"id": str(node.get("id") or ""), "type": str(node.get("type") or "")}
                                  for node in body.get("nodes", []) if isinstance(node, dict)],
                        "changed_canvas_keys": [key for key in set(cls.canvas) | set(body)
                                                 if key not in {"revision", "updated_at", "base_revision",
                                                                "base_updated_at", "client_id", "migration_version"}
                                                 and cls.canvas.get(key) != body.get(key)],
                        "changed_node_fields": [{"id": node_id,
                                                 "keys": [key for key in set(previous_nodes.get(node_id, {}))
                                                          | set(submitted_nodes.get(node_id, {}))
                                                          if previous_nodes.get(node_id, {}).get(key)
                                                          != submitted_nodes.get(node_id, {}).get(key)]}
                                                for node_id in sorted(set(previous_nodes) | set(submitted_nodes))
                                                if previous_nodes.get(node_id) != submitted_nodes.get(node_id)],
                    })
                    if cls.fail_canvas_puts:
                        cls.fail_canvas_puts -= 1
                        self._json(503, {"detail": "fixture canvas save failed"})
                        return
                    if int(body.get("base_revision", -1)) != int(cls.canvas["revision"]):
                        self._json(409, {"detail": {"message": "画布已由另一标签更新", "canvas": cls.canvas}})
                        return
                    cls.canvas_puts.append(body)
                    stored = {key: value for key, value in body.items()
                              if key not in {"base_revision", "base_updated_at", "client_id", "migration_version",
                                             "test_statuses"}}
                    cls.canvas = {**cls.canvas, **stored, "revision": cls.canvas["revision"] + 1, "updated_at": cls.canvas["updated_at"] + 1}
                    # test_statuses 是读取投影，不落入画布记录；GET 与成功 PUT
                    # 的响应必须都返回同一投影，避免客户端误判启动状态为本地脏数据。
                    self._json(200, {"canvas": {**cls.canvas, "test_statuses": cls.test_statuses}})
                else:
                    self._json(403, {"detail": "隔离 fixture 禁止此 PUT"})

            def do_POST(self):
                path = urlsplit(self.path).path
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                cls.write_paths.append(path)
                if path == "/api/hypit/settings-canvas/test":
                    cls.test_posts.append(body)
                    run_id = f"fixture-run-{len(cls.test_posts)}"
                    self._json(200, {"run_id": run_id, "attempt_id": run_id, "status": "queued",
                                     "slot": body.get("slot"), "output_node_id": body.get("output_node_id"),
                                     "recipe_fingerprint": "fixture-fingerprint",
                                     "poll_url": f"/api/hypit/settings-canvas/test/{run_id}"})
                    return
                if path == "/api/agent/canvases/hypit-settings/commands":
                    action = str(body.get("action") or "")
                    request_id = str(body.get("request_id") or "")
                    args = body.get("args") or {}
                    cls.agent_command_posts.append(body)
                    command_id = f"fixture-command-{len(cls.agent_command_posts)}"
                    if action == "run_node":
                        node_id = str(args.get("node_id") or "")
                        node = next((item for item in cls.canvas["nodes"] if item.get("id") == node_id), None)
                        if node is None:
                            self._json(404, {"detail": "fixture node not found"})
                            return
                        tasks = []
                        for _ in range(max(1, int(cls.agent_task_count))):
                            cls.agent_task_counter += 1
                            task_id = f"studio_fixture-{cls.agent_task_counter}"
                            task = {
                                "id": task_id, "type": "smart-material", "sourceKind": "result",
                                "sourceExecutionNodeId": node_id, "creationId": node.get("creationId", ""),
                                "creationSignature": node.get("creationSignature", ""), "creationTask": True,
                                "isRunPlaceholder": True, "runStatus": "queued", "pending": 1,
                                "runStartedAt": 1791158400000 + cls.agent_task_counter,
                                "images": [],
                            }
                            node.setdefault("creationTasks", []).append(task)
                            cls.studio_task_statuses[task_id] = "queued"
                            tasks.append(task)
                        cls.canvas["revision"] += 1
                        cls.canvas["updated_at"] += 1
                        cls.agent_commands[request_id] = {
                            "id": command_id, "request_id": request_id, "status": "succeeded",
                            "result": {"node_id": node_id, "task_ids": [task["id"] for task in tasks], "tasks": tasks},
                        }
                    elif action == "cancel_run":
                        cls.agent_cancel_posts.append(body)
                        node_id = str(args.get("node_id") or "")
                        task_id = str(args.get("task_id") or "")
                        node = next((item for item in cls.canvas["nodes"] if item.get("id") == node_id), None)
                        task = next((item for item in (node or {}).get("creationTasks", []) if item.get("id") == task_id), None)
                        if task is None:
                            self._json(404, {"detail": "fixture task not found"})
                            return
                        task["runStatus"] = "cancelled"
                        task["pending"] = 0
                        cls.studio_task_statuses[task_id] = "cancelled"
                        cls.canvas["revision"] += 1
                        cls.canvas["updated_at"] += 1
                        cls.agent_commands[request_id] = {
                            "id": command_id, "request_id": request_id, "status": "succeeded",
                            "result": {"cancelled": task_id},
                        }
                    else:
                        self._json(400, {"detail": "unsupported fixture action"})
                        return
                    self._json(200, cls.agent_commands[request_id])
                    return
                if path == "/api/hypit/settings-canvas/reset":
                    cls.reset_posts.append(body)
                    if int(body.get("base_revision", -1)) != int(cls.canvas["revision"]):
                        self._json(409, {"detail": {"canvas": cls.canvas}})
                        return
                    cls.canvas = {**cls.canvas, "nodes": [], "connections": [], "logs": [], "settings": {},
                                  "viewport": {"x": 0, "y": 0, "scale": 1}, "revision": cls.canvas["revision"] + 1,
                                  "updated_at": cls.canvas["updated_at"] + 1}
                    self._json(200, {"id": "hypit-settings", "canvas": cls.canvas, "reset": True})
                else:
                    self._json(403, {"detail": "隔离 fixture 禁止此 POST"})

        cls.test_statuses = {}

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.debug_port = probe.getsockname()[1]
        cls.cache = ROOT / ".cache" / "validation" / "studio-tests"
        cls.cache.mkdir(parents=True, exist_ok=True)
        cls.profile = cls.cache / "tmp" / f"hypit-settings-canvas-{int(time.time())}"
        cls.profile.mkdir(parents=True, exist_ok=True)
        cls.chrome = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--window-size=1440,1000", "--force-device-scale-factor=1",
            f"--user-data-dir={cls.profile}", f"--remote-debugging-port={cls.debug_port}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.target = cls._wait_target()
        if not cls.target:
            cls.tearDownClass()
            raise unittest.SkipTest("Chrome 未能暴露调试目标")
        script = r"""const readline=require('readline');const ws=new WebSocket(process.argv[1]);const input=readline.createInterface({input:process.stdin});ws.onopen=()=>{console.log(JSON.stringify({ready:true}));input.on('line',line=>{const q=JSON.parse(line);ws.send(JSON.stringify({id:q.id,method:q.method,params:q.params||{}}));});};ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id!==undefined)console.log(JSON.stringify({id:m.id,result:m.result||{},error:m.error||null}));};"""
        cls.cdp_process = subprocess.Popen([NODE, "-e", script, cls.target["webSocketDebuggerUrl"]], stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        if not json.loads(cls.cdp_process.stdout.readline() or "{}").get("ready"):
            cls.tearDownClass()
            raise unittest.SkipTest("未能建立隔离 CDP 会话")
        cls.request_id = 0
        cls.cdp("Page.enable")
        cls.cdp("Runtime.enable")

    def setUp(self):
        # 上一用例的 iframe 可能仍有已排队的同源 GET。先卸载旧页面并等待
        # about:blank 提交完成，再重置计数，避免把上一用例的请求归到本用例。
        self.cdp("Page.navigate", {"url":"about:blank"})
        self.assertTrue(self.evaluate("(async()=>{for(let i=0;i<80;i++){if(document.readyState==='complete'&&location.href==='about:blank')return true;await new Promise(r=>setTimeout(r,10));}return false;})()"),
                        "隔离浏览器未能卸载上一用例页面")
        time.sleep(0.05)
        type(self).canvas = self._empty_canvas()
        type(self).canvas_gets = 0
        type(self).canvas_puts = []
        type(self).canvas_put_attempts = 0
        type(self).canvas_put_attempt_log = []
        type(self).fail_canvas_puts = 0
        type(self).reset_posts = []
        type(self).test_posts = []
        type(self).test_polls = 0
        type(self).agent_commands = {}
        type(self).agent_command_posts = []
        type(self).agent_command_list_gets = 0
        type(self).agent_cancel_posts = []
        type(self).agent_task_counter = 0
        type(self).agent_task_count = 1
        type(self).studio_task_statuses = {}
        type(self).write_paths = []
        type(self).legacy_get_paths = []
        type(self).model_option_requests = []
        type(self).module_model_options = {}
        type(self).api_providers_payload = []
        type(self).model_capabilities_payload = {"schema_version": 1, "providers": [], "options": []}
        type(self).poll_state = {"status": "succeeded", "current_recipe_matches": True, "output_kind": "image"}
        type(self).test_statuses = {}

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "cdp_process", None):
            cls.cdp_process.terminate()
            try:
                cls.cdp_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.cdp_process.kill()
        if getattr(cls, "chrome", None):
            cls.chrome.terminate()
            try:
                cls.chrome.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.chrome.kill()
        if getattr(cls, "server", None):
            cls.server.shutdown()
            cls.server.server_close()
        if getattr(cls, "profile", None):
            shutil.rmtree(cls.profile, ignore_errors=True)

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

    def frame_evaluate(self, expression):
        return self.evaluate(f"document.getElementById('hypitSettingsCanvasFrame').contentWindow.eval({json.dumps(expression)})")

    def open_hypit_canvas(self):
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/static/api-settings.html"})
        self.assertTrue(self.evaluate("(async()=>{for(let i=0;i<120;i++){if(document.readyState==='complete'&&document.getElementById('hypitSettingsNav'))return true;await new Promise(r=>setTimeout(r,25));}return false;})()"))
        self.evaluate("document.getElementById('hypitSettingsNav').click()")
        ready = self.evaluate("(async()=>{for(let i=0;i<160;i++){const f=document.getElementById('hypitSettingsCanvasFrame');const u=new URL(f?.src||'about:blank',location.href);if(f&&u.pathname==='/static/smart-canvas.html'&&f.contentWindow?.location?.pathname==='/static/smart-canvas.html'&&f.contentWindow?.document?.getElementById('world'))return true;await new Promise(r=>setTimeout(r,50));}return false;})()")
        self.assertTrue(ready, "Hypit 设置没有挂载共享智能画布 iframe")
        deadline = time.time() + 5
        while not self.canvas_gets and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.canvas_gets, 1, "嵌入画布必须只通过标准 canvas GET 加载专用 ID")
        expected_ids = [str(node.get("id", "")) for node in type(self).canvas.get("nodes", []) if node.get("id")]
        if expected_ids:
            encoded_ids = json.dumps(expected_ids)
            self.wait_for(lambda: self.frame_evaluate(
                f"(()=>{{const ids={encoded_ids};return ids.every(id=>!!document.querySelector('.image-node[data-id='+JSON.stringify(id)+']'));}})()"),
                "专用画布的fixture节点尚未完成真实DOM挂载")

    def seed_canvas(self, nodes, connections=(), test_statuses=None):
        type(self).canvas = {**self._empty_canvas(), "nodes": nodes, "connections": list(connections)}
        type(self).test_statuses = test_statuses or {}

    def seed_image_model_catalog(self, *, allowed_model="fixture-image-valid", excluded_model="fixture-image-excluded"):
        def profile(model_id, family_id):
            return {
                "model_id": model_id, "node_type": "image_generation", "operation": "text_to_image",
                "family_id": family_id, "family_name": family_id, "variant_id": "text_to_image",
                "provider_id": "fixture-provider", "capability_provider_id": "fixture-provider",
                "variant_name": model_id, "validation_mode": "strict", "readiness": "ready",
                "runnable": True, "selectable": True,
                "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
                "parameters": {},
            }

        allowed = profile(allowed_model, "allowed-family")
        excluded = profile(excluded_model, "excluded-family")
        options = [
            {"option_id": f"opt-{allowed_model}", "connection_id": "fixture-provider",
             "capability_provider_id": "fixture-provider", "catalog_model_id": allowed_model,
             "node_type": "image_generation", "operation": "text_to_image", "region_id": ""},
            {"option_id": f"opt-{excluded_model}", "connection_id": "fixture-provider",
             "capability_provider_id": "fixture-provider", "catalog_model_id": excluded_model,
             "node_type": "image_generation", "operation": "text_to_image", "region_id": ""},
        ]
        type(self).api_providers_payload = [{
            "id": "fixture-provider", "name": "Fixture Provider", "protocol": "openai", "enabled": True,
            "image_models": [allowed_model, excluded_model],
        }]
        type(self).model_capabilities_payload = {
            "schema_version": 1,
            "providers": [{
                "id": "fixture-provider", "name": "Fixture Provider", "protocol": "openai",
                "capability_provider_id": "fixture-provider", "models": [allowed, excluded],
                "families": [
                    {"family_id": "allowed-family", "family_name": "Allowed", "node_type": "image_generation", "variants": [allowed]},
                    {"family_id": "excluded-family", "family_name": "Excluded", "node_type": "image_generation", "variants": [excluded]},
                ],
            }],
            "options": options,
            "catalog_revision": "fixture-revision",
        }
        type(self).module_model_options = {
            "image": [options[0]], "audio": [], "voice": [], "text": [], "video": [], "music": [],
        }

    def seed_audio_model_catalog(self):
        def profile(model_id, family_id):
            return {
                "model_id": model_id, "node_type": "audio_generation", "operation": "text_to_audio",
                "family_id": family_id, "family_name": family_id, "variant_id": "text_to_audio",
                "provider_id": "fixture-provider", "capability_provider_id": "fixture-provider",
                "variant_name": model_id, "validation_mode": "strict", "readiness": "ready",
                "runnable": True, "selectable": True,
                "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
                "parameters": {},
            }

        audio = profile("fixture-audio-model", "audio-family")
        voice = profile("fixture-voice-model", "voice-family")
        options = [
            {"option_id": "opt-audio", "connection_id": "fixture-provider", "capability_provider_id": "fixture-provider",
             "catalog_model_id": audio["model_id"], "node_type": "audio_generation", "operation": "text_to_audio", "region_id": ""},
            {"option_id": "opt-voice", "connection_id": "fixture-provider", "capability_provider_id": "fixture-provider",
             "catalog_model_id": voice["model_id"], "node_type": "audio_generation", "operation": "text_to_audio", "region_id": ""},
        ]
        type(self).api_providers_payload = [{"id": "fixture-provider", "name": "Fixture Provider", "protocol": "openai",
                                             "enabled": True, "audio_models": [audio["model_id"], voice["model_id"]]}]
        type(self).model_capabilities_payload = {
            "schema_version": 1,
            "providers": [{"id": "fixture-provider", "name": "Fixture Provider",
                            "protocol": "openai", "capability_provider_id": "fixture-provider",
                            "models": [audio, voice],
                            "families": [
                                {"family_id": "audio-family", "family_name": "Audio", "node_type": "audio_generation", "variants": [audio]},
                                {"family_id": "voice-family", "family_name": "Voice", "node_type": "audio_generation", "variants": [voice]},
                            ]}],
            "options": options, "catalog_revision": "fixture-revision",
        }
        type(self).module_model_options = {"audio": [options[0]], "voice": [options[1]]}

    def seed_gpt_image_identity_catalog(self):
        from model_capabilities import ModelCapabilityRegistry
        from studio_model_selection import compile_catalog_options

        laohu_models = [
            "laohu-image-g-v2.5-flare", "laohu-image-g-v2.5-lowprice", "laohu-image-g-v2.5-sunburst",
        ]
        runninghub_models = [
            "gpt-image-2.5/flare/text-to-image/economy",
            "gpt-image-2.5/sunburst/text-to-image/economy",
            "gpt-image-2.5/flare/text-to-image/stable-token",
            "gpt-image-2.5/sunburst/text-to-image/stable-token",
            "gpt-image-2.5/flare/image-to-image/economy",
            "gpt-image-2.5/sunburst/image-to-image/economy",
            "gpt-image-2.5/flare/image-to-image/stable-token",
            "gpt-image-2.5/sunburst/image-to-image/stable-token",
        ]
        # Use the same disk capability source and option compiler as the runtime
        # endpoint. Provider configuration here is an isolated, credential-free
        # fixture that merely enables the exact candidates under test.
        provider_configs = [
            {"id": "ai-money", "enabled": True, "image_models": laohu_models},
            {"id": "runninghub", "enabled": True, "rh_region": "global", "rh_regions": {
                "global": {"enabled": True, "image_models": runninghub_models},
                "cn": {"enabled": False, "image_models": []},
            }},
        ]
        catalog = ModelCapabilityRegistry(ROOT).build_catalog(provider_configs)
        catalog["options"] = compile_catalog_options(catalog)
        type(self).api_providers_payload = provider_configs
        type(self).model_capabilities_payload = catalog
        enabled_ids = {model["model_id"] for provider in catalog["providers"] for model in provider.get("models", [])
                       if model.get("selectable") is True}
        self.assertTrue(set(laohu_models + runninghub_models).issubset(enabled_ids),
                        f"runtime profile converter 没有生成所有预期可选模型: {set(laohu_models + runninghub_models) - enabled_ids}")

    def wait_for(self, predicate, message, timeout=8):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        self.fail(message() if callable(message) else message)

    def drag_connect(self, source_id, output_id):
        self.frame_evaluate(f"document.querySelector('.image-node[data-id={json.dumps(source_id)}]').click(); true")
        coords = self.frame_evaluate(f"(() => {{const frame=parent.document.getElementById('hypitSettingsCanvasFrame').getBoundingClientRect();const source=document.querySelector('.image-node[data-id={json.dumps(source_id)}] .node-port.port-out').getBoundingClientRect();const target=document.querySelector('.image-node[data-id={json.dumps(output_id)}] .node-port.port-in').getBoundingClientRect();return {{sx:frame.left+source.left+source.width/2,sy:frame.top+source.top+source.height/2,tx:frame.left+target.left+target.width/2,ty:frame.top+target.top+target.height/2}};}})()")
        time.sleep(0.05)
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": coords["sx"], "y": coords["sy"], "button": "none", "buttons": 0})
        self.cdp("Input.dispatchMouseEvent", {"type": "mousePressed", "x": coords["sx"], "y": coords["sy"], "button": "left", "buttons": 1, "clickCount": 1})
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": coords["tx"], "y": coords["ty"], "button": "left", "buttons": 1})
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": coords["tx"], "y": coords["ty"], "button": "left", "buttons": 0, "clickCount": 1})

    def drag_connect_to_execution(self, source_id, target_id):
        self.frame_evaluate(f"document.querySelector('.image-node[data-id={json.dumps(source_id)}]').click(); true")
        coords = self.frame_evaluate(f"(() => {{const frame=parent.document.getElementById('hypitSettingsCanvasFrame').getBoundingClientRect();const source=document.querySelector('.image-node[data-id={json.dumps(source_id)}] .node-port.port-out').getBoundingClientRect();const target=document.querySelector('.image-node[data-id={json.dumps(target_id)}] .node-port.port-in').getBoundingClientRect();return {{sx:frame.left+source.left+source.width/2,sy:frame.top+source.top+source.height/2,tx:frame.left+target.left+target.width/2,ty:frame.top+target.top+target.height/2}};}})()")
        time.sleep(0.05)
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": coords["sx"], "y": coords["sy"], "button": "none", "buttons": 0})
        self.cdp("Input.dispatchMouseEvent", {"type": "mousePressed", "x": coords["sx"], "y": coords["sy"], "button": "left", "buttons": 1, "clickCount": 1})
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": coords["tx"], "y": coords["ty"], "button": "left", "buttons": 1})
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": coords["tx"], "y": coords["ty"], "button": "left", "buttons": 0, "clickCount": 1})

    def drag_node_header(self, node_id, dx, dy):
        coords = self.frame_evaluate(f"(() => {{const frame=parent.document.getElementById('hypitSettingsCanvasFrame').getBoundingClientRect();const title=document.querySelector('.image-node[data-id={json.dumps(node_id)}] .hypit-output-title');const rect=title.getBoundingClientRect();return {{sx:frame.left+rect.left+rect.width/2,sy:frame.top+rect.top+rect.height/2,tx:frame.left+rect.left+rect.width/2+{int(dx)},ty:frame.top+rect.top+rect.height/2+{int(dy)}}};}})()")
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": coords["sx"], "y": coords["sy"], "button": "none", "buttons": 0})
        self.cdp("Input.dispatchMouseEvent", {"type": "mousePressed", "x": coords["sx"], "y": coords["sy"], "button": "left", "buttons": 1, "clickCount": 1})
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": coords["sx"] + dx / 2, "y": coords["sy"] + dy / 2, "button": "left", "buttons": 1})
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": coords["tx"], "y": coords["ty"], "button": "left", "buttons": 1})
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": coords["tx"], "y": coords["ty"], "button": "left", "buttons": 0, "clickCount": 1})

    def resize_node_bottom_right(self, node_id, dx, dy):
        coords = self.frame_evaluate(f"(() => {{const frame=parent.document.getElementById('hypitSettingsCanvasFrame').getBoundingClientRect();const handle=document.querySelector('.image-node[data-id={json.dumps(node_id)}] .node-resize-handle');const rect=handle.getBoundingClientRect();return {{sx:frame.left+rect.left+rect.width/2,sy:frame.top+rect.top+rect.height/2,tx:frame.left+rect.left+rect.width/2+{int(dx)},ty:frame.top+rect.top+rect.height/2+{int(dy)}}};}})()")
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": coords["sx"], "y": coords["sy"], "button": "none", "buttons": 0})
        self.cdp("Input.dispatchMouseEvent", {"type": "mousePressed", "x": coords["sx"], "y": coords["sy"], "button": "left", "buttons": 1, "clickCount": 1})
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": coords["tx"], "y": coords["ty"], "button": "left", "buttons": 1})
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": coords["tx"], "y": coords["ty"], "button": "left", "buttons": 0, "clickCount": 1})

    def test_hypit_settings_opens_the_shared_smart_canvas(self):
        self.open_hypit_canvas()
        details = self.evaluate("""(() => {const frame=document.getElementById('hypitSettingsCanvasFrame');return {
          src:new URL(frame.src).pathname+new URL(frame.src).search,
          title:frame.title,
          embeddedId:frame.contentWindow?.location?.search&&new URLSearchParams(frame.contentWindow.location.search).get('id'),
          mode:frame.contentWindow?.location?.search&&new URLSearchParams(frame.contentWindow.location.search).get('mode'),
          canvasTitle:frame.contentDocument?.getElementById('smartTitle')?.textContent?.trim()
        };})()""")
        self.assertEqual(details["embeddedId"], "hypit-settings", details)
        self.assertEqual(details["mode"], "hypit-settings", details)
        self.assertEqual(self.canvas_gets, 1, "嵌入画布必须只通过标准 canvas GET 加载专用 ID")
        self.assertTrue(self.evaluate("document.querySelectorAll('#hypitSettingsCanvasFrame').length === 1"))
        self.assertFalse(self.evaluate("[...document.querySelectorAll('.hypit-settings-card,.hypit-model-card')].some(el=>!el.hidden)"),
                         "旧 Hypit 模型卡片不能与共享画布并列成为第二套选择器")

    def test_shared_canvas_mode_does_not_read_or_write_legacy_hypit_defaults(self):
        self.open_hypit_canvas()
        self.assertEqual(self.legacy_get_paths, [], "新版入口只加载共享画布，不应后台读取旧六槽 defaults")
        self.evaluate("window.dispatchEvent(new CustomEvent('studio-api-change',{detail:{type:'providers-changed',updated_at:'fixture'}})); true")
        time.sleep(0.2)
        result = self.evaluate("window.saveHypitSettings()")
        self.assertFalse(result, "旧保存入口在未挂载六槽表单时必须拒绝写回")
        self.assertEqual(self.legacy_get_paths, [], "平台变化事件不能重新启动旧六槽目录/设置读取")
        self.assertNotIn("/api/studio/hypit/models/settings", self.write_paths,
                         "共享画布模式不能再保存旧 Hypit defaults")

    def test_output_drawer_adds_one_real_output_and_saves_through_shared_canvas_api(self):
        self.open_hypit_canvas()
        self.assertEqual(self.frame_evaluate("document.querySelector('#hypitOutputDrawerToggle span')?.textContent.trim()"),
                         "添加输出端口", "输出抽屉入口应使用具体操作名称")
        self.frame_evaluate("document.getElementById('hypitOutputDrawerToggle').click(); document.querySelector('[data-hypit-slot=image]').click(); true")
        self.wait_for(lambda: bool(self.canvas_puts), "添加用途输出后没有通过标准画布 PUT 自动保存")
        saved = self.canvas_puts[-1]
        outputs = [node for node in saved.get("nodes", []) if node.get("type") == "smart-hypit-output" and node.get("hypitSlot") == "image"]
        self.assertEqual(len(outputs), 1, saved)
        self.assertEqual(saved.get("settings"), {}, "专用画布不应复制普通画布设置")
        self.assertNotIn("test_statuses", saved, "测试状态是服务端投影，不能写进画布 PUT")
        self.assertEqual(self.write_paths, ["/api/canvases/hypit-settings"])

        self.frame_evaluate("document.querySelector('[data-hypit-slot=image]').click(); true")
        self.assertTrue(self.frame_evaluate("document.querySelectorAll('.hypit-output-node[data-hypit-slot=image]').length === 1"),
                        "重复点同一用途应聚焦已有输出，不能新增第二个")
        self.assertEqual(len([node for node in self.canvas.get("nodes", []) if node.get("type") == "smart-hypit-output" and node.get("hypitSlot") == "image"]), 1)
        self.assertEqual(len(self.canvas_puts), 1, "重复点已有输出不应再次保存或改写画布")

    def test_hypit_output_port_title_stays_visible_and_real_drag_is_saved(self):
        self.seed_canvas([{
            "id": "text-output", "type": "smart-hypit-output", "hypitSlot": "text",
            "outputKind": "text", "x": 260, "y": 180,
        }])
        self.open_hypit_canvas()
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('.hypit-output-node[data-id=text-output]')"),
                      "Hypit 专用输出端口没有按原共享画布数据加载")
        initial = self.frame_evaluate("JSON.stringify((()=>{const node=document.querySelector('.hypit-output-node[data-id=text-output]');const title=node?.querySelector('.hypit-output-title');const style=title&&getComputedStyle(title.closest('.node-head'));const button=document.getElementById('hypitOutputDrawerToggle');const r=button.getBoundingClientRect();return {title:title?.textContent.trim(),headerDisplay:style?.display,headerVisibility:style?.visibility,buttonLabel:button?.getAttribute('aria-label'),button:{left:r.left,right:r.right,top:r.top,bottom:r.bottom},viewport:{width:innerWidth,height:innerHeight}};})())")
        observed = json.loads(initial)
        self.assertEqual(observed["title"], "文本输出", f"未选中的输出节点也须显示明确用途标题：{initial}")
        self.assertNotEqual(observed["headerDisplay"], "none", f"输出标题必须常显：{initial}")
        self.assertEqual(observed["buttonLabel"], "添加输出端口", initial)
        button = observed["button"]
        self.assertLessEqual(button["top"], 60, initial)
        self.assertLessEqual(button["right"], observed["viewport"]["width"] + 1, initial)
        toolbar = self.frame_evaluate("JSON.stringify((()=>{const a=document.getElementById('hypitOutputDrawerToggle').getBoundingClientRect();const b=document.getElementById('canvasProductionToggle').getBoundingClientRect();return {output:{left:a.left,right:a.right,top:a.top,bottom:a.bottom},progress:{left:b.left,right:b.right,top:b.top,bottom:b.bottom}};})())")
        toolbar_state = json.loads(toolbar)
        self.assertLess(toolbar_state["output"]["left"], toolbar_state["progress"]["left"],
                        f"添加输出端口应在创作进度左侧：{toolbar}")
        self.assertLess(abs((toolbar_state["output"]["top"] + toolbar_state["output"]["bottom"]) / 2 -
                            (toolbar_state["progress"]["top"] + toolbar_state["progress"]["bottom"]) / 2), 2,
                        f"输出入口和创作进度应同排：{toolbar}")
        original = next(node for node in self.canvas["nodes"] if node["id"] == "text-output")
        before = (original["x"], original["y"])
        self.drag_node_header("text-output", 90, 65)
        self.wait_for(lambda: bool(self.canvas_puts), "拖动输出端口后没有走共享画布 PUT 保存")
        persisted = next(node for node in self.canvas["nodes"] if node["id"] == "text-output")
        self.assertNotEqual((persisted["x"], persisted["y"]), before,
                            "输出端口应像其他节点一样可拖动排版并持久化位置")
        self.assertEqual(persisted["hypitSlot"], "text", "拖动不能改变输出用途身份")
        self.frame_evaluate("document.querySelector('.hypit-output-node[data-id=text-output]').click(); true")
        handle_state = self.frame_evaluate("JSON.stringify((()=>{const handle=document.querySelector('.hypit-output-node[data-id=text-output] .node-resize-handle');return {exists:!!handle,display:handle&&getComputedStyle(handle).display};})())")
        self.assertNotEqual(json.loads(handle_state)["display"], "none", f"输出端口保留普通节点尺寸调整手柄：{handle_state}")
        original_size = (persisted.get("w"), persisted.get("h"))
        self.resize_node_bottom_right("text-output", 36, 28)
        self.wait_for(lambda: len(self.canvas_puts) >= 2, "调整输出端口尺寸后没有保存共享画布")
        resized = next(node for node in self.canvas["nodes"] if node["id"] == "text-output")
        self.assertNotEqual((resized.get("w"), resized.get("h")), original_size,
                            "输出端口尺寸应能按普通节点手柄调整并保存")

    def test_hypit_output_port_button_joins_top_toolbar_on_narrow_embedded_viewport(self):
        self.open_hypit_canvas()
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": False})
        self.addCleanup(lambda: self.cdp("Emulation.clearDeviceMetricsOverride"))
        resize_state = self.frame_evaluate("""(async()=>{
          const shell=document.getElementById('shell');
          const drawer=document.getElementById('hypitOutputDrawer');
          const sample=()=>{const rect=shell.getBoundingClientRect();const style=getComputedStyle(drawer);return {
            viewport:innerWidth,documentWidth:document.documentElement.clientWidth,shellWidth:rect.width,
            media900:matchMedia('(max-width:900px)').matches,drawerRight:style.right,drawerWidth:style.width
          };};
          const aligned=value=>value.viewport>=300&&value.viewport<=390&&Math.abs(value.shellWidth-value.viewport)<1&&value.media900&&value.drawerRight==='8px';
          for(let attempt=0;attempt<120;attempt++){
            const first=sample();
            if(aligned(first)){
              await new Promise(requestAnimationFrame);
              await new Promise(requestAnimationFrame);
              const second=sample();
              if(aligned(second)&&Math.abs(first.shellWidth-second.shellWidth)<0.5)return {ready:true,first,second};
            }
            await new Promise(resolve=>setTimeout(resolve,16));
          }
          return {ready:false,layout:sample(),parentWidth:parent.innerWidth,documentReady:document.readyState};
        })()""")
        self.assertTrue(resize_state["ready"], f"窄屏 iframe 尚未完成视口布局更新：{json.dumps(resize_state, ensure_ascii=False)}")
        state = self.frame_evaluate("JSON.stringify((()=>{const button=document.getElementById('hypitOutputDrawerToggle').getBoundingClientRect();const progress=document.getElementById('canvasProductionToggle').getBoundingClientRect();const title=document.getElementById('smartTitle').getBoundingClientRect();const minimap=document.getElementById('minimap').getBoundingClientRect();const composer=document.getElementById('composer');const c=composer.classList.contains('open')?composer.getBoundingClientRect():null;return {button:{left:button.left,right:button.right,top:button.top,bottom:button.bottom},progress:{left:progress.left,right:progress.right,top:progress.top,bottom:progress.bottom},title:{left:title.left,right:title.right,top:title.top,bottom:title.bottom},minimap:{left:minimap.left,right:minimap.right,top:minimap.top,bottom:minimap.bottom},composer:c&&{left:c.left,right:c.right,top:c.top,bottom:c.bottom},width:innerWidth,parentWidth:parent.innerWidth,height:innerHeight};})())")
        observed = json.loads(state)
        self.assertEqual(observed["parentWidth"], 390, state)
        self.assertGreaterEqual(observed["width"], 300, "窄屏 API 设置侧栏预留后，画布 iframe 仍应保有可用宽度：" + state)
        self.assertLessEqual(observed["width"], 390, state)
        button, progress, title, minimap = observed["button"], observed["progress"], observed["title"], observed["minimap"]
        self.assertLess(button["left"], progress["left"], f"窄屏输出入口须在创作进度左侧：{state}")
        self.assertLess(abs((button["top"] + button["bottom"]) / 2 - (progress["top"] + progress["bottom"]) / 2), 2,
                        f"窄屏输出入口须与创作进度同排：{state}")
        self.assertLess(abs((title["top"] + title["bottom"]) / 2 - (progress["top"] + progress["bottom"]) / 2), 2,
                        f"Hypit 标题须与工具栏垂直居中对齐：{state}")
        self.assertLess(title["right"], button["left"], f"窄屏标题与工具栏不能重叠：{state}")
        self.assertLessEqual(button["top"], 60, state)
        overlaps_minimap = button["left"] < minimap["right"] and button["right"] > minimap["left"] and button["top"] < minimap["bottom"] and button["bottom"] > minimap["top"]
        self.assertFalse(overlaps_minimap, f"窄屏顶部输出入口不能遮住 minimap：{state}")
        if observed["composer"]:
            c = observed["composer"]
            overlaps_composer = button["left"] < c["right"] and button["right"] > c["left"] and button["top"] < c["bottom"] and button["bottom"] > c["top"]
            self.assertFalse(overlaps_composer, f"输出入口不能遮住已打开的 composer：{state}")
        self.frame_evaluate("document.getElementById('hypitOutputDrawerToggle').click(); true")
        drawer_state = self.frame_evaluate("JSON.stringify((()=>{const drawer=document.getElementById('hypitOutputDrawer').getBoundingClientRect();const button=document.getElementById('hypitOutputDrawerToggle').getBoundingClientRect();return {hidden:document.getElementById('hypitOutputDrawer').hidden,drawer:{left:drawer.left,right:drawer.right,top:drawer.top,bottom:drawer.bottom},button:{left:button.left,right:button.right,top:button.top,bottom:button.bottom},width:innerWidth,height:innerHeight};})())")
        drawer_observed = json.loads(drawer_state)
        self.assertFalse(drawer_observed["hidden"], drawer_state)
        self.assertGreaterEqual(drawer_observed["drawer"]["left"], 0, drawer_state)
        self.assertLessEqual(drawer_observed["drawer"]["right"], drawer_observed["width"] + 1,
                             f"窄屏抽屉须完整留在画布视口中：{drawer_state}")
        self.assertGreaterEqual(drawer_observed["drawer"]["left"], 0, drawer_state)
        self.assertGreaterEqual(drawer_observed["drawer"]["top"], 48, drawer_state)
        self.assertLessEqual(drawer_observed["drawer"]["bottom"], drawer_observed["height"] + 1, drawer_state)
        self.cdp("Emulation.clearDeviceMetricsOverride")

    def test_hypit_output_port_toolbar_is_visible_on_standalone_settings_canvas(self):
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/static/smart-canvas.html?id=hypit-settings&mode=hypit-settings"})
        self.assertTrue(self.evaluate("(async()=>{for(let i=0;i<120;i++){if(document.readyState==='complete'&&document.getElementById('world')&&document.documentElement.dataset.canvasMode==='hypit-settings')return true;await new Promise(r=>setTimeout(r,25));}return false;})()"))
        self.wait_for(lambda: self.canvas_gets == 1, "独立编辑页没有读取专用共享画布")
        state = self.evaluate("JSON.stringify((()=>{const button=document.getElementById('hypitOutputDrawerToggle');const output=button.getBoundingClientRect();const progress=document.getElementById('canvasProductionToggle').getBoundingClientRect();const title=document.getElementById('smartTitle').getBoundingClientRect();return {mode:document.documentElement.dataset.canvasMode,hidden:document.getElementById('hypitCanvasTools').hidden,label:button.getAttribute('aria-label'),titleText:document.getElementById('smartTitle').textContent.trim(),output:{left:output.left,right:output.right,top:output.top,bottom:output.bottom},progress:{left:progress.left,right:progress.right,top:progress.top,bottom:progress.bottom},title:{left:title.left,right:title.right,top:title.top,bottom:title.bottom}};})())")
        observed = json.loads(state)
        self.assertEqual(observed["mode"], "hypit-settings", state)
        self.assertFalse(observed["hidden"], state)
        self.assertEqual(observed["label"], "添加输出端口", state)
        self.assertEqual(observed["titleText"], "Hypit 流程设置", state)
        self.assertLess(observed["output"]["left"], observed["progress"]["left"], state)
        self.assertLess(abs((observed["output"]["top"] + observed["output"]["bottom"]) / 2 -
                            (observed["progress"]["top"] + observed["progress"]["bottom"]) / 2), 2, state)
        self.assertLess(abs((observed["title"]["top"] + observed["title"]["bottom"]) / 2 -
                            (observed["progress"]["top"] + observed["progress"]["bottom"]) / 2), 2, state)

    def test_hypit_output_titles_and_drawer_action_follow_chinese_and_english(self):
        slots = ["text", "image", "video", "audio", "music", "voice"]
        self.seed_canvas([{"id": f"{slot}-output", "type": "smart-hypit-output", "hypitSlot": slot,
                           "outputKind": "audio" if slot in {"audio", "music", "voice"} else slot,
                           "x": 100 + index * 40, "y": 80 + index * 20}
                          for index, slot in enumerate(slots)])
        self.open_hypit_canvas()
        self.wait_for(lambda: self.frame_evaluate("document.querySelectorAll('.hypit-output-node').length === 6"),
                      "六种用途输出节点没有完整加载")
        chinese = self.frame_evaluate("JSON.stringify({titles:Object.fromEntries([...document.querySelectorAll('.hypit-output-node')].map(node=>[node.dataset.hypitSlot,node.querySelector('.hypit-output-title')?.textContent.trim()])),menu:[...document.querySelectorAll('.hypit-output-drawer-list [data-hypit-slot]')].map(button=>button.querySelector('span')?.textContent.trim()),toggle:document.querySelector('#hypitOutputDrawerToggle span')?.textContent.trim(),drawer:document.querySelector('.hypit-output-drawer-head strong')?.textContent.trim(),help:document.querySelector('.hypit-output-drawer-head span')?.textContent.trim()})")
        observed_zh = json.loads(chinese)
        self.assertEqual(observed_zh["titles"], {"text":"文本输出","image":"图片输出","video":"视频输出","audio":"音效输出","music":"音乐输出","voice":"语音输出"})
        self.assertEqual(observed_zh["menu"], ["文本", "图片", "视频", "音效", "音乐", "语音"])
        self.assertEqual(observed_zh["toggle"], "添加输出端口")
        self.assertIn("只添加", observed_zh["help"])
        self.frame_evaluate("window.StudioI18n.set('en'); true")
        english = self.frame_evaluate("JSON.stringify({titles:Object.fromEntries([...document.querySelectorAll('.hypit-output-node')].map(node=>[node.dataset.hypitSlot,node.querySelector('.hypit-output-title')?.textContent.trim()])),menu:[...document.querySelectorAll('.hypit-output-drawer-list [data-hypit-slot]')].map(button=>button.querySelector('span')?.textContent.trim()),toggle:document.querySelector('#hypitOutputDrawerToggle span')?.textContent.trim(),drawer:document.querySelector('.hypit-output-drawer-head strong')?.textContent.trim(),help:document.querySelector('.hypit-output-drawer-head span')?.textContent.trim()})")
        observed_en = json.loads(english)
        self.assertEqual(observed_en["titles"], {"text":"Text output","image":"Image output","video":"Video output","audio":"Sound effects output","music":"Music output","voice":"Voice output"})
        self.assertEqual(observed_en["menu"], ["Text", "Image", "Video", "Sound effects", "Music", "Voice"])
        self.assertEqual(observed_en["toggle"], "Add output port")
        self.assertIn("only", observed_en["help"].lower())
        self.frame_evaluate("window.StudioI18n.set('zh'); true")

    def test_input_lock_is_a_real_toolbar_toggle_and_persists_on_shared_graph(self):
        self.seed_canvas([{
            "id": "reference", "type": "smart-material", "sourceKind": "input",
            "hypitInputLocked": False, "x": 80, "y": 80,
            "images": [{"id": "fixture-image", "kind": "image", "url": "/fixture-image.png", "name": "参考图"}],
        }])
        self.open_hypit_canvas()
        self.frame_evaluate("document.querySelector('.image-node[data-id=reference]').click(); true")
        self.wait_for(lambda: bool(self.frame_evaluate("!!document.querySelector('[data-hypit-input-lock]')")),
                      "选中素材后没有显示 Hypit 输入锁控件")
        self.frame_evaluate("document.querySelector('[data-hypit-input-lock]').click(); true")
        self.wait_for(lambda: bool(self.canvas_puts), "点击素材锁后没有保存共享画布")
        saved = self.canvas_puts[-1]
        reference = next(node for node in saved["nodes"] if node["id"] == "reference")
        self.assertIs(reference.get("hypitInputLocked"), True)
        self.assertEqual(self.write_paths, ["/api/canvases/hypit-settings"], "锁只改画布，不应触发模型配置或生成写入")

    def test_hypit_output_has_no_separate_test_button_or_submission(self):
        self.seed_canvas([
            {"id": "image-run", "type": "smart-image-generator", "x": 100, "y": 100,
             "runSettings": {"imageProvider": "fixture", "imageModel": "fixture-image"},
             "promptDraftText": "mock flow"},
            {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image", "x": 540, "y": 100},
        ], [{"id": "edge-image", "from": "image-run", "to": "image-output", "kind": "input"}])
        self.open_hypit_canvas()
        self.assertEqual(self.frame_evaluate("document.querySelectorAll('.hypit-output-node [data-hypit-test],.hypit-output-node .hypit-output-test').length"), 0,
                         "输出端口不应提供第二个测试/生成入口")
        self.assertTrue(self.frame_evaluate("!!document.querySelector('.hypit-output-node[data-id=image-output]')"),
                        "必须确认共享画布中的真实输出节点已加载，不能让空界面误过")
        self.frame_evaluate("document.querySelector('.hypit-output-node[data-id=image-output]').click(); true")
        time.sleep(0.15)
        self.assertNotIn("/api/hypit/settings-canvas/test", self.write_paths,
                         "选择或点击输出端口不能触发额外执行提交")
        self.assertEqual(self.test_posts, [], "输出端口不应调用独立流程测试接口")

    def test_hypit_normal_run_uses_shared_command_once_and_waits_for_server_projection(self):
        self.seed_canvas([
            {"id": "image-run", "type": "smart-image-generator", "x": 100, "y": 100,
             "runSettings": {"imageProvider": "fixture", "imageModel": "fixture-image"},
             "promptDraftText": "mock flow"},
            {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image", "x": 540, "y": 100},
        ], [{"id": "edge-image", "from": "image-run", "to": "image-output", "kind": "input"}])
        self.open_hypit_canvas()
        self.wait_for(lambda: not self.frame_evaluate("canvasSyncInFlight"),
                      "共享画布初始化保存未结束：" + str(self.frame_evaluate("JSON.stringify({base:canvasSyncBase?.revision,revision:canvas?.revision,queued:canvasSyncSaveQueued,timer:Boolean(saveTimer)})")))
        self.frame_evaluate("document.querySelector('.image-node[data-id=image-run]').click(); promptInput.textContent='mock flow'; promptInput.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:'mock flow'})); document.getElementById('runBtn').click(); true")
        self.wait_for(lambda: any(item.get("action") == "run_node" for item in self.agent_command_posts),
                      lambda: "Hypit 普通运行没有进入共享服务端 run_node 命令：" + str(self.frame_evaluate("(()=>{const local=canvasSyncComparableSnapshot(canvasSyncCurrentSnapshot()),base=canvasSyncComparableSnapshot(canvasSyncBase);const keys=[...new Set([...Object.keys(local||{}),...Object.keys(base||{})])];const diff=keys.filter(key=>JSON.stringify(local?.[key])!==JSON.stringify(base?.[key])).map(key=>[key,String(JSON.stringify(local?.[key])).slice(0,300),String(JSON.stringify(base?.[key])).slice(0,300)]);return JSON.stringify({mode:isHypitSettingsMode,selectedId,buttonDisabled:document.getElementById('runBtn')?.disabled,operation:hypitNodeRunOperations.has('image-run'),syncInFlight:canvasSyncInFlight,saveQueued:canvasSyncSaveQueued,saveBlocked:canvasSyncSaveBlocked,hasSaveTimer:Boolean(saveTimer),baseRevision:canvasSyncBase?.revision,canvasRevision:canvas?.revision,diff,toast:document.querySelector('[role=alert]')?.textContent})})()")) + f" fixtureRevision={self.canvas.get('revision')} writes={self.write_paths} putAttempts={self.canvas_put_attempts} puts={len(self.canvas_puts)}", timeout=1)
        run_commands = [item for item in self.agent_command_posts if item.get("action") == "run_node"]
        self.assertEqual(len(run_commands), 1, run_commands)
        self.assertEqual(run_commands[0].get("args"), {"node_id": "image-run"}, run_commands)
        self.assertFalse(self.test_posts, "普通运行不得提交 Hypit 专用流程测试接口")
        task_id = self.agent_commands[run_commands[0]["request_id"]]["result"]["task_ids"][0]
        self.assertTrue(task_id.startswith("studio_"), task_id)
        self.assertTrue(self.frame_evaluate("Boolean(hypitStoredRunRequestId('image-run'))"),
                        "排队期间必须保留同一个幂等 request_id，避免不确定重试重复提交")
        self.assertTrue(self.frame_evaluate("document.getElementById('runBtn').disabled"),
                        "服务端任务进行中时应阻止再次运行，避免重复提交")
        self.assertEqual(self.frame_evaluate("document.querySelector('.hypit-output-node').dataset.hypitStatus"), "ready",
                         "命令已接收/任务排队不能提前显示绿色")
        self.frame_evaluate("runGeneration(); true")
        time.sleep(0.15)
        self.assertEqual(len([item for item in self.agent_command_posts if item.get("action") == "run_node"]), 1,
                         "任务仍在运行时再次触发必须复用忙碌状态，不得重复提交")
        self.assertNotIn("/api/hypit/settings-canvas/test", self.write_paths)

        task = next(task for node in self.canvas["nodes"] for task in node.get("creationTasks", []) if task["id"] == task_id)
        task["runStatus"] = "succeeded"
        task["pending"] = 0
        type(self).studio_task_statuses[task_id] = "succeeded"
        type(self).test_statuses = {
            "image-output": {"run_id": task_id, "status": "passed", "test_passed": True,
                             "current_recipe_matches": True, "output_kind": "image"}
        }
        self.assertEqual(self.frame_evaluate("document.querySelector('.hypit-output-node').dataset.hypitStatus"), "ready",
                         "本地任务状态不能代替服务端画布投影")
        self.wait_for(lambda: not self.frame_evaluate("hypitNodeRunOperations.has('image-run')")
                      and self.frame_evaluate("document.querySelector('.hypit-output-node')?.dataset.hypitStatus === 'passed'"),
                      "普通 Studio task 成功且服务端确认配方/物理类型后仍未显示绿色")
        self.assertFalse(self.frame_evaluate("Boolean(hypitStoredRunRequestId('image-run'))"),
                         "任务终态和最终画布同步完成后应释放 request_id，允许用户之后重新运行")
        self.assertFalse(self.test_posts)
        self.assertFalse(any(path.startswith("/api/canvas-tasks/") for path in self.write_paths), self.write_paths)
        self.assertTrue(all(path in {"/api/canvases/hypit-settings", "/api/agent/canvases/hypit-settings/commands"}
                            for path in self.write_paths), self.write_paths)

    def test_hypit_multi_task_waits_for_all_tasks_after_one_is_cancelled(self):
        self.seed_canvas([
            {"id": "image-run", "type": "smart-image-generator", "x": 100, "y": 100,
             "runSettings": {"imageProvider": "fixture", "imageModel": "fixture-image"},
             "promptDraftText": "mock flow"},
            {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image", "x": 540, "y": 100},
        ], [{"id": "edge-image", "from": "image-run", "to": "image-output", "kind": "input"}])
        type(self).agent_task_count = 2
        self.open_hypit_canvas()
        self.wait_for(lambda: not self.frame_evaluate("canvasSyncInFlight"), "共享画布初始化保存未结束")
        self.frame_evaluate("document.querySelector('.image-node[data-id=image-run]').click(); promptInput.textContent='mock flow'; promptInput.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:'mock flow'})); document.getElementById('runBtn').click(); true")
        self.wait_for(lambda: any(item.get("action") == "run_node" for item in self.agent_command_posts),
                      "无法为多任务回归创建隔离 Studio 命令")
        run_command = next(item for item in self.agent_command_posts if item.get("action") == "run_node")
        task_ids = self.agent_commands[run_command["request_id"]]["result"]["task_ids"]
        self.assertEqual(len(task_ids), 2, task_ids)
        self.wait_for(lambda: self.frame_evaluate("(nodes.find(n=>n.id==='image-run')?.creationTasks||[]).length===2"),
                      "画布未显示服务端返回的两个任务")
        first, second = task_ids
        first_task = next(task for task in self.canvas["nodes"][0]["creationTasks"] if task["id"] == first)
        first_task.update(runStatus="cancelled", pending=0)
        type(self).studio_task_statuses[first] = "cancelled"
        time.sleep(0.85)
        self.assertTrue(self.frame_evaluate("hypitNodeRunOperations.has('image-run')"),
                        "一个任务取消时仍须等待同一命令返回的其他任务到达终态")
        second_task = next(task for task in self.canvas["nodes"][0]["creationTasks"] if task["id"] == second)
        second_task.update(runStatus="succeeded", pending=0)
        type(self).studio_task_statuses[second] = "succeeded"
        self.wait_for(lambda: not self.frame_evaluate("hypitNodeRunOperations.has('image-run')"),
                      "所有任务到达终态后运行操作仍未结束")
        self.assertFalse(self.frame_evaluate("Boolean(hypitStoredRunRequestId('image-run'))"),
                         "所有任务终态并完成画布同步后应清理幂等 request_id")
        self.assertEqual(len([item for item in self.agent_command_posts if item.get("action") == "run_node"]), 1)
        self.assertFalse(self.test_posts)
        self.assertNotEqual(self.frame_evaluate("document.querySelector('.hypit-output-node').dataset.hypitStatus"), "passed",
                            "含取消任务的多任务运行不可将输出端口标为绿色")

    def test_hypit_recoverable_task_keeps_request_id_for_manual_reconciliation(self):
        self.seed_canvas([
            {"id": "image-run", "type": "smart-image-generator", "x": 100, "y": 100,
             "runSettings": {"imageProvider": "fixture", "imageModel": "fixture-image"},
             "promptDraftText": "mock flow"},
            {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image", "x": 540, "y": 100},
        ], [{"id": "edge-image", "from": "image-run", "to": "image-output", "kind": "input"}])
        self.open_hypit_canvas()
        self.wait_for(lambda: not self.frame_evaluate("canvasSyncInFlight"), "共享画布初始化保存未结束")
        self.frame_evaluate("document.querySelector('.image-node[data-id=image-run]').click(); promptInput.textContent='mock flow'; promptInput.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:'mock flow'})); document.getElementById('runBtn').click(); true")
        self.wait_for(lambda: any(item.get("action") == "run_node" for item in self.agent_command_posts),
                      "无法为 recoverable 回归创建隔离 Studio 命令")
        run = next(item for item in self.agent_command_posts if item.get("action") == "run_node")
        request_id = run["request_id"]
        task_id = self.agent_commands[request_id]["result"]["task_ids"][0]
        task = next(task for node in self.canvas["nodes"] for task in node.get("creationTasks", []) if task["id"] == task_id)
        task.update(runStatus="recoverable", pending=0, runError="需要查询原任务")
        type(self).studio_task_statuses[task_id] = "recoverable"

        self.wait_for(lambda: not self.frame_evaluate("hypitNodeRunOperations.has('image-run')"),
                      "recoverable 不应让页面无限等待，但必须保留原任务身份")
        self.assertEqual(self.frame_evaluate("hypitStoredRunRequestId('image-run')"), request_id,
                         "未确认终态的 recoverable 任务不能清除原 request_id")
        self.assertFalse(self.frame_evaluate("document.getElementById('runBtn').disabled"),
                         "用户需要能手动重查 recoverable 任务")
        self.assertIn("待恢复", self.frame_evaluate("document.querySelector('.creation-task')?.textContent || ''"),
                      "recoverable 应说明需要用户查询原任务，不能继续显示为正在生成")

        self.frame_evaluate("document.getElementById('runBtn').click(); true")
        self.wait_for(lambda: not self.frame_evaluate("hypitNodeRunOperations.has('image-run')"),
                      "使用同一 request_id 查询原 recoverable 任务后仍未结束")
        self.assertEqual(self.frame_evaluate("hypitStoredRunRequestId('image-run')"), request_id,
                         "重查到 recoverable 后仍应保留幂等 request_id")
        self.assertEqual(len([item for item in self.agent_command_posts if item.get("action") == "run_node"]), 1,
                         "重查不能再创建一次 run_node 提交")
        self.assertEqual(self.agent_task_counter, 1, "recoverable 重查不能生成第二个 Studio 任务")
        self.assertGreaterEqual(self.agent_command_list_gets, 2, "重试应先查询已有命令，而不是重新提交")
        self.assertFalse(self.test_posts)

    def test_hypit_server_task_cancel_uses_one_shared_cancel_command(self):
        self.seed_canvas([
            {"id": "image-run", "type": "smart-image-generator", "x": 100, "y": 100,
             "runSettings": {"imageProvider": "fixture", "imageModel": "fixture-image"},
             "promptDraftText": "mock flow"},
            {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image", "x": 540, "y": 100},
        ], [{"id": "edge-image", "from": "image-run", "to": "image-output", "kind": "input"}])
        self.open_hypit_canvas()
        self.frame_evaluate("document.querySelector('.image-node[data-id=image-run]').click(); promptInput.textContent='mock flow'; promptInput.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:'mock flow'})); document.getElementById('runBtn').click(); true")
        self.wait_for(lambda: any(item.get("action") == "run_node" for item in self.agent_command_posts),
                      "无法为取消回归创建隔离 Studio task")
        self.wait_for(lambda: bool(self.frame_evaluate("!!document.querySelector('.creation-task [data-cancel-run]')")),
                      lambda: "共享任务状态没有显示普通取消入口：" + str(self.frame_evaluate("JSON.stringify({operation:hypitNodeRunOperations.has('image-run'),selectedId,nodes:nodes.map(n=>({id:n.id,creationId:n.creationId,creationTasks:n.creationTasks?.map(t=>({id:t.id,status:t.runStatus,pending:t.pending,creationId:t.creationId}))})),buttons:[...document.querySelectorAll('[data-cancel-run]')].map(b=>b.outerHTML),body:document.querySelector('.image-node[data-id=image-run]')?.innerHTML.slice(-1500)})")), timeout=3)
        self.frame_evaluate("document.querySelector('.creation-task [data-cancel-run]').click(); true")
        self.wait_for(lambda: len(self.agent_cancel_posts) == 1, "取消没有进入共享 cancel_run 命令")
        cancel = self.agent_cancel_posts[0]
        run = next(item for item in self.agent_command_posts if item.get("action") == "run_node")
        task_id = self.agent_commands[run["request_id"]]["result"]["task_ids"][0]
        self.assertEqual(cancel.get("action"), "cancel_run", cancel)
        self.assertEqual(cancel.get("args"), {"node_id": "image-run", "task_id": task_id}, cancel)
        time.sleep(0.15)
        self.assertEqual(len(self.agent_cancel_posts), 1, "重复点击不能重复发送取消命令")
        self.assertEqual(len([item for item in self.agent_command_posts if item.get("action") == "run_node"]), 1)
        self.assertFalse(self.test_posts)
        self.assertFalse(any(path.startswith("/api/canvas-tasks/") for path in self.write_paths), self.write_paths)

    def test_atomic_reset_never_saves_an_empty_graph_with_put(self):
        self.seed_canvas([{"id": "preserved-until-reset", "type": "smart-material", "sourceKind": "input",
                           "hypitInputLocked": False, "images": [], "x": 0, "y": 0}])
        self.open_hypit_canvas()
        self.evaluate("window.StudioDialog={confirm:async()=>true}")
        self.evaluate("document.getElementById('hypitSettingsReset').click(); true")
        self.wait_for(lambda: bool(self.reset_posts), "重置没有调用原子 reset endpoint")
        self.assertEqual(len(self.reset_posts), 1)
        self.assertEqual(self.write_paths, ["/api/hypit/settings-canvas/reset"], "重置禁止退化成 PUT 空画布")
        self.assertEqual(self.canvas["nodes"], [])
        self.assertEqual(self.canvas["connections"], [])

    def test_failed_or_wrong_physical_output_does_not_turn_green(self):
        self.seed_canvas([
            {"id": "image-run", "type": "smart-image-generator", "x": 100, "y": 100,
             "runSettings": {"apiKind": "image", "imageProvider": "fixture", "imageModel": "fixture-image",
                             "videoMultimodal": True, "videoUseFrameRoles": False}},
            {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image", "x": 540, "y": 100},
        ], [{"id": "edge-image", "from": "image-run", "to": "image-output", "kind": "input"}])
        type(self).test_statuses = {"image-output": {"status": "passed", "test_passed": True,
            "current_recipe_matches": True, "output_kind": "video", "error": "fixture output type mismatch"}}
        self.open_hypit_canvas()
        self.assertTrue(self.frame_evaluate("document.querySelector('.hypit-output-node').dataset.hypitStatus !== 'passed'"),
                        "物理输出类型与用途不一致时不能显示绿色")
        self.assertFalse(self.test_posts, "错误类型状态不得通过独立测试接口修饰为绿色")

    def test_output_status_uses_three_colored_borders_and_short_accessible_labels(self):
        self.seed_canvas([
            {"id": "image-run", "type": "smart-image-generator", "x": 100, "y": 100,
             "runSettings": {"apiKind": "image", "imageProvider": "fixture", "imageModel": "fixture-image",
                             "videoMultimodal": True, "videoUseFrameRoles": False}},
            {"id": "video-run", "type": "smart-video-generator", "x": 100, "y": 320,
             "runSettings": {"apiKind": "video", "videoProvider": "fixture", "videoModel": "fixture-video",
                             "videoMultimodal": True, "videoUseFrameRoles": False}},
            {"id": "output-red", "type": "smart-hypit-output", "hypitSlot": "text", "outputKind": "text", "x": 540, "y": 20},
            {"id": "output-yellow", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image", "x": 540, "y": 220},
            {"id": "output-green", "type": "smart-hypit-output", "hypitSlot": "video", "outputKind": "video", "x": 540, "y": 420},
        ], [
            {"id": "edge-yellow", "from": "image-run", "to": "output-yellow", "kind": "input"},
            {"id": "edge-green", "from": "video-run", "to": "output-green", "kind": "input"},
        ], {
            "output-green": {"status": "passed", "test_passed": True, "current_recipe_matches": True, "output_kind": "video"},
        })
        self.open_hypit_canvas()

        self.frame_evaluate("document.querySelector('.hypit-output-node[data-id=output-yellow]').click(); true")
        state = json.loads(self.frame_evaluate("JSON.stringify(['output-red','output-yellow','output-green'].map(id=>{const node=document.querySelector(`.hypit-output-node[data-id=${JSON.stringify(id)}]`);const style=getComputedStyle(node);return {id,status:node.dataset.hypitStatus,border:style.borderTopColor,title:node.getAttribute('title'),label:node.getAttribute('aria-label'),selected:node.classList.contains('selected'),visibleCopy:node.querySelector('.hypit-output-status-copy')?.textContent||'',body:node.querySelector('.hypit-output-body')?.innerText||'',type:node.querySelector('.hypit-output-title')?.textContent.trim()||''};}))"))
        self.assertEqual([item["status"] for item in state], ["disconnected", "ready", "passed"], state)
        self.assertEqual([item["border"] for item in state], ["rgb(220, 38, 38)", "rgb(213, 155, 32)", "rgb(33, 131, 75)"], state)
        self.assertEqual([item["type"] for item in state], ["文本输出", "图片输出", "视频输出"], state)
        self.assertEqual([item["title"] for item in state], ["未连接", "待运行", "运行成功"], state)
        self.assertEqual([item["label"] for item in state], ["文本输出 · 未连接", "图片输出 · 待运行", "视频输出 · 运行成功"], state)
        selected = next(item for item in state if item["id"] == "output-yellow")
        self.assertTrue(selected["selected"], f"测试应通过真实节点点击检查选中态：{state}")
        self.assertEqual(selected["border"], "rgb(213, 155, 32)", "选中态的焦点光晕不能覆盖用途状态边框")
        self.assertTrue(all("测试" not in item["visibleCopy"] + item["body"] + item["title"] + item["label"] for item in state), state)
        self.assertTrue(all(item["label"] for item in state), state)

    def test_saved_green_projection_survives_canvas_reload(self):
        self.seed_canvas([
            {"id": "image-run", "type": "smart-image-generator", "x": 100, "y": 100,
             "runSettings": {"apiKind": "image", "imageProvider": "fixture", "imageModel": "fixture-image",
                             "videoMultimodal": True, "videoUseFrameRoles": False}},
            {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image", "x": 540, "y": 100},
        ], [{"id": "edge-image", "from": "image-run", "to": "image-output", "kind": "input"}],
        {"image-output": {"status": "succeeded", "test_passed": True, "current_recipe_matches": True, "output_kind": "image"}})
        self.open_hypit_canvas()
        self.wait_for(lambda: self.frame_evaluate("document.querySelector('.hypit-output-node')?.dataset.hypitStatus === 'passed'"),
                      "服务端保存的有效通过状态在首次加载后应投影为绿色")

    def test_recipe_edits_invalidate_passed_state_but_result_projection_does_not(self):
        self.seed_canvas([
            {"id": "reference", "type": "smart-material", "sourceKind": "input", "creationId": "creation-reference-fixture", "x": 30, "y": 90,
             "images": [{"id": "fixture-ref", "url": "/fixture-ref.png", "kind": "image", "name": "参考图"}]},
            {"id": "prompt-source", "type": "smart-prompt", "x": 40, "y": 280,
             "text": "初始正文", "prompt": "初始提示词", "inputs": [{"key": "first", "value": "初始输入"}],
             "llmProvider": "comfly", "llmModel": "gpt-4o-mini", "llmSystemEnabled": False,
             "promptSplitEnabled": False, "promptSeparator": ";"},
            {"id": "prompt-source-alt", "type": "smart-prompt", "x": 40, "y": 420,
             "text": "备用正文", "prompt": "备用提示词", "inputs": [{"key": "alt", "value": "备用输入"}],
             "llmProvider": "comfly", "llmModel": "gpt-4o-mini", "llmSystemEnabled": False,
             "promptSplitEnabled": False, "promptSeparator": ";"},
            {"id": "image-run", "type": "smart-image-generator", "x": 390, "y": 100,
             "runSettings": {"apiKind": "image", "imageProvider": "fixture", "imageModel": "fixture-image",
                             "angle": "square", "videoMultimodal": True, "videoUseFrameRoles": False},
             "creationId": "creation-image-fixture",
             "creationInputBinding": [{"source": "creation-reference-fixture", "version": "", "field": ""},
                                       {"source": "prompt-source", "version": "", "field": ""}],
             "promptDraftText": "fixture prompt", "blockedInputRefs": [], "inputRefOrder": ["url|/fixture-ref.png"],
             "images": [{"url": "/old-result.png", "kind": "image"}], "outputKind": "image", "sourceKind": "result"},
            {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image", "x": 800, "y": 100},
        ], [
            {"id": "reference-edge", "from": "reference", "to": "image-run", "kind": "input"},
            {"id": "prompt-edge", "from": "prompt-source", "to": "image-run", "kind": "input"},
            {"id": "image-edge", "from": "image-run", "to": "image-output", "kind": "input"},
        ], {"image-output": {"status": "passed", "test_passed": True,
            "current_recipe_matches": True, "output_kind": "image"}})
        self.open_hypit_canvas()
        self.wait_for(lambda: self.frame_evaluate("document.querySelector('.hypit-output-node')?.dataset.hypitStatus === 'passed'"),
                      "服务端确认当前配方通过后应显示为绿色")
        self.frame_evaluate("window.__hypitDraftRecipeBaseline=CANVAS_SYNC.clone(canvasSyncCurrentSnapshot()); true")

        signatures = self.frame_evaluate("JSON.stringify((()=>{const before=hypitRecipeSignature('image-output');const node=nodes.find(item=>item.id==='image-run');node.images=[{url:'/new-result.png',kind:'image'}];node.outputKind='video';node.sourceKind='generated';hypitObserveRecipeChanges();updateHypitOutputStatuses();return {before,after:hypitRecipeSignature('image-output'),status:document.querySelector('.hypit-output-node')?.dataset.hypitStatus};})())")
        observed = json.loads(signatures)
        self.assertEqual(observed["before"], observed["after"], "结果媒体及执行回填的 outputKind/sourceKind 不属于生成配方")
        self.assertEqual(observed["status"], "passed", "仅结果回填变化不能使已通过的配方变黄")

        def change_recipe(script, label):
            self.frame_evaluate("canvasSyncApplySnapshot(CANVAS_SYNC.clone(window.__hypitDraftRecipeBaseline)); " + script + "; hypitObserveRecipeChanges(); updateHypitOutputStatuses(); true")
            self.assertTrue(self.frame_evaluate("document.querySelector('.hypit-output-node')?.dataset.hypitStatus !== 'passed'"),
                            f"{label}改变后旧的通过状态必须失效")
            self.assertTrue(self.frame_evaluate("hypitTestStatuses['image-output']?.test_passed===true"),
                            f"{label}变化应保持旧服务端结果，只有未保存草稿签名阻止显示绿色")

        change_recipe("nodes.find(node=>node.id==='image-run').blockedInputRefs=['url|/fixture-ref.png']",
                      "屏蔽输入引用")
        change_recipe("nodes.find(node=>node.id==='image-run').inputRefOrder=['url|/another-ref.png','url|/fixture-ref.png']",
                      "输入引用顺序")
        change_recipe("nodes.find(node=>node.id==='prompt-source').text='更新后的正文'",
                      "smart-prompt 正文")
        change_recipe("nodes.find(node=>node.id==='prompt-source').prompt='更新后的提示词'",
                      "smart-prompt 提示词")
        change_recipe("nodes.find(node=>node.id==='prompt-source').inputs=[{key:'second',value:'更新后的输入'}]",
                      "smart-prompt 输入")
        change_recipe("nodes.find(node=>node.id==='image-run').runSettings.angle='portrait'",
                      "未保存的生成参数")
        change_recipe("canvas.connections.find(edge=>edge.id==='prompt-edge').from='prompt-source-alt'",
                      "未保存的上游连接")
        self.assertTrue(self.frame_evaluate("hypitTestStatuses['image-output']?.test_passed===true"),
                        "服务端旧 passed 投影应仍在；本地未保存草稿必须靠配方签名保持黄色")

    def test_hypit_extensions_stay_hidden_on_an_ordinary_canvas(self):
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/static/smart-canvas.html?id=ordinary-fixture"})
        self.assertTrue(self.evaluate("(async()=>{for(let i=0;i<100;i++){if(document.readyState==='complete'&&document.getElementById('hypitCanvasTools'))return true;await new Promise(r=>setTimeout(r,30));}return false;})()"))
        state = self.evaluate("JSON.stringify({mode:document.documentElement.dataset.canvasMode,toolsHidden:document.getElementById('hypitCanvasTools').hidden,drawerHidden:document.getElementById('hypitOutputDrawer').hidden,lockButtons:document.querySelectorAll('[data-hypit-input-lock]').length,outputNodes:document.querySelectorAll('.hypit-output-node').length})")
        self.assertEqual(json.loads(state), {"toolsHidden": True, "drawerHidden": True, "lockButtons": 0, "outputNodes": 0})

    def test_real_port_drag_rejects_static_mismatch_but_accepts_dynamic_app_and_replaces_edge(self):
        self.seed_canvas([
            {"id": "video-run", "type": "smart-video-generator", "x": 40, "y": 80,
             "runSettings": {"videoProvider": "fixture", "videoModel": "fixture-video"}},
            {"id": "app-one", "type": "smart-ai-app", "x": 330, "y": 80,
             "runSettings": {"engine": "runninghub", "rhAppId": "fixture-app"}},
            {"id": "app-two", "type": "smart-comfy-workflow", "x": 330, "y": 160,
             "runSettings": {"engine": "comfy", "comfyWorkflow": "fixture-workflow"}},
            {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image", "x": 710, "y": 80},
            {"id": "audio-output", "type": "smart-hypit-output", "hypitSlot": "audio", "outputKind": "audio", "x": 710, "y": 160},
        ])
        self.open_hypit_canvas()
        self.wait_for(lambda: self.frame_evaluate("document.querySelectorAll('.image-node').length === 5"), "测试节点没有加载")
        self.drag_connect("video-run", "image-output")
        self.assertTrue(self.frame_evaluate("document.querySelector('.hypit-output-node[data-hypit-slot=image]')?.dataset.hypitStatus === 'disconnected'"),
                        "静态视频节点不能连到图片用途")
        self.drag_connect("app-one", "audio-output")
        self.wait_for(lambda: self.frame_evaluate("document.querySelector('.hypit-output-node[data-hypit-slot=audio]')?.dataset.hypitStatus === 'ready'"),
                      "动态 AI 应用的未知输出类型应允许接线并交给执行测试校验")
        self.wait_for(lambda: bool(self.canvas_puts), "动态 AI 应用连线没有保存")
        self.assertEqual(len([edge for edge in self.canvas.get("connections", []) if edge.get("to") == "audio-output"]), 1)
        self.assertEqual(next(edge for edge in self.canvas["connections"] if edge.get("to") == "audio-output")["from"], "app-one")
        self.drag_connect("app-two", "audio-output")
        self.wait_for(lambda: len(self.canvas_puts) >= 2 and any(edge.get("from") == "app-two" and edge.get("to") == "audio-output" for edge in self.canvas.get("connections", [])),
                      "连接新动态工作流后没有替换旧入边")
        audio_edges = [edge for edge in self.canvas["connections"] if edge.get("to") == "audio-output"]
        self.assertEqual(len(audio_edges), 1, "每个用途输出只能保留一个执行来源")
        self.assertEqual(audio_edges[0]["from"], "app-two")

    def test_hypit_dynamic_app_input_keeps_explicit_field_binding_for_mismatched_media(self):
        self.seed_canvas([
            {"id": "image-source", "type": "smart-material", "sourceKind": "input", "x": 40, "y": 100,
             "images": [{"id": "fixture-image", "kind": "image", "url": "/fixture-image.png", "name": "参考图片"}]},
            {"id": "app-target", "type": "smart-ai-app", "x": 650, "y": 100,
             "runSettings": {"engine": "runninghub", "rhFields": [
                 {"nodeId": "7", "fieldName": "video_input", "label": "视频输入", "fieldType": "VIDEO", "enabled": True},
             ]}},
        ])
        self.open_hypit_canvas()
        self.wait_for(lambda: self.frame_evaluate("document.querySelectorAll('.image-node').length === 2"), "动态 AI 应用输入测试节点没有加载")
        self.drag_connect_to_execution("image-source", "app-target")
        picker_state = self.frame_evaluate("JSON.stringify({picker:!!document.querySelector('.smart-rh-field-picker'),choices:[...document.querySelectorAll('.smart-rh-field-picker [data-rh-target-field]')].map(el=>el.dataset.rhTargetField),edges:(canvas.connections||[]).filter(edge=>edge.to==='app-target').length,mode:isHypitSettingsMode})")
        self.assertTrue(json.loads(picker_state)["picker"], f"媒体类型不匹配时仍须让用户显式选择动态字段：{picker_state}")
        self.assertEqual(json.loads(picker_state)["choices"], ["7::video_input"], "不能猜字段，也不能把类型不匹配误当作类型匹配")
        self.assertEqual(json.loads(picker_state)["edges"], 0, "字段确认前不能静默建立无绑定连线")
        self.frame_evaluate("document.querySelector('.smart-rh-field-picker [data-rh-target-field]').click(); true")
        self.wait_for(lambda: bool(self.canvas_puts), "用户明确选择字段后没有保存共享画布")
        edge = next(edge for edge in self.canvas["connections"] if edge.get("to") == "app-target")
        self.assertEqual(edge.get("targetFieldKey"), "7::video_input", "即使类型不匹配也必须保存用户选定的动态输入字段")

    def test_hypit_dynamic_app_input_requires_explicit_field_for_unknown_tool_output(self):
        self.seed_canvas([
            {"id": "angle-tool", "type": "smart-angle-control", "x": 40, "y": 100},
            {"id": "app-target", "type": "smart-ai-app", "x": 650, "y": 100,
             "runSettings": {"engine": "runninghub", "rhFields": [
                 {"nodeId": "8", "fieldName": "prompt", "label": "提示词", "fieldType": "STRING", "enabled": True},
             ]}},
        ])
        self.open_hypit_canvas()
        self.wait_for(lambda: self.frame_evaluate("document.querySelectorAll('.image-node').length === 2"), "动态输入测试节点没有加载")
        self.drag_connect_to_execution("angle-tool", "app-target")
        pending = self.frame_evaluate("JSON.stringify({picker:!!document.querySelector('.smart-rh-field-picker'),choices:[...document.querySelectorAll('.smart-rh-field-picker [data-rh-target-field]')].map(el=>el.dataset.rhTargetField),edges:(canvas.connections||[]).filter(edge=>edge.to==='app-target').length})")
        self.assertEqual(json.loads(pending), {"picker": True, "choices": ["8::prompt"], "edges": 0},
                         f"未知类型输入必须停在明确字段选择，不能预判拒绝或自动猜字段：{pending}")
        self.frame_evaluate("document.querySelector('.smart-rh-field-picker [data-rh-target-field]').click(); true")
        self.wait_for(lambda: bool(self.canvas_puts), "工具输出选择目标字段后没有持久化")
        edge = next(edge for edge in self.canvas["connections"] if edge.get("to") == "app-target")
        self.assertEqual(edge.get("from"), "angle-tool")
        self.assertEqual(edge.get("targetFieldKey"), "8::prompt")

    def test_adding_output_keeps_output_port_clear_of_open_composer(self):
        self.seed_canvas([{
            "id": "text-run", "type": "smart-text-generator", "x": 50, "y": 120,
            "runSettings": {"textProvider": "fixture", "textModel": "fixture-text"},
            "promptDraftText": "test prompt",
        }])
        self.open_hypit_canvas()
        self.frame_evaluate("document.querySelector('.image-node[data-id=text-run]').click(); true")
        self.wait_for(lambda: self.frame_evaluate("document.getElementById('composer')?.classList.contains('open')"), "测试前未能打开真实节点 composer")
        self.frame_evaluate("document.getElementById('hypitOutputDrawerToggle').click(); document.querySelector('[data-hypit-slot=text]').click(); true")
        state = self.frame_evaluate("JSON.stringify((()=>{const output=document.querySelector('.hypit-output-node[data-hypit-slot=text]');const composer=document.getElementById('composer');const button=document.getElementById('hypitOutputDrawerToggle');const a=output?.getBoundingClientRect(),b=composer?.classList.contains('open')?composer.getBoundingClientRect():null,t=button?.getBoundingClientRect();return {output:a&&{left:a.left,right:a.right,top:a.top,bottom:a.bottom},button:t&&{left:t.left,right:t.right,top:t.top,bottom:t.bottom},viewport:{width:innerWidth,height:innerHeight},composerOpen:!!b,composer:b&&{left:b.left,right:b.right,top:b.top,bottom:b.bottom},canvasRect:document.getElementById('shell')?.getBoundingClientRect().toJSON()};})())")
        observed = json.loads(state)
        self.assertTrue(observed["output"], f"添加后固定输出节点必须出现在可视区域：{state}")
        self.assertGreaterEqual(observed["output"]["left"], observed["canvasRect"]["left"] - 1, state)
        self.assertLessEqual(observed["output"]["right"], observed["canvasRect"]["right"] + 1, state)
        self.assertGreaterEqual(observed["output"]["top"], observed["canvasRect"]["top"] - 1, state)
        self.assertLessEqual(observed["output"]["bottom"], observed["canvasRect"]["bottom"] + 1, state)
        if observed["composerOpen"]:
            output, composer_rect = observed["output"], observed["composer"]
            overlaps = output["left"] < composer_rect["right"] and output["right"] > composer_rect["left"] and output["top"] < composer_rect["bottom"] and output["bottom"] > composer_rect["top"]
            self.assertFalse(overlaps, f"聚焦用途输出后不能被仍打开的 composer 遮住：{state}")
            toggle = observed["button"]
            toggle_overlaps = toggle["left"] < composer_rect["right"] and toggle["right"] > composer_rect["left"] and toggle["top"] < composer_rect["bottom"] and toggle["bottom"] > composer_rect["top"]
            self.assertFalse(toggle_overlaps, f"输出端口入口不能被打开的 composer 遮挡：{state}")

    def test_hypit_image_picker_uses_slot_contract_without_replacing_saved_model(self):
        self.seed_image_model_catalog()
        self.seed_canvas([
            {"id": "image-run", "type": "smart-image-generator", "x": 100, "y": 100,
             "runSettings": {"engine": "api", "apiKind": "image", "provider_id": "fixture-provider",
                             "model": "fixture-image-excluded", "imageFamilyId": "excluded-family"},
             "promptDraftText": "fixture prompt"},
            {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image", "x": 540, "y": 100},
        ], [{"id": "edge-image", "from": "image-run", "to": "image-output", "kind": "input"}])
        self.open_hypit_canvas()
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('.image-node[data-id=image-run]')"),
                      "图片生成节点尚未加载")
        self.frame_evaluate("document.querySelector('.image-node[data-id=image-run]').click(); true")
        self.wait_for(lambda: ("hypit", "image") in self.model_option_requests,
                      "Hypit 图片模型选择没有向槽位契约读取过滤后的候选")
        diagnostic_expression = """JSON.stringify({
          text:document.getElementById('dynamicParams')?.innerText,
          cache:[...hypitSlotModelOptions.entries()],
          active:activeSettingsSubject()?.id,
          context:hypitModelSlotContext(activeSettingsSubject()),
          engine:settings.engine,
          pendingNode:hypitModelOptionPendingNodeId,
          pendingKey:hypitModelOptionPendingContextKey
        })"""
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('[data-capability-model-picker] [data-capability-picker-stage=family]')"),
                      lambda: "图片模型选择器未在契约候选返回后恢复：" + self.frame_evaluate(diagnostic_expression))
        state = json.loads(self.frame_evaluate("JSON.stringify({families:[...document.querySelectorAll('[data-capability-picker-stage=family] [data-capability-picker-option]')].map(el=>el.dataset.capabilityPickerFamily),model:settings.model,nodeModel:nodes.find(node=>node.id==='image-run')?.runSettings?.model})"))
        self.assertEqual(state["families"], ["series-image-allowed-family"], "Hypit 生成节点只能展示后端为当前用途放行的家族")
        self.assertEqual(state["model"], "fixture-image-excluded", "已保存但当前用途不允许的旧模型必须保留，不能偷偷替换")
        self.assertEqual(state["nodeModel"], "fixture-image-excluded")
        self.assertEqual(self.model_option_requests, [("hypit", "image")])

    def test_hypit_model_path_is_draft_until_leaf_and_failed_save_can_retry(self):
        self.seed_image_model_catalog()
        self.seed_canvas([{
            "id": "image-run", "type": "smart-image-generator", "x": 100, "y": 100,
            "runSettings": {"engine": "api", "apiKind": "image", "provider_id": "fixture-provider",
                            "model": "fixture-image-excluded", "imageFamilyId": "excluded-family"},
            "promptDraftText": "fixture prompt",
        }, {
            "id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image",
            "outputKind": "image", "x": 540, "y": 100,
        }], [{"id": "edge-image", "from": "image-run", "to": "image-output", "kind": "input"}])
        self.open_hypit_canvas()
        self.frame_evaluate("document.querySelector('.image-node[data-id=image-run]').click(); true")
        self.wait_for(lambda: ("hypit", "image") in self.model_option_requests,
                      "Hypit 图片模型菜单未读取当前输出用途的候选")
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('[data-capability-model-picker] .capability-model-picker-pill')"),
                      "真实画布没有渲染共享模型选择入口")
        self.frame_evaluate("document.querySelector('[data-capability-model-picker] .capability-model-picker-pill').click(); true")
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('[data-capability-picker-stage=family] [data-capability-picker-option]')"),
                      "模型家族列表没有打开")

        family = self.frame_evaluate("JSON.stringify({families:[...document.querySelectorAll('[data-capability-picker-stage=family] [data-capability-picker-option]')].map(row=>row.dataset.capabilityPickerValue),selected:settings.model,puts:canvasSyncSaveQueued})")
        self.assertEqual(json.loads(family)["families"], ["series-image-allowed-family"], family)
        self.assertEqual(json.loads(family)["selected"], "fixture-image-excluded", "当前用途不允许的已保存选择要保留")
        self.assertEqual(self.canvas_put_attempts, 0, "打开模型菜单不写画布")

        self.frame_evaluate("document.querySelector('[data-capability-picker-stage=family] [data-capability-picker-option]').click(); true")
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('[data-capability-picker-stage=platform] [data-capability-picker-option]')"),
                      "选择家族后没有显示可用平台")
        self.frame_evaluate("document.querySelector('[data-capability-picker-stage=platform] [data-capability-picker-option]').click(); true")
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('[data-capability-picker-stage=variant] [data-capability-picker-option]')"),
                      "选择平台后没有显示运行模式")
        before_leaf = json.loads(self.frame_evaluate("JSON.stringify({model:settings.model,nodeModel:nodes.find(node=>node.id==='image-run')?.runSettings?.model,attempts:canvasSyncSaveQueued})"))
        self.assertEqual(self.canvas_put_attempts, 0, "家族/平台浏览不得保存")
        self.assertEqual(self.canvas["nodes"][0]["runSettings"]["model"], "fixture-image-excluded",
                         "家族/平台草稿不能改写服务端已保存模型")

        type(self).fail_canvas_puts = 1
        leaf = self.frame_evaluate("JSON.stringify([...document.querySelectorAll('[data-capability-picker-stage=variant] [data-capability-picker-option]')].map(row=>({model:row.dataset.capabilityPickerModel,value:row.dataset.capabilityPickerValue,badges:[...row.querySelectorAll('.capability-picker-option-badge')].map(b=>b.textContent.trim())})))")
        leaves = json.loads(leaf)
        target = next((item for item in leaves if item["model"] == "fixture-image-valid"), None)
        self.assertIsNotNone(target, leaf)
        self.assertIn("文生图", target["badges"], "真实候选仍应展示来自能力契约的用途标签")
        self.frame_evaluate(f"document.querySelector('[data-capability-picker-stage=variant] [data-capability-picker-option][data-capability-picker-model={json.dumps(target['model'])}]').click(); true")
        self.wait_for(lambda: self.canvas_put_attempts == 1,
                      "只在选择运行模式后才应提交画布")
        self.wait_for(lambda: not self.frame_evaluate("canvasSyncInFlight"),
                      "失败的画布保存请求未结束")
        failed_state = json.loads(self.frame_evaluate("JSON.stringify({model:settings.model,nodeModel:nodes.find(node=>node.id==='image-run')?.runSettings?.model,toast:document.querySelector('#toast .toast-message')?.textContent||''})"))
        self.assertEqual(failed_state["model"], "fixture-image-valid", failed_state)
        self.assertIn("fixture canvas save failed", failed_state["toast"], failed_state)
        self.assertEqual(self.canvas["nodes"][0]["runSettings"]["model"], "fixture-image-excluded",
                         "失败保存后服务端仍保留旧选择，不能假报成功")
        self.assertIn("fixture canvas save failed", failed_state["toast"], failed_state)
        self.assertEqual(len(self.canvas_puts), 0, "失败响应不能伪装成成功保存")

        self.frame_evaluate("document.querySelector('[data-capability-model-picker] .capability-model-picker-pill').click(); true")
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('[data-capability-picker-stage=variant] [data-capability-picker-option]')"),
                      "失败后应能重新打开候选并重试")
        self.frame_evaluate(f"document.querySelector('[data-capability-picker-stage=variant] [data-capability-picker-option][data-capability-picker-model={json.dumps(target['model'])}]').click(); true")
        self.wait_for(lambda: self.canvas_put_attempts == 2 and len(self.canvas_puts) == 1,
                      "重试叶子选择应完成一次有效保存")
        self.assertEqual(self.write_paths, ["/api/canvases/hypit-settings", "/api/canvases/hypit-settings"])
        saved_node = next(node for node in self.canvas["nodes"] if node["id"] == "image-run")
        self.assertEqual(saved_node["runSettings"]["model"], "fixture-image-valid")
        self.assertEqual(self.model_option_requests, [("hypit", "image")], "浏览和重试都复用已读用途候选")

    def test_delayed_old_canvas_reload_cannot_revert_a_saved_model_selection(self):
        self.seed_image_model_catalog(allowed_model="fixture-image-next", excluded_model="fixture-image-current")
        type(self).module_model_options["image"] = list(self.module_model_options["image"]) + [
            option for option in self.model_capabilities_payload["options"]
            if option["catalog_model_id"] == "fixture-image-current"
        ]
        self.seed_canvas([{
            "id": "image-run", "type": "smart-image-generator", "x": 100, "y": 100,
            "runSettings": {"engine": "api", "apiKind": "image", "provider_id": "fixture-provider",
                            "model": "fixture-image-current", "imageFamilyId": "excluded-family"},
            "promptDraftText": "fixture prompt",
        }, {
            "id": "image-other", "type": "smart-image-generator", "x": 420, "y": 100,
            "runSettings": {"engine": "api", "apiKind": "image", "provider_id": "fixture-provider",
                            "model": "fixture-image-current", "imageFamilyId": "excluded-family"},
            "promptDraftText": "other fixture prompt",
        }], [])
        self.open_hypit_canvas()
        self.frame_evaluate("document.querySelector('.image-node[data-id=image-run]').click(); true")
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('[data-capability-model-picker] .capability-model-picker-pill')"),
                      "模型菜单未能挂载")

        # 模拟较慢的多标签 GET：服务先返回旧快照，但客户端暂不处理响应。
        # 在该回包等待期间，用户选择新模式并保存，随后旧 GET 才到达。
        self.frame_evaluate("""(()=>{
          const originalFetch=window.fetch.bind(window);
          window.__delayedOldCanvasReadCaptured=false;
          window.__releaseDelayedOldCanvasRead=null;
          window.__delayedOldCanvasReadDone=false;
          window.fetch=async (input,init={})=>{
            const response=await originalFetch(input,init);
            const url=typeof input==='string'?input:input.url;
            if(window.__delayNextCanvasRead&&url.includes('/api/canvases/hypit-settings')&&String(init.method||'GET').toUpperCase()==='GET'){
              window.__delayNextCanvasRead=false;
              const payload=await response.clone().json();
              window.__delayedOldCanvasPayload={revision:payload.canvas?.revision,model:payload.canvas?.nodes?.find(node=>node.id==='image-run')?.runSettings?.model};
              window.__delayedOldCanvasReadCaptured=true;
              await new Promise(resolve=>window.__releaseDelayedOldCanvasRead=resolve);
              return new Response(JSON.stringify(payload),{status:response.status,headers:{'Content-Type':'application/json'}});
            }
            return response;
          };
          window.__delayNextCanvasRead=true;
          window.__delayedOldCanvasRead=mergeReloadCanvasNow().finally(()=>window.__delayedOldCanvasReadDone=true);
          return true;
        })()""")
        self.wait_for(lambda: self.frame_evaluate("window.__delayedOldCanvasReadCaptured"),
                      "旧画布 GET 没有进入延迟点")

        self.frame_evaluate("document.querySelector('[data-capability-model-picker] .capability-model-picker-pill').click(); true")
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('[data-capability-picker-stage=family] [data-capability-picker-option]')"),
                      "模型家族列表没有打开")
        self.frame_evaluate("document.querySelector('[data-capability-picker-stage=family] [data-capability-picker-option][data-capability-picker-value=series-image-allowed-family]').click(); true")
        self.frame_evaluate("document.querySelector('[data-capability-picker-stage=platform] [data-capability-picker-option]').click(); true")
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('[data-capability-picker-stage=variant] [data-capability-picker-option][data-capability-picker-model=fixture-image-next]')"),
                      "目标运行模式没有显示")
        self.frame_evaluate("document.querySelector('[data-capability-picker-stage=variant] [data-capability-picker-option][data-capability-picker-model=fixture-image-next]').click(); true")
        def save_response_applied():
            server_has_new_model = any(
                node.get("runSettings", {}).get("model") == "fixture-image-next"
                for node in self.canvas.get("nodes", [])
            )
            client_state = json.loads(self.frame_evaluate(
                "JSON.stringify({"
                "node:nodes.find(node=>node.id==='image-run')?.runSettings?.model,"
                "settings:settings.model,"
                "base:canvasSyncBase?.nodes?.find(node=>node.id==='image-run')?.runSettings?.model,"
                "revision:canvas.revision,baseRevision:canvasSyncBase?.revision,"
                "inFlight:canvasSyncInFlight,queued:canvasSyncSaveQueued"
                "})"
            ))
            return (
                server_has_new_model
                and client_state["node"] == "fixture-image-next"
                and client_state["settings"] == "fixture-image-next"
                and client_state["base"] == "fixture-image-next"
                and client_state["revision"] == client_state["baseRevision"]
                and not client_state["inFlight"]
                and not client_state["queued"]
            )

        self.wait_for(save_response_applied,
                      "新模型 PUT 响应必须处理完成并同步服务端、客户端基线与 revision")
        saved_revision = self.canvas["revision"]
        saved_state = json.loads(self.frame_evaluate("JSON.stringify({local:nodes.find(node=>node.id==='image-run')?.runSettings?.model,base:canvasSyncBase?.nodes?.find(node=>node.id==='image-run')?.runSettings?.model,snapshot:canvasSyncCurrentSnapshot()?.nodes?.find(node=>node.id==='image-run')?.runSettings?.model,settings:settings.model,canvasSettings:canvas.settings?.model,revision:canvas.revision,baseRevision:canvasSyncBase?.revision})"))
        self.assertEqual(saved_state["base"], "fixture-image-next", f"PUT 成功后同步基线应包含新模型: {saved_state}")
        delayed = json.loads(self.frame_evaluate("JSON.stringify(window.__delayedOldCanvasPayload)"))
        self.assertEqual(delayed, {"revision": saved_revision - 1, "model": "fixture-image-current"},
                         f"竞态 fixture 必须确实持有保存前的旧模型响应: {delayed}")

        # 旧 GET 的 body 是在保存前捕获的。应用它不能覆盖已经确认保存的新选择。
        self.frame_evaluate("document.querySelector('.image-node[data-id=image-other]').click(); true")
        self.frame_evaluate("window.__releaseDelayedOldCanvasRead(); true")
        self.wait_for(lambda: self.frame_evaluate("window.__delayedOldCanvasReadDone"),
                      "延迟 GET 没有完成")
        self.frame_evaluate("document.querySelector('.image-node[data-id=image-run]').click(); true")
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('[data-capability-model-picker] .capability-model-picker-pill')"),
                      "重新打开目标节点时模型菜单未挂载")
        self.frame_evaluate("document.querySelector('[data-capability-model-picker] .capability-model-picker-pill').click(); true")
        state = json.loads(self.frame_evaluate("JSON.stringify({model:settings.model,nodeModel:nodes.find(node=>node.id==='image-run')?.runSettings?.model,snapshot:canvasSyncCurrentSnapshot()?.nodes?.find(node=>node.id==='image-run')?.runSettings?.model,settingsSnapshot:canvasSyncCurrentSnapshot()?.settings?.model,canvasSettings:canvas.settings?.model,revision:canvas.revision,baseRevision:canvasSyncBase?.revision,menuOpen:document.querySelector('[data-capability-model-picker]')?.classList.contains('pinned'),selectedLeaf:document.querySelector('[data-capability-picker-stage=variant] [data-capability-picker-option].active')?.dataset.capabilityPickerModel})"))
        self.assertEqual(state["model"], "fixture-image-next", f"迟到的旧 GET 不得让参数面板恢复为旧模型: {state}")
        self.assertEqual(state["nodeModel"], "fixture-image-next", f"迟到的旧 GET 不得覆盖节点已保存模型: {state}")
        self.assertGreaterEqual(state["revision"], saved_revision, f"画布修订不能因旧回包倒退: {state}")
        self.assertTrue(state["menuOpen"], f"重新打开参数菜单时应继续显示当前选择: {state}")
        self.assertEqual(state["selectedLeaf"], "fixture-image-next", f"重新打开参数菜单不能选回旧运行模式: {state}")

        # Same-revision payloads may still carry an independent field from a
        # concurrent tab; only strictly older revisions are stale.
        equal_revision_remote = json.loads(json.dumps(self.canvas))
        equal_revision_remote["nodes"][1]["promptDraftText"] = "equal-revision remote edit"
        equal_revision_remote["nodes"][1]["title"] = "equal-revision remote title"
        equal_result = json.loads(self.frame_evaluate(
            f"JSON.stringify((()=>{{const result=applyMergedServerCanvas({json.dumps(equal_revision_remote)},{{prompt:false,scheduleSave:false}});const other=nodes.find(node=>node.id==='image-other');return {{stale:result?.stale===true,conflicts:result?.conflicts||[],model:nodes.find(node=>node.id==='image-run')?.runSettings?.model,other:other?.promptDraftText,otherTitle:other?.title,revision:canvas.revision}};}})())"
        ))
        self.assertFalse(equal_result["stale"], f"同 revision 的独立远端修改仍须合并: {equal_result}")
        self.assertEqual([item["path"] for item in equal_result["conflicts"]], ["nodes.image-other.promptDraftText"],
                         f"同 revision 上真实同字段冲突仍须报告: {equal_result}")
        self.assertEqual(equal_result["model"], "fixture-image-next", f"同 revision 合并不能丢失已保存模型: {equal_result}")
        self.assertEqual(equal_result["other"], "", f"同 revision 冲突不得覆盖本地字段: {equal_result}")
        self.assertEqual(equal_result["otherTitle"], "equal-revision remote title", f"同 revision 的独立远端字段应进入画布: {equal_result}")
        self.assertEqual(equal_result["revision"], saved_revision)

        higher_revision_remote = json.loads(json.dumps(equal_revision_remote))
        higher_revision_remote["revision"] = saved_revision + 1
        higher_revision_remote["nodes"][1]["title"] = "higher-revision remote edit"
        higher_result = json.loads(self.frame_evaluate(
            f"JSON.stringify((()=>{{const result=applyMergedServerCanvas({json.dumps(higher_revision_remote)},{{prompt:false,scheduleSave:false}});return {{stale:result?.stale===true,conflicts:result?.conflicts?.map(item=>item.path)||[],model:nodes.find(node=>node.id==='image-run')?.runSettings?.model,otherTitle:nodes.find(node=>node.id==='image-other')?.title,revision:canvas.revision}};}})())"
        ))
        self.assertFalse(higher_result["stale"], f"更高 revision 的远端快照应参与合并: {higher_result}")
        self.assertEqual(higher_result["conflicts"], [], f"其他节点的独立更新应无冲突合并: {higher_result}")
        self.assertEqual(higher_result["model"], "fixture-image-next", f"更高 revision 的另一节点更新不能覆盖所选模型: {higher_result}")
        self.assertEqual(higher_result["otherTitle"], "higher-revision remote edit", f"更高 revision 的其他节点更新应进入画布: {higher_result}")
        self.assertEqual(higher_result["revision"], saved_revision + 1)
        self.assertEqual(self.canvas["nodes"][0]["runSettings"]["model"], "fixture-image-next")

    def test_stale_409_keeps_revision_and_resaves_queued_canvas_draft(self):
        self.seed_canvas([{
            "id": "image-run", "type": "smart-image-generator", "x": 100, "y": 100,
            "runSettings": {"engine": "api", "apiKind": "image", "provider_id": "fixture-provider",
                            "model": "fixture-image-model"},
            "promptDraftText": "fixture prompt",
        }])
        type(self).canvas["revision"] = 2
        self.open_hypit_canvas()
        initial = json.loads(self.frame_evaluate("JSON.stringify({revision:canvas.revision,base:canvasSyncBase?.revision})"))
        self.assertEqual(initial, {"revision": 2, "base": 2})

        # The server advances while a revision-2 PUT is in flight. Its 409 body
        # is then delayed and made stale by a newer revision-3 canvas read.
        type(self).canvas["revision"] = 3
        type(self).canvas["title"] = "remote tab title"
        self.frame_evaluate("""(()=>{
          const originalFetch=window.fetch.bind(window);
          window.__stale409Captured=false;
          window.__releaseStale409=null;
          window.__old409SaveDone=false;
          window.fetch=async (input,init={})=>{
            const response=await originalFetch(input,init);
            const url=typeof input==='string'?input:input.url;
            if(url.includes('/api/canvases/hypit-settings')
              && String(init.method||'GET').toUpperCase()==='PUT' && response.status===409){
              const payload=await response.clone().json();
              window.__original409Revision=payload.detail?.canvas?.revision;
              payload.detail.canvas.revision=1;
              window.__stale409Captured=true;
              await new Promise(resolve=>window.__releaseStale409=resolve);
              return new Response(JSON.stringify(payload),{status:409,headers:{'Content-Type':'application/json'}});
            }
            return response;
          };
          nodes.find(node=>node.id==='image-run').title='draft in first request';
          canvas.nodes=nodes;
          window.__old409Save=saveCanvas().finally(()=>window.__old409SaveDone=true);
          return true;
        })()""")
        self.wait_for(lambda: self.frame_evaluate("window.__stale409Captured"), "冲突 PUT 没有进入延迟 409 响应")
        self.assertEqual(self.frame_evaluate("window.__original409Revision"), 3,
                         "fixture 必须先捕获服务端生成的 revision-3 冲突响应")

        # An edit and save request made while the first request is unresolved
        # must survive the stale response and be sent against the newer base.
        self.frame_evaluate("nodes.find(node=>node.id==='image-run').title='queued local draft'; canvas.nodes=nodes; true")
        self.assertTrue(self.frame_evaluate("saveCanvas().then(result=>result===false)"),
                        "在途期间的保存应排队等待当前 PUT 收尾")
        latest_remote = json.dumps(type(self).canvas, ensure_ascii=False)
        latest_state = json.loads(self.frame_evaluate(
            f"JSON.stringify((()=>{{const result=applyMergedServerCanvas({latest_remote},{{prompt:false,scheduleSave:false}});return {{stale:result?.stale===true,revision:canvas.revision,retryRevision:canvasSyncRetryBase?.revision,title:canvas.title,nodeTitle:nodes.find(node=>node.id==='image-run')?.title}};}})())"
        ))
        self.assertFalse(latest_state["stale"])
        self.assertEqual(latest_state["revision"], 3)
        self.assertEqual(latest_state["retryRevision"], 3)
        self.assertEqual(latest_state["title"], "remote tab title")
        self.assertEqual(latest_state["nodeTitle"], "queued local draft")

        self.frame_evaluate("window.__releaseStale409(); true")
        self.wait_for(lambda: self.frame_evaluate("window.__old409SaveDone"), "延迟的旧 409 没有完成")
        pending = json.loads(self.frame_evaluate("JSON.stringify({revision:canvas.revision,base:canvasSyncBase?.revision,retryBase:canvasSyncRetryBase?.revision,localTitle:nodes.find(node=>node.id==='image-run')?.title,dirty:canvasSyncHasLocalChanges(canvasSyncCurrentSnapshot(),canvasSyncRetryBase||canvasSyncBase),inFlight:canvasSyncInFlight,queued:canvasSyncSaveQueued,hasSaveTimer:Boolean(saveTimer)})"))
        self.assertEqual(pending["revision"], 3, f"迟到 409 不得降低画布 revision: {pending}")
        self.assertEqual(pending["retryBase"], 3, f"迟到 409 不得替换较新的同步基线: {pending}")
        self.assertEqual(pending["localTitle"], "queued local draft", f"本地草稿必须保留: {pending}")
        self.assertTrue(pending["dirty"], f"未提交草稿仍须相对新基线保持 dirty: {pending}")
        self.assertFalse(pending["inFlight"])
        self.assertFalse(pending["queued"], "finally 应消费 queued 标记并排入新的保存")
        self.assertTrue(pending["hasSaveTimer"], f"queued 保存应在冲突请求收尾后重新排队: {pending}")
        self.assertEqual(self.canvas_put_attempts, 1)

        self.wait_for(
            lambda: (
                self.canvas_put_attempts == 2
                and len(self.canvas_puts) == 1
                and self.canvas.get("revision") == 4
                and self.canvas.get("nodes", [{}])[0].get("title") == "queued local draft"
                and json.loads(self.frame_evaluate(
                    "JSON.stringify({revision:canvas.revision,base:canvasSyncBase?.revision,dirty:canvasSyncHasLocalChanges(canvasSyncCurrentSnapshot(),canvasSyncBase)})"
                )) == {"revision": 4, "base": 4, "dirty": False}
            ),
            "迟到 409 后排队的本地草稿没有按新基线完成保存与客户端同步",
        )
        self.assertEqual(self.canvas_put_attempts, 2, "冲突后的草稿必须只重试一次")
        self.assertEqual(len(self.canvas_puts), 1, "只应有排队草稿成功写入，原 409 不得计为成功")
        self.assertEqual(self.canvas_puts[0]["nodes"][0]["title"], "queued local draft",
                         "成功 PUT 必须携带队列中的最新草稿")
        self.assertEqual(self.canvas["revision"], 4)
        self.assertEqual(self.canvas["title"], "remote tab title")
        self.assertEqual(self.canvas["nodes"][0]["title"], "queued local draft")
        final_state = json.loads(self.frame_evaluate("JSON.stringify({revision:canvas.revision,base:canvasSyncBase?.revision,dirty:canvasSyncHasLocalChanges(canvasSyncCurrentSnapshot(),canvasSyncBase)})"))
        self.assertEqual(final_state, {"revision": 4, "base": 4, "dirty": False})

    def test_plain_canvas_image_picker_shows_enabled_gpt_image_25_models(self):
        self.seed_gpt_image_identity_catalog()
        self.seed_canvas([{
            "id": "image-input", "type": "smart-material", "sourceKind": "input", "inputNodeIds": [],
            "x": 80, "y": 360,
            "images": [{"url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l3sAAAAASUVORK5CYII=",
                        "kind": "image", "name": "fixture reference"}],
        }, {
            "id": "image-run", "type": "smart-image-generator", "x": 100, "y": 100,
            "runSettings": {"engine": "api", "apiKind": "image", "provider_id": "ai-money",
                            "model": "laohu-image-g-v2.5-flare", "imageFamilyId": "series-image-gpt-image"},
            "promptDraftText": "fixture prompt",
        }, {
            "id": "image-run-with-reference", "type": "smart-image-generator", "x": 480, "y": 100,
            "runSettings": {"engine": "api", "apiKind": "image", "provider_id": "ai-money",
                            "model": "laohu-image-g-v2.5-flare", "imageFamilyId": "series-image-gpt-image"},
            "promptDraftText": "fixture prompt with reference",
        }], [{"id": "fixture-reference-edge", "from": "image-input", "to": "image-run-with-reference", "kind": "input"}])
        # 本例只验候选浏览与输入过滤；使用当前 schema 的标准素材节点，
        # 避免把旧 smart-image 迁移保存混入“浏览模型不写入”的基线。
        type(self).canvas["node_schema_version"] = 7
        self.open_hypit_canvas()
        # 页面切换会再次启动真实画布加载。先在新文档执行前安装事件标记，
        # 这样不会把前一次 Hypit iframe 的旧窗口状态误当成普通模式已就绪。
        ready_script = self.cdp("Page.addScriptToEvaluateOnNewDocument", {"source":
            "window.addEventListener('canvas-ready',()=>{window.__plainCanvasReadyForTest=true;},{once:true});"})
        try:
            self.evaluate("document.getElementById('hypitSettingsCanvasFrame').src='/static/smart-canvas.html?id=hypit-settings'; true")

            def plain_canvas_ready():
                try:
                    return bool(self.frame_evaluate(
                        "window.__plainCanvasReadyForTest===true && !isSettingsCanvasMode && !isCanvasSettingsMode"))
                except AssertionError:
                    # iframe 导航切换执行上下文时会短暂不可读，继续等待新文档事件。
                    return False

            self.wait_for(plain_canvas_ready, "普通画布没有发出 canvas-ready 或仍处于模块配置模式", timeout=12)
        finally:
            if ready_script.get("identifier"):
                self.cdp("Page.removeScriptToEvaluateOnNewDocument", {"identifier": ready_script["identifier"]})

        # 先等页面自己的启动迁移/规范化写入收敛。成功 PUT 必须已经反映到
        # 客户端同步基线；若启动状态被阻塞或仍有草稿，则失败并保留诊断，不能
        # 通过清零请求计数把初始化写入藏掉。600ms 静默覆盖 450ms 保存防抖。
        settle_deadline = time.monotonic() + 15
        quiet_since = None
        last_signature = None
        settled_state = None
        while time.monotonic() < settle_deadline:
            try:
                state = json.loads(self.frame_evaluate("JSON.stringify((()=>{"
                    "const base=canvasSyncRetryBase||canvasSyncBase;"
                    "return {ready:window.__plainCanvasReadyForTest===true,"
                    "settingsMode:isSettingsCanvasMode,canvasSettingsMode:isCanvasSettingsMode,"
                    "revision:Number(canvas?.revision||0),baseRevision:Number(base?.revision||0),"
                    "dirty:base?canvasSyncHasLocalChanges(canvasSyncCurrentSnapshot(),base):true,"
                    "inFlight:canvasSyncInFlight,queued:canvasSyncSaveQueued,blocked:canvasSyncSaveBlocked,"
                    "saveTimer:Boolean(saveTimer)};})())"))
            except AssertionError:
                time.sleep(0.05)
                continue
            attempts = self.canvas_put_attempts
            successes = len(self.canvas_puts)
            server_revision = int(self.canvas.get("revision", 0))
            signature = (attempts, successes, server_revision, state["revision"], state["baseRevision"],
                         state["dirty"], state["inFlight"], state["queued"], state["blocked"])
            now = time.monotonic()
            if signature != last_signature:
                last_signature = signature
                quiet_since = now
            synced = (
                state["ready"] and not state["settingsMode"] and not state["canvasSettingsMode"]
                and not state["dirty"]
                and not state["inFlight"] and not state["queued"] and not state["blocked"]
                and state["revision"] == state["baseRevision"] == server_revision
            )
            if synced and quiet_since is not None and now - quiet_since >= 0.65:
                settled_state = state
                break
            if not synced:
                quiet_since = None
            time.sleep(0.05)
        if settled_state is None:
            try:
                final_state = self.frame_evaluate("JSON.stringify((()=>{const base=canvasSyncRetryBase||canvasSyncBase;"
                    "const local=canvasSyncComparableSnapshot(canvasSyncCurrentSnapshot()||{});"
                    "const cleanBase=canvasSyncComparableSnapshot(base||{});"
                    "const keys=[...new Set([...Object.keys(local),...Object.keys(cleanBase)])];"
                    "const changedKeys=keys.filter(key=>JSON.stringify(local[key])!==JSON.stringify(cleanBase[key]));"
                    "const localNodes=new Map((local.nodes||[]).map(node=>[node.id,node]));"
                    "const baseNodes=new Map((cleanBase.nodes||[]).map(node=>[node.id,node]));"
                    "const nodeChanges=[...new Set([...localNodes.keys(),...baseNodes.keys()])].map(id=>{"
                    "const a=localNodes.get(id)||{},b=baseNodes.get(id)||{};"
                    "return {id:String(id||''),keys:[...new Set([...Object.keys(a),...Object.keys(b)])].filter(key=>JSON.stringify(a[key])!==JSON.stringify(b[key]))};"
                    "}).filter(item=>item.keys.length);"
                    "return {ready:window.__plainCanvasReadyForTest===true,revision:Number(canvas?.revision||0),"
                    "baseRevision:Number(base?.revision||0),dirty:base?canvasSyncHasLocalChanges(canvasSyncCurrentSnapshot(),base):true,"
                    "changedKeys,nodeChanges,"
                    "inFlight:canvasSyncInFlight,queued:canvasSyncSaveQueued,blocked:canvasSyncSaveBlocked,"
                    "saveTimer:Boolean(saveTimer)};})())")
            except AssertionError as error:
                final_state = str(error)
            safe_put_meta = [{"path": item.get("path"), "base_revision": item.get("base_revision"),
                              "server_revision": item.get("server_revision"),
                              "migration_version": item.get("migration_version"),
                              "node_schema_version": item.get("node_schema_version"), "nodes": item.get("nodes")}
                             for item in self.canvas_put_attempt_log]
            self.fail(f"普通画布初始化未在限定时间内完成同步：state={final_state}; "
                      f"fixture_revision={self.canvas.get('revision')}; paths={self.write_paths}; "
                      f"attempts={self.canvas_put_attempts}; successes={len(self.canvas_puts)}; "
                      f"attempt_metadata={safe_put_meta}")

        browse_baseline = {
            "attempts": self.canvas_put_attempts,
            "successes": len(self.canvas_puts),
            "revision": int(self.canvas.get("revision", 0)),
        }

        def assert_candidate_browsing_did_not_write():
            # 保留候选操作后的 650ms 观察窗，覆盖 450ms 防抖以及迟到的同步写入。
            # 一旦计数变化立即失败；只有同步状态稳定后才能结束等待。
            check_deadline = time.monotonic() + 6
            check_quiet_since = None
            check_signature = None
            observed_state = None
            settled = False
            while time.monotonic() < check_deadline:
                try:
                    state = json.loads(self.frame_evaluate("JSON.stringify((()=>{"
                        "const base=canvasSyncRetryBase||canvasSyncBase;"
                        "return {revision:Number(canvas?.revision||0),baseRevision:Number(base?.revision||0),"
                        "dirty:base?canvasSyncHasLocalChanges(canvasSyncCurrentSnapshot(),base):true,"
                        "inFlight:canvasSyncInFlight,queued:canvasSyncSaveQueued,blocked:canvasSyncSaveBlocked};})())"))
                except AssertionError:
                    time.sleep(0.05)
                    continue
                attempts = self.canvas_put_attempts
                successes = len(self.canvas_puts)
                server_revision = int(self.canvas.get("revision", 0))
                observed_state = state
                signature = (attempts, successes, server_revision, state["revision"], state["baseRevision"],
                             state["dirty"], state["inFlight"], state["queued"], state["blocked"])
                now = time.monotonic()
                if signature != check_signature:
                    check_signature = signature
                    check_quiet_since = now
                if attempts != browse_baseline["attempts"] or successes != browse_baseline["successes"]:
                    observed_state = state
                    break
                # 选中节点后，composer 可产生尚未提交的本地草稿；本断言只
                # 关心浏览是否发起保存，故要求同步队列空且 revision 对齐，
                # 同时保留 650ms 观察窗捕获延迟防抖 PUT。
                synced = (not state["inFlight"] and not state["queued"] and not state["blocked"]
                          and state["revision"] == state["baseRevision"] == server_revision)
                if synced and check_quiet_since is not None and now - check_quiet_since >= 0.65:
                    observed_state = state
                    settled = True
                    break
                if not synced:
                    check_quiet_since = None
                time.sleep(0.05)
            safe_put_meta = [{"path": item.get("path"), "base_revision": item.get("base_revision"),
                              "server_revision": item.get("server_revision"),
                              "migration_version": item.get("migration_version"),
                              "node_schema_version": item.get("node_schema_version"), "nodes": item.get("nodes")}
                             for item in self.canvas_put_attempt_log]
            if (self.canvas_put_attempts == browse_baseline["attempts"]
                    and len(self.canvas_puts) == browse_baseline["successes"]):
                self.assertTrue(settled, f"候选浏览后同步状态未在限定时间内稳定：baseline={browse_baseline}; "
                                f"paths={self.write_paths}; safe_attempt_metadata={safe_put_meta}; "
                                f"sync_state={observed_state}")
            self.assertEqual(
                {"attempts": self.canvas_put_attempts, "successes": len(self.canvas_puts),
                 "revision": int(self.canvas.get("revision", 0))}, browse_baseline,
                f"只浏览普通画布候选不应触发 PUT；基线={browse_baseline} 当前 attempts={self.canvas_put_attempts} "
                f"successes={len(self.canvas_puts)} revision={self.canvas.get('revision')}; "
                f"paths={self.write_paths}; safe_attempt_metadata={safe_put_meta}; sync_state={observed_state}")

        self.frame_evaluate("document.querySelector('.image-node[data-id=image-run]').click(); true")
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('[data-capability-model-picker] .capability-model-picker-pill')"),
                      lambda: "普通画布图片节点模型选择器未挂载：" + str(json.loads(self.frame_evaluate("JSON.stringify((()=>{const node=canvas?.nodes?.find(item=>item.id==='image-run');return {mode:{hypit:isHypitSettingsMode,article:isArticleSettingsMode,canvas:isCanvasSettingsMode},node:{type:node?.type,runSettings:node?.runSettings,modelSelection:node?.modelSelection},settings:{engine:settings?.engine,apiKind:settings?.apiKind,provider:settings?.provider_id,model:settings?.model},composer:document.getElementById('composer')?.className,dynamic:{hidden:dynamicParams?.hidden,html:dynamicParams?.innerHTML?.slice(0,1600)},modelOptions:modelCapabilityCatalog?.options?.length,providers:modelCapabilityCatalog?.providers?.map(provider=>({id:provider.id,models:provider.models?.length,families:provider.families?.length}))}})())"))))
        self.frame_evaluate("document.querySelector('[data-capability-model-picker] .capability-model-picker-pill').click(); true")
        families = json.loads(self.frame_evaluate("JSON.stringify([...document.querySelectorAll('[data-capability-picker-stage=family] [data-capability-picker-option]')].map(el=>({id:el.dataset.capabilityPickerFamily,label:el.querySelector('.capability-picker-option-label')?.textContent.trim()})))"))
        self.assertIn({"id": "series-image-gpt-image", "label": "GPT Image"}, families,
                      f"中转站和 RunningHub 的图片候选应合并到 GPT Image 家族: {families}")
        self.frame_evaluate("document.querySelector('[data-capability-picker-stage=family] [data-capability-picker-option][data-capability-picker-value=series-image-gpt-image]').click(); true")
        platforms = json.loads(self.frame_evaluate("JSON.stringify([...document.querySelectorAll('[data-capability-picker-stage=platform] [data-capability-picker-option]')].map(el=>({provider:el.dataset.capabilityPickerProvider,region:el.dataset.capabilityPickerRegion,label:el.querySelector('.capability-picker-option-label')?.textContent.trim()})))"))
        platform_debug = json.loads(self.frame_evaluate("JSON.stringify({api:apiProviders.map(p=>({id:p.id,enabled:p.enabled,image_models:p.image_models})),catalog:modelCapabilityCatalog.providers.map(p=>({id:p.id,models:p.models.filter(m=>m.model_id.includes('laohu-image-g-v2.5')).map(m=>({id:m.model_id,ready:m.readiness,selectable:m.selectable})),families:p.families.map(f=>({id:f.family_id,models:f.variants.map(v=>v.model_id)}))})),enabled:[...capabilityEnabledProviderIds('image_generation')],configured:[...configuredCapabilityModelIds('ai-money','image_generation')]})"))
        self.assertTrue(any(item["provider"] == "ai-money" for item in platforms), f"已启用的中转站应可选: platforms={platforms} details={platform_debug}")
        self.assertTrue(any(item["provider"] == "runninghub" and item["region"] == "global" for item in platforms),
                        f"已启用 Global 区域的 RunningHub 应可选: {platforms}")

        self.frame_evaluate("document.querySelector('[data-capability-picker-stage=platform] [data-capability-picker-option][data-capability-picker-value=ai-money]').click(); true")
        laohu_models = json.loads(self.frame_evaluate("JSON.stringify([...document.querySelectorAll('[data-capability-picker-stage=variant] [data-capability-picker-option]')].map(el=>el.dataset.capabilityPickerModel))"))
        self.assertEqual(set(laohu_models), {
            "laohu-image-g-v2.5-flare", "laohu-image-g-v2.5-lowprice", "laohu-image-g-v2.5-sunburst",
        }, f"普通画布图片节点应显示当前启用的三个 Laohu GPT Image 2.5 变体: {laohu_models}")

        self.frame_evaluate("document.querySelector('[data-capability-picker-stage=platform] [data-capability-picker-option][data-capability-picker-provider=runninghub][data-capability-picker-region=global]').click(); true")
        runninghub_models = json.loads(self.frame_evaluate("JSON.stringify([...document.querySelectorAll('[data-capability-picker-stage=variant] [data-capability-picker-option]')].map(el=>el.dataset.capabilityPickerModel))"))
        expected_text_modes = {
            "gpt-image-2.5/flare/text-to-image/economy",
            "gpt-image-2.5/sunburst/text-to-image/economy",
            "gpt-image-2.5/flare/text-to-image/stable-token",
            "gpt-image-2.5/sunburst/text-to-image/stable-token",
        }
        self.assertEqual(set(runninghub_models), expected_text_modes,
                         f"RunningHub Global 的文生图模式应出现在普通图片菜单；无参考图时图生图应按输入契约隐藏: {runninghub_models}")
        assert_candidate_browsing_did_not_write()

        self.frame_evaluate("document.querySelector('.image-node[data-id=image-run-with-reference]').click(); true")
        self.frame_evaluate("document.querySelector('[data-capability-model-picker] .capability-model-picker-pill').click(); true")
        self.frame_evaluate("document.querySelector('[data-capability-picker-stage=family] [data-capability-picker-option][data-capability-picker-value=series-image-gpt-image]').click(); true")
        self.frame_evaluate("document.querySelector('[data-capability-picker-stage=platform] [data-capability-picker-option][data-capability-picker-provider=runninghub][data-capability-picker-region=global]').click(); true")
        referenced_models = json.loads(self.frame_evaluate("JSON.stringify([...document.querySelectorAll('[data-capability-picker-stage=variant] [data-capability-picker-option]')].map(el=>el.dataset.capabilityPickerModel))"))
        expected_reference_modes = {
            "gpt-image-2.5/flare/image-to-image/economy",
            "gpt-image-2.5/sunburst/image-to-image/economy",
            "gpt-image-2.5/flare/image-to-image/stable-token",
            "gpt-image-2.5/sunburst/image-to-image/stable-token",
        }
        self.assertEqual(set(referenced_models), expected_reference_modes,
                         f"提供图片参考时应显示四个 RunningHub Global 图生图模式: {referenced_models}")
        assert_candidate_browsing_did_not_write()

    def test_hypit_unconnected_audio_node_unions_voice_and_audio_slot_candidates(self):
        self.seed_audio_model_catalog()
        self.seed_canvas([{"id": "audio-run", "type": "smart-audio-generator", "x": 100, "y": 100,
                           "runSettings": {"engine": "api", "apiKind": "audio", "audioProvider": "fixture-provider",
                                           "audioModel": "fixture-audio-model"},
                           "promptDraftText": "fixture prompt"}])
        self.open_hypit_canvas()
        self.frame_evaluate("document.querySelector('.image-node[data-id=audio-run]').click(); true")
        self.wait_for(lambda: len(self.model_option_requests) == 2, "未连接用途输出的音频节点应读取 voice 与 audio 两种语义候选")
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('[data-capability-model-picker] [data-capability-picker-stage=family]')"),
                      "音频模型选择器未在两种语义候选返回后恢复")
        state = json.loads(self.frame_evaluate("JSON.stringify({families:[...document.querySelectorAll('[data-capability-picker-stage=family] [data-capability-picker-option]')].map(el=>el.dataset.capabilityPickerFamily),model:settings.audioModel})"))
        self.assertEqual(set(self.model_option_requests), {("hypit", "audio"), ("hypit", "voice")})
        self.assertEqual(set(state["families"]), {"series-audio-audio-family", "series-audio-voice-family"}, "无明确音频用途时应并集，不以名称猜 voice/audio")
        self.assertEqual(state["model"], "fixture-audio-model")

    def test_hypit_audio_node_uses_connected_voice_slot_only(self):
        self.seed_audio_model_catalog()
        self.seed_canvas([
            {"id": "audio-run", "type": "smart-audio-generator", "x": 100, "y": 100,
             "runSettings": {"engine": "api", "apiKind": "audio", "audioProvider": "fixture-provider",
                             "audioModel": "fixture-audio-model"},
             "promptDraftText": "fixture prompt"},
            {"id": "voice-output", "type": "smart-hypit-output", "hypitSlot": "voice", "outputKind": "audio", "x": 540, "y": 100},
        ], [{"id": "voice-edge", "from": "audio-run", "to": "voice-output", "kind": "input"}])
        self.open_hypit_canvas()
        self.frame_evaluate("document.querySelector('.image-node[data-id=audio-run]').click(); true")
        self.wait_for(lambda: self.model_option_requests == [("hypit", "voice")],
                      "连接 voice 输出的音频节点应只读取 voice 语义候选")
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('[data-capability-model-picker] [data-capability-picker-stage=family]')"),
                      "voice 槽候选返回后音频模型选择器没有恢复")
        families = self.frame_evaluate("JSON.stringify([...document.querySelectorAll('[data-capability-picker-stage=family] [data-capability-picker-option]')].map(el=>el.dataset.capabilityPickerFamily))")
        self.assertEqual(json.loads(families), ["series-audio-voice-family"])
        self.assertEqual(self.model_option_requests, [("hypit", "voice")])

    def test_hypit_dynamic_ai_app_does_not_use_static_generation_slot_filter(self):
        self.seed_canvas([{"id": "app", "type": "smart-ai-app", "x": 200, "y": 100,
                           "runSettings": {"engine": "runninghub", "rhAppId": "fixture-app", "rhFields": []}}])
        self.open_hypit_canvas()
        self.wait_for(lambda: self.frame_evaluate("!!document.querySelector('.image-node[data-id=app]')"), "AI 应用节点没有加载")
        self.frame_evaluate("document.querySelector('.image-node[data-id=app]').click(); true")
        self.wait_for(lambda: self.frame_evaluate("document.getElementById('composer')?.classList.contains('open')"),
                      "动态 AI 应用 composer 未打开")
        time.sleep(0.2)
        self.assertEqual(self.model_option_requests, [], "动态 AI 应用候选不能套静态图片/音视频槽位过滤")


if __name__ == "__main__":
    unittest.main()
