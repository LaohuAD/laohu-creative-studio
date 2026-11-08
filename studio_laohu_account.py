"""本机 laohu OAuth 身份连接；模型执行仍由共享执行器单独授权接入。"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import secrets
import stat
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Callable, Literal
from urllib.parse import urlencode, urlsplit
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


LAOHU_API_ORIGIN = "https://api.lao-hu.com"
LAOHU_AUTHORIZE_URL = f"{LAOHU_API_ORIGIN}/authorize"
LAOHU_TOKEN_URL = f"{LAOHU_API_ORIGIN}/api/auth/token"
LAOHU_USERINFO_URL = f"{LAOHU_API_ORIGIN}/api/auth/userinfo"
LAOHU_MODELS_URL = f"{LAOHU_API_ORIGIN}/v1/models"
LAOHU_STATUS_URL = f"{LAOHU_API_ORIGIN}/api/status"
LAOHU_CALLBACK_URI = "http://127.0.0.1:3000/api/laohu/account/callback"
LOGIN_FLOW_TTL_SECONDS = 600
LOGIN_UNAVAILABLE_REASON = "尚未配置可用的本机 laohu 登录应用，请先使用手动 Key"
BALANCE_UNAVAILABLE_DISPLAY = "请在充值页查看"
BALANCE_CONFIG_CACHE_SECONDS = 300
BALANCE_CONFIG_FAILURE_CACHE_SECONDS = 30
BALANCE_DISPLAY_VERSION = 1
LAOHU_ACCOUNT_LINKS = {
    "console": f"{LAOHU_API_ORIGIN}/keys",
    "wallet": f"{LAOHU_API_ORIGIN}/wallet",
    "usage": f"{LAOHU_API_ORIGIN}/usage-logs",
}
_AUTH_CACHE_UNSET = object()
_REDACTED_EXECUTION_CREDENTIAL = "[redacted laohu credential]"
_BALANCE_CONFIG_UNSET = object()


class _ExecutionCredentialRedactedError(RuntimeError):
    """Safe replacement for a provider error that echoed its bound credential."""

    def __init__(self, message: str, *, detail=None):
        super().__init__(message)
        self.detail = message if detail is None else detail


class AccountStoreError(RuntimeError):
    """Private local configuration or session storage cannot be used safely."""


class AccountTemporaryError(AccountStoreError):
    """A remote status read failed transiently; the saved identity remains intact."""


class AccountInvalidError(AccountStoreError):
    """The server explicitly rejected the currently stored access token."""


class LaohuExecutionAuthRequestBoundary:
    """Reset direct-request credential pinning at each HTTP ASGI boundary."""

    def __init__(self, app, *, state=None, state_getter=None):
        self.app = app
        self.state = state
        self.state_getter = state_getter

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        state = self.state_getter() if self.state_getter is not None else self.state
        cache_token = state._begin_auth_request()
        try:
            await self.app(scope, receive, send)
        finally:
            state._end_auth_request(cache_token)


def _origin(value: str, *, allow_path: bool = False):
    try:
        parsed = urlsplit(str(value or ""))
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password
                or (not allow_path and (parsed.query or parsed.fragment))):
            return None
        if not allow_path and parsed.path not in {"", "/"}:
            return None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return parsed.scheme.lower(), parsed.hostname.lower().rstrip("."), port
    except ValueError:
        return None


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _trusted_local_host(host: str) -> bool:
    host = str(host or "").lower().rstrip(".")
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_loopback
    except ValueError:
        return False


def _same_origin(expected, actual) -> bool:
    if not expected or not actual:
        return False
    if expected == actual:
        return True
    return (expected[0] == actual[0] and expected[2] == actual[2]
            and _loopback(expected[1]) and _loopback(actual[1]))


def _require_local_request(request: Request, *, action: bool = False) -> None:
    """Reject cross-origin reads/writes and untrusted Host headers."""
    if action and request.headers.get("x-laohu-account-action") != "1":
        raise HTTPException(status_code=403, detail="缺少账户操作确认头")

    host = request.headers.get("host", "")
    expected = _origin(f"{request.url.scheme}://{host}") if host else None
    peer_host = str(request.client.host if request.client else "").split("%", 1)[0]
    if (not expected or not _trusted_local_host(expected[1])
            or not _loopback(peer_host)):
        raise HTTPException(status_code=403, detail="仅允许从受信任的本地地址访问")

    origin_header = request.headers.get("origin")
    referer_header = request.headers.get("referer")
    if origin_header:
        actual = _origin(origin_header)
        if not _same_origin(expected, actual):
            raise HTTPException(status_code=403, detail="只允许从当前页面执行此操作")
    elif referer_header:
        actual = _origin(referer_header, allow_path=True)
        if not _same_origin(expected, actual):
            raise HTTPException(status_code=403, detail="只允许从当前页面执行此操作")
    elif request.headers.get("sec-fetch-site", "").lower() not in {"", "same-origin", "none"}:
        raise HTTPException(status_code=403, detail="只允许从当前页面执行此操作")


def _require_callback_peer(request: Request) -> None:
    peer_host = str(request.client.host if request.client else "").split("%", 1)[0]
    if (request.url.scheme != "http"
            or request.headers.get("host", "").lower() != "127.0.0.1:3000"
            or not _loopback(peer_host)):
        raise HTTPException(status_code=403, detail="OAuth 回调地址不匹配")


def _safe_file_permissions(path: Path, *, writable: bool = False) -> None:
    if path.is_symlink():
        raise AccountStoreError("本机账户文件不能是符号链接")
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise AccountStoreError("本机账户配置不可读取") from exc
    if os.name == "posix" and mode & 0o077:
        raise AccountStoreError("本机账户文件权限过宽；请设为仅当前用户可读写")
    if writable and os.name == "posix" and not mode & 0o200:
        raise AccountStoreError("本机账户会话文件不可写")


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise AccountStoreError("本机账户文件格式无效") from exc
    if not isinstance(value, dict):
        raise AccountStoreError("本机账户文件格式无效")
    return value


def _quota_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    # Keep hostile or malformed values from creating enormous formatted strings.
    if parsed != 0 and (parsed.adjusted() > 30 or parsed.as_tuple().exponent < -60):
        return None
    return parsed


def _config_decimal(value: object, *, minimum: Decimal, maximum: Decimal) -> Decimal | None:
    parsed = _quota_decimal(value)
    if parsed is None or parsed < minimum or parsed > maximum:
        return None
    return parsed


def _balance_config(value: object) -> dict | None:
    if not isinstance(value, dict) or value.get("success") is False or value.get("error"):
        return None
    data = value.get("data") if isinstance(value.get("data"), dict) else value
    display_type = data.get("quota_display_type")
    if not isinstance(display_type, str):
        return None
    display_type = display_type.strip().upper()
    # Only CUSTOM has been verified against the currently deployed status and UI.
    # Other display modes remain unavailable until their conversion is confirmed.
    if display_type != "CUSTOM":
        return None
    quota_per_unit = _config_decimal(
        data.get("quota_per_unit"), minimum=Decimal("1e-18"), maximum=Decimal("1e30")
    )
    if quota_per_unit is None:
        return None
    display_in_currency = data.get("display_in_currency")
    if display_in_currency is not True:
        return None
    exchange_rate = _config_decimal(
        data.get("custom_currency_exchange_rate"),
        minimum=Decimal("1e-18"), maximum=Decimal("1e12"),
    )
    if exchange_rate is None:
        return None
    symbol = data.get("custom_currency_symbol")
    if (not isinstance(symbol, str) or not symbol.strip()
            or len(symbol.strip()) > 12
            or any(ord(char) < 32 for char in symbol.strip())):
        return None
    symbol = symbol.strip()
    return {
        "display_type": display_type,
        "quota_per_unit": quota_per_unit,
        "exchange_rate": exchange_rate,
        "symbol": symbol,
    }


def _format_balance(quota: object, config: dict | None) -> str:
    amount_quota = _quota_decimal(quota)
    if amount_quota is None or not isinstance(config, dict):
        return BALANCE_UNAVAILABLE_DISPLAY
    try:
        with localcontext() as context:
            context.prec = 80
            amount = amount_quota / config["quota_per_unit"]
            display_type = config["display_type"]
            amount *= config["exchange_rate"]
            if not amount.is_finite() or (amount != 0 and amount.adjusted() > 30):
                return BALANCE_UNAVAILABLE_DISPLAY
            digits = 2 if abs(amount) >= 1 else 4
            rounded = amount.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
            text = f"{rounded:,.{digits}f}"
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            if text in {"", "-0"}:
                text = "0"
            return f"{config['symbol']}{text}"
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return BALANCE_UNAVAILABLE_DISPLAY


def _account_record(value: object, *, balance_display: str = BALANCE_UNAVAILABLE_DISPLAY) -> dict | None:
    if not isinstance(value, dict):
        return None
    data = value.get("data") if isinstance(value.get("data"), dict) else value
    if isinstance(data.get("user"), dict):
        data = data["user"]
    user_id = next((data.get(key) for key in ("id", "user_id", "uid", "sub")
                    if isinstance(data.get(key), (str, int)) and str(data.get(key)).strip()), None)
    username = next((data.get(key) for key in ("username", "user_name", "preferred_username", "name", "nickname")
                     if isinstance(data.get(key), str) and data.get(key).strip()), None)
    if user_id is None:
        return None
    return {
        "id": str(user_id).strip()[:160],
        "username": str(username or user_id).strip()[:160],
        "balance_display": balance_display[:80] or BALANCE_UNAVAILABLE_DISPLAY,
    }


def _account_quota(value: object) -> Decimal | None:
    if not isinstance(value, dict):
        return None
    data = value.get("data") if isinstance(value.get("data"), dict) else value
    if isinstance(data.get("user"), dict):
        data = data["user"]
    return _quota_decimal(data.get("quota")) if "quota" in data else None


def _models_response_is_authorized(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("success") is False or value.get("error"):
        return False
    candidates = [value.get("data"), value.get("models")]
    data = value.get("data")
    if isinstance(data, dict):
        candidates.extend([data.get("data"), data.get("models")])
    return any(isinstance(candidate, list) for candidate in candidates)


def _diagnostic_field_names(value: object) -> str:
    if not isinstance(value, dict):
        return "none"
    names = sorted({
        key for key in value
        if isinstance(key, str)
        and 1 <= len(key) <= 48
        and all(char.isascii() and (char.isalnum() or char in "_-") for char in key)
    })
    if not names:
        return "none"
    shown = names[:24]
    if len(names) > len(shown):
        shown.append(f"+{len(names) - len(shown)} more")
    return ",".join(shown)


def _token_response_shape_diagnostic(value: object) -> str:
    if not isinstance(value, dict):
        return "top_fields=none; data_fields=none; success=non_object; token_type=missing"
    data = value.get("data")
    data_fields = _diagnostic_field_names(data)
    success = value.get("success")
    success_label = (
        "missing" if "success" not in value
        else "true" if success is True
        else "false" if success is False
        else "non_boolean"
    )
    token_container = data if isinstance(data, dict) and "access_token" not in value else value
    token_type_label = "present" if isinstance(token_container, dict) and "token_type" in token_container else "missing"
    return (
        f"top_fields={_diagnostic_field_names(value)}; data_fields={data_fields}; "
        f"success={success_label}; token_type={token_type_label}"
    )


class LaohuAccountModeRequest(BaseModel):
    mode: Literal["manual", "account"]

    class Config:
        extra = "forbid"


class LaohuAccountLoginRequest(BaseModel):
    client_operation_id: str = Field(..., min_length=1, max_length=128)

    class Config:
        extra = "forbid"


class LaohuAccountState:
    """Owner-only local OAuth state; public methods never return tokens or verifiers."""

    def __init__(self, base_dir: str | os.PathLike[str] | None = None, *,
                 client_factory: Callable[..., httpx.AsyncClient] | None = None,
                 clock: Callable[[], float] = time.time):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parent).resolve()
        self.config_path = self.base_dir / "API" / ".laohu-login-app.json"
        self.session_path = self.base_dir / "API" / ".laohu-account-session.json"
        self.client_factory = client_factory or httpx.AsyncClient
        self.clock = clock
        self._lock = threading.RLock()
        context_id = uuid.uuid4().hex
        self._execution_binding_id = ContextVar(f"laohu_execution_binding_{context_id}", default="")
        self._direct_key_cache = ContextVar(f"laohu_direct_key_cache_{context_id}", default=_AUTH_CACHE_UNSET)
        self._execution_hooks_ready = False
        self._balance_config_cache = _BALANCE_CONFIG_UNSET
        self._balance_config_cached_at = 0.0

    @staticmethod
    def _empty_session() -> dict:
        return {
            "version": 1,
            "mode": "manual",
            "selection_revision": 0,
            "latest_login_flow_id": "",
            "flows": {},
            "connection": None,
            "executions": {},
        }

    def _read_session(self) -> dict:
        if not self.session_path.exists():
            return self._empty_session()
        _safe_file_permissions(self.session_path, writable=True)
        data = _json_object(self.session_path)
        if data.get("version") != 1 or data.get("mode") not in {"manual", "account"}:
            raise AccountStoreError("本机账户会话格式无效")
        try:
            data["selection_revision"] = max(0, int(data.get("selection_revision") or 0))
        except (TypeError, ValueError) as exc:
            raise AccountStoreError("本机账户会话格式无效") from exc
        latest_flow_id = data.get("latest_login_flow_id")
        data["latest_login_flow_id"] = latest_flow_id if isinstance(latest_flow_id, str) else ""
        flows = data.get("flows")
        if not isinstance(flows, dict):
            data["flows"] = {}
        connection = data.get("connection")
        if connection is not None and not isinstance(connection, dict):
            data["connection"] = None
        executions = data.get("executions")
        if not isinstance(executions, dict):
            data["executions"] = {}
        return data

    def _write_session(self, value: dict) -> None:
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.session_path.with_name(
            f".laohu-account-session-{uuid.uuid4().hex}.tmp.json"
        )
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(temp_path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name == "posix":
                os.chmod(temp_path, 0o600)
            os.replace(temp_path, self.session_path)
            if os.name == "posix":
                os.chmod(self.session_path, 0o600)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _begin_auth_request(self):
        return self._direct_key_cache.set(_AUTH_CACHE_UNSET)

    def _end_auth_request(self, cache_token) -> None:
        self._direct_key_cache.reset(cache_token)

    @contextmanager
    def execution_auth_scope(self, binding_id: str):
        binding_id = self._checked_binding_id(binding_id)
        binding_token = self._execution_binding_id.set(binding_id)
        cache_token = self._direct_key_cache.set(_AUTH_CACHE_UNSET)
        try:
            try:
                yield
            except Exception as exc:
                credential = self._execution_credential_for_error_redaction(binding_id)
                if not credential:
                    raise
                if isinstance(exc, HTTPException):
                    detail = self._redact_execution_credential(exc.detail, credential)
                    headers = self._redact_execution_credential(exc.headers, credential)
                    if detail != exc.detail or headers != exc.headers:
                        raise HTTPException(
                            status_code=exc.status_code,
                            detail=detail,
                            headers=headers,
                        ) from None
                original_message = str(exc)
                safe_message = self._redact_execution_credential(original_message, credential)
                detail_marker = object()
                original_detail = getattr(exc, "detail", detail_marker)
                safe_detail = (
                    self._redact_execution_credential(original_detail, credential)
                    if original_detail is not detail_marker else detail_marker
                )
                if safe_message != original_message or safe_detail != original_detail:
                    public_message = (
                        str(safe_detail) if safe_detail is not detail_marker
                        and safe_detail != original_detail else safe_message
                    )
                    public_detail = safe_detail if safe_detail is not detail_marker else public_message
                    raise _ExecutionCredentialRedactedError(
                        public_message, detail=public_detail,
                    ) from None
                raise
        finally:
            self._direct_key_cache.reset(cache_token)
            self._execution_binding_id.reset(binding_token)

    def _execution_credential_for_error_redaction(self, binding_id: str) -> str:
        """Read only this private binding's credential for exact error scrubbing."""
        try:
            with self._lock:
                session = self._read_session()
            executions = session.get("executions")
            snapshot = executions.get(binding_id) if isinstance(executions, dict) else None
            credential = snapshot.get("credential") if isinstance(snapshot, dict) else None
            return credential if isinstance(credential, str) else ""
        except Exception:
            return ""

    @classmethod
    def _redact_execution_credential(cls, value, credential: str):
        if isinstance(value, str):
            return value.replace(credential, _REDACTED_EXECUTION_CREDENTIAL)
        if isinstance(value, bytes):
            return value.replace(
                credential.encode("utf-8"),
                _REDACTED_EXECUTION_CREDENTIAL.encode("utf-8"),
            )
        if isinstance(value, dict):
            safe_value = {
                cls._redact_execution_credential(key, credential):
                cls._redact_execution_credential(item, credential)
                for key, item in value.items()
            }
        elif isinstance(value, list):
            safe_value = [cls._redact_execution_credential(item, credential) for item in value]
        elif isinstance(value, tuple):
            safe_value = tuple(cls._redact_execution_credential(item, credential) for item in value)
        else:
            safe_value = value
        try:
            rendered = str(safe_value)
        except Exception:
            return safe_value
        if credential in rendered:
            return rendered.replace(credential, _REDACTED_EXECUTION_CREDENTIAL)
        return safe_value

    def set_execution_hooks_ready(self, ready: bool) -> None:
        self._execution_hooks_ready = bool(ready)

    @staticmethod
    def _checked_binding_id(binding_id: str) -> str:
        value = str(binding_id or "").strip()
        if (not value or len(value) > 512
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise HTTPException(status_code=400, detail="任务凭据绑定标识无效")
        return value

    def _snapshot_selected_credential(self, session: dict, manual_key, *, require_key: bool) -> dict | None:
        if session.get("mode") == "account":
            connection = session.get("connection")
            if not isinstance(connection, dict):
                raise HTTPException(status_code=409, detail="laohu 账户未连接；请重新登录或明确切换手动 Key")
            token = connection.get("access_token")
            generation_id = connection.get("generation_id")
            try:
                expires_at = float(connection.get("expires_at") or 0)
            except (TypeError, ValueError):
                expires_at = 0
            if not isinstance(token, str) or not token or not expires_at > self.clock():
                raise HTTPException(status_code=401, detail="laohu 账户令牌已过期；请重新登录，不会自动切换凭据")
            if connection.get("access_validation_state") == "rejected":
                raise HTTPException(status_code=401, detail="laohu 账户令牌已被服务端拒绝；请重新连接，不会自动切换凭据")
            if connection.get("model_authorized") is not True:
                raise HTTPException(status_code=403, detail="laohu 账户尚未通过模型授权核验")
            if not isinstance(generation_id, str) or not generation_id:
                raise HTTPException(status_code=409, detail="laohu 账户凭据代际无效")
            return {
                "credential_kind": "account",
                "credential": token,
                "generation_id": generation_id,
                "expires_at": expires_at,
                "model_authorized": True,
                "bound_at": self.clock(),
            }

        value = manual_key() if callable(manual_key) else manual_key
        credential = str(value or "").strip()
        if not credential:
            if require_key:
                raise HTTPException(status_code=400, detail="laohu 未配置手动 API Key")
            return None
        generation = hashlib.sha256(credential.encode("utf-8")).hexdigest()
        return {
            "credential_kind": "manual",
            "credential": credential,
            "generation_id": f"manual-{generation}",
            "expires_at": None,
            "bound_at": self.clock(),
        }

    def _credential_from_snapshot(self, snapshot: object) -> str:
        if not isinstance(snapshot, dict):
            raise HTTPException(status_code=409, detail="任务 laohu 凭据快照无效")
        credential = snapshot.get("credential")
        kind = snapshot.get("credential_kind")
        if not isinstance(credential, str) or not credential:
            raise HTTPException(status_code=409, detail="任务 laohu 凭据快照缺失")
        if kind == "manual":
            return credential
        if kind == "account":
            if snapshot.get("model_authorized") is not True:
                raise HTTPException(status_code=403, detail="任务账户凭据未通过模型授权核验")
            try:
                expires_at = float(snapshot.get("expires_at") or 0)
            except (TypeError, ValueError):
                expires_at = 0
            if not expires_at > self.clock():
                raise HTTPException(status_code=401, detail="任务账户令牌已过期；不会自动切换凭据")
            if not isinstance(snapshot.get("generation_id"), str) or not snapshot.get("generation_id"):
                raise HTTPException(status_code=409, detail="任务账户凭据代际无效")
            return credential
        raise HTTPException(status_code=409, detail="任务 laohu 凭据类型无效")

    def bind_execution(self, binding_id: str, *, manual_key) -> bool:
        binding_id = self._checked_binding_id(binding_id)
        with self._lock:
            try:
                session = self._read_session()
            except AccountStoreError as exc:
                raise HTTPException(status_code=409, detail="本机任务凭据存储不可用") from exc
            executions = session.setdefault("executions", {})
            if binding_id in executions:
                # Existing bindings are immutable, including after account or manual-key changes.
                self._credential_from_snapshot(executions[binding_id])
                return False
            snapshot = self._snapshot_selected_credential(session, manual_key, require_key=True)
            executions[binding_id] = snapshot
            self._write_session(session)
            return True

    def release_execution(self, binding_id: str) -> bool:
        try:
            binding_id = self._checked_binding_id(binding_id)
            with self._lock:
                session = self._read_session()
                executions = session.setdefault("executions", {})
                if binding_id not in executions:
                    return False
                executions.pop(binding_id, None)
                self._write_session(session)
                return True
        except (AccountStoreError, HTTPException, OSError):
            # Cleanup failure must not change the outcome of an already terminal task.
            return False

    def _bound_execution_credential(self, binding_id: str) -> str:
        binding_id = self._checked_binding_id(binding_id)
        with self._lock:
            try:
                session = self._read_session()
            except AccountStoreError as exc:
                raise HTTPException(status_code=409, detail="本机任务凭据存储不可用") from exc
            snapshot = session.get("executions", {}).get(binding_id)
            if snapshot is None:
                raise HTTPException(status_code=409, detail="任务 laohu 凭据快照不存在；不会读取当前凭据")
            return self._credential_from_snapshot(snapshot)

    def resolve_model_key(self, *, manual_key) -> str:
        binding_id = self._execution_binding_id.get()
        if binding_id:
            return self._bound_execution_credential(binding_id)

        cached = self._direct_key_cache.get()
        if cached is not _AUTH_CACHE_UNSET:
            if cached[0] == "error":
                raise HTTPException(status_code=cached[1], detail=cached[2])
            return cached[1]
        try:
            with self._lock:
                session = self._read_session()
                snapshot = self._snapshot_selected_credential(session, manual_key, require_key=False)
                credential = self._credential_from_snapshot(snapshot) if snapshot else ""
                credential_kind = snapshot.get("credential_kind") if snapshot else ""
            self._direct_key_cache.set(("key", credential, credential_kind))
            return credential
        except HTTPException as exc:
            self._direct_key_cache.set(("error", exc.status_code, str(exc.detail)))
            raise
        except AccountStoreError as exc:
            error = HTTPException(status_code=409, detail="本机 laohu 凭据存储不可用")
            self._direct_key_cache.set(("error", error.status_code, str(error.detail)))
            raise error from exc

    def model_credential_status(self, *, manual_key) -> dict:
        """Return safe availability metadata for provider filtering, never the credential."""
        binding_id = self._execution_binding_id.get()
        if binding_id:
            # Execution scopes are bound to their accepted identity. Missing/invalid
            # snapshots stay unavailable here and must not fall through to current mode.
            try:
                with self._lock:
                    session = self._read_session()
                    snapshot = session.get("executions", {}).get(binding_id)
                    if snapshot is None:
                        return {"has_key": False, "credential_kind": "", "bound": True}
                    self._credential_from_snapshot(snapshot)
                return {
                    "has_key": True,
                    "credential_kind": str(snapshot.get("credential_kind") or ""),
                    "bound": True,
                }
            except (AccountStoreError, HTTPException):
                return {"has_key": False, "credential_kind": "", "bound": True}

        cached = self._direct_key_cache.get()
        if cached is not _AUTH_CACHE_UNSET:
            if cached[0] == "error" or not cached[1]:
                return {"has_key": False, "credential_kind": "", "bound": False}
            return {
                "has_key": True,
                "credential_kind": str(cached[2]) if len(cached) > 2 else "",
                "bound": False,
                "pinned": True,
            }
        try:
            with self._lock:
                session = self._read_session()
                snapshot = self._snapshot_selected_credential(session, manual_key, require_key=False)
                if not snapshot:
                    return {"has_key": False, "credential_kind": "", "bound": False, "pinned": False}
                self._credential_from_snapshot(snapshot)
                return {
                    "has_key": True,
                    "credential_kind": str(snapshot.get("credential_kind") or ""),
                    "bound": False,
                    "pinned": False,
                }
        except (AccountStoreError, HTTPException):
            return {"has_key": False, "credential_kind": "", "bound": False, "pinned": False}

    def account_model_credential_available(self) -> bool:
        with self._lock:
            try:
                session = self._read_session()
            except AccountStoreError:
                return False
            if session.get("mode") != "account":
                return False
            connection = session.get("connection")
            if not isinstance(connection, dict) or connection.get("model_authorized") is not True:
                return False
            if connection.get("access_validation_state") == "rejected":
                return False
            token = connection.get("access_token")
            try:
                expires_at = float(connection.get("expires_at") or 0)
            except (TypeError, ValueError):
                return False
            return isinstance(token, str) and bool(token) and expires_at > self.clock()

    def _config(self) -> dict:
        if not self.config_path.is_file():
            raise AccountStoreError(LOGIN_UNAVAILABLE_REASON)
        _safe_file_permissions(self.config_path)
        config = _json_object(self.config_path)
        client_id = config.get("client_id")
        client_secret = config.get("client_secret")
        redirect_uri = config.get("redirect_uri")
        if (not isinstance(client_id, str) or not client_id.strip()
                or not isinstance(client_secret, str) or not client_secret.strip()
                or redirect_uri != LAOHU_CALLBACK_URI):
            raise AccountStoreError("本机 laohu 登录应用配置无效或回调地址不匹配")
        return {"client_id": client_id.strip(), "client_secret": client_secret.strip()}

    async def _balance_display_config(self) -> dict | None:
        now = self.clock()
        with self._lock:
            cached = self._balance_config_cache
            age = now - self._balance_config_cached_at
            if cached is not _BALANCE_CONFIG_UNSET and age < (
                BALANCE_CONFIG_CACHE_SECONDS if cached is not None
                else BALANCE_CONFIG_FAILURE_CACHE_SECONDS
            ):
                return cached
        config = None
        try:
            async with self.client_factory(timeout=10.0, follow_redirects=False) as client:
                response = await client.get(LAOHU_STATUS_URL, headers={"Accept": "application/json"})
            if response.status_code == 200:
                config = _balance_config(response.json())
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
            config = None
        with self._lock:
            self._balance_config_cache = config
            self._balance_config_cached_at = self.clock()
        return config

    async def _legacy_userinfo_quota(self, access_token: str) -> Decimal | None:
        try:
            async with self.client_factory(timeout=10.0, follow_redirects=False) as client:
                response = await client.get(
                    LAOHU_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                )
            if response.status_code != 200:
                return None
            return _account_quota(response.json())
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
            return None

    async def refresh_balance_display(self) -> None:
        """Refresh only the cached balance presentation; never changes identity or auth state."""
        with self._lock:
            session = self._read_session()
            connection = session.get("connection")
            if not isinstance(connection, dict) or not isinstance(connection.get("account"), dict):
                return
            generation_id = str(connection.get("generation_id") or "")
            starting_quota_value = connection.get("balance_quota")
            quota = _quota_decimal(starting_quota_value)
            access_token = str(connection.get("access_token") or "")
            try:
                expires_at = float(connection.get("expires_at") or 0)
            except (TypeError, ValueError):
                expires_at = 0
            if (expires_at <= self.clock()
                    or connection.get("access_validation_state") == "rejected"):
                return
        if quota is None and access_token:
            # Old sessions did not retain the raw quota. Re-read only the known
            # userinfo `quota` field; never reinterpret legacy display text.
            quota = await self._legacy_userinfo_quota(access_token)
        config = await self._balance_display_config()
        display = _format_balance(quota, config)
        with self._lock:
            session = self._read_session()
            current = session.get("connection")
            if not isinstance(current, dict) or str(current.get("generation_id") or "") != generation_id:
                return
            if current.get("balance_quota") != starting_quota_value:
                # A concurrent refresh installed a newer quota while the public
                # status read was waiting on HTTP; leave that result untouched.
                return
            account = current.get("account")
            if not isinstance(account, dict):
                return
            old_quota = current.get("balance_quota")
            if quota is not None:
                current["balance_quota"] = str(quota)
            old_display = account.get("balance_display")
            old_version = current.get("balance_display_version")
            new_version = (
                BALANCE_DISPLAY_VERSION if display != BALANCE_UNAVAILABLE_DISPLAY else 0
            )
            if (old_display == display and old_version == new_version
                    and (quota is None or old_quota == str(quota))):
                return
            account["balance_display"] = display
            current["balance_display_version"] = new_version
            self._write_session(session)

    def _readable_session_or_error(self) -> tuple[dict | None, str]:
        try:
            return self._read_session(), ""
        except AccountStoreError as exc:
            return None, str(exc)

    def mode(self) -> str:
        with self._lock:
            try:
                return str(self._read_session().get("mode") or "manual")
            except AccountStoreError:
                # An unreadable existing account store must never enable a manual-key fallback.
                return "account" if self.session_path.exists() else "manual"

    def set_manual_mode(self) -> str:
        with self._lock:
            session = self._read_session()
            session["mode"] = "manual"
            session["selection_revision"] += 1
            self._write_session(session)
        return "manual"

    def set_account_mode(self) -> str:
        with self._lock:
            session = self._read_session()
            connection = session.get("connection")
            try:
                valid_connection = (
                    isinstance(connection, dict)
                    and bool(connection.get("access_token"))
                    and float(connection.get("expires_at") or 0) > self.clock()
                    and connection.get("access_validation_state") != "rejected"
                )
            except (TypeError, ValueError):
                valid_connection = False
            if not valid_connection:
                raise HTTPException(status_code=409, detail="没有已连接的 laohu 账户")
            session["mode"] = "account"
            session["selection_revision"] += 1
            self._write_session(session)
        return "account"

    def public_status(
        self,
        has_manual_key: Callable[[], bool],
        manual_key_preview: Callable[[], str] | None = None,
    ) -> dict:
        config_error = ""
        try:
            self._config()
        except AccountStoreError as exc:
            config_error = str(exc)
        session, session_error = self._readable_session_or_error()
        connection = session.get("connection") if session else None
        if isinstance(connection, dict) and not isinstance(connection.get("access_token"), str):
            connection = None
        try:
            has_connection = isinstance(connection, dict) and bool(connection.get("account"))
            not_expired = bool(
                has_connection and float(connection.get("expires_at") or 0) > self.clock()
            )
        except (TypeError, ValueError):
            has_connection = False
            not_expired = False
        access_rejected = bool(
            has_connection and connection.get("access_validation_state") == "rejected"
        )
        reauth_required = bool(has_connection and (not not_expired or access_rejected))
        connected = bool(has_connection and not_expired and not access_rejected)
        connection_state = (
            "disconnected" if not has_connection else
            "reauth_required" if reauth_required else
            "refresh_unavailable" if connection.get("refresh_state") == "unavailable" else
            "connected"
        )
        model_authorized = bool(connection.get("model_authorized")) if connected else False
        reason = config_error or session_error
        mode = session.get("mode") if session else ("account" if self.session_path.exists() else "manual")
        execution_ready = bool(
            mode == "account" and connected and model_authorized and self._execution_hooks_ready
        )
        model_unavailable_reason = ""
        if mode == "account" and reauth_required:
            model_unavailable_reason = "账户访问凭据已失效，请重新连接"
        elif connected and mode == "account":
            if not model_authorized:
                model_unavailable_reason = "当前账户尚未通过模型目录授权核验"
            elif not self._execution_hooks_ready:
                model_unavailable_reason = "账户模型凭据尚未接入共享模型执行链"
        public_account = None
        if has_connection:
            stored_account = connection.get("account")
            if isinstance(stored_account, dict):
                display = stored_account.get("balance_display")
                if (connection.get("balance_display_version") != BALANCE_DISPLAY_VERSION
                        or not isinstance(display, str) or not display.strip()
                        or len(display) > 80):
                    display = BALANCE_UNAVAILABLE_DISPLAY
                if reauth_required:
                    display = BALANCE_UNAVAILABLE_DISPLAY
                public_account = {
                    "id": str(stored_account.get("id") or "")[:160],
                    "username": str(stored_account.get("username") or "")[:160],
                    "balance_display": display,
                }
        manual_key_configured = bool(has_manual_key())
        active_credential = {"kind": "none", "configured": False, "label": "", "preview": ""}
        if mode == "account" and connected and model_authorized:
            active_credential = {
                "kind": "account",
                "configured": True,
                "label": "登录自动配置",
                "preview": "••••••••",
            }
        elif mode == "manual" and manual_key_configured:
            preview = ""
            if manual_key_preview is not None:
                try:
                    preview = str(manual_key_preview() or "").strip()[:80]
                except Exception:
                    preview = ""
            active_credential = {
                "kind": "manual",
                "configured": True,
                "label": "手动 API Key",
                "preview": preview or "••••••••",
            }
        return {
            "mode": mode,
            "connected": connected,
            "connection_state": connection_state,
            "reauth_required": reauth_required,
            "connection_message": (
                "登录已失效，请重新连接" if reauth_required else ""
            ),
            "login_available": not bool(reason),
            "login_unavailable_reason": reason,
            "account": public_account,
            "links": dict(LAOHU_ACCOUNT_LINKS),
            "has_manual_key": manual_key_configured,
            "active_credential": active_credential,
            "model_authorized": model_authorized,
            "execution_ready": execution_ready,
            "model_unavailable_reason": model_unavailable_reason,
        }

    @staticmethod
    def _flow_public_result(flow_id: str, flow: dict) -> dict:
        query = urlencode({
            "client_id": flow["client_id"],
            "redirect_uri": LAOHU_CALLBACK_URI,
            "response_type": "code",
            "state": flow["state"],
            "code_challenge": flow["code_challenge"],
            "code_challenge_method": "S256",
        })
        return {
            "authorization_url": f"{LAOHU_AUTHORIZE_URL}?{query}",
            "flow_id": flow_id,
            "expires_at": datetime.fromtimestamp(flow["expires_at"], timezone.utc).isoformat(),
        }

    def start_login(self, client_operation_id: str) -> dict:
        config = self._config()
        operation_hash = hashlib.sha256(client_operation_id.encode("utf-8")).hexdigest()
        with self._lock:
            session = self._read_session()
            flows = session.setdefault("flows", {})
            for flow_id, prior in flows.items():
                if prior.get("operation_hash") == operation_hash:
                    if prior.get("status") in {"pending", "exchanging"} and float(prior.get("expires_at") or 0) > self.clock():
                        prior["client_id"] = config["client_id"]
                        return self._flow_public_result(flow_id, prior)
                    raise HTTPException(status_code=409, detail="此登录操作已结束，请重新发起登录")
            now = self.clock()
            for flow_id, prior in list(flows.items()):
                if float(prior.get("expires_at") or 0) < now - 86400:
                    flows.pop(flow_id, None)
            flow_id = secrets.token_urlsafe(24)
            state = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
            flow = {
                "operation_hash": operation_hash,
                "state": state,
                "code_verifier": verifier,
                "code_challenge": challenge,
                "client_id": config["client_id"],
                "status": "pending",
                "message": "",
                "created_at": now,
                "expires_at": now + LOGIN_FLOW_TTL_SECONDS,
                "base_selection_revision": session["selection_revision"],
            }
            flows[flow_id] = flow
            session["latest_login_flow_id"] = flow_id
            if len(flows) > 32:
                for old_id, _old in sorted(flows.items(), key=lambda item: item[1].get("created_at", 0))[:len(flows) - 32]:
                    flows.pop(old_id, None)
            self._write_session(session)
            return self._flow_public_result(flow_id, flow)

    def flow_status(self, flow_id: str) -> dict:
        with self._lock:
            session = self._read_session()
            flow = session.get("flows", {}).get(flow_id)
            if not isinstance(flow, dict):
                raise HTTPException(status_code=404, detail="登录流程不存在")
            if flow.get("status") in {"pending", "exchanging"} and float(flow.get("expires_at") or 0) <= self.clock():
                expired_during_exchange = flow.get("status") == "exchanging"
                flow["status"] = "failed"
                flow["message"] = (
                    "令牌交换状态未知，请重新登录（不会自动重试）"
                    if expired_during_exchange else "登录流程已超时，请重新登录"
                )
                flow.pop("code_verifier", None)
                self._write_session(session)
            status = flow.get("status")
            return {
                "status": "pending" if status == "exchanging" else status,
                "message": str(flow.get("message") or "")[:200],
            }

    async def _token_exchange(self, config: dict, code: str, verifier: str) -> dict:
        try:
            async with self.client_factory(timeout=15.0, follow_redirects=False) as client:
                response = await client.post(
                    LAOHU_TOKEN_URL,
                    auth=(config["client_id"], config["client_secret"]),
                    json={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": LAOHU_CALLBACK_URI,
                        "code_verifier": verifier,
                    },
                )
        except httpx.TimeoutException as exc:
            raise AccountStoreError("令牌交换网络超时") from exc
        except httpx.HTTPError as exc:
            raise AccountStoreError("令牌交换网络请求失败") from exc
        if response.status_code != 200:
            raise AccountStoreError(f"令牌交换 HTTP {response.status_code}")
        try:
            value = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise AccountStoreError("令牌服务响应格式无效") from exc
        if not isinstance(value, dict):
            raise AccountStoreError(
                "令牌服务响应未满足安全令牌格式（"
                f"{_token_response_shape_diagnostic(value)}）"
            )
        data = value.get("data")
        if (
            value.get("success") is False
            or ("success" in value and not isinstance(value.get("success"), bool))
            or "error" in value
            or (isinstance(data, dict) and "error" in data)
        ):
            raise AccountStoreError(
                "令牌服务响应未满足安全令牌格式（"
                f"{_token_response_shape_diagnostic(value)}）"
            )
        if "access_token" in value:
            token_value = value
        elif value.get("success") is True and isinstance(data, dict):
            token_value = data
        else:
            raise AccountStoreError(
                "令牌服务响应未满足安全令牌格式（"
                f"{_token_response_shape_diagnostic(value)}）"
            )
        token = token_value.get("access_token")
        token_type = token_value.get("token_type")
        if (
            not isinstance(token, str)
            or not token.strip()
            or not isinstance(token_type, str)
            or token_type.strip().lower() != "bearer"
        ):
            raise AccountStoreError(
                "令牌服务响应未满足安全令牌格式（"
                f"{_token_response_shape_diagnostic(value)}）"
            )
        token = token.strip()
        refresh_value = value.get("refresh_token") if "refresh_token" in value else token_value.get("refresh_token")
        expiry_value = value.get("expires_in") if "expires_in" in value else token_value.get("expires_in")
        return {
            "access_token": token,
            "refresh_token": refresh_value if isinstance(refresh_value, str) else "",
            "expires_at": self.clock() + max(0, int(expiry_value or 0)) if str(expiry_value or "").isdigit() else 0,
        }

    async def _inspect_access(self, access_token: str) -> tuple[dict, bool | None, str | None]:
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        async with self.client_factory(timeout=15.0, follow_redirects=False) as client:
            try:
                user_response = await client.get(LAOHU_USERINFO_URL, headers=headers)
            except httpx.TimeoutException as exc:
                raise AccountTemporaryError("账户身份读取网络超时") from exc
            except httpx.HTTPError as exc:
                raise AccountTemporaryError("账户身份读取网络请求失败") from exc
            if user_response.status_code != 200:
                if user_response.status_code in {401, 403}:
                    raise AccountInvalidError(f"账户身份 HTTP {user_response.status_code}，登录已失效")
                if user_response.status_code == 429 or user_response.status_code >= 500:
                    raise AccountTemporaryError(
                        f"账户身份 HTTP {user_response.status_code}，连接状态未更改"
                    )
                raise AccountStoreError(f"账户身份 HTTP {user_response.status_code}，连接状态未更改")
            try:
                user_json = user_response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise AccountStoreError("账户身份响应格式无效") from exc
            quota = _account_quota(user_json)
            balance_config = await self._balance_display_config()
            account = _account_record(
                user_json,
                balance_display=_format_balance(quota, balance_config),
            )
            if account is None:
                raise AccountStoreError("账户身份响应缺少有效账户标识")
            model_authorized: bool | None
            try:
                models_response = await client.get(LAOHU_MODELS_URL, headers=headers)
                if models_response.status_code == 200:
                    models_json = models_response.json()
                    model_authorized = _models_response_is_authorized(models_json)
                elif models_response.status_code == 429 or models_response.status_code >= 500:
                    model_authorized = None
                else:
                    model_authorized = False
            except httpx.HTTPError:
                model_authorized = None
            except (ValueError, json.JSONDecodeError):
                model_authorized = False
        return account, model_authorized, str(quota) if quota is not None else None

    def _finish_flow(self, flow_id: str, status: str, message: str, *, connection: dict | None = None) -> bool:
        with self._lock:
            session = self._read_session()
            flow = session.get("flows", {}).get(flow_id)
            if not isinstance(flow, dict):
                return False
            if status == "succeeded" and flow.get("status") != "exchanging":
                return False
            if status == "failed" and flow.get("status") not in {"pending", "exchanging"}:
                return False
            expired_exchange = (
                status == "succeeded"
                and flow.get("status") == "exchanging"
                and float(flow.get("expires_at") or 0) <= self.clock()
            )
            if expired_exchange:
                status = "failed"
                message = "令牌交换状态未知，请重新登录（不会自动重试）"
            still_selected = (
                flow.get("status") == "exchanging"
                and float(flow.get("expires_at") or 0) > self.clock()
                and int(flow.get("base_selection_revision") or 0) == session["selection_revision"]
                and session.get("latest_login_flow_id") == flow_id
            )
            adopted = bool(status == "succeeded" and connection and still_selected)
            if status == "succeeded" and connection and adopted:
                session["connection"] = connection
                session["mode"] = "account"
                session["selection_revision"] += 1
            elif status == "succeeded" and connection:
                message = "登录已完成，但账户选择已变化；请重新发起连接"
            flow["status"] = status
            flow["message"] = message[:200]
            flow.pop("code_verifier", None)
            self._write_session(session)
            return adopted

    async def handle_callback(self, code: str, state_value: str, error: str = "") -> bool:
        flow_id = ""
        verifier = ""
        with self._lock:
            session = self._read_session()
            match = next(((key, flow) for key, flow in session.get("flows", {}).items()
                          if isinstance(flow, dict) and hmac.compare_digest(str(flow.get("state") or ""), state_value)), None)
            if not match:
                return False
            flow_id, flow = match
            if flow.get("status") != "pending":
                return flow.get("status") == "succeeded"
            if float(flow.get("expires_at") or 0) <= self.clock():
                flow["status"] = "failed"
                flow["message"] = "登录流程已超时，请重新登录"
                flow.pop("code_verifier", None)
                self._write_session(session)
                return False
            if error:
                flow["status"] = "failed"
                flow["message"] = "用户取消了账户授权" if error == "access_denied" else "账户授权未完成"
                flow.pop("code_verifier", None)
                self._write_session(session)
                return False
            if not code:
                flow["status"] = "failed"
                flow["message"] = "授权回调缺少授权码"
                flow.pop("code_verifier", None)
                self._write_session(session)
                return False
            flow["status"] = "exchanging"
            verifier = str(flow.get("code_verifier") or "")
            self._write_session(session)
        try:
            config = self._config()
            token_data = await self._token_exchange(config, code, verifier)
            account, model_authorized, balance_quota = await self._inspect_access(token_data["access_token"])
            model_authorized = bool(model_authorized)
        except AccountStoreError as exc:
            self._finish_flow(flow_id, "failed", str(exc))
            return False
        except (httpx.HTTPError, OSError, ValueError, TypeError):
            self._finish_flow(flow_id, "failed", "授权流程处理失败，结果无法确认")
            return False
        connection = {
            "generation_id": uuid.uuid4().hex,
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "expires_at": token_data["expires_at"],
            "account": account,
            "balance_quota": balance_quota,
            "balance_display_version": (
                BALANCE_DISPLAY_VERSION
                if account.get("balance_display") != BALANCE_UNAVAILABLE_DISPLAY else 0
            ),
            "model_authorized": model_authorized,
            "connected_at": self.clock(),
        }
        message = "账户已连接；模型授权已核验" if model_authorized else "账户已连接，但模型调用权限尚未核验"
        self._finish_flow(flow_id, "succeeded", message, connection=connection)
        return True

    def callback_flow_is_active(self, state_value: str) -> bool:
        """Return whether state identifies a live, unprocessed OAuth callback flow."""
        with self._lock:
            session = self._read_session()
            for flow in session.get("flows", {}).values():
                if not isinstance(flow, dict):
                    continue
                if not hmac.compare_digest(str(flow.get("state") or ""), state_value):
                    continue
                return (
                    flow.get("status") in {"pending", "exchanging"}
                    and float(flow.get("expires_at") or 0) > self.clock()
                )
        return False

    async def refresh_connection(self) -> None:
        with self._lock:
            session = self._read_session()
            connection = session.get("connection")
            if not isinstance(connection, dict) or not connection.get("access_token"):
                raise HTTPException(status_code=409, detail="没有已连接的 laohu 账户，无法刷新")
            access_token = str(connection["access_token"])
            generation_id = str(connection.get("generation_id") or "")
            selection_revision = int(session.get("selection_revision") or 0)
            try:
                check_revision = int(connection.get("refresh_check_revision") or 0) + 1
            except (TypeError, ValueError):
                check_revision = 1
            connection["refresh_check_revision"] = check_revision
            self._write_session(session)
        try:
            account, model_authorized, balance_quota = await self._inspect_access(access_token)
        except AccountInvalidError as exc:
            with self._lock:
                session = self._read_session()
                current = session.get("connection")
                if (isinstance(current, dict)
                        and current.get("generation_id") == generation_id
                        and current.get("refresh_check_revision") == check_revision
                        and int(session.get("selection_revision") or 0) == selection_revision):
                    current["access_validation_state"] = "rejected"
                    current.pop("refresh_state", None)
                    self._write_session(session)
            raise HTTPException(status_code=401, detail="账户访问凭据已被服务端拒绝，请重新连接") from exc
        except AccountTemporaryError as exc:
            with self._lock:
                session = self._read_session()
                current = session.get("connection")
                if (isinstance(current, dict)
                        and current.get("generation_id") == generation_id
                        and current.get("refresh_check_revision") == check_revision
                        and int(session.get("selection_revision") or 0) == selection_revision):
                    current["refresh_state"] = "unavailable"
                    self._write_session(session)
            raise HTTPException(status_code=502, detail="账户状态暂时无法读取，请稍后重试；连接凭据已保留") from exc
        except AccountStoreError as exc:
            raise HTTPException(status_code=502, detail="刷新账户状态失败，连接状态未更改") from exc
        except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=502, detail="刷新账户状态失败，请稍后重试") from exc
        with self._lock:
            session = self._read_session()
            current = session.get("connection")
            if (isinstance(current, dict)
                    and current.get("generation_id") == generation_id
                    and current.get("refresh_check_revision") == check_revision
                    and int(session.get("selection_revision") or 0) == selection_revision):
                current["account"] = account
                current["balance_quota"] = balance_quota
                current["balance_display_version"] = (
                    BALANCE_DISPLAY_VERSION
                    if account.get("balance_display") != BALANCE_UNAVAILABLE_DISPLAY else 0
                )
                if model_authorized is not None:
                    current["model_authorized"] = bool(model_authorized)
                current["checked_at"] = self.clock()
                current.pop("access_validation_state", None)
                current.pop("refresh_state", None)
                self._write_session(session)

    def logout(self) -> None:
        with self._lock:
            session = self._read_session()
            session["connection"] = None
            session["flows"] = {}
            session["latest_login_flow_id"] = ""
            session["selection_revision"] += 1
            self._write_session(session)


def account_status(
    state: LaohuAccountState,
    has_manual_key: Callable[[], bool],
    manual_key_preview: Callable[[], str] | None = None,
) -> dict:
    return state.public_status(has_manual_key, manual_key_preview)


def _no_store_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"}


def _callback_response(*, close_allowed: bool = False) -> HTMLResponse:
    nonce = secrets.token_urlsafe(18)
    headers = {
        **_no_store_headers(),
        "Content-Security-Policy": (
            f"default-src 'none'; script-src 'nonce-{nonce}'; "
            "base-uri 'none'; frame-ancestors 'none'"
        ),
    }
    cleanup_script = "history.replaceState(null,\"\",\"/api/laohu/account/callback/complete\");"
    close_script = (
        "const showFallback=()=>{if(window.closed)return;"
        "const message=document.createElement('p');"
        "message.textContent='请关闭此页返回画梦枋';document.body.appendChild(message);};"
        "window.close();setTimeout(showFallback,600);"
        if close_allowed else ""
    )
    html = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"referrer\" content=\"no-referrer\"><title>laohu 登录</title>"
        f"<script nonce=\"{nonce}\">"
        + cleanup_script + close_script
        + "</script></head><body></body></html>"
    )
    return HTMLResponse(html, headers=headers)


def create_laohu_account_router(
    state: LaohuAccountState,
    *,
    has_manual_key: Callable[[], bool],
    manual_key_preview: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/laohu/account", tags=["Laohu account"])

    @router.get("/status")
    async def status(request: Request, response: Response):
        _require_local_request(request)
        response.headers.update(_no_store_headers())
        try:
            await state.refresh_balance_display()
        except (AccountStoreError, OSError, ValueError, TypeError):
            # A balance formatting failure must not invalidate a connected identity.
            pass
        return account_status(state, has_manual_key, manual_key_preview)

    @router.post("/login")
    async def login(payload: LaohuAccountLoginRequest, request: Request, response: Response):
        _require_local_request(request, action=True)
        try:
            value = state.start_login(payload.client_operation_id.strip())
        except AccountStoreError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        response.headers.update(_no_store_headers())
        return value

    @router.get("/login/{flow_id}")
    async def login_status(flow_id: str, request: Request, response: Response):
        _require_local_request(request)
        response.headers.update(_no_store_headers())
        try:
            return state.flow_status(flow_id)
        except AccountStoreError as exc:
            raise HTTPException(status_code=503, detail="本机账户会话不可读取") from exc

    @router.get("/callback")
    async def callback(
        request: Request,
        code: str = Query(default="", max_length=4096),
        state_value: str = Query(default="", alias="state", max_length=256),
        error: str = Query(default="", max_length=128),
    ):
        # OAuth redirects are top-level cross-site navigations. Require the exact
        # registered local callback origin instead of the same-origin write header.
        _require_callback_peer(request)
        if request.url.path != "/api/laohu/account/callback":
            raise HTTPException(status_code=404, detail="OAuth 回调地址不匹配")
        try:
            close_allowed = state.callback_flow_is_active(state_value)
            await state.handle_callback(code, state_value, error)
        except AccountStoreError as exc:
            raise HTTPException(status_code=503, detail="本机账户会话不可用") from exc
        return _callback_response(close_allowed=close_allowed)

    @router.get("/callback/complete", response_class=HTMLResponse)
    async def callback_complete(request: Request):
        _require_callback_peer(request)
        return HTMLResponse(
            "<!doctype html><meta charset=\"utf-8\"><meta name=\"referrer\" content=\"no-referrer\">"
            "<title>laohu 登录</title>",
            headers=_no_store_headers(),
        )

    @router.post("/logout")
    async def logout(request: Request, response: Response):
        _require_local_request(request, action=True)
        try:
            state.logout()
        except AccountStoreError as exc:
            raise HTTPException(status_code=503, detail="本机账户会话不可用") from exc
        response.headers.update(_no_store_headers())
        return {"success": True, **account_status(state, has_manual_key, manual_key_preview)}

    @router.post("/mode")
    async def set_mode(payload: LaohuAccountModeRequest, request: Request, response: Response):
        _require_local_request(request, action=True)
        try:
            if payload.mode == "account":
                state.set_account_mode()
            else:
                state.set_manual_mode()
        except AccountStoreError as exc:
            raise HTTPException(status_code=503, detail="本机账户会话不可用") from exc
        response.headers.update(_no_store_headers())
        return account_status(state, has_manual_key, manual_key_preview)

    @router.post("/refresh")
    async def refresh(request: Request, response: Response):
        _require_local_request(request, action=True)
        try:
            await state.refresh_connection()
        except HTTPException:
            raise
        except AccountStoreError as exc:
            raise HTTPException(status_code=503, detail="本机账户会话不可用") from exc
        response.headers.update(_no_store_headers())
        return account_status(state, has_manual_key, manual_key_preview)

    return router
