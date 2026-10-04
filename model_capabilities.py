import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


CONFIRMED_EVIDENCE = {"runtime_verified", "official_schema", "official_documented"}


def generation_visibility_issue(profile: Dict[str, Any]) -> str:
    """生成节点的候选边界；保留工具目录和用户启用记录，不冒充已适配生成能力。"""
    model_id = str(profile.get("model_id") or profile.get("catalog_model_id") or "").lower()
    operation = str(profile.get("operation") or "").lower()
    if model_id.startswith('marble') or operation in {'text_to_3d', 'image_to_3d'}:
        return '3D 场景输入与结果尚未接入'
    if not profile.get('inputs'):
        return '生成输入契约尚未完整登记'
    expected = {'text_generation': 'text', 'image_generation': 'image', 'video_generation': 'video',
                'audio_generation': 'audio', 'music_generation': 'audio'}.get(profile.get('node_type'))
    actual = (profile.get('output') or {}).get('media_type') or str(profile.get('output_contract') or '').split(',')[0]
    if actual == 'chat':
        actual = 'text'
    if expected and actual and expected != actual:
        return '输出类型不属于该生成节点'
    return ''


NODE_MODEL_FIELDS = {
    "text_generation": "chat_models",
    "image_generation": "image_models",
    "video_generation": "video_models",
    "audio_generation": "audio_models",
    "music_generation": "audio_models",
}
INPUT_ROLE_ALIASES = {
    "first": "first_frame",
    "last": "last_frame",
    "reference_image": "reference",
    "image_reference": "reference",
    "audio_reference": "reference_audio",
}
PROVIDER_ALIASES = {
    "codex": "codex-cli",
    "jimeng": "jimeng-cli",
}


from static.model_migrations import normalize_laohu_model_id
RUNNINGHUB_PROFILE_ALIASES = {
    "seedance-2.0-global/text-to-video": "Seedance2.0 Text to Video",
    "seedance-2.0-global/image-to-video": "Seedance2.0 Image to Video",
}

JIMENG_IMAGE_TEXT2IMAGE_MODELS = {"3.0", "3.1", "4.0", "4.1", "4.5", "4.6", "4.7", "5.0", "5.0Pro"}
JIMENG_IMAGE2IMAGE_MODELS = {"4.0", "4.1", "4.5", "4.6", "4.7", "5.0", "5.0Pro"}


def jimeng_image_resolution_options(model_id: str, mode: str = "text2image") -> List[str]:
    """按具体模型返回已核实接口契约的分辨率，不跨模型统一选项。"""
    normalized = str(model_id or "").strip()
    if mode == "image2image" and normalized in {"3.0", "3.1"}:
        return []
    if normalized == "5.0Pro":
        # 2026-09-12 服务端明确要求 1.5k/2k/4k；CLI 旧帮助不能缩减接口选项。
        return ["1.5k", "2k", "4k"]
    if normalized in {"3.0", "3.1"}:
        return ["1k", "2k"]
    if normalized in (JIMENG_IMAGE2IMAGE_MODELS if mode == "image2image" else JIMENG_IMAGE_TEXT2IMAGE_MODELS):
        return ["2k", "4k"]
    return ["2k", "4k"]


def _is_music_model_id(model_id: str) -> bool:
    lower = str(model_id or "").strip().lower()
    return lower.startswith("flowmusic") or bool(re.search(r"(?:^|[-/:_])(music|mureka|suno)(?:[-/:_]|$)", lower))


_MODEL_TIER_LABELS = {
    "fast": "Fast",
    "mini": "Mini",
    "pro": "Pro",
    "turbo": "Turbo",
    "lite": "Lite",
    "flash": "Flash",
    "standard": "Standard",
    "std": "Standard",
    "quality": "Quality",
    "4k": "4K",
    "code": "Code",
    "plus": "Plus",
    "max": "Max",
    "max-preview": "Max Preview",
    "ultra": "Ultra",
    "spicy": "Spicy",
    "ad": "AD",
    "drama": "Drama",
    "mix": "Mix",
    "realistic": "Realistic",
    "omni-flash": "Omni Flash",
}


_OPERATION_LABELS = {
    "chat": ("对话", "Chat"),
    "text_to_image": ("文生图", "Text to Image"),
    "image_to_image": ("图生图", "Image to Image"),
    "text_to_image_or_image_to_image": ("文生图 / 图生图", "Text or Image to Image"),
    "image_enhancement": ("图片增强", "Image Enhancement"),
    "text_to_video": ("文生视频", "Text to Video"),
    "image_to_video": ("图生视频", "Image to Video"),
    "reference_to_video": ("参考生视频", "Reference to Video"),
    "start_end_to_video": ("首尾帧生视频", "Start-End to Video"),
    "video_to_video": ("视频编辑", "Video to Video"),
    "video_extend": ("视频续写", "Video Extension"),
    "multimodal_to_video": ("多模态视频", "Multimodal Video"),
    "compatible_video": ("视频生成", "Video Generation"),
    "special_video": ("视频处理", "Video Processing"),
    "video_enhancement": ("视频增强", "Video Enhancement"),
    "motion_control": ("动作控制", "Motion Control"),
    "text_to_audio": ("文本转语音", "Text to Speech"),
    "text_to_speech": ("文本转语音", "Text to Speech"),
    "speech_or_audio": ("语音生成", "Speech Generation"),
    "voice_clone": ("声音克隆", "Voice Clone"),
    "voice_design": ("音色设计", "Voice Design"),
    "audio_to_audio": ("音频处理", "Audio Processing"),
    "music": ("音乐生成", "Music Generation"),
    "music_to_music": ("音乐处理", "Music Processing"),
    "music_song": ("歌曲生成", "Song Generation"),
    "image_description": ("图片描述", "Image Description"),
    "prompt_enhancement": ("提示词优化", "Prompt Enhancement"),
    "transcription": ("音频转写", "Audio Transcription"),
    "video_upscale": ("视频放大", "Video Upscale"),
    "image_upscale": ("图片放大", "Image Upscale"),
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _tier_name(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    return _MODEL_TIER_LABELS.get(normalized, normalized.replace("-", " ").title())


def _route_labels(model_id: str) -> tuple[str, str]:
    lower = str(model_id or "").strip().lower()
    labels = []
    if "global" in lower:
        labels.append(("全球版", "Global"))
    if "channel-low-price" in lower or "lowprice" in lower:
        labels.append(("低价渠道版", "Low-price Channel"))
    elif "official-stable" in lower:
        labels.append(("官方稳定版", "Official Stable"))
    if "_vip" in lower or lower.endswith("-vip"):
        labels.append(("VIP", "VIP"))
    if "asyn" in lower or "async" in lower:
        labels.append(("异步", "Async"))
    if "deprecated" in lower or "下架" in lower:
        labels.append(("已下架", "Deprecated"))
    return " · ".join(item[0] for item in labels), " · ".join(item[1] for item in labels)


def _operation_labels(profile: Dict[str, Any]) -> tuple[str, str]:
    operation = str(profile.get("operation") or "").strip()
    if operation in _OPERATION_LABELS:
        return _OPERATION_LABELS[operation]
    if operation == "text_to_video_or_image_to_video":
        return "文生视频 / 图生视频", "Text or Image to Video"
    if operation == "text_or_image_to_video":
        return "文生视频 / 图生视频", "Text or Image to Video"
    if operation == "text_or_image_to_image":
        return "文生图 / 图生图", "Text or Image to Image"
    if operation.startswith("music_"):
        action = operation.removeprefix("music_")
        action_labels = {
            "generation": ("歌曲生成", "Song Generation"),
            "lyrics": ("歌词生成", "Lyrics Generation"),
            "inspo": ("参考音乐生成", "Music Inspiration"),
            "sounds": ("音效生成", "Sound Effects"),
            "upload": ("导入音频", "Import Audio"),
            "cover_song": ("风格翻唱", "Cover Song"),
            "extend": ("歌曲续写", "Extend Song"),
            "crop": ("裁剪歌曲", "Crop Song"),
            "remaster": ("重新母带", "Remaster"),
            "add_vocals": ("添加人声", "Add Vocals"),
            "add_instrumental": ("添加伴奏", "Add Instrumental"),
        }
        return action_labels.get(action, (f"音乐：{action.replace('_', ' ')}", f"Music: {action.replace('_', ' ')}"))
    if operation.startswith("midjourney_"):
        action = operation.removeprefix("midjourney_")
        action_labels = {
            "imagine": ("生成图片", "Imagine"),
            "blend": ("图片混合", "Blend"),
            "upscale": ("图片放大", "Upscale"),
            "variation": ("生成变体", "Variation"),
            "high_variation": ("高变化变体", "High Variation"),
            "low_variation": ("低变化变体", "Low Variation"),
            "reroll": ("重新生成", "Reroll"),
            "pan": ("扩展画面", "Pan"),
            "zoom": ("缩放画面", "Zoom"),
            "inpaint": ("局部重绘", "Inpaint"),
            "edits": ("图片编辑", "Edits"),
            "describe": ("图片描述", "Describe"),
        }
        return action_labels.get(action, (f"Midjourney：{action.replace('_', ' ')}", f"Midjourney: {action.replace('_', ' ')}"))
    if operation == "prompt_enhancement":
        model_id = str(profile.get("model_id") or "").lower()
        for suffix, labels in (
            ("-multimodal", ("多模态提示词优化", "Multimodal Prompt Enhancement")),
            ("-image", ("图片提示词优化", "Image Prompt Enhancement")),
            ("-text", ("文本提示词优化", "Text Prompt Enhancement")),
        ):
            if model_id.endswith(suffix):
                return labels
    current = str(profile.get("variant_name") or profile.get("display_name") or operation or "默认").strip()
    return current, str(profile.get("variant_name_en") or current).strip()


def _classification_tier(profile: Dict[str, Any], provider_id: str) -> str:
    model_id = str(profile.get("model_id") or "").strip().lower().replace("_", "-")
    node_type = str(profile.get("node_type") or "").strip()
    operation = str(profile.get("operation") or "").strip()
    family_id = str(profile.get("family_id") or "").strip()

    if provider_id == "jimeng-cli" and node_type == "video_generation":
        if "mini" in model_id:
            return "mini"
        if "fast" in model_id:
            return "fast"
        return ""

    if provider_id == "ai-money":
        if node_type == "text_generation":
            for pattern in (
                r"doubao-seed-2\.0-(code|lite|mini|pro)$",
                r"doubao-seed-2\.1-(pro|turbo)$",
                r"deepseek-v4-(flash|pro)$",
                r"glm-5-(turbo)$",
                r"qwen3\.(?:6|7|8)-(flash|max-preview|max|plus)$",
            ):
                match = re.search(pattern, model_id)
                if match:
                    return match.group(1)
        if node_type == "image_generation":
            if re.search(r"image-nb-2-lite$", model_id):
                return "lite"
            if re.search(r"image-nb-flash$", model_id):
                return "flash"
            if re.search(r"qwen-image-3\.0(?:-global)?-pro-", model_id):
                return "pro"
            if re.search(r"wan-2\.7-global-i2i-pro$", model_id):
                return "pro"
            match = re.search(r"image-gk-v(15|2)(?:-edit)?$", model_id)
            if match:
                return f"v{match.group(1)}"
        if node_type == "video_generation":
            patterns = (
                r"seedance-[0-9.]+-(?:global-)?(fast|mini|standard)-",
                r"hailuo-2\.3-(fast-pro|fast|pro|standard)-",
                r"kling-(?:o3|v3(?:\.0)?)-(turbo-pro|turbo-std|4k|pro|std)-",
                r"minimax-h3-ow-.*-(fast)$",
                r"vidu-q3-(pro-fast|pro|turbo|ad|drama|mix)-",
            )
            for pattern in patterns:
                match = re.search(pattern, model_id)
                if match:
                    return match.group(1)
            if model_id == "laohu-video-g-omni-flash":
                return "omni-flash"
            match = re.search(r"laohu-video-v31-(fast|lite|quality)$", model_id)
            if match:
                return match.group(1)
        if node_type == "audio_generation":
            if model_id.startswith("minimax-speech-"):
                return model_id.removeprefix("minimax-")
            if model_id.startswith("qwen3-tts-"):
                return model_id.removeprefix("qwen3-tts-")
        if node_type == "music_generation" and re.fullmatch(r"mureka-(?:o2|v9)-song", model_id):
            return model_id.removeprefix("mureka-").removesuffix("-song")

    if provider_id == "runninghub":
        if node_type == "image_generation":
            if model_id.startswith("topazlabs-image-"):
                return model_id.removeprefix("topazlabs-image-")
            if model_id.startswith("midjourney-text-to-image-"):
                return model_id.removeprefix("midjourney-text-to-image-")
            if model_id.endswith("/image-edit-pro") or model_id.endswith("/text-to-image-pro"):
                return "pro"
            if model_id.endswith("/edit-ultra-official-stable") or model_id.endswith("/text-to-image-ultra-official-stable"):
                return "ultra"
        if node_type == "video_generation":
            patterns = (
                r"seedance[- ]?v?[0-9.]+[- ](fast|mini|standard)\b",
                r"seedance-[0-9.]+-(?:global-)?(fast|mini|standard)-",
                r"google/veo[0-9.]+-(fast|lite|pro)/",
                r"vidu-.*-q[23]-(pro-fast|pro|turbo|ad|drama|mix)-",
                r"hailuo-(?:02|2\.3)-(fast-pro|fast|pro|standard)[-/]",
                r"kling-(?:video-)?(?:o3|v2\.5|v2\.6|v3(?:\.0)?)-(turbo-pro|turbo-std|4k|pro|std)[-/]",
                r"skyreels-v[0-9.]+/(?:omni-reference-|image-to-video-|text-to-video-)(fast|std)$",
                r"sora-2/.*-(pro|realistic)-",
            )
            for pattern in patterns:
                match = re.search(pattern, model_id)
                if match:
                    return match.group(1)
            if "wan-2.6" in model_id and "-flash" in model_id:
                return "flash"
            if "wan-2.7-spicy" in model_id:
                return "spicy"
            if "minimax-h3" in model_id and "regeneration" in model_id:
                return "regeneration"
        if node_type == "audio_generation" and model_id.startswith("minimax/"):
            if model_id.startswith("minimax/speech-"):
                return model_id.removeprefix("minimax/")
            if model_id.endswith("voice-clone"):
                return "voice-clone"
            if model_id.endswith("voice-design"):
                return "voice-design"
        if node_type == "music_generation":
            if model_id.startswith("minimax/music-"):
                return model_id.removeprefix("minimax/")
            match = re.fullmatch(r"suno-(?:single|custom)-v(.+)", model_id)
            if match:
                return f"v{match.group(1)}"
            if model_id == "suno-lyrics":
                return "tools"

    return ""


_VIDEO_OPERATION_DISPLAY_EXCEPTIONS = {
    "video_upscale",
    "video_to_video",
    "video_extend",
    "video_enhancement",
    "video_effects",
    "video_transition",
    "motion_control",
    "lip_sync",
    "avatar_video",
    "subtitle_erase",
    "video_translation",
    "special_video",
    "draft_enhance",
    "script_to_video",
}


def _video_mode_from_inputs(profile: Dict[str, Any]) -> tuple[str, str]:
    """根据能力档案的输入字段生成视频运行模式展示名。"""
    operation = str(profile.get("operation") or "").strip()
    if operation in _VIDEO_OPERATION_DISPLAY_EXCEPTIONS:
        return _operation_labels(profile)

    media_types = {
        str(spec.get("media_type") or "").strip().lower()
        for spec in (profile.get("inputs") or {}).values()
        if isinstance(spec, dict)
    }
    roles = set()
    required_roles = set()
    for key, spec in (profile.get("inputs") or {}).items():
        if not isinstance(spec, dict):
            continue
        role = str(spec.get("role") or key).strip().lower().replace("-", "_")
        roles.add(role)
        if int(spec.get("min") or 0) > 0:
            required_roles.add(role)
    if "video" in media_types or "audio" in media_types or "source_video" in roles or "reference_audio" in roles:
        return _OPERATION_LABELS["multimodal_to_video"]
    if {"first_frame", "last_frame"}.issubset(required_roles):
        return _OPERATION_LABELS["start_end_to_video"]
    if "image" in media_types or "reference" in roles or "first_frame" in roles or "last_frame" in roles:
        return _OPERATION_LABELS["image_to_video"]
    return _OPERATION_LABELS["text_to_video"]


def _family_without_classification_tier(profile: Dict[str, Any], provider_id: str) -> tuple[str, str, str]:
    """清理旧档案中误写进家族的版本后缀，版本只留给运行模式。"""
    family_id = str(profile.get("family_id") or profile.get("model_id") or "").strip()
    family_name = str(profile.get("family_name") or profile.get("display_name") or family_id).strip()
    family_name_en = str(profile.get("family_name_en") or family_name).strip()
    tier = _classification_tier(profile, provider_id)
    if tier == "tools":
        return f"{family_id}-tools", "Suno 工具", "Suno Tools"
    if not tier:
        return family_id, family_name, family_name_en
    suffix = f"-{_slug(tier)}"
    if family_id.lower().endswith(suffix):
        family_id = family_id[: -len(suffix)].rstrip("-")
    label = _tier_name(tier)
    family_name = re.sub(rf"(?:[ ·/-]+){re.escape(label)}$", "", family_name, flags=re.I).strip()
    family_name_en = re.sub(rf"(?:[ ·/-]+){re.escape(label)}$", "", family_name_en, flags=re.I).strip()
    return family_id, family_name, family_name_en


def _variant_identity_label(profile: Dict[str, Any], provider_id: str, has_fast_sibling: bool = False) -> tuple[str, str]:
    """从真实 ID 提取可解释的版本与档次，避免用列表序号区分模式。"""
    model_id = str(profile.get("model_id") or "").strip().lower()
    version = re.search(r"(?:^|[/_-])(?:(v|q|h|o))?(\d+(?:\.\d+)?)(?=[/_-]|$)", model_id)
    prefix = ""
    if version:
        marker = version.group(1) or ""
        prefix = f"{marker.upper()}{version.group(2)}" if marker in "qho" and marker else version.group(2)
    qualifiers = []
    tier = _classification_tier(profile, provider_id)
    for token, zh, en in (
        ("fast", "快速版", "Fast"), ("turbo", "极速版", "Turbo"),
        ("flash", "闪速版", "Flash"), ("pro", "专业版", "Pro"),
        ("max", "增强版", "Max"), ("lite", "轻量版", "Lite"),
        ("mini", "精简版", "Mini"), ("standard", "标准版", "Standard"),
        ("std", "标准版", "Standard"),
    ):
        if re.search(rf"(?:^|[/_-]){token}(?=[/_-]|$)", model_id):
            qualifiers.append((zh, en))
    if not qualifiers and tier in {"fast", "mini", "pro", "turbo", "lite", "flash"}:
        qualifiers.append((dict(fast="快速版", mini="精简版", pro="专业版", turbo="极速版", lite="轻量版", flash="闪速版")[tier], tier.title()))
    if not qualifiers and has_fast_sibling:
        qualifiers.append(("标准版", "Standard"))
    zh_parts = ([prefix] if prefix else []) + [item[0] for item in qualifiers]
    en_parts = ([prefix] if prefix else []) + [item[1] for item in qualifiers]
    return " · ".join(zh_parts), " · ".join(en_parts)


def normalize_model_classification(profile: Dict[str, Any], provider_id: str) -> Dict[str, Any]:
    result = deepcopy(profile)
    old_family_id = str(result.get("family_id") or result.get("model_id") or "").strip()
    family_id, family_name, family_name_en = _family_without_classification_tier(result, provider_id)
    if family_id != old_family_id:
        aliases = list(result.get("legacy_family_ids") or [])
        if old_family_id and old_family_id not in aliases:
            aliases.append(old_family_id)
        result["legacy_family_ids"] = aliases
    result["family_id"] = family_id
    result["family_name"] = family_name or family_id
    result["family_name_en"] = family_name_en or result["family_name"]

    if result.get("node_type") == "video_generation":
        zh_mode, en_mode = _video_mode_from_inputs(result)
    else:
        zh_mode, en_mode = _operation_labels(result)
    route_zh, route_en = _route_labels(str(result.get("model_id") or ""))
    if result.get("node_type") == "image_generation" and route_zh:
        result["variant_name"] = route_zh
        result["variant_name_en"] = route_en
    else:
        result["variant_name"] = " · ".join(item for item in (zh_mode, route_zh) if item)
        result["variant_name_en"] = " · ".join(item for item in (en_mode, route_en) if item)
    result["classification_version"] = 2
    return result


def normalize_model_classifications(models: List[Dict[str, Any]], provider_id: str) -> List[Dict[str, Any]]:
    normalized = [normalize_model_classification(model, provider_id) for model in models]
    groups: Dict[tuple[str, str, str], List[Dict[str, Any]]] = {}
    for model in normalized:
        key = (
            str(model.get("family_id") or "").strip(),
            str(model.get("node_type") or "").strip(),
            str(model.get("variant_name") or "").strip(),
        )
        groups.setdefault(key, []).append(model)
    for group in groups.values():
        if len(group) < 2:
            continue
        has_fast_sibling = any(re.search(r"(?:^|[/_-])fast(?=[/_-]|$)", str(item.get("model_id") or "").lower()) for item in group)
        for model in group:
            zh, en = _variant_identity_label(model, provider_id, has_fast_sibling)
            if zh:
                model["variant_name"] = f"{zh} · {model['variant_name']}"
                model["variant_name_en"] = f"{en} · {model['variant_name_en']}"
    # 只有同一展示名确实覆盖了不同模型时才细化；保留真实 ID 作为最后的可核对区别。
    named: Dict[tuple[str, str, str], List[Dict[str, Any]]] = {}
    for model in normalized:
        key = (str(model.get("family_id") or ""), str(model.get("node_type") or ""), str(model.get("variant_name") or ""))
        named.setdefault(key, []).append(model)
    for items in named.values():
        if len({str(item.get("model_id") or "") for item in items}) < 2:
            continue
        for model in items:
            model_id = str(model.get("model_id") or "").lower()
            operation = str(model.get("operation") or "")
            detail = ""
            detail_en = ""
            if re.search(r"(?:^|[/_-])r2v|reference[-_]to[-_]video", model_id):
                detail, detail_en = "多图参考", "Multiple References"
            elif "start" in model_id and "end" in model_id:
                detail, detail_en = "首尾帧", "First and Last Frame"
            elif re.search(r"(?:^|[/_-])i2v|image[-_]to[-_]video", model_id):
                detail, detail_en = "单图输入", "Single Image Input"
            elif re.search(r"(?:^|[/_-])t2v|text[-_]to[-_]video", model_id):
                detail, detail_en = "文字输入", "Text Input"
            elif "text-to-image" in model_id or "-t2i" in model_id:
                detail, detail_en = "文字输入", "Text Input"
            elif "image-to-image" in model_id or "-i2i" in model_id or "edit" in model_id:
                detail, detail_en = "图片输入", "Image Input"
            if detail and (operation.endswith("video") or str(model.get("node_type")) == "image_generation"):
                model["variant_name"] = f"{model['variant_name']} · {detail}"
                model["variant_name_en"] = f"{model['variant_name_en']} · {detail_en}"
    return normalized


def _profile_parameter(parameter_type: str, field: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    normalized = str(parameter_type or "").strip().upper()
    if normalized in {"STRING", "TEXT", "SIZE"}:
        result: Dict[str, Any] = {"level": "optional", "type": "text"}
        if field.get("defaultValue") not in (None, ""):
            result["default"] = str(field["defaultValue"])
        return result
    if normalized in {"LIST", "SELECT", "COMBO", "SWITCH"}:
        options = []
        for option in field.get("options") or []:
            value = option.get("value") if isinstance(option, dict) else option
            if value is not None and str(value) != "":
                options.append(str(value))
        result: Dict[str, Any] = {"level": "optional", "type": "enum", "options": options}
        if field.get("defaultValue") not in (None, ""):
            result["default"] = str(field["defaultValue"])
        return result
    if normalized in {"BOOLEAN", "BOOL"}:
        return {"level": "optional", "type": "boolean", "default": bool(field.get("defaultValue", False))}
    if normalized in {"INT", "INTEGER"}:
        result = {"level": "optional", "type": "integer"}
    elif normalized in {"FLOAT", "NUMBER", "DOUBLE"}:
        result = {"level": "optional", "type": "number"}
    else:
        return None
    # RunningHub 控件的 step 是滑动步幅，不是 API 的离散取值约束；官方默认值也可能不落在该网格上。
    for source_key, target_key in (("min", "min"), ("max", "max"), ("step", "ui_step")):
        if field.get(source_key) not in (None, ""):
            result[target_key] = field[source_key]
    if field.get("defaultValue") not in (None, ""):
        result["default"] = field["defaultValue"]
    return result


def _byte_limit(value: str, unit: str) -> int:
    amount = max(0.0, float(value))
    multiplier = 1024 if str(unit or "").lower() in {"kb", "kib"} else 1024 * 1024
    return int(amount * multiplier)


def _input_constraints_from_field(field: Dict[str, Any], media_type: str) -> Dict[str, Any]:
    text = " ".join(str(field.get(key) or "") for key in ("label", "description", "tips", "helpText"))
    compact = text.replace("×", "x").replace("*", "x").replace("～", "~").replace("—", "-").replace("–", "-")
    constraints: Dict[str, Any] = {}
    max_chars = re.search(r"(?:最长|不超过|最多)\s*(\d+)\s*个?字符", compact, re.I)
    if max_chars:
        constraints["max_chars"] = int(max_chars.group(1))
    file_limit = re.search(r"(?:单(?:张|个|段|文件)?|文件)?[^。；,，]{0,16}(?:大小|文件大小)?\s*(?:不超过|≤|<=)\s*(\d+(?:\.\d+)?)\s*(Mi?B|Ki?B)", compact, re.I)
    if file_limit:
        constraints["max_bytes"] = _byte_limit(file_limit.group(1), file_limit.group(2))
    duration = re.search(r"(?:时长|长度)\s*(?:为|：|:)?\s*\[?\s*(\d+(?:\.\d+)?)\s*(?:~|-|至|到|,)\s*(\d+(?:\.\d+)?)\s*\]?\s*(?:秒|s)", compact, re.I)
    if duration and media_type in {"video", "audio"}:
        constraints["min_duration_seconds"] = float(duration.group(1))
        constraints["max_duration_seconds"] = float(duration.group(2))
    total_duration = re.search(r"总时长\s*(?:不超过|≤|<=)\s*(\d+(?:\.\d+)?)\s*(?:秒|s)", compact, re.I)
    if total_duration and media_type in {"video", "audio"}:
        constraints["max_total_duration_seconds"] = float(total_duration.group(1))
    minimum_size = re.search(r"(?:像素|尺寸|分辨率)\s*(?:不小于|至少|≥|>=)\s*(\d+)\s*x\s*(\d+)", compact, re.I)
    if minimum_size and media_type in {"image", "video"}:
        constraints["min_width"] = int(minimum_size.group(1))
        constraints["min_height"] = int(minimum_size.group(2))
    axis_range = re.search(r"宽\s*/?\s*高[^。；]{0,12}(?:介于|范围(?:为|是)?)\s*(\d+)\s*px?\s*(?:~|-|至|到)\s*(\d+)\s*px?", compact, re.I)
    if axis_range and media_type in {"image", "video"}:
        constraints.update({
            "min_width": int(axis_range.group(1)), "min_height": int(axis_range.group(1)),
            "max_width": int(axis_range.group(2)), "max_height": int(axis_range.group(2)),
        })
    aspect_ratio = re.search(r"比例\s*(?:不超过|≤|<=)\s*(\d+(?:\.\d+)?)\s*:\s*1", compact, re.I)
    if aspect_ratio and media_type in {"image", "video"}:
        constraints["max_aspect_ratio"] = float(aspect_ratio.group(1))
    return constraints


def _standard_parameter_key(field_key: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", str(field_key or "").strip().lower())
    return {
        "aspectratio": "aspect_ratio",
        "ratio": "aspect_ratio",
        "duration": "duration",
        "seconds": "duration",
        "resolution": "resolution",
        "generateaudio": "generate_audio",
        "returnlastframe": "return_last_frame",
        "seed": "seed",
        "quality": "quality",
        "count": "count",
        "n": "count",
    }.get(normalized, str(field_key or "").strip())


def _runninghub_operation(output_type: str, media_fields: List[Dict[str, Any]], model_id: str = "") -> str:
    output = str(output_type or "").strip().lower()
    lower = str(model_id or "").strip().lower().replace("_", "-")
    media = {
        str(item.get("media_type") or "").strip()
        for item in media_fields
        if str(item.get("media_type") or "").strip() != "text" and item.get("required") is True
    }
    declared_media = {
        str(item.get("media_type") or "").strip()
        for item in media_fields
        if str(item.get("media_type") or "").strip() not in {"", "text"}
    }
    declared_roles = {
        _runninghub_media_role(str(item.get("field_key") or ""), "", str(item.get("media_type") or "").strip())
        for item in media_fields
        if str(item.get("media_type") or "").strip() not in {"", "text"}
    }
    required_roles = {
        _runninghub_media_role(str(item.get("field_key") or ""), "", str(item.get("media_type") or "").strip())
        for item in media_fields
        if str(item.get("media_type") or "").strip() not in {"", "text"} and item.get("required") is True
    }
    if output == "image":
        if lower.startswith("topazlabs-image-"):
            return "image_enhancement"
        if any(token in lower for token in ("image-to-image", "image-edit", "/edit", " image edit")):
            return "image_to_image"
        return "image_to_image" if "image" in media else "text_to_image"
    if output == "video":
        if lower.startswith("topazlabs-video-"):
            return "video_enhancement"
        if re.search(r"(?:^|[/_-])effects(?:$|[/_-])", lower):
            return "video_effects"
        if "transition" in lower:
            return "video_transition"
        if "motion-control" in lower or lower.endswith("-motion"):
            return "motion_control"
        if "lip-sync" in lower:
            return "lip_sync"
        if "ai-avatar" in lower:
            return "avatar_video"
        if "subtitle-erase" in lower:
            return "subtitle_erase"
        if "video-translate" in lower:
            return "video_translation"
        if lower in {"rh-video-upscaler", "rh-video-fps-increaser"}:
            return "video_enhancement"
        if any(token in lower for token in ("video-to-video", "video-edit", "edit-video", "video-restyling")):
            return "video_to_video"
        if any(token in lower for token in ("video-extend", "video-extension", "video-continuation")):
            return "video_extend"
        if "video" in declared_media or "audio" in declared_media or {"source_video", "reference_audio"} & declared_roles:
            return "multimodal_to_video"
        if {"first_frame", "last_frame"}.issubset(required_roles):
            return "start_end_to_video"
        if "image" in declared_media or {"reference", "first_frame", "last_frame"} & declared_roles:
            return "image_to_video"
        return "text_to_video"
    if output == "audio":
        if "voice-clone" in lower:
            return "voice_clone"
        if "voice-design" in lower:
            return "voice_design"
        return "audio_to_audio" if "audio" in media else "text_to_audio"
    return "compatible"


def _runninghub_family_mode(
    model_id: str,
    node_type: str,
    operation: str,
    display_name: str,
) -> Dict[str, str]:
    normalized = str(model_id or "").strip()
    canonical = re.sub(r"\s*/\s*", "/", normalized).replace("_", "-")
    lower = canonical.lower()
    operation_pattern = (
        r"(?:/|[- ])(?:text-to-image|image-to-image|image-edit|edit|text-to-video|image-to-video|"
        r"reference-to-video|ref-to-video|refrence-to-video|start-end-to-video|start-to-end|"
        r"video-to-video|video-edit|edit-video|video-extend|video-extension|video-continuation|"
        r"multimodal-video|multimodal-reference-to-video|transition|effects)(?:[-/ ()\[\].>0-9a-z]*)?$"
    )
    family_base = re.sub(operation_pattern, "", canonical, flags=re.I).strip(" -/") or canonical
    if re.fullmatch(r"grok-[34]-image-to-image", lower):
        family_base = canonical[:-len("-to-image")]

    visible_name = str(display_name or normalized).strip()
    visible_operation = re.search(
        r"(?:文生图|图生图|图片编辑|文生视频|图生视频|多模态参考生视频|参考生视频|首尾帧生视频|"
        r"视频编辑|视频续写|视频延长|文生音频|文本转语音|声音克隆|音色设计|"
        r"text[- ]to[- ]image|image[- ]to[- ]image|text[- ]to[- ]video|image[- ]to[- ]video|"
        r"multimodal[- ]reference[- ]to[- ]video|reference[- ]to[- ]video|video[- ]to[- ]video|"
        r"video[- ]edit|video[- ]extend)",
        visible_name,
        flags=re.I,
    )
    neutral_name = visible_name[:visible_operation.start()].rstrip(" -/（(") if visible_operation else visible_name
    neutral_name = neutral_name or family_base.rsplit("/", 1)[-1].replace("-", " ").title()
    if family_base == "grok-image":
        neutral_name = "全能图片X（Grok Image）"
    elif family_base == "xai/grok-imagine-image":
        neutral_name = "全能图片X（Grok Imagine）"
    variant_name = visible_name[visible_operation.start():].lstrip(" -/") if visible_operation else visible_name
    variant_id = re.sub(r"[^a-z0-9.]+", "-", lower).strip("-") or operation
    result = {
        "family_base": family_base,
        "family_name": neutral_name,
        "family_name_en": "",
        "variant_id": variant_id,
        "variant_name": variant_name,
        "variant_name_en": canonical,
    }

    # RunningHub 目录有时只给中文展示名，仍按展示名保持同一模型家族。
    if re.search(r"全能视频\s*s|(?:^|\b)sora(?:\b|[-/])", visible_name, flags=re.I):
        assign_family = ("sora", "Sora", "Sora")
        result.update({"family_base": assign_family[0], "family_name": assign_family[1], "family_name_en": assign_family[2]})
    elif re.search(r"万相|\bwan\b", visible_name, flags=re.I):
        result.update({"family_base": "wan", "family_name": "Wan", "family_name_en": "Wan"})

    def assign(family_base: str, family_name: str, family_name_en: str, variant_name: str = "", variant_name_en: str = "") -> None:
        result.update({
            "family_base": family_base,
            "family_name": family_name,
            "family_name_en": family_name_en,
            "variant_name": variant_name or result["variant_name"],
            "variant_name_en": variant_name_en or result["variant_name_en"],
        })

    if lower.startswith("minimax/"):
        mode_zh = ""
        mode_en = ""
        speech = re.search(r"speech-([0-9.]+)-(hd|turbo)$", lower)
        if speech:
            quality_zh = "高清" if speech.group(2) == "hd" else "极速"
            quality_en = "HD" if speech.group(2) == "hd" else "Turbo"
            mode_zh = f"Speech {speech.group(1)} · {quality_zh}"
            mode_en = f"Speech {speech.group(1)} · {quality_en}"
        elif lower.endswith("voice-clone"):
            mode_zh, mode_en = "声音克隆", "Voice Clone"
        elif lower.endswith("voice-design"):
            mode_zh, mode_en = "音色设计", "Voice Design"
        elif "/music-" in lower:
            music_mode = lower.split("/music-", 1)[1]
            music_names = {
                "cover": ("音乐翻唱", "Music Cover"),
                "cover-preprocess": ("翻唱前处理", "Cover Preprocess"),
            }
            mode_zh, mode_en = music_names.get(music_mode, (f"Music {music_mode}", f"Music {music_mode}"))
        assign("minimax", "MiniMax", "MiniMax", mode_zh, mode_en)
    elif node_type == "video_generation" and re.match(r"^minimax-h3(?:[- /]|$)", lower):
        assign("minimax-h3", "MiniMax H3", "MiniMax H3")
    elif node_type == "video_generation" and re.match(r"^(?:laohu[-_/])?(?:video[-_/])?grok(?:[-_/]|$)|^laohu-video-gk(?:[-_/]|$)", lower):
        assign("grok", "Grok", "Grok")
    elif lower.startswith("suno-"):
        suno = re.match(r"suno-(single|custom)-v(.+)$", lower)
        if suno:
            action_zh = "灵感生成" if suno.group(1) == "single" else "自定义生成"
            action_en = "Simple Generation" if suno.group(1) == "single" else "Custom Generation"
            assign("suno", "Suno", "Suno", f"V{suno.group(2)} · {action_zh}", f"V{suno.group(2)} · {action_en}")
        elif lower == "suno-lyrics":
            assign("suno", "Suno", "Suno", "歌词生成", "Lyrics Generation")
    elif lower.startswith("topazlabs-image-"):
        assign("topazlabs-image", "Topaz 图片增强", "Topaz Image Enhancement")
    elif lower.startswith("topazlabs-video-"):
        assign("topazlabs-video", "Topaz 视频增强", "Topaz Video Enhancement")
    elif lower.startswith("midjourney-") and node_type == "image_generation":
        mode = re.sub(r"^midjourney-text-to-image-", "", lower)
        assign("midjourney", "Midjourney", "Midjourney", f"文生图 · {mode.upper()}", f"Text to Image · {mode.upper()}")
    else:
        product_patterns = (
            (r"^pixverse[-/](v[0-9.]+|c1)", "pixverse-{0}", "PixVerse {0}"),
            (r"^hailuo-(02|2[.]3|h3)", "hailuo-{0}", "海螺 {0}"),
            (r"^skyreels-(v[0-9.]+)", "skyreels-{0}", "SkyReels {0}"),
            # Wan/万相的版本是运行模式，不拆成 Wan 2.x、Wan 3.x 多个模型家族。
            (r"^wan-(2[.][0-9]+|3[.][0-9]+)(?:[-/].*)?$", "wan", "Wan"),
            # 全能视频 S 的真实调用 ID 属于 Sora 系列，S 保留在运行模式信息中。
            (r"^(sora|omni-video-s)(?:[-/].*)?$", "sora", "Sora"),
            (r"^qwen-image-(2[.][0-9]+(?:-pro)?|3[.][0-9]+(?:-pro)?)", "qwen-image-{0}", "Qwen Image {0}"),
        )
        for pattern, family_template, name_template in product_patterns:
            match = re.search(pattern, lower)
            if not match:
                continue
            version = match.group(1)
            assign(family_template.format(version), name_template.format(version.upper()), name_template.format(version.upper()))
            break
        else:
            seedance = re.search(r"seedance[- ]?v?([0-9]+(?:[.][0-9]+)?)", lower)
            veo = re.search(r"google/veo(3[.]1)", lower)
            vidu = re.search(r"^vidu-.*-(q[23])(?:-|$)", lower)
            kling = re.search(r"^kling-(?:video-)?(o[13]|v?2[.][56]|v?3(?:[.]0)?)", lower)
            luma = re.search(r"^luma uni-(1(?:-max)?)", lower)
            if seedance:
                version = seedance.group(1)
                assign(f"seedance-{version}", f"Seedance {version}", f"Seedance {version}")
            elif veo:
                assign("google-veo3.1", "Veo 3.1", "Veo 3.1")
            elif vidu:
                version = vidu.group(1).upper()
                assign(f"vidu-{version.lower()}", f"Vidu {version}", f"Vidu {version}")
            elif kling:
                version = kling.group(1).lstrip("v").upper()
                if version == "3":
                    version = "3.0"
                assign(f"kling-{version.lower()}", f"可灵 {version}", f"Kling {version}")
            elif luma:
                version = luma.group(1)
                assign(f"luma-uni-{version}", f"Luma Uni {version}", f"Luma Uni {version}")

    # 版本档次是用户做选择时需要的信息：保留 Fast/Mini/Pro/Lite/Flash 等
    # 原始字母标识，同时给出中文含义，避免只剩“视频编辑”这类模糊能力名。
    edition = re.search(r"(?:^|[-_/ .])((?:fast|mini|pro|lite|flash|turbo|plus|max|standard))(?:$|[-_/ .])", lower)
    if edition:
        edition_en = edition.group(1).capitalize()
        edition_zh = {
            "fast": "快速版", "mini": "Mini 版", "pro": "Pro 版", "lite": "Lite 版",
            "flash": "Flash 版", "turbo": "Turbo 版", "plus": "Plus 版", "max": "Max 版",
            "standard": "标准版",
        }.get(edition.group(1), edition_en)
        current = str(result.get("variant_name") or "").strip()
        if edition_en.lower() not in current.lower() and edition_zh not in current:
            result["variant_name"] = f"{current} · {edition_zh}" if current else edition_zh
            result["variant_name_en"] = f"{result.get('variant_name_en') or ''} · {edition_en}".strip(" ·")

    if not result["family_name_en"]:
        result["family_name_en"] = str(result["family_base"] or normalized).replace("/", " ").replace("-", " ").title()
    return result


def _runninghub_media_role(field_key: str, operation: str, media_type: str) -> str:
    key = str(field_key or "").strip().lower()
    if media_type == "image":
        if any(token in key for token in ("lastframe", "last_frame", "endframe", "end_frame")):
            return "last_frame"
        if operation == "image_to_video" or any(token in key for token in ("firstframe", "first_frame")):
            return "first_frame"
        return "reference"
    if media_type == "video":
        return "source_video"
    if media_type == "audio":
        return "reference_audio"
    return "prompt"


def runninghub_profile_from_registry_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert one official RunningHub registry entry into the canvas contract."""
    item = item if isinstance(item, dict) else {}
    model_id = str(item.get("name_en") or item.get("id") or item.get("endpoint") or "").strip()
    output_type = str(item.get("output_type") or item.get("outputType") or "").strip().lower()
    node_type = {
        "image": "image_generation",
        "video": "video_generation",
        "audio": "audio_generation",
        "text": "text_generation",
        "chat": "text_generation",
    }.get(output_type, "")
    if node_type == "audio_generation" and _is_music_model_id(model_id):
        node_type = "music_generation"
    if not model_id or not node_type:
        raise ModelCapabilityError("RunningHub 注册表条目缺少模型 ID 或输出类型")
    params = item.get("params") if isinstance(item.get("params"), list) else []
    media_fields: List[Dict[str, Any]] = []
    inputs: Dict[str, Dict[str, Any]] = {}
    parameters: Dict[str, Dict[str, Any]] = {}
    request_mapping: Dict[str, str] = {}
    for field in params:
        if not isinstance(field, dict):
            continue
        field_key = str(field.get("fieldKey") or field.get("name") or "").strip()
        field_type = str(field.get("type") or "").strip().upper()
        if not field_key:
            continue
        media_type = {"IMAGE": "image", "VIDEO": "video", "AUDIO": "audio"}.get(field_type)
        if field_type in {"STRING", "TEXT"} and field_key.lower() in {"prompt", "text", "content", "input"}:
            media_type = "text"
        if media_type:
            media_fields.append({"field_key": field_key, "media_type": media_type, "required": field.get("required") is True})
            role = _runninghub_media_role(field_key, "", media_type)
            key = role
            if role == "reference" and key in inputs:
                key = f"reference_{len([name for name in inputs if name.startswith('reference')]) + 1}"
            max_inputs = field.get("maxInputNum")
            try:
                max_count = max(1, int(max_inputs)) if max_inputs not in (None, "") else (10 if field.get("multipleInputs") else 1)
            except (TypeError, ValueError):
                max_count = 1
            inputs[key] = {
                "media_type": media_type,
                "min": 1 if field.get("required") is True else 0,
                "max": max_count,
                "role": key,
                "label": str(field.get("label") or field.get("description") or field_key),
                "source_field": field_key,
                **_input_constraints_from_field(field, media_type),
            }
            request_mapping[key] = field_key
            continue
        parameter = _profile_parameter(field_type, field)
        if parameter:
            parameter["source_field"] = field_key
            label = field.get("label") or field.get("description")
            if label:
                parameter["label"] = str(label)
            parameter_key = _standard_parameter_key(field_key)
            parameters[parameter_key] = parameter
            request_mapping[parameter_key] = field_key
    operation = _runninghub_operation(output_type, media_fields, model_id)
    if node_type == "music_generation":
        operation = "music_to_music" if "audio" in {item.get("media_type") for item in media_fields} else "music"
    if node_type == "text_generation":
        operation = "chat"
        if not inputs:
            inputs = {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt", "label": "prompt", "source_field": "messages"}}
            request_mapping["prompt"] = "messages"
        documented = {
            "temperature": {"level": "optional", "type": "number", "min": 0, "max": 2, "default": 1},
            "top_p": {"level": "optional", "type": "number", "min": 0, "max": 1, "default": 1},
            "presence_penalty": {"level": "advanced", "type": "number", "min": -2, "max": 2, "default": 0},
            "frequency_penalty": {"level": "advanced", "type": "number", "min": -2, "max": 2, "default": 0},
            "max_output_tokens": {"level": "optional", "type": "integer", "min": 1, "default": 2048},
            "reasoning_effort": {"level": "advanced", "type": "enum", "options": ["none", "low", "medium", "high"], "default": "none"},
        }
        parameters = {**documented, **parameters}
        request_mapping.update({
            "temperature": "temperature", "top_p": "top_p",
            "presence_penalty": "presence_penalty", "frequency_penalty": "frequency_penalty",
            "max_output_tokens": "max_tokens", "reasoning_effort": "reasoning_effort",
        })
    normalized_inputs: Dict[str, Dict[str, Any]] = {}
    normalized_mapping: Dict[str, str] = {}
    for key, spec in inputs.items():
        source_field = str(spec.get("source_field") or "")
        role = _runninghub_media_role(source_field, operation, spec["media_type"])
        normalized_key = role if role not in normalized_inputs else key
        normalized_spec = deepcopy(spec)
        normalized_spec["role"] = role
        normalized_inputs[normalized_key] = normalized_spec
        normalized_mapping[normalized_key] = request_mapping.get(key) or source_field
    inputs = normalized_inputs
    request_mapping = {**{key: value for key, value in request_mapping.items() if key in parameters}, **normalized_mapping}
    display_name = str(item.get("name_cn") or item.get("display_name") or item.get("name_en") or model_id).strip()
    family_mode = _runninghub_family_mode(model_id, node_type, operation, display_name)
    family_id = "runninghub-" + re.sub(r"[^a-z0-9.]+", "-", family_mode["family_base"].lower()).strip("-")
    has_confirmed_field_schema = bool(request_mapping) or node_type == "text_generation"
    return {
        "model_id": model_id,
        "family_id": family_id or model_id,
        "family_name": family_mode["family_name"],
        "family_name_en": family_mode["family_name_en"],
        "display_name": display_name,
        "variant_id": family_mode["variant_id"],
        "variant_name": family_mode["variant_name"],
        "variant_name_en": family_mode["variant_name_en"],
        "node_type": node_type,
        "operation": operation,
        "status": "confirmed" if has_confirmed_field_schema else "pending",
        "readiness": "ready" if has_confirmed_field_schema else "needs_profile",
        "runnable": has_confirmed_field_schema,
        "version": 1,
        "evidence_level": "official_schema",
        "inputs": inputs,
        "parameters": parameters,
        "request_mapping": request_mapping,
        "output": {"media_type": output_type, "min": 1, "async": True},
        "platform": {"endpoint": str(item.get("endpoint") or "").strip()},
        **({} if has_confirmed_field_schema else {
            "note": "当前只同步到 RunningHub 端点名，尚未同步字段 Schema；在补齐字段定义前禁止运行。",
        }),
    }


def _ai_money_video_profile(model_id: str) -> Dict[str, Any]:
    normalized = normalize_laohu_model_id(model_id)
    lower = normalized.lower()
    if lower == "animate-motion-transfer":
        return {
            "model_id": normalized,
            "family_id": "ai-money-animate-motion-transfer",
            "family_name": "Animate",
            "family_name_en": "Animate",
            "display_name": normalized,
            "variant_id": "motion-transfer",
            "variant_name": "动作迁移",
            "variant_name_en": "Motion Transfer",
            "node_type": "video_generation",
            "operation": "motion_transfer",
            "status": "confirmed", "readiness": "ready", "runnable": True,
            "version": 1, "evidence_level": "official_documented",
            "inputs": {
                "reference_image": {"media_type": "image", "min": 1, "max": 1, "role": "reference_image"},
                "motion_video": {"media_type": "video", "min": 1, "max": 1, "role": "motion_video"},
            },
            "parameters": {
                "resolution": {"level": "optional", "type": "enum", "options": ["480p", "720p", "1080p"], "default": "720p", "source_field": "metadata.resolution"},
                "ratio": {"level": "optional", "type": "enum", "options": ["adaptive", "16:9", "9:16", "1:1"], "default": "adaptive", "source_field": "metadata.ratio"},
                "frame_rate": {"level": "optional", "type": "integer", "options": [24, 30], "default": 30, "source_field": "metadata.frame_rate"},
                "pose_method": {"level": "advanced", "type": "enum", "options": ["vitpose"], "default": "vitpose", "source_field": "metadata.pose_method"},
            },
            "request_mapping": {"reference_image": "images", "motion_video": "metadata.video_url", "resolution": "metadata.resolution", "ratio": "metadata.ratio", "frame_rate": "metadata.frame_rate", "pose_method": "metadata.pose_method"},
            "output": {"media_type": "video", "min": 1, "max": 1, "async": True},
            "platform": {"endpoint": "/v1/video/generations"},
        }
    is_wan_3_prime = bool(re.fullmatch(r"wan-3\.0-(?:global-)?prime-(?:i2v|r2v)", lower))
    if lower in {"fashvsr_video_upscale", "fashvsr-video-upscale"}:
        operation = "video_upscale"
    elif lower == "laohu-upscaler":
        operation = "video_upscale"
    elif lower.endswith(("-start-end", "-start-to-end")):
        operation = "start_end_to_video"
    elif re.search(r"-(r2v|reference-to-video)(?:-|$)", lower):
        operation = "reference_to_video"
    elif re.search(r"-(v2v|edit|motion)(?:-|$)", lower):
        operation = "video_to_video"
    elif lower.endswith("-short-play"):
        operation = "script_to_video"
    elif lower.endswith(("-fl2va-audio-drive-fast", "-ref2va-audio-drive-fast")):
        operation = "audio_driven_video"
    elif re.search(r"-t2v(?:-|$)", lower):
        operation = "text_to_video"
    elif re.search(r"-i2v(?:-|$)", lower):
        operation = "image_to_video"
    elif lower.endswith("-multi"):
        operation = "multimodal_to_video"
    elif lower.startswith("laohu-video-"):
        operation = "multimodal_to_video" if "omni" in lower else "compatible_video"
    elif lower in {"kling-elements-advanced", "kling-lip-sync-identify-face", "kling-lip-sync-video", "midjourney-video"}:
        operation = "special_video"
    elif "draft-enhance" in lower:
        operation = "draft_enhance"
    else:
        raise ModelCapabilityError(f"不是已确认的 laohu 视频模型：{model_id}")
    base = re.sub(r"-(t2v|i2v|multi|r2v|reference-to-video|start-end|start-to-end|v2v|edit|motion|short-play)$", "", lower)
    family_patterns = (
        (r"^wan-3\.0-", "wan-3.0"),
        (r"^seedance-2\.5-", "seedance-2.5"),
        (r"^seedance-2\.0-", "seedance-2.0"),
        (r"^flux-3-video-", "flux-3-video"),
        (r"^hailuo-h3-", "hailuo-h3"),
        (r"^hailuo-2\.3-", "hailuo-2.3"),
        (r"^happyhorse-1\.1-", "happyhorse-1.1"),
        (r"^kling-o3-", "kling-o3"),
        (r"^kling-v3(?:\.0)?-", "kling-v3.0"),
        (r"^minimax-h3-ow-", "minimax-h3"),
        (r"^fashvsr[_-]", "fashvsr"),
        (r"^vidu-q3-", "vidu-q3"),
        (r"^wan-2\.7-spicy-", "wan-2.7-spicy"),
        (r"^laohu-video-v31-", "veo3.1"),
        (r"^laohu-video-g-omni-", "veo3.1"),
        (r"^laohu-video-gk-", "grok-video"),
    )
    family_name = next((name for pattern, name in family_patterns if re.search(pattern, lower)), base)
    if lower in {"fashvsr_video_upscale", "fashvsr-video-upscale"}:
        family_name = "FashVSR"
    elif lower == "laohu-upscaler":
        family_name = "upscaler"
    elif lower == "midjourney-video":
        family_name = "midjourney"
    family_id = "ai-money-" + re.sub(r"[^a-z0-9]+", "-", family_name.lower()).strip("-")
    inputs: Dict[str, Dict[str, Any]] = {
        "prompt": {
            "media_type": "text", "min": 1, "max": 1, "role": "prompt",
            **({"max_chars": 20000} if is_wan_3_prime else {}),
        }
    }
    mapping = {"prompt": "prompt"}
    if operation == "video_upscale":
        if lower in {"fashvsr_video_upscale", "fashvsr-video-upscale"}:
            inputs = {
                "source_video": {
                    "media_type": "video", "min": 1, "max": 1, "role": "source_video",
                    "min_duration_seconds": 3, "max_duration_seconds": 15,
                    "max_pixels": 854 * 480, "label": "480P 输入视频",
                },
            }
            mapping = {"source_video": "metadata.video_url"}
        else:
            inputs = {"source_video": {"media_type": "video", "min": 1, "max": 1, "role": "source_video"}}
            mapping = {"source_video": "metadata.content"}
    elif operation == "start_end_to_video":
        inputs["first_frame"] = {"media_type": "image", "min": 1, "max": 1, "role": "first_frame"}
        inputs["last_frame"] = {"media_type": "image", "min": 1, "max": 1, "role": "last_frame"}
        mapping.update({"first_frame": "images", "last_frame": "images"})
    elif operation == "reference_to_video":
        if is_wan_3_prime:
            inputs.update({
                "reference": {"media_type": "image", "min": 0, "max": 10, "role": "reference"},
                "source_video": {"media_type": "video", "min": 0, "max": 5, "role": "source_video"},
                "reference_audio": {"media_type": "audio", "min": 0, "max": 5, "role": "reference_audio"},
            })
            mapping.update({
                "reference": "metadata.content",
                "source_video": "metadata.content",
                "reference_audio": "metadata.content",
            })
        else:
            inputs["reference"] = {"media_type": "image", "min": 1, "max": 9, "role": "reference"}
            mapping["reference"] = "images"
    elif operation == "video_to_video":
        inputs["source_video"] = {"media_type": "video", "min": 1, "max": 1, "role": "source_video"}
        mapping["source_video"] = "metadata.video_url"
    elif operation == "image_to_video":
        inputs["first_frame"] = {"media_type": "image", "min": 1, "max": 1, "role": "first_frame"}
        if lower.startswith("seedance-2.5-") or is_wan_3_prime:
            inputs["last_frame"] = {"media_type": "image", "min": 0, "max": 1, "role": "last_frame"}
            mapping["last_frame"] = "images"
        mapping["first_frame"] = "images"
    elif operation in {"multimodal_to_video", "compatible_video"}:
        inputs.update({
            "reference": {"media_type": "image", "min": 0, "max": 10, "role": "reference"},
            "source_video": {"media_type": "video", "min": 0, "max": 5, "role": "source_video"},
            "reference_audio": {"media_type": "audio", "min": 0, "max": 5, "role": "reference_audio"},
        })
        mapping.update({"reference": "metadata.content", "source_video": "metadata.content", "reference_audio": "metadata.content"})
    elif lower.endswith(("-fl2va-audio-drive-fast", "-ref2va-audio-drive-fast")):
        inputs = {
            "prompt": {"media_type": "text", "min": 0, "max": 1, "role": "prompt"},
            "first_frame": {"media_type": "image", "min": 1, "max": 1, "role": "first_frame"},
            "reference_audio": {"media_type": "audio", "min": 1, "max": 1, "role": "reference_audio"},
        }
        mapping = {"prompt": "prompt", "first_frame": "images", "reference_audio": "metadata.audio_urls"}
    parameters = {
        "duration": {"level": "optional", "type": "integer", "min": 1, "max": 60, "default": 5, "source_field": "seconds"},
        "resolution": {"level": "optional", "type": "enum", "options": ["720p", "1080p", "2k"], "source_field": "metadata.resolution"},
        "aspect_ratio": {"level": "optional", "type": "enum", "options": ["1:1", "16:9", "9:16", "4:3", "3:4"], "source_field": "metadata.ratio"},
        "generate_audio": {"level": "optional", "type": "boolean", "default": False, "source_field": "metadata.generate_audio"},
        "return_last_frame": {"level": "optional", "type": "boolean", "default": False, "source_field": "metadata.return_last_frame"},
        "seed": {"level": "advanced", "type": "integer", "min": 0, "max": 4294967295, "source_field": "metadata.seed"},
    }
    if is_wan_3_prime:
        parameters = {
            "duration": {"level": "optional", "type": "enum", "options": [-1, *range(2, 31)], "default": 5, "source_field": "seconds"},
            "resolution": {"level": "optional", "type": "enum", "options": ["480p", "720p", "1080p"], "default": "720p", "source_field": "metadata.resolution"},
            "aspect_ratio": {"level": "optional", "type": "enum", "options": ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16"], "default": "adaptive", "source_field": "metadata.ratio"},
            "generate_audio": {"level": "optional", "type": "boolean", "default": True, "source_field": "metadata.generate_audio"},
            "seed": {"level": "advanced", "type": "integer", "min": 0, "max": 2147483647, "source_field": "metadata.seed"},
        }
    elif lower.startswith("seedance-2.5-"):
        if operation == "multimodal_to_video":
            inputs["reference"]["max"] = 30
            inputs["source_video"]["max"] = 10
            inputs["reference_audio"]["max"] = 10
        parameters = {
            "duration": {"level": "optional", "type": "enum", "options": [-1, *range(4, 31)], "default": 5, "source_field": "seconds"},
            "resolution": {"level": "optional", "type": "enum", "options": ["480p", "720p", "1080p", "2k", "4k", "native1080p"], "default": "720p", "source_field": "metadata.resolution"},
            "aspect_ratio": {"level": "optional", "type": "enum", "options": ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"], "default": "adaptive" if operation == "image_to_video" else "16:9", "source_field": "metadata.ratio"},
            "generate_audio": {"level": "optional", "type": "boolean", "default": True, "source_field": "metadata.generate_audio"},
            "return_last_frame": {"level": "optional", "type": "boolean", "default": False, "source_field": "metadata.return_last_frame"},
        }
    elif lower in {"fashvsr_video_upscale", "fashvsr-video-upscale"}:
        parameters = {}
    elif lower.startswith("minimax-h3-ow-"):
        parameters = {
            "duration": {"level": "optional", "type": "enum", "options": [5, 10, 15], "default": 5, "source_field": "seconds"},
            "resolution": {"level": "optional", "type": "enum", "options": ["480p", "720p"], "default": "720p", "source_field": "metadata.resolution"},
            "aspect_ratio": {"level": "optional", "type": "enum", "options": ["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"], "default": "16:9", "source_field": "metadata.ratio"},
        }
    elif lower.startswith("laohu-video-v31-"):
        inputs = {
            "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
            "reference": {"media_type": "image", "min": 0, "max": 3, "role": "reference"},
        }
        mapping = {"prompt": "prompt", "reference": "images"}
        parameters = {
            "duration": {"level": "optional", "type": "enum", "options": [10], "default": 10, "source_field": "seconds"},
            "aspect_ratio": {"level": "optional", "type": "enum", "options": ["16:9", "9:16"], "default": "16:9", "source_field": "metadata.ratio"},
        }
    elif lower.startswith("laohu-video-gk-v15"):
        inputs = {
            "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
            "reference": {"media_type": "image", "min": 0, "max": 7, "role": "reference"},
        }
        mapping = {"prompt": "prompt", "reference": "images"}
    elif lower.startswith("laohu-video-g-omni-"):
        inputs = {
            "prompt": {"media_type": "text", "min": 0, "max": 1, "role": "prompt"},
            "reference": {"media_type": "image", "min": 0, "max": 16, "role": "reference"},
            "source_video": {"media_type": "video", "min": 0, "max": 1, "role": "source_video"},
        }
        mapping = {"prompt": "prompt", "reference": "images", "source_video": "metadata.video_url"}
    elif operation == "video_upscale" and lower not in {"fashvsr_video_upscale", "fashvsr-video-upscale"}:
        parameters = {
            "resolution": {"level": "optional", "type": "enum", "options": ["720p", "1080p", "2k", "4k"], "default": "1080p", "source_field": "metadata.resolution"},
        }
    elif operation == "draft_enhance":
        parameters["draft_cache"] = {"level": "required", "type": "text", "source_field": "metadata.draft_cache"}
    elif operation == "script_to_video":
        parameters["script_name"] = {"level": "optional", "type": "text", "source_field": "metadata.script_name"}
    mapping.update({
        key: str(spec.get("source_field") or key)
        for key, spec in parameters.items()
    })
    return {
        "model_id": normalized, "family_id": family_id,
        "family_name": "FashVSR" if lower in {"fashvsr_video_upscale", "fashvsr-video-upscale"} else family_name.replace("-", " ").title(),
        "display_name": normalized, "variant_id": operation, "node_type": "video_generation", "operation": operation,
        "status": "confirmed", "readiness": "ready", "runnable": True, "version": 1,
        "evidence_level": "official_documented", "inputs": inputs, "parameters": parameters,
        "request_mapping": mapping, "output": {"media_type": "video", "min": 1, "max": 1, "async": True},
        "platform": {"endpoint": "/v1/video/generations" if lower in {"fashvsr_video_upscale", "fashvsr-video-upscale"} else "/v1/videos"},
        **({"requires_any_media": ["image", "video", "audio"]} if is_wan_3_prime and operation == "reference_to_video" else {}),
    }


def _ai_money_text_family_mode(model_id: str) -> Dict[str, str]:
    normalized = str(model_id or "").strip()
    lower = normalized.lower()
    patterns = (
        (r"^(bytedance/doubao-seed-2\.0)(?:-(code|lite|mini|pro))?$", "豆包 Seed 2.0", "Doubao Seed 2.0"),
        (r"^(bytedance/doubao-seed-2\.1)(?:-(pro|turbo))?$", "豆包 Seed 2.1", "Doubao Seed 2.1"),
        (r"^(deepseek/deepseek-v4)(?:-(flash|pro))?$", "DeepSeek V4", "DeepSeek V4"),
        (r"^(glm-5)(?:-(turbo))?$", "GLM 5", "GLM 5"),
        (r"^(qwen/qwen3\.(?:6|7|8))(?:-(flash|max|max-preview|plus))?$", "Qwen 3", "Qwen 3"),
    )
    mode_names = {
        "code": ("代码", "Code"),
        "lite": ("轻量", "Lite"),
        "mini": ("迷你", "Mini"),
        "pro": ("专业", "Pro"),
        "turbo": ("极速", "Turbo"),
        "flash": ("闪速", "Flash"),
        "max": ("Max", "Max"),
        "max-preview": ("Max 预览", "Max Preview"),
        "plus": ("增强", "Plus"),
        "default": ("默认", "Default"),
    }
    for pattern, family_name, family_name_en in patterns:
        match = re.fullmatch(pattern, lower)
        if not match:
            continue
        family_base = match.group(1)
        mode = match.group(2) or "default"
        if family_base.startswith("qwen/qwen3."):
            version = family_base.rsplit("qwen3.", 1)[-1]
            family_name = f"Qwen 3.{version}"
            family_name_en = family_name
        variant_name, variant_name_en = mode_names[mode]
        family_id = "ai-money-" + re.sub(r"[^a-z0-9]+", "-", family_base).strip("-")
        return {
            "family_id": family_id,
            "family_name": family_name,
            "family_name_en": family_name_en,
            "variant_id": mode,
            "variant_name": variant_name,
            "variant_name_en": variant_name_en,
        }
    safe_id = re.sub(r"[^a-z0-9]+", "-", lower).strip("-") or "model"
    return {
        "family_id": f"ai-money-{safe_id}",
        "family_name": normalized.rsplit("/", 1)[-1],
        "family_name_en": normalized.rsplit("/", 1)[-1],
        "variant_id": "default",
        "variant_name": "默认",
        "variant_name_en": "Default",
    }


def _ai_money_flowmusic_profile(model_id: str) -> Dict[str, Any]:
    action = str(model_id or "").strip().lower().removeprefix("flowmusic-")
    action_labels = {
        "generation": ("音乐生成", "Music generation"),
        "lyrics": ("歌词生成", "Lyrics generation"),
        "extend": ("音乐续写", "Extend music"),
        "replace": ("片段替换", "Replace section"),
        "cover": ("风格翻唱", "Cover music"),
        "stems": ("分离音轨", "Separate stems"),
        "upload-audio": ("导入音频", "Upload audio"),
        "download-audio": ("导出音频", "Download audio"),
        "video-clip": ("音乐视频", "Music video"),
    }
    if action not in action_labels:
        raise ModelCapabilityError(f"未知 FlowMusic 操作：{model_id}")
    family_id = "ai-money-flowmusic-lyria-3-5"
    family_name, family_name_en = "FlowMusic · Lyria 3.5", "FlowMusic · Lyria 3.5"
    variant_name, variant_name_en = action_labels[action]
    prompt_input = {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}
    inputs: Dict[str, Dict[str, Any]] = {}
    parameters: Dict[str, Dict[str, Any]] = {}
    mapping: Dict[str, str] = {}
    version_actions = {"generation", "extend", "replace", "cover"}
    if action == "generation":
        inputs["prompt"] = prompt_input
        mapping["prompt"] = "sound_prompt"
        parameters = {
            "version": {"level": "optional", "type": "text", "default": "lyria-3.5", "ui_hidden": True},
            "lyrics": {"level": "optional", "type": "text"},
            "title": {"level": "optional", "type": "text"},
            "bpm": {"level": "optional", "type": "integer", "min": 1},
            "length": {"level": "optional", "type": "integer", "min": 1, "max": 240},
            "seed": {"level": "optional", "type": "integer"},
        }
        output = {"media_type": "audio", "min": 1, "max": 1, "async": True}
    elif action == "lyrics":
        inputs["prompt"] = {**prompt_input, "max_chars": 3000}
        mapping["prompt"] = "prompt"
        output = {"media_type": "text", "min": 1, "max": 1, "async": True}
    elif action in {"extend", "replace", "cover"}:
        parameters = {"clip_id": {"level": "required", "type": "text"}}
        mapping["clip_id"] = "clip_id"
        if action == "extend":
            parameters.update({
                "version": {"level": "optional", "type": "text", "default": "lyria-3.5", "ui_hidden": True},
                "extend_from_s": {"level": "required", "type": "number", "min": 0},
                "extend_s": {"level": "required", "type": "number", "min": 1, "max": 164},
                "instruction": {"level": "required", "type": "text"},
                "title": {"level": "optional", "type": "text"},
                "seed": {"level": "optional", "type": "integer"},
            })
        elif action == "replace":
            parameters.update({
                "version": {"level": "optional", "type": "text", "default": "lyria-3.5", "ui_hidden": True},
                "start_s": {"level": "required", "type": "number", "min": 0},
                "end_s": {"level": "required", "type": "number", "min": 0},
                "instruction": {"level": "required", "type": "text"},
                "title": {"level": "optional", "type": "text"},
                "seed": {"level": "optional", "type": "integer"},
            })
        else:
            parameters.update({
                "instruction": {"level": "required", "type": "text"},
                "strength": {"level": "optional", "type": "number", "min": 0, "max": 1, "default": 0.5},
                "title": {"level": "optional", "type": "text"},
                "seed": {"level": "optional", "type": "integer"},
            })
        output = {"media_type": "audio", "min": 1, "max": 1, "async": True}
    elif action == "stems":
        parameters = {"clip_id": {"level": "required", "type": "text"}}
        mapping["clip_id"] = "clip_id"
        output = {"media_type": "file", "min": 1, "max": 1, "async": True}
    elif action == "upload-audio":
        inputs["reference_audio"] = {"media_type": "audio", "min": 1, "max": 1, "role": "reference_audio"}
        mapping["reference_audio"] = "audio_url"
        output = {"media_type": "audio", "min": 1, "max": 1, "async": True}
    elif action == "download-audio":
        parameters = {
            "clip_id": {"level": "required", "type": "text"},
            "format": {"level": "optional", "type": "enum", "options": ["wav", "mp3"], "default": "wav"},
        }
        mapping.update({"clip_id": "clip_id", "format": "format"})
        output = {"media_type": "audio", "min": 1, "max": 1, "async": True}
    else:
        parameters = {
            "clip_id": {"level": "required", "type": "text"},
            "preset": {"level": "optional", "type": "enum", "options": ["simple", "modern", "player"], "default": "modern"},
        }
        mapping.update({"clip_id": "clip_id", "preset": "preset"})
        output = {"media_type": "video", "min": 1, "max": 1, "async": True}
    for key in parameters:
        mapping.setdefault(key, key)
    return {
        "model_id": model_id,
        "family_id": family_id,
        "family_name": family_name,
        "family_name_en": family_name_en,
        "display_name": model_id,
        "variant_id": action,
        "variant_name": variant_name,
        "variant_name_en": variant_name_en,
        "node_type": "music_generation",
        "operation": f"flowmusic_{action.replace('-', '_')}",
        "status": "confirmed",
        "readiness": "ready",
        "runnable": True,
        "version": 1,
        "evidence_level": "official_documented",
        "inputs": inputs,
        "parameters": parameters,
        "request_mapping": mapping,
        "output": output,
        "platform": {
            "endpoint": "/v1/music/generations" if action == "generation" else f"/v1/music/generations/{action}",
            "model": "flowmusic",
            **({"version": "lyria-3.5"} if action in version_actions else {}),
        },
    }


@lru_cache(maxsize=2)
def _laohu_documented_profiles(path, modified_ns):
    return _read_json(Path(path))


def ai_money_profile_from_model_id(model_id: str, node_type: str = "") -> Dict[str, Any]:
    normalized = normalize_laohu_model_id(model_id)
    lower = normalized.lower()
    # 已有明确档案优先于历史按名称推导，避免新版本被旧分支覆盖。
    documented_path = Path(__file__).resolve().parent / "data/model_capabilities/providers/ai-money.json"
    documented = _laohu_documented_profiles(str(documented_path), documented_path.stat().st_mtime_ns)
    matches = [item for item in documented.get("models", []) if item.get("model_id") == normalized and item.get("version", 0) >= 2]
    if matches:
        matched = next((item for item in matches if item.get("node_type") == node_type), None)
        if matched:
            return deepcopy(matched)
        raise ModelCapabilityError(f"模型 {normalized} 不支持 {node_type}")
    music_model = _is_music_model_id(normalized)
    if node_type == "music_generation" and not music_model:
        raise ModelCapabilityError(f"laohu 模型 {normalized} 不是音乐生成模型")
    if node_type == "audio_generation" and music_model:
        raise ModelCapabilityError(f"laohu 模型 {normalized} 属于音乐生成节点")
    if node_type == "text_generation" and lower == "whisper-1":
        return {
            "model_id": normalized, "family_id": "ai-money-whisper", "family_name": "Whisper",
            "display_name": normalized, "variant_id": "transcription", "node_type": "text_generation",
            "operation": "transcription", "status": "confirmed", "readiness": "ready", "runnable": True,
            "version": 1, "evidence_level": "official_documented",
            "inputs": {"reference_audio": {"media_type": "audio", "min": 1, "max": 1, "role": "reference_audio"}},
            "parameters": {}, "request_mapping": {"reference_audio": "file"},
            "output": {"media_type": "text", "min": 1, "max": 1, "async": False},
            "platform": {"endpoint": "/v1/audio/transcriptions"},
        }
    if node_type == "text_generation" and "context-ir-" in lower:
        inputs = {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}}
        if lower.endswith("-image"):
            inputs["first_frame"] = {"media_type": "image", "min": 1, "max": 1, "role": "first_frame"}
            inputs["last_frame"] = {"media_type": "image", "min": 0, "max": 1, "role": "last_frame"}
        elif lower.endswith("-multimodal"):
            inputs.update({
                "reference": {"media_type": "image", "min": 0, "max": 9, "role": "reference"},
                "source_video": {"media_type": "video", "min": 0, "max": 3, "role": "source_video"},
                "reference_audio": {"media_type": "audio", "min": 0, "max": 3, "role": "reference_audio"},
            })
        return {
            "model_id": normalized, "family_id": "ai-money-minmax-h3-context-ir", "family_name": "MiniMax H3 Context IR",
            "display_name": normalized, "variant_id": lower.rsplit("-", 1)[-1], "node_type": "text_generation",
            "operation": "prompt_enhancement", "status": "confirmed", "readiness": "ready", "runnable": True,
            "version": 1, "evidence_level": "official_documented", "inputs": inputs,
            "parameters": {
                "duration": {"level": "optional", "type": "enum", "options": [str(value) for value in range(4, 16)], "default": "5"},
                "aspect_ratio": {"level": "optional", "type": "enum", "options": ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]},
            },
            "request_mapping": {"prompt": "prompt", "duration": "seconds", "aspect_ratio": "metadata.ratio"},
            "output": {"media_type": "text", "min": 1, "max": 1, "async": True},
            "platform": {"endpoint": "/v1/video/generations"},
        }
    if node_type == "text_generation" and lower == "midjourney-describe":
        return {
            "model_id": normalized, "family_id": "ai-money-midjourney", "family_name": "Midjourney",
            "display_name": normalized, "variant_id": "describe", "node_type": "text_generation",
            "operation": "image_description", "status": "confirmed", "readiness": "ready", "runnable": True,
            "version": 1, "evidence_level": "official_schema",
            "inputs": {"reference": {"media_type": "image", "min": 1, "max": 1, "role": "reference"}},
            "parameters": {}, "request_mapping": {"reference": "image_urls"},
            "output": {"media_type": "text", "min": 1, "max": 4, "async": False},
            "platform": {"endpoint": "/v1/midjourney/generations/describe"},
        }
    if node_type == "text_generation" and lower == "laohu/gk-4.6":
        return {
            "model_id": normalized,
            "family_id": "ai-money-laohu-gk-4-6",
            "family_name": "GK 4.6",
            "family_name_en": "GK 4.6",
            "display_name": normalized,
            "variant_id": "default",
            "variant_name": "默认",
            "variant_name_en": "Default",
            "node_type": "text_generation",
            "operation": "chat",
            "status": "confirmed",
            "readiness": "ready",
            "runnable": True,
            "version": 1,
            "evidence_level": "official_documented",
            "inputs": {
                "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
                "reference": {
                    "media_type": "image",
                    "min": 0,
                    "max": 8,
                    "role": "reference",
                    "note": "官方文档确认支持视觉输入；当前画布适配器最多转发 8 张图片。",
                },
            },
            "parameters": {
                "max_output_tokens": {"level": "optional", "type": "integer", "min": 1},
            },
            "request_mapping": {
                "prompt": "messages",
                "reference": "messages.content",
                "max_output_tokens": "max_tokens",
            },
            "output": {"media_type": "text", "min": 1, "max": 1, "async": False},
            "platform": {"endpoint": "/v1/chat/completions"},
        }
    if node_type == "text_generation":
        family_mode = _ai_money_text_family_mode(normalized)
        return {
            "model_id": normalized, **family_mode,
            "display_name": normalized,
            "node_type": "text_generation", "operation": "chat", "status": "confirmed",
            "readiness": "ready", "runnable": True, "version": 1, "evidence_level": "official_documented",
            "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
            "parameters": {}, "request_mapping": {"prompt": "messages"},
            "output": {"media_type": "text", "min": 1, "max": 1, "async": False},
            "platform": {"endpoint": "/v1/chat/completions"},
        }
    if node_type == "video_generation":
        return _ai_money_video_profile(normalized)
    if node_type == "image_generation" and lower.startswith("midjourney-"):
        action = lower.removeprefix("midjourney-")
        input_specs = {"prompt": {"media_type": "text", "min": 0, "max": 1, "role": "prompt"}}
        parameters = {
            "speed": {"level": "optional", "type": "enum", "options": ["relax", "fast", "turbo"], "default": "relax"},
            "size": {"level": "optional", "type": "enum", "options": ["1:1", "16:9", "9:16", "4:3", "3:4"], "default": "1:1"},
            "aspect_ratio": {"level": "optional", "type": "enum", "options": ["1:1", "16:9", "9:16", "4:3", "3:4"], "source_field": "size"},
        }
        if action in {"blend", "edits", "imagine"}:
            input_specs["reference"] = {
                "media_type": "image", "min": 2 if action == "blend" else 0,
                "max": 4, "role": "reference", "max_bytes": 12 * 1024 * 1024,
            }
        if action == "imagine":
            parameters["version"] = {"level": "optional", "type": "enum", "options": ["6.1", "6.0", "5.2", "5.1"], "default": "6.1"}
        elif action == "modal":
            parameters["upstream_task_id"] = {"level": "required", "type": "text"}
            input_specs["mask"] = {"media_type": "image", "min": 1, "max": 1, "role": "mask"}
        else:
            parameters.update({
                "upstream_task_id": {"level": "required", "type": "text"},
                "index": {"level": "optional", "type": "integer", "min": 1, "max": 4},
                "custom_id": {"level": "optional", "type": "text"},
            })
            if action == "zoom":
                parameters["zoom_ratio"] = {"level": "required", "type": "number", "min": 1.01, "max": 4, "default": 2}
            if action == "pan":
                parameters["direction"] = {"level": "required", "type": "enum", "options": ["left", "right", "up", "down"]}
            if action in {"remix_subtle", "remix_strong"}:
                input_specs["prompt"]["min"] = 0
        return {
            "model_id": normalized, "family_id": "ai-money-midjourney", "family_name": "Midjourney",
            "display_name": normalized, "variant_id": action, "node_type": "image_generation",
            "operation": f"midjourney_{action.replace('-', '_')}", "status": "confirmed", "readiness": "ready", "runnable": True,
            "version": 1, "evidence_level": "official_schema", "inputs": input_specs, "parameters": parameters,
            "request_mapping": {"prompt": "prompt", "reference": "image_urls", "speed": "speed", "size": "size", "aspect_ratio": "size", "version": "version", "upstream_task_id": "task_id", "index": "index", "custom_id": "custom_id", "zoom_ratio": "zoom_ratio", "direction": "direction"},
            "output": {"media_type": "image", "min": 1, "async": True},
            "platform": {"endpoint": f"/v1/midjourney/generations/{action}" if action != "imagine" else "/v1/midjourney/generations"},
        }
    layer_decomposition = "layer-decomposition" in lower
    official_image_model = (
        lower.startswith("laohu-image-")
        or lower.startswith("seedream-v5-pro-")
        or lower.startswith("qwen-image-3.0-")
        or lower.startswith("wan-2.7-global-")
        or layer_decomposition
    )
    if official_image_model:
        operation = "layer_decomposition" if layer_decomposition else "image_to_image" if any(token in lower for token in ("-i2i", "-edit", "image-to-image")) else "text_to_image"
        family_base = re.sub(r"-(i2i|t2i|edit)$", "", lower)
        if lower.startswith("laohu-image-g2-") or lower.startswith("laohu-image-g-v2-"):
            family_base = "gpt-image-2"
        elif lower.startswith("laohu-image-gk-"):
            family_base = "grok-image"
        elif lower.startswith("laohu-image-nb-pro"):
            family_base = "nano-banana-pro"
        elif lower.startswith("laohu-image-nb-"):
            family_base = "nano-banana-2"
        elif lower.startswith("qwen-image-3.0-"):
            family_base = "qwen-image-3.0"
        elif lower.startswith("seedream-v5-pro-") and not layer_decomposition:
            family_base = "seedream-v5-pro"
        elif lower.startswith("wan-2.7-global-"):
            family_base = "wan-image"
        prompt_input = {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}
        if lower == "laohu-image-nb-flash":
            prompt_input["max_chars"] = 1000
        elif operation == "image_to_image" and lower.startswith("laohu-image-"):
            prompt_input.update({"min_chars": 5, "max_chars": 2000})
        inputs = {"prompt": prompt_input}
        mapping = {"prompt": "prompt"}
        optional_reference_max = 0
        if lower.startswith("laohu-image-nb-"):
            optional_reference_max = 14
        elif lower.startswith("laohu-image-g-v2-lowprice"):
            optional_reference_max = 16
        if operation in {"image_to_image", "layer_decomposition"} or optional_reference_max:
            reference_min = 1 if operation in {"image_to_image", "layer_decomposition"} else 0
            if lower == "laohu-image-gk-v2-edit":
                reference_max = 3
            else:
                reference_max = 1 if layer_decomposition or lower.startswith("laohu-image-gk-v15-edit") else (optional_reference_max or 10)
            inputs["reference"] = {"media_type": "image", "min": reference_min, "max": reference_max, "role": "reference"}
            mapping["reference"] = "images"
        parameters = {
            "resolution": {"level": "optional", "type": "enum", "options": ["1k", "2k", "4k"], "source_field": "metadata.resolution"},
            "aspect_ratio": {"level": "optional", "type": "enum", "options": ["1:1", "16:9", "9:16", "4:3", "3:4"], "source_field": "metadata.ratio"},
        }
        if lower == "laohu-image-gk-v2-edit":
            parameters = {
                "resolution": {"level": "optional", "type": "enum", "options": ["1k", "2k"], "source_field": "resolution"},
                "aspect_ratio": {"level": "optional", "type": "enum", "options": ["auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "9:21", "1:2", "2:1"], "source_field": "aspect_ratio"},
                "count": {"level": "optional", "type": "integer", "min": 1, "max": 10, "source_field": "n"},
                "nsfw_check": {"level": "optional", "type": "boolean", "default": False, "source_field": "nsfw_check"},
            }
        elif lower == "laohu-image-gk-v2":
            parameters = {
                "resolution": {"level": "optional", "type": "enum", "options": ["quality"], "source_field": "resolution"},
                "aspect_ratio": {"level": "optional", "type": "enum", "options": ["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9"], "source_field": "size"},
                "count": {"level": "optional", "type": "integer", "min": 1, "max": 12, "source_field": "n"},
            }
        if lower == "laohu-image-g-v2-lowprice":
            parameters["aspect_ratio"]["source_field"] = "size"
            parameters["count"] = {"level": "optional", "type": "integer", "min": 1, "max": 10, "source_field": "n"}
        mapping.update({
            key: str(spec.get("source_field") or key)
            for key, spec in parameters.items()
        })
        return {
            "model_id": normalized, "family_id": "ai-money-" + re.sub(r"[^a-z0-9]+", "-", family_base).strip("-"),
            "family_name": family_base.replace("-", " ").title(), "display_name": normalized,
            "variant_id": operation, "node_type": "image_generation", "operation": operation,
            "status": "confirmed", "readiness": "ready", "runnable": True, "version": 1,
            "evidence_level": "official_documented", "inputs": inputs,
            "parameters": parameters, "request_mapping": mapping, "output": {"media_type": "image", "min": 1, "max": 10, "async": True},
            "platform": {"endpoint": "/v1/image/generations"},
        }
    if normalized == "doubao-seed-audio-1.0":
        return {
            "model_id": normalized, "family_id": "ai-money-doubao-seed-audio", "family_name": "豆包 Seed Audio",
            "display_name": normalized, "variant_id": "speech", "node_type": "audio_generation", "operation": "text_to_audio",
            "status": "confirmed", "readiness": "ready", "runnable": True, "version": 1,
            "evidence_level": "official_documented",
            "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}, "reference_audio": {"media_type": "audio", "min": 0, "max": 1, "role": "reference_audio"}},
            "parameters": {"speaker": {"level": "optional", "type": "text"}, "format": {"level": "optional", "type": "enum", "options": ["mp3", "wav", "pcm", "ogg_opus"], "default": "mp3"}, "sample_rate": {"level": "optional", "type": "enum", "options": [8000, 16000, 24000, 32000, 44100], "default": 24000}, "speech_rate": {"level": "advanced", "type": "integer", "min": -50, "max": 100}, "loudness_rate": {"level": "advanced", "type": "integer", "min": -50, "max": 100}, "pitch_rate": {"level": "advanced", "type": "integer", "min": -12, "max": 12}},
            "request_mapping": {"prompt": "prompt", "reference_audio": "metadata.audio_url", "speaker": "metadata.speaker", "format": "metadata.format", "sample_rate": "metadata.sample_rate", "speech_rate": "metadata.speech_rate", "loudness_rate": "metadata.loudness_rate", "pitch_rate": "metadata.pitch_rate"},
            "output": {"media_type": "audio", "min": 1, "async": True},
            "platform": {"endpoint": "/v1/audio/generations"},
        }
    if lower in {"qwen3-tts-flash", "qwen3-tts-instruct-flash"}:
        parameters = {
            "voice": {"level": "optional", "type": "text", "default": "Cherry"},
            "language_type": {
                "level": "optional", "type": "enum",
                "options": ["Chinese", "English", "Japanese", "Korean", "German", "French", "Russian", "Portuguese", "Spanish", "Italian"],
                "default": "Chinese",
            },
        }
        if lower == "qwen3-tts-instruct-flash":
            parameters.update({
                "instructions": {"level": "optional", "type": "text"},
                "optimize_instructions": {"level": "optional", "type": "boolean", "default": True},
            })
        return {
            "model_id": normalized, "family_id": "ai-money-qwen3-tts", "family_name": "Qwen3 TTS",
            "display_name": normalized, "variant_id": lower.removeprefix("qwen3-tts-"),
            "node_type": "audio_generation", "operation": "text_to_speech",
            "status": "confirmed", "readiness": "ready", "runnable": True, "version": 1,
            "evidence_level": "runtime_verified",
            "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
            "parameters": parameters,
            "request_mapping": {
                "prompt": "prompt", "voice": "metadata.voice", "language_type": "metadata.language_type",
                "instructions": "metadata.instructions", "optimize_instructions": "metadata.optimize_instructions",
            },
            "output": {"media_type": "audio", "min": 1, "max": 1, "async": True},
            "platform": {"endpoint": "/v1/audio/generations"},
        }
    if lower == "minimax-music-2.6":
        return {
            "model_id": normalized, "family_id": "ai-money-minimax", "family_name": "MiniMax",
            "family_name_en": "MiniMax", "display_name": normalized,
            "variant_id": "music-2.6", "variant_name": "Music 2.6", "variant_name_en": "Music 2.6",
            "node_type": "music_generation",
            "operation": "music", "status": "confirmed", "readiness": "ready", "runnable": True,
            "version": 1, "evidence_level": "runtime_verified",
            "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
            "parameters": {
                "is_instrumental": {"level": "optional", "type": "boolean", "default": True},
                "lyrics": {"level": "optional", "type": "text"},
                "lyrics_optimizer": {"level": "optional", "type": "boolean", "default": False},
                "format": {"level": "optional", "type": "enum", "options": ["mp3", "wav", "flac"], "default": "mp3"},
                "sample_rate": {"level": "optional", "type": "enum", "options": ["16000", "24000", "32000", "44100"], "default": "44100"},
                "bitrate": {"level": "optional", "type": "enum", "options": ["32000", "64000", "128000", "256000"], "default": "256000"},
            },
            "request_mapping": {
                "prompt": "prompt", "is_instrumental": "metadata.is_instrumental", "lyrics": "metadata.lyrics",
                "lyrics_optimizer": "metadata.lyrics_optimizer", "format": "metadata.format",
                "sample_rate": "metadata.sample_rate", "bitrate": "metadata.bitrate",
            },
            "output": {"media_type": "audio", "min": 1, "max": 1, "async": True},
            "platform": {"endpoint": "/v1/audio/generations"},
        }
    if lower in {"minimax-speech-2.8-hd", "minimax-speech-2.8-turbo"}:
        quality = "hd" if lower.endswith("-hd") else "turbo"
        return {
            "model_id": normalized, "family_id": "ai-money-minimax", "family_name": "MiniMax",
            "family_name_en": "MiniMax", "display_name": normalized, "variant_id": f"speech-2.8-{quality}",
            "variant_name": f"Speech 2.8 · {'高清' if quality == 'hd' else '极速'}",
            "variant_name_en": f"Speech 2.8 · {'HD' if quality == 'hd' else 'Turbo'}",
            "node_type": "audio_generation", "operation": "text_to_speech",
            "status": "confirmed", "readiness": "ready", "runnable": True, "version": 1,
            "evidence_level": "runtime_verified",
            "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
            "parameters": {
                "voice_id": {"level": "optional", "type": "text", "default": "Wise_Woman"},
                "speed": {"level": "optional", "type": "number", "min": 0.5, "max": 2, "default": 1},
                "volume": {"level": "optional", "type": "number", "min": 0.000001, "max": 10, "default": 1},
                "pitch": {"level": "optional", "type": "integer", "min": -12, "max": 12, "default": 0},
                "language_boost": {
                    "level": "optional", "type": "enum",
                    "options": ["auto", "Chinese", "Chinese,Yue", "English", "Japanese", "Korean", "French", "German", "Spanish", "Portuguese", "Russian"],
                    "default": "auto",
                },
                "format": {"level": "optional", "type": "enum", "options": ["mp3", "wav", "flac"], "default": "mp3"},
                "sample_rate": {"level": "optional", "type": "enum", "options": ["16000", "24000", "32000", "44100"], "default": "32000"},
                "bitrate": {"level": "optional", "type": "enum", "options": ["32000", "64000", "128000", "256000"], "default": "128000"},
                "channel": {"level": "optional", "type": "enum", "options": [1, 2], "default": 1},
            },
            "request_mapping": {
                "prompt": "prompt", "voice_id": "metadata.voice_id", "speed": "metadata.speed",
                "volume": "metadata.vol", "pitch": "metadata.pitch", "language_boost": "metadata.language_boost",
                "format": "metadata.format", "sample_rate": "metadata.sample_rate",
                "bitrate": "metadata.bitrate", "channel": "metadata.channel",
            },
            "output": {"media_type": "audio", "min": 1, "max": 1, "async": True},
            "platform": {"endpoint": "/v1/audio/generations"},
        }
    if lower == "minimax-voice-clone":
        return {
            "model_id": normalized, "family_id": "ai-money-minimax", "family_name": "MiniMax",
            "family_name_en": "MiniMax", "display_name": normalized, "variant_id": "voice-clone",
            "variant_name": "声音克隆", "variant_name_en": "Voice Clone", "node_type": "audio_generation",
            "operation": "voice_clone", "status": "confirmed", "readiness": "ready", "runnable": True,
            "version": 1, "evidence_level": "runtime_verified",
            "inputs": {
                "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
                "reference_audio": {"media_type": "audio", "min": 1, "max": 1, "role": "reference_audio"},
            },
            "parameters": {
                "custom_voice_id": {"level": "required", "type": "text"},
                "clone_target_model": {
                    "level": "optional", "type": "enum",
                    "options": ["minimax-speech-2.8-hd", "minimax-speech-2.8-turbo"], "default": "minimax-speech-2.8-hd",
                },
                "need_noise_reduction": {"level": "optional", "type": "boolean", "default": False},
                "need_volume_normalization": {"level": "optional", "type": "boolean", "default": False},
            },
            "request_mapping": {
                "prompt": "prompt", "reference_audio": "metadata.audio_url",
                "custom_voice_id": "metadata.custom_voice_id", "clone_target_model": "metadata.model",
                "need_noise_reduction": "metadata.need_noise_reduction",
                "need_volume_normalization": "metadata.need_volume_normalization",
            },
            "output": {"media_type": "text", "min": 1, "max": 1, "async": True},
            "platform": {"endpoint": "/v1/audio/generations"},
        }
    if lower in {"mureka-v8-bgm", "mureka-v9-bgm"}:
        return {
            "model_id": normalized, "family_id": "ai-money-mureka-bgm", "family_name": "Mureka BGM",
            "display_name": normalized, "variant_id": lower.removeprefix("mureka-"), "node_type": "music_generation",
            "operation": "music", "status": "confirmed", "readiness": "ready", "runnable": True,
            "version": 1, "evidence_level": "official_documented",
            "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
            "parameters": {"count": {"level": "optional", "type": "integer", "min": 1, "max": 3, "default": 2}},
            "request_mapping": {"prompt": "prompt", "count": "metadata.n"},
            "output": {"media_type": "audio", "min": 1, "max": 3, "async": True},
            "platform": {"endpoint": "/v1/audio/generations"},
        }
    if lower in {"mureka-o2-song", "mureka-v9-song"}:
        is_v9 = lower == "mureka-v9-song"
        parameters = {
            "count": {"level": "optional", "type": "integer", "min": 1, "max": 3, "default": 2},
            "style_prompt": {"level": "optional", "type": "text"},
            "reference_id": {"level": "optional", "type": "text"},
        }
        request_mapping = {
            "prompt": "metadata.lyrics",
            "count": "metadata.n",
            "style_prompt": "metadata.prompt",
            "reference_id": "metadata.reference_id",
        }
        if is_v9:
            parameters.update({
                "vocal_id": {"level": "optional", "type": "text"},
                "melody_id": {"level": "optional", "type": "text"},
                "stream": {"level": "optional", "type": "boolean", "default": False},
            })
            request_mapping.update({
                "vocal_id": "metadata.vocal_id",
                "melody_id": "metadata.melody_id",
                "stream": "metadata.stream",
            })
        return {
            "model_id": normalized, "family_id": "ai-money-mureka-song", "family_name": "Mureka 歌曲",
            "family_name_en": "Mureka Song", "display_name": normalized,
            "variant_id": "v9-song" if is_v9 else "o2-song",
            "variant_name": "Mureka v9 歌曲" if is_v9 else "Mureka O2 歌曲",
            "variant_name_en": "Mureka v9 Song" if is_v9 else "Mureka O2 Song",
            "node_type": "music_generation", "operation": "music_song",
            "status": "confirmed", "readiness": "ready", "runnable": True, "version": 1,
            "evidence_level": "official_documented",
            "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
            "parameters": parameters, "request_mapping": request_mapping,
            "output": {"media_type": "audio", "min": 1, "max": 3, "async": True},
            "platform": {"endpoint": "/v1/audio/generations"},
        }
    if lower.startswith("flowmusic-"):
        return _ai_money_flowmusic_profile(normalized)
    if lower == "kling-lip-sync-tts" and node_type == "audio_generation":
        return {
            "model_id": normalized, "family_id": "ai-money-kling-lip-sync", "family_name": "可灵对口型",
            "family_name_en": "Kling Lip Sync", "display_name": normalized,
            "variant_id": "lip-sync-tts", "variant_name": "口型同步语音流程",
            "variant_name_en": "Lip Sync TTS Workflow", "node_type": node_type,
            "operation": "lip_sync_workflow", "status": "confirmed", "readiness": "adapter_missing",
            "runnable": False, "version": 1, "evidence_level": "official_documented",
            "inputs": {
                "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
                "source_video": {"media_type": "video", "min": 1, "max": 1, "role": "source_video"},
            },
            "parameters": {}, "request_mapping": {},
            "output": {"media_type": "video", "min": 1, "max": 1, "async": True},
            "platform": {"endpoint": "/v1/video/generations", "workflow": "identify-face -> tts -> lip-sync-video"},
            "note": "官方接口是人脸识别、语音合成、口型同步的多步流程，当前普通音频节点没有 sessionId/faceId 编排适配器。",
        }
    if lower.startswith("suno-"):
        action = lower.removeprefix("suno-")
        endpoint = "/v1/music/generations" if action == "generation" else f"/v1/music/generations/{action}"
        source_actions = {"generation", "lyrics", "upload", "inspo", "sounds", "create-voice", "upsample-tags"}
        parameters = {
            "version": {
                "level": "optional",
                "type": "enum",
                "options": ["v6", "v6-wild", "v6-mini"],
            },
        }
        if action not in source_actions:
            parameters["upstream_task_id"] = {"level": "required", "type": "text"}
            parameters["upstream_result_index"] = {"level": "optional", "type": "integer", "min": 1}
        return {
            "model_id": normalized, "family_id": "ai-money-suno", "family_name": "Suno",
            "display_name": normalized, "variant_id": action, "node_type": "music_generation",
            "operation": f"music_{action.replace('-', '_')}", "status": "confirmed",
            "readiness": "ready", "runnable": True, "version": 1,
            "evidence_level": "official_schema",
            "inputs": {"prompt": {"media_type": "text", "min": 0, "max": 1, "role": "prompt"}},
            "parameters": parameters,
            "request_mapping": {
                "prompt": "prompt", "version": "version",
                "upstream_task_id": "task_id", "upstream_result_index": "audio_index",
            },
            "output": {"media_type": "audio", "min": 1, "async": True},
            "platform": {"endpoint": endpoint},
        }
    raise ModelCapabilityError(f"laohu 模型 {normalized} 缺少已确认的平台适配器")


def modelscope_profile_from_model_id(model_id: str, node_type: str) -> Dict[str, Any]:
    normalized = str(model_id or "").strip()
    supported_text = {
        "Qwen/Qwen3-235B-A22B",
        "Qwen/Qwen3-VL-235B-A22B-Instruct",
        "MiniMax/MiniMax-M2.7:MiniMax",
    }
    supported_image = {
        "Tongyi-MAI/Z-Image-Turbo",
        "Qwen/Qwen-Image-2512",
        "Qwen/Qwen-Image-Edit-2511",
        "black-forest-labs/FLUX.2-klein-9B",
    }
    if node_type == "text_generation":
        if normalized not in supported_text:
            raise ModelCapabilityError(f"ModelScope 文本模型 {normalized} 尚未建立已确认能力档案")
        inputs = {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}}
        operation = "chat"
        if "qwen3-vl" in normalized.lower():
            operation = "multimodal_chat"
            inputs["reference"] = {"media_type": "image", "min": 0, "max": 10, "role": "reference"}
        return {
            "model_id": normalized, "family_id": f"modelscope-{re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')}",
            "family_name": normalized.rsplit("/", 1)[-1], "display_name": normalized,
            "variant_id": operation, "node_type": node_type, "operation": operation,
            "status": "confirmed", "readiness": "ready", "runnable": True, "version": 1,
            "evidence_level": "runtime_verified", "inputs": inputs,
            "parameters": {}, "request_mapping": {"prompt": "messages", "reference": "messages.content"},
            "output": {"media_type": "text", "min": 1, "max": 1, "async": False},
            "platform": {"endpoint": "/v1/chat/completions"},
        }
    if node_type != "image_generation":
        raise ModelCapabilityError(f"ModelScope 模型 {normalized} 不支持节点类型 {node_type}")
    if normalized not in supported_image:
        raise ModelCapabilityError(f"ModelScope 图片模型 {normalized} 尚未建立已确认能力档案")
    lower = normalized.lower()
    image_to_image = "image-edit" in lower or "flux.2-klein" in lower
    inputs = {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}}
    if image_to_image:
        inputs["reference"] = {"media_type": "image", "min": 1, "max": 10, "role": "reference"}
    return {
        "model_id": normalized, "family_id": f"modelscope-{re.sub(r'[^a-z0-9]+', '-', lower).strip('-')}",
        "family_name": normalized.rsplit("/", 1)[-1], "display_name": normalized,
        "variant_id": "image_to_image" if image_to_image else "text_to_image",
        "node_type": node_type, "operation": "image_to_image" if image_to_image else "text_to_image",
        "status": "confirmed", "readiness": "ready", "runnable": True, "version": 1,
        "evidence_level": "runtime_verified", "inputs": inputs, "parameters": {},
        "request_mapping": {"prompt": "prompt", "reference": "image_url"},
        "output": {"media_type": "image", "min": 1, "max": 1, "async": True},
        "platform": {"endpoint": "/v1/images/generations"},
    }


def jimeng_profile_from_model_id(model_id: str, node_type: str) -> Dict[str, Any]:
    normalized = str(model_id or "").strip()
    if node_type == "image_generation":
        supported = JIMENG_IMAGE_TEXT2IMAGE_MODELS
        editable = JIMENG_IMAGE2IMAGE_MODELS
        if normalized not in supported:
            raise ModelCapabilityError(f"即梦 CLI 图片模型 {normalized} 不在命令白名单中")
        inputs = {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}}
        if normalized in editable:
            inputs["reference"] = {"media_type": "image", "min": 0, "max": 10, "role": "reference"}
        resolution_options = jimeng_image_resolution_options(normalized)
        operation = "text_to_image_or_image_to_image" if normalized in editable else "text_to_image"
        return {
            "model_id": normalized, "family_id": f"jimeng-image-{normalized.lower()}",
            "family_name": f"即梦图片 {normalized}", "display_name": normalized,
            "variant_id": operation, "node_type": node_type, "operation": operation,
            "status": "confirmed", "readiness": "ready", "runnable": True, "version": 1,
            "evidence_level": "runtime_verified", "inputs": inputs,
            "parameters": {
                "aspect_ratio": {"level": "optional", "type": "enum", "options": ["21:9", "16:9", "3:2", "4:3", "1:1", "3:4", "2:3", "9:16"]},
                "resolution": {"level": "optional", "type": "enum", "options": resolution_options},
            },
            "request_mapping": {"prompt": "prompt", "reference": "images", "aspect_ratio": "ratio", "resolution": "resolution_type"},
            "output": {"media_type": "image", "min": 1, "max": 1, "async": True},
            "platform": {"transport": "local_cli", "commands": ["text2image"] + (["image2image"] if normalized in editable else [])},
        }
    if node_type == "video_generation":
        supported = {"seedance2.0_vip", "seedance2.0fast_vip", "seedance2.0", "seedance2.0fast", "seedance2.0mini", "seedance2.5"}
        if normalized not in supported:
            raise ModelCapabilityError(f"即梦 CLI 视频模型 {normalized} 不在命令白名单中")
        is_seedance_25 = normalized == "seedance2.5"
        prompt_max_chars = 15000 if is_seedance_25 else 4000
        reference_max = 30 if is_seedance_25 else 9
        video_max = 10 if is_seedance_25 else 3
        audio_max = 10 if is_seedance_25 else 3
        return {
            "model_id": normalized,
            "family_id": "jimeng-seedance-2.5" if is_seedance_25 else "jimeng-seedance-2.0",
            "family_name": "Seedance 2.5" if is_seedance_25 else "Seedance 2.0",
            "display_name": normalized, "variant_id": normalized, "node_type": node_type,
            "operation": "multimodal_to_video", "status": "confirmed", "readiness": "ready",
            "runnable": True, "version": 1, "evidence_level": "runtime_verified",
            "inputs": {
                "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt", "max_chars": prompt_max_chars},
                "first_frame": {"media_type": "image", "min": 0, "max": 1, "role": "first_frame"},
                "last_frame": {"media_type": "image", "min": 0, "max": 1, "role": "last_frame"},
                "reference": {"media_type": "image", "min": 0, "max": reference_max, "role": "reference"},
                "source_video": {"media_type": "video", "min": 0, "max": video_max, "role": "source_video"},
                "reference_audio": {"media_type": "audio", "min": 0, "max": audio_max, "role": "reference_audio"},
            },
            "parameters": {
                "duration": {"level": "optional", "type": "integer", "min": 4, "max": 30 if is_seedance_25 else 15, "default": 5},
                "aspect_ratio": {"level": "optional", "type": "enum", "options": ["1:1", "3:4", "16:9", "4:3", "9:16", "21:9"]},
                "resolution": {
                    "level": "optional",
                    "type": "enum",
                    "options": ["480p", "720p"] if is_seedance_25 else (["720p", "1080p", "4k"] if normalized == "seedance2.0_vip" else ["720p"]),
                },
            },
            "request_mapping": {
                "prompt": "prompt", "first_frame": "first", "last_frame": "last", "reference": "image",
                "source_video": "video", "reference_audio": "audio", "duration": "duration",
                "aspect_ratio": "ratio", "resolution": "video_resolution",
            },
            "output": {"media_type": "video", "min": 1, "max": 1, "async": True},
            "platform": {
                "transport": "local_cli",
                "commands": ["text2video", "image2video", "frames2video", "multimodal2video"],
                **({
                    "vip_only": True,
                    "prompt_modes": {
                        "text_to_video": 15000,
                        "image_to_video": 15000,
                        "frames_to_video": 15000,
                        "multimodal_to_video": 15000,
                        "video_edit": 15000,
                    },
                } if is_seedance_25 else {}),
            },
        }
    raise ModelCapabilityError(f"即梦 CLI 模型 {normalized} 不支持节点类型 {node_type}")


def agnes_profile_from_model_id(model_id: str, node_type: str) -> Dict[str, Any]:
    normalized = str(model_id or "").strip()
    common = {
        "model_id": normalized,
        "family_id": "agnes-" + re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-"),
        "family_name": normalized,
        "display_name": normalized,
        "node_type": node_type,
        "status": "confirmed",
        "readiness": "ready",
        "runnable": True,
        "version": 1,
        "evidence_level": "runtime_verified",
    }
    if node_type == "text_generation" and normalized == "agnes-2.0-flash":
        return {
            **common,
            "variant_id": "chat",
            "operation": "chat",
            "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}},
            "parameters": {
                "temperature": {"level": "optional", "type": "number", "min": 0, "max": 2, "default": 1},
                "top_p": {"level": "optional", "type": "number", "min": 0, "max": 1, "default": 1},
                "max_output_tokens": {"level": "optional", "type": "integer", "min": 1, "default": 2048},
            },
            "request_mapping": {
                "prompt": "messages", "temperature": "temperature",
                "top_p": "top_p", "max_output_tokens": "max_tokens",
            },
            "output": {"media_type": "text", "min": 1, "max": 1, "async": False},
            "platform": {"endpoint": "/v1/chat/completions"},
        }
    if node_type == "image_generation" and normalized in {"agnes-image-2.0-flash", "agnes-image-2.1-flash"}:
        return {
            **common,
            "variant_id": "text_or_image_to_image",
            "operation": "text_or_image_to_image",
            "inputs": {
                "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
                "reference": {"media_type": "image", "min": 0, "max": 4, "role": "reference"},
            },
            "parameters": {
                "size": {
                    "level": "optional", "type": "enum",
                    "options": ["512x512", "1024x1024"], "default": "1024x1024",
                },
            },
            "request_mapping": {"prompt": "prompt", "reference": "extra_body.image", "size": "size"},
            "output": {"media_type": "image", "min": 1, "max": 1, "async": False},
            "platform": {"endpoint": "/v1/images/generations"},
        }
    if node_type == "video_generation" and normalized == "agnes-video-v2.0":
        return {
            **common,
            "variant_id": "text_or_image_to_video",
            "operation": "text_or_image_to_video",
            "inputs": {
                "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
                "reference": {"media_type": "image", "min": 0, "max": 4, "role": "reference"},
            },
            "parameters": {
                "aspect_ratio": {
                    "level": "optional", "type": "enum",
                    "options": ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9", "9:21"],
                    "default": "16:9",
                },
                "resolution": {
                    "level": "optional", "type": "enum",
                    "options": ["480p", "720p", "1080p"], "default": "720p",
                },
                "duration": {"level": "optional", "type": "integer", "min": 1, "max": 18, "default": 5},
                "frame_rate": {"level": "advanced", "type": "integer", "min": 1, "max": 60, "default": 24},
                "seed": {"level": "advanced", "type": "integer", "min": 0, "max": 4294967295},
            },
            "request_mapping": {
                "prompt": "prompt", "reference": "image", "aspect_ratio": "aspect_ratio",
                "resolution": "resolution", "duration": "duration", "frame_rate": "frame_rate", "seed": "seed",
            },
            "output": {"media_type": "video", "min": 1, "max": 1, "async": True},
            "platform": {"submit_endpoint": "/v1/videos", "poll_endpoint": "/agnesapi"},
        }
    raise ModelCapabilityError(f"Agnes 模型 {normalized} 不支持节点类型 {node_type}")


def dynamic_profile_for_model(provider_id: str, model_id: str, node_type: str) -> Optional[Dict[str, Any]]:
    try:
        if provider_id == "codex-cli":
            normalized = str(model_id or "").strip()
            if node_type != "text_generation" or not normalized:
                raise ModelCapabilityError(f"Codex 模型 {normalized or model_id} 不支持节点类型 {node_type}")
            follows_current = normalized.lower() == "auto"
            return {
                "model_id": normalized,
                "family_id": "codex-current" if follows_current else normalized,
                "family_name": "Codex 当前配置" if follows_current else normalized,
                "variant_id": "follow_current_config" if follows_current else "explicit_model_override",
                "node_type": "text_generation",
                "operation": "chat_or_agent_text",
                "status": "confirmed",
                "readiness": "ready",
                "runnable": True,
                "version": 1,
                "evidence_level": "runtime_verified",
                "inputs": {
                    "prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"},
                    "system_prompt": {"media_type": "text", "min": 0, "max": 1, "role": "system_prompt"},
                    "reference_image": {"media_type": "image", "min": 0, "max": 10, "role": "reference", "context_only": True},
                },
                "parameters": {} if follows_current else {
                    "model": {
                        "level": "required",
                        "type": "model",
                        "ui_hidden": True,
                        "description": "当前节点的单次 Codex --model 覆盖，不修改全局配置。",
                        "description_en": "Per-node Codex --model override; it does not modify global configuration.",
                    }
                },
                "request_mapping": {
                    "prompt": "stdin",
                    "system_prompt": "prompt_prefix",
                    "reference_image": "--image",
                    **({} if follows_current else {"model": "--model"}),
                },
                "output": {"media_type": "text", "min": 1, "max": 1, "async": False},
                "platform": {"transport": "local_cli", "command": "codex"},
                "note": "模型是否对当前账号或 API Provider 可用，由 Codex CLI 在运行时校验。",
            }
        if provider_id == "runninghub" and node_type == "text_generation":
            return runninghub_profile_from_registry_item({
                "name_en": model_id,
                "endpoint": model_id,
                "output_type": "chat",
            })
        if provider_id == "ai-money":
            return ai_money_profile_from_model_id(model_id, node_type)
        if provider_id == "modelscope":
            return modelscope_profile_from_model_id(model_id, node_type)
        if provider_id == "jimeng-cli":
            return jimeng_profile_from_model_id(model_id, node_type)
        if provider_id == "agnes":
            return agnes_profile_from_model_id(model_id, node_type)
    except ModelCapabilityError:
        return None
    return None


class ModelCapabilityError(ValueError):
    pass


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_runninghub_registry_snapshot(
    root: Path,
    region: str,
    items: Iterable[Dict[str, Any]],
    source: str = "",
) -> Path:
    safe_region = "cn" if str(region or "").strip().lower() == "cn" else "global"
    allowed_keys = {
        "class_name", "internal_name", "display_name", "name_cn", "name_en",
        "endpoint", "output_type", "category", "params",
    }
    sanitized = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        clean = {key: deepcopy(item[key]) for key in allowed_keys if key in item}
        if clean.get("name_en") or clean.get("endpoint"):
            sanitized.append(clean)
    path = Path(root) / "data" / "model_capabilities" / "snapshots" / f"runninghub-{safe_region}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "region": safe_region,
        "source": str(source or "").strip(),
        "items": sanitized,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_provider_catalog_snapshot(
    root: Path,
    provider_id: str,
    catalog: Dict[str, Any],
    source: str = "",
) -> Path:
    safe_provider_id = re.sub(r"[^a-z0-9-]+", "-", str(provider_id or "").strip().lower()).strip("-")
    if not safe_provider_id:
        raise ModelCapabilityError("平台 ID 不能为空")
    payload = {
        "schema_version": 1,
        "provider_id": safe_provider_id,
        "source": str(source or "").strip(),
        **{
            field_name: _unique_strings((catalog or {}).get(field_name) or [])
            for field_name in NODE_MODEL_FIELDS.values()
        },
    }
    path = Path(root) / "data" / "model_capabilities" / "snapshots" / f"{safe_provider_id}-catalog.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _unique_strings(values: Iterable[Any]) -> List[str]:
    seen = set()
    result = []
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


class ModelCapabilityRegistry:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.registry_path = self.root / "data" / "model_capabilities" / "registry.json"

    def load(self) -> Dict[str, Any]:
        registry = _read_json(self.registry_path)
        profiles = {}
        for provider_ref in registry.get("providers") or []:
            relative = str(provider_ref.get("file") or "").strip()
            if not relative:
                continue
            profile = _read_json(self.root / relative)
            provider_id = str(profile.get("provider_id") or provider_ref.get("provider_id") or "").strip()
            if provider_id:
                profiles[provider_id] = profile
        return {"registry": registry, "profiles": profiles}

    def runninghub_official_snapshot_profiles(self) -> Dict[str, Dict[str, Any]]:
        path = self.root / "data" / "model_capabilities" / "snapshots" / "runninghub-official-public.json"
        if not path.is_file():
            return {}
        try:
            raw = _read_json(path)
        except (OSError, ValueError, TypeError):
            return {}
        items = raw.get("models") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            return {}
        profiles: Dict[str, Dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                profile = runninghub_profile_from_registry_item(item)
            except ModelCapabilityError:
                continue
            profiles[profile["model_id"]] = profile
        return profiles

    def runninghub_snapshot_profiles(self, region: str = "global") -> Dict[str, Dict[str, Any]]:
        safe_region = "cn" if str(region or "").strip().lower() == "cn" else "global"
        path = self.root / "data" / "model_capabilities" / "snapshots" / f"runninghub-{safe_region}.json"
        profiles: Dict[str, Dict[str, Any]] = self.runninghub_official_snapshot_profiles()
        if not path.is_file():
            return profiles
        try:
            raw = _read_json(path)
        except (OSError, ValueError, TypeError):
            return profiles
        items = raw.get("items") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return profiles
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                profile = runninghub_profile_from_registry_item(item)
            except ModelCapabilityError:
                continue
            profiles[profile["model_id"]] = profile
        for alias, official_id in RUNNINGHUB_PROFILE_ALIASES.items():
            source = profiles.get(official_id)
            if not source:
                continue
            profile = deepcopy(source)
            profile["model_id"] = alias
            profiles[alias] = profile
        return profiles

    def audit_catalog_coverage(
        self,
        provider_id: str,
        catalog: Dict[str, Any],
        region: str = "global",
    ) -> Dict[str, Any]:
        capability_id = PROVIDER_ALIASES.get(str(provider_id or "").strip().lower(), str(provider_id or "").strip().lower())
        loaded = self.load()
        profile_set = loaded["profiles"].get(capability_id) or {}
        indexed_profiles = {
            (str(item.get("model_id") or "").strip(), str(item.get("node_type") or "").strip()): item
            for item in profile_set.get("models") or []
            if str(item.get("model_id") or "").strip()
        }
        if capability_id == "runninghub":
            for model_id, profile in self.runninghub_snapshot_profiles(region).items():
                indexed_profiles[(model_id, str(profile.get("node_type") or "").strip())] = profile

        result = {
            "provider_id": capability_id,
            "total": 0,
            "ready": 0,
            "needs_profile": 0,
            "adapter_missing": 0,
            "deprecated": 0,
            "missing_model_ids": [],
            "adapter_missing_model_ids": [],
            "deprecated_model_ids": [],
        }
        seen = set()
        for field_name in dict.fromkeys(NODE_MODEL_FIELDS.values()):
            candidate_node_types = [
                node_type
                for node_type, mapped_field in NODE_MODEL_FIELDS.items()
                if mapped_field == field_name
            ]
            for model_id in _unique_strings((catalog or {}).get(field_name) or []):
                identity = (field_name, model_id)
                if identity in seen:
                    continue
                seen.add(identity)
                source = None
                for node_type in candidate_node_types:
                    candidate = indexed_profiles.get((model_id, node_type))
                    if self.readiness(candidate) != "ready":
                        candidate = dynamic_profile_for_model(capability_id, model_id, node_type) or candidate
                    if source is None and candidate:
                        source = candidate
                    if self.readiness(candidate) == "ready":
                        source = candidate
                        break
                readiness = self.readiness(source)
                result["total"] += 1
                result[readiness] += 1
                if readiness == "needs_profile":
                    result["missing_model_ids"].append(model_id)
                elif readiness == "adapter_missing":
                    result["adapter_missing_model_ids"].append(model_id)
                elif readiness == "deprecated":
                    result["deprecated_model_ids"].append(model_id)
        return result

    def validate_provider_manifest(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        errors: List[str] = []
        if not isinstance(manifest, dict):
            return {"valid": False, "errors": ["Manifest 必须是 JSON 对象"]}
        if manifest.get("schema_version") != 1:
            errors.append("schema_version 必须为 1")
        provider = manifest.get("provider")
        if not isinstance(provider, dict):
            errors.append("缺少 provider 对象")
            provider = {}
        provider_id = str(provider.get("id") or "").strip()
        if not provider_id or not __import__("re").fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", provider_id):
            errors.append("provider.id 必须是 2-63 位小写字母、数字或连字符")
        if not str(provider.get("name") or "").strip():
            errors.append("provider.name 不能为空")
        transport = manifest.get("transport")
        if not isinstance(transport, dict) or transport.get("type") not in {"http", "local_cli"}:
            errors.append("transport.type 必须是 http 或 local_cli")
        catalog = manifest.get("catalog")
        if not isinstance(catalog, dict) or catalog.get("mode") not in {"endpoint", "static", "cli"}:
            errors.append("catalog.mode 必须是 endpoint、static 或 cli")
        families = manifest.get("families")
        if not isinstance(families, list):
            errors.append("families 必须是数组")
            families = []
        elif not families:
            errors.append("families 至少包含一个模型家族")
        family_ids = set()
        model_ids = set()
        allowed_nodes = {"text_generation", "image_generation", "video_generation", "audio_generation", "music_generation"}
        for family_index, family in enumerate(families):
            prefix = f"families[{family_index}]"
            if not isinstance(family, dict):
                errors.append(f"{prefix} 必须是对象")
                continue
            family_id = str(family.get("family_id") or "").strip()
            if not family_id:
                errors.append(f"{prefix}.family_id 不能为空")
            elif family_id in family_ids:
                errors.append(f"模型家族重复：{family_id}")
            family_ids.add(family_id)
            if family.get("node_type") not in allowed_nodes:
                errors.append(f"{prefix}.node_type 不受支持")
            variants = family.get("variants")
            if not isinstance(variants, list) or not variants:
                errors.append(f"{prefix}.variants 至少包含一项")
                continue
            for variant_index, variant in enumerate(variants):
                variant_prefix = f"{prefix}.variants[{variant_index}]"
                if not isinstance(variant, dict):
                    errors.append(f"{variant_prefix} 必须是对象")
                    continue
                model_id = str(variant.get("model_id") or "").strip()
                if not model_id:
                    errors.append(f"{variant_prefix}.model_id 不能为空")
                elif model_id in model_ids:
                    errors.append(f"真实模型 ID 重复：{model_id}")
                model_ids.add(model_id)
                for field in ("variant_id", "operation"):
                    if not str(variant.get(field) or "").strip():
                        errors.append(f"{variant_prefix}.{field} 不能为空")
                mapping = variant.get("request_mapping")
                if not isinstance(mapping, dict) or not mapping:
                    errors.append(f"{variant_prefix}.request_mapping 不能为空")
                evidence = variant.get("evidence")
                if not isinstance(evidence, dict) or evidence.get("level") not in {
                    "runtime_verified", "official_schema", "official_documented", "model_card_only", "unknown"
                }:
                    errors.append(f"{variant_prefix}.evidence.level 无效")
                if not isinstance(evidence, dict) or not str(evidence.get("source") or "").strip():
                    errors.append(f"{variant_prefix}.evidence.source 不能为空")
        forbidden_keys = {"api_key", "apikey", "authorization", "cookie", "token", "secret", "shell", "script", "command"}
        def inspect(value: Any, path: str = "") -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    normalized = str(key).lower().replace("-", "_")
                    if normalized in forbidden_keys:
                        errors.append(f"Manifest 不允许字段：{path + '.' if path else ''}{key}")
                    inspect(item, f"{path}.{key}" if path else str(key))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    inspect(item, f"{path}[{index}]")
        inspect(manifest)
        return {
            "valid": not errors,
            "errors": errors,
            "summary": {
                "provider_id": provider_id,
                "family_count": len(family_ids),
                "variant_count": len(model_ids),
                "validation": "contract_validated" if not errors else "invalid",
                "network_requested": False,
            },
        }

    @staticmethod
    def capability_provider_id(provider: Dict[str, Any]) -> str:
        provider_id = str(provider.get("id") or "").strip().lower()
        protocol = str(provider.get("protocol") or "").strip().lower()
        return PROVIDER_ALIASES.get(provider_id) or PROVIDER_ALIASES.get(protocol) or provider_id

    @staticmethod
    def validation_mode(profile: Optional[Dict[str, Any]]) -> str:
        if not profile:
            return "blocked"
        if profile.get("status") != "confirmed":
            return "blocked"
        if profile.get("evidence_level") not in CONFIRMED_EVIDENCE:
            return "blocked"
        return "strict"

    @classmethod
    def readiness(cls, profile: Optional[Dict[str, Any]]) -> str:
        if not profile:
            return "needs_profile"
        if profile.get("status") == "deprecated":
            return "deprecated"
        explicit = str(profile.get("readiness") or "").strip()
        if explicit in {"ready", "needs_profile", "adapter_missing", "deprecated"}:
            return explicit
        return "ready" if cls.validation_mode(profile) == "strict" else "needs_profile"

    @staticmethod
    def _family_catalog(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        families: Dict[tuple, Dict[str, Any]] = {}
        order: List[tuple] = []
        for model in models:
            family_id = str(model.get("family_id") or model.get("model_id") or "").strip()
            node_type = str(model.get("node_type") or "").strip()
            if not family_id:
                continue
            family_key = (family_id, node_type)
            if family_key not in families:
                order.append(family_key)
                families[family_key] = {
                    "family_id": family_id,
                    "display_name": model.get("family_name") or model.get("display_name") or family_id,
                    "display_name_en": model.get("family_name_en") or "",
                    "node_type": node_type,
                    "provider_id": model.get("provider_id") or "",
                    "readiness": "ready" if model.get("runnable") else model.get("readiness") or "needs_profile",
                    "runnable": bool(model.get("runnable")),
                    "variants": [],
                }
            family = families[family_key]
            family["variants"].append(model)
            if model.get("runnable"):
                family["runnable"] = True
                family["readiness"] = "ready"
        return [families[family_key] for family_key in order]

    def _runninghub_catalog_scopes(self, provider: Dict[str, Any]):
        """把一个 RunningHub provider 展开为已启用站点的只读能力 scope。"""
        if self.capability_provider_id(provider) != "runninghub":
            return [(provider, "")]
        regions = provider.get("rh_regions") if isinstance(provider.get("rh_regions"), dict) else {}
        if not regions:
            return [(provider, str(provider.get("rh_region") or "global").strip().lower() or "global")]
        locked = str(provider.get("_runninghub_selected_region") or "").strip().lower()
        if locked:
            candidate_regions = [locked]
        else:
            candidate_regions = [
                region for region, config in regions.items()
                if isinstance(config, dict) and config.get("enabled") is True
            ]
            # 兼容尚未经过主程序 normalize_provider 的测试/调用方输入；正式配置
            # 会显式写入 enabled，不能把缺失字段当成双站启用。
            if not candidate_regions and not any(
                isinstance(config, dict) and isinstance(config.get("enabled"), bool)
                for config in regions.values()
            ):
                candidate_regions = [str(provider.get("rh_region") or "global").strip().lower() or "global"]
            active_region = str(provider.get("rh_region") or "").strip().lower()
            if active_region in candidate_regions:
                candidate_regions = [active_region] + [region for region in candidate_regions if region != active_region]
        scopes = []
        for region in candidate_regions:
            config = regions.get(region)
            if not isinstance(config, dict) or (locked and config.get("enabled") is not True):
                continue
            scoped = dict(provider)
            scoped["rh_region"] = region
            for field_name in set(NODE_MODEL_FIELDS.values()):
                scoped[field_name] = deepcopy(config.get(field_name) or [])
            scoped["model_names"] = deepcopy(config.get("model_names") or {})
            scoped["rh_apps"] = deepcopy(config.get("rh_apps") or [])
            scoped["rh_workflows"] = deepcopy(config.get("rh_workflows") or [])
            scopes.append((scoped, region))
        return scopes

    def _catalog_models_for_provider(self, provider, capability_id, profile_set, region=""):
        indexed_profiles = {
            (str(item.get("model_id") or "").strip(), str(item.get("node_type") or "").strip()): item
            for item in profile_set.get("models") or []
            if str(item.get("model_id") or "").strip()
        }
        if capability_id == "runninghub":
            for model_id, profile in self.runninghub_snapshot_profiles(region or provider.get("rh_region") or "global").items():
                indexed_profiles[(model_id, str(profile.get("node_type") or "").strip())] = profile
        models = []
        for node_type, field_name in NODE_MODEL_FIELDS.items():
            configured_model_ids = _unique_strings(provider.get(field_name) or [])
            if capability_id == "ai-money":
                configured_model_ids = _unique_strings(normalize_laohu_model_id(model_id) for model_id in configured_model_ids)
            for model_id in configured_model_ids:
                source = indexed_profiles.get((model_id, node_type))
                if self.readiness(source) != "ready":
                    source = dynamic_profile_for_model(capability_id, model_id, node_type) or source
                if node_type == "music_generation" and not source:
                    continue
                if node_type == "audio_generation" and not source:
                    music_source = indexed_profiles.get((model_id, "music_generation"))
                    if self.readiness(music_source) == "ready":
                        continue
                    if dynamic_profile_for_model(capability_id, model_id, "music_generation"):
                        continue
                item = deepcopy(source) if source else {
                    "model_id": model_id,
                    "node_type": node_type,
                    "operation": "compatible",
                    "status": "pending",
                    "version": 0,
                    "evidence_level": "unknown",
                    "inputs": {},
                    "parameters": {},
                    "note": "该模型来自用户配置，尚未绑定经过核实的能力档案。",
                }
                item["node_type"] = node_type
                item["validation_mode"] = self.validation_mode(source)
                item["readiness"] = self.readiness(source)
                item["runnable"] = item["validation_mode"] == "strict" and item["readiness"] == "ready"
                item["provider_id"] = str(provider.get("id") or "").strip()
                item["capability_provider_id"] = capability_id
                item["family_id"] = str(item.get("family_id") or item["model_id"]).strip()
                item["family_name"] = item.get("family_name") or item.get("display_name") or item["family_id"]
                item["variant_id"] = str(item.get("variant_id") or item.get("operation") or item["model_id"]).strip()
                item["inputs"] = deepcopy(item.get("inputs") or {})
                item["parameters"] = deepcopy(item.get("parameters") or {})
                item["selection_unavailable_reason"] = generation_visibility_issue(item)
                item["selectable"] = item["runnable"] and not item["selection_unavailable_reason"]
                if capability_id == "runninghub":
                    item["regions"] = [region or str(provider.get("rh_region") or "global").strip().lower()]
                models.append(item)
            models = normalize_model_classifications(models, capability_id)
        return models

    def build_catalog(self, providers: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        loaded = self.load()
        registry = loaded["registry"]
        profile_sets = loaded["profiles"]
        runtime_providers = []
        for provider in providers or []:
            if provider.get("enabled") is False:
                continue
            capability_id = self.capability_provider_id(provider)
            profile_set = profile_sets.get(capability_id) or {}
            scopes = self._runninghub_catalog_scopes(provider)
            models_by_key = {}
            for scoped, region in scopes:
                for model in self._catalog_models_for_provider(scoped, capability_id, profile_set, region):
                    key = (
                        str(model.get("model_id") or ""),
                        str(model.get("node_type") or ""),
                        str(model.get("variant_id") or model.get("operation") or ""),
                    )
                    existing = models_by_key.get(key)
                    if existing is None:
                        if capability_id == "runninghub":
                            existing_region = (model.get("regions") or [region or "global"])[0]
                            existing = model
                            existing["region_profiles"] = {
                                existing_region: {
                                    field: deepcopy(model.get(field))
                                    for field in (
                                        "model_id", "node_type", "operation", "family_id", "family_name",
                                        "variant_id", "inputs", "parameters", "platform", "validation_mode",
                                        "readiness", "runnable", "selectable", "selection_unavailable_reason",
                                    ) if field in model
                                }
                            }
                        else:
                            existing = model
                        models_by_key[key] = model
                        continue
                    for candidate_region in model.get("regions") or []:
                        if candidate_region not in (existing.setdefault("regions", [])):
                            existing["regions"].append(candidate_region)
                        if capability_id == "runninghub":
                            existing.setdefault("region_profiles", {})[candidate_region] = {
                                field: deepcopy(model.get(field))
                                for field in (
                                    "model_id", "node_type", "operation", "family_id", "family_name",
                                    "variant_id", "inputs", "parameters", "platform", "validation_mode",
                                    "readiness", "runnable", "selectable", "selection_unavailable_reason",
                                ) if field in model
                            }
            models = list(models_by_key.values())
            combined_provider = dict(provider)
            for node_type, field_name in NODE_MODEL_FIELDS.items():
                values = []
                for scoped, _region in scopes:
                    values.extend(scoped.get(field_name) or [])
                combined_provider[field_name] = _unique_strings(values)
            configured_order_by_type = {
                node_type: {
                    model_id: index
                    for index, model_id in enumerate(_unique_strings(
                        normalize_laohu_model_id(value) if capability_id == "ai-money" else value
                        for value in (combined_provider.get(field_name) or [])
                    ))
                }
                for node_type, field_name in NODE_MODEL_FIELDS.items()
            }
            node_type_order = {node_type: index for index, node_type in enumerate(NODE_MODEL_FIELDS)}
            models.sort(key=lambda item: (
                node_type_order.get(str(item.get("node_type") or ""), len(node_type_order)),
                configured_order_by_type.get(str(item.get("node_type") or ""), {}).get(
                    str(item.get("model_id") or ""),
                    len(configured_order_by_type.get(str(item.get("node_type") or ""), {})),
                ),
            ))
            region_candidates = []
            if capability_id == "runninghub":
                regions = provider.get("rh_regions") if isinstance(provider.get("rh_regions"), dict) else {}
                for region, config in regions.items():
                    if not isinstance(config, dict):
                        continue
                    region_candidates.append({
                        "region": region,
                        "enabled": config.get("enabled") is True,
                        "base_url": config.get("base_url") or "",
                        "model_count": sum(len(_unique_strings(config.get(field) or [])) for field in set(NODE_MODEL_FIELDS.values())),
                        "app_count": len(config.get("rh_apps") or []),
                        "workflow_count": len(config.get("rh_workflows") or []),
                    })
            runtime_providers.append({
                "id": str(provider.get("id") or "").strip(),
                "name": provider.get("name") or provider.get("id") or capability_id,
                "protocol": provider.get("protocol") or "openai",
                "capability_provider_id": capability_id,
                "profile_updated_at": profile_set.get("updated_at") or "",
                "regions": region_candidates,
                "models": models,
                "families": self._family_catalog(models),
            })
        return {
            "schema_version": registry.get("schema_version") or 1,
            "updated_at": registry.get("updated_at") or "",
            "providers": runtime_providers,
        }

    def find_model(
        self,
        providers: Iterable[Dict[str, Any]],
        provider_id: str,
        model_id: str,
        node_type: str,
    ) -> Optional[Dict[str, Any]]:
        # 单模型预检无需重建所有平台目录，仍从用户启用白名单筛选。
        selected_providers = []
        for provider in providers:
            if provider.get("id") != provider_id:
                continue
            selected = dict(provider)
            field = NODE_MODEL_FIELDS.get(node_type)
            requested = normalize_laohu_model_id(model_id) if self.capability_provider_id(provider) == "ai-money" else model_id
            for key in set(NODE_MODEL_FIELDS.values()):
                selected[key] = [value for value in (provider.get(key) or []) if key == field and (normalize_laohu_model_id(value) if self.capability_provider_id(provider) == "ai-money" else value) == requested]
            selected_providers.append(selected)
        catalog = self.build_catalog(selected_providers)
        for provider in catalog["providers"]:
            if provider["id"] != provider_id:
                continue
            requested_model_id = normalize_laohu_model_id(model_id) if provider.get("capability_provider_id") == "ai-money" else model_id
            for model in provider["models"]:
                if model["model_id"] == requested_model_id and model["node_type"] == node_type:
                    return model
        return None

    def resolve_family_variant(
        self,
        providers: Iterable[Dict[str, Any]],
        provider_id: str,
        family_id: str,
        node_type: str,
        input_counts: Optional[Dict[str, int]] = None,
        input_roles: Optional[Dict[str, int]] = None,
        parameters: Optional[Dict[str, Any]] = None,
        operation: str = "",
    ) -> Dict[str, Any]:
        catalog = self.build_catalog(providers)
        provider = next((item for item in catalog["providers"] if item["id"] == provider_id), None)
        if not provider:
            raise ModelCapabilityError(f"平台 {provider_id} 未启用")
        family = next((item for item in provider["families"] if item["family_id"] == family_id and item["node_type"] == node_type), None)
        if not family:
            raise ModelCapabilityError(f"平台 {provider_id} 未启用模型家族 {family_id}")
        candidates = []
        rejection_reasons = []
        for variant in family.get("variants") or []:
            if operation and operation not in {variant.get("operation"), variant.get("variant_id")}:
                continue
            try:
                candidates.append(self.validate_request(
                    providers,
                    provider_id,
                    variant.get("model_id") or "",
                    node_type,
                    input_counts=input_counts,
                    input_roles=input_roles,
                    parameters=parameters,
                ))
            except ModelCapabilityError as exc:
                reason = str(exc).strip()
                if reason and reason not in rejection_reasons:
                    rejection_reasons.append(reason)
                continue
        if not candidates:
            detail = "；".join(rejection_reasons[:2])
            suffix = f"原因：{detail}" if detail else "请检查输入类型、数量和参数是否与模型档案一致"
            raise ModelCapabilityError(f"模型家族 {family_id} 没有匹配当前输入和参数的任务变体。{suffix}")
        if len(candidates) > 1:
            variants = "、".join(str(item.get("variant_id") or item.get("operation") or item.get("model_id")) for item in candidates)
            raise ModelCapabilityError(f"模型家族 {family_id} 存在多个匹配变体：{variants}，请选择操作模式")
        return candidates[0]

    @staticmethod
    def _media_limits(inputs: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
        limits: Dict[str, Dict[str, int]] = {}
        for spec in (inputs or {}).values():
            media_type = str(spec.get("media_type") or "").strip()
            if not media_type:
                continue
            current = limits.setdefault(media_type, {"min": 0, "max": 0})
            current["min"] += max(0, int(spec.get("min") or 0))
            raw_max = spec.get("max")
            current["max"] += max(0, int(raw_max if raw_max is not None else 1))
        return limits

    @staticmethod
    def _normalize_input_role(value: Any) -> str:
        role = str(value or "").strip().lower().replace("-", "_")
        return INPUT_ROLE_ALIASES.get(role, role)

    @classmethod
    def _role_limits(cls, inputs: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        limits: Dict[str, Dict[str, Any]] = {}
        for key, spec in (inputs or {}).items():
            role = cls._normalize_input_role(spec.get("role") or key)
            if not role:
                continue
            current = limits.setdefault(role, {
                "min": 0,
                "max": 0,
                "media_type": str(spec.get("media_type") or "").strip(),
            })
            current["min"] += max(0, int(spec.get("min") or 0))
            raw_max = spec.get("max")
            current["max"] += max(0, int(raw_max if raw_max is not None else 1))
        return limits

    @staticmethod
    def _effective_parameters(profile: Dict[str, Any], parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        values = deepcopy(parameters or {})
        for key, spec in (profile.get("parameters") or {}).items():
            if not spec.get("ui_hidden") or values.get(key) not in (None, ""):
                continue
            default = spec.get("default")
            if str(spec.get("type") or "").strip().lower() == "model":
                default = profile.get("model_id")
            if default not in (None, ""):
                values[key] = default
        return values

    @staticmethod
    def _request_mapping_target(profile: Dict[str, Any], input_key: str) -> str:
        mapping = profile.get("request_mapping") or {}
        direct = mapping.get(input_key)
        if direct:
            return str(direct)
        normalized = str(input_key or "").strip().lower().replace("-", "_")
        specs = profile.get("inputs") or {}
        role_matches = [
            key for key, spec in specs.items()
            if str(spec.get("role") or key).strip().lower().replace("-", "_") == normalized
            and mapping.get(key)
        ]
        if len(role_matches) == 1:
            return str(mapping[role_matches[0]])
        generic_aliases = {
            "image": "image",
            "images": "image",
            "reference": "image",
            "reference_image": "image",
            "video": "video",
            "videos": "video",
            "source_video": "video",
            "reference_video": "video",
            "audio": "audio",
            "audios": "audio",
            "reference_audio": "audio",
            "text": "text",
            "prompt": "text",
        }
        media_type = generic_aliases.get(normalized)
        if not media_type:
            return ""
        media_matches = [
            key for key, spec in specs.items()
            if str(spec.get("media_type") or "").strip().lower() == media_type
            and mapping.get(key)
        ]
        return str(mapping[media_matches[0]]) if len(media_matches) == 1 else ""

    def validate_request(
        self,
        providers: Iterable[Dict[str, Any]],
        provider_id: str,
        model_id: str,
        node_type: str,
        input_counts: Optional[Dict[str, int]] = None,
        input_roles: Optional[Dict[str, int]] = None,
        parameters: Optional[Dict[str, Any]] = None,
        input_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        profile = self.find_model(providers, provider_id, model_id, node_type)
        if not profile:
            raise ModelCapabilityError(f"平台 {provider_id} 未启用模型 {model_id}")
        if profile["validation_mode"] != "strict":
            readiness = profile.get("readiness") or "needs_profile"
            if readiness == "adapter_missing":
                raise ModelCapabilityError(f"模型 {model_id} 的平台适配器尚未完成，不能发起请求")
            raise ModelCapabilityError(f"模型 {model_id} 缺少经过核实的能力档案，不能发起请求")
        if not profile.get("runnable"):
            raise ModelCapabilityError(f"模型 {model_id} 当前不可运行：{profile.get('readiness') or 'unknown'}")

        parameters = self._effective_parameters(profile, parameters)
        counts: Dict[str, int] = {}
        declared_inputs = profile.get("inputs") or {}
        for key, value in (input_counts or {}).items():
            count = max(0, int(value or 0))
            spec = declared_inputs.get(str(key)) or {}
            media_type = str(spec.get("media_type") or "").strip() or {
                "prompt": "text",
                "system_prompt": "text",
                "reference": "image",
                "reference_image": "image",
                "first_frame": "image",
                "last_frame": "image",
                "source_video": "video",
                "reference_audio": "audio",
                "audio": "audio",
                "image": "image",
                "video": "video",
                "text": "text",
            }.get(str(key), str(key))
            counts[media_type] = counts.get(media_type, 0) + count
        limits = self._media_limits(profile.get("inputs") or {})
        labels = {"text": "文本", "image": "图片", "video": "视频", "audio": "音频"}
        for media_type, count in counts.items():
            limit = limits.get(media_type)
            label = labels.get(media_type, media_type)
            if count > 0 and not limit:
                raise ModelCapabilityError(f"模型 {model_id} 不支持{label}输入")
            if limit and count > limit["max"]:
                raise ModelCapabilityError(f"模型 {model_id} 最多接收 {limit['max']} 个{label}输入")
        for media_type, limit in limits.items():
            if counts.get(media_type, 0) < limit["min"]:
                label = labels.get(media_type, media_type)
                raise ModelCapabilityError(f"模型 {model_id} 至少需要 {limit['min']} 个{label}输入")
        requires_any_media = [
            str(media_type or "").strip().lower()
            for media_type in (profile.get("requires_any_media") or [])
            if str(media_type or "").strip()
        ]
        if requires_any_media and not any(counts.get(media_type, 0) > 0 for media_type in requires_any_media):
            readable = "、".join(labels.get(media_type, media_type) for media_type in requires_any_media)
            raise ModelCapabilityError(f"模型 {model_id} 至少需要一个{readable}参考素材")

        normalized_roles: Dict[str, int] = {}
        for raw_role, value in (input_roles or {}).items():
            role = self._normalize_input_role(raw_role)
            count = max(0, int(value or 0))
            if role and count:
                normalized_roles[role] = normalized_roles.get(role, 0) + count
        if normalized_roles:
            role_limits = self._role_limits(declared_inputs)
            role_media_counts: Dict[str, int] = {}
            for role, count in normalized_roles.items():
                limit = role_limits.get(role)
                if not limit:
                    generic_media_type = "image" if role == "reference" else ""
                    has_assignable_role = generic_media_type and any(
                        str(item.get("media_type") or "").strip() == generic_media_type
                        for item in role_limits.values()
                    )
                    if has_assignable_role and count <= counts.get(generic_media_type, 0):
                        continue
                    raise ModelCapabilityError(f"模型 {model_id} 不支持输入角色 {role}")
                if count > limit["max"]:
                    raise ModelCapabilityError(f"模型 {model_id} 的输入角色 {role} 最多接收 {limit['max']} 项")
                media_type = str(limit.get("media_type") or "").strip()
                if media_type:
                    role_media_counts[media_type] = role_media_counts.get(media_type, 0) + count
            covered_media_types = set(role_media_counts)
            for role, limit in role_limits.items():
                if limit.get("media_type") in covered_media_types and limit["min"] > 0 and normalized_roles.get(role, 0) < limit["min"]:
                    raise ModelCapabilityError(f"模型 {model_id} 至少需要 {limit['min']} 个 {role} 输入")
            for media_type, role_count in role_media_counts.items():
                if role_count > counts.get(media_type, 0):
                    raise ModelCapabilityError(f"输入角色数量超过实际{labels.get(media_type, media_type)}输入数量")

        if input_metadata is not None:
            self.validate_input_metadata(profile, input_metadata)

        allowed_parameters = set((profile.get("parameters") or {}).keys())
        required_parameters = sorted(
            key for key, spec in (profile.get("parameters") or {}).items()
            if (spec.get("required") or str(spec.get("level") or "").strip().lower() == "required")
            and spec.get("default") in (None, "")
            and (parameters or {}).get(key) in (None, "")
        )
        if required_parameters:
            raise ModelCapabilityError(f"模型 {model_id} 缺少必填参数：{', '.join(required_parameters)}")
        unsupported = sorted(
            key for key, value in (parameters or {}).items()
            if value is not None and value != "" and key not in allowed_parameters
        )
        if unsupported:
            raise ModelCapabilityError(f"模型 {model_id} 不支持参数：{', '.join(unsupported)}")
        from studio_model_evaluation import validate_parameter_value

        for key, value in (parameters or {}).items():
            if value is None or value == "" or key not in allowed_parameters:
                continue
            spec = profile["parameters"][key]
            if validate_parameter_value(spec, value):
                if spec.get("type") in {"integer", "number"} and not isinstance(value, bool):
                    try:
                        numeric = float(value)
                    except (TypeError, ValueError):
                        numeric = float('nan')
                    if spec.get("min") is not None and numeric < float(spec["min"]):
                        raise ModelCapabilityError(f"模型 {model_id} 的参数 {key} 不能小于 {spec['min']}")
                    if spec.get("max") is not None and numeric > float(spec["max"]):
                        raise ModelCapabilityError(f"模型 {model_id} 的参数 {key} 不能大于 {spec['max']}")
                raise ModelCapabilityError(f"模型 {model_id} 的参数 {key} 不支持取值 {value}")
        if str(profile.get("model_id") or "").startswith(("MiniMax-H3", "laohu-image-g-v2.5-", "suno-")):
            from laohu_protocols import validate_parameters
            try:
                validate_parameters(profile["model_id"], parameters, counts, normalized_roles, input_metadata)
            except ValueError as exc:
                raise ModelCapabilityError(str(exc)) from exc
        return profile

    @staticmethod
    def _format_bytes(value: Any) -> str:
        size = max(0, int(float(value or 0)))
        if size >= 1024 * 1024 and size % (1024 * 1024) == 0:
            return f"{size // (1024 * 1024)} MiB"
        if size >= 1024 and size % 1024 == 0:
            return f"{size // 1024} KiB"
        return f"{size} B"

    @classmethod
    def validate_input_metadata(cls, profile: Dict[str, Any], input_metadata: Dict[str, Any]) -> None:
        constraint_keys = {
            "min_chars", "max_chars", "min_bytes", "max_bytes",
            "min_width", "max_width", "min_height", "max_height",
            "min_pixels", "max_pixels", "max_aspect_ratio",
            "min_duration_seconds", "max_duration_seconds", "max_total_duration_seconds",
        }
        model_id = str(profile.get("model_id") or "当前模型")
        for key, spec in (profile.get("inputs") or {}).items():
            constraints = {name: spec.get(name) for name in constraint_keys if spec.get(name) is not None}
            if not constraints:
                continue
            raw_items = (input_metadata or {}).get(key)
            if raw_items is None:
                raw_items = (input_metadata or {}).get(str(spec.get("role") or ""))
            if isinstance(raw_items, dict):
                items = [raw_items]
            elif isinstance(raw_items, list):
                items = [item if isinstance(item, dict) else {} for item in raw_items]
            else:
                items = []
            if not items:
                continue
            total_duration = 0.0
            for index, item in enumerate(items):
                name = str(item.get("name") or spec.get("label") or f"{key} {index + 1}")
                def numeric(field: str, readable_name: str) -> float:
                    value = item.get(field)
                    if value is None or value == "":
                        raise ModelCapabilityError(f"模型 {model_id} 无法读取「{name}」的{readable_name}，请重新上传后再运行")
                    try:
                        return float(value)
                    except (TypeError, ValueError) as exc:
                        raise ModelCapabilityError(f"模型 {model_id} 无法读取「{name}」的{readable_name}，请重新上传后再运行") from exc
                if "min_chars" in constraints or "max_chars" in constraints:
                    chars = numeric("characters", "文本长度")
                    if "min_chars" in constraints and chars < float(constraints["min_chars"]):
                        raise ModelCapabilityError(f"模型 {model_id} 的「{name}」当前 {int(chars)} 个字符，至少需要 {constraints['min_chars']} 个字符")
                    if "max_chars" in constraints and chars > float(constraints["max_chars"]):
                        raise ModelCapabilityError(f"模型 {model_id} 的「{name}」当前 {int(chars)} 个字符，最多允许 {constraints['max_chars']} 个字符")
                if "min_bytes" in constraints or "max_bytes" in constraints:
                    size = numeric("bytes", "文件大小")
                    if "min_bytes" in constraints and size < float(constraints["min_bytes"]):
                        raise ModelCapabilityError(f"模型 {model_id} 的「{name}」不能小于 {cls._format_bytes(constraints['min_bytes'])}")
                    if "max_bytes" in constraints and size > float(constraints["max_bytes"]):
                        raise ModelCapabilityError(f"模型 {model_id} 的「{name}」不能超过 {cls._format_bytes(constraints['max_bytes'])}")
                needs_dimensions = any(field in constraints for field in ("min_width", "max_width", "min_height", "max_height", "min_pixels", "max_pixels", "max_aspect_ratio"))
                if needs_dimensions:
                    width = numeric("width", "宽度")
                    height = numeric("height", "高度")
                    for field, value, label, direction in (
                        ("min_width", width, "宽度", "小于"), ("max_width", width, "宽度", "大于"),
                        ("min_height", height, "高度", "小于"), ("max_height", height, "高度", "大于"),
                    ):
                        if field not in constraints:
                            continue
                        limit = float(constraints[field])
                        invalid = value < limit if field.startswith("min_") else value > limit
                        if invalid:
                            raise ModelCapabilityError(f"模型 {model_id} 的「{name}」{label}不能{direction} {constraints[field]} 像素")
                    pixels = width * height
                    if "min_pixels" in constraints and pixels < float(constraints["min_pixels"]):
                        raise ModelCapabilityError(f"模型 {model_id} 的「{name}」总像素不能小于 {constraints['min_pixels']}")
                    if "max_pixels" in constraints and pixels > float(constraints["max_pixels"]):
                        raise ModelCapabilityError(f"模型 {model_id} 的「{name}」总像素不能超过 {constraints['max_pixels']}")
                    if "max_aspect_ratio" in constraints:
                        ratio = max(width / max(height, 1), height / max(width, 1))
                        if ratio > float(constraints["max_aspect_ratio"]):
                            raise ModelCapabilityError(f"模型 {model_id} 的「{name}」宽高比不能超过 {constraints['max_aspect_ratio']}:1")
                if "min_duration_seconds" in constraints or "max_duration_seconds" in constraints or "max_total_duration_seconds" in constraints:
                    duration = numeric("duration_seconds", "媒体时长")
                    total_duration += duration
                    if "min_duration_seconds" in constraints and duration < float(constraints["min_duration_seconds"]):
                        raise ModelCapabilityError(f"模型 {model_id} 的「{name}」时长不能短于 {constraints['min_duration_seconds']} 秒")
                    if "max_duration_seconds" in constraints and duration > float(constraints["max_duration_seconds"]):
                        raise ModelCapabilityError(f"模型 {model_id} 的「{name}」时长不能超过 {constraints['max_duration_seconds']} 秒")
            if "max_total_duration_seconds" in constraints and total_duration > float(constraints["max_total_duration_seconds"]):
                label = str(spec.get("label") or key)
                raise ModelCapabilityError(f"模型 {model_id} 的「{label}」总时长不能超过 {constraints['max_total_duration_seconds']} 秒")

    @staticmethod
    def _set_path(target: Dict[str, Any], path: str, value: Any) -> None:
        parts = [part for part in str(path or "").split(".") if part]
        if not parts:
            return
        current = target
        for part in parts[:-1]:
            existing = current.get(part)
            if not isinstance(existing, dict):
                existing = {}
                current[part] = existing
            current = existing
        current[parts[-1]] = value

    def build_dry_run(
        self,
        profile: Dict[str, Any],
        inputs: Optional[Dict[str, Any]] = None,
        parameters: Optional[Dict[str, Any]] = None,
        input_roles: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        if profile.get("validation_mode") != "strict" or not profile.get("runnable"):
            raise ModelCapabilityError("只有能力档案和适配器均已就绪的模型才能生成 dry-run 请求")
        inputs = deepcopy(inputs or {})
        parameters = deepcopy(parameters or {})
        effective_parameters = self._effective_parameters(profile, parameters)
        mapping = profile.get("request_mapping") or {}
        platform_request: Dict[str, Any] = {}
        for key, value in {**inputs, **effective_parameters}.items():
            if value is None or value == "":
                continue
            target = self._request_mapping_target(profile, key)
            if target:
                self._set_path(platform_request, target, value)
        output_media_type = str((profile.get("output") or {}).get("media_type") or "").strip()
        if output_media_type == "chat":
            output_media_type = "text"
        return {
            "standard_request": {
                "provider_id": profile.get("provider_id") or "",
                "family_id": profile.get("family_id") or profile.get("model_id") or "",
                "variant_id": profile.get("variant_id") or profile.get("operation") or "",
                "model_id": profile.get("model_id") or "",
                "node_type": profile.get("node_type") or "",
                "operation": profile.get("operation") or "",
                "profile_version": profile.get("version") or 0,
                "inputs": inputs,
                "input_roles": deepcopy(input_roles or {}),
                "parameters": parameters,
            },
            "platform_request": platform_request,
            "result_contract": {
                "media_type": output_media_type,
                "min": (profile.get("output") or {}).get("min"),
                "max": (profile.get("output") or {}).get("max"),
                "async": bool((profile.get("output") or {}).get("async")),
            },
            "network_requested": False,
            "validation": "contract_validated",
        }

    def platform_parameters(self, profile: Dict[str, Any], parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.build_dry_run(profile, parameters=parameters or {})["platform_request"]
