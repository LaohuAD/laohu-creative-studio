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
    const WORKFLOW_OUTPUT_KINDS = { text: 'text', image: 'image', video: 'video', audio: 'audio', music: 'audio', voice: 'audio' };
    const WORKFLOW_INPUT_TYPES = {
        prompt: 'text', system_prompt: 'text', reference: 'image', source_video: 'video',
        reference_audio: 'audio', first_frame: 'image', last_frame: 'image'
    };
    const WORKFLOW_SLOT_ROLES = {
        text: ['reference', 'source_video', 'reference_audio'],
        image: ['reference'],
        video: ['reference', 'source_video', 'reference_audio', 'first_frame', 'last_frame'],
        audio: ['reference_audio'], music: ['reference_audio'], voice: ['reference_audio']
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
    const settingsCanvasFrame = document.getElementById('hypitSettingsCanvasFrame');
    const settingsCanvasResetButton = document.getElementById('hypitSettingsReset');
    const settingsCanvasNewTabButton = document.getElementById('hypitSettingsNewTab');
    const SETTINGS_CANVAS_ID = 'hypit-settings';
    let settingsCanvasResetting = false;
    const settingsCanvasController = window.StudioSettingsCanvasController.create({
        id: SETTINGS_CANVAS_ID,
        mode: 'hypit-settings',
        endpoint: '/api/hypit/settings-canvas',
        frame: settingsCanvasFrame,
        invalidUrlMessage: () => currentLang() === 'en' ? 'The Hypit settings canvas address is invalid.' : '服务返回了无效的 Hypit 画布地址',
        invalidPayloadMessage: () => currentLang() === 'en' ? 'The Hypit settings canvas response is invalid.' : '服务未返回专用 Hypit 设置画布',
        timeoutMessage: () => t('hypit.canvasFrameTimeout'),
        frameErrorMessage: () => t('hypit.canvasFrameError'),
        onLoading: () => setStatus(t('hypit.canvasLoading')),
        onReady: () => setStatus(t('hypit.canvasReady')),
        onError: error => setStatus(t('hypit.canvasLoadError', {message:error?.message || error}), 'error'),
    });
    const AUTOSAVE_DELAY = 320;
    const state = {
        catalog: { providers: [] },
        capabilities: [],
        unsupported: [],
        settings: { defaults: {} },
        persistedDefaults: {},
        loaded: false,
        loading: false,
        loadError: '',
        saving: false,
        saveTimer: null,
        savePromise: null,
        saveWaiters: [],
        draftVersion: 0,
        savedVersion: 0,
        dirty: false,
        selectionAttemptId: 0,
        selectionAttempts: {},
        workflowOptions: { options: [], unavailable: [] },
        workflowLoaded: false,
        workflowLoading: false,
        workflowLoadError: '',
        workflowStale: false,
        workflowPromise: null,
        workflowRequestSeq: 0,
        workflowInvalidation: 0,
        workflowReloadAfterLoad: false,
        workflowDrafts: {},
        workflowAttempts: {},
        slotSources: {},
        lastWorkflowSourceChangeKey: '',
        loadPromise: null,
        catalogStale: false,
        providerInvalidation: 0,
        reloadAfterLoad: false
    };

    const translations = {
        zh: {
            'hypit.navTitle': 'Hypit 设置',
            'hypit.navLabel': 'Hypit克隆',
            'hypit.navMeta': '生成模型',
            'hypit.title': 'Hypit 设置',
            'hypit.description': '选择各类生成任务使用的 API 模型或工作流；每次任务按所选来源要求提供内容与参数。',
            'hypit.canvasTitle': 'Hypit 流程设置',
            'hypit.canvasDescription': '在画布中配置生成流程，将执行节点连接到对应输出端口。',
            'hypit.canvasReset': '重置配置',
            'hypit.canvasResetTitle': '清空 Hypit 流程配置画布',
            'hypit.canvasNewTab': '打开画布编辑',
            'hypit.canvasNewTabTitle': '在独立标签中打开同一份 Hypit 画布',
            'hypit.canvasFrameTitle': 'Hypit 流程设置画布',
            'hypit.canvasLoading': '正在读取 Hypit 流程画布…',
            'hypit.canvasReady': '',
            'hypit.canvasFrameTimeout': '画布页面加载超时',
            'hypit.canvasFrameError': '画布页面无法打开',
            'hypit.canvasLoadError': 'Hypit 流程画布读取失败：{message}。请重试读取。',
            'hypit.canvasRetry': '重试读取',
            'hypit.canvasResetConfirm': '将清空 Hypit 设置画布中的所有节点和连线。磁盘素材、生成结果与其他画布不会删除。此操作无法撤销，是否继续？',
            'hypit.canvasResetDone': 'Hypit 流程画布已重置。',
            'hypit.canvasResetError': '重置失败，当前画布内容已保留：{message}',
            'articleSettings.navLabel': '公众号文章',
            'articleSettings.navMeta': '文章生成配置',
            'articleSettings.canvasTitle': '文章生成配置',
            'articleSettings.canvasDescription': '在同一画布中配置文章生成节点与输出。',
            'articleSettings.canvasReset': '重置配置',
            'articleSettings.canvasResetTitle': '清空文章生成配置画布',
            'articleSettings.canvasNewTab': '打开画布编辑',
            'articleSettings.canvasNewTabTitle': '在独立标签中打开同一份文章配置画布',
            'articleSettings.canvasFrameTitle': '文章生成配置画布',
            'articleSettings.canvasLoading': '正在读取文章生成配置…',
            'articleSettings.canvasReady': '',
            'articleSettings.canvasFrameTimeout': '画布页面加载超时',
            'articleSettings.canvasFrameError': '画布页面无法打开',
            'articleSettings.canvasLoadError': '文章生成配置读取失败：{message}。请重试读取。',
            'articleSettings.canvasRetry': '重试读取',
            'articleSettings.canvasResetConfirm': '将清空文章生成配置画布中的所有节点和连线。磁盘素材、生成结果与其他画布不会删除。此操作无法撤销，是否继续？',
            'articleSettings.canvasResetDone': '文章生成配置画布已重置。',
            'articleSettings.canvasResetError': '重置失败，当前画布内容已保留：{message}',
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
            'hypit.selectedUnavailable': '已选不可用',
            'hypit.loadingStatus': '读取中',
            'hypit.loadFailedStatus': '读取失败',
            'hypit.loadFailedSlot': '模型设置读取失败：{message}。请点击页面上方“重新读取”重试。',
            'hypit.notSet': '未设置',
            'hypit.noCandidatesStatus': '暂无可用模型',
            'hypit.noCandidates': '当前没有符合此用途和接口契约的可运行模型。请启用适用于此槽位的模型；现有设置会保留。',
            'hypit.noPlatforms': '当前没有已启用的平台。请先到“平台连接”配置并启用平台。',
            'hypit.noVideoGenerator': '当前视频目录只有视频增强工具，没有可用的视频生成模型。请启用视频生成模型；现有设置会保留。',
            'hypit.noSoundEffectGenerator': '当前目录只有语音合成模型，没有可用的音效生成模型。语音模型可在独立的“语音生成”槽使用；现有设置会保留。',
            'hypit.operationVideoUpscale': '当前已保存的是视频增强/放大工具，不是视频生成模型；原选择已保留。请从可运行候选中选择视频生成模型。',
            'hypit.operationSpeechInAudio': '当前已保存的是语音合成模型，不适用于音效生成；原选择已保留。请在音效槽选择音效模型，语音合成请使用独立的语音生成槽。',
            'hypit.selectedUnavailableGeneric': '当前已保存的模型不在此槽位的可运行候选中；原选择已保留。检查平台启用状态和模型配置，或从候选中重新选择。',
            'hypit.platformUnavailable': '该平台当前未配置或未启用；原选择已保留。请到“平台连接”检查平台状态，再重新选择。',
            'hypit.modelUnavailable': '该模型不在平台当前可用目录中；原选择已保留。请启用此模型或从当前候选中重新选择。',
            'hypit.adapterUnavailable': '该模型的本机适配器或执行契约尚未就绪；原选择已保留。请检查平台适配状态或选择已就绪的候选。',
            'hypit.localReady': '可运行',
            'hypit.localReadyTitle': '当前模型支持此用途，已保存。实际运行结果以平台响应为准。',
            'hypit.loading': '正在读取 Hypit 模型设置…',
            'hypit.refreshing': '正在更新模型候选，更新完成前暂不能更改模型。',
            'hypit.saving': '正在保存…',
            'hypit.saved': '已保存',
            'hypit.loaded': '',
            'hypit.loadError': '读取 Hypit 设置失败：{message}',
            'hypit.saveError': '保存 Hypit 设置失败：{message}',
            'hypit.apiModels': 'API 模型',
            'hypit.workflowSource': '工作流',
            'hypit.workflowLoading': '正在读取工作流候选…',
            'hypit.workflowLoadError': '工作流候选读取失败：{message}',
            'hypit.workflowRetry': '重试读取',
            'hypit.workflowEmpty': '当前没有可用工作流。请先配置并启用 RunningHub 应用/工作流，或本地 ComfyUI 工作流。',
            'hypit.workflowUnnamed': '未命名工作流',
            'hypit.workflowChoose': '选择工作流后检查输入映射和必填项。',
            'hypit.workflowSourceAppAI': 'RunningHub AI · 应用',
            'hypit.workflowSourceAppCN': 'RunningHub CN · 应用',
            'hypit.workflowSourceFlowAI': 'RunningHub AI · 工作流',
            'hypit.workflowSourceFlowCN': 'RunningHub CN · 工作流',
            'hypit.workflowSourceComfy': '本地 ComfyUI',
            'hypit.workflowUnavailable': '此工作流当前不可用；请检查来源状态或重新同步字段。',
            'hypit.workflowSchemaChanged': '输入字段已变化，需要重新选择并检查映射。',
            'hypit.workflowSavedMissing': '已保存的工作流已不存在或不可用；原选择保留。请重新选择工作流。',
            'hypit.workflowFields': '输入字段',
            'hypit.workflowRole': '映射到输入',
            'hypit.workflowFieldValue': '默认值',
            'hypit.workflowTypeText': '文本',
            'hypit.workflowTypeImage': '图片',
            'hypit.workflowTypeVideo': '视频',
            'hypit.workflowTypeAudio': '音频',
            'hypit.workflowTypeNumber': '数值',
            'hypit.workflowTypeBoolean': '开关',
            'hypit.workflowTypeSelect': '选项',
            'hypit.workflowNoMapping': '不绑定',
            'hypit.workflowPrompt': '提示词',
            'hypit.workflowSystemPrompt': '系统提示词',
            'hypit.workflowReference': '参考图片',
            'hypit.workflowSourceVideo': '参考视频',
            'hypit.workflowReferenceAudio': '参考音频',
            'hypit.workflowFirstFrame': '首帧图片',
            'hypit.workflowLastFrame': '尾帧图片',
            'hypit.workflowPromptAmbiguous': '有多个文本字段，请明确选择提示词字段。',
            'hypit.workflowNeedPrompt': '请把一个文本字段映射为提示词。',
            'hypit.workflowNeedRequired': '请填写或映射所有必填字段。',
            'hypit.workflowConfirm': '用于{slot}',
            'hypit.workflowConfirming': '正在保存…',
            'hypit.workflowRetrySave': '重试保存',
            'hypit.workflowUnsupportedField': '此字段类型暂不支持编辑',
        },
        en: {
            'hypit.navTitle': 'Hypit settings',
            'hypit.navLabel': 'Hypit Clone',
            'hypit.navMeta': 'Generation models',
            'hypit.title': 'Hypit settings',
            'hypit.description': 'Choose an API model or workflow for each generation task; provide the content and parameters required by the selected source.',
            'hypit.canvasTitle': 'Hypit workflow settings',
            'hypit.canvasDescription': 'Configure generation flows on the canvas and connect execution nodes to their matching output ports.',
            'hypit.canvasReset': 'Reset configuration',
            'hypit.canvasResetTitle': 'Clear the Hypit workflow configuration canvas',
            'hypit.canvasNewTab': 'Open canvas editor',
            'hypit.canvasNewTabTitle': 'Open the same Hypit canvas in a separate tab',
            'hypit.canvasFrameTitle': 'Hypit workflow settings canvas',
            'hypit.canvasLoading': 'Loading the Hypit workflow canvas…',
            'hypit.canvasReady': '',
            'hypit.canvasFrameTimeout': 'Canvas page load timed out',
            'hypit.canvasFrameError': 'Canvas page could not be opened',
            'hypit.canvasLoadError': 'Could not load the Hypit workflow canvas: {message}. Retry loading.',
            'hypit.canvasRetry': 'Retry loading',
            'hypit.canvasResetConfirm': 'This clears all nodes and connections from the Hypit settings canvas. Disk assets, generated results, and other canvases are preserved. This cannot be undone. Continue?',
            'hypit.canvasResetDone': 'The Hypit workflow canvas was reset.',
            'hypit.canvasResetError': 'Reset failed; the current canvas was preserved: {message}',
            'articleSettings.navLabel': 'Articles',
            'articleSettings.navMeta': 'Generation setup',
            'articleSettings.canvasTitle': 'Article generation setup',
            'articleSettings.canvasDescription': 'Configure article generation nodes and outputs on the same canvas.',
            'articleSettings.canvasReset': 'Reset configuration',
            'articleSettings.canvasResetTitle': 'Clear the article generation canvas',
            'articleSettings.canvasNewTab': 'Open canvas editor',
            'articleSettings.canvasNewTabTitle': 'Open the same article configuration canvas in a separate tab',
            'articleSettings.canvasFrameTitle': 'Article generation canvas',
            'articleSettings.canvasLoading': 'Loading article generation setup…',
            'articleSettings.canvasReady': '',
            'articleSettings.canvasFrameTimeout': 'Canvas page load timed out',
            'articleSettings.canvasFrameError': 'Canvas page could not be opened',
            'articleSettings.canvasLoadError': 'Could not load article generation setup: {message}. Retry loading.',
            'articleSettings.canvasRetry': 'Retry loading',
            'articleSettings.canvasResetConfirm': 'This clears all nodes and connections from the article generation canvas. Disk assets, generated results, and other canvases are preserved. This cannot be undone. Continue?',
            'articleSettings.canvasResetDone': 'The article generation canvas was reset.',
            'articleSettings.canvasResetError': 'Reset failed; the current canvas was preserved: {message}',
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
            'hypit.selectedUnavailable': 'Selected model unavailable',
            'hypit.loadingStatus': 'Loading',
            'hypit.loadFailedStatus': 'Load failed',
            'hypit.loadFailedSlot': 'Could not load model settings: {message}. Use “Reload” above to try again.',
            'hypit.notSet': 'Not set',
            'hypit.noCandidatesStatus': 'No available models',
            'hypit.noCandidates': 'No runnable model currently matches this use and API contract. Enable a model for this slot; existing settings are retained.',
            'hypit.noPlatforms': 'No platform is currently configured and enabled. Configure and enable one under Platform connections.',
            'hypit.noVideoGenerator': 'The current video catalog contains only video-enhancement tools, with no video-generation model. Enable a video-generation model; existing settings are retained.',
            'hypit.noSoundEffectGenerator': 'The current catalog contains speech-synthesis models but no sound-effects model. Speech models belong in the separate Speech generation slot; existing settings are retained.',
            'hypit.operationVideoUpscale': 'The saved choice is a video-enhancement/upscaling tool, not a video-generation model. It has been retained. Choose a runnable video-generation candidate.',
            'hypit.operationSpeechInAudio': 'The saved choice is a speech-synthesis model, not a sound-effects model. It has been retained. Choose a sound-effects model here; speech synthesis has its own slot.',
            'hypit.selectedUnavailableGeneric': 'The saved model is not a runnable candidate for this slot. It has been retained. Check platform/model enablement or choose a current candidate.',
            'hypit.platformUnavailable': 'This platform is not currently configured or enabled. The saved choice is retained. Check Platform connections, then choose again.',
            'hypit.modelUnavailable': 'This model is not in the platform’s current available catalog. The saved choice is retained. Enable it or choose a current candidate.',
            'hypit.adapterUnavailable': 'The local adapter or execution contract for this model is not ready. The saved choice is retained. Check the adapter or choose a ready candidate.',
            'hypit.localReady': 'Ready',
            'hypit.localReadyTitle': 'This saved model supports this use. Actual results depend on the provider response.',
            'hypit.loading': 'Loading Hypit model settings…',
            'hypit.refreshing': 'Updating model choices; changes are temporarily disabled until the refresh completes.',
            'hypit.saving': 'Saving…',
            'hypit.saved': 'Saved',
            'hypit.loaded': '',
            'hypit.loadError': 'Could not load Hypit settings: {message}',
            'hypit.saveError': 'Could not save Hypit settings: {message}',
            'hypit.apiModels': 'API models',
            'hypit.workflowSource': 'Workflows',
            'hypit.workflowLoading': 'Loading workflow choices…',
            'hypit.workflowLoadError': 'Could not load workflow choices: {message}',
            'hypit.workflowRetry': 'Retry loading',
            'hypit.workflowEmpty': 'No available workflows. Configure and enable a RunningHub app/workflow or a local ComfyUI workflow first.',
            'hypit.workflowUnnamed': 'Unnamed workflow',
            'hypit.workflowChoose': 'Choose a workflow to review its input mappings and required fields.',
            'hypit.workflowSourceAppAI': 'RunningHub AI · Apps',
            'hypit.workflowSourceAppCN': 'RunningHub CN · Apps',
            'hypit.workflowSourceFlowAI': 'RunningHub AI · Workflows',
            'hypit.workflowSourceFlowCN': 'RunningHub CN · Workflows',
            'hypit.workflowSourceComfy': 'Local ComfyUI',
            'hypit.workflowUnavailable': 'This workflow is unavailable. Check its source or sync its fields again.',
            'hypit.workflowSchemaChanged': 'Its input fields changed. Reselect it and review the mappings.',
            'hypit.workflowSavedMissing': 'The saved workflow is missing or unavailable; the selection is retained. Choose another workflow.',
            'hypit.workflowFields': 'Input fields',
            'hypit.workflowRole': 'Map to input',
            'hypit.workflowFieldValue': 'Default value',
            'hypit.workflowTypeText': 'Text',
            'hypit.workflowTypeImage': 'Image',
            'hypit.workflowTypeVideo': 'Video',
            'hypit.workflowTypeAudio': 'Audio',
            'hypit.workflowTypeNumber': 'Number',
            'hypit.workflowTypeBoolean': 'Boolean',
            'hypit.workflowTypeSelect': 'Choice',
            'hypit.workflowNoMapping': 'Do not bind',
            'hypit.workflowPrompt': 'Prompt',
            'hypit.workflowSystemPrompt': 'System prompt',
            'hypit.workflowReference': 'Reference image',
            'hypit.workflowSourceVideo': 'Reference video',
            'hypit.workflowReferenceAudio': 'Reference audio',
            'hypit.workflowFirstFrame': 'First-frame image',
            'hypit.workflowLastFrame': 'Last-frame image',
            'hypit.workflowPromptAmbiguous': 'Several text fields are available. Choose the prompt field explicitly.',
            'hypit.workflowNeedPrompt': 'Map one text field to the prompt.',
            'hypit.workflowNeedRequired': 'Fill in or map every required field.',
            'hypit.workflowConfirm': 'Use for {slot}',
            'hypit.workflowConfirming': 'Saving…',
            'hypit.workflowRetrySave': 'Retry save',
            'hypit.workflowUnsupportedField': 'Editing this field type is not supported yet',
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

    function settingsCanvasUrl(payload) {
        return settingsCanvasController.canvasUrl(payload);
    }

    function loadSettingsCanvasBootstrap(options = {}) {
        return settingsCanvasController.loadBootstrap(options);
    }

    function prefetchSettingsCanvasBootstrap() {
        return loadSettingsCanvasBootstrap().then(() => true).catch(() => false);
    }

    function syncSettingsCanvasFrameContext() {
        return settingsCanvasController.syncContext();
    }

    function loadSettingsCanvas(options = {}) {
        settingsCanvasController.activate();
        return settingsCanvasController.load(options);
    }

    function openSettingsCanvasInNewTab() {
        return settingsCanvasController.openInNewTab({
            onBlocked:() => setStatus(t('hypit.canvasLoadError', {message:currentLang() === 'en' ? 'the browser blocked the new tab' : '浏览器阻止了新标签'}), 'error'),
            onError:error => setStatus(t('hypit.canvasLoadError', {message:error?.message || error}), 'error'),
        });
    }

    async function resetSettingsCanvas() {
        if (settingsCanvasResetting) return false;
        const confirmMessage = t('hypit.canvasResetConfirm');
        const confirmed = window.StudioDialog?.confirm
            ? await window.StudioDialog.confirm(confirmMessage, {title:t('hypit.canvasReset'), type:'danger'})
            : window.confirm(confirmMessage);
        if (!confirmed) return false;
        settingsCanvasResetting = true;
        settingsCanvasResetButton?.setAttribute('disabled', 'disabled');
        settingsCanvasFrame?.classList.add('is-resetting');
        try {
            await loadSettingsCanvas();
            const bridge = settingsCanvasFrame?.contentWindow?.HypitSettingsCanvasBridge;
            if (!bridge?.prepareReset) throw new Error(t('hypit.canvasRetry'));
            const revision = await bridge.prepareReset();
            const response = await fetch('/api/hypit/settings-canvas/reset', {
                method:'POST', headers:{'Content-Type':'application/json'},
                body:JSON.stringify({base_revision:revision, client_id:`hypit_settings_${Date.now().toString(36)}`})
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || payload?.reset !== true || payload?.canvas?.id !== SETTINGS_CANVAS_ID) {
                throw new Error(payload?.detail?.message || payload?.detail || `HTTP ${response.status}`);
            }
            const applied = await bridge.applyReset?.(payload.canvas);
            if (applied !== true) throw new Error(currentLang() === 'en' ? 'the editor could not apply the reset snapshot' : '画布没有接收重置结果');
            setStatus(t('hypit.canvasResetDone'), 'success');
            return true;
        } catch (error) {
            settingsCanvasFrame?.contentWindow?.HypitSettingsCanvasBridge?.cancelReset?.();
            setStatus(t('hypit.canvasResetError', {message:error?.message || error}), 'error');
            return false;
        } finally {
            settingsCanvasResetting = false;
            settingsCanvasResetButton?.removeAttribute('disabled');
            settingsCanvasFrame?.classList.remove('is-resetting');
        }
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
        return { selection_kind: 'api_model', provider: '', model: '', region: '', parameters: {} };
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
            const selected = state.settings.defaults[slot];
            // 缺少 selection_kind 的旧槽位按 API 模型读取；工作流身份只接受冻结的 workflow 枚举。
            selected.selection_kind = selected.selection_kind === 'workflow' ? 'workflow' : 'api_model';
            selected.region = normalizeRegion(selected.region);
            if (!selected.parameters || typeof selected.parameters !== 'object') {
                selected.parameters = {};
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

    function sameSelection(left, right) {
        return left?.provider === right?.provider
            && left?.model === right?.model
            && normalizeRegion(left?.region) === normalizeRegion(right?.region);
    }

    function sameWorkflow(left, right) {
        return left?.selection_kind === 'workflow' && right?.selection_kind === 'workflow'
            && left?.source === right?.source
            && left?.provider_id === right?.provider_id
            && normalizeRegion(left?.region) === normalizeRegion(right?.region)
            && left?.item_id === right?.item_id
            && left?.schema_fingerprint === right?.schema_fingerprint;
    }

    function allWorkflowOptions() {
        return [...(state.workflowOptions.options || []), ...(state.workflowOptions.unavailable || [])];
    }

    function workflowOptionForSelection(selection) {
        return allWorkflowOptions().find(option => option.source === selection?.source
            && option.provider_id === selection?.provider_id
            && normalizeRegion(option.region) === normalizeRegion(selection?.region)
            && option.item_id === selection?.item_id) || null;
    }

    function workflowUnavailableReason(selection, option) {
        if (!state.workflowLoaded) return state.workflowLoadError
            ? t('hypit.workflowLoadError', { message: state.workflowLoadError })
            : t('hypit.workflowLoading');
        if (!option) return t('hypit.workflowSavedMissing');
        if (selection?.schema_fingerprint && option.schema_fingerprint
            && selection.schema_fingerprint !== option.schema_fingerprint) return t('hypit.workflowSchemaChanged');
        return option.unavailable_reason || t('hypit.workflowUnavailable');
    }

    function savedWorkflowStatus(slot, selection) {
        if (state.workflowStale || state.workflowLoading) {
            return { text: t('hypit.loadingStatus'), className: '',
                description: state.workflowLoadError
                    ? t('hypit.workflowLoadError', { message: state.workflowLoadError })
                    : t('hypit.workflowLoading') };
        }
        const option = workflowOptionForSelection(selection);
        if (!state.workflowLoaded) {
            return { text: state.workflowLoadError ? t('hypit.selectedUnavailable') : t('hypit.loadingStatus'),
                className: state.workflowLoadError ? 'is-warning' : '',
                description: workflowUnavailableReason(selection, option) };
        }
        if (!option || option.available !== true || option.enabled !== true || option.schema_status !== 'ready'
            || !option.schema_fingerprint || option.schema_fingerprint !== selection.schema_fingerprint) {
            return { text: t('hypit.selectedUnavailable'), className: 'is-warning',
                description: workflowUnavailableReason(selection, option) };
        }
        return { text: t('hypit.localReady'), title: t('hypit.localReadyTitle'), className: 'is-ready' };
    }

    function catalogOptionForSelection(current) {
        const options = Array.isArray(state.catalog?.options) ? state.catalog.options : [];
        return options.find(option => option.connection_id === current.provider
            && option.catalog_model_id === current.model
            && normalizeRegion(option.region_id) === normalizeRegion(current.region))
            || (!current.region ? options.find(option => option.connection_id === current.provider
                && option.catalog_model_id === current.model) : null)
            || null;
    }

    function selectedUnavailableReason(slot, current) {
        const option = catalogOptionForSelection(current);
        if (slot === 'video' && option?.operation === 'video_upscale') return t('hypit.operationVideoUpscale');
        if (slot === 'audio' && option?.operation === 'text_to_speech') return t('hypit.operationSpeechInAudio');
        const providers = Array.isArray(state.catalog?.providers) ? state.catalog.providers : [];
        const activeProvider = providers.some(provider => String(provider.id || '') === current.provider
            && provider.enabled !== false);
        if (!activeProvider) return t('hypit.platformUnavailable');
        return option ? t('hypit.adapterUnavailable') : t('hypit.modelUnavailable');
    }

    function noCandidateMessage(slot) {
        const providers = Array.isArray(state.catalog?.providers) ? state.catalog.providers : [];
        if (!providers.some(provider => provider && provider.enabled !== false)) return t('hypit.noPlatforms');
        const options = Array.isArray(state.catalog?.options) ? state.catalog.options : [];
        const slotOptions = options.filter(option => option.node_type === NODE_TYPES[slot]);
        if (slot === 'video' && slotOptions.some(option => option.operation === 'video_upscale')
            && !slotOptions.some(option => option.operation !== 'video_upscale' && option.runnable === true && option.selectable !== false)) {
            return t('hypit.noVideoGenerator');
        }
        if (slot === 'audio' && slotOptions.some(option => option.operation === 'text_to_speech')
            && !slotOptions.some(option => option.operation !== 'text_to_speech' && option.runnable === true && option.selectable !== false)) {
            return t('hypit.noSoundEffectGenerator');
        }
        return t('hypit.noCandidates');
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
        if (!model) return { text: t('hypit.noCandidatesStatus'), className: 'is-warning' };
        if (model.runnable === false || (model.readiness && model.readiness !== 'ready') || model.validation_mode !== 'strict') {
            return { text: model.readiness || t('hypit.unavailable'), className: 'is-warning' };
        }
        return { text: t('hypit.localReady'), title: t('hypit.localReadyTitle'), className: 'is-ready' };
    }

    function slotStatus(slot, current, models, selectedModel) {
        if (state.loading && !state.loaded) return { text: t('hypit.loadingStatus'), className: '' };
        if (state.loadError && !state.loaded) {
            const message = state.loadError;
            return {
                text: t('hypit.loadFailedStatus'),
                className: 'is-warning',
                description: t('hypit.loadFailedSlot', { message })
            };
        }
        if (!state.loaded) return { text: t('hypit.loadingStatus'), className: '' };
        if (current.selection_kind === 'workflow') return savedWorkflowStatus(slot, current);
        if (current.provider && current.model) {
            return selectedModel
                ? statusFor(slot, selectedModel)
                : { text: t('hypit.selectedUnavailable'), className: 'is-warning', description: selectedUnavailableReason(slot, current) };
        }
        if (!models.length) return { text: t('hypit.noCandidatesStatus'), className: 'is-warning', description: noCandidateMessage(slot) };
        return { text: t('hypit.notSet'), className: '' };
    }

    function selectedModelNote(slot, current) {
        const providerName = current.provider === 'ai-money' ? 'laohu' : current.provider;
        return `<div class="hypit-slot-description">${escapeHtml(selectedUnavailableReason(slot, current))}<br><code>${escapeHtml(providerName)} / ${escapeHtml(current.model)}${current.region ? ` · ${escapeHtml(regionLabel(current.region))}` : ''}</code></div>`;
    }

    function selectedWorkflowNote(slot, current) {
        const option = workflowOptionForSelection(current);
        const name = option ? workflowDisplayName(option) : t('hypit.workflowSource');
        const status = savedWorkflowStatus(slot, current);
        if (status.className !== 'is-warning' && status.className !== '') return '';
        return `<div class="hypit-slot-description" data-workflow-saved-note="${escapeHtml(slot)}">${escapeHtml(status.description || t('hypit.workflowSavedMissing'))}<br><strong>${escapeHtml(name)}</strong></div>`;
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
            selection_kind: 'api_model',
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

    function workflowGroupKey(option) {
        if (option.source === 'local_comfy_workflow') return 'comfy';
        const region = normalizeRegion(option.region) === 'cn' ? 'cn' : 'ai';
        return `${option.source === 'runninghub_app' ? 'app' : 'flow'}-${region}`;
    }

    function workflowGroupLabel(key) {
        const labels = {
            'app-ai': 'hypit.workflowSourceAppAI', 'app-cn': 'hypit.workflowSourceAppCN',
            'flow-ai': 'hypit.workflowSourceFlowAI', 'flow-cn': 'hypit.workflowSourceFlowCN',
            comfy: 'hypit.workflowSourceComfy'
        };
        return t(labels[key] || 'hypit.workflowSource');
    }

    function workflowDisplayName(option) {
        return String(option?.name || '').trim() || t('hypit.workflowUnnamed');
    }

    function workflowFieldLabel(option, field) {
        const label = String(field?.label || '').trim() || t('hypit.workflowRole');
        const sameLabelCount = (option?.fields || []).filter(item => String(item?.label || '').trim() === label).length;
        if (sameLabelCount < 2 || !String(field?.key || '').includes('::')) return label;
        const nodeId = String(field.key).split('::', 1)[0];
        if (!nodeId) return label;
        return currentLang() === 'en' ? `${label} · Node ${nodeId}` : `${label} · 节点 ${nodeId}`;
    }

    function workflowIdentityKey(option) {
        return [option?.source, option?.provider_id, normalizeRegion(option?.region), option?.item_id].join('::');
    }

    function workflowDraftFor(slot) {
        if (state.workflowDrafts[slot]) return state.workflowDrafts[slot];
        const current = state.settings.defaults[slot];
        if (current?.selection_kind !== 'workflow') return null;
        const option = workflowOptionForSelection(current);
        if (!option || option.schema_status !== 'ready' || option.available !== true) return null;
        const fieldRoles = {};
        Object.entries(current.input_bindings || {}).forEach(([role, keys]) => {
            (Array.isArray(keys) ? keys : [keys]).forEach(key => { fieldRoles[key] = role; });
        });
        state.workflowDrafts[slot] = {
            option, fieldRoles, fieldValues: clone(current.field_values || {}), error: '', revision: 0,
            savedFingerprint: current.schema_fingerprint
        };
        return state.workflowDrafts[slot];
    }

    function workflowDraftFromOption(slot, option) {
        const current = state.settings.defaults[slot];
        const sameIdentity = current?.selection_kind === 'workflow'
            && current.source === option.source && current.provider_id === option.provider_id
            && normalizeRegion(current.region) === normalizeRegion(option.region) && current.item_id === option.item_id
            && current.schema_fingerprint === option.schema_fingerprint;
        if (sameIdentity) {
            delete state.workflowDrafts[slot];
            return workflowDraftFor(slot);
        }
        const fields = Array.isArray(option.fields) ? option.fields : [];
        const textFields = fields.filter(field => field.type === 'text');
        const fieldRoles = {};
        // 单一文本字段是唯一不会造成歧义的提示词推荐；多个文本字段必须由用户指定。
        if (textFields.length === 1) fieldRoles[textFields[0].key] = 'prompt';
        const fieldValues = {};
        fields.forEach(field => {
            if (fieldRoles[field.key]) return;
            if (['text', 'number', 'boolean', 'select'].includes(field.type) && field.default !== undefined) {
                fieldValues[field.key] = field.default;
            }
        });
        const draft = { option, fieldRoles, fieldValues, error: '', revision: 0, savedFingerprint: '' };
        state.workflowDrafts[slot] = draft;
        return draft;
    }

    function workflowRoleLabel(role) {
        const keys = {
            prompt: 'hypit.workflowPrompt', system_prompt: 'hypit.workflowSystemPrompt',
            reference: 'hypit.workflowReference', source_video: 'hypit.workflowSourceVideo',
            reference_audio: 'hypit.workflowReferenceAudio', first_frame: 'hypit.workflowFirstFrame',
            last_frame: 'hypit.workflowLastFrame'
        };
        return t(keys[role] || 'hypit.workflowRole');
    }

    function workflowFieldTypeLabel(type) {
        const keys = {
            text: 'hypit.workflowTypeText', image: 'hypit.workflowTypeImage',
            video: 'hypit.workflowTypeVideo', audio: 'hypit.workflowTypeAudio',
            number: 'hypit.workflowTypeNumber', boolean: 'hypit.workflowTypeBoolean',
            select: 'hypit.workflowTypeSelect'
        };
        return keys[type] ? t(keys[type]) : String(type || '');
    }

    function workflowFieldDescription(field) {
        const description = String(field?.description || '').trim();
        if (!description) return '';
        const roleAliases = {
            positive_prompt: 'prompt', caption: 'prompt', instruction: 'prompt',
            image: 'reference', image_reference: 'reference', video: 'source_video', audio: 'reference_audio'
        };
        const inputRole = String(field?.input_role || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
        const role = Object.prototype.hasOwnProperty.call(WORKFLOW_INPUT_TYPES, inputRole)
            ? inputRole : roleAliases[inputRole];
        const duplicates = [field?.label, field?.key, field?.type, field?.input_role,
            role ? workflowRoleLabel(role) : ''].map(value => String(value || '').trim().toLowerCase());
        return duplicates.includes(description.toLowerCase()) ? '' : description;
    }

    function workflowAllowedRoles(slot, field) {
        const type = String(field?.type || '');
        if (type === 'text') return ['prompt', 'system_prompt'];
        return (WORKFLOW_SLOT_ROLES[slot] || []).filter(role => WORKFLOW_INPUT_TYPES[role] === type);
    }

    function workflowRoleSelect(slot, field, draft) {
        const allowed = workflowAllowedRoles(slot, field);
        if (!allowed.length) return '';
        const selected = draft.fieldRoles[field.key] || '';
        const disabled = state.workflowAttempts[slot]?.saving === true || state.workflowStale || state.workflowLoading;
        const choices = [`<option value="">${escapeHtml(t('hypit.workflowNoMapping'))}</option>`, ...allowed.map(role =>
            `<option value="${escapeHtml(role)}"${selected === role ? ' selected' : ''}>${escapeHtml(workflowRoleLabel(role))}</option>`
        )].join('');
        return `<label class="hypit-workflow-role"><span>${escapeHtml(t('hypit.workflowRole'))}</span><select data-workflow-role data-hypit-slot="${escapeHtml(slot)}" data-field-key="${escapeHtml(field.key)}"${disabled ? ' disabled' : ''}>${choices}</select></label>`;
    }

    function workflowValueControl(slot, field, draft) {
        if (!['text', 'number', 'boolean', 'select'].includes(field.type) || draft.fieldRoles[field.key]) return '';
        const value = Object.prototype.hasOwnProperty.call(draft.fieldValues, field.key)
            ? draft.fieldValues[field.key] : (field.default !== undefined ? field.default : '');
        const disabled = state.workflowAttempts[slot]?.saving === true || state.workflowStale || state.workflowLoading;
        const attrs = `data-workflow-value data-hypit-slot="${escapeHtml(slot)}" data-field-key="${escapeHtml(field.key)}"${disabled ? ' disabled' : ''}`;
        if (field.type === 'boolean') {
            return `<select ${attrs}><option value="">${escapeHtml(t('hypit.workflowFieldValue'))}</option><option value="true"${value === true ? ' selected' : ''}>${escapeHtml(currentLang() === 'en' ? 'Yes' : '是')}</option><option value="false"${value === false ? ' selected' : ''}>${escapeHtml(currentLang() === 'en' ? 'No' : '否')}</option></select>`;
        }
        if (field.type === 'select' && Array.isArray(field.options) && field.options.length) {
            return `<select ${attrs}><option value="">${escapeHtml(t('hypit.workflowFieldValue'))}</option>${field.options.map(option => `<option value="${escapeHtml(JSON.stringify(option))}"${String(option) === String(value) ? ' selected' : ''}>${escapeHtml(option)}</option>`).join('')}</select>`;
        }
        const numeric = field.type === 'number';
        return `<input ${attrs} type="${numeric ? 'number' : 'text'}"${numeric && field.step !== undefined ? ` step="${escapeHtml(field.step)}"` : ''}${numeric && field.min !== undefined ? ` min="${escapeHtml(field.min)}"` : ''}${numeric && field.max !== undefined ? ` max="${escapeHtml(field.max)}"` : ''} value="${escapeHtml(value)}" placeholder="${escapeHtml(t('hypit.workflowFieldValue'))}">`;
    }

    function workflowFieldEditor(slot, field, draft) {
        const required = field.required === true;
        if (!['text', 'number', 'boolean', 'select', 'image', 'video', 'audio'].includes(field.type)) {
            return `<div class="hypit-workflow-field is-unsupported"><strong>${escapeHtml(workflowFieldLabel(draft.option, field))}${required ? ' · *' : ''}</strong><small>${escapeHtml(t('hypit.workflowUnsupportedField'))}</small></div>`;
        }
        const role = workflowRoleSelect(slot, field, draft);
        const control = workflowValueControl(slot, field, draft);
        const description = workflowFieldDescription(field);
        return `<div class="hypit-workflow-field" data-workflow-field="${escapeHtml(field.key)}"><strong>${escapeHtml(workflowFieldLabel(draft.option, field))}${required ? ' · *' : ''}</strong><code>${escapeHtml(workflowFieldTypeLabel(field.type))}</code>${description ? `<small class="hypit-workflow-description">${escapeHtml(description)}</small>` : ''}${role}${control}</div>`;
    }

    function workflowBindings(draft) {
        const output = {};
        Object.entries(draft.fieldRoles || {}).forEach(([key, role]) => {
            if (!role) return;
            (output[role] ||= []).push(key);
        });
        return output;
    }

    function workflowDraftValidation(draft) {
        if (!draft?.option) return t('hypit.workflowChoose');
        if (draft.invalidated) return t('hypit.workflowSchemaChanged');
        if (state.workflowStale || state.workflowLoading) return t('hypit.workflowLoading');
        const bindings = workflowBindings(draft);
        const promptTargets = bindings.prompt || [];
        if (promptTargets.length !== 1) {
            const textCount = (draft.option.fields || []).filter(field => field.type === 'text').length;
            return textCount > 1 && !promptTargets.length ? t('hypit.workflowPromptAmbiguous') : t('hypit.workflowNeedPrompt');
        }
        for (const field of draft.option.fields || []) {
            if (field.required !== true) continue;
            const mapped = Boolean(draft.fieldRoles[field.key]);
            if (['image', 'video', 'audio'].includes(field.type)) {
                if (!mapped) return t('hypit.workflowNeedRequired');
                continue;
            }
            const value = Object.prototype.hasOwnProperty.call(draft.fieldValues, field.key)
                ? draft.fieldValues[field.key] : field.default;
            if (!mapped && (value === undefined || value === null || value === '')) return t('hypit.workflowNeedRequired');
        }
        if (!/^[0-9a-f]{64}$/i.test(String(draft.option.schema_fingerprint || ''))) return t('hypit.workflowUnavailable');
        return '';
    }

    function renderWorkflowPanel(slot) {
        if (state.workflowLoading && !state.workflowLoaded) {
            return `<div class="hypit-workflow-message" role="status">${escapeHtml(t('hypit.workflowLoading'))}</div>`;
        }
        if (state.workflowLoadError && !state.workflowLoaded) {
            return `<div class="hypit-workflow-error" role="alert">${escapeHtml(t('hypit.workflowLoadError', { message: state.workflowLoadError }))}<button type="button" data-workflow-retry="${escapeHtml(slot)}">${escapeHtml(t('hypit.workflowRetry'))}</button></div>`;
        }
        if (!state.workflowLoaded) {
            return `<div class="hypit-workflow-message" role="status">${escapeHtml(t('hypit.workflowChoose'))}</div>`;
        }
        const draft = workflowDraftFor(slot);
        const refreshError = state.workflowLoadError && state.workflowLoaded
            ? `<div class="hypit-workflow-error" role="alert">${escapeHtml(t('hypit.workflowLoadError', { message: state.workflowLoadError }))}<button type="button" data-workflow-retry="${escapeHtml(slot)}">${escapeHtml(t('hypit.workflowRetry'))}</button></div>` : '';
        const pending = state.workflowAttempts[slot]?.saving === true;
        const groups = ['app-ai', 'app-cn', 'flow-ai', 'flow-cn', 'comfy'];
        const candidateGroups = groups.map(group => {
            const options = allWorkflowOptions().filter(option => workflowGroupKey(option) === group);
            if (!options.length) return '';
            return `<section class="hypit-workflow-group"><h4>${escapeHtml(workflowGroupLabel(group))}</h4>${options.map(option => {
                const eligible = option.available === true && option.enabled === true && option.schema_status === 'ready'
                    && !state.workflowStale && !state.workflowLoading && !pending;
                const selected = draft && workflowIdentityKey(draft.option) === workflowIdentityKey(option);
                const reason = eligible ? '' : (option.unavailable_reason || t('hypit.workflowUnavailable'));
                return `<button type="button" class="hypit-workflow-option${selected ? ' is-selected' : ''}" data-workflow-option-id="${escapeHtml(option.id || workflowIdentityKey(option))}" data-hypit-slot="${escapeHtml(slot)}" aria-pressed="${selected ? 'true' : 'false'}"${eligible ? '' : ' disabled'}><span><strong>${escapeHtml(workflowDisplayName(option))}</strong><small>${escapeHtml(normalizeRegion(option.region) === 'cn' ? 'CN' : option.source === 'local_comfy_workflow' ? (currentLang() === 'en' ? 'Local' : '本地') : 'AI')}</small></span>${reason ? `<em>${escapeHtml(reason)}</em>` : ''}</button>`;
            }).join('')}</section>`;
        }).join('');
        if (!candidateGroups) return `<div class="hypit-workflow-message">${escapeHtml(t('hypit.workflowEmpty'))}</div>`;
        let editor = `<div class="hypit-workflow-message">${escapeHtml(t('hypit.workflowChoose'))}</div>`;
        if (draft) {
            const fields = Array.isArray(draft.option.fields) ? draft.option.fields : [];
            const validation = workflowDraftValidation(draft);
            const buttonText = pending ? t('hypit.workflowConfirming')
                : draft.error ? t('hypit.workflowRetrySave')
                    : t('hypit.workflowConfirm', { slot: t(SLOT_LABELS[slot]).toLowerCase() });
            editor = `<div class="hypit-workflow-editor" data-workflow-editor="${escapeHtml(slot)}"><div class="hypit-workflow-selected"><strong>${escapeHtml(workflowDisplayName(draft.option))}</strong><span>${escapeHtml(workflowGroupLabel(workflowGroupKey(draft.option)))}</span></div><h4>${escapeHtml(t('hypit.workflowFields'))}</h4><div class="hypit-workflow-fields">${fields.map(field => workflowFieldEditor(slot, field, draft)).join('')}</div>${draft.error ? `<div class="hypit-workflow-error" role="alert">${escapeHtml(draft.error)}</div>` : ''}<div class="hypit-workflow-validation" data-workflow-validation>${escapeHtml(validation)}</div><button type="button" class="hypit-workflow-confirm" data-workflow-confirm="${escapeHtml(slot)}"${validation || pending ? ' disabled' : ''}>${escapeHtml(buttonText)}</button></div>`;
        }
        return `<div class="hypit-workflow-content" data-workflow-content="${escapeHtml(slot)}">${refreshError}<div class="hypit-workflow-groups">${candidateGroups}</div>${editor}</div>`;
    }

    function renderSlot(slot) {
        const models = enabledModels(slot);
        const families = candidateFamilies(slot);
        const current = state.settings.defaults[slot] || emptySlot();
        const selectedModel = modelForSelection(models, current);
        const selectedFamily = families.find(family => family.variants.some(model => modelKey(model) === modelKey(selectedModel)));
        const variants = selectedFamily?.variants || [];
        const selectedVariant = variants.find(model => modelKey(model) === modelKey(selectedModel)) || variants[0];
        const providers = variants.filter((item, index, list) => list.findIndex(other => selectionKey(other) === selectionKey(item)) === index);
        const selectedProvider = providers.find(item => selectionKey(item) === selectionKey(selectedModel)) || selectedVariant;
        const status = slotStatus(slot, current, models, selectedModel);
        const unavailable = current.selection_kind !== 'workflow' && Boolean(current.provider && current.model && !selectedModel);
        const familyOptions = `<option value="">${currentLang() === 'en' ? 'Choose' : '选择'}</option>` + families.map(item => `<option value="${escapeHtml(item.family_id)}"${item === selectedFamily ? ' selected' : ''}>${escapeHtml(familyLabel(item))}</option>`).join('');
        const variantOptionsHtml = variantOptions(variants, selectedVariant?.model_id);
        const providerOptions = providers.map(item => {
            const value = selectionKey(item);
            return `<option value="${escapeHtml(value)}"${value === selectionKey(selectedProvider) ? ' selected' : ''}>${escapeHtml(modelLabel(item))}</option>`;
        }).join('');
        const title = t(SLOT_LABELS[slot]);
        const source = state.slotSources[slot] || (current.selection_kind === 'workflow' ? 'workflow' : 'api_model');
        state.slotSources[slot] = source;
        const modelNote = unavailable ? selectedModelNote(slot, current) : '';
        const workflowNote = current.selection_kind === 'workflow' ? selectedWorkflowNote(slot, current) : '';
        const apiBody = models.length && families.length
            ? `<div class="hypit-model-config" data-model-config-slot="${escapeHtml(slot)}"><div class="hypit-model-config-fallback"><label><span>${escapeHtml(currentLang() === 'en' ? 'Model' : '模型')}</span><select data-hypit-slot="${escapeHtml(slot)}" data-hypit-family="${escapeHtml(slot)}">${familyOptions}</select></label><label><span>${escapeHtml(currentLang() === 'en' ? 'Platform' : '平台')}</span><select data-hypit-slot="${escapeHtml(slot)}" data-hypit-provider="${escapeHtml(slot)}">${providerOptions}</select></label><label><span>${escapeHtml(currentLang() === 'en' ? 'Run mode' : '运行模式')}</span><select data-hypit-slot="${escapeHtml(slot)}" data-hypit-variant="${escapeHtml(slot)}">${variantOptionsHtml}</select></label></div></div>`
            : `<div class="hypit-empty">${escapeHtml(!state.loaded && !state.loadError ? '' : noCandidateMessage(slot))}</div>`;
        const apiDisabled = !models.length && source !== 'workflow' && current.selection_kind !== 'workflow';
        return `<section class="hypit-slot-card${apiDisabled ? ' is-disabled' : ''}" data-hypit-slot-card="${escapeHtml(slot)}" data-source-active="${escapeHtml(source)}"><div class="hypit-slot-head"><div><div class="hypit-slot-title">${escapeHtml(title)}</div></div><span class="hypit-slot-status ${status.className}"${status.title ? ` title="${status.title}"` : ''}>${escapeHtml(status.text)}</span></div><div class="hypit-source-switch" role="tablist"><button type="button" role="tab" data-hypit-source="api_model" data-hypit-slot="${escapeHtml(slot)}" aria-pressed="${source === 'api_model' ? 'true' : 'false'}" aria-selected="${source === 'api_model' ? 'true' : 'false'}">${escapeHtml(t('hypit.apiModels'))}</button><button type="button" role="tab" data-hypit-source="workflow" data-hypit-slot="${escapeHtml(slot)}" aria-pressed="${source === 'workflow' ? 'true' : 'false'}" aria-selected="${source === 'workflow' ? 'true' : 'false'}">${escapeHtml(t('hypit.workflowSource'))}</button></div><div class="hypit-source-panel" data-source-panel="api_model"${source === 'api_model' ? '' : ' hidden'}>${apiBody}${modelNote}</div><div class="hypit-source-panel" data-source-panel="workflow"${source === 'workflow' ? '' : ' hidden'}>${renderWorkflowPanel(slot)}${workflowNote}</div></section>`;
    }

    function updateSlotStatus(slot) {
        const card = [...(slotsEl?.querySelectorAll('[data-hypit-slot-card]') || [])]
            .find(item => item.dataset.hypitSlotCard === slot);
        if (!card) return;
        const current = state.settings.defaults[slot] || emptySlot();
        const models = enabledModels(slot);
        const selectedModel = modelForSelection(models, current);
        const status = slotStatus(slot, current, models, selectedModel);
        const statusNode = card.querySelector('.hypit-slot-status');
        if (statusNode) {
            statusNode.textContent = status.text;
            statusNode.className = `hypit-slot-status ${status.className}`.trim();
            if (status.title) statusNode.title = status.title;
            else statusNode.removeAttribute('title');
        }
        const oldNote = card.querySelector('.hypit-slot-description');
        const noteMarkup = current.selection_kind === 'workflow'
            ? selectedWorkflowNote(slot, current)
            : (current.provider && current.model && !selectedModel ? selectedModelNote(slot, current) : '');
        if (noteMarkup) {
            const holder = document.createElement('div');
            holder.innerHTML = noteMarkup;
            const note = holder.firstElementChild;
            if (oldNote) oldNote.replaceWith(note);
            else if (current.selection_kind === 'workflow' && card.querySelector('[data-source-panel="workflow"]')) {
                card.querySelector('[data-source-panel="workflow"]').append(note);
            } else if (card.querySelector('.hypit-model-config')) card.querySelector('.hypit-model-config').insertAdjacentElement('afterend', note);
            else card.append(note);
        } else {
            oldNote?.remove();
        }
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
                    if (state.catalogStale || state.loading) {
                        return Promise.reject(new Error(t('hypit.refreshing')));
                    }
                    const picked = options.find(option => option.option_id === payload.selection.optionId);
                    if (!picked) return Promise.reject(new Error('选择不属于当前槽位'));
                    const previousSelection = clone(state.settings.defaults[slot] || emptySlot());
                    const attemptId = ++state.selectionAttemptId;
                    state.selectionAttempts[slot] = attemptId;
                const attemptedSelection = {
                    selection_kind: 'api_model',
                    provider: picked.connection_id || '',
                    model: picked.catalog_model_id || '',
                    region: normalizeRegion(picked.region_id),
                    parameters: {}
                };
                state.settings.defaults[slot] = attemptedSelection;
                selectSlotSource(slot, 'api_model');
                return markDirty({ waitForSave: true }).then(() => {
                        // 保存响应会重建 defaults 对象；比较槽位身份和值，不能用对象引用挡掉成功后的状态刷新。
                        if (state.selectionAttempts[slot] !== attemptId
                            || !sameSelection(state.settings.defaults[slot], attemptedSelection)) return;
                        updateSlotStatus(slot);
                    }).catch(error => {
                        // 失败后撤回本次未保存值，避免另一个槽位的后续保存把它悄悄带上。
                        // 同槽已有更新选择时，只回滚仍属于本次尝试的值，不覆盖新草稿。
                        if (state.selectionAttempts[slot] === attemptId
                            && sameSelection(state.settings.defaults[slot], attemptedSelection)) {
                            state.settings.defaults[slot] = clone(state.persistedDefaults[slot] || previousSelection);
                            updateSlotStatus(slot);
                        }
                        throw error;
                    });
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

    function workflowPanelFor(slot) {
        const card = [...(slotsEl?.querySelectorAll('[data-hypit-slot-card]') || [])]
            .find(item => item.dataset.hypitSlotCard === slot);
        return card?.querySelector('[data-source-panel="workflow"]') || null;
    }

    function renderWorkflowView(slot) {
        const panel = workflowPanelFor(slot);
        if (!panel) return;
        const current = state.settings.defaults[slot] || emptySlot();
        panel.innerHTML = `${renderWorkflowPanel(slot)}${current.selection_kind === 'workflow' ? selectedWorkflowNote(slot, current) : ''}`;
        refreshIcons();
    }

    function refreshWorkflowViews() {
        SLOTS.forEach(slot => {
            updateSlotStatus(slot);
            if (state.slotSources[slot] === 'workflow') renderWorkflowView(slot);
        });
    }

    function selectSlotSource(slot, source) {
        if (!SLOTS.includes(slot) || !['api_model', 'workflow'].includes(source)) return;
        state.slotSources[slot] = source;
        const card = [...(slotsEl?.querySelectorAll('[data-hypit-slot-card]') || [])]
            .find(item => item.dataset.hypitSlotCard === slot);
        if (card) {
            card.dataset.sourceActive = source;
            card.classList.toggle('is-disabled', !enabledModels(slot).length && source === 'api_model'
                && state.settings.defaults[slot]?.selection_kind !== 'workflow');
            card.querySelectorAll('[data-hypit-source]').forEach(button => {
                const active = button.dataset.hypitSource === source;
                button.setAttribute('aria-pressed', active ? 'true' : 'false');
                button.setAttribute('aria-selected', active ? 'true' : 'false');
            });
            card.querySelectorAll('[data-source-panel]').forEach(panel => {
                panel.hidden = panel.dataset.sourcePanel !== source;
            });
        }
        if (source === 'workflow') {
            renderWorkflowView(slot);
            void loadWorkflowOptions();
        }
    }

    function loadWorkflowOptions({ force = false } = {}) {
        if (state.workflowLoading) {
            if (force) state.workflowReloadAfterLoad = true;
            return state.workflowPromise || Promise.resolve(state.workflowOptions);
        }
        if (state.workflowLoaded && !force && !state.workflowStale) return Promise.resolve(state.workflowOptions);
        if (force && state.workflowLoaded) state.workflowStale = true;
        const requestSeq = ++state.workflowRequestSeq;
        const invalidationAtStart = state.workflowInvalidation;
        state.workflowLoading = true;
        state.workflowLoadError = '';
        refreshWorkflowViews();
        const promise = (async () => {
            let succeeded = false;
            try {
                const response = await fetch(`${API}/workflow-options`);
                const body = await responseJSON(response);
                if (requestSeq !== state.workflowRequestSeq) return;
                if (invalidationAtStart !== state.workflowInvalidation) {
                    state.workflowStale = true;
                    state.workflowReloadAfterLoad = true;
                    return;
                }
                state.workflowOptions = {
                    options: Array.isArray(body.options) ? body.options : [],
                    unavailable: Array.isArray(body.unavailable) ? body.unavailable : []
                };
                state.workflowLoaded = true;
                state.workflowStale = false;
                state.workflowLoadError = '';
                SLOTS.forEach(slot => {
                    const draft = state.workflowDrafts[slot];
                    if (!draft) return;
                    const latest = workflowOptionForSelection(draft.option);
                    if (!latest || latest.available !== true || latest.schema_status !== 'ready'
                        || latest.schema_fingerprint !== draft.option.schema_fingerprint) {
                        draft.invalidated = true;
                        return;
                    }
                    draft.option = latest;
                    draft.invalidated = false;
                });
                succeeded = true;
            } catch (error) {
                state.workflowLoadError = error?.message || String(error);
            } finally {
                if (requestSeq === state.workflowRequestSeq) {
                    state.workflowLoading = false;
                    state.workflowPromise = null;
                    refreshWorkflowViews();
                    const reload = state.workflowReloadAfterLoad || invalidationAtStart !== state.workflowInvalidation;
                    state.workflowReloadAfterLoad = false;
                    if (reload) queueMicrotask(() => { void loadWorkflowOptions({ force: true }); });
                }
            }
            return succeeded ? state.workflowOptions : null;
        })();
        state.workflowPromise = promise;
        return promise;
    }

    function invalidateWorkflowOptions() {
        state.workflowInvalidation += 1;
        state.workflowStale = true;
        const active = SLOTS.some(slot => state.slotSources[slot] === 'workflow'
            || state.settings.defaults[slot]?.selection_kind === 'workflow');
        if (state.workflowLoading) {
            state.workflowReloadAfterLoad = true;
            return;
        }
        if (active) void loadWorkflowOptions({ force: true });
    }

    function workflowFieldValue(draft, field) {
        if (Object.prototype.hasOwnProperty.call(draft.fieldValues, field.key)) return draft.fieldValues[field.key];
        return field.default;
    }

    function workflowDraftSelection(slot, draft) {
        const option = draft.option;
        const inputBindings = workflowBindings(draft);
        const fieldValues = {};
        for (const field of option.fields || []) {
            if (draft.fieldRoles[field.key] || !['text', 'number', 'boolean', 'select'].includes(field.type)) continue;
            const value = workflowFieldValue(draft, field);
            if (value !== undefined && value !== null && value !== '') fieldValues[field.key] = value;
        }
        return {
            selection_kind: 'workflow',
            source: option.source,
            provider_id: option.provider_id,
            region: normalizeRegion(option.region),
            item_id: option.item_id,
            expected_slot: slot,
            expected_kind: WORKFLOW_OUTPUT_KINDS[slot],
            confirmed_for_slot: true,
            schema_fingerprint: option.schema_fingerprint,
            input_bindings: inputBindings,
            field_values: fieldValues,
            parameters: {}
        };
    }

    async function confirmWorkflowForSlot(slot) {
        const draft = workflowDraftFor(slot);
        const validation = workflowDraftValidation(draft);
        if (validation || !draft || state.workflowStale || state.workflowLoading) return false;
        const attemptedSelection = workflowDraftSelection(slot, draft);
        const previousSelection = clone(state.settings.defaults[slot] || emptySlot());
        const attemptId = ++state.selectionAttemptId;
        const draftRevision = draft.revision;
        state.workflowAttempts[slot] = { attemptId, saving: true };
        state.selectionAttempts[slot] = attemptId;
        state.settings.defaults[slot] = attemptedSelection;
        state.slotSources[slot] = 'workflow';
        selectSlotSource(slot, 'workflow');
        renderWorkflowView(slot);
        try {
            await markDirty({ waitForSave: true });
            if (state.workflowAttempts[slot]?.attemptId !== attemptId
                || !sameWorkflow(state.settings.defaults[slot], attemptedSelection)) return true;
            state.workflowAttempts[slot] = { attemptId, saving: false };
            if (draft.revision === draftRevision && state.workflowDrafts[slot] === draft) {
                delete state.workflowDrafts[slot];
            }
            updateSlotStatus(slot);
            renderWorkflowView(slot);
            return true;
        } catch (error) {
            if (state.workflowAttempts[slot]?.attemptId === attemptId
                && sameWorkflow(state.settings.defaults[slot], attemptedSelection)) {
                state.settings.defaults[slot] = clone(state.persistedDefaults[slot] || previousSelection);
            }
            if (state.workflowAttempts[slot]?.attemptId === attemptId) {
                state.workflowAttempts[slot] = { attemptId, saving: false };
                draft.error = error?.message || String(error);
                updateSlotStatus(slot);
                renderWorkflowView(slot);
            }
            return false;
        }
    }

    function workflowRoleChanged(slot, fieldKey, role) {
        const draft = workflowDraftFor(slot);
        if (!draft || !draft.option.fields.some(field => field.key === fieldKey)) return;
        if (role) draft.fieldRoles[fieldKey] = role;
        else delete draft.fieldRoles[fieldKey];
        draft.error = '';
        draft.revision += 1;
        renderWorkflowView(slot);
        const select = workflowPanelFor(slot)?.querySelector(`[data-workflow-role][data-field-key="${CSS.escape(fieldKey)}"]`);
        select?.focus();
    }

    function parseWorkflowFieldValue(field, value) {
        if (value === '') return '';
        if (field.type === 'boolean') return value === true || value === 'true';
        if (field.type === 'select') {
            try { return JSON.parse(value); } catch (_) { return value; }
        }
        if (field.type === 'number') return Number(value);
        return value;
    }

    function updateWorkflowValidation(slot) {
        const draft = workflowDraftFor(slot);
        const panel = workflowPanelFor(slot);
        const message = workflowDraftValidation(draft);
        const validation = panel?.querySelector('[data-workflow-validation]');
        const confirm = panel?.querySelector('[data-workflow-confirm]');
        if (validation) validation.textContent = message;
        if (confirm) confirm.disabled = Boolean(message) || state.workflowAttempts[slot]?.saving === true
            || state.workflowStale || state.workflowLoading;
    }

    function workflowSourcesChanged(value) {
        // 新版设置页没有旧六槽卡片；这些事件只通知共享画布刷新自己的候选。
        // 避免旧卡片链在后台重新读取 defaults 并与专用画布形成第二份状态。
        if (!slotsEl) return;
        const message = typeof value === 'string' ? { type: value } : (value || {});
        const type = message.type;
        if (!['providers-changed', 'workflows-changed', 'comfy-instances-changed'].includes(type)) return;
        const eventKey = `${type}:${message.updated_at || ''}`;
        if (message.updated_at && state.lastWorkflowSourceChangeKey === eventKey) return;
        state.lastWorkflowSourceChangeKey = eventKey;
        if (type === 'providers-changed') invalidateCatalog();
        invalidateWorkflowOptions();
    }

    function markDirty(options = {}) {
        state.draftVersion += 1;
        state.dirty = true;
        scheduleAutosave();
        if (!options.waitForSave) return Promise.resolve();
        return new Promise((resolve, reject) => {
            state.saveWaiters.push({ version: state.draftVersion, resolve, reject });
        });
    }

    function scheduleAutosave(delay = AUTOSAVE_DELAY) {
        if (state.saveTimer) clearTimeout(state.saveTimer);
        state.saveTimer = setTimeout(() => {
            state.saveTimer = null;
            save().catch(() => {});
        }, delay);
    }

    function settleSaveWaiters(throughVersion, error) {
        const waiting = [];
        state.saveWaiters.forEach(waiter => {
            if (waiter.version <= throughVersion) {
                if (error) waiter.reject(error);
                else waiter.resolve({ savedVersion: waiter.version });
            } else {
                waiting.push(waiter);
            }
        });
        state.saveWaiters = waiting;
    }

    function load({ force = false } = {}) {
        if (state.loading) {
            if (force) state.reloadAfterLoad = true;
            return state.loadPromise || Promise.resolve();
        }
        if (state.loaded && !force && !state.catalogStale) return Promise.resolve(state.catalog);

        const invalidationAtStart = state.providerInvalidation;
        const draftVersionAtStart = state.draftVersion;
        const hadLoadedData = state.loaded;
        state.loading = true;
        state.loadError = '';
        if (hadLoadedData) {
            state.catalogStale = true;
            slotsEl?.setAttribute('inert', '');
        } else {
            slotsEl?.replaceChildren();
        }
        if (layout?.classList.contains('hypit-settings-mode')) {
            setStatus(t(hadLoadedData ? 'hypit.refreshing' : 'hypit.loading'));
        }

        let succeeded = false;
        const promise = (async () => {
            try {
                const [capabilityResponse, settingsResponse] = await Promise.all([
                    fetch(`${API}/capabilities`),
                    fetch(settingsURL)
                ]);
                const [capabilities, settings] = await Promise.all([
                    responseJSON(capabilityResponse), responseJSON(settingsResponse)
                ]);
                if (invalidationAtStart !== state.providerInvalidation) {
                    // 平台配置在读取中改变：丢弃旧快照，串行重读，不能回滚到旧候选。
                    state.catalogStale = true;
                    state.reloadAfterLoad = true;
                    return;
                }
                state.catalog = {
                    ...capabilities,
                    providers: Array.isArray(capabilities?.providers) ? capabilities.providers : [],
                    options: Array.isArray(capabilities?.options) ? capabilities.options : [],
                    catalog_revision: capabilities?.catalog_revision || ''
                };
                state.capabilities = Array.isArray(capabilities?.supported_capabilities)
                    ? capabilities.supported_capabilities : [];
                state.unsupported = Array.isArray(capabilities?.unsupported_capabilities)
                    ? capabilities.unsupported_capabilities : [];
                if (state.draftVersion === draftVersionAtStart && !state.dirty) {
                    state.settings = settings;
                    ensureDefaults();
                    state.persistedDefaults = clone(state.settings.defaults || {});
                }
                state.loaded = true;
                state.catalogStale = false;
                succeeded = true;
            } catch (error) {
                state.loadError = error?.message || String(error);
            } finally {
                state.loading = false;
                const needsAnotherRead = state.reloadAfterLoad
                    || invalidationAtStart !== state.providerInvalidation;
                state.reloadAfterLoad = false;
                if (needsAnotherRead) {
                    state.catalogStale = state.loaded;
                    if (state.loaded) slotsEl?.setAttribute('inert', '');
                    if (layout?.classList.contains('hypit-settings-mode')) {
                        setStatus(t(state.loaded ? 'hypit.refreshing' : 'hypit.loading'));
                    }
                } else if (succeeded) {
                    state.catalogStale = false;
                    slotsEl?.removeAttribute('inert');
                    if (layout?.classList.contains('hypit-settings-mode')) {
                        render();
                        setStatus(t('hypit.loaded'), 'success');
                    }
                    if (SLOTS.some(slot => state.settings.defaults[slot]?.selection_kind === 'workflow')) {
                        void loadWorkflowOptions();
                    }
                } else if (state.loaded) {
                    slotsEl?.setAttribute('inert', '');
                    if (layout?.classList.contains('hypit-settings-mode')) {
                        setStatus(t('hypit.loadError', { message: state.loadError || t('hypit.loading') }), 'error');
                    }
                } else {
                    slotsEl?.replaceChildren();
                    if (layout?.classList.contains('hypit-settings-mode') && state.loadError) {
                        setStatus(t('hypit.loadError', { message: state.loadError }), 'error');
                    }
                }
                state.loadPromise = null;
                if (needsAnotherRead) queueMicrotask(() => { void load({ force: true }); });
            }
        })();
        state.loadPromise = promise;
        return promise;
    }

    function invalidateCatalog() {
        state.providerInvalidation += 1;
        state.catalogStale = true;
        state.loadError = '';
        if (state.loaded) slotsEl?.setAttribute('inert', '');
        if (layout?.classList.contains('hypit-settings-mode')) {
            setStatus(t(state.loaded ? 'hypit.refreshing' : 'hypit.loading'));
        }
        if (state.loading) {
            state.reloadAfterLoad = true;
            return;
        }
        void load({ force: true });
    }

    async function save() {
        // 旧保存入口保留给独立回归夹具兼容；真实 API 设置页已不再挂载六槽表单，
        // 因此该入口不得再写入旧 Hypit defaults。
        if (!slotsEl) return false;
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
                state.persistedDefaults = clone(saved.defaults || snapshot.defaults);
                state.settings = {
                    ...saved,
                    defaults: changedDuringRequest ? localDefaults : saved.defaults
                };
                ensureDefaults();
                state.savedVersion = Math.max(state.savedVersion, snapshot.draftVersion);
                settleSaveWaiters(snapshot.draftVersion);
                if (!changedDuringRequest) {
                    state.dirty = false;
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
                settleSaveWaiters(snapshot.draftVersion, error);
                throw error;
            } finally {
                state.saving = false;
                state.savePromise = null;
                if (state.dirty && state.draftVersion !== snapshot.draftVersion) scheduleAutosave(0);
            }
        })();
        return state.savePromise;
    }

    function open() {
        settingsCanvasController.deactivate();
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
        syncEditorHeader();
        settingsCanvasController.activate();
        void loadSettingsCanvas();
    }

    function close(options = {}) {
        settingsCanvasController.deactivate();
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
                if(!target.value){state.settings.defaults[slot]=emptySlot();state.slotSources[slot]='api_model';renderSlotInPlace(slot);mountSlotControls();markDirty();return;}
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
            state.slotSources[slot] = 'api_model';
            renderSlotInPlace(slot);
            mountSlotControls();
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

    function onWorkflowFieldChange(event) {
        const target = event.target;
        if (target.matches('[data-workflow-role]')) {
            workflowRoleChanged(target.dataset.hypitSlot, target.dataset.fieldKey, target.value);
            return true;
        }
        if (!target.matches('[data-workflow-value]')) return false;
        const slot = target.dataset.hypitSlot;
        const draft = workflowDraftFor(slot);
        const field = draft?.option.fields?.find(item => item.key === target.dataset.fieldKey);
        if (!draft || !field) return true;
        draft.fieldValues[field.key] = parseWorkflowFieldValue(field, target.value);
        draft.error = '';
        draft.revision += 1;
        updateWorkflowValidation(slot);
        return true;
    }

    function onWorkflowFieldInput(event) {
        const target = event.target;
        if (!target.matches('[data-workflow-value]')) return false;
        const slot = target.dataset.hypitSlot;
        const draft = workflowDraftFor(slot);
        const field = draft?.option.fields?.find(item => item.key === target.dataset.fieldKey);
        if (!draft || !field) return true;
        draft.fieldValues[field.key] = parseWorkflowFieldValue(field, target.value);
        draft.error = '';
        draft.revision += 1;
        updateWorkflowValidation(slot);
        return true;
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
    window.deactivateHypitSettingsCanvasController = () => settingsCanvasController.deactivate();
    window.prefetchHypitSettings = prefetchSettingsCanvasBootstrap;
    window.reloadHypitSettings = () => loadSettingsCanvas({force:true});
    window.openHypitSettingsCanvasEditor = openSettingsCanvasInNewTab;
    window.resetHypitSettingsCanvas = resetSettingsCanvas;
    window.saveHypitSettings = save;

    settingsCanvasResetButton?.addEventListener('click', () => { void resetSettingsCanvas(); });
    settingsCanvasNewTabButton?.addEventListener('click', openSettingsCanvasInNewTab);
    settingsCanvasFrame?.addEventListener('load', syncSettingsCanvasFrameContext);

    slotsEl?.addEventListener('click', event=>{
        const sourceButton = event.target.closest('[data-hypit-source]');
        if (sourceButton) {
            selectSlotSource(sourceButton.dataset.hypitSlot, sourceButton.dataset.hypitSource);
            return;
        }
        const retry = event.target.closest('[data-workflow-retry]');
        if (retry) {
            void loadWorkflowOptions({ force: true });
            return;
        }
        const candidateButton = event.target.closest('[data-workflow-option-id]');
        if (candidateButton) {
            const slot = candidateButton.dataset.hypitSlot;
            const option = allWorkflowOptions().find(item => (item.id || workflowIdentityKey(item)) === candidateButton.dataset.workflowOptionId);
            if (!option || option.available !== true || option.enabled !== true || option.schema_status !== 'ready'
                || state.workflowStale || state.workflowLoading) return;
            workflowDraftFromOption(slot, option);
            state.slotSources[slot] = 'workflow';
            renderWorkflowView(slot);
            return;
        }
        const confirm = event.target.closest('[data-workflow-confirm]');
        if (confirm) {
            void confirmWorkflowForSlot(confirm.dataset.workflowConfirm);
            return;
        }
        const target=event.target.closest('[data-hypit-choice]');if(!target)return;
        const current=state.settings.defaults[target.dataset.hypitSlot];
        if(target.dataset.value==='')delete current.parameters[target.dataset.hypitChoice];
        else current.parameters[target.dataset.hypitChoice]=JSON.parse(target.dataset.value);
        renderSlotInPlace(target.dataset.hypitSlot);
        markDirty();
    });
    slotsEl?.addEventListener('change', event => {
        if (onWorkflowFieldChange(event)) return;
        onSlotChange(event);
    });
    slotsEl?.addEventListener('input', event => {
        if (onWorkflowFieldInput(event)) return;
        onSlotChange(event);
    });
    document.addEventListener('click', handleHypitNavigationCapture, true);
    window.addEventListener('studio-api-change', event => workflowSourcesChanged(event.detail));
    window.addEventListener('message', event => {
        if (event.origin !== location.origin || (event.source !== window.parent && event.source !== window.top)) return;
        workflowSourcesChanged(event.data);
    });
    try {
        if (window === globalThis && typeof BroadcastChannel === 'function') {
            const studioApiChannel = new BroadcastChannel('studio-api');
            studioApiChannel.addEventListener('message', event => workflowSourcesChanged(event.data));
            studioApiChannel.unref?.();
        }
    } catch (_) {}
    window.addEventListener('studio-lang-change', () => {
        syncEditorHeader();
        syncSettingsCanvasFrameContext();
    });
    window.addEventListener('load', () => {
        // 预取专用画布 bootstrap；点击 Hypit 时共享这一响应，再挂载唯一编辑 iframe。
        void prefetchSettingsCanvasBootstrap();
        // Hypit 通过专用画布懒加载；不再读取旧的模型卡片配置链。
        if (new URLSearchParams(location.search).get('section') === 'hypit') {
            open();
        }
    });
})();
