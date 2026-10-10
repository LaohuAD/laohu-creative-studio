"""P6 模块与槽位契约的行为回归。

对应《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§10.2、§10.4、§10.5、§16 P6、§17 D 系列。

只读仓库能力声明与假选项，不写模块设置、不写项目 binding、不发请求。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import studio_module_models as smm  # noqa: E402
from studio_hypit_models import SUPPORTED_HYPIT_CAPABILITIES, UNSUPPORTED_HYPIT_CAPABILITIES  # noqa: E402


def option(**overrides) -> dict:
    base = {
        "option_id": "opt_0000000000000001",
        "node_type": "image_generation",
        "operation": "text_to_image",
        "catalog_model_id": "fixture-image",
        "connection_id": "fixture-conn",
        "region_id": "global",
        "output_contract": "image,min=1,max=1",
        "readiness": "ready",
        "runnable": True,
        "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
    }
    base.update(overrides)
    return base


class SlotContractTests(unittest.TestCase):
    """§10.5 槽位模板必须来自真实桥接能力，不另写一份清单。"""

    def test_hypit_slots_derive_from_the_bridge_declaration(self):
        descriptors = smm.hypit_slot_descriptors()
        from_bridge = {str(item["slot"]) for item in SUPPORTED_HYPIT_CAPABILITIES}
        self.assertEqual({slot["id"] for slot in descriptors}, from_bridge,
                         "槽位清单必须与 Hypit 桥接声明一致，不能两处各写一份")

    def test_every_slot_carries_the_contract_fields(self):
        required = ("id", "selection_policy", "node_type", "expected_output",
                    "allowed_operations", "required_input_scenarios", "supported_input_roles",
                    "runtime_model_override", "runtime_parameter_overrides")
        for slot in smm.hypit_slot_descriptors():
            for key in required:
                self.assertIn(key, slot, f"槽位 {slot.get('id')} 缺少契约字段 {key}")
            self.assertEqual(slot["selection_policy"], "fixed")
            self.assertEqual(slot["runtime_model_override"], "deny",
                             "固定槽位默认禁止调用者随请求更换模型（§10.7）")

    def test_audio_and_voice_are_distinct_slots(self):
        audio = smm.slot_descriptor("hypit", "audio")
        voice = smm.slot_descriptor("hypit", "voice")
        self.assertIsNotNone(audio)
        self.assertIsNotNone(voice)
        self.assertNotEqual(audio["capability_name"], voice["capability_name"],
                            "D04：音效槽与语音槽即使输出都是 audio 也必须按能力标识区分")
        self.assertEqual(audio["capability_name"], "audio-generation")
        self.assertEqual(voice["capability_name"], "speech-generation")
        self.assertNotEqual(audio["required_input_scenarios"], voice["required_input_scenarios"])

    def test_unknown_slot_is_not_invented(self):
        self.assertIsNone(smm.slot_descriptor("hypit", "fixture-unknown-slot"))
        self.assertIsNone(smm.slot_descriptor("hypit", "cover_image"))

    def test_music_slot_uses_music_models_and_audio_output(self):
        slot = smm.slot_descriptor('hypit', 'music')
        self.assertEqual(slot['node_type'], 'music_generation')
        self.assertEqual(slot['expected_output']['media_type'], 'audio')
        result = smm.validate_slot_binding('hypit', 'music', option(node_type='music_generation', operation='music', output_contract='audio,min=1,max=1'))
        self.assertTrue(result['valid'], result['reasons'])

    def test_article_declares_six_real_canvas_output_slots_without_hypit_filtering(self):
        module = smm.module_descriptor("article")
        self.assertIsNotNone(module, "文章设置图必须是已注册宿主，不能冒充 canvas 或 hypit")
        self.assertEqual(module["module_id"], "article")
        slots = {item["id"]: item for item in module["slots"]}
        self.assertEqual(set(slots), {"text", "image", "video", "audio", "music", "voice"})
        expected = {
            "text": ("text_generation", "text"),
            "image": ("image_generation", "image"),
            "video": ("video_generation", "video"),
            "audio": ("audio_generation", "audio"),
            "music": ("music_generation", "audio"),
            "voice": ("audio_generation", "audio"),
        }
        for slot_id, (node_type, media_type) in expected.items():
            descriptor = slots[slot_id]
            self.assertEqual(descriptor["node_type"], node_type)
            self.assertEqual(descriptor["expected_output"]["media_type"], media_type)
            self.assertEqual(descriptor["selection_policy"], "fixed")

    def test_article_uses_enabled_exact_node_contract_but_not_hypit_operation_exclusions(self):
        # 同为 text-to-image 的 image-edit/upscale profile 按真实输出模型节点契约保留；
        # Hypit 专属用途过滤只能施加于 hypit 宿主。
        image_slot = smm.slot_descriptor("article", "image")
        self.assertIsNotNone(image_slot)
        profile = option(operation="image_upscale")
        profile["node_type"] = "image_generation"
        result = smm.validate_slot_binding("article", "image", profile)
        self.assertTrue(result["valid"], result["reasons"])
        disabled = smm.validate_slot_binding("article", "image", option(runnable=False))
        self.assertFalse(disabled["valid"])
        self.assertIn("ADAPTER_MISSING", [item["code"] for item in disabled["reasons"]])


class HypitGenerationEligibilityTests(unittest.TestCase):
    def test_tools_and_incomplete_inputs_are_not_generation_candidates(self):
        from studio_module_models import hypit_profile_reasons
        base = dict(node_type='image_generation', operation='text_to_image', runnable=True,
                    readiness='ready', validation_mode='strict', output={'media_type': 'image'},
                    inputs={'prompt': {'media_type': 'text', 'min': 1, 'max': 1}})
        self.assertEqual(hypit_profile_reasons('image', base), [])
        for changes in ({'operation': 'image_upscale'}, {'inputs': {}},
                        {'model_id': 'hypir-balance', 'operation': 'image_to_image'},
                        {'output': {'media_type': 'file'}},
                        {'inputs': {**base['inputs'], 'mask': {'media_type': 'image', 'min': 1}}}):
            self.assertTrue(hypit_profile_reasons('image', {**base, **changes}), changes)
        video = {**base, 'node_type': 'video_generation', 'operation': 'image_to_video',
                 'output': {'media_type': 'video'}, 'inputs': {**base['inputs'],
                 'reference': {'media_type': 'image', 'min': 1, 'max': 4}}}
        self.assertEqual(hypit_profile_reasons('video', video), [])
        self.assertTrue(hypit_profile_reasons('video', {**video, 'operation': 'video_upscale'}))

    def test_unadapted_world_and_empty_contract_do_not_enter_generation_picker(self):
        from model_capabilities import generation_visibility_issue
        self.assertTrue(generation_visibility_issue({'model_id': 'marble-1.1/image-to-world'}))
        self.assertTrue(generation_visibility_issue({'model_id': 'fixture', 'inputs': {}}))
        self.assertFalse(generation_visibility_issue({
            'model_id': 'fixture', 'node_type': 'image_generation',
            'inputs': {'prompt': {'media_type': 'text'}}, 'output': {'media_type': 'image'}}))


class SelectionPolicyTests(unittest.TestCase):
    """§10.2 画布候选池多选、固定槽位单选。"""

    def test_canvas_pool_is_multi_select_and_hypit_is_fixed(self):
        modules = smm.module_descriptors()
        self.assertEqual(modules["canvas"]["selection_policy"], "multiple")
        self.assertEqual(modules["hypit"]["selection_policy"], "fixed")
        self.assertEqual(smm.selection_policy("canvas"), "multiple")
        self.assertEqual(smm.selection_policy("hypit"), "fixed")

    def test_d14_canvas_pool_and_node_slot_are_different_objects(self):
        canvas = smm.module_descriptor("canvas")
        node_slots = {slot["id"] for slot in canvas["slots"]}
        self.assertEqual(node_slots, {"text_generation", "image_generation", "video_generation",
                                      "audio_generation", "music_generation"})
        for slot in canvas["slots"]:
            self.assertEqual(slot["selection_policy"], "fixed",
                             "D14：真实节点是单选，与候选池的多选不是同一对象")

    def test_unknown_module_has_no_policy(self):
        self.assertEqual(smm.selection_policy("not-a-module"), "")
        self.assertIsNone(smm.module_descriptor("not-a-module"))


class UnsupportedCapabilityTests(unittest.TestCase):
    """D05：模块不支持的桥接能力必须明确拒绝。"""

    def test_ai_app_is_unsupported_but_music_is_supported(self):
        names = {str(item.get("name")) for item in UNSUPPORTED_HYPIT_CAPABILITIES}
        self.assertIn("ai-application", names)
        self.assertNotIn("music-generation", names)
        for name in names:
            reason = smm.unsupported_capability_reason("hypit", name)
            self.assertIsNotNone(reason, f"{name} 必须能在模块声明里查到拒绝原因")
            self.assertTrue(reason["reason"].get("zh"), "拒绝原因必须有中文说明")

    def test_supported_capability_is_not_reported_unsupported(self):
        for capability in SUPPORTED_HYPIT_CAPABILITIES:
            self.assertIsNone(smm.unsupported_capability_reason("hypit", capability["slot"]))


class SlotBindingValidationTests(unittest.TestCase):
    """§10.5、D06：绑定必须落到该槽位真实允许的输出与操作。"""

    def test_image_slot_accepts_an_image_option(self):
        result = smm.validate_slot_binding("hypit", "image", option())
        self.assertTrue(result["valid"], result["reasons"])

    def test_d06_image_slot_rejects_a_video_tool(self):
        result = smm.validate_slot_binding("hypit", "image", option(
            node_type="video_generation", output_contract="video,min=1,max=1"))
        codes = [item["code"] for item in result["reasons"]]
        self.assertFalse(result["valid"])
        self.assertIn("HOST_OUTPUT_UNSUPPORTED", codes, "固定图片槽不得绑定输出视频的工具")

    def test_voice_slot_rejects_a_music_node_type(self):
        result = smm.validate_slot_binding("hypit", "voice", option(
            node_type="music_generation", output_contract="audio,min=1,max=1"))
        self.assertFalse(result["valid"])
        self.assertIn("HOST_OUTPUT_UNSUPPORTED", [item["code"] for item in result["reasons"]])

    def test_adapter_gap_cannot_be_bound(self):
        result = smm.validate_slot_binding("hypit", "video", option(
            node_type="video_generation", output_contract="video,min=1,max=1",
            readiness="adapter_missing", runnable=False))
        codes = [item["code"] for item in result["reasons"]]
        self.assertIn("ADAPTER_MISSING", codes)
        self.assertIn("PROFILE_UNCONFIRMED", codes)

    def test_unconfirmed_profile_cannot_be_bound(self):
        result = smm.validate_slot_binding("hypit", "text", option(
            node_type="text_generation", output_contract="text,min=1,max=1", readiness="needs_profile"))
        self.assertIn("PROFILE_UNCONFIRMED", [item["code"] for item in result["reasons"]])

    def test_operation_allowlist_is_enforced_when_declared(self):
        slot = dict(smm.slot_descriptor("hypit", "image"))
        slot["allowed_operations"] = ["text_to_image"]
        blocked = smm.validate_option_against_slot(slot, option(operation="image_edit"))
        self.assertIn("OPERATION_NOT_ALLOWED", [item["code"] for item in blocked])
        allowed = smm.validate_option_against_slot(slot, option(operation="text_to_image"))
        self.assertEqual(allowed, [], "声明内的操作必须通过")

    def test_descriptors_are_rebuilt_so_callers_cannot_pollute_them(self):
        first = smm.slot_descriptor("hypit", "image")
        original = first['allowed_operations'][:]
        first["allowed_operations"] = ["tampered"]
        self.assertEqual(smm.slot_descriptor("hypit", "image")["allowed_operations"], original,
                         "槽位声明每次重建，调用方的修改不得影响后续校验")

    def test_undeclared_operation_cannot_enter_generation_slot(self):
        result = smm.validate_slot_binding("hypit", "image", option(operation="anything_goes"))
        self.assertFalse(result["valid"])
        self.assertIn('OPERATION_NOT_ALLOWED', [reason['code'] for reason in result['reasons']])

    def test_unknown_slot_binding_is_rejected(self):
        result = smm.validate_slot_binding("hypit", "fixture-unknown-slot", option())
        self.assertFalse(result["valid"])
        self.assertEqual(result["reasons"][0]["code"], "OPERATION_NOT_ALLOWED")

    def test_validation_does_not_mutate_the_option(self):
        import json

        payload = option()
        snapshot = json.dumps(payload, sort_keys=True)
        smm.validate_slot_binding("hypit", "image", payload)
        self.assertEqual(json.dumps(payload, sort_keys=True), snapshot)


class HypitSettingsReuseTests(unittest.TestCase):
    """§9.4：Hypit 设置页必须复用同一份选项投影，不再各写一套筛选规则。"""

    SOURCE = (ROOT / "static" / "js" / "hypit-settings.js").read_text(encoding="utf-8")

    def test_slot_options_come_from_the_shared_projection(self):
        self.assertIn("function slotOptions(slot)", self.SOURCE)
        self.assertIn("state.catalog?.options", self.SOURCE,
                      "槽位候选必须取自目录选项投影")
        self.assertRegex(self.SOURCE, r"option\.node_type === nodeType\s*&& option\.runnable === true")

    def test_enabled_models_prefers_the_projection(self):
        start = self.SOURCE.index("function enabledModels(slot)")
        body = self.SOURCE[start:start + 300]
        self.assertIn("slotOptions(slot)", body, "必须优先使用共享投影")
        self.assertIn("if (projected) return projected", body)

    def test_projection_path_carries_the_fields_downstream_code_needs(self):
        start = self.SOURCE.index("function slotOptions(slot)")
        body = self.SOURCE[start:self.SOURCE.index('function enabledModels(slot)', start)]
        for field in ("option_id", "provider_id", "model_id", "region", "parameters", "inputs"):
            self.assertIn(field + ":", body, f"映射结果必须带 {field}，否则下游选择与参数面板会断")
        self.assertIn("canonical_family_id", body)


class ProjectionContractBoundaryTests(unittest.TestCase):
    """跨边界：后端投影字段必须正是前端 slotOptions 消费的那些。"""

    @classmethod
    def setUpClass(cls):
        import main
        from fastapi.testclient import TestClient

        cls.client = TestClient(main.app, base_url="http://127.0.0.1")

    def test_capabilities_endpoint_exposes_the_flat_projection(self):
        response = self.client.get("/api/model-capabilities")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("options", payload, "目录必须携带扁平可执行选项投影")
        self.assertTrue(payload["options"], "投影不得为空，否则前端会静默回退")
        self.assertTrue(str(payload.get("catalog_revision") or "").startswith("rev_"))

    def test_projected_fields_match_what_the_settings_page_consumes(self):
        options = self.client.get("/api/model-capabilities").json()["options"]
        consumed = ("option_id", "node_type", "runnable", "connection_id",
                    "catalog_model_id", "region_id", "parameters", "inputs")
        for option in options[:200]:
            for key in consumed:
                self.assertIn(key, option, f"前端会读取 {key}，投影必须提供")
        self.assertTrue(any(o["runnable"] is True for o in options), "至少要有可运行候选")

    def test_hypit_capabilities_endpoint_returns_the_full_option_projection(self):
        response = self.client.get("/api/studio/hypit/models/capabilities")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        options = payload.get("options")
        self.assertIsInstance(options, list)
        self.assertTrue(options, "Hypit capability response must include its candidate options")
        self.assertEqual(set(payload.get("slot_options") or {}), {"text", "image", "video", "audio", "music", "voice"})
        consumed = ("option_id", "node_type", "runnable", "connection_id", "catalog_model_id",
                    "region_id", "parameters", "inputs")
        for option in options:
            for key in consumed:
                self.assertIn(key, option, f"Hypit candidate projection is missing {key}")

    def test_settings_page_loads_the_shared_canvas_shell_and_route(self):
        # Hypit 设置现在嵌入共享画布；API 页不再维护第二套六槽选择器。
        page = (ROOT / "static" / "api-settings.html").read_text(encoding="utf-8")
        self.assertIn("hypit-settings.js", page, "设置页必须加载共享画布宿主脚本")
        self.assertIn("settings-canvas-controller.js", page, "四种配置必须先加载共同的画布生命周期控制器")
        self.assertIn('id="hypitSettingsCanvasFrame"', page, "设置页必须挂载共享画布 iframe")
        self.assertIn('id="hypitSettingsReset"', page, "共享画布需要原子重置入口")
        self.assertIn('id="hypitSettingsNewTab"', page, "共享画布需要同一画布的独立编辑入口")
        source = (ROOT / "static" / "js" / "hypit-settings.js").read_text(encoding="utf-8")
        self.assertIn("window.StudioSettingsCanvasController.create({", source, "Hypit must use the shared iframe lifecycle controller")
        self.assertIn("endpoint: '/api/hypit/settings-canvas'", source, "shared controller must retain the Hypit bootstrap route")
        self.assertIn("SETTINGS_CANVAS_ID = 'hypit-settings'", source, "共享画布 ID 必须稳定")
        controller = (ROOT / "static" / "js" / "settings-canvas-controller.js").read_text(encoding="utf-8")
        self.assertIn("/static/smart-canvas.html", controller, "必须复用智能画布页面")
        self.assertIn("searchParams.getAll('mode')", controller, "专用模式必须通过同一画布 URL 识别")

    def test_missing_projection_is_not_silent(self):
        source = (ROOT / "static" / "js" / "hypit-settings.js").read_text(encoding="utf-8")
        start = source.index("function slotOptions(slot)")
        body = source[start:start + 1200]
        self.assertIn("projectionAvailable = false", body, "投影缺失必须留下可观测状态")
        self.assertIn("console.warn", body, "投影缺失不得静默回退")


if __name__ == "__main__":
    unittest.main()
