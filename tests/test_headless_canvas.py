import asyncio
import copy
import threading
import time
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from canvas_agent import create_agent_router
from canvas_core.headless_canvas import HeadlessCanvas


ROOT = Path(__file__).resolve().parents[1]


class HeadlessCanvasTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.lock = threading.RLock()
        self.stored = {
            "id": "canvas-1",
            "revision": 1,
            "nodes": [],
            "connections": [],
            "settings": {},
        }
        self.saved = []
        self.validated = []
        self.submitted = []
        self.cancelled = []
        self.notifications = []
        self.task_counter = 0

        def load_canvas(canvas_id):
            self.assertEqual(canvas_id, self.stored["id"])
            with self.lock:
                return copy.deepcopy(self.stored)

        def save_canvas(canvas):
            with self.lock:
                self.saved.append(copy.deepcopy(canvas))
                self.stored = copy.deepcopy(canvas)

        def validate_model(kind, provider, model, parameters):
            self.validated.append((kind, provider, model, copy.deepcopy(parameters)))
            if provider != "provider-a" or model not in {"image-1", "text-1"}:
                raise ValueError("model unavailable")
            allowed = {"count", "seed", "temperature"}
            if any(key not in allowed for key in parameters):
                raise ValueError("unsupported parameter")
            return {
                "model_id": model,
                "family_id": f"family-{model}",
                "runnable": True,
                "parameters": {key: {} for key in allowed},
            }

        async def submit_run(canvas, node, request_id):
            self.task_counter += 1
            task_id = f"task-{self.task_counter}"
            task = {
                "id": task_id,
                "creationTask": True,
                "creationId": node.get("creationId"),
                "sourceExecutionNodeId": node["id"],
                "runStatus": "queued",
            }
            node.setdefault("creationTasks", []).append(task)
            self.submitted.append((request_id, node["id"], task_id))
            return [task_id]

        async def cancel_run(canvas, node, task_id):
            self.cancelled.append((node["id"], task_id))
            for task in node.get("creationTasks", []):
                if task.get("id") == task_id:
                    task["runStatus"] = "cancelled"

        async def notify(canvas):
            self.notifications.append(copy.deepcopy(canvas))

        self.load_canvas = load_canvas
        self.executor = HeadlessCanvas(
            load_canvas=load_canvas,
            save_canvas=save_canvas,
            lock=self.lock,
            submit_run=submit_run,
            cancel_run=cancel_run,
            validate_model=validate_model,
            notify=notify,
        )

    def _use_hypit_settings_canvas(self):
        self.stored = {
            "id": "hypit-settings",
            "kind": "smart",
            "project": "hypit-settings",
            "revision": 1,
            "hypit_flow_schema_version": 1,
            "hypit_legacy_migration_done": True,
            "nodes": [],
            "connections": [],
            "settings": {},
            "logs": [],
            "viewport": {"x": 0, "y": 0, "scale": 1},
        }

    async def test_hypit_output_creation_is_settings_canvas_only_and_reuses_slot(self):
        self._use_hypit_settings_canvas()
        created = await self.executor.execute(
            "hypit-settings",
            "create_node",
            {"kind": "hypit_output", "slot": "image", "title": "图片输出", "x": 640, "y": 80},
            "create-hypit-output",
        )
        moved = await self.executor.execute(
            "hypit-settings",
            "update_node",
            {"node_id": created["node_id"], "x": 940, "y": 245},
            "move-hypit-output",
        )
        self.assertEqual((moved["node"]["x"], moved["node"]["y"]), (940, 245))
        repeated = await self.executor.execute(
            "hypit-settings",
            "create_node",
            {"kind": "hypit_output", "slot": "image", "title": "再次添加图片输出"},
            "focus-existing-hypit-output",
        )
        outputs = [node for node in self.stored["nodes"] if node.get("type") == "smart-hypit-output"]
        self.assertEqual(len(outputs), 1)
        self.assertEqual(repeated["node_id"], created["node_id"])
        self.assertEqual(repeated["node"]["hypitSlot"], "image")
        self.assertEqual((repeated["node"]["x"], repeated["node"]["y"]), (940, 245))
        self.assertTrue(repeated["existing"])

        self.stored = {"id": "canvas-1", "revision": 1, "nodes": [], "connections": [], "settings": {}}
        with self.assertRaises(ValueError):
            await self.executor.execute(
                "canvas-1",
                "create_node",
                {"kind": "hypit_output", "slot": "image", "title": "普通画布不能创建"},
                "reject-ordinary-output",
            )
        self.assertEqual(self.stored["nodes"], [])

    async def test_hypit_output_connections_validate_and_replace_atomically(self):
        self._use_hypit_settings_canvas()
        output = await self.executor.execute(
            "hypit-settings",
            "create_node",
            {"kind": "hypit_output", "slot": "image", "title": "图片输出"},
            "create-output-for-connect",
        )
        self.stored["nodes"].extend([
            {"id": "image-node", "type": "smart-image-generator", "title": "图片生成", "outputKind": "image", "images": []},
            {"id": "text-node", "type": "smart-text-generator", "title": "文本生成", "outputKind": "text", "images": []},
            {"id": "app-node", "type": "smart-ai-app", "title": "AI 应用", "outputKind": "dynamic", "images": []},
        ])
        first = await self.executor.execute(
            "hypit-settings", "connect", {"from": "image-node", "to": output["node_id"]}, "connect-static-image"
        )
        self.assertEqual(first["connections"][-1]["from"], "image-node")

        replaced = await self.executor.execute(
            "hypit-settings", "connect", {"from": "app-node", "to": output["node_id"]}, "replace-with-dynamic-app"
        )
        incoming = [edge for edge in replaced["connections"] if edge.get("to") == output["node_id"]]
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0]["from"], "app-node")

        before_invalid = copy.deepcopy(self.stored["connections"])
        with self.assertRaises(ValueError):
            await self.executor.execute(
                "hypit-settings", "connect", {"from": "text-node", "to": output["node_id"]}, "reject-static-text"
            )
        self.assertEqual(self.stored["connections"], before_invalid)

        with self.assertRaises(ValueError):
            await self.executor.execute(
                "hypit-settings", "connect", {"from": output["node_id"], "to": "image-node", "relation": "story"},
                "reject-output-source",
            )
        self.assertEqual(self.stored["connections"], before_invalid)

    async def test_hypit_dynamic_app_preserves_explicit_field_for_unknown_media(self):
        self._use_hypit_settings_canvas()
        self.stored["nodes"] = [
            {
                "id": "unknown-source",
                "type": "smart-material",
                "title": "未识别素材",
                "images": [{"kind": "vendor-payload", "url": "/assets/input.bin"}],
            },
            {
                "id": "dynamic-app",
                "type": "smart-ai-app",
                "title": "动态应用",
                "runSettings": {"rhFields": [{"nodeId": "2", "fieldName": "image", "fieldType": "IMAGE"}]},
            },
            {
                "id": "second-unknown-source",
                "type": "smart-material",
                "title": "未映射素材",
                "images": [{"kind": "vendor-payload", "url": "/assets/second.bin"}],
            },
        ]
        result = await self.executor.execute(
            "hypit-settings",
            "connect",
            {"from": "unknown-source", "to": "dynamic-app", "target_field_key": "user-selected::attachment"},
            "connect-explicit-unknown-app-field",
        )
        self.assertEqual(len(result["connections"]), 1)
        self.assertEqual(result["connections"][0]["from"], "unknown-source")
        self.assertEqual(result["connections"][0]["targetFieldKey"], "user-selected::attachment")

        unmapped = await self.executor.execute(
            "hypit-settings",
            "connect",
            {"from": "second-unknown-source", "to": "dynamic-app"},
            "connect-unmapped-app-source",
        )
        self.assertIn("second-unknown-source", [edge["from"] for edge in unmapped["connections"]])
        self.assertFalse(any(edge.get("from") == "second-unknown-source" and edge.get("targetFieldKey") for edge in unmapped["connections"]))

    async def test_hypit_input_lock_is_boolean_and_scoped_to_settings_materials(self):
        self._use_hypit_settings_canvas()
        material = await self.executor.execute(
            "hypit-settings",
            "create_node",
            {"kind": "material", "title": "固定输入", "text": "保留此素材"},
            "create-hypit-material",
        )
        locked = await self.executor.execute(
            "hypit-settings", "update_node", {"node_id": material["node_id"], "hypitInputLocked": True},
            "lock-hypit-input",
        )
        self.assertIs(locked["node"]["hypitInputLocked"], True)

        with self.assertRaises(ValueError):
            await self.executor.execute(
                "hypit-settings", "update_node", {"node_id": material["node_id"], "hypitInputLocked": "yes"},
                "reject-nonboolean-lock",
            )
        persisted = next(node for node in self.stored["nodes"] if node["id"] == material["node_id"])
        self.assertIs(persisted["hypitInputLocked"], True)

        self.stored = {"id": "canvas-1", "revision": 1, "nodes": [], "connections": [], "settings": {}}
        ordinary = await self.executor.execute(
            "canvas-1", "create_node", {"kind": "material", "title": "普通素材", "text": "内容"},
            "create-ordinary-material-for-lock",
        )
        with self.assertRaises(ValueError):
            await self.executor.execute(
                "canvas-1", "update_node", {"node_id": ordinary["node_id"], "hypitInputLocked": True},
                "reject-ordinary-input-lock",
            )

    async def test_create_update_connect_duplicate_branch_and_reopen(self):
        material = await self.executor.execute(
            "canvas-1",
            "create_node",
            {"kind": "material", "title": "正文.md", "text": "第一段"},
            "create-material",
        )
        text_node = await self.executor.execute(
            "canvas-1",
            "create_node",
            {
                "kind": "text",
                "title": "文本改写",
                "provider_id": "provider-a",
                "model": "text-1",
                "text": "请改写正文",
            },
            "create-text",
        )
        image_node = await self.executor.execute(
            "canvas-1",
            "create_node",
            {
                "kind": "image",
                "title": "封面图",
                "provider_id": "provider-a",
                "model": "image-1",
                "parameters": {"count": 1, "seed": 0},
            },
            "create-image",
        )

        self.assertEqual(material["node"]["displayNumber"], 1)
        self.assertEqual(text_node["node"]["displayNumber"], 2)
        self.assertEqual(image_node["node"]["displayNumber"], 3)
        self.assertEqual(self.stored["nextNodeNumber"], 4)
        self.assertEqual(self.stored["nodes"][1]["runSettings"]["textModel"], "text-1")
        self.assertEqual(self.stored["nodes"][2]["runSettings"]["capabilityParameters"]["image-1"]["seed"], 0)

        updated = await self.executor.execute(
            "canvas-1",
            "update_node",
            {
                "node_id": text_node["node_id"],
                "expected_revision": text_node["node"]["creationRevision"],
                "creation_details": "# 说明\n\n完整 Markdown。",
                "text": "请改写正文并保留事实",
                "parameters": {"temperature": 0},
            },
            "update-text",
        )
        self.assertEqual(updated["node"]["creationDetails"], "# 说明\n\n完整 Markdown。")
        self.assertEqual(updated["node"]["promptDraftText"], "请改写正文并保留事实")
        self.assertEqual(updated["node"]["runSettings"]["capabilityParameters"]["text-1"]["temperature"], 0)

        await self.executor.execute(
            "canvas-1",
            "connect",
            {"from": material["node_id"], "to": text_node["node_id"]},
            "connect-input",
        )
        source_after_connect = next(
            node for node in self.stored["nodes"] if node["id"] == text_node["node_id"]
        )
        duplicate = await self.executor.execute(
            "canvas-1",
            "duplicate_node",
            {"node_id": text_node["node_id"], "title": "分支文本"},
            "duplicate-text",
        )
        self.assertEqual(duplicate["node"]["creationId"], source_after_connect["creationId"])
        self.assertTrue(any(c["to"] == duplicate["node_id"] for c in self.stored["connections"]))

        branched = await self.executor.execute(
            "canvas-1",
            "update_node",
            {
                "node_id": duplicate["node_id"],
                "expected_revision": duplicate["node"]["creationRevision"],
                "text": "分支提示词",
            },
            "branch-text",
        )
        self.assertNotEqual(branched["node"]["creationId"], updated["node"]["creationId"])
        self.assertEqual(branched["node"]["creationParentId"], source_after_connect["creationId"])

        await self.executor.execute(
            "canvas-1",
            "connect",
            {"from": text_node["node_id"], "to": image_node["node_id"], "relation": "story"},
            "connect-story",
        )
        self.assertTrue(any(c.get("kind") == "story" for c in self.stored["connections"]))
        self.assertNotIn(text_node["node_id"], self.stored["nodes"][2].get("inputNodeIds", []))

        snapshot = await self.executor.execute("canvas-1", "snapshot", {}, "snapshot")
        self.assertEqual(snapshot["canvas"]["nextNodeNumber"], 5)
        reopened = await self.executor.execute("canvas-1", "snapshot", {}, "snapshot-reopen")
        self.assertEqual(
            [node["displayNumber"] for node in snapshot["canvas"]["nodes"]],
            [node["displayNumber"] for node in reopened["canvas"]["nodes"]],
        )
        self.assertGreaterEqual(len(self.saved), 1)
        self.assertGreaterEqual(len(self.notifications), 1)

    async def test_connection_checks_official_app_field_and_cycles(self):
        self.stored["nodes"] = [
            {
                "id": "source",
                "type": "smart-material",
                "title": "图像",
                "images": [{"kind": "image", "url": "/assets/source.png"}],
                "creationId": "creation-source",
                "creationOwnerNodeId": "source",
                "creationRevision": 1,
            },
            {
                "id": "app",
                "type": "smart-ai-app",
                "title": "应用",
                "runSettings": {
                    "rhFields": [
                        {"nodeId": "10", "fieldName": "image", "fieldType": "IMAGE"},
                    ]
                },
            },
            {
                "id": "target",
                "type": "smart-text-generator",
                "title": "文本",
                "runSettings": {"textProvider": "provider-a", "textModel": "text-1"},
            },
        ]
        with self.assertRaises(ValueError):
            await self.executor.execute(
                "canvas-1",
                "connect",
                {"from": "source", "to": "app", "target_field_key": "99::image"},
                "bad-field",
            )
        connected = await self.executor.execute(
            "canvas-1",
            "connect",
            {"from": "source", "to": "app", "target_field_key": "10::image"},
            "good-field",
        )
        self.assertEqual(connected["connections"][-1]["targetFieldKey"], "10::image")

        await self.executor.execute(
            "canvas-1",
            "connect",
            {"from": "app", "to": "target"},
            "cycle-a",
        )
        with self.assertRaises(ValueError):
            await self.executor.execute(
                "canvas-1",
                "connect",
                {"from": "target", "to": "app"},
                "cycle-b",
            )

    async def test_run_cancel_is_idempotent_and_uses_submit_contract(self):
        image = await self.executor.execute(
            "canvas-1",
            "create_node",
            {
                "kind": "image",
                "title": "需要运行",
                "provider_id": "provider-a",
                "model": "image-1",
            },
            "create-run-node",
        )
        first = await self.executor.execute("canvas-1", "run_node", {"node_id": image["node_id"]}, "run-once")
        replay = await self.executor.execute("canvas-1", "run_node", {"node_id": image["node_id"]}, "run-once")
        self.assertEqual(first, replay)
        self.assertEqual(len(self.submitted), 1)
        self.assertEqual(first["task_ids"], ["task-1"])

        cancelled = await self.executor.execute(
            "canvas-1",
            "cancel_run",
            {"node_id": image["node_id"], "task_id": "task-1"},
            "cancel-once",
        )
        self.assertEqual(cancelled["cancelled"], "task-1")
        self.assertEqual(self.cancelled, [(image["node_id"], "task-1")])

    async def test_production_registration_uses_story_edges_and_keeps_content_separate(self):
        script = await self.executor.execute(
            "canvas-1",
            "create_node",
            {"kind": "material", "title": "完整剧本.md", "text": "第一段\n第二段\n第三段"},
            "script",
        )
        segment = await self.executor.execute(
            "canvas-1",
            "create_node",
            {"kind": "material", "title": "第二段.md", "text": "第二段"},
            "segment",
        )
        image = await self.executor.execute(
            "canvas-1",
            "create_node",
            {
                "kind": "material",
                "title": "第二段图.png",
                "media": [{"kind": "image", "url": "/assets/segment.png"}],
            },
            "asset-image",
        )
        audio = await self.executor.execute(
            "canvas-1",
            "create_node",
            {
                "kind": "material",
                "title": "第二段音频.mp3",
                "media": [{"kind": "audio", "url": "/assets/segment.mp3"}],
            },
            "asset-audio",
        )

        registered = await self.executor.execute(
            "canvas-1",
            "update_node",
            {
                "node_id": segment["node_id"],
                "production": {
                    "role": "segment",
                    "order": 1,
                    "sourceNodeId": script["node_id"],
                    "imageNodeIds": [image["node_id"]],
                    "audioNodeIds": [audio["node_id"]],
                },
            },
            "register-segment",
        )
        self.assertEqual(registered["node"]["production"]["role"], "segment")
        self.assertNotIn("imageNodeIds", registered["node"]["production"])
        story = [connection for connection in self.stored["connections"] if connection["kind"] == "story"]
        self.assertEqual({connection["to"] for connection in story}, {image["node_id"], audio["node_id"]})

        status = await self.executor.execute("canvas-1", "production_status", {}, "production-status")
        self.assertEqual(status["rows"][0]["number"], 1)
        self.assertEqual(len(status["rows"][0]["images"]), 1)
        self.assertEqual(len(status["rows"][0]["audio"]), 1)
        self.assertEqual(status["rows"][0]["sourceStatus"], "current")

        group = await self.executor.execute(
            "canvas-1",
            "group_nodes",
            {"node_ids": [segment["node_id"], audio["node_id"]], "title": "第二段资产"},
            "group-assets",
        )
        arranged = await self.executor.execute(
            "canvas-1",
            "arrange",
            {"node_ids": [audio["node_id"]]},
            "arrange-group",
        )
        self.assertEqual(arranged["node_ids"], [group["node_id"]])

        disconnected = await self.executor.execute(
            "canvas-1",
            "disconnect",
            {"from": segment["node_id"], "to": image["node_id"], "relation": "story"},
            "disconnect-image",
        )
        self.assertEqual(disconnected["removed"], 1)
        deleted = await self.executor.execute(
            "canvas-1",
            "delete_node",
            {"node_id": image["node_id"]},
            "delete-image",
        )
        self.assertEqual(deleted["deleted"], image["node_id"])
        self.assertNotIn(image["node_id"], {node["id"] for node in self.stored["nodes"]})


class ServerExecutorRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_executor_runs_without_claim_or_open_canvas(self):
        lock = threading.RLock()
        stored = {
            "id": "canvas-1",
            "revision": 1,
            "nodes": [],
            "connections": [],
            "settings": {},
        }

        def load_canvas(canvas_id):
            with lock:
                return copy.deepcopy(stored)

        def save_canvas(canvas):
            nonlocal stored
            with lock:
                stored = copy.deepcopy(canvas)

        async def execute(canvas_id, action, args, request_id):
            return {"canvas_id": canvas_id, "action": action, "request_id": request_id, "args": args}

        app = FastAPI()
        app.include_router(create_agent_router(".", load_canvas, executor=execute))
        with TestClient(app) as client:
            self.assertFalse(client.get("/api/agent/capabilities").json()["requires_open_canvas"])
            submitted = client.post(
                "/api/agent/canvases/canvas-1/commands",
                json={"request_id": "server-1", "action": "snapshot", "args": {}},
            )
            self.assertEqual(submitted.status_code, 200)
            command = submitted.json()
            self.assertIn(command["status"], {"queued", "running", "succeeded"})
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                current = client.get(f"/api/agent/canvases/canvas-1/commands/{command['id']}").json()
                if current["status"] == "succeeded":
                    break
                time.sleep(0.01)
            self.assertEqual(current["status"], "succeeded")
            self.assertEqual(current["result"]["request_id"], "server-1")
            self.assertEqual(
                client.post("/api/agent/canvases/canvas-1/claim", json={"client_id": "browser"}).status_code,
                410,
            )
            replay = client.post(
                "/api/agent/canvases/canvas-1/commands",
                json={"request_id": "server-1", "action": "snapshot", "args": {}},
            ).json()
            self.assertEqual(replay["id"], command["id"])


if __name__ == "__main__":
    unittest.main()
