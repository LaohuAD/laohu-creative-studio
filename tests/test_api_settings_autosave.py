"""API 设置导航与自动保存的定向回归测试。"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "static/api-settings.html"
SCRIPT = ROOT / "static/js/api-settings.js"
STYLES = ROOT / "static/css/api-settings.css"
I18N = ROOT / "static/js/i18n/api-settings.js"
NODE = shutil.which("node")


NODE_TEST = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const sourcePath = process.argv[1];
const source = fs.readFileSync(sourcePath, 'utf8');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

function response(body, ok = true) {
    return {
        ok,
        status: ok ? 200 : 500,
        json: async () => body,
        text: async () => JSON.stringify(body),
    };
}

function createHarness() {
    const elements = new Map();
    const makeElement = id => {
        const listeners = {};
        return {
            id,
            textContent: '',
            innerHTML: '',
            value: '',
            checked: false,
            hidden: false,
            disabled: false,
            dataset: {},
            style: {},
            listeners,
            classList: {
                add() {},
                remove() {},
                toggle() {},
                contains() { return false; },
            },
            querySelector() { return null; },
            querySelectorAll() { return []; },
            addEventListener(type, fn) { listeners[type] = fn; },
            dispatchEvent(event) { listeners[event.type]?.(event); },
            setAttribute() {},
            removeAttribute() {},
            getAttribute() { return null; },
            getBoundingClientRect() { return { left: 0, right: 0, top: 0, bottom: 0 }; },
            closest() { return null; },
            contains() { return false; },
            focus() {},
        };
    };
    const document = {
        title: '',
        body: makeElement('body'),
        documentElement: makeElement('documentElement'),
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, makeElement(id));
            return elements.get(id);
        },
        querySelector(selector) {
            if (selector === '.layout') return this.getElementById('layout');
            return null;
        },
        querySelectorAll() { return []; },
        createElement(tag) { return makeElement(tag); },
        addEventListener() {},
    };
    const window = {
        parent: { postMessage() {} },
        top: null,
        addEventListener() {},
        StudioI18n: { t: key => key, lang: () => 'en', apply() {}, set() {} },
        lucide: { createIcons() {} },
    };
    const putCalls = [];
    const pendingPuts = [];
    let putMode = 'resolved';
    const initialProviders = [
        { id: 'alpha', name: 'Alpha', base_url: 'https://alpha.example', protocol: 'openai', enabled: true, image_models: ['image-a'], chat_models: ['chat-a'], video_models: [], audio_models: [], model_names: {} },
        { id: 'beta', name: 'Beta', base_url: 'https://beta.example', protocol: 'openai', enabled: true, image_models: [], chat_models: [], video_models: [], audio_models: [], model_names: {} },
    ];
    const fetch = (url, options = {}) => {
        const method = options.method || 'GET';
        if (method === 'GET' && url === '/api/providers') {
            return Promise.resolve(response({ providers: initialProviders.map(item => ({ ...item })) }));
        }
        if (method === 'GET' && url === '/api/model-capabilities') {
            return Promise.resolve(response({ providers: [] }));
        }
        if (method === 'PUT' && url === '/api/providers') {
            const call = { url, body: JSON.parse(options.body || '{}') };
            putCalls.push(call);
            if (putMode === 'pending') {
                return new Promise(resolve => pendingPuts.push(() => resolve(response({ providers: call.body }))));
            }
            if (putMode === 'failure') return Promise.resolve(response({ detail: 'forced failure' }, false));
            return Promise.resolve(response({ providers: call.body }));
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
        getComputedStyle: () => ({ display: 'none' }),
        Math,
        Date,
        JSON,
        Promise,
    };
    context.globalThis = context;
    vm.createContext(context);
    vm.runInContext(source, context, { filename: sourcePath });
    vm.runInContext(`
        renderEditor = () => {};
        renderProviderList = () => {};
        renderCliProviderList = () => {};
        renderModels = () => {};
        renderMsLoras = () => {};
        renderRunningHubCards = () => {};
        refreshIcons = () => {};
        syncRecommendView = () => {};
        closeRecommendApi = () => {};
        refreshProviderOnboarding = () => {};
        window.__addRunningHubForTest = () => providers.push({
            id: 'runninghub', name: 'RunningHub', base_url: 'https://www.runninghub.ai', protocol: 'runninghub',
            enabled: false, image_models: [], chat_models: [], video_models: [], audio_models: [], model_names: {},
            rh_region: 'global', rh_regions: {
                global: { base_url: 'https://www.runninghub.ai', enabled: false },
                cn: { base_url: 'https://www.runninghub.cn', enabled: false },
            },
        });
    `, context);
    return {
        context,
        document,
        putCalls,
        pendingPuts,
        setPutMode(mode) { putMode = mode; },
        resolveNextPut() {
            const resolve = pendingPuts.shift();
            assert(resolve, 'expected a pending PUT request');
            resolve();
        },
    };
}

async function load(harness) {
    await harness.context.window.onload();
    await wait(30);
}

function input(harness, id, value) {
    const element = harness.document.getElementById(id);
    element.value = value;
    element.dispatchEvent({ type: 'input', target: element });
}

async function testDebouncedTextAutosave() {
    const h = createHarness();
    await load(h);
    input(h, 'nameInput', 'Alpha draft 1');
    input(h, 'nameInput', 'Alpha draft 2');
    assert.strictEqual(h.putCalls.length, 0, 'text edits must be debounced');
    await wait(450);
    assert.strictEqual(h.putCalls.length, 1);
    assert.strictEqual(h.putCalls[0].body.find(item => item.id === 'alpha').name, 'Alpha draft 2');
}

async function testWritesAreSerialAndStaleResponseDoesNotOverwriteNewInput() {
    const h = createHarness();
    await load(h);
    h.setPutMode('pending');
    input(h, 'nameInput', 'first');
    await wait(450);
    assert.strictEqual(h.putCalls.length, 1);
    input(h, 'nameInput', 'second');
    await wait(450);
    assert.strictEqual(h.putCalls.length, 1, 'the second write waits for the first response');
    h.resolveNextPut();
    await wait(40);
    assert.strictEqual(h.putCalls.length, 2);
    assert.strictEqual(h.putCalls[0].body.find(item => item.id === 'alpha').name, 'first');
    assert.strictEqual(h.putCalls[1].body.find(item => item.id === 'alpha').name, 'second');
    assert.strictEqual(h.document.getElementById('nameInput').value, 'second');
    h.resolveNextPut();
    await wait(30);
}

async function testSwitchFlushesOldProviderDraft() {
    const h = createHarness();
    await load(h);
    input(h, 'nameInput', 'Alpha before switch');
    h.context.selectProvider('beta');
    await wait(40);
    assert.strictEqual(h.putCalls.length, 1, 'switching provider flushes the old object');
    assert.strictEqual(h.putCalls[0].body.find(item => item.id === 'alpha').name, 'Alpha before switch');
}

async function testSwitchWithoutDraftDoesNotWriteUnchangedProvider() {
    const h = createHarness();
    await load(h);
    h.context.selectProvider('beta');
    await wait(40);
    assert.strictEqual(h.putCalls.length, 0, 'navigation alone must not save unchanged fields');
}

async function testNewKeyIsNotClearedByOlderResponse() {
    const h = createHarness();
    await load(h);
    h.setPutMode('pending');
    input(h, 'keyInput', 'key-one');
    await wait(450);
    assert.strictEqual(h.putCalls.length, 1);
    input(h, 'keyInput', 'key-two');
    await wait(450);
    assert.strictEqual(h.putCalls.length, 1);
    h.resolveNextPut();
    await wait(40);
    assert.strictEqual(h.putCalls.length, 2);
    assert.strictEqual(h.document.getElementById('keyInput').value, 'key-two', 'an old response must not clear a newer key');
    assert.strictEqual(h.putCalls[1].body.find(item => item.id === 'alpha').api_key, 'key-two');
    h.resolveNextPut();
    await wait(30);
}

    async function testFailureKeepsDraftAndAllowsNextSave() {
        const h = createHarness();
        await load(h);
    h.setPutMode('failure');
    input(h, 'nameInput', 'failed draft');
    await wait(450);
    assert.strictEqual(h.putCalls[0].body.find(item => item.id === 'alpha').name, 'failed draft');
    assert.strictEqual(h.document.getElementById('status').textContent, 'api.autosaveFailed');
    h.setPutMode('resolved');
    input(h, 'nameInput', 'retry draft');
    await wait(450);
    assert.strictEqual(h.putCalls.length, 2);
        assert.strictEqual(h.putCalls[1].body.find(item => item.id === 'alpha').name, 'retry draft');
    }

    async function testRunningHubKeysKeepBothRegionsInSeparatePendingMaps() {
        const h = createHarness();
        await load(h);
        h.context.window.__addRunningHubForTest();
        h.context.selectProvider('runninghub');
        h.setPutMode('pending');
        input(h, 'rhGlobalFreeKeyInput', 'global-key');
        await wait(450);
        assert.strictEqual(h.putCalls.length, 1);
        const first = h.putCalls[0].body.find(item => item.id === 'runninghub');
        assert.strictEqual(first.rh_api_keys.global, 'global-key');
        assert.strictEqual(first.rh_api_keys.cn, undefined);

        input(h, 'rhCnFreeKeyInput', 'cn-key');
        await wait(450);
        assert.strictEqual(h.putCalls.length, 1, 'the second region waits for the first write');
        h.resolveNextPut();
        await wait(40);
        assert.strictEqual(h.putCalls.length, 2);
        const second = h.putCalls[1].body.find(item => item.id === 'runninghub');
        assert.strictEqual(second.rh_api_keys.global, 'global-key');
        assert.strictEqual(second.rh_api_keys.cn, 'cn-key');
        h.resolveNextPut();
        await wait(30);
    }

async function testOlderDebounceCannotRewindAnotherObject() {
    const h = createHarness();
    await load(h);
    input(h, 'nameInput', 'Alpha edited');
    vm.runInContext("providers.find(p => p.id === 'beta').name = 'Beta edited'; scheduleProviderAutosave({providerId:'beta', immediate:true, sync:false});", h.context);
    await wait(450);
    const last = h.putCalls.at(-1).body;
    assert.strictEqual(last.find(p => p.id === 'alpha').name, 'Alpha edited');
    assert.strictEqual(last.find(p => p.id === 'beta').name, 'Beta edited');
}

async function testFailedKeyRemainsAfterNavigation() {
    const h = createHarness();
    await load(h);
    h.setPutMode('failure');
    input(h, 'keyInput', 'fake-unsaved-key');
    await wait(450);
    h.context.selectProvider('beta');
    await wait(30);
    h.context.selectProvider('alpha');
    await wait(30);
    assert.strictEqual(h.document.getElementById('keyInput').value, 'fake-unsaved-key');
}

async function testAppRemovalOnlyChangesItsRegion() {
    const h = createHarness(); await load(h);
    h.context.window.__addRunningHubForTest();
    vm.runInContext(`{
      const p = providers.find(p=>p.id==='runninghub');
      p.rh_regions.global.enabled = p.rh_regions.cn.enabled = true;
      p.rh_regions.global.rh_apps = [{id:'test-shared-app', title:'AI app'}];
      p.rh_regions.cn.rh_apps = [{id:'test-shared-app', title:'CN app'}];
    }`,h.context);
    h.context.selectProvider('runninghub');
    await h.context.removeRhEntry('app',0,'global');
    const saved = h.putCalls.at(-1).body.find(p=>p.id==='runninghub');
    assert.strictEqual(saved.rh_regions.global.rh_apps.length,0);
    assert.strictEqual(saved.rh_regions.cn.rh_apps.length,1);
    assert.strictEqual(saved.rh_regions.cn.rh_apps[0].title,'CN app');
}

(async () => {
    await testAppRemovalOnlyChangesItsRegion();
    await testOlderDebounceCannotRewindAnotherObject();
    await testFailedKeyRemainsAfterNavigation();
    await testDebouncedTextAutosave();
    await testWritesAreSerialAndStaleResponseDoesNotOverwriteNewInput();
    await testSwitchFlushesOldProviderDraft();
    await testSwitchWithoutDraftDoesNotWriteUnchangedProvider();
    await testNewKeyIsNotClearedByOlderResponse();
    await testFailureKeepsDraftAndAllowsNextSave();
    await testRunningHubKeysKeepBothRegionsInSeparatePendingMaps();
})().catch(error => {
    console.error(error.stack || error);
    process.exitCode = 1;
});
"""


class ApiSettingsAutosaveTests(unittest.TestCase):
    def test_navigation_and_manual_actions_match_new_shell(self) -> None:
        html = HTML.read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8")
        styles = STYLES.read_text(encoding="utf-8")
        i18n = I18N.read_text(encoding="utf-8")
        order = [
            html.index('id="canvasModelsNav"'),
            html.index('id="hypitSubnav"'),
            html.index('api-connection-nav'),
            html.index('id="comfyuiSubnav"'),
            html.index('id="localComfyuiNav"'),
            html.index('id="cliProviderList"'),
        ]
        self.assertEqual(order, sorted(order))
        for forbidden in (
            'id="apiSettingsSectionTabs"',
            'api-page-save-btn',
            'onclick="saveKeyOnly()"',
            'onclick="saveRhKeyOnly(',
            'onclick="saveVolcengineAssetKeys()',
            'id="rhWorkflowSaveBtn"',
            'onclick="closeHypitSettings()"',
            'onclick="closeComfyUiSettings()"',
        ):
            self.assertNotIn(forbidden, html)
        self.assertIn('onclick="clearKeyOnly()', html)
        self.assertIn("const HIDDEN_PROVIDER_IDS = new Set(['agnes', 'openai-compatible', 'modelscope', 'volcengine'])", script)
        self.assertIn('HIDDEN_RECOMMENDED_API_IDS', script)
        self.assertNotIn('onboarding-save-btn', html + script)
        self.assertIn('function scheduleProviderAutosave', script)
        self.assertIn('apiAutosavePendingByKey', script)
        self.assertIn('objectId', script)
        self.assertIn('region', script)
        self.assertIn('api.autosaveFailed', script + i18n)
        self.assertIn('.sidebar', styles)
        self.assertIn('overflow-y:auto', styles)

    @unittest.skipUnless(NODE, "Node.js is required for the browser behavior harness")
    def test_api_settings_autosave_node_behaviors(self) -> None:
        completed = subprocess.run(
            [NODE, "-e", NODE_TEST, str(SCRIPT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
