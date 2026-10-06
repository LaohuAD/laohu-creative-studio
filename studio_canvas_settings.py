"""画布模型设置图及精确模型管理接口的边界。"""
from __future__ import annotations

import copy
import inspect
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, Body, HTTPException


CANVAS_SETTINGS_CANVAS_ID = "canvas-settings"
CANVAS_SETTINGS_CANVAS_URL = (
    f"/static/smart-canvas.html?id={CANVAS_SETTINGS_CANVAS_ID}&mode=canvas-settings"
)
CANVAS_SETTINGS_ROUTE = "/api/studio/canvas/settings-canvas"
MODEL_MANAGEMENT_CATALOG_ROUTE = "/api/studio/canvas/model-management-catalog"
MODEL_ENABLEMENT_ROUTE = "/api/studio/canvas/model-enablement"

_GRAPH_FIELDS = ("nodes", "connections", "viewport", "logs", "settings")
_TRANSPORT_FIELDS = {
    "base_revision",
    "base_updated_at",
    "client_id",
    "migration_version",
}


class CanvasSettingsService:
    """让模型管理图复用现有画布保存链。

    存储、校验、锁与实时通知均由调用方注入，便于在不加载真实配置的
    情况下验证并发与重置行为。
    """

    def __init__(
        self,
        *,
        load_canvas: Callable[[str], Any],
        save_canvas: Callable[..., Any],
        lock: Any,
        validate_canvas: Callable[[Mapping[str, Any]], Any],
        broadcast_canvas_updated: Callable[[str, int, int, str], Any],
        now_ms: Callable[[], int],
        reset_display_preferences: Callable[[], Any] | None = None,
        canvas_id: str = CANVAS_SETTINGS_CANVAS_ID,
        canvas_url: str = CANVAS_SETTINGS_CANVAS_URL,
        title: str = "画布模型设置",
        project_id: str = "__canvas_settings__",
    ):
        if canvas_id != CANVAS_SETTINGS_CANVAS_ID:
            raise ValueError("画布模型设置只能使用保留 ID canvas-settings")
        self.canvas_id = canvas_id
        self.canvas_url = canvas_url
        self.title = title
        self.project_id = project_id
        self._load_canvas = load_canvas
        self._save_canvas = save_canvas
        self.lock = lock
        self._validate_canvas = validate_canvas
        self._broadcast_canvas_updated = broadcast_canvas_updated
        self._now_ms = now_ms
        self._reset_display_preferences = reset_display_preferences

    @staticmethod
    def _as_dict(payload: Any) -> dict[str, Any]:
        if isinstance(payload, Mapping):
            return dict(payload)
        model_dump = getattr(payload, "model_dump", None)
        if callable(model_dump):
            result = model_dump()
            if isinstance(result, Mapping):
                return dict(result)
        legacy_dict = getattr(payload, "dict", None)
        if callable(legacy_dict):
            result = legacy_dict()
            if isinstance(result, Mapping):
                return dict(result)
        raise HTTPException(status_code=400, detail="画布设置请求必须是对象")

    def _blank_canvas(self) -> dict[str, Any]:
        stamp = int(self._now_ms())
        return {
            "id": self.canvas_id,
            "title": self.title,
            "icon": "settings",
            "kind": "smart",
            "owner": "",
            "color": "",
            "pinned": False,
            "project": self.project_id,
            "created_at": stamp,
            "updated_at": stamp,
            "revision": 1,
            "node_schema_version": 1,
            "nodes": [],
            "connections": [],
            "viewport": {"x": 0, "y": 0, "scale": 1},
            "logs": [],
            "settings": {},
        }

    def _validate(self, canvas: Mapping[str, Any], *, status_code: int = 400) -> None:
        if not isinstance(canvas, Mapping) or canvas.get("id") != self.canvas_id:
            raise HTTPException(status_code=status_code, detail="画布模型设置身份无效")
        for key in ("nodes", "connections", "logs"):
            if not isinstance(canvas.get(key), list):
                raise HTTPException(status_code=status_code, detail=f"画布设置 {key} 必须是数组")
        if not isinstance(canvas.get("viewport"), Mapping) or not isinstance(canvas.get("settings"), Mapping):
            raise HTTPException(status_code=status_code, detail="画布设置 viewport 或 settings 格式无效")
        if any(
            isinstance(node, Mapping) and node.get("type") == "smart-hypit-output"
            for node in canvas["nodes"]
        ):
            raise HTTPException(status_code=status_code, detail="模型管理画布不支持用途输出端口")
        try:
            result = self._validate_canvas(canvas)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=status_code, detail=f"画布模型设置校验失败：{exc}") from exc
        if inspect.isawaitable(result):
            raise TypeError("validate_canvas 必须是同步校验回调")

    def _save(self, canvas: dict[str, Any], *, increment_revision: bool, touch_updated_at: bool) -> dict[str, Any]:
        result = self._save_canvas(
            canvas,
            increment_revision=increment_revision,
            touch_updated_at=touch_updated_at,
        )
        if result is None:
            result = canvas
        if not isinstance(result, Mapping):
            raise HTTPException(status_code=500, detail="画布模型设置保存失败")
        result = copy.deepcopy(dict(result))
        self._validate(result, status_code=500)
        return result

    def ensure_canvas(self) -> dict[str, Any]:
        with self.lock:
            try:
                current = self._load_canvas(self.canvas_id)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                current = None
            except (FileNotFoundError, KeyError):
                current = None
            if current is None:
                return self._save(
                    self._blank_canvas(), increment_revision=False, touch_updated_at=False
                )
            if not isinstance(current, Mapping) or current.get("id") != self.canvas_id:
                raise HTTPException(status_code=500, detail="画布模型设置存储身份无效，原数据已保留")
            result = copy.deepcopy(dict(current))
            result.setdefault("nodes", [])
            result.setdefault("connections", [])
            result.setdefault("viewport", {"x": 0, "y": 0, "scale": 1})
            result.setdefault("logs", [])
            result.setdefault("settings", {})
            self._validate(result, status_code=500)
            return result

    async def projected_canvas(self, canvas: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return copy.deepcopy(dict(canvas if canvas is not None else self.ensure_canvas()))

    @staticmethod
    def _revision_conflict(current: Mapping[str, Any]) -> HTTPException:
        revision = max(1, int(current.get("revision") or 1))
        return HTTPException(status_code=409, detail={
            "message": "画布模型设置已在其他页面更新，请重新读取后重试。",
            "canvas": copy.deepcopy(dict(current)),
            "revision": revision,
            "updated_at": int(current.get("updated_at") or 0),
        })

    def prepare_update_candidate(self, current: Mapping[str, Any], payload: Any) -> dict[str, Any]:
        body = self._as_dict(payload)
        expected = body.get("base_revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected <= 0:
            raise HTTPException(status_code=400, detail="base_revision 必须是大于零的整数")
        current_revision = max(1, int(current.get("revision") or 1))
        if expected != current_revision:
            raise self._revision_conflict(current)

        candidate = copy.deepcopy(dict(current))
        for key in _GRAPH_FIELDS:
            if key in body:
                candidate[key] = copy.deepcopy(body[key])
        # Identity and transport fields never come from a browser/Agent payload.
        candidate["id"] = self.canvas_id
        candidate["title"] = current.get("title", self.title)
        candidate["icon"] = current.get("icon", "settings")
        candidate["kind"] = "smart"
        candidate["project"] = self.project_id
        self._validate(candidate)
        return candidate

    def save_agent_canvas(
        self,
        canvas: dict[str, Any],
        *,
        increment_revision: bool = True,
        touch_updated_at: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(canvas, dict) or canvas.get("id") != self.canvas_id:
            raise HTTPException(status_code=400, detail="画布模型设置身份无效")
        with self.lock:
            current = self.ensure_canvas()
            expected = canvas.get("revision")
            current_revision = max(1, int(current.get("revision") or 1))
            if isinstance(expected, bool) or not isinstance(expected, int) or expected != current_revision:
                raise self._revision_conflict(current)
            candidate = copy.deepcopy(current)
            for key in _GRAPH_FIELDS:
                if key in canvas:
                    candidate[key] = copy.deepcopy(canvas[key])
            candidate["id"] = self.canvas_id
            candidate["title"] = current.get("title", self.title)
            candidate["icon"] = current.get("icon", "settings")
            candidate["kind"] = "smart"
            candidate["project"] = self.project_id
            self._validate(candidate)
            saved = self._save(
                candidate,
                increment_revision=increment_revision,
                touch_updated_at=touch_updated_at,
            )
            canvas.clear()
            canvas.update(copy.deepcopy(saved))
            return saved

    async def reset_canvas(self, payload: Any) -> dict[str, Any]:
        body = self._as_dict(payload)
        expected = body.get("base_revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected <= 0:
            raise HTTPException(status_code=400, detail="base_revision 必须是大于零的整数")
        client_id = str(body.get("client_id") or "")
        with self.lock:
            current = self.ensure_canvas()
            current_revision = max(1, int(current.get("revision") or 1))
            if expected != current_revision:
                raise self._revision_conflict(current)

            reset_preferences = None
            if self._reset_display_preferences is not None:
                try:
                    reset_preferences = self._reset_display_preferences()
                    if inspect.isawaitable(reset_preferences):
                        close = getattr(reset_preferences, "close", None)
                        if callable(close):
                            close()
                        raise TypeError("reset_display_preferences 必须是同步回调")
                    required_preference_maps = {
                        "executionLayouts", "modelOrder", "parameterOptionOrder", "parameterPresentation",
                    }
                    if (
                        not isinstance(reset_preferences, Mapping)
                        or isinstance(reset_preferences.get("version"), bool)
                        or not isinstance(reset_preferences.get("version"), int)
                        or reset_preferences.get("version") != 1
                        or not required_preference_maps.issubset(reset_preferences)
                        or any(not isinstance(reset_preferences.get(key), Mapping) for key in required_preference_maps)
                    ):
                        raise ValueError("展示偏好重置回调未返回完整的版本 1 配置")
                    reset_preferences = copy.deepcopy(dict(reset_preferences))
                except Exception as exc:
                    reason = exc.detail if isinstance(exc, HTTPException) else str(exc)
                    status_code = exc.status_code if isinstance(exc, HTTPException) else 500
                    raise HTTPException(status_code=status_code, detail={
                        "message": "显示设置未能恢复，配置画布未清空；请处理原因后重试。",
                        "preferences_reset": False,
                        "canvas_reset": False,
                        "revision": current_revision,
                        "reason": reason,
                    }) from exc

            candidate = copy.deepcopy(current)
            candidate.update({
                "nodes": [],
                "connections": [],
                "viewport": {"x": 0, "y": 0, "scale": 1},
                "logs": [],
                "settings": {},
            })
            self._validate(candidate)
            try:
                saved = self._save(candidate, increment_revision=True, touch_updated_at=True)
            except Exception as exc:
                if reset_preferences is None:
                    raise
                revision = current_revision
                try:
                    persisted = self._load_canvas(self.canvas_id)
                    if isinstance(persisted, Mapping) and persisted.get("id") == self.canvas_id:
                        revision = max(1, int(persisted.get("revision") or current_revision))
                except Exception:
                    pass
                reason = exc.detail if isinstance(exc, HTTPException) else str(exc)
                raise HTTPException(status_code=500, detail={
                    "message": "显示设置已恢复，但配置画布尚未清空；请基于当前版本重试。",
                    "preferences_reset": True,
                    "canvas_reset": False,
                    "revision": revision,
                    "preferences": copy.deepcopy(reset_preferences),
                    "reason": reason,
                }) from exc
        await self.broadcast_canvas_revision(saved, client_id)
        response = {"id": self.canvas_id, "canvas": saved, "reset": True}
        if reset_preferences is not None:
            response["preferences_reset"] = True
            response["preferences"] = reset_preferences
        return response

    async def broadcast_canvas_revision(self, canvas: Mapping[str, Any], client_id: str = "") -> None:
        result = self._broadcast_canvas_updated(
            self.canvas_id,
            int(canvas.get("updated_at") or self._now_ms()),
            max(1, int(canvas.get("revision") or 1)),
            str(client_id or ""),
        )
        if inspect.isawaitable(result):
            await result


def create_canvas_settings_router(
    service: CanvasSettingsService,
    *,
    get_catalog: Callable[[], Any] | None = None,
    patch_enabled: Callable[[str, bool, str], Any] | None = None,
    base_path: str = CANVAS_SETTINGS_ROUTE,
) -> APIRouter:
    """注册设置图读取/重置与精确选项启停接口。"""
    router = APIRouter()

    @router.get(base_path)
    async def get_canvas_settings():
        canvas = service.ensure_canvas()
        return {"id": service.canvas_id, "canvas": canvas, "url": service.canvas_url}

    @router.post(f"{base_path}/reset")
    async def reset_canvas_settings(payload: dict[str, Any] = Body(...)):
        return await service.reset_canvas(payload)

    @router.get(MODEL_MANAGEMENT_CATALOG_ROUTE)
    async def get_model_management_catalog():
        if get_catalog is None:
            raise HTTPException(status_code=503, detail="模型管理目录尚未接入")
        result = get_catalog()
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, Mapping) or not isinstance(result.get("options"), list):
            raise HTTPException(status_code=502, detail="模型管理目录响应无效")
        return copy.deepcopy(dict(result))

    @router.patch(MODEL_ENABLEMENT_ROUTE)
    async def patch_model_enablement(payload: dict[str, Any] = Body(...)):
        if patch_enabled is None:
            raise HTTPException(status_code=503, detail="模型启用设置尚未接入")
        option_id = payload.get("option_id")
        enabled = payload.get("enabled")
        catalog_revision = payload.get("catalog_revision")
        if not isinstance(option_id, str) or not option_id.strip():
            raise HTTPException(status_code=400, detail="option_id 无效")
        if not isinstance(enabled, bool):
            raise HTTPException(status_code=400, detail="enabled 必须是布尔值")
        if not isinstance(catalog_revision, str) or not catalog_revision.strip():
            raise HTTPException(status_code=400, detail="catalog_revision 无效")
        if set(payload) != {"option_id", "enabled", "catalog_revision"}:
            raise HTTPException(status_code=400, detail="只允许更新一个精确模型选项")
        result = patch_enabled(option_id.strip(), enabled, catalog_revision.strip())
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, Mapping):
            raise HTTPException(status_code=502, detail="模型启用设置响应无效")
        return copy.deepcopy(dict(result))

    return router
