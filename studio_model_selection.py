"""统一模型选择投影服务（P2）。

依据：《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§8、§11.3、§16 P2。

职责：
    1. 身份索引：把各平台的局部 family_id 归并到 canonical_family_id；
       没有映射证据的条目保留 provider-local 身份（§8.1、§19.4）。
    2. ExecutionOption：区分 model ID / endpoint / operation / 连接 / 站点，
       并给出与显示名、语言无关的稳定 option_id（§8.3）。
    3. 唯一性与冲突校验、显示标签生成、原始 ID 追踪、schema 版本。

约束：
- 只使用机器标识计算身份；显示名（中英文）不参与 option_id（§8.3、A11）。
- option_id 用稳定 JSON 编码后哈希，不用 `::` 拼接，避免碰撞（§8.3）。
- 原始模型 ID 大小写原样保留，不做规范化（§8.3）。
- 本模块纯函数为主，不读密钥、不发网络请求、不提交生成任务（§11.3）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = 2
IDENTITY_SCHEMA_VERSION = 1
PROVIDER_LOCAL_PREFIX = "provider-local"

# 版本与档次只从 ID 字面提取（可追溯的文本证据），不从名称猜测含义。
_VERSION_PATTERN = (
    r"(?<![0-9.])((?:v)?\d+(?:\.\d+)?)(?![0-9])",
)
_EDITION_TOKENS = ("fast", "mini", "pro", "standard", "turbo", "lite", "flash", "plus", "max")

# 明确、可复核的跨平台产品系列映射（§3.3 与 §4.2/§4.3 授权的聚合范围）。
# 每条规则必须给出 source_ref；未列出的模型一律保留 provider-local 身份。
IDENTITY_RULES: List[Dict[str, Any]] = [
    {"family": "seedance", "label": {"zh": "Seedance", "en": "Seedance"}, "tokens": ["seedance"], "node_types": ["video_generation"], "source_ref": "§3.3 已确认属于 Seedance 的各平台条目"},
    {"family": "series-video-minimax", "label": {"zh": "MiniMax", "en": "MiniMax"}, "tokens": ["hailuo", "minimax"], "node_types": ["video_generation"], "source_ref": "§3.3 MiniMax/Hailuo/H3 同一模型家族，版本与生成方式由运行模式区分"},
    {"family": "kling", "label": {"zh": "Kling", "en": "Kling"}, "tokens": ["kling"], "node_types": ["video_generation"], "source_ref": "§3.3 Kling 系列"},
    {"family": "vidu", "label": {"zh": "Vidu", "en": "Vidu"}, "tokens": ["vidu"], "node_types": ["video_generation"], "source_ref": "§3.3 Vidu 系列"},
    {"family": "wan-video", "label": {"zh": "Wan", "en": "Wan"}, "tokens": ["wan", "wan2", "wan-2", "wanx"], "node_types": ["video_generation"], "source_ref": "视频模型 ID 中的 Wan/万相统一归入 Wan 家族"},
    {"family": "series-video-sora", "label": {"zh": "Sora", "en": "Sora"}, "tokens": ["sora", "全能视频s", "omni-video-s"], "node_types": ["video_generation"], "source_ref": "全能视频 S 的模型 ID 与 Sora 系列映射"},
    {"family": "series-image-seedream", "label": {"zh": "Seedream", "en": "Seedream"}, "tokens": ["seedream", "jimeng-image", "bytedance/jimeng"], "node_types": ["image_generation"], "source_ref": "§4.2 图片生成/编辑清单；即梦图片归属 Seedream"},
    {"family": "qwen-image", "label": {"zh": "Qwen Image", "en": "Qwen Image"}, "tokens": ["qwen-image", "qwen/qwen-image"], "node_types": ["image_generation"], "source_ref": "§4.2 图片生成/编辑清单"},
    {"family": "series-text-qwen", "label": {"zh": "Qwen", "en": "Qwen"}, "tokens": ["qwen3", "qwen/qwen3", "qwen2.5", "qwen-max", "qwen-plus"], "node_types": ["text_generation"], "source_ref": "§4.2 文本清单"},
    {"family": "series-text-deepseek", "label": {"zh": "DeepSeek", "en": "DeepSeek"}, "tokens": ["deepseek"], "node_types": ["text_generation"], "source_ref": "§4.2 文本清单"},
    {"family": "series-text-glm", "label": {"zh": "GLM", "en": "GLM"}, "tokens": ["glm"], "node_types": ["text_generation"], "source_ref": "§4.2 文本清单"},
    {"family": "series-text-kimi", "label": {"zh": "Kimi", "en": "Kimi"}, "tokens": ["kimi", "moonshot"], "node_types": ["text_generation"], "source_ref": "§4.2 文本清单"},
    {"family": "series-text-gpt", "label": {"zh": "GPT", "en": "GPT"}, "tokens": ["openai/gpt", "gpt-", "gpt/", "laohu/g5", "laohu/g6"], "node_types": ["text_generation"], "source_ref": "真实模型 ID 的 GPT 系列规则；g5/g6 为平台缩写"},
    {"family": "series-text-grok", "label": {"zh": "Grok", "en": "Grok"}, "tokens": ["grok", "laohu/gk-"], "node_types": ["text_generation"], "source_ref": "真实模型 ID 的 Grok 系列规则；gk 为平台缩写"},
    {"family": "series-text-gemini", "label": {"zh": "Gemini", "en": "Gemini"}, "tokens": ["gemini", "laohu/gm-"], "node_types": ["text_generation"], "source_ref": "真实模型 ID 的 Gemini 系列规则；gm 为平台缩写"},
    {"family": "series-text-minimax", "label": {"zh": "MiniMax", "en": "MiniMax"}, "tokens": ["minimax", "minmax"], "node_types": ["text_generation"], "source_ref": "真实模型 ID 的 MiniMax 系列规则"},
    {"family": "series-text-doubao-seed", "label": {"zh": "豆包", "en": "Doubao"}, "tokens": ["doubao-seed", "bytedance/doubao"], "node_types": ["text_generation"], "source_ref": "真实模型 ID 的豆包系列规则"},
    {"family": "minimax-music", "label": {"zh": "MiniMax Music", "en": "MiniMax Music"}, "tokens": ["minimax/music", "music-2", "music-cover"], "node_types": ["music_generation"], "source_ref": "§4.2 音乐清单"},
    {"family": "minimax-speech", "label": {"zh": "MiniMax 语音", "en": "MiniMax Speech"}, "tokens": ["minimax/voice", "minimax/speech", "speech-2"], "node_types": ["audio_generation"], "source_ref": "§4.2 语音/音频清单"},
]

# 这些前缀本身标识产品系列。旧 family_id 可能来自错误的目录标签，
# 因此识别时只看真实模型 ID，不能让 "海螺" 等标签覆盖 Grok ID。
MODEL_ID_RULES: List[Dict[str, Any]] = [
    {"family": "series-image-seedream", "label": {"zh": "Seedream", "en": "Seedream"}, "tokens": ["/jimeng-", "dreamina-"], "node_types": ["image_generation"]},
    {"family": "series-image-nano-banana", "label": {"zh": "Nano Banana", "en": "Nano Banana"}, "tokens": ["nano-banana", "nanobanana"], "node_types": ["image_generation"]},
    {"family": "series-image-gpt-image", "label": {"zh": "GPT Image", "en": "GPT Image"}, "model_ids": [
        "laohu-image-g-v2-lowprice",
        "laohu-image-g-v2.5-flare",
        "laohu-image-g-v2.5-lowprice",
        "laohu-image-g-v2.5-sunburst",
        "laohu-image-g2-i2i",
        "laohu-image-g2-t2i",
    ], "node_types": ["image_generation"], "source_ref": "现有 laohu 静态与动态能力档案为这些精确 ID 建立 GPT Image 输入/用途映射；未据 g 前缀外推"},
    {"family": "series-image-grok-image", "label": {"zh": "Grok Image", "en": "Grok Image"}, "tokens": ["grok-image", "grok-imagine-image", "grok-3-image", "grok-4-image", "laohu-image-gk-"], "node_types": ["image_generation"]},
    {"family": "series-image-midjourney", "label": {"zh": "Midjourney", "en": "Midjourney"}, "tokens": ["midjourney"], "node_types": ["image_generation"]},
    {"family": "series-image-qwen-image", "label": {"zh": "Qwen Image", "en": "Qwen Image"}, "tokens": ["qwen-image", "qwen/image"], "node_types": ["image_generation"]},
    {"family": "series-image-seedream", "label": {"zh": "Seedream", "en": "Seedream"}, "tokens": ["seedream"], "node_types": ["image_generation"]},
    {"family": "series-video-grok", "label": {"zh": "Grok", "en": "Grok"}, "tokens": ["grok-imagine", "grok-video"], "node_types": ["video_generation"]},
    {"family": "series-video-grok", "label": {"zh": "Grok", "en": "Grok"}, "tokens": ["laohu-video-gk", "video-grok"], "node_types": ["video_generation"]},
    {"family": "series-video-sora", "label": {"zh": "Sora", "en": "Sora"}, "tokens": ["sora", "omni-video-s"], "node_types": ["video_generation"]},
    {"family": "series-video-minimax", "label": {"zh": "MiniMax", "en": "MiniMax"}, "tokens": ["hailuo", "minimax-h3"], "node_types": ["video_generation"]},
    {"family": "series-video-happyhorse", "label": {"zh": "HappyHorse", "en": "HappyHorse"}, "tokens": ["happyhorse", "happy-horse"], "node_types": ["video_generation"]},
    {"family": "series-music-suno", "label": {"zh": "Suno", "en": "Suno"}, "tokens": ["suno"], "node_types": ["music_generation"]},
]


def _norm(value: Any) -> str:
    return str(value or "").strip()


def provider_local_family(adapter: str, family_id: str, model_id: str) -> str:
    """未经映射的模型保留 provider-local 临时系列身份（§8.1）。"""
    anchor = _norm(family_id) or _norm(model_id) or "unknown"
    return f"{PROVIDER_LOCAL_PREFIX}:{_norm(adapter) or 'unknown'}:{anchor}"


def match_identity_rule(
    *, capability_provider_id: str, model_id: str, family_id: str, node_type: str
) -> Optional[Dict[str, Any]]:
    """按显式规则表匹配产品系列；未命中返回 None（保持 provider-local）。"""
    import re

    model_text = _norm(model_id).lower()
    if node_type == "text_generation":
        # 部分中转平台用单字母缩写表示系列：g5/g6=GPT，gk=Grok，gm=Gemini。
        # 只在文本能力档案中解释这些缩写，避免影响图片/视频模型。
        alias_text = model_text
        text_aliases = (
            (r"(^|[/_.-])gk(?:[/_.-]|$)|grok", "series-text-grok", {"zh": "Grok", "en": "Grok"}, "文本模型 ID 的 gk/Grok 缩写"),
            (r"(^|[/_.-])gm(?:[/_.-]|$)|gemini", "series-text-gemini", {"zh": "Gemini", "en": "Gemini"}, "文本模型 ID 的 gm/Gemini 缩写"),
            (r"(^|[/_.-])g(?:5|6)(?:[/_.-]|$)|(^|[/_.-])gpt(?:[/_.-]|$)|openai[/_.-]gpt", "series-text-gpt", {"zh": "GPT", "en": "GPT"}, "文本模型 ID 的 g5/g6/GPT 缩写"),
        )
        for pattern, family, label, source_ref in text_aliases:
            if re.search(pattern, alias_text, re.I):
                return {"family": family, "label": label, "tokens": [], "node_types": ["text_generation"], "source_ref": source_ref}
    for rule in MODEL_ID_RULES:
        exact_model_ids = {str(value).lower() for value in rule.get("model_ids") or []}
        token_match = any(token in model_text for token in rule.get("tokens") or [])
        if node_type in rule["node_types"] and (model_text in exact_model_ids or token_match):
            return {**rule, "source_ref": rule.get("source_ref") or "真实模型 ID 的已确认产品系列"}
    if capability_provider_id == "jimeng-cli" and node_type == "image_generation" and model_text in {
        "3.0", "3.1", "4.0", "4.1", "4.5", "4.6", "4.7", "5.0", "5.0pro"
    }:
        return {"family": "series-image-seedream", "label": {"zh": "Seedream", "en": "Seedream"},
                "tokens": [model_text], "source_ref": "即梦 CLI 图片模型 ID 与平台契约"}
    haystack = f"{model_text} {_norm(family_id)}".lower()
    for rule in IDENTITY_RULES:
        if rule["node_types"] and node_type not in rule["node_types"]:
            continue
        for token in rule["tokens"]:
            if token in haystack:
                return rule
    return None


def extract_version(model_id: str) -> Tuple[str, str]:
    """从 ID 字面提取版本与档次，并标注提取来源，不做语义猜测。"""
    import re

    text = _norm(model_id).lower()
    version = ""
    match = re.search(_VERSION_PATTERN[0], text)
    if match:
        candidate = match.group(1)
        # 纯数字且形如 1 位的年代/型号不作为产品版本，避免把 "h3" 之类误判
        if "." in candidate or candidate.startswith("v"):
            version = candidate.lstrip("v")
    edition = ""
    for token in _EDITION_TOKENS:
        if token in text:
            edition = token
            break
    return version, edition


def resolve_identity(
    *, capability_provider_id: str, adapter_id: str, model_id: str, family_id: str, node_type: str,
    identity_document: Optional[Dict[str, Any]] = None, operation: str = ""
) -> Dict[str, Any]:
    """解析单条记录的规范化身份。"""
    id_rule = match_identity_rule(
        capability_provider_id=capability_provider_id, model_id=model_id,
        family_id="", node_type=node_type,
    )
    identity_bindings = (identity_document or {}).get("bindings") or []
    identity_bindings = sorted(identity_bindings, key=lambda binding: bool((binding.get("match") or {}).get("operation")), reverse=True)
    for binding in identity_bindings:
        match = binding.get("match") or {}
        if (
            _norm(match.get("capability_provider_id")) == _norm(capability_provider_id)
            and _norm(match.get("model_id")) == _norm(model_id)
            and _norm(match.get("node_type")) == _norm(node_type)
            and (not _norm(match.get("operation")) or _norm(match.get("operation")) == _norm(operation))
        ):
            families = {
                _norm(item.get("id")): item.get("label") or {}
                for item in (identity_document or {}).get("families") or []
            }
            family_key = _norm(binding.get("canonical_family_id"))
            if id_rule and id_rule["family"] != family_key:
                family_key = id_rule["family"]
                family_label = dict(id_rule["label"])
                evidence = {"status": "reviewed", "source_ref": id_rule["source_ref"], "matched_token": model_id}
            else:
                family_label = dict(families.get(family_key) or binding.get("canonical_family_label") or {})
                evidence = binding.get("evidence") or {"status": "reviewed", "source_ref": "model-identities.json", "matched_token": model_id}
            return {
                "canonical_family_id": family_key,
                "canonical_family_label": family_label,
                "identity_mapping_status": "mapped",
                "identity_evidence": evidence,
                "model_version": _norm(binding.get("model_version")),
                "model_version_origin": "reviewed" if binding.get("model_version") else "",
                "edition_id": _norm(binding.get("edition_id")),
                "edition_origin": "reviewed" if binding.get("edition_id") else "",
                "display_mode": _norm(binding.get("display_mode")),
            }
    rule = match_identity_rule(
        capability_provider_id=capability_provider_id,
        model_id=model_id,
        family_id=family_id,
        node_type=node_type,
    )
    version, edition = extract_version(model_id)
    if rule:
        return {
            "canonical_family_id": rule["family"],
            "canonical_family_label": dict(rule["label"]),
            "identity_mapping_status": "mapped",
            "identity_evidence": {
                "status": "reviewed",
                "source_ref": rule["source_ref"],
                "matched_token": next((t for t in rule.get("tokens") or [] if t in f"{model_id} {family_id}".lower()), _norm(model_id)),
            },
            "model_version": version,
            "model_version_origin": "id_pattern" if version else "",
            "edition_id": edition,
            "edition_origin": "id_token" if edition else "",
            "display_mode": "",
        }
    return {
        "canonical_family_id": provider_local_family(adapter_id, family_id, model_id),
        "canonical_family_label": {"zh": _norm(family_id) or _norm(model_id), "en": _norm(family_id) or _norm(model_id)},
        "identity_mapping_status": "provider_local",
        "identity_evidence": {"status": "unmapped", "source_ref": "", "matched_token": ""},
        "model_version": version,
        "model_version_origin": "id_pattern" if version else "",
        "edition_id": edition,
        "edition_origin": "id_token" if edition else "",
        "display_mode": "",
    }


def compute_option_id(
    *,
    connection_id: str,
    region_id: str,
    deployment_id: str,
    node_type: str,
    catalog_model_id: str,
    endpoint_id: str,
    operation: str,
    fixed_variant_id: str = "",
) -> str:
    """稳定 option_id：规范化元组的稳定 JSON 编码后取哈希（§8.3）。

    明确不包含显示名、语言与 profile_revision。
    """
    payload = {
        "connection_id": _norm(connection_id),
        "region_id": _norm(region_id),
        "deployment_id": _norm(deployment_id),
        "node_type": _norm(node_type),
        "catalog_model_id": _norm(catalog_model_id),
        "endpoint_id": _norm(endpoint_id),
        "operation": _norm(operation),
        "fixed_variant_id": _norm(fixed_variant_id),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "opt_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def compile_option(record: Dict[str, Any], *, adapter_id: str = "") -> Dict[str, Any]:
    """把一条发现记录投影为 ExecutionOption（§8.3）。"""
    connection_id = _norm(record.get("connection_id")) or _norm(record.get("capability_provider_id"))
    region_id = _norm(record.get("region_id"))
    node_type = _norm(record.get("node_type"))
    catalog_model_id = _norm(record.get("catalog_model_id"))
    endpoint_id = _norm(record.get("endpoint_id"))
    operation = _norm(record.get("operation"))
    capability_provider_id = _norm(record.get("capability_provider_id"))
    identity = resolve_identity(
        capability_provider_id=capability_provider_id,
        adapter_id=adapter_id or capability_provider_id,
        model_id=catalog_model_id,
        family_id=_norm(record.get("legacy_family_id")),
        node_type=node_type,
        operation=operation,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "option_id": compute_option_id(
            connection_id=connection_id,
            region_id=region_id,
            deployment_id="",
            node_type=node_type,
            catalog_model_id=catalog_model_id,
            endpoint_id=endpoint_id,
            operation=operation,
        ),
        "canonical_family_id": identity["canonical_family_id"],
        "canonical_family_label": identity["canonical_family_label"],
        "legacy_family_id": _norm(record.get("legacy_family_id")),
        "model_version": identity["model_version"],
        "model_version_origin": identity["model_version_origin"],
        "edition_id": identity["edition_id"],
        "edition_origin": identity["edition_origin"],
        "display_mode": identity.get("display_mode", ""),
        "operation": operation,
        "node_type": node_type,
        "connection_id": connection_id,
        "capability_provider_id": capability_provider_id,
        "region_id": region_id,
        "deployment_id": "",
        "catalog_model_id": catalog_model_id,
        "request_model_id": _norm(record.get("request_model_id")),
        "endpoint_id": endpoint_id,
        "profile_revision": _norm(record.get("profile_revision")),
        "adapter_id": _norm(adapter_id) or capability_provider_id,
        "output_contract": _norm(record.get("output_contract")),
        "readiness": _norm(record.get("readiness")),
        "evidence_level": _norm(record.get("evidence_level")),
        "identity_mapping_status": identity["identity_mapping_status"],
        "identity_evidence": identity["identity_evidence"],
        "source_scope": _norm(record.get("source_scope")),
    }


_IMAGE_OPERATION_LABELS = {
    "text_to_image": ("文生图", "Text to Image"),
    "image_to_image": ("图生图", "Image to Image"),
    "text_to_image_or_image_to_image": ("文生图 / 图生图", "Text or Image to Image"),
    "text_or_image_to_image": ("文生图 / 图生图", "Text or Image to Image"),
    "text_or_reference_to_image": ("文生图 / 图生图", "Text or Image to Image"),
}

_MODE_LABELS = {
    "text to image": ("text_to_image", "文生图", "Text to image"),
    "文生图": ("text_to_image", "文生图", "Text to image"),
    "image to image": ("image_to_image", "图生图", "Image to image"),
    "图生图": ("image_to_image", "图生图", "Image to image"),
    "text or image to image": ("text_or_image_to_image", "文生图 / 图生图", "Text or Image to Image"),
    "文生图 / 图生图": ("text_or_image_to_image", "文生图 / 图生图", "Text or Image to Image"),
    "image editing": ("image_editing", "图像编辑", "Image Editing"),
    "图像编辑": ("image_editing", "图像编辑", "Image Editing"),
    "regional editing": ("regional_editing", "局部编辑", "Regional Editing"),
    "局部编辑": ("regional_editing", "局部编辑", "Regional Editing"),
    "image segmentation": ("image_segmentation", "图像分割", "Image Segmentation"),
    "图像分割": ("image_segmentation", "图像分割", "Image Segmentation"),
    "low-price channel": ("low_price_channel", "低价渠道版", "Low-price Channel"),
    "low price channel": ("low_price_channel", "低价渠道版", "Low-price Channel"),
    "低价渠道": ("low_price_channel", "低价渠道版", "Low-price Channel"),
    "低价渠道版": ("low_price_channel", "低价渠道版", "Low-price Channel"),
    "official stable": ("official_stable", "官方稳定版", "Official Stable"),
    "official stable version": ("official_stable", "官方稳定版", "Official Stable"),
    "官方稳定": ("official_stable", "官方稳定版", "Official Stable"),
    "官方稳定版": ("official_stable", "官方稳定版", "Official Stable"),
    "fast": ("fast", "快速版", "Fast"),
    "快速版": ("fast", "快速版", "Fast"),
    "turbo": ("turbo", "极速版", "Turbo"),
    "极速版": ("turbo", "极速版", "Turbo"),
    "pro": ("pro", "专业版", "Pro"),
    "专业版": ("pro", "专业版", "Pro"),
    "standard": ("standard", "标准版", "Standard"),
    "标准版": ("standard", "标准版", "Standard"),
    "flare": ("flare", "Flare", "Flare"),
    "sunburst": ("sunburst", "Sunburst", "Sunburst"),
    "economy": ("economy", "经济渠道", "Economy"),
    "stable-token": ("stable_token", "稳定 Token", "Stable Token"),
}

_GENERIC_MODE_LABELS = {"default", "默认"}
_INPUT_DETAIL_LABELS = {"image input", "图片输入", "text input", "文字输入", "单图输入", "图片参考"}


def _mode_parts(value: Any) -> List[str]:
    return [part.strip() for part in str(value or "").split("·") if part.strip()]


def _mode_label_entry(part: str) -> Optional[Tuple[str, str, str]]:
    return _MODE_LABELS.get(part.strip().casefold())


def _mode_version_value(part: str) -> str:
    return part.strip().lower().lstrip("v")


def _mode_numeric_version(parts: List[str]) -> str:
    """只把审阅模式中的完整数字片段识别为版本，不拆解其他名称。"""
    import re

    return next((part for part in parts if re.fullmatch(r"[vV]?\d+(?:\.\d+)?", part.strip())), "")


def _image_option_display_label(option: Dict[str, Any]) -> Tuple[str, str]:
    """从审阅标签、精确 ID 和输入操作组成可辨认的图片运行模式名。"""
    model_id = _norm(option.get("catalog_model_id"))
    model_id_lower = model_id.lower()
    reviewed_parts = _mode_parts(option.get("display_mode"))
    variant_parts = _mode_parts(option.get("variant_name"))
    variant_en_parts = _mode_parts(option.get("variant_name_en"))
    reviewed_version = _mode_numeric_version(reviewed_parts)
    variant_version = _mode_numeric_version(variant_parts)
    version = (
        reviewed_version
        or variant_version
        or _norm(option.get("model_version"))
        or extract_version(model_id)[0]
    )

    # 已审阅模式中的 V2/V2.5 写法优先保留；档案版本为空时再从真实模型 ID 提取。
    version_display = next((part for part in reviewed_parts
                            if version and _mode_version_value(part) == _mode_version_value(version)), "")
    version_display = version_display or reviewed_version
    if not version_display:
        version_display = variant_version
    version_display = version_display or version

    reviewed_entries = [(part, _mode_label_entry(part)) for part in reviewed_parts]
    reviewed_purpose = next((entry for _, entry in reviewed_entries
                             if entry and entry[0] in {"image_editing", "regional_editing", "image_segmentation"}), None)

    operation = _norm(option.get("operation"))
    purpose = reviewed_purpose
    if purpose is None:
        operation_label = _IMAGE_OPERATION_LABELS.get(operation)
        if operation_label:
            purpose = (operation, operation_label[0], operation_label[1])
        else:
            purpose = next((entry for _, entry in reviewed_entries
                            if entry and entry[0] in {"text_to_image", "image_to_image", "text_or_image_to_image"}), None)

    descriptor_entries: List[Tuple[str, str, str]] = []

    def add_descriptor(part: str, counterpart: str = "") -> None:
        cleaned = part.strip()
        if not cleaned or cleaned.casefold() in _GENERIC_MODE_LABELS or cleaned.casefold() in _INPUT_DETAIL_LABELS:
            return
        if version and _mode_version_value(cleaned) == _mode_version_value(version):
            return
        if cleaned.casefold() in {model_id_lower, _norm(option.get("family_name")).lower(), operation.casefold()}:
            return
        entry = _mode_label_entry(cleaned)
        if entry:
            # 运行目的已表达同一信息时，删除重复片段。
            if entry[0] in {"text_to_image", "image_to_image", "text_or_image_to_image"}:
                return
            if purpose and entry[0] == purpose[0]:
                return
            descriptor_entries.append(entry)
            return
        counterpart = counterpart.strip()
        counterpart_is_id = counterpart.casefold() in {
            model_id_lower, _norm(option.get("family_name")).lower(), operation.casefold(),
        }
        if not counterpart or counterpart.casefold() in _GENERIC_MODE_LABELS | _INPUT_DETAIL_LABELS or counterpart_is_id:
            counterpart = cleaned
        # 保留档案中的未映射变体名称，并使用同位置英文名称；不推断其质量或渠道含义。
        descriptor_entries.append(("label:" + cleaned.casefold(), cleaned, counterpart))

    for part in reviewed_parts:
        add_descriptor(part)
    if len(variant_parts) == len(variant_en_parts):
        for zh_part, en_part in zip(variant_parts, variant_en_parts):
            add_descriptor(zh_part, en_part)
    else:
        for part in variant_parts:
            add_descriptor(part)
        for part in variant_en_parts:
            add_descriptor(part)

    # 按审阅档案先后取值，不依赖候选列表顺序；归并中英文同义项与重复渠道标签。
    unique_descriptors: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for entry in descriptor_entries:
        if entry[0] not in seen:
            seen.add(entry[0])
            unique_descriptors.append(entry)

    zh_parts = [part for part in (version_display, purpose[1] if purpose else "") if part]
    en_parts = [part for part in (version_display, purpose[2] if purpose else "") if part]
    zh_parts.extend(item[1] for item in unique_descriptors)
    en_parts.extend(item[2] for item in unique_descriptors)
    if not zh_parts:
        # 没有可核实的版本、用途或名称时，保留原始模型 ID 供用户核对。
        return model_id, model_id
    return " · ".join(zh_parts), " · ".join(en_parts)


def option_display_label(option: Dict[str, Any]) -> Dict[str, str]:
    """第三栏叶子主标题；名称改变不改变 option_id 或请求身份。"""
    label = dict(option.get("canonical_family_label") or {})
    if _norm(option.get("node_type")) == "image_generation":
        zh, en = _image_option_display_label(option)
    else:
        reviewed_mode = _norm(option.get("display_mode"))
        if reviewed_mode:
            zh, en = reviewed_mode, _norm(option.get("display_mode_en")) or reviewed_mode
        else:
            parts = [
                _norm(option.get("model_version")),
                _norm(option.get("edition_id")),
                _norm(option.get("operation")),
            ]
            fallback = " · ".join(part for part in parts if part) or _norm(option.get("catalog_model_id"))
            zh, en = fallback, fallback
    return {"zh": zh, "en": en, "family_zh": label.get("zh", ""), "family_en": label.get("en", "")}


def compile_options(records: Iterable[Dict[str, Any]], *, adapter_id: str = "") -> List[Dict[str, Any]]:
    """批量投影，按 option_id 去重但保留全部来源记录数。"""
    compiled: Dict[str, Dict[str, Any]] = {}
    for record in records:
        option = compile_option(record, adapter_id=adapter_id)
        existing = compiled.get(option["option_id"])
        if existing is None:
            option["source_record_count"] = 1
            compiled[option["option_id"]] = option
        else:
            existing["source_record_count"] = int(existing.get("source_record_count") or 0) + 1
    return list(compiled.values())


def detect_conflicts(options: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """冲突报告：同 ID 跨站、同 ID 多 operation、身份未映射、option_id 重复语义。"""
    options = list(options)
    by_region: Dict[str, set] = {}
    by_operation: Dict[Tuple[str, str, str], set] = {}
    unmapped = []
    for option in options:
        key = (
            _norm(option.get("connection_id")),
            _norm(option.get("catalog_model_id")),
            _norm(option.get("node_type")),
        )
        by_region.setdefault(_norm(option.get("catalog_model_id")), set()).add(_norm(option.get("region_id")))
        by_operation.setdefault(key, set()).add(_norm(option.get("operation")))
        if option.get("identity_mapping_status") != "mapped":
            unmapped.append(option.get("option_id"))
    cross_region = {mid: sorted(r for r in regions) for mid, regions in by_region.items() if len(regions) > 1}
    multi_operation = {f"{k[0]}::{k[1]}::{k[2]}": sorted(v) for k, v in by_operation.items() if len(v) > 1}
    return {
        "option_count": len(options),
        "distinct_canonical_families": len({o.get("canonical_family_id") for o in options}),
        "mapped_count": sum(1 for o in options if o.get("identity_mapping_status") == "mapped"),
        "unmapped_count": len(unmapped),
        "cross_region_same_id": cross_region,
        "cross_region_same_id_count": len(cross_region),
        "multi_operation_same_id": multi_operation,
        "multi_operation_same_id_count": len(multi_operation),
    }


def group_by_canonical_family(options: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """按 canonical_family_id 聚合，供第一栏展示；跨平台条目归入同一系列。"""
    families: Dict[str, List[Dict[str, Any]]] = {}
    for option in options:
        families.setdefault(_norm(option.get("canonical_family_id")), []).append(option)
    return families


def build_identity_document(options: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """生成 model-identities.json 内容（§8.2）。"""
    families: Dict[str, Dict[str, str]] = {}
    bindings: List[Dict[str, Any]] = []
    for option in options:
        family_id = _norm(option.get("canonical_family_id"))
        if not family_id:
            continue
        label = option.get("canonical_family_label") or {}
        families.setdefault(family_id, {"id": family_id, "label": {"zh": label.get("zh", ""), "en": label.get("en", "")}})
        if option.get("identity_mapping_status") != "mapped":
            continue
        bindings.append({
            "match": {
                "capability_provider_id": _norm(option.get("capability_provider_id")),
                "model_id": _norm(option.get("catalog_model_id")),
                "node_type": _norm(option.get("node_type")),
            },
            "canonical_family_id": family_id,
            "model_version": option.get("model_version", ""),
            "edition_id": option.get("edition_id", ""),
            "evidence": option.get("identity_evidence") or {},
        })
    bindings.sort(key=lambda item: (
        item["match"]["capability_provider_id"], item["match"]["node_type"], item["match"]["model_id"]
    ))
    return {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "families": sorted(families.values(), key=lambda item: item["id"]),
        "bindings": bindings,
    }


def load_identity_document(root: Path) -> Dict[str, Any]:
    path = Path(root) / "data" / "model_capabilities" / "model-identities.json"
    if not path.is_file():
        return {"schema_version": IDENTITY_SCHEMA_VERSION, "families": [], "bindings": []}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def output_contract_text(output: Any) -> str:
    """把档案的 output 契约规范成 "media,min=..,max=.." 文本。

    档案里 `output` 是字典，直接 str() 会得到 Python repr，既不可读也无法被消费方比较。
    """
    if isinstance(output, dict):
        parts = [str(output.get("media_type") or "").strip()]
        for key in ("min", "max"):
            if output.get(key) is not None:
                parts.append(f"{key}={output[key]}")
        if output.get("async"):
            parts.append("async")
        return ",".join(part for part in parts if part)
    return str(output or "").strip()


def _model_region_entries(model: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """列出模型在每个站点上的有效配置；分站条目不能被合并成一条。"""
    regions = [str(item).strip() for item in (model.get("regions") or []) if str(item).strip()]
    region_profiles = model.get("region_profiles") if isinstance(model.get("region_profiles"), dict) else {}
    if not regions:
        regions = [""]
    entries: List[Tuple[str, Dict[str, Any]]] = []
    for region in regions:
        scoped = region_profiles.get(region) if region else None
        entries.append((region, scoped if isinstance(scoped, dict) else model))
    return entries


def generation_capability_tags(profile: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """标签只来自操作与已声明输入，不从营销名称猜能力。"""
    names = {
        'chat': ('文本对话', 'Text chat'), 'chat_or_agent_text': ('文本与 Agent', 'Text / Agent'),
        'multimodal_chat': ('多模态理解', 'Multimodal understanding'),
        'prompt_enhancement': ('提示词优化', 'Prompt enhancement'),
        'text_to_image': ('文生图', 'Text to image'), 'image_to_image': ('图生图', 'Image to image'),
        'text_to_video': ('文生视频', 'Text to video'), 'image_to_video': ('图生视频', 'Image to video'),
        'reference_to_video': ('参考生视频', 'Reference to video'),
        'start_end_to_video': ('首尾帧', 'First / last frame'),
        'multimodal_to_video': ('多模态参考', 'Multimodal reference'),
        'text_to_speech': ('语音合成', 'Text to speech'), 'text_to_audio': ('语音合成', 'Text to speech'),
        'speech_or_audio': ('语音与音效', 'Speech / sound'),
        'sound_effects': ('音效生成', 'Sound effects'), 'text_to_sound': ('音效生成', 'Sound effects'),
        'music_sounds': ('音效生成', 'Sound effects'),
        'music': ('音乐生成', 'Music generation'), 'music_song': ('歌曲生成', 'Song generation'),
        'flowmusic_generation': ('音乐生成', 'Music generation'), 'music_to_music': ('参考音频翻唱', 'Audio cover'),
        'midjourney_imagine': ('文生图', 'Text to image'),
    }
    operation = str(profile.get('operation') or '')
    pairs = [names[operation]] if operation in names else []
    if operation in {'text_to_image_or_image_to_image', 'text_or_image_to_image', 'text_or_reference_to_image'}:
        pairs.extend([names['text_to_image'], names['image_to_image']])
    if operation in {'text_to_video_or_image_to_video', 'text_or_image_to_video', 'text_or_reference_to_video'}:
        pairs.extend([names['text_to_video'], names['image_to_video']])
    inputs = profile.get('inputs') or {}
    image_max = sum(float(spec.get('max', 1) or 0) for key, spec in inputs.items()
                    if spec.get('media_type') == 'image' and str(spec.get('role') or key).startswith('reference'))
    if image_max > 1:
        pairs.append(('多图参考', 'Multiple image references'))
    if any(spec.get('media_type') == 'audio' for spec in inputs.values()):
        pairs.append(('音频参考', 'Audio reference'))
    if any(spec.get('media_type') == 'video' for spec in inputs.values()):
        pairs.append(('视频参考', 'Video reference'))
    return [pair[0] for pair in pairs], [pair[1] for pair in pairs]


def compile_catalog_options(catalog: Dict[str, Any], *, adapter_id: str = "") -> List[Dict[str, Any]]:
    """把 ModelCapabilityRegistry.build_catalog 的结果编译为扁平可执行选项。

    前端不再自行计算 option_id，避免前后端各算一套标识（§13.5）。
    同一真实 ID 在不同站点出现时产出多个选项，各自带自己的 region 与 option_id（E01）。
    """
    compiled: Dict[str, Dict[str, Any]] = {}
    identity_document = load_identity_document(Path(__file__).resolve().parent)
    for provider in (catalog or {}).get("providers") or []:
        if not isinstance(provider, dict):
            continue
        connection_id = _norm(provider.get("id"))
        capability_id = _norm(provider.get("capability_provider_id")) or connection_id
        for model in provider.get("models") or []:
            if not isinstance(model, dict):
                continue
            model_id = _norm(model.get("model_id"))
            if not model_id:
                continue
            for region, scoped in _model_region_entries(model):
                node_type = _norm(scoped.get("node_type") or model.get("node_type"))
                operation = _norm(scoped.get("operation") or model.get("operation"))
                endpoint_id = _norm(scoped.get("endpoint_id"))
                identity = resolve_identity(
                    capability_provider_id=capability_id,
                    adapter_id=adapter_id or capability_id,
                    model_id=model_id,
                    family_id=_norm(model.get("family_id")),
                    node_type=node_type,
                    identity_document=identity_document,
                    operation=operation,
                )
                if identity['identity_mapping_status'] != 'mapped':
                    identity['canonical_family_label'] = {
                        'zh': model.get('family_name') or model_id,
                        'en': model.get('family_name_en') or model.get('family_name') or model_id,
                    }
                from model_capabilities import generation_visibility_issue
                visibility_issue = generation_visibility_issue({**model, **scoped})
                tags_zh, tags_en = generation_capability_tags({**model, **scoped})
                use_image_mode_label = node_type == "image_generation"
                if use_image_mode_label:
                    display = option_display_label({
                        "canonical_family_label": identity["canonical_family_label"],
                        "catalog_model_id": model_id,
                        "family_name": _norm(model.get("family_name")),
                        "model_version": identity.get("model_version", ""),
                        "edition_id": identity.get("edition_id"),
                        "display_mode": identity.get("display_mode", ""),
                        "display_mode_en": identity.get("display_mode_en", ""),
                        "variant_name": _norm(model.get("variant_name")),
                        "variant_name_en": _norm(model.get("variant_name_en")),
                        "operation": operation,
                        "node_type": node_type,
                    })
                    display_label = {"zh": display["zh"], "en": display["en"]}
                else:
                    # 图片命名规则不扩展到文本、视频、音频等其他能力。
                    display_label = {
                        "zh": _norm(model.get("variant_name")) or _norm(identity.get("display_mode")) or model_id,
                        "en": _norm(model.get("variant_name_en")) or _norm(model.get("variant_name"))
                             or _norm(identity.get("display_mode_en")) or _norm(identity.get("display_mode")) or model_id,
                    }
                option = {
                    "schema_version": SCHEMA_VERSION,
                    "option_id": compute_option_id(
                        connection_id=connection_id,
                        region_id=region,
                        deployment_id="",
                        node_type=node_type,
                        catalog_model_id=model_id,
                        endpoint_id=endpoint_id,
                        operation=operation,
                    ),
                    "canonical_family_id": identity["canonical_family_id"],
                    "canonical_family_label": identity["canonical_family_label"],
                    "legacy_family_id": _norm(model.get("family_id")),
                    "family_name": _norm(model.get("family_name")),
                    "model_version": identity["model_version"],
                    "edition_id": identity["edition_id"],
                    "display_mode": identity.get("display_mode", ""),
                    "display_label": display_label,
                    # Hypit 通过模型 variant 字段读取同一份投影名称。
                    "variant_name": display_label["zh"],
                    "variant_name_en": display_label["en"],
                    "operation": operation,
                    "node_type": node_type,
                    "connection_id": connection_id,
                    "capability_provider_id": capability_id,
                    "platform_label": _norm(provider.get("name")) or capability_id,
                    "region_id": region,
                    "deployment_id": "",
                    "catalog_model_id": model_id,
                    "request_model_id": _norm(scoped.get("request_model_id")),
                    "endpoint_id": endpoint_id,
                    "variant_id": _norm(scoped.get("variant_id") or model.get("variant_id")),
                    "profile_revision": _norm(scoped.get("version") or model.get("version")),
                    "adapter_id": adapter_id or capability_id,
                    "readiness": _norm(scoped.get("readiness") or model.get("readiness")),
                    "runnable": bool(scoped.get("runnable", model.get("runnable"))),
                    "selectable": bool(scoped.get('runnable', model.get('runnable'))) and not visibility_issue,
                    "selection_unavailable_reason": visibility_issue,
                    "validation_mode": _norm(scoped.get("validation_mode") or model.get("validation_mode")),
                    "identity_mapping_status": identity["identity_mapping_status"],
                    "identity_evidence": identity["identity_evidence"],
                    "capability_tags": tags_zh,
                    "capability_tags_en": tags_en,
                    "output_contract": output_contract_text(scoped.get("output") if scoped.get("output") is not None else model.get("output")),
                    "inputs": scoped.get("inputs") or model.get("inputs") or {},
                    "parameters": scoped.get("parameters") or model.get("parameters") or {},
                    "profile_ref": _norm(scoped.get("profile_ref") or model.get("profile_ref") or model_id),
                }
                compiled.setdefault(option["option_id"], option)
    options = sorted(compiled.values(), key=lambda item: (
        item["canonical_family_id"], item["connection_id"], item["region_id"], item["catalog_model_id"], item["operation"]
    ))
    # 同平台、同地区、同家族的模式重名时，以真实目录 ID 作为最后消歧信息。
    duplicate_labels: Dict[Tuple[str, str, str, str, str], List[Dict[str, Any]]] = {}
    for option in options:
        if option.get("node_type") != "image_generation":
            continue
        label = option.get("display_label") or {}
        key = (
            _norm(option.get("connection_id")), _norm(option.get("region_id")),
            _norm(option.get("canonical_family_id")), _norm(label.get("zh")), _norm(label.get("en")),
        )
        duplicate_labels.setdefault(key, []).append(option)
    for group in duplicate_labels.values():
        if len({_norm(item.get("catalog_model_id")) for item in group}) < 2:
            continue
        for option in group:
            model_id = _norm(option.get("catalog_model_id"))
            option["display_label"] = {
                "zh": f"{option['display_label']['zh']} · {model_id}",
                "en": f"{option['display_label']['en']} · {model_id}",
            }
            option["variant_name"] = option["display_label"]["zh"]
            option["variant_name_en"] = option["display_label"]["en"]
    return options


def catalog_revision(options: Iterable[Dict[str, Any]]) -> str:
    """目录内容摘要：用于缓存键与“档案已更新”判定（§11.4、§12.3）。"""
    payload = [
        {
            "option_id": option.get("option_id"),
            "readiness": option.get("readiness"),
            "profile_revision": option.get("profile_revision"),
            "operation": option.get("operation"),
        }
        for option in sorted(options, key=lambda item: str(item.get("option_id") or ""))
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "rev_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
