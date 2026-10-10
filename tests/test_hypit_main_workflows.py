import copy
import asyncio
import sys
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main
import studio_app_execution
import studio_hypit_models
from project_storage import ProjectStorage
from studio_hypit_flow import HypitFlowRunner


class Request(BaseModel):
    prompt: str = ""
    width: int = 1024
    height: int = 1024
    params: dict = {}


class HypitMainWorkflowTests(unittest.TestCase):
    def test_agent_run_node_completes_server_task_and_projects_green_after_connect(self):
        """用真实 Agent 路由与 StudioExecution 验证先运行后连输出，不需要浏览器 Agent。"""
        import time
        import threading
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from canvas_agent import create_agent_router
        from canvas_core.headless_canvas import HeadlessCanvas
        from canvas_core.hypit_config import hypit_execution_recipe_fingerprint, validate_hypit_settings_canvas
        from project_storage import ProjectStorage
        from studio_execution import StudioExecution
        from studio_hypit_canvas import HypitSettingsCanvasService, create_hypit_settings_canvas_router

        temp_root_base = ROOT / "cache" / "studio-tests" / "tmp"
        temp_root_base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root_base) as temp_root:
            storage = ProjectStorage(Path(temp_root) / "project")
            storage.ensure_layout()
            lock = threading.RLock()
            stored_canvas = {
                "id": "hypit-settings", "title": "Hypit 生成配置", "kind": "smart",
                "project": "__hypit_settings__", "revision": 1,
                "hypit_flow_schema_version": 1, "hypit_legacy_migration_done": True,
                "nodes": [
                    {"id": "image-source", "displayNumber": 1, "type": "smart-image-generator",
                     "title": "图片生成", "promptDraftText": "fixture prompt", "promptDraftHtml": "fixture prompt",
                     "runSettings": {"provider_id": "fixture", "model": "image-fixture",
                                     "capabilityParameters": {"image-fixture": {}}},
                     "images": [], "connections": [], "creationTasks": [], "resultVersions": []},
                    {"id": "image-output", "displayNumber": 2, "type": "smart-hypit-output",
                     "title": "图片输出", "hypitSlot": "image"},
                ],
                "connections": [], "viewport": {"x": 0, "y": 0, "scale": 1},
                "logs": [], "settings": {},
            }

            def load_canvas(canvas_id):
                if canvas_id != "hypit-settings":
                    raise FileNotFoundError(canvas_id)
                with lock:
                    return copy.deepcopy(stored_canvas)

            def save_canvas(canvas, *, increment_revision=True, touch_updated_at=True):
                nonlocal stored_canvas
                with lock:
                    value = copy.deepcopy(canvas)
                    if increment_revision:
                        value["revision"] = int(stored_canvas.get("revision") or 1) + 1
                    if touch_updated_at:
                        value["updated_at"] = int(time.time() * 1000)
                    stored_canvas = value
                    return copy.deepcopy(value)

            async def preflight(_canvas, _node, _request, _request_id):
                return {"fixture_validated": True}

            async def generate(_request):
                return {"fixture": True}

            async def collect(_result, _request, _task):
                source = Path(temp_root) / "fixture.png"
                source.write_bytes(b"managed fixture image")
                managed = storage.store_result_file(source, "fixture.png")
                return [{"kind": "image", "resultId": managed["id"], "url": managed["url"]}]

            metadata_calls = []

            def task_metadata(canvas, node, _request):
                value = {
                    "hypit_source_node_id": node["id"],
                    "hypit_source_recipe_fingerprint": hypit_execution_recipe_fingerprint(canvas, node["id"]),
                    "hypit_supported_output_slots": ["image"],
                }
                metadata_calls.append(value)
                return value

            async def notify(_canvas):
                return None

            statuses = lambda canvas_id, canvas: main.studio_hypit_test_statuses(canvas_id, canvas)
            settings_service = HypitSettingsCanvasService(
                load_canvas=load_canvas,
                save_canvas=save_canvas,
                lock=lock,
                load_legacy_settings=lambda: None,
                backup_legacy_settings=lambda _record: None,
                migrate_legacy_settings=lambda _defaults, _canvas_id: copy.deepcopy(stored_canvas),
                validate_canvas=validate_hypit_settings_canvas,
                test_statuses=statuses,
                broadcast_canvas_updated=lambda *_args: None,
                now_ms=lambda: int(time.time() * 1000),
            )
            execution = StudioExecution(
                load_canvas=load_canvas,
                save_canvas=settings_service.save_agent_canvas,
                lock=lock,
                storage=storage,
                preflight=preflight,
                generate=generate,
                collect=collect,
                notify=notify,
                task_metadata=task_metadata,
            )

            async def submit_run(canvas, node, request_id):
                result = await execution.submit(canvas, node, request_id)
                latest = load_canvas(canvas["id"])
                canvas.clear()
                canvas.update(latest)
                return result

            async def cancel_run(_canvas, _node, _task_id):
                return None

            executor = HeadlessCanvas(
                load_canvas=load_canvas,
                save_canvas=settings_service.save_agent_canvas,
                lock=lock,
                submit_run=submit_run,
                cancel_run=cancel_run,
                validate_model=lambda *_args: {"runnable": True, "parameters": {}},
                notify=notify,
            )
            app = FastAPI()
            app.include_router(create_hypit_settings_canvas_router(service=settings_service))
            app.include_router(create_agent_router(Path(temp_root) / "agent", load_canvas, executor=executor))

            with mock.patch.object(main, "PROJECT_STORAGE", storage), TestClient(app) as client:
                capabilities = client.get("/api/agent/capabilities")
                self.assertEqual(capabilities.status_code, 200)
                self.assertFalse(capabilities.json()["requires_open_canvas"])

                initial = client.get("/api/hypit/settings-canvas").json()["canvas"]
                self.assertEqual(initial["test_statuses"]["image-output"]["status"], "unconfigured")

                submitted = client.post(
                    "/api/agent/canvases/hypit-settings/commands",
                    json={"request_id": "hypit-server-run-1", "action": "run_node",
                          "args": {"node_id": "image-source"}},
                )
                self.assertEqual(submitted.status_code, 200, submitted.text)
                command_id = submitted.json()["id"]
                command = submitted.json()
                deadline = time.monotonic() + 3
                while command.get("status") not in {"succeeded", "failed"} and time.monotonic() < deadline:
                    time.sleep(0.01)
                    command = client.get(f"/api/agent/canvases/hypit-settings/commands/{command_id}").json()
                self.assertEqual(command["status"], "succeeded", (command, metadata_calls))
                self.assertEqual(len(metadata_calls), 2)
                self.assertEqual(metadata_calls[0], metadata_calls[1])
                task_ids = command["result"]["task_ids"]
                self.assertEqual(len(task_ids), 1)

                deadline = time.monotonic() + 3
                task = storage.get_canvas_task(task_ids[0])
                while task and task.get("status") not in {"succeeded", "failed", "cancelled", "recoverable"} and time.monotonic() < deadline:
                    time.sleep(0.01)
                    task = storage.get_canvas_task(task_ids[0])
                self.assertEqual(task["status"], "succeeded", task)
                self.assertEqual(task["canvas_id"], "hypit-settings")

                before_connect = client.get("/api/hypit/settings-canvas").json()["canvas"]
                self.assertFalse(before_connect["test_statuses"]["image-output"]["test_passed"])
                self.assertEqual(before_connect["test_statuses"]["image-output"]["status"], "unconfigured")

                connected = client.post(
                    "/api/agent/canvases/hypit-settings/commands",
                    json={"request_id": "hypit-connect-output-1", "action": "connect",
                          "args": {"from": "image-source", "to": "image-output"}},
                )
                self.assertEqual(connected.status_code, 200, connected.text)
                after_connect = client.get("/api/hypit/settings-canvas").json()["canvas"]
                self.assertTrue(after_connect["test_statuses"]["image-output"]["test_passed"])
                self.assertTrue(after_connect["test_statuses"]["image-output"]["current_recipe_matches"])
                self.assertEqual(after_connect["test_statuses"]["image-output"]["output_kind"], "image")

    def test_scaffold_backup_is_once_only_and_uses_managed_backup_root(self):
        callback = getattr(main, "studio_hypit_backup_legacy_prompt_scaffold", None)
        self.assertTrue(callable(callback), "应备份可证明旧提示词脚手架后再写回配置图")
        temp_root_base = ROOT / "cache" / "studio-tests" / "tmp"
        temp_root_base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root_base) as temp_root:
            backup_root = Path(temp_root) / "backups"
            storage = mock.Mock(backups_dir=backup_root)
            original = {"id": "hypit-settings", "revision": 4, "nodes": [{"id": "old"}]}
            with mock.patch.object(main, "PROJECT_STORAGE", storage):
                callback(original)
                target = backup_root / "hypit" / "hypit-settings-before-empty-prompt-scaffold-cleanup.json"
                first = target.read_bytes()
                callback({**original, "revision": 5, "nodes": []})
            self.assertEqual(target.read_bytes(), first)
            self.assertIn(b'"revision": 4', first)

    def test_one_generator_can_feed_multiple_outputs_but_only_requested_slot_is_checked(self):
        canvas = {
            "id": "hypit-settings",
            "nodes": [
                {"id": "image-gen", "type": "smart-image-generator", "runSettings": {"provider_id": "fixture", "model": "image-v1"}},
                {"id": "out-image", "type": "smart-hypit-output", "hypitSlot": "image"},
                {"id": "out-video", "type": "smart-hypit-output", "hypitSlot": "video"},
            ],
            "connections": [
                {"from": "image-gen", "to": "out-image", "kind": "input"},
                {"from": "image-gen", "to": "out-video", "kind": "input"},
            ],
        }
        with mock.patch.object(main, "studio_request_for", side_effect=lambda *_args, **_kwargs: {"kind": "image", "request_id": ""}):
            request = asyncio.run(main.studio_hypit_prepare_node_request(
                copy.deepcopy(canvas), canvas["nodes"][0], "op", {},
                {"_hypit_requested_slot": "image", "_hypit_output_node_id": "out-image"},
                preflight=True,
            ))
            video_request = asyncio.run(main.studio_hypit_prepare_node_request(
                copy.deepcopy(canvas), canvas["nodes"][0], "op-video", {},
                {"_hypit_requested_slot": "video", "_hypit_output_node_id": "out-video"},
                preflight=True,
            ))
        self.assertEqual(request["_hypit_output_slot"], "image")
        self.assertEqual(video_request["_hypit_output_slot"], "video")

    def test_generic_task_endpoint_projects_hypit_flow_without_private_snapshot(self):
        private_task = {
            "id": "run-private",
            "kind": "hypit_settings_flow",
            "accepted_snapshot": {"workflow_json": {"secret": "not-public"}},
            "provider_config": {"api_key": "not-public"},
        }
        public_flow = {
            "run_id": "run-private", "status": "succeeded", "output_kind": "image",
            "media": [{"kind": "image", "url": "/api/results/fixture.png"}],
        }
        storage = mock.Mock()
        storage.get_canvas_task.return_value = private_task
        runner = mock.Mock()
        runner.get.return_value = public_flow

        with mock.patch.object(main, "PROJECT_STORAGE", storage), \
             mock.patch.object(main, "HYPIT_FLOW_RUNNER", runner):
            response = asyncio.run(main.studio_task_status("run-private"))

        self.assertEqual(response["run_id"], public_flow["run_id"])
        self.assertEqual(response["media"], public_flow["media"])
        self.assertEqual(response["result"]["images"], public_flow["media"])
        self.assertNotIn("accepted_snapshot", response)
        self.assertNotIn("provider_config", response)

    def test_test_status_callback_is_read_only_projection_for_reserved_canvas(self):
        canvas = {
            "id": "hypit-settings",
            "nodes": [
                {"id": "image", "type": "smart-image-generator", "runSettings": {"provider_id": "fixture", "model": "image-v1"}},
                {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image"},
            ],
            "connections": [{"from": "image", "to": "image-output", "kind": "input"}],
        }
        with mock.patch.object(main.PROJECT_STORAGE, "get_canvas_task", return_value=None) as get_task, \
             mock.patch.object(main.PROJECT_STORAGE, "get_result", return_value=None):
            result = main.studio_hypit_test_statuses("hypit-settings", canvas)
        self.assertFalse(result["image-output"]["test_passed"])
        self.assertEqual(result["image-output"]["status"], "ready")
        get_task.assert_not_called()

    def test_hypit_static_execution_metadata_uses_slot_contract_and_audio_union(self):
        image = {
            "id": "image", "type": "smart-image-generator",
            "runSettings": {"provider_id": "fixture", "model": "image-v1"},
        }
        canvas = {"id": "hypit-settings", "nodes": [image], "connections": []}
        profile = {
            "model_id": "image-v1", "node_type": "image_generation", "operation": "text_to_image",
            "selectable": True, "runnable": True, "readiness": "ready",
            "inputs": {"prompt": {"media_type": "text", "role": "prompt", "min": 1}},
            "output": {"media_type": "image"},
        }
        request = {"kind": "image", "provider_id": "fixture", "model": "image-v1"}
        with mock.patch.object(main.MODEL_CAPABILITY_REGISTRY, "find_model", return_value=profile), \
             mock.patch.object(main, "canvas_api_providers", return_value=[]):
            metadata = main.studio_hypit_task_metadata(canvas, image, request)
        self.assertEqual(metadata["hypit_supported_output_slots"], ["image"])
        self.assertEqual(len(metadata["hypit_source_recipe_fingerprint"]), 64)

        audio_node = {"id": "audio", "type": "smart-audio-generator"}
        audio_profile = {
            **profile, "node_type": "audio_generation", "operation": "speech_or_audio",
            "output": {"media_type": "audio"},
        }
        audio_request = {"kind": "audio", "provider_id": "fixture", "model": "audio-v1"}
        with mock.patch.object(main.MODEL_CAPABILITY_REGISTRY, "find_model", return_value=audio_profile), \
             mock.patch.object(main, "canvas_api_providers", return_value=[]):
            supported = main.studio_hypit_supported_output_slots(audio_node, audio_request)
        self.assertEqual(supported, ["audio", "voice"])

        rejected_profile = {**profile, "operation": "image_enhance"}
        with mock.patch.object(main.MODEL_CAPABILITY_REGISTRY, "find_model", return_value=rejected_profile), \
             mock.patch.object(main, "canvas_api_providers", return_value=[]):
            with self.assertRaises(HTTPException) as caught:
                main.studio_hypit_task_metadata(canvas, image, request)
        self.assertIn("不符合 Hypit 用途契约", str(caught.exception.detail))

    def test_article_main_adapters_use_article_identity_and_article_profile_rules(self):
        """Article 的状态、普通运行指纹与生产预检按 article-settings 身份处理。"""
        # FastAPI 当前以延迟包含路由形式保存子路由；OpenAPI 顺序反映最终注册顺序。
        registered_paths = list(main.app.openapi()["paths"])
        self.assertIn("/api/studio/articles/settings-canvas", registered_paths)
        self.assertIn("/api/studio/articles/{project_id}", registered_paths)
        self.assertLess(
            registered_paths.index("/api/studio/articles/settings-canvas"),
            registered_paths.index("/api/studio/articles/{project_id}"),
        )
        self.assertIn("/api/studio/articles/{project_id}/generations", registered_paths)
        article_node = {
            "id": "article-image", "type": "smart-image-generator",
            "runSettings": {"provider_id": "fixture", "model": "image-enhance-fixture"},
        }
        article_output = {
            "id": "article-image-output", "type": "smart-hypit-output", "hypitSlot": "image",
        }
        canvas = {
            "id": "article-settings", "nodes": [article_node, article_output],
            "connections": [{"from": "article-image", "to": "article-image-output", "kind": "input"}],
        }
        profile = {
            "model_id": "image-enhance-fixture", "node_type": "image_generation",
            "operation": "image_enhance", "selectable": True, "runnable": True,
            "readiness": "ready", "inputs": {"prompt": {"media_type": "text", "role": "prompt", "min": 1}},
            "output": {"media_type": "image"},
        }
        request = {
            "kind": "image", "provider_id": "fixture", "model": "image-enhance-fixture",
            "region": "", "parameters": {}, "inputs": {"prompt": "fixture"},
            "input_counts": {}, "input_roles": {}, "_hypit_output_slot": "image",
        }
        with mock.patch.object(main.MODEL_CAPABILITY_REGISTRY, "find_model", return_value=profile), \
             mock.patch.object(main, "canvas_api_providers", return_value=[]):
            metadata = main.studio_hypit_task_metadata(canvas, article_node, request)
            self.assertEqual(metadata["hypit_supported_output_slots"], ["image"])
            self.assertEqual(len(metadata["hypit_source_recipe_fingerprint"]), 64)
            # 本文用途可以用普通文章模块可运行的图像能力；不套 Hypit 专用工具黑名单。
            self.assertEqual(main.studio_article_supported_output_slots(article_node, request), ["image"])

        with mock.patch.object(main.PROJECT_STORAGE, "get_canvas_task", return_value=None), \
             mock.patch.object(main.PROJECT_STORAGE, "get_result", return_value=None):
            statuses = main.studio_hypit_test_statuses("article-settings", canvas, module_id="article")
            projected_canvas = asyncio.run(main.ARTICLE_SETTINGS_CANVAS_SERVICE.projected_canvas(canvas))
        self.assertEqual(statuses["article-image-output"]["status"], "ready")
        self.assertFalse(statuses["article-image-output"]["test_passed"])
        self.assertEqual(projected_canvas["test_statuses"]["article-image-output"]["status"], "ready")
        with self.assertRaises(ValueError):
            main.studio_hypit_test_statuses("article-settings", canvas, module_id="hypit")

        async_preflight = mock.AsyncMock(return_value={"preflight": "ordinary shared canvas check"})
        with mock.patch.object(main, "studio_preflight", new=async_preflight), \
             mock.patch.object(main.MODEL_CAPABILITY_REGISTRY, "find_model", return_value=profile), \
             mock.patch.object(main, "canvas_api_providers", return_value=[]):
            result = asyncio.run(main.studio_hypit_preflight_node(
                canvas, article_node, request, "article-preflight-run",
            ))
        self.assertEqual(result["preflight"], "ordinary shared canvas check")
        async_preflight.assert_awaited_once()

        # 同一档案仍被 Hypit 的专用 profile 规则拒绝，确认 Article 适配没有放宽 Hypit。
        hypit_canvas = {**canvas, "id": "hypit-settings"}
        with mock.patch.object(main, "studio_preflight", new=mock.AsyncMock(return_value={})), \
             mock.patch.object(main.MODEL_CAPABILITY_REGISTRY, "find_model", return_value=profile), \
             mock.patch.object(main, "canvas_api_providers", return_value=[]):
            with self.assertRaises(HTTPException):
                asyncio.run(main.studio_hypit_preflight_node(
                    hypit_canvas, article_node, request, "hypit-preflight-run",
                ))

    def test_hypit_static_run_rejects_connected_incompatible_slot_before_run_record(self):
        image = {
            "id": "image", "type": "smart-image-generator",
            "runSettings": {"provider_id": "fixture", "model": "image-v1"},
        }
        video_output = {"id": "video-output", "type": "smart-hypit-output", "hypitSlot": "video"}
        canvas = {
            "id": "hypit-settings", "nodes": [image, video_output],
            "connections": [{"from": "image", "to": "video-output", "kind": "input"}],
        }
        request = {
            "provider_id": "fixture", "model": "image-v1", "kind": "image", "region": "",
            "inputs": {"prompt": "fixture"}, "input_counts": {}, "input_roles": {}, "parameters": {},
        }
        with mock.patch.object(main, "studio_hypit_supported_output_slots", return_value=["image"]), \
             mock.patch.object(main, "canvas_preflight", new=mock.AsyncMock()) as preflight:
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(main.studio_preflight(canvas, image, request, "fixture-run"))
        self.assertIn("不适用于 Hypit video", str(caught.exception.detail))
        preflight.assert_not_awaited()

    def test_hypit_managed_result_projection_requires_existing_nonempty_file(self):
        temp_root_base = ROOT / "cache" / "studio-tests" / "tmp"
        temp_root_base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root_base) as temp_root:
            path = Path(temp_root) / "managed.png"
            record = {"id": "image-1", "kind": "image"}
            with mock.patch.object(main, "PROJECT_STORAGE", mock.Mock(
                get_result=mock.Mock(return_value=record),
                result_path=mock.Mock(return_value=path),
            )):
                self.assertIsNone(main.studio_hypit_verified_managed_result("image-1"))
                path.write_bytes(b"fixture image bytes")
                verified = main.studio_hypit_verified_managed_result("image-1")
            self.assertTrue(verified["_managed_verified"])

    def test_trusted_workflow_projection_does_not_apply_legacy_node_id_patches(self):
        graph = {
            "23": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
            "144": {"class_type": "PreviewImage", "inputs": {"width": 512, "height": 640}},
            "22": {"class_type": "SomeNode", "inputs": {"seed": 41}},
        }
        before = copy.deepcopy(graph)

        projected, seed = main.prepare_comfy_workflow_request(
            graph,
            Request(prompt="Hypit prompt", width=768, height=768),
            trusted_snapshot=True,
        )

        self.assertEqual(projected, before)
        self.assertIsNone(seed)

    def test_trusted_workflow_applies_only_explicit_schema_projected_params(self):
        graph = {
            "23": {"class_type": "TextEncode", "inputs": {"text": "configured"}},
            "144": {"class_type": "Resize", "inputs": {"width": 512, "height": 640}},
            "22": {"class_type": "Seed", "inputs": {"seed": 41}},
        }
        request = Request(
            prompt="request prompt",
            width=768,
            height=768,
            params={"23": {"text": "mapped prompt"}},
        )

        projected, seed = main.prepare_comfy_workflow_request(graph, request, trusted_snapshot=True)

        self.assertEqual(projected["23"]["inputs"]["text"], "mapped prompt")
        self.assertEqual(projected["144"]["inputs"], {"width": 512, "height": 640})
        self.assertEqual(projected["22"]["inputs"]["seed"], 41)
        self.assertIsNone(seed)

    def test_legacy_workflow_keeps_existing_zimage_overrides(self):
        graph = {
            "23": {"class_type": "TextEncode", "inputs": {"text": "configured"}},
            "144": {"class_type": "Resize", "inputs": {"width": 512, "height": 640}},
            "22": {"class_type": "Seed", "inputs": {"seed": 41}},
        }
        request = Request(prompt="legacy prompt", width=768, height=832, params={})

        projected, seed = main.prepare_comfy_workflow_request(graph, request, trusted_snapshot=False, seed=123)

        self.assertEqual(projected["23"]["inputs"]["text"], "legacy prompt")
        self.assertEqual(projected["144"]["inputs"], {"width": 768, "height": 832})
        self.assertEqual(projected["22"]["inputs"]["seed"], 123)
        self.assertEqual(seed, 123)

    def test_unknown_image_bucket_entry_is_not_accepted_as_image(self):
        with self.assertRaisesRegex(RuntimeError, "未返回可确认的 image"):
            studio_hypit_models._validate_workflow_result("image", {
                "images": [{"url": "https://fixture.invalid/result?id=opaque"}],
            })

    def test_slot_projection_only_returns_confirmed_matching_results(self):
        result = studio_hypit_models._validate_workflow_result("image", {
            "images": [
                {"url": "/api/results/opaque"},
                {"url": "/api/results/image.png"},
            ],
            "videos": [{"url": "/api/results/clip.mp4"}],
            "files": [{"url": "/api/results/unknown"}],
        })
        self.assertEqual([item["url"] for item in result["images"]], ["/api/results/image.png"])
        self.assertNotIn("videos", result)
        self.assertNotIn("files", result)

    def test_runninghub_candidates_are_unavailable_without_saved_region_key(self):
        provider = {
            "rh_apps": [{"id": "app-1", "title": "Fixture app", "enabled": True,
                         "fields": [{"nodeId": "1", "fieldName": "prompt", "fieldType": "TEXT", "required": True}]}],
            "rh_workflows": [],
        }
        with mock.patch.object(main, "_hypit_runninghub_region", return_value=(provider, provider, True)), \
             mock.patch.object(main, "runninghub_api_key", side_effect=HTTPException(400, "no key")), \
             mock.patch.object(main, "COMFYUI_INSTANCES", []), \
             mock.patch.object(main, "list_workflows", return_value={"workflows": []}):
            options = main.studio_hypit_workflow_options()
        candidates = [item for item in options if item["source"] == "runninghub_app"]
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(not item["enabled"] for item in candidates))
        self.assertTrue(all(item["reason_code"] == "credentials_missing" for item in candidates))
        self.assertTrue(all("API Key" in item["unavailable_reason"] for item in candidates))


class HypitMainCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_runninghub_callback_uses_private_snapshot_for_submit(self):
        graph = {"23": {"class_type": "fixture", "inputs": {"text": "configured"}}}
        fields = [{"nodeId": "23", "fieldName": "text", "fieldType": "TEXT"}]
        submit = mock.AsyncMock(return_value={"task_id": "fixture-task"})
        request = {
            "kind": "runninghub_workflow", "platform_request": {"workflowId": "wf-fixture"},
            "workflow": graph, "_hypit_execution_snapshot": {"fields": fields},
        }
        with mock.patch.object(main, "_runninghub_workflow_submit", submit):
            result = await main.studio_runninghub_submit(request)
        self.assertEqual(result["task_id"], "fixture-task")
        args, kwargs = submit.await_args
        self.assertEqual(args[0].workflowId, "wf-fixture")
        self.assertEqual(kwargs["trusted_fields"], fields)
        self.assertEqual(kwargs["trusted_workflow"], graph)

    async def test_runninghub_query_callback_keeps_strict_region_and_wallet(self):
        query = mock.AsyncMock(return_value={"status": "SUCCESS"})
        with mock.patch.object(main, "_runninghub_query", query):
            result = await main.studio_runninghub_query("fixture-task", {
                "region": "cn", "use_wallet": True, "strict_result": True,
            })
        self.assertEqual(result["status"], "SUCCESS")
        query.assert_awaited_once_with("fixture-task", True, "cn", strict=True)


class HypitDynamicInputChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_module_settings_freeze_dynamic_schema_and_definition_with_actual_upstream(self):
        from canvas_core.hypit_config import ARTICLE_SETTINGS_CANVAS_ID, MUSIC_SETTINGS_CANVAS_ID

        temp_root_base = ROOT / "cache" / "studio-tests" / "tmp"
        temp_root_base.mkdir(parents=True, exist_ok=True)
        for module_id, canvas_id in (
            ("hypit", "hypit-settings"),
            ("article", ARTICLE_SETTINGS_CANVAS_ID),
            ("music", MUSIC_SETTINGS_CANVAS_ID),
        ):
            with self.subTest(module_id=module_id), tempfile.TemporaryDirectory(
                prefix=f"{module_id}-accepted-schema-", dir=temp_root_base,
            ) as temp_root:
                storage = ProjectStorage(Path(temp_root))
                storage.ensure_layout()
                old_definition = {"wf-node": {"class_type": "TextEncode", "inputs": {"text": "accepted definition"}}}
                changed_definition = {"wf-node": {"class_type": "TextEncode", "inputs": {"text": "changed definition"}}}
                old_fields = [{
                    "nodeId": "consumer-node", "fieldName": "lyrics", "fieldType": "STRING",
                    "required": True, "enabled": True,
                }]
                changed_fields = [{
                    "nodeId": "consumer-node", "fieldName": "replacement", "fieldType": "STRING",
                    "required": True, "enabled": True,
                }]
                forged_snapshot = {
                    "version": 1, "node_type": "smart-ai-app",
                    "fields": [{"nodeId": "forged", "fieldName": "credential", "fieldType": "STRING"}],
                    "workflow_definition": {"wf-node": {"class_type": "Forged", "inputs": {"text": "forged"}}},
                }
                canvas = {
                    "id": canvas_id, "revision": 1, "nodes": [
                        {"id": "source", "type": "smart-text-generator", "title": "歌词源",
                         "promptDraftText": "真实上游歌词", "runSettings": {"textProvider": "fixture", "textModel": "fixture-text"},
                         "images": []},
                        {"id": "consumer", "type": "smart-ai-app", "title": "动态工作流",
                         "runSettings": {"rhMode": "workflow", "rhConfigKey": "workflow:fixture-workflow",
                                         "rhWorkflowId": "fixture-workflow", "rhRegion": "global",
                                         "_studioAcceptedDynamicSnapshot": copy.deepcopy(forged_snapshot),
                                         "_musicSchemaSnapshot": copy.deepcopy(forged_snapshot)},
                         "images": []},
                        {"id": "output-image", "type": "smart-hypit-output", "hypitSlot": "image"},
                    ],
                    "connections": [
                        {"from": "source", "to": "consumer", "kind": "input",
                         "targetFieldKey": "consumer-node::lyrics"},
                        {"from": "consumer", "to": "output-image", "kind": "input"},
                    ],
                }
                saved_canvas = copy.deepcopy(canvas)
                resolver_calls = []
                executed = []
                preflight_requests = []

                def resolve_schema(_workflow_id, _node, _canvas):
                    resolver_calls.append(len(resolver_calls) + 1)
                    return {
                        "fields": copy.deepcopy(old_fields if len(resolver_calls) == 1 else changed_fields),
                        "workflowJson": copy.deepcopy(old_definition if len(resolver_calls) == 1 else changed_definition),
                    }

                async def preflight(_canvas, node, request, _request_id):
                    preflight_requests.append((node["id"], copy.deepcopy(request)))
                    if node["id"] == "consumer":
                        self.assertIn("consumer-node::lyrics", request.get("app_field_values", {}), request)
                        self.assertEqual(request["workflow"], old_definition)
                    return {"fixture_validated": True}

                async def execute(_canvas, node, request, _request_id, _resolved, on_submitted):
                    executed.append(node["id"])
                    on_submitted({"provider_task_id": f"fixture-{node['id']}"})
                    if node["id"] == "consumer":
                        self.assertEqual(request["app_field_values"].get("consumer-node::lyrics"), "真实上游歌词")
                        self.assertNotIn("consumer-node::replacement", request["app_field_values"])
                        self.assertEqual(request["workflow"], old_definition)
                        self.assertEqual(request["_studio_dynamic_snapshot"]["fields"], old_fields)
                        return {"fixture_kind": "image"}
                    return {"fixture_kind": "text"}

                async def collect(result, _request, task):
                    kind = result["fixture_kind"]
                    extension = ".txt" if kind == "text" else ".png"
                    source = Path(temp_root) / f"{task['id']}-{kind}{extension}"
                    source.write_text("真实上游歌词" if kind == "text" else "fixture image", encoding="utf-8")
                    stored = storage.store_result_file(source, source.name)
                    item = {"kind": kind, "url": stored["url"], "resultId": stored["id"], "name": stored["display_name"]}
                    if kind == "text":
                        item.update(text="真实上游歌词", content="真实上游歌词")
                    return [item]

                if module_id == "music":
                    trusted_context = {
                        "module_id": "music", "project_id": "fixture-project", "purpose": "cover", "slot": "image",
                        "accepted_revision": 1, "source_hash": "a" * 64, "client_operation_id": "accepted-schema-op",
                        "client_request_sha256": "b" * 64, "client_base_revision": 1,
                        "source_snapshot": {"title": "", "lyrics": "歌词", "style_prompt": "", "notes": "",
                                            "cover_prompt": "封面", "reference_audio_refs": [], "score_refs": []},
                        "settings_revision": 1, "resolved_request": {"parameters": {}, "input_fields": {}},
                    }
                elif module_id == "article":
                    trusted_context = {
                        "module_id": "article", "project_id": "fixture-project", "purpose": "cover", "slot": "image",
                        "accepted_revision": 1, "source_hash": "a" * 64, "client_operation_id": "accepted-schema-op",
                    }
                else:
                    trusted_context = None

                runner = HypitFlowRunner(
                    load_canvas=lambda _canvas_id: copy.deepcopy(canvas), storage=storage,
                    prepare_node_request=main.studio_hypit_prepare_node_request,
                    preflight_node=preflight, execute_node=execute, collect_results=collect,
                    notify=lambda *_args: None, lock=threading.RLock(), now_ms=lambda: 1,
                    canvas_id=canvas_id, module_id=module_id,
                )
                payload = {"base_revision": 1, "request": {}}
                with mock.patch.object(main.STUDIO_APP_EXECUTION, "resolve_runninghub_fields", side_effect=resolve_schema):
                    submitted = await runner.submit(
                        "image", "output-image", "accepted-schema-op", payload, test=False,
                        trusted_context=trusted_context,
                    )
                    await asyncio.wait_for(runner._active[submitted["run_id"]], timeout=5)
                    status = runner.get(submitted["run_id"])
                    self.assertEqual(status["status"], "succeeded", status)
                    self.assertEqual(resolver_calls, [1], "runtime must not resolve the changed schema")
                    self.assertEqual(executed, ["source", "consumer"])
                    self.assertEqual(canvas, saved_canvas, "task snapshot preparation must not write into the settings graph")
                    task = storage.get_canvas_task(submitted["run_id"])
                    private_nodes = {node["id"]: node for node in task["private_snapshot"]["canvas"]["nodes"]}
                    accepted = private_nodes["consumer"]["runSettings"]["_studioAcceptedDynamicSnapshot"]
                    self.assertEqual(accepted["fields"], old_fields)
                    self.assertEqual(accepted["workflow_definition"], old_definition)
                    self.assertNotIn("accepted definition", json.dumps(status, ensure_ascii=False))
                    self.assertNotIn("changed definition", json.dumps(status, ensure_ascii=False))

                    restarted_runner = HypitFlowRunner(
                        load_canvas=lambda _canvas_id: copy.deepcopy(canvas), storage=storage,
                        prepare_node_request=main.studio_hypit_prepare_node_request,
                        preflight_node=preflight, execute_node=execute, collect_results=collect,
                        notify=lambda *_args: None, lock=threading.RLock(), now_ms=lambda: 2,
                        canvas_id=canvas_id, module_id=module_id,
                    )
                    self.assertEqual(restarted_runner.get(submitted["run_id"])["status"], "succeeded")
                    replay = await restarted_runner.submit(
                        "image", "output-image", "accepted-schema-op", payload, test=False,
                        trusted_context=trusted_context,
                    )
                    self.assertEqual(replay["run_id"], submitted["run_id"])
                    self.assertEqual(executed, ["source", "consumer"], "recovery must not resubmit provider work")

    async def _run_dynamic_app_chain(self, upstream_kind):
        temp_root_base = ROOT / "cache" / "studio-tests" / "tmp"
        temp_root_base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="hypit-dynamic-app-", dir=temp_root_base) as temp_root:
            storage = ProjectStorage(Path(temp_root))
            storage.ensure_layout()
            source_fields = [{
                "nodeId": "source-node", "fieldName": "prompt", "fieldType": "STRING",
                "required": True, "defaultValue": "fixture input",
            }]
            consumer_fields = [{
                "nodeId": "consumer-node", "fieldName": "video", "fieldType": "VIDEO",
                "required": True,
            }]

            def app_node(node_id, app_id, fields, *, output_kind=""):
                return {
                    "id": node_id, "type": "smart-ai-app", "title": node_id,
                    "outputKind": output_kind,
                    "runSettings": {
                        "rhMode": "app", "rhConfigKey": f"app:{app_id}", "rhAppId": app_id,
                        "rhRegion": "global", "rhFields": copy.deepcopy(fields),
                    },
                    "images": [],
                }

            canvas = {
                "id": "hypit-settings", "revision": 1, "nodes": [
                    app_node("source", "source-app", source_fields, output_kind="text"),
                    app_node("consumer", "consumer-app", consumer_fields),
                    {"id": "output-image", "type": "smart-hypit-output", "hypitSlot": "image"},
                ],
                "connections": [
                    {"from": "source", "to": "consumer", "kind": "input"},
                    {"from": "consumer", "to": "output-image", "kind": "input"},
                ],
            }
            execution_calls = []
            prepared = []

            def resolve_fields(app_id, node, _canvas):
                return {"fields": copy.deepcopy(node["runSettings"]["rhFields"])}

            async def fake_app_preflight(_canvas, node, request, _request_id, *, record_run=True):
                del record_run
                prepared.append((node["id"], copy.deepcopy(request)))
                for field in request.get("fields") or []:
                    if field.get("required") is not True:
                        continue
                    key = f"{field.get('nodeId', '')}::{field.get('fieldName', '')}"
                    if not request.get("app_field_values", {}).get(key):
                        raise ValueError(f"缺少必填输入：{key}")
                return {"network_requested": False}

            async def execute(_canvas, node, request, _request_id, _resolved, _on_submitted):
                execution_calls.append(node["id"])
                if node["id"] == "consumer":
                    self.assertTrue(request["app_field_values"].get("consumer-node::video"))
                    return {"fixture_kind": "image"}
                return {"fixture_kind": upstream_kind}

            async def collect(result, _request, task):
                kind = result["fixture_kind"]
                extension = {"image": ".png", "video": ".mp4", "audio": ".wav", "text": ".txt"}[kind]
                output_dir = Path(temp_root) / "generated"
                output_dir.mkdir(parents=True, exist_ok=True)
                source = output_dir / f"{task['id']}-{kind}{extension}"
                source.write_bytes(b"isolated dynamic result")
                item = storage.store_result_file(source, source.name)
                return [{"kind": kind, "url": item["url"], "resultId": item["id"], "name": item["display_name"]}]

            async def no_op(*_args):
                return None

            runner = HypitFlowRunner(
                load_canvas=lambda _canvas_id: copy.deepcopy(canvas), storage=storage,
                prepare_node_request=main.studio_hypit_prepare_node_request,
                preflight_node=main.studio_hypit_preflight_node, execute_node=execute,
                collect_results=collect, notify=no_op, lock=threading.RLock(), now_ms=lambda: 1,
            )
            with mock.patch.object(main.STUDIO_APP_EXECUTION, "resolve_runninghub_fields", side_effect=resolve_fields), \
                 mock.patch.object(main, "studio_app_preflight", side_effect=fake_app_preflight):
                submitted = await runner.submit("image", "output-image", f"dynamic-{upstream_kind}", {"base_revision": 1}, test=True)
                await asyncio.wait_for(runner._active[submitted["run_id"]], timeout=5)
                status = runner.get(submitted["run_id"])

            return status, execution_calls, prepared

    async def test_dynamic_app_output_type_is_checked_only_after_runtime_result(self):
        video_status, video_calls, video_preflights = await self._run_dynamic_app_chain("video")
        self.assertEqual(video_status["status"], "succeeded", video_status)
        self.assertEqual(video_calls, ["source", "consumer"])
        preflight_placeholder = next(
            request for node_id, request in video_preflights
            if node_id == "consumer" and str(request.get("app_field_values", {}).get("consumer-node::video", "")).startswith("hypit-preflight://")
        )
        self.assertEqual(preflight_placeholder["app_field_values"]["consumer-node::video"],
                         "hypit-preflight://dynamic-upstream/consumer-node::video")

        image_status, image_calls, _ = await self._run_dynamic_app_chain("image")
        self.assertEqual(image_status["status"], "failed")
        self.assertEqual(image_calls, ["source"])
        self.assertIn("缺少必填输入", image_status["error"])

    async def test_private_comfy_adapter_passes_snapshot_graph_without_legacy_mutation(self):
        graph = {
            "23": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "fixture.safetensors"}},
            "144": {"class_type": "Resize", "inputs": {"width": 512, "height": 640}},
            "22": {"class_type": "Seed", "inputs": {"seed": 41}},
        }
        captured = {}

        def fake_generate(req, *, trusted_workflow_snapshot=None):
            captured["params"] = copy.deepcopy(req.params)
            captured["graph"] = copy.deepcopy(trusted_workflow_snapshot)
            return {"items": [{"url": "/api/results/image.png", "kind": "image"}]}

        adapter_request = {
            "kind": "comfy", "workflow_fields": [], "workflow_values": {}, "params": {"7": {"steps": 19}},
            "references": [], "platform_request": {
                "prompt": "", "workflow_json": "custom/fixture.json", "params": {"7": {"steps": 19}},
                "type": "hypit-image", "client_id": "fixture-request",
            },
            "_hypit_execution_snapshot": {"workflow_json": graph},
        }
        with mock.patch.object(main, "generate_request", side_effect=fake_generate):
            await main.STUDIO_APP_EXECUTION._generate(adapter_request)
        self.assertEqual(captured["graph"], graph)
        self.assertEqual(captured["params"], {"7": {"steps": 19}})
        self.assertNotIn("prompt", captured["params"].get("23", {}))
        self.assertNotIn("width", captured["params"].get("144", {}))

    async def test_real_strict_runninghub_query_projection_preserves_mixed_types(self):
        raw = {"code": 0, "data": [
            {"fileUrl": "https://fixture.invalid/no-extension", "name": "opaque"},
            {"fileUrl": "https://fixture.invalid/image", "fileType": "application/octet-stream"},
            {"fileUrl": "https://fixture.invalid/video", "fileType": "video/mp4"},
        ]}

        class Response:
            status_code = 200

            def json(self):
                return copy.deepcopy(raw)

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                return Response()

        async def fake_store(_client, remote, *, strict=False, return_metadata=False):
            self.assertTrue(strict)
            self.assertTrue(return_metadata)
            index = "opaque" if "no-extension" in remote else "image" if remote.endswith("/image") else "video"
            content_type = "image/png" if index == "image" else "application/octet-stream"
            return (f"/api/results/{index}.bin", content_type)

        with mock.patch.object(main.httpx, "AsyncClient", Client), \
             mock.patch.object(main, "runninghub_provider", return_value={"id": "runninghub", "base_url": "https://fixture.invalid"}), \
             mock.patch.object(main, "runninghub_api_key", return_value="fixture-only"), \
             mock.patch.object(main, "runninghub_endpoint_url", return_value="https://fixture.invalid/query"), \
             mock.patch.object(main, "runninghub_app_headers", return_value={}), \
             mock.patch.object(main, "runninghub_store_remote_output", side_effect=fake_store):
            query = await main._runninghub_query("fixture-task", region="global", strict=True)

        projected = studio_app_execution._normalize_runninghub_result(query, strict=True)
        self.assertEqual(len(projected["images"]), 1)
        self.assertEqual(len(projected["videos"]), 1)
        self.assertEqual(len(projected["files"]), 1)
        validated = studio_hypit_models._validate_workflow_result("image", projected)
        self.assertEqual(len(validated["images"]), 1)
        self.assertNotIn("videos", validated)
        self.assertNotIn("files", validated)

    async def test_comfy_result_unknown_bucket_is_strictly_rejected(self):
        snapshot = {"workflow_json": {"1": {"class_type": "fixture", "inputs": {}}}, "fields": []}
        request = {
            "source": "local_comfy_workflow", "expected_slot": "image", "expected_kind": "image",
            "field_values": {}, "references": [], "comfy_params": {},
        }
        with mock.patch.object(main.STUDIO_APP_EXECUTION, "_generate", new=mock.AsyncMock(return_value={
            "images": [{"url": "https://fixture.invalid/result?id=unknown"}], "items": [],
        })):
            result = await main.studio_hypit_generate_workflow(request, snapshot)
        self.assertEqual(len(result["files"]), 1)
        with self.assertRaisesRegex(RuntimeError, "未返回可确认的 image"):
            studio_hypit_models._validate_workflow_result("image", result)

    async def test_main_callbacks_run_text_to_image_through_real_shared_collector_in_isolated_storage(self):
        """真实 main 请求/收集回调只写入外接盘测试 ProjectStorage。"""
        cache_tmp = ROOT / "cache" / "studio-tests" / "tmp"
        cache_tmp.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="hypit-main-collector-", dir=cache_tmp) as temp_root:
            storage = ProjectStorage(temp_root)
            storage.ensure_layout()
            canvas = {
                "id": "hypit-settings", "title": "隔离纵切", "kind": "smart", "revision": 3,
                "hypit_flow_schema_version": 1, "hypit_legacy_migration_done": True,
                "nodes": [
                    {"id": "text-step", "type": "smart-text-generator", "title": "上游文本",
                     "promptDraftText": "写一段场景描述",
                     "runSettings": {"textProvider": "fixture-provider", "textModel": "text-model"}},
                    {"id": "image-step", "type": "smart-image-generator", "title": "下游图片",
                     "promptDraftText": "把上游文字画成图片",
                     "runSettings": {"provider_id": "fixture-provider", "model": "image-model"}},
                    {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image",
                     "outputKind": "image"},
                ],
                "connections": [
                    {"from": "text-step", "to": "image-step", "kind": "input"},
                    {"from": "image-step", "to": "image-output", "kind": "input"},
                ],
            }
            preflight_calls = []
            generation_calls = []

            actual_canvas_preflight_impl = main._canvas_preflight_impl

            async def observe_canvas_preflight_impl(payload, **kwargs):
                preflight_calls.append(payload)
                return await actual_canvas_preflight_impl(payload, **kwargs)

            async def fake_generate(request):
                generation_calls.append(copy.deepcopy(request))
                if request["kind"] == "text":
                    return {"text": "一间被午后阳光照亮的画室"}
                if request["kind"] != "image":
                    raise AssertionError(f"unexpected fake generation kind: {request['kind']}")
                self.assertIn("一间被午后阳光照亮的画室", request["prompt"])
                fixture_dir = Path(temp_root) / "fixture-results"
                fixture_dir.mkdir(parents=True, exist_ok=True)
                source = fixture_dir / "canvas-result.png"
                source.write_bytes(b"isolated image bytes")
                stored = storage.store_result_file(source, "canvas-result.png")
                return {"images": [{"kind": "image", "url": stored["url"], "mime_type": "image/png"}]}

            async def no_op_notify(*_args):
                return None

            runner = HypitFlowRunner(
                load_canvas=lambda canvas_id: copy.deepcopy(canvas) if canvas_id == "hypit-settings" else None,
                storage=storage,
                prepare_node_request=main.studio_hypit_prepare_node_request,
                preflight_node=main.studio_hypit_preflight_node,
                execute_node=main.studio_hypit_execute_node,
                collect_results=main.studio_hypit_collect_results,
                notify=no_op_notify,
                lock=threading.RLock(),
                now_ms=lambda: 1,
            )
            fake_service = mock.Mock()
            fake_service.ensure_canvas.return_value = copy.deepcopy(canvas)
            # 预检经由 get_api_provider() 读取 API 设置。用明确启用的
            # 内存平台隔离它，避免 CI 回退到默认 RunningHub 站点状态。
            fixture_provider = {
                "id": "fixture-provider", "name": "隔离测试平台", "protocol": "openai",
                "enabled": True, "base_url": "https://fixture.invalid/v1",
                "image_models": ["image-model"], "chat_models": ["text-model"],
                "video_models": [], "audio_models": [], "disabled_model_options": [],
            }
            profile = {
                "provider_id": "fixture-provider", "model_id": "image-model", "operation": "text_to_image", "runnable": True,
                "readiness": "ready", "selectable": True, "validation_mode": "strict",
                "parameters": {},
                "inputs": {"prompt": {"media_type": "text", "role": "prompt", "min": 1}},
            }

            with mock.patch.object(main, "PROJECT_STORAGE", storage), \
                 mock.patch.object(main, "HYPIT_SETTINGS_CANVAS_SERVICE", fake_service), \
                 mock.patch.object(main, "HYPIT_FLOW_RUNNER", runner), \
                 mock.patch.object(main, "_canvas_preflight_impl", side_effect=observe_canvas_preflight_impl), \
                 mock.patch.object(main, "load_api_providers", return_value=[fixture_provider]), \
                 mock.patch.object(main, "canvas_api_providers", return_value=[fixture_provider]), \
                 mock.patch.object(main.MODEL_CAPABILITY_REGISTRY, "find_model", return_value=profile), \
                 mock.patch.object(main.studio_module_models, "hypit_profile_reasons", return_value=[]), \
                 mock.patch.object(main, "studio_generate", side_effect=fake_generate):
                submitted = await main.studio_hypit_submit_settings_canvas_request(
                    "image", "image-output", "isolated-text-image-op", {"base_revision": 3}, test=True,
                )
                task = runner._active[submitted["run_id"]]
                await asyncio.wait_for(task, timeout=5)
                status = main.studio_hypit_get_settings_canvas_request(submitted["run_id"])

            self.assertEqual(status["status"], "succeeded", status)
            self.assertEqual(status["output_kind"], "image")
            self.assertEqual(len(status["result"]["images"]), 1)
            self.assertEqual(status["result"]["images"][0]["kind"], "image")
            self.assertEqual([call["kind"] for call in generation_calls], ["text", "image"])
            image_call = generation_calls[-1]
            self.assertIn("一间被午后阳光照亮的画室", image_call["prompt"])
            self.assertEqual([call.node_type for call in preflight_calls], [
                "text_generation", "image_generation", "text_generation", "image_generation",
            ])
            self.assertTrue(all(call.provider_id == "fixture-provider" for call in preflight_calls),
                            [call.provider_id for call in preflight_calls])
            self.assertTrue(all(not call.canvas_id and not call.node_id and not call.client_operation_id
                                for call in preflight_calls))
            self.assertEqual(len(storage.list_runs(canvas_id="hypit-settings")), 1)
            run = storage.list_runs(canvas_id="hypit-settings")[0]
            self.assertEqual(run["attempts"][-1]["status"], "succeeded")
            self.assertEqual(len(run["attempts"][-1].get("result_ids") or []), 2)
            result_records = storage.list_results()
            self.assertEqual({item["kind"] for item in result_records}, {"text", "image"})
            self.assertTrue(all(storage.result_path(item["id"]).is_file() for item in result_records))
            self.assertTrue(all(Path(storage.result_path(item["id"])).is_relative_to(Path(temp_root))
                                for item in result_records))


if __name__ == "__main__":
    unittest.main()
