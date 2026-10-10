"""音乐字段只能按精确模型契约进入共享执行器。"""
from __future__ import annotations

import asyncio
import unittest

import main
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


if __name__ == "__main__":
    unittest.main()
