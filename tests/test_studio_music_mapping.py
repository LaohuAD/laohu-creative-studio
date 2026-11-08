"""音乐字段只能按精确模型契约进入共享执行器。"""
from __future__ import annotations

import asyncio
import copy
import unittest

import main
from fastapi import HTTPException
from canvas_core.hypit_config import prepare_hypit_task_canvas
from provider_fixture import ConfiguredProvidersMixin


class StudioMusicMappingTests(ConfiguredProvidersMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.canvas = {
                "id": main.MUSIC_SETTINGS_CANVAS_ID,
            "nodes": [{
                "id": "music-source", "type": "smart-music-generator",
                "runSettings": {"musicProvider": "ai-money", "musicModel": "fixture-music"},
            }, {
                "id": "music-output", "type": "smart-hypit-output", "hypitSlot": "music",
            }],
            "connections": [{"from": "music-source", "to": "music-output", "kind": "flow"}],
        }
        self.plan = {"node_ids": ["music-source"]}

    def _prepare(self, model, snapshot, request=None):
        self.canvas["nodes"][0]["runSettings"]["musicModel"] = model
        return asyncio.run(main.studio_music_prepare_generation_request(
            canvas=self.canvas,
            purpose="song",
            slot="music",
            output_node_id="music-output",
            song={},
            source_snapshot=snapshot,
            request=request or {},
        ))

    def test_bgm_style_is_the_prompt_and_does_not_require_song_style_parameter(self):
        value = self._prepare("mureka-v8-bgm", {
            "lyrics": "", "style_prompt": "舒缓、无歌词的钢琴背景音乐", "notes": "只供用户查看的备注",
        })
        self.assertEqual(value["prompt"], "舒缓、无歌词的钢琴背景音乐")
        self.assertEqual(value["parameters"], {})

    def test_song_maps_lyrics_and_only_explicitly_supported_style_parameter(self):
        value = self._prepare("mureka-v9-song", {
            "lyrics": "沿海风声，灯火渐亮。", "style_prompt": "温暖的民谣", "notes": "不自动拼到生成内容",
        }, {"parameters": {"stream": False}})
        self.assertEqual(value["prompt"], "沿海风声，灯火渐亮。")
        self.assertEqual(value["parameters"], {"style_prompt": "温暖的民谣", "stream": False})
        self.assertNotIn("notes", value["parameters"])

    def test_suno_saved_lyrics_use_custom_mode_and_the_style_parameter(self):
        value = self._prepare("suno-generation", {
            "title": "归人", "lyrics": "[Verse]\n归人过桥。", "style_prompt": "古琴、女声",
            "notes": "不应进入歌词或风格的创作说明",
        })
        self.assertEqual(value["prompt"], "[Verse]\n归人过桥。")
        self.assertEqual(value["parameters"], {
            "title": "归人", "style": "古琴、女声", "custom": True, "instrumental": False,
        })
        body = main.ai_money_suno_request_body("suno-generation", value["prompt"], value["parameters"])
        self.assertEqual(body["prompt"], "[Verse]\n归人过桥。")
        self.assertEqual(body["style"], "古琴、女声")
        self.assertTrue(body["custom"])
        self.assertFalse(body["instrumental"])
        self.assertNotIn("style_prompt", body)
        self.assertNotIn("notes", body)

    def test_suno_lyrics_cannot_be_silently_changed_to_inspiration_or_instrumental(self):
        for parameters in ({"custom": False}, {"instrumental": True}):
            with self.subTest(parameters=parameters), self.assertRaises(HTTPException) as caught:
                self._prepare("suno-generation", {"lyrics": "归人过桥。", "style_prompt": "古琴"},
                              {"parameters": parameters})
            self.assertEqual(caught.exception.status_code, 400)
            self.assertIn("custom=true", str(caught.exception.detail))

    def test_suno_style_still_obeys_the_real_parameter_length_limit(self):
        with self.assertRaises(HTTPException) as caught:
            self._prepare("suno-generation", {"lyrics": "归人过桥。", "style_prompt": "琴" * 1001})
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("style", str(caught.exception.detail))

    def test_bgm_model_still_rejects_song_lyrics(self):
        with self.assertRaises(HTTPException) as caught:
            self._prepare("mureka-v8-bgm", {"lyrics": "归人过桥。", "style_prompt": "钢琴"})
        self.assertEqual(caught.exception.status_code, 400)

    def test_suno_without_lyrics_keeps_the_description_prompt(self):
        value = self._prepare("suno-generation", {"lyrics": "", "style_prompt": "古琴背景音乐"})
        self.assertEqual(value["prompt"], "古琴背景音乐")
        self.assertNotIn("custom", value["parameters"])

    def test_suno_shared_private_graph_keeps_lyrics_style_and_saved_voice(self):
        node = self.canvas["nodes"][0]
        node["runSettings"]["musicModel"] = "suno-generation"
        node["runSettings"]["capabilityParameters"] = {"suno-generation": {
            "version": "v6", "custom": False, "instrumental": False, "vocal_gender": "Female",
            "audio_format": "mp3",
        }}
        node["modelSelection"] = {"option_id": "", "operation": "music", "parameters": {
            "custom": False, "vocal_gender": "Male",
        }}
        before = copy.deepcopy(self.canvas)
        resolved = self._prepare("suno-generation", {
            "title": "归人", "lyrics": "[Verse]\n归人过桥。", "style_prompt": "古琴、女声",
        })
        private = prepare_hypit_task_canvas(
            self.canvas, "music", resolved, "music-output", canvas_id="music-settings", module_id="music",
        )["canvas"]
        request = asyncio.run(main.studio_hypit_prepare_node_request(
            private, private["nodes"][0], "song-test", {}, resolved, preflight=True,
        ))
        self.assertEqual(request["prompt"], "[Verse]\n归人过桥。")
        self.assertEqual(request["parameters"]["style"], "古琴、女声")
        self.assertTrue(request["parameters"]["custom"])
        self.assertFalse(request["parameters"]["instrumental"])
        self.assertEqual(request["parameters"]["vocal_gender"], "Female")
        self.assertEqual(self.canvas, before, "本次歌曲参数只能进入私有图，不能写回共享配置")


if __name__ == "__main__":
    unittest.main()
