"""模块与槽位模型注册（P6）。

依据：《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§10.2、§10.4、§10.5、§10.8、§16 P6。

职责：
    - 声明每个模块的选择基数（多选候选池 / 固定单选槽位）与槽位契约；
    - 校验一个可执行选项是否满足某个槽位的契约；
    - 供 Hypit 与未来模块复用，不复制平台适配器、不新建项目级模型设置。

复用原则（§14.1）：Hypit 支持边界直接取自 `studio_hypit_models.SUPPORTED_HYPIT_CAPABILITIES`，
不在这里另写一份能力清单，避免两处漂移。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from studio_modules import studio_module_label

try:  # FastAPI 在运行环境里一定存在；缺失时本模块仍可用于纯逻辑测试
    from fastapi import Request
except Exception:  # pragma: no cover
    Request = None  # type: ignore[assignment]

MODULE_SCHEMA_VERSION = 1

# 输出类型 → 期望的媒体与集合语义（§10.5 expected_output）
_OUTPUT_MEDIA = {
    "text_generation": {"media_type": "text", "collection": False},
    "image_generation": {"media_type": "image", "collection": True},
    "video_generation": {"media_type": "video", "collection": True},
    "audio_generation": {"media_type": "audio", "collection": True},
    "music_generation": {"media_type": "audio", "collection": True},
}

# 槽位 → 该槽位在本项目里实际可发送的输入角色（§10.5 supported_input_roles）
_SLOT_INPUT_ROLES = {
    "text": ["prompt", "system_prompt", "reference", "source_video", "reference_audio"],
    "image": ["prompt", "reference"],
    "video": ["prompt", "reference", "first_frame", "last_frame", "source_video", "reference_audio"],
    "audio": ["prompt", "reference_audio"],
    "voice": ["prompt", "reference_audio"],
    "music": ["prompt", "reference_audio"],
}

# 固定生成槽只接受其真正实现的用途，不把上传、查询、放大、字幕或 3D 工具当生成器。
_SLOT_OPERATIONS = {
    'text': {'chat', 'chat_or_agent_text', 'multimodal_chat', 'prompt_enhancement'},
    'image': {'text_to_image', 'image_to_image', 'text_to_image_or_image_to_image',
              'text_or_image_to_image', 'text_or_reference_to_image', 'midjourney_imagine'},
    'video': {'text_to_video', 'image_to_video', 'reference_to_video', 'multimodal_to_video',
              'start_end_to_video', 'text_to_video_or_image_to_video', 'text_or_image_to_video',
              'text_or_reference_to_video'},
    'audio': {'speech_or_audio', 'sound_effects', 'text_to_sound', 'music_sounds'},
    'voice': {'text_to_speech', 'text_to_audio', 'speech_or_audio'},
    'music': {'music', 'music_song', 'music_to_music', 'flowmusic_generation'},
}


def hypit_profile_reasons(slot_id: str, profile: Dict[str, Any]) -> List[str]:
    from model_capabilities import generation_visibility_issue
    reasons = []
    if generation_visibility_issue(profile) or profile.get('selectable') is False:
        reasons.append('PROFILE_UNCONFIRMED')
    if profile.get('runnable') is False or profile.get('readiness') not in (None, 'ready'):
        reasons.append('ADAPTER_MISSING')
    if profile.get('operation') not in _SLOT_OPERATIONS.get(slot_id, set()):
        reasons.append('OPERATION_NOT_ALLOWED')
    inputs = profile.get('inputs') or {}
    if not any(spec.get('media_type') == 'text' for spec in inputs.values()):
        reasons.append('INPUT_TYPE_UNSUPPORTED')
    roles = _SLOT_INPUT_ROLES.get(slot_id, [])
    for key, spec in inputs.items():
        role = spec.get('role') or key
        if role.startswith('reference_') and spec.get('media_type') == 'image':
            role = 'reference'
        if spec.get('min', 0) and role not in roles:
            reasons.append('ROLE_CONFLICT')
    # 这些工具的上游粗分类也叫 music，但不返回可用于成片的音乐。
    model_id = str(profile.get('model_id') or profile.get('catalog_model_id') or '').lower()
    if model_id.endswith(('-lyrics', '/music-cover-preprocess', '-create-model')):
        reasons.append('OPERATION_NOT_ALLOWED')
    # RunningHub 快照将 HYPIR 登记为 image-enhance；它是增强工具，不能作为通用生图源。
    if model_id in {'hypir-balance', 'hypir-ultra'}:
        reasons.append('OPERATION_NOT_ALLOWED')
    return list(dict.fromkeys(reasons))

# 槽位 → 需要的调用场景（§10.5 required_input_scenarios）
_SLOT_SCENARIOS = {
    "text": ["text_prompt"],
    "image": ["text_prompt", "image_reference"],
    "video": ["text_prompt", "image_reference"],
    "audio": ["text_prompt"],
    "voice": ["text_prompt", "voice_reference"],
}

_ARTICLE_SLOT_NODE_TYPES = {
    "text": "text_generation",
    "image": "image_generation",
    "video": "video_generation",
    "audio": "audio_generation",
    "music": "music_generation",
    # 语音和普通音频最终都由 audio_generation 宿主执行，语义槽位仍分别保留。
    "voice": "audio_generation",
}


def music_slot_descriptors() -> List[Dict[str, Any]]:
    """歌曲/封面配置槽复用共享模型目录与普通画布的执行节点契约。"""
    labels = {
        "music": {"zh": "歌曲", "en": "Song"},
        "image": {"zh": "封面", "en": "Cover"},
    }
    descriptors = []
    for slot, node_type in (("music", "music_generation"), ("image", "image_generation")):
        descriptors.append({
            "id": slot,
            "module_id": "music",
            "selection_policy": "fixed",
            "node_type": node_type,
            "capability_name": node_type.replace("_", "-"),
            "label": dict(labels[slot]),
            "expected_output": dict(_OUTPUT_MEDIA[node_type]),
            "allowed_operations": sorted(_SLOT_OPERATIONS[slot]),
            "required_input_scenarios": list(_SLOT_SCENARIOS.get(slot, ["text_prompt"])),
            "supported_input_roles": list(_SLOT_INPUT_ROLES[slot]),
            "runtime_model_override": "allow",
            "runtime_parameter_overrides": "schema_allowlist",
        })
    return descriptors


def article_slot_descriptors() -> List[Dict[str, Any]]:
    """为文章设置图声明实际画布执行类型；只按共享模型目录的输出契约筛选。"""
    labels = {
        "text": {"zh": "文本", "en": "Text"},
        "image": {"zh": "图片", "en": "Image"},
        "video": {"zh": "视频", "en": "Video"},
        "audio": {"zh": "音效", "en": "Sound effects"},
        "music": {"zh": "音乐", "en": "Music"},
        "voice": {"zh": "语音", "en": "Voice"},
    }
    descriptors = []
    for slot, node_type in _ARTICLE_SLOT_NODE_TYPES.items():
        descriptors.append({
            "id": slot,
            "module_id": "article",
            "selection_policy": "fixed",
            "node_type": node_type,
            "capability_name": node_type.replace("_", "-"),
            "label": dict(labels[slot]),
            "expected_output": dict(_OUTPUT_MEDIA[node_type]),
            # 文章沿用用户启用清单、可执行状态和实际输出类型；Hypit 的用途
            # 黑名单不属于文章宿主的选择规则。
            "allowed_operations": [],
            "required_input_scenarios": list(_SLOT_SCENARIOS.get(slot, ["text_prompt"])),
            "supported_input_roles": list(_SLOT_INPUT_ROLES.get(slot, ["prompt"])),
            "runtime_model_override": "allow",
            "runtime_parameter_overrides": "schema_allowlist",
        })
    return descriptors


def _hypit_supported() -> Tuple[Dict[str, Any], ...]:
    """直接复用 Hypit 桥接声明的支持边界，不复制清单（§10.4）。"""
    from studio_hypit_models import SUPPORTED_HYPIT_CAPABILITIES

    return tuple(SUPPORTED_HYPIT_CAPABILITIES)


def _hypit_unsupported() -> Tuple[Dict[str, Any], ...]:
    from studio_hypit_models import UNSUPPORTED_HYPIT_CAPABILITIES

    return tuple(UNSUPPORTED_HYPIT_CAPABILITIES)


def hypit_slot_descriptors() -> List[Dict[str, Any]]:
    """按真实桥接能力生成 Hypit 槽位契约（§10.5）。"""
    descriptors: List[Dict[str, Any]] = []
    for capability in _hypit_supported():
        slot = str(capability.get("slot") or "").strip()
        node_type = str(capability.get("node_type") or "").strip()
        if not slot or not node_type:
            continue
        descriptors.append({
            "id": slot,
            "module_id": "hypit",
            "selection_policy": "fixed",
            "node_type": node_type,
            "capability_name": (capability.get("capability") or {}).get("name", ""),
            "label": dict(capability.get("label") or {}),
            "expected_output": dict(_OUTPUT_MEDIA.get(node_type, {})),
            "allowed_operations": sorted(_SLOT_OPERATIONS.get(slot, [])),
            "required_input_scenarios": list(_SLOT_SCENARIOS.get(slot, ["text_prompt"])),
            "supported_input_roles": list(_SLOT_INPUT_ROLES.get(slot, ["prompt"])),
            # 固定槽位必须真的固定：默认禁止调用者随请求更换模型/平台（§10.7）
            "runtime_model_override": "deny",
            "runtime_parameter_overrides": "schema_allowlist",
        })
    return descriptors


def module_descriptors() -> Dict[str, Dict[str, Any]]:
    """模块注册表：画布是多选候选池，Hypit 是固定单选槽位（§10.2）。"""
    return {
        "canvas": {
            "schema_version": MODULE_SCHEMA_VERSION,
            "module_id": "canvas",
            "label": studio_module_label("canvas"),
            "selection_policy": "multiple",
            "executor_id": "canvas-execution",
            "slots": [
                {
                    "id": node_type,
                    "selection_policy": "fixed",
                    "node_type": node_type,
                    "label": {"zh": node_type, "en": node_type},
                    "expected_output": dict(_OUTPUT_MEDIA.get(node_type, {})),
                    "runtime_model_override": "allow",
                    "runtime_parameter_overrides": "schema_allowlist",
                }
                for node_type in ("text_generation", "image_generation", "video_generation",
                                  "audio_generation", "music_generation")
            ],
        },
        "hypit": {
            "schema_version": MODULE_SCHEMA_VERSION,
            "module_id": "hypit",
            "label": studio_module_label("hypit"),
            "selection_policy": "fixed",
            "executor_id": "hypit-models-bridge",
            "slots": hypit_slot_descriptors(),
            "unsupported": [
                {
                    "name": str(item.get("name") or ""),
                    "label": dict(item.get("label") or {}),
                    "reason": dict(item.get("reason") or {}),
                }
                for item in _hypit_unsupported()
            ],
        },
        "article": {
            "schema_version": MODULE_SCHEMA_VERSION,
            "module_id": "article",
            "label": studio_module_label("article"),
            "selection_policy": "fixed",
            "executor_id": "article-settings-canvas-execution",
            "slots": article_slot_descriptors(),
        },
        "music": {
            "schema_version": MODULE_SCHEMA_VERSION,
            "module_id": "music",
            "label": studio_module_label("music"),
            "selection_policy": "fixed",
            "executor_id": "music-settings-canvas-execution",
            "slots": music_slot_descriptors(),
        },
    }


def module_descriptor(module_id: str) -> Optional[Dict[str, Any]]:
    return module_descriptors().get(str(module_id or "").strip().lower())


def slot_descriptor(module_id: str, slot_id: str) -> Optional[Dict[str, Any]]:
    module = module_descriptor(module_id)
    if not module:
        return None
    wanted = str(slot_id or "").strip()
    for slot in module.get("slots") or []:
        if str(slot.get("id")) == wanted:
            return slot
    return None


def validate_option_against_slot(slot: Dict[str, Any], option: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把一个选项与一份槽位声明比对，返回原因码列表。

    接受显式槽位声明，便于对声明的 allowlist 单独验证；纯函数，不修改入参。
    """
    reasons: List[Dict[str, Any]] = []
    node_type = str(option.get("node_type") or "")
    if node_type != str(slot.get("node_type") or ""):
        reasons.append({
            "code": "HOST_OUTPUT_UNSUPPORTED",
            "detail": {"expected": slot.get("node_type"), "actual": node_type},
        })

    expected_media = str((slot.get("expected_output") or {}).get("media_type") or "")
    actual_media = str(option.get("output_contract") or "").split(",")[0].strip()
    if actual_media == 'chat':
        actual_media = 'text'
    if expected_media and actual_media and actual_media != expected_media:
        reasons.append({
            "code": "HOST_OUTPUT_UNSUPPORTED",
            "detail": {"expected_media": expected_media, "actual_media": actual_media},
        })

    allowed = list(slot.get("allowed_operations") or [])
    if allowed and str(option.get("operation") or "") not in allowed:
        reasons.append({
            "code": "OPERATION_NOT_ALLOWED",
            "detail": {"operation": option.get("operation"), "allowed": allowed},
        })

    if str(option.get("readiness") or "") != "ready":
        reasons.append({"code": "PROFILE_UNCONFIRMED", "detail": {"readiness": option.get("readiness")}})
    if option.get("runnable") is False:
        reasons.append({"code": "ADAPTER_MISSING", "detail": {}})
    if slot.get("module_id") == "hypit" and slot.get('id') in _SLOT_OPERATIONS:
        reasons.extend({'code': code, 'detail': {}} for code in hypit_profile_reasons(slot['id'], option)
                       if code not in {reason['code'] for reason in reasons})
    return reasons


def validate_slot_binding(
    module_id: str,
    slot_id: str,
    option: Dict[str, Any],
    *,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """校验一个可执行选项能否作为该槽位的固定绑定（§10.5、D05、D06）。

    只返回机器原因码与说明；不修改选项、不替用户换模型。
    """
    slot = slot_descriptor(module_id, slot_id)
    if slot is None:
        return {"valid": False, "reasons": [{"code": "OPERATION_NOT_ALLOWED", "detail": {"slot": slot_id}}]}
    reasons = validate_option_against_slot(slot, option)
    return {"valid": not reasons, "reasons": reasons, "slot": slot.get("id"), "module_id": module_id}


def unsupported_capability_reason(module_id: str, capability_name: str) -> Optional[Dict[str, Any]]:
    """模块明确不支持的能力必须拒绝，而不是因为公共控件能列出就开放（D05）。"""
    module = module_descriptor(module_id)
    if not module:
        return None
    for item in module.get("unsupported") or []:
        if str(item.get("name")) == str(capability_name or "").strip():
            return item
    return None


def select_options_for_slot(
    options: List[Dict[str, Any]], module_id: str, slot_id: str
) -> Dict[str, Any]:
    """按槽位契约筛选候选选项（§11.2 只读目录）。

    只做“能不能进这个槽位”的判定：节点类型匹配、档案就绪、适配器可用。
    更细的输入/参数兼容性由评估接口负责，这里不越权替用户决定。
    """
    slot = slot_descriptor(module_id, slot_id)
    if slot is None:
        return {"options": [], "excluded": [], "slot": None}
    kept: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    wanted_node_type = str(slot.get("node_type") or "")
    for option in options or []:
        # 先做结构筛选：节点类型不符的选项根本不是这个槽位的候选，
        # 不能当成“被拒绝”来计数（否则会把目录里全部选项都报成不支持）。
        if wanted_node_type and str(option.get("node_type") or "") != wanted_node_type:
            continue
        reasons = validate_option_against_slot(slot, option)
        if reasons:
            excluded.append({
                "option_id": option.get("option_id"),
                "reasons": [item["code"] for item in reasons],
            })
            continue
        kept.append(option)
    return {"options": kept, "excluded": excluded, "slot": dict(slot)}


def create_module_models_router(get_catalog: Any, *, get_module_settings: Any = None):
    """模块模型只读接口（§11.2）。

    `GET /api/studio/model-options` 返回脱敏候选、契约版本与目录 revision，不返回任何密钥。
    保存类接口（PATCH 槽位）尚未实现，避免在没有迁移结论前引入第二套可写入口。
    """
    import inspect

    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api/studio", tags=["Studio Module Models"], dependencies=[Depends_local()])

    @router.get("/model-options")
    async def model_options(module_id: str = "canvas", slot_id: str = "") -> Dict[str, Any]:
        catalog = get_catalog()
        if inspect.isawaitable(catalog):
            raise HTTPException(status_code=500, detail="get_catalog 必须是同步目录函数")
        if not isinstance(catalog, dict):
            raise HTTPException(status_code=500, detail="模型能力目录格式不正确")
        module = module_descriptor(module_id)
        if module is None:
            raise HTTPException(status_code=400, detail=f"未注册的模块：{module_id}")
        options = catalog.get("options") or []
        slots = list(module.get("slots") or [])
        if slot_id:
            selected = select_options_for_slot(options, module_id, slot_id)
            if selected["slot"] is None:
                raise HTTPException(status_code=400, detail=f"{module_id} 未声明槽位 {slot_id}")
            slots = [selected["slot"]]
            offered = selected["options"]
        else:
            offered = list({option['option_id']: option for slot in slots
                            for option in select_options_for_slot(options, module_id, slot['id'])['options']}.values())
        return {
            "module_id": module_id,
            "selection_policy": module.get("selection_policy"),
            "slots": slots,
            "unsupported": module.get("unsupported") or [],
            "contract_version": MODULE_SCHEMA_VERSION,
            "catalog_revision": catalog.get("catalog_revision") or "",
            "selection_contract_version": catalog.get("selection_contract_version"),
            "options": offered,
        }

    return router


def Depends_local():
    """延迟导入 Depends，避免本模块在没有 FastAPI 的环境下无法用于纯逻辑测试。"""
    from fastapi import Depends

    return Depends(_local_guard)


async def _local_guard(request: Request) -> None:  # type: ignore[valid-type]
    from fastapi import HTTPException

    client = getattr(request, "client", None)
    host = str(getattr(client, "host", "") or "")
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="该接口仅允许本机访问")


def selection_policy(module_id: str) -> str:
    module = module_descriptor(module_id)
    return str((module or {}).get("selection_policy") or "")
