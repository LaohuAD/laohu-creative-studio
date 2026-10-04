import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AiMoneyUiTests(unittest.TestCase):
    def test_api_settings_audio_model_copy_has_bilingual_translations(self):
        translations = (ROOT / "static/js/i18n/api-settings.js").read_text(encoding="utf-8")

        self.assertIn('"api.audioModels": { zh: "音频模型", en: "Audio Models" }', translations)
        self.assertIn(
            '"api.audioHint": { zh: "智能画布音频生成节点使用。", en: "Used by Smart Canvas audio generation nodes." }',
            translations,
        )
        self.assertIn("只有已启用且已适配的模型会进入画布", translations)
        self.assertIn("Only enabled and adapted models enter the canvas", translations)

    def test_api_settings_i18n_cache_versions_are_kept_in_sync(self):
        html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")
        for relative_path in ("static/js/i18n-core.js", "static/js/i18n/api-settings.js"):
            public_path = "/" + relative_path
            self.assertIn(f'{public_path}?v=', html)
        self.assertNotIn('/static/js/i18n.js?v=', html)

    def test_api_settings_contains_ai_money_entry_and_links(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")

        self.assertIn("const AI_MONEY_DEFAULT_BASE_URL = 'https://api.lao-hu.com';", script)
        self.assertIn("const order = ['modelscope', 'runninghub', 'volcengine', 'ai-money', 'agnes'];", script)
        self.assertIn("/static/images/ai-money.png", script)
        self.assertIn("https://api.lao-hu.com/sign-up?aff=460d", script)
        self.assertIn("const AI_MONEY_HOME_URL = 'https://api.lao-hu.com/';", script)
        self.assertIn('href="https://api.lao-hu.com/"', html)
        self.assertNotIn("api.laohuaimoney.com", script)
        self.assertNotIn("api.laohuaimoney.com", html)
        self.assertNotIn("llms.txt", script)
        self.assertNotIn("llms.txt", html)

    def test_recommended_api_page_only_exposes_agnes(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        translations = (ROOT / "static/js/i18n/api-settings.js").read_text(encoding="utf-8")

        recommended_catalog = script.split("const RECOMMENDED_APIS = [", 1)[1].split(
            "];\nconst RECOMMEND_GROUPS", 1
        )[0]
        recommend_renderer = script.split("function renderRecommendApi(){", 1)[1].split(
            "function recommendedProviderForApi", 1
        )[0]

        self.assertIn("id:'agnes'", recommended_catalog)
        for hidden_provider in (
            "土豆API",
            "EXELLOME",
            "FHL",
            "VIP-GPT",
            "RunningHub",
            "APIMART",
            "灵境API",
            "ModelScope",
        ):
            self.assertNotIn(hidden_provider, recommended_catalog)
        self.assertNotIn("recommend-provider-invitation", recommend_renderer)
        self.assertNotIn("recommend-seedance-private-note", recommend_renderer)
        self.assertIn('"api.recommendPanelSub": { zh: "欢迎优质 API 平台入驻；通过管理员审核后，才会在这里展示。", en: "Quality API providers are welcome; only administrator-approved providers are listed here." }', translations)
        for hidden_key in (
            "api.recommendInviteTitle",
            "api.recommendTudouSummary",
            "api.recommendLingjingSummary",
            "api.recommendRunninghubSummary",
            "api.recommendSeedancePrivateNote",
        ):
            self.assertNotIn(hidden_key, translations)

    def test_recommended_cleanup_preserves_configured_platforms_and_clis(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")

        self.assertIn("const order = ['modelscope', 'runninghub', 'volcengine', 'ai-money', 'agnes'];", script)
        for cli_id in ("jimeng", "codex", "gemini-cli"):
            self.assertIn(f"addCliProvider('{cli_id}')", html)

    def test_ai_money_copy_is_bilingual(self):
        translations = (ROOT / "static/js/i18n/api-settings.js").read_text(encoding="utf-8")

        self.assertIn('"api.aiMoneyRegister"', translations)
        self.assertIn('zh: "注册并获取 Key"', translations)
        self.assertIn('en: "Register and Get Key"', translations)
        self.assertIn('"api.recommendPanelSub"', translations)
        self.assertIn('zh: "欢迎优质 API 平台入驻；通过管理员审核后，才会在这里展示。"', translations)
        self.assertIn('en: "Quality API providers are welcome; only administrator-approved providers are listed here."', translations)

    def test_social_links_are_replaced(self):
        html = (ROOT / "static/index.html").read_text(encoding="utf-8")
        translations = (ROOT / "static/js/i18n/common.js").read_text(encoding="utf-8")

        expected_links = [
            "https://xhslink.com/m/AZo7UbSx1ef",
            "https://v.douyin.com/usGF0Kz_Yic/",
            "https://space.bilibili.com/13497214",
            "https://www.youtube.com/@xingduo3927",
        ]
        for link in expected_links:
            self.assertIn(link, html)
        self.assertIn("老胡画梦枋", html)
        self.assertNotIn("dx-letter", html)
        self.assertNotIn("frame-online", html)
        self.assertNotIn("frame-gpt-chat", html)
        self.assertNotIn("wuli大雄", html)
        for key in ("social.xiaohongshu", "social.douyin", "social.bilibili", "social.youtube"):
            self.assertIn(f'data-i18n-title="{key}"', html)
            self.assertIn(f'"{key}"', translations)
        self.assertNotIn("https://x.com/dx8152?s=21", html)

    def test_ai_money_logo_is_stored_in_project(self):
        logo = ROOT / "static/images/ai-money.png"

        self.assertTrue(logo.is_file())
        self.assertGreater(logo.stat().st_size, 0)

    def test_ai_money_logo_and_name_are_centered_as_one_group(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        styles = (ROOT / "static/css/api-settings.css").read_text(encoding="utf-8")

        self.assertIn('src="/static/images/laohu-wordmark.png" alt="laohu" class="laohu-wordmark"', script)
        self.assertTrue((ROOT / 'static/images/laohu-wordmark.png').is_file())
        self.assertIn(".provider-card-ai-money .provider-logo-ai-money { width:auto;", styles)

    def test_api_settings_and_smart_canvas_expose_audio_model_flow(self):
        html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")
        settings_script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        canvas_script = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn('id="audioModelList"', html)
        self.assertIn("addModel('audio')", html)
        self.assertIn('data-cat="audio"', html)
        self.assertIn("renderModels('audio')", settings_script)
        self.assertIn("function renderApiAudioParams", canvas_script)
        self.assertIn("function audioApiProviders", canvas_script)
        self.assertIn("function runApiAudioGeneration", canvas_script)
        self.assertIn("/api/canvas-audio", canvas_script)
        self.assertIn("activeSettings.apiKind === 'audio'", canvas_script)
        self.assertNotIn("音频节点尚无已确认并完成适配的模型", canvas_script)
        self.assertNotIn("node?.type === SMART_NODE_TYPES.audioGenerator ||", canvas_script)

    def test_custom_provider_shows_agent_integration_guide(self):
        html = (ROOT / "static" / "api-settings.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "api-settings.js").read_text(encoding="utf-8")
        translations = (ROOT / "static" / "js" / "i18n" / "api-settings.js").read_text(encoding="utf-8")

        self.assertIn('id="customProviderGuide"', html)
        self.assertIn('/api/provider-integration-guide', html)
        self.assertIn('/api/provider-manifest-schema', html)
        self.assertIn('copyProviderAgentPrompt', script)
        self.assertIn('show-custom-provider-guide', script)
        self.assertIn('拉取全部模型只建立目录', script)
        self.assertIn('"api.customProviderGuideTitle"', translations)
        self.assertIn('"api.viewManifestSchema"', translations)
        self.assertIn('"api.copyAgentPrompt"', translations)

    def test_model_rows_show_backend_capability_readiness(self):
        script = (ROOT / "static" / "js" / "api-settings.js").read_text(encoding="utf-8")
        stylesheet = (ROOT / "static" / "css" / "api-settings.css").read_text(encoding="utf-8")
        translations = (ROOT / "static" / "js" / "i18n" / "api-settings.js").read_text(encoding="utf-8")

        self.assertIn("fetch('/api/model-capabilities')", script)
        self.assertIn("function modelCapabilityStatus", script)
        self.assertIn("model-capability-status", script)
        self.assertIn("model-capability-status", stylesheet)
        self.assertIn('"api.modelReady"', translations)
        self.assertIn('"api.modelNeedsProfile"', translations)
        self.assertIn('"api.modelAdapterMissing"', translations)

    def test_editor_renders_all_four_model_categories(self):
        script = (ROOT / "static" / "js" / "api-settings.js").read_text(encoding="utf-8")

        editor_start = script.index("function renderEditor()")
        editor_end = script.index("function showVerifyResult", editor_start)
        editor_source = script[editor_start:editor_end]
        for kind in ("image", "chat", "video", "audio"):
            self.assertIn(f"renderModels('{kind}')", editor_source)

    def test_api_settings_exposes_network_free_model_preflight(self):
        script = (ROOT / "static" / "js" / "api-settings.js").read_text(encoding="utf-8")
        translations = (ROOT / "static" / "js" / "i18n" / "api-settings.js").read_text(encoding="utf-8")
        self.assertIn("async function preflightModel", script)
        self.assertIn("/api/canvas-preflight", script)
        self.assertIn("network_requested", script)
        self.assertIn("api.preflightModel", translations)

    def test_provider_guide_and_manifest_schema_exist(self):
        guide = ROOT / "docs" / "第三方API平台接入规范.md"
        schema = ROOT / "data" / "model_capabilities" / "provider-manifest.schema.json"

        self.assertTrue(guide.is_file())
        self.assertTrue(schema.is_file())
        guide_text = guide.read_text(encoding="utf-8")
        self.assertIn("目录发现不等于可运行", guide_text)
        self.assertIn("模型家族", guide_text)
        self.assertIn("dry-run", guide_text)


if __name__ == "__main__":
    unittest.main()
