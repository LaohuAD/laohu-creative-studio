import asyncio
import base64
import copy
import hashlib
import json
import logging
import os
import re
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main
from canvas_core.request_boundary import LocalRequestBoundary
from studio_laohu_account import (
    LAOHU_ACCOUNT_LINKS,
    LAOHU_CALLBACK_URI,
    LAOHU_MODELS_URL,
    LAOHU_STATUS_URL,
    LAOHU_TOKEN_URL,
    LAOHU_USERINFO_URL,
    LOGIN_UNAVAILABLE_REASON,
    LaohuAccountState,
    LaohuExecutionAuthRequestBoundary,
    create_laohu_account_router,
)


class LaohuAccountApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".cache")
        self.root = Path(self.temp.name)
        self.now = [1_800_000_000.0]
        self.requests = []
        self.token_status = 200
        self.token_response_payload = None
        self.userinfo_status = 200
        self.models_status = 200
        self.status_status = 200
        self.userinfo_quota = 1234
        self.status_payload = {
            "success": True,
            "data": {
                "quota_display_type": "CUSTOM",
                "quota_per_unit": 1,
                "custom_currency_symbol": "¥",
                "custom_currency_exchange_rate": 1,
                "usd_exchange_rate": 1,
                "display_in_currency": True,
            },
        }
        self.timeout_url = ""
        self.block_token = False
        self.token_entered = asyncio.Event()
        self.release_token = asyncio.Event()
        self.block_userinfo = False
        self.userinfo_entered = asyncio.Event()
        self.release_userinfo = asyncio.Event()
        self.userinfo_plan = []
        self.state = LaohuAccountState(
            base_dir=self.root,
            client_factory=self._client_factory,
            clock=lambda: self.now[0],
        )
        self.manual_key = ["fixture-manual-key"]
        self.manual_preview = ["••••••••-key"]
        self.app = FastAPI()
        self.app.add_middleware(LocalRequestBoundary)
        self.app.add_middleware(LaohuExecutionAuthRequestBoundary, state=self.state)
        self.app.include_router(create_laohu_account_router(
            self.state,
            has_manual_key=lambda: bool(self.manual_key[0]),
            manual_key_preview=lambda: self.manual_preview[0],
        ))
        self.direct_key = ["direct-key-a"]

        @self.app.get("/_test/auth-pin")
        async def auth_pin():
            first = self.state.resolve_model_key(manual_key=lambda: self.direct_key[0])
            self.direct_key[0] = "direct-key-b"
            second = self.state.resolve_model_key(manual_key=lambda: self.direct_key[0])
            return {"same_request_pinned": first == second}

        @self.app.get("/_test/auth-current")
        async def auth_current():
            return {"uses_new_request_key": self.state.resolve_model_key(
                manual_key=lambda: self.direct_key[0],
            ) == "direct-key-b"}
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://127.0.0.1:3000",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        self.temp.cleanup()

    def _client_factory(self, **kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(self._mock_service), **kwargs)

    async def _mock_service(self, request):
        self.requests.append(request)
        if str(request.url) == self.timeout_url:
            raise httpx.ReadTimeout("sensitive-network-detail", request=request)
        if request.method == "POST" and str(request.url) == LAOHU_TOKEN_URL:
            if self.block_token:
                self.token_entered.set()
                await self.release_token.wait()
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            if self.token_response_payload is not None:
                return httpx.Response(200, json=self.token_response_payload)
            return httpx.Response(200, json={
                "access_token": "test-access-token",
                "refresh_token": "test-refresh-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            })
        if request.method == "GET" and str(request.url) == LAOHU_USERINFO_URL:
            plan = self.userinfo_plan.pop(0) if self.userinfo_plan else None
            if plan and plan.get("entered"):
                plan["entered"].set()
            elif self.block_userinfo:
                self.userinfo_entered.set()
            if plan and plan.get("release"):
                await plan["release"].wait()
            elif self.block_userinfo:
                await self.release_userinfo.wait()
            status = plan.get("status", self.userinfo_status) if plan else self.userinfo_status
            if status != 200:
                return httpx.Response(status, json={"error": "test"})
            return httpx.Response(200, json={
                "success": True,
                "data": {"id": "test-account", "username": "Test User", "quota": self.userinfo_quota},
            })
        if request.method == "GET" and str(request.url) == LAOHU_STATUS_URL:
            if self.status_status != 200:
                return httpx.Response(self.status_status, json={"error": "test"})
            return httpx.Response(200, json=self.status_payload)
        if request.method == "GET" and str(request.url) == LAOHU_MODELS_URL:
            if self.models_status != 200:
                return httpx.Response(self.models_status, json={"error": "test"})
            return httpx.Response(200, json={"data": [{"id": "read-only-model"}]})
        return httpx.Response(404)

    def _configure_private_app(self):
        api_dir = self.root / "API"
        api_dir.mkdir(exist_ok=True)
        path = api_dir / ".laohu-login-app.json"
        path.write_text(json.dumps({
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            "redirect_uri": LAOHU_CALLBACK_URI,
        }), encoding="utf-8")
        os.chmod(path, 0o600)
        return path

    async def _start_login(self, operation_id="test-login-operation"):
        self._configure_private_app()
        return await self.client.post(
            "/api/laohu/account/login",
            json={"client_operation_id": operation_id},
            headers={"X-Laohu-Account-Action": "1"},
        )

    def _flow_params(self, response):
        body = response.json()
        query = parse_qs(urlsplit(body["authorization_url"]).query)
        return body, query

    async def _complete_login(self, flow, *, code="test-auth-code"):
        response = await self.client.get(
            "/api/laohu/account/callback",
            params={"code": code, "state": flow["state"][0]},
            follow_redirects=False,
        )
        return response

    async def test_status_without_private_config_is_manual_disconnected_and_secret_free(self):
        response = await self.client.get("/api/laohu/account/status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["mode"], "manual")
        self.assertFalse(body["connected"])
        self.assertFalse(body["login_available"])
        self.assertEqual(body["login_unavailable_reason"], LOGIN_UNAVAILABLE_REASON)
        self.assertIsNone(body["account"])
        self.assertEqual(body["links"], LAOHU_ACCOUNT_LINKS)
        self.assertTrue(body["has_manual_key"])
        self.assertFalse(body["model_authorized"])
        self.assertFalse(body["execution_ready"])
        self.assertNotIn("access_token", response.text)
        self.assertNotIn("refresh_token", response.text)
        self.assertNotIn("client_secret", response.text)
        self.assertEqual(body["active_credential"], {
            "kind": "manual", "configured": True, "label": "手动 API Key", "preview": "••••••••-key",
        })

    async def test_manual_mode_without_saved_key_is_not_reported_as_configured(self):
        self.manual_key[0] = ""
        response = await self.client.get("/api/laohu/account/status")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["has_manual_key"])
        self.assertEqual(response.json()["active_credential"], {
            "kind": "none", "configured": False, "label": "", "preview": "",
        })

    async def test_custom_currency_balance_uses_public_site_quota_formula_and_rounding(self):
        self.userinfo_quota = 9673838
        self.status_payload["data"].update({
            "quota_display_type": "CUSTOM",
            "quota_per_unit": 500000,
            "custom_currency_symbol": "¥",
            "custom_currency_exchange_rate": 1,
            "usd_exchange_rate": 1,
            "display_in_currency": True,
        })
        started = await self._start_login("formatted-custom-balance")
        _body, query = self._flow_params(started)
        await self._complete_login(query)
        response = await self.client.get("/api/laohu/account/status")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["connected"])
        self.assertEqual(response.json()["account"]["balance_display"], "¥19.35")
        self.assertEqual(len([request for request in self.requests if str(request.url) == LAOHU_STATUS_URL]), 1)
        status_request = next(request for request in self.requests if str(request.url) == LAOHU_STATUS_URL)
        self.assertNotIn("authorization", status_request.headers)
        private_connection = self.state._read_session()["connection"]
        self.assertEqual(private_connection["balance_quota"], "9673838")
        self.assertEqual(private_connection["balance_display_version"], 1)
        self.assertNotIn("balance_quota", response.text)

    async def test_zero_quota_is_formatted_with_currency(self):
        self.userinfo_quota = 0
        self.status_payload["data"]["quota_per_unit"] = 500000
        started = await self._start_login("zero-balance")
        _body, query = self._flow_params(started)
        await self._complete_login(query)
        status = await self.client.get("/api/laohu/account/status")

        self.assertTrue(status.json()["connected"])
        self.assertEqual(status.json()["account"]["balance_display"], "¥0")

    async def test_unknown_balance_unit_keeps_account_connected_with_safe_fallback(self):
        self.userinfo_quota = 9673838
        self.status_payload["data"]["quota_display_type"] = "UNRECOGNIZED"
        started = await self._start_login("unknown-balance-unit")
        _body, query = self._flow_params(started)
        await self._complete_login(query)
        status = await self.client.get("/api/laohu/account/status")

        self.assertTrue(status.json()["connected"])
        self.assertTrue(status.json()["model_authorized"])
        self.assertEqual(status.json()["account"]["balance_display"], "请在充值页查看")
        self.assertNotIn("9673838", status.text)

    async def test_unverified_currency_and_token_modes_do_not_guess_a_display(self):
        self.userinfo_quota = 9673838
        for index, display_type in enumerate(("USD", "CNY", "TOKENS")):
            self.now[0] += 31  # Expire the previous negative status-config cache.
            self.status_payload["data"]["quota_display_type"] = display_type
            started = await self._start_login(f"unverified-display-mode-{index}")
            _body, query = self._flow_params(started)
            await self._complete_login(query)
            status = await self.client.get("/api/laohu/account/status")

            self.assertTrue(status.json()["connected"])
            self.assertEqual(status.json()["account"]["balance_display"], "请在充值页查看")
            self.assertNotIn("9673838", status.text)

    async def test_balance_config_http_failure_does_not_disconnect_or_expose_raw_quota(self):
        self.userinfo_quota = 9673838
        self.status_status = 503
        started = await self._start_login("balance-status-error")
        _body, query = self._flow_params(started)
        await self._complete_login(query)
        status = await self.client.get("/api/laohu/account/status")

        self.assertTrue(status.json()["connected"])
        self.assertTrue(status.json()["model_authorized"])
        self.assertEqual(status.json()["account"]["balance_display"], "请在充值页查看")
        self.assertNotIn("9673838", status.text)

    async def test_legacy_raw_balance_is_hidden_then_reformatted_on_status_read(self):
        self._configure_private_app()
        self.userinfo_quota = 9673838
        self.status_payload["data"].update({
            "quota_display_type": "CUSTOM",
            "quota_per_unit": 500000,
            "custom_currency_symbol": "¥",
            "custom_currency_exchange_rate": 1,
            "display_in_currency": True,
        })
        session = self.state._empty_session()
        session.update(mode="account", connection={
            "generation_id": "legacy-balance-connection",
            "access_token": "legacy-test-token",
            "expires_at": self.now[0] + 3600,
            "account": {
                "id": "test-account", "username": "Test User", "balance": 6000000,
                "balance_display": "9673838",
            },
            "model_authorized": True,
        })
        self.state._write_session(session)

        before_refresh = self.state.public_status(lambda: True)
        response = await self.client.get("/api/laohu/account/status")
        stored = self.state._read_session()["connection"]

        self.assertEqual(before_refresh["account"]["balance_display"], "请在充值页查看")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["connected"])
        self.assertEqual(response.json()["account"]["balance_display"], "¥19.35")
        self.assertEqual(stored["balance_quota"], "9673838")
        self.assertEqual(stored["balance_display_version"], 1)
        self.assertNotIn("9673838", response.text)

    async def test_login_without_config_is_unavailable_without_network_or_session_creation(self):
        payload = {"client_operation_id": "same-operation"}
        headers = {"X-Laohu-Account-Action": "1"}

        with patch.object(socket.socket, "connect", side_effect=AssertionError("unexpected network request")) as connect:
            first = await self.client.post("/api/laohu/account/login", json=payload, headers=headers)
            second = await self.client.post("/api/laohu/account/login", json=payload, headers=headers)
            connect.assert_not_called()

        self.assertEqual(first.status_code, 503)
        self.assertEqual(second.status_code, 503)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["detail"], LOGIN_UNAVAILABLE_REASON)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.state.mode(), "manual")

    async def test_configured_login_is_idempotent_pkce_and_keeps_secrets_private(self):
        first = await self._start_login()
        second = await self.client.post(
            "/api/laohu/account/login",
            json={"client_operation_id": "test-login-operation"},
            headers={"X-Laohu-Account-Action": "1"},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), second.json())
        body, query = self._flow_params(first)
        self.assertEqual(urlsplit(body["authorization_url"]).scheme, "https")
        self.assertEqual(urlsplit(body["authorization_url"]).netloc, "api.lao-hu.com")
        self.assertEqual(urlsplit(body["authorization_url"]).path, "/authorize")
        self.assertEqual(query["redirect_uri"], [LAOHU_CALLBACK_URI])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotIn("test-client-secret", body["authorization_url"])
        session = self.state._read_session()
        flow = session["flows"][body["flow_id"]]
        digest = hashlib.sha256(flow["code_verifier"].encode("ascii")).digest()
        expected_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        self.assertEqual(query["code_challenge"], [expected_challenge])
        self.assertEqual(session["mode"], "manual")
        for filename in (".laohu-login-app.json", ".laohu-account-session.json"):
            path = self.root / "API" / filename
            self.assertTrue(path.is_file())
            self.assertFalse(path.is_symlink())
            self.assertTrue(os.access(path, os.R_OK | os.W_OK))
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("test-client-secret", json.dumps(body))
        self.assertEqual(self.requests, [])

    async def test_callback_connects_identity_but_never_returns_token_and_only_marks_readonly_models(self):
        started = await self._start_login()
        _body, query = self._flow_params(started)
        callback = await self._complete_login(query)
        self.assertEqual(callback.status_code, 200)
        self.assertIsNone(callback.headers.get("location"))
        self.assertEqual(callback.headers["cache-control"], "no-store")
        self.assertEqual(callback.headers["referrer-policy"], "no-referrer")
        csp = callback.headers["content-security-policy"]
        nonce_match = re.fullmatch(
            r"default-src 'none'; script-src 'nonce-([A-Za-z0-9_-]+)'; base-uri 'none'; frame-ancestors 'none'",
            csp,
        )
        self.assertIsNotNone(nonce_match)
        self.assertIn(
            f'history.replaceState(null,"","/api/laohu/account/callback/complete");',
            callback.text,
        )
        self.assertIn(f'<script nonce="{nonce_match.group(1)}">', callback.text)
        self.assertIn("history.replaceState(null,\"\",\"/api/laohu/account/callback/complete\");", callback.text)
        self.assertLess(callback.text.index("history.replaceState"), callback.text.index("window.close()"))
        # The app intentionally severs popup.opener. A verified OAuth callback may
        # close only its own script-opened window, without consulting or touching opener.
        self.assertNotIn("window.opener", callback.text)
        self.assertIn("window.close()", callback.text)
        self.assertIn("请关闭此页返回画梦枋", callback.text)
        self.assertNotIn("授权结果已返回，请回到画梦枋查看。", callback.text)
        self.assertIn("<body></body>", callback.text)

        poll = await self.client.get(f"/api/laohu/account/login/{started.json()['flow_id']}")
        status = await self.client.get("/api/laohu/account/status")
        complete = await self.client.get("/api/laohu/account/callback/complete")
        self.assertEqual(poll.status_code, 200)
        self.assertEqual(poll.json()["status"], "succeeded")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(complete.status_code, 200)
        self.assertNotIn("授权结果已返回", complete.text)
        self.assertNotIn("请回到老胡画梦枋", complete.text)
        self.assertNotIn("<p", complete.text)
        public = status.json()
        self.assertEqual(public["mode"], "account")
        self.assertTrue(public["connected"])
        self.assertEqual(public["account"], {
            "id": "test-account", "username": "Test User", "balance_display": "¥1,234",
        })
        self.assertEqual(public["active_credential"], {
            "kind": "account", "configured": True, "label": "登录自动配置", "preview": "••••••••",
        })
        self.assertTrue(public["model_authorized"])
        self.assertFalse(public["execution_ready"])
        self.assertIn("账户模型凭据尚未接入共享模型执行链", public["model_unavailable_reason"])
        for secret in ("test-access-token", "test-refresh-token", "test-client-secret", query["state"][0], "test-auth-code"):
            self.assertNotIn(secret, callback.text + poll.text + status.text)
        self.assertEqual([request.url for request in self.requests], [
            httpx.URL(LAOHU_TOKEN_URL), httpx.URL(LAOHU_USERINFO_URL),
            httpx.URL(LAOHU_STATUS_URL), httpx.URL(LAOHU_MODELS_URL),
        ])
        token_request = self.requests[0]
        self.assertEqual(token_request.headers.get("content-type"), "application/json")
        self.assertTrue(token_request.headers.get("authorization", "").startswith("Basic "))
        self.assertEqual(json.loads(token_request.content)["code"], "test-auth-code")
        self.assertEqual(self.requests[1].headers["authorization"], "Bearer test-access-token")
        self.assertNotIn("authorization", self.requests[2].headers)
        self.assertEqual(self.requests[3].headers["authorization"], "Bearer test-access-token")

    async def test_callback_flow_keeps_only_safe_stage_status_and_timeout_diagnostics(self):
        for operation_id, url, expected_message in (
            ("token-timeout", LAOHU_TOKEN_URL, "令牌交换网络超时"),
            ("userinfo-timeout", LAOHU_USERINFO_URL, "账户身份读取网络超时"),
        ):
            self.timeout_url = url
            started = await self._start_login(operation_id)
            _body, query = self._flow_params(started)
            callback = await self._complete_login(query)
            flow = await self.client.get(f"/api/laohu/account/login/{started.json()['flow_id']}")
            self.assertEqual(callback.status_code, 200)
            self.assertEqual(flow.json()["status"], "failed")
            self.assertEqual(flow.json()["message"], expected_message)
            self.assertNotIn("sensitive-network-detail", callback.text + flow.text)
            self.assertNotIn("test-auth-code", callback.text + flow.text)

        self.timeout_url = ""
        for operation_id, failing_stage, expected_message in (
            ("token-http-status", "token", "令牌交换 HTTP 503"),
            ("userinfo-http-status", "userinfo", "账户身份 HTTP 502"),
        ):
            self.token_status = 503 if failing_stage == "token" else 200
            self.userinfo_status = 502 if failing_stage == "userinfo" else 200
            started = await self._start_login(operation_id)
            _body, query = self._flow_params(started)
            callback = await self._complete_login(query)
            flow = await self.client.get(f"/api/laohu/account/login/{started.json()['flow_id']}")
            self.assertEqual(callback.status_code, 200)
            self.assertEqual(flow.json()["status"], "failed")
            self.assertIn(expected_message, flow.json()["message"])
            self.assertNotIn("invalid_grant", callback.text + flow.text)
            self.assertNotIn("test-auth-code", callback.text + flow.text)
        self.token_status = 200
        self.userinfo_status = 200

    async def test_token_exchange_accepts_only_standard_or_explicit_success_data_envelopes(self):
        self.token_response_payload = {
            "success": True,
            "data": {
                "access_token": "wrapped-access-secret",
                "refresh_token": "wrapped-refresh-secret",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        }
        started = await self._start_login("wrapped-token")
        _body, query = self._flow_params(started)
        callback = await self._complete_login(query)
        flow = await self.client.get(f"/api/laohu/account/login/{started.json()['flow_id']}")
        status = await self.client.get("/api/laohu/account/status")
        self.assertEqual(callback.status_code, 200)
        self.assertEqual(flow.json()["status"], "succeeded")
        self.assertTrue(status.json()["connected"])
        self.assertTrue(status.json()["model_authorized"])
        self.assertFalse(status.json()["execution_ready"])
        self.assertEqual(self.requests[1].headers["authorization"], "Bearer wrapped-access-secret")
        self.assertNotIn("authorization", self.requests[2].headers)
        self.assertEqual(self.requests[3].headers["authorization"], "Bearer wrapped-access-secret")
        for secret in ("wrapped-access-secret", "wrapped-refresh-secret", "test-auth-code"):
            self.assertNotIn(secret, callback.text + flow.text + status.text)

    async def test_token_exchange_error_wrong_type_and_missing_token_fail_with_shape_only(self):
        cases = (
            (
                "error-envelope",
                {
                    "success": False,
                    "error": "never-expose-error-value",
                    "data": {"access_token": "must-not-use-error-token", "token_type": "Bearer"},
                },
                ("success=false", "error", "access_token", "token_type=present"),
                ("never-expose-error-value", "must-not-use-error-token"),
            ),
            (
                "wrong-type",
                {"access_token": "must-not-use-wrong-type-token", "token_type": {"kind": "Bearer"}},
                ("success=missing", "access_token", "token_type=present"),
                ("must-not-use-wrong-type-token", "Bearer"),
            ),
            (
                "missing-token",
                {"token_type": "Bearer", "expires_in": 3600},
                ("success=missing", "token_type=present"),
                ("Bearer",),
            ),
        )
        for operation_id, payload, expected_fields, forbidden_values in cases:
            with self.subTest(operation_id=operation_id):
                self.token_response_payload = payload
                started = await self._start_login(operation_id)
                _body, query = self._flow_params(started)
                callback = await self._complete_login(query)
                flow = await self.client.get(f"/api/laohu/account/login/{started.json()['flow_id']}")
                status = await self.client.get("/api/laohu/account/status")
                self.assertEqual(callback.status_code, 200)
                self.assertEqual(flow.json()["status"], "failed")
                for expected in expected_fields:
                    self.assertIn(expected, flow.json()["message"])
                for forbidden in forbidden_values + ("test-auth-code", "test-client-secret"):
                    self.assertNotIn(forbidden, flow.json()["message"] + callback.text + flow.text + status.text)
                self.assertFalse(status.json()["connected"])
                self.assertFalse(status.json()["model_authorized"])
                self.assertFalse(status.json()["execution_ready"])
                self.assertIsNone(self.state._read_session()["connection"])
        self.token_response_payload = None

    async def test_model_directory_denial_is_not_misreported_as_execution_ready(self):
        self.models_status = 401
        started = await self._start_login("model-denied")
        _body, query = self._flow_params(started)
        await self._complete_login(query)

        status = (await self.client.get("/api/laohu/account/status")).json()
        self.assertTrue(status["connected"])
        self.assertFalse(status["model_authorized"])
        self.assertFalse(status["execution_ready"])
        self.assertEqual(status["active_credential"], {
            "kind": "none", "configured": False, "label": "", "preview": "",
        })
        self.assertIn("尚未通过模型目录授权核验", status["model_unavailable_reason"])
        with patch.object(main, "LAOHU_ACCOUNT_STATE", self.state):
            with self.assertRaises(main.HTTPException) as raised:
                main.api_headers(provider={"id": "ai-money", "name": "laohu", "protocol": "openai"}, model="test")
        self.assertEqual(raised.exception.status_code, 403)

    async def test_invalid_state_and_wrong_callback_host_do_not_exchange_code(self):
        started = await self._start_login("state-check")
        wrong_state = await self.client.get(
            "/api/laohu/account/callback",
            params={"code": "test-auth-code", "state": "wrong-state"},
            follow_redirects=False,
        )
        wrong_host = await self.client.get(
            "/api/laohu/account/callback",
            params={"code": "test-auth-code", "state": "anything"},
            headers={"Host": "localhost:3000"},
            follow_redirects=False,
        )
        self.assertEqual(wrong_state.status_code, 200)
        self.assertEqual(wrong_host.status_code, 403)
        self.assertEqual(self.requests, [])
        self.assertEqual((await self.client.get(f"/api/laohu/account/login/{started.json()['flow_id']}")).json()["status"], "pending")

    async def test_exact_provider_callback_navigation_passes_boundary_but_random_state_cannot_mutate(self):
        started = await self._start_login("provider-navigation")
        session_before = self.state.session_path.read_bytes()
        fetch_headers = {
            "Host": "127.0.0.1:3000",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
            "Referer": "https://api.lao-hu.com/authorize",
        }

        callback = await self.client.get(
            "/api/laohu/account/callback",
            params={"code": "fake-untrusted-code", "state": "random-state"},
            headers=fetch_headers,
            follow_redirects=False,
        )
        status_cross_site = await self.client.get(
            "/api/laohu/account/status", headers=fetch_headers
        )
        complete_cross_site = await self.client.get(
            "/api/laohu/account/callback/complete", headers=fetch_headers
        )
        wrong_referrer = await self.client.get(
            "/api/laohu/account/callback",
            params={"code": "fake-untrusted-code", "state": "random-state"},
            headers={**fetch_headers, "Referer": "https://attacker.example/authorize"},
            follow_redirects=False,
        )
        reload_without_referrer = await self.client.get(
            "/api/laohu/account/callback",
            params={"code": "fake-untrusted-code", "state": "random-state"},
            headers={
                "Host": "127.0.0.1:3000",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document",
            },
            follow_redirects=False,
        )

        self.assertEqual(callback.status_code, 200)
        self.assertIsNone(callback.headers.get("location"))
        self.assertIn("history.replaceState", callback.text)
        self.assertNotIn("window.close()", callback.text)
        self.assertNotIn("请关闭此页返回画梦枋", callback.text)
        self.assertEqual(status_cross_site.status_code, 403)
        self.assertEqual(complete_cross_site.status_code, 403)
        self.assertEqual(wrong_referrer.status_code, 403)
        self.assertEqual(reload_without_referrer.status_code, 200)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.state.session_path.read_bytes(), session_before)
        flow_status = await self.client.get(f"/api/laohu/account/login/{started.json()['flow_id']}")
        self.assertEqual(flow_status.json()["status"], "pending")

    async def test_lan_peer_and_lan_host_cannot_read_or_change_local_account_state(self):
        remote = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, client=("192.168.1.44", 4321)),
            base_url="http://127.0.0.1:3000",
        )
        try:
            spoofed_loopback_host = await remote.get("/api/laohu/account/status", headers={"Host": "127.0.0.1:3000"})
            spoofed_callback = await remote.get(
                "/api/laohu/account/callback?code=unused&state=unused",
                headers={"Host": "127.0.0.1:3000"},
            )
            spoofed_provider_navigation = await remote.get(
                "/api/laohu/account/callback?code=unused&state=unused",
                headers={
                    "Host": "127.0.0.1:3000",
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Dest": "document",
                    "Referer": "https://api.lao-hu.com/authorize",
                },
            )
            spoofed_complete = await remote.get(
                "/api/laohu/account/callback/complete",
                headers={"Host": "127.0.0.1:3000"},
            )
            spoofed_logout = await remote.post(
                "/api/laohu/account/logout",
                headers={"Host": "127.0.0.1:3000", "X-Laohu-Account-Action": "1"},
            )
        finally:
            await remote.aclose()
        lan_host = await self.client.get("/api/laohu/account/status", headers={"Host": "192.168.1.44:3000"})
        cross_origin = await self.client.get(
            "/api/laohu/account/status", headers={"Origin": "https://attacker.example"}
        )
        self.assertEqual(spoofed_loopback_host.status_code, 403)
        self.assertEqual(spoofed_callback.status_code, 403)
        self.assertEqual(spoofed_provider_navigation.status_code, 403)
        self.assertEqual(spoofed_complete.status_code, 403)
        self.assertEqual(spoofed_logout.status_code, 403)
        self.assertEqual(lan_host.status_code, 403)
        self.assertEqual(cross_origin.status_code, 403)

    async def test_action_requests_require_custom_header_and_same_origin(self):
        missing_header = await self.client.post("/api/laohu/account/logout")
        same_origin = await self.client.post(
            "/api/laohu/account/logout",
            headers={"X-Laohu-Account-Action": "1", "Origin": "http://127.0.0.1:3000"},
        )
        cross_origin = await self.client.post(
            "/api/laohu/account/logout",
            headers={"X-Laohu-Account-Action": "1", "Origin": "https://attacker.example"},
        )
        self.assertEqual(missing_header.status_code, 403)
        self.assertEqual(same_origin.status_code, 200)
        self.assertEqual(cross_origin.status_code, 403)

    async def test_explicit_mode_selection_preserves_connection_and_logout_does_not_fallback(self):
        started = await self._start_login("explicit-mode")
        _body, query = self._flow_params(started)
        await self._complete_login(query)
        action_headers = {"X-Laohu-Account-Action": "1"}

        manual = await self.client.post(
            "/api/laohu/account/mode", json={"mode": "manual"}, headers=action_headers
        )
        self.assertEqual(manual.status_code, 200)
        self.assertEqual(manual.json()["mode"], "manual")
        self.assertTrue(manual.json()["connected"])
        self.assertEqual(manual.json()["active_credential"], {
            "kind": "manual", "configured": True, "label": "手动 API Key", "preview": "••••••••-key",
        })
        account = await self.client.post(
            "/api/laohu/account/mode", json={"mode": "account"}, headers=action_headers
        )
        self.assertEqual(account.status_code, 200)
        self.assertEqual(account.json()["mode"], "account")
        self.assertEqual(account.json()["active_credential"], {
            "kind": "account", "configured": True, "label": "登录自动配置", "preview": "••••••••",
        })

        logged_out = await self.client.post("/api/laohu/account/logout", headers=action_headers)
        refused_reselect = await self.client.post(
            "/api/laohu/account/mode", json={"mode": "account"}, headers=action_headers
        )
        current = self.state.public_status(lambda: True)
        self.assertEqual(logged_out.status_code, 200)
        self.assertEqual(logged_out.json()["mode"], "account")
        self.assertEqual(refused_reselect.status_code, 409)
        self.assertEqual(current["mode"], "account")
        self.assertFalse(current["connected"])
        self.assertTrue(current["has_manual_key"])
        self.assertEqual(current["active_credential"], {
            "kind": "none", "configured": False, "label": "", "preview": "",
        })

    async def test_late_callback_cannot_override_manual_choice_or_newer_login(self):
        first = await self._start_login("older-operation")
        _first_body, first_query = self._flow_params(first)
        self.block_token = True
        pending_callback = asyncio.create_task(self.state.handle_callback("test-auth-code", first_query["state"][0]))
        await asyncio.wait_for(self.token_entered.wait(), timeout=2)
        self.state.set_manual_mode()
        self.release_token.set()
        self.assertTrue(await asyncio.wait_for(pending_callback, timeout=2))
        first_status = self.state.flow_status(first.json()["flow_id"])
        self.assertEqual(first_status["status"], "succeeded")
        self.assertIn("账户选择已变化", first_status["message"])
        current = self.state.public_status(lambda: True)
        self.assertEqual(current["mode"], "manual")
        self.assertFalse(current["connected"])
        self.assertNotIn("test-access-token", self.state.session_path.read_text(encoding="utf-8"))

        self.block_token = False
        second = await self._start_login("newer-operation")
        third = await self.client.post(
            "/api/laohu/account/login",
            json={"client_operation_id": "latest-operation"},
            headers={"X-Laohu-Account-Action": "1"},
        )
        second_flow = self._flow_params(second)[1]
        third_flow = self._flow_params(third)[1]
        await self._complete_login(second_flow)
        after_old = self.state.public_status(lambda: True)
        self.assertEqual(after_old["mode"], "manual")
        self.assertFalse(after_old["connected"])
        await self._complete_login(third_flow)
        after_latest = self.state.public_status(lambda: True)
        self.assertEqual(after_latest["mode"], "account")
        self.assertTrue(after_latest["connected"])

    async def test_expired_exchanging_flow_is_unknown_failure_and_never_redeems_again(self):
        started = await self._start_login("expire-during-exchange")
        flow_id = started.json()["flow_id"]
        session = self.state._read_session()
        flow = session["flows"][flow_id]
        flow["status"] = "exchanging"
        self.state._write_session(session)
        self.now[0] += 601

        polled = self.state.flow_status(flow_id)
        callback_result = await self.state.handle_callback("test-auth-code", flow["state"])
        self.assertEqual(polled["status"], "failed")
        self.assertIn("状态未知", polled["message"])
        self.assertFalse(callback_result)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.state.mode(), "manual")

    async def test_refresh_preserves_transient_connection_and_quarantines_rejected_access(self):
        started = await self._start_login("refresh-status")
        _body, query = self._flow_params(started)
        await self._complete_login(query)
        headers = {"X-Laohu-Account-Action": "1"}

        self.userinfo_status = 503
        server_error = await self.client.post("/api/laohu/account/refresh", headers=headers)
        self.assertEqual(server_error.status_code, 502)
        still_connected = self.state.public_status(lambda: True)
        self.assertTrue(still_connected["connected"])
        self.assertEqual(still_connected["mode"], "account")

        # A userinfo 401 is not an OAuth refresh-token revocation receipt. Keep
        # the stored connection so a transient/endpoint-specific rejection does
        # not destroy credentials or silently select the manual key.
        self.userinfo_status = 401
        rejected = await self.client.post("/api/laohu/account/refresh", headers=headers)
        after_rejection = self.state.public_status(lambda: True)
        self.assertEqual(rejected.status_code, 401)
        self.assertFalse(after_rejection["connected"])
        self.assertEqual(after_rejection["connection_state"], "reauth_required")
        self.assertTrue(after_rejection["reauth_required"])
        self.assertEqual(after_rejection["account"]["id"], "test-account")
        self.assertEqual(after_rejection["mode"], "account")
        self.assertFalse(self.state.account_model_credential_available())

    async def test_models_transient_failure_does_not_downgrade_known_authorization(self):
        started = await self._start_login("models-transient-refresh")
        _body, query = self._flow_params(started)
        await self._complete_login(query)
        self.assertTrue(self.state.public_status(lambda: True)["model_authorized"])

        self.models_status = 503
        refreshed = await self.client.post(
            "/api/laohu/account/refresh",
            headers={"X-Laohu-Account-Action": "1"},
        )
        status = self.state.public_status(lambda: True)

        self.assertEqual(refreshed.status_code, 200)
        self.assertTrue(status["connected"])
        self.assertTrue(status["model_authorized"])

        self.timeout_url = LAOHU_MODELS_URL
        second_refresh = await self.client.post(
            "/api/laohu/account/refresh",
            headers={"X-Laohu-Account-Action": "1"},
        )
        status_after_timeout = self.state.public_status(lambda: True)
        self.assertEqual(second_refresh.status_code, 200)
        self.assertTrue(status_after_timeout["model_authorized"])

    async def test_expired_connection_without_refresh_token_requires_explicit_relogin(self):
        self._configure_private_app()
        self.state._write_session({
            "version": 1,
            "mode": "account",
            "selection_revision": 2,
            "latest_login_flow_id": "",
            "flows": {},
            "connection": {
                "generation_id": "expired-without-refresh",
                "access_token": "expired-test-token",
                "refresh_token": "",
                "expires_at": self.now[0] - 1,
                "account": {"id": "test-account", "username": "test", "balance_display": "1"},
                "model_authorized": True,
            },
        })

        result = await self.client.get("/api/laohu/account/status")
        status = result.json()

        self.assertEqual(result.status_code, 200)
        self.assertFalse(status["connected"])
        self.assertEqual(status["connection_state"], "reauth_required")
        self.assertTrue(status["reauth_required"])
        self.assertEqual(status["active_credential"]["kind"], "none")
        self.assertEqual(status["account"]["id"], "test-account")
        self.assertEqual(status["account"]["balance_display"], "请在充值页查看")

    async def test_restarted_state_reads_the_same_valid_private_connection(self):
        started = await self._start_login("restart-persisted-connection")
        _body, query = self._flow_params(started)
        completed = await self._complete_login(query)
        self.assertEqual(completed.status_code, 200)

        restarted = LaohuAccountState(
            base_dir=self.root,
            client_factory=self._client_factory,
            clock=lambda: self.now[0],
        )
        status = restarted.public_status(lambda: True)

        self.assertTrue(status["connected"])
        self.assertTrue(status["model_authorized"])
        self.assertEqual(status["connection_state"], "connected")
        self.assertEqual(status["active_credential"]["preview"], "••••••••")
        self.assertNotIn("test-access-token", json.dumps(status))

    async def test_late_refresh_result_after_logout_does_not_resurrect_connection(self):
        started = await self._start_login("logout-during-account-refresh")
        _body, query = self._flow_params(started)
        await self._complete_login(query)
        self.block_userinfo = True

        refresh_task = asyncio.create_task(self.state.refresh_connection())
        await asyncio.wait_for(self.userinfo_entered.wait(), timeout=2)
        self.state.logout()
        self.release_userinfo.set()
        await refresh_task

        status = self.state.public_status(lambda: True)
        self.assertEqual(status["mode"], "account")
        self.assertFalse(status["connected"])
        self.assertEqual(status["connection_state"], "disconnected")

    async def test_older_successful_refresh_cannot_undo_newer_rejected_access_result(self):
        started = await self._start_login("refresh-response-order")
        _body, query = self._flow_params(started)
        await self._complete_login(query)
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        self.userinfo_plan = [
            {"status": 200, "entered": first_entered, "release": release_first},
            {"status": 401},
        ]

        older_success = asyncio.create_task(self.state.refresh_connection())
        await asyncio.wait_for(first_entered.wait(), timeout=2)
        with self.assertRaises(HTTPException) as rejected:
            await self.state.refresh_connection()
        self.assertEqual(rejected.exception.status_code, 401)
        release_first.set()
        await older_success

        session = self.state._read_session()
        connection = session["connection"]
        status = self.state.public_status(lambda: True)
        self.assertEqual(connection["access_validation_state"], "rejected")
        self.assertFalse(status["connected"])
        self.assertTrue(status["reauth_required"])

    async def test_expired_access_token_is_not_reported_as_connected(self):
        self._configure_private_app()
        self.state._write_session({
            "version": 1,
            "mode": "account",
            "selection_revision": 2,
            "latest_login_flow_id": "",
            "flows": {},
            "connection": {
                "access_token": "expired-test-token",
                "expires_at": self.now[0] - 1,
                "account": {"id": "test-account", "username": "test", "balance_display": "1"},
                "model_authorized": True,
            },
        })
        public = self.state.public_status(lambda: True, lambda: "••••••••test")
        self.assertEqual(public["mode"], "account")
        self.assertFalse(public["connected"])
        self.assertTrue(public["reauth_required"])
        self.assertEqual(public["connection_state"], "reauth_required")
        self.assertEqual(public["account"]["id"], "test-account")
        self.assertEqual(public["active_credential"]["kind"], "none")
        self.assertFalse(public["execution_ready"])
        self.assertEqual(public["active_credential"], {
            "kind": "none", "configured": False, "label": "", "preview": "",
        })

    async def test_direct_request_credential_pin_resets_between_http_requests(self):
        pinned = await self.client.get("/_test/auth-pin")
        next_request = await self.client.get("/_test/auth-current")
        self.assertEqual(pinned.status_code, 200)
        self.assertTrue(pinned.json()["same_request_pinned"])
        self.assertEqual(next_request.status_code, 200)
        self.assertTrue(next_request.json()["uses_new_request_key"])

    async def test_execution_binding_keeps_original_manual_key_after_mode_change(self):
        self.state.bind_execution("studio-task-1", manual_key="manual-snapshot-key")
        session = self.state._read_session()
        session["mode"] = "account"
        session["connection"] = {
            "generation_id": "account-generation-2",
            "access_token": "new-account-token",
            "expires_at": self.now[0] + 3600,
            "account": {"id": "test-account", "username": "Test User", "balance_display": "1234"},
            "model_authorized": True,
        }
        self.state._write_session(session)

        with self.state.execution_auth_scope("studio-task-1"):
            selected = self.state.resolve_model_key(manual_key=lambda: "new-manual-key")
        self.assertEqual(selected, "manual-snapshot-key")
        self.assertEqual(self.state.resolve_model_key(manual_key=lambda: "new-manual-key"), "new-account-token")

        self.assertTrue(self.state.release_execution("studio-task-1"))
        with self.state.execution_auth_scope("studio-task-1"):
            with self.assertRaises(main.HTTPException) as missing:
                self.state.resolve_model_key(manual_key=lambda: "must-not-fallback")
        self.assertEqual(missing.exception.status_code, 409)

    async def test_account_binding_survives_current_connection_replacement_but_not_expiry(self):
        session = self.state._empty_session()
        session.update(mode="account", connection={
            "generation_id": "account-generation-1",
            "access_token": "old-account-token",
            "expires_at": self.now[0] + 3600,
            "account": {"id": "test-account", "username": "Test User", "balance_display": "1234"},
            "model_authorized": True,
        })
        self.state._write_session(session)
        self.state.bind_execution("studio-task-account", manual_key=lambda: "unused-manual-key")

        session = self.state._read_session()
        session["connection"].update(
            generation_id="account-generation-2",
            access_token="new-account-token",
        )
        self.state._write_session(session)
        with self.state.execution_auth_scope("studio-task-account"):
            self.assertEqual(
                self.state.resolve_model_key(manual_key=lambda: "must-not-fallback"),
                "old-account-token",
            )

        self.now[0] += 3601
        with self.state.execution_auth_scope("studio-task-account"):
            with self.assertRaises(main.HTTPException) as expired:
                self.state.resolve_model_key(manual_key=lambda: "must-not-fallback")
        self.assertEqual(expired.exception.status_code, 401)

    async def test_execution_ready_requires_all_auth_hooks_and_account_mode(self):
        session = self.state._empty_session()
        session.update(mode="account", connection={
            "generation_id": "account-generation-1",
            "access_token": "test-account-token",
            "expires_at": self.now[0] + 3600,
            "account": {"id": "test-account", "username": "Test User", "balance_display": "1234"},
            "model_authorized": True,
        })
        self.state._write_session(session)
        self.assertFalse(self.state.public_status(lambda: True)["execution_ready"])
        self.state.set_execution_hooks_ready(True)
        self.assertTrue(self.state.public_status(lambda: True)["execution_ready"])
        self.state.set_manual_mode()
        self.assertFalse(self.state.public_status(lambda: True)["execution_ready"])

    async def test_logout_is_local_idempotent_and_refresh_without_connection_is_rejected(self):
        headers = {"X-Laohu-Account-Action": "1"}
        first = await self.client.post("/api/laohu/account/logout", headers=headers)
        second = await self.client.post("/api/laohu/account/logout", headers=headers)
        refresh = await self.client.post("/api/laohu/account/refresh", headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["mode"], "manual")
        self.assertTrue(first.json()["has_manual_key"])
        self.assertEqual(refresh.status_code, 409)

    async def test_provider_put_then_explicit_manual_switch_uses_new_key_without_rebinding_task(self):
        api_dir = self.root / "API"
        api_dir.mkdir(exist_ok=True)
        api_env = api_dir / ".env"
        api_env.write_text("", encoding="utf-8")
        self.state.bind_execution("accepted-old-manual-task", manual_key="old-manual-key")
        session = self.state._read_session()
        session.update(mode="account", connection={
            "generation_id": "account-generation-save-test",
            "access_token": "account-save-test-token",
            "expires_at": self.now[0] + 3600,
            "account": {"id": "test-account", "username": "test", "balance_display": "¥1"},
            "model_authorized": True,
        })
        self.state._write_session(session)
        provider_payload = main.ApiProviderPayload(
            id="ai-money", name="laohu", base_url="https://api.lao-hu.com",
            protocol="openai", api_key="new-manual-key",
        )
        headers = {"X-Laohu-Account-Action": "1"}

        with patch.object(main, "LAOHU_ACCOUNT_STATE", self.state), \
             patch.object(main, "API_ENV_FILE", str(api_env)), \
             patch.object(main, "save_api_providers"), \
             patch.object(main, "reload_env_globals", lambda: None), \
             patch.dict(os.environ, {
                 "API_PROVIDER_LAOHU_KEY": "old-manual-key",
                 "API_PROVIDER_AI_MONEY_KEY": "",
             }):
            saved = await main.save_providers([provider_payload])
            public_provider = saved["providers"][0]
            self.assertTrue(public_provider["has_key"])  # Account is still the active credential.
            self.assertTrue(public_provider["has_manual_key"])  # The submitted manual Key was saved too.
            self.assertEqual(public_provider["key_preview"], "账户授权")
            self.assertNotIn("new-manual-key", json.dumps(saved, ensure_ascii=False))
            self.assertEqual(main.laohu_manual_key_preview(), "••••••••-key")

            account_request = self.state._begin_auth_request()
            try:
                self.assertEqual(main.provider_env_key_value("ai-money"), "account-save-test-token")
            finally:
                self.state._end_auth_request(account_request)
            with self.state.execution_auth_scope("accepted-old-manual-task"):
                self.assertEqual(main.provider_env_key_value("ai-money"), "old-manual-key")

            self.manual_key[0] = "new-manual-key"
            self.manual_preview[0] = main.laohu_manual_key_preview()
            switched = await self.client.post(
                "/api/laohu/account/mode", json={"mode": "manual"}, headers=headers,
            )
            self.assertEqual(switched.status_code, 200)
            self.assertEqual(switched.json()["active_credential"], {
                "kind": "manual", "configured": True,
                "label": "手动 API Key", "preview": "••••••••-key",
            })
            manual_request = self.state._begin_auth_request()
            try:
                self.assertEqual(main.provider_env_key_value("ai-money"), "new-manual-key")
            finally:
                self.state._end_auth_request(manual_request)
            with self.state.execution_auth_scope("accepted-old-manual-task"):
                self.assertEqual(main.provider_env_key_value("ai-money"), "old-manual-key")


class LaohuPayloadOriginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".cache")
        self.state = LaohuAccountState(base_dir=self.temp.name)
        session = self.state._empty_session()
        session.update(mode="account", connection={
            "generation_id": "origin-test-account",
            "access_token": "fixture-origin-account-token",
            "expires_at": 4_000_000_000,
            "account": {"id": "test-account", "username": "test", "balance_display": "1"},
            "model_authorized": True,
        })
        self.state._write_session(session)
        self.requests = []
        original_client = httpx.AsyncClient

        def handle(request):
            self.requests.append(request)
            return httpx.Response(200, json={"data": []})

        self.patches = [
            patch.object(main, "LAOHU_ACCOUNT_STATE", self.state),
            patch.object(main, "manual_provider_env_key_value", return_value="fixture-manual-key"),
            patch.object(main.httpx, "AsyncClient", side_effect=lambda **kw: original_client(
                **{**kw, "transport": httpx.MockTransport(handle)},
            )),
        ]
        for item in self.patches:
            item.start()
        self.request_token = self.state._begin_auth_request()

    async def asyncTearDown(self):
        self.state._end_auth_request(self.request_token)
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    async def test_three_provider_posts_reject_foreign_origins_before_any_request(self):
        for handler in (main.test_provider_connection, main.probe_async_endpoint,
                        main.fetch_upstream_models_from_payload):
            with self.subTest(handler=handler.__name__):
                payload = main.TestConnectionPayload(
                    provider_id="ai-money", base_url="https://foreign.example", api_key="typed-manual-key",
                )
                with self.assertRaises(HTTPException) as error:
                    await handler(payload)
                self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.requests, [], "账户令牌不能在拒绝前进入 HTTP 请求")

    async def test_account_payload_rejects_origin_spoofs_and_protocol_overrides(self):
        urls = (
            "http://api.lao-hu.com", "https://api.lao-hu.com.evil.example",
            "https://api.lao-hu.com@foreign.example", "https://user@api.lao-hu.com",
            "https://api.lao-hu.com:444", "https://api.lao-hu.com/proxy",
            "https://api.lao-hu.com?target=foreign", "https://api.lao-hu.com#fragment",
        )
        for url in urls:
            with self.subTest(url=url), self.assertRaises(HTTPException):
                main.api_key_from_payload(main.TestConnectionPayload(provider_id="ai-money", base_url=url))
        for protocol in ("runninghub", "gemini", "volcengine"):
            with self.subTest(protocol=protocol), self.assertRaises(HTTPException):
                main.api_key_from_payload(main.TestConnectionPayload(
                    provider_id="ai-money", base_url="https://api.lao-hu.com", protocol=protocol,
                ))
        for url in ("https://api.lao-hu.com", "https://api.lao-hu.com/", "https://api.lao-hu.com:443/v1/"):
            self.assertEqual(main.api_key_from_payload(main.TestConnectionPayload(
                provider_id="ai-money", base_url=url,
            )), "fixture-origin-account-token")

    async def test_bound_account_stays_restricted_after_logout_and_manual_mode_stays_compatible(self):
        self.state.bind_execution("origin-test-task", manual_key=lambda: "fixture-manual-key")
        self.state.logout()
        foreign = main.TestConnectionPayload(provider_id="ai-money", base_url="https://foreign.example")
        with self.state.execution_auth_scope("origin-test-task"), self.assertRaises(HTTPException):
            main.api_key_from_payload(foreign)
        with self.assertRaises(HTTPException):
            main.api_key_from_payload(foreign)
        self.state.set_manual_mode()
        self.state._end_auth_request(self.request_token)
        self.request_token = self.state._begin_auth_request()
        self.assertEqual(main.api_key_from_payload(foreign), "fixture-manual-key")

    async def test_uncertain_bound_identity_cannot_return_a_previously_resolved_token(self):
        with patch.object(self.state, "model_credential_status", side_effect=[
            {"has_key": True, "bound": True, "credential_kind": "account"},
            {"has_key": False, "bound": True, "credential_kind": ""},
        ]), patch.object(main, "provider_env_key_value", return_value="fixture-origin-account-token"):
            with self.assertRaises(HTTPException):
                main.api_key_from_payload(main.TestConnectionPayload(
                    provider_id="ai-money", base_url="https://api.lao-hu.com",
                ))


class LaohuProviderIsolationTests(unittest.TestCase):
    def test_active_credential_metadata_does_not_confuse_account_with_manual_key(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache") as temp_dir:
            state = LaohuAccountState(base_dir=temp_dir)
            api_env = Path(temp_dir) / "API" / ".env"
            api_env.parent.mkdir(parents=True)
            api_env.write_text("", encoding="utf-8")
            provider = {"id": "ai-money", "name": "laohu", "base_url": "https://api.lao-hu.com", "protocol": "openai"}
            session = state._empty_session()
            session.update(mode="account", connection={
                "generation_id": "account-generation-preview",
                "access_token": "account-preview-secret",
                "expires_at": 4_000_000_000,
                "account": {"id": "test-account", "username": "test", "balance_display": "¥1"},
                "model_authorized": True,
            })
            state._write_session(session)
            with patch.object(main, "LAOHU_ACCOUNT_STATE", state), \
                 patch.object(main, "API_ENV_FILE", str(api_env)), \
                 patch.dict(os.environ, {
                     "API_PROVIDER_LAOHU_KEY": "", "API_PROVIDER_AI_MONEY_KEY": "",
                 }):
                provider_public = main.public_provider(provider)
                status = state.public_status(
                    lambda: bool(main.manual_provider_env_key_value("ai-money")),
                    main.laohu_manual_key_preview,
                )
                self.assertTrue(provider_public["has_key"])
                self.assertFalse(provider_public["has_manual_key"])
                self.assertEqual(provider_public["key_preview"], "账户授权")
                self.assertEqual(status["active_credential"], {
                    "kind": "account", "configured": True,
                    "label": "登录自动配置", "preview": "••••••••",
                })
                serialized = json.dumps({"provider": provider_public, "status": status}, ensure_ascii=False)
                self.assertNotIn("account-preview-secret", serialized)

    def test_account_and_manual_provider_resolution_share_mode_without_secret_preview(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache") as temp_dir:
            state = LaohuAccountState(base_dir=temp_dir)
            api_env = Path(temp_dir) / "API" / ".env"
            api_env.parent.mkdir(parents=True)
            api_env.write_text("", encoding="utf-8")
            provider = {
                "id": "ai-money", "name": "laohu", "base_url": "https://api.lao-hu.com",
                "protocol": "openai", "access_token": "must-not-be-public",
            }
            with patch.object(main, "LAOHU_ACCOUNT_STATE", state), \
                 patch.object(main, "API_ENV_FILE", str(api_env)), \
                 patch.dict(os.environ, {
                     "API_PROVIDER_LAOHU_KEY": "manual-test-key",
                     "API_PROVIDER_OTHER_KEY": "other-test-key",
                 }):
                headers = main.api_headers(provider=provider, model="test-model")
                self.assertEqual(headers["Authorization"], "Bearer manual-test-key")

                session = state._empty_session()
                session.update(mode="account", connection={
                    "generation_id": "account-generation-1",
                    "access_token": "account-test-token",
                    "expires_at": 1_900_000_000,
                    "account": {"id": "test-account", "username": "test", "balance_display": "1"},
                    "model_authorized": True,
                })
                state._write_session(session)
                state.set_execution_hooks_ready(True)

                account_request_token = state._begin_auth_request()
                try:
                    account_headers = main.api_headers(provider=provider, model="test-model")
                    self.assertEqual(account_headers["Authorization"], "Bearer account-test-token")
                    payload = SimpleNamespace(
                        provider_id="ai-money", api_key="typed-manual-key",
                        base_url="https://api.lao-hu.com", protocol="openai",
                    )
                    self.assertEqual(main.api_key_from_payload(payload), "account-test-token")
                    self.assertEqual(main.manual_provider_env_key_value("ai-money"), "manual-test-key")

                    public = main.public_provider(provider)
                    self.assertTrue(public["has_key"])
                    self.assertTrue(public["has_manual_key"])
                    self.assertEqual(public["key_preview"], "账户授权")
                    self.assertNotIn("must-not-be-public", json.dumps(public, ensure_ascii=False))
                    self.assertNotIn("account-test-token", json.dumps(public, ensure_ascii=False))
                finally:
                    state._end_auth_request(account_request_token)

                state.logout()
                next_request_token = state._begin_auth_request()
                try:
                    with self.assertRaises(main.HTTPException) as raised:
                        main.api_headers(provider=provider, model="test-model")
                    self.assertEqual(raised.exception.status_code, 409)
                finally:
                    state._end_auth_request(next_request_token)

                other_headers = main.api_headers(
                    provider={"id": "other", "name": "Other", "base_url": "https://other.example", "protocol": "openai"},
                    model="test-model",
                )
                self.assertEqual(other_headers["Authorization"], "Bearer other-test-key")

    def test_main_installs_all_required_execution_auth_hooks(self):
        components = [
            main.STUDIO_EXECUTION, main.HYPIT_FLOW_RUNNER, main.ARTICLE_FLOW_RUNNER,
            main.MUSIC_FLOW_RUNNER, main.SCRIPT_FLOW_RUNNER, main.NOVEL_FLOW_RUNNER,
        ]
        for component in components:
            self.assertTrue(callable(component.bind_execution_auth))
            self.assertTrue(callable(component.execution_auth_scope))
            self.assertTrue(callable(component.release_execution_auth))
        self.assertTrue(main.LAOHU_ACCOUNT_STATE._execution_hooks_ready)

    def test_bound_account_provider_stays_available_after_logout_and_unbound_scope_fails_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache") as temp_dir:
            state = LaohuAccountState(base_dir=temp_dir)
            api_env = Path(temp_dir) / "API" / ".env"
            api_env.parent.mkdir(parents=True)
            api_env.write_text("", encoding="utf-8")
            provider = {"id": "ai-money", "name": "laohu", "protocol": "openai"}
            with patch.object(main, "LAOHU_ACCOUNT_STATE", state), \
                 patch.object(main, "API_ENV_FILE", str(api_env)), \
                 patch.dict(os.environ, {"API_PROVIDER_LAOHU_KEY": "manual-test-key"}):
                session = state._empty_session()
                session.update(mode="account", connection={
                    "generation_id": "account-generation-1",
                    "access_token": "accepted-task-token",
                    "expires_at": 4_000_000_000,
                    "account": {"id": "test-account", "username": "test", "balance_display": "1"},
                    "model_authorized": True,
                })
                state._write_session(session)
                main.laohu_bind_execution_auth(
                    "flow-accepted:node-1", {"provider_id": "ai-money"},
                )
                state.logout()

                with state.execution_auth_scope("flow-accepted:node-1"):
                    # Exercise the real provider projection used by canvas preflight;
                    # it must expose only generic availability for the accepted binding.
                    with patch.object(main, "load_api_providers", return_value=[provider]):
                        canvas_provider = next(
                            item for item in main.canvas_api_providers()
                            if item.get("id") == "ai-money"
                        )
                    public = main.public_provider(provider)
                    self.assertTrue(canvas_provider["has_key"])
                    self.assertEqual(canvas_provider["key_preview"], "账户授权")
                    self.assertTrue(public["has_key"])
                    self.assertEqual(public["key_preview"], "账户授权")
                    self.assertNotIn("accepted-task-token", json.dumps(public, ensure_ascii=False))
                    headers = main.api_headers(provider=provider, model="test-model")
                    self.assertEqual(headers["Authorization"], "Bearer accepted-task-token")
                    self.assertEqual(main.api_key_from_payload(SimpleNamespace(
                        provider_id="ai-money", api_key="must-not-override-binding",
                        base_url="https://api.lao-hu.com", protocol="openai",
                    )), "accepted-task-token")

                with state.execution_auth_scope("non-ai-money-task"):
                    public = main.public_provider(provider)
                    self.assertFalse(public["has_key"])
                    self.assertEqual(public["key_preview"], "")
                    with self.assertRaises(main.HTTPException) as missing:
                        main.api_headers(provider=provider, model="test-model")
                    self.assertEqual(missing.exception.status_code, 409)

    def test_main_app_registers_laohu_account_routes(self):
        paths = set(main.app.openapi()["paths"])
        self.assertIn("/api/laohu/account/status", paths)
        self.assertIn("/api/laohu/account/login", paths)
        self.assertIn("/api/laohu/account/login/{flow_id}", paths)
        self.assertIn("/api/laohu/account/logout", paths)
        self.assertIn("/api/laohu/account/mode", paths)
        self.assertIn("/api/laohu/account/refresh", paths)

    def test_access_log_filter_drops_oauth_callback_query_for_every_status(self):
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="main.py",
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %s',
            args=("127.0.0.1", "GET", "/api/laohu/account/callback?code=private&state=private", "1.1", 403),
            exc_info=None,
        )
        self.assertFalse(main.QuietAccessLogFilter().filter(record))


class LaohuExecutionErrorRedactionTests(unittest.TestCase):
    def _state_with_account_binding(self, base_dir, token):
        state = LaohuAccountState(base_dir=base_dir)
        session = state._empty_session()
        session.update(mode="account", connection={
            "generation_id": "error-test-generation",
            "access_token": token,
            "expires_at": 4_000_000_000,
            "account": {"id": "fixture-account"},
            "model_authorized": True,
        })
        state._write_session(session)
        state.bind_execution("error-test-binding", manual_key=lambda: "unused-manual-key")
        return state

    def test_bound_scope_redacts_bare_and_bearer_credentials_from_exception(self):
        token = "fake-redaction-token-1"
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache") as temp_dir:
            state = self._state_with_account_binding(temp_dir, token)
            with self.assertRaises(RuntimeError) as raised:
                with state.execution_auth_scope("error-test-binding"):
                    raise ValueError(f"upstream rejected {token}; Authorization: Bearer {token}")
        message = str(raised.exception)
        self.assertNotIn(token, message)
        self.assertIn("upstream rejected", message)
        self.assertEqual(message.count("[redacted laohu credential]"), 2)

    def test_bound_scope_redacts_nested_http_detail_and_preserves_status(self):
        token = "fake-redaction-token-2"
        nested = {
            "error": {
                "message": f"upstream echoed Bearer {token}",
                "causes": [f"raw={token}"],
            },
        }
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache") as temp_dir:
            state = self._state_with_account_binding(temp_dir, token)
            with self.assertRaises(main.HTTPException) as raised:
                with state.execution_auth_scope("error-test-binding"):
                    raise main.HTTPException(
                        status_code=429,
                        detail=nested,
                        headers={"X-Debug": f"Bearer {token}"},
                    )
        self.assertEqual(raised.exception.status_code, 429)
        safe = json.dumps({"detail": raised.exception.detail, "headers": raised.exception.headers})
        self.assertNotIn(token, safe)
        self.assertIn("upstream echoed Bearer [redacted laohu credential]", safe)
        self.assertIn("raw=[redacted laohu credential]", safe)

    def test_unbound_non_laohu_scope_keeps_original_exception(self):
        token_like_message = "fixture error text remains unchanged"
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache") as temp_dir:
            state = LaohuAccountState(base_dir=temp_dir)
            with self.assertRaisesRegex(ValueError, token_like_message) as raised:
                with state.execution_auth_scope("unbound-non-laohu-task"):
                    raise ValueError(token_like_message)
        self.assertEqual(str(raised.exception), token_like_message)


class LaohuStudioExecutionAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_execution_public_task_error_redacts_bound_credential(self):
        token = "fake-task-error-secret-8832"
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache") as temp_dir:
            state = LaohuAccountState(base_dir=temp_dir)
            api_env = Path(temp_dir) / "API" / ".env"
            api_env.parent.mkdir(parents=True)
            api_env.write_text("", encoding="utf-8")
            session = state._empty_session()
            session.update(mode="account", connection={
                "generation_id": "fake-error-generation",
                "access_token": token,
                "expires_at": 4_000_000_000,
                "account": {"id": "fixture-account"},
                "model_authorized": True,
            })
            state._write_session(session)
            canvas = {
                "id": "laohu-auth-error-canvas",
                "nodes": [{
                    "id": "image-node", "type": "smart-image-generator", "title": "测试图片",
                    "promptDraftText": "fake execution only",
                    "runSettings": {"provider_id": "ai-money", "model": "fixture-image"},
                }],
                "connections": [],
            }

            class Store:
                def __init__(self):
                    self.tasks = {}

                def get_canvas_task(self, task_id):
                    return copy.deepcopy(self.tasks.get(task_id))

                def create_canvas_task(self, task):
                    self.tasks[task["id"]] = copy.deepcopy(task)

                def update_canvas_task(self, task_id, **changes):
                    self.tasks[task_id].update(copy.deepcopy(changes))

            store = Store()

            async def preflight(*_args):
                return {"run_id": "fixture-error-preflight"}

            async def fake_provider_generate(request):
                headers = main.api_headers(
                    provider={"id": request["provider_id"], "name": "laohu", "protocol": "openai"},
                    model=request["model"],
                )
                bearer_value = headers["Authorization"]
                raise RuntimeError(f"provider echoed {token}; {bearer_value}")

            async def collect(_result, _request, _task):
                return [{"kind": "image", "url": "/api/results/unreachable"}]

            async def notify(_canvas):
                state.logout()

            from studio_execution import StudioExecution

            executor = StudioExecution(
                load_canvas=lambda _canvas_id: copy.deepcopy(canvas),
                save_canvas=lambda value: canvas.update(copy.deepcopy(value)),
                lock=threading.RLock(),
                storage=store,
                preflight=preflight,
                generate=fake_provider_generate,
                collect=collect,
                notify=notify,
                bind_execution_auth=lambda binding_id, request: state.bind_execution(
                    binding_id,
                    manual_key=lambda: main.manual_provider_env_key_value("ai-money"),
                ) if request.get("provider_id") == "ai-money" else False,
                execution_auth_scope=state.execution_auth_scope,
                release_execution_auth=state.release_execution,
            )

            with patch.object(main, "LAOHU_ACCOUNT_STATE", state), \
                 patch.object(main, "API_ENV_FILE", str(api_env)), \
                 patch.dict(os.environ, {"API_PROVIDER_LAOHU_KEY": "unused-manual-fixture"}):
                submitted = await executor.submit(canvas, canvas["nodes"][0], "fake-error-operation")
                task_id = submitted["task_ids"][0]
                handle = executor.handles.get(task_id)
                if handle:
                    await asyncio.wait_for(asyncio.shield(handle), timeout=3)

            task = store.get_canvas_task(task_id)
            self.assertEqual(task["status"], "failed")
            self.assertIn("provider echoed", task["error"])
            self.assertIn("Bearer [redacted laohu credential]", task["error"])
            self.assertNotIn(token, json.dumps(task, ensure_ascii=False))
            self.assertFalse(state._read_session().get("executions"))

    async def test_studio_fake_provider_call_uses_accepted_account_after_logout(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache") as temp_dir:
            state = LaohuAccountState(base_dir=temp_dir)
            api_env = Path(temp_dir) / "API" / ".env"
            api_env.parent.mkdir(parents=True)
            api_env.write_text("", encoding="utf-8")
            session = state._empty_session()
            session.update(mode="account", connection={
                "generation_id": "account-generation-1",
                "access_token": "accepted-task-token",
                "expires_at": 4_000_000_000,
                "account": {"id": "test-account", "username": "test", "balance_display": "1"},
                "model_authorized": True,
            })
            state._write_session(session)

            canvas = {
                "id": "laohu-auth-test-canvas",
                "nodes": [{
                    "id": "image-node", "type": "smart-image-generator", "title": "测试图片",
                    "promptDraftText": "fake execution only",
                    "runSettings": {"provider_id": "ai-money", "model": "fixture-image"},
                }],
                "connections": [],
            }

            class Store:
                def __init__(self):
                    self.tasks = {}

                def get_canvas_task(self, task_id):
                    return copy.deepcopy(self.tasks.get(task_id))

                def create_canvas_task(self, task):
                    self.tasks[task["id"]] = copy.deepcopy(task)

                def update_canvas_task(self, task_id, **changes):
                    self.tasks[task_id].update(copy.deepcopy(changes))

            store = Store()
            seen_headers = []

            async def preflight(*_args):
                return {"run_id": "fixture-preflight"}

            async def fake_provider_generate(request):
                headers = main.api_headers(
                    provider={"id": request["provider_id"], "name": "laohu", "protocol": "openai"},
                    model=request["model"],
                )
                seen_headers.append(headers["Authorization"])
                return {"images": ["/api/results/fake-laohu-auth"]}

            async def collect(_result, _request, _task):
                return [{"kind": "image", "url": "/api/results/fake-laohu-auth"}]

            async def notify(_canvas):
                # Simulate logout after task acceptance, before the worker makes its provider call.
                state.logout()

            from studio_execution import StudioExecution

            executor = StudioExecution(
                load_canvas=lambda _canvas_id: copy.deepcopy(canvas),
                save_canvas=lambda value: canvas.update(copy.deepcopy(value)),
                lock=threading.RLock(),
                storage=store,
                preflight=preflight,
                generate=fake_provider_generate,
                collect=collect,
                notify=notify,
                bind_execution_auth=lambda binding_id, request: state.bind_execution(
                    binding_id,
                    manual_key=lambda: main.manual_provider_env_key_value("ai-money"),
                ) if request.get("provider_id") == "ai-money" else False,
                execution_auth_scope=state.execution_auth_scope,
                release_execution_auth=state.release_execution,
            )

            with patch.object(main, "LAOHU_ACCOUNT_STATE", state), \
                 patch.object(main, "API_ENV_FILE", str(api_env)), \
                 patch.dict(os.environ, {"API_PROVIDER_LAOHU_KEY": "manual-key-must-not-fallback"}):
                result = await executor.submit(canvas, canvas["nodes"][0], "fake-provider-operation")
                task_id = result["task_ids"][0]
                handle = executor.handles.get(task_id)
                if handle:
                    await asyncio.wait_for(asyncio.shield(handle), timeout=3)

            self.assertEqual(seen_headers, ["Bearer accepted-task-token"])
            self.assertEqual(store.get_canvas_task(task_id)["status"], "succeeded")
            self.assertFalse(state._read_session().get("executions"))
            self.assertNotIn("accepted-task-token", json.dumps(store.tasks[task_id], ensure_ascii=False))
            self.assertNotIn("manual-key-must-not-fallback", json.dumps(store.tasks[task_id], ensure_ascii=False))

if __name__ == "__main__":
    unittest.main()
