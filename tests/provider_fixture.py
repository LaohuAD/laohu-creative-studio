"""能力回归使用公开档案构造启用清单，不读取维护者的模型配置或密钥。"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def configured_providers():
    fields = {
        'text_generation': 'chat_models', 'image_generation': 'image_models',
        'video_generation': 'video_models', 'audio_generation': 'audio_models',
        'music_generation': 'audio_models',
    }
    providers = []
    for name, provider_id, protocol in (
        ('ai-money', 'ai-money', 'openai'), ('modelscope', 'modelscope', 'openai'),
        ('codex-cli', 'codex', 'codex'), ('jimeng-cli', 'jimeng', 'jimeng'),
        ('runninghub', 'runninghub', 'runninghub'),
    ):
        data = json.loads((ROOT / f'data/model_capabilities/providers/{name}.json').read_text(encoding='utf-8'))
        provider = dict(id=provider_id, name=provider_id, protocol=protocol, enabled=True,
                        base_url='https://example.invalid', rh_region='global')
        provider.update({field: [] for field in set(fields.values())})
        for model in data['models']:
            field = fields.get(model.get('node_type'))
            if field and model['model_id'] not in provider[field]:
                provider[field].append(model['model_id'])
        if provider_id == 'ai-money':
            catalog = json.loads((ROOT / 'data/model_capabilities/snapshots/ai-money-catalog.json').read_text(encoding='utf-8'))
            for field in set(fields.values()):
                provider[field] = list(dict.fromkeys(provider[field] + catalog.get(field, [])))
        if provider_id == 'jimeng':
            provider['image_models'] = ['5.0Pro', '5.0', '4.7', '4.6', '4.5', '4.1', '4.0', '3.1', '3.0']
            provider['video_models'] = ['seedance2.5', 'seedance2.0fast_vip', 'seedance2.0_vip', 'seedance2.0', 'seedance2.0fast', 'seedance2.0mini']
        providers.append(provider)
    return providers


class ConfiguredProvidersMixin:
    def setUp(self):
        super().setUp()
        import main
        replacement = patch.object(main, 'load_api_providers', side_effect=configured_providers)
        replacement.start()
        self.addCleanup(replacement.stop)

        # 成功的模拟生图会走到 save_to_history；所有使用该 fixture 的测试
        # 都把这条间接写入链指向外接盘测试缓存，避免污染用户历史。
        history_cache = ROOT / 'cache' / 'studio-tests'
        history_cache.mkdir(parents=True, exist_ok=True)
        self._history_tempdir = tempfile.TemporaryDirectory(
            prefix='provider-test-history-', dir=history_cache,
        )
        self.history_file = Path(self._history_tempdir.name) / 'data' / 'history.json'
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._history_tempdir.cleanup)
        history_patch = patch.object(main, 'HISTORY_FILE', str(self.history_file))
        history_patch.start()
        self.addCleanup(history_patch.stop)
