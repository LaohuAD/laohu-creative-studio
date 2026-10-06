"""Hypit 设置专用画布的存储边界；画布更新委托宿主的标准保存链。"""
from __future__ import annotations

import copy
import inspect
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from studio_canvas_settings import CANVAS_SETTINGS_CANVAS_ID

from canvas_core.hypit_config import (
    HYPIT_FLOW_SCHEMA_VERSION,
    HYPIT_SETTINGS_CANVAS_ID,
    upgrade_hypit_legacy_prompt_scaffold,
)


HYPIT_SETTINGS_PROJECT_ID = "__hypit_settings__"
HYPIT_SETTINGS_CANVAS_URL = f"/static/smart-canvas.html?id={HYPIT_SETTINGS_CANVAS_ID}&mode=hypit-settings"
ARTICLE_SETTINGS_CANVAS_ID = "article-settings"
ARTICLE_SETTINGS_PROJECT_ID = "__article_settings__"
ARTICLE_SETTINGS_CANVAS_URL = f"/static/smart-canvas.html?id={ARTICLE_SETTINGS_CANVAS_ID}&mode=article-settings"


def is_settings_canvas(value: Any, canvas_id: str | None = None) -> bool:
    """按明确保留 ID 识别设置图，不从画布内容推测身份。"""
    if isinstance(value, Mapping):
        value = value.get("id")
    selected_id = str(value or "").strip()
    if canvas_id is not None:
        return selected_id == str(canvas_id)
    return selected_id in {HYPIT_SETTINGS_CANVAS_ID, ARTICLE_SETTINGS_CANVAS_ID, CANVAS_SETTINGS_CANVAS_ID}


def is_hypit_settings_canvas(value: Any) -> bool:
    """识别保留配置图 ID；不依赖它是否已初始化或数据形状是否完整。"""
    return is_settings_canvas(value, HYPIT_SETTINGS_CANVAS_ID)


def filter_hypit_settings_canvas_records(records):
    """从普通画布列表中过滤专用配置图记录。"""
    return [item for item in records if not is_hypit_settings_canvas(item)]


def filter_settings_canvas_records(records):
    """从普通画布列表中过滤全部模块专用配置图。"""
    return [item for item in records if not is_settings_canvas(item)]


def reject_hypit_settings_canvas_mutation(canvas_id: str, operation: str) -> None:
    """阻止通用作品管理入口修改 Hypit 配置图身份或生命周期。"""
    if is_hypit_settings_canvas(canvas_id):
        raise HTTPException(status_code=409, detail=f"Hypit 配置图不是普通作品，不能{operation}")


def reject_settings_canvas_mutation(canvas_id: str, operation: str) -> None:
    """阻止通用作品入口改变模块配置图的身份或生命周期。"""
    if is_settings_canvas(canvas_id):
        raise HTTPException(status_code=409, detail=f"模块配置图不是普通作品，不能{operation}")


class HypitSettingsCanvasService:
    """仅管理 Hypit 配置图初始化、重置和请求投影，不复制通用画布更新链。"""

    def __init__(
        self,
        *,
        load_canvas: Callable[[str], dict[str, Any]],
        save_canvas: Callable[..., Any],
        lock: Any,
        load_legacy_settings: Callable[[], Any],
        backup_legacy_settings: Callable[[Any], Any],
        backup_scaffold: Callable[[Mapping[str, Any]], Any] | None = None,
        migrate_legacy_settings: Callable[[Mapping[str, Any], str], dict[str, Any]],
        validate_canvas: Callable[[Mapping[str, Any]], Any],
        test_statuses: Callable[[str, Mapping[str, Any]], Any],
        broadcast_canvas_updated: Callable[[str, int, int, str], Any],
        now_ms: Callable[[], int],
        canvas_id: str = HYPIT_SETTINGS_CANVAS_ID,
        module_id: str = "hypit",
        canvas_url: str | None = None,
        title: str | None = None,
        project_id: str | None = None,
        migrate_legacy: bool | None = None,
    ):
        if module_id not in {"hypit", "article"}:
            raise ValueError("设置画布模块不受支持")
        if not canvas_id or (module_id == "hypit" and canvas_id != HYPIT_SETTINGS_CANVAS_ID) or (
            module_id == "article" and canvas_id != ARTICLE_SETTINGS_CANVAS_ID
        ):
            raise ValueError("设置画布 ID 与模块不匹配")
        self.canvas_id = canvas_id
        self.module_id = module_id
        self.project_id = project_id or (HYPIT_SETTINGS_PROJECT_ID if module_id == "hypit" else ARTICLE_SETTINGS_PROJECT_ID)
        self.canvas_url = canvas_url or (HYPIT_SETTINGS_CANVAS_URL if module_id == "hypit" else ARTICLE_SETTINGS_CANVAS_URL)
        self.title = title or ("Hypit 生成配置" if module_id == "hypit" else "文章生成配置")
        self.migrate_legacy = module_id == "hypit" if migrate_legacy is None else bool(migrate_legacy)
        self.schema_version_key = "hypit_flow_schema_version" if module_id == "hypit" else "article_flow_schema_version"
        self.migration_done_key = "hypit_legacy_migration_done" if module_id == "hypit" else "article_settings_initialized"
        self._load_canvas = load_canvas
        self._save_canvas = save_canvas
        self._lock = lock
        self._load_legacy_settings = load_legacy_settings
        self._backup_legacy_settings = backup_legacy_settings
        self._backup_scaffold = backup_scaffold
        self._migrate_legacy_settings = migrate_legacy_settings
        self._validate_canvas = validate_canvas
        self._test_statuses = test_statuses
        self._broadcast_canvas_updated = broadcast_canvas_updated
        self._now_ms = now_ms

    @staticmethod
    def _legacy_defaults(record: Any) -> Mapping[str, Any]:
        if record is None:
            return {}
        if not isinstance(record, Mapping):
            raise HTTPException(status_code=500, detail="旧 Hypit 设置格式无效，原文件已保留")
        value = record.get("defaults")
        if value is None:
            value = record.get("slots")
        if value is None:
            value = record
        if not isinstance(value, Mapping):
            raise HTTPException(status_code=500, detail="旧 Hypit 设置槽位格式无效，原文件已保留")
        return value

    def _blank_canvas(self) -> dict[str, Any]:
        stamp = int(self._now_ms())
        return {
            "id": self.canvas_id,
            "title": self.title,
            "icon": "sparkles",
            "kind": "smart",
            "owner": "",
            "color": "",
            "pinned": False,
            "project": self.project_id,
            "created_at": stamp,
            "updated_at": stamp,
            "revision": 1,
            "node_schema_version": 1,
            self.schema_version_key: HYPIT_FLOW_SCHEMA_VERSION,
            self.migration_done_key: True,
            "nodes": [],
            "connections": [],
            "viewport": {"x": 0, "y": 0, "scale": 1},
            "logs": [],
            "settings": {},
        }

    def _load_current(self) -> dict[str, Any] | None:
        try:
            current = self._load_canvas(self.canvas_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                return None
            raise
        except FileNotFoundError:
            return None
        if not isinstance(current, dict) or current.get("id") != self.canvas_id:
            raise HTTPException(status_code=500, detail=f"{self.module_id} 配置图存储记录格式无效")
        return current

    def _persist(self, canvas: dict[str, Any], *, increment_revision: bool, touch_updated_at: bool) -> dict[str, Any]:
        saved = self._save_canvas(canvas, increment_revision=increment_revision, touch_updated_at=touch_updated_at)
        result = saved if isinstance(saved, dict) else canvas
        result["id"] = self.canvas_id
        result["kind"] = "smart"
        result["project"] = self.project_id
        result[self.schema_version_key] = HYPIT_FLOW_SCHEMA_VERSION
        result[self.migration_done_key] = True
        return result

    def ensure_canvas_with_status(self) -> tuple[dict[str, Any], bool]:
        """幂等初始化：先保留旧设置备份，再执行一次旧六槽投影。"""
        with self._lock:
            current = self._load_current()
            if current and current.get(self.migration_done_key) is True:
                candidate = copy.deepcopy(current)
                metadata_changed = (
                    candidate.get("project") != self.project_id
                    or candidate.get(self.schema_version_key) != HYPIT_FLOW_SCHEMA_VERSION
                )
                candidate["project"] = self.project_id
                candidate[self.schema_version_key] = HYPIT_FLOW_SCHEMA_VERSION
                self._validate_or_http_error(candidate, 500, f"{self.module_id} 配置图校验失败")
                upgraded, changed = (upgrade_hypit_legacy_prompt_scaffold(candidate)
                                     if self.module_id == "hypit" else (candidate, False))
                if not changed:
                    if metadata_changed:
                        candidate = self._persist(candidate, increment_revision=False, touch_updated_at=False)
                    return candidate, False
                self._validate_or_http_error(upgraded, 500, f"{self.module_id} 旧占位清理校验失败")
                if self._backup_scaffold is None:
                    raise HTTPException(status_code=503, detail=f"{self.module_id} 旧占位清理缺少安全备份服务，未修改配置图")
                # 先备份完整旧图，再通过标准保存回调原子递增 revision；只在精确占位匹配时清理。
                self._backup_scaffold(copy.deepcopy(current))
                saved = self._persist(upgraded, increment_revision=True, touch_updated_at=True)
                self._validate_or_http_error(saved, 500, f"{self.module_id} 占位清理后的配置图校验失败")
                return saved, True

            legacy = self._load_legacy_settings() if self.migrate_legacy else None
            if current and (current.get("nodes") or current.get("connections")):
                # 已有图不能被旧表单覆盖，只补齐一次性迁移标记。
                canvas = copy.deepcopy(current)
            elif self.migrate_legacy and legacy is not None:
                self._backup_legacy_settings(legacy)
                canvas = self._migrate_legacy_settings(self._legacy_defaults(legacy), self.canvas_id)
                if not isinstance(canvas, dict) or canvas.get("id") != self.canvas_id:
                    raise HTTPException(status_code=500, detail="旧 Hypit 设置迁移未返回有效配置图")
                if current:
                    for key in ("created_at", "revision", "title", "icon"):
                        if current.get(key) is not None:
                            canvas[key] = current[key]
                    canvas["updated_at"] = current.get("updated_at", canvas.get("updated_at", 0))
            else:
                canvas = copy.deepcopy(current) if current else self._blank_canvas()

            canvas.update({
                "id": self.canvas_id,
                "kind": "smart",
                "project": self.project_id,
                self.schema_version_key: HYPIT_FLOW_SCHEMA_VERSION,
                self.migration_done_key: True,
            })
            canvas.setdefault("title", self.title)
            canvas.setdefault("icon", "sparkles")
            canvas.setdefault("revision", 1)
            canvas.setdefault("created_at", int(self._now_ms()))
            canvas.setdefault("updated_at", canvas["created_at"])
            canvas.setdefault("node_schema_version", 1)
            canvas.setdefault("nodes", [])
            canvas.setdefault("connections", [])
            canvas.setdefault("viewport", {"x": 0, "y": 0, "scale": 1})
            canvas.setdefault("logs", [])
            canvas.setdefault("settings", {})
            self._validate_or_http_error(canvas, 500, f"{self.module_id} 配置图初始化校验失败")
            return self._persist(canvas, increment_revision=False, touch_updated_at=False), False

    def ensure_canvas(self) -> dict[str, Any]:
        """兼容同步读取方；需要广播时由异步初始化路由使用状态返回值。"""
        return self.ensure_canvas_with_status()[0]

    async def broadcast_canvas_revision(self, canvas: Mapping[str, Any], client_id: str = "") -> None:
        result = self._broadcast_canvas_updated(
            self.canvas_id,
            int(canvas.get("updated_at") or self._now_ms()),
            max(1, int(canvas.get("revision") or 1)),
            str(client_id or ""),
        )
        if inspect.isawaitable(result):
            await result

    def _validate_or_http_error(self, canvas: Mapping[str, Any], status_code: int, message: str) -> None:
        try:
            try:
                parameters = inspect.signature(self._validate_canvas).parameters
            except (TypeError, ValueError):
                parameters = {}
            accepts_kwargs = any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values())
            kwargs = {}
            if "canvas_id" in parameters or accepts_kwargs:
                kwargs["canvas_id"] = self.canvas_id
            if "module_id" in parameters or accepts_kwargs:
                kwargs["module_id"] = self.module_id
            self._validate_canvas(canvas, **kwargs)
        except HTTPException:
            raise
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status_code, detail=f"{message}：{exc}") from exc

    async def projected_canvas(self, canvas: Mapping[str, Any] | None = None) -> dict[str, Any]:
        result = copy.deepcopy(dict(canvas if canvas is not None else self.ensure_canvas()))
        statuses = self._test_statuses(self.canvas_id, result)
        if inspect.isawaitable(statuses):
            statuses = await statuses
        result["test_statuses"] = copy.deepcopy(dict(statuses)) if isinstance(statuses, Mapping) else {}
        return result

    @staticmethod
    def _payload_dict(payload: Any) -> dict[str, Any]:
        if isinstance(payload, Mapping):
            return dict(payload)
        model_dump = getattr(payload, "model_dump", None)
        if callable(model_dump):
            return model_dump()
        dict_method = getattr(payload, "dict", None)
        if callable(dict_method):
            return dict_method()
        raise HTTPException(status_code=400, detail=f"{self.module_id} 配置图请求必须是对象")

    def prepare_update_candidate(self, current: Mapping[str, Any], payload: Any) -> dict[str, Any]:
        """在标准保存链前进行配置图专属 revision 与图结构校验。"""
        body = self._payload_dict(payload)
        expected = body.get("base_revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected <= 0:
            raise HTTPException(status_code=400, detail="base_revision 必须是大于零的整数")
        current_revision = max(1, int(current.get("revision") or 1))
        if expected != current_revision:
            raise self._revision_conflict(current)

        candidate = copy.deepcopy(dict(current))
        for key in ("title", "icon", "nodes", "connections", "viewport", "logs", "settings"):
            if key in body:
                candidate[key] = copy.deepcopy(body[key])
        if not isinstance(candidate.get("nodes"), list) or not isinstance(candidate.get("connections"), list):
            raise HTTPException(status_code=400, detail=f"{self.module_id} 配置图节点和连线必须是数组")
        if not isinstance(candidate.get("viewport"), Mapping):
            raise HTTPException(status_code=400, detail=f"{self.module_id} 配置图 viewport 格式无效")
        if not isinstance(candidate.get("logs"), list) or not isinstance(candidate.get("settings"), Mapping):
            raise HTTPException(status_code=400, detail=f"{self.module_id} 配置图日志或设置格式无效")
        candidate.update({
            "id": self.canvas_id,
            "kind": "smart",
            "project": self.project_id,
            self.schema_version_key: HYPIT_FLOW_SCHEMA_VERSION,
            self.migration_done_key: True,
        })
        self._validate_or_http_error(candidate, 400, f"{self.module_id} 配置图无效")
        return candidate

    def save_agent_canvas(
        self,
        canvas: dict[str, Any],
        *,
        increment_revision: bool = True,
        touch_updated_at: bool = True,
    ) -> dict[str, Any] | None:
        """让 Agent 继续使用共享画布，但保护配置图的修订、身份和图契约。"""
        if not is_settings_canvas(canvas, self.canvas_id):
            return self._save_canvas(
                canvas,
                increment_revision=increment_revision,
                touch_updated_at=touch_updated_at,
            )
        if not isinstance(canvas, dict):
            raise HTTPException(status_code=400, detail=f"{self.module_id} 配置图必须是对象")

        with self._lock:
            current = self._load_current()
            if current is None:
                raise HTTPException(status_code=404, detail=f"{self.module_id} 配置图不存在")
            current_revision = max(1, int(current.get("revision") or 1))
            expected_revision = canvas.get("revision")
            if (
                isinstance(expected_revision, bool)
                or not isinstance(expected_revision, int)
                or expected_revision != current_revision
            ):
                raise self._revision_conflict(current)

            candidate = copy.deepcopy(canvas)
            candidate.update({
                "id": self.canvas_id,
                "kind": "smart",
                "project": self.project_id,
                self.schema_version_key: HYPIT_FLOW_SCHEMA_VERSION,
                self.migration_done_key: True,
            })
            candidate["title"] = current.get("title", self.title)
            candidate["icon"] = current.get("icon", "sparkles")
            for field, expected_type in (
                ("nodes", list),
                ("connections", list),
                ("logs", list),
                ("settings", Mapping),
                ("viewport", Mapping),
            ):
                if not isinstance(candidate.get(field), expected_type):
                    raise HTTPException(status_code=400, detail=f"{self.module_id} 配置图 {field} 格式无效")
            self._validate_or_http_error(candidate, 400, f"{self.module_id} Agent 配置图无效")

            # 标准保存会原位更新 revision/updated_at，HeadlessCanvas 随后广播同一对象。
            canvas.clear()
            canvas.update(candidate)
            return self._save_canvas(
                canvas,
                increment_revision=increment_revision,
                touch_updated_at=touch_updated_at,
            )

    def _revision_conflict(self, current: Mapping[str, Any]) -> HTTPException:
        revision = max(1, int(current.get("revision") or 1))
        return HTTPException(status_code=409, detail={
            "message": f"{self.module_id} 配置图已被其他页面更新，请重新读取后重试。",
            "canvas": copy.deepcopy(dict(current)),
            "revision": revision,
            "updated_at": int(current.get("updated_at") or 0),
        })

    async def reset_canvas(self, payload: Any) -> dict[str, Any]:
        body = self._payload_dict(payload)
        expected = body.get("base_revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected <= 0:
            raise HTTPException(status_code=400, detail="base_revision 必须是大于零的整数")
        client_id = str(body.get("client_id") or "")
        with self._lock:
            current = self.ensure_canvas()
            current_revision = max(1, int(current.get("revision") or 1))
            if expected != current_revision:
                raise self._revision_conflict(current)
            candidate = copy.deepcopy(current)
            candidate.update({
                "nodes": [],
                "connections": [],
                "settings": {},
                "logs": [],
                "viewport": {"x": 0, "y": 0, "scale": 1},
                self.schema_version_key: HYPIT_FLOW_SCHEMA_VERSION,
                self.migration_done_key: True,
            })
            self._validate_or_http_error(candidate, 400, f"{self.module_id} 配置图无效")
            saved = self._persist(candidate, increment_revision=True, touch_updated_at=True)
        await self.broadcast_canvas_revision(saved, client_id)
        return {"id": self.canvas_id, "canvas": await self.projected_canvas(saved), "reset": True}


def create_hypit_settings_canvas_router(
    *,
    service: HypitSettingsCanvasService,
    submit_test: Callable[..., Any] | None = None,
    get_test: Callable[[str], Any] | None = None,
    base_path: str | None = None,
    include_test_routes: bool = True,
) -> APIRouter:
    """注册设置图初始化、重置和可选的 Hypit 流程测试入口。"""
    router = APIRouter()
    route_path = base_path or (
        "/api/hypit/settings-canvas" if service.module_id == "hypit"
        else "/api/studio/articles/settings-canvas"
    )

    @router.get(route_path)
    async def get_hypit_settings_canvas():
        current, scaffold_upgraded = service.ensure_canvas_with_status()
        if scaffold_upgraded:
            await service.broadcast_canvas_revision(current)
        canvas = await service.projected_canvas(current)
        return {"id": service.canvas_id, "canvas": canvas, "url": service.canvas_url}

    @router.post(f"{route_path}/reset")
    async def reset_hypit_settings_canvas(payload: dict[str, Any] = Body(...)):
        return await service.reset_canvas(payload)

    if include_test_routes:
        @router.post(f"{route_path}/test")
        async def submit_hypit_settings_canvas_test(payload: dict[str, Any] = Body(...)):
            if submit_test is None:
                raise HTTPException(status_code=503, detail=f"{service.module_id} 流程执行服务尚未接入")
            slot = str(payload.get("slot") or "").strip().lower()
            output_node_id = str(payload.get("output_node_id") or "").strip()
            operation_id = str(payload.get("client_operation_id") or payload.get("request_id") or "").strip()
            if not slot or not output_node_id or not operation_id:
                raise HTTPException(status_code=400, detail="缺少 slot、output_node_id 或 client_operation_id")
            result = submit_test(slot, output_node_id, operation_id, dict(payload), test=True)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, Mapping):
                raise HTTPException(status_code=502, detail=f"{service.module_id} 流程执行服务返回无效状态")
            return dict(result)

        @router.get(f"{route_path}/test/{{run_id}}")
        async def get_hypit_settings_canvas_test(run_id: str):
            if get_test is None:
                raise HTTPException(status_code=503, detail=f"{service.module_id} 流程状态查询尚未接入")
            result = get_test(str(run_id or "").strip())
            if inspect.isawaitable(result):
                result = await result
            if result is None:
                raise HTTPException(status_code=404, detail=f"{service.module_id} 流程任务不存在")
            if not isinstance(result, Mapping):
                raise HTTPException(status_code=502, detail=f"{service.module_id} 流程状态无效")
            return dict(result)

    return router
