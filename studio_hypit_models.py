"""Hypit 原生 Endpoint 与工作台共享模型执行的桥接。

本模块只负责 Hypit 模型设置、项目绑定和异步任务边界。真正的模型目录、
参数预检以及模型请求均由主控通过显式回调注入；这里不读取 API Key，也不
复制任何平台适配器。
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import math
import mimetypes
import re
import time
import urllib.parse
from pathlib import Path
from threading import RLock
from typing import Any, Awaitable, Callable, Dict, Iterable, Mapping, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from canvas_agent import is_local_client
from canvas_core.json_store import DataFileError, read_json, write_json


HYPIT_SETTINGS_VERSION = 2
HYPIT_BINDING_VERSION = 1
HYPIT_TASK_VERSION = 1

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_REQUEST_ID = re.compile(r"^[^\x00\r\n]{1,160}$")
_SLOTS = ("text", "image", "video", "audio", "music", "voice")
_RUNNINGHUB_REGIONS = frozenset(("global", "cn"))
_SLOT_NODE_TYPES = {
    "text": "text_generation",
    "image": "image_generation",
    "video": "video_generation",
    "audio": "audio_generation",
    "music": "music_generation",
    "voice": "audio_generation",
}
_SLOT_KINDS = {
    "text": "text",
    "image": "image",
    "video": "video",
    "audio": "audio",
    "music": "music",
    "voice": "audio",
}
_WORKFLOW_OUTPUT_KINDS = {
    "text": "text",
    "image": "image",
    "video": "video",
    "audio": "audio",
    "music": "audio",
    "voice": "audio",
}
_WORKFLOW_SOURCES = {
    "runninghub_app": "runninghub",
    "runninghub_workflow": "runninghub",
    "local_comfy_workflow": "local-comfyui",
}
_WORKFLOW_INPUT_ROLES = frozenset({
    "prompt", "system_prompt", "reference", "source_video", "reference_audio", "first_frame", "last_frame",
})

_CAPABILITY_MODULE = {"name": "@laohu/studio-models", "version": "1"}


def _capability_ref(name: str) -> Dict[str, Any]:
    return {"module": dict(_CAPABILITY_MODULE), "name": name}

# 这些声明与 static/hypit-endpoint.mjs 保持同一份公开能力边界。Hypit 的
# `speech-generation` 走工作台 audio_generation 适配器，但仍以独立 voice
# 槽位呈现，避免把语音误认为音乐。
SUPPORTED_HYPIT_CAPABILITIES = (
    {
        "slot": "text",
        "kind": "text",
        "node_type": "text_generation",
        "capability": _capability_ref("text-generation"),
        "returns": _capability_ref("text"),
        "label": {"zh": "文本生成", "en": "Text generation"},
    },
    {
        "slot": "image",
        "kind": "image",
        "node_type": "image_generation",
        "capability": _capability_ref("image-generation"),
        "returns": _capability_ref("image-set"),
        "label": {"zh": "图片生成", "en": "Image generation"},
    },
    {
        "slot": "video",
        "kind": "video",
        "node_type": "video_generation",
        "capability": _capability_ref("video-generation"),
        "returns": _capability_ref("video-set"),
        "label": {"zh": "视频生成", "en": "Video generation"},
    },
    {
        "slot": "audio", "kind": "audio", "node_type": "audio_generation",
        "capability": _capability_ref("audio-generation"), "returns": _capability_ref("audio-set"),
        "label": {"zh": "音频生成", "en": "Audio generation"},
    },
    {
        "slot": "music", "kind": "music", "node_type": "music_generation",
        "capability": _capability_ref("music-generation"), "returns": _capability_ref("audio-set"),
        "label": {"zh": "音乐生成", "en": "Music generation"},
    },
    {
        "slot": "voice",
        "kind": "audio",
        "node_type": "audio_generation",
        "capability": _capability_ref("speech-generation"),
        "returns": _capability_ref("audio-set"),
        "label": {"zh": "语音生成", "en": "Speech generation"},
    },
)

UNSUPPORTED_HYPIT_CAPABILITIES = (
    {
        "name": "ai-application",
        "label": {"zh": "AI 应用", "en": "AI application"},
        "reason": {
            "zh": "任意 AI 应用仍不能作为原生能力直接运行；已映射到六个生成槽的来源会按该槽输入和输出契约校验。",
            "en": "Arbitrary AI applications are not direct native capabilities; sources mapped to one of the six generation slots are validated against that slot's input and output contract.",
        },
    },
)

_MEDIA_KEYS = {
    "reference": "reference",
    "references": "reference",
    "image": "reference",
    "images": "reference",
    "reference_image": "reference",
    "reference_images": "reference",
    "referenceimage": "reference",
    "referenceimages": "reference",
    "source_video": "source_video",
    "source_videos": "source_video",
    "sourcevideo": "source_video",
    "sourcevideos": "source_video",
    "video": "source_video",
    "videos": "source_video",
    "reference_video": "source_video",
    "reference_videos": "source_video",
    "referencevideo": "source_video",
    "referencevideos": "source_video",
    "audio": "reference_audio",
    "audios": "reference_audio",
    "reference_audio": "reference_audio",
    "reference_audios": "reference_audio",
    "referenceaudio": "reference_audio",
    "referenceaudios": "reference_audio",
    "first_frame": "first_frame",
    "firstframe": "first_frame",
    "last_frame": "last_frame",
    "lastframe": "last_frame",
}
_PROMPT_KEYS = {
    "prompt",
    "text",
    "message",
    "instruction",
    "description",
    "lyrics",
    "voice_description",
    "voicedescription",
}
_SYSTEM_PROMPT_KEYS = {"system_prompt", "systemprompt"}
_PARAMETER_KEYS = {
    "aspectratio": "aspect_ratio",
    "aspect_ratio": "aspect_ratio",
    "duration": "duration",
    "resolution": "resolution",
    "generateaudio": "generate_audio",
    "generate_audio": "generate_audio",
    "returnlastframe": "return_last_frame",
    "return_last_frame": "return_last_frame",
    "speaker": "speaker",
    "voice": "voice",
    "format": "format",
    "samplerate": "sample_rate",
    "sample_rate": "sample_rate",
    "speechrate": "speech_rate",
    "speech_rate": "speech_rate",
    "loudnessrate": "loudness_rate",
    "loudness_rate": "loudness_rate",
    "pitchrate": "pitch_rate",
    "pitch_rate": "pitch_rate",
    "seed": "seed",
    "count": "count",
    "watermark": "watermark",
    "quality": "quality",
    "size": "size",
}
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "accesstoken",
    "auth_token",
    "authtoken",
    "bearer_token",
    "bearertoken",
    "session_token",
    "sessiontoken",
    "refresh_token",
    "refreshtoken",
    "id_token",
    "idtoken",
    "secret",
    "token",
    "password",
    "authorization",
    "credential",
}
_SECRET_FIELD_PARTS = ("api_key", "apikey", "secret", "password", "access_token", "authorization", "credential")
_SECRET_IDENTIFIER_NAMES = _SECRET_KEYS | {"api_token", "apitoken", "token_value", "tokenvalue"}


def _is_secret_identifier(value: Any) -> bool:
    """识别凭据字段名，同时保留 max_tokens、token_count 等合法数值参数。"""
    for part in re.split(r"::", str(value or "")):
        normal = re.sub(r"[^a-z0-9]+", "_", part.lower()).strip("_")
        compact = normal.replace("_", "")
        if normal in _SECRET_IDENTIFIER_NAMES or compact in _SECRET_IDENTIFIER_NAMES:
            return True
        if any(token in normal for token in _SECRET_FIELD_PARTS):
            return True
    return False


def _now() -> float:
    return time.time()


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _empty_defaults() -> Dict[str, Dict[str, Any]]:
    return {slot: {"selection_kind": "api_model", "provider": "", "model": "", "region": "", "parameters": {}} for slot in _SLOTS}


def _normalise_region(value: Any, label: str = "RunningHub 站点") -> str:
    region = str(value or "").strip().lower()
    if not region:
        return ""
    if region not in _RUNNINGHUB_REGIONS:
        raise HTTPException(status_code=400, detail=f"{label}不受支持：{region}")
    return region


def _safe_identifier(value: Any, label: str, pattern: re.Pattern[str]) -> str:
    text = str(value or "")
    if not pattern.fullmatch(text):
        raise HTTPException(status_code=400, detail=f"{label} 不合法")
    return text


def _raise_storage(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, DataFileError):
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    raise exc


def _provider_id(provider: Mapping[str, Any]) -> str:
    return str(provider.get("id") or provider.get("provider_id") or "")


def _model_id(model: Mapping[str, Any]) -> str:
    return str(model.get("model_id") or model.get("id") or "")


def _provider_models(provider: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    models = provider.get("models")
    if isinstance(models, list):
        return (item for item in models if isinstance(item, Mapping))
    # 某些兼容目录以能力列表分栏，但仍然是同一份用户启用白名单。
    output = []
    for key, node_type in (
        ("chat_models", "text_generation"),
        ("image_models", "image_generation"),
        ("video_models", "video_generation"),
        ("audio_models", "audio_generation"),
    ):
        for item in provider.get(key) or []:
            if isinstance(item, str):
                output.append({"model_id": item, "node_type": node_type})
            elif isinstance(item, Mapping):
                value = dict(item)
                value.setdefault("node_type", node_type)
                output.append(value)
    return output


def _provider_region_candidates(provider: Mapping[str, Any]) -> set[str]:
    raw = provider.get("regions")
    if isinstance(raw, list):
        values = set()
        for item in raw:
            if isinstance(item, Mapping):
                region = str(item.get("region") or "").strip().lower()
                if region in _RUNNINGHUB_REGIONS and item.get("enabled") is True:
                    values.add(region)
            else:
                region = str(item or "").strip().lower()
                if region in _RUNNINGHUB_REGIONS:
                    values.add(region)
        if values:
            return values
    raw_regions = provider.get("rh_regions")
    if isinstance(raw_regions, Mapping):
        return {
            str(region).strip().lower()
            for region, config in raw_regions.items()
            if str(region).strip().lower() in _RUNNINGHUB_REGIONS
            and isinstance(config, Mapping)
            and config.get("enabled") is True
        }
    return set()


def _model_region_candidates(model: Mapping[str, Any], provider: Mapping[str, Any]) -> set[str]:
    values = model.get("regions")
    regions = {
        str(item).strip().lower()
        for item in values
        if str(item).strip().lower() in _RUNNINGHUB_REGIONS
    } if isinstance(values, list) else set()
    profiles = model.get("region_profiles")
    if isinstance(profiles, Mapping):
        regions.update(
            str(region).strip().lower()
            for region in profiles
            if str(region).strip().lower() in _RUNNINGHUB_REGIONS
        )
    return regions or _provider_region_candidates(provider)


def _merge_profile(
    model: Mapping[str, Any], provider: Mapping[str, Any], provider_id: str, region: str = ""
) -> Dict[str, Any]:
    value = dict(model)
    if region:
        scoped_profiles = model.get("region_profiles")
        scoped = scoped_profiles.get(region) if isinstance(scoped_profiles, Mapping) else None
        if isinstance(scoped, Mapping):
            value.update(_copy(scoped))
        value["region"] = region
    value.setdefault("provider_id", provider_id)
    value.setdefault("provider_name", provider.get("name") or provider_id)
    return value


def _find_profile(
    catalog: Mapping[str, Any], provider_id: str, model_id: str, node_type: str, region: str = ""
) -> Optional[Dict[str, Any]]:
    region = _normalise_region(region)
    for provider in catalog.get("providers") or []:
        if not isinstance(provider, Mapping) or _provider_id(provider) != provider_id:
            continue
        for model in _provider_models(provider):
            if _model_id(model) != model_id:
                continue
            if region and region not in _model_region_candidates(model, provider):
                continue
            value = _merge_profile(model, provider, provider_id, region)
            if value.get("node_type") == node_type:
                return value
    return None


def _resolve_profile(
    catalog: Mapping[str, Any], provider_id: str, model_id: str, node_type: str, region: str = ""
) -> tuple[Dict[str, Any], str]:
    requested_region = _normalise_region(region)
    provider = next(
        (
            item
            for item in catalog.get("providers") or []
            if isinstance(item, Mapping) and _provider_id(item) == provider_id
        ),
        None,
    )
    if provider is None:
        raise HTTPException(status_code=400, detail=f"模型 {model_id} 不在当前用户启用白名单中")

    matches = [
        model
        for model in _provider_models(provider)
        if _model_id(model) == model_id and model.get("node_type") == node_type
    ]
    if not matches:
        raise HTTPException(status_code=400, detail=f"模型 {model_id} 不在当前用户启用白名单中")

    if provider_id != "runninghub":
        if requested_region:
            raise HTTPException(status_code=400, detail="只有 RunningHub 模型支持 region=global/cn")
        profile = _find_profile(catalog, provider_id, model_id, node_type)
        assert profile is not None
        return profile, ""

    available_regions = set()
    for model in matches:
        available_regions.update(_model_region_candidates(model, provider))
    if requested_region:
        if available_regions and requested_region not in available_regions:
            raise HTTPException(
                status_code=400,
                detail=f"RunningHub 模型 {model_id} 未在 {requested_region} 站点启用",
            )
        profile = _find_profile(catalog, provider_id, model_id, node_type, requested_region)
        if profile is None:
            raise HTTPException(status_code=400, detail=f"模型 {model_id} 不在 {requested_region} 站点启用白名单中")
        return profile, requested_region

    if len(available_regions) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"RunningHub 模型 {model_id} 同时属于多个站点，请明确选择 region=global 或 region=cn",
        )
    resolved_region = next(iter(available_regions), "")
    profile = _find_profile(catalog, provider_id, model_id, node_type, resolved_region)
    if profile is None:
        raise HTTPException(status_code=400, detail=f"模型 {model_id} 不在当前用户启用白名单中")
    return profile, resolved_region


def _parameter_schema(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    parameters = profile.get("parameters")
    return parameters if isinstance(parameters, Mapping) else {}


def _check_scalar_type(name: str, value: Any, schema: Mapping[str, Any]) -> None:
    kind = str(schema.get("type") or "").lower()
    if kind in {"integer", "int"} and (isinstance(value, bool) or not isinstance(value, int)):
        raise HTTPException(status_code=400, detail=f"参数 {name} 必须是整数")
    if kind in {"number", "float"} and (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise HTTPException(status_code=400, detail=f"参数 {name} 必须是数字")
    if kind in {"boolean", "bool"} and not isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"参数 {name} 必须是布尔值")
    if kind in {"text", "string", "str"} and not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"参数 {name} 必须是文本")
    if kind in {"array", "list"} and not isinstance(value, list):
        raise HTTPException(status_code=400, detail=f"参数 {name} 必须是数组")

    choices = schema.get("enum")
    if choices is None:
        choices = schema.get("options")
    if choices is None:
        choices = schema.get("values")
    if isinstance(choices, list) and value not in choices:
        raise HTTPException(status_code=400, detail=f"参数 {name} 不在模型允许值内")
    for key, message in (("min", "不能小于"), ("minimum", "不能小于")):
        if key in schema and isinstance(value, (int, float)) and value < schema[key]:
            raise HTTPException(status_code=400, detail=f"参数 {name} {message} {schema[key]}")
    for key, message in (("max", "不能大于"), ("maximum", "不能大于")):
        if key in schema and isinstance(value, (int, float)) and value > schema[key]:
            raise HTTPException(status_code=400, detail=f"参数 {name} {message} {schema[key]}")


def _validate_parameters(profile: Mapping[str, Any], parameters: Mapping[str, Any]) -> Dict[str, Any]:
    schema = _parameter_schema(profile)
    result = dict(parameters)
    for key, value in result.items():
        key_text = str(key)
        if _is_secret_identifier(key_text):
            raise HTTPException(status_code=400, detail="模型参数不能包含 API Key 或凭据")
        if schema and key_text not in schema:
            raise HTTPException(status_code=400, detail=f"参数 {key_text} 不属于模型已确认参数")
        if key_text in schema and isinstance(schema[key_text], Mapping):
            _check_scalar_type(key_text, value, schema[key_text])
    return result


def _reject_secrets(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_secret_identifier(key):
                raise HTTPException(status_code=400, detail="Hypit 设置不能保存 API Key 或凭据")
            _reject_secrets(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secrets(item)


def _workflow_field_key(field: Mapping[str, Any], source: str) -> str:
    if source == "local_comfy_workflow":
        return str(field.get("id") or field.get("paramid") or field.get("paramId") or field.get("key") or "").strip()
    node_id = str(field.get("nodeId") or field.get("node_id") or "").strip()
    name = str(field.get("fieldName") or field.get("field_name") or field.get("inputName") or "").strip()
    if not node_id or not name:
        param_id = str(field.get("paramid") or field.get("paramId") or field.get("key") or "").strip()
        if "::" in param_id:
            node_id, name = (part.strip() for part in param_id.split("::", 1))
    return f"{node_id}::{name}" if node_id or name else str(field.get("key") or "").strip()


def _workflow_secret_field(field: Mapping[str, Any]) -> bool:
    identity_fields = [field.get(key) for key in (
        "fieldName", "field_name", "inputName", "input", "name", "label", "id", "key", "paramid", "paramId",
    )]
    field_type = str(field.get("fieldType") or field.get("type") or field.get("kind") or "").lower()
    return field_type in {"password", "secret", "credential", "token"} or any(
        _is_secret_identifier(identity) for identity in identity_fields if identity
    )


def _safe_workflow_fields(descriptor: Mapping[str, Any]) -> list[Dict[str, Any]]:
    source = str(descriptor.get("source") or "")
    raw_fields = descriptor.get("fields")
    if not isinstance(raw_fields, list):
        return []
    output = []
    for field in raw_fields:
        if not isinstance(field, Mapping) or _workflow_secret_field(field):
            continue
        key = _workflow_field_key(field, source)
        if not key:
            continue
        raw_type = str(field.get("fieldType") or field.get("type") or field.get("kind") or "").strip().lower()
        type_map = {
            "string": "text", "plain-text": "text", "textarea": "text", "text": "text",
            "float": "number", "integer": "number", "int": "number", "slider": "number", "number": "number",
            "boolean": "boolean", "bool": "boolean", "image": "image", "video": "video", "audio": "audio",
            "switch": "select", "combo": "select", "dropdown": "select", "enum": "select", "select": "select", "list": "select",
        }
        # Comfy 的 STRING/FLOAT/INT/BOOLEAN/COMBO 是配置中明确记录的 Widget 类型。
        type_map.update({
            "string": "text", "float": "number", "int": "number", "combo": "select",
        })
        field_type = type_map.get(raw_type, "unknown")
        item: Dict[str, Any] = {
            "key": key,
            "label": str(field.get("label") or field.get("fieldName") or field.get("field_name") or field.get("name") or key),
            "type": field_type,
            "required": field.get("required") is True,
        }
        role = str(field.get("inputRole") or field.get("input_role") or field.get("semanticRole") or field.get("semantic_role") or field.get("role") or "").strip()
        if role:
            item["input_role"] = role
        default_value = field.get("fieldValue", field.get("defaultValue", field.get("default")))
        if (isinstance(default_value, (str, int, float, bool)) and not isinstance(default_value, float) or
                isinstance(default_value, float) and math.isfinite(default_value) or
                isinstance(default_value, str) and len(default_value) <= 500):
            if default_value is not None:
                item["default"] = default_value
        options = field.get("options") or field.get("values")
        if isinstance(options, list):
            item["options"] = [value for value in options if isinstance(value, (str, int, float, bool))][:100]
        for target, sources in (("min", ("min", "minimum")), ("max", ("max", "maximum")), ("step", ("step",))):
            bound = next((field.get(name) for name in sources if field.get(name) not in (None, "")), None)
            if isinstance(bound, (int, float)) and not isinstance(bound, bool) and math.isfinite(float(bound)):
                item[target] = bound
        output.append(item)
    return output


def _workflow_schema_state(descriptor: Mapping[str, Any], fields: list[Dict[str, Any]]) -> tuple[str, str, str]:
    raw_fields = descriptor.get("fields") if isinstance(descriptor.get("fields"), list) else []
    if any(isinstance(field, Mapping) and _workflow_secret_field(field) and field.get("required") is True for field in raw_fields):
        return "invalid", "secret_required_field", "工作流包含必填凭据字段，不能用于 Hypit。"
    unknown_required = any(field.get("type") == "unknown" and field.get("required") for field in fields)
    if unknown_required:
        return "invalid", "required_field_type_unknown", "工作流存在必填字段类型未确认，请重新同步或配置字段 Schema。"
    known_fields = [field for field in fields if field.get("type") != "unknown"]
    raw_status = str(descriptor.get("schema_status") or "").strip().lower()
    if raw_status == "invalid":
        return "invalid", "schema_invalid", "此来源的输入字段 Schema 无效，需要重新同步。"
    if raw_status == "missing" or not known_fields:
        return "missing", "schema_missing", "此来源缺少可确认类型的输入字段 Schema，请先同步或配置字段。"
    return "ready", "", ""


def _workflow_schema_fingerprint(descriptor: Mapping[str, Any]) -> str:
    return _hash({"fields": _safe_workflow_fields(descriptor)})


def _public_workflow_option(descriptor: Mapping[str, Any]) -> Dict[str, Any]:
    source = str(descriptor.get("source") or "")
    provider_id = str(descriptor.get("provider_id") or "")
    region = str(descriptor.get("region") or "")
    item_id = str(descriptor.get("item_id") or "")
    fields = _safe_workflow_fields(descriptor)
    schema_status, reason_code, reason = _workflow_schema_state(descriptor, fields)
    enabled = descriptor.get("enabled") is True
    declared_reason_code = str(descriptor.get("reason_code") or "").strip()
    declared_reason = str(descriptor.get("unavailable_reason") or "").strip()
    if not enabled:
        reason_code = declared_reason_code or "source_disabled"
        reason = declared_reason or "来源或所属站点当前已停用。"
    elif declared_reason_code:
        reason_code, reason = declared_reason_code, declared_reason or "工作流来源当前不可用。"
    identity = {"source": source, "provider_id": provider_id, "region": region, "item_id": item_id}
    return {
        "id": _hash(identity), "name": str(descriptor.get("name") or item_id),
        **identity, "enabled": enabled, "available": not bool(reason_code),
        "schema_status": schema_status,
        "schema_fingerprint": _workflow_schema_fingerprint(descriptor) if fields else "",
        "fields": fields, "reason_code": reason_code, "unavailable_reason": reason,
    }


def _normalise_slot(raw: Any, slot: str) -> Dict[str, Any]:
    if raw is None:
        return {"selection_kind": "api_model", "provider": "", "model": "", "region": "", "parameters": {}}
    if not isinstance(raw, Mapping):
        raise HTTPException(status_code=400, detail=f"{slot} 默认模型格式不正确")
    _reject_secrets(raw)
    selection_kind = str(raw.get("selection_kind") or "api_model").strip().lower()
    if selection_kind == "api_model":
        provider = str(raw.get("provider") or raw.get("provider_id") or "")
        model = str(raw.get("model") or raw.get("model_id") or "")
        region = _normalise_region(raw.get("region"), f"{slot} RunningHub 站点")
        parameters = raw.get("parameters", {})
        if parameters is None:
            parameters = {}
        if not isinstance(parameters, Mapping):
            raise HTTPException(status_code=400, detail=f"{slot} 默认参数必须是对象")
        if bool(provider) != bool(model):
            raise HTTPException(status_code=400, detail=f"{slot} 必须同时选择平台和模型")
        if region and not provider:
            raise HTTPException(status_code=400, detail=f"{slot} 未选择模型，不能保存站点")
        return {"selection_kind": "api_model", "provider": provider, "model": model, "region": region, "parameters": dict(parameters)}
    if selection_kind != "workflow":
        raise HTTPException(status_code=400, detail=f"{slot} 来源类型不受支持")
    source = str(raw.get("source") or "").strip()
    provider_id = str(raw.get("provider_id") or "").strip()
    if source not in _WORKFLOW_SOURCES or provider_id != _WORKFLOW_SOURCES[source]:
        raise HTTPException(status_code=400, detail=f"{slot} 工作流来源身份不正确")
    if str(raw.get("provider") or raw.get("model") or raw.get("model_id") or "").strip():
        raise HTTPException(status_code=400, detail="工作流来源不能伪装成 API 模型")
    region = _normalise_region(raw.get("region"), f"{slot} RunningHub 站点")
    if source.startswith("runninghub_") and not region:
        raise HTTPException(status_code=400, detail=f"{slot} 必须明确选择 RunningHub 站点")
    if source == "local_comfy_workflow" and region:
        raise HTTPException(status_code=400, detail="本地 ComfyUI 工作流不能绑定 RunningHub 站点")
    item_id = str(raw.get("item_id") or "").strip()
    if not item_id or "\x00" in item_id or "\n" in item_id or "\r" in item_id:
        raise HTTPException(status_code=400, detail=f"{slot} 工作流身份不正确")
    if raw.get("expected_slot") != slot or raw.get("expected_kind") != _WORKFLOW_OUTPUT_KINDS[slot]:
        raise HTTPException(status_code=400, detail=f"{slot} 工作流用途确认与目标槽位不一致")
    if raw.get("confirmed_for_slot") is not True:
        raise HTTPException(status_code=400, detail=f"请确认该工作流用于 {slot} 生成用途")
    fingerprint = str(raw.get("schema_fingerprint") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise HTTPException(status_code=400, detail=f"{slot} 工作流字段映射缺少有效 Schema 指纹")
    input_bindings = raw.get("input_bindings") or {}
    field_values = raw.get("field_values") or {}
    if not isinstance(input_bindings, Mapping) or not isinstance(field_values, Mapping):
        raise HTTPException(status_code=400, detail=f"{slot} 工作流字段绑定格式不正确")
    normalized_bindings = {}
    for role, targets in input_bindings.items():
        if role not in _WORKFLOW_INPUT_ROLES:
            raise HTTPException(status_code=400, detail=f"{slot} 工作流输入角色不受支持：{role}")
        values = [targets] if isinstance(targets, str) else targets
        if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value.strip() for value in values):
            raise HTTPException(status_code=400, detail=f"{slot} 工作流输入 {role} 必须绑定一个或多个字段")
        normalized_bindings[str(role)] = [value.strip() for value in values]
    normalized_values = {}
    for key, value in field_values.items():
        key = str(key).strip()
        if not key or _is_secret_identifier(key):
            raise HTTPException(status_code=400, detail="工作流字段值不能保存凭据字段")
        try:
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"工作流字段 {key} 不是有效 JSON 值") from exc
        normalized_values[key] = _copy(value)
    return {
        "selection_kind": "workflow", "provider": "", "model": "", "region": region, "parameters": {},
        "source": source, "provider_id": provider_id, "item_id": item_id,
        "expected_slot": slot, "expected_kind": _WORKFLOW_OUTPUT_KINDS[slot], "confirmed_for_slot": True,
        "schema_fingerprint": fingerprint, "input_bindings": normalized_bindings, "field_values": normalized_values,
    }


def _workflow_snapshot(descriptor: Mapping[str, Any]) -> Dict[str, Any]:
    fields = descriptor.get("fields") if isinstance(descriptor.get("fields"), list) else []
    safe_fields = []
    safe_names = {
        "nodeId", "node_id", "fieldName", "field_name", "inputName", "fieldType", "type", "kind",
        "required", "defaultValue", "fieldValue", "default", "options", "values", "step",
        "inputRole", "input_role", "role", "node", "input", "name", "id", "paramid", "paramId", "key", "label",
        "semanticRole", "semantic_role", "min", "max", "minimum", "maximum", "optionLabels",
    }
    for field in fields:
        if not isinstance(field, Mapping) or _workflow_secret_field(field):
            continue
        cleaned = {}
        for key, value in field.items():
            if key not in safe_names:
                continue
            if key in {"options", "values", "optionLabels"}:
                if isinstance(value, list):
                    cleaned[key] = [item for item in value if isinstance(item, (str, int, float, bool)) and
                                    not isinstance(item, float) or isinstance(item, float) and math.isfinite(item)]
                continue
            if key in {"defaultValue", "fieldValue", "default"}:
                if isinstance(value, (str, int, bool)) or isinstance(value, float) and math.isfinite(value):
                    cleaned[key] = value
                elif isinstance(value, list):
                    cleaned[key] = [item for item in value if isinstance(item, (str, int, float, bool)) and
                                    not isinstance(item, float) or isinstance(item, float) and math.isfinite(item)]
                continue
            cleaned[key] = _copy(value)
        if cleaned:
            safe_fields.append(cleaned)
    snapshot = {
        "source": str(descriptor.get("source") or ""),
        "provider_id": str(descriptor.get("provider_id") or ""),
        "region": str(descriptor.get("region") or ""),
        "item_id": str(descriptor.get("item_id") or ""),
        "name": str(descriptor.get("name") or descriptor.get("item_id") or ""),
        "enabled": descriptor.get("enabled") is True,
        "schema_status": str(descriptor.get("schema_status") or ""),
        "fields": safe_fields,
        "schema_fingerprint": _workflow_schema_fingerprint({**descriptor, "fields": safe_fields}),
        "use_wallet": bool(descriptor.get("use_wallet")),
        "instance_type": str(descriptor.get("instance_type") or ""),
        "optional_image_mode": str(descriptor.get("optional_image_mode") or "prune-workflow"),
    }
    workflow_json = descriptor.get("workflow_json", descriptor.get("workflowJson"))
    if workflow_json is not None:
        if not isinstance(workflow_json, (dict, list)):
            raise HTTPException(status_code=400, detail="工作流定义格式无效")
        _reject_secrets(workflow_json)
        snapshot["workflow_json"] = _copy(workflow_json)
    return snapshot


def _check_workflow_selection(value: Mapping[str, Any], descriptor: Mapping[str, Any], slot: str) -> Dict[str, Any]:
    for key in ("source", "provider_id", "region", "item_id"):
        actual = str(descriptor.get(key) or "")
        if actual != str(value.get(key) or ""):
            raise HTTPException(status_code=409, detail="已选工作流身份发生变化，请重新选择")
    if descriptor.get("enabled") is not True:
        raise HTTPException(status_code=400, detail="已选工作流来源或站点已停用，不能提交新任务")
    option = _public_workflow_option(descriptor)
    if option["schema_status"] != "ready":
        raise HTTPException(status_code=400, detail=option["unavailable_reason"] or "工作流 Schema 不可用")
    if option["schema_fingerprint"] != value.get("schema_fingerprint"):
        raise HTTPException(status_code=409, detail="工作流字段 Schema 已变化，请重新检查字段映射后再运行")
    known_fields = {field["key"]: field for field in _safe_workflow_fields(descriptor)}
    unknown_values = set(value.get("field_values") or {}) - set(known_fields)
    if unknown_values:
        raise HTTPException(status_code=400, detail="工作流默认字段已失效：" + ", ".join(sorted(unknown_values)))
    used_fields = set()
    role_types = {
        "prompt": "text", "system_prompt": "text", "reference": "image", "first_frame": "image",
        "last_frame": "image", "source_video": "video", "reference_audio": "audio",
    }
    for role, targets in (value.get("input_bindings") or {}).items():
        for target in targets:
            field = known_fields.get(target)
            if field is None:
                raise HTTPException(status_code=400, detail=f"工作流映射字段不存在或不允许使用：{target}")
            if field.get("type") != role_types[role]:
                raise HTTPException(status_code=400, detail=f"工作流字段 {target} 与 {role} 输入类型不匹配")
            if target in used_fields:
                raise HTTPException(status_code=400, detail=f"工作流字段 {target} 不能绑定多个输入角色")
            used_fields.add(target)
    return _workflow_snapshot(descriptor)


def _capability_by_kind(kind: str) -> Optional[Mapping[str, Any]]:
    for item in SUPPORTED_HYPIT_CAPABILITIES:
        if item["kind"] == kind:
            return item
    return None


def _capability_kind(value: Any) -> Optional[str]:
    if isinstance(value, str):
        text = value
        module = ""
        name = text
    elif isinstance(value, Mapping):
        module_value = value.get("module")
        module = str(module_value.get("name") if isinstance(module_value, Mapping) else module_value or "")
        name = str(value.get("name") or value.get("id") or "")
    else:
        return None
    if module and module != _CAPABILITY_MODULE["name"]:
        return None
    for item in SUPPORTED_HYPIT_CAPABILITIES:
        capability = item["capability"]
        returns = item["returns"]
        if name in {item["kind"], capability["name"], returns["name"]}:
            return item["kind"]
    aliases = {"speech": "audio", "audio-generation": "audio"}
    return aliases.get(name)


def _extract_url(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return ""
    for key in ("url", "src", "href", "path"):
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
    artifact = value.get("artifact")
    if isinstance(artifact, Mapping):
        return _extract_url(artifact)
    return ""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _collect_media(value: Any, role: str, output: Dict[str, list[Any]]) -> None:
    for item in _as_list(value):
        url = _extract_url(item)
        if not url:
            raise HTTPException(status_code=400, detail=f"{role} 输入缺少可访问资源地址")
        output.setdefault(role, []).append(url)


def _normalise_ports(
    raw: Mapping[str, Any], prompt_parts: list[str], system_parts: list[str], media: Dict[str, list[Any]], parameters: Dict[str, Any]
) -> None:
    ports = raw.get("ports")
    if ports is None:
        return
    if not isinstance(ports, Mapping):
        raise HTTPException(status_code=400, detail="Endpoint ports 必须是对象")
    for key, value in ports.items():
        name = str(key)
        normal = re.sub(r"[^a-z0-9_]", "", name.lower())
        if normal in _MEDIA_KEYS:
            _collect_media(value, _MEDIA_KEYS[normal], media)
            continue
        if normal in _PROMPT_KEYS:
            for item in _as_list(value):
                if str(item).strip():
                    prompt_parts.append(str(item))
            continue
        if normal in _SYSTEM_PROMPT_KEYS:
            for item in _as_list(value):
                if str(item).strip():
                    system_parts.append(str(item))
            continue
        parameter = _PARAMETER_KEYS.get(normal)
        if parameter:
            parameters[parameter] = value
            continue
        # Hypit generation ports carry their media role in each value, for
        # example {role: "image", url: ...}. Keep the role typed even when
        # the model's exact port name is provider-specific (referenceImage,
        # firstFrame, referenceAudio, ...).
        media_values = _as_list(value)
        if media_values and all(isinstance(item, Mapping) and item.get("role") in {"image", "video", "audio"} for item in media_values):
            for item in media_values:
                role = {"image": "reference", "video": "source_video", "audio": "reference_audio"}[item["role"]]
                _collect_media(item, role, media)
            continue
        if value not in (None, "", [], {}):
            raise HTTPException(status_code=400, detail=f"暂不支持 Endpoint 输入端口 {name}")


def _normalise_media_inputs(raw: Mapping[str, Any], media: Dict[str, list[Any]]) -> None:
    inputs = raw.get("inputs")
    if inputs is None:
        return
    if not isinstance(inputs, Mapping):
        raise HTTPException(status_code=400, detail="Endpoint inputs 必须是对象")
    for key, value in inputs.items():
        normal = re.sub(r"[^a-z0-9_]", "", str(key).lower())
        role = _MEDIA_KEYS.get(normal)
        if role is None:
            if key == "prompt":
                continue
            raise HTTPException(status_code=400, detail=f"暂不支持 Endpoint 输入类型 {key}")
        _collect_media(value, role, media)


def _collect_constraint_parameters(raw: Mapping[str, Any], parameters: Dict[str, Any]) -> None:
    supplied = raw.get("parameters")
    if supplied is not None:
        if not isinstance(supplied, Mapping):
            raise HTTPException(status_code=400, detail="模型参数必须是对象")
        parameters.update(dict(supplied))
    for key, value in raw.items():
        normal = re.sub(r"[^a-z0-9_]", "", str(key).lower())
        mapped = _PARAMETER_KEYS.get(normal)
        if mapped:
            parameters[mapped] = value


def _project_constraints(raw: Mapping[str, Any], binding: Mapping[str, Any], catalog: Mapping[str, Any]) -> Dict[str, Any]:
    constraints = raw.get("constraints") if isinstance(raw.get("constraints"), Mapping) else raw
    if not isinstance(constraints, Mapping):
        raise HTTPException(status_code=400, detail="Hypit 请求约束必须是对象")
    nested = constraints.get("studio_request") or constraints.get("request")
    if isinstance(nested, Mapping):
        constraints = nested

    capability_kind = _capability_kind(raw.get("capability"))
    kind = str(constraints.get("kind") or raw.get("kind") or capability_kind or "").strip().lower()
    if kind == "speech":
        kind = "audio"
    if not kind or _capability_by_kind(kind) is None:
        raise HTTPException(status_code=400, detail="Hypit 只支持已声明的文本、图片、视频、语音和音乐能力")
    if capability_kind and capability_kind != kind:
        raise HTTPException(status_code=400, detail="Endpoint capability 与请求 kind 不一致")
    capability = _capability_by_kind(kind)
    assert capability is not None
    slot = str(constraints.get("slot") or capability["slot"])
    if slot not in _SLOTS or _SLOT_KINDS.get(slot) != kind:
        raise HTTPException(status_code=400, detail=f"能力 {kind} 的默认模型槽位不正确")
    defaults = binding.get("defaults") if isinstance(binding, Mapping) else {}
    selected = defaults.get(slot) if isinstance(defaults, Mapping) else None
    if not isinstance(selected, Mapping):
        selected = {"provider": "", "model": "", "parameters": {}}
    provider = str(constraints.get("provider_id") or constraints.get("provider") or selected.get("provider") or "")
    model = str(constraints.get("model") or constraints.get("model_id") or selected.get("model") or "")
    if not provider or not model:
        raise HTTPException(status_code=400, detail=f"请先为 {slot} 配置工作台模型")

    explicit_region = constraints.get("region")
    if explicit_region is None:
        explicit_region = raw.get("region")
    if explicit_region is None and provider == selected.get("provider") and model == selected.get("model"):
        explicit_region = selected.get("region")
    profile, region = _resolve_profile(
        catalog,
        provider,
        model,
        _SLOT_NODE_TYPES[slot],
        _normalise_region(explicit_region),
    )
    from studio_module_models import hypit_profile_reasons
    if hypit_profile_reasons(slot, profile):
        raise HTTPException(400, detail="该模型不支持此 Hypit 生成用途，请重新选择模型")
    if profile.get("validation_mode") not in (None, "strict") or profile.get("readiness") not in (None, "ready") or profile.get("runnable") is False:
        readiness = profile.get("readiness") or "needs_profile"
        if readiness == "adapter_missing":
            message = f"模型 {model} 已有能力档案，但工作台适配器尚未完成"
        else:
            message = f"模型 {model} 当前不可运行（{readiness}）"
        raise HTTPException(status_code=400, detail=message)

    # §10.7 收敛：显式 provider/model 覆盖不再是隐藏路径。
    # 原生 Endpoint 会转发这些字段（static/hypit-endpoint.mjs），因此保留受限兼容：
    # 覆盖仍要落到该槽位真实允许、且档案就绪的模型；这里把来源显式记录下来，
    # 供审计与后续按槽位 runtime_model_override 策略判定，而不是静默绕过模块设置。
    explicit_override = bool(
        str(constraints.get("provider_id") or constraints.get("provider") or "").strip()
        or str(constraints.get("model") or constraints.get("model_id") or "").strip()
    )
    matches_module_binding = provider == selected.get("provider") and model == selected.get("model")
    model_source = "runtime_override" if (explicit_override and not matches_module_binding) else "module_settings"

    prompt_parts: list[str] = []
    system_parts: list[str] = []
    # Hypit 参数由本次复刻请求与模型默认契约决定，旧模块参数不再覆盖任务。
    parameters: Dict[str, Any] = {}
    _collect_constraint_parameters(constraints, parameters)
    _normalise_ports(constraints, prompt_parts, system_parts, media := {}, parameters)
    _normalise_media_inputs(constraints, media)
    for key in ("prompt", "text", "message", "instruction"):
        value = constraints.get(key)
        for item in _as_list(value):
            if str(item).strip():
                prompt_parts.append(str(item))
    for key in ("system_prompt", "systemPrompt"):
        value = constraints.get(key)
        for item in _as_list(value):
            if str(item).strip():
                system_parts.append(str(item))
    if not prompt_parts:
        raise HTTPException(status_code=400, detail="模型请求需要非空文本 prompt")

    parameters = _validate_parameters(profile, parameters)
    allowed_media = {
        "text": {"reference", "source_video", "reference_audio"},
        "image": {"reference"},
        "video": {"reference", "source_video", "reference_audio", "first_frame", "last_frame"},
        "audio": {"reference_audio"},
        "music": {"reference_audio"},
    }[kind]
    unexpected = [role for role, values in media.items() if values and role not in allowed_media]
    if unexpected:
        raise HTTPException(status_code=400, detail=f"{kind} 能力不支持输入类型：{', '.join(unexpected)}")

    prompt = "\n".join(prompt_parts).strip()
    inputs: Dict[str, Any] = {"prompt": prompt}
    input_roles: Dict[str, int] = {"prompt": 1}
    input_counts: Dict[str, int] = {"text" if kind == "text" else "prompt": 1}
    references = []
    for role in ("reference", "source_video", "reference_audio", "first_frame", "last_frame"):
        values = media.get(role) or []
        if not values:
            continue
        inputs[role] = values
        input_roles[role] = len(values)
        media_kind = {
            "reference": "image",
            "first_frame": "image",
            "last_frame": "image",
            "source_video": "video",
            "reference_audio": "audio",
        }[role]
        input_counts[media_kind] = input_counts.get(media_kind, 0) + len(values)
        references.extend({"kind": media_kind, "url": item} for item in values)
    return {
        "kind": kind,
        "provider_id": provider,
        "model": model,
        "region": region,
        "parameters": parameters,
        "prompt": prompt,
        "inputs": inputs,
        "input_roles": input_roles,
        "input_counts": input_counts,
        "references": references,
        "system_prompt": "\n".join(system_parts).strip(),
        "model_source": model_source,
        "module_slot": slot,
    }


def _project_workflow_constraints(raw: Mapping[str, Any], selected: Mapping[str, Any], slot: str,
                                  snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    constraints = raw.get("constraints") if isinstance(raw.get("constraints"), Mapping) else raw
    if not isinstance(constraints, Mapping):
        raise HTTPException(status_code=400, detail="Hypit 请求约束必须是对象")
    nested = constraints.get("studio_request") or constraints.get("request")
    if isinstance(nested, Mapping):
        constraints = nested
    capability_kind = _capability_kind(raw.get("capability"))
    kind = str(constraints.get("kind") or raw.get("kind") or capability_kind or "").strip().lower()
    if kind == "speech":
        kind = "audio"
    if not kind or _capability_by_kind(kind) is None:
        raise HTTPException(status_code=400, detail="Hypit 只支持已声明的文本、图片、视频、语音和音乐能力")
    if capability_kind and capability_kind != kind:
        raise HTTPException(status_code=400, detail="Endpoint capability 与请求 kind 不一致")
    if kind != _SLOT_KINDS[slot]:
        raise HTTPException(status_code=400, detail=f"当前工作流绑定到 {slot} 槽，不能用于 {kind} 请求")
    requested_slot = str(constraints.get("slot") or slot)
    if requested_slot != slot:
        raise HTTPException(status_code=400, detail="请求槽位与已保存工作流用途不一致")
    if selected.get("expected_slot") != slot or selected.get("expected_kind") != _WORKFLOW_OUTPUT_KINDS[slot]:
        raise HTTPException(status_code=400, detail="工作流用途确认与请求类型不一致")
    if selected.get("confirmed_for_slot") is not True:
        raise HTTPException(status_code=400, detail="请确认该工作流用于当前 Hypit 生成用途")

    prompt_parts: list[str] = []
    system_parts: list[str] = []
    parameters: Dict[str, Any] = {}
    media: Dict[str, list[Any]] = {}
    _collect_constraint_parameters(constraints, parameters)
    _normalise_ports(constraints, prompt_parts, system_parts, media, {})
    _normalise_media_inputs(constraints, media)
    for key in ("prompt", "text", "message", "instruction"):
        for item in _as_list(constraints.get(key)):
            if str(item).strip():
                prompt_parts.append(str(item))
    for key in ("system_prompt", "systemPrompt"):
        for item in _as_list(constraints.get(key)):
            if str(item).strip():
                system_parts.append(str(item))
    if not prompt_parts:
        raise HTTPException(status_code=400, detail="工作流请求需要非空文本 prompt")

    allowed_media = {
        "text": {"reference", "source_video", "reference_audio"},
        "image": {"reference"},
        "video": {"reference", "source_video", "reference_audio", "first_frame", "last_frame"},
        "audio": {"reference_audio"},
        "music": {"reference_audio"},
    }[kind]
    unexpected = [role for role, values in media.items() if values and role not in allowed_media]
    if unexpected:
        raise HTTPException(status_code=400, detail=f"{kind} 能力不支持输入类型：{', '.join(unexpected)}")

    references = []
    input_roles = {"prompt": 1}
    input_counts = {"text" if kind == "text" else "prompt": 1}
    inputs: Dict[str, Any] = {"prompt": "\n".join(prompt_parts).strip()}
    for role in ("reference", "source_video", "reference_audio", "first_frame", "last_frame"):
        values = media.get(role) or []
        if not values:
            continue
        inputs[role] = values
        input_roles[role] = len(values)
        media_kind = {"reference": "image", "first_frame": "image", "last_frame": "image",
                      "source_video": "video", "reference_audio": "audio"}[role]
        input_counts[media_kind] = input_counts.get(media_kind, 0) + len(values)
        references.extend({"kind": media_kind, "role": role, "url": value} for value in values)

    try:
        from studio_execution import project_workflow_fields
        projected_fields = project_workflow_fields(
            snapshot.get("fields") or [],
            engine="comfy" if selected["source"] == "local_comfy_workflow" else "runninghub",
            prompt=inputs["prompt"], system_prompt="\n".join(system_parts).strip(), references=references,
            input_bindings=selected.get("input_bindings") or {},
            stored_values=selected.get("field_values") or {}, task_values=parameters, strict=True,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    projected = {
        "kind": kind, "slot": slot, "module_slot": slot,
        "selection_kind": "workflow", "source": selected["source"],
        "provider_id": selected["provider_id"], "region": selected.get("region", ""),
        "item_id": selected["item_id"], "expected_slot": slot,
        "expected_kind": selected["expected_kind"],
        "schema_fingerprint": selected["schema_fingerprint"],
        "input_bindings": _copy(selected.get("input_bindings") or {}),
        "field_values": projected_fields["field_values"],
        "parameters": projected_fields["parameters"],
        "prompt": inputs["prompt"], "system_prompt": "\n".join(system_parts).strip(),
        "inputs": inputs, "input_roles": input_roles, "input_counts": input_counts,
        "references": references, "node_info_list": projected_fields["node_info_list"],
        "comfy_params": projected_fields["comfy_params"],
    }
    return projected


def _project_settings_canvas_request(raw: Mapping[str, Any], slot: str) -> Dict[str, Any]:
    """规整原生 Endpoint 输入；实际模型与字段契约由设置流程图节点决定。"""
    constraints = raw.get("constraints") if isinstance(raw.get("constraints"), Mapping) else raw
    if not isinstance(constraints, Mapping):
        raise HTTPException(status_code=400, detail="Hypit 请求约束必须是对象")
    nested = constraints.get("studio_request") or constraints.get("request")
    if isinstance(nested, Mapping):
        constraints = nested
    if slot not in _SLOTS:
        raise HTTPException(status_code=400, detail="Hypit 设置流程槽位不受支持")

    capability_kind = _capability_kind(raw.get("capability"))
    kind = str(constraints.get("kind") or raw.get("kind") or capability_kind or _SLOT_KINDS[slot]).strip().lower()
    if kind == "speech":
        kind = "audio"
    if kind != _SLOT_KINDS[slot]:
        raise HTTPException(status_code=400, detail=f"请求类型与 {slot} 设置流程槽位不一致")
    requested_slot = str(constraints.get("slot") or slot).strip().lower()
    if requested_slot != slot:
        raise HTTPException(status_code=400, detail="请求槽位与 Hypit 设置流程输出不一致")
    if capability_kind and capability_kind != kind:
        raise HTTPException(status_code=400, detail="Endpoint capability 与请求 kind 不一致")
    if any(str(constraints.get(key) or "").strip() for key in ("provider_id", "provider", "model", "model_id")):
        raise HTTPException(status_code=400, detail="Hypit 模型由设置流程图决定，请移除请求中的模型覆盖")

    prompt_parts: list[str] = []
    system_parts: list[str] = []
    media: Dict[str, list[Any]] = {}
    parameters: Dict[str, Any] = {}
    _collect_constraint_parameters(constraints, parameters)
    _normalise_ports(constraints, prompt_parts, system_parts, media, parameters)
    _normalise_media_inputs(constraints, media)
    for key in ("prompt", "text", "message", "instruction"):
        for item in _as_list(constraints.get(key)):
            if isinstance(item, str) and item.strip():
                prompt_parts.append(item)
    for key in ("system_prompt", "systemPrompt"):
        for item in _as_list(constraints.get(key)):
            if isinstance(item, str) and item.strip():
                system_parts.append(item)

    # 动态应用允许携带不同媒体类型；静态模型或应用字段是否接收，交给
    # 专用画布的真实节点 Schema 在任何供应商提交之前校验。
    inputs: Dict[str, Any] = {}
    references: list[dict[str, Any]] = []
    role_kinds = {
        "reference": "image", "first_frame": "image", "last_frame": "image",
        "source_video": "video", "reference_audio": "audio",
    }
    for role, values in media.items():
        if not values:
            continue
        inputs[role] = _copy(values)
        references.extend({"kind": role_kinds[role], "role": role, "url": value} for value in values)

    explicit_references = constraints.get("references")
    if explicit_references is not None:
        if not isinstance(explicit_references, list):
            raise HTTPException(status_code=400, detail="Hypit references 必须是数组")
        for reference in explicit_references:
            if not isinstance(reference, Mapping):
                raise HTTPException(status_code=400, detail="Hypit references 项必须是对象")
            item = _copy(dict(reference))
            ref_kind = str(item.get("kind") or item.get("media_type") or "").strip().lower()
            if ref_kind not in {"image", "video", "audio", "text"}:
                raise HTTPException(status_code=400, detail="Hypit reference 缺少已确认的输入类型")
            if ref_kind == "text":
                if not str(item.get("text") or item.get("content") or "").strip():
                    raise HTTPException(status_code=400, detail="Hypit 文本 reference 缺少正文")
            elif not _extract_url(item):
                raise HTTPException(status_code=400, detail=f"Hypit {ref_kind} reference 缺少资源地址")
            references.append(item)

    projected = {
        "selection_kind": "settings_canvas",
        "slot": slot,
        "kind": kind,
        "prompt": "\n".join(prompt_parts).strip(),
        "system_prompt": "\n".join(system_parts).strip(),
        "parameters": _copy(parameters),
        "inputs": inputs,
        "references": references,
    }
    for key in ("prompt_target_node_id", "promptTargetNodeId"):
        if constraints.get(key):
            projected["prompt_target_node_id"] = str(constraints[key])
            break
    return projected


def _task_key(project_id: str, request_id: str) -> str:
    return hashlib.sha256(f"{project_id}\0{request_id}".encode("utf-8")).hexdigest()


def _request_fingerprint(payload: Mapping[str, Any]) -> str:
    """只根据调用方输入做幂等判断，不把模块默认模型算进输入。"""
    value = _copy(dict(payload))
    value.pop("request_id", None)
    return _hash({"input": value})


def _public_task(record: Mapping[str, Any]) -> Dict[str, Any]:
    value = _copy(dict(record))
    value.pop("execution_snapshot", None)
    return value


def _normalise_result(value: Any) -> Any:
    # 回调返回的结果由主控拥有；只做 JSON 安全检查，不改变图片/视频/音频
    # 的分别存储结构，方便 native Endpoint 在 collect 阶段建立对应类型。
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("共享模型执行结果不是可持久化 JSON") from exc
    return _copy(value)


def _result_category(item: Any, bucket_category: str = "") -> str:
    """只依显式类型、MIME、已知扩展名或内联文本确认工作流结果类型。

    旧 provider 的 images 桶可能由未知类型兜底生成，因此桶名本身不能证明
    一个没有媒体元数据的 URL 是图片。
    """
    url = ""
    if isinstance(item, Mapping):
        explicit = str(item.get("kind") or item.get("mediaKind") or item.get("media_type") or item.get("type") or
                       item.get("fileType") or item.get("file_type") or item.get("mediaType") or "").lower()
        mime = str(item.get("mime_type") or item.get("mimeType") or item.get("mime") or item.get("content_type") or
                   item.get("contentType") or "").lower()
        url = str(item.get("url") or item.get("source_url") or item.get("original_url") or "")
        if explicit == "file":
            return "file"
        if explicit in {"image", "video", "audio", "text"}:
            return explicit
        type_hint = mime if "/" in mime else explicit if "/" in explicit else ""
        if type_hint:
            prefix = type_hint.split("/", 1)[0]
            if prefix in {"image", "video", "audio", "text"}:
                return prefix
        inline_text = item.get("text") or item.get("content")
        if isinstance(inline_text, str) and inline_text.strip():
            return "text"
    elif isinstance(item, str):
        url = item.strip()
        parsed = urllib.parse.urlsplit(url)
        if bucket_category == "text" and not parsed.scheme and not parsed.netloc and not url.startswith(("/", "\\")):
            return "text"
    parsed_path = urllib.parse.urlsplit(url).path.lower()
    guessed_mime = mimetypes.guess_type(parsed_path)[0] or ""
    if guessed_mime:
        prefix = guessed_mime.split("/", 1)[0]
        if prefix in {"image", "video", "audio", "text"}:
            return prefix
    if parsed_path.endswith((".srt", ".vtt", ".log", ".yaml", ".yml")):
        return "text"
    return "file"


def _validate_workflow_result(slot: str, result: Any) -> Dict[str, Any]:
    if not isinstance(result, Mapping):
        raise RuntimeError("工作流没有返回可识别的结果对象")
    if result.get("pending") or result.get("jimeng_pending"):
        return _copy(dict(result))
    target_category = {"text": "text", "image": "image", "video": "video", "audio": "audio",
                       "music": "audio", "voice": "audio"}[slot]
    normalized = _copy(dict(result))
    typed = {"image": [], "video": [], "audio": [], "text": []}
    known_buckets = {"images": "image", "videos": "video", "audios": "audio", "texts": "text"}
    for key, bucket_category in known_buckets.items():
        values = result.get(key)
        if values is None:
            continue
        if not isinstance(values, list):
            values = [values]
        for item in values:
            category = _result_category(item, bucket_category)
            if category in typed:
                typed[category].append(_copy(item))
    text_value = result.get("text")
    if isinstance(text_value, str) and text_value.strip():
        typed["text"].append({"text": text_value})
    result_files = result.get("files")
    if result_files is not None:
        if not isinstance(result_files, list):
            result_files = [result_files]
        for item in result_files:
            category = _result_category(item)
            if category in typed:
                typed[category].append(_copy(item))
    if target_category == "text":
        if not typed["text"]:
            raise RuntimeError("工作流未返回可确认的文本结果")
        text_items = typed["text"]
        value = next((item.get("text") or item.get("content") or item.get("value") for item in text_items
                      if isinstance(item, Mapping) and str(item.get("text") or item.get("content") or item.get("value") or "").strip()), "")
        if not value:
            raise RuntimeError("工作流文本结果为空")
        normalized["text"] = str(value)
    elif not typed[target_category]:
        raise RuntimeError(f"工作流未返回可确认的 {target_category} 结果")
    # 工作流所有可识别结果已由调用适配器注册到共享素材存储；Hypit 当前槽的
    # 返回值只暴露匹配类型，避免视频/封面等辅助结果冒充该槽生成结果。
    for category, values in typed.items():
        key = {"image": "images", "video": "videos", "audio": "audios", "text": "texts"}[category]
        if category == target_category and values:
            normalized[key] = values
        else:
            normalized.pop(key, None)
    normalized.pop("files", None)
    if target_category != "text":
        normalized.pop("text", None)
    return normalized


def create_hypit_models_router(
    root: str | Path,
    get_project: Callable[..., Any],
    get_capabilities: Callable[[], Mapping[str, Any]],
    validate: Callable[[Mapping[str, Any]], Awaitable[Any]],
    generate: Callable[[Mapping[str, Any]], Awaitable[Any]],
    *,
    get_workflow_options: Optional[Callable[[], Any]] = None,
    resolve_workflow: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    validate_workflow: Optional[Callable[[Mapping[str, Any], Mapping[str, Any]], Any]] = None,
    generate_workflow: Optional[Callable[[Mapping[str, Any], Mapping[str, Any]], Any]] = None,
    get_settings_canvas_projection: Optional[Callable[[], Mapping[str, Any]]] = None,
    submit_settings_canvas_request: Optional[Callable[[str, str, str, Mapping[str, Any], bool], Any]] = None,
    get_settings_canvas_request: Optional[Callable[[str], Any]] = None,
) -> APIRouter:
    """创建 Hypit 模型桥接路由。

    主控注入方式：

    ``create_hypit_models_router(BASE_DIR, STUDIO_PROJECTS.get,
    build_model_capability_catalog, validate_hypit_request, studio_generate)``，
    其中 ``validate_hypit_request`` 是主控提供的 ``async(request)`` 适配器，
    负责把已投影请求接到官方元数据和参数预检。

    工作流来源由额外的目录、解析、预检和生成回调注入；解析回调只接受稳定来源身份，
    并返回服务端当前 Schema 与执行快照。此模块不自行寻找适配器，也不保存凭据。
    后台任务集合持有 asyncio.Task 强引用，页面关闭不会取消。
    """

    root = Path(root)
    lock = RLock()
    background_tasks: Dict[str, asyncio.Task[Any]] = {}
    settings_path = root / "data" / "hypit_settings.json"
    settings_v1_backup_path = root / "backups" / "hypit" / "hypit_settings.v1.json"
    bindings_dir = root / "data" / "hypit_bindings"
    tasks_dir = root / "data" / "hypit_model_tasks"

    async def call_workflow_callback(callback: Optional[Callable[..., Any]], *args: Any) -> Any:
        if callback is None:
            raise HTTPException(status_code=503, detail="工作流来源执行适配尚未接入")
        try:
            value = callback(*args)
            return await value if inspect.isawaitable(value) else value
        except HTTPException:
            raise
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="已选工作流来源不存在") from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"读取工作流来源失败：{exc}") from exc

    async def call_settings_canvas_callback(callback: Optional[Callable[..., Any]], *args: Any) -> Any:
        if callback is None:
            raise HTTPException(status_code=503, detail="Hypit 设置流程执行适配尚未接入")
        try:
            value = callback(*args)
            return await value if inspect.isawaitable(value) else value
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Hypit 设置流程执行失败：{exc}") from exc

    def settings_record() -> Dict[str, Any]:
        if get_settings_canvas_projection is not None:
            try:
                value = get_settings_canvas_projection()
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"读取 Hypit 设置画布投影失败：{exc}") from exc
            if inspect.isawaitable(value):
                raise HTTPException(status_code=500, detail="Hypit 设置画布投影回调必须同步返回")
            if not isinstance(value, Mapping) or not isinstance(value.get("defaults"), Mapping):
                raise HTTPException(status_code=500, detail="Hypit 设置画布投影格式无效")
            public_slot_keys = {
                "selection_kind", "status", "connected", "expected_kind", "output_node_id",
                "source_node_id", "source_node_type", "node_ids", "recipe_fingerprint", "node_source",
            }
            public_source_keys = {"kind", "source", "provider_id", "model_id", "region", "item_id"}
            defaults: Dict[str, Dict[str, Any]] = {}
            for slot in _SLOTS:
                raw = value["defaults"].get(slot)
                expected_kind = _WORKFLOW_OUTPUT_KINDS[slot]
                if not isinstance(raw, Mapping):
                    defaults[slot] = {
                        "selection_kind": "settings_canvas", "status": "unconfigured", "connected": False,
                        "expected_kind": expected_kind, "output_node_id": "", "source_node_id": "",
                        "source_node_type": "", "node_ids": [], "recipe_fingerprint": "",
                    }
                    continue
                projected = {key: _copy(raw[key]) for key in public_slot_keys if key in raw}
                projected["selection_kind"] = "settings_canvas"
                projected["expected_kind"] = expected_kind
                node_source = raw.get("node_source")
                if isinstance(node_source, Mapping):
                    projected["node_source"] = {
                        key: str(node_source.get(key) or "") for key in public_source_keys if key in node_source
                    }
                else:
                    projected["node_source"] = {}
                projected.setdefault("status", "unconfigured")
                projected["connected"] = bool(projected.get("connected"))
                projected["node_ids"] = [str(item) for item in projected.get("node_ids", [])
                                          if isinstance(item, (str, int))] if isinstance(projected.get("node_ids"), list) else []
                for key in ("output_node_id", "source_node_id", "source_node_type", "recipe_fingerprint"):
                    projected[key] = str(projected.get(key) or "")
                defaults[slot] = projected
            revision = value.get("revision", 1)
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise HTTPException(status_code=500, detail="Hypit 设置画布修订号无效")
            return {
                "version": HYPIT_SETTINGS_VERSION,
                "source": "settings_canvas",
                "canvas_id": str(value.get("canvas_id") or "hypit-settings"),
                "defaults": defaults,
                "created_at": value.get("created_at"),
                "updated_at": value.get("updated_at"),
                "revision": revision,
            }
        try:
            value = read_json(settings_path, default=None)
        except Exception as exc:
            _raise_storage(exc)
        if value is None:
            return {
                "version": HYPIT_SETTINGS_VERSION,
                "defaults": _empty_defaults(),
                "created_at": None,
                "updated_at": None,
                "revision": 1,
            }
        stored_version = value.get("version", 1) if isinstance(value, Mapping) else None
        if not isinstance(value, Mapping) or isinstance(stored_version, bool) or stored_version not in {1, HYPIT_SETTINGS_VERSION}:
            raise HTTPException(status_code=500, detail="Hypit 设置版本不受支持，原文件已保留")
        defaults = _empty_defaults()
        raw_defaults = value.get("defaults") or value.get("slots") or {}
        if not isinstance(raw_defaults, Mapping):
            raise HTTPException(status_code=500, detail="Hypit 设置格式损坏，原文件已保留")
        for slot in _SLOTS:
            defaults[slot] = _normalise_slot(raw_defaults.get(slot), slot)
        revision = value.get("revision", 1)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise HTTPException(status_code=500, detail="Hypit 设置修订号损坏，原文件已保留")
        return {
            "version": HYPIT_SETTINGS_VERSION,
            "defaults": defaults,
            "created_at": value.get("created_at"),
            "updated_at": value.get("updated_at"),
            "revision": revision,
        }

    def preserve_v1_settings_before_write() -> None:
        """首次写 v2 前保存 v1 原始字节；读取不迁移，备份只创建一次。"""
        try:
            original = settings_path.read_bytes()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise HTTPException(status_code=500, detail="读取旧 Hypit 设置以创建迁移备份失败，未写入新设置") from exc
        try:
            value = json.loads(original.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail="旧 Hypit 设置损坏，原文件已保留，未写入新设置") from exc
        stored_version = value.get("version", 1) if isinstance(value, Mapping) else None
        if stored_version != 1:
            return
        try:
            settings_v1_backup_path.parent.mkdir(parents=True, exist_ok=True)
            with settings_v1_backup_path.open("xb") as backup:
                backup.write(original)
                backup.flush()
        except FileExistsError:
            # 稳定路径上的首份原件优先；后续 autosave 不生成或覆盖版本副本。
            return
        except OSError as exc:
            try:
                settings_v1_backup_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise HTTPException(status_code=500, detail="创建 Hypit v1 迁移备份失败，未写入新设置") from exc

    def catalog_record() -> Dict[str, Any]:
        try:
            value = get_capabilities()
            if inspect.isawaitable(value):
                raise RuntimeError("get_capabilities 必须是同步目录函数")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"读取模型能力目录失败：{exc}") from exc
        if not isinstance(value, Mapping) or not isinstance(value.get("providers"), list):
            raise HTTPException(status_code=500, detail="主控模型能力目录格式不正确")
        return _copy(value)

    async def workflow_descriptors() -> list[Mapping[str, Any]]:
        if get_workflow_options is None:
            return []
        value = await call_workflow_callback(get_workflow_options)
        if isinstance(value, Mapping):
            value = value.get("options")
        if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
            raise HTTPException(status_code=500, detail="工作流来源目录格式无效")
        return value

    def same_workflow_identity(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
        return all(str(left.get(key) or "") == str(right.get(key) or "") for key in ("source", "provider_id", "region", "item_id"))

    async def settings_with_workflow_availability(defaults: Mapping[str, Any]) -> Dict[str, Any]:
        result = _copy(dict(defaults))
        descriptors = await workflow_descriptors()
        for slot, value in result.items():
            if not isinstance(value, Mapping) or value.get("selection_kind") != "workflow":
                continue
            descriptor = next((item for item in descriptors if same_workflow_identity(value, item)), None)
            if descriptor is None:
                availability = {"available": False, "reason_code": "source_missing", "unavailable_reason": "已保存的工作流来源当前不可用，原选择已保留。"}
            else:
                option = _public_workflow_option(descriptor)
                if option["schema_fingerprint"] != value.get("schema_fingerprint"):
                    availability = {"available": False, "reason_code": "schema_changed", "unavailable_reason": "工作流字段 Schema 已变化，请重新检查映射。"}
                else:
                    availability = {key: option[key] for key in ("available", "reason_code", "unavailable_reason")}
            result[slot]["availability"] = availability
        return result

    async def validate_settings(defaults: Mapping[str, Any], previous: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        catalog = None
        result = _empty_defaults()
        for slot in _SLOTS:
            value = _normalise_slot(defaults.get(slot), slot)
            prior = (previous or {}).get(slot) or {}
            if previous is not None and value == prior:
                result[slot] = value
                continue
            if value["selection_kind"] == "workflow":
                selection = {key: value[key] for key in ("source", "provider_id", "region", "item_id")}
                descriptor = await call_workflow_callback(resolve_workflow, selection)
                if not isinstance(descriptor, Mapping):
                    raise HTTPException(status_code=400, detail="工作流来源返回的 Schema 格式无效")
                _check_workflow_selection(value, descriptor, slot)
            elif value["provider"] and value["model"]:
                if catalog is None:
                    catalog = catalog_record()
                profile, region = _resolve_profile(
                    catalog,
                    value["provider"],
                    value["model"],
                    _SLOT_NODE_TYPES[slot],
                    value.get("region", ""),
                )
                from studio_module_models import hypit_profile_reasons
                if hypit_profile_reasons(slot, profile):
                    raise HTTPException(400, detail="该模型不支持此 Hypit 生成用途，请重新选择模型")
                value["region"] = region
                value["parameters"] = _validate_parameters(profile, value["parameters"])
            result[slot] = value
        return result

    def binding_path(project_id: str) -> Path:
        return bindings_dir / f"{project_id}.json"

    def task_path(project_id: str, request_id: str) -> Path:
        return tasks_dir / project_id / f"{_task_key(project_id, request_id)}.json"

    def _call_project_sync(project_id: str) -> Any:
        try:
            return get_project(project_id, "hypit")
        except TypeError:
            # 允许主控传入只接收 project_id 的显式适配器；真实 StudioProjectStore
            # 仍会收到 module="hypit"，确保模块隔离不被绕过。
            try:
                return get_project(project_id)
            except TypeError:
                raise
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Hypit 项目不存在") from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"无法读取 Hypit 项目：{exc}") from exc

    async def project(project_id: str) -> Any:
        project_id = _safe_identifier(project_id, "项目 ID", _PROJECT_ID)
        return await run_in_threadpool(_call_project_sync, project_id)

    def read_binding(project_id: str) -> Dict[str, Any]:
        # binding URL 是旧客户端的兼容入口，但不再创建或读取项目级模型快照。
        # 历史 data/hypit_bindings/<project_id>.json 保留在原处，仅供追溯，不能
        # 反向决定新版运行模型。
        settings = settings_record()
        return {
            "version": HYPIT_BINDING_VERSION,
            "project_id": project_id,
            "defaults": _copy(settings["defaults"]),
            "created_at": settings.get("created_at"),
            "updated_at": settings.get("updated_at"),
            "revision": settings.get("revision", 1),
            "source": settings.get("source", "module_settings"),
            **({"canvas_id": settings["canvas_id"]} if settings.get("canvas_id") else {}),
        }

    def read_task(project_id: str, request_id: str) -> Dict[str, Any]:
        try:
            value = read_json(task_path(project_id, request_id))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Hypit 模型任务不存在") from exc
        except Exception as exc:
            _raise_storage(exc)
        if not isinstance(value, Mapping) or value.get("version") != HYPIT_TASK_VERSION:
            raise HTTPException(status_code=500, detail="Hypit 模型任务格式不受支持，原文件已保留")
        return dict(value)

    def write_task(record: Mapping[str, Any], project_id: str, request_id: str) -> None:
        try:
            write_json(task_path(project_id, request_id), dict(record))
        except Exception as exc:
            _raise_storage(exc)

    def update_task(project_id: str, request_id: str, **changes: Any) -> Dict[str, Any]:
        with lock:
            record = read_task(project_id, request_id)
            record.update(_copy(changes))
            record["updated_at"] = _now()
            write_task(record, project_id, request_id)
            return record

    def update_settings_flow_task(project_id: str, request_id: str, status: str, **changes: Any) -> Dict[str, Any]:
        """并发轮询不能用较旧的 queued 响应覆盖已完成任务。"""
        ranks = {"queued": 0, "running": 1, "recoverable": 2, "failed": 2, "succeeded": 2}
        with lock:
            current = read_task(project_id, request_id)
            current_status = str(current.get("status") or "queued")
            if current_status in {"recoverable", "failed", "succeeded"}:
                return current
            if ranks.get(status, 0) < ranks.get(current_status, 0):
                return current
            return update_task(project_id, request_id, status=status, **changes)

    def flow_task_status(value: Any) -> str:
        if not isinstance(value, Mapping):
            return "running"
        status = str(value.get("status") or "running").strip().lower()
        if status in {"queued", "pending", "accepted", "created"}:
            return "queued"
        if status in {"succeeded", "success", "completed", "done"}:
            return "succeeded"
        if status in {"failed", "error", "cancelled", "canceled"}:
            return "failed"
        if status in {"recoverable", "stale"}:
            return "recoverable"
        return "running"

    async def refresh_settings_canvas_task(project_id: str, request_id: str,
                                          record: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        current = dict(record or read_task(project_id, request_id))
        run_id = str(current.get("flow_run_id") or "")
        if not run_id:
            return current
        flow = await call_settings_canvas_callback(get_settings_canvas_request, run_id)
        if not isinstance(flow, Mapping):
            raise HTTPException(status_code=502, detail="Hypit 设置流程状态格式无效")
        state = flow_task_status(flow)
        if state in {"queued", "running"}:
            return update_settings_flow_task(project_id, request_id, state,
                                             flow_status=str(flow.get("status") or state))
        if state == "recoverable":
            return update_settings_flow_task(project_id, request_id, "recoverable",
                                             error=str(flow.get("error") or "设置流程已变化或需要人工核对；不会自动重新提交"),
                                             flow_status=str(flow.get("status") or state))
        if state == "failed":
            return update_settings_flow_task(project_id, request_id, "failed",
                                             error=str(flow.get("error") or "Hypit 设置流程执行失败"),
                                             flow_status=str(flow.get("status") or state), completed_at=_now())

        slot = str(current.get("slot") or "")
        expected_kind = _WORKFLOW_OUTPUT_KINDS.get(slot)
        actual_kind = str(flow.get("output_kind") or "").strip().lower()
        if actual_kind != expected_kind:
            return update_settings_flow_task(project_id, request_id, "failed",
                                             error=f"Hypit 设置流程返回 {actual_kind or '未知类型'}，与 {slot} 槽要求的 {expected_kind} 不一致",
                                             flow_status=str(flow.get("status") or state), completed_at=_now())
        if current.get("settings_canvas_test") is True and flow.get("current_recipe_matches") is not True:
            return update_settings_flow_task(project_id, request_id, "recoverable",
                                             error="流程配方未能与当前设置确认一致，结果保留在任务历史中；请重新检查当前流程",
                                             flow_status="stale", completed_at=_now())
        try:
            result = _validate_workflow_result(slot, flow.get("result"))
        except (RuntimeError, TypeError, ValueError) as exc:
            return update_settings_flow_task(project_id, request_id, "failed", error=str(exc),
                                             flow_status=str(flow.get("status") or state), completed_at=_now())
        return update_settings_flow_task(project_id, request_id, "succeeded", result=_normalise_result(result),
                                         flow_status=str(flow.get("status") or state), completed_at=_now())

    async def execute_task(project_id: str, request_id: str, projected: Mapping[str, Any],
                           execution_snapshot: Optional[Mapping[str, Any]] = None,
                           flow_request_id: str = "") -> None:
        try:
            update_task(project_id, request_id, status="running", started_at=_now())
            if projected.get("selection_kind") == "settings_canvas":
                submission = await call_settings_canvas_callback(
                    submit_settings_canvas_request,
                    str(projected.get("slot") or ""), "", flow_request_id,
                    _copy(projected), False,
                )
                if not isinstance(submission, Mapping) or not str(submission.get("run_id") or "").strip():
                    raise RuntimeError("Hypit 设置流程没有返回可查询的 run_id")
                run_id = str(submission["run_id"])
                update_task(project_id, request_id, flow_run_id=run_id,
                            flow_status=str(submission.get("status") or "queued"), status="running")
                state = flow_task_status(submission)
                if state in {"succeeded", "failed", "recoverable"}:
                    await refresh_settings_canvas_task(project_id, request_id)
                    return
                # 只查询这一次已创建的流程任务，不在超时或服务重启后重新提交。
                while True:
                    await asyncio.sleep(0.15)
                    current = await refresh_settings_canvas_task(project_id, request_id)
                    if current.get("status") not in {"queued", "running"}:
                        return
            elif projected.get("selection_kind") == "workflow":
                if not isinstance(execution_snapshot, Mapping):
                    raise RuntimeError("工作流任务缺少执行快照")
                validation = await call_workflow_callback(validate_workflow, _copy(projected), _copy(execution_snapshot))
            else:
                validation = await validate(_copy(projected))
            update_task(project_id, request_id, validation=_normalise_result(validation))
            if projected.get("selection_kind") == "workflow":
                result = await call_workflow_callback(generate_workflow, _copy(projected), _copy(execution_snapshot or {}))
                result = _validate_workflow_result(str(projected.get("expected_slot") or ""), result)
            else:
                result = await generate(_copy(projected))
            if isinstance(result, Mapping) and (result.get('pending') or result.get('jimeng_pending')):
                update_task(project_id, request_id, status='recoverable', result=_normalise_result(result),
                            error='上游任务未完成，请按原任务 ID 查询；不会自动重新提交')
                return
            update_task(
                project_id,
                request_id,
                status="succeeded",
                result=_normalise_result(result),
                completed_at=_now(),
            )
        except asyncio.CancelledError:
            # 主控不应取消工作台任务；若应用关闭导致取消，留下 running 记录，
            # 重启后不会静默重发，也不会把一次付费请求伪装成失败重试。
            raise
        except Exception as exc:
            message = str(getattr(exc, "detail", None) or exc)
            try:
                update_task(project_id, request_id, status="failed", error=message, completed_at=_now())
            except Exception:
                # 原始任务记录已在排队前落盘；写回失败时不以空记录覆盖它。
                pass

    async def local(request: Request) -> None:
        host = request.client.host if request.client else ""
        if not await run_in_threadpool(is_local_client, host):
            raise HTTPException(status_code=403, detail="请在工作台服务所在电脑操作")
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(status_code=403, detail="不允许跨站操作")

    router = APIRouter(prefix="/api/studio/hypit/models", tags=["Hypit Models"], dependencies=[Depends(local)])

    @router.get("/capabilities")
    async def capabilities() -> Dict[str, Any]:
        catalog = catalog_record()
        settings = settings_record()
        from studio_module_models import hypit_profile_reasons, select_options_for_slot
        supported = []
        for item in SUPPORTED_HYPIT_CAPABILITIES:
            models = []
            for provider in catalog.get("providers") or []:
                if not isinstance(provider, Mapping):
                    continue
                provider_id = _provider_id(provider)
                for model in _provider_models(provider):
                    if model.get("node_type") != item["node_type"]:
                        continue
                    if hypit_profile_reasons(item['slot'], model):
                        continue
                    models.append(
                        {
                            "provider_id": provider_id,
                            "provider_name": provider.get("name") or provider_id,
                            "model_id": _model_id(model),
                            "family_id": model.get("family_id"),
                            "variant_id": model.get("variant_id"),
                            "display_name": model.get("display_name") or _model_id(model),
                            "readiness": model.get("readiness"),
                            "runnable": model.get("runnable"),
                            "validation_mode": model.get("validation_mode"),
                            "region": model.get("region") or "",
                            "regions": _copy(model.get("regions") or []),
                            "region_profiles": _copy(model.get("region_profiles") or {}),
                            "parameters": _copy(model.get("parameters") or {}),
                            "inputs": _copy(model.get("inputs") or {}),
                        }
                    )
            supported.append({**_copy(item), "models": models})
        return {
            **catalog,
            "hypit_module": _copy(_CAPABILITY_MODULE),
            "supported_capabilities": supported,
            "unsupported_capabilities": _copy(list(UNSUPPORTED_HYPIT_CAPABILITIES)),
            "defaults": settings["defaults"],
            "settings_source": settings.get("source", "module_settings"),
            "settings_canvas_id": settings.get("canvas_id"),
            "settings_revision": settings.get("revision", 1),
            "slot_options": {item['slot']: select_options_for_slot(catalog.get('options') or [], 'hypit', item['slot'])['options']
                             for item in SUPPORTED_HYPIT_CAPABILITIES} if 'options' in catalog else None,
        }

    @router.get("/settings")
    async def get_settings() -> Dict[str, Any]:
        record = settings_record()
        if get_settings_canvas_projection is None:
            record["defaults"] = await settings_with_workflow_availability(record["defaults"])
        return record

    @router.get("/workflow-options")
    async def workflow_options(slot: str = "") -> Dict[str, Any]:
        if slot and slot not in _SLOTS:
            raise HTTPException(status_code=400, detail="Hypit 工作流目标槽位不受支持")
        descriptors = await workflow_descriptors()
        public = [_public_workflow_option(item) for item in descriptors]
        available = [item for item in public if item["available"]]
        unavailable = [item for item in public if not item["available"]]
        selected = None
        if slot:
            chosen = settings_record()["defaults"].get(slot) or {}
            if get_settings_canvas_projection is not None:
                source_identity = chosen.get("node_source") if isinstance(chosen.get("node_source"), Mapping) else {}
                source = str(source_identity.get("source") or source_identity.get("kind") or "")
                if source in _WORKFLOW_SOURCES:
                    chosen = {
                        "selection_kind": "workflow", "source": source,
                        "provider_id": source_identity.get("provider_id") or _WORKFLOW_SOURCES[source],
                        "region": source_identity.get("region") or "",
                        "item_id": source_identity.get("item_id") or "",
                        "schema_fingerprint": source_identity.get("schema_fingerprint") or "",
                    }
                else:
                    chosen = {}
            if chosen.get("selection_kind") == "workflow":
                selected = next((item for item in public if same_workflow_identity(chosen, item)), None)
                if selected is None:
                    selected = {
                        "source": chosen.get("source"), "provider_id": chosen.get("provider_id"),
                        "region": chosen.get("region"), "item_id": chosen.get("item_id"),
                        "enabled": False, "available": False, "schema_status": "missing",
                        "schema_fingerprint": chosen.get("schema_fingerprint", ""), "fields": [],
                        "reason_code": "source_missing", "unavailable_reason": "已保存的工作流来源当前不可用，原选择已保留。",
                    }
        return {
            "slot": slot or None,
            "expected_kind": _WORKFLOW_OUTPUT_KINDS.get(slot) if slot else None,
            "options": available,
            "unavailable": unavailable,
            "selected": selected,
        }

    @router.put("/settings")
    @router.post("/settings")
    async def save_settings(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
        if get_settings_canvas_projection is not None:
            raise HTTPException(status_code=410, detail="Hypit 模型设置已统一到 Hypit 设置画布，请在画布中编辑各用途流程")
        with lock:
            current = settings_record()
            expected_revision = payload.get("expected_revision") if isinstance(payload, Mapping) else None
            if expected_revision is not None and (isinstance(expected_revision, bool) or expected_revision != current.get("revision", 1)):
                raise HTTPException(409, detail="Hypit 模块模型设置已更新，请重新读取")
            raw_defaults = payload.get("defaults") if isinstance(payload, Mapping) else None
            if raw_defaults is None and isinstance(payload, Mapping):
                raw_defaults = payload.get("slots")
            if raw_defaults is None:
                raw_defaults = {key: value for key, value in payload.items()
                                if key not in {"expected_revision", "revision", "version"}}
            if not isinstance(raw_defaults, Mapping):
                raise HTTPException(status_code=400, detail="Hypit 默认模型必须是对象")
            merged = _copy(current["defaults"])
            for key, value in raw_defaults.items():
                if key not in _SLOTS:
                    raise HTTPException(status_code=400, detail=f"不支持的 Hypit 模型槽位：{key}")
                merged[key] = _normalise_slot(value, key)
            if payload.get('parameter_mode') == 'per_request':
                for value in merged.values():
                    value['parameters'] = {}
            defaults = await validate_settings(merged, current['defaults'])
            now = _now()
            record = {
                "version": HYPIT_SETTINGS_VERSION,
                "defaults": defaults,
                "created_at": current.get("created_at") or now,
                "updated_at": now,
                "revision": current.get("revision", 1) + 1,
            }
            try:
                preserve_v1_settings_before_write()
                write_json(settings_path, record)
            except Exception as exc:
                _raise_storage(exc)
            return record

    @router.get("/projects/{project_id}/binding")
    async def get_binding(project_id: str) -> Dict[str, Any]:
        await project(project_id)
        with lock:
            return read_binding(_safe_identifier(project_id, "项目 ID", _PROJECT_ID))

    @router.post("/projects/{project_id}/binding")
    async def create_binding(project_id: str) -> Dict[str, Any]:
        await project(project_id)
        with lock:
            return read_binding(_safe_identifier(project_id, "项目 ID", _PROJECT_ID))

    @router.put("/projects/{project_id}/binding")
    async def update_binding(project_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        if get_settings_canvas_projection is not None:
            raise HTTPException(status_code=410, detail="Hypit 项目模型绑定已统一到 Hypit 设置画布，不能另存独立模型绑定")
        await project(project_id)
        project_id = _safe_identifier(project_id, "项目 ID", _PROJECT_ID)
        _reject_secrets(payload)
        with lock:
            current = read_binding(project_id)
            expected_revision = payload.get("expected_revision")
            if isinstance(expected_revision, bool) or expected_revision != current.get("revision", 1):
                raise HTTPException(409, detail="Hypit 模块模型设置已更新，请重新读取")
            defaults = payload.get("defaults")
            if not isinstance(defaults, Mapping) or set(defaults) - set(_SLOTS):
                raise HTTPException(400, detail="Hypit 模块模型设置无效")
            settings = settings_record()
            merged = _copy(settings["defaults"])
            for key, value in defaults.items():
                merged[key] = _normalise_slot(value, key)
            validated = await validate_settings(merged)
            now = _now()
            updated_settings = {
                "version": HYPIT_SETTINGS_VERSION,
                "defaults": validated,
                "created_at": settings.get("created_at") or now,
                "updated_at": now,
                "revision": settings.get("revision", 1) + 1,
            }
            try:
                preserve_v1_settings_before_write()
                write_json(settings_path, updated_settings)
            except Exception as exc:
                _raise_storage(exc)
            return {
                "version": HYPIT_BINDING_VERSION,
                "project_id": project_id,
                "defaults": _copy(validated),
                "created_at": updated_settings["created_at"],
                "updated_at": updated_settings["updated_at"],
                "revision": updated_settings["revision"],
                "source": "module_settings",
            }

    @router.post("/projects/{project_id}/requests")
    async def submit_request(project_id: str, payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
        project_id = _safe_identifier(project_id, "项目 ID", _PROJECT_ID)
        await project(project_id)
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=400, detail="Hypit 请求必须是对象")
        _reject_secrets(payload)
        request_id = _safe_identifier(payload.get("request_id"), "request_id", _REQUEST_ID)
        input_fingerprint = _request_fingerprint(payload)
        target = task_path(project_id, request_id)
        # 先按调用方输入查已有任务。这样模块设置变化、当前模型下线或目录
        # 刷新都不会把同一个 request_id 重新投影成另一条收费任务。
        with lock:
            if target.exists():
                existing = read_task(project_id, request_id)
                existing_fingerprint = existing.get("input_fingerprint") or existing.get("fingerprint")
                if existing_fingerprint != input_fingerprint:
                    raise HTTPException(status_code=409, detail="相同 request_id 不能用于不同输入")
                return _public_task(existing)
        constraints = payload.get("constraints") if isinstance(payload.get("constraints"), Mapping) else payload
        if isinstance(constraints, Mapping):
            nested = constraints.get("studio_request") or constraints.get("request")
            if isinstance(nested, Mapping):
                constraints = nested
        capability_kind = _capability_kind(payload.get("capability"))
        requested_kind = str((constraints or {}).get("kind") or payload.get("kind") or capability_kind or "").strip().lower()
        if requested_kind == "speech":
            requested_kind = "audio"
        capability = _capability_by_kind(requested_kind)
        if capability is None:
            raise HTTPException(status_code=400, detail="Hypit 只支持已声明的文本、图片、视频、语音和音乐能力")
        slot = str((constraints or {}).get("slot") or capability["slot"])
        if slot not in _SLOTS:
            raise HTTPException(status_code=400, detail="Hypit 模型槽位不受支持")
        flow_request_id = ""
        execution_snapshot = None
        if submit_settings_canvas_request is not None:
            projected = _project_settings_canvas_request(payload, slot)
            flow_request_id = "native_" + hashlib.sha256(f"{project_id}\0{request_id}".encode("utf-8")).hexdigest()
        else:
            with lock:
                binding = read_binding(project_id)
            selected = binding.get("defaults", {}).get(slot) or _normalise_slot(None, slot)
            if selected.get("selection_kind") == "workflow":
                selection = {key: selected[key] for key in ("source", "provider_id", "region", "item_id")}
                descriptor = await call_workflow_callback(resolve_workflow, selection)
                if not isinstance(descriptor, Mapping):
                    raise HTTPException(status_code=400, detail="工作流来源返回的 Schema 格式无效")
                execution_snapshot = _check_workflow_selection(selected, descriptor, slot)
                projected = _project_workflow_constraints(payload, selected, slot, execution_snapshot)
            else:
                projected = _project_constraints(payload, binding, catalog_record())
        with lock:
            if target.exists():
                existing = read_task(project_id, request_id)
                existing_fingerprint = existing.get("input_fingerprint") or existing.get("fingerprint")
                if existing_fingerprint != input_fingerprint:
                    raise HTTPException(status_code=409, detail="相同 request_id 不能用于不同输入")
                return _public_task(existing)
            record: Dict[str, Any] = {
                "version": HYPIT_TASK_VERSION,
                "task_id": f"hypit_{_task_key(project_id, request_id)[:32]}",
                "project_id": project_id,
                "request_id": request_id,
                "fingerprint": input_fingerprint,
                "input_fingerprint": input_fingerprint,
                "status": "queued",
                "request": projected,
                **({"slot": slot, "settings_canvas_request_id": flow_request_id}
                   if projected.get("selection_kind") == "settings_canvas" else {}),
                **({"execution_snapshot": _copy(execution_snapshot)} if execution_snapshot is not None else {}),
                "created_at": _now(),
                "updated_at": _now(),
            }
            write_task(record, project_id, request_id)
            task = asyncio.create_task(execute_task(project_id, request_id, projected, execution_snapshot, flow_request_id))
            task_key = f"{project_id}\0{request_id}"
            background_tasks[task_key] = task

            def discard(done: asyncio.Task[Any], key: str = task_key) -> None:
                # 只移除内存强引用；任务记录仍永久保留，防止重复请求再次执行。
                background_tasks.pop(key, None)

            task.add_done_callback(discard)
        return _public_task(record)

    @router.get("/projects/{project_id}/requests/{request_id}")
    async def request_status(project_id: str, request_id: str) -> Dict[str, Any]:
        project_id = _safe_identifier(project_id, "项目 ID", _PROJECT_ID)
        request_id = _safe_identifier(request_id, "request_id", _REQUEST_ID)
        await project(project_id)
        with lock:
            record = read_task(project_id, request_id)
            if record.get("request", {}).get("selection_kind") == "settings_canvas" and record.get("flow_run_id"):
                pass
            elif record.get('status') in {'queued', 'running'} and f'{project_id}\0{request_id}' not in background_tasks:
                record = update_task(project_id, request_id, status='recoverable', error='服务重启，原任务状态需核对；不会自动重新提交')
        if record.get("request", {}).get("selection_kind") == "settings_canvas" and record.get("flow_run_id"):
            record = await refresh_settings_canvas_task(project_id, request_id, record)
        with lock:
            record = read_task(project_id, request_id)
            return _public_task(record)

    return router


__all__ = [
    "SUPPORTED_HYPIT_CAPABILITIES",
    "UNSUPPORTED_HYPIT_CAPABILITIES",
    "create_hypit_models_router",
]
