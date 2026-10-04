import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "static/js/hypit-settings.js"
STYLES = ROOT / "static/css/hypit-settings.css"
PAGE = ROOT / "static/api-settings.html"


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

    def test_autosave_race_keeps_latest_draft_and_server_revision(self):
        node = __import__("shutil").which("node")
        if not node:
            self.skipTest("node is required for the frontend behavior fixture")
        fixture = r'''
const fs = require('fs');
const source = fs.readFileSync('static/js/hypit-settings.js', 'utf8');
const listeners = Object.create(null);
const slotsListeners = Object.create(null);
const elements = Object.create(null);
function classList() {
  const values = new Set();
  return {
    add: (...items) => items.forEach(item => values.add(item)),
    remove: (...items) => items.forEach(item => values.delete(item)),
    contains: item => values.has(item),
    toggle: (item, force) => force === undefined ? (values.has(item) ? values.delete(item) : values.add(item)) : (force ? values.add(item) : values.delete(item)),
  };
}
function element(id) {
  if (!elements[id]) elements[id] = {
    id, hidden: false, dataset: {}, classList: classList(),
    addEventListener: (type, handler) => { (id === 'hypitSlots' ? slotsListeners : listeners)[type] = handler; },
    setAttribute: function(key, value) { this[key] = value; },
    removeAttribute: function(key) { delete this[key]; },
    querySelector: () => null,
    querySelectorAll: () => [],
    closest: () => null,
    matches: () => false,
  };
  return elements[id];
}
const runningHubModel = {
  provider_id:'runninghub', provider_name:'RunningHub', model_id:'shared-image', family_id:'shared-image-family',
  node_type:'image_generation', runnable:true, validation_mode:'strict', readiness:'ready',
  regions:['global','cn'], parameters:{count:{type:'integer',min:1,max:2}}, inputs:{prompt:{media_type:'text',min:1,max:1}}
};
const defaults = {text:{provider:'',model:'',parameters:{}},image:{provider:'runninghub',model:'shared-image',region:'global',parameters:{}},video:{provider:'',model:'',parameters:{}},audio:{provider:'',model:'',parameters:{}},voice:{provider:'',model:'',parameters:{}}};
const pending = [];
const puts = [];
let revision = 1;
global.window = {
  location: {search: '?section=hypit'},
  addEventListener: (type, handler) => { (listeners[type] ||= []).push(handler); },
  StudioI18n: {register(){}, apply(){}, t:key => key, lang:() => 'zh'},
  refreshIcons: () => {},
};
global.location = global.window.location;
global.document = {
  getElementById: id => element(id),
  querySelector: selector => selector === '.layout' ? element('layout') : element(selector.slice(1)),
  querySelectorAll: () => [],
  addEventListener: (type, handler, capture) => { listeners[`document:${type}:${capture}`] = handler; },
};
global.fetch = async (url, options = {}) => {
  if (options.method === 'PUT') {
    const body = JSON.parse(options.body);
    puts.push(body);
    return await new Promise(resolve => pending.push({body, resolve}));
  }
  if (url.endsWith('/capabilities')) return {ok:true, json:async() => ({
    providers:[{id:'runninghub',name:'RunningHub',regions:[{region:'global',enabled:true},{region:'cn',enabled:true}]}],
    supported_capabilities:[{slot:'image',kind:'image',models:[runningHubModel]}], unsupported_capabilities:[]
  })};
  return {ok:true, json:async() => ({version:1, defaults, revision})};
};
eval(source);
const fire = (type, target) => slotsListeners[type]({target});
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
  await Promise.all((listeners.load || []).map(handler => handler()));
  await wait(0);
  const candidateLabels = window.hypitSlotCandidates('image').map(item => item.label);
  if (!candidateLabels.some(label => label.includes('AI')) || !candidateLabels.some(label => label.includes('CN'))) throw new Error('both RunningHub sites were not offered: ' + JSON.stringify(candidateLabels));
  if (!window.hypitSlotCandidates('image').some(item => item.region === 'cn')) throw new Error('cn 站点候选缺失');
  const otherNav = {id:'canvasModelsNav', closest: selector => selector === '#hypitSettingsNav' ? null : otherNav};
  let prevented = false;
  let stopped = false;
  listeners['document:click:true']({target: otherNav, preventDefault: () => { prevented = true; }, stopPropagation: () => { stopped = true; }});
  if (element('layout').classList.contains('hypit-settings-mode') || !element('hypitSettingsBlock').hidden || prevented || stopped) throw new Error('other sidebar navigation did not close Hypit without swallowing the click');
  const target = {
    dataset: {hypitSlot:'image', hypitParameter:'count'},
    type: 'number', value: '1',
    matches: selector => selector === '[data-hypit-parameter]',
  };
  fire('input', target);
  const firstSave = window.saveHypitSettings();
  await wait(0);
  if (puts.length !== 1 || puts[0].defaults.image.parameters.count !== 1 || puts[0].expected_revision !== 1) throw new Error('first save was not captured');
  target.value = '2';
  fire('input', target);
  pending[0].resolve({ok:true, json:async() => ({version:1, defaults:JSON.parse(JSON.stringify(defaults)), revision:2})});
  await firstSave;
  for (let index = 0; index < 50 && puts.length < 2; index += 1) await wait(10);
  if (puts.length !== 2) throw new Error('latest draft was not queued');
  if (puts[1].defaults.image.parameters.count !== 2 || puts[1].expected_revision !== 2) throw new Error(JSON.stringify(puts));
  pending[1].resolve({ok:true, json:async() => ({version:1, defaults:JSON.parse(JSON.stringify(defaults)), revision:3})});
  await wait(20);
  process.stdout.write(JSON.stringify({puts, status: element('hypitSettingsStatus').textContent}));
})().catch(error => { console.error(error.stack || error); process.exit(1); });
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
        self.assertEqual(len(result["puts"]), 2)
        self.assertEqual(result["puts"][1]["defaults"]["image"]["parameters"]["count"], 2)
        self.assertEqual(result["puts"][1]["expected_revision"], 2)


if __name__ == "__main__":
    unittest.main()
