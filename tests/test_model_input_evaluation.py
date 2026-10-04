"""P3 输入/参数决策核心的行为回归。

对应《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§6、§7、§17 B/C 系列。

全部使用虚构 fixture（§18.1），不读真实目录、不写真实用户配置、不发任何请求。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import studio_model_evaluation as ev  # noqa: E402


def option(**overrides) -> dict:
    base = {
        "option_id": "opt_0000000000000000",
        "connection_id": "fixture-conn-a",
        "region_id": "global",
        "operation": "text_to_video",
        "node_type": "video_generation",
        "catalog_model_id": "fixturevideo-t",
        "endpoint_id": "fixture-endpoint-t",
        "readiness": "ready",
        "output_contract": "video,min=1,max=1",
        "identity_mapping_status": "mapped",
    }
    base.update(overrides)
    return base


def binding(binding_id: str, media_type: str, role: str = "unassigned", **overrides) -> dict:
    data = {
        "binding_id": binding_id,
        "source_kind": "canvas_edge",
        "media_type": media_type,
        "role": role,
        "metadata_status": "verified_local",
    }
    data.update(overrides)
    return data


PROMPT = {"prompt": {"media_type": "text", "role": "prompt", "min": 1, "max": 1}}

PROFILE_T2V = {"inputs": dict(PROMPT)}
PROFILE_FIRST = {"inputs": {**PROMPT, "first_frame": {"media_type": "image", "role": "first_frame", "min": 1, "max": 1}}}
PROFILE_FIRST_LAST = {
    "inputs": {
        **PROMPT,
        "first_frame": {"media_type": "image", "role": "first_frame", "min": 1, "max": 1},
        "last_frame": {"media_type": "image", "role": "last_frame", "min": 1, "max": 1},
    }
}
PROFILE_FIRST_OR_REFERENCE = {
    "inputs": {
        **PROMPT,
        "first_frame": {"media_type": "image", "role": "first_frame", "min": 0, "max": 1},
        "reference": {"media_type": "image", "role": "reference", "min": 0, "max": 3},
    }
}
PROFILE_MULTIMODAL = {
    "inputs": {
        "reference": {"media_type": "image", "role": "reference", "min": 0, "max": 3},
        "reference_video": {"media_type": "video", "role": "reference_video", "min": 0, "max": 1},
        "reference_audio": {"media_type": "audio", "role": "reference_audio", "min": 0, "max": 1},
    },
    "input_total_max": 4,
}
PROFILE_DRIVING = {"inputs": {**PROMPT, "driving_audio": {"media_type": "audio", "role": "driving_audio", "min": 1, "max": 1}}}
PROFILE_MASK_EDIT = {
    "inputs": {
        **PROMPT,
        "reference": {"media_type": "image", "role": "reference", "min": 0, "max": 1},
        "mask": {"media_type": "image", "role": "mask", "min": 0, "max": 1},
    }
}
PROFILE_TWO_IMAGE_ROLES = {
    "inputs": {
        "reference": {"media_type": "image", "role": "reference", "min": 0, "max": 3},
        "mask": {"media_type": "image", "role": "mask", "min": 0, "max": 3},
    },
    "input_total_max": 4,
}
PROFILE_TWO_IMAGE_ROLES_CAP2 = {
    "inputs": {
        "reference": {"media_type": "image", "role": "reference", "min": 0, "max": 1},
        "mask": {"media_type": "image", "role": "mask", "min": 0, "max": 1},
    },
}


def codes(result: dict) -> list[str]:
    return [item["code"] for item in result["reasons"]]


class InputScenarioTests(unittest.TestCase):
    """规划表 7.9 的输入场景。"""

    def test_b01_empty_node_can_configure_but_not_run(self):
        result = ev.evaluate_option(option(), PROFILE_T2V, bindings=[], context="live")
        self.assertTrue(result["selectable"], "空节点仍应能选择模型")
        self.assertFalse(result["runnable"], "缺提示词时不得可运行")
        self.assertEqual(result["input_status"], "needs_input")
        self.assertIn("INPUT_REQUIRED", codes(result))

    def test_b02_single_image_keeps_both_meanings(self):
        result = ev.evaluate_option(
            option(), PROFILE_FIRST_OR_REFERENCE,
            bindings=[binding("b1", "image", "unassigned")], context="live",
        )
        self.assertEqual(result["input_status"], "needs_binding", "不得自动锁定为首帧")
        self.assertIn("ROLE_AMBIGUOUS", codes(result))
        self.assertFalse(result["runnable"])

    def test_b03_explicit_first_and_last_roles_are_kept(self):
        result = ev.evaluate_option(
            option(), PROFILE_FIRST_LAST,
            bindings=[
                binding("p", "text", "prompt"),
                binding("f", "image", "first_frame", role_origin="explicit_port"),
                binding("l", "image", "last_frame", role_origin="explicit_port"),
            ],
            context="live",
        )
        self.assertEqual(result["input_status"], "compatible")
        self.assertTrue(result["runnable"])
        self.assertEqual(set(result["consumed_binding_ids"]), {"p", "f", "l"})
        self.assertNotIn("ROLE_AMBIGUOUS", codes(result))

    def test_b04_two_images_without_roles_require_confirmation(self):
        result = ev.evaluate_option(
            option(), PROFILE_FIRST_LAST,
            bindings=[
                binding("p", "text", "prompt"),
                binding("i1", "image"),
                binding("i2", "image"),
            ],
            context="live",
        )
        self.assertEqual(result["input_status"], "needs_binding", "不得用连线顺序猜首尾")
        self.assertIn("ROLE_AMBIGUOUS", codes(result))

    def test_b07_only_last_frame_reports_missing_first_frame(self):
        result = ev.evaluate_option(
            option(), PROFILE_FIRST,
            bindings=[
                binding("p", "text", "prompt"),
                binding("l", "image", "last_frame", role_origin="explicit_user"),
            ],
            context="live",
        )
        self.assertEqual(result["input_status"], "needs_input")
        self.assertIn("ROLE_CONFLICT", codes(result), "显式尾帧与该模式冲突必须说明")
        self.assertTrue(
            any(item["code"] == "INPUT_REQUIRED" and item["detail"].get("role") == "first_frame" for item in result["reasons"]),
            "必须指出缺少首帧，而不是把尾帧改首帧",
        )
        self.assertFalse(result["runnable"])

    def test_b06_driving_audio_is_not_downgraded_to_reference_audio(self):
        # 只有驱动音频契约的叶子可接受 driving_audio
        ok = ev.evaluate_option(
            option(), PROFILE_DRIVING,
            bindings=[binding("p", "text", "prompt"), binding("a", "audio", "driving_audio")],
            context="live",
        )
        self.assertEqual(ok["input_status"], "compatible")
        # 普通参考音频契约不接受 driving_audio
        bad = ev.evaluate_option(
            option(), PROFILE_MULTIMODAL,
            bindings=[binding("a", "audio", "driving_audio")],
            context="live",
        )
        self.assertIn("ROLE_CONFLICT", codes(bad))
        self.assertFalse(bad["runnable"])

    def test_b08_three_outputs_of_one_edge_count_as_three(self):
        result = ev.evaluate_option(
            option(), PROFILE_MULTIMODAL,
            bindings=[
                binding("edge-1:output-0", "image", "reference"),
                binding("edge-1:output-1", "image", "reference"),
                binding("edge-1:output-2", "image", "reference"),
            ],
            context="live",
        )
        self.assertEqual(result["input_status"], "compatible")
        self.assertEqual(len(result["consumed_binding_ids"]), 3, "一根边的 3 个输出必须按 3 份计算")

    def test_b09_four_reference_images_exceed_limit_of_three(self):
        result = ev.evaluate_option(
            option(), PROFILE_MULTIMODAL,
            bindings=[binding(f"i{n}", "image") for n in range(4)],
            context="live",
        )
        self.assertEqual(result["input_status"], "incompatible")
        self.assertIn("INPUT_COUNT_EXCEEDED", codes(result))
        self.assertFalse(result["runnable"], "不得丢弃第 4 张后继续运行")

    def test_b10_role_maxima_must_not_be_summed_into_global_limit(self):
        """各角色单独不超限，但合计超过宿主总量上限时必须拒绝。"""
        result = ev.evaluate_option(
            option(), PROFILE_TWO_IMAGE_ROLES,
            bindings=[binding(f"i{n}", "image") for n in range(5)],
            context="live",
        )
        self.assertEqual(result["input_status"], "incompatible")
        self.assertIn("INPUT_COMBINATION_INVALID", codes(result))
        self.assertTrue(
            any(item["detail"].get("limit") == 4 for item in result["reasons"]),
            "必须按宿主声明的总量上限 4 判定，而不是各角色 max 相加",
        )

    def test_b11_unconsumed_material_blocks_execution(self):
        result = ev.evaluate_option(
            option(), PROFILE_TWO_IMAGE_ROLES_CAP2,
            bindings=[binding(f"i{n}", "image") for n in range(3)],
            context="live",
        )
        self.assertFalse(result["runnable"])
        self.assertIn("UNCONSUMED_INPUT", codes(result))
        self.assertTrue(result["unconsumed_binding_ids"], "必须列出未被消费的素材")

    def test_b13_mask_without_support_is_rejected(self):
        result = ev.evaluate_option(
            option(), {**PROFILE_T2V, "inputs": {**PROMPT, "reference": {"media_type": "image", "role": "reference", "min": 0, "max": 1}}},
            bindings=[binding("p", "text", "prompt"), binding("m", "image", "mask")],
            context="live",
        )
        self.assertIn("ROLE_CONFLICT", codes(result))
        self.assertFalse(result["runnable"], "不支持 mask 时不得丢弃 mask 继续运行")

    def test_b14_unknown_metadata_blocks_when_contract_declares_limits(self):
        profile = {
            "inputs": {
                "p": {"media_type": "text", "role": "prompt", "min": 1, "max": 1},
                "i": {"media_type": "image", "role": "reference", "min": 0, "max": 1, "constraints": {"max_bytes": 1024}},
            }
        }
        result = ev.evaluate_option(
            option(), profile,
            bindings=[binding("p", "text", "prompt"), binding("i", "image", "reference", metadata_status="unknown")],
            context="live",
        )
        self.assertIn("INPUT_METADATA_MISSING", codes(result))
        self.assertFalse(result["runnable"])

    def test_b15_planned_context_stays_configurable(self):
        result = ev.evaluate_option(option(), PROFILE_T2V, bindings=[], context="planned")
        self.assertTrue(result["selectable"], "上游未完成时仍应可配置")
        self.assertFalse(result["runnable"], "运行必须等素材落地后再校验")

    def test_b19_output_contract_decides_host_fit(self):
        audio_leaf = option(operation="audio_generation", node_type="audio_generation", output_contract="text")
        result = ev.evaluate_option(
            audio_leaf, {"inputs": PROMPT and {}},
            bindings=[], context="template",
            host_output_types=("audio",),
        )
        self.assertEqual(result["host_status"], "unsupported")
        self.assertIn("HOST_OUTPUT_UNSUPPORTED", codes(result))
        self.assertFalse(result["runnable"])

    def test_operation_not_allowed_by_host_slot(self):
        result = ev.evaluate_option(
            option(operation="image_edit"), PROFILE_T2V,
            bindings=[], context="template",
            host_contract={"allowed_operations": ["text_to_video"]},
        )
        self.assertIn("OPERATION_NOT_ALLOWED", codes(result))
        self.assertFalse(result["runnable"])


class StatusDimensionTests(unittest.TestCase):
    """§7.5 各维度必须分别返回，不能只给一个布尔。"""

    def test_dimensions_are_reported_separately(self):
        result = ev.evaluate_option(option(), PROFILE_T2V, bindings=[], context="live")
        for key in ("identity_status", "capability_status", "adapter_status", "connection_status",
                    "input_status", "parameter_status", "host_status"):
            self.assertIn(key, result)
        self.assertEqual(result["identity_status"], "mapped")
        self.assertEqual(result["adapter_status"], "ready")

    def test_connection_disabled_reports_specific_code(self):
        result = ev.evaluate_option(option(), PROFILE_T2V, bindings=[], context="live", connection_status="disabled")
        self.assertIn("CONNECTION_DISABLED", codes(result))
        self.assertFalse(result["runnable"])

    def test_region_disabled_reports_specific_code(self):
        result = ev.evaluate_option(option(), PROFILE_T2V, bindings=[], context="live", connection_status="region_disabled")
        self.assertIn("REGION_DISABLED", codes(result))

    def test_unconfigured_connection_asks_for_credentials(self):
        result = ev.evaluate_option(option(), PROFILE_T2V, bindings=[], context="live", connection_status="unconfigured")
        self.assertIn("CREDENTIAL_NOT_CONFIGURED", codes(result))

    def test_pending_profile_and_missing_adapter(self):
        pending = ev.evaluate_option(option(readiness="needs_profile"), PROFILE_T2V, bindings=[], context="live")
        self.assertIn("PROFILE_UNCONFIRMED", codes(pending))
        missing = ev.evaluate_option(option(readiness="adapter_missing"), PROFILE_T2V, bindings=[], context="live")
        self.assertIn("ADAPTER_MISSING", codes(missing))

    def test_every_reason_has_machine_code_and_localized_text(self):
        result = ev.evaluate_option(
            option(readiness="adapter_missing"), PROFILE_T2V,
            bindings=[], context="live", connection_status="disabled",
        )
        self.assertTrue(result["reasons"])
        for item in result["reasons"]:
            self.assertIn(item["code"], ev.REASON_TEXT, "原因码必须在统一表内")
            self.assertTrue(item["message"]["zh"])
            self.assertTrue(item["message"]["en"])


class ParameterTests(unittest.TestCase):
    """规划 §17 C 系列参数行为。"""

    DISCRETE_DURATION = {"parameters": {"duration": {"type": "integer", "options": [4, 8, 12], "default": 8}}}
    INTEGER_DURATION = {"parameters": {"duration": {"type": "integer", "min": 4, "max": 30, "step": 1, "default": 5}}}
    BOOL_FLAG = {"parameters": {"generate_audio": {"type": "boolean", "default": False}}}
    STEP_NUMBER = {"parameters": {"strength": {"type": "number", "min": 0, "max": 1, "step": 0.5, "default": 0.5}}}

    def test_c01_default_applied_and_idempotent(self):
        once = ev.apply_defaults(self.DISCRETE_DURATION, {})
        twice = ev.apply_defaults(self.DISCRETE_DURATION, once)
        self.assertEqual(once["duration"], 8)
        self.assertEqual(once, twice, "重复应用默认值不得改变结果")

    def test_c02_required_enum_without_default_stays_empty(self):
        profile = {"parameters": {"resolution": {"type": "enum", "options": ["720p", "1080p"], "required": True}}}
        values = ev.apply_defaults(profile, {})
        self.assertNotIn("resolution", values, "没有 default 的必填项不得自动取第一项")
        status, issues = ev.evaluate_parameters(profile, values)
        self.assertEqual(status, "needs_value")
        self.assertEqual(issues.get("resolution"), "PARAM_REQUIRED")

    def test_c03_false_and_zero_are_kept(self):
        values = ev.apply_defaults(self.BOOL_FLAG, {"generate_audio": False})
        self.assertIs(values["generate_audio"], False, "false 必须原样保留")
        zero = {"parameters": {"seed": {"type": "integer", "min": 0, "max": 100, "default": 42}}}
        self.assertEqual(ev.apply_defaults(zero, {"seed": 0})["seed"], 0, "0 必须原样保留")

    def test_c04_null_absent_and_empty_are_distinct(self):
        self.assertTrue(ev.is_missing(None))
        self.assertFalse(ev.is_missing(False))
        self.assertFalse(ev.is_missing(0))
        self.assertFalse(ev.is_missing(""))
        values = ev.apply_defaults(self.DISCRETE_DURATION, {"duration": None})
        self.assertEqual(values["duration"], 8, "显式 null 视为未设置，应用默认")

    def test_c05_discrete_duration_only_allows_declared_values(self):
        for bad in (5, 6, 7):
            self.assertEqual(ev.validate_parameter_value(self.DISCRETE_DURATION["parameters"]["duration"], bad), "PARAM_INVALID")
        for good in (4, 8, 12):
            self.assertIsNone(ev.validate_parameter_value(self.DISCRETE_DURATION["parameters"]["duration"], good))

    def test_c06_integer_range_reaches_every_step(self):
        spec = self.INTEGER_DURATION["parameters"]["duration"]
        for value in range(4, 31):
            self.assertIsNone(ev.validate_parameter_value(spec, value), f"{value} 应合法")
        self.assertEqual(ev.validate_parameter_value(spec, 31), "PARAM_INVALID")
        self.assertEqual(ev.validate_parameter_value(spec, 3), "PARAM_INVALID")

    def test_c07_number_step_and_fractional_precision(self):
        spec = self.STEP_NUMBER["parameters"]["strength"]
        self.assertIsNone(ev.validate_parameter_value(spec, 0.5))
        self.assertIsNone(ev.validate_parameter_value(spec, 1))
        self.assertEqual(ev.validate_parameter_value(spec, 0.3), "PARAM_INVALID", "步长不合法的值必须拒绝而非取整")

    def test_c09_illegal_value_kept_visible_not_silently_changed(self):
        old = {"parameters": {"duration": {"type": "integer", "min": 4, "max": 30, "step": 1, "default": 5}}}
        new = {"parameters": {"duration": {"type": "integer", "min": 4, "max": 15, "step": 1, "default": 5}}}
        result = ev.reconcile_parameters(old, new, {"duration": 30})
        self.assertEqual(result["activeValues"]["duration"], 30, "必须保留用户原值而不是压到 15")
        self.assertIn("duration", result["validationIssues"])
        self.assertEqual(result["validationIssues"]["duration"]["code"], "PARAM_INVALID")

    def test_c10_unknown_field_becomes_draft_not_sent(self):
        old = {"parameters": {"legacy_style": {"type": "string"}}}
        new = {"parameters": {"duration": {"type": "integer", "min": 1, "max": 10, "default": 5}}}
        result = ev.reconcile_parameters(old, new, {"legacy_style": "anime"})
        self.assertNotIn("legacy_style", result["activeValues"], "旧字段不得进入提交值")
        self.assertEqual(result["inactiveDraftValues"]["legacy_style"], "anime", "旧字段必须保留为草稿")
        self.assertTrue(any(item["code"] == "DRAFT_ONLY" for item in result["notices"]))

    def test_c11_conditional_applicability_switches_duration(self):
        profile = {
            "parameters": {
                "resolution": {"type": "enum", "options": ["720p", "1080p"], "default": "720p"},
                "duration_1080": {
                    "type": "integer", "min": 4, "max": 8, "default": 5,
                    "applicable_if": {"op": "eq", "path": "resolution", "value": "1080p"},
                },
            }
        }
        at_720 = ev.apply_defaults(profile, {"resolution": "720p"}, {"resolution": "720p"})
        self.assertNotIn("duration_1080", at_720, "条件不适用时不得注入")
        at_1080 = ev.apply_defaults(profile, {"resolution": "1080p"}, {"resolution": "1080p"})
        self.assertEqual(at_1080["duration_1080"], 5)

    def test_c11_illegal_condition_operator_raises(self):
        with self.assertRaises(ValueError):
            ev.evaluate_condition({"op": "eval", "value": "1+1"}, {})

    def test_c12_hidden_but_fixed_value_is_rejected_when_overridden(self):
        profile = {
            "inputs": dict(PROMPT),
            "fixed_parameters": {"mode": "standard"},
            "parameters": {},
        }
        blocked = ev.validate_execution(
            option(), profile,
            [binding("p", "text", "prompt")], {"mode": "pro"},
        )
        self.assertIn("FIXED_PARAM_OVERRIDE", ev_codes(blocked))
        self.assertFalse(blocked["runnable"])
        allowed = ev.validate_execution(option(), profile, [binding("p", "text", "prompt")], {})
        self.assertTrue(allowed["runnable"])

    def test_c16_native_resolution_enum_value_is_preserved(self):
        profile = {"parameters": {"resolution": {"type": "enum", "options": ["720p", "1080p", "native1080p"], "default": "native1080p"}}}
        values = ev.apply_defaults(profile, {})
        self.assertEqual(values["resolution"], "native1080p", "真实枚举值不得被本地化改写")
        self.assertIsNone(ev.validate_parameter_value(profile["parameters"]["resolution"], "native1080p"))

    def test_c17_reset_only_touches_current_leaf_parameters(self):
        profile = {**self.DISCRETE_DURATION, "parameters": {**self.DISCRETE_DURATION["parameters"], "resolution": {"type": "enum", "options": ["720p"], "default": "720p"}}}
        reset = ev.reset_to_profile_defaults(profile)
        self.assertEqual(reset, {"duration": 8, "resolution": "720p"})
        self.assertNotIn("catalog_model_id", reset)
        self.assertNotIn("connection_id", reset)

    def test_c18_nan_infinity_and_unknown_boolean_are_rejected(self):
        spec = {"type": "number", "min": 0, "max": 10}
        self.assertEqual(ev.validate_parameter_value(spec, float("nan")), "PARAM_INVALID")
        self.assertEqual(ev.validate_parameter_value(spec, float("inf")), "PARAM_INVALID")
        boolean = {"type": "boolean"}
        for bad in ("maybe", "true", "0", 1):
            self.assertEqual(
                ev.validate_parameter_value(boolean, bad), "PARAM_INVALID",
                f"{bad!r} 不是真实布尔值，运行路径不得隐式强转",
            )
        self.assertIsNone(ev.validate_parameter_value(boolean, True))
        self.assertIsNone(ev.validate_parameter_value(boolean, False))

    def test_c19_text_length_contract_counts_code_points(self):
        self.assertEqual(ev.text_length("中文"), 2)
        self.assertEqual(ev.text_length("🎬"), 1, "emoji 必须以码点计，与前端 [...s].length 对齐")
        self.assertEqual(ev.text_length(None), 0)

    def test_c20_field_is_not_duplicated_between_common_and_advanced(self):
        profile = {"parameters": {"seed": {"type": "integer", "min": 0, "max": 10, "level": "advanced", "ui": {"level": "advanced"}}}}
        values = ev.apply_defaults(profile, {})
        self.assertNotIn("seed", values)
        result = ev.reconcile_parameters(profile, profile, {"seed": 3})
        self.assertEqual(list(result["activeValues"].keys()), ["seed"], "同一字段只能有一份可编辑值")


class EvaluationVectorTests(unittest.TestCase):
    """前后端共享测试向量的确定性（§16 P3 第 5 项）。"""

    def test_evaluation_is_deterministic_across_runs(self):
        kwargs = dict(bindings=[binding("b1", "image")], context="live")
        first = ev.evaluate_option(option(), PROFILE_FIRST_OR_REFERENCE, **kwargs)
        second = ev.evaluate_option(option(), PROFILE_FIRST_OR_REFERENCE, **kwargs)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_evaluation_does_not_mutate_inputs(self):
        bindings = [binding("b1", "image", "reference")]
        snapshot = json.dumps(bindings, sort_keys=True)
        profile_snapshot = json.dumps(PROFILE_MULTIMODAL, sort_keys=True)
        ev.evaluate_option(option(), PROFILE_MULTIMODAL, bindings=bindings, context="live")
        self.assertEqual(json.dumps(bindings, sort_keys=True), snapshot, "评估不得修改调用方数据")
        self.assertEqual(json.dumps(PROFILE_MULTIMODAL, sort_keys=True), profile_snapshot)

    def test_frozen_snapshot_contains_no_credentials(self):
        snapshot = ev.freeze_execution_snapshot(
            option=option(), bindings=[binding("b1", "image", "reference")],
            parameters={"duration": 5}, catalog_revision="rev-1", module_id="hypit", slot_id="video",
        )
        blob = json.dumps(snapshot, ensure_ascii=False).lower()
        for forbidden in ("api_key", "authorization", "bearer", "cookie", "secret"):
            self.assertNotIn(forbidden, blob)


def ev_codes(result: dict) -> list[str]:
    return [item["code"] for item in result["reasons"]]


class SharedVectorConsistencyTests(unittest.TestCase):
    """前后端共享测试向量：同一份 JSON 必须让 Python 与 Node 得出相同判定（§13.5）。"""

    VECTORS = ROOT / "tests" / "model_selection_fixtures" / "parameter_vectors.json"

    def _python_judgement(self, spec: dict, value) -> str:
        issue = ev.validate_parameter_value(spec, value)
        if issue is None:
            return "legal"
        if issue == "PARAM_REQUIRED":
            return "required"
        return "illegal"

    def _node_judgements(self) -> dict:
        import subprocess

        script = (
            "const c=require('./static/js/smart-model-capabilities.js');"
            "const fs=require('fs');"
            "const v=JSON.parse(fs.readFileSync('tests/model_selection_fixtures/parameter_vectors.json','utf8'));"
            "const out={};"
            "for(const item of v.cases){"
            " const issue=c.parameterIssue(item.spec, item.value);"
            " out[item.id]= issue==='' ? 'legal' : (issue==='PARAM_REQUIRED' ? 'required' : 'illegal');"
            "}"
            "console.log(JSON.stringify(out));"
        )
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True
        )
        return json.loads(result.stdout)

    def test_vectors_are_marked_test_only(self):
        payload = json.loads(self.VECTORS.read_text(encoding="utf-8"))
        self.assertTrue(payload["test_only"])
        self.assertTrue(payload["cases"])

    def test_python_matches_declared_expectations(self):
        payload = json.loads(self.VECTORS.read_text(encoding="utf-8"))
        for case in payload["cases"]:
            with self.subTest(case=case["id"]):
                self.assertEqual(
                    self._python_judgement(case["spec"], case["value"]),
                    case["expect"],
                    case.get("why", ""),
                )

    def test_node_matches_python_for_every_vector(self):
        payload = json.loads(self.VECTORS.read_text(encoding="utf-8"))
        node = self._node_judgements()
        for case in payload["cases"]:
            with self.subTest(case=case["id"]):
                self.assertIn(case["id"], node, "Node 必须逐个返回判定")
                self.assertEqual(
                    node[case["id"]],
                    self._python_judgement(case["spec"], case["value"]),
                    f"{case['id']} 前后端判定不一致：{case.get('why','')}",
                )

    def test_effective_parameters_never_silently_rewrites_values(self):
        """前端取值只做放行/丢弃，不得改写数值（§1.3）。"""
        import subprocess

        script = (
            "const c=require('./static/js/smart-model-capabilities.js');"
            "const profile={validation_mode:'strict',parameters:{"
            "  duration:{type:'integer',min:4,max:15,step:1},"
            "  resolution:{type:'enum',options:['720p','native1080p']}}};"
            "const out=c.effectiveParameters(profile,{duration:30,resolution:'native1080p'});"
            "const issues=c.parameterIssues(profile,{duration:30,resolution:'720p'});"
            "console.log(JSON.stringify({out,issues}));"
        )
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True
        )
        payload = json.loads(result.stdout)
        self.assertNotIn("duration", payload["out"], "越界值不得被裁剪后提交")
        self.assertEqual(payload["out"]["resolution"], "native1080p", "合法枚举值必须原样通过")
        self.assertEqual(payload["issues"]["duration"], "PARAM_INVALID", "非法字段必须被报出")


if __name__ == "__main__":
    unittest.main()
