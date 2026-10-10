"""Shared settings-canvas iframe lifecycle regression tests."""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


NODE_TEST = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('static/js/settings-canvas-controller.js', 'utf8');
const calls = [];
const pending = new Map();
const payload = (id, url = `/static/smart-canvas.html?id=${id}&mode=${id}`) => ({id, canvas:{id}, url});

function response(body, ok = true, status = 200) {
  return {ok, status, json:async()=>body};
}

function fetch(url) {
  calls.push(url);
  const queue = pending.get(url);
  if (queue?.length) return queue.shift()();
  const id = url.includes('/article/') ? 'article-settings' :
    url.includes('/music/') ? 'music-settings' : 'canvas-settings';
  return Promise.resolve(response(payload(id)));
}

class FakeFrame {
  constructor() {
    this.attrs = new Map();
    this.listeners = new Map();
    this.autoLoad = true;
    this.contentWindow = {messages:[], postMessage(message, origin) { this.messages.push({message, origin}); }};
  }
  get src() { return this.attrs.get('src') || ''; }
  set src(value) {
    this.attrs.set('src', value);
    if (this.autoLoad) queueMicrotask(() => this.emit('load'));
  }
  getAttribute(name) { return this.attrs.get(name) ?? null; }
  setAttribute(name, value) { this.attrs.set(name, String(value)); }
  removeAttribute(name) { this.attrs.delete(name); }
  addEventListener(type, callback, options = {}) {
    const items = this.listeners.get(type) || [];
    items.push({callback, once:options.once === true});
    this.listeners.set(type, items);
  }
  removeEventListener(type, callback) {
    this.listeners.set(type, (this.listeners.get(type) || []).filter(item => item.callback !== callback));
  }
  emit(type) {
    const items = [...(this.listeners.get(type) || [])];
    for (const item of items) {
      item.callback({type});
      if (item.once) this.removeEventListener(type, item.callback);
    }
  }
}

const window = {
  StudioTheme:{getPreference:()=> 'dark'},
  StudioI18n:{lang:()=> 'en'},
};
const context = {
  window, location:{href:'https://studio.test/static/api-settings.html',origin:'https://studio.test'},
  fetch, URL, Promise, setTimeout, clearTimeout, queueMicrotask, console,
};
context.globalThis = context;
vm.runInNewContext(source, context, {filename:'settings-canvas-controller.js'});
const create = window.StudioSettingsCanvasController.create;

function make(id, endpoint, status = []) {
  const frame = new FakeFrame();
  const controller = create({
    id, mode:id, endpoint, frame, timeoutMs:100,
    onLoading:()=>status.push('loading'), onReady:()=>status.push('ready'),
    onError:error=>status.push(`error:${error.message}`),
  });
  return {frame, controller, status};
}

async function eventually(predicate, message) {
  for (let i=0;i<100;i++) {
    if (predicate()) return;
    await new Promise(resolve=>setTimeout(resolve, 2));
  }
  assert.fail(message);
}

async function testBootstrapCoalescesRequestsAndValidatesIdentity() {
  calls.length = 0;
  assert.throws(() => make('experimental-settings', '/api/experimental/settings-canvas'), /identity/);
  const entry = make('article-settings', '/api/article/settings-canvas');
  const [a,b] = await Promise.all([
    entry.controller.loadBootstrap(), entry.controller.loadBootstrap(),
  ]);
  assert.strictEqual(a, b);
  assert.deepStrictEqual(calls, ['/api/article/settings-canvas']);
  assert.throws(() => entry.controller.canvasUrl(payload('article-settings',
    'https://elsewhere.test/static/smart-canvas.html?id=article-settings&mode=article-settings')));
  assert.throws(() => entry.controller.canvasUrl(payload('article-settings',
    '/static/smart-canvas.html?id=music-settings&mode=article-settings')));
  assert.throws(() => entry.controller.canvasUrl(payload('article-settings',
    '/static/smart-canvas.html?id=article-settings&id=article-settings&mode=article-settings')));
}

async function testOldModuleResponseCannotMountAfterSwitch() {
  calls.length = 0;
  let resolveOld;
  pending.set('/api/article/settings-canvas', [() => new Promise(resolve=>{resolveOld=resolve;})]);
  const article = make('article-settings', '/api/article/settings-canvas');
  const music = make('music-settings', '/api/music/settings-canvas');
  article.controller.activate();
  const oldLoad = article.controller.load();
  await eventually(()=>typeof resolveOld === 'function', 'article request did not start');
  article.controller.deactivate();
  music.controller.activate();
  assert.strictEqual(await music.controller.load(), true);
  resolveOld(response(payload('article-settings')));
  assert.strictEqual(await oldLoad, false);
  assert.strictEqual(article.frame.getAttribute('src'), null, 'stale response must not mount the hidden module iframe');
  assert.deepStrictEqual(article.status, ['loading'], 'stale response must not replace the current module status');
  assert.deepStrictEqual(music.status, ['loading','ready']);
}

async function testFailedLoadCanRetryAndContextFollowsCurrentLanguageTheme() {
  const url = '/api/canvas/settings-canvas';
  pending.set(url, [
    () => Promise.resolve(response(payload('canvas-settings', '/static/smart-canvas.html?id=canvas-settings&mode=hypit-settings'))),
    () => Promise.resolve(response(payload('canvas-settings'))),
  ]);
  const entry = make('canvas-settings', url);
  entry.controller.activate();
  assert.strictEqual(await entry.controller.load(), false);
  assert.match(entry.status.at(-1), /^error:/);
  assert.strictEqual(entry.frame.getAttribute('hidden'), 'hidden');
  assert.strictEqual(await entry.controller.load({force:true}), true);
  assert.strictEqual(entry.status.at(-1), 'ready');
  const afterLoad = entry.frame.contentWindow.messages.length;
  assert.strictEqual(afterLoad, 2);
  window.StudioTheme.getPreference = () => 'light';
  window.StudioI18n.lang = () => 'zh';
  assert.strictEqual(entry.controller.syncContext(), true);
  const messages = entry.frame.contentWindow.messages;
  assert.deepStrictEqual(messages.map(item=>item.message.type), ['studio-theme','studio-lang','studio-theme','studio-lang']);
  assert.deepStrictEqual(messages.map(item=>item.origin), Array(4).fill('https://studio.test'));
  assert.strictEqual(messages[0].message.preference, 'dark');
  assert.strictEqual(messages[1].message.lang, 'en');
  assert.strictEqual(messages[2].message.preference, 'light');
  assert.strictEqual(messages[3].message.lang, 'zh');
  entry.controller.deactivate();
  assert.strictEqual(entry.controller.syncContext(), false, 'hidden modules do not receive stale theme/language messages');
  assert.strictEqual(messages.length, 4);
}

async function testFrameTimeoutCanRetryTheSameCanvas() {
  const entry = make('article-settings', '/api/article/settings-canvas');
  entry.frame.autoLoad = false;
  entry.controller.activate();
  assert.strictEqual(await entry.controller.load(), false);
  assert.strictEqual(entry.status.at(-1), 'error:Canvas load timed out.');
  assert.strictEqual(entry.frame.getAttribute('hidden'), 'hidden');
  entry.frame.autoLoad = true;
  assert.strictEqual(await entry.controller.load({force:true}), true);
  assert.strictEqual(entry.status.at(-1), 'ready');
  assert.strictEqual(entry.frame.getAttribute('src'), '/static/smart-canvas.html?id=article-settings&mode=article-settings&embedded=1');
}

(async()=>{
  await testBootstrapCoalescesRequestsAndValidatesIdentity();
  await testOldModuleResponseCannotMountAfterSwitch();
  await testFailedLoadCanRetryAndContextFollowsCurrentLanguageTheme();
  await testFrameTimeoutCanRetryTheSameCanvas();
  process.stdout.write('4 controller lifecycle cases passed\n');
})().catch(error=>{console.error(error.stack||error);process.exit(1);});
"""


@unittest.skipUnless(NODE, "Node.js is required for settings-canvas lifecycle tests")
class SettingsCanvasControllerTests(unittest.TestCase):
    def test_shared_controller_identity_concurrency_switch_retry_and_context(self):
        completed = subprocess.run(
            [NODE, "-e", NODE_TEST], cwd=ROOT, check=False, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("4 controller lifecycle cases passed", completed.stdout)


if __name__ == "__main__":
    unittest.main()
