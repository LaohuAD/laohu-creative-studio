"""全局模型清单与无输出端口设置画布的隔离回归。"""
from __future__ import annotations

import copy
import ast
import asyncio
import contextvars
import hashlib
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from model_capabilities import ModelCapabilityError, ModelCapabilityRegistry
from model_capabilities import generation_visibility_issue
import studio_model_selection
from canvas_core.json_store import DataFileError, write_json as atomic_write_json
from studio_canvas_settings import (
    CANVAS_SETTINGS_CANVAS_ID,
    CANVAS_SETTINGS_CANVAS_URL,
    CanvasSettingsService,
    create_canvas_settings_router,
)
from studio_module_models import select_options_for_slot


ROOT = Path(__file__).resolve().parents[1]


class CanvasSettingsManagementTests(unittest.TestCase):
    def make_service(self, state=None):
        state = state if state is not None else {"canvases": {}, "broadcasts": []}
        lock = threading.RLock()

        def load_canvas(canvas_id):
            canvas = state["canvases"].get(canvas_id)
            if canvas is None:
                raise HTTPException(status_code=404, detail="not found")
            return copy.deepcopy(canvas)

        def save_canvas(canvas, *, increment_revision=True, touch_updated_at=True):
            previous = state["canvases"].get(canvas["id"])
            saved = copy.deepcopy(canvas)
            if previous and increment_revision:
                saved["revision"] = int(previous["revision"]) + 1
            if previous and not touch_updated_at:
                saved["updated_at"] = previous["updated_at"]
            elif previous and touch_updated_at:
                saved["updated_at"] = int(previous["updated_at"]) + 1
            state["canvases"][saved["id"]] = copy.deepcopy(saved)
            return saved

        service = CanvasSettingsService(
            load_canvas=load_canvas,
            save_canvas=save_canvas,
            lock=lock,
            validate_canvas=lambda canvas: self.assertEqual(canvas["id"], CANVAS_SETTINGS_CANVAS_ID),
            broadcast_canvas_updated=lambda *args: state["broadcasts"].append(args),
            now_ms=lambda: 1791158400000,
        )
        return service, state

    def _actual_reset_option(self):
        """用公开严格能力档案取得精确 option，避免虚构布局身份键。"""
        from tests.provider_fixture import configured_providers

        registry = ModelCapabilityRegistry(ROOT)
        catalog = registry.build_catalog(configured_providers())
        options = studio_model_selection.compile_catalog_options(catalog)
        option = next((item for item in options if (
            item.get("connection_id") == "ai-money"
            and item.get("catalog_model_id") == "laohu-image-g-v2.5-flare"
            and item.get("node_type") == "image_generation"
            and item.get("operation") == "text_or_reference_to_image"
        )), None)
        self.assertIsNotNone(option, "测试应能从公开能力档案解析真实选项")
        self.assertEqual(option.get("validation_mode"), "strict")
        self.assertEqual(option.get("readiness"), "ready")
        self.assertTrue(option.get("runnable"))
        return option

    def _personalization_functions(self, path):
        """仅执行 main.py 中真实个性化函数，避免导入时初始化生产存储。"""
        source = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        names = {
            "validate_smart_canvas_personalization",
            "merge_smart_canvas_personalization",
            "reset_smart_canvas_presentation_preferences",
            "get_smart_canvas_personalization",
            "put_smart_canvas_personalization",
            "reset_smart_canvas_personalization",
        }
        functions = [
            node for node in source.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
        ]
        self.assertEqual({node.name for node in functions}, names)
        for node in functions:
            # 只移除路由注册装饰器；函数体仍直接取自 main.py。
            node.decorator_list = []

        from canvas_core.json_store import DataFileError, read_json, write_json

        reset_option = self._actual_reset_option()
        namespace = {
            "copy": copy,
            "Path": Path,
            "HTTPException": HTTPException,
            "DataFileError": DataFileError,
            "read_json_file": read_json,
            "atomic_write_json": write_json,
            "SMART_CANVAS_PERSONALIZATION_PATH": str(path),
            "CANVAS_LOCK": threading.RLock(),
            "_build_model_management_catalog": lambda: {"options": [reset_option]},
            "_SMART_CANVAS_PERSONALIZATION_MAPS": (
                "executionLayouts", "parameterOptionOrder", "modelOrder", "parameterPresentation",
            ),
        }
        module = ast.Module(body=functions, type_ignores=[])
        exec(compile(module, str(ROOT / "main.py"), "exec"), namespace)
        namespace["_reset_test_option"] = reset_option
        return namespace

    def test_personalization_default_and_partial_put_preserve_existing_history(self):
        with tempfile.TemporaryDirectory(
            prefix="canvas-personalization-", dir=ROOT / "cache" / "studio-tests" / "tmp"
        ) as directory:
            path = Path(directory) / "smart_canvas_personalization.json"
            scope = self._personalization_functions(path)
            defaults = asyncio.run(scope["get_smart_canvas_personalization"]())
            self.assertEqual(defaults, {
                "version": 1, "executionLayouts": {}, "parameterOptionOrder": {},
                "modelOrder": {}, "parameterPresentation": {},
            })

            prior = {
                "version": 1,
                "executionLayouts": {"image_generation::fixture": {"collapsed": True}},
                "parameterOptionOrder": {"image_generation::fixture::quality": ["high", "standard"]},
                "modelOrder": {"picker::family": ["option-a", "option-b"]},
                "parameterPresentation": {
                    "option-a": {"quality": {"visible": True, "width": "half", "order": 1}},
                },
                "legacyDisplayHint": {"source": "older-client", "value": [1, "kept"]},
            }
            path.write_text(json.dumps(prior), encoding="utf-8")
            result = asyncio.run(scope["put_smart_canvas_personalization"]({
                "version": 1,
                "modelOrder": {"picker::platform": ["fixture-provider"]},
                "parameterPresentation": {
                    "option-b": {"width": {"visible": True, "width": "full", "order": 0}},
                },
            }))
            self.assertEqual(result, {"ok": True})
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["version"], 1)
            self.assertEqual(saved["reset_epoch"], 0)
            self.assertEqual(saved["executionLayouts"], prior["executionLayouts"])
            self.assertEqual(saved["parameterOptionOrder"], prior["parameterOptionOrder"])
            self.assertEqual(saved["modelOrder"], {
                **prior["modelOrder"], "picker::platform": ["fixture-provider"],
            })
            self.assertEqual(saved["parameterPresentation"], {
                "option-a": {"quality": {"width": "half", "order": 1}},
                "option-b": {"width": {"width": "full", "order": 0}},
            })
            self.assertEqual(saved["legacyDisplayHint"], prior["legacyDisplayHint"])
            self.assertNotIn("default", json.dumps(saved["parameterPresentation"]))

    def test_personalization_reset_clears_only_requested_display_scope(self):
        with tempfile.TemporaryDirectory(
            prefix="canvas-personalization-reset-", dir=ROOT / "cache" / "studio-tests" / "tmp"
        ) as directory:
            path = Path(directory) / "smart_canvas_personalization.json"
            scope = self._personalization_functions(path)
            option = scope["_reset_test_option"]
            option_id = option["option_id"]
            node_type = option["node_type"]
            provider_id = option["connection_id"]
            family_id = option["canonical_family_id"]
            model_id = option["catalog_model_id"]
            layout_key = "::".join((node_type, provider_id, family_id, model_id))
            parameter_prefix = f"parameter-options::{layout_key}::"
            original = {
                "version": 1,
                "executionLayouts": {
                    layout_key: {"mode": "grid"},
                    "video_generation::fixture-provider::other-family::other-model": {"mode": "list"},
                },
                "parameterOptionOrder": {
                    f"{parameter_prefix}quality": ["high", "standard"],
                    "parameter-options::image_generation::fixture-provider::other-family::other-model::quality": ["low"],
                    "other-scope": ["untouched"],
                },
                "modelOrder": {
                    f"families::{node_type}": [family_id],
                    f"platforms::{node_type}": [provider_id],
                    f"variants::{node_type}::{family_id}": [option_id],
                    f"families::{node_type}::{provider_id}": [family_id],
                    f"families::{node_type}::another-provider": ["another-family"],
                    "families::video_generation": ["other-family"],
                    "other-scope": ["untouched"],
                },
                "parameterPresentation": {
                    option_id: {"quality": {"visible": False, "width": "half", "order": 1}},
                    "other-option": {"quality": {"width": "full", "order": 0}},
                },
                "legacyDisplayHint": {"keep": True},
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            # 读取旧 visible:false 时回传可布局偏好，但不回传隐藏能力；读取不改磁盘。
            before_read = path.read_bytes()
            visible = asyncio.run(scope["get_smart_canvas_personalization"]())
            self.assertNotIn("visible", visible["parameterPresentation"][option_id]["quality"])
            self.assertEqual(path.read_bytes(), before_read)

            response = asyncio.run(scope["reset_smart_canvas_personalization"]({
                "scope": "node", "option_id": option_id, "node_type": node_type,
            }))
            self.assertTrue(response["ok"])
            reset = response["personalization"]
            self.assertNotIn(option_id, reset["parameterPresentation"])
            self.assertEqual(reset["parameterPresentation"]["other-option"], {"quality": {"width": "full", "order": 0}})
            self.assertEqual(reset["parameterOptionOrder"], {
                "parameter-options::image_generation::fixture-provider::other-family::other-model::quality": ["low"],
                "other-scope": ["untouched"],
            })
            self.assertEqual(reset["executionLayouts"], {
                "video_generation::fixture-provider::other-family::other-model": {"mode": "list"},
            })
            self.assertEqual(reset["modelOrder"], {
                "families::video_generation": ["other-family"],
                "other-scope": ["untouched"],
            })
            self.assertEqual(reset["legacyDisplayHint"], {"keep": True})

            all_response = asyncio.run(scope["reset_smart_canvas_personalization"]({"scope": "all"}))
            all_reset = all_response["personalization"]
            self.assertEqual(all_reset["reset_epoch"], 2)
            self.assertEqual({key: all_reset[key] for key in (
                "executionLayouts", "parameterOptionOrder", "modelOrder", "parameterPresentation",
            )}, {key: {} for key in (
                "executionLayouts", "parameterOptionOrder", "modelOrder", "parameterPresentation",
            )})
            self.assertEqual(all_reset["legacyDisplayHint"], {"keep": True})

    def test_personalization_reset_epoch_rejects_stale_put_without_resurrecting_preferences(self):
        with tempfile.TemporaryDirectory(
            prefix="canvas-personalization-reset-epoch-", dir=ROOT / "cache" / "studio-tests" / "tmp"
        ) as directory:
            path = Path(directory) / "smart_canvas_personalization.json"
            scope = self._personalization_functions(path)
            initial = {
                "version": 1,
                "reset_epoch": 0,
                "executionLayouts": {},
                "parameterOptionOrder": {},
                "modelOrder": {"families::image_generation": ["fixture-family"]},
                "parameterPresentation": {
                    "exact-option": {"quality": {"width": "half", "order": 0}},
                },
            }
            path.write_text(json.dumps(initial), encoding="utf-8")

            reset = asyncio.run(scope["reset_smart_canvas_personalization"]({"scope": "all"}))
            self.assertEqual(reset["personalization"]["reset_epoch"], 1)
            after_reset = path.read_bytes()

            # 浏览器在重置前打开，旧完整PUT和旧客户端缺少epoch的PUT都不得恢复旧排序。
            for stale_payload in (
                initial,
                {key: value for key, value in initial.items() if key != "reset_epoch"},
            ):
                with self.subTest(payload_has_epoch="reset_epoch" in stale_payload):
                    with self.assertRaises(HTTPException) as stale:
                        asyncio.run(scope["put_smart_canvas_personalization"](stale_payload))
                    self.assertEqual(stale.exception.status_code, 409)
                    self.assertEqual(stale.exception.detail["reset_epoch"], 1)
                    self.assertEqual(path.read_bytes(), after_reset)

            fresh_payload = {
                "version": 1,
                "reset_epoch": 1,
                "executionLayouts": {},
                "parameterOptionOrder": {},
                "modelOrder": {"families::video_generation": ["fresh-family"]},
                "parameterPresentation": {},
            }
            saved = asyncio.run(scope["put_smart_canvas_personalization"](fresh_payload))
            self.assertEqual(saved, {"ok": True})
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["reset_epoch"], 1)
            self.assertNotIn("families::image_generation", persisted["modelOrder"])
            self.assertEqual(persisted["modelOrder"]["families::video_generation"], ["fresh-family"])

    def test_personalization_node_reset_rejects_mismatched_identity_without_writing(self):
        with tempfile.TemporaryDirectory(
            prefix="canvas-personalization-reset-identity-", dir=ROOT / "cache" / "studio-tests" / "tmp"
        ) as directory:
            path = Path(directory) / "smart_canvas_personalization.json"
            scope = self._personalization_functions(path)
            option = scope["_reset_test_option"]
            option_id = option["option_id"]
            original = {"version": 1, "executionLayouts": {}, "parameterOptionOrder": {},
                        "modelOrder": {}, "parameterPresentation": {option_id: {"quality": {"width": "half"}}}}
            path.write_text(json.dumps(original), encoding="utf-8")
            before = path.read_bytes()
            with self.assertRaises(HTTPException) as error:
                asyncio.run(scope["reset_smart_canvas_personalization"]({
                    "scope": "node", "option_id": option_id, "node_type": "video_generation",
                }))
            self.assertEqual(error.exception.status_code, 400)
            self.assertEqual(path.read_bytes(), before)

    def test_personalization_unknown_or_corrupt_stored_version_blocks_reads_and_writes(self):
        with tempfile.TemporaryDirectory(
            prefix="canvas-personalization-invalid-", dir=ROOT / "cache" / "studio-tests" / "tmp"
        ) as directory:
            path = Path(directory) / "smart_canvas_personalization.json"
            scope = self._personalization_functions(path)
            for raw in (
                b'{"version":2,"modelOrder":{}}',
                b'{"version":true,"modelOrder":{}}',
                b'{"version":1,"reset_epoch":-1}',
                b'{"version":1,"reset_epoch":true}',
                b'{"version":1,"parameterPresentation":[]} ',
                b'{not-json',
            ):
                with self.subTest(raw=raw):
                    path.write_bytes(raw)
                    with self.assertRaises(HTTPException) as get_error:
                        asyncio.run(scope["get_smart_canvas_personalization"]())
                    self.assertEqual(get_error.exception.status_code, 500)
                    with self.assertRaises(HTTPException) as put_error:
                        asyncio.run(scope["put_smart_canvas_personalization"]({"version": 1, "modelOrder": {}}))
                    self.assertEqual(put_error.exception.status_code, 500)
                    with self.assertRaises(HTTPException) as reset_error:
                        asyncio.run(scope["reset_smart_canvas_personalization"]({"scope": "all"}))
                    self.assertEqual(reset_error.exception.status_code, 500)
                    self.assertEqual(path.read_bytes(), raw, "拒绝损坏/未知版本时必须保留原始字节")

    def test_personalization_rejects_values_that_would_change_parameter_contract(self):
        with tempfile.TemporaryDirectory(
            prefix="canvas-personalization-contract-", dir=ROOT / "cache" / "studio-tests" / "tmp"
        ) as directory:
            path = Path(directory) / "smart_canvas_personalization.json"
            scope = self._personalization_functions(path)
            original = {
                "version": 1, "executionLayouts": {}, "parameterOptionOrder": {},
                "modelOrder": {}, "parameterPresentation": {},
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            before = path.read_bytes()
            with self.assertRaises(HTTPException) as error:
                asyncio.run(scope["put_smart_canvas_personalization"]({
                    "version": 1,
                    "parameterPresentation": {
                        "option-a": {"quality": {
                            "visible": False, "width": "half", "order": 2,
                            "default": "high", "options": ["high"],
                        }},
                    },
                }))
            self.assertEqual(error.exception.status_code, 400)
            self.assertEqual(path.read_bytes(), before)

    def test_settings_canvas_reset_only_clears_its_own_graph(self):
        state = {
            "canvases": {
                "ordinary-project": {"id": "ordinary-project", "nodes": [{"id": "keep"}]},
            },
            "providers": [{
                "id": "fixture-api", "enabled": True, "api_key": "fixture-secret",
                "image_models": ["fixture-image"], "chat_models": [],
            }],
            "personalization": {
                "modelOrder": {"image_generation": ["fixture-image"]},
                "parameterPresentation": {"fixture-image": {"quality": {"visible": False, "width": "half"}}},
            },
            "inflight": [{"id": "fixture-task", "provider_id": "fixture-api", "model_id": "fixture-image"}],
            "media": [{"id": "fixture-result", "path": "assets/output/image/fixture.png"}],
            "broadcasts": [],
        }
        untouched = {key: copy.deepcopy(state[key]) for key in ("providers", "personalization", "inflight", "media")}
        service, state = self.make_service(state)
        app = FastAPI()
        app.include_router(create_canvas_settings_router(service))

        with TestClient(app) as client:
            opened = client.get("/api/studio/canvas/settings-canvas")
            self.assertEqual(opened.status_code, 200, opened.text)
            self.assertEqual(opened.json()["id"], "canvas-settings")
            self.assertEqual(opened.json()["url"], CANVAS_SETTINGS_CANVAS_URL)
            blank = opened.json()["canvas"]
            self.assertEqual(blank["nodes"], [])
            self.assertEqual(blank["connections"], [])

            saved = client.post("/api/studio/canvas/settings-canvas/reset", json={
                "base_revision": blank["revision"], "client_id": "settings-tab",
            })
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertTrue(saved.json()["reset"])
            self.assertEqual(saved.json()["canvas"]["nodes"], [])
            self.assertEqual(saved.json()["canvas"]["connections"], [])
            self.assertEqual(saved.json()["canvas"]["revision"], blank["revision"] + 1)

        for key, value in untouched.items():
            self.assertEqual(state[key], value, f"重置配置图不能改动 {key}")
        self.assertEqual(state["canvases"]["ordinary-project"]["nodes"], [{"id": "keep"}])
        self.assertEqual(len(state["broadcasts"]), 1)

    def test_settings_graph_rejects_output_ports_and_stale_reset_keeps_current_graph(self):
        service, state = self.make_service()
        app = FastAPI()

        @app.get("/api/canvases/{canvas_id}")
        async def standard_get(canvas_id):
            if canvas_id != CANVAS_SETTINGS_CANVAS_ID:
                raise HTTPException(status_code=404)
            return {"canvas": service.ensure_canvas()}

        @app.put("/api/canvases/{canvas_id}")
        async def standard_put(canvas_id, payload: dict):
            if canvas_id != CANVAS_SETTINGS_CANVAS_ID:
                raise HTTPException(status_code=404)
            with service.lock:
                current = service.ensure_canvas()
                candidate = service.prepare_update_candidate(current, payload)
                saved = service.save_agent_canvas(candidate)
            return {"canvas": saved}

        app.include_router(create_canvas_settings_router(service))

        with TestClient(app) as client:
            blank = client.get("/api/studio/canvas/settings-canvas").json()["canvas"]
            bad_graph = client.put("/api/canvases/canvas-settings", json={
                "base_revision": blank["revision"],
                "nodes": [{"id": "output", "type": "smart-hypit-output", "hypitSlot": "image"}],
                "connections": [],
            })
            self.assertEqual(bad_graph.status_code, 400, bad_graph.text)

            ordinary_graph = client.put("/api/canvases/canvas-settings", json={
                "base_revision": blank["revision"],
                "nodes": [{"id": "generator", "type": "smart-image-generator"}],
                "connections": [],
            })
            self.assertEqual(ordinary_graph.status_code, 200, ordinary_graph.text)
            current = ordinary_graph.json()["canvas"]
            self.assertEqual(current["nodes"][0]["id"], "generator")

            stale = client.post("/api/studio/canvas/settings-canvas/reset", json={
                "base_revision": current["revision"] - 1,
            })
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(state["canvases"]["canvas-settings"]["revision"], current["revision"])
            self.assertEqual(state["canvases"]["canvas-settings"]["nodes"], current["nodes"])

    def test_management_routes_expose_disabled_runnable_options_but_only_patch_one_option(self):
        service, state = self.make_service()
        fake_key = "fixture-secret-never-return"
        state["providers"] = [{
            "id": "fixture-api", "api_key": fake_key,
            "image_models": ["fixture-image-enabled"], "chat_models": ["fixture-chat"],
        }]
        options = [
            {"option_id": "opt-enabled", "catalog_model_id": "fixture-image-enabled", "enabled": True,
             "readiness": "ready", "runnable": True},
            {"option_id": "opt-disabled", "catalog_model_id": "fixture-image-disabled", "enabled": False,
             "readiness": "ready", "runnable": True},
        ]
        patch_calls = []
        catalog_revision = "catalog-7"

        def get_catalog():
            # 生产回调只应返回可运行精确选项的脱敏投影；disabled 仍须在管理目录可见。
            return {"options": copy.deepcopy(options), "catalog_revision": catalog_revision,
                    "selection_contract_version": 1}

        def patch_enabled(option_id, enabled, supplied_revision):
            patch_calls.append((option_id, enabled, supplied_revision))
            if supplied_revision != catalog_revision:
                raise HTTPException(status_code=409, detail="模型目录已更新")
            target = next(item for item in options if item["option_id"] == option_id)
            target["enabled"] = enabled
            return {"option_id": option_id, "enabled": enabled,
                    "catalog_revision": "catalog-8"}

        app = FastAPI()
        app.include_router(create_canvas_settings_router(service, get_catalog=get_catalog, patch_enabled=patch_enabled))
        with TestClient(app) as client:
            catalog = client.get("/api/studio/canvas/model-management-catalog")
            self.assertEqual(catalog.status_code, 200, catalog.text)
            self.assertEqual([item["option_id"] for item in catalog.json()["options"]], ["opt-enabled", "opt-disabled"])
            self.assertFalse(catalog.json()["options"][1]["enabled"])
            self.assertNotIn(fake_key, catalog.text)
            self.assertNotIn("api_key", catalog.text)

            enabled = client.patch("/api/studio/canvas/model-enablement", json={
                "option_id": "opt-disabled", "enabled": True, "catalog_revision": "catalog-7",
            })
            self.assertEqual(enabled.status_code, 200, enabled.text)
            self.assertEqual(patch_calls, [("opt-disabled", True, "catalog-7")])
            self.assertEqual(state["providers"][0]["api_key"], fake_key)
            self.assertEqual(state["providers"][0]["chat_models"], ["fixture-chat"])

            before = copy.deepcopy(options)
            invalid = client.patch("/api/studio/canvas/model-enablement", json={
                "option_id": "opt-enabled", "enabled": False, "catalog_revision": "catalog-7",
                "providers": [{"id": "fixture-api", "api_key": "attacker-value"}],
            })
            self.assertEqual(invalid.status_code, 400)
            self.assertEqual(options, before)
            self.assertEqual(len(patch_calls), 1)

    def _isolated_registry(self):
        cache_root = ROOT / "cache" / "studio-tests" / "tmp"
        cache_root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="canvas-settings-registry-", dir=cache_root)
        root = Path(temporary.name)
        capability_root = root / "data" / "model_capabilities"
        (capability_root / "providers").mkdir(parents=True)
        models = [
            {
                "model_id": "fixture-chat-a", "node_type": "text_generation", "operation": "chat",
                "status": "confirmed", "readiness": "ready", "validation_mode": "strict",
                "runnable": True, "selectable": True, "evidence_level": "official_documented",
                "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
                "output": {"media_type": "text", "min": 1, "max": 1}, "parameters": {},
                "request_mapping": {"prompt": "messages"},
            },
            {
                "model_id": "fixture-image", "node_type": "image_generation", "operation": "text_to_image",
                "status": "confirmed", "readiness": "ready", "validation_mode": "strict",
                "runnable": True, "selectable": True, "evidence_level": "official_documented",
                "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
                "output": {"media_type": "image", "min": 1, "max": 1}, "parameters": {},
                "request_mapping": {"prompt": "prompt"},
            },
            {
                "model_id": "fixture-image-upscale", "node_type": "image_generation", "operation": "image_upscale",
                "status": "confirmed", "readiness": "ready", "validation_mode": "strict",
                "runnable": True, "selectable": True, "evidence_level": "official_documented",
                "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
                "output": {"media_type": "image", "min": 1, "max": 1}, "parameters": {},
                "request_mapping": {"prompt": "prompt"},
            },
            {
                # 同一个模型 ID 可提供不同执行操作；管理开关必须按 option_id 精确区分。
                "model_id": "fixture-image", "node_type": "image_generation", "operation": "image_to_image",
                "status": "confirmed", "readiness": "ready", "validation_mode": "strict",
                "runnable": True, "selectable": True, "evidence_level": "official_documented",
                "inputs": {
                    "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
                    "reference": {"media_type": "image", "min": 1, "max": 1, "role": "reference"},
                },
                "output": {"media_type": "image", "min": 1, "max": 1}, "parameters": {},
                "request_mapping": {"prompt": "prompt", "reference": "images"},
            },
        ]
        (capability_root / "registry.json").write_text(json.dumps({
            "schema_version": 1,
            "providers": [{"provider_id": "fixture", "file": "data/model_capabilities/providers/fixture.json"}],
        }), encoding="utf-8")
        (capability_root / "providers" / "fixture.json").write_text(json.dumps({
            "provider_id": "fixture", "models": models,
        }), encoding="utf-8")
        self.addCleanup(temporary.cleanup)
        return ModelCapabilityRegistry(root), root

    def test_enabled_provider_list_is_shared_but_each_module_keeps_its_slot_contract(self):
        registry, root = self._isolated_registry()
        providers = [{
            "id": "fixture", "name": "Fixture", "protocol": "openai", "enabled": True,
            "api_key": "fixture-secret", "chat_models": ["fixture-chat-a"],
            "image_models": ["fixture-image", "fixture-image-upscale"], "video_models": [], "audio_models": [],
        }]
        models = registry.build_catalog(providers)["providers"][0]["models"]
        model_ids = {item["model_id"] for item in models}
        self.assertEqual(model_ids, {"fixture-chat-a", "fixture-image", "fixture-image-upscale"})

        shared_text = {
            ("canvas", "text_generation"), ("hypit", "text"), ("article", "text"),
        }
        for module_id, slot_id in shared_text:
            offered = select_options_for_slot(models, module_id, slot_id)["options"]
            self.assertEqual([item["model_id"] for item in offered], ["fixture-chat-a"])

        image_modules = {
            "canvas": "image_generation", "hypit": "image", "article": "image",
        }
        offered_by_module = {
            module_id: {item["model_id"] for item in select_options_for_slot(models, module_id, slot)["options"]}
            for module_id, slot in image_modules.items()
        }
        self.assertEqual(offered_by_module["canvas"], {"fixture-image", "fixture-image-upscale"})
        self.assertEqual(offered_by_module["article"], offered_by_module["canvas"])
        self.assertEqual(offered_by_module["hypit"], {"fixture-image"},
                         "共享白名单不取消 Hypit 的用途过滤")

        # 模型被停用只改变本次运行允许集；共享能力档案和已接受任务快照仍保留。
        accepted_task = {"provider_id": "fixture", "model_id": "fixture-image", "parameters": {"seed": 17}}
        providers[0]["image_models"].remove("fixture-image")
        self.assertIn("fixture-image", {item["model_id"] for item in registry.load()["profiles"]["fixture"]["models"]})
        self.assertEqual(accepted_task["model_id"], "fixture-image")
        with self.assertRaisesRegex(ModelCapabilityError, "未启用模型"):
            registry.validate_request(
                providers, "fixture", "fixture-image", "image_generation",
                input_counts={"prompt": 1}, input_roles={"prompt": 1}, parameters={},
            )

    def _management_main_functions(self, registry, config_path, providers):
        """执行 main.py 的真实目录、启用写入与校验函数，所有文件路径均指向 fixture。"""
        source = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        names = {
            "model_list_from_values", "normalize_model_option_ids", "laohu_model_list",
            "_management_profile_ready", "_management_profiles_for_scope",
            "_build_model_management_catalog", "build_model_capability_catalog",
            "_disabled_option_ids_for_provider", "_filter_disabled_model_options",
            "_filter_compiled_disabled_options",
            "_read_raw_api_provider_records_locked", "_api_provider_catalog_view",
            "patch_canvas_model_option_enabled", "_guard_disabled_model_option",
            "resolve_model_capability_request", "studio_validate_model",
            "_resolve_model_option_descriptor",
            "_validated_studio_model_context", "_provider_with_validated_model",
        }
        functions = [node for node in source.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
        self.assertEqual({node.name for node in functions}, names)
        for node in functions:
            node.decorator_list = []
        namespace = {
            "copy": copy, "hashlib": hashlib, "json": json, "re": re, "os": __import__("os"), "Path": Path,
            "HTTPException": HTTPException, "DataFileError": DataFileError,
            "ModelCapabilityError": ModelCapabilityError,
            "atomic_write_json": atomic_write_json,
            "MODEL_CAPABILITY_REGISTRY": registry,
            "CANVAS_SETTINGS_CANVAS_ID": CANVAS_SETTINGS_CANVAS_ID,
            "CANVAS_MODEL_MANAGEMENT_HIDDEN_PROVIDER_IDS": {"agnes", "openai-compatible", "modelscope", "volcengine"},
            "NODE_MODEL_FIELDS": {
                "text_generation": "chat_models", "image_generation": "image_models",
                "video_generation": "video_models", "audio_generation": "audio_models",
                "music_generation": "audio_models",
            },
            "studio_model_selection": studio_model_selection,
            "_STUDIO_VALIDATED_MODEL_CONTEXT": contextvars.ContextVar(
                "isolated_studio_validated_model_context", default=None,
            ),
            "generation_visibility_issue": generation_visibility_issue,
            "GLOBAL_CONFIG_LOCK": threading.RLock(),
            "API_PROVIDERS_FILE": str(config_path),
            # 此 fixture 已是 normalize_provider 输出形状；其 API Key 是假值，仅用于确认不会出现在目录。
            "normalize_provider": lambda value: copy.deepcopy(value),
            "model_list_from_values": lambda values: list(dict.fromkeys(
                str(value or "").strip() for value in values or [] if str(value or "").strip()
            )),
            "selected_model": lambda label, value: value,
            "normalize_laohu_model_id": lambda value: str(value or "").strip(),
            "canvas_api_providers": lambda: copy.deepcopy(providers()),
            "load_api_providers": lambda **_kwargs: copy.deepcopy(providers()),
            "runninghub_normalize_region": lambda value, default="global": str(value or default),
        }
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(ROOT / "main.py"), "exec"), namespace)
        return namespace

    def test_real_main_callbacks_first_enable_one_operation_and_block_disabled_preflight(self):
        """真实 main 回调把启用白名单与精确操作停用分开，并限定管理图试跑旁路。"""
        registry, root = self._isolated_registry()
        records = [{
            "id": "fixture", "name": "Fixture", "protocol": "openai", "enabled": True,
            "api_key": "fixture-only-secret", "base_url": "https://fixture.invalid/v1",
            "chat_models": [], "image_models": [], "video_models": [], "audio_models": [],
            "disabled_model_options": [],
        }]
        config_path = root / "api_providers.json"
        config_path.write_text(json.dumps(records), encoding="utf-8")
        namespace = self._management_main_functions(
            registry, config_path, lambda: json.loads(config_path.read_text(encoding="utf-8")),
        )

        initial = namespace["_build_model_management_catalog"](records)
        image_options = [item for item in initial["options"]
                         if item["connection_id"] == "fixture" and item["node_type"] == "image_generation"]
        same_model_options = [item for item in image_options if item["catalog_model_id"] == "fixture-image"]
        self.assertEqual({item["operation"] for item in same_model_options}, {"text_to_image", "image_to_image"}, initial)
        option_a = next(item for item in same_model_options if item["operation"] == "text_to_image")
        option_b = next(item for item in same_model_options if item["operation"] == "image_to_image")
        self.assertFalse(option_a["enabled"])
        self.assertFalse(option_b["enabled"])
        self.assertNotIn("fixture-only-secret", json.dumps(initial))

        result = namespace["patch_canvas_model_option_enabled"](
            option_a["option_id"], True, initial["catalog_revision"],
        )
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["image_models"], ["fixture-image"])
        self.assertTrue(result["enabled"])
        after_first_enable = namespace["_build_model_management_catalog"](saved)
        self.assertTrue(next(item for item in after_first_enable["options"]
                             if item["option_id"] == option_a["option_id"])["enabled"])
        self.assertFalse(next(item for item in after_first_enable["options"]
                              if item["option_id"] == option_b["option_id"])["enabled"],
                         "首次启用 A 不能连带启用 B")

        enabled_b = namespace["patch_canvas_model_option_enabled"](
            option_b["option_id"], True, after_first_enable["catalog_revision"],
        )
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertIn("fixture-image", saved[0]["image_models"])
        disabled_b = namespace["patch_canvas_model_option_enabled"](
            option_b["option_id"], False, enabled_b["catalog_revision"],
        )
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["image_models"], ["fixture-image"])
        self.assertEqual(saved[0]["disabled_model_options"], [option_b["option_id"]])
        self.assertFalse(disabled_b["enabled"])

        active_catalog = namespace["build_model_capability_catalog"](saved)
        active_options = [item for item in active_catalog["options"]
                          if item["catalog_model_id"] == "fixture-image"]
        self.assertIn(option_a["option_id"], {item["option_id"] for item in active_options})
        self.assertNotIn(option_b["option_id"], {item["option_id"] for item in active_options})

        with self.assertRaises(HTTPException) as preflight_error:
            namespace["resolve_model_capability_request"](
                "fixture", "fixture-image", "", "image_generation",
                input_counts={"text": 1, "image": 1},
                input_roles={"prompt": 1, "reference": 1}, parameters={},
                operation="image_to_image", providers=saved, option_id=option_b["option_id"],
            )
        self.assertIn("该精确模型运行模式已在 API 设置中停用", str(preflight_error.exception.detail))
        with self.assertRaisesRegex(ValueError, "停用"):
            namespace["studio_validate_model"](
                "image_generation", "fixture", "fixture-image", {},
                canvas_id="ordinary-project", option_id=option_b["option_id"],
                operation="image_to_image",
            )
        profile = namespace["studio_validate_model"](
            "image_generation", "fixture", "fixture-image", {},
            canvas_id="canvas-settings", option_id=option_b["option_id"],
            operation="image_to_image",
        )
        self.assertEqual(profile["operation"], "image_to_image")
        self.assertNotIn("fixture-only-secret", json.dumps(registry.build_catalog(saved)))

    def test_public_management_catalog_covers_active_multimedia_and_dynamic_options_without_input_state(self):
        """公开档案反向核对管理目录，并验证共享音频字段、动态档案及精确启停。"""
        from tests.provider_fixture import configured_providers

        registry = ModelCapabilityRegistry(ROOT)
        providers = copy.deepcopy(configured_providers())
        # 模拟已规范化的 RunningHub 配置：站点启用状态明确，用户启用清单来自公开 fixture。
        # 这里不读取或修改真实 API 配置，也不携带真实凭据。
        runninghub = next(item for item in providers if item["id"] == "runninghub")
        fields = ("image_models", "chat_models", "video_models", "audio_models")
        runninghub["rh_regions"] = {
            "global": {
                "enabled": True,
                **{field: copy.deepcopy(runninghub.get(field) or []) for field in fields},
                "rh_apps": [], "rh_workflows": [],
            },
            "cn": {
                "enabled": False,
                **{field: [] for field in fields},
                "rh_apps": [], "rh_workflows": [],
            },
        }

        with tempfile.TemporaryDirectory(
            prefix="canvas-management-public-catalog-",
            dir=ROOT / "cache" / "studio-tests" / "tmp",
        ) as directory:
            config_path = Path(directory) / "api_providers.json"
            config_path.write_text(json.dumps(providers), encoding="utf-8")
            namespace = self._management_main_functions(
                registry, config_path,
                lambda: json.loads(config_path.read_text(encoding="utf-8")),
            )

            # 直接执行 main.py 的生产回调；编译能力目录作为正式候选真源，
            # 管理画布只能保留其中当前启用、严格可运行的 option 身份。
            formal = namespace["build_model_capability_catalog"](providers)["options"]
            # 正式编译目录可能保留隐藏 provider 或资料不完整的档案供诊断；管理目录
            # 的比较范围只包含正式入口实际允许的新候选，资格仍按真实投影字段判断。
            hidden_providers = {"agnes", "openai-compatible", "modelscope", "volcengine"}
            eligible_formal = [item for item in formal if (
                item.get("connection_id") not in hidden_providers
                and item.get("validation_mode") == "strict"
                and item.get("readiness") == "ready"
                and item.get("runnable") is True
                and item.get("selectable") is True
                and not item.get("selection_unavailable_reason")
            )]
            formal_by_id = {item["option_id"]: item for item in eligible_formal}
            management = namespace["_build_model_management_catalog"](providers)
            management_by_id = {item["option_id"]: item for item in management["options"]}
            self.assertTrue(formal_by_id, "公开能力档案应生成正式严格候选")
            self.assertLessEqual(
                set(formal_by_id), set(management_by_id),
                "管理目录不能漏掉正式入口中严格可运行候选的精确 option_id；差异示例："
                + repr(sorted(set(formal_by_id) - set(management_by_id))[:8]),
            )

            node_types = (
                "text_generation", "image_generation", "video_generation",
                "audio_generation", "music_generation",
            )
            for node_type in node_types:
                self.assertTrue(
                    any(item["node_type"] == node_type for item in management["options"]),
                    f"公开管理目录缺少 {node_type} 严格候选",
                )
            audio_ids = {
                item["option_id"] for item in management["options"]
                if item["node_type"] == "audio_generation"
            }
            music_ids = {
                item["option_id"] for item in management["options"]
                if item["node_type"] == "music_generation"
            }
            self.assertTrue(audio_ids, "共享 audio_models 字段不能被 music_generation 覆盖")
            self.assertTrue(music_ids, "共享 audio_models 字段也必须保留 music_generation")
            self.assertTrue(audio_ids.isdisjoint(music_ids), "音频与音乐必须保留各自的精确 node_type/option_id")

            # Codex 的 auto 来自运行时动态档案；管理目录需与正式目录使用同一解析器。
            dynamic_text = [
                item for item in management["options"]
                if item["connection_id"] == "codex"
                and item["catalog_model_id"] == "auto"
                and item["node_type"] == "text_generation"
            ]
            self.assertEqual(len(dynamic_text), 1, "管理目录必须包含严格可运行的动态 Codex 档案")
            self.assertIn(dynamic_text[0]["option_id"], formal_by_id)

            # 管理图本身没有输入节点参数；必需参考模式仍列出，但正式验证仍拒绝缺素材。
            reference_option = next((
                item for item in eligible_formal
                if item["node_type"] == "image_generation"
                and any(
                    spec.get("media_type") == "image"
                    and int(spec.get("min") or 0) > 0
                    for spec in (item.get("inputs") or {}).values()
                )
            ), None)
            self.assertIsNotNone(reference_option, "公开严格档案中应有必需图片输入的生成模式")
            self.assertIn(reference_option["option_id"], management_by_id,
                          "无素材管理图仍应浏览到正式候选中的严格参考图模式")
            required_parameters = {
                key: spec.get("default")
                for key, spec in (reference_option.get("parameters") or {}).items()
                if spec.get("required") or str(spec.get("level") or "").lower() == "required"
                if "default" in spec
            }
            with self.assertRaises(ModelCapabilityError):
                registry.validate_request(
                    providers,
                    reference_option["connection_id"],
                    reference_option["catalog_model_id"],
                    reference_option["node_type"],
                    input_counts={"text": 1},
                    input_roles={"prompt": 1},
                    parameters=required_parameters,
                    operation=reference_option.get("operation") or "",
                    endpoint_id=reference_option.get("endpoint_id") or "",
                    region=reference_option.get("region_id") or "",
                )
            registry.validate_request(
                providers,
                reference_option["connection_id"],
                reference_option["catalog_model_id"],
                reference_option["node_type"],
                input_counts={"text": 1, "image": 1},
                input_roles={"prompt": 1, "reference": 1},
                parameters=required_parameters,
                operation=reference_option.get("operation") or "",
                endpoint_id=reference_option.get("endpoint_id") or "",
                region=reference_option.get("region_id") or "",
            )

            # 精确关闭参考图模式后，它仍留在管理目录但退出正式候选；同 ID 多操作
            # 的兄弟隔离由独立 synthetic-registry 用例验证，不假设公开目录一定有兄弟项。
            target = reference_option
            before_ids = set(management_by_id)
            write_result = namespace["patch_canvas_model_option_enabled"](
                target["option_id"], False, management["catalog_revision"],
            )
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            after_management = namespace["_build_model_management_catalog"](saved)
            after_formal = namespace["build_model_capability_catalog"](saved)["options"]
            after_by_id = {item["option_id"]: item for item in after_management["options"]}
            after_formal_ids = {
                item["option_id"] for item in after_formal if (
                    item.get("connection_id") not in hidden_providers
                    and item.get("validation_mode") == "strict"
                    and item.get("readiness") == "ready"
                    and item.get("runnable") is True
                    and item.get("selectable") is True
                    and not item.get("selection_unavailable_reason")
                )
            }
            self.assertEqual(set(after_by_id), before_ids)
            self.assertFalse(after_by_id[target["option_id"]]["enabled"])
            self.assertNotIn(target["option_id"], after_formal_ids)
            self.assertEqual(after_formal_ids, set(formal_by_id) - {target["option_id"]},
                             "关闭一项不能影响其它合格正式候选")
            self.assertTrue(write_result["enabled"] is False)
            retained = after_by_id[target["option_id"]]
            self.assertEqual(
                (retained["catalog_model_id"], retained["node_type"], retained.get("operation")),
                (target["catalog_model_id"], target["node_type"], target.get("operation")),
                "关闭正式候选不能从管理目录移除这条精确共享能力身份",
            )

    def test_runninghub_site_scope_does_not_leak_candidates_when_one_site_is_disabled(self):
        registry, root = self._isolated_registry()
        profile_root = root / "data" / "model_capabilities" / "providers" / "runninghub.json"
        profile_root.write_text(json.dumps({
            "provider_id": "runninghub",
            "models": [
                {
                    "model_id": "fixture-rh-global", "node_type": "image_generation", "operation": "text_to_image",
                    "status": "confirmed", "readiness": "ready", "validation_mode": "strict", "runnable": True,
                    "selectable": True, "evidence_level": "official_documented",
                    "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
                    "output": {"media_type": "image", "min": 1, "max": 1}, "parameters": {},
                    "request_mapping": {"prompt": "prompt"},
                },
                {
                    "model_id": "fixture-rh-cn", "node_type": "image_generation", "operation": "text_to_image",
                    "status": "confirmed", "readiness": "ready", "validation_mode": "strict", "runnable": True,
                    "selectable": True, "evidence_level": "official_documented",
                    "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
                    "output": {"media_type": "image", "min": 1, "max": 1}, "parameters": {},
                    "request_mapping": {"prompt": "prompt"},
                },
            ],
        }), encoding="utf-8")
        providers = [{
            "id": "runninghub", "name": "RunningHub", "protocol": "runninghub", "enabled": True,
            "rh_regions": {
                "global": {"enabled": True, "free_key": "global-fixture-secret", "image_models": ["fixture-rh-global"]},
                "cn": {"enabled": True, "free_key": "cn-fixture-secret", "image_models": ["fixture-rh-cn"]},
            },
        }]
        models = registry.build_catalog(providers)["providers"][0]["models"]
        self.assertEqual({(item["model_id"], item["regions"][0]) for item in models}, {
            ("fixture-rh-global", "global"), ("fixture-rh-cn", "cn"),
        })
        providers[0]["rh_regions"]["cn"]["enabled"] = False
        after = registry.build_catalog(providers)["providers"][0]["models"]
        self.assertEqual({(item["model_id"], item["regions"][0]) for item in after}, {
            ("fixture-rh-global", "global"),
        })
        self.assertEqual(providers[0]["rh_regions"]["cn"]["free_key"], "cn-fixture-secret")
        self.assertNotIn("fixture-secret", json.dumps(after))


if __name__ == "__main__":
    unittest.main()
