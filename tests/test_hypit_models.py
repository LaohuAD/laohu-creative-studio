import asyncio
import copy
import json
import time
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from studio_hypit_models import _validate_workflow_result, create_hypit_models_router


def catalog():
    result = {
        "schema_version": 1,
        "providers": [
            {
                "id": "provider-a",
                "name": "Provider A",
                "protocol": "openai",
                "models": [
                    {
                        "model_id": "text-1",
                        "node_type": "text_generation",
                        "family_id": "text-family",
                        "runnable": True,
                        "readiness": "ready",
                        "validation_mode": "strict",
                        "parameters": {"temperature": {"type": "number", "min": 0, "max": 2}},
                        "inputs": {
                            "prompt": {"media_type": "text", "min": 1, "max": 1},
                            "reference": {"media_type": "image", "min": 0, "max": 2},
                        },
                    },
                    {
                        "model_id": "image-1",
                        "node_type": "image_generation",
                        "family_id": "image-family",
                        "runnable": True,
                        "readiness": "ready",
                        "validation_mode": "strict",
                        "parameters": {"count": {"type": "integer", "min": 1, "max": 2}},
                        "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
                    },
                    {
                        "model_id": "image-2",
                        "node_type": "image_generation",
                        "family_id": "image-family",
                        "runnable": True,
                        "readiness": "ready",
                        "validation_mode": "strict",
                        "parameters": {"count": {"type": "integer", "min": 1, "max": 2}},
                        "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
                    },
                    {
                        "model_id": "video-1",
                        "node_type": "video_generation",
                        "family_id": "video-family",
                        "runnable": True,
                        "readiness": "ready",
                        "validation_mode": "strict",
                        "parameters": {"duration": {"type": "integer", "min": 1, "max": 10}},
                        "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
                    },
                    {
                        "model_id": "voice-1",
                        "node_type": "audio_generation",
                        "family_id": "voice-family",
                        "runnable": True,
                        "readiness": "ready",
                        "validation_mode": "strict",
                        "parameters": {"speaker": {"type": "text"}},
                        "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
                    },
                    {
                        "model_id": "music-1",
                        "node_type": "music_generation",
                        "family_id": "music-family",
                        "runnable": True,
                        "readiness": "ready",
                        "validation_mode": "strict",
                        "parameters": {"instrumental": {"type": "boolean"}},
                        "inputs": {
                            "prompt": {"media_type": "text", "min": 1, "max": 1},
                            "reference_audio": {"media_type": "audio", "min": 0, "max": 1},
                        },
                    },
                ],
            },
            {
                "id": "runninghub",
                "name": "RunningHub",
                "protocol": "runninghub",
                "regions": [
                    {"region": "global", "enabled": True},
                    {"region": "cn", "enabled": True},
                ],
                "models": [
                    {
                        "model_id": "shared-image",
                        "node_type": "image_generation",
                        "family_id": "shared-image-family",
                        "runnable": True,
                        "readiness": "ready",
                        "validation_mode": "strict",
                        "regions": ["global", "cn"],
                        "region_profiles": {
                            "global": {
                                "model_id": "shared-image",
                                "node_type": "image_generation",
                                "family_id": "shared-image-family",
                                "runnable": True,
                                "readiness": "ready",
                                "validation_mode": "strict",
                                "parameters": {"count": {"type": "integer", "min": 1, "max": 1}},
                                "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
                            },
                            "cn": {
                                "model_id": "shared-image",
                                "node_type": "image_generation",
                                "family_id": "shared-image-family",
                                "runnable": True,
                                "readiness": "ready",
                                "validation_mode": "strict",
                                "parameters": {"count": {"type": "integer", "min": 1, "max": 2}},
                                "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
                            },
                        },
                        "parameters": {"count": {"type": "integer", "min": 1, "max": 4}},
                        "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
                    },
                ],
            },
        ],
    }


    operations = {'text_generation': 'chat', 'image_generation': 'text_to_image',
                  'video_generation': 'text_to_video', 'audio_generation': 'text_to_speech',
                  'music_generation': 'music'}
    for provider in result['providers']:
        for model in provider['models']:
            for profile in [model, *model.get('region_profiles', {}).values()]:
                profile['operation'] = operations[profile['node_type']]
                profile['output'] = {'media_type': 'audio' if profile['node_type'] == 'music_generation' else profile['node_type'].split('_')[0]}
    return result


class HypitModelsTests(unittest.TestCase):
    def test_workflow_result_exposes_only_slot_match_after_typed_collection(self):
        mixed = _validate_workflow_result("image", {
            "images": [{"url": "/api/results/frame.png", "mime_type": "image/png"}],
            "videos": [{"url": "/api/results/clip.mp4", "mime_type": "video/mp4"}],
            "files": [{"url": "/api/results/unknown"}],
        })
        self.assertEqual(len(mixed["images"]), 1)
        self.assertNotIn("videos", mixed)
        self.assertNotIn("files", mixed)
        with self.assertRaisesRegex(RuntimeError, "未返回可确认的 image"):
            _validate_workflow_result("image", {"videos": [{"url": "/api/results/clip.mp4", "mime_type": "video/mp4"}]})
        with self.assertRaisesRegex(RuntimeError, "未返回可确认的 image"):
            _validate_workflow_result("image", {"images": [{"url": "https://fixture.invalid/no-type"}]})

    def test_native_build_uses_settings_canvas_callback_and_is_idempotent(self):
        runs = {}
        submissions = []

        async def submit_canvas(slot, output_node_id, request_id, payload, test=False):
            submissions.append((slot, output_node_id, request_id, copy.deepcopy(payload), test))
            run_id = f"run-{request_id}"
            runs[run_id] = {
                # Native build returns the saved execution snapshot result even if
                # the shared settings graph changed while that request was running.
                "run_id": run_id, "status": "succeeded", "current_recipe_matches": False,
                "output_kind": "image", "result": {"images": [{"url": "/api/results/from-settings-canvas.png",
                    "kind": "image", "mime_type": "image/png"}]},
            }
            return {"run_id": run_id, "status": "queued"}

        async def get_canvas_run(run_id):
            return copy.deepcopy(runs[run_id])

        app = FastAPI()
        app.include_router(create_hypit_models_router(
            self.root,
            lambda project_id, module: copy.deepcopy(self.projects[project_id]),
            lambda: catalog(),
            lambda request: self.fail("settings-canvas build must not use legacy API validation"),
            lambda request: self.fail("settings-canvas build must not use legacy API generation"),
            submit_settings_canvas_request=submit_canvas,
            get_settings_canvas_request=get_canvas_run,
        ))

        payload = {
            "request_id": "native-canvas-build",
            "capability": {"module": {"name": "@laohu/studio-models", "version": "1"},
                           "name": "image-generation"},
            "constraints": {"kind": "image", "slot": "image", "prompt": "画一只红狐狸",
                            "inputs": {"reference": ["data:image/png;base64,AA=="]},
                            "parameters": {"quality": "high"}},
        }
        with TestClient(app) as client:
            submitted = client.post("/api/studio/hypit/models/projects/project-a/requests", json=payload)
            self.assertEqual(submitted.status_code, 200, submitted.text)
            result = self.wait_for_status(client, "project-a", "native-canvas-build", "succeeded")
            duplicate = client.post("/api/studio/hypit/models/projects/project-a/requests", json=payload)
            self.assertEqual(duplicate.status_code, 200, duplicate.text)
            self.assertEqual(duplicate.json()["task_id"], result["task_id"])

        self.assertEqual(len(submissions), 1)
        slot, output_node_id, flow_request_id, projected, is_test = submissions[0]
        self.assertEqual(slot, "image")
        self.assertEqual(output_node_id, "")  # 主控从专用图按槽定位唯一输出节点
        self.assertNotEqual(flow_request_id, payload["request_id"])
        self.assertFalse(is_test)
        self.assertEqual(projected["kind"], "image")
        self.assertEqual(projected["prompt"], "画一只红狐狸")
        self.assertEqual(projected["inputs"], {"reference": ["data:image/png;base64,AA=="]})
        self.assertEqual(projected["parameters"], {"quality": "high"})
        self.assertEqual(result["result"]["images"][0]["url"], "/api/results/from-settings-canvas.png")
        self.assertFalse((self.root / "data" / "hypit_settings.json").exists(),
                         "原生运行不得回退读取或创建旧六槽 JSON 默认设置")

    def test_settings_canvas_projection_is_authoritative_and_legacy_puts_are_blocked(self):
        settings_path = self.root / "data" / "hypit_settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_bytes = json.dumps({
            "version": 2,
            "defaults": {"image": {"provider": "legacy-provider", "model": "legacy-model"}},
        }).encode("utf-8")
        settings_path.write_bytes(legacy_bytes)
        projection = {
            "version": 2,
            "source": "settings_canvas",
            "canvas_id": "hypit-settings",
            "revision": 23,
            "created_at": "2026-10-05T00:00:00Z",
            "updated_at": "2026-10-05T00:01:00Z",
            "defaults": {
                "image": {
                    "selection_kind": "settings_canvas", "status": "connected", "connected": True,
                    "expected_kind": "image", "output_node_id": "out-image", "source_node_id": "gen-image",
                    "node_ids": ["gen-image"], "recipe_fingerprint": "recipe-image",
                },
                "text": {"selection_kind": "settings_canvas", "status": "unconfigured", "connected": False,
                         "expected_kind": "text", "output_node_id": "", "source_node_id": "",
                         "node_ids": [], "recipe_fingerprint": ""},
            },
        }
        app = FastAPI()
        app.include_router(create_hypit_models_router(
            self.root,
            lambda project_id, module: copy.deepcopy(self.projects[project_id]),
            lambda: catalog(),
            lambda request: asyncio.sleep(0, result={"ok": True}),
            lambda request: asyncio.sleep(0, result={"images": []}),
            get_settings_canvas_projection=lambda: copy.deepcopy(projection),
        ))

        with TestClient(app) as client:
            settings = client.get("/api/studio/hypit/models/settings")
            capabilities = client.get("/api/studio/hypit/models/capabilities")
            binding = client.get("/api/studio/hypit/models/projects/project-a/binding")
            self.assertEqual(settings.status_code, 200, settings.text)
            self.assertEqual(capabilities.status_code, 200, capabilities.text)
            self.assertEqual(binding.status_code, 200, binding.text)
            capability_record = capabilities.json()
            self.assertEqual(capability_record["settings_source"], "settings_canvas")
            self.assertEqual(capability_record["settings_canvas_id"], "hypit-settings")
            self.assertEqual(capability_record["settings_revision"], 23)
            self.assertEqual(capability_record["defaults"]["image"]["source_node_id"], "gen-image")
            for record in (settings.json(), binding.json()):
                self.assertEqual(record["source"], "settings_canvas")
                self.assertEqual(record["canvas_id"], "hypit-settings")
                self.assertEqual(record["revision"], 23)
                self.assertEqual(record["defaults"]["image"]["source_node_id"], "gen-image")
                self.assertEqual(record["defaults"]["text"]["status"], "unconfigured")
                self.assertNotEqual(record["defaults"]["image"].get("model"), "legacy-model")

            settings_put = client.put("/api/studio/hypit/models/settings", json={
                "expected_revision": 23, "defaults": {"image": {"provider": "other", "model": "other"}},
            })
            binding_put = client.put("/api/studio/hypit/models/projects/project-a/binding", json={
                "expected_revision": 23, "defaults": {"image": {"provider": "other", "model": "other"}},
            })
            self.assertEqual(settings_put.status_code, 410, settings_put.text)
            self.assertEqual(binding_put.status_code, 410, binding_put.text)
            self.assertEqual(settings_path.read_bytes(), legacy_bytes)

    def setUp(self):
        self.root = Path("cache/studio-tests/hypit-models") / f"case-{time.time_ns()}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.projects = {"project-a": {"id": "project-a"}, "project-b": {"id": "project-b"}}
        self.calls = []
        self.fail_generation = False

        def get_project(project_id, module):
            self.assertEqual(module, "hypit")
            if project_id not in self.projects:
                raise KeyError(project_id)
            return copy.deepcopy(self.projects[project_id])

        def get_capabilities():
            return copy.deepcopy(catalog())

        async def validate(request):
            self.calls.append(("validate", copy.deepcopy(request)))
            return {"validation": "ok", "model": request["model"]}

        async def generate(request):
            self.calls.append(("generate", copy.deepcopy(request)))
            await asyncio.sleep(0)
            if self.fail_generation:
                raise RuntimeError("simulated generation failure")
            if request['kind'] == 'music':
                return {'audios': [{'url': '/api/results/fixture-music.wav'}], 'model': request['model']}
            return {"images": [{"url": "/api/results/result-a.png"}], "model": request["model"]}

        self.app = FastAPI()
        self.app.include_router(
            create_hypit_models_router(
                self.root,
                get_project,
                get_capabilities,
                validate,
                generate,
            )
        )

    def tearDown(self):
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)

    def wait_for_status(self, client, project_id, request_id, expected):
        for _ in range(100):
            response = client.get(
                f"/api/studio/hypit/models/projects/{project_id}/requests/{request_id}"
            )
            self.assertEqual(response.status_code, 200, response.text)
            value = response.json()
            if value["status"] == expected:
                return value
            time.sleep(0.01)
        self.fail(f"request did not reach {expected}: {value}")

    def workflow_app(self, descriptor, workflow_result, calls):
        from studio_hypit_models import create_hypit_models_router

        async def validate_workflow(request, snapshot):
            calls.append(("validate", copy.deepcopy(request), copy.deepcopy(snapshot)))
            return {"checked": True}

        async def generate_workflow(request, snapshot):
            calls.append(("generate", copy.deepcopy(request), copy.deepcopy(snapshot)))
            await asyncio.sleep(0)
            return copy.deepcopy(workflow_result)

        selection = {key: descriptor[key] for key in ("source", "provider_id", "region", "item_id")}

        def resolve_workflow(value):
            calls.append(("resolve", copy.deepcopy(value)))
            if value != selection:
                raise KeyError("workflow source not found")
            return copy.deepcopy(descriptor)

        app = FastAPI()
        app.include_router(create_hypit_models_router(
            self.root,
            lambda project_id, module: copy.deepcopy(self.projects[project_id]),
            lambda: catalog(),
            lambda request: asyncio.sleep(0, result={"ok": True}),
            lambda request: asyncio.sleep(0, result={"images": []}),
            get_workflow_options=lambda: [copy.deepcopy(descriptor)],
            resolve_workflow=resolve_workflow,
            validate_workflow=validate_workflow,
            generate_workflow=generate_workflow,
        ))
        return app

    def test_runninghub_app_workflow_is_saved_projected_and_snapshotted(self):
        descriptor = {
            "source": "runninghub_app", "provider_id": "runninghub", "region": "global",
            "item_id": "app-1", "name": "Fixture image app", "enabled": True,
            "schema_status": "ready", "fields": [
                {"nodeId": "1", "fieldName": "prompt", "fieldType": "TEXT", "inputRole": "prompt", "required": True},
                {"nodeId": "2", "fieldName": "image", "fieldType": "IMAGE", "required": True},
                {"nodeId": "3", "fieldName": "strength", "fieldType": "NUMBER", "required": True, "defaultValue": 0.5},
            ],
        }
        calls = []
        app = self.workflow_app(descriptor, {"images": [{"url": "/api/results/fixture.png", "kind": "image", "mime_type": "image/png"}]}, calls)
        selection = {
            "selection_kind": "workflow", "source": "runninghub_app", "provider_id": "runninghub",
            "region": "global", "item_id": "app-1", "expected_slot": "image",
            "expected_kind": "image", "confirmed_for_slot": True,
            "input_bindings": {"prompt": "1::prompt", "reference": "2::image"},
            "field_values": {"3::strength": 0.5},
        }
        with TestClient(app) as client:
            options = client.get("/api/studio/hypit/models/workflow-options?slot=image")
            self.assertEqual(options.status_code, 200, options.text)
            self.assertEqual(options.json()["options"][0]["item_id"], "app-1")
            self.assertNotIn("workflow_json", options.text)
            selection["schema_fingerprint"] = options.json()["options"][0]["schema_fingerprint"]
            saved = client.put("/api/studio/hypit/models/settings", json={"defaults": {"image": selection}})
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()["defaults"]["image"]["selection_kind"], "workflow")
            submitted = client.post("/api/studio/hypit/models/projects/project-a/requests", json={
                "request_id": "workflow-app",
                "capability": {"module": {"name": "@laohu/studio-models", "version": "1"}, "name": "image-generation"},
                "constraints": {"kind": "image", "prompt": "一只红狐狸", "inputs": {"reference": ["data:image/png;base64,AA=="]},
                                "parameters": {"3::strength": 0.8}},
            })
            self.assertEqual(submitted.status_code, 200, submitted.text)
            task = self.wait_for_status(client, "project-a", "workflow-app", "succeeded")

        validate = next(item for item in calls if item[0] == "validate")
        generate = next(item for item in calls if item[0] == "generate")
        self.assertEqual(validate[1]["source"], "runninghub_app")
        self.assertEqual(validate[1]["expected_slot"], "image")
        self.assertEqual(validate[1]["field_values"]["1::prompt"], "一只红狐狸")
        self.assertEqual(validate[1]["field_values"]["2::image"], "data:image/png;base64,AA==")
        self.assertEqual(validate[1]["field_values"]["3::strength"], 0.8)
        self.assertEqual(generate[2]["item_id"], "app-1")
        self.assertEqual(task["result"]["images"][0]["kind"], "image")
        self.assertNotIn("execution_snapshot", task)

    def test_local_comfy_workflow_executes_with_audio_slot_and_typed_result(self):
        descriptor = {
            "source": "local_comfy_workflow", "provider_id": "local-comfyui", "region": "",
            "item_id": "audio/voice.json", "name": "Fixture voice workflow", "enabled": True,
            "schema_status": "ready", "workflow_json": {"1": {"class_type": "SaveAudio", "inputs": {}}},
            "fields": [
                {"id": "prompt", "node": "2", "input": "text", "type": "textarea", "required": True},
                {"id": "audio", "node": "3", "input": "audio", "type": "AUDIO", "required": True},
            ],
        }
        calls = []
        app = self.workflow_app(descriptor, {"audios": [{"url": "/api/results/voice.wav", "kind": "audio", "mime_type": "audio/wav"}]}, calls)
        selection = {
            "selection_kind": "workflow", "source": "local_comfy_workflow", "provider_id": "local-comfyui",
            "region": "", "item_id": "audio/voice.json", "expected_slot": "audio",
            "expected_kind": "audio", "confirmed_for_slot": True,
            "input_bindings": {"prompt": "prompt", "reference_audio": "audio"}, "field_values": {},
        }
        with TestClient(app) as client:
            options = client.get("/api/studio/hypit/models/workflow-options?slot=audio")
            self.assertEqual(options.status_code, 200, options.text)
            selection["schema_fingerprint"] = options.json()["options"][0]["schema_fingerprint"]
            saved = client.put("/api/studio/hypit/models/settings", json={"defaults": {"audio": selection}})
            self.assertEqual(saved.status_code, 200, saved.text)
            submitted = client.post("/api/studio/hypit/models/projects/project-a/requests", json={
                "request_id": "workflow-comfy-audio",
                "capability": {"module": {"name": "@laohu/studio-models", "version": "1"}, "name": "audio-generation"},
                "constraints": {"kind": "audio", "prompt": "轻柔的雨声", "inputs": {"reference_audio": ["data:audio/wav;base64,AA=="]}},
            })
            self.assertEqual(submitted.status_code, 200, submitted.text)
            task = self.wait_for_status(client, "project-a", "workflow-comfy-audio", "succeeded")

        generated = next(item for item in calls if item[0] == "generate")
        self.assertEqual(generated[1]["source"], "local_comfy_workflow")
        self.assertEqual(generated[1]["field_values"], {"prompt": "轻柔的雨声", "audio": "data:audio/wav;base64,AA=="})
        self.assertEqual(generated[2]["workflow_json"]["1"]["class_type"], "SaveAudio")
        self.assertEqual(task["result"]["audios"][0]["kind"], "audio")

    def test_module_settings_are_shared_and_binding_is_compatibility_read(self):
        with TestClient(self.app) as client:
            initial = client.get("/api/studio/hypit/models/settings")
            self.assertEqual(initial.status_code, 200, initial.text)
            self.assertNotIn("api_key", initial.text.lower())
            self.assertEqual(initial.json()["defaults"]["image"]["provider"], "")
            self.assertEqual(initial.json()["revision"], 1)

            saved = client.put(
                "/api/studio/hypit/models/settings",
                json={
                    "expected_revision": initial.json()["revision"],
                    "defaults": {
                        "image": {
                            "provider": "provider-a",
                            "model": "image-1",
                            "parameters": {"count": 1},
                        },
                        "voice": {
                            "provider": "provider-a",
                            "model": "voice-1",
                            "parameters": {"speaker": "Narrator"},
                        },
                    }
                },
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertNotIn("api_key", saved.text.lower())
            self.assertEqual(saved.json()["revision"], 2)

            first = client.get(
                "/api/studio/hypit/models/projects/project-a/binding"
            )
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()["defaults"]["image"]["model"], "image-1")
            self.assertEqual(first.json()["revision"], saved.json()["revision"])
            self.assertEqual(first.json()["source"], "module_settings")

            legacy_path = self.root / "data" / "hypit_bindings" / "project-a.json"
            legacy_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "project_id": "project-a",
                        "defaults": {"image": {"provider": "provider-a", "model": "image-1", "parameters": {}}},
                        "revision": 1,
                    }
                ),
                encoding="utf-8",
            )

            changed = client.put(
                "/api/studio/hypit/models/settings",
                json={
                    "expected_revision": saved.json()["revision"],
                    "defaults": {
                        "image": {
                            "provider": "provider-a",
                            "model": "image-2",
                            "parameters": {},
                        }
                    }
                },
            )
            self.assertEqual(changed.status_code, 200, changed.text)
            pinned = client.get(
                "/api/studio/hypit/models/projects/project-a/binding"
            )
            self.assertEqual(pinned.status_code, 200, pinned.text)
            self.assertEqual(pinned.json()["defaults"]["image"]["model"], "image-2")
            self.assertEqual(pinned.json()["revision"], changed.json()["revision"])
            self.assertEqual(json.loads(legacy_path.read_text(encoding="utf-8"))["defaults"]["image"]["model"], "image-1")

            stale_settings = client.put(
                "/api/studio/hypit/models/settings",
                json={
                    "expected_revision": saved.json()["revision"],
                    "defaults": {"image": {"provider": "provider-a", "model": "image-1", "parameters": {}}},
                },
            )
            self.assertEqual(stale_settings.status_code, 409, stale_settings.text)

    def test_v1_settings_backup_is_created_once_on_first_write_only(self):
        settings_path = self.root / "data" / "hypit_settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        original = b'{"version":1,"defaults":{"image":{"provider":"provider-a","model":"image-1","parameters":{}}},"revision":4}\n'
        settings_path.write_bytes(original)
        backup_path = self.root / "backups" / "hypit" / "hypit_settings.v1.json"

        with TestClient(self.app) as client:
            read = client.get("/api/studio/hypit/models/settings")
            self.assertEqual(read.status_code, 200, read.text)
            self.assertFalse(backup_path.exists(), "读取 v1 设置不能触发迁移备份")
            self.assertEqual(settings_path.read_bytes(), original)

            first = client.put("/api/studio/hypit/models/settings", json={"defaults": {}})
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()["version"], 2)
            self.assertEqual(backup_path.read_bytes(), original)

            second = client.put("/api/studio/hypit/models/settings", json={"defaults": {}})
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(second.json()["version"], 2)
            self.assertEqual(backup_path.read_bytes(), original, "重复保存不能覆盖一次性 v1 原件备份")

    def test_workflow_credential_fields_are_hidden_without_removing_token_count(self):
        secret = "fixture-never-return-this-secret"
        descriptor = {
            "source": "runninghub_app", "provider_id": "runninghub", "region": "global",
            "item_id": "app-secret-fields", "name": "Fixture app", "enabled": True,
            "fields": [
                {"nodeId": "1", "fieldName": "prompt", "fieldType": "STRING", "inputRole": "prompt", "required": True},
                {"nodeId": "2", "fieldName": "token", "fieldType": "STRING", "fieldValue": secret},
                {"nodeId": "3", "fieldName": "auth_token", "fieldType": "STRING", "fieldValue": secret},
                {"nodeId": "4", "fieldName": "bearer_token", "fieldType": "STRING", "fieldValue": secret},
                {"nodeId": "5", "fieldName": "session_token", "fieldType": "STRING", "fieldValue": secret},
                {"nodeId": "6", "fieldName": "max_tokens", "fieldType": "INT", "fieldValue": 64},
                {"nodeId": "7", "fieldName": "quality", "fieldType": "SELECT",
                 "options": [{"name": "credential", "default": secret}]},
            ],
        }
        calls = []
        app = self.workflow_app(descriptor, {"images": [{"url": "/api/results/fixture.png", "kind": "image"}]}, calls)
        with TestClient(app) as client:
            options = client.get("/api/studio/hypit/models/workflow-options?slot=image")
            self.assertEqual(options.status_code, 200, options.text)
            self.assertNotIn(secret, options.text)
            option_fields = options.json()["options"][0]["fields"]
            self.assertIn("6::max_tokens", {field["key"] for field in option_fields})
            self.assertFalse({field["key"] for field in option_fields} & {
                "2::token", "3::auth_token", "4::bearer_token", "5::session_token",
            })
            selected = {
                "selection_kind": "workflow", "source": "runninghub_app", "provider_id": "runninghub",
                "region": "global", "item_id": "app-secret-fields", "expected_slot": "image",
                "expected_kind": "image", "confirmed_for_slot": True,
                "schema_fingerprint": option_fields and options.json()["options"][0]["schema_fingerprint"],
                "input_bindings": {"prompt": "1::prompt"}, "field_values": {},
            }
            saved = client.put("/api/studio/hypit/models/settings", json={"defaults": {"image": selected}})
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertNotIn(secret, saved.text)
            submitted = client.post("/api/studio/hypit/models/projects/project-a/requests", json={
                "request_id": "secret-fields-safe",
                "capability": {"module": {"name": "@laohu/studio-models", "version": "1"}, "name": "image-generation"},
                "constraints": {"kind": "image", "prompt": "一只红狐狸"},
            })
            self.assertEqual(submitted.status_code, 200, submitted.text)
            task = self.wait_for_status(client, "project-a", "secret-fields-safe", "succeeded")
            self.assertNotIn(secret, json.dumps(task, ensure_ascii=False))
            stored_task = next((self.root / "data" / "hypit_model_tasks" / "project-a").glob("*.json"))
            self.assertNotIn(secret, stored_task.read_text(encoding="utf-8"), "内部执行快照也不能保存凭据字段默认值")

            selected["input_bindings"] = {"prompt": "2::token"}
            selected["schema_fingerprint"] = options.json()["options"][0]["schema_fingerprint"]
            rejected = client.put("/api/studio/hypit/models/settings", json={"defaults": {"image": selected}})
            self.assertEqual(rejected.status_code, 400, rejected.text)
            self.assertNotIn(secret, rejected.text)

    def test_project_binding_update_rejects_stale_revision(self):
        with TestClient(self.app) as client:
            url = '/api/studio/hypit/models/projects/project-a/binding'
            initial = client.get(url).json()
            payload = {'expected_revision': initial['revision'], 'defaults': {
                'image': {'provider': 'provider-a', 'model': 'image-1', 'parameters': {'count': 1}}}}
            updated = client.put(url, json=payload)
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertEqual(updated.json()['revision'], initial['revision'] + 1)
            self.assertEqual(client.put(url, json=payload).status_code, 409)
            self.assertEqual(client.get(url).json()['defaults']['image']['model'], 'image-1')
            other = client.get('/api/studio/hypit/models/projects/project-b/binding').json()
            self.assertEqual(other['defaults']['image']['model'], 'image-1')
            self.assertEqual(other['revision'], updated.json()['revision'])

    def test_only_enabled_model_ids_are_accepted(self):
        with TestClient(self.app) as client:
            response = client.put(
                "/api/studio/hypit/models/settings",
                json={
                    "defaults": {
                        "image": {
                            "provider": "provider-a",
                            "model": "not-enabled",
                            "parameters": {},
                        }
                    }
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("启用", response.text)

    def test_runninghub_region_is_saved_projected_and_required_when_ambiguous(self):
        with TestClient(self.app) as client:
            setup = client.put(
                "/api/studio/hypit/models/settings",
                json={
                    "defaults": {
                        "image": {
                            "provider": "runninghub",
                            "model": "shared-image",
                            "region": "cn",
                            "parameters": {"count": 2},
                        }
                    }
                },
            )
            self.assertEqual(setup.status_code, 200, setup.text)
            self.assertEqual(setup.json()["defaults"]["image"]["region"], "cn")

            payload = {
                "request_id": "runninghub-cn",
                "capability": {"module": {"name": "@laohu/studio-models", "version": "1"}, "name": "image-generation"},
                "constraints": {"kind": "image", "prompt": "a red fox"},
            }
            submitted = client.post(
                "/api/studio/hypit/models/projects/project-a/requests", json=payload
            )
            self.assertEqual(submitted.status_code, 200, submitted.text)
            self.wait_for_status(client, "project-a", "runninghub-cn", "succeeded")
            validate_request = [call[1] for call in self.calls if call[0] == "validate"][-1]
            generate_request = [call[1] for call in self.calls if call[0] == "generate"][-1]
            self.assertEqual(validate_request["region"], "cn")
            self.assertEqual(generate_request["region"], "cn")

            ambiguous = client.put(
                "/api/studio/hypit/models/settings",
                json={
                    "defaults": {
                        "image": {
                            "provider": "runninghub",
                            "model": "shared-image",
                            "parameters": {"count": 1},
                        }
                    }
                },
            )
            self.assertEqual(ambiguous.status_code, 400, ambiguous.text)
            self.assertIn("region", ambiguous.text.lower())

            explicit_global = client.post(
                "/api/studio/hypit/models/projects/project-a/requests",
                json={
                    **payload,
                    "request_id": "runninghub-global",
                    "constraints": {
                        "kind": "image",
                        "prompt": "a blue fox",
                        "region": "global",
                        "parameters": {"count": 1},
                    },
                },
            )
            self.assertEqual(explicit_global.status_code, 200, explicit_global.text)
            self.wait_for_status(client, "project-a", "runninghub-global", "succeeded")
            explicit_request = [call[1] for call in self.calls if call[0] == "validate"][-1]
            self.assertEqual(explicit_request["region"], "global")

    def test_native_projection_keeps_media_roles_and_requires_music_configuration(self):
        with TestClient(self.app) as client:
            setup = client.put(
                "/api/studio/hypit/models/settings",
                json={
                    "defaults": {
                        "video": {
                            "provider": "provider-a",
                            "model": "video-1",
                            "parameters": {"duration": 5},
                        }
                    }
                },
            )
            self.assertEqual(setup.status_code, 200, setup.text)
            payload = {
                "request_id": "typed-media",
                "capability": {"module": {"name": "@laohu/studio-models", "version": "1"}, "name": "video-generation"},
                "constraints": {
                    "kind": "video",
                    "prompt": "a fox walks",
                    "inputs": {
                        "reference": ["data:image/png;base64,AA=="],
                        "source_video": ["data:video/mp4;base64,AA=="],
                        "reference_audio": ["data:audio/wav;base64,AA=="],
                    },
                },
            }
            submitted = client.post(
                "/api/studio/hypit/models/projects/project-a/requests", json=payload
            )
            self.assertEqual(submitted.status_code, 200, submitted.text)
            self.wait_for_status(client, "project-a", "typed-media", "succeeded")
            projected = [call[1] for call in self.calls if call[0] == "validate"][-1]
            self.assertEqual(projected["inputs"]["reference"], ["data:image/png;base64,AA=="])
            self.assertEqual(projected["inputs"]["source_video"], ["data:video/mp4;base64,AA=="])
            self.assertEqual(projected["inputs"]["reference_audio"], ["data:audio/wav;base64,AA=="])

            unsupported = client.post(
                "/api/studio/hypit/models/projects/project-a/requests",
                json={
                    **payload,
                    "request_id": "music-request",
                    "capability": {"module": {"name": "@laohu/studio-models", "version": "1"}, "name": "music-generation"},
                    "constraints": {"kind": "music", "prompt": "music"},
                },
            )
            self.assertEqual(unsupported.status_code, 400, unsupported.text)
            self.assertIn("请先为 music 配置工作台模型", unsupported.text)

    def test_configured_music_request_uses_music_slot_and_returns_audio(self):
        with TestClient(self.app) as client:
            saved = client.put('/api/studio/hypit/models/settings', json={'defaults': {
                'music': {'provider':'provider-a', 'model':'music-1', 'parameters':{'instrumental':True}}
            }})
            self.assertEqual(saved.status_code, 200, saved.text)
            submitted = client.post('/api/studio/hypit/models/projects/project-a/requests', json={
                'request_id':'configured-music',
                'capability': {'module':{'name':'@laohu/studio-models','version':'1'}, 'name':'music-generation'},
                'constraints': {
                    'kind':'music', 'prompt':'fixture instrumental music',
                    'parameters': {'instrumental': True},
                    'inputs': {'reference_audio': ['data:audio/wav;base64,AA==']},
                },
            })
            self.assertEqual(submitted.status_code, 200, submitted.text)
            done = self.wait_for_status(client, 'project-a', 'configured-music', 'succeeded')
            request = next(call[1] for call in self.calls if call[0] == 'generate')
            self.assertEqual(request['kind'], 'music')
            self.assertEqual(request['model'], 'music-1')
            self.assertTrue(request['parameters']['instrumental'])
            self.assertEqual(request['inputs']['reference_audio'], ['data:audio/wav;base64,AA=='])
            self.assertEqual(request['input_counts']['audio'], 1)
            self.assertEqual(done['result']['audios'][0]['url'], '/api/results/fixture-music.wav')

            rejected = client.post('/api/studio/hypit/models/projects/project-a/requests', json={
                'request_id': 'invalid-music-image',
                'capability': {'module': {'name': '@laohu/studio-models', 'version': '1'}, 'name': 'music-generation'},
                'constraints': {
                    'kind': 'music', 'prompt': 'fixture music',
                    'inputs': {'reference': ['data:image/png;base64,AA==']},
                },
            })
            self.assertEqual(rejected.status_code, 400, rejected.text)
            self.assertIn('music 能力不支持输入类型', rejected.text)
            self.assertEqual(len([call for call in self.calls if call[0] == 'generate']), 1)

    def test_model_only_save_clears_stale_parameters_and_request_supplies_values(self):
        with TestClient(self.app) as client:
            saved = client.put('/api/studio/hypit/models/settings', json={
                'parameter_mode': 'per_request',
                'defaults': {'image': {'provider': 'provider-a', 'model': 'image-1',
                                       'parameters': {'resolution': 'obsolete-value'}}},
            })
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()['defaults']['image']['parameters'], {})
            request = {'request_id': 'per-request-parameters', 'constraints': {
                'kind': 'image', 'prompt': 'fixture', 'parameters': {'count': 2}}}
            response = client.post('/api/studio/hypit/models/projects/project-a/requests', json=request)
            self.assertEqual(response.status_code, 200, response.text)
            self.wait_for_status(client, 'project-a', request['request_id'], 'succeeded')
            self.assertEqual(next(call[1] for call in self.calls if call[0] == 'generate')['parameters'], {'count': 2})
            request['request_id'] = 'invalid-request-parameters'
            request['constraints']['parameters'] = {'count': 3}
            response = client.post('/api/studio/hypit/models/projects/project-a/requests', json=request)
            self.assertEqual(response.status_code, 400, response.text)

    def test_request_id_is_idempotent_cross_project_isolated_and_failure_is_not_retried(self):
        with TestClient(self.app) as client:
            setup = client.put(
                "/api/studio/hypit/models/settings",
                json={
                    "defaults": {
                        "image": {
                            "provider": "provider-a",
                            "model": "image-1",
                            "parameters": {"count": 1},
                        }
                    }
                },
            )
            self.assertEqual(setup.status_code, 200)

            payload = {
                "request_id": "same-request",
                "capability": {"module": {"name": "@laohu/studio-models", "version": "1"}, "name": "image-generation"},
                "constraints": {"kind": "image", "prompt": "a red fox"},
            }
            first = client.post(
                "/api/studio/hypit/models/projects/project-a/requests", json=payload
            )
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()["status"], "queued")
            done = self.wait_for_status(client, "project-a", "same-request", "succeeded")
            repeat = client.post(
                "/api/studio/hypit/models/projects/project-a/requests", json=payload
            )
            self.assertEqual(repeat.status_code, 200, repeat.text)
            self.assertEqual(repeat.json()["task_id"], done["task_id"])
            self.assertEqual(len([call for call in self.calls if call[0] == "generate"]), 1)

            current_settings = client.get("/api/studio/hypit/models/settings").json()
            changed = client.put(
                "/api/studio/hypit/models/settings",
                json={
                    "expected_revision": current_settings["revision"],
                    "defaults": {
                        "image": {
                            "provider": "provider-a",
                            "model": "image-2",
                            "parameters": {"count": 1},
                        }
                    },
                },
            )
            self.assertEqual(changed.status_code, 200, changed.text)
            after_setting_change = client.post(
                "/api/studio/hypit/models/projects/project-a/requests", json=payload
            )
            self.assertEqual(after_setting_change.status_code, 200, after_setting_change.text)
            self.assertEqual(after_setting_change.json()["task_id"], done["task_id"])
            self.assertEqual(after_setting_change.json()["request"]["model"], "image-1")
            self.assertEqual(len([call for call in self.calls if call[0] == "generate"]), 1)

            different_input = {
                **payload,
                "constraints": {**payload["constraints"], "prompt": "a blue fox"},
            }
            conflict = client.post(
                "/api/studio/hypit/models/projects/project-a/requests", json=different_input
            )
            self.assertEqual(conflict.status_code, 409, conflict.text)
            self.assertIn("不同输入", conflict.text)

            other = client.post(
                "/api/studio/hypit/models/projects/project-b/requests", json=payload
            )
            self.assertEqual(other.status_code, 200, other.text)
            self.assertEqual(other.json()["request"]["model"], "image-2")
            self.wait_for_status(client, "project-b", "same-request", "succeeded")
            self.assertEqual(len([call for call in self.calls if call[0] == "generate"]), 2)

            self.fail_generation = True
            failed_payload = {**payload, "request_id": "failed-request"}
            failed = client.post(
                "/api/studio/hypit/models/projects/project-a/requests", json=failed_payload
            )
            self.assertEqual(failed.status_code, 200, failed.text)
            failed_task = self.wait_for_status(client, "project-a", "failed-request", "failed")
            again = client.post(
                "/api/studio/hypit/models/projects/project-a/requests", json=failed_payload
            )
            self.assertEqual(again.status_code, 200, again.text)
            self.assertEqual(again.json()["task_id"], failed_task["task_id"])
            self.assertEqual(len([call for call in self.calls if call[0] == "generate"]), 3)


if __name__ == "__main__":
    unittest.main()
