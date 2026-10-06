import asyncio
import base64
import json
import os
import tempfile
import threading
import unittest
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main
from project_storage import ProjectStorage


TEST_PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z5GkAAAAASUVORK5CYII="


class OpenAICompatibleFixtureHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, _format, *_args):
        return

    def _json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.__class__.requests.append({"method": "GET", "path": self.path, "authorization": self.headers.get("Authorization")})
        if self.path == "/v1/models":
            self._send_json({"data": [{"id": "canvas-e2e-text"}, {"id": "canvas-e2e-image"}]})
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        payload = self._json_body()
        self.__class__.requests.append({
            "method": "POST",
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "payload": payload,
        })
        if self.path == "/v1/chat/completions":
            self._send_json({
                "id": "chatcmpl-canvas-e2e",
                "choices": [{"message": {"role": "assistant", "content": "画布文本链路已贯通"}}],
            })
            return
        if self.path == "/v1/images/generations":
            self._send_json({"created": 1, "data": [{"b64_json": TEST_PNG_BASE64}]})
            return
        self._send_json({"error": "not found"}, status=404)


class ApiSettingsConnectionTests(unittest.IsolatedAsyncioTestCase):
    def test_local_server_auto_reload_is_enabled_by_default_and_can_be_disabled(self):
        self.assertTrue(main.local_auto_reload_enabled({}))
        for value in ("0", "false", "FALSE", "no", "off"):
            self.assertFalse(main.local_auto_reload_enabled({"INFINITE_CANVAS_AUTO_RELOAD": value}))
        self.assertTrue(main.local_auto_reload_enabled({"INFINITE_CANVAS_AUTO_RELOAD": "1"}))

    def test_local_server_reload_configuration_watches_python_but_not_runtime_data(self):
        options = main.local_server_uvicorn_options(env={})

        self.assertEqual(options["app"], "main:app")
        self.assertTrue(options["kwargs"]["reload"])
        self.assertEqual(options["kwargs"]["reload_includes"], ["*.py"])
        excluded = "\n".join(options["kwargs"]["reload_excludes"])
        for directory in (".venv", "python", ".git", "assets", "data", "cache", "backups", "output"):
            self.assertIn(directory, excluded)

        disabled = main.local_server_uvicorn_options(env={"INFINITE_CANVAS_AUTO_RELOAD": "0"})
        self.assertEqual(disabled["app"], "main:app")
        self.assertFalse(disabled["kwargs"]["reload"])

    def test_canvas_creation_is_smart_only(self):
        request = main.CanvasCreateRequest()
        self.assertEqual(request.kind, "smart")
        self.assertEqual(request.icon, "sparkles")
        with self.assertRaises(main.HTTPException) as raised:
            main.new_canvas("普通画布", kind="classic")
        self.assertEqual(raised.exception.status_code, 400)

    def test_runninghub_output_media_kind_uses_explicit_type_or_real_reference(self):
        explicit = main.image_output_meta(
            "https://cdn.example.com/result-without-extension",
            {"type": "video"},
        )
        self.assertEqual(explicit["kind"], "video")

        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            from_file = main.image_output_meta(video.name)
        self.assertEqual(from_file["kind"], "video")

        self.assertEqual(
            main.image_output_meta("https://cdn.example.com/result.mp3")["kind"],
            "audio",
        )

    def test_runninghub_output_items_keep_official_source_metadata_for_type_detection(self):
        items = main.runninghub_extract_output_items({
            "outputs": [
                {"fileUrl": "https://cdn.example.com/video", "mediaType": "video/mp4"},
                {"fileUrl": "https://cdn.example.com/image.png", "type": "image"},
            ]
        })

        self.assertEqual([item["url"] for item in items], [
            "https://cdn.example.com/video",
            "https://cdn.example.com/image.png",
        ])
        self.assertEqual(main.image_output_meta(items[0]["url"], items[0]["source"])["kind"], "video")

    def test_canvas_result_media_kind_hydration_repairs_output_and_nested_result_items(self):
        storage = MagicMock()
        storage.get_result.return_value = {"kind": "video"}
        storage.result_path.return_value = Path("/tmp/generated-result.mp4")
        canvas = {
            "nodes": [{
                "runRef": {"resultIds": ["res-video"]},
                "outputKind": "image",
                "outputs": [{"url": "/api/results/res-video", "kind": "image"}],
                "resultVersions": [{
                    "images": [{"url": "/api/results/res-video", "kind": "image"}],
                }],
            }]
        }

        with patch.object(main, "PROJECT_STORAGE", storage):
            changed = main.hydrate_canvas_result_media_kinds(canvas)

        self.assertTrue(changed)
        node = canvas["nodes"][0]
        self.assertEqual(node["outputKind"], "video")
        self.assertEqual(node["outputs"][0]["kind"], "video")
        self.assertEqual(node["resultVersions"][0]["images"][0]["kind"], "video")

    def test_comfyui_settings_uses_platform_navigation_and_preserves_local_layout(self):
        html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/api-settings.css").read_text(encoding="utf-8")

        self.assertIn('id="comfyuiLocalSection" class="comfyui-local-embed"', html)
        self.assertNotIn('id="comfyuiLocalSection" class="comfyui-local-embed block"', html)
        self.assertIn(".comfyui-local-embed { min-height:680px; padding:0;", css)
        self.assertNotIn('comfyui-settings-nav', html)
        self.assertIn('id="localComfyuiNav"', html)
        self.assertIn('id="runningHubComfyuiNav"', html)
        self.assertNotIn('comfyui-settings.html?embedded=1', html)
        self.assertIn("function setComfyUiSection", script)
        self.assertIn("comfyuiSettingsSection === 'runninghub'", script)
        self.assertIn(".comfyui-subnav", css)

    def test_legacy_runninghub_workflow_is_visibly_marked_deprecated(self):
        html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        i18n = (ROOT / "static/js/i18n/api-settings.js").read_text(encoding="utf-8")
        combined = "\n".join((html, script, i18n))

        self.assertIn("api.runningHubLegacyWorkflowDeprecated", combined)
        self.assertIn("已废弃", combined)
        self.assertIn("Deprecated", combined)

    def test_runninghub_app_reference_accepts_id_and_supported_links(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")

        self.assertIn("new URL(text)", script)
        self.assertIn("webappId", script)
        self.assertIn("/\\/(?:run\\/)?(ai-app|workflow)\\/", script)

    def test_new_runninghub_app_is_saved_into_its_selected_region_before_sync(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")

        create_start = script.index("async function createRhEntryFromPaste(region='')")
        sync_start = script.index("async function syncRhAppFromOfficial", create_start)
        create_source = script[create_start:sync_start]
        self.assertIn("runningHubRegionState(item, targetRegion).rh_apps = targetEntries;", create_source)
        self.assertIn("regions[targetRegion].rh_apps", create_source)
        self.assertIn("const rollbackSaved = await saveProviders();", create_source)
        sync_source = script[sync_start:script.index("function updateRhEntry", sync_start)]
        self.assertIn("服务器未返回已保存的 AI 应用 ID", sync_source)
        self.assertNotIn("renderRunningHubCards();\n    const saved = await saveProviders();", sync_source)

    def test_runninghub_app_addition_uses_a_non_persistent_progress_card(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/api-settings.css").read_text(encoding="utf-8")

        self.assertIn("let rhAppSyncState = null", script)
        self.assertIn("function renderRhSyncCard(state)", script)
        self.assertIn('data-rh-sync-card', script)
        self.assertIn('aria-busy="true"', script)
        self.assertIn("api.rhAppPhaseRead", script)
        self.assertIn("api.rhAppPhaseSave", script)
        self.assertIn("setRhAppSyncState(null)", script)
        self.assertIn("api.rhAppSyncBusy", script)
        self.assertIn(".rh-sync-spinner", css)
        self.assertIn(".rh-paste-row .action-btn:disabled", css)

        i18n = (ROOT / "static/js/i18n/api-settings.js").read_text(encoding="utf-8")
        self.assertIn('"api.rhAppSyncDescription"', i18n)
        self.assertIn('en: "Reading the title, cover, and parameters', i18n)

    def test_runninghub_app_ui_shows_plain_id_and_id_only_placeholder(self):
        html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")

        self.assertIn('placeholder="AI 应用 ID"', html)
        self.assertIn("<span>${escapeHtml(entry.id)}</span>", script)
        self.assertNotIn("/run/ai-app/${entry.id}", script)
        self.assertIn("输入 AI 应用 ID 后点击添加并同步", script)

    def test_runninghub_unsynced_placeholder_is_removed_but_valid_entries_remain(self):
        entries = main.normalize_runninghub_entries([
            {
                "id": "2089305540787126273",
                "title": "AI 应用 126273",
                "note": "",
                "thumbnail": "",
            },
            {
                "id": "valid-legacy",
                "title": "旧版静态应用",
                "note": "",
                "thumbnail": "",
            },
            {
                "id": "synced-empty",
                "title": "AI 应用 -empty",
                "schemaSyncedAt": 123,
            },
        ], "app")

        self.assertEqual([entry["id"] for entry in entries], ["valid-legacy", "synced-empty"])
        self.assertEqual(entries[1]["schemaSyncedAt"], 123)

    async def test_runninghub_app_info_retries_wallet_key_and_returns_schema(self):
        first = MagicMock(status_code=200)
        first.json.return_value = {"code": 332, "msg": "USER_DOES_NOT_EXIST"}
        second = MagicMock(status_code=200)
        second.json.return_value = {
            "code": 0,
            "data": {
                "webappId": "2064269998658510850",
                "webappName": "官方应用",
                "nodeInfoList": [{"nodeId": "1", "fieldName": "text", "fieldType": "STRING", "fieldData": "[]"}],
            },
        }
        client = MagicMock()
        client.get = AsyncMock(side_effect=[first, second])
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=client)
        client_context.__aexit__ = AsyncMock(return_value=False)

        with patch.object(main, "runninghub_provider", return_value={"id": "runninghub", "base_url": "https://www.runninghub.ai"}), \
             patch.object(main, "runninghub_app_info_key_candidates", return_value=["rh-coin-key", "wallet-key"]), \
             patch.object(main, "runninghub_app_headers", return_value={"Host": "www.runninghub.ai"}), \
             patch.object(main.httpx, "AsyncClient", return_value=client_context):
            result = await main.runninghub_app_info("2064269998658510850", "global")

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["webappName"], "官方应用")
        self.assertEqual(client.get.await_count, 2)
        self.assertEqual(client.get.await_args_list[0].kwargs["params"]["webappId"], "2064269998658510850")
        self.assertNotEqual(client.get.await_args_list[0].kwargs["params"]["apiKey"], client.get.await_args_list[1].kwargs["params"]["apiKey"])

    async def test_runninghub_app_info_rejects_incomplete_schema(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"code": 0, "data": {"webappId": "bad-app"}}
        client = MagicMock()
        client.get = AsyncMock(return_value=response)
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=client)
        client_context.__aexit__ = AsyncMock(return_value=False)

        with patch.object(main, "runninghub_provider", return_value={"id": "runninghub", "base_url": "https://www.runninghub.ai"}), \
             patch.object(main, "runninghub_app_info_key_candidates", return_value=["global-key"]), \
             patch.object(main, "runninghub_app_headers", return_value={"Host": "www.runninghub.ai"}), \
             patch.object(main.httpx, "AsyncClient", return_value=client_context):
            with self.assertRaises(main.HTTPException) as raised:
                await main.runninghub_app_info("bad-app", "global")

        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("资料不完整", raised.exception.detail)

    def test_jimeng_login_details_parse_complete_device_flow_output(self):
        verification_url = (
            "https://jimeng.jianying.com/ai-tool/cli-auth?"
            "verification_uri=https%3A%2F%2Fjimeng.jianying.com%2Fpassport%2Fopen%2Fscan_user_code%2F"
            "%3Fuser_code%3D79a7a9cb606e0be0906a0bff81e7941c"
        )
        details = main.jimeng_login_details_from_text(
            "请使用浏览器完成 OAuth Device Flow 登录。\n"
            f"verification_uri: {verification_url}\n"
            "user_code: 79a7a9cb606e0be0906a0bff81e7941c\n"
            "device_code: c7dfda3ffe155f688167ea6fe6d1266a\n"
            "poll_interval: 1s\n"
            "expires_at: 2026-08-13T10:50:54+08:00\n"
        )

        self.assertEqual(details["verification_url"], verification_url)
        self.assertEqual(details["qr_data"], verification_url)
        self.assertEqual(details["user_code"], "79a7a9cb606e0be0906a0bff81e7941c")
        self.assertEqual(details["device_code"], "c7dfda3ffe155f688167ea6fe6d1266a")
        self.assertEqual(details["expires_at"], "2026-08-13T10:50:54+08:00")

    def test_jimeng_login_check_args_use_device_code_and_wait_for_authorization(self):
        args = main.jimeng_login_check_args(
            "verification_uri: https://jimeng.jianying.com/ai-tool/cli-auth\n"
            "device_code: c7dfda3ffe155f688167ea6fe6d1266a\n"
        )

        self.assertEqual(args, [
            "login",
            "checklogin",
            "--device_code=c7dfda3ffe155f688167ea6fe6d1266a",
            "--poll=600",
        ])

    def test_jimeng_login_payload_reports_expired_authorization(self):
        previous = dict(main.JIMENG_LOGIN_SESSION)
        main.JIMENG_LOGIN_SESSION.update({
            "stdout": "verification_uri: https://jimeng.jianying.com/ai-tool/cli-auth\n",
            "stderr": "登录已过期，请重新执行 dreamina login --headless\n",
        })
        try:
            payload = main.jimeng_login_payload(running=False, logged_in=False, returncode=1)
        finally:
            main.JIMENG_LOGIN_SESSION.clear()
            main.JIMENG_LOGIN_SESSION.update(previous)

        self.assertEqual(payload["state"], "expired")
        self.assertIn("重新", payload["message"])

    def test_jimeng_verification_url_only_allows_official_https_host(self):
        self.assertTrue(main.jimeng_verification_url_is_allowed("https://jimeng.jianying.com/ai-tool/cli-auth?code=1"))
        self.assertFalse(main.jimeng_verification_url_is_allowed("http://jimeng.jianying.com/ai-tool/cli-auth?code=1"))
        self.assertFalse(main.jimeng_verification_url_is_allowed("https://jimeng.jianying.com.evil.example/steal"))
        self.assertFalse(main.jimeng_verification_url_is_allowed("file:///tmp/secret"))

    def test_jimeng_qr_png_is_a_real_local_image(self):
        data = main.jimeng_qr_png("https://jimeng.jianying.com/ai-tool/cli-auth?code=local-only")

        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        image = main.Image.open(BytesIO(data))
        self.assertEqual(image.format, "PNG")
        self.assertGreaterEqual(image.width, 180)
        self.assertEqual(image.width, image.height)

    def test_jimeng_browser_command_is_cross_platform(self):
        url = "https://jimeng.jianying.com/ai-tool/cli-auth?code=1"

        self.assertEqual(main.jimeng_browser_command(url, os_name="nt", sys_platform="win32"), ["rundll32.exe", "url.dll,FileProtocolHandler", url])
        self.assertEqual(main.jimeng_browser_command(url, os_name="posix", sys_platform="darwin"), ["open", url])
        self.assertEqual(main.jimeng_browser_command(url, os_name="posix", sys_platform="linux"), ["xdg-open", url])

    async def test_jimeng_open_verification_uses_current_login_session_only(self):
        verification_url = "https://jimeng.jianying.com/ai-tool/cli-auth?code=current-session"
        previous = dict(main.JIMENG_LOGIN_SESSION)
        main.JIMENG_LOGIN_SESSION.update({"stdout": f"verification_uri: {verification_url}\n", "stderr": ""})
        try:
            with patch.object(main, "open_jimeng_verification_url") as opener:
                response = await main.jimeng_login_open_verification()
        finally:
            main.JIMENG_LOGIN_SESSION.clear()
            main.JIMENG_LOGIN_SESSION.update(previous)

        self.assertTrue(response["success"])
        opener.assert_called_once_with(verification_url)

    async def test_jimeng_login_status_becomes_authenticated_after_checklogin_finishes(self):
        class FinishedProcess:
            returncode = 0

        previous = dict(main.JIMENG_LOGIN_SESSION)
        main.JIMENG_LOGIN_SESSION.update({
            "proc": FinishedProcess(),
            "stdout": "登录成功\n",
            "stderr": "",
        })
        try:
            with patch.object(main, "run_jimeng_cli", return_value={"credit": 100}):
                response = await main.jimeng_login_status()
        finally:
            main.JIMENG_LOGIN_SESSION.clear()
            main.JIMENG_LOGIN_SESSION.update(previous)

        self.assertTrue(response["logged_in"])
        self.assertEqual(response["state"], "authenticated")
        self.assertEqual(response["raw"], {"credit": 100})

    def test_jimeng_login_frontend_uses_local_qr_endpoint(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        stylesheet = (ROOT / "static/css/api-settings.css").read_text(encoding="utf-8")

        self.assertIn("/api/jimeng/login/qr", script)
        self.assertIn("openJimengVerification", script)
        self.assertIn("data?.state === 'expired'", script)
        self.assertIn("clearInterval(jimengLoginTimer)", script)
        self.assertNotIn('src="${escapeHtml(qrUrl)}"', script)
        self.assertIn("@media (max-width:720px)", stylesheet)
        self.assertIn(".jimeng-output { grid-template-columns:1fr; justify-items:center; }", stylesheet)

    def test_api_settings_keeps_platform_editor_visible_and_fetch_can_cancel(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        stylesheet = (ROOT / "static/css/api-settings.css").read_text(encoding="utf-8")

        self.assertIn("let fetchModelsController = null;", script)
        self.assertIn("fetchModelsController.abort();", script)
        self.assertIn("signal:fetchModelsController.signal", script)
        self.assertIn("closeRecommendApi();\n        setStatus('');", script)
        self.assertIn("if(event.key !== 'Escape') return;", script)
        self.assertIn("if(event.target !== overlay) return;", script)
        self.assertIn(".action-btn.primary-btn.is-cancel", stylesheet)
        self.assertIn("#modelPickerOverlay {", stylesheet)
        self.assertIn("align-items:flex-start", stylesheet)
        self.assertIn("#modelPickerOverlay .picker-body", stylesheet)

    def test_runninghub_app_snapshot_keeps_official_schema_without_credentials(self):
        snapshot = main.sanitize_runninghub_app_snapshot({
            "webappName": "官方应用",
            "webappNameZh": "中文应用",
            "webappNameEn": "English App",
            "titles": {"zh": "中文应用", "en": "English App"},
            "covers": [{"thumbnailUri": "https://example.com/cover.jpg", "ignored": "x"}],
            "tags": [{"name": "视频", "ignored": "x"}],
            "nodeInfoList": [{"nodeId": "1", "fieldName": "image", "fieldType": "IMAGE", "fieldData": "[]"}],
            "curl": "--data apiKey=secret",
            "apiKey": "secret",
        })

        self.assertEqual(snapshot["webappName"], "官方应用")
        self.assertEqual(snapshot["webappNameZh"], "中文应用")
        self.assertEqual(snapshot["webappNameEn"], "English App")
        self.assertEqual(snapshot["titles"], {"zh": "中文应用", "en": "English App"})
        self.assertEqual(snapshot["covers"][0]["thumbnailUri"], "https://example.com/cover.jpg")
        self.assertEqual(snapshot["nodeInfoList"][0]["fieldType"], "IMAGE")
        self.assertNotIn("curl", snapshot)
        self.assertNotIn("apiKey", snapshot)

    def test_runninghub_preflight_rejects_text_in_official_float_field(self):
        provider = {
            "rh_apps": [{
                "id": "2089305540787126273",
                "title": "老胡音乐数字人V3",
                "fields": [
                    {"nodeId": "360", "fieldName": "text", "fieldType": "STRING", "label": "提示词文本"},
                    {"nodeId": "105", "fieldName": "megapixels", "fieldType": "FLOAT", "label": "一采参数 分辨率"},
                ],
            }],
        }

        with self.assertRaises(main.HTTPException) as caught:
            main.runninghub_preflight_app(provider, "2089305540787126273", {
                "360::text": "这个女人在录音棚里面唱歌",
                "105::megapixels": "这个女人在录音棚里面唱歌",
            })

        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("105::megapixels", str(caught.exception.detail))
        self.assertIn("要求数字", str(caught.exception.detail))

    def test_runninghub_role_does_not_use_field_name_or_label(self):
        self.assertEqual(main.rh_field_role({
            "fieldName": "prompt",
            "label": "提示词文本",
            "fieldType": "STRING",
        }), "text")
        self.assertEqual(main.rh_field_role({
            "fieldName": "text",
            "label": "普通文本",
            "fieldType": "STRING",
            "inputRole": "prompt",
        }), "prompt")

    def test_normalized_runninghub_app_removes_credentials_from_legacy_raw_snapshot(self):
        entry = main.normalize_runninghub_entry({
            "id": "2064269998658510850",
            "title": "老胡音乐数字人V2",
            "raw": {
                "webappId": "2064269998658510850",
                "webappName": "老胡音乐数字人V2",
                "nodeInfoList": [{
                    "nodeId": "720",
                    "fieldName": "select",
                    "fieldType": "SWITCH",
                    "description": "是否高清视频？",
                    "fieldData": '[{"name":"input2","index":2.0,"description":"否"},{"name":"input1","index":1.0,"description":"是"}]',
                }],
                "curl": "curl --data apiKey=secret",
                "apiKey": "secret",
            },
            "fields": [{
                "id": "720::select",
                "nodeId": "720",
                "fieldName": "select",
                "fieldType": "SWITCH",
                "label": "是否高清视频？",
                "options": [],
            }],
        }, "app")

        self.assertEqual(entry["raw"]["webappName"], "老胡音乐数字人V2")
        self.assertNotIn("curl", entry["raw"])
        self.assertNotIn("apiKey", entry["raw"])
        self.assertEqual(entry["fields"][0]["options"], ["2", "1"])
        self.assertEqual(entry["fields"][0]["optionLabels"], {"2": "否", "1": "是"})

    def test_upstream_model_classification_preserves_audio_models(self):
        grouped, model_ids = main.parse_upstream_models({
            "data": [
                {"id": "gpt-5.5"},
                {"id": "gpt-image-2"},
                {"id": "seedance-2.0"},
                {"id": "doubao-seed-audio-1.0"},
            ]
        })

        self.assertEqual(grouped["chat"], ["gpt-5.5"])
        self.assertEqual(grouped["image"], ["gpt-image-2"])
        self.assertEqual(grouped["video"], ["seedance-2.0"])
        self.assertEqual(grouped["audio"], ["doubao-seed-audio-1.0"])
        self.assertEqual(len(model_ids), 4)

    def test_runninghub_registry_payload_preserves_audio_output_type(self):
        payload = main.runninghub_registry_payload([
            {"id": "rh-image", "output_type": "image"},
            {"id": "rh-video", "output_type": "video"},
            {"id": "rh-audio", "output_type": "audio"},
            {"id": "rh-chat", "output_type": "chat"},
        ])

        self.assertIn("rh-audio", payload["audio_models"])
        self.assertIn("rh-audio", payload["all"])
        self.assertIn("rh-chat", payload["chat_models"])
        self.assertIn("rh-chat", payload["all"])

    def test_api_settings_new_provider_contract_includes_audio_models(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")

        self.assertIn("image_models:[], chat_models:[], video_models:[], audio_models:[]", script)

    def test_recommended_provider_contract_preserves_audio_models(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")

        self.assertIn("if(Array.isArray(api.audio_models)) item.audio_models = [...api.audio_models];", script)
        self.assertIn("item.audio_models = [];", script)
        self.assertIn("audio_models:api.empty_models_on_save ? []", script)

    def test_api_settings_script_cache_version_is_current(self):
        html = main.versioned_static_html((ROOT / "static/api-settings.html").read_text(encoding="utf-8"))
        app_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        asset_version = f"{app_version}.{(ROOT / 'static/js/api-settings.js').stat().st_mtime_ns}"

        self.assertIn(f'/static/js/api-settings.js?v={asset_version}', html)

    def test_legacy_volcengine_migration_preserves_audio_models(self):
        providers = main.merge_default_api_providers([
            {
                "id": "legacy-volcengine",
                "name": "旧火山引擎",
                "base_url": main.VOLCENGINE_DEFAULT_BASE_URL,
                "protocol": "volcengine",
                "audio_models": ["doubao-seed-audio-1.0"],
            }
        ])

        provider = next(item for item in providers if item["id"] == "volcengine")
        self.assertEqual(provider["audio_models"], ["doubao-seed-audio-1.0"])

    async def test_public_model_catalog_aggregates_enabled_provider_audio_models(self):
        providers = [
            {
                "id": "audio-provider",
                "enabled": True,
                "chat_models": ["chat-model"],
                "image_models": ["image-model"],
                "video_models": ["video-model"],
                "audio_models": ["audio-model"],
            },
            {
                "id": "disabled-provider",
                "enabled": False,
                "audio_models": ["hidden-audio-model"],
            },
        ]

        with patch.object(main, "public_api_providers", return_value=providers):
            payload = await main.ai_models()

        self.assertIn("audio-model", payload["audio_models"])
        self.assertNotIn("hidden-audio-model", payload["audio_models"])

    def test_codex_cli_exposes_text_only(self):
        with patch.object(main, "codex_models_cache_path", return_value=ROOT / "missing-models-cache.json", create=True):
            payload = main.codex_models_payload()

        self.assertEqual(main.CODEX_DEFAULT_IMAGE_MODELS, [])
        self.assertEqual(payload["image_models"], [])
        self.assertEqual(payload["video_models"], [])
        self.assertEqual(payload["chat_models"], main.CODEX_DEFAULT_CHAT_MODELS)
        self.assertEqual(main.CODEX_DEFAULT_CHAT_MODELS[0], "auto")

    def test_codex_models_payload_reads_current_visible_codex_model_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "models_cache.json"
            cache_path.write_text(json.dumps({
                "fetched_at": "2026-08-27T11:02:10Z",
                "client_version": "0.148.0",
                "models": [
                    {"slug": "gpt-visible-a", "display_name": "GPT Visible A", "visibility": "list"},
                    {"slug": "gpt-hidden", "display_name": "GPT Hidden", "visibility": "hide"},
                    {"slug": "gpt-visible-b", "display_name": "GPT Visible B", "visibility": "list"},
                ],
            }), encoding="utf-8")

            with patch.dict(main.os.environ, {"CODEX_HOME": temp_dir}, clear=False):
                payload = main.codex_models_payload()

        self.assertEqual(payload["chat_models"], ["auto", "gpt-visible-a", "gpt-visible-b"])
        self.assertEqual(payload["model_count"], 3)
        self.assertEqual(payload["source"], "codex_models_cache")
        self.assertEqual(payload["fetched_at"], "2026-08-27T11:02:10Z")
        self.assertEqual(payload["model_names"]["auto"], "Codex 当前配置")
        self.assertEqual(payload["model_names"]["gpt-visible-b"], "GPT Visible B")
        self.assertNotIn("gpt-hidden", payload["all"])

    def test_model_picker_uses_codex_catalog_display_names(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")

        self.assertIn("const fetched = lastFetchedModelNames?.[raw];", script)
        self.assertIn("return saved || fetched || raw;", script)

    def test_applying_model_picker_persists_provider_models_immediately(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")

        self.assertIn("async function applyModelPicker(){", script)
        apply_block = script.split("async function applyModelPicker(){", 1)[1].split("async function saveKeyOnly(){", 1)[0]
        self.assertIn("const saved = await scheduleProviderAutosave(", apply_block)
        self.assertNotIn("点保存生效", apply_block)

    def test_model_picker_waits_for_persistence_before_closing(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        apply_block = script.split("async function applyModelPicker(){", 1)[1].split("async function saveKeyOnly(){", 1)[0]

        self.assertLess(apply_block.index("const saved = await scheduleProviderAutosave("), apply_block.index("closeModelPicker();"))
        self.assertIn("if(saved){", apply_block)
        self.assertIn("Object.assign(item, previousModels);", apply_block)

    def test_model_picker_uses_actionable_availability_copy_and_bulk_controls(self):
        html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        i18n = (ROOT / "static/js/i18n/api-settings.js").read_text(encoding="utf-8")

        self.assertIn('onclick="selectPickerModels(\'recommended\')"', html)
        self.assertIn('onclick="selectPickerModels(\'all\')"', html)
        self.assertIn('onclick="selectPickerModels(\'clear\')"', html)
        self.assertIn('zh: "建议选择"', i18n)
        self.assertIn('zh: "可能不可用"', i18n)
        self.assertIn("api.rhModelConfirmedHint", script)
        self.assertIn("api.rhModelUnverifiedHint", script)

    def test_connection_check_keeps_complete_fetched_model_metadata(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        connection_block = script.split("async function testConnection(){", 1)[1].split("let lastFetchedAll", 1)[0]

        self.assertIn("setFetchedModelState(data);", connection_block)
        self.assertNotIn("lastFetchedAll = data.all || [];", connection_block)

    def test_runninghub_editor_checks_both_provider_persistence_results(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        save_block = script.split("async function saveRhWorkflowEditor(){", 1)[1].split("function renderRhWorkflowEditor(){", 1)[0]

        self.assertIn("return scheduleRhWorkflowEditorAutosave(true);", save_block)

    def test_destructive_provider_actions_rollback_after_failed_save(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        delete_block = script.split("async function deleteProvider(){", 1)[1].split("async function saveRhKeyOnly", 1)[0]
        clear_key_block = script.split("async function clearKeyOnly(){", 1)[1].split("const FIXED_PROTOCOL_PROVIDER_IDS", 1)[0]
        clear_rh_block = script.split("async function clearRhKeyOnly(kind, region=''){", 1)[1].split("async function saveVolcengineAssetKeys", 1)[0]
        clear_volc_block = script.split("async function clearVolcengineAssetKeys(){", 1)[1].split("function addModel", 1)[0]
        remove_rh_block = script.split("async function removeRhEntry(kind, index, region=''){", 1)[1].split("function readFileAsDataUrl", 1)[0]
        add_recommended_block = script.split("async function addRecommendedApi(index){", 1)[1].split("async function saveRecommendedApi", 1)[0]
        save_recommended_block = script.split("async function saveRecommendedApi(index, suppliedKey=''){", 1)[1].split("function sortedProviders", 1)[0]
        add_cli_block = script.split("async function addCliProvider(kind){", 1)[1].split("async function deleteProvider", 1)[0]

        self.assertIn("providers = previousProviders;", delete_block)
        self.assertIn("item._clearKey = previousClearKey;", clear_key_block)
        self.assertIn("item._clearRhApiKeys = previousApiClears;", clear_rh_block)
        self.assertIn("item._clearRhWalletKeys = previousWalletClears;", clear_rh_block)
        self.assertIn("item._clearVolcengineAccessKey = previousAccessClear;", clear_volc_block)
        self.assertIn("item._clearVolcengineSecretKey = previousSecretClear;", clear_volc_block)
        self.assertIn("regionState[listKey] = previousEntries;", remove_rh_block)
        self.assertIn("if(!response.ok)", remove_rh_block)
        workflow_deleted_block = remove_rh_block.split("if(workflowBodyDeleted){", 1)[1].split("regionState[listKey] = previousEntries;", 1)[0]
        self.assertNotIn("previousEntries", workflow_deleted_block)
        self.assertIn("请刷新后重试", workflow_deleted_block)
        self.assertIn("providers = previousProviders;", add_recommended_block)
        self.assertIn("providers = previousProviders;", save_recommended_block)
        self.assertIn("providers = previousProviders;", add_cli_block)

    def test_comfyui_saved_state_is_not_reversed_by_broadcast_failure(self):
        script = (ROOT / "static/js/comfyui-settings.js").read_text(encoding="utf-8")

        self.assertIn("function broadcastComfyUiChange(type){", script)
        self.assertGreaterEqual(script.count("broadcastComfyUiChange('workflows-changed');"), 3)
        self.assertIn("await selectWorkflow(result.name);", script)

    def test_codex_auto_model_follows_current_codex_configuration(self):
        self.assertEqual(main.codex_model_for_exec("auto"), "")
        self.assertEqual(main.codex_model_for_exec(""), "")
        self.assertEqual(main.codex_model_for_exec("gpt-5.5"), "gpt-5.5")

    async def test_codex_image_generation_is_rejected(self):
        with self.assertRaises(main.HTTPException) as context:
            await main.generate_codex_provider_image("测试", "1024x1024", "gpt-image-2")

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("不支持图片生成", str(context.exception.detail))

    async def test_image_dispatch_rejects_legacy_codex_provider(self):
        legacy_provider = {
            "id": "codex",
            "name": "GPT CLI",
            "protocol": "codex",
            "image_models": ["gpt-image-2"],
        }

        with patch.object(main, "get_api_provider", return_value=legacy_provider):
            with self.assertRaises(main.HTTPException) as context:
                await main.generate_ai_image("测试", "1024x1024", "high", "gpt-image-2", provider_id="codex")

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("不支持图片生成", str(context.exception.detail))

    async def test_video_dispatch_rejects_legacy_codex_provider(self):
        legacy_provider = {
            "id": "codex",
            "name": "GPT CLI",
            "protocol": "codex",
            "video_models": ["sora-2"],
        }
        payload = main.CanvasVideoRequest(prompt="测试", provider_id="codex", model="sora-2")

        with patch.object(main, "get_api_provider", return_value=legacy_provider):
            with self.assertRaises(main.HTTPException) as context:
                await main.canvas_video(payload)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("不支持视频生成", str(context.exception.detail))

    async def test_codex_status_does_not_expose_image_helper(self):
        with patch.object(main, "codex_cli_executable", return_value=""):
            status = await main.codex_status()

        self.assertNotIn("image2_helper_installed", status)
        self.assertNotIn("生图", status["message"])

    def test_codex_cli_candidates_include_chatgpt_bundle_on_macos(self):
        with patch.object(main.sys, "platform", "darwin"), patch.object(main, "codex_env_value", return_value=""), patch.object(main.os.path, "expanduser", return_value="/Users/test"):
            candidates = main.codex_cli_candidates()

        self.assertIn("/Applications/ChatGPT.app/Contents/Resources/codex", candidates)
        self.assertIn(main.os.path.join("/Users/test", "Applications", "ChatGPT.app", "Contents", "Resources", "codex"), candidates)

    async def test_codex_status_reports_login_state(self):
        version_proc = MagicMock()
        version_proc.communicate = AsyncMock(return_value=(b"codex-cli 1.0\n", b""))
        version_proc.returncode = 0
        login_proc = MagicMock()
        login_proc.communicate = AsyncMock(return_value=(b"Logged in using an API key - sk-***\n", b""))
        login_proc.returncode = 0

        create_process = AsyncMock(side_effect=[version_proc, login_proc])
        with patch.object(main, "codex_cli_executable", return_value="/tmp/codex"), patch.object(main, "codex_cli_env", return_value={"CODEX_HOME": "/tmp/shared-codex"}), patch.object(main.asyncio, "create_subprocess_exec", new=create_process):
            status = await main.codex_status()

        self.assertTrue(status["installed"])
        self.assertTrue(status["logged_in"])
        self.assertEqual(status["state"], "ready")
        self.assertNotIn("sk-***", status["message"])
        self.assertEqual(create_process.await_count, 2)
        for call in create_process.await_args_list:
            self.assertEqual(call.kwargs["env"]["CODEX_HOME"], "/tmp/shared-codex")

    def test_codex_cli_env_follows_current_codex_auth_configuration(self):
        with patch.dict(main.os.environ, {"CODEX_HOME": "/Users/test/.codex", "CODEX_CLI_HOME": "/tmp/obsolete-project-auth"}, clear=False):
            env = main.codex_cli_env()

        self.assertEqual(env["CODEX_HOME"], "/Users/test/.codex")
        self.assertNotIn("CODEX_CLI_HOME", env)

    async def test_run_codex_cli_uses_current_shared_auth_environment(self):
        process = MagicMock()
        process.communicate = AsyncMock(return_value=("当前凭据已跟随\n".encode("utf-8"), b""))
        process.returncode = 0
        create_process = AsyncMock(return_value=process)

        with patch.object(main, "codex_cli_executable", return_value="/tmp/codex"), patch.object(main, "codex_cli_env", return_value={"CODEX_HOME": "/tmp/shared-codex"}), patch.object(main.asyncio, "create_subprocess_exec", new=create_process):
            result = await main.run_codex_cli("测试", output_last_message=False)

        self.assertEqual(result["text"], "当前凭据已跟随")
        self.assertEqual(create_process.await_args.kwargs["env"]["CODEX_HOME"], "/tmp/shared-codex")

    async def test_run_codex_cli_explicit_model_override_is_process_scoped(self):
        process = MagicMock()
        process.communicate = AsyncMock(return_value=(b"MODEL_OK\n", b""))
        process.returncode = 0
        create_process = AsyncMock(return_value=process)

        with patch.object(main, "codex_cli_executable", return_value="/tmp/codex"), patch.object(main, "codex_cli_env", return_value={"CODEX_HOME": "/tmp/shared-codex"}), patch.object(main.asyncio, "create_subprocess_exec", new=create_process):
            result = await main.run_codex_cli("测试", model="gpt-5.6-luna", output_last_message=False)

        command = create_process.await_args.args
        self.assertEqual(result["text"], "MODEL_OK")
        self.assertIn("--model", command)
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.6-luna")
        self.assertNotIn("login", command)

    def test_api_settings_does_not_register_codex_image_models(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")

        self.assertIn("const CODEX_DEFAULT_IMAGE_MODELS = [];", script)
        self.assertIn("item.image_models = [];", script)
        self.assertIn("只支持文本生成", script)
        self.assertNotIn("OpenAI CLI”聊天或生成图片", script)

    def test_codex_installers_do_not_install_image_helpers(self):
        installer_paths = [
            ROOT / "CLI/macos/openai/install_openai_codex_cli.command",
            ROOT / "CLI/linux/openai/install_openai_codex_cli.sh",
            ROOT / "CLI/windows/openai/install_openai_codex_cli.ps1",
        ]

        for path in installer_paths:
            script = path.read_text(encoding="utf-8")
            self.assertNotIn("gpt-image-2-skill", script, path.as_posix())
            self.assertIn("仅接入 OpenAI Codex CLI 的文本能力", script, path.as_posix())
            self.assertNotIn("API/codex-home", script, path.as_posix())
            self.assertNotIn("API\\codex-home", script, path.as_posix())

        windows_launcher = (ROOT / "CLI/windows/openai/2-start_openai_codex_cli.bat").read_text(encoding="utf-8")
        self.assertNotIn("CODEX_HOME", windows_launcher)

    def test_codex_missing_cli_message_is_cross_platform(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("请先在 API 设置的 GPT CLI 卡片中安装或更新", source)
        self.assertNotIn("请先运行 CLI/windows/openai/install_openai_codex_cli.bat", source)

    def test_codex_provider_normalization_removes_legacy_media_models(self):
        provider = main.normalize_provider({
            "id": "codex",
            "name": "GPT CLI",
            "protocol": "codex",
            "image_models": ["gpt-image-2"],
            "video_models": ["sora-2"],
            "chat_models": ["gpt-5.5"],
        })

        self.assertEqual(provider["image_models"], [])
        self.assertEqual(provider["video_models"], [])

    def test_existing_cli_provider_model_selection_is_not_reseeded(self):
        providers = main.merge_default_api_providers([{
            "id": "jimeng",
            "name": "即梦 CLI",
            "protocol": "jimeng",
            "image_models": ["5.0Pro"],
            "chat_models": [],
            "video_models": [],
            "audio_models": [],
        }, {
            "id": "codex",
            "name": "GPT CLI",
            "protocol": "codex",
            "image_models": [],
            "chat_models": [],
            "video_models": [],
            "audio_models": [],
        }], inject_missing=False)

        jimeng = next(item for item in providers if item["id"] == "jimeng")
        codex = next(item for item in providers if item["id"] == "codex")
        self.assertEqual(jimeng["image_models"], ["5.0Pro"])
        self.assertEqual(jimeng["video_models"], [])
        self.assertEqual(codex["chat_models"], [])

    def test_existing_codex_provider_does_not_restore_deleted_auto_choice(self):
        providers = main.merge_default_api_providers([{
            "id": "codex",
            "name": "GPT CLI",
            "protocol": "codex",
            "image_models": [],
            "chat_models": ["gpt-5.5"],
            "video_models": [],
            "audio_models": [],
        }], inject_missing=False)

        codex = next(item for item in providers if item["id"] == "codex")
        self.assertEqual(codex["chat_models"], ["gpt-5.5"])

    def test_api_settings_only_seeds_cli_models_on_explicit_setup(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")

        self.assertIn("function applyCliProtocolDefaults(item, protocol, seedModels=false)", script)
        self.assertIn("applyCliProtocolDefaults(item, item.protocol, protocolChanged)", script)
        self.assertIn("applyCliProtocolDefaults(item, preset.protocol, created)", script)
        self.assertNotIn("if(isCliProtocol) applyCliProtocolDefaults(item, item.protocol);", script)

    def test_runninghub_uses_official_registry_and_region_catalog_urls(self):
        self.assertEqual(
            main.RUNNINGHUB_MODEL_REGISTRY_URL,
            "https://raw.githubusercontent.com/HM-RunningHub/ComfyUI_RH_OpenAPI/main/models_registry.json",
        )
        self.assertEqual(
            main.runninghub_public_catalog_url("cn"),
            "https://www.runninghub.cn/call-api/search-api/standard-model",
        )
        self.assertEqual(
            main.runninghub_public_catalog_url("global"),
            "https://www.runninghub.ai/call-api/search-api/standard-model",
        )

    def test_runninghub_official_registry_parser_rejects_non_schema_model_lists(self):
        official = main.runninghub_official_registry_items({
            "version": "public-test",
            "models": [{
                "name_en": "Demo Image",
                "endpoint": "demo/text-to-image",
                "output_type": "image",
                "params": [{"fieldKey": "prompt", "type": "STRING"}],
            }],
        })
        llm_only = main.runninghub_official_registry_items({
            "data": [{"id": "gpt-test"}],
        })
        source_list = main.runninghub_official_registry_items([{
            "name_en": "Demo Image Source",
            "endpoint": "demo/image-to-image",
            "output_type": "image",
            "params": [{"fieldKey": "prompt", "type": "STRING"}],
        }])

        self.assertEqual([item["endpoint"] for item in official], ["demo/text-to-image"])
        self.assertEqual([item["endpoint"] for item in source_list], ["demo/image-to-image"])
        self.assertEqual(llm_only, [])

    def test_runninghub_public_catalog_parser_reads_only_official_ssr_records(self):
        values = [
            ["ShallowReactive", 1],
            {"data": 2},
            ["ShallowReactive", 3],
            {'api-list-search-STANDARD_MODEL-{"pageNum":1}': 4},
            {"page": 5},
            {"records": 6},
            [7, 9],
            {"name": 8},
            "demo/text-to-image",
            {"name": 10},
            "Demo Video",
        ]
        html = (
            '<script type="application/json" data-nuxt-data="nuxt-app" '
            f'id="__NUXT_DATA__">{json.dumps(values)}</script>'
        )

        self.assertEqual(
            main.runninghub_public_catalog_names_from_html(html),
            {"demo/text-to-image", "Demo Video"},
        )
        self.assertEqual(main.runninghub_public_catalog_names_from_html("<html></html>"), set())

    def test_runninghub_region_availability_does_not_guess_unlisted_models(self):
        items = [
            {
                "name_en": "Demo Image",
                "endpoint": "demo/text-to-image",
                "output_type": "image",
                "params": [],
            },
            {
                "name_en": "Hidden Video",
                "endpoint": "hidden/text-to-video",
                "output_type": "video",
                "params": [],
            },
        ]

        availability = main.runninghub_region_availability(items, {"demo/text-to-image"})

        self.assertEqual(availability["Demo Image"], "confirmed")
        self.assertEqual(availability["Hidden Video"], "unverified")

    def test_runninghub_llm_models_url_follows_selected_region(self):
        self.assertEqual(
            main.runninghub_llm_models_url({"rh_region": "cn"}),
            "https://llm.runninghub.cn/v1/models",
        )
        self.assertEqual(
            main.runninghub_llm_models_url({"rh_region": "global"}),
            "https://llm.runninghub.ai/v1/models",
        )

    async def test_runninghub_public_standard_catalog_does_not_require_llm_key(self):
        with patch.object(main, "runninghub_api_headers", side_effect=main.HTTPException(status_code=400, detail="missing key")):
            models, meta = await main.fetch_runninghub_llm_models({"rh_region": "cn"})

        self.assertEqual(models, [])
        self.assertEqual(meta["count"], 0)
        self.assertIn("missing key", " ".join(meta["errors"]))

    def test_runninghub_production_source_does_not_use_undocumented_models_endpoint(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertNotIn('runninghub_openapi_url(provider, "models")', source)
        self.assertNotIn('"/openapi/v2/models" if protocol == "runninghub"', source)

    async def test_runninghub_registry_uses_verified_snapshot_when_remote_is_unavailable(self):
        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, url, **_kwargs):
                if url == main.RUNNINGHUB_MODEL_REGISTRY_URL:
                    raise httpx.ConnectError("offline")
                return httpx.Response(503, text="offline")

        with patch.object(main.httpx, "AsyncClient", return_value=FakeClient()):
            items, meta = await main.fetch_runninghub_model_registry(
                {"rh_region": "cn"},
                include_fallback=True,
                include_meta=True,
            )

        snapshot_path = Path(main.RUNNINGHUB_OFFICIAL_REGISTRY_SNAPSHOT_FILE)
        verified_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

        self.assertGreaterEqual(meta["registry_count"], 300)
        self.assertEqual(meta["source"], "official-snapshot")
        self.assertEqual(meta["registry_version"], verified_snapshot["version"])
        self.assertTrue(any(item.get("params") for item in items))

    async def test_runninghub_llm_only_response_never_replaces_standard_registry(self):
        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, url, **_kwargs):
                if "llm.runninghub" in url:
                    return httpx.Response(200, json={"data": [{"id": "gpt-only"}]})
                return httpx.Response(200, json={"data": [{"id": "not-a-standard-registry"}]})

        with patch.object(main, "RUNNINGHUB_OFFICIAL_REGISTRY_SNAPSHOT_FILE", str(ROOT / "missing-runninghub-registry.json")), patch.object(main.httpx, "AsyncClient", return_value=FakeClient()):
            with self.assertRaises(main.HTTPException) as raised:
                await main.fetch_runninghub_model_registry(
                    {"rh_region": "cn"},
                    include_fallback=False,
                    include_meta=True,
                )

        self.assertEqual(raised.exception.status_code, 502)

    async def test_runninghub_payload_keeps_region_status_separate_from_schema(self):
        registry = [
            {"name_en": "Public Image", "endpoint": "public/text-to-image", "output_type": "image", "params": []},
            {"name_en": "Hidden Video", "endpoint": "hidden/text-to-video", "output_type": "video", "params": []},
            {"name_en": "String Utility", "endpoint": "utility/string", "output_type": "string", "params": []},
            {"name_en": "Region LLM", "endpoint": "region-llm", "output_type": "chat"},
        ]
        meta = {
            "source": "official-snapshot",
            "registry_count": 3,
            "registry_version": "public-test",
            "llm_count": 1,
        }
        with patch.object(main, "fetch_runninghub_model_registry", new=AsyncMock(return_value=(registry, meta))), patch.object(main, "fetch_runninghub_public_catalog_names", new=AsyncMock(return_value=({"public/text-to-image"}, {"source": "official-site", "count": 1, "error": ""}))), patch.object(main, "save_runninghub_registry_snapshot"):
            payload = await main.runninghub_models_payload({"rh_region": "cn"})

        self.assertEqual(payload["region"], "cn")
        self.assertEqual(payload["model_availability"]["Public Image"], "confirmed")
        self.assertEqual(payload["model_availability"]["Hidden Video"], "unverified")
        self.assertEqual(payload["model_availability"]["Region LLM"], "confirmed")
        self.assertEqual(payload["raw"]["confirmed_count"], 2)
        self.assertNotIn("String Utility", payload["model_availability"])

    async def test_runninghub_generation_definition_does_not_wait_for_llm_catalog(self):
        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, _url, **_kwargs):
                return httpx.Response(503, text="offline")

        llm_fetch = AsyncMock(return_value=([], {}))
        with patch.object(main, "fetch_runninghub_model_registry", wraps=main.fetch_runninghub_model_registry) as registry_fetch, patch.object(main, "fetch_runninghub_llm_models", new=llm_fetch), patch.object(main.httpx, "AsyncClient", return_value=FakeClient()):
            definition = await main.runninghub_model_definition(
                {"rh_region": "cn"},
                "qwen-image-3.0-pro/text-to-image",
            )

        self.assertEqual(definition["endpoint"], "alibaba/qwen-image-3.0-pro/text-to-image")
        self.assertEqual(llm_fetch.await_count, 0)
        self.assertFalse(registry_fetch.await_args.kwargs["include_llm"])

    def test_runninghub_payload_can_read_saved_wallet_key(self):
        payload = main.TestConnectionPayload(
            provider_id="runninghub",
            protocol="runninghub",
            base_url="https://www.runninghub.cn",
        )
        with patch.object(main, "runninghub_wallet_key_value", return_value="test-wallet-key"):
            self.assertEqual(main.api_key_from_payload(payload, "runninghub"), "test-wallet-key")

    def test_runninghub_regions_migrate_legacy_fields_without_cross_contamination(self):
        provider = main.normalize_provider({
            "id": "runninghub",
            "base_url": "https://www.runninghub.cn",
            "image_models": ["cn-image"],
            "model_names": {"cn-image": "国内图片"},
            "rh_apps": [{"id": "cn-app", "title": "国内应用"}],
        })

        self.assertEqual(provider["rh_region"], "cn")
        self.assertEqual(provider["rh_regions"]["cn"]["image_models"], ["cn-image"])
        self.assertEqual(provider["rh_regions"]["cn"]["rh_apps"][0]["id"], "cn-app")
        self.assertEqual(provider["rh_regions"]["global"]["image_models"], [])
        self.assertEqual(provider["rh_regions"]["global"]["rh_apps"], [])

    def test_runninghub_region_provider_switches_base_url_and_catalog(self):
        provider = main.normalize_provider({
            "id": "runninghub",
            "rh_region": "cn",
            "rh_regions": {
                "cn": {"base_url": "https://www.runninghub.cn", "image_models": ["cn-model"], "rh_apps": [{"id": "cn-app"}]},
                "global": {"base_url": "https://www.runninghub.ai", "image_models": ["global-model"], "rh_apps": [{"id": "global-app"}]},
            },
        })

        global_provider = main.runninghub_provider_for_region(provider, "global")
        self.assertEqual(global_provider["base_url"], "https://www.runninghub.ai")
        self.assertEqual(global_provider["image_models"], ["global-model"])
        self.assertEqual(global_provider["rh_apps"][0]["id"], "global-app")
        self.assertEqual(main.runninghub_provider_for_region(provider, "cn")["rh_apps"][0]["id"], "cn-app")

    def test_runninghub_region_forces_its_official_base_url(self):
        provider = main.normalize_provider({
            "id": "runninghub",
            "rh_region": "cn",
            "base_url": "https://www.runninghub.ai",
            "rh_regions": {
                "cn": {"base_url": "https://www.runninghub.ai"},
                "global": {"base_url": "https://www.runninghub.cn"},
            },
        })

        self.assertEqual(main.runninghub_provider_for_region(provider, "cn")["base_url"], "https://www.runninghub.cn")
        self.assertEqual(main.runninghub_provider_for_region(provider, "global")["base_url"], "https://www.runninghub.ai")

    def test_canvas_exposes_only_selected_runninghub_region(self):
        provider = main.normalize_provider({
            "id": "runninghub",
            "rh_region": "cn",
            "rh_regions": {
                "cn": {"base_url": "https://www.runninghub.cn", "image_models": ["cn-model"], "rh_apps": [{"id": "cn-app"}]},
                "global": {"base_url": "https://www.runninghub.ai", "image_models": ["global-model"], "rh_apps": [{"id": "global-app"}]},
            },
        })

        with patch.object(main, "load_api_providers", return_value=[provider]):
            canvas_provider = main.canvas_api_providers()[0]

        self.assertEqual(canvas_provider["rh_region"], "cn")
        self.assertEqual(canvas_provider["image_models"], ["cn-model"])
        self.assertEqual(canvas_provider["rh_apps"][0]["id"], "cn-app")
        self.assertTrue(canvas_provider["rh_regions"]["cn"]["enabled"])
        self.assertFalse(canvas_provider["rh_regions"]["global"]["enabled"])
        self.assertEqual(canvas_provider["rh_regions"]["global"]["image_models"], [])
        self.assertNotIn("global-model", canvas_provider["image_models"])

    def test_runninghub_explicit_region_keeps_sites_and_credentials_independent(self):
        provider = main.normalize_provider({
            "id": "runninghub",
            "rh_region": "global",
            "rh_regions": {
                "cn": {"enabled": True, "image_models": ["cn-model"], "rh_apps": [{"id": "cn-app"}]},
                "global": {"enabled": True, "image_models": ["global-model"], "rh_apps": [{"id": "global-app"}]},
            },
        })

        with patch.object(main, "runninghub_region_key_value", side_effect=lambda region="global", use_wallet=False: f"{region}-key"):
            cn_provider = main.runninghub_provider_for_region(provider, "cn", require_enabled=True)
            global_provider = main.runninghub_provider_for_region(provider, "global", require_enabled=True)
            cn_headers = main.runninghub_app_headers(provider=cn_provider)
            global_headers = main.runninghub_app_headers(provider=global_provider)

        self.assertEqual(provider["rh_region"], "global")
        self.assertEqual(cn_provider["base_url"], "https://www.runninghub.cn")
        self.assertEqual(global_provider["base_url"], "https://www.runninghub.ai")
        self.assertEqual(cn_provider["image_models"], ["cn-model"])
        self.assertEqual(global_provider["image_models"], ["global-model"])
        self.assertEqual(cn_headers["Authorization"], "Bearer cn-key")
        self.assertEqual(global_headers["Authorization"], "Bearer global-key")

    def test_runninghub_capability_catalog_keeps_region_candidates_without_copying_models(self):
        provider = main.normalize_provider({
            "id": "runninghub",
            "rh_region": "global",
            "rh_regions": {
                "cn": {"enabled": True, "image_models": ["cn-only"]},
                "global": {"enabled": True, "image_models": ["global-only"]},
            },
        })

        catalog = main.MODEL_CAPABILITY_REGISTRY.build_catalog([provider])
        capability_provider = catalog["providers"][0]
        models = {
            item["model_id"]: set(item.get("regions") or [])
            for item in capability_provider["models"]
            if item["node_type"] == "image_generation"
        }

        self.assertEqual(models["cn-only"], {"cn"})
        self.assertEqual(models["global-only"], {"global"})
        self.assertEqual(
            {item["region"] for item in capability_provider["regions"] if item["enabled"]},
            {"cn", "global"},
        )

        cn_catalog = main.MODEL_CAPABILITY_REGISTRY.build_catalog([
            main.runninghub_provider_for_region(provider, "cn", require_enabled=True),
        ])
        cn_models = {
            item["model_id"] for item in cn_catalog["providers"][0]["models"]
            if item["node_type"] == "image_generation"
        }
        self.assertEqual(cn_models, {"cn-only"})

    async def test_runninghub_submit_workflow_and_query_use_selected_site_without_network(self):
        provider = main.normalize_provider({
            "id": "runninghub",
            "rh_region": "global",
            "rh_regions": {
                "cn": {"enabled": True, "rh_apps": [{"id": "cn-app", "fields": []}]},
                "global": {"enabled": True, "rh_apps": [{"id": "global-app", "fields": []}]},
            },
        })
        requests = []

        class Response:
            status_code = 200
            text = ""

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def post(self, url, headers=None, json=None, **_kwargs):
                requests.append({"url": url, "headers": headers or {}, "json": json or {}})
                if url.endswith("/task/openapi/outputs"):
                    return Response({"code": 804, "data": {}})
                return Response({"code": 0, "data": {"taskId": "rh-test-task"}})

        with patch.object(main, "get_api_provider_exact", return_value=provider), \
             patch.object(main, "runninghub_region_key_value", side_effect=lambda region="global", use_wallet=False: f"{region}-key"), \
             patch.object(main.httpx, "AsyncClient", return_value=Client()):
            await main.runninghub_submit(main.RunningHubSubmitRequest(webappId="cn-app", region="cn"))
            await main.runninghub_workflow_submit(main.RunningHubWorkflowSubmitRequest(workflowId="global-wf", region="global"))
            provider["rh_regions"]["cn"]["enabled"] = False
            with self.assertRaises(main.HTTPException):
                await main.runninghub_submit(main.RunningHubSubmitRequest(webappId="cn-app", region="cn"))
            result = await main.runninghub_query(taskId="rh-test-task", region="cn")

        self.assertEqual(result["data"]["status"], "RUNNING")
        self.assertEqual(requests[0]["url"], "https://www.runninghub.cn/task/openapi/ai-app/run")
        self.assertEqual(requests[0]["headers"]["Authorization"], "Bearer cn-key")
        self.assertEqual(requests[1]["url"], "https://www.runninghub.ai/task/openapi/create")
        self.assertEqual(requests[1]["headers"]["Authorization"], "Bearer global-key")
        self.assertEqual(requests[2]["url"], "https://www.runninghub.cn/task/openapi/outputs")
        self.assertEqual(requests[2]["json"]["apiKey"], "cn-key")

    def test_runninghub_llm_resolution_uses_explicit_region_key_and_base_url(self):
        provider = main.normalize_provider({
            "id": "runninghub",
            "rh_region": "global",
            "rh_regions": {
                "cn": {"enabled": True, "chat_models": ["cn-chat"]},
                "global": {"enabled": True, "chat_models": ["global-chat"]},
            },
        })

        with patch.object(main, "load_api_providers", return_value=[provider]), \
             patch.object(main, "runninghub_region_key_value", side_effect=lambda region="global", use_wallet=False: f"{region}-key"):
            base_url, headers, model = main.resolve_chat_provider("runninghub", "cn-chat", "", "cn")

        self.assertEqual(base_url, "https://llm.runninghub.cn/v1")
        self.assertEqual(headers["Authorization"], "Bearer cn-key")
        self.assertEqual(model, "cn-chat")
        self.assertEqual(provider["rh_region"], "global")

    async def test_image_task_query_recovers_saved_region_when_client_omits_it(self):
        provider = main.normalize_provider({
            "id": "runninghub",
            "rh_region": "cn",
            "rh_regions": {"cn": {"enabled": True}, "global": {"enabled": True}},
        })
        requests = []

        class Response:
            status_code = 200
            text = ""

            def raise_for_status(self):
                return None

            def json(self):
                return {"code": 804, "data": {}}

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def post(self, url, headers=None, json=None, **_kwargs):
                requests.append({"url": url, "headers": headers or {}, "json": json or {}})
                return Response()

        captured = []

        def select_provider(provider_id, region="", require_enabled=True):
            self.assertFalse(require_enabled)
            captured.append(region)
            return provider

        with patch.object(main.PROJECT_STORAGE, "get_canvas_task", return_value={"region": "cn"}), \
             patch.object(main, "get_api_provider", side_effect=select_provider), \
             patch.object(main, "runninghub_region_key_value", return_value="cn-key"), \
             patch.object(main.httpx, "AsyncClient", return_value=Client()):
            result = await main.query_image_task(main.ImageTaskQueryRequest(provider_id="runninghub", task_id="old-task"))

        self.assertEqual(result["status"], "running")
        self.assertEqual(captured, ["cn"])
        self.assertEqual(requests[0]["url"], "https://www.runninghub.cn/task/openapi/outputs")

    def test_runninghub_region_key_environment_names_are_independent(self):
        self.assertEqual(main.runninghub_api_key_env("cn"), "RUNNINGHUB_CN_API_KEY")
        self.assertEqual(main.runninghub_wallet_key_env("cn"), "RUNNINGHUB_CN_WALLET_API_KEY")
        self.assertEqual(main.runninghub_api_key_env("global"), "RUNNINGHUB_GLOBAL_API_KEY")
        self.assertEqual(main.runninghub_wallet_key_env("global"), "RUNNINGHUB_GLOBAL_WALLET_API_KEY")

    def test_global_legacy_key_is_ignored_when_it_is_the_saved_cn_key(self):
        values = {
            "RUNNINGHUB_API_KEY": "same-cn-key",
            "RUNNINGHUB_CN_API_KEY": "same-cn-key",
        }

        with patch.object(main.os, "getenv", side_effect=lambda key, default="": values.get(key, default)), \
             patch.object(main, "read_api_env_value", side_effect=lambda key: values.get(key, "")):
            self.assertEqual(main.runninghub_region_key_value("global"), "")
            self.assertEqual(main.runninghub_region_key_value("cn"), "same-cn-key")

    def test_runninghub_headers_use_the_key_for_the_explicit_provider_region(self):
        def region_key(region="global", use_wallet=False):
            return f"{region}-{'wallet' if use_wallet else 'free'}-key"

        with patch.object(main, "runninghub_region_key_value", side_effect=region_key):
            cn_headers = main.runninghub_app_headers(
                provider={"id": "runninghub", "rh_region": "cn", "base_url": "https://www.runninghub.cn"}
            )
            global_headers = main.runninghub_app_headers(
                provider={"id": "runninghub", "rh_region": "global", "base_url": "https://www.runninghub.ai"}
            )

        self.assertEqual(cn_headers["Host"], "www.runninghub.cn")
        self.assertEqual(cn_headers["Authorization"], "Bearer cn-free-key")
        self.assertEqual(global_headers["Host"], "www.runninghub.ai")
        self.assertEqual(global_headers["Authorization"], "Bearer global-free-key")

    def test_runninghub_requests_keep_explicit_provider_when_building_headers(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertNotIn("runninghub_app_headers(False, use_wallet)", source)
        self.assertNotIn("runninghub_app_headers(True, use_wallet)", source)
        self.assertNotIn("headers=runninghub_app_headers(True),", source)
        self.assertIn(
            "runninghub_app_headers(False, use_wallet, provider=provider, api_key=api_key)",
            source,
        )
        self.assertIn(
            "runninghub_app_headers(True, use_wallet, provider=provider, api_key=api_key)",
            source,
        )

    def test_api_settings_uses_safe_response_reader_for_connection_requests(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")

        self.assertIn("async function readApiResponse(response", script)
        self.assertIn("return readApiResponse(r, 'RunningHub 验证失败');", script)
        self.assertIn("return readApiResponse(r, tr('api.urlInvalid') || '验证失败');", script)
        self.assertNotIn("if(!r.ok) throw new Error((await r.json()).detail", script)

    def test_runninghub_columns_link_to_their_own_key_pages(self):
        html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")
        for region, host in (("global", "www.runninghub.ai"), ("cn", "www.runninghub.cn")):
            column = html.split(f'data-rh-region="{region}"', 1)[1].split('</fieldset>', 1)[0]
            self.assertIn(host + '/enterprise-api/consumerApi', column)
            self.assertIn(host + '/enterprise-api/sharedApi', column)
        self.assertNotIn('id="rhRegionInput"', html)

    def test_runninghub_site_switches_are_only_in_connection_details(self):
        html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")
        sidebar = html.split('<aside class="sidebar">', 1)[1].split('</aside>', 1)[0]
        self.assertNotIn('toggleRunningHubRegionEnabled', sidebar)
        self.assertEqual(html.count('onchange="toggleRunningHubRegionEnabled('), 2)
        self.assertNotIn('id="rhAppRegionInput"', html)

    def test_volcengine_settings_link_to_official_key_consoles(self):
        html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")

        self.assertIn("https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey", html)
        self.assertIn("https://console.volcengine.com/iam/keymanage/", html)
        self.assertIn("api.volcengineGetArkKey", html)
        self.assertIn("api.volcengineGetAkSk", html)
        self.assertNotIn("https://ark.cn-beijing.volces.com/api/v3/models", html)

    def test_agnes_is_added_from_recommended_apis_before_configuration(self):
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")

        self.assertIn("id:'agnes'", script)
        self.assertIn("add_without_key:true", script)
        self.assertIn("async function addRecommendedApi(index)", script)
        self.assertIn("onclick=\"addRecommendedApi(${index})\"", script)
        self.assertIn("enabled:api.add_without_key ? false : true", script)
        self.assertIn("item.enabled = api.add_without_key ? Boolean(item.has_key) : true;", script)
        self.assertNotIn("|| id === 'agnes';", script)
        self.assertNotIn("refreshIcons();\n    return;\n    const recommendProtocolBadge", script)
        self.assertIn("'modelscope', 'runninghub', 'volcengine', 'ai-money', 'agnes'", script)
        self.assertIn("if(item.id === 'agnes') item.enabled = true;", script)
        self.assertIn("if(item.id === 'agnes') item.enabled = false;", script)
        self.assertIn("https://platform.agnes-ai.com/settings/apiKeys", script)
        self.assertIn("agnes-2.0-flash", script)

    def test_custom_provider_guide_exposes_local_contract_and_bilingual_safe_prompt(self):
        html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")
        script = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")

        self.assertIn('href="/api/provider-integration-guide"', html)
        self.assertIn('href="/api/provider-manifest-schema"', html)
        self.assertIn("copyProviderAgentPrompt()", html)
        self.assertIn("window.StudioI18n?.lang?.() === 'en'", script)
        self.assertIn("Run only Manifest validation, dry-run, fixtures, mocks, and local contract tests.", script)
        self.assertIn("禁止读取、输出、复制或保存 API Key", script)
        self.assertIn("network_requested=false", script)


class ApiSettingsCanvasEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache = ROOT / 'cache'
        cache.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.root = Path(self.temp.name)
        self.storage = ProjectStorage(self.root)
        self.storage.ensure_layout()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), OpenAICompatibleFixtureHandler)
        OpenAICompatibleFixtureHandler.requests = []
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.api_env_file = self.root / "API" / ".env"
        self.api_env_file.parent.mkdir(parents=True, exist_ok=True)
        self.api_env_file.write_text("", encoding="utf-8")
        self.providers_file = self.root / "data" / "api_providers.json"
        self.history_file = self.root / "data" / "history.json"
        self.static_providers_file = self.root / "static" / "runninghub" / "api_providers.json"
        self.patches = [
            patch.object(main, "PROJECT_STORAGE", self.storage),
            patch.object(main, "ASSETS_DIR", str(self.storage.assets_dir)),
            patch.object(main, "OUTPUT_OUTPUT_DIR", str(self.storage.results_dir)),
            patch.object(main, "RESULTS_DIR", str(self.storage.results_dir)),
            patch.object(main, "API_PROVIDERS_FILE", str(self.providers_file)),
            # 保存平台会同步静态模板和工作流存储，必须和正式配置一起隔离。
            patch.object(main, "STATIC_RUNNINGHUB_DIR", str(self.static_providers_file.parent)),
            patch.object(main, "STATIC_RUNNINGHUB_API_PROVIDERS_FILE", str(self.static_providers_file)),
            patch.object(main, "RUNNINGHUB_WORKFLOW_STORE_FILE", str(self.root / "data" / "runninghub_workflows.json")),
            patch.object(main, "DATA_DIR", str(self.root / "data")),
            patch.object(main, "API_ENV_FILE", str(self.api_env_file)),
            patch.object(main, "HISTORY_FILE", str(self.history_file)),
            patch.object(main, "GLOBAL_LOOP", None),
        ]
        for active_patch in self.patches:
            active_patch.start()
        with main.CANVAS_TASK_LOCK:
            main.CANVAS_TASKS.clear()

    async def asyncTearDown(self):
        with main.CANVAS_TASK_LOCK:
            main.CANVAS_TASKS.clear()
        for active_patch in reversed(self.patches):
            active_patch.stop()
        key = main.provider_key_env("canvas-e2e")
        os.environ.pop(key, None)
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)
        self.temp.cleanup()

    async def test_runninghub_app_is_kept_in_top_level_and_selected_region(self):
        app_id = "2089305540787126273"
        entry = {
            "id": app_id,
            "appId": app_id,
            "title": "Laohu Music Digital Human V3",
            "note": "",
            "thumbnail": "https://example.com/cover.png",
            "fields": [],
            "raw": {
                "webappName": "Laohu Music Digital Human V3",
                "nodeInfoList": [{"nodeId": "1", "fieldName": "text", "fieldType": "STRING"}],
            },
            "schemaSyncedAt": 123,
            "enabled": True,
        }
        provider = main.ApiProviderPayload(
            id="runninghub",
            name="RunningHub",
            base_url="https://www.runninghub.ai",
            protocol="runninghub",
            rh_region="global",
            rh_apps=[entry],
            rh_regions={
                "cn": {"base_url": "https://www.runninghub.cn", "rh_apps": []},
                "global": {"base_url": "https://www.runninghub.ai", "rh_apps": [entry]},
            },
        )

        saved = await main.save_providers([provider])
        saved_provider = saved["providers"][0]
        self.assertTrue(self.static_providers_file.is_file(), '静态模板必须写入测试目录')
        self.assertEqual(Path(main.STATIC_RUNNINGHUB_API_PROVIDERS_FILE), self.static_providers_file)
        self.assertIn(app_id, [item["id"] for item in saved_provider["rh_apps"]])
        self.assertIn(app_id, [item["id"] for item in saved_provider["rh_regions"]["global"]["rh_apps"]])

        stored = json.loads(self.providers_file.read_text(encoding="utf-8"))
        stored_provider = next(item for item in stored if item["id"] == "runninghub")
        self.assertIn(app_id, [item["id"] for item in stored_provider["rh_apps"]])
        self.assertIn(app_id, [item["id"] for item in stored_provider["rh_regions"]["global"]["rh_apps"]])

    async def test_saving_cn_runninghub_key_does_not_overwrite_legacy_global_key(self):
        provider = main.ApiProviderPayload(
            id="runninghub",
            name="RunningHub",
            base_url="https://www.runninghub.cn",
            protocol="runninghub",
            rh_region="cn",
            api_key="cn-only-key",
        )

        with patch.object(main, "update_env_values") as update_env:
            await main.save_providers([provider])

        updates = update_env.call_args.args[0]
        self.assertEqual(updates["RUNNINGHUB_CN_API_KEY"], "cn-only-key")
        self.assertNotIn("RUNNINGHUB_API_KEY", updates)
        self.assertNotIn("RUNNINGHUB_GLOBAL_API_KEY", updates)

    async def test_saved_openai_provider_requires_profiles_before_canvas_generation(self):
        provider = main.ApiProviderPayload(
            id="canvas-e2e",
            name="Canvas E2E",
            base_url=self.base_url,
            protocol="openai",
            enabled=True,
            chat_models=["canvas-e2e-text"],
            image_models=["canvas-e2e-image"],
            video_models=["canvas-e2e-video"],
            audio_models=["canvas-e2e-audio"],
            api_key="canvas-e2e-secret",
        )

        saved = await main.save_providers([provider])
        saved_provider = saved["providers"][0]
        self.assertEqual(saved_provider["id"], "canvas-e2e")
        self.assertTrue(saved_provider["has_key"])
        self.assertNotIn("canvas-e2e-secret", json.dumps(saved, ensure_ascii=False))

        capability_response = await main.model_capabilities()
        capabilities = json.loads(capability_response.body) if hasattr(capability_response, "body") else capability_response
        capability_provider = next(item for item in capabilities["providers"] if item["id"] == "canvas-e2e")
        self.assertEqual(
            {(item["model_id"], item["node_type"]) for item in capability_provider["models"]},
            {
                ("canvas-e2e-text", "text_generation"),
                ("canvas-e2e-image", "image_generation"),
                ("canvas-e2e-video", "video_generation"),
                ("canvas-e2e-audio", "audio_generation"),
            },
        )
        self.assertTrue(all(item["validation_mode"] == "blocked" for item in capability_provider["models"]))
        self.assertTrue(all(item["readiness"] == "needs_profile" for item in capability_provider["models"]))
        self.assertTrue(all(item["runnable"] is False for item in capability_provider["models"]))

        with self.assertRaises(main.HTTPException) as text_context:
            await main.canvas_llm(main.CanvasLLMRequest(
                message="请返回画布文本链路结果",
                model="canvas-e2e-text",
                provider="canvas-e2e",
            ))
        self.assertEqual(text_context.exception.status_code, 400)
        self.assertIn("缺少经过核实的能力档案", str(text_context.exception.detail))

        image_task = await main.create_canvas_image_task(main.OnlineImageRequest(
            prompt="一张用于验证智能画布的极简测试图片",
            provider_id="canvas-e2e",
            model="canvas-e2e-image",
            size="1024x1024",
            n=1,
        ))
        task_id = image_task["task_id"]
        completed = None
        for _ in range(100):
            completed = await main.get_canvas_image_task(task_id)
            if completed["status"] in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(completed["status"], "failed")
        self.assertIn("缺少经过核实的能力档案", completed.get("error", ""))
        self.assertFalse(any(item["method"] == "POST" for item in OpenAICompatibleFixtureHandler.requests))


if __name__ == "__main__":
    unittest.main()
