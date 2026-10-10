"""AI 应用与 ComfyUI 的画布后台执行适配。

本模块只编排画布任务和已有主程序回调，不直接导入 ``main``，也不创建新的
RunningHub/ComfyUI HTTP 客户端。主控把现有的预检、提交、查询、上传和结果
保存函数注入进来即可，因此浏览器页面关闭后任务仍由服务端继续运行。
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import mimetypes
import math
import re
import time
import uuid
from typing import Any, Callable

from studio_execution import recipe, request_for, stable


APP_NODE_TYPES = {'smart-ai-app', 'smart-comfy-workflow'}
RUNNINGHUB_KINDS = {'ai_application', 'runninghub_workflow'}
_ACCEPTED_DYNAMIC_SNAPSHOT_KEY = '_studioAcceptedDynamicSnapshot'
_REQUEST_DYNAMIC_SNAPSHOT_KEY = '_studio_dynamic_snapshot'


def _secret_identifier(value: Any) -> bool:
    """Match the project's credential-field rule without rejecting token counts."""
    secret_names = {
        'api_key', 'apikey', 'access_token', 'accesstoken', 'auth_token', 'authtoken',
        'bearer_token', 'bearertoken', 'session_token', 'sessiontoken', 'refresh_token',
        'refreshtoken', 'id_token', 'idtoken', 'secret', 'token', 'password',
        'authorization', 'credential', 'api_token', 'apitoken', 'token_value', 'tokenvalue',
    }
    secret_parts = ('api_key', 'apikey', 'secret', 'password', 'access_token', 'authorization', 'credential')
    for part in re.split(r'::', str(value or '')):
        normal = re.sub(r'[^a-z0-9]+', '_', part.lower()).strip('_')
        compact = normal.replace('_', '')
        if normal in secret_names or compact in secret_names or any(token in normal for token in secret_parts):
            return True
    return False


def _schema_field_key(field: dict[str, Any], node_type: str) -> str:
    if node_type == 'smart-comfy-workflow':
        return str(field.get('id') or field.get('paramid') or field.get('paramId') or field.get('key') or '').strip()
    node_id = str(field.get('nodeId') or field.get('node_id') or '').strip()
    field_name = str(field.get('fieldName') or field.get('field_name') or field.get('inputName') or '').strip()
    if not node_id or not field_name:
        param_id = str(field.get('paramid') or field.get('paramId') or field.get('key') or '').strip()
        if '::' in param_id:
            node_id, field_name = (part.strip() for part in param_id.split('::', 1))
    return f'{node_id}::{field_name}' if node_id or field_name else str(
        field.get('key') or field.get('paramid') or field.get('paramId') or ''
    ).strip()


def _schema_field_media_kind(field: dict[str, Any], node_type: str) -> str:
    raw = str(field.get('fieldType') or field.get('type') or field.get('kind') or '').strip().lower()
    if raw in {'image', 'video', 'audio'}:
        return raw
    if node_type == 'smart-comfy-workflow':
        name = ' '.join(str(field.get(key) or '') for key in ('input', 'name', 'fieldName')).lower()
        return 'text' if raw == 'textarea' or any(
            token in name for token in ('prompt', 'text', '提示词', '正向', '负向')
        ) else ''
    if raw in {'string', 'text', 'plain-text', 'textarea'}:
        return 'text'
    return ''


def _safe_schema_fields(fields: list[dict[str, Any]], node_type: str) -> list[dict[str, Any]]:
    result = []
    for field in fields:
        identities = [field.get(key) for key in (
            'nodeId', 'node_id', 'fieldName', 'field_name', 'inputName', 'input', 'name',
            'label', 'id', 'key', 'paramid', 'paramId',
        )]
        raw_type = str(field.get('fieldType') or field.get('type') or field.get('kind') or '').strip().lower()
        if raw_type in {'password', 'secret', 'credential', 'token'} or any(
            _secret_identifier(value) for value in identities if value
        ):
            continue
        if _schema_field_key(field, node_type):
            result.append(copy.deepcopy(field))
    return result


def _workflow_definition(resolved: Any, node_type: str, settings: dict[str, Any]) -> Any:
    if not isinstance(resolved, dict):
        return None
    candidates = []
    if node_type == 'smart-comfy-workflow':
        candidates.extend([resolved.get('workflow'), resolved.get('workflow_json')])
    else:
        mode = str(settings.get('rhMode') or '').strip().lower()
        config_key = str(settings.get('rhConfigKey') or '').strip().lower()
        if mode == 'workflow' or config_key.startswith('workflow:'):
            candidates.extend([resolved.get('workflowJson'), resolved.get('workflow_json')])
    data = resolved.get('data') if isinstance(resolved.get('data'), dict) else {}
    candidates.extend([data.get('workflowJson'), data.get('workflow_json'), data.get('workflow')])
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            return copy.deepcopy(candidate)
    if node_type == 'smart-comfy-workflow':
        candidate = settings.get('comfyWorkflowDefinition') or settings.get('comfyWorkflowJson')
        if isinstance(candidate, dict) and candidate:
            return copy.deepcopy(candidate)
    else:
        candidate = settings.get('rhWorkflowJson')
        if isinstance(candidate, dict) and candidate:
            return copy.deepcopy(candidate)
    return None


def _validated_dynamic_snapshot(value: Any, node_type: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get('version') != 1 or value.get('node_type') != node_type:
        raise ValueError('已接受的动态工作流快照不存在或与节点类型不匹配')
    fields = value.get('fields')
    if not isinstance(fields, list) or not fields or len(fields) > 1024:
        raise ValueError('已接受的动态字段 Schema 无效')
    safe_fields = _safe_schema_fields([field for field in fields if isinstance(field, dict)], node_type)
    if len(safe_fields) != len(fields):
        raise ValueError('已接受的动态字段 Schema 包含凭据字段')
    snapshot = {'version': 1, 'node_type': node_type, 'fields': safe_fields}
    definition = value.get('workflow_definition')
    if definition is not None:
        if not isinstance(definition, (dict, list)) or not definition:
            raise ValueError('已接受的动态工作流定义无效')
        _reject_dynamic_secrets(definition)
        snapshot['workflow_definition'] = copy.deepcopy(definition)
    if value.get('optional_image_mode'):
        snapshot['optional_image_mode'] = str(value['optional_image_mode'])[:80]
    return snapshot


def _reject_dynamic_secrets(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _secret_identifier(key):
                raise ValueError('工作流定义包含不允许保存的凭据字段')
            _reject_dynamic_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _reject_dynamic_secrets(child)
async def _invoke(callback: Callable[..., Any] | None, *args: Any) -> Any:
    """调用同步/异步回调，并兼容主控只接收所需前缀参数的函数。"""
    if callback is None:
        raise ValueError('缺少执行回调')
    call_args = args
    try:
        signature = inspect.signature(callback)
        parameters = list(signature.parameters.values())
        if not any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
            positional = [parameter for parameter in parameters if parameter.kind in (
                inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD
            )]
            call_args = args[:len(positional)]
    except (TypeError, ValueError):
        pass
    result = callback(*call_args)
    if inspect.isawaitable(result):
        return await result
    return result


async def _invoke_threaded(callback: Callable[..., Any] | None, *args: Any) -> Any:
    """在线程中运行已有同步平台函数；不让 ComfyUI 渲染阻塞事件循环。"""
    if callback is None:
        raise ValueError('缺少执行回调')
    if inspect.iscoroutinefunction(callback):
        return await _invoke(callback, *args)
    call_args = args
    try:
        signature = inspect.signature(callback)
        parameters = list(signature.parameters.values())
        if not any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
            positional = [parameter for parameter in parameters if parameter.kind in (
                inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD
            )]
            call_args = args[:len(positional)]
    except (TypeError, ValueError):
        pass
    result = await asyncio.to_thread(callback, *call_args)
    if inspect.isawaitable(result):
        return await result
    return result


def _schema_fields(value: Any, *, comfy: bool = False) -> list[dict[str, Any]]:
    """从已有工作流/应用响应中取字段 Schema，不猜测平台字段。"""
    if isinstance(value, list):
        return [copy.deepcopy(item) for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    candidates = []
    if comfy:
        candidates.extend([
            value.get('config', {}).get('fields') if isinstance(value.get('config'), dict) else None,
            value.get('fields'), value.get('workflowFields'),
        ])
    else:
        candidates.extend([
            value.get('fields'), value.get('rhFields'), value.get('nodeInfoList'),
            value.get('data', {}).get('fields') if isinstance(value.get('data'), dict) else None,
            value.get('data', {}).get('nodeInfoList') if isinstance(value.get('data'), dict) else None,
            value.get('workflow') if isinstance(value.get('workflow'), (dict, list)) else None,
        ])
    for candidate in candidates:
        fields = _schema_fields(candidate, comfy=comfy)
        if fields:
            return fields
    return []


def _task_id_from_submission(value: Any) -> str:
    if not isinstance(value, dict):
        return ''
    candidates = [
        value.get('task_id'), value.get('taskId'), value.get('provider_task_id'),
        value.get('data', {}).get('taskId') if isinstance(value.get('data'), dict) else None,
        value.get('data', {}).get('task_id') if isinstance(value.get('data'), dict) else None,
        value.get('result', {}).get('taskId') if isinstance(value.get('result'), dict) else None,
    ]
    return next((str(item).strip() for item in candidates if str(item or '').strip()), '')


def _query_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    data = value.get('data')
    if isinstance(data, dict) and not any(key in value for key in ('status', 'state', 'urls', 'images', 'outputs')):
        return data
    return value


def _media_kind(url: str, item: dict[str, Any] | None = None, *, strict: bool = False) -> str:
    item = item or {}
    if strict:
        aliases = {'image': 'image', 'video': 'video', 'audio': 'audio', 'text': 'text'}
        declared_types = [str(item.get(key) or '').strip().lower() for key in (
            'mime_type', 'mimeType', 'mime', 'content_type', 'contentType',
            'mediaType', 'media_type', 'fileType', 'file_type',
        )]
        for declared_type in declared_types:
            if declared_type in aliases:
                return aliases[declared_type]
            if '/' in declared_type and declared_type.split('/', 1)[0] in aliases.values():
                return declared_type.split('/', 1)[0]
        source_url = str(item.get('_source_url') or url or '')
        suffix = source_url.split('?', 1)[0].split('#', 1)[0].lower()
        if any(suffix.endswith(ext) for ext in ('.txt', '.md', '.markdown', '.json', '.csv', '.yaml', '.yml', '.srt', '.vtt', '.log')):
            return 'text'
        mime = mimetypes.guess_type(source_url)[0] or ''
    else:
        explicit = str(item.get('kind') or item.get('mediaKind') or item.get('type') or '').strip().lower()
        if explicit in {'image', 'video', 'audio', 'text', 'file'} and explicit != 'file':
            return explicit
        mime = str(item.get('mime') or item.get('mimeType') or item.get('contentType') or item.get('content_type') or
                   item.get('fileType') or item.get('file_type') or mimetypes.guess_type(str(url or ''))[0] or '').lower()
    if mime.startswith('image/'):
        return 'image'
    if mime.startswith('video/'):
        return 'video'
    if mime.startswith('audio/'):
        return 'audio'
    if mime.startswith('text/'):
        return 'text'
    return 'file' if strict else 'image'


def _normalize_runninghub_result(value: Any, *, strict: bool = False) -> dict[str, Any]:
    """把既有 RunningHub 查询返回统一成 studio_collect 可保存的结果形状。"""
    payload = copy.deepcopy(_query_payload(value))
    if not payload:
        return {}
    if not strict and any(payload.get(key) for key in ('images', 'videos', 'audios', 'texts', 'files')):
        return payload

    if strict:
        raw = payload.get('raw') if isinstance(payload.get('raw'), dict) else {}
        raw_data = raw.get('data') if isinstance(raw, dict) else None
        raw_entries = []
        if isinstance(raw_data, list):
            raw_items = raw_data
        elif isinstance(raw_data, dict):
            raw_items = next((raw_data.get(key) for key in ('outputs', 'results', 'files', 'data')
                              if isinstance(raw_data.get(key), list)), [])
            if not raw_items and (raw_data.get('fileUrl') or raw_data.get('url')):
                raw_items = [raw_data]
        else:
            raw_items = []
        for raw_item in raw_items:
            if isinstance(raw_item, str):
                raw_entries.append({'url': raw_item, 'source': None})
            elif isinstance(raw_item, dict):
                raw_url = (raw_item.get('fileUrl') or raw_item.get('file_url') or raw_item.get('url') or
                           raw_item.get('downloadUrl') or raw_item.get('download_url'))
                if isinstance(raw_url, list):
                    raw_entries.extend({'url': url, 'source': raw_item} for url in raw_url if url)
                elif raw_url:
                    raw_entries.append({'url': raw_url, 'source': raw_item})
        prior_items = payload.get('image_items') or payload.get('items') or []
        if not isinstance(prior_items, list):
            prior_items = []
        prior_urls = payload.get('urls') or payload.get('outputs') or []
        if not isinstance(prior_urls, list):
            prior_urls = [prior_urls]
        if raw_entries:
            entries = []
            for index, raw_entry in enumerate(raw_entries):
                cached = prior_items[index] if index < len(prior_items) and isinstance(prior_items[index], dict) else {}
                url = cached.get('url') or (prior_urls[index] if index < len(prior_urls) else '') or raw_entry.get('url')
                source = raw_entry.get('source') if isinstance(raw_entry, dict) else None
                item = copy.deepcopy(source) if isinstance(source, dict) else {}
                item['_source_url'] = str(raw_entry.get('url') or '')
                if isinstance(cached, dict):
                    for metadata_key in ('content_type', 'contentType', 'mime', 'mimeType', 'fileType', 'file_type'):
                        if cached.get(metadata_key) and not item.get(metadata_key):
                            item[metadata_key] = cached[metadata_key]
                item['url'] = str(url or '')
                entries.append(item)
        else:
            entries = []
            for key in ('images', 'videos', 'audios', 'texts', 'files'):
                values = payload.get(key)
                if values is None:
                    continue
                if not isinstance(values, list):
                    values = [values]
                entries.extend(value if isinstance(value, dict) else {'url': value} for value in values)
            if not entries:
                entries = []
            for value in prior_items:
                item = copy.deepcopy(value) if isinstance(value, dict) else {'url': value}
                # image_items 是旧查询结果的 UI 投影，kind 可能来自其未知→image 兜底。
                item.pop('kind', None)
                item.pop('mediaKind', None)
                item.pop('type', None)
                entries.append(item)
            known = {str(item.get('url') or '') for item in entries}
            entries.extend({'url': url} for url in prior_urls if str(url or '') not in known)
        normalized = {key: copy.deepcopy(value) for key, value in payload.items()
                      if key in {'status', 'state', 'task_id', 'taskId', 'provider_task_id', 'success', 'pending', 'jimeng_pending', 'failReason', 'text'}}
        for item in entries:
            url = str(item.get('url') or item.get('value') or '').strip()
            if not url:
                continue
            item['url'] = url
            kind = _media_kind(url, item, strict=True)
            item.pop('_source_url', None)
            item['kind'] = kind
            normalized.setdefault({'image': 'images', 'video': 'videos', 'audio': 'audios', 'text': 'texts', 'file': 'files'}[kind], []).append(item)
        return normalized

    items = payload.get('image_items') or payload.get('items') or []
    urls = payload.get('urls') or payload.get('outputs') or []
    if not isinstance(items, list):
        items = []
    if not isinstance(urls, list):
        urls = [urls]
    entries = [item if isinstance(item, dict) else {'url': item} for item in items]
    known_urls = {str(item.get('url') or '') for item in entries}
    entries.extend({'url': url} for url in urls if str(url or '') not in known_urls)
    for item in entries:
        url = str(item.get('url') or item.get('value') or '').strip()
        if not url:
            continue
        item['url'] = url
        kind = _media_kind(url, item)
        item['kind'] = kind
        payload.setdefault({'image': 'images', 'video': 'videos', 'audio': 'audios', 'text': 'texts', 'file': 'files'}[kind], []).append(item)
    return payload


class StudioAppExecution:
    """服务端执行 ``smart-ai-app`` 和 ``smart-comfy-workflow`` 节点。

    回调契约：

    * ``preflight(canvas, node, request, request_id)``：调用现有画布真实预检。
    * ``local_comfy_generate(request)``：接收包含 ``platform_request``、工作流
      字段和已投影 ``params`` 的规范请求，调用现有 ``GenerateRequest``/``generate`` 路径。
    * ``runninghub_submit(request)``：接收包含 ``app_id``/``workflow_id``、
      ``node_info_list``、计费方式和地区的规范请求；只提交一次。
    * ``runninghub_query(provider_task_id, request)``：接收上一次提交返回的任务
      ID 和原请求，调用现有 RunningHub 查询路径。
    * ``upload_runninghub_asset(ref, request)``、``upload_comfy_media(ref, request)``：
      可选，分别复用既有素材上传接口，返回平台字段值。
    * ``collect(result, request, task)``：复用现有结果存储，返回画布媒体引用列表。

    回调可以是同步函数或 async 函数。模块不重试提交；查询失败、上游失败和
    本地取消只会结束当前任务，避免页面重开或异常恢复导致重复付费。
    """

    def __init__(
        self,
        *,
        load_canvas: Callable[[str], dict[str, Any]],
        save_canvas: Callable[[dict[str, Any]], Any],
        lock: Any,
        storage: Any,
        preflight: Callable[..., Any],
        collect: Callable[..., Any],
        notify: Callable[..., Any],
        local_comfy_generate: Callable[..., Any] | None = None,
        runninghub_submit: Callable[..., Any] | None = None,
        runninghub_query: Callable[..., Any] | None = None,
        resolve_runninghub_fields: Callable[..., Any] | None = None,
        resolve_comfy_fields: Callable[..., Any] | None = None,
        upload_runninghub_asset: Callable[..., Any] | None = None,
        upload_comfy_media: Callable[..., Any] | None = None,
        task_metadata: Callable[..., Any] | None = None,
        poll_interval: float = 1.6,
        max_polls: int = 720,
    ):
        self.load = load_canvas
        self.save = save_canvas
        self.lock = lock
        self.storage = storage
        self.preflight = preflight
        self.collect = collect
        self.notify = notify
        self.local_comfy_generate = local_comfy_generate
        self.runninghub_submit = runninghub_submit
        self.runninghub_query = runninghub_query
        self.resolve_runninghub_fields = resolve_runninghub_fields
        self.resolve_comfy_fields = resolve_comfy_fields
        self.upload_runninghub_asset = upload_runninghub_asset
        self.upload_comfy_media = upload_comfy_media
        self.task_metadata = task_metadata
        self.poll_interval = max(0.0, float(poll_interval))
        self.max_polls = max(1, int(max_polls))
        self.handles: dict[str, asyncio.Task] = {}

    async def _prepare_request(
        self,
        canvas: dict[str, Any],
        node: dict[str, Any],
        request_id: str,
        *,
        freeze_dynamic_snapshot: bool = False,
        resolved_schema: Any = None,
        accepted_dynamic_snapshot: Any = None,
    ) -> dict[str, Any]:
        node_type = node.get('type')
        settings = node.get('runSettings') or {}
        dynamic_snapshot = None
        if node_type == 'smart-ai-app':
            if accepted_dynamic_snapshot is not None:
                dynamic_snapshot = _validated_dynamic_snapshot(accepted_dynamic_snapshot, node_type)
                resolved = {'fields': copy.deepcopy(dynamic_snapshot['fields'])}
                if dynamic_snapshot.get('workflow_definition'):
                    resolved['workflowJson'] = copy.deepcopy(dynamic_snapshot['workflow_definition'])
                if dynamic_snapshot.get('optional_image_mode'):
                    resolved['optionalImageMode'] = dynamic_snapshot['optional_image_mode']
            elif resolved_schema is not None:
                resolved = copy.deepcopy(resolved_schema)
            elif self.resolve_runninghub_fields:
                config_key = str(settings.get('rhConfigKey') or '').strip()
                entry_id = config_key.split(':', 1)[1] if ':' in config_key else str(
                    settings.get('rhWorkflowId') or settings.get('rhAppId') or config_key
                )
                resolved = await _invoke(self.resolve_runninghub_fields, entry_id, node, canvas)
            else:
                resolved = {'fields': settings.get('rhFields') or settings.get('rhSchemaSnapshot') or []}
            fields = _schema_fields(resolved)
            if freeze_dynamic_snapshot:
                enabled_flags_present = any(isinstance(field, dict) and 'enabled' in field for field in fields)
                if enabled_flags_present:
                    fields = [field for field in fields if field.get('enabled') is True]
                fields = _safe_schema_fields(fields, node_type)
            if not fields:
                raise ValueError('AI 应用缺少安全、启用中的字段 Schema')
            if freeze_dynamic_snapshot and dynamic_snapshot is None:
                dynamic_snapshot = {
                    'version': 1,
                    'node_type': node_type,
                    'fields': copy.deepcopy(fields),
                }
                definition = _workflow_definition(resolved, node_type, settings)
                if definition is not None:
                    _reject_dynamic_secrets(definition)
                    dynamic_snapshot['workflow_definition'] = definition
                optional_mode = (resolved.get('optionalImageMode') or resolved.get('optional_image_mode')) if isinstance(resolved, dict) else None
                if optional_mode:
                    dynamic_snapshot['optional_image_mode'] = str(optional_mode)[:80]
                dynamic_snapshot = _validated_dynamic_snapshot(dynamic_snapshot, node_type)
            request_node = node
            mode = str(settings.get('rhMode') or '').strip().lower()
            config_key = str(settings.get('rhConfigKey') or '').strip().lower()
            if (mode == 'workflow' or config_key.startswith('workflow:')) and isinstance(resolved, dict):
                workflow_json = resolved.get('workflowJson') or resolved.get('workflow_json')
                if not workflow_json and isinstance(resolved.get('data'), dict):
                    workflow_json = resolved['data'].get('workflowJson') or resolved['data'].get('workflow_json')
                if workflow_json and (freeze_dynamic_snapshot or not settings.get('rhWorkflowJson')):
                    request_node = copy.deepcopy(node)
                    request_settings = request_node.setdefault('runSettings', {})
                    request_settings['rhWorkflowJson'] = copy.deepcopy(workflow_json)
                    optional_mode = resolved.get('optionalImageMode') or resolved.get('optional_image_mode')
                    if optional_mode and not request_settings.get('rhOptionalImageMode'):
                        request_settings['rhOptionalImageMode'] = optional_mode
            request = request_for(canvas, request_node, app_fields=fields)
        elif node_type == 'smart-comfy-workflow':
            if accepted_dynamic_snapshot is not None:
                dynamic_snapshot = _validated_dynamic_snapshot(accepted_dynamic_snapshot, node_type)
                resolved = {
                    'config': {'fields': copy.deepcopy(dynamic_snapshot['fields'])},
                }
                if dynamic_snapshot.get('workflow_definition'):
                    resolved['workflow'] = copy.deepcopy(dynamic_snapshot['workflow_definition'])
            elif resolved_schema is not None:
                resolved = copy.deepcopy(resolved_schema)
            elif self.resolve_comfy_fields:
                workflow_name = str(settings.get('comfyWorkflow') or '').strip()
                resolved = await _invoke(self.resolve_comfy_fields, workflow_name, node, canvas)
            else:
                resolved = {'fields': settings.get('comfyFields') or settings.get('workflowFields') or []}
            fields = _schema_fields(resolved, comfy=True)
            if freeze_dynamic_snapshot:
                enabled_flags_present = any(isinstance(field, dict) and 'enabled' in field for field in fields)
                if enabled_flags_present:
                    fields = [field for field in fields if field.get('enabled') is True]
                fields = _safe_schema_fields(fields, node_type)
            if not fields:
                raise ValueError('本地 ComfyUI 工作流缺少安全、启用中的字段 Schema')
            if freeze_dynamic_snapshot and dynamic_snapshot is None:
                dynamic_snapshot = {
                    'version': 1,
                    'node_type': node_type,
                    'fields': copy.deepcopy(fields),
                }
                definition = _workflow_definition(resolved, node_type, settings)
                if definition is not None:
                    _reject_dynamic_secrets(definition)
                    dynamic_snapshot['workflow_definition'] = definition
                dynamic_snapshot = _validated_dynamic_snapshot(dynamic_snapshot, node_type)
            request = request_for(canvas, node, comfy_fields=fields)
        else:
            raise ValueError('此服务只接受 AI 应用和 ComfyUI 节点')
        if freeze_dynamic_snapshot:
            self._validate_explicit_dynamic_inputs(canvas, node, request, fields, node_type)
            self._validate_dynamic_parameter_overrides(node, fields, node_type)
        request['request_id'] = str(request_id)
        request['client_id'] = str(settings.get('clientId') or settings.get('client_id') or request_id)
        if str(canvas.get('id') or '') == 'hypit-settings':
            # Hypit 的动态工作流必须根据真实类型或 MIME 分类；未知文件不能回退成图片。
            request['strict_result'] = True
        if request['kind'] == 'comfy':
            request['platform_request'] = {
                'prompt': request.get('prompt', ''),
                'workflow_json': request.get('workflow_json', ''),
                'params': copy.deepcopy(request.get('params') or {}),
                'type': 'workflow-custom',
                'client_id': request['client_id'],
            }
        else:
            request['platform_request'] = {
                'webappId': request.get('app_id', ''),
                'workflowId': request.get('workflow_id', ''),
                'nodeInfoList': copy.deepcopy(request.get('node_info_list') or []),
                'useWallet': bool(request.get('use_wallet')),
                'instanceType': request.get('instance_type', ''),
                'region': request.get('region', ''),
            }
            if request.get('workflow'):
                request['platform_request']['workflow'] = copy.deepcopy(request['workflow'])
        if freeze_dynamic_snapshot and dynamic_snapshot is not None:
            request[_REQUEST_DYNAMIC_SNAPSHOT_KEY] = copy.deepcopy(dynamic_snapshot)
        return request

    @staticmethod
    def _validate_explicit_dynamic_inputs(
        canvas: dict[str, Any], node: dict[str, Any], request: dict[str, Any],
        fields: list[dict[str, Any]], node_type: str,
    ) -> None:
        refs = request.get('references') if isinstance(request.get('references'), list) else []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            target_key = str(ref.get('targetFieldKey') or ref.get('target_field_key') or '').strip()
            if not target_key:
                continue
            field = next((entry for entry in fields if _schema_field_key(entry, node_type) == target_key), None)
            if field is None or field.get('enabled') is False:
                raise ValueError(f'显式动态字段 {target_key} 已不存在或未启用，请重新选择字段')
            if _secret_identifier(target_key) or _schema_field_media_kind(field, node_type) != str(ref.get('kind') or '').strip().lower():
                raise ValueError(f'显式动态字段 {target_key} 的类型与本次输入不匹配')

    @staticmethod
    def _validate_dynamic_parameter_overrides(
        node: dict[str, Any], fields: list[dict[str, Any]], node_type: str,
    ) -> None:
        override_keys = node.get('hypitTaskParameterOverrideKeys')
        if not isinstance(override_keys, list):
            return
        settings = node.get('runSettings') if isinstance(node.get('runSettings'), dict) else {}
        values = settings.get('rhParams') if node_type == 'smart-ai-app' else settings.get('comfyParams')
        values = values if isinstance(values, dict) else {}
        field_by_key = {_schema_field_key(field, node_type): field for field in fields}
        for raw_key in override_keys:
            key = str(raw_key)
            field = field_by_key.get(key)
            if field is None or key not in values:
                raise ValueError(f'动态流程参数 {key} 不属于当前启用的字段 Schema')
            value = values[key]
            if isinstance(value, dict) and 'value' in value:
                value = value.get('value')
            raw_type = str(field.get('fieldType') or field.get('type') or field.get('kind') or '').strip().lower()
            valid = True
            if raw_type in {'boolean', 'bool'}:
                valid = isinstance(value, bool)
            elif raw_type in {'integer', 'int'}:
                valid = isinstance(value, int) and not isinstance(value, bool)
            elif raw_type in {'number', 'float', 'slider'}:
                valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
            elif raw_type in {'string', 'text', 'plain-text', 'textarea'}:
                valid = isinstance(value, str)
            elif raw_type in {'select', 'switch', 'combo', 'dropdown', 'list', 'enum'}:
                valid = isinstance(value, str)
            else:
                valid = False
            if not valid:
                raise ValueError(f'动态流程参数 {key} 与当前字段类型不匹配')

    async def submit(self, canvas: dict[str, Any], node: dict[str, Any], request_id: str) -> dict[str, Any]:
        if node.get('type') not in APP_NODE_TYPES:
            raise ValueError('此服务只接受 AI 应用和 ComfyUI 节点')
        task_id = 'studio_app_' + hashlib.sha256(
            f"{canvas['id']}:{node['id']}:{request_id}".encode()
        ).hexdigest()[:32]
        existing = self.storage.get_canvas_task(task_id)
        if existing:
            return {'task_ids': [task_id], 'status': existing['status']}
        request = await self._prepare_request(canvas, node, request_id)
        task_metadata = self.task_metadata(canvas, node, request) if self.task_metadata else {}
        if not isinstance(task_metadata, dict):
            raise ValueError('task_metadata 必须返回对象')
        validated = await _invoke(self.preflight, canvas, node, request, request_id)
        with self.lock:
            existing = self.storage.get_canvas_task(task_id)
            if existing:
                return {'task_ids': [task_id], 'status': existing['status']}
            latest = self.load(canvas['id'])
            current = next((item for item in latest.get('nodes', []) if item.get('id') == node.get('id')), None)
            if current is None or recipe(current) != recipe(node):
                raise ValueError('预检期间节点已修改，请重新读取后运行')
            if self.task_metadata:
                latest_metadata = self.task_metadata(latest, current, request)
                if latest_metadata != task_metadata:
                    raise ValueError('预检期间 Hypit 流程或输入结果已修改，请重新读取后运行')
            current.setdefault('creationId', 'creation_' + uuid.uuid4().hex)
            if current.get('creationOwnerNodeId', current['id']) != current['id']:
                current['creationParentId'] = current['creationId']
                current['creationId'] = 'creation_' + uuid.uuid4().hex
            current['creationOwnerNodeId'] = current['id']
            current['creationRevision'] = current.get('creationRevision', 0) + 1
            signature = stable(recipe(current))
            current['creationSignature'] = signature
            task = {
                **copy.deepcopy(current), 'id': task_id, 'type': 'smart-material',
                'creationType': current['type'], 'sourceExecutionNodeId': current['id'],
                'creationTask': True, 'runStatus': 'queued', 'isRunPlaceholder': True,
                'pending': 1, 'runStartedAt': int(time.time() * 1000), 'images': [],
                'runInputRefs': request['references'], 'runPrompt': request.get('prompt', ''),
                'runRef': validated, 'creationSignature': signature, **copy.deepcopy(task_metadata),
            }
            for key in ('creationTasks', 'resultVersions'):
                task.pop(key, None)
            self.storage.create_canvas_task({
                'id': task_id, 'status': 'queued', 'kind': request['kind'],
                'canvas_id': canvas['id'], 'node_id': node['id'], 'request': request,
                'creation_snapshot': task, **copy.deepcopy(task_metadata),
            })
            current.setdefault('creationTasks', []).append(task)
            self.save(latest)
        await _invoke(self.notify, latest)
        handle = asyncio.create_task(self._run(canvas['id'], task, request))
        self.handles[task_id] = handle
        handle.add_done_callback(lambda _: self.handles.pop(task_id, None))
        return {'task_ids': [task_id], 'status': 'queued'}

    async def _upload_value(self, callback, ref: dict[str, Any], request: dict[str, Any]) -> str:
        value = await _invoke(callback, ref, request)
        if isinstance(value, dict):
            value = value.get('fileName') or value.get('filename') or value.get('name') or value.get('url')
        return str(value or '').strip()

    async def _prepare_comfy_request(self, request: dict[str, Any]) -> dict[str, Any]:
        prepared = copy.deepcopy(request)
        fields = prepared.get('workflow_fields') or []
        refs_by_kind = {kind: [ref for ref in prepared.get('references', []) if ref.get('kind') == kind]
                        for kind in ('image', 'video', 'audio')}
        indexes = {kind: 0 for kind in refs_by_kind}
        values = prepared.get('workflow_values') or {}
        uploaded_by_url: dict[str, str] = {}
        for field in fields:
            raw = str(field.get('fieldType') or field.get('type') or field.get('kind') or '').strip().lower()
            if raw not in {'image', 'video', 'audio'}:
                continue
            if 'media_field_keys' in prepared:
                field_key = str(field.get('id') or field.get('paramid') or field.get('paramId') or field.get('key') or '')
                if field_key not in set(prepared.get('media_field_keys') or []):
                    continue
            kind = raw
            field_key = str(field.get('id') or field.get('paramid') or field.get('paramId') or field.get('key') or '')
            current_value = values.get(field_key)
            ref = next((item for item in refs_by_kind[kind]
                        if str(item.get('url') or item.get('path') or '') == str(current_value or '')
                        ), None)
            if ref is None and 'media_field_keys' not in prepared:
                index = indexes[kind]
                ref = refs_by_kind[kind][index] if index < len(refs_by_kind[kind]) else None
                indexes[kind] += 1
            if ref is None and field_key in set(prepared.get('media_field_keys') or []):
                raise ValueError(f'工作流媒体字段 {field_key} 没有匹配的引用素材')
            if not ref or ref.get('comfy_name') or not self.upload_comfy_media:
                continue
            reference_key = str(ref.get('url') or ref.get('path') or '')
            uploaded = uploaded_by_url.get(reference_key)
            if not uploaded:
                uploaded = await self._upload_value(self.upload_comfy_media, ref, prepared)
                if uploaded:
                    uploaded_by_url[reference_key] = uploaded
            if uploaded:
                field_node = str(field.get('node') or field.get('nodeId') or '')
                field_input = str(field.get('input') or field.get('fieldName') or '')
                values[field_key] = uploaded
                for node_id, node_inputs in (prepared.get('params') or {}).items():
                    if field_node == str(node_id) and isinstance(node_inputs, dict) and field_input:
                        node_inputs[field_input] = uploaded
        prepared['workflow_values'] = values
        prepared['parameters'] = values
        if isinstance(prepared.get('platform_request'), dict):
            prepared['platform_request']['params'] = copy.deepcopy(prepared.get('params') or {})
        return prepared

    async def _prepare_runninghub_request(self, request: dict[str, Any]) -> dict[str, Any]:
        prepared = copy.deepcopy(request)
        refs = prepared.get('references') or []
        refs_by_kind = {kind: [ref for ref in refs if ref.get('kind') == kind and ref.get('url')]
                        for kind in ('image', 'video', 'audio')}
        uploaded_by_url: dict[str, str] = {}
        for field in prepared.get('fields') or []:
            raw = str(field.get('fieldType') or field.get('type') or field.get('kind') or '').strip().lower()
            if raw not in refs_by_kind or not self.upload_runninghub_asset:
                continue
            node_id = str(field.get('nodeId') or field.get('node_id') or '').strip()
            field_name = str(field.get('fieldName') or field.get('field_name') or field.get('inputName') or '').strip()
            if not node_id or not field_name:
                param_id = str(field.get('paramid') or field.get('paramId') or field.get('key') or '').strip()
                if '::' in param_id:
                    node_id, field_name = (part.strip() for part in param_id.split('::', 1))
            key = f'{node_id}::{field_name}' if node_id or field_name else str(
                field.get('key') or field.get('paramid') or field.get('paramId') or ''
            ).strip()
            media_field_keys = set(prepared.get('media_field_keys') or [])
            if 'media_field_keys' in prepared and key not in media_field_keys:
                continue
            value = (prepared.get('app_field_values') or {}).get(key)
            ref = next((item for item in refs_by_kind[raw] if str(item.get('url')) == str(value)), None)
            if ref is None and 'media_field_keys' not in prepared:
                ref = next((item for item in refs_by_kind[raw] if id(item) not in used), None)
            if ref is None and key in media_field_keys:
                raise ValueError(f'工作流媒体字段 {key} 没有匹配的引用素材')
            if ref is None:
                continue
            reference_key = str(ref.get('url') or '')
            uploaded = uploaded_by_url.get(reference_key)
            if not uploaded:
                uploaded = await self._upload_value(self.upload_runninghub_asset, ref, prepared)
                if uploaded:
                    uploaded_by_url[reference_key] = uploaded
            if not uploaded:
                continue
            prepared.setdefault('app_field_values', {})[key] = uploaded
            prepared.setdefault('inputs', {})[key] = uploaded
            for item in prepared.get('node_info_list') or []:
                if str(item.get('nodeId')) == node_id and str(item.get('fieldName')) == field_name:
                    item['fieldValue'] = uploaded
        if isinstance(prepared.get('platform_request'), dict):
            prepared['platform_request']['nodeInfoList'] = copy.deepcopy(prepared.get('node_info_list') or [])
            if prepared.get('kind') == 'runninghub_workflow' and isinstance(prepared.get('workflow'), dict):
                workflow = copy.deepcopy(prepared['workflow'])
                if str(prepared.get('optional_image_mode') or 'prune-workflow').strip() == 'prune-workflow':
                    remove_ids: set[str] = set()
                    supplied = prepared.get('app_field_values') or {}
                    for field in prepared.get('fields') or []:
                        raw = str(field.get('fieldType') or field.get('type') or field.get('kind') or '').strip().lower()
                        if raw not in refs_by_kind or field.get('required') is True:
                            continue
                        node_id = str(field.get('nodeId') or field.get('node_id') or '').strip()
                        field_name = str(field.get('fieldName') or field.get('field_name') or field.get('inputName') or '').strip()
                        if not node_id or not field_name:
                            param_id = str(field.get('paramid') or field.get('paramId') or field.get('key') or '').strip()
                            if '::' in param_id:
                                node_id, field_name = (part.strip() for part in param_id.split('::', 1))
                        key = f'{node_id}::{field_name}' if node_id or field_name else str(
                            field.get('key') or field.get('paramid') or field.get('paramId') or ''
                        ).strip()
                        node = workflow.get(node_id)
                        if key in supplied or not isinstance(node, dict) or not isinstance(node.get('inputs'), dict):
                            continue
                        if field_name in node['inputs']:
                            del node['inputs'][field_name]
                        if not node['inputs']:
                            remove_ids.add(node_id)
                    for node_id in remove_ids:
                        workflow.pop(node_id, None)
                    for node in workflow.values():
                        if not isinstance(node, dict) or not isinstance(node.get('inputs'), dict):
                            continue
                        for input_name, value in list(node['inputs'].items()):
                            if (isinstance(value, list) and len(value) == 2
                                    and isinstance(value[1], int) and str(value[0]) in remove_ids):
                                del node['inputs'][input_name]
                for item in prepared.get('node_info_list') or []:
                    node = workflow.get(str(item.get('nodeId')))
                    field_name = str(item.get('fieldName') or '')
                    if isinstance(node, dict) and isinstance(node.get('inputs'), dict) and field_name:
                        if field_name in node['inputs']:
                            node['inputs'][field_name] = item.get('fieldValue')
                prepared['workflow'] = workflow
                prepared['platform_request']['workflow'] = copy.deepcopy(prepared['workflow'])
        return prepared

    async def _run_runninghub(self, request: dict[str, Any], on_submitted=None) -> dict[str, Any]:
        strict_result = request.get('strict_result') is True
        prepared = await self._prepare_runninghub_request(request)
        request.clear()
        request.update(prepared)
        submission = await _invoke(self.runninghub_submit, request)
        provider_task_id = _task_id_from_submission(submission)
        if not provider_task_id:
            normalized = _normalize_runninghub_result(submission, strict=strict_result)
            if any(normalized.get(key) for key in ('images', 'videos', 'audios', 'texts', 'files', 'text')):
                return normalized
            raise ValueError('RunningHub 提交成功但没有返回 taskId')
        request['provider_task_id'] = provider_task_id
        if on_submitted:
            await on_submitted(provider_task_id)
        last = {}
        for index in range(self.max_polls):
            if index and self.poll_interval:
                await asyncio.sleep(self.poll_interval)
            queried = await _invoke(self.runninghub_query, provider_task_id, request)
            payload = _query_payload(queried)
            last = payload
            status = str(payload.get('status') or payload.get('state') or '').strip().upper()
            normalized = _normalize_runninghub_result(queried, strict=strict_result)
            has_result = any(normalized.get(key) for key in ('images', 'videos', 'audios', 'texts', 'files', 'text'))
            has_typed_result = any(normalized.get(key) for key in ('images', 'videos', 'audios', 'texts', 'text'))
            if status in {'SUCCESS', 'SUCCEEDED', 'COMPLETED'} or (has_result and (not strict_result or has_typed_result)):
                return normalized
            if status in {'FAILED', 'FAIL', 'ERROR', 'CANCELLED', 'CANCELED', 'TIMEOUT', 'REVOKED'}:
                reason = payload.get('failReason') or payload.get('error') or payload.get('message') or status
                raise ValueError(f'RunningHub 任务失败：{reason}')
        raise TimeoutError(f'RunningHub 查询超时，任务编号：{provider_task_id}，最近状态：{last.get("status") or last.get("state") or "unknown"}')

    async def _generate(self, request: dict[str, Any], on_submitted=None) -> dict[str, Any]:
        if request['kind'] == 'comfy':
            prepared = await self._prepare_comfy_request(request)
            result = await _invoke_threaded(self.local_comfy_generate, prepared)
            return result if isinstance(result, dict) else {'outputs': result}
        if request['kind'] in RUNNINGHUB_KINDS:
            return await self._run_runninghub(request, on_submitted)
        raise ValueError('未支持的应用执行类型')

    async def _transition(self, canvas_id: str, task: dict[str, Any], status: str,
                          media: list[dict[str, Any]] | None = None, error: str = '') -> None:
        task.update(
            runStatus=status,
            pending=int(status in {'queued', 'running'}),
            isRunPlaceholder=status in {'queued', 'running'},
            error=error,
        )
        if status not in {'queued', 'running'}:
            task['runFinishedAt'] = int(time.time() * 1000)
        if media:
            task['images'] = media
        self.storage.update_canvas_task(
            task['id'], status=status, error=error,
            result={'media': media or [], 'creation_snapshot': task},
        )
        run_id = (task.get('runRef') or {}).get('run_id')
        if run_id and hasattr(self.storage, 'update_run_status'):
            self.storage.update_run_status(run_id, 'submitted' if status == 'running' else status, error=error)
        with self.lock:
            canvas = self.load(canvas_id)
            if not canvas:
                return
            for node in canvas.get('nodes', []):
                for index, prior in enumerate(node.get('creationTasks', [])):
                    if prior.get('id') == task['id']:
                        node['creationTasks'][index] = copy.deepcopy(task)
                if media and node.get('creationId') == task.get('creationId') and stable(recipe(node)) == task.get('creationSignature'):
                    versions = node.setdefault('resultVersions', ([copy.deepcopy(node)] if node.get('images') else []))
                    version = copy.deepcopy(task)
                    version.update(type=task['creationType'], outputKind=media[0].get('kind', 'file'))
                    old = next((index for index, item in enumerate(versions) if item.get('id') == task['id']), None)
                    if old is None:
                        versions.append(version)
                        old = len(versions) - 1
                    else:
                        versions[old] = version
                    node.update(
                        activeResultVersion=old, images=copy.deepcopy(media), sourceKind='result',
                        outputKind=media[0].get('kind', 'file'),
                        creationRevision=node.get('creationRevision', 0) + 1,
                    )
            self.save(canvas)
        await _invoke(self.notify, canvas)

    async def _run(self, canvas_id: str, task: dict[str, Any], request: dict[str, Any]) -> None:
        try:
            await self._transition(canvas_id, task, 'running')
            async def remember_submission(provider_task_id):
                task['providerTaskId'] = provider_task_id
                await self._transition(canvas_id, task, 'running')
            result = await self._generate(request, remember_submission)
            if request.get('provider_task_id'):
                task['providerTaskId'] = request['provider_task_id']
            if result.get('error'):
                raise ValueError(str(result['error']))
            if result.get('pending') or result.get('jimeng_pending'):
                task['upstreamPending'] = copy.deepcopy(result)
                await self._transition(canvas_id, task, 'recoverable', error='上游仍在运行，需查询原任务')
                return
            media = await _invoke(self.collect, result, request, task)
            if not media:
                raise ValueError('接口没有返回可保存的结果')
            await self._transition(canvas_id, task, 'succeeded', media=media)
        except asyncio.CancelledError:
            await self._transition(canvas_id, task, 'cancelled', error='已取消本地任务；已提交的上游请求可能仍在运行')
        except Exception as exc:
            await self._transition(canvas_id, task, 'failed', error=str(getattr(exc, 'detail', None) or exc))

    async def cancel(self, canvas: dict[str, Any], node: dict[str, Any], task_id: str) -> dict[str, Any]:
        task = self.storage.get_canvas_task(task_id)
        if not task or task.get('canvas_id') != canvas.get('id') or task.get('node_id') != node.get('id'):
            raise ValueError('当前节点不存在此任务')
        handle = self.handles.get(task_id)
        if handle:
            handle.cancel()
            await asyncio.gather(handle, return_exceptions=True)
            current = self.storage.get_canvas_task(task_id)
            if current and current.get('status') in {'queued', 'running'}:
                await self._transition(
                    canvas['id'], task['creation_snapshot'], 'cancelled',
                    error='已取消本地任务；已提交的上游请求可能仍在运行',
                )
        return self.storage.get_canvas_task(task_id)


def create_studio_app_execution(**callbacks: Any) -> StudioAppExecution:
    """主控装配入口；参数与 ``StudioAppExecution`` 构造器一一对应。

    主控在画布节点运行入口调用 ``await service.submit(canvas, node, request_id)``，
    在取消入口调用 ``await service.cancel(canvas, node, task_id)``。提交回调收到的
    是规范请求；其中 ``platform_request`` 可直接适配现有 GenerateRequest、
    RunningHub 应用提交或 RunningHub 工作流提交，而无需在本模块创建 HTTP 客户端。
    """
    return StudioAppExecution(**callbacks)


__all__ = ['APP_NODE_TYPES', 'StudioAppExecution', 'create_studio_app_execution']
