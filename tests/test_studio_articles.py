import base64
import importlib
import importlib.util
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from project_storage import ProjectStorage
from studio_projects import StudioProjectStore, create_studio_projects_router


class FakeCanvasAdapter:
    def list(self):
        return []

    def get(self, project_id):
        return None

    def create(self, name):
        raise AssertionError("文章服务不得创建画布")

    def rename(self, project_id, name, expected_revision=None):
        raise AssertionError("文章服务不得改写画布")

    def delete(self, project_id, expected_revision=None):
        raise AssertionError("文章服务不得删除画布")


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP_ROOT = REPO_ROOT / "cache" / "studio-tests" / "tmp"
REAL_CATALOG = REPO_ROOT / "static" / "article-templates" / "catalog.json"


def catalog_fixture(path: Path):
    ids = (
        "moyu-green", "red-white", "graphite-minimal",
        "zen-whitespace", "moyu-ticket", "olive-journal",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "source_fingerprints": {
            "theme_index": "fixture-index",
            "common_components": "fixture-common",
            "themes": {theme_id: f"fixture-{theme_id}" for theme_id in ids},
        },
        "templates": [{
            "id": theme_id,
            "name": theme_id,
            "name_en": theme_id,
            "color": "#059669",
            "description": "fixture description",
            "description_en": "fixture description",
            "preview_url": f"/static/article-templates/{theme_id}.html",
        } for theme_id in ids],
    }), encoding="utf-8")
    return path


def fake_media_reference(asset_id: str, result_id: str):
    ref_id = asset_id or result_id
    refs = {
        "mat_cover": ("image", "image/png", "cover.png"),
        "res_cover": ("image", "image/png", "cover-result.png"),
        "mat_video": ("video", "video/mp4", "clip.mp4"),
        "res_audio": ("audio", "audio/wav", "voice.wav"),
        "mat_text": ("text", "text/plain", "notes.txt"),
        "res_text": ("text", "text/markdown", "draft.md"),
    }
    if ref_id not in refs:
        return None
    prefix = "materials" if asset_id else "results"
    kind, mime, name = refs[ref_id]
    return {
        "id": ref_id,
        "kind": kind,
        "url": f"/api/{prefix}/{ref_id}",
        "name": name,
        "mime": mime,
    }


def find_shared_media_by_hash(storage: ProjectStorage, digest: str, kind: str):
    """模拟生产共享索引查询，同时核对索引文件确实存在且哈希一致。"""
    collections = []
    if kind == "image":
        collections.append((storage.list_materials(kind=kind), "asset"))
    collections.append((storage.list_results(kind=kind), "result"))
    for records, ref_kind in collections:
        for item in records:
            if item.get("sha256") != digest:
                continue
            item_id = str(item.get("id") or "")
            path = storage.material_path(item_id) if ref_kind == "asset" else storage.result_path(item_id)
            if path is None or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                continue
            return {
                "asset_id": item_id if ref_kind == "asset" else "",
                "result_id": item_id if ref_kind == "result" else "",
                "sha256": digest,
                "kind": item.get("kind") or "",
                "url": item.get("url") or "",
                "name": item.get("display_name") or item.get("original_name") or "",
                "mime": item.get("mime") or "",
                "path": str(path),
            }
    return None


def client_for(root: Path, *, catalog_path: Path | None = None, include_connection: bool = False,
               resolve_media_reference=fake_media_reference, submit_generation=None, get_generation=None,
               project_storage: ProjectStorage | None = None):
    module = importlib.import_module("studio_articles")
    project_store = StudioProjectStore(root, FakeCanvasAdapter())
    project_storage = project_storage or ProjectStorage(root)
    project_storage.ensure_layout()

    def resolve_media(asset_id: str, result_id: str):
        resolved = resolve_media_reference(asset_id, result_id) if resolve_media_reference else None
        if resolved is not None:
            return resolved
        if asset_id:
            record = project_storage.get_material(asset_id)
            path = project_storage.material_path(asset_id) if record else None
            if not record or path is None or not path.is_file() or path.stat().st_size <= 0:
                return None
            return {
                "url": project_storage.material_url(asset_id),
                "name": record.get("display_name") or record.get("original_name") or "",
                "mime": record.get("mime") or "",
                "kind": record.get("kind") or "",
            }
        if not result_id:
            return None
        record = project_storage.get_result(result_id)
        path = project_storage.result_path(result_id) if record else None
        if not record or path is None or not path.is_file() or path.stat().st_size <= 0:
            return None
        return {
            "url": project_storage.result_url(result_id),
            "name": record.get("display_name") or record.get("original_name") or "",
            "mime": record.get("mime") or "",
            "kind": record.get("kind") or "",
        }

    app = FastAPI()
    app.include_router(create_studio_projects_router(root, FakeCanvasAdapter(), store=project_store))
    if include_connection:
        from studio_connection import create_connection_router
        app.include_router(create_connection_router(project_store.get))
    app.include_router(module.create_studio_articles_router(
        root,
        project_store,
        catalog_path=catalog_path or catalog_fixture(root / "static" / "article-templates" / "catalog.json"),
        resolve_media_reference=resolve_media,
        register_managed_result=project_storage.register_managed_result,
        find_shared_media_by_hash=lambda digest, kind: find_shared_media_by_hash(project_storage, digest, kind),
        submit_generation=submit_generation,
        get_generation=get_generation,
    ))
    return TestClient(app)


GOOD_HTML = (
    '<section><p><span leaf="">一段保留原文的正文。</span></p>'
    '<img alt="示意图" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/6j8AAAAASUVORK5CYII=" '
    'style="max-width:100%;height:auto;display:block;margin:0 auto"></section>'
)
SECOND_GOOD_HTML = '<section><h2><span leaf="">另一个真实主题结构</span></h2><p><span leaf="">同一来源的第二种排版。</span></p></section>'


class StudioArticleTests(unittest.TestCase):
    def test_article_service_module_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("studio_articles"), "公众号文章 API 尚未实现")

    def test_new_article_projects_default_to_moyu_green_without_rewriting_existing_selection(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            with client_for(Path(temporary)) as client:
                created = client.post("/api/studio/projects", json={"module": "article", "name": "新文章"})
                self.assertEqual(created.status_code, 200, created.text)
                first_project = created.json()["project"]
                first_path = f"/api/studio/articles/{first_project['id']}"
                first = client.get(first_path).json()["article"]
                self.assertEqual(first["selected_theme_id"], "moyu-green")

                selected = client.put(first_path, json={
                    "expected_revision": first["revision"],
                    "selected_theme_id": "red-white",
                })
                self.assertEqual(selected.status_code, 200, selected.text)
                self.assertEqual(selected.json()["article"]["selected_theme_id"], "red-white")

                second = client.post("/api/studio/projects", json={"module": "article", "name": "另一篇文章"})
                self.assertEqual(second.status_code, 200, second.text)
                second_path = f"/api/studio/articles/{second.json()['project']['id']}"
                self.assertEqual(client.get(second_path).json()["article"]["selected_theme_id"], "moyu-green")
                self.assertEqual(client.get(first_path).json()["article"]["selected_theme_id"], "red-white")

    def test_template_catalog_and_project_article_round_trip(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            root = Path(temporary)
            with client_for(root, catalog_path=REAL_CATALOG) as client:
                created = client.post("/api/studio/projects", json={"module": "article", "name": "草稿项目"})
                self.assertEqual(created.status_code, 200, created.text)
                project = created.json()["project"]
                catalog = client.get("/api/studio/articles/templates")
                self.assertEqual(catalog.status_code, 200, catalog.text)
                self.assertEqual(
                    catalog.json()["catalog_fingerprint"],
                    hashlib.sha256(REAL_CATALOG.read_bytes()).hexdigest(),
                )
                self.assertEqual({item["id"] for item in catalog.json()["templates"]}, {
                    "moyu-green", "red-white", "graphite-minimal", "zen-whitespace", "moyu-ticket", "olive-journal",
                })

                current = client.get(f"/api/studio/articles/{project['id']}")
                self.assertEqual(current.status_code, 200, current.text)
                article = current.json()["article"]
                self.assertEqual(article["project_id"], project["id"])
                self.assertEqual(article["revision"], project["revision"])
                self.assertEqual(article["source_markdown"], "")

                saved = client.put(f"/api/studio/articles/{project['id']}", json={
                    "expected_revision": article["revision"],
                    "title": "文章标题",
                    "source_markdown": "# 文章标题\n\n一段保留原文的正文。",
                    "selected_theme_id": "moyu-green",
                    "variants": {"moyu-green": {"body_html": GOOD_HTML}},
                })
                self.assertEqual(saved.status_code, 200, saved.text)
                rendered = saved.json()["article"]
                self.assertTrue(rendered["variants"]["moyu-green"]["valid"])
                self.assertEqual(rendered["variants"]["moyu-green"]["body_html"], GOOD_HTML)
                self.assertTrue(rendered["selected_title_variant_id"])
                self.assertEqual(rendered["title_variants"][rendered["selected_title_variant_id"]]["title"], "文章标题")

    def test_html_variants_are_shared_text_results_without_duplicate_files_or_index_entries(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            root = Path(temporary)
            storage = ProjectStorage(root)
            with client_for(root, project_storage=storage) as client:
                project = client.post("/api/studio/projects", json={"module": "article", "name": "共享排版"}).json()["project"]
                path = f"/api/studio/articles/{project['id']}"
                article = client.get(path).json()["article"]
                saved = client.put(path, json={
                    "expected_revision": article["revision"],
                    "title": "共享结果标题",
                    "source_markdown": "一段文章正文。",
                    "variants": {"moyu-green": {"body_html": GOOD_HTML}},
                })
                self.assertEqual(saved.status_code, 200, saved.text)
                variant = saved.json()["article"]["variants"]["moyu-green"]
                self.assertEqual(variant["result_kind"], "text")
                self.assertTrue(variant["result_mime"].startswith("text/html"))
                self.assertEqual(variant["result_url"], storage.result_url(variant["result_id"]))

                managed = storage.get_result(variant["result_id"])
                result_path = storage.result_path(variant["result_id"])
                expected_html = root / "assets" / "output" / "text" / "articles" / f"{variant['html_sha256']}.html"
                self.assertEqual(managed["kind"], "text")
                self.assertEqual(managed["sha256"], variant["html_sha256"])
                self.assertEqual(result_path, expected_html)
                self.assertEqual(result_path.read_text(encoding="utf-8"), GOOD_HTML)
                self.assertIn(variant["result_id"], {item["id"] for item in storage.list_results("text")})
                self.assertEqual(len(variant["embedded_media_ids"]), 1)
                embedded_id = variant["embedded_media_ids"][0]
                embedded = storage.get_result(embedded_id)
                self.assertEqual(embedded["kind"], "image")
                self.assertIn(embedded_id, {item["id"] for item in storage.list_results("image")})
                article_media = saved.json()["article"]["media_refs"]
                self.assertTrue(any(item["result_id"] == embedded_id and item["valid"] for item in article_media))
                result_count = len(storage.list_results())
                html_files = list((root / "assets" / "output" / "text" / "articles").glob("*.html"))
                image_files = list((root / "assets" / "output" / "image" / "articles").glob("*.png"))
                self.assertEqual(len(html_files), 1)
                self.assertEqual(len(image_files), 1)

                # 同一版本重复保存和读取都复用同一哈希文件及登记项。
                repeated = client.put(path, json={
                    "expected_revision": saved.json()["article"]["revision"],
                    "variants": {"moyu-green": {"body_html": GOOD_HTML}},
                })
                self.assertEqual(repeated.status_code, 200, repeated.text)
                repeated_variant = repeated.json()["article"]["variants"]["moyu-green"]
                self.assertEqual(repeated_variant["result_id"], variant["result_id"])
                self.assertEqual(repeated_variant["embedded_media_ids"], variant["embedded_media_ids"])
                self.assertEqual(len(storage.list_results()), result_count)
                self.assertEqual(len(list((root / "assets" / "output" / "text" / "articles").glob("*.html"))), 1)
                self.assertEqual(len(list((root / "assets" / "output" / "image" / "articles").glob("*.png"))), 1)
                fetched = client.get(path).json()["article"]["variants"]["moyu-green"]
                self.assertTrue(fetched["result_available"])
                self.assertEqual(fetched["result_id"], variant["result_id"])

                # 模拟旧文章 JSON：GET 幂等补登记，并只写回稳定 result_id，不抬升用户修订号。
                record_path = root / "data" / "studio_projects" / f"{project['id']}.json"
                record = json.loads(record_path.read_text(encoding="utf-8"))
                stored_variant = record["article"]["variants"]["moyu-green"]
                stored_variant.pop("result_id", None)
                stored_variant.pop("result_url", None)
                stored_variant.pop("result_kind", None)
                stored_variant.pop("result_mime", None)
                record_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
                storage._save_index(storage.result_index_path, {"version": 2, "items": []})
                before_revision = record["revision"]
                migrated = client.get(path)
                self.assertEqual(migrated.status_code, 200, migrated.text)
                migrated_variant = migrated.json()["article"]["variants"]["moyu-green"]
                self.assertTrue(migrated_variant["result_id"].startswith("res_"))
                self.assertTrue(migrated_variant["result_available"])
                after_record = json.loads(record_path.read_text(encoding="utf-8"))
                self.assertEqual(after_record["revision"], before_revision)
                self.assertEqual(len(storage.list_results()), result_count)
                self.assertEqual(after_record["article"]["variants"]["moyu-green"]["result_id"], migrated_variant["result_id"])
                repeated_get = client.get(path).json()["article"]["variants"]["moyu-green"]
                self.assertEqual(repeated_get["result_id"], migrated_variant["result_id"])

    def test_embedded_image_reuses_existing_shared_material_without_copy(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            root = Path(temporary)
            storage = ProjectStorage(root)
            storage.ensure_layout()
            match = re.search(r"data:image/png;base64,([^\" ]+)", GOOD_HTML)
            png = base64.b64decode(match.group(1))
            original = storage.store_material_bytes(png, "共享图片.png", scope="asset", content_type="image/png")
            original_path = storage.material_path(original["id"])
            before_files = sorted(path.relative_to(root) for path in (root / "assets").rglob("*") if path.is_file())
            with client_for(root, project_storage=storage) as client:
                project = client.post("/api/studio/projects", json={"module": "article", "name": "复用已有图片"}).json()["project"]
                article_path = f"/api/studio/articles/{project['id']}"
                article = client.get(article_path).json()["article"]
                saved = client.put(article_path, json={
                    "expected_revision": article["revision"],
                    "title": "已有素材",
                    "source_markdown": "正文",
                    "variants": {"moyu-green": {"body_html": GOOD_HTML}},
                })
                self.assertEqual(saved.status_code, 200, saved.text)
                variant = saved.json()["article"]["variants"]["moyu-green"]
                self.assertEqual(variant["embedded_media_ids"], [original["id"]])
                self.assertFalse((root / "assets" / "output" / "image" / "articles").exists())
                references = saved.json()["article"]["media_refs"]
                self.assertTrue(any(item["asset_id"] == original["id"] and item["valid"] for item in references))
                after_files = sorted(path.relative_to(root) for path in (root / "assets").rglob("*") if path.is_file())
                self.assertEqual(
                    after_files,
                    sorted(before_files + [Path("assets/output/text/articles") / f"{variant['html_sha256']}.html"]),
                )
                self.assertEqual(storage.material_path(original["id"]), original_path)

    def test_embedded_image_reuses_existing_shared_result_without_copy(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            root = Path(temporary)
            storage = ProjectStorage(root)
            storage.ensure_layout()
            match = re.search(r"data:image/png;base64,([^\" ]+)", GOOD_HTML)
            png = base64.b64decode(match.group(1))
            existing_path = root / "assets" / "output" / "image" / "shared" / "existing.png"
            existing_path.parent.mkdir(parents=True, exist_ok=True)
            existing_path.write_bytes(png)
            original = storage.register_managed_result(existing_path, "共享图片.png")
            before_files = sorted(path.relative_to(root) for path in (root / "assets").rglob("*") if path.is_file())
            before_results = len(storage.list_results())

            with client_for(root, project_storage=storage) as client:
                project = client.post("/api/studio/projects", json={"module": "article", "name": "复用图片结果"}).json()["project"]
                article_path = f"/api/studio/articles/{project['id']}"
                article = client.get(article_path).json()["article"]
                saved = client.put(article_path, json={
                    "expected_revision": article["revision"],
                    "title": "已有图片结果",
                    "source_markdown": "正文",
                    "variants": {"moyu-green": {"body_html": GOOD_HTML}},
                })
                self.assertEqual(saved.status_code, 200, saved.text)
                variant = saved.json()["article"]["variants"]["moyu-green"]
                self.assertEqual(variant["embedded_media_ids"], [original["id"]])
                self.assertFalse((root / "assets" / "output" / "image" / "articles").exists())
                self.assertEqual(storage.result_path(original["id"]), existing_path)
                self.assertEqual(len(storage.list_results()), before_results + 1)  # 仅新增 HTML 正文结果
                after_files = sorted(path.relative_to(root) for path in (root / "assets").rglob("*") if path.is_file())
                self.assertEqual(
                    after_files,
                    sorted(before_files + [Path("assets/output/text/articles") / f"{variant['html_sha256']}.html"]),
                )

    def test_corrupt_shared_result_index_blocks_article_write_without_overwrite(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            root = Path(temporary)
            storage = ProjectStorage(root)
            with client_for(root, project_storage=storage) as client:
                project = client.post("/api/studio/projects", json={"module": "article", "name": "索引保护"}).json()["project"]
                article_path = f"/api/studio/articles/{project['id']}"
                article = client.get(article_path).json()["article"]
                record_path = root / "data" / "studio_projects" / f"{project['id']}.json"
                before_record = record_path.read_bytes()
                index_path = storage.result_index_path
                damaged_index = b"{broken index"
                index_path.write_bytes(damaged_index)

                failed = client.put(article_path, json={
                    "expected_revision": article["revision"],
                    "title": "不应提交",
                    "source_markdown": "原稿应保留",
                    "variants": {"moyu-green": {"body_html": GOOD_HTML}},
                })

                self.assertEqual(failed.status_code, 500)
                self.assertIn("共享素材索引不可读取", failed.json()["detail"])
                self.assertEqual(index_path.read_bytes(), damaged_index)
                self.assertEqual(record_path.read_bytes(), before_record)
                self.assertFalse((root / "assets" / "output" / "text" / "articles").exists())
                self.assertFalse((root / "assets" / "output" / "image" / "articles").exists())

    def test_html_variant_reuses_existing_shared_text_result_path(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            root = Path(temporary)
            storage = ProjectStorage(root)
            storage.ensure_layout()
            existing_path = root / "assets" / "output" / "text" / "archive" / "shared-copy.html"
            existing_path.parent.mkdir(parents=True, exist_ok=True)
            existing_path.write_text(GOOD_HTML, encoding="utf-8")
            existing_hash = hashlib.sha256(GOOD_HTML.encode("utf-8")).hexdigest()
            existing = storage.register_managed_result(existing_path, "shared-copy.html")
            before_files = sorted(path.relative_to(root) for path in (root / "assets").rglob("*") if path.is_file())
            before_results = len(storage.list_results())
            with client_for(root, project_storage=storage) as client:
                project = client.post("/api/studio/projects", json={"module": "article", "name": "复用排版"}).json()["project"]
                path = f"/api/studio/articles/{project['id']}"
                article = client.get(path).json()["article"]
                saved = client.put(path, json={
                    "expected_revision": article["revision"],
                    "title": "已有排版结果",
                    "source_markdown": "正文",
                    "variants": {"moyu-green": {"body_html": GOOD_HTML}},
                })
                self.assertEqual(saved.status_code, 200, saved.text)
                variant = saved.json()["article"]["variants"]["moyu-green"]
                self.assertEqual(variant["html_sha256"], existing_hash)
                self.assertEqual(variant["result_id"], existing["id"])
                self.assertEqual(variant["result_url"], existing["url"])
                self.assertEqual(variant["body_html"], GOOD_HTML)
                self.assertEqual(len(storage.list_results()), before_results + 1)
                record_path = root / "data" / "studio_projects" / f"{project['id']}.json"
                record = json.loads(record_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    record["article"]["variants"]["moyu-green"]["path"],
                    "assets/output/text/archive/shared-copy.html",
                )
                self.assertFalse((root / "assets" / "output" / "text" / "articles").exists())
                after_files = sorted(path.relative_to(root) for path in (root / "assets").rglob("*") if path.is_file())
                embedded_id = variant["embedded_media_ids"][0]
                embedded_path = storage.result_path(embedded_id)
                self.assertEqual(after_files, sorted(before_files + [embedded_path.relative_to(root)]))

    def test_nested_spans_do_not_end_a_leaf_and_gallery_css_properties_are_supported(self):
        from studio_articles import ArticleValidationError, validate_article_html
        validate_article_html(
            '<section><p style="background-color:#fff;padding-right:12px">'
            '<span leaf="">正文<span style="font-weight:700">嵌套强调</span>继续正文</span>'
            '</p></section>'
        )
        with self.assertRaises(ArticleValidationError):
            validate_article_html('<section><p><span leaf="">正文</span><span>叶子外文字</span></p></section>')
        with self.assertRaises(ArticleValidationError):
            validate_article_html('<section><img src="data:image/png;base64,aGVsbG8=" /></section>')

    def test_title_and_cover_history_are_immutable_and_old_media_loss_does_not_break_article_read(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            missing_ids = set()
            def resolver(asset_id, result_id):
                if (asset_id or result_id) in missing_ids:
                    return None
                return fake_media_reference(asset_id, result_id)
            with client_for(Path(temporary), resolve_media_reference=resolver) as client:
                project = client.post("/api/studio/projects", json={"module": "article", "name": "版本测试"}).json()["project"]
                path = f"/api/studio/articles/{project['id']}"
                first = client.get(path).json()["article"]
                saved = client.put(path, json={
                    "expected_revision": first["revision"],
                    "title": "标题甲",
                    "source_markdown": "正文甲",
                    "title_variants": {
                        "title_candidate_b": {"title": "候选标题乙"},
                    },
                    "cover_variants": [{"asset_id": "mat_cover"}],
                })
                self.assertEqual(saved.status_code, 200, saved.text)
                article = saved.json()["article"]
                self.assertEqual(article["title_variants"]["title_candidate_b"]["title"], "候选标题乙")
                cover = article["cover_variants"][0]
                self.assertEqual(cover["asset_id"], "mat_cover")
                self.assertEqual(cover["url"], "/api/materials/mat_cover")
                self.assertTrue(cover["valid"])

                # 历史标题可应用到新正文；服务端另记当前组合，不覆盖原历史候选。
                changed = client.put(path, json={
                    "expected_revision": article["revision"],
                    "source_markdown": "正文乙",
                    "selected_title_variant_id": "title_candidate_b",
                    "selected_cover_variant_id": cover["id"],
                })
                self.assertEqual(changed.status_code, 200, changed.text)
                current = changed.json()["article"]
                self.assertEqual(current["title"], "候选标题乙")
                self.assertNotEqual(current["selected_title_variant_id"], "title_candidate_b")
                self.assertEqual(current["title_variants"]["title_candidate_b"]["title"], "候选标题乙")
                self.assertFalse(current["title_variants"]["title_candidate_b"]["source_matches"])
                self.assertEqual(current["title_variants"][current["selected_title_variant_id"]]["title"], "候选标题乙")
                self.assertTrue(current["title_variants"][current["selected_title_variant_id"]]["source_matches"])
                self.assertEqual(current["selected_cover_variant_id"], cover["id"])
                self.assertTrue(current["cover_variants"][0]["valid"])
                self.assertFalse(current["cover_variants"][0]["source_matches"])

                # 失联历史素材保留为不可用版本，正文本身仍可读取。
                missing_ids.add("mat_cover")
                unavailable = client.get(path)
                self.assertEqual(unavailable.status_code, 200, unavailable.text)
                unavailable_article = unavailable.json()["article"]
                self.assertEqual(unavailable_article["source_markdown"], "正文乙")
                self.assertFalse(unavailable_article["cover_variants"][0]["valid"])
                self.assertTrue(unavailable_article["cover_variants"][0]["error"])

    def test_generic_media_refs_preserve_all_supported_managed_kinds(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            with client_for(Path(temporary)) as client:
                project = client.post("/api/studio/projects", json={"module": "article", "name": "媒体引用"}).json()["project"]
                path = f"/api/studio/articles/{project['id']}"
                article = client.get(path).json()["article"]
                saved = client.put(path, json={
                    "expected_revision": article["revision"],
                    "media_refs": [
                        {"asset_id": "mat_cover"},
                        {"result_id": "res_cover"},
                        {"asset_id": "mat_video"},
                        {"result_id": "res_audio"},
                        {"asset_id": "mat_text"},
                        {"result_id": "res_text"},
                    ],
                })
                self.assertEqual(saved.status_code, 200, saved.text)
                refs = saved.json()["article"]["media_refs"]
                self.assertEqual({item["kind"] for item in refs}, {"image", "video", "audio", "text"})
                self.assertEqual(len(refs), 6)
                wrong_cover = client.put(path, json={
                    "expected_revision": saved.json()["article"]["revision"],
                    "cover_variants": [{"asset_id": "mat_video"}],
                })
                self.assertEqual(wrong_cover.status_code, 400)

    def test_article_generation_uses_server_snapshot_and_requires_explicit_purpose(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            submit_calls = []
            poll_calls = []

            def submit(project_id, payload, article_snapshot):
                from fastapi import HTTPException

                requested_revision = article_snapshot.get("requested_revision")
                if requested_revision is not None and requested_revision != article_snapshot["accepted_revision"]:
                    raise HTTPException(status_code=409, detail="文章已更新，请重新读取后再生成。")
                submit_calls.append((project_id, payload, article_snapshot))
                return {"run_id": "run_fixture", "status": "queued", "slot": payload["slot"]}

            def poll(project_id, run_id):
                poll_calls.append((project_id, run_id))
                return {"run_id": run_id, "status": "processing", "slot": "image"}

            with client_for(Path(temporary), submit_generation=submit, get_generation=poll) as client:
                project = client.post("/api/studio/projects", json={
                    "module": "article", "name": "生成关联",
                }).json()["project"]
                path = f"/api/studio/articles/{project['id']}"
                article = client.get(path).json()["article"]
                response = client.post(f"{path}/generations", json={
                    "slot": "image", "purpose": "cover", "output_node_id": "cover-output",
                    "client_operation_id": "article-op-1", "base_revision": article["revision"],
                    "request": {"prompt": "受限测试提示词"},
                })
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["generation"]["run_id"], "run_fixture")
                project_id, submitted, accepted = submit_calls[0]
                self.assertEqual(project_id, project["id"])
                self.assertEqual(submitted["purpose"], "cover")
                self.assertEqual(accepted["accepted_revision"], article["revision"])
                self.assertEqual(accepted["source_hash"], article["source_sha256"])

                omitted_purpose = client.post(f"{path}/generations", json={
                    "slot": "image", "output_node_id": "cover-output",
                    "client_operation_id": "article-op-2",
                })
                self.assertEqual(omitted_purpose.status_code, 422)
                wrong_cover_slot = client.post(f"{path}/generations", json={
                    "slot": "video", "purpose": "cover", "output_node_id": "video-output",
                    "client_operation_id": "article-op-3",
                })
                self.assertEqual(wrong_cover_slot.status_code, 400)
                self.assertEqual(len(submit_calls), 1)

                stale = client.post(f"{path}/generations", json={
                    "slot": "image", "purpose": "illustration", "output_node_id": "cover-output",
                    "client_operation_id": "article-op-4", "base_revision": article["revision"] + 1,
                })
                self.assertEqual(stale.status_code, 409)
                self.assertEqual(len(submit_calls), 1)

                polled = client.get(f"{path}/generations/run_fixture")
                self.assertEqual(polled.status_code, 200, polled.text)
                self.assertEqual(poll_calls, [(project["id"], "run_fixture")])

    def test_article_settings_uses_real_agent_commands_and_shared_three_argument_run(self):
        """文章配置图走标准 Agent 命令与 HeadlessCanvas，不需要自建命令路由。"""
        import copy
        import threading
        import time

        from canvas_agent import create_agent_router
        from canvas_core.headless_canvas import HeadlessCanvas
        from canvas_core.hypit_config import validate_hypit_settings_canvas
        from canvas_core.json_store import read_json, write_json
        from project_storage import ProjectStorage
        from studio_hypit_canvas import HypitSettingsCanvasService, create_hypit_settings_canvas_router

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            root = Path(temporary)
            canvas_path = root / "data" / "article-settings.json"
            canvas_path.parent.mkdir(parents=True, exist_ok=True)
            lock = threading.RLock()
            storage = ProjectStorage(root / "project-storage")
            storage.ensure_layout()

            def load_canvas(canvas_id):
                if canvas_id != "article-settings" or not canvas_path.is_file():
                    raise FileNotFoundError(canvas_id)
                return read_json(canvas_path)

            def save_canvas(canvas, *, increment_revision=True, touch_updated_at=True):
                with lock:
                    value = copy.deepcopy(canvas)
                    try:
                        current = read_json(canvas_path) if canvas_path.is_file() else None
                    except OSError:
                        current = None
                    if increment_revision and current:
                        value["revision"] = int(current.get("revision") or 1) + 1
                    if touch_updated_at:
                        value["updated_at"] = int(time.time() * 1000)
                    write_json(canvas_path, value)
                    return copy.deepcopy(value)

            service = HypitSettingsCanvasService(
                load_canvas=load_canvas,
                save_canvas=save_canvas,
                lock=lock,
                load_legacy_settings=lambda: None,
                backup_legacy_settings=lambda _record: None,
                migrate_legacy_settings=lambda _defaults, _canvas_id: {},
                validate_canvas=validate_hypit_settings_canvas,
                test_statuses=lambda _canvas_id, _canvas: {},
                broadcast_canvas_updated=lambda *_args: None,
                now_ms=lambda: int(time.time() * 1000),
                canvas_id="article-settings",
                module_id="article",
                migrate_legacy=False,
            )

            def load_article_canvas(canvas_id):
                if canvas_id != "article-settings":
                    raise FileNotFoundError(canvas_id)
                return service.ensure_canvas()

            run_calls = []

            async def submit_run(canvas, node, request_id):
                # 这是 HeadlessCanvas 唯一的既有运行回调：始终为 (canvas, node, request_id)。
                run_calls.append((canvas["id"], node["id"], request_id))
                task = storage.create_canvas_task({
                    "id": "article-node-run-fixture",
                    "canvas_id": canvas["id"],
                    "node_id": node["id"],
                    "kind": "studio_node_run",
                    "status": "succeeded",
                    "result": {"output_kind": "image", "media": []},
                })
                return {"task_ids": [task["id"]], "tasks": [{"id": task["id"], "status": task["status"]}]}

            async def cancel_run(_canvas, _node, _task_id):
                return None

            executor = HeadlessCanvas(
                load_canvas=load_article_canvas,
                save_canvas=service.save_agent_canvas,
                lock=lock,
                submit_run=submit_run,
                cancel_run=cancel_run,
                validate_model=lambda *_args: {"runnable": True, "parameters": {}, "family_id": "fixture"},
            )
            app = FastAPI()
            app.include_router(create_hypit_settings_canvas_router(service=service, include_test_routes=False))
            app.include_router(create_agent_router(
                root / "agent",
                load_article_canvas,
                executor=executor,
            ))

            with TestClient(app) as client:
                initial = client.get("/api/studio/articles/settings-canvas")
                self.assertEqual(initial.status_code, 200, initial.text)
                self.assertEqual(initial.json()["id"], "article-settings")
                self.assertEqual(initial.json()["canvas"]["nodes"], [])

                created = client.post("/api/agent/canvases/article-settings/commands", json={
                    "request_id": "article-create-image-node",
                    "action": "create_node",
                    "args": {"kind": "image", "title": "文章插图", "provider_id": "fixture",
                             "model": "image-fixture", "parameters": {}},
                })
                self.assertEqual(created.status_code, 200, created.text)
                command = created.json()
                deadline = time.monotonic() + 3
                while command.get("status") not in {"succeeded", "failed"} and time.monotonic() < deadline:
                    time.sleep(0.01)
                    command = client.get(f"/api/agent/canvases/article-settings/commands/{command['id']}").json()
                self.assertEqual(command["status"], "succeeded", command)
                node_id = command["result"]["node_id"]

                updated = client.post("/api/agent/canvases/article-settings/commands", json={
                    "request_id": "article-update-image-node",
                    "action": "update_node",
                    "args": {"node_id": node_id, "text": "本次测试提示词", "x": 160, "y": 80},
                })
                self.assertEqual(updated.status_code, 200, updated.text)
                command = updated.json()
                deadline = time.monotonic() + 3
                while command.get("status") not in {"succeeded", "failed"} and time.monotonic() < deadline:
                    time.sleep(0.01)
                    command = client.get(f"/api/agent/canvases/article-settings/commands/{command['id']}").json()
                self.assertEqual(command["status"], "succeeded", command)
                self.assertEqual(command["result"]["node"]["promptDraftText"], "本次测试提示词")

                run = client.post("/api/agent/canvases/article-settings/commands", json={
                    "request_id": "article-run-image-node",
                    "action": "run_node",
                    "args": {"node_id": node_id},
                })
                self.assertEqual(run.status_code, 200, run.text)
                command = run.json()
                deadline = time.monotonic() + 3
                while command.get("status") not in {"succeeded", "failed"} and time.monotonic() < deadline:
                    time.sleep(0.01)
                    command = client.get(f"/api/agent/canvases/article-settings/commands/{command['id']}").json()
                self.assertEqual(command["status"], "succeeded", command)
                self.assertEqual(run_calls, [("article-settings", node_id, "article-run-image-node")])
                self.assertEqual(command["result"]["task_ids"], ["article-node-run-fixture"])
                stored_task = storage.get_canvas_task("article-node-run-fixture")
                self.assertEqual(stored_task["canvas_id"], "article-settings")

    def test_source_change_expires_variants_and_revision_conflict_preserves_current(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            with client_for(Path(temporary)) as client:
                project = client.post("/api/studio/projects", json={"module": "article", "name": "并发文章"}).json()["project"]
                first = client.get(f"/api/studio/articles/{project['id']}").json()["article"]
                saved = client.put(f"/api/studio/articles/{project['id']}", json={
                    "expected_revision": first["revision"],
                    "title": "标题一",
                    "source_markdown": "正文一",
                    "selected_theme_id": "moyu-green",
                    "variants": {"moyu-green": {"body_html": GOOD_HTML}},
                }).json()["article"]
                next_save = client.put(f"/api/studio/articles/{project['id']}", json={
                    "expected_revision": saved["revision"],
                    "source_markdown": "正文二",
                })
                self.assertEqual(next_save.status_code, 200, next_save.text)
                current = next_save.json()["article"]
                self.assertFalse(current["variants"]["moyu-green"]["valid"])
                conflict = client.put(f"/api/studio/articles/{project['id']}", json={
                    "expected_revision": saved["revision"],
                    "source_markdown": "旧页面覆盖",
                })
                self.assertEqual(conflict.status_code, 409)
                reread = client.get(f"/api/studio/articles/{project['id']}").json()["article"]
                self.assertEqual(reread["source_markdown"], "正文二")

    def test_unsafe_html_rejected_atomically_without_losing_source(self):
        unsafe = (
            '<section><script>alert(1)</script></section>',
            '<section><p onclick="run()"><span leaf="">正文</span></p></section>',
            '<section><img src="file:///Users/private/photo.png"></section>',
            '<section><img src="/Users/private/photo.png"></section>',
            '<section><img src="https://example.test/x.png" style="background:url(javascript:alert(1))"></section>',
            '<section class="unsafe"><p><span leaf="">正文</span></p></section>',
        )
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            with client_for(Path(temporary)) as client:
                project = client.post("/api/studio/projects", json={"module": "article", "name": "安全测试"}).json()["project"]
                initial = client.get(f"/api/studio/articles/{project['id']}").json()["article"]
                saved = client.put(f"/api/studio/articles/{project['id']}", json={
                    "expected_revision": initial["revision"],
                    "source_markdown": "原文必须保留",
                }).json()["article"]
                for fragment in unsafe:
                    response = client.put(f"/api/studio/articles/{project['id']}", json={
                        "expected_revision": saved["revision"],
                        "source_markdown": "不应随恶意HTML提交",
                        "variants": {"moyu-green": {"body_html": fragment}},
                    })
                    self.assertEqual(response.status_code, 400, fragment)
                    current = client.get(f"/api/studio/articles/{project['id']}").json()["article"]
                    self.assertEqual(current["source_markdown"], "原文必须保留")

    def test_invalid_theme_unknown_id_and_corrupt_record_are_safe(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            root = Path(temporary)
            with client_for(root) as client:
                project = client.post("/api/studio/projects", json={"module": "article", "name": "边界测试"}).json()["project"]
                unknown = client.get("/api/studio/articles/../outside")
                self.assertIn(unknown.status_code, {400, 404})
                current = client.get(f"/api/studio/articles/{project['id']}").json()["article"]
                invalid = client.put(f"/api/studio/articles/{project['id']}", json={
                    "expected_revision": current["revision"],
                    "selected_theme_id": "unknown-theme",
                })
                self.assertEqual(invalid.status_code, 400)
                record = root / "data" / "studio_projects" / f"{project['id']}.json"
                record.write_bytes(b"{corrupt")
                response = client.get(f"/api/studio/articles/{project['id']}")
                self.assertEqual(response.status_code, 500)
                self.assertEqual(record.read_bytes(), b"{corrupt")

    def test_delete_archives_article_record_but_keeps_immutable_html_asset(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            root = Path(temporary)
            with client_for(root) as client:
                project = client.post("/api/studio/projects", json={"module": "article", "name": "归档测试"}).json()["project"]
                article = client.get(f"/api/studio/articles/{project['id']}").json()["article"]
                saved = client.put(f"/api/studio/articles/{project['id']}", json={
                    "expected_revision": article["revision"],
                    "source_markdown": "原文",
                    "variants": {"moyu-green": {"body_html": GOOD_HTML}},
                }).json()["article"]
                record = root / "data" / "studio_projects" / f"{project['id']}.json"
                raw = json.loads(record.read_text(encoding="utf-8"))
                html_path = root / raw["article"]["variants"]["moyu-green"]["path"]
                self.assertTrue(html_path.is_file())
                deleted = client.delete(
                    f"/api/studio/projects/{project['id']}?module=article&revision={saved['revision']}"
                )
                self.assertEqual(deleted.status_code, 200, deleted.text)
                self.assertTrue(deleted.json()["recycled"])
                self.assertFalse(record.exists())
                self.assertTrue(html_path.is_file())

    def test_shared_project_connection_and_article_routes_use_same_store(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            root = Path(temporary)
            with client_for(root, include_connection=True) as client:
                project = client.post("/api/studio/projects", json={
                    "module": "article", "name": "连接集成稿",
                }).json()["project"]
                connection = client.get(
                    f"/api/studio/projects/{project['id']}/connection?module=article"
                )
                self.assertEqual(connection.status_code, 200, connection.text)
                document = client.get(connection.json()["document_url"])
                self.assertEqual(document.status_code, 200, document.text)
                self.assertIn(f"/api/studio/articles/{project['id']}", document.text)

                article_url = f"/api/studio/articles/{project['id']}"
                current = client.get(article_url).json()["article"]
                saved_source = client.put(article_url, json={
                    "expected_revision": current["revision"],
                    "title": "集成标题",
                    "source_markdown": "集成正文",
                    "selected_theme_id": "moyu-green",
                })
                self.assertEqual(saved_source.status_code, 200, saved_source.text)
                source_snapshot = client.get(article_url).json()["article"]
                saved = client.put(article_url, json={
                    "expected_revision": source_snapshot["revision"],
                    "expected_catalog_fingerprint": source_snapshot["catalog_fingerprint"],
                    "variants": {
                        "moyu-green": {"body_html": GOOD_HTML, "source_sha256": source_snapshot["source_sha256"]},
                        "red-white": {"body_html": SECOND_GOOD_HTML, "source_sha256": source_snapshot["source_sha256"]},
                    },
                })
                self.assertEqual(saved.status_code, 200, saved.text)
                saved_article = saved.json()["article"]
                self.assertTrue(saved_article["variants"]["moyu-green"]["valid"])
                self.assertTrue(saved_article["variants"]["red-white"]["valid"])
                self.assertEqual(saved_article["variants"]["moyu-green"]["body_html"], GOOD_HTML)
                self.assertEqual(saved_article["variants"]["red-white"]["body_html"], SECOND_GOOD_HTML)
                record_path = root / "data" / "studio_projects" / f"{project['id']}.json"
                raw = json.loads(record_path.read_text(encoding="utf-8"))
                html_paths = [root / item["path"] for item in raw["article"]["variants"].values()]
                self.assertTrue(all(path.is_file() for path in html_paths))
                renamed = client.patch(
                    f"/api/studio/projects/{project['id']}?module=article",
                    json={"module": "article", "name": "改名后", "revision": saved_article["revision"]},
                )
                self.assertEqual(renamed.status_code, 200, renamed.text)
                after_rename = client.get(article_url).json()["article"]
                self.assertEqual(after_rename["source_markdown"], "集成正文")
                self.assertEqual(after_rename["variants"]["red-white"]["body_html"], SECOND_GOOD_HTML)
                deleted = client.delete(
                    f"/api/studio/projects/{project['id']}?module=article&revision={renamed.json()['project']['revision']}"
                )
                self.assertEqual(deleted.status_code, 200, deleted.text)
                self.assertTrue(deleted.json()["recycled"])
                self.assertFalse(record_path.exists())
                self.assertTrue(all(path.is_file() for path in html_paths))


if __name__ == "__main__":
    unittest.main()
