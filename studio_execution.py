"""与页面生命周期无关的创作执行；模型协议和素材存储通过明确回调复用。"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import mimetypes
import time
import uuid


FIELDS = {
    'smart-text-generator': ('text', 'textProvider', 'textModel'),
    'smart-image-generator': ('image', 'provider_id', 'model'),
    'smart-video-generator': ('video', 'videoProvider', 'videoModel'),
    'smart-audio-generator': ('audio', 'audioProvider', 'audioModel'),
    'smart-music-generator': ('music', 'musicProvider', 'musicModel'),
    'smart-ai-app': ('ai_application', 'runninghub', 'rhConfigKey'),
    'smart-comfy-workflow': ('comfy', 'comfy', 'comfyWorkflow'),
}


def stable(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def recipe(node):
    return {key: copy.deepcopy(node.get(key, default)) for key, default in (
        ('type', ''), ('runSettings', {}), ('promptDraftText', ''), ('manualInputRefs', []),
        ('blockedInputRefs', []), ('inputRefOrder', []), ('creationInputBinding', []))}


def input_media(canvas, node):
    """引用顺序使用显式排序，再使用连线创建顺序；所属虚线不进入生成输入。"""
    found = []
    by_id = {item['id']: item for item in canvas.get('nodes', [])}

    def media_key(item, node_id='', index=0):
        """与画布前端稳定引用一致，并保留旧 node|index 形式用于迁移读取。"""
        explicit = str(item.get('key') or '').strip()
        if explicit:
            return explicit
        result_id = str(item.get('resultId') or item.get('result_id') or '').strip()
        if result_id:
            return f'result:{result_id}'
        item_node_id = str(item.get('nodeId') or item.get('node_id') or node_id or '').strip()
        image_index = item.get('imageIndex', item.get('image_index', index))
        try:
            image_index = int(image_index)
        except (TypeError, ValueError):
            image_index = index
        if item_node_id:
            return f'node:{item_node_id}:{image_index}'
        material_id = str(
            item.get('materialId') or item.get('material_id')
            or item.get('assetId') or item.get('asset_id') or ''
        ).strip()
        if material_id:
            return f'material:{material_id}'
        text = str(item.get('text', item.get('content', '')) or '').strip()
        if text:
            return f'text:{text}'
        return f"url:{item.get('url') or item.get('path') or item.get('src') or item.get('uri') or ''}"

    def media_keys(item, node_id='', index=0):
        key = media_key(item, node_id, index)
        aliases = {key}
        result_id = str(item.get('resultId') or item.get('result_id') or '').strip()
        if result_id:
            aliases.add(f'result:{result_id}')
        item_node_id = str(item.get('nodeId') or item.get('node_id') or node_id or '').strip()
        try:
            image_index = int(item.get('imageIndex', item.get('image_index', index)))
        except (TypeError, ValueError):
            image_index = index
        if item_node_id:
            aliases.update({f'node:{item_node_id}:{image_index}', f'{item_node_id}|{image_index}'})
        return aliases

    def select_source_items(source, source_id, link):
        source_version_id = str(link.get('sourceVersionId') or link.get('source_version_id') or '').strip()
        if source_version_id:
            source = next((version for version in source.get('resultVersions', [])
                           if str(version.get('id') or '') == source_version_id), None)
            if source is None:
                raise ValueError('引用的历史版本不存在')
        items = list(source.get('images') or [])
        if not items and source.get('type') == 'smart-text-generator' and str(source.get('promptDraftText') or '').strip():
            items = [{'kind': 'text', 'text': str(source['promptDraftText']), 'content': str(source['promptDraftText'])}]
        source_result_id = str(link.get('sourceResultId') or link.get('source_result_id') or '').strip()
        if source_result_id:
            items = [item for item in items if str(item.get('resultId') or item.get('result_id') or '') == source_result_id]
        source_media_key = str(link.get('sourceMediaKey') or link.get('source_media_key') or '').strip()
        selected = []
        for index, media in enumerate(items):
            if source_media_key and source_media_key not in media_keys(media, source_id, index):
                continue
            selected.append({
                **copy.deepcopy(media),
                'nodeId': source_id,
                'imageIndex': index,
                **({'inputSourceNodeId': source_id} if source_id else {}),
                **({'inputSourceResultId': source_result_id} if source_result_id else {}),
                **({'targetFieldKey': str(link.get('targetFieldKey') or link.get('target_field_key') or '').strip()}
                   if str(link.get('targetFieldKey') or link.get('target_field_key') or '').strip() else {}),
            })
        return selected

    for link in canvas.get('connections', []):
        if link.get('to', link.get('target')) != node['id'] or link.get('kind') in {'story', 'history', 'result'}:
            continue
        source = by_id.get(link.get('from', link.get('source')))
        if not source:
            raise ValueError('引用的源节点不存在')
        source_id = link.get('from', link.get('source'))
        found.extend(select_source_items(source, source_id, link))
    found.extend(copy.deepcopy(node.get('manualInputRefs', [])))
    def identity(item):
        return media_key(item, item.get('nodeId', ''), item.get('imageIndex', 0))
    blocked = {str(x).strip() for x in node.get('blockedInputRefs', []) if not isinstance(x, dict)}
    blocked.update(identity(x) for x in node.get('blockedInputRefs', []) if isinstance(x, dict))
    unique = {}
    for item in found:
        if not item.get('kind'):
            mime = item.get('mime') or mimetypes.guess_type(item.get('name') or item.get('url', ''))[0] or ''
            item['kind'] = 'text' if item.get('text') or item.get('content') else mime.split('/')[0] if mime else 'image'
        key = identity(item)
        if key not in blocked and not (set(media_keys(item, item.get('nodeId', ''), item.get('imageIndex', 0))) & blocked):
            unique.setdefault(key, item)
    order = node.get('inputRefOrder', [])
    if order:
        ranks = {str(value): index for index, value in enumerate(order)}
        for item in unique.values():
            for alias in media_keys(item, item.get('nodeId', ''), item.get('imageIndex', 0)):
                ranks.setdefault(alias, ranks.get(identity(item), len(ranks)))
        return sorted(unique.values(), key=lambda item: min(
            (ranks.get(alias, len(ranks)) for alias in media_keys(item, item.get('nodeId', ''), item.get('imageIndex', 0))),
            default=len(ranks),
        ))
    return list(unique.values())


def request_for(canvas, node, *, app_fields=None, comfy_fields=None):
    node_type = node.get('type')
    if node_type not in FIELDS:
        raise ValueError('此执行类型尚未接入服务端任务；不能提交未适配请求')

    if node_type in {'smart-ai-app', 'smart-comfy-workflow'}:
        settings = node.get('runSettings') or {}
        refs = input_media(canvas, node)

        def field_parts(field):
            node_id = str(field.get('nodeId') or field.get('node_id') or '').strip()
            field_name = str(field.get('fieldName') or field.get('field_name') or field.get('inputName') or '').strip()
            if not node_id or not field_name:
                param_id = str(field.get('paramid') or field.get('paramId') or field.get('key') or '').strip()
                if '::' in param_id:
                    node_id, field_name = (part.strip() for part in param_id.split('::', 1))
            return node_id, field_name

        def field_key(field):
            if field.get('id') and node_type == 'smart-comfy-workflow':
                return str(field.get('id'))
            if node_type == 'smart-comfy-workflow':
                return str(field.get('paramid') or field.get('paramId') or field.get('key') or '')
            node_id, field_name = field_parts(field)
            if node_id or field_name:
                return f"{node_id}::{field_name}"
            return str(field.get('key') or field.get('paramid') or field.get('paramId') or '').strip()

        def field_kind(field):
            raw = str(field.get('fieldType') or field.get('type') or field.get('kind') or '').strip().lower()
            if raw in {'image', 'video', 'audio'}:
                return raw
            if node_type == 'smart-ai-app':
                if raw in {'string', 'text', 'plain-text'}:
                    return 'text'
                if raw in {'float', 'number', 'integer', 'int', 'slider'}:
                    return 'number'
                if raw in {'boolean', 'bool'}:
                    return 'boolean'
                if raw in {'select', 'switch', 'combo', 'dropdown', 'list', 'enum'}:
                    return 'select'
                return 'text'
            name = f"{field.get('input', '')} {field.get('name', '')} {field.get('fieldName', '')}".lower()
            if raw == 'textarea' or any(token in name for token in ('prompt', 'text', '提示词', '正向', '负向')):
                return 'prompt'
            return 'setting'

        def default_value(field):
            value = field.get('fieldValue', field.get('defaultValue', field.get('default')))
            if isinstance(value, list):
                return value[0] if value else ''
            return '' if isinstance(value, dict) or value is None else value

        def stored_value(field):
            values = settings.get('rhParams') if node_type == 'smart-ai-app' else settings.get('comfyParams')
            values = values or {}
            key = field_key(field)
            candidates = [key]
            if node_type == 'smart-ai-app':
                node_id, field_name = field_parts(field)
                candidates.extend([f"{node_id}::{field_name}", str(field.get('paramid') or '').strip()])
            else:
                candidates.extend([
                    str(field.get('paramid') or field.get('paramId') or '').strip(),
                    str(field.get('key') or '').strip(),
                ])
            value = next((values.get(candidate) for candidate in candidates if candidate and candidate in values), None)
            if isinstance(value, dict) and 'value' in value:
                return value.get('value')
            return value

        def coerce(field, value):
            raw = str(field.get('fieldType') or field.get('type') or field.get('kind') or '').strip().upper()
            if value in (None, ''):
                return value
            if raw in {'BOOLEAN', 'BOOL'}:
                if node_type == 'smart-ai-app':
                    return value
                return bool(value)
            if node_type == 'smart-comfy-workflow' and raw in {'DROPDOWN', 'SELECT', 'COMBO', 'LIST'} and isinstance(value, str):
                text = value.strip()
                try:
                    number = float(text)
                    return int(number) if number.is_integer() else number
                except (TypeError, ValueError):
                    return value
            if raw not in {'FLOAT', 'NUMBER', 'SLIDER', 'INT', 'INTEGER'}:
                return value
            try:
                number = float(str(value).strip())
            except (TypeError, ValueError) as exc:
                raise ValueError(f"字段“{field_key(field)}”要求数字，当前值为“{value}”") from exc
            if raw in {'INT', 'INTEGER'} and not number.is_integer():
                raise ValueError(f"字段“{field_key(field)}”要求整数，当前值为“{value}”")
            if node_type == 'smart-comfy-workflow' and raw not in {'INT', 'INTEGER'}:
                step = field.get('step')
                try:
                    if step in (None, '') or float(step) >= 1:
                        return int(round(number))
                except (TypeError, ValueError):
                    return int(round(number))
            return int(number) if raw in {'INT', 'INTEGER'} else number

        def ref_key(item):
            explicit = str(item.get('key') or '').strip()
            if explicit:
                return explicit
            result_id = str(item.get('resultId') or item.get('result_id') or '').strip()
            if result_id:
                return f'result:{result_id}'
            item_node = str(item.get('nodeId') or item.get('node_id') or '').strip()
            index = item.get('imageIndex', item.get('image_index', 0))
            if item_node:
                return f'node:{item_node}:{index}'
            material_id = str(item.get('materialId') or item.get('material_id') or item.get('assetId') or item.get('asset_id') or '').strip()
            if material_id:
                return f'material:{material_id}'
            text = str(item.get('text', item.get('content', '')) or '').strip()
            if text:
                return f'text:{text}'
            return f"url:{item.get('url') or item.get('path') or item.get('src') or item.get('uri') or ''}"

        def ref_aliases(item):
            aliases = {ref_key(item)}
            explicit = str(item.get('key') or '').strip()
            if explicit:
                aliases.add(explicit)
            result_id = str(item.get('resultId') or item.get('result_id') or '').strip()
            if result_id:
                aliases.add(f'result:{result_id}')
            node_id = str(item.get('nodeId') or item.get('node_id') or '').strip()
            if node_id:
                index = item.get('imageIndex', item.get('image_index', 0))
                aliases.update({f'node:{node_id}:{index}', f'{node_id}|{index}'})
            return aliases

        prompt = '\n\n'.join([str(node.get('promptDraftText') or '').strip()] + [
            str(ref.get('text', ref.get('content', ''))).strip() for ref in refs if ref.get('kind') == 'text'
        ]).strip()

        if node_type == 'smart-comfy-workflow':
            workflow_name = str(settings.get('comfyWorkflow') or '').strip()
            if not workflow_name:
                raise ValueError('请先选择本地 ComfyUI 工作流')
            fields = list(comfy_fields if comfy_fields is not None else (
                settings.get('comfyFields') or settings.get('workflowFields') or []
            ))
            fields = [field for field in fields if isinstance(field, dict)]
            if not fields:
                raise ValueError('本地 ComfyUI 工作流缺少字段 Schema')
            values = {}
            media_by_kind = {kind: [ref for ref in refs if ref.get('kind') == kind]
                             for kind in ('image', 'video', 'audio')}
            media_indexes = {kind: 0 for kind in media_by_kind}
            prompt_index = 0
            for field in fields:
                if not isinstance(field, dict):
                    continue
                field_node = field.get('node') or field.get('nodeId')
                field_input = field.get('input') or field.get('fieldName')
                if not field_node or not field_input:
                    continue
                kind = field_kind(field)
                key = field_key(field)
                if kind == 'prompt':
                    value = prompt if prompt_index == 0 else default_value(field)
                    prompt_index += 1
                elif kind in media_by_kind:
                    index = media_indexes[kind]
                    media_indexes[kind] += 1
                    ref = media_by_kind[kind][index] if index < len(media_by_kind[kind]) else None
                    value = (ref or {}).get('comfy_name') or (ref or {}).get('url') or ''
                else:
                    value = stored_value(field)
                    if value is None:
                        value = default_value(field)
                values[key] = coerce(field, value)
            params = {}
            for field in fields:
                if not isinstance(field, dict):
                    continue
                field_node = field.get('node') or field.get('nodeId')
                field_input = field.get('input') or field.get('fieldName')
                if not field_node or not field_input:
                    continue
                params.setdefault(str(field_node), {})[str(field_input)] = values.get(field_key(field))
            media = {kind: [ref for ref in refs if ref.get('kind') == kind and ref.get('url')]
                     for kind in ('image', 'video', 'audio')}
            return {
                'kind': 'comfy', 'engine': 'comfy', 'provider_id': 'local-comfyui', 'model': workflow_name,
                'workflow_json': workflow_name, 'workflow_fields': copy.deepcopy(fields),
                'workflow_values': values, 'params': params, 'parameters': values,
                'prompt': prompt, 'inputs': {'prompt': prompt, 'reference': [ref['url'] for ref in media['image']],
                                              'source_video': [ref['url'] for ref in media['video']],
                                              'reference_audio': [ref['url'] for ref in media['audio']]},
                'input_roles': {'prompt': 1 if prompt else 0, 'reference': len(media['image']),
                                'source_video': len(media['video']), 'reference_audio': len(media['audio'])},
                'input_counts': {'text': 1 if prompt else 0, **{key: len(value) for key, value in media.items()}},
                'references': refs, 'comfy_mode': settings.get('comfyMode') or 'custom',
            }

        config_key = str(settings.get('rhConfigKey') or '').strip()
        config_kind, _, config_id = config_key.partition(':')
        mode = str(settings.get('rhMode') or '').strip().lower()
        workflow_mode = mode == 'workflow' or config_kind == 'workflow' or bool(settings.get('rhWorkflowId') and not settings.get('rhAppId'))
        entry_id = str((settings.get('rhWorkflowId') if workflow_mode else settings.get('rhAppId')) or config_id).strip()
        if not entry_id:
            raise ValueError('请先选择已同步的 RunningHub AI 应用')
        fields = list(app_fields if app_fields is not None else (
            settings.get('rhFields') or settings.get('rhSchemaSnapshot') or []
        ))
        fields = [field for field in fields if isinstance(field, dict)]
        enabled = [field for field in fields if isinstance(field, dict) and field.get('enabled') is True]
        if enabled:
            fields = enabled
        if not fields:
            raise ValueError('AI 应用缺少官方字段 Schema，请先同步能力档案')
        fields.sort(key=lambda field: (
            field.get('schemaOrder') is None,
            field.get('schemaOrder') if field.get('schemaOrder') is not None else 0,
        ))
        if workflow_mode:
            explicit_params = settings.get('rhParams') or {}

            def has_explicit_value(field):
                key = field_key(field)
                node_id, field_name = field_parts(field)
                return any(candidate and candidate in explicit_params for candidate in (
                    key, f'{node_id}::{field_name}', str(field.get('paramid') or '').strip(),
                ))

            def complex_default(field):
                value = default_value(field)
                if isinstance(value, (dict, list)):
                    return True
                if not isinstance(value, str) or not value.lstrip().startswith(('{', '[')):
                    return False
                try:
                    return isinstance(json.loads(value), (dict, list))
                except (TypeError, ValueError):
                    return False

            def is_prompt_field(field):
                role = str(field.get('inputRole') or field.get('input_role') or field.get('role') or '').strip().lower()
                role = role.replace('-', '_').replace(' ', '_')
                return role in {'prompt', 'positive_prompt', 'negative_prompt', 'caption', 'description', 'instruction'}

            fields = [field for field in fields if not (
                field.get('sourceFromUpstream') is False
                and field_kind(field) not in {'image', 'video', 'audio'}
            ) and not (
                not has_explicit_value(field)
                and complex_default(field)
                and not is_prompt_field(field)
            )]
        bindings = settings.get('rhInputBindings') or {}
        field_values, inputs, parameters = {}, {}, {}
        media_by_kind = {kind: [ref for ref in refs if ref.get('kind') == kind]
                         for kind in ('text', 'image', 'video', 'audio')}
        media_field_counts = {kind: sum(field_kind(field) == kind for field in fields) for kind in media_by_kind}
        for field in fields:
            if not isinstance(field, dict):
                continue
            key = field_key(field)
            kind = field_kind(field)
            value = stored_value(field)
            bound = None
            node_id, field_name = field_parts(field)
            binding_key = f'{node_id}::{field_name}'
            requested_ref = str(bindings.get(key) or bindings.get(binding_key) or '').strip()
            if requested_ref:
                bound = next((ref for ref in refs
                              if requested_ref in ref_aliases(ref) and ref.get('kind') == kind), None)
            if bound is None and kind in media_by_kind:
                target_bound = next((ref for ref in refs
                                     if str(ref.get('targetFieldKey') or ref.get('target_field_key') or '')
                                     in {key, binding_key}
                                     and ref.get('kind') == kind), None)
                bound = target_bound
            if bound is None and kind in media_by_kind and media_field_counts[kind] == 1 and len(media_by_kind[kind]) == 1:
                bound = media_by_kind[kind][0]
            if kind == 'text':
                if bound:
                    value = bound.get('text', bound.get('content', ''))
                elif value in (None, '') and str(field.get('inputRole') or field.get('input_role') or field.get('role') or '').strip().lower() in {
                    'prompt', 'positive_prompt', 'caption', 'description', 'instruction'
                }:
                    value = prompt
                if value in (None, ''):
                    value = default_value(field)
            elif kind in {'image', 'video', 'audio'}:
                value = (bound or {}).get('url') or ''
            elif value is None:
                value = default_value(field)
            if value in (None, ''):
                if field.get('required') is True:
                    raise ValueError(f"RunningHub AI 应用缺少必填输入：{key}")
                continue
            value = coerce(field, value)
            field_values[key] = value
            if kind in {'text', 'image', 'video', 'audio'}:
                inputs[key] = value
            else:
                parameters[key] = value
        node_info_list = [
            {'nodeId': field_parts(field)[0], 'fieldName': field_parts(field)[1], 'fieldValue': field_values[key]}
            for field in fields if isinstance(field, dict) and (key := field_key(field)) in field_values
            and field_parts(field)[0] and field_parts(field)[1]
        ]
        media = {kind: [ref for ref in refs if ref.get('kind') == kind and ref.get('url')]
                 for kind in ('image', 'video', 'audio')}
        common = {
            'kind': 'runninghub_workflow' if workflow_mode else 'ai_application', 'engine': 'runninghub',
            'provider_id': 'runninghub', 'model': f"{'workflow' if workflow_mode else 'app'}:{entry_id}",
            'app_id': '' if workflow_mode else entry_id, 'workflow_id': entry_id if workflow_mode else '',
            'fields': copy.deepcopy(fields), 'app_field_values': field_values,
            'node_info_list': node_info_list, 'inputs': inputs, 'parameters': parameters,
            'prompt': prompt, 'references': refs,
            'input_counts': {'text': len(media_by_kind['text']) + (1 if prompt and not media_by_kind['text'] else 0),
                             **{key: len(value) for key, value in media.items()}},
            'input_roles': {'prompt': 1 if prompt else 0, 'reference': len(media['image']),
                            'source_video': len(media['video']), 'reference_audio': len(media['audio'])},
            'use_wallet': settings.get('rhPayment') == 'wallet',
            'instance_type': str(settings.get('rhInstanceType') or ''),
            'region': str(settings.get('rhRegion') or settings.get('region') or ''),
        }
        if workflow_mode:
            common['optional_image_mode'] = str(
                settings.get('rhOptionalImageMode') or settings.get('optionalImageMode') or 'prune-workflow'
            )
            workflow_json = settings.get('rhWorkflowJson')
            if isinstance(workflow_json, (dict, list)) and workflow_json:
                common['workflow'] = copy.deepcopy(workflow_json)
        return common

    kind, provider_key, model_key = FIELDS[node['type']]
    settings = node.get('runSettings') or {}
    provider, model = settings.get(provider_key, ''), settings.get(model_key, '')
    if not provider or not model:
        raise ValueError('请先为节点选择已启用的平台与模型')
    parameters = copy.deepcopy((settings.get('capabilityParameters') or {}).get(model, {}))
    parameters = {key: value for key, value in parameters.items() if value != '__canvas_unset__'}
    refs = input_media(canvas, node)
    prompt = '\n\n'.join([str(node.get('promptDraftText') or '').strip()] + [
        str(ref.get('text', ref.get('content', ''))).strip() for ref in refs if ref.get('kind') == 'text'])
    prompt = prompt.strip()
    if not prompt:
        raise ValueError('请输入创作内容')
    media = {kind: [ref for ref in refs if ref.get('kind') == kind and ref.get('url')]
             for kind in ('image', 'video', 'audio')}
    roles = {'prompt': 1, 'reference': len(media['image']), 'source_video': len(media['video']),
             'reference_audio': len(media['audio'])}
    inputs = {'prompt': prompt, 'reference': [r['url'] for r in media['image']],
              'source_video': [r['url'] for r in media['video']], 'reference_audio': [r['url'] for r in media['audio']]}
    if kind == 'video' and settings.get('videoUseFrameRoles'):
        if len(media['image']) != 2:
            raise ValueError('首尾帧模式需要恰好两张图片')
        inputs.update(first_frame=inputs['reference'][:1], last_frame=inputs['reference'][1:])
        inputs['reference'] = []
        roles.update(first_frame=1, last_frame=1, reference=0)
    return {'kind': kind, 'provider_id': provider, 'model': model, 'parameters': parameters,
            'prompt': prompt, 'inputs': inputs, 'input_roles': roles, 'references': refs,
            'input_counts': {'text' if kind == 'text' else 'prompt': 1,
                             **{key: len(value) for key, value in media.items()}},
            'system_prompt': settings.get('textSystemPrompt', '') if settings.get('textSystemEnabled') else '',
            'region': str(settings.get('region') or settings.get('rhRegion') or '')}


class StudioExecution:
    def __init__(self, *, load_canvas, save_canvas, lock, storage, preflight, generate, collect, notify):
        self.load = load_canvas
        self.save = save_canvas
        self.lock = lock
        self.storage = storage
        self.preflight = preflight
        self.generate = generate
        self.collect = collect
        self.notify = notify
        self.handles = {}

    async def submit(self, canvas, node, request_id):
        task_id = 'studio_' + hashlib.sha256(f"{canvas['id']}:{node['id']}:{request_id}".encode()).hexdigest()[:32]
        existing = self.storage.get_canvas_task(task_id)
        if existing:
            return {'task_ids': [task_id], 'status': existing['status']}
        request = request_for(canvas, node)
        validated = await self.preflight(canvas, node, request, request_id)
        with self.lock:
            existing = self.storage.get_canvas_task(task_id)
            if existing:
                return {'task_ids': [task_id], 'status': existing['status']}
            latest = self.load(canvas['id'])
            current = next((n for n in latest['nodes'] if n['id'] == node['id']), None)
            if current is None or recipe(current) != recipe(node):
                raise ValueError('预检期间节点已修改，请重新读取后运行')
            current.setdefault('creationId', 'creation_' + uuid.uuid4().hex)
            if current.get('creationOwnerNodeId', current['id']) != current['id']:
                current['creationParentId'] = current['creationId']
                current['creationId'] = 'creation_' + uuid.uuid4().hex
            current['creationOwnerNodeId'] = current['id']
            current['creationRevision'] = current.get('creationRevision', 0) + 1
            signature = stable(recipe(current))
            current['creationSignature'] = signature
            task = {**copy.deepcopy(current), 'id': task_id, 'type': 'smart-material',
                    'creationType': current['type'], 'sourceExecutionNodeId': current['id'],
                    'creationTask': True, 'runStatus': 'queued', 'isRunPlaceholder': True,
                    'pending': 1, 'runStartedAt': int(time.time()*1000), 'images': [],
                    'runInputRefs': request['references'], 'runPrompt': request['prompt'],
                    'runRef': validated, 'creationSignature': signature}
            for key in ('creationTasks', 'resultVersions'):
                task.pop(key, None)
            self.storage.create_canvas_task({'id': task_id, 'status': 'queued', 'kind': request['kind'],
                                            'canvas_id': canvas['id'], 'node_id': node['id'],
                                            'request': request, 'creation_snapshot': task})
            current.setdefault('creationTasks', []).append(task)
            self.save(latest)
        await self.notify(latest)
        handle = asyncio.create_task(self._run(canvas['id'], task, request))
        self.handles[task_id] = handle
        handle.add_done_callback(lambda _: self.handles.pop(task_id, None))
        return {'task_ids': [task_id], 'status': 'queued'}

    async def _transition(self, canvas_id, task, status, media=None, error=''):
        task.update(runStatus=status, pending=int(status in {'queued', 'running'}),
                    isRunPlaceholder=status in {'queued', 'running'}, error=error)
        if status not in {'queued', 'running'}:
            task['runFinishedAt'] = int(time.time()*1000)
        if media:
            task['images'] = media
        self.storage.update_canvas_task(task['id'], status=status, error=error,
                                       result={'media': media or [], 'creation_snapshot': task})
        run_id = (task.get('runRef') or {}).get('run_id')
        if run_id and hasattr(self.storage, 'update_run_status'):
            self.storage.update_run_status(run_id, 'submitted' if status == 'running' else status, error=error)
        with self.lock:
            canvas = self.load(canvas_id)
            if not canvas:
                return
            for node in canvas.get('nodes', []):
                for index, prior in enumerate(node.get('creationTasks', [])):
                    if prior['id'] == task['id']:
                        node['creationTasks'][index] = copy.deepcopy(task)
                if media and node.get('creationId') == task['creationId'] and stable(recipe(node)) == task['creationSignature']:
                    versions = node.setdefault('resultVersions', ([copy.deepcopy(node)] if node.get('images') else []))
                    version = copy.deepcopy(task)
                    version.update(type=task['creationType'], outputKind=media[0]['kind'])
                    old = next((i for i, v in enumerate(versions) if v['id'] == task['id']), None)
                    if old is None:
                        versions.append(version)
                        old = len(versions)-1
                    else:
                        versions[old] = version
                    node.update(activeResultVersion=old, images=copy.deepcopy(media), sourceKind='result',
                                outputKind=media[0]['kind'], creationRevision=node.get('creationRevision', 0)+1)
            self.save(canvas)
        await self.notify(canvas)

    async def _run(self, canvas_id, task, request):
        try:
            await self._transition(canvas_id, task, 'running')
            result = await self.generate(request)
            if result.get('jimeng_pending') or result.get('pending'):
                task['upstreamPending'] = copy.deepcopy(result)
                await self._transition(canvas_id, task, 'recoverable', error='上游仍在运行，需查询原任务')
                return
            media = await self.collect(result, request, task)
            if not media:
                raise ValueError('接口没有返回可保存的结果')
            await self._transition(canvas_id, task, 'succeeded', media=media)
        except asyncio.CancelledError:
            await self._transition(canvas_id, task, 'cancelled', error='已停止本地等待，上游任务可能仍在运行')
        except Exception as exc:
            await self._transition(canvas_id, task, 'failed', error=str(getattr(exc, 'detail', None) or exc))

    async def cancel(self, canvas, node, task_id):
        task = self.storage.get_canvas_task(task_id)
        if not task or task.get('canvas_id') != canvas['id'] or task.get('node_id') != node['id']:
            raise ValueError('当前节点不存在此任务')
        handle = self.handles.get(task_id)
        if handle:
            handle.cancel()
            await asyncio.gather(handle, return_exceptions=True)
            current = self.storage.get_canvas_task(task_id)
            if current.get('status') in {'queued', 'running'}:
                await self._transition(canvas['id'], task['creation_snapshot'], 'cancelled',
                                       error='已取消本地任务；已提交的上游请求可能仍在运行')
        return self.storage.get_canvas_task(task_id)
