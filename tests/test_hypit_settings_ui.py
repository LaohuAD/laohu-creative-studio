import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "static/js/hypit-settings.js"
STYLES = ROOT / "static/css/hypit-settings.css"
PAGE = ROOT / "static/api-settings.html"
CANVAS_PAGE = ROOT / "static/smart-canvas.html"


class HypitSettingsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.styles = STYLES.read_text(encoding="utf-8")
        cls.page = PAGE.read_text(encoding="utf-8")

    def test_hypit_navigation_keeps_sidebar_and_handles_section_route(self):
        self.assertIn("new URLSearchParams(location.search).get('section') === 'hypit'", self.script)
        self.assertIn("document.getElementById('canvasModelSettingsBlock')", self.script)
        self.assertIn("handleHypitNavigationCapture", self.script)
        self.assertIn("document.addEventListener('click', handleHypitNavigationCapture, true)", self.script)
        self.assertIn("#canvasModelSettingsBlock", self.styles)
        self.assertNotIn(".layout.hypit-settings-mode .provider-list", self.styles)
        self.assertNotIn(".layout.hypit-settings-mode .cli-quick-group", self.styles)

    def test_hypit_loads_the_shared_model_control_before_mounting(self):
        self.assertIn("/static/js/model-config-core.js", self.page)
        self.assertIn("/static/js/model-config-control.js", self.page)
        self.assertIn("/static/css/model-config-control.css", self.page)
        self.assertIn("data-hypit-slot=\"${escapeHtml(slot)}\"", self.script)

    def test_hypit_canvas_description_explains_shared_flow_in_both_languages(self):
        self.assertIn('hypit.canvasDescription', self.script)
        self.assertIn('在画布中配置生成流程，将执行节点连接到对应输出端口。', self.script)
        self.assertIn('Configure generation flows on the canvas and connect execution nodes to their matching output ports.', self.script)
        self.assertIn('在画布中配置生成流程，将执行节点连接到对应输出端口。', self.page)
        self.assertNotIn('连接完整流程后可测试', self.script + self.page)

    def test_canvas_output_button_has_current_initial_bilingual_labels(self):
        canvas_page = CANVAS_PAGE.read_text(encoding="utf-8")
        self.assertIn('aria-label="添加输出端口"', canvas_page)
        self.assertIn('data-hypit-label-en="Add output port"', canvas_page)
        self.assertIn('aria-label="Hypit 输出端口"', canvas_page)
        self.assertIn('data-hypit-aria-label-en="Hypit output ports"', canvas_page)
        self.assertNotIn("添加用途输出", canvas_page)
        self.assertNotIn("Hypit 用途输出", canvas_page)

    def test_shared_canvas_prefetch_is_cached_and_legacy_save_is_inert(self):
        node = __import__("shutil").which("node")
        if not node:
            self.skipTest("node is required for the frontend behavior fixture")
        fixture = r'''const fs = require('fs');
const source = fs.readFileSync('static/js/hypit-settings.js', 'utf8');
const controllerSource = fs.readFileSync('static/js/settings-canvas-controller.js', 'utf8');
const listeners = Object.create(null);
const requests = [];
const layout = {classList:{contains:()=>false,add(){},remove(){}}};
const elements = new Map();
const document = {
  getElementById(id) {
    if (id === 'hypitSlots') return null;
    if (id === 'hypitSettingsCanvasFrame') {
      if (!elements.has(id)) elements.set(id, {src:'',contentWindow:{postMessage(){}},getAttribute(){return this.src||null;},addEventListener(){},removeEventListener(){},setAttribute(){},removeAttribute(){}});
      return elements.get(id);
    }
    return elements.get(id) || null;
  },
  querySelector(selector) { return selector === '.layout' ? layout : null; },
  querySelectorAll() { return []; },
  addEventListener(type, handler) { (listeners[type] ||= []).push(handler); },
};
global.document = document;
global.location = {href:'http://127.0.0.1/static/api-settings.html', origin:'http://127.0.0.1'};
global.window = {
  location:{search:'?section=hypit'},
  addEventListener(type, handler) { (listeners[type] ||= []).push(handler); },
  StudioI18n:{register(){},apply(){},t:key=>key,lang:()=> 'zh'},
  refreshIcons(){},
};
eval(controllerSource);
global.fetch = async (url, options={}) => {
  requests.push({url,method:options.method||'GET'});
  if (url === '/api/hypit/settings-canvas') return {ok:true,json:async()=>({id:'hypit-settings',canvas:{id:'hypit-settings'},url:'/static/smart-canvas.html?id=hypit-settings&mode=hypit-settings'})};
  throw new Error('unexpected legacy/config request: ' + url);
};
eval(source);
(async()=>{
  const [first, second] = await Promise.all([window.prefetchHypitSettings(), window.prefetchHypitSettings()]);
  const third = await window.prefetchHypitSettings();
  const save = await window.saveHypitSettings();
  if (!first || !second || !third) throw new Error('settings-canvas bootstrap prefetch failed');
  if (save !== false) throw new Error('legacy save must be inert when the six-slot form is absent');
  if (requests.length !== 1 || requests[0].url !== '/api/hypit/settings-canvas' || requests[0].method !== 'GET') throw new Error('shared canvas bootstrap must be one cached GET: ' + JSON.stringify(requests));
  if (document.getElementById('hypitSlots') !== null) throw new Error('fixture must match the shipped page without legacy six-slot markup');
  process.stdout.write(JSON.stringify({requests,legacySave:save,legacySlotsMounted:false}));
})().catch(error=>{console.error(error.stack||error);process.exit(1);});
'''
        completed = subprocess.run(
            [node, "-e", fixture],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["requests"], [{"url":"/api/hypit/settings-canvas","method":"GET"}])
        self.assertFalse(result["legacySlotsMounted"])
        self.assertIs(result["legacySave"], False)


if __name__ == "__main__":
    unittest.main()
