import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from project_storage import ProjectStorage, StorageError


class ProjectStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.storage = ProjectStorage(self.root)
        self.storage.ensure_layout()

    def tearDown(self):
        self.temp.cleanup()

    def test_same_second_safety_backup_never_replaces_source_archive(self):
        value = self.storage.data_dir / 'sentinel.json'
        value.write_text('{"value": 1}', encoding='utf-8')
        with patch('project_storage.time.strftime', return_value='20260913-000000'):
            original = self.storage.create_backup()
            original_bytes = original.read_bytes()
            value.write_text('{"value": 2}', encoding='utf-8')
            restored = self.storage.restore_backup(original, create_safety_backup=True)
        self.assertNotEqual(str(original), restored['safety_backup'])
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual(json.loads(value.read_text())['value'], 1)
        with zipfile.ZipFile(restored['safety_backup']) as backup:
            self.assertEqual(json.loads(backup.read('data/sentinel.json'))['value'], 2)

    def test_layout_separates_structured_data_media_workflows_backups_and_cache(self):
        layout = self.storage.layout()

        self.assertEqual(layout["materials"], self.root / "assets" / "input")
        self.assertEqual(layout["results"], self.root / "assets" / "output")
        self.assertEqual(layout["config"], self.root / "data" / "settings")
        self.assertEqual(layout["indexes"], self.root / "data" / "indexes")
        self.assertEqual(layout["workflows"], self.root / "workflows")
        self.assertEqual(layout["backups"], self.root / "backups")
        self.assertEqual(layout["previews"], self.root / "cache" / "previews")

    def test_prepare_run_reuses_same_client_operation(self):
        first = self.storage.prepare_run(
            canvas_id="canvas-1",
            node_id="node-1",
            client_operation_id="operation-1",
            standard_request={"provider_id": "fixture", "model_id": "model-1", "inputs": {"prompt": "测试"}},
            platform_request={"model": "model-1", "prompt": "测试"},
        )
        second = self.storage.prepare_run(
            canvas_id="canvas-1",
            node_id="node-1",
            client_operation_id="operation-1",
            standard_request={"provider_id": "fixture", "model_id": "model-1", "inputs": {"prompt": "测试"}},
            platform_request={"model": "model-1", "prompt": "测试"},
        )

        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["attempts"][0]["attempt_id"], second["attempts"][0]["attempt_id"])
        self.assertEqual(first["attempts"][0]["idempotency_key"], second["attempts"][0]["idempotency_key"])
        self.assertEqual(len(self.storage.list_runs()), 1)

    def test_prepare_run_creates_new_record_for_new_operation(self):
        request = {"provider_id": "fixture", "model_id": "model-1", "inputs": {"prompt": "测试"}}
        first = self.storage.prepare_run("canvas-1", "node-1", "operation-1", request, {"model": "model-1"})
        second = self.storage.prepare_run("canvas-1", "node-1", "operation-2", request, {"model": "model-1"})

        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(len(self.storage.list_runs()), 2)

    def test_prepare_run_rejects_changed_request_for_same_operation(self):
        self.storage.prepare_run(
            "canvas-1", "node-1", "operation-1",
            {"provider_id": "fixture", "model_id": "model-1", "inputs": {"prompt": "第一次"}},
            {"model": "model-1", "prompt": "第一次"},
        )

        with self.assertRaises(StorageError):
            self.storage.prepare_run(
                "canvas-1", "node-1", "operation-1",
                {"provider_id": "fixture", "model_id": "model-1", "inputs": {"prompt": "第二次"}},
                {"model": "model-1", "prompt": "第二次"},
            )

    def test_run_status_uses_whitelisted_transitions_and_results_are_union(self):
        run = self.storage.prepare_run(
            "canvas-1", "node-1", "operation-1",
            {"provider_id": "fixture", "model_id": "model-1"},
            {"model": "model-1"},
        )
        run_id = run["run_id"]
        self.storage.update_run_status(run_id, "queued")
        self.storage.update_run_status(run_id, "submitted", provider_task_id="task-1")
        self.storage.update_run_status(run_id, "processing")
        self.storage.append_run_results(run_id, ["res_1", "res_2"])
        updated = self.storage.append_run_results(run_id, ["res_2", "res_3"])

        self.assertEqual(updated["attempts"][0]["result_ids"], ["res_1", "res_2", "res_3"])
        self.assertEqual(updated["attempts"][0]["provider_task_id"], "task-1")
        with self.assertRaises(StorageError):
            self.storage.update_run_status(run_id, "queued")

    def test_run_snapshots_remove_credentials(self):
        run = self.storage.prepare_run(
            "canvas-1", "node-1", "operation-1",
            {"provider_id": "fixture", "authorization": "Bearer secret", "inputs": {"prompt": "测试"}},
            {"apiKey": "secret", "nested": {"cookie": "secret", "value": 1}},
        )
        stored = json.loads(self.storage.run_index_path.read_text(encoding="utf-8"))
        serialized = json.dumps(stored, ensure_ascii=False).lower()

        self.assertNotIn("bearer secret", serialized)
        self.assertNotIn('"apikey"', serialized)
        self.assertNotIn('"cookie"', serialized)
        self.assertEqual(run["standard_request"]["inputs"]["prompt"], "测试")

    def test_canvas_tasks_persist_across_storage_instances(self):
        created = self.storage.create_canvas_task({
            "id": "canvas_img_1",
            "type": "online-image",
            "status": "queued",
            "provider_id": "fixture",
            "model": "fixture-image",
        })
        self.storage.update_canvas_task(created["id"], status="succeeded", result={
            "images": ["/api/results/res_1"],
            "image_items": [{"url": "/api/results/res_1", "result_id": "res_1"}],
        })

        reopened = ProjectStorage(self.root)
        reopened.ensure_layout()
        task = reopened.get_canvas_task(created["id"])

        self.assertEqual(task["status"], "succeeded")
        self.assertEqual(task["result"]["image_items"][0]["result_id"], "res_1")

    def test_interrupted_canvas_tasks_become_recoverable_without_resubmission(self):
        self.storage.create_canvas_task({
            "id": "canvas_img_queued",
            "type": "online-image",
            "status": "queued",
            "provider_id": "fixture",
        })
        self.storage.create_canvas_task({
            "id": "canvas_img_running",
            "type": "online-image",
            "status": "running",
            "provider_id": "fixture",
            "upstream_task_id": "upstream-1",
        })
        self.storage.create_canvas_task({
            "id": "canvas_img_done",
            "type": "online-image",
            "status": "succeeded",
            "provider_id": "fixture",
        })

        recovered = self.storage.recover_interrupted_canvas_tasks()

        self.assertEqual({item["id"] for item in recovered}, {"canvas_img_queued", "canvas_img_running"})
        self.assertEqual(self.storage.get_canvas_task("canvas_img_queued")["status"], "recoverable")
        self.assertEqual(self.storage.get_canvas_task("canvas_img_running")["upstream_task_id"], "upstream-1")
        self.assertEqual(self.storage.get_canvas_task("canvas_img_done")["status"], "succeeded")

    def test_same_material_content_is_stored_once_and_reused(self):
        first = self.storage.store_material_bytes(b"same-image", "封面.png", scope="temporary")
        second = self.storage.store_material_bytes(b"same-image", "再次上传.png", scope="temporary")

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["path"], second["path"])
        self.assertEqual(first["original_name"], "封面.png")
        self.assertEqual(first["display_name"], "封面.png")
        self.assertEqual(first["path"], "input/temporary/image/封面.png")
        self.assertEqual(len(list((self.root / "assets" / "input").rglob("*.png"))), 1)

    def test_external_material_result_is_idempotent_and_shares_managed_file(self):
        material = self.storage.store_material_bytes(b"external-image", "画面.png", scope="temporary")
        receipt = {
            "provider": "dreamina",
            "tool": "dreamina-cli",
            "model": "image-v3",
            "task_id": "task-001",
            "output_index": 1,
        }

        first = self.storage.register_external_material_result(material["id"], **receipt)
        repeated = self.storage.register_external_material_result(material["id"], **receipt)
        another_task = self.storage.register_external_material_result(
            material["id"], **{**receipt, "task_id": "task-002"}
        )

        self.assertEqual(first["id"], repeated["id"])
        self.assertNotEqual(first["id"], another_task["id"])
        self.assertEqual(len(self.storage.list_results()), 2)
        self.assertEqual(first["origin"], {
            "kind": "external_cli",
            "source_material_id": material["id"],
            **receipt,
            "provenance_verified": False,
        })
        self.assertNotIn("run_id", first)
        self.assertNotIn("canvas_task_id", first)
        self.assertEqual(self.storage.result_path(first["id"]), self.storage.material_path(material["id"]))
        self.assertEqual(first["path"], material["path"])
        self.assertEqual(len(list((self.root / "assets" / "input").rglob("*.png"))), 1)
        self.assertEqual(list((self.root / "assets" / "output").rglob("*.png")), [])

    def test_external_material_result_rejects_missing_unmanaged_and_corrupt_materials(self):
        with self.assertRaises(StorageError):
            self.storage.register_external_material_result(
                "mat_missing", provider="dreamina", tool="cli", model="m1", task_id="t1", output_index=1
            )

        material = self.storage.store_material_bytes(b"managed", "managed.png", scope="asset")
        index = json.loads(self.storage.material_index_path.read_text(encoding="utf-8"))
        item = next(entry for entry in index["items"] if entry["id"] == material["id"])

        item["path"] = "output/image/managed.png"
        self.storage.material_index_path.write_text(json.dumps(index), encoding="utf-8")
        with self.assertRaises(StorageError):
            self.storage.register_external_material_result(
                material["id"], provider="dreamina", tool="cli", model="m1", task_id="t1", output_index=1
            )

        item["path"] = "input/asset/image/managed.png"
        item["sha256"] = "0" * 64
        self.storage.material_index_path.write_text(json.dumps(index), encoding="utf-8")
        with self.assertRaises(StorageError):
            self.storage.register_external_material_result(
                material["id"], provider="dreamina", tool="cli", model="m1", task_id="t1", output_index=1
            )

        item["sha256"] = material["sha256"]
        item["path"] = "input/asset/image/missing.png"
        self.storage.material_index_path.write_text(json.dumps(index), encoding="utf-8")
        with self.assertRaises(StorageError):
            self.storage.register_external_material_result(
                material["id"], provider="dreamina", tool="cli", model="m1", task_id="t1", output_index=1
            )

    def test_external_material_result_rejects_url_path_credentials_and_invalid_index(self):
        material = self.storage.store_material_bytes(b"validated", "validated.png", scope="asset")
        valid = {"provider": "dreamina", "tool": "cli", "model": "m1", "task_id": "t1", "output_index": 1}
        invalid_receipts = [
            {**valid, "provider": "https://provider.example"},
            {**valid, "tool": "data:image/png;base64,AA"},
            {**valid, "model": "image api_key=private"},
            {**valid, "task_id": "../secret"},
            {**valid, "task_id": "task\nforged"},
            {**valid, "output_index": True},
            {**valid, "output_index": 0},
            {**valid, "output_index": 101},
        ]

        for receipt in invalid_receipts:
            with self.subTest(receipt=receipt), self.assertRaises(StorageError):
                self.storage.register_external_material_result(material["id"], **receipt)
        self.assertEqual(self.storage.list_results(), [])

    def test_external_result_alias_tracks_material_moves_and_renames(self):
        material = self.storage.store_material_bytes(b"movable-image", "初稿.png", scope="temporary")
        result = self.storage.register_external_material_result(
            material["id"], provider="dreamina", tool="cli", model="m1", task_id="task-move", output_index=1
        )

        promoted = self.storage.promote_material(material["id"])
        promoted_result = self.storage.get_result(result["id"])
        self.assertEqual(promoted_result["path"], promoted["path"])
        self.assertEqual(self.storage.result_path(result["id"]), self.storage.material_path(material["id"]))

        self.storage.add_material_scope(material["id"], "temporary")
        demoted = self.storage.remove_material_scope(material["id"], "asset")
        temporary = self.storage.get_material(material["id"])
        self.assertEqual(demoted["deleted_file"], False)
        self.assertEqual(temporary["path"], "input/temporary/image/初稿.png")
        self.assertEqual(self.storage.get_result(result["id"])["path"], temporary["path"])

        readded = self.storage.add_material_scope(material["id"], "asset")
        self.assertEqual(readded["path"], "input/asset/image/初稿.png")
        self.assertEqual(self.storage.get_result(result["id"])["path"], readded["path"])

        renamed = self.storage.rename_material(material["id"], "终稿")
        self.assertEqual(renamed["path"], "input/asset/image/终稿.png")
        self.assertEqual(self.storage.get_result(result["id"])["path"], renamed["path"])
        self.assertEqual(self.storage.result_path(result["id"]), self.storage.material_path(material["id"]))
        self.assertEqual(len(list((self.root / "assets" / "input").rglob("*.png"))), 1)

    def test_external_alias_delete_order_preserves_referenced_material_file(self):
        material = self.storage.store_material_bytes(b"shared-image", "shared.png", scope="asset")
        result = self.storage.register_external_material_result(
            material["id"], provider="dreamina", tool="cli", model="m1", task_id="task-delete", output_index=1
        )
        shared_path = self.storage.material_path(material["id"])

        self.assertTrue(self.storage.delete_result(result["id"]))
        self.assertTrue(shared_path.is_file())
        self.assertEqual(self.storage.material_path(material["id"]), shared_path)
        alias2 = self.storage.register_external_material_result(
            material["id"], provider="dreamina", tool="cli", model="m1", task_id="task-rename", output_index=1
        )
        renamed_alias = self.storage.rename_result(alias2["id"], "用户显示名")
        self.assertEqual(renamed_alias["display_name"], "用户显示名.png")
        self.assertEqual(renamed_alias["path"], material["path"])
        self.assertEqual(self.storage.material_path(material["id"]), shared_path)
        self.assertFalse((self.root / "assets" / "output" / "image" / "用户显示名.png").exists())
        self.assertTrue(self.storage.delete_result(alias2["id"]))
        self.assertEqual(self.storage.remove_material_scope(material["id"], "asset")["deleted_file"], True)
        self.assertFalse(shared_path.exists())

        material2 = self.storage.store_material_bytes(b"shared-image-2", "shared2.png", scope="asset")
        result2 = self.storage.register_external_material_result(
            material2["id"], provider="dreamina", tool="cli", model="m1", task_id="task-delete-2", output_index=1
        )
        shared_path2 = self.storage.material_path(material2["id"])

        self.assertFalse(self.storage.remove_material_scope(material2["id"], "asset")["deleted_file"])
        retained = self.storage.get_material(material2["id"])
        self.assertEqual(retained["scopes"], [])
        self.assertEqual(self.storage.result_path(result2["id"]), shared_path2)
        self.assertTrue(shared_path2.is_file())

        self.assertTrue(self.storage.delete_result(result2["id"]))
        self.assertIsNone(self.storage.get_material(material2["id"]))
        self.assertFalse(shared_path2.exists())

    def test_rename_result_preserves_stable_id_and_url(self):
        source = self.root / "generated.png"
        source.write_bytes(b"generated-image")
        result = self.storage.store_result_file(source, "第一次名称.png", move=True)

        renamed = self.storage.rename_result(result["id"], "第二次名称")

        self.assertEqual(renamed["id"], result["id"])
        self.assertEqual(renamed["url"], self.storage.result_url(result["id"]))
        self.assertEqual(renamed["display_name"], "第二次名称.png")
        self.assertTrue(self.storage.result_path(result["id"]).is_file())
        self.assertEqual(self.storage.result_path(result["id"]).read_bytes(), b"generated-image")

    def test_prune_missing_results_only_removes_missing_requested_kind(self):
        image_source = self.root / "missing.png"
        image_source.write_bytes(b"missing-image")
        image_result = self.storage.store_result_file(image_source, "失效图片.png", move=True)

        text_source = self.root / "kept.md"
        text_source.write_text("保留文本", encoding="utf-8")
        text_result = self.storage.store_result_file(text_source, "保留文本.md", move=True)
        self.storage.result_path(image_result["id"]).unlink()

        self.assertEqual(self.storage.prune_missing_results("image"), 1)
        self.assertIsNone(self.storage.get_result(image_result["id"]))
        self.assertIsNotNone(self.storage.get_result(text_result["id"]))
        self.assertEqual([item["id"] for item in self.storage.list_results("text")], [text_result["id"]])

    def test_promoting_material_does_not_create_another_file(self):
        temporary = self.storage.store_material_bytes(b"image", "人物.png", scope="temporary")
        promoted = self.storage.promote_material(temporary["id"])

        self.assertEqual(promoted["scopes"], ["asset"])
        self.assertEqual(promoted["path"], "input/asset/image/人物.png")
        self.assertEqual(self.storage.list_materials("temporary"), [])
        self.assertEqual(len(list((self.root / "assets" / "input").rglob("*.png"))), 1)

    def test_legacy_dual_scope_asset_is_not_listed_as_temporary(self):
        item = self.storage.store_material_bytes(b"image", "旧素材.png", scope="temporary")
        self.storage.add_material_scope(item["id"], "asset")

        self.assertEqual(self.storage.list_materials("temporary"), [])
        self.assertEqual(len(self.storage.list_materials("asset")), 1)

    def test_result_keeps_source_canvas_metadata(self):
        source = self.root / "result.png"
        source.write_bytes(b"result")
        result = self.storage.store_result_file(source, "结果.png")

        updated = self.storage.set_result_source_canvas(
            result["id"],
            {"id": "canvas-1", "title": "产品主图", "kind": "smart"},
        )

        self.assertEqual(updated["source_canvas"]["id"], "canvas-1")
        self.assertEqual(updated["source_canvas"]["title"], "产品主图")
        self.assertEqual(self.storage.list_results()[0]["source_canvas"]["kind"], "smart")

    def test_renaming_material_updates_readable_file_name_and_keeps_original_name(self):
        item = self.storage.store_material_bytes(b"image", "旧名称.png", scope="temporary")
        renamed = self.storage.rename_material(item["id"], "新名称")

        self.assertEqual(renamed["display_name"], "新名称")
        self.assertEqual(renamed["original_name"], "旧名称.png")
        self.assertEqual(renamed["path"], "input/temporary/image/新名称.png")
        self.assertFalse((self.root / "assets" / item["path"]).exists())

    def test_renaming_material_cannot_change_file_extension(self):
        item = self.storage.store_material_bytes(b"image", "旧名称.png", scope="temporary")

        renamed = self.storage.rename_material(item["id"], "新名称.jpg")

        self.assertEqual(renamed["display_name"], "新名称")
        self.assertEqual(renamed["path"], "input/temporary/image/新名称.png")
        self.assertTrue((self.root / "assets" / renamed["path"]).is_file())

    def test_results_keep_distinct_records_while_reusing_physical_content(self):
        source_a = self.root / "first.mp4"
        source_b = self.root / "second.mp4"
        source_a.write_bytes(b"video-data")
        source_b.write_bytes(b"video-data")

        first = self.storage.store_result_file(source_a, "第一个视频.mp4")
        second = self.storage.store_result_file(source_b, "第二个视频.mp4")

        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["kind"], "video")
        self.assertEqual(first["path"], "output/video/第一个视频.mp4")
        self.assertEqual(first["path"], second["path"])
        self.assertEqual(len(self.storage.list_results()), 2)
        self.assertEqual(len(list((self.root / "assets" / "output" / "video").glob("*.mp4"))), 1)

        self.assertTrue(self.storage.delete_result(first["id"]))
        self.assertIsNotNone(self.storage.result_path(second["id"]))
        self.assertEqual(self.storage.result_path(second["id"]).read_bytes(), b"video-data")

    def test_migration_rewrites_canvas_and_asset_library_references(self):
        legacy_input = self.root / "assets" / "input"
        legacy_library = self.root / "assets" / "library" / "角色"
        legacy_input.mkdir(parents=True, exist_ok=True)
        legacy_library.mkdir(parents=True, exist_ok=True)
        (legacy_input / "ai_ref_old.png").write_bytes(b"temporary")
        (legacy_library / "lib_old.png").write_bytes(b"asset")
        canvas_dir = self.root / "data" / "canvases"
        canvas_dir.mkdir(parents=True)
        canvas_path = canvas_dir / "canvas.json"
        canvas_path.write_text(json.dumps({
            "nodes": [{"images": [{"url": "/assets/input/ai_ref_old.png", "name": "输入图.png"}]}]
        }, ensure_ascii=False), encoding="utf-8")
        library_path = self.root / "data" / "asset_library.json"
        library_path.write_text(json.dumps({
            "libraries": [{"id": "default", "name": "默认资产库", "categories": [{
                "id": "characters", "items": [{"id": "asset_old", "name": "人物", "url": "/assets/library/角色/lib_old.png"}]
            }]}]
        }, ensure_ascii=False), encoding="utf-8")

        report = self.storage.migrate_legacy(cleanup=False)

        canvas = json.loads(canvas_path.read_text(encoding="utf-8"))
        image = canvas["nodes"][0]["images"][0]
        library = json.loads(library_path.read_text(encoding="utf-8"))
        asset = library["libraries"][0]["categories"][0]["items"][0]
        self.assertTrue(image["url"].startswith("/api/materials/"))
        self.assertTrue(image["material_id"].startswith("mat_"))
        self.assertTrue(asset["url"].startswith("/api/materials/"))
        self.assertEqual(asset["material_id"], asset["url"].rsplit("/", 1)[-1])
        self.assertEqual(library["libraries"][0]["name"], "资产库")
        self.assertEqual(report["materials"], 2)

    def test_migration_places_workflows_settings_and_previews_in_dedicated_directories(self):
        legacy_workflow = self.root / "workflows" / "旧工作流.json"
        legacy_workflow.write_text('{"1": {"class_type": "Test"}}', encoding="utf-8")
        (self.root / "history.json").write_text("[]", encoding="utf-8")
        (self.root / "global_config.json").write_text('{"token": "legacy"}', encoding="utf-8")
        legacy_preview = self.root / "data" / "media_previews" / "preview.webp"
        legacy_preview.parent.mkdir(parents=True)
        legacy_preview.write_bytes(b"preview")

        self.storage.migrate_legacy(cleanup=False)

        self.assertTrue((self.root / "workflows" / "comfyui" / "旧工作流.json").is_file())
        self.assertTrue((self.root / "data" / "history.json").is_file())
        self.assertTrue((self.root / "data" / "settings" / "global.json").is_file())
        self.assertTrue((self.root / "cache" / "previews" / "media" / "preview.webp").is_file())

    def test_migration_rewrites_legacy_canvas_workflow_url(self):
        legacy_workflow = self.root / "assets" / "library" / "工作流" / "批处理.zip"
        legacy_workflow.parent.mkdir(parents=True)
        legacy_workflow.write_bytes(b"workflow")
        library_path = self.root / "data" / "asset_library.json"
        library_path.write_text(json.dumps({
            "libraries": [{"id": "default", "name": "资产库", "categories": [{
                "id": "workflows",
                "type": "workflow",
                "items": [{"id": "wf_old", "name": "批处理", "url": "/assets/library/工作流/批处理.zip"}],
            }]}],
        }, ensure_ascii=False), encoding="utf-8")

        self.storage.migrate_legacy(cleanup=False)

        library = json.loads(library_path.read_text(encoding="utf-8"))
        item = library["libraries"][0]["categories"][0]["items"][0]
        self.assertTrue(item["url"].startswith("/workflow-files/"))
        self.assertTrue((self.storage.canvas_workflows_dir / "批处理.zip").is_file())

    def test_cleanup_removes_nested_empty_legacy_directories(self):
        legacy = self.root / "assets" / "library" / "角色" / "人物"
        legacy.mkdir(parents=True)
        (legacy / "参考图.png").write_bytes(b"asset")
        (self.root / "assets" / "library" / ".DS_Store").write_bytes(b"metadata")
        (self.root / "data" / "media_previews").mkdir(parents=True)

        self.storage.migrate_legacy(cleanup=True)

        self.assertFalse((self.root / "assets" / "library").exists())
        self.assertFalse((self.root / "data" / "media_previews").exists())
        self.assertEqual(len(self.storage.list_materials("asset")), 1)

    def test_backup_contains_runtime_data_and_excludes_nested_backups(self):
        (self.root / "data" / "canvases").mkdir(parents=True)
        (self.root / "data" / "canvases" / "one.json").write_text("{}", encoding="utf-8")
        (self.root / "assets" / "materials").mkdir(parents=True, exist_ok=True)
        (self.root / "assets" / "materials" / "one.bin").write_bytes(b"asset")
        self.storage.backups_dir.mkdir(parents=True, exist_ok=True)
        (self.storage.backups_dir / "old.zip").write_bytes(b"old")
        (self.root / "API").mkdir()
        (self.root / "API" / ".env").write_text("SECRET=1", encoding="utf-8")

        archive = self.storage.create_backup(include_secrets=True)

        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
        self.assertIn("data/canvases/one.json", names)
        self.assertIn("assets/materials/one.bin", names)
        self.assertIn("API/.env", names)
        self.assertNotIn("data/backups/old.zip", names)
        self.assertIn("backup-manifest.json", names)

    def test_restore_rejects_archive_path_traversal(self):
        archive = self.root / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("../outside.txt", "bad")

        with self.assertRaises(StorageError):
            self.storage.restore_backup(archive)


if __name__ == "__main__":
    unittest.main()
