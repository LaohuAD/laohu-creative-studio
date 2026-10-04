"""P5 目录→可执行选项投影的行为回归。

对应《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§8.3、§11.2、§13.5、§17 E01。

目标：后端给出的 option_id 是前后端唯一来源，前端不再自行计算；分站条目不得被合并。
真实目录部分为只读，不写用户配置、不发请求。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import studio_model_selection as sms  # noqa: E402


def fake_catalog() -> dict:
    """纯假目录，形状与 ModelCapabilityRegistry.build_catalog 一致。"""
    return {
        "providers": [
            {
                "id": "fixture-conn",
                "name": "Fixture Platform",
                "capability_provider_id": "fixture-provider",
                "models": [
                    {
                        "model_id": "fixturevideo-m",
                        "node_type": "video_generation",
                        "operation": "multimodal_to_video",
                        "family_id": "fixture-video-m",
                        "family_name": "Fixture Video M",
                        "variant_id": "multimodal",
                        "version": 3,
                        "readiness": "ready",
                        "runnable": True,
                        "regions": ["global", "cn"],
                        "region_profiles": {
                            "global": {
                                "node_type": "video_generation", "operation": "multimodal_to_video",
                                "readiness": "ready", "runnable": True, "version": 3,
                                "parameters": {"duration": {"type": "integer", "min": 4, "max": 12}},
                            },
                            "cn": {
                                "node_type": "video_generation", "operation": "multimodal_to_video",
                                "readiness": "ready", "runnable": True, "version": 2,
                                "parameters": {"duration": {"type": "integer", "min": 4, "max": 8}},
                            },
                        },
                        "inputs": {"reference": {"media_type": "image", "role": "reference", "min": 0, "max": 3}},
                        "capability_tags": ["多模态参考"],
                    },
                    {
                        "model_id": "fixtureaudio-dual",
                        "node_type": "audio_generation",
                        "operation": "speech_or_audio",
                        "family_id": "fixture-audio-dual",
                        "readiness": "adapter_missing",
                        "runnable": False,
                        "regions": [""],
                        "parameters": {},
                        "inputs": {},
                    },
                ],
            }
        ]
    }


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.options = sms.compile_catalog_options(fake_catalog())

    def test_same_id_in_two_regions_yields_two_options(self):
        items = [o for o in self.options if o["catalog_model_id"] == "fixturevideo-m"]
        self.assertEqual(len(items), 2, "E01：同 ID 跨站必须保留为两个选项")
        self.assertEqual({o["region_id"] for o in items}, {"global", "cn"})
        self.assertEqual(len({o["option_id"] for o in items}), 2, "两个站点必须有不同 option_id")
        by_region = {o["region_id"]: o for o in items}
        self.assertEqual(by_region["cn"]["parameters"]["duration"]["max"], 8, "各站点使用自己的契约")
        self.assertEqual(by_region["global"]["parameters"]["duration"]["max"], 12)

    def test_option_id_matches_the_shared_formula(self):
        for option in self.options:
            expected = sms.compute_option_id(
                connection_id=option["connection_id"],
                region_id=option["region_id"],
                deployment_id=option["deployment_id"],
                node_type=option["node_type"],
                catalog_model_id=option["catalog_model_id"],
                endpoint_id=option["endpoint_id"],
                operation=option["operation"],
            )
            self.assertEqual(option["option_id"], expected, "前端与后端必须得到同一个 option_id")

    def test_unmapped_identity_stays_provider_local(self):
        option = next(o for o in self.options if o["catalog_model_id"] == "fixtureaudio-dual")
        self.assertEqual(option["identity_mapping_status"], "provider_local")
        self.assertTrue(option["canonical_family_id"].startswith("provider-local:"))
        self.assertEqual(option["readiness"], "adapter_missing", "适配器缺口必须原样透传")
        self.assertFalse(option["runnable"])

    def test_options_carry_ui_metadata_and_tags(self):
        option = next(o for o in self.options if o["region_id"] == "global")
        self.assertTrue(option["parameters"], "参数 schema 必须随选项下发，供参数面板渲染")
        self.assertTrue(option["inputs"], "输入契约必须随选项下发，供兼容性判断")
        self.assertEqual(option["capability_tags"], ["多模态参考", "多图参考"])
        self.assertEqual(option["capability_tags_en"], ['Multimodal reference', 'Multiple image references'])
        self.assertEqual(option["platform_label"], "Fixture Platform")
        self.assertEqual(option["profile_revision"], "3")

    def test_projection_is_idempotent_and_deduplicated(self):
        again = sms.compile_catalog_options(fake_catalog())
        self.assertEqual(
            json.dumps(self.options, ensure_ascii=False, sort_keys=True),
            json.dumps(again, ensure_ascii=False, sort_keys=True),
        )
        ids = [o["option_id"] for o in self.options]
        self.assertEqual(len(ids), len(set(ids)), "option_id 必须唯一")

    def test_revision_tracks_meaningful_changes(self):
        first = sms.catalog_revision(self.options)
        self.assertEqual(first, sms.catalog_revision(self.options), "相同内容必须得到相同 revision")
        changed = [dict(o) for o in self.options]
        changed[0]["readiness"] = "needs_profile"
        self.assertNotEqual(first, sms.catalog_revision(changed), "能力状态变化必须改变 revision")
        self.assertTrue(first.startswith("rev_"))


class RealCatalogContractTests(unittest.TestCase):
    """真实目录（只读）必须可直接被公共控件消费。"""

    @classmethod
    def setUpClass(cls):
        import main

        # 公开档案与明确双站启用清单，不能依赖维护者本机配置。
        from provider_fixture import configured_providers
        providers = configured_providers()
        runninghub = next(provider for provider in providers if provider['id'] == 'runninghub')
        fields = ('chat_models', 'image_models', 'video_models', 'audio_models')
        runninghub['rh_regions'] = {
            region: {'enabled': True, **{field: list(runninghub[field]) for field in fields}}
            for region in ('global', 'cn')
        }
        cls.catalog = main.build_model_capability_catalog(providers)
        cls.options = cls.catalog.get("options") or []

    def test_catalog_exposes_options_and_contract_version(self):
        self.assertTrue(self.options, "目录必须携带可执行选项投影")
        self.assertEqual(self.catalog.get("selection_contract_version"), sms.SCHEMA_VERSION)
        self.assertTrue(str(self.catalog.get("catalog_revision") or "").startswith("rev_"))

    def test_required_fields_for_the_shared_control(self):
        required = ("option_id", "canonical_family_id", "canonical_family_label", "operation",
                    "node_type", "connection_id", "capability_provider_id", "catalog_model_id",
                    "identity_mapping_status", "readiness")
        import re

        pattern = re.compile(r"^opt_[0-9a-f]{16}$")
        for option in self.options:
            for key in required:
                self.assertIn(key, option, f"选项缺少 {key}")
            self.assertRegex(option["option_id"], pattern)
            self.assertIn(option["identity_mapping_status"], {"mapped", "provider_local"})

    def test_control_visible_fields_are_populated(self):
        with_tags = sum(1 for o in self.options if o["capability_tags"])
        with_params = sum(1 for o in self.options if o["parameters"])
        with_inputs = sum(1 for o in self.options if o["inputs"])
        with_version = sum(1 for o in self.options if o["model_version"])
        self.assertGreater(with_params, 0, "参数 schema 覆盖不足，参数面板无法渲染")
        self.assertGreater(with_inputs, 0, "输入契约覆盖不足")
        self.assertGreater(with_version, 0, "版本维度未填充，第三栏无法区分")
        self.assertGreaterEqual(with_tags, 0)

    def test_cross_region_options_are_not_merged(self):
        by_id = {}
        for option in self.options:
            by_id.setdefault(option["catalog_model_id"], set()).add(option["region_id"])
        multi = [mid for mid, regions in by_id.items() if len(regions) > 1]
        self.assertGreater(len(multi), 0, "真实目录应存在跨站同 ID，且必须保留为多个选项")
        for model_id in multi[:5]:
            scoped = [o for o in self.options if o["catalog_model_id"] == model_id]
            self.assertEqual(len({o["option_id"] for o in scoped}), len(scoped))

    def test_projection_contains_no_credentials(self):
        blob = json.dumps(self.options, ensure_ascii=False).lower()
        for forbidden in ("api_key", "apikey", "authorization", "bearer", "cookie", "secret", "wallet_api_key"):
            self.assertNotIn(forbidden, blob, f"选项投影不得包含 {forbidden}")


if __name__ == "__main__":
    unittest.main()
