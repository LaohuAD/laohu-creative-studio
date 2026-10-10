"""音乐幂等操作在并发不同目标下也只能接受一次。"""
from __future__ import annotations

import asyncio
import copy
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from project_storage import ProjectStorage
from studio_music import MusicPutRequest, StudioMusicStore
from studio_music_generation import StudioMusicGenerationBridge
from studio_projects import StudioProjectStore
from tests.test_studio_projects import FakeCanvasAdapter, TEST_TMP_ROOT


class _Settings:
    def ensure_canvas(self):
        return {"id": "music-settings", "revision": 2, "nodes": [], "connections": []}


class _Runner:
    canvas_id = "music-settings"

    def __init__(self, storage):
        self.storage = storage
        self.flows = {}
        self.accepted = 0

    async def submit(self, slot, output_node_id, request_id, payload, test=False, *, trusted_context=None):
        del test
        run = self.storage.prepare_run(
            canvas_id=self.canvas_id,
            node_id=output_node_id,
            client_operation_id=request_id,
            standard_request={"slot": slot, **copy.deepcopy(payload)},
            platform_request={},
            capability_snapshot={"trusted_context": copy.deepcopy(dict(trusted_context or {}))},
        )
        run_id = str(run["run_id"])
        if run_id not in self.flows:
            self.accepted += 1
            self.flows[run_id] = {
                "run_id": run_id, "canvas_id": self.canvas_id, "status": "queued",
                "output_node_id": output_node_id, "trusted_context": copy.deepcopy(dict(trusted_context or {})),
            }
            self.storage.create_canvas_task({"id": run_id, "canvas_id": self.canvas_id, "status": "queued"})
        return {"run_id": run_id, "status": "queued", "output_node_id": output_node_id}

    def get(self, run_id):
        value = self.flows.get(run_id)
        return copy.deepcopy(value) if value else None


class StudioMusicConcurrentOperationTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT)
        self.root = Path(self.temporary.name)
        self.projects = StudioProjectStore(self.root, FakeCanvasAdapter())
        self.project = self.projects.create("music", "并发音乐")
        self.music = StudioMusicStore(self.projects)
        self.music.put(self.project["id"], MusicPutRequest.model_validate({
            "expected_revision": 1, "title": "并发歌词", "lyrics": "同一份已保存歌词。",
        }))
        self.storage = ProjectStorage(self.root / "managed")
        self.storage.ensure_layout()

    def tearDown(self):
        self.temporary.cleanup()

    def test_same_operation_with_different_outputs_is_serialized_and_rejected(self):
        runner = _Runner(self.storage)

        async def prepare_request(**_kwargs):
            # 让两个 HTTP 请求都能穿插到同一 operation lock 的等待边界。
            await asyncio.sleep(0.01)
            return {"prompt": "同一来源快照"}

        bridge = StudioMusicGenerationBridge(
            music_store=self.music,
            runner=runner,
            storage=self.storage,
            settings_service=_Settings(),
            prepare_request=prepare_request,
        )
        current = self.music.get(self.project["id"])
        accepted = {"accepted_revision": current["revision"], "source_hash": current["source_sha256"]}
        common = {
            "purpose": "song", "slot": "music", "client_operation_id": "shared-operation",
            "base_revision": current["revision"], "request": {},
        }

        async def run_pair():
            return await asyncio.gather(
                bridge.submit(self.project["id"], {**common, "output_node_id": "output-a"}, accepted),
                bridge.submit(self.project["id"], {**common, "output_node_id": "output-b"}, accepted),
                return_exceptions=True,
            )

        values = asyncio.run(run_pair())
        successes = [value for value in values if isinstance(value, dict)]
        conflicts = [value for value in values if isinstance(value, HTTPException)]
        self.assertEqual(len(successes), 1, values)
        self.assertEqual(len(conflicts), 1, values)
        self.assertEqual(conflicts[0].status_code, 409)
        self.assertEqual(runner.accepted, 1)
        self.assertEqual(len(self.storage.list_runs(canvas_id="music-settings")), 1)


if __name__ == "__main__":
    unittest.main()
