"""原生 Hypit Studio 源码与检查器对比度浏览器回归。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
THEME_IDENTITIES = ("studio-violet", "sunlit", "vermilion", "forest", "classic")
CHROME = next((item for item in (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("google-chrome"),
    shutil.which("chromium"),
) if item and Path(item).is_file()), None)
NODE = shutil.which("node")


@unittest.skipUnless(CHROME and NODE, "需要本机 Chrome/Chromium 和 Node.js 执行浏览器回归")
class NativeStudioTextContrastBrowserTests(unittest.TestCase):
    """使用发行版编辑器 DOM 类和生产主题 CSS，不依赖本机 Hypit 服务或用户配置。"""

    @classmethod
    def setUpClass(cls):
        cls.cache = ROOT / "cache" / "studio-tests" / "tmp"
        cls.cache.mkdir(parents=True, exist_ok=True)
        cls.profile = Path(tempfile.mkdtemp(prefix="hypit-native-contrast-", dir=cls.cache))
        cls.fixture = cls.cache / f"hypit-native-contrast-{os.getpid()}.html"
        cls.fixture.write_text(cls.fixture_html(), encoding="utf-8")

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT), **kwargs)

            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.fixture_url = f"http://127.0.0.1:{cls.server.server_port}/{cls.fixture.relative_to(ROOT).as_posix()}"
        cls.chrome = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions",
            "--window-size=1440,1000", "--force-device-scale-factor=1",
            f"--user-data-dir={cls.profile}", "--remote-debugging-port=0", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        active_port = cls.profile / "DevToolsActivePort"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not active_port.exists():
            time.sleep(.1)
        if not active_port.exists():
            cls.tearDownClass()
            raise unittest.SkipTest("Chrome 未能启动隔离调试会话")
        cls.debug_port = active_port.read_text(encoding="utf-8").splitlines()[0]
        target = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and target is None:
            try:
                with urlopen(f"http://127.0.0.1:{cls.debug_port}/json/list", timeout=1) as response:
                    targets = json.loads(response.read().decode("utf-8"))
                target = next((item for item in targets if item.get("type") == "page"), None)
            except Exception:
                time.sleep(.1)
        if not target:
            cls.tearDownClass()
            raise unittest.SkipTest("Chrome 未暴露页面调试目标")
        node_script = r"""const readline=require('readline');
const ws=new WebSocket(process.argv[1]);
const input=readline.createInterface({input:process.stdin});
ws.onopen=()=>{console.log(JSON.stringify({ready:true}));input.on('line',line=>{
 const req=JSON.parse(line);ws.send(JSON.stringify({id:req.id,method:req.method,params:req.params||{}}));
});};
ws.onmessage=event=>{const msg=JSON.parse(event.data);if(msg.id!==undefined)
 console.log(JSON.stringify({id:msg.id,result:msg.result||{},error:msg.error||null}));};"""
        cls.cdp_process = subprocess.Popen([
            NODE, "-e", node_script, target["webSocketDebuggerUrl"],
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1)
        ready = json.loads(cls.cdp_process.stdout.readline() or "{}")
        if not ready.get("ready"):
            cls.tearDownClass()
            raise unittest.SkipTest("无法连接隔离 Chrome 页面")
        cls.request_id = 0
        cls.cdp("Page.enable")
        cls.cdp("Runtime.enable")

    @classmethod
    def fixture_html(cls):
        # DOM 节点与 0.2.7 packages/studio/src/ui/code.ts 生成结构一致；
        # 第一段内联样式保留发行版 style.css 的原始文字色，随后加载生产主题 CSS。
        return """<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<script>(()=>{const params=new URLSearchParams(location.search),root=document.documentElement;
root.dataset.studioTheme=params.get('theme_id')||'studio-violet';
root.dataset.studioAppearance=params.get('appearance')||'light';
root.dataset.studioAppearanceMode=root.dataset.studioAppearance;
root.dataset.laohuThemeId=root.dataset.studioTheme;
root.dataset.laohuTheme=root.dataset.studioAppearance;})();</script>
<style>
:root{--app:#0b0c0e;--panel:#141518;--field:#222429;--line:#26282d;--text:#e7e8eb;--text-2:#a4a7ae;--text-3:#6f737c;--font-mono:monospace;font:500 12px/1.45 sans-serif}
*{box-sizing:border-box}body{margin:0}#app{display:grid;grid-template-columns:1fr 320px;min-height:100vh;background:var(--app);color:var(--text)}
.source-panel,.workspace-panel{min-width:0;background:var(--panel)}.code-scroll{height:500px;overflow:auto;padding:10px 0;background:#141518;font:11px/19px var(--font-mono)}
.code-line{display:flex;min-height:19px}.code-line .line-number{width:42px;flex:none;padding-right:14px;color:#454850;text-align:right}.code-line code{padding-right:12px;color:#bebebe;white-space:pre}
.tok-header,.tok-comment{color:#4e5358;font-style:italic}.tok-punct{color:#686c71}.tok-tag{color:#6896c6}.tok-attr{color:#8f83b7}.tok-string{color:#76aa80}.tok-reference{color:#e18f7a}.tok-role{color:#ca84b3}.tok-marker{color:#c0aa54}.tone-0{--tone:#dfca7d}.tok-marker.tone-0{color:var(--tone)}
.property-group{padding:14px;background:var(--panel);border-bottom:1px solid var(--line)}.property-group h3{margin:0 0 10px;color:#c4c6cc;font-size:11px;font-weight:500}
.property{display:grid;grid-template-columns:80px 1fr;gap:12px;padding:5px 0}.property>span{color:var(--text-3);font-size:11px}.property>strong{color:var(--text-2)}.parameter-label{color:var(--text-3);font-size:11px}
</style><link rel='stylesheet' href='/static/css/studio-theme-palettes.css'>
<link rel='stylesheet' href='/static/css/hypit-native-theme.css'></head><body>
<div id='app'><section class='source-panel'><div class='code-scroll'>
<div class='code-line'><span class='line-number'>1</span><code><span class='tok tok-header'>&lt;?svml</span> <span class='tok tok-attr'>using</span>=<span class='tok tok-string'>"@hypit/markup@1"</span><span class='tok tok-punct'>?&gt;</span></code></div>
<div class='code-line'><span class='line-number'>2</span><code><span class='tok tok-punct'>&lt;</span><span class='tok tok-tag'>svml</span><span class='tok tok-punct'>&gt;</span></code></div>
<div class='code-line'><span class='line-number'>3</span><code>  <span class='tok tok-punct'>&lt;</span><span class='tok tok-tag'>chat:Message</span> <span class='tok tok-attr'>id</span>=<span class='tok tok-string'>"sample"</span> <span class='tok tok-attr'>sender</span>=<span class='tok tok-string'>"Maya"</span><span class='tok tok-punct'>/&gt;</span></code></div>
<div class='code-line'><span class='line-number'>4</span><code>  <span class='tok tok-role'>narration</span> <span class='tok tok-reference'>{scene.main}</span> <span class='tok tok-marker tone-0'>@{claim}</span></code></div>
</div></section><aside class='workspace-panel'>
<section class='property-group'><h3>项目</h3><div class='property'><span>源文件</span><strong>chat.svml</strong></div></section>
<section class='property-group'><h3>画布</h3><div class='property'><span>分辨率</span><strong>540 × 960</strong></div></section>
<section class='property-group'><h3>检查器</h3><div class='parameter-label'>画幅比例</div></section>
</aside></div></body></html>"""

    @classmethod
    def tearDownClass(cls):
        cdp_process = getattr(cls, "cdp_process", None)
        if cdp_process:
            cdp_process.terminate()
            try:
                cdp_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cdp_process.kill()
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
        server_thread = getattr(cls, "server_thread", None)
        if server_thread:
            server_thread.join(timeout=2)
        profile = getattr(cls, "profile", None)
        if profile:
            shutil.rmtree(profile, ignore_errors=True)
        fixture = getattr(cls, "fixture", None)
        if fixture:
            fixture.unlink(missing_ok=True)

    @classmethod
    def cdp(cls, method, params=None):
        cls.request_id += 1
        request_id = cls.request_id
        cls.cdp_process.stdin.write(json.dumps({
            "id": request_id, "method": method, "params": params or {},
        }) + "\n")
        cls.cdp_process.stdin.flush()
        response = json.loads(cls.cdp_process.stdout.readline() or "{}")
        if response.get("id") != request_id or response.get("error"):
            raise AssertionError(f"CDP 调用失败：{response}")
        return response.get("result", {})

    @classmethod
    def evaluate(cls, expression):
        response = cls.cdp("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        })
        if response.get("exceptionDetails"):
            raise AssertionError(f"页面计算失败：{response['exceptionDetails']}")
        return response.get("result", {}).get("value")

    def read_native_dom(self, identity, appearance):
        self.cdp("Page.navigate", {"url": f"{self.fixture_url}?theme_id={identity}&appearance={appearance}"})
        ready = self.evaluate(r"""(async()=>{
          const params=new URLSearchParams(location.search),root=document.documentElement;
          const requiredSheets=['/static/css/studio-theme-palettes.css','/static/css/hypit-native-theme.css'];
          for(let i=0;i<100;i++){
            const sheets=[...document.querySelectorAll('link[rel="stylesheet"]')];
            let loadedSheets=false;
            try{
              loadedSheets=requiredSheets.every(path=>sheets.some(link=>
                new URL(link.href,location.href).pathname===path && link.sheet && link.sheet.cssRules.length>0));
            }catch(_error){loadedSheets=false;}
            const roles=getComputedStyle(root);
            const themeReady=root.dataset.studioTheme===params.get('theme_id') &&
              root.dataset.studioAppearance===params.get('appearance') &&
              ['--studio-bg','--studio-soft','--studio-text','--native-code-text'].every(name=>
                roles.getPropertyValue(name).trim());
            if(document.readyState==='complete' && loadedSheets && themeReady &&
               document.querySelector('.code-line .line-number') &&
               document.querySelector('.property-group h3')) return true;
            await new Promise(resolve=>setTimeout(resolve,50));
          }
          return false;
        })()""")
        self.assertTrue(ready, "原生编辑器/检查器 DOM、目标主题和两份生产样式表必须全部就绪后才能测量")
        return self.evaluate(r"""(()=>{
          const luminance=color=>{
            const values=color.match(/[\d.]+/g)?.map(Number);
            if(!values||values.length<3)return null;
            const c=values.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});
            return .2126*c[0]+.7152*c[1]+.0722*c[2];
          };
          const measure=(element,surface,area)=>{
            const foreground=getComputedStyle(element).color,background=getComputedStyle(surface).backgroundColor;
            const a=luminance(foreground),b=luminance(background);
            return {area,foreground,background,contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),sample:element.textContent.trim().slice(0,32)};
          };
          const scroll=document.querySelector('.code-scroll'),metrics=[];
          metrics.push(measure(document.querySelector('.code-line code'),scroll,'普通代码'));
          metrics.push(measure(document.querySelector('.line-number'),scroll,'行号'));
          const tokens=new Map();
          for(const token of document.querySelectorAll('.code-line .tok')){
            const name=[...token.classList].filter(value=>value==='tok'||value.startsWith('tok-')||value.startsWith('tone-')).join('.');
            if(!tokens.has(name))tokens.set(name,token);
          }
          for(const [name,token] of tokens)metrics.push(measure(token,scroll,`语法 ${name}`));
          for(const heading of document.querySelectorAll('.property-group h3'))metrics.push(measure(heading,heading.parentElement,'检查器标题'));
          for(const label of document.querySelectorAll('.property > span, .parameter-label')){
            const surface=label.closest('.property-group,.parameter-group,.workspace-panel');
            if(surface)metrics.push(measure(label,surface,'检查器字段标签'));
          }
          return {
            identity:document.documentElement.dataset.studioTheme,
            appearance:document.documentElement.dataset.studioAppearance,
            brandRole:getComputedStyle(document.documentElement).getPropertyValue('--brand-500').trim(),
            metrics,tokenTypes:tokens.size
          };
        })()""")

    def test_editor_code_tokens_line_numbers_and_inspector_keep_contrast_for_all_palettes(self):
        failures = []
        brand_roles = set()
        reports = [
            self.read_native_dom(identity, appearance)
            for identity in THEME_IDENTITIES
            for appearance in ("light", "dark")
        ]
        for report in reports:
            self.assertIn(report["identity"], THEME_IDENTITIES, report)
            self.assertIn(report["appearance"], ("light", "dark"), report)
            self.assertGreater(report["tokenTypes"], 0, report)
            brand_roles.add(report.get("brandRole"))
            for metric in report["metrics"]:
                if metric["contrast"] < 4.5:
                    failures.append({"identity": report["identity"], "appearance": report["appearance"], **metric})
        self.assertFalse(failures, "Hypit Studio 原生编辑器/检查器对比度不足：" +
                         json.dumps(failures, ensure_ascii=False))
        self.assertGreater(len(brand_roles - {None, ""}), 1,
                           "五种主题身份必须至少提供不同的原生品牌色角色")


if __name__ == "__main__":
    unittest.main()
