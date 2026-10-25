"""公众号文章模块的隔离浏览器回归。全部 API 写入仅存在测试进程内。"""
from __future__ import annotations

import json
import hashlib
import base64
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
import unittest
import zlib
from html import unescape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def chrome_binary():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
    ]
    return next((item for item in candidates if item and Path(item).is_file()), None)


CHROME = chrome_binary()
NODE = shutil.which("node")


def visible_cover_png(width=640, height=274):
    """生成带清晰主体的 21:9 隔离封面，验证预览不裁切。"""
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            color = (241, 203, 151)  # 天空
            if (x - 505) ** 2 + (y - 86) ** 2 <= 43 ** 2:
                color = (255, 239, 174)  # 太阳
            if y > 235 - int(70 * (1 - abs(x - 155) / 155)) and x < 310:
                color = (105, 139, 117)  # 远山
            if y > 250 - int(88 * (1 - abs(x - 445) / 195)) and x > 245:
                color = (62, 101, 91)  # 近山
            # 中央珊瑚色小屋，屋顶与主体在 16:9 裁切区内完整可见。
            if 286 <= x <= 378 and 218 <= y <= 302:
                color = (193, 91, 69)
            if 274 <= x <= 390 and 207 <= y <= 230 and abs(x - 332) <= (y - 207) * 2.55:
                color = (126, 70, 62)
            if 325 <= x <= 343 and 260 <= y <= 302:
                color = (246, 218, 168)
            row.extend(color)
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(rows)
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) +
            chunk(b"IEND", b""))


def article_payload(selected="moyu-green"):
    source = "# 隔离样例\n\n正文第一段。\n\n```text\n第一行\n第二行\n```"
    digest = "source-current"
    green_html = "<section style='font-family:serif'><h1>隔离样例</h1><p>正文第一段。</p><picture><source srcset='/api/results/result-fixture-image 2x'><img alt='知识卡图片' src='/api/results/result-fixture-image' srcset='/api/results/result-fixture-image 2x' sizes='100vw' data-src='/api/results/unused-lazy-source'></picture><pre><code>第一行\n第二行</code></pre></section>"
    red_html = "<section style='border-top:3px solid #ad3838'><h1><span>隔离样例</span></h1><table><tbody><tr><td>01</td><td>正文第一段。</td></tr></tbody></table><pre><code>第一行\n第二行</code></pre></section>"
    stale_html = "<section><h1>过期内容不应显示</h1></section>"
    return {
        "article": {
            "project_id": "article-fixture", "title": "隔离文章", "source_markdown": source,
            "source_sha256": digest, "revision": 3, "selected_theme_id": selected,
            "title_variants": {
                "short": {"title": "隔离短标题", "source_sha256": digest, "source_matches": True, "valid": True},
                "long": {"title": "隔离历史标题", "source_sha256": "source-older", "source_matches": False, "valid": True},
                "stale": {"title": "过期标题不应显示", "source_sha256": "source-old", "source_matches": False, "valid": True},
            "alternate": {"title": "同原文备选标题", "source_sha256": "source-alternate-title", "source_matches": True, "valid": True},
            },
            "selected_title_variant_id": "short",
            "cover_variants": [
                {"id":"cover-a","asset_id":"asset-cover-a","result_id":"result-cover-a","source_sha256":digest,"source_matches":True,"valid":True,"url":"/fixture/cover.png","name":"cover.png","mime":"image/png"},
                {"id":"cover-b","asset_id":"asset-cover-b","result_id":"result-cover-b","source_sha256":"source-older","source_matches":False,"valid":True,"url":"/fixture/cover.png","name":"5e87fba7-4dc0-4a91-aaa0-13725c585db6_image_1.png","mime":"image/png"},
            ],
            "selected_cover_variant_id": "cover-a",
            "updated_at": 1791060000,
            "variants": {
                "moyu-green": {
                    "body_html": green_html,
                    "source_sha256": digest, "html_sha256": hashlib.sha256(green_html.encode("utf-8")).hexdigest(), "valid": True,
                },
                "red-white": {
                    "body_html": red_html,
                    "source_sha256": digest, "html_sha256": hashlib.sha256(red_html.encode("utf-8")).hexdigest(), "valid": True,
                },
                "graphite-minimal": {
                    "body_html": stale_html,
                    "source_sha256": "source-old", "html_sha256": hashlib.sha256(stale_html.encode("utf-8")).hexdigest(), "valid": True,
                },
            },
        }
    }


def article_versions_payload(article):
    """Contract-shaped version manifest and snapshots for the isolated article API."""
    title_specs = [
        ("title-v1", 1, "long", "source-older"),
        ("title-v2", 2, "short", article.get("source_sha256", "source-current")),
        ("title-v3", 3, "alternate", article.get("source_sha256", "source-current")),
    ]
    title_versions = []
    details = {}
    for version_id, number, variant_id, digest in title_specs:
        variant = article.get("title_variants", {}).get(variant_id)
        if not variant:
            continue
        title_versions.append({"id": version_id, "number": number, "created_at": None, "source_revision": 1 + number,
                              "origin": "legacy" if number == 1 else "put", "label": variant.get("title", ""),
                              "source_sha256": digest, "active": article.get("selected_title_variant_id") == variant_id,
                              "availability": {"available": True}})
        details["title:" + version_id] = {"project_id": "article-fixture", "current_revision": article["revision"],
            "kind": "title", "id": version_id, "number": number, "created_at": None, "source_revision": 1 + number,
            "origin": "legacy" if number == 1 else "put", "active": article.get("selected_title_variant_id") == variant_id,
            "snapshot": {"title": variant.get("title", ""), "title_variant_id": variant_id, "source_sha256": digest}}

    cover_versions = []
    for index, cover in enumerate(article.get("cover_variants", []), start=1):
        version_id = "cover-v-" + str(cover.get("id", index))
        active = article.get("selected_cover_variant_id") == cover.get("id")
        cover_versions.append({"id": version_id, "number": index, "created_at": None, "source_revision": index,
                               "origin": "legacy" if index == 1 else "generation", "label": cover.get("name", f"Cover {index}"),
                               "source_sha256": cover.get("source_sha256", ""), "active": active,
                               "availability": {"available": bool(cover.get("valid") and cover.get("url"))},
                               "public_media": {"url": cover.get("url", "") if cover.get("valid") else "",
                                                "name": cover.get("name", "") if cover.get("valid") else "",
                                                "mime": cover.get("mime", "") if cover.get("valid") else "",
                                                "available": bool(cover.get("valid") and cover.get("url"))}})
        details["cover:" + version_id] = {"project_id": "article-fixture", "current_revision": article["revision"],
            "kind": "cover", "id": version_id, "number": index, "created_at": None, "source_revision": index,
            "origin": "legacy" if index == 1 else "generation", "active": active,
            "snapshot": {"cover_variant_id": cover.get("id"), "asset_id": cover.get("asset_id"), "result_id": cover.get("result_id"),
                         "source_sha256": cover.get("source_sha256", ""),
                         "public_media": {"url": cover.get("url", ""), "name": cover.get("name", ""), "mime": cover.get("mime", "image/png"),
                                          "available": bool(cover.get("valid") and cover.get("url"))}}}

    body_specs = [
        ("body-v1", 1, "<article><h1>隔离旧稿</h1><p>旧版本正文。</p></article>", "legacy"),
        ("body-v2", 2, article_payload()["article"]["variants"]["moyu-green"]["body_html"], "put"),
    ]
    body_versions = []
    for version_id, number, layout_html, origin in body_specs:
        layout_sha = hashlib.sha256(layout_html.encode()).hexdigest()
        layout_excerpt = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", " ", layout_html))).strip()[:180]
        current_layout = article.get("variants", {}).get("moyu-green", {})
        layout_active = current_layout.get("html_sha256") == layout_sha or current_layout.get("body_html") == layout_html
        body_versions.append({"id": version_id, "number": number, "created_at": None, "source_revision": number,
                              "origin": origin, "label": f"Body {number}", "active": layout_active,
                              "layout_active": layout_active, "layout_available": True,
                              "availability": {"available": True}, "preview_theme_id": "moyu-green",
                              "layout_excerpt": layout_excerpt})
        layouts = [{"theme_id": "moyu-green", "html_sha256": layout_sha,
                    "catalog_fingerprint": "fixture-catalog", "result_id": f"result-body-{number}",
                    "available": True,
                    "body_html": layout_html}]
        details["body:" + version_id] = {"project_id": "article-fixture", "current_revision": article["revision"],
            "kind": "body", "id": version_id, "number": number, "created_at": None, "source_revision": number,
            "origin": origin, "active": layout_active, "layout_active": layout_active,
            "layout_available": True, "preview_theme_id": "moyu-green",
            "snapshot": {"layout_available": True, "layouts": layouts}}

    manifest = {"project_id": "article-fixture", "revision": article["revision"], "streams": [
        {"kind": "title", "title": "标题", "versions": title_versions},
        {"kind": "cover", "title": "封面", "versions": cover_versions},
        {"kind": "body", "title": "正文", "versions": body_versions},
    ]}
    return manifest, details


def article_settings_canvas():
    return {
        "id": "article-settings", "title": "文章生成配置", "icon": "notebook-pen",
        "project": "__article_settings__", "revision": 2, "updated_at": 1791060000,
        "node_schema_version": 9999, "nodes": [], "connections": [], "logs": [],
        "settings": {}, "viewport": {"x": 0, "y": 0, "scale": 1}, "nextNodeNumber": 1,
        "test_statuses": {},
    }


@unittest.skipUnless(CHROME and NODE, "需要本机 Chrome/Chromium 和 Node.js 执行隔离浏览器回归")
class StudioArticleBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = {
            "projects": [], "article": article_payload()["article"], "requests": [],
            "article_restore_conflict_once": False,
            "article_canvas": article_settings_canvas(), "article_canvas_bootstraps": 0,
            "article_canvas_gets": 0, "article_canvas_puts": [], "article_canvas_resets": [],
            "article_model_option_requests": [],
            "article_put_conflict_once": False,
            "article_template_reads": 0,
            "fail_body_image": False,
            "body_image_requests": [],
        }

        class Handler(SimpleHTTPRequestHandler):
            extensions_map = {
                **SimpleHTTPRequestHandler.extensions_map,
                ".html": "text/html; charset=utf-8",
            }

            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT), **kwargs)

            def log_message(self, *_args):
                pass

            def _json(self, status, payload):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urlsplit(self.path)
                path = parsed.path
                query = parse_qs(parsed.query)
                if path == "/clipboard-target":
                    body = b"<!doctype html><meta charset='utf-8'><title>Clipboard paste target</title><div id='clipboard-paste-target' contenteditable='true'></div>"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/api/studio/projects":
                    self._json(200, {"projects": list(cls.fixture["projects"])})
                    return
                if path == "/api/providers":
                    self._json(200, {"providers": []})
                    return
                if path == "/api/model-capabilities":
                    self._json(200, {"schema_version": 1, "providers": [], "options": [], "catalog_revision": "article-fixture"})
                    return
                if path == "/api/studio/articles/settings-canvas":
                    cls.fixture["article_canvas_bootstraps"] += 1
                    self._json(200, {"id": "article-settings", "canvas": cls.fixture["article_canvas"],
                                     "url": "/static/smart-canvas.html?id=article-settings&mode=article-settings"})
                    return
                if path == "/api/canvases/article-settings":
                    cls.fixture["article_canvas_gets"] += 1
                    canvas = json.loads(json.dumps(cls.fixture["article_canvas"], ensure_ascii=False))
                    self._json(200, {"canvas": canvas})
                    return
                if path == "/api/canvases/article-settings/meta":
                    canvas = cls.fixture["article_canvas"]
                    self._json(200, {"id": canvas["id"], "revision": canvas["revision"], "updated_at": canvas["updated_at"]})
                    return
                if path == "/api/studio/model-options":
                    query = parse_qs(parsed.query)
                    module_id = (query.get("module_id") or [""])[0]
                    slot_id = (query.get("slot_id") or [""])[0]
                    cls.fixture["article_model_option_requests"].append((module_id, slot_id))
                    self._json(200, {"module_id": module_id, "slots": [{"id": slot_id}],
                                     "catalog_revision": "article-fixture", "options": []})
                    return
                # 智能画布静态应用只读依赖的隔离响应；未配置任何用户平台或密钥。
                if path == "/api/config":
                    self._json(200, {"api_providers": [], "comfy_instances": []})
                    return
                if path == "/api/model-pricing":
                    self._json(200, {"schema_version": 1, "entries": {}, "unit_definitions": {}})
                    return
                if path == "/api/workflows":
                    self._json(200, {"workflows": []})
                    return
                if path == "/api/prompt-libraries":
                    self._json(200, {"library": {"active_library_id": "system", "libraries": [{"id": "system", "items": [], "categories": []}]}})
                    return
                if path == "/api/smart-canvas/personalization":
                    self._json(200, {"version": 1, "executionLayouts": {}, "parameterOptionOrder": {}, "modelOrder": {}})
                    return
                if path == "/api/asset-library":
                    self._json(200, {"library": {"libraries": []}})
                    return
                if path == "/api/local-assets":
                    self._json(200, {"items": [], "tree": {"id": "__root__", "items": [], "children": []}})
                    return
                if path == "/api/results":
                    self._json(200, {"items": [], "counts": {}})
                    return
                if path == "/api/results/result-fixture-image":
                    cls.fixture["body_image_requests"].append({"path": path, "accept": self.headers.get("Accept", "")})
                    image = visible_cover_png()
                    status = 404 if cls.fixture["fail_body_image"] else 200
                    self.send_response(status)
                    self.send_header("Content-Type", "image/png" if status == 200 else "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(image) if status == 200 else 0))
                    self.end_headers()
                    if status == 200:
                        self.wfile.write(image)
                    return
                if path == "/api/canvases/trash":
                    self._json(200, {"items": []})
                    return
                if path == "/api/canvas-runs":
                    self._json(200, {"runs": []})
                    return
                if path == "/api/studio/articles/templates":
                    cls.fixture["article_template_reads"] += 1
                    self._json(200, {"catalog_fingerprint": "fixture-catalog", "templates": [
                        {"id": "moyu-green", "name": "摸鱼绿", "name_en": "Moyu Green", "color": "#6d9e76", "description": "绿色杂志排版", "description_en": "Green magazine layout", "preview_url": "/static/article-templates/moyu-green.html"},
                        {"id": "red-white", "name": "红白色系", "name_en": "Red and White", "color": "#ad3838", "description": "红白评论排版", "description_en": "Editorial red and white", "preview_url": "/static/article-templates/red-white.html"},
                        {"id": "graphite-minimal", "name": "石墨极简风", "name_en": "Graphite Minimal", "color": "#343434", "description": "石墨极简排版", "description_en": "Graphite minimal layout", "preview_url": "/static/article-templates/graphite-minimal.html"},
                        {"id": "zen-whitespace", "name": "留白禅意风", "name_en": "Zen Whitespace", "color": "#d8d0be", "description": "留白排版", "description_en": "Whitespace layout", "preview_url": "/static/article-templates/zen-whitespace.html"},
                        {"id": "moyu-ticket", "name": "摸鱼票据风", "name_en": "Moyu Ticket", "color": "#d6a744", "description": "票据式排版", "description_en": "Ticket layout", "preview_url": "/static/article-templates/moyu-ticket.html"},
                        {"id": "olive-journal", "name": "橄榄手记", "name_en": "Olive Journal", "color": "#69734a", "description": "手记排版", "description_en": "Journal layout", "preview_url": "/static/article-templates/olive-journal.html"},
                    ]})
                    return
                if path == "/api/studio/articles/article-fixture":
                    cls.fixture["requests"].append({"method": "GET", "path": path})
                    self._json(200, {"article": json.loads(json.dumps(cls.fixture["article"], ensure_ascii=False))})
                    return
                if path == "/api/studio/articles/article-fixture/versions":
                    cls.fixture["requests"].append({"method": "GET", "path": path})
                    manifest, details = article_versions_payload(cls.fixture["article"])
                    cls.fixture["article_version_details"] = details
                    self._json(200, manifest)
                    return
                version_match = __import__('re').fullmatch(r"/api/studio/articles/article-fixture/versions/(title|cover|body)/([^/]+)", path)
                if version_match:
                    cls.fixture["requests"].append({"method": "GET", "path": path})
                    manifest, details = article_versions_payload(cls.fixture["article"])
                    cls.fixture["article_version_details"] = details
                    detail = details.get(version_match.group(1) + ":" + version_match.group(2))
                    self._json(200 if detail else 404, detail or {"detail": "版本不存在"})
                    return
                if path.startswith("/fixture/gallery/"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<!doctype html><title>Safe fixture preview</title><p>Fixture preview only</p>")
                    return
                if path == "/fixture/cover.png":
                    image = visible_cover_png()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(image)))
                    self.end_headers()
                    self.wfile.write(image)
                    return
                if path.startswith("/api/"):
                    self._json(404, {"detail": "隔离文章 fixture 未实现此路由"})
                    return
                super().do_GET()

            def do_POST(self):
                parsed = urlsplit(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                cls.fixture["requests"].append({"method": "POST", "path": parsed.path, "body": body})
                if parsed.path == "/api/studio/projects" and body.get("module") == "article":
                    project = {"id": "article-fixture", "module": "article", "name": body.get("name", ""), "revision": 1, "updated_at": 1791060000, "url": "/static/article.html?id=article-fixture"}
                    cls.fixture["projects"] = [project]
                    self._json(201, {"project": project})
                    return
                restore_match = __import__('re').fullmatch(r"/api/studio/articles/article-fixture/versions/(title|cover|body)/([^/]+)/restore", parsed.path)
                if restore_match:
                    kind, version_id = restore_match.groups()
                    article = cls.fixture["article"]
                    cls.fixture["article_version_restores"].append({"kind": kind, "id": version_id, "body": body})
                    if cls.fixture["article_restore_conflict_once"]:
                        cls.fixture["article_restore_conflict_once"] = False
                        article["revision"] += 1
                        self._json(409, {"detail": {"article": json.loads(json.dumps(article, ensure_ascii=False)), "revision": article["revision"]}})
                        return
                    if int(body.get("expected_revision", -1)) != int(article["revision"]):
                        self._json(409, {"detail": {"article": json.loads(json.dumps(article, ensure_ascii=False)), "revision": article["revision"]}})
                        return
                    _, details = article_versions_payload(article)
                    detail = details.get(kind + ":" + version_id)
                    if not detail:
                        self._json(404, {"detail": "版本不存在"})
                        return
                    snapshot = detail["snapshot"]
                    if kind == "title":
                        title = snapshot["title"]
                        article["title"] = title
                        title_id = snapshot.get("title_variant_id")
                        article["selected_title_variant_id"] = title_id
                        digest = "source-title-" + version_id
                        article["source_sha256"] = digest
                        if title_id in article.get("title_variants", {}):
                            article["title_variants"][title_id].update({"source_sha256": digest, "source_matches": True})
                    elif kind == "cover":
                        article["selected_cover_variant_id"] = snapshot.get("cover_variant_id")
                    else:
                        if body.get("body_view") != "preview":
                            self._json(422, {"detail": "body_view 必须为 preview"})
                            return
                        available = [layout for layout in snapshot.get("layouts", []) if layout.get("available") is True and layout.get("body_html")]
                        if not available:
                            self._json(409, {"detail": "正文排版不可恢复"})
                            return
                        layout = available[0]
                        theme_id = layout.get("theme_id")
                        if not theme_id:
                            self._json(409, {"detail": "正文排版不可恢复"})
                            return
                        existing = article.setdefault("variants", {}).get(theme_id, {})
                        article["variants"][theme_id] = {**existing, "body_html": layout["body_html"],
                            "html_sha256": layout.get("html_sha256", ""), "valid": True}
                        article["selected_theme_id"] = theme_id
                    article["revision"] += 1
                    response_article = json.loads(json.dumps(article, ensure_ascii=False))
                    restored={"kind": kind, "id": version_id}
                    if kind == "body": restored["body_view"] = body.get("body_view", "preview")
                    self._json(200, {"article": response_article, "restored": restored, "revision": article["revision"]})
                    return
                if parsed.path == "/api/studio/articles/settings-canvas/reset":
                    canvas = cls.fixture["article_canvas"]
                    cls.fixture["article_canvas_resets"].append(body)
                    if int(body.get("base_revision", -1)) != int(canvas["revision"]):
                        self._json(409, {"detail": {"message": "画布已由另一标签更新", "canvas": canvas}})
                        return
                    cls.fixture["article_canvas"] = {**canvas, "nodes": [], "connections": [], "logs": [],
                                                       "settings": {}, "viewport": {"x": 0, "y": 0, "scale": 1},
                                                       "revision": canvas["revision"] + 1,
                                                       "updated_at": canvas["updated_at"] + 1}
                    self._json(200, {"id": "article-settings", "canvas": cls.fixture["article_canvas"], "reset": True})
                    return
                self._json(404, {"detail": "隔离文章 fixture 未实现此路由"})

            def do_PUT(self):
                parsed = urlsplit(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                cls.fixture["requests"].append({"method": "PUT", "path": parsed.path, "body": body})
                if parsed.path == "/api/studio/articles/article-fixture":
                    if cls.fixture["article_put_conflict_once"]:
                        cls.fixture["article_put_conflict_once"] = False
                        cls.fixture["article"]["revision"] += 1
                        cls.fixture["article"]["variants"]["red-white"] = {
                            "body_html": "<section><h1>并发更新后的正文</h1><p>远端最新版本。</p></section>",
                            "source_sha256": cls.fixture["article"]["source_sha256"], "valid": True,
                        }
                        self._json(409, {"detail": "文章已更新，请重新读取后再切换版式。"})
                        return
                    if body.get("expected_revision") != cls.fixture["article"]["revision"]:
                        self._json(409, {"detail": "文章已更新，请重新读取后再切换版式。"})
                        return
                    cls.fixture["article"]["revision"] += 1
                    if body.get("selected_title_variant_id") == "alternate":
                        candidate = cls.fixture["article"]["title_variants"]["alternate"]
                        canonical_id = "title-canonical-alternate"
                        cls.fixture["article"]["title"] = candidate["title"]
                        cls.fixture["article"]["source_sha256"] = "source-after-title-selection"
                        cls.fixture["article"]["title_variants"][canonical_id] = {
                            "title": candidate["title"], "source_sha256": "source-after-title-selection",
                            "source_matches": True, "valid": True,
                        }
                        cls.fixture["article"]["selected_title_variant_id"] = canonical_id
                    for field in ("selected_theme_id", "selected_title_variant_id", "selected_cover_variant_id"):
                        if field in body and not (field == "selected_title_variant_id" and body[field] == "alternate"):
                            cls.fixture["article"][field] = body[field]
                    self._json(200, {"article": json.loads(json.dumps(cls.fixture["article"], ensure_ascii=False))})
                    return
                if parsed.path == "/api/canvases/article-settings":
                    canvas = cls.fixture["article_canvas"]
                    if int(body.get("base_revision", -1)) != int(canvas["revision"]):
                        self._json(409, {"detail": {"message": "画布已由另一标签更新", "canvas": canvas}})
                        return
                    stored = {key: value for key, value in body.items()
                              if key not in {"base_revision", "base_updated_at", "client_id", "migration_version"}}
                    cls.fixture["article_canvas_puts"].append(json.loads(json.dumps(body)))
                    cls.fixture["article_canvas"] = {**canvas, **stored, "revision": canvas["revision"] + 1,
                                                     "updated_at": canvas["updated_at"] + 1}
                    self._json(200, {"canvas": cls.fixture["article_canvas"]})
                    return
                self._json(404, {"detail": "隔离文章 fixture 未实现此路由"})

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.http_port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.debug_port = probe.getsockname()[1]
        cls.cache = ROOT / "cache" / "studio-tests"
        cls.profile = cls.cache / "tmp" / f"article-browser-{int(time.time())}"
        cls.profile.mkdir(parents=True, exist_ok=True)
        cls.chrome = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--disable-popup-blocking", "--window-size=1440,1000",
            f"--user-data-dir={cls.profile}", f"--remote-debugging-port={cls.debug_port}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.target = cls._wait_for_target()
        if not cls.target:
            cls.tearDownClass()
            raise unittest.SkipTest("Chrome 未能暴露调试目标")
        node_script = r"""const readline=require('readline');
const ws=new WebSocket(process.argv[1]);const input=readline.createInterface({input:process.stdin});
ws.onopen=()=>{console.log(JSON.stringify({ready:true}));input.on('line',line=>{const q=JSON.parse(line);ws.send(JSON.stringify({id:q.id,method:q.method,params:q.params||{}}));});};
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id!==undefined)console.log(JSON.stringify({id:m.id,result:m.result||{},error:m.error||null}));};"""
        cls.cdp_process = subprocess.Popen([NODE, "-e", node_script, cls.target["webSocketDebuggerUrl"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        if not json.loads(cls.cdp_process.stdout.readline() or "{}").get("ready"):
            cls.tearDownClass()
            raise unittest.SkipTest("未能建立隔离 CDP 会话")
        cls.cdp("Page.enable")
        cls.cdp("Runtime.enable")

    @classmethod
    def tearDownClass(cls):
        for name in ("cdp_process", "chrome"):
            process = getattr(cls, name, None)
            if process:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except Exception:
                    pass
        if getattr(cls, "server", None):
            cls.server.shutdown()
            cls.server.server_close()
        profile = getattr(cls, "profile", None)
        if profile:
            shutil.rmtree(profile, ignore_errors=True)

    @classmethod
    def _wait_for_target(cls):
        import urllib.request
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cls.debug_port}/json/list", timeout=2) as response:
                    for target in json.loads(response.read().decode("utf-8")):
                        if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                            return target
            except Exception:
                pass
            time.sleep(0.15)
        return None

    @classmethod
    def cdp(cls, method, params=None):
        request_id = getattr(cls, "request_id", 0) + 1
        cls.request_id = request_id
        cls.cdp_process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params or {}}) + "\n")
        cls.cdp_process.stdin.flush()
        response = json.loads(cls.cdp_process.stdout.readline() or "{}")
        if response.get("id") != request_id or response.get("error"):
            raise AssertionError(response.get("error") or response)
        return response.get("result", {})

    @classmethod
    def evaluate(cls, expression):
        result = cls.cdp("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if result.get("exceptionDetails"):
            raise AssertionError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    def click_element(self, selector):
        point = self.evaluate(f"""(()=>{{const el=document.querySelector({json.dumps(selector)});if(!el)return null;el.scrollIntoView({{block:'center',inline:'center'}});const r=el.getBoundingClientRect();return {{x:r.left+r.width/2,y:r.top+r.height/2}};}})()""")
        if not point:
            raise AssertionError(f"missing browser element: {selector}")
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": point["x"], "y": point["y"]})
        self.cdp("Input.dispatchMouseEvent", {"type": "mousePressed", "x": point["x"], "y": point["y"], "button": "left", "clickCount": 1})
        self.cdp("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": point["x"], "y": point["y"], "button": "left", "clickCount": 1})

    @classmethod
    def targets(cls):
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{cls.debug_port}/json/list", timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))

    def setUp(self):
        type(self).fixture["projects"] = []
        type(self).fixture["article"] = article_payload()["article"]
        type(self).fixture["requests"] = []
        type(self).fixture["article_restore_conflict_once"] = False
        type(self).fixture["article_version_restores"] = []
        type(self).fixture["article_canvas"] = article_settings_canvas()
        type(self).fixture["article_canvas_bootstraps"] = 0
        type(self).fixture["article_canvas_gets"] = 0
        type(self).fixture["article_canvas_puts"] = []
        type(self).fixture["article_canvas_resets"] = []
        type(self).fixture["article_model_option_requests"] = []
        type(self).fixture["article_put_conflict_once"] = False
        type(self).fixture["article_template_reads"] = 0
        type(self).fixture["fail_body_image"] = False
        type(self).fixture["body_image_requests"] = []
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        self.download_dir = ROOT / "cache" / "studio-tests" / "tmp" / "article-downloads"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        for item in self.download_dir.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
        origin = f"http://127.0.0.1:{type(self).http_port}"
        self.cdp("Browser.grantPermissions", {"origin": origin, "permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"]})
        self.cdp("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(self.download_dir)})
        self.cdp("Page.bringToFront")
        import urllib.request
        for item in self.targets():
            if item.get("type") == "page" and item.get("id") != type(self).target.get("id"):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{type(self).debug_port}/json/close/{item['id']}", timeout=2).read()
                except Exception:
                    pass

    def navigate(self, path):
        self.cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.http_port}{path}"})
        self.assertTrue(self.evaluate("(async()=>{for(let i=0;i<160;i++){if(document.readyState==='complete')return true;await new Promise(r=>setTimeout(r,25));}return false;})()"))

    def wait_for(self, expression, message):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.evaluate(f"Boolean({expression})"):
                return
            time.sleep(0.025)
        state = self.evaluate("JSON.stringify({url:location.href,article:document.querySelector('#articleTitle')?.textContent,selected:[...document.querySelectorAll('[data-theme-id]')].map(x=>[x.dataset.themeId,x.getAttribute('aria-pressed')]),frame:document.querySelector('#articlePreviewFrame')?{key:document.querySelector('#articlePreviewFrame').dataset.previewKey,loaded:document.querySelector('#articlePreviewFrame').dataset.loadedPreviewKey,body:document.querySelector('#articlePreviewFrame').contentDocument?.body?.innerText?.slice(0,180)}:null,status:document.querySelector('[data-article-status]')?.textContent})")
        self.fail(f"{message}; state={state}")

    def save_screenshot(self, name):
        import base64
        encoded = self.cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}).get("data", "")
        path = ROOT / "cache" / "studio-tests" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(encoded))
        return path

    def save_validation_screenshot(self, name):
        import base64
        encoded = self.cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}).get("data", "")
        path = ROOT / ".cache" / "validation" / "studio-tests" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(encoded))
        return path

    def test_article_workbench_keeps_body_visible_with_long_history_and_view_switches_are_read_only(self):
        article = type(self).fixture["article"]
        long_title = "隔离工作台长标题测试：查看正文时标题仍保持清楚并与右侧操作留出空间"
        article["title_variants"]["short"]["title"] = long_title
        article["cover_variants"] = [*article["cover_variants"], *[
            {"id": f"cover-history-{index}", "asset_id": f"asset-cover-{index}", "result_id": f"result-cover-{index}",
             "source_sha256": "source-older", "source_matches": False, "valid": True,
             "url": "/fixture/cover.png", "name": f"历史封面 {index}", "mime": "image/png"}
            for index in range(3, 25)
        ]]
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1200, "deviceScaleFactor": 1, "mobile": False})
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey && document.querySelector('#articleStatus')===null && document.querySelector('[data-article-status]')?.hidden", "文章工作台未完成读取或成功状态未清除")
        self.wait_for("document.querySelector('#articleManagementDrawer')?.open===true && document.querySelector('#articleThemeChoices [data-theme-id]')", "桌面管理栏/已有排版未就绪")
        self.wait_for("document.querySelectorAll('#articleCoverHistory [data-version-kind=cover]').length===24", "长封面历史没有加载")
        self.wait_for("document.querySelectorAll('#articleTitleHistory [data-version-kind=title]').length===3 && document.querySelectorAll('#articleBodyHistory [data-version-kind=body]').length===2", "标题/正文版本历史没有加载")
        self.evaluate("document.querySelector('#articleTitleHistoryDetails').open=true;document.querySelector('#articleBodyHistoryDetails').open=true")
        section_order = self.evaluate("(() => [...document.querySelector('.article-layout-rail').children].filter(node=>node.matches('.article-version-group,.article-cover-history-details,.article-layout-section')).map(node=>node.id||node.querySelector('h2')?.textContent||node.querySelector('.article-meta-summary-label')?.textContent))()")
        self.assertEqual(section_order, ["标题", "封面", "articleCoverDetails", "正文", "主题"], section_order)
        self.wait_for("document.querySelector('#articlePreviewFrame')?.contentDocument?.querySelector('img')?.complete", "隔离正文中的图片没有结束加载")
        preview_image = self.evaluate("(() => {const frame=document.querySelector('#articlePreviewFrame'),img=frame?.contentDocument?.querySelector('img');return {src:img?.getAttribute('src'),currentSrc:img?.currentSrc,complete:img?.complete,naturalWidth:img?.naturalWidth,naturalHeight:img?.naturalHeight,resourceNames:frame?.contentWindow?.performance?.getEntriesByType('resource')?.map(entry=>entry.name).filter(name=>name.includes('fixture-image'))||[],requests:window.__imageRequests||null};})()")
        self.assertTrue(preview_image["naturalWidth"] > 0 and preview_image["currentSrc"].endswith("/api/results/result-fixture-image"), {**preview_image, "serverRequests": type(self).fixture["body_image_requests"]})

        geometry = self.evaluate("(() => {const rail=document.querySelector('.article-layout-rail'),workspace=document.querySelector('.article-workspace'),preview=document.querySelector('.article-preview-region'),frame=document.querySelector('#articlePreviewFrame'),title=document.querySelector('#articleTitle'),current=document.querySelector('#articleSelectedTitle'),picker=document.querySelector('#articleTitleDetails'),actions=document.querySelector('.article-title-toolbar .article-body-actions'),cover=document.querySelector('#articleCurrentCoverPreview'),exportButton=document.querySelector('#articleExportButton'),t=current?.getBoundingClientRect(),a=actions?.getBoundingClientRect();return {viewport:{w:innerWidth,h:innerHeight,scrollH:document.documentElement.scrollHeight},title:title?.textContent,currentTitle:current?.textContent,titleDetails:picker?.open,coverDetails:document.querySelector('#articleCoverDetails')?.open,coverId:cover?.dataset.coverPreviewId,actions:a?.toJSON(),currentTitleBox:t?.toJSON(),titleOverlap:!!(t&&a&&t.left<a.right&&a.left<t.right&&t.top<a.bottom&&a.top<t.bottom),titleRows:getComputedStyle(current).webkitLineClamp,rail:{top:rail?.getBoundingClientRect().top,height:rail?.getBoundingClientRect().height,client:rail?.clientHeight,scroll:rail?.scrollHeight},workspace:workspace?.getBoundingClientRect().toJSON(),preview:preview?.getBoundingClientRect().toJSON(),frame:frame?.getBoundingClientRect().toJSON(),frameInner:frame?.contentDocument?.body?.getBoundingClientRect().toJSON(),exportDirect:!!exportButton?.parentElement?.matches('.article-body-actions')&&!exportButton.closest('details')};})()")
        self.assertEqual(geometry["title"], "公众号文章", geometry)
        self.assertEqual(geometry["currentTitle"], long_title, geometry)
        self.assertEqual(geometry["titleRows"], "2", geometry)
        self.assertFalse(geometry["titleOverlap"], geometry)
        self.assertEqual(geometry["coverId"], "cover-a", geometry)
        self.assertFalse(geometry["titleDetails"] or geometry["coverDetails"], geometry)
        self.assertEqual(geometry["viewport"]["scrollH"], geometry["viewport"]["h"], geometry)
        self.assertLess(geometry["preview"]["top"], 230, geometry)
        self.assertGreater(geometry["preview"]["height"], 700, geometry)
        self.assertTrue(geometry["exportDirect"], geometry)
        self.evaluate("document.querySelector('#articleCoverDetails').open=true")
        scrolled_rail = self.evaluate("(() => {const rail=document.querySelector('.article-layout-rail'),preview=document.querySelector('.article-preview-region');return {rail:{client:rail.clientHeight,scroll:rail.scrollHeight},preview:preview.getBoundingClientRect().toJSON()};})()")
        self.assertGreater(scrolled_rail["rail"]["scroll"], scrolled_rail["rail"]["client"], scrolled_rail)
        self.assertAlmostEqual(scrolled_rail["preview"]["top"], geometry["preview"]["top"], delta=1, msg=str(scrolled_rail))
        self.assertAlmostEqual(scrolled_rail["preview"]["height"], geometry["preview"]["height"], delta=1, msg=str(scrolled_rail))
        self.evaluate("document.querySelector('#articleCoverDetails').open=false")
        light = self.save_validation_screenshot("article-four-version-desktop-light.png")

        initial_viewport = geometry["viewport"]
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 1100, "height": initial_viewport["h"], "deviceScaleFactor": 1, "mobile": False})
        self.wait_for("innerWidth===1100", "标题候选边界验证视口没有切换")
        self.evaluate("document.querySelector('#articleTitleDetails').open=true")
        self.wait_for("document.querySelector('#articleTitleDetails')?.open===true && document.querySelector('#articleTitleChoices .article-title-choice')", "标题候选菜单没有打开")
        title_menu = self.evaluate("(() => {const body=document.querySelector('.article-body-section').getBoundingClientRect(),picker=document.querySelector('#articleTitleDetails').getBoundingClientRect(),panel=document.querySelector('.article-title-choice-panel').getBoundingClientRect();return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,body:{left:body.left,right:body.right},picker:{left:picker.left,right:picker.right},panel:{left:panel.left,right:panel.right,width:panel.width}};})()")
        self.assertGreaterEqual(title_menu["panel"]["left"], title_menu["body"]["left"] - 1, title_menu)
        self.assertLessEqual(title_menu["panel"]["right"], title_menu["body"]["right"] + 1, title_menu)
        self.assertLessEqual(title_menu["documentWidth"], title_menu["width"] + 1, title_menu)
        self.save_validation_screenshot("article-four-version-title-menu-1100.png")
        self.evaluate("document.querySelector('#articleTitleDetails').open=false")
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": initial_viewport["w"], "height": initial_viewport["h"], "deviceScaleFactor": 1, "mobile": False})
        self.wait_for(f"innerWidth==={initial_viewport['w']}", "桌面截图视口没有恢复")

        before_puts = len([item for item in type(self).fixture["requests"] if item["method"] == "PUT"])
        before_revision = article["revision"]
        self.assertTrue(self.evaluate("!document.querySelector('#articleSourceTab') && !document.querySelector('#articleSourceDetails')"), "Markdown 原文浏览不属于公众号文章可见工作区")
        self.assertEqual(self.evaluate("[...document.querySelectorAll('#articleBodyViewTabs [role=tab]')].map(tab=>tab.id)"), ["articlePreviewTab", "articleCompareTab"])
        self.evaluate("document.querySelector('#articleCompareTab').click()")
        self.wait_for("document.querySelector('#articleComparePanel')?.hidden===false && document.querySelector('#articlePreviewPanel')?.hidden===true", "正文对比没有切换到同一工作区")
        self.evaluate("document.querySelector('#articlePreviewTab').click()")
        self.wait_for("document.querySelector('#articlePreviewPanel')?.hidden===false && document.querySelector('#articlePreviewTab')?.getAttribute('aria-selected')==='true'", "返回排版预览失败")
        self.assertEqual(len([item for item in type(self).fixture["requests"] if item["method"] == "PUT"]), before_puts, "排版预览/正文对比切换不能保存选择")
        self.assertEqual(type(self).fixture["article"]["revision"], before_revision)

        self.evaluate("window.StudioTheme?.set?.('dark')")
        self.wait_for("document.documentElement.dataset.studioAppearance==='dark'", "深色主题没有应用")
        dark = self.save_validation_screenshot("article-four-version-desktop-dark.png")
        self.assertTrue(light.is_file() and dark.is_file())

        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        self.wait_for("document.querySelector('#articleManagementDrawer')?.open===false", "窄屏管理栏没有切换为折叠抽屉")
        mobile = self.evaluate("(() => {const body=document.querySelector('.article-body-section'),preview=document.querySelector('.article-preview-region'),summary=document.querySelector('#articleManagementSummary');return {viewport:innerWidth,doc:document.documentElement.scrollWidth,body:document.body.scrollWidth,bodyTop:body?.getBoundingClientRect().top,preview:preview?.getBoundingClientRect().toJSON(),summary:summary?.getBoundingClientRect().toJSON()};})()")
        self.assertLessEqual(mobile["doc"], mobile["viewport"] + 1, mobile)
        self.assertLessEqual(mobile["body"], mobile["viewport"] + 1, mobile)
        self.assertLess(mobile["bodyTop"], 130, mobile)
        self.evaluate("window.StudioTheme?.set?.('light')")
        self.wait_for("document.documentElement.dataset.studioAppearance==='light'", "浅色主题没有恢复")
        narrow = self.save_validation_screenshot("article-four-version-390.png")
        self.assertTrue(narrow.is_file() and narrow.stat().st_size > 1000, str(narrow))

        self.evaluate("document.querySelector('#articleManagementSummary').click()")
        self.assertTrue(self.evaluate("document.querySelector('#articleManagementDrawer')?.open===true"), "窄屏管理抽屉应能展开")
        overlay = self.evaluate("(() => {const body=document.querySelector('.article-body-section'),rail=document.querySelector('.article-layout-rail'),r=rail.getBoundingClientRect(),hit=document.elementFromPoint(Math.min(r.right-12,r.left+22),Math.min(r.bottom-12,r.top+22));return {bodyTop:body.getBoundingClientRect().top,railBottom:r.bottom,railTop:r.top,hitInsideRail:!!hit?.closest('.article-layout-rail'),hit:hit?.className||hit?.id};})()")
        self.assertLessEqual(overlay["railTop"], overlay["bodyTop"], overlay)
        self.assertTrue(overlay["hitInsideRail"], overlay)
        drawer_shot = self.save_validation_screenshot("article-four-version-390-drawer-open.png")
        self.assertTrue(drawer_shot.is_file() and drawer_shot.stat().st_size > 1000, str(drawer_shot))
        self.assertLess(overlay["bodyTop"], 130, overlay)

    def test_body_history_is_html_only_and_restores_layout_without_markdown_ui(self):
        original_source = type(self).fixture["article"]["source_markdown"]
        original_layout = type(self).fixture["article"]["variants"]["moyu-green"]["body_html"]
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey && document.querySelectorAll('#articleBodyHistory [data-version-kind=body]').length===2", "文章及正文排版历史没有加载")
        self.wait_for("!['正在读取文章…','Loading article…'].includes(document.querySelector('[data-article-status]')?.textContent)", "文章读取状态没有完成")
        self.assertTrue(self.evaluate("!document.querySelector('#articleSourceTab') && !document.querySelector('#articleSourceDetails')"), "页面不应显示 Markdown 原文标签或历史面板")
        self.assertTrue(self.evaluate("!document.querySelector('#articleBodyVersionCurrentMeta')"), "内部文章 revision 不应混入正文版本摘要")
        self.assertEqual(self.evaluate("[...document.querySelectorAll('#articleBodyViewTabs [role=tab]')].map(tab=>tab.id)"), ["articlePreviewTab", "articleCompareTab"])
        self.evaluate("document.querySelector('#articleBodyHistoryDetails').open=true")
        self.wait_for("document.querySelector('#articleBodyHistory [data-layout-preview-version=body-v1][data-preview-state=ready] iframe')?.contentDocument?.body?.innerText.includes('旧版本正文')", "正文历史必须展示真实 HTML 排版缩略图")
        self.assertTrue(self.evaluate("[...document.querySelectorAll('#articleBodyHistory [data-version-kind=body]')].every(row=>row.querySelector('iframe[data-history-layout-frame]') && !row.querySelector('.article-history-source-excerpt'))"), "每条正文历史只提供排版预览，不提供源文摘要")
        self.assertTrue(all(not any(key in detail.get("snapshot", {}) for key in ("source_markdown", "source_markdown_available")) for key, detail in type(self).fixture["article_version_details"].items() if key.startswith("body:")), "历史详情 fixture 不能向界面暴露 Markdown 快照")

        v1 = "#articleBodyHistory button[data-version-id=body-v1]"
        v2 = "#articleBodyHistory button[data-version-id=body-v2]"
        self.assertEqual(self.evaluate(f"document.querySelector({json.dumps(v1)})?.getAttribute('aria-pressed')"), "false")
        preview_revision = type(self).fixture["article"]["revision"]
        writes_before = len(type(self).fixture["article_version_restores"])
        self.click_element(v1)
        self.wait_for("document.querySelector('#articlePreviewFrame')?.contentDocument?.body?.innerText.includes('旧版本正文') && document.querySelector('#articleBodyHistory button[data-version-id=body-v1]')?.getAttribute('aria-current')==='true' && document.querySelector('#articleBodyVersionCurrent')?.textContent.includes('V1')", "点击 V1 排版卡片应直接恢复对应 HTML")
        self.assertEqual(type(self).fixture["article"]["source_markdown"], original_source, "HTML 版本恢复不得恢复或改写内部 Markdown")
        self.assertEqual(type(self).fixture["article"]["variants"]["moyu-green"]["body_html"], "<article><h1>隔离旧稿</h1><p>旧版本正文。</p></article>")
        restore_v1 = type(self).fixture["article_version_restores"][-1]
        self.assertEqual(restore_v1["body"], {"expected_revision": preview_revision, "body_view": "preview"})
        self.assertEqual(len(type(self).fixture["article_version_restores"]), writes_before+1)

        self.click_element(v2)
        self.wait_for("document.querySelector('#articlePreviewFrame')?.contentDocument?.body?.innerText.includes('正文第一段') && document.querySelector('#articleBodyHistory button[data-version-id=body-v2]')?.getAttribute('aria-current')==='true' && document.querySelector('#articleBodyVersionCurrent')?.textContent.includes('V2')", "点击 V2 应切回对应 HTML 版本")
        self.assertEqual(type(self).fixture["article"]["source_markdown"], original_source)
        self.assertEqual(type(self).fixture["article"]["variants"]["moyu-green"]["body_html"], original_layout)
        self.assertEqual(type(self).fixture["article_version_restores"][-1]["body"]["body_view"], "preview")
        self.assertEqual(self.evaluate("document.querySelector('#articlePreviewTab')?.getAttribute('aria-selected')"), "true", "历史恢复保持排版预览标签")

        self.wait_for("document.querySelector('#articleBodyHistory [data-layout-preview-version=body-v1][data-preview-state=ready] iframe')?.contentDocument?.body?.innerText.includes('旧版本正文')", "恢复后的历史 HTML 缩略图没有加载")
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        self.evaluate("window.StudioTheme?.set?.('dark')")
        self.wait_for("document.documentElement.dataset.studioAppearance==='dark'", "深色主题没有应用")
        desktop_shot = self.save_validation_screenshot("article-history-html-only-desktop-dark.png")
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        self.wait_for("innerWidth===390 && document.querySelector('#articleManagementDrawer')?.open===false", "窄屏布局没有生效")
        mobile_shot = self.save_validation_screenshot("article-history-html-only-390.png")
        self.assertTrue(desktop_shot.is_file() and desktop_shot.stat().st_size > 1000, str(desktop_shot))
        self.assertTrue(mobile_shot.is_file() and mobile_shot.stat().st_size > 1000, str(mobile_shot))

        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        self.assertTrue(self.evaluate("document.querySelector('#articleBodyHistory button[data-version-id=body-v1]')?.disabled===false"), "非当前 HTML 历史必须可选")
        writes_before_conflict = len(type(self).fixture["article_version_restores"])
        type(self).fixture["article_restore_conflict_once"] = True
        self.click_element(v1)
        self.wait_for("document.querySelector('[data-article-status]')?.textContent.includes('文章已更新，未采用此历史版本')", "409 应提示重新核对，不得假装采用")
        self.assertEqual(len(type(self).fixture["article_version_restores"]), writes_before_conflict+1, "409 不自动重试")
        self.assertEqual(type(self).fixture["article"]["source_markdown"], original_source, "冲突恢复不得改写内部 Markdown")
        self.assertTrue(self.evaluate("document.querySelector('#articlePreviewTab')?.getAttribute('aria-selected')==='true'"), "409 后保留当前排版预览")
        self.assertTrue(self.evaluate("document.querySelector('#articleBodyHistory button[data-version-id=body-v2]')?.getAttribute('aria-current')==='true'"), "409 后不能把未采用版本标为当前")
        self.assertEqual(self.evaluate("document.querySelector('#articleBodyHistory button[data-version-id=body-v1]')?.disabled"), False, "409 后仍可由用户明确重新选择")
    def test_article_loading_status_clears_after_superseding_read_without_clearing_errors(self):
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey && document.querySelector('#articleTitleVersionCurrent')?.textContent!=='—' && document.querySelector('[data-article-status]')?.hidden", "初始文章和版本目录没有完成读取")

        self.evaluate("""(()=>{
          const real=window.fetch.bind(window);window.__articleRealFetch=real;
          let holdFirst=true;window.__staleReadSettled=false;
          window.fetch=(url,options)=>{
            if(holdFirst&&String(url)==='/api/studio/articles/article-fixture'){
              holdFirst=false;
              return new Promise(resolve=>{window.__releaseStaleArticleRead=()=>{
                resolve(real(url,options).then(response=>{window.__staleReadSettled=true;return response;}));
              };});
            }
            return real(url,options);
          };
          document.querySelector('#articleRefreshButton').click();
        })()""")
        self.wait_for("typeof window.__releaseStaleArticleRead==='function' && document.querySelector('[data-article-status]')?.classList.contains('is-loading')", "前台刷新没有进入可识别的读取状态")
        current_revision=type(self).fixture["article"]["revision"]
        type(self).fixture["article"]["revision"]=current_revision-1
        self.evaluate("window.dispatchEvent(new Event('focus'))")
        self.wait_for("document.querySelector('[data-article-status]')?.hidden===true", "被后台低 revision 响应拒绝后，读取状态应结束")
        type(self).fixture["article"]["revision"]=current_revision
        self.evaluate("window.__releaseStaleArticleRead()")
        self.wait_for("window.__staleReadSettled===true && document.querySelector('[data-article-status]')?.hidden===true", "迟到的旧读取不能重新显示或遗留读取状态")

        self.evaluate("""(()=>{
          const real=window.__articleRealFetch;let fail=true;
          window.fetch=(url,options)=>{
            if(fail&&String(url)==='/api/studio/articles/article-fixture'){
              fail=false;
              return Promise.resolve(new Response(JSON.stringify({detail:'隔离读取失败'}),{status:503,headers:{'Content-Type':'application/json'}}));
            }
            return real(url,options);
          };
          document.querySelector('#articleRefreshButton').click();
        })()""")
        self.wait_for("document.querySelector('[data-article-status]')?.classList.contains('is-error') && document.querySelector('[data-article-status]')?.textContent.includes('隔离读取失败')", "读取失败应保留为可见错误")
        self.evaluate("""(()=>{
          const real=window.__articleRealFetch;window.__recoveryReadSettled=false;
          window.fetch=(url,options)=>String(url)==='/api/studio/articles/article-fixture'
            ?real(url,options).then(response=>{window.__recoveryReadSettled=true;return response;})
            :real(url,options);
          window.dispatchEvent(new Event('focus'));
        })()""")
        self.wait_for("window.__recoveryReadSettled===true", "后台成功读取没有完成")
        self.assertTrue(self.evaluate("document.querySelector('[data-article-status]')?.classList.contains('is-error') && document.querySelector('[data-article-status]')?.textContent.includes('隔离读取失败')"), "后台成功刷新不能覆盖真实读取错误")

    def test_article_module_creates_a_card_then_opens_the_explicit_article_url(self):
        self.navigate("/static/index.html")
        self.wait_for("document.querySelector('#nav-article')", "主导航没有公众号文章入口")
        self.evaluate("window.StudioI18n?.set?.('zh')")
        self.assertTrue(self.evaluate("document.querySelector('#nav-article').compareDocumentPosition([...document.querySelectorAll('.nav-item')].find(n=>n.textContent.includes('素材库'))) & Node.DOCUMENT_POSITION_FOLLOWING"))
        self.evaluate("document.querySelector('#nav-article').click()")
        self.wait_for("document.querySelector('#frame-article')?.src.includes('/static/article-list.html')", "公众号文章列表没有在模块 iframe 中打开")
        self.wait_for("document.querySelector('#frame-article')?.contentDocument?.body?.dataset?.studioModule==='article'", "文章项目页未加载")
        self.evaluate("window.StudioI18n?.set?.('zh')")
        self.wait_for("document.querySelector('#frame-article')?.contentDocument?.querySelectorAll('.article-template-option').length===6", "未显示六种真实模板目录项")
        preview = self.evaluate("(() => {const d=document.querySelector('#frame-article').contentDocument;return {options:[...d.querySelectorAll('.article-template-option')].map(x=>x.dataset.templateId),frames:[...d.querySelectorAll('#articleTemplatePreview')].map(x=>({sandbox:x.getAttribute('sandbox'),src:x.getAttribute('src')}))};})()")
        self.assertEqual(len(preview["options"]), 6, preview)
        self.assertEqual(len(preview["frames"]), 1, preview)
        self.assertNotIn("allow-scripts", (preview["frames"][0]["sandbox"] or "").split(), preview)
        self.assertTrue(preview["frames"][0]["src"].startswith("http://127.0.0.1:"), preview)

        before = {item.get("url") for item in self.targets() if item.get("type") == "page"}
        created = self.evaluate("""(async()=>{
          const frame=document.querySelector('#frame-article');
          frame.contentWindow.StudioDialog.prompt=async()=> '新文章样例';
          frame.contentDocument.querySelector('#studioNewProjectButton').click();
          for(let i=0;i<160;i++){if(frame.contentDocument.querySelector('[data-project-id="article-fixture"]'))return true;await new Promise(r=>setTimeout(r,25));}
          return false;
        })()""")
        self.assertTrue(created, "创建文章项目没有生成卡片")
        time.sleep(0.25)
        after = {item.get("url") for item in self.targets() if item.get("type") == "page"}
        self.assertEqual(after, before, "创建项目不应自动打开文章页或新增标签")
        self.assertEqual(type(self).fixture["requests"][0], {"method": "POST", "path": "/api/studio/projects", "body": {"module": "article", "name": "新文章样例"}})

        # 新标签打开动作由真实卡片按钮触发；禁用弹窗拦截后核验新 target 的完整 URL。
        self.evaluate("document.querySelector('#frame-article').contentDocument.querySelector('[data-card-action=open][data-project-id=article-fixture]').click()")
        opened = False
        for _ in range(60):
            urls = {item.get("url", "") for item in self.targets() if item.get("type") == "page"}
            if any("/static/article.html?id=article-fixture" in url for url in urls):
                opened = True
                break
            time.sleep(0.1)
        self.assertTrue(opened, f"显式打开未导航到文章 URL；targets={self.targets()}")

    def test_article_template_directory_switches_one_large_real_preview(self):
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        self.navigate("/static/index.html")
        self.wait_for("document.querySelector('#nav-article')", "主导航没有公众号文章入口")
        self.evaluate("document.querySelector('#nav-article').click()")
        self.wait_for("document.querySelector('#frame-article')?.contentDocument?.body?.dataset?.studioModule==='article'", "文章项目页未加载")
        self.wait_for("document.querySelector('#frame-article')?.contentDocument?.querySelectorAll('.article-template-option').length===6", "模板目录没有展示六种真实模板")
        self.wait_for("document.querySelector('#frame-article')?.contentDocument?.querySelector('#articleTemplatePreview')?.getAttribute('src')", "没有加载当前模板的大预览")
        self.assertEqual(self.evaluate("document.querySelector('#frame-article').contentDocument.querySelector('#studioPrepareButton')?.textContent.trim()"), "准备创作技能")

        initial = self.evaluate("(() => {const d=document.querySelector('#frame-article').contentDocument;return {buttons:[...d.querySelectorAll('.article-template-option')].map(x=>({id:x.dataset.templateId,selected:x.getAttribute('aria-selected'),tabIndex:x.tabIndex})),frame:[...d.querySelectorAll('#articleTemplatePreview')].map(x=>({src:x.getAttribute('src'),sandbox:x.getAttribute('sandbox'),title:x.title})),activeId:d.querySelector('#articleTemplateDirectory')?.dataset?.selectedTemplateId};})()")
        self.assertEqual(len(initial["buttons"]), 6, initial)
        self.assertEqual(sum(item["selected"] == "true" for item in initial["buttons"]), 1, initial)
        self.assertEqual(len(initial["frame"]), 1, initial)
        self.assertNotIn("allow-scripts", (initial["frame"][0]["sandbox"] or "").split(), initial)
        self.assertTrue(initial["frame"][0]["src"].startswith("http://127.0.0.1:"), initial)

        before_puts = sum(item["method"] == "PUT" for item in type(self).fixture["requests"])
        self.evaluate("document.querySelector('#frame-article').contentDocument.querySelector('.article-template-option[data-template-id=red-white]').click()")
        self.wait_for("document.querySelector('#frame-article')?.contentDocument?.querySelector('#articleTemplateDirectory')?.dataset?.selectedTemplateId==='red-white'", "点击目录后没有切换当前示例")
        self.wait_for("document.querySelector('#frame-article')?.contentDocument?.querySelector('#articleTemplatePreview')?.getAttribute('src').endsWith('/static/article-templates/red-white.html')", "右侧没有切换到红白主题的真实预览")
        selected = self.evaluate("(() => {const d=document.querySelector('#frame-article').contentDocument;return {selected:[...d.querySelectorAll('.article-template-option')].filter(x=>x.getAttribute('aria-selected')==='true').map(x=>x.dataset.templateId),frames:d.querySelectorAll('#articleTemplatePreview').length,putCount:0};})()")
        self.assertEqual(selected["selected"], ["red-white"], selected)
        self.assertEqual(selected["frames"], 1, selected)
        self.assertEqual(sum(item["method"] == "PUT" for item in type(self).fixture["requests"]), before_puts, "浏览模板示例不得修改文章主题或文章内容")

        desktop = self.evaluate("(() => {const d=document.querySelector('#frame-article').contentDocument,b=d.querySelector('.article-template-browser'),list=d.querySelector('#articleTemplateDirectory'),preview=d.querySelector('.article-template-preview-pane');return {width:innerWidth,viewport:d.documentElement.clientWidth,documentWidth:d.documentElement.scrollWidth,browser:b?.getBoundingClientRect().toJSON(),list:list?.getBoundingClientRect().toJSON(),preview:preview?.getBoundingClientRect().toJSON(),columns:getComputedStyle(b).gridTemplateColumns};})()")
        self.assertEqual(desktop["width"], 1440, desktop)
        self.assertEqual(len(desktop["columns"].split()), 2, desktop)
        self.assertLessEqual(desktop["documentWidth"], desktop["viewport"] + 1, desktop)
        self.assertGreater(desktop["preview"]["width"], desktop["list"]["width"] * 2, desktop)
        self.evaluate("document.querySelector('#frame-article').contentDocument.querySelector('#articleTemplateTitle')?.scrollIntoView({block:'start'})")
        time.sleep(0.25)
        self.save_screenshot("article-template-directory-desktop.png")

        self.evaluate("window.StudioI18n?.set?.('zh');document.querySelector('#lang-toggle-btn')?.click()")
        self.wait_for("document.querySelector('#frame-article')?.contentDocument?.querySelector('.article-template-option[data-template-id=red-white]')?.textContent.includes('Red and White')", "英文界面没有同步模板目录")
        english = self.evaluate("(() => {const d=document.querySelector('#frame-article').contentDocument;const button=d.querySelector('.article-template-option[data-template-id=red-white]');return {selected:button?.getAttribute('aria-selected'),label:button?.getAttribute('aria-label'),title:d.querySelector('#articleTemplatePreview')?.title,src:d.querySelector('#articleTemplatePreview')?.getAttribute('src')};})()")
        self.assertEqual(english["selected"], "true", english)
        self.assertIn("Red and White", english["label"], english)
        self.assertTrue(english["src"].endswith("/static/article-templates/red-white.html"), english)
        self.assertEqual(self.evaluate("document.querySelector('#frame-article').contentDocument.querySelector('#studioPrepareButton')?.textContent.trim()"), "Prepare creative skills")

        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 573, "height": 860, "deviceScaleFactor": 1, "mobile": True})
        medium = self.evaluate("(() => {const d=document.querySelector('#frame-article').contentDocument,b=d.querySelector('.article-template-browser'),list=d.querySelector('#articleTemplateDirectory'),preview=d.querySelector('.article-template-preview-pane');return {width:innerWidth,innerDocumentWidth:d.documentElement.scrollWidth,viewport:d.documentElement.clientWidth,browser:b?.getBoundingClientRect().toJSON(),list:list?.getBoundingClientRect().toJSON(),preview:preview?.getBoundingClientRect().toJSON(),columns:getComputedStyle(b).gridTemplateColumns};})()")
        self.assertEqual(medium["width"], 573, medium)
        self.assertLessEqual(medium["innerDocumentWidth"], medium["viewport"] + 1, medium)
        self.assertEqual(len(medium["columns"].split()), 1, medium)
        self.assertGreater(medium["preview"]["width"], medium["list"]["width"] - 4, medium)
        self.evaluate("document.querySelector('#frame-article').contentDocument.querySelector('#articleTemplateTitle')?.scrollIntoView({block:'start'})")
        time.sleep(0.2)
        self.save_screenshot("article-template-directory-573.png")

        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 320, "height": 740, "deviceScaleFactor": 1, "mobile": True})
        mobile = self.evaluate("(() => {const outer=document.querySelector('#frame-article'),d=outer.contentDocument,browser=d.querySelector('.article-template-browser'),directory=d.querySelector('#articleTemplateDirectory'),pane=d.querySelector('.article-template-preview-pane'),frame=d.querySelector('#articleTemplatePreview'),options=d.querySelector('.article-template-options');const overflows=[...d.querySelectorAll('body,body *')].map(el=>({tag:el.tagName,id:el.id,cls:typeof el.className==='string'?el.className:'',right:el.getBoundingClientRect().right,width:el.getBoundingClientRect().width})).filter(el=>el.right>d.documentElement.clientWidth+1).slice(0,8);return {outerWidth:innerWidth,frame:outer.getBoundingClientRect().toJSON(),viewport:d.documentElement.clientWidth,documentWidth:d.documentElement.scrollWidth,browserWidth:browser?.getBoundingClientRect().width,browserScrollWidth:browser?.scrollWidth,directory:directory?.getBoundingClientRect().toJSON(),pane:pane?.getBoundingClientRect().toJSON(),preview:frame?.getBoundingClientRect().toJSON(),columns:getComputedStyle(browser).gridTemplateColumns,optionColumns:getComputedStyle(options).gridTemplateColumns,optionWidth:options?.getBoundingClientRect().width,overflows};})()")
        self.assertEqual(mobile["outerWidth"], 320, mobile)
        self.assertLessEqual(mobile["documentWidth"], mobile["viewport"] + 1, mobile)
        self.assertLessEqual(mobile["browserWidth"], mobile["viewport"] + 1, mobile)
        self.assertLessEqual(mobile["browserScrollWidth"], mobile["browserWidth"] + 1, mobile)
        self.assertEqual(len(mobile["columns"].split()), 1, mobile)
        self.assertEqual(len(mobile["optionColumns"].split()), 1, mobile)
        self.assertGreater(mobile["optionWidth"], 120, mobile)
        self.assertGreater(mobile["preview"]["width"], 150, mobile)
        self.evaluate("document.querySelector('#frame-article').contentDocument.querySelector('#articleTemplateTitle')?.scrollIntoView({block:'start'})")
        time.sleep(0.2)
        self.save_screenshot("article-template-directory-mobile.png")
        self.evaluate("window.StudioI18n?.set?.('zh')")

        # sandbox="" 故意隔离预览文档的脚本与同源读取；切换行为在上面验证，内容由直接打开同一静态资产验证。
        self.navigate("/static/article-templates/red-white.html")
        self.wait_for("document.body?.innerText.includes('我是老胡')", "红白示例正文没有加载老胡介绍")
        preview_copy = self.evaluate("(() => {const text=document.body?.innerText||'';const chapterHeadings=['让技能接住具体环节','画布把流程摆在眼前','视频创作与复刻有自己的入口','公众号文章项目'];return {text,chapterHeadings:chapterHeadings.filter(title=>text.includes(title)),sectionCount:document.querySelectorAll('section').length};})()")
        self.assertIn("老胡画梦枋", preview_copy["text"], preview_copy)
        self.assertIn("Hypit", preview_copy["text"], preview_copy)
        self.assertEqual(preview_copy["chapterHeadings"], ["让技能接住具体环节", "画布把流程摆在眼前", "视频创作与复刻有自己的入口", "公众号文章项目"], preview_copy)
        self.assertGreater(preview_copy["sectionCount"], 10, preview_copy)
        self.assertIn("工具可以把路铺开，创作者仍然能决定作品往哪里走。", preview_copy["text"], preview_copy)
        self.assertNotIn("2026.07", preview_copy["text"], preview_copy)
        self.assertNotIn("甲木", preview_copy["text"], preview_copy)

    def test_real_template_body_does_not_overflow_preview_at_tablet_or_phone_width(self):
        self.navigate("/static/article-templates/moyu-green.html")
        self.wait_for("document.body?.innerText?.length>300", "真实正文示例没有加载")
        self.evaluate("(() => {const meta=document.createElement('meta');meta.name='viewport';meta.content='width=device-width,initial-scale=1';document.head.append(meta);})()")
        for width in (573, 320):
            with self.subTest(width=width):
                self.cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": 860, "deviceScaleFactor": 1, "mobile": True})
                report = self.evaluate("({width:innerWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,scrollable:[...document.querySelectorAll('body *')].filter(node=>node.scrollWidth>node.clientWidth+4&&getComputedStyle(node).overflowX==='visible').slice(0,6).map(node=>({tag:node.tagName,className:typeof node.className==='string'?node.className:'',scrollWidth:node.scrollWidth,clientWidth:node.clientWidth}))})")
                self.assertEqual(report["width"], width, report)
                self.assertLessEqual(report["documentWidth"], width + 1, report)
                self.assertLessEqual(report["bodyWidth"], width + 1, report)

    def test_article_without_saved_layouts_shows_no_template_placeholders_or_generation_request(self):
        type(self).fixture["article"]["variants"] = {}
        type(self).fixture["article"]["selected_theme_id"] = None
        source = type(self).fixture["article"]["source_markdown"]
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewEmpty')?.textContent.includes('没有已保存的正文排版')", "缺少正文排版时未显示真实缺失状态")
        empty = self.evaluate("(() => ({themes:[...document.querySelectorAll('[data-theme-id]')].map(node=>node.dataset.themeId),catalog:!!document.querySelector('#articleAgentRequest,#articleAgentAllRequest'),label:document.querySelector('#articlePreviewThemeName')?.textContent,buttons:[...document.querySelectorAll('#articleCopyButton,#articleExportButton')].map(button=>button.disabled),note:document.querySelector('#articleThemeChoices')?.textContent}))()")
        self.assertEqual(empty["themes"], [])
        self.assertFalse(empty["catalog"])
        self.assertEqual(empty["label"], "摸鱼绿", "无用户主题选择时以摸鱼绿作为新创作默认主题")
        self.assertTrue(all(empty["buttons"]))
        self.assertIn("摸鱼绿", empty["note"])
        self.assertEqual(type(self).fixture["article_template_reads"], 0)
        self.assertTrue(type(self).fixture["requests"])
        self.assertTrue(all(item["method"]=="GET" for item in type(self).fixture["requests"]),
                        "无已保存排版时后台焦点刷新仍只能读取文章，不能写入或生成")
        self.assertEqual(type(self).fixture["article"]["source_markdown"], source)

    def test_title_candidate_with_same_markdown_is_not_historical_and_server_selection_id_wins(self):
        source = type(self).fixture["article"]["source_markdown"]
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('[data-title-variant-id=alternate]')", "同一 Markdown 的备选标题没有显示")
        self.evaluate("document.querySelector('#articleTitleDetails').open=true")
        self.assertNotIn("历史标题", self.evaluate("document.querySelector('[data-title-variant-id=alternate]')?.textContent||''"),
                         "alternate title hash differs by title; its source_matches=true must prevent false historical labeling")
        self.evaluate("document.querySelector('[data-title-variant-id=alternate]').click()")
        self.wait_for("document.querySelector('#articleSelectedTitle')?.textContent==='同原文备选标题' && document.querySelector('[data-title-variant-id=title-canonical-alternate]')?.getAttribute('aria-pressed')==='true'", "前端未采用服务端返回的规范标题版本 ID")
        self.assertFalse(self.evaluate("document.querySelector('[data-title-variant-id=alternate]')?.getAttribute('aria-pressed')==='true'"),
                         "服务端返回规范版本 ID 后，旧候选 ID 不应继续被显示为当前项")
        self.assertEqual(type(self).fixture["article"]["selected_title_variant_id"], "title-canonical-alternate")
        self.assertEqual(type(self).fixture["article"]["source_markdown"], source, "复用标题不应改写 Markdown")

    def test_duplicate_titles_dedupe_by_trimmed_text_and_keep_export_direct_on_mobile(self):
        article = type(self).fixture["article"]
        digest = article["source_sha256"]
        article["title_variants"].update({
            "duplicate-first": {"title": " 同名候选 ", "source_sha256": "source-old-a", "source_matches": False, "valid": True},
            "duplicate-current": {"title": "同名候选", "source_sha256": digest, "source_matches": True, "valid": True},
            "duplicate-selected": {"title": "同名候选  ", "source_sha256": "source-old-b", "source_matches": False, "valid": True},
            "different-punctuation": {"title": "同名候选。", "source_sha256": digest, "source_matches": True, "valid": True},
            "invalid-one": {"valid": False},
            "invalid-two": {"valid": False},
        })
        article["selected_title_variant_id"] = "duplicate-selected"
        before_titles = json.loads(json.dumps(article["title_variants"], ensure_ascii=False))
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey && document.querySelector('#articleExportButton')?.disabled===false", "文章页或导出按钮未就绪")
        self.evaluate("document.querySelector('#articleTitleDetails').open=true")
        choices = self.evaluate("(() => [...document.querySelectorAll('#articleTitleChoices [data-title-variant-id]')].map(node=>({id:node.dataset.titleVariantId,title:node.querySelector('span')?.textContent,selected:node.getAttribute('aria-pressed'),disabled:node.disabled})) )()")
        duplicate_choices = [item for item in choices if item["title"] == "同名候选"]
        self.assertEqual(len(duplicate_choices), 1, choices)
        self.assertEqual(duplicate_choices[0]["id"], "duplicate-selected", "有效当前选中项优先作为同名标题的代表")
        self.assertEqual(duplicate_choices[0]["selected"], "true", choices)
        self.assertEqual(len([item for item in choices if item["title"] == "同名候选。"]), 1,
                         "仅按 trim 后的完整文本合并，不忽略标点")
        self.assertEqual(len([item for item in choices if item["id"].startswith("invalid-")]), 2,
                         "无效历史记录仍逐条显示，不按本地化不可用文案合并")
        self.assertEqual(self.evaluate("document.querySelector('#articleSelectedTitle')?.textContent"), "同名候选")
        self.assertFalse(self.evaluate("document.querySelector('[data-title-variant-id=duplicate-selected]')?.disabled"),
                         "有效的代表标题仍需保持可点击")
        self.evaluate("document.querySelector('[data-title-variant-id=duplicate-selected]').click()")
        self.assertEqual(self.evaluate("document.querySelector('#articleSelectedTitle')?.textContent"), "同名候选")
        self.assertFalse(self.evaluate("document.querySelector('[data-title-variant-id=different-punctuation]')?.disabled"),
                         "其他有效标题候选不能因去重而被禁用")
        self.evaluate("document.querySelector('[data-title-variant-id=different-punctuation]').click()")
        self.wait_for("document.querySelector('#articleSelectedTitle')?.textContent==='同名候选。' && document.querySelector('[data-title-variant-id=different-punctuation]')?.getAttribute('aria-pressed')==='true'",
                      "选择独立标题后应更新当前标题与选中态")
        self.evaluate("(()=>{window.__articleCopiedTitle='';Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{window.__articleCopiedTitle=value;}}});document.querySelector('#articleCopyTitleButton').click();})()")
        self.wait_for("window.__articleCopiedTitle==='同名候选。'", "复制标题应与当前选中候选一致")
        self.assertEqual(self.evaluate("document.querySelector('#articleExportButton')?.closest('details')===null && document.querySelector('#articleExportButton')?.parentElement?.matches('.article-body-actions')"), True,
                         "导出应直接位于正文操作栏，不藏在折叠菜单中")
        self.assertEqual(type(self).fixture["article"]["title_variants"], before_titles,
                         "去重与复制不能删除、重写或合并服务端历史记录")
        mutations = [item for item in type(self).fixture["requests"] if item["method"] in {"PUT", "POST"}]
        self.assertEqual([item["method"] for item in mutations], ["PUT"],
                         "只允许用户明确切换选择时写一次选中 ID，不得写入或删除标题历史")
        self.assertEqual(mutations[0]["body"].get("selected_title_variant_id"), "different-punctuation")
        self.assertNotIn("title_variants", mutations[0]["body"])

        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        self.wait_for("innerWidth===390", "窄屏视口没有生效")
        mobile = self.evaluate("(() => {const button=document.querySelector('#articleExportButton'),box=button.getBoundingClientRect();return {viewport:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth,left:box.left,right:box.right,visible:box.width>0&&getComputedStyle(button).visibility!=='hidden',label:button.innerText};})()")
        self.assertLessEqual(mobile["document"], 391, mobile)
        self.assertLessEqual(mobile["body"], 391, mobile)
        self.assertTrue(mobile["visible"] and mobile["left"] >= 0 and mobile["right"] <= 391, mobile)
        self.save_validation_screenshot("article-title-dedup-export-390.png")

    def test_real_html_digest_enables_copy_and_export_and_reports_download_start(self):
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey && !document.querySelector('#articleCopyButton')?.disabled", "有真实 html_sha256 的当前版本应通过同一预览指纹启用复制")
        ready = self.evaluate("(() => ({preview:document.querySelector('#articlePreviewFrame')?.dataset?.previewKey,loaded:document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey,copyDisabled:document.querySelector('#articleCopyButton')?.disabled,exportDisabled:document.querySelector('#articleExportButton')?.disabled}))()")
        self.assertEqual(ready["preview"], ready["loaded"], ready)
        self.assertFalse(ready["copyDisabled"] or ready["exportDisabled"], ready)

        self.evaluate("""(()=>{const clipboard=navigator.clipboard;const realWrite=clipboard?.write?.bind(clipboard);if(realWrite)Object.defineProperty(navigator,'clipboard',{configurable:true,value:{write:async items=>{const item=items[0];window.__articleClipboardPayload={via:'Clipboard.write',types:item.types};for(const type of item.types)window.__articleClipboardPayload[type]=await item.getType(type).then(blob=>blob.text());try{return await realWrite(items);}catch(error){window.__articleClipboardError=String(error);throw error;}}}});document.addEventListener('copy',event=>{window.__articleCopyEventPayload={via:'copy event',types:['text/html','text/plain'],html:event.clipboardData?.getData('text/html')||'',plain:event.clipboardData?.getData('text/plain')||''};},false);})()""")
        self.click_element("#articleCopyButton")
        self.wait_for("document.querySelector('#articleCopyFeedback')?.textContent.includes('正文已复制')", "Clipboard API 拒绝了当前复制操作")
        copied = self.evaluate("window.__articleClipboardPayload||window.__articleCopyEventPayload")
        self.assertTrue(copied, self.evaluate("({clipboard:!!navigator.clipboard,write:typeof navigator.clipboard?.write,clipboardItem:typeof ClipboardItem,apiError:window.__articleClipboardError,event:window.__articleCopyEventPayload,feedback:document.querySelector('#articleCopyFeedback')?.textContent})"))
        self.assertIn("text/html", copied, copied)
        self.assertIn("<section", copied["text/html"])
        self.assertIn("正文第一段。", copied["text/plain"])
        self.assertIn("data:image/png;base64,", copied["text/html"], "同源受管正文图应在剪贴板HTML中变成自包含data URI")
        self.assertNotIn("/api/results/", copied["text/html"], "图片srcset或延迟加载属性不能留下localhost旁路")
        self.assertNotIn("srcset=", copied["text/html"].lower(), "复制HTML应移除可能重新指回本地路径的srcset")
        self.assertIn("text/html", copied["types"], copied)
        self.assertIn("text/plain", copied["types"], copied)
        self.assertIn(copied["via"], {"Clipboard.write", "copy event"}, copied)
        self.assertIsNone(self.evaluate("window.__articleClipboardError||null"), "授权场景的原生 Clipboard.write 应成功解析")
        self.wait_for("document.querySelector('#articleCopyFeedback')?.textContent.includes('正文已复制')", "正文复制成功后应在按钮旁反馈")

        # 从另一 host/origin 读取真实系统剪贴板，再粘进 contenteditable，证明图像字节不依赖原 localhost 地址。
        other_origin=f"http://localhost:{type(self).http_port}"
        self.cdp("Browser.grantPermissions", {"origin":other_origin,"permissions":["clipboardReadWrite","clipboardSanitizedWrite"]})
        self.cdp("Page.navigate", {"url":f"{other_origin}/clipboard-target"})
        self.wait_for("document.readyState==='complete' && location.hostname==='localhost' && document.querySelector('#clipboard-paste-target')", "不同origin剪贴板目标页没有加载")
        pasted=self.evaluate("""(async()=>{
          try{
            const items=await navigator.clipboard.read();let html='';
            for(const item of items)if(item.types.includes('text/html'))html=await (await item.getType('text/html')).text();
            if(!html)return {error:'clipboard has no text/html'};
            const editor=document.createElement('div');editor.id='clipboard-paste-target';editor.contentEditable='true';document.body.replaceChildren(editor);editor.focus();editor.innerHTML=html;
            const image=editor.querySelector('img');if(!image)return {error:'pasted HTML has no image',html};
            await image.decode();
            const response=await fetch(image.src);const bytes=new Uint8Array(await response.arrayBuffer());
            let binary='';for(let offset=0;offset<bytes.length;offset+=0x8000)binary+=String.fromCharCode(...bytes.subarray(offset,offset+0x8000));
            return {origin:location.origin,html,src:image.getAttribute('src'),width:image.naturalWidth,height:image.naturalHeight,bytesBase64:btoa(binary)};
          }catch(error){return {error:String(error)}}
        })()""")
        self.assertNotIn("error",pasted,pasted)
        self.assertEqual(pasted["origin"],other_origin)
        self.assertTrue(pasted["src"].startswith("data:image/png;base64,"),pasted)
        self.assertEqual((pasted["width"],pasted["height"]),(640,274),pasted)
        self.assertEqual(base64.b64decode(pasted["bytesBase64"]),visible_cover_png(),"跨origin读取的剪贴板粘贴图应保留完整原始PNG字节")

        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey", "返回原文章页失败")
        self.click_element("#articleExportButton")
        self.wait_for("document.querySelector('#articleCopyFeedback')?.textContent.includes('已开始下载')", "导出HTML应在按钮旁报告已开始")
        exported_path = self.download_dir / "摸鱼绿.html"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not exported_path.is_file():
            time.sleep(0.025)
        self.assertTrue(exported_path.is_file(), f"Chromium authorized download did not create {exported_path}")
        exported = exported_path.read_text(encoding="utf-8")
        self.assertIn("<section", exported)
        self.assertIn("正文第一段。", exported)
        self.assertIn("data:image/png;base64,", exported)
        self.assertNotIn("/api/results/", exported)
        self.assertNotIn("已保存", self.evaluate("document.querySelector('#articleCopyFeedback').textContent"), "UI只报告浏览器下载已开始，不能声称文件已写入磁盘")

    def test_missing_managed_image_fails_copy_and_export_without_success_feedback(self):
        type(self).fixture["fail_body_image"] = True
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey && !document.querySelector('#articleCopyButton')?.disabled", "文章复制操作未就绪")
        self.evaluate("""(()=>{window.__articleCopyEventSeen=false;document.addEventListener('copy',()=>window.__articleCopyEventSeen=true,true);})();""")
        self.click_element("#articleCopyButton")
        self.wait_for("document.querySelector('#articleCopyFeedback')?.dataset.state==='error'", "图片读取失败后应明确报告复制失败")
        copy_failure=self.evaluate("({message:document.querySelector('#articleCopyFeedback').textContent,state:document.querySelector('#articleCopyFeedback').dataset.state,event:window.__articleCopyEventSeen})")
        self.assertIn("图片",copy_failure["message"],copy_failure)
        self.assertIn("未复制",copy_failure["message"],copy_failure)
        self.assertFalse(copy_failure["event"],"图片未成功内嵌时不能将原本地URL HTML送入回退剪贴板")

        self.click_element("#articleExportButton")
        self.wait_for("document.querySelector('#articleCopyFeedback')?.dataset.state==='error'", "图片读取失败后应明确报告导出失败")
        export_failure=self.evaluate("({message:document.querySelector('#articleCopyFeedback').textContent,state:document.querySelector('#articleCopyFeedback').dataset.state})")
        self.assertIn("图片",export_failure["message"],export_failure)
        self.assertIn("未导出",export_failure["message"],export_failure)
        self.assertFalse((self.download_dir/"摸鱼绿.html").exists(),"图片读取失败不能启动未便携的HTML下载")

    def test_article_change_during_image_fetch_aborts_prepared_copy(self):
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey && !document.querySelector('#articleCopyButton')?.disabled", "文章复制操作未就绪")
        original_layout = type(self).fixture["article"]["variants"]["moyu-green"]["body_html"]
        original_key = self.evaluate("document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey")
        self.evaluate("""(()=>{
          const original=window.fetch.bind(window);window.__releaseArticleImage=null;
          window.fetch=(url,options)=>String(url).includes('/api/results/result-fixture-image')?new Promise(resolve=>{window.__releaseArticleImage=()=>resolve(original(url,options));}):original(url,options);
        })()""")
        self.click_element("#articleCopyButton")
        self.wait_for("typeof window.__releaseArticleImage==='function'", "复制没有开始读取受管图片")
        article=type(self).fixture["article"]
        article["revision"]+=1
        changed_layout=original_layout.replace("正文第一段。","当前选中排版已替换。")
        article["variants"]["moyu-green"].update({
            "body_html":changed_layout,
            "html_sha256":hashlib.sha256(changed_layout.encode("utf-8")).hexdigest(),
            "valid":True,
        })
        self.evaluate("document.querySelector('#articleRefreshButton').click()")
        changed_key="moyu-green:"+article["variants"]["moyu-green"]["html_sha256"]
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset.previewKey==="+json.dumps(changed_key)+" && document.querySelector('#articlePreviewFrame')?.dataset.loadedPreviewKey==="+json.dumps(changed_key)+" && document.querySelector('#articlePreviewFrame')?.contentDocument?.body?.innerText.includes('当前选中排版已替换。') && document.querySelector('#articleCopyButton')?.disabled",
                      "异步复制期间没有读取到新的已选排版 HTML")
        self.assertNotEqual(original_key,changed_key,"负向场景必须真正改变当前 HTML 的 hash/key")
        self.evaluate("window.__releaseArticleImage()")
        self.wait_for("document.querySelector('#articleCopyFeedback')?.dataset.state==='error'", "文章版本变化后应停止复制")
        result=self.evaluate("({message:document.querySelector('#articleCopyFeedback').textContent,state:document.querySelector('#articleCopyFeedback').dataset.state})")
        self.assertIn("版本已变化",result["message"],result)
        self.assertNotIn("已复制",result["message"],result)

    def test_copy_failures_and_download_start_are_reported_near_their_buttons(self):
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey && !document.querySelector('#articleCopyButton')?.disabled", "文章复制操作未就绪")
        self.evaluate("document.querySelector('#articleTitleDetails').open=true;document.querySelector('#articleCoverDetails').open=true")
        self.evaluate("""(()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new Error('denied');},write:async()=>{throw new Error('denied');}}});document.execCommand=()=>false;document.querySelector('#articleCopyTitleButton').click();})()""")
        self.wait_for("document.querySelector('#articleTitleFeedback')?.dataset.state==='error'", "标题剪贴板拒绝后应显示就近失败状态")
        title_failure = self.evaluate("({message:document.querySelector('#articleTitleFeedback').textContent,selected:document.getSelection()?.toString()})")
        self.assertIn("复制失败", title_failure["message"], title_failure)
        self.assertIn("隔离短标题", title_failure["selected"], title_failure)

        self.evaluate("document.querySelector('#articleCopyCoverButton').click()")
        self.wait_for("document.querySelector('#articleCoverStatus')?.dataset.state==='error'", "图片剪贴板拒绝后应显示就近失败状态")
        self.assertIn("无法复制", self.evaluate("document.querySelector('#articleCoverStatus').textContent"))

        self.evaluate("HTMLAnchorElement.prototype.click=function(){if(this.download)throw new Error('blocked');}")
        self.click_element("#articleDownloadCoverButton")
        self.wait_for("document.querySelector('#articleCoverStatus')?.dataset.state==='error'", "封面下载无法启动时应区别于成功状态")
        self.assertIn("下载未能启动", self.evaluate("document.querySelector('#articleCoverStatus').textContent"))

        self.evaluate("URL.createObjectURL=()=>{throw new Error('blocked');}")
        self.click_element("#articleExportButton")
        self.wait_for("document.querySelector('#articleCopyFeedback')?.dataset.state==='error'", "HTML导出无法启动时应显示就近失败状态")
        self.assertIn("导出未能启动", self.evaluate("document.querySelector('#articleCopyFeedback').textContent"))

    def test_rich_copy_fallback_event_contains_real_html_and_plain_text(self):
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey && !document.querySelector('#articleCopyButton')?.disabled", "文章复制操作未就绪")
        self.evaluate("""(()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:{write:async()=>{throw new Error('simulated permission denial');}}});document.addEventListener('copy',event=>{window.__articleCopyEventPayload={html:event.clipboardData?.getData('text/html')||'',plain:event.clipboardData?.getData('text/plain')||'',prevented:event.defaultPrevented};},false);})()""")
        self.click_element("#articleCopyButton")
        self.wait_for("window.__articleCopyEventPayload?.html && window.__articleCopyEventPayload?.plain", "execCommand回退没有发出带HTML和纯文本的复制事件")
        event_payload = self.evaluate("window.__articleCopyEventPayload")
        self.assertIn("<section", event_payload["html"], event_payload)
        self.assertIn("正文第一段。", event_payload["plain"], event_payload)
        self.assertIn("data:image/png;base64,",event_payload["html"],event_payload)
        self.assertNotIn("/api/results/",event_payload["html"],event_payload)
        self.assertTrue(event_payload["prevented"], event_payload)

    def test_article_variants_change_structure_and_copy_only_current_article_content(self):
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.contentDocument?.querySelector('#articlePreviewContent section p')", "有效初始主题没有显示正文预览")
        original_source = type(self).fixture["article"]["source_markdown"]
        self.assertEqual(len(self.evaluate("[...document.querySelectorAll('[data-theme-id]')].map(node=>node.dataset.themeId)")), 3,
                         "左侧只列文章记录里已保存的三个主题，不能展示未生成目录占位")
        self.assertEqual(type(self).fixture["article_template_reads"], 0, "文章页不需要读取六主题目录")
        self.assertIsNone(self.evaluate("document.querySelector('#articleAgentRequest,#articleAgentAllRequest')"), "文章页不应要求用户复制待生成模板要求")
        initial = self.evaluate("(() => ({sandbox:document.querySelector('#articlePreviewFrame').getAttribute('sandbox'),paragraph:!!document.querySelector('#articlePreviewFrame').contentDocument.querySelector('#articlePreviewContent section p'),toolbar:document.querySelector('#articlePreviewFrame').contentDocument.querySelector('.article-toolbar')!==null}))()")
        self.assertNotIn("allow-scripts", initial["sandbox"].split())
        self.assertFalse(initial["toolbar"], "预览正文不应混入工具栏")
        self.assertTrue(initial["paragraph"])

        self.evaluate("document.querySelector('[data-theme-id=red-white]').click()")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.contentDocument?.querySelector('#articlePreviewContent section table')", "切换主题没有切换到另一种真实排版结构")
        self.wait_for("document.querySelector('[data-theme-id=red-white]')?.getAttribute('aria-pressed')==='true' && document.querySelector('[data-article-status]')?.hidden===true", "版式选择后应显示选中态，不显示全宽成功提示")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and type(self).fixture["article"]["selected_theme_id"] != "red-white":
            time.sleep(0.02)
        self.assertTrue(any(item["method"] == "PUT" and item["body"].get("selected_theme_id") == "red-white" for item in type(self).fixture["requests"]))
        self.assertEqual(type(self).fixture["article"]["selected_theme_id"], "red-white")
        self.assertEqual(type(self).fixture["article"]["source_markdown"], original_source, "主题切换只能更改选择，不能覆盖 Markdown 原文")
        graphite_choice=self.evaluate("document.querySelector('[data-theme-id=graphite-minimal]')?.textContent||''")
        self.assertIn("已保存排版",graphite_choice,"非选中但已保存且完整性有效的主题仍以普通保存状态展示")
        self.assertNotIn("基于其他原文",graphite_choice,"仅标题/正文来源指纹不同不应误报为排版异常")

        captured = self.evaluate("""(async()=>{
          const original=window.ClipboardItem;
          let payload=null;
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{write:async items=>{
            const item=items[0];payload={types:item.types};
            for(const type of item.types)payload[type]=await item.getType(type).then(blob=>blob.text());
          }}});
          document.querySelector('#articleCopyButton').click();
          for(let i=0;i<80&&(!payload?.['text/html']||!payload?.['text/plain']);i++)await new Promise(r=>setTimeout(r,20));
          window.__articleClipboardPayload=payload;
          return payload;
        })()""")
        self.assertIn("text/html", captured["types"], captured)
        self.assertIn("text/plain", captured["types"], captured)
        self.assertIn("<table>", captured["text/html"])
        self.assertNotIn("articleCopyButton", captured["text/html"])
        self.assertIn("正文第一段。", captured["text/plain"])
        self.assertRegex(captured["text/plain"], r"第一行\s+第二行")

        self.evaluate("document.querySelector('[data-theme-id=graphite-minimal]').click()")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.contentDocument?.body?.innerText.includes('过期内容不应显示')", "已保存的历史排版应允许作为历史预览")
        stale = self.evaluate("(() => ({body:document.querySelector('#articlePreviewFrame')?.contentDocument?.body?.innerText,badge:document.querySelector('#articlePreviewBadge')?.textContent,notice:document.querySelector('#articlePreviewHistoryNote')?.hidden,copyDisabled:document.querySelector('#articleCopyButton')?.disabled,exportDisabled:document.querySelector('#articleExportButton')?.disabled,ready:document.querySelector('[data-theme-id=graphite-minimal]')?.dataset.ready}))()")
        self.assertIn("过期内容不应显示", stale["body"])
        self.assertIn("当前排版", stale["badge"])
        self.assertTrue(stale["notice"], stale)
        self.assertFalse(stale["copyDisabled"] or stale["exportDisabled"], stale)
        self.assertEqual(stale["ready"], "true", stale)

    def test_title_restore_during_portable_copy_keeps_selected_html_bytes_and_no_success_banner(self):
        article = type(self).fixture["article"]
        saved_html = article["variants"]["moyu-green"]["body_html"]
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey && !document.querySelector('#articleCopyButton')?.disabled", "初始排版未就绪")
        self.evaluate("""(()=>{
          window.__articleBodyCopies=[];
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{write:async items=>{
            const item=items[0],payload={};
            for(const type of item.types)payload[type]=await item.getType(type).then(blob=>blob.text());
            window.__articleBodyCopies.push(payload);
          }}});
        })()""")
        self.click_element("#articleCopyButton")
        self.wait_for("window.__articleBodyCopies.length===1 && document.querySelector('#articleCopyFeedback')?.dataset.state==='success'", "基准排版复制没有完成")
        baseline = self.evaluate("window.__articleBodyCopies[0]['text/html']")
        self.assertIn("data:image/png;base64,", baseline, "测试须覆盖受管图片准备过程")

        self.evaluate("""(()=>{
          window.__articleOriginalFetch=window.fetch.bind(window);
          window.__holdArticleImage=true;window.__releaseArticleImage=null;
          window.fetch=(url,options)=>{
            if(window.__holdArticleImage&&String(url).includes('/api/results/result-fixture-image'))
              return new Promise(resolve=>{window.__releaseArticleImage=()=>{window.__holdArticleImage=false;resolve(window.__articleOriginalFetch(url,options));};});
            return window.__articleOriginalFetch(url,options);
          };
        })()""")
        self.click_element("#articleCopyButton")
        self.wait_for("typeof window.__releaseArticleImage==='function'", "第二次复制没有进入受管图片读取")
        self.evaluate("document.querySelector('#articleTitleHistoryDetails').open=true")
        self.wait_for("document.querySelector('#articleTitleHistory button[data-version-id=title-v1]') && !document.querySelector('#articleTitleHistory button[data-version-id=title-v1]').disabled", "标题历史未就绪")
        self.click_element("#articleTitleHistory button[data-version-id=title-v1]")
        self.wait_for("document.querySelector('#articleSelectedTitle')?.textContent==='隔离历史标题' && document.querySelector('#articleTitleHistory button[data-version-id=title-v1]')?.getAttribute('aria-pressed')==='true' && document.querySelector('[data-article-status]')?.hidden===true", "采用标题历史后应只更新标题选择，不显示全宽成功提示")
        preview_state = self.evaluate("(()=>{const frame=document.querySelector('#articlePreviewFrame');return {key:frame?.dataset.previewKey,loaded:frame?.dataset.loadedPreviewKey,copyDisabled:document.querySelector('#articleCopyButton')?.disabled};})()")
        self.assertEqual(preview_state["key"], preview_state["loaded"], preview_state)
        self.assertTrue(preview_state["copyDisabled"], "复制操作进行中时仅由忙碌状态禁用按钮")
        self.assertEqual(article["variants"]["moyu-green"]["body_html"], saved_html, "选择标题不能改写已保存排版 HTML")
        self.assertEqual(article["source_markdown"], article_payload()["article"]["source_markdown"], "选择标题不能改写 Markdown")

        self.evaluate("window.__releaseArticleImage()")
        self.wait_for("window.__articleBodyCopies.length===2 && document.querySelector('#articleCopyFeedback')?.dataset.state==='success'", "标题恢复不应中止已经开始的正文复制")
        copied = self.evaluate("window.__articleBodyCopies[1]['text/html']")
        self.assertEqual(copied, baseline, "标题或文章 revision 变化不能改变同一排版的可复制 HTML 字节")
        self.assertTrue(self.evaluate("document.querySelector('#articleCopyButton')?.disabled===false"), "当前已选安全排版在标题变化后仍应可复制")

        original_body_key=self.evaluate("document.querySelector('#articlePreviewFrame')?.dataset?.loadedPreviewKey")
        self.evaluate("window.__holdArticleImage=true;window.__releaseArticleImage=null")
        self.click_element("#articleCopyButton")
        self.wait_for("typeof window.__releaseArticleImage==='function'", "Markdown 正向并发场景没有开始准备受管图片")
        article["revision"]+=1
        article["source_markdown"]+="\n\n并发更新的 Markdown。"
        article["source_sha256"]="source-markdown-concurrently-edited"
        self.evaluate("document.querySelector('#articleRefreshButton').click()")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset.loadedPreviewKey===document.querySelector('#articlePreviewFrame')?.dataset.previewKey && document.querySelector('#articleCopyButton')?.disabled",
                      "内部源文变化后应刷新文章，同时保留同一有效排版与进行中的复制")
        self.assertIn("并发更新的 Markdown。", article["source_markdown"], "源文仍保存在文章数据中")
        self.assertEqual(self.evaluate("document.querySelector('#articlePreviewFrame')?.dataset.loadedPreviewKey"),original_body_key,
                         "源文变化不得重绑或重新加载未变化的排版 HTML")
        self.evaluate("window.__releaseArticleImage()")
        self.wait_for("window.__articleBodyCopies.length===3 && document.querySelector('#articleCopyFeedback')?.dataset.state==='success'", "Markdown 变化不应中止仍指向相同 HTML 的正文复制")
        self.assertEqual(self.evaluate("window.__articleBodyCopies[2]['text/html']"),baseline,"Markdown 来源变化不能改写相同已选 HTML 的便携复制字节")

    def test_title_and_cover_history_selection_copy_download_and_mobile_layout(self):
        type(self).fixture["article"]["title_variants"]["alternate"]["title"] = " 隔离短标题 "
        type(self).fixture["article"]["selected_title_variant_id"] = "alternate"
        self.navigate("/static/article.html?id=article-fixture")
        self.evaluate("document.querySelector('#articleCoverDetails').open=true")
        self.wait_for("document.querySelector('#articleSelectedTitle')?.textContent==='隔离短标题' && document.querySelector('[data-restore-kind=cover][data-version-id=cover-v-cover-a]')", "文章标题与封面版本未从 GET 初始化")
        self.wait_for("document.querySelectorAll('#articleTitleHistory [data-version-kind=title]').length===2 && document.querySelector('#articleTitleHistory button[data-version-id=title-v3]')?.getAttribute('aria-pressed')==='true'", "同名标题历史应去重并优先保留当前版本 ID")
        self.assertFalse(self.evaluate("!!document.querySelector('#articleTitleHistory [data-version-id=title-v2]')"), "同名历史不得重复显示")
        self.assertTrue(self.evaluate("!document.querySelector('[data-view-kind]') && !document.querySelector('#articleVersionPreviewBanner') && !document.querySelector('#articleHistoryLayoutChoices')"), "历史详情不能出现第二层查看/选择控件")
        self.evaluate("document.querySelector('.article-current-title-summary').click()")
        self.wait_for("document.querySelector('#articleTitleDetails')?.open===true && document.querySelector('[data-title-variant-id=long]')", "标题候选没有从标题旁展开")
        self.wait_for("document.querySelector('#articleCoverSummaryImage')?.complete && document.querySelector('#articleCoverSummaryImage')?.naturalWidth===640", "当前封面 fixture 没有加载")
        image_geometry = self.evaluate("(()=>{const image=document.querySelector('#articleCoverSummaryImage');return {loaded:image?.complete,width:image?.naturalWidth,height:image?.naturalHeight,displayWidth:image?.getBoundingClientRect().width,displayHeight:image?.getBoundingClientRect().height,fit:getComputedStyle(image).objectFit};})()")
        self.assertEqual((image_geometry["width"], image_geometry["height"]), (640, 274), image_geometry)
        self.assertEqual(image_geometry["fit"], "contain", image_geometry)
        self.assertGreater(image_geometry["displayWidth"], 150, image_geometry)
        self.assertGreater(image_geometry["displayHeight"], 65, image_geometry)
        self.assertTrue(self.evaluate("document.querySelector('[data-title-variant-id=long]')?.disabled===false"), "来源不同的历史标题仍应允许用户主动复用")
        self.assertTrue(self.evaluate("document.querySelector('[data-restore-kind=cover][data-version-id=cover-v-cover-b]')?.closest('.article-version-row')?.textContent.includes('V2')"), "封面历史应显示版本号而非文件名")
        self.assertFalse(self.evaluate("document.querySelector('#articleCoverHistory')?.textContent.includes('5e87fba7')"), "封面版本列表不能泄露无意义文件名")
        self.save_screenshot("article-three-sections-desktop.png")

        self.evaluate("document.querySelector('[data-title-variant-id=long]').click()")
        self.wait_for("document.querySelector('#articleSelectedTitle')?.textContent==='隔离历史标题' && document.querySelector('[data-title-variant-id=long]')?.getAttribute('aria-pressed')==='true' && document.querySelector('#articleTitleDetails')?.open===false", "切换标题没有立即更新并收起正文标题区域")
        self.wait_for("document.querySelector('[data-article-status]')?.hidden===true", "标题选择后不应显示全宽成功提示")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and type(self).fixture["article"]["selected_title_variant_id"] != "long":
            time.sleep(0.02)
        self.assertEqual(type(self).fixture["article"]["selected_title_variant_id"], "long")
        copied_title = self.evaluate("(async()=>{let value='';Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{value=text;window.__articleTitleCopy=text;}}});document.querySelector('#articleCopyTitleButton').click();for(let i=0;i<80&&!value;i++)await new Promise(r=>setTimeout(r,20));return value;})()")
        self.assertEqual(copied_title, "隔离历史标题")
        self.wait_for("document.querySelector('#articleTitleFeedback')?.textContent==='标题已复制。'", "标题复制成功后应在按钮旁反馈")
        self.assertTrue(any(item["method"] == "PUT" and item["body"].get("selected_title_variant_id") == "long" for item in type(self).fixture["requests"]))

        self.evaluate("document.querySelector('#articleTitleHistoryDetails').open=true")
        self.wait_for("document.querySelector('#articleTitleHistory button[data-version-id=title-v1]')?.getAttribute('aria-pressed')==='true' && document.querySelectorAll('#articleTitleHistory [data-version-kind=title]').length===2", "保存新标题后标题历史活动态/trim 去重未更新")
        self.wait_for("document.querySelector('#articleTitleHistory button[data-version-id=title-v2]')", "同名短标题版本没有留下唯一整卡")
        title_restore_revision=type(self).fixture["article"]["revision"]
        title_restore_count=len(type(self).fixture["article_version_restores"])
        restore_button_state=self.evaluate("(()=>{const button=document.querySelector('#articleTitleHistory button[data-version-id=title-v2]');return {buttons:[...document.querySelectorAll('#articleTitleHistory button[data-version-id]')].map(item=>({id:item.dataset.versionId,disabled:item.disabled,pressed:item.getAttribute('aria-pressed')})),disabled:button?button.disabled:null,pressed:button?.getAttribute('aria-pressed'),current:button?.getAttribute('aria-current'),text:button?.parentElement?.textContent,status:document.querySelector('[data-article-status]')?.textContent};})()")
        self.assertIsNotNone(restore_button_state["disabled"],restore_button_state)
        self.assertFalse(restore_button_state["disabled"],restore_button_state)
        self.click_element("#articleTitleHistory button[data-version-id=title-v2]")
        self.wait_for("document.querySelector('#articleSelectedTitle')?.textContent==='隔离短标题' && document.querySelector('#articleTitleHistory button[data-version-id=title-v2]')?.getAttribute('aria-pressed')==='true' && document.querySelector('[data-article-status]')?.hidden===true", "标题历史整卡点击没有直接恢复并更新当前标题，或仍显示全宽成功提示")
        self.assertEqual(type(self).fixture["article"]["revision"],title_restore_revision+1)
        self.assertEqual(len(type(self).fixture["article_version_restores"]),title_restore_count+1)
        self.assertEqual(type(self).fixture["article_version_restores"][-1]["kind"],"title")
        copied_restored_title = self.evaluate("(async()=>{let value='';Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{value=text;}}});document.querySelector('#articleCopyTitleButton').click();for(let i=0;i<80&&!value;i++)await new Promise(r=>setTimeout(r,20));return value;})()")
        self.assertEqual(copied_restored_title,"隔离短标题","恢复后的当前标题复制内容应同步")

        self.wait_for("document.querySelector('#articleCoverHistory [data-version-id=cover-v-cover-b] .article-history-cover-thumb')?.complete && document.querySelector('#articleCoverHistory [data-version-id=cover-v-cover-b] .article-history-cover-thumb')?.naturalWidth===640", "封面历史卡片未加载公开缩略图")
        before_cover_card = len(type(self).fixture["requests"])
        revision_before_restore=type(self).fixture["article"]["revision"]
        before_restore_count=len(type(self).fixture["article_version_restores"])
        self.click_element("#articleCoverHistory [data-version-id=cover-v-cover-b] .article-history-cover-thumb")
        self.wait_for("document.querySelector('#articleCurrentCoverPreview')?.dataset.coverPreviewId==='cover-b' && document.querySelector('#articleCopyCoverButton')?.disabled===false && document.querySelector('[data-article-status]')?.hidden===true", "历史封面没有作为当前封面恢复，或仍显示全宽成功提示")
        self.assertFalse(self.evaluate("document.querySelector('#articleCoverLightbox')?.open"), "历史封面缩略图点击应直接恢复，不能打开原图放大")
        self.assertEqual(len(type(self).fixture["article_version_restores"]),before_restore_count+1,"真实坐标点击历史封面缩略图只执行一次直接恢复")
        self.assertFalse(any(item["method"]=="GET" and item["path"].endswith("/versions/cover/cover-v-cover-b") for item in type(self).fixture["requests"][before_cover_card:]),"列表缩略图应直接使用公开 media，不额外读取详情")
        self.assertEqual(type(self).fixture["article"]["selected_cover_variant_id"], "cover-b")
        self.assertEqual(type(self).fixture["article"]["revision"], revision_before_restore+1)
        self.assertTrue(any(item["method"]=="POST" and item["path"].endswith("/versions/cover/cover-v-cover-b/restore") and item["body"].get("expected_revision")==revision_before_restore for item in type(self).fixture["requests"]))
        self.assertFalse(any(item["method"]=="PUT" and "selected_cover_variant_id" in item.get("body",{}) for item in type(self).fixture["requests"]))
        selected_cover_view = self.evaluate("(() => {const button=document.querySelector('#articleCurrentCoverPreview'),image=document.querySelector('#articleCoverSummaryImage');return {id:button?.dataset.coverPreviewId,src:image?.getAttribute('src'),selected:document.querySelector('#articleCoverHistory [data-restore-kind=cover][data-version-id=cover-v-cover-b]')?.getAttribute('aria-pressed')};})()")
        self.assertEqual(selected_cover_view["id"], "cover-b", selected_cover_view)
        self.assertTrue(selected_cover_view["src"].endswith("/fixture/cover.png"), selected_cover_view)
        self.assertEqual(selected_cover_view["selected"], "true", selected_cover_view)
        self.evaluate("document.querySelector('#articleBodyHistoryDetails').open=true;document.querySelector('#articleCoverDetails').open=true")
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        self.wait_for("document.querySelector('[data-article-status]')?.hidden===true", "封面恢复提示没有结束，避免将短暂反馈误当页面内容截图")
        self.evaluate("window.StudioTheme?.set?.('dark')")
        self.wait_for("document.documentElement.dataset.studioAppearance==='dark'", "深色主题没有应用")
        desktop_path=self.save_validation_screenshot("article-history-cards-cover-desktop-dark.png")
        self.evaluate("window.StudioTheme?.set?.('light')")
        self.wait_for("document.documentElement.dataset.studioAppearance==='light'", "浅色主题没有恢复")
        light_path=self.save_validation_screenshot("article-history-cards-cover-desktop-light.png")
        before_current_zoom_puts = len([item for item in type(self).fixture["requests"] if item["method"] == "PUT"])
        revision_before_current_zoom = type(self).fixture["article"]["revision"]
        self.evaluate("document.querySelector('#articleCurrentCoverPreview').click()")
        self.wait_for("document.querySelector('#articleCoverLightbox')?.open && document.querySelector('#articleCoverLightboxImage')?.naturalWidth===640", "当前封面图片没有打开完整预览")
        self.assertEqual(type(self).fixture["article"]["revision"], revision_before_current_zoom, "点击当前封面放大不能保存")
        self.assertEqual(len([item for item in type(self).fixture["requests"] if item["method"] == "PUT"]), before_current_zoom_puts)
        self.evaluate("document.querySelector('#articleCoverLightboxClose').click()")
        copied_cover = self.evaluate("(async()=>{let payload=null;Object.defineProperty(navigator,'clipboard',{configurable:true,value:{write:async items=>{const item=items[0],type=item.types[0],blob=await item.getType(type);payload={type,size:blob.size};window.__articleCoverClipboard=payload;}}});document.querySelector('#articleCopyCoverButton').click();for(let i=0;i<100&&!payload;i++)await new Promise(r=>setTimeout(r,20));return payload;})()")
        self.assertEqual(copied_cover["type"], "image/png", copied_cover)
        self.assertGreater(copied_cover["size"], 0, copied_cover)
        self.wait_for("document.querySelector('#articleCoverStatus')?.textContent==='封面图片已复制。'", "封面复制成功后应在按钮旁反馈")
        self.click_element("#articleDownloadCoverButton")
        self.wait_for("document.querySelector('#articleCoverStatus')?.textContent.includes('已开始下载')", "封面下载应只报告已开始")
        self.assertNotIn("下载完成", self.evaluate("document.querySelector('#articleCoverStatus').textContent"))
        cover_download = self.download_dir / "5e87fba7-4dc0-4a91-aaa0-13725c585db6_image_1.png"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not cover_download.is_file():
            time.sleep(0.025)
        self.assertTrue(cover_download.is_file(), f"Chromium did not preserve the original cover filename: {cover_download}")
        self.assertTrue(cover_download.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(any(item["method"] == "POST" and item["path"].endswith("/versions/cover/cover-v-cover-b/restore") for item in type(self).fixture["requests"]))

        self.evaluate("document.querySelector('#articleFullPreviewButton').click()")
        self.assertTrue(self.evaluate("document.querySelector('.article-preview-region')?.classList.contains('is-full-preview')"))
        self.cdp("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "Escape", "windowsVirtualKeyCode": 27})
        self.cdp("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "windowsVirtualKeyCode": 27})
        self.assertFalse(self.evaluate("document.querySelector('.article-preview-region')?.classList.contains('is-full-preview')"))

        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 320, "height": 740, "deviceScaleFactor": 1, "mobile": True})
        mobile = self.evaluate("({width:innerWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,buttons:[...document.querySelectorAll('#articleCopyTitleButton,#articleCopyCoverButton,#articleFullPreviewButton')].map(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,hidden:el.hidden};})})")
        self.assertEqual(mobile["width"], 320, mobile)
        self.assertLessEqual(mobile["documentWidth"], 320, mobile)
        self.assertLessEqual(mobile["bodyWidth"], 320, mobile)
        self.assertTrue(all(item["left"] >= 0 and item["right"] <= 320 for item in mobile["buttons"]), mobile)
        self.evaluate("document.querySelector('#articleCurrentCoverPreview').click()")
        self.wait_for("document.querySelector('#articleCoverLightbox')?.open", "窄屏下无法打开封面预览")
        mobile_lightbox = self.evaluate("(() => {const d=document.querySelector('#articleCoverLightbox'),i=document.querySelector('#articleCoverLightboxImage');return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,dialog:d.getBoundingClientRect().toJSON(),image:i.getBoundingClientRect().toJSON(),fit:getComputedStyle(i).objectFit,close:document.querySelector('#articleCoverLightboxClose').getBoundingClientRect().toJSON()};})()")
        self.assertLessEqual(mobile_lightbox["documentWidth"], 320, mobile_lightbox)
        self.assertLessEqual(mobile_lightbox["dialog"]["width"], 320, mobile_lightbox)
        self.assertGreater(mobile_lightbox["image"]["width"], 250, mobile_lightbox)
        self.assertEqual(mobile_lightbox["fit"], "contain")
        self.assertLessEqual(mobile_lightbox["close"]["right"], 320, mobile_lightbox)
        self.evaluate("document.querySelector('#articleCoverLightboxClose').click()")
        self.assertFalse(self.evaluate("document.querySelector('#articleCoverLightbox')?.open"))
        self.evaluate("document.querySelector('#articleManagementDrawer').open=true;document.querySelector('#articleBodyHistoryDetails').open=true;document.querySelector('#articleCoverDetails').open=true")
        self.evaluate("document.querySelector('.article-layout-rail').scrollTop=document.querySelector('.article-layout-rail').scrollHeight")
        mobile_path = self.save_validation_screenshot("article-history-cards-320.png")
        self.assertTrue(mobile_path.is_file() and mobile_path.stat().st_size > 1000, str(mobile_path))
        self.assertTrue(desktop_path.is_file() and desktop_path.stat().st_size>1000 and light_path.is_file() and light_path.stat().st_size>1000)

    def test_article_selection_conflict_reloads_latest_content_without_marking_draft_saved(self):
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('[data-theme-id=red-white]')", "文章主题选择未加载")
        type(self).fixture["article_put_conflict_once"] = True
        self.evaluate("document.querySelector('[data-theme-id=red-white]').click()")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.contentDocument?.body?.innerText.includes('并发更新后的正文')", "409 后没有读取并发更新的最新文章内容")
        self.assertTrue(self.evaluate("document.querySelector('[data-theme-id=red-white]')?.getAttribute('aria-pressed')==='true'"), "冲突后应保留用户刚选的主题草稿")
        self.assertTrue(self.evaluate("document.querySelector('[data-article-status]')?.textContent.includes('未保存草稿')"), "409 后不能把本地选择显示为已保存")
        self.assertEqual(type(self).fixture["article"]["revision"], 4)
        self.assertEqual(type(self).fixture["article"]["selected_theme_id"], "moyu-green")
        self.assertTrue(any(item["method"] == "GET" and item["path"] == "/api/studio/articles/article-fixture" for item in type(self).fixture["requests"]))

    def test_article_settings_embeds_the_shared_canvas_and_resets_atomically(self):
        self.navigate("/static/api-settings.html")
        self.wait_for("document.querySelector('#articleSettingsNav')", "API 设置没有公众号文章配置入口")
        self.evaluate("document.querySelector('#articleSettingsNav').click()")
        self.wait_for("document.querySelector('#articleSettingsCanvasFrame')?.contentWindow?.location?.search.includes('id=article-settings')", "文章配置没有挂载专用共享画布")
        self.wait_for("document.querySelector('#articleSettingsCanvasFrame')?.contentDocument?.documentElement?.dataset?.canvasMode==='article-settings'", "画布没有识别文章配置模式")
        self.wait_for("document.querySelector('#articleSettingsCanvasFrame')?.contentDocument?.readyState==='complete'", "文章配置画布静态页面没有完成加载")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and type(self).fixture["article_canvas_gets"] == 0:
            time.sleep(0.025)
        self.assertEqual(type(self).fixture["article_canvas_bootstraps"], 1)
        self.assertEqual(type(self).fixture["article_canvas_gets"], 1, self.evaluate("JSON.stringify({title:document.querySelector('#articleSettingsCanvasFrame')?.contentDocument?.querySelector('#smartTitle')?.textContent,body:document.querySelector('#articleSettingsCanvasFrame')?.contentDocument?.body?.innerText?.slice(0,120)})"))

        self.evaluate("document.querySelector('#articleSettingsCanvasFrame').contentDocument.querySelector('#hypitOutputDrawerToggle').click()")
        self.evaluate("document.querySelector('#articleSettingsCanvasFrame').contentDocument.querySelector('#hypitOutputDrawer [data-hypit-slot=image]').click()")
        self.wait_for("document.querySelector('#articleSettingsCanvasFrame')?.contentDocument?.querySelector('.hypit-output-node[data-hypit-slot=image')", "文章配置画布未创建共享图片输出端口")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not type(self).fixture["article_canvas_puts"]:
            time.sleep(0.025)
        self.assertEqual(len(type(self).fixture["article_canvas_puts"]), 1, type(self).fixture["article_canvas_puts"])
        stored = type(self).fixture["article_canvas"]
        self.assertEqual(stored["id"], "article-settings")
        self.assertEqual(len(stored["nodes"]), 1)
        self.assertEqual(stored["nodes"][0]["type"], "smart-hypit-output")
        self.assertEqual(stored["nodes"][0]["hypitSlot"], "image")
        self.assertNotIn("purpose", stored["nodes"][0], "用途类别仅属于文章生成任务，不应固化为节点参数")
        self.assertEqual(type(self).fixture["article_model_option_requests"], [])
        self.assertEqual([item["path"] for item in type(self).fixture["requests"] if item["method"] == "PUT"], ["/api/canvases/article-settings"])

        self.evaluate("window.StudioI18n?.set?.('en')")
        self.wait_for("window.StudioI18n?.lang?.()==='en' && document.querySelector('#articleSettingsCanvasFrame')?.contentDocument?.documentElement?.dataset?.canvasMode==='article-settings'", "切换文章配置语言时页面没有稳定响应")
        self.evaluate("window.StudioI18n?.set?.('zh')")
        self.evaluate("document.querySelector('#articleSettingsNewTab')?.click()")
        opened = ""
        for _ in range(60):
            urls = [item.get("url", "") for item in self.targets() if item.get("type") == "page"]
            opened = next((url for url in urls if "/static/smart-canvas.html?id=article-settings&mode=article-settings" in url and "embedded=1" not in url), "")
            if opened:
                break
            time.sleep(0.1)
        self.assertTrue(opened, f"文章配置独立页没有经过bootstrap打开正确共享画布：{self.targets()}")
        import urllib.request
        for item in self.targets():
            if item.get("type") == "page" and item.get("url") == opened and item.get("id") != type(self).target.get("id"):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{type(self).debug_port}/json/close/{item['id']}", timeout=2).read()
                except Exception:
                    pass

        frame = "document.querySelector('#articleSettingsCanvasFrame').contentDocument"
        self.evaluate(f"(()=>{{const shell={frame}.querySelector('#shell');shell.dispatchEvent(new MouseEvent('contextmenu',{{bubbles:true,cancelable:true,button:2,clientX:620,clientY:500}}));{frame}.querySelector('.create-menu [data-create-type=image-generator]').click();}})()")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not any(module == "article" and slot == "image" for module, slot in type(self).fixture["article_model_option_requests"]):
            time.sleep(0.025)
        self.assertIn(("article", "image"), type(self).fixture["article_model_option_requests"], "文章配置的图片生成节点必须请求 Article 槽候选，而不是 Hypit/全局候选")

        self.evaluate(f"(()=>{{const shell={frame}.querySelector('#shell');shell.dispatchEvent(new MouseEvent('contextmenu',{{bubbles:true,cancelable:true,button:2,clientX:640,clientY:520}}));{frame}.querySelector('.create-menu [data-create-type=audio-generator]').click();}})()")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not all(("article", slot) in type(self).fixture["article_model_option_requests"] for slot in ("audio", "voice")):
            time.sleep(0.025)
        self.assertTrue(all(("article", slot) in type(self).fixture["article_model_option_requests"] for slot in ("audio", "voice")),
                        f"未连接的文章音频节点应按 Article 音效/语音用途加载候选：{type(self).fixture['article_model_option_requests']}")

        self.evaluate(f"(()=>{{const shell={frame}.querySelector('#shell');shell.dispatchEvent(new MouseEvent('contextmenu',{{bubbles:true,cancelable:true,button:2,clientX:660,clientY:540}}));{frame}.querySelector('.create-menu [data-create-type=music-generator]').click();}})()")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and ("article", "music") not in type(self).fixture["article_model_option_requests"]:
            time.sleep(0.025)
        self.assertIn(("article", "music"), type(self).fixture["article_model_option_requests"], "独立音乐生成节点必须使用 Article music 槽，而不是混进音频节点")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and len(type(self).fixture["article_canvas"]["nodes"]) < 4:
            time.sleep(0.025)
        self.assertGreaterEqual(len(type(self).fixture["article_canvas_puts"]), 2, "执行节点应写入与输出端口相同的标准画布")
        stored = type(self).fixture["article_canvas"]
        self.assertEqual({node.get("type") for node in stored["nodes"]}, {"smart-hypit-output", "smart-image-generator", "smart-audio-generator", "smart-music-generator"})
        puts_before_reset = len(type(self).fixture["article_canvas_puts"])

        self.evaluate("window.StudioDialog={confirm:async()=>true};void window.resetArticleSettingsCanvas()")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not type(self).fixture["article_canvas_resets"]:
            time.sleep(0.025)
        self.assertEqual(len(type(self).fixture["article_canvas_resets"]), 1)
        self.wait_for("document.querySelector('#articleSettingsCanvasFrame')?.contentDocument?.querySelectorAll('.hypit-output-node').length===0", "服务端原子重置后嵌入画布仍显示旧节点")
        self.assertEqual(len(type(self).fixture["article_canvas_puts"]), puts_before_reset, "重置不应另外 PUT 空画布")
        self.assertGreaterEqual(type(self).fixture["article_canvas_gets"], 1, "重置后仍应只读取共享画布数据源")
        self.assertEqual([item["path"] for item in type(self).fixture["requests"] if item["method"] == "POST"], ["/api/studio/articles/settings-canvas/reset"])

    def test_article_body_compare_reads_immutable_layouts_into_independent_panes(self):
        self.navigate("/static/article.html?id=article-fixture")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.dataset.loadedPreviewKey && document.querySelector('#articleBodyHistoryDetails')", "文章正文没有准备好")
        self.evaluate("document.querySelector('#articleBodyHistoryDetails').open=true")
        self.wait_for("document.querySelector('#articleBodyHistory [data-layout-preview-version=body-v1][data-preview-state=ready] iframe')?.contentDocument?.body?.innerText.includes('旧版本正文')", "历史正文预览卡片没有准备好")
        revision_before = type(self).fixture["article"]["revision"]
        selected_before = type(self).fixture["article"]["selected_theme_id"]
        mutations_before = len([item for item in type(self).fixture["requests"] if item["method"] in {"POST", "PUT"}])
        restores_before = len(type(self).fixture["article_version_restores"])

        self.click_element("#articleCompareTab")
        self.wait_for("document.querySelector('#articleCompareTab')?.getAttribute('aria-selected')==='true' && document.querySelector('#articleComparePanel')?.hidden===false", "正文对比标签没有打开")
        self.wait_for("document.querySelector('#articleCompareLeftFrame')?.contentDocument?.body?.innerText.includes('正文第一段') && document.querySelector('#articleCompareRightFrame')?.hidden===true", "进入对比时左栏应显示当前安全排版，右栏保持空提示")
        self.assertEqual(self.evaluate("document.querySelector('[data-compare-select=left]')?.getAttribute('aria-pressed')"), "true")
        self.assertTrue(self.evaluate("document.querySelector('#articleCopyButton')?.hidden && document.querySelector('#articleExportButton')?.hidden && document.querySelector('#articleFullPreviewButton')?.hidden && !document.querySelector('#articleCopyTitleButton')?.hidden && document.querySelector('#articleCompareActionHint')?.classList.contains('article-visually-hidden')"), "对比视图应隐藏单篇正文操作，保留标题复制并提供屏幕阅读器说明")

        self.evaluate("(()=>{window.__compareOriginalFetch=window.fetch.bind(window);window.__compareHoldId='body-v1';window.__compareHoldUsed=false;window.fetch=(url,options)=>{const match=String(url).match(/\\/versions\\/body\\/([^/?]+)/);if(match&&match[1]===window.__compareHoldId&&!window.__compareHoldUsed){window.__compareHoldUsed=true;return new Promise((resolve,reject)=>{window.__releaseCompareRequest=()=>window.__compareOriginalFetch(url,options).then(resolve,reject);});}return window.__compareOriginalFetch(url,options);};})()")
        self.click_element("#articleBodyHistory [data-layout-preview-version=body-v1] iframe")
        self.wait_for("typeof window.__releaseCompareRequest==='function'", "点击正文历史卡片后应只发起版本详情 GET")
        self.click_element("[data-compare-select=right]")
        self.assertEqual(self.evaluate("document.querySelector('[data-compare-select=right]')?.getAttribute('aria-pressed')"), "true")
        self.assertIn("右栏", self.evaluate("document.querySelector('#articleBodyHistory button[data-version-id=body-v1]')?.getAttribute('aria-label')"))
        self.click_element("#articleBodyHistory [data-layout-preview-version=body-v2] iframe")
        self.wait_for("document.querySelector('#articleCompareRightFrame')?.contentDocument?.body?.innerText.includes('正文第一段') && document.querySelector('[data-compare-lane=right] [data-compare-version-label]')?.textContent.includes('V2')", "V2 应载入右栏而不改当前文章")
        self.evaluate("window.__releaseCompareRequest();window.__compareHoldId=''")
        self.wait_for("document.querySelector('#articleCompareLeftFrame')?.contentDocument?.body?.innerText.includes('旧版本正文') && document.querySelector('#articleCompareRightFrame')?.contentDocument?.body?.innerText.includes('正文第一段')", "较慢的左栏 V1 响应不能覆盖右栏 V2")

        self.evaluate("window.__compareHoldId='body-v2';window.__compareHoldUsed=false;window.__releaseCompareRequest=null")
        self.click_element("[data-compare-select=left]")
        self.click_element("#articleBodyHistory [data-layout-preview-version=body-v2] iframe")
        self.wait_for("typeof window.__releaseCompareRequest==='function'", "同栏竞态测试未拦截 V2 读取")
        self.click_element("#articleBodyHistory [data-layout-preview-version=body-v1] iframe")
        self.wait_for("document.querySelector('#articleCompareLeftFrame')?.contentDocument?.body?.innerText.includes('旧版本正文')", "同栏新选择 V1 应先完成")
        self.evaluate("window.__releaseCompareRequest();window.__compareHoldId=''")
        self.wait_for("document.querySelector('#articleCompareLeftFrame')?.contentDocument?.body?.innerText.includes('旧版本正文') && document.querySelector('[data-compare-lane=left] [data-compare-version-label]')?.textContent.includes('V1')", "同栏较慢旧响应不得覆盖较新的 V1")

        self.click_element("[data-compare-select=right]")
        self.click_element("#articleCompareLeftFrame")
        self.wait_for("document.querySelector('[data-compare-select=left]')?.getAttribute('aria-pressed')==='true'", "点击左栏预览正文内部应选中左栏目标")
        self.click_element("#articleBodyHistory [data-layout-preview-version=body-v2] iframe")
        self.wait_for("document.querySelector('#articleCompareLeftFrame')?.contentDocument?.body?.innerText.includes('正文第一段') && document.querySelector('#articleCompareRightFrame')?.contentDocument?.body?.innerText.includes('正文第一段')", "预览正文内部选中左栏后，点击 V2 应只更新左栏")

        geometry = self.evaluate("(()=>{const left=document.querySelector('#articleCompareLeftFrame'),right=document.querySelector('#articleCompareRightFrame'),scroll=document.querySelector('.article-compare-scroll');for(const f of [left,right])f.contentDocument.body.style.minHeight='1800px';left.contentWindow.scrollTo(0,140);right.contentWindow.scrollTo(0,360);return {left:{y:left.contentWindow.scrollY,height:left.getBoundingClientRect().height,body:left.contentDocument.documentElement.scrollHeight},right:{y:right.contentWindow.scrollY,height:right.getBoundingClientRect().height,body:right.contentDocument.documentElement.scrollHeight},host:scroll.getBoundingClientRect().toJSON()};})()")
        self.assertGreater(geometry["left"]["height"], 200, geometry)
        self.assertGreater(geometry["right"]["height"], 200, geometry)
        self.assertNotEqual(geometry["left"]["y"], geometry["right"]["y"], "左右 iframe 的滚动位置必须独立")

        self.evaluate("(()=>{for(const id of ['articleCompareLeftFrame','articleCompareRightFrame'])document.querySelector('#'+id).contentWindow.scrollTo(0,0)})()")
        wheel_point=self.evaluate("(()=>{const r=document.querySelector('#articleCompareLeftFrame').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()")
        self.cdp("Input.dispatchMouseEvent", {"type":"mouseWheel","x":wheel_point["x"],"y":wheel_point["y"],"deltaX":0,"deltaY":320})
        self.wait_for("document.querySelector('#articleCompareLeftFrame')?.contentWindow?.scrollY>0", "鼠标滚轮应只滚动指针所在的左栏预览")
        self.assertEqual(self.evaluate("document.querySelector('#articleCompareRightFrame')?.contentWindow?.scrollY"), 0, "左栏滚动不得同步右栏位置")

        self.assertTrue(self.evaluate("!document.querySelector('#articleSourceTab') && !document.querySelector('#articleSourceDetails')"), "对比视图不应提供 Markdown 原文标签")
        self.evaluate("document.querySelector('#articlePreviewTab').click()")
        self.wait_for("document.querySelector('#articlePreviewFrame')?.contentDocument?.body?.innerText.includes('正文第一段') && document.querySelector('#articlePreviewTab')?.getAttribute('aria-selected')==='true'", "切回单篇预览应仍显示当前正文")
        self.assertEqual(type(self).fixture["article"]["revision"], revision_before, "比较历史不得改变文章 revision")
        self.assertEqual(type(self).fixture["article"]["selected_theme_id"], selected_before, "比较历史不得改变当前主题")
        self.assertEqual(len(type(self).fixture["article_version_restores"]), restores_before, "比较历史不得 POST restore")
        self.assertEqual(len([item for item in type(self).fixture["requests"] if item["method"] in {"POST", "PUT"}]), mutations_before, "对比过程不得 POST/PUT")
        self.assertTrue(any(item["method"]=="GET" and item["path"].endswith("/versions/body/body-v1") for item in type(self).fixture["requests"]))
        self.assertTrue(any(item["method"]=="GET" and item["path"].endswith("/versions/body/body-v2") for item in type(self).fixture["requests"]))
        self.assertEqual(self.evaluate("document.querySelector('#articleCopyButton')?.disabled"), False, "离开对比后正文复制应恢复")
        self.assertTrue(self.evaluate("!document.querySelector('#articleCopyButton')?.hidden && !document.querySelector('#articleExportButton')?.hidden && !document.querySelector('#articleFullPreviewButton')?.hidden"), "离开对比后单篇正文操作应恢复可见")

        self.evaluate("document.querySelector('#articleCompareTab').click();document.querySelector('#articleBodyHistoryDetails').open=true")
        self.wait_for("document.querySelector('#articleCompareLeftFrame')?.contentDocument?.body?.innerText.includes('正文第一段')", "重新进入对比后应保留本页已有的比较对象")
        self.click_element("[data-compare-select=left]")
        self.click_element("#articleBodyHistory [data-layout-preview-version=body-v1] iframe")
        self.wait_for("document.querySelector('#articleCompareLeftFrame')?.contentDocument?.body?.innerText.includes('旧版本正文') && document.querySelector('#articleCompareRightFrame')?.contentDocument?.body?.innerText.includes('正文第一段') && document.querySelector('[data-compare-lane=left] [data-compare-version-label]')?.textContent.includes('V1') && document.querySelector('[data-compare-lane=right] [data-compare-version-label]')?.textContent.includes('V2')", "截图应显示左栏V1与右栏V2两个不同历史版本")
        self.evaluate("(()=>{for(const id of ['articleCompareLeftFrame','articleCompareRightFrame'])document.querySelector('#'+id).contentWindow.scrollTo(0,0)})()")
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        self.evaluate("window.StudioTheme?.set?.('dark')")
        self.wait_for("document.documentElement.dataset.studioAppearance==='dark'", "对比截图未能应用深色主题")
        desktop_path=self.save_validation_screenshot("article-body-compare-desktop-dark.png")
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 740, "deviceScaleFactor": 1, "mobile": True})
        self.wait_for("innerWidth===390", "对比窄屏视口未生效")
        self.evaluate("document.querySelector('#articleManagementDrawer').open=false;window.StudioTheme?.set?.('light')")
        self.wait_for("document.documentElement.dataset.studioAppearance==='light'", "对比窄屏截图未能应用浅色主题")
        mobile_geometry=self.evaluate("(()=>{const scroll=document.querySelector('.article-compare-scroll'),grid=document.querySelector('.article-compare-grid'),left=document.querySelector('#articleCompareLeftFrame'),right=document.querySelector('#articleCompareRightFrame');return {viewport:innerWidth,document:document.documentElement.scrollWidth,host:scroll.getBoundingClientRect().toJSON(),scrollWidth:scroll.scrollWidth,clientWidth:scroll.clientWidth,grid:grid.getBoundingClientRect().toJSON(),columns:getComputedStyle(grid).gridTemplateColumns,left:left.getBoundingClientRect().toJSON(),right:right.getBoundingClientRect().toJSON()};})()")
        self.assertEqual(mobile_geometry["viewport"],390,mobile_geometry)
        self.assertLessEqual(mobile_geometry["document"],390,mobile_geometry)
        self.assertGreater(mobile_geometry["scrollWidth"],mobile_geometry["clientWidth"],mobile_geometry)
        self.assertGreater(mobile_geometry["left"]["height"],200,mobile_geometry)
        self.assertGreater(mobile_geometry["right"]["height"],200,mobile_geometry)
        mobile_path=self.save_validation_screenshot("article-body-compare-390.png")
        self.assertTrue(desktop_path.is_file() and desktop_path.stat().st_size>1000,str(desktop_path))
        self.assertTrue(mobile_path.is_file() and mobile_path.stat().st_size>1000,str(mobile_path))


if __name__ == "__main__":
    unittest.main()
