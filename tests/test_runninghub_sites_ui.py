import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "static/api-settings.html"
SCRIPT = ROOT / "static/js/api-settings.js"
STYLES = ROOT / "static/css/api-settings.css"
I18N = ROOT / "static/js/i18n/api-settings.js"


class RunningHubSitesUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML.read_text(encoding="utf-8")
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.styles = STYLES.read_text(encoding="utf-8")
        cls.i18n = I18N.read_text(encoding="utf-8")

    def test_connection_has_two_explicit_region_cards_without_site_dropdown_or_nav_switches(self):
        for element_id in (
            'id="rhGlobalEnabledInput"',
            'id="rhCnEnabledInput"',
            'id="rhGlobalFreeKeyInput"',
            'id="rhGlobalWalletKeyInput"',
            'id="rhCnFreeKeyInput"',
            'id="rhCnWalletKeyInput"',
        ):
            self.assertIn(element_id, self.html)
        self.assertIn('data-rh-region="global"', self.html)
        self.assertIn('data-rh-region="cn"', self.html)
        self.assertNotIn('id="rhRegionInput"', self.html)
        self.assertNotIn('id="rhAppRegionInput"', self.html)
        self.assertNotIn("rhGlobalEnabledNavInput", self.script)
        self.assertNotIn("rhCnEnabledNavInput", self.script)
        self.assertNotIn("runningHubNavRegionSwitches", self.script)
        self.assertIn("function toggleRunningHubRegionEnabled(region, enabled)", self.script)
        self.assertIn("function updateRunningHubKeyInput(region, kind, value)", self.script)
        self.assertIn("rh_regions:item.id === 'runninghub' ? (item.rh_regions || {}) : {}", self.script)
        self.assertIn("enabled:item.id === 'runninghub'", self.script)

    def test_region_enabled_state_survives_normalization_and_switching(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is required for the frontend behavior fixture")
        start = self.script.index("function runningHubRegionFromItem")
        end = self.script.index("\nfunction persistActiveRunningHubRegion", start)
        region_logic = self.script[start:end]
        fixture = f"""
const RUNNINGHUB_REGIONS = {{
  global: {{baseUrl: 'https://www.runninghub.ai'}},
  cn: {{baseUrl: 'https://www.runninghub.cn'}},
}};
const RH_DEFAULT_BASE_URL = RUNNINGHUB_REGIONS.global.baseUrl;
function unique(values) {{ return [...new Set(Array.isArray(values) ? values : [])]; }}
function normalizeRhEntries(values) {{ return Array.isArray(values) ? values : []; }}
{region_logic}
const combinations = [[false, false], [false, true], [true, false], [true, true]];
const actual = combinations.map(([cn, global]) => {{
  const item = {{
    id: 'runninghub',
    rh_region: 'global',
    rh_regions: {{global: {{enabled: global}}, cn: {{enabled: cn}}}},
  }};
  ensureRunningHubRegions(item);
  const before = [item.rh_regions.cn.enabled, item.rh_regions.global.enabled];
  activateRunningHubRegion(item, 'cn');
  const after = [item.rh_regions.cn.enabled, item.rh_regions.global.enabled];
  return {{before, after, selected: item.rh_region}};
}});
const legacy = Object.create(null);
legacy.id = 'runninghub';
legacy.rh_region = 'cn';
legacy.rh_regions = Object.create(null);
legacy.rh_regions.cn = Object.create(null);
legacy.rh_regions.global = Object.create(null);
ensureRunningHubRegions(legacy);
process.stdout.write(JSON.stringify({{actual, legacy: [legacy.rh_regions.cn.enabled, legacy.rh_regions.global.enabled]}}));
"""
        completed = subprocess.run(
            [node, "-e", fixture],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(
            result["actual"],
            [
                {"before": [cn, global_enabled], "after": [cn, global_enabled], "selected": "cn"}
                for cn, global_enabled in ((False, False), (False, True), (True, False), (True, True))
            ],
        )
        self.assertEqual(result["legacy"], [True, False])

    def test_legacy_region_without_enabled_only_enables_original_configured_site(self):
        helper_start = self.script.index("function runningHubRegionEnabledValue")
        helper_end = self.script.index("\nfunction runningHubEmptyRegion", helper_start)
        helper = self.script[helper_start:helper_end]
        self.assertIn("Object.prototype.hasOwnProperty.call(sourceRegion, 'enabled')", helper)
        self.assertIn("return region === selected", helper)
        self.assertIn("regions[region].enabled = runningHubRegionEnabledValue(region, selected, rawRegion);", self.script)

    def test_switching_configured_region_does_not_change_enabled_state(self):
        start = self.script.index("function selectRunningHubModelRegion(region)")
        end = self.script.index("\nfunction broadcastStudioApiChange", start)
        region_switch = self.script[start:end]
        self.assertNotIn("toggleRunningHubRegionEnabled", region_switch)
        self.assertNotIn("enabled =", region_switch)
        self.assertIn("activateRunningHubRegion(item, region);", region_switch)
        self.assertIn("rh_regions:item.id === 'runninghub' ? (item.rh_regions || {}) : {}", self.script)

    def test_runninghub_apps_are_grouped_by_region_and_disabled_site_is_read_only(self):
        self.assertIn('data-rh-app-region="global"', self.html)
        self.assertIn('data-rh-app-region="cn"', self.html)
        self.assertIn('id="rhGlobalPasteInput"', self.html)
        self.assertIn('id="rhCnPasteInput"', self.html)
        self.assertIn("createRhEntryFromPaste('global')", self.html)
        self.assertIn("createRhEntryFromPaste('cn')", self.html)
        self.assertIn("function renderRunningHubCards()", self.script)
        self.assertIn("regionState.enabled === true", self.script)
        self.assertIn("api.rhSiteDisabled", self.i18n)
        self.assertNotIn("changeRunningHubRegion(this.value)", self.html)

    def test_redundant_hypit_and_legacy_comfyui_copy_is_removed(self):
        self.assertNotIn('data-i18n="hypit.noKeys"', self.html)
        self.assertNotIn('id="hypitCapabilitySummary"', self.html)
        self.assertNotIn('class="comfyui-deprecated-note"', self.html)
        self.assertNotIn('data-i18n="api.runningHubLegacyWorkflowDeprecated"', self.html)
        self.assertIn('data-i18n="api.aiAppsTitle"', self.html)

    def test_key_status_does_not_expose_backend_environment_names(self):
        for token in ("key_env", "wallet_key_env", "API/.env"):
            self.assertNotIn(token, self.script + self.html + self.i18n)

    def test_runninghub_models_and_apps_have_explicit_site_badges(self):
        self.assertIn("function runningHubRegionBadge(region", self.script)
        self.assertIn("class=\"model-region-badge\"", self.script)
        self.assertIn("class=\"rh-region-badge\"", self.script)
        self.assertIn('"api.rhRegionBadgeGlobal"', self.i18n)
        self.assertIn('"api.rhRegionBadgeCn"', self.i18n)

    def test_cli_navigation_hides_add_action_after_provider_is_configured(self):
        self.assertIn('id="cliProviderList"', self.html)
        self.assertIn('data-cli-kind="jimeng"', self.html)
        self.assertIn('data-cli-kind="codex"', self.html)
        self.assertIn('data-cli-kind="gemini-cli"', self.html)
        self.assertIn("function syncCliQuickActions()", self.script)
        self.assertIn("button.hidden = configured", self.script)
        self.assertIn("cliCapabilityLabel(item)", self.script)
        self.assertIn('"api.cliJimengCapabilities"', self.i18n)
        self.assertIn('"api.cliCodexCapabilities"', self.i18n)
        self.assertIn('"api.cliGeminiCapabilities"', self.i18n)
        self.assertNotIn("cliLocalSession'))}</span>", self.script)

    def test_jimeng_keeps_image_video_models_while_codex_remains_text_only(self):
        start = self.script.index("function applyCliProtocolDefaults")
        end = self.script.index("\nlet rhWorkflowEditorState", start)
        defaults = self.script[start:end]
        self.assertIn("item.image_models = unique(seedModels ? [...imageModels, ...JIMENG_DEFAULT_IMAGE_MODELS]", defaults)
        self.assertIn("item.video_models = unique(seedModels ? [...videoModels, ...JIMENG_DEFAULT_VIDEO_MODELS]", defaults)
        self.assertIn("item.image_models = [];", defaults)
        self.assertIn("item.video_models = [];", defaults)
        self.assertIn("item.audio_models = [];", defaults)

    def test_runninghub_connection_controls_are_not_tiny_page_scale_overrides(self):
        self.assertIn(".rh-region-card-grid", self.styles)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", self.styles)
        self.assertIn(".rh-region-switch-label", self.styles)
        self.assertIn("font-size:13px", self.styles)
        self.assertIn(".rh-app-region-grid", self.styles)


if __name__ == "__main__":
    unittest.main()
