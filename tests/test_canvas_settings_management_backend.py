import copy
import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from studio_canvas_settings import (
    CANVAS_SETTINGS_CANVAS_ID,
    CANVAS_SETTINGS_CANVAS_URL,
    CanvasSettingsService,
    create_canvas_settings_router,
)


class CanvasSettingsManagementBackendTests(unittest.TestCase):
    def make_service(self, reset_display_preferences=None, lock=None):
        store = {}
        broadcasts = []
        lock = lock or threading.RLock()

        def load_canvas(canvas_id):
            if canvas_id not in store:
                raise HTTPException(status_code=404, detail="not found")
            return copy.deepcopy(store[canvas_id])

        def save_canvas(canvas, *, increment_revision=True, touch_updated_at=True):
            current = store.get(canvas["id"])
            result = copy.deepcopy(canvas)
            if current and increment_revision:
                result["revision"] = current["revision"] + 1
            elif current:
                result["revision"] = current["revision"]
            store[result["id"]] = copy.deepcopy(result)
            return result

        service = CanvasSettingsService(
            load_canvas=load_canvas,
            save_canvas=save_canvas,
            lock=lock,
            validate_canvas=lambda canvas: self.assertEqual(canvas["id"], CANVAS_SETTINGS_CANVAS_ID),
            broadcast_canvas_updated=lambda *args: broadcasts.append(args),
            now_ms=lambda: 1234,
            reset_display_preferences=reset_display_preferences,
        )
        return service, store, broadcasts

    def test_settings_canvas_is_blank_shared_graph_and_reset_is_revision_guarded(self):
        default_preferences = {
            "version": 1,
            "executionLayouts": {},
            "modelOrder": {},
            "parameterOptionOrder": {},
            "parameterPresentation": {},
        }
        service, store, broadcasts = self.make_service(
            reset_display_preferences=lambda: copy.deepcopy(default_preferences),
        )
        app = FastAPI()

        @app.get("/api/canvases/{canvas_id}")
        async def standard_get(canvas_id):
            canvas = service.ensure_canvas()
            if canvas_id != CANVAS_SETTINGS_CANVAS_ID:
                raise HTTPException(status_code=404)
            return {"canvas": canvas}

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
            opened = client.get("/api/studio/canvas/settings-canvas")
            self.assertEqual(opened.status_code, 200, opened.text)
            self.assertEqual(opened.json()["id"], CANVAS_SETTINGS_CANVAS_ID)
            self.assertEqual(opened.json()["url"], CANVAS_SETTINGS_CANVAS_URL)
            initial = opened.json()["canvas"]
            self.assertEqual(initial["nodes"], [])
            self.assertEqual(initial["connections"], [])

            saved = client.put(f"/api/canvases/{CANVAS_SETTINGS_CANVAS_ID}", json={
                "base_revision": initial["revision"],
                "nodes": [{"id": "run-1", "type": "smart-image-generator"}],
                "connections": [],
                "viewport": {"x": 15, "y": 30, "scale": 1},
                "logs": [],
                "settings": {},
            })
            self.assertEqual(saved.status_code, 200, saved.text)
            edited = saved.json()["canvas"]
            self.assertEqual(edited["nodes"][0]["id"], "run-1")

            reset = client.post("/api/studio/canvas/settings-canvas/reset", json={
                "base_revision": edited["revision"],
                "client_id": "tab-a",
            })
            self.assertEqual(reset.status_code, 200, reset.text)
            self.assertTrue(reset.json()["reset"])
            self.assertEqual(reset.json()["canvas"]["nodes"], [])
            self.assertEqual(reset.json()["canvas"]["connections"], [])
            self.assertEqual(reset.json()["canvas"]["revision"], edited["revision"] + 1)
            self.assertTrue(reset.json()["preferences_reset"])
            self.assertEqual(reset.json()["preferences"], default_preferences)
            self.assertEqual(len(broadcasts), 1)

            stale_reset = client.post("/api/studio/canvas/settings-canvas/reset", json={
                "base_revision": edited["revision"],
            })
            self.assertEqual(stale_reset.status_code, 409)
            self.assertEqual(store[CANVAS_SETTINGS_CANVAS_ID]["nodes"], [])

    def test_overall_reset_uses_real_personalization_helper_under_shared_canvas_lock(self):
        import main

        temp_dir = tempfile.TemporaryDirectory(prefix="canvas-reset-prefs-", dir="cache/studio-tests")
        self.addCleanup(temp_dir.cleanup)
        preferences_path = Path(temp_dir.name) / "prefs.json"
        existing_preferences = {
            "version": 1,
            "executionLayouts": {"text::fixture": {"layout": "compact"}},
            "modelOrder": {"families::text_generation": ["family-a"]},
            "parameterOptionOrder": {"parameter-options::text::fixture::model-a::defaults": ["temperature"]},
            "parameterPresentation": {"option-a": {"temperature": {"visible": True, "width": "half", "order": 0}}},
            "extension_metadata": {"keep": True},
        }
        preferences_path.write_text(json.dumps(existing_preferences), encoding="utf-8")
        service, store, broadcasts = self.make_service(
            reset_display_preferences=lambda: main.reset_smart_canvas_presentation_preferences(scope="all"),
            lock=main.CANVAS_LOCK,
        )
        initial = service.ensure_canvas()
        edited = service.save_agent_canvas(service.prepare_update_candidate(initial, {
            "base_revision": initial["revision"],
            "nodes": [{"id": "image-1", "type": "smart-image-generator"}],
            "connections": [],
            "viewport": {"x": 10, "y": 20, "scale": 1.5},
            "logs": [],
            "settings": {"manager": True},
        }))

        with mock.patch.object(main, "SMART_CANVAS_PERSONALIZATION_PATH", str(preferences_path)):
            response = asyncio.run(service.reset_canvas({"base_revision": edited["revision"]}))
            stored_preferences = json.loads(preferences_path.read_text(encoding="utf-8"))

        expected = {
            "version": 1,
            "reset_epoch": 1,
            "executionLayouts": {},
            "modelOrder": {},
            "parameterOptionOrder": {},
            "parameterPresentation": {},
            "extension_metadata": {"keep": True},
        }
        self.assertEqual(stored_preferences, expected)
        self.assertEqual(response["preferences"], expected)
        self.assertEqual(store[CANVAS_SETTINGS_CANVAS_ID]["nodes"], [])
        self.assertEqual(response["canvas"]["viewport"], {"x": 0, "y": 0, "scale": 1})
        self.assertEqual(len(broadcasts), 1)

    def test_overall_reset_checks_revision_before_preferences_then_clears_graph(self):
        display_preferences = {"version": 1, "parameterOptionOrder": {"option-a": ["size"]}}
        events = []
        def reset_preferences():
            events.append("preferences")
            display_preferences.clear()
            display_preferences.update({
                "version": 1,
                "executionLayouts": {},
                "modelOrder": {},
                "parameterOptionOrder": {},
                "parameterPresentation": {},
            })
            return copy.deepcopy(display_preferences)

        service, store, broadcasts = self.make_service(reset_display_preferences=reset_preferences)
        real_save = service._save_canvas

        def observe_save(canvas, **kwargs):
            events.append("canvas")
            return real_save(canvas, **kwargs)

        service._save_canvas = observe_save
        initial = service.ensure_canvas()
        candidate = service.prepare_update_candidate(initial, {
            "base_revision": initial["revision"],
            "nodes": [{"id": "image-1", "type": "smart-image-generator"}],
            "connections": [],
            "viewport": {"x": 30, "y": 50, "scale": 1.2},
            "logs": [],
            "settings": {"draft": True},
        })
        edited = service.save_agent_canvas(candidate)
        events.clear()

        with self.assertRaises(HTTPException) as stale:
            asyncio.run(service.reset_canvas({"base_revision": initial["revision"]}))
        self.assertEqual(stale.exception.status_code, 409)
        self.assertTrue(display_preferences)
        self.assertEqual(store[CANVAS_SETTINGS_CANVAS_ID]["nodes"][0]["id"], "image-1")
        self.assertEqual(events, [])

        response = asyncio.run(service.reset_canvas({
            "base_revision": edited["revision"], "client_id": "reset-tab",
        }))
        self.assertEqual(events, ["preferences", "canvas"])
        self.assertEqual(display_preferences, {
            "version": 1,
            "executionLayouts": {},
            "modelOrder": {},
            "parameterOptionOrder": {},
            "parameterPresentation": {},
        })
        self.assertTrue(response["reset"])
        self.assertEqual(response["canvas"]["nodes"], [])
        self.assertEqual(response["canvas"]["connections"], [])
        self.assertEqual(response["preferences"], display_preferences)
        self.assertTrue(response["preferences_reset"])
        self.assertEqual(len(broadcasts), 1)

    def test_overall_reset_does_not_clear_graph_when_preferences_fail(self):
        def fail_preferences():
            raise HTTPException(status_code=503, detail="展示偏好暂时不可重置")

        service, store, broadcasts = self.make_service(reset_display_preferences=fail_preferences)
        initial = service.ensure_canvas()
        edited = service.save_agent_canvas(service.prepare_update_candidate(initial, {
            "base_revision": initial["revision"],
            "nodes": [{"id": "image-1", "type": "smart-image-generator"}],
            "connections": [],
            "viewport": {"x": 0, "y": 0, "scale": 1},
            "logs": [],
            "settings": {},
        }))

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(service.reset_canvas({"base_revision": edited["revision"]}))
        self.assertEqual(raised.exception.status_code, 503)
        self.assertFalse(raised.exception.detail["preferences_reset"])
        self.assertFalse(raised.exception.detail["canvas_reset"])
        self.assertEqual(store[CANVAS_SETTINGS_CANVAS_ID]["nodes"][0]["id"], "image-1")
        self.assertEqual(broadcasts, [])

    def test_overall_reset_reports_partial_when_graph_save_fails_after_preferences(self):
        display_preferences = {"version": 1, "parameterPresentation": {"option-a": {"prompt": {"visible": True}}}}
        def reset_preferences():
            events.append("preferences")
            display_preferences.clear()
            display_preferences.update({
                "version": 1,
                "executionLayouts": {},
                "modelOrder": {},
                "parameterOptionOrder": {},
                "parameterPresentation": {},
            })
            return copy.deepcopy(display_preferences)

        service, store, broadcasts = self.make_service(reset_display_preferences=reset_preferences)
        events = []
        initial = service.ensure_canvas()
        edited = service.save_agent_canvas(service.prepare_update_candidate(initial, {
            "base_revision": initial["revision"],
            "nodes": [{"id": "image-1", "type": "smart-image-generator"}],
            "connections": [],
            "viewport": {"x": 0, "y": 0, "scale": 1},
            "logs": [],
            "settings": {},
        }))
        real_save = service._save_canvas

        def fail_reset_save(canvas, **kwargs):
            if not canvas.get("nodes") and events:
                events.append("canvas-failed")
                raise OSError("isolated graph write failure")
            return real_save(canvas, **kwargs)

        service._save_canvas = fail_reset_save
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(service.reset_canvas({"base_revision": edited["revision"]}))
        self.assertEqual(raised.exception.status_code, 500)
        self.assertIsInstance(raised.exception.detail, dict)
        self.assertTrue(raised.exception.detail["preferences_reset"])
        self.assertFalse(raised.exception.detail["canvas_reset"])
        self.assertEqual(raised.exception.detail["revision"], edited["revision"])
        self.assertIn("尚未清空", raised.exception.detail["message"])
        self.assertEqual(events, ["preferences", "canvas-failed"])
        self.assertEqual(store[CANVAS_SETTINGS_CANVAS_ID]["nodes"][0]["id"], "image-1")
        self.assertEqual(broadcasts, [])

    def test_management_catalog_and_exact_option_patch_are_server_callbacks(self):
        service, _store, _broadcasts = self.make_service()
        options = [{"option_id": "option-hash", "catalog_model_id": "model-a", "enabled": False}]
        patch_calls = []

        def patch_enabled(option_id, enabled, catalog_revision):
            patch_calls.append((option_id, enabled, catalog_revision))
            return {"option_id": option_id, "enabled": enabled, "catalog_revision": "rev-next"}

        app = FastAPI()
        app.include_router(create_canvas_settings_router(
            service,
            get_catalog=lambda: {"options": options, "catalog_revision": "rev-current", "selection_contract_version": 2},
            patch_enabled=patch_enabled,
        ))
        with TestClient(app) as client:
            catalog = client.get("/api/studio/canvas/model-management-catalog")
            self.assertEqual(catalog.status_code, 200, catalog.text)
            self.assertEqual(catalog.json()["options"], options)
            self.assertEqual(catalog.json()["catalog_revision"], "rev-current")

            updated = client.patch("/api/studio/canvas/model-enablement", json={
                "option_id": "option-hash", "enabled": True, "catalog_revision": "rev-current",
            })
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertEqual(updated.json(), {
                "option_id": "option-hash", "enabled": True, "catalog_revision": "rev-next",
            })
            self.assertEqual(patch_calls, [("option-hash", True, "rev-current")])

    def test_first_enable_keeps_sibling_operations_disabled(self):
        """首次启用模型时，仅开放所选精确运行模式。"""
        import main

        options = [
            {
                "option_id": "image-option-a",
                "connection_id": "fixture-conn",
                "capability_provider_id": "fixture-provider",
                "catalog_model_id": "fixture-image-model",
                "node_type": "image_generation",
                "operation": "text_to_image",
                "region_id": "",
                "profile_revision": "fixture-v1",
                "readiness": "ready",
            },
            {
                "option_id": "image-option-b",
                "connection_id": "fixture-conn",
                "capability_provider_id": "fixture-provider",
                "catalog_model_id": "fixture-image-model",
                "node_type": "image_generation",
                "operation": "image_to_image",
                "region_id": "",
                "profile_revision": "fixture-v1",
                "readiness": "ready",
            },
        ]

        def fake_management_catalog(providers=None):
            provider = next((item for item in (providers or []) if item.get("id") == "fixture-conn"), {})
            enabled_ids = set(provider.get("image_models") or [])
            disabled = set(provider.get("disabled_model_options") or [])
            projected = copy.deepcopy(options)
            for item in projected:
                item["enabled"] = (
                    item["catalog_model_id"] in enabled_ids
                    and item["option_id"] not in disabled
                )
            return {
                "options": projected,
                "catalog_revision": "rev-fixture",
                "selection_contract_version": 2,
            }

        with tempfile.TemporaryDirectory(dir="cache/studio-tests") as directory:
            config_path = Path(directory) / "api_providers.json"
            original_records = [{
                "id": "fixture-conn",
                "name": "Fixture Platform",
                "base_url": "https://fixture.invalid/v1",
                "enabled": True,
                "image_models": [],
                "chat_models": [],
                "video_models": [],
                "audio_models": [],
            }]
            config_path.write_text(json.dumps(original_records), encoding="utf-8")
            with mock.patch.object(main, "API_PROVIDERS_FILE", str(config_path)), mock.patch.object(
                main, "_build_model_management_catalog", side_effect=fake_management_catalog
            ):
                result = main.patch_canvas_model_option_enabled("image-option-a", True, "rev-fixture")

            saved_records = json.loads(config_path.read_text(encoding="utf-8"))
            saved_provider = saved_records[0]
            self.assertEqual(result["enabled"], True)
            self.assertEqual(saved_provider["image_models"], ["fixture-image-model"])
            self.assertEqual(saved_provider["disabled_model_options"], ["image-option-b"])
            projected = fake_management_catalog(main._api_provider_catalog_view(saved_records))
            state_by_option = {item["option_id"]: item["enabled"] for item in projected["options"]}
            self.assertEqual(state_by_option, {"image-option-a": True, "image-option-b": False})

    def test_formal_compiled_options_filter_exact_sibling_option(self):
        """正式候选按稳定 option ID 过滤，同站点同模型的其他 operation 不受牵连。"""
        import main

        options = [
            {"option_id": "same-site-op-a", "connection_id": "runninghub", "region_id": "global",
             "catalog_model_id": "same-model", "node_type": "image_generation", "operation": "text_to_image"},
            {"option_id": "same-site-op-b", "connection_id": "runninghub", "region_id": "global",
             "catalog_model_id": "same-model", "node_type": "image_generation", "operation": "image_to_image"},
            {"option_id": "cn-op-a", "connection_id": "runninghub", "region_id": "cn",
             "catalog_model_id": "same-model", "node_type": "image_generation", "operation": "text_to_image"},
        ]
        providers = [{
            "id": "runninghub", "rh_region": "global", "disabled_model_options": ["legacy-ignore"],
            "rh_regions": {
                "global": {"enabled": True, "disabled_model_options": ["same-site-op-a"]},
                "cn": {"enabled": True, "disabled_model_options": ["cn-op-a"]},
            },
        }]

        filtered = main._filter_compiled_disabled_options(options, providers)

        self.assertEqual([item["option_id"] for item in filtered], ["same-site-op-b"])

    def test_registry_keeps_same_model_operations_and_resolves_each_explicitly(self):
        """同 model/node 多操作同时出现在目录中，显式 operation 决定精确档案。"""
        from model_capabilities import ModelCapabilityRegistry
        import studio_model_selection

        with tempfile.TemporaryDirectory(dir="cache/studio-tests") as directory:
            root = Path(directory)
            (root / "data/model_capabilities/providers").mkdir(parents=True)
            (root / "data/model_capabilities/registry.json").write_text(json.dumps({
                "schema_version": 1,
                "providers": [{"provider_id": "fixture-cap", "file": "data/model_capabilities/providers/fixture.json"}],
            }), encoding="utf-8")
            profiles = []
            for operation, endpoint in (
                ("text_to_image", "/v1/images/generations"),
                ("image_to_image", "/v1/images/edits"),
            ):
                inputs = {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}}
                profiles.append({
                    "model_id": "fixture-image", "node_type": "image_generation",
                    "family_id": "fixture-family", "family_name": "Fixture",
                    "variant_id": operation, "operation": operation,
                    "status": "confirmed", "readiness": "ready", "version": 1,
                    "evidence_level": "official_schema", "inputs": inputs, "parameters": {},
                    "request_mapping": {key: key for key in inputs},
                    "output": {"media_type": "image", "min": 1, "max": 1, "async": False},
                    "platform": {"endpoint": endpoint},
                })
            (root / "data/model_capabilities/providers/fixture.json").write_text(json.dumps({
                "provider_id": "fixture-cap", "models": profiles,
            }), encoding="utf-8")

            registry = ModelCapabilityRegistry(root)
            providers = [{
                "id": "fixture-cap", "name": "Fixture", "protocol": "openai", "enabled": True,
                "image_models": ["fixture-image"], "chat_models": [], "video_models": [], "audio_models": [],
            }]
            catalog = registry.build_catalog(providers)
            options = studio_model_selection.compile_catalog_options(catalog)
            self.assertEqual({item["operation"] for item in options}, {"text_to_image", "image_to_image"})

            text_profile = registry.validate_request(
                providers, "fixture-cap", "fixture-image", "image_generation",
                input_counts={"text": 1}, input_roles={"prompt": 1}, parameters={}, operation="text_to_image",
            )
            image_profile = registry.validate_request(
                providers, "fixture-cap", "fixture-image", "image_generation",
                input_counts={"text": 1}, input_roles={"prompt": 1}, parameters={}, operation="image_to_image",
            )
            self.assertEqual(text_profile["platform"]["endpoint"], "/v1/images/generations")
            self.assertEqual(image_profile["platform"]["endpoint"], "/v1/images/edits")

            import main
            with mock.patch.object(main, "MODEL_CAPABILITY_REGISTRY", registry):
                exact_options = {item["operation"]: item for item in options}
                for operation, endpoint in (
                    ("text_to_image", "/v1/images/generations"),
                    ("image_to_image", "/v1/images/edits"),
                ):
                    selected = exact_options[operation]
                    resolved = main.resolve_model_capability_request(
                        "fixture-cap", "fixture-image", "", "image_generation",
                        input_counts={"text": 1}, input_roles={"prompt": 1}, parameters={},
                        providers=providers, option_id=selected["option_id"],
                    )
                    self.assertEqual(resolved["operation"], operation)
                    self.assertEqual(resolved["platform"]["endpoint"], endpoint)
                with self.assertRaisesRegex(Exception, "多个精确运行选项"):
                    main.resolve_model_capability_request(
                        "fixture-cap", "fixture-image", "", "image_generation",
                        input_counts={"text": 1}, input_roles={"prompt": 1}, parameters={},
                        providers=providers,
                    )

    def test_canvas_settings_submit_and_collect_use_validated_snapshot_for_all_generators(self):
        """五种共享生成入口在预检后停用选项仍按原快照完成模拟结果收集。"""
        import main
        import studio_model_selection
        from model_capabilities import ModelCapabilityRegistry

        cases = [
            ("text", "text_generation", "smart-text-generator", "prompt_enhancement", "text", "textProvider", "textModel"),
            ("image", "image_generation", "smart-image-generator", "text_to_image", "image", "provider_id", "model"),
            ("video", "video_generation", "smart-video-generator", "text_to_video", "video", "videoProvider", "videoModel"),
            ("audio", "audio_generation", "smart-audio-generator", "text_to_audio", "audio", "audioProvider", "audioModel"),
            ("music", "music_generation", "smart-music-generator", "text_to_audio", "audio", "musicProvider", "musicModel"),
        ]

        with tempfile.TemporaryDirectory(dir="cache/studio-tests") as directory:
            root = Path(directory)
            (root / "data/model_capabilities/providers").mkdir(parents=True)
            (root / "data/model_capabilities/registry.json").write_text(json.dumps({
                "schema_version": 1,
                "providers": [{"provider_id": "ai-money", "file": "data/model_capabilities/providers/fixture.json"}],
            }), encoding="utf-8")
            profiles = []
            provider = {
                "id": "ai-money", "name": "Fixture laohu", "protocol": "openai",
                "base_url": "https://fixture.invalid/v1", "enabled": True,
                "chat_models": [], "image_models": [], "video_models": [], "audio_models": [],
            }
            for kind, node_type, _saved_type, operation, output_kind, field_provider, field_model in cases:
                model_id = f"fixture-{kind}"
                model_field = {
                    "text_generation": "chat_models", "image_generation": "image_models",
                    "video_generation": "video_models", "audio_generation": "audio_models",
                    "music_generation": "audio_models",
                }[node_type]
                provider[model_field].append(model_id)
                profiles.append({
                    "model_id": model_id, "node_type": node_type,
                    "family_id": f"fixture-{kind}-family", "family_name": "Fixture",
                    "variant_id": operation, "operation": operation,
                    "status": "confirmed", "readiness": "ready", "version": 1,
                    "evidence_level": "official_schema",
                    "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
                    "parameters": {}, "request_mapping": {"prompt": "prompt"},
                    "output": {"media_type": output_kind, "min": 1, "max": 1, "async": False},
                    "platform": {"endpoint": f"/v1/{kind}/generations"},
                })
            (root / "data/model_capabilities/providers/fixture.json").write_text(json.dumps({
                "provider_id": "ai-money", "models": profiles,
            }), encoding="utf-8")
            registry = ModelCapabilityRegistry(root)
            options = studio_model_selection.compile_catalog_options(registry.build_catalog([provider]))
            option_by_model = {item["catalog_model_id"]: item for item in options}
            self.assertEqual(set(option_by_model), {f"fixture-{kind}" for kind, *_ in cases})

            current_provider = copy.deepcopy(provider)
            collected = []

            class FakeResponse:
                status_code = 200
                text = "{}"

                def raise_for_status(self):
                    return None

                def json(self):
                    return {"choices": [{"message": {"content": "fixture text result"}}]}

            class FakeAsyncClient:
                def __init__(self, *args, **kwargs):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return None

                async def post(self, *args, **kwargs):
                    return FakeResponse()

            async def run_cases():
                for kind, node_type, saved_type, operation, _output_kind, field_provider, field_model in cases:
                    model_id = f"fixture-{kind}"
                    option = option_by_model[model_id]
                    option["enabled"] = False
                    node = {
                        "id": f"node-{kind}", "type": saved_type,
                        "modelSelection": {
                            "option_id": option["option_id"], "connection_id": "ai-money",
                            "operation": operation, "region_id": "",
                        },
                        "runSettings": {field_provider: "ai-money", field_model: model_id},
                    }
                    canvas = {
                        "id": main.CANVAS_SETTINGS_CANVAS_ID,
                        "nodes": [node], "connections": [], "settings": {},
                    }
                    request = {
                        "kind": kind, "provider_id": "ai-money", "model": model_id,
                        "region": "", "operation": operation, "option_id": option["option_id"],
                        "inputs": {"reference": [], "first_frame": [], "last_frame": [],
                                   "source_video": [], "reference_audio": []},
                        "input_counts": {"text": 1}, "input_roles": {"prompt": 1},
                        "parameters": {}, "prompt": "A safe fixture prompt", "system_prompt": "",
                    }
                    await main.studio_preflight(canvas, node, request, f"request-{kind}")
                    self.assertTrue(request.get("_studio_validated_model_context"))
                    self.assertEqual(request["_studio_validated_model_context"]["node_type"], node_type)

                    # 模拟预检后管理员关闭该选项；共享执行器只能使用本次已验证快照。
                    field_name = {"text": "chat_models", "image": "image_models", "video": "video_models",
                                  "audio": "audio_models", "music": "audio_models"}[kind]
                    current_provider[field_name] = [value for value in current_provider[field_name] if value != model_id]

                    with mock.patch.object(main, "get_api_provider", side_effect=lambda *_a, **_k: copy.deepcopy(current_provider)), \
                         mock.patch.object(main, "MODEL_CAPABILITY_REGISTRY", registry), \
                         mock.patch.object(main, "resolve_chat_provider", return_value=("https://fixture.invalid/v1", {}, model_id)), \
                         mock.patch.object(main.httpx, "AsyncClient", FakeAsyncClient), \
                         mock.patch.object(main, "generate_ai_money_special_text", new=mock.AsyncMock(return_value={
                             "text": "fixture text result", "model": model_id, "raw_usage": None, "raw": {},
                         })), \
                         mock.patch.object(main, "generate_ai_image", new=mock.AsyncMock(return_value=(b"fixture-image", {}))), \
                         mock.patch.object(main, "extract_images", side_effect=main.HTTPException(status_code=502, detail="fixture fallback")), \
                         mock.patch.object(main, "save_ai_image_to_output", new=mock.AsyncMock(return_value="/api/results/fixture-image.png")), \
                         mock.patch.object(main, "save_to_history"), \
                         mock.patch.object(main.PROJECT_STORAGE, "update_result_metadata"), \
                         mock.patch.object(main, "generate_ai_money_video", new=mock.AsyncMock(return_value={"videos": ["/api/results/fixture-video.mp4"]})), \
                         mock.patch.object(main, "generate_ai_money_audio", new=mock.AsyncMock(return_value={"audios": ["/api/results/fixture-audio.mp3"]})):
                        result = await main.studio_generate(request)
                    collected.append((kind, result))
                    self.assertNotIn(model_id, current_provider[field_name])
                    with mock.patch.object(main, "MODEL_CAPABILITY_REGISTRY", registry):
                        with self.assertRaises(main.HTTPException):
                            main.resolve_model_capability_request(
                                "ai-money", model_id, "", node_type,
                                input_counts={"text": 1}, input_roles={"prompt": 1}, parameters={},
                                operation=operation, providers=[copy.deepcopy(current_provider)],
                                option_id=option["option_id"],
                            )

            with mock.patch.object(main, "MODEL_CAPABILITY_REGISTRY", registry), \
                 mock.patch.object(main, "get_api_provider", side_effect=lambda *_a, **_k: copy.deepcopy(current_provider)), \
                 mock.patch.object(main, "_build_model_management_catalog", return_value={"options": options}):
                asyncio.run(run_cases())

            self.assertEqual([kind for kind, _result in collected], [case[0] for case in cases])
            for kind, result in collected:
                output_key = {"text": "text", "image": "images", "video": "videos", "audio": "audios", "music": "audios"}[kind]
                self.assertTrue(result.get(output_key), f"{kind} 返回结果未被收集")

    def test_management_catalog_returns_full_safe_profile_view(self):
        """manager 目录复用共享档案形状，但 provider 只暴露白名单字段。"""
        import main

        option = {
            "option_id": "fixture-option", "connection_id": "fixture-conn",
            "capability_provider_id": "fixture-cap", "catalog_model_id": "fixture-model",
            "node_type": "image_generation", "operation": "text_to_image", "endpoint_id": "/image",
            "region_id": "", "validation_mode": "strict", "readiness": "ready",
            "runnable": True, "selectable": True, "selection_unavailable_reason": "",
            "profile_revision": "fixture-profile",
        }
        profile = {
            "model_id": "fixture-model", "node_type": "image_generation", "operation": "text_to_image",
            "endpoint_id": "/image", "validation_mode": "strict", "readiness": "ready", "runnable": True,
            "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
            "parameters": {"size": {"type": "enum", "options": ["small", "large"]}},
            "family_id": "fixture-family", "family_name": "Fixture family",
        }
        unsafe_catalog = {
            "schema_version": 1, "updated_at": "now", "private_key": "must-not-leak",
            "providers": [{
                "id": "fixture-conn", "name": "Fixture", "protocol": "openai",
                "capability_provider_id": "fixture-cap", "profile_updated_at": "now",
                "regions": [{"region": "", "enabled": True, "model_count": 1, "base_url": "internal"}],
                "models": [profile], "families": [{"id": "fixture-family", "variants": [profile]}],
                "api_key": "must-not-leak",
            }],
        }
        configured = [{"id": "fixture-conn", "enabled": True, "image_models": ["fixture-model"]}]

        with mock.patch.object(main.MODEL_CAPABILITY_REGISTRY, "load", return_value={
            "profiles": {"fixture-cap": {"models": [profile]}}
        }), mock.patch.object(main.MODEL_CAPABILITY_REGISTRY, "capability_provider_id", return_value="fixture-cap"), \
             mock.patch.object(main.MODEL_CAPABILITY_REGISTRY, "build_catalog", return_value=unsafe_catalog), \
             mock.patch.object(main.studio_model_selection, "compile_catalog_options", return_value=[option]):
            result = main._build_model_management_catalog(configured)

        self.assertEqual(result["catalog"]["providers"][0]["id"], option["connection_id"])
        self.assertEqual(result["catalog"]["providers"][0]["models"][0]["inputs"], profile["inputs"])
        self.assertEqual(result["catalog"]["providers"][0]["families"][0]["variants"][0]["parameters"], profile["parameters"])
        self.assertEqual(result["catalog"]["providers"][0]["regions"], [{"region": "", "enabled": True, "model_count": 1}])
        self.assertNotIn("api_key", result["catalog"]["providers"][0])
        self.assertNotIn("private_key", result["catalog"])
        self.assertNotIn("base_url", result["catalog"]["providers"][0]["regions"][0])

    def test_disabled_guard_uses_exact_non_runninghub_identity_despite_client_region(self):
        import main
        import studio_model_selection

        operation_a = "text_to_image"
        operation_b = "image_to_image"
        endpoint_a = "/v1/images/generations"
        endpoint_b = "/v1/images/edits"
        option_a = studio_model_selection.compute_option_id(
            connection_id="fixture-conn", region_id="", deployment_id="",
            node_type="image_generation", catalog_model_id="fixture-image",
            endpoint_id=endpoint_a, operation=operation_a,
        )
        option_b = studio_model_selection.compute_option_id(
            connection_id="fixture-conn", region_id="", deployment_id="",
            node_type="image_generation", catalog_model_id="fixture-image",
            endpoint_id=endpoint_b, operation=operation_b,
        )
        provider = {
            "id": "fixture-conn", "image_models": ["fixture-image"],
            "disabled_model_options": [option_a],
        }
        catalog = {"options": [
            {
                "option_id": option_a, "connection_id": "fixture-conn", "region_id": "",
                "catalog_model_id": "fixture-image", "node_type": "image_generation",
                "operation": operation_a, "endpoint_id": endpoint_a, "enabled": False,
            },
            {
                "option_id": option_b, "connection_id": "fixture-conn", "region_id": "",
                "catalog_model_id": "fixture-image", "node_type": "image_generation",
                "operation": operation_b, "endpoint_id": endpoint_b, "enabled": True,
            },
        ]}
        with mock.patch.object(main, "_build_model_management_catalog", return_value=catalog):
            with self.assertRaises(main.ModelCapabilityError):
                main._guard_disabled_model_option(
                    "fixture-conn", "fixture-image", "image_generation",
                    operation=operation_a, region="global", providers=[provider],
                    option_id=option_a, endpoint_id=endpoint_a,
                )
            # 客户端传 global/CN 不会让普通 provider 的 region 维度变成空匹配后绕过停用检查。
            with self.assertRaises(main.ModelCapabilityError):
                main._guard_disabled_model_option(
                    "fixture-conn", "fixture-image", "image_generation",
                    operation=operation_a, region="cn", providers=[provider], endpoint_id=endpoint_a,
                )
            # 同一 model 的另一个 endpoint/operation 仍独立启用，不被兄弟 option 牵连。
            self.assertIsNone(main._guard_disabled_model_option(
                "fixture-conn", "fixture-image", "image_generation",
                operation=operation_b, region="global", providers=[provider], endpoint_id=endpoint_b,
            ))

    def test_settings_canvas_accepts_disabled_option_for_five_real_execution_node_shapes(self):
        import main
        import studio_model_selection

        nodes = [
            ("smart-text-generator", "text_generation", "textProvider", "textModel", "text_to_text"),
            ("smart-image-generator", "image_generation", "provider_id", "model", "text_to_image"),
            ("smart-video-generator", "video_generation", "videoProvider", "videoModel", "text_to_video"),
            ("smart-audio-generator", "audio_generation", "audioProvider", "audioModel", "text_to_audio"),
            ("smart-music-generator", "music_generation", "musicProvider", "musicModel", "text_to_music"),
        ]
        options = []
        canvas_nodes = []
        payloads = []
        for index, (node_kind, node_type, provider_key, model_key, operation) in enumerate(nodes):
            option_id = studio_model_selection.compute_option_id(
                connection_id="fixture-conn", region_id="", deployment_id="",
                node_type=node_type, catalog_model_id=f"model-{index}",
                endpoint_id=f"endpoint-{index}", operation=operation,
            )
            node = {
                "id": f"run-{index}", "type": node_kind,
                "runSettings": {provider_key: "fixture-conn", model_key: f"model-{index}"},
                "modelSelection": {
                    "option_id": option_id, "connection_id": "fixture-conn",
                    "region_id": "", "operation": operation,
                },
            }
            canvas_nodes.append(node)
            options.append({
                "option_id": option_id, "connection_id": "fixture-conn", "region_id": "",
                "catalog_model_id": f"model-{index}", "node_type": node_type,
                "operation": operation, "endpoint_id": f"endpoint-{index}", "enabled": False,
            })
            payloads.append(main.CanvasPreflightRequest(
                canvas_id="canvas-settings", node_id=node["id"], provider_id="fixture-conn",
                model_id=f"model-{index}", node_type=node_type, operation=operation, option_id=option_id,
            ))
        canvas = {"id": "canvas-settings", "nodes": canvas_nodes, "connections": []}
        with mock.patch.object(main, "_build_model_management_catalog", return_value={"options": options}):
            selected = [main._canvas_settings_selected_option(payload, canvas) for payload in payloads]
        self.assertEqual([item["node_type"] for item in selected], [item[1] for item in nodes])
        self.assertTrue(all(item and item["enabled"] is False for item in selected))

    def test_validated_studio_snapshot_keeps_exact_model_for_all_five_shared_generators(self):
        import main
        import studio_model_selection

        nodes = [
            ("text_generation", "text", "text_to_text", "chat_models"),
            ("image_generation", "image", "text_to_image", "image_models"),
            ("video_generation", "video", "text_to_video", "video_models"),
            ("audio_generation", "audio", "text_to_audio", "audio_models"),
            ("music_generation", "music", "text_to_music", "audio_models"),
        ]
        for node_type, kind, operation, field_name in nodes:
            with self.subTest(node_type=node_type):
                model_id = f"fixture-{kind}"
                endpoint_id = f"/fixture/{kind}"
                option_id = studio_model_selection.compute_option_id(
                    connection_id="fixture-conn", region_id="", deployment_id="",
                    node_type=node_type, catalog_model_id=model_id,
                    endpoint_id=endpoint_id, operation=operation,
                )
                profile = {
                    "provider_id": "fixture-conn", "model_id": model_id, "node_type": node_type,
                    "operation": operation, "variant_id": operation, "endpoint_id": endpoint_id,
                    "family_id": f"family-{kind}", "parameters": {},
                    "validation_mode": "strict", "runnable": True,
                }
                providers = [{"id": "fixture-conn", "enabled": True, field_name: [],
                             "disabled_model_options": [option_id]}]
                context = {
                    "validated": True, "canvas_id": "canvas-settings", "node_id": f"node-{kind}",
                    "option_id": option_id, "connection_id": "fixture-conn",
                    "capability_provider_id": "fixture-conn", "region_id": "",
                    "node_type": node_type, "catalog_model_id": model_id,
                    "endpoint_id": endpoint_id, "operation": operation, "manager_test": True,
                }
                token = main._STUDIO_VALIDATED_MODEL_CONTEXT.set(context)
                try:
                    with mock.patch.object(main.MODEL_CAPABILITY_REGISTRY, "validate_request", return_value=profile) as validate_request, \
                         mock.patch.object(main, "_guard_disabled_model_option", side_effect=AssertionError("validated task was re-guarded")):
                        result = main.resolve_model_capability_request(
                            "fixture-conn", model_id, "", node_type, providers=providers, region="global",
                        )
                    self.assertEqual(result, profile)
                    self.assertIn(model_id, validate_request.call_args.args[0][0][field_name])
                    self.assertEqual(validate_request.call_args.kwargs["operation"], operation)
                finally:
                    main._STUDIO_VALIDATED_MODEL_CONTEXT.reset(token)


if __name__ == "__main__":
    unittest.main()
