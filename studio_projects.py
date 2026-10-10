"""老胡创意工作台的共用项目目录。

画布项目不在这里复制保存。它们通过主控注入的 ``canvas_adapter`` 直接
读取现有画布实体；Hypit 项目才使用 ``data/studio_projects`` 里的独立记录。
这个模块故意不依赖主控模块，也不执行外部工程代码。
"""

from __future__ import annotations

import inspect
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from canvas_agent import is_local_client
from canvas_core.json_store import DataFileError, read_json, write_json
from studio_modules import PROJECT_MODULE_IDS, RESERVED_SETTINGS_CANVAS_IDS


PROJECT_MODULES = PROJECT_MODULE_IDS
PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
PROJECT_RECORD_VERSION = 1
MAX_PROJECT_NAME_LENGTH = 120


def now_ms() -> int:
    return int(time.time() * 1000)


class StudioProjectError(RuntimeError):
    """可安全返回给 HTTP 客户端的项目目录错误。"""

    status_code = 400

    def __init__(self, detail: Any):
        super().__init__(str(detail))
        self.detail = detail


class StudioProjectNotFound(StudioProjectError):
    status_code = 404


class StudioProjectConflict(StudioProjectError):
    status_code = 409


class StudioProjectStoreError(StudioProjectError):
    status_code = 500


class ProjectCreateRequest(BaseModel):
    module: str = Field(min_length=1, max_length=24)
    name: str = Field(default="", max_length=MAX_PROJECT_NAME_LENGTH)


class ProjectPatchRequest(BaseModel):
    module: Optional[str] = Field(default=None, max_length=24)
    name: Optional[str] = Field(default=None, max_length=MAX_PROJECT_NAME_LENGTH)
    revision: Optional[int] = Field(default=None, ge=1)
    base_revision: Optional[int] = Field(default=None, ge=1)
    expected_revision: Optional[int] = Field(default=None, ge=1)


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _unwrap(item: Any) -> Any:
    if isinstance(item, Mapping):
        for key in ("project", "canvas", "item", "record"):
            nested = item.get(key)
            if isinstance(nested, Mapping):
                return nested
    return item


def _clean_module(value: Any, *, allow_none: bool = False) -> Optional[str]:
    if value is None and allow_none:
        return None
    module = str(value or "").strip().lower()
    if module not in PROJECT_MODULES:
        raise StudioProjectError("项目模块必须是 canvas、hypit、article 或 music")
    return module


def _clean_project_id(value: Any) -> str:
    project_id = str(value or "").strip()
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise StudioProjectError("项目 ID 不合法")
    return project_id


def _clean_name(value: Any) -> str:
    name = str(value or "").replace("\x00", "").strip()
    name = "".join(char for char in name if ord(char) >= 32 or char in "\n\t")
    name = re.sub(r"\s+", " ", name).strip()
    return (name or "未命名项目")[:MAX_PROJECT_NAME_LENGTH]


def _timestamp(item: Any) -> int:
    raw = _value(item, "updated_at", None)
    if raw in (None, ""):
        raw = _value(item, "created_at", 0)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _revision(item: Any) -> int:
    try:
        return max(1, int(_value(item, "revision", 1) or 1))
    except (TypeError, ValueError):
        return 1


def _public_project(
    *,
    module: str,
    project_id: str,
    name: str,
    updated_at: int,
    url: str,
    revision: int = 1,
) -> dict[str, Any]:
    # revision 不是列表展示必需字段，但让 PATCH 可以做乐观并发检查。
    return {
        "id": project_id,
        "module": module,
        "name": _clean_name(name),
        "url": url,
        "updated_at": int(updated_at or 0),
        "revision": max(1, int(revision or 1)),
    }


class StudioProjectStore:
    """共用项目存储。

    ``canvas_adapter`` 只接受显式传入的 ``list/get/create/rename/delete`` 方法。
    这样主控可以把 main 里的真源函数包装后注入，而本模块不会反向依赖 main。
    """

    def __init__(self, root: str | os.PathLike[str], canvas_adapter: Any):
        self.root = Path(root).expanduser().absolute()
        self.canvas_adapter = canvas_adapter
        self.studio_dir = self.root / "data" / "studio_projects"
        self.hypit_dir = self.root / "workflows" / "hypit"
        self.backup_dir = self.root / "backups" / "studio-projects"
        self.recycle_index = self.backup_dir / "recycle.json"
        self.lock = RLock()
        self._validate_adapter()

    def _adapter_method(self, name: str) -> Callable[..., Any]:
        adapter = self.canvas_adapter
        method = adapter.get(name) if isinstance(adapter, Mapping) else getattr(adapter, name, None)
        if not callable(method):
            raise StudioProjectStoreError(f"canvas_adapter 缺少 {name} 方法")
        return method

    def _validate_adapter(self) -> None:
        for name in ("list", "get", "create", "rename", "delete"):
            self._adapter_method(name)

    @staticmethod
    def _call(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        result = method(*args, **kwargs)
        if inspect.isawaitable(result):
            # 主控的适配器通常是同步函数。若调用方提供异步方法，在线程池中
            # 仍可安全完成一次调用，不在这里创建后台任务或执行外部代码。
            import asyncio

            return asyncio.run(result)
        return result

    @classmethod
    def _call_with_revision(
        cls,
        method: Callable[..., Any],
        *args: Any,
        expected_revision: Optional[int] = None,
    ) -> Any:
        kwargs: dict[str, Any] = {}
        if expected_revision is not None:
            try:
                parameters = inspect.signature(method).parameters
            except (TypeError, ValueError):
                parameters = {}
            for key in ("expected_revision", "base_revision", "revision"):
                parameter = parameters.get(key)
                if parameter is not None or any(
                    item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()
                ):
                    kwargs[key] = expected_revision
                    break
        return cls._call(method, *args, **kwargs)

    def _canvas_items(self) -> list[Any]:
        result = self._call(self._adapter_method("list"))
        if isinstance(result, Mapping):
            for key in ("canvases", "projects", "items"):
                if isinstance(result.get(key), list):
                    result = result[key]
                    break
        if result is None:
            return []
        if isinstance(result, (str, bytes, Mapping)):
            raise StudioProjectStoreError("canvas_adapter.list 返回格式不正确")
        try:
            return [
                item for item in result
                if _clean_project_id(_value(_unwrap(item), "id", _value(_unwrap(item), "canvas_id", "")))
                not in RESERVED_SETTINGS_CANVAS_IDS
            ]
        except TypeError as exc:
            raise StudioProjectStoreError("canvas_adapter.list 返回格式不正确") from exc

    def _canvas_item(self, project_id: str) -> Any:
        if project_id in RESERVED_SETTINGS_CANVAS_IDS:
            return None
        method = self._adapter_method("get")
        try:
            result = self._call(method, project_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                return None
            raise
        except (FileNotFoundError, KeyError):
            return None
        return _unwrap(result) if result is not None else None

    @staticmethod
    def _canvas_public(item: Any) -> dict[str, Any]:
        item = _unwrap(item)
        project_id = _clean_project_id(_value(item, "id", _value(item, "canvas_id", "")))
        name = _clean_name(_value(item, "name", _value(item, "title", "未命名画布")))
        custom_url = _value(item, "url", "")
        url = (
            str(custom_url)
            if isinstance(custom_url, str) and custom_url.startswith("/")
            else f"/static/smart-canvas.html?id={quote(project_id, safe='')}"
        )
        return _public_project(
            module="canvas",
            project_id=project_id,
            name=name,
            updated_at=_timestamp(item),
            url=url,
            revision=_revision(item),
        )

    def _hypit_record_path(self, project_id: str) -> Path:
        project_id = _clean_project_id(project_id)
        return self.studio_dir / f"{project_id}.json"

    def article_record_path(self, project_id: str) -> Path:
        return self._hypit_record_path(project_id)

    def _read_hypit_record(self, project_id: str, *, missing_ok: bool = False) -> Optional[dict[str, Any]]:
        if project_id in RESERVED_SETTINGS_CANVAS_IDS:
            if missing_ok:
                return None
            raise StudioProjectNotFound("该 ID 保留给模块设置画布")
        path = self._hypit_record_path(project_id)
        if not path.exists():
            if missing_ok:
                return None
            raise StudioProjectNotFound("项目不存在")
        try:
            raw = read_json(path)
        except DataFileError:
            # 损坏记录必须向上抛出，不能用空对象覆盖原文件。
            raise
        if not isinstance(raw, dict):
            raise DataFileError(f"项目记录 {path.name} 格式损坏，原文件已保留，请从备份恢复。")
        if raw.get("id") != project_id or raw.get("module") != "hypit":
            raise DataFileError(f"项目记录 {path.name} 与文件名不匹配，原文件已保留，请从备份恢复。")
        version = raw.get("version", 1)
        if not isinstance(version, int) or version > PROJECT_RECORD_VERSION:
            raise DataFileError(f"项目记录 {path.name} 版本不受支持，原文件已保留，请从备份恢复。")
        if not PROJECT_ID_PATTERN.fullmatch(str(raw.get("id") or "")):
            raise DataFileError(f"项目记录 {path.name} 的 ID 不合法，原文件已保留，请从备份恢复。")
        if not isinstance(raw.get("name"), str):
            raise DataFileError(f"项目记录 {path.name} 的名称不合法，原文件已保留，请从备份恢复。")
        revision = raw.get("revision", 1)
        if not isinstance(revision, int) or revision < 1:
            raise DataFileError(f"项目记录 {path.name} 的修订号不合法，原文件已保留，请从备份恢复。")
        return raw

    def _read_article_record(self, project_id: str, *, missing_ok: bool = False) -> Optional[dict[str, Any]]:
        if project_id in RESERVED_SETTINGS_CANVAS_IDS:
            if missing_ok:
                return None
            raise StudioProjectNotFound("该 ID 保留给模块设置画布")
        path = self._hypit_record_path(project_id)
        if not path.exists():
            if missing_ok:
                return None
            raise StudioProjectNotFound("文章项目不存在")
        try:
            raw = read_json(path)
        except DataFileError:
            raise
        if not isinstance(raw, dict):
            raise DataFileError(f"项目记录 {path.name} 格式损坏，原文件已保留，请从备份恢复。")
        if raw.get("id") != project_id or raw.get("module") != "article":
            raise DataFileError(f"项目记录 {path.name} 与文章模块或文件名不匹配，原文件已保留，请从备份恢复。")
        version = raw.get("version", 1)
        if not isinstance(version, int) or version > PROJECT_RECORD_VERSION:
            raise DataFileError(f"项目记录 {path.name} 版本不受支持，原文件已保留，请从备份恢复。")
        if not PROJECT_ID_PATTERN.fullmatch(str(raw.get("id") or "")):
            raise DataFileError(f"项目记录 {path.name} 的 ID 不合法，原文件已保留，请从备份恢复。")
        if not isinstance(raw.get("name"), str):
            raise DataFileError(f"项目记录 {path.name} 的名称不合法，原文件已保留，请从备份恢复。")
        revision = raw.get("revision", 1)
        if not isinstance(revision, int) or revision < 1:
            raise DataFileError(f"项目记录 {path.name} 的修订号不合法，原文件已保留，请从备份恢复。")
        article = raw.get("article")
        if not isinstance(article, dict):
            raise DataFileError(f"文章记录 {path.name} 内容损坏，原文件已保留，请从备份恢复。")
        return raw

    def _read_music_record(self, project_id: str, *, missing_ok: bool = False) -> Optional[dict[str, Any]]:
        if project_id in RESERVED_SETTINGS_CANVAS_IDS:
            if missing_ok:
                return None
            raise StudioProjectNotFound("该 ID 保留给模块设置画布")
        path = self._hypit_record_path(project_id)
        if not path.exists():
            if missing_ok:
                return None
            raise StudioProjectNotFound("音乐项目不存在")
        raw = read_json(path)
        if not isinstance(raw, dict):
            raise DataFileError(f"项目记录 {path.name} 格式损坏，原文件已保留，请从备份恢复。")
        if raw.get("id") != project_id or raw.get("module") != "music":
            raise DataFileError(f"项目记录 {path.name} 与音乐模块或文件名不匹配，原文件已保留，请从备份恢复。")
        version = raw.get("version", 1)
        revision = raw.get("revision", 1)
        if not isinstance(version, int) or version > PROJECT_RECORD_VERSION:
            raise DataFileError(f"项目记录 {path.name} 版本不受支持，原文件已保留，请从备份恢复。")
        if not PROJECT_ID_PATTERN.fullmatch(str(raw.get("id") or "")) or not isinstance(raw.get("name"), str):
            raise DataFileError(f"项目记录 {path.name} 的身份或名称不合法，原文件已保留，请从备份恢复。")
        if not isinstance(revision, int) or revision < 1:
            raise DataFileError(f"项目记录 {path.name} 的修订号不合法，原文件已保留，请从备份恢复。")
        if not isinstance(raw.get("music"), dict):
            raise DataFileError(f"音乐记录 {path.name} 内容损坏，原文件已保留，请从备份恢复。")
        return raw

    def read_article_record(self, project_id: str) -> dict[str, Any]:
        """在共享项目锁内读取文章主记录，损坏数据不会被空文章覆盖。"""
        project_id = _clean_project_id(project_id)
        with self.lock:
            record = self._read_article_record(project_id)
            assert record is not None
            return record

    def write_article_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """原子替换文章主记录；调用方须已持有本实例的共享项目锁。"""
        project_id = _clean_project_id(record.get("id"))
        if project_id in RESERVED_SETTINGS_CANVAS_IDS:
            raise StudioProjectStoreError("保留设置画布 ID 不能作为文章项目 ID")
        value = dict(record)
        if value.get("module") != "article":
            raise StudioProjectStoreError("文章记录模块不匹配")
        write_json(self._hypit_record_path(project_id), value)
        return value

    def read_music_record(self, project_id: str) -> dict[str, Any]:
        project_id = _clean_project_id(project_id)
        with self.lock:
            record = self._read_music_record(project_id)
            assert record is not None
            return record

    def write_music_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        project_id = _clean_project_id(record.get("id"))
        if project_id in RESERVED_SETTINGS_CANVAS_IDS:
            raise StudioProjectStoreError("保留设置画布 ID 不能作为音乐项目 ID")
        value = dict(record)
        if value.get("module") != "music":
            raise StudioProjectStoreError("音乐记录模块不匹配")
        if not isinstance(value.get("music"), Mapping):
            raise StudioProjectStoreError("音乐项目内容格式无效")
        write_json(self._hypit_record_path(project_id), value)
        return value

    @staticmethod
    def _hypit_public(record: Mapping[str, Any]) -> dict[str, Any]:
        project_id = _clean_project_id(record.get("id"))
        return _public_project(
            module="hypit",
            project_id=project_id,
            name=record.get("name", "未命名项目"),
            updated_at=_timestamp(record),
            url=f"/static/hypit.html?id={quote(project_id, safe='')}",
            revision=_revision(record),
        )

    @staticmethod
    def _article_public(record: Mapping[str, Any]) -> dict[str, Any]:
        project_id = _clean_project_id(record.get("id"))
        return _public_project(
            module="article",
            project_id=project_id,
            name=record.get("name", "未命名文章"),
            updated_at=_timestamp(record),
            url=f"/static/article.html?id={quote(project_id, safe='')}",
            revision=_revision(record),
        )

    @staticmethod
    def _music_public(record: Mapping[str, Any]) -> dict[str, Any]:
        project_id = _clean_project_id(record.get("id"))
        return _public_project(
            module="music",
            project_id=project_id,
            name=record.get("name", "未命名音乐"),
            updated_at=_timestamp(record),
            url=f"/static/music.html?id={quote(project_id, safe='')}",
            revision=_revision(record),
        )

    @staticmethod
    def _check_revision(current: Mapping[str, Any], expected_revision: Optional[int]) -> None:
        if expected_revision is None:
            return
        actual = _revision(current)
        if int(expected_revision) != actual:
            project = dict(current)
            project["revision"] = actual
            raise StudioProjectConflict({
                "message": "项目已被其他页面更新，请刷新后重试。",
                "project": project,
                "revision": actual,
            })

    def _load_recycle_index(self) -> dict[str, Any]:
        if not self.recycle_index.exists():
            return {"version": PROJECT_RECORD_VERSION, "items": []}
        raw = read_json(self.recycle_index)
        if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
            raise DataFileError("项目回收索引格式损坏，原文件已保留，请从备份恢复。")
        version = raw.get("version", 1)
        if not isinstance(version, int) or version > PROJECT_RECORD_VERSION:
            raise DataFileError("项目回收索引版本不受支持，原文件已保留，请从备份恢复。")
        raw["version"] = PROJECT_RECORD_VERSION
        return raw

    def _append_recycle_item(self, record: Mapping[str, Any], backup_path: Path) -> None:
        index = self._load_recycle_index()
        items = list(index.get("items") or [])
        items.append({
            "id": str(record.get("id")),
            "module": str(record.get("module") or "hypit"),
            "name": str(record.get("name") or "未命名项目"),
            "deleted_at": now_ms(),
            "backup_path": str(backup_path.relative_to(self.root)).replace(os.sep, "/"),
        })
        index["items"] = items
        index["updated_at"] = now_ms()
        write_json(self.recycle_index, index)

    def resolve_module(self, project_id: str, module: Optional[str] = None) -> str:
        project_id = _clean_project_id(project_id)
        normalized = _clean_module(module, allow_none=True)
        if normalized:
            return normalized
        canvas_item = self._canvas_item(project_id)
        hypit_exists = self._hypit_record_path(project_id).exists()
        record_module = self._record_module(self._hypit_record_path(project_id)) if hypit_exists else ""
        article_exists = hypit_exists and record_module == "article"
        music_exists = hypit_exists and record_module == "music"
        hypit_exists = hypit_exists and record_module == "hypit"
        matches = [name for name, exists in (("canvas", canvas_item is not None), ("hypit", hypit_exists),
                                               ("article", article_exists), ("music", music_exists)) if exists]
        if len(matches) > 1:
            raise StudioProjectConflict("项目 ID 在多个模块中都存在，请附带 module 参数")
        if matches:
            return matches[0]
        raise StudioProjectNotFound("项目不存在")

    @staticmethod
    def _record_module(path: Path) -> str:
        try:
            raw = read_json(path)
        except DataFileError:
            raise
        if not isinstance(raw, dict):
            raise DataFileError(f"项目记录 {path.name} 格式损坏，原文件已保留，请从备份恢复。")
        return str(raw.get("module") or "")

    def list(self, module: Optional[str] = None) -> list[dict[str, Any]]:
        normalized = _clean_module(module, allow_none=True)
        with self.lock:
            output: list[dict[str, Any]] = []
            if normalized in (None, "canvas"):
                for item in self._canvas_items():
                    output.append(self._canvas_public(item))
            if normalized in (None, "hypit", "article", "music"):
                if self.studio_dir.exists():
                    for path in sorted(self.studio_dir.glob("*.json")):
                        record = self._record_module(path)
                        if record == "hypit" and normalized in (None, "hypit"):
                            output.append(self._hypit_public(self._read_hypit_record(path.stem) or {}))
                        elif record == "article" and normalized in (None, "article"):
                            output.append(self._article_public(self._read_article_record(path.stem) or {}))
                        elif record == "music" and normalized in (None, "music"):
                            output.append(self._music_public(self._read_music_record(path.stem) or {}))
                        elif record not in {"hypit", "article", "music"}:
                            raise DataFileError(f"项目记录 {path.name} 模块不受支持，原文件已保留。")
            return sorted(output, key=lambda item: (-int(item.get("updated_at") or 0), item["name"], item["id"]))

    def get(self, project_id: str, module: Optional[str] = None) -> dict[str, Any]:
        project_id = _clean_project_id(project_id)
        normalized = self.resolve_module(project_id, module)
        with self.lock:
            if normalized == "canvas":
                item = self._canvas_item(project_id)
                if item is None:
                    raise StudioProjectNotFound("项目不存在")
                return self._canvas_public(item)
            if normalized == "hypit":
                record = self._read_hypit_record(project_id)
                return self._hypit_public(record or {})
            if normalized == "article":
                article = self._read_article_record(project_id)
                return self._article_public(article or {})
            music = self._read_music_record(project_id)
            return self._music_public(music or {})

    def create(self, module: str, name: str) -> dict[str, Any]:
        normalized = _clean_module(module)
        clean_name = _clean_name(name)
        with self.lock:
            if normalized == "canvas":
                created = _unwrap(self._call(self._adapter_method("create"), clean_name))
                if created is None:
                    raise StudioProjectStoreError("canvas_adapter.create 未返回画布")
                return self._canvas_public(created)

            self.studio_dir.mkdir(parents=True, exist_ok=True)
            project_id = uuid.uuid4().hex
            record_path = self._hypit_record_path(project_id)
            timestamp = now_ms()
            if normalized == "hypit":
                self.hypit_dir.mkdir(parents=True, exist_ok=True)
                workflow_path = self.hypit_dir / project_id
            else:
                workflow_path = None
            record = {
                "version": PROJECT_RECORD_VERSION,
                "id": project_id,
                "module": normalized,
                "name": clean_name,
                "created_at": timestamp,
                "updated_at": timestamp,
                "revision": 1,
            }
            if normalized == "article":
                record["article"] = {
                    "title": "",
                    "source_markdown": "",
                    "source_sha256": "",
                    "selected_theme_id": "moyu-green",
                    "variants": {},
                    "title_variants": {},
                    "selected_title_variant_id": None,
                    "cover_variants": [],
                    "selected_cover_variant_id": None,
                    "media_refs": [],
                }
            if normalized == "music":
                record["music"] = {
                    "title": "",
                    "lyrics": "",
                    "style_prompt": "",
                    "notes": "",
                    "cover_prompt": "",
                    "title_candidates": {},
                    "selected_title_candidate_id": None,
                    "score_refs": [],
                    "reference_audio_refs": [],
                    "source_versions": [],
                    "cover_variants": [],
                    "audio_variants": [],
                    "selected_cover_variant_id": None,
                    "selected_audio_variant_id": None,
                }
            if workflow_path is not None:
                workflow_path.mkdir(parents=True, exist_ok=False)
            try:
                write_json(record_path, record)
            except Exception:
                # 只清理本次刚创建的空工程目录，不触碰 assets 或既有工程。
                if workflow_path is not None:
                    try:
                        workflow_path.rmdir()
                    except OSError:
                        pass
                raise
            return self._hypit_public(record) if normalized == "hypit" else (
                self._article_public(record) if normalized == "article" else self._music_public(record)
            )

    def rename(
        self,
        project_id: str,
        name: str,
        module: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> dict[str, Any]:
        project_id = _clean_project_id(project_id)
        clean_name = _clean_name(name)
        normalized = self.resolve_module(project_id, module)
        with self.lock:
            if normalized == "canvas":
                current = self._canvas_item(project_id)
                if current is None:
                    raise StudioProjectNotFound("项目不存在")
                self._check_revision(current, expected_revision)
                self._call_with_revision(
                    self._adapter_method("rename"),
                    project_id,
                    clean_name,
                    expected_revision=expected_revision,
                )
                updated = self._canvas_item(project_id)
                if updated is None:
                    raise StudioProjectStoreError("画布重命名后无法重新读取画布")
                return self._canvas_public(updated)

            record = (self._read_hypit_record(project_id) if normalized == "hypit" else
                      self._read_article_record(project_id) if normalized == "article" else
                      self._read_music_record(project_id))
            self._check_revision(record or {}, expected_revision)
            assert record is not None
            record["name"] = clean_name
            record["updated_at"] = now_ms()
            record["revision"] = _revision(record) + 1
            write_json(self._hypit_record_path(project_id), record)
            return (self._hypit_public(record) if normalized == "hypit" else
                    self._article_public(record) if normalized == "article" else self._music_public(record))

    def delete(
        self,
        project_id: str,
        module: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> dict[str, Any]:
        project_id = _clean_project_id(project_id)
        normalized = self.resolve_module(project_id, module)
        with self.lock:
            if normalized == "canvas":
                current = self._canvas_item(project_id)
                if current is None:
                    raise StudioProjectNotFound("项目不存在")
                self._check_revision(current, expected_revision)
                self._call_with_revision(
                    self._adapter_method("delete"),
                    project_id,
                    expected_revision=expected_revision,
                )
                return self._canvas_public(current)

            record = (self._read_hypit_record(project_id) if normalized == "hypit" else
                      self._read_article_record(project_id) if normalized == "article" else
                      self._read_music_record(project_id))
            self._check_revision(record or {}, expected_revision)
            assert record is not None
            # 先读回收索引，索引损坏时在任何移动动作前拒绝操作。
            self._load_recycle_index()
            stamp = f"{now_ms()}-{uuid.uuid4().hex[:8]}"
            archive = self.backup_dir / normalized / f"{project_id}-{stamp}"
            archive.mkdir(parents=True, exist_ok=False)
            workflow_path = self.hypit_dir / project_id if normalized == "hypit" else None
            if workflow_path is not None and workflow_path.exists():
                shutil.move(str(workflow_path), str(archive / "workflow"))
            # 移动记录而非 unlink，方便从备份恢复，也避免删除用户资产。
            shutil.move(str(self._hypit_record_path(project_id)), str(archive / "project.json"))
            self._append_recycle_item(record, archive)
            return (self._hypit_public(record) if normalized == "hypit" else
                    self._article_public(record) if normalized == "article" else self._music_public(record))


def _revision_from_request(
    payload: Optional[ProjectPatchRequest] = None,
    *,
    query_revision: Optional[int] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> Optional[int]:
    values = []
    if payload is not None:
        values.extend([payload.revision, payload.base_revision, payload.expected_revision])
    values.append(query_revision)
    if headers:
        for key in ("if-match", "x-project-revision"):
            raw = headers.get(key)
            if raw:
                raw = raw.strip().strip('"')
                if raw.startswith("W/"):
                    raw = raw[2:].strip().strip('"')
                try:
                    values.append(int(raw))
                except ValueError:
                    raise StudioProjectError("项目修订号不合法")
    chosen = [int(value) for value in values if value is not None]
    if not chosen:
        return None
    if any(item != chosen[0] for item in chosen[1:]):
        raise StudioProjectError("请求包含互相冲突的项目修订号")
    return chosen[0]


async def _guard_local_write(request: Request) -> None:
    host = request.client.host if request.client else ""
    if not await run_in_threadpool(is_local_client, host):
        raise HTTPException(status_code=403, detail="项目写入只能从运行服务的本机发起")
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(status_code=403, detail="不允许跨站写入项目")


def _raise_store_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, StudioProjectError):
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    if isinstance(exc, DataFileError):
        raise HTTPException(status_code=500, detail=str(exc))
    raise exc


def create_studio_projects_router(
    root: str | os.PathLike[str],
    canvas_adapter: Any,
    *,
    store: Optional[StudioProjectStore] = None,
) -> APIRouter:
    """创建共用项目 API 路由。

    主控应在装配阶段传入画布适配器，例如把 ``list_canvases``、
    ``load_canvas``、``new_canvas`` 等真源函数包装成五个显式方法；本函数不会
    也不会创建或运行 Hypit 代码。
    """

    store = store or StudioProjectStore(root, canvas_adapter)
    router = APIRouter(prefix="/api/studio", tags=["Studio Projects"])

    @router.get("/projects")
    async def list_projects(module: Optional[str] = None):
        try:
            normalized = _clean_module(module, allow_none=True)
            projects = await run_in_threadpool(store.list, normalized)
            return {"projects": projects, "module": normalized or "all"}
        except Exception as exc:
            _raise_store_error(exc)

    @router.post("/projects", dependencies=[Depends(_guard_local_write)])
    async def create_project(payload: ProjectCreateRequest):
        try:
            project = await run_in_threadpool(store.create, payload.module, payload.name)
            return {"project": project}
        except Exception as exc:
            _raise_store_error(exc)

    @router.get("/projects/{project_id}")
    async def get_project(project_id: str, module: Optional[str] = None):
        try:
            project = await run_in_threadpool(store.get, project_id, module)
            return {"project": project}
        except Exception as exc:
            _raise_store_error(exc)

    @router.patch("/projects/{project_id}", dependencies=[Depends(_guard_local_write)])
    async def rename_project(
        project_id: str,
        payload: ProjectPatchRequest,
        module: Optional[str] = None,
        revision: Optional[int] = None,
        request: Request = None,
    ):
        try:
            if payload.name is None:
                raise StudioProjectError("重命名需要提供 name")
            selected_module = module or payload.module
            expected = _revision_from_request(
                payload,
                query_revision=revision,
                headers=request.headers if request else None,
            )
            project = await run_in_threadpool(
                store.rename,
                project_id,
                payload.name,
                selected_module,
                expected,
            )
            return {"project": project}
        except Exception as exc:
            _raise_store_error(exc)

    @router.delete("/projects/{project_id}", dependencies=[Depends(_guard_local_write)])
    async def delete_project(
        project_id: str,
        module: Optional[str] = None,
        revision: Optional[int] = None,
        request: Request = None,
    ):
        try:
            expected = _revision_from_request(query_revision=revision, headers=request.headers if request else None)
            project = await run_in_threadpool(store.delete, project_id, module, expected)
            return {"ok": True, "project": project,
                    "recycled": project.get("module") in {"hypit", "article", "music"}}
        except Exception as exc:
            _raise_store_error(exc)

    return router


__all__ = [
    "PROJECT_MODULES",
    "StudioProjectStore",
    "create_studio_projects_router",
]
