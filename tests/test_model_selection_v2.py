"""P2 稳定身份与可执行选项投影的行为回归。

对应《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§8、§16 P2、§17 A11/E01/E06。

所有用例只使用假数据或只读仓库快照；不写任何真实用户配置（§2.3）。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import studio_model_selection as sms  # noqa: E402

FIXTURE = ROOT / "tests" / "model_selection_fixtures" / "fixture_options.json"


def load_fixture_records() -> list[dict]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if not payload.get("test_only"):
        raise AssertionError("fixture 必须标记 test_only")
    return payload["records"]


class OptionIdentityTests(unittest.TestCase):
    """option_id 的稳定性、敏感性与语言无关性。"""

    def test_option_id_is_stable_for_same_tuple(self):
        first = sms.compute_option_id(
            connection_id="c1", region_id="global", deployment_id="", node_type="video_generation",
            catalog_model_id="Seedance-X", endpoint_id="ep-1", operation="text_to_video",
        )
        second = sms.compute_option_id(
            connection_id="c1", region_id="global", deployment_id="", node_type="video_generation",
            catalog_model_id="Seedance-X", endpoint_id="ep-1", operation="text_to_video",
        )
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("opt_"))

    def test_option_id_changes_with_region_operation_and_endpoint(self):
        base = dict(
            connection_id="c1", region_id="global", deployment_id="", node_type="video_generation",
            catalog_model_id="fixture-1", endpoint_id="ep-1", operation="text_to_video",
        )
        baseline = sms.compute_option_id(**base)
        self.assertNotEqual(baseline, sms.compute_option_id(**{**base, "region_id": "cn"}))
        self.assertNotEqual(baseline, sms.compute_option_id(**{**base, "operation": "image_to_video"}))
        self.assertNotEqual(baseline, sms.compute_option_id(**{**base, "endpoint_id": "ep-2"}))
        self.assertNotEqual(baseline, sms.compute_option_id(**{**base, "connection_id": "c2"}))

    def test_option_id_ignores_display_labels_and_language(self):
        """A11：改名或切换语言不得改变选择身份。"""
        record = {
            "capability_provider_id": "fixture-provider-a",
            "connection_id": "fixture-conn-a",
            "region_id": "global",
            "catalog_model_id": "fixturevideo-t",
            "endpoint_id": "fixture-endpoint-t",
            "legacy_family_id": "fixture-video-t",
            "node_type": "video_generation",
            "operation": "text_to_video",
        }
        option = sms.compile_option(record)
        renamed_family = {**record, "legacy_family_id": "完全不同的显示名"}
        other = sms.compile_option(renamed_family)
        # legacy_family_id 只影响 canonical 归属，不影响 option_id
        self.assertEqual(option["option_id"], other["option_id"])
        label_zh = sms.option_display_label(option)["zh"]
        option["canonical_family_label"] = {"zh": "改名后", "en": "Renamed"}
        self.assertEqual(label_zh, sms.option_display_label(option)["zh"])

    def test_raw_model_id_case_is_preserved(self):
        """§8.3：原始模型 ID 大小写不得随意规范化。"""
        option = sms.compile_option({
            "capability_provider_id": "runninghub", "connection_id": "runninghub", "region_id": "global",
            "catalog_model_id": "Seedance2.0 Fast Image to Video", "endpoint_id": "ep",
            "node_type": "video_generation", "operation": "image_to_video",
        })
        self.assertEqual(option["catalog_model_id"], "Seedance2.0 Fast Image to Video")


class SameIdIsNotMergedTests(unittest.TestCase):
    """E01 / §8.3.1：同 ID 跨站、同 ID 跨操作都不能被合并丢失。"""

    def setUp(self):
        self.options = sms.compile_options(load_fixture_records())
        self.by_model: dict[str, list[dict]] = {}
        for option in self.options:
            self.by_model.setdefault(option["catalog_model_id"], []).append(option)

    def test_same_id_in_two_regions_yields_two_options(self):
        items = self.by_model["fixturevideo-m"]
        self.assertEqual(len(items), 2, "同 ID 跨站必须保留为两个叶子")
        self.assertEqual({item["region_id"] for item in items}, {"global", "cn"})
        self.assertEqual(len({item["option_id"] for item in items}), 2)

    def test_same_id_two_operations_yields_two_options(self):
        items = self.by_model["fixtureaudio-dual"]
        self.assertEqual(len(items), 2, "同 ID 两个 operation 必须都保留")
        self.assertEqual({item["operation"] for item in items}, {"speech_or_audio", "text_to_audio"})
        self.assertEqual(len({item["option_id"] for item in items}), 2)

    def test_conflict_report_detects_both_shapes(self):
        report = sms.detect_conflicts(self.options)
        self.assertIn("fixturevideo-m", report["cross_region_same_id"])
        self.assertGreaterEqual(report["multi_operation_same_id_count"], 1)
        self.assertTrue(any("fixtureaudio-dual" in key for key in report["multi_operation_same_id"]))


class IdentityMappingTests(unittest.TestCase):
    """§8.1 / §19.4：未知等价保留 provider-local，不伪造能力。"""

    def test_unmapped_model_keeps_provider_local_identity(self):
        identity = sms.resolve_identity(
            capability_provider_id="fixture-provider-c", adapter_id="fixture-adapter-c",
            model_id="fixturetext-unknown", family_id="fixture-text-unknown", node_type="text_generation",
        )
        self.assertEqual(identity["identity_mapping_status"], "provider_local")
        self.assertTrue(identity["canonical_family_id"].startswith("provider-local:"))
        self.assertEqual(identity["identity_evidence"]["status"], "unmapped")

    def test_unmapped_does_not_gain_capability(self):
        """未知身份不得被赋予以外能力：readiness 原样透传。"""
        option = sms.compile_option({
            "capability_provider_id": "fixture-provider-c", "connection_id": "fixture-conn-c",
            "catalog_model_id": "fixture-3d-tool", "node_type": "text_generation",
            "operation": "text_to_3d", "readiness": "adapter_missing", "output_contract": "model3d",
        })
        self.assertEqual(option["readiness"], "adapter_missing")
        self.assertEqual(option["output_contract"], "model3d")

    def test_mapped_model_records_evidence(self):
        identity = sms.resolve_identity(
            capability_provider_id="jimeng-cli", adapter_id="jimeng-cli",
            model_id="seedance2.0", family_id="jimeng-seedance-2.0", node_type="video_generation",
        )
        self.assertEqual(identity["canonical_family_id"], "seedance")
        self.assertEqual(identity["identity_mapping_status"], "mapped")
        self.assertEqual(identity["identity_evidence"]["status"], "reviewed")
        self.assertTrue(identity["identity_evidence"]["source_ref"])
        self.assertEqual(identity["model_version"], "2.0")
        self.assertEqual(identity["model_version_origin"], "id_pattern")

    def test_catalog_repairs_existing_jimeng_and_minimax_video_families(self):
        """补齐既有目录中的错绑项，同时保留模型 ID 作为唯一归类依据。"""
        identity_document = sms.load_identity_document(ROOT)

        jimeng = sms.resolve_identity(
            capability_provider_id="runninghub", adapter_id="runninghub",
            model_id="bytedance/jimeng-4.6/text-to-image", family_id="Seedream",
            node_type="image_generation", identity_document=identity_document,
        )
        self.assertEqual(jimeng["canonical_family_id"], "series-image-seedream")

        jimeng_cli = sms.resolve_identity(
            capability_provider_id="jimeng-cli", adapter_id="jimeng-cli",
            model_id="5.0Pro", family_id="jimeng-image-5.0-pro",
            node_type="image_generation", identity_document=identity_document,
        )
        self.assertEqual(jimeng_cli["canonical_family_id"], "series-image-seedream")

        hailuo = sms.resolve_identity(
            capability_provider_id="runninghub", adapter_id="runninghub",
            model_id="hailuo-h3-global-i2v", family_id="MiniMax H3",
            node_type="video_generation", identity_document=identity_document,
        )
        self.assertEqual(hailuo["canonical_family_id"], "series-video-minimax")

        grok = sms.resolve_identity(
            capability_provider_id="laohu", adapter_id="laohu",
            model_id="xai/grok-imagine-video-v1.5/text-to-video", family_id="MiniMax",
            node_type="video_generation", identity_document=identity_document,
        )
        self.assertEqual(grok["canonical_family_id"], "series-video-grok")

        midjourney = sms.resolve_identity(
            capability_provider_id="ai-money", adapter_id="ai-money",
            model_id="midjourney-modal", family_id="ai-money-midjourney",
            node_type="image_generation", identity_document=identity_document,
        )
        self.assertEqual(midjourney["canonical_family_id"], "series-image-midjourney")

    def test_text_aliases_use_the_requested_canonical_families(self):
        cases = {
            "g5": "series-text-gpt",
            "g6": "series-text-gpt",
            "gk-4.6": "series-text-grok",
            "gm-3.8-flash": "series-text-gemini",
            "laohu/g5.6-sol": "series-text-gpt",
            "laohu/g6-astra": "series-text-gpt",
            "laohu/gk-4.6": "series-text-grok",
            "laohu/gm-3.8-flash": "series-text-gemini",
            "minmax-h3-context-ir-text": "series-text-minimax",
            "moonshotai/kimi-k3": "series-text-kimi",
            "deepseek/deepseek-v4.1-flash": "series-text-deepseek",
            "glm-5.3-flash": "series-text-glm",
            "qwen/qwen3.8-max": "series-text-qwen",
            "bytedance/doubao-seed-2.1-pro": "series-text-doubao-seed",
        }
        for model_id, expected in cases.items():
            identity = sms.resolve_identity(
                capability_provider_id="ai-money", adapter_id="ai-money",
                model_id=model_id, family_id="provider-local-model", node_type="text_generation",
            )
            self.assertEqual(identity["canonical_family_id"], expected, model_id)

    def test_edition_extracted_from_id_literal_only(self):
        identity = sms.resolve_identity(
            capability_provider_id="runninghub", adapter_id="runninghub",
            model_id="seedance-2.0-mini/text-to-video", family_id="runninghub-seedance-2.0",
            node_type="video_generation",
        )
        self.assertEqual(identity["edition_id"], "mini")
        self.assertEqual(identity["edition_origin"], "id_token")

    def test_identity_rule_respects_node_type(self):
        """同一 token 在错误节点类型下不得被归并（防止能力外扩）。"""
        identity = sms.resolve_identity(
            capability_provider_id="runninghub", adapter_id="runninghub",
            model_id="seedance-2.0-t2v", family_id="x", node_type="audio_generation",
        )
        self.assertEqual(identity["identity_mapping_status"], "provider_local")


class RealCatalogAggregationTests(unittest.TestCase):
    """在真实仓库快照上验证跨平台聚合（只读，不写用户配置）。"""

    @classmethod
    def setUpClass(cls):
        import tools.audit_model_coverage as audit

        registry = audit.mc.ModelCapabilityRegistry(ROOT)
        loaded = registry.load()
        records = []
        for provider_id in loaded["registry"].get("providers") or []:
            pid = str(provider_id.get("provider_id") or "").strip()
            if pid:
                records.extend(audit.discovery_records(registry, loaded, pid))
        cls.options = sms.compile_options(records)
        cls.families = sms.group_by_canonical_family(cls.options)

    def test_seedance_aggregates_across_three_providers(self):
        items = self.families.get("seedance")
        self.assertIsNotNone(items, "Seedance 必须聚合为单一产品系列")
        providers = {item["capability_provider_id"] for item in items}
        self.assertGreaterEqual(len(providers), 2, f"Seedance 应跨平台聚合，实际 {providers}")
        self.assertIn("jimeng-cli", providers)

    def test_cross_region_same_id_preserved_in_real_catalog(self):
        report = sms.detect_conflicts(self.options)
        self.assertGreater(report["cross_region_same_id_count"], 0)
        for model_id, regions in list(report["cross_region_same_id"].items())[:5]:
            self.assertGreaterEqual(len(regions), 2, f"{model_id} 跨站必须保留两个站点")

    def test_identity_breakdown_is_reported(self):
        report = sms.detect_conflicts(self.options)
        self.assertGreater(report["mapped_count"], 0)
        self.assertGreater(report["unmapped_count"], 0)
        self.assertEqual(
            report["mapped_count"] + report["unmapped_count"],
            report["option_count"],
            "每个选项必须有明确身份状态，不得遗漏",
        )

    def test_option_ids_are_unique(self):
        ids = [option["option_id"] for option in self.options]
        self.assertEqual(len(ids), len(set(ids)), "option_id 必须唯一")


class IdentityDocumentTests(unittest.TestCase):
    """§8.2 身份索引文档结构。"""

    def test_document_shape_and_evidence(self):
        options = sms.compile_options(load_fixture_records())
        document = sms.build_identity_document(options)
        self.assertEqual(document["schema_version"], sms.IDENTITY_SCHEMA_VERSION)
        for family in document["families"]:
            self.assertTrue(family["id"])
            self.assertIn("zh", family["label"])
            self.assertIn("en", family["label"])
        for binding in document["bindings"]:
            self.assertIn("match", binding)
            self.assertTrue(binding["canonical_family_id"])
            self.assertTrue(binding["evidence"].get("source_ref"), "映射必须带证据来源")
        self.assertTrue(document["families"], "至少应有一个系列")

    def test_document_never_contains_credentials(self):
        options = sms.compile_options(load_fixture_records())
        blob = json.dumps(sms.build_identity_document(options), ensure_ascii=False).lower()
        for forbidden in ("api_key", "apikey", "authorization", "bearer", "cookie", "secret"):
            self.assertNotIn(forbidden, blob, f"身份索引不得包含 {forbidden}")


class FrontendVariantKeyTests(unittest.TestCase):
    """前端 variantSelectionKey 必须由机器字段决定，显示名与语言不参与（§8.3、A11）。"""

    def _run(self, script: str) -> dict:
        import subprocess

        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True
        )
        return json.loads(result.stdout)

    def test_variant_key_is_machine_only_with_legacy_fallback(self):
        script = r'''
const c = require('./static/js/smart-model-capabilities.js');
const base = {provider_id:'p1', model_id:'m-1', variant_id:'mode', operation:'text_to_video'};
const zh = c.variantSelectionKey({...base, variant_name:'标准', variant_name_en:'Standard'});
const renamedEn = c.variantSelectionKey({...base, variant_name:'Standard', variant_name_en:'Standard'});
const otherModel = c.variantSelectionKey({...base, model_id:'m-2'});
const otherRegion = c.variantSelectionKey({...base, region:'cn'});
const legacyFast = c.legacyVariantSelectionKey({variant_id:'mode', variant_name:'Fast'});
const legacyMini = c.legacyVariantSelectionKey({variant_id:'mode', variant_name:'Mini'});
const degenerateFast = c.variantSelectionKey({variant_id:'mode', variant_name:'Fast'});
const degenerateMini = c.variantSelectionKey({variant_id:'mode', variant_name:'Mini'});
console.log(JSON.stringify({zh, renamedEn, otherModel, otherRegion, legacyFast, legacyMini, degenerateFast, degenerateMini}));
'''
        r = self._run(script)
        self.assertEqual(r["zh"], r["renamedEn"], "改显示名/切换语言不得改变变体身份")
        self.assertNotEqual(r["zh"], r["otherModel"], "不同 model_id 必须是不同身份")
        self.assertNotEqual(r["legacyFast"], r["legacyMini"], "遗留 key 仍须区分 Fast/Mini")
        self.assertNotEqual(r["degenerateFast"], r["degenerateMini"], "缺 model_id 的退化数据回退旧 key")
        self.assertTrue(r["zh"].startswith("p1::mode::text_to_video::m-1"))

    def test_variant_key_has_no_display_name_in_machine_path(self):
        script = r'''
const c = require('./static/js/smart-model-capabilities.js');
const key = c.variantSelectionKey({provider_id:'p1', model_id:'m-1', variant_id:'mode',
  operation:'text_to_video', variant_name:'中文显示名', variant_name_en:'English label'});
console.log(JSON.stringify({key}));
'''
        r = self._run(script)
        self.assertNotIn("中文显示名", r["key"])
        self.assertNotIn("English label", r["key"])


class SchemaConformanceTests(unittest.TestCase):
    """不引入新依赖的结构校验：schema 文件与投影结果必须自洽。"""

    SCHEMA = ROOT / "data" / "model_capabilities" / "model-selection.schema.json"

    def test_schema_file_is_valid_and_has_required_defs(self):
        schema = json.loads(self.SCHEMA.read_text(encoding="utf-8"))
        for name in ("identityDocument", "executionOption", "modelSelection", "parameterField", "condition"):
            self.assertIn(name, schema["$defs"], f"schema 缺少 $defs.{name}")
        self.assertEqual(schema["$defs"]["executionOption"]["properties"]["schema_version"]["const"], sms.SCHEMA_VERSION)
        # 条件表达式只允许受限操作符
        allowed = set(schema["$defs"]["condition"]["properties"]["op"]["enum"])
        self.assertEqual(allowed, {"eq", "in", "all", "any", "not", "count_lte"})

    def test_compiled_options_satisfy_required_shape(self):
        import re

        required = ("schema_version", "option_id", "canonical_family_id", "operation",
                    "node_type", "connection_id", "capability_provider_id",
                    "catalog_model_id", "identity_mapping_status")
        pattern = re.compile(r"^opt_[0-9a-f]{16}$")
        options = sms.compile_options(load_fixture_records())
        self.assertTrue(options)
        for option in options:
            for key in required:
                self.assertIn(key, option, f"选项缺少 {key}")
                self.assertNotEqual(option[key], "", f"{key} 不得为空")
            self.assertRegex(option["option_id"], pattern)
            self.assertIn(option["identity_mapping_status"], {"mapped", "provider_local", "unresolved"})
            self.assertNotIn("provider-local", option["option_id"])

    def test_selection_record_shape_rejects_credentials(self):
        import re

        record = {
            "schema_version": 2,
            "option_id": sms.compute_option_id(
                connection_id="c1", region_id="global", deployment_id="", node_type="video_generation",
                catalog_model_id="m", endpoint_id="e", operation="text_to_video",
            ),
            "connection_id": "c1",
            "region_id": "global",
            "operation": "text_to_video",
            "profile_revision_seen": 3,
            "parameters": {"resolution": "720p", "duration": 5},
            "parameter_origins": {"resolution": "user", "duration": "profile_default"},
            "revision": 7,
        }
        self.assertRegex(record["option_id"], re.compile(r"^opt_[0-9a-f]{16}$"))
        blob = json.dumps(record, ensure_ascii=False).lower()
        for forbidden in ("api_key", "wallet_api_key", "authorization", "bearer"):
            self.assertNotIn(forbidden, blob)


if __name__ == "__main__":
    unittest.main()
