"""ComfyUI 设置页自动保存的 Node 行为回归测试。"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "static/js/comfyui-settings.js"
NODE = shutil.which("node")


NODE_TEST = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const sourcePath = process.argv[1];
const source = fs.readFileSync(sourcePath, 'utf8');

const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const response = (body, ok = true) => ({ ok, json: async () => body });

function createHarness() {
    const elements = new Map();
    const makeElement = id => ({
        id,
        textContent: '',
        innerHTML: '',
        value: '',
        style: {},
        classList: {
            add() {},
            remove() {},
            toggle() {},
            contains() { return false; },
        },
        querySelector() { return null; },
        querySelectorAll() { return []; },
        addEventListener() {},
        getBoundingClientRect() { return { left: 0, right: 0, top: 0, bottom: 0 }; },
        setAttribute() {},
    });
    const document = {
        title: '',
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, makeElement(id));
            return elements.get(id);
        },
        querySelector() { return null; },
        querySelectorAll() { return []; },
        addEventListener() {},
    };
    const window = {
        parent: { postMessage() {} },
        addEventListener() {},
        StudioI18n: { t: key => key, lang: () => 'en', apply() {} },
        lucide: { createIcons() {} },
    };
    const putCalls = [];
    const getCalls = [];
    const pendingPuts = [];
    let putMode = 'resolved';
    const workflows = {
        A: {
            workflow: { '1': { class_type: 'Note', inputs: { text: 'A' } } },
            config: { title: 'A', fields: [] },
            builtin: false,
        },
        B: {
            workflow: { '1': { class_type: 'Note', inputs: { text: 'B' } } },
            config: { title: 'B', fields: [] },
            builtin: false,
        },
    };
    const fetch = (url, options = {}) => {
        const method = options.method || 'GET';
        if (method === 'GET' && url.startsWith('/api/workflows/')) {
            const name = decodeURIComponent(url.slice('/api/workflows/'.length));
            getCalls.push(name);
            return Promise.resolve(response(workflows[name]));
        }
        if (method === 'PUT') {
            const call = { url, body: JSON.parse(options.body || '{}') };
            putCalls.push(call);
            if (putMode === 'pending') {
                return new Promise(resolve => pendingPuts.push(() => resolve(response({ instances: ['old:8188'] }))));
            }
            if (putMode === 'failure') {
                return Promise.resolve(response({ detail: 'forced failure' }, false));
            }
            return Promise.resolve(response({}));
        }
        if (url === '/api/comfyui/instances') {
            return Promise.resolve(response({ instances: ['127.0.0.1:8188'] }));
        }
        if (url === '/api/workflows') {
            return Promise.resolve(response({ workflows: [] }));
        }
        throw new Error(`Unexpected request: ${method} ${url}`);
    };
    const context = {
        console,
        document,
        window,
        fetch,
        BroadcastChannel: class { postMessage() {} },
        StudioDialog: { alert: async () => {}, confirm: async () => true, prompt: async () => null },
        URL,
        FormData,
        setTimeout,
        clearTimeout,
        setInterval,
        clearInterval,
        Math,
        Date,
        JSON,
        Promise,
    };
    context.globalThis = context;
    vm.createContext(context);
    vm.runInContext(source, context, { filename: sourcePath });
    // Avoid rendering concerns; these replacements still exercise the production save functions.
    vm.runInContext(`
        renderList = () => {};
        renderEditor = () => {};
        renderPreview = () => {};
        renderWorkspaceView = () => {};
        refreshIcons = () => {};
        graphFit = () => {};
    `, context);
    return {
        context,
        putCalls,
        getCalls,
        pendingPuts,
        setPutMode(mode) { putMode = mode; },
        resolveNextPut() {
            const resolve = pendingPuts.shift();
            assert(resolve, 'expected a pending PUT request');
            resolve();
        },
    };
}

async function loadWorkflow(harness, name) {
    await harness.context.selectWorkflow(name);
}

async function testWorkflowInputIsDebounced() {
    const h = createHarness();
    await loadWorkflow(h, 'A');
    h.context.updateWorkflowTitle('draft-1');
    h.context.updateWorkflowTitle('draft-2');
    assert.strictEqual(h.putCalls.length, 0, 'text input must not save synchronously');
    await wait(450);
    assert.strictEqual(h.putCalls.length, 1, 'debounced edits should produce one PUT');
    assert.strictEqual(h.putCalls[0].url, '/api/workflows/A/config');
    assert.strictEqual(h.putCalls[0].body.title, 'draft-2');
}

async function testWorkflowWritesAreSerial() {
    const h = createHarness();
    await loadWorkflow(h, 'A');
    h.setPutMode('pending');
    h.context.updateWorkflowTitle('first');
    await wait(450);
    assert.strictEqual(h.putCalls.length, 1);
    h.context.updateWorkflowTitle('second');
    await wait(450);
    assert.strictEqual(h.putCalls.length, 1, 'second write must wait for the first response');
    h.resolveNextPut();
    await wait(30);
    assert.strictEqual(h.putCalls.length, 2);
    assert.strictEqual(h.putCalls[0].body.title, 'first');
    assert.strictEqual(h.putCalls[1].body.title, 'second');
    h.resolveNextPut();
    await wait(30);
}

async function testSwitchFlushesOldDraftBeforeLoadingNewWorkflow() {
    const h = createHarness();
    await loadWorkflow(h, 'A');
    h.context.updateWorkflowTitle('A draft');
    const switchPromise = loadWorkflow(h, 'B');
    await switchPromise;
    assert.strictEqual(h.putCalls.length, 1, 'switching must flush the old workflow draft');
    assert.strictEqual(h.putCalls[0].url, '/api/workflows/A/config');
    assert.strictEqual(h.putCalls[0].body.title, 'A draft');
    assert.deepStrictEqual(h.getCalls, ['A', 'B']);
    assert.ok(!h.putCalls.some(call => call.url === '/api/workflows/B/config' && call.body.title === 'A draft'));
}

async function testComfyBackendInputIsDebounced() {
    const h = createHarness();
    vm.runInContext(`comfyInstances = ['old:8188'];`, h.context);
    h.context.updateComfyInstance(0, 'new:8188');
    assert.strictEqual(h.putCalls.length, 0, 'backend text input must not save synchronously');
    await wait(450);
    assert.strictEqual(h.putCalls.length, 1);
    assert.strictEqual(h.putCalls[0].url, '/api/comfyui/instances');
    assert.deepStrictEqual(h.putCalls[0].body.instances, ['new:8188']);
}

async function testSlowBackendResponseCannotOverwriteNewerDraft() {
    const h = createHarness();
    vm.runInContext(`comfyInstances = ['old:8188'];`, h.context);
    h.setPutMode('pending');
    h.context.updateComfyInstance(0, 'first:8188');
    await wait(450);
    assert.strictEqual(h.putCalls.length, 1);
    h.context.updateComfyInstance(0, '');
    h.resolveNextPut();
    await wait(30);
    assert.strictEqual(JSON.stringify(vm.runInContext('comfyInstances', h.context)), '[""]');
    assert.strictEqual(h.context.document.getElementById('status').textContent, 'comfy.saveFailed');
}

async function testFailedSaveKeepsDraftAndAllowsTheNextSave() {
    const h = createHarness();
    await loadWorkflow(h, 'A');
    h.setPutMode('failure');
    h.context.updateWorkflowTitle('failed draft');
    await wait(450);
    assert.strictEqual(h.putCalls[0].body.title, 'failed draft');
    assert.strictEqual(h.context.document.getElementById('status').textContent, 'comfy.saveFailed');
    h.setPutMode('resolved');
    h.context.updateWorkflowTitle('retry draft');
    await wait(450);
    assert.strictEqual(h.putCalls.length, 2);
    assert.strictEqual(h.putCalls[1].body.title, 'retry draft');
}

async function testFieldSelectionSavesImmediately() {
    const h = createHarness();
    await loadWorkflow(h, 'A');
    vm.runInContext(`
        currentWorkflow = { '1': { class_type: 'Note', inputs: { value: 1 } } };
        currentConfig = { title: 'A', fields: [{ id: 'f1', node: '1', input: 'value', name: 'Value', type: 'text', options: [] }] };
    `, h.context);
    h.context.updateField('f1', 'type', 'number');
    await wait(30);
    assert.strictEqual(h.putCalls.length, 1);
    assert.strictEqual(h.putCalls[0].body.fields[0].type, 'number');
    h.context.updateField('f1', 'random_enabled', true);
    await wait(30);
    assert.strictEqual(h.putCalls.length, 2, 'checkbox changes should save immediately');
    assert.strictEqual(h.putCalls[1].body.fields[0].random_enabled, true);
}

async function testPreviewValueDoesNotAutosave() {
    const h = createHarness();
    await loadWorkflow(h, 'A');
    vm.runInContext(`
        currentConfig = { title: 'A', fields: [{ id: 'f1', node: '1', input: 'text', name: 'Text', type: 'text', default: '' }] };
    `, h.context);
    h.context.setPreviewValue('f1', 'temporary run value');
    await wait(450);
    assert.strictEqual(h.putCalls.length, 0);
}

(async () => {
    await testWorkflowInputIsDebounced();
    await testWorkflowWritesAreSerial();
    await testSwitchFlushesOldDraftBeforeLoadingNewWorkflow();
    await testComfyBackendInputIsDebounced();
    await testSlowBackendResponseCannotOverwriteNewerDraft();
    await testFailedSaveKeepsDraftAndAllowsTheNextSave();
    await testFieldSelectionSavesImmediately();
    await testPreviewValueDoesNotAutosave();
})().catch(error => {
    console.error(error.stack || error);
    process.exitCode = 1;
});
"""


class ComfyUiAutosaveTests(unittest.TestCase):
    @unittest.skipUnless(NODE, "Node.js is required for the browser behavior harness")
    def test_comfyui_autosave_node_behaviors(self) -> None:
        completed = subprocess.run(
            [NODE, "-e", NODE_TEST, str(SCRIPT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_manual_save_controls_are_removed_without_reloading_after_autosave(self) -> None:
        html = (ROOT / "static/comfyui-settings.html").read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8")
        i18n = (ROOT / "static/js/i18n/comfyui-settings.js").read_text(encoding="utf-8")
        self.assertNotIn('id="saveBtn"', html)
        self.assertNotIn('onclick="onSave()', html)
        self.assertNotIn('saveComfyInstances()', html)
        self.assertNotIn('comfy.saveConfig', html + i18n)
        save_body = script[script.index("async function onSave"):script.index("async function onDelete")]
        self.assertNotIn("loadList()", save_body)
