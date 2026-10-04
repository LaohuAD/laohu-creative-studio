"""统一输入/参数决策核心（P3）。

依据：《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§6、§7、§11.3、§18。

职责（§11.3 服务层最小接口）：
    evaluate_option(...)          兼容性评估，返回 §7.7 结果对象与机器原因码
    resolve_saved_selection(...)  已保存选择在新目录下的重新解析
    reconcile_parameters(...)     模型切换后的参数协调（§6.6）
    validate_execution(...)       运行前权威校验
    freeze_execution_snapshot(...) 冻结一次执行的快照

硬性约束：
- 每一份实际参与调用的素材是一项，不是每根连线是一项（§7.2）。
- 各角色上限不能相加当成全局上限（§B10）；必须分别检查角色容量与宿主总量。
- 未被消费的素材必须阻断执行，不得静默忽略（§7.10）。
- 软参数偏好不是硬过滤；只有用户主动锁定才升级为硬要求（§7.6）。
- 条件表达式限定为受限 JSON 表达式，禁止任意代码/Shell/网络（§8.5）。
- 本模块纯函数，不读密钥、不发网络请求、不产生付费任务。
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# §7.3 角色词汇（最小规范集）
# ---------------------------------------------------------------------------

ROLES: Tuple[str, ...] = (
    "prompt",
    "system_prompt",
    "reference",
    "first_frame",
    "last_frame",
    "source_video",
    "reference_video",
    "motion_video",
    "reference_audio",
    "driving_audio",
    "mask",
)

# 只归一化同一语义的不同拼写；不把 reference_video / motion_video / source_video
# 合并成同一用途（§7.3）。
ROLE_ALIASES: Dict[str, str] = {
    "first": "first_frame",
    "first_frame_image": "first_frame",
    "start_frame": "first_frame",
    "last": "last_frame",
    "last_frame_image": "last_frame",
    "end_frame": "last_frame",
    "reference_image": "reference",
    "image_reference": "reference",
    "reference_images": "reference",
    "audio_reference": "reference_audio",
    "reference_audios": "reference_audio",
    "video_reference": "reference_video",
    "reference_videos": "reference_video",
    "source_videos": "source_video",
    "motion": "motion_video",
    "system": "system_prompt",
    "text": "prompt",
}

ROLE_ORIGINS = ("explicit_port", "explicit_user", "legacy_mapping", "unique_inference", "unassigned")

CONTEXTS = ("live", "planned", "template")

# ---------------------------------------------------------------------------
# §18.2 统一原因码
# ---------------------------------------------------------------------------

REASON_TEXT: Dict[str, Dict[str, str]] = {
    "OPTION_NOT_FOUND": {"zh": "原模型选项已不存在，配置已保留待修复", "en": "The saved option no longer exists; the configuration is kept for repair"},
    "CONNECTION_DISABLED": {"zh": "当前连接已停用", "en": "This connection is disabled"},
    "REGION_DISABLED": {"zh": "当前站点已停用", "en": "This site is disabled"},
    "CREDENTIAL_NOT_CONFIGURED": {"zh": "请先配置当前连接凭据", "en": "Configure credentials for this connection first"},
    "PROFILE_UNCONFIRMED": {"zh": "能力档案尚未确认", "en": "The capability profile is not confirmed yet"},
    "ADAPTER_MISSING": {"zh": "当前适配器未完成", "en": "The adapter is not ready"},
    "HOST_OUTPUT_UNSUPPORTED": {"zh": "此模块不能接收该结果类型", "en": "This host cannot consume that output type"},
    "OPERATION_NOT_ALLOWED": {"zh": "当前槽位不允许此任务模式", "en": "This slot does not allow that operation"},
    "INPUT_TYPE_UNSUPPORTED": {"zh": "不支持这类输入素材", "en": "This input media type is not supported"},
    "ROLE_AMBIGUOUS": {"zh": "请分配素材用途", "en": "Assign the purpose of these materials"},
    "ROLE_CONFLICT": {"zh": "显式用途与当前模式冲突", "en": "An explicit role conflicts with this operation"},
    "INPUT_REQUIRED": {"zh": "缺少必要输入", "en": "A required input is missing"},
    "INPUT_COUNT_EXCEEDED": {"zh": "输入数量超出上限", "en": "Too many inputs"},
    "INPUT_COMBINATION_INVALID": {"zh": "当前素材组合不符合接口要求", "en": "This input combination is not accepted by the interface"},
    "INPUT_METADATA_MISSING": {"zh": "无法读取素材规格", "en": "Material metadata is unavailable"},
    "INPUT_SPEC_EXCEEDED": {"zh": "素材规格超出限制", "en": "Material specifications exceed the limit"},
    "UNCONSUMED_INPUT": {"zh": "存在尚未被使用的已选素材", "en": "Some selected materials would not be consumed"},
    "PARAM_REQUIRED": {"zh": "必填参数未填", "en": "A required parameter is missing"},
    "PARAM_INVALID": {"zh": "参数值不合法", "en": "A parameter value is invalid"},
    "PARAM_DEPENDENCY_CONFLICT": {"zh": "与当前模式或其它参数冲突", "en": "Conflicts with the current operation or other parameters"},
    "FIXED_PARAM_OVERRIDE": {"zh": "该字段由运行模式固定，不能单独覆盖", "en": "This field is fixed by the run mode and cannot be overridden"},
    "CATALOG_CHANGED": {"zh": "能力档案已更新，请确认冲突项", "en": "The catalog changed; confirm the conflicting items"},
    "REVISION_CONFLICT": {"zh": "此配置已在其他位置更新", "en": "This configuration was updated elsewhere"},
    "MIGRATION_AMBIGUOUS": {"zh": "旧选择可对应多个接口，需要确认", "en": "The legacy selection matches multiple interfaces"},
    "EXECUTION_ACCEPTANCE_UNKNOWN": {"zh": "上游是否已受理尚待核对，不会自动重发", "en": "Upstream acceptance is unknown; nothing is resent automatically"},
}

# §7.5 各维度取值
IDENTITY_STATUSES = ("mapped", "unresolved")
CAPABILITY_STATUSES = ("confirmed", "pending", "deprecated")
ADAPTER_STATUSES = ("ready", "missing")
CONNECTION_STATUSES = ("ready", "disabled", "unconfigured", "auth_unknown", "unavailable")
INPUT_STATUSES = ("compatible", "needs_binding", "needs_input", "awaiting_metadata", "incompatible")
PARAMETER_STATUSES = ("valid", "needs_value", "invalid")
HOST_STATUSES = ("supported", "unsupported")


def reason(code: str, **detail: Any) -> Dict[str, Any]:
    """构造机器原因码 + 可本地化文字（§7.7）。"""
    text = REASON_TEXT.get(code, {"zh": code, "en": code})
    message_zh = text["zh"]
    if detail:
        rendered = "，".join(f"{key}={value}" for key, value in detail.items())
        message_zh = f"{message_zh}（{rendered}）"
    return {
        "code": code,
        "message": {"zh": message_zh, "en": text["en"]},
        "detail": dict(detail),
    }


# ---------------------------------------------------------------------------
# §7.2 InputBinding
# ---------------------------------------------------------------------------

def normalize_role(value: Any) -> str:
    role = str(value or "").strip().lower().replace("-", "_")
    return ROLE_ALIASES.get(role, role)


def normalize_input_binding(raw: Dict[str, Any], *, order: int = 0) -> Dict[str, Any]:
    """把一条素材引用规范化为 InputBinding。"""
    role = normalize_role(raw.get("role"))
    origin = str(raw.get("role_origin") or "").strip().lower()
    if not role:
        role = "unassigned"
    if origin not in ROLE_ORIGINS:
        origin = "explicit_user" if role != "unassigned" else "unassigned"
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    return {
        "binding_id": str(raw.get("binding_id") or "").strip(),
        "source_kind": str(raw.get("source_kind") or "canvas_edge").strip(),
        "source_node_id": str(raw.get("source_node_id") or "").strip(),
        "output_index": raw.get("output_index"),
        "asset_id": str(raw.get("asset_id") or "").strip(),
        "media_type": str(raw.get("media_type") or "").strip().lower(),
        "role": role,
        "role_origin": origin,
        "order": int(raw.get("order") if raw.get("order") is not None else order),
        "materialization": str(raw.get("materialization") or "ready").strip(),
        "metadata": dict(metadata),
        "metadata_status": str(raw.get("metadata_status") or ("verified_local" if metadata else "unknown")).strip(),
    }


def normalize_bindings(raw_bindings: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    bindings = [
        normalize_input_binding(raw, order=index)
        for index, raw in enumerate(raw_bindings or [])
        if isinstance(raw, dict)
    ]
    bindings.sort(key=lambda item: item["order"])
    return bindings


def count_bindings(bindings: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """逐素材计数（§7.2）：一份素材算一项，一根连线上的 3 个输出算 3 项。"""
    counts: Dict[str, int] = {}
    for binding in bindings:
        media = binding.get("media_type") or "unknown"
        counts[media] = counts.get(media, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# 契约解析
# ---------------------------------------------------------------------------

def contract_roles(profile: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """把档案 inputs 解析为按角色聚合的契约，保留每个来源键的独立容量。"""
    roles: Dict[str, Dict[str, Any]] = {}
    for key, spec in (profile.get("inputs") or {}).items():
        if not isinstance(spec, dict):
            continue
        role = normalize_role(spec.get("role") or key)
        if not role:
            continue
        entry = roles.setdefault(role, {
            "role": role,
            "media_type": str(spec.get("media_type") or "").strip().lower(),
            "min": 0,
            "max": 0,
            "sources": [],
            "context_only": bool(spec.get("context_only")),
        })
        entry["min"] += max(0, int(spec.get("min") or 0))
        raw_max = spec.get("max")
        entry["max"] += max(0, int(raw_max if raw_max is not None else 1))
        entry["sources"].append(key)
    return roles


def contract_total_limit(profile: Dict[str, Any]) -> Optional[int]:
    """宿主声明的输入总量上限（若档案显式提供）。

    仅当档案显式声明时才有意义；不得用各角色 max 相加代替（§B10）。
    """
    for key in ("input_total_max", "max_inputs", "input_limit"):
        value = profile.get(key)
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                return None
    contract = profile.get("input_contract")
    if isinstance(contract, dict) and contract.get("total_max") is not None:
        try:
            return max(0, int(contract.get("total_max")))
        except (TypeError, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------
# §7.8 角色分配
# ---------------------------------------------------------------------------

MAX_ASSIGNMENT_PLANS = 24


def _candidate_roles(binding: Dict[str, Any], roles: Dict[str, Dict[str, Any]]) -> List[str]:
    media = binding.get("media_type") or ""
    if not media:
        return []
    return [
        role for role, spec in roles.items()
        if (not spec.get("media_type") or spec.get("media_type") == media)
    ]


def _assignment_plans(
    roles: Dict[str, Dict[str, Any]], bindings: Sequence[Dict[str, Any]]
) -> List[Dict[str, List[Dict[str, Any]]]]:
    """受限回溯：给出所有可行的角色分配方案（上限 MAX_ASSIGNMENT_PLANS）。"""
    plans: List[Dict[str, List[Dict[str, Any]]]] = []
    explicit: Dict[str, List[Dict[str, Any]]] = {}
    free: List[Dict[str, Any]] = []
    for binding in bindings:
        role = binding.get("role") or "unassigned"
        if role != "unassigned":
            explicit.setdefault(role, []).append(binding)
        else:
            free.append(binding)

    def walk(index: int, plan: Dict[str, List[Dict[str, Any]]]) -> None:
        if len(plans) >= MAX_ASSIGNMENT_PLANS:
            return
        if index == len(free):
            plans.append({key: list(value) for key, value in plan.items()})
            return
        binding = free[index]
        for role in _candidate_roles(binding, roles):
            taken = len(plan.get(role, []))
            if taken >= int(roles[role].get("max") or 0):
                continue
            plan.setdefault(role, []).append(binding)
            walk(index + 1, plan)
            plan[role].pop()
            if not plan[role]:
                plan.pop(role, None)

    base = {role: list(items) for role, items in explicit.items()}
    walk(0, base)
    return plans


def _plan_signature(plan: Dict[str, List[Dict[str, Any]]]) -> Tuple:
    return tuple(sorted(
        (role, tuple(binding.get("binding_id") or "" for binding in items))
        for role, items in plan.items()
    ))


def _max_partial_assignment(
    roles: Dict[str, Dict[str, Any]], bindings: Sequence[Dict[str, Any]]
) -> Tuple[List[str], List[str]]:
    """当不存在完整分配方案时，求“最多能消费多少份”的部分分配。

    返回 (被消费的 binding_id, 未被消费的 binding_id)。用于 §7.10：
    未被消费的已选素材必须阻断执行，不得静默忽略。
    """
    best: Dict[str, int] = {"count": -1, "consumed": []}

    ordered = sorted(bindings, key=lambda item: len(_candidate_roles(item, roles)))

    def walk(index: int, remaining: Dict[str, int], consumed: List[str]) -> None:
        if len(consumed) > best["count"]:
            best["count"] = len(consumed)
            best["consumed"] = list(consumed)
        if index >= len(ordered):
            return
        # 上界剪枝：剩余份数不足以超过当前最优
        if len(consumed) + (len(ordered) - index) <= best["count"]:
            return
        binding = ordered[index]
        for role in _candidate_roles(binding, roles):
            if remaining.get(role, 0) <= 0:
                continue
            remaining[role] -= 1
            consumed.append(binding.get("binding_id") or "")
            walk(index + 1, remaining, consumed)
            consumed.pop()
            remaining[role] += 1
        walk(index + 1, remaining, consumed)

    remaining = {role: int(spec.get("max") or 0) for role, spec in roles.items()}
    walk(0, remaining, [])
    consumed_ids = [item for item in best["consumed"] if item]
    leftover = [
        binding.get("binding_id") or ""
        for binding in bindings
        if (binding.get("binding_id") or "") not in set(consumed_ids)
    ]
    return consumed_ids, leftover


# ---------------------------------------------------------------------------
# §8.5 受限条件表达式
# ---------------------------------------------------------------------------

CONDITION_OPS = ("eq", "in", "all", "any", "not", "count_lte")


def _read_path(context: Dict[str, Any], path: str) -> Any:
    current: Any = context
    for part in str(path or "").split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def evaluate_condition(condition: Any, context: Dict[str, Any]) -> bool:
    """受限 JSON 表达式求值；非法操作符显式报错，不静默降级（§8.5）。"""
    if not condition:
        return True
    if not isinstance(condition, dict):
        raise ValueError("条件必须是对象")
    op = str(condition.get("op") or "").strip()
    if op not in CONDITION_OPS:
        raise ValueError(f"不支持的条件操作符: {op or '(空)'}")
    if op == "not":
        return not evaluate_condition(condition.get("value"), context)
    if op in ("all", "any"):
        items = condition.get("value")
        if not isinstance(items, list):
            raise ValueError(f"{op} 需要数组")
        results = [evaluate_condition(item, context) for item in items]
        return all(results) if op == "all" else any(results)
    if op == "in":
        options = condition.get("value")
        if not isinstance(options, list):
            raise ValueError("in 需要数组")
        return _read_path(context, condition.get("path")) in options
    if op == "count_lte":
        try:
            limit = int(condition.get("value"))
        except (TypeError, ValueError):
            raise ValueError("count_lte 需要整数上限")
        value = _read_path(context, condition.get("path"))
        if isinstance(value, (list, tuple, dict, str)):
            return len(value) <= limit
        if value is None:
            return True
        raise ValueError("count_lte 只适用于可计数的值")
    return _read_path(context, condition.get("path")) == condition.get("value")


def field_applicable(spec: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """适用性判定：applicable_if 优先，其次 visible_if。"""
    condition = spec.get("applicable_if") or spec.get("visible_if")
    return evaluate_condition(condition, context)


# ---------------------------------------------------------------------------
# §11.3 evaluate_option
# ---------------------------------------------------------------------------

def evaluate_option(
    option: Dict[str, Any],
    profile: Optional[Dict[str, Any]],
    *,
    bindings: Sequence[Dict[str, Any]] = (),
    context: str = "live",
    connection_status: str = "ready",
    host_contract: Optional[Dict[str, Any]] = None,
    host_output_types: Sequence[str] = (),
    parameter_values: Optional[Dict[str, Any]] = None,
    hard_requirements: Optional[Dict[str, Any]] = None,
    catalog_revision: str = "",
) -> Dict[str, Any]:
    """评估一个可执行选项在当前输入/连接/宿主下的状态（§7.7）。"""
    if context not in CONTEXTS:
        raise ValueError(f"未知上下文: {context}")
    host_contract = host_contract or {}
    hard = hard_requirements or {}
    values = dict(parameter_values or {})
    reasons: List[Dict[str, Any]] = []
    identity_status = "mapped" if option.get("identity_mapping_status") == "mapped" else "unresolved"
    readiness = str(option.get("readiness") or "")
    capability_status = "confirmed" if readiness == "ready" else ("deprecated" if readiness == "deprecated" else "pending")
    adapter_status = "missing" if readiness == "adapter_missing" else "ready"

    # 1) 宿主与输出契约（§7.6 第 1 优先级）
    host_status = "supported"
    output_types = list(host_output_types or [])
    output_contract = str(option.get("output_contract") or "")
    if output_types:
        produced = output_contract.split(",")[0].strip() if output_contract else ""
        if produced and produced not in output_types:
            host_status = "unsupported"
            reasons.append(reason("HOST_OUTPUT_UNSUPPORTED", output=produced, host="/".join(output_types)))

    # 2) 连接与站点（第 2 优先级）
    if connection_status != "ready":
        code = "REGION_DISABLED" if connection_status == "region_disabled" else "CONNECTION_DISABLED"
        if connection_status == "unconfigured":
            code = "CREDENTIAL_NOT_CONFIGURED"
        reasons.append(reason(code))

    # 3) 身份 / 档案 / 适配器（第 3 优先级）
    if capability_status == "pending":
        reasons.append(reason("PROFILE_UNCONFIRMED"))
    elif capability_status == "deprecated":
        reasons.append(reason("PROFILE_UNCONFIRMED", state="deprecated"))
    if adapter_status == "missing":
        reasons.append(reason("ADAPTER_MISSING"))

    # 4) 槽位允许的任务模式
    allowed_operations = host_contract.get("allowed_operations")
    if allowed_operations and str(option.get("operation") or "") not in set(allowed_operations):
        reasons.append(reason("OPERATION_NOT_ALLOWED", operation=option.get("operation") or ""))

    roles = contract_roles(profile or {})
    normalized = normalize_bindings(bindings)
    input_status = "compatible"
    proposed: List[Dict[str, Any]] = []
    consumed: List[str] = []
    unconsumed: List[str] = []

    if context == "template":
        # 模板场景：没有具体素材，按槽位声明的输入场景判断（§7.4）
        required_scenarios = host_contract.get("required_input_scenarios") or []
        covered = set(host_contract.get("covered_scenarios") or [])
        missing = [item for item in required_scenarios if item not in covered]
        if missing:
            input_status = "needs_input"
            reasons.append(reason("INPUT_REQUIRED", missing=",".join(missing)))
    elif not normalized:
        # 没有素材：配置态允许选择，运行才阻断（§7.5 selectable/runnable 分离）
        required = [role for role, spec in roles.items() if int(spec.get("min") or 0) > 0]
        if required:
            input_status = "needs_input"
            reasons.append(reason("INPUT_REQUIRED", roles=",".join(sorted(required))))
        elif context == "planned":
            input_status = "compatible"
    else:
        # 显式角色与契约冲突
        for binding in normalized:
            role = binding.get("role") or "unassigned"
            if role != "unassigned" and role not in roles:
                reasons.append(reason("ROLE_CONFLICT", role=role))
        unknown_media = [
            binding for binding in normalized
            if binding.get("media_type") and not _candidate_roles(binding, roles)
        ]
        if unknown_media:
            input_status = "incompatible"
            reasons.append(reason("INPUT_TYPE_UNSUPPORTED", media=",".join(sorted({b["media_type"] for b in unknown_media}))))
        plans = _assignment_plans(roles, normalized) if roles else []
        if roles and not plans:
            if input_status != "incompatible":
                input_status = "incompatible"
            counts = count_bindings(normalized)
            # 媒体容量 = 能接受该媒体的所有角色上限之和（不得用单个角色的 max 比对总数）
            capacity: Dict[str, int] = {}
            for spec in roles.values():
                media = spec.get("media_type") or ""
                if media:
                    capacity[media] = capacity.get(media, 0) + int(spec.get("max") or 0)
            over = sorted(
                media for media, total in counts.items()
                if total > capacity.get(media, 0)
            )
            _, leftover = _max_partial_assignment(roles, normalized)
            if over:
                reasons.append(reason("INPUT_COUNT_EXCEEDED", media=",".join(over)))
            elif not leftover:
                reasons.append(reason("INPUT_COMBINATION_INVALID"))
            # §7.10：只要存在未被消费的已选素材就必须阻断并列出来
            if leftover:
                unconsumed = leftover
                reasons.append(reason("UNCONSUMED_INPUT", bindings=",".join(leftover[:5])))
        elif plans:
            signatures = {_plan_signature(plan) for plan in plans}
            if len(signatures) > 1:
                input_status = "needs_binding"
                reasons.append(reason("ROLE_AMBIGUOUS", options=len(signatures)))
            else:
                plan = plans[0]
                proposed = [
                    {"binding_id": binding["binding_id"], "role": role, "role_origin": "unique_inference"}
                    for role, items in sorted(plan.items())
                    for binding in items
                ]
                # 必要角色与容量
                for role, spec in sorted(roles.items()):
                    got = len(plan.get(role, []))
                    if got < int(spec.get("min") or 0):
                        input_status = "needs_input"
                        reasons.append(reason("INPUT_REQUIRED", role=role, need=spec.get("min"), got=got))
                    if int(spec.get("max") or 0) and got > int(spec["max"]):
                        input_status = "incompatible"
                        reasons.append(reason("INPUT_COUNT_EXCEEDED", role=role, limit=spec.get("max"), got=got))
                consumed = [binding["binding_id"] for items in plan.values() for binding in items]

    # 5) 宿主总量上限：独立检查，不得用角色 max 相加（§B10）
    total_limit = contract_total_limit(profile or {})
    if total_limit is not None and len(normalized) > total_limit:
        input_status = "incompatible"
        reasons.append(reason("INPUT_COMBINATION_INVALID", total=len(normalized), limit=total_limit))
        overflow = [item["binding_id"] for item in normalized[total_limit:]]
        if overflow:
            unconsumed = sorted(set(unconsumed) | set(overflow))
            reasons.append(reason("UNCONSUMED_INPUT", bindings=",".join(overflow[:5])))

    if normalized and consumed:
        rest = [item["binding_id"] for item in normalized if item["binding_id"] not in set(consumed)]
        if rest:
            input_status = "incompatible"
            if not unconsumed:
                reasons.append(reason("UNCONSUMED_INPUT", bindings=",".join(rest[:5])))
            unconsumed = sorted(set(unconsumed) | set(rest))

    # 6) 元数据（仅在契约确实声明限制时检查）
    if context != "template" and normalized:
        for binding in normalized:
            if binding.get("metadata_status") == "unknown" and _profile_declares_specs(profile or {}):
                if input_status not in ("incompatible",):
                    input_status = "needs_binding"
                reasons.append(reason("INPUT_METADATA_MISSING", binding=binding.get("binding_id") or ""))
                break

    # 7) 参数（第 6 优先级）
    parameter_status, parameter_issues = evaluate_parameters(
        profile or {}, values, option_context=_option_context(option)
    )
    if parameter_status == "invalid":
        reasons.append(reason("PARAM_INVALID", fields=",".join(sorted(parameter_issues))))

    # 8) 硬要求（用户主动锁定；软偏好不进来）
    for key, expected in (hard.get("parameters") or {}).items():
        if values.get(key) != expected:
            parameter_status = "invalid"
            reasons.append(reason("PARAM_INVALID", field=key, expected=expected))
    if hard.get("required_media") and str(hard["required_media"]) not in count_bindings(normalized):
        input_status = "incompatible"
        reasons.append(reason("INPUT_TYPE_UNSUPPORTED", media=hard["required_media"]))

    blocking = any(
        item["code"] in {
            "OPTION_NOT_FOUND", "CONNECTION_DISABLED", "REGION_DISABLED", "CREDENTIAL_NOT_CONFIGURED",
            "PROFILE_UNCONFIRMED", "ADAPTER_MISSING", "HOST_OUTPUT_UNSUPPORTED", "OPERATION_NOT_ALLOWED",
            "INPUT_TYPE_UNSUPPORTED", "ROLE_CONFLICT", "INPUT_COUNT_EXCEEDED", "INPUT_COMBINATION_INVALID",
            "INPUT_SPEC_EXCEEDED", "UNCONSUMED_INPUT", "PARAM_INVALID",
        }
        for item in reasons
    )
    needs_action = any(
        item["code"] in {"INPUT_REQUIRED", "ROLE_AMBIGUOUS", "INPUT_METADATA_MISSING", "PARAM_REQUIRED"}
        for item in reasons
    )
    runnable = not blocking and not needs_action and input_status == "compatible" and connection_status == "ready"
    return {
        "option_id": str(option.get("option_id") or ""),
        "selectable": not blocking,
        "runnable": runnable,
        "input_status": input_status,
        "identity_status": identity_status,
        "capability_status": capability_status,
        "adapter_status": adapter_status,
        "connection_status": connection_status,
        "parameter_status": parameter_status,
        "host_status": host_status,
        "reasons": reasons,
        "proposed_bindings": proposed,
        "required_changes": [item["code"] for item in reasons if item["code"] in {
            "ROLE_AMBIGUOUS", "INPUT_REQUIRED", "PARAM_REQUIRED", "INPUT_METADATA_MISSING"}],
        "consumed_binding_ids": consumed,
        "unconsumed_binding_ids": unconsumed,
        "catalog_revision": catalog_revision,
    }


def _option_context(option: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "operation": str(option.get("operation") or ""),
        "node_type": str(option.get("node_type") or ""),
        "region_id": str(option.get("region_id") or ""),
        "catalog_model_id": str(option.get("catalog_model_id") or ""),
    }


def _profile_declares_specs(profile: Dict[str, Any]) -> bool:
    for spec in (profile.get("inputs") or {}).values():
        if isinstance(spec, dict) and (spec.get("constraints") or spec.get("specs")):
            return True
    return False


# ---------------------------------------------------------------------------
# §6.5 / §6.6 参数默认、校验与协调
# ---------------------------------------------------------------------------

def is_missing(value: Any) -> bool:
    """字段存在性判断：false / 0 / "" 是已设置的值，None 与缺失才是未设置。"""
    return value is None


def apply_defaults(
    profile: Dict[str, Any], values: Optional[Dict[str, Any]], context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """按 §6.5 优先级应用默认值；不存在的 default 不做猜测。"""
    context = context or {}
    result = dict(values or {})
    for key, spec in (profile.get("parameters") or {}).items():
        if not isinstance(spec, dict):
            continue
        if not field_applicable(spec, context):
            continue
        if key in result and not is_missing(result[key]):
            continue
        if "default" not in spec:
            continue
        result[key] = copy.deepcopy(spec["default"])
    return result


def _coerce_number(spec: Dict[str, Any], value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _option_key(value: Any) -> str:
    """与 JS 的 String(value) 对齐，保证前后端枚举比较结果一致。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def validate_parameter_value(spec: Dict[str, Any], value: Any) -> Optional[str]:
    """返回 None 表示合法，否则返回机器原因码。

    只判定，不修改：不得取整、不得裁剪到 min/max、不得做字符串 truthy 转换
    （§1.3、§6.6、C07/C09）。
    """
    if is_missing(value):
        return "PARAM_REQUIRED" if spec.get("required") or spec.get("level") == "required" else None
    kind = str(spec.get("type") or "").strip().lower()
    options = spec.get("options")
    has_options = isinstance(options, list) and bool(options)
    option_keys = [_option_key(item) for item in options] if has_options else []
    key = _option_key(value)

    if kind == "boolean":
        # 只接受真实布尔值；已知字面量在迁移阶段转换，运行路径不做隐式强转（C18）
        return None if isinstance(value, bool) else "PARAM_INVALID"
    if kind == "enum":
        if not has_options:
            # 枚举来源不可靠时阻断，而不是放行任意字符串（§6.2）
            return "PARAM_INVALID"
        return None if key in option_keys else "PARAM_INVALID"
    if kind in ("integer", "number"):
        if has_options and key not in option_keys:
            return "PARAM_INVALID"
        number = _coerce_number(spec, value)
        if number is None:
            return "PARAM_INVALID"
        if kind == "integer" and not float(number).is_integer():
            return "PARAM_INVALID"
        step = spec.get("step")
        if step:
            try:
                step_value = float(step)
            except (TypeError, ValueError):
                step_value = 0
            base = float(spec.get("min") or 0)
            if step_value > 0 and abs(((number - base) / step_value) - round((number - base) / step_value)) > 1e-9:
                return "PARAM_INVALID"
        if spec.get("min") is not None and number < float(spec["min"]):
            return "PARAM_INVALID"
        if spec.get("max") is not None and number > float(spec["max"]):
            return "PARAM_INVALID"
        return None
    if has_options:
        return None if key in option_keys else "PARAM_INVALID"
    return None


def evaluate_parameters(
    profile: Dict[str, Any], values: Dict[str, Any], *, option_context: Optional[Dict[str, Any]] = None
) -> Tuple[str, Dict[str, str]]:
    """返回 (parameterStatus, {字段: 原因码})。"""
    context = option_context or {}
    issues: Dict[str, str] = {}
    status = "valid"
    for key, spec in (profile.get("parameters") or {}).items():
        if not isinstance(spec, dict):
            continue
        if not field_applicable(spec, context):
            continue
        issue = validate_parameter_value(spec, values.get(key))
        if issue == "PARAM_REQUIRED":
            status = "needs_value" if status == "valid" else status
            issues[key] = issue
        elif issue:
            status = "invalid"
            issues[key] = issue
    return status, issues


def reconcile_parameters(
    old_profile: Dict[str, Any],
    new_profile: Dict[str, Any],
    values: Optional[Dict[str, Any]],
    drafts: Optional[Dict[str, Any]] = None,
    *,
    old_context: Optional[Dict[str, Any]] = None,
    new_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """模型切换后的参数协调（§6.6）。"""
    values = dict(values or {})
    drafts = dict(drafts or {})
    new_specs = new_profile.get("parameters") or {}
    old_specs = old_profile.get("parameters") or {}
    new_context = new_context or {}
    active: Dict[str, Any] = {}
    inactive: Dict[str, Any] = dict(drafts)
    issues: Dict[str, Dict[str, Any]] = {}
    notices: List[Dict[str, Any]] = []

    for key, value in values.items():
        spec = new_specs.get(key)
        if spec is None:
            inactive[key] = value
            continue
        if not field_applicable(spec, new_context):
            inactive[key] = value
            continue
        issue = validate_parameter_value(spec, value)
        if issue:
            # 保留可见原值并标红，不自动压到合法值（§6.6 第 2 条）
            active[key] = value
            issues[key] = {"code": issue, "kept_value": value, "spec": _spec_summary(spec)}
        else:
            active[key] = value

    # 新出现字段：应用真实合法默认；没有默认且必填则待填
    for key, spec in new_specs.items():
        if key in active or not isinstance(spec, dict):
            continue
        if not field_applicable(spec, new_context):
            continue
        if key in drafts:
            active[key] = copy.deepcopy(drafts[key])
            inactive.pop(key, None)
            continue
        if "default" in spec:
            active[key] = copy.deepcopy(spec["default"])
        elif spec.get("required"):
            issues[key] = {"code": "PARAM_REQUIRED", "kept_value": None, "spec": _spec_summary(spec)}

    if inactive:
        notices.append({"code": "DRAFT_ONLY", "count": len(inactive), "fields": sorted(inactive)})
    dropped = [key for key in old_specs if key not in new_specs and key not in values]
    if dropped:
        notices.append({"code": "FIELD_REMOVED", "fields": sorted(dropped)})
    return {
        "activeValues": active,
        "inactiveDraftValues": inactive,
        "validationIssues": issues,
        "notices": notices,
    }


def text_length(value: Any) -> int:
    """字符计数契约（§C19）：以 Unicode 码点计，前后端必须一致。

    Python 的 len() 即码点数；前端必须使用 [...text].length 而不是 text.length，
    后者按 UTF-16 码元计数，遇到 emoji 等增补平面字符会得出更大的值。
    """
    return len(str(value if value is not None else ""))


def _spec_summary(spec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: spec.get(key)
        for key in ("type", "min", "max", "step", "options", "required")
        if spec.get(key) is not None
    }


def reset_to_profile_defaults(
    profile: Dict[str, Any], *, option_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """“恢复默认”只重置当前叶子的参数覆盖（§6.6 第 6 条）。"""
    context = option_context or {}
    values: Dict[str, Any] = {}
    for key, spec in (profile.get("parameters") or {}).items():
        if not isinstance(spec, dict) or not field_applicable(spec, context):
            continue
        if "default" in spec:
            values[key] = copy.deepcopy(spec["default"])
    return values


# ---------------------------------------------------------------------------
# §11.3 运行前校验与快照
# ---------------------------------------------------------------------------

def resolve_saved_selection(
    selection: Dict[str, Any], catalog: Dict[str, Any], *, host_contract: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """在新目录下重新解析已保存选择；存在即返回，不存在给 OPTION_NOT_FOUND 而不静默替换。"""
    host_contract = host_contract or {}
    option_id = str(selection.get("option_id") or "")
    for option in catalog.get("options") or []:
        if option.get("option_id") != option_id:
            continue
        allowed = host_contract.get("allowed_operations")
        if allowed and option.get("operation") not in set(allowed):
            return {"found": True, "option": option, "reasons": [reason("OPERATION_NOT_ALLOWED", operation=option.get("operation") or "")]}
        return {"found": True, "option": option, "reasons": []}
    return {"found": False, "option": None, "reasons": [reason("OPTION_NOT_FOUND")]}


def freeze_execution_snapshot(
    *, option: Dict[str, Any], bindings: Sequence[Dict[str, Any]], parameters: Dict[str, Any],
    binding_revision: Any = None, catalog_revision: str = "", module_id: str = "", slot_id: str = "",
) -> Dict[str, Any]:
    """冻结一次执行的输入、参数与契约，供重试使用（§10.6、§11.6）。"""
    return {
        "schema_version": 2,
        "option_id": str(option.get("option_id") or ""),
        "connection_id": str(option.get("connection_id") or ""),
        "region_id": str(option.get("region_id") or ""),
        "operation": str(option.get("operation") or ""),
        "catalog_model_id": str(option.get("catalog_model_id") or ""),
        "endpoint_id": str(option.get("endpoint_id") or ""),
        "profile_revision": str(option.get("profile_revision") or ""),
        "module_id": str(module_id or ""),
        "slot_id": str(slot_id or ""),
        "binding_revision": binding_revision,
        "catalog_revision": str(catalog_revision or ""),
        "parameters": copy.deepcopy(parameters or {}),
        "input_bindings": [
            {
                key: binding.get(key)
                for key in ("binding_id", "asset_id", "media_type", "role", "role_origin", "order")
            }
            for binding in bindings or []
        ],
    }


def validate_execution(
    option: Dict[str, Any],
    profile: Optional[Dict[str, Any]],
    trusted_bindings: Sequence[Dict[str, Any]],
    effective_parameters: Dict[str, Any],
    *,
    host_contract: Optional[Dict[str, Any]] = None,
    host_output_types: Sequence[str] = (),
    connection_status: str = "ready",
) -> Dict[str, Any]:
    """后端权威校验：不信任客户端的可用性声明（§11.4、§13.5）。"""
    result = evaluate_option(
        option, profile,
        bindings=trusted_bindings,
        context="live",
        connection_status=connection_status,
        host_contract=host_contract,
        host_output_types=host_output_types,
        parameter_values=effective_parameters,
    )
    fixed = (profile or {}).get("fixed_parameters") or {}
    overridden = [key for key in fixed if key in effective_parameters and effective_parameters[key] != fixed[key]]
    if overridden:
        result["reasons"].append(reason("FIXED_PARAM_OVERRIDE", fields=",".join(sorted(overridden))))
        result["runnable"] = False
    return result
