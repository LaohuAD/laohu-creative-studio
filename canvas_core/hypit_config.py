"""Hypit 设置专用画布的纯图校验与目标流程快照。"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from collections import defaultdict
from typing import Any, Mapping


HYPIT_SETTINGS_CANVAS_ID = "hypit-settings"
ARTICLE_SETTINGS_CANVAS_ID = "article-settings"
SETTINGS_CANVAS_MODULES = {
    HYPIT_SETTINGS_CANVAS_ID: "hypit",
    ARTICLE_SETTINGS_CANVAS_ID: "article",
}
HYPIT_FLOW_SCHEMA_VERSION = 1
HYPIT_OUTPUT_SLOTS = ("text", "image", "video", "audio", "music", "voice")
HYPIT_OUTPUT_KINDS = {
    "text": "text",
    "image": "image",
    "video": "video",
    "audio": "audio",
    "music": "audio",
    "voice": "audio",
}

_STATIC_OUTPUT_KINDS = {
    "smart-text-generator": "text",
    "smart-image-generator": "image",
    "smart-video-generator": "video",
    "smart-audio-generator": "audio",
    "smart-music-generator": "audio",
}
_DYNAMIC_OUTPUT_TYPES = {"smart-ai-app", "smart-comfy-workflow"}
_EXECUTABLE_TYPES = set(_STATIC_OUTPUT_KINDS) | _DYNAMIC_OUTPUT_TYPES
_FLOW_CONNECTION_KINDS = {"", "flow", "input"}
_IGNORED_CONNECTION_KINDS = {"story", "history", "result"}
_LAYOUT_NODE_KEYS = {
    "title", "x", "y", "w", "h", "scale", "mediaSizeMode", "displayNumber",
    "selected", "hovered", "collapsed", "layout_w", "layout_h", "created_at",
    "updated_at", "createdAt", "updatedAt", "lastViewedAt", "connections",
}
_EXECUTION_STATE_KEYS = {
    "creationTasks", "resultVersions", "activeResultVersion", "runStatus", "runAt",
    "runStartedAt", "runFinishedAt", "runError", "runRef", "runSnapshot", "pending",
    "isRunPlaceholder", "cancelInProgress", "error", "taskId", "providerTaskId",
    "creationId", "creationOwnerNodeId", "creationRevision", "creationSignature",
    # 执行后由结果收集器回填，不能让一次测试的产物状态改变自身配方指纹。
    "sourceKind", "outputKind",
}


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _edge_source(edge: Mapping[str, Any]) -> str:
    return str(edge.get("from", edge.get("source", "")) or "")


def _edge_target(edge: Mapping[str, Any]) -> str:
    return str(edge.get("to", edge.get("target", "")) or "")


def _edge_kind(edge: Mapping[str, Any]) -> str:
    return str(edge.get("kind") or "").strip().lower()


def _group_member_ids(node: Mapping[str, Any]) -> list[str]:
    """读取智能分组成员；结果组还会在流程规划时合并真实结果连线。"""
    members = []
    items = node.get("items") if isinstance(node.get("items"), list) else []
    for item in items:
        if isinstance(item, Mapping):
            node_id = str(item.get("nodeId") or item.get("node_id") or "").strip()
        else:
            node_id = str(item or "").strip()
        if node_id and node_id not in members:
            members.append(node_id)
    return members


def _execution_output_kind(node: Mapping[str, Any]) -> str:
    node_type = str(node.get("type") or "")
    if node_type in _DYNAMIC_OUTPUT_TYPES:
        return "dynamic"
    # 静态类型以已接入的执行节点身份为准，不允许用户可编辑的 outputKind
    # 把图片节点伪装成视频或把素材节点伪装成生成器。
    return _STATIC_OUTPUT_KINDS.get(node_type, "")


def _validate_settings_canvas_identity(
    canvas: Mapping[str, Any],
    *,
    canvas_id: str = HYPIT_SETTINGS_CANVAS_ID,
    module_id: str = "hypit",
) -> str:
    """校验共享设置图的身份；Hypit 是兼容默认，文章图必须显式声明。"""
    if not isinstance(canvas, Mapping):
        raise ValueError("设置流程画布格式无效")
    actual_id = str(canvas.get("id") or "")
    expected_id = str(canvas_id or "")
    expected_module = SETTINGS_CANVAS_MODULES.get(expected_id)
    if (not expected_module or actual_id != expected_id
            or str(module_id or "") != expected_module):
        raise ValueError("设置流程画布身份或所属模块无效")
    return actual_id


def validate_hypit_settings_canvas(
    canvas: Mapping[str, Any],
    *,
    canvas_id: str = HYPIT_SETTINGS_CANVAS_ID,
    module_id: str = "hypit",
) -> bool:
    """检查 Hypit/文章专用图的身份、输出槽、连线和静态媒体类型。"""
    actual_id = _validate_settings_canvas_identity(canvas, canvas_id=canvas_id, module_id=module_id)
    nodes = canvas.get("nodes")
    edges = canvas.get("connections")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("设置流程节点或连线格式无效")

    by_id: dict[str, Mapping[str, Any]] = {}
    outputs: dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, Mapping):
            raise ValueError("Hypit 设置流程含无效节点")
        node_id = str(node.get("id") or "").strip()
        if not node_id or node_id in by_id:
            raise ValueError("Hypit 设置流程节点 ID 缺失或重复")
        by_id[node_id] = node
        fixed_kind = _STATIC_OUTPUT_KINDS.get(str(node.get("type") or ""))
        declared_kind = str(node.get("outputKind") or "").strip().lower()
        if fixed_kind and declared_kind:
            normalized_declared = "audio" if declared_kind == "music" else declared_kind
            if normalized_declared != fixed_kind:
                raise ValueError("Hypit 节点声明的输出类型与执行节点类型不匹配")
        if "hypitInputLocked" in node and not isinstance(node.get("hypitInputLocked"), bool):
            raise ValueError("素材输入的 hypitInputLocked 必须是布尔值")
        if node.get("type") == "smart-hypit-output":
            slot = str(node.get("hypitSlot") or "").strip().lower()
            if slot not in HYPIT_OUTPUT_SLOTS:
                raise ValueError("Hypit 输出节点用途不受支持")
            if slot in outputs:
                raise ValueError(f"Hypit {slot} 用途只能有一个输出节点")
            outputs[slot] = node

    incoming: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    graph: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if not isinstance(edge, Mapping):
            raise ValueError("Hypit 设置流程含无效连线")
        source_id, target_id = _edge_source(edge), _edge_target(edge)
        if source_id not in by_id or target_id not in by_id:
            raise ValueError("Hypit 设置流程连线引用了不存在的节点")
        if by_id[source_id].get("type") == "smart-hypit-output":
            raise ValueError("Hypit 输出节点不能作为连线来源")
        kind = _edge_kind(edge)
        if by_id[target_id].get("type") == "smart-hypit-output":
            if kind in _IGNORED_CONNECTION_KINDS or kind not in _FLOW_CONNECTION_KINDS:
                raise ValueError("Hypit 输出节点只接受一条生成流程连线")
            incoming[target_id].append(edge)
        if kind in _FLOW_CONNECTION_KINDS:
            graph[source_id].add(target_id)

    for output in outputs.values():
        output_id = str(output.get("id") or "")
        links = incoming.get(output_id, [])
        if len(links) > 1:
            raise ValueError(f"Hypit {output['hypitSlot']} 输出只能连接一个上游节点")
        if not links:
            continue
        source = by_id[_edge_source(links[0])]
        if source.get("type") == "smart-hypit-output":
            raise ValueError("Hypit 输出节点不能连接另一个输出节点")
        actual = _execution_output_kind(source)
        expected = HYPIT_OUTPUT_KINDS[str(output["hypitSlot"])]
        if actual and actual != "dynamic" and actual != expected:
            raise ValueError(f"Hypit {output['hypitSlot']} 输出类型与上游节点输出类型不匹配")

    # 保存入口也拒绝循环流程，避免执行和输出状态计算得到不同结果。
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("Hypit 设置流程不能形成循环")
        if node_id in visited:
            return
        visiting.add(node_id)
        for child in graph.get(node_id, ()):
            visit(child)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in by_id:
        visit(node_id)
    return True


def _node_recipe(node: Mapping[str, Any]) -> dict[str, Any]:
    node_type = str(node.get("type") or "")
    if node_type == "smart-hypit-output":
        return {key: copy.deepcopy(node.get(key)) for key in ("id", "type", "hypitSlot")}
    excluded = _LAYOUT_NODE_KEYS | _EXECUTION_STATE_KEYS
    # 画布持久化会补齐空的创作字段；它们与“未设置”语义一致。
    # creationDetails 只供维护者阅读，不进入生成请求。连线以画布级 connections 为准。
    excluded.add("creationDetails")
    if node_type not in {"smart-material", "smart-image"}:
        excluded.add("images")
    recipe = {key: copy.deepcopy(value) for key, value in node.items() if key not in excluded}
    if not recipe.get("creationInputBinding"):
        recipe.pop("creationInputBinding", None)
    return recipe


def plan_hypit_slot(
    canvas: Mapping[str, Any],
    slot: str,
    output_node_id: str = "",
    *,
    canvas_id: str = HYPIT_SETTINGS_CANVAS_ID,
    module_id: str = "hypit",
) -> dict[str, Any]:
    """解析输出上游与分组成员闭包，生成不含布局信息的配方指纹。"""
    validate_hypit_settings_canvas(canvas, canvas_id=canvas_id, module_id=module_id)
    slot = str(slot or "").strip().lower()
    if slot not in HYPIT_OUTPUT_SLOTS:
        raise ValueError("Hypit 输出用途不受支持")
    nodes = canvas["nodes"]
    by_id = {str(node["id"]): node for node in nodes}
    matches = [node for node in nodes if node.get("type") == "smart-hypit-output"
               and str(node.get("hypitSlot") or "").strip().lower() == slot
               and (not output_node_id or str(node.get("id")) == str(output_node_id))]
    if not matches:
        raise ValueError(f"Hypit {slot} 输出节点尚未配置")
    output = matches[0]
    output_id = str(output["id"])
    edges = [edge for edge in canvas["connections"]
             if isinstance(edge, Mapping) and _edge_kind(edge) in _FLOW_CONNECTION_KINDS]
    upstream: dict[str, list[str]] = defaultdict(list)
    result_members: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source_id, target_id = _edge_source(edge), _edge_target(edge)
        upstream[target_id].append(source_id)
    for edge in canvas["connections"]:
        if not isinstance(edge, Mapping) or _edge_kind(edge) != "result":
            continue
        source_id, target_id = _edge_source(edge), _edge_target(edge)
        if by_id.get(target_id, {}).get("type") == "smart-result-group" and source_id:
            result_members[target_id].append(source_id)
    relevant = {output_id}
    pending = [output_id]
    member_pairs: set[tuple[str, str]] = set()
    while pending:
        target_id = pending.pop()
        dependencies = list(upstream.get(target_id, []))
        target = by_id[target_id]
        if target.get("type") in {"smart-group", "smart-result-group"}:
            members = _group_member_ids(target)
            for member_id in result_members.get(target_id, []):
                if member_id not in members:
                    members.append(member_id)
            for member_id in members:
                if member_id not in by_id:
                    raise ValueError(f"Hypit 分组引用的成员节点不存在：{member_id}")
                member_pairs.add((member_id, target_id))
                dependencies.append(member_id)
        for source_id in dependencies:
            if source_id not in relevant:
                relevant.add(source_id)
                pending.append(source_id)
    if not upstream.get(output_id):
        raise ValueError(f"Hypit {slot} 输出尚未连接")
    output_source = by_id[upstream[output_id][0]]
    if _execution_output_kind(output_source) not in set(_STATIC_OUTPUT_KINDS.values()) | {"dynamic"}:
        raise ValueError(f"Hypit {slot} 输出必须连接可执行节点")

    index = {str(node["id"]): position for position, node in enumerate(nodes)}
    indegree = {node_id: 0 for node_id in relevant}
    plan_downstream: dict[str, list[str]] = defaultdict(list)
    dependency_pairs = {
        (_edge_source(edge), _edge_target(edge))
        for edge in edges
        if _edge_source(edge) in relevant and _edge_target(edge) in relevant
    }
    dependency_pairs.update((source_id, target_id) for source_id, target_id in member_pairs
                            if source_id in relevant and target_id in relevant)
    for source_id, target_id in dependency_pairs:
        indegree[target_id] += 1
        plan_downstream[source_id].append(target_id)
    ready = sorted((node_id for node_id, count in indegree.items() if count == 0), key=index.get)
    ordered_ids = []
    while ready:
        node_id = ready.pop(0)
        ordered_ids.append(node_id)
        for target_id in plan_downstream.get(node_id, []):
            if target_id not in indegree:
                continue
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                ready.append(target_id)
                ready.sort(key=index.get)
    if len(ordered_ids) != len(relevant):
        raise ValueError("Hypit 设置流程不能形成循环")
    relevant_edges = [copy.deepcopy(edge) for edge in edges
                      if _edge_source(edge) in relevant and _edge_target(edge) in relevant]
    member_dependencies = [
        {"from": source_id, "to": target_id}
        for source_id, target_id in sorted(member_pairs, key=lambda pair: (index[pair[1]], index[pair[0]]))
    ]
    ordered_nodes = [copy.deepcopy(by_id[node_id]) for node_id in ordered_ids]
    recipe = {
        "slot": slot,
        "output_node_id": output_id,
        "nodes": [_node_recipe(node) for node in ordered_nodes],
        "connections": relevant_edges,
        "member_dependencies": member_dependencies,
    }
    fingerprint = hashlib.sha256(_stable(recipe).encode("utf-8")).hexdigest()
    return {
        "slot": slot,
        "output_node": copy.deepcopy(output),
        "node_ids": ordered_ids,
        "nodes": ordered_nodes,
        "connections": relevant_edges,
        "member_dependencies": member_dependencies,
        "recipe": recipe,
        "recipe_fingerprint": fingerprint,
    }


def hypit_execution_recipe_fingerprint(
    canvas: Mapping[str, Any],
    node_id: str,
    *,
    canvas_id: str = HYPIT_SETTINGS_CANVAS_ID,
    module_id: str = "hypit",
) -> str:
    """生成普通单节点运行证据指纹，不把 Hypit 输出端口纳入配方。"""
    validate_hypit_settings_canvas(canvas, canvas_id=canvas_id, module_id=module_id)
    target_id = str(node_id or "").strip()
    by_id = {str(node.get("id") or ""): node for node in canvas["nodes"]}
    target = by_id.get(target_id)
    if target is None or _execution_output_kind(target) not in set(_STATIC_OUTPUT_KINDS.values()) | {"dynamic"}:
        raise ValueError("Hypit 运行证据必须绑定到真实执行节点")

    edges = [edge for edge in canvas["connections"] if isinstance(edge, Mapping)]
    upstream: dict[str, list[str]] = defaultdict(list)
    result_members: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source_id, destination_id = _edge_source(edge), _edge_target(edge)
        kind = _edge_kind(edge)
        if kind in _FLOW_CONNECTION_KINDS:
            upstream[destination_id].append(source_id)
        elif kind == "result" and by_id.get(destination_id, {}).get("type") == "smart-result-group":
            result_members[destination_id].append(source_id)

    relevant = {target_id}
    pending = [target_id]
    member_pairs: set[tuple[str, str]] = set()
    while pending:
        current_id = pending.pop()
        current = by_id[current_id]
        dependencies = list(upstream.get(current_id, ()))
        if current.get("type") in {"smart-group", "smart-result-group"}:
            members = _group_member_ids(current)
            if current.get("type") == "smart-result-group":
                for member_id in result_members.get(current_id, ()):
                    if member_id not in members:
                        members.append(member_id)
            for member_id in members:
                if member_id not in by_id:
                    raise ValueError(f"Hypit 分组引用的成员节点不存在：{member_id}")
                member_pairs.add((member_id, current_id))
                dependencies.append(member_id)
        for source_id in dependencies:
            if source_id not in by_id:
                raise ValueError("Hypit 运行证据的上游节点不存在")
            if source_id not in relevant:
                relevant.add(source_id)
                pending.append(source_id)

    relevant_edges = [
        copy.deepcopy(dict(edge)) for edge in edges
        if _edge_source(edge) in relevant and _edge_target(edge) in relevant
        and _edge_kind(edge) not in {"story", "history"}
    ]
    relevant_edges.sort(key=_stable)
    member_dependencies = [
        {"from": source_id, "to": group_id}
        for source_id, group_id in sorted(member_pairs)
    ]
    nodes = []
    for current_id in sorted(relevant):
        current = by_id[current_id]
        entry: dict[str, Any] = {"id": current_id, "recipe": _node_recipe(current)}
        # 执行节点作为上游输入时，实际已收集的结果会进入下游请求；将其纳入
        # 指纹，避免上游换图后旧引用仍被误认为当前配方的成功结果。
        if current_id != target_id and current.get("type") in _EXECUTABLE_TYPES:
            entry["input_outputs"] = copy.deepcopy(current.get("images") or [])
        nodes.append(entry)
    recipe = {
        "source_node_id": target_id,
        "nodes": nodes,
        "connections": relevant_edges,
        "member_dependencies": member_dependencies,
    }
    return hashlib.sha256(_stable(recipe).encode("utf-8")).hexdigest()


def project_hypit_execution_statuses(
    canvas: Mapping[str, Any],
    load_task: Any,
    load_result: Any,
    *,
    canvas_id: str = HYPIT_SETTINGS_CANVAS_ID,
    module_id: str = "hypit",
) -> dict[str, dict[str, Any]]:
    """只从服务端持久任务与托管结果投影普通 Hypit 节点运行状态。"""
    graph_id = _validate_settings_canvas_identity(canvas, canvas_id=canvas_id, module_id=module_id)
    validate_hypit_settings_canvas(canvas, canvas_id=graph_id, module_id=module_id)
    by_id = {str(node.get("id") or ""): node for node in canvas["nodes"] if isinstance(node, Mapping)}
    outputs = [node for node in canvas["nodes"]
               if isinstance(node, Mapping) and node.get("type") == "smart-hypit-output"]
    statuses: dict[str, dict[str, Any]] = {}

    for output in outputs:
        output_id = str(output.get("id") or "")
        slot = str(output.get("hypitSlot") or "").strip().lower()
        expected_kind = HYPIT_OUTPUT_KINDS[slot]
        incoming = [edge for edge in canvas["connections"]
                    if isinstance(edge, Mapping)
                    and _edge_target(edge) == output_id
                    and _edge_kind(edge) in _FLOW_CONNECTION_KINDS]
        base = {
            "run_id": "",
            "status": "unconfigured" if not incoming else "ready",
            "test_passed": False,
            "current_recipe_matches": False,
            "output_kind": "",
            "error": "" if incoming else "Hypit 输出尚未连接执行节点",
        }
        if not incoming:
            statuses[output_id] = base
            continue

        source_id = _edge_source(incoming[0])
        source = by_id.get(source_id)
        if source is None:
            statuses[output_id] = base
            continue
        try:
            current_fingerprint = hypit_execution_recipe_fingerprint(
                canvas, source_id, canvas_id=graph_id, module_id=module_id,
            )
        except (TypeError, ValueError):
            statuses[output_id] = base
            continue

        candidates = []
        for order, entry in enumerate(source.get("creationTasks") or []):
            if not isinstance(entry, Mapping) or not str(entry.get("id") or "").strip():
                continue
            task = load_task(str(entry["id"])) if callable(load_task) else None
            if not isinstance(task, Mapping):
                continue
            if (str(task.get("canvas_id") or "") != graph_id
                    or str(task.get("node_id") or "") != source_id
                    or str(task.get("hypit_source_node_id") or "") != source_id
                    or not task.get("hypit_source_recipe_fingerprint")):
                continue
            try:
                created_at = int(task.get("created_at") or 0)
            except (TypeError, ValueError):
                created_at = 0
            candidates.append((created_at, order, task))
        if not candidates:
            statuses[output_id] = base
            continue
        # 同一毫秒内创建时，以画布 creationTasks 的追加顺序确定较新的任务。
        task = max(candidates, key=lambda item: (item[0], item[1]))[2]
        stored_fingerprint = str(task.get("hypit_source_recipe_fingerprint") or "")
        recipe_matches = stored_fingerprint == current_fingerprint
        media = ((task.get("result") or {}).get("media")
                 if isinstance(task.get("result"), Mapping) else [])
        typed_kinds = []
        matching_kind = False
        for item in media if isinstance(media, list) else []:
            if not isinstance(item, Mapping):
                continue
            result_id = str(item.get("resultId") or item.get("result_id") or "").strip()
            if not result_id:
                url = str(item.get("url") or "")
                marker = "/api/results/"
                if marker in url:
                    result_id = url.split(marker, 1)[1].split("?", 1)[0].strip("/")
            if not result_id or not callable(load_result):
                continue
            stored = load_result(result_id)
            if not isinstance(stored, Mapping) or stored.get("_managed_verified") is not True:
                continue
            item_kind = str(item.get("kind") or item.get("media_type") or "").strip().lower()
            stored_kind = str(stored.get("kind") or "").strip().lower()
            if item_kind not in {"text", "image", "video", "audio"} or item_kind != stored_kind:
                continue
            if item_kind not in typed_kinds:
                typed_kinds.append(item_kind)
            if item_kind == expected_kind:
                matching_kind = True

        supported_slots = task.get("hypit_supported_output_slots")
        slot_supported = isinstance(supported_slots, list) and slot in supported_slots
        task_status = str(task.get("status") or "recoverable").strip().lower()
        passed = task_status == "succeeded" and recipe_matches and slot_supported and matching_kind
        if passed:
            status = "passed"
        elif task_status in {"failed", "cancelled", "recoverable"}:
            status = task_status
        elif task_status == "succeeded" and recipe_matches and slot_supported and not matching_kind:
            status = "failed"
        else:
            status = "ready"
        error = str(task.get("error") or "")
        if task_status == "succeeded" and recipe_matches and slot_supported and not matching_kind:
            error = f"运行结果没有可验证的 {expected_kind} 托管素材"
        statuses[output_id] = {
            "run_id": str(task.get("id") or ""),
            "status": status,
            "test_passed": passed,
            "current_recipe_matches": recipe_matches,
            "output_kind": expected_kind if matching_kind else (typed_kinds[0] if typed_kinds else ""),
            "error": error,
        }
    return statuses


def legacy_hypit_defaults_to_canvas(defaults: Mapping[str, Any], canvas_id: str = HYPIT_SETTINGS_CANVAS_ID) -> dict[str, Any]:
    """把旧六槽默认选择一次性投影成普通画布执行节点和用途输出节点。"""
    if canvas_id != HYPIT_SETTINGS_CANVAS_ID:
        raise ValueError("Hypit 设置流程画布身份无效")
    if not isinstance(defaults, Mapping):
        raise ValueError("旧 Hypit 设置格式无效")
    timestamp = int(time.time() * 1000)
    nodes: list[dict[str, Any]] = []
    connections: list[dict[str, Any]] = []
    slot_node_types = {
        "text": "smart-text-generator", "image": "smart-image-generator",
        "video": "smart-video-generator", "audio": "smart-audio-generator",
        "music": "smart-music-generator", "voice": "smart-audio-generator",
    }
    for index, slot in enumerate(HYPIT_OUTPUT_SLOTS):
        selected = defaults.get(slot)
        if not isinstance(selected, Mapping):
            continue
        selection_kind = str(selected.get("selection_kind") or "api_model").strip().lower()
        run_settings: dict[str, Any] = {}
        if selection_kind == "api_model":
            provider = str(selected.get("provider") or selected.get("provider_id") or "").strip()
            model = str(selected.get("model") or selected.get("model_id") or "").strip()
            if not provider or not model:
                continue
            run_settings[{
                "text": "textProvider", "image": "provider_id", "video": "videoProvider",
                "audio": "audioProvider", "music": "musicProvider", "voice": "audioProvider",
            }[slot]] = provider
            model_key = {
                "text": "textModel", "image": "model", "video": "videoModel",
                "audio": "audioModel", "music": "musicModel", "voice": "audioModel",
            }[slot]
            run_settings[model_key] = model
            parameters = selected.get("parameters") if isinstance(selected.get("parameters"), Mapping) else {}
            if parameters:
                run_settings["capabilityParameters"] = {model: copy.deepcopy(dict(parameters))}
        elif selection_kind == "workflow":
            source = str(selected.get("source") or "").strip()
            provider_id = str(selected.get("provider_id") or "").strip()
            item_id = str(selected.get("item_id") or "").strip()
            region = str(selected.get("region") or "").strip()
            fields = selected.get("fields") if isinstance(selected.get("fields"), list) else []
            values = selected.get("field_values") if isinstance(selected.get("field_values"), Mapping) else {}
            if not source or not provider_id or not item_id:
                continue
            if source == "local_comfy_workflow":
                run_settings = {
                    "comfyMode": "custom", "comfyWorkflow": item_id,
                    "comfyFields": copy.deepcopy(fields), "comfyParams": copy.deepcopy(dict(values)),
                }
                node_type = "smart-comfy-workflow"
            elif source in {"runninghub_app", "runninghub_workflow"}:
                is_workflow = source == "runninghub_workflow"
                run_settings = {
                    "rhMode": "workflow" if is_workflow else "app",
                    "rhConfigKey": f"{'workflow' if is_workflow else 'app'}:{item_id}",
                    "rhAppId": "" if is_workflow else item_id,
                    "rhWorkflowId": item_id if is_workflow else "",
                    "rhRegion": region,
                    "rhFields": copy.deepcopy(fields), "rhSchemaSnapshot": copy.deepcopy(fields),
                    "rhParams": copy.deepcopy(dict(values)),
                    "rhInputBindings": copy.deepcopy(selected.get("input_bindings") or {}),
                }
                node_type = "smart-ai-app"
            else:
                continue
        else:
            continue

        node_type = slot_node_types[slot] if selection_kind == "api_model" else node_type
        node_id = f"hypit-run-{slot}"
        output_id = f"hypit-output-{slot}"
        run_settings["region"] = str(selected.get("region") or run_settings.get("rhRegion") or "")
        run_settings["hypitGenerationSlot"] = slot
        node = {
            "id": node_id, "type": node_type, "title": {"text": "文本生成", "image": "图片生成",
                "video": "视频生成", "audio": "音频生成", "music": "音乐生成", "voice": "语音生成"}[slot],
            "x": 80, "y": index * 220, "runSettings": run_settings, "hypitSlot": slot,
            "hypitLegacySelection": copy.deepcopy(dict(selected)), "images": [],
        }
        output = {"id": output_id, "type": "smart-hypit-output", "hypitSlot": slot,
                  "outputKind": HYPIT_OUTPUT_KINDS[slot], "x": 560, "y": index * 220, "images": []}
        nodes.extend((node, output))
        connections.append({"from": node_id, "to": output_id, "kind": "input"})

    return {
        "id": HYPIT_SETTINGS_CANVAS_ID, "title": "Hypit 生成流程", "icon": "workflow",
        "kind": "smart", "owner": "", "color": "", "pinned": False, "project": "default",
        "created_at": timestamp, "updated_at": timestamp, "revision": 1,
        "node_schema_version": 1, "hypit_flow_schema_version": HYPIT_FLOW_SCHEMA_VERSION,
        "hypit_legacy_migration_done": True, "nodes": nodes, "connections": connections,
        "viewport": {"x": 0, "y": 0, "scale": 1}, "logs": [], "settings": {},
    }


def upgrade_hypit_legacy_prompt_scaffold(canvas: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """只在迁移标记和空占位形状完全吻合时，复制并移除旧自动提示素材节点。

    返回新的画布副本和是否发生变化；不写文件、不递增修订号，调用方负责备份与原子保存。
    任何正文、素材、额外字段、改动过的布局或连线都会让节点原样保留。
    """
    if not isinstance(canvas, Mapping):
        raise ValueError("Hypit 设置流程画布格式无效")
    updated = copy.deepcopy(dict(canvas))
    if (updated.get("id") != HYPIT_SETTINGS_CANVAS_ID
            or updated.get("hypit_legacy_migration_done") is not True
            or updated.get("hypit_flow_schema_version") != HYPIT_FLOW_SCHEMA_VERSION
            or not isinstance(updated.get("nodes"), list)
            or not isinstance(updated.get("connections"), list)):
        return updated, False

    allowed_keys = {"id", "type", "title", "sourceKind", "hypitInputLocked", "images", "x", "y"}
    text_keys = ("text", "content", "markdown", "prompt", "promptDraftText", "promptDraftHtml", "data", "notes")
    remove_ids: set[str] = set()
    remove_edges: set[int] = set()
    by_id = {str(node.get("id") or ""): node for node in updated["nodes"] if isinstance(node, Mapping)}
    for slot_index, slot in enumerate(HYPIT_OUTPUT_SLOTS):
        node_id = f"hypit-prompt-{slot}"
        node = by_id.get(node_id)
        if not isinstance(node, Mapping):
            continue
        if (set(node) - allowed_keys
                or node.get("type") != "smart-material"
                or node.get("title") != "本次提示词"
                or node.get("sourceKind") != "input"
                or node.get("hypitInputLocked") is not False
                or node.get("images") != []
                or node.get("x") != 0
                or node.get("y") != slot_index * 220
                or any(node.get(key) not in (None, "", [], {}) for key in text_keys)):
            continue
        generator_id = f"hypit-run-{slot}"
        generator = by_id.get(generator_id)
        if (not isinstance(generator, Mapping)
                or generator.get("type") not in _EXECUTABLE_TYPES
                or not isinstance(generator.get("hypitLegacySelection"), Mapping)):
            continue
        linked = [(index, edge) for index, edge in enumerate(updated["connections"])
                  if isinstance(edge, Mapping)
                  and (str(edge.get("from", edge.get("source", "")) or "") == node_id
                       or str(edge.get("to", edge.get("target", "")) or "") == node_id)]
        if len(linked) != 1:
            continue
        edge_index, edge = linked[0]
        if (set(edge) != {"from", "to", "kind"}
                or str(edge.get("from") or "") != node_id
                or str(edge.get("to") or "") != generator_id
                or str(edge.get("kind") or "").strip().lower() != "input"):
            continue
        remove_ids.add(node_id)
        remove_edges.add(edge_index)
    if not remove_ids:
        return updated, False
    updated["nodes"] = [node for node in updated["nodes"]
                        if not isinstance(node, Mapping) or str(node.get("id") or "") not in remove_ids]
    updated["connections"] = [edge for index, edge in enumerate(updated["connections"]) if index not in remove_edges]
    return updated, True


def prepare_hypit_task_canvas(
    canvas: Mapping[str, Any],
    slot: str,
    request: Mapping[str, Any],
    output_node_id: str = "",
    *,
    canvas_id: str = HYPIT_SETTINGS_CANVAS_ID,
    module_id: str = "hypit",
) -> dict[str, Any]:
    """为一次 Hypit 请求构造私有画布快照，绝不改写已保存的设置画布。"""
    plan = plan_hypit_slot(
        canvas, slot, output_node_id, canvas_id=canvas_id, module_id=module_id,
    )
    task_canvas = copy.deepcopy(dict(canvas))
    by_id = {str(node.get("id") or ""): node for node in task_canvas.get("nodes", []) if isinstance(node, dict)}
    ordered = [by_id[node_id] for node_id in plan["node_ids"]]
    execution_nodes = [node for node in ordered if node.get("type") in _EXECUTABLE_TYPES]
    if not execution_nodes:
        raise ValueError(f"Hypit {slot} 输出流程没有可执行节点")

    refs = [copy.deepcopy(item) for item in request.get("references") or [] if isinstance(item, Mapping)]
    if not refs:
        inputs = request.get("inputs") if isinstance(request.get("inputs"), Mapping) else {}
        roles = (("reference", "image"), ("first_frame", "image"), ("last_frame", "image"),
                 ("source_video", "video"), ("reference_audio", "audio"))
        for role, kind in roles:
            values = inputs.get(role) or []
            values = values if isinstance(values, list) else [values]
            refs.extend({"url": str(value), "kind": kind, "role": role}
                        for value in values if isinstance(value, str) and value.strip())

    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ref in refs:
        kind = str(ref.get("kind") or "").strip().lower()
        if kind in {"image", "video", "audio", "text"}:
            by_kind[kind].append(ref)
        elif kind:
            raise ValueError(f"Hypit 请求包含不支持的输入类型：{kind}")
    def item_kind(item: Mapping[str, Any]) -> str:
        return str(item.get("kind") or item.get("media_type") or "").strip().lower()

    def target_node_id(value: Mapping[str, Any]) -> str:
        return str(value.get("target_node_id") or value.get("targetNodeId") or "").strip()

    material_nodes = [node for node in ordered if node.get("type") in {"smart-material", "smart-image"}]
    prompt_candidates = []
    for node in ordered:
        node_type = str(node.get("type") or "")
        if node_type == "smart-prompt":
            prompt_candidates.append(node)
        elif node_type == "smart-material":
            items = node.get("images") if isinstance(node.get("images"), list) else []
            if not items or any(isinstance(item, Mapping) and item_kind(item) == "text" for item in items):
                prompt_candidates.append(node)
    prompt = str(request.get("prompt") or "").strip()

    def node_input_kinds(node: Mapping[str, Any], kind: str) -> list[int]:
        items = node.get("images") if isinstance(node.get("images"), list) else []
        return [index for index, item in enumerate(items) if isinstance(item, Mapping) and item_kind(item) == kind]

    def eligible_nodes(kind: str) -> list[dict[str, Any]]:
        result = []
        for node in material_nodes:
            items = node.get("images") if isinstance(node.get("images"), list) else []
            kinds = {item_kind(item) for item in items if isinstance(item, Mapping) and item_kind(item)}
            if kind in kinds or not kinds:
                result.append(node)
        return result

    def choose_node(kind: str, candidates: list[dict[str, Any]], explicit_target: str = "") -> dict[str, Any] | None:
        if explicit_target:
            node = next((item for item in candidates if str(item.get("id") or "") == explicit_target), None)
            if node is None:
                raise ValueError(f"Hypit {slot} 输入目标节点不存在或不接收 {kind} 类型：{explicit_target}")
            if node.get("hypitInputLocked") is True:
                raise ValueError(f"Hypit {slot} 输入素材节点已锁定，不能替换 {kind} 素材：{explicit_target}")
            return node
        unlocked = [node for node in candidates if node.get("hypitInputLocked") is not True]
        if len(unlocked) > 1:
            raise ValueError(f"Hypit {slot} 流程有多个可接收 {kind} 输入的素材节点，请提供明确的目标节点 ID")
        if unlocked:
            return unlocked[0]
        if candidates:
            raise ValueError(f"Hypit {slot} 输入素材节点已锁定，当前用途没有可替换的 {kind} 输入槽")
        return None

    def normalize_reference(ref: Mapping[str, Any], kind: str) -> dict[str, Any]:
        value = copy.deepcopy(dict(ref))
        value["kind"] = kind
        if kind == "text":
            text = value.get("text", value.get("content"))
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Hypit 文本输入缺少正文")
            value["text"] = value["content"] = text
        elif not str(value.get("url") or value.get("path") or value.get("src") or "").strip():
            raise ValueError(f"Hypit {kind} 输入缺少可访问资源地址")
        return value

    def replace_material_kind(node: dict[str, Any], kind: str, values: list[dict[str, Any]], explicit_indexes: list[int] | None = None) -> None:
        current = node.get("images") if isinstance(node.get("images"), list) else []
        indexes = node_input_kinds(node, kind)
        if explicit_indexes is not None:
            if len(explicit_indexes) != len(values) or any(index < 0 or index >= len(current) for index in explicit_indexes):
                raise ValueError(f"Hypit {slot} 的 {kind} 输入目标索引无效")
            for index, value in zip(explicit_indexes, values):
                current[index] = value
            node["images"] = current
            return
        if len(indexes) > 1 and len(indexes) != len(values):
            raise ValueError(f"Hypit {slot} 输入素材节点包含多个 {kind} 项，请提供与节点素材匹配的显式索引")
        insertion = indexes[0] if indexes else len(current)
        kept = [item for item in current if not (isinstance(item, Mapping) and item_kind(item) == kind)]
        insertion = min(insertion, len(kept))
        node["images"] = kept[:insertion] + copy.deepcopy(values) + kept[insertion:]

    # 按稳定节点 ID 分配媒体引用；无目标时仅允许唯一候选，不以列表顺序猜测。
    explicitly_assigned: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    implicit_refs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for kind, values in by_kind.items():
        if kind == "text":
            continue
        candidates = eligible_nodes(kind)
        for ref in values:
            value = normalize_reference(ref, kind)
            explicit = target_node_id(ref)
            if explicit:
                target = choose_node(kind, candidates, explicit)
                explicitly_assigned[(str(target["id"]), kind)].append(value)
            else:
                implicit_refs[kind].append(value)

    for (node_id, kind), values in explicitly_assigned.items():
        replace_material_kind(by_id[node_id], kind, values)

    for kind, values in implicit_refs.items():
        target = choose_node(kind, eligible_nodes(kind))
        if target is not None:
            key = (str(target["id"]), kind)
            if key in explicitly_assigned:
                raise ValueError(f"Hypit {slot} 输入同时包含显式和自动 {kind} 目标，请明确拆分输入")
            replace_material_kind(target, kind, values)
            continue
        # 无同类素材端口时，复用普通画布生成节点已有的手工引用契约；
        # 若图中有同类锁定节点，choose_node 会在这里提前拒绝，不会绕过锁。
        execution_nodes[0].setdefault("manualInputRefs", []).extend(copy.deepcopy(values))

    text_refs = [normalize_reference(ref, "text") for ref in by_kind.get("text", [])]
    prompt_target = str(request.get("prompt_target_node_id") or request.get("promptTargetNodeId") or "").strip()
    text_targets = {target_node_id(ref) for ref in text_refs if target_node_id(ref)}
    selected_prompt_target = ""
    target = None
    if prompt:
        candidates = [node for node in prompt_candidates if str(node.get("id") or "") not in text_targets]
        direct_prompt_target = False
        if prompt_target:
            if any(str(node.get("id") or "") == prompt_target for node in candidates):
                target = choose_node("text", candidates, prompt_target)
                selected_prompt_target = str(target.get("id") or "") if target else ""
            elif not prompt_candidates:
                direct_targets = [node for node in execution_nodes
                                  if not node.get("creationInputBinding")
                                  and not str(node.get("promptDraftHtml") or "").strip()]
                target = next((node for node in direct_targets
                               if str(node.get("id") or "") == prompt_target), None)
                if target is None:
                    raise ValueError(f"Hypit {slot} 提示词目标节点不存在或已有模板/引用：{prompt_target}")
                selected_prompt_target = str(target.get("id") or "")
                target["promptDraftText"] = prompt
                direct_prompt_target = True
            else:
                target = choose_node("text", candidates, prompt_target)
        else:
            unlocked = [node for node in candidates if node.get("hypitInputLocked") is not True]
            if len(unlocked) == 1:
                target = unlocked[0]
                selected_prompt_target = str(target.get("id") or "")
            elif len(unlocked) > 1:
                raise ValueError(f"Hypit {slot} 流程有多个文本输入节点，请提供明确的提示词目标节点 ID")
            elif candidates:
                raise ValueError(f"Hypit {slot} 提示词目标素材已锁定，不能替换")
            elif prompt_candidates:
                raise ValueError(f"Hypit {slot} 请求文本目标与素材映射冲突")
            else:
                direct_targets = [node for node in execution_nodes
                                  if not node.get("creationInputBinding")
                                  and not str(node.get("promptDraftHtml") or "").strip()]
                if len(direct_targets) == 1 and len(execution_nodes) == 1:
                    target = direct_targets[0]
                    selected_prompt_target = str(target.get("id") or "")
                else:
                    raise ValueError(f"Hypit {slot} 流程没有可接收提示词的唯一目标执行节点")
                # 没有上游文本节点或模板时，执行节点的 promptDraftText 仅在这份
                # 私有任务图内覆盖；保存的配置图和原默认提示保持不变。
                target["promptDraftText"] = prompt
                direct_prompt_target = True
        if target is not None:
            if target.get("hypitInputLocked") is True:
                raise ValueError(f"Hypit {slot} 提示词目标素材已锁定，不能替换")
            if direct_prompt_target:
                pass
            elif target.get("type") == "smart-prompt":
                target["text"] = prompt
            else:
                replace_material_kind(target, "text", [{"kind": "text", "text": prompt, "content": prompt}],
                                      explicit_indexes=None)

    # 用户文字素材也进入普通画布素材引用链；与 prompt 占用同一目标或有多个候选时拒绝猜测。
    assigned_text: dict[str, list[dict[str, Any]]] = defaultdict(list)
    implicit_text: list[dict[str, Any]] = []
    for ref in text_refs:
        explicit = target_node_id(ref)
        if explicit:
            target = choose_node("text", prompt_candidates, explicit)
            if prompt and explicit == selected_prompt_target:
                raise ValueError(f"Hypit {slot} 同一文本节点不能同时接收请求提示词和独立文本素材")
            assigned_text[str(target["id"])].append(ref)
        else:
            implicit_text.append(ref)
    for node_id, values in assigned_text.items():
        node = by_id[node_id]
        if node.get("type") == "smart-prompt":
            if len(values) != 1:
                raise ValueError(f"Hypit {slot} 文本目标节点只能接收一项提示词正文")
            node["text"] = str(values[0]["text"])
        else:
            replace_material_kind(node, "text", values)
    if implicit_text:
        candidates = [node for node in prompt_candidates
                      if str(node.get("id") or "") not in assigned_text
                      and str(node.get("id") or "") != selected_prompt_target]
        target = choose_node("text", candidates)
        if target is None:
            if prompt and prompt_candidates:
                raise ValueError(f"Hypit {slot} 提示词和文本素材需要分别指定稳定目标节点 ID")
            # 无显式素材节点时，沿用画布生成节点的普通手工引用字段。
            execution_nodes[0].setdefault("manualInputRefs", []).extend(copy.deepcopy(implicit_text))
        elif target.get("type") == "smart-prompt":
            if len(implicit_text) != 1:
                raise ValueError(f"Hypit {slot} 文本目标节点只能接收一项提示词正文")
            target["text"] = str(implicit_text[0]["text"])
        else:
            replace_material_kind(target, "text", implicit_text)

    parameters = request.get("parameters") if isinstance(request.get("parameters"), Mapping) else {}
    if parameters:
        target = execution_nodes[-1]
        settings = target.setdefault("runSettings", {})
        node_type = str(target.get("type") or "")
        if node_type in _STATIC_OUTPUT_KINDS:
            model_key = {"smart-text-generator": "textModel", "smart-image-generator": "model",
                         "smart-video-generator": "videoModel", "smart-audio-generator": "audioModel",
                         "smart-music-generator": "musicModel"}.get(node_type)
            model = str(settings.get(model_key) or "") if model_key else ""
            if not model:
                raise ValueError("Hypit 输出节点未选择模型，无法应用本次参数")
            per_model = settings.setdefault("capabilityParameters", {}).setdefault(model, {})
            per_model.update(copy.deepcopy(dict(parameters)))
        elif node_type == "smart-ai-app":
            settings.setdefault("rhParams", {}).update(copy.deepcopy(dict(parameters)))
            target["hypitTaskParameterOverrideKeys"] = sorted(str(key) for key in parameters)
        elif node_type == "smart-comfy-workflow":
            settings.setdefault("comfyParams", {}).update(copy.deepcopy(dict(parameters)))
            target["hypitTaskParameterOverrideKeys"] = sorted(str(key) for key in parameters)
    return {"canvas": task_canvas, "plan": plan, "recipe_fingerprint": plan["recipe_fingerprint"]}


def verify_hypit_slot_results(slot: str, results: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """只把物理类型匹配目标槽的结果交给槽位；其他类型须由调用方另行收集。"""
    slot = str(slot or "").strip().lower()
    expected = HYPIT_OUTPUT_KINDS.get(slot)
    if not expected:
        raise ValueError("Hypit 输出用途不受支持")
    matching = [copy.deepcopy(dict(item)) for item in results if isinstance(item, Mapping)
                and str(item.get("kind") or item.get("media_type") or "").strip().lower() == expected]
    if not matching:
        raise ValueError(f"Hypit {slot} 流程没有返回可确认的 {expected} 结果")
    return matching


def project_hypit_test_statuses(
    canvas: Mapping[str, Any],
    runs: list[Mapping[str, Any]],
    *,
    canvas_id: str = HYPIT_SETTINGS_CANVAS_ID,
    module_id: str = "hypit",
) -> dict[str, dict[str, Any]]:
    """只从持久化测试 run 投影各输出状态；不写图、不触发执行。"""
    graph_id = _validate_settings_canvas_identity(canvas, canvas_id=canvas_id, module_id=module_id)
    validate_hypit_settings_canvas(canvas, canvas_id=graph_id, module_id=module_id)
    outputs = {
        str(node.get("id") or ""): node
        for node in canvas.get("nodes", [])
        if isinstance(node, Mapping) and node.get("type") == "smart-hypit-output"
    }
    current_fingerprints: dict[str, str] = {}
    for output_id, output in outputs.items():
        slot = str(output.get("hypitSlot") or "").strip().lower()
        try:
            current_fingerprints[output_id] = plan_hypit_slot(
                canvas, slot, output_id, canvas_id=graph_id, module_id=module_id,
            )["recipe_fingerprint"]
        except (TypeError, ValueError):
            continue

    latest_by_output: dict[str, tuple[int, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]] = {}
    for run in runs or []:
        if not isinstance(run, Mapping):
            continue
        run_canvas_id = str(run.get("canvas_id") or (graph_id if graph_id == HYPIT_SETTINGS_CANVAS_ID else ""))
        if run_canvas_id != graph_id:
            continue
        snapshot = run.get("capability_snapshot") if isinstance(run.get("capability_snapshot"), Mapping) else {}
        if snapshot.get("hypit_output_test") is not True:
            continue
        output_id = str(snapshot.get("output_node_id") or "").strip()
        output = outputs.get(output_id)
        if output is None or str(snapshot.get("hypit_slot") or "") != str(output.get("hypitSlot") or ""):
            continue
        try:
            updated = int(run.get("updated_at") or run.get("created_at") or 0)
        except (TypeError, ValueError):
            updated = 0
        current = latest_by_output.get(output_id)
        if current is None or updated >= current[0]:
            attempts = run.get("attempts") if isinstance(run.get("attempts"), list) else []
            attempt = attempts[-1] if attempts and isinstance(attempts[-1], Mapping) else {}
            latest_by_output[output_id] = (updated, run, snapshot, attempt)

    statuses: dict[str, dict[str, Any]] = {}
    for output_id, (_, run, snapshot, attempt) in latest_by_output.items():
        output = outputs[output_id]
        slot = str(output.get("hypitSlot") or "").strip().lower()
        expected_kind = HYPIT_OUTPUT_KINDS[slot]
        status = str(attempt.get("status") or run.get("status") or "recoverable").strip().lower()
        output_kind = str(snapshot.get("output_kind") or "").strip().lower()
        recipe_matches = bool(
            snapshot.get("recipe_fingerprint")
            and snapshot.get("recipe_fingerprint") == current_fingerprints.get(output_id)
        )
        passed = status == "succeeded" and recipe_matches and output_kind == expected_kind
        statuses[output_id] = {
            "run_id": str(run.get("run_id") or ""),
            "status": "passed" if passed else status,
            "test_passed": passed,
            "current_recipe_matches": recipe_matches,
            "output_kind": output_kind,
            "error": str(attempt.get("error") or run.get("error") or ""),
        }
    return statuses
