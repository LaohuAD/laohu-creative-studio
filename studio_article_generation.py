"""公众号文章任务与共享生成流程之间的服务端桥接。"""
from __future__ import annotations

import copy
import inspect
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException


class StudioArticleGenerationBridge:
    """把文章绑定信息加入共享流程快照，并在成功后幂等关联托管结果。"""

    def __init__(self, *, article_store: Any, runner: Any, storage: Any, settings_service: Any,
                 publish_node_result: Any = None):
        self.article_store = article_store
        self.runner = runner
        self.storage = storage
        self.settings_service = settings_service
        self.publish_node_result_callback = publish_node_result

    @staticmethod
    async def _await(value: Any) -> Any:
        return await value if inspect.isawaitable(value) else value

    @staticmethod
    def _trusted_context(project_id: str, payload: Mapping[str, Any], accepted: Mapping[str, Any]) -> dict[str, Any]:
        slot = str(payload.get("slot") or "").strip().lower()
        purpose = str(payload.get("purpose") or "").strip().lower()
        operation_id = str(payload.get("client_operation_id") or "").strip()
        revision = accepted.get("accepted_revision")
        source_hash = str(accepted.get("source_hash") or "").strip().lower()
        if slot not in {"text", "image", "video", "audio", "music", "voice"}:
            raise HTTPException(status_code=400, detail="文章生成用途槽不受支持")
        if purpose not in {"cover", "illustration", "knowledge"}:
            raise HTTPException(status_code=400, detail="文章生成 purpose 必须是 cover、illustration 或 knowledge")
        if purpose == "cover" and slot != "image":
            raise HTTPException(status_code=400, detail="封面用途只能选择图片输出槽")
        if not operation_id:
            raise HTTPException(status_code=400, detail="文章生成缺少 client_operation_id")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise HTTPException(status_code=400, detail="文章生成缺少有效文章修订号")
        if len(source_hash) != 64 or any(char not in "0123456789abcdef" for char in source_hash):
            raise HTTPException(status_code=400, detail="文章生成缺少有效文章来源指纹")
        return {
            "module_id": "article",
            "project_id": str(project_id),
            "purpose": purpose,
            "slot": slot,
            "accepted_revision": revision,
            "source_hash": source_hash,
            "client_operation_id": operation_id,
        }

    def _prior_context(self, operation_id: str) -> tuple[dict[str, Any] | None, Mapping[str, Any] | None]:
        """只找相同操作的原服务端快照；是否输入相同仍交给 runner 幂等校验。"""
        try:
            runs = self.storage.list_runs(canvas_id="article-settings")
        except Exception:
            return None, None
        for run in runs:
            if str(run.get("client_operation_id") or "") != operation_id:
                continue
            run_snapshot = run.get("capability_snapshot") if isinstance(run.get("capability_snapshot"), Mapping) else {}
            context = run_snapshot.get("trusted_context") if isinstance(run_snapshot.get("trusted_context"), Mapping) else None
            task = self.storage.get_canvas_task(str(run.get("run_id") or ""))
            if task:
                private = task.get("private_snapshot") if isinstance(task.get("private_snapshot"), Mapping) else {}
                task_context = private.get("trusted_context") if isinstance(private.get("trusted_context"), Mapping) else None
                if task_context is not None:
                    context = task_context
            if isinstance(context, Mapping):
                return copy.deepcopy(dict(context)), run
        return None, None

    async def submit(self, project_id: str, payload: Mapping[str, Any], accepted: Mapping[str, Any]) -> dict[str, Any]:
        """校验文章与配置图快照后，只通过共享 runner 提交一次任务。"""
        if not isinstance(payload, Mapping) or not isinstance(accepted, Mapping):
            raise HTTPException(status_code=400, detail="文章生成请求格式无效")
        article = self.article_store.get(project_id)
        candidate_context = self._trusted_context(project_id, payload, accepted)
        requested_revision = accepted.get("requested_revision")
        prior_context, prior_run = self._prior_context(candidate_context["client_operation_id"])
        if prior_context is not None:
            same_request_identity = all(
                prior_context.get(key) == candidate_context.get(key)
                for key in ("module_id", "project_id", "purpose", "slot", "client_operation_id")
            )
            if not same_request_identity:
                raise HTTPException(status_code=409, detail="此 client_operation_id 已绑定到其他文章、用途或输出槽")
            if requested_revision is not None and requested_revision != prior_context.get("accepted_revision"):
                raise HTTPException(status_code=409, detail="此 client_operation_id 的文章修订号与原请求不同")
            requested_output_id = str(payload.get("output_node_id") or "")
            if str((prior_run or {}).get("node_id") or "") != requested_output_id:
                raise HTTPException(status_code=409, detail="此 client_operation_id 已绑定到其他输出端口")
            # 重放时保留原来的文章版本上下文。runner 仍负责校验原输入指纹并返回持久任务，
            # 不因文章关联已递增修订号而再次提交模型。
            context = prior_context
        else:
            context = candidate_context
            if requested_revision is not None and requested_revision != context["accepted_revision"]:
                raise HTTPException(status_code=409, detail="文章已更新，请重新读取后再生成。")
            if (int(article.get("revision") or 1) != context["accepted_revision"]
                    or str(article.get("source_sha256") or "") != context["source_hash"]):
                raise HTTPException(status_code=409, detail="文章内容已更新，请重新读取后再生成。")
        request = payload.get("request") if isinstance(payload.get("request"), Mapping) else {}
        canvas = self.settings_service.ensure_canvas()
        runner_payload = {
            "request": copy.deepcopy(dict(request)),
            "base_revision": max(1, int(canvas.get("revision") or 1)),
        }
        value = await self._await(self.runner.submit(
            context["slot"],
            str(payload.get("output_node_id") or ""),
            context["client_operation_id"],
            runner_payload,
            test=False,
            trusted_context=context,
        ))
        if not isinstance(value, Mapping) or not value.get("run_id"):
            raise HTTPException(status_code=502, detail="共享文章生成流程未返回持久任务 ID")
        return {**dict(value), "module_id": "article", "project_id": str(project_id),
                "purpose": context["purpose"]}

    def _save_association_state(self, run_id: str, error: bool) -> dict[str, Any] | None:
        task = self.storage.get_canvas_task(run_id)
        if not isinstance(task, Mapping):
            return None
        result = copy.deepcopy(task.get("result") if isinstance(task.get("result"), Mapping) else {})
        if error:
            result["article_association_error"] = {
                "code": "article_association_failed",
                "message": "生成任务已成功，但结果尚未关联到文章。重新查询此任务可重试关联；不会重复提交模型。",
            }
        else:
            result.pop("article_association_error", None)
        try:
            saved = self.storage.update_canvas_task(run_id, result=result)
        except Exception:
            return None
        return saved if isinstance(saved, dict) else None

    def _associate(self, flow: Mapping[str, Any]) -> bool:
        """将现有成功任务的托管结果关联到文章；重复执行由存储层按 run/asset 去重。"""
        context = flow.get("trusted_context") if isinstance(flow.get("trusted_context"), Mapping) else {}
        run_id = str(flow.get("run_id") or "").strip()
        project_id = str(context.get("project_id") or "").strip()
        if (not run_id or context.get("module_id") != "article"
                or str(flow.get("status") or "").lower() != "succeeded"):
            return False
        try:
            self.article_store.associate_generation_media(
                project_id,
                generation={
                    "run_id": run_id,
                    "status": "succeeded",
                    "output_kind": str(flow.get("output_kind") or ""),
                    "media": copy.deepcopy(flow.get("media") if isinstance(flow.get("media"), list) else []),
                },
                purpose=str(context.get("purpose") or ""),
                slot=str(context.get("slot") or ""),
                accepted_revision=int(context.get("accepted_revision") or 0),
                source_hash=str(context.get("source_hash") or ""),
            )
        except Exception:
            self._save_association_state(run_id, True)
            return False
        self._save_association_state(run_id, False)
        return True

    async def publish_node_result(self, canvas_snapshot: Mapping[str, Any], source_node: Mapping[str, Any],
                                  media: list[dict[str, Any]], task: Mapping[str, Any]) -> None:
        """尝试关联文章并回填普通节点历史；关联错误与生成成功状态分离。"""
        run_id = str(task.get("run_id") or "").strip()
        trusted_context = task.get("trusted_context") if isinstance(task.get("trusted_context"), Mapping) else {}
        flow = {
            **dict(task),
            "run_id": run_id,
            "status": str(task.get("status") or ""),
            "output_kind": str(task.get("output_kind") or ""),
            "media": copy.deepcopy(media),
            "trusted_context": copy.deepcopy(dict(trusted_context)),
        }
        self._associate(flow)
        if self.publish_node_result_callback is not None:
            try:
                await self._await(self.publish_node_result_callback(canvas_snapshot, source_node, media, task))
            except Exception:
                # 文章关联状态已单独持久化；普通节点历史回填失败不能改写成功任务。
                return

    async def get(self, project_id: str, run_id: str) -> dict[str, Any] | None:
        """读取持久任务并重试关联；不再调用 runner.submit 或供应商。"""
        flow = self.runner.get(run_id)
        if not isinstance(flow, Mapping):
            return None
        context = flow.get("trusted_context") if isinstance(flow.get("trusted_context"), Mapping) else {}
        if (str(flow.get("canvas_id") or "") != "article-settings"
                or context.get("module_id") != "article"
                or str(context.get("project_id") or "") != str(project_id)):
            return None
        association_succeeded = True
        if str(flow.get("status") or "").lower() == "succeeded":
            association_succeeded = self._associate(flow)
        task = self.storage.get_canvas_task(run_id) or {}
        result = task.get("result") if isinstance(task.get("result"), Mapping) else {}
        response = copy.deepcopy(dict(flow))
        association_error = result.get("article_association_error")
        if not association_succeeded and not association_error:
            # 索引写失败时任务记录也可能暂时无法保存错误；当前读取仍要给出可行动状态。
            association_error = {
                "code": "article_association_failed",
                "message": "生成任务已成功，但结果尚未关联到文章。重新查询此任务可重试关联；不会重复提交模型。",
            }
        response["article_association_error"] = copy.deepcopy(association_error)
        return response


__all__ = ["StudioArticleGenerationBridge"]
