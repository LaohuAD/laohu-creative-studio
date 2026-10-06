"""页面自动缩放与手动缩放偏好的真实浏览器回归。"""
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
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    return next((item for item in candidates if item and Path(item).is_file()), None)


CHROME = chrome_binary()
NODE = shutil.which("node")


@unittest.skipUnless(CHROME and NODE, "需要本机 Chrome/Chromium 和 Node.js 执行缩放浏览器回归")
class ThemeUiScaleBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT), **kwargs)

            def log_message(self, *_args):
                pass

            def _json(self, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/api/providers":
                    self._json({"providers": []})
                    return
                if path == "/api/model-capabilities":
                    self._json({"schema_version": 1, "providers": [], "options": []})
                    return
                if path == "/api/studio/hypit/models/capabilities":
                    self._json({
                        "schema_version": 1, "providers": [], "options": [], "slot_options": {},
                        "supported_capabilities": [], "unsupported_capabilities": [], "defaults": {},
                    })
                    return
                if path == "/api/studio/hypit/models/settings":
                    self._json({"version": 1, "revision": 1, "defaults": {}})
                    return
                if path == "/api/config":
                    self._json({"api_providers": [], "comfy_instances": []})
                    return
                if path == "/api/model-pricing":
                    self._json({"schema_version": 1, "entries": {}, "unit_definitions": {}})
                    return
                if path == "/api/workflows":
                    self._json({"workflows": []})
                    return
                if path == "/api/prompt-libraries":
                    self._json({"library": {"active_library_id": "system", "libraries": [
                        {"id": "system", "name": "系统库", "readonly": True, "items": [], "categories": []}
                    ]}})
                    return
                if path == "/api/asset-library":
                    self._json({"library": {"libraries": []}})
                    return
                if path == "/api/local-assets":
                    self._json({"items": [], "tree": None})
                    return
                if path == "/api/results":
                    self._json({"items": [], "canvases": [], "counts": {}})
                    return
                if path == "/api/smart-canvas/personalization":
                    self._json({})
                    return
                if path == "/api/canvases":
                    self._json({"canvases": []})
                    return
                if path == "/api/projects":
                    self._json({"projects": []})
                    return
                if path == "/api/canvases/trash":
                    self._json({"items": []})
                    return
                super().do_GET()

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.http_port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.debug_port = probe.getsockname()[1]
        cls.profile = ROOT / "cache" / "studio-tests" / "tmp" / f"theme-ui-scale-{int(time.time())}"
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
        node_script = """const readline=require('readline');
const ws=new WebSocket(process.argv[1]);let nextId=0;const pending=new Map();
ws.onopen=()=>process.stdout.write(JSON.stringify({ready:true})+'\\n');
ws.onmessage=event=>{const message=JSON.parse(event.data);if(message.id===undefined)return;
  process.stdout.write(JSON.stringify({id:message.id,result:message.result||{},error:message.error||null})+'\\n');};
readline.createInterface({input:process.stdin}).on('line',line=>{
  const request=JSON.parse(line);ws.send(JSON.stringify({id:request.id||++nextId,method:request.method,params:request.params||{}}));
});"""
        cls.cdp_process = subprocess.Popen(
            [NODE, "-e", node_script, cls.target["webSocketDebuggerUrl"]],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        ready = json.loads(cls.cdp_process.stdout.readline() or "{}")
        if not ready.get("ready"):
            cls.tearDownClass()
            raise unittest.SkipTest("未能建立持久 CDP 会话")
        cls.cdp_request_id = 0
        cls.cdp("Page.enable")
        cls.cdp("Runtime.enable")

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
        request_id = cls.cdp_request_id + 1
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
            raise AssertionError(f"页面脚本异常：{result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def set_viewport(self, width, height=1000):
        self.cdp("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600,
        })

    def open_api_page(self, width, mode="auto"):
        self.set_viewport(width)
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}/static/index.html"})
        prepared = self.evaluate(f"""(async()=>{{
          for(let i=0;i<100;i++){{
            if(location.origin==='http://127.0.0.1:{self.http_port}'){{
              localStorage.clear();
              localStorage.setItem('studio_ui_scale_mode',{json.dumps(mode)});
              localStorage.setItem('studio_theme','light');
              return true;
            }}
            await new Promise(resolve=>setTimeout(resolve,20));
          }}
          return false;
        }})()""")
        self.assertTrue(prepared, "隔离测试源站未就绪")
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}/static/api-settings.html?scale-test=1"})
        self.assertTrue(self.evaluate("""(async()=>{
          for(let i=0;i<160;i++){
            if(document.getElementById('settingsContent')?.dataset.apiStartup==='empty') return true;
            await new Promise(resolve=>setTimeout(resolve,50));
          }
          return false;
        })()"""), "API 设置隔离页面没有完成空配置读取")

    def test_auto_mode_preserves_css_pixel_size_at_desktop_and_phone_widths(self):
        snapshots = []
        for width in (1280, 390):
            self.open_api_page(width)
            snapshots.append(self.evaluate("""(() => ({
              viewport: document.documentElement.clientWidth,
              mode: window.StudioScale.getMode(),
              scale: window.StudioScale.getScale(),
              cssScale: getComputedStyle(document.documentElement).getPropertyValue('--studio-ui-scale').trim(),
              scaledClass: document.documentElement.classList.contains('studio-ui-scaled'),
              bodyTransform: getComputedStyle(document.body).transform,
              titleFontSize: getComputedStyle(document.querySelector('.api-settings-boot-title')).fontSize,
              pageScrollWidth: document.documentElement.scrollWidth,
              bodyScrollWidth: document.body.scrollWidth
            }))()"""))
        for expected_width, result in zip((1280, 390), snapshots):
            with self.subTest(width=expected_width):
                self.assertEqual(result["viewport"], expected_width, result)
                self.assertEqual(result["mode"], "auto", result)
                self.assertAlmostEqual(result["scale"], 1.0, places=3, msg=str(result))
                self.assertAlmostEqual(float(result["cssScale"]), 1.0, places=3, msg=str(result))
                self.assertFalse(result["scaledClass"], result)
                self.assertEqual(result["bodyTransform"], "none", result)
                self.assertEqual(result["titleFontSize"], "14px", result)
                self.assertLessEqual(result["pageScrollWidth"], expected_width + 1, result)
                self.assertLessEqual(result["bodyScrollWidth"], expected_width + 1, result)

    def test_manual_scale_preference_and_canvas_viewport_coordinates_remain_independent(self):
        self.set_viewport(1280)
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}/static/index.html"})
        shell_ready = self.evaluate("(async()=>{for(let i=0;i<120;i++){if(document.querySelector('.app-shell .sidebar')&&window.StudioScale)return true;await new Promise(r=>setTimeout(r,25));}return false;})()")
        if not shell_ready:
            diagnostics = self.evaluate("JSON.stringify({url:location.href,title:document.title,readyState:document.readyState,body:document.body?.innerText?.slice(0,300),shell:!!document.querySelector('.app-shell'),sidebar:!!document.querySelector('.sidebar'),scale:typeof window.StudioScale})")
            self.fail("主工作台缩放宿主未就绪：" + str(diagnostics))
        self.evaluate("window.StudioScale.set('75'); true")
        manual = self.evaluate("""(() => ({
          mode: window.StudioScale.getMode(),
          stored: localStorage.getItem('studio_ui_scale_mode'),
          scale: window.StudioScale.getScale(),
          scaledClass: document.documentElement.classList.contains('studio-ui-scaled'),
          cssScale: getComputedStyle(document.documentElement).getPropertyValue('--studio-ui-scale').trim(),
          sidebarZoom: getComputedStyle(document.querySelector('.app-shell .sidebar')).zoom,
          sidebarRect: document.querySelector('.app-shell .sidebar').getBoundingClientRect().width
        }))()""")
        self.assertEqual(manual["mode"], "75", manual)
        self.assertEqual(manual["stored"], "75", manual)
        self.assertAlmostEqual(manual["scale"], 0.75, places=3, msg=str(manual))
        self.assertTrue(manual["scaledClass"], manual)
        self.assertAlmostEqual(float(manual["cssScale"]), 0.75, places=3, msg=str(manual))
        self.assertAlmostEqual(float(manual["sidebarZoom"]), 0.75, places=3, msg=str(manual))
        self.assertAlmostEqual(manual["sidebarRect"], 60, delta=1, msg=str(manual))

        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}/static/smart-canvas.html?scale-test=1"})
        canvas = self.evaluate("""(async()=>{
          let ready=false;
          for(let i=0;i<160;i++){
            if(location.pathname==='/static/smart-canvas.html' && window.StudioScale && typeof screenToWorld==='function') { ready=true; break; }
            await new Promise(resolve=>setTimeout(resolve,50));
          }
          if(!ready) throw new Error('实际画布坐标函数未就绪');
          viewport={x:40,y:25,scale:1.6};
          const rect=shell.getBoundingClientRect();
          const coordinate=screenToWorld({clientX:rect.left+200,clientY:rect.top+160});
          return {
            mode: window.StudioScale.getMode(),
            stored: localStorage.getItem('studio_ui_scale_mode'),
            scale: window.StudioScale.getScale(),
            cssScale: getComputedStyle(document.documentElement).getPropertyValue('--studio-ui-scale').trim(),
            coordinate,
            canvasScaleOptOut: document.documentElement.dataset.studioScale==='off',
            scaledClass: document.documentElement.classList.contains('studio-ui-scaled')
          };
        })()""")
        self.assertEqual(canvas["mode"], "75", canvas)
        self.assertEqual(canvas["stored"], "75", canvas)
        self.assertAlmostEqual(canvas["scale"], 0.75, places=3, msg=str(canvas))
        self.assertAlmostEqual(float(canvas["cssScale"]), 0.75, places=3, msg=str(canvas))
        self.assertTrue(canvas["canvasScaleOptOut"], canvas)
        self.assertFalse(canvas["scaledClass"], canvas)
        self.assertAlmostEqual(canvas["coordinate"]["x"], 100, places=3, msg=str(canvas))
        self.assertAlmostEqual(canvas["coordinate"]["y"], 84.375, places=3, msg=str(canvas))


if __name__ == "__main__":
    unittest.main()
