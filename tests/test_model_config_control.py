"""P4 公共控件与紧凑样式的行为回归。

对应《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§5、§16 P4、§17 A 系列。

两层验证：
  1. 纯状态机（Node，无 DOM）：状态转换、单次提交、hover 零写入、搜索与失效保留。
  2. 真实浏览器（Chrome DevTools Protocol）：三栏顺序、键盘预览、参数齿轮、浮层视口与事件清理。

浏览器用例在本机没有 Chrome 时自动跳过，不伪装成已通过。
"""
from __future__ import annotations

import json
import base64
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CORE = ROOT / "static" / "js" / "model-config-core.js"
CONTROL = ROOT / "static" / "js" / "model-config-control.js"
STYLE = ROOT / "static" / "css" / "model-config-control.css"
DEMO = ROOT / "tests" / "browser" / "model-config-demo.html"


def run_node(script: str, timeout: int = 60):
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True, timeout=timeout
    )
    return json.loads(result.stdout)


def chrome_binary() -> str | None:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


CHROME = chrome_binary()


class CoreStateMachineTests(unittest.TestCase):
    """纯状态：committed / pathDraft / preview 三态与单次提交（§5.6）。"""

    FIXTURE = r'''
const c = require('./static/js/model-config-core.js');
function opt(family, conn, region, version, edition, operation, extra) {
  return Object.assign({
    option_id: 'opt_' + family + '_' + conn + '_' + region + '_' + version + '_' + edition,
    canonical_family_id: family,
    canonical_family_label: { zh: family, en: family },
    catalog_model_id: family + '-' + version + '-' + edition,
    connection_id: conn,
    region_id: region,
    model_version: version,
    edition_id: edition,
    operation: operation,
    capability_provider_id: conn,
    platform_label: conn + ' ' + region,
    capability_tags: [operation],
    selectable: true,
    runnable: true,
    reasons: []
  }, extra || {});
}
const options = [
  opt('seedance', 'rh', 'global', '2.0', 'standard', 'multimodal_to_video'),
  opt('seedance', 'rh', 'global', '2.5', 'fast', 'text_to_video'),
  opt('seedance', 'rh', 'cn', '2.0', 'standard', 'multimodal_to_video'),
  opt('seedance', 'cli', 'default', '2.0', 'standard', 'text_to_video'),
  opt('kling', 'rh', 'global', '3.0', 'pro', 'text_to_video'),
  opt('blocked-family', 'rh', 'global', '1.0', 'std', 'text_to_video', {
    selectable: false, runnable: false,
    reasons: [{ code: 'ADAPTER_MISSING', message: { zh: '当前适配器未完成', en: 'adapter' } }]
  })
];
function last(state) { return { options: options, state: state }; }
'''

    def test_a01_stage_order_is_model_platform_variant(self):
        script = self.FIXTURE + r'''
let s = c.createState({});
s = c.act(s, 'selectFamily', { familyId: 'seedance' }).state;
const stages = c.projectStages(options, s);
console.log(JSON.stringify({
  families: stages.families.map(f => f.id),
  platforms: stages.platforms.map(p => p.key),
  variantsAfterPlatform: (() => {
    const s2 = c.act(s, 'selectPlatform', { platformKey: 'rh@global' }).state;
    return c.projectStages(options, s2).variants.map(v => v.option.option_id);
  })()
}));
'''
        result = run_node(script)
        self.assertEqual(result["families"], ["seedance", "kling"], "第一栏是模型/系列")
        self.assertEqual(result["platforms"], ["rh@global", "rh@cn", "cli@default"], "第二栏是平台/连接+站点")
        self.assertEqual(len(result["variantsAfterPlatform"]), 2, "第三栏只含该平台实际提供的运行模式")

    def test_a02_family_click_only_updates_draft(self):
        script = self.FIXTURE + r'''
let s = c.createState({ optionId: 'opt_seedance_rh_global_2.0_standard', parameters: { duration: 5 } });
const r = c.act(s, 'selectFamily', { familyId: 'kling' });
console.log(JSON.stringify({
  persist: r.effects.persist,
  committed: r.state.committed.optionId,
  draftFamily: r.state.draft.familyId,
  draftPlatform: r.state.draft.platformKey,
  open: r.state.open
}));
'''
        result = run_node(script)
        self.assertFalse(result["persist"], "点击模型不得写持久化")
        self.assertEqual(result["committed"], "opt_seedance_rh_global_2.0_standard", "已选完整选择不得被改写")
        self.assertEqual(result["draftFamily"], "kling")
        self.assertEqual(result["draftPlatform"], "", "换模型必须清理不适用的草稿平台")

    def test_a04_hover_preview_never_persists(self):
        script = self.FIXTURE + r'''
let s = c.createState({ optionId: 'opt_seedance_rh_global_2.0_standard' });
const r = c.act(s, 'previewOption', { optionId: 'opt_kling_rh_global_3.0_pro' });
const cleared = c.act(r.state, 'clearPreview', {});
console.log(JSON.stringify({
  persist: r.effects.persist,
  notify: r.effects.notifyPreview,
  committedUnchanged: r.state.committed.optionId === s.committed.optionId,
  previewId: r.state.previewOptionId,
  afterClear: cleared.state.previewOptionId
}));
'''
        result = run_node(script)
        self.assertFalse(result["persist"], "A04：hover 必须零写入")
        self.assertTrue(result["notify"], "hover 只触发只读预览事件")
        self.assertTrue(result["committedUnchanged"])
        self.assertEqual(result["previewId"], "opt_kling_rh_global_3.0_pro")
        self.assertEqual(result["afterClear"], "", "移开必须恢复已选值")

    def test_a06_leaf_click_commits_exactly_once(self):
        script = self.FIXTURE + r'''
let s = c.createState({});
const r = c.act(s, 'clickVariant', { option: options[1], parameters: { duration: 5 } });
console.log(JSON.stringify({
  persist: r.effects.persist, close: r.effects.close,
  committed: r.state.committed.optionId,
  open: r.state.open
}));
'''
        result = run_node(script)
        self.assertTrue(result["persist"], "只有第三栏提交才写一次")
        self.assertTrue(result["close"], "提交后收起模型弹层")
        self.assertEqual(result["committed"], "opt_seedance_rh_global_2.5_fast")
        self.assertFalse(result["open"])

    def test_a06_blocked_leaf_is_rejected_without_persisting(self):
        script = self.FIXTURE + r'''
const blocked = options[5];
let s = c.act(c.createState({}), 'open', {}).state;
const r = c.act(s, 'clickVariant', { option: blocked });
console.log(JSON.stringify({
  persist: r.effects.persist,
  rejected: r.effects.rejected && r.effects.rejected.code,
  committed: r.state.committed.optionId,
  open: r.state.open
}));
'''
        result = run_node(script)
        self.assertFalse(result["persist"])
        self.assertEqual(result["rejected"], "ADAPTER_MISSING", "必须给出具体原因")
        self.assertEqual(result["committed"], "")
        self.assertTrue(result["open"], "被拒绝时弹层保持打开")

    def test_a07_cancel_restores_committed_selection(self):
        script = self.FIXTURE + r'''
let s = c.createState({ optionId: 'opt_seedance_rh_global_2.0_standard' });
s = c.act(s, 'open', {}).state;
s = c.act(s, 'selectFamily', { familyId: 'kling' }).state;
s = c.act(s, 'previewOption', { optionId: 'opt_kling_rh_global_3.0_pro' }).state;
const r = c.act(s, 'cancel', {});
console.log(JSON.stringify({
  persist: r.effects.persist,
  committed: r.state.committed.optionId,
  draftFamily: r.state.draft.familyId,
  preview: r.state.previewOptionId,
  open: r.state.open
}));
'''
        result = run_node(script)
        self.assertFalse(result["persist"], "A07：Escape 不得产生保存")
        self.assertEqual(result["committed"], "opt_seedance_rh_global_2.0_standard")
        self.assertEqual(result["draftFamily"], "")
        self.assertEqual(result["preview"], "")
        self.assertFalse(result["open"])

    def test_a08_single_platform_single_variant_still_shows_three_stages(self):
        script = self.FIXTURE + r'''
const single = [options[1]];
let s = c.createState({});
const stages = c.projectStages(single, s);
console.log(JSON.stringify({
  familyCount: stages.families.length,
  platformCount: stages.platforms.length,
  families: stages.families.map(f => f.id)
}));
'''
        result = run_node(script)
        self.assertEqual(result["familyCount"], 1, "单一平台单一模式也不得跳过显式步骤")
        self.assertEqual(result["platformCount"], 1)

    def test_a09_search_matches_real_id_and_alias(self):
        script = self.FIXTURE + r'''
let s = c.createState({});
const byRealId = c.projectStages(options, Object.assign({}, s, { search: 'seedance-2.5-fast' })).families;
const byOperation = c.projectStages(options, Object.assign({}, s, { search: 'multimodal_to_video' })).families;
const noMatch = c.projectStages(options, Object.assign({}, s, { search: 'zzz-none' })).families;
console.log(JSON.stringify({
  byRealId: byRealId.map(f => f.id),
  byOperation: byOperation.map(f => f.id),
  noMatch: noMatch.length
}));
'''
        result = run_node(script)
        self.assertEqual(result["byRealId"], ["seedance"], "必须能按真实 ID 命中")
        self.assertEqual(result["byOperation"], ["seedance"], "必须能按任务模式命中")
        self.assertEqual(result["noMatch"], 0, "无结果时给空状态")

    def test_clear_filters_resets_search_and_all_selected_tags(self):
        script = self.FIXTURE + r'''
let s = Object.assign({}, c.createState({}), {search:'no-match', tags:['text_to_video', 'multimodal_to_video']});
const cleared = c.act(s, 'clearFilters', {}).state;
console.log(JSON.stringify({search:cleared.search, tags:cleared.tags}));
'''
        result = run_node(script)
        self.assertEqual(result, {"search": "", "tags": []})

    def test_a10_unavailable_selected_option_stays_visible(self):
        script = self.FIXTURE + r'''
const hidden = options.map((o, i) => i === 4 ? Object.assign({}, o, { selectable: false, reasons: [{ code: 'ADAPTER_MISSING', message: { zh: '适配器未完成', en: 'x' } }] }) : o);
let s = c.createState({ optionId: 'opt_kling_rh_global_3.0_pro' });
const pool = c.visibleOptions(hidden, s);
console.log(JSON.stringify({
  ids: pool.map(o => o.option_id),
  keepsSelected: pool.some(o => o.option_id === 'opt_kling_rh_global_3.0_pro'),
  hidesOtherBlocked: !pool.some(o => o.option_id === 'opt_blocked-family_rh_global_1.0_std')
}));
'''
        result = run_node(script)
        self.assertTrue(result["keepsSelected"], "A10：已选失效条目必须保留可见")
        self.assertTrue(result["hidesOtherBlocked"], "未选中的不可用项默认隐藏")

    def test_a13_large_catalog_projection_is_fast(self):
        script = r'''
const c = require('./static/js/model-config-core.js');
const options = [];
for (let i = 0; i < 1000; i++) {
  options.push({
    option_id: 'opt_' + ('000000000000000' + i).slice(-16),
    canonical_family_id: 'fam-' + (i % 50),
    canonical_family_label: { zh: '系列' + (i % 50), en: 'fam' + (i % 50) },
    catalog_model_id: 'model-' + i,
    connection_id: 'conn-' + (i % 3),
    region_id: 'global',
    operation: 'text_to_video',
    capability_provider_id: 'p',
    capability_tags: ['文生视频'],
    selectable: true, runnable: true, reasons: []
  });
}
const s = c.createState({});
const started = Date.now();
for (let i = 0; i < 20; i++) c.projectStages(options, Object.assign({}, s, { search: i % 2 ? 'model-1' : '' }));
const elapsed = Date.now() - started;
console.log(JSON.stringify({ elapsed, families: c.projectStages(options, s).families.length }));
'''
        result = run_node(script)
        self.assertEqual(result["families"], 50)
        self.assertLess(result["elapsed"], 2000, "1000 条目录下候选投影不得明显阻塞")


class ArtifactTests(unittest.TestCase):
    """公共文件存在性、语法与样式目标（不需要浏览器）。"""

    def test_files_exist_and_parse(self):
        for path in (CORE, CONTROL, STYLE, DEMO):
            self.assertTrue(path.is_file(), f"缺少 {path.name}")
        for js in (CORE, CONTROL):
            subprocess.run(["node", "--check", str(js)], check=True, capture_output=True, text=True)

    def test_popover_is_portal_level_not_inside_transformed_layer(self):
        source = CONTROL.read_text(encoding="utf-8")
        self.assertIn("model-config-portal", source)
        self.assertIn("position: fixed", STYLE.read_text(encoding="utf-8"))

    def test_density_targets_match_plan(self):
        css = STYLE.read_text(encoding="utf-8")
        self.assertIn("minmax(150px, 26fr)", css, "三栏比例约 26%")
        self.assertIn("minmax(150px, 25fr)", css, "第二栏约 25%")
        self.assertIn("minmax(250px, 49fr)", css, "第三栏约 49%")
        self.assertIn("min-height: 34px", css, "普通列表行 32–38px")
        self.assertIn("min-height: 48px", css, "有徽章的第三栏 48–62px")

    def test_namespaced_styles_avoid_global_selectors(self):
        import re

        css = STYLE.read_text(encoding="utf-8")
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        # 反复移除最内层声明块，只留下选择器与 at-rule 前奏
        previous = None
        while previous != css:
            previous = css
            css = re.sub(r"\{[^{}]*\}", "{}", css)
        selectors = re.findall(r"([^{}]+)\{", css)
        checked = 0
        for chunk in selectors:
            chunk = chunk.strip()
            if not chunk or chunk.startswith("@"):
                continue
            for part in chunk.split(","):
                part = part.strip()
                if not part:
                    continue
                checked += 1
                self.assertTrue(
                    part.startswith(".model-config") or part.startswith(":root"),
                    f"公共样式不得使用宿主级宽泛选择器：{part}",
                )
        self.assertGreater(checked, 10, "选择器提取器必须真的提取到规则")


@unittest.skipUnless(CHROME, "本机没有可用 Chrome，浏览器用例跳过（不伪装成已通过）")
class BrowserBehaviourTests(unittest.TestCase):
    """真实浏览器：DOM 顺序、hover 零写入、键盘预览、参数分工、浮层边界与事件清理。"""

    @classmethod
    def setUpClass(cls):
        cls.port = 9337
        cls.profile_dir = ROOT / "cache" / "p4-chrome-profile"
        shutil.rmtree(cls.profile_dir, ignore_errors=True)
        cls.chrome = subprocess.Popen(
            [
                CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--allow-file-access-from-files", f"--user-data-dir={cls.profile_dir}",
                f"--remote-debugging-port={cls.port}", DEMO.as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.target = cls._wait_for_target()
        if not cls.target:
            cls.tearDownClass()
            raise unittest.SkipTest("Chrome 未能暴露调试目标")

    @classmethod
    def tearDownClass(cls):
        try:
            if getattr(cls, "chrome", None):
                cls.chrome.terminate()
                cls.chrome.wait(timeout=10)
        except Exception:
            pass
        shutil.rmtree(getattr(cls, "profile_dir", ""), ignore_errors=True)

    @classmethod
    def _wait_for_target(cls):
        import urllib.request

        for _ in range(40):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/json/list", timeout=2) as response:
                    targets = json.loads(response.read().decode("utf-8"))
                for target in targets:
                    if (target.get("type") == "page"
                            and target.get("webSocketDebuggerUrl")
                            and target.get("url") == DEMO.as_uri()):
                        return target
            except Exception:
                time.sleep(0.5)
        return None

    def _evaluate(self, expression: str):
        """通过 Node 内置 WebSocket 走 CDP，不依赖额外 Python 包。"""
        script = (
            "(async()=>{const ws=new WebSocket(process.argv[1]);"
            "await new Promise((res,rej)=>{ws.onopen=res;ws.onerror=rej;});"
            "const reply=await new Promise(res=>{ws.onmessage=e=>res(e.data);"
            "ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',params:{expression:process.argv[2],returnByValue:true,awaitPromise:true}}));});"
            "const m=JSON.parse(reply);if(m.result&&m.result.exceptionDetails){console.error(JSON.stringify(m.result.exceptionDetails));process.exit(3);}"
            "const value=m.result&&m.result.result?m.result.result.value:null;console.log(JSON.stringify(value===undefined?null:value));ws.close();})()"
        )
        result = subprocess.run(
            ["node", "-e", script, self.target["webSocketDebuggerUrl"], expression],
            capture_output=True, text=True, timeout=40,
        )
        if result.returncode != 0:
            raise AssertionError(f"CDP 调用失败：{result.stderr[:400]}")
        return json.loads(result.stdout)

    def _wait_for_demo_ready(self, stage: str):
        """等待当前目标文档与 fixture 脚本都就绪，再操作 demo 对象。"""
        expected_url = json.dumps(DEMO.as_uri())
        state = self._evaluate(f"""(async()=>{{
          const expected={expected_url};
          const deadline=Date.now()+12000;
          let state=null;
          do {{
            state={{url:location.href,readyState:document.readyState,
              reset:typeof window.__demo?.reset,destroyAll:typeof window.__demo?.destroyAll,
              host:!!document.getElementById('host')}};
            if(state.url===expected&&state.readyState==='complete'
              &&state.reset==='function'&&state.destroyAll==='function'&&state.host){{
              state.ready=true;return state;
            }}
            await new Promise(resolve=>setTimeout(resolve,50));
          }} while(Date.now()<deadline);
          state.ready=false;return state;
        }})()""")
        self.assertTrue(
            state and state.get("ready"),
            f"{stage}前 demo fixture 未完成初始化（12 秒超时）：{state!r}",
        )
        return state

    def _cdp(self, method: str, params: dict | None = None):
        script = (
            "(async()=>{const ws=new WebSocket(process.argv[1]);"
            "await new Promise((res,rej)=>{ws.onopen=res;ws.onerror=rej;});"
            "const reply=await new Promise(res=>{ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id===1)res(m);};"
            "ws.send(JSON.stringify({id:1,method:process.argv[2],params:JSON.parse(process.argv[3])}));});"
            "if(reply.error){console.error(JSON.stringify(reply.error));process.exit(3);}console.log(JSON.stringify(reply.result||{}));ws.close();})()"
        )
        result = subprocess.run(
            ["node", "-e", script, self.target["webSocketDebuggerUrl"], method, json.dumps(params or {})],
            capture_output=True, text=True, timeout=40,
        )
        if result.returncode != 0:
            raise AssertionError(f"CDP {method} 失败：{result.stderr[:400]}")
        return json.loads(result.stdout)

    def _with_viewport(self, width: int, height: int, method: str, params: dict | None = None, mobile: bool | None = None):
        """以窄屏移动布局视口测试 CSS；手势验收使用明确的鼠标事件。"""
        if mobile is None:
            mobile = width <= 720
        state = (width, height, bool(mobile))
        # 每次 CDP 调用都使用新 WebSocket 会话；会话关闭后设备尺寸会回到窗口默认值，不能跨调用缓存。
        apply_emulation = True
        script = r'''(async()=>{
          const ws=new WebSocket(process.argv[1]);
          await new Promise((res,rej)=>{ws.onopen=res;ws.onerror=rej;});
          let id=0;
          const send=(method,params={})=>new Promise((resolve,reject)=>{
            const current=++id;
            const handler=e=>{const m=JSON.parse(e.data);if(m.id!==current)return;ws.removeEventListener('message',handler);m.error?reject(m.error):resolve(m.result||{});};
            ws.addEventListener('message',handler);
            ws.send(JSON.stringify({id:current,method,params}));
          });
          try {
            await send('Page.bringToFront');
            if(process.argv[7]==='true'){
              await send('Emulation.setDeviceMetricsOverride',{width:Number(process.argv[2]),height:Number(process.argv[3]),deviceScaleFactor:1,mobile:process.argv[6]==='true'});
              await send('Emulation.setTouchEmulationEnabled',{enabled:false});
            }
            const method=process.argv[4];
            const result=await send(method,JSON.parse(process.argv[5]));
            if(method==='Input.synthesizeScrollGesture'||method==='Input.dispatchMouseEvent') await new Promise(resolve=>setTimeout(resolve,120));
            console.log(JSON.stringify(result));
          } catch(error) { console.error(JSON.stringify(error)); process.exitCode=3; }
          finally { ws.close(); }
        })()'''
        result = subprocess.run(
            ["node", "-e", script, self.target["webSocketDebuggerUrl"], str(width), str(height), method, json.dumps(params or {}), str(mobile).lower(), str(apply_emulation).lower()],
            capture_output=True, text=True, timeout=40,
        )
        if result.returncode != 0:
            raise AssertionError(f"CDP viewport action failed: {result.stderr[:400]}")
        self._emulation_state = state
        return json.loads(result.stdout)

    def _evaluate_at_viewport(self, width: int, height: int, expression: str):
        return self._with_viewport(width, height, "Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        }).get("result", {}).get("value")

    def _press_tab_steps_at_viewport(self, width: int, height: int, count: int, measure_expression: str = "true"):
        script = r'''(async()=>{
          const ws=new WebSocket(process.argv[1]);
          await new Promise((res,rej)=>{ws.onopen=res;ws.onerror=rej;});
          let id=0;
          const send=(method,params={})=>new Promise((resolve,reject)=>{
            const current=++id;
            const handler=e=>{const m=JSON.parse(e.data);if(m.id!==current)return;ws.removeEventListener('message',handler);m.error?reject(m.error):resolve(m.result||{});};
            ws.addEventListener('message',handler);
            ws.send(JSON.stringify({id:current,method,params}));
          });
          try {
            await send('Page.bringToFront');
            await send('Emulation.setDeviceMetricsOverride',{width:Number(process.argv[2]),height:Number(process.argv[3]),deviceScaleFactor:1,mobile:false});
            await send('Emulation.setTouchEmulationEnabled',{enabled:false});
            for(let i=0;i<Number(process.argv[4]);i+=1){
              await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9,nativeVirtualKeyCode:9});
              await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9,nativeVirtualKeyCode:9});
            }
            const measured=await send('Runtime.evaluate',{expression:process.argv[5],returnByValue:true,awaitPromise:true});
            if(measured.exceptionDetails)throw new Error(JSON.stringify(measured.exceptionDetails));
            console.log(JSON.stringify({steps:Number(process.argv[4]),value:measured.result?.value}));
          } catch(error) { console.error(JSON.stringify(error)); process.exitCode=3; }
          finally { ws.close(); }
        })()'''
        result = subprocess.run(
            ["node", "-e", script, self.target["webSocketDebuggerUrl"], str(width), str(height), str(count), measure_expression],
            capture_output=True, text=True, timeout=40,
        )
        if result.returncode != 0:
            raise AssertionError(f"CDP Tab 失败：{result.stderr[:400]}")
        self._emulation_state = (width, height, False)
        return json.loads(result.stdout).get("value")

    def _press_key_at_viewport(self, width: int, height: int, key: str):
        code = {"Enter":"Enter", "Escape":"Escape"}.get(key, key)
        virtual_key = {"Enter":13, "Escape":27}.get(key, 0)
        script = r'''(async()=>{
          const ws=new WebSocket(process.argv[1]);
          await new Promise((res,rej)=>{ws.onopen=res;ws.onerror=rej;});
          let id=0;
          const send=(method,params={})=>new Promise((resolve,reject)=>{
            const current=++id;
            const handler=e=>{const m=JSON.parse(e.data);if(m.id!==current)return;ws.removeEventListener('message',handler);m.error?reject(m.error):resolve(m.result||{});};
            ws.addEventListener('message',handler);
            ws.send(JSON.stringify({id:current,method,params}));
          });
          try {
            await send('Page.bringToFront');
            await send('Emulation.setDeviceMetricsOverride',{width:Number(process.argv[2]),height:Number(process.argv[3]),deviceScaleFactor:1,mobile:false});
            await send('Emulation.setTouchEmulationEnabled',{enabled:false});
            const key=process.argv[4], code=process.argv[5], vk=Number(process.argv[6]);
            await send('Input.dispatchKeyEvent',{type:'keyDown',key,code,windowsVirtualKeyCode:vk,nativeVirtualKeyCode:vk});
            await send('Input.dispatchKeyEvent',{type:'keyUp',key,code,windowsVirtualKeyCode:vk,nativeVirtualKeyCode:vk});
            console.log(JSON.stringify({key}));
          } catch(error) { console.error(JSON.stringify(error)); process.exitCode=3; }
          finally { ws.close(); }
        })()'''
        result = subprocess.run(
            ["node", "-e", script, self.target["webSocketDebuggerUrl"], str(width), str(height), key, code, str(virtual_key)],
            capture_output=True, text=True, timeout=40,
        )
        if result.returncode != 0:
            raise AssertionError(f"CDP {key} 失败：{result.stderr[:400]}")
        self._emulation_state = (width, height, False)

    def _click_selector(self, selector: str):
        width, height = self._node_defaults_viewport
        point = self._evaluate_at_viewport(width, height, """
          (() => {
            const element = document.querySelector(%s);
            if (!element) throw new Error('missing click target');
            const rect = element.getBoundingClientRect();
            return {x:rect.left + rect.width/2, y:rect.top + rect.height/2};
          })()
        """ % json.dumps(selector))
        for params in (
            {"type":"mouseMoved", **point},
            {"type":"mousePressed", "button":"left", "clickCount":1, **point},
            {"type":"mouseReleased", "button":"left", "clickCount":1, **point},
        ):
            self._with_viewport(width, height, "Input.dispatchMouseEvent", params)

    def _touch_scroll_selector(self, selector: str, distance: float):
        width, height = self._node_defaults_viewport
        script = r'''(async()=>{
          const ws=new WebSocket(process.argv[1]);
          await new Promise((res,rej)=>{ws.onopen=res;ws.onerror=rej;});
          let id=0;
          const send=(method,params={})=>new Promise((resolve,reject)=>{
            const current=++id;
            const handler=e=>{const m=JSON.parse(e.data);if(m.id!==current)return;ws.removeEventListener('message',handler);m.error?reject(m.error):resolve(m.result||{});};
            ws.addEventListener('message',handler);
            ws.send(JSON.stringify({id:current,method,params}));
          });
          try {
            await send('Page.bringToFront');
            await send('Emulation.setDeviceMetricsOverride',{width:Number(process.argv[2]),height:Number(process.argv[3]),deviceScaleFactor:1,mobile:true});
            await send('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:1,configuration:'mobile'});
            const hit=await send('Runtime.evaluate',{expression:`(()=>{const element=document.querySelector(${JSON.stringify(process.argv[4])});if(!element)throw new Error('missing scroll target');const rect=element.getBoundingClientRect();return {x:rect.left+Math.min(30,rect.width/2),y:rect.top+Math.min(30,rect.height/2)}})()`,returnByValue:true});
            const point=hit.result?.value;
            if(!point)throw new Error('scroll target could not be measured');
            const x=Number(point.x),startY=Number(point.y),distance=Number(process.argv[5]);
            await send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y:startY,id:1}]});
            for(let index=1;index<=10;index+=1){
              const y=startY-distance*index/10;
              await send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y,id:1}]});
              await new Promise(resolve=>setTimeout(resolve,12));
            }
            await send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
            await new Promise(resolve=>setTimeout(resolve,100));
            console.log(JSON.stringify({x,startY,distance}));
          } catch(error) { console.error(JSON.stringify(error)); process.exitCode=3; }
          finally { ws.close(); }
        })()'''
        result = subprocess.run(
            ["node", "-e", script, self.target["webSocketDebuggerUrl"], str(width), str(height),
             selector, str(distance)],
            capture_output=True, text=True, timeout=40,
        )
        if result.returncode != 0:
            raise AssertionError(f"CDP touch scroll failed: {result.stderr[:400]}")
        self._emulation_state = (width, height, True)

    def _synthesize_touch_scroll_selector(self, selector: str, distance: float):
        width, height = self._node_defaults_viewport
        state = (width, height, True)
        apply_emulation = getattr(self, "_emulation_state", None) != state
        script = r'''(async()=>{
          const ws=new WebSocket(process.argv[1]);
          await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
          let id=0;
          const send=(method,params={})=>new Promise((resolve,reject)=>{
            const current=++id;
            const handler=event=>{const message=JSON.parse(event.data);if(message.id!==current)return;
              ws.removeEventListener('message',handler);message.error?reject(message.error):resolve(message.result||{});};
            ws.addEventListener('message',handler);
            ws.send(JSON.stringify({id:current,method,params}));
          });
          const evaluate=async expression=>{
            const result=await send('Runtime.evaluate',{expression,returnByValue:true});
            if(result.exceptionDetails)throw new Error(result.exceptionDetails.text);
            return result.result.value;
          };
          try {
            await send('Page.bringToFront');
            if(process.argv[6]==='true'){
              await send('Emulation.setDeviceMetricsOverride',{width:Number(process.argv[2]),height:Number(process.argv[3]),deviceScaleFactor:1,mobile:true});
              await send('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:1,configuration:'mobile'});
            }
            const selector=JSON.stringify(process.argv[4]);
            const metrics=await evaluate(`(()=>{
              const target=document.querySelector(${selector});
              if(!target)throw new Error('missing scroll target');
              const rect=target.getBoundingClientRect();
              let left=Math.max(0,rect.left),right=Math.min(innerWidth,rect.right);
              let top=Math.max(0,rect.top),bottom=Math.min(innerHeight,rect.bottom);
              for(let parent=target.parentElement;parent&&parent!==document.documentElement;parent=parent.parentElement){
                const style=getComputedStyle(parent),clip=parent.getBoundingClientRect();
                if(['hidden','clip','auto','scroll'].includes(style.overflowX)){left=Math.max(left,clip.left);right=Math.min(right,clip.right);}
                if(['hidden','clip','auto','scroll'].includes(style.overflowY)){top=Math.max(top,clip.top);bottom=Math.min(bottom,clip.bottom);}
              }
              if(right-left<2||bottom-top<2)throw new Error('scroll target has no visible touch area');
              const point={x:Math.min(right-1,left+2),y:(top+bottom)/2};
              const hit=document.elementFromPoint(point.x,point.y);
              return {point,viewport:{width:innerWidth,height:innerHeight,visualWidth:visualViewport.width,visualHeight:visualViewport.height,scale:visualViewport.scale,screenWidth:screen.width,screenHeight:screen.height,dpr:devicePixelRatio},visible:{left,top,right,bottom},
                hit:hit?{tag:hit.tagName,className:String(hit.className||'')}:null,
                before:{scrollTop:target.scrollTop,maxScroll:target.scrollHeight-target.clientHeight}};
            })()`);
            await send('Input.synthesizeScrollGesture',{x:metrics.point.x,y:metrics.point.y,
              yDistance:-Number(process.argv[5]),speed:900,gestureSourceType:'touch',preventFling:true});
            await new Promise(resolve=>setTimeout(resolve,180));
            metrics.after=await evaluate(`(()=>{const target=document.querySelector(${selector});
              return {scrollTop:target.scrollTop,maxScroll:target.scrollHeight-target.clientHeight};})()`);
            console.log(JSON.stringify(metrics));
          } catch(error) { console.error(JSON.stringify({message:error.message}));process.exitCode=3; }
          finally { ws.close(); }
        })()'''
        result = subprocess.run(
            ["node", "-e", script, self.target["webSocketDebuggerUrl"], str(width), str(height), selector, str(distance), str(apply_emulation).lower()],
            capture_output=True, text=True, timeout=40,
        )
        if result.returncode != 0:
            raise AssertionError(f"CDP touch scroll failed: {result.stderr[:400]}")
        self._emulation_state = state
        return json.loads(result.stdout)

    def _wheel_scroll_selector(self, selector: str, distance: float = 0, *, horizontal: float = 0, padding_edge: bool = False):
        """在同一 CDP 会话中设置视口、定位并发送真实鼠标滚轮事件。"""
        width, height = self._node_defaults_viewport
        mobile_layout = width <= 720
        state = (width, height, mobile_layout)
        script = r'''(async()=>{
          const ws=new WebSocket(process.argv[1]);
          await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
          let id=0;
          const send=(method,params={})=>new Promise((resolve,reject)=>{
            const current=++id;
            const handler=event=>{const message=JSON.parse(event.data);if(message.id!==current)return;
              ws.removeEventListener('message',handler);message.error?reject(message.error):resolve(message.result||{});};
            ws.addEventListener('message',handler);
            ws.send(JSON.stringify({id:current,method,params}));
          });
          const evaluate=async expression=>{
            const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
            if(result.exceptionDetails)throw new Error(result.exceptionDetails.text);
            return result.result.value;
          };
          try {
            await send('Page.bringToFront');
            await send('Emulation.setDeviceMetricsOverride',{width:Number(process.argv[2]),height:Number(process.argv[3]),deviceScaleFactor:1,mobile:process.argv[8]==='true'});
            await send('Emulation.setTouchEmulationEnabled',{enabled:false});
            const selector=JSON.stringify(process.argv[4]);
            const paddingEdge=process.argv[7]==='true';
            const point=await evaluate(`(()=>{
              const element=document.querySelector(${selector});
              if(!element)throw new Error('missing scroll target');
              const rect=element.getBoundingClientRect();
              const paddingEdge=${paddingEdge};
              const x=paddingEdge?rect.left+Math.min(19,rect.width/2):rect.left+rect.width/2;
              const y=rect.top+rect.height/2;
              const hit=document.elementFromPoint(x,y);
              return {x,y,viewport:{width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth},
                before:{top:element.scrollTop,left:element.scrollLeft,scrollHeight:element.scrollHeight,clientHeight:element.clientHeight,
                  scrollWidth:element.scrollWidth,clientWidth:element.clientWidth},
                hit:hit?{tag:hit.tagName,className:String(hit.className||'')}:null};
            })()`);
            await send('Input.dispatchMouseEvent',{type:'mouseWheel',x:point.x,y:point.y,deltaX:Number(process.argv[6]),deltaY:Number(process.argv[5])});
            await new Promise(resolve=>setTimeout(resolve,120));
            point.after=await evaluate(`(()=>{const element=document.querySelector(${selector});return {top:element.scrollTop,left:element.scrollLeft};})()`);
            console.log(JSON.stringify(point));
          } catch(error) {console.error(JSON.stringify({message:error.message}));process.exitCode=3;}
          finally {ws.close();}
        })()'''
        result = subprocess.run(
            ["node", "-e", script, self.target["webSocketDebuggerUrl"], str(width), str(height), selector,
             str(distance), str(horizontal), str(padding_edge).lower(), str(mobile_layout).lower()],
            capture_output=True, text=True, timeout=40,
        )
        if result.returncode != 0:
            raise AssertionError(f"CDP wheel scroll failed: {result.stderr[:400]}")
        self._emulation_state = state
        return json.loads(result.stdout)

    def _run_viewport_scenario(self, width: int, height: int, scenario: str, *, mobile: bool = False):
        """在单条 CDP WebSocket 内设置视口并完成操作、读取最终 DOM 状态。"""
        script = r'''(async()=>{
          const ws=new WebSocket(process.argv[1]);
          await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
          let id=0;
          const send=(method,params={})=>new Promise((resolve,reject)=>{
            const current=++id;
            const handler=event=>{const message=JSON.parse(event.data);if(message.id!==current)return;
              ws.removeEventListener('message',handler);message.error?reject(message.error):resolve(message.result||{});};
            ws.addEventListener('message',handler);
            ws.send(JSON.stringify({id:current,method,params}));
          });
          const evaluate=async expression=>{
            const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
            if(result.exceptionDetails)throw new Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text||JSON.stringify(result.exceptionDetails));
            return result.result?.value;
          };
          const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
          const wheel=async(selector,{deltaX=0,deltaY=0,paddingEdge=false}={})=>{
            const selectorLiteral=JSON.stringify(selector);
            const point=await evaluate(`(()=>{
              const element=document.querySelector(${selectorLiteral});
              if(!element)throw new Error('missing scroll target');
              const rect=element.getBoundingClientRect();
              const x=${paddingEdge}?rect.left+Math.min(2,rect.width/2):rect.left+rect.width/2;
              const y=rect.top+rect.height/2;
              const hit=document.elementFromPoint(x,y);
              return {x,y,viewport:{width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth},
                before:{top:element.scrollTop,left:element.scrollLeft,scrollHeight:element.scrollHeight,clientHeight:element.clientHeight,
                  scrollWidth:element.scrollWidth,clientWidth:element.clientWidth},
                hit:hit?{tag:hit.tagName,className:String(hit.className||'')}:null};
            })()`);
            await send('Input.dispatchMouseEvent',{type:'mouseWheel',x:point.x,y:point.y,deltaX:Number(deltaX),deltaY:Number(deltaY)});
            await delay(120);
            point.after=await evaluate(`(()=>{const element=document.querySelector(${selectorLiteral});
              return {top:element.scrollTop,left:element.scrollLeft};})()`);
            return point;
          };
          const click=async(selector)=>{
            const selectorLiteral=JSON.stringify(selector);
            const point=await evaluate(`(()=>{
              const element=document.querySelector(${selectorLiteral});
              if(!element)throw new Error('missing click target');
              const rect=element.getBoundingClientRect();
              const x=rect.left+rect.width/2,y=rect.top+rect.height/2;
              if(x<0||x>innerWidth||y<0||y>innerHeight)throw new Error('click target is outside viewport: '+JSON.stringify({selector:${selectorLiteral},rect:{left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom},viewport:{width:innerWidth,height:innerHeight}}));
              const hit=document.elementFromPoint(x,y);
              if(!hit||!(element===hit||element.contains(hit)))throw new Error('click target is clipped or covered');
              return {x,y,rect:{left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom},
                hit:{tag:hit.tagName,className:String(hit.className||'')}};
            })()`);
            await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:point.x,y:point.y});
            await send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,x:point.x,y:point.y});
            await send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,x:point.x,y:point.y});
            await delay(80);
            return point;
          };
          const key=async(name,vk)=>{
            const code=name==='Tab'?'Tab':name;
            await send('Input.dispatchKeyEvent',{type:'keyDown',key:name,code,windowsVirtualKeyCode:vk,nativeVirtualKeyCode:vk});
            await send('Input.dispatchKeyEvent',{type:'keyUp',key:name,code,windowsVirtualKeyCode:vk,nativeVirtualKeyCode:vk});
          };
          try {
            await send('Page.bringToFront');
            await send('Emulation.setDeviceMetricsOverride',{width:Number(process.argv[2]),height:Number(process.argv[3]),deviceScaleFactor:1,mobile:process.argv[4]==='true'});
            await send('Emulation.setTouchEmulationEnabled',{enabled:false});
            await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
            const run=new Function('send','evaluate','wheel','click','key','delay',
              'return (async()=>{' + process.argv[5] + '\n})()');
            const result=await run(send,evaluate,wheel,click,key,delay);
            console.log(JSON.stringify(result));
          } catch(error) {console.error(JSON.stringify({message:error.message}));process.exitCode=3;}
          finally {ws.close();}
        })()'''
        result = subprocess.run(
            ["node", "-e", script, self.target["webSocketDebuggerUrl"], str(width), str(height),
             str(mobile).lower(), scenario],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise AssertionError(f"CDP viewport scenario failed: {result.stderr[:500]}")
        self._emulation_state = (width, height, mobile)
        return json.loads(result.stdout)

    def _capture_screenshot(self, name: str):
        width, height = self._node_defaults_viewport
        result = self._with_viewport(width, height, "Page.captureScreenshot", {"format":"png", "fromSurface":True})
        path = ROOT / "cache" / "studio-tests" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(result["data"]))
        return path

    def _reload_demo_at_viewport(self, width: int, height: int):
        """先设置 CSS 视口再重载测试页，让初始 viewport meta 从首帧生效。"""
        mobile_layout = width <= 720
        script = r'''(async()=>{
          const ws=new WebSocket(process.argv[1]);
          await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
          let id=0;
          const send=(method,params={})=>new Promise((resolve,reject)=>{
            const current=++id;
            const handler=event=>{const message=JSON.parse(event.data);if(message.id!==current)return;
              ws.removeEventListener('message',handler);message.error?reject(message.error):resolve(message.result||{});};
            ws.addEventListener('message',handler);
            ws.send(JSON.stringify({id:current,method,params}));
          });
          try {
            await send('Page.enable');
            await send('Emulation.setDeviceMetricsOverride',{width:Number(process.argv[2]),height:Number(process.argv[3]),deviceScaleFactor:1,mobile:process.argv[4]==='true'});
            await send('Emulation.setTouchEmulationEnabled',{enabled:false});
            const loaded=new Promise(resolve=>{
              const handler=event=>{const message=JSON.parse(event.data);if(message.method==='Page.loadEventFired'){
                ws.removeEventListener('message',handler);resolve();}};
              ws.addEventListener('message',handler);
            });
            await send('Page.reload',{ignoreCache:true});
            await Promise.race([loaded,new Promise((_,reject)=>setTimeout(()=>reject(new Error('fixture reload timed out')),10000))]);
            const expression=`(async()=>{
              const expected=${JSON.stringify(process.argv[5])};
              const deadline=Date.now()+12000;let state=null;
              do {
                state={url:location.href,readyState:document.readyState,
                  width:innerWidth,height:innerHeight,
                  meta:document.querySelector('meta[name="viewport"]')?.content,
                  reset:typeof window.__demo?.reset,destroyAll:typeof window.__demo?.destroyAll,
                  host:!!document.getElementById('host')};
                if(state.url===expected&&state.readyState==='complete'
                  &&state.reset==='function'&&state.destroyAll==='function'&&state.host){state.ready=true;return state;}
                await new Promise(resolve=>setTimeout(resolve,50));
              } while(Date.now()<deadline);
              state.ready=false;return state;
            })()`;
            const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
            const readiness=result.result?.value||null;
            if(!readiness?.ready)throw new Error('fixture reload did not initialize: '+JSON.stringify(readiness));
            console.log(JSON.stringify(readiness));
          } catch(error) {console.error(JSON.stringify({message:error.message}));process.exitCode=3;}
          finally {ws.close();}
        })()'''
        result = subprocess.run(
            ["node", "-e", script, self.target["webSocketDebuggerUrl"], str(width), str(height),
             str(mobile_layout).lower(), DEMO.as_uri()],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            raise AssertionError(f"测试夹具视口重载失败：{result.stderr[:400]}")
        viewport = json.loads(result.stdout)
        self._emulation_state = (width, height, mobile_layout)
        self.assertEqual(viewport["width"], width, f"fixture 重载后 CSS 视口应为 {width}px: {viewport}")
        self.assertEqual(viewport["meta"], "width=device-width, initial-scale=1.0", viewport)
        return viewport

    def _prepare_node_defaults_dialog(self, width: int, height: int):
        self._node_defaults_viewport = (width, height)
        self._reload_demo_at_viewport(width, height)
        css_path = ROOT / "static" / "css" / "smart-canvas.css"
        canvas_css = css_path.read_text(encoding="utf-8")
        start = canvas_css.index("/* Agent 接入复用工具栏")
        end = canvas_css.index("/* 顶部工具保持", start)
        canvas_css = ":root{--line:#ddd;--panel:#fff;--text:#342e40;--muted:#706b7a;--soft:#f3edff;--card:#fff;--shadow:rgba(0,0,0,.16);--strong:#7047eb;}\n" + canvas_css[start:end]
        prepared = self._evaluate_at_viewport(width, height, """
          (async () => {
            const previous = document.getElementById('canvasAgentDialog');
            if (previous) previous.remove();
            const viewport = document.querySelector('meta[name="viewport"]');
            if (!viewport || viewport.content !== 'width=device-width, initial-scale=1.0') {
              throw new Error('test page must load its mobile viewport meta before JavaScript');
            }
            let style = document.querySelector('style[data-node-defaults-css]');
            if (!style) { style = document.createElement('style'); style.dataset.nodeDefaultsCss = 'true'; document.head.appendChild(style); }
            style.textContent = __CANVAS_CSS__;
            const dialog = document.createElement('dialog');
            dialog.id = 'canvasAgentDialog';
            dialog.className = 'canvas-agent-dialog';
            dialog.innerHTML = `
              <div class="canvas-agent-head"><h2 id="canvasAgentHeading">节点默认设置</h2><button id="canvasAgentClose" type="button" aria-label="关闭">×</button></div>
              <section id="canvasAgentDefaults">
                <div class="agent-default-heading"><h3>新建节点默认值</h3><span>仅当前画布</span></div>
                <p>先设好每类节点。Agent 创建此类节点时会沿用这里选定的模型和参数。</p>
                <div class="agent-default-tabs" role="tablist">
                  <button type="button" role="tab" data-agent-kind="text">文本 / LLM</button>
                  <button type="button" role="tab" data-agent-kind="image">图片</button>
                  <button type="button" role="tab" data-agent-kind="video">视频</button>
                  <button type="button" role="tab" data-agent-kind="audio">音频</button>
                  <button type="button" role="tab" data-agent-kind="music">音乐</button>
                  <button type="button" role="tab" data-agent-kind="app">AI 应用</button>
                  <button type="button" role="tab" data-agent-kind="comfy">ComfyUI</button>
                </div>
                <div class="agent-default-model-host" data-agent-model-host id="nodeDefaultsHost"></div>
                <div class="agent-default-actions"><button type="button" data-agent-save>保存默认设置</button></div>
              </section>
              <p id="canvasAgentFeedback" role="status" aria-live="polite">设置尚未保存</p>`;
            window.__nodeDefaultsSaveClicks = 0;
            dialog.querySelector('[data-agent-save]').addEventListener('click', () => { window.__nodeDefaultsSaveClicks += 1; });
            document.body.appendChild(dialog);
            dialog.showModal();
            window.__demo.commits.length = 0;
            const catalog = window.__demo.buildCatalog(180);
            const baseMode = catalog.options[0];
            for (let index = 0; index < 36; index += 1) {
              catalog.options.push({
                ...baseMode,
                option_id: 'node-default-leaf-' + String(index).padStart(2, '0'),
                catalog_model_id: 'seedance-node-default-' + index,
                request_model_id: 'node-default-request-' + index,
                endpoint_id: 'node-default-endpoint-' + index,
                model_version: '9.' + index,
                edition_id: 'fixture',
                display_label: {zh:'测试模式 ' + String(index).padStart(2, '0'), en:'Fixture mode ' + String(index).padStart(2, '0')}
              });
            }
            window.__nodeDefaultsCatalog = catalog;
            window.__nodeDefaultsInstance = window.__demo.mount('nodeDefaultsHost', {
              catalog,
              selection: {optionId:'', parameters:{duration:5, resolution:'720p'}},
              presentation: 'module',
              onCommit: payload => { window.__demo.commits.push(payload); return Promise.resolve(); }
            });
            const rect=dialog.getBoundingClientRect();
            return {width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,
              meta:document.querySelector('meta[name="viewport"]')?.content,
              dialog:{left:rect.left,right:rect.right,width:rect.width,cssWidth:getComputedStyle(dialog).width,
                minWidth:getComputedStyle(dialog).minWidth,boxSizing:getComputedStyle(dialog).boxSizing}};
          })()
        """.replace("__CANVAS_CSS__", json.dumps(canvas_css, ensure_ascii=False)))
        self.assertEqual(prepared["width"], width,
                         f"挂入默认设置对话框后仍须保持声明的 CSS 视口：{prepared}")
        return prepared

    def _open_node_defaults_picker(self):
        width, height = self._node_defaults_viewport
        self._evaluate_at_viewport(width, height, "document.querySelector('#nodeDefaultsHost .model-config-trigger').click()")
        return self._evaluate_at_viewport(width, height, """
          (() => {
            const dialog = document.getElementById('canvasAgentDialog');
            const popover = dialog.querySelector('.model-config-popover');
            const rect = popover.getBoundingClientRect();
            const dialogRect = dialog.getBoundingClientRect();
            const stage = popover.querySelector('.model-config-stages');
            const list = popover.querySelector('.model-config-stage-family .model-config-stage-options');
            const variants = popover.querySelector('.model-config-stage-variant .model-config-stage-options');
            return {
              viewport: {width: innerWidth, height: innerHeight},
              dialog: {top: dialogRect.top, bottom: dialogRect.bottom, left: dialogRect.left, right: dialogRect.right, width: dialogRect.width},
              popover: {top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right,
                width: rect.width, height: rect.height, scrollHeight: popover.scrollHeight,
                maxHeight: getComputedStyle(popover).maxHeight, position: getComputedStyle(popover).position},
              stages: {height: stage.getBoundingClientRect().height, scrollHeight: stage.scrollHeight,
                overflowY: getComputedStyle(stage).overflowY},
              familyList: {height:list.clientHeight, scrollHeight:list.scrollHeight,
                overflowY:getComputedStyle(list).overflowY},
              variantList: {height:variants.clientHeight, scrollHeight:variants.scrollHeight,
                overflowY:getComputedStyle(variants).overflowY}
            };
          })()
        """)

    def setUp(self):
        self._wait_for_demo_ready("每个浏览器用例初始化")
        self._evaluate("window.__demo.reset(); window.__demo.destroyAll(); window.StudioI18n = null; document.getElementById('canvasAgentDialog')?.remove(); document.getElementById('host').replaceChildren();")
        self._evaluate(
            "window.__demo.mount('host', {catalog: window.__demo.buildCatalog(0),"
            " selection: {optionId: 'opt_0000000000000001', parameters: {duration: 5, resolution: '720p'}}});"
        )

    def test_numeric_and_text_parameters_are_editable_without_truncating_the_range(self):
        result = self._evaluate("""
            (() => {
              document.querySelector('.model-config-gear').click();
              const panel = document.querySelector('.model-config-parameters');
              const seed = panel.querySelector('[data-param-key="seed"] input[type="number"]');
              seed.value = '123456';
              seed.dispatchEvent(new Event('change', {bubbles:true}));
              const prompt = panel.querySelector('[data-param-key="negative_prompt"] input');
              prompt.value = 'fixture negative prompt';
              prompt.dispatchEvent(new Event('change', {bubbles:true}));
              return {
                seed: panel.querySelector('[data-param-key="seed"] input[type="number"]').value,
                max: panel.querySelector('[data-param-key="seed"] input[type="range"]').max,
                prompt: panel.querySelector('[data-param-key="negative_prompt"] input').value,
                chips: panel.querySelector('[data-param-key="seed"]').querySelectorAll('button').length
              };
            })()
        """)
        self.assertEqual(result, {'seed':'123456', 'max':'999999', 'prompt':'fixture negative prompt', 'chips':0})

    def test_three_columns_render_in_order(self):
        # 浮层挂在 portal 根，不随宿主 transform 缩放（§13.3）
        order = self._evaluate(
            "[...document.querySelector('#model-config-portal .model-config-stages').children]"
            ".map(n => n.getAttribute('data-stage'))"
        )
        self.assertEqual(order, ["family", "platform", "variant"], "A01：顺序必须是模型→平台→运行模式")
        self.assertEqual(self._evaluate("document.querySelectorAll('#model-config-portal .model-config-popover').length"), 1,
                         "同一宿主只应有一个选择器实例")
        self.assertEqual(self._evaluate("document.querySelectorAll('#model-config-portal .model-config-stage').length"), 3,
                         "横向递进三栏，不变成纵向大卡片")

    def test_hover_previews_without_any_commit(self):
        self._evaluate("document.querySelector('.model-config-trigger').click();")
        self._evaluate("""
            const leaf = document.querySelector('.model-config-stage-variant .model-config-leaf');
            leaf.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
        """)
        result = self._evaluate("""
            (() => {
              const idRow = document.querySelector('.model-config-id-row');
              return {
                previewing: idRow.classList.contains('is-previewing'),
                label: document.querySelector('.model-config-id-label').textContent,
                commits: window.__demo.commits.length,
                previews: window.__demo.previews.length,
                previewValue: document.querySelector('.model-config-id-value').textContent
              };
            })()
        """)
        self.assertTrue(result["previewing"], "hover 必须高亮真实标识行")
        self.assertEqual(result["label"], "预览接口")
        self.assertEqual(result["commits"], 0, "A04：hover 持久化请求数必须为 0")
        self.assertGreater(result["previews"], 0, "hover 只触发只读预览事件")
        self.assertTrue(result["previewValue"])

    def test_leaf_click_commits_once_and_closes(self):
        self._evaluate("document.querySelector('.model-config-trigger').click();")
        self._evaluate("document.querySelector('.model-config-stage-variant .model-config-leaf').click();")
        result = self._evaluate("""
            (() => ({commits: window.__demo.commits.length,
                     hidden: document.querySelector('.model-config-popover').hidden,
                     persisted: window.__demo.commits[0] && window.__demo.commits[0].selection.optionId}))()
        """)
        self.assertEqual(result["commits"], 1, "A06：合法叶子一次提交")
        self.assertTrue(result["hidden"], "提交后收起模型弹层")
        self.assertTrue(result["persisted"])

    def test_family_platform_and_tag_clicks_stay_open_until_leaf_is_chosen(self):
        self._evaluate("document.querySelector('.model-config-trigger').click();")
        result = self._evaluate("""
            (() => {
              const popover = document.querySelector('.model-config-popover');
              const commits = () => window.__demo.commits.length;
              const family = [...popover.querySelectorAll('.model-config-stage-family .model-config-option')]
                .find(row => row.textContent.includes('Kling'));
              const familyId = family.getAttribute('data-family-id');
              family.focus();
              family.click();
              const afterFamily = {open: !popover.hidden, commits: commits(), focusRestored: document.activeElement?.getAttribute('data-family-id') === familyId};
              const platform = popover.querySelector('.model-config-stage-platform .model-config-option');
              platform.focus();
              platform.click();
              const afterPlatform = {open: !popover.hidden, commits: commits(), focusRestored: document.activeElement?.getAttribute('data-platform-key') === platform.getAttribute('data-platform-key')};
              const tag = [...popover.querySelectorAll('.model-config-tag')]
                .find(chip => chip.textContent.includes('首尾帧'));
              tag.focus();
              tag.click();
              const selectedChip = popover.querySelector('.model-config-tag.is-on');
              const selected = !!selectedChip;
              const selectedFocusRestored = selectedChip && document.activeElement === selectedChip;
              if (selectedChip) selectedChip.click();
              const toggledOff = !popover.querySelector('.model-config-tag.is-on');
              const offChip = [...popover.querySelectorAll('.model-config-tag')]
                .find(chip => chip.textContent.includes('首尾帧'));
              const offFocusRestored = offChip && document.activeElement === offChip;
              offChip.click();
              if (!popover.hidden) document.querySelector('.model-config-trigger').click();
              const closedAfterFilter = popover.hidden;
              document.querySelector('.model-config-trigger').click();
              const reopenedTagRetained = !popover.hidden && !!popover.querySelector('.model-config-tag.is-on');
              const afterTag = {
                open: !popover.hidden,
                commits: commits(),
                selected,
                selectedFocusRestored,
                toggledOff,
                offFocusRestored,
                selectedReplacement: !!popover.querySelector('.model-config-tag.is-on'),
                closedAfterFilter,
                reopenedTagRetained
              };
              return {afterFamily, afterPlatform, afterTag};
            })()
        """)
        self.assertEqual(result["afterFamily"], {"open": True, "commits": 0, "focusRestored": True}, result)
        self.assertEqual(result["afterPlatform"], {"open": True, "commits": 0, "focusRestored": True}, result)
        self.assertEqual(result["afterTag"], {"open": True, "commits": 0, "selected": True, "selectedFocusRestored": True, "toggledOff": True, "offFocusRestored": True, "selectedReplacement": True, "closedAfterFilter": True, "reopenedTagRetained": True}, result)

    def test_unchanged_catalog_refresh_does_not_interrupt_open_picker_draft(self):
        result = self._evaluate("""
          (() => {
            const catalog = window.__demo.buildCatalog(180);
            catalog.options.forEach(option => {
              if (String(option.canonical_family_id || '').startsWith('fixture-scale-family-')) {
                option.capability_tags = ['首尾帧'];
                option.capability_tags_en = ['First and last frame'];
              }
            });
            const instance = window.__demo.mount('host', {catalog});
            const root = instance.element;
            root.querySelector('.model-config-trigger').click();
            const popover = instance.popover;
            const familyList = popover.querySelector('.model-config-stage-family .model-config-stage-options');
            familyList.scrollTop = 180;
            const family = popover.querySelector('[data-family-id=\"fixture-kling\"]');
            family.click();
            const platform = popover.querySelector('.model-config-stage-platform [data-platform-key]');
            const platformKey = platform?.getAttribute('data-platform-key') || '';
            platform?.click();
            const tag = [...popover.querySelectorAll('.model-config-tag')]
              .find(chip => chip.getAttribute('data-model-config-tag') === '首尾帧');
            tag?.click();
            const search = popover.querySelector('[data-model-config-search]');
            search.value = 'fixture';
            search.dispatchEvent(new Event('input', {bubbles:true}));
            const activeTag = [...popover.querySelectorAll('.model-config-tag')]
              .find(chip => chip.getAttribute('data-model-config-tag') === '首尾帧');
            activeTag?.focus();
            const tagNode = activeTag;
            const familyNode = popover.querySelector('[data-family-id=\"fixture-kling\"]');
            const before = {
              open: !instance.popover.hidden,
              search: instance.getState().search,
              tags: instance.getState().tags.slice(),
              familyId: instance.getState().draft.familyId,
              platformKey: instance.getState().draft.platformKey,
              familyScrollTop: familyList.scrollTop,
              commits: window.__demo.commits.length
            };
            const mutations = [];
            const observer = new MutationObserver(records => mutations.push(...records));
            observer.observe(popover.querySelector('.model-config-stage-family .model-config-stage-options'), {childList:true});
            const unchangedCatalog = JSON.parse(JSON.stringify(catalog));
            instance.updateCatalog(unchangedCatalog);
            const unchanged = {
              familyNodePreserved: familyNode === popover.querySelector('[data-family-id=\"fixture-kling\"]'),
              tagNodePreserved: tagNode === popover.querySelector('[data-model-config-tag=\"首尾帧\"]'),
              focusPreserved: document.activeElement === tagNode,
              state: instance.getState(),
              familyScrollTop: familyList.scrollTop,
              open: !instance.popover.hidden
            };
            const mutationCount = observer.takeRecords().length;
            const refreshedCatalog = JSON.parse(JSON.stringify(unchangedCatalog));
            refreshedCatalog.options.forEach(option => {
              if (option.canonical_family_id === 'fixture-kling') {
                option.canonical_family_label = {zh:'Kling 更新版', en:'Kling refreshed'};
              }
            });
            instance.updateCatalog(refreshedCatalog);
            const changedRecords = observer.takeRecords();
            const changed = {
              open: !instance.popover.hidden,
              search: instance.getState().search,
              tags: instance.getState().tags.slice(),
              draft: Object.assign({}, instance.getState().draft),
              familyScrollTop: familyList.scrollTop,
              familyLabel: popover.querySelector('[data-family-id="fixture-kling"] .model-config-option-label')?.textContent || '',
              familyReplacementBatches: changedRecords.filter(record => record.removedNodes.length > 0).length
            };
            observer.disconnect();
            return {before, unchanged, familyMutationCount:mutationCount, changed, commits:window.__demo.commits.length};
          })()
        """)
        self.assertTrue(result["before"]["open"], result)
        self.assertEqual(result["before"]["search"], "fixture", result)
        self.assertEqual(result["before"]["familyId"], "fixture-kling", result)
        self.assertEqual(result["before"]["platformKey"], result["unchanged"]["state"]["draft"]["platformKey"], result)
        self.assertEqual(result["before"]["tags"], result["unchanged"]["state"]["tags"], result)
        self.assertTrue(result["unchanged"]["open"], result)
        self.assertTrue(result["unchanged"]["familyNodePreserved"], result)
        self.assertTrue(result["unchanged"]["tagNodePreserved"], result)
        self.assertTrue(result["unchanged"]["focusPreserved"], result)
        self.assertEqual(result["before"]["familyScrollTop"], result["unchanged"]["familyScrollTop"], result)
        self.assertEqual(result["familyMutationCount"], 0, result)
        self.assertTrue(result["changed"]["open"], result)
        self.assertEqual(result["changed"]["search"], result["before"]["search"], result)
        self.assertEqual(result["changed"]["tags"], result["before"]["tags"], result)
        self.assertEqual(result["changed"]["draft"]["familyId"], result["before"]["familyId"], result)
        self.assertEqual(result["changed"]["draft"]["platformKey"], result["before"]["platformKey"], result)
        self.assertEqual(result["changed"]["familyScrollTop"], result["before"]["familyScrollTop"], result)
        self.assertEqual(result["changed"]["familyLabel"], "Kling 更新版", result)
        self.assertEqual(result["changed"]["familyReplacementBatches"], 1, result)
        self.assertEqual(result["commits"], 0, result)

    def test_outside_click_cancels_browsed_path_without_changing_saved_option(self):
        self._evaluate("document.querySelector('.model-config-trigger').click();")
        result = self._evaluate("""
            (() => {
              const popover = document.querySelector('.model-config-popover');
              const original = window.__demo.mounted[0].getState().committed.optionId;
              [...popover.querySelectorAll('.model-config-stage-family .model-config-option')]
                .find(row => row.textContent.includes('Kling')).click();
              const stayedOpen = !popover.hidden;
              document.body.click();
              const state = window.__demo.mounted[0].getState();
              return {stayedOpen, closed: popover.hidden, commits: window.__demo.commits.length,
                unchanged: state.committed.optionId === original};
            })()
        """)
        self.assertTrue(result["stayedOpen"], result)
        self.assertTrue(result["closed"], result)
        self.assertEqual(result["commits"], 0, result)
        self.assertTrue(result["unchanged"], result)

    def test_filter_empty_state_and_clear_action_are_localized_in_english(self):
        result = self._evaluate("""
            (() => {
              const previous = window.StudioI18n;
              window.StudioI18n = {lang: () => 'en'};
              const instance = window.__demo.mounted[0];
              instance.element.querySelector('.model-config-trigger').click();
              const popover = instance.popover;
              const search = popover.querySelector('[data-model-config-search]');
              search.value = 'fixture-no-match';
              search.dispatchEvent(new Event('input', {bubbles:true}));
              const clear = popover.querySelector('.model-config-clear-filters');
              const result = {
                tag: [...popover.querySelectorAll('.model-config-tag')]
                  .some(chip => chip.textContent === 'Multimodal reference'),
                empty: popover.querySelector('.model-config-empty').textContent,
                clear: clear && clear.textContent
              };
              if (clear) clear.click();
              result.clearLeavesPopoverOpen = !popover.hidden;
              result.searchCleared = popover.querySelector('[data-model-config-search]').value === '';
              window.StudioI18n = previous;
              return result;
            })()
        """)
        self.assertTrue(result["tag"], result)
        self.assertEqual(result["empty"], "No models match the current search or filters.")
        self.assertEqual(result["clear"], "Clear filters")
        self.assertTrue(result["clearLeavesPopoverOpen"], result)
        self.assertTrue(result["searchCleared"], result)

    def test_search_keeps_focus_across_multiple_characters_and_renders_once(self):
        result = self._evaluate("""
            (() => {
              const instance = window.__demo.mounted[0];
              instance.element.querySelector('.model-config-trigger').click();
              const popover = instance.popover;
              const search = popover.querySelector('[data-model-config-search]');
              const familyList = popover.querySelector('.model-config-stage-family .model-config-stage-options');
              let renders = 0;
              const replace = familyList.replaceChildren.bind(familyList);
              familyList.replaceChildren = (...args) => { renders += 1; return replace(...args); };
              search.focus();
              const focusAfterEachCharacter = [];
              for (const query of ['s', 'se', 'seedance']) {
                search.value = query;
                search.dispatchEvent(new Event('input', {bubbles:true}));
                focusAfterEachCharacter.push(document.activeElement === search);
              }
              return {
                sameInput: popover.querySelector('[data-model-config-search]') === search,
                focusAfterEachCharacter,
                renders,
                query: instance.getState().search
              };
            })()
        """)
        self.assertTrue(result["sameInput"], result)
        self.assertEqual(result["focusAfterEachCharacter"], [True, True, True], result)
        self.assertEqual(result["renders"], 3, "每个搜索输入事件只应投影一次候选列表")
        self.assertEqual(result["query"], "seedance")

    def test_commit_failure_is_visible_retryable_and_cleared_after_success(self):
        result = self._evaluate("""
            (async () => {
              window.__demo.destroyAll();
              const host = document.getElementById('host');
              host.replaceChildren();
              let attempts = 0;
              const instance = window.mountModelConfigControl(host, {
                catalog: window.__demo.buildCatalog(0),
                selection: {optionId: '', parameters: {}},
                onCommit: () => ++attempts === 1
                  ? Promise.reject(new Error('fixture commit failed'))
                  : Promise.resolve()
              });
              const trigger = instance.element.querySelector('.model-config-trigger');
              trigger.click();
              instance.popover.querySelector('.model-config-stage-variant .model-config-leaf').click();
              await new Promise(resolve => setTimeout(resolve, 0));
              const failed = {
                visible: !instance.popover.querySelector('.model-config-error').hidden,
                message: instance.popover.querySelector('.model-config-error').textContent,
                open: !instance.popover.hidden,
                committed: instance.getState().committed.optionId
              };
              window.StudioI18n = {lang: () => 'en'};
              instance.updateContext({phase: 'language-check'});
              const englishMessage = instance.popover.querySelector('.model-config-error').textContent;
              window.StudioI18n = null;
              instance.updateContext({phase: 'retry'});
              const retry = instance.popover.querySelector('.model-config-stage-variant .model-config-leaf');
              if (retry) retry.click();
              await new Promise(resolve => setTimeout(resolve, 0));
              return {
                failed,
                englishMessage,
                attempts,
                cleared: instance.popover.querySelector('.model-config-error').hidden,
                closed: instance.popover.hidden
              };
            })()
        """)
        self.assertTrue(result["failed"]["visible"], result)
        self.assertIn("fixture commit failed", result["failed"]["message"])
        self.assertIn("再次选择运行模式重试", result["failed"]["message"])
        self.assertIn("Save failed: fixture commit failed. Choose the run mode again to retry.", result["englishMessage"])
        self.assertTrue(result["failed"]["open"], result)
        self.assertEqual(result["failed"]["committed"], "")
        self.assertEqual(result["attempts"], 2, result)
        self.assertTrue(result["cleared"], result)
        self.assertTrue(result["closed"], result)

    def test_delayed_commit_success_preserves_reopened_picker_browse_dom_and_focus(self):
        result = self._evaluate("""
            (async () => {
              window.__demo.destroyAll();
              const host = document.getElementById('host');
              host.replaceChildren();
              let resolveCommit;
              let attempts = 0;
              const pendingCommit = new Promise(resolve => { resolveCommit = resolve; });
              const instance = window.mountModelConfigControl(host, {
                catalog: window.__demo.buildCatalog(0),
                selection: {optionId: '', parameters: {}},
                onCommit: () => { attempts += 1; return pendingCommit; }
              });
              const trigger = instance.element.querySelector('.model-config-trigger');
              trigger.click();
              instance.popover.querySelector('.model-config-stage-variant .model-config-leaf').click();
              await new Promise(resolve => setTimeout(resolve, 0));
              const pendingClosed = instance.popover.hidden && attempts === 1;

              trigger.click();
              const popover = instance.popover;
              const kling = [...popover.querySelectorAll('.model-config-stage-family [data-family-id]')]
                .find(row => row.getAttribute('data-family-id') === 'fixture-kling');
              kling.click();
              const platform = [...popover.querySelectorAll('.model-config-stage-platform [data-platform-key]')]
                .find(row => row.getAttribute('data-platform-key') === 'fixture-conn-cn@cn');
              platform.click();
              const selectedFamily = popover.querySelector('.model-config-stage-family [data-family-id="fixture-kling"]');
              const selectedPlatform = popover.querySelector('.model-config-stage-platform [data-platform-key="fixture-conn-cn@cn"]');
              selectedPlatform.focus();
              const focusedBeforeResolve = document.activeElement;
              const familyBeforeResolve = selectedFamily;
              const platformBeforeResolve = selectedPlatform;
              const draftBeforeResolve = Object.assign({}, instance.getState().draft);

              resolveCommit();
              await new Promise(resolve => setTimeout(resolve, 0));
              return {
                pendingClosed,
                attempts,
                open: !popover.hidden,
                draft: instance.getState().draft,
                draftBeforeResolve,
                familyNodePreserved: familyBeforeResolve === popover.querySelector('[data-family-id="fixture-kling"]'),
                platformNodePreserved: platformBeforeResolve === popover.querySelector('[data-platform-key="fixture-conn-cn@cn"]'),
                focusPreserved: document.activeElement === focusedBeforeResolve,
                focusedElement: document.activeElement?.getAttribute('data-platform-key') || ''
              };
            })()
        """)
        self.assertTrue(result["pendingClosed"], result)
        self.assertEqual(result["attempts"], 1, result)
        self.assertTrue(result["open"], result)
        self.assertEqual(result["draft"], result["draftBeforeResolve"], result)
        self.assertTrue(result["familyNodePreserved"], result)
        self.assertTrue(result["platformNodePreserved"], result)
        self.assertTrue(result["focusPreserved"], result)

    def test_escape_discards_without_commit(self):
        self._evaluate("document.querySelector('.model-config-trigger').click();")
        self._evaluate("""
            document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
        """)
        result = self._evaluate(
            "({commits: window.__demo.commits.length, hidden: document.querySelector('.model-config-popover').hidden})"
        )
        self.assertEqual(result["commits"], 0, "A07：Escape 不得保存")
        self.assertTrue(result["hidden"])

    def test_keyboard_focus_gives_same_preview_as_hover(self):
        self._evaluate("document.querySelector('.model-config-trigger').click();")
        self._evaluate("document.querySelector('.model-config-stage-variant .model-config-leaf').focus();")
        result = self._evaluate("""
            (() => ({previewing: document.querySelector('.model-config-id-row').classList.contains('is-previewing'),
                     commits: window.__demo.commits.length}))()
        """)
        self.assertTrue(result["previewing"], "A05：键盘 focus 必须获得与 hover 相同的只读预览")
        self.assertEqual(result["commits"], 0)

    def test_common_parameters_inline_and_advanced_only_behind_gear(self):
        result = self._evaluate("""
            (() => {
              const panel = document.querySelector('.model-config-parameters');
              const inlineKeys = [...panel.querySelectorAll('.model-config-param')].map(n => n.dataset.paramKey);
              const gear = document.querySelector('.model-config-gear');
              const gearHidden = gear.hidden;
              gear.click();
              const advancedKeys = [...panel.querySelectorAll('.model-config-param')].map(n => n.dataset.paramKey);
              return {inlineKeys, gearHidden, advancedKeys};
            })()
        """)
        self.assertIn("resolution", result["inlineKeys"], "常用参数必须直接铺开，不再全藏齿轮")
        self.assertNotIn("seed", result["inlineKeys"], "高级参数不得混在常用区")
        self.assertFalse(result["gearHidden"], "有高级字段时齿轮必须出现")
        self.assertEqual(result["advancedKeys"], ["seed", "negative_prompt"], "齿轮内只放高级参数")

    def test_popover_stays_inside_viewport(self):
        result = self._evaluate("""
            (() => {
              document.querySelector('.model-config-trigger').click();
              const rect = document.querySelector('.model-config-popover').getBoundingClientRect();
              return {top: rect.top, left: rect.left, right: rect.right, bottom: rect.bottom,
                      vw: document.documentElement.clientWidth, vh: document.documentElement.clientHeight};
            })()
        """)
        self.assertGreaterEqual(result["top"], 0, "浮层不得溢出视口上缘")
        self.assertGreaterEqual(result["left"], 0)
        self.assertLessEqual(result["right"], result["vw"] + 1, "浮层不得横向溢出")
        self.assertLessEqual(result["bottom"], result["vh"] + 1, "浮层不得纵向溢出")

    def test_node_defaults_module_picker_fits_canvas_agent_viewport(self):
        """真实默认设置 dialog 中的 module picker 不得超出可视区，并应限制整体高度。"""
        for width, height in ((1440, 900), (1280, 720), (390, 844)):
            with self.subTest(viewport=(width, height)):
                self._prepare_node_defaults_dialog(width, height)
                result = self._open_node_defaults_picker()
                if width == 1440:
                    self._capture_screenshot("node-defaults-picker-layout-green.png")
                self.assertGreaterEqual(result["popover"]["top"], 0, f"popover top out of viewport: {result}")
                self.assertGreaterEqual(result["popover"]["left"], 0, f"popover left out of viewport: {result}")
                self.assertLessEqual(result["popover"]["bottom"], height + 1, f"popover below viewport: {result}")
                self.assertLessEqual(result["popover"]["right"], width + 1, f"popover right of viewport: {result}")
                self.assertGreaterEqual(result["dialog"]["left"], 0, f"dialog left of viewport: {result}")
                self.assertLessEqual(result["dialog"]["right"], width + 1, f"dialog right of viewport: {result}")
                self.assertLess(result["popover"]["height"], height, f"picker must have a viewport-bounded height: {result}")
                if width <= 720:
                    self.assertLessEqual(result["familyList"]["scrollHeight"], result["familyList"]["height"] + 1,
                                         "窄屏家族目录随外层菜单自然展开，不再截成嵌套滚动框")
                else:
                    self.assertGreater(result["familyList"]["scrollHeight"], result["familyList"]["height"],
                                       "桌面模型家族列表仍应独立滚动")
                self.assertGreater(result["variantList"]["scrollHeight"], result["variantList"]["height"],
                                   "run-mode list must be independently scrollable")
                self.assertEqual(self._evaluate_at_viewport(width, height, "window.__demo.commits.length"), 0,
                                 "打开默认值选择器不得保存选择")

    def test_node_defaults_fixture_tracks_production_seven_tabs(self):
        """浏览器夹具的七个默认槽位必须与生产 canvas-agent.js 保持一致。"""
        import re

        source = (ROOT / "static" / "js" / "canvas-agent.js").read_text(encoding="utf-8")
        match = re.search(r"const kindLabels = \(\) => \(\{(.*?)\}\);", source, flags=re.S)
        self.assertIsNotNone(match, "生产默认槽位清单必须仍由 kindLabels 明确声明")
        production_kinds = re.findall(r"\b(text|image|video|audio|music|app|comfy)\s*:", match.group(1))
        expected_kinds = ["text", "image", "video", "audio", "music", "app", "comfy"]
        self.assertEqual(production_kinds, expected_kinds)

        self._prepare_node_defaults_dialog(390, 844)
        self._open_node_defaults_picker()
        result = self._run_viewport_scenario(390, 844, """
          const before=await evaluate(`(()=>{
            const tabs=document.querySelector('.agent-default-tabs');
            return {width:innerWidth,kinds:[...tabs.querySelectorAll('[data-agent-kind]')].map(tab=>tab.dataset.agentKind),
              scrollWidth:tabs.scrollWidth,clientWidth:tabs.clientWidth,scrollLeft:tabs.scrollLeft};
          })()`);
          const wheelResult=await wheel('.agent-default-tabs',{deltaX:700});
          const after=await evaluate(`(()=>{
            const tabs=document.querySelector('.agent-default-tabs'),last=tabs.querySelector('[data-agent-kind="comfy"]');
            const a=tabs.getBoundingClientRect(),b=last.getBoundingClientRect();
            return {width:innerWidth,left:b.left,right:b.right,boxLeft:a.left,boxRight:a.right,scrollLeft:tabs.scrollLeft,
              scrollWidth:tabs.scrollWidth,clientWidth:tabs.clientWidth};
          })()`);
          return {before,wheel:wheelResult,after};
        """)
        self.assertEqual(result["before"]["width"], 390, result)
        self.assertEqual(result["before"]["kinds"], expected_kinds, "夹具必须实际呈现生产七个默认槽位")
        self.assertGreater(result["before"]["scrollWidth"], result["before"]["clientWidth"], result)
        self.assertGreater(result["wheel"]["after"]["left"], 0, f"真实横向滚轮应能浏览七槽末项: {result}")
        self.assertGreater(result["after"]["scrollLeft"], 0, result)
        self.assertGreaterEqual(result["after"]["left"], result["after"]["boxLeft"] - 1, result)
        self.assertLessEqual(result["after"]["right"], result["after"]["boxRight"] + 1, result)

    def test_node_defaults_keyboard_reaches_scrolled_family_then_leaf_commits_once(self):
        width, height = 1280, 720
        self._prepare_node_defaults_dialog(width, height)
        self._open_node_defaults_picker()
        result = self._run_viewport_scenario(width, height, """
          const hasFamily=await evaluate(`Boolean(document.querySelector('#nodeDefaultsHost .model-config-stage-family [data-family-id]'))`);
          if(!hasFamily)throw new Error('family picker has no keyboard target');
          await evaluate(`document.querySelector('#nodeDefaultsHost .model-config-stage-family [data-family-id]').focus()`);
          for(let index=0;index<42;index+=1)await key('Tab',9);
          const focused=await evaluate(`(()=>{
            const active=document.activeElement;
            const list=document.querySelector('#nodeDefaultsHost .model-config-stage-family .model-config-stage-options');
            const row=active.getBoundingClientRect(),box=list.getBoundingClientRect();
            return {family:active.getAttribute('data-family-id'),scrollTop:list.scrollTop,
              visible:row.top>=box.top&&row.bottom<=box.bottom};
          })()`);
          await click('#nodeDefaultsHost .model-config-stage-family [data-family-id="fixture-scale-family-39"]');
          const familyChoice=await evaluate(`(()=>{
            const popover=document.querySelector('#nodeDefaultsHost .model-config-popover');
            const family=popover.querySelector('.model-config-stage-family .model-config-option.is-current');
            return {family:family?.getAttribute('data-family-id'),commits:window.__demo.commits.length,open:!popover.hidden};
          })()`);
          await click('#nodeDefaultsHost .model-config-stage-platform [data-platform-key]');
          const beforeLeaf=await evaluate(`(()=>{
            const popover=document.querySelector('#nodeDefaultsHost .model-config-popover');
            const leaf=popover.querySelector('.model-config-stage-variant .model-config-leaf');
            return {commits:window.__demo.commits.length,open:!popover.hidden,leafCount:popover.querySelectorAll('.model-config-stage-variant .model-config-leaf').length,
              leafId:leaf?.getAttribute('data-option-id')};
          })()`);
          await click('#nodeDefaultsHost .model-config-stage-variant .model-config-leaf');
          await delay(60);
          const leafResult=await evaluate(`(()=>{
            const popover=document.querySelector('#nodeDefaultsHost .model-config-popover');
            return {commits:window.__demo.commits.length,optionId:window.__demo.commits[0]?.selection.optionId,hidden:popover.hidden};
          })()`);
          return {focused,familyChoice,beforeLeaf,leafResult};
        """)
        focused = result["focused"]
        self.assertEqual(focused["family"], "fixture-scale-family-39", "Tab 必须能逐项走到列表底部的模型家族")
        self.assertGreater(focused["scrollTop"], 0, "键盘焦点到末项时，家族列表应跟随滚动")
        self.assertTrue(focused["visible"], "键盘焦点项必须留在当前列表可见范围")
        self.assertEqual(result["familyChoice"]["family"], "fixture-scale-family-39")
        self.assertTrue(result["familyChoice"]["open"])
        self.assertEqual(result["familyChoice"]["commits"], 0, "键盘确认家族只更新草稿，不得保存")
        before_leaf = result["beforeLeaf"]
        self.assertEqual(before_leaf["commits"], 0, "家族和平台只更新草稿，不得保存")
        self.assertTrue(before_leaf["open"], "模型路径选择期间菜单必须保持展开")
        self.assertGreater(before_leaf["leafCount"], 0)
        leaf_result = result["leafResult"]
        self.assertEqual(leaf_result["commits"], 1, "最后点击运行模式才提交，且只能提交一次")
        self.assertEqual(leaf_result["optionId"], before_leaf["leafId"])
        self.assertTrue(leaf_result["hidden"], "叶子提交成功后菜单应关闭")

    def test_node_defaults_scrolls_to_last_run_mode_and_selects_it(self):
        width, height = 390, 844
        self._prepare_node_defaults_dialog(width, height)
        opened = self._open_node_defaults_picker()
        self.assertEqual(opened["viewport"]["width"], width, opened)
        self.assertLessEqual(opened["dialog"]["left"], width, opened)
        self.assertLessEqual(opened["dialog"]["right"], width + 1, opened)
        result = self._run_viewport_scenario(width, height, """
          const viewport=await evaluate(`(()=>({width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth}))()`);
          const commitsBefore=await evaluate(`window.__demo.commits.length`);
          await click('#nodeDefaultsHost .model-config-stage-family [data-family-id="fixture-seedance"]');
          const contrast=await evaluate(`(()=>{
            const button=document.querySelector('#nodeDefaultsHost .model-config-stage-family .model-config-option.is-current');
            const count=button.querySelector('.model-config-option-count');
            const parse=value=>{
              const parts=String(value).match(/[0-9.]+/g);
              if(!parts||parts.length<3)throw new Error('无法解析选中状态颜色: '+String(value));
              return parts.slice(0,3).map(Number);
            };
            const luminance=rgb=>rgb.map(value=>{value/=255;return value<=.04045?value/12.92:((value+.055)/1.055)**2.4;})
              .reduce((sum,value,index)=>sum+value*[.2126,.7152,.0722][index],0);
            const foreground=luminance(parse(getComputedStyle(count).color));
            const background=luminance(parse(getComputedStyle(button).backgroundColor));
            return {ratio:(Math.max(foreground,background)+.05)/(Math.min(foreground,background)+.05),
              color:getComputedStyle(count).color,background:getComputedStyle(button).backgroundColor};
          })()`);
          const familyWheel=await wheel('#nodeDefaultsHost .model-config-popover',{deltaY:500,paddingEdge:true});
          const familyMetrics=await evaluate(`(()=>{
            const popover=document.querySelector('#nodeDefaultsHost .model-config-popover');
            const list=popover.querySelector('.model-config-stage-family .model-config-stage-options');
            const selected=popover.querySelector('.model-config-stage-family .model-config-option.is-current');
            const stage=popover.querySelector('.model-config-stage-platform').getBoundingClientRect();
            const box=popover.getBoundingClientRect();
            return {scrollTop:list.scrollTop,max:list.scrollHeight-list.clientHeight,popoverScrollTop:popover.scrollTop,
              overflow:getComputedStyle(list).overflowY,family:selected?.getAttribute('data-family-id'),commits:window.__demo.commits.length,
              platformVisible:stage.top>=Math.max(0,box.top)&&stage.bottom<=Math.min(innerHeight,box.bottom)};
          })()`);
          const platformWheels=[];
          for(let index=0;index<8&&!familyMetrics.platformVisible;index+=1){
            platformWheels.push(await wheel('#nodeDefaultsHost .model-config-popover',{deltaY:500,paddingEdge:true}));
            Object.assign(familyMetrics,await evaluate(`(()=>{
              const popover=document.querySelector('#nodeDefaultsHost .model-config-popover');
              const box=popover.getBoundingClientRect();
              const stage=popover.querySelector('.model-config-stage-platform').getBoundingClientRect();
              return {popoverScrollTop:popover.scrollTop,platformVisible:stage.top>=Math.max(0,box.top)&&stage.bottom<=Math.min(innerHeight,box.bottom)};
            })()`));
          }
          await click('#nodeDefaultsHost .model-config-stage-platform [data-platform-key="fixture-conn-ai@global"]');
          const variantWheels=[];
          let leafMetrics=await evaluate(`(()=>{
            const popover=document.querySelector('#nodeDefaultsHost .model-config-popover');
            const list=popover.querySelector('.model-config-stage-variant .model-config-stage-options');
            const leaf=popover.querySelector('[data-option-id="node-default-leaf-35"]').getBoundingClientRect();
            const box=list.getBoundingClientRect(),menu=popover.getBoundingClientRect();
            return {scrollTop:list.scrollTop,max:list.scrollHeight-list.clientHeight,popoverScrollTop:popover.scrollTop,
              listTop:box.top,listBottom:box.bottom,
              listVisible:box.top>=Math.max(0,menu.top)&&box.bottom<=Math.min(innerHeight,menu.bottom),
              visible:leaf.top>=box.top&&leaf.bottom<=box.bottom&&leaf.top>=Math.max(0,menu.top)&&leaf.bottom<=Math.min(innerHeight,menu.bottom),
              commits:window.__demo.commits.length};
          })()`);
          for(let index=0;index<8&&!leafMetrics.listVisible;index+=1){
            variantWheels.push(await wheel('#nodeDefaultsHost .model-config-popover',{deltaY:500,paddingEdge:true}));
            Object.assign(leafMetrics,await evaluate(`(()=>{
              const popover=document.querySelector('#nodeDefaultsHost .model-config-popover');
              const list=popover.querySelector('.model-config-stage-variant .model-config-stage-options');
              const leaf=popover.querySelector('[data-option-id="node-default-leaf-35"]').getBoundingClientRect();
              const box=list.getBoundingClientRect(),menu=popover.getBoundingClientRect();
              return {scrollTop:list.scrollTop,max:list.scrollHeight-list.clientHeight,popoverScrollTop:popover.scrollTop,
                listTop:box.top,listBottom:box.bottom,
                listVisible:box.top>=Math.max(0,menu.top)&&box.bottom<=Math.min(innerHeight,menu.bottom),
                visible:leaf.top>=box.top&&leaf.bottom<=box.bottom&&leaf.top>=Math.max(0,menu.top)&&leaf.bottom<=Math.min(innerHeight,menu.bottom),
                commits:window.__demo.commits.length};
            })()`));
          }
          const leafScrolls=[];
          for(let index=0;index<8&&!leafMetrics.visible;index+=1){
            leafScrolls.push(await wheel('#nodeDefaultsHost .model-config-stage-variant .model-config-stage-options',{deltaY:700}));
            Object.assign(leafMetrics,await evaluate(`(()=>{
              const popover=document.querySelector('#nodeDefaultsHost .model-config-popover');
              const list=popover.querySelector('.model-config-stage-variant .model-config-stage-options');
              const leaf=popover.querySelector('[data-option-id="node-default-leaf-35"]').getBoundingClientRect();
              const box=list.getBoundingClientRect(),menu=popover.getBoundingClientRect();
              return {scrollTop:list.scrollTop,max:list.scrollHeight-list.clientHeight,popoverScrollTop:popover.scrollTop,
                listTop:box.top,listBottom:box.bottom,listVisible:box.top>=Math.max(0,menu.top)&&box.bottom<=Math.min(innerHeight,menu.bottom),
                visible:leaf.top>=box.top&&leaf.bottom<=box.bottom&&leaf.top>=Math.max(0,menu.top)&&leaf.bottom<=Math.min(innerHeight,menu.bottom),
                commits:window.__demo.commits.length};
            })()`));
          }
          await click('#nodeDefaultsHost [data-option-id="node-default-leaf-35"]');
          const committed=await evaluate(`(()=>{
            const popover=document.querySelector('#nodeDefaultsHost .model-config-popover');
            const save=document.querySelector('#canvasAgentDialog [data-agent-save]').getBoundingClientRect();
            return {commits:window.__demo.commits.length,selected:window.__demo.commits[0]?.selection.optionId,
              hidden:popover.hidden,saveVisible:save.top>=0&&save.bottom<=innerHeight};
          })()`);
          let saveState=await evaluate(`(()=>{
            const dialog=document.querySelector('#canvasAgentDialog'),save=dialog.querySelector('[data-agent-save]').getBoundingClientRect();
            return {scrollTop:dialog.scrollTop,max:dialog.scrollHeight-dialog.clientHeight,visible:save.top>=0&&save.bottom<=innerHeight};
          })()`);
          const saveWheels=[];
          for(let index=0;index<8&&!saveState.visible;index+=1){
            saveWheels.push(await wheel('#canvasAgentDialog',{deltaY:520,paddingEdge:true}));
            Object.assign(saveState,await evaluate(`(()=>{
              const dialog=document.querySelector('#canvasAgentDialog'),save=dialog.querySelector('[data-agent-save]').getBoundingClientRect();
              return {scrollTop:dialog.scrollTop,max:dialog.scrollHeight-dialog.clientHeight,visible:save.top>=0&&save.bottom<=innerHeight};
            })()`));
          }
          if(saveState.visible)await click('#canvasAgentDialog [data-agent-save]');
          const saveClicks=await evaluate(`window.__nodeDefaultsSaveClicks`);
          return {viewport,commitsBefore,contrast,familyWheel,familyMetrics,platformWheels,variantWheels,leafScrolls,leafMetrics,committed,saveState,saveWheels,saveClicks};
        """, mobile=False)
        self.assertEqual(result["viewport"]["width"], width, f"必须在真实390 CSS像素视口操作：{result}")
        self.assertEqual(result["viewport"]["documentWidth"], width, result)
        self.assertEqual(result["commitsBefore"], 0)
        self.assertGreaterEqual(result["contrast"]["ratio"], 4.5, f"选中项数量文字对比度至少4.5:1: {result['contrast']}")
        self.assertEqual(result["familyWheel"]["viewport"]["width"], width, result["familyWheel"])
        self.assertEqual(result["familyWheel"]["before"]["top"], 0, result["familyWheel"])
        self.assertGreater(result["familyWheel"]["after"]["top"], 100,
                           f"padding 边缘的真实滚轮应推动移动端弹层：{result['familyWheel']}")
        self.assertLessEqual(result["familyMetrics"]["max"], 1,
                             f"窄屏家族列表不应形成嵌套滚动区: {result['familyMetrics']}")
        self.assertGreater(result["familyMetrics"]["popoverScrollTop"], 100,
                           f"真实滚动应能浏览后续列：{result['familyMetrics']}")
        self.assertTrue(result["familyMetrics"]["platformVisible"],
                        f"平台列应能通过真实滚动到达：{result['familyMetrics']}")
        self.assertEqual(result["familyMetrics"]["family"], "fixture-seedance")
        self.assertEqual(result["familyMetrics"]["commits"], 0, "滚动/家族选择不得提前保存")
        self.assertEqual(result["leafMetrics"]["commits"], 0, "平台选择仍只是草稿")
        self.assertTrue(result["leafMetrics"]["listVisible"],
                        f"第三栏运行模式列表应先通过外层滚动进入可视区：{result['leafMetrics']} / {result['variantWheels']}")
        self.assertTrue(result["leafMetrics"]["visible"], f"末叶应通过真实滚动进入可点击区域：{result['leafMetrics']}")
        self.assertGreater(result["leafScrolls"][-1]["after"]["top"] if result["leafScrolls"] else result["leafMetrics"]["scrollTop"], 0,
                           f"运行模式列表必须由真实滚轮滚到底：{result['leafScrolls']} / {result['leafMetrics']}")
        self.assertEqual(result["committed"]["commits"], 1)
        self.assertEqual(result["committed"]["selected"], "node-default-leaf-35")
        self.assertTrue(result["committed"]["hidden"])
        self.assertTrue(result["saveState"]["visible"], f"保存按钮应能滚入移动视口：{result['saveState']}")
        self.assertEqual(result["saveClicks"], 1, "应能用真实点击到达保存按钮")

    def test_node_defaults_outside_click_and_escape_cancel_without_committing(self):
        width, height = 1280, 720
        self._prepare_node_defaults_dialog(width, height)
        self._open_node_defaults_picker()
        result = self._evaluate_at_viewport(width, height, """
          (() => {
            const popover=document.querySelector('#nodeDefaultsHost .model-config-popover');
            popover.querySelector('[data-family-id="fixture-seedance"]').click();
            document.querySelector('#canvasAgentDialog .canvas-agent-head h2').click();
            const outsideClosed=popover.hidden;
            document.querySelector('#nodeDefaultsHost .model-config-trigger').click();
            popover.querySelector('[data-family-id="fixture-kling"]').click();
            return {outsideClosed, commits:window.__demo.commits.length, open:!popover.hidden};
          })()
        """)
        self._press_key_at_viewport(width, height, "Escape")
        result["escapeClosed"] = self._evaluate_at_viewport(width, height,
            "document.querySelector('#nodeDefaultsHost .model-config-popover').hidden")
        self.assertTrue(result["outsideClosed"], "点击控件外部应收起默认值模型选择器")
        self.assertTrue(result["escapeClosed"], "Escape 应取消当前未提交的路径")
        self.assertEqual(result["commits"], 0, "取消路径不能持久化默认值")

    def test_inline_presentation_renders_in_place_without_portal(self):
        """§16 P4 第 4 项：inline 与 popover 共用同一套控件，只换承载方式。"""
        result = self._evaluate("""
            (async () => {
              window.__demo.destroyAll();
              const host = document.getElementById('host');
              host.replaceChildren();
              const box = document.createElement('div');
              box.id = 'inline-host';
              host.appendChild(box);
              window.__demo.commits.length = 0;
              const instance = window.__demo.mountInline('inline-host', {
                catalog: window.__demo.buildCatalog(0),
                selection: { optionId: 'opt_0000000000000001', parameters: { duration: 5, resolution: '720p' } }
              });
              await new Promise(r => setTimeout(r, 50));
              const inlinePopover = box.querySelector('.model-config-popover.is-inline');
              const portaled = document.querySelectorAll('#model-config-portal .model-config-popover').length;
              const stages = box.querySelectorAll('.model-config-stage').length;
              const order = [...box.querySelectorAll('.model-config-stage')].map(n => n.getAttribute('data-stage'));
              const paramGroups = box.querySelectorAll('.model-config-param').length;
              const leaf = box.querySelector('.model-config-stage-variant .model-config-leaf');
              if (leaf) leaf.click();
              await new Promise(r => setTimeout(r, 50));
              const afterCommit = {
                visible: !!box.querySelector('.model-config-popover.is-inline') && !box.querySelector('.model-config-popover').hidden,
                commits: window.__demo.commits.length
              };
              return {
                hasInlinePopover: !!inlinePopover,
                portaled,
                stages, order, paramGroups,
                afterCommit
              };
            })()
        """)
        self.assertTrue(result["hasInlinePopover"], "inline 必须就地渲染弹层内容")
        self.assertEqual(result["portaled"], 0, "inline 不得挂到 portal")
        self.assertEqual(result["stages"], 3)
        self.assertEqual(result["order"], ["family", "platform", "variant"])
        self.assertGreater(result["paramGroups"], 0, "内联同样要铺开常用参数")
        self.assertEqual(result["afterCommit"]["commits"], 1, "内联下提交语义与 popover 一致")
        self.assertTrue(result["afterCommit"]["visible"], "内联提交后不得隐藏控件")

    def test_destroy_removes_listeners_and_persists_nothing(self):
        result = self._evaluate("""
            (async () => {
              window.__demo.destroyAll();
              const host = document.getElementById('host');
              host.replaceChildren();
              const instance = window.mountModelConfigControl(host, {
                catalog: window.__demo.buildCatalog(0),
                selection: {optionId: '', parameters: {}},
                onCommit: p => window.__demo.commits.push(p)
              });
              instance.element.querySelector('.model-config-trigger').click();
              instance.popover.querySelector('.model-config-stage-variant .model-config-leaf').click();
              await new Promise(resolve => setTimeout(resolve, 0));   // onCommit 是异步的（§9.3）
              const before = window.__demo.commits.length;
              instance.destroy();
              const leftBehind = document.querySelectorAll('#model-config-portal .model-config-popover').length;
              const hostChildren = host.children.length;
              instance.destroy();   // 重复 destroy 必须安全
              return {before, leftBehind, hostChildren, afterSecondDestroy: host.children.length};
            })()
        """)
        self.assertGreaterEqual(result["before"], 1, "一次合法叶子点击必须恰好提交一次")
        self.assertEqual(result["leftBehind"], 0, "destroy 必须移除浮层，避免重复监听")
        self.assertEqual(result["hostChildren"], 0, "destroy 必须卸载根节点")
        self.assertEqual(result["afterSecondDestroy"], 0, "重复 destroy 必须幂等")


if __name__ == "__main__":
    unittest.main()
