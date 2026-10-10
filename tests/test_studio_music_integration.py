"""独立音乐项目的版本、共享结果和生成恢复回归。"""
from __future__ import annotations

import asyncio
import io
import copy
import tempfile
import unittest
import wave
import threading
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from project_storage import ProjectStorage
from studio_music import MusicPutRequest, StudioMusicStore
from studio_music_generation import StudioMusicGenerationBridge
from studio_connection import create_connection_router
from studio_hypit_flow import HypitFlowRunner
from studio_module_models import module_descriptor, music_slot_descriptors, validate_slot_binding
from studio_projects import StudioProjectStore, create_studio_projects_router
from tests.test_studio_projects import FakeCanvasAdapter, TEST_TMP_ROOT


def _tiny_wav() -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(1)
        audio.setframerate(8000)
        audio.writeframes(bytes([128] * 80))
    return stream.getvalue()


def _tiny_png() -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">2I5B", 1, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00\x20\x80\xc0")) + chunk(b"IEND", b"")


def _music_canvas(node_type: str = "smart-music-generator", revision: int = 4) -> dict:
    source = {"id": "music-source", "type": node_type, "title": "歌曲生成", "outputKind": "audio",
              "runSettings": {"musicProvider": "fixture-provider", "musicModel": "fixture-song-model",
                              "capabilityParameters": {"fixture-song-model": {"existing": "keep"}}}}
    return {"id": "music-settings", "title": "音乐配置图", "kind": "smart", "project": "__music_settings__",
            "revision": revision, "nodes": [source,
            {"id": "music-output", "type": "smart-hypit-output", "hypitSlot": "music"}],
            "connections": [{"from": "music-source", "to": "music-output", "kind": "input"}],
            "viewport": {"x": 0, "y": 0, "scale": 1}, "logs": [], "settings": {}}


class FakeMusicRunner:
    """只记录共享画布任务；测试不会接触外部供应商。"""

    canvas_id = "music-settings"

    def __init__(self, storage: ProjectStorage):
        self.storage = storage
        self.flows: dict[str, dict] = {}
        self.accepted_count = 0

    async def submit(self, slot, output_node_id, request_id, payload, test=False, *, trusted_context=None):
        del test
        run = self.storage.prepare_run(
            canvas_id=self.canvas_id,
            node_id=output_node_id,
            client_operation_id=request_id,
            standard_request={"node_type": "music_generation", "slot": slot, **copy.deepcopy(payload)},
            platform_request={},
            capability_snapshot={"module_id": "music", "trusted_context": copy.deepcopy(dict(trusted_context or {}))},
        )
        run_id = str(run["run_id"])
        if run_id not in self.flows:
            self.accepted_count += 1
            self.flows[run_id] = {
                "run_id": run_id,
                "canvas_id": self.canvas_id,
                "module_id": "music",
                "status": "queued",
                "slot": slot,
                "output_node_id": output_node_id,
                "output_kind": "",
                "media": [],
                "trusted_context": copy.deepcopy(dict(trusted_context or {})),
            }
            self.storage.create_canvas_task({
                "id": run_id,
                "canvas_id": self.canvas_id,
                "module_id": "music",
                "node_id": output_node_id,
                "kind": "hypit_settings_flow",
                "status": "queued",
                "result": {"media": []},
            })
        flow = self.flows[run_id]
        return {"run_id": run_id, "status": flow["status"], "slot": slot, "output_node_id": output_node_id}

    def get(self, run_id):
        value = self.flows.get(run_id)
        return copy.deepcopy(value) if value else None


class SettingsService:
    def __init__(self):
        self.canvas = {
            "id": "music-settings",
            "revision": 7,
            "nodes": [
                {"id": "music-source", "type": "smart-music-generator"},
                {"id": "music-output", "type": "smart-hypit-output", "hypitSlot": "music"},
            ],
            "connections": [{"from": "music-source", "to": "music-output", "kind": "input"}],
        }

    def ensure_canvas(self):
        return copy.deepcopy(self.canvas)


class StudioMusicIntegrationTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT)
        self.root = Path(self.temporary.name)
        self.project_store = StudioProjectStore(self.root, FakeCanvasAdapter())
        self.project = self.project_store.create("music", "隔离歌曲")
        self.storage = ProjectStorage(self.root / "managed")
        self.storage.ensure_layout()

    def tearDown(self):
        self.temporary.cleanup()

    def _resolve_media(self, asset_id: str, result_id: str):
        if asset_id or not result_id:
            return None
        record = self.storage.get_result(result_id)
        path = self.storage.result_path(result_id) if record else None
        if not record or not path or not path.is_file() or path.stat().st_size <= 0:
            return None
        return {
            "url": self.storage.result_url(result_id),
            "name": record.get("display_name") or "",
            "mime": record.get("mime") or "",
            "kind": record.get("kind") or "",
            "path": str(path),
        }

    def _read_media(self, asset_id: str, result_id: str):
        reference = self._resolve_media(asset_id, result_id)
        if not reference:
            return None
        return Path(reference["path"]).read_bytes()

    def _music_store(self):
        return StudioMusicStore(
            self.project_store,
            resolve_media_reference=self._resolve_media,
            read_media_reference=self._read_media,
        )

    def _managed_result(self, name: str, content: bytes):
        source = self.root / name
        source.write_bytes(content)
        return self.storage.store_result_file(source, name)

    def test_music_crud_source_versions_and_revision_conflict(self):
        store = self._music_store()
        app = FastAPI()
        app.include_router(create_studio_projects_router(self.root, FakeCanvasAdapter(), store=self.project_store))
        app.include_router(store.router())
        with TestClient(app) as client:
            listing = client.get("/api/studio/projects?module=music")
            self.assertEqual(listing.status_code, 200, listing.text)
            self.assertEqual(listing.json()["projects"][0]["id"], self.project["id"])
            self.assertEqual(listing.json()["projects"][0]["url"], f"/static/music.html?id={self.project['id']}")

            first = client.get(f"/api/studio/music/{self.project['id']}")
            self.assertEqual(first.status_code, 200, first.text)
            initial = first.json()
            self.assertEqual(initial["revision"], 1)
            self.assertEqual(initial["source_versions"], [])
            self.assertRegex(initial["source_sha256"], r"^[a-f0-9]{64}$")

            updated = client.put(f"/api/studio/music/{self.project['id']}", json={
                "expected_revision": 1,
                "title": "海边的歌",
                "lyrics": "潮声渐远，灯火初明。",
                "style_prompt": "木吉他与轻柔女声",
            })
            self.assertEqual(updated.status_code, 200, updated.text)
            first_version = updated.json()["source_versions"][0]
            self.assertEqual(first_version["lyrics"], "潮声渐远，灯火初明。")
            self.assertEqual(first_version["style_prompt"], "木吉他与轻柔女声")
            self.assertEqual(first_version["source_sha256"], updated.json()["source_sha256"])
            self.assertEqual(updated.json()["audio_variants"], [])

            changed = client.put(f"/api/studio/music/{self.project['id']}", json={
                "expected_revision": 2, "lyrics": "潮声退去，天色渐白。",
            })
            self.assertEqual(changed.status_code, 200, changed.text)
            versions = changed.json()["source_versions"]
            self.assertEqual(len(versions), 2)
            self.assertEqual(versions[0]["lyrics"], "潮声渐远，灯火初明。")
            self.assertEqual(versions[1]["lyrics"], "潮声退去，天色渐白。")
            self.assertNotEqual(versions[0]["source_sha256"], versions[1]["source_sha256"])

            stale = client.put(f"/api/studio/music/{self.project['id']}", json={
                "expected_revision": 1, "style_prompt": "过期草稿",
            })
            self.assertEqual(stale.status_code, 409)
            current = client.get(f"/api/studio/music/{self.project['id']}").json()
            self.assertEqual(current["style_prompt"], "木吉他与轻柔女声")
            self.assertEqual(current["revision"], 3)

    def test_music_generation_http_routes_wrap_safe_generation_projection(self):
        store = self._music_store()
        current = store.put(self.project["id"], MusicPutRequest.model_validate({
            "expected_revision": 1, "title": "接口歌曲", "lyrics": "接口歌词", "style_prompt": "接口风格",
        }))
        settings = SettingsService()
        runner = FakeMusicRunner(self.storage)

        def prepare_request(*, source_snapshot, song, **kwargs):
            del song, kwargs
            return {"prompt": source_snapshot["lyrics"], "parameters": {"style_prompt": source_snapshot["style_prompt"]}}

        bridge = StudioMusicGenerationBridge(
            music_store=store, runner=runner, storage=self.storage, settings_service=settings,
            prepare_request=prepare_request,
        )
        app = FastAPI()
        app.include_router(store.router(submit_generation=bridge.submit, get_generation=bridge.get,
                                        list_generations=bridge.list))
        with TestClient(app) as client:
            payload = {
                "purpose": "song", "slot": "music", "output_node_id": "music-output",
                "client_operation_id": "http-music-op", "base_revision": current["revision"],
                "request": {"instruction": "按已保存内容生成"},
            }
            submitted = client.post(f"/api/studio/music/{self.project['id']}/generations", json=payload)
            self.assertEqual(submitted.status_code, 200, submitted.text)
            body = submitted.json()
            self.assertEqual(set(body), {"generation"})
            generation = body["generation"]
            run_id = generation["run_id"]
            self.assertEqual(generation["purpose"], "song")
            self.assertEqual(generation["module_id"], "music")
            self.assertEqual(generation["client_operation_id"], "http-music-op")
            for private_key in ("trusted_context", "private_snapshot", "path", "lyrics", "style_prompt", "request"):
                self.assertNotIn(private_key, generation)

            queried = client.get(f"/api/studio/music/{self.project['id']}/generations/{run_id}")
            self.assertEqual(queried.status_code, 200, queried.text)
            response = queried.json()
            self.assertEqual(set(response), {"generation", "music"})
            self.assertEqual(response["generation"]["run_id"], run_id)
            self.assertEqual(response["generation"]["accepted_revision"], current["revision"])
            self.assertEqual(response["music"]["lyrics"], "接口歌词")
            listing = client.get(f"/api/studio/music/{self.project['id']}/generations")
            self.assertEqual(listing.status_code, 200, listing.text)
            self.assertEqual([item["run_id"] for item in listing.json()["generations"]], [run_id])

            replay = client.post(f"/api/studio/music/{self.project['id']}/generations", json=payload)
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json()["generation"]["run_id"], run_id)
            conflict = client.post(f"/api/studio/music/{self.project['id']}/generations", json={
                **payload, "request": {"instruction": "different content"},
            })
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(runner.accepted_count, 1)

    def test_dynamic_field_projection_keeps_exact_text_audio_keys_and_hides_secret_fields(self):
        import main

        fields = main.studio_music_public_dynamic_fields([
            {"nodeId": "flow", "fieldName": "lyrics", "fieldType": "string", "label": "歌词"},
            {"nodeId": "flow", "fieldName": "reference_audio", "fieldType": "audio", "label": "参考音频"},
            # A provider may return only a compound key instead of separate node/name fields.
            {"key": "flow::api_key", "fieldType": "string", "label": "配置"},
            {"nodeId": "flow", "fieldName": "seed", "fieldType": "integer", "label": "Seed"},
        ], "smart-ai-app")
        self.assertEqual(
            fields,
            [
                {"targetFieldKey": "flow::lyrics", "label": "歌词", "kind": "text", "required": False},
                {"targetFieldKey": "flow::reference_audio", "label": "参考音频", "kind": "audio", "required": False},
            ],
        )

    def test_dynamic_music_mapper_rechecks_current_schema_and_rejects_unknown_parameters(self):
        import main

        canvas = _music_canvas("smart-ai-app", revision=12)
        canvas["nodes"][0]["runSettings"] = {"rhMode": "app", "rhConfigKey": "app:fixture"}
        source_snapshot = {
            "title": "测试标题", "lyrics": "测试歌词", "style_prompt": "测试风格",
            "notes": "", "cover_prompt": "", "reference_audio_refs": [],
        }
        schema = [
            {"nodeId": "flow", "fieldName": "lyrics", "fieldType": "string", "enabled": True},
            {"nodeId": "flow", "fieldName": "style", "fieldType": "textarea", "enabled": True},
            {"nodeId": "flow", "fieldName": "reference_audio", "fieldType": "audio", "enabled": True},
            {"key": "flow::enabled", "fieldType": "boolean", "enabled": True},
            {"key": "flow::seed", "fieldType": "integer", "enabled": True},
            {"nodeId": "flow", "fieldName": "disabled_text", "fieldType": "string", "enabled": False},
        ]

        def prepare(request):
            return asyncio.run(main.studio_music_prepare_generation_request(
                canvas=canvas, purpose="song", slot="music", output_node_id="music-output",
                song={}, source_snapshot=source_snapshot, request=request,
            ))

        with patch.object(main, "studio_app_fields", return_value=schema):
            valid = prepare({"input_fields": {
                "lyrics": {"node_id": "music-source", "targetFieldKey": "flow::lyrics"},
                "style_prompt": {"node_id": "music-source", "targetFieldKey": "flow::style"},
            }, "parameters": {"flow::enabled": False, "flow::seed": 0}})
            self.assertEqual(
                [(item["targetFieldKey"], item["value"]) for item in valid["field_inputs"]],
                [("flow::lyrics", "测试歌词"), ("flow::style", "测试风格")],
            )
            self.assertIs(valid["parameters"]["flow::enabled"], False)
            self.assertEqual(valid["parameters"]["flow::seed"], 0)

            for role, field_key in (
                ("lyrics", "flow::deleted"),
                ("lyrics", "flow::reference_audio"),  # Existing key, wrong kind for text.
                ("lyrics", "flow::disabled_text"),
            ):
                with self.subTest(role=role, field_key=field_key):
                    with self.assertRaises(HTTPException) as invalid:
                        prepare({"input_fields": {
                            role: {"node_id": "music-source", "targetFieldKey": field_key},
                            "style_prompt": {"node_id": "music-source", "targetFieldKey": "flow::style"},
                        }})
                    self.assertEqual(invalid.exception.status_code, 400)

            with self.assertRaises(HTTPException) as unknown_parameter:
                prepare({"input_fields": {
                    "lyrics": {"node_id": "music-source", "targetFieldKey": "flow::lyrics"},
                    "style_prompt": {"node_id": "music-source", "targetFieldKey": "flow::style"},
                }, "parameters": {"unconfirmed": 1}})
            self.assertEqual(unknown_parameter.exception.status_code, 400)
            with self.assertRaises(HTTPException) as wrong_parameter_type:
                prepare({"input_fields": {
                    "lyrics": {"node_id": "music-source", "targetFieldKey": "flow::lyrics"},
                    "style_prompt": {"node_id": "music-source", "targetFieldKey": "flow::style"},
                }, "parameters": {"flow::enabled": "false"}})
            self.assertEqual(wrong_parameter_type.exception.status_code, 400)

        # When every field is explicitly disabled, none may become a candidate through
        # the projection's empty-enabled-list fallback.
        disabled_schema = [
            {"nodeId": "flow", "fieldName": "lyrics", "fieldType": "string", "enabled": False},
            {"nodeId": "flow", "fieldName": "style", "fieldType": "textarea", "enabled": False},
        ]
        with patch.object(main, "studio_app_fields", return_value=disabled_schema):
            with self.assertRaises(HTTPException) as all_disabled:
                prepare({"input_fields": {
                    "lyrics": {"node_id": "music-source", "targetFieldKey": "flow::lyrics"},
                    "style_prompt": {"node_id": "music-source", "targetFieldKey": "flow::style"},
                }})
        self.assertEqual(all_disabled.exception.status_code, 400)

    def test_music_input_fields_endpoint_resolves_selected_output_and_projects_safe_schema(self):
        import main

        canvas = _music_canvas("smart-ai-app", revision=12)
        schema = [
            {"nodeId": "flow", "fieldName": "lyrics", "fieldType": "string", "label": "歌词", "enabled": True},
            {"nodeId": "flow", "fieldName": "reference_audio", "fieldType": "audio", "label": "参考音频", "enabled": True},
            {"key": "flow::api_key", "fieldType": "string", "label": "连接凭据", "enabled": True},
            {"nodeId": "flow", "fieldName": "seed", "fieldType": "integer", "label": "Seed", "enabled": True},
        ]
        with patch.object(main.MUSIC_SETTINGS_CANVAS_SERVICE, "ensure_canvas", return_value=canvas), \
                patch.object(main, "studio_app_fields", return_value=schema):
            projection = asyncio.run(main.studio_music_dynamic_input_fields("music-output"))
        self.assertEqual(projection["canvas_revision"], 12)
        self.assertEqual(projection["output_node_id"], "music-output")
        self.assertEqual(projection["slot"], "music")
        self.assertEqual(projection["nodes"][0]["node_id"], "music-source")
        self.assertEqual([field["targetFieldKey"] for field in projection["nodes"][0]["fields"]],
                         ["flow::lyrics", "flow::reference_audio"])

    def test_agent_can_attach_only_resolvable_shared_media_without_forging_history(self):
        store = self._music_store()
        audio = self._managed_result("agent-song.wav", _tiny_wav())
        cover = self._managed_result("agent-cover.png", _tiny_png())
        music = store.put(self.project["id"], MusicPutRequest.model_validate({
            "expected_revision": 1,
            "title": "外部 Agent 作品",
            "lyrics": "测试歌词",
            "audio_refs": [{"result_id": audio["id"]}],
            "cover_refs": [{"result_id": cover["id"]}],
        }))
        self.assertEqual(len(music["audio_variants"]), 1)
        self.assertEqual(len(music["cover_variants"]), 1)
        attached = music["audio_variants"][0]
        self.assertEqual(attached["origin"], "agent")
        self.assertEqual(attached["run_id"], "")
        self.assertEqual(attached["snapshot"]["lyrics"], "测试歌词")
        self.assertEqual(attached["snapshot"]["accepted_revision"], music["revision"])
        self.assertNotIn("path", attached)
        record = self.project_store.read_music_record(self.project["id"])
        self.assertNotIn("path", record["music"]["audio_variants"][0])

        with self.assertRaises(ValidationError):
            MusicPutRequest.model_validate({
                "expected_revision": music["revision"],
                "audio_refs": [{"result_id": audio["id"], "run_id": "forged-run", "snapshot": {"lyrics": "fake"}}],
            })

        with self.assertRaises(HTTPException) as missing:
            store.put(self.project["id"], MusicPutRequest.model_validate({
                "expected_revision": music["revision"],
                "audio_refs": [{"result_id": "res_missing"}],
            }))
        self.assertEqual(missing.exception.status_code, 400)

    def test_score_references_are_retained_in_immutable_source_snapshots(self):
        store = self._music_store()
        score = self._managed_result("song-score.txt", b"X:1\nT:Song\nM:4/4\nL:1/4\nK:C\nC D E F|G A B c|\n")
        updated = store.put(self.project["id"], MusicPutRequest.model_validate({
            "expected_revision": 1, "title": "带乐谱的歌",
            "score_refs": [{"result_id": score["id"], "format": "abc"}],
        }))
        reference = updated["score_refs"][0]
        self.assertEqual(len(updated["source_versions"]), 1)
        self.assertEqual(updated["source_versions"][0]["score_refs"], [reference])
        self.assertEqual(updated["source_versions"][0]["source_sha256"], updated["source_sha256"])
        self.assertNotIn("path", updated["source_versions"][0]["score_refs"][0])

        settings = SettingsService()
        runner = FakeMusicRunner(self.storage)
        prepared = []

        def prepare_request(*, source_snapshot, **kwargs):
            del kwargs
            prepared.append(copy.deepcopy(source_snapshot))
            return {"prompt": source_snapshot["lyrics"]}

        bridge = StudioMusicGenerationBridge(
            music_store=store, runner=runner, storage=self.storage, settings_service=settings,
            prepare_request=prepare_request,
        )
        asyncio.run(bridge.submit(self.project["id"], {
            "purpose": "song", "slot": "music", "output_node_id": "music-output",
            "client_operation_id": "music-score-snapshot", "base_revision": updated["revision"],
        }, {"accepted_revision": updated["revision"], "source_hash": updated["source_sha256"]}))
        self.assertEqual(prepared[0]["score_refs"], [reference])

    def test_music_generation_uses_shared_graph_and_recovers_same_snapshot_once(self):
        store = self._music_store()
        initial = store.put(self.project["id"], MusicPutRequest.model_validate({
            "expected_revision": 1,
            "title": "清晨",
            "lyrics": "旧歌词，作为已接受快照。",
            "style_prompt": "原声钢琴",
        }))
        settings = SettingsService()
        runner = FakeMusicRunner(self.storage)
        prepared = []

        def prepare_request(*, canvas, purpose, slot, output_node_id, song, source_snapshot, request):
            self.assertEqual(canvas["id"], "music-settings")
            self.assertEqual(purpose, "song")
            self.assertEqual(slot, "music")
            self.assertEqual(output_node_id, "music-output")
            self.assertTrue(any(edge["to"] == output_node_id for edge in canvas["connections"]))
            prepared.append(copy.deepcopy(source_snapshot))
            return {"prompt": f"{source_snapshot['title']}\n{source_snapshot['lyrics']}\n{source_snapshot['style_prompt']}",
                    "source_sha256": song["source_sha256"]}

        bridge = StudioMusicGenerationBridge(
            music_store=store,
            runner=runner,
            storage=self.storage,
            settings_service=settings,
            prepare_request=prepare_request,
        )
        payload = {
            "purpose": "song", "slot": "music", "output_node_id": "music-output",
            "client_operation_id": "music-operation-1", "base_revision": initial["revision"],
            "request": {"instruction": "使用已保存歌词"},
        }
        accepted = {"accepted_revision": initial["revision"], "source_hash": initial["source_sha256"]}
        submitted = asyncio.run(bridge.submit(self.project["id"], payload, accepted))
        run_id = submitted["run_id"]
        self.assertEqual(submitted["project_id"], self.project["id"])
        self.assertEqual(runner.canvas_id, "music-settings")
        self.assertEqual(runner.accepted_count, 1)
        self.assertEqual(prepared[0]["lyrics"], "旧歌词，作为已接受快照。")

        edited = store.put(self.project["id"], MusicPutRequest.model_validate({
            "expected_revision": initial["revision"], "lyrics": "新歌词，不应改写已接受任务。",
        }))
        self.assertEqual(len(edited["source_versions"]), 2)
        replay = asyncio.run(bridge.submit(self.project["id"], payload, accepted))
        self.assertEqual(replay["run_id"], run_id)
        self.assertEqual(runner.accepted_count, 1)
        self.assertEqual(len(prepared), 1)

        conflicting = {**payload, "request": {"instruction": "同一 ID 的不同请求"}}
        with self.assertRaises(HTTPException) as conflict:
            asyncio.run(bridge.submit(self.project["id"], conflicting, accepted))
        self.assertEqual(conflict.exception.status_code, 409)

        other_output = {**payload, "output_node_id": "another-output"}
        with self.assertRaises(HTTPException) as output_conflict:
            asyncio.run(bridge.submit(self.project["id"], other_output, accepted))
        self.assertEqual(output_conflict.exception.status_code, 409)
        self.assertEqual(runner.accepted_count, 1)

        audio = self._managed_result("completed-song.wav", _tiny_wav())
        flow = runner.flows[run_id]
        flow.update(status="succeeded", output_kind="audio", media=[{
            "kind": "audio", "resultId": audio["id"], "url": audio["url"],
        }])
        before_association = store.get(self.project["id"])
        first_read = asyncio.run(bridge.get(self.project["id"], run_id))
        self.assertEqual(first_read["status"], "succeeded")
        associated = store.get(self.project["id"])
        self.assertEqual(associated["lyrics"], "新歌词，不应改写已接受任务。")
        self.assertEqual(len(associated["audio_variants"]), 1)
        variant = associated["audio_variants"][0]
        self.assertEqual(variant["snapshot"]["lyrics"], "旧歌词，作为已接受快照。")
        self.assertEqual(variant["snapshot"]["source_sha256"], initial["source_sha256"])
        self.assertEqual(variant["snapshot"]["accepted_revision"], initial["revision"])
        after_first_association = associated["revision"]

        asyncio.run(bridge.get(self.project["id"], run_id))
        second_read = store.get(self.project["id"])
        self.assertEqual(len(second_read["audio_variants"]), 1)
        self.assertEqual(second_read["revision"], after_first_association,
                         "恢复/重复轮询同一任务不得重复递增歌曲修订")
        self.assertLess(before_association["revision"], after_first_association)
        self.assertEqual(runner.accepted_count, 1)

    def test_score_format_rejects_content_that_disagrees_with_extension_and_mime(self):
        store = self._music_store()
        invalid_midi = self._managed_result("mislabelled.mid", b"this is not a MIDI stream")
        with self.assertRaises(HTTPException) as mismatch:
            store.put(self.project["id"], MusicPutRequest.model_validate({
                "expected_revision": 1,
                "score_refs": [{"result_id": invalid_midi["id"], "format": "midi"}],
            }))
        self.assertEqual(mismatch.exception.status_code, 400)

    def test_music_module_model_slots_and_bilingual_agent_connection(self):
        module = module_descriptor("music")
        self.assertEqual(module["executor_id"], "music-settings-canvas-execution")
        slots = {slot["id"]: slot for slot in music_slot_descriptors()}
        self.assertEqual(set(slots), {"music", "image"})
        self.assertEqual(slots["music"]["expected_output"]["media_type"], "audio")
        self.assertEqual(slots["image"]["expected_output"]["media_type"], "image")
        self.assertEqual(slots["music"]["supported_input_roles"], ["prompt", "reference_audio"])
        valid = {"node_type": "music_generation", "output_contract": "audio,min=1,max=1",
                 "operation": "music_song", "readiness": "ready", "runnable": True}
        self.assertTrue(validate_slot_binding("music", "music", valid)["valid"])

        app = FastAPI()
        app.include_router(create_connection_router(lambda project_id, module_id: {
            "id": project_id, "module": module_id, "name": "测试歌曲",
        }))
        with TestClient(app) as client:
            document = client.get("/api/studio/projects/song-1/connection.md?module=music&lang=zh")
            self.assertEqual(document.status_code, 200, document.text)
            self.assertIn("source_versions", document.text)
            self.assertIn("client_operation_id", document.text)
            self.assertIn("不自动创作或生成", document.text)
            english = client.get("/api/studio/projects/song-1/connection.md?module=music&lang=en")
            self.assertEqual(english.status_code, 200, english.text)
            self.assertIn("immutable lyric/style/source snapshots", english.text)
            self.assertIn("do not create content or run a model", english.text)
            self.assertEqual(client.get("/api/studio/projects/song-1/connection.md?module=unknown").status_code, 404)

    def test_main_openapi_registers_music_project_and_shared_graph_routes(self):
        import main

        paths = main.app.openapi()["paths"]
        self.assertIn("/api/studio/music/{project_id}", paths)
        self.assertEqual(set(paths["/api/studio/music/{project_id}"]), {"get", "put"})
        self.assertEqual(set(paths["/api/studio/music/{project_id}/generations"]), {"get", "post"})
        self.assertIn("get", paths["/api/studio/music/{project_id}/generations/{run_id}"])
        self.assertIn("/api/studio/music/settings-canvas", paths)
        self.assertIn("/api/studio/music/settings-canvas/reset", paths)
        self.assertIn("/api/agent/canvases/{canvas_id}/commands", paths)

    def test_shared_runner_preserves_song_inputs_parameters_and_private_dynamic_fields(self):
        import main

        store = self._music_store()
        initial = store.put(self.project["id"], MusicPutRequest.model_validate({
            "expected_revision": 1, "title": "测试标题", "lyrics": "第一行歌词", "style_prompt": "温暖民谣",
        }))
        settings = SettingsService()
        settings.canvas = _music_canvas()
        settings_before = copy.deepcopy(settings.canvas)
        seen = {"prepared": [], "requests": [], "resolved": [], "executed": []}

        async def prepare_node_request(canvas, node, request_id, upstream, user_request, *, preflight=False):
            del request_id, upstream
            seen["prepared"].append((preflight, copy.deepcopy(node.get("manualInputRefs") or []),
                                      copy.deepcopy(node.get("runSettings") or {}), copy.deepcopy(user_request),
                                      copy.deepcopy(canvas.get("connections") or [])))
            return {"node_id": node["id"], "request": copy.deepcopy(dict(user_request)),
                    "inputs": copy.deepcopy(node.get("manualInputRefs") or []), "preflight": preflight}

        async def preflight_node(canvas, node, request, request_id):
            del canvas, node, request_id
            seen["requests"].append(copy.deepcopy(request))
            return {"ready": True}

        async def execute_node(canvas, node, request, request_id, resolved, on_submitted):
            del canvas, node, request_id
            seen["resolved"].append(copy.deepcopy(resolved))
            seen["executed"].append(copy.deepcopy(request))
            on_submitted({"provider_task_id": "fixture-provider-task"})
            return {"synthetic": True}

        async def collect_results(raw, request, task):
            del raw, request, task
            wav_path = self.root / "runner-output.wav"
            wav_path.write_bytes(_tiny_wav())
            item = self.storage.store_result_file(wav_path, wav_path.name)
            return [{"kind": "audio", "resultId": item["id"], "url": item["url"],
                     "name": item["display_name"], "path": str(wav_path)}]

        runner = HypitFlowRunner(
            load_canvas=lambda canvas_id: copy.deepcopy(settings.canvas), storage=self.storage,
            prepare_node_request=prepare_node_request, preflight_node=preflight_node,
            execute_node=execute_node, collect_results=collect_results, notify=lambda *_: None,
            lock=threading.RLock(), now_ms=lambda: 1000, canvas_id="music-settings", module_id="music",
        )
        bridge = StudioMusicGenerationBridge(
            music_store=store, runner=runner, storage=self.storage, settings_service=settings,
            prepare_request=main.studio_music_prepare_generation_request,
        )
        runner.publish_node_result = bridge.publish_node_result
        song_profile = {
            "runnable": True, "operation": "music_song", "request_mapping": {"prompt": "prompt", "style_prompt": "style_prompt"},
            "parameters": {"style_prompt": {"type": "string"}, "enabled": {"type": "boolean"},
                            "seed": {"type": "integer"}},
            "inputs": {"prompt": {"media_type": "text", "role": "prompt", "min": 1}},
        }
        async def run_static_song():
            with patch.object(main.MODEL_CAPABILITY_REGISTRY, "find_model", return_value=song_profile):
                submitted = await bridge.submit(self.project["id"], {
                    "purpose": "song", "slot": "music", "output_node_id": "music-output",
                    "client_operation_id": "music-runner-song", "base_revision": initial["revision"],
                    "request": {"parameters": {"style_prompt": "温暖民谣", "enabled": False, "seed": 0}},
                }, {"accepted_revision": initial["revision"], "source_hash": initial["source_sha256"]})
            return await self._wait_runner(bridge, runner, self.project["id"], submitted["run_id"])

        song_result = asyncio.run(run_static_song())
        self.assertEqual(song_result["status"], "succeeded", song_result)
        self.assertNotIn("path", song_result["media"][0], "public music task projection must not expose local paths")
        safe_steps = bridge._public_steps([{
            "node_id": "music-source", "type": "smart-music-generator", "status": "succeeded",
            "path": "/private/cache/provider-response.wav", "payload": {"lyrics": "private"},
        }])
        self.assertEqual(safe_steps, [{
            "node_id": "music-source", "type": "smart-music-generator", "status": "succeeded",
        }])
        private = self.storage.get_canvas_task(song_result["run_id"])["private_snapshot"]
        request_snapshot = private["request"]
        self.assertEqual(request_snapshot["prompt"], "第一行歌词")
        self.assertEqual(request_snapshot["parameters"]["style_prompt"], "温暖民谣")
        self.assertIs(request_snapshot["parameters"]["enabled"], False)
        self.assertEqual(request_snapshot["parameters"]["seed"], 0)
        self.assertEqual(seen["executed"][0]["request"]["parameters"]["enabled"], False)
        self.assertEqual(seen["executed"][0]["request"]["parameters"]["seed"], 0)
        self.assertEqual(settings.canvas, settings_before, "普通生成输入只能改私有任务图")
        accepted_project_revision = store.get(self.project["id"])["revision"]
        asyncio.run(bridge.get(self.project["id"], song_result["run_id"]))
        self.assertEqual(store.get(self.project["id"])["revision"], accepted_project_revision,
                         "重复查询同一共享 runner 任务不得重复追加版本或递增项目 revision")

        # The BGM operation uses style_prompt as its actual prompt; song models use lyrics plus style.
        bgm_profile = {"runnable": True, "operation": "music", "request_mapping": {"prompt": "prompt"},
                       "parameters": {"enabled": {"type": "boolean"}, "seed": {"type": "integer"}},
                       "inputs": {"prompt": {"media_type": "text", "role": "prompt", "min": 1}}}
        with patch.object(main.MODEL_CAPABILITY_REGISTRY, "find_model", return_value=bgm_profile):
            bgm = asyncio.run(main.studio_music_prepare_generation_request(
                canvas=settings.canvas, purpose="song", slot="music", output_node_id="music-output",
                song=initial, source_snapshot={"title": "测试标题", "lyrics": "", "style_prompt": "氛围配乐",
                                               "notes": "", "cover_prompt": "", "reference_audio_refs": []},
                request={"parameters": {"enabled": False, "seed": 0}},
            ))
        self.assertEqual(bgm["prompt"], "氛围配乐")
        self.assertNotIn("style_prompt", bgm["parameters"], "BGM style is the prompt, not a second unconfirmed parameter")
        self.assertIs(bgm["parameters"]["enabled"], False)
        self.assertEqual(bgm["parameters"]["seed"], 0)
        with patch.object(main.MODEL_CAPABILITY_REGISTRY, "find_model", return_value=bgm_profile):
            with self.assertRaises(HTTPException) as unknown_bgm_parameter:
                asyncio.run(main.studio_music_prepare_generation_request(
                    canvas=settings.canvas, purpose="song", slot="music", output_node_id="music-output",
                    song=initial, source_snapshot={"title": "测试标题", "lyrics": "", "style_prompt": "氛围配乐",
                                                   "notes": "", "cover_prompt": "", "reference_audio_refs": []},
                    request={"parameters": {"unconfirmed": "value"}},
                ))
        self.assertEqual(unknown_bgm_parameter.exception.status_code, 400)

        # Dynamic workflows require explicit role-to-node/targetFieldKey mappings; verify the
        # mapper output then run it through the same private graph executor.
        dynamic_settings = SettingsService()
        dynamic_settings.canvas = _music_canvas("smart-ai-app", revision=5)
        dynamic_settings.canvas["nodes"][0]["runSettings"] = {"rhMode": "app", "rhConfigKey": "app:fixture"}
        dynamic_settings.canvas["nodes"].insert(0, {
            "id": "legacy-text-source", "type": "smart-material", "title": "配置默认字段",
            "images": [
                {"kind": "text", "text": "旧歌词连接", "content": "旧歌词连接"},
                {"kind": "text", "text": "旧风格连接", "content": "旧风格连接"},
                {"kind": "text", "text": "保留标题", "content": "保留标题"},
            ],
        })
        dynamic_settings.canvas["nodes"][1]["manualInputRefs"] = [
            {"kind": "text", "targetFieldKey": "lyrics_exact", "text": "旧歌词映射", "content": "旧歌词映射"},
            {"kind": "text", "targetFieldKey": "style_exact", "text": "旧风格映射", "content": "旧风格映射"},
            {"kind": "text", "targetFieldKey": "title_exact", "text": "保留标题", "content": "保留标题"},
        ]
        dynamic_settings.canvas["connections"] = [
            {"from": "legacy-text-source", "to": "music-source", "kind": "input", "targetFieldKey": "lyrics_exact"},
            {"from": "legacy-text-source", "to": "music-source", "kind": "input", "targetFieldKey": "style_exact"},
            {"from": "legacy-text-source", "to": "music-source", "kind": "input", "targetFieldKey": "title_exact"},
            {"from": "music-source", "to": "music-output", "kind": "input"},
        ]
        dynamic_before = copy.deepcopy(dynamic_settings.canvas)
        dynamic_runner = HypitFlowRunner(
            load_canvas=lambda canvas_id: copy.deepcopy(dynamic_settings.canvas), storage=self.storage,
            prepare_node_request=prepare_node_request, preflight_node=preflight_node,
            execute_node=execute_node, collect_results=collect_results, notify=lambda *_: None,
            lock=threading.RLock(), now_ms=lambda: 1000, canvas_id="music-settings", module_id="music",
        )
        dynamic_bridge = StudioMusicGenerationBridge(
            music_store=store, runner=dynamic_runner, storage=self.storage, settings_service=dynamic_settings,
            prepare_request=main.studio_music_prepare_generation_request,
        )
        dynamic_runner.publish_node_result = dynamic_bridge.publish_node_result
        source_now = store.get(self.project["id"])
        dynamic_schema = [
            {"key": "lyrics_exact", "fieldType": "string", "enabled": True},
            {"key": "style_exact", "fieldType": "string", "enabled": True},
            {"key": "title_exact", "fieldType": "textarea", "enabled": True},
            {"key": "enabled", "fieldType": "boolean", "enabled": True},
            {"key": "seed", "fieldType": "integer", "enabled": True},
        ]
        async def run_dynamic_song():
            submitted = await dynamic_bridge.submit(self.project["id"], {
                "purpose": "song", "slot": "music", "output_node_id": "music-output",
                "client_operation_id": "music-runner-dynamic", "base_revision": source_now["revision"],
                "request": {"input_fields": {
                    "lyrics": {"node_id": "music-source", "targetFieldKey": "lyrics_exact"},
                    "style_prompt": {"node_id": "music-source", "targetFieldKey": "style_exact"},
                }, "parameters": {"enabled": False, "seed": 0}},
            }, {"accepted_revision": source_now["revision"], "source_hash": source_now["source_sha256"]})
            return await self._wait_runner(dynamic_bridge, dynamic_runner, self.project["id"], submitted["run_id"])
        with patch.object(main, "studio_app_fields", return_value=dynamic_schema):
            dynamic_result = asyncio.run(run_dynamic_song())
        self.assertEqual(dynamic_result["status"], "succeeded", dynamic_result)
        dynamic_inputs = next((entry[1] for entry in seen["prepared"] if entry[0] is False and
                               any(item.get("targetFieldKey") == "lyrics_exact" for item in entry[1])), None)
        self.assertIsNotNone(dynamic_inputs)
        self.assertEqual({item["targetFieldKey"] for item in dynamic_inputs}, {"lyrics_exact", "style_exact", "title_exact"})
        self.assertEqual(len(dynamic_inputs), 3, "update exact field mappings in the private copy instead of appending duplicates")
        by_field = {item["targetFieldKey"]: item for item in dynamic_inputs}
        self.assertEqual(by_field["lyrics_exact"]["text"], "第一行歌词")
        self.assertEqual(by_field["style_exact"]["text"], "温暖民谣")
        self.assertEqual(by_field["title_exact"]["text"], "保留标题")
        dynamic_request = next(entry[3] for entry in seen["prepared"] if entry[0] is False and
                               "field_inputs" in entry[3])
        self.assertIs(dynamic_request["parameters"]["enabled"], False)
        self.assertEqual(dynamic_request["parameters"]["seed"], 0)
        self.assertIs(seen["executed"][-1]["request"]["parameters"]["enabled"], False)
        self.assertEqual(seen["executed"][-1]["request"]["parameters"]["seed"], 0)
        dynamic_connections = next(entry[4] for entry in seen["prepared"] if entry[0] is False and
                                   any(item.get("targetFieldKey") == "lyrics_exact" for item in entry[1]))
        replaced_connection_fields = {edge.get("targetFieldKey") for edge in dynamic_connections
                                      if edge.get("to") == "music-source"}
        self.assertEqual(replaced_connection_fields, {"title_exact"},
                         "remove only connections shadowed by explicit per-run fields")
        self.assertEqual(dynamic_settings.canvas, dynamic_before, "动态字段也必须留在私有任务快照")
        dynamic_revision = store.get(self.project["id"])["revision"]
        asyncio.run(dynamic_bridge.get(self.project["id"], dynamic_result["run_id"]))
        self.assertEqual(store.get(self.project["id"])["revision"], dynamic_revision)

    async def _wait_runner(self, bridge, runner, project_id: str, run_id: str):
        for _ in range(200):
            flow = runner.get(run_id)
            if flow and flow["status"] in {"succeeded", "failed", "cancelled"}:
                return await bridge.get(project_id, run_id)
            await asyncio.sleep(0)
        self.fail("共享配置图 runner 未在测试时间内完成")


if __name__ == "__main__":
    unittest.main()
