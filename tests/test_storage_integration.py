import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request, UploadFile
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main
from project_storage import ProjectStorage


def make_request(host, origin="", referer="", scheme="http", client_host="127.0.0.1"):
    headers = [(b"host", host.encode("ascii"))]
    if origin:
        headers.append((b"origin", origin.encode("ascii")))
    if referer:
        headers.append((b"referer", referer.encode("ascii")))
    return Request({
        "type": "http",
        "method": "POST",
        "scheme": scheme,
        "path": "/api/materials/test/promote",
        "raw_path": b"/api/materials/test/promote",
        "query_string": b"",
        "headers": headers,
        "server": ("127.0.0.1", 3000),
        "client": (client_host, 50000),
    })


class SameOriginRequestTests(unittest.TestCase):
    def test_local_request_without_browser_origin_is_allowed(self):
        main.ensure_same_origin_request(make_request("127.0.0.1:3000"))

    def test_missing_origin_is_rejected_for_nonlocal_client(self):
        request = make_request("127.0.0.1:3000", client_host="192.168.1.20")

        with self.assertRaises(HTTPException) as caught:
            main.ensure_same_origin_request(request)
        self.assertEqual(caught.exception.status_code, 403)

    def test_localhost_and_loopback_address_are_equivalent(self):
        request = make_request("127.0.0.1:3000", origin="http://localhost:3000")

        main.ensure_same_origin_request(request)

    def test_ipv6_loopback_is_equivalent_to_localhost(self):
        request = make_request("[::1]:3000", referer="http://localhost:3000/static/asset-manager.html")

        main.ensure_same_origin_request(request)

    def test_cross_origin_request_is_rejected(self):
        request = make_request("127.0.0.1:3000", origin="https://example.com")

        with self.assertRaises(HTTPException) as caught:
            main.ensure_same_origin_request(request)
        self.assertEqual(caught.exception.status_code, 403)


class StorageIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.storage = ProjectStorage(self.root)
        self.storage.ensure_layout()
        self.asset_library_path = self.root / "data" / "asset_library.json"
        self.canvas_dir = self.root / "data" / "canvases"
        self.canvas_dir.mkdir(parents=True, exist_ok=True)
        self.patches = [
            patch.object(main, "PROJECT_STORAGE", self.storage),
            patch.object(main, "CANVAS_DIR", str(self.canvas_dir)),
            patch.object(main, "ASSETS_DIR", str(self.storage.assets_dir)),
            patch.object(main, "OUTPUT_OUTPUT_DIR", str(self.storage.results_dir)),
            patch.object(main, "RESULTS_DIR", str(self.storage.results_dir)),
            patch.object(main, "ASSET_LIBRARY_PATH", str(self.asset_library_path)),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self):
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.temp.cleanup()

    async def test_creation_recipe_round_trip_reuses_file_and_keeps_distinct_origins(self):
        source = self.root / 'fixture.png'
        source.write_bytes(b'creation-fixture')
        result = self.storage.store_result_file(source, '林澈_妆造_正常.png', move=True)
        def node(node_id, creation_id, prompt):
            return {'id': node_id, 'type': 'smart-image-generator', 'title': '林澈_妆造_正常',
                    'creationId': creation_id, 'creationOwnerNodeId': node_id,
                    'runSettings': {'model': 'fixture', 'apiKey': 'must-not-leak'},
                    'promptDraftText': prompt,
                    'resultVersions': [{'id': creation_id + '_v1', 'images': [{'resultId': result['id'], 'url': result['url']}]}]}
        original = {'id': 'canvas-fixture', 'kind': 'smart', 'nodes': [node('a', 'shared', '正常妆造')]}
        main.sync_canvas_result_origins(original)
        main.sync_canvas_result_origins(original)
        main.sync_canvas_result_origins({'id': 'canvas-fixture', 'kind': 'smart', 'nodes': [node('b', 'branch', '受伤妆造')]})
        recipes = (await main.result_creation_recipe(result['id']))['recipes']
        self.assertEqual({record['creationId'] for record in recipes}, {'shared', 'branch'})
        self.assertNotIn('must-not-leak', json.dumps(recipes))
        self.assertEqual(len(self.storage.list_results()), 1)
        self.assertEqual(self.storage.get_result(result['id'])['path'], result['path'])

    async def test_external_cli_registration_http_aliases_managed_material_without_claiming_studio_run(self):
        source = self.root / "external-cli-image.png"
        source.write_bytes(b"external-cli-fixture-image")
        material = self.storage.store_material_file(source, "temporary")
        payload = {
            "material_id": material["id"],
            "provider": "fixture-provider",
            "tool": "fixture-cli",
            "model": "fixture-image-v1",
            "task_id": "fixture-task-001",
            "output_index": 1,
        }
        client = TestClient(main.app, base_url="http://127.0.0.1:3000")
        headers = {"Origin": "http://127.0.0.1:3000"}

        response = client.post(
            "/api/results/register-external-cli-material",
            json=payload,
            headers=headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["item"]
        self.assertEqual(result["url"], f"/api/results/{result['id']}")
        self.assertEqual(result["path"], material["path"])
        self.assertEqual(result["origin"], {
            "kind": "external_cli",
            "source_material_id": material["id"],
            "provider": "fixture-provider",
            "tool": "fixture-cli",
            "model": "fixture-image-v1",
            "task_id": "fixture-task-001",
            "output_index": 1,
            "provenance_verified": False,
        })
        self.assertFalse(response.json()["studio_task_proof"])
        self.assertNotIn("run_id", result)

        repeated = client.post(
            "/api/results/register-external-cli-material",
            json=payload,
            headers=headers,
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["item"]["id"], result["id"])
        self.assertEqual(len(self.storage.list_results()), 1)
        self.assertEqual(len(list(self.storage.materials_dir.rglob("*.png"))), 1)

        body_with_path = {**payload, "path": str(source)}
        rejected_path = client.post(
            "/api/results/register-external-cli-material",
            json=body_with_path,
            headers=headers,
        )
        self.assertEqual(rejected_path.status_code, 422)
        body_with_run_claim = {**payload, "status": "succeeded", "run_id": "forged"}
        rejected_claim = client.post(
            "/api/results/register-external-cli-material",
            json=body_with_run_claim,
            headers=headers,
        )
        self.assertEqual(rejected_claim.status_code, 422)
        rejected_origin = client.post(
            "/api/results/register-external-cli-material",
            json=payload,
            headers={"Origin": "https://example.invalid"},
        )
        self.assertEqual(rejected_origin.status_code, 403)

        downloaded = client.get(result["url"])
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, b"external-cli-fixture-image")

    async def test_result_delete_preflights_article_references_for_the_entire_batch(self):
        referenced_file = self.root / "article-html.png"
        unrelated_file = self.root / "unrelated.png"
        referenced_file.write_bytes(b"article-referenced-result")
        unrelated_file.write_bytes(b"unrelated-result")
        referenced = self.storage.store_result_file(referenced_file, "article-html.png", move=True)
        unrelated = self.storage.store_result_file(unrelated_file, "unrelated.png", move=True)
        article = {
            "project_id": "article-fixture",
            "title": "引用保护测试文章",
            "cover_variants": [],
            "media_refs": [],
            "variants": {"moyu-green": {"result_id": referenced["id"]}},
        }
        projects = SimpleNamespace(list=lambda module=None: [{"id": "article-fixture"}] if module == "article" else [])
        articles = SimpleNamespace(get=lambda project_id: article if project_id == "article-fixture" else None)
        client = TestClient(main.app, base_url="http://127.0.0.1:3000")

        with patch.object(main, "STUDIO_PROJECTS", projects), patch.object(main, "STUDIO_ARTICLES", articles):
            response = client.post(
                "/api/results/delete",
                json={"ids": [unrelated["id"], referenced["id"]]},
                headers={"Origin": "http://127.0.0.1:3000"},
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("引用保护测试文章", response.json()["detail"])
        self.assertIsNotNone(self.storage.get_result(referenced["id"]))
        self.assertIsNotNone(self.storage.get_result(unrelated["id"]))
        self.assertTrue(self.storage.result_path(referenced["id"]).is_file())
        self.assertTrue(self.storage.result_path(unrelated["id"]).is_file())

    async def test_article_asset_references_block_asset_batch_and_temporary_scope_removal(self):
        referenced_asset = self.storage.store_material_bytes(b"article-cover-asset", "cover.png", scope="asset")
        unrelated_asset = self.storage.store_material_bytes(b"unrelated-asset", "other.png", scope="asset")
        temporary_asset = self.storage.store_material_bytes(b"temporary-asset", "temporary.png", scope="temporary")
        article = {
            "project_id": "article-fixture",
            "title": "素材引用保护文章",
            "cover_variants": [{"asset_id": referenced_asset["id"]}],
            "media_refs": [{"asset_id": temporary_asset["id"]}],
            "variants": {},
        }
        projects = SimpleNamespace(list=lambda module=None: [{"id": "article-fixture"}] if module == "article" else [])
        articles = SimpleNamespace(get=lambda project_id: article if project_id == "article-fixture" else None)
        library = main.default_asset_library()
        category = library["libraries"][0]["categories"][0]
        category["items"] = [
            {"id": "entry-referenced", "material_id": referenced_asset["id"], "name": "cover.png"},
            {"id": "entry-unrelated", "material_id": unrelated_asset["id"], "name": "other.png"},
        ]
        main.save_asset_library(library)
        client = TestClient(main.app, base_url="http://127.0.0.1:3000")

        with patch.object(main, "STUDIO_PROJECTS", projects), patch.object(main, "STUDIO_ARTICLES", articles):
            batch = client.post(
                "/api/asset-library/items/delete",
                json={"library_id": "default", "ids": ["entry-unrelated", "entry-referenced"]},
            )
            temporary = client.post(
                "/api/local-assets/delete",
                json={"names": [temporary_asset["id"]]},
                headers={"Origin": "http://127.0.0.1:3000"},
            )

        self.assertEqual(batch.status_code, 409, batch.text)
        self.assertIn("素材引用保护文章", batch.json()["detail"])
        self.assertIsNotNone(self.storage.get_material(referenced_asset["id"]))
        self.assertIsNotNone(self.storage.get_material(unrelated_asset["id"]))
        saved_library = main.load_asset_library()
        saved_ids = {item["id"] for item in saved_library["libraries"][0]["categories"][0]["items"]}
        self.assertEqual(saved_ids, {"entry-referenced", "entry-unrelated"})
        self.assertEqual(temporary.status_code, 409, temporary.text)
        self.assertIn("素材引用保护文章", temporary.json()["detail"])
        self.assertIsNotNone(self.storage.get_material(temporary_asset["id"]))
        self.assertTrue(self.storage.material_path(temporary_asset["id"]).is_file())

    async def test_canvas_upload_reuses_same_material_and_returns_stable_id(self):
        first = UploadFile(filename="封面.png", file=io.BytesIO(b"same-content"))
        second = UploadFile(filename="再次上传.png", file=io.BytesIO(b"same-content"))

        first_response = await main.upload_ai_reference([first])
        second_response = await main.upload_ai_reference([second])

        first_item = first_response["files"][0]
        second_item = second_response["files"][0]
        self.assertEqual(first_item["material_id"], second_item["material_id"])
        self.assertEqual(first_item["url"], second_item["url"])
        self.assertTrue(first_item["url"].startswith("/api/materials/"))
        self.assertEqual(len(self.storage.list_materials("temporary")), 1)

    async def test_generated_output_is_registered_and_listed_independently(self):
        path = Path(main.output_path_for("生成视频.mp4", "output"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video-result")

        url = main.output_url_for("生成视频.mp4", "output")
        response = await main.list_generation_results(kind="video")

        self.assertTrue(url.startswith("/api/results/"))
        self.assertEqual(response["total"], 1)
        self.assertEqual(response["items"][0]["kind"], "video")
        self.assertEqual(response["items"][0]["url"], url)

    async def test_generation_result_rename_keeps_stable_public_url(self):
        source = self.root / "generated.png"
        source.write_bytes(b"generated-image")
        result = self.storage.store_result_file(source, "原名称.png", move=True)

        response = await main.rename_generation_result(
            result["id"],
            {"name": "新名称"},
            make_request("127.0.0.1:3000"),
        )

        self.assertEqual(response["item"]["id"], result["id"])
        self.assertEqual(response["item"]["name"], "新名称.png")
        self.assertEqual(response["item"]["url"], self.storage.result_url(result["id"]))

    async def test_material_route_reads_file_from_index(self):
        item = self.storage.store_material_bytes(b"image", "人物.png")

        response = await main.get_material_file(item["id"])

        self.assertEqual(Path(response.path).read_bytes(), b"image")

    async def test_canvas_workflow_uses_independent_stable_url(self):
        item = main.make_workflow_library_item_from_bytes(b'{"nodes": []}', "测试工作流.json")

        self.assertTrue(item["url"].startswith("/workflow-files/"))
        path = main.output_file_from_url(item["url"])
        self.assertIsNotNone(path)
        self.assertEqual(Path(path).read_bytes(), b'{"nodes": []}')

    async def test_default_asset_library_is_named_asset_library_and_cannot_be_deleted(self):
        library = main.load_asset_library()
        library["libraries"].append({"id": "second", "name": "第二个库", "type": "asset", "categories": []})
        main.save_asset_library(library)

        self.assertEqual(library["libraries"][0]["name"], "资产库")
        with self.assertRaises(HTTPException) as caught:
            await main.delete_asset_library("default")
        self.assertEqual(caught.exception.status_code, 400)

    async def test_canvas_text_result_is_stored_as_markdown_generation_result(self):
        payload = main.CanvasTextResultRequest(
            text="# 文本结果\n\n正文",
            name="文案结果.md",
            canvas_id="smart-canvas-1",
            canvas_title="产品文案",
        )

        result = await main.create_canvas_text_result(payload)

        self.assertEqual(result["kind"], "text")
        self.assertEqual(result["display_name"], "文案结果.md")
        self.assertEqual(result["source_canvas"]["id"], "smart-canvas-1")
        self.assertTrue(result["url"].startswith("/api/results/res_"))
        stored_path = main.PROJECT_STORAGE.result_path(result["id"])
        self.assertEqual(stored_path.read_text(encoding="utf-8"), "# 文本结果\n\n正文")

    async def test_generation_result_can_be_indexed_as_asset_without_moving_file(self):
        source = self.root / "preview.png"
        source.write_bytes(b"result-image")
        result = self.storage.store_result_file(source, "编辑结果.png", move=True)
        request = make_request("127.0.0.1:3000")

        response = await main.promote_result_record(
            result["id"],
            main.ResultPromoteRequest(library_id="default", category_id="characters"),
            request,
        )

        self.assertEqual(response["item"]["result_id"], result["id"])
        self.assertEqual(response["item"]["url"], self.storage.result_url(result["id"]))
        self.assertTrue(self.storage.result_path(result["id"]).is_file())
        self.assertFalse(self.storage.list_materials("asset"))

    async def test_canvas_result_origins_are_synced_from_urls_and_explicit_ids(self):
        first_source = self.root / "first.png"
        second_source = self.root / "second.mp4"
        first_source.write_bytes(b"first-result")
        second_source.write_bytes(b"second-result")
        first = self.storage.store_result_file(first_source, "第一张.png", move=True)
        second = self.storage.store_result_file(second_source, "第二段.mp4", move=True)
        canvas = {
            "id": "smart-canvas-results",
            "title": "结果来源同步",
            "kind": "smart",
            "nodes": [
                {
                    "id": "image-result",
                    "url": f"{first['url']}?preview=1",
                    "nested": {"resultId": first["id"]},
                },
                {
                    "id": "video-result",
                    "result_id": second["id"],
                },
            ],
        }

        changed = main.sync_canvas_result_origins(canvas)

        self.assertEqual(changed, 2)
        self.assertEqual(self.storage.get_result(first["id"])["source_canvas"], {
            "id": "smart-canvas-results",
            "title": "结果来源同步",
            "kind": "smart",
        })
        self.assertEqual(self.storage.get_result(second["id"])["source_canvas"]["id"], "smart-canvas-results")

    async def test_video_trim_creates_derived_result_without_overwriting_source(self):
        source = self.storage.store_material_bytes(b"source-video", "原视频.mp4", scope="temporary")

        def fake_run(command, **_kwargs):
            if "ffprobe" in str(command[0]):
                return SimpleNamespace(returncode=0, stdout="12.5\n", stderr="")
            Path(command[-1]).write_bytes(b"trimmed-video")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        payload = main.CanvasMediaTransformRequest(
            url=source["url"],
            operation="trim",
            start=2.0,
            end=5.5,
            name="原视频",
            canvas_id="canvas-media-tools",
            canvas_title="媒体工具",
        )
        with patch.object(main, "resolve_media_tool", side_effect=lambda name: f"/usr/bin/{name}"), patch.object(main.subprocess, "run", side_effect=fake_run):
            result = await main.transform_canvas_media(payload)

        stored = self.storage.get_result(result["id"])
        self.assertEqual(result["kind"], "video")
        self.assertEqual(self.storage.result_path(result["id"]).read_bytes(), b"trimmed-video")
        self.assertEqual(self.storage.material_path(source["id"]).read_bytes(), b"source-video")
        self.assertEqual(stored["source_canvas"]["id"], "canvas-media-tools")
        self.assertEqual(stored["derivation"]["operation"], "trim")
        self.assertEqual(stored["derivation"]["source_material_id"], source["id"])
        self.assertEqual(stored["derivation"]["start"], 2.0)
        self.assertEqual(stored["derivation"]["end"], 5.5)

    async def test_video_audio_extraction_creates_audio_derived_result(self):
        source_path = self.root / "generated.mp4"
        source_path.write_bytes(b"source-result-video")
        source = self.storage.store_result_file(source_path, "生成视频.mp4", move=True)

        def fake_run(command, **_kwargs):
            if "ffprobe" in str(command[0]):
                return SimpleNamespace(returncode=0, stdout="8\n", stderr="")
            Path(command[-1]).write_bytes(b"extracted-audio")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        payload = main.CanvasMediaTransformRequest(
            url=source["url"],
            operation="extract_audio",
            start=1.25,
            end=6.0,
            name="生成视频",
            canvas_id="canvas-media-tools",
            canvas_title="媒体工具",
        )
        with patch.object(main, "resolve_media_tool", side_effect=lambda name: f"/usr/bin/{name}"), patch.object(main.subprocess, "run", side_effect=fake_run):
            result = await main.transform_canvas_media(payload)

        stored = self.storage.get_result(result["id"])
        self.assertEqual(result["kind"], "audio")
        self.assertEqual(self.storage.result_path(result["id"]).read_bytes(), b"extracted-audio")
        self.assertEqual(stored["derivation"]["operation"], "extract_audio")
        self.assertEqual(stored["derivation"]["source_result_id"], source["id"])
        self.assertEqual(stored["derivation"]["duration"], 4.75)

    async def test_upload_and_agent_grouping_never_call_a_model_and_keep_stable_url(self):
        with patch.object(main.httpx, "AsyncClient", side_effect=AssertionError("上传和分组不能调用模型")):
            uploaded = await main.upload_local_assets([
                UploadFile(filename="分类测试.png", file=io.BytesIO(b"group-test-image"))
            ], folder="")
            material = uploaded["files"][0]
            added = await main.add_asset_library_item(main.AssetLibraryAddRequest(
                library_id="default", category_id="characters", url=material["url"], name="分类测试.png"
            ))
            category = await main.create_asset_library_category(main.AssetLibraryCategoryRequest(
                library_id="default", name="Agent 分组", type="image"
            ))
            moved = await main.batch_move_asset_library_items(main.AssetLibraryBatchMoveRequest(
                ids=[added["item"]["id"]], library_id="default", target_library_id="default",
                target_category_id=category["category"]["id"]
            ))
        self.assertEqual(moved["moved"], 1)
        destination = main.find_asset_category_in_library(main.load_asset_library(), category["category"]["id"], "default")
        self.assertEqual(destination["items"][0]["url"], material["url"])
        self.assertEqual(len(self.storage.list_materials()), 1)

    async def test_asset_category_is_logical_and_does_not_recreate_legacy_directory(self):
        legacy_library = self.root / "assets" / "library"
        with patch.object(main, "ASSET_LIBRARY_DIR", str(legacy_library)):
            response = await main.create_asset_library_category(
                main.AssetLibraryCategoryRequest(library_id="default", name="新分组", type="image")
            )

        self.assertEqual(response["category"]["name"], "新分组")
        self.assertFalse(legacy_library.exists())

    async def test_asset_upload_can_be_deleted_and_uploaded_again(self):
        material = self.storage.store_material_bytes(b"asset-image", "测试素材.png", scope="temporary")
        payload = main.AssetLibraryBatchAddRequest(
            library_id="default",
            category_id="characters",
            items=[main.AssetLibraryAddRequest(
                library_id="default",
                category_id="characters",
                url=material["url"],
                name="测试素材.png",
            )],
        )

        first = await main.batch_add_asset_library_items(payload)
        await main.delete_asset_library_item(first["items"][0]["id"])
        second = await main.batch_add_asset_library_items(payload)

        self.assertEqual(len(second["items"]), 1)
        self.assertEqual(second["items"][0]["material_id"], material["id"])
        self.assertTrue(self.storage.material_path(material["id"]).is_file())

    async def test_asset_library_accepts_video_and_audio_materials(self):
        video = self.storage.store_material_bytes(b"video-content", "片段.mp4", scope="temporary")
        audio = self.storage.store_material_bytes(b"audio-content", "旁白.mp3", scope="temporary")
        payload = main.AssetLibraryBatchAddRequest(
            library_id="default",
            category_id="characters",
            items=[
                main.AssetLibraryAddRequest(library_id="default", category_id="characters", url=video["url"], name="片段"),
                main.AssetLibraryAddRequest(library_id="default", category_id="characters", url=audio["url"], name="旁白"),
            ],
        )

        response = await main.batch_add_asset_library_items(payload)

        self.assertEqual([item["kind"] for item in response["items"]], ["video", "audio"])
        self.assertEqual([item["extension"] for item in response["items"]], [".mp4", ".mp3"])

    async def test_smart_canvas_save_round_trip_preserves_connection_order_and_result_ids(self):
        canvas = main.new_canvas("连接契约", kind="smart")
        connections = [
            {"from": "material-b", "to": "ai-app", "kind": "input"},
            {"from": "result-group", "to": "ai-app", "kind": "input", "sourceResultId": "result-2"},
            {"from": "material-a", "to": "ai-app", "kind": "input"},
            {"from": "result-group", "to": "loop", "kind": "input", "sourceResultId": "result-1"},
        ]
        payload = main.CanvasSaveRequest(
            title="连接契约",
            icon="sparkles",
            nodes=[
                {"id": "material-a", "type": "smart-material"},
                {"id": "material-b", "type": "smart-material"},
                {"id": "result-group", "type": "smart-result-group"},
                {"id": "ai-app", "type": "smart-ai-app", "inputNodeIds": ["material-b", "result-group", "material-a"]},
                {"id": "loop", "type": "smart-loop"},
            ],
            connections=connections,
            viewport={"x": 12, "y": 34, "scale": 0.9},
            base_updated_at=canvas["updated_at"],
        )

        with patch.object(main.manager, "broadcast_canvas_updated", new=AsyncMock()):
            await main.update_canvas(canvas["id"], payload)
        loaded = (await main.get_canvas(canvas["id"]))["canvas"]

        self.assertEqual(loaded["connections"], connections)
        ai_app = next(node for node in loaded["nodes"] if node["id"] == "ai-app")
        self.assertEqual(ai_app["inputNodeIds"], ["material-b", "result-group", "material-a"])

    async def test_new_canvas_starts_at_revision_one_and_successful_save_increments_once(self):
        canvas = main.new_canvas("版本画布", kind="smart")

        self.assertEqual(canvas["revision"], 1)

        payload = main.CanvasSaveRequest(
            title="版本画布更新",
            nodes=[{"id": "material", "type": "smart-material"}],
            base_revision=canvas["revision"],
            base_updated_at=canvas["updated_at"],
        )
        with patch.object(main.manager, "broadcast_canvas_updated", new=AsyncMock()):
            response = await main.update_canvas(canvas["id"], payload)

        self.assertEqual(response["canvas"]["revision"], 2)
        self.assertEqual((await main.get_canvas(canvas["id"]))["canvas"]["revision"], 2)

    async def test_stale_revision_returns_latest_canvas_without_overwriting_it(self):
        canvas = main.new_canvas("并发画布", kind="smart")
        first_payload = main.CanvasSaveRequest(
            title="新版本",
            nodes=[{"id": "new", "type": "smart-material"}],
            base_revision=1,
        )
        with patch.object(main.manager, "broadcast_canvas_updated", new=AsyncMock()):
            await main.update_canvas(canvas["id"], first_payload)

        stale_payload = main.CanvasSaveRequest(
            title="旧版本",
            nodes=[{"id": "stale", "type": "smart-material"}],
            base_revision=1,
        )
        with self.assertRaises(HTTPException) as caught:
            await main.update_canvas(canvas["id"], stale_payload)

        self.assertEqual(caught.exception.status_code, 409)
        detail = caught.exception.detail
        self.assertEqual(detail["revision"], 2)
        self.assertEqual(detail["canvas"]["nodes"][0]["id"], "new")
        latest = (await main.get_canvas(canvas["id"]))["canvas"]
        self.assertEqual(latest["title"], "新版本")
        self.assertEqual(latest["revision"], 2)

    async def test_canvas_meta_update_preserves_edit_time_and_increments_revision(self):
        canvas = main.new_canvas("元数据画布", kind="smart")
        original_updated_at = canvas["updated_at"]

        response = await main.update_canvas_meta(
            canvas["id"],
            main.CanvasMetaUpdate(title="新标题", pinned=True, base_revision=1),
        )

        self.assertEqual(response["canvas"]["revision"], 2)
        self.assertEqual(response["canvas"]["updated_at"], original_updated_at)
        loaded = (await main.get_canvas(canvas["id"]))["canvas"]
        self.assertEqual(loaded["title"], "新标题")
        self.assertTrue(loaded["pinned"])
        self.assertEqual(loaded["updated_at"], original_updated_at)

    async def test_stale_canvas_meta_update_cannot_overwrite_latest_metadata(self):
        canvas = main.new_canvas("元数据并发", kind="smart")
        await main.update_canvas_meta(
            canvas["id"],
            main.CanvasMetaUpdate(owner="新负责人", base_revision=1),
        )

        with self.assertRaises(HTTPException) as caught:
            await main.update_canvas_meta(
                canvas["id"],
                main.CanvasMetaUpdate(owner="旧负责人", base_revision=1),
            )

        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail["revision"], 2)
        loaded = (await main.get_canvas(canvas["id"]))["canvas"]
        self.assertEqual(loaded["owner"], "新负责人")
        self.assertEqual(loaded["revision"], 2)

    async def test_two_saves_from_the_same_revision_only_commit_once(self):
        canvas = main.new_canvas("并发提交", kind="smart")
        first = main.CanvasSaveRequest(title="窗口一", base_revision=1)
        second = main.CanvasSaveRequest(title="窗口二", base_revision=1)

        with patch.object(main.manager, "broadcast_canvas_updated", new=AsyncMock()):
            results = await __import__("asyncio").gather(
                main.update_canvas(canvas["id"], first),
                main.update_canvas(canvas["id"], second),
                return_exceptions=True,
            )

        successes = [result for result in results if isinstance(result, dict)]
        conflicts = [result for result in results if isinstance(result, HTTPException)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].status_code, 409)
        loaded = (await main.get_canvas(canvas["id"]))["canvas"]
        self.assertEqual(loaded["revision"], 2)
        self.assertEqual(loaded["title"], "窗口一")

    async def test_material_name_sync_atomically_versions_only_matching_canvases(self):
        material = self.storage.store_material_bytes(b"image", "原名称.png")
        matching = main.new_canvas("命中画布", kind="smart")
        matching["nodes"] = [{
            "id": "material",
            "material_id": material["id"],
            "display_name": "原名称.png",
        }]
        main.save_canvas(matching, touch_updated_at=False)
        untouched = main.new_canvas("未命中画布", kind="smart")
        original_matching_revision = matching["revision"]
        original_untouched_revision = untouched["revision"]

        changed = main.sync_material_display_name(material["id"], "新名称.png")

        self.assertEqual(changed, 1)
        updated_matching = (await main.get_canvas(matching["id"]))["canvas"]
        updated_untouched = (await main.get_canvas(untouched["id"]))["canvas"]
        self.assertEqual(updated_matching["nodes"][0]["display_name"], "新名称.png")
        self.assertEqual(updated_matching["revision"], original_matching_revision + 1)
        self.assertEqual(updated_untouched["revision"], original_untouched_revision)

    async def test_atomic_canvas_replace_failure_keeps_previous_json_and_cleans_temp_file(self):
        canvas = main.new_canvas("原始画布", kind="smart")
        path = Path(main.canvas_path(canvas["id"]))
        original = path.read_text(encoding="utf-8")
        canvas["title"] = "不会写入"

        with patch.object(main.os, "replace", side_effect=OSError("模拟替换失败")):
            with self.assertRaises(OSError):
                main.save_canvas(canvas)

        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    async def test_canvas_media_capabilities_report_ffmpeg_and_ffprobe(self):
        with patch.object(main, "resolve_media_tool", side_effect=lambda name: f"/usr/bin/{name}"):
            response = await main.canvas_media_capabilities()

        self.assertTrue(response["media_transform"])
        self.assertTrue(response["capabilities"]["ffmpeg"]["available"])
        self.assertTrue(response["capabilities"]["ffprobe"]["available"])
        self.assertEqual(response["message"], "媒体处理环境可用")

        with patch.object(main, "resolve_media_tool", return_value=None):
            response = await main.canvas_media_capabilities()

        self.assertFalse(response["media_transform"])
        self.assertEqual(response["message"], "缺少FFmpeg和FFprobe，播放预览仍可用，但媒体处理暂不可用")

    async def test_director_reference_rejects_unknown_operation_and_remote_source(self):
        with self.assertRaises(ValidationError):
            main.DirectorReferenceRequest(source_url="/api/results/a", operation="middle_frame")

        with self.assertRaises(HTTPException) as caught:
            await main.create_director_reference(main.DirectorReferenceRequest(
                source_url="https://example.com/video.mp4",
                operation="first_frame",
            ))

        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("本地", caught.exception.detail)

    async def test_director_reference_rejects_invalid_or_out_of_bounds_segment(self):
        source = self.root / "source.mp4"
        source.write_bytes(b"video-source")

        with patch.object(main, "director_reference_duration_ms", return_value=5000):
            with self.assertRaises(HTTPException) as caught:
                await main.create_director_reference(main.DirectorReferenceRequest(
                    source_url=str(source), operation="video_segment", start_ms=-1, end_ms=1000,
                ))
            self.assertEqual(caught.exception.status_code, 400)

            with self.assertRaises(HTTPException) as caught:
                await main.create_director_reference(main.DirectorReferenceRequest(
                    source_url=str(source), operation="video_segment", start_ms=4500, end_ms=5100,
                ))
            self.assertEqual(caught.exception.status_code, 400)
            self.assertIn("超出", caught.exception.detail)

    async def test_director_reference_uses_stable_rebuildable_cache(self):
        source = self.root / "source.mp4"
        source.write_bytes(b"same-video-source")
        builds = []

        def fake_build(source_path, target_path, request, duration_ms):
            builds.append((source_path, target_path, request.operation, duration_ms))
            Path(target_path).parent.mkdir(parents=True, exist_ok=True)
            Path(target_path).write_bytes(b"frame")

        request = main.DirectorReferenceRequest(source_url=str(source), operation="last_frame")
        with patch.object(main, "director_reference_duration_ms", return_value=5000), patch.object(main, "build_director_reference_file", side_effect=fake_build):
            first = await main.create_director_reference(request)
            second = await main.create_director_reference(request)

        self.assertEqual(first["url"], second["url"])
        self.assertEqual(first["cache_key"], second["cache_key"])
        self.assertEqual(len(builds), 1)
        self.assertTrue(main.local_media_reference_path(first["url"]))

    async def test_director_export_orders_all_clip_types_by_midpoint_and_writes_manifest(self):
        sources = {}
        for name in ("first.mp4", "ordinary.mp4", "bridge.mp4"):
            path = self.root / name
            path.write_bytes(name.encode("utf-8"))
            sources[name] = str(path)
        payload = main.DirectorExportRequest(project_name="制作/A", clips=[
            main.DirectorExportClip(id="ordinary", type="ordinary", start_ms=5000, duration_ms=2000, created_at=2, result_id="r2", url=sources["ordinary.mp4"]),
            main.DirectorExportClip(id="bridge", type="connection", start_ms=3000, duration_ms=2000, created_at=2, result_id="r3", url=sources["bridge.mp4"]),
            main.DirectorExportClip(id="first", type="ordinary", start_ms=0, duration_ms=3000, created_at=1, result_id="r1", url=sources["first.mp4"]),
        ])

        result = await main.export_director_clips(payload)
        archive_path = main.local_media_reference_path(result["url"])

        self.assertTrue(archive_path)
        with zipfile.ZipFile(archive_path, "r") as archive:
            names = archive.namelist()
            self.assertEqual(names[:3], ["制作_A-clip-001.mp4", "制作_A-clip-002.mp4", "制作_A-clip-003.mp4"])
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        self.assertEqual([item["clip_id"] for item in manifest["clips"]], ["first", "bridge", "ordinary"])
        self.assertEqual(manifest["clips"][1]["type"], "connection")

    async def test_director_export_rejects_missing_or_remote_results(self):
        with self.assertRaises(HTTPException) as caught:
            await main.export_director_clips(main.DirectorExportRequest(project_name="A", clips=[
                main.DirectorExportClip(id="missing", type="ordinary", start_ms=0, duration_ms=1000, url="")
            ]))
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("结果", caught.exception.detail)

        with self.assertRaises(HTTPException) as caught:
            await main.export_director_clips(main.DirectorExportRequest(project_name="A", clips=[
                main.DirectorExportClip(id="remote", type="connection", start_ms=0, duration_ms=1000, url="https://example.com/a.mp4")
            ]))
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("本地", caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
