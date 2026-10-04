(function () {
    'use strict';

    const SLOTS = ['text', 'image', 'video', 'audio', 'music', 'voice'];
    const NODE_TYPES = {
        text: 'text_generation',
        image: 'image_generation',
        video: 'video_generation',
        audio: 'audio_generation',
        music: 'music_generation',
        voice: 'audio_generation'
    };
    const SLOT_LABELS = {
        text: 'hypit.slotText',
        image: 'hypit.slotImage',
        video: 'hypit.slotVideo',
        audio: 'hypit.slotAudio',
        music: 'hypit.slotMusic',
        voice: 'hypit.slotVoice'
    };
    const API = '/api/studio/hypit/models';
    // 画布模型选择器目前不提供这两个平台的生成节点；Hypit 默认设置必须与画布候选保持同一白名单。
    const CANVAS_EXCLUDED_PROVIDERS = new Set(['modelscope', 'volcengine']);
    const settingsURL = `${API}/settings`;
    const root = document.getElementById('providerSettingsView');
    const layout = document.querySelector('.layout');
    const block = document.getElementById('hypitSettingsBlock');
    const nav = document.getElementById('hypitSettingsNav');
    const canvasModelSettingsBlock = document.getElementById('canvasModelSettingsBlock');
    const slotsEl = document.getElementById('hypitSlots');
    const statusEl = document.getElementById('hypitSettingsStatus');
    const AUTOSAVE_DELAY = 320;
    const state = {
        catalog: { providers: [] },
        capabilities: [],
        unsupported: [],
        settings: { defaults: {} },
        loaded: false,
        loading: false,
        saving: false,
        saveTimer: null,
        savePromise: null,
        draftVersion: 0,
        savedVersion: 0,
        dirty: false
    };

    const translations = {
        zh: {
            'hypit.navTitle': 'Hypit 设置',
            'hypit.navLabel': 'Hypit',
            'hypit.navMeta': '生成模型',
            'hypit.title': 'Hypit 设置',
            'hypit.description': '选择各类生成任务使用的模型；参数由每次复刻任务按模型要求配置。',
            'hypit.reload': '重新读取',
            'hypit.slotText': '文本生成',
            'hypit.slotImage': '图片生成',
            'hypit.slotVideo': '视频生成',
            'hypit.slotAudio': '音效生成',
            'hypit.slotMusic': '音乐生成',
            'hypit.slotVoice': '语音生成',
            'hypit.family': '模型',
            'hypit.variant': '模式',
            'hypit.provider': '平台',
            'hypit.parameters': '参数',
            'hypit.noModels': '暂无可用模型，请先配置对应平台。',
            'hypit.unavailable': '未接入',
            'hypit.selectedUnavailable': '已选模型暂不可用，请检查平台或重新选择。',
            'hypit.loading': '正在读取 Hypit 模型设置…',
            'hypit.saving': '正在保存…',
            'hypit.saved': '已保存',
            'hypit.loaded': '',
            'hypit.loadError': '读取 Hypit 设置失败：{message}',
            'hypit.saveError': '保存 Hypit 设置失败：{message}',
        },
        en: {
            'hypit.navTitle': 'Hypit settings',
            'hypit.navLabel': 'Hypit',
            'hypit.navMeta': 'Generation models',
            'hypit.title': 'Hypit settings',
            'hypit.description': 'Choose generation models. Each recreation task supplies parameters supported by its model.',
            'hypit.reload': 'Reload',
            'hypit.slotText': 'Text generation',
            'hypit.slotImage': 'Image generation',
            'hypit.slotVideo': 'Video generation',
            'hypit.slotAudio': 'Sound effects',
            'hypit.slotMusic': 'Music generation',
            'hypit.slotVoice': 'Speech generation',
            'hypit.family': 'Model',
            'hypit.variant': 'Variant',
            'hypit.provider': 'Platform',
            'hypit.parameters': 'Parameters',
            'hypit.noModels': 'No models available. Configure a platform first.',
            'hypit.unavailable': 'Not implemented',
            'hypit.selectedUnavailable': 'The selected model is unavailable. Check the platform or choose another.',
            'hypit.loading': 'Loading Hypit model settings…',
            'hypit.saving': 'Saving…',
            'hypit.saved': 'Saved',
            'hypit.loaded': '',
            'hypit.loadError': 'Could not load Hypit settings: {message}',
            'hypit.saveError': 'Could not save Hypit settings: {message}',
        }
    };

    function registerTranslations() {
        if (window.StudioI18n) window.StudioI18n.register(translations);
    }

    function t(key, values) {
        if (translations[currentLang()][key] === '') return '';
        const base = window.StudioI18n ? window.StudioI18n.t(key) : (translations.zh[key] || key);
        return String(base).replace(/\{(\w+)\}/g, (_, name) => values && values[name] !== undefined ? String(values[name]) : `{${name}}`);
    }

    function currentLang() {
        return window.StudioI18n?.lang?.() === 'en' ? 'en' : 'zh';
    }

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>'"]/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
        }[char]));
    }

    function setStatus(message, stateName = '') {
        if (!statusEl) return;
        statusEl.textContent = message || '';
        if (stateName) statusEl.dataset.state = stateName;
        else delete statusEl.dataset.state;
    }

    function refreshIcons() {
        if (typeof window.refreshIcons === 'function') window.refreshIcons();
        else if (window.lucide?.createIcons) window.lucide.createIcons();
    }

    function syncEditorHeader() {
        const title = document.getElementById('editorTitle');
        if (title && layout?.classList.contains('hypit-settings-mode')) title.textContent = t('hypit.title');
    }

    function emptySlot() {
        return { provider: '', model: '', region: '', parameters: {} };
    }

    function normalizeRegion(value) {
        const region = String(value || '').trim().toLowerCase();
        return region === 'global' || region === 'cn' ? region : '';
    }

    function regionLabel(region) {
        return normalizeRegion(region) === 'cn' ? 'CN' : 'AI';
    }

    function selectionKey(model) {
        return `${String(model?.provider_id || '')}::${normalizeRegion(model?.region)}`;
    }

    function selectionKeyForValues(provider, region) {
        return `${String(provider || '')}::${normalizeRegion(region)}`;
    }

    function modelLabel(model) {
        const provider = String(model?.provider_id || '');
        const name = String(model?.provider_name || provider);
        return provider === 'runninghub' && normalizeRegion(model?.region)
            ? `${name} · ${regionLabel(model.region)}`
            : name;
    }

    function ensureDefaults() {
        if (!state.settings || typeof state.settings !== 'object') state.settings = { defaults: {} };
        if (!state.settings.defaults || typeof state.settings.defaults !== 'object') state.settings.defaults = {};
        SLOTS.forEach(slot => {
            const value = state.settings.defaults[slot];
            if (!value || typeof value !== 'object') state.settings.defaults[slot] = emptySlot();
            state.settings.defaults[slot].region = normalizeRegion(state.settings.defaults[slot].region);
            if (!state.settings.defaults[slot].parameters || typeof state.settings.defaults[slot].parameters !== 'object') {
                state.settings.defaults[slot].parameters = {};
            }
        });
    }

    function capabilityFor(slot) {
        return state.capabilities.find(item => item.slot === slot) || null;
    }

    function expandModel(model, provider) {
        const providerId = String(model?.provider_id || provider?.id || '');
        const providerName = String(model?.provider_name || provider?.name || providerId);
        if (providerId !== 'runninghub') {
            return [{ ...model, provider_id: providerId, provider_name: providerName, region: normalizeRegion(model?.region) }];
        }
        const modelRegions = Array.isArray(model?.regions)
            ? model.regions.map(normalizeRegion).filter(Boolean)
            : [];
        const providerRegions = Array.isArray(provider?.regions)
            ? provider.regions.filter(item => item?.enabled === true).map(item => normalizeRegion(item.region)).filter(Boolean)
            : [];
        const regions = [...new Set(modelRegions.length ? modelRegions : providerRegions)];
        if (!regions.length) {
            return [{ ...model, provider_id: providerId, provider_name: providerName, region: normalizeRegion(model?.region) }];
        }
        return regions.map(region => ({
            ...model,
            ...(model?.region_profiles?.[region] || {}),
            provider_id: providerId,
            provider_name: providerName,
            region
        }));
    }

    // 槽位候选优先取自目录选项投影（§9.4、§10.5）：与画布共用同一份可执行选项，
    // 不再在这里各写一套 strict/runnable/节点类型规则，避免两处规则慢慢漂移。
    function slotOptions(slot) {
        const slotCatalog = state.catalog?.slot_options;
        const projected = slotCatalog && Array.isArray(slotCatalog[slot]) ? slotCatalog[slot]
            : (Array.isArray(state.catalog?.options) ? state.catalog.options : []);
        if (slotCatalog && !projected.length) return [];
        if (!projected.length) {
            // 投影缺失会安静地退回旧推导，曾经导致“以为接上了其实没生效”。
            // 这里留下可观测痕迹，便于在页面控制台与状态里发现。
            if (!state.projectionWarningShown) {
                state.projectionWarningShown = true;
                state.projectionAvailable = false;
                console.warn('[hypit-settings] 目录缺少 options 投影，槽位候选回退到旧推导');
            }
            return null;
        }
        state.projectionAvailable = true;
        const nodeType = NODE_TYPES[slot];
        const scoped = projected.filter(option => option.node_type === nodeType
            && option.runnable === true
            && option.selectable !== false
            && !CANVAS_EXCLUDED_PROVIDERS.has(String(option.connection_id || '').trim().toLowerCase()));
        if (!scoped.length) return [];
        return scoped.map(option => ({
            ...option,
            option_id: option.option_id,
            provider_id: option.connection_id,
            provider_name: option.platform_label || option.capability_provider_id || option.connection_id,
            model_id: option.catalog_model_id,
            model: option.catalog_model_id,
            node_type: option.node_type,
            family_id: option.canonical_family_id,
            family_name: (option.canonical_family_label || {}).zh || option.canonical_family_id,
            region: normalizeRegion(option.region_id),
            runnable: option.runnable,
            readiness: option.readiness,
            validation_mode: option.validation_mode,
            parameters: option.parameters || {},
            inputs: option.inputs || {},
            capability_tags: option.capability_tags || []
        }));
    }

    function enabledModels(slot) {
        const projected = slotOptions(slot);
        if (projected) return projected;
        const capability = capabilityFor(slot);
        if (Array.isArray(capability?.models)) {
            return capability.models
                .filter(model => model && model.model_id && model.runnable === true && model.validation_mode === 'strict'
                    && !CANVAS_EXCLUDED_PROVIDERS.has(String(model.provider_id || '').trim().toLowerCase()))
                .flatMap(model => expandModel(model, (state.catalog.providers || []).find(provider => provider.id === model.provider_id)));
        }
        const nodeType = NODE_TYPES[slot];
        return (state.catalog.providers || []).flatMap(provider => (provider.models || [])
            .filter(model => model.node_type === nodeType && model.runnable === true && model.validation_mode === 'strict'
                && !CANVAS_EXCLUDED_PROVIDERS.has(String(provider.id || '').trim().toLowerCase()))
            .flatMap(model => expandModel({ ...model, provider_id: provider.id, provider_name: provider.name || provider.id }, provider)));
    }

    function modelForSelection(models, current) {
        const exact = models.find(model => model.provider_id === current.provider
            && model.model_id === current.model
            && normalizeRegion(model.region) === normalizeRegion(current.region));
        if (exact || current.region) return exact || null;
        const compatible = models.filter(model => model.provider_id === current.provider && model.model_id === current.model);
        return compatible.length === 1 ? compatible[0] : null;
    }

    function modelKey(model) {
        return `${String(model?.provider_id || '')}::${String(model?.model_id || '')}::${normalizeRegion(model?.region)}`;
    }

    function exactProfile(slot, providerId, modelId) {
        const direct = enabledModels(slot).find(item => item.provider_id === providerId && item.model_id === modelId);
        if (direct) return direct;
        const helper = window.SmartModelCapabilities;
        return helper?.findModel?.(state.catalog, providerId, modelId, NODE_TYPES[slot]) || null;
    }

    function candidateFamilies(slot) {
        const models = enabledModels(slot);
        const allowed = new Set(models.map(modelKey));
        const output = [];
        models.forEach(model => {
            const familyId = String(model.family_id || model.model_id);
            let family = output.find(item => item.family_id === familyId);
            if (!family) {
                family = {
                    family_id: familyId,
                    family_name: model.family_name || model.display_name || familyId,
                    provider_ids: [],
                    providers: [],
                    variants: []
                };
                output.push(family);
            }
            if (!family.provider_ids.includes(model.provider_id)) family.provider_ids.push(model.provider_id);
            const providerKey = selectionKey(model);
            if (!family.providers.some(item => `${String(item.id || '')}::${normalizeRegion(item.region)}` === providerKey)) {
                family.providers.push({ id: model.provider_id, name: modelLabel(model), region: model.region });
            }
            if (allowed.has(modelKey(model)) && !family.variants.some(item => modelKey(item) === modelKey(model))) {
                family.variants.push(model);
            }
        });
        return output.filter(family => family.variants.length);
    }

    function familyLabel(family) {
        const name = currentLang() === 'en'
            ? (family.family_name_en || family.display_name_en || family.family_name || family.display_name)
            : (family.family_name || family.display_name || family.family_name_en || family.display_name_en);
        return String(name || family.family_id || '-');
    }

    function variantLabel(model) {
        const name = currentLang() === 'en'
            ? (model.variant_name_en || model.variant_name || model.display_name_en || model.display_name)
            : (model.variant_name || model.display_name || model.variant_name_en || model.display_name_en);
        const modelId = String(model.model_id || model.variant_id || '').trim();
        const display = String(name || '').trim();
        return display && display !== modelId ? `${display} · ${modelId}` : (modelId || display || '-');
    }

    function statusFor(slot, model) {
        if (!model) return { text: t('hypit.unavailable'), className: 'is-warning' };
        if (model.runnable === false || (model.readiness && model.readiness !== 'ready') || model.validation_mode !== 'strict') {
            return { text: model.readiness || t('hypit.unavailable'), className: 'is-warning' };
        }
        return { text: currentLang() === 'en' ? 'Ready' : '可运行', className: 'is-ready' };
    }

    function optionsHtml(items, selected, labeler, valueKey) {
        return items.map(item => {
            const value = String(item[valueKey] ?? '');
            return `<option value="${escapeHtml(value)}"${value === String(selected ?? '') ? ' selected' : ''}>${escapeHtml(labeler(item))}</option>`;
        }).join('');
    }

    function parameterInput(slot, key, spec, value) {
        const type = String(spec?.type || '').toLowerCase();
        const labels = {duration:['时长','Duration'], resolution:['分辨率','Resolution'],aspect_ratio:['画幅','Ratio'],quality:['画质','Quality'],voice_id:['音色','Voice'],speed:['语速','Speed'],volume:['音量','Volume'],pitch:['音高','Pitch']};
        const label = labels[key]?.[currentLang() === 'en' ? 1 : 0] || spec?.label || key;
        let choices = Array.isArray(spec?.options || spec?.values) ? spec.options || spec.values : null;
        if(type === 'boolean' || type === 'bool') choices=[true,false];
        const lower=spec?.min ?? spec?.minimum, upper=spec?.max ?? spec?.maximum;
        if(!choices && type==='integer' && Number.isInteger(lower) && Number.isInteger(upper) && upper-lower<=100) choices=Array.from({length:upper-lower+1},(_,i)=>lower+i);
        if(choices) return `<div class="hypit-parameter-field"><span class="hypit-parameter-label">${escapeHtml(label)}</span><div class="hypit-choices">${[undefined,...choices].map(option=>`<button type="button" class="${option===value?'active':''}" data-hypit-choice="${escapeHtml(key)}" data-hypit-slot="${escapeHtml(slot)}" data-value="${escapeHtml(option===undefined?'':JSON.stringify(option))}">${escapeHtml(option===undefined?(currentLang()==='en'?'Default':'默认'):option===true?(currentLang()==='en'?'Yes':'是'):option===false?(currentLang()==='en'?'No':'否'):option)}</button>`).join('')}</div></div>`;
        if (type === 'boolean' || type === 'bool') {
            return `<label class="hypit-parameter-checkbox"><input type="checkbox" data-hypit-parameter="${escapeHtml(key)}" data-hypit-slot="${escapeHtml(slot)}"${value === true ? ' checked' : ''}><span>${escapeHtml(label)}</span></label>`;
        }
        if (type === 'enum' && Array.isArray(spec?.options || spec?.values)) {
            const values = spec.options || spec.values;
            return `<label class="hypit-parameter-field"><span class="hypit-parameter-label">${escapeHtml(label)}</span><select data-hypit-parameter="${escapeHtml(key)}" data-hypit-slot="${escapeHtml(slot)}">${values.map(option => `<option value="${escapeHtml(option)}"${String(option) === String(value ?? '') ? ' selected' : ''}>${escapeHtml(option)}</option>`).join('')}</select></label>`;
        }
        const numeric = type === 'integer' || type === 'number' || type === 'float';
        const min = spec?.min ?? spec?.minimum;
        const max = spec?.max ?? spec?.maximum;
        return `<label class="hypit-parameter-field"><span class="hypit-parameter-label">${escapeHtml(label)}</span><input type="${numeric ? 'number' : 'text'}"${numeric && type === 'integer' ? ' step="1"' : ''}${min !== undefined ? ` min="${escapeHtml(min)}"` : ''}${max !== undefined ? ` max="${escapeHtml(max)}"` : ''} value="${escapeHtml(value ?? '')}" data-hypit-parameter="${escapeHtml(key)}" data-hypit-slot="${escapeHtml(slot)}"></label>`;
    }

    function renderParameters(slot, profile) {
        const schema = profile?.parameters && typeof profile.parameters === 'object' ? profile.parameters : {};
        const keys = Object.keys(schema);
        if (!keys.length) return '';
        const values = state.settings.defaults[slot].parameters || {};
        return `<div class="hypit-parameters"><div class="hypit-parameters-title">${escapeHtml(t('hypit.parameters'))}</div>${keys.map(key => parameterInput(slot, key, schema[key], values[key])).join('')}</div>`;
    }

    function syncSelection(slot, card) {
        const familySelect = card.querySelector('[data-hypit-family]');
        const variantSelect = card.querySelector('[data-hypit-variant]');
        const providerSelect = card.querySelector('[data-hypit-provider]');
        const familyId = familySelect?.value || '';
        const family = candidateFamilies(slot).find(item => String(item.family_id) === familyId);
        const variants = family?.variants || [];
        const selectedVariants = variants.filter(item => String(item.model_id) === String(variantSelect?.value || ''));
        const current = state.settings.defaults[slot];
        const selectedVariant = selectedVariants.find(item => normalizeRegion(item.region) === normalizeRegion(current.region)) || selectedVariants[0] || variants[0];
        const providerKey = providerSelect?.value || selectionKey(selectedVariant);
        const model = variants.find(item => selectionKey(item) === providerKey && item.model_id === selectedVariant?.model_id) || selectedVariant;
        if (!model) return;
        const helper = window.SmartModelCapabilities;
        const retained = current.provider === model.provider_id && current.model === model.model_id && normalizeRegion(current.region) === normalizeRegion(model.region)
            ? current.parameters || {}
            : {};
        const parameters = helper?.effectiveParameters?.(model, retained) || retained;
        state.settings.defaults[slot] = {
            provider: model.provider_id || '',
            model: model.model_id || '',
            region: normalizeRegion(model.region),
            parameters
        };
    }

    function variantOptions(variants, selected) {
        const seen = new Set();
        return variants.filter(model => {
            const key = String(model.model_id || model.variant_id || '');
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        }).map(model => `<option value="${escapeHtml(String(model.model_id || model.variant_id || ''))}"${String(model.model_id || model.variant_id || '') === String(selected || '') ? ' selected' : ''}>${escapeHtml(variantLabel(model))}</option>`).join('');
    }

    function renderSlot(slot) {
        const capability = capabilityFor(slot);
        const models = enabledModels(slot);
        const families = candidateFamilies(slot);
        const current = state.settings.defaults[slot] || emptySlot();
        const selectedModel = modelForSelection(models, current);
        const selectedFamily = families.find(family => family.variants.some(model => modelKey(model) === modelKey(selectedModel)));
        const variants = selectedFamily?.variants || [];
        const selectedVariant = variants.find(model => modelKey(model) === modelKey(selectedModel)) || variants[0];
        const providers = variants.filter((item, index, list) => list.findIndex(other => selectionKey(other) === selectionKey(item)) === index);
        const selectedProvider = providers.find(item => selectionKey(item) === selectionKey(selectedModel)) || selectedVariant;
        const activeModel = variants.find(item => selectionKey(item) === selectionKey(selectedProvider) && item.model_id === selectedVariant?.model_id) || selectedVariant;
        const status = current.model ? statusFor(slot, selectedModel) : {text:currentLang() === 'en' ? 'Not set' : '未设置',className:''};
        const unavailable = Boolean(current.provider && current.model && !selectedModel);
        const familyOptions = `<option value="">${currentLang() === 'en' ? 'Choose' : '选择'}</option>` + families.map(item => `<option value="${escapeHtml(item.family_id)}"${item === selectedFamily ? ' selected' : ''}>${escapeHtml(familyLabel(item))}</option>`).join('');
        const variantOptionsHtml = variantOptions(variants, selectedVariant?.model_id);
        const providerOptions = providers.map(item => {
            const value = selectionKey(item);
            return `<option value="${escapeHtml(value)}"${value === selectionKey(selectedProvider) ? ' selected' : ''}>${escapeHtml(modelLabel(item))}</option>`;
        }).join('');
        const title = t(SLOT_LABELS[slot]);
        const providerName = current.provider === 'ai-money' ? 'laohu' : current.provider;
        const modelNote = unavailable ? `<div class="hypit-slot-description">${escapeHtml(t('hypit.selectedUnavailable'))}<br><code>${escapeHtml(providerName)} / ${escapeHtml(current.model)}${current.region ? ` · ${escapeHtml(regionLabel(current.region))}` : ''}</code></div>` : '';
        if (!models.length || !families.length) {
            return `<section class="hypit-slot-card is-disabled" data-hypit-slot-card="${escapeHtml(slot)}"><div class="hypit-slot-head"><div><div class="hypit-slot-title">${escapeHtml(title)}</div></div><span class="hypit-slot-status is-warning">${escapeHtml(t('hypit.unavailable'))}</span></div><div class="hypit-empty">${escapeHtml(t('hypit.noModels'))}${modelNote}</div></section>`;
        }
        const fallbackControls = `<div class="hypit-model-config-fallback" data-model-config-slot="${escapeHtml(slot)}"><label><span>${escapeHtml(currentLang() === 'en' ? 'Model' : '模型')}</span><select data-hypit-slot="${escapeHtml(slot)}" data-hypit-family="${escapeHtml(slot)}">${familyOptions}</select></label><label><span>${escapeHtml(currentLang() === 'en' ? 'Platform' : '平台')}</span><select data-hypit-slot="${escapeHtml(slot)}" data-hypit-provider="${escapeHtml(slot)}">${providerOptions}</select></label><label><span>${escapeHtml(currentLang() === 'en' ? 'Run mode' : '运行模式')}</span><select data-hypit-slot="${escapeHtml(slot)}" data-hypit-variant="${escapeHtml(slot)}">${variantOptionsHtml}</select></label></div>`;
        // 公共控件自身包含参数面板；旧的槽位级参数渲染只在公共控件尚未加载时保留，
        // 避免同一组分辨率、画幅、数量在卡片里出现两次。
        const legacyParameters = '';
        return `<section class="hypit-slot-card" data-hypit-slot-card="${escapeHtml(slot)}"><div class="hypit-slot-head"><div><div class="hypit-slot-title">${escapeHtml(title)}</div></div><span class="hypit-slot-status ${status.className}">${escapeHtml(status.text)}</span></div><div class="hypit-model-config" data-model-config-slot="${escapeHtml(slot)}">${fallbackControls}</div>${modelNote}${legacyParameters}</section>`;
    }

    // Hypit 槽位使用内联公共控件（§16 P6 第 3 项、§9.4）：
    // 与画布共用同一套三栏选择与参数面板，不维护第二套模型下拉。
    let slotControls = [];

    function destroySlotControls() {
        slotControls.forEach(instance => { try { instance.destroy(); } catch (_) {} });
        slotControls = [];
    }

    function optionIdForSlot(slot, model, current) {
        const models = enabledModels(slot);
        const exact = models.find(item => item.provider_id === current.provider
            && item.model_id === current.model
            && normalizeRegion(item.region) === normalizeRegion(current.region));
        if (exact?.option_id) return exact.option_id;
        const sameModel = models.filter(item => item.provider_id === current.provider && item.model_id === current.model);
        if (sameModel.length === 1 && sameModel[0].option_id) return sameModel[0].option_id;
        return '';
    }

    function slotOptionsForControl(slot) {
        return enabledModels(slot).map(model => ({
            ...model,
            option_id: model.option_id || '',
            node_type: NODE_TYPES[slot],
            operation: model.operation || '',
            connection_id: model.provider_id,
            capability_provider_id: model.provider_id,
            platform_label: model.provider_name || model.provider_id,
            region_id: normalizeRegion(model.region),
            catalog_model_id: model.model_id,
            canonical_family_id: model.family_id || model.model_id,
            canonical_family_label: {
                zh: model.family_name || model.family_id || model.model_id,
                en: model.canonical_family_label?.en || model.family_name_en || model.family_name || model.model_id
            },
            readiness: model.readiness || 'ready',
            runnable: model.runnable !== false,
            selectable: true,
            capability_tags: model.capability_tags || [],
            parameters: model.parameters || {},
            inputs: model.inputs || {}
        })).filter(option => option.option_id);
    }

    function mountSlotControls() {
        destroySlotControls();
        if (!slotsEl || !window.mountModelConfigControl) return;
        SLOTS.forEach(slot => {
            const host = slotsEl.querySelector(`[data-model-config-slot="${slot}"]`);
            if (!host) return;
            const options = slotOptionsForControl(slot);
            if (!options.length) return;
            // 挂载公共控件前清空兼容下拉，避免两套选择器重叠并拦截点击。
            host.replaceChildren();
            const current = state.settings.defaults[slot] || emptySlot();
            const instance = window.mountModelConfigControl(host, {
                context: { host: 'module-settings', moduleId: 'hypit', slotId: slot, phase: 'template' },
                catalog: { options, profiles: [] },
                selection: { optionId: optionIdForSlot(slot, options[0], current), parameters: current.parameters || {} },
                presentation: 'module',
                modelOnly: true,
                onCommit: payload => {
                    const picked = options.find(option => option.option_id === payload.selection.optionId);
                    if (!picked) return Promise.reject(new Error('选择不属于当前槽位'));
                    state.settings.defaults[slot] = {
                        provider: picked.connection_id || '',
                        model: picked.catalog_model_id || '',
                        region: normalizeRegion(picked.region_id),
                        parameters: {}
                    };
                    const card = host.closest('.hypit-slot-card');
                    const status = card?.querySelector('.hypit-slot-status');
                    if (status) { status.textContent = currentLang() === 'en' ? 'Ready' : '可运行'; status.className = 'hypit-slot-status is-ready'; }
                    card?.querySelector('.hypit-slot-description')?.remove();
                    markDirty();
                    return Promise.resolve();
                },
                onParametersChange: payload => {
                    const latest = state.settings.defaults[slot] || emptySlot();
                    state.settings.defaults[slot] = {
                        ...latest,
                        parameters: Object.assign({}, payload?.parameters || {})
                    };
                    markDirty();
                }
            });
            if (instance) slotControls.push(instance);
        });
    }

    function render() {
        ensureDefaults();
        if (slotsEl) {
            slotsEl.innerHTML = SLOTS.map(renderSlot).join('');
            mountSlotControls();
        }
        refreshIcons();
    }

    async function responseJSON(response) {
        let body = {};
        try { body = await response.json(); } catch (_) {}
        if (!response.ok) throw new Error(body?.detail || body?.error || `HTTP ${response.status}`);
        return body;
    }

    function clone(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function markDirty() {
        state.draftVersion += 1;
        state.dirty = true;
        scheduleAutosave();
    }

    function scheduleAutosave(delay = AUTOSAVE_DELAY) {
        if (state.saveTimer) clearTimeout(state.saveTimer);
        state.saveTimer = setTimeout(() => {
            state.saveTimer = null;
            save();
        }, delay);
    }

    async function load() {
        if (state.loading) return;
        state.loading = true;
        setStatus(t('hypit.loading'));
        try {
            const [capabilityResponse, settingsResponse, catalogResponse] = await Promise.all([
                fetch(`${API}/capabilities`),
                fetch(settingsURL),
                // 统一可执行选项投影（§9.4）：槽位候选与画布共用同一份，不在这里重算规则。
                fetch('/api/model-capabilities', { cache:'no-store' })
            ]);
            const capabilities = await responseJSON(capabilityResponse);
            state.settings = await responseJSON(settingsResponse);
            const catalogOptions = await responseJSON(catalogResponse);
            state.catalog = {
                ...capabilities,
                options: Array.isArray(catalogOptions?.options) ? catalogOptions.options : [],
                catalog_revision: catalogOptions?.catalog_revision || ''
            };
            state.capabilities = Array.isArray(capabilities.supported_capabilities) ? capabilities.supported_capabilities : [];
            state.unsupported = Array.isArray(capabilities.unsupported_capabilities) ? capabilities.unsupported_capabilities : [];
            state.loaded = true;
            render();
            setStatus(t('hypit.loaded'), 'success');
        } catch (error) {
            setStatus(t('hypit.loadError', { message: error?.message || error }), 'error');
            render();
        } finally {
            state.loading = false;
        }
    }

    async function save() {
        if (state.savePromise) return state.savePromise;
        ensureDefaults();
        const snapshot = {
            defaults: clone(state.settings.defaults),
            expectedRevision: state.settings.revision || 1,
            draftVersion: state.draftVersion
        };
        state.saving = true;
        setStatus(t('hypit.saving'));
        state.savePromise = (async () => {
            try {
                const response = await fetch(settingsURL, {
                    method: 'PUT',
                    headers: { 'content-type': 'application/json' },
                    body: JSON.stringify({
                        defaults: snapshot.defaults,
                        parameter_mode: 'per_request',
                        expected_revision: snapshot.expectedRevision
                    })
                });
                const saved = await responseJSON(response);
                const localDefaults = state.settings.defaults;
                const changedDuringRequest = state.draftVersion !== snapshot.draftVersion;
                state.settings = {
                    ...saved,
                    defaults: changedDuringRequest ? localDefaults : saved.defaults
                };
                ensureDefaults();
                if (!changedDuringRequest) {
                    state.dirty = false;
                    state.savedVersion = snapshot.draftVersion;
                    setStatus(t('hypit.saved'), 'success');
                } else {
                    // 响应只确认了旧快照；最新草稿仍在队列中，不能提前显示已保存。
                    state.dirty = true;
                    setStatus(t('hypit.saving'));
                }
            } catch (error) {
                // 失败时保留本地草稿和修订号，避免错误响应抹掉用户输入或伪装成成功。
                state.dirty = true;
                setStatus(t('hypit.saveError', { message: error?.message || error }), 'error');
            } finally {
                state.saving = false;
                state.savePromise = null;
                if (state.dirty && state.draftVersion !== snapshot.draftVersion) scheduleAutosave(0);
            }
        })();
        return state.savePromise;
    }

    function open() {
        if (typeof window.closeComfyUiSettings === 'function') window.closeComfyUiSettings();
        if (typeof window.setApiSettingsSection === 'function') window.setApiSettingsSection('connections');
        root?.removeAttribute('hidden');
        canvasModelSettingsBlock?.setAttribute('hidden', 'hidden');
        layout?.classList.add('hypit-settings-mode');
        block?.removeAttribute('hidden');
        nav?.classList.add('active');
        nav?.setAttribute('aria-current', 'page');
        document.querySelector('.api-page-delete-btn')?.setAttribute('hidden', 'hidden');
        document.querySelector('.api-page-save-btn')?.setAttribute('hidden', 'hidden');
        render();
        syncEditorHeader();
        if (!state.loaded) load();
    }

    function close(options = {}) {
        layout?.classList.remove('hypit-settings-mode');
        block?.setAttribute('hidden', 'hidden');
        nav?.classList.remove('active');
        nav?.setAttribute('aria-current', 'false');
        document.querySelector('.api-page-delete-btn')?.removeAttribute('hidden');
        document.querySelector('.api-page-save-btn')?.removeAttribute('hidden');
        if (options.deferEditor) return;
        if (typeof window.setApiSettingsSection === 'function') window.setApiSettingsSection('connections');
        else if (typeof window.renderEditor === 'function') window.renderEditor();
    }

    function onSlotChange(event) {
        const target = event.target;
        const slot = target?.dataset?.hypitSlot;
        if (!slot) return;
        if (target.matches('[data-hypit-family], [data-hypit-variant], [data-hypit-provider]')) {
            const card = target.closest('[data-hypit-slot-card]');
            if (!card) return;
            if (target.matches('[data-hypit-family]')) {
                const families = candidateFamilies(slot);
                if(!target.value){state.settings.defaults[slot]=emptySlot();renderSlotInPlace(slot);markDirty();return;}
                const family = families.find(item => item.family_id === target.value);
                const variants = family?.variants || [];
                const variantSelect = card.querySelector('[data-hypit-variant]');
                const providerSelect = card.querySelector('[data-hypit-provider]');
                if (variantSelect) variantSelect.innerHTML = variantOptions(variants, variants[0]?.model_id);
                const providers = variants.filter((item, index, list) => list.findIndex(other => selectionKey(other) === selectionKey(item)) === index);
                if (providerSelect) providerSelect.innerHTML = providers.map(item => `<option value="${escapeHtml(selectionKey(item))}">${escapeHtml(modelLabel(item))}</option>`).join('');
            } else if (target.matches('[data-hypit-variant]')) {
                const families = candidateFamilies(slot);
                const family = families.find(item => item.family_id === card.querySelector('[data-hypit-family]')?.value);
                const selected = family?.variants.find(item => item.model_id === target.value);
                const providerSelect = card.querySelector('[data-hypit-provider]');
                if (providerSelect && selected) providerSelect.value = selectionKey(selected);
            }
            syncSelection(slot, card);
            renderSlotInPlace(slot);
            markDirty();
            return;
        }
        if (target.matches('[data-hypit-parameter]')) {
            const current = state.settings.defaults[slot] || emptySlot();
            current.parameters = current.parameters || {};
            const value = target.type === 'checkbox' ? target.checked : (target.type === 'number' && target.value !== '' ? Number(target.value) : target.value);
            if (value === '' || value === undefined) delete current.parameters[target.dataset.hypitParameter];
            else current.parameters[target.dataset.hypitParameter] = value;
            state.settings.defaults[slot] = current;
            markDirty();
        }
    }

    function renderSlotInPlace(slot) {
        const active = document.activeElement;
        const focusState = active && slotsEl?.contains?.(active) ? {
            slot: active.dataset?.hypitSlot || '',
            parameter: active.dataset?.hypitParameter || '',
            choice: active.dataset?.hypitChoice || '',
            selectionStart: active.selectionStart,
            selectionEnd: active.selectionEnd
        } : null;
        const currentCard = [...(slotsEl?.querySelectorAll('[data-hypit-slot-card]') || [])]
            .find(item => item.dataset.hypitSlotCard === slot);
        if (!currentCard) return render();
        const wrapper = document.createElement('div');
        wrapper.innerHTML = renderSlot(slot);
        const next = wrapper.firstElementChild;
        if (next) currentCard.replaceWith(next);
        refreshIcons();
        if (!focusState) return;
        const candidates = [...(slotsEl?.querySelectorAll('[data-hypit-slot], [data-hypit-choice]') || [])];
        const focused = candidates.find(item => item.dataset?.hypitSlot === focusState.slot
            && item.dataset?.hypitParameter === focusState.parameter
            && item.dataset?.hypitChoice === focusState.choice);
        if (focused?.focus) {
            focused.focus();
            if (focusState.selectionStart !== undefined && focused.setSelectionRange) {
                focused.setSelectionRange(focusState.selectionStart, focusState.selectionEnd);
            }
        }
    }

    function handleHypitNavigationCapture(event) {
        if (!layout?.classList.contains('hypit-settings-mode')) return;
        const target = event.target?.closest?.('.sidebar button, .sidebar [role="button"], .sidebar .provider-card, .sidebar a');
        if (!target || target.id === 'hypitSettingsNav' || target.closest?.('#hypitSettingsNav')) return;
        // 捕获阶段只退出 Hypit，不阻止目标按钮自己的 onclick，保证左侧导航仍能继续执行。
        close({ deferEditor: true });
    }

    registerTranslations();
    if (window.StudioI18n) window.StudioI18n.apply(document);

    // 诊断/测试用只读查询：让用例断言“候选数据”而不是渲染出来的 HTML，
    // 这样槽位 UI 换成公共控件时不会因为标记变化而误报。
    window.hypitSlotCandidates = slot => enabledModels(slot).map(model => ({
        option_id: model.option_id || '',
        provider_id: model.provider_id || '',
        model_id: model.model_id || '',
        region: normalizeRegion(model.region),
        label: modelLabel(model),
        parameters: model.parameters || {},
        inputs: model.inputs || {}
    }));
    window.hypitSlotSelection = slot => clone(state.settings.defaults[slot] || emptySlot());
    window.hypitProjectionAvailable = () => state.projectionAvailable === true;

    window.openHypitSettings = open;
    window.closeHypitSettings = close;
    window.reloadHypitSettings = load;
    window.saveHypitSettings = save;

    slotsEl?.addEventListener('click', event=>{
        const target=event.target.closest('[data-hypit-choice]');if(!target)return;
        const current=state.settings.defaults[target.dataset.hypitSlot];
        if(target.dataset.value==='')delete current.parameters[target.dataset.hypitChoice];
        else current.parameters[target.dataset.hypitChoice]=JSON.parse(target.dataset.value);
        renderSlotInPlace(target.dataset.hypitSlot);
        markDirty();
    });
    slotsEl?.addEventListener('change', onSlotChange);
    slotsEl?.addEventListener('input', onSlotChange);
    document.addEventListener('click', handleHypitNavigationCapture, true);
    window.addEventListener('studio-lang-change', () => {
        if (state.loaded || layout?.classList.contains('hypit-settings-mode')) render();
        syncEditorHeader();
    });
    window.addEventListener('load', () => {
        if (new URLSearchParams(location.search).get('section') === 'hypit') {
            open();
            return;
        }
        if (layout?.classList.contains('hypit-settings-mode')) load();
    });
})();
