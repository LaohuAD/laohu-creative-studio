"""Atomic, snapshot-based bridge from saved script segments to canvas progress."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from typing import Any

from canvas_core.headless_canvas import HeadlessCanvas, HeadlessCanvasError
from studio_manuscripts import StudioManuscriptStore
from studio_projects import StudioProjectError
from studio_modules import RESERVED_SETTINGS_CANVAS_IDS
from canvas_core.json_store import DataFileError


_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def _strict_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HeadlessCanvasError(f"{label} 必须是正整数")
    return value


class StudioScriptImport:
    """Resolve script snapshots before the canvas lock, then commit once."""

    def __init__(self, manuscripts: StudioManuscriptStore, canvas: HeadlessCanvas):
        self.manuscripts = manuscripts
        self.canvas = canvas

    async def execute(self, canvas_id: str, args: Mapping[str, Any], request_id: str) -> dict[str, Any]:
        if not isinstance(args, Mapping):
            raise HeadlessCanvasError("import_script_segments.args 必须是对象")
        unknown = set(args) - {"script_project_id", "source_revision", "expected_canvas_revision", "scope", "mode"}
        missing = {"script_project_id", "source_revision", "expected_canvas_revision", "scope", "mode"} - set(args)
        if unknown or missing:
            details = []
            if unknown:
                details.append("未知字段：" + ", ".join(sorted(unknown)))
            if missing:
                details.append("缺少字段：" + ", ".join(sorted(missing)))
            raise HeadlessCanvasError("；".join(details))
        project_id = str(args.get("script_project_id") or "").strip()
        if not _ID.fullmatch(project_id):
            raise HeadlessCanvasError("script_project_id 不合法")
        source_revision = _strict_positive_int(args.get("source_revision"), "source_revision")
        canvas_revision = _strict_positive_int(args.get("expected_canvas_revision"), "expected_canvas_revision")
        mode = str(args.get("mode") or "")
        if mode not in {"append", "new_snapshot"}:
            raise HeadlessCanvasError("mode 必须是 append 或 new_snapshot")
        if not _ID.fullmatch(str(request_id or "")):
            raise HeadlessCanvasError("request_id 只能包含英文字母、数字、下划线和连字符")
        if str(canvas_id) in RESERVED_SETTINGS_CANVAS_IDS:
            raise HeadlessCanvasError("剧本只能导入普通画布，不能导入模块设置图")

        prior = self.canvas.script_import_receipt(str(canvas_id), str(request_id), args)
        if prior is not None:
            return prior

        # This read owns and releases the shared Studio project lock before the
        # canvas transaction starts. No model or filesystem media operation is
        # performed while either lock is held.
        try:
            snapshot = self.manuscripts.script_import_snapshot(project_id, source_revision, args["scope"])
        except StudioProjectError as exc:
            raise HeadlessCanvasError(exc.detail, status_code=exc.status_code) from exc
        except DataFileError as exc:
            raise HeadlessCanvasError(str(exc), status_code=500) from exc
        return await self.canvas.import_script_snapshot(
            str(canvas_id), dict(args), str(request_id), snapshot,
            expected_canvas_revision=canvas_revision,
        )


def import_fingerprint(action: str, args: Mapping[str, Any]) -> str:
    encoded = json.dumps([action, args], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["StudioScriptImport", "import_fingerprint"]
