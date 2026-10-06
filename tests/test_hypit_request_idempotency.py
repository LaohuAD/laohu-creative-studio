"""P6 请求幂等与固定槽位的回归。

对应《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§10.7、§11.6、§16 P6、§17 D 系列。

验证机制层（纯函数与调用顺序），不启动服务、不读用户配置、不产生任务。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import studio_hypit_models as shm  # noqa: E402


class RequestFingerprintTests(unittest.TestCase):
    """D09/D10：幂等只按调用方输入判定，模块默认变化不得改变指纹。"""

    def fingerprint(self, payload):
        return shm._request_fingerprint(payload)

    def test_request_id_is_excluded_from_the_fingerprint(self):
        first = self.fingerprint({"request_id": "r1", "kind": "image", "prompt": "a"})
        second = self.fingerprint({"request_id": "r2", "kind": "image", "prompt": "a"})
        self.assertEqual(first, second, "request_id 本身不是业务输入")

    def test_same_business_input_is_stable(self):
        payload = {"request_id": "r1", "kind": "video", "prompt": "日落", "constraints": {"duration": 5}}
        self.assertEqual(self.fingerprint(payload), self.fingerprint(dict(payload)))

    def test_different_explicit_input_changes_the_fingerprint(self):
        base = {"request_id": "r1", "kind": "video", "prompt": "日落"}
        changed = {"request_id": "r1", "kind": "video", "prompt": "日出"}
        self.assertNotEqual(self.fingerprint(base), self.fingerprint(changed),
                            "D10：显式输入不同必须得到不同指纹，才能触发 409")

    def test_module_defaults_are_not_part_of_the_input(self):
        """D09：模块默认模型变化后，同一原始请求必须仍命中原任务。"""
        payload = {"request_id": "r1", "kind": "image", "prompt": "a"}
        # 指纹函数只吃调用方 payload；这里断言它没有读取任何模块设置来源
        source = (ROOT / "studio_hypit_models.py").read_text(encoding="utf-8")
        start = source.index("def _request_fingerprint(")
        body = source[start:start + 400]
        self.assertIn("不把模块默认模型算进输入", body)
        for forbidden in ("settings_record", "read_binding", "defaults"):
            self.assertNotIn(forbidden, body, f"指纹不得引用模块设置来源：{forbidden}")
        self.assertEqual(self.fingerprint(payload), self.fingerprint(dict(payload)))

    def test_fingerprint_ignores_key_order(self):
        first = self.fingerprint({"request_id": "r", "kind": "image", "prompt": "a", "n": 2})
        second = self.fingerprint({"n": 2, "prompt": "a", "kind": "image", "request_id": "r"})
        self.assertEqual(first, second, "字典顺序不得影响幂等判定")


class SubmitOrderingTests(unittest.TestCase):
    """§11.6：先查已接收任务，再解析当前模块默认，避免默认变化导致重复付费。"""

    SOURCE = (ROOT / "studio_hypit_models.py").read_text(encoding="utf-8")

    def _submit_body(self) -> str:
        start = self.SOURCE.index("    async def submit_request(")
        end = self.SOURCE.index("\n    @router.", start)
        return self.SOURCE[start:end]

    def test_fingerprint_is_computed_before_resolving_the_binding(self):
        body = self._submit_body()
        fingerprint_at = body.index("input_fingerprint = _request_fingerprint(payload)")
        binding_at = body.index("binding = read_binding(project_id)")
        self.assertLess(fingerprint_at, binding_at,
                        "指纹必须在读取模块绑定之前算好，否则默认变化会改变幂等判定")

    def test_existing_task_is_returned_before_projection(self):
        body = self._submit_body()
        first_lookup = body.index("existing = read_task(project_id, request_id)")
        projections = (
            ("工作流", body.index("projected = _project_workflow_constraints(")),
            ("API 模型", body.index("projected = _project_constraints(")),
        )
        for source, projection in projections:
            with self.subTest(source=source):
                self.assertLess(first_lookup, projection,
                                f"已有任务必须在{source}请求投影之前返回，不能让默认变化重新解释旧请求")

    def test_conflicting_input_returns_409(self):
        body = self._submit_body()
        self.assertIn("相同 request_id 不能用于不同输入", body)
        self.assertIn("409", body)

    def test_repeat_lookup_after_binding_read_guards_the_race(self):
        body = self._submit_body()
        # 读取绑定与投影后、写任务前再次查重，防止并发请求都创建任务。
        lookup = "existing = read_task(project_id, request_id)"
        lookup_at = [index for index in range(len(body)) if body.startswith(lookup, index)]
        self.assertGreaterEqual(len(lookup_at), 2,
                                "绑定读取后必须再查一次，避免并发下重复创建任务")
        binding_at = body.index("binding = read_binding(project_id)")
        projection_at = max(
            body.index("projected = _project_workflow_constraints("),
            body.index("projected = _project_constraints("),
        )
        write_at = body.index("write_task(record, project_id, request_id)")
        self.assertLess(lookup_at[0], binding_at,
                        "首次查重必须在读取可变模块绑定前完成")
        self.assertLess(binding_at, lookup_at[1],
                        "投影前读取绑定后必须二次查重")
        self.assertLess(projection_at, lookup_at[1],
                        "API/工作流投影完成后、写入前必须二次查重")
        self.assertLess(lookup_at[1], write_at,
                        "二次查重必须先于任务持久化")


class FixedSlotBoundaryTests(unittest.TestCase):
    """§10.7 / D11：固定槽位不得被请求绕过。"""

    SOURCE = (ROOT / "studio_hypit_models.py").read_text(encoding="utf-8")

    def _projection_body(self) -> str:
        """按函数边界取完整函数体，避免用字符窗口截断。"""
        start = self.SOURCE.index("def _project_constraints(")
        end = self.SOURCE.index("\ndef ", start + 1)
        return self.SOURCE[start:end]

    def test_override_is_recorded_instead_of_being_a_hidden_path(self):
        """§10.7 收敛：显式覆盖保留受限兼容，但必须可观测。"""
        body = self._projection_body()
        self.assertIn('explicit_override = bool(', body)
        self.assertIn('model_source = "runtime_override" if (explicit_override and not matches_module_binding) else "module_settings"', body)
        self.assertIn('"model_source": model_source', body)
        self.assertIn('"module_slot": slot', body)

    def test_override_still_passes_capability_validation(self):
        """受限兼容：覆盖仍要落到该槽位允许且档案就绪的模型，不能绕过校验。"""
        body = self._projection_body()
        self.assertIn("_resolve_profile(", body)
        self.assertIn("profile.get(\"validation_mode\") not in (None, \"strict\")", body)
        self.assertIn("适配器尚未完成", body)

    def test_module_settings_are_the_documented_default_source(self):
        start = self.SOURCE.index("def _project_constraints(")
        body = self.SOURCE[start:start + 2000]
        self.assertIn("selected.get(\"provider\")", body, "未显式指定时应回落到模块槽位绑定")
        self.assertIn("selected.get(\"model\")", body)

    def test_missing_slot_configuration_is_rejected(self):
        start = self.SOURCE.index("def _project_constraints(")
        body = self.SOURCE[start:start + 2200]
        self.assertIn("请先为", body, "槽位未配置时必须明确拒绝，而不是猜一个模型")

    def test_unsupported_capability_is_rejected(self):
        with self.assertRaises(shm.HTTPException) as rejected:
            shm._project_constraints({'kind': 'fixture-unknown-kind', 'prompt': 'fixture'}, {}, {})
        self.assertEqual(rejected.exception.status_code, 400)
        self.assertIn("Hypit 只支持已声明", rejected.exception.detail,
                      "D05：未声明能力必须拒绝，不因公共控件能列出就开放")


class SlotVocabularyTests(unittest.TestCase):
    """§10.4：audio 与 voice 是不同槽位，不得按 kind 取第一个默认。"""

    def test_slot_to_kind_mapping_keeps_voice_separate(self):
        self.assertEqual(shm._SLOT_KINDS["voice"], "audio")
        self.assertEqual(shm._SLOT_KINDS["audio"], "audio")
        self.assertNotEqual("voice", "audio")
        self.assertIn("voice", shm._SLOTS)
        self.assertIn("audio", shm._SLOTS)

    def test_voice_and_audio_use_the_same_node_type_but_distinct_slots(self):
        self.assertEqual(shm._SLOT_NODE_TYPES["voice"], "audio_generation")
        self.assertEqual(shm._SLOT_NODE_TYPES["audio"], "audio_generation")
        # 槽位才是权威：同一 node_type 下两个槽位不得互相顶替
        self.assertEqual(len({"voice", "audio"} & set(shm._SLOTS)), 2)

    def test_speech_kind_normalises_to_audio_not_music(self):
        source = (ROOT / "studio_hypit_models.py").read_text(encoding="utf-8")
        start = source.index("def _project_constraints(")
        body = source[start:start + 900]
        self.assertIn('if kind == "speech":', body)
        self.assertIn('kind = "audio"', body)
        self.assertNotIn('kind = "music"', body, "语音不得被归成音乐")


class ModuleBindingEndToEndTests(unittest.TestCase):
    """D07/D08：端到端验证新请求用最新绑定、旧任务不被重新投影。

    使用假执行器（本模块自带 fixture 目录），不联网、不产生付费任务。
    """

    def setUp(self):
        import asyncio
        import copy
        import time

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        self.asyncio = asyncio
        self.copy = copy
        self.time = time
        self.TestClient = TestClient
        self.root = ROOT / "cache" / "p6-e2e" / f"case-{time.time_ns()}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.projects = {"project-a": {"id": "project-a"}}
        self.calls = []

        catalog = {
            "schema_version": 1,
            "providers": [{
                "id": "provider-a", "name": "Provider A", "protocol": "openai",
                "models": [
                    {"model_id": "image-1", "node_type": "image_generation", "family_id": "image-family",
                     "operation": "text_to_image", "output_type": "image",
                     "runnable": True, "readiness": "ready", "validation_mode": "strict",
                     "parameters": {"count": {"type": "integer", "min": 1, "max": 2}},
                     "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}}},
                    {"model_id": "image-2", "node_type": "image_generation", "family_id": "image-family",
                     "operation": "text_to_image", "output_type": "image",
                     "runnable": True, "readiness": "ready", "validation_mode": "strict",
                     "parameters": {"count": {"type": "integer", "min": 1, "max": 2}},
                     "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}}},
                ],
            }],
        }

        def get_project(project_id, module):
            return copy.deepcopy(self.projects[project_id])

        def get_capabilities():
            return copy.deepcopy(catalog)

        async def validate(request):
            self.calls.append(("validate", copy.deepcopy(request)))
            return {"validation": "ok"}

        async def generate(request):
            self.calls.append(("generate", copy.deepcopy(request)))
            await asyncio.sleep(0)
            return {"images": [{"url": "/api/results/result-a.png"}]}

        self.app = FastAPI()
        self.app.include_router(shm.create_hypit_models_router(
            self.root, get_project, get_capabilities, validate, generate))

    def tearDown(self):
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)

    def _save_image_slot(self, client, model, expected_revision):
        response = client.put("/api/studio/hypit/models/settings", json={
            "expected_revision": expected_revision,
            "defaults": {"image": {"provider": "provider-a", "model": model, "parameters": {"count": 1}}},
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["revision"]

    def _submit(self, client, request_id, prompt):
        return client.post("/api/studio/hypit/models/projects/project-a/requests", json={
            "request_id": request_id,
            "capability": {"module": {"name": "@laohu/studio-models", "version": "1"}, "name": "image-generation"},
            "constraints": {"kind": "image", "prompt": prompt},
        })

    def _wait(self, client, request_id, expected="succeeded"):
        import time as _time

        for _ in range(100):
            value = client.get(
                f"/api/studio/hypit/models/projects/project-a/requests/{request_id}").json()
            if value["status"] == expected:
                return value
            _time.sleep(0.01)
        self.fail(f"任务未到达 {expected}: {value}")

    def test_d07_new_request_uses_the_latest_module_binding(self):
        with self.TestClient(self.app) as client:
            revision = self._save_image_slot(client, "image-1", 1)
            first = self._submit(client, "req-1", "a red fox")
            self.assertEqual(first.status_code, 200, first.text)
            self._wait(client, "req-1")
            self.assertEqual(self.calls[-1][1]["model"], "image-1", "新请求必须使用当前模块绑定")

            self._save_image_slot(client, "image-2", revision)
            second = self._submit(client, "req-2", "a blue fox")
            self.assertEqual(second.status_code, 200, second.text)
            self._wait(client, "req-2")
            self.assertEqual(self.calls[-1][1]["model"], "image-2",
                             "改模块设置后，下一次新请求必须使用新配置")

    def test_d08_existing_task_is_not_reprojected_after_settings_change(self):
        with self.TestClient(self.app) as client:
            revision = self._save_image_slot(client, "image-1", 1)
            first = self._submit(client, "req-1", "a red fox")
            self._wait(client, "req-1")
            generates_after_first = sum(1 for kind, _ in self.calls if kind == "generate")
            self.assertEqual(generates_after_first, 1)

            self._save_image_slot(client, "image-2", revision)
            again = self._submit(client, "req-1", "a red fox")
            self.assertEqual(again.status_code, 200, again.text)
            self.assertEqual(again.json()["task_id"], first.json()["task_id"],
                             "同一 request_id 必须返回原任务")
            generates_after_retry = sum(1 for kind, _ in self.calls if kind == "generate")
            self.assertEqual(generates_after_retry, 1,
                             "模块默认变化后重试不得重新执行，避免重复付费（D09）")
            self.assertEqual(again.json()["request"]["model"], "image-1",
                             "原任务必须保持提交时的冻结模型（D08）")

    def test_d10_same_request_id_with_different_input_conflicts(self):
        with self.TestClient(self.app) as client:
            self._save_image_slot(client, "image-1", 1)
            self._submit(client, "req-1", "a red fox")
            self._wait(client, "req-1")
            conflict = self._submit(client, "req-1", "完全不同的输入")
            self.assertEqual(conflict.status_code, 409, conflict.text)
            self.assertGreaterEqual(sum(1 for kind, _ in self.calls if kind == "generate"), 1)
            self.assertEqual(sum(1 for kind, _ in self.calls if kind == "generate"), 1,
                             "冲突请求不得创建第二次执行")

    def test_d11_module_binding_is_the_reported_source_without_override(self):
        with self.TestClient(self.app) as client:
            self._save_image_slot(client, "image-1", 1)
            self._submit(client, "req-plain", "a red fox")
            task = self._wait(client, "req-plain")
            self.assertEqual(task["request"]["model_source"], "module_settings")
            self.assertEqual(task["request"]["module_slot"], "image")

    def test_d11_explicit_override_is_visible_and_stays_contract_validated(self):
        with self.TestClient(self.app) as client:
            self._save_image_slot(client, "image-1", 1)
            response = client.post(
                "/api/studio/hypit/models/projects/project-a/requests",
                json={
                    "request_id": "req-override",
                    "capability": {"module": {"name": "@laohu/studio-models", "version": "1"},
                                   "name": "image-generation"},
                    "constraints": {"kind": "image", "prompt": "a red fox",
                                    "provider_id": "provider-a", "model": "image-2"},
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            task = self._wait(client, "req-override")
            self.assertEqual(task["request"]["model"], "image-2")
            self.assertEqual(task["request"]["model_source"], "runtime_override",
                             "绕过模块设置的调用必须被显式标记，不再是隐藏路径")

    def test_d11_override_to_a_model_outside_the_slot_is_rejected(self):
        with self.TestClient(self.app) as client:
            self._save_image_slot(client, "image-1", 1)
            response = client.post(
                "/api/studio/hypit/models/projects/project-a/requests",
                json={
                    "request_id": "req-bad-override",
                    "capability": {"module": {"name": "@laohu/studio-models", "version": "1"},
                                   "name": "image-generation"},
                    "constraints": {"kind": "image", "prompt": "a red fox",
                                    "provider_id": "provider-a", "model": "never-exists"},
                },
            )
            self.assertEqual(response.status_code, 400, response.text)
            self.assertIn("白名单", response.text)
            self.assertEqual([k for k, _ in self.calls if k == "generate"], [],
                             "非法覆盖不得触发执行")

    def test_unconfigured_slot_is_rejected_before_any_execution(self):
        with self.TestClient(self.app) as client:
            response = self._submit(client, "req-x", "a red fox")
            self.assertEqual(response.status_code, 400, response.text)
            self.assertIn("请先为", response.text)
            self.assertEqual([k for k, _ in self.calls if k == "generate"], [],
                             "槽位未配置时不得执行")


if __name__ == "__main__":
    unittest.main()
