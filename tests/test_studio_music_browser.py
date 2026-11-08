"""音乐创作前端与受管媒体/动态字段路径的隔离真实浏览器回归。"""
from __future__ import annotations

import base64
import copy
import io
import json
import math
import struct
import sys
import threading
import time
import unittest
import wave
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import test_studio_brand_browser as _brand  # noqa: E402

PROJECT_ID = "music-browser-fixture"
LYRICS = "雨落在窗台\n灯火照着归途"
STYLE = "Warm piano, restrained strings, slow tempo"


def wave_fixture() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        samples = bytearray()
        for index in range(16000):
            value = int(1800 * math.sin(2 * math.pi * 440 * index / 8000))
            samples.extend(struct.pack("<h", value))
        audio.writeframes(bytes(samples))
    return output.getvalue()


def midi_fixture() -> bytes:
    track = bytes([
        0x00, 0x90, 60, 100,        # note on, C4
        0x83, 0x60, 0x80, 60, 64,  # note off after 480 ticks
        0x00, 0xFF, 0x2F, 0x00,    # end of track
    ])
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", len(track)) + track


@unittest.skipUnless(_brand.CHROME and _brand.NODE, "需要本机 Chrome/Chromium 和 Node.js 执行隔离浏览器回归")
class StudioMusicBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _brand.StudioBrandBrowserTests.setUpClass()
        cls.browser = _brand.StudioBrandBrowserTests("test_shared_brand_theme_and_interaction_states_across_product_pages")
        cls.lock = threading.Lock()
        cls.wav = wave_fixture()
        cls.midi = midi_fixture()
        cls.project = None
        cls.canvas = None
        cls.projection = None
        cls.puts = []
        cls.posts = []
        cls.unexpected_posts = []
        cls.generations = []
        cls.preparation_calls = []
        cls.project_list_calls = []
        cls.api_requests = []

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT), **kwargs)

            def log_message(self, *_args):
                pass

            def json(self, status, payload):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    pass

            def binary(self, content_type, body):
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    pass

            def read_json(self):
                length = int(self.headers.get("Content-Length", "0"))
                return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

            def do_GET(self):
                parsed = urlsplit(self.path)
                path = parsed.path
                query = parse_qs(parsed.query)
                if path.startswith('/api/'):
                    with cls.lock:
                        cls.api_requests.append(("GET", path))
                if path == "/fixture/reset.html":
                    body = b"<!doctype html><meta charset='utf-8'><title>ready</title>"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/api/studio/projects":
                    with cls.lock:
                        cls.project_list_calls.append(query.get("module", [""])[0])
                    self.json(200, {"projects": [{"id": PROJECT_ID, "module": "music", "name": "雨落归途", "revision": 7, "updated_at": 1791312345}]})
                    return
                if path == "/api/studio/modules/music/preparation":
                    language = "en" if query.get("lang", ["zh"])[0].startswith("en") else "zh"
                    document = f"http://127.0.0.1:{cls.port}/api/studio/modules/music/preparation.md?lang={language}"
                    with cls.lock:
                        cls.preparation_calls.append({"module": "music", "lang": language, "method": "GET"})
                    text = (f"我准备使用老胡画梦枋的音乐模块。请读取技能准备文档：{document}\n只在后续明确要求创作时查找适用能力；不自动创作或生成。"
                            if language == "zh" else f"I plan to use the music module. Read the preparation guide: {document}\nDiscover a suitable capability only after an explicit creative request; do not create or generate automatically.")
                    self.json(200, {"module": "music", "optional": True, "text": text, "document_url": document})
                    return
                if path == f"/api/studio/music/{PROJECT_ID}":
                    with cls.lock:
                        self.json(200, copy.deepcopy(cls.project))
                    return
                if path == f"/api/studio/music/{PROJECT_ID}/generations":
                    with cls.lock:
                        self.json(200, {"generations": copy.deepcopy(cls.generations)})
                    return
                if path == f"/api/studio/music/{PROJECT_ID}/generations/music-run-fixture":
                    with cls.lock:
                        post = copy.deepcopy(cls.posts[-1]) if cls.posts else {}
                        music = copy.deepcopy(cls.project)
                    self.json(200, {"generation": {"run_id": "music-run-fixture", "client_operation_id": post.get("client_operation_id"), "purpose": post.get("purpose", "song"), "status": "succeeded", "results": [{"url": "/api/results/music-wav", "mime": "audio/wav", "name": "fixture.wav"}], "music_association_error": None}, "music": music})
                    return
                if path == "/api/studio/music/settings-canvas":
                    self.json(200, {"id": "music-settings", "canvas": copy.deepcopy(cls.canvas)})
                    return
                if path == "/api/studio/music/settings-canvas/input-fields":
                    with cls.lock:
                        output_id = query.get("output_node_id", [""])[0]
                        self.assert_output_projection(output_id)
                        self.json(200, copy.deepcopy(cls.projection))
                    return
                if path == "/api/results/music-wav" or path == "/api/results/music-reference":
                    self.binary("audio/wav", cls.wav)
                    return
                if path == "/api/results/music-midi":
                    self.binary("audio/midi", cls.midi)
                    return
                if path == "/api/results/music-abc":
                    self.binary("text/x-abc", b'X:1\nM:4/4\nL:1/32\nQ:1/4=88\nV: Vocal\nV: Ins\nK:G\n% verse\nV: Vocal\n"G"B8d8c8A8|\nV: Ins\nZ|\n')
                    return
                if path == "/api/results/music-xml":
                    data = ("<?xml version='1.0'?><score-partwise><part-list><score-part id='P1'><part-name>Piano</part-name></score-part></part-list><part id='P1'><measure number='1'><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note></measure></part></score-partwise>").encode()
                    self.binary("application/vnd.recordare.musicxml+xml", data)
                    return
                if path == "/api/results/music-bad-xml":
                    self.binary("application/vnd.recordare.musicxml+xml", b"<!DOCTYPE score-partwise [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><score-partwise>&x;</score-partwise>")
                    return
                if path.startswith("/api/"):
                    self.json(404, {"detail": f"fixture route missing: {path}"})
                    return
                super().do_GET()

            def assert_output_projection(self, output_id):
                if output_id not in ("music-output", "cover-output"):
                    self.json(400, {"detail": "unexpected output"})

            def do_PUT(self):
                path = urlsplit(self.path).path
                if path.startswith('/api/'):
                    with cls.lock:
                        cls.api_requests.append(("PUT", path))
                if path == f"/api/studio/music/{PROJECT_ID}":
                    body = self.read_json()
                    with cls.lock:
                        cls.puts.append(copy.deepcopy(body))
                        if body.get("expected_revision") != cls.project["revision"]:
                            self.json(409, {"detail": "revision conflict"})
                            return
                        for key, value in body.items():
                            if key not in ("expected_revision", "project_id", "revision", "updated_at"):
                                cls.project[key] = value
                        cls.project["revision"] += 1
                        cls.project["updated_at"] = 1791312346
                        self.json(200, copy.deepcopy(cls.project))
                    return
                self.json(404, {"detail": "unknown PUT"})

            def do_POST(self):
                path = urlsplit(self.path).path
                if path.startswith('/api/'):
                    with cls.lock:
                        cls.api_requests.append(("POST", path))
                if path == f"/api/studio/music/{PROJECT_ID}/generations":
                    body = self.read_json()
                    with cls.lock:
                        cls.posts.append(copy.deepcopy(body))
                        generation = {"run_id": "music-run-fixture", "client_operation_id": body.get("client_operation_id"), "purpose": body.get("purpose"), "slot": body.get("slot"), "status": "queued", "output_node_id": body.get("output_node_id")}
                        cls.generations = [copy.deepcopy(generation)]
                        if body.get("purpose") == "song":
                            cls.project["audio_variants"].insert(0, {"id": "audio-generated", "result_id": "music-wav", "url": "/api/results/music-wav", "name": "新生成.wav", "mime": "audio/wav", "created_at": 1791312350, "snapshot": {"title": "雨落归途", "lyrics": LYRICS, "style_prompt": STYLE}, "timed_lyrics": []})
                    self.json(200, {"generation": generation})
                    return
                with cls.lock:
                    cls.unexpected_posts.append(path)
                self.json(404, {"detail": "unknown POST"})

            def do_PATCH(self):
                path = urlsplit(self.path).path
                with cls.lock:
                    cls.api_requests.append(("PATCH", path))
                self.json(404, {"detail": "unknown PATCH"})

            def do_DELETE(self):
                path = urlsplit(self.path).path
                with cls.lock:
                    cls.api_requests.append(("DELETE", path))
                self.json(404, {"detail": "unknown DELETE"})

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.cache = ROOT / "cache" / "studio-tests"
        cls.cache.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "server", None):
            cls.server.shutdown()
            cls.server.server_close()
        _brand.StudioBrandBrowserTests.tearDownClass()

    def reset_fixture(self):
        project = {
            "project_id": PROJECT_ID, "revision": 7, "updated_at": 1791312345,
            "title": "雨落归途", "lyrics": LYRICS, "style_prompt": STYLE,
            "notes": "收尾保留钢琴尾音。", "cover_prompt": "夜雨街道上的暖色窗灯，歌曲封面。", "source_sha256": "sha256-fixture",
            "title_candidates": {"title-a": {"title": "雨落归途"}, "title-b": {"title": "雨夜来信"}},
            "selected_title_candidate_id": "title-a", "source_versions": [],
            "field_versions": {"title":[{"id":"t1","number":1,"content":"雨落归途"},{"id":"t2","number":2,"content":"雨夜来信"}], "lyrics":[], "style_prompt":[], "notes":[]}, "selected_score_ref_id":"score-midi",
            "score_refs": [
                {"id":"score-abc","result_id":"music-abc","format":"abc","url":"/api/results/music-abc","name":"score.abc","mime":"text/x-abc"},
                {"id": "score-midi", "result_id": "music-midi", "format": "midi", "url": "/api/results/music-midi", "name": "旋律草稿.mid", "mime": "audio/midi"},
                {"id": "score-xml", "result_id": "music-xml", "format": "musicxml", "url": "/api/results/music-xml", "name": "钢琴谱.musicxml", "mime": "application/vnd.recordare.musicxml+xml"},
                {"id": "score-bad-xml", "result_id": "music-bad-xml", "format": "musicxml", "url": "/api/results/music-bad-xml", "name": "损坏样本.musicxml", "mime": "application/vnd.recordare.musicxml+xml"},
            ],
            "reference_audio_refs": [{"id": "reference-one", "result_id": "music-reference", "url": "/api/results/music-reference", "name": "节奏参考.wav", "mime": "audio/wav"}],
            "cover_variants": [], "audio_variants": [
                {"id": "audio-one", "result_id": "music-wav", "url": "/api/results/music-wav", "name": "第一版.wav", "mime": "audio/wav", "created_at": 1791312300, "snapshot": {"title": "雨落归途", "lyrics": LYRICS, "style_prompt": STYLE}, "timed_lyrics": [{"start": 0, "text": "雨落在窗台"}, {"start": 0.45, "text": "灯火照着归途"}]},
                {"id": "audio-two", "result_id": "music-wav", "url": "/api/results/music-wav", "name": "未同步版.wav", "mime": "audio/wav", "created_at": 1791312200, "snapshot": {"title": "旧标题", "lyrics": "旧版歌词\n保留完整原文", "style_prompt": STYLE}, "timed_lyrics": []},
                {"id": "audio-external", "url": "https://outside.invalid/song.wav", "name": "外部地址.wav", "mime": "audio/wav", "snapshot": {"title": "外部"}},
            ], "selected_cover_variant_id": None, "selected_audio_variant_id": None,
        }
        canvas = {
            "id": "music-settings", "revision": 2,
            "nodes": [
                {"id": "dynamic-music", "type": "smart-ai-app", "title": "AI 应用"},
                {"id": "music-output", "type": "smart-hypit-output", "hypitSlot": "music"},
                {"id": "dynamic-cover", "type": "smart-comfy-workflow", "title": "封面流程"},
                {"id": "cover-output", "type": "smart-hypit-output", "hypitSlot": "image"},
            ],
            "connections": [
                {"from": "dynamic-music", "to": "music-output", "kind": "input"},
                {"from": "dynamic-cover", "to": "cover-output", "kind": "input"},
            ],
        }
        projection = {"canvas_revision": 2, "output_node_id": "music-output", "slot": "music", "nodes": [{
            "node_id": "dynamic-music", "node_type": "smart-ai-app", "title": "歌词音乐工作流",
            "fields": [
                {"targetFieldKey": "prompt_text", "label": "主提示", "kind": "text", "required": True},
                {"targetFieldKey": "lyrics_text", "label": "歌词内容", "kind": "text", "required": True},
                {"targetFieldKey": "style_text", "label": "风格描述", "kind": "text", "required": False},
                {"targetFieldKey": "reference_audio", "label": "音频参考", "kind": "audio", "required": False},
            ],
        }]}
        with self.lock:
            type(self).project = project
            type(self).canvas = canvas
            type(self).projection = projection
            type(self).puts = []
            type(self).posts = []
            type(self).unexpected_posts = []
            type(self).generations = []
            type(self).preparation_calls = []
            type(self).project_list_calls = []
            type(self).api_requests = []

    def open_page(self, width=1440):
        browser = self.browser
        browser.cdp("Network.enable")
        browser.cdp("Network.setCacheDisabled", {"cacheDisabled": True})
        browser.set_viewport(width)
        ready = f"http://127.0.0.1:{self.port}/fixture/reset.html"
        browser.cdp("Page.navigate", {"url": ready})
        browser.wait_for_document(ready)
        browser.evaluate("localStorage.setItem('studio_theme_preference_v1', JSON.stringify({version:1,themeId:'studio-violet',appearance:'light'}));")
        url = f"http://127.0.0.1:{self.port}/static/music.html?id={PROJECT_ID}"
        browser.cdp("Page.navigate", {"url": url})
        browser.wait_for_document(url)
        ready = browser.evaluate("(async()=>{for(let i=0;i<160;i++){if(document.getElementById('musicCurrentTitle')?.value==='雨落归途')return true;await new Promise(r=>setTimeout(r,25));}return false;})()")
        self.assertTrue(ready, browser.evaluate("({title:document.title, status:document.querySelector('#musicStatus')?.textContent,errors:window.__brandBrowserDiagnostics?.errors})"))
        browser.evaluate("StudioI18n?.set?.('zh')")

    def open_project_list(self, module="music"):
        browser = self.browser
        browser.cdp("Network.enable")
        browser.cdp("Network.setCacheDisabled", {"cacheDisabled": True})
        browser.set_viewport(1200)
        ready = f"http://127.0.0.1:{self.port}/fixture/reset.html"
        browser.cdp("Page.navigate", {"url": ready})
        browser.wait_for_document(ready)
        browser.evaluate("localStorage.setItem('studio_theme_preference_v1', JSON.stringify({version:1,themeId:'studio-violet',appearance:'light'}));localStorage.setItem('studio_lang','zh');")
        url = f"http://127.0.0.1:{self.port}/static/{module}-list.html"
        browser.cdp("Page.navigate", {"url": url})
        browser.wait_for_document(url)
        self.assertTrue(self.wait_for("document.querySelector('#studioProjectGrid .studio-project-card')"), browser.evaluate("({title:document.title, heading:document.querySelector('#studioProjectListTitle')?.textContent, errors:window.__brandBrowserDiagnostics?.errors})"))

    def wait_for(self, expression, timeout=8):
        return self.browser.evaluate(f"(async()=>{{const end=Date.now()+{int(timeout*1000)};while(Date.now()<end){{if({expression})return true;await new Promise(r=>setTimeout(r,25));}}return false;}})()")

    def click_real(self, selector):
        self.browser.evaluate(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block:'center'}})")
        rect = self.browser.evaluate(f"(()=>{{const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.left+r.width/2,y:r.top+r.height/2}};}})()")
        self.browser.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": rect["x"], "y": rect["y"]})
        self.browser.cdp("Input.dispatchMouseEvent", {"type": "mousePressed", "x": rect["x"], "y": rect["y"], "button": "left", "clickCount": 1})
        self.browser.cdp("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": rect["x"], "y": rect["y"], "button": "left", "clickCount": 1})

    def test_music_preparation_uses_shared_flow_and_hypit_clone_labels_keep_technical_id(self):
        self.reset_fixture()
        self.open_project_list("music")
        browser = self.browser
        prepare = browser.evaluate("({hidden:document.getElementById('studioPrepareButton').hidden,label:document.getElementById('studioPrepareButton').textContent.trim()})")
        self.assertFalse(prepare["hidden"], prepare)
        self.assertIn("准备创作技能", prepare["label"])
        self.click_real("#studioPrepareButton")
        self.assertTrue(self.wait_for("document.querySelector('#studioConnectionDialog')?.open"))
        zh = browser.evaluate("({title:document.querySelector('#studioConnectionDialog h2').textContent,text:document.querySelector('#studioConnectionDialog textarea').value})")
        self.assertEqual(zh["title"], "准备创作技能")
        self.assertIn("/api/studio/modules/music/preparation.md?lang=zh", zh["text"])
        self.assertIn("不自动创作或生成", zh["text"])
        zh_screenshot = self.cache / "music-preparation-zh.png"
        zh_screenshot.write_bytes(base64.b64decode(browser.cdp("Page.captureScreenshot", {"format":"png"})["data"]))
        browser.evaluate("document.querySelector('#studioConnectionDialog [data-close]').click();StudioI18n.set('en')")
        self.assertIn("Prepare creative skills", browser.evaluate("document.getElementById('studioPrepareButton').textContent"))
        self.click_real("#studioPrepareButton")
        self.assertTrue(self.wait_for("document.querySelector('#studioConnectionDialog')?.open && document.querySelector('#studioConnectionDialog textarea').value.includes('preparation.md?lang=en')"))
        en_screenshot = self.cache / "music-preparation-en.png"
        en_screenshot.write_bytes(base64.b64decode(browser.cdp("Page.captureScreenshot", {"format":"png"})["data"]))
        self.assertEqual(self.preparation_calls, [
            {"module": "music", "lang": "zh", "method": "GET"},
            {"module": "music", "lang": "en", "method": "GET"},
        ])
        self.assertEqual(self.unexpected_posts, [], "准备入口不得自动安装或提交生成任务")

        self.reset_fixture()
        self.open_project_list("hypit")
        self.assertEqual(browser.evaluate("document.body.dataset.studioModule"), "hypit")
        self.assertEqual(browser.evaluate("StudioI18n.t('nav.hypit')"), "视频克隆")
        self.assertEqual(browser.evaluate("document.querySelector('#studioProjectListTitle').textContent"), "视频克隆项目")
        self.assertEqual(browser.evaluate("document.title"), "视频克隆")
        self.assertIn("hypit", self.project_list_calls)
        browser.evaluate("StudioI18n.set('en')")
        self.assertTrue(self.wait_for("document.querySelector('#studioProjectListTitle').textContent === 'Video Cloning projects'"))
        self.assertEqual(browser.evaluate("StudioI18n.t('nav.hypit')"), "Video Cloning")
        self.assertEqual(browser.evaluate("document.body.dataset.studioModule"), "hypit")

        browser.cdp("Page.navigate", {"url":f"http://127.0.0.1:{self.port}/static/api-settings.html"})
        browser.wait_for_document(f"http://127.0.0.1:{self.port}/static/api-settings.html")
        browser.evaluate("StudioI18n.set('zh')")
        self.assertTrue(self.wait_for("document.querySelector('#hypitSettingsNav .provider-name')?.textContent === '视频克隆'"))
        browser.evaluate("StudioI18n.set('en')")
        self.assertTrue(self.wait_for("document.querySelector('#hypitSettingsNav .provider-name')?.textContent === 'Video Cloning'"))

        browser.cdp("Page.navigate", {"url":f"http://127.0.0.1:{self.port}/static/index.html"})
        browser.wait_for_document(f"http://127.0.0.1:{self.port}/static/index.html")
        browser.evaluate("StudioI18n.set('zh')")
        hypit_nav_text = "[...document.querySelectorAll('.nav-item')].find(el=>el.getAttribute('onclick')?.includes(\"'hypit'\"))?.querySelector('.nav-text')?.textContent"
        self.assertTrue(self.wait_for(f"{hypit_nav_text} === '视频克隆'"))
        browser.evaluate("StudioI18n.set('en')")
        self.assertTrue(self.wait_for(f"{hypit_nav_text} === 'Video Cloning'"))
        self.assertTrue(zh_screenshot.is_file() and zh_screenshot.stat().st_size > 1000, str(zh_screenshot))
        self.assertTrue(en_screenshot.is_file() and en_screenshot.stat().st_size > 1000, str(en_screenshot))

    def test_unknown_module_query_is_unavailable_without_project_reads_or_writes(self):
        self.open_project_list("music")
        self.reset_fixture()
        browser = self.browser
        url = f"http://127.0.0.1:{self.port}/static/music-list.html?module=unsupported-module"
        browser.cdp("Page.navigate", {"url":url})
        browser.wait_for_document(url)
        self.assertTrue(self.wait_for("document.querySelector('#studioProjectState strong')?.textContent === '无法打开这个创作模块'"))
        self.assertEqual(browser.evaluate("document.querySelector('#studioProjectState span')?.textContent"), "链接中的模块标识无效。请从主菜单选择模块后再试。")
        self.assertTrue(browser.evaluate("document.querySelector('.studio-project-toolbar-actions').hidden"))
        self.assertTrue(browser.evaluate("document.querySelectorAll('#studioProjectGrid .studio-project-card').length === 0"))
        browser.evaluate("StudioI18n.set('en')")
        self.assertTrue(self.wait_for("document.querySelector('#studioProjectState strong')?.textContent === 'This creative module is unavailable'"))
        self.assertEqual(self.api_requests, [], "未知模块不得读取项目或发起任何 API 写入")
        self.assertEqual(self.project_list_calls, [])
        self.assertEqual(self.posts, [])
        self.assertEqual(self.puts, [])
        self.assertEqual(self.unexpected_posts, [])

    def test_375px_locales_themes_and_safe_candidate_rendering(self):
        self.reset_fixture(); self.open_page(375); browser=self.browser
        for appearance in ('light','dark'):
            browser.evaluate(f"StudioTheme.set({json.dumps(appearance)})")
            for language in ('zh','en'):
                browser.evaluate(f"StudioI18n.set({json.dumps(language)})")
                report=browser.evaluate("({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,editor:document.querySelector('#musicLyrics').tagName,buttons:document.querySelectorAll('[data-copy]').length,generate:!!document.querySelector('#musicGenerateButton'),errors:window.__brandBrowserDiagnostics?.errors})")
                self.assertLessEqual(report['scroll'], report['width'], report)
                self.assertEqual(report['editor'], 'TEXTAREA', report)
                self.assertGreaterEqual(report['buttons'], 3, report)
                self.assertFalse(report['generate'], report)
                image=browser.cdp('Page.captureScreenshot', {'format':'png','fromSurface':True})['data']
                (self.cache/f'music-editable-375-{appearance}-{language}.png').write_bytes(base64.b64decode(image))
        self.open_page(1440)
        image=browser.cdp('Page.captureScreenshot', {'format':'png','fromSurface':True})['data']
        (self.cache/'music-editable-desktop.png').write_bytes(base64.b64decode(image))
        with self.lock:
            type(self).project['field_versions']['title'].append({'id':'xss','number':3,'content':'<img src=x onerror=window.__musicXss=1>'})
        browser.evaluate("document.querySelector('#musicRefreshButton').click()")
        self.assertTrue(self.wait_for("document.querySelector('#musicTitleChoices').textContent.includes('<img src=x')"))
        self.assertFalse(browser.evaluate("window.__musicXss === 1 || !!document.querySelector('#musicTitleChoices img')"))

    def test_real_wav_playback_timeupdate_static_lyrics_and_view_does_not_adopt(self):
        self.reset_fixture()
        self.open_page(375)
        browser = self.browser
        browser.evaluate("window.__musicTimeUpdates=0;document.getElementById('musicAudioElement').addEventListener('timeupdate',()=>window.__musicTimeUpdates++);")
        browser.evaluate("document.querySelector('#musicAudioList details').open=true");self.click_real('[data-audio-action="play"][data-audio-id="audio-one"]')
        playing = self.wait_for("document.getElementById('musicAudioElement').currentTime > 0.65 && window.__musicTimeUpdates >= 2", timeout=6)
        self.assertTrue(playing, browser.evaluate("({time:document.getElementById('musicAudioElement').currentTime, paused:document.getElementById('musicAudioElement').paused, events:window.__musicTimeUpdates, error:document.querySelector('#musicStatus')?.textContent})"))
        browser.evaluate("document.getElementById('musicOpenPlayer').click()")
        self.assertTrue(self.wait_for("document.querySelector('[data-lyric-index=\"1\"]')?.classList.contains('active')"))
        player = browser.evaluate("({open:document.getElementById('musicPlayerDialog').open, lyrics:[...document.querySelectorAll('.music-lyric-line')].map(x=>({text:x.textContent,active:x.classList.contains('active')})),selected:document.querySelector('[data-audio-select=\"audio-one\"]').dataset.selected})")
        self.assertTrue(player["open"], player)
        self.assertEqual(player["lyrics"][-1], {"text": "灯火照着归途", "active": True}, player)
        self.assertEqual(player["selected"], "false", player)
        self.assertEqual(len(self.puts), 0, "试听或打开播放器修改了作品 revision")
        browser.evaluate("document.getElementById('musicPlayerClose').click();document.getElementById('musicAudioElement').pause()")
        browser.evaluate("document.querySelector('[data-audio-action=play][data-audio-id=audio-two]').click()")
        static = browser.evaluate("({note:document.querySelector('.music-lyric-sync-note')?.textContent,source:document.querySelector('.music-static-lyrics')?.textContent,line:document.querySelector('.music-lyric-line')})")
        self.assertTrue(static["note"], static)
        self.assertEqual(static["source"], "旧版歌词\n保留完整原文", static)
        self.assertIsNone(static["line"], static)
        external = browser.evaluate("({disabled:document.querySelector('[data-audio-action=play][data-audio-id=audio-external]').disabled, src:document.getElementById('musicAudioElement').src})")
        self.assertTrue(external["disabled"], external)

    def test_edit_autosave_preserves_draft_across_refresh_and_never_generates(self):
        self.reset_fixture(); self.open_page(); browser=self.browser
        browser.evaluate("localStorage.removeItem('studio_music_draft_v2:music-browser-fixture');document.querySelector('#musicLyrics').focus();document.querySelector('#musicLyrics').value='new lyrics\\n第二行';document.querySelector('#musicLyrics').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#musicRefreshButton').click()")
        self.assertTrue(self.wait_for("document.querySelector('#musicSaveStatus').textContent.includes('已保存')"))
        self.assertEqual(self.project['lyrics'], 'new lyrics\n第二行')
        browser.evaluate("document.querySelector('#musicTabStyle').click()")
        self.assertTrue(self.wait_for("!document.querySelector('#musicPanelStyle').hidden"))
        self.assertEqual(browser.evaluate("document.querySelector('#musicStyle').value"), STYLE)
        self.assertFalse(self.posts)
        self.assertTrue(any(item.get('archive') is False for item in self.puts))
        self.assertTrue(any('lyrics' in item.get('archive_fields',[]) for item in self.puts))

    def test_score_source_is_editable_and_selection_is_independent_of_playback(self):
        self.reset_fixture(); self.open_page(1200); browser=self.browser
        browser.evaluate("document.querySelector('#musicTabScores').click()")
        self.assertTrue(self.wait_for("document.querySelector('.music-piano-roll')"))
        browser.evaluate("document.querySelector('[data-score-id=score-xml]').click()")
        self.assertTrue(self.wait_for("document.querySelector('#musicScoreSource')?.value.includes('score-partwise')"))
        self.assertFalse(browser.evaluate("!!document.querySelector('.music-score-table')"))
        browser.evaluate("document.querySelector('[data-score-id=score-bad-xml]').click()")
        self.assertTrue(self.wait_for("document.querySelector('#musicScoreSource')?.value.includes('DOCTYPE')"))
        self.assertFalse(browser.evaluate("!!document.querySelector('#musicScoreViewer script')"))
        browser.evaluate("document.querySelector('[data-audio-select=audio-one]').click()")
        self.assertTrue(self.wait_for("document.querySelector('[data-audio-select=audio-one][aria-pressed=true]')"))
        self.assertTrue(browser.evaluate("document.querySelector('#musicAudioElement').paused"))
        self.assertFalse(self.posts)

    def test_abc_copies_exact_source_instead_of_note_table(self):
        self.reset_fixture();self.open_page();browser=self.browser
        browser.evaluate("document.querySelector('#musicTabScores').click()")
        self.assertTrue(self.wait_for("!document.querySelector('#musicPanelScores').hidden"))
        browser.evaluate("document.querySelector('[data-score-id=score-abc]').click()")
        self.assertTrue(self.wait_for("document.querySelector('#musicScoreSource')?.value.includes('V: Vocal')"))
        source=browser.evaluate("document.querySelector('#musicScoreSource').value")
        browser.evaluate("window.__copiedMusic=null;Object.defineProperty(navigator.clipboard,'writeText',{configurable:true,value:async value=>{window.__copiedMusic=value}});document.querySelector('[data-copy=musicScoreSource]').click()")
        self.assertTrue(self.wait_for("window.__copiedMusic!==null"))
        self.assertEqual(browser.evaluate("window.__copiedMusic"),source)
        self.assertIn('"G"B8d8c8A8|',source)
        self.assertFalse(browser.evaluate("!!document.querySelector('.music-score-table')"))
        self.assertFalse(self.posts)

    def test_conflicting_refresh_keeps_both_texts_until_explicit_resolution(self):
        self.reset_fixture();self.open_page();browser=self.browser
        browser.evaluate("document.querySelector('#musicLyrics').focus();document.querySelector('#musicLyrics').value='my draft';document.querySelector('#musicLyrics').dispatchEvent(new Event('input',{bubbles:true}))")
        with self.lock:
            type(self).project['lyrics']='remote text';type(self).project['revision']+=1
        browser.evaluate("document.querySelector('#musicRefreshButton').click()")
        self.assertTrue(self.wait_for("document.querySelector('#musicConflictDialog').open"))
        self.assertEqual(browser.evaluate("document.querySelector('#musicLyrics').value"),'my draft')
        self.assertEqual(browser.evaluate("document.querySelector('#musicConflictLatest').value"),'remote text')
        self.assertEqual(self.project['lyrics'],'remote text')
        browser.evaluate("document.querySelector('#musicKeepMine').click()")
        self.assertTrue(self.wait_for("document.querySelector('#musicSaveStatus').textContent==='已保存'"))
        self.assertEqual(self.project['lyrics'],'my draft')


if __name__ == '__main__':
    unittest.main()
