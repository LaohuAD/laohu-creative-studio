/* 画布模型配置宿主（P5）：把画布节点接到公共控件，不复制选择算法。
 *
 * 依据《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§8.4、§9.2、§9.3、§12.1、§12.4。
 *
 * 职责（§9.2 CanvasModelConfigHost）：
 *   - 从节点与连线构造上下文，写节点配置与撤销命令；
 *   - 不重新实现选择算法，不把整个 canvas 状态传进公共组件；
 *   - 每个实例只持有自己的 nodeId 与草稿，不依赖跨页面“当前节点”变量（§12.1）。
 *
 * 选择记录的存储（§8.4）：节点上的 modelSelection 是新真相源；
 * provider_id / model / rhRegion 等旧字段由新选择派生，供旧代码读取，不再反向覆盖。
 */
(function (global) {
    'use strict';

    var Core = global.ModelConfigCore;
    var Inputs = global.CanvasInputBindings;

    var SELECTION_SCHEMA_VERSION = 2;

    function text(value) { return String(value == null ? '' : value).trim(); }

    function requireDependencies() {
        if (!Core) throw new Error('canvas-model-config-host 需要先加载 model-config-core.js');
        if (!Inputs) throw new Error('canvas-model-config-host 需要先加载 canvas-input-bindings.js');
        return true;
    }

    // 节点上的新选择记录；缺失说明尚未迁移（P7 处理），此处不做猜测
    function selectionForNode(node) {
        var record = node && node.modelSelection;
        if (!record || typeof record !== 'object') return null;
        var optionId = text(record.option_id || record.optionId);
        if (!optionId) return null;
        return {
            schema_version: SELECTION_SCHEMA_VERSION,
            optionId: optionId,
            connectionId: text(record.connection_id || record.connectionId),
            regionId: text(record.region_id || record.regionId),
            operation: text(record.operation),
            parameters: Object.assign({}, record.parameters || {}),
            parameterOrigins: Object.assign({}, record.parameter_origins || {}),
            revision: record.revision
        };
    }

    // 由完整选择派生旧字段，供旧读取路径使用（§8.4）
    function legacyFieldsFromSelection(option, selection) {
        if (!option) return {};
        return {
            provider_id: text(option.connection_id) || text(option.capability_provider_id),
            model: text(option.catalog_model_id),
            rhRegion: text(option.region_id),
            operation: text(option.operation)
        };
    }

    function selectionRecordFrom(option, selection, previous) {
        var parameters = Object.assign({}, (previous && previous.parameters) || {}, (selection && selection.parameters) || {});
        return {
            schema_version: SELECTION_SCHEMA_VERSION,
            option_id: text(option && option.option_id),
            connection_id: text(option && option.connection_id),
            region_id: text(option && option.region_id),
            operation: text(option && option.operation),
            profile_revision_seen: text(option && option.profile_revision),
            parameters: parameters,
            parameter_origins: (previous && previous.parameter_origins) || {},
            revision: Number((previous && previous.revision) || 0) + 1
        };
    }

    function createCanvasModelConfigHost(options) {
        requireDependencies();
        var config = options || {};
        var readNode = config.readNode || function () { return null; };
        var writeNode = config.writeNode || function () {};
        var pushUndo = config.pushUndo || function () {};
        var graphNodes = config.nodes || [];
        var graphConnections = config.connections || [];
        var catalog = config.catalog || { options: [], profiles: [] };
        var instances = {};

        function refreshGraph(nextNodes, nextConnections) {
            if (Array.isArray(nextNodes)) graphNodes = nextNodes;
            if (Array.isArray(nextConnections)) graphConnections = nextConnections;
        }

        function refreshCatalog(nextCatalog) {
            catalog = nextCatalog || { options: [], profiles: [] };
            Object.keys(instances).forEach(function (key) { instances[key].updateCatalog(catalog); });
        }

        // 从真实节点与连线构造上下文；只传公共组件需要的字段（§9.1）
        function buildContext(nodeId, phase) {
            var node = readNode(nodeId);
            var bindings = Inputs.collectInputBindings({
                node: node, nodes: graphNodes, connections: graphConnections,
                selectedOutputs: (node && node.selectedOutputs) || {}
            });
            return {
                host: 'canvas',
                moduleId: 'canvas',
                slotId: text(node && node.type),
                phase: phase || 'live',
                nodeId: text(nodeId),
                inputBindings: bindings,
                inputCounts: Inputs.countBindings(bindings),
                inputRoles: Inputs.roleCounts(bindings),
                pendingInputs: Inputs.pendingBindings(bindings).map(function (binding) { return binding.binding_id; }),
                hostContract: config.hostContract || {}
            };
        }

        function withEvaluation(scope) {
            // 目录中的可执行选项由后端带回 selectable / runnable / reasons；
            // 这里只把当前输入上下文对应的评估结果附加上去，不在前端重算规则（§13.5）。
            var bindings = scope.inputBindings || [];
            var counts = scope.inputCounts || {};
            return (catalog.options || []).map(function (option) {
                var evaluated = option;
                if (typeof config.evaluate === 'function') {
                    evaluated = Object.assign({}, option, config.evaluate(option, scope, counts, bindings));
                }
                return evaluated;
            });
        }

        function mount(container, nodeId, callbacks) {
            requireDependencies();
            var scope = buildContext(nodeId, (callbacks && callbacks.phase) || 'live');
            var instance = global.mountModelConfigControl(container, {
                context: scope,
                catalog: { options: withEvaluation(scope), profiles: catalog.profiles || [] },
                selection: selectionForNode(readNode(nodeId)) || { optionId: '', parameters: {} },
                presentation: (callbacks && callbacks.presentation) || 'popover',
                onPreview: function (payload) {
                    if (callbacks && typeof callbacks.onPreview === 'function') callbacks.onPreview(payload);
                },
                onParametersChange: function (payload) {
                    applyParameters(nodeId, payload.parameters || {});
                },
                onCommit: function (payload) {
                    return commit(nodeId, payload);
                }
            });
            instances[nodeId] = instance;
            return instance;
        }

        function optionById(optionId) {
            var wanted = text(optionId);
            var list = catalog.options || [];
            for (var i = 0; i < list.length; i += 1) {
                if (text(list[i] && list[i].option_id) === wanted) return list[i];
            }
            return null;
        }

        // 提交：写节点 + 记撤销命令；只改该节点的选择，不动其他节点或连线（§12.4）
        function commit(nodeId, payload) {
            var node = readNode(nodeId);
            if (!node) throw new Error('找不到节点：' + nodeId);
            var option = optionById(payload && payload.selection && payload.selection.optionId);
            if (!option) throw new Error('选择不属于当前目录：' + text(payload && payload.selection && payload.selection.optionId));
            var before = {
                modelSelection: node.modelSelection || null,
                provider_id: node.provider_id, model: node.model, rhRegion: node.rhRegion
            };
            var record = selectionRecordFrom(option, payload.selection, node.modelSelection);
            var patch = Object.assign({ modelSelection: record }, legacyFieldsFromSelection(option, payload.selection));
            writeNode(nodeId, patch);
            pushUndo({
                type: 'modelSelection',
                nodeId: nodeId,
                before: before,
                after: {
                    modelSelection: record,
                    provider_id: patch.provider_id, model: patch.model, rhRegion: patch.rhRegion
                }
            });
            return { nodeId: nodeId, selection: record };
        }

        // 参数草案：只改参数，不改模型/平台/连线；撤销时与模型切换合并成一条命令
        function applyParameters(nodeId, parameters) {
            var node = readNode(nodeId);
            if (!node) return null;
            var before = node.modelSelection || null;
            var record = Object.assign({}, before || {}, {
                schema_version: SELECTION_SCHEMA_VERSION,
                parameters: Object.assign({}, (before && before.parameters) || {}, parameters || {}),
                parameter_origins: Object.assign({}, (before && before.parameter_origins) || {}),
                revision: Number((before && before.revision) || 0) + 1
            });
            Object.keys(parameters || {}).forEach(function (key) {
                record.parameter_origins[key] = 'user';
            });
            writeNode(nodeId, { modelSelection: record });
            return record;
        }

        // 已选失效显示（§5.4、§15.6）：保留原 ID 与原因，不自动换模型
        function invalidStateForNode(nodeId) {
            var node = readNode(nodeId);
            var selection = selectionForNode(node);
            if (!selection) return { migrated: false, missing: false, option: null, reasons: [] };
            var option = optionById(selection.optionId);
            if (option) return { migrated: true, missing: false, option: option, reasons: option.reasons || [] };
            return {
                migrated: true, missing: true, option: null,
                reasons: [{ code: 'OPTION_NOT_FOUND', message: Core.reasonText('OPTION_NOT_FOUND') }],
                keptOptionId: selection.optionId
            };
        }

        function destroy(nodeId) {
            var instance = instances[nodeId];
            if (instance) { instance.destroy(); delete instances[nodeId]; }
        }

        function destroyAll() {
            Object.keys(instances).forEach(destroy);
        }

        return {
            buildContext: buildContext,
            selectionForNode: selectionForNode,
            invalidStateForNode: invalidStateForNode,
            mount: mount,
            commit: commit,
            applyParameters: applyParameters,
            refreshGraph: refreshGraph,
            refreshCatalog: refreshCatalog,
            destroy: destroy,
            destroyAll: destroyAll,
            instances: instances
        };
    }

    // 旧节点解析（§15.2）：只做确定性映射，出现歧义就报待确认，绝不猜第一个候选。
    function resolveLegacyNodeSelection(node, options) {
        var record = node && node.modelSelection;
        var list = Array.isArray(options) ? options : [];
        if (record && text(record.option_id)) {
            var known = list.some(function (option) { return text(option.option_id) === text(record.option_id); });
            if (known) {
                return { resolved: true, ambiguous: false, optionId: text(record.option_id), reason: '' };
            }
            // 目录已移除该选项：保留原 ID，标记需要修复，不自动换模型（§15.6）
            return {
                resolved: false, ambiguous: false, optionId: '',
                keptOptionId: text(record.option_id), reason: 'OPTION_NOT_FOUND'
            };
        }
        var providerId = text(node && node.provider_id);
        var modelId = text(node && node.model);
        var region = text(node && (node.rhRegion || node.region_id));
        if (!providerId || !modelId) {
            return { resolved: false, ambiguous: false, optionId: '', reason: 'MIGRATION_AMBIGUOUS' };
        }
        var candidates = list.filter(function (option) {
            return text(option.connection_id) === providerId && text(option.catalog_model_id) === modelId;
        });
        if (!candidates.length) {
            return { resolved: false, ambiguous: false, optionId: '', reason: 'OPTION_NOT_FOUND' };
        }
        if (region) {
            candidates = candidates.filter(function (option) { return text(option.region_id) === region; });
        }
        if (candidates.length === 1) {
            return { resolved: true, ambiguous: false, optionId: text(candidates[0].option_id), reason: '' };
        }
        // 多个候选、或缺少站点信息而候选不止一条：需要人工确认，不猜当前默认站
        return { resolved: false, ambiguous: true, optionId: '', reason: 'MIGRATION_AMBIGUOUS' };
    }

    var api = {
        SELECTION_SCHEMA_VERSION: SELECTION_SCHEMA_VERSION,
        selectionForNode: selectionForNode,
        legacyFieldsFromSelection: legacyFieldsFromSelection,
        selectionRecordFrom: selectionRecordFrom,
        createCanvasModelConfigHost: createCanvasModelConfigHost,
        resolveLegacyNodeSelection: resolveLegacyNodeSelection
    };

    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    global.CanvasModelConfigHost = api;
})(typeof window !== 'undefined' ? window : globalThis);
