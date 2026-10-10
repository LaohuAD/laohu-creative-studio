"""音乐生成入口桥接至共享配置图 runner 和受管素材收集器。"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re
from collections.abc import Mapping
from typing import Any, Callable

from fastapi import HTTPException
from studio_hypit_flow import AsyncOperationLockRegistry


class StudioMusicGenerationBridge:
    _PUBLIC_ERROR_CATEGORIES = {
        "input_validation", "execution_failed", "result_collection_failed",
        "music_association_failed", "upstream_pending", "output_mismatch",
        "output_unavailable", "interrupted",
    }

    def __init__(self, *, music_store: Any, runner: Any, storage: Any, settings_service: Any,
                 prepare_request: Callable[..., Any]):
        self.music_store = music_store
        self.runner = runner
        self.storage = storage
        self.settings_service = settings_service
        self.prepare_request = prepare_request
        self._operation_locks = AsyncOperationLockRegistry()

    @staticmethod
    async def _await(value: Any) -> Any:
        return await value if inspect.isawaitable(value) else value

    @staticmethod
    def _fingerprint(value: Any) -> str:
        try:
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "音乐生成请求必须是有效 JSON") from exc
        return hashlib.sha256(encoded).hexdigest()

    def _prior_run(self, operation_id: str) -> dict[str, Any] | None:
        # Operation IDs are unique within the whole music graph, not per output port.
        for item in self.storage.list_runs(canvas_id=self.runner.canvas_id):
            if str(item.get("client_operation_id") or "") == operation_id:
                run_id = str(item.get("run_id") or "")
                flow = self.runner.get(run_id)
                if isinstance(flow, Mapping):
                    return dict(flow)
                snapshot = item.get("capability_snapshot") if isinstance(item.get("capability_snapshot"), Mapping) else {}
                context = snapshot.get("trusted_context") if isinstance(snapshot.get("trusted_context"), Mapping) else {}
                standard = item.get("standard_request") if isinstance(item.get("standard_request"), Mapping) else {}
                return {
                    "run_id": run_id,
                    "status": "validated",
                    "output_node_id": str(standard.get("output_node_id") or snapshot.get("output_node_id") or ""),
                    "trusted_context": copy.deepcopy(dict(context)),
                }
        return None

    async def submit(self, project_id: str, payload: Mapping[str, Any], accepted: Mapping[str, Any]) -> dict[str, Any]:
        operation_id = str(payload.get("client_operation_id") or "").strip() if isinstance(payload, Mapping) else ""
        async with self._operation_locks.hold(operation_id):
            return await self._submit_locked(project_id, payload, accepted)

    async def _submit_locked(self, project_id: str, payload: Mapping[str, Any], accepted: Mapping[str, Any]) -> dict[str, Any]:
        purpose = str(payload.get("purpose") or "").strip().lower()
        slot = str(payload.get("slot") or "").strip().lower()
        output_node_id = str(payload.get("output_node_id") or "").strip()
        operation_id = str(payload.get("client_operation_id") or "").strip()
        if (purpose, slot) not in {("song", "music"), ("cover", "image")}:
            raise HTTPException(400, "歌曲使用 music 输出，封面使用 image 输出")
        if not output_node_id or len(output_node_id) > 160 or not operation_id or len(operation_id) > 160:
            raise HTTPException(400, "缺少有效的 output_node_id 或 client_operation_id")
        client_request = payload.get("request") if isinstance(payload.get("request"), Mapping) else {}
        client_request_hash = self._fingerprint(dict(client_request))
        prior = self._prior_run(operation_id)
        if prior:
            prior_context = prior.get("trusted_context") if isinstance(prior.get("trusted_context"), Mapping) else {}
            if (prior_context.get("module_id") != "music"
                    or str(prior_context.get("project_id") or "") != str(project_id)
                    or prior_context.get("purpose") != purpose
                    or prior_context.get("slot") != slot
                    or prior_context.get("client_operation_id") != operation_id
                    or prior_context.get("client_request_sha256") != client_request_hash
                    or prior_context.get("client_base_revision") != payload.get("base_revision")
                    or str(prior.get("output_node_id") or "") != output_node_id):
                raise HTTPException(409, "此 client_operation_id 已绑定到其他音乐项目、用途、端口或输入")
            context = copy.deepcopy(dict(prior_context))
            flow_request = context.get("resolved_request")
            if not isinstance(flow_request, Mapping):
                raise HTTPException(409, "原音乐任务缺少可恢复的请求快照，请保留原任务并联系维护者")
            settings_revision = int(context.get("settings_revision") or 1)
        else:
            current = self.music_store.get(project_id)
            requested_revision = payload.get("base_revision")
            if requested_revision is not None and int(requested_revision) != int(current["revision"]):
                raise HTTPException(409, detail={"message": "歌曲内容已更新，请重新读取后再生成。",
                                                  "music": current, "revision": current["revision"]})
            if (int(current["revision"]) != int(accepted.get("accepted_revision") or 0)
                    or str(current.get("source_sha256") or "") != str(accepted.get("source_hash") or "")):
                raise HTTPException(409, detail={"message": "歌曲内容已更新，请重新读取后再生成。",
                                                  "music": current, "revision": current["revision"]})
            source_snapshot = {key: str(current.get(key) or "") for key in (
                "title", "lyrics", "style_prompt", "notes", "cover_prompt",
            )}
            source_snapshot["reference_audio_refs"] = copy.deepcopy(current.get("reference_audio_refs") or [])
            source_snapshot["score_refs"] = copy.deepcopy(current.get("score_refs") or [])
            source_snapshot.update({"source_sha256": str(current["source_sha256"]),
                                    "accepted_revision": int(current["revision"])})
            canvas = self.settings_service.ensure_canvas()
            settings_revision = max(1, int(canvas.get("revision") or 1))
            context = {
                "module_id": "music", "project_id": str(project_id), "purpose": purpose, "slot": slot,
                "accepted_revision": int(current["revision"]), "source_hash": str(current["source_sha256"]),
                "client_operation_id": operation_id, "client_request_sha256": client_request_hash,
                "client_base_revision": requested_revision,
                "source_snapshot": source_snapshot, "settings_revision": settings_revision,
            }
            resolved = await self._await(self.prepare_request(
                canvas=canvas, purpose=purpose, slot=slot, output_node_id=output_node_id,
                song=current, source_snapshot=source_snapshot, request=copy.deepcopy(dict(client_request)),
            ))
            if not isinstance(resolved, Mapping):
                raise HTTPException(400, "音乐输入无法按当前节点或模型契约明确映射")
            flow_request = copy.deepcopy(dict(resolved))
            # 持久受信快照确保重放使用原输入，即使当前歌词或配置图已改变。
            context["resolved_request"] = copy.deepcopy(flow_request)

        canvas = self.settings_service.ensure_canvas()
        runner_payload = {"request": copy.deepcopy(dict(flow_request)), "base_revision": settings_revision}
        value = await self._await(self.runner.submit(
            slot, output_node_id, operation_id, runner_payload, test=False, trusted_context=context,
        ))
        if not isinstance(value, Mapping) or not value.get("run_id"):
            raise HTTPException(502, "共享音乐执行流程未返回持久任务 ID")
        return {**dict(value), "module_id": "music", "project_id": str(project_id), "purpose": purpose,
                "client_operation_id": operation_id}

    def _save_association_state(self, run_id: str, error: bool) -> None:
        task = self.storage.get_canvas_task(run_id)
        if not isinstance(task, Mapping):
            return
        result = copy.deepcopy(task.get("result") if isinstance(task.get("result"), Mapping) else {})
        if error:
            result["music_association_error"] = {
                "code": "music_association_failed",
                "message": "生成成功，但受管素材尚未关联到歌曲。重新查询同一任务可重试，不会重复提交模型。",
            }
        else:
            result.pop("music_association_error", None)
        try:
            self.storage.update_canvas_task(run_id, result=result)
        except Exception:
            return

    def _associate(self, flow: Mapping[str, Any]) -> bool:
        context = flow.get("trusted_context") if isinstance(flow.get("trusted_context"), Mapping) else {}
        run_id = str(flow.get("run_id") or "").strip()
        if (not run_id or context.get("module_id") != "music"
                or str(flow.get("status") or "").lower() != "succeeded"):
            return False
        try:
            self.music_store.associate_generation(
                str(context.get("project_id") or ""), run_id=run_id,
                purpose=str(context.get("purpose") or ""),
                media=copy.deepcopy(flow.get("media") if isinstance(flow.get("media"), list) else []),
                snapshot=copy.deepcopy(context.get("source_snapshot") if isinstance(context.get("source_snapshot"), Mapping) else {}),
                accepted_revision=int(context.get("accepted_revision") or 0),
            )
        except Exception:
            self._save_association_state(run_id, True)
            return False
        self._save_association_state(run_id, False)
        return True

    async def publish_node_result(self, canvas_snapshot: Mapping[str, Any], source_node: Mapping[str, Any],
                                  media: list[dict[str, Any]], task: Mapping[str, Any]) -> None:
        del canvas_snapshot, source_node
        value = dict(task)
        value["media"] = copy.deepcopy(media)
        self._associate(value)

    @staticmethod
    def _safe_error(category: Any) -> str:
        """Use actionable public errors without exposing provider payloads or paths."""
        return {
            "input_validation": "输入内容或字段校验失败，请检查当前内容与配置字段。",
            "execution_failed": "生成服务执行失败；确认配置可用后，可明确发起新一轮生成。",
            "result_collection_failed": "执行已结束，但受管结果收集失败；可查询原任务恢复关联。",
            "music_association_failed": "生成结果暂未关联到歌曲；重新查询同一任务可重试关联。",
            "upstream_pending": "上游仍在运行；系统会继续查询原任务，不会重复提交。",
        }.get(str(category or ""), "")

    def _public_media(self, values: Any, purpose: str) -> list[dict[str, Any]]:
        if not isinstance(values, list):
            return []
        expected_kind = "audio" if purpose == "song" else "image"
        output = []
        for item in values:
            if not isinstance(item, Mapping):
                continue
            kind = str(item.get("kind") or item.get("media_type") or item.get("type") or "").strip().lower()
            if kind != expected_kind:
                continue
            result_id = str(item.get("resultId") or item.get("result_id") or "").strip()
            asset_id = str(item.get("assetId") or item.get("asset_id") or "").strip()
            record = None
            if result_id:
                record = self.storage.get_result(result_id)
                if not isinstance(record, Mapping):
                    continue
                url = self.storage.result_url(result_id)
                result_key = "resultId"
            elif asset_id:
                get_material = getattr(self.storage, "get_material", None)
                record = get_material(asset_id) if callable(get_material) else None
                if not isinstance(record, Mapping):
                    continue
                material_url = getattr(self.storage, "material_url", None)
                if not callable(material_url):
                    continue
                url = material_url(asset_id)
                result_key = "assetId"
            else:
                # Only resolve strict, same-origin managed URLs to storage IDs.
                candidate = str(item.get("url") or "").strip()
                match = re.fullmatch(r"/api/(results|materials)/([A-Za-z0-9_-]+)", candidate)
                if not match:
                    continue
                family, managed_id = match.groups()
                if family == "results":
                    record = self.storage.get_result(managed_id)
                    if not isinstance(record, Mapping):
                        continue
                    result_id, result_key = managed_id, "resultId"
                    url = self.storage.result_url(managed_id)
                else:
                    get_material = getattr(self.storage, "get_material", None)
                    material_url = getattr(self.storage, "material_url", None)
                    record = get_material(managed_id) if callable(get_material) else None
                    if not isinstance(record, Mapping) or not callable(material_url):
                        continue
                    asset_id, result_key = managed_id, "assetId"
                    url = material_url(managed_id)
            safe_url = str(url or "")
            if not re.fullmatch(r"/api/(?:results|materials)/[A-Za-z0-9_-]+", safe_url):
                continue
            kind_from_record = str(record.get("kind") or record.get("media_type") or "").strip().lower()
            if kind_from_record and kind_from_record != expected_kind:
                continue
            raw_name = str(record.get("display_name") or item.get("name") or "").replace("\\", "/").split("/")[-1]
            entry = {
                "kind": expected_kind,
                "url": safe_url,
                "name": raw_name[:240],
                "mime": str(record.get("mime") or record.get("mime_type") or item.get("mime") or "")[:160],
                result_key: result_id if result_key == "resultId" else asset_id,
            }
            output.append(entry)
        return output

    def _public_steps(self, values: Any) -> list[dict[str, Any]]:
        if not isinstance(values, list):
            return []
        output = []
        for item in values:
            if not isinstance(item, Mapping):
                continue
            category = str(item.get("error_category") or item.get("errorCategory") or "")
            if category not in self._PUBLIC_ERROR_CATEGORIES:
                category = "execution_failed" if category else ""
            step = {
                key: str(item.get(key) or "")[:160]
                for key in ("node_id", "type", "status") if item.get(key) is not None
            }
            if category:
                step["error_category"] = category[:80]
                message = self._safe_error(category)
                if message:
                    step["error"] = message
            output.append(step)
        return output

    def _public_flow(self, flow: Mapping[str, Any]) -> dict[str, Any]:
        context = flow.get("trusted_context") if isinstance(flow.get("trusted_context"), Mapping) else {}
        purpose = str(context.get("purpose") or "")
        raw_category = str(flow.get("error_category") or "")
        error_category = raw_category if raw_category in self._PUBLIC_ERROR_CATEGORIES else (
            "execution_failed" if raw_category else ""
        )
        public = {key: copy.deepcopy(flow.get(key)) for key in (
            "run_id", "status", "slot", "output_node_id", "recipe_fingerprint", "current_recipe_matches",
            "output_kind", "provider_task_id",
        ) if key in flow}
        if error_category:
            public["error_category"] = error_category
        result_ids = flow.get("result_ids") if isinstance(flow.get("result_ids"), list) else []
        public["result_ids"] = [str(value) for value in result_ids
                                if isinstance(value, str) and self.storage.get_result(value)]
        public["media"] = self._public_media(flow.get("media"), purpose)
        public["steps"] = self._public_steps(flow.get("steps"))
        public["error"] = self._safe_error(error_category)
        task = self.storage.get_canvas_task(str(flow.get("run_id") or "")) or {}
        result = task.get("result") if isinstance(task.get("result"), Mapping) else {}
        association_failed = bool(result.get("music_association_error"))
        public.update({"module_id": "music", "project_id": str(context.get("project_id") or ""),
                       "purpose": purpose,
                       "accepted_revision": int(context.get("accepted_revision") or 0),
                       "client_operation_id": str(context.get("client_operation_id") or ""),
                       "music_association_error": ({
                           "code": "music_association_failed",
                           "message": self._safe_error("music_association_failed"),
                       } if association_failed else None)})
        return public

    async def get(self, project_id: str, run_id: str) -> dict[str, Any] | None:
        flow = self.runner.get(run_id)
        if not isinstance(flow, Mapping):
            return None
        context = flow.get("trusted_context") if isinstance(flow.get("trusted_context"), Mapping) else {}
        if (str(flow.get("canvas_id") or "") != "music-settings" or context.get("module_id") != "music"
                or str(context.get("project_id") or "") != str(project_id)):
            return None
        if str(flow.get("status") or "").lower() == "succeeded":
            self._associate(flow)
            flow = self.runner.get(run_id) or flow
        return self._public_flow(flow)

    async def list(self, project_id: str) -> list[dict[str, Any]]:
        output = []
        for run in self.storage.list_runs(canvas_id="music-settings"):
            run_id = str(run.get("run_id") or "")
            flow = self.runner.get(run_id) if run_id else None
            if not isinstance(flow, Mapping):
                continue
            context = flow.get("trusted_context") if isinstance(flow.get("trusted_context"), Mapping) else {}
            if context.get("module_id") == "music" and str(context.get("project_id") or "") == str(project_id):
                if str(flow.get("status") or "").lower() == "succeeded":
                    self._associate(flow)
                    flow = self.runner.get(run_id) or flow
                output.append(self._public_flow(flow))
        return sorted(output, key=lambda item: str(item.get("run_id") or ""))


__all__ = ["StudioMusicGenerationBridge"]
