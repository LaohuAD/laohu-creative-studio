import json
import hashlib
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from studio_connection import create_connection_router
from studio_articles import validate_article_html


ROOT = Path(__file__).resolve().parents[1]


class _VisibleArticleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(" ".join(data.split()))


class _TemplateStructureSignature(HTMLParser):
    """锁定 Git 原画廊的 DOM 顺序与样式，只允许替换正文和内容属性。"""

    CONTENT_ATTRIBUTES = {"alt", "href", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events = []
        self.leaf_count = 0

    def handle_starttag(self, tag, attrs):
        normalized = []
        for name, value in sorted(attrs):
            if name == "style":
                normalized.append((name, value))
            elif name in self.CONTENT_ATTRIBUTES:
                normalized.append((name, "<content>"))
            else:
                normalized.append((name, value))
        self.events.append(("open", tag, tuple(normalized)))
        if tag == "span" and "leaf" in dict(attrs):
            self.leaf_count += 1

    def handle_endtag(self, tag):
        self.events.append(("close", tag))


TEMPLATE_STRUCTURE_BASELINES = {
    "graphite-minimal": ("1fc07a36688f727eab5b3c62e0554b7b47c852f7313e989c196ad81f35902776", 120),
    "moyu-green": ("19887dca53617cd1c7d0972d6a3075e1aa9de2f746276b0df44bf76f7313d853", 146),
    "moyu-ticket": ("56be60037a8262344b18987ec7bac969c0e422b575155c9972c84c3b453e565a", 136),
    "olive-journal": ("8215509ee488a67fc7d9d2ac1e7f57e2afad7696e4a767296e8d010872bca5af", 143),
    "red-white": ("3b1849d5985e5994cced3b6a6821a34317fe658855acdac3d06f5a833d8ef50c", 118),
    "zen-whitespace": ("1045c6db8cbc3e470c9930d7fbcd279b635324ac12e63d33cc36d961648add45", 109),
}


class StudioArticleConnectionTests(unittest.TestCase):
    def setUp(self):
        self.project_calls = []

        def get_project(project_id, module):
            self.project_calls.append((project_id, module))
            return {"id": project_id, "module": module, "name": "保留原文的文章"}

        app = FastAPI()
        app.include_router(create_connection_router(get_project))
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_article_connection_uses_revisioned_article_and_template_api_in_both_languages(self):
        for lang in ("zh", "en"):
            with self.subTest(lang=lang):
                prompt = self.client.get(
                    f"/api/studio/projects/article-1/connection?module=article&lang={lang}"
                ).json()
                self.assertEqual(prompt["project_id"], "article-1")
                self.assertEqual(prompt["module"], "article")
                self.assertIn("article-1", prompt["text"])
                self.assertIn(prompt["document_url"], prompt["text"])
                self.assertLess(len(prompt["text"]), 420)
                self.assertIn("不自动创作" if lang == "zh" else "do not create content", prompt["text"])
                self.assertIn("关联当前文章" if lang == "zh" else "connect this article", prompt["text"])

                response = self.client.get(prompt["document_url"])
                self.assertEqual(response.status_code, 200)
                self.assertIn("/api/studio/articles/article-1", response.text)
                self.assertIn("/api/studio/articles/templates", response.text)
                self.assertIn("templates", response.text)
                self.assertIn("preview_url", response.text)
                self.assertIn("catalog_fingerprint", response.text)
                self.assertIn("expected_catalog_fingerprint", response.text)
                self.assertIn(
                    "预览示例仅供浏览" if lang == "zh" else "Previews are for browsing",
                    response.text,
                )
                self.assertIn("source_sha256", response.text)
                self.assertIn("expected_revision", response.text)
                self.assertIn("409", response.text)
                self.assertIn("selected_theme_id", response.text)
                self.assertIn("title_variants", response.text)
                self.assertIn("cover_variants", response.text)
                self.assertIn("media_refs", response.text)
                self.assertIn("data:image", response.text)
                self.assertIn("stable asset_id/result_id" if lang == "en" else "稳定 asset_id/result_id", response.text)
                self.assertIn("does not fetch arbitrary HTTPS images" if lang == "en" else "不会自动抓取任意 HTTPS 图片", response.text)
                self.assertIn(
                    "仅限用户明确要求相关创作时" if lang == "zh" else "only for explicitly requested work",
                    response.text,
                )
                self.assertIn("client_operation_id", response.text)
                self.assertIn("output_node_id", response.text)
                self.assertIn("purpose", response.text)
                self.assertIn("run_id", response.text)
                self.assertIn("标题和正文 HTML 不会由文本/媒体任务自动改写" if lang == "zh" else "Text generation does not rewrite the title", response.text)
                self.assertIn("不自动用新 ID 重发" if lang == "zh" else "do not automatically resubmit with a new ID", response.text)
                self.assertIn("缺少有效版本时" if lang == "zh" else "If no valid version exists", response.text)
                self.assertIn("也不发布" if lang == "zh" else "does not publish", response.text)
                self.assertNotIn("仍在实现" if lang == "zh" else "still being integrated", response.text)
                self.assertIn("text/markdown", response.headers["content-type"])

        self.assertEqual(self.project_calls, [("article-1", "article")] * 4)

    def test_article_skill_preparation_reuses_parent_entry_and_official_installer_instructions(self):
        for lang in ("zh", "en"):
            with self.subTest(lang=lang):
                prompt = self.client.get(
                    f"/api/studio/modules/article/preparation?lang={lang}"
                ).json()
                detail = self.client.get(prompt["document_url"])
                self.assertEqual(detail.status_code, 200)
                self.assertIn("github.com/LaohuAD/laohu-creative-skills.git", detail.text)
                self.assertIn("/laohu-htmlshow", detail.text)
                self.assertIn("laohu-htmlshow-gzh", detail.text)
                self.assertIn("tools/install.py", detail.text)
                self.assertIn("/laohu-update", detail.text)
                self.assertIn("preserve local changes" if lang == "en" else "保留本地修改", detail.text)
                self.assertIn("ask before updating" if lang == "en" else "询问", detail.text)
                self.assertIn("安装" if lang == "zh" else "install", detail.text.lower())
                self.assertIn("不" if lang == "zh" else "not", detail.text.lower())
                self.assertIn(prompt["document_url"], prompt["text"])

    def test_canvas_preparation_keeps_manual_canvas_available_and_points_to_real_skill_repository(self):
        for lang in ("zh", "en"):
            with self.subTest(lang=lang):
                prompt = self.client.get(
                    f"/api/studio/modules/canvas/preparation?lang={lang}"
                ).json()
                detail = self.client.get(prompt["document_url"])
                self.assertEqual(detail.status_code, 200)
                self.assertIn("github.com/LaohuAD/laohu-creative-skills.git", detail.text)
                self.assertIn("/laohu", detail.text)
                self.assertIn("/laohu-update", detail.text)
                self.assertIn("保留本地修改" if lang == "zh" else "preserve local changes", detail.text)
                self.assertIn("手动" if lang == "zh" else "manual", detail.text.lower())
                self.assertIn("已有" if lang == "zh" else "reuse", detail.text.lower())

    def test_module_preparation_waits_for_project_choice_without_claiming_project_connection(self):
        for module in ("canvas", "hypit", "article"):
            for lang in ("zh", "en"):
                with self.subTest(module=module, lang=lang):
                    prompt = self.client.get(
                        f"/api/studio/modules/{module}/preparation?lang={lang}"
                    ).json()
                    detail = self.client.get(prompt["document_url"])
                    self.assertEqual(detail.status_code, 200)
                    if lang == "zh":
                        self.assertIn("等待我选择", prompt["text"])
                        self.assertIn("等待用户选择", detail.text)
                        self.assertNotIn("关联当前项目", prompt["text"])
                        self.assertNotIn("接入当前项目", detail.text)
                        self.assertNotIn("接入当前文章", detail.text)
                    else:
                        self.assertIn("wait for me to choose", prompt["text"])
                        self.assertIn("wait for the user to choose", detail.text)
                        self.assertNotIn("connect the project", prompt["text"].lower())
                        self.assertNotIn("connect to the current project", detail.text.lower())
                        self.assertNotIn("connect to the current article", detail.text.lower())

    def test_catalog_templates_keep_the_original_full_gallery_structure(self):
        catalog = json.loads((ROOT / "static" / "article-templates" / "catalog.json").read_text(encoding="utf-8"))
        signatures = set()
        for item in catalog["templates"]:
            path = ROOT / "static" / item["preview_url"].removeprefix("/static/")
            preview = path.read_text(encoding="utf-8")
            signature = _TemplateStructureSignature()
            signature.feed(preview)
            expected_signature, expected_leaf_count = TEMPLATE_STRUCTURE_BASELINES[item["id"]]
            actual_signature = hashlib.sha256(repr(signature.events).encode("utf-8")).hexdigest()
            self.assertEqual(actual_signature, expected_signature, f"{item['id']} 的原组件、顺序、样式或属性被改动")
            self.assertEqual(signature.leaf_count, expected_leaf_count, item["id"])
            signatures.add(actual_signature)
        self.assertEqual(len(signatures), 6, "六种 gallery 版式应保留各自的完整结构差异")

    def test_catalog_examples_replace_gallery_copy_and_preserve_license(self):
        catalog_path = ROOT / "static" / "article-templates" / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.assertEqual(len(catalog["templates"]), 6)
        self.assertEqual(len({item["id"] for item in catalog["templates"]}), 6)
        self.assertEqual(catalog["source_repository"], "https://github.com/LaohuAD/laohu-creative-skills.git")
        fingerprints = catalog["source_fingerprints"]
        self.assertRegex(fingerprints["theme_index"], r"^[a-f0-9]{64}$")
        self.assertRegex(fingerprints["common_components"], r"^[a-f0-9]{64}$")
        self.assertEqual(set(fingerprints["themes"]), {item["id"] for item in catalog["templates"]})

        shared_copy = (
            "我是老胡", "老胡画梦枋", "Hypit", "老胡造梦技能",
            "画布", "公众号", "标题", "封面", "正文", "作品",
        )
        reference_copy = (
            "教程", "开源", "https://lao-hu.com/", "https://lao-hu.com/projects/",
            "https://lao-hu.com/learn/", "https://github.com/LaohuAD/laohu-creative-skills",
        )
        removed_gallery_copy = (
            "甲木", "Moyu Xiaoli", "2026.07", "Agent 不抹平能力差距",
            "个人产品的复利飞轮", "点赞、在看、转发三连",
        )
        format_markers = {
            "graphite-minimal": ("大标题", "引用", "有序列表示例", "表格示例"),
            "moyu-green": ("大标题", "引用", "有序列表示例", "表格示例"),
            "moyu-ticket": ("从念头到作品", "四个入口", "共享素材示意"),
            "olive-journal": ("开始前可以记下", "创作入口", "共享素材示意"),
            "red-white": ("大标题", "引用", "有序列表示例", "表格示例"),
            "zen-whitespace": ("大标题", "引用", "竖向编号重点示例", "图片说明示例"),
        }
        all_visible = []
        for item in catalog["templates"]:
            self.assertTrue(item["name"] and item["name_en"])
            self.assertTrue(item["description"] and item["description_en"])
            self.assertRegex(item["color"], r"^#[A-Fa-f0-9]{6}$")
            preview_path = ROOT / "static" / item["preview_url"].removeprefix("/static/")
            self.assertTrue(preview_path.is_file(), item["id"])
            preview = preview_path.read_text(encoding="utf-8")
            self.assertTrue(preview.startswith("<!-- 主题示例预览，非用户文章。"))
            self.assertIn(f"docs-gallery/{item['id']}.html", preview)

            visible_parser = _VisibleArticleText()
            visible_parser.feed(preview)
            visible = " ".join(visible_parser.parts)
            all_visible.append(visible)
            for phrase in shared_copy:
                self.assertIn(phrase, visible, f"{item['id']} is missing {phrase}")
            for marker in format_markers[item["id"]]:
                self.assertIn(marker, visible, f"{item['id']} lost an original-layout teaching marker")
            for removed in removed_gallery_copy:
                self.assertNotIn(removed, visible, f"{item['id']} leaks prior gallery copy: {removed}")
            self.assertNotIn("<script", preview.lower())
            self.assertNotIn("<style", preview.lower())
            self.assertNotIn("<svg", preview.lower())
            self.assertNotIn("<mp-style-type", preview.lower())
            validate_article_html(preview)

        # 原模板的页脚容量不同；站点入口在六篇合计中完整出现即可，不要求每种排版重复塞入全部长 URL。
        combined_visible = " ".join(all_visible)
        for phrase in reference_copy:
            self.assertIn(phrase, combined_visible, f"六种预览都应保留真实创作信息入口：{phrase}")

        notice = (ROOT / "static" / "article-templates" / "NOTICE.md").read_text(encoding="utf-8")
        self.assertIn("Copyright (C) 2026 甲木", notice)
        self.assertIn("AGPL-3.0-or-later", notice)
        self.assertTrue((ROOT / "static" / "article-templates" / "LICENSE").is_file())

    def test_unknown_module_remains_a_404(self):
        response = self.client.get("/api/studio/modules/not-a-module/preparation.md")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
