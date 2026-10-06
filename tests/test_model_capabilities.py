import asyncio
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main
from provider_fixture import ConfiguredProvidersMixin, configured_providers
from model_capabilities import (
    ModelCapabilityError,
    ModelCapabilityRegistry,
    ai_money_profile_from_model_id,
    dynamic_profile_for_model,
    normalize_model_classification,
    normalize_model_classifications,
    runninghub_profile_from_registry_item,
    save_provider_catalog_snapshot,
    save_runninghub_registry_snapshot,
)
from fastapi.testclient import TestClient
from project_storage import ProjectStorage
from studio_module_models import select_options_for_slot


def run_node(source):
    result = subprocess.run(
        # 大型能力目录超过 Windows 命令行长度限制，通过标准输入传递脚本。
        ["node", "-"],
        input=source,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class ModelCapabilityTests(ConfiguredProvidersMixin, unittest.IsolatedAsyncioTestCase):
    def test_history_write_target_is_isolated_from_project_data(self):
        self.assertNotEqual(
            Path(main.HISTORY_FILE).resolve(),
            (ROOT / "data" / "history.json").resolve(),
        )

    def test_jimeng_queue_payload_hides_invalid_zero_progress(self):
        pending = main.JimengPendingError(
            "submit-zero",
            "video",
            {"queue_idx": 0, "queue_length": 0, "queue_status": "pending"},
        )
        payload = main.jimeng_pending_payload(pending)

        self.assertEqual(payload["queue_info"], {"queue_status": "pending"})
        self.assertNotIn("第 0/0 位", payload["message"])
        self.assertIn("云端处理", payload["message"])

    def test_jimeng_queue_payload_keeps_valid_live_progress(self):
        pending = main.JimengPendingError(
            "submit-live",
            "video",
            {"queue_idx": "4", "queue_length": "11", "queue_status": "pending"},
        )
        payload = main.jimeng_pending_payload(pending)

        self.assertEqual(payload["queue_info"]["queue_idx"], 4)
        self.assertEqual(payload["queue_info"]["queue_length"], 11)
        self.assertIn("第 4/11 位", payload["message"])

    def test_model_capability_preflight_validates_input_content_constraints(self):
        registry = ModelCapabilityRegistry(ROOT)
        profile = {
            "model_id": "fixture-multimodal",
            "validation_mode": "strict",
            "runnable": True,
            "inputs": {
                "prompt": {
                    "media_type": "text", "min": 1, "max": 1, "role": "prompt",
                    "max_chars": 5,
                },
                "reference": {
                    "media_type": "image", "min": 1, "max": 1, "role": "reference",
                    "max_bytes": 10, "min_width": 128, "min_height": 128,
                },
                "source_video": {
                    "media_type": "video", "min": 1, "max": 2, "role": "source_video",
                    "min_duration_seconds": 2, "max_duration_seconds": 6,
                    "max_total_duration_seconds": 8,
                },
            },
            "parameters": {},
        }
        base = {
            "providers": [],
            "provider_id": "fixture",
            "model_id": "fixture-multimodal",
            "node_type": "video_generation",
            "input_counts": {"text": 1, "image": 1, "video": 2},
            "input_roles": {"prompt": 1, "reference": 1, "source_video": 2},
            "parameters": {},
        }
        valid_metadata = {
            "prompt": [{"name": "节点提示词", "characters": 5, "bytes": 5}],
            "reference": [{"name": "参考图 1", "bytes": 10, "width": 128, "height": 128}],
            "source_video": [
                {"name": "视频 1", "duration_seconds": 3},
                {"name": "视频 2", "duration_seconds": 5},
            ],
        }
        with patch.object(registry, "find_model", return_value=profile):
            self.assertIs(
                registry.validate_request(**base, input_metadata=valid_metadata),
                profile,
            )
            cases = [
                ("prompt", [{"name": "节点提示词", "characters": 6, "bytes": 6}], "最多允许 5 个字符"),
                ("reference", [{"name": "参考图 1", "bytes": 11, "width": 128, "height": 128}], "不能超过 10 B"),
                ("reference", [{"name": "参考图 1", "bytes": 10, "width": 127, "height": 128}], "宽度不能小于 128 像素"),
                ("source_video", [{"name": "视频 1", "duration_seconds": 1}, {"name": "视频 2", "duration_seconds": 5}], "时长不能短于 2 秒"),
                ("source_video", [{"name": "视频 1", "duration_seconds": 4}, {"name": "视频 2", "duration_seconds": 5}], "总时长不能超过 8 秒"),
            ]
            for key, value, message in cases:
                metadata = {name: [dict(item) for item in items] for name, items in valid_metadata.items()}
                metadata[key] = value
                with self.subTest(message=message), self.assertRaisesRegex(ModelCapabilityError, message):
                    registry.validate_request(**base, input_metadata=metadata)

    def test_model_capability_preflight_requires_readable_constrained_metadata(self):
        registry = ModelCapabilityRegistry(ROOT)
        profile = {
            "model_id": "fixture-image",
            "validation_mode": "strict",
            "runnable": True,
            "inputs": {
                "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
                "reference": {
                    "media_type": "image", "min": 1, "max": 1, "role": "reference",
                    "max_bytes": 1024,
                },
            },
            "parameters": {},
        }
        with patch.object(registry, "find_model", return_value=profile), self.assertRaisesRegex(
            ModelCapabilityError,
            "无法读取.*文件大小",
        ):
            registry.validate_request(
                [], "fixture", "fixture-image", "image_generation",
                input_counts={"text": 1, "image": 1},
                input_roles={"prompt": 1, "reference": 1},
                parameters={},
                input_metadata={
                    "prompt": [{"name": "节点提示词", "characters": 2, "bytes": 6}],
                    "reference": [{"name": "参考图 1"}],
                },
            )

    def test_runninghub_official_descriptions_become_input_constraints(self):
        profile = runninghub_profile_from_registry_item({
            "name_en": "demo/multimodal-to-video",
            "output_type": "video",
            "params": [
                {
                    "fieldKey": "prompt", "type": "STRING", "required": True,
                    "description": "支持中英文，最长5000个字符。",
                },
                {
                    "fieldKey": "images", "type": "IMAGE", "multipleInputs": True,
                    "maxInputNum": 7,
                    "description": "像素不小于128x128，比例不超过4:1，单张不超过50MB。",
                },
                {
                    "fieldKey": "audio", "type": "AUDIO", "multipleInputs": True,
                    "maxInputNum": 3,
                    "description": "单个音频时长 [2, 15] s，所有音频总时长不超过 15 s。",
                },
            ],
        })

        self.assertEqual(profile["inputs"]["prompt"]["max_chars"], 5000)
        self.assertEqual(profile["inputs"]["reference"]["max"], 7)
        self.assertEqual(profile["inputs"]["reference"]["min_width"], 128)
        self.assertEqual(profile["inputs"]["reference"]["min_height"], 128)
        self.assertEqual(profile["inputs"]["reference"]["max_aspect_ratio"], 4)
        self.assertEqual(profile["inputs"]["reference"]["max_bytes"], 50 * 1024 * 1024)
        self.assertEqual(profile["inputs"]["reference_audio"]["min_duration_seconds"], 2)
        self.assertEqual(profile["inputs"]["reference_audio"]["max_duration_seconds"], 15)
        self.assertEqual(profile["inputs"]["reference_audio"]["max_total_duration_seconds"], 15)

    def test_canvas_input_metadata_reads_local_file_properties_without_network(self):
        profile = {
            "inputs": {
                "prompt": {"media_type": "text", "role": "prompt"},
                "reference": {"media_type": "image", "role": "reference"},
                "source_video": {"media_type": "video", "role": "source_video"},
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            image_path = Path(temporary) / "input.png"
            video_path = Path(temporary) / "clip.mp4"
            main.Image.new("RGB", (320, 180), "white").save(image_path)
            video_path.write_bytes(b"fixture-video")
            with patch.object(main, "output_file_from_url", side_effect=lambda url: str(image_path) if "input.png" in url else str(video_path)), \
                 patch.object(main, "_probe_canvas_media_properties", return_value={"width": 1280, "height": 720, "duration_seconds": 4.5}):
                metadata = main.canvas_input_metadata(
                    profile,
                    {"prompt": "测试", "reference": ["/assets/input.png"], "source_video": ["/assets/clip.mp4"]},
                    {"source_video": [{"name": "演示视频"}]},
                )

        self.assertEqual(metadata["prompt"][0]["characters"], 2)
        self.assertEqual(metadata["prompt"][0]["name"], "节点提示词")
        self.assertEqual(metadata["reference"][0]["width"], 320)
        self.assertEqual(metadata["reference"][0]["height"], 180)
        self.assertGreater(metadata["reference"][0]["bytes"], 0)
        self.assertEqual(metadata["source_video"][0]["duration_seconds"], 4.5)

    def test_ai_money_official_input_limits_are_kept_in_profiles(self):
        blend = ai_money_profile_from_model_id("midjourney-blend", "image_generation")
        nano_flash = ai_money_profile_from_model_id("laohuaimoney-image-nb-flash", "image_generation")
        video_gk = ai_money_profile_from_model_id("laohuaimoney-video-gk-v15", "video_generation")
        video_omni = ai_money_profile_from_model_id("laohuaimoney-video-g-omni-flash", "video_generation")

        self.assertEqual(blend["inputs"]["reference"]["max_bytes"], 12 * 1024 * 1024)
        self.assertEqual(nano_flash["inputs"]["prompt"]["max_chars"], 1000)
        self.assertEqual(nano_flash["inputs"]["reference"]["max"], 14)
        self.assertEqual(video_gk["inputs"]["reference"]["max"], 7)
        self.assertEqual(video_omni["inputs"]["reference"]["max"], 16)
        self.assertEqual(video_omni["inputs"]["source_video"]["max"], 1)

    def test_ai_money_text_variants_share_a_family_without_changing_model_ids(self):
        provider = next(item for item in main.load_api_providers() if item.get("id") == "ai-money")
        catalog = main.MODEL_CAPABILITY_REGISTRY.build_catalog([provider])
        runtime_provider = catalog["providers"][0]
        variants = [
            item for item in runtime_provider["families"]
            if item.get("family_id") == "ai-money-bytedance-doubao-seed-2-0"
        ][0]["variants"]

        self.assertEqual(
            {item["model_id"] for item in variants},
            {
                "bytedance/doubao-seed-2.0-code",
                "bytedance/doubao-seed-2.0-lite",
                "bytedance/doubao-seed-2.0-mini",
                "bytedance/doubao-seed-2.0-pro",
            },
        )
        self.assertEqual(
            {item["variant_id"] for item in variants},
            {"code", "lite", "mini", "pro"},
        )

    def test_canvas_preflight_rejects_local_media_before_runtime_submission(self):
        profile = {
            "provider_id": "fixture",
            "model_id": "fixture-image",
            "family_id": "fixture-family",
            "variant_id": "image_to_image",
            "node_type": "image_generation",
            "operation": "image_to_image",
            "validation_mode": "strict",
            "runnable": True,
            "inputs": {
                "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
                "reference": {
                    "media_type": "image", "min": 1, "max": 1, "role": "reference",
                    "max_width": 32,
                },
            },
            "parameters": {},
            "request_mapping": {"prompt": "prompt", "reference": "image"},
        }
        payload = main.CanvasPreflightRequest(
            provider_id="fixture",
            model_id="fixture-image",
            node_type="image_generation",
            inputs={"prompt": "测试", "reference": ["/assets/input.png"]},
            input_counts={"text": 1, "image": 1},
            input_roles={"prompt": 1, "reference": 1},
        )
        with tempfile.TemporaryDirectory() as temporary:
            image_path = Path(temporary) / "input.png"
            main.Image.new("RGB", (64, 64), "white").save(image_path)
            with patch.object(main, "resolve_model_capability_request", return_value=profile), \
                 patch.object(main, "output_file_from_url", return_value=str(image_path)), \
                 self.assertRaisesRegex(main.HTTPException, "宽度不能大于 32 像素"):
                asyncio.run(main.canvas_preflight(payload))

    def test_runninghub_official_schema_builds_video_capability_profile(self):
        profile = runninghub_profile_from_registry_item({
            "name_en": "sora-2/image-to-video-realistic-official-stable",
            "name_cn": "全能视频S-图生视频",
            "endpoint": "rhart-video-s-official/image-to-video-realistic",
            "output_type": "video",
            "params": [
                {"fieldKey": "prompt", "type": "STRING", "required": True},
                {
                    "fieldKey": "duration", "type": "LIST", "required": True,
                    "options": [{"value": "4"}, {"value": "8"}], "defaultValue": "4",
                },
                {
                    "fieldKey": "imageUrl", "type": "IMAGE", "required": True,
                    "maxInputNum": 1,
                },
            ],
        })

        self.assertEqual(profile["node_type"], "video_generation")
        self.assertEqual(profile["operation"], "image_to_video")
        self.assertEqual(profile["inputs"]["prompt"]["media_type"], "text")
        self.assertEqual(profile["inputs"]["first_frame"], {
            "media_type": "image", "min": 1, "max": 1, "role": "first_frame",
            "label": "imageUrl", "source_field": "imageUrl",
        })
        self.assertEqual(profile["parameters"]["duration"]["options"], ["4", "8"])
        self.assertEqual(profile["parameters"]["duration"]["default"], "4")
        self.assertEqual(profile["request_mapping"]["first_frame"], "imageUrl")
        self.assertEqual(profile["readiness"], "ready")

    def test_runninghub_schema_normalizes_common_parameter_names_but_keeps_upstream_mapping(self):
        profile = runninghub_profile_from_registry_item({
            "name_en": "demo/text-to-video",
            "endpoint": "demo/text-to-video",
            "output_type": "video",
            "params": [
                {"fieldKey": "prompt", "type": "STRING", "required": True},
                {"fieldKey": "aspectRatio", "type": "LIST", "options": [{"value": "16:9"}]},
                {"fieldKey": "generateAudio", "type": "BOOLEAN", "defaultValue": False},
            ],
        })

        self.assertIn("aspect_ratio", profile["parameters"])
        self.assertIn("generate_audio", profile["parameters"])
        self.assertEqual(profile["request_mapping"]["aspect_ratio"], "aspectRatio")
        self.assertEqual(profile["request_mapping"]["generate_audio"], "generateAudio")

    def test_runninghub_minimax_audio_functions_share_one_model_family(self):
        fixtures = [
            ("minimax/speech-02-hd", "minimax/speech-02-hd", "Speech 02 · 高清"),
            ("minimax/speech-2.8-turbo", "minimax/speech-2.8-turbo", "Speech 2.8 · 极速 · Turbo 版"),
            ("minimax/voice-clone", "minimax/voice-clone", "声音克隆"),
            ("minimax/voice-design", "minimax/voice-design", "音色设计"),
        ]
        profiles = []
        for model_id, endpoint, expected_mode_name in fixtures:
            params = [{"fieldKey": "text", "type": "STRING", "required": True}]
            if model_id.endswith("voice-clone"):
                params.append({"fieldKey": "audio", "type": "AUDIO", "required": True})
            profile = runninghub_profile_from_registry_item({
                "name_en": model_id,
                "name_cn": model_id,
                "endpoint": endpoint,
                "output_type": "audio",
                "params": params,
            })
            profiles.append(profile)
            self.assertEqual(profile["family_name"], "MiniMax")
            self.assertEqual(profile["family_name_en"], "MiniMax")
            self.assertEqual(profile["variant_name"], expected_mode_name)
            self.assertTrue(profile["variant_name_en"])

        self.assertEqual({profile["family_id"] for profile in profiles}, {"runninghub-minimax"})
        self.assertEqual(len({profile["variant_id"] for profile in profiles}), len(profiles))
        self.assertEqual(profiles[2]["operation"], "voice_clone")
        self.assertEqual(profiles[3]["operation"], "voice_design")

    def test_runninghub_obvious_product_functions_are_grouped_as_run_modes(self):
        fixtures = [
            ("pixverse-v6/text-to-video", "video", "runninghub-pixverse-v6"),
            ("pixverse-v6/effects", "video", "runninghub-pixverse-v6"),
            ("topazlabs-video-upscale", "video", "runninghub-topazlabs-video"),
            ("topazlabs-video-denoise", "video", "runninghub-topazlabs-video"),
            ("suno-single-v5.5", "audio", "runninghub-suno"),
            ("suno-custom-v5", "audio", "runninghub-suno"),
        ]
        profiles = []
        for model_id, output_type, expected_family in fixtures:
            profile = runninghub_profile_from_registry_item({
                "name_en": model_id,
                "name_cn": model_id,
                "endpoint": model_id,
                "output_type": output_type,
                "params": [{"fieldKey": "prompt", "type": "STRING", "required": True}],
            })
            profiles.append(profile)
            self.assertEqual(profile["family_id"], expected_family)
            self.assertTrue(profile["variant_name"])
        self.assertEqual(profiles[0]["family_id"], profiles[1]["family_id"])
        self.assertEqual(profiles[2]["family_id"], profiles[3]["family_id"])
        self.assertEqual(profiles[4]["family_id"], profiles[5]["family_id"])
        self.assertEqual(profiles[0]["operation"], "text_to_video")
        self.assertEqual(profiles[1]["operation"], "video_effects")
        self.assertEqual(profiles[2]["operation"], "video_enhancement")

    def test_runninghub_versioned_products_keep_functions_in_one_model_family(self):
        fixtures = [
            ("hailuo-2.3-t2v-standard", "runninghub-hailuo-2.3"),
            ("hailuo-2.3/i2v-pro", "runninghub-hailuo-2.3"),
            ("Vidu-text-to-video-q3-pro", "runninghub-vidu-q3"),
            ("Vidu-image-to-video-q3-turbo", "runninghub-vidu-q3"),
            ("kling-v3.0-std-text-to-video", "runninghub-kling-3.0"),
            ("kling-v3.0-pro-image-to-video", "runninghub-kling-3.0"),
            ("kling-v3-4k-text-to-video", "runninghub-kling-3.0"),
            ("Seedance2.0 Fast Text to Video", "runninghub-seedance-2.0"),
            ("seedance-2.0-mini/image-to-video", "runninghub-seedance-2.0"),
            ("google/veo3.1-fast/text-to-video-official-stable", "runninghub-google-veo3.1"),
            ("google/veo3.1-pro/image-to-video-official-stable", "runninghub-google-veo3.1"),
            ("wan-2.7-reference-to-video", "runninghub-wan"),
            ("wan-2.7/video-edit", "runninghub-wan"),
        ]
        for model_id, expected_family in fixtures:
            profile = runninghub_profile_from_registry_item({
                "name_en": model_id,
                "name_cn": model_id,
                "endpoint": model_id,
                "output_type": "video",
                "params": [{"fieldKey": "prompt", "type": "STRING", "required": True}],
            })
            self.assertEqual(profile["family_id"], expected_family, model_id)

    def test_runninghub_separator_modes_use_neutral_family_names(self):
        fixtures = [
            ("grok-3-image-text-to-image", "全能图片X-3-文生图", "image", "runninghub-grok-3-image", "全能图片X-3", "文生图"),
            ("grok-3-image-to-image", "全能图片X-3-图生图", "image", "runninghub-grok-3-image", "全能图片X-3", "图生图"),
            ("MiniMax-H3 Text-to-Video", "MiniMax-H3 文生视频", "video", "runninghub-minimax-h3", "MiniMax H3", "文生视频"),
            ("MiniMax-H3 Image-to-Video (first/last frame)", "MiniMax-H3 图生视频（首尾帧）", "video", "runninghub-minimax-h3", "MiniMax H3", "图生视频（首尾帧）"),
            ("xai / grok-imagine-video-v1.5 / text-to-video-official-stable", "全能视频X-文生视频-官方稳定版-v1.5", "video", "runninghub-xai-grok-imagine-video-v1.5", "全能视频X", "文生视频-官方稳定版-v1.5"),
            ("xai/grok-imagine-video-v1.5/image-to-video-official-stable", "全能视频X-图生视频-官方稳定版-v1.5", "video", "runninghub-xai-grok-imagine-video-v1.5", "全能视频X", "图生视频-官方稳定版-v1.5"),
        ]
        profiles = []
        for model_id, display_name, output_type, family_id, family_name, variant_name in fixtures:
            profile = runninghub_profile_from_registry_item({
                "name_en": model_id,
                "name_cn": display_name,
                "endpoint": model_id,
                "output_type": output_type,
                "params": [{"fieldKey": "prompt", "type": "STRING", "required": True}],
            })
            profiles.append(profile)
            self.assertEqual(profile["family_id"], family_id, model_id)
            self.assertEqual(profile["family_name"], family_name, model_id)
            self.assertEqual(profile["variant_name"], variant_name, model_id)
            self.assertEqual(profile["model_id"], model_id)

        self.assertEqual(profiles[0]["family_id"], profiles[1]["family_id"])
        self.assertEqual(profiles[2]["family_id"], profiles[3]["family_id"])
        self.assertEqual(profiles[4]["family_id"], profiles[5]["family_id"])

    def test_jimeng_seedance_variants_have_one_family_after_legacy_profile_cleanup(self):
        provider = next(item for item in main.load_api_providers() if item.get("id") == "jimeng")
        catalog = main.MODEL_CAPABILITY_REGISTRY.build_catalog([provider])
        runtime_provider = catalog["providers"][0]
        families = [
            family for family in runtime_provider["families"]
            if family.get("node_type") == "video_generation" and family.get("display_name") == "Seedance 2.0"
        ]
        self.assertEqual(len(families), 1)
        self.assertEqual(
            {variant["model_id"] for variant in families[0]["variants"]},
            {"seedance2.0fast_vip", "seedance2.0_vip", "seedance2.0", "seedance2.0fast", "seedance2.0mini"},
        )

    def test_ai_money_minimax_audio_functions_share_one_model_family(self):
        speech = ai_money_profile_from_model_id("minimax-speech-2.8-hd", "audio_generation")
        clone = ai_money_profile_from_model_id("minimax-voice-clone", "audio_generation")

        self.assertEqual(speech["family_id"], "ai-money-minimax")
        self.assertEqual(clone["family_id"], speech["family_id"])
        self.assertEqual(speech["family_name"], "MiniMax")
        self.assertEqual(speech["variant_name"], "Speech 2.8 · 高清")
        self.assertEqual(clone["variant_name"], "声音克隆")

    def test_ai_money_seedance_variants_share_family_and_route_inputs(self):
        text_profile = ai_money_profile_from_model_id("seedance-2.0-fast-t2v", "video_generation")
        image_profile = ai_money_profile_from_model_id("seedance-2.0-fast-i2v", "video_generation")
        multi_profile = ai_money_profile_from_model_id("seedance-2.0-fast-multi", "video_generation")

        self.assertEqual(text_profile["family_id"], "ai-money-seedance-2-0")
        self.assertEqual(image_profile["family_id"], text_profile["family_id"])
        self.assertEqual(multi_profile["family_id"], text_profile["family_id"])
        self.assertEqual(text_profile["operation"], "text_to_video")
        self.assertEqual(image_profile["operation"], "image_to_video")
        self.assertEqual(multi_profile["operation"], "multimodal_to_video")
        self.assertNotIn("first_frame", text_profile["inputs"])
        self.assertEqual(image_profile["inputs"]["first_frame"]["min"], 1)
        self.assertEqual(multi_profile["inputs"]["reference"]["max"], 10)
        self.assertEqual(multi_profile["inputs"]["source_video"]["max"], 5)
        self.assertEqual(multi_profile["inputs"]["reference_audio"]["max"], 5)
        self.assertEqual(
            set(multi_profile["parameters"]),
            {"duration", "resolution", "aspect_ratio", "generate_audio", "return_last_frame", "seed"},
        )
        self.assertEqual(multi_profile["request_mapping"]["reference"], "metadata.content")
        self.assertEqual(multi_profile["readiness"], "ready")

    def test_video_display_mode_comes_from_declared_inputs_not_model_name(self):
        base = {
            "family_id": "fixture-seedance-2-0-fast",
            "family_name": "Seedance 2.0 Fast",
            "family_name_en": "Seedance 2.0 Fast",
            "node_type": "video_generation",
            "operation": "compatible_video",
            "status": "confirmed",
            "readiness": "ready",
            "runnable": True,
        }
        text = normalize_model_classification({
            **base,
            "model_id": "misleading-space-name",
            "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
        }, "fixture-provider")
        image = normalize_model_classification({
            **base,
            "model_id": "misleading-text-to-video-name",
            "inputs": {
                "prompt": {"media_type": "text", "min": 1, "max": 1},
                "reference": {"media_type": "image", "min": 0, "max": 4},
            },
        }, "fixture-provider")
        multimodal = normalize_model_classification({
            **base,
            "model_id": "misleading-image-to-video-name",
            "inputs": {
                "prompt": {"media_type": "text", "min": 1, "max": 1},
                "reference": {"media_type": "image", "min": 0, "max": 4},
                "source_video": {"media_type": "video", "min": 0, "max": 1},
                "reference_audio": {"media_type": "audio", "min": 0, "max": 1},
            },
        }, "fixture-provider")

        self.assertEqual(text["variant_name"], "文生视频")
        self.assertEqual(image["variant_name"], "图生视频")
        self.assertEqual(multimodal["variant_name"], "多模态视频")
        self.assertEqual(text["family_id"], "fixture-seedance-2-0-fast")
        self.assertEqual(text["family_name"], "Seedance 2.0 Fast")

        optional_last_frame = normalize_model_classification({
            **base,
            "model_id": "first-frame-with-optional-last-frame",
            "inputs": {
                "prompt": {"media_type": "text", "min": 1, "max": 1},
                "first_frame": {"media_type": "image", "min": 1, "max": 1},
                "last_frame": {"media_type": "image", "min": 0, "max": 1},
            },
        }, "fixture-provider")
        self.assertEqual(optional_last_frame["variant_name"], "图生视频")

    def test_image_channel_variant_hides_redundant_operation_label(self):
        profile = normalize_model_classification({
            "model_id": "laohuaimoney-image-g-v2-lowprice",
            "family_id": "ai-money-image-g-v2-lowprice",
            "family_name": "AI MONEY Image G V2",
            "node_type": "image_generation",
            "operation": "text_to_image",
        }, "ai-money")

        self.assertEqual(profile["variant_name"], "低价渠道版")
        self.assertEqual(profile["variant_name_en"], "Low-price Channel")

    def test_repeated_video_modes_keep_family_and_append_tier_to_variant(self):
        profiles = [dynamic_profile_for_model("jimeng-cli", model_id, "video_generation") for model_id in (
            "seedance2.0",
            "seedance2.0fast",
            "seedance2.0mini",
        )]
        normalized = normalize_model_classifications(profiles, "jimeng-cli")

        self.assertEqual({item["family_id"] for item in normalized}, {"jimeng-seedance-2.0"})
        self.assertEqual({item["family_name"] for item in normalized}, {"Seedance 2.0"})
        self.assertEqual(
            [item["variant_name"] for item in normalized],
            ["多模态视频", "快速版 · 多模态视频", "精简版 · 多模态视频"],
        )

    def test_repeated_minimax_modes_use_id_meaning_instead_of_sequence_numbers(self):
        profiles = [ai_money_profile_from_model_id(model_id, "video_generation") for model_id in (
            "minimax-h3-ow-r2v", "minimax-h3-ow-r2v-fast",
        )]
        normalized = normalize_model_classifications(profiles, "ai-money")
        self.assertEqual([item["variant_name"] for item in normalized], [
            "H3 · 标准版 · 图生视频", "H3 · 快速版 · 图生视频",
        ])
        self.assertEqual([item["variant_name_en"] for item in normalized], [
            "H3 · Standard · Image to Video", "H3 · Fast · Image to Video",
        ])

    def test_ai_money_standard_chat_catalog_model_gets_text_capability(self):
        profile = ai_money_profile_from_model_id("glm-5.2", "text_generation")

        self.assertEqual(profile["node_type"], "text_generation")
        self.assertEqual(profile["operation"], "chat")
        self.assertEqual(profile["inputs"]["prompt"]["media_type"], "text")
        self.assertEqual(profile["request_mapping"]["prompt"], "messages")
        self.assertTrue(profile["runnable"])

    def test_ai_money_special_action_models_use_dedicated_contracts(self):
        midjourney = ai_money_profile_from_model_id("midjourney-upscale", "image_generation")
        self.assertEqual(midjourney["operation"], "midjourney_upscale")
        self.assertEqual(midjourney["platform"]["endpoint"], "/v1/midjourney/generations/upscale")
        with self.assertRaises(main.ModelCapabilityError):
            ai_money_profile_from_model_id("minmax-h3-context-ir-image", "image_generation")

    def test_ai_money_official_non_seedance_families_have_explicit_canvas_contracts(self):
        layer = ai_money_profile_from_model_id("seedream-v5-pro-layer-decomposition", "image_generation")
        reference_video = ai_money_profile_from_model_id("happyhorse-1.1-r2v", "video_generation")
        hailuo = ai_money_profile_from_model_id("hailuo-2.3-i2v-pro", "video_generation")
        minimax_fast = ai_money_profile_from_model_id("minimax-h3-ow-r2v-fast", "video_generation")
        upscaler = ai_money_profile_from_model_id("laohuaimoney-upscaler", "video_generation")
        music = ai_money_profile_from_model_id("mureka-v9-bgm", "music_generation")

        self.assertEqual(layer["operation"], "layer_decomposition")
        self.assertEqual(layer["inputs"]["reference"]["min"], 1)
        self.assertEqual(reference_video["inputs"]["reference"]["max"], 9)
        self.assertEqual(hailuo["operation"], "image_to_video")
        self.assertEqual(minimax_fast["operation"], "reference_to_video")
        self.assertEqual(upscaler["inputs"]["source_video"]["min"], 1)
        self.assertEqual(music["operation"], "music")
        self.assertEqual(music["node_type"], "music_generation")
        self.assertTrue(all(item["readiness"] == "ready" for item in (layer, reference_video, upscaler, music)))

    def test_ai_money_action_and_analysis_models_have_explicit_canvas_contracts(self):
        midjourney = ai_money_profile_from_model_id("midjourney-upscale", "image_generation")
        suno = ai_money_profile_from_model_id("suno-extend", "music_generation")
        whisper = ai_money_profile_from_model_id("whisper-1", "text_generation")
        context = ai_money_profile_from_model_id("minmax-h3-context-ir-multimodal", "text_generation")

        self.assertEqual(midjourney["platform"]["endpoint"], "/v1/midjourney/generations/upscale")
        self.assertIn("upstream_task_id", midjourney["parameters"])
        self.assertEqual(suno["platform"]["endpoint"], "/v1/music/generations/extend")
        self.assertIn("upstream_task_id", suno["parameters"])
        self.assertEqual(whisper["operation"], "transcription")
        self.assertEqual(whisper["inputs"]["reference_audio"]["min"], 1)
        self.assertEqual(context["operation"], "prompt_enhancement")
        self.assertEqual(context["inputs"]["reference_audio"]["max"], 3)

    def test_ai_money_new_image_and_flowmusic_models_have_official_contracts(self):
        image = ai_money_profile_from_model_id("laohuaimoney-image-gk-v2-edit", "image_generation")
        flow_generation = ai_money_profile_from_model_id("flowmusic-generation", "music_generation")
        flow_lyrics = ai_money_profile_from_model_id("flowmusic-lyrics", "music_generation")
        flow_video = ai_money_profile_from_model_id("flowmusic-video-clip", "music_generation")

        self.assertEqual(image["inputs"]["reference"]["max"], 3)
        self.assertEqual(image["parameters"]["resolution"]["options"], ["1k", "2k"])
        self.assertEqual(image["request_mapping"]["aspect_ratio"], "aspect_ratio")
        self.assertEqual(flow_generation["platform"]["endpoint"], "/v1/music/generations")
        self.assertEqual(flow_generation["request_mapping"]["prompt"], "sound_prompt")
        self.assertEqual(flow_generation["parameters"]["version"]["default"], "lyria-3.5")
        self.assertEqual(flow_lyrics["output"]["media_type"], "text")
        self.assertEqual(flow_video["output"]["media_type"], "video")

    def test_required_action_parameters_are_rejected_before_network_request(self):
        provider = {
            "id": "ai-money", "name": "AI MONEY", "protocol": "openai", "enabled": True,
            "image_models": ["midjourney-pan"], "chat_models": [], "video_models": [], "audio_models": [],
        }

        with self.assertRaises(main.HTTPException) as context:
            main.validate_model_capability_request(
                "ai-money",
                "midjourney-pan",
                "image_generation",
                input_counts={"text": 0, "image": 0},
                parameters={},
                providers=[provider],
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("缺少必填参数", str(context.exception.detail))
        self.assertIn("upstream_task_id", str(context.exception.detail))
        self.assertIn("direction", str(context.exception.detail))

    def test_modelscope_configured_models_have_runtime_contracts(self):
        text = dynamic_profile_for_model("modelscope", "Qwen/Qwen3-235B-A22B", "text_generation")
        vision = dynamic_profile_for_model("modelscope", "Qwen/Qwen3-VL-235B-A22B-Instruct", "text_generation")
        image = dynamic_profile_for_model("modelscope", "Tongyi-MAI/Z-Image-Turbo", "image_generation")
        edit = dynamic_profile_for_model("modelscope", "Qwen/Qwen-Image-Edit-2511", "image_generation")

        self.assertEqual(text["operation"], "chat")
        self.assertEqual(vision["inputs"]["reference"]["media_type"], "image")
        self.assertEqual(image["operation"], "text_to_image")
        self.assertEqual(edit["operation"], "image_to_image")
        self.assertTrue(all(profile["readiness"] == "ready" for profile in (text, vision, image, edit)))

    def test_modelscope_canvas_uses_enabled_model_catalog_and_shared_task_route(self):
        script = (ROOT / "static" / "js" / "smart-canvas.js").read_text(encoding="utf-8")
        function_start = script.index("async function runModelscopeGeneration")
        function_end = script.index("async function urlToBase64", function_start)
        function_source = script[function_start:function_end]

        self.assertIn("const models = modelscopeImageModels()", function_source)
        self.assertIn("resolveCapabilityForRun('modelscope', 'image_generation'", function_source)
        self.assertIn("fetch('/api/canvas-image-tasks'", function_source)
        self.assertNotIn("MS_GEN_MODELS", function_source)
        self.assertIn("rhModelMode || settings.engine === 'modelscope'", script)
        self.assertIn("return modelscopeProvider()?.image_models || []", script)
        self.assertIn("const compatibleModels = profiles.map(item => item.model_id)", script)

    async def test_canvas_modelscope_text_uses_enabled_chat_model_without_external_network(self):
        provider = {
            "id": "modelscope", "name": "ModelScope", "protocol": "openai", "enabled": True,
            "image_models": [], "chat_models": ["Qwen/Qwen3-235B-A22B"], "video_models": [], "audio_models": [],
        }
        submitted = {}

        class Response:
            content = b'{"choices":[{"message":{"content":"ModelScope mock"}}]}'

            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "ModelScope mock"}}]}

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, url, headers=None, json=None):
                submitted.update({"url": url, "headers": headers, "json": json})
                return Response()

        payload = main.CanvasLLMRequest(
            message="测试 ModelScope 文本路由",
            provider="modelscope",
            model="Qwen/Qwen3-235B-A22B",
        )
        with patch.object(main, "get_api_provider", return_value=provider), \
             patch.object(main, "resolve_chat_provider", return_value=(
                 "https://api-inference.modelscope.cn/v1",
                 {"Authorization": "Bearer test"},
                 "Qwen/Qwen3-235B-A22B",
             )), patch("main.httpx.AsyncClient", return_value=Client()):
            result = await main.canvas_llm(payload)

        self.assertEqual(result["text"], "ModelScope mock")
        self.assertEqual(submitted["url"], "https://api-inference.modelscope.cn/v1/chat/completions")
        self.assertEqual(submitted["json"]["model"], "Qwen/Qwen3-235B-A22B")
        self.assertEqual(submitted["json"]["messages"][-1], {"role": "user", "content": "测试 ModelScope 文本路由"})

    def test_jimeng_catalog_models_have_version_specific_contracts(self):
        legacy_image = dynamic_profile_for_model("jimeng-cli", "3.0", "image_generation")
        edit_image = dynamic_profile_for_model("jimeng-cli", "4.7", "image_generation")
        pro_image = dynamic_profile_for_model("jimeng-cli", "5.0Pro", "image_generation")
        standard_video = dynamic_profile_for_model("jimeng-cli", "seedance2.0fast", "video_generation")
        vip_video = dynamic_profile_for_model("jimeng-cli", "seedance2.0_vip", "video_generation")
        seedance_25 = dynamic_profile_for_model("jimeng-cli", "seedance2.5", "video_generation")

        self.assertNotIn("reference", legacy_image["inputs"])
        self.assertEqual(edit_image["inputs"]["reference"]["max"], 10)
        self.assertEqual(legacy_image["parameters"]["resolution"]["options"], ["1k", "2k"])
        self.assertEqual(edit_image["parameters"]["resolution"]["options"], ["2k", "4k"])
        self.assertEqual(pro_image["parameters"]["resolution"]["options"], ["1.5k", "2k", "4k"])
        self.assertEqual(standard_video["parameters"]["resolution"]["options"], ["720p"])
        self.assertEqual(vip_video["parameters"]["resolution"]["options"], ["720p", "1080p", "4k"])
        self.assertEqual(vip_video["inputs"]["reference_audio"]["max"], 3)
        self.assertEqual(standard_video["inputs"]["prompt"]["max_chars"], 4000)
        self.assertEqual(seedance_25["family_name"], "Seedance 2.5")
        self.assertEqual(seedance_25["inputs"]["prompt"]["max_chars"], 15000)
        self.assertEqual(seedance_25["inputs"]["reference"]["max"], 30)
        self.assertEqual(seedance_25["inputs"]["source_video"]["max"], 10)
        self.assertEqual(seedance_25["inputs"]["reference_audio"]["max"], 10)
        self.assertEqual(seedance_25["parameters"]["duration"]["max"], 30)
        self.assertEqual(seedance_25["parameters"]["resolution"]["options"], ["480p", "720p"])
        self.assertEqual(
            seedance_25["platform"]["prompt_modes"],
            {
                "text_to_video": 15000,
                "image_to_video": 15000,
                "frames_to_video": 15000,
                "multimodal_to_video": 15000,
                "video_edit": 15000,
            },
        )

    def test_canvas_video_request_allows_seedance_25_prompt_ceiling(self):
        prompt = "字" * 15000

        payload = main.CanvasVideoRequest(
            provider_id="jimeng",
            model="seedance2.5",
            prompt=prompt,
        )

        self.assertEqual(len(payload.prompt), 15000)

    async def test_canvas_jimeng_image_routes_through_cli_adapter_without_network(self):
        provider = {
            "id": "jimeng", "name": "即梦 CLI", "protocol": "jimeng", "enabled": True,
            "image_models": ["5.0Pro"], "chat_models": [], "video_models": [], "audio_models": [],
        }
        payload = main.OnlineImageRequest(
            prompt="测试即梦图片路由",
            provider_id="jimeng",
            model="5.0Pro",
        )

        real_history_file = ROOT / "data" / "history.json"
        real_history_existed_before = real_history_file.exists()
        real_history_hash_before = (
            hashlib.sha256(real_history_file.read_bytes()).hexdigest()
            if real_history_existed_before else None
        )
        with tempfile.TemporaryDirectory(
            prefix="model-capability-image-storage-",
            dir=ROOT / "cache" / "studio-tests",
        ) as isolated_root:
            storage = ProjectStorage(isolated_root)
            storage.ensure_layout()
            with patch.object(main, "PROJECT_STORAGE", storage), \
                 patch.object(main, "ASSETS_DIR", str(storage.assets_dir)), \
                 patch.object(main, "MATERIALS_DIR", str(storage.materials_dir)), \
                 patch.object(main, "OUTPUT_INPUT_DIR", str(storage.materials_dir / "imports")), \
                 patch.object(main, "OUTPUT_OUTPUT_DIR", str(storage.results_dir)), \
                 patch.object(main, "RESULTS_DIR", str(storage.results_dir)), \
                 patch.object(main, "OUTPUT_DIR", str(Path(isolated_root) / "output")), \
                 patch.object(main, "get_api_provider", return_value=provider), \
                 patch.object(main, "generate_jimeng_provider_image", new=AsyncMock(return_value=(
                     {"type": "url", "value": "/api/results/jimeng-image.png"},
                     {"images": ["/api/results/jimeng-image.png"]},
                 ))) as generate_mock, \
                 patch.object(main, "save_ai_image_to_output", new=AsyncMock(return_value="/api/results/jimeng-image.png")):
                result = await main.build_online_image_result(payload)

        saved_history = json.loads(self.history_file.read_text(encoding="utf-8"))
        self.assertEqual(len(saved_history), 1)
        self.assertEqual(saved_history[0]["prompt"], payload.prompt)
        self.assertEqual(saved_history[0]["images"], ["/api/results/jimeng-image.png"])
        self.assertEqual(real_history_file.exists(), real_history_existed_before)
        real_history_hash_after = (
            hashlib.sha256(real_history_file.read_bytes()).hexdigest()
            if real_history_file.exists() else None
        )
        self.assertEqual(real_history_hash_after, real_history_hash_before)

        self.assertEqual(result["images"], ["/api/results/jimeng-image.png"])
        self.assertEqual(generate_mock.await_args.args[2], "5.0Pro")

    async def test_jimeng_image_cli_preserves_capability_parameters_without_network(self):
        with patch.object(main, "run_jimeng_cli", new=AsyncMock(return_value={"images": ["/tmp/mock.png"]})) as cli_mock, \
             patch.object(main, "jimeng_store_outputs", new=AsyncMock(return_value=["/api/results/mock-image.png"])):
            result, _ = await main.generate_jimeng_provider_image(
                "测试即梦图片参数",
                "1024x1024",
                "5.0Pro",
                [],
                {"id": "jimeng"},
                {"ratio": "3:4", "resolution_type": "2k"},
            )

        args = cli_mock.await_args.args[0]
        self.assertEqual(args[0], "text2image")
        self.assertIn("--ratio=3:4", args)
        self.assertIn("--resolution_type=2k", args)
        self.assertEqual(result["value"], "/api/results/mock-image.png")

    async def test_jimeng_pro_1_5k_reaches_cli_for_generation_and_editing(self):
        for refs in ([], [{"url":"/api/materials/reference"}]):
            for field in ("resolution", "resolution_type"):
                with self.subTest(mode="image2image" if refs else "text2image", field=field), \
                     patch.object(main, "run_jimeng_cli", new=AsyncMock(return_value={"images": []})) as cli, \
                     patch.object(main, "jimeng_prepare_local_media", new=AsyncMock(return_value=(str(ROOT / "cache/reference.png"), []))), \
                     patch.object(main, "jimeng_store_outputs", new=AsyncMock(return_value=["/api/results/mock"])):
                    await main.generate_jimeng_provider_image("验收", "1024x1024", "5.0Pro", refs, {"id":"jimeng"}, {field:"1.5K", "ratio":"3:4"})
                    args = cli.await_args.args[0]
                    self.assertEqual(args[0], "image2image" if refs else "text2image")
                    self.assertIn("--resolution_type=1.5k", args)
                    self.assertIn("--model_version=5.0Pro", args)
                    self.assertIn("--ratio=3:4", args)
        catalog = ModelCapabilityRegistry(ROOT).build_catalog([{
            "id":"jimeng", "name":"即梦 CLI", "protocol":"jimeng", "enabled":True,
            "image_models":["5.0Pro"], "chat_models":[], "video_models":[], "audio_models":[],
        }])
        profile = catalog["providers"][0]["models"][0]
        self.assertEqual(profile["parameters"]["resolution"]["options"], ["1.5k", "2k", "4k"])

    async def test_jimeng_pro_rejects_stale_1k_and_uses_common_default(self):
        with patch.object(main, "run_jimeng_cli", new=AsyncMock()) as cli:
            with self.assertRaises(main.HTTPException):
                await main.generate_jimeng_provider_image("验收", "1024x1024", "5.0Pro", [], {"id":"jimeng"}, {"resolution_type":"1k"})
            cli.assert_not_awaited()
        self.assertEqual(main.jimeng_image_resolution("5.0Pro", "1024x1024"), "2k")
        self.assertEqual(main.jimeng_image_resolution_options("5.0Pro"), ["1.5k", "2k", "4k"])

    async def test_jimeng_image_cli_rejects_resolution_not_supported_by_model(self):
        with self.assertRaises(main.HTTPException) as context:
            await main.generate_jimeng_provider_image(
                "测试即梦图片参数",
                "1024x1024",
                "4.7",
                [],
                {"id": "jimeng"},
                {"resolution_type": "1k"},
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("2K、4K", context.exception.detail)

    def test_jimeng_image_resolution_options_follow_each_model_contract(self):
        self.assertEqual(main.jimeng_image_resolution_options("3.0"), ["1k", "2k"])
        self.assertEqual(main.jimeng_image_resolution_options("4.7"), ["2k", "4k"])
        self.assertEqual(main.jimeng_image_resolution_options("5.0Pro"), ["1.5k", "2k", "4k"])
        self.assertEqual(main.jimeng_image_resolution_options("4.7", "image2image"), ["2k", "4k"])
        self.assertIn("1.5k", main.jimeng_image_resolution_options("5.0Pro", "image2image"))

    async def test_canvas_jimeng_video_routes_through_cli_adapter_without_network(self):
        provider = {
            "id": "jimeng", "name": "即梦 CLI", "protocol": "jimeng", "enabled": True,
            "image_models": [], "chat_models": [], "video_models": ["seedance2.0"], "audio_models": [],
        }
        payload = main.CanvasVideoRequest(
            prompt="测试即梦视频路由",
            provider_id="jimeng",
            model="seedance2.0",
        )

        with patch.object(main, "get_api_provider", return_value=provider), \
             patch.object(main, "generate_jimeng_video", new=AsyncMock(return_value={
                 "videos": ["/api/results/jimeng-video.mp4"],
                 "task_id": "jimeng-task",
             })) as generate_mock:
            result = await main.canvas_video(payload)

        self.assertEqual(result["task_id"], "jimeng-task")
        self.assertEqual(generate_mock.await_args.args[0].model, "seedance2.0")
        self.assertEqual(generate_mock.await_args.args[2], {})

    async def test_canvas_jimeng_video_validates_prompt_limit_by_selected_model(self):
        provider = {
            "id": "jimeng", "name": "即梦 CLI", "protocol": "jimeng", "enabled": True,
            "image_models": [], "chat_models": [],
            "video_models": ["seedance2.0", "seedance2.5"], "audio_models": [],
        }
        generate = AsyncMock(return_value={"videos": ["/api/results/mock-video.mp4"]})

        with patch.object(main, "get_api_provider", return_value=provider), \
             patch.object(main, "load_api_providers", return_value=[provider]), \
             patch.object(main, "generate_jimeng_video", generate):
            accepted = await main.canvas_video(main.CanvasVideoRequest(
                provider_id="jimeng",
                model="seedance2.5",
                prompt="字" * 15000,
            ))
            with self.assertRaises(main.HTTPException) as context:
                await main.canvas_video(main.CanvasVideoRequest(
                    provider_id="jimeng",
                    model="seedance2.0",
                    prompt="字" * 4001,
                ))

        self.assertEqual(accepted["videos"], ["/api/results/mock-video.mp4"])
        self.assertEqual(generate.await_count, 1)
        self.assertIn("最多允许 4000 个字符", str(context.exception.detail))

    async def test_canvas_jimeng_multimodal_video_preserves_selected_parameters_without_network(self):
        provider = {
            "id": "jimeng", "name": "即梦 CLI", "protocol": "jimeng", "enabled": True,
            "image_models": [], "chat_models": [], "video_models": ["seedance2.0mini"], "audio_models": [],
        }
        payload = main.CanvasVideoRequest(
            prompt="测试即梦视频参数",
            provider_id="jimeng",
            model="seedance2.0mini",
            images=[main.AIReference(url="/api/results/reference-image", role="reference")],
            multimodal=True,
            parameters={"duration": 4, "aspect_ratio": "3:4", "resolution": "720p"},
        )

        with patch.object(main, "get_api_provider", return_value=provider), \
             patch.object(main, "load_api_providers", return_value=[provider]), \
             patch.object(main, "jimeng_prepare_local_media", new=AsyncMock(return_value=("/tmp/reference.png", []))), \
             patch.object(main, "run_jimeng_cli", new=AsyncMock(return_value={"submit_id": "mock-task"})) as cli_mock, \
             patch.object(main, "jimeng_store_outputs", new=AsyncMock(return_value=["/api/results/mock-video.mp4"])):
            result = await main.canvas_video(payload)

        args = cli_mock.await_args.args[0]
        self.assertEqual(args[0], "multimodal2video")
        self.assertIn("--model_version=seedance2.0mini", args)
        self.assertIn("--duration=4", args)
        self.assertIn("--ratio=3:4", args)
        self.assertIn("--video_resolution=720p", args)
        self.assertEqual(result["videos"], ["/api/results/mock-video.mp4"])

    async def test_canvas_jimeng_ratio_mismatch_promotes_single_image_to_multimodal_without_network(self):
        provider = {
            "id": "jimeng", "name": "即梦 CLI", "protocol": "jimeng", "enabled": True,
            "image_models": [], "chat_models": [], "video_models": ["seedance2.0mini"], "audio_models": [],
        }
        payload = main.CanvasVideoRequest(
            prompt="把方图生成竖版视频",
            provider_id="jimeng",
            model="seedance2.0mini",
            images=[main.AIReference(url="/api/results/reference-image", role="reference", width=1024, height=1024)],
            parameters={"duration": 4, "aspect_ratio": "3:4", "resolution": "720p"},
        )

        with patch.object(main, "get_api_provider", return_value=provider), \
             patch.object(main, "load_api_providers", return_value=[provider]), \
             patch.object(main, "jimeng_prepare_local_media", new=AsyncMock(return_value=("/tmp/reference.png", []))), \
             patch.object(main, "run_jimeng_cli", new=AsyncMock(return_value={"submit_id": "mock-task"})) as cli_mock, \
             patch.object(main, "jimeng_store_outputs", new=AsyncMock(return_value=["/api/results/mock-video.mp4"])):
            await main.canvas_video(payload)

        args = cli_mock.await_args.args[0]
        self.assertEqual(args[0], "multimodal2video")
        self.assertIn("--ratio=3:4", args)

    async def test_canvas_jimeng_matching_ratio_keeps_single_image_mode_without_network(self):
        provider = {
            "id": "jimeng", "name": "即梦 CLI", "protocol": "jimeng", "enabled": True,
            "image_models": [], "chat_models": [], "video_models": ["seedance2.0mini"], "audio_models": [],
        }
        payload = main.CanvasVideoRequest(
            prompt="让方图动起来",
            provider_id="jimeng",
            model="seedance2.0mini",
            images=[main.AIReference(url="/api/results/reference-image", role="reference", width=1024, height=1024)],
            parameters={"duration": 4, "aspect_ratio": "1:1", "resolution": "720p"},
        )

        with patch.object(main, "get_api_provider", return_value=provider), \
             patch.object(main, "load_api_providers", return_value=[provider]), \
             patch.object(main, "jimeng_prepare_local_media", new=AsyncMock(return_value=("/tmp/reference.png", []))), \
             patch.object(main, "run_jimeng_cli", new=AsyncMock(return_value={"submit_id": "mock-task"})) as cli_mock, \
             patch.object(main, "jimeng_store_outputs", new=AsyncMock(return_value=["/api/results/mock-video.mp4"])):
            await main.canvas_video(payload)

        args = cli_mock.await_args.args[0]
        self.assertEqual(args[0], "image2video")
        self.assertNotIn("--ratio=1:1", args)

    async def test_canvas_jimeng_two_images_use_explicit_first_last_frame_order_without_network(self):
        provider = {
            "id": "jimeng", "name": "即梦 CLI", "protocol": "jimeng", "enabled": True,
            "image_models": [], "chat_models": [], "video_models": ["seedance2.0mini"], "audio_models": [],
        }
        payload = main.CanvasVideoRequest(
            prompt="从首帧过渡到尾帧",
            provider_id="jimeng",
            model="seedance2.0mini",
            images=[
                main.AIReference(url="/api/results/first-image", role="first_frame", width=1024, height=1024),
                main.AIReference(url="/api/results/last-image", role="last_frame", width=1024, height=1024),
            ],
            input_roles={"prompt": 1, "first_frame": 1, "last_frame": 1},
            parameters={"duration": 4, "resolution": "720p"},
        )

        async def local_media(url, _kind):
            return ({
                "/api/results/first-image": "/tmp/first.png",
                "/api/results/last-image": "/tmp/last.png",
            }[url], [])

        with patch.object(main, "get_api_provider", return_value=provider), \
             patch.object(main, "load_api_providers", return_value=[provider]), \
             patch.object(main, "jimeng_prepare_local_media", new=AsyncMock(side_effect=local_media)), \
             patch.object(main, "run_jimeng_cli", new=AsyncMock(return_value={"submit_id": "mock-task"})) as cli_mock, \
             patch.object(main, "jimeng_store_outputs", new=AsyncMock(return_value=["/api/results/mock-video.mp4"])):
            await main.canvas_video(payload)

        args = cli_mock.await_args.args[0]
        self.assertEqual(args[0], "frames2video")
        self.assertIn("--first=/tmp/first.png", args)
        self.assertIn("--last=/tmp/last.png", args)

    async def test_canvas_codex_text_routes_through_cli_adapter_without_network(self):
        provider = {
            "id": "codex", "name": "GPT CLI", "protocol": "codex", "enabled": True,
            "image_models": [], "chat_models": ["gpt-5.5"], "video_models": [], "audio_models": [],
        }
        payload = main.CanvasLLMRequest(
            message="根据参考图给出文字说明",
            provider="codex",
            model="gpt-5.5",
            images=["/assets/input/reference.png"],
            parameters={"model": "gpt-5.5"},
        )

        with patch.object(main, "get_api_provider", return_value=provider), \
             patch.object(main, "codex_chat_text", new=AsyncMock(return_value=("测试文本结果", {"source": "mock"}))) as chat_mock:
            result = await main.canvas_llm(payload)

        self.assertEqual(result["text"], "测试文本结果")
        self.assertEqual(result["model"], "gpt-5.5")
        self.assertEqual(chat_mock.await_args.args[0].images, ["/assets/input/reference.png"])

    async def test_codex_reads_result_and_material_api_urls_as_local_media(self):
        def local_path(url):
            return {
                "/api/results/result-1": "/tmp/result-1.png",
                "/api/materials/material-1": "/tmp/material-1.png",
            }.get(url)

        with patch.object(main, "output_file_from_url", side_effect=local_path):
            result_path, result_cleanup = await main.codex_prepare_local_media("/api/results/result-1")
            material_path, material_cleanup = await main.codex_prepare_local_media("/api/materials/material-1")

        self.assertEqual(result_path, "/tmp/result-1.png")
        self.assertEqual(material_path, "/tmp/material-1.png")
        self.assertEqual(result_cleanup, [])
        self.assertEqual(material_cleanup, [])

    async def test_jimeng_reads_result_and_material_api_urls_as_local_media(self):
        def local_path(url):
            return {
                "/api/results/result-1": "/tmp/result-1.png",
                "/api/materials/material-1": "/tmp/material-1.png",
            }.get(url)

        with patch.object(main, "output_file_from_url", side_effect=local_path):
            result_path, result_cleanup = await main.jimeng_prepare_local_media("/api/results/result-1")
            material_path, material_cleanup = await main.jimeng_prepare_local_media("/api/materials/material-1")

        self.assertEqual(result_path, "/tmp/result-1.png")
        self.assertEqual(material_path, "/tmp/material-1.png")
        self.assertEqual(result_cleanup, [])
        self.assertEqual(material_cleanup, [])

    async def test_jimeng_converts_cli_absolute_output_to_project_media_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "output-1.mp4"
            path.write_bytes(b"video")
            with patch.object(main, "jimeng_local_output_url", return_value="/api/results/video-1") as store:
                result = await main.jimeng_store_output_value(str(path), "video")
            self.assertEqual(result, "/api/results/video-1")
            store.assert_called_once_with(str(path), "video")

    async def test_jimeng_store_outputs_queries_submitted_task_without_network(self):
        query = AsyncMock(return_value={"videos": ["/api/results/video-1.mp4"]})
        with patch.object(main, "jimeng_query_result", new=query), \
             patch.object(main, "jimeng_store_output_value", new=AsyncMock(return_value="/api/results/video-1.mp4")):
            result = await main.jimeng_store_outputs({"submit_id": "jimeng-task"}, "video")
        self.assertEqual(result, ["/api/results/video-1.mp4"])
        query.assert_awaited_once_with("jimeng-task", "video")

    def test_canvas_migrates_existing_absolute_output_media_reference(self):
        with tempfile.NamedTemporaryFile(dir=main.OUTPUT_OUTPUT_DIR, suffix=".mp4", delete=False) as handle:
            path = Path(handle.name)
        try:
            canvas = {"nodes": [{"images": [{"url": str(path)}]}]}
            with patch.object(main, "output_url_for", return_value="/api/results/legacy-video") as output_url:
                changed = main.migrate_canvas_media_references(canvas)
            self.assertTrue(changed)
            self.assertEqual(canvas["nodes"][0]["images"][0]["url"], "/api/results/legacy-video")
            output_url.assert_called_once()
        finally:
            path.unlink(missing_ok=True)

    def test_unified_local_media_resolver_handles_logical_file_and_absolute_refs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "reference.png"
            path.write_bytes(base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ))

            self.assertEqual(main.local_media_reference_path(str(path)), str(path))
            self.assertEqual(main.local_media_reference_path(path.as_uri()), str(path))
            self.assertTrue(main.is_local_media_reference(path.as_uri()))

            with patch.object(main, "output_file_from_url", return_value=str(path)) as resolver:
                self.assertEqual(
                    main.local_media_reference_path("/api/results/result-1"),
                    str(path),
                )
                self.assertEqual(
                    main.media_reference_to_url("/api/results/result-1"),
                    "data:image/png;base64," + "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                )
                self.assertTrue(
                    main.modelscope_image_url("/api/materials/material-1").startswith(
                        "data:image/jpeg;base64,"
                    )
                )
                resolver.assert_called()

    def test_local_cloud_upload_resolver_accepts_result_api_url_without_network(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "reference.png"
            path.write_bytes(base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ))
            with patch.object(main, "output_file_from_url", return_value=str(path)):
                resolved = main.local_media_path_for_cloud_upload(
                    "/api/results/result-1",
                    allowed_prefixes=("image/",),
                )
            self.assertEqual(resolved, str(path))

    def test_official_non_volcengine_catalogs_have_expected_coverage(self):
        providers = configured_providers()
        registry = ModelCapabilityRegistry(ROOT)
        expected = {
            "modelscope": (7, 7),
            "jimeng": (15, 15),
        }

        for provider_id, counts in expected.items():
            provider = next(item for item in providers if item.get("id") == provider_id)
            report = registry.audit_catalog_coverage(
                provider_id,
                {field: provider.get(field, []) for field in ("chat_models", "image_models", "video_models", "audio_models")},
                provider.get("rh_region", "global"),
            )
            self.assertEqual((report["total"], report["ready"]), counts, provider_id)

        runninghub_raw = json.loads(
            (ROOT / "data" / "model_capabilities" / "snapshots" / "runninghub-official-public.json").read_text(encoding="utf-8")
        )
        runninghub_catalog = {
            "chat_models": [], "image_models": [], "video_models": [], "audio_models": [],
        }
        output_fields = {"image": "image_models", "video": "video_models", "audio": "audio_models"}
        for item in runninghub_raw.get("models") or []:
            field = output_fields.get(item.get("output_type"))
            model_id = item.get("name_en") or item.get("endpoint")
            if field and model_id:
                runninghub_catalog[field].append(model_id)
        runninghub_report = registry.audit_catalog_coverage("runninghub", runninghub_catalog, "cn")
        runninghub_total = sum(len(values) for values in runninghub_catalog.values())
        self.assertEqual(runninghub_report["total"], runninghub_total)
        self.assertGreaterEqual(runninghub_report["ready"], runninghub_total - 4)

        codex = next(item for item in providers if item.get("id") == "codex")
        codex_report = registry.audit_catalog_coverage(
            "codex",
            {field: codex.get(field, []) for field in ("chat_models", "image_models", "video_models", "audio_models")},
            codex.get("rh_region", "global"),
        )
        self.assertEqual(codex_report["total"], len(codex.get("chat_models") or []))
        self.assertEqual(codex_report["ready"], codex_report["total"])

    def test_runtime_catalog_generates_profiles_for_enabled_official_models(self):
        providers = [{
            "id": "ai-money", "name": "AI MONEY", "protocol": "openai", "enabled": True,
            "image_models": [], "chat_models": [],
            "video_models": [
                "seedance-2.0-fast-t2v",
                "seedance-2.0-fast-i2v",
                "seedance-2.0-fast-multi",
            ],
            "audio_models": [],
        }]

        catalog = main.build_model_capability_catalog(providers)
        provider = catalog["providers"][0]
        self.assertEqual(len(provider["models"]), 3)
        self.assertTrue(all(model["runnable"] for model in provider["models"]))
        family = next(item for item in provider["families"] if item["family_id"] == "ai-money-seedance-2-0")
        self.assertEqual(
            [variant["variant_id"] for variant in family["variants"]],
            ["text_to_video", "image_to_video", "multimodal_to_video"],
        )

    def test_api_settings_model_list_is_the_only_runtime_enablement_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capability_root = root / "data" / "model_capabilities"
            (capability_root / "providers").mkdir(parents=True)
            (capability_root / "registry.json").write_text(json.dumps({
                "schema_version": 1,
                "providers": [{"provider_id": "ai-money", "file": "data/model_capabilities/providers/ai-money.json"}],
            }), encoding="utf-8")
            (capability_root / "providers" / "ai-money.json").write_text(json.dumps({
                "provider_id": "ai-money",
                "models": [{
                    "model_id": "kimi-k3",
                    "node_type": "text_generation",
                    "operation": "chat",
                    "status": "confirmed",
                    "readiness": "ready",
                    "enabled_in_api_settings": False,
                    "evidence_level": "official_documented",
                    "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
                    "parameters": {},
                    "request_mapping": {"prompt": "messages"},
                }],
            }), encoding="utf-8")
            catalog = ModelCapabilityRegistry(root).build_catalog([{
                "id": "ai-money", "name": "AI MONEY", "protocol": "openai", "enabled": True,
                "chat_models": ["kimi-k3"], "image_models": [], "video_models": [], "audio_models": [],
            }])

        self.assertEqual([item["model_id"] for item in catalog["providers"][0]["models"]], ["kimi-k3"])
        self.assertTrue(catalog["providers"][0]["models"][0]["runnable"])

    def test_runtime_catalog_hides_profiles_not_enabled_in_api_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capability_root = root / "data" / "model_capabilities"
            (capability_root / "providers").mkdir(parents=True)
            (capability_root / "registry.json").write_text(json.dumps({
                "schema_version": 1,
                "providers": [{"provider_id": "ai-money", "file": "data/model_capabilities/providers/ai-money.json"}],
            }), encoding="utf-8")
            (capability_root / "providers" / "ai-money.json").write_text(json.dumps({
                "provider_id": "ai-money",
                "models": [{
                    "model_id": model_id,
                    "node_type": "text_generation",
                    "operation": "chat",
                    "status": "confirmed",
                    "readiness": "ready",
                    "evidence_level": "official_documented",
                    "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
                    "parameters": {},
                    "request_mapping": {"prompt": "messages"},
                } for model_id in ("model-a", "model-b", "model-c", "model-d")],
            }), encoding="utf-8")
            registry = ModelCapabilityRegistry(root)
            catalog = registry.build_catalog([{
                "id": "ai-money", "name": "AI MONEY", "protocol": "openai", "enabled": True,
                "chat_models": ["model-a", "model-b"], "image_models": [], "video_models": [], "audio_models": [],
            }])

        self.assertEqual(
            [item["model_id"] for item in catalog["providers"][0]["models"]],
            ["model-a", "model-b"],
        )

    def test_runtime_catalog_splits_audio_and_music_while_preserving_configured_order(self):
        catalog = ModelCapabilityRegistry(ROOT).build_catalog([{
            "id": "ai-money", "name": "AI MONEY", "protocol": "openai", "enabled": True,
            "chat_models": [], "image_models": [], "video_models": [],
            "audio_models": [
                "mureka-v9-bgm",
                "qwen3-tts-flash",
                "minimax-music-2.6",
                "minimax-speech-2.8-hd",
            ],
        }])
        models = catalog["providers"][0]["models"]

        self.assertEqual(
            [item["model_id"] for item in models if item["node_type"] == "audio_generation"],
            ["qwen3-tts-flash", "minimax-speech-2.8-hd"],
        )
        self.assertEqual(
            [item["model_id"] for item in models if item["node_type"] == "music_generation"],
            ["mureka-v9-bgm", "minimax-music-2.6"],
        )

    def test_full_catalog_coverage_is_audited_independently_from_user_enablement(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capability_root = root / "data" / "model_capabilities"
            (capability_root / "providers").mkdir(parents=True)
            (capability_root / "registry.json").write_text(json.dumps({
                "schema_version": 1,
                "providers": [{"provider_id": "demo", "file": "data/model_capabilities/providers/demo.json"}],
            }), encoding="utf-8")
            (capability_root / "providers" / "demo.json").write_text(json.dumps({
                "provider_id": "demo",
                "models": [{
                    "model_id": "model-a",
                    "node_type": "text_generation",
                    "operation": "chat",
                    "status": "confirmed",
                    "readiness": "ready",
                    "evidence_level": "official_documented",
                    "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
                    "parameters": {},
                    "request_mapping": {"prompt": "messages"},
                }, {
                    "model_id": "model-c",
                    "node_type": "image_generation",
                    "operation": "text_to_image",
                    "status": "confirmed",
                    "readiness": "adapter_missing",
                    "evidence_level": "official_documented",
                    "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
                    "parameters": {},
                    "request_mapping": {"prompt": "prompt"},
                }],
            }), encoding="utf-8")
            registry = ModelCapabilityRegistry(root)
            coverage = registry.audit_catalog_coverage("demo", {
                "chat_models": ["model-a", "model-b"],
                "image_models": ["model-c", "model-d"],
            })

        self.assertEqual(coverage["total"], 4)
        self.assertEqual(coverage["ready"], 1)
        self.assertEqual(coverage["adapter_missing"], 1)
        self.assertEqual(coverage["needs_profile"], 2)
        self.assertEqual(coverage["missing_model_ids"], ["model-b", "model-d"])
        self.assertEqual(coverage["adapter_missing_model_ids"], ["model-c"])

    def test_provider_catalog_snapshot_keeps_full_catalog_separate_from_user_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = save_provider_catalog_snapshot(root, "ai-money", {
                "chat_models": ["model-a", "model-b"],
                "image_models": ["model-c"],
                "video_models": ["model-d"],
                "audio_models": [],
                "raw": {"secret": "must-not-be-saved"},
            }, source="/v1/models")
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["provider_id"], "ai-money")
        self.assertEqual(payload["source"], "/v1/models")
        self.assertEqual(payload["chat_models"], ["model-a", "model-b"])
        self.assertEqual(payload["video_models"], ["model-d"])
        self.assertNotIn("raw", payload)
        self.assertNotIn("secret", json.dumps(payload))

    def test_runninghub_optional_audio_input_does_not_force_audio_to_audio(self):
        optional = runninghub_profile_from_registry_item({
            "name_en": "demo/text-to-speech",
            "endpoint": "demo/text-to-speech",
            "output_type": "audio",
            "params": [
                {"fieldKey": "text", "type": "STRING", "required": True},
                {"fieldKey": "audioUrl", "type": "AUDIO", "required": False},
            ],
        })
        required = runninghub_profile_from_registry_item({
            "name_en": "demo/audio-to-audio",
            "endpoint": "demo/audio-to-audio",
            "output_type": "audio",
            "params": [
                {"fieldKey": "text", "type": "STRING", "required": False},
                {"fieldKey": "audioUrl", "type": "AUDIO", "required": True},
            ],
        })

        self.assertEqual(optional["operation"], "text_to_audio")
        self.assertEqual(required["operation"], "audio_to_audio")

    def test_runtime_catalog_loads_runninghub_profiles_from_active_region_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capability_root = root / "data" / "model_capabilities"
            (capability_root / "providers").mkdir(parents=True)
            (capability_root / "snapshots").mkdir(parents=True)
            (capability_root / "registry.json").write_text(json.dumps({
                "schema_version": 1,
                "providers": [{"provider_id": "runninghub", "file": "data/model_capabilities/providers/runninghub.json"}],
            }), encoding="utf-8")
            (capability_root / "providers" / "runninghub.json").write_text(json.dumps({
                "provider_id": "runninghub", "models": [],
            }), encoding="utf-8")
            (capability_root / "snapshots" / "runninghub-global.json").write_text(json.dumps({
                "schema_version": 1,
                "region": "global",
                "items": [{
                    "name_en": "sora-2/text-to-video-official-stable",
                    "name_cn": "全能视频S-文生视频",
                    "endpoint": "rhart-video-s-official/text-to-video",
                    "output_type": "video",
                    "params": [{"fieldKey": "prompt", "type": "STRING", "required": True}],
                }],
            }), encoding="utf-8")
            registry = ModelCapabilityRegistry(root)
            catalog = registry.build_catalog([{
                "id": "runninghub", "name": "RunningHub", "protocol": "runninghub", "enabled": True,
                "rh_region": "global", "image_models": [], "chat_models": [],
                "video_models": ["sora-2/text-to-video-official-stable"], "audio_models": [],
            }])

        model = catalog["providers"][0]["models"][0]
        self.assertEqual(model["operation"], "text_to_video")
        self.assertEqual(model["platform"]["endpoint"], "rhart-video-s-official/text-to-video")
        self.assertTrue(model["runnable"])

    def test_malformed_runninghub_region_snapshot_preserves_official_profiles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshots = root / "data" / "model_capabilities" / "snapshots"
            snapshots.mkdir(parents=True)
            (snapshots / "runninghub-official-public.json").write_text(json.dumps({
                "models": [{
                    "name_en": "gpt-image-2.5/flare/text-to-image/economy",
                    "endpoint": "gpt-image-2.5/flare/text-to-image/economy",
                    "output_type": "image",
                    "params": [{"fieldKey": "prompt", "type": "STRING", "required": True}],
                }],
            }), encoding="utf-8")
            (snapshots / "runninghub-cn.json").write_text(json.dumps({"items": {"bad": "shape"}}), encoding="utf-8")

            profiles = ModelCapabilityRegistry(root).runninghub_snapshot_profiles("cn")

        model_id = "gpt-image-2.5/flare/text-to-image/economy"
        self.assertIn(model_id, profiles)
        self.assertEqual(profiles[model_id]["node_type"], "image_generation")
        self.assertTrue(profiles[model_id]["runnable"])

    def test_runninghub_legacy_seedance_ids_reuse_current_official_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capability_root = root / "data" / "model_capabilities"
            (capability_root / "providers").mkdir(parents=True)
            (capability_root / "snapshots").mkdir(parents=True)
            (capability_root / "registry.json").write_text(json.dumps({
                "schema_version": 1,
                "providers": [{"provider_id": "runninghub", "file": "data/model_capabilities/providers/runninghub.json"}],
            }), encoding="utf-8")
            (capability_root / "providers" / "runninghub.json").write_text(json.dumps({
                "provider_id": "runninghub", "models": [],
            }), encoding="utf-8")
            (capability_root / "snapshots" / "runninghub-global.json").write_text(json.dumps({
                "schema_version": 1,
                "region": "global",
                "items": [{
                    "name_en": "Seedance2.0 Text to Video",
                    "name_cn": "Seedance2.0/文生视频",
                    "endpoint": "rhart-video/sparkvideo-2.0/text-to-video",
                    "output_type": "video",
                    "params": [
                        {"fieldKey": "prompt", "type": "STRING", "required": True},
                        {"fieldKey": "duration", "type": "LIST", "required": True, "options": [{"value": "5"}]},
                    ],
                }],
            }), encoding="utf-8")
            registry = ModelCapabilityRegistry(root)
            catalog = registry.build_catalog([{
                "id": "runninghub", "name": "RunningHub", "protocol": "runninghub", "enabled": True,
                "rh_region": "global", "image_models": [], "chat_models": [],
                "video_models": ["seedance-2.0-global/text-to-video"], "audio_models": [],
            }])

        model = catalog["providers"][0]["models"][0]
        self.assertEqual(model["model_id"], "seedance-2.0-global/text-to-video")
        self.assertEqual(model["platform"]["endpoint"], "rhart-video/sparkvideo-2.0/text-to-video")
        self.assertEqual(model["parameters"]["duration"]["options"], ["5"])
        self.assertTrue(model["runnable"])

    def test_runninghub_chat_registry_item_uses_documented_openai_parameters(self):
        profile = runninghub_profile_from_registry_item({
            "name_en": "glm-5.2",
            "endpoint": "glm-5.2",
            "output_type": "chat",
        })

        self.assertEqual(profile["node_type"], "text_generation")
        self.assertEqual(profile["operation"], "chat")
        self.assertEqual(profile["inputs"]["prompt"]["media_type"], "text")
        self.assertEqual(profile["parameters"]["temperature"]["type"], "number")
        self.assertEqual(profile["request_mapping"]["max_output_tokens"], "max_tokens")
        self.assertTrue(profile["runnable"])

    def test_runninghub_enabled_chat_model_without_registry_params_uses_documented_llm_contract(self):
        providers = [{
            "id": "runninghub", "name": "RunningHub", "protocol": "runninghub", "enabled": True,
            "rh_region": "global", "image_models": [], "chat_models": ["openai/gpt-5.1"],
            "video_models": [], "audio_models": [],
        }]
        catalog = main.build_model_capability_catalog(providers)
        model = catalog["providers"][0]["models"][0]

        self.assertEqual(model["node_type"], "text_generation")
        self.assertEqual(model["operation"], "chat")
        self.assertIn("temperature", model["parameters"])
        self.assertTrue(model["runnable"])

    def test_ai_money_catalog_classifies_task_suffixes_before_generic_chat(self):
        grouped, _ = main.parse_upstream_models({"data": [
            {"id": "happyhorse-1.1-i2v"},
            {"id": "vidu-q3-pro-fast-t2v"},
            {"id": "wan-2.7-spicy-i2v"},
            {"id": "qwen-image-3.0-global-t2i"},
            {"id": "glm-5.2"},
        ]}, "openai")

        self.assertIn("happyhorse-1.1-i2v", grouped["video"])
        self.assertIn("vidu-q3-pro-fast-t2v", grouped["video"])
        self.assertIn("wan-2.7-spicy-i2v", grouped["video"])
        self.assertIn("qwen-image-3.0-global-t2i", grouped["image"])
        self.assertEqual(grouped["chat"], ["glm-5.2"])

    def test_runninghub_snapshot_writer_keeps_schema_without_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = save_runninghub_registry_snapshot(
                Path(temp_dir),
                "cn",
                [{
                    "name_en": "demo/text-to-image",
                    "endpoint": "demo/text-to-image",
                    "output_type": "image",
                    "params": [{"fieldKey": "prompt", "type": "STRING"}],
                    "apiKey": "must-not-be-saved",
                }],
                source="official-registry",
            )
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(saved["region"], "cn")
        self.assertEqual(saved["source"], "official-registry")
        self.assertEqual(saved["items"][0]["name_en"], "demo/text-to-image")
        self.assertNotIn("apiKey", saved["items"][0])

    def test_platform_parameter_mapping_uses_profile_request_paths(self):
        profile = runninghub_profile_from_registry_item({
            "name_en": "demo/text-to-video",
            "endpoint": "demo/text-to-video",
            "output_type": "video",
            "params": [
                {"fieldKey": "prompt", "type": "STRING", "required": True},
                {"fieldKey": "aspectRatio", "type": "LIST", "options": [{"value": "16:9"}]},
                {"fieldKey": "negativePrompt", "type": "STRING"},
            ],
        })
        profile.update({"provider_id": "runninghub", "validation_mode": "strict", "runnable": True})

        mapped = main.MODEL_CAPABILITY_REGISTRY.platform_parameters(profile, {
            "aspect_ratio": "16:9",
            "negativePrompt": "模糊",
        })

        self.assertEqual(mapped, {"aspectRatio": "16:9", "negativePrompt": "模糊"})

    def test_ai_money_song_profiles_map_lyrics_and_mark_lip_sync_workflow_gap(self):
        providers = [{
            "id": "ai-money", "enabled": True, "protocol": "openai",
            "chat_models": [], "image_models": [], "video_models": [],
            "audio_models": ["mureka-o2-song", "mureka-v9-song", "kling-lip-sync-tts"],
        }]
        o2 = main.MODEL_CAPABILITY_REGISTRY.find_model(providers, "ai-money", "mureka-o2-song", "music_generation")
        v9 = main.MODEL_CAPABILITY_REGISTRY.find_model(providers, "ai-money", "mureka-v9-song", "music_generation")
        lip_sync = main.MODEL_CAPABILITY_REGISTRY.find_model(providers, "ai-money", "kling-lip-sync-tts", "audio_generation")

        self.assertEqual(o2["readiness"], "ready")
        self.assertEqual(o2["request_mapping"]["prompt"], "metadata.lyrics")
        self.assertIn("melody_id", v9["parameters"])
        self.assertEqual(lip_sync["readiness"], "adapter_missing")
        self.assertFalse(lip_sync["runnable"])

    def test_ai_money_dynamic_image_and_video_profiles_map_every_visible_parameter(self):
        providers = [next(item for item in main.load_api_providers() if item.get("id") == "ai-money")]
        catalog = main.build_model_capability_catalog(providers)
        missing = []
        for profile in catalog["providers"][0]["models"]:
            if not profile.get("runnable"):
                continue
            mapping = profile.get("request_mapping") or {}
            for key, spec in (profile.get("parameters") or {}).items():
                if spec.get("ui_hidden") is not True and key not in mapping:
                    missing.append((profile.get("model_id"), profile.get("node_type"), key))

        self.assertEqual(missing, [])

        video = main.MODEL_CAPABILITY_REGISTRY.find_model(
            providers, "ai-money", "seedance-2.5-standard-t2v", "video_generation"
        )
        image = main.MODEL_CAPABILITY_REGISTRY.find_model(
            providers, "ai-money", "qwen-image-3.0-t2i", "image_generation"
        )
        self.assertEqual(main.MODEL_CAPABILITY_REGISTRY.platform_parameters(video, {
            "duration": 4, "aspect_ratio": "3:4", "resolution": "720p",
        }), {
            "seconds": 4,
            "metadata": {"ratio": "3:4", "resolution": "720p"},
        })
        self.assertEqual(main.MODEL_CAPABILITY_REGISTRY.platform_parameters(image, {
            "aspect_ratio": "3:4", "resolution": "2k",
        }), {
            "metadata": {"ratio": "3:4", "resolution": "2k"},
        })

    def test_canvas_video_capability_parameters_include_generic_values(self):
        payload = main.CanvasVideoRequest(
            prompt="测试",
            parameters={"seed": 123, "return_last_frame": True, "negativePrompt": "模糊"},
        )

        self.assertEqual(main.canvas_video_capability_parameters(payload), {
            "seed": 123,
            "return_last_frame": True,
            "negativePrompt": "模糊",
        })

    async def test_runninghub_audio_uses_schema_endpoint_and_parameters_without_real_network(self):
        payload = main.CanvasAudioRequest(
            prompt="你好",
            provider_id="runninghub",
            model="minimax/speech-2.8-hd",
            parameters={"voice_id": "Wise_Woman", "speed": 1.2},
        )
        provider = {"id": "runninghub", "base_url": "https://www.runninghub.ai", "rh_region": "global"}
        submitted = {}

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"taskId": "task-audio"}

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, url, headers=None, json=None, **_kwargs):
                submitted.update({"url": url, "headers": headers, "json": json})
                return Response()

        model_def = {
            "endpoint": "rhart-audio/text-to-audio/speech-2.8-hd",
            "params": [
                {"fieldKey": "text", "type": "STRING", "required": True},
                {"fieldKey": "voice_id", "type": "STRING", "required": True},
                {"fieldKey": "speed", "type": "FLOAT"},
            ],
        }
        completed = {"data": {"status": "SUCCESS", "outputs": ["https://cdn.example.com/result.mp3"]}}
        with patch.object(main, "runninghub_model_definition", new=AsyncMock(return_value=model_def)), \
             patch.object(main, "runninghub_json_headers", return_value={"Authorization": "Bearer test"}), \
             patch.object(main, "wait_for_runninghub_openapi_task", new=AsyncMock(return_value=completed)), \
             patch.object(main, "save_remote_audio_to_output", new=AsyncMock(return_value="/api/results/audio-result")), \
             patch("main.httpx.AsyncClient", return_value=Client()):
            result = await main.generate_runninghub_audio(
                payload,
                provider,
                {"voice_id": "Wise_Woman", "speed": 1.2},
            )

        self.assertTrue(submitted["url"].endswith("/openapi/v2/rhart-audio/text-to-audio/speech-2.8-hd"))
        self.assertEqual(submitted["json"], {"text": "你好", "voice_id": "Wise_Woman", "speed": 1.2})
        self.assertEqual(result["audios"], ["/api/results/audio-result"])

    async def test_runninghub_audio_reports_compliance_rejection_instead_of_fake_success(self):
        payload = main.CanvasAudioRequest(
            prompt="写一首歌",
            provider_id="runninghub",
            model="suno-custom-v5",
        )
        provider = {
            "id": "runninghub",
            "base_url": "https://www.runninghub.cn",
            "rh_region": "cn",
        }

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "taskId": "",
                    "status": "",
                    "errorCode": "40310",
                    "errorMessage": "Due to compliance requirements, this model is no longer available on this site.",
                }

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **_kwargs):
                return Response()

        model_def = {
            "endpoint": "suno/music",
            "params": [{"fieldKey": "text", "type": "STRING", "required": True}],
        }
        with patch.object(main, "runninghub_model_definition", new=AsyncMock(return_value=model_def)), \
             patch.object(main, "runninghub_json_headers", return_value={"Authorization": "Bearer test"}), \
             patch("main.httpx.AsyncClient", return_value=Client()):
            with self.assertRaises(main.HTTPException) as raised:
                await main.generate_runninghub_audio(payload, provider, {})

        self.assertEqual(raised.exception.status_code, 400)
        detail = raised.exception.detail
        self.assertEqual(detail["errorCode"], "40310")
        self.assertIn("当前站点", detail["message"])
        self.assertIn("国际站 Key", detail["message"])
        self.assertNotIn("生成成功", detail["message"])

    def test_runninghub_standard_media_share_rejection_parser(self):
        raw = {"errorCode": "49999", "errorMessage": "model rejected"}

        detail = main.runninghub_rejection_detail(raw, "视频")

        self.assertEqual(detail["errorCode"], "49999")
        self.assertIn("视频请求被拒绝", detail["message"])

    async def test_runninghub_audio_adapter_uploads_reference_audio_into_schema_field(self):
        payload = main.CanvasAudioRequest(
            provider_id="runninghub",
            model="demo/audio-model",
            prompt="你好",
            reference_audio="/api/results/audio/source.wav",
        )
        provider = {"id": "runninghub", "base_url": "https://www.runninghub.ai", "rh_region": "global", "wallet_api_key": "fixture-not-a-real-key"}
        submitted = {}

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"outputs": ["https://cdn.example.com/result.mp3"]}

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, url, headers=None, json=None, **_kwargs):
                submitted.update({"url": url, "headers": headers, "json": json})
                return Response()

        model_def = {
            "endpoint": "demo/audio-model",
            "params": [
                {"fieldKey": "text", "type": "STRING", "required": True},
                {"fieldKey": "audioUrl", "type": "AUDIO", "required": False},
            ],
        }
        with patch.object(main, "runninghub_model_definition", new=AsyncMock(return_value=model_def)), \
             patch.object(main, "runninghub_upload_reference", new=AsyncMock(return_value="https://cdn.example.com/source.wav")) as upload_mock, \
             patch.object(main, "save_remote_audio_to_output", new=AsyncMock(return_value="/api/results/audio-result")), \
             patch("main.httpx.AsyncClient", return_value=Client()):
            await main.generate_runninghub_audio(payload, provider, {})

        upload_mock.assert_awaited_once()
        self.assertEqual(submitted["json"]["audioUrl"], "https://cdn.example.com/source.wav")

    def test_canvas_llm_request_accepts_capability_parameters(self):
        payload = main.CanvasLLMRequest(
            message="你好",
            parameters={"temperature": 0.4, "max_output_tokens": 1024},
        )

        self.assertEqual(payload.parameters["temperature"], 0.4)
        self.assertEqual(payload.parameters["max_output_tokens"], 1024)

    def test_canvas_preflight_is_network_free_for_all_generation_nodes(self):
        providers = [{
            "id": "fixture-provider", "name": "Fixture", "protocol": "openai", "enabled": True,
            "chat_models": ["fixture-text"], "image_models": ["fixture-image"],
            "video_models": ["fixture-video"], "audio_models": ["fixture-audio", "fixture-music"],
        }]
        profiles = {
            "fixture-provider": {
                "provider_id": "fixture-provider", "models": [
                    {"model_id": "fixture-text", "family_id": "text-family", "variant_id": "chat", "node_type": "text_generation", "operation": "chat", "status": "confirmed", "evidence_level": "official_documented", "version": 1, "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}}, "parameters": {}, "request_mapping": {"prompt": "messages"}},
                    {"model_id": "fixture-image", "family_id": "image-family", "variant_id": "text_to_image", "node_type": "image_generation", "operation": "text_to_image", "status": "confirmed", "evidence_level": "official_schema", "version": 1, "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}}, "parameters": {}, "request_mapping": {"prompt": "prompt"}},
                    {"model_id": "fixture-video", "family_id": "video-family", "variant_id": "text_to_video", "node_type": "video_generation", "operation": "text_to_video", "status": "confirmed", "evidence_level": "official_schema", "version": 1, "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}}, "parameters": {}, "request_mapping": {"prompt": "prompt"}},
                    {"model_id": "fixture-audio", "family_id": "audio-family", "variant_id": "text_to_audio", "node_type": "audio_generation", "operation": "text_to_audio", "status": "confirmed", "evidence_level": "official_documented", "version": 1, "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}}, "parameters": {}, "request_mapping": {"prompt": "input"}},
                    {"model_id": "fixture-music", "family_id": "music-family", "variant_id": "music", "node_type": "music_generation", "operation": "music", "status": "confirmed", "evidence_level": "official_documented", "version": 1, "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}}, "parameters": {}, "request_mapping": {"prompt": "input"}},
                ],
            },
        }
        payloads = [
            main.CanvasPreflightRequest(provider_id="fixture-provider", model_id=model, node_type=node_type, inputs={"prompt": "测试"}, input_counts={"text": 1}, input_roles={"prompt": 1})
            for node_type, model in (("text_generation", "fixture-text"), ("image_generation", "fixture-image"), ("video_generation", "fixture-video"), ("audio_generation", "fixture-audio"), ("music_generation", "fixture-music"))
        ]
        with patch.object(main, "load_api_providers", return_value=providers), patch.object(
            main.MODEL_CAPABILITY_REGISTRY, "load", return_value={"registry": {"schema_version": 1}, "profiles": profiles}
        ):
            for payload in payloads:
                result = asyncio.run(main.canvas_preflight(payload))
                self.assertFalse(result["network_requested"])
                self.assertEqual(result["validation"], "contract_validated")
                self.assertEqual(result["standard_request"]["node_type"], payload.node_type)

    def test_canvas_preflight_prefers_selected_model_inside_multi_mode_family(self):
        providers = [{
            "id": "fixture-provider", "name": "Fixture", "protocol": "openai", "enabled": True,
            "chat_models": [], "image_models": [], "video_models": [],
            "audio_models": ["speech-hd", "speech-turbo"],
        }]
        variants = [
            {
                "model_id": model_id, "family_id": "speech-family", "family_name": "Speech",
                "variant_id": variant_id, "node_type": "audio_generation", "operation": "text_to_audio",
                "status": "confirmed", "evidence_level": "official_schema", "version": 1,
                "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
                "parameters": {}, "request_mapping": {"prompt": "text"},
            }
            for model_id, variant_id in (("speech-hd", "hd"), ("speech-turbo", "turbo"))
        ]
        payload = main.CanvasPreflightRequest(
            provider_id="fixture-provider", model_id="speech-turbo", family_id="speech-family",
            node_type="audio_generation", inputs={"prompt": "测试"},
            input_counts={"text": 1}, input_roles={"prompt": 1},
        )
        with patch.object(main, "load_api_providers", return_value=providers), patch.object(
            main.MODEL_CAPABILITY_REGISTRY,
            "load",
            return_value={"registry": {"schema_version": 1}, "profiles": {"fixture-provider": {"provider_id": "fixture-provider", "models": variants}}},
        ):
            result = asyncio.run(main.canvas_preflight(payload))

        self.assertEqual(result["standard_request"]["model_id"], "speech-turbo")
        self.assertEqual(result["standard_request"]["variant_id"], "turbo")

    def test_canvas_graph_accepts_fused_music_output_as_audio_input(self):
        result = main.validate_canvas_preflight_graph([
            {"id": "music", "type": "smart-music-generator"},
            {"id": "audio", "type": "smart-audio-generator"},
        ], [{"id": "edge", "from": "music", "to": "audio"}])
        self.assertEqual(result, {"node_count": 2, "connection_count": 1})


    def test_provider_manifest_accepts_music_generation_family(self):
        manifest = {
            "schema_version": 1,
            "provider": {"id": "music-demo", "name": "Music Demo", "version": "1"},
            "transport": {"type": "http"},
            "catalog": {"mode": "static"},
            "families": [{
                "family_id": "music-family",
                "display_name": "Music Family",
                "node_type": "music_generation",
                "variants": [{
                    "variant_id": "text-to-music",
                    "model_id": "music-model",
                    "operation": "text_to_music",
                    "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
                    "parameters": {},
                    "request_mapping": {"prompt": "prompt"},
                    "output": {"media_type": "audio"},
                    "evidence": {"level": "official_schema", "source": "fixture"},
                }],
            }],
        }

        result = ModelCapabilityRegistry(ROOT).validate_provider_manifest(manifest)

        self.assertTrue(result["valid"], result["errors"])

    def test_canvas_preflight_creates_and_reuses_local_run_record(self):
        providers = [{
            "id": "fixture-provider", "name": "Fixture", "protocol": "openai", "enabled": True,
            "chat_models": [], "image_models": ["fixture-image"], "video_models": [], "audio_models": [],
        }]
        profile = {
            "provider_id": "fixture-provider", "model_id": "fixture-image", "family_id": "fixture-image",
            "variant_id": "text_to_image", "node_type": "image_generation", "operation": "text_to_image",
            "status": "confirmed", "evidence_level": "official_schema", "version": 1,
            "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
            "parameters": {}, "request_mapping": {"prompt": "prompt"},
        }
        payload = main.CanvasPreflightRequest(
            canvas_id="canvas-1", node_id="node-1", client_operation_id="operation-1",
            provider_id="fixture-provider", model_id="fixture-image", node_type="image_generation",
            inputs={"prompt": "测试"}, input_counts={"text": 1}, input_roles={"prompt": 1},
        )

        with tempfile.TemporaryDirectory() as temporary:
            storage = ProjectStorage(temporary)
            storage.ensure_layout()
            with patch.object(main, "PROJECT_STORAGE", storage), patch.object(
                main, "load_api_providers", return_value=providers
            ), patch.object(
                main.MODEL_CAPABILITY_REGISTRY,
                "load",
                return_value={"registry": {"schema_version": 1}, "profiles": {"fixture-provider": {"provider_id": "fixture-provider", "models": [profile]}}},
            ):
                first = asyncio.run(main.canvas_preflight(payload))
                second = asyncio.run(main.canvas_preflight(payload))

        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["attempt_id"], second["attempt_id"])
        self.assertEqual(first["idempotency_key"], second["idempotency_key"])
        self.assertFalse(first["network_requested"])

    def test_canvas_run_endpoints_restore_filter_and_advance_local_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            storage = ProjectStorage(temporary)
            storage.ensure_layout()
            first = storage.prepare_run(
                "canvas-1", "node-1", "operation-1",
                {"provider_id": "fixture", "model_id": "model-1"},
                {"model": "model-1"},
            )
            storage.prepare_run(
                "canvas-2", "node-2", "operation-2",
                {"provider_id": "fixture", "model_id": "model-2"},
                {"model": "model-2"},
            )
            client = TestClient(main.app)
            with patch.object(main, "PROJECT_STORAGE", storage):
                listed = client.get("/api/canvas-runs", params={"canvas_id": "canvas-1"})
                queued = client.post(f"/api/canvas-runs/{first['run_id']}/status", json={"status": "queued"})
                submitted = client.post(f"/api/canvas-runs/{first['run_id']}/status", json={
                    "status": "submitted", "provider_task_id": "task-1",
                })
                results = client.post(f"/api/canvas-runs/{first['run_id']}/results", json={
                    "result_ids": ["res-1", "res-2", "res-1"],
                })

        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["run_id"] for item in listed.json()["runs"]], [first["run_id"]])
        self.assertEqual(queued.json()["attempts"][-1]["status"], "queued")
        self.assertEqual(submitted.json()["attempts"][-1]["provider_task_id"], "task-1")
        self.assertEqual(results.json()["attempts"][-1]["result_ids"], ["res-1", "res-2"])

    def test_canvas_run_status_endpoint_rejects_terminal_regression_and_missing_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            storage = ProjectStorage(temporary)
            storage.ensure_layout()
            run = storage.prepare_run(
                "canvas-1", "node-1", "operation-1",
                {"provider_id": "fixture", "model_id": "model-1"},
                {"model": "model-1"},
            )
            storage.update_run_status(run["run_id"], "submitted")
            storage.update_run_status(run["run_id"], "succeeded")
            client = TestClient(main.app)
            with patch.object(main, "PROJECT_STORAGE", storage):
                regression = client.post(f"/api/canvas-runs/{run['run_id']}/status", json={"status": "processing"})
                missing = client.post("/api/canvas-runs/run_missing/results", json={"result_ids": ["res-1"]})

        self.assertEqual(regression.status_code, 409)
        self.assertIn("不允许", regression.json()["detail"])
        self.assertEqual(missing.status_code, 404)

    def test_canvas_image_task_endpoint_reads_persisted_task_after_memory_cache_is_cleared(self):
        with tempfile.TemporaryDirectory() as temporary:
            storage = ProjectStorage(temporary)
            storage.ensure_layout()
            storage.create_canvas_task({
                "id": "canvas_img_persisted",
                "type": "online-image",
                "status": "succeeded",
                "provider_id": "fixture",
                "model": "fixture-image",
                "result": {"images": ["/api/results/res_1"]},
            })
            with main.CANVAS_TASK_LOCK:
                main.CANVAS_TASKS.clear()
            with patch.object(main, "PROJECT_STORAGE", storage):
                result = asyncio.run(main.get_canvas_image_task("canvas_img_persisted"))

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["result"]["images"], ["/api/results/res_1"])

    def test_canvas_preflight_validates_graph_before_model_resolution(self):
        payload = main.CanvasPreflightRequest(
            provider_id="fixture-provider", model_id="fixture-image", node_type="image_generation",
            inputs={"prompt": "测试"}, input_counts={"text": 1}, input_roles={"prompt": 1},
            nodes=[{"id": "material-1", "type": "smart-material"}, {"id": "run-1", "type": "smart-image-generator"}],
            connections=[{"from": "missing", "to": "run-1"}],
        )
        with self.assertRaises(main.HTTPException) as context:
            asyncio.run(main.canvas_preflight(payload))
        self.assertIn("不存在", str(context.exception.detail))

    def test_canvas_preflight_checks_runninghub_ai_app_fields_without_network(self):
        providers = [{
            "id": "runninghub", "name": "RunningHub", "protocol": "runninghub", "enabled": True,
            "rh_apps": [{"id": "app-1", "title": "数字人应用", "fields": [
                {"nodeId": "1", "fieldName": "image", "fieldType": "IMAGE", "schemaOrder": 0},
                {"nodeId": "2", "fieldName": "prompt", "fieldType": "TEXT", "schemaOrder": 1},
            ]}], "chat_models": [], "image_models": [], "video_models": [], "audio_models": [],
        }]
        payload = main.CanvasPreflightRequest(
            provider_id="runninghub", node_type="ai_application", ai_app_id="app-1",
            inputs={"1::image": "asset://image-1", "2::prompt": "测试"},
            input_roles={"image": 1, "prompt": 1},
            app_field_values={"1::image": "asset://image-1", "2::prompt": "测试"},
        )
        with patch.object(main, "canvas_api_providers", return_value=providers):
            result = asyncio.run(main.canvas_preflight(payload))
        self.assertFalse(result["network_requested"])
        self.assertEqual(result["standard_request"]["node_type"], "ai_application")
        self.assertEqual(result["standard_request"]["ai_app_id"], "app-1")
        self.assertEqual(result["platform_request"]["fields"]["1::image"], "asset://image-1")

    def test_runninghub_preflight_preserves_official_order_and_separates_inputs_from_parameters(self):
        provider = {
            "id": "runninghub", "name": "RunningHub", "protocol": "runninghub", "enabled": True,
            "rh_apps": [{"id": "app-1", "title": "多模态应用", "fields": [
                {"nodeId": "1", "fieldName": "prompt", "fieldType": "TEXT", "schemaOrder": 0},
                {"nodeId": "2", "fieldName": "image", "fieldType": "IMAGE", "schemaOrder": 1},
                {"nodeId": "3", "fieldName": "video", "fieldType": "VIDEO", "schemaOrder": 2},
                {"nodeId": "4", "fieldName": "audio", "fieldType": "AUDIO", "schemaOrder": 3},
                {"nodeId": "5", "fieldName": "enabled", "fieldType": "BOOLEAN", "schemaOrder": 4},
                {"nodeId": "6", "fieldName": "mode", "fieldType": "SELECT", "schemaOrder": 5},
                {"nodeId": "7", "fieldName": "strength", "fieldType": "NUMBER", "schemaOrder": 6},
            ]}],
        }
        payload = main.CanvasPreflightRequest(
            provider_id="runninghub", node_type="ai_application", ai_app_id="app-1",
            app_field_values={
                "7::strength": 0.8,
                "2::image": "asset://image-1",
                "6::mode": "fast",
                "1::prompt": "测试",
                "5::enabled": True,
                "4::audio": "asset://audio-1",
                "3::video": "asset://video-1",
            },
        )

        with patch.object(main, "canvas_api_providers", return_value=[provider]):
            result = asyncio.run(main.canvas_preflight(payload))

        expected_order = [
            "1::prompt", "2::image", "3::video", "4::audio",
            "5::enabled", "6::mode", "7::strength",
        ]
        self.assertEqual(list(result["platform_request"]["fields"]), expected_order)
        self.assertEqual(list(result["standard_request"]["inputs"]), expected_order[:4])
        self.assertEqual(list(result["standard_request"]["parameters"]), expected_order[4:])
        self.assertEqual(result["validation"], "contract_validated")
        self.assertFalse(result["network_requested"])

    def test_all_canvas_node_variants_build_network_free_platform_snapshots(self):
        providers = [{
            "id": "fixture-provider", "name": "Fixture", "protocol": "openai", "enabled": True,
            "chat_models": ["text-multimodal"],
            "image_models": ["image-text", "image-single", "image-multi"],
            "video_models": ["video-text", "video-first", "video-first-last", "video-multi"],
            "audio_models": ["audio-text", "audio-reference"],
        }]
        def profile(model_id, family_id, variant_id, node_type, operation, inputs, mapping):
            return {
                "model_id": model_id, "family_id": family_id, "variant_id": variant_id,
                "node_type": node_type, "operation": operation, "status": "confirmed",
                "evidence_level": "official_schema", "version": 1, "inputs": inputs,
                "parameters": {}, "request_mapping": mapping,
            }
        prompt = {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}
        models = [
            profile("text-multimodal", "text-family", "multimodal", "text_generation", "chat", {
                "prompt": prompt,
                "reference": {"media_type": "image", "min": 0, "max": 2, "role": "reference"},
                "source_video": {"media_type": "video", "min": 0, "max": 1, "role": "source_video"},
                "reference_audio": {"media_type": "audio", "min": 0, "max": 1, "role": "reference_audio"},
            }, {"prompt": "messages.prompt", "reference": "messages.images", "source_video": "messages.video", "reference_audio": "messages.audio"}),
            profile("image-text", "image-family", "text", "image_generation", "text_to_image", {"prompt": prompt}, {"prompt": "prompt"}),
            profile("image-single", "image-family", "single", "image_generation", "image_to_image", {
                "prompt": prompt, "reference": {"media_type": "image", "min": 1, "max": 1, "role": "reference"},
            }, {"prompt": "prompt", "reference": "image"}),
            profile("image-multi", "image-family", "multi", "image_generation", "multi_reference", {
                "prompt": prompt, "reference": {"media_type": "image", "min": 2, "max": 3, "role": "reference"},
            }, {"prompt": "prompt", "reference": "images"}),
            profile("video-text", "video-family", "text", "video_generation", "text_to_video", {"prompt": prompt}, {"prompt": "prompt"}),
            profile("video-first", "video-family", "first", "video_generation", "first_frame", {
                "prompt": prompt, "first_frame": {"media_type": "image", "min": 1, "max": 1, "role": "first_frame"},
            }, {"prompt": "prompt", "first_frame": "first_frame"}),
            profile("video-first-last", "video-family", "first_last", "video_generation", "first_last_frame", {
                "prompt": prompt,
                "first_frame": {"media_type": "image", "min": 1, "max": 1, "role": "first_frame"},
                "last_frame": {"media_type": "image", "min": 1, "max": 1, "role": "last_frame"},
            }, {"prompt": "prompt", "first_frame": "first_frame", "last_frame": "last_frame"}),
            profile("video-multi", "video-family", "multi", "video_generation", "multi_reference", {
                "prompt": prompt, "reference": {"media_type": "image", "min": 2, "max": 4, "role": "reference"},
            }, {"prompt": "prompt", "reference": "images"}),
            profile("audio-text", "audio-family", "text", "audio_generation", "text_to_audio", {"prompt": prompt}, {"prompt": "input"}),
            profile("audio-reference", "audio-family", "reference", "audio_generation", "reference_audio", {
                "prompt": prompt, "reference_audio": {"media_type": "audio", "min": 1, "max": 1, "role": "reference_audio"},
            }, {"prompt": "input", "reference_audio": "reference_audio"}),
        ]
        cases = [
            ("text-family", "text_generation", {"prompt": "分析", "reference": ["image-1"], "source_video": ["video-1"], "reference_audio": ["audio-1"]}, {"text": 1, "image": 1, "video": 1, "audio": 1}, {"prompt": 1, "reference": 1, "source_video": 1, "reference_audio": 1}, "text-multimodal"),
            ("image-family", "image_generation", {"prompt": "生成"}, {"text": 1, "image": 0}, {"prompt": 1}, "image-text"),
            ("image-family", "image_generation", {"prompt": "编辑", "reference": ["image-1"]}, {"text": 1, "image": 1}, {"prompt": 1, "reference": 1}, "image-single"),
            ("image-family", "image_generation", {"prompt": "融合", "reference": ["image-1", "image-2"]}, {"text": 1, "image": 2}, {"prompt": 1, "reference": 2}, "image-multi"),
            ("video-family", "video_generation", {"prompt": "视频"}, {"text": 1, "image": 0}, {"prompt": 1}, "video-text"),
            ("video-family", "video_generation", {"prompt": "动画", "first_frame": ["image-1"]}, {"text": 1, "image": 1}, {"prompt": 1, "first_frame": 1}, "video-first"),
            ("video-family", "video_generation", {"prompt": "转场", "first_frame": ["image-1"], "last_frame": ["image-2"]}, {"text": 1, "image": 2}, {"prompt": 1, "first_frame": 1, "last_frame": 1}, "video-first-last"),
            ("video-family", "video_generation", {"prompt": "参考", "reference": ["image-1", "image-2", "image-3"]}, {"text": 1, "image": 3}, {"prompt": 1, "reference": 3}, "video-multi"),
            ("audio-family", "audio_generation", {"prompt": "朗读"}, {"text": 1, "audio": 0}, {"prompt": 1}, "audio-text"),
            ("audio-family", "audio_generation", {"prompt": "仿声", "reference_audio": "audio-1"}, {"text": 1, "audio": 1}, {"prompt": 1, "reference_audio": 1}, "audio-reference"),
        ]
        fixture = {"provider_id": "fixture-provider", "models": models}
        with patch.object(main, "load_api_providers", return_value=providers), patch.object(
            main.MODEL_CAPABILITY_REGISTRY, "load",
            return_value={"registry": {"schema_version": 1}, "profiles": {"fixture-provider": fixture}},
        ):
            for family_id, node_type, inputs, counts, roles, expected_model in cases:
                payload = main.ModelCapabilityDryRunRequest(
                    provider_id="fixture-provider", family_id=family_id, node_type=node_type,
                    inputs=inputs, input_counts=counts, input_roles=roles,
                )
                result = asyncio.run(main.model_capability_dry_run(payload))
                self.assertEqual(result["standard_request"]["model_id"], expected_model)
                self.assertEqual(result["validation"], "contract_validated")
                self.assertFalse(result["network_requested"])
                self.assertTrue(result["platform_request"])

    def test_provider_integration_endpoints_are_local_and_non_generating(self):
        client = TestClient(main.app)
        guide = client.get("/api/provider-integration-guide")
        schema = client.get("/api/provider-manifest-schema")

        self.assertEqual(guide.status_code, 200)
        self.assertIn("目录发现不等于可运行", guide.text)
        self.assertEqual(schema.status_code, 200)
        self.assertEqual(schema.json()["title"], "智能画布第三方平台 Provider Manifest")

    def test_provider_manifest_validation_rejects_secrets_and_scripts(self):
        client = TestClient(main.app)
        response = client.post("/api/provider-manifests/validate", json={"manifest": {
            "schema_version": 1,
            "provider": {"id": "fixture-provider", "name": "Fixture", "version": "1"},
            "transport": {"type": "http", "script": "curl example"},
            "catalog": {"mode": "endpoint"},
            "families": [],
            "api_key": "secret"
        }})

        self.assertEqual(response.status_code, 400)
        detail = " ".join(response.json()["errors"])
        self.assertIn("api_key", detail)
        self.assertIn("script", detail)

    def test_provider_manifest_validation_rejects_empty_families(self):
        client = TestClient(main.app)
        response = client.post("/api/provider-manifests/validate", json={"manifest": {
            "schema_version": 1,
            "provider": {"id": "fixture-provider", "name": "Fixture", "version": "1"},
            "transport": {"type": "http"},
            "catalog": {"mode": "endpoint"},
            "families": [],
        }})

        self.assertEqual(response.status_code, 400)
        self.assertIn("families 至少包含一个模型家族", response.json()["errors"])

    def test_runninghub_profiles_include_official_image_enum_options(self):
        profile_path = ROOT / "data" / "model_capabilities" / "providers" / "runninghub.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        expected_ratios = [
            "empty", "3:2", "1:1", "2:3", "5:4", "4:5", "16:9", "9:16",
            "21:9", "3:4", "4:3", "9:21", "1:2", "2:1", "1:3", "3:1",
        ]

        for model in profile["models"]:
            self.assertEqual(model["parameters"]["aspect_ratio"]["options"], expected_ratios)
            self.assertEqual(model["parameters"]["aspect_ratio"]["default"], "empty")
            self.assertEqual(model["parameters"]["resolution"]["options"], ["1k", "2k", "4k"])
            self.assertEqual(model["parameters"]["resolution"]["default"], "1k")

    def test_runtime_catalog_intersects_profiles_with_enabled_provider_models(self):
        providers = [
            {
                "id": "ai-money",
                "name": "AI MONEY",
                "protocol": "openai",
                "enabled": True,
                "image_models": ["laohuaimoney-image-g-v2-lowprice", "custom-image"],
                "chat_models": [],
                "video_models": [],
                "audio_models": ["doubao-seed-audio-1.0"],
            },
            {
                "id": "jimeng",
                "name": "即梦 CLI",
                "protocol": "jimeng",
                "enabled": True,
                "image_models": ["5.0Pro"],
                "chat_models": [],
                "video_models": ["seedance2.0"],
            },
            {
                "id": "codex",
                "name": "GPT CLI",
                "protocol": "codex",
                "enabled": True,
                "image_models": [],
                "chat_models": ["gpt-5.5"],
                "video_models": [],
            },
        ]

        catalog = main.build_model_capability_catalog(providers)
        by_id = {item["id"]: item for item in catalog["providers"]}

        ai_models = {item["model_id"]: item for item in by_id["ai-money"]["models"]}
        self.assertEqual(ai_models["laohu-image-g-v2-lowprice"]["validation_mode"], "strict")
        self.assertEqual(ai_models["custom-image"]["validation_mode"], "blocked")
        self.assertEqual(ai_models["custom-image"]["readiness"], "needs_profile")
        self.assertFalse(ai_models["custom-image"]["runnable"])
        self.assertEqual(ai_models["laohu-image-g-v2-lowprice"]["readiness"], "ready")
        self.assertTrue(ai_models["laohu-image-g-v2-lowprice"]["runnable"])
        self.assertEqual(ai_models["doubao-seed-audio-1.0"]["node_type"], "audio_generation")
        self.assertEqual(ai_models["doubao-seed-audio-1.0"]["validation_mode"], "strict")
        self.assertEqual(by_id["jimeng"]["capability_provider_id"], "jimeng-cli")
        self.assertEqual(by_id["codex"]["capability_provider_id"], "codex-cli")
        self.assertFalse(any(item["node_type"] == "image_generation" for item in by_id["codex"]["models"]))

    def test_laohu_gpt_image_variants_share_canvas_and_hypit_candidates(self):
        confirmed_gpt_ids = [
            "laohu-image-g-v2.5-flare",
            "laohu-image-g-v2.5-lowprice",
            "laohu-image-g-v2.5-sunburst",
            "laohu-image-g2-i2i",
            "laohu-image-g2-t2i",
            "laohu-image-g-v2-lowprice",
        ]
        grok_id = "laohu-image-gk-v2-edit"
        providers = [{
            "id": "ai-money",
            "name": "laohu",
            "protocol": "openai",
            "enabled": True,
            "image_models": [*confirmed_gpt_ids, grok_id],
            "chat_models": [],
            "video_models": [],
            "audio_models": [],
        }]

        catalog = main.build_model_capability_catalog(providers)
        runtime_provider = next(item for item in catalog["providers"] if item["id"] == "ai-money")
        runtime_models = {item["model_id"]: item for item in runtime_provider["models"]}
        for model_id in [*confirmed_gpt_ids, grok_id]:
            self.assertTrue(runtime_models[model_id]["runnable"], model_id)
            self.assertTrue(runtime_models[model_id]["selectable"], model_id)

        options = {item["catalog_model_id"]: item for item in catalog["options"]}
        for model_id in confirmed_gpt_ids:
            self.assertEqual(options[model_id]["canonical_family_id"], "series-image-gpt-image")
            self.assertEqual(options[model_id]["canonical_family_label"], {"zh": "GPT Image", "en": "GPT Image"})
        self.assertEqual(options[grok_id]["canonical_family_id"], "series-image-grok-image")
        self.assertEqual(options["laohu-image-g2-i2i"]["inputs"]["reference"]["min"], 1)
        self.assertEqual(options["laohu-image-g2-t2i"]["operation"], "text_to_image")

        canvas_options = select_options_for_slot(catalog["options"], "canvas", "image_generation")["options"]
        hypit_options = select_options_for_slot(catalog["options"], "hypit", "image")["options"]
        expected = set([*confirmed_gpt_ids, grok_id])
        self.assertEqual({item["catalog_model_id"] for item in canvas_options}, expected)
        self.assertEqual({item["catalog_model_id"] for item in hypit_options}, expected)
        self.assertEqual(
            {item["canonical_family_id"] for item in hypit_options if item["catalog_model_id"] in confirmed_gpt_ids},
            {"series-image-gpt-image"},
        )

    def test_removed_model_leaves_runtime_catalog_without_deleting_profile(self):
        providers = [{
            "id": "ai-money",
            "name": "AI MONEY",
            "protocol": "openai",
            "enabled": True,
            "image_models": [],
            "chat_models": [],
            "video_models": [],
            "audio_models": ["doubao-seed-audio-1.0"],
        }]

        catalog = main.build_model_capability_catalog(providers)
        runtime_models = catalog["providers"][0]["models"]
        self.assertEqual([item["model_id"] for item in runtime_models], ["doubao-seed-audio-1.0"])

        providers[0]["audio_models"] = []
        catalog = main.build_model_capability_catalog(providers)
        self.assertEqual(catalog["providers"][0]["models"], [])

        profile_path = ROOT / "data" / "model_capabilities" / "providers" / "ai-money.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        self.assertTrue(any(item["model_id"] == "doubao-seed-audio-1.0" for item in profile["models"]))

    def test_confirmed_profile_rejects_unsupported_reference_input(self):
        providers = [{
            "id": "runninghub",
            "name": "RunningHub",
            "protocol": "runninghub",
            "enabled": True,
            "image_models": ["gpt-image-2.0/text-to-image-channel-low-price"],
            "chat_models": [],
            "video_models": [],
        }]

        with self.assertRaises(main.HTTPException) as context:
            main.validate_model_capability_request(
                "runninghub",
                "gpt-image-2.0/text-to-image-channel-low-price",
                "image_generation",
                input_counts={"prompt": 1, "image": 1},
                parameters={"resolution": "2k"},
                providers=providers,
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("不支持图片输入", str(context.exception.detail))

    def test_video_variants_are_selected_by_input_roles(self):
        providers = [{
            "id": "jimeng-cli",
            "name": "即梦 CLI",
            "protocol": "jimeng",
            "enabled": True,
            "image_models": [],
            "chat_models": [],
            "video_models": ["seedance2.0"],
            "audio_models": [],
        }]

        profile = main.validate_model_capability_request(
            "jimeng-cli",
            "seedance2.0",
            "video_generation",
            input_counts={"text": 1, "image": 2, "video": 0, "audio": 0},
            input_roles={"prompt": 1, "first_frame": 1, "last_frame": 1},
            providers=providers,
        )
        self.assertEqual(profile["model_id"], "seedance2.0")

        with self.assertRaises(main.HTTPException) as context:
            main.validate_model_capability_request(
                "jimeng-cli",
                "seedance2.0",
                "video_generation",
                input_counts={"text": 1, "image": 1, "video": 0, "audio": 0},
                input_roles={"prompt": 1, "source_video": 1},
                providers=providers,
            )
        self.assertIn("输入角色", str(context.exception.detail))

    def test_canvas_image_dry_run_preserves_input_roles_without_network(self):
        providers = [{
            "id": "runninghub",
            "name": "RunningHub",
            "protocol": "runninghub",
            "enabled": True,
            "image_models": ["gpt-image-2.0/text-to-image-channel-low-price"],
            "chat_models": [],
            "video_models": [],
            "audio_models": [],
        }]
        profile = main.validate_model_capability_request(
            "runninghub",
            "gpt-image-2.0/text-to-image-channel-low-price",
            "image_generation",
            input_counts={"prompt": 1, "image": 0},
            input_roles={"prompt": 1},
            providers=providers,
        )
        dry_run = main.MODEL_CAPABILITY_REGISTRY.build_dry_run(
            profile,
            inputs={"prompt": "测试"},
            input_roles={"prompt": 1},
        )
        self.assertFalse(dry_run["network_requested"])
        self.assertEqual(dry_run["standard_request"]["input_roles"], {"prompt": 1})

    def test_confirmed_profile_only_accepts_declared_parameters(self):
        providers = [{
            "id": "ai-money",
            "name": "AI MONEY",
            "protocol": "openai",
            "enabled": True,
            "image_models": ["laohuaimoney-image-g-v2-lowprice"],
            "chat_models": [],
            "video_models": [],
        }]

        with self.assertRaises(main.HTTPException) as context:
            main.validate_model_capability_request(
                "ai-money",
                "laohuaimoney-image-g-v2-lowprice",
                "image_generation",
                input_counts={"prompt": 1},
                parameters={"quality": "high"},
                providers=providers,
            )

        self.assertIn("不支持参数", str(context.exception.detail))

    def test_confirmed_profile_validates_parameter_range_and_enum(self):
        providers = [{
            "id": "ai-money",
            "name": "AI MONEY",
            "protocol": "openai",
            "enabled": True,
            "image_models": ["laohuaimoney-image-g-v2-lowprice"],
            "chat_models": [],
            "video_models": [],
        }]

        with self.assertRaises(main.HTTPException) as count_context:
            main.validate_model_capability_request(
                "ai-money",
                "laohuaimoney-image-g-v2-lowprice",
                "image_generation",
                input_counts={"prompt": 1},
                parameters={"count": 11},
                providers=providers,
            )
        self.assertIn("不能大于 10", str(count_context.exception.detail))

        with self.assertRaises(main.HTTPException) as resolution_context:
            main.validate_model_capability_request(
                "ai-money",
                "laohuaimoney-image-g-v2-lowprice",
                "image_generation",
                input_counts={"prompt": 1},
                parameters={"resolution": "8k"},
                providers=providers,
            )
        self.assertIn("不支持取值 8k", str(resolution_context.exception.detail))

    def test_pending_or_unknown_profile_is_blocked_before_network_use(self):
        providers = [{
            "id": "modelscope",
            "name": "ModelScope",
            "protocol": "openai",
            "enabled": True,
            "image_models": ["example/Unknown-Image-Model"],
            "chat_models": [],
            "video_models": [],
        }]

        with self.assertRaises(main.HTTPException) as context:
            main.validate_model_capability_request(
                "modelscope",
                "example/Unknown-Image-Model",
                "image_generation",
                input_counts={"prompt": 1, "image": 2},
                parameters={"legacy_parameter": True},
                providers=providers,
            )

        self.assertIn("能力档案", str(context.exception.detail))

    def test_frontend_filters_strict_models_by_connected_media(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const catalog={providers:[
  {id:'rh',name:'RH',models:[
    {model_id:'t2i',node_type:'image_generation',validation_mode:'strict',inputs:{prompt:{media_type:'text',min:1,max:1}}},
    {model_id:'edit',node_type:'image_generation',validation_mode:'strict',inputs:{prompt:{media_type:'text',min:1,max:1},reference:{media_type:'image',min:1,max:2}}},
    {model_id:'legacy',node_type:'image_generation',validation_mode:'compatible',inputs:{}}
  ]}
]};
console.log(JSON.stringify({
  withoutImage:c.modelsForInputs(catalog,'image_generation',{text:1,image:0}).map(x=>x.model_id),
  withImage:c.modelsForInputs(catalog,'image_generation',{text:1,image:1}).map(x=>x.model_id),
  tooMany:c.modelsForInputs(catalog,'image_generation',{text:1,image:3}).map(x=>x.model_id)
}));
"""
        data = run_node(source)

        self.assertEqual(data["withoutImage"], ["t2i"])
        self.assertEqual(data["withImage"], ["edit"])
        self.assertEqual(data["tooMany"], [])

    def test_text_generation_requires_verified_capability_for_connected_media(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const catalog={providers:[{id:'p',models:[
  {model_id:'text',node_type:'text_generation',validation_mode:'strict',inputs:{prompt:{media_type:'text',min:1,max:1}}},
  {model_id:'vision',node_type:'text_generation',validation_mode:'strict',inputs:{prompt:{media_type:'text',min:1,max:8},reference:{media_type:'image',min:0,max:4}}},
  {model_id:'unknown',node_type:'text_generation',validation_mode:'compatible',inputs:{}}
]}]};
console.log(JSON.stringify({
  text:c.modelsForVerifiedInputs(catalog,'text_generation',{text:1,image:0,video:0,audio:0}).map(x=>x.model_id),
  image:c.modelsForVerifiedInputs(catalog,'text_generation',{text:1,image:1,video:0,audio:0}).map(x=>x.model_id),
  video:c.modelsForVerifiedInputs(catalog,'text_generation',{text:1,image:0,video:1,audio:0}).map(x=>x.model_id)
}));
"""
        data = run_node(source)

        self.assertEqual(data["text"], ["text", "vision"])
        self.assertEqual(data["image"], ["vision"])
        self.assertEqual(data["video"], [])

    def test_runtime_catalog_groups_enabled_variants_into_product_family(self):
        providers = [{
            "id": "fixture-provider",
            "name": "Fixture",
            "protocol": "openai",
            "enabled": True,
            "image_models": [],
            "chat_models": [],
            "video_models": ["seedance-fast-t2v", "seedance-fast-i2v"],
            "audio_models": [],
        }]
        registry = main.MODEL_CAPABILITY_REGISTRY
        loaded = registry.load
        fixture_profile = {
            "provider_id": "fixture-provider",
            "models": [
                {
                    "model_id": "seedance-fast-t2v", "family_id": "seedance-fast",
                    "family_name": "Seedance Fast", "variant_id": "text_to_video",
                    "node_type": "video_generation", "operation": "text_to_video",
                    "status": "confirmed", "evidence_level": "official_schema", "version": 1,
                    "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
                    "parameters": {}, "request_mapping": {"prompt": "prompt"},
                },
                {
                    "model_id": "seedance-fast-i2v", "family_id": "seedance-fast",
                    "family_name": "Seedance Fast", "variant_id": "image_to_video",
                    "node_type": "video_generation", "operation": "image_to_video",
                    "status": "confirmed", "evidence_level": "official_schema", "version": 1,
                    "inputs": {
                        "prompt": {"media_type": "text", "min": 1, "max": 1},
                        "first_frame": {"media_type": "image", "min": 1, "max": 1},
                    },
                    "parameters": {}, "request_mapping": {"prompt": "prompt", "first_frame": "image"},
                },
            ],
        }
        with patch.object(registry, "load", return_value={"registry": {"schema_version": 1}, "profiles": {"fixture-provider": fixture_profile}}):
            catalog = main.build_model_capability_catalog(providers)

        family = catalog["providers"][0]["families"][0]
        self.assertEqual(family["family_id"], "seedance-fast")
        self.assertEqual(family["display_name"], "Seedance Fast")
        self.assertEqual([item["variant_id"] for item in family["variants"]], ["text_to_video", "image_to_video"])

    def test_variant_router_uses_input_roles_to_select_unique_upstream_model(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const family={family_id:'seedance-fast',variants:[
  {model_id:'seedance-fast-t2v',variant_id:'text_to_video',validation_mode:'strict',readiness:'ready',inputs:{prompt:{media_type:'text',min:1,max:1}}},
  {model_id:'seedance-fast-i2v',variant_id:'image_to_video',validation_mode:'strict',readiness:'ready',inputs:{prompt:{media_type:'text',min:1,max:1},first_frame:{media_type:'image',min:1,max:1}}}
]};
console.log(JSON.stringify({
  text:c.resolveFamilyVariant(family,{text:1,image:0,video:0,audio:0}),
  image:c.resolveFamilyVariant(family,{text:1,image:1,video:0,audio:0})
}));
"""
        data = run_node(source)
        self.assertEqual(data["text"]["model_id"], "seedance-fast-t2v")
        self.assertEqual(data["image"]["model_id"], "seedance-fast-i2v")

    def test_variant_router_keeps_generic_image_ambiguous_but_honors_explicit_first_frame(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const family={family_id:'seedance-role',variants:[
  {model_id:'seedance-frame',variant_id:'first_frame',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1,role:'prompt'},first_frame:{media_type:'image',min:1,max:1,role:'first_frame'}}},
  {model_id:'seedance-reference',variant_id:'reference',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1,role:'prompt'},reference:{media_type:'image',min:1,max:1,role:'reference'}}}
]};
console.log(JSON.stringify({
  first:c.resolveFamilyVariant(family,{text:1,image:1},'',{first_frame:1}),
  reference:c.resolveFamilyVariant(family,{text:1,image:1},'',{reference:1}),
  unspecified:c.resolveFamilyVariant(family,{text:1,image:1})
}));
"""
        data = run_node(source)

        self.assertEqual(data["first"]["model_id"], "seedance-frame")
        self.assertIsNone(data["reference"])
        self.assertIsNone(data["unspecified"])

    def test_backend_role_router_requires_mode_for_generic_image_but_honors_explicit_first_frame(self):
        providers = [{
            "id": "fixture-provider", "name": "Fixture", "protocol": "openai", "enabled": True,
            "image_models": [], "chat_models": [],
            "video_models": ["seedance-frame", "seedance-reference"], "audio_models": [],
        }]
        fixture_profile = {
            "provider_id": "fixture-provider",
            "models": [
                {
                    "model_id": "seedance-frame", "family_id": "seedance-role", "variant_id": "first_frame",
                    "node_type": "video_generation", "operation": "image_to_video", "status": "confirmed",
                    "evidence_level": "official_schema", "version": 1,
                    "inputs": {
                        "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
                        "first_frame": {"media_type": "image", "min": 1, "max": 1, "role": "first_frame"},
                    },
                    "parameters": {}, "request_mapping": {"prompt": "prompt", "first_frame": "image"},
                },
                {
                    "model_id": "seedance-reference", "family_id": "seedance-role", "variant_id": "reference",
                    "node_type": "video_generation", "operation": "reference_to_video", "status": "confirmed",
                    "evidence_level": "official_schema", "version": 1,
                    "inputs": {
                        "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
                        "reference": {"media_type": "image", "min": 1, "max": 1, "role": "reference"},
                    },
                    "parameters": {}, "request_mapping": {"prompt": "prompt", "reference": "images"},
                },
            ],
        }
        registry = main.MODEL_CAPABILITY_REGISTRY
        with patch.object(registry, "load", return_value={"registry": {"schema_version": 1}, "profiles": {"fixture-provider": fixture_profile}}):
            first = registry.resolve_family_variant(
                providers, "fixture-provider", "seedance-role", "video_generation",
                input_counts={"text": 1, "image": 1}, input_roles={"first_frame": 1},
            )
            with self.assertRaises(main.ModelCapabilityError):
                registry.resolve_family_variant(
                    providers, "fixture-provider", "seedance-role", "video_generation",
                    input_counts={"text": 1, "image": 1}, input_roles={"reference": 1},
                )
            reference = registry.resolve_family_variant(
                providers, "fixture-provider", "seedance-role", "video_generation",
                input_counts={"text": 1, "image": 1}, input_roles={"reference": 1},
                operation="reference",
            )

        self.assertEqual(first["model_id"], "seedance-frame")
        self.assertEqual(reference["model_id"], "seedance-reference")

    def test_frontend_exposes_one_resolvable_option_per_model_family(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const catalog={providers:[{id:'fixture',name:'Fixture',families:[
  {family_id:'seedance-fast',display_name:'Seedance Fast',node_type:'video_generation',variants:[
    {model_id:'seedance-fast-t2v',variant_id:'text_to_video',node_type:'video_generation',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1}}},
    {model_id:'seedance-fast-i2v',variant_id:'image_to_video',node_type:'video_generation',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1},first_frame:{media_type:'image',min:1,max:1}}}
  ]},
  {family_id:'ambiguous',display_name:'Ambiguous',node_type:'video_generation',variants:[
    {model_id:'ambiguous-a',variant_id:'a',node_type:'video_generation',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1}}},
    {model_id:'ambiguous-b',variant_id:'b',node_type:'video_generation',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1}}}
  ]}
]}]};
console.log(JSON.stringify({
  text:c.familiesForInputs(catalog,'video_generation',{text:1,image:0},'fixture'),
  image:c.familiesForInputs(catalog,'video_generation',{text:1,image:1},'fixture')
}));
"""
        data = run_node(source)

        self.assertEqual([item["family_id"] for item in data["text"]], ["seedance-fast", "ambiguous"])
        self.assertEqual(data["text"][0]["resolved_variant"]["model_id"], "seedance-fast-t2v")
        self.assertIsNone(data["text"][1]["resolved_variant"])
        self.assertEqual(data["image"][0]["resolved_variant"]["model_id"], "seedance-fast-i2v")

    def test_frontend_migrates_legacy_model_id_to_family_selection(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const provider={id:'fixture',families:[
  {family_id:'seedance-fast',display_name:'Seedance Fast',variants:[
    {model_id:'seedance-fast-t2v'}, {model_id:'seedance-fast-i2v'}
  ]}
]};
console.log(JSON.stringify(c.familyForModel(provider,'seedance-fast-i2v')));
"""

        self.assertEqual(run_node(source)["family_id"], "seedance-fast")

    def test_frontend_does_not_silently_replace_incompatible_family(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const catalog={providers:[{id:'fixture',families:[
  {family_id:'text-only',node_type:'video_generation',variants:[
    {model_id:'text-only-v1',node_type:'video_generation',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1}}}
  ]},
  {family_id:'image-ready',node_type:'video_generation',variants:[
    {model_id:'image-ready-v1',node_type:'video_generation',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1},reference:{media_type:'image',min:1,max:1}}}
  ]}
]}]};
const families=c.familiesForInputs(catalog,'video_generation',{text:1,image:1},'fixture');
const selected=families.find(item=>item.family_id==='text-only') || null;
console.log(JSON.stringify({available:families.map(item=>item.family_id),selected}));
"""
        data = run_node(source)

        self.assertEqual(data["available"], ["image-ready"])
        self.assertIsNone(data["selected"])

    def test_backend_resolves_family_to_unique_enabled_variant(self):
        providers = [{
            "id": "fixture-provider", "name": "Fixture", "protocol": "openai", "enabled": True,
            "image_models": [], "chat_models": [],
            "video_models": ["seedance-fast-t2v", "seedance-fast-i2v"], "audio_models": [],
        }]
        fixture_profile = {
            "provider_id": "fixture-provider",
            "models": [
                {
                    "model_id": "seedance-fast-t2v", "family_id": "seedance-fast",
                    "family_name": "Seedance Fast", "variant_id": "text_to_video",
                    "node_type": "video_generation", "operation": "text_to_video",
                    "status": "confirmed", "evidence_level": "official_schema", "version": 1,
                    "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
                    "parameters": {}, "request_mapping": {"prompt": "prompt"},
                },
                {
                    "model_id": "seedance-fast-i2v", "family_id": "seedance-fast",
                    "family_name": "Seedance Fast", "variant_id": "image_to_video",
                    "node_type": "video_generation", "operation": "image_to_video",
                    "status": "confirmed", "evidence_level": "official_schema", "version": 1,
                    "inputs": {
                        "prompt": {"media_type": "text", "min": 1, "max": 1},
                        "first_frame": {"media_type": "image", "min": 1, "max": 1},
                    },
                    "parameters": {}, "request_mapping": {"prompt": "prompt", "first_frame": "image"},
                },
            ],
        }
        registry = main.MODEL_CAPABILITY_REGISTRY
        with patch.object(registry, "load", return_value={"registry": {"schema_version": 1}, "profiles": {"fixture-provider": fixture_profile}}):
            text_variant = registry.resolve_family_variant(
                providers, "fixture-provider", "seedance-fast", "video_generation",
                input_counts={"text": 1, "image": 0},
            )
            image_variant = registry.resolve_family_variant(
                providers, "fixture-provider", "seedance-fast", "video_generation",
                input_counts={"text": 1, "image": 1},
            )

        self.assertEqual(text_variant["model_id"], "seedance-fast-t2v")
        self.assertEqual(image_variant["model_id"], "seedance-fast-i2v")

    def test_dry_run_endpoint_accepts_family_and_returns_resolved_variant(self):
        providers = [{
            "id": "fixture-provider", "name": "Fixture", "protocol": "openai", "enabled": True,
            "image_models": ["fixture-t2i", "fixture-i2i"],
            "chat_models": [], "video_models": [], "audio_models": [],
        }]
        fixture_profile = {
            "provider_id": "fixture-provider",
            "models": [
                {
                    "model_id": "fixture-t2i", "family_id": "fixture-image", "family_name": "Fixture Image",
                    "variant_id": "text_to_image", "node_type": "image_generation", "operation": "text_to_image",
                    "status": "confirmed", "evidence_level": "official_schema", "version": 1,
                    "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
                    "parameters": {"resolution": {"type": "enum", "options": ["1k", "2k"]}},
                    "request_mapping": {"prompt": "input.prompt", "resolution": "settings.resolution"},
                },
                {
                    "model_id": "fixture-i2i", "family_id": "fixture-image", "family_name": "Fixture Image",
                    "variant_id": "image_to_image", "node_type": "image_generation", "operation": "image_to_image",
                    "status": "confirmed", "evidence_level": "official_schema", "version": 1,
                    "inputs": {
                        "prompt": {"media_type": "text", "min": 1, "max": 1},
                        "reference": {"media_type": "image", "min": 1, "max": 1},
                    },
                    "parameters": {"resolution": {"type": "enum", "options": ["1k", "2k"]}},
                    "request_mapping": {"prompt": "input.prompt", "reference": "input.image", "resolution": "settings.resolution"},
                },
            ],
        }
        registry = main.MODEL_CAPABILITY_REGISTRY
        payload = main.ModelCapabilityDryRunRequest(
            provider_id="fixture-provider",
            family_id="fixture-image",
            node_type="image_generation",
            inputs={"prompt": "测试", "reference": "asset://image-1"},
            input_counts={"text": 1, "image": 1},
            parameters={"resolution": "2k"},
        )
        with patch.object(main, "load_api_providers", return_value=providers), patch.object(
            registry, "load", return_value={"registry": {"schema_version": 1}, "profiles": {"fixture-provider": fixture_profile}}
        ):
            result = asyncio.run(main.model_capability_dry_run(payload))

        self.assertEqual(result["standard_request"]["family_id"], "fixture-image")
        self.assertEqual(result["standard_request"]["variant_id"], "image_to_image")
        self.assertEqual(result["standard_request"]["model_id"], "fixture-i2i")
        self.assertEqual(result["platform_request"]["input"]["image"], "asset://image-1")
        self.assertFalse(result["network_requested"])

    def test_dry_run_keeps_explicit_input_roles_in_standard_request(self):
        profile = {
            "provider_id": "fixture", "model_id": "video-v1", "family_id": "video-family",
            "variant_id": "first_frame", "node_type": "video_generation",
            "operation": "image_to_video", "version": 1, "validation_mode": "strict",
            "readiness": "ready", "runnable": True,
            "inputs": {
                "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
                "first_frame": {"media_type": "image", "min": 1, "max": 1, "role": "first_frame"},
            },
            "parameters": {}, "request_mapping": {"prompt": "prompt", "first_frame": "image"},
        }

        result = main.MODEL_CAPABILITY_REGISTRY.build_dry_run(
            profile,
            inputs={"prompt": "测试", "first_frame": "asset://image-1"},
            parameters={},
            input_roles={"first_frame": 1},
        )

        self.assertEqual(result["standard_request"]["input_roles"], {"first_frame": 1})
        self.assertFalse(result["network_requested"])

    def test_generation_request_resolves_family_instead_of_trusting_stale_model_id(self):
        providers = [{
            "id": "fixture-provider", "name": "Fixture", "protocol": "openai", "enabled": True,
            "image_models": ["fixture-t2i", "fixture-i2i"],
            "chat_models": [], "video_models": [], "audio_models": [],
        }]
        fixture_profile = {
            "provider_id": "fixture-provider",
            "models": [
                {
                    "model_id": "fixture-t2i", "family_id": "fixture-image", "variant_id": "text_to_image",
                    "node_type": "image_generation", "operation": "text_to_image", "status": "confirmed",
                    "evidence_level": "official_schema", "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
                    "parameters": {}, "request_mapping": {"prompt": "prompt"},
                },
                {
                    "model_id": "fixture-i2i", "family_id": "fixture-image", "variant_id": "image_to_image",
                    "node_type": "image_generation", "operation": "image_to_image", "status": "confirmed",
                    "evidence_level": "official_schema", "inputs": {
                        "prompt": {"media_type": "text", "min": 1, "max": 1},
                        "reference": {"media_type": "image", "min": 1, "max": 1},
                    },
                    "parameters": {}, "request_mapping": {"prompt": "prompt", "reference": "image"},
                },
            ],
        }
        registry = main.MODEL_CAPABILITY_REGISTRY
        with patch.object(registry, "load", return_value={"registry": {"schema_version": 1}, "profiles": {"fixture-provider": fixture_profile}}):
            profile = main.resolve_model_capability_request(
                "fixture-provider", "fixture-t2i", "fixture-image", "image_generation",
                input_counts={"text": 1, "image": 1}, parameters={}, providers=providers,
            )

        self.assertEqual(profile["model_id"], "fixture-i2i")

    def test_generation_payloads_expose_family_identity_for_backend_recheck(self):
        self.assertEqual(main.OnlineImageRequest(prompt="测试").family_id, "")
        self.assertEqual(main.CanvasVideoRequest(prompt="测试").family_id, "")
        self.assertEqual(main.CanvasAudioRequest(prompt="测试").family_id, "")
        self.assertEqual(main.CanvasLLMRequest(message="测试").family_id, "")

    def test_standard_request_dry_run_maps_fields_without_network(self):
        profile = {
            "provider_id": "fixture", "model_id": "image-v1", "family_id": "image-family",
            "variant_id": "text_to_image", "node_type": "image_generation",
            "operation": "text_to_image", "version": 2, "validation_mode": "strict",
            "readiness": "ready", "runnable": True,
            "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1}},
            "parameters": {"resolution": {"type": "enum", "options": ["1k", "2k"]}},
            "request_mapping": {"prompt": "input.prompt", "resolution": "settings.resolution"},
        }
        result = main.MODEL_CAPABILITY_REGISTRY.build_dry_run(
            profile,
            inputs={"prompt": "测试"},
            parameters={"resolution": "2k"},
        )
        self.assertEqual(result["standard_request"]["family_id"], "image-family")
        self.assertEqual(result["platform_request"], {"input": {"prompt": "测试"}, "settings": {"resolution": "2k"}})
        self.assertFalse(result["network_requested"])

    def test_frontend_drops_parameters_not_declared_by_strict_profile(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const profile={validation_mode:'strict',parameters:{resolution:{type:'enum',options:['1k','2k']},count:{type:'integer'}}};
console.log(JSON.stringify(c.effectiveParameters(profile,{resolution:'2k',count:2,quality:'high'})));
"""

        self.assertEqual(run_node(source), {"resolution": "2k", "count": 2})

    def test_frontend_rejects_invalid_strict_parameters_instead_of_normalizing(self):
        """新契约：非法值被拒绝并报出，不再取整、裁剪或做字符串 truthy 转换（§1.3、C07/C09）。"""
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const profile={validation_mode:'strict',parameters:{
  resolution:{type:'enum',options:['1k','2k']},
  count:{type:'integer',min:1,max:4},
  generate_audio:{type:'boolean'}
}};
const values={resolution:'8k',count:9,generate_audio:'true'};
console.log(JSON.stringify({effective:c.effectiveParameters(profile,values),issues:c.parameterIssues(profile,values)}));
"""
        result = run_node(source)
        self.assertEqual(result["effective"], {}, "非法值不得被裁剪或强转后提交")
        self.assertEqual(result["issues"], {
            "resolution": "PARAM_INVALID",
            "count": "PARAM_INVALID",
            "generate_audio": "PARAM_INVALID",
        }, "每个非法字段都必须被明确报出，供界面标红与运行前阻断")

    def test_frontend_keeps_legal_strict_parameter_values_unchanged(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const profile={validation_mode:'strict',parameters:{
  resolution:{type:'enum',options:['1k','2k','native1080p']},
  count:{type:'integer',min:1,max:4},
  generate_audio:{type:'boolean'}
}};
console.log(JSON.stringify(c.effectiveParameters(profile,{resolution:'native1080p',count:4,generate_audio:false})));
"""
        self.assertEqual(run_node(source), {
            "resolution": "native1080p",
            "count": 4,
            "generate_audio": False,
        }, "合法值必须原样通过，false 与真实枚举值不得被改写")

    def test_frontend_builds_traceable_capability_snapshot(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const profile={
  provider_id:'runninghub', capability_provider_id:'runninghub', model_id:'rh-image',
  node_type:'image_generation', operation:'text_to_image', version:3,
  validation_mode:'strict', evidence_level:'official_schema',
  parameters:{resolution:{type:'enum',options:['1k','2k']},count:{type:'integer',min:1,max:4}},
  request_mapping:{prompt:'prompt',resolution:'resolution',count:'n'}
};
console.log(JSON.stringify(c.capabilitySnapshot(profile,{text:1,image:0},{resolution:'2k',count:2,quality:'high'})));
"""

        self.assertEqual(run_node(source), {
            "provider_id": "runninghub",
            "capability_provider_id": "runninghub",
            "family_id": "rh-image",
            "variant_id": "text_to_image",
            "model_id": "rh-image",
            "node_type": "image_generation",
            "operation": "text_to_image",
            "profile_version": 3,
            "validation_mode": "strict",
            "evidence_level": "official_schema",
            "input_counts": {"text": 1, "image": 0},
            "effective_parameters": {"resolution": "2k", "count": 2},
            "omitted_parameters": {"quality": "high"},
            "request_mapping": {"prompt": "prompt", "resolution": "resolution", "count": "n"},
        })

    def test_frontend_keeps_family_visible_when_multiple_variants_match(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const catalog={providers:[{id:'fixture',name:'Fixture',families:[{
  family_id:'seedance-2.5',display_name:'Seedance 2.5',node_type:'video_generation',variants:[
    {model_id:'seedance-2.5-fast-t2v',variant_id:'fast',operation:'text_to_video',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1}}},
    {model_id:'seedance-2.5-standard-t2v',variant_id:'standard',operation:'text_to_video',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1}}}
  ]
}]}]};
console.log(JSON.stringify(c.familiesForInputs(catalog,'video_generation',{text:1},'fixture')));
"""

        families = run_node(source)
        self.assertEqual(len(families), 1)
        self.assertEqual(families[0]["family_id"], "seedance-2.5")
        self.assertEqual(len(families[0]["compatible_variants"]), 2)
        self.assertIsNone(families[0]["resolved_variant"])

    def test_frontend_resolves_explicit_family_variant(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const family={variants:[
  {model_id:'seedance-2.5-fast-t2v',variant_id:'fast',operation:'text_to_video',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1}}},
  {model_id:'seedance-2.5-standard-t2v',variant_id:'standard',operation:'text_to_video',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1}}}
]};
console.log(JSON.stringify(c.resolveFamilyVariant(family,{text:1},'standard')));
"""

        variant = run_node(source)
        self.assertEqual(variant["model_id"], "seedance-2.5-standard-t2v")

    def test_generic_image_reference_can_match_specialized_frame_role(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const model={validation_mode:'strict',readiness:'ready',runnable:true,inputs:{
  prompt:{media_type:'text',min:1,max:1,role:'prompt'},
  first_frame:{media_type:'image',min:1,max:1,role:'first_frame'},
  last_frame:{media_type:'image',min:0,max:1,role:'last_frame'}
}};
console.log(JSON.stringify(c.modelSupportsInputs(model,{text:1,image:1},{prompt:1,reference:1})));
"""

        self.assertTrue(run_node(source))

    def test_reference_platforms_have_local_configuration_entries(self):
        providers = {item["id"]: item for item in main.default_api_providers()}

        self.assertNotIn("agnes", providers)
        self.assertIn("openai-compatible", providers)
        self.assertFalse(providers["openai-compatible"]["enabled"])

    def test_optional_reference_platforms_are_not_restored_for_existing_config(self):
        providers = main.merge_default_api_providers([{
            "id": "custom",
            "name": "Custom",
            "base_url": "https://example.com/v1",
            "protocol": "openai",
        }], inject_missing=False)
        provider_ids = {item["id"] for item in providers}

        self.assertNotIn("agnes", provider_ids)
        self.assertIn("openai-compatible", provider_ids)

    def test_existing_agnes_configuration_is_preserved_and_normalized(self):
        providers = main.merge_default_api_providers([{
            "id": "agnes",
            "name": "Agnes AI",
            "api_key": "configured",
            "enabled": True,
        }], inject_missing=False)
        agnes = next(item for item in providers if item["id"] == "agnes")

        self.assertTrue(agnes["enabled"])
        self.assertEqual(agnes["base_url"], "https://apihub.agnes-ai.com/v1")
        self.assertEqual(agnes["protocol"], "openai")
        self.assertEqual(agnes["image_request_mode"], "openai-json")

    def test_agnes_models_have_verified_node_capabilities(self):
        chat = dynamic_profile_for_model("agnes", "agnes-2.0-flash", "text_generation")
        image = dynamic_profile_for_model("agnes", "agnes-image-2.1-flash", "image_generation")
        video = dynamic_profile_for_model("agnes", "agnes-video-v2.0", "video_generation")

        self.assertEqual(chat["operation"], "chat")
        self.assertEqual(image["operation"], "text_or_image_to_image")
        self.assertEqual(image["inputs"]["reference"]["max"], 4)
        self.assertEqual(video["operation"], "text_or_image_to_video")
        self.assertEqual(video["inputs"]["reference"]["max"], 4)
        self.assertEqual(video["parameters"]["duration"]["max"], 18)
        self.assertEqual(video["parameters"]["resolution"]["options"], ["480p", "720p", "1080p"])
        self.assertEqual(video["request_mapping"]["frame_rate"], "frame_rate")
        self.assertTrue(all(profile["readiness"] == "ready" for profile in (chat, image, video)))

    def test_reference_audio_models_have_verified_capabilities(self):
        qwen = ai_money_profile_from_model_id("qwen3-tts-instruct-flash", "audio_generation")
        music = ai_money_profile_from_model_id("minimax-music-2.6", "music_generation")
        speech = ai_money_profile_from_model_id("minimax-speech-2.8-hd", "audio_generation")
        clone = ai_money_profile_from_model_id("minimax-voice-clone", "audio_generation")

        self.assertEqual(qwen["family_id"], "ai-money-qwen3-tts")
        self.assertIn("instructions", qwen["parameters"])
        self.assertEqual(music["parameters"]["bitrate"]["options"], ["32000", "64000", "128000", "256000"])
        with self.assertRaises(main.ModelCapabilityError):
            ai_money_profile_from_model_id("minimax-music-2.6", "audio_generation")
        with self.assertRaises(main.ModelCapabilityError):
            ai_money_profile_from_model_id("minimax-speech-2.8-hd", "music_generation")
        self.assertEqual(speech["parameters"]["speed"]["min"], 0.5)
        self.assertEqual(clone["inputs"]["reference_audio"]["min"], 1)
        self.assertEqual(clone["output"]["media_type"], "text")
        self.assertTrue(all(profile["readiness"] == "ready" for profile in (qwen, music, speech, clone)))

    def test_enabled_agnes_models_enter_matching_canvas_nodes(self):
        providers = [{
            "id": "agnes", "name": "Agnes AI", "protocol": "openai", "enabled": True,
            "base_url": "https://apihub.agnes-ai.com/v1",
            "chat_models": ["agnes-2.0-flash"],
            "image_models": ["agnes-image-2.1-flash"],
            "video_models": ["agnes-video-v2.0"],
            "audio_models": [],
        }]

        catalog = main.build_model_capability_catalog(providers)
        models = catalog["providers"][0]["models"]

        self.assertEqual(
            {(model["model_id"], model["node_type"]) for model in models if model["runnable"]},
            {
                ("agnes-2.0-flash", "text_generation"),
                ("agnes-image-2.1-flash", "image_generation"),
                ("agnes-video-v2.0", "video_generation"),
            },
        )

    def test_same_model_id_keeps_separate_text_and_image_capabilities(self):
        providers = [{
            "id": "gemini-cli", "name": "Antigravity CLI", "protocol": "gemini-cli", "enabled": True,
            "chat_models": ["auto"], "image_models": ["auto"], "video_models": [], "audio_models": [],
        }]

        catalog = main.build_model_capability_catalog(providers)
        provider = catalog["providers"][0]

        self.assertEqual(
            {(model["model_id"], model["node_type"]) for model in provider["models"] if model["runnable"]},
            {("auto", "text_generation"), ("auto", "image_generation")},
        )
        self.assertEqual(
            {(family["family_id"], family["node_type"]) for family in provider["families"]},
            {("gemini-cli-auto", "text_generation"), ("gemini-cli-auto", "image_generation")},
        )

    async def test_agnes_video_uses_capability_parameters_in_submit_body(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"video_url": "https://cdn.example.com/agnes.mp4"}

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def post(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return FakeResponse()

        client = FakeClient()
        payload = main.CanvasVideoRequest(
            prompt="测试视频",
            provider_id="agnes",
            model="agnes-video-v2.0",
            duration=5,
            aspect_ratio="16:9",
            resolution="720p",
        )
        provider = {"id": "agnes", "name": "Agnes AI", "base_url": "https://apihub.agnes-ai.com/v1"}

        with (
            patch.object(main, "provider_env_key_value", return_value="sk-test"),
            patch.object(main, "save_remote_video_to_output", new=AsyncMock(side_effect=lambda value: value)),
        ):
            await main.generate_agnes_video(
                client,
                payload,
                provider,
                "https://apihub.agnes-ai.com",
                "agnes-video-v2.0",
                {"duration": 2, "aspect_ratio": "9:16", "resolution": "480p", "frame_rate": 8, "seed": 7},
            )

        self.assertEqual(client.calls[0][0], "https://apihub.agnes-ai.com/v1/videos")
        self.assertEqual(client.calls[0][1]["json"], {
            "model": "agnes-video-v2.0",
            "prompt": "测试视频",
            "width": 408,
            "height": 720,
            "num_frames": 17,
            "frame_rate": 8,
            "seed": 7,
        })

    def test_ai_money_seedance_variants_share_reference_family_and_parameters(self):
        text_profile = ai_money_profile_from_model_id("seedance-2.5-standard-t2v", "video_generation")
        image_profile = ai_money_profile_from_model_id("seedance-2.5-standard-i2v", "video_generation")
        multi_profile = ai_money_profile_from_model_id("seedance-2.5-standard-multi", "video_generation")

        self.assertEqual(text_profile["family_id"], "ai-money-seedance-2-5")
        self.assertEqual(image_profile["family_id"], text_profile["family_id"])
        self.assertEqual(multi_profile["family_id"], text_profile["family_id"])
        self.assertEqual(text_profile["parameters"]["duration"]["options"], [-1, *range(4, 31)])
        self.assertIn("native1080p", text_profile["parameters"]["resolution"]["options"])
        self.assertNotIn("native4k", text_profile["parameters"]["resolution"]["options"])
        self.assertEqual(image_profile["parameters"]["resolution"]["options"], text_profile["parameters"]["resolution"]["options"])
        self.assertEqual(multi_profile["inputs"]["reference"]["max"], 30)
        self.assertEqual(multi_profile["inputs"]["source_video"]["max"], 10)
        self.assertEqual(multi_profile["inputs"]["reference_audio"]["max"], 10)

    def test_ai_money_wan_3_prime_models_use_documented_inputs_and_parameters(self):
        domestic_i2v = ai_money_profile_from_model_id("wan-3.0-prime-i2v", "video_generation")
        domestic_r2v = ai_money_profile_from_model_id("wan-3.0-prime-r2v", "video_generation")
        global_i2v = ai_money_profile_from_model_id("wan-3.0-global-prime-i2v", "video_generation")
        global_r2v = ai_money_profile_from_model_id("wan-3.0-global-prime-r2v", "video_generation")
        profiles = (domestic_i2v, domestic_r2v, global_i2v, global_r2v)

        self.assertEqual({item["family_id"] for item in profiles}, {"ai-money-wan-3-0"})
        self.assertEqual({item["family_name"] for item in profiles}, {"Wan 3.0"})
        self.assertEqual(domestic_i2v["operation"], "image_to_video")
        self.assertEqual(domestic_r2v["operation"], "reference_to_video")
        self.assertEqual(global_i2v["inputs"]["first_frame"]["min"], 1)
        self.assertEqual(global_i2v["inputs"]["last_frame"]["min"], 0)
        self.assertEqual(global_i2v["inputs"]["last_frame"]["max"], 1)
        self.assertEqual(domestic_r2v["inputs"]["reference"]["max"], 10)
        self.assertEqual(domestic_r2v["inputs"]["source_video"]["max"], 5)
        self.assertEqual(domestic_r2v["inputs"]["reference_audio"]["max"], 5)
        self.assertTrue(all(item["inputs"]["prompt"]["max_chars"] == 20000 for item in profiles))

        parameters = domestic_r2v["parameters"]
        self.assertEqual(parameters["duration"]["options"], [-1, *range(2, 31)])
        self.assertEqual(parameters["resolution"]["options"], ["480p", "720p", "1080p"])
        self.assertEqual(parameters["aspect_ratio"]["options"], ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16"])
        self.assertTrue(parameters["generate_audio"]["default"])
        self.assertEqual(parameters["seed"]["max"], 2147483647)
        self.assertNotIn("enable_thinking", global_i2v["parameters"])
        self.assertNotIn("return_last_frame", global_r2v["parameters"])
        self.assertEqual(domestic_r2v["request_mapping"]["reference"], "metadata.content")
        self.assertEqual(domestic_r2v["request_mapping"]["source_video"], "metadata.content")
        self.assertEqual(domestic_r2v["request_mapping"]["reference_audio"], "metadata.content")
        self.assertTrue(all(item["platform"]["endpoint"] == "/v1/videos" for item in profiles))

    def test_wan_3_prime_prompt_reaches_its_20000_character_model_limit(self):
        payload = main.CanvasVideoRequest(
            provider_id="ai-money",
            model="wan-3.0-prime-i2v",
            prompt="字" * 20000,
        )
        profile = ai_money_profile_from_model_id(payload.model, "video_generation")

        main.validate_canvas_video_prompt(profile, payload.prompt)
        self.assertEqual(len(payload.prompt), 20000)

    def test_ai_money_wan_3_reference_video_preflight_requires_any_reference_media(self):
        providers = [{
            "id": "ai-money",
            "name": "AI MONEY",
            "enabled": True,
            "video_models": ["wan-3.0-prime-r2v"],
        }]

        with self.assertRaises(ModelCapabilityError):
            main.MODEL_CAPABILITY_REGISTRY.validate_request(
                providers,
                "ai-money",
                "wan-3.0-prime-r2v",
                "video_generation",
                input_counts={"prompt": 1, "image": 0, "video": 0, "audio": 0},
            )

        profile = main.MODEL_CAPABILITY_REGISTRY.validate_request(
            providers,
            "ai-money",
            "wan-3.0-prime-r2v",
            "video_generation",
            input_counts={"prompt": 1, "image": 0, "video": 1, "audio": 0},
        )
        self.assertEqual(profile["model_id"], "wan-3.0-prime-r2v")

    def test_ai_money_fashvsr_profile_requires_a_480p_video_only(self):
        profile = ai_money_profile_from_model_id("FashVSR_video_upscale", "video_generation")

        self.assertEqual(profile["family_id"], "ai-money-fashvsr")
        self.assertEqual(profile["family_name"], "FashVSR")
        self.assertEqual(profile["operation"], "video_upscale")
        self.assertEqual(set(profile["inputs"]), {"source_video"})
        self.assertEqual(profile["inputs"]["source_video"]["min_duration_seconds"], 3)
        self.assertEqual(profile["inputs"]["source_video"]["max_duration_seconds"], 15)
        self.assertEqual(profile["request_mapping"]["source_video"], "metadata.video_url")
        self.assertEqual(profile["platform"]["endpoint"], "/v1/video/generations")
        self.assertEqual(profile["parameters"], {})

        catalog = main.MODEL_CAPABILITY_REGISTRY.build_catalog([{
            "id": "ai-money",
            "name": "AI MONEY",
            "video_models": ["FashVSR_video_upscale"],
        }])
        family = catalog["providers"][0]["families"][0]
        self.assertEqual(family["family_id"], "ai-money-fashvsr")
        self.assertEqual(family["display_name"], "FashVSR")
        self.assertEqual(family["variants"][0]["variant_name"], "视频放大")

    def test_ai_money_minimax_h3_ow_uses_documented_input_and_parameter_limits(self):
        t2v = ai_money_profile_from_model_id("minimax-h3-ow-t2v", "video_generation")
        i2v_fast = ai_money_profile_from_model_id("minimax-h3-ow-i2v-fast", "video_generation")
        audio_drive = ai_money_profile_from_model_id("minimax-h3-ow-fl2va-audio-drive-fast", "video_generation")

        self.assertEqual(t2v["parameters"]["duration"]["options"], [5, 10, 15])
        self.assertEqual(t2v["parameters"]["resolution"]["options"], ["480p", "720p"])
        self.assertEqual(t2v["parameters"]["aspect_ratio"]["options"], ["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"])
        self.assertEqual(i2v_fast["inputs"]["first_frame"]["max"], 1)
        self.assertEqual(audio_drive["inputs"]["first_frame"]["max"], 1)
        self.assertEqual(audio_drive["inputs"]["reference_audio"]["max"], 1)

    def test_ai_money_branded_image_variants_share_reference_family(self):
        text_profile = ai_money_profile_from_model_id("laohuaimoney-image-g2-t2i", "image_generation")
        image_profile = ai_money_profile_from_model_id("laohuaimoney-image-g2-i2i", "image_generation")

        self.assertEqual(text_profile["family_id"], "ai-money-gpt-image-2")
        self.assertEqual(image_profile["family_id"], text_profile["family_id"])
        self.assertNotIn("reference", text_profile["inputs"])
        self.assertEqual(image_profile["inputs"]["reference"]["max"], 10)

    def test_frontend_snapshot_keeps_omitted_parameters_separate_from_effective_values(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const profile={validation_mode:'strict',version:2,provider_id:'rh',model_id:'t2i',node_type:'image_generation',parameters:{resolution:{type:'enum',options:['1k','2k']}}};
console.log(JSON.stringify(c.capabilitySnapshot(profile,{text:1},{resolution:'1k',aspect_ratio:'1:1'})));
"""
        data = run_node(source)
        self.assertEqual(data["effective_parameters"], {"resolution": "1k"})
        self.assertEqual(data["omitted_parameters"], {"aspect_ratio": "1:1"})

    def test_video_runtime_filters_legacy_flags_for_strict_profiles(self):
        source = (ROOT / "static" / "js" / "smart-canvas.js").read_text(encoding="utf-8")
        capability_source = (ROOT / "static" / "js" / "smart-model-capabilities.js").read_text(encoding="utf-8")

        self.assertIn("SmartModelCapabilities.buildVideoRequest(profile", source)
        self.assertIn("function buildVideoRequest(profile", capability_source)
        self.assertIn("enhance_prompt:strict ? undefined", capability_source)
        self.assertIn("enable_upsample:strict ? undefined", capability_source)
        self.assertIn("multimodal:base.multimodal !== undefined", capability_source)

    def test_runtime_catalog_uses_api_settings_as_the_only_visibility_filter(self):
        providers = [{
            "id": "ai-money",
            "name": "AI MONEY",
            "protocol": "openai",
            "enabled": True,
            "image_models": [],
            "chat_models": [],
            "video_models": [],
            "audio_models": ["doubao-seed-audio-1.0", "mureka-v8-bgm", "custom-audio"],
        }]

        catalog = main.build_model_capability_catalog(providers)
        model_ids = [item["model_id"] for item in catalog["providers"][0]["models"]]

        self.assertEqual(model_ids, ["doubao-seed-audio-1.0", "custom-audio", "mureka-v8-bgm"])

    def test_frontend_builds_strict_video_request_from_declared_parameters_only(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const profile={validation_mode:'strict',parameters:{
  duration:{type:'integer',min:1,max:10},
  aspect_ratio:{type:'enum',options:['16:9','9:16']},
  generate_audio:{type:'boolean'}
}};
console.log(JSON.stringify(c.buildVideoRequest(profile,{
  prompt:'测试',provider_id:'jimeng',model:'seedance2.0',
  images:[{url:'/assets/a.png'}],videos:[],audios:[],multimodal:true,trusted_asset:false
},{
  duration:8,aspect_ratio:'16:9',resolution:'4k',generate_audio:true,
  enhance_prompt:true,enable_upsample:true,watermark:true,camerafixed:true,multimodal:true
})));
"""

        # 只有档案声明的参数进入请求：未声明的 resolution/enhance_prompt 等被丢弃；
        # 越界值在新契约下被拒绝而不是裁剪。见 test_model_input_evaluation.py。
        self.assertEqual(run_node(source), {
            "prompt": "测试",
            "provider_id": "jimeng",
            "model": "seedance2.0",
            "images": [{"url": "/assets/a.png"}],
            "videos": [],
            "audios": [],
            "multimodal": True,
            "trusted_asset": False,
            "duration": 8,
            "aspect_ratio": "16:9",
            "generate_audio": True,
        })

    def test_frontend_filters_model_candidates_by_selected_parameter_values(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const catalog={providers:[{id:'p',models:[
  {model_id:'wide-only',node_type:'video_generation',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1}},parameters:{aspect_ratio:{type:'enum',options:['16:9']},duration:{type:'integer',min:4,max:8}}},
  {model_id:'portrait',node_type:'video_generation',validation_mode:'strict',readiness:'ready',runnable:true,inputs:{prompt:{media_type:'text',min:1,max:1}},parameters:{aspect_ratio:{type:'enum',options:['3:4','9:16']},duration:{type:'integer',min:4,max:15}}}
]}]};
console.log(JSON.stringify(c.modelsForVerifiedInputs(catalog,'video_generation',{text:1},{prompt:1},{aspect_ratio:'3:4',duration:12}).map(item=>item.model_id)));
"""

        self.assertEqual(run_node(source), ["portrait"])

    def test_frontend_video_mode_uses_parameters_and_explicit_frame_roles(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
console.log(JSON.stringify({
  mismatch:c.resolveVideoExecutionMode({imageRefs:[{width:1024,height:1024}],parameters:{aspect_ratio:'3:4'}}),
  matching:c.resolveVideoExecutionMode({imageRefs:[{width:1024,height:1024}],parameters:{aspect_ratio:'1:1'}}),
  frames:c.resolveVideoExecutionMode({imageRefs:[{width:1024,height:1024},{width:1024,height:1024}],useFrameRoles:true,parameters:{duration:4}}),
  multiple:c.resolveVideoExecutionMode({imageRefs:[{width:1024,height:1024},{width:1024,height:1024}],parameters:{duration:4}})
}));
"""

        self.assertEqual(run_node(source), {
            "mismatch": "multimodal2video",
            "matching": "image2video",
            "frames": "frames2video",
            "multiple": "multimodal2video",
        })

    def test_frontend_video_candidates_match_execution_mode_operation(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const catalog={providers:[{id:'p',models:[
  {model_id:'i2v',node_type:'video_generation',operation:'image_to_video',validation_mode:'strict',readiness:'ready',runnable:true,
    inputs:{prompt:{media_type:'text',min:1,max:1},first_frame:{media_type:'image',min:1,max:1}},parameters:{aspect_ratio:{type:'enum',options:['1:1','3:4']}}},
  {model_id:'multi',node_type:'video_generation',operation:'multimodal_to_video',validation_mode:'strict',readiness:'ready',runnable:true,
    inputs:{prompt:{media_type:'text',min:1,max:1},reference:{media_type:'image',min:0,max:10}},parameters:{aspect_ratio:{type:'enum',options:['1:1','3:4']}}}
]}]};
console.log(JSON.stringify(c.modelsForVerifiedInputs(catalog,'video_generation',{text:1,image:1},{prompt:1,reference:1},{aspect_ratio:'3:4',__execution_mode:'multimodal2video'}).map(item=>item.model_id)));
"""

        self.assertEqual(run_node(source), ["multi"])

    def test_jimeng_multi_command_models_remain_visible_for_each_supported_video_mode(self):
        provider = next(item for item in main.load_api_providers() if item.get("id") == "jimeng")
        catalog = main.MODEL_CAPABILITY_REGISTRY.build_catalog([provider])
        source = f"""
const c=require('./static/js/smart-model-capabilities.js');
const catalog={json.dumps(catalog, ensure_ascii=False)};
const cases={{
  text:c.familiesForInputs(catalog,'video_generation',{{text:1,image:0,video:0,audio:0}},'jimeng','',{{prompt:1}},{{__execution_mode:'text2video'}}),
  image:c.familiesForInputs(catalog,'video_generation',{{text:1,image:1,video:0,audio:0}},'jimeng','',{{prompt:1,reference:1}},{{__execution_mode:'image2video'}}),
  frames:c.familiesForInputs(catalog,'video_generation',{{text:1,image:2,video:0,audio:0}},'jimeng','',{{prompt:1,first_frame:1,last_frame:1}},{{__execution_mode:'frames2video'}}),
  multimodal:c.familiesForInputs(catalog,'video_generation',{{text:1,image:1,video:1,audio:0}},'jimeng','',{{prompt:1,reference:1,source_video:1}},{{__execution_mode:'multimodal2video'}})
}};
console.log(JSON.stringify(Object.fromEntries(Object.entries(cases).map(([key,families]) => [key,
  Object.fromEntries(families.map(family => [family.family_id, family.compatible_variants.map(variant => variant.model_id)]))
]))));
"""

        expected = {
            "jimeng-seedance-2.5": ["seedance2.5"],
            "jimeng-seedance-2.0": [
                "seedance2.0fast_vip",
                "seedance2.0_vip",
                "seedance2.0",
                "seedance2.0fast",
                "seedance2.0mini",
            ],
        }
        result = run_node(source)
        self.assertEqual(result["text"], expected)
        self.assertEqual(result["image"], expected)
        self.assertEqual(result["frames"], expected)
        self.assertEqual(result["multimodal"], expected)

    def test_direct_static_canvas_html_uses_current_asset_mtime_and_disables_html_cache(self):
        asset = ROOT / "static" / "js" / "smart-model-capabilities.js"
        expected = (
            "/static/js/smart-model-capabilities.js"
            f"?v={main.current_app_version()}.{asset.stat().st_mtime_ns}"
        )

        response = TestClient(main.app).get("/static/smart-canvas.html")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("cache-control"), "no-cache")
        self.assertIn(expected, response.text)

    def test_release_metadata_and_sidebar_badge_share_root_version(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        notes = json.loads((ROOT / "static/update-notes.json").read_text(encoding="utf-8"))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        index_html = (ROOT / "static/index.html").read_text(encoding="utf-8")

        response = TestClient(main.app).get("/api/app-info")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(main.current_app_version(), version)
        self.assertEqual(response.json().get("version"), version)
        self.assertEqual(notes.get("version"), version)
        self.assertIn(f"当前版本：`v{version}`", readme)
        self.assertIn('id="project-version-badge"', index_html)
        self.assertIn("fetch('/api/app-info', { cache:'no-store' })", index_html)
        self.assertIn("setProjectVersionBadge(current);", index_html)

    def test_startup_does_not_rewrite_tracked_static_html_cache_versions(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        startup = source.split("async def startup_event():", 1)[1].split('@app.websocket("/ws/stats")', 1)[0]

        self.assertNotIn("sync_static_html_versions()", startup)

    def test_frontend_builds_strict_audio_request_with_endpoint_field_names(self):
        source = """
const c=require('./static/js/smart-model-capabilities.js');
const profile={validation_mode:'strict',parameters:{
  format:{type:'enum',options:['mp3','wav']},
  sample_rate:{type:'enum',options:[16000,24000]},
  pitch_rate:{type:'integer',min:-12,max:12}
}};
console.log(JSON.stringify(c.buildAudioRequest(profile,{
  prompt:'测试',provider_id:'ai-money',model:'audio-model',reference_audio:''
},{
  speaker:'voice-a',format:'wav',sample_rate:24000,
  speech_rate:30,loudness_rate:20,pitch_rate:12
})));
"""

        # 未声明的 speaker / speech_rate / loudness_rate 一律不提交；
        # 越界值（如 pitch_rate:99）在新契约下被拒绝而不是裁剪到 12。见 test_model_input_evaluation.py。
        self.assertEqual(run_node(source), {
            "prompt": "测试",
            "provider_id": "ai-money",
            "model": "audio-model",
            "reference_audio": "",
            "audio_format": "wav",
            "sample_rate": 24000,
            "pitch_rate": 12,
        })

    async def test_image_task_validates_confirmed_profile_before_network_request(self):
        provider = {
            "id": "runninghub",
            "name": "RunningHub",
            "protocol": "runninghub",
            "enabled": True,
            "image_models": ["gpt-image-2.0/text-to-image-channel-low-price"],
            "chat_models": [],
            "video_models": [],
        }
        payload = main.OnlineImageRequest(
            provider_id="runninghub",
            model="gpt-image-2.0/text-to-image-channel-low-price",
            prompt="测试",
            reference_images=[main.AIReference(url="/assets/reference.png")],
        )

        with patch.object(main, "load_api_providers", return_value=[provider]), patch.object(main, "get_api_provider", return_value=provider):
            with self.assertRaises(main.HTTPException) as context:
                await main.build_online_image_result(payload)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("不支持图片输入", str(context.exception.detail))

    def test_modelscope_account_binding_error_is_explained_in_chinese(self):
        upstream_error = '{"error":"Please bind your Alibaba Cloud account before use."}'
        detail = main.friendly_image_error_detail(
            upstream_error,
            "1024x1024",
            "Tongyi-MAI/Z-Image-Turbo",
        )

        self.assertIn("ModelScope", detail)
        self.assertIn("绑定阿里云账号", detail)
        self.assertIn("未产生图片结果", detail)

        chat_detail = main.friendly_chat_error_detail(upstream_error, "Qwen/Qwen3-235B-A22B")
        self.assertIn("ModelScope", chat_detail)
        self.assertIn("绑定阿里云账号", chat_detail)
        self.assertIn("未产生结果", chat_detail)

    async def test_video_task_validates_confirmed_profile_before_network_request(self):
        provider = {
            "id": "jimeng",
            "name": "即梦 CLI",
            "protocol": "jimeng",
            "enabled": True,
            "image_models": ["5.0Pro"],
            "chat_models": [],
            "video_models": ["seedance2.0"],
        }
        payload = main.CanvasVideoRequest(
            provider_id="jimeng",
            model="seedance2.0",
            prompt="测试",
            videos=[
                "/assets/reference-1.mp4",
                "/assets/reference-2.mp4",
                "/assets/reference-3.mp4",
                "/assets/reference-4.mp4",
            ],
        )

        with patch.object(main, "load_api_providers", return_value=[provider]), patch.object(main, "get_api_provider", return_value=provider):
            with self.assertRaises(main.HTTPException) as context:
                await main.canvas_video(payload)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("最多接收 3 个视频输入", str(context.exception.detail))

    async def test_audio_task_rejects_incompatible_inputs_before_network_request(self):
        provider = {
            "id": "ai-money",
            "name": "AI MONEY",
            "protocol": "openai",
            "enabled": True,
            "image_models": [],
            "chat_models": [],
            "video_models": [],
            "audio_models": ["mureka-v8-bgm"],
        }
        payload = main.CanvasAudioRequest(
            provider_id="ai-money",
            model="mureka-v8-bgm",
            prompt="测试",
            reference_audio="/assets/reference.mp3",
        )
        generate = AsyncMock()

        with patch.object(main, "load_api_providers", return_value=[provider]), \
                patch.object(main, "get_api_provider", return_value=provider), \
                patch.object(main, "generate_ai_money_audio", generate):
            with self.assertRaises(main.HTTPException) as context:
                await main.canvas_music(payload)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("不支持音频输入", str(context.exception.detail))
        generate.assert_not_awaited()

    def test_video_capability_parameters_only_include_explicit_request_fields(self):
        payload = main.CanvasVideoRequest(
            provider_id="jimeng",
            model="seedance2.0",
            prompt="测试",
            generate_audio=True,
        )

        self.assertEqual(main.canvas_video_capability_parameters(payload), {"generate_audio": True})

    def test_audio_capability_parameters_only_include_explicit_request_fields(self):
        payload = main.CanvasAudioRequest(
            provider_id="ai-money",
            model="doubao-seed-audio-1.0",
            prompt="测试",
            audio_format="wav",
        )

        self.assertEqual(main.canvas_audio_capability_parameters(payload), {"format": "wav"})

    def test_smart_canvas_loads_capability_runtime_before_main_script(self):
        html = (ROOT / "static" / "smart-canvas.html").read_text(encoding="utf-8")

        capability_index = html.index("/static/js/smart-model-capabilities.js")
        canvas_index = html.index("/static/js/smart-canvas.js")
        self.assertLess(capability_index, canvas_index)

    def test_smart_canvas_uses_family_selection_without_unknown_model_fallback(self):
        script = (ROOT / "static" / "js" / "smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("function capabilityFamiliesForProvider", script)
        self.assertIn("function resolveCapabilityFamilySelection", script)
        self.assertIn("settings.imageFamilyId", script)
        self.assertIn("settings.videoFamilyId", script)
        self.assertIn("settings.audioFamilyId", script)
        self.assertIn("settings.textFamilyId", script)
        self.assertNotIn("validation_mode:'compatible', node_type:nodeType", script)


if __name__ == "__main__":
    unittest.main()
