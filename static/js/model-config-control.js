/* 公共模型配置控件（P4）：三栏选择器 + 常用/高级参数面板。
 *
 * 依据《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§5、§9.2、§9.3、§13.3、§13.4。
 *
 * 职责边界（§9.2）：
 *   - 只负责 DOM 与交互；状态、候选投影、参数协调复用 ModelConfigCore；
 *   - 不读密钥、不发网络请求、不保存画布或模块设置；
 *   - onCommit 只由“点击合法叶子”触发，render / hover / 默认值展示都不得触发（§9.3）。
 *
 * 宿主通过 mountModelConfigControl(container, options) 挂载，并可用
 * updateCatalog / updateContext / updateSelection / destroy 生命周期接口（§9.3）。
 */
(function (global) {
    'use strict';

    var Core = global.ModelConfigCore;
    if (!Core) throw new Error('model-config-control 需要先加载 model-config-core.js');

    var PORTAL_ID = 'model-config-portal';
    var instances = 0;

    function text(value) { return String(value == null ? '' : value).trim(); }
    function language() { return global.StudioI18n?.lang?.() === 'en' ? 'en' : 'zh'; }

    function el(tag, className, content) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (content !== undefined) node.textContent = content;
        return node;
    }

    // 浮层不放在随画布 transform 缩放的层内，统一挂到公共 portal 根（§13.3）
    function portalRoot(hostDocument) {
        var doc = hostDocument || document;
        var root = doc.getElementById(PORTAL_ID);
        if (!root) {
            root = doc.createElement('div');
            root.id = PORTAL_ID;
            root.className = 'model-config-portal';
            doc.body.appendChild(root);
        }
        return root;
    }

    function mountModelConfigControl(container, options) {
        var config = options || {};
        var doc = container.ownerDocument || document;
        var win = doc.defaultView || window;
        var state = Core.createState(config.selection);
        var instanceId = 'mc' + (++instances);
        var catalog = config.catalog || { options: [] };
        var context = config.context || {};
        var profiles = {};
        var destroyed = false;
        var listeners = [];

        function on(target, type, handler, opts) {
            target.addEventListener(type, handler, opts);
            listeners.push(function () { target.removeEventListener(type, handler, opts); });
        }

        /* ------------------------------------------------------------ 索引 */

        function indexProfiles() {
            profiles = {};
            (catalog.profiles || []).forEach(function (profile) {
                profiles[text(profile.profile_ref || profile.model_id)] = profile;
            });
        }

        function profileFor(option) {
            if (!option) return null;
            var found = profiles[text(option.profile_ref)] || profiles[text(option.catalog_model_id)] || option.profile || null;
            if (found) return found;
            // 后端投影已把参数 schema 与输入契约随选项下发，控件可直接使用（§11.2）
            if (option.parameters || option.inputs) {
                return {
                    parameters: option.parameters || {},
                    inputs: option.inputs || {},
                    fixed_parameters: option.fixed_parameters || {}
                };
            }
            return null;
        }

        function optionsById() {
            return catalog.options || [];
        }

        /* ------------------------------------------------------------ 根节点 */

        var root = el('div', 'model-config');
        root.setAttribute('data-model-config-instance', instanceId);

        var trigger = el('button', 'model-config-trigger');
        trigger.type = 'button';
        trigger.setAttribute('aria-haspopup', 'dialog');
        var triggerText = el('span', 'model-config-trigger-value');
        var triggerCaret = el('i', 'model-config-caret');
        triggerCaret.setAttribute('aria-hidden', 'true');
        trigger.appendChild(triggerText);
        trigger.appendChild(triggerCaret);

        var summary = el('button', 'model-config-summary');
        summary.type = 'button';
        var summaryText = el('span', 'model-config-summary-value');
        summary.appendChild(summaryText);

        var gear = el('button', 'model-config-gear');
        gear.type = 'button';
        gear.setAttribute('aria-label', language() === 'en' ? 'Advanced parameters' : '高级参数');
        gear.appendChild(el('span', 'model-config-gear-icon', '⚙'));

        var actions = el('div', 'model-config-actions');
        actions.appendChild(summary);
        actions.appendChild(gear);

        var bar = el('div', 'model-config-bar');
        bar.appendChild(trigger);
        if (!config.modelOnly) bar.appendChild(actions);

        var popover = el('div', 'model-config-popover');
        popover.setAttribute('role', 'dialog');
        popover.hidden = true;

        var inline = config.presentation === 'inline';
        // 模块设置使用可折叠的本地面板；画布仍使用默认 portal 弹层，
        // 这样 Hypit 可以保持六行紧凑布局而不改变画布交互。
        var modulePresentation = config.presentation === 'module';
        root.appendChild(bar);
        if (inline) {
            // 内联表现（§16 P4 第 4 项）：同一套控件与状态机，只换承载方式，不复制核心逻辑。
            root.classList.add('model-config-inline');
            popover.classList.add('is-inline');
            popover.hidden = false;
            bar.hidden = true;
            root.appendChild(popover);
        } else if (modulePresentation) {
            root.classList.add('model-config-module');
            popover.classList.add('is-module');
            popover.hidden = true;
            root.appendChild(popover);
        } else {
            portalRoot(doc).appendChild(popover);
            popover.hidden = true;
        }
        container.appendChild(root);

        /* ------------------------------------------------------------ 弹层 */

        var head = el('div', 'model-config-head');
        var idRow = el('div', 'model-config-id-row');
        var idLabel = el('span', 'model-config-id-label');
        var idValue = el('code', 'model-config-id-value');
        var idKind = el('span', 'model-config-id-kind');
        var copyBtn = el('button', 'model-config-copy');
        copyBtn.type = 'button';
        copyBtn.textContent = language() === 'en' ? 'Copy' : '复制';
        idRow.appendChild(idLabel);
        idRow.appendChild(idValue);
        idRow.appendChild(idKind);
        idRow.appendChild(copyBtn);
        head.appendChild(idRow);

        var searchWrap = el('label', 'model-config-search');
        var searchInput = el('input');
        searchInput.type = 'search';
        searchInput.setAttribute('data-model-config-search', '');
        searchInput.placeholder = language() === 'en' ? 'Search models, versions or IDs' : '搜索模型、版本或真实 ID';
        searchInput.autocomplete = 'off';
        searchWrap.appendChild(searchInput);
        head.appendChild(searchWrap);

        var tagRow = el('div', 'model-config-tags');
        head.appendChild(tagRow);
        popover.appendChild(head);

        var stages = el('div', 'model-config-stages');
        var columns = {};
        ['family', 'platform', 'variant'].forEach(function (stage, index) {
            var column = el('section', 'model-config-stage model-config-stage-' + stage);
            column.setAttribute('data-stage', stage);
            var title = el('h4', 'model-config-stage-title');
            title.appendChild(el('span', 'model-config-stage-index', String(index + 1)));
            title.appendChild(el('strong', null, (language() === 'en' ? ['Model', 'Platform', 'Run mode'] : ['模型', '平台', '运行模式'])[index]));
            var list = el('div', 'model-config-stage-options');
            list.setAttribute('role', 'listbox');
            column.appendChild(title);
            column.appendChild(list);
            stages.appendChild(column);
            columns[stage] = { root: column, title: title, list: list };
        });
        popover.appendChild(stages);

        var noMatch = el('div', 'model-config-empty', '没有匹配的模型、模式或平台');
        noMatch.hidden = true;
        popover.appendChild(noMatch);

        var panel = el('div', 'model-config-parameters');
        panel.hidden = true;
        popover.appendChild(panel);

        /* --------------------------------------------------------- 事件绑定 */

        on(trigger, 'click', function () {
            focusPanel = 'model';
            transition(state.open ? 'cancel' : 'open');
        });

        on(summary, 'click', function () {
            focusPanel = 'parameters';
            transition(state.open ? 'cancel' : 'open');
        });

        // 点击完成后再收起，避免 mousedown 折叠前一块导致下一按钮移动、吞掉本次点击。
        on(doc, 'click', function (event) {
            if (inline || destroyed || !state.open) return;
            var target = event.target;
            if (popover.contains(target) || root.contains(target)) return;
            transition('cancel');
        });

        on(doc, 'keydown', function (event) {
            if (destroyed || !state.open) return;
            if (event.key === 'Escape') {
                event.preventDefault();
                transition('cancel');
                trigger.focus();
            }
        });

        on(searchInput, 'input', function () {
            transition('search', { query: searchInput.value });
            render();
        });

        on(popover, 'scroll', function (event) { event.stopPropagation(); }, true);
        on(popover, 'wheel', function (event) { event.stopPropagation(); }, { passive: true });

        on(copyBtn, 'click', function (event) {
            event.preventDefault();
            var value = Core.copyValueFor(Core.findOption(optionsById(), state.committed.optionId), state.previewOptionId);
            copyToClipboard(value);
        });

        on(gear, 'click', function () {
            focusPanel = 'parameters';
            openAdvanced = !openAdvanced;
            if (modulePresentation && !state.open) transition('open');
            renderParameters();
        });

        on(win, 'resize', function () { if (!inline && state.open) place(); });
        on(win, 'scroll', function () { if (!inline && state.open) place(); }, true);

        var openAdvanced = false;
        var focusPanel = 'model';

        /* --------------------------------------------------------- 状态转换 */

        function transition(event, payload) {
            var before = state;
            var result = Core.act(state, event, payload);
            state = result.state;
            if (!inline && state.open !== before.open) popover.hidden = !state.open;
            if (result.effects.notifyPreview && typeof config.onPreview === 'function') {
                config.onPreview({ optionId: state.previewOptionId, readOnly: true });
            }
            if (result.effects.rejected && typeof config.onValidationChange === 'function') {
                config.onValidationChange({ optionId: '', rejected: result.effects.rejected });
            }
            if (result.effects.persist) {
                // 只有第三栏提交会走到这里，且一次写完整选择（§5.6）
                var committed = result.effects.committed;
                Promise.resolve()
                    .then(function () {
                        return typeof config.onCommit === 'function'
                            ? config.onCommit({ selection: committed, baseRevision: state.committed.revision, changes: { optionId: committed.optionId, parameters: committed.parameters } })
                            : null;
                    })
                    .then(function () { render(); })
                    .catch(function (error) {
                        state = Object.assign({}, state, { lastError: String(error && error.message || error) });
                        render();
                    });
            }
            if (!inline && state.open) place();
            // 预览变化只更新高亮，不重建列表：重建会销毁当前聚焦元素并触发 blur，
            // 使键盘 focus 预览立即被清掉（A05、§13.4）。
            if (event === 'previewOption' || event === 'clearPreview') {
                paintPreview();
                renderIdentity(Core.projectStages(optionsById(), state));
                return;
            }
            render();
        }

        // 原位切换预览高亮，不替换 DOM
        function paintPreview() {
            var rows = columns.variant.list.querySelectorAll('.model-config-leaf');
            Array.prototype.forEach.call(rows, function (row) {
                row.classList.toggle('is-previewing', text(row.getAttribute('data-option-id')) === text(state.previewOptionId));
            });
        }

        function copyToClipboard(value) {
            if (!value) return;
            var done = function () {
                copyBtn.textContent = '已复制，去粘贴';
                copyBtn.classList.add('is-copied');
                setTimeout(function () { copyBtn.textContent = '复制'; copyBtn.classList.remove('is-copied'); }, 1600);
            };
            if (win.navigator && win.navigator.clipboard && win.navigator.clipboard.writeText) {
                win.navigator.clipboard.writeText(value).then(done).catch(function () { fallbackCopy(value, done); });
            } else {
                fallbackCopy(value, done);
            }
        }

        function fallbackCopy(value, done) {
            var area = el('textarea', 'model-config-copy-area');
            area.value = value;
            root.appendChild(area);
            area.select();
            try { doc.execCommand('copy'); done(); } catch (error) { /* 复制失败不改变选择 */ }
            root.removeChild(area);
        }

        /* ----------------------------------------------------------- 渲染 */

        function render() {
            if (destroyed) return;
            var positions = {};
            Object.keys(columns).forEach(function (key) { positions[key] = columns[key].list.scrollTop; });
            var stagesData = Core.projectStages(optionsById(), state);
            renderTrigger(stagesData);
            renderTags(stagesData);
            renderFamilies(stagesData);
            renderPlatforms(stagesData);
            renderVariants(stagesData);
            renderIdentity(stagesData);
            renderSummary(stagesData);
            renderParameters();
            Object.keys(columns).forEach(function (key) { columns[key].list.scrollTop = positions[key]; });
            if (modulePresentation) {
                stages.hidden = focusPanel === 'parameters';
                panel.hidden = focusPanel === 'model' || panel.hidden;
            }
            // 只有真的搜索且无结果时才显示空状态
            noMatch.hidden = !(text(state.search) && !stagesData.families.length);
        }

        function renderTrigger(stagesData) {
            var option = stagesData.selectedOption;
            var pieces = Core.selectionParts(option);
            if (!pieces.length) pieces.push(language() === 'en' ? 'Choose a model' : '选择模型');
            triggerText.textContent = pieces.join(' · ');
            trigger.title = pieces.join(' · ');
            trigger.classList.toggle('is-invalid', !!state.catalogMissing);
        }

        function renderTags(stagesData) {
            var pool = {};
            var labels = {};
            optionsById().forEach(function (option) {
                (option.capability_tags || []).forEach(function (tag, index) {
                    labels[tag] = language() === 'en' ? (option.capability_tags_en?.[index] || tag) : tag;
                });
            });
            stagesData.families.forEach(function (family) {
                family.tags.forEach(function (tag) { pool[tag] = true; });
            });
            tagRow.replaceChildren();
            Object.keys(pool).slice(0, 8).forEach(function (tag) {
                var chip = el('button', 'model-config-tag', labels[tag] || tag);
                chip.type = 'button';
                chip.classList.toggle('is-on', (state.tags || []).indexOf(tag) !== -1);
                on(chip, 'click', function () { transition('toggleTag', { tag: tag }); render(); });
                tagRow.appendChild(chip);
            });
        }

        function renderFamilies(stagesData) {
            columns.family.list.replaceChildren();
            stagesData.families.forEach(function (family) {
                var row = el('button', 'model-config-option');
                row.type = 'button';
                row.setAttribute('role', 'option');
                row.setAttribute('data-option-id', family.id);
                row.classList.toggle('is-current', family.id === stagesData.draftFamilyId);
                row.appendChild(el('span', 'model-config-option-label', family.label[language()] || family.id));
                row.appendChild(el('span', 'model-config-option-count', String(family.options.length)));
                on(row, 'click', function () { transition('selectFamily', { familyId: family.id }); render(); });
                columns.family.list.appendChild(row);
            });
        }

        function renderPlatforms(stagesData) {
            columns.platform.list.replaceChildren();
            stagesData.platforms.forEach(function (platform) {
                var row = el('button', 'model-config-option');
                row.type = 'button';
                row.setAttribute('role', 'option');
                row.setAttribute('data-platform-key', platform.key);
                row.classList.toggle('is-current', platform.key === stagesData.draftPlatformKey);
                row.appendChild(el('span', 'model-config-option-label', platform.label));
                row.appendChild(el('span', 'model-config-option-count', String(platform.count)));
                on(row, 'click', function () { transition('selectPlatform', { platformKey: platform.key }); render(); });
                columns.platform.list.appendChild(row);
            });
        }

        function renderVariants(stagesData) {
            columns.variant.list.replaceChildren();
            stagesData.variants.forEach(function (item) {
                var option = item.option;
                var row = el('button', 'model-config-option model-config-leaf');
                row.type = 'button';
                row.setAttribute('role', 'option');
                row.setAttribute('data-option-id', option.option_id);
                row.classList.toggle('is-current', option.option_id === state.committed.optionId);
                row.classList.toggle('is-previewing', option.option_id === state.previewOptionId);
                row.classList.toggle('is-blocked', item.status.level === 'blocked');
                row.classList.toggle('is-pending', item.status.level === 'pending');
                row.appendChild(el('span', 'model-config-option-label', option.display_label?.[language()] || item.label));

                var tags = (option.capability_tags || []).slice(0, 4);
                if (tags.length) {
                    var badgeRow = el('span', 'model-config-badges');
                    tags.forEach(function (tag, index) { badgeRow.appendChild(el('span', 'model-config-badge',
                        language() === 'en' ? (option.capability_tags_en?.[index] || tag) : tag)); });
                    row.appendChild(badgeRow);
                }
                if (item.status.level !== 'ready') {
                    var note = item.status.text && (item.status.text.zh || item.status.code);
                    row.appendChild(el('span', 'model-config-option-note', note || ''));
                    row.title = note || '';
                }
                // hover 与键盘 focus 都必须触发同一份只读预览（A04/A05）
                on(row, 'mouseenter', function () { transition('previewOption', { optionId: option.option_id }); });
                on(row, 'focus', function () { transition('previewOption', { optionId: option.option_id }); });
                on(row, 'mouseleave', function () { transition('clearPreview', {}); });
                on(row, 'blur', function () { transition('clearPreview', {}); });
                on(row, 'click', function () {
                    transition('clickVariant', { option: option, parameters: config.modelOnly ? {} : state.committed.parameters });
                });
                columns.variant.list.appendChild(row);
            });
        }

        function renderIdentity(stagesData) {
            var previewOption = state.previewOptionId ? Core.findOption(optionsById(), state.previewOptionId) : null;
            var option = previewOption || stagesData.selectedOption;
            var lines = Core.identifierLines(option);
            idLabel.textContent = previewOption ? '预览接口' : '已选接口';
            idValue.textContent = lines.primary || '—';
            idKind.textContent = option ? (lines.primaryKind || '') : '';
            idRow.classList.toggle('is-previewing', !!previewOption);
            idRow.title = lines.detail.map(function (item) { return item.label + '：' + item.value; }).join('\n');
        }

        function renderSummary(stagesData) {
            var option = stagesData.selectedOption || Core.findOption(optionsById(), state.committed.optionId);
            var parts = Core.summaryParts(state.committed.parameters, profileFor(option));
            summaryText.textContent = parts.length ? parts.join(' · ') : '参数';
            summary.title = summaryText.textContent;
        }

        // 参数面板：常用直接铺开，高级收进齿轮；无高级字段时不显示齿轮（C14）
        function renderParameters() {
            if (config.modelOnly) { panel.hidden = true; return; }
            var scrollTop = panel.scrollTop;
            var option = Core.findOption(optionsById(), state.committed.optionId);
            var profile = profileFor(option);
            var specs = (profile && profile.parameters) || {};
            var keys = Object.keys(specs).filter(function (key) { return !specs[key].ui_hidden; });
            var advancedKeys = keys.filter(function (key) {
                var spec = specs[key];
                var uiLevel = (spec.ui && spec.ui.level) || (spec.level === 'advanced' ? 'advanced' : 'common');
                return uiLevel === 'advanced';
            });
            var commonKeys = keys.filter(function (key) { return advancedKeys.indexOf(key) === -1; });

            gear.hidden = advancedKeys.length === 0;
            panel.hidden = !keys.length;
            panel.replaceChildren();
            if (!keys.length) return;

            var shown = openAdvanced ? advancedKeys : commonKeys;
            var selected = state.committed.parameters || {};
            var english = global.StudioI18n?.lang?.() === 'en' || String(doc.documentElement.lang || '').toLowerCase().startsWith('en');

            function changeValue(key, value) {
                var next = {};
                next[key] = value;
                transition('updateParameters', { parameters: next });
                if (typeof config.onParametersChange === 'function') {
                    config.onParametersChange({ parameters: Object.assign({}, state.committed.parameters) });
                }
            }

            shown.forEach(function (key) {
                var spec = specs[key] || {};
                var group = el('div', 'model-config-param');
                group.setAttribute('data-param-key', key);
                group.appendChild(el('div', 'model-config-param-title', spec.label || spec.title || key));
                var row = el('div', 'model-config-param-options');
                var values = parameterOptions(spec);
                values.forEach(function (value) {
                    var label = spec.option_labels && spec.option_labels[String(value)];
                    if (spec.type === 'boolean') label = value ? (english ? 'Yes' : '是') : (english ? 'No' : '否');
                    var chip = el('button', 'model-config-param-option', label || String(value));
                    chip.type = 'button';
                    chip.classList.toggle('is-on', String(selected[key]) === String(value));
                    on(chip, 'click', function () {
                        changeValue(key, value);
                    });
                    row.appendChild(chip);
                });
                if (!values.length && spec.type === 'enum') {
                    row.appendChild(el('span', 'model-config-param-unavailable', english
                        ? 'Allowed values are unverified. Refresh the platform model information.'
                        : '可选值尚未核实，请更新平台模型资料。'));
                } else if (!values.length) {
                    var numeric = spec.type === 'integer' || spec.type === 'number';
                    var input = el('input', 'model-config-param-input');
                    input.type = numeric ? 'number' : 'text';
                    input.setAttribute('aria-label', spec.label || spec.title || key);
                    input.value = selected[key] != null ? selected[key] : (spec.default != null ? spec.default : '');
                    if (numeric) {
                        if (spec.min != null) input.min = spec.min;
                        if (spec.max != null) input.max = spec.max;
                        input.step = spec.step || (spec.type === 'integer' ? 1 : 'any');
                        if (spec.min != null && spec.max != null && Number(spec.max) > Number(spec.min)) {
                            var slider = el('input', 'model-config-param-range');
                            slider.type = 'range';
                            slider.min = input.min;
                            slider.max = input.max;
                            slider.step = input.step;
                            slider.value = input.value;
                            slider.setAttribute('aria-label', input.getAttribute('aria-label'));
                            on(slider, 'input', function () { input.value = slider.value; });
                            on(slider, 'change', function () { changeValue(key, Number(slider.value)); });
                            row.appendChild(slider);
                        }
                    }
                    on(input, 'change', function () {
                        changeValue(key, numeric ? (input.value === '' ? null : Number(input.value)) : input.value);
                    });
                    row.appendChild(input);
                }
                group.appendChild(row);
                panel.appendChild(group);
            });
            panel.classList.toggle('is-advanced', openAdvanced);
            panel.scrollTop = scrollTop;
        }

        function parameterOptions(spec) {
            if (Array.isArray(spec.options) && spec.options.length) return spec.options;
            if (spec.type === 'boolean') return [true, false];
            return [];
        }

        /* ------------------------------------------------------------ 定位 */

        // 下方优先、空间不足翻到上方，左右与上下夹取到视口内（§13.3）
        function place() {
            if (modulePresentation || inline) return;
            var hostRect = trigger.getBoundingClientRect();
            var viewportWidth = doc.documentElement.clientWidth;
            var viewportHeight = doc.documentElement.clientHeight;
            var maxHeight = Math.min(560, viewportHeight - 32);
            popover.style.maxHeight = maxHeight + 'px';

            var popRect = popover.getBoundingClientRect();
            var top = hostRect.bottom + 6;
            if (top + popRect.height > viewportHeight - 8) {
                var flipped = hostRect.top - popRect.height - 6;
                top = flipped >= 8 ? flipped : Math.max(8, viewportHeight - 8 - popRect.height);
            }
            var left = hostRect.left;
            if (left + popRect.width > viewportWidth - 8) left = viewportWidth - 8 - popRect.width;
            popover.style.top = Math.max(8, top) + 'px';
            popover.style.left = Math.max(8, left) + 'px';
        }

        /* --------------------------------------------------------- 生命周期 */

        indexProfiles();
        render();

        var instance = {
            id: instanceId,
            element: root,
            popover: popover,
            getState: function () { return state; },
            updateCatalog: function (nextCatalog) {
                catalog = nextCatalog || { options: [] };
                indexProfiles();
                transition('catalogUpdated', { options: optionsById() });
                render();
            },
            updateContext: function (nextContext) {
                context = nextContext || {};
                render();
            },
            updateSelection: function (nextSelection) {
                state = Object.assign({}, state, { committed: Core.normalizeSelection(nextSelection), draft: { familyId: '', platformKey: '', optionId: '' } });
                render();
            },
            open: function () {
                if (inline) { state = Object.assign({}, state, { open: true }); render(); return; }
                transition('open');
            },
            close: function () { transition('cancel'); },
            destroy: function () {
                if (destroyed) return;
                destroyed = true;
                listeners.forEach(function (off) { off(); });
                listeners = [];
                if (popover.parentNode) popover.parentNode.removeChild(popover);
                if (root.parentNode) root.parentNode.removeChild(root);
            }
        };
        return instance;
    }

    global.mountModelConfigControl = mountModelConfigControl;
    if (typeof module !== 'undefined' && module.exports) module.exports = { mountModelConfigControl: mountModelConfigControl };
})(typeof window !== 'undefined' ? window : globalThis);
