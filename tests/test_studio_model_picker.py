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


class StudioModelPickerTests(unittest.TestCase):
    def test_generation_renderers_use_one_searchable_picker(self):
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

        picker_start = source.index("function renderCapabilityModelPicker")
        picker_end = source.index("\nfunction renderExecutionModeFallbackControl", picker_start)
        picker = source[picker_start:picker_end]
        self.assertIn("data-capability-picker-search", picker)
        self.assertIn("renderCapabilityPickerOption", picker)
        self.assertIn("data-capability-picker-option", source)
        self.assertIn("family", picker)
        self.assertIn("variant", picker)
        self.assertIn("platform", picker)
        self.assertIn("capabilityPickerPlatformEntries", picker)
        self.assertIn("region: data.region || ''", source)

    def test_parameter_panel_is_single_column_and_keeps_short_values(self):
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        js = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        self.assertIn(".capability-settings-list { max-height", css)
        self.assertIn("display:flex; flex-direction:column", css)
        self.assertIn(".capability-settings-list .capability-option { min-width:0", css)
        self.assertIn(".capability-settings-list .capability-option-drag-handle { display:none; }", css)
        sort_start = js.index("function bindCapabilityOptionSort")
        sort_end = js.index("\nfunction preferenceListButtons", sort_start)
        self.assertNotIn("document.createElement('span')", js[sort_start:sort_end])

    def test_model_popup_uses_available_screen_height(self):
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        popup = css.split(".capability-model-picker-popover {", 1)[1].split("}", 1)[0]
        stages = css.split(".capability-model-picker-stages {", 1)[1].split("}", 1)[0]
        self.assertIn("max-height:var(--smart-popover-available", popup)
        self.assertIn("var(--smart-popover-available", stages)
        self.assertIn("overflow-y:auto", stages)

    def test_dense_picker_places_titles_above_full_width_options(self):
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        dense_rules = css.split("/* 模型家族、模式和平台共用一个阶梯入口", 1)[1]
        self.assertIn(".capability-picker-stage { min-width:0; display:flex; flex-direction:column;", dense_rules)
        self.assertNotIn("grid-template-columns:104px", dense_rules)
        self.assertIn(".capability-picker-stage-family .capability-picker-stage-options", dense_rules)
        self.assertIn(".capability-setting-row { display:flex; flex-direction:column;", dense_rules)
        self.assertNotIn("grid-template-columns:minmax(84px", dense_rules)
        self.assertIn("display:grid; grid-template-columns:repeat(auto-fit,minmax(58px,1fr))", dense_rules)
        self.assertIn("white-space:nowrap", dense_rules)

    def test_variant_options_render_short_capability_badges(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        self.assertIn("function capabilityPickerBadgeLabels", source)
        self.assertIn("capability-picker-option-badges", source)
        self.assertIn("badges:capabilityPickerBadgeLabels(variant, nodeType)", source)

    def test_ai_app_label_does_not_revert_after_translation(self):
        translations = (ROOT / "static/js/i18n/smart-canvas.js").read_text(encoding="utf-8")
        entry = next(line for line in translations.splitlines() if '"smart.createAiApp":' in line)
        self.assertIn('zh: "AI 应用"', entry)
        self.assertIn('en: "AI App"', entry)

    def test_video_frame_mode_is_filtered_by_current_inputs(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        start = source.index("function renderVolcengineVideoParams")
        end = source.index("\nfunction renderRunningHubParams", start)
        renderer = source[start:end]
        self.assertIn("renderVideoInputModeControl", renderer)
        self.assertNotIn("renderVideoToggleControl('videoUseFrameRoles'", renderer)

    def test_search_and_real_api_enum_values_are_preserved(self):
        result = run_node(
            r'''
const c = require('./static/js/smart-model-capabilities.js');
const profile = {
  validation_mode:'strict',
  parameters:{resolution:{type:'enum', options:['1.5k','2k','4k']}}
};
console.log(JSON.stringify({
  search:c.matchesSearch('Seedance 2.5 · RunningHub', 'seedance runninghub'),
  mismatch:c.matchesSearch('Seedance 2.5 · RunningHub', 'audio'),
  legal:c.modelSupportsParameters(profile, {resolution:'1.5k'}),
  preserved:c.effectiveParameters(profile, {resolution:'1.5k'}).resolution
}));
'''
        )
        self.assertTrue(result["search"])
        self.assertFalse(result["mismatch"])
        self.assertTrue(result["legal"])
        self.assertEqual(result["preserved"], "1.5k")

    def test_picker_copy_is_bilingual(self):
        i18n = (ROOT / "static/js/i18n/smart-canvas.js").read_text(encoding="utf-8")
        for key in (
            "smart.modelPicker",
            "smart.modelPickerSearch",
            "smart.modelPickerFiltered",
            "smart.modelPickerFamily",
            "smart.modelPickerVariant",
            "smart.modelPickerProvider",
            "smart.modelPickerNoMatch",
        ):
            line = next(line for line in i18n.splitlines() if f'"{key}"' in line)
            self.assertIn("zh:", line)
            self.assertIn("en:", line)


if __name__ == "__main__":
    unittest.main()
