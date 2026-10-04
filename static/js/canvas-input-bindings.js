/* 画布输入绑定收集（P5）：把真实节点与连线整理成 InputBinding[]。
 *
 * 依据《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§7.2、§7.3、§7.10。
 *
 * 关键约束：
 *   - 每一份实际参与调用的素材是一项，不是每根连线是一项（§7.2）。
 *     一根边带着 3 个输出，就是 3 项输入。
 *   - 只读宿主传入的 nodes / connections 数组，不接受整个 canvas 对象（§9.1）。
 *   - 虚线关系（story / history）不参与模型输入、参数与运行依赖。
 *   - 不猜测角色：能明确来源的标记来源，推断不出来的保持 unassigned（§7.3、§7.8）。
 *   - 纯函数：不修改传入数据、不发请求、不写画布。
 */
(function (global) {
    'use strict';

    // 参与执行的连线语义；story / history 等关系不进入模型输入
    var EXECUTION_KINDS = ['flow', 'input'];
    var NON_INPUT_KINDS = ['story', 'history', 'historyFor'];

    var MEDIA_FIELDS = [
        { field: 'images', media: 'image' },
        { field: 'videos', media: 'video' },
        { field: 'audios', media: 'audio' },
        { field: 'texts', media: 'text' }
    ];

    function text(value) { return String(value == null ? '' : value).trim(); }

    function connectionId(connection, fallbackIndex) {
        return text(connection && connection.id)
            || [text(connection && connection.from), text(connection && connection.to), fallbackIndex].join('~');
    }

    function connectionKind(connection) {
        return text(connection && connection.kind) || 'flow';
    }

    function isExecutionConnection(connection) {
        var kind = connectionKind(connection);
        if (NON_INPUT_KINDS.indexOf(kind) !== -1) return false;
        return EXECUTION_KINDS.indexOf(kind) !== -1;
    }

    function outputsOf(node) {
        var out = [];
        MEDIA_FIELDS.forEach(function (spec) {
            var items = node && node[spec.field];
            if (!Array.isArray(items)) return;
            items.forEach(function (item, index) {
                out.push({
                    mediaType: spec.media,
                    field: spec.field,
                    index: index,
                    item: item || {},
                    url: text(item && (item.url || item.src)),
                    assetId: text(item && (item.assetId || item.asset_id || item.id)),
                    resultId: text(item && (item.resultId || item.result_id)),
                    role: text(item && item.role)
                });
            });
        });
        return out;
    }

    // 上游节点是否仍在产出：用于区分 ready / pending，不据此判定“没有输入”（§7.4）
    function upstreamPending(node) {
        if (!node) return false;
        if (text(node.runStatus) === 'running' || text(node.runStatus) === 'queued') return true;
        if (node.runRef && !text(node.runRef.finishedAt)) return true;
        return false;
    }

    function collectInputBindings(options) {
        var config = options || {};
        var target = config.node || null;
        var nodes = Array.isArray(config.nodes) ? config.nodes : [];
        var connections = Array.isArray(config.connections) ? config.connections : [];
        var selection = config.selectedOutputs || {};
        var targetId = text(target && target.id);
        if (!targetId) return [];

        var nodeMap = {};
        nodes.forEach(function (node) {
            var id = text(node && node.id);
            if (id) nodeMap[id] = node;
        });

        var bindings = [];
        var order = 0;
        connections.forEach(function (connection, connectionIndex) {
            if (!isExecutionConnection(connection)) return;
            var to = text(connection && connection.to);
            if (to !== targetId) return;
            var from = text(connection && connection.from);
            var source = nodeMap[from];
            if (!source && !from) return;

            var outputs = outputsOf(source);
            var wanted = selection[from];
            if (Array.isArray(wanted) && wanted.length) {
                var allowed = {};
                wanted.forEach(function (value) { allowed[String(value)] = true; });
                outputs = outputs.filter(function (output) { return allowed[String(output.index)] === true; });
            }
            var sourceResultId = text(connection && connection.sourceResultId);
            if (sourceResultId) {
                outputs = outputs.filter(function (output) { return output.resultId === sourceResultId; });
            }

            var pending = upstreamPending(source);
            var cid = connectionId(connection, connectionIndex);
            outputs.forEach(function (output) {
                // 不做唯一推断：单张图片既可能是首帧也可能是参考图，语义留给用户或模式决定（B02）。
                // 只有上游已明确写入 role 时才沿用，并标记为 legacy_mapping。
                var role = output.role;
                var origin = role ? 'legacy_mapping' : 'unassigned';
                bindings.push({
                    binding_id: cid + ':output-' + output.index,
                    source_kind: 'canvas_edge',
                    source_node_id: from,
                    output_index: output.index,
                    asset_id: output.assetId || output.url,
                    media_type: output.mediaType,
                    role: role || 'unassigned',
                    role_origin: origin,
                    order: order,
                    materialization: pending ? 'pending' : (output.url || output.assetId ? 'ready' : 'pending'),
                    metadata: {},
                    metadata_status: 'unknown'
                });
                order += 1;
            });
        });
        return bindings;
    }

    // 逐素材计数（§7.2）：一根边的 3 个输出算 3 项
    function countBindings(bindings) {
        var counts = {};
        (bindings || []).forEach(function (binding) {
            var media = text(binding && binding.media_type) || 'unknown';
            counts[media] = (counts[media] || 0) + 1;
        });
        return counts;
    }

    // 角色汇总（与后端 input_roles 语义保持一致）
    function roleCounts(bindings) {
        var roles = {};
        (bindings || []).forEach(function (binding) {
            var role = text(binding && binding.role);
            if (!role || role === 'unassigned') return;
            roles[role] = (roles[role] || 0) + 1;
        });
        return roles;
    }

    function pendingBindings(bindings) {
        return (bindings || []).filter(function (binding) {
            return text(binding && binding.materialization) === 'pending';
        });
    }

    var api = {
        EXECUTION_KINDS: EXECUTION_KINDS,
        NON_INPUT_KINDS: NON_INPUT_KINDS,
        isExecutionConnection: isExecutionConnection,
        outputsOf: outputsOf,
        upstreamPending: upstreamPending,
        collectInputBindings: collectInputBindings,
        countBindings: countBindings,
        roleCounts: roleCounts,
        pendingBindings: pendingBindings
    };

    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    global.CanvasInputBindings = api;
})(typeof window !== 'undefined' ? window : globalThis);
