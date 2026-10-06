"""文章生成绑定与关联恢复使用隔离项目、任务和素材目录。"""
from __future__ import annotations

import asyncio
import copy
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from canvas_core.hypit_config import ARTICLE_SETTINGS_CANVAS_ID
from project_storage import ProjectStorage
from studio_articles import StudioArticleStore, create_studio_articles_router
from studio_article_generation import StudioArticleGenerationBridge
from studio_hypit_flow import HypitFlowRunner
from studio_projects import StudioProjectStore, create_studio_projects_router

from tests.test_studio_articles import (
    FakeCanvasAdapter,
    TEST_TMP_ROOT,
    catalog_fixture,
    fake_media_reference,
    find_shared_media_by_hash,
)


class StudioArticleGenerationTests(unittest.TestCase):
    def test_failed_publish_association_is_persisted_and_get_retries_without_resubmit(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            root = Path(temporary)
            project_store = StudioProjectStore(root, FakeCanvasAdapter())
            article_project = project_store.create("article", "关联恢复测试")
            storage = ProjectStorage(root)
            storage.ensure_layout()
            article_store = StudioArticleStore(
                root,
                project_store,
                catalog_fixture(root / "static" / "article-templates" / "catalog.json"),
                resolve_media_reference=fake_media_reference,
                register_managed_result=storage.register_managed_result,
                find_shared_media_by_hash=lambda digest, kind: find_shared_media_by_hash(storage, digest, kind),
            )
            article = article_store.get(article_project["id"])

            class SettingsService:
                def ensure_canvas(self):
                    return {"id": "article-settings", "revision": 3, "nodes": [], "connections": []}

            class Runner:
                def __init__(self):
                    self.submit_calls = []
                    self.flow = None

                async def submit(self, slot, output_node_id, request_id, payload, test=False, *, trusted_context=None):
                    self.submit_calls.append((slot, output_node_id, request_id, copy.deepcopy(payload), test))
                    self.flow = {
                        "run_id": "article-flow-run-1",
                        "canvas_id": "article-settings",
                        "module_id": "article",
                        "status": "queued",
                        "slot": slot,
                        "output_node_id": output_node_id,
                        "output_kind": "",
                        "media": [],
                        "trusted_context": copy.deepcopy(dict(trusted_context or {})),
                    }
                    storage.create_canvas_task({
                        "id": "article-flow-run-1", "canvas_id": "article-settings",
                        "module_id": "article", "node_id": output_node_id,
                        "kind": "hypit_settings_flow", "status": "queued", "result": {},
                    })
                    return {"run_id": "article-flow-run-1", "status": "queued", "slot": slot}

                def get(self, run_id):
                    return copy.deepcopy(self.flow) if self.flow and self.flow["run_id"] == run_id else None

            runner = Runner()
            bridge = StudioArticleGenerationBridge(
                article_store=article_store,
                runner=runner,
                storage=storage,
                settings_service=SettingsService(),
            )
            payload = {
                "slot": "image", "purpose": "cover", "output_node_id": "cover-output",
                "client_operation_id": "article-op-1", "request": {"prompt": "安全测试"},
            }
            accepted = {"accepted_revision": article["revision"], "source_hash": article["source_sha256"]}
            submitted = asyncio.run(bridge.submit(article_project["id"], payload, accepted))
            self.assertEqual(submitted["run_id"], "article-flow-run-1")
            self.assertEqual(len(runner.submit_calls), 1)
            self.assertEqual(runner.submit_calls[0][3]["base_revision"], 3)

            original_associate = article_store.associate_generation_media
            calls = []

            def fail_once(*args, **kwargs):
                calls.append((args, kwargs))
                if len(calls) == 1:
                    raise RuntimeError("隔离测试模拟文章索引暂时不可写")
                return original_associate(*args, **kwargs)

            article_store.associate_generation_media = fail_once
            media = [{"kind": "image", "resultId": "res_cover", "url": "/api/results/res_cover"}]
            runner.flow.update(status="succeeded", output_kind="image", media=copy.deepcopy(media))
            task = storage.get_canvas_task("article-flow-run-1")
            storage.update_canvas_task(
                "article-flow-run-1",
                status="succeeded",
                result={"status": "succeeded", "output_kind": "image", "media": media},
            )
            callback_meta = {
                "run_id": "article-flow-run-1", "canvas_id": "article-settings", "module_id": "article",
                "slot": "image", "output_node_id": "cover-output", "recipe_fingerprint": "fixture",
                "status": "succeeded", "output_kind": "image", "media": media,
                "trusted_context": copy.deepcopy(runner.flow["trusted_context"]),
            }
            asyncio.run(bridge.publish_node_result({}, {"id": "image-node", "type": "smart-image-generator"}, media, callback_meta))
            failed_task = storage.get_canvas_task("article-flow-run-1")
            self.assertEqual(failed_task["status"], "succeeded")
            self.assertEqual(failed_task["result"]["article_association_error"]["code"], "article_association_failed")
            self.assertEqual(len(runner.submit_calls), 1)

            recovered = asyncio.run(bridge.get(article_project["id"], "article-flow-run-1"))
            self.assertEqual(recovered["status"], "succeeded")
            self.assertIsNone(recovered["article_association_error"])
            self.assertEqual(len(runner.submit_calls), 1)
            self.assertEqual(len(calls), 2)
            updated_article = article_store.get(article_project["id"])
            self.assertEqual(len(updated_article["media_refs"]), 1)
            self.assertEqual(len(updated_article["cover_variants"]), 1)
            cleared_task = storage.get_canvas_task("article-flow-run-1")
            self.assertNotIn("article_association_error", cleared_task["result"])

    def test_real_runner_article_store_and_project_storage_complete_route_association(self):
        """真实 runner、文章存储与托管结果存储共同完成提交、收集、关联和幂等重放。"""
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            root = Path(temporary)
            project_store = StudioProjectStore(root, FakeCanvasAdapter())
            project = project_store.create("article", "端到端封面")
            other_project = project_store.create("article", "另一个文章")
            storage = ProjectStorage(root / "project-storage")
            storage.ensure_layout()

            def resolve_media(asset_id, result_id):
                if asset_id or not result_id:
                    return None
                record = storage.get_result(result_id)
                path = storage.result_path(result_id) if record else None
                if not record or path is None or not path.is_file() or path.stat().st_size <= 0:
                    return None
                return {
                    "url": storage.result_url(result_id),
                    "name": record.get("display_name") or "",
                    "mime": record.get("mime") or "",
                    "kind": record.get("kind") or "",
                }

            article_store = StudioArticleStore(
                root,
                project_store,
                catalog_fixture(root / "static" / "article-templates" / "catalog.json"),
                resolve_media_reference=resolve_media,
                register_managed_result=storage.register_managed_result,
                find_shared_media_by_hash=lambda digest, kind: find_shared_media_by_hash(storage, digest, kind),
            )
            settings_canvas = {
                "id": ARTICLE_SETTINGS_CANVAS_ID,
                "title": "文章生成配置",
                "kind": "smart",
                "revision": 4,
                "nodes": [
                    {"id": "article-image", "type": "smart-image-generator", "promptDraftText": "默认封面", "runSettings": {"model": "fixture-image"}},
                    {"id": "article-cover", "type": "smart-hypit-output", "hypitSlot": "image"},
                ],
                "connections": [{"from": "article-image", "to": "article-cover", "kind": "input"}],
                "settings": {},
                "viewport": {"x": 0, "y": 0, "scale": 1},
                "logs": [],
            }

            class SettingsService:
                def ensure_canvas(self):
                    return copy.deepcopy(settings_canvas)

            execute_calls = []

            async def prepare(canvas, node, request_id, upstream, user_request, *, preflight):
                return {
                    "kind": "image",
                    "prompt": str(user_request.get("prompt") or node.get("promptDraftText") or ""),
                    "parameters": {},
                    "inputs": {},
                    "request_id": request_id,
                    "preflight": preflight,
                }

            async def preflight(canvas, node, request, request_id):
                return {"node_id": node["id"], "validated": True}

            async def execute(canvas, node, request, request_id, resolved, on_submitted):
                execute_calls.append((node["id"], request["prompt"]))
                on_submitted({"provider_task_id": "fixture-no-network"})
                return {"fixture": "image-bytes-are-created-by-the-isolated-collector"}

            async def collect(result, request, task):
                source = root / "fixture-cover.png"
                source.write_bytes(b"isolated managed image result")
                managed = storage.store_result_file(source, "fixture-cover.png")
                return [{
                    "kind": "image", "url": managed["url"], "resultId": managed["id"],
                    "name": managed["display_name"],
                }]

            runner = HypitFlowRunner(
                load_canvas=lambda canvas_id: copy.deepcopy(settings_canvas)
                    if canvas_id == ARTICLE_SETTINGS_CANVAS_ID else None,
                storage=storage,
                prepare_node_request=prepare,
                preflight_node=preflight,
                execute_node=execute,
                collect_results=collect,
                notify=lambda *_args: None,
                lock=threading.RLock(),
                now_ms=lambda: int(time.time() * 1000),
                canvas_id=ARTICLE_SETTINGS_CANVAS_ID,
                module_id="article",
            )
            bridge = StudioArticleGenerationBridge(
                article_store=article_store,
                runner=runner,
                storage=storage,
                settings_service=SettingsService(),
            )
            runner.publish_node_result = bridge.publish_node_result

            app = FastAPI()
            app.include_router(create_studio_projects_router(root, FakeCanvasAdapter(), store=project_store))
            app.include_router(create_studio_articles_router(
                root,
                project_store,
                catalog_path=root / "static" / "article-templates" / "catalog.json",
                resolve_media_reference=resolve_media,
                store=article_store,
                submit_generation=bridge.submit,
                get_generation=bridge.get,
            ))

            with TestClient(app) as client:
                article_path = f"/api/studio/articles/{project['id']}"
                initial = client.get(article_path).json()["article"]
                request_body = {
                    "slot": "image", "purpose": "cover", "output_node_id": "article-cover",
                    "client_operation_id": "article-e2e-operation-1", "base_revision": initial["revision"],
                    "request": {"prompt": "生成一张测试封面"},
                }
                submitted = client.post(f"{article_path}/generations", json=request_body)
                self.assertEqual(submitted.status_code, 200, submitted.text)
                run_id = submitted.json()["generation"]["run_id"]

                latest = None
                for _ in range(100):
                    response = client.get(f"{article_path}/generations/{run_id}")
                    self.assertEqual(response.status_code, 200, response.text)
                    latest = response.json()
                    if latest["generation"].get("status") == "succeeded":
                        break
                    time.sleep(0.01)
                self.assertIsNotNone(latest)
                self.assertEqual(latest["generation"]["status"], "succeeded")
                self.assertEqual(len(latest["article"]["cover_variants"]), 1)
                cover = latest["article"]["cover_variants"][0]
                self.assertTrue(cover["valid"])
                self.assertTrue(cover["url"].startswith("/api/results/res_"))
                self.assertEqual(cover["mime"], "image/png")
                self.assertEqual(latest["article"]["selected_cover_variant_id"], cover["id"])
                self.assertEqual(execute_calls, [("article-image", "生成一张测试封面")])

                wrong_article = client.get(
                    f"/api/studio/articles/{other_project['id']}/generations/{run_id}"
                )
                self.assertEqual(wrong_article.status_code, 404)

                # 自动关联会递增文章修订；同 operation ID 仍读取原任务而不再次执行。
                replay = client.post(f"{article_path}/generations", json=request_body)
                self.assertEqual(replay.status_code, 200, replay.text)
                self.assertEqual(replay.json()["generation"]["run_id"], run_id)
                self.assertEqual(execute_calls, [("article-image", "生成一张测试封面")])

                changed_request = {
                    **request_body,
                    "request": {"prompt": "同一操作 ID 不得提交另一条提示词"},
                }
                rejected_replay = client.post(f"{article_path}/generations", json=changed_request)
                self.assertEqual(rejected_replay.status_code, 409, rejected_replay.text)
                self.assertEqual(execute_calls, [("article-image", "生成一张测试封面")])
                final_article = client.get(article_path).json()["article"]
                self.assertEqual(len(final_article["cover_variants"]), 1)


if __name__ == "__main__":
    unittest.main()
