"""Explicit text-optimization bridge for saved script/novel fields.

The bridge snapshots source from StudioManuscriptStore, submits through the
module's shared HypitFlowRunner, and applies only a verified managed text result.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from studio_hypit_flow import AsyncOperationLockRegistry
from studio_projects import StudioProjectConflict, StudioProjectError, StudioProjectNotFound


_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OptimizationPrompt(_StrictModel):
    prompt: StrictStr = Field(min_length=1, max_length=100_000)
    system_prompt: Optional[StrictStr] = Field(default=None, max_length=100_000)
    parameters: Optional[dict[str, Any]] = None
    prompt_target_node_id: Optional[StrictStr] = Field(default=None, max_length=160)
    field_inputs: Optional[list[dict[str, Any]]] = Field(default=None, max_length=64)


class ScriptGenerationRequest(_StrictModel):
    scope: Literal["scene", "segment", "episode_outline"]
    source_id: StrictStr = Field(min_length=1, max_length=128)
    expected_source_revision: StrictInt = Field(ge=0)
    expected_source_sha256: StrictStr = Field(max_length=64)
    output_node_id: StrictStr = Field(min_length=1, max_length=160)
    client_operation_id: StrictStr = Field(min_length=1, max_length=128, pattern=_ID.pattern)
    request: OptimizationPrompt
    base_revision: Optional[StrictInt] = Field(default=None, ge=1)


class NovelGenerationRequest(_StrictModel):
    scope: Literal["chapter", "chapter_outline"]
    source_id: StrictStr = Field(min_length=1, max_length=128)
    expected_source_revision: StrictInt = Field(ge=0)
    expected_source_sha256: StrictStr = Field(max_length=64)
    output_node_id: StrictStr = Field(min_length=1, max_length=160)
    client_operation_id: StrictStr = Field(min_length=1, max_length=128, pattern=_ID.pattern)
    request: OptimizationPrompt
    base_revision: Optional[StrictInt] = Field(default=None, ge=1)


class ApplyOptimizationRequest(_StrictModel):
    result_id: StrictStr = Field(min_length=1, max_length=128, pattern=_ID.pattern)
    request_id: StrictStr = Field(min_length=1, max_length=128, pattern=_ID.pattern)


class GenerationMedia(_StrictModel):
    kind: Literal["text"]
    resultId: StrictStr
    url: StrictStr
    name: StrictStr
    mime: StrictStr
    text: StrictStr
    content: StrictStr


class GenerationStatus(_StrictModel):
    run_id: StrictStr
    status: StrictStr
    slot: Literal["text"]
    output_node_id: StrictStr
    module_id: Literal["script", "novel"]
    project_id: StrictStr
    purpose: Literal["optimize"]
    scope: StrictStr
    source_id: StrictStr
    client_operation_id: StrictStr
    accepted_revision: StrictInt
    source_revision: StrictInt
    source_sha256: StrictStr
    source_object_sha256: StrictStr
    settings_revision: StrictInt
    recipe_fingerprint: StrictStr
    current_recipe_matches: bool = False
    output_kind: StrictStr = ""
    result_ids: list[StrictStr] = Field(default_factory=list)
    media: list[GenerationMedia] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    error: StrictStr = ""
    error_category: StrictStr = ""


class StudioManuscriptGenerationBridge:
    def __init__(self, *, module: Literal["script", "novel"], manuscript_store: Any,
                 runner: Any, storage: Any, settings_service: Any):
        self.module = module
        self.manuscript_store = manuscript_store
        self.runner = runner
        self.storage = storage
        self.settings_service = settings_service
        self._operation_locks = AsyncOperationLockRegistry()

    @staticmethod
    def _fingerprint(value: Any) -> str:
        try:
            raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="文本优化请求必须是有效 JSON") from exc
        return hashlib.sha256(raw).hexdigest()

    def _prior_run(self, operation_id: str) -> dict[str, Any] | None:
        for run in self.storage.list_runs(canvas_id=self.runner.canvas_id):
            if str(run.get("client_operation_id") or "") != operation_id:
                continue
            run_id = str(run.get("run_id") or "")
            flow = self.runner.get(run_id)
            if isinstance(flow, Mapping):
                return dict(flow)
            snapshot = run.get("capability_snapshot") if isinstance(run.get("capability_snapshot"), Mapping) else {}
            task = self.storage.get_canvas_task(run_id) or {}
            private = task.get("private_snapshot") if isinstance(task.get("private_snapshot"), Mapping) else {}
            context = private.get("trusted_context") if isinstance(private.get("trusted_context"), Mapping) else snapshot.get("trusted_context")
            standard = run.get("standard_request") if isinstance(run.get("standard_request"), Mapping) else {}
            return {"run_id": run_id, "status": "recoverable",
                    "output_node_id": str(standard.get("output_node_id") or snapshot.get("output_node_id") or ""),
                    "trusted_context": copy.deepcopy(dict(context)) if isinstance(context, Mapping) else {}}
        return None

    @staticmethod
    def _context(flow: Mapping[str, Any]) -> dict[str, Any]:
        value = flow.get("trusted_context") if isinstance(flow.get("trusted_context"), Mapping) else {}
        return copy.deepcopy(dict(value))

    def _response(self, flow: Mapping[str, Any], *, project_id: str, run_id: str | None = None) -> dict[str, Any]:
        context = self._context(flow)
        if (context.get("module_id") != self.module or str(context.get("project_id") or "") != str(project_id)
                or context.get("purpose") != "optimize" or context.get("slot") != "text"):
            raise HTTPException(status_code=404, detail="文本优化任务不存在")
        result_ids: list[str] = []
        media: list[dict[str, Any]] = []
        errors: list[str] = []
        for item in flow.get("media") if isinstance(flow.get("media"), list) else []:
            if not isinstance(item, Mapping) or str(item.get("kind") or "").lower() != "text":
                continue
            result_id = str(item.get("resultId") or item.get("result_id") or "").strip()
            if not result_id or result_id in result_ids:
                continue
            managed = self.storage.get_result(result_id)
            path = self.storage.result_path(result_id)
            if not isinstance(managed, Mapping) or managed.get("kind") != "text" or path is None:
                errors.append("文本结果文件缺失或类型不匹配")
                continue
            try:
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != str(managed.get("sha256") or ""):
                    raise ValueError("摘要不匹配")
                text = raw.decode("utf-8")
            except (OSError, UnicodeDecodeError, ValueError):
                errors.append("文本结果文件无法验证")
                continue
            result_ids.append(result_id)
            url = self.storage.result_url(result_id)
            media.append({"kind": "text", "resultId": result_id, "url": url,
                          "name": str(managed.get("display_name") or item.get("name") or "优化结果.md"),
                          "mime": str(managed.get("mime") or "text/markdown; charset=utf-8"),
                          "text": text, "content": text})
        status = str(flow.get("status") or "recoverable")
        output_kind = str(flow.get("output_kind") or "")
        error = str(flow.get("error") or "")
        error_category = str(flow.get("error_category") or "")
        if status == "succeeded" and (output_kind != "text" or not result_ids):
            if not error:
                error = errors[0] if errors else "共享文本结果不可访问，不能采用。"
            error_category = "output_unavailable"
        source_snapshot = context.get("source_snapshot") if isinstance(context.get("source_snapshot"), Mapping) else {}
        value = {
            "run_id": str(run_id or flow.get("run_id") or ""), "status": status,
            "slot": "text", "output_node_id": str(flow.get("output_node_id") or ""),
            "module_id": self.module, "project_id": str(project_id), "purpose": "optimize",
            "scope": str(context.get("scope") or ""), "source_id": str(context.get("source_id") or ""),
            "client_operation_id": str(context.get("client_operation_id") or ""),
            "accepted_revision": int(context.get("accepted_revision") or 1),
            "source_revision": int(context.get("source_revision") or 0),
            "source_sha256": str(context.get("source_sha256") or ""),
            "source_object_sha256": str(context.get("source_object_sha256") or ""),
            "settings_revision": int(context.get("settings_revision") or 1),
            "recipe_fingerprint": str(flow.get("recipe_fingerprint") or ""),
            "current_recipe_matches": bool(flow.get("current_recipe_matches")),
            "output_kind": output_kind, "result_ids": result_ids, "media": media,
            "steps": copy.deepcopy(flow.get("steps") if isinstance(flow.get("steps"), list) else []),
            "error": error, "error_category": error_category,
        }
        return value

    def _request_prompt(self, request: Mapping[str, Any], source: Mapping[str, Any]) -> str:
        source_text = str(source.get("body_markdown") or "")
        source_digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        directions = [
            "按用户的明确要求优化下方已保存文本。只输出可直接保存的正文，不要加解释、标题包装或代码围栏。",
        ]
        if self.module == "script" and source.get("scope") == "scene":
            directions.append(f"保留原有 {int(source.get('segment_count') or 0)} 个分段的数量、顺序和独立 --- 边界；不要合并、新增或删除分段。")
        if self.module == "script" and source.get("scope") == "segment":
            directions.append("只返回当前分段正文；不要输出独立 --- 分隔行。")
        if self.module == "novel" and source.get("scope") == "chapter":
            directions.append("这是章节正文，不要输出一级或二级标题；小标题从 ### 开始。")
        return ("\n".join(directions) + "\n\n用户要求：\n" + str(request.get("prompt") or "")
                + "\n\n已保存文本（SHA-256 " + source_digest + "): \n<BEGIN SAVED TEXT>\n"
                + source_text + "\n<END SAVED TEXT>")

    async def submit(self, project_id: str, payload: Mapping[str, Any], accepted: Mapping[str, Any] | None = None) -> dict[str, Any]:
        del accepted  # Only this bridge's store read is trusted; the client cannot submit a source snapshot.
        operation_id = str(payload.get("client_operation_id") or "")
        async with self._operation_locks.hold(operation_id):
            return await self._submit_locked(project_id, payload)

    async def _submit_locked(self, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        module = self.module
        scope = str(payload.get("scope") or "")
        source_id = str(payload.get("source_id") or "")
        output_node_id = str(payload.get("output_node_id") or "")
        operation_id = str(payload.get("client_operation_id") or "")
        if not _ID.fullmatch(project_id) or not _ID.fullmatch(source_id) or not _ID.fullmatch(output_node_id):
            raise HTTPException(status_code=400, detail="项目、来源对象或输出节点 ID 无效")
        if not _ID.fullmatch(operation_id):
            raise HTTPException(status_code=400, detail="client_operation_id 无效")
        request = payload.get("request") if isinstance(payload.get("request"), Mapping) else {}
        request_value = copy.deepcopy(dict(request))
        request_fingerprint = self._fingerprint({key: value for key, value in payload.items() if key != "client_operation_id"})
        prior = self._prior_run(operation_id)
        if prior:
            context = self._context(prior)
            snapshot = context.get("source_snapshot") if isinstance(context.get("source_snapshot"), Mapping) else {}
            if (context.get("module_id") != module or str(context.get("project_id") or "") != project_id
                    or context.get("purpose") != "optimize" or context.get("slot") != "text"
                    or context.get("scope") != scope or context.get("source_id") != source_id
                    or context.get("client_operation_id") != operation_id
                    or context.get("client_request_sha256") != request_fingerprint
                    or context.get("client_base_revision") != payload.get("base_revision")
                    or int(context.get("source_revision") or -1) != int(payload.get("expected_source_revision", -2))
                    or str(context.get("source_sha256") or "") != str(payload.get("expected_source_sha256") or "")
                    or str(prior.get("output_node_id") or "") != output_node_id):
                raise HTTPException(status_code=409, detail="此 client_operation_id 已绑定到不同项目、来源版本、端口或优化要求")
            resolved_request = context.get("resolved_request")
            if not isinstance(resolved_request, Mapping) or not isinstance(snapshot.get("text"), str):
                raise HTTPException(status_code=409, detail="原优化任务缺少可恢复的受信请求快照")
            settings_revision = int(context.get("settings_revision") or 1)
            runner_payload = {"request": copy.deepcopy(dict(resolved_request)), "base_revision": settings_revision}
        else:
            try:
                source = self.manuscript_store.generation_source(project_id, module, scope, source_id)
            except StudioProjectNotFound as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except StudioProjectConflict as exc:
                raise HTTPException(status_code=409, detail=exc.args[0]) from exc
            except StudioProjectError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            expected_revision = payload.get("expected_source_revision")
            expected_sha = str(payload.get("expected_source_sha256") or "")
            if (isinstance(expected_revision, bool) or not isinstance(expected_revision, int)
                    or source["source_revision"] != expected_revision or source["source_sha256"] != expected_sha):
                raise HTTPException(status_code=409, detail={"code": "SOURCE_CHANGED",
                    "message": "所选正文或章纲已更新，请重新读取后再优化。",
                    "source_revision": source["source_revision"], "source_sha256": source["source_sha256"]})
            source_text = str(source["body_markdown"])
            source_object_sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            if source_object_sha != str(source.get("source_object_sha256") or ""):
                raise HTTPException(status_code=500, detail="读取的正文指纹校验失败")
            settings_canvas = self.settings_service.ensure_canvas()
            settings_revision = max(1, int(settings_canvas.get("revision") or 1))
            base_revision = payload.get("base_revision")
            if base_revision is not None and base_revision != int(source["project_revision"]):
                raise HTTPException(status_code=409, detail={
                    "code": "PROJECT_REVISION_CHANGED",
                    "message": "作品项目已更新，请重新读取正文后再提交优化。",
                    "revision": int(source["project_revision"]),
                })
            resolved_request = {"prompt": self._request_prompt(request_value, source)}
            for key in ("system_prompt", "parameters", "prompt_target_node_id", "field_inputs"):
                if key in request_value and request_value[key] is not None:
                    resolved_request[key] = copy.deepcopy(request_value[key])
            context = {
                "module_id": module, "project_id": project_id, "purpose": "optimize", "slot": "text",
                "accepted_revision": int(source["project_revision"]),
                "source_hash": source_object_sha, "source_sha256": str(source["source_sha256"] or ""),
                "source_object_sha256": source_object_sha, "source_revision": int(source["source_revision"]),
                "scope": scope, "source_id": source_id, "client_operation_id": operation_id,
                "source_snapshot": {"text": source_text, "title": str(source.get("title") or ""),
                                    **({"segment_count": source.get("segment_count")} if scope == "scene" else {})},
                "client_request_sha256": request_fingerprint,
                "client_base_revision": payload.get("base_revision"), "settings_revision": settings_revision,
                "resolved_request": resolved_request,
            }
            runner_payload = {"request": resolved_request, "base_revision": settings_revision}
        try:
            flow = await self.runner.submit("text", output_node_id, operation_id, runner_payload,
                                            test=False, trusted_context=context)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail="共享文本优化流程未能提交，请按原 client_operation_id 恢复") from exc
        if not isinstance(flow, Mapping) or not flow.get("run_id"):
            raise HTTPException(status_code=502, detail="共享文本优化流程未返回持久任务 ID")
        return self._response({**dict(flow), "trusted_context": context}, project_id=project_id)

    def _managed_text(self, result_id: str) -> str:
        managed = self.storage.get_result(result_id)
        path = self.storage.result_path(result_id)
        if not isinstance(managed, Mapping) or managed.get("kind") != "text" or path is None:
            raise HTTPException(status_code=422, detail="只能采用属于此任务且仍可访问的托管文本结果")
        try:
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != str(managed.get("sha256") or ""):
                raise ValueError("hash")
            return raw.decode("utf-8")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="文本结果缺失或校验失败；已保留作品原文") from exc

    def apply(self, project_id: str, run_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        result_id, request_id = str(payload.get("result_id") or ""), str(payload.get("request_id") or "")
        if not _ID.fullmatch(run_id) or not _ID.fullmatch(result_id) or not _ID.fullmatch(request_id):
            raise HTTPException(status_code=400, detail="run_id、result_id 或 request_id 无效")
        try:
            replay = self.manuscript_store.generation_apply_receipt(project_id, self.module, request_id, run_id, result_id)
        except StudioProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StudioProjectConflict as exc:
            raise HTTPException(status_code=409, detail=exc.args[0]) from exc
        if replay is not None:
            return replay
        flow = self.runner.get(run_id)
        if not isinstance(flow, Mapping):
            raise HTTPException(status_code=404, detail="文本优化任务不存在")
        context = self._context(flow)
        if (context.get("module_id") != self.module or str(context.get("project_id") or "") != project_id
                or flow.get("status") != "succeeded" or flow.get("output_kind") != "text"):
            raise HTTPException(status_code=409, detail="任务尚未成功，或其服务端输出类型不是 text；不能采用。")
        status = self._response(flow, project_id=project_id, run_id=run_id)
        if result_id not in status["result_ids"]:
            raise HTTPException(status_code=422, detail="result_id 不属于此任务的已验证托管文本结果")
        result_text = self._managed_text(result_id)
        source_snapshot = context.get("source_snapshot") if isinstance(context.get("source_snapshot"), Mapping) else {}
        try:
            return self.manuscript_store.apply_generated_text(
                project_id, self.module, scope=str(context.get("scope") or ""),
                source_id=str(context.get("source_id") or ""),
                source_revision=int(context.get("source_revision") or 0),
                source_sha256=str(context.get("source_sha256") or ""),
                source_object_sha256=str(context.get("source_object_sha256") or ""),
                body_markdown=result_text, request_id=request_id, run_id=run_id, result_id=result_id,
                source_segment_count=source_snapshot.get("segment_count"),
            )
        except StudioProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StudioProjectConflict as exc:
            raise HTTPException(status_code=409, detail=exc.args[0]) from exc
        except StudioProjectError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    async def get(self, project_id: str, run_id: str) -> dict[str, Any] | None:
        flow = self.runner.get(run_id)
        if not isinstance(flow, Mapping):
            return None
        try:
            return self._response(flow, project_id=project_id, run_id=run_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                return None
            raise


def create_studio_manuscript_generation_router(*, module: Literal["script", "novel"], bridge: StudioManuscriptGenerationBridge) -> APIRouter:
    router = APIRouter()
    collection = "scripts" if module == "script" else "novels"
    if module == "script":
        @router.post(f"/api/studio/{collection}/{{project_id}}/generations", response_model=GenerationStatus)
        async def submit_generation(project_id: str, payload: ScriptGenerationRequest):
            return await bridge.submit(project_id, payload.model_dump(exclude_unset=True))
    else:
        @router.post(f"/api/studio/{collection}/{{project_id}}/generations", response_model=GenerationStatus)
        async def submit_generation(project_id: str, payload: NovelGenerationRequest):
            return await bridge.submit(project_id, payload.model_dump(exclude_unset=True))

    @router.get(f"/api/studio/{collection}/{{project_id}}/generations/{{run_id}}", response_model=GenerationStatus)
    async def get_generation(project_id: str, run_id: str):
        result = await bridge.get(project_id, run_id)
        if not isinstance(result, dict):
            raise HTTPException(status_code=404, detail="文本优化任务不存在")
        return result

    @router.post(f"/api/studio/{collection}/{{project_id}}/generations/{{run_id}}/apply")
    async def apply_generation(project_id: str, run_id: str, payload: ApplyOptimizationRequest):
        return bridge.apply(project_id, run_id, payload.model_dump())

    return router


__all__ = [
    "ApplyOptimizationRequest", "GenerationStatus", "NovelGenerationRequest",
    "ScriptGenerationRequest", "StudioManuscriptGenerationBridge",
    "create_studio_manuscript_generation_router",
]
