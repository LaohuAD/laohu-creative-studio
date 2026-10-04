"""画布 Enter 运行/保存的浏览器事件回归，不提交真实生成或保存请求。"""
import json
import unittest
from pathlib import Path

from tests import test_hypit_slot_candidates_browser as browser

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(browser.CHROME, '本机没有可用 Chrome')
class CanvasInputShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        browser.HypitSlotCandidateBrowserTests.setUpClass()
        cls.page = browser.HypitSlotCandidateBrowserTests()
        source = (ROOT / 'static/js/smart-canvas.js').read_text()
        helper = source[source.index('const SMART_TEXT_EDITABLE_SELECTOR'):source.index('function canvasEditableRootDescriptor')]
        handler = source[source.index('function canvasInputEnterAction'):source.index("promptInput.addEventListener('keydown'", source.index('function canvasInputEnterAction'))]
        cls.page.evaluate('''
            document.body.innerHTML = `<div id="composer" class="open" data-smart-node-id="n1">
              <div id="promptInput" contenteditable="true"></div>
              <textarea id="parameter"></textarea><input type="number" id="numeric">
              <input type="search" id="search"><button id="runBtn"></button>
            </div><div id="smartTextEditorModal" class="open">
              <textarea id="material" data-text-editor-input></textarea>
              <textarea id="notes" data-creation-notes></textarea><button data-text-editor-save></button>
            </div><textarea id="unrelated"></textarea>`;
            var nodes = [{id:'n1',type:'image'}];
            var runBtn = document.getElementById('runBtn');
            var counts = {run:0,save:0,change:0};
            var busy = false;
            function selectedNode(){return nodes[0];}
            function isSmartRunnableNode(node){return ['text','image','video','audio','music','app','comfy'].includes(node?.type);}
            function smartNodeInFlight(){return busy;}
            function smartCascadeIsLoopRunning(){return false;}
            runBtn.onclick = () => counts.run++;
            document.querySelector('[data-text-editor-save]').onclick = () => counts.save++;
            document.getElementById('parameter').onchange = () => counts.change++;
            function press(id, options={}){
              const input=document.getElementById(id);
              input.focus();
              const event=new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true,...options});
              input.dispatchEvent(event);
              return {prevented:event.defaultPrevented,...counts};
            }
        ''' + helper + handler)

    @classmethod
    def tearDownClass(cls):
        browser.HypitSlotCandidateBrowserTests.tearDownClass()

    def setUp(self):
        self.page.evaluate("counts={run:0,save:0,change:0}; busy=false; runBtn.disabled=false; nodes[0].type='image'; document.getElementById('parameter').readOnly=false;")

    def test_all_generation_node_inputs_run_and_commit_parameters(self):
        for kind in ('text', 'image', 'video', 'audio', 'music', 'app', 'comfy'):
            with self.subTest(kind=kind):
                result = self.page.evaluate(f"counts={{run:0,save:0,change:0}}; nodes[0].type={json.dumps(kind)}; press('parameter');")
                self.assertEqual(result, {'prevented':True, 'run':1, 'save':0, 'change':1})
        result = self.page.evaluate("press('promptInput');")
        self.assertEqual(result['run'], 2)

    def test_text_material_and_notes_save_instead_of_running(self):
        self.assertEqual(self.page.evaluate("press('material');")['save'], 1)
        self.assertEqual(self.page.evaluate("press('notes');")['save'], 2)
        self.assertEqual(self.page.evaluate('counts.run'), 0)

    def test_shift_enter_and_input_method_confirmation_are_not_submitted(self):
        for field in ('promptInput', 'parameter', 'material', 'notes'):
            for options in ({'shiftKey':True}, {'isComposing':True}, {'keyCode':229}, {'ctrlKey':True}, {'metaKey':True}):
                with self.subTest(field=field, options=options):
                    result = self.page.evaluate(f'press({json.dumps(field)}, {json.dumps(options)});')
                    self.assertFalse(result['prevented'])
                    self.assertEqual(result['run'] + result['save'], 0)

    def test_busy_disabled_repeat_search_and_unrelated_inputs_do_not_run(self):
        self.page.evaluate("press('promptInput',{repeat:true}); busy=true; press('parameter'); busy=false; runBtn.disabled=true; press('numeric'); runBtn.disabled=false; press('search'); press('unrelated'); document.getElementById('parameter').readOnly=true; press('parameter');")
        self.assertEqual(self.page.evaluate('counts.run'), 0)

    def test_help_describes_both_actions_and_newlines_in_both_languages(self):
        html = (ROOT / 'static/smart-canvas.html').read_text()
        i18n = (ROOT / 'static/js/i18n/smart-canvas.js').read_text()
        for key in ('smart.shortcutInputRun', 'smart.shortcutInputSave', 'smart.shortcutInputNewline'):
            self.assertIn(f'data-i18n="{key}"', html)
            line = next(line for line in i18n.splitlines() if f'"{key}"' in line)
            self.assertIn('zh:', line)
            self.assertIn('en:', line)
