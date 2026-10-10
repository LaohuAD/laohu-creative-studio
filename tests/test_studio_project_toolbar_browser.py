"""项目页工具栏与主题选择 UI 的隔离真实浏览器回归。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import test_studio_brand_browser as _brand  # noqa: E402


@unittest.skipUnless(_brand.CHROME and _brand.NODE, "需要本机 Chrome/Chromium 和 Node.js 执行隔离浏览器回归")
class StudioProjectToolbarBrowserTests(unittest.TestCase):
    """复用品牌测试提供的安全 mock API、独立 Chrome profile 与 CDP。"""

    @classmethod
    def setUpClass(cls):
        _brand.StudioBrandBrowserTests.setUpClass()
        cls.browser = _brand.StudioBrandBrowserTests("test_shared_brand_theme_and_interaction_states_across_product_pages")

    @classmethod
    def tearDownClass(cls):
        _brand.StudioBrandBrowserTests.tearDownClass()

    def open_hypit_projects(self, width: int):
        browser = self.browser
        browser.set_viewport(width)
        url = f"http://127.0.0.1:{_brand.StudioBrandBrowserTests.http_port}/static/hypit-list.html"
        browser.cdp("Page.navigate", {"url": url})
        self.assertTrue(browser.evaluate("(async()=>{for(let i=0;i<100;i++){if(document.readyState==='complete')return true;await new Promise(r=>setTimeout(r,20));}return false;})()"))
        self.assertTrue(browser.evaluate("(async()=>{for(let i=0;i<120;i++){if(document.querySelector('[data-project-id=\"safe-hypit\"]'))return true;await new Promise(r=>setTimeout(r,25));}return false;})()"), "Hypit 安全项目数据未加载")

    def layout_report(self):
        return self.browser.evaluate("""(() => {
          const title=document.querySelector('.studio-project-toolbar-heading');
          const titleText=document.querySelector('.studio-project-toolbar-heading h2');
          const description=document.getElementById('studioProjectDescription');
          const actions=document.querySelector('.studio-project-toolbar-actions');
          const toolbar=document.querySelector('.studio-project-toolbar');
          const guide=document.querySelector('#studioProjectGuide');
          const grid=document.querySelector('#studioProjectGrid');
          const rect=(node)=>node&&node.getBoundingClientRect();
          const titleRect=rect(title), actionRect=rect(actions), toolbarRect=rect(toolbar), guideRect=rect(guide), gridRect=rect(grid);
          const descriptionLineHeight=description&&parseFloat(getComputedStyle(description).lineHeight);
          return {
            module:document.body.dataset.studioModule,
            description:document.getElementById('studioProjectDescription')?.textContent?.trim()||'',
            titleRect:rect(titleText)&&{x:rect(titleText).x,y:rect(titleText).y,right:rect(titleText).right,bottom:rect(titleText).bottom},
            descriptionRect:rect(description)&&{x:rect(description).x,y:rect(description).y,right:rect(description).right,bottom:rect(description).bottom},
            descriptionFirstLineBottom:descriptionLineHeight&&rect(description).y+descriptionLineHeight,
            legacyCount:document.getElementById('studioProjectCount')?.textContent?.trim()||'',
            titleActionCenterDelta:titleRect&&actionRect?Math.abs((titleRect.top+titleRect.bottom-actionRect.top-actionRect.bottom)/2):null,
            actionParent:actions?.parentElement?.className||null,
            controls:[...document.querySelectorAll('#studioProjectSearch,#studioNewProjectButton,#studioPrepareButton,#studioImportGuide,#studioTrashButton')].map(node=>({id:node.id,parent:node.closest('.studio-project-toolbar-actions')!==null,rect:{x:rect(node).x,y:rect(node).y,width:rect(node).width,height:rect(node).height},fontSize:getComputedStyle(node).fontSize})),
            projectActions:[...document.querySelectorAll('.studio-project-card')].map(card=>({
              id:card.dataset.projectId,
              actions:[...card.querySelectorAll('.studio-project-card-actions [data-card-action]')].map(node=>({action:node.dataset.cardAction,rect:{x:rect(node).x,y:rect(node).y,width:rect(node).width,height:rect(node).height}}))
            })),
            toolbarY:toolbarRect?.y, toolbarBottom:toolbarRect?.bottom, guideY:guideRect?.y, gridY:gridRect?.y,
            legacyTools:!!document.querySelector('#studioCanvasTools'),
            viewport:document.documentElement.clientWidth, scrollWidth:document.documentElement.scrollWidth,
            bodyScrollWidth:document.body.scrollWidth,
            guideAfterToolbar:!!(toolbar&&guide&&toolbar.compareDocumentPosition(guide)&Node.DOCUMENT_POSITION_FOLLOWING),
            guideBeforeGrid:!!(guide&&grid&&guide.compareDocumentPosition(grid)&Node.DOCUMENT_POSITION_FOLLOWING)
          };
        })()""")

    def test_canvas_actions_share_title_header_and_guide_precedes_project_management(self):
        self.browser.navigate("projects", "light", 1440)
        self.browser.evaluate("StudioI18n.set('zh')")
        report = self.layout_report()
        self.assertEqual(report["module"], "canvas")
        self.assertFalse(report["legacyTools"], "冗余画布工具说明块仍存在")
        self.assertEqual({item["id"] for item in report["controls"]}, {
            "studioProjectSearch", "studioPrepareButton", "studioNewProjectButton", "studioImportGuide", "studioTrashButton"
        })
        self.assertEqual(self.browser.evaluate("document.querySelector('#studioPrepareButton')?.textContent.trim()"), "准备创作技能")
        self.assertTrue(all(item["parent"] for item in report["controls"]), report)
        self.assertLess(report["titleActionCenterDelta"], 50, report)
        self.assertTrue(report["guideAfterToolbar"] and report["guideBeforeGrid"], report)
        self.browser.evaluate("StudioI18n.set('en')")
        english = self.browser.evaluate("""(() => ({
          description:document.getElementById('studioProjectDescription')?.textContent?.trim(),
          search:document.getElementById('studioProjectSearch')?.getAttribute('aria-label'),
          controls:[...document.querySelectorAll('.studio-project-toolbar-actions button')].map(button=>button.innerText.trim())
        }))()""")
        self.assertEqual(english["description"], "Organise assets, connect canvas nodes and build each piece step by step.")
        self.assertEqual(english["search"], "Search projects")
        self.assertEqual(english["controls"], ["Prepare creative skills", "New project", "Import project", "Trash"])
        self.browser.evaluate("document.getElementById('studioTrashButton').click()")
        self.assertTrue(self.browser.evaluate("(async()=>{for(let i=0;i<80;i++){const panel=document.getElementById('studioTrashPanel');if(panel&&!panel.hidden)return true;await new Promise(r=>setTimeout(r,20));}return false;})()"), "回收站原点击处理未保留")
        self.browser.evaluate("document.getElementById('studioTrashClose').click()")

    def test_hypit_search_skill_and_create_share_title_header(self):
        self.open_hypit_projects(1440)
        self.browser.evaluate("StudioI18n.set('zh')")
        report = self.layout_report()
        self.assertEqual(report["module"], "hypit")
        self.assertEqual({item["id"] for item in report["controls"]}, {
            "studioProjectSearch", "studioPrepareButton", "studioNewProjectButton"
        })
        self.assertEqual(self.browser.evaluate("document.querySelector('#studioPrepareButton')?.textContent.trim()"), "准备创作技能")
        self.assertTrue(all(item["parent"] for item in report["controls"]), report)
        self.assertLess(report["titleActionCenterDelta"], 50, report)
        self.assertTrue(report["guideAfterToolbar"] and report["guideBeforeGrid"], report)
        self.browser.evaluate("StudioI18n.set('en')")
        english = self.browser.evaluate("""(() => ({
          description:document.getElementById('studioProjectDescription')?.textContent?.trim(),
          search:document.getElementById('studioProjectSearch')?.getAttribute('aria-label'),
          controls:[...document.querySelectorAll('.studio-project-toolbar-actions button')].map(button=>button.innerText.trim())
        }))()""")
        self.assertEqual(english["description"], "Manage Hypit video recreation projects, connect an external Agent and review the work.")
        self.assertEqual(english["search"], "Search projects")
        self.assertEqual(english["controls"], ["Prepare creative skills", "New project"])

    def test_project_headers_describe_each_module_and_all_cards_keep_two_by_two_actions(self):
        browser = self.browser
        expected_actions = ["open", "rename", "connect", "delete"]
        expected_descriptions = {
            "canvas": "整理素材、连接画布节点，逐步完成作品。",
            "hypit": "管理 Hypit 视频复刻项目，连接外部 Agent，并查看制作内容与结果。",
        }
        expected_english = {
            "canvas": "Organise assets, connect canvas nodes and build each piece step by step.",
            "hypit": "Manage Hypit video recreation projects, connect an external Agent and review the work.",
        }
        for module in ("canvas", "hypit"):
            for width in (1440, 1280, 390):
                with self.subTest(module=module, width=width):
                    if module == "hypit":
                        self.open_hypit_projects(width)
                    else:
                        browser.navigate("projects", "light", width)
                    browser.evaluate("StudioI18n.set('zh')")
                    report = self.layout_report()
                    self.assertEqual(report["module"], module)
                    self.assertEqual(report["description"], expected_descriptions[module], report)
                    if width > 820:
                        self.assertGreater(report["descriptionRect"]["x"], report["titleRect"]["right"], report)
                        self.assertLess(abs(report["descriptionFirstLineBottom"] - report["titleRect"]["bottom"]), 2, report)
                    else:
                        self.assertGreaterEqual(report["descriptionRect"]["y"], report["titleRect"]["bottom"], report)
                    self.assertEqual(report["legacyCount"], "", "列表头部仍显示项目计数/排序文案")
                    browser.evaluate("StudioI18n.set('en')")
                    self.assertEqual(self.layout_report()["description"], expected_english[module])
                    browser.evaluate("StudioI18n.set('zh')")
                    report = self.layout_report()
                    self.assertLessEqual(report["scrollWidth"], report["viewport"], report)
                    self.assertEqual(len(report["projectActions"]), 1, report)
                    actions = report["projectActions"][0]["actions"]
                    self.assertEqual([item["action"] for item in actions], expected_actions, report)
                    self.assertTrue(all(item["rect"]["width"] > 0 and item["rect"]["height"] > 0 for item in actions), report)
                    self.assertLess(abs(actions[0]["rect"]["y"] - actions[1]["rect"]["y"]), 1, report)
                    self.assertLess(abs(actions[2]["rect"]["y"] - actions[3]["rect"]["y"]), 1, report)
                    self.assertGreater(actions[2]["rect"]["y"], actions[0]["rect"]["y"], report)
                    self.assertLess(abs(actions[0]["rect"]["x"] - actions[2]["rect"]["x"]), 1, report)
                    self.assertLess(abs(actions[1]["rect"]["x"] - actions[3]["rect"]["x"]), 1, report)

    def test_sidebar_module_navigation_keeps_click_target_and_compact_spacing(self):
        browser = self.browser
        for width in (1440, 1280):
            with self.subTest(width=width):
                browser.navigate("shell", "light", width)
                report = browser.evaluate("""(() => {
                  const items=[...document.querySelectorAll('.sidebar nav > .nav-item')];
                  return {
                    width:document.documentElement.clientWidth,
                    labels:items.map(node=>node.innerText.trim()),
                    heights:items.map(node=>node.getBoundingClientRect().height),
                    pitches:items.slice(1).map((node,index)=>node.getBoundingClientRect().top-items[index].getBoundingClientRect().top)
                  };
                })()""")
                self.assertEqual(report["labels"], ["画布", "Hypit克隆", "公众号文章", "音乐创作", "素材库"], report)
                self.assertTrue(all(height >= 44 for height in report["heights"]), report)
                self.assertTrue(all(52 <= pitch <= 56 for pitch in report["pitches"]), report)

    def test_canvas_and_hypit_toolbar_wrap_on_narrow_screens_without_horizontal_overflow(self):
        for module in ("canvas", "hypit"):
            with self.subTest(module=module):
                if module == "canvas":
                    self.browser.navigate("projects", "light", 390)
                else:
                    self.open_hypit_projects(390)
                report = self.layout_report()
                self.assertLessEqual(report["scrollWidth"], report["viewport"], report)
                self.assertTrue(all(item["parent"] and item["rect"]["width"] > 0 for item in report["controls"]), report)
                self.assertTrue(all(float(item["fontSize"].removesuffix("px")) >= 12 for item in report["controls"]), report)

    def test_independent_work_pages_have_no_management_return_and_share_three_toolbar_controls(self):
        browser = self.browser
        pages = (
            ("article.html?id=article-fixture", ".article-toolbar-actions", "articleRefreshButton", "articleLanguageButton", "articleThemeButton"),
            ("music.html?id=music-fixture", ".music-toolbar-actions", "musicRefreshButton", "musicLanguageButton", "musicThemeButton"),
            ("hypit.html?id=safe-hypit", ".hypit-toolbar-actions", "refresh", "language", "theme"),
        )
        for width in (1440, 390):
            for path, group_selector, refresh_id, language_id, theme_id in pages:
                with self.subTest(page=path.split("?", 1)[0], width=width):
                    browser.set_viewport(width)
                    browser.cdp("Page.navigate", {"url": f"http://127.0.0.1:{_brand.StudioBrandBrowserTests.http_port}/static/{path}"})
                    loaded = browser.evaluate(f"""(async()=>{{
                      for(let i=0;i<160;i++){{
                        if(document.readyState==='complete' && document.querySelector({json.dumps(group_selector)}) &&
                           document.getElementById({json.dumps(refresh_id)}) && window.StudioTheme && window.StudioI18n) return true;
                        await new Promise(resolve=>setTimeout(resolve,25));
                      }} return false;
                    }})()""")
                    self.assertTrue(loaded, f"作品页工具没有加载：{path}")
                    browser.evaluate("StudioI18n.set('zh');StudioTheme.setPreference({version:1,themeId:'studio-violet',appearance:'light'});")
                    report = browser.evaluate(f"""(() => {{
                      const group=document.querySelector({json.dumps(group_selector)});
                      const buttons=[...group.querySelectorAll('button')];
                      const rect=button=>{{const r=button.getBoundingClientRect();return {{width:r.width,height:r.height,radius:getComputedStyle(button).borderRadius}};}};
                      return {{
                        ids:buttons.map(button=>button.id), metrics:buttons.map(rect), gap:getComputedStyle(group).gap,
                        managementLinks:[...document.querySelectorAll('header a, #empty a')].filter(link=>/管理|项目|projects/i.test(link.textContent+' '+link.getAttribute('href'))).length,
                        agentButton:!!document.getElementById('musicConnectButton'), connectionDialog:!!document.getElementById('musicConnectionDialog'),
                        overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,
                        languageLabel:document.getElementById({json.dumps(language_id)}).getAttribute('aria-label'),
                        refreshLabel:document.getElementById({json.dumps(refresh_id)}).getAttribute('aria-label')
                      }};
                    }})()""")
                    self.assertEqual(report["ids"], [refresh_id, language_id, theme_id], report)
                    self.assertEqual(report["metrics"], [{"width": 34, "height": 34, "radius": "9px"}] * 3, report)
                    self.assertEqual(report["gap"], "7px" if width > 420 else "5px", report)
                    self.assertEqual(report["managementLinks"], 0, report)
                    self.assertFalse(report["agentButton"] or report["connectionDialog"], report)
                    self.assertFalse(report["overflow"], report)
                    self.assertTrue(report["refreshLabel"] and report["languageLabel"], report)

                    browser.evaluate(f"document.getElementById({json.dumps(language_id)}).click()")
                    self.assertTrue(browser.evaluate("StudioI18n.lang()==='en'"), f"语言按钮没有切换：{path}")
                    labels = browser.evaluate(f"""(() => ({{
                      language:document.getElementById({json.dumps(language_id)}).textContent.trim(),
                      languageLabel:document.getElementById({json.dumps(language_id)}).getAttribute('aria-label')
                    }}))()""")
                    self.assertEqual(labels, {"language": "EN", "languageLabel": "Switch language"}, labels)
                    before = browser.evaluate("StudioTheme.get()")
                    browser.evaluate(f"document.getElementById({json.dumps(theme_id)}).click()")
                    self.assertNotEqual(browser.evaluate("StudioTheme.get()"), before, f"主题按钮没有切换：{path}")
                    browser.evaluate("window.__toolbarFetches=[];const originalFetch=window.fetch.bind(window);window.fetch=(input,init={})=>{window.__toolbarFetches.push({url:String(input),method:String(init.method||'GET').toUpperCase()});return originalFetch(input,init);};")
                    browser.evaluate(f"document.getElementById({json.dumps(refresh_id)}).click()")
                    self.assertTrue(browser.evaluate("(async()=>{for(let i=0;i<40;i++){if(window.__toolbarFetches?.length)return window.__toolbarFetches.some(item=>item.method==='GET');await new Promise(resolve=>setTimeout(resolve,25));}return false;})()"), f"刷新按钮没有调用本页现有读取逻辑：{path}")

        self.open_hypit_projects(1440)
        self.assertTrue(browser.evaluate("!!document.querySelector('.studio-project-card-actions [data-card-action=connect]')"), "项目管理页的 Agent 接入入口必须保留")

    def test_theme_picker_hides_system_and_undo_but_keeps_system_preference_compatible(self):
        browser = self.browser
        browser.navigate("shell", "light", 1440)
        browser.evaluate("document.getElementById('theme-toggle-btn').click()")
        self.assertTrue(browser.evaluate("(async()=>{for(let i=0;i<80;i++){const p=document.getElementById('studioThemePanel');if(p&&!p.hidden)return true;await new Promise(r=>setTimeout(r,20));}return false;})()"))
        picker = browser.evaluate("""(() => ({
          appearances:[...document.querySelectorAll('#studioThemePanel [data-theme-appearance]')].map(node=>node.dataset.themeAppearance),
          undo:!!document.getElementById('studioThemeUndo')
        }))()""")
        self.assertEqual(picker["appearances"], ["light", "dark"])
        self.assertFalse(picker["undo"])

        browser.evaluate("""(() => {
          localStorage.setItem('studio_theme_preference_v1', JSON.stringify({version:1,themeId:'forest',appearance:'system'}));
          return true;
        })()""")
        browser.cdp("Page.reload", {"ignoreCache": True})
        self.assertTrue(browser.evaluate("(async()=>{for(let i=0;i<120;i++){if(document.readyState==='complete'&&document.querySelectorAll('.side-pill').length>=4&&StudioTheme?.getPreference?.().appearance==='system')return true;await new Promise(r=>setTimeout(r,25));}return false;})()"), "重载后没有保留 system 旧偏好")
        browser.evaluate("document.getElementById('theme-toggle-btn').click()")
        state = browser.evaluate("""(() => {
          const preference=StudioTheme.getPreference();
          const appearance=document.documentElement.dataset.studioAppearance;
          const mode=document.documentElement.dataset.studioAppearanceMode;
          const selected=[...document.querySelectorAll('#studioThemePanel [data-theme-appearance]')].filter(node=>node.getAttribute('aria-pressed')==='true').map(node=>node.dataset.themeAppearance);
          return {preference,appearance,mode,selected,stored:localStorage.getItem('studio_theme_preference_v1')};
        })()""")
        self.assertEqual(state["preference"], {"version": 1, "themeId": "forest", "appearance": "system"})
        self.assertEqual(state["mode"], "system")
        self.assertIn(state["appearance"], ("light", "dark"))
        self.assertEqual(state["selected"], [state["appearance"]])
        self.assertEqual(json.loads(state["stored"]), state["preference"])


if __name__ == "__main__":
    unittest.main()
