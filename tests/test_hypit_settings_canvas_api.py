import copy
import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from canvas_core.hypit_config import (
    HYPIT_FLOW_SCHEMA_VERSION,
    legacy_hypit_defaults_to_canvas,
    validate_hypit_settings_canvas,
)
from canvas_core.headless_canvas import HeadlessCanvas
from studio_hypit_canvas import (
    HYPIT_SETTINGS_CANVAS_ID,
    HypitSettingsCanvasService,
    create_hypit_settings_canvas_router,
    filter_hypit_settings_canvas_records,
    reject_hypit_settings_canvas_mutation,
)


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache" / "studio-tests"


def _canvas(revision=1):
    return {
        "id": HYPIT_SETTINGS_CANVAS_ID,
        "title": "Hypit 生成配置",
        "icon": "sparkles",
        "kind": "smart",
        "owner": "",
        "color": "",
        "pinned": False,
        "project": "__hypit_settings__",
        "created_at": 10,
        "updated_at": 10,
        "revision": revision,
        "node_schema_version": 1,
        "hypit_flow_schema_version": HYPIT_FLOW_SCHEMA_VERSION,
        "hypit_legacy_migration_done": True,
        "nodes": [],
        "connections": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
        "logs": [],
        "settings": {},
    }


def _image_graph(revision=1):
    value = _canvas(revision)
    value["nodes"] = [
        {
            "id": "image-generator",
            "type": "smart-image-generator",
            "x": 10,
            "y": 20,
            "promptDraftText": "migration fixture prompt",
            "runSettings": {"engine": "api", "apiKind": "image", "provider_id": "ai-money", "model": "laohu-test-image", "region": ""},
        },
        {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image"},
    ]
    value["connections"] = [{"id": "edge-1", "from": "image-generator", "to": "image-output", "kind": "flow"}]
    validate_hypit_settings_canvas(value)
    return value


def _legacy_prompt_scaffold_graph(revision=1):
    """重现旧版本精确生成的空提示素材占位，供一次性迁移测试使用。"""
    value = legacy_hypit_defaults_to_canvas({
        "image": {"provider": "ai-money", "model": "laohu-test-image", "region": ""},
    })
    value["project"] = "__hypit_settings__"
    value["revision"] = revision
    value["nodes"] = [node for node in value["nodes"]
                      if node.get("id") in {"hypit-run-image", "hypit-output-image"}]
    value["connections"] = [edge for edge in value["connections"]
                            if edge.get("from") == "hypit-run-image" and edge.get("to") == "hypit-output-image"]
    generator = next(node for node in value["nodes"] if node.get("id") == "hypit-run-image")
    generator["hypitLegacySelection"] = {"provider": "ai-money", "model": "laohu-test-image"}
    value["nodes"].append({
        "id": "hypit-prompt-image", "type": "smart-material", "title": "本次提示词",
        "sourceKind": "input", "hypitInputLocked": False, "images": [], "x": 0, "y": 220,
    })
    value["connections"].append({"from": "hypit-prompt-image", "to": "hypit-run-image", "kind": "input"})
    validate_hypit_settings_canvas(value)
    return value


class _FakeRepository:
    def __init__(self, directory, legacy=None):
        self.directory = Path(directory)
        self.canvas_path = self.directory / "data" / "canvases" / f"{HYPIT_SETTINGS_CANVAS_ID}.json"
        self.legacy_path = self.directory / "data" / "hypit_settings.json"
        self.backup_path = self.directory / "backups" / "hypit-settings-before-canvas-migration.json"
        self.scaffold_backup_path = self.directory / "backups" / "hypit-settings-before-empty-prompt-cleanup.json"
        self.canvas_path.parent.mkdir(parents=True, exist_ok=True)
        self.legacy_path.parent.mkdir(parents=True, exist_ok=True)
        if legacy is not None:
            self.legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
        self.lock = threading.RLock()
        self.migrations = []
        self.backups = 0
        self.scaffold_backups = 0
        self.saves = 0
        self.events = []
        self.status_reads = 0
        self.test_statuses = {"hypit-output-image": {"status": "passed", "test_passed": True}}
        self.revision_time = 10
        self.canonical_update_calls = []
        self.service = HypitSettingsCanvasService(
            load_canvas=self.load_canvas,
            save_canvas=self.save_canvas,
            lock=self.lock,
            load_legacy_settings=self.load_legacy_settings,
            backup_legacy_settings=self.backup_legacy_settings,
            backup_scaffold=self.backup_scaffold,
            migrate_legacy_settings=self.migrate_legacy_settings,
            validate_canvas=validate_hypit_settings_canvas,
            test_statuses=self.test_statuses_for_canvas,
            broadcast_canvas_updated=self.broadcast,
            now_ms=lambda: self.revision_time,
        )

    def load_canvas(self, canvas_id):
        if canvas_id != HYPIT_SETTINGS_CANVAS_ID or not self.canvas_path.exists():
            raise HTTPException(status_code=404, detail="画布不存在")
        return json.loads(self.canvas_path.read_text(encoding="utf-8"))

    def save_canvas(self, canvas, increment_revision=True, touch_updated_at=True):
        current = self.load_canvas(HYPIT_SETTINGS_CANVAS_ID) if self.canvas_path.exists() else None
        result = copy.deepcopy(canvas)
        result["revision"] = (int(current.get("revision") or 1) + 1) if current and increment_revision else max(1, int(result.get("revision") or 1))
        if touch_updated_at:
            self.revision_time += 1
            result["updated_at"] = self.revision_time
        temporary = self.canvas_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result), encoding="utf-8")
        temporary.replace(self.canvas_path)
        self.saves += 1
        return copy.deepcopy(result)

    def load_legacy_settings(self):
        if not self.legacy_path.exists():
            return None
        return json.loads(self.legacy_path.read_text(encoding="utf-8"))

    def backup_legacy_settings(self, _record):
        self.backup_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.backup_path.exists():
            self.backup_path.write_bytes(self.legacy_path.read_bytes())
            self.backups += 1

    def backup_scaffold(self, canvas):
        self.scaffold_backup_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.scaffold_backup_path.exists():
            self.scaffold_backup_path.write_text(json.dumps(canvas, ensure_ascii=False), encoding="utf-8")
            self.scaffold_backups += 1

    def migrate_legacy_settings(self, defaults, canvas_id):
        self.migrations.append(copy.deepcopy(defaults))
        return legacy_hypit_defaults_to_canvas(defaults, canvas_id=canvas_id)

    def test_statuses_for_canvas(self, canvas_id, canvas):
        self.status_reads += 1
        self.events.append(("status", canvas_id, [node.get("id") for node in canvas.get("nodes", [])]))
        return copy.deepcopy(self.test_statuses)

    async def broadcast(self, canvas_id, updated_at, revision, client_id):
        self.events.append(("broadcast", canvas_id, updated_at, revision, client_id))

    async def canonical_update(self, payload):
        """模拟宿主既有 PUT 入口；service 仅负责图校验，不持久化标准更新。"""
        self.canonical_update_calls.append(copy.deepcopy(payload))
        with self.lock:
            current = self.service.ensure_canvas()
            candidate = self.service.prepare_update_candidate(current, payload)
            saved = self.save_canvas(candidate, increment_revision=True, touch_updated_at=True)
        await self.broadcast(
            HYPIT_SETTINGS_CANVAS_ID,
            saved["updated_at"],
            saved["revision"],
            str(payload.get("client_id") or ""),
        )
        return {"canvas": saved}

    def build_client(self):
        app = FastAPI()

        @app.get("/api/canvases/{canvas_id}")
        async def standard_get(canvas_id):
            if canvas_id != HYPIT_SETTINGS_CANVAS_ID:
                raise HTTPException(status_code=404, detail="画布不存在")
            return {"canvas": await self.service.projected_canvas(self.service.ensure_canvas())}

        @app.put("/api/canvases/{canvas_id}")
        async def standard_put(canvas_id, payload: dict):
            if canvas_id != HYPIT_SETTINGS_CANVAS_ID:
                raise HTTPException(status_code=404, detail="画布不存在")
            result = await self.canonical_update(payload)
            return {"canvas": await self.service.projected_canvas(result["canvas"])}

        app.include_router(create_hypit_settings_canvas_router(service=self.service))
        self.app = app
        return TestClient(app)


class HypitSettingsCanvasApiTests(unittest.TestCase):
    def setUp(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        cache_tmp = CACHE / "tmp"
        cache_tmp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="hypit-settings-api-", dir=cache_tmp)
        self.repo = _FakeRepository(self.temp.name, {
            "version": 1,
            "defaults": {
                "image": {"provider": "ai-money", "model": "laohu-test-image", "region": ""},
                "text": {"provider": "", "model": ""},
            },
        })
        self.client = self.repo.build_client()

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_bootstrap_migrates_legacy_once_and_projects_read_only_test_statuses(self):
        response = self.client.get("/api/hypit/settings-canvas")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["id"], HYPIT_SETTINGS_CANVAS_ID)
        self.assertEqual(body["canvas"]["id"], HYPIT_SETTINGS_CANVAS_ID)
        self.assertEqual(body["url"], "/static/smart-canvas.html?id=hypit-settings&mode=hypit-settings")
        self.assertTrue(body["canvas"]["hypit_legacy_migration_done"])
        self.assertEqual(body["canvas"]["hypit_flow_schema_version"], HYPIT_FLOW_SCHEMA_VERSION)
        self.assertIn("hypit-output-image", [node["id"] for node in body["canvas"]["nodes"]])
        self.assertIn(
            {"from": "hypit-run-image", "to": "hypit-output-image", "kind": "input"},
            body["canvas"]["connections"],
        )
        self.assertEqual(
            {node["id"] for node in body["canvas"]["nodes"]},
            {"hypit-run-image", "hypit-output-image"},
        )
        image_node = next(node for node in body["canvas"]["nodes"] if node.get("type") == "smart-image-generator")
        self.assertEqual(image_node["runSettings"]["provider_id"], "ai-money")
        self.assertEqual(image_node["runSettings"]["model"], "laohu-test-image")
        self.assertEqual(image_node.get("promptDraftText", ""), "")
        self.assertEqual(body["canvas"]["test_statuses"], self.repo.test_statuses)
        stored = self.repo.load_canvas(HYPIT_SETTINGS_CANVAS_ID)
        self.assertNotIn("test_statuses", stored)
        self.assertEqual(self.repo.backups, 1)
        self.assertEqual(len(self.repo.migrations), 1)
        standard_canvas_paths = [route.path for route in self.repo.app.routes if "PUT" in getattr(route, "methods", set())]
        self.assertEqual(standard_canvas_paths.count("/api/canvases/{canvas_id}"), 1)
        self.assertNotIn("/api/hypit/settings-canvas", standard_canvas_paths)

        self.client.get("/api/hypit/settings-canvas")
        standard = self.client.get("/api/canvases/hypit-settings")
        self.assertEqual(standard.status_code, 200, standard.text)
        self.assertEqual(standard.json()["canvas"]["test_statuses"], self.repo.test_statuses)
        self.assertEqual(self.repo.backups, 1)
        self.assertEqual(len(self.repo.migrations), 1)

    def test_existing_exact_empty_prompt_scaffold_is_backed_up_and_removed_once(self):
        old_graph = _legacy_prompt_scaffold_graph(revision=7)
        self.repo.canvas_path.write_text(json.dumps(old_graph, ensure_ascii=False), encoding="utf-8")

        first = self.client.get("/api/hypit/settings-canvas")
        self.assertEqual(first.status_code, 200, first.text)
        saved = first.json()["canvas"]
        self.assertEqual(saved["revision"], 8)
        self.assertEqual(saved["nodes"], [node for node in old_graph["nodes"] if node["id"] != "hypit-prompt-image"])
        self.assertEqual(saved["connections"], [edge for edge in old_graph["connections"] if edge["from"] != "hypit-prompt-image"])
        self.assertEqual(self.repo.scaffold_backups, 1)
        backed_up = json.loads(self.repo.scaffold_backup_path.read_text(encoding="utf-8"))
        self.assertEqual(backed_up, old_graph)
        self.assertEqual(self.repo.events.count(("broadcast", HYPIT_SETTINGS_CANVAS_ID, saved["updated_at"], 8, "")), 1)

        save_count = self.repo.saves
        second = self.client.get("/api/hypit/settings-canvas")
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["canvas"]["revision"], 8)
        self.assertEqual(self.repo.saves, save_count)
        self.assertEqual(self.repo.scaffold_backups, 1)

    def test_edited_prompt_material_is_never_removed_or_backed_up_for_cleanup(self):
        edited = _legacy_prompt_scaffold_graph(revision=4)
        prompt = next(node for node in edited["nodes"] if node["id"] == "hypit-prompt-image")
        prompt["images"] = [{"kind": "text", "text": "用户已编辑的正文"}]
        validate_hypit_settings_canvas(edited)
        self.repo.canvas_path.write_text(json.dumps(edited, ensure_ascii=False), encoding="utf-8")

        response = self.client.get("/api/hypit/settings-canvas")
        self.assertEqual(response.status_code, 200, response.text)
        returned = response.json()["canvas"]
        self.assertEqual(returned["revision"], 4)
        self.assertEqual(returned["nodes"], edited["nodes"])
        self.assertEqual(self.repo.scaffold_backups, 0)
        self.assertEqual(self.repo.saves, 0)

    def test_exact_scaffold_is_not_mutated_when_backup_service_is_unavailable(self):
        old_graph = _legacy_prompt_scaffold_graph(revision=6)
        self.repo.canvas_path.write_text(json.dumps(old_graph, ensure_ascii=False), encoding="utf-8")
        self.repo.service._backup_scaffold = None

        response = self.client.get("/api/hypit/settings-canvas")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(self.repo.load_canvas(HYPIT_SETTINGS_CANVAS_ID), old_graph)
        self.assertEqual(self.repo.saves, 0)
        self.assertEqual(self.repo.scaffold_backups, 0)

    def test_flow_test_routes_delegate_submission_and_read_only_status(self):
        submissions = []

        async def submit_test(slot, output_node_id, operation_id, payload, *, test):
            submissions.append((slot, output_node_id, operation_id, copy.deepcopy(payload), test))
            return {"run_id": "run_fixture", "status": "queued"}

        def get_test(run_id):
            return {"run_id": run_id, "status": "succeeded", "output_kind": "image"}

        app = FastAPI()
        app.include_router(create_hypit_settings_canvas_router(
            service=self.repo.service, submit_test=submit_test, get_test=get_test,
        ))
        client = TestClient(app)
        try:
            payload = {
                "slot": "image",
                "output_node_id": "output-image",
                "client_operation_id": "operation-fixture",
                "base_revision": 2,
                "request": {"prompt": "isolated prompt", "system_prompt": "isolated system prompt"},
            }
            submitted = client.post("/api/hypit/settings-canvas/test", json=payload)
            self.assertEqual(submitted.status_code, 200, submitted.text)
            self.assertEqual(submitted.json(), {"run_id": "run_fixture", "status": "queued"})
            self.assertEqual(submissions, [("image", "output-image", "operation-fixture", payload, True)])
            status = client.get("/api/hypit/settings-canvas/test/run_fixture")
            self.assertEqual(status.status_code, 200, status.text)
            self.assertEqual(status.json()["status"], "succeeded")
        finally:
            client.close()

    def test_fresh_empty_initialization_is_marked_and_reset_never_reimports_late_legacy_settings(self):
        self.repo.legacy_path.unlink()
        first = self.client.get("/api/hypit/settings-canvas")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()["canvas"]["hypit_legacy_migration_done"])
        self.assertEqual(first.json()["canvas"]["nodes"], [])

        self.repo.legacy_path.write_text(json.dumps({"defaults": {"image": {"provider": "laohu", "model": "late"}}}), encoding="utf-8")
        reset = self.client.post("/api/hypit/settings-canvas/reset", json={"base_revision": 1, "client_id": "tab-a"})
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.json()["canvas"]["nodes"], [])
        self.assertEqual(self.repo.migrations, [])

    def test_specialized_put_requires_positive_revision_validates_and_rejects_stale_writes(self):
        self.client.get("/api/hypit/settings-canvas")
        graph = _image_graph()
        missing_revision = {key: value for key, value in graph.items() if key not in {"id", "revision", "updated_at"}}
        missing_revision["base_revision"] = 0
        rejected = self.client.put("/api/canvases/hypit-settings", json=missing_revision)
        self.assertEqual(rejected.status_code, 400, rejected.text)

        payload = {key: value for key, value in graph.items() if key not in {"id", "revision", "updated_at"}}
        payload.update({"base_revision": 1, "client_id": "tab-b"})
        invalid = copy.deepcopy(payload)
        invalid["nodes"][0]["type"] = "smart-video-generator"
        rejected_graph = self.client.put("/api/canvases/hypit-settings", json=invalid)
        self.assertEqual(rejected_graph.status_code, 400, rejected_graph.text)
        self.assertEqual(self.repo.load_canvas(HYPIT_SETTINGS_CANVAS_ID)["revision"], 1)

        saved = self.client.put("/api/canvases/hypit-settings", json=payload)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["canvas"]["revision"], 2)
        self.assertTrue(saved.json()["canvas"]["hypit_legacy_migration_done"])
        self.assertEqual(len(self.repo.canonical_update_calls), 3)  # 三次请求都走标准回调，失败校验不保存。
        self.assertEqual(self.repo.saves, 2)  # 首次迁移 + 一次有效标准 PUT。
        self.assertIn(("broadcast", HYPIT_SETTINGS_CANVAS_ID, 11, 2, "tab-b"), self.repo.events)

        stale = self.client.put("/api/canvases/hypit-settings", json=payload)
        self.assertEqual(stale.status_code, 409, stale.text)
        conflict = stale.json()["detail"]
        self.assertEqual(conflict["canvas"]["id"], HYPIT_SETTINGS_CANVAS_ID)
        self.assertEqual(conflict["canvas"]["revision"], 2)
        self.assertEqual(self.repo.load_canvas(HYPIT_SETTINGS_CANVAS_ID)["revision"], 2)

    def test_reset_revision_lock_clears_only_canvas_state_and_preserves_migration_markers(self):
        self.client.get("/api/hypit/settings-canvas")
        unrelated_result = self.repo.directory / "assets" / "output" / "keep-result.dat"
        unrelated_canvas = self.repo.directory / "data" / "canvases" / "other-work.json"
        unrelated_result.parent.mkdir(parents=True, exist_ok=True)
        unrelated_canvas.parent.mkdir(parents=True, exist_ok=True)
        unrelated_result.write_bytes(b"preserve-result")
        unrelated_canvas.write_bytes(b"preserve-other-canvas")
        saved = _image_graph()
        saved.update({"base_revision": 1, "client_id": "tab-c", "settings": {"projectPreference": "keep-unrelated-settings?"}})
        update = self.client.put("/api/canvases/hypit-settings", json=saved)
        self.assertEqual(update.status_code, 200, update.text)

        reset = self.client.post("/api/hypit/settings-canvas/reset", json={"base_revision": 2, "client_id": "tab-c"})
        self.assertEqual(reset.status_code, 200, reset.text)
        canvas = reset.json()["canvas"]
        self.assertEqual(canvas["revision"], 3)
        self.assertEqual(canvas["nodes"], [])
        self.assertEqual(canvas["connections"], [])
        self.assertEqual(canvas["settings"], {})
        self.assertEqual(canvas["logs"], [])
        self.assertEqual(canvas["viewport"], {"x": 0, "y": 0, "scale": 1})
        self.assertEqual(canvas["id"], HYPIT_SETTINGS_CANVAS_ID)
        self.assertTrue(canvas["hypit_legacy_migration_done"])
        self.assertEqual(canvas["hypit_flow_schema_version"], 1)
        self.assertEqual(self.repo.backups, 1)
        self.assertEqual(len(self.repo.migrations), 1)
        self.assertEqual(unrelated_result.read_bytes(), b"preserve-result")
        self.assertEqual(unrelated_canvas.read_bytes(), b"preserve-other-canvas")

        stale = self.client.post("/api/hypit/settings-canvas/reset", json={"base_revision": 2})
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(self.repo.load_canvas(HYPIT_SETTINGS_CANVAS_ID)["revision"], 3)

    def test_reserved_canvas_is_filtered_from_standard_lists_and_cannot_be_deleted_or_purged(self):
        records = [
            {"id": "ordinary-a", "project": "p1"},
            {"id": HYPIT_SETTINGS_CANVAS_ID, "project": "__hypit_settings__"},
            {"id": "ordinary-b", "project": "p2"},
        ]
        self.assertEqual([row["id"] for row in filter_hypit_settings_canvas_records(records)], ["ordinary-a", "ordinary-b"])
        with self.assertRaises(HTTPException) as delete_error:
            reject_hypit_settings_canvas_mutation(HYPIT_SETTINGS_CANVAS_ID, "删除")
        self.assertEqual(delete_error.exception.status_code, 409)
        reject_hypit_settings_canvas_mutation("ordinary-a", "删除")
        self.client.get("/api/hypit/settings-canvas")
        self.assertTrue(self.repo.canvas_path.exists())

    def test_agent_writes_share_graph_validation_and_stale_copy_cannot_restore_after_reset(self):
        self.repo.service.ensure_canvas()
        agent = HeadlessCanvas(
            load_canvas=lambda canvas_id: self.repo.service.ensure_canvas()
            if canvas_id == HYPIT_SETTINGS_CANVAS_ID else self.repo.load_canvas(canvas_id),
            save_canvas=self.repo.service.save_agent_canvas,
            lock=self.repo.lock,
            submit_run=lambda *_args: {"task_ids": []},
            cancel_run=lambda *_args: None,
            validate_model=lambda *_args: {"runnable": True},
        )

        async def edit_with_agent():
            material = await agent.execute(HYPIT_SETTINGS_CANVAS_ID, "create_node", {
                "kind": "material", "title": "输入正文", "text": "隔离测试文本",
            }, "agent-create-material")
            generator = await agent.execute(HYPIT_SETTINGS_CANVAS_ID, "create_node", {
                "kind": "text", "title": "文本生成", "defer_configuration": True,
            }, "agent-create-generator")
            await agent.execute(HYPIT_SETTINGS_CANVAS_ID, "connect", {
                "from": material["node_id"], "to": generator["node_id"],
            }, "agent-connect-text")

        asyncio.run(edit_with_agent())
        saved = self.repo.load_canvas(HYPIT_SETTINGS_CANVAS_ID)
        self.assertEqual(saved["project"], "__hypit_settings__")
        self.assertTrue(saved["hypit_legacy_migration_done"])
        self.assertTrue(any(
            edge.get("from") and edge.get("to")
            and edge.get("kind") == "input"
            for edge in saved["connections"]
        ))

        # 图级校验拒绝把视频执行节点连到图片用途输出，Agent 保存不落盘。
        invalid = copy.deepcopy(saved)
        image_source = next(node for node in invalid["nodes"] if node.get("type") == "smart-image-generator")
        image_source.update(type="smart-video-generator", outputKind="video")
        revision_before_invalid_save = saved["revision"]
        with self.assertRaises(HTTPException) as invalid_error:
            self.repo.service.save_agent_canvas(invalid)
        self.assertEqual(invalid_error.exception.status_code, 400)
        self.assertEqual(self.repo.load_canvas(HYPIT_SETTINGS_CANVAS_ID)["revision"], revision_before_invalid_save)

        stale_copy = copy.deepcopy(saved)
        reset = asyncio.run(self.repo.service.reset_canvas({
            "base_revision": saved["revision"], "client_id": "reset-tab",
        }))
        self.assertEqual(reset["canvas"]["nodes"], [])
        with self.assertRaises(HTTPException) as stale_error:
            self.repo.service.save_agent_canvas(stale_copy)
        self.assertEqual(stale_error.exception.status_code, 409)
        self.assertEqual(stale_error.exception.detail["canvas"]["nodes"], [])
        self.assertEqual(self.repo.load_canvas(HYPIT_SETTINGS_CANVAS_ID)["nodes"], [])


if __name__ == "__main__":
    unittest.main()
