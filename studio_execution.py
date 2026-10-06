"""与页面生命周期无关的创作执行；模型协议和素材存储通过明确回调复用。"""
from __future__ import annotations

import asyncio
import copy
import hashlib
from html.parser import HTMLParser
import json
import mimetypes
import re
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


def _reference_identity(item, index=0):
    explicit = str(item.get('key') or '').strip()
    if explicit:
        return explicit
    result_id = str(item.get('resultId') or item.get('result_id') or '').strip()
    if result_id:
        return f'result:{result_id}'
    node_id = str(item.get('nodeId') or item.get('node_id') or '').strip()
    image_index = item.get('imageIndex', item.get('image_index', index))
    try:
        image_index = int(image_index)
    except (TypeError, ValueError):
        image_index = index
    if node_id:
        return f'node:{node_id}:{image_index}'
    material_id = str(item.get('materialId') or item.get('material_id') or item.get('assetId') or item.get('asset_id') or '').strip()
    if material_id:
        return f'material:{material_id}'
    text = str(item.get('text', item.get('content', '')) or '').strip()
    if text:
        return f'text:{text}'
    return f"url:{item.get('url') or item.get('path') or item.get('src') or item.get('uri') or ''}"


def _reference_aliases(item, index=0):
    aliases = {_reference_identity(item, index)}
    result_id = str(item.get('resultId') or item.get('result_id') or '').strip()
    node_id = str(item.get('nodeId') or item.get('node_id') or '').strip()
    if result_id:
        aliases.add(f'result:{result_id}')
    if node_id:
        image_index = item.get('imageIndex', item.get('image_index', index))
        aliases.update({f'node:{node_id}:{image_index}', f'{node_id}|{image_index}'})
    return aliases


class _PromptDraftParser(HTMLParser):
    """只解析已知的画布 @素材 token；其它 HTML 仅保留可见文本，不执行标记。"""
    _BLOCK_TAGS = {'div', 'p', 'li', 'section', 'article', 'header', 'footer', 'blockquote'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._mention_tags = []

    def _append_text(self, value):
        if not value:
            return
        if self.parts and isinstance(self.parts[-1], dict) and self.parts[-1].get('type') == 'text':
            self.parts[-1]['text'] += value
        else:
            self.parts.append({'type': 'text', 'text': value})

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(str(attrs.get('class') or '').split())
        if self._mention_tags:
            if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
                self._mention_tags.append(tag)
            return
        if tag == 'span' and 'mention-image-token' in classes:
            self._mention_tags = ['span']
            self.parts.append({
                'type': 'mention',
                'kind': str(attrs.get('data-kind') or 'image').strip().lower(),
                'url': str(attrs.get('data-url') or '').strip(),
                'name': str(attrs.get('data-name') or ''),
                'text': str(attrs.get('data-text') or ''),
                'node_id': str(attrs.get('data-node-id') or '').strip(),
                'source_node_id': str(attrs.get('data-source-node-id') or '').strip(),
                'image_index': attrs.get('data-image-index', ''),
                'asset_uris': attrs.get('data-asset-uris') or '{}',
            })
            return
        if tag == 'br':
            self._append_text('\n')
        elif tag in self._BLOCK_TAGS and self.parts:
            last = self.parts[-1]
            if isinstance(last, dict) and last.get('type') == 'text' and last.get('text') and not last['text'].endswith('\n'):
                self._append_text('\n')

    def handle_endtag(self, tag):
        if self._mention_tags:
            for index in range(len(self._mention_tags) - 1, -1, -1):
                if self._mention_tags[index] == tag:
                    del self._mention_tags[index:]
                    break
            return
        if tag in self._BLOCK_TAGS:
            self._append_text('\n')

    def handle_data(self, data):
        if not self._mention_tags:
            self._append_text(data)

    def handle_startendtag(self, tag, attrs):
        if not self._mention_tags:
            self.handle_starttag(tag, attrs)


def prompt_request_for(node, references=None, *, source_nodes=None, connected_source_ids=None, connections=None, language='zh'):
    """按普通画布 @mention 顺序生成提示词；素材内容优先读当前任务图快照。"""
    source_nodes = source_nodes if isinstance(source_nodes, dict) else {}
    connected_source_ids = [str(value or '').strip() for value in (connected_source_ids or []) if str(value or '').strip()]
    connections = connections if isinstance(connections, list) else []

    def direct_input_source_ids(target_id):
        return [str(edge.get('from', edge.get('source', '')) or '').strip()
                for edge in connections
                if isinstance(edge, dict)
                and str(edge.get('to', edge.get('target', '')) or '') == str(target_id or '')
                and str(edge.get('kind') or 'flow').strip().lower() == 'input'
                and str(edge.get('from', edge.get('source', '')) or '').strip()]

    def live_reference(ref, index):
        source_id = str(ref.get('inputSourceNodeId') or ref.get('sourceNodeId') or ref.get('nodeId') or ref.get('node_id') or '').strip()
        source = source_nodes.get(source_id)
        if not source:
            return copy.deepcopy(ref)
        try:
            image_index = int(ref.get('imageIndex', ref.get('image_index', index)))
        except (TypeError, ValueError):
            image_index = index
        items = source.get('images') if isinstance(source.get('images'), list) else []
        if image_index < 0 or image_index >= len(items) or not isinstance(items[image_index], dict):
            return copy.deepcopy(ref)
        current = copy.deepcopy(items[image_index])
        for key, value in ref.items():
            if key not in {'url', 'path', 'src', 'uri', 'kind', 'text', 'content', 'name'}:
                current.setdefault(key, copy.deepcopy(value))
        current.update(nodeId=source_id, imageIndex=image_index, inputSourceNodeId=source_id)
        return current

    references = [live_reference(item, index) for index, item in enumerate(references or []) if isinstance(item, dict)]
    parser = _PromptDraftParser()
    draft_html = str(node.get('promptDraftHtml') or '')
    if draft_html:
        parser.feed(draft_html)
        parser.close()
    parts = parser.parts
    mention_parts = [part for part in parts if part.get('type') == 'mention']
    fallback_prompt = str(node.get('promptDraftText') or '').strip()
    if not mention_parts:
        prompt = '\n\n'.join([fallback_prompt] + [
            str(ref.get('text', ref.get('content', ''))).strip()
            for ref in references if ref.get('kind') == 'text'
        ]).strip()
        return {'prompt': prompt, 'display_prompt': fallback_prompt, 'references': references, 'mentioned': False}

    blocked = {str(value).strip() for value in node.get('blockedInputRefs', []) if not isinstance(value, dict)}
    blocked.update(_reference_identity(value, index) for index, value in enumerate(node.get('blockedInputRefs') or []) if isinstance(value, dict))

    def is_blocked(item, index=0):
        return bool(_reference_aliases(item, index) & blocked)

    image_refs = []
    image_numbers = {}
    for index, ref in enumerate(references):
        if not ref.get('url') or str(ref.get('kind') or '').lower() == 'text' or is_blocked(ref, index):
            continue
        url = str(ref.get('url') or '')
        if url not in image_numbers:
            image_numbers[url] = len(image_refs) + 1
            image_refs.append(ref)

    by_node_index = {}
    for index, ref in enumerate(references):
        node_id = str(ref.get('sourceNodeId') or ref.get('inputSourceNodeId') or ref.get('nodeId') or ref.get('node_id') or '').strip()
        image_index = ref.get('imageIndex', ref.get('image_index', index))
        try:
            image_index = int(image_index)
        except (TypeError, ValueError):
            image_index = index
        if node_id:
            by_node_index.setdefault((node_id, image_index), ref)

    def source_text_values(source_id, visited=None):
        """复用普通画布的直连文本顺序，不把 @ 已展开的文本重复前置。"""
        visited = set() if visited is None else visited
        if not source_id or source_id in visited:
            return []
        visited.add(source_id)
        source = source_nodes.get(source_id)
        if not isinstance(source, dict):
            return []
        source_type = str(source.get('type') or '')
        if source_type == 'smart-prompt':
            value = str(source.get('text') or '').strip()
            if not value:
                return []
            if source.get('promptSplitEnabled') is True:
                separator = str(source.get('promptSeparator') or ';') or ';'
                split = [item.strip() for item in value.split(separator) if item.strip()]
                value = '\n\n'.join(split) if len(split) > 1 else value
            return [value]
        if source_type == 'smart-group':
            values = []
            for member_id in source.get('items') or []:
                member_id = str(member_id or '').strip()
                member = source_nodes.get(member_id)
                if isinstance(member, dict) and member.get('type') != 'smart-group':
                    values.extend(source_text_values(member_id, visited))
            return values
        if source_type == 'smart-loop':
            if source.get('showPrompt') is not True:
                return []
            values = []
            for edge_source_id in direct_input_source_ids(source_id):
                values.extend(source_text_values(edge_source_id, visited))
            prompts = source.get('variablePrompts') if isinstance(source.get('variablePrompts'), list) else []
            if not prompts:
                prompts = str(source.get('variablePrompt') or '').splitlines()
            local = next((str(value).strip() for value in prompts if str(value).strip()), '')
            default_prompt = local in {'现在生成第《计数》张卖点图片', 'Generate selling-point image 《计数》'}
            if local and not default_prompt:
                local = local.replace('《计数》', str(max(1, int(source.get('loopStart') or 1))))
                local = local.replace('[计数]', str(max(1, int(source.get('loopStart') or 1))))
                local = local.replace('《总数》', str(max(1, int(source.get('count') or 1))))
                local = local.replace('[总数]', str(max(1, int(source.get('count') or 1))))
                values.append(local)
            return values
        values = []
        for index, ref in enumerate(references):
            ref_node_id = str(ref.get('inputSourceNodeId') or ref.get('sourceNodeId') or ref.get('nodeId') or ref.get('node_id') or '').strip()
            text = ref.get('text', ref.get('content'))
            if ref_node_id == source_id and str(ref.get('kind') or '').lower() == 'text' and isinstance(text, str) and text.strip():
                values.append(text.strip())
        if not values:
            for item in source.get('images') or []:
                if isinstance(item, dict) and str(item.get('kind') or '').lower() == 'text':
                    text = item.get('text', item.get('content'))
                    if isinstance(text, str) and text.strip():
                        values.append(text.strip())
        return values

    def connected_prompt_text(excluded_source_ids):
        values = []
        seen = set()
        for source_id in connected_source_ids:
            if source_id in excluded_source_ids:
                continue
            for value in source_text_values(source_id):
                text = str(value or '').strip()
                if text and text not in seen:
                    seen.add(text)
                    values.append(text)
        return '\n\n'.join(values)

    def current_source_text(part):
        node_id = part.get('source_node_id') or part.get('node_id')
        if not node_id:
            return part.get('text') or ''
        try:
            image_index = int(part.get('image_index') or 0)
        except (TypeError, ValueError):
            image_index = 0
        ref = by_node_index.get((node_id, image_index))
        source = source_nodes.get(node_id)
        if isinstance(source, dict):
            items = source.get('images') or []
            if 0 <= image_index < len(items) and isinstance(items[image_index], dict):
                item = items[image_index]
                if str(item.get('kind') or '').lower() == 'text':
                    value = item.get('text', item.get('content'))
                    if isinstance(value, str) and value.strip():
                        return value
            resolved_text = source_text_values(node_id)
            if resolved_text:
                return '\n\n'.join(resolved_text)
            value = source.get('text') or source.get('promptDraftText') or source.get('prompt') or source.get('content')
            if source.get('type') == 'smart-prompt' and isinstance(value, str) and source.get('promptSplitEnabled') is True:
                separator = str(source.get('promptSeparator') or ';') or ';'
                split = [item.strip() for item in value.split(separator) if item.strip()]
                value = '\n\n'.join(split) if len(split) > 1 else value.strip()
            if isinstance(value, str) and value.strip():
                return value
            raise ValueError(f'引用的文本节点“{node_id}”没有当前可用的正文')
        if ref and str(ref.get('kind') or '').lower() == 'text':
            value = ref.get('text', ref.get('content'))
            if isinstance(value, str) and value.strip():
                return value
        # 只有脱离源节点身份的旧 token 才使用 HTML 内嵌的兼容快照。
        return part.get('text') or ''

    def image_reference(part):
        node_id = part.get('source_node_id') or part.get('node_id')
        try:
            image_index = int(part.get('image_index') or 0)
        except (TypeError, ValueError):
            image_index = 0
        source = source_nodes.get(node_id) if node_id else None
        if isinstance(source, dict):
            items = source.get('images') or []
            if 0 <= image_index < len(items) and isinstance(items[image_index], dict):
                current = copy.deepcopy(items[image_index])
                if current.get('url'):
                    current.update(nodeId=node_id, imageIndex=image_index, inputSourceNodeId=node_id)
                    return current
            raise ValueError(f'引用的媒体节点“{node_id}”没有当前可用的媒体')
        ref = by_node_index.get((node_id, image_index))
        if ref:
            return ref
        return part

    body = []
    original = []
    has_image_mention = False
    for part in parts:
        if part['type'] == 'text':
            text = part.get('text') or ''
            body.append(text)
            original.append(text)
            continue
        name = part.get('name') or ('文本' if part.get('kind') == 'text' else '图片')
        original.append('@' + name)
        if part.get('kind') == 'text':
            text = current_source_text(part)
            body.append(f'\n\n{text}\n\n' if text else '')
            continue
        url = str(part.get('url') or '').strip()
        ref = image_reference(part)
        url = str(ref.get('url') or url).strip()
        if not url:
            if part.get('source_node_id') or part.get('node_id'):
                raise ValueError(f'引用的媒体“{name}”缺少可用地址')
            continue
        has_image_mention = True
        try:
            part_index = int(part.get('image_index') or 0)
        except (TypeError, ValueError):
            part_index = 0
        aliases = _reference_aliases(ref, part_index)
        if aliases & blocked:
            body.append('@' + name)
            continue
        if url not in image_numbers:
            image_numbers[url] = len(image_refs) + 1
            item = copy.deepcopy(ref)
            item.update(url=url, name=name, kind=part.get('kind') or 'image')
            image_refs.append(item)
        body.append(f"图{image_numbers[url]}")

    body_text = ''.join(body)
    body_text = re.sub(r'[ \t]+\n', '\n', body_text)
    body_text = re.sub(r'\n{3,}', '\n\n', body_text).strip()
    mentioned_text_source_ids = {
        str(part.get('source_node_id') or part.get('node_id') or '').strip()
        for part in mention_parts if str(part.get('kind') or '').lower() == 'text'
        and str(part.get('source_node_id') or part.get('node_id') or '').strip()
    }
    prefix = connected_prompt_text(mentioned_text_source_ids)
    if prefix:
        body_text = '\n\n'.join(value for value in (prefix, body_text) if value).strip()
    display_prompt = ''.join(original)
    display_prompt = re.sub(r'[ \t]+\n', '\n', display_prompt)
    display_prompt = re.sub(r'\n{3,}', '\n\n', display_prompt).strip()
    if has_image_mention and image_refs:
        if str(language or 'zh').lower().startswith('en'):
            map_header, need_header, map_prefix = 'Reference image map:', 'User request:', 'Image '
        else:
            map_header, need_header, map_prefix = '参考图编号：', '用户需求：', '图'
        separator = ': ' if str(language or 'zh').lower().startswith('en') else '：'
        map_text = '\n'.join(f"{map_prefix}{index + 1}{separator}{item.get('name') or f'图片{index + 1}'}"
                              for index, item in enumerate(image_refs))
        body_text = f'{map_header}\n{map_text}\n\n{need_header}\n{body_text}'
    return {'prompt': body_text, 'display_prompt': display_prompt, 'references': image_refs,
            'mentioned': has_image_mention}


def recipe(node):
    return {key: copy.deepcopy(node.get(key, default)) for key, default in (
        ('type', ''), ('runSettings', {}), ('promptDraftText', ''), ('promptDraftHtml', ''),
        ('manualInputRefs', []), ('runInputRefs', []), ('runPromptRefs', []),
        ('blockedInputRefs', []), ('inputRefOrder', []), ('creationInputBinding', []),
        ('hypitInputLocked', False))}


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


def _connected_input_source_ids(canvas, node):
    node_id = str(node.get('id') or '')
    connections = canvas.get('connections') if isinstance(canvas.get('connections'), list) else []
    return [str(edge.get('from') or edge.get('source') or '').strip()
            for edge in connections
            if isinstance(edge, dict)
            and str(edge.get('to', edge.get('target', '')) or '') == node_id
            and str(edge.get('kind') or 'flow').strip().lower() == 'input'
            and str(edge.get('from', edge.get('source', '')) or '').strip()]


def project_workflow_fields(fields, *, engine, prompt, references, system_prompt='', input_bindings=None,
                            stored_values=None, task_values=None, strict=False):
    """把已确认的任务输入投影到 AI 应用或 Comfy 字段；不读取画布或存储。"""
    fields = [copy.deepcopy(field) for field in fields if isinstance(field, dict)]
    input_bindings = input_bindings if isinstance(input_bindings, dict) else {}
    stored_values = stored_values if isinstance(stored_values, dict) else {}
    task_values = task_values if isinstance(task_values, dict) else {}

    def parts(field):
        node_id = str(field.get('nodeId') or field.get('node_id') or field.get('node') or '').strip()
        field_name = str(field.get('fieldName') or field.get('field_name') or field.get('inputName') or field.get('input') or '').strip()
        if not node_id or not field_name:
            param_id = str(field.get('paramid') or field.get('paramId') or field.get('key') or '').strip()
            if '::' in param_id:
                node_id, field_name = (part.strip() for part in param_id.split('::', 1))
        return node_id, field_name

    def key_of(field):
        if engine == 'comfy':
            return str(field.get('id') or field.get('paramid') or field.get('paramId') or field.get('key') or '').strip()
        node_id, field_name = parts(field)
        return f'{node_id}::{field_name}' if node_id or field_name else str(field.get('key') or field.get('paramid') or field.get('paramId') or '').strip()

    def is_secret(field):
        identity = ' '.join(str(field.get(name) or '') for name in (
            'fieldName', 'field_name', 'inputName', 'input', 'name', 'label', 'id', 'key', 'paramid', 'paramId',
        )).lower().replace('-', '_').replace(' ', '_')
        raw = str(field.get('fieldType') or field.get('type') or field.get('kind') or '').lower()
        return any(token in identity for token in ('api_key', 'apikey', 'secret', 'password', 'access_token', 'authorization')) or raw in {'password', 'secret', 'credential', 'token'}

    fields = [field for field in fields if not is_secret(field)]
    by_key = {key_of(field): field for field in fields if key_of(field)}
    if not by_key:
        raise ValueError('工作流没有可映射的安全字段 Schema')

    def kind_of(field):
        raw = str(field.get('fieldType') or field.get('type') or field.get('kind') or '').strip().lower()
        return {
            'string': 'text', 'plain-text': 'text', 'textarea': 'text', 'text': 'text',
            'float': 'number', 'number': 'number', 'integer': 'number', 'int': 'number', 'slider': 'number',
            'boolean': 'boolean', 'bool': 'boolean',
            'select': 'select', 'switch': 'select', 'combo': 'select', 'dropdown': 'select', 'list': 'select', 'enum': 'select',
            'image': 'image', 'video': 'video', 'audio': 'audio',
        }.get(raw, 'unknown')

    if strict:
        unknown_required = [key for key, field in by_key.items()
                            if field.get('required') is True and kind_of(field) == 'unknown']
        if unknown_required:
            raise ValueError('工作流必填字段类型未确认：' + ', '.join(sorted(unknown_required)))

    def default_of(field):
        value = field.get('fieldValue', field.get('defaultValue', field.get('default')))
        if isinstance(value, list):
            return value[0] if value else ''
        return '' if isinstance(value, (dict, list)) or value is None else value

    def coerce(field, value, key):
        raw = str(field.get('fieldType') or field.get('type') or field.get('kind') or '').strip().upper()
        if value in (None, ''):
            return value
        if raw in {'BOOLEAN', 'BOOL'}:
            if isinstance(value, str):
                normal = value.strip().lower()
                if normal in {'true', '1', 'yes', 'on'}:
                    return True
                if normal in {'false', '0', 'no', 'off'}:
                    return False
                raise ValueError(f'字段“{key}”要求布尔值')
            if not isinstance(value, bool):
                raise ValueError(f'字段“{key}”要求布尔值')
            return value
        if raw in {'FLOAT', 'NUMBER', 'SLIDER', 'INT', 'INTEGER'}:
            if isinstance(value, bool):
                raise ValueError(f'字段“{key}”要求数字')
            try:
                number = float(str(value).strip())
            except (TypeError, ValueError) as exc:
                raise ValueError(f'字段“{key}”要求数字') from exc
            if raw in {'INT', 'INTEGER'} and not number.is_integer():
                raise ValueError(f'字段“{key}”要求整数')
            minimum = field.get('min', field.get('minimum'))
            maximum = field.get('max', field.get('maximum'))
            step = field.get('step')
            if minimum not in (None, '') and number < float(minimum):
                raise ValueError(f'字段“{key}”不能小于 {minimum}')
            if maximum not in (None, '') and number > float(maximum):
                raise ValueError(f'字段“{key}”不能大于 {maximum}')
            if step not in (None, '') and float(step) > 0:
                origin = float(minimum) if minimum not in (None, '') else 0.0
                increments = (number - origin) / float(step)
                if abs(increments - round(increments)) > 1e-8:
                    raise ValueError(f'字段“{key}”不符合步幅 {step}')
            return int(number) if raw in {'INT', 'INTEGER'} else number
        choices = field.get('options') or field.get('values')
        if isinstance(choices, list) and choices and value not in choices:
            raise ValueError(f'字段“{key}”不在工作流允许选项内')
        if kind_of(field) == 'select' and not isinstance(value, str):
            raise ValueError(f'字段“{key}”要求选择字段值')
        return value

    role_field_keys = {}
    target_roles = {}
    for role, raw_targets in input_bindings.items():
        if role not in {'prompt', 'system_prompt', 'reference', 'source_video', 'reference_audio', 'first_frame', 'last_frame'}:
            raise ValueError(f'不支持的工作流输入映射角色：{role}')
        targets = [raw_targets] if isinstance(raw_targets, str) else raw_targets
        if not isinstance(targets, list) or not targets or any(not isinstance(item, str) for item in targets):
            raise ValueError(f'工作流输入映射 {role} 必须是一项或多项字段键')
        if len(targets) != len(set(targets)):
            raise ValueError(f'工作流输入映射 {role} 包含重复字段')
        role_field_keys[role] = targets
        for target in targets:
            if target not in by_key:
                raise ValueError(f'工作流映射字段不存在或不允许使用：{target}')
            if target in target_roles:
                raise ValueError(f'工作流字段 {target} 不能同时接收多个输入角色')
            expected_type = 'text' if role in {'prompt', 'system_prompt'} else {
                'reference': 'image', 'source_video': 'video', 'reference_audio': 'audio',
                'first_frame': 'image', 'last_frame': 'image',
            }[role]
            if kind_of(by_key[target]) != expected_type:
                raise ValueError(f'工作流字段 {target} 与 {role} 输入类型不匹配')
            target_roles[target] = role

    refs = [copy.deepcopy(item) for item in references if isinstance(item, dict)]
    role_kinds = {'reference': 'image', 'source_video': 'video', 'reference_audio': 'audio',
                  'first_frame': 'image', 'last_frame': 'image'}
    refs_by_role = {role: [] for role in role_kinds}
    for ref in refs:
        raw_role = str(ref.get('role') or '').strip()
        if raw_role in refs_by_role:
            refs_by_role[raw_role].append(ref)
            continue
        media_kind = str(ref.get('kind') or ref.get('media_type') or '').lower()
        role = {'image': 'reference', 'video': 'source_video', 'audio': 'reference_audio'}.get(media_kind)
        if role:
            refs_by_role[role].append(ref)
    if strict:
        if system_prompt and not role_field_keys.get('system_prompt'):
            raise ValueError('工作流没有系统提示词映射字段')
        prompt_targets = role_field_keys.get('prompt', [])
        prompt_text_fields = [key for key, field in by_key.items()
                              if kind_of(field) == 'text' and str(field.get('inputRole') or field.get('input_role') or field.get('role') or '').lower().replace('-', '_') in {'prompt', 'positive_prompt', 'caption', 'description', 'instruction'}]
        all_text_fields = [key for key, field in by_key.items() if kind_of(field) == 'text']
        if prompt and not prompt_targets:
            candidates = prompt_text_fields if len(prompt_text_fields) == 1 else all_text_fields
            if len(candidates) == 1:
                prompt_targets = [candidates[0]]
                role_field_keys['prompt'] = prompt_targets
                target_roles[prompt_targets[0]] = 'prompt'
            elif not candidates:
                raise ValueError('工作流没有文本输入字段，请映射提示词')
            else:
                raise ValueError('工作流有多个文本输入字段，请明确映射提示词')
        for role, values in refs_by_role.items():
            if values and not role_field_keys.get(role):
                raise ValueError(f'工作流输入 {role} 尚未映射到字段')

    for key in task_values:
        if str(key) not in by_key:
            raise ValueError(f'工作流不支持任务字段：{key}')
        if is_secret(by_key[str(key)]):
            raise ValueError('工作流任务字段不能包含凭据')
        if kind_of(by_key[str(key)]) == 'unknown':
            raise ValueError(f'工作流任务字段类型未确认：{key}')
        if key in target_roles:
            raise ValueError(f'工作流字段 {key} 已映射输入，不能重复作为任务参数')

    prompt = str(prompt or '').strip()
    values = {}
    fields_by_role = {}
    for key, role in target_roles.items():
        fields_by_role.setdefault(role, []).append(key)
    inputs = {}
    parameters = {}
    comfy_params = {}
    for key, field in by_key.items():
        kind = kind_of(field)
        if kind == 'unknown':
            continue
        role = target_roles.get(key)
        value = task_values.get(key, stored_values.get(key, default_of(field)))
        if role == 'prompt':
            value = prompt
        elif role == 'system_prompt':
            value = str(system_prompt or '').strip()
        elif role in role_kinds:
            candidates = refs_by_role.get(role) or []
            targets = fields_by_role.get(role) or []
            target_index = targets.index(key) if key in targets else 0
            if len(candidates) == 1:
                chosen = candidates[0]
            elif len(candidates) == len(targets) and target_index < len(candidates):
                chosen = candidates[target_index]
            elif candidates:
                raise ValueError(f'工作流输入 {role} 与字段映射数量不匹配')
            else:
                chosen = None
            if chosen:
                value = chosen.get('url') or chosen.get('path') or chosen.get('text') or chosen.get('content') or ''
        elif key in task_values:
            value = task_values[key]
        elif key in stored_values:
            value = stored_values[key]
        else:
            value = default_of(field)
        if value in (None, ''):
            if field.get('required') is True:
                raise ValueError(f'工作流缺少必填输入：{key}')
            continue
        value = coerce(field, value, key)
        values[key] = value
        if kind in {'text', 'image', 'video', 'audio'}:
            inputs[key] = value
        else:
            parameters[key] = value
        if engine == 'comfy':
            field_node = field.get('node') or field.get('nodeId')
            field_input = field.get('input') or field.get('fieldName')
            if field_node and field_input:
                comfy_params.setdefault(str(field_node), {})[str(field_input)] = value

    node_info_list = [
        {'nodeId': parts(field)[0], 'fieldName': parts(field)[1], 'fieldValue': values[key]}
        for key, field in by_key.items() if key in values and parts(field)[0] and parts(field)[1]
    ]
    return {'field_values': values, 'inputs': inputs, 'parameters': parameters,
            'node_info_list': node_info_list, 'comfy_params': comfy_params, 'fields': fields}


def request_for(canvas, node, *, app_fields=None, comfy_fields=None):
    node_type = node.get('type')
    if node_type not in FIELDS:
        raise ValueError('此执行类型尚未接入服务端任务；不能提交未适配请求')

    if node_type in {'smart-ai-app', 'smart-comfy-workflow'}:
        settings = node.get('runSettings') or {}
        refs = input_media(canvas, node)
        prompt_result = prompt_request_for(
            node, refs,
            source_nodes={str(item.get('id') or ''): item for item in canvas.get('nodes', []) if isinstance(item, dict)},
            connected_source_ids=_connected_input_source_ids(canvas, node),
            connections=canvas.get('connections', []),
        )
        prompt = prompt_result['prompt']

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
    prompt = prompt_request_for(
        node, refs,
        source_nodes={str(item.get('id') or ''): item for item in canvas.get('nodes', []) if isinstance(item, dict)},
        connected_source_ids=_connected_input_source_ids(canvas, node),
        connections=canvas.get('connections', []),
    )['prompt']
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
    model_selection = node.get('modelSelection') if isinstance(node.get('modelSelection'), dict) else {}
    return {'kind': kind, 'provider_id': provider, 'model': model, 'parameters': parameters,
            'prompt': prompt, 'inputs': inputs, 'input_roles': roles, 'references': refs,
            'option_id': str(model_selection.get('option_id') or '').strip(),
            'operation': str(model_selection.get('operation') or '').strip(),
            'input_counts': {'text' if kind == 'text' else 'prompt': 1,
                             **{key: len(value) for key, value in media.items()}},
            'system_prompt': settings.get('textSystemPrompt', '') if settings.get('textSystemEnabled') else '',
            'region': str(settings.get('region') or settings.get('rhRegion') or '')}


class StudioExecution:
    def __init__(self, *, load_canvas, save_canvas, lock, storage, preflight, generate, collect, notify,
                 task_metadata=None):
        self.load = load_canvas
        self.save = save_canvas
        self.lock = lock
        self.storage = storage
        self.preflight = preflight
        self.generate = generate
        self.collect = collect
        self.notify = notify
        self.task_metadata = task_metadata
        self.handles = {}

    async def submit(self, canvas, node, request_id):
        task_id = 'studio_' + hashlib.sha256(f"{canvas['id']}:{node['id']}:{request_id}".encode()).hexdigest()[:32]
        existing = self.storage.get_canvas_task(task_id)
        if existing:
            return {'task_ids': [task_id], 'status': existing['status']}
        request = request_for(canvas, node)
        task_metadata = self.task_metadata(canvas, node, request) if self.task_metadata else {}
        if not isinstance(task_metadata, dict):
            raise ValueError('task_metadata 必须返回对象')
        validated = await self.preflight(canvas, node, request, request_id)
        with self.lock:
            existing = self.storage.get_canvas_task(task_id)
            if existing:
                return {'task_ids': [task_id], 'status': existing['status']}
            latest = self.load(canvas['id'])
            current = next((n for n in latest['nodes'] if n['id'] == node['id']), None)
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
            task = {**copy.deepcopy(current), 'id': task_id, 'type': 'smart-material',
                    'creationType': current['type'], 'sourceExecutionNodeId': current['id'],
                    'creationTask': True, 'runStatus': 'queued', 'isRunPlaceholder': True,
                    'pending': 1, 'runStartedAt': int(time.time()*1000), 'images': [],
                    'runInputRefs': request['references'], 'runPrompt': request['prompt'],
                    'runRef': validated, 'creationSignature': signature, **copy.deepcopy(task_metadata)}
            for key in ('creationTasks', 'resultVersions'):
                task.pop(key, None)
            self.storage.create_canvas_task({'id': task_id, 'status': 'queued', 'kind': request['kind'],
                                            'canvas_id': canvas['id'], 'node_id': node['id'],
                                            'request': request, 'creation_snapshot': task,
                                            **copy.deepcopy(task_metadata)})
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
