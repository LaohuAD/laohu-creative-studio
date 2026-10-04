"""P6 浏览器验证：Hypit 槽位使用内联公共控件，候选来自共享选项投影。

对应《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§9.4、§16 P6。

零服务器、零用户数据：桩页面把 fetch 全部拦截并返回本地假数据。
判别方式——投影里放一个家族树中不存在的模型 `fixture-projected-only-model`，
家族树里放一个投影中不存在的 `fixture-family-tree-model`；谁出现就说明谁在生效。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "tests" / "browser" / "hypit-slot-candidates.html"

PROJECTED_MODEL = "fixture-projected-only-model"
FAMILY_TREE_MODEL = "fixture-family-tree-model"


def chrome_binary():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


CHROME = chrome_binary()


@unittest.skipUnless(CHROME, "本机没有可用 Chrome，浏览器用例跳过（不伪装成已通过）")
class HypitSlotCandidateBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 9351
        cls.profile_dir = ROOT / "cache" / "p6-hypit-chrome"
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

    def evaluate(self, expression: str):
        script = (
            "(async()=>{"
            "const ws=new WebSocket(process.argv[1]);"
            "await new Promise((res,rej)=>{ws.onopen=res;ws.onerror=rej;});"
            "const reply=await new Promise(res=>{ws.onmessage=e=>res(e.data);"
            "  ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',"
            "    params:{expression:process.argv[2],returnByValue:true,awaitPromise:true}}));});"
            "const m=JSON.parse(reply);"
            "if(m.result&&m.result.exceptionDetails){console.error(JSON.stringify(m.result.exceptionDetails));process.exit(3);}"
            "const v=m.result&&m.result.result?m.result.result.value:null;"
            "console.log(JSON.stringify(v===undefined?null:v));ws.close();})()"
        )
        result = subprocess.run(
            ["node", "-e", script, self.target["webSocketDebuggerUrl"], expression],
            capture_output=True, text=True, timeout=40,
        )
        if result.returncode != 0:
            raise AssertionError(f"CDP 调用失败：{result.stderr[:400]}")
        return json.loads(result.stdout)

    def _load_settings(self):
        return self.evaluate("""
            (async () => {
              for (let i = 0; i < 60 && !window.__fixture?.ready; i++) {
                await new Promise(r => setTimeout(r, 100));
              }
              await window.__fixture.forceLoad();
              await new Promise(r => setTimeout(r, 300));
              const slots = document.getElementById('hypitSlots');
              return {
                ready: !!window.__fixture?.ready,
                html: slots ? slots.textContent : '',
                containerExists: !!slots,
                requested: window.__fixture.requests,
                controlCount: slots ? slots.querySelectorAll('.model-config').length : 0,
                stageCount: slots ? slots.querySelectorAll('.model-config-stage').length : 0,
                stageOrder: slots ? [...new Set([...slots.querySelectorAll('.model-config-stage')]
                    .map(n => n.getAttribute('data-stage')))].join('|') : '',
                inlinePopovers: slots ? slots.querySelectorAll('.model-config-popover.is-module').length : 0,
                familyText: slots ? [...slots.querySelectorAll('.model-config-stage-family')]
                    .map(n => n.textContent).join('|') : '',
                variantText: slots ? [...slots.querySelectorAll('.model-config-stage-variant')]
                    .map(n => [...n.querySelectorAll('[data-option-id]')].map(el => el.dataset.optionId).join('|')).join('|') : ''
              };
            })()
        """)

    def test_model_only_cards_switch_in_one_click_and_show_tags(self):
        self._load_settings()
        result = self.evaluate("""(() => {
          const cards = document.querySelectorAll('.hypit-slot-card:not(.is-disabled)');
          const first = cards[0], second = cards[1];
          first.querySelector('.model-config-trigger').click();
          const button = second.querySelector('.model-config-trigger');
          button.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
          const noEarlyCollapse = !first.querySelector('.model-config-popover').hidden;
          button.click();
          const switched = first.querySelector('.model-config-popover').hidden && !second.querySelector('.model-config-popover').hidden;
          const tags = second.querySelector('.model-config-badges')?.textContent || '';
          const hasParameterBar = [...document.querySelectorAll('.model-config-actions')].some(el => el.getBoundingClientRect().height > 0);
          document.body.click();
          return {noEarlyCollapse, switched, tags, hasParameterBar, closed: second.querySelector('.model-config-popover').hidden};
        })()""")
        self.assertTrue(result['noEarlyCollapse'], result)
        self.assertTrue(result['switched'], result)
        self.assertTrue(result['closed'], result)
        self.assertFalse(result['hasParameterBar'], result)
        self.assertIn('文生图', result['tags'])

    def test_slot_cards_mount_the_inline_shared_control(self):
        data = self._load_settings()
        self.assertTrue(data["ready"], "桩页面必须完成初始化")
        self.assertTrue(data["containerExists"], "必须存在 #hypitSlots 容器")
        self.assertGreater(data["controlCount"], 0, "槽位必须挂载公共控件")
        self.assertGreater(data["inlinePopovers"], 0, "槽位必须使用槽位内的可折叠面板，而不是漂浮弹层")
        self.assertGreaterEqual(data["stageCount"], 3, "每个槽位至少渲染三栏")
        self.assertEqual(data["stageOrder"], "family|platform|variant", "三栏顺序必须固定")

    def test_candidates_come_from_the_shared_projection(self):
        data = self._load_settings()
        # 投影里的 canonical_family_label 只存在于共享投影路径；
        # 旧推导会退回 display_name/model_id，不会产生这个中文系列名。
        self.assertIn("桩系列", data["familyText"], "第一栏必须展示投影提供的系列标签")
        self.assertNotIn("不应显示", data["familyText"], "画布不提供的 ModelScope 节点不得进入 Hypit 默认候选")
        self.assertNotIn(FAMILY_TREE_MODEL, data["familyText"] + data["variantText"],
                         "家族树专有模型不得出现——出现即说明回退分支在生效")
        # 桩投影只提供 text/image 两槽候选，其余四槽（含音乐）显示“未接入”是正确行为：
        # 断言精确数量，确认“有候选才挂载、没候选不假装可用”。
        self.assertEqual(data["html"].count("未接入"), 4, "无候选槽位必须明确标注，不得伪造可用项")

    def test_projected_model_reaches_the_variant_column(self):
        data = self.evaluate("""
            (async () => {
              await window.__fixture.forceLoad();
              await new Promise(r => setTimeout(r, 300));
              const slots = document.getElementById('hypitSlots');
              const row = [...slots.querySelectorAll('.model-config-stage-family .model-config-option')]
                .find(item => item.textContent.indexOf('桩系列') !== -1);
              if (!row) return { found: false };
              row.click();
              await new Promise(r => setTimeout(r, 250));
              return {
                found: true,
                variantText: [...slots.querySelectorAll('.model-config-stage-variant [data-option-id]')].map(n => n.dataset.optionId).join('|')
              };
            })()
        """)
        self.assertTrue(data["found"], "必须能找到投影系列的条目")
        self.assertIn('opt_1111111111111111', data["variantText"],
                      "投影提供的真实选项必须能在第三栏选到")

    def test_settings_page_fetches_the_projection_endpoint(self):
        data = self._load_settings()
        self.assertTrue(any("/api/model-capabilities" in url for url in data["requested"]),
                        "设置页必须请求扁平投影来源")


if __name__ == "__main__":
    unittest.main()
