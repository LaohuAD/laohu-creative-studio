from __future__ import annotations

import asyncio
import copy
import tempfile
import threading
import unittest
from pathlib import Path

from fastapi import HTTPException

from canvas_core.hypit_config import (
    ARTICLE_SETTINGS_CANVAS_ID,
    HYPIT_SETTINGS_CANVAS_ID,
    plan_hypit_slot,
    prepare_hypit_task_canvas,
    project_hypit_execution_statuses,
    validate_hypit_settings_canvas,
)
from project_storage import ProjectStorage
from studio_hypit_flow import HypitFlowRunner


ROOT = Path(__file__).resolve().parents[1]
CACHE_TMP = ROOT / "cache" / "studio-tests" / "tmp"


def _article_canvas(revision: int = 1) -> dict:
    return {
        "id": ARTICLE_SETTINGS_CANVAS_ID,
        "title": "文章创作配置",
        "kind": "smart",
        "revision": revision,
        "nodes": [
            {"id": "article-image", "type": "smart-image-generator", "promptDraftText": "默认提示", "runSettings": {"model": "fixture-image"}},
            {"id": "article-cover", "type": "smart-hypit-output", "hypitSlot": "image"},
        ],
        "connections": [
            {"from": "article-image", "to": "article-cover", "kind": "input"},
        ],
        "settings": {},
        "viewport": {"x": 0, "y": 0, "scale": 1},
        "logs": [],
    }


class SharedArticleGraphCoreTests(unittest.TestCase):
    def test_article_settings_uses_shared_validator_plan_and_private_task_projection(self):
        canvas = _article_canvas()
        self.assertTrue(validate_hypit_settings_canvas(
            canvas, canvas_id=ARTICLE_SETTINGS_CANVAS_ID, module_id="article",
        ))
        plan = plan_hypit_slot(canvas, "image", "article-cover", canvas_id=ARTICLE_SETTINGS_CANVAS_ID,
                               module_id="article")
        self.assertEqual(set(plan["node_ids"]), {"article-image", "article-cover"})
        prepared = prepare_hypit_task_canvas(
            canvas, "image", {"prompt": "文章封面"}, "article-cover",
            canvas_id=ARTICLE_SETTINGS_CANVAS_ID, module_id="article",
        )
        self.assertEqual(prepared["canvas"]["id"], ARTICLE_SETTINGS_CANVAS_ID)
        self.assertEqual(prepared["plan"]["recipe_fingerprint"], plan["recipe_fingerprint"])
        self.assertEqual(prepared["canvas"]["nodes"][0]["promptDraftText"], "文章封面")
        self.assertEqual(canvas["nodes"][0]["promptDraftText"], "默认提示")

    def test_identity_pair_is_checked_and_legacy_migration_remains_hypit_only(self):
        article = _article_canvas()
        with self.assertRaises(ValueError):
            validate_hypit_settings_canvas(article)
        with self.assertRaises(ValueError):
            validate_hypit_settings_canvas(article, canvas_id=ARTICLE_SETTINGS_CANVAS_ID, module_id="hypit")
        with self.assertRaises(ValueError):
            validate_hypit_settings_canvas({**article, "id": "unrelated"}, canvas_id="unrelated", module_id="article")
        with self.assertRaises(ValueError):
            from canvas_core.hypit_config import legacy_hypit_defaults_to_canvas
            legacy_hypit_defaults_to_canvas({}, canvas_id=ARTICLE_SETTINGS_CANVAS_ID)

    def test_direct_prompt_needs_a_unique_target_or_explicit_execution_node_id(self):
        canvas = _article_canvas()
        canvas["nodes"].insert(1, {
            "id": "article-preprocess", "type": "smart-image-generator",
            "runSettings": {"model": "fixture-preprocess"},
        })
        canvas["connections"] = [
            {"from": "article-image", "to": "article-preprocess", "kind": "input"},
            {"from": "article-preprocess", "to": "article-cover", "kind": "input"},
        ]
        with self.assertRaisesRegex(ValueError, "没有可接收提示词"):
            prepare_hypit_task_canvas(
                canvas, "image", {"prompt": "明确提示词"}, "article-cover",
                canvas_id=ARTICLE_SETTINGS_CANVAS_ID, module_id="article",
            )
        prepared = prepare_hypit_task_canvas(
            canvas, "image", {"prompt": "明确提示词", "prompt_target_node_id": "article-image"},
            "article-cover", canvas_id=ARTICLE_SETTINGS_CANVAS_ID, module_id="article",
        )
        private_node = next(node for node in prepared["canvas"]["nodes"] if node["id"] == "article-image")
        untouched_node = next(node for node in canvas["nodes"] if node["id"] == "article-image")
        self.assertEqual(private_node["promptDraftText"], "明确提示词")
        self.assertEqual(untouched_node["promptDraftText"], "默认提示")

    def test_test_status_projection_filters_by_real_article_canvas_identity(self):
        from canvas_core.hypit_config import project_hypit_test_statuses

        canvas = _article_canvas()
        fingerprint = plan_hypit_slot(
            canvas, "image", "article-cover", canvas_id=ARTICLE_SETTINGS_CANVAS_ID, module_id="article",
        )["recipe_fingerprint"]
        run = {
            "run_id": "article-test-run", "canvas_id": ARTICLE_SETTINGS_CANVAS_ID,
            "capability_snapshot": {
                "hypit_output_test": True, "hypit_slot": "image", "output_node_id": "article-cover",
                "recipe_fingerprint": fingerprint, "output_kind": "image",
            },
            "attempts": [{"status": "succeeded", "error": ""}],
        }
        passed = project_hypit_test_statuses(
            canvas, [run], canvas_id=ARTICLE_SETTINGS_CANVAS_ID, module_id="article",
        )
        self.assertTrue(passed["article-cover"]["test_passed"])
        foreign = project_hypit_test_statuses(
            canvas, [{**run, "canvas_id": HYPIT_SETTINGS_CANVAS_ID}],
            canvas_id=ARTICLE_SETTINGS_CANVAS_ID, module_id="article",
        )
        self.assertEqual(foreign, {})


class ArticleFlowRunnerIsolationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        CACHE_TMP.mkdir(parents=True, exist_ok=True)
        self._temp = tempfile.TemporaryDirectory(prefix="article-flow-runner-", dir=CACHE_TMP)
        self.storage_root = Path(self._temp.name)
        self.storage = ProjectStorage(self.storage_root)
        self.storage.ensure_layout()
        self.canvas = _article_canvas()
        self.execute_calls: list[str] = []
        self.published_contexts: list[dict] = []
        self.published_metadata: list[dict] = []
        self.notifications: list[tuple] = []
        self.lock = threading.RLock()
        self.execution_gate: asyncio.Event | None = None
        self.execution_started = asyncio.Event()
        self.clock = 100
        self.runner = self._make_runner()

    def tearDown(self):
        self._temp.cleanup()

    def _make_runner(self, *, canvas_id=ARTICLE_SETTINGS_CANVAS_ID, module_id="article"):
        async def prepare(canvas, node, operation_id, upstream, payload, *, preflight):
            return {
                "node_id": node["id"], "prompt": payload.get("prompt", ""),
                "upstream_results": copy.deepcopy(upstream), "preflight": preflight,
            }

        async def preflight(canvas, node, request, operation_id):
            return {"node_id": node["id"], "resolved_model": "fixture-image"}

        async def execute(canvas, node, request, operation_id, resolved, on_submitted):
            self.execute_calls.append(node["id"])
            self.execution_started.set()
            if self.execution_gate is not None:
                await self.execution_gate.wait()
            on_submitted({"provider_task_id": f"fake-{node['id']}"})
            return {"node_id": node["id"], "generated": True}

        async def collect(result, request, task):
            output = self.storage_root / "fixture-cover.png"
            output.write_bytes(b"isolated article cover fixture")
            managed = self.storage.store_result_file(output, output.name)
            return [{"kind": "image", "url": managed["url"], "resultId": managed["id"]}]

        async def notify(canvas_id, run_id, status):
            self.notifications.append((canvas_id, run_id, status))

        async def publish(snapshot, node, media, task):
            self.published_contexts.append(copy.deepcopy(task.get("trusted_context") or {}))
            stored_task = self.storage.get_canvas_task(task["run_id"])
            stored_run = self.storage.get_run(task["run_id"])
            self.published_metadata.append({
                "status": task.get("status"),
                "output_kind": task.get("output_kind"),
                "media": copy.deepcopy(task.get("media")),
                "stored_status": (stored_task or {}).get("status"),
                "stored_run_status": ((stored_run or {}).get("attempts") or [{}])[-1].get("status"),
            })

        return HypitFlowRunner(
            load_canvas=lambda requested_id: copy.deepcopy(self.canvas) if requested_id == canvas_id else None,
            storage=self.storage,
            prepare_node_request=prepare,
            preflight_node=preflight,
            execute_node=execute,
            collect_results=collect,
            notify=notify,
            lock=self.lock,
            now_ms=self._now_ms,
            publish_node_result=publish,
            canvas_id=canvas_id,
            module_id=module_id,
        )

    def _now_ms(self):
        self.clock += 1
        return self.clock

    async def _wait(self, runner, run_id):
        for _ in range(200):
            handle = runner._active.get(run_id)
            if handle is None or handle.done():
                return
            await asyncio.sleep(0)
        self.fail("article flow background task did not finish")

    async def test_article_task_is_persisted_under_real_graph_id_and_recovers_context(self):
        context = {
            "module_id": "article", "project_id": "article-123", "purpose": "cover",
            "slot": "image", "accepted_revision": 7, "source_hash": "a" * 64,
            "client_operation_id": "article-op-1",
        }
        submitted = await self.runner.submit(
            "image", "article-cover", "article-op-1", {"request": {"prompt": "封面"}},
            trusted_context=context,
        )
        await self._wait(self.runner, submitted["run_id"])

        run = self.storage.get_run(submitted["run_id"])
        task = self.storage.get_canvas_task(submitted["run_id"])
        self.assertEqual(run["canvas_id"], ARTICLE_SETTINGS_CANVAS_ID)
        self.assertEqual(task["canvas_id"], ARTICLE_SETTINGS_CANVAS_ID)
        self.assertEqual(task["status"], "succeeded")
        self.assertEqual(run["capability_snapshot"]["module_id"], "article")
        self.assertEqual(run["capability_snapshot"]["trusted_context"], context)
        self.assertEqual(task["private_snapshot"]["trusted_context"], context)
        self.assertEqual(self.storage.list_runs(canvas_id=HYPIT_SETTINGS_CANVAS_ID), [])
        self.assertEqual(len(self.storage.list_runs(canvas_id=ARTICLE_SETTINGS_CANVAS_ID)), 1)
        self.assertEqual(self.published_contexts, [context])
        self.assertEqual(self.published_metadata, [{
            "status": "succeeded", "output_kind": "image",
            "media": task["result"]["media"], "stored_status": "succeeded",
            "stored_run_status": "succeeded",
        }])

        restarted_runner = self._make_runner()
        status = restarted_runner.get(submitted["run_id"])
        self.assertEqual(status["status"], "succeeded")
        self.assertEqual(status["canvas_id"], ARTICLE_SETTINGS_CANVAS_ID)
        self.assertEqual(status["module_id"], "article")
        self.assertEqual(status["trusted_context"], context)
        self.assertEqual(status["media"][0]["kind"], "image")
        self.assertEqual(task["private_snapshot"]["canvas"]["id"], ARTICLE_SETTINGS_CANVAS_ID)
        self.assertNotIn("source_hash", run["standard_request"])
        self.assertNotIn("trusted_context", run["standard_request"])
        self.assertNotIn("api_key", task["private_snapshot"])

    async def test_operation_idempotence_is_scoped_to_canvas_module_and_context_is_server_owned(self):
        context = {
            "module_id": "article", "project_id": "article-123", "purpose": "cover",
            "slot": "image", "accepted_revision": 7, "source_hash": "b" * 64,
            "client_operation_id": "shared-op",
        }
        first = await self.runner.submit(
            "image", "article-cover", "shared-op",
            {"request": {"prompt": "封面"}, "trusted_context": {"project_id": "attacker"}},
            trusted_context=context,
        )
        await self._wait(self.runner, first["run_id"])
        duplicate = await self.runner.submit(
            "image", "article-cover", "shared-op", {"request": {"prompt": "封面"}},
            trusted_context=context,
        )
        self.assertEqual(duplicate["run_id"], first["run_id"])
        self.assertEqual(self.execute_calls, ["article-image"])
        with self.assertRaises(HTTPException) as changed_context:
            await self.runner.submit(
                "image", "article-cover", "shared-op", {"request": {"prompt": "封面"}},
                trusted_context={**context, "source_hash": "c" * 64},
            )
        self.assertEqual(changed_context.exception.status_code, 409)
        with self.assertRaises(HTTPException) as unsafe_context:
            await self.runner.submit(
                "image", "article-cover", "another-op", {"request": {"prompt": "封面"}},
                trusted_context={**context, "client_operation_id": "another-op", "api_key": "not-allowed"},
            )
        self.assertEqual(unsafe_context.exception.status_code, 400)

        hypit = _article_canvas()
        hypit["id"] = HYPIT_SETTINGS_CANVAS_ID
        hypit["nodes"] = [
            {"id": "hypit-image", "type": "smart-image-generator", "promptDraftText": "默认提示", "runSettings": {"model": "fixture-image"}},
            {"id": "hypit-output", "type": "smart-hypit-output", "hypitSlot": "image"},
        ]
        hypit["connections"] = [{"from": "hypit-image", "to": "hypit-output", "kind": "input"}]
        self.canvas = hypit
        hypit_runner = self._make_runner(canvas_id=HYPIT_SETTINGS_CANVAS_ID, module_id="hypit")
        other = await hypit_runner.submit(
            "image", "hypit-output", "shared-op", {"request": {"prompt": "封面"}},
        )
        await self._wait(hypit_runner, other["run_id"])
        self.assertNotEqual(other["run_id"], first["run_id"])
        self.assertEqual(self.storage.get_run(other["run_id"])["canvas_id"], HYPIT_SETTINGS_CANVAS_ID)
        self.assertEqual(len(self.storage.list_runs(canvas_id=ARTICLE_SETTINGS_CANVAS_ID)), 1)
        self.assertEqual(len(self.storage.list_runs(canvas_id=HYPIT_SETTINGS_CANVAS_ID)), 1)
        self.assertIsNone(hypit_runner.get(first["run_id"]))

    async def test_accepted_article_snapshot_finishes_after_graph_changes(self):
        self.execution_gate = asyncio.Event()
        context = {
            "module_id": "article", "project_id": "article-456", "purpose": "illustration",
            "slot": "image", "accepted_revision": 1, "source_hash": "d" * 64,
            "client_operation_id": "snapshot-op",
        }
        submitted = await self.runner.submit(
            "image", "article-cover", "snapshot-op", {"request": {"prompt": "原稿中的封面"}},
            trusted_context=context,
        )
        await asyncio.wait_for(self.execution_started.wait(), timeout=2)
        self.canvas = _article_canvas(revision=2)
        self.canvas["nodes"][0]["runSettings"]["model"] = "changed-after-acceptance"
        self.execution_gate.set()
        await self._wait(self.runner, submitted["run_id"])

        task = self.storage.get_canvas_task(submitted["run_id"])
        self.assertEqual(task["status"], "succeeded")
        accepted_generator = next(
            node for node in task["private_snapshot"]["canvas"]["nodes"]
            if node["id"] == "article-image"
        )
        self.assertEqual(accepted_generator["runSettings"]["model"], "fixture-image")
        self.assertEqual(task["private_snapshot"]["trusted_context"], context)
        self.assertFalse(self.runner.get(submitted["run_id"])["current_recipe_matches"])

    async def test_article_graph_validation_errors_use_article_wording(self):
        self.canvas["connections"] = []
        with self.assertRaises(HTTPException) as missing_edge:
            await self.runner.submit(
                "image", "article-cover", "missing-edge",
                {"request": {"prompt": "封面"}},
                trusted_context={
                    "module_id": "article", "project_id": "article-123", "purpose": "cover",
                    "slot": "image", "accepted_revision": 7, "source_hash": "e" * 64,
                    "client_operation_id": "missing-edge",
                },
            )
        detail = str(missing_edge.exception.detail)
        self.assertIn("文章生成", detail)
        self.assertNotIn("Hypit", detail)

    def test_status_projection_uses_actual_graph_id(self):
        canvas = _article_canvas()
        source = next(node for node in canvas["nodes"] if node["id"] == "article-image")
        source["creationTasks"] = [{"id": "article-run"}]
        task = {
            "id": "article-run", "canvas_id": ARTICLE_SETTINGS_CANVAS_ID,
            "node_id": "article-image", "hypit_source_node_id": "article-image",
            "hypit_source_recipe_fingerprint": "will-be-replaced", "hypit_supported_output_slots": ["image"],
            "status": "succeeded", "created_at": 10,
            "result": {"media": [{"kind": "image", "resultId": "managed-image"}]},
        }
        from canvas_core.hypit_config import hypit_execution_recipe_fingerprint
        task["hypit_source_recipe_fingerprint"] = hypit_execution_recipe_fingerprint(
            canvas, "article-image", canvas_id=ARTICLE_SETTINGS_CANVAS_ID, module_id="article",
        )
        result = project_hypit_execution_statuses(
            canvas,
            lambda run_id: task if run_id == "article-run" else None,
            lambda result_id: {"_managed_verified": True, "kind": "image"} if result_id == "managed-image" else None,
            canvas_id=ARTICLE_SETTINGS_CANVAS_ID,
            module_id="article",
        )
        self.assertTrue(result["article-cover"]["test_passed"])
