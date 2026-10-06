"""Hypit 配置图的私有依赖闭包执行编排。"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import re
import threading
from collections.abc import Mapping
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException

from canvas_core.hypit_config import (
    HYPIT_OUTPUT_KINDS,
    HYPIT_SETTINGS_CANVAS_ID,
    SETTINGS_CANVAS_MODULES,
    plan_hypit_slot,
    prepare_hypit_task_canvas,
    verify_hypit_slot_results,
)
from project_storage import StorageError


_EXECUTABLE_NODE_TYPES = {
    "smart-text-generator", "smart-image-generator", "smart-video-generator",
    "smart-audio-generator", "smart-music-generator", "smart-ai-app", "smart-comfy-workflow",
}
_PASSIVE_NODE_TYPES = {
    "smart-material", "smart-image", "smart-prompt", "smart-hypit-output",
    "smart-group", "smart-result-group", "smart-angle-control", "smart-image-compare",
}
_STATIC_OUTPUT_KIND_BY_NODE = {
    "smart-text-generator": "text",
    "smart-image-generator": "image",
    "smart-video-generator": "video",
    "smart-audio-generator": "audio",
    "smart-music-generator": "audio",
}
_DYNAMIC_OUTPUT_NODE_TYPES = {"smart-ai-app", "smart-comfy-workflow"}
_PRIVATE_SNAPSHOT_DROP_KEYS = {
    "api_key", "authorization", "cookie", "credential", "password", "secret", "signature",
    "signed_url", "token", "access_token", "refresh_token", "workflow", "workflow_json",
    "workflow_definition", "workflow_graph", "raw_workflow", "raw_schema", "schema_json",
}
_PRIVATE_URL_KEYS = {"url", "src", "href", "path"}
_PRIVATE_QUERY_KEYS = {"api_key", "apikey", "auth", "authorization", "key", "password", "secret",
                       "signature", "signed", "token", "access_token", "refresh_token"}
_TRUSTED_CONTEXT_FIELDS = {
    "module_id", "project_id", "purpose", "slot", "accepted_revision", "source_hash",
    "client_operation_id",
}
_ARTICLE_PURPOSES = {"cover", "illustration", "knowledge"}


class HypitFlowRunner:
    """复用已注入的画布、预检、执行、结果收集与 ProjectStorage 服务。"""

    def __init__(
        self,
        load_canvas: Callable[[str], dict[str, Any]],
        storage: Any,
        prepare_node_request: Callable[..., Any],
        preflight_node: Callable[..., Any],
        execute_node: Callable[..., Any],
        collect_results: Callable[..., Any],
        notify: Callable[[str, str, str], Any],
        lock: Any,
        now_ms: Callable[[], int],
        publish_node_result: Callable[[Mapping[str, Any], Mapping[str, Any], list[dict[str, Any]], Mapping[str, Any]], Any] | None = None,
        *,
        canvas_id: str = HYPIT_SETTINGS_CANVAS_ID,
        module_id: str = "hypit",
    ):
        canvas_id = str(canvas_id or "").strip()
        module_id = str(module_id or "").strip()
        if SETTINGS_CANVAS_MODULES.get(canvas_id) != module_id:
            raise ValueError("设置流程 runner 的画布 ID 与模块不匹配")
        self.load_canvas = load_canvas
        self.storage = storage
        self.prepare_node_request = prepare_node_request
        self.preflight_node = preflight_node
        self.execute_node = execute_node
        self.collect_results = collect_results
        self.notify = notify
        self.lock = lock
        self.now_ms = now_ms
        self.publish_node_result = publish_node_result
        self.canvas_id = canvas_id
        self.module_id = module_id
        self.flow_kind = f"{module_id}_settings_flow"
        self._active: dict[str, asyncio.Task] = {}
        self._active_guard = threading.RLock()

    @staticmethod
    def _canonical(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Hypit 测试请求必须是有效的 JSON 数据") from exc

    def _module_message(self, value: Any) -> str:
        """将共享流程内核的错误名称投影为当前模块的用户用语。"""
        text = str(value or "")
        if self.module_id == "hypit":
            return text
        replacements = (
            ("Hypit 测试请求", "文章生成请求"),
            ("Hypit 流程请求", "文章生成请求"),
            ("Hypit 执行快照", "文章生成执行快照"),
            ("Hypit 设置流程画布", "文章配置画布"),
            ("Hypit 设置流程", "文章配置流程"),
            ("Hypit 全链", "文章生成全链"),
            ("Hypit 参数", "文章生成参数"),
            ("Hypit 输入", "文章生成输入"),
            ("Hypit 引用", "文章生成引用"),
            ("Hypit 输出", "文章生成输出"),
            ("Hypit 节点", "文章生成节点"),
            ("Hypit 流程", "文章生成流程"),
            ("Hypit 配置", "文章配置"),
            ("Hypit", "文章生成"),
        )
        for old, new in replacements:
            text = text.replace(old, new)
        slot_names = {"text": "文本", "image": "图片", "video": "视频", "audio": "音频",
                      "music": "音乐", "voice": "语音"}
        text = re.sub(
            r"文章生成 (text|image|video|audio|music|voice)\b",
            lambda match: "文章生成" + slot_names[match.group(1)],
            text,
        )
        return text

    @classmethod
    def _request_payload(cls, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=400, detail="Hypit 流程请求必须是对象")
        nested = payload.get("request")
        source = nested if isinstance(nested, Mapping) else payload
        allowed = {
            "prompt", "system_prompt", "parameters", "inputs", "references",
            "prompt_target_node_id", "promptTargetNodeId",
        }
        request = {key: copy.deepcopy(source[key]) for key in allowed if key in source}
        if "parameters" in request and not isinstance(request["parameters"], Mapping):
            raise HTTPException(status_code=400, detail="Hypit 参数必须是对象")
        if "inputs" in request and not isinstance(request["inputs"], Mapping):
            raise HTTPException(status_code=400, detail="Hypit 输入必须是对象")
        if "references" in request and not isinstance(request["references"], list):
            raise HTTPException(status_code=400, detail="Hypit 引用必须是数组")
        cls._canonical(request)
        return request

    @classmethod
    def _safe_snapshot(cls, value: Any, *, field_name: str = "") -> Any:
        """持久化追溯所需的安全快照；剔除凭据、签名链接和原始工作流定义。"""
        if isinstance(value, Mapping):
            item_name = str(value.get("key") or value.get("name") or value.get("field_key") or value.get("field") or "")
            normalized_item = cls._snapshot_key(item_name)
            cleaned = {}
            for key, item in value.items():
                normalized = cls._snapshot_key(key)
                if normalized in _PRIVATE_SNAPSHOT_DROP_KEYS or normalized.endswith("_api_key"):
                    continue
                if normalized in {"default", "value", "options"} and normalized_item in _PRIVATE_SNAPSHOT_DROP_KEYS:
                    continue
                cleaned[str(key)] = cls._safe_snapshot(item, field_name=str(key))
            return cleaned
        if isinstance(value, (list, tuple)):
            return [cls._safe_snapshot(item, field_name=field_name) for item in value]
        normalized_field = cls._snapshot_key(field_name)
        if isinstance(value, str) and (normalized_field in _PRIVATE_URL_KEYS or normalized_field.endswith("_url")):
            try:
                parts = urlsplit(value)
                query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
                         if cls._snapshot_key(key) not in _PRIVATE_QUERY_KEYS]
                return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
            except ValueError:
                return value
        if isinstance(value, str) and value.lower().startswith(("bearer ", "basic ")):
            return "[已隐藏]"
        return value

    @staticmethod
    def _snapshot_key(value: Any) -> str:
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value or "").strip())
        return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

    @staticmethod
    def _fingerprint(value: Any) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _trusted_context(self, value: Any, *, slot: str, request_id: str) -> dict[str, Any]:
        """验证服务端文章绑定元数据；它不来自请求体，也不影响用户输入指纹。"""
        if value is None:
            if self.module_id == "article":
                raise HTTPException(status_code=400, detail="文章生成缺少受信关联信息")
            return {}
        if not isinstance(value, Mapping):
            raise HTTPException(status_code=400, detail="受信任务上下文格式无效")
        unknown = set(str(key) for key in value) - _TRUSTED_CONTEXT_FIELDS
        if unknown:
            raise HTTPException(status_code=400, detail="受信任务上下文包含未允许字段")
        context = copy.deepcopy(dict(value))
        if context.get("module_id") != self.module_id:
            raise HTTPException(status_code=400, detail="受信任务模块与配置图不匹配")
        if context.get("slot") != slot:
            raise HTTPException(status_code=400, detail="受信任务用途与输出端口不匹配")
        if context.get("client_operation_id") != request_id:
            raise HTTPException(status_code=400, detail="受信任务操作标识与本次请求不匹配")
        if self.module_id == "article":
            project_id = str(context.get("project_id") or "").strip()
            purpose = str(context.get("purpose") or "").strip()
            revision = context.get("accepted_revision")
            source_hash = str(context.get("source_hash") or "").strip().lower()
            if not project_id or len(project_id) > 160:
                raise HTTPException(status_code=400, detail="文章受信上下文缺少有效项目 ID")
            if purpose not in _ARTICLE_PURPOSES:
                raise HTTPException(status_code=400, detail="文章生成用途无效")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
                raise HTTPException(status_code=400, detail="文章受信上下文缺少有效修订号")
            if not re.fullmatch(r"[a-f0-9]{64}", source_hash):
                raise HTTPException(status_code=400, detail="文章受信上下文缺少有效来源指纹")
            context["project_id"] = project_id
            context["purpose"] = purpose
            context["source_hash"] = source_hash
        try:
            self._canonical(context)
        except HTTPException as exc:
            raise HTTPException(status_code=400, detail="受信任务上下文不能安全持久化") from exc
        safe = self._safe_snapshot(context)
        if safe != context:
            raise HTTPException(status_code=400, detail="受信任务上下文包含敏感信息")
        return context

    @staticmethod
    async def _await(value: Any) -> Any:
        return await value if inspect.isawaitable(value) else value

    @staticmethod
    def _attempt(run: Mapping[str, Any]) -> dict[str, Any]:
        attempts = run.get("attempts") if isinstance(run.get("attempts"), list) else []
        return dict(attempts[-1]) if attempts and isinstance(attempts[-1], Mapping) else {}

    def _find_operation(self, output_node_id: str, request_id: str) -> dict[str, Any] | None:
        for run in self.storage.list_runs(canvas_id=self.canvas_id, node_id=output_node_id):
            if str(run.get("client_operation_id") or "") == request_id:
                return dict(run)
        return None

    def _saved_trusted_context(self, run: Mapping[str, Any]) -> dict[str, Any]:
        task = self.storage.get_canvas_task(str(run.get("run_id") or "")) or {}
        private = task.get("private_snapshot") if isinstance(task.get("private_snapshot"), Mapping) else {}
        run_snapshot = run.get("capability_snapshot") if isinstance(run.get("capability_snapshot"), Mapping) else {}
        value = private.get("trusted_context") if isinstance(private.get("trusted_context"), Mapping) else None
        if not isinstance(value, Mapping):
            value = run_snapshot.get("trusted_context") if isinstance(run_snapshot.get("trusted_context"), Mapping) else {}
        return copy.deepcopy(dict(value))

    def _ensure_same_operation_context(self, run: Mapping[str, Any], context: Mapping[str, Any]) -> None:
        old_module = str((run.get("capability_snapshot") or {}).get("module_id") or "hypit")
        if old_module != self.module_id or self._saved_trusted_context(run) != dict(context):
            raise HTTPException(status_code=409, detail="同一操作 ID 已绑定到不同的模块或文章版本")

    def _active_task(self, run_id: str) -> bool:
        with self._active_guard:
            task = self._active.get(run_id)
            return bool(task and not task.done())

    def _submission_response(self, run: Mapping[str, Any], slot: str, output_node_id: str) -> dict[str, Any]:
        attempt = self._attempt(run)
        run_id = str(run.get("run_id") or "")
        status = str(attempt.get("status") or "validated")
        task = self.storage.get_canvas_task(run_id)
        if task:
            status = str(task.get("status") or status)
            if status in {"queued", "running"} and not self._active_task(run_id):
                status = "recoverable"
        if status == "validated" and task is None:
            status = "validated"
        snapshot = run.get("capability_snapshot") if isinstance(run.get("capability_snapshot"), Mapping) else {}
        response = {
            "run_id": run_id,
            "status": status,
            "slot": slot,
            "output_node_id": output_node_id,
            "recipe_fingerprint": str(snapshot.get("recipe_fingerprint") or ""),
        }
        if self.module_id == "hypit":
            response["poll_url"] = f"/api/hypit/settings-canvas/test/{run_id}"
        return response

    @staticmethod
    def _provider_pending(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        status = str(value.get("status") or value.get("state") or "").strip().lower()
        pending = bool(value.get("pending") or value.get("jimeng_pending") or status in {
            "pending", "jimeng_pending", "queued", "submitted", "processing", "running", "recoverable",
        })
        if not pending:
            return None
        nested = value.get("jimeng_pending") if isinstance(value.get("jimeng_pending"), Mapping) else {}
        provider_task_id = next((str(value.get(key) or "").strip() for key in (
            "provider_task_id", "providerTaskId", "task_id", "taskId", "submit_id", "submitId", "id",
        ) if str(value.get(key) or "").strip()), "") or next((str(nested.get(key) or "").strip() for key in (
            "provider_task_id", "providerTaskId", "task_id", "taskId", "submit_id", "submitId", "id",
        ) if str(nested.get(key) or "").strip()), "")
        return {"provider_task_id": provider_task_id, "status": status or "pending"}

    @staticmethod
    def _preflight_output_kind(node: Mapping[str, Any]) -> str:
        """预检只声明静态生成器类型；动态来源必须等执行后读取真实结果。"""
        node_type = str(node.get("type") or "")
        if node_type in _DYNAMIC_OUTPUT_NODE_TYPES:
            return "dynamic"
        return _STATIC_OUTPUT_KIND_BY_NODE.get(node_type, "dynamic")

    @staticmethod
    def _group_member_ids(node: Mapping[str, Any]) -> list[str]:
        members = []
        for item in node.get("items") or []:
            if isinstance(item, Mapping):
                node_id = str(item.get("nodeId") or item.get("node_id") or "").strip()
            else:
                node_id = str(item or "").strip()
            if node_id and node_id not in members:
                members.append(node_id)
        return members

    @classmethod
    def _execution_dependencies(cls, plan: Mapping[str, Any], nodes: Mapping[str, Mapping[str, Any]],
                                execution_nodes: list[Mapping[str, Any]]) -> dict[str, list[str]]:
        executable_ids = {str(node.get("id") or "") for node in execution_nodes}
        parents: dict[str, list[str]] = {}
        dependency_edges = [*plan.get("connections", []), *plan.get("member_dependencies", [])]
        for edge in dependency_edges:
            if not isinstance(edge, Mapping) or str(edge.get("kind") or "input").lower() in {"story", "history"}:
                continue
            source_id = str(edge.get("from", edge.get("source", "")) or "")
            target_id = str(edge.get("to", edge.get("target", "")) or "")
            if source_id and target_id:
                parents.setdefault(target_id, []).append(source_id)
        dependencies: dict[str, list[str]] = {}
        for target in execution_nodes:
            target_id = str(target.get("id") or "")
            found: list[str] = []
            visited: set[str] = set()
            pending = list(parents.get(target_id, []))
            while pending:
                source_id = pending.pop()
                if source_id in visited:
                    continue
                visited.add(source_id)
                if source_id in executable_ids:
                    if source_id not in found:
                        found.append(source_id)
                    continue
                source = nodes.get(source_id)
                if not isinstance(source, Mapping):
                    continue
                if source.get("type") in {"smart-group", "smart-result-group"}:
                    for member_id in cls._group_member_ids(source):
                        if member_id in executable_ids and member_id not in found:
                            found.append(member_id)
                        elif member_id in nodes:
                            pending.extend(parents.get(member_id, []))
                pending.extend(parents.get(source_id, []))
            dependencies[target_id] = found
        return dependencies

    @staticmethod
    def _set_private_node_output(node: dict[str, Any], media: list[dict[str, Any]], kind: str) -> None:
        node["images"] = copy.deepcopy(media)
        node["outputKind"] = kind
        node["sourceKind"] = "result"

    def _accepted_snapshot(self, canvas: Mapping[str, Any], task_canvas: Mapping[str, Any], plan: Mapping[str, Any],
                           execution_nodes: list[Mapping[str, Any]], request: Mapping[str, Any],
                           prepared_requests: Mapping[str, Any], resolved_nodes: Mapping[str, Any],
                           trusted_context: Mapping[str, Any]) -> dict[str, Any]:
        relevant_ids = set(str(value) for value in plan.get("node_ids") or [])
        safe_canvas = {
            "id": str(canvas.get("id") or self.canvas_id),
            "revision": max(1, int(canvas.get("revision") or 1)),
            "nodes": [copy.deepcopy(node) for node in task_canvas.get("nodes", [])
                      if isinstance(node, Mapping) and str(node.get("id") or "") in relevant_ids],
            "connections": [copy.deepcopy(edge) for edge in plan.get("connections", []) if isinstance(edge, Mapping)],
        }
        safe = self._safe_snapshot({
            "module_id": self.module_id,
            "trusted_context": copy.deepcopy(dict(trusted_context)),
            "accepted_revision": safe_canvas["revision"],
            "slot": plan.get("slot"),
            "output_node_id": str((plan.get("output_node") or {}).get("id") or ""),
            "recipe_fingerprint": plan.get("recipe_fingerprint"),
            "canvas": safe_canvas,
            "request": copy.deepcopy(dict(request)),
            "steps": [{
                "node_id": str(node.get("id") or ""),
                "type": str(node.get("type") or ""),
                "request": copy.deepcopy(prepared_requests.get(str(node.get("id") or ""))),
                "resolved": copy.deepcopy(resolved_nodes.get(str(node.get("id") or ""))),
            } for node in execution_nodes],
        })
        try:
            return json.loads(self._canonical(safe))
        except HTTPException as exc:
            raise HTTPException(status_code=422, detail="Hypit 执行快照不能安全持久化") from exc

    async def submit(
        self,
        slot: str,
        output_node_id: str,
        request_id: str,
        payload: Mapping[str, Any],
        test: bool = False,
        *,
        trusted_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """先完整预检，再把一次流程作为持久任务排入后台执行。"""
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=400, detail=self._module_message("Hypit 流程请求必须是对象"))
        slot = str(slot or "").strip().lower()
        output_node_id = str(output_node_id or "").strip()
        request_id = str(request_id or payload.get("client_operation_id") or "").strip()
        if slot not in HYPIT_OUTPUT_KINDS:
            raise HTTPException(status_code=400, detail=self._module_message("Hypit 输出用途不受支持"))
        if not output_node_id:
            raise HTTPException(status_code=400, detail=self._module_message("缺少 Hypit 输出节点 ID"))
        if not request_id or len(request_id) > 160:
            raise HTTPException(status_code=400, detail="缺少有效的 client_operation_id")
        try:
            request = self._request_payload(payload)
        except HTTPException as exc:
            raise HTTPException(status_code=exc.status_code, detail=self._module_message(exc.detail)) from exc
        payload_fingerprint = self._fingerprint(request)
        trusted = self._trusted_context(trusted_context, slot=slot, request_id=request_id)
        # 目标用途是服务端路由上下文，不是调用方输入；在用户输入指纹完成后
        # 写入私有请求，供每个执行节点的预检和运行使用。
        request["_hypit_requested_slot"] = slot
        request["_hypit_output_node_id"] = output_node_id

        with self.lock:
            prior = self._find_operation(output_node_id, request_id)
            if prior:
                old_standard = prior.get("standard_request") if isinstance(prior.get("standard_request"), Mapping) else {}
                if (old_standard.get("input_fingerprint") != payload_fingerprint
                        or old_standard.get("slot") != slot
                        or bool(old_standard.get("test")) != bool(test)):
                    raise HTTPException(status_code=409, detail="同一操作 ID 已用于不同的输入或参数")
                self._ensure_same_operation_context(prior, trusted)
                task = self.storage.get_canvas_task(str(prior.get("run_id") or ""))
                if task or self._attempt(prior).get("status") != "validated":
                    return self._submission_response(prior, slot, output_node_id)

        canvas = self.load_canvas(self.canvas_id)
        if not isinstance(canvas, dict) or canvas.get("id") != self.canvas_id:
            raise HTTPException(status_code=404, detail="设置流程配置图不存在")
        base_revision = payload.get("base_revision")
        if base_revision is not None:
            if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision <= 0:
                raise HTTPException(status_code=400, detail="base_revision 必须是大于零的整数")
            if base_revision != max(1, int(canvas.get("revision") or 1)):
                raise HTTPException(status_code=409, detail={
                    "message": "设置流程配置图已更新，请重新读取后重试。",
                    "canvas": copy.deepcopy(canvas),
                    "revision": max(1, int(canvas.get("revision") or 1)),
                })
        try:
            prepared = prepare_hypit_task_canvas(
                canvas, slot, request, output_node_id,
                canvas_id=self.canvas_id, module_id=self.module_id,
            )
            task_canvas = prepared["canvas"]
            plan = prepared["plan"]
            recipe_fingerprint = str(prepared["recipe_fingerprint"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=self._module_message(exc)) from exc

        task_nodes = {str(node.get("id") or ""): node for node in task_canvas.get("nodes", []) if isinstance(node, dict)}
        original_nodes = {str(node.get("id") or ""): node for node in canvas.get("nodes", []) if isinstance(node, dict)}
        ordered_nodes = [task_nodes[node_id] for node_id in plan.get("node_ids", []) if node_id in task_nodes]
        if any(str(node.get("type") or "") == "smart-loop" for node in ordered_nodes):
            raise HTTPException(status_code=422, detail=self._module_message("Hypit 配置暂不支持多轮 Loop；请先改为明确的单轮依赖流程"))
        if any(str(node.get("type") or "") == "smart-image-compare" for node in ordered_nodes):
            raise HTTPException(status_code=422, detail=self._module_message("图像对比节点只用于查看结果，不能作为 Hypit 生成输入步骤"))
        unsupported = [str(node.get("type") or "(未知节点)") for node in ordered_nodes
                       if str(node.get("type") or "") not in (_EXECUTABLE_NODE_TYPES | _PASSIVE_NODE_TYPES)]
        if unsupported:
            raise HTTPException(status_code=422, detail=self._module_message("Hypit 流程包含暂不支持的步骤：" + ", ".join(dict.fromkeys(unsupported))))
        execution_nodes = [node for node in ordered_nodes if str(node.get("type") or "") in _EXECUTABLE_NODE_TYPES]
        if not execution_nodes:
            raise HTTPException(status_code=400, detail=self._module_message(f"Hypit {slot} 流程没有可执行节点"))

        upstream_ids = self._execution_dependencies(plan, task_nodes, execution_nodes)

        expected_kind = HYPIT_OUTPUT_KINDS[slot]
        prepared_requests: dict[str, Any] = {}
        resolved_nodes: dict[str, Any] = {}
        preflight_steps = []
        preflight_canvas = copy.deepcopy(task_canvas)
        preflight_nodes = {str(node.get("id") or ""): node for node in preflight_canvas.get("nodes", [])
                           if isinstance(node, dict)}
        try:
            for node in execution_nodes:
                node_id = str(node["id"])
                preflight_node = preflight_nodes.get(node_id, node)
                placeholders = {}
                for source_id in upstream_ids.get(node_id, []):
                    source = preflight_nodes[source_id]
                    kind = self._preflight_output_kind(source)
                    placeholders[source_id] = {"kind": kind, "upstream_node_id": source_id, "placeholder": True}
                prepared_request = await self._await(self.prepare_node_request(
                    preflight_canvas, preflight_node, request_id, placeholders, request, preflight=True,
                ))
                resolved = await self._await(self.preflight_node(preflight_canvas, preflight_node, prepared_request, request_id))
                prepared_requests[node_id] = prepared_request
                resolved_nodes[node_id] = resolved
                preflight_steps.append({"node_id": node_id, "type": str(node.get("type") or "")})
                preflight_node["images"] = [{
                    "kind": self._preflight_output_kind(preflight_node),
                    "upstream_node_id": node_id,
                    "placeholder": True,
                }]
                preflight_node["outputKind"] = preflight_node["images"][0]["kind"]
                preflight_node["sourceKind"] = "result"
        except HTTPException:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=f"Hypit 全链预检失败：{exc}") from exc

        # 预检可能读取远端 Schema；在接受请求前确认整链仍对应本次看到的修订与配方。
        latest = self.load_canvas(self.canvas_id)
        try:
            latest_plan = plan_hypit_slot(
                latest, slot, output_node_id, canvas_id=self.canvas_id, module_id=self.module_id,
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=409, detail=self._module_message("设置流程在预检期间已变化，请重新读取后重试")) from exc
        if (
            max(1, int(latest.get("revision") or 1)) != max(1, int(canvas.get("revision") or 1))
            or latest_plan.get("recipe_fingerprint") != recipe_fingerprint
        ):
            raise HTTPException(status_code=409, detail={
                "message": "设置流程在预检期间已变化，请重新读取后重试。",
                "canvas": copy.deepcopy(latest),
                "revision": max(1, int(latest.get("revision") or 1)),
            })

        request_identity = {
            "module_id": self.module_id,
            "slot": slot,
            "output_node_id": output_node_id,
            "recipe_fingerprint": recipe_fingerprint,
            "input_fingerprint": payload_fingerprint,
            "base_revision": max(1, int(canvas.get("revision") or 1)),
            "hypit_flow_test": bool(test),
        }
        step_summary = [{"node_id": str(node["id"]), "type": str(node.get("type") or "")} for node in execution_nodes]
        try:
            with self.lock:
                prior = self._find_operation(output_node_id, request_id)
                if prior:
                    old_standard = prior.get("standard_request") if isinstance(prior.get("standard_request"), Mapping) else {}
                    if (old_standard.get("input_fingerprint") != payload_fingerprint
                            or old_standard.get("recipe_fingerprint") != recipe_fingerprint
                            or old_standard.get("slot") != slot
                            or bool(old_standard.get("test")) != bool(test)):
                        raise HTTPException(status_code=409, detail="同一操作 ID 已用于不同的输入、参数或配置")
                    self._ensure_same_operation_context(prior, trusted)
                    existing_task = self.storage.get_canvas_task(str(prior.get("run_id") or ""))
                    if existing_task or self._attempt(prior).get("status") != "validated":
                        return self._submission_response(prior, slot, output_node_id)

                try:
                    accepted_snapshot = self._accepted_snapshot(
                        canvas, task_canvas, plan, execution_nodes, request,
                        prepared_requests, resolved_nodes, trusted,
                    )
                except HTTPException as exc:
                    raise HTTPException(status_code=exc.status_code, detail=self._module_message(exc.detail)) from exc
                run = self.storage.prepare_run(
                    canvas_id=self.canvas_id,
                    node_id=output_node_id,
                    client_operation_id=request_id,
                    standard_request={
                        "node_type": self.flow_kind,
                        "module_id": self.module_id,
                        "slot": slot,
                        "output_node_id": output_node_id,
                        "recipe_fingerprint": recipe_fingerprint,
                        "input_fingerprint": payload_fingerprint,
                        "expected_kind": expected_kind,
                        "base_revision": request_identity["base_revision"],
                        "test": bool(test),
                    },
                    platform_request={
                        "kind": self.flow_kind,
                        "module_id": self.module_id,
                        "steps": step_summary,
                        "test": bool(test),
                    },
                    capability_snapshot={
                        "node_type": self.flow_kind,
                        "module_id": self.module_id,
                        "trusted_context": copy.deepcopy(trusted),
                        "hypit_output_test": bool(test),
                        "hypit_slot": slot,
                        "output_node_id": output_node_id,
                        "recipe_fingerprint": recipe_fingerprint,
                        "output_kind": expected_kind,
                        "step_count": len(execution_nodes),
                    },
                )
                run_id = str(run.get("run_id") or "")
                existing_task = self.storage.get_canvas_task(run_id)
                if existing_task:
                    return self._submission_response(run, slot, output_node_id)
                attempt_status = str(self._attempt(run).get("status") or "validated")
                if attempt_status != "validated":
                    return self._submission_response(run, slot, output_node_id)

                task_result = {
                    "module_id": self.module_id,
                    "slot": slot,
                    "output_node_id": output_node_id,
                    "recipe_fingerprint": recipe_fingerprint,
                    "input_fingerprint": payload_fingerprint,
                    "expected_kind": expected_kind,
                    "output_kind": "",
                    "test": bool(test),
                    "steps": [{"node_id": item["node_id"], "type": item["type"], "status": "queued"} for item in preflight_steps],
                    "media": [],
                    "result_ids": [],
                    "error_category": "",
                    "error": "",
                }
                self.storage.create_canvas_task({
                    "id": run_id,
                    "canvas_id": self.canvas_id,
                    "module_id": self.module_id,
                    "node_id": output_node_id,
                    "kind": self.flow_kind,
                    "status": "queued",
                    "request": request_identity,
                    "private_snapshot": accepted_snapshot,
                    "result": task_result,
                })
                self.storage.update_run_status(run_id, "queued")
                task = asyncio.create_task(self._execute(
                    run_id,
                    slot,
                    output_node_id,
                    request_id,
                    bool(test),
                    copy.deepcopy(canvas),
                    task_canvas,
                    plan,
                    execution_nodes,
                    upstream_ids,
                    prepared_requests,
                    resolved_nodes,
                    request,
                    expected_kind,
                ))
                with self._active_guard:
                    self._active[run_id] = task
                task.add_done_callback(lambda done, key=run_id: self._forget_task(key, done))
        except StorageError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        response = {
            "run_id": run_id,
            "status": "queued",
            "slot": slot,
            "output_node_id": output_node_id,
            "recipe_fingerprint": recipe_fingerprint,
        }
        if self.module_id == "hypit":
            response["poll_url"] = f"/api/hypit/settings-canvas/test/{run_id}"
        return response

    def _forget_task(self, run_id: str, task: asyncio.Task) -> None:
        try:
            task.exception()
        except (asyncio.CancelledError, Exception):
            pass
        with self._active_guard:
            if self._active.get(run_id) is task:
                self._active.pop(run_id, None)

    def _save_task_result(self, run_id: str, result: dict[str, Any], *, status: str | None = None, error: str = "") -> None:
        changes: dict[str, Any] = {"result": self._safe_snapshot(result)}
        if status:
            changes["status"] = status
        if error:
            changes["error"] = error
        self.storage.update_canvas_task(run_id, **changes)

    def _safe_error(self, value: Any) -> str:
        text = str(value or "执行失败").replace("\x00", " ").strip()
        text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [隐藏]", text)
        text = re.sub(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|authorization)(\s*[:=]\s*)[^\s,;]+", r"\1\2[隐藏]", text)
        return self._module_message(text[:1000] or "执行失败")

    def _mark_submitted(self, run_id: str, provider_task_id: str = "") -> None:
        run = self.storage.get_run(run_id)
        if not run:
            raise StorageError("Hypit 流程运行记录不存在")
        current = str(self._attempt(run).get("status") or "validated")
        if current == "queued":
            self.storage.update_run_status(run_id, "submitted", provider_task_id=provider_task_id)
        elif current == "submitted" and provider_task_id:
            self.storage.update_run_status(run_id, "submitted", provider_task_id=provider_task_id)

    def _set_step(self, run_id: str, node_id: str, *, status: str, media: list[dict[str, Any]] | None = None,
                  error_category: str = "", error: str = "", provider_task_id: str = "") -> None:
        task = self.storage.get_canvas_task(run_id)
        if not task:
            return
        result = copy.deepcopy(task.get("result") if isinstance(task.get("result"), dict) else {})
        for step in result.get("steps") or []:
            if str(step.get("node_id") or "") != node_id:
                continue
            step["status"] = status
            if media is not None:
                step["media"] = copy.deepcopy(media)
            if error_category:
                step["error_category"] = error_category
            if error:
                step["error"] = error
            if provider_task_id:
                step["provider_task_id"] = provider_task_id
            step["updated_at"] = int(self.now_ms())
            break
        task_status = "running" if status in {"running", "succeeded"} else "recoverable" if status == "recoverable" else None
        self._save_task_result(run_id, result, status=task_status, error=error if status == "recoverable" else "")
        if provider_task_id:
            self.storage.update_canvas_task(run_id, upstream_task_id=provider_task_id)

    @staticmethod
    def _upstream_values(node_id: str, upstream_ids: Mapping[str, list[str]], collected: Mapping[str, list[dict[str, Any]]],
                         task_nodes: Mapping[str, Mapping[str, Any]], placeholders: bool) -> dict[str, Any]:
        values = {}
        for source_id in upstream_ids.get(node_id, []):
            if placeholders:
                source = task_nodes[source_id]
                kind = HypitFlowRunner._preflight_output_kind(source)
                values[source_id] = {"kind": kind, "upstream_node_id": source_id, "placeholder": True}
            else:
                values[source_id] = copy.deepcopy(collected.get(source_id) or [])
        return values

    @staticmethod
    def _media_refs(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            items = value
        elif isinstance(value, Mapping):
            if value.get("kind") or value.get("media_type"):
                items = [value]
            else:
                items = []
                for key in ("images", "videos", "audios", "texts", "files"):
                    group = value.get(key)
                    if isinstance(group, list):
                        items.extend(group)
                    elif group:
                        items.append(group)
        else:
            items = []
        return [copy.deepcopy(dict(item)) for item in items if isinstance(item, Mapping)]

    @staticmethod
    def _result_ids(media: list[Mapping[str, Any]]) -> list[str]:
        return list(dict.fromkeys(str(item.get("resultId") or item.get("result_id") or "").strip()
                                  for item in media if str(item.get("resultId") or item.get("result_id") or "").strip()))

    def _has_accessible_managed_result(self, item: Mapping[str, Any]) -> bool:
        """确认媒体结果由共享结果存储登记且文件仍可读取。"""
        result_id = str(item.get("resultId") or item.get("result_id") or "").strip()
        if not result_id:
            url = str(item.get("url") or "").strip()
            try:
                path = urlsplit(url).path
            except ValueError:
                path = ""
            prefix = "/api/results/"
            if path.startswith(prefix):
                result_id = path[len(prefix):].strip("/").split("/")[0]
        if not result_id:
            return False
        record = self.storage.get_result(result_id)
        if not isinstance(record, Mapping):
            return False
        path = self.storage.result_path(result_id)
        if path is None or not path.is_file():
            return False
        item_kind = str(item.get("kind") or item.get("media_type") or "").strip().lower()
        stored_kind = str(record.get("kind") or "").strip().lower()
        return bool(item_kind and stored_kind == item_kind)

    def _usable_slot_result(self, item: Mapping[str, Any]) -> dict[str, Any] | None:
        kind = str(item.get("kind") or item.get("media_type") or "").strip().lower()
        if kind == "text" and str(item.get("text") or item.get("content") or "").strip():
            value = copy.deepcopy(dict(item))
            if self._has_accessible_managed_result(item):
                result_id = str(item.get("resultId") or item.get("result_id") or "").strip()
                value["url"] = self.storage.result_url(result_id)
                value["resultId"] = result_id
            else:
                value.pop("url", None)
                value.pop("resultId", None)
                value.pop("result_id", None)
            return value
        if not self._has_accessible_managed_result(item):
            return None
        result_id = str(item.get("resultId") or item.get("result_id") or "").strip()
        record = self.storage.get_result(result_id) or {}
        value = copy.deepcopy(dict(item))
        value["url"] = self.storage.result_url(result_id)
        value["resultId"] = result_id
        value.setdefault("name", str(record.get("display_name") or ""))
        return value

    async def _notify(self, run_id: str, status: str) -> None:
        try:
            await self._await(self.notify(self.canvas_id, run_id, status))
        except Exception:
            # 广播失败不得重做或重复提交生成任务。
            return

    async def _execute(
        self,
        run_id: str,
        slot: str,
        output_node_id: str,
        request_id: str,
        test: bool,
        canvas_snapshot: dict[str, Any],
        task_canvas: dict[str, Any],
        plan: Mapping[str, Any],
        execution_nodes: list[dict[str, Any]],
        upstream_ids: Mapping[str, list[str]],
        preflight_requests: Mapping[str, Any],
        preflight_resolved: Mapping[str, Any],
        user_request: Mapping[str, Any],
        expected_kind: str,
    ) -> None:
        by_id = {str(node.get("id") or ""): node for node in task_canvas.get("nodes", []) if isinstance(node, dict)}
        original_by_id = {str(node.get("id") or ""): node for node in canvas_snapshot.get("nodes", []) if isinstance(node, dict)}
        collected: dict[str, list[dict[str, Any]]] = {}
        last_error_category = ""
        try:
            self.storage.update_canvas_task(run_id, status="running")
            await self._notify(run_id, "running")
            for node in execution_nodes:
                node_id = str(node.get("id") or "")
                self._set_step(run_id, node_id, status="running")
                actual_upstream = self._upstream_values(node_id, upstream_ids, collected, by_id, placeholders=False)
                try:
                    request = await self._await(self.prepare_node_request(
                        task_canvas, node, request_id, actual_upstream, user_request, preflight=False,
                    ))
                    resolved = await self._await(self.preflight_node(task_canvas, node, request, request_id))
                except Exception as exc:
                    last_error_category = "input_validation"
                    raise RuntimeError(f"节点 {node_id} 的运行时输入校验失败：{self._safe_error(getattr(exc, 'detail', exc))}") from exc

                def on_submitted(value: Any = "") -> None:
                    if isinstance(value, Mapping):
                        provider_task_id = str(value.get("provider_task_id") or value.get("task_id") or value.get("id") or "")
                    else:
                        provider_task_id = str(value or "")
                    self._mark_submitted(run_id, provider_task_id)
                    self._set_step(run_id, node_id, status="running", provider_task_id=provider_task_id)

                try:
                    raw = await self._await(self.execute_node(
                        task_canvas, node, request, request_id, resolved, on_submitted,
                    ))
                    pending = self._provider_pending(raw)
                    self._mark_submitted(run_id, pending["provider_task_id"] if pending else "")
                except Exception as exc:
                    last_error_category = "execution_failed"
                    raise RuntimeError(f"节点 {node_id} 执行失败：{self._safe_error(getattr(exc, 'detail', exc))}") from exc

                if pending:
                    provider_task_id = pending["provider_task_id"]
                    message = "上游仍在运行；已保留原任务标识，系统不会自动重新提交。"
                    self._set_step(
                        run_id, node_id, status="recoverable", error_category="upstream_pending",
                        error=message, provider_task_id=provider_task_id,
                    )
                    task_record = self.storage.get_canvas_task(run_id) or {}
                    result = copy.deepcopy(task_record.get("result") if isinstance(task_record.get("result"), dict) else {})
                    for item in result.get("steps") or []:
                        if str(item.get("node_id") or "") == node_id:
                            safe_response = {
                                "status": pending["status"],
                                "provider_task_id": provider_task_id,
                            }
                            if isinstance(raw, Mapping):
                                safe_response.update({
                                    "queue_info": raw.get("queue_info"),
                                    "message": raw.get("message"),
                                })
                            item["provider_response"] = self._safe_snapshot(safe_response)
                    result.update({
                        "error_category": "upstream_pending",
                        "error": message,
                        "provider_task_id": provider_task_id,
                    })
                    self._save_task_result(run_id, result, status="recoverable", error=message)
                    self.storage.update_run_status(run_id, "recoverable", provider_task_id=provider_task_id, error=message)
                    await self._notify(run_id, "recoverable")
                    return

                try:
                    collect_task = {
                        "id": run_id,
                        "creationId": run_id,
                        "title": str(node.get("title") or node.get("type") or self._module_message("Hypit 流程结果")),
                        "test": test,
                    }
                    media = self._media_refs(await self._await(self.collect_results(raw, request, collect_task)))
                    if not media:
                        raise ValueError("节点没有返回可收集的媒体结果")
                    ids = self._result_ids(media)
                    if ids:
                        self.storage.append_run_results(run_id, ids)
                    collected[node_id] = media
                    actual_kind = next((str(item.get("kind") or item.get("media_type") or "").strip().lower()
                                        for item in media if str(item.get("kind") or item.get("media_type") or "").strip()),
                                       self._preflight_output_kind(node))
                    self._set_private_node_output(node, media, actual_kind)
                    task_record = self.storage.get_canvas_task(run_id) or {}
                    result = copy.deepcopy(task_record.get("result") if isinstance(task_record.get("result"), dict) else {})
                    result["result_ids"] = list(dict.fromkeys([*(result.get("result_ids") or []), *ids]))
                    self._save_task_result(run_id, result)
                    self._set_step(run_id, node_id, status="succeeded", media=media)
                except Exception as exc:
                    last_error_category = "result_collection_failed"
                    raise RuntimeError(f"节点 {node_id} 结果收集失败：{self._safe_error(getattr(exc, 'detail', exc))}") from exc

            output_edge = next((edge for edge in plan.get("connections", [])
                                if isinstance(edge, Mapping)
                                and str(edge.get("to", edge.get("target", "")) or "") == output_node_id
                                and str(edge.get("kind") or "input") not in {"story", "history", "result"}), None)
            final_source_id = str((output_edge or {}).get("from", (output_edge or {}).get("source", "")) or "")
            try:
                final_media = verify_hypit_slot_results(slot, collected.get(final_source_id) or [])
            except (TypeError, ValueError) as exc:
                last_error_category = "output_mismatch"
                raise RuntimeError(str(exc)) from exc
            final_media = [usable for item in final_media
                           if (usable := self._usable_slot_result(item)) is not None]
            if not final_media:
                last_error_category = "output_unavailable"
                raise RuntimeError(self._module_message(f"Hypit {slot} 流程没有返回正文或可访问的受管结果"))

            task_record = self.storage.get_canvas_task(run_id) or {}
            result = copy.deepcopy(task_record.get("result") if isinstance(task_record.get("result"), dict) else {})
            result.update({"media": final_media, "output_kind": expected_kind, "error_category": "", "error": ""})
            self._save_task_result(run_id, result, status="succeeded")
            self.storage.update_run_status(run_id, "succeeded")
            if self.publish_node_result:
                source_node = original_by_id.get(final_source_id)
                if source_node:
                    try:
                        persisted_task = self.storage.get_canvas_task(run_id) or {}
                        private_snapshot = (persisted_task.get("private_snapshot")
                                            if isinstance(persisted_task.get("private_snapshot"), Mapping) else {})
                        trusted_context = (private_snapshot.get("trusted_context")
                                           if isinstance(private_snapshot.get("trusted_context"), Mapping) else {})
                        if not trusted_context:
                            persisted_run = self.storage.get_run(run_id) or {}
                            run_snapshot = (persisted_run.get("capability_snapshot")
                                            if isinstance(persisted_run.get("capability_snapshot"), Mapping) else {})
                            trusted_context = (run_snapshot.get("trusted_context")
                                               if isinstance(run_snapshot.get("trusted_context"), Mapping) else {})
                        await self._await(self.publish_node_result(
                            canvas_snapshot, source_node, copy.deepcopy(final_media),
                            {"run_id": run_id, "canvas_id": self.canvas_id, "module_id": self.module_id,
                             "slot": slot, "output_node_id": output_node_id,
                             "recipe_fingerprint": plan.get("recipe_fingerprint"), "test": test,
                             "status": "succeeded", "output_kind": expected_kind,
                             "media": copy.deepcopy(final_media),
                             "trusted_context": copy.deepcopy(dict(trusted_context))},
                        ))
                    except Exception:
                        # 失败只影响图内关联；已完成任务和结果仍可查询并供关联恢复使用。
                        pass
            await self._notify(run_id, "succeeded")
        except asyncio.CancelledError:
            message = "服务中断，保留原任务供查询；系统不会自动重新提交。"
            task_record = self.storage.get_canvas_task(run_id) or {}
            result = copy.deepcopy(task_record.get("result") if isinstance(task_record.get("result"), dict) else {})
            result.update({"error_category": "interrupted", "error": message})
            self._save_task_result(run_id, result, status="recoverable", error=message)
            run = self.storage.get_run(run_id)
            if run and self._attempt(run).get("status") in {"queued", "submitted", "processing"}:
                self.storage.update_run_status(run_id, "recoverable", error=message)
            await self._notify(run_id, "recoverable")
            raise
        except Exception as exc:
            error = self._safe_error(exc)
            if not last_error_category:
                last_error_category = "execution_failed"
            task_record = self.storage.get_canvas_task(run_id) or {}
            result = copy.deepcopy(task_record.get("result") if isinstance(task_record.get("result"), dict) else {})
            result.update({"error_category": last_error_category, "error": error})
            self._save_task_result(run_id, result, status="failed", error=error)
            run = self.storage.get_run(run_id)
            if run:
                current = str(self._attempt(run).get("status") or "validated")
                if current not in {"failed", "cancelled", "succeeded"}:
                    self.storage.update_run_status(run_id, "failed", error=error)
            await self._notify(run_id, "failed")

    def get(self, run_id: str) -> dict[str, Any] | None:
        """从 ProjectStorage 读取任务，不依赖 runner 进程内存。"""
        run_id = str(run_id or "").strip()
        if not run_id:
            return None
        run = self.storage.get_run(run_id)
        task = self.storage.get_canvas_task(run_id)
        if not run or not task or run.get("canvas_id") != self.canvas_id or task.get("canvas_id") != self.canvas_id:
            return None
        snapshot = run.get("capability_snapshot") if isinstance(run.get("capability_snapshot"), Mapping) else {}
        task_module = str(task.get("module_id") or snapshot.get("module_id") or "hypit")
        if task_module != self.module_id:
            return None
        task_result = task.get("result") if isinstance(task.get("result"), Mapping) else {}
        attempt = self._attempt(run)
        status = str(task.get("status") or attempt.get("status") or "recoverable")
        if status in {"queued", "running"} and not self._active_task(run_id):
            status = "recoverable"
        slot = str(snapshot.get("hypit_slot") or task_result.get("slot") or "")
        output_node_id = str(snapshot.get("output_node_id") or task_result.get("output_node_id") or "")
        fingerprint = str(snapshot.get("recipe_fingerprint") or task_result.get("recipe_fingerprint") or "")
        current_matches = False
        if slot and output_node_id and fingerprint:
            try:
                current_canvas = self.load_canvas(self.canvas_id)
                current_plan = plan_hypit_slot(
                    current_canvas, slot, output_node_id,
                    canvas_id=self.canvas_id, module_id=self.module_id,
                )
                current_matches = current_plan.get("recipe_fingerprint") == fingerprint
            except (HTTPException, TypeError, ValueError, KeyError, OSError):
                current_matches = False
        media = copy.deepcopy(task_result.get("media") if isinstance(task_result.get("media"), list) else [])
        result_ids = list(self._attempt(run).get("result_ids") or task_result.get("result_ids") or [])
        provider_task_id = str(attempt.get("provider_task_id") or task.get("upstream_task_id") or task.get("submit_id") or "")
        error = str(task_result.get("error") or attempt.get("error") or task.get("error") or "")
        private_snapshot = task.get("private_snapshot") if isinstance(task.get("private_snapshot"), Mapping) else {}
        trusted_context = private_snapshot.get("trusted_context") if isinstance(private_snapshot.get("trusted_context"), Mapping) else None
        if not isinstance(trusted_context, Mapping):
            trusted_context = snapshot.get("trusted_context") if isinstance(snapshot.get("trusted_context"), Mapping) else {}
        response = {
            "run_id": run_id,
            "status": status,
            "slot": slot,
            "output_node_id": output_node_id,
            "recipe_fingerprint": fingerprint,
            "current_recipe_matches": current_matches,
            "output_kind": str(task_result.get("output_kind") or ""),
            "result_ids": result_ids,
            "provider_task_id": provider_task_id,
            "media": self._safe_snapshot(media),
            "steps": self._safe_snapshot(copy.deepcopy(task_result.get("steps") or [])),
            "error_category": str(task_result.get("error_category") or ""),
            "error": self._safe_error(error) if error else "",
            "test": bool(snapshot.get("hypit_output_test")),
        }
        if self.module_id != "hypit":
            response.update({
                "canvas_id": self.canvas_id,
                "module_id": self.module_id,
                "trusted_context": self._safe_snapshot(copy.deepcopy(dict(trusted_context))),
            })
        return response
