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
import re
import time
from pathlib import Path
from threading import RLock
from typing import Any, Awaitable, Callable, Dict, Iterable, Mapping, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from canvas_agent import is_local_client
from canvas_core.json_store import DataFileError, read_json, write_json


HYPIT_SETTINGS_VERSION = 1
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
            "zh": "AI 应用的输入输出契约尚未在本桥接中确认。",
            "en": "The AI application input/output contract is not confirmed by this bridge.",
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
    "secret",
    "token",
    "password",
    "authorization",
}


def _now() -> float:
    return time.time()


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _empty_defaults() -> Dict[str, Dict[str, Any]]:
    return {slot: {"provider": "", "model": "", "region": "", "parameters": {}} for slot in _SLOTS}


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
        if key_text.lower() in _SECRET_KEYS:
            raise HTTPException(status_code=400, detail="模型参数不能包含 API Key 或凭据")
        if schema and key_text not in schema:
            raise HTTPException(status_code=400, detail=f"参数 {key_text} 不属于模型已确认参数")
        if key_text in schema and isinstance(schema[key_text], Mapping):
            _check_scalar_type(key_text, value, schema[key_text])
    return result


def _reject_secrets(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                raise HTTPException(status_code=400, detail="Hypit 设置不能保存 API Key 或凭据")
            _reject_secrets(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secrets(item)


def _normalise_slot(raw: Any, slot: str) -> Dict[str, Any]:
    if raw is None:
        return {"provider": "", "model": "", "region": "", "parameters": {}}
    if not isinstance(raw, Mapping):
        raise HTTPException(status_code=400, detail=f"{slot} 默认模型格式不正确")
    _reject_secrets(raw)
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
    return {"provider": provider, "model": model, "region": region, "parameters": dict(parameters)}


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


def _task_key(project_id: str, request_id: str) -> str:
    return hashlib.sha256(f"{project_id}\0{request_id}".encode("utf-8")).hexdigest()


def _request_fingerprint(payload: Mapping[str, Any]) -> str:
    """只根据调用方输入做幂等判断，不把模块默认模型算进输入。"""
    value = _copy(dict(payload))
    value.pop("request_id", None)
    return _hash({"input": value})


def _public_task(record: Mapping[str, Any]) -> Dict[str, Any]:
    return _copy(record)


def _normalise_result(value: Any) -> Any:
    # 回调返回的结果由主控拥有；只做 JSON 安全检查，不改变图片/视频/音频
    # 的分别存储结构，方便 native Endpoint 在 collect 阶段建立对应类型。
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("共享模型执行结果不是可持久化 JSON") from exc
    return _copy(value)


def create_hypit_models_router(
    root: str | Path,
    get_project: Callable[..., Any],
    get_capabilities: Callable[[], Mapping[str, Any]],
    validate: Callable[[Mapping[str, Any]], Awaitable[Any]],
    generate: Callable[[Mapping[str, Any]], Awaitable[Any]],
) -> APIRouter:
    """创建 Hypit 模型桥接路由。

    主控注入方式：

    ``create_hypit_models_router(BASE_DIR, STUDIO_PROJECTS.get,
    build_model_capability_catalog, validate_hypit_request, studio_generate)``，
    其中 ``validate_hypit_request`` 是主控提供的 ``async(request)`` 适配器，
    负责把已投影请求接到官方元数据和参数预检。

    ``validate`` 和 ``generate`` 必须是 async 回调；本模块不自行寻找适配器，
    也不保存凭据。后台任务集合持有 asyncio.Task 强引用，页面关闭不会取消。
    """

    root = Path(root)
    lock = RLock()
    background_tasks: Dict[str, asyncio.Task[Any]] = {}
    settings_path = root / "data" / "hypit_settings.json"
    bindings_dir = root / "data" / "hypit_bindings"
    tasks_dir = root / "data" / "hypit_model_tasks"

    def settings_record() -> Dict[str, Any]:
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
        if not isinstance(value, Mapping) or value.get("version", HYPIT_SETTINGS_VERSION) != HYPIT_SETTINGS_VERSION:
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

    def validate_settings(defaults: Mapping[str, Any], previous: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        catalog = catalog_record()
        result = _empty_defaults()
        for slot in _SLOTS:
            value = _normalise_slot(defaults.get(slot), slot)
            prior = (previous or {}).get(slot) or {}
            if previous is not None and all(value.get(k) == prior.get(k) for k in ('provider', 'model', 'region')):
                result[slot] = value
                continue
            if value["provider"] and value["model"]:
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
            "source": "module_settings",
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

    async def execute_task(project_id: str, request_id: str, projected: Mapping[str, Any]) -> None:
        try:
            update_task(project_id, request_id, status="running", started_at=_now())
            validation = await validate(_copy(projected))
            update_task(project_id, request_id, validation=_normalise_result(validation))
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
            "defaults": settings_record()["defaults"],
            "slot_options": {item['slot']: select_options_for_slot(catalog.get('options') or [], 'hypit', item['slot'])['options']
                             for item in SUPPORTED_HYPIT_CAPABILITIES} if 'options' in catalog else None,
        }

    @router.get("/settings")
    async def get_settings() -> Dict[str, Any]:
        return settings_record()

    @router.put("/settings")
    @router.post("/settings")
    async def save_settings(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
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
            defaults = validate_settings(merged, current['defaults'])
            now = _now()
            record = {
                "version": HYPIT_SETTINGS_VERSION,
                "defaults": defaults,
                "created_at": current.get("created_at") or now,
                "updated_at": now,
                "revision": current.get("revision", 1) + 1,
            }
            try:
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
            validated = validate_settings(merged)
            now = _now()
            updated_settings = {
                "version": HYPIT_SETTINGS_VERSION,
                "defaults": validated,
                "created_at": settings.get("created_at") or now,
                "updated_at": now,
                "revision": settings.get("revision", 1) + 1,
            }
            try:
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
        with lock:
            binding = read_binding(project_id)
        catalog = catalog_record()
        projected = _project_constraints(payload, binding, catalog)
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
                "created_at": _now(),
                "updated_at": _now(),
            }
            write_task(record, project_id, request_id)
            task = asyncio.create_task(execute_task(project_id, request_id, projected))
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
            if record.get('status') in {'queued', 'running'} and f'{project_id}\0{request_id}' not in background_tasks:
                record = update_task(project_id, request_id, status='recoverable', error='服务重启，原任务状态需核对；不会自动重新提交')
            return _public_task(record)

    return router


__all__ = [
    "SUPPORTED_HYPIT_CAPABILITIES",
    "UNSUPPORTED_HYPIT_CAPABILITIES",
    "create_hypit_models_router",
]
