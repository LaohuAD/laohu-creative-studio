"""全目录参数契约回归：不读取个人配置，不提交生成任务。"""
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import model_capabilities as mc
import main
from studio_model_evaluation import validate_parameter_value

ROOT = Path(__file__).resolve().parents[1]


def public_profiles():
    registry = mc.ModelCapabilityRegistry(ROOT)
    for provider_id, provider in registry.load()['profiles'].items():
        for profile in provider.get('models', []):
            yield provider_id, 'static', profile
    for region in ('cn', 'global'):
        for profile in registry.runninghub_snapshot_profiles(region).values():
            yield 'runninghub', region, profile
    for profile in registry.runninghub_official_snapshot_profiles().values():
        yield 'runninghub', 'official', profile
    snapshot = json.loads((ROOT / 'data/model_capabilities/snapshots/ai-money-catalog.json').read_text())
    for node_type, field in mc.NODE_MODEL_FIELDS.items():
        for model_id in snapshot.get(field, []):
            profile = mc.dynamic_profile_for_model('ai-money', model_id, node_type)
            if profile:
                yield 'ai-money', 'dynamic', profile


class ParameterContractAuditTests(unittest.TestCase):
    def test_every_declared_enum_and_default_is_valid(self):
        for provider, source, profile in public_profiles():
            for key, spec in profile.get('parameters', {}).items():
                with self.subTest(provider=provider, source=source, model=profile['model_id'], key=key):
                    if spec.get('type') == 'enum':
                        self.assertTrue(spec.get('options'), '固定选项缺失不能用通用值冒充')
                    for value in spec.get('options', []):
                        self.assertIsNone(validate_parameter_value(spec, value))
                    if spec.get('default') is not None:
                        self.assertIsNone(validate_parameter_value(spec, spec['default']), spec)

    def test_jimeng_image_ratio_is_verified_and_mapped(self):
        registry = mc.ModelCapabilityRegistry(ROOT)
        profiles = registry.load()['profiles']['jimeng-cli']['models']
        for profile in profiles:
            if profile['node_type'] != 'image_generation':
                continue
            with self.subTest(model=profile['model_id']):
                self.assertEqual(profile['parameters']['aspect_ratio']['options'],
                                 ['21:9', '16:9', '3:2', '4:3', '1:1', '3:4', '2:3', '9:16'])
                self.assertEqual(profile['request_mapping']['aspect_ratio'], 'ratio')
                self.assertEqual(profile['parameters']['resolution']['options'],
                                 mc.jimeng_image_resolution_options(profile['model_id']))

    def test_all_catalog_choices_and_defaults_pass_frontend_preflight(self):
        profiles = list(public_profiles())
        script = r'''
const c=require('./static/js/smart-model-capabilities.js');
const profiles=JSON.parse(require('fs').readFileSync(0,'utf8'));
const failures=[];
for(const [provider,source,profile] of profiles){
  for(const [key,spec] of Object.entries(profile.parameters || {})){
    const values=[...(spec.options || [])];
    if(spec.default != null) values.push(spec.default);
    for(const value of values){
      if(c.parameterIssue(spec,value) || !c.modelSupportsParameters({...profile,validation_mode:'strict'},{[key]:value}))
        failures.push({provider,source,model:profile.model_id,key,value});
    }
  }
}
console.log(JSON.stringify(failures));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True,
                                text=True, input=json.dumps(profiles))
        self.assertEqual(json.loads(result.stdout), [])

    def test_canvas_choices_never_invent_missing_enum_values(self):
        script = r'''
const fs=require('fs');
const source=fs.readFileSync('static/js/smart-canvas.js','utf8');
const start=source.indexOf('function capabilityParameterControlKind(');
const end=source.indexOf('function renderCapabilityUnsetChoice(',start);
function capabilityParameterSemantic(key){return key;}
eval(source.slice(start,end));
console.log(JSON.stringify({
  emptyRatio:capabilityParameterChoiceOptions('aspect_ratio',{type:'enum'}),
  emptyResolution:capabilityParameterChoiceOptions('resolution',{type:'enum',options:[]}),
  fixed:capabilityParameterChoiceOptions('duration',{type:'integer',options:[4,8,12],min:4,max:12}),
  textOptions:capabilityParameterControlKind('voice',{type:'text',options:['m','f']}),
  freeRatio:capabilityParameterChoiceOptions('aspect_ratio',{type:'text'})
}));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True, text=True)
        data = json.loads(result.stdout)
        self.assertEqual(data['emptyRatio'], [])
        self.assertEqual(data['emptyResolution'], [])
        self.assertEqual(data['fixed'], [4, 8, 12])
        self.assertIn(data['textOptions'], ['segments', 'select'])
        self.assertIn('3:4', data['freeRatio'])

    def test_submission_rejects_values_disallowed_by_same_contract(self):
        registry = mc.ModelCapabilityRegistry(ROOT)
        for spec, value in [
            ({'type': 'enum'}, '3:4'),
            ({'type': 'integer', 'options': [4, 8, 12]}, 5),
            ({'type': 'number', 'min': 0, 'max': 1, 'step': .5}, .3),
            ({'type': 'number'}, float('nan')),
            ({'type': 'boolean'}, 'false'),
        ]:
            profile = {'model_id': 'fixture', 'validation_mode': 'strict', 'runnable': True,
                       'inputs': {}, 'parameters': {'value': spec}}
            with self.subTest(spec=spec, value=value), patch.object(registry, 'find_model', return_value=profile):
                with self.assertRaises(mc.ModelCapabilityError):
                    registry.validate_request([], 'fixture', 'fixture', 'image_generation', parameters={'value': value})

    def test_required_parameters_distinguish_user_inputs_from_hidden_model_identity(self):
        script = r'''
const c=require('./static/js/smart-model-capabilities.js');
console.log(JSON.stringify(c.parameterIssues({model_id:'fixture',parameters:{
 model:{type:'model',level:'required',ui_hidden:true},
 clip:{type:'text',level:'required'}
}},{})));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), {'clip': 'PARAM_REQUIRED'})

    def test_laohu_raw_snapshot_and_seedream_v5_flash_contracts(self):
        snapshot = json.loads((ROOT / 'data/model_capabilities/snapshots/ai-money-catalog.json').read_text())
        raw_models = snapshot.get('source_models') or []
        raw_ids = {item.get('id') for item in raw_models if isinstance(item, dict)}
        self.assertEqual(snapshot.get('source_model_count'), 274)
        self.assertEqual(len(raw_models), 274)
        self.assertEqual(len(raw_ids), 274)
        self.assertIn('FlashVSR_video_upscale', snapshot['video_models'])

        expected = {
            'seedream-v5-flash-t2i': 'text_to_image',
            'seedream-v5-flash-i2i': 'image_to_image',
            'dola-seedream-5.0-flash-t2i': 'text_to_image',
            'dola-seedream-5.0-flash-i2i': 'image_to_image',
        }
        self.assertTrue(set(expected).issubset(raw_ids))
        provider = {
            'id': 'ai-money', 'name': 'laohu', 'enabled': True, 'protocol': 'openai',
            'chat_models': [], 'image_models': list(expected), 'video_models': [], 'audio_models': [],
        }
        registry = mc.ModelCapabilityRegistry(ROOT)
        for model_id, operation in expected.items():
            with self.subTest(model=model_id):
                profile = registry.find_model([provider], 'ai-money', model_id, 'image_generation')
                self.assertTrue(profile['runnable'])
                self.assertEqual(profile['operation'], operation)
                self.assertEqual(profile['platform']['endpoint'], '/v1/image/generations')
                self.assertEqual(profile['parameters']['resolution']['options'], ['1k', '1.5k', '2k'])
                self.assertEqual(profile['parameters']['output_format']['options'], ['jpeg', 'png'])
                self.assertEqual((profile['parameters']['width']['min'], profile['parameters']['width']['max']), (240, 8192))
                self.assertEqual((profile['parameters']['height']['min'], profile['parameters']['height']['max']), (240, 8192))
                self.assertEqual(profile['inputs']['prompt']['min_chars'], 5)
                self.assertEqual(profile['inputs']['prompt']['max_chars'], 5000)
                parameters = {'resolution': '1.5k', 'output_format': 'png'}
                if operation == 'image_to_image':
                    self.assertEqual((profile['inputs']['reference']['min'], profile['inputs']['reference']['max']), (1, 10))
                    self.assertEqual(profile['inputs']['reference']['max_bytes'], 30 * 1024 * 1024)
                    counts = {'prompt': 1, 'reference': 1}
                    metadata = {'prompt': {'characters': 12}, 'reference': {'bytes': 1024}}
                    refs = ['https://example.test/reference.png']
                else:
                    counts = {'prompt': 1}
                    metadata = {'prompt': {'characters': 12}}
                    refs = []
                registry.validate_request([provider], 'ai-money', model_id, 'image_generation',
                                          input_counts=counts, input_metadata=metadata, parameters=parameters)
                for characters in (4, 5001):
                    with self.subTest(model=model_id, characters=characters), self.assertRaises(mc.ModelCapabilityError):
                        registry.validate_request([provider], 'ai-money', model_id, 'image_generation',
                                                  input_counts=counts,
                                                  input_metadata={'prompt': {'characters': characters}, **({'reference': {'bytes': 1024}} if operation == 'image_to_image' else {})},
                                                  parameters=parameters)
                if operation == 'image_to_image':
                    with self.assertRaises(mc.ModelCapabilityError):
                        registry.validate_request([provider], 'ai-money', model_id, 'image_generation',
                                                  input_counts=counts,
                                                  input_metadata={'prompt': {'characters': 12}, 'reference': {'bytes': 30 * 1024 * 1024 + 1}},
                                                  parameters=parameters)
                    with self.assertRaises(mc.ModelCapabilityError):
                        registry.validate_request([provider], 'ai-money', model_id, 'image_generation',
                                                  input_counts={'prompt': 1, 'reference': 11},
                                                  parameters=parameters)
                mapped = registry.platform_parameters(profile, parameters)
                body = main.ai_money_image_request_body('足够长度的提示词', model_id, reference_urls=refs,
                                                        capability_parameters=mapped)
                self.assertEqual(body['model'], model_id)
                self.assertEqual(body['metadata'], {'resolution': '1.5k', 'output_format': 'png'})
                self.assertEqual(body.get('images', []), refs)
                # Width/height are sent only when resolution is omitted; the official docs say resolution wins otherwise.
                dimension_parameters = {'width': 1024, 'height': 768, 'output_format': 'jpeg'}
                dimension_mapping = registry.platform_parameters(profile, dimension_parameters)
                dimension_body = main.ai_money_image_request_body('足够长度的提示词', model_id,
                                                                   reference_urls=refs,
                                                                   capability_parameters=dimension_mapping)
                self.assertEqual(dimension_body['metadata'], {'width': 1024, 'height': 768, 'output_format': 'jpeg'})
                self.assertNotIn('resolution', dimension_body['metadata'])
