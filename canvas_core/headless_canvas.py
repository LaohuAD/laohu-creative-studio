"""无浏览器画布执行器。

这里保留画布 Agent 的数据契约，只负责结构化命令、节点/连线变更和
已有运行回调的编排。真实模型请求、素材落盘和任务生命周期由调用方传入
的 ``submit_run`` / ``cancel_run`` 负责。
"""

from __future__ import annotations

import copy
import hashlib
import html
import inspect
import json
import math
import time
import uuid
from collections.abc import Mapping
from typing import Any, Callable

from canvas_core.hypit_config import (
    HYPIT_OUTPUT_KINDS,
    HYPIT_OUTPUT_SLOTS,
    HYPIT_SETTINGS_CANVAS_ID,
    validate_hypit_settings_canvas,
)


class HeadlessCanvasError(ValueError):
    """命令不符合当前画布契约。"""


class HeadlessCanvas:
    """在服务端执行画布 Agent 命令。

    ``load_canvas``、``save_canvas`` 和 ``lock`` 是主程序已有的同步存储
    接口；本类不复制模型适配器、素材存储或任务执行器。
    """

    NODE_TYPES = {
        "material": "smart-material",
        "text": "smart-text-generator",
        "image": "smart-image-generator",
        "video": "smart-video-generator",
        "audio": "smart-audio-generator",
        "music": "smart-music-generator",
        "app": "smart-ai-app",
        "comfy": "smart-comfy-workflow",
    }
    EXECUTION_TYPES = {
        "smart-text-generator",
        "smart-image-generator",
        "smart-video-generator",
        "smart-audio-generator",
        "smart-music-generator",
        "smart-ai-app",
        "smart-comfy-workflow",
    }
    MATERIAL_TYPES = {"smart-material", "smart-image"}
    MODEL_FIELDS = {
        "text": ("textProvider", "textModel", "textFamilyId", "text_generation"),
        "image": ("provider_id", "model", "imageFamilyId", "image_generation"),
        "video": ("videoProvider", "videoModel", "videoFamilyId", "video_generation"),
        "audio": ("audioProvider", "audioModel", "audioFamilyId", "audio_generation"),
        "music": ("musicProvider", "musicModel", "musicFamilyId", "music_generation"),
    }
    OUTPUT_KINDS = {
        "smart-text-generator": "text",
        "smart-image-generator": "image",
        "smart-video-generator": "video",
        "smart-audio-generator": "audio",
        "smart-music-generator": "audio",
        "smart-ai-app": "dynamic",
        "smart-comfy-workflow": "dynamic",
    }
    TITLES = {
        "smart-text-generator": "文本生成",
        "smart-image-generator": "图片生成",
        "smart-video-generator": "视频生成",
        "smart-audio-generator": "音频生成",
        "smart-music-generator": "音乐生成",
        "smart-ai-app": "RunningHub ComfyUI",
        "smart-comfy-workflow": "本地 ComfyUI",
    }
    APP_RUN_SETTINGS = {"rhAppId", "rhConfigKey", "rhParams"}
    COMFY_RUN_SETTINGS = {"comfyWorkflow", "comfyParams"}
    PRODUCTION_FIELDS = {
        "role",
        "order",
        "sourceNodeId",
        "sourceStart",
        "sourceEnd",
        "imageNodeIds",
        "audioNodeIds",
        "videoNodeIds",
    }
    PRODUCTION_COLUMNS = {
        "imageNodeIds": "image",
        "audioNodeIds": "audio",
        "videoNodeIds": "video",
    }
    TERMINAL_TASK_STATES = {"succeeded", "partially_succeeded", "failed", "cancelled"}

    def __init__(
        self,
        load_canvas: Callable[[str], dict[str, Any]],
        save_canvas: Callable[[dict[str, Any]], Any],
        lock: Any,
        submit_run: Callable[[dict[str, Any], dict[str, Any], str], Any],
        cancel_run: Callable[[dict[str, Any], dict[str, Any], str], Any],
        validate_model: Callable[[str, str, str, dict[str, Any]], Mapping[str, Any]],
        notify: Callable[[dict[str, Any]], Any] | None = None,
    ):
        self.load_canvas = load_canvas
        self.save_canvas = save_canvas
        self.lock = lock
        self.submit_run = submit_run
        self.cancel_run = cancel_run
        self.validate_model = validate_model
        self.notify = notify
        self._request_cache: dict[tuple[str, str], tuple[str, Any]] = {}

    async def execute(
        self,
        canvas_id: str,
        action: str,
        args: Mapping[str, Any] | None,
        request_id: str,
    ) -> dict[str, Any]:
        """执行一个幂等 Agent 命令并持久化画布结果。"""

        canvas_id = str(canvas_id or "").strip()
        action = str(action or "").strip()
        request_id = str(request_id or "").strip()
        if not canvas_id:
            raise HeadlessCanvasError("画布 ID 不能为空")
        if not action:
            raise HeadlessCanvasError("命令 action 不能为空")
        if not request_id:
            raise HeadlessCanvasError("request_id 不能为空")
        if args is None:
            args = {}
        if not isinstance(args, Mapping):
            raise HeadlessCanvasError("命令 args 必须是对象")
        args = copy.deepcopy(dict(args))
        fingerprint = self._fingerprint(action, args)
        cache_key = (canvas_id, request_id)
        with self.lock:
            cached = self._request_cache.get(cache_key)
            if cached:
                old_fingerprint, result = cached
                if old_fingerprint != fingerprint:
                    raise HeadlessCanvasError("同一 request_id 不能提交不同操作")
                return copy.deepcopy(result)

            canvas = self._load(canvas_id)
            before = copy.deepcopy(canvas)
            numbers_changed = self._ensure_canvas_shape(canvas, canvas_id)

        try:
            if action == "run_node":
                result = await self._run_node(canvas, args, request_id)
            elif action == "cancel_run":
                result = await self._cancel_run(canvas, args)
            else:
                with self.lock:
                    result = self._execute_sync(canvas, action, args)
        except Exception:
            with self.lock:
                self._restore(canvas, before)
            raise

        should_persist = numbers_changed or action not in {"snapshot", "production_status"} or canvas != before
        if should_persist:
            with self.lock:
                self.save_canvas(canvas)
            await self._notify(canvas)

        result = copy.deepcopy(result)
        with self.lock:
            self._request_cache[cache_key] = (fingerprint, copy.deepcopy(result))
        return result

    def _load(self, canvas_id: str) -> dict[str, Any]:
        canvas = self.load_canvas(canvas_id)
        if not isinstance(canvas, dict):
            raise HeadlessCanvasError("画布数据必须是对象")
        return canvas

    @staticmethod
    def _restore(canvas: dict[str, Any], source: dict[str, Any]) -> None:
        canvas.clear()
        canvas.update(copy.deepcopy(source))

    @staticmethod
    def _fingerprint(action: str, args: Mapping[str, Any]) -> str:
        payload = json.dumps([action, args], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def _notify(self, canvas: dict[str, Any]) -> None:
        if self.notify is None:
            return
        value = self.notify(canvas)
        if inspect.isawaitable(value):
            await value

    def _ensure_canvas_shape(self, canvas: dict[str, Any], canvas_id: str) -> bool:
        changed = False
        if canvas.get("id") != canvas_id:
            canvas["id"] = canvas_id
            changed = True
        if not isinstance(canvas.get("nodes"), list):
            canvas["nodes"] = []
            changed = True
        if not isinstance(canvas.get("connections"), list):
            canvas["connections"] = []
            changed = True

        used: set[int] = set()
        next_number = self._positive_int(canvas.get("nextNodeNumber"), 1)
        for node in canvas["nodes"]:
            if not isinstance(node, dict):
                raise HeadlessCanvasError("画布包含无效节点")
            current = self._positive_int(node.get("displayNumber"), 0)
            if not current or current in used:
                while next_number in used:
                    next_number += 1
                node["displayNumber"] = next_number
                current = next_number
                changed = True
            elif node.get("displayNumber") != current:
                node["displayNumber"] = current
                changed = True
            used.add(current)
            next_number = max(next_number, current + 1)
        if self._positive_int(canvas.get("nextNodeNumber"), 0) != next_number:
            canvas["nextNodeNumber"] = next_number
            changed = True
        return changed

    @staticmethod
    def _positive_int(value: Any, default: int = 0) -> int:
        if isinstance(value, bool):
            return default
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    def _allocate_display_number(self, canvas: dict[str, Any]) -> int:
        number = self._positive_int(canvas.get("nextNodeNumber"), 1)
        used = {self._positive_int(node.get("displayNumber"), 0) for node in canvas.get("nodes", [])}
        while number in used:
            number += 1
        canvas["nextNodeNumber"] = number + 1
        return number

    def _new_id(self, canvas: dict[str, Any], prefix: str) -> str:
        used = {str(node.get("id")) for node in canvas.get("nodes", [])}
        while True:
            value = f"{prefix}_{uuid.uuid4().hex}"
            if value not in used:
                return value

    def _find_node(self, canvas: dict[str, Any], args: Mapping[str, Any], *, required: bool = True) -> dict[str, Any] | None:
        node_id_present = "node_id" in args
        number_present = "node_number" in args
        by_id = None
        by_number = None
        if node_id_present:
            requested_id = args.get("node_id")
            by_id = next((node for node in canvas["nodes"] if node.get("id") == requested_id), None)
        if number_present:
            number = self._positive_int(args.get("node_number"), 0)
            if not number:
                raise HeadlessCanvasError("node_number 必须是正整数")
            by_number = next((node for node in canvas["nodes"] if node.get("displayNumber") == number), None)
        if node_id_present and number_present and (by_id is None or by_number is None or by_id is not by_number):
            raise HeadlessCanvasError("node_id 与 node_number 指向不同节点")
        node = by_id or by_number
        if node is None and required:
            if node_id_present:
                raise HeadlessCanvasError(f"节点不存在：{args.get('node_id')}")
            raise HeadlessCanvasError(f"节点编号不存在：{args.get('node_number')}")
        return node

    def _find_node_id(self, canvas: dict[str, Any], value: Any) -> dict[str, Any]:
        node = next((item for item in canvas["nodes"] if item.get("id") == value), None)
        if node is None:
            raise HeadlessCanvasError(f"节点不存在：{value}")
        return node

    def _execute_sync(self, canvas: dict[str, Any], action: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if action == "create_node":
            return self._create_node(canvas, args)
        if action == "update_node":
            return self._update_node(canvas, args)
        if action == "duplicate_node":
            return self._duplicate_node(canvas, args)
        if action == "group_nodes":
            return self._group_nodes(canvas, args)
        if action == "connect":
            return self._connect(canvas, args)
        if action == "disconnect":
            return self._disconnect(canvas, args)
        if action == "delete_node":
            return self._delete_node(canvas, args)
        if action == "arrange":
            return self._arrange(canvas, args)
        if action == "snapshot":
            return {"canvas": copy.deepcopy(canvas)}
        if action == "production_status":
            return {"rows": self._production_rows(canvas)}
        raise HeadlessCanvasError(f"Unsupported action: {action}")

    async def _run_node(self, canvas: dict[str, Any], args: Mapping[str, Any], request_id: str) -> dict[str, Any]:
        with self.lock:
            node = self._find_node(canvas, args)
            if not self._is_execution(node):
                raise HeadlessCanvasError("请选择执行节点")
            self._reconcile(canvas)
            if node.get("creationOwnerNodeId") != node.get("id"):
                node["creationParentId"] = node.get("creationId")
                node["creationId"] = self._new_creation_id()
                node["creationOwnerNodeId"] = node["id"]
                node["creationRevision"] = self._positive_int(node.get("creationRevision"), 1) + 1

        value = self.submit_run(canvas, node, request_id)
        if inspect.isawaitable(value):
            value = await value
        task_ids, returned_tasks = self._task_result(value)
        tasks = returned_tasks or self._tasks_by_id(canvas, task_ids)
        return {
            "node_id": node["id"],
            "task_ids": task_ids,
            "tasks": tasks,
            "versions": copy.deepcopy(node.get("resultVersions") or []),
        }

    async def _cancel_run(self, canvas: dict[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        task_id = str(args.get("task_id") or args.get("node_id") or "").strip()
        if not task_id and "node_number" in args:
            task_id = str(self._find_node(canvas, args)["id"])
        if not task_id:
            raise HeadlessCanvasError("请提供 task_id 或 node_id")
        node = next(
            (
                candidate
                for candidate in canvas["nodes"]
                if any(str(task.get("id")) == task_id for task in candidate.get("creationTasks") or [])
            ),
            None,
        )
        if node is None:
            if "node_id" in args or "node_number" in args:
                node = self._find_node(canvas, args)
            else:
                node = self._find_node_id(canvas, task_id)
        value = self.cancel_run(canvas, node, task_id)
        if inspect.isawaitable(value):
            await value
        return {"cancelled": task_id}

    @staticmethod
    def _task_result(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
        returned_tasks: list[dict[str, Any]] = []
        if isinstance(value, Mapping):
            returned_tasks = [copy.deepcopy(item) for item in value.get("tasks") or [] if isinstance(item, dict)]
            value = value.get("task_ids", value.get("taskIds", []))
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple)):
            raise HeadlessCanvasError("submit_run 必须返回 task_ids 数组")
        task_ids = [str(item.get("id") if isinstance(item, dict) else item) for item in value]
        task_ids = [item for item in task_ids if item]
        return task_ids, returned_tasks

    @staticmethod
    def _tasks_by_id(canvas: dict[str, Any], task_ids: list[str]) -> list[dict[str, Any]]:
        by_id = {
            str(task.get("id")): task
            for node in canvas.get("nodes") or []
            for task in node.get("creationTasks") or []
            if isinstance(task, dict) and task.get("id") is not None
        }
        return [copy.deepcopy(by_id[task_id]) for task_id in task_ids if task_id in by_id]

    def _create_node(self, canvas: dict[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        kind = str(args.get("kind") or "").strip()
        if kind == "hypit_output":
            return self._create_hypit_output(canvas, args)

        title = str(args.get("title") or "").strip()
        if not title:
            raise HeadlessCanvasError("请提供有实际意义的节点名称 title")
        node_type = self.NODE_TYPES.get(kind)
        if not node_type:
            raise HeadlessCanvasError("kind 必须为 material/text/image/video/audio/music/app/comfy/hypit_output")

        node_id = self._new_id(canvas, "material" if kind == "material" else "run")
        x = self._number(args.get("x", 0), "x")
        y = self._number(args.get("y", 0), "y")
        node = {
            "id": node_id,
            "type": node_type,
            "x": x,
            "y": y,
            "title": title[:160],
            "displayNumber": self._allocate_display_number(canvas),
            "created_at": int(time.time() * 1000),
        }

        needs_configuration = False
        if kind == "material":
            items = args.get("media", [])
            if "text" in args:
                text = str(args.get("text") or "")
                items = [{"kind": "text", "text": text, "content": text, "name": title}]
            if not isinstance(items, list):
                raise HeadlessCanvasError("media must be an array")
            node["sourceKind"] = str(args.get("source_kind") or args.get("sourceKind") or "input")
            node["images"] = copy.deepcopy(items)
            if len(items) > 1:
                node["title"] = title[:160] or "素材组"
                node["scale"] = 0.8
            elif len(items) == 1:
                node["w"] = 316
                node["h"] = 194
                node["mediaSizeMode"] = "auto"
            self._ensure_creation(node)
            configure_args = dict(args)
            configure_args.pop("text", None)
            self._configure_node(canvas, node, configure_args)
        else:
            node.update(
                {
                    "w": 316,
                    "h": 194,
                    "outputKind": self.OUTPUT_KINDS[node_type],
                    "images": [],
                    "promptDraftHtml": "",
                    "promptDraftText": "",
                    "runSettings": self._base_run_settings(kind),
                }
            )
            self._ensure_creation(node)
            effective = dict(args)
            defaults = ((canvas.get("settings") or {}).get("agentDefaults") or {}).get(kind) or {}
            if not isinstance(defaults, Mapping):
                defaults = {}
            if kind in self.MODEL_FIELDS:
                provider = effective.get("provider_id", defaults.get("provider_id"))
                model = effective.get("model", defaults.get("model"))
                if not provider and not model and args.get("defer_configuration"):
                    needs_configuration = True
                    effective.pop("provider_id", None)
                    effective.pop("model", None)
                    effective.pop("parameters", None)
                else:
                    if not provider or not model:
                        raise HeadlessCanvasError("请先设置此类节点默认模型，或明确提供平台和模型")
                    effective["provider_id"] = provider
                    effective["model"] = model
                    default_parameters = defaults.get("parameters") or {}
                    explicit_parameters = effective.get("parameters")
                    if explicit_parameters is not None and not isinstance(explicit_parameters, Mapping):
                        raise HeadlessCanvasError("parameters 必须是对象")
                    changed_model = provider != defaults.get("provider_id") or model != defaults.get("model")
                    merged = {} if changed_model else copy.deepcopy(dict(default_parameters))
                    merged.update(copy.deepcopy(dict(explicit_parameters or {})))
                    effective["parameters"] = merged
            else:
                default_settings = defaults.get("run_settings") or {}
                explicit_settings = effective.get("run_settings") or {}
                if not isinstance(default_settings, Mapping) or not isinstance(explicit_settings, Mapping):
                    raise HeadlessCanvasError("run_settings 必须是对象")
                effective["run_settings"] = {**copy.deepcopy(dict(default_settings)), **copy.deepcopy(dict(explicit_settings))}
            self._configure_node(canvas, node, effective)

        canvas["nodes"].append(node)
        self._reconcile(canvas)
        result = {"node_id": node_id, "node": copy.deepcopy(node)}
        if needs_configuration:
            result["needs_configuration"] = True
        return result

    def _create_hypit_output(self, canvas: dict[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        if not self._is_hypit_settings_canvas(canvas):
            raise HeadlessCanvasError("Hypit 输出端口只能创建在 Hypit 配置图中")
        slot = str(args.get("slot") or args.get("hypitSlot") or "").strip().lower()
        if slot not in HYPIT_OUTPUT_SLOTS:
            raise HeadlessCanvasError("Hypit 输出用途必须是 text/image/video/audio/music/voice")
        existing = next((node for node in canvas.get("nodes", [])
                         if isinstance(node, dict)
                         and node.get("type") == "smart-hypit-output"
                         and str(node.get("hypitSlot") or "").strip().lower() == slot), None)
        if existing is not None:
            return {
                "node_id": str(existing["id"]),
                "node": copy.deepcopy(existing),
                "existing": True,
                "focus": True,
            }

        titles = {
            "text": "文本输出", "image": "图片输出", "video": "视频输出",
            "audio": "音频输出", "music": "音乐输出", "voice": "语音输出",
        }
        index = HYPIT_OUTPUT_SLOTS.index(slot)
        node = {
            "id": self._new_id(canvas, f"hypit-output-{slot}"),
            "type": "smart-hypit-output",
            "hypitSlot": slot,
            "outputKind": HYPIT_OUTPUT_KINDS[slot],
            "x": self._number(args.get("x", 720), "x"),
            "y": self._number(args.get("y", index * 205), "y"),
            "w": 300,
            "h": 150,
            "title": str(args.get("title") or titles[slot])[:160],
            "images": [],
            "displayNumber": self._allocate_display_number(canvas),
            "created_at": int(time.time() * 1000),
        }
        canvas.setdefault("nodes", []).append(node)
        try:
            validate_hypit_settings_canvas(canvas)
        except (TypeError, ValueError) as exc:
            raise HeadlessCanvasError(str(exc)) from exc
        return {"node_id": node["id"], "node": copy.deepcopy(node), "existing": False}

    def _base_run_settings(self, kind: str) -> dict[str, Any]:
        settings: dict[str, Any] = {"engine": "api", "apiKind": kind, "capabilityParameters": {}}
        if kind in self.MODEL_FIELDS:
            provider_key, model_key, family_key, _ = self.MODEL_FIELDS[kind]
            settings.update({provider_key: "", model_key: "", family_key: ""})
            if kind == "image":
                settings["count"] = 1
        elif kind == "app":
            settings.update({"engine": "runninghub", "apiKind": "image", "rhMode": "app"})
        elif kind == "comfy":
            settings.update({"engine": "comfy", "apiKind": "image", "comfyMode": "custom"})
        return settings

    def _update_node(self, canvas: dict[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        node = self._find_node(canvas, args)
        self._ensure_creation(node)
        self._check_expected_revision(node, args)
        backup = copy.deepcopy(node)
        try:
            self._configure_node(canvas, node, args)
            self._reconcile(canvas)
        except Exception:
            node.clear()
            node.update(backup)
            raise
        return {"node_id": node["id"], "node": copy.deepcopy(node)}

    def _configure_node(self, canvas: dict[str, Any], node: dict[str, Any], args: Mapping[str, Any]) -> None:
        lock_keys = [key for key in ("hypitInputLocked", "hypit_input_locked") if key in args]
        if lock_keys:
            if not self._is_hypit_settings_canvas(canvas):
                raise HeadlessCanvasError("hypitInputLocked 仅适用于 Hypit 配置图")
            if not self._is_material(node):
                raise HeadlessCanvasError("只有 Hypit 输入素材可以设置 hypitInputLocked")
            values = [args[key] for key in lock_keys]
            if any(type(value) is not bool for value in values) or any(value != values[0] for value in values[1:]):
                raise HeadlessCanvasError("hypitInputLocked 必须是布尔值")
            node["hypitInputLocked"] = values[0]

        if "creation_details" in args:
            details = args.get("creation_details")
            if not isinstance(details, str):
                raise HeadlessCanvasError("创作说明请填写 Markdown 文本")
            node["creationDetails"] = details
            node["creationRevision"] = self._positive_int(node.get("creationRevision"), 1) + 1

        kind = self._kind_for_node(node)
        if any(key in args for key in ("provider_id", "model", "parameters")):
            if kind not in self.MODEL_FIELDS:
                raise HeadlessCanvasError("此节点请通过 run_settings 配置应用或工作流")
            self._configure_model(node, kind, args, canvas_id=str(canvas.get("id") or ""))

        if "run_settings" in args:
            if kind == "app":
                allowed = self.APP_RUN_SETTINGS
            elif kind == "comfy":
                allowed = self.COMFY_RUN_SETTINGS
            else:
                raise HeadlessCanvasError("普通模型使用 provider_id、model 和 parameters 配置")
            run_settings = args.get("run_settings")
            if not isinstance(run_settings, Mapping):
                raise HeadlessCanvasError("run_settings 必须是对象")
            unsupported = set(run_settings) - allowed
            if unsupported:
                raise HeadlessCanvasError(f"包含未支持的应用设置字段：{sorted(unsupported)}")
            node.setdefault("runSettings", {}).update(copy.deepcopy(dict(run_settings)))
            if kind == "app":
                node["runSettings"]["engine"] = "runninghub"
                node["runSettings"]["apiKind"] = "image"
            else:
                node["runSettings"]["engine"] = "comfy"
                node["runSettings"]["apiKind"] = "image"

        for key in ("x", "y", "w", "h"):
            if key not in args:
                continue
            value = self._number(args[key], key)
            if key in {"w", "h"} and value <= 0:
                raise HeadlessCanvasError(f"Invalid {key}")
            node[key] = value
        if "title" in args:
            node["title"] = str(args.get("title") or "")[:160]

        if "text" in args:
            text = str(args.get("text") or "")
            if self._is_material(node):
                images = node.get("images") or []
                if images and any(self._media_kind(item) != "text" for item in images):
                    raise HeadlessCanvasError("Only text material accepts text")
                if images:
                    node.setdefault("resultVersions", [self._snapshot(node, f"initial:{node['id']}")])
                    node["creationParentId"] = node.get("creationId")
                    node["creationId"] = self._new_creation_id()
                    node["creationOwnerNodeId"] = node["id"]
                node["images"] = [{"kind": "text", "text": text, "content": text, "name": node.get("title") or "正文.md"}]
                node.setdefault("resultVersions", [])
                node["resultVersions"].append(self._snapshot(node, self._new_id_for_version()))
                node["activeResultVersion"] = len(node["resultVersions"]) - 1
                node["creationRevision"] = self._positive_int(node.get("creationRevision"), 1) + 1
            elif self._is_execution(node):
                node["promptDraftText"] = text
                node["promptDraftHtml"] = html.escape(text, quote=True)
                node["promptDraftTouched"] = True

        if "production" in args:
            self._update_production(canvas, node, args.get("production"))

        if self._is_execution(node):
            node.setdefault("runSettings", {})
            self._normalize_run_settings(node)
        self._ensure_creation(node)

    def _configure_model(self, node: dict[str, Any], kind: str, args: Mapping[str, Any], *, canvas_id="") -> None:
        provider_key, model_key, family_key, api_kind = self.MODEL_FIELDS[kind]
        source = node.setdefault("runSettings", {})
        provider = args.get("provider_id", source.get(provider_key))
        model = args.get("model", source.get(model_key))
        provider = str(provider or "").strip()
        model = str(model or "").strip()
        if not provider or not model:
            raise HeadlessCanvasError("必须明确指定 provider_id 和 model，不能猜测模型")
        if "parameters" in args and args.get("parameters") is not None and not isinstance(args.get("parameters"), Mapping):
            raise HeadlessCanvasError("parameters 必须是对象")
        changed_model = source.get(provider_key) != provider or source.get(model_key) != model
        existing = {}
        if not changed_model:
            existing = copy.deepcopy((source.get("capabilityParameters") or {}).get(model) or {})
        requested = existing
        if "parameters" in args:
            requested.update(copy.deepcopy(dict(args.get("parameters") or {})))
        previous_selection = node.get("modelSelection") if isinstance(node.get("modelSelection"), dict) else {}
        option_id = str(args.get("option_id") or previous_selection.get("option_id") or "").strip()
        operation = str(args.get("operation") or previous_selection.get("operation") or "").strip()
        try:
            signature = inspect.signature(self.validate_model)
            accepts_extra = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
            kwargs = {}
            for key, value in (
                ("canvas_id", canvas_id), ("option_id", option_id), ("operation", operation),
                ("region", str(args.get("region") or source.get("rhRegion") or source.get("region") or "")),
            ):
                if accepts_extra or key in signature.parameters:
                    kwargs[key] = value
        except (TypeError, ValueError):
            kwargs = {}
        profile = self.validate_model(api_kind, provider, model, requested, **kwargs)
        if not isinstance(profile, Mapping):
            raise HeadlessCanvasError("模型能力档案无效")
        if not profile.get("runnable"):
            raise HeadlessCanvasError("模型未启用或适配不可用")
        profile_parameters = profile.get("parameters") or {}
        if not isinstance(profile_parameters, Mapping) or any(key not in profile_parameters for key in requested):
            unsupported = [key for key in requested if key not in profile_parameters]
            raise HeadlessCanvasError(f"模型不支持参数：{', '.join(map(str, unsupported))}")
        source[provider_key] = provider
        source[model_key] = model
        source[family_key] = str(profile.get("family_id") or profile.get("familyId") or "")
        if option_id:
            node["modelSelection"] = {
                "schema_version": 2,
                "option_id": option_id,
                "connection_id": provider,
                "region_id": str(args.get("region") or source.get("rhRegion") or source.get("region") or ""),
                "operation": str(profile.get("operation") or operation),
                "parameters": copy.deepcopy(requested),
                "revision": int(previous_selection.get("revision") or 0) + 1,
            }
        elif changed_model:
            node.pop("modelSelection", None)
        source.setdefault("capabilityParameters", {})[model] = requested
        if kind == "image" and "count" in requested:
            value = requested["count"]
            source["count"] = 1 if value == "__canvas_unset__" else value
        source["apiKind"] = "text" if kind == "text" else kind
        source["engine"] = "api"

    @staticmethod
    def _check_expected_revision(node: dict[str, Any], args: Mapping[str, Any]) -> None:
        if "expected_revision" not in args:
            return
        expected = args.get("expected_revision")
        actual = node.get("creationRevision")
        if expected != actual:
            raise HeadlessCanvasError("节点已修改，请重新读取再更新")

    @staticmethod
    def _number(value: Any, name: str) -> int | float:
        if isinstance(value, bool):
            raise HeadlessCanvasError(f"Invalid {name}")
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise HeadlessCanvasError(f"Invalid {name}") from None
        if not math.isfinite(value):
            raise HeadlessCanvasError(f"Invalid {name}")
        return int(value) if value.is_integer() else value

    def _duplicate_node(self, canvas: dict[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        source = self._find_node(canvas, args)
        copy_node = copy.deepcopy(source)
        copy_node["id"] = self._new_id(canvas, "run" if self._is_execution(source) else "material")
        copy_node["displayNumber"] = self._allocate_display_number(canvas)
        copy_node["x"] = self._number(source.get("x", 0), "x") + self._number(args.get("dx", 420), "dx")
        copy_node["y"] = self._number(source.get("y", 0), "y") + self._number(args.get("dy", 0), "dy")
        copy_node["running"] = False
        copy_node["pending"] = 0
        copy_node["queued"] = False
        for key in ("jimengPending", "pendingTasks", "_runMetaTargetId", "runStartedAt", "runFinishedAt", "runElapsedMs", "runTimerHidden"):
            copy_node.pop(key, None)
        copy_node.pop("creationTasks", None)
        if copy_node.get("production", {}).get("role") in {"script", "segment"}:
            copy_node["production"] = {"role": "none"}
        if args.get("title"):
            copy_node["title"] = str(args["title"])[:160]
        canvas["nodes"].append(copy_node)
        for connection in list(canvas.get("connections") or []):
            if connection.get("to") == source.get("id"):
                cloned = copy.deepcopy(connection)
                cloned["to"] = copy_node["id"]
                cloned["id"] = self._new_id_for_edge()
                canvas["connections"].append(cloned)
        self._reconcile(canvas)
        return {"node_id": copy_node["id"], "node": copy.deepcopy(copy_node)}

    def _group_nodes(self, canvas: dict[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        raw_ids = args.get("node_ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            raise HeadlessCanvasError("请提供 node_ids")
        members = [self._find_node_id(canvas, node_id) for node_id in raw_ids]
        title = str(args.get("title") or "").strip()
        if not title:
            raise HeadlessCanvasError("请提供有实际意义的分组名称")
        group = {
            "id": self._new_id(canvas, "group"),
            "type": "smart-group",
            "x": 0,
            "y": 0,
            "w": 340,
            "h": 286,
            "title": title[:160],
            "items": list(dict.fromkeys(node["id"] for node in members)),
            "displayNumber": self._allocate_display_number(canvas),
            "created_at": int(time.time() * 1000),
        }
        canvas["nodes"].append(group)
        self._fit_group(group, members)
        return {"node_id": group["id"], "node": copy.deepcopy(group)}

    def _connect(self, canvas: dict[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        source_id = args.get("from")
        target_id = args.get("to")
        source = self._find_node_id(canvas, source_id)
        target = self._find_node_id(canvas, target_id)
        if source["id"] == target["id"]:
            raise HeadlessCanvasError("Cannot connect a node to itself")

        source_is_output = source.get("type") == "smart-hypit-output"
        target_is_output = target.get("type") == "smart-hypit-output"
        if source_is_output:
            raise HeadlessCanvasError("Hypit 输出端口不能作为连线来源")

        relation = str(args.get("relation") or "").strip().lower()
        if relation == "story":
            if target_is_output:
                raise HeadlessCanvasError("Hypit 输出端口只接受生成流程连线")
            self._add_connection(canvas, source["id"], target["id"], "story")
            return {"connections": copy.deepcopy(canvas["connections"])}

        if target_is_output:
            if not self._is_hypit_settings_canvas(canvas):
                raise HeadlessCanvasError("Hypit 输出端口只能连接在 Hypit 配置图中")
            if not self._can_connect(source, target, hypit_settings=True):
                raise HeadlessCanvasError("Hypit 输出只能连接执行节点")
            kind = self._connection_kind(source, target)
            target_field_key = str(args.get("target_field_key") or args.get("targetFieldKey") or "").strip()
            candidate = copy.deepcopy(canvas)
            candidate["connections"] = [
                connection for connection in candidate.get("connections") or []
                if not (
                    connection.get("to") == target["id"]
                    and str(connection.get("kind") or "input").strip().lower() in {"", "input", "flow"}
                )
            ]
            self._check_cycle(candidate, source["id"], target["id"], kind)
            self._add_connection(
                candidate,
                source["id"],
                target["id"],
                kind,
                source_result_id=str(args.get("source_result_id") or args.get("sourceResultId") or "").strip(),
                source_media_key=str(args.get("source_media_key") or args.get("sourceMediaKey") or "").strip(),
                target_field_key=target_field_key,
            )
            try:
                validate_hypit_settings_canvas(candidate)
            except (TypeError, ValueError) as exc:
                raise HeadlessCanvasError(str(exc)) from exc
            canvas["connections"] = candidate["connections"]
            self._reconcile(canvas)
            return {"connections": copy.deepcopy(canvas["connections"])}

        if not self._can_connect(source, target):
            raise HeadlessCanvasError("Incompatible connection")
        kind = self._connection_kind(source, target)
        self._check_cycle(canvas, source["id"], target["id"], kind)
        target_field_key = str(args.get("target_field_key") or args.get("targetFieldKey") or "").strip()
        if target.get("type") == "smart-ai-app":
            if not self._is_hypit_settings_canvas(canvas):
                target_field_key = self._resolve_app_field(canvas, source, target, target_field_key, args)
            # Hypit 配置图不靠 Schema 猜测用途或自动绑定字段。明确给出的 key
            # 原样保留；未指定时先保留来源连线，必填与格式在执行预检时核对。
        self._add_connection(
            canvas,
            source["id"],
            target["id"],
            kind,
            source_result_id=str(args.get("source_result_id") or args.get("sourceResultId") or "").strip(),
            source_media_key=str(args.get("source_media_key") or args.get("sourceMediaKey") or "").strip(),
            target_field_key=target_field_key,
        )
        if kind in {"input", "flow"}:
            target["inputNodeIds"] = list(dict.fromkeys([*(target.get("inputNodeIds") or []), source["id"]]))
        self._reconcile(canvas)
        return {"connections": copy.deepcopy(canvas["connections"])}

    def _resolve_app_field(
        self,
        canvas: dict[str, Any],
        source: dict[str, Any],
        target: dict[str, Any],
        requested: str,
        args: Mapping[str, Any],
    ) -> str:
        fields = self._official_app_fields(target)
        if not fields:
            raise HeadlessCanvasError("AI 应用缺少官方输入字段，不能猜测 target_field_key")
        source_kind = self._source_kind_for_connection(canvas, source, args)
        matching = [field for field in fields if self._field_kind(field) == source_kind]
        keys = {self._field_key(field): field for field in fields if self._field_key(field)}
        if requested:
            field = keys.get(requested)
            if field is None or self._field_kind(field) != source_kind:
                raise HeadlessCanvasError("target_field_key 不是该 AI 应用的官方输入字段")
            return requested
        occupied = {
            str(connection.get("targetFieldKey") or connection.get("target_field_key") or "").strip()
            for connection in canvas.get("connections") or []
            if connection.get("to") == target.get("id")
        }
        available = [self._field_key(field) for field in matching if self._field_key(field) not in occupied]
        if len(available) == 1:
            return available[0]
        raise HeadlessCanvasError("请提供官方字段 target_field_key（nodeId::fieldName）")

    @staticmethod
    def _official_app_fields(node: dict[str, Any]) -> list[dict[str, Any]]:
        settings = node.get("runSettings") or {}
        for key in ("rhFields", "rhSchemaSnapshot"):
            fields = settings.get(key)
            if isinstance(fields, list) and fields:
                return [field for field in fields if isinstance(field, dict)]
        return []

    @staticmethod
    def _field_key(field: Mapping[str, Any]) -> str:
        if field.get("key"):
            return str(field["key"])
        return f"{field.get('nodeId', '')}::{field.get('fieldName', '')}"

    @staticmethod
    def _field_kind(field: Mapping[str, Any]) -> str:
        raw = str(field.get("fieldType") or field.get("type") or field.get("kind") or "").strip().lower()
        if raw in {"string", "text", "plain-text"}:
            return "text"
        if raw in {"image", "video", "audio"}:
            return raw
        return ""

    def _disconnect(self, canvas: dict[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        source = self._find_node(canvas, {"node_id": args.get("from")})
        target = self._find_node(canvas, {"node_id": args.get("to")})
        relation = str(args.get("relation") or "").strip().lower()
        removed = []
        kept = []
        for connection in canvas.get("connections") or []:
            same_endpoints = connection.get("from") == source["id"] and connection.get("to") == target["id"]
            is_story = connection.get("kind", "flow") == "story"
            matches = same_endpoints and (is_story if relation == "story" else not is_story)
            if matches:
                removed.append(connection)
            else:
                kept.append(connection)
        canvas["connections"] = kept
        if removed:
            target["inputNodeIds"] = [
                value
                for value in target.get("inputNodeIds") or []
                if not any(item.get("kind", "flow") in {"input", "flow"} and item.get("from") == value for item in removed)
            ]
            self._reconcile(canvas)
        return {"removed": len(removed)}

    def _delete_node(self, canvas: dict[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        node = self._find_node(canvas, args)
        if node.get("running") or node.get("pending"):
            raise HeadlessCanvasError("请先停止运行再删除")
        if any(task.get("runStatus") not in self.TERMINAL_TASK_STATES for task in node.get("creationTasks") or []):
            raise HeadlessCanvasError("请先停止运行再删除")
        delete_ids = {node["id"]}
        delete_ids.update(
            candidate["id"]
            for candidate in canvas["nodes"]
            if candidate.get("historyFor") == node["id"]
        )
        canvas["nodes"] = [candidate for candidate in canvas["nodes"] if candidate.get("id") not in delete_ids]
        canvas["connections"] = [
            connection
            for connection in canvas.get("connections") or []
            if connection.get("from") not in delete_ids and connection.get("to") not in delete_ids
        ]
        for candidate in canvas["nodes"]:
            candidate["inputNodeIds"] = [
                value for value in candidate.get("inputNodeIds") or [] if value not in delete_ids
            ]
            if candidate.get("type") == "smart-group":
                candidate["items"] = [value for value in candidate.get("items") or [] if value not in delete_ids]
        return {"deleted": node["id"]}

    def _arrange(self, canvas: dict[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        raw_ids = args.get("node_ids")
        if raw_ids is None:
            requested_ids = [node["id"] for node in canvas["nodes"]]
        else:
            if not isinstance(raw_ids, list):
                raise HeadlessCanvasError("node_ids 必须是数组")
            requested_ids = [self._find_node_id(canvas, node_id)["id"] for node_id in raw_ids]
        requested_ids = list(dict.fromkeys(requested_ids))
        selected_ids = set(requested_ids)
        replacements = {}
        for group in canvas["nodes"]:
            if group.get("type") != "smart-group":
                continue
            members = set(group.get("items") or [])
            if not members.intersection(selected_ids):
                continue
            selected_ids.difference_update(members)
            selected_ids.add(group["id"])
            for member_id in members:
                replacements[member_id] = group["id"]
        nodes = []
        for node_id in requested_ids:
            replacement = replacements.get(node_id, node_id)
            if replacement in selected_ids and replacement not in nodes:
                nodes.append(replacement)
        for node in canvas["nodes"]:
            if node.get("id") in selected_ids and node.get("id") not in nodes:
                nodes.append(node["id"])
        selected = [self._find_node_id(canvas, node_id) for node_id in nodes]
        columns = max(1, int(math.ceil(math.sqrt(len(selected)))))
        base_x = min((float(node.get("x") or 0) for node in selected), default=0)
        base_y = min((float(node.get("y") or 0) for node in selected), default=0)
        for index, node in enumerate(selected):
            target_x = base_x + (index % columns) * 360
            target_y = base_y + (index // columns) * 240
            self._move_node(canvas, node, target_x - float(node.get("x") or 0), target_y - float(node.get("y") or 0))
        return {"node_ids": nodes}

    def _move_node(self, canvas: dict[str, Any], node: dict[str, Any], dx: float, dy: float, seen: set[str] | None = None) -> None:
        seen = seen or set()
        if node.get("id") in seen:
            return
        seen.add(node.get("id"))
        node["x"] = round(float(node.get("x") or 0) + dx)
        node["y"] = round(float(node.get("y") or 0) + dy)
        if node.get("type") == "smart-group":
            for member_id in node.get("items") or []:
                member = next((candidate for candidate in canvas["nodes"] if candidate.get("id") == member_id), None)
                if member:
                    self._move_node(canvas, member, dx, dy, seen)

    @staticmethod
    def _fit_group(group: dict[str, Any], members: list[dict[str, Any]]) -> None:
        if not members:
            return
        left = min(float(member.get("x") or 0) for member in members)
        top = min(float(member.get("y") or 0) for member in members)
        right = max(float(member.get("x") or 0) + float(member.get("w") or 316) for member in members)
        bottom = max(float(member.get("y") or 0) + float(member.get("h") or 194) for member in members)
        group["x"] = round(left - 18)
        group["y"] = round(top - 44 - 18)
        group["w"] = max(150, round(right - left + 36))
        group["h"] = max(130, round(bottom - top + 36 + 44))

    def _can_connect(self, source: dict[str, Any], target: dict[str, Any], *, hypit_settings: bool = False) -> bool:
        if source.get("type") == "smart-hypit-output":
            return False
        if target.get("type") == "smart-hypit-output":
            return hypit_settings and self._is_execution(source)
        if target.get("type") in {"smart-group", "smart-result-group"}:
            return False
        source_type = source.get("type")
        target_type = target.get("type")
        if self._is_material(source):
            return self._is_material(target) or self._is_execution(target) or target_type in {
                "smart-prompt",
                "smart-loop",
                "smart-minimax",
                "smart-video-director",
                "smart-minimax-director",
            }
        if self._is_execution(source):
            return self._is_material(target) or self._is_execution(target) or target_type in {
                "smart-angle-control",
                "smart-image-compare",
                "smart-loop",
            }
        if source_type in {"smart-angle-control", "smart-image-compare"}:
            return self._is_material(target) and bool(self._node_text(target) or not target.get("images"))
        if source_type == "smart-result-group":
            return self._is_execution(target) or target_type == "smart-loop"
        if source_type in {"smart-prompt", "smart-loop", "smart-group"}:
            return self._is_execution(target) or target_type in {"smart-loop", "smart-material"}
        return False

    @staticmethod
    def _is_hypit_settings_canvas(canvas: Mapping[str, Any]) -> bool:
        return str(canvas.get("id") or "") == HYPIT_SETTINGS_CANVAS_ID

    @staticmethod
    def _connection_kind(source: dict[str, Any], target: dict[str, Any]) -> str:
        if HeadlessCanvas._is_execution(source) and HeadlessCanvas._is_material(target) and target.get("isRunPlaceholder"):
            return "result"
        if source.get("type") in {"smart-angle-control", "smart-image-compare"} and HeadlessCanvas._is_material(target) and HeadlessCanvas._node_text(target):
            return "result"
        return "input"

    @staticmethod
    def _add_connection(
        canvas: dict[str, Any],
        source_id: Any,
        target_id: Any,
        kind: str,
        *,
        source_result_id: str = "",
        source_media_key: str = "",
        target_field_key: str = "",
    ) -> bool:
        candidate = {
            "from": source_id,
            "to": target_id,
            "kind": kind,
        }
        if source_result_id:
            candidate["sourceResultId"] = source_result_id
        if source_media_key:
            candidate["sourceMediaKey"] = source_media_key
        if target_field_key:
            candidate["targetFieldKey"] = target_field_key
        for existing in canvas.get("connections") or []:
            if (
                existing.get("from") == source_id
                and existing.get("to") == target_id
                and existing.get("kind", "flow") == kind
                and str(existing.get("sourceResultId") or existing.get("source_result_id") or "") == source_result_id
                and str(existing.get("sourceMediaKey") or existing.get("source_media_key") or "") == source_media_key
                and str(existing.get("targetFieldKey") or existing.get("target_field_key") or "") == target_field_key
            ):
                return False
        canvas.setdefault("connections", []).append(candidate)
        return True

    @staticmethod
    def _check_cycle(canvas: dict[str, Any], source_id: Any, target_id: Any, kind: str) -> None:
        if kind not in {"input", "flow"}:
            return
        graph: dict[Any, set[Any]] = {}
        for connection in canvas.get("connections") or []:
            if connection.get("kind", "flow") not in {"input", "flow"}:
                continue
            graph.setdefault(connection.get("from"), set()).add(connection.get("to"))
        graph.setdefault(source_id, set()).add(target_id)
        pending = [target_id]
        seen = set()
        while pending:
            current = pending.pop()
            if current == source_id:
                raise HeadlessCanvasError("不能创建循环连线")
            if current in seen:
                continue
            seen.add(current)
            pending.extend(graph.get(current, ()))

    @staticmethod
    def _is_material(node: Mapping[str, Any]) -> bool:
        return node.get("type") in HeadlessCanvas.MATERIAL_TYPES

    @staticmethod
    def _is_execution(node: Mapping[str, Any]) -> bool:
        return node.get("type") in HeadlessCanvas.EXECUTION_TYPES

    def _kind_for_node(self, node: Mapping[str, Any]) -> str:
        node_type = node.get("type")
        if node_type in self.MATERIAL_TYPES:
            return "material"
        for kind, value in self.NODE_TYPES.items():
            if value == node_type:
                return kind
        return ""

    def _source_kind_for_connection(self, canvas: dict[str, Any], node: dict[str, Any], args: Mapping[str, Any]) -> str:
        if self._is_execution(node):
            output = self.OUTPUT_KINDS.get(node.get("type"), "")
            items = node.get("images") or []
            source_result_id = str(args.get("source_result_id") or args.get("sourceResultId") or "").strip()
            if source_result_id:
                items = [
                    item
                    for item in items
                    if str(item.get("resultId") or item.get("result_id") or "") == source_result_id
                ]
                if not items:
                    raise HeadlessCanvasError("source_result_id 不属于来源节点")
            source_key = str(args.get("source_media_key") or args.get("sourceMediaKey") or "").strip()
            if source_key:
                for index, item in enumerate(items):
                    if self._media_reference_key(item, node.get("id"), index) == source_key:
                        return self._media_kind(item)
                raise HeadlessCanvasError("source_media_key 不属于来源节点")
            if len(items) > 1:
                raise HeadlessCanvasError("多个素材必须明确 source_media_key")
            kinds = {self._media_kind(item) for item in items if self._media_kind(item)}
            if len(kinds) == 1:
                return next(iter(kinds))
            if len(kinds) > 1:
                raise HeadlessCanvasError("多个素材必须明确 source_media_key")
            if output == "text" and str(node.get("promptDraftText") or "").strip():
                return "text"
            return ""
        if node.get("type") in {"smart-group", "smart-result-group"}:
            member_ids = [
                item.get("nodeId") if isinstance(item, Mapping) else item
                for item in (node.get("items") or [])
            ]
            members = [
                candidate
                for candidate in canvas.get("nodes") or []
                if candidate.get("id") in member_ids
            ]
            kinds = {self._source_kind_for_connection(canvas, member, args) for member in members}
            kinds.discard("")
            if len(kinds) == 1:
                return next(iter(kinds))
            if len(kinds) > 1:
                raise HeadlessCanvasError("多个素材必须明确 source_media_key")
            return ""
        items = node.get("images") or []
        source_result_id = str(args.get("source_result_id") or args.get("sourceResultId") or "").strip()
        if source_result_id:
            items = [
                item
                for item in items
                if str(item.get("resultId") or item.get("result_id") or "") == source_result_id
            ]
            if not items:
                raise HeadlessCanvasError("source_result_id 不属于来源节点")
        source_key = str(args.get("source_media_key") or args.get("sourceMediaKey") or "").strip()
        if source_key:
            for index, item in enumerate(items):
                candidate = self._media_reference_key(item, node.get("id"), index)
                if candidate == source_key:
                    return self._media_kind(item)
            raise HeadlessCanvasError("source_media_key 不属于来源节点")
        if len(items) > 1:
            raise HeadlessCanvasError("多个素材必须明确 source_media_key")
        kinds = {self._media_kind(item) for item in items if self._media_kind(item)}
        if len(kinds) == 1:
            return next(iter(kinds))
        if not kinds and self._node_text(node):
            return "text"
        if len(kinds) > 1:
            raise HeadlessCanvasError("多个素材必须明确 source_media_key")
        return ""

    @classmethod
    def _media_reference_key(cls, item: Mapping[str, Any], node_id: Any, index: int) -> str:
        explicit = str(item.get("key") or "").strip()
        if explicit:
            return explicit
        result_id = str(item.get("resultId") or item.get("result_id") or "").strip()
        if result_id:
            return f"result:{result_id}"
        item_node_id = str(item.get("nodeId") or item.get("node_id") or node_id or "").strip()
        image_index = item.get("imageIndex", item.get("image_index", index))
        if item_node_id:
            return f"node:{item_node_id}:{image_index}"
        material_id = str(item.get("materialId") or item.get("material_id") or item.get("assetId") or item.get("asset_id") or "").strip()
        if material_id:
            return f"material:{material_id}"
        text = str(item.get("text") if item.get("text") is not None else item.get("content") or "").strip()
        if text:
            return f"text:{text}"
        return f"url:{item.get('url') or item.get('path') or item.get('src') or item.get('uri') or ''}"

    @staticmethod
    def _media_kind(item: Mapping[str, Any] | None) -> str:
        if not isinstance(item, Mapping):
            return ""
        explicit = str(
            item.get("kind")
            or item.get("mediaKind")
            or item.get("media_type")
            or item.get("mediaType")
            or item.get("type")
            or item.get("outputType")
            or ""
        ).lower()
        if explicit in {"image", "video", "audio", "text", "file"}:
            return explicit
        value = str(item.get("url") or item.get("path") or item.get("src") or item.get("uri") or "").lower().split("?")[0]
        if value.endswith((".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv")):
            return "video"
        if value.endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")):
            return "audio"
        if value.endswith((".txt", ".json", ".csv", ".srt", ".vtt", ".md")):
            return "text"
        return "image" if value else ""

    def _node_text(self, node: Mapping[str, Any]) -> str:
        return "\n\n".join(
            str(item.get("text") if item.get("text") is not None else item.get("content") or "")
            for item in node.get("images") or []
            if self._media_kind(item) == "text" and str(item.get("text") if item.get("text") is not None else item.get("content") or "")
        )

    @staticmethod
    def _normalize_run_settings(node: dict[str, Any]) -> None:
        settings = node.setdefault("runSettings", {})
        node_type = node.get("type")
        if node_type == "smart-text-generator":
            settings["apiKind"] = "text"
        elif node_type == "smart-image-generator":
            settings["apiKind"] = "image"
            for key in ("ratio", "resolution", "customRatio", "customRatioWidth", "customRatioHeight", "customSize", "customWidth", "customHeight", "capabilityAspectRatio"):
                settings.pop(key, None)
        elif node_type == "smart-video-generator":
            settings["apiKind"] = "video"
            for key in ("videoDuration", "videoAspect", "videoResolution", "videoEnhancePrompt", "videoEnableUpsample", "videoWatermark", "videoCameraFixed", "videoGenerateAudio"):
                settings.pop(key, None)
        elif node_type == "smart-audio-generator":
            settings.update({"engine": "api", "apiKind": "audio"})
        elif node_type == "smart-music-generator":
            settings.update({"engine": "api", "apiKind": "music"})
        elif node_type == "smart-ai-app":
            settings.update({"engine": "runninghub", "apiKind": "image"})
        elif node_type == "smart-comfy-workflow":
            settings.update({"engine": "comfy", "apiKind": "image", "comfyMode": "custom"})

    def _ensure_creation(self, node: dict[str, Any]) -> None:
        if not (self._is_material(node) or self._is_execution(node)):
            return
        node["creationDetails"] = self._details_markdown(node.get("creationDetails"))
        node.setdefault("creationId", self._new_creation_id())
        node.setdefault("creationOwnerNodeId", node.get("id"))
        node["creationRevision"] = self._positive_int(node.get("creationRevision"), 1)
        node.setdefault("creationSignature", self._stable(self._recipe(node)))

    def _reconcile(self, canvas: dict[str, Any]) -> None:
        nodes = canvas.get("nodes") or []
        for node in nodes:
            if not (self._is_material(node) or self._is_execution(node)):
                continue
            self._ensure_creation(node)
            first = "creationInputBinding" not in node
            node["creationInputBinding"] = [
                {
                    "source": next(
                        (
                            candidate.get("creationId") or connection.get("from")
                            for candidate in nodes
                            if candidate.get("id") == connection.get("from")
                        ),
                        connection.get("from"),
                    ),
                    "version": connection.get("sourceVersionId") or "",
                    "field": connection.get("targetFieldKey") or connection.get("target_field_key") or "",
                }
                for connection in canvas.get("connections") or []
                if connection.get("to") == node.get("id")
                and connection.get("kind", "flow") not in {"story", "history", "result"}
            ]
            signature = self._stable(self._recipe(node))
            if first:
                node["creationSignature"] = signature
            elif node.get("creationSignature") != signature:
                node["creationParentId"] = node.get("creationId")
                node["creationId"] = self._new_creation_id()
                node["creationOwnerNodeId"] = node.get("id")
                node["creationSignature"] = signature
                node["creationRevision"] = self._positive_int(node.get("creationRevision"), 1) + 1

    @staticmethod
    def _recipe(node: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "type": node.get("type"),
            "runSettings": copy.deepcopy(node.get("runSettings") or {}),
            "promptDraftText": node.get("promptDraftText") or "",
            "manualInputRefs": copy.deepcopy(node.get("manualInputRefs") or []),
            "blockedInputRefs": copy.deepcopy(node.get("blockedInputRefs") or []),
            "inputRefOrder": copy.deepcopy(node.get("inputRefOrder") or []),
            "creationInputBinding": copy.deepcopy(node.get("creationInputBinding") or []),
        }

    @staticmethod
    def _stable(value: Any) -> str:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _new_creation_id() -> str:
        return f"creation_{uuid.uuid4().hex}"

    @staticmethod
    def _new_id_for_version() -> str:
        return f"version_{uuid.uuid4().hex}"

    @staticmethod
    def _new_id_for_edge() -> str:
        return f"edge_{uuid.uuid4().hex}"

    def _snapshot(self, node: Mapping[str, Any], node_id: str) -> dict[str, Any]:
        recipe = self._recipe(node)
        return {
            **copy.deepcopy(recipe),
            "type": node.get("creationType") or node.get("type"),
            "id": node_id,
            "creationId": node.get("creationId"),
            "creationOwnerNodeId": node.get("creationOwnerNodeId"),
            "creationDetails": node.get("creationDetails") or "",
            "images": copy.deepcopy(node.get("images") or []),
            "outputKind": node.get("outputKind"),
            "title": node.get("title"),
            "runPrompt": node.get("runPrompt") or node.get("promptDraftText") or "",
            "runModelPrompt": node.get("runModelPrompt") or node.get("runPrompt") or node.get("promptDraftText") or "",
            "promptDraftHtml": node.get("promptDraftHtml") or "",
            "runInputRefs": copy.deepcopy(node.get("runInputRefs") or node.get("manualInputRefs") or []),
            "runPromptRefs": copy.deepcopy(node.get("runPromptRefs") or []),
            "runRef": copy.deepcopy(node.get("runRef")),
            "runSnapshot": copy.deepcopy(node.get("runSnapshot")),
            "createdAt": node.get("runFinishedAt") or node.get("created_at") or int(time.time() * 1000),
        }

    @classmethod
    def _details_markdown(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        if value is None:
            return ""
        labels = {
            "role": "用途",
            "episode": "集数",
            "scene": "场次",
            "segment_id": "分段编号",
            "source_node_id": "来源节点",
            "source_text": "来源正文",
            "duration": "预计秒数",
            "purpose": "本段作用",
            "direction": "讲戏说明",
            "assets": "资产",
            "start_state": "开始状态",
            "end_state": "结束状态",
            "background": "背景",
            "characters": "人物",
            "notation": "符号说明",
            "asset_category": "资产类别",
            "owner": "归属",
            "base_asset_node_id": "基础资产节点",
            "state": "状态",
            "notes": "补充说明",
            "name": "名称",
            "node_id": "节点",
        }

        def render(item: Any, depth: int = 0) -> str:
            indent = "  " * depth
            if isinstance(item, list):
                return "\n".join(
                    f"{indent}-\n{render(entry, depth + 1)}" if isinstance(entry, (dict, list)) else f"{indent}- {entry}"
                    for entry in item
                )
            if isinstance(item, dict):
                lines = []
                for key, child in item.items():
                    if child in (None, ""):
                        continue
                    label = labels.get(key, key)
                    if isinstance(child, (dict, list)):
                        lines.append(f"{indent}- **{label}**\n{render(child, depth + 1)}")
                    else:
                        lines.append(f"{indent}- **{label}**：{str(child).replace(chr(10), chr(10) + indent + '  ')}")
                return "\n".join(lines)
            return indent + str(item)

        return render(value)

    def _update_production(self, canvas: dict[str, Any], node: dict[str, Any], patch: Any) -> None:
        if not isinstance(patch, Mapping) or isinstance(patch, list):
            raise HeadlessCanvasError("production 必须是关联对象")
        unsupported = set(patch) - self.PRODUCTION_FIELDS
        if unsupported:
            raise HeadlessCanvasError(f"不支持的生产关联字段：{sorted(unsupported)}")
        value = {**copy.deepcopy(node.get("production") or {}), **copy.deepcopy(dict(patch))}
        role = value.get("role")
        if role not in {"script", "segment", "asset", "video", "none"}:
            raise HeadlessCanvasError("无效的生产角色")
        if role in {"script", "segment"} and self._node_kind_for_production(node) != "text":
            raise HeadlessCanvasError("剧本和分段须使用文本节点")
        if role == "segment":
            order = value.get("order")
            if isinstance(order, bool) or not isinstance(order, int) or order < 1:
                raise HeadlessCanvasError("分段序号须为正整数")
            if any(
                other.get("id") != node.get("id")
                and (other.get("production") or {}).get("role") == "segment"
                and (other.get("production") or {}).get("order") == order
                for other in canvas.get("nodes") or []
            ):
                raise HeadlessCanvasError("分段序号重复")

        for field, wanted in self.PRODUCTION_COLUMNS.items():
            if field not in patch:
                continue
            ids = patch.get(field)
            if not isinstance(ids, list):
                raise HeadlessCanvasError(f"{field} 须为节点 ID 数组")
            unique_ids = list(dict.fromkeys(ids))
            for node_id in unique_ids:
                target = self._find_node_id(canvas, node_id)
                if self._node_kind_for_production(target) != wanted:
                    raise HeadlessCanvasError(f"关联节点不存在或类型不符：{node_id}")
            for index in range(len(canvas.get("connections") or []) - 1, -1, -1):
                connection = canvas["connections"][index]
                if connection.get("kind") == "story" and connection.get("from") == node.get("id"):
                    target = next((item for item in canvas["nodes"] if item.get("id") == connection.get("to")), None)
                    if self._node_kind_for_production(target) == wanted:
                        canvas["connections"].pop(index)
            for node_id in unique_ids:
                self._add_connection(canvas, node["id"], node_id, "story")
            value.pop(field, None)

        source_id = value.get("sourceNodeId")
        if source_id:
            source = self._find_node_id(canvas, source_id)
            if source.get("id") == node.get("id") or self._node_kind_for_production(source) != "text":
                raise HeadlessCanvasError("来源剧本不存在")
            full = self._node_text(source)
            excerpt = self._node_text(node)
            if not excerpt or not full:
                raise HeadlessCanvasError("请先读取完整剧本与分段正文")
            if "sourceStart" not in value and "sourceEnd" not in value:
                start = full.find(excerpt)
                if start < 0 or full.find(excerpt, start + 1) >= 0:
                    raise HeadlessCanvasError("请提供能唯一定位原文的起止范围")
                value["sourceStart"] = len(full[:start])
                value["sourceEnd"] = value["sourceStart"] + len(excerpt)
            start = value.get("sourceStart")
            end = value.get("sourceEnd")
            if (
                isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end <= start
                or end > len(full)
                or full[start:end] != excerpt
            ):
                raise HeadlessCanvasError("分段必须与选取的剧本原文一致，不得改写")
        node["production"] = value
        node["creationRevision"] = self._positive_int(node.get("creationRevision"), 1) + 1

    def _node_kind_for_production(self, node: Mapping[str, Any] | None) -> str:
        if not node:
            return ""
        if self._is_material(node):
            first = (node.get("images") or [None])[0]
            return self._media_kind(first) or str(node.get("outputKind") or "")
        return self.OUTPUT_KINDS.get(node.get("type"), "")

    def _production_rows(self, canvas: dict[str, Any]) -> list[dict[str, Any]]:
        by_id = {node.get("id"): node for node in canvas.get("nodes") or []}
        rows = []
        segments = [
            node
            for node in canvas.get("nodes") or []
            if (node.get("production") or {}).get("role") == "segment"
        ]
        segments.sort(key=lambda node: (int((node.get("production") or {}).get("order") or 0), str(node.get("id"))))
        for segment in segments:
            spec = segment.get("production") or {}
            source = by_id.get(spec.get("sourceNodeId"))
            source_status = "unlinked"
            if source:
                full = self._node_text(source)
                excerpt = self._node_text(segment)
                source_status = "current" if full and full[spec.get("sourceStart", 0):spec.get("sourceEnd", 0)] == excerpt else "changed"
            elif spec.get("sourceNodeId"):
                source_status = "missing"
            related = {"image": [], "audio": [], "video": []}
            for connection in canvas.get("connections") or []:
                if connection.get("kind") != "story" or connection.get("from") != segment.get("id"):
                    continue
                target = by_id.get(connection.get("to"))
                kind = self._node_kind_for_production(target)
                if kind in related:
                    related[kind].append(self._production_summary(target))
            rows.append(
                {
                    "number": spec.get("order"),
                    "script": self._production_summary(segment),
                    "sourceStatus": source_status,
                    "images": related["image"],
                    "audio": related["audio"],
                    "videos": related["video"],
                }
            )
        return rows

    def _production_summary(self, node: Mapping[str, Any] | None) -> dict[str, Any]:
        if not node:
            return {"id": "", "title": "", "kind": "", "status": "not_generated", "media": None, "error": "", "creationId": ""}
        media = (node.get("images") or [None])[0]
        active = next(
            (
                task
                for task in node.get("creationTasks") or []
                if task.get("runStatus") not in self.TERMINAL_TASK_STATES
            ),
            None,
        )
        last = (node.get("creationTasks") or [])[-1] if node.get("creationTasks") else None
        if active or node.get("pending") or node.get("running"):
            status = "running"
        elif last and last.get("runStatus") == "failed":
            status = "failed"
        elif media and (media.get("url") or self._media_kind(media) == "text"):
            status = "ready"
        else:
            status = "not_generated"
        return {
            "id": node.get("id"),
            "title": node.get("title") or (media or {}).get("name") or node.get("id"),
            "kind": self._node_kind_for_production(node),
            "status": status,
            "media": copy.deepcopy(media),
            "error": (last or {}).get("runError", "") if last and last.get("runStatus") == "failed" else "",
            "creationId": node.get("creationId") or "",
        }


__all__ = ["HeadlessCanvas", "HeadlessCanvasError"]
