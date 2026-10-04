import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_node(script):
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class WorkbenchModelPickerTests(unittest.TestCase):
    def test_same_series_merges_across_platforms_without_losing_model_ids(self):
        script = r'''
const c = require('./static/js/smart-model-capabilities.js');
const profile = (provider, model, family, variant, name='Fast') => ({
  model_id:model,
  family_id:family,
  variant_id:variant,
  variant_name:name,
  node_type:'video_generation',
  validation_mode:'strict',
  readiness:'ready',
  runnable:true,
  operation:'text_to_video',
  inputs:{prompt:{role:'prompt', media_type:'text', min:0, max:1}},
  parameters:{}
});
const catalog = {providers:[
  {id:'p1', name:'平台一', protocol:'p1', families:[{family_id:'seedance-2', display_name:'Seedance 2.0', node_type:'video_generation', variants:[profile('p1','p1-fast','seedance-2','fast')]}]},
  {id:'p2', name:'平台二', protocol:'p2', families:[{family_id:'seedance-2', display_name:'Seedance 2.0', node_type:'video_generation', variants:[profile('p2','p2-fast','seedance-2','fast')]}]},
  {id:'p3', name:'平台三', protocol:'p3', families:[{family_id:'other-seedance-2', display_name:'Seedance 2.0', node_type:'video_generation', variants:[profile('p3','p3-fast','other-seedance-2','fast')]}]}
]};
const families = c.familiesAcrossProviders(catalog, 'video_generation', {text:1}, ['p1','p2','p3'], '', {prompt:1}, {});
const merged = families.find(item => item.family_id === 'seedance-2');
const sameLabel = families.filter(item => item.display_name === 'Seedance 2.0');
console.log(JSON.stringify({
  familyCount:families.length,
  mergedProviders:merged?.provider_ids || [],
  mergedModels:(merged?.compatible_variants || []).map(item => item.model_id),
  sameLabelFamilyIds:sameLabel.map(item => item.family_id),
  variantKeys:[c.variantSelectionKey({variant_id:'mode',variant_name:'Fast'}), c.variantSelectionKey({variant_id:'mode',variant_name:'Mini'})]
}));
'''
        result = run_node(script)
        self.assertEqual(result["familyCount"], 1)
        self.assertEqual(result["mergedProviders"], ["p1", "p2", "p3"])
        self.assertEqual(result["mergedModels"], ["p1-fast", "p2-fast", "p3-fast"])
        self.assertEqual(result["sameLabelFamilyIds"], ["seedance-2"])
        self.assertNotEqual(result["variantKeys"][0], result["variantKeys"][1])

    def test_generation_renderers_use_one_family_variant_platform_picker_and_one_bundle(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        for function_name in (
            "function renderTextGenerationParams",
            "function renderApiParams",
            "function renderApiVideoParams",
            "function renderApiAudioParams",
            "function renderApiMusicParams",
        ):
            start = source.index(function_name)
            end = source.index("\nfunction ", start + len(function_name))
            renderer = source[start:end]
            self.assertIn("renderCapabilityModelPicker(selection, descriptor)", renderer)
            self.assertNotIn("renderCapabilityFamilyControl", renderer)
            self.assertNotIn("renderCapabilityVariantControl", renderer)
            self.assertNotIn("renderExecutionPlatformControl", renderer)

        picker = source[source.index("function renderCapabilityModelPicker"):source.index("function renderExecutionModeFallbackControl")]
        self.assertIn("capabilityPickerPlatformEntries", picker)
        self.assertIn("region: data.region || ''", source)
        self.assertIn("RunningHub · ${region === 'cn' ? 'CN' : 'AI'}", picker)

        bundle_start = source.index("function renderCapabilityParameterBundleForSource")
        bundle_end = source.index("function renderCapabilityParameterBundle(", bundle_start)
        bundle = source[bundle_start:bundle_end]
        # 常用参数直接铺开为 markup，仅 level=advanced 的高级参数进入齿轮弹层。
        self.assertIn("inlineEntries", bundle)
        self.assertIn("advancedEntries", bundle)
        self.assertIn("capability-summary-control", bundle)
        self.assertIn("capability-summary-popover", bundle)
        self.assertIn("${entry.body}", bundle)
        self.assertIn("renderCapabilitySettingsControl(advancedEntries", bundle)

    def test_parameter_popover_keeps_scroll_inside_canvas(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        binding_start = source.index("function bindDynamicParams")
        binding_end = source.index("dynamicParams.querySelectorAll('[data-execution-platform-option]')", binding_start)
        bindings = source[binding_start:binding_end]
        self.assertIn("popover.addEventListener('wheel'", bindings)
        self.assertIn("event.stopPropagation()", bindings)
        self.assertIn("inCapabilitySettings", source)
        self.assertIn("requestAnimationFrame(() => positionPinnedSmartPopover(match))", source)

    def test_runninghub_region_profiles_keep_same_model_id_isolated_by_region(self):
        result = run_node(r'''
const c = require('./static/js/smart-model-capabilities.js');
const model = {
  model_id:'same-model', family_id:'same-family', variant_id:'fast', variant_name:'Fast',
  node_type:'image_generation', validation_mode:'strict', readiness:'ready', runnable:true,
  regions:['global','cn'],
  region_profiles:{
    global:{parameters:{quality:{type:'enum', options:['standard']}}},
    cn:{parameters:{quality:{type:'enum', options:['hd']}}}
  },
  inputs:{prompt:{role:'prompt', media_type:'text', min:0, max:1}}, parameters:{}
};
const catalog = {providers:[{id:'runninghub', name:'RunningHub', models:[model], families:[{
  family_id:'same-family', node_type:'image_generation', variants:[model]
}]}]};
const globalProfile = c.findModel(catalog, 'runninghub', 'same-model', 'image_generation', 'global');
const cnProfile = c.findModel(catalog, 'runninghub', 'same-model', 'image_generation', 'cn');
console.log(JSON.stringify({
  global:globalProfile.parameters.quality.options,
  cn:cnProfile.parameters.quality.options,
  closed:c.findModel(catalog, 'runninghub', 'same-model', 'image_generation', 'eu')
}));
''')
        self.assertEqual(result["global"], ["standard"])
        self.assertEqual(result["cn"], ["hd"])
        self.assertIsNone(result["closed"])

    def test_runninghub_region_scopes_candidates_and_picker_state(self):
        result = run_node(r'''
const c = require('./static/js/smart-model-capabilities.js');
const model = {
  model_id:'same-model', family_id:'same-family', variant_id:'fast', variant_name:'Fast',
  node_type:'image_generation', validation_mode:'strict', readiness:'ready', runnable:true,
  regions:['global','cn'],
  region_profiles:{
    global:{parameters:{quality:{type:'enum', options:['standard']}}},
    cn:{parameters:{quality:{type:'enum', options:['hd']}}}
  },
  inputs:{prompt:{role:'prompt', media_type:'text', min:0, max:1}}, parameters:{}
};
const catalog = {providers:[{id:'runninghub', name:'RunningHub', models:[model]}]};
const scoped = region => c.modelsForInputs(catalog, 'image_generation', {text:1}, {prompt:1}, {}, region);
console.log(JSON.stringify({
  global:scoped('global').map(item => item.model_id),
  cn:scoped('cn').map(item => item.model_id),
  closed:scoped('eu').map(item => item.model_id)
}));
''')
        self.assertEqual(result["global"], ["same-model"])
        self.assertEqual(result["cn"], ["same-model"])
        self.assertEqual(result["closed"], [])

        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        self.assertIn("const variantFamily = family", source)
        self.assertIn("compatible_variants:compatibleVariants", source)
        self.assertIn("settings.rhRegion = normalizeRunningHubRegion(button.dataset.capabilityPickerRegion", source)
        self.assertIn("initializedRunningHubRegions", source)
        self.assertIn("if(!provider) return [];", source[source.index("function runningHubEntries"):source.index("function runningHubEntryId")])
        workflow_loader = source[source.index("async function ensureRunningHubWorkflow"):source.index("async function currentRunningHubWorkflowConfig")]
        self.assertIn("options.fetchRemote === true", workflow_loader)
        self.assertIn("region", workflow_loader)
        workflow_config = source[source.index("async function currentRunningHubWorkflowConfig"):source.index("function rhMediaForRun")]
        self.assertIn("const entryFields = rhEntryFields(ref.entry)", workflow_config)
        text_candidates = source[source.index("function verifiedTextGenerationModels"):source.index("function renderTextGenerationParams")]
        self.assertIn("const sourceSettings = node?.runSettings || settings", text_candidates)
        self.assertIn("modelsForVerifiedInputs", text_candidates)
        self.assertIn("configuredCapabilityModelIds(model.provider_id, 'text_generation', region)", text_candidates)


if __name__ == "__main__":
    unittest.main()
