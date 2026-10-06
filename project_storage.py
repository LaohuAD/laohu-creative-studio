from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import threading
import time
import urllib.parse
import uuid
import zipfile
from pathlib import Path
from typing import Any, Iterable
from canvas_core.json_store import read_json, write_json, DataFileError


SCHEMA_VERSION = 2
MATERIAL_SCOPES = {"asset", "temporary"}
MEDIA_EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif", ".svg"},
    "video": {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv", ".flv"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"},
    "text": {".txt", ".md", ".markdown", ".html", ".json", ".csv", ".yaml", ".yml", ".log"},
}
RUN_STATUS_TRANSITIONS = {
    "validated": {"queued", "submitted", "failed", "cancelled"},
    "queued": {"submitted", "failed", "cancelling", "cancelled", "recoverable"},
    "submitted": {"processing", "succeeded", "partially_succeeded", "failed", "cancelling", "cancelled", "recoverable"},
    "processing": {"succeeded", "partially_succeeded", "failed", "cancelling", "cancelled", "recoverable"},
    "recoverable": {"submitted", "processing", "failed", "cancelling", "cancelled"},
    "cancelling": {"cancelled", "failed", "recoverable"},
    "partially_succeeded": {"succeeded", "failed"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}
SENSITIVE_SNAPSHOT_KEYS = {
    "api_key", "apikey", "authorization", "cookie", "secret", "token",
    "access_token", "refresh_token", "password", "signature", "signed_url",
}


class StorageError(RuntimeError):
    pass


def now_ms() -> int:
    return int(time.time() * 1000)


def media_kind(name: str = "", content_type: str = "") -> str:
    extension = Path(str(name or "")).suffix.lower()
    for kind, extensions in MEDIA_EXTENSIONS.items():
        if extension in extensions:
            return kind
    mime = str(content_type or "").lower()
    for kind in ("image", "video", "audio", "text"):
        if mime.startswith(f"{kind}/"):
            return kind
    return "file"


def safe_name(value: str, fallback: str = "文件") -> str:
    name = Path(str(value or fallback).replace("\\", "/")).name.strip()
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" .")
    name = name or "文件"
    # Windows 设备名即使带扩展名仍不可作为文件名；两端使用相同规范。
    if re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", name.split(".")[0].rstrip(), re.I):
        name = "_" + name
    if len(name.encode("utf-8")) > 180:
        suffix = Path(name).suffix
        if len(suffix.encode("utf-8")) > 20:
            suffix = ""
        digest = "_" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
        budget = 180 - len((digest + suffix).encode("utf-8"))
        name = name.encode("utf-8")[:budget].decode("utf-8", errors="ignore").rstrip(" .") + digest + suffix
    return name


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ProjectStorage:
    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser().absolute()
        self.data_dir = self.root / "data"
        self.assets_dir = self.root / "assets"
        self.materials_dir = self.assets_dir / "input"
        self.results_dir = self.assets_dir / "output"
        self.workflows_dir = self.root / "workflows"
        self.canvas_workflows_dir = self.workflows_dir / "canvas"
        self.previews_dir = self.root / "cache" / "previews"
        self.backups_dir = self.root / "backups"
        self.config_dir = self.data_dir / "settings"
        self.indexes_dir = self.data_dir / "indexes"
        self.material_index_path = self.indexes_dir / "materials.json"
        self.result_index_path = self.indexes_dir / "results.json"
        self.run_index_path = self.indexes_dir / "runs.json"
        self.canvas_task_index_path = self.indexes_dir / "canvas_tasks.json"
        self.manifest_path = self.data_dir / "storage_manifest.json"
        self._lock = threading.RLock()

    def layout(self) -> dict[str, Path]:
        return {
            "data": self.data_dir,
            "assets": self.assets_dir,
            "materials": self.materials_dir,
            "results": self.results_dir,
            "workflows": self.workflows_dir,
            "canvas_workflows": self.canvas_workflows_dir,
            "previews": self.previews_dir,
            "backups": self.backups_dir,
            "config": self.config_dir,
            "indexes": self.indexes_dir,
        }

    def ensure_layout(self) -> None:
        for path in self.layout().values():
            path.mkdir(parents=True, exist_ok=True)
        for scope in ("asset", "temporary"):
            for kind in ("image", "video", "audio", "text", "file"):
                (self.materials_dir / scope / kind).mkdir(parents=True, exist_ok=True)
        for kind in ("image", "video", "audio", "text", "file"):
            (self.results_dir / kind).mkdir(parents=True, exist_ok=True)
        if not self.material_index_path.exists():
            self._write_json(self.material_index_path, {"version": SCHEMA_VERSION, "items": []})
        if not self.result_index_path.exists():
            self._write_json(self.result_index_path, {"version": SCHEMA_VERSION, "items": []})
        if not self.run_index_path.exists():
            self._write_json(self.run_index_path, {"version": SCHEMA_VERSION, "items": []})
        if not self.canvas_task_index_path.exists():
            self._write_json(self.canvas_task_index_path, {"version": SCHEMA_VERSION, "items": []})
        if not self.manifest_path.exists():
            self._write_json(self.manifest_path, {
                "version": SCHEMA_VERSION,
                "created_at": now_ms(),
                "updated_at": now_ms(),
                "legacy_urls": {},
            })

    def _read_json(self, path: Path, fallback: Any) -> Any:
        try:
            return read_json(path, default=fallback)
        except DataFileError as exc:
            raise StorageError(str(exc)) from exc

    def _write_json(self, path: Path, value: Any) -> None:
        try:
            write_json(path, value)
        except DataFileError as exc:
            raise StorageError(str(exc)) from exc

    def _load_index(self, path: Path) -> dict[str, Any]:
        value = self._read_json(path, {"version": SCHEMA_VERSION, "items": []})
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            raise StorageError(f"索引 {path.name} 格式损坏，已阻止写入；请从备份恢复。")
        version = value.get("version", 1)
        if not isinstance(version, int) or version > SCHEMA_VERSION:
            raise StorageError(f"索引 {path.name} 的版本不受支持，请使用相应新版程序，不能覆盖现有数据。")
        value["version"] = SCHEMA_VERSION
        return value

    def _save_index(self, path: Path, value: dict[str, Any]) -> None:
        value["version"] = SCHEMA_VERSION
        value["updated_at"] = now_ms()
        self._write_json(path, value)

    @staticmethod
    def _snapshot_key(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")

    @classmethod
    def _sanitize_snapshot(cls, value: Any) -> Any:
        if isinstance(value, dict):
            cleaned = {}
            for key, item in value.items():
                normalized = cls._snapshot_key(key)
                if normalized in SENSITIVE_SNAPSHOT_KEYS or normalized.endswith("_api_key"):
                    continue
                cleaned[str(key)] = cls._sanitize_snapshot(item)
            return cleaned
        if isinstance(value, list):
            return [cls._sanitize_snapshot(item) for item in value]
        if isinstance(value, tuple):
            return [cls._sanitize_snapshot(item) for item in value]
        if isinstance(value, str) and value.lower().startswith(("bearer ", "basic ")):
            return "[redacted]"
        return value

    @classmethod
    def _request_digest(cls, standard_request: dict[str, Any], platform_request: dict[str, Any]) -> str:
        snapshot = {
            "standard_request": cls._sanitize_snapshot(standard_request or {}),
            "platform_request": cls._sanitize_snapshot(platform_request or {}),
        }
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def list_runs(self, canvas_id: str = "", node_id: str = "") -> list[dict[str, Any]]:
        index = self._load_index(self.run_index_path)
        items = []
        for raw in index["items"]:
            if canvas_id and raw.get("canvas_id") != canvas_id:
                continue
            if node_id and raw.get("node_id") != node_id:
                continue
            items.append(dict(raw))
        return sorted(items, key=lambda item: int(item.get("created_at") or 0), reverse=True)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        index = self._load_index(self.run_index_path)
        item = next((entry for entry in index["items"] if entry.get("run_id") == run_id), None)
        return dict(item) if item else None

    def prepare_run(
        self,
        canvas_id: str,
        node_id: str,
        client_operation_id: str,
        standard_request: dict[str, Any],
        platform_request: dict[str, Any],
        capability_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        canvas_id = str(canvas_id or "").strip()
        node_id = str(node_id or "").strip()
        client_operation_id = str(client_operation_id or "").strip()
        if not canvas_id or not node_id or not client_operation_id:
            raise StorageError("运行记录缺少画布、节点或操作标识")
        clean_standard = self._sanitize_snapshot(standard_request or {})
        clean_platform = self._sanitize_snapshot(platform_request or {})
        clean_capability = self._sanitize_snapshot(capability_snapshot or {})
        request_digest = self._request_digest(clean_standard, clean_platform)
        idempotency_source = f"{canvas_id}\n{node_id}\n{client_operation_id}\n{request_digest}"
        idempotency_key = hashlib.sha256(idempotency_source.encode("utf-8")).hexdigest()
        with self._lock:
            index = self._load_index(self.run_index_path)
            existing = next((entry for entry in index["items"] if (
                entry.get("canvas_id") == canvas_id
                and entry.get("node_id") == node_id
                and entry.get("client_operation_id") == client_operation_id
            )), None)
            if existing:
                if existing.get("request_digest") != request_digest:
                    raise StorageError("同一次运行操作的输入或参数已经变化，请创建新的运行操作")
                return dict(existing)
            timestamp = now_ms()
            attempt = {
                "attempt_id": f"attempt_{uuid.uuid4().hex[:24]}",
                "idempotency_key": idempotency_key,
                "status": "validated",
                "provider_id": str(clean_standard.get("provider_id") or ""),
                "model_id": str(clean_standard.get("model_id") or ""),
                "provider_task_id": "",
                "submitted_at": 0,
                "last_polled_at": 0,
                "result_ids": [],
                "error": "",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            item = {
                "run_id": f"run_{uuid.uuid4().hex[:24]}",
                "canvas_id": canvas_id,
                "node_id": node_id,
                "client_operation_id": client_operation_id,
                "request_digest": request_digest,
                "standard_request": clean_standard,
                "platform_request": clean_platform,
                "capability_snapshot": clean_capability,
                "attempts": [attempt],
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            index["items"].append(item)
            self._save_index(self.run_index_path, index)
            return dict(item)

    def update_run_status(
        self,
        run_id: str,
        status: str,
        provider_task_id: str = "",
        error: str = "",
        last_polled_at: int = 0,
    ) -> dict[str, Any]:
        status = str(status or "").strip()
        with self._lock:
            index = self._load_index(self.run_index_path)
            item = next((entry for entry in index["items"] if entry.get("run_id") == run_id), None)
            if not item or not item.get("attempts"):
                raise StorageError("运行记录不存在")
            attempt = item["attempts"][-1]
            current = str(attempt.get("status") or "validated")
            if status != current and status not in RUN_STATUS_TRANSITIONS.get(current, set()):
                raise StorageError(f"不允许从 {current} 变更为 {status}")
            timestamp = now_ms()
            attempt["status"] = status
            if provider_task_id:
                attempt["provider_task_id"] = str(provider_task_id)
            if status == "submitted" and not int(attempt.get("submitted_at") or 0):
                attempt["submitted_at"] = timestamp
            if last_polled_at:
                attempt["last_polled_at"] = int(last_polled_at)
            if error:
                attempt["error"] = str(error)[:4000]
            attempt["updated_at"] = timestamp
            item["updated_at"] = timestamp
            self._save_index(self.run_index_path, index)
            return dict(item)

    def append_run_results(self, run_id: str, result_ids: Iterable[str]) -> dict[str, Any]:
        with self._lock:
            index = self._load_index(self.run_index_path)
            item = next((entry for entry in index["items"] if entry.get("run_id") == run_id), None)
            if not item or not item.get("attempts"):
                raise StorageError("运行记录不存在")
            attempt = item["attempts"][-1]
            merged = list(dict.fromkeys([
                *(str(value) for value in attempt.get("result_ids") or [] if str(value)),
                *(str(value) for value in result_ids if str(value)),
            ]))
            timestamp = now_ms()
            attempt["result_ids"] = merged
            if (item.get("standard_request") or {}).get("node_type") == "music_generation" or (item.get("capability_snapshot") or {}).get("node_type") == "music_generation":
                for result_id in merged:
                    result = self.get_result(result_id)
                    if result and result.get("kind") == "audio" and result.get("media_category") != "music":
                        self.update_result_metadata(result_id, media_category="music")
            attempt["updated_at"] = timestamp
            item["updated_at"] = timestamp
            self._save_index(self.run_index_path, index)
            return dict(item)

    def create_canvas_task(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = str((task or {}).get("id") or "").strip()
        if not task_id:
            raise StorageError("画布任务缺少 ID")
        timestamp = now_ms()
        value = self._sanitize_snapshot(dict(task or {}))
        value["id"] = task_id
        value.setdefault("status", "queued")
        value.setdefault("created_at", timestamp)
        value["updated_at"] = timestamp
        with self._lock:
            index = self._load_index(self.canvas_task_index_path)
            existing = next((item for item in index["items"] if item.get("id") == task_id), None)
            if existing:
                return dict(existing)
            index["items"].append(value)
            self._save_index(self.canvas_task_index_path, index)
            return dict(value)

    def get_canvas_task(self, task_id: str) -> dict[str, Any] | None:
        task_id = str(task_id or "").strip()
        if not task_id:
            return None
        with self._lock:
            index = self._load_index(self.canvas_task_index_path)
            item = next((entry for entry in index["items"] if entry.get("id") == task_id), None)
            return dict(item) if item else None

    def update_canvas_task(self, task_id: str, **changes: Any) -> dict[str, Any]:
        task_id = str(task_id or "").strip()
        if not task_id:
            raise StorageError("画布任务缺少 ID")
        allowed = {
            "status", "result", "error", "status_code", "provider_id", "model",
            "upstream_task_id", "submit_id", "kind", "queue_info", "message",
        }
        with self._lock:
            index = self._load_index(self.canvas_task_index_path)
            item = next((entry for entry in index["items"] if entry.get("id") == task_id), None)
            if not item:
                raise StorageError("画布任务不存在")
            for key, value in changes.items():
                if key in allowed:
                    item[key] = self._sanitize_snapshot(value)
            item["updated_at"] = now_ms()
            self._save_index(self.canvas_task_index_path, index)
            return dict(item)

    def recover_interrupted_canvas_tasks(self) -> list[dict[str, Any]]:
        recovered = []
        with self._lock:
            index = self._load_index(self.canvas_task_index_path)
            for item in index["items"]:
                if str(item.get("status") or "") not in {"queued", "running"}:
                    continue
                item["status"] = "recoverable"
                item["error"] = (
                    "服务重启时任务尚未完成。为避免重复提交，系统没有自动重新调用；"
                    "如果记录了上游任务 ID，请使用原任务查询入口继续恢复。"
                )
                item["updated_at"] = now_ms()
                recovered.append(dict(item))
            if recovered:
                self._save_index(self.canvas_task_index_path, index)
        return recovered

    def _asset_relative(self, path: Path) -> str:
        relative = os.path.relpath(path.absolute(), self.assets_dir.absolute())
        if relative == ".." or relative.startswith(f"..{os.sep}"):
            raise StorageError("资源路径超出 assets 目录")
        return Path(relative).as_posix()

    def _asset_path(self, relative: str) -> Path:
        candidate = (self.assets_dir / str(relative or "")).absolute()
        try:
            common = os.path.commonpath([self.assets_dir.absolute(), candidate])
        except ValueError as exc:
            raise StorageError("资源路径超出 assets 目录") from exc
        if common != str(self.assets_dir.absolute()):
            raise StorageError("资源路径超出 assets 目录")
        return candidate

    def _readable_target(self, directory: Path, filename: str, digest: str) -> Path:
        name = safe_name(filename)
        candidate = directory / name
        if not candidate.exists() or (candidate.is_file() and sha256_file(candidate) == digest):
            return candidate
        stem = Path(name).stem or "文件"
        extension = Path(name).suffix
        candidate = directory / f"{stem}-{digest[:8]}{extension}"
        if not candidate.exists() or (candidate.is_file() and sha256_file(candidate) == digest):
            return candidate
        index = 2
        while True:
            candidate = directory / f"{stem}-{digest[:8]}-{index}{extension}"
            if not candidate.exists() or (candidate.is_file() and sha256_file(candidate) == digest):
                return candidate
            index += 1

    def _material_target(self, scope: str, kind: str, filename: str, digest: str) -> Path:
        directory = self.materials_dir / scope / kind
        directory.mkdir(parents=True, exist_ok=True)
        return self._readable_target(directory, filename, digest)

    def _same_asset_path(self, left: str, right: str) -> bool:
        if not left or not right:
            return False
        try:
            return self._asset_path(left).resolve() == self._asset_path(right).resolve()
        except (OSError, StorageError):
            return False

    def _sync_external_results_for_material(self, item: dict[str, Any]) -> None:
        """Keep result aliases pointed at the current path of their source material."""
        material_id = str(item.get("id") or "")
        relative = str(item.get("path") or "")
        if not material_id or not relative:
            return
        target = self._asset_path(relative)
        if not target.is_file():
            return
        material_digest = str(item.get("sha256") or "")
        results = self._load_index(self.result_index_path)
        changed = False
        for result in results["items"]:
            origin = result.get("origin")
            if not isinstance(origin, dict) or origin.get("kind") != "external_cli":
                continue
            if origin.get("source_material_id") != material_id:
                continue
            if str(result.get("sha256") or "") != material_digest:
                continue
            if result.get("path") != relative or result.get("size") != target.stat().st_size:
                result["path"] = relative
                result["size"] = target.stat().st_size
                result["updated_at"] = now_ms()
                changed = True
        if changed:
            self._save_index(self.result_index_path, results)

    def _result_references_material(self, result: dict[str, Any], material: dict[str, Any]) -> bool:
        origin = result.get("origin")
        if isinstance(origin, dict) and origin.get("source_material_id") == material.get("id"):
            return True
        return self._same_asset_path(str(result.get("path") or ""), str(material.get("path") or ""))

    def _material_has_result_reference(
        self,
        material: dict[str, Any],
        result_items: list[dict[str, Any]] | None = None,
    ) -> bool:
        if result_items is None:
            result_items = self._load_index(self.result_index_path)["items"]
        return any(self._result_references_material(result, material) for result in result_items)

    def _path_referenced_elsewhere(
        self,
        relative: str,
        *,
        result_items: list[dict[str, Any]] | None = None,
        material_items: list[dict[str, Any]] | None = None,
        excluding_result_id: str = "",
        excluding_material_id: str = "",
    ) -> bool:
        if not relative:
            return False
        if result_items is None:
            result_items = self._load_index(self.result_index_path)["items"]
        if material_items is None:
            material_items = self._load_index(self.material_index_path)["items"]
        if any(
            entry.get("id") != excluding_result_id
            and self._same_asset_path(str(entry.get("path") or ""), relative)
            for entry in result_items
        ):
            return True
        return any(
            entry.get("id") != excluding_material_id
            and self._same_asset_path(str(entry.get("path") or ""), relative)
            for entry in material_items
        )

    def material_url(self, material_id: str) -> str:
        return f"/api/materials/{urllib.parse.quote(str(material_id or ''), safe='')}"

    def result_url(self, result_id: str) -> str:
        return f"/api/results/{urllib.parse.quote(str(result_id or ''), safe='')}"

    def get_material(self, material_id: str) -> dict[str, Any] | None:
        index = self._load_index(self.material_index_path)
        return next((dict(item) for item in index["items"] if item.get("id") == material_id), None)

    def material_path(self, material_id: str) -> Path | None:
        item = self.get_material(material_id)
        if not item:
            return None
        path = self._asset_path(item.get("path") or "")
        return path if path.is_file() else None

    def list_materials(self, scope: str = "", kind: str = "") -> list[dict[str, Any]]:
        index = self._load_index(self.material_index_path)
        items = []
        for raw in index["items"]:
            item = dict(raw)
            scopes = set(item.get("scopes") or [])
            if scope and scope not in scopes:
                continue
            if scope == "temporary" and "asset" in scopes:
                continue
            if kind and item.get("kind") != kind:
                continue
            item["url"] = self.material_url(item.get("id") or "")
            items.append(item)
        return sorted(items, key=lambda item: int(item.get("updated_at") or 0), reverse=True)

    def store_material_bytes(
        self,
        content: bytes,
        original_name: str,
        scope: str = "temporary",
        content_type: str = "",
        folder: str = "",
    ) -> dict[str, Any]:
        if scope not in MATERIAL_SCOPES:
            raise StorageError("未知素材范围")
        if not content:
            raise StorageError("素材内容为空")
        self.ensure_layout()
        digest = sha256_bytes(content)
        original = safe_name(original_name)
        extension = Path(original).suffix.lower()
        if not extension:
            extension = mimetypes.guess_extension(content_type or "") or ".bin"
        kind = media_kind(original, content_type)
        with self._lock:
            index = self._load_index(self.material_index_path)
            current = next((item for item in index["items"] if item.get("sha256") == digest), None)
            if current:
                scopes = set(current.get("scopes") or [])
                scopes.add(scope)
                current["scopes"] = sorted(scopes)
                if scope == "asset" and str(current.get("path") or "").startswith("input/temporary/"):
                    old_path = self._asset_path(current["path"])
                    target = self._material_target("asset", current.get("kind") or kind, old_path.name or original, digest)
                    if old_path.is_file() and old_path != target:
                        shutil.move(str(old_path), str(target))
                    current["path"] = self._asset_relative(target)
                    self._sync_external_results_for_material(current)
                current["updated_at"] = now_ms()
                if folder and not current.get("folder"):
                    current["folder"] = str(folder).strip("/\\")
                self._save_index(self.material_index_path, index)
                value = dict(current)
                value["url"] = self.material_url(value["id"])
                return value
            material_id = f"mat_{digest[:24]}"
            target = self._material_target(scope, kind, original, digest)
            if not target.exists():
                target.write_bytes(content)
            timestamp = now_ms()
            item = {
                "id": material_id,
                "sha256": digest,
                "original_name": original,
                "display_name": original,
                "kind": kind,
                "mime": content_type or mimetypes.guess_type(original)[0] or "application/octet-stream",
                "size": len(content),
                "path": self._asset_relative(target),
                "scopes": [scope],
                "folder": str(folder or "").strip("/\\"),
                "caption": "",
                "classification": {},
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            index["items"].append(item)
            self._save_index(self.material_index_path, index)
            value = dict(item)
            value["url"] = self.material_url(material_id)
            return value

    def store_material_file(self, source: str | os.PathLike[str], scope: str, original_name: str = "", folder: str = "") -> dict[str, Any]:
        path = Path(source)
        if not path.is_file():
            raise StorageError(f"素材文件不存在：{path}")
        selected_name = original_name or path.name
        if not Path(selected_name).suffix and path.suffix:
            selected_name = f"{selected_name}{path.suffix.lower()}"
        return self.store_material_bytes(
            path.read_bytes(),
            selected_name,
            scope=scope,
            content_type=mimetypes.guess_type(path.name)[0] or "",
            folder=folder,
        )

    def add_material_scope(self, material_id: str, scope: str) -> dict[str, Any]:
        if scope not in MATERIAL_SCOPES:
            raise StorageError("未知素材范围")
        with self._lock:
            index = self._load_index(self.material_index_path)
            item = next((entry for entry in index["items"] if entry.get("id") == material_id), None)
            if not item:
                raise StorageError("素材不存在")
            scopes = set(item.get("scopes") or []) | {scope}
            item["scopes"] = sorted(scopes)
            if scope == "asset" and str(item.get("path") or "").startswith("input/temporary/"):
                old_path = self._asset_path(item["path"])
                target = self._material_target("asset", item.get("kind") or "file", old_path.name, item.get("sha256") or "")
                if old_path.is_file() and old_path != target:
                    shutil.move(str(old_path), str(target))
                item["path"] = self._asset_relative(target)
                self._sync_external_results_for_material(item)
            item["updated_at"] = now_ms()
            self._save_index(self.material_index_path, index)
            value = dict(item)
            value["url"] = self.material_url(material_id)
            return value

    def promote_material(self, material_id: str, folder: str = "") -> dict[str, Any]:
        with self._lock:
            index = self._load_index(self.material_index_path)
            item = next((entry for entry in index["items"] if entry.get("id") == material_id), None)
            if not item:
                raise StorageError("素材不存在")
            old_path = self._asset_path(item.get("path") or "")
            target = self._material_target(
                "asset",
                item.get("kind") or "file",
                old_path.name or item.get("original_name") or "素材",
                item.get("sha256") or "",
            )
            if old_path.is_file() and old_path != target:
                shutil.move(str(old_path), str(target))
            item["path"] = self._asset_relative(target)
            item["scopes"] = ["asset"]
            item["folder"] = str(folder or "").strip("/\\")
            item["updated_at"] = now_ms()
            self._sync_external_results_for_material(item)
            self._save_index(self.material_index_path, index)
            value = dict(item)
            value["url"] = self.material_url(material_id)
            return value

    def rename_material(self, material_id: str, display_name: str) -> dict[str, Any]:
        name = safe_name(display_name, "素材")
        with self._lock:
            index = self._load_index(self.material_index_path)
            item = next((entry for entry in index["items"] if entry.get("id") == material_id), None)
            if not item:
                raise StorageError("素材不存在")
            old_path = self._asset_path(item.get("path") or "")
            extension = old_path.suffix or Path(item.get("original_name") or "").suffix
            known_extensions = {extension.lower()} | {suffix for values in MEDIA_EXTENSIONS.values() for suffix in values}
            if Path(name).suffix.lower() in known_extensions:
                name = Path(name).stem or "素材"
            item["display_name"] = name
            display_filename = f"{name}{extension}" if extension else name
            scope = "asset" if "asset" in set(item.get("scopes") or []) else "temporary"
            target = self._material_target(scope, item.get("kind") or "file", display_filename, item.get("sha256") or "")
            if old_path.is_file() and old_path != target:
                shutil.move(str(old_path), str(target))
            item["path"] = self._asset_relative(target)
            item["updated_at"] = now_ms()
            self._sync_external_results_for_material(item)
            self._save_index(self.material_index_path, index)
            value = dict(item)
            value["url"] = self.material_url(material_id)
            return value

    def update_material(self, material_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {"folder", "caption", "classification"}
        with self._lock:
            index = self._load_index(self.material_index_path)
            item = next((entry for entry in index["items"] if entry.get("id") == material_id), None)
            if not item:
                raise StorageError("素材不存在")
            for key, value in changes.items():
                if key in allowed:
                    item[key] = value
            item["updated_at"] = now_ms()
            self._save_index(self.material_index_path, index)
            value = dict(item)
            value["url"] = self.material_url(material_id)
            return value

    def remove_material_scope(self, material_id: str, scope: str, referenced: bool = False) -> dict[str, Any]:
        with self._lock:
            index = self._load_index(self.material_index_path)
            item = next((entry for entry in index["items"] if entry.get("id") == material_id), None)
            if not item:
                raise StorageError("素材不存在")
            if referenced:
                raise StorageError("素材仍被画布引用，不能删除")
            scopes = set(item.get("scopes") or [])
            scopes.discard(scope)
            old_relative = str(item.get("path") or "")
            if scopes:
                item["scopes"] = sorted(scopes)
                if scope == "asset" and "temporary" in scopes and str(item.get("path") or "").startswith("input/asset/"):
                    old_path = self._asset_path(item["path"])
                    target = self._material_target("temporary", item.get("kind") or "file", old_path.name, item.get("sha256") or "")
                    if old_path.is_file() and old_path != target:
                        shutil.move(str(old_path), str(target))
                    item["path"] = self._asset_relative(target)
                item["updated_at"] = now_ms()
                if item.get("path") != old_relative:
                    self._sync_external_results_for_material(item)
            else:
                results = self._load_index(self.result_index_path)["items"]
                if self._material_has_result_reference(item, results):
                    item["scopes"] = []
                    item["updated_at"] = now_ms()
                else:
                    index["items"] = [entry for entry in index["items"] if entry.get("id") != material_id]
                    if not self._path_referenced_elsewhere(
                        old_relative,
                        result_items=results,
                        material_items=index["items"],
                    ):
                        self._asset_path(old_relative).unlink(missing_ok=True)
            self._save_index(self.material_index_path, index)
            return {"id": material_id, "removed_scope": scope, "deleted_file": not scopes and item not in index["items"]}

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        index = self._load_index(self.result_index_path)
        return next((dict(item) for item in index["items"] if item.get("id") == result_id), None)

    def result_path(self, result_id: str) -> Path | None:
        item = self.get_result(result_id)
        if not item or not item.get("path"):
            return None
        path = self._asset_path(item["path"])
        return path if path.is_file() else None

    def list_results(self, kind: str = "") -> list[dict[str, Any]]:
        index = self._load_index(self.result_index_path)
        items = []
        for raw in index["items"]:
            if kind and raw.get("kind") != kind:
                continue
            item = dict(raw)
            item["url"] = self.result_url(item.get("id") or "")
            items.append(item)
        return sorted(items, key=lambda item: int(item.get("created_at") or 0), reverse=True)

    def prune_missing_results(self, kind: str = "") -> int:
        with self._lock:
            index = self._load_index(self.result_index_path)
            kept = []
            removed = 0
            for item in index["items"]:
                if kind and item.get("kind") != kind:
                    kept.append(item)
                    continue
                path = self._asset_path(item.get("path") or "")
                if path.is_file():
                    kept.append(item)
                else:
                    removed += 1
            if removed:
                index["items"] = kept
                self._save_index(self.result_index_path, index)
            return removed

    def set_result_source_canvas(self, result_id: str, canvas: dict[str, Any]) -> dict[str, Any]:
        canvas_id = str((canvas or {}).get("id") or "").strip()
        if not canvas_id:
            raise StorageError("画布 ID 不能为空")
        with self._lock:
            index = self._load_index(self.result_index_path)
            item = next((entry for entry in index["items"] if entry.get("id") == result_id), None)
            if not item:
                raise StorageError("生成结果不存在")
            current = item.get("source_canvas") if isinstance(item.get("source_canvas"), dict) else {}
            if current.get("id") and current.get("id") != canvas_id:
                value = dict(item)
                value["url"] = self.result_url(result_id)
                return value
            item["source_canvas"] = {
                "id": canvas_id,
                "title": str((canvas or {}).get("title") or current.get("title") or "未命名画布")[:120],
                "kind": str((canvas or {}).get("kind") or current.get("kind") or "smart"),
            }
            item["updated_at"] = now_ms()
            self._save_index(self.result_index_path, index)
            value = dict(item)
            value["url"] = self.result_url(result_id)
            return value

    def update_result_metadata(self, result_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {"derivation", "media_info", "media_category", "creation_recipes"}
        with self._lock:
            index = self._load_index(self.result_index_path)
            item = next((entry for entry in index["items"] if entry.get("id") == result_id), None)
            if not item:
                raise StorageError("生成结果不存在")
            for key, value in changes.items():
                if key in allowed:
                    item[key] = value
            item["updated_at"] = now_ms()
            self._save_index(self.result_index_path, index)
            value = dict(item)
            value["url"] = self.result_url(result_id)
            return value

    def rename_result(self, result_id: str, display_name: str) -> dict[str, Any]:
        name = safe_name(display_name, "生成结果")
        with self._lock:
            index = self._load_index(self.result_index_path)
            item = next((entry for entry in index["items"] if entry.get("id") == result_id), None)
            if not item:
                raise StorageError("生成结果不存在")
            old_path = self._asset_path(item.get("path") or "")
            extension = old_path.suffix or Path(item.get("original_name") or "").suffix
            known_extensions = {extension.lower()} | {
                suffix for values in MEDIA_EXTENSIONS.values() for suffix in values
            }
            if Path(name).suffix.lower() in known_extensions:
                name = Path(name).stem or "生成结果"
            display_filename = f"{name}{extension}" if extension else name
            materials = self._load_index(self.material_index_path)["items"]
            origin = item.get("origin") if isinstance(item.get("origin"), dict) else {}
            shared_by_source = bool(
                origin.get("kind") == "external_cli"
                and any(material.get("id") == origin.get("source_material_id") for material in materials)
            )
            shared_by_path = self._path_referenced_elsewhere(
                str(item.get("path") or ""),
                result_items=index["items"],
                material_items=materials,
                excluding_result_id=result_id,
            )
            if shared_by_source or shared_by_path:
                item["display_name"] = display_filename
                item["updated_at"] = now_ms()
                self._save_index(self.result_index_path, index)
                value = dict(item)
                value["url"] = self.result_url(result_id)
                return value
            digest = item.get("sha256") or (sha256_file(old_path) if old_path.is_file() else "")
            target = self._readable_target(
                self.results_dir / (item.get("kind") or "file"),
                display_filename,
                digest,
            )
            if old_path.is_file() and old_path != target:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_path), str(target))
            item["display_name"] = display_filename
            item["path"] = self._asset_relative(target)
            item["size"] = target.stat().st_size if target.is_file() else item.get("size", 0)
            item["updated_at"] = now_ms()
            self._save_index(self.result_index_path, index)
            value = dict(item)
            value["url"] = self.result_url(result_id)
            return value

    def store_result_file(self, source: str | os.PathLike[str], display_name: str = "", move: bool = False) -> dict[str, Any]:
        source_path = Path(source).absolute()
        if not source_path.is_file():
            raise StorageError(f"结果文件不存在：{source_path}")
        self.ensure_layout()
        digest = sha256_file(source_path)
        name = safe_name(display_name or source_path.name, "结果")
        extension = source_path.suffix.lower() or Path(name).suffix.lower() or ".bin"
        kind = media_kind(name or source_path.name)
        target = self._readable_target(self.results_dir / kind, name if Path(name).suffix else f"{name}{extension}", digest)
        with self._lock:
            index = self._load_index(self.result_index_path)
            physical = next((item for item in index["items"] if item.get("sha256") == digest and item.get("path")), None)
            if physical:
                target = self._asset_path(physical["path"])
                if move and source_path != target:
                    source_path.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
            if not physical and source_path != target.absolute():
                if move:
                    shutil.move(str(source_path), str(target))
                else:
                    shutil.copy2(source_path, target)
            timestamp = now_ms()
            result_id = f"res_{uuid.uuid4().hex[:24]}"
            item = {
                "id": result_id,
                "sha256": digest,
                "display_name": name,
                "original_name": source_path.name,
                "kind": kind,
                "mime": mimetypes.guess_type(name)[0] or "application/octet-stream",
                "size": target.stat().st_size,
                "path": self._asset_relative(target),
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            index["items"].append(item)
            self._save_index(self.result_index_path, index)
            value = dict(item)
            value["url"] = self.result_url(result_id)
            return value

    def register_managed_result(self, source: str | os.PathLike[str], display_name: str = "", **metadata: Any) -> dict[str, Any]:
        """登记受管原生结果，保留伴随清单的相对文件布局，不再复制媒体。"""
        path = Path(source).resolve()
        if not path.is_file() or not path.is_relative_to(self.results_dir.resolve()):
            raise StorageError("只能登记生成结果目录内的真实文件")
        digest = sha256_file(path)
        name = safe_name(display_name or path.name, "结果")
        with self._lock:
            index = self._load_index(self.result_index_path)
            item = next((entry for entry in index['items'] if entry.get('sha256') == digest
                         and entry.get('path') and self._asset_path(entry['path']).is_file()), None)
            if item is None:
                item = {'id': f'res_{uuid.uuid4().hex[:24]}', 'sha256': digest,
                        'display_name': name, 'original_name': path.name, 'kind': media_kind(name),
                        'mime': mimetypes.guess_type(name)[0] or 'application/octet-stream',
                        'size': path.stat().st_size, 'path': self._asset_relative(path),
                        'created_at': now_ms(), 'updated_at': now_ms()}
                item.update({key: str(metadata[key]) for key in ('source_module', 'source_project_id', 'source_build_id') if key in metadata})
                index['items'].append(item)
                self._save_index(self.result_index_path, index)
            return {**item, 'url': self.result_url(item['id'])}

    @staticmethod
    def _external_cli_identity(value: Any, field: str) -> str:
        if not isinstance(value, str):
            raise StorageError(f"外部素材登记字段 {field} 必须是字符串")
        normalized = value.strip()
        limits = {"provider": 80, "tool": 120, "model": 160, "task_id": 180}
        limit = limits[field]
        if not normalized or len(normalized) > limit:
            raise StorageError(f"外部素材登记字段 {field} 不能为空或超过 {limit} 个字符")
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise StorageError(f"外部素材登记字段 {field} 不能包含控制字符")
        lowered = normalized.lower()
        if re.search(r"(?:https?://|data:|file://)", lowered):
            raise StorageError(f"外部素材登记字段 {field} 不能包含 URL 或 data URI")
        if re.search(r"\b(?:api[\s_-]?key|authorization|bearer|token|secret|password|signed[\s_-]?url)\b", lowered):
            raise StorageError(f"外部素材登记字段 {field} 不能包含凭据内容")
        if normalized.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", normalized):
            raise StorageError(f"外部素材登记字段 {field} 不能是文件路径")
        if any(part == ".." for part in re.split(r"[/\\]", normalized)):
            raise StorageError(f"外部素材登记字段 {field} 不能包含路径穿越片段")
        return normalized

    def register_external_material_result(
        self,
        material_id: str,
        *,
        provider: str,
        tool: str,
        model: str,
        task_id: str,
        output_index: int,
    ) -> dict[str, Any]:
        """Create an external CLI result record that aliases a managed material file."""
        source_id = str(material_id or "").strip()
        if not source_id or len(source_id) > 200 or any(ord(character) < 32 for character in source_id):
            raise StorageError("外部素材登记缺少有效素材 ID")
        identity = {
            "provider": self._external_cli_identity(provider, "provider"),
            "tool": self._external_cli_identity(tool, "tool"),
            "model": self._external_cli_identity(model, "model"),
            "task_id": self._external_cli_identity(task_id, "task_id"),
        }
        if type(output_index) is not int or output_index < 1 or output_index > 100:
            raise StorageError("外部素材登记字段 output_index 必须是 1 到 100 的整数")

        with self._lock:
            material_index = self._load_index(self.material_index_path)
            material = next((entry for entry in material_index["items"] if entry.get("id") == source_id), None)
            if not material:
                raise StorageError("外部素材登记引用的素材不存在")
            relative = str(material.get("path") or "")
            try:
                source_path = self._asset_path(relative).resolve()
                managed_root = self.materials_dir.resolve()
            except OSError as exc:
                raise StorageError("外部素材登记的素材路径无效") from exc
            if not source_path.is_relative_to(managed_root):
                raise StorageError("外部素材登记只能引用 assets/input 内的受管素材")
            if not source_path.is_file():
                raise StorageError("外部素材登记引用的受管素材文件不存在")
            digest = sha256_file(source_path)
            expected_digest = str(material.get("sha256") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected_digest) or digest != expected_digest:
                raise StorageError("外部素材登记引用的素材内容与 SHA-256 索引不匹配")

            receipt = {
                "kind": "external_cli",
                "source_material_id": source_id,
                **identity,
                "output_index": output_index,
                "provenance_verified": False,
            }
            receipt_bytes = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            result_id = f"res_{sha256_bytes(receipt_bytes)[:24]}"
            index = self._load_index(self.result_index_path)
            existing = next((entry for entry in index["items"] if (
                isinstance(entry.get("origin"), dict) and entry.get("origin") == receipt
            )), None)
            if existing:
                if existing.get("sha256") != digest:
                    raise StorageError("相同外部素材回执已登记为不同文件内容，拒绝覆盖")
                if existing.get("id") != result_id:
                    raise StorageError("外部素材回执与已有结果标识不一致，拒绝覆盖")
                changed = False
                if existing.get("path") != relative or existing.get("size") != source_path.stat().st_size:
                    existing["path"] = relative
                    existing["size"] = source_path.stat().st_size
                    existing["updated_at"] = now_ms()
                    changed = True
                if changed:
                    self._save_index(self.result_index_path, index)
                return {**existing, "url": self.result_url(result_id)}

            collision = next((entry for entry in index["items"] if entry.get("id") == result_id), None)
            if collision:
                raise StorageError("外部素材回执生成的结果 ID 已被其他来源占用，拒绝覆盖")
            timestamp = now_ms()
            original_name = safe_name(str(material.get("original_name") or source_path.name), "素材")
            item = {
                "id": result_id,
                "sha256": digest,
                "display_name": safe_name(str(material.get("display_name") or original_name), "生成结果"),
                "original_name": original_name,
                "kind": str(material.get("kind") or media_kind(original_name)),
                "mime": str(material.get("mime") or mimetypes.guess_type(original_name)[0] or "application/octet-stream"),
                "size": source_path.stat().st_size,
                "path": relative,
                "created_at": timestamp,
                "updated_at": timestamp,
                "origin": receipt,
            }
            index["items"].append(item)
            self._save_index(self.result_index_path, index)
            return {**item, "url": self.result_url(result_id)}

    def delete_result(self, result_id: str) -> bool:
        with self._lock:
            index = self._load_index(self.result_index_path)
            item = next((entry for entry in index["items"] if entry.get("id") == result_id), None)
            if not item:
                return False
            remaining = [entry for entry in index["items"] if entry.get("id") != result_id]
            shared_path = str(item.get("path") or "")
            index["items"] = remaining
            self._save_index(self.result_index_path, index)

            material_index = self._load_index(self.material_index_path)
            origin = item.get("origin") if isinstance(item.get("origin"), dict) else {}
            source_id = str(origin.get("source_material_id") or "") if origin.get("kind") == "external_cli" else ""
            orphaned = next((entry for entry in material_index["items"] if entry.get("id") == source_id and not entry.get("scopes")), None)
            if orphaned and not self._material_has_result_reference(orphaned, remaining):
                material_index["items"] = [entry for entry in material_index["items"] if entry.get("id") != source_id]
                if not self._path_referenced_elsewhere(
                    str(orphaned.get("path") or ""),
                    result_items=remaining,
                    material_items=material_index["items"],
                ):
                    self._asset_path(str(orphaned.get("path") or "")).unlink(missing_ok=True)
                self._save_index(self.material_index_path, material_index)

            if shared_path and not self._path_referenced_elsewhere(
                shared_path,
                result_items=remaining,
                material_items=material_index["items"],
            ):
                self._asset_path(shared_path).unlink(missing_ok=True)
            return True

    def material_reference_count(self, material_id: str) -> int:
        needle = self.material_url(material_id)
        total = 0
        for path in (self.data_dir / "canvases").glob("*.json"):
            try:
                total += path.read_text(encoding="utf-8-sig").count(needle)
            except OSError:
                continue
        return total

    def _legacy_url_entries(self, source: Path, category: str, record: dict[str, Any]) -> dict[str, dict[str, str]]:
        relative = source.relative_to(self.root).as_posix()
        quoted = urllib.parse.quote(relative, safe="/")
        target = self.material_url(record["id"]) if category == "material" else self.result_url(record["id"])
        identity_key = "material_id" if category == "material" else "result_id"
        entries = {
            f"/{relative}": {"url": target, identity_key: record["id"]},
            f"/{quoted}": {"url": target, identity_key: record["id"]},
        }
        if relative.startswith("assets/uploads/"):
            local_rel = relative[len("assets/uploads/"):]
            entries[f"/api/storage-files/local/{local_rel}"] = {"url": target, identity_key: record["id"]}
            entries[f"/api/storage-files/local/{urllib.parse.quote(local_rel, safe='/')}"] = {"url": target, identity_key: record["id"]}
        return entries

    def _rewrite_value(self, value: Any, mappings: dict[str, dict[str, str]]) -> tuple[Any, int]:
        changed = 0
        if isinstance(value, list):
            result = []
            for entry in value:
                next_entry, entry_changed = self._rewrite_value(entry, mappings)
                result.append(next_entry)
                changed += entry_changed
            return result, changed
        if isinstance(value, dict):
            original_url = str(value.get("url") or "")
            original_match = self._mapping_for_url(original_url, mappings)
            result = {}
            for key, entry in value.items():
                next_entry, entry_changed = self._rewrite_value(entry, mappings)
                result[key] = next_entry
                changed += entry_changed
            match = original_match or self._mapping_for_url(str(result.get("url") or ""), mappings)
            if match:
                if result.get("url") != match["url"]:
                    result["url"] = match["url"]
                    changed += 1
                for key in ("material_id", "result_id"):
                    if match.get(key) and result.get(key) != match[key]:
                        result[key] = match[key]
                        changed += 1
            return result, changed
        if isinstance(value, str):
            match = self._mapping_for_url(value, mappings)
            if match:
                return match["url"], 1
        return value, changed

    def _mapping_for_url(self, value: str, mappings: dict[str, dict[str, str]]) -> dict[str, str] | None:
        text = str(value or "").strip()
        if not text:
            return None
        direct = mappings.get(text) or mappings.get(urllib.parse.unquote(text))
        if direct:
            return direct
        parsed = urllib.parse.urlsplit(text)
        path = urllib.parse.unquote(parsed.path or "")
        return mappings.get(path) or mappings.get(urllib.parse.quote(path, safe="/"))

    def _rewrite_json_file(self, path: Path, mappings: dict[str, dict[str, str]], normalize_library: bool = False) -> int:
        value = self._read_json(path, None)
        if value is None:
            return 0
        rewritten, changed = self._rewrite_value(value, mappings)
        if normalize_library and isinstance(rewritten, dict):
            for library in rewritten.get("libraries") or []:
                if isinstance(library, dict) and library.get("id") == "default" and library.get("name") != "资产库":
                    library["name"] = "资产库"
                    changed += 1
            if rewritten.get("active_library_id") == "default":
                categories = next((library.get("categories") for library in rewritten.get("libraries") or [] if library.get("id") == "default"), None)
                if categories is not None:
                    rewritten["categories"] = categories
        if changed:
            self._write_json(path, rewritten)
        return changed

    def migrate_legacy(self, cleanup: bool = False) -> dict[str, Any]:
        self.ensure_layout()
        support_files = self._migrate_support_files(cleanup)
        mappings: dict[str, dict[str, str]] = {}
        migrated_sources: list[Path] = []
        material_ids: set[str] = set()
        result_ids: set[str] = set()
        material_sources = [
            (self.assets_dir / "input", "temporary"),
            (self.assets_dir / "uploads", "temporary"),
            (self.assets_dir / "library", "asset"),
        ]
        for base, scope in material_sources:
            if not base.is_dir():
                continue
            for source in sorted(base.rglob("*")):
                if not source.is_file() or source.name.startswith((".", "._")):
                    continue
                relative_parts = source.relative_to(base).parts
                if base == self.materials_dir and relative_parts and relative_parts[0] in {"asset", "temporary", "imports"}:
                    continue
                if source.suffix.lower() in {".classification.json", ".txt"} and base.name == "uploads":
                    continue
                if base.name == "library" and source.suffix.lower() in {".zip", ".json"}:
                    target = self.canvas_workflows_dir / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        shutil.copy2(source, target)
                    old = f"/{source.relative_to(self.root).as_posix()}"
                    filename = urllib.parse.quote(target.name, safe="")
                    mappings[old] = {"url": f"/workflow-files/{filename}"}
                    migrated_sources.append(source)
                    continue
                folder = source.parent.relative_to(base).as_posix()
                if folder == ".":
                    folder = ""
                record = self.store_material_file(source, scope, original_name=source.name, folder=folder)
                material_ids.add(record["id"])
                mappings.update(self._legacy_url_entries(source, "material", record))
                migrated_sources.append(source)
        result_sources = [self.assets_dir / "output", self.root / "output"]
        for base in result_sources:
            if not base.is_dir():
                continue
            for source in sorted(base.rglob("*")):
                if not source.is_file() or source.name.startswith((".", "._")):
                    continue
                relative_parts = source.relative_to(base).parts
                if base == self.results_dir and relative_parts and relative_parts[0] in {"image", "video", "audio", "text", "file", ".pending"}:
                    continue
                record = self.store_result_file(source, source.name)
                result_ids.add(record["id"])
                mappings.update(self._legacy_url_entries(source, "result", record))
                migrated_sources.append(source)
        rewritten = 0
        canvas_dir = self.data_dir / "canvases"
        if canvas_dir.is_dir():
            for path in canvas_dir.glob("*.json"):
                rewritten += self._rewrite_json_file(path, mappings)
        asset_library = self.data_dir / "asset_library.json"
        if asset_library.exists():
            rewritten += self._rewrite_json_file(asset_library, mappings, normalize_library=True)
        manifest = self._read_json(self.manifest_path, {})
        manifest.update({
            "version": SCHEMA_VERSION,
            "updated_at": now_ms(),
            "last_migration_at": now_ms(),
            "legacy_urls": {key: value["url"] for key, value in mappings.items()},
        })
        self._write_json(self.manifest_path, manifest)
        if cleanup:
            canonical = {self._asset_path(item["path"]).resolve() for item in self.list_materials()}
            canonical.update(self._asset_path(item["path"]).resolve() for item in self.list_results())
            for source in migrated_sources:
                if source.resolve() not in canonical:
                    source.unlink(missing_ok=True)
            self._remove_empty_legacy_dirs()
        return {
            "version": SCHEMA_VERSION,
            "materials": len(material_ids),
            "results": len(result_ids),
            "rewritten_references": rewritten,
            "legacy_files": len(migrated_sources),
            "support_files": support_files,
            "cleanup": bool(cleanup),
        }

    def _migrate_support_files(self, cleanup: bool) -> int:
        copied = 0

        def copy_file(source: Path, target: Path) -> None:
            nonlocal copied
            if not source.is_file() or source.absolute() == target.absolute():
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)
                copied += 1
            if cleanup and target.is_file() and sha256_file(source) == sha256_file(target):
                source.unlink(missing_ok=True)

        comfyui_dir = self.workflows_dir / "comfyui"
        comfyui_dir.mkdir(parents=True, exist_ok=True)
        for source in self.workflows_dir.iterdir():
            if source.is_file() and source.suffix.lower() == ".json":
                copy_file(source, comfyui_dir / source.name)
        copy_file(self.root / "history.json", self.data_dir / "history.json")
        copy_file(self.root / "global_config.json", self.config_dir / "global.json")
        legacy_previews = self.data_dir / "media_previews"
        if legacy_previews.is_dir():
            for source in legacy_previews.rglob("*"):
                if source.is_file():
                    copy_file(source, self.previews_dir / "media" / source.relative_to(legacy_previews))
        return copied

    def _remove_empty_legacy_dirs(self) -> None:
        for path in (
            self.assets_dir / "uploads",
            self.assets_dir / "library",
            self.root / "output",
            self.data_dir / "media_previews",
        ):
            if not path.exists():
                continue
            for metadata_name in (".DS_Store", "Thumbs.db", "desktop.ini"):
                for metadata in path.rglob(metadata_name):
                    metadata.unlink(missing_ok=True)
            for current, _dirs, _files in os.walk(path, topdown=False):
                current_path = Path(current)
                try:
                    current_path.rmdir()
                except OSError:
                    pass

    def create_backup(self, destination: str | os.PathLike[str] | None = None, include_secrets: bool = False) -> Path:
        self.ensure_layout()
        if destination:
            archive = Path(destination).expanduser().resolve()
        else:
            # 同秒内的恢复前备份不能覆盖正在读取的原备份（Windows 还会拒绝替换）。
            archive = self.backups_dir / f"无限画布备份-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.zip"
        archive.parent.mkdir(parents=True, exist_ok=True)
        temp = archive.with_name(f".{archive.name}.{uuid.uuid4().hex}.tmp")
        sources: list[Path] = [self.data_dir, self.assets_dir]
        for relative in ("workflows", "output", "history.json", "global_config.json", "static/runninghub"):
            path = self.root / relative
            if path.exists():
                sources.append(path)
        if include_secrets and (self.root / "API").exists():
            sources.append(self.root / "API")
        manifest = {
            "version": SCHEMA_VERSION,
            "created_at": now_ms(),
            "project": self.root.name,
            "include_secrets": bool(include_secrets),
        }
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
            bundle.writestr("backup-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            seen: set[str] = set()
            for source in sources:
                files = source.rglob("*") if source.is_dir() else [source]
                for path in files:
                    if not path.is_file():
                        continue
                    if self.backups_dir == path or self.backups_dir in path.parents:
                        continue
                    relative = path.relative_to(self.root).as_posix()
                    if relative in seen or relative.startswith(("__pycache__/", ".git/", ".superpowers/")):
                        continue
                    seen.add(relative)
                    bundle.write(path, relative)
        os.replace(temp, archive)
        return archive

    def restore_backup(self, archive: str | os.PathLike[str], create_safety_backup: bool = False) -> dict[str, Any]:
        source = Path(archive).expanduser().resolve()
        if not source.is_file():
            raise StorageError("备份文件不存在")
        allowed_roots = {"data", "assets", "workflows", "output", "API", "static"}
        allowed_files = {"history.json", "global_config.json", "backup-manifest.json"}
        with zipfile.ZipFile(source) as bundle:
            members = bundle.infolist()
            for member in members:
                name = member.filename.replace("\\", "/")
                path = Path(name)
                if path.is_absolute() or ".." in path.parts:
                    raise StorageError("备份包包含不安全路径")
                if not path.parts:
                    continue
                if path.parts[0] not in allowed_roots and name not in allowed_files:
                    raise StorageError(f"备份包包含未知路径：{name}")
            if "backup-manifest.json" not in {item.filename for item in members}:
                raise StorageError("备份包缺少清单")
            safety = self.create_backup(include_secrets=True) if create_safety_backup else None
            restored = 0
            for member in members:
                if member.is_dir() or member.filename == "backup-manifest.json":
                    continue
                target = (self.root / member.filename).resolve()
                if self.root not in target.parents:
                    raise StorageError("恢复路径超出项目目录")
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as input_file, target.open("wb") as output_file:
                    shutil.copyfileobj(input_file, output_file)
                restored += 1
        self.ensure_layout()
        return {"restored": restored, "safety_backup": str(safety) if safety else ""}

    def status(self) -> dict[str, Any]:
        self.ensure_layout()

        def directory_size(path: Path) -> int:
            return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())

        return {
            "version": SCHEMA_VERSION,
            "root": str(self.root),
            "materials": len(self.list_materials()),
            "results": len(self.list_results()),
            "data_bytes": directory_size(self.data_dir),
            "assets_bytes": directory_size(self.assets_dir),
            "layout": {key: str(value) for key, value in self.layout().items()},
        }
