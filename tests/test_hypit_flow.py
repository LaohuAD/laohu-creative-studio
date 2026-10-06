from __future__ import annotations

import asyncio
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path

from fastapi import HTTPException

from canvas_core.hypit_config import HYPIT_SETTINGS_CANVAS_ID
from project_storage import ProjectStorage
from studio_hypit_flow import HypitFlowRunner


ROOT = Path(__file__).resolve().parents[1]
CACHE_TMP = ROOT / "cache" / "studio-tests" / "tmp"


def _canvas(revision: int = 1) -> dict:
    nodes = [
        {"id": "prompt-source", "type": "smart-prompt", "title": "提示词", "text": ""},
        {
            "id": "step-a", "type": "smart-ai-app", "title": "第一步",
            "outputKind": "text",
            "runSettings": {"rhMode": "app", "rhConfigKey": "app:fixture-a", "rhAppId": "fixture-a", "rhRegion": "global", "rhFields": []},
        },
        {
            "id": "step-b", "type": "smart-ai-app", "title": "第二步",
            "outputKind": "video",
            "runSettings": {"rhMode": "app", "rhConfigKey": "app:fixture-b", "rhAppId": "fixture-b", "rhRegion": "global", "rhFields": []},
        },
        {"id": "output-image", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image"},
    ]
    return {
        "id": HYPIT_SETTINGS_CANVAS_ID,
        "title": "Hypit 隔离配置图",
        "kind": "smart",
        "project": "__hypit_settings__",
        "revision": revision,
        "created_at": 1,
        "updated_at": 1,
        "node_schema_version": 1,
        "hypit_flow_schema_version": 1,
        "hypit_legacy_migration_done": True,
        "nodes": nodes,
        "connections": [
            {"from": "prompt-source", "to": "step-a", "kind": "input"},
            {"from": "step-a", "to": "step-b", "kind": "input"},
            {"from": "step-b", "to": "output-image", "kind": "input"},
        ],
        "viewport": {"x": 0, "y": 0, "scale": 1},
        "logs": [],
        "settings": {},
    }


def _contains(value, needle: str) -> bool:
    if isinstance(value, dict):
        return any(_contains(key, needle) or _contains(item, needle) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains(item, needle) for item in value)
    return needle.lower() in str(value).lower()


class HypitFlowRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        CACHE_TMP.mkdir(parents=True, exist_ok=True)
        self._temp = tempfile.TemporaryDirectory(prefix="hypit-flow-runner-", dir=CACHE_TMP)
        self.storage_root = Path(self._temp.name)
        self.storage = ProjectStorage(self.storage_root)
        self.storage.ensure_layout()
        self.canvas = _canvas()
        self.events: list[tuple] = []
        self.execute_calls: list[str] = []
        self.prepare_calls: list[tuple] = []
        self.request_payloads: list[tuple] = []
        self.result_ids_by_node: dict[str, str] = {}
        self.group_member_observations: list[tuple] = []
        self.notify_events: list[tuple] = []
        self.preflight_failure_node = ""
        self.pending_node = ""
        self.bad_output_node = ""
        self.change_canvas_during_execution = False
        self.publish_attempts = 0
        self.published = 0
        self.lock = threading.RLock()
        self._clock = 100

        async def prepare(canvas, node, operation_id, upstream, payload, *, preflight):
            node_id = str(node["id"])
            self.prepare_calls.append((node_id, bool(preflight), copy.deepcopy(upstream)))
            self.request_payloads.append((node_id, bool(preflight), copy.deepcopy(payload)))
            if node_id == "consumer-image":
                group = next(item for item in canvas["nodes"] if item.get("id") == "group-a")
                member_id = group["items"][0]["nodeId"]
                member = next(item for item in canvas["nodes"] if item.get("id") == member_id)
                self.group_member_observations.append((bool(preflight), copy.deepcopy(member.get("images") or [])))
            self.events.append(("prepare", node_id, bool(preflight)))
            return {
                "node_id": node_id,
                "upstream_results": copy.deepcopy(upstream),
                "prompt": str(payload.get("prompt") or ""),
                "parameters": copy.deepcopy(payload.get("parameters") or {}),
                "preflight": bool(preflight),
            }

        async def preflight(canvas, node, request, operation_id):
            node_id = str(node["id"])
            self.events.append(("preflight", node_id))
            if node_id == self.preflight_failure_node:
                raise ValueError("fixture input validation failure")
            return {
                "node_id": node_id,
                "schema_fingerprint": "fixture-fingerprint",
                "workflow_json": {"apiKey": "MUST_NOT_PERSIST_RAW_WORKFLOW_OR_CREDENTIALS"},
                "fields": [{"key": "password", "value": "MUST_NOT_PERSIST_FIELD_SECRET", "type": "text"}],
            }

        async def execute(canvas, node, request, operation_id, resolved, on_submitted):
            node_id = str(node["id"])
            self.execute_calls.append(node_id)
            self.events.append(("execute", node_id))
            on_submitted({"provider_task_id": f"remote-{node_id}"})
            if self.pending_node == node_id:
                return {"jimeng_pending": True, "submit_id": "remote-pending-001", "queue_info": {"queue_status": "pending"}}
            if self.change_canvas_during_execution and node_id == "step-a":
                self.canvas = {
                    **_canvas(revision=2),
                    "nodes": [],
                    "connections": [],
                }
            return {"fixture_node_id": node_id, "output": "fixture"}

        async def collect(result, request, task):
            node_id = str(result["fixture_node_id"])
            self.events.append(("collect", node_id))
            kind = "video" if node_id == self.bad_output_node else "image"
            extension = ".mp4" if kind == "video" else ".png"
            generated_dir = self.storage_root / "collector-fixtures"
            generated_dir.mkdir(parents=True, exist_ok=True)
            source = generated_dir / f"{node_id}{extension}"
            source.write_bytes((f"isolated managed result for {node_id}").encode("utf-8"))
            stored = self.storage.store_result_file(source, source.name)
            self.result_ids_by_node[node_id] = stored["id"]
            return [{
                "kind": kind,
                "url": stored["url"],
                "resultId": stored["id"],
                "name": stored["display_name"],
            }]

        async def notify(canvas_id, run_id, status):
            self.notify_events.append((canvas_id, run_id, status))

        async def publish(snapshot, node, media, task):
            self.publish_attempts += 1
            try:
                from canvas_core.hypit_config import plan_hypit_slot
                current = plan_hypit_slot(self.canvas, task["slot"], task["output_node_id"])
                if current["recipe_fingerprint"] == task["recipe_fingerprint"]:
                    self.published += 1
            except (KeyError, TypeError, ValueError):
                return

        self.runner = HypitFlowRunner(
            load_canvas=lambda canvas_id: copy.deepcopy(self.canvas),
            storage=self.storage,
            prepare_node_request=prepare,
            preflight_node=preflight,
            execute_node=execute,
            collect_results=collect,
            notify=notify,
            lock=self.lock,
            now_ms=self._now_ms,
            publish_node_result=publish,
        )

    def tearDown(self):
        self._temp.cleanup()

    def _now_ms(self):
        self._clock += 1
        return self._clock

    async def _wait_for_task(self, run_id: str):
        for _ in range(200):
            handle = self.runner._active.get(run_id)
            if handle is None or handle.done():
                return
            await asyncio.sleep(0)
        self.fail("runner background task did not finish")

    async def _submit(self, operation_id="op-1", payload=None):
        return await self.runner.submit(
            "image", "output-image", operation_id,
            payload if payload is not None else {"base_revision": 1, "request": {
                "prompt": "fixture prompt", "system_prompt": "fixture system instruction",
                "parameters": {"strength": 3},
            }},
            test=True,
        )

    def test_execution_dependencies_merge_group_member_edges_without_mutating_connections(self):
        nodes = {
            "member-image": {"id": "member-image", "type": "smart-image-generator"},
            "group-a": {"id": "group-a", "type": "smart-group", "items": ["member-image"]},
            "consumer-image": {"id": "consumer-image", "type": "smart-image-generator"},
        }
        original_connections = [{"from": "group-a", "to": "consumer-image", "kind": "input"}]
        plan = {
            "connections": copy.deepcopy(original_connections),
            "member_dependencies": [{"from": "member-image", "to": "group-a"}],
        }
        dependencies = self.runner._execution_dependencies(
            plan, nodes, [nodes["member-image"], nodes["consumer-image"]],
        )
        self.assertEqual(dependencies["member-image"], [])
        self.assertEqual(dependencies["consumer-image"], ["member-image"])
        self.assertEqual(plan["connections"], original_connections)

    async def test_group_member_generation_runs_once_and_flows_through_private_canvas(self):
        self.canvas = _canvas()
        self.canvas["nodes"] = [
            {"id": "prompt-source", "type": "smart-prompt", "text": ""},
            {"id": "member-image", "type": "smart-image-generator",
             "runSettings": {"provider_id": "fixture-provider", "model": "fixture-image"}, "images": []},
            {"id": "group-a", "type": "smart-group", "items": [{"nodeId": "member-image"}]},
            {"id": "consumer-image", "type": "smart-image-generator",
             "runSettings": {"provider_id": "fixture-provider", "model": "fixture-image"}, "images": []},
            {"id": "output-image", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image"},
            {"id": "unused-image", "type": "smart-image-generator",
             "runSettings": {"provider_id": "fixture-provider", "model": "unused"}, "images": []},
        ]
        self.canvas["connections"] = [
            {"from": "prompt-source", "to": "member-image", "kind": "input"},
            {"from": "group-a", "to": "consumer-image", "kind": "input"},
            {"from": "consumer-image", "to": "output-image", "kind": "input"},
        ]
        saved_connections = copy.deepcopy(self.canvas["connections"])
        saved_member_images = copy.deepcopy(self.canvas["nodes"][1]["images"])
        submitted = await self._submit(operation_id="group-flow")
        await self._wait_for_task(submitted["run_id"])

        self.assertEqual(self.runner.get(submitted["run_id"])["status"], "succeeded")
        self.assertEqual(self.execute_calls, ["member-image", "consumer-image"])
        member_preflight, member_runtime = self.group_member_observations
        self.assertEqual(member_preflight[0], True)
        self.assertEqual(member_preflight[1][0]["placeholder"], True)
        self.assertEqual(member_runtime[0], False)
        self.assertEqual(member_runtime[1][0]["resultId"], self.result_ids_by_node["member-image"])
        consumer_runtime = next(call for call in self.prepare_calls if call[0] == "consumer-image" and not call[1])
        self.assertEqual(consumer_runtime[2]["member-image"][0]["resultId"], self.result_ids_by_node["member-image"])
        self.assertEqual(self.canvas["connections"], saved_connections)
        self.assertEqual(self.canvas["nodes"][1]["images"], saved_member_images)

    async def test_full_chain_preflights_before_submission_and_uses_collected_upstream(self):
        submitted = await self._submit()
        self.assertEqual(submitted["status"], "queued")
        await self._wait_for_task(submitted["run_id"])
        first_execute = next(index for index, event in enumerate(self.events) if event[0] == "execute")
        self.assertEqual([event for event in self.events[:first_execute]
                          if event[0] == "prepare" and event[2] is True], [
            ("prepare", "step-a", True), ("prepare", "step-b", True),
        ])
        self.assertTrue(all(event[0] != "execute" for event in self.events[:first_execute]))
        preflight_for_b = next(item for item in self.prepare_calls if item[0] == "step-b" and item[1])
        self.assertEqual(preflight_for_b[2]["step-a"], {
            "kind": "dynamic", "upstream_node_id": "step-a", "placeholder": True,
        })
        actual_for_b = next(item for item in self.prepare_calls if item[0] == "step-b" and not item[1])
        self.assertEqual(actual_for_b[2]["step-a"][0]["resultId"], self.result_ids_by_node["step-a"])
        status = self.runner.get(submitted["run_id"])
        self.assertEqual(status["status"], "succeeded", status)
        self.assertEqual(status["output_kind"], "image")
        self.assertEqual(self.execute_calls, ["step-a", "step-b"])
        self.assertEqual(self.request_payloads[0][2]["system_prompt"], "fixture system instruction")
        self.assertTrue(all(item[2]["_hypit_requested_slot"] == "image" for item in self.request_payloads))
        self.assertTrue(all(item[2]["_hypit_output_node_id"] == "output-image" for item in self.request_payloads))
        final_result = self.storage.get_result(self.result_ids_by_node["step-b"])
        self.assertEqual(final_result["kind"], "image")
        self.assertTrue(self.storage.result_path(self.result_ids_by_node["step-b"]).is_file())
        self.assertEqual(status["media"][0]["url"], self.storage.result_url(self.result_ids_by_node["step-b"]))
        self.assertIn((HYPIT_SETTINGS_CANVAS_ID, submitted["run_id"], "succeeded"), self.notify_events)

        persisted = self.storage.get_canvas_task(submitted["run_id"])
        snapshot = persisted["private_snapshot"]
        self.assertTrue(_contains(snapshot, "fixture prompt"))
        self.assertTrue(_contains(snapshot, "fixture system instruction"))
        self.assertTrue(_contains(snapshot, "fixture-fingerprint"))
        self.assertFalse(_contains(snapshot, "MUST_NOT_PERSIST"), snapshot)
        self.assertFalse(_contains(snapshot, "workflow_json"), snapshot)
        self.assertNotIn("private_snapshot", status)

        reloaded_runner = HypitFlowRunner(
            load_canvas=lambda canvas_id: copy.deepcopy(self.canvas), storage=self.storage,
            prepare_node_request=self.runner.prepare_node_request, preflight_node=self.runner.preflight_node,
            execute_node=self.runner.execute_node, collect_results=self.runner.collect_results,
            notify=self.runner.notify, lock=self.lock, now_ms=self._now_ms,
        )
        self.assertEqual(reloaded_runner.get(submitted["run_id"])["status"], "succeeded")

    async def test_preflight_failure_creates_no_task_and_submits_no_provider(self):
        self.preflight_failure_node = "step-b"
        with self.assertRaises(HTTPException) as caught:
            await self._submit()
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(self.execute_calls, [])
        self.assertEqual(self.storage.list_runs(canvas_id=HYPIT_SETTINGS_CANVAS_ID), [])
        task_index = json.loads(self.storage.canvas_task_index_path.read_text(encoding="utf-8"))
        self.assertEqual(task_index["items"], [])

    async def test_provider_pending_preserves_remote_id_and_never_resubmits_or_runs_downstream(self):
        self.pending_node = "step-a"
        submitted = await self._submit()
        await self._wait_for_task(submitted["run_id"])
        status = self.runner.get(submitted["run_id"])
        self.assertEqual(status["status"], "recoverable")
        self.assertEqual(status["provider_task_id"], "remote-pending-001")
        self.assertEqual(self.execute_calls, ["step-a"])
        self.assertEqual(self.storage.get_canvas_task(submitted["run_id"])["status"], "recoverable")
        restarted_runner = HypitFlowRunner(
            load_canvas=lambda canvas_id: copy.deepcopy(self.canvas), storage=self.storage,
            prepare_node_request=self.runner.prepare_node_request, preflight_node=self.runner.preflight_node,
            execute_node=self.runner.execute_node, collect_results=self.runner.collect_results,
            notify=self.runner.notify, lock=self.lock, now_ms=self._now_ms,
        )
        self.assertEqual(restarted_runner.get(submitted["run_id"])["status"], "recoverable")
        repeated = await restarted_runner.submit("image", "output-image", "op-1", {
            "base_revision": 1, "request": {
                "prompt": "fixture prompt", "system_prompt": "fixture system instruction",
                "parameters": {"strength": 3},
            },
        }, test=True)
        self.assertEqual(repeated["run_id"], submitted["run_id"])
        self.assertEqual(repeated["status"], "recoverable")
        self.assertEqual(self.execute_calls, ["step-a"])
        with self.assertRaises(HTTPException) as wrong_slot:
            await self.runner.submit("video", "output-image", "op-1", {
                "base_revision": 1, "request": {"prompt": "fixture prompt", "parameters": {"strength": 3}},
            }, test=True)
        self.assertEqual(wrong_slot.exception.status_code, 409)

    async def test_final_output_mismatch_fails_and_duplicate_does_not_resubmit(self):
        self.bad_output_node = "step-b"
        submitted = await self._submit()
        await self._wait_for_task(submitted["run_id"])
        status = self.runner.get(submitted["run_id"])
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["error_category"], "output_mismatch")
        self.assertEqual(status["result_ids"], [
            self.result_ids_by_node["step-a"], self.result_ids_by_node["step-b"],
        ])
        self.assertEqual(self.storage.get_run(submitted["run_id"])["attempts"][-1]["status"], "failed")
        await self._submit()
        self.assertEqual(self.execute_calls, ["step-a", "step-b"])

    async def test_final_output_requires_body_or_accessible_managed_result(self):
        async def unregistered_collector(result, request, task):
            node_id = str(result["fixture_node_id"])
            return [{
                "kind": "image",
                "url": f"https://unmanaged.invalid/{node_id}.png",
                "resultId": f"missing-result-{node_id}",
            }]

        self.runner.collect_results = unregistered_collector
        submitted = await self._submit()
        await self._wait_for_task(submitted["run_id"])
        status = self.runner.get(submitted["run_id"])
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["error_category"], "output_unavailable")
        self.assertIn("可访问的受管结果", status["error"])
        self.assertEqual(self.storage.get_run(submitted["run_id"])["attempts"][-1]["status"], "failed")
        self.assertEqual(self.runner._usable_slot_result({"kind": "text", "text": "已收集的正文"})["text"], "已收集的正文")
        self.assertIsNone(self.runner._usable_slot_result({"kind": "text", "text": "  "}))

    async def test_accepted_snapshot_runs_to_completion_after_reset_without_republishing(self):
        self.change_canvas_during_execution = True
        submitted = await self._submit()
        await self._wait_for_task(submitted["run_id"])
        status = self.runner.get(submitted["run_id"])
        self.assertEqual(status["status"], "succeeded", status)
        self.assertFalse(status["current_recipe_matches"])
        self.assertEqual(self.execute_calls, ["step-a", "step-b"])
        self.assertEqual(self.publish_attempts, 1)
        self.assertEqual(self.published, 0)
        snapshot = self.storage.get_canvas_task(submitted["run_id"])["private_snapshot"]
        self.assertEqual(snapshot["canvas"]["revision"], 1)
        self.assertEqual([node["id"] for node in snapshot["canvas"]["nodes"]], ["prompt-source", "step-a", "step-b", "output-image"])

    async def test_unknown_provider_pending_still_stops_chain_without_retry(self):
        self.pending_node = "step-a"

        async def unknown_pending(canvas, node, request, operation_id, resolved, on_submitted):
            self.execute_calls.append(str(node["id"]))
            if node["id"] == "step-a":
                return {"status": "pending"}
            return {"fixture_node_id": str(node["id"])}

        self.runner.execute_node = unknown_pending
        submitted = await self._submit()
        await self._wait_for_task(submitted["run_id"])
        self.assertEqual(self.runner.get(submitted["run_id"])["status"], "recoverable")
        self.assertEqual(self.execute_calls, ["step-a"])
        await self._submit()
        self.assertEqual(self.execute_calls, ["step-a"])


if __name__ == "__main__":
    unittest.main()
