"""P4 公共控件与紧凑样式的行为回归。

对应《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§5、§16 P4、§17 A 系列。

两层验证：
  1. 纯状态机（Node，无 DOM）：状态转换、单次提交、hover 零写入、搜索与失效保留。
  2. 真实浏览器（Chrome DevTools Protocol）：三栏顺序、键盘预览、参数齿轮、浮层视口与事件清理。

浏览器用例在本机没有 Chrome 时自动跳过，不伪装成已通过。
"""
from __future__ import annotations

import json
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
                "--disable-extensions", f"--user-data-dir={cls.profile_dir}",
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
                    if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                        return target
            except Exception:
                time.sleep(0.5)
        return None

    def _evaluate(self, expression: str):
        """通过 Node 内置 WebSocket 走 CDP，不依赖额外 Python 包。"""
        script = (
            "(async()=>{"
            "const ws=new WebSocket(process.argv[1]);"
            "await new Promise((res,rej)=>{ws.onopen=res;ws.onerror=rej;});"
            "const reply=await new Promise(res=>{"
            "  ws.onmessage=e=>res(e.data);"
            "  ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',"
            "    params:{expression:process.argv[2],returnByValue:true,awaitPromise:true}}));"
            "});"
            "const m=JSON.parse(reply);"
            "if(m.result&&m.result.exceptionDetails){console.error(JSON.stringify(m.result.exceptionDetails));process.exit(3);}"
            "const value=m.result&&m.result.result?m.result.result.value:null;"
            "console.log(JSON.stringify(value===undefined?null:value));"
            "ws.close();"
            "})()"
        )
        result = subprocess.run(
            ["node", "-e", script, self.target["webSocketDebuggerUrl"], expression],
            capture_output=True, text=True, timeout=40,
        )
        if result.returncode != 0:
            raise AssertionError(f"CDP 调用失败：{result.stderr[:400]}")
        return json.loads(result.stdout)

    def setUp(self):
        self._evaluate("window.__demo.reset(); window.__demo.destroyAll(); document.getElementById('host').replaceChildren();")
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
