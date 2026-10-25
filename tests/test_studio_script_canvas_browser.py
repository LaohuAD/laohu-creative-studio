"""Isolated real-browser regression for screenplay provenance in the shared canvas."""
from __future__ import annotations

import copy
import base64
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import unittest
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def browser_binary():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"), shutil.which("chromium"),
    ]
    return next((path for path in candidates if path and Path(path).is_file()), None)


CHROME = browser_binary()
NODE = shutil.which("node")
CANVAS_ID = "script-import-browser-fixture"


@unittest.skipUnless(CHROME and NODE, "需要本机 Chrome/Chromium 和 Node.js 执行画布来源链浏览器回归")
class StudioScriptCanvasBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validation = ROOT / ".cache" / "validation"
        cls.tmp = ROOT / ".cache" / "tmp"
        cls.validation.mkdir(parents=True, exist_ok=True)
        cls.tmp.mkdir(parents=True, exist_ok=True)
        os.environ["TMPDIR"] = str(cls.tmp)
        cls.canvas_lock = threading.RLock()
        cls.state = {
            "canvas": {
                "id": CANVAS_ID, "title": "隔离剧本来源样例", "project": "safe-script-canvas",
                "kind": "smart", "revision": 1, "updated_at": 100,
                "node_schema_version": 9999, "nodes": [], "connections": [],
                "viewport": {"x": 0, "y": 0, "scale": 1}, "logs": [], "settings": {},
                "scriptImports": {"schema_version": 1, "requests": {}, "snapshots": {}},
            },
            "writes": [],
            "import_workflow": {},
            "import_posts": 0,
        }

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT), **kwargs)

            def log_message(self, *_args):
                pass

            def _json(self, status, payload):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == f"/api/canvases/{CANVAS_ID}":
                    with cls.canvas_lock:
                        canvas = copy.deepcopy(cls.state["canvas"])
                    self._json(200, {"canvas": canvas})
                    return
                if path == f"/api/canvases/{CANVAS_ID}/meta":
                    with cls.canvas_lock:
                        canvas = cls.state["canvas"]
                        meta = {key: canvas[key] for key in ("id", "revision", "updated_at")}
                    self._json(200, meta)
                    return
                if path == "/api/canvas-runs":
                    self._json(200, {"runs": []})
                    return
                if path == "/api/smart-canvas/personalization":
                    self._json(200, {})
                    return
                if path.startswith("/api/"):
                    # The source-chain fixture never executes a model. Unrelated
                    # catalog reads return harmless empty values on the isolated origin.
                    self._json(200, {})
                    return
                super().do_GET()

            def do_PUT(self):
                if urlsplit(self.path).path != f"/api/canvases/{CANVAS_ID}":
                    self._json(404, {"detail": "unknown isolated fixture route"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length) or b"{}")
                with cls.canvas_lock:
                    current = cls.state["canvas"]
                    if int(request.get("base_revision", 0) or 0) != int(current["revision"]):
                        self._json(409, {"detail": "fixture revision conflict"})
                        return
                    current.update({
                        "title": request.get("title", current["title"]),
                        "icon": request.get("icon", current.get("icon", "layers")),
                        "nodes": copy.deepcopy(request.get("nodes", [])),
                        "connections": copy.deepcopy(request.get("connections", [])),
                        "viewport": copy.deepcopy(request.get("viewport", current["viewport"])),
                        "logs": copy.deepcopy(request.get("logs", [])),
                        "settings": copy.deepcopy(request.get("settings", {})),
                    })
                    if "script_imports" in request:
                        current["scriptImports"] = copy.deepcopy(request["script_imports"])
                    current["revision"] += 1
                    current["updated_at"] += 1
                    cls.state["writes"].append(copy.deepcopy(request))
                    saved = copy.deepcopy(current)
                self._json(200, {"canvas": saved})

            def do_POST(self):
                if urlsplit(self.path).path == "/api/canvas-workflows/import":
                    length = int(self.headers.get("Content-Length", "0"))
                    self.rfile.read(length)
                    with cls.canvas_lock:
                        cls.state["import_posts"] += 1
                        workflow = copy.deepcopy(cls.state["import_workflow"])
                    self._json(200, workflow)
                    return
                self._json(200, {"ok": True, "runs": []})

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.debug_port = probe.getsockname()[1]
        cls.profile = cls.tmp / f"script-canvas-browser-{uuid.uuid4().hex}"
        cls.profile.mkdir(parents=True, exist_ok=False)
        cls.chrome = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--window-size=1440,1000", "--force-device-scale-factor=1",
            f"--user-data-dir={cls.profile}", f"--remote-debugging-port={cls.debug_port}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            [NODE, "-e", node_script, cls.target["webSocketDebuggerUrl"]], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        if not json.loads(cls.cdp_process.stdout.readline() or "{}").get("ready"):
            cls.tearDownClass()
            raise unittest.SkipTest("未能建立隔离浏览器 CDP 会话")
        cls.cdp("Page.enable")
        cls.cdp("Runtime.enable")
        cls.cdp("Page.addScriptToEvaluateOnNewDocument", {"source": """(() => {
          window.__scriptCanvasBrowserErrors=[];
          window.__scriptCanvasReadyForTest=false;
          addEventListener('error', event=>window.__scriptCanvasBrowserErrors.push(String(event.message||'')));
          addEventListener('unhandledrejection', event=>window.__scriptCanvasBrowserErrors.push(String(event.reason?.stack||event.reason||'')));
          addEventListener('canvas-ready',()=>{window.__scriptCanvasReadyForTest=true;},{once:true});
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
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cls.debug_port}/json/list", timeout=2) as response:
                    for target in json.loads(response.read().decode("utf-8")):
                        if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                            return target
            except Exception:
                time.sleep(0.15)
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
            raise AssertionError(f"浏览器用例脚本异常：{result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def wait_for_canvas_ready_sync(self, timeout=20, quiet_ms=250):
        expected_id = json.dumps(CANVAS_ID)
        return self.evaluate(f"""(async()=>{{
          const deadline=Date.now()+{int(timeout * 1000)};
          let previous='',stableSince=0,last=null;
          while(Date.now()<deadline){{
            try{{
              last={{
                ready:window.__scriptCanvasReadyForTest===true,
                documentReady:document.readyState==='complete',
                canvasId:canvas?.id||'',baseId:canvasSyncBase?.id||'',
                revision:Number(canvas?.revision||0),baseRevision:Number(canvasSyncBase?.revision||0),
                inFlight:Boolean(canvasSyncInFlight),queued:Boolean(canvasSyncSaveQueued),
                blocked:Boolean(canvasSyncSaveBlocked),timer:Boolean(saveTimer),
                dirty:typeof canvasSyncHasLocalChanges==='function'
                  ? canvasSyncHasLocalChanges(canvas,canvasSyncBase) : true,
                errors:window.__scriptCanvasBrowserErrors||[]
              }};
            }}catch(error){{last={{error:String(error)}};}}
            const settled=Boolean(last?.ready&&last.documentReady&&last.canvasId==={expected_id}
              &&last.baseId==={expected_id}&&last.revision===last.baseRevision
              &&!last.inFlight&&!last.queued&&!last.blocked&&!last.dirty);
            const signature=settled?JSON.stringify(last):'';
            if(settled&&signature===previous){{
              if(Date.now()-stableSince>={int(quiet_ms)})return {{ok:true,state:last}};
            }}else{{
              stableSince=settled?Date.now():0;
              previous=signature;
            }}
            await new Promise(resolve=>setTimeout(resolve,25));
          }}
          return {{ok:false,state:last}};
        }})()""")

    def open_workflow_transfer_panel(self):
        self.evaluate("document.getElementById('smartWorkflowToggle').click(); true")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.evaluate("document.getElementById('smartWorkflowTransferModal')?.classList.contains('open')"):
                return True
            time.sleep(0.05)
        return False

    def test_source_reference_survives_canvas_save_reload_and_workflow_export(self):
        url = f"http://127.0.0.1:{self.port}/static/smart-canvas.html?id={CANVAS_ID}"
        self.cdp("Page.navigate", {"url": url})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                ready = self.evaluate("typeof canvas !== 'undefined' && canvas?.id === " + json.dumps(CANVAS_ID) + " && !!document.getElementById('world')")
                if ready:
                    break
            except AssertionError:
                pass
            time.sleep(0.1)
        else:
            self.fail(f"smart-canvas 未启动：{self.evaluate('JSON.stringify({url:location.href, errors:window.__scriptCanvasBrowserErrors})')}")

        sync = self.wait_for_canvas_ready_sync()
        self.assertTrue(sync["ok"], f"首次载入未完成 canvas-ready 与保存同步：{sync}")

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                controls_ready = self.evaluate("!!document.getElementById('smartWorkflowToggle')?.onclick && !!document.getElementById('smartWorkflowImportInput')")
                if controls_ready:
                    break
            except AssertionError:
                pass
            time.sleep(0.1)
        else:
            self.fail("工作流导入控件尚未绑定交互")

        created = self.evaluate(r"""(async()=>{
          const sourceRef={module:'script',projectId:'script-source-project',projectRevision:12,
            importId:'script-source-import',sourceNodeId:'episode-1',sourceContentSha256:'a'.repeat(64),sourceStart:0,sourceEnd:8};
          nodes=[
            {id:'fixture-episode',type:'smart-material',title:'第 1 集',x:0,y:0,
              images:[{kind:'text',text:'整集剧本正文'}],sourceRef},
            {id:'fixture-segment',type:'smart-material',title:'第 1 场·分段 1',x:360,y:0,
              images:[{kind:'text',text:'😀中文分段正文'}],
              sourceRef:{...sourceRef,sourceNodeId:'segment-1',sourceContentSha256:'b'.repeat(64),sourceStart:0,sourceEnd:7},
              production:{role:'segment',order:1}}
          ];
          canvas.nodes=nodes;
          canvas.connections=[];
          canvas.scriptImports={schema_version:1,requests:{'request-1':{request_id:'request-1'}},snapshots:{'import-1':{
            import_id:'import-1',source_project_id:'script-source-project',source_revision:12,
            episodes:[{source_node_id:'fixture-episode',segments:[{node_id:'fixture-segment',source_segment_id:'segment-1',content_sha256:'b'.repeat(64)}]}]
          }}};
          canvas.revision=1;canvas.updated_at=100;
          selectedId='';selectedIds=[];
          canvasSyncRememberBase(canvas);
          const saved=await saveCanvas();
          return {saved, revision:canvas.revision, payload:JSON.stringify(canvas.scriptImports)};
        })()""")
        self.assertTrue(created and created["saved"], created)
        with self.canvas_lock:
            self.assertEqual(len(self.state["writes"]), 1)
            expected_imports = json.loads(created["payload"])
            expected_imports.setdefault("advisorySnapshots", {})
            self.assertEqual(self.state["writes"][0]["script_imports"], expected_imports)
            self.assertEqual(self.state["canvas"]["nodes"][1]["sourceRef"]["sourceStart"], 0)

        self.cdp("Page.reload")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                loaded = self.evaluate("typeof canvas !== 'undefined' && canvas?.revision === 2 && canvas?.scriptImports?.snapshots?.['import-1']?.episodes?.length === 1")
                if loaded:
                    break
            except AssertionError:
                pass
            time.sleep(0.1)
        else:
            self.fail("重新载入没有恢复来源引用与脚本导入索引")

        sync = self.wait_for_canvas_ready_sync()
        self.assertTrue(sync["ok"], f"重载后应用启动尚未完成，不能操作工作流面板：{sync}")

        workflow = {
            "nodes": [
                {"id": "incoming-episode", "type": "smart-material", "title": "导入的整集", "x": 0, "y": 0,
                 "images": [{"kind": "text", "text": "完整文本"}],
                 "sourceRef": {"module": "script", "projectId": "another-script", "projectRevision": 4,
                               "importId": "another-import", "sourceNodeId": "episode-9",
                               "sourceContentSha256": "c" * 64, "sourceStart": 10, "sourceEnd": 18}},
                {"id": "incoming-segment", "type": "smart-material", "title": "导入分段", "x": 300, "y": 0,
                 "images": [{"kind": "text", "text": "某一段"}],
                 "sourceRef": {"module": "script", "projectId": "another-script", "projectRevision": 4,
                               "importId": "another-import", "sourceNodeId": "segment-9",
                               "sourceContentSha256": "d" * 64, "sourceStart": 10, "sourceEnd": 13},
                 "production": {"role": "segment", "order": 1}},
            ],
            "connections": [],
            "script_imports": {"schema_version": 1, "snapshots": {"incoming-receipt": {
                "import_id": "incoming-receipt", "source_project_id": "another-script", "source_revision": 4,
                "episodes": [{"source_node_id": "incoming-episode", "segments": [
                    {"node_id": "incoming-segment", "source_segment_id": "segment-9", "content_sha256": "d" * 64}
                ]}],
            }}},
        }
        with self.canvas_lock:
            self.state["import_workflow"] = copy.deepcopy(workflow)
        self.assertTrue(self.open_workflow_transfer_panel(), "通过真实工具栏操作打开工作流面板失败")
        encoded_workflow = json.dumps(json.dumps(workflow, ensure_ascii=False))
        expression = (
            "(()=>{const input=document.getElementById('smartWorkflowImportInput');if(!input)return null;"
            "const file=new File([" + encoded_workflow + "],'script-workflow.json',{type:'application/json'});"
            "const transfer=new DataTransfer();transfer.items.add(file);"
            "Object.defineProperty(input,'files',{configurable:true,value:transfer.files});"
            "input.dispatchEvent(new Event('change',{bubbles:true}));"
            "return transfer.files.length;})()"
        )
        import_trigger = self.evaluate(expression)
        self.assertEqual(import_trigger, 1, import_trigger)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            state = self.evaluate("({count:nodes.length, transfers:Object.keys({...canvas?.scriptImports?.snapshots,...canvas?.scriptImports?.advisorySnapshots}).filter(key=>key.startsWith('scriptimport_transfer_')).length})")
            if state and state["count"] >= 4 and state["transfers"] == 1:
                break
            time.sleep(0.1)
        else:
            debug = self.evaluate("JSON.stringify({errors:window.__scriptCanvasBrowserErrors,modal:document.getElementById('smartWorkflowTransferModal')?.className,input:document.getElementById('smartWorkflowImportInput')?.files?.length,sub:document.getElementById('smartWorkflowTransferSub')?.textContent,meta:document.getElementById('smartWorkflowExportMeta')?.textContent,toast:document.getElementById('toast')?.textContent,ids:nodes.map(n=>n.id),imports:canvas?.scriptImports})")
            with self.canvas_lock:
                debug += f" server_posts={self.state['import_posts']}"
            self.fail(f"工作流文件导入没有建立映射后的来源记录：{state}; {debug}")
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            with self.canvas_lock:
                saved_transfers = [key for key in {**self.state["canvas"]["scriptImports"]["snapshots"],
                                                    **self.state["canvas"]["scriptImports"].get("advisorySnapshots", {})}
                                   if key.startswith("scriptimport_transfer_")]
                import_posts = self.state["import_posts"]
            if saved_transfers and import_posts == 1:
                break
            time.sleep(0.1)
        else:
            self.fail("导入后的节点及来源索引没有通过真实画布保存请求持久化")

        transfer_state = self.evaluate(r"""(()=>{
          const allSnapshots={...canvas.scriptImports.snapshots,...canvas.scriptImports.advisorySnapshots};
          const transferred=Object.entries(allSnapshots).find(([key])=>key.startsWith('scriptimport_transfer_'))?.[1];
          const episode=transferred?.episodes?.[0];
          const byId=new Map(nodes.map(node=>[node.id,node]));
          return {episode,sourceRef:byId.get(episode?.source_node_id)?.sourceRef,
            sourceId:episode?.source_node_id,segmentId:episode?.segments?.[0]?.node_id};
        })()""")
        self.assertTrue(transfer_state and transfer_state["episode"], transfer_state)
        self.assertEqual(transfer_state["sourceRef"]["sourceNodeId"], "episode-9")

        self.assertTrue(self.open_workflow_transfer_panel(), "导入关闭面板后，无法通过真实工具栏重新打开")
        actual_download = self.evaluate(r"""(async()=>{
          window.__scriptWorkflowDownload=null;
          const original=URL.createObjectURL;
          const originalClick=HTMLAnchorElement.prototype.click;
          URL.createObjectURL=blob=>{window.__scriptWorkflowBlob=blob;return original.call(URL,blob);};
          HTMLAnchorElement.prototype.click=function(){window.__scriptWorkflowFilename=this.download;};
          document.querySelector('.workflow-export-actions button.secondary').click();
          for(let i=0;i<80&&!window.__scriptWorkflowBlob;i++)await new Promise(resolve=>setTimeout(resolve,25));
          HTMLAnchorElement.prototype.click=originalClick;
          if(!window.__scriptWorkflowBlob)return null;
          return {filename:window.__scriptWorkflowFilename,text:await window.__scriptWorkflowBlob.text()};
        })()""")
        self.assertTrue(actual_download and actual_download["filename"].endswith(".json"), actual_download)
        downloaded_workflow = json.loads(actual_download["text"])
        self.assertEqual(len(downloaded_workflow["nodes"]), 2)
        self.assertIn(transfer_state["sourceId"], [node["id"] for node in downloaded_workflow["nodes"]])
        self.assertIn(transfer_state["segmentId"], [node["id"] for node in downloaded_workflow["nodes"]])
        self.assertEqual(downloaded_workflow["script_imports"].get("schema_version"), 1)
        self.assertEqual(len(downloaded_workflow["script_imports"]["snapshots"]), 1)
        exported_episode = next(iter(downloaded_workflow["script_imports"]["snapshots"].values()))["episodes"][0]
        self.assertEqual(exported_episode["source_node_id"], transfer_state["sourceId"])
        self.assertEqual(exported_episode["segments"][0]["node_id"], transfer_state["segmentId"])

        self.evaluate("document.getElementById('smartWorkflowTransferModal')?.classList.remove('open')")
        screenshot = self.cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        screenshot_path = self.validation / "script-canvas-source-chain.png"
        screenshot_path.write_bytes(base64.b64decode(screenshot["data"]))
        self.assertGreater(screenshot_path.stat().st_size, 1000)

        with self.canvas_lock:
            errors = self.evaluate("window.__scriptCanvasBrowserErrors")
            self.assertGreaterEqual(len(self.state["writes"]), 2)
            self.assertTrue(self.state["canvas"]["scriptImports"]["snapshots"])
        self.assertEqual(errors, [], errors)


if __name__ == "__main__":
    unittest.main()
