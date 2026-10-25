from __future__ import annotations

import copy
import asyncio
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

import main
from canvas_agent import create_agent_router
from canvas_core.headless_canvas import HeadlessCanvas, HeadlessCanvasError
from studio_manuscripts import SCRIPT_ARGS, StudioManuscriptStore, create_studio_manuscripts_router
from studio_projects import StudioProjectStore, create_studio_projects_router
from studio_script_import import StudioScriptImport


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_ROOT = PROJECT_ROOT / ".cache" / "validation" / "studio-script-import"


class CanvasAdapter:
    def list(self):
        return []

    def get(self, _project_id):
        return None

    def create(self, _name):
        raise AssertionError("script imports must target an existing canvas")

    def rename(self, *_args, **_kwargs):
        raise AssertionError("script import test does not rename canvases")

    def delete(self, *_args, **_kwargs):
        raise AssertionError("script import test does not delete canvases")


class CanvasStorage:
    def __init__(self):
        self.lock = threading.RLock()
        self.canvas = {"id": "canvas_script_test", "kind": "smart", "revision": 1,
                       "nodes": [], "connections": [], "settings": {}, "viewport": {"x": 0, "y": 0, "scale": 1}}
        self.saved = 0
        self.notifications = 0

    def load(self, canvas_id):
        if canvas_id != self.canvas["id"]:
            raise KeyError(canvas_id)
        with self.lock:
            return copy.deepcopy(self.canvas)

    def save(self, canvas):
        with self.lock:
            next_revision = int(self.canvas.get("revision") or 0) + 1
            self.canvas = copy.deepcopy(canvas)
            self.canvas["revision"] = next_revision
            canvas["revision"] = next_revision
            self.saved += 1

    async def notify(self, _canvas):
        self.notifications += 1


class StudioScriptImportTests(unittest.TestCase):
    def setUp(self):
        VALIDATION_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=VALIDATION_ROOT)
        self.root = Path(self.tmp.name)
        self.adapter = CanvasAdapter()
        self.projects = StudioProjectStore(self.root, self.adapter)
        self.manuscripts = StudioManuscriptStore(self.root, self.projects)
        self.storage = CanvasStorage()
        self.executor = self.new_executor(self.projects, self.manuscripts)
        self.script_project = self.projects.create("script", "Unicode source")
        self.script_id = self.script_project["id"]
        self.segment_ids = self.make_structured_script()

    def tearDown(self):
        self.tmp.cleanup()

    def new_executor(self, projects, manuscripts):
        canvas = HeadlessCanvas(self.storage.load, self.storage.save, self.storage.lock,
            submit_run=lambda *_args: (_ for _ in ()).throw(AssertionError("import must not run a model")),
            cancel_run=lambda *_args: None, validate_model=lambda *_args: {}, notify=self.storage.notify)
        canvas.script_import_handler = StudioScriptImport(manuscripts, canvas).execute
        return canvas

    def run_script_command(self, revision, request_id, action, args):
        payload = SCRIPT_ARGS[action].model_validate(args)
        from studio_manuscripts import ScriptCommand
        command = TypeAdapter(ScriptCommand).validate_python({"request_id": request_id, "expected_revision": revision,
                                                              "action": action, "args": payload.model_dump(exclude_unset=True)})
        return self.manuscripts.execute(self.script_id, "script", command)

    def make_structured_script(self):
        self.run_script_command(1, "draft", "set_draft", {"body_markdown": "😀甲\n\n乙丙"})
        receipt = self.run_script_command(2, "structure", "structure_draft", {"episodes": [
            {"client_ref": "ep", "title": "第 1 集", "scenes": [
                {"client_ref": "scene-a", "title": "第 1 场", "body_markdown": "😀甲\n\n乙丙", "start": 0, "end": 6,
                 "segments": [
                     {"client_ref": "seg-a", "title": "开场", "start": 0, "end": 2, "exact_text": "😀甲"},
                     {"client_ref": "seg-b", "title": "转折", "start": 4, "end": 6, "exact_text": "乙丙"},
                 ]},
            ]}
        ]})
        return [receipt["created_ids"]["seg-a"], receipt["created_ids"]["seg-b"]]

    def payload(self, *, request_id="import-one", source_revision=3, canvas_revision=1, mode="append", scope=None):
        return {"request_id": request_id, "action": "import_script_segments", "args": {
            "script_project_id": self.script_id, "source_revision": source_revision,
            "expected_canvas_revision": canvas_revision,
            "scope": scope or {"type": "segments", "ids": self.segment_ids}, "mode": mode}}

    def app_for(self, executor):
        app = FastAPI()
        app.include_router(create_agent_router(self.root, self.storage.load, executor=executor))
        return app

    def full_app_for(self, executor):
        app = FastAPI()
        app.include_router(create_studio_projects_router(self.root, self.adapter, store=self.projects))
        app.include_router(create_studio_manuscripts_router(self.manuscripts))
        app.include_router(create_agent_router(self.root, self.storage.load, executor=executor))
        return app

    def wait_command(self, client, command_id):
        for _ in range(100):
            response = client.get(f"/api/agent/canvases/{self.storage.canvas['id']}/commands/{command_id}")
            self.assertEqual(response.status_code, 200, response.text)
            command = response.json()
            if command["status"] in {"succeeded", "failed"}:
                return command
            time.sleep(0.01)
        self.fail("Agent import command did not reach a terminal state")

    def test_agent_import_is_atomic_unicode_precise_and_recovers_after_restart_and_source_delete(self):
        payload = self.payload()
        with TestClient(self.app_for(self.executor), client=("127.0.0.1", 42000)) as client:
            accepted = client.post(f"/api/agent/canvases/{self.storage.canvas['id']}/commands", json=payload)
            self.assertEqual(accepted.status_code, 200, accepted.text)
            command = self.wait_command(client, accepted.json()["id"])
            self.assertEqual(command["status"], "succeeded", command)
            receipt = command["result"]

        self.assertEqual(receipt["added_count"], 3)  # one complete episode source + two segments
        self.assertEqual(receipt["skipped_count"], 0)
        self.assertEqual(self.storage.saved, 1)
        canvas = self.storage.load(self.storage.canvas["id"])
        scripts = [node for node in canvas["nodes"] if (node.get("production") or {}).get("role") == "script"]
        segments = [node for node in canvas["nodes"] if (node.get("production") or {}).get("role") == "segment"]
        self.assertEqual(len(scripts), 1)
        self.assertEqual(len(segments), 2)
        source_text = scripts[0]["images"][0]["text"]
        self.assertEqual(source_text, "😀甲\n\n乙丙")
        self.assertEqual([(node["production"]["sourceStart"], node["production"]["sourceEnd"]) for node in segments], [(0, 2), (4, 6)])
        for node in segments:
            production = node["production"]
            start, end = production["sourceStart"], production["sourceEnd"]
            self.assertEqual(source_text[start:end], node["images"][0]["text"])
            self.assertEqual(node["sourceRef"]["module"], "script")
        self.assertEqual(len([edge for edge in canvas["connections"] if edge.get("kind") == "story"]), 2)
        self.assertEqual(len(self.executor._production_rows(canvas)), 2)
        self.assertEqual(canvas["revision"], receipt["canvas_revision"])

        # Simulate the canvas transaction committing but the Agent mailbox not
        # storing its result, then restart the executor and recycle the source.
        mailbox_path = self.root / "data" / "agent_commands" / f"{self.storage.canvas['id']}.json"
        commands = json.loads(mailbox_path.read_text(encoding="utf-8"))
        commands[0]["status"] = "running"
        commands[0].pop("result", None)
        commands[0].pop("completed_at", None)
        mailbox_path.write_text(json.dumps(commands, ensure_ascii=False), encoding="utf-8")
        self.projects.delete(self.script_id, "script", expected_revision=3)
        restarted_projects = StudioProjectStore(self.root, self.adapter)
        restarted_manuscripts = StudioManuscriptStore(self.root, restarted_projects)
        restarted_executor = self.new_executor(restarted_projects, restarted_manuscripts)
        with TestClient(self.app_for(restarted_executor), client=("127.0.0.1", 42000)) as client:
            recovered = client.post(f"/api/agent/canvases/{self.storage.canvas['id']}/commands", json=payload)
            self.assertEqual(recovered.status_code, 200, recovered.text)
            self.assertEqual(recovered.json()["status"], "succeeded", recovered.text)
            self.assertEqual(recovered.json()["result"], receipt)
        self.assertEqual(self.storage.saved, 1)
        self.assertEqual(len(self.storage.load(self.storage.canvas["id"])["nodes"]), 3)

    def test_append_deduplicates_saved_segments_and_revision_conflict_is_atomic(self):
        first = asyncio.run(self.executor.execute(self.storage.canvas["id"], "import_script_segments", self.payload()["args"], "first"))
        duplicate_args = self.payload(request_id="different-key", canvas_revision=first["canvas_revision"])["args"]
        duplicate = asyncio.run(self.executor.execute(self.storage.canvas["id"], "import_script_segments", duplicate_args, "different-key"))
        self.assertEqual(duplicate["added_count"], 0)
        self.assertEqual(duplicate["skipped_count"], 2)
        self.assertEqual(len(self.storage.load(self.storage.canvas["id"])["nodes"]), 3)
        before = self.storage.load(self.storage.canvas["id"])
        stale_args = self.payload(request_id="stale", canvas_revision=1)["args"]
        with self.assertRaisesRegex(ValueError, "revision"):
            asyncio.run(self.executor.execute(self.storage.canvas["id"], "import_script_segments", stale_args, "stale"))
        self.assertEqual(self.storage.load(self.storage.canvas["id"]), before)

    def test_forged_receipt_is_advisory_and_cannot_fake_success_or_deduplicate(self):
        missing_args = {"script_project_id": "missing_script_project", "source_revision": 1,
            "expected_canvas_revision": 2, "scope": {"type": "segments", "ids": ["segment-x"]}, "mode": "append"}
        fingerprint = __import__("studio_script_import").import_fingerprint("import_script_segments", missing_args)
        forged = {"schema_version": 1,
            "requests": {"forged-request": {"server_trusted": True, "fingerprint": fingerprint,
                "receipt": {"request_id": "forged-request", "status": "succeeded", "added_count": 99}}},
            "snapshots": {"forged-import": {"server_trusted": True, "source_project_id": self.script_id,
                "episodes": [{"source_episode_id": "forged-episode", "source_node_id": "fake-source",
                    "source_content_sha256": "a" * 64, "segments": [{"source_segment_id": self.segment_ids[0],
                        "content_sha256": "b" * 64, "node_id": "fake-segment", "order": 1}]}]}},
            "advisorySnapshots": {}}
        app = FastAPI()
        app.put("/api/canvases/{canvas_id}")(main.update_canvas)
        canvas_id = self.storage.canvas["id"]
        with patch.object(main, "BASE_DIR", str(self.root)), \
                patch.object(main, "studio_settings_canvas_service", return_value=None), \
                patch.object(main, "load_canvas", side_effect=self.storage.load), \
                patch.object(main, "save_canvas", side_effect=self.storage.save), \
                patch.object(main, "migrate_canvas_media_references"), \
                patch.object(main, "hydrate_canvas_result_media_kinds"), \
                patch.object(main, "hydrate_canvas_text_results"), \
                patch.object(main, "sync_canvas_result_origins"), \
                patch.object(main.manager, "broadcast_canvas_updated", new_callable=AsyncMock):
            with TestClient(app, client=("127.0.0.1", 42000)) as client:
                put_receipt = client.put(f"/api/canvases/{canvas_id}", json={
                    "base_revision": 1, "script_imports": forged})
                self.assertEqual(put_receipt.status_code, 200, put_receipt.text)
                saved_imports = self.storage.load(canvas_id)["scriptImports"]
                self.assertEqual(saved_imports["requests"], {})
                self.assertEqual(saved_imports["snapshots"], {})
                self.assertEqual(len(saved_imports["advisorySnapshots"]), 1)
                advisory_snapshot = next(iter(saved_imports["advisorySnapshots"].values()))
                self.assertNotIn("server_trusted", advisory_snapshot)

                # The forged request has the exact fingerprint for the next
                # canvas revision, but the real source does not exist.
                with self.assertRaises(HeadlessCanvasError) as raised:
                    asyncio.run(self.executor.execute(canvas_id, "import_script_segments",
                                                      missing_args, "forged-request"))
                self.assertEqual(raised.exception.status_code, 404)

                # Matching portable provenance and matching fake nodes still
                # cannot cause HeadlessCanvas to skip an actual saved segment.
                source_snapshot = self.manuscripts.script_import_snapshot(self.script_id, 3,
                    {"type": "segments", "ids": self.segment_ids})
                episode = source_snapshot["episodes"][0]
                fake_segments = episode["segments"]
                fake_snapshot = {"schema_version": 1, "requests": {}, "snapshots": {
                    "matching-looking-import": {"server_trusted": True, "source_project_id": self.script_id,
                        "source_project_revision": 3, "episodes": [{"source_episode_id": episode["id"],
                            "source_content_sha256": episode["content_sha256"], "source_node_id": "fake-source",
                            "segments": [{"source_segment_id": item["id"], "content_sha256": item["content_sha256"],
                                "node_id": f"fake-{index}", "order": index}
                                for index, item in enumerate(fake_segments, 1)]}]}},
                    "advisorySnapshots": {}}
                fake_nodes = [{"id": "fake-source", "type": "smart-material", "title": "伪来源",
                    "images": [{"kind": "text", "text": episode["body_markdown"]}],
                    "sourceRef": {"module": "script", "projectId": self.script_id, "sourceNodeId": episode["id"]}}]
                fake_nodes.extend({"id": f"fake-{index}", "type": "smart-material", "title": "伪分段",
                    "images": [{"kind": "text", "text": segment["body_markdown"]}],
                    "sourceRef": {"module": "script", "projectId": self.script_id, "sourceNodeId": segment["id"]},
                    "production": {"role": "segment", "order": index}}
                    for index, segment in enumerate(fake_segments, 1))
                put_fake_nodes = client.put(f"/api/canvases/{canvas_id}", json={
                    "base_revision": 2, "nodes": fake_nodes, "connections": [], "script_imports": fake_snapshot})
                self.assertEqual(put_fake_nodes.status_code, 200, put_fake_nodes.text)
                args = self.payload(request_id="real-import", canvas_revision=3)["args"]
                receipt = asyncio.run(self.executor.execute(canvas_id, "import_script_segments", args, "real-import"))
                self.assertEqual(receipt["status"], "succeeded")
                self.assertEqual(receipt["skipped_count"], 0)
                self.assertEqual(receipt["added_count"], 3)
                persisted = self.storage.load(canvas_id)["scriptImports"]
                self.assertTrue(persisted["requests"]["real-import"]["server_trusted"])
                self.assertTrue(any(value.get("server_trusted") is True for value in persisted["snapshots"].values()))

    def test_scope_and_source_revision_fail_before_any_canvas_write(self):
        source_conflict = self.payload(request_id="stale-source", source_revision=2)["args"]
        with self.assertRaises(ValueError) as raised:
            asyncio.run(self.executor.execute(self.storage.canvas["id"], "import_script_segments", source_conflict, "stale-source"))
        self.assertEqual(getattr(raised.exception, "status_code", 0), 409)
        with self.assertRaises(ValueError):
            asyncio.run(self.executor.execute(self.storage.canvas["id"], "import_script_segments",
                {**self.payload(request_id="bad-scope")["args"], "production": {"role": "segment"}}, "bad-scope"))
        self.assertEqual(self.storage.saved, 0)
        self.assertEqual(self.storage.load(self.storage.canvas["id"])["nodes"], [])

    def test_empty_script_segment_is_preserved_in_store_but_canvas_import_returns_actionable_conflict(self):
        summary = self.manuscripts.script_summary(self.script_id)
        episode_id = summary["directory"]["episodes"][0]["id"]
        created = self.run_script_command(3, "create-empty-scene", "create_scene", {
            "episode_id": episode_id, "title": "空场", "body_markdown": "", "client_ref": "empty-scene"})
        scene_id = created["created_ids"]["empty-scene"]
        empty_id = self.manuscripts.script_scene(self.script_id, scene_id)["scene"]["segments"][0]["id"]
        self.assertEqual(self.manuscripts.script_scene(self.script_id, scene_id)["scene"]["segments"][-1]["body_markdown"], "")
        nonempty_snapshot = self.manuscripts.script_import_snapshot(self.script_id, 4,
            {"type": "segments", "ids": [self.segment_ids[0]]})
        self.assertEqual(nonempty_snapshot["segment_count"], 1)
        args = self.payload(request_id="reject-empty", source_revision=4,
                            scope={"type": "segments", "ids": [empty_id]})["args"]
        with self.assertRaises(HeadlessCanvasError) as raised:
            asyncio.run(self.executor.execute(self.storage.canvas["id"], "import_script_segments", args, "reject-empty"))
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "EMPTY_SCRIPT_SEGMENT")
        self.assertIn("先补充正文，再导入画布", raised.exception.detail["message"])
        self.assertEqual(self.storage.saved, 0)
        self.assertEqual(self.storage.load(self.storage.canvas["id"])["nodes"], [])

    def test_http_markdown_view_edit_canvas_import_and_export_round_trip(self):
        source_markdown = "# E1 ###\n## S1 ##\n甲😀\n---\n乙"
        edited_scene_body = "甲😀\n---\n乙\n"
        with TestClient(self.full_app_for(self.executor), client=("127.0.0.1", 42000)) as client:
            created_project = client.post("/api/studio/projects", json={"module": "script", "name": "HTTP integration"})
            self.assertEqual(created_project.status_code, 200, created_project.text)
            project_id = created_project.json()["project"]["id"]

            imported = client.post(f"/api/studio/scripts/{project_id}/commands", json={
                "request_id": "http-import-markdown", "expected_revision": 1,
                "action": "import_markdown", "args": {"body_markdown": source_markdown, "replace": False},
            })
            self.assertEqual(imported.status_code, 200, imported.text)
            self.assertEqual(imported.json()["revision"], 2)
            self.assertTrue(imported.json()["source_sha256"])
            raw_history = client.get(
                f"/api/studio/scripts/{project_id}/markdown/history/{imported.json()['source_sha256']}")
            self.assertEqual(raw_history.status_code, 200, raw_history.text)
            self.assertEqual(raw_history.json()["body_markdown"], source_markdown)

            summary = client.get(f"/api/studio/scripts/{project_id}")
            self.assertEqual(summary.status_code, 200, summary.text)
            episode = summary.json()["directory"]["episodes"][0]
            scene = episode["scenes"][0]
            self.assertEqual(episode["title"], "E1")
            self.assertEqual(scene["title"], "S1")
            view = client.get(f"/api/studio/scripts/{project_id}/view", params={
                "scope": "scene", "node_id": scene["id"],
            })
            self.assertEqual(view.status_code, 200, view.text)
            self.assertEqual(view.json()["blocks"][0]["editable_markdown"], "甲😀\n---\n乙")

            updated = client.post(f"/api/studio/scripts/{project_id}/commands", json={
                "request_id": "http-update-scene", "expected_revision": 2,
                "action": "update_scene", "args": {"scene_id": scene["id"], "body_markdown": edited_scene_body},
            })
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertEqual(updated.json()["revision"], 3)

            current_view = client.get(f"/api/studio/scripts/{project_id}/view", params={
                "scope": "scene", "node_id": scene["id"],
            })
            self.assertEqual(current_view.status_code, 200, current_view.text)
            self.assertEqual(current_view.json()["blocks"][0]["editable_markdown"], edited_scene_body)
            segment_ids = [item["id"] for item in current_view.json()["blocks"][0]["segments"]]
            self.assertEqual(len(segment_ids), 2)

            command_response = client.post(f"/api/agent/canvases/{self.storage.canvas['id']}/commands", json={
                "request_id": "http-canvas-import", "action": "import_script_segments", "args": {
                    "script_project_id": project_id, "source_revision": 3,
                    "expected_canvas_revision": 1,
                    "scope": {"type": "segments", "ids": segment_ids}, "mode": "append",
                },
            })
            self.assertEqual(command_response.status_code, 200, command_response.text)
            command = command_response.json()
            if command["status"] not in {"succeeded", "failed"}:
                command = self.wait_command(client, command["id"])
            self.assertEqual(command["status"], "succeeded", command)
            self.assertEqual(command["result"]["added_count"], 3)
            imported_canvas = self.storage.load(self.storage.canvas["id"])
            imported_segments = [node for node in imported_canvas["nodes"]
                if (node.get("production") or {}).get("role") == "segment"]
            self.assertEqual(len(imported_segments), 2)
            self.assertEqual([node["images"][0]["text"] for node in imported_segments], ["甲😀", "乙\n"])
            production_rows = self.executor._production_rows(imported_canvas)
            self.assertEqual(len(production_rows), 2)
            self.assertEqual([row["sourceStatus"] for row in production_rows], ["current", "current"])

            exported = client.get(f"/api/studio/scripts/{project_id}/markdown")
            self.assertEqual(exported.status_code, 200, exported.text)
            self.assertEqual(exported.json()["body_markdown"], "# E1\n## S1\n" + edited_scene_body)
            self.assertEqual(exported.json()["revision"], 3)


if __name__ == "__main__":
    unittest.main()
