from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from fastapi import HTTPException
from canvas_core.hypit_config import HYPIT_SETTINGS_CANVAS_ID
from project_storage import ProjectStorage
from studio_execution import StudioExecution
from studio_hypit_flow import HypitFlowRunner


ROOT = Path(__file__).resolve().parents[1]
CACHE_TMP = ROOT / ".cache" / "tmp" / "execution-auth"


class FakeExecutionAuth:
    """In-memory account identities; token-shaped values never enter task storage."""

    def __init__(self):
        self.identity = "A"
        self.bindings: dict[str, str] = {}
        self.bind_calls: list[tuple[str, str, dict]] = []
        self.release_calls: list[str] = []
        self.fail_binding_id = ""
        self.fail_release = False
        self._scope = ContextVar("execution_auth_test_identity", default=None)
        self._private_tokens = {"A": "PRIVATE_TOKEN_A", "B": "PRIVATE_TOKEN_B"}

    def bind_execution_auth(self, binding_id: str, request: dict):
        binding_id = str(binding_id)
        self.bind_calls.append((binding_id, self.identity, copy.deepcopy(request)))
        if binding_id == self.fail_binding_id:
            raise RuntimeError("PRIVATE_TOKEN_A must never be exposed")
        self.bindings[binding_id] = self.identity

    def execution_auth_scope(self, binding_id: str):
        @contextmanager
        def scope():
            identity = self.bindings.get(str(binding_id))
            if identity is None:
                raise RuntimeError("execution identity is not bound")
            token = self._scope.set(identity)
            try:
                yield
            finally:
                self._scope.reset(token)

        return scope()

    def release_execution_auth(self, binding_id: str):
        binding_id = str(binding_id)
        self.release_calls.append(binding_id)
        if self.fail_release:
            raise RuntimeError("PRIVATE_TOKEN_A cleanup failure")
        self.bindings.pop(binding_id, None)

    def current_identity(self):
        return self._scope.get() or self.identity

    def in_execution_scope(self):
        return self._scope.get() is not None


class MemoryCanvasTasks:
    def __init__(self):
        self.tasks: dict[str, dict] = {}

    def get_canvas_task(self, key):
        return copy.deepcopy(self.tasks.get(str(key)))

    def create_canvas_task(self, task):
        self.tasks[str(task["id"])] = copy.deepcopy(task)

    def update_canvas_task(self, key, **changes):
        self.tasks[str(key)].update(copy.deepcopy(changes))


def _studio_canvas():
    return {
        "id": "auth-test-canvas",
        "nodes": [{
            "id": "image-node", "type": "smart-image-generator", "title": "图片",
            "promptDraftText": "old prompt",
            "runSettings": {"provider_id": "fixture", "model": "fixture-image"},
        }],
        "connections": [],
    }


def _flow_canvas(revision: int = 1):
    return {
        "id": HYPIT_SETTINGS_CANVAS_ID,
        "title": "隔离配置图",
        "kind": "smart",
        "project": "__hypit_settings__",
        "revision": revision,
        "created_at": 1,
        "updated_at": 1,
        "node_schema_version": 1,
        "hypit_flow_schema_version": 1,
        "hypit_legacy_migration_done": True,
        "nodes": [
            {"id": "prompt", "type": "smart-prompt", "text": ""},
            {"id": "step-a", "type": "smart-ai-app", "outputKind": "text",
             "runSettings": {"rhMode": "app", "rhConfigKey": "app:a", "rhAppId": "a",
                              "rhRegion": "global", "rhFields": []}},
            {"id": "step-b", "type": "smart-ai-app", "outputKind": "video",
             "runSettings": {"rhMode": "app", "rhConfigKey": "app:b", "rhAppId": "b",
                              "rhRegion": "global", "rhFields": []}},
            {"id": "output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image"},
        ],
        "connections": [
            {"from": "prompt", "to": "step-a", "kind": "input"},
            {"from": "step-a", "to": "step-b", "kind": "input"},
            {"from": "step-b", "to": "output", "kind": "input"},
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
    return needle in str(value)


class StudioExecutionAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.auth = FakeExecutionAuth()
        self.canvas = _studio_canvas()
        self.storage = MemoryCanvasTasks()
        self.old_started = asyncio.Event()
        self.finish_old = asyncio.Event()
        self.observations: list[tuple[str, str, str]] = []

        async def preflight(*_args):
            return {"run_id": "fixture-run"}

        async def generate(request):
            prompt = request["prompt"]
            self.observations.append((prompt, "generate", self.auth.current_identity()))
            if prompt == "old prompt":
                self.old_started.set()
                await self.finish_old.wait()
            return {"images": ["/api/results/isolated"]}

        async def collect(_result, request, _task):
            self.observations.append((request["prompt"], "collect", self.auth.current_identity()))
            return [{"kind": "image", "url": "/api/results/isolated"}]

        async def notify(_canvas):
            return None

        self.service = StudioExecution(
            load_canvas=lambda _canvas_id: copy.deepcopy(self.canvas),
            save_canvas=self._save,
            lock=threading.RLock(),
            storage=self.storage,
            preflight=preflight,
            generate=generate,
            collect=collect,
            notify=notify,
            bind_execution_auth=self.auth.bind_execution_auth,
            execution_auth_scope=self.auth.execution_auth_scope,
            release_execution_auth=self.auth.release_execution_auth,
        )

    def _save(self, canvas):
        self.canvas = copy.deepcopy(canvas)

    async def _wait_task(self, task_id):
        handle = self.service.handles.get(task_id)
        if handle:
            await asyncio.wait_for(asyncio.shield(handle), timeout=3)

    async def test_account_switch_does_not_rebind_or_change_inflight_task(self):
        first_node = self.canvas["nodes"][0]
        old = await self.service.submit(self.canvas, first_node, "old-op")
        old_id = old["task_ids"][0]
        await asyncio.wait_for(self.old_started.wait(), timeout=3)

        self.auth.identity = "B"
        duplicate = await self.service.submit(self.canvas, first_node, "old-op")
        self.assertEqual(duplicate["task_ids"], [old_id])
        self.assertEqual(len(self.auth.bind_calls), 1)

        self.canvas["nodes"][0]["promptDraftText"] = "new prompt"
        new = await self.service.submit(self.canvas, self.canvas["nodes"][0], "new-op")
        new_id = new["task_ids"][0]
        await self._wait_task(new_id)
        self.finish_old.set()
        await self._wait_task(old_id)

        self.assertEqual(
            self.observations,
            [
                ("old prompt", "generate", "A"),
                ("new prompt", "generate", "B"),
                ("new prompt", "collect", "B"),
                ("old prompt", "collect", "A"),
            ],
        )
        self.assertEqual([(item[0], item[1]) for item in self.auth.bind_calls], [(old_id, "A"), (new_id, "B")])
        self.assertEqual(set(self.auth.release_calls), {old_id, new_id})
        self.assertFalse(self.auth.bindings)
        self.assertFalse(any(_contains(task, "PRIVATE_TOKEN_") for task in self.storage.tasks.values()))

    async def test_binding_failure_rejects_before_task_creation(self):
        self.auth.fail_binding_id = "studio-invalid"
        node = self.canvas["nodes"][0]
        expected_id = "studio_" + hashlib.sha256(
            f"{self.canvas['id']}:{node['id']}:reject-op".encode()
        ).hexdigest()[:32]
        self.auth.fail_binding_id = expected_id
        with self.assertRaisesRegex(ValueError, "任务未提交") as caught:
            await self.service.submit(self.canvas, node, "reject-op")
        self.assertNotIn("PRIVATE_TOKEN", str(caught.exception))
        self.assertEqual(self.storage.tasks, {})
        self.assertFalse(self.service.handles)
        self.assertIn(expected_id, self.auth.release_calls)

    async def test_postcommit_storage_error_keeps_binding_for_persisted_task(self):
        original_create = self.storage.create_canvas_task

        def commit_then_raise(task):
            original_create(task)
            raise RuntimeError("fixture error after commit")

        self.storage.create_canvas_task = commit_then_raise
        node = self.canvas["nodes"][0]
        task_id = "studio_" + hashlib.sha256(
            f"{self.canvas['id']}:{node['id']}:postcommit-op".encode()
        ).hexdigest()[:32]
        with self.assertRaisesRegex(RuntimeError, "after commit"):
            await self.service.submit(self.canvas, node, "postcommit-op")
        self.assertEqual(self.storage.get_canvas_task(task_id)["status"], "queued")
        self.assertEqual(self.auth.bindings.get(task_id), "A")
        self.assertNotIn(task_id, self.auth.release_calls)
        self.assertFalse(self.service.handles)

    async def test_cancelled_task_releases_bound_identity(self):
        node = self.canvas["nodes"][0]
        submitted = await self.service.submit(self.canvas, node, "cancel-op")
        task_id = submitted["task_ids"][0]
        await asyncio.wait_for(self.old_started.wait(), timeout=3)
        result = await self.service.cancel(self.canvas, node, task_id)
        self.assertEqual(result["status"], "cancelled")
        self.assertNotIn(task_id, self.auth.bindings)
        self.assertIn(task_id, self.auth.release_calls)

    async def test_recoverable_task_retains_binding_and_cleanup_error_keeps_success(self):
        async def pending_generate(_request):
            return {"pending": True, "task_id": "provider-task"}

        self.service.generate = pending_generate
        node = self.canvas["nodes"][0]
        submitted = await self.service.submit(self.canvas, node, "pending-op")
        task_id = submitted["task_ids"][0]
        await self._wait_task(task_id)
        self.assertEqual(self.storage.get_canvas_task(task_id)["status"], "recoverable")
        self.assertIn(task_id, self.auth.bindings)
        self.assertNotIn(task_id, self.auth.release_calls)

        self.auth.fail_release = True
        self.service.generate = self._success_generate
        # A separate, terminal task proves release callback failure cannot rewrite success.
        self.canvas["nodes"][0]["promptDraftText"] = "terminal prompt"
        node = self.canvas["nodes"][0]
        terminal = await self.service.submit(self.canvas, node, "terminal-op")
        terminal_id = terminal["task_ids"][0]
        await self._wait_task(terminal_id)
        self.assertEqual(self.storage.get_canvas_task(terminal_id)["status"], "succeeded")
        self.assertNotIn("PRIVATE_TOKEN", self.storage.get_canvas_task(terminal_id).get("error", ""))

    async def _success_generate(self, _request):
        return {"images": ["/api/results/isolated"]}


class HypitFlowExecutionAuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        CACHE_TMP.mkdir(parents=True, exist_ok=True)
        self._temp = tempfile.TemporaryDirectory(prefix="flow-", dir=CACHE_TMP)
        self.storage_root = Path(self._temp.name)
        self.storage = ProjectStorage(self.storage_root)
        self.storage.ensure_layout()
        self.canvas = _flow_canvas()
        self.auth = FakeExecutionAuth()
        self.old_started = asyncio.Event()
        self.finish_old = asyncio.Event()
        self.observations: list[tuple[str, str, str, bool | None]] = []
        self._clock = 10

        async def prepare(canvas, node, _operation_id, upstream, payload, *, preflight):
            node_id = str(node["id"])
            prompt = str(payload.get("prompt") or "")
            self.observations.append((prompt, "prepare", self.auth.current_identity(), preflight))
            return {"node_id": node_id, "prompt": prompt, "upstream_results": copy.deepcopy(upstream)}

        async def preflight(_canvas, _node, request, _operation_id):
            self.observations.append((request["prompt"], "preflight", self.auth.current_identity(),
                                     self.auth.in_execution_scope()))
            return {"schema_fingerprint": "fixture"}

        async def execute(_canvas, _node, request, _operation_id, _resolved, on_submitted):
            prompt = request["prompt"]
            self.observations.append((prompt, "execute", self.auth.current_identity(), None))
            on_submitted({"provider_task_id": f"remote-{prompt}"})
            if prompt == "old" and request["node_id"] == "step-a":
                self.old_started.set()
                await self.finish_old.wait()
            return {"fixture_node_id": request["node_id"], "prompt": prompt}

        async def collect(result, request, task):
            prompt = request["prompt"]
            self.observations.append((prompt, "collect", self.auth.current_identity(), None))
            generated_dir = self.storage_root / "collector-fixtures"
            generated_dir.mkdir(parents=True, exist_ok=True)
            source = generated_dir / f"{task['title']}-{prompt}.png"
            source.write_bytes(b"isolated result")
            stored = self.storage.store_result_file(source, source.name)
            return [{"kind": "image", "url": stored["url"], "resultId": stored["id"]}]

        async def notify(*_args):
            return None

        self.runner = HypitFlowRunner(
            load_canvas=lambda _canvas_id: copy.deepcopy(self.canvas),
            storage=self.storage,
            prepare_node_request=prepare,
            preflight_node=preflight,
            execute_node=execute,
            collect_results=collect,
            notify=notify,
            lock=threading.RLock(),
            now_ms=self._now_ms,
            bind_execution_auth=self.auth.bind_execution_auth,
            execution_auth_scope=self.auth.execution_auth_scope,
            release_execution_auth=self.auth.release_execution_auth,
        )

    def tearDown(self):
        self._temp.cleanup()

    def _now_ms(self):
        self._clock += 1
        return self._clock

    async def _submit(self, operation_id: str, prompt: str):
        return await self.runner.submit(
            "image", "output", operation_id,
            {"base_revision": 1, "request": {"prompt": prompt, "parameters": {}}},
            test=True,
        )

    async def _wait_task(self, run_id: str):
        for _ in range(500):
            handle = self.runner._active.get(run_id)
            if handle is None or handle.done():
                return
            await asyncio.sleep(0)
        self.fail("flow task did not finish")

    async def test_account_switch_keeps_old_flow_identity_through_poll_and_collection(self):
        old = await self._submit("old-op", "old")
        old_id = old["run_id"]
        await asyncio.wait_for(self.old_started.wait(), timeout=3)

        self.auth.identity = "B"
        duplicate = await self._submit("old-op", "old")
        self.assertEqual(duplicate["run_id"], old_id)
        self.assertEqual(len(self.auth.bind_calls), 2)

        new = await self._submit("new-op", "new")
        new_id = new["run_id"]
        await self._wait_task(new_id)
        self.finish_old.set()
        await self._wait_task(old_id)

        runtime = [
            item for item in self.observations
            if (item[1] == "prepare" and item[3] is False)
            or (item[1] == "preflight" and item[3] is True)
            or item[1] in {"execute", "collect"}
        ]
        by_prompt = {prompt: [item for item in runtime if item[0] == prompt] for prompt in ("old", "new")}
        self.assertTrue(by_prompt["old"])
        self.assertTrue(by_prompt["new"])
        self.assertTrue(all(item[2] == "A" for item in by_prompt["old"]), by_prompt["old"])
        self.assertTrue(all(item[2] == "B" for item in by_prompt["new"]), by_prompt["new"])
        self.assertEqual(
            {(item[0], item[1]) for item in self.auth.bind_calls},
            {(f"{old_id}:step-a", "A"), (f"{old_id}:step-b", "A"),
             (f"{new_id}:step-a", "B"), (f"{new_id}:step-b", "B")},
        )
        self.assertEqual(set(self.auth.release_calls), {
            f"{old_id}:step-a", f"{old_id}:step-b", f"{new_id}:step-a", f"{new_id}:step-b",
        })
        self.assertFalse(self.auth.bindings)
        for task_id in (old_id, new_id):
            self.assertFalse(_contains(self.storage.get_canvas_task(task_id), "PRIVATE_TOKEN_"))

    async def test_binding_failure_rolls_back_attempted_bindings_without_canvas_task(self):
        self.auth.fail_binding_id = "pending-run:step-b"
        # The run ID is generated from the storage operation; fail on the second bind below.
        original_bind = self.auth.bind_execution_auth

        def fail_second(binding_id, request):
            if binding_id.endswith(":step-b"):
                self.auth.fail_binding_id = binding_id
            return original_bind(binding_id, request)

        self.runner.bind_execution_auth = fail_second
        with self.assertRaises(HTTPException) as caught:
            await self._submit("reject-op", "reject")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("PRIVATE_TOKEN", str(caught.exception.detail))
        index = json.loads(self.storage.canvas_task_index_path.read_text(encoding="utf-8"))
        self.assertEqual(index["items"], [])
        self.assertEqual(len(self.auth.release_calls), 2)
        self.assertFalse(self.auth.bindings)

    async def test_postcommit_storage_error_keeps_all_bindings_for_persisted_flow(self):
        original_create = self.storage.create_canvas_task

        def commit_then_raise(task):
            original_create(task)
            raise RuntimeError("fixture error after commit")

        self.storage.create_canvas_task = commit_then_raise
        with self.assertRaisesRegex(RuntimeError, "after commit"):
            await self._submit("postcommit-op", "hold")
        index = json.loads(self.storage.canvas_task_index_path.read_text(encoding="utf-8"))
        self.assertEqual(len(index["items"]), 1)
        run_id = index["items"][0]["id"]
        self.assertEqual(self.storage.get_canvas_task(run_id)["status"], "queued")
        self.assertEqual(set(self.auth.bindings), {f"{run_id}:step-a", f"{run_id}:step-b"})
        self.assertFalse(self.auth.release_calls)
        self.assertFalse(self.runner._active)

    async def test_cancelled_flow_releases_each_node_identity(self):
        submitted = await self._submit("cancel-op", "old")
        run_id = submitted["run_id"]
        await asyncio.wait_for(self.old_started.wait(), timeout=3)
        cancelling = await self.runner.cancel(run_id)
        self.assertEqual(cancelling["status"], "cancelling")
        await self._wait_task(run_id)
        self.assertEqual(self.storage.get_canvas_task(run_id)["status"], "cancelled")
        self.assertEqual(set(self.auth.release_calls), {f"{run_id}:step-a", f"{run_id}:step-b"})
        self.assertFalse(self.auth.bindings)

    async def test_recoverable_flow_keeps_binding_and_replay_does_not_rebind(self):
        async def pending_execute(_canvas, node, request, _operation_id, _resolved, on_submitted):
            on_submitted({"provider_task_id": "remote-pending"})
            if node["id"] == "step-a":
                return {"jimeng_pending": True, "submit_id": "remote-pending", "queue_info": {}}
            return {"fixture_node_id": node["id"], "prompt": request["prompt"]}

        self.runner.execute_node = pending_execute
        submitted = await self._submit("pending-op", "hold")
        run_id = submitted["run_id"]
        await self._wait_task(run_id)
        self.assertEqual(self.storage.get_canvas_task(run_id)["status"], "recoverable")
        self.assertEqual(len(self.auth.bindings), 2)
        self.assertFalse(self.auth.release_calls)
        repeated = await self._submit("pending-op", "hold")
        self.assertEqual(repeated["run_id"], run_id)
        self.assertEqual(len(self.auth.bind_calls), 2)


if __name__ == "__main__":
    unittest.main()
