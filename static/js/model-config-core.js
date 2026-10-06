/* 公共模型配置核心（P4）：纯状态与候选投影，不碰 DOM、不持久化、不发网络请求。
 *
 * 依据《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§5.6、§9.2、§9.3。
 *
 * 维护三个不同对象（§5.6）：
 *   committedSelection  已保存的完整选项
 *   pathDraft           弹层中的模型/平台浏览路径
 *   previewOptionId     仅悬停或键盘聚焦的预览选项
 *
 * 只有第三栏叶子提交会写持久化，且一次提交完整选择（§5.6）。
 * 本文件不依赖任何宿主页面状态，多实例之间不共享可变全局对象（§12.1）。
 */
(function (global) {
    'use strict';

    var REASON_TEXT = {
        OPTION_NOT_FOUND: { zh: '原模型选项已不存在，配置已保留待修复', en: 'The saved option no longer exists' },
        CONNECTION_DISABLED: { zh: '当前连接已停用', en: 'This connection is disabled' },
        REGION_DISABLED: { zh: '当前站点已停用', en: 'This site is disabled' },
        CREDENTIAL_NOT_CONFIGURED: { zh: '请先配置当前连接凭据', en: 'Configure credentials first' },
        PROFILE_UNCONFIRMED: { zh: '能力档案尚未确认', en: 'The capability profile is not confirmed' },
        ADAPTER_MISSING: { zh: '当前适配器未完成', en: 'The adapter is not ready' },
        HOST_OUTPUT_UNSUPPORTED: { zh: '此模块不能接收该结果类型', en: 'This host cannot consume that output' },
        OPERATION_NOT_ALLOWED: { zh: '当前槽位不允许此任务模式', en: 'This slot does not allow that operation' },
        INPUT_TYPE_UNSUPPORTED: { zh: '不支持这类输入素材', en: 'This input type is not supported' },
        ROLE_AMBIGUOUS: { zh: '请分配素材用途', en: 'Assign the purpose of these materials' },
        ROLE_CONFLICT: { zh: '显式用途与当前模式冲突', en: 'An explicit role conflicts with this operation' },
        INPUT_REQUIRED: { zh: '缺少必要输入', en: 'A required input is missing' },
        INPUT_COUNT_EXCEEDED: { zh: '输入数量超出上限', en: 'Too many inputs' },
        INPUT_COMBINATION_INVALID: { zh: '当前素材组合不符合接口要求', en: 'This input combination is not accepted' },
        INPUT_METADATA_MISSING: { zh: '无法读取素材规格', en: 'Material metadata is unavailable' },
        INPUT_SPEC_EXCEEDED: { zh: '素材规格超出限制', en: 'Material specifications exceed the limit' },
        UNCONSUMED_INPUT: { zh: '存在尚未被使用的已选素材', en: 'Some materials would not be consumed' },
        PARAM_REQUIRED: { zh: '必填参数未填', en: 'A required parameter is missing' },
        PARAM_INVALID: { zh: '参数值不合法', en: 'A parameter value is invalid' },
        PARAM_DEPENDENCY_CONFLICT: { zh: '与当前模式或其它参数冲突', en: 'Conflicts with the current operation' },
        FIXED_PARAM_OVERRIDE: { zh: '该字段由运行模式固定，不能单独覆盖', en: 'Fixed by the run mode' },
        CATALOG_CHANGED: { zh: '能力档案已更新，请确认冲突项', en: 'The catalog changed' },
        REVISION_CONFLICT: { zh: '此配置已在其他位置更新', en: 'Updated elsewhere' },
        MIGRATION_AMBIGUOUS: { zh: '旧选择可对应多个接口，需要确认', en: 'The legacy selection is ambiguous' },
        EXECUTION_ACCEPTANCE_UNKNOWN: { zh: '上游是否已受理尚待核对', en: 'Upstream acceptance is unknown' }
    };

    function text(value) { return String(value == null ? '' : value).trim(); }

    function reasonText(code) {
        var entry = REASON_TEXT[code];
        return entry || { zh: code, en: code };
    }

    /* ---------------------------------------------------------------- 状态 */

    function createState(selection) {
        var committed = normalizeSelection(selection);
        return {
            committed: committed,
            draft: draftFromCommitted(committed),
            previewOptionId: '',
            open: false,
            search: '',
            tags: [],
            showUnavailable: false,
            lastAction: ''
        };
    }

    function normalizeSelection(selection) {
        var source = selection || {};
        return {
            optionId: text(source.optionId || source.option_id),
            parameters: Object.assign({}, source.parameters || {}),
            revision: source.revision
        };
    }

    function draftFromCommitted(committed) {
        return { familyId: '', platformKey: '', optionId: '' };
    }

    function familyIdOf(option) { return text(option && option.canonical_family_id); }
    function platformKeyOf(option) {
        var connection = text(option && option.connection_id);
        var region = text(option && option.region_id);
        return region ? connection + '@' + region : connection;
    }
    function familyLabelOf(option) {
        var label = (option && option.canonical_family_label) || {};
        return { zh: text(label.zh) || familyIdOf(option), en: text(label.en) || familyIdOf(option) };
    }
    function platformLabelOf(option) {
        var platform = text(option && (option.platform_label || option.capability_provider_id));
        var region = text(option && option.region_id);
        if (region && region !== 'default') platform += ' · ' + (region === 'global' ? 'AI' : region.toUpperCase());
        return platform;
    }
    function optionTagsOf(option) { return (option && option.capability_tags) || []; }

    /* ------------------------------------------------------- 搜索与筛选 */

    function searchHaystack(option) {
        return [
            option && option.catalog_model_id,
            option && option.request_model_id,
            option && option.endpoint_id,
            option && option.legacy_family_id,
            option && option.canonical_family_id,
            option && option.model_version,
            option && option.edition_id,
            option && option.operation,
            option && option.capability_provider_id,
            option && option.region_id,
            (option && (option.model_aliases || []).join(' ')),
            (option && (option.canonical_family_label || {}).zh),
            (option && (option.canonical_family_label || {}).en)
        ].filter(Boolean).join(' ').toLowerCase();
    }

    function matchesSearch(option, query) {
        var tokens = text(query).toLowerCase().split(/\s+/).filter(Boolean);
        if (!tokens.length) return true;
        var haystack = searchHaystack(option);
        return tokens.every(function (token) { return haystack.indexOf(token) !== -1; });
    }

    // 能力标签是备选任务集合，默认 OR（§5.8）；条件类硬要求由硬要求字段承担。
    function matchesTags(option, tags) {
        var wanted = (tags || []).map(text).filter(Boolean);
        if (!wanted.length) return true;
        var own = optionTagsOf(option).map(text);
        return wanted.some(function (tag) { return own.indexOf(tag) !== -1; });
    }

    function isUsable(option) { return option && option.selectable !== false; }

    function visibleOptions(options, state) {
        return (options || []).filter(function (option) {
            if (!option) return false;
            var selected = state && state.committed && state.committed.optionId === text(option.option_id);
            // 已选中的失效条目必须保留，不能因被过滤而看不到（§5.4）
            if (selected) return matchesSearch(option, state.search);
            if (!matchesSearch(option, state.search)) return false;
            if (!matchesTags(option, state.tags)) return false;
            if (!state.showUnavailable && !isUsable(option)) return false;
            return true;
        });
    }

    function optionStatus(option) {
        if (!option) return { level: 'unknown', code: '', text: { zh: '', en: '' } };
        var reasons = option.reasons || [];
        var blocking = reasons.filter(function (item) {
            return ['OPTION_NOT_FOUND', 'CONNECTION_DISABLED', 'REGION_DISABLED', 'CREDENTIAL_NOT_CONFIGURED',
                'PROFILE_UNCONFIRMED', 'ADAPTER_MISSING', 'HOST_OUTPUT_UNSUPPORTED', 'OPERATION_NOT_ALLOWED',
                'INPUT_TYPE_UNSUPPORTED', 'ROLE_CONFLICT', 'INPUT_COUNT_EXCEEDED', 'INPUT_COMBINATION_INVALID',
                'UNCONSUMED_INPUT', 'PARAM_INVALID'].indexOf(item.code) !== -1;
        });
        var soft = reasons.filter(function (item) {
            return ['INPUT_REQUIRED', 'ROLE_AMBIGUOUS', 'INPUT_METADATA_MISSING', 'PARAM_REQUIRED'].indexOf(item.code) !== -1;
        });
        if (blocking.length) {
            return { level: 'blocked', code: blocking[0].code, text: blocking[0].message || reasonText(blocking[0].code) };
        }
        if (soft.length) {
            return { level: 'pending', code: soft[0].code, text: soft[0].message || reasonText(soft[0].code) };
        }
        return { level: 'ready', code: '', text: { zh: '', en: '' } };
    }

    /* --------------------------------------------------------- 候选投影 */

    // 三栏递进：模型 → 平台 → 运行模式（§5.2、A01）
    function projectStages(options, state) {
        var pool = visibleOptions(options, state);
        var selectedOption = findOption(options, state && state.committed && state.committed.optionId);
        var draftFamily = text(state && state.draft && state.draft.familyId) || familyIdOf(selectedOption);
        var draftPlatform = text(state && state.draft && state.draft.platformKey) || platformKeyOf(selectedOption);

        var families = [];
        var familyIndex = {};
        pool.forEach(function (option) {
            var id = familyIdOf(option);
            if (!id) return;
            if (!familyIndex[id]) {
                var label = familyLabelOf(option);
                familyIndex[id] = { id: id, label: label, options: [], platforms: [], tags: [] };
                families.push(familyIndex[id]);
            }
            familyIndex[id].options.push(option);
            var platformKey = platformKeyOf(option);
            if (familyIndex[id].platforms.indexOf(platformKey) === -1) familyIndex[id].platforms.push(platformKey);
            optionTagsOf(option).forEach(function (tag) {
                if (familyIndex[id].tags.indexOf(tag) === -1) familyIndex[id].tags.push(tag);
            });
        });

        // 尚无已选值时，浏览路径落到第一个候选，保证三栏都有内容（A08）。
        // 这只是弹层内的浏览状态，不写任何持久化，也不代表已选中模型。
        var effectiveFamily = draftFamily || (families[0] && families[0].id) || '';
        var platformMap = {};
        var platforms = [];
        pool.filter(function (option) { return familyIdOf(option) === effectiveFamily; }).forEach(function (option) {
            var key = platformKeyOf(option);
            if (!platformMap[key]) {
                platformMap[key] = { key: key, label: platformLabelOf(option), connectionId: text(option.connection_id), regionId: text(option.region_id), count: 0 };
                platforms.push(platformMap[key]);
            }
            platformMap[key].count += 1;
        });

        var effectivePlatform = draftPlatform;
        if (!platforms.some(function (platform) { return platform.key === effectivePlatform; })) {
            effectivePlatform = (platforms[0] && platforms[0].key) || '';
        }

        var variants = pool.filter(function (option) {
            return familyIdOf(option) === effectiveFamily && platformKeyOf(option) === effectivePlatform;
        }).map(function (option) {
            return { option: option, status: optionStatus(option), label: variantLabel(option) };
        });

        return {
            families: families,
            platforms: platforms,
            variants: variants,
            draftFamilyId: effectiveFamily,
            draftPlatformKey: effectivePlatform,
            selectedOption: selectedOption || null
        };
    }

    // 第三栏叶子主标题：必要产品版本 · 必要档次 · 任务模式（§5.5）
    function variantLabel(option) {
        var lang = global.StudioI18n?.lang?.() === 'en' ? 'en' : 'zh';
        if (option?.display_label?.[lang]) return text(option.display_label[lang]);
        var parts = [text(option && option.model_version), text(option && option.edition_id), text(option && option.operation)];
        var joined = parts.filter(Boolean).join(' · ');
        return joined || text(option && option.catalog_model_id);
    }

    function findOption(options, optionId) {
        var wanted = text(optionId);
        if (!wanted) return null;
        var list = options || [];
        for (var i = 0; i < list.length; i += 1) {
            if (text(list[i] && list[i].option_id) === wanted) return list[i];
        }
        return null;
    }

    /* ------------------------------------------------------------- 事件 */

    // 每个事件返回 {state, effects}；effects 描述是否写持久化与是否收起（§5.6）
    function act(state, event, payload) {
        var next = Object.assign({}, state, {
            draft: Object.assign({}, state.draft),
            tags: (state.tags || []).slice()
        });
        var effects = { persist: false, close: false, notifyPreview: false, rejected: null };
        event = text(event);

        if (event === 'open') {
            next.open = true;
            next.draft = draftFromCommitted(state.committed);
            next.previewOptionId = '';
        } else if (event === 'close') {
            next.open = false;
            next.draft = state.draft;
            next.previewOptionId = '';
        } else if (event === 'cancel') {
            // Escape / 点击外部：丢弃草稿与预览，保留参数里已确认的修改（§5.6）
            next.open = false;
            next.draft = draftFromCommitted(state.committed);
            next.previewOptionId = '';
        } else if (event === 'selectFamily') {
            next.draft = { familyId: text(payload && payload.familyId), platformKey: '', optionId: '' };
            next.previewOptionId = '';
        } else if (event === 'selectPlatform') {
            next.draft = Object.assign({}, next.draft, { platformKey: text(payload && payload.platformKey), optionId: '' });
            next.previewOptionId = '';
        } else if (event === 'previewOption') {
            next.previewOptionId = text(payload && payload.optionId);
            effects.notifyPreview = true;
        } else if (event === 'clearPreview') {
            next.previewOptionId = '';
            effects.notifyPreview = true;
        } else if (event === 'search') {
            next.search = String((payload && payload.query) || '');
        } else if (event === 'toggleTag') {
            var tag = text(payload && payload.tag);
            var index = next.tags.indexOf(tag);
            if (index === -1) next.tags.push(tag); else next.tags.splice(index, 1);
        } else if (event === 'clearFilters') {
            next.search = '';
            next.tags = [];
        } else if (event === 'toggleShowUnavailable') {
            next.showUnavailable = !next.showUnavailable;
        } else if (event === 'clickVariant') {
            var option = payload && payload.option;
            var status = optionStatus(option);
            if (status.level === 'blocked') {
                // 点击被禁用模式：展示具体原因，不写库、不收起（§5.6）
                effects.rejected = status;
                next.lastAction = 'rejected';
            } else {
                next.committed = {
                    optionId: text(option.option_id),
                    parameters: Object.assign({}, (payload && payload.parameters) || next.committed.parameters || {}),
                    revision: next.committed.revision
                };
                next.open = false;
                next.previewOptionId = '';
                next.draft = draftFromCommitted(next.committed);
                next.lastAction = 'committed';
                effects.persist = true;   // 只有最后一栏提交才写一次
                effects.close = true;
                effects.committed = next.committed;
            }
        } else if (event === 'updateParameters') {
            next.committed = Object.assign({}, next.committed, {
                parameters: Object.assign({}, next.committed.parameters, (payload && payload.parameters) || {})
            });
            next.lastAction = 'parameterDraft';
        } else if (event === 'catalogUpdated') {
            // 目录更新：保留已选身份，清理过期预览（§5.6）
            var stillThere = findOption(payload && payload.options, state.committed && state.committed.optionId);
            next.previewOptionId = '';
            next.catalogMissing = !stillThere && !!text(state.committed && state.committed.optionId);
        }
        return { state: next, effects: effects };
    }

    /* --------------------------------------------------------------- 摘要 */

    // 节点底部两条入口（§5.1）：
    //   第一行 模型 · 平台 · 运行模式；第二行只放参数摘要 720p · 5秒 · 有声 · 16:9
    function selectionParts(option) {
        if (!option) return [];
        var lang = global.StudioI18n?.lang?.() === 'en' ? 'en' : 'zh';
        var parts = [familyLabelOf(option)[lang], platformLabelOf(option)];
        var leaf = variantLabel(option);
        if (leaf) parts.push(leaf);
        return parts.filter(Boolean);
    }

    // 摘要只展示当前有效常用字段，不把旧草稿拼进去（§6.8）
    function summaryParts(optionOrParameters, parametersOrProfile, maybeProfile) {
        // 兼容两种调用：summaryParts(option, parameters, profile) / summaryParts(parameters, profile)
        var parameters = parametersOrProfile || {};
        var profile = maybeProfile;
        if (maybeProfile === undefined) {
            parameters = optionOrParameters || {};
            profile = parametersOrProfile;
        }
        var specs = (profile && profile.parameters) || {};
        var parts = [];
        Object.keys(parameters || {}).forEach(function (key) {
            var spec = specs[key];
            if (!spec) return;
            var uiLevel = (spec.ui && spec.ui.level) || (spec.level === 'advanced' ? 'advanced' : 'common');
            if (uiLevel !== 'common') return;
            var value = parameters[key];
            if (value === undefined || value === null || value === '') return;
            parts.push(formatParameterValue(spec, value));
        });
        return parts.filter(Boolean);
    }

    function formatParameterValue(spec, value) {
        var label = (spec && (spec.label || spec.title)) || '';
        var textValue = typeof value === 'boolean' ? (value ? '是' : '否') : String(value);
        var unit = text(spec && spec.unit);
        if (unit === 'seconds') return textValue + '秒';
        if (spec && (spec.type === 'enum' || spec.type === 'boolean')) return textValue;
        return label ? label + ' ' + textValue : textValue;
    }

    // 真实接口标识行：目录 ID 与真实请求 ID / endpoint 分开（§5.7）
    function identifierLines(option) {
        if (!option) return { primary: '', primaryKind: '', detail: [] };
        var catalogId = text(option.catalog_model_id);
        var requestId = text(option.request_model_id);
        var endpointId = text(option.endpoint_id);
        var detail = [];
        if (requestId && requestId !== catalogId) detail.push({ label: '请求模型', value: requestId });
        if (endpointId && endpointId !== catalogId) detail.push({ label: '接口 ID', value: endpointId });
        return {
            primary: catalogId,
            primaryKind: requestId ? '目录 ID' : '接口 ID',
            detail: detail
        };
    }

    function copyValueFor(option, previewOptionId) {
        var target = previewOptionId ? { option_id: previewOptionId } : option;
        if (previewOptionId && option && text(option.option_id) === previewOptionId) target = option;
        return text(target && (target.request_model_id || target.endpoint_id || target.catalog_model_id));
    }

    function parameterRequired(spec) {
        return !!(spec && (spec.required === true || (spec.ui && spec.ui.required === true) || text(spec.level).toLowerCase() === 'required'));
    }

    function parameterDefaultIsValid(spec) {
        if (!spec || !Object.prototype.hasOwnProperty.call(spec, 'default') || spec.default === undefined || spec.default === null || spec.default === '') return false;
        var value = spec.default;
        var type = text(spec.type).toLowerCase();
        // enum 的默认值只有在选项清单存在且命中时才可验证；缺少候选
        // 清单代表契约资料不完整，不能把任意非空默认值当成可运行值。
        if (type === 'enum' && (!Array.isArray(spec.options) || !spec.options.length)) return false;
        if (Array.isArray(spec.options) && (!spec.options.length || !spec.options.some(function (item) { return item === value || String(item) === String(value); }))) return false;
        if (type === 'boolean') return value === true || value === false || value === 'true' || value === 'false' || value === 1 || value === 0;
        if (type === 'integer') return Number.isInteger(Number(value)) && Number.isFinite(Number(value))
            && (spec.min == null || Number(value) >= Number(spec.min))
            && (spec.max == null || Number(value) <= Number(spec.max));
        if (type === 'number') return Number.isFinite(Number(value))
            && (spec.min == null || Number(value) >= Number(spec.min))
            && (spec.max == null || Number(value) <= Number(spec.max));
        return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean';
    }

    function parameterMustStayVisible(spec) {
        return parameterRequired(spec) && !parameterDefaultIsValid(spec);
    }

    var api = {
        REASON_TEXT: REASON_TEXT,
        reasonText: reasonText,
        createState: createState,
        normalizeSelection: normalizeSelection,
        act: act,
        projectStages: projectStages,
        visibleOptions: visibleOptions,
        optionStatus: optionStatus,
        variantLabel: variantLabel,
        familyIdOf: familyIdOf,
        platformKeyOf: platformKeyOf,
        familyLabelOf: familyLabelOf,
        platformLabelOf: platformLabelOf,
        matchesSearch: matchesSearch,
        matchesTags: matchesTags,
        findOption: findOption,
        selectionParts: selectionParts,
        summaryParts: summaryParts,
        formatParameterValue: formatParameterValue,
        identifierLines: identifierLines,
        copyValueFor: copyValueFor,
        parameterRequired: parameterRequired,
        parameterDefaultIsValid: parameterDefaultIsValid,
        parameterMustStayVisible: parameterMustStayVisible
    };

    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    global.ModelConfigCore = api;
})(typeof window !== 'undefined' ? window : globalThis);
