let providers = [];
let selectedId = '';
let modelCapabilityCatalog = {providers:[]};
const providerList = document.getElementById('providerList');
const cliProviderList = document.getElementById('cliProviderList');
const editorTitle = document.getElementById('editorTitle');
const editorSub = document.getElementById('editorSub');
const statusEl = document.getElementById('status');
const nameInput = document.getElementById('nameInput');
const idInput = document.getElementById('idInput');
const baseInput = document.getElementById('baseInput');
const protocolInput = document.getElementById('protocolInput');
const imageRequestModeInput = document.getElementById('imageRequestModeInput');
const imageEditRouteInput = document.getElementById('imageEditRouteInput');
const keyInput = document.getElementById('keyInput');
const keyHint = document.getElementById('keyHint');
const volcArkKeyHint = document.getElementById('volcArkKeyHint');
const volcAkInput = document.getElementById('volcAkInput');
const volcSkInput = document.getElementById('volcSkInput');
const volcAssetKeyHint = document.getElementById('volcAssetKeyHint');
const volcProjectInput = document.getElementById('volcProjectInput');
const volcRegionInput = document.getElementById('volcRegionInput');
const jimengCliPanel = document.getElementById('jimengCliPanel');
const jimengCliStatus = document.getElementById('jimengCliStatus');
const jimengCredit = document.getElementById('jimengCredit');
const jimengLoginBox = document.getElementById('jimengLoginBox');
const jimengHelpOverlay = document.getElementById('jimengHelpOverlay');
const jimengHelpCommand = document.getElementById('jimengHelpCommand');
const jimengHelpOutput = document.getElementById('jimengHelpOutput');
const codexCliPanel = document.getElementById('codexCliPanel');
const codexCliStatus = document.getElementById('codexCliStatus');
const codexCliInfo = document.getElementById('codexCliInfo');
const codexHelpOverlay = document.getElementById('codexHelpOverlay');
const codexHelpCommand = document.getElementById('codexHelpCommand');
const codexHelpOutput = document.getElementById('codexHelpOutput');
const geminiCliPanel = document.getElementById('geminiCliPanel');
const geminiCliStatus = document.getElementById('geminiCliStatus');
const geminiCliInfo = document.getElementById('geminiCliInfo');
const geminiCliHelpOverlay = document.getElementById('geminiCliHelpOverlay');
const geminiCliHelpCommand = document.getElementById('geminiCliHelpCommand');
const geminiCliHelpOutput = document.getElementById('geminiCliHelpOutput');
const runninghubConfigBlock = document.getElementById('runninghubConfigBlock');
const rhGlobalAppsList = document.getElementById('rhGlobalAppsList');
const rhCnAppsList = document.getElementById('rhCnAppsList');
const rhGlobalAppsCount = document.getElementById('rhGlobalAppsCount');
const rhCnAppsCount = document.getElementById('rhCnAppsCount');
const rhWorkflowsList = document.getElementById('rhWorkflowsList');
const rhWorkflowsCount = document.getElementById('rhWorkflowsCount');
const runningHubModelRegionTabs = document.getElementById('runningHubModelRegionTabs');
const settingsContent = document.getElementById('settingsContent');
const providerSettingsView = document.getElementById('providerSettingsView');
const canvasModelSettingsBlock = document.getElementById('canvasModelSettingsBlock');
const canvasModelProviderSelect = document.getElementById('canvasModelProviderSelect');
const comfyuiSettingsBlock = document.getElementById('comfyuiSettingsBlock');
const comfyuiSubnav = document.getElementById('comfyuiSubnav');
const localComfyuiNav = document.getElementById('localComfyuiNav');
const runningHubComfyuiNav = document.getElementById('runningHubComfyuiNav');
const comfyuiLocalSection = document.getElementById('comfyuiLocalSection');
const recommendContent = document.getElementById('recommendContent');
const recommendPanel = document.getElementById('recommendPanel');
const providerOnboardingCard = document.getElementById('providerOnboardingCard');
const customProviderGuide = document.getElementById('customProviderGuide');
const rhWorkflowEditorOverlay = document.getElementById('rhWorkflowEditorOverlay');
const rhWorkflowEditorTitle = document.getElementById('rhWorkflowEditorTitle');
const rhWorkflowEditorSub = document.getElementById('rhWorkflowEditorSub');
const rhWorkflowEditName = document.getElementById('rhWorkflowEditName');
const rhWorkflowEditNote = document.getElementById('rhWorkflowEditNote');
const rhWorkflowEditorSummary = document.getElementById('rhWorkflowEditorSummary');
const rhWorkflowEditorNodeList = document.getElementById('rhWorkflowEditorNodeList');
const rhWorkflowEditorGraphWrap = document.getElementById('rhWorkflowEditorGraphWrap');
let rhWorkflowEditorGraphSvg = document.getElementById('rhWorkflowEditorGraphSvg');
let rhWorkflowEditorZoom = document.getElementById('rhWorkflowEditorZoom');
const imageModelList = document.getElementById('imageModelList');
const chatModelList = document.getElementById('chatModelList');
const videoModelList = document.getElementById('videoModelList');
const audioModelList = document.getElementById('audioModelList');
const musicModelList = document.getElementById('musicModelList');
const msLoraBlock = document.getElementById('msLoraBlock');
const msLoraList = document.getElementById('msLoraList');
const recommendApiOverlay = document.getElementById('recommendApiOverlay');
const recommendApiList = document.getElementById('recommendApiList');
const VOLCENGINE_DEFAULT_BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3';
const VOLCENGINE_DEFAULT_PROJECT_NAME = 'default';
const VOLCENGINE_DEFAULT_REGION = 'cn-beijing';
const AI_MONEY_DEFAULT_BASE_URL = 'https://api.lao-hu.com';
const AI_MONEY_REGISTER_URL = 'https://api.lao-hu.com/sign-up?aff=460d';
const AI_MONEY_HOME_URL = 'https://api.lao-hu.com/';
const AGNES_DEFAULT_BASE_URL = 'https://apihub.agnes-ai.com/v1';
const AGNES_REGISTER_URL = 'https://platform.agnes-ai.com/settings/apiKeys';
const MS_BUILTIN_IMAGE_MODELS = [
    'Tongyi-MAI/Z-Image-Turbo',
    'Qwen/Qwen-Image-2512',
    'Qwen/Qwen-Image-Edit-2511',
    'black-forest-labs/FLUX.2-klein-9B'
];
const MS_DEFAULT_BASE_URL = 'https://api-inference.modelscope.cn/v1';
const RH_DEFAULT_BASE_URL = 'https://www.runninghub.ai';
const RUNNINGHUB_REGIONS = {
    cn: {
        baseUrl:'https://www.runninghub.cn',
        consumerUrl:'https://www.runninghub.cn/enterprise-api/consumerApi?inviteCode=rh-v1001',
        walletUrl:'https://www.runninghub.cn/enterprise-api/sharedApi?inviteCode=rh-v1001'
    },
    global: {
        baseUrl:'https://www.runninghub.ai',
        consumerUrl:'https://www.runninghub.ai/enterprise-api/consumerApi?inviteCode=rh-v1001',
        walletUrl:'https://www.runninghub.ai/enterprise-api/sharedApi?inviteCode=rh-v1001'
    }
};
const RUNNINGHUB_REGION_UI = {
    global: {
        enabled: 'rhGlobalEnabledInput',
        free: 'rhGlobalFreeKeyInput',
        wallet: 'rhGlobalWalletKeyInput',
        freeHint: 'rhGlobalFreeKeyHint',
        walletHint: 'rhGlobalWalletKeyHint',
        paste: 'rhGlobalPasteInput',
        apps: 'rhGlobalAppsList',
        count: 'rhGlobalAppsCount'
    },
    cn: {
        enabled: 'rhCnEnabledInput',
        free: 'rhCnFreeKeyInput',
        wallet: 'rhCnWalletKeyInput',
        freeHint: 'rhCnFreeKeyHint',
        walletHint: 'rhCnWalletKeyHint',
        paste: 'rhCnPasteInput',
        apps: 'rhCnAppsList',
        count: 'rhCnAppsCount'
    }
};
function runningHubRegionUi(region, part){
    const ids = RUNNINGHUB_REGION_UI[region];
    return ids?.[part] ? document.getElementById(ids[part]) : null;
}
function runningHubRegionInput(region, kind){
    return runningHubRegionUi(region, kind === 'wallet' ? 'wallet' : 'free');
}
function runningHubRegionEnabledInput(region){
    return runningHubRegionUi(region, 'enabled');
}
function runningHubRegionAppInput(region){
    return runningHubRegionUi(region, 'paste');
}
let rhAppSyncState = null;
let comfyuiSettingsMode = false;
let comfyuiSettingsSection = 'local';
let apiSettingsSection = 'connections';
let canvasModelCategory = 'all';
let runningHubModelRegion = '';
const API_AUTOSAVE_DELAY = 360;
const HIDDEN_PROVIDER_IDS = new Set(['agnes', 'openai-compatible', 'modelscope', 'volcengine']);
const HIDDEN_RECOMMENDED_API_IDS = HIDDEN_PROVIDER_IDS;
const apiAutosavePendingByKey = new Map();
const apiAutosaveTimersByKey = new Map();
const apiAutosaveObjectRevision = new Map();
const apiAutosaveDirtyObjects = new Set();
const apiAutosaveInFlightByKey = new Map();
let apiAutosaveSerial = Promise.resolve();
let apiAutosaveLastWriteRevision = 0;
let apiAutosaveRevision = 0;
let apiNavigationCaptureInProgress = false;
let apiClosingHypitSettings = false;

function closeHypitSettingsForApiNavigation(){
    if(apiClosingHypitSettings) return;
    const layout = document.querySelector('.layout');
    if(!layout?.classList?.contains('hypit-settings-mode')) return;
    if(typeof window.closeHypitSettings !== 'function') return;
    apiClosingHypitSettings = true;
    try {
        // 切换只更新右侧内容，递归保护避免重复进入。
        window.closeHypitSettings({deferEditor:true});
    } finally {
        apiClosingHypitSettings = false;
    }
}

function apiAutosaveRegion(item, region=''){
    if(item?.id !== 'runninghub') return '';
    return String(region || runningHubRegionFromItem(item) || 'global');
}

function apiAutosaveObjectKey(providerId, region=''){
    return `${String(providerId || '')}::${String(region || '')}`;
}

function cloneApiSettingsValue(value){
    return value == null ? value : JSON.parse(JSON.stringify(value));
}

function captureApiAutosaveDraft(item, region='', revision=apiAutosaveRevision){
    if(!item) return null;
    const resolvedRegion = apiAutosaveRegion(item, region);
    const objectId = apiAutosaveObjectKey(item.id, resolvedRegion);
    const objectRevision = (apiAutosaveObjectRevision.get(objectId) || 0) + 1;
    apiAutosaveObjectRevision.set(objectId, objectRevision);
    return {
        objectId,
        providerId:item.id,
        region:resolvedRegion,
        revision,
        objectRevision,
        providers:cloneApiSettingsValue(providers)
    };
}

function captureApiObjectBeforeNavigation({immediate=true}={}){
    if(apiNavigationCaptureInProgress) return Promise.resolve(false);
    if(rhWorkflowEditorState?.open) closeRhWorkflowEditor();
    const item = provider();
    if(!item) return Promise.resolve(false);
    apiNavigationCaptureInProgress = true;
    try {
        syncEditor();
        const objectId = apiAutosaveObjectKey(item.id, apiAutosaveRegion(item));
        if(!apiAutosaveDirtyObjects.has(objectId)) return Promise.resolve(false);
        if(!apiAutosavePendingByKey.has(objectId) && apiAutosaveInFlightByKey.has(objectId)){
            return apiAutosaveSerial;
        }
        return scheduleProviderAutosave({
            providerId:item.id,
            region:apiAutosaveRegion(item),
            immediate,
            sync:false,
        });
    } finally {
        apiNavigationCaptureInProgress = false;
    }
}

function clearProviderAutosaveTimer(objectId){
    const timer = apiAutosaveTimersByKey.get(objectId);
    if(timer) clearTimeout(timer);
    apiAutosaveTimersByKey.delete(objectId);
}

function discardProviderAutosave(providerId, region=''){
    const objectId = apiAutosaveObjectKey(providerId, region);
    clearProviderAutosaveTimer(objectId);
    apiAutosavePendingByKey.delete(objectId);
    apiAutosaveDirtyObjects.delete(objectId);
    apiAutosaveObjectRevision.set(objectId, (apiAutosaveObjectRevision.get(objectId) || 0) + 1);
    apiAutosaveRevision += 1;
}

function latestApiAutosaveDraft(objectId){
    return apiAutosavePendingByKey.get(objectId) || null;
}

function flushProviderAutosave(objectId, waitForWrite=false){
    clearProviderAutosaveTimer(objectId);
    const draft = latestApiAutosaveDraft(objectId);
    if(!draft) return waitForWrite ? apiAutosaveSerial : Promise.resolve(false);
    apiAutosavePendingByKey.delete(objectId);
    const write = apiAutosaveSerial.then(() => {
        apiAutosaveInFlightByKey.set(objectId, draft);
        return saveProviders(draft);
    }).finally(() => {
        if(apiAutosaveInFlightByKey.get(objectId) === draft) apiAutosaveInFlightByKey.delete(objectId);
    });
    // 队列失败后必须恢复可写状态；失败本身由 saveProviders 设置草稿失败状态。
    apiAutosaveSerial = write.catch(() => false);
    return waitForWrite ? apiAutosaveSerial : write;
}

function scheduleProviderAutosave({providerId='', region='', immediate=false, sync=true}={}){
    if(sync) syncEditor();
    const item = providers.find(candidate => candidate?.id === providerId) || provider();
    if(!item) return Promise.resolve(false);
    const resolvedRegion = apiAutosaveRegion(item, region);
    const objectId = apiAutosaveObjectKey(item.id, resolvedRegion);
    const revision = ++apiAutosaveRevision;
    const draft = captureApiAutosaveDraft(item, resolvedRegion, revision);
    apiAutosaveDirtyObjects.add(objectId);
    apiAutosavePendingByKey.set(objectId, draft);
    clearProviderAutosaveTimer(objectId);
    setStatus(tr('api.autosaving') || tr('api.saving'));
    if(immediate) return flushProviderAutosave(objectId, true);
    const timer = setTimeout(() => {
        apiAutosaveTimersByKey.delete(objectId);
        void flushProviderAutosave(objectId, false);
    }, API_AUTOSAVE_DELAY);
    apiAutosaveTimersByKey.set(objectId, timer);
    return Promise.resolve(true);
}

function scheduleCurrentProviderAutosave(immediate=false){
    const item = provider();
    if(!item) return Promise.resolve(false);
    return scheduleProviderAutosave({
        providerId:item.id,
        region:apiAutosaveRegion(item),
        immediate,
    });
}

function isCliProvider(item){
    return CLI_PROTOCOLS.has(String(item?.protocol || '').toLowerCase());
}
function syncApiSettingsView(){
    const models = !comfyuiSettingsMode && apiSettingsSection === 'models';
    const connections = !comfyuiSettingsMode && !models;
    if(providerSettingsView) providerSettingsView.hidden = models;
    if(canvasModelSettingsBlock) canvasModelSettingsBlock.hidden = !models;
    document.getElementById('canvasModelsNav')?.classList.toggle('active', models);
}
function setApiSettingsSection(section='connections'){
    void captureApiObjectBeforeNavigation({immediate:true});
    closeHypitSettingsForApiNavigation();
    if(comfyuiSettingsMode) closeComfyUiSettings();
    apiSettingsSection = section === 'models' ? 'models' : 'connections';
    if(apiSettingsSection === 'models') canvasModelCategory = 'all';
    syncApiSettingsView();
    renderEditor();
    refreshIcons();
}
function selectCanvasModelProvider(id){
    const next = visibleProviders().find(item => item.id === id);
    if(!next) return;
    void captureApiObjectBeforeNavigation({immediate:true});
    clearFetchedModelState();
    selectedId = next.id;
    apiSettingsSection = 'models';
    syncApiSettingsView();
    renderEditor();
}
function selectCanvasModelCategory(category='all'){
    const allowed = new Set(['all','text','image','video','audio','music']);
    canvasModelCategory = allowed.has(category) ? category : 'all';
    document.querySelectorAll('.canvas-model-category-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.cat === canvasModelCategory);
    });
    document.querySelectorAll('.canvas-model-category').forEach(block => {
        block.hidden = canvasModelCategory !== 'all' && block.dataset.modelCategory !== canvasModelCategory;
    });
}
function syncCanvasModelCategoryAvailability(item=provider()){
    // 只有 GPT CLI 被项目契约限定为文本；即梦等 CLI 的图片/视频能力仍按已有模型白名单展示。
    const textOnly = String(item?.protocol || '').toLowerCase() === 'codex' || String(item?.id || '').toLowerCase() === 'codex';
    document.querySelectorAll('.canvas-model-category-tab').forEach(tab => {
        const restricted = textOnly && !['all','text'].includes(tab.dataset.cat);
        tab.hidden = restricted;
    });
    if(textOnly && !['all','text'].includes(canvasModelCategory)) canvasModelCategory = 'text';
}
function syncComfyUiNavigation(){
    const local = comfyuiSettingsMode && comfyuiSettingsSection === 'local';
    const runninghub = comfyuiSettingsMode && comfyuiSettingsSection === 'runninghub';
    comfyuiSubnav?.classList.toggle('active', comfyuiSettingsMode);
    localComfyuiNav?.classList.toggle('active', local);
    runningHubComfyuiNav?.classList.toggle('active', runninghub);
    localComfyuiNav?.setAttribute('aria-current', local ? 'page' : 'false');
    runningHubComfyuiNav?.setAttribute('aria-current', runninghub ? 'page' : 'false');
    if(comfyuiLocalSection) comfyuiLocalSection.hidden = !local;
    if(runninghubConfigBlock) runninghubConfigBlock.hidden = !runninghub;
}
function setComfyUiSection(section='local'){
    comfyuiSettingsSection = section === 'runninghub' ? 'runninghub' : 'local';
    if(comfyuiSettingsSection === 'runninghub'){
        const runningHub = providers.find(item => item.id === 'runninghub');
        if(runningHub) selectedId = 'runninghub';
    }
    syncComfyUiNavigation();
    renderEditor();
    refreshIcons();
}
function openComfyUiSettings(section='local'){
    void captureApiObjectBeforeNavigation({immediate:true});
    closeHypitSettingsForApiNavigation();
    comfyuiSettingsMode = true;
    providerSettingsView?.classList.add('comfyui-embedded-mode');
    if(comfyuiSettingsBlock) comfyuiSettingsBlock.hidden = false;
    syncApiSettingsView();
    document.querySelector('.api-page-delete-btn')?.setAttribute('hidden', 'hidden');
    renderProviderList();
    setComfyUiSection(section);
}
function closeComfyUiSettings(){
    comfyuiSettingsMode = false;
    providerSettingsView?.classList.remove('comfyui-embedded-mode');
    if(comfyuiSettingsBlock) comfyuiSettingsBlock.hidden = true;
    syncApiSettingsView();
    document.querySelector('.api-page-delete-btn')?.removeAttribute('hidden');
    syncComfyUiNavigation();
    renderEditor();
}
function setRhAppSyncState(nextState){
    rhAppSyncState = nextState;
    renderRunningHubCards();
}
function updateRhAppSyncPhase(phase){
    if(!rhAppSyncState) return;
    rhAppSyncState = {...rhAppSyncState, phase};
    renderRunningHubCards();
}
function runningHubRegionFromItem(item){
    const raw = String(item?.rh_region || '').trim().toLowerCase();
    if(RUNNINGHUB_REGIONS[raw]) return raw;
    return runningHubRegionFromBase(item?.base_url || '') || 'global';
}
function runningHubRegionEnabledValue(region, selected, sourceRegion){
    if(sourceRegion && typeof sourceRegion === 'object'
        && Object.prototype.hasOwnProperty.call(sourceRegion, 'enabled')
        && typeof sourceRegion.enabled === 'boolean'){
        return sourceRegion.enabled === true;
    }
    // 旧配置没有区域 enabled 时，只迁移原来正在编辑的站点为启用。
    return region === selected;
}
function runningHubEmptyRegion(region){
    const config = RUNNINGHUB_REGIONS[region] || RUNNINGHUB_REGIONS.global;
    return {
        base_url:config.baseUrl,
        enabled:false,
        image_models:[], chat_models:[], video_models:[], audio_models:[],
        model_names:{},
        rh_apps:[], rh_workflows:[]
    };
}
const normalizedRunningHubRegions = new WeakMap();
function ensureRunningHubRegions(item){
    if(!item || item.id !== 'runninghub') return {};
    if(normalizedRunningHubRegions.get(item) === item.rh_regions && item.rh_regions) return item.rh_regions;
    const selected = runningHubRegionFromItem(item);
    const source = item.rh_regions && typeof item.rh_regions === 'object' ? item.rh_regions : {};
    const legacy = {
        base_url:item.base_url || RH_DEFAULT_BASE_URL,
        image_models:Array.isArray(item.image_models) ? item.image_models : [],
        chat_models:Array.isArray(item.chat_models) ? item.chat_models : [],
        video_models:Array.isArray(item.video_models) ? item.video_models : [],
        audio_models:Array.isArray(item.audio_models) ? item.audio_models : [],
        model_names:item.model_names && typeof item.model_names === 'object' ? item.model_names : {},
        rh_apps:Array.isArray(item.rh_apps) ? item.rh_apps : [],
        rh_workflows:Array.isArray(item.rh_workflows) ? item.rh_workflows : []
    };
    const regions = {};
    Object.keys(RUNNINGHUB_REGIONS).forEach(region => {
        const rawRegion = source[region] && typeof source[region] === 'object' ? source[region] : {};
        regions[region] = {
            ...runningHubEmptyRegion(region),
            ...rawRegion
        };
        if(region === selected && !source[region]) regions[region] = {...regions[region], ...legacy};
        regions[region].enabled = runningHubRegionEnabledValue(region, selected, rawRegion);
        regions[region].base_url = RUNNINGHUB_REGIONS[region].baseUrl;
        ['image_models','chat_models','video_models','audio_models'].forEach(key => {
            regions[region][key] = unique(regions[region][key] || []);
        });
        regions[region].model_names = regions[region].model_names && typeof regions[region].model_names === 'object' ? regions[region].model_names : {};
        regions[region].rh_apps = normalizeRhEntries(regions[region].rh_apps || [], 'app');
        regions[region].rh_workflows = normalizeRhEntries(regions[region].rh_workflows || [], 'workflow');
    });
    item.rh_region = selected;
    item.rh_regions = regions;
    normalizedRunningHubRegions.set(item, regions);
    return regions;
}
function runningHubProviderItem(){
    return providers.find(item => item?.id === 'runninghub') || null;
}
function runningHubHasEnabledRegion(item){
    if(!item || item.id !== 'runninghub') return false;
    const regions = ensureRunningHubRegions(item);
    return Object.values(regions).some(region => region?.enabled === true);
}
function syncRunningHubProviderEnabled(item){
    if(!item || item.id !== 'runninghub') return false;
    item.enabled = runningHubHasEnabledRegion(item);
    return item.enabled;
}
function activateRunningHubRegion(item, region){
    if(!item || item.id !== 'runninghub') return null;
    const regions = ensureRunningHubRegions(item);
    const selected = RUNNINGHUB_REGIONS[region] ? region : runningHubRegionFromItem(item);
    const active = regions[selected] || runningHubEmptyRegion(selected);
    item.rh_region = selected;
    item.base_url = active.base_url;
    item.image_models = active.image_models;
    item.chat_models = active.chat_models;
    item.video_models = active.video_models;
    item.audio_models = active.audio_models;
    item.model_names = active.model_names || {};
    item.rh_apps = active.rh_apps;
    item.rh_workflows = active.rh_workflows;
    return active;
}
function persistActiveRunningHubRegion(item){
    if(!item || item.id !== 'runninghub') return null;
    const region = runningHubRegionFromItem(item);
    const regions = ensureRunningHubRegions(item);
    const active = regions[region] || runningHubEmptyRegion(region);
    active.base_url = RUNNINGHUB_REGIONS[region].baseUrl;
    active.image_models = unique(item.image_models || []);
    active.chat_models = unique(item.chat_models || []);
    active.video_models = unique(item.video_models || []);
    active.audio_models = unique(item.audio_models || []);
    active.model_names = item.model_names && typeof item.model_names === 'object' ? {...item.model_names} : {};
    active.rh_apps = normalizeRhEntries(item.rh_apps || [], 'app');
    active.rh_workflows = normalizeRhEntries(item.rh_workflows || [], 'workflow');
    regions[region] = active;
    item.rh_apps = active.rh_apps;
    item.rh_workflows = active.rh_workflows;
    return active;
}
const LINGJING_DEFAULT_BASE_URL = 'https://apistudio.vip';
const LINGJING_REGISTER_URL = 'https://apistudio.vip/register?aff=g1CT';
const VIP_GPT_DEFAULT_BASE_URL = 'https://www.vip-gpt.net';
const VIP_GPT_REGISTER_URL = 'https://www.vip-gpt.net/vip-gpt/register?aff=YGMS7BDKNY5Y';
const EXAMPLE_BASE_URL = 'https://api.example.com/v1';
const JIMENG_DEFAULT_IMAGE_MODELS = ['5.0Pro', '5.0', '4.7', '4.6', '4.5', '4.1', '4.0', '3.1', '3.0'];
const JIMENG_DEFAULT_VIDEO_MODELS = ['seedance2.0fast_vip', 'seedance2.0_vip', 'seedance2.0', 'seedance2.0fast', 'seedance2.0mini'];
const JIMENG_LEGACY_IMAGE_MODELS = new Set(['jimeng-image-2k', 'jimeng-image-4k']);
const JIMENG_LEGACY_VIDEO_MODELS = new Set(['jimeng-video-720p', 'jimeng-video-1080p']);
const CODEX_DEFAULT_IMAGE_MODELS = [];
const CODEX_DEFAULT_CHAT_MODELS = ['auto', 'gpt-5.5'];
const GEMINI_CLI_DEFAULT_IMAGE_MODELS = ['auto'];
const GEMINI_CLI_DEFAULT_CHAT_MODELS = ['auto'];
const CLI_PROTOCOLS = new Set(['jimeng', 'codex', 'gemini-cli']);
const API_PROTOCOLS = ['openai', 'apimart', 'gemini', 'volcengine', 'runninghub', 'jimeng', 'codex', 'gemini-cli'];
const CLI_PROVIDER_PRESETS = {
    jimeng:{id:'jimeng', name:'即梦 CLI', protocol:'jimeng'},
    codex:{id:'codex', name:'GPT CLI', protocol:'codex'},
    'gemini-cli':{id:'gemini-cli', name:'Antigravity CLI', protocol:'gemini-cli'}
};
const ONBOARDING_GUIDES = {
    modelscope:{
        titleKey:'api.msOnboardingTitle',
        descKey:'api.msOnboardingDesc',
        primaryLabelKey:'api.msGetTokenCn',
        secondaryLabelKey:'api.msGetTokenGlobal',
        primaryUrl:'https://www.modelscope.cn/my/access/token',
        secondaryUrl:'https://www.modelscope.ai/my/access/token'
    },
    'ai-money':{
        titleKey:'api.aiMoneyOnboardingTitle',
        descKey:'api.aiMoneyOnboardingDesc',
        primaryLabelKey:'api.aiMoneyRegister',
        primaryUrl:AI_MONEY_REGISTER_URL,
        secondaryLabelKey:'api.aiMoneyDocs',
        secondaryUrl:AI_MONEY_HOME_URL
    },
    agnes:{
        titleKey:'api.agnesOnboardingTitle',
        descKey:'api.agnesOnboardingDesc',
        primaryLabelKey:'api.agnesGetKey',
        primaryUrl:AGNES_REGISTER_URL
    },
    lingjing:{
        titleKey:'api.lingjingOnboardingTitle',
        descKey:'api.lingjingOnboardingDesc',
        primaryLabelKey:'api.lingjingGetApi',
        primaryUrl:LINGJING_REGISTER_URL
    }
};
function normalizeRunningHubBaseUrl(value){
    const url = String(value || '').trim().replace(/\/+$/, '');
    return url || RH_DEFAULT_BASE_URL;
}
function applyCliProtocolDefaults(item, protocol, seedModels=false){
    if(!item) return;
    const value = String(protocol || item.protocol || '').toLowerCase();
    if(!CLI_PROTOCOLS.has(value)) return;
    item.base_url = '';
    item.protocol = value;
    if(value === 'jimeng'){
        const imageModels = (item.image_models || []).filter(model => !JIMENG_LEGACY_IMAGE_MODELS.has(String(model || '').trim()));
        const videoModels = (item.video_models || []).filter(model => !JIMENG_LEGACY_VIDEO_MODELS.has(String(model || '').trim()));
        item.image_models = unique(seedModels ? [...imageModels, ...JIMENG_DEFAULT_IMAGE_MODELS] : imageModels);
        item.video_models = unique(seedModels ? [...videoModels, ...JIMENG_DEFAULT_VIDEO_MODELS] : videoModels);
        item.chat_models = unique(item.chat_models || []);
    } else if(value === 'codex'){
        item.image_models = [];
        item.chat_models = unique(seedModels ? [...(item.chat_models || []), ...CODEX_DEFAULT_CHAT_MODELS] : (item.chat_models || []));
        item.video_models = [];
        item.audio_models = [];
    } else if(value === 'gemini-cli'){
        item.image_models = unique(seedModels ? [...(item.image_models || []), ...GEMINI_CLI_DEFAULT_IMAGE_MODELS] : (item.image_models || []));
        item.chat_models = unique(seedModels ? [...(item.chat_models || []), ...GEMINI_CLI_DEFAULT_CHAT_MODELS] : (item.chat_models || []));
        item.video_models = [];
        item.audio_models = [];
    }
}
let rhWorkflowEditorState = { open:false, index:-1, entry:null, config:null, expanded:{}, activeNodeId:'', graph:{ k:1, x:0, y:0, w:0, h:0 }, pan:null, bound:false, previewParams:{}, previewRunning:false, previewStatus:'', previewOutputs:[] };
let rhEditorMode = 'workflow';
let rhWorkflowAutosaveTimer = null;
let rhWorkflowAutosavePending = null;
let rhWorkflowAutosaveSerial = Promise.resolve();
let rhWorkflowAutosaveRevision = 0;
let recommendInlineOpen = false;
const recommendedKeySaveTimers = new Map();
let providerDragId = '';
let fetchModelsController = null;
// 推荐平台是管理员审核后的公开白名单，不能从可适配平台或历史配置自动扩展。
const RECOMMENDED_APIS = [
    {
        id:'agnes',
        name:'Agnes AI',
        category:'free',
        base_url:AGNES_DEFAULT_BASE_URL,
        protocol:'openai',
        image_request_mode:'openai-json',
        register_url:AGNES_REGISTER_URL,
        tagKeys:['api.tagImageModels','api.tagVideoModels','api.tagLlmModels'],
        icons:['IMG','VID','LLM'],
        summaryKey:'api.recommendAgnesSummary',
        perkKey:'api.recommendAgnesFree',
        perkClass:'recommend-free-tag',
        add_without_key:true,
        advantages:['免费额度可用', '支持 Agnes 图像与视频接口', 'OpenAI 兼容地址配置简单'],
        image_models:['agnes-image-2.1-flash', 'agnes-image-2.0-flash'],
        chat_models:['agnes-2.0-flash'],
        video_models:['agnes-video-v2.0']
    }
];
const RECOMMEND_GROUPS = [
    {key:'free', titleKey:'api.recommendGroupFree', icon:'gift'}
];
const LOCKED_RECOMMENDED_PROTOCOL_IDS = new Set(['exellome', 'fhl']);
function lockedRecommendedApi(itemOrId){
    const id = typeof itemOrId === 'string' ? itemOrId : itemOrId?.id;
    const name = typeof itemOrId === 'string' ? '' : itemOrId?.name;
    const baseUrl = typeof itemOrId === 'string' ? '' : itemOrId?.base_url;
    const normalizedId = String(id || '').trim().toLowerCase();
    const normalizedName = String(name || '').trim().toLowerCase();
    const normalizedBase = String(baseUrl || '').trim().replace(/\/+$/, '').toLowerCase();
    const normalizedHost = (() => {
        try { return new URL(normalizedBase).host.toLowerCase(); } catch(e) { return ''; }
    })();
    return RECOMMENDED_APIS.find(api => {
        if(!LOCKED_RECOMMENDED_PROTOCOL_IDS.has(api.id)) return false;
        const apiBase = String(api.base_url || '').trim().replace(/\/+$/, '').toLowerCase();
        const apiHost = (() => {
            try { return new URL(apiBase).host.toLowerCase(); } catch(e) { return ''; }
        })();
        return normalizedId === api.id
            || normalizedName === String(api.name || '').trim().toLowerCase()
            || (apiBase && normalizedBase === apiBase)
            || (apiHost && normalizedHost === apiHost);
    }) || null;
}
function hasLockedRecommendedProtocol(itemOrId){
    return Boolean(lockedRecommendedApi(itemOrId));
}
function applyLockedRecommendedProtocol(item){
    const api = lockedRecommendedApi(item);
    if(!item || !api) return false;
    item.protocol = String(api.protocol || 'openai').toLowerCase();
    item.image_request_mode = normalizeImageRequestMode(api.image_request_mode);
    return true;
}

function refreshIcons(){ if(window.lucide) lucide.createIcons(); }
function tr(key){
    const translated = window.StudioI18n ? window.StudioI18n.t(key) : key;
    if(translated !== key) return translated;
    const fallback = {
        'api.jimengStartLogin':'扫码登录',
        'api.jimengCredit':'查询积分',
        'api.jimengHelp':'帮助',
        'api.jimengLogout':'退出登录',
        'api.jimengScanTitle':'使用手机扫描二维码完成验证',
        'api.jimengBrowserDesc':'也可以在当前电脑的默认浏览器中完成认证。',
        'api.jimengOpenBrowser':'在浏览器中验证',
        'api.jimengOpenFailed':'无法打开验证网页',
        'api.jimengWaitingVerify':'等待验证...',
        'api.jimengQrWaiting':'正在生成二维码...',
        'api.jimengQrAlt':'即梦登录二维码',
        'api.jimengUserCode':'用户码',
        'api.jimengExpiresAt':'有效期至',
        'api.jimengVerified':'即梦 CLI 登录验证成功',
        'api.jimengExpired':'本次认证已过期，请重新登录',
        'api.jimengFailed':'即梦登录验证失败，请重新登录',
        'api.jimengRetry':'重新登录',
        'api.comfyuiSettingsTitle':'ComfyUI 设置',
        'api.comfyuiSettingsMeta':'本地工作流与 RunningHub 应用',
        'api.comfyuiSubnavTitle':'ComfyUI 设置',
        'api.localComfyuiNav':'本地 ComfyUI',
        'api.runningHubComfyuiNav':'RunningHub ComfyUI',
        'api.comfyuiSettingsDesc':'在这里统一管理 RunningHub AI 应用和本地 ComfyUI 工作流。RunningHub 的 API Key 仍在对应平台中保存。',
        'api.keyConfigured':'已配置',
        'api.keyNotConfigured':'未配置',
        'api.rhSiteDisabled':'此站点已停用',
        'api.runningHubLegacyWorkflowDeprecated':'已废弃：RunningHub 旧工作流入口只用于历史画布兼容；新导演台和新节点仅使用已同步的 AI 应用。',
        'api.comfyuiSettingsBack':'返回平台设置'
    };
    return fallback[key] || key;
}
function trf(key, vars={}){
    let text = tr(key);
    Object.entries(vars).forEach(([name, value]) => {
        text = text.replaceAll(`{${name}}`, String(value ?? ''));
    });
    return text;
}
function setStatus(text){ statusEl.textContent = text || ''; }
function apiResponseDetail(data, fallback='请求失败'){
    if(data && typeof data === 'object'){
        const detail = data.detail || data.message || data.error;
        if(typeof detail === 'string' && detail.trim()) return detail.trim();
        if(detail && typeof detail === 'object') return detail.message || JSON.stringify(detail);
    }
    return fallback;
}
async function readApiResponse(response, fallback='请求失败'){
    const text = await response.text();
    let data = {};
    if(text.trim()){
        try { data = JSON.parse(text); }
        catch(e){ data = {detail:text.trim()}; }
    }
    if(!response.ok){
        throw new Error(`${apiResponseDetail(data, fallback)}（HTTP ${response.status}）`);
    }
    return data;
}
function runningHubRegionFromBase(value){
    return String(value || '').toLowerCase().includes('runninghub.cn') ? 'cn' : 'global';
}
function syncRunningHubRegion(replaceBase=false){
    const item = provider();
    const region = item?.id === 'runninghub'
        ? (RUNNINGHUB_REGIONS[runningHubModelRegion] ? runningHubModelRegion : runningHubRegionFromItem(item))
        : runningHubRegionFromBase(baseInput?.value || '');
    if(item?.id === 'runninghub'){
        const regions = ensureRunningHubRegions(item);
        Object.keys(RUNNINGHUB_REGIONS).forEach(site => {
            const enabledInput = runningHubRegionEnabledInput(site);
            if(enabledInput) enabledInput.checked = regions[site]?.enabled === true;
        });
    }
    if(replaceBase && baseInput && RUNNINGHUB_REGIONS[region]){
        baseInput.value = RUNNINGHUB_REGIONS[region].baseUrl;
    }
}
function selectRunningHubModelRegion(region){
    if(!RUNNINGHUB_REGIONS[region]) return;
    const item = provider();
    if(!item || item.id !== 'runninghub') return;
    void captureApiObjectBeforeNavigation({immediate:true});
    runningHubModelRegion = region;
    activateRunningHubRegion(item, region);
    if(baseInput) baseInput.value = item.base_url;
    clearFetchedModelState();
    renderEditor();
    updateApimartDomesticHint(item);
    void scheduleProviderAutosave({providerId:item.id, region, immediate:true, sync:false});
}
function updateRunningHubKeyInput(region, kind, value){
    if(!RUNNINGHUB_REGIONS[region] || !['free','wallet'].includes(kind)) return;
    const item = runningHubProviderItem();
    if(!item) return;
    const trimmed = String(value || '').trim();
    const keyName = kind === 'wallet' ? '_pendingRhWalletKey' : '_pendingRhApiKey';
    const pending = {...(item[keyName] || {})};
    if(trimmed) pending[region] = trimmed;
    else delete pending[region];
    if(Object.keys(pending).length) item[keyName] = pending;
    else delete item[keyName];
    void scheduleProviderAutosave({providerId:item.id, region, immediate:false, sync:false});
}
function broadcastStudioApiChange(type='providers-changed'){
    const message = { type, updated_at:Date.now() };
    try { new BroadcastChannel('studio-api').postMessage(message); } catch(e) {}
    try { window.parent?.postMessage(message, '*'); } catch(e) {}
    try { window.top?.postMessage(message, '*'); } catch(e) {}
}
function toggleRunningHubRegionEnabled(region, enabled){
    if(!RUNNINGHUB_REGIONS[region]) return;
    const item = runningHubProviderItem();
    if(!item) return;
    if(provider()?.id === 'runninghub') syncEditor();
    const regions = ensureRunningHubRegions(item);
    regions[region].enabled = enabled === true;
    item.rh_regions = regions;
    syncRunningHubProviderEnabled(item);
    if(selectedId === item.id) renderEditor();
    else renderProviderList();
    void scheduleProviderAutosave({providerId:item.id, region, immediate:true, sync:false});
}
function rhEditorSideScrollEl(){
    return rhWorkflowEditorNodeList?.closest?.('.rh-workflow-editor-side') || rhWorkflowEditorNodeList;
}
function captureRhEditorScrollState(){
    const pop = document.getElementById('rhNodePopover');
    const popBody = pop?.querySelector?.('.rh-popover-body');
    const side = rhEditorSideScrollEl();
    return {
        sideTop:side?.scrollTop || 0,
        nodeListTop:rhWorkflowEditorNodeList?.scrollTop || 0,
        graphTop:rhWorkflowEditorGraphWrap?.scrollTop || 0,
        popNodeId:pop?.dataset?.nodeId || '',
        popFieldKey:pop?.dataset?.fieldKey || '',
        popBodyTop:popBody?.scrollTop || 0
    };
}
function restoreRhEditorScrollState(state){
    if(!state) return;
    const restore = () => {
        const side = rhEditorSideScrollEl();
        if(side) side.scrollTop = state.sideTop || 0;
        if(rhWorkflowEditorNodeList) rhWorkflowEditorNodeList.scrollTop = state.nodeListTop || 0;
        if(rhWorkflowEditorGraphWrap) rhWorkflowEditorGraphWrap.scrollTop = state.graphTop || 0;
        const pop = document.getElementById('rhNodePopover');
        const samePopover = pop && (
            (state.popNodeId && pop.dataset.nodeId === state.popNodeId) ||
            (state.popFieldKey && pop.dataset.fieldKey === state.popFieldKey)
        );
        if(samePopover){
            const popBody = pop.querySelector('.rh-popover-body');
            if(popBody) popBody.scrollTop = state.popBodyTop || 0;
        }
    };
    requestAnimationFrame(() => {
        restore();
        requestAnimationFrame(restore);
    });
}
function withRhEditorScrollPreserved(callback){
    const scrollState = captureRhEditorScrollState();
    const result = callback();
    restoreRhEditorScrollState(scrollState);
    return result;
}
function findRhAppFieldCard(key){
    return Array.from(document.querySelectorAll('.rh-app-field-card')).find(el => el.dataset.fieldKey === String(key || ''));
}
function normalizeId(value){
    return String(value || '').trim().toLowerCase().replace(/[^a-z0-9_-]/g, '-').replace(/^-+|-+$/g, '').replace(/-+/g, '-').slice(0, 40);
}
// 平台 Key 按稳定 ID 保存；ID 一旦创建就保持稳定，避免改名或中文名称导致 Key 看起来丢失。
function deriveIdFromName(name, existingId){
    if(existingId) return existingId;
    let id = normalizeId(name);
    if(!id){
        id = 'api-' + Math.random().toString(36).slice(2, 8);
    }
    let candidate = id, i = 2;
    while(providers.some(p => p.id === candidate)){
        candidate = `${id}-${i++}`;
    }
    return candidate;
}
function updateIdPreview(){
    const item = provider();
    if(!item) return;
    const isBuiltin = item.id === 'comfly' || item.id === 'modelscope' || item.id === 'runninghub' || item.id === 'volcengine' || item.id === 'ai-money' || item.id === 'jimeng';
    const idPreview = document.getElementById('idPreview');
    if(!idPreview) return;
    if(isBuiltin){
        idPreview.textContent = item.id;
        return;
    }
    idPreview.textContent = deriveIdFromName(nameInput.value, item.id);
}
function provider(){
    return visibleProviders().find(item => item.id === selectedId) || visibleProviders()[0];
}
function isProviderTemporarilyHidden(item){
    return HIDDEN_PROVIDER_IDS.has(String(item?.id || '').trim().toLowerCase());
}
function visibleProviders(){
    return (providers || []).filter(item => !isProviderTemporarilyHidden(item));
}
function isFixedProvider(itemOrId){
    const id = typeof itemOrId === 'string' ? itemOrId : itemOrId?.id;
    // 即梦 CLI 不再是固定平台：可删除、可排序，未添加则不存在。
    return id === 'modelscope' || id === 'runninghub' || id === 'volcengine' || id === 'ai-money';
}
function isCustomApiProvider(item){
    if(!item || isFixedProvider(item)) return false;
    const protocol = String(item.protocol || 'openai').toLowerCase();
    if(CLI_PROTOCOLS.has(protocol)) return false;
    return !lockedRecommendedApi(item);
}
function providerAgentPrompt(){
    const item = provider() || {};
    const providerName = String(item.name || '<平台名称>').trim() || '<平台名称>';
    const baseUrl = String(item.base_url || '<API Base URL>').trim() || '<API Base URL>';
    if(window.StudioI18n?.lang?.() === 'en'){
        return [
            'Adapt a third-party API provider for this Smart Canvas project.',
            '',
            `Target provider: ${providerName}`,
            `Current Base URL: ${baseUrl}`,
            'Official API documentation: <add a documentation URL or local path here>',
            'Project integration guide: docs/第三方API平台接入规范.md',
            'Manifest Schema: data/model_capabilities/provider-manifest.schema.json',
            '',
            'Requirements:',
            '1. Read AGENTS.md, the integration guide, PRD chapter 4, and existing provider adapters first. Do not create provider-specific canvas nodes.',
            '2. Build an official-field → standard-field → canvas-location → provider-field mapping worksheet covering catalog discovery, model families, task variants, input roles, parameter types and options, outputs, task states, error codes, and official evidence.',
            '3. Create and validate a Provider Manifest. Keep provider differences in capability profiles and controlled adapters, and route model family → task variant → real model_id. Mark undocumented capabilities as unknown/needs_profile instead of guessing from model names.',
            '4. Connect API Settings key storage, catalog fetching, and the four enabled-model lists. Fetching creates a catalog snapshot only; the user decides which models enter the canvas. Removing a model only disables it for this user and must not delete adapters, profiles, or historical canvases.',
            '5. The canvas may show only models enabled for this provider with readiness=ready. Resolve exactly one real task variant from input media types, roles, and counts; never switch silently.',
            '6. Reuse the provider-independent standard request and existing adapter boundary. Do not scatter provider fields through canvas UI code. Add tests for catalog parsing, family routing, dynamic parameters, backend validation, and request snapshots.',
            '7. Run only Manifest validation, dry-run, fixtures, mocks, and local contract tests. Do not upload media, submit or poll tasks, download provider results, trigger generation, or incur charges.',
            '8. If the guide conflicts with the provider\'s real Schema, record official evidence and the mismatch, decide whether the shared contract must change, and preserve the last valid version.',
            '9. Report changed files, supported model families and variants, field mappings, unresolved evidence, the current enabled list, dry-run results, guide differences, and every paid or real-network action that was deliberately not performed.',
            '',
            'Never read, print, copy, or store API keys, cookies, authorization headers, signed URLs, or user media in the Manifest, capability profiles, canvas exports, fixtures, or logs.'
        ].join('\n');
    }
    return [
        '请在当前智能画布项目中完成第三方 API 平台适配。',
        '',
        `目标平台：${providerName}`,
        `当前 Base URL：${baseUrl}`,
        '第三方官方 API 文档：<请在这里补充文档 URL 或本地路径>',
        '项目接入规范：docs/第三方API平台接入规范.md',
        'Manifest Schema：data/model_capabilities/provider-manifest.schema.json',
        '',
        '执行要求：',
        '1. 先阅读 AGENTS.md、接入规范、PRD 第四章和现有平台适配代码，不要另建画布节点。',
        '2. 先建立“官方字段 → 标准字段 → 画布位置 → 平台字段”的映射工作表，明确目录、模型家族、任务变体、输入角色、参数类型/选项、输出、任务状态和错误码的官方证据。',
        '3. 创建并校验 Provider Manifest；将平台差异放入能力档案和受控适配器，建立模型家族 → 任务变体 → 真实 model_id 的路由。文档没有证据的能力标为 unknown/needs_profile，不得按模型名称猜测。',
        '4. 接通 API 设置中的 Key、模型目录拉取和四类模型启用清单。拉取全部模型只建立目录和当前用户目录快照，用户通过“选择模型”决定哪些模型进入画布；删除模型只是停用当前用户，不得删除适配器、能力档案或历史画布。',
        '5. 画布只显示当前平台启用且 readiness=ready 的模型，并根据输入类型、角色和数量路由到唯一真实变体；不能静默猜测或切换。',
        '6. 复用平台无关的标准请求层和现有适配器边界，第三方字段不得直接散落到节点前端；为目录解析、家族路由、动态参数、后端校验及请求映射补测试。',
        '7. 只运行 Manifest 校验、dry-run 和本地契约测试，禁止真实上传、提交、轮询、下载结果或产生费用。',
        '8. 如果规范与第三方真实 Schema 不一致，记录官方证据和差异，先判断是否应扩展公共标准，再实现平台特例；保留版本和最近有效配置。',
        '9. 报告改动文件、支持的模型家族与变体、字段映射、待补证据项、当前启用清单、dry-run 结果、规范差异，以及明确未执行的付费测试。',
        '',
        '禁止读取、输出、复制或保存 API Key、Cookie、完整 Authorization、签名 URL 和用户素材；这些内容不得进入 Manifest、能力档案、画布导出、测试夹具或日志。'
    ].join('\n');
}
async function copyProviderAgentPrompt(){
    const text = providerAgentPrompt();
    try {
        if(navigator.clipboard?.writeText && window.isSecureContext !== false){
            await navigator.clipboard.writeText(text);
        } else {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            if(!document.execCommand('copy')) throw new Error('copy failed');
            textarea.remove();
        }
        setStatus(tr('api.agentPromptCopied'));
        const label = document.querySelector('#copyProviderPromptBtn span');
        if(label){
            label.textContent = tr('api.copied');
            setTimeout(() => { label.textContent = tr('api.copyAgentPrompt'); }, 1600);
        }
    } catch(error){
        await StudioDialog.alert(tr('api.copyAgentPromptFailed'), {type:'warning'});
    }
}
function unique(values){
    const seen = new Set();
    return values.map(v => String(v || '').trim()).filter(v => v && !seen.has(v) && seen.add(v));
}
function normalizeRhEntries(values, kind){
    const seen = new Set();
    return (Array.isArray(values) ? values : []).map(raw => {
        const parsed = parseRunningHubRunRef(raw?.appId || raw?.workflowId || raw?.id || '');
        const id = String(parsed?.id || raw?.id || raw?.appId || raw?.workflowId || '').trim();
        if(!id || seen.has(id)) return null;
        seen.add(id);
        const fallback = kind === 'app' ? `AI 应用 ${id.slice(-6)}` : `工作流 ${id.slice(-6)}`;
        const entry = {
            id,
            title:String(raw?.title || raw?.name || fallback).trim(),
            note:String(raw?.note || raw?.description || '').trim(),
            thumbnail:String(raw?.thumbnail || '').trim(),
            enabled:raw?.enabled !== false
        };
        ['title_zh','title_en','name_zh','name_en'].forEach(key => {
            if(raw?.[key] !== undefined && raw?.[key] !== null) entry[key] = String(raw[key]).trim();
        });
        ['titles','names','localizedNames','webappNames'].forEach(key => {
            if(raw?.[key] && typeof raw[key] === 'object' && !Array.isArray(raw[key])) entry[key] = {...raw[key]};
        });
        if(raw?.hidden === true) entry.hidden = true;
        if(Array.isArray(raw?.fields)) entry.fields = raw.fields.map(normalizeRhWorkflowField);
        if(raw?.workflowJson && typeof raw.workflowJson === 'object') entry.workflowJson = raw.workflowJson;
        if(raw?.raw && typeof raw.raw === 'object') entry.raw = raw.raw;
        if(Array.isArray(raw?.tags)) entry.tags = raw.tags;
        const schemaSyncedAt = Number(raw?.schemaSyncedAt || 0);
        if(schemaSyncedAt > 0) entry.schemaSyncedAt = schemaSyncedAt;
        const updatedAt = Number(raw?.updatedAt || 0);
        if(updatedAt > 0) entry.updatedAt = updatedAt;
        if(kind === 'app') entry.appId = id;
        else {
            entry.workflowId = id;
            entry.optionalImageMode = String(raw?.optionalImageMode || 'prune-workflow');
        }
        return entry;
    }).filter(Boolean);
}
function runningHubLocalizedTitle(entry, region=currentRunningHubRegion(provider())){
    const isEnglish = region !== 'cn' && window.StudioI18n?.lang?.() === 'en';
    const localized = [entry?.titles, entry?.names, entry?.localizedNames, entry?.webappNames]
        .find(value => value && typeof value === 'object' && !Array.isArray(value)) || {};
    const values = isEnglish
        ? [entry?.title_en, entry?.name_en, localized.en, localized.en_US, localized['en-US'], localized.english]
        : [entry?.title_zh, entry?.name_zh, localized.zh, localized.zh_CN, localized['zh-CN'], localized.chinese];
    const selected = values.find(value => String(value || '').trim());
    return String(selected || entry?.title || entry?.name || '').trim();
}
function runningHubRegionBadge(region=currentRunningHubRegion(provider())){
    return tr(String(region || '').toLowerCase() === 'cn' ? 'api.rhRegionBadgeCn' : 'api.rhRegionBadgeGlobal');
}
function parseRunningHubRunRef(value){
    const text = String(value || '').trim();
    const match = text.match(/\/(?:run\/)?(ai-app|workflow)\/([0-9A-Za-z_-]+)/i);
    if(match) return { type:match[1].toLowerCase() === 'ai-app' ? 'app' : 'workflow', id:match[2] };
    try {
        const url = new URL(text);
        const id = url.searchParams.get('webappId') || url.searchParams.get('appId') || url.searchParams.get('webapp_id');
        if(id && /^[0-9A-Za-z_-]{4,}$/.test(id)) return { type:'app', id };
    } catch(_error) {}
    if(/^[0-9A-Za-z_-]{4,}$/.test(text)) return { type:'app', id:text };
    return null;
}
function workflowNodeTitle(node){
    return (node?._meta?.title || node?.class_type || node?._class || node?.type || 'Node').toString();
}
function workflowNodeClass(node){
    return (node?.class_type || node?._class || node?.type || '').toString();
}
function workflowNodeCategory(node){
    const text = `${workflowNodeTitle(node)} ${workflowNodeClass(node)}`.toLowerCase();
    if(/text|prompt|clip/.test(text)) return 'prompt';
    if(/lora/.test(text)) return 'lora';
    if(/ksampler|k sampler|sampler|scheduler|guid|cfg/.test(text)) return 'sampler';
    if(/video|movie|mp4|webm|frame/.test(text)) return 'video';
    if(/audio|sound|voice|music|wav|mp3/.test(text)) return 'audio';
    if(/image|mask|resize|scale|crop|photo|picture|preview|save/.test(text)) return 'image';
    return 'misc';
}
function rhWorkflowFieldKey(field){
    return `${field?.nodeId || ''}::${field?.fieldName || ''}`;
}
function rhWorkflowFieldKind(field){
    const type = String(field?.fieldType || '').toUpperCase();
    if(['IMAGE','VIDEO','AUDIO','BOOLEAN','NUMBER','FLOAT','INT','INTEGER','TEXT','SLIDER'].includes(type)){
        if(type === 'FLOAT' || type === 'INT' || type === 'INTEGER') return 'NUMBER';
        return type;
    }
    const key = `${field?.fieldName || ''} ${field?.label || field?.title || field?.description || ''} ${field?.fieldValue || ''}`.toLowerCase();
    if(/image|img|mask|png|jpg|jpeg|webp|图片|图像|照片|参考图|首帧|尾帧/.test(key)) return 'IMAGE';
    if(/video|mp4|webm|mov|视频|影片/.test(key)) return 'VIDEO';
    if(/audio|wav|mp3|voice|sound|音频|声音|语音|音乐/.test(key)) return 'AUDIO';
    if(/true|false/.test(key)) return 'BOOLEAN';
    if(/^-?\d+(\.\d+)?$/.test(String(field?.fieldValue || '').trim())) return 'NUMBER';
    return 'TEXT';
}
function rhWorkflowFieldTypeLabel(type){
    return ({
        TEXT:'文本',
        NUMBER:'数字',
        SLIDER:'滑块',
        BOOLEAN:'开关',
        SELECT:'下拉',
        IMAGE:'图片',
        VIDEO:'视频',
        AUDIO:'音频'
    })[String(type || '').toUpperCase()] || type;
}
const RH_EDITOR_KNOWN_FIELD_OPTIONS = {
    sampler_name:['euler','euler_ancestral','heun','dpm_2','dpm_2_ancestral','lms','dpmpp_2m','dpmpp_sde','ddim','uni_pc'],
    sampler:['euler','euler_ancestral','heun','dpm_2','dpm_2_ancestral','lms','dpmpp_2m','dpmpp_sde','ddim','uni_pc'],
    scheduler:['normal','karras','exponential','sgm_uniform','simple','ddim_uniform','beta'],
    ratio:['1:1','16:9','9:16','21:9','9:21','4:3','3:4','4:5','5:4','3:2','2:3'],
    aspectRatio:['1:1','16:9','9:16','4:3','3:4','4:5','5:4','3:2','2:3'],
    resolution:['512','768','1024','1280','1536','2048','1k','2k','4k'],
    size:['512','768','1024','1280','1536','2048'],
    ckpt_name:[],
    unet_name:[],
    lora_name:[]
};
function rhKnownOptionsForField(field){
    const name = String(field?.fieldName || '').trim();
    if(!name) return [];
    if(RH_EDITOR_KNOWN_FIELD_OPTIONS[name]) return RH_EDITOR_KNOWN_FIELD_OPTIONS[name].map(String);
    const hit = Object.keys(RH_EDITOR_KNOWN_FIELD_OPTIONS).find(key => key.toLowerCase() === name.toLowerCase());
    return hit ? RH_EDITOR_KNOWN_FIELD_OPTIONS[hit].map(String) : [];
}
function normalizeRhWorkflowField(field){
    const options = Array.isArray(field?.options)
        ? field.options.map(option => String(option ?? '').trim()).filter(Boolean)
        : String(field?.options || '').split(/\r?\n|,/).map(option => option.trim()).filter(Boolean);
    const knownOptions = options.length ? options : field?.officialSchema === true ? [] : rhKnownOptionsForField(field);
    const fieldType = String(field?.fieldType || rhWorkflowFieldKind(field));
    const normalizedType = fieldType.toUpperCase();
    const savedSource = field?.sourceFromUpstream;
    const optionLabels = field?.optionLabels && typeof field.optionLabels === 'object'
        ? Object.fromEntries(Object.entries(field.optionLabels).map(([value, label]) => [String(value), String(label)]))
        : {};
    return {
        id:String(field?.id || rhWorkflowFieldKey(field)),
        nodeId:String(field?.nodeId || ''),
        fieldName:String(field?.fieldName || ''),
        fieldValue:field?.fieldValue == null ? '' : String(field.fieldValue),
        fieldType:knownOptions.length && !['IMAGE','VIDEO','AUDIO','SLIDER'].includes(normalizedType) ? 'SELECT' : fieldType,
        inputRole:String(field?.inputRole ?? field?.input_role ?? field?.semanticRole ?? field?.semantic_role ?? field?.role ?? ''),
        label:String(field?.label || field?.fieldName || ''),
        enabled:field?.enabled === true,
        sourceFromUpstream:savedSource === undefined ? false : savedSource !== false,
        group:String(field?.group || ''),
        note:String(field?.note || ''),
        options:knownOptions,
        optionLabels,
        acceptsUpload:field?.acceptsUpload === true,
        random_enabled:field?.random_enabled === true,
        min:field?.min ?? '',
        max:field?.max ?? '',
        step:field?.step ?? '',
        imageOrder:Number(field?.imageOrder || field?.image_order || 0) || 0,
        required:field?.required === true,
        officialSchema:field?.officialSchema === true
    };
}
function normalizeFetchedRhWorkflowField(field){
    return {...normalizeRhWorkflowField(field), enabled:true};
}
function rhWorkflowGroupKey(field){
    return `${field?.nodeId || ''}::${field?.group || ''}`;
}
function rhEditorSortedFields(fields){
    return [...(fields || [])].sort((a, b) => {
        const ak = rhWorkflowFieldKind(a);
        const bk = rhWorkflowFieldKind(b);
        if(ak === 'IMAGE' && bk === 'IMAGE'){
            const ao = Number(a.imageOrder) || 9999;
            const bo = Number(b.imageOrder) || 9999;
            if(ao !== bo) return ao - bo;
        }
        if(ak === 'IMAGE' && bk !== 'IMAGE') return -1;
        if(ak !== 'IMAGE' && bk === 'IMAGE') return 1;
        return String(a.nodeId || '').localeCompare(String(b.nodeId || ''), undefined, {numeric:true}) || String(a.fieldName || '').localeCompare(String(b.fieldName || ''));
    });
}
function keyStatusText(configured){
    return configured ? tr('api.keyConfigured') : tr('api.keyNotConfigured');
}
function rhFreeKeyHintText(regionState){
    return keyStatusText(Boolean(regionState?.has_key));
}
function rhWalletKeyHintText(regionState){
    return keyStatusText(Boolean(regionState?.has_wallet_key));
}
function volcengineArkKeyHintText(item){
    return keyStatusText(Boolean(item?.has_key));
}
function volcengineAssetKeyHintText(item){
    const ak = `AK：${keyStatusText(Boolean(item?.has_volcengine_access_key))}`;
    const sk = `SK：${keyStatusText(Boolean(item?.has_volcengine_secret_key))}`;
    return `${ak} · ${sk}`;
}
function isNewUserProvider(item){
    if(!item) return false;
    if(item.id === 'modelscope') return !item.has_key;
    if(item.id === 'ai-money') return !item.has_key;
    if(item.id === 'agnes') return !item.has_key;
    return false;
}
function isApimartProviderContext(item){
    const baseUrl = String(baseInput?.value || item?.base_url || '').trim().toLowerCase();
    return baseUrl.includes('apimart.ai');
}
function updateApimartDomesticHint(item=provider()){
    const hasKey = Boolean(item?.has_key || (keyInput?.value || '').trim());
    document.body.classList.toggle('show-apimart-domestic-hint', Boolean(isApimartProviderContext(item) && hasKey));
}
function renderProviderOnboarding(item){
    if(!providerOnboardingCard) return;
    const guide = ONBOARDING_GUIDES[item?.id];
    const visible = Boolean(!recommendInlineOpen && guide && isNewUserProvider(item));
    providerOnboardingCard.hidden = !visible;
    document.body.classList.toggle('show-provider-onboarding', visible);
    if(!visible){
        providerOnboardingCard.innerHTML = '';
        return;
    }
    if(item.id === 'modelscope'){
        providerOnboardingCard.innerHTML = `
            <div class="onboarding-head">
                <div>
                    <div class="onboarding-title">${escapeHtml(tr(guide.titleKey))}</div>
                    <div class="onboarding-desc">${escapeHtml(tr(guide.descKey))}</div>
                </div>
                <span class="onboarding-badge">${escapeHtml(tr('api.onboardingNew'))}</span>
            </div>
            <div class="onboarding-step-panel onboarding-rh-linear-panel onboarding-ms-linear-panel">
                <div class="onboarding-rh-panel-head">
                    <div>
                        <div class="onboarding-step-title">${escapeHtml(tr('api.msOnboardingStep'))}</div>
                    </div>
                    <i data-lucide="key-round" class="onboarding-rh-icon w-4 h-4"></i>
                </div>
                <div class="onboarding-rh-linear-rows">
                    <div class="onboarding-rh-linear-row onboarding-ms-linear-row">
                        <div class="onboarding-rh-source-group">
                            <div class="onboarding-rh-source-label">${escapeHtml(tr('api.msTokenLabel'))}</div>
                            <div class="onboarding-key-actions onboarding-rh-key-actions">
                                <a class="onboarding-key-btn" href="${escapeAttr(guide.primaryUrl)}" target="_blank" rel="noopener noreferrer"><i data-lucide="key-round" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr(guide.primaryLabelKey))}</span></a>
                                <a class="onboarding-key-btn" href="${escapeAttr(guide.secondaryUrl)}" target="_blank" rel="noopener noreferrer"><i data-lucide="globe-2" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr(guide.secondaryLabelKey))}</span></a>
                            </div>
                        </div>
                        <div class="recommend-flow-arrow onboarding-flow-arrow onboarding-rh-row-arrow" aria-hidden="true"><span></span><b></b></div>
                        <label class="onboarding-key-field onboarding-rh-row-field">
                            <span>API Key</span>
                            <input type="password" value="${escapeAttr(keyInput?.value || '')}" placeholder="${escapeAttr(tr('api.msTokenPlaceholder'))}" oninput="syncOnboardingKeyInput('standard', this.value)">
                        </label>
                    </div>
                </div>
                <div class="ms-binding-guide onboarding-ms-binding-guide">
                    <div class="ms-binding-copy">
                        <div class="ms-binding-title"><i data-lucide="link-2" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr('api.msBindingTitle'))}</span></div>
                        <div class="ms-binding-desc">${escapeHtml(tr('api.msBindingDesc'))}</div>
                    </div>
                    <div class="ms-binding-actions">
                        <a href="https://www.modelscope.cn/binding" target="_blank" rel="noopener noreferrer"><i data-lucide="external-link" class="w-3 h-3"></i><span>${escapeHtml(tr('api.msBindingCn'))}</span></a>
                        <a href="https://www.modelscope.ai/binding" target="_blank" rel="noopener noreferrer"><i data-lucide="external-link" class="w-3 h-3"></i><span>${escapeHtml(tr('api.msBindingGlobal'))}</span></a>
                    </div>
                </div>
                <div class="onboarding-autosave-note"><i data-lucide="cloud-check" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr('api.autosaveHint'))}</span></div>
            </div>
        `;
        refreshIcons();
        return;
    }
    if(item.id === 'ai-money'){
        providerOnboardingCard.innerHTML = `
            <div class="onboarding-head">
                <div>
                    <div class="onboarding-title">${escapeHtml(tr(guide.titleKey))}</div>
                    <div class="onboarding-desc">${escapeHtml(tr(guide.descKey))}</div>
                </div>
                <span class="onboarding-badge">laohu</span>
            </div>
            <div class="onboarding-step-panel onboarding-rh-linear-panel onboarding-ai-money-panel">
                <div class="onboarding-rh-linear-row">
                    <div class="onboarding-rh-source-group">
                        <div class="onboarding-rh-source-label">laohu API</div>
                        <div class="onboarding-key-actions onboarding-rh-key-actions">
                            <a class="onboarding-key-btn" href="${escapeAttr(guide.primaryUrl)}" target="_blank" rel="noopener noreferrer"><i data-lucide="user-plus" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr(guide.primaryLabelKey))}</span></a>
                            <a class="onboarding-key-btn" href="${escapeAttr(guide.secondaryUrl)}" target="_blank" rel="noopener noreferrer"><i data-lucide="book-open" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr(guide.secondaryLabelKey))}</span></a>
                        </div>
                    </div>
                    <div class="recommend-flow-arrow onboarding-flow-arrow onboarding-rh-row-arrow" aria-hidden="true"><span></span><b></b></div>
                    <label class="onboarding-key-field onboarding-rh-row-field">
                        <span>API Key</span>
                        <input type="password" value="${escapeAttr(keyInput?.value || '')}" placeholder="${escapeAttr(tr('api.aiMoneyKeyPlaceholder'))}" oninput="syncOnboardingKeyInput('standard', this.value)">
                    </label>
                </div>
                <div class="onboarding-autosave-note"><i data-lucide="cloud-check" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr('api.autosaveHint'))}</span></div>
            </div>
        `;
        refreshIcons();
        return;
    }
    if(item.id === 'agnes'){
        providerOnboardingCard.innerHTML = `
            <div class="onboarding-head">
                <div>
                    <div class="onboarding-title">${escapeHtml(tr(guide.titleKey))}</div>
                    <div class="onboarding-desc">${escapeHtml(tr(guide.descKey))}</div>
                </div>
                <span class="onboarding-badge">Agnes AI</span>
            </div>
            <div class="onboarding-step-panel onboarding-rh-linear-panel">
                <div class="onboarding-rh-linear-row">
                    <div class="onboarding-rh-source-group">
                        <div class="onboarding-rh-source-label">Agnes AI API</div>
                        <div class="onboarding-key-actions onboarding-rh-key-actions">
                            <a class="onboarding-key-btn" href="${escapeAttr(guide.primaryUrl)}" target="_blank" rel="noopener noreferrer"><i data-lucide="key-round" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr(guide.primaryLabelKey))}</span></a>
                        </div>
                    </div>
                    <div class="recommend-flow-arrow onboarding-flow-arrow onboarding-rh-row-arrow" aria-hidden="true"><span></span><b></b></div>
                    <label class="onboarding-key-field onboarding-rh-row-field">
                        <span>API Key</span>
                        <input type="password" value="${escapeAttr(keyInput?.value || '')}" placeholder="${escapeAttr(tr('api.enterKey'))}" oninput="syncOnboardingKeyInput('standard', this.value)">
                    </label>
                </div>
                <div class="onboarding-autosave-note"><i data-lucide="cloud-check" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr('api.autosaveHint'))}</span></div>
            </div>
        `;
        refreshIcons();
        return;
    }
}
function applyProviderOnboardingDefaults(id){
    const item = providers.find(provider => provider.id === id);
    if(!item) return;
    if(id === 'modelscope'){
        item.base_url = MS_DEFAULT_BASE_URL;
        item.protocol = 'openai';
        item.image_models = unique([...MS_BUILTIN_IMAGE_MODELS, ...(item.image_models || [])]);
        item.chat_models = unique([...(item.chat_models || [])]);
        item.ms_defaults_version = Math.max(3, Number(item.ms_defaults_version || 0));
    } else if(id === 'runninghub'){
        item.base_url = normalizeRunningHubBaseUrl(item.base_url);
        item.protocol = 'runninghub';
        item.image_models = unique(item.image_models || []);
        item.chat_models = unique(item.chat_models || []);
        item.video_models = unique(item.video_models || []);
        ensureRunningHubLists(item);
    } else if(id === 'volcengine'){
        item.base_url = VOLCENGINE_DEFAULT_BASE_URL;
        item.protocol = 'volcengine';
        item.video_models = unique(item.video_models || []);
        item.volcengine_project_name = item.volcengine_project_name || VOLCENGINE_DEFAULT_PROJECT_NAME;
        item.volcengine_region = item.volcengine_region || VOLCENGINE_DEFAULT_REGION;
    } else if(id === 'ai-money'){
        item.name = 'laohu';
        item.base_url = AI_MONEY_DEFAULT_BASE_URL;
        item.protocol = 'openai';
        item.image_request_mode = 'openai';
        item.image_models = unique(item.image_models || []);
        item.chat_models = unique(item.chat_models || []);
        item.video_models = unique(item.video_models || []);
    } else if(id === 'agnes'){
        item.name = 'Agnes AI';
        item.base_url = AGNES_DEFAULT_BASE_URL;
        item.protocol = 'openai';
        item.image_request_mode = 'openai-json';
        item.image_models = unique(['agnes-image-2.1-flash', 'agnes-image-2.0-flash', ...(item.image_models || [])]);
        item.chat_models = unique(['agnes-2.0-flash', ...(item.chat_models || [])]);
        item.video_models = unique(['agnes-video-v2.0', ...(item.video_models || [])]);
    } else if(id === 'lingjing'){
        item.base_url = item.base_url || LINGJING_DEFAULT_BASE_URL;
        item.protocol = item.protocol || 'openai';
        item.image_request_mode = normalizeImageRequestMode(item.image_request_mode);
    } else if(id === 'jimeng'){
        applyCliProtocolDefaults(item, 'jimeng', true);
    } else if(id === 'codex'){
        applyCliProtocolDefaults(item, 'codex', true);
    } else if(id === 'gemini-cli'){
        applyCliProtocolDefaults(item, 'gemini-cli');
    }
    clearFetchedModelState();
    selectedId = item.id;
    renderEditor();
    setStatus(tr('api.autosaveHint') || '填写 Key 后自动保存');
}
function refreshProviderOnboarding(){
    renderProviderOnboarding(provider());
    refreshIcons();
}
function syncEditor(){
    const item = provider();
    if(!item) return;
    const oldId = item.id;
    const isBuiltin = item.id === 'comfly' || item.id === 'modelscope' || item.id === 'runninghub' || item.id === 'volcengine' || item.id === 'ai-money' || item.id === 'agnes' || item.id === 'jimeng';
    // 内置和自定义平台的 ID 都保持稳定；新建时若没有 ID 才生成一次。
    const nextId = isBuiltin ? item.id : deriveIdFromName(nameInput.value, item.id);
    item.id = nextId;
    if(oldId !== item.id) selectedId = item.id;
    item.name = nameInput.value.trim() || item.id;
    if(item.id === 'runninghub') ensureRunningHubRegions(item);
    const lockedApi = lockedRecommendedApi(item);
    const selectedProtocol = lockedApi
        ? lockedApi.protocol
        : item.id === 'modelscope'
        ? 'openai'
        : item.id === 'runninghub'
        ? 'runninghub'
        : item.id === 'volcengine'
        ? 'volcengine'
        : item.id === 'ai-money'
        ? 'openai'
        : (protocolInput?.value || 'openai');
    item.base_url = item.id === 'ai-money'
        ? AI_MONEY_DEFAULT_BASE_URL
        : CLI_PROTOCOLS.has(selectedProtocol)
        ? ''
        : selectedProtocol === 'runninghub'
        ? RUNNINGHUB_REGIONS[runningHubRegionFromItem(item)].baseUrl
        : baseInput.value.trim();
    // 固定平台不从协议下拉读取
    item.protocol = selectedProtocol;
    item.image_request_mode = normalizeImageRequestMode(
        item.id === 'modelscope' || item.id === 'runninghub' || item.id === 'volcengine' || item.id === 'ai-money' || CLI_PROTOCOLS.has(selectedProtocol)
            ? 'openai'
            : lockedApi
            ? lockedApi.image_request_mode
            : (imageRequestModeInput?.value || item.image_request_mode)
    );
    item.image_edit_route = normalizeImageEditRoute(
        item.id === 'modelscope' || item.id === 'runninghub' || item.id === 'volcengine' || item.id === 'ai-money' || CLI_PROTOCOLS.has(selectedProtocol)
            ? 'general'
            : (imageEditRouteInput?.value || item.image_edit_route)
    );
    item.image_generation_endpoint = '';
    item.image_edit_endpoint = '';
    item.rh_apps = normalizeRhEntries(item.rh_apps || [], 'app');
    item.rh_workflows = normalizeRhEntries(item.rh_workflows || [], 'workflow');
    const key = keyInput.value.trim();
    if(key) item.api_key = key;
    if(item.id === 'runninghub'){
        const activeRegion = runningHubRegionFromItem(item);
        item.base_url = RUNNINGHUB_REGIONS[activeRegion].baseUrl;
        const active = persistActiveRunningHubRegion(item);
        activateRunningHubRegion(item, activeRegion);
        const pendingApiKeys = {...(item._pendingRhApiKey || {})};
        const pendingWalletKeys = {...(item._pendingRhWalletKey || {})};
        Object.keys(RUNNINGHUB_REGIONS).forEach(region => {
            const freeKey = runningHubRegionInput(region, 'free')?.value.trim() || '';
            const walletKey = runningHubRegionInput(region, 'wallet')?.value.trim() || '';
            if(freeKey) pendingApiKeys[region] = freeKey;
            if(walletKey) pendingWalletKeys[region] = walletKey;
        });
        if(Object.keys(pendingApiKeys).length) item._pendingRhApiKey = pendingApiKeys;
        else delete item._pendingRhApiKey;
        if(Object.keys(pendingWalletKeys).length) item._pendingRhWalletKey = pendingWalletKeys;
        else delete item._pendingRhWalletKey;
    }
    if(item.id === 'volcengine'){
        const ak = volcAkInput?.value.trim() || '';
        const sk = volcSkInput?.value.trim() || '';
        if(ak) item.volcengine_access_key_id = ak;
        if(sk) item.volcengine_secret_access_key = sk;
        item.volcengine_project_name = (volcProjectInput?.value.trim() || VOLCENGINE_DEFAULT_PROJECT_NAME);
        item.volcengine_region = (volcRegionInput?.value.trim() || VOLCENGINE_DEFAULT_REGION);
    }
}
function ensureRunningHubLists(item){
    if(!item) return;
    ensureRunningHubRegions(item);
    activateRunningHubRegion(item, runningHubRegionFromItem(item));
    item.rh_apps = normalizeRhEntries(item.rh_apps || [], 'app');
    item.rh_workflows = normalizeRhEntries(item.rh_workflows || [], 'workflow');
    persistActiveRunningHubRegion(item);
}
function updateProtocolFromInput(){
    const item = provider();
    if(!item || !protocolInput || item.id === 'modelscope' || item.id === 'runninghub' || item.id === 'volcengine' || item.id === 'ai-money') return;
    if(applyLockedRecommendedProtocol(item)){
        protocolInput.value = item.protocol;
        if(imageRequestModeInput) imageRequestModeInput.value = item.image_request_mode;
        return;
    }
    const previousProtocol = String(item.protocol || '').toLowerCase();
    const value = String(protocolInput.value || 'openai').toLowerCase();
    item.protocol = API_PROTOCOLS.includes(value) ? value : 'openai';
    if(CLI_PROTOCOLS.has(item.protocol)) item.base_url = '';
    const protocolChanged = previousProtocol !== item.protocol;
    applyCliProtocolDefaults(item, item.protocol, protocolChanged);
    document.body.classList.toggle('show-jimeng', item.protocol === 'jimeng');
    document.body.classList.toggle('show-codex', item.protocol === 'codex');
    document.body.classList.toggle('show-gemini-cli', item.protocol === 'gemini-cli');
    clearVerifyResult();
    // 协议会改变整个表单（如即梦 CLI 账户面板、默认模型、Key 占位）。renderEditor 是唯一切换这些的入口，
    // 这里复跑一次让面板立即出现；保存并恢复 Key 输入框，避免推荐流程里先填的 Key 被 renderEditor 清空。
    const savedKey = keyInput ? keyInput.value : '';
    renderEditor();
    if(keyInput) keyInput.value = savedKey;
    updateApimartDomesticHint(item);
    void scheduleProviderAutosave({providerId:item.id, region:apiAutosaveRegion(item), immediate:true, sync:false});
}
function isVolcengineProvider(item){
    return String(item?.protocol || '').toLowerCase() === 'volcengine';
}
function handleRhPasteInput(value){
    const parsed = parseRunningHubRunRef(value);
    if(parsed?.type === 'app') setStatus('已识别 AI 应用 ID，点击右侧添加并同步');
    else if(parsed) setStatus('这里只支持 AI 应用，不支持工作流');
}
function runningHubRegionState(item, region){
    if(!item || item.id !== 'runninghub' || !RUNNINGHUB_REGIONS[region]) return null;
    const regions = ensureRunningHubRegions(item);
    if(!regions[region]) regions[region] = runningHubEmptyRegion(region);
    return regions[region];
}
function runningHubRegionEntries(item, region, kind='app'){
    const state = runningHubRegionState(item, region);
    if(!state) return [];
    const listKey = kind === 'app' ? 'rh_apps' : 'rh_workflows';
    state[listKey] = normalizeRhEntries(state[listKey] || [], kind);
    if(runningHubRegionFromItem(item) === region) item[listKey] = state[listKey];
    return state[listKey];
}
function runningHubRegionPendingKey(item, region){
    const free = item?._pendingRhApiKey?.[region] || runningHubRegionInput(region, 'free')?.value || '';
    const wallet = item?._pendingRhWalletKey?.[region] || runningHubRegionInput(region, 'wallet')?.value || '';
    return String(free || wallet || '').trim();
}
async function createRhEntryFromPaste(region=''){
    let item = provider();
    if(!item || item.id !== 'runninghub') return;
    const targetRegion = RUNNINGHUB_REGIONS[region] ? region : runningHubRegionFromItem(item);
    const pasteInput = runningHubRegionAppInput(targetRegion);
    const parsed = parseRunningHubRunRef(pasteInput?.value || '');
    if(!parsed || parsed.type !== 'app'){ setStatus('请输入 AI 应用 ID'); return; }
    const activeConfig = runningHubRegionState(item, targetRegion);
    if(activeConfig?.enabled !== true){
        setStatus(tr('api.rhSiteDisabled'));
        return false;
    }
    if(rhAppSyncState){
        setStatus(tr('api.rhAppSyncBusy'));
        return false;
    }
    const entries = runningHubRegionEntries(item, targetRegion, 'app');
    const pendingKey = runningHubRegionPendingKey(item, targetRegion);
    const currentEntry = entries.find(entry => String(entry?.id || entry?.appId || '') === parsed.id && entry?.hidden !== true);
    setRhAppSyncState({
        id:parsed.id,
        region:targetRegion,
        isNew:!currentEntry,
        phase:pendingKey && !activeConfig.has_key && !activeConfig.has_wallet_key ? tr('api.rhAppPhaseSaveKey') : tr('api.rhAppPhasePrepare')
    });
    if(pendingKey && !activeConfig.has_key && !activeConfig.has_wallet_key){
        setStatus('正在保存当前站点的 RunningHub Key...');
        if(!await saveProviders()){
            setRhAppSyncState(null);
            setStatus(tr('api.rhAppKeySaveFailed'));
            return false;
        }
        item = provider();
    }
    const targetEntries = runningHubRegionEntries(item, targetRegion, 'app');
    const previousEntries = JSON.parse(JSON.stringify(targetEntries));
    const existingIndex = targetEntries.findIndex(entry => String(entry?.id || entry?.appId || '').trim() === parsed.id);
    const exists = existingIndex >= 0 && targetEntries[existingIndex]?.hidden !== true;
    if(existingIndex >= 0 && targetEntries[existingIndex]?.hidden === true){
        targetEntries[existingIndex] = {
            ...targetEntries[existingIndex],
            enabled:true,
            hidden:false
        };
    } else if(!exists){
        targetEntries.unshift({
            id:parsed.id,
            appId:parsed.id,
            title:`AI 应用 ${parsed.id.slice(-6)}`,
            note:'',
            thumbnail:'',
            enabled:true
        });
    }
    runningHubRegionState(item, targetRegion).rh_apps = targetEntries;
    updateRhAppSyncPhase(tr('api.rhAppPhaseRead'));
    setStatus(exists ? '正在重新同步 AI 应用...' : '正在验证并同步 AI 应用...');
    try {
        const current = provider();
        const currentEntries = current?.id === 'runninghub' ? runningHubRegionEntries(current, targetRegion, 'app') : [];
        const targetIndex = current?.id === 'runninghub'
            ? currentEntries.findIndex(entry => String(entry?.id || entry?.appId || '') === parsed.id)
            : -1;
        if(targetIndex < 0) throw new Error('应用没有写入当前站点，请切换到对应站点后重试');
        const synced = await syncRhAppFromOfficial(targetIndex, targetRegion);
        if(!synced) throw new Error('官方信息已读取，但保存配置失败');
        if(pasteInput) pasteInput.value = '';
        setRhAppSyncState(null);
        setStatus(tr('api.rhAppSaved'));
    } catch(error) {
        const regions = ensureRunningHubRegions(item);
        regions[targetRegion].rh_apps = JSON.parse(JSON.stringify(previousEntries));
        const rollbackSaved = await saveProviders();
        setRhAppSyncState(null);
        const rollbackHint = rollbackSaved ? '' : tr('api.rhAppRollbackFailed');
        setStatus(trf('api.rhAppValidationFailed', {error:error.message || '无法读取官方配置', rollback:rollbackHint}));
        return false;
    }
}
async function syncRhAppFromOfficial(index, region=''){
    let item = provider();
    if(!item || item.id !== 'runninghub') return false;
    const targetRegion = RUNNINGHUB_REGIONS[region] ? region : runningHubRegionFromItem(item);
    const regionState = runningHubRegionState(item, targetRegion);
    if(regionState?.enabled !== true){
        setStatus(tr('api.rhSiteDisabled'));
        return false;
    }
    const entries = runningHubRegionEntries(item, targetRegion, 'app');
    let entry = entries[index];
    const appId = String(entry?.appId || entry?.id || '').trim();
    if(!appId) return false;
    setStatus('正在从 RunningHub 同步 AI 应用信息...');
    const res = await fetch(`/api/runninghub/app-info?webappId=${encodeURIComponent(appId)}&region=${encodeURIComponent(targetRegion)}`);
    const data = await readApiResponse(res, '拉取 AI 应用信息失败');
    if(data.success === false) throw new Error(apiResponseDetail(data, '拉取 AI 应用信息失败'));
    // 等待网络期间可能切换页面或保存了其他配置，重新定位原站点条目。
    item = providers.find(candidate => candidate?.id === 'runninghub');
    if(!item || runningHubRegionState(item, targetRegion)?.enabled !== true) return false;
    entry = runningHubRegionEntries(item, targetRegion, 'app').find(candidate => String(candidate?.appId || candidate?.id || '') === appId && candidate.hidden !== true);
    if(!entry) throw new Error(tr('api.rhAppMissing'));
    const raw = data.data || {};
    const officialTitle = String(raw.webappName || raw.title || raw.name || '').trim();
    if(!officialTitle || !Array.isArray(raw.nodeInfoList)){
        throw new Error('RunningHub 返回的应用资料不完整，请确认应用 ID 与当前站点一致');
    }
    entry.id = appId;
    entry.appId = appId;
    entry.title = officialTitle;
    entry.title_zh = String(raw.webappNameZh || raw.titleZh || raw.nameZh || '').trim();
    entry.title_en = String(raw.webappNameEn || raw.titleEn || raw.nameEn || '').trim();
    entry.titles = raw.titles && typeof raw.titles === 'object' ? {...raw.titles} : {};
    entry.names = raw.names && typeof raw.names === 'object' ? {...raw.names} : {};
    entry.localizedNames = raw.localizedNames && typeof raw.localizedNames === 'object' ? {...raw.localizedNames} : {};
    entry.webappNames = raw.webappNames && typeof raw.webappNames === 'object' ? {...raw.webappNames} : {};
    entry.note = String(raw.descriptionText || raw.description || raw.descriptionCn || '');
    entry.thumbnail = String(raw.covers?.[0]?.thumbnailUri || raw.covers?.[0]?.url || '');
    entry.tags = Array.isArray(raw.tags) ? raw.tags : [];
    entry.fields = rhAppFieldSourceList(raw).map(normalizeFetchedRhAppField);
    entry.raw = raw;
    entry.schemaSyncedAt = Date.now();
    entry.enabled = true;
    entry.hidden = false;
    if(rhAppSyncState?.id === appId) updateRhAppSyncPhase(tr('api.rhAppPhaseSave'));
    const saved = await scheduleProviderAutosave({providerId:item.id, region:targetRegion, immediate:true, sync:false});
    if(!saved) return false;
    const savedProvider = providers.find(candidate => candidate?.id === 'runninghub');
    const savedRegion = savedProvider?.rh_regions?.[targetRegion];
    const persisted = [
        ...(savedRegion?.rh_apps || [])
    ].some(candidate => String(candidate?.id || candidate?.appId || '') === appId && candidate?.hidden !== true);
    if(!persisted) throw new Error('服务器未返回已保存的 AI 应用 ID，请检查当前站点和配置保存状态');
    renderRunningHubCards();
    setStatus(tr('api.rhAppSaved'));
    return true;
}
function updateRhEntry(kind, index, prop, value, region=''){
    const item = provider();
    if(!item || item.id !== 'runninghub') return;
    const targetRegion = RUNNINGHUB_REGIONS[region] ? region : runningHubRegionFromItem(item);
    const regionState = runningHubRegionState(item, targetRegion);
    if(regionState?.enabled !== true){
        setStatus(tr('api.rhSiteDisabled'));
        return;
    }
    const entries = runningHubRegionEntries(item, targetRegion, kind);
    if(!entries[index]) return;
    entries[index][prop] = value;
    void scheduleProviderAutosave({providerId:item.id, region:targetRegion, immediate:false, sync:false});
}
function isStaticRunningHubEntry(kind, entry){
    const id = String((kind === 'app' ? (entry?.appId || entry?.id) : (entry?.workflowId || entry?.id)) || '').trim();
    const thumb = String(entry?.thumbnail || '');
    if(thumb.includes('/static/runninghub/')) return true;
    if(id && thumb.includes(`${kind === 'app' ? 'app' : 'workflow'}-${id}`)) return true;
    // 静态模板会随 /api/providers 合并返回完整字段；手动粘贴的新卡片通常没有这些配置。
    return Array.isArray(entry?.fields) || (entry?.workflowJson && typeof entry.workflowJson === 'object') || (entry?.raw && typeof entry.raw === 'object');
}
async function removeRhEntry(kind, index, region=''){
    const item = provider();
    if(!item || item.id !== 'runninghub') return;
    const targetRegion = RUNNINGHUB_REGIONS[region] ? region : runningHubRegionFromItem(item);
    const regionState = runningHubRegionState(item, targetRegion);
    if(regionState?.enabled !== true){
        setStatus(tr('api.rhSiteDisabled'));
        return false;
    }
    const listKey = kind === 'app' ? 'rh_apps' : 'rh_workflows';
    const entries = runningHubRegionEntries(item, targetRegion, kind);
    const entry = entries[index];
    if(!entry) return;
    const previousEntries = JSON.parse(JSON.stringify(entries || []));
    const entryId = String((kind === 'workflow' ? (entry.workflowId || entry.id) : (entry.appId || entry.id)) || '').trim();
    if(isStaticRunningHubEntry(kind, entry)){
        entries[index] = {
            ...entry,
            enabled:false,
            hidden:true
        };
    } else {
        entries.splice(index, 1);
    }
    regionState[listKey] = entries;
    renderRunningHubCards();
    setStatus('已删除，正在保存...');
    let workflowBodyDeleted = false;
    if(kind === 'workflow' && entryId){
        try {
            const response = await fetch(`/api/runninghub/workflows/${encodeURIComponent(entryId)}?region=${encodeURIComponent(targetRegion)}`, {method:'DELETE'});
            if(!response.ok) throw new Error('工作流主体删除失败');
            workflowBodyDeleted = true;
        } catch(error) {
            regionState[listKey] = previousEntries;
            renderRunningHubCards();
            setStatus(error.message || '删除失败');
            return;
        }
    }
    const ok = await saveProviders();
    if(ok){
        setStatus('已删除并保存');
    } else {
        if(workflowBodyDeleted){
            renderRunningHubCards();
            setStatus('工作流主体已删除，但平台目录保存失败；请刷新后重试');
            return;
        }
        regionState[listKey] = previousEntries;
        renderRunningHubCards();
        setStatus('删除未保存，已恢复原列表');
    }
}
function readFileAsDataUrl(file){
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(reader.error || new Error('读取图片失败'));
        reader.readAsDataURL(file);
    });
}
function loadImageForThumbnail(src){
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error('图片解析失败'));
        img.src = src;
    });
}
async function createRhThumbnailDataUrl(file){
    const original = await readFileAsDataUrl(file);
    try {
        const img = await loadImageForThumbnail(original);
        const maxSide = 360;
        const scale = Math.min(1, maxSide / Math.max(img.naturalWidth || img.width || 1, img.naturalHeight || img.height || 1));
        const width = Math.max(1, Math.round((img.naturalWidth || img.width || 1) * scale));
        const height = Math.max(1, Math.round((img.naturalHeight || img.height || 1) * scale));
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(img, 0, 0, width, height);
        return canvas.toDataURL('image/jpeg', 0.78);
    } catch(e) {
        return original;
    }
}
function pickRhThumbnail(kind, index){
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = async () => {
        const file = input.files?.[0];
        if(!file) return;
        try {
            const thumbnail = await createRhThumbnailDataUrl(file);
            updateRhEntry(kind, index, 'thumbnail', thumbnail);
            renderRunningHubCards();
            setStatus(tr('api.autosaving') || '正在自动保存');
        } catch(e) {
            await StudioDialog.alert(e.message || '上传缩略图失败', {type:'warning'});
        }
    };
    input.click();
}
function isCurrentRhWorkflowDraft(draft){
    return Boolean(draft
        && rhWorkflowEditorState === draft.stateRef
        && rhWorkflowAutosaveRevision === draft.revision
        && rhWorkflowEditorState.open);
}
function clearRhWorkflowAutosaveTimer(){
    if(rhWorkflowAutosaveTimer) clearTimeout(rhWorkflowAutosaveTimer);
    rhWorkflowAutosaveTimer = null;
}
function updateRunningHubEditorEntry(draft, config){
    const item = providers.find(candidate => candidate?.id === draft.providerId);
    if(!item || item.id !== 'runninghub') throw new Error('RunningHub 平台已不存在');
    const regions = ensureRunningHubRegions(item);
    const regionState = regions[draft.region] || runningHubEmptyRegion(draft.region);
    const listKey = draft.mode === 'app' ? 'rh_apps' : 'rh_workflows';
    const entryId = String(draft.entryId || '').trim();
    const entries = normalizeRhEntries(regionState[listKey] || [], draft.mode);
    const entry = entries.find(candidate => String((draft.mode === 'app'
        ? (candidate?.appId || candidate?.id)
        : (candidate?.workflowId || candidate?.id)) || '').trim() === entryId);
    if(!entry) throw new Error('RunningHub 当前站点目录中找不到正在编辑的条目');
    entry.title = config.title || entry.title || entryId;
    entry.note = config.description || '';
    entry.fields = (config.fields || []).map(normalizeRhWorkflowField);
    if(draft.mode === 'workflow'){
        entry.workflowJson = config.workflowJson || {};
        entry.optionalImageMode = config.optionalImageMode || 'prune-workflow';
        entry.updatedAt = Number(config.updatedAt || Date.now());
    }
    entry.raw = config.raw || {};
    regionState[listKey] = entries;
    regions[draft.region] = regionState;
    item.rh_regions = regions;
    if(runningHubRegionFromItem(item) === draft.region){
        activateRunningHubRegion(item, draft.region);
        renderRunningHubCards();
    }
    return item;
}
async function persistRhWorkflowEditorDraft(draft){
    const config = cloneApiSettingsValue(draft.config) || {};
    if(draft.mode === 'workflow'){
        const res = await fetch(`/api/runninghub/workflows/${encodeURIComponent(config.workflowId)}`, {
            method:'PUT',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({
                workflowId:config.workflowId,
                title:config.title,
                description:config.description,
                fields:(config.fields || []).map(normalizeRhWorkflowField),
                workflowJson:config.workflowJson || {},
                optionalImageMode:config.optionalImageMode || 'prune-workflow',
                raw:config.raw || {}
            })
        });
        const data = await res.json();
        if(!res.ok || data.success === false) throw new Error(data.detail || '保存失败');
        Object.assign(config, data.workflow || {});
        config.updatedAt = Number(data.workflow?.updatedAt || Date.now());
    }
    const item = updateRunningHubEditorEntry(draft, config);
    const saved = await scheduleProviderAutosave({
        providerId:item.id,
        region:draft.region,
        immediate:true,
        sync:false,
    });
    if(!saved) throw new Error('RunningHub 条目已经修改，但平台配置保存失败');
    if(isCurrentRhWorkflowDraft(draft)){
        setStatus(tr('api.autosaved'));
        if(draft.mode === 'workflow') broadcastStudioApiChange('workflows-changed');
        else broadcastStudioApiChange('providers-changed');
    }
    return true;
}
function flushRhWorkflowEditorAutosave(waitForWrite=false){
    clearRhWorkflowAutosaveTimer();
    const draft = rhWorkflowAutosavePending;
    if(!draft) return waitForWrite ? rhWorkflowAutosaveSerial : Promise.resolve(false);
    rhWorkflowAutosavePending = null;
    const write = rhWorkflowAutosaveSerial.then(() => persistRhWorkflowEditorDraft(draft));
    rhWorkflowAutosaveSerial = write.catch(error => {
        if(isCurrentRhWorkflowDraft(draft)) setStatus(error.message || tr('api.autosaveFailed'));
        return false;
    });
    return waitForWrite ? rhWorkflowAutosaveSerial : write;
}
function scheduleRhWorkflowEditorAutosave(immediate=false){
    const state = rhWorkflowEditorState;
    if(!state.open || !state.config) return Promise.resolve(false);
    clearRhWorkflowAutosaveTimer();
    const item = provider();
    const revision = ++rhWorkflowAutosaveRevision;
    rhWorkflowAutosavePending = {
        stateRef:state,
        revision,
        mode:rhEditorMode,
        providerId:item?.id || 'runninghub',
        region:apiAutosaveRegion(item, currentRunningHubRegion(item)),
        entryId:String(state.entry?.appId || state.entry?.workflowId || state.entry?.id || '').trim(),
        config:cloneApiSettingsValue(state.config)
    };
    setStatus(tr('api.autosaving') || tr('api.saving'));
    if(immediate) return flushRhWorkflowEditorAutosave(true);
    rhWorkflowAutosaveTimer = setTimeout(() => {
        rhWorkflowAutosaveTimer = null;
        void flushRhWorkflowEditorAutosave(false);
    }, API_AUTOSAVE_DELAY);
    return Promise.resolve(true);
}
async function openRhWorkflowEditor(index){
    if(rhWorkflowEditorState.open) await flushRhWorkflowEditorAutosave(true);
    const item = provider();
    if(!item || item.id !== 'runninghub') return;
    ensureRunningHubLists(item);
    const entry = item.rh_workflows[index];
    if(!entry) return;
    rhEditorMode = 'workflow';
    rhWorkflowEditorState = { open:true, index, entry, config:null, expanded:{}, activeNodeId:'', graph:{ k:1, x:0, y:0, w:0, h:0 }, pan:null, bound:false, previewParams:{}, previewRunning:false, previewStatus:'', previewOutputs:[] };
    if(rhWorkflowEditorOverlay) rhWorkflowEditorOverlay.classList.add('open');
    renderRhWorkflowEditorLoading('正在加载工作流...');
    refreshIcons();
    try {
        await loadRhWorkflowEditorConfig(entry);
    } catch(e) {
        renderRhWorkflowEditorLoading(e.message || '工作流加载失败');
    }
}
function closeRhWorkflowEditor(){
    void flushRhWorkflowEditorAutosave(false);
    if(rhWorkflowEditorOverlay) rhWorkflowEditorOverlay.classList.remove('open');
    rhWorkflowEditorState.open = false;
}
function renderRhWorkflowEditorLoading(text){
    if(rhWorkflowEditorTitle) rhWorkflowEditorTitle.textContent = rhWorkflowEditorState.entry?.title || (rhEditorMode === 'app' ? 'RunningHub AI 应用' : 'RunningHub 工作流');
    if(rhWorkflowEditName) rhWorkflowEditName.value = rhWorkflowEditorState.entry?.title || '';
    if(rhWorkflowEditNote) rhWorkflowEditNote.value = rhWorkflowEditorState.entry?.note || '';
    if(rhWorkflowEditorSub) rhWorkflowEditorSub.textContent = '';
    if(rhWorkflowEditorSummary) rhWorkflowEditorSummary.innerHTML = `<div class="rh-editor-empty">${escapeHtml(text)}</div>`;
    if(rhWorkflowEditorNodeList) rhWorkflowEditorNodeList.innerHTML = '';
    if(rhEditorMode === 'workflow') {
        restoreRhGraphWrap();
        if(rhWorkflowEditorGraphSvg) rhWorkflowEditorGraphSvg.innerHTML = '';
    } else if(rhWorkflowEditorGraphWrap) {
        rhWorkflowEditorGraphWrap.classList.add('rh-app-field-wrap');
        rhWorkflowEditorGraphWrap.innerHTML = `<div class="rh-editor-empty">${escapeHtml(text)}</div>`;
    }
}
async function loadRhWorkflowEditorConfig(entry){
    let config = null;
    const workflowId = String(entry.workflowId || entry.id || '').trim();
    if(!workflowId) throw new Error('workflowId 为空');
    const existing = await fetch(`/api/runninghub/workflows/${encodeURIComponent(workflowId)}`).then(async r => {
        if(r.status === 404) return null;
        const data = await r.json();
        if(!r.ok) throw new Error(data.detail || '读取工作流配置失败');
        return data.workflow || null;
    });
    if(existing) {
        config = existing;
    } else {
        config = await fetchRhWorkflowEditor(false);
        return config;
    }
    rhWorkflowEditorState.config = normalizeRhWorkflowConfig(config, entry);
    renderRhWorkflowEditor();
    setTimeout(() => rhEditorGraphFit(), 50);
    return rhWorkflowEditorState.config;
}
function normalizeRhWorkflowConfig(config, entry){
    const workflowId = String(config?.workflowId || entry?.workflowId || entry?.id || '').trim();
    const normalized = {
        workflowId,
        title:String(config?.title || entry?.title || workflowId),
        description:String(config?.description || entry?.note || ''),
        fields:(Array.isArray(config?.fields) ? config.fields : []).map(normalizeRhWorkflowField),
        workflowJson:config?.workflowJson || {},
        optionalImageMode:String(config?.optionalImageMode || entry?.optionalImageMode || 'prune-workflow'),
        raw:config?.raw || {}
    };
    return applyRhImageSlotDefaults(normalized);
}
function applyRhImageSlotDefaults(config){
    const imageFields = (config.fields || []).filter(field => rhWorkflowFieldKind(field) === 'IMAGE');
    imageFields.forEach((field, index) => {
        if(!Number(field.imageOrder)) field.imageOrder = index + 1;
        if(field.required !== true && field.required !== false) field.required = index === 0;
        if(index === 0 && field.required !== false) field.required = true;
    });
    config.optionalImageMode = config.optionalImageMode || 'prune-workflow';
    return config;
}
function setRhWorkflowOptionalImageMode(value){
    const config = rhWorkflowEditorState.config;
    if(!config || rhEditorMode !== 'workflow') return;
    config.optionalImageMode = value || 'prune-workflow';
    withRhEditorScrollPreserved(() => renderRhMappedPreview());
    void scheduleRhWorkflowEditorAutosave(true);
}
function rhAppFieldSourceList(raw){
    const data = raw?.data && typeof raw.data === 'object' ? raw.data : raw;
    const candidates = [
        data?.nodeInfoList,
        data?.fields,
        data?.inputs,
        data?.inputList,
        data?.formItems,
        data?.forms,
        data?.params,
        data?.parameters,
        data?.apiParams,
        data?.config?.fields,
        data?.webapp?.fields,
        data?.webapp?.inputs
    ];
    for(const candidate of candidates){
        if(Array.isArray(candidate) && candidate.length) return candidate;
        if(candidate && typeof candidate === 'object' && Object.keys(candidate).length){
            return Object.entries(candidate).map(([key, value]) => ({fieldName:key, fieldValue:value}));
        }
    }
    return [];
}
function parseRhOfficialFieldData(value){
    if(typeof SmartNodeContract !== 'undefined' && typeof SmartNodeContract.parseRunningHubOfficialFieldData === 'function'){
        return SmartNodeContract.parseRunningHubOfficialFieldData(value);
    }
    const result = {
        type:'',
        options:[],
        optionLabels:{},
        min:'',
        max:'',
        step:'',
        defaultValue:undefined,
        required:false,
        acceptsUpload:false
    };
    if(typeof value === 'string'){
        try{ value = JSON.parse(value); }
        catch(_error){ return result; }
    }
    if(!Array.isArray(value) || !value.length) return result;
    const knownTypes = new Set(['STRING','TEXT','FLOAT','NUMBER','INT','INTEGER','BOOLEAN','BOOL','SWITCH','SELECT','COMBO','IMAGE','VIDEO','AUDIO']);
    const first = typeof value[0] === 'string' ? value[0].trim().toUpperCase() : '';
    let payload = value;
    if(knownTypes.has(first)){
        result.type = first;
        payload = value.slice(1);
    }
    const metadata = payload.find(item => item && typeof item === 'object' && !Array.isArray(item)
        && ['min','max','step','default','defaultValue','required','acceptsUpload','options','image_upload','video_upload','audio_upload','inputRole','input_role','semanticRole','semantic_role','role'].some(key => Object.prototype.hasOwnProperty.call(item, key)));
    if(metadata){
        result.min = metadata.min ?? '';
        result.max = metadata.max ?? '';
        result.step = metadata.step ?? '';
        result.defaultValue = metadata.defaultValue ?? metadata.default;
        result.required = metadata.required === true;
        result.acceptsUpload = metadata.acceptsUpload === true
            || metadata.image_upload === true
            || metadata.video_upload === true
            || metadata.audio_upload === true;
        result.role = String(metadata.inputRole ?? metadata.input_role ?? metadata.semanticRole ?? metadata.semantic_role ?? metadata.role ?? '').trim();
        if(metadata.image_upload === true) result.type = 'IMAGE';
        else if(metadata.video_upload === true) result.type = 'VIDEO';
        else if(metadata.audio_upload === true) result.type = 'AUDIO';
    }
    const nestedOptions = payload.find(item => Array.isArray(item) && item.some(option => option && typeof option === 'object' && !Array.isArray(option)));
    const optionSource = Array.isArray(metadata?.options) ? metadata.options : nestedOptions || payload;
    const optionItems = optionSource.filter(item => {
        if(item == null || item === metadata) return false;
        if(typeof item === 'object') return 'index' in item || 'value' in item || 'name' in item || 'label' in item;
        return Array.isArray(metadata?.options) && !knownTypes.has(String(item).trim().toUpperCase());
    });
    optionItems.forEach(item => {
        const submitValue = item && typeof item === 'object'
            ? item.index ?? item.value ?? item.name
            : item;
        if(submitValue === undefined || submitValue === null) return;
        const valueKey = String(submitValue);
        if(!valueKey || result.options.includes(valueKey)) return;
        result.options.push(valueKey);
        if(item && typeof item === 'object'){
            result.optionLabels[valueKey] = String(item.description ?? item.label ?? item.title ?? item.name ?? valueKey);
        }
    });
    if(['IMAGE','VIDEO','AUDIO'].includes(result.type)) result.acceptsUpload = true;
    return result;
}
function normalizeFetchedRhAppField(field, index=0){
    const name = field?.fieldName || field?.inputName || field?.name || field?.key || field?.paramName || field?.id || `field_${index + 1}`;
    const nodeId = field?.nodeId || field?.node_id || field?.groupId || 'app';
    const official = parseRhOfficialFieldData(field?.fieldData);
    let value = field?.fieldValue;
    if(value === undefined) value = field?.defaultValue;
    if(value === undefined) value = field?.value;
    if(value === undefined) value = field?.default;
    if(value === undefined) value = official.defaultValue;
    if(value === undefined || value === null) value = '';
    if(typeof value === 'object') value = JSON.stringify(value);
    if(!official.options.length) official.options = extractRhEditorFieldOptions(field, false);
    const officialType = official.type || field?.fieldType || field?.type || field?.valueType || (official.options.length ? 'SELECT' : '');
    if(['IMAGE','VIDEO','AUDIO'].includes(String(officialType).toUpperCase())) official.acceptsUpload = true;
    return normalizeRhWorkflowField({
        id:field?.id || `${nodeId}::${name}`,
        nodeId,
        fieldName:name,
        fieldValue:value,
        fieldType:officialType,
        inputRole:field?.inputRole ?? field?.input_role ?? field?.semanticRole ?? field?.semantic_role ?? field?.role ?? official.role ?? '',
        label:field?.label || field?.title || field?.description || field?.name || name,
        enabled:true,
        group:field?.group || field?.category || field?.title || 'AI 应用参数',
        note:field?.note || field?.description || '',
        options:official.options,
        optionLabels:official.optionLabels,
        acceptsUpload:official.acceptsUpload,
        required:field?.required === true || official.required,
        min:official.min !== '' ? official.min : field?.min ?? '',
        max:official.max !== '' ? official.max : field?.max ?? '',
        step:official.step !== '' ? official.step : field?.step ?? '',
        officialSchema:true
    });
}
function extractRhEditorFieldOptions(field, allowKnown=true){
    const candidates = [field?.options, field?.optionList, field?.values, field?.enum, field?.choices, field?.items, field?.list, field?.selectOptions];
    for(const candidate of candidates){
        if(!Array.isArray(candidate) || !candidate.length) continue;
        return candidate.map(item => {
            if(item && typeof item === 'object') return item.value ?? item.label ?? item.name ?? item.title;
            return item;
        }).filter(item => item !== undefined && item !== null).map(String);
    }
    const known = allowKnown ? rhKnownOptionsForField(field) : [];
    if(known.length) return known;
    return [];
}
async function fetchRhWorkflowEditor(force=false){
    if(force) await flushRhWorkflowEditorAutosave(true);
    const state = rhWorkflowEditorState;
    const entry = state.entry;
    if(!entry) return null;
    const workflowId = String(entry.workflowId || entry.id || '').trim();
    if(!workflowId) throw new Error('workflowId 为空');
    if(force) renderRhWorkflowEditorLoading('正在重新拉取...');
    const res = await fetch('/api/runninghub/workflows/fetch', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
            workflowId,
            title:rhWorkflowEditName?.value.trim() || entry.title || workflowId,
            description:rhWorkflowEditNote?.value.trim() || entry.note || ''
        })
    });
    const data = await res.json();
    if(!res.ok || data.success === false) throw new Error(data.detail || '拉取工作流失败');
    state.config = normalizeRhWorkflowConfig({
        workflowId:data.data.workflowId,
        title:data.data.title,
        description:data.data.description,
        fields:(data.data.fields || []).map(normalizeFetchedRhWorkflowField),
        workflowJson:data.data.workflowJson || {},
        optionalImageMode:entry.optionalImageMode || 'prune-workflow',
        raw:data.data.raw || {}
    }, entry);
    state.graph = { k:1, x:0, y:0, w:0, h:0 };
    renderRhWorkflowEditor();
    setTimeout(() => rhEditorGraphFit(), 50);
    return state.config;
}
function updateRhWorkflowEditorMeta(prop, value){
    const config = rhWorkflowEditorState.config;
    if(!config) return;
    if(prop === 'title') config.title = value;
    if(prop === 'description') config.description = value;
    withRhEditorScrollPreserved(() => renderRhMappedPreview());
    void scheduleRhWorkflowEditorAutosave(false);
}
function toggleRhWorkflowEditorGroup(groupId){
    const expanded = rhWorkflowEditorState.expanded;
    expanded[groupId] = expanded[groupId] === false;
    withRhEditorScrollPreserved(() => renderRhWorkflowEditor());
}
function focusRhWorkflowEditorNode(nodeId){
    const state = rhWorkflowEditorState;
    const config = state.config;
    if(!config) return;
    state.activeNodeId = String(nodeId || '');
    (config.fields || []).forEach(field => {
        if(String(field.nodeId) === state.activeNodeId){
            const groupId = rhWorkflowGroupKey(field).replace(/[^a-zA-Z0-9_-]/g, '_');
            state.expanded[groupId] = true;
        }
    });
    withRhEditorScrollPreserved(() => renderRhWorkflowEditor());
}
function openRhWorkflowNodePopover(nodeId, anchorEl){
    const state = rhWorkflowEditorState;
    state.activeNodeId = String(nodeId || '');
    renderRhWorkflowEditorGraph();
    const freshAnchor = Array.from(document.querySelectorAll('.rh-editor-gnode')).find(el => el.dataset.nodeId === state.activeNodeId) || anchorEl;
    renderRhNodePopover(state.activeNodeId, freshAnchor);
}
function closeRhNodePopover(){
    document.getElementById('rhNodePopover')?.remove();
}
function renderRhNodePopover(nodeId, anchorEl){
    closeRhNodePopover();
    const config = rhWorkflowEditorState.config;
    if(!config) return;
    const fields = (config.fields || []).filter(field => String(field.nodeId) === String(nodeId));
    if(!fields.length) return;
    const pop = document.createElement('div');
    pop.id = 'rhNodePopover';
    pop.className = 'rh-node-popover';
    pop.dataset.nodeId = String(nodeId || '');
    const workflowNode = config.workflowJson?.[nodeId] || {};
    const title = (workflowNode?._meta?.title || workflowNode?.class_type || fields[0]?.group || `Node #${nodeId}`).toString();
    pop.innerHTML = `
        <div class="rh-popover-head">
            <div>
                <strong>${escapeHtml(title)}</strong>
                <span>#${escapeHtml(nodeId)} · ${fields.length}</span>
            </div>
            <button type="button" onclick="closeRhNodePopover()"><i data-lucide="x" class="w-3.5 h-3.5"></i></button>
        </div>
        <div class="rh-popover-body">${fields.map(field => renderRhWorkflowEditorField(field)).join('')}</div>
    `;
    document.body.appendChild(pop);
    const rect = anchorEl?.getBoundingClientRect?.();
    const modalRect = rhWorkflowEditorOverlay?.getBoundingClientRect?.() || {left:0, top:0, right:window.innerWidth, bottom:window.innerHeight};
    let left = rect ? rect.right + 12 : window.innerWidth / 2 - 190;
    let top = rect ? rect.top : window.innerHeight / 2 - 180;
    const width = 390;
    if(left + width > modalRect.right - 16) left = Math.max(modalRect.left + 16, (rect?.left || left) - width - 12);
    top = Math.max(modalRect.top + 74, Math.min(top, modalRect.bottom - 420));
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
    refreshIcons();
}
function toggleRhWorkflowEditorField(key){
    const config = rhWorkflowEditorState.config;
    if(!config) return;
    withRhEditorScrollPreserved(() => {
        config.fields = (config.fields || []).map(field => {
            if(rhWorkflowFieldKey(field) !== key) return field;
            return {...field, enabled: field.enabled !== true};
        });
        renderRhWorkflowEditor();
        if(rhEditorMode === 'workflow' && rhWorkflowEditorState.activeNodeId) {
            const active = document.querySelector(`.rh-editor-gnode[data-node-id="${rhWorkflowEditorState.activeNodeId}"]`);
            if(active) renderRhNodePopover(rhWorkflowEditorState.activeNodeId, active);
        } else if(rhEditorMode === 'app') {
            const active = findRhAppFieldCard(key);
            if(active) openRhAppFieldPopover(key, active);
        }
    });
    void scheduleRhWorkflowEditorAutosave(true);
}
function updateRhWorkflowEditorField(key, prop, value){
    const config = rhWorkflowEditorState.config;
    if(!config) return;
    config.fields = (config.fields || []).map(field => {
        if(rhWorkflowFieldKey(field) !== key) return field;
        const nextValue = prop === 'imageOrder' ? Math.max(1, Number(value) || 1) : prop === 'required' ? Boolean(value) : value;
        return {...field, [prop]: nextValue};
    });
    if(prop === 'random_enabled' || prop === 'fieldType' || prop === 'required' || prop === 'sourceFromUpstream'){
        withRhEditorScrollPreserved(() => {
            renderRhWorkflowEditor();
            if(rhEditorMode === 'workflow' && rhWorkflowEditorState.activeNodeId) {
                const active = document.querySelector(`.rh-editor-gnode[data-node-id="${rhWorkflowEditorState.activeNodeId}"]`);
                if(active) renderRhNodePopover(rhWorkflowEditorState.activeNodeId, active);
            } else if(rhEditorMode === 'app') {
                const active = findRhAppFieldCard(key);
                if(active) openRhAppFieldPopover(key, active);
            }
        });
    }
    void scheduleRhWorkflowEditorAutosave(['random_enabled','fieldType','required','sourceFromUpstream'].includes(prop));
}
async function saveRhWorkflowEditor(){
    const state = rhWorkflowEditorState;
    const config = state.config;
    if(!config){ await StudioDialog.alert(rhEditorMode === 'app' ? '请先加载应用参数' : '请先加载工作流', {type:'warning'}); return; }
    config.title = rhWorkflowEditName?.value.trim() || config.title || config.workflowId;
    config.description = rhWorkflowEditNote?.value.trim() || config.description || '';
    return scheduleRhWorkflowEditorAutosave(true);
}
function renderRhWorkflowEditor(){
    const config = rhWorkflowEditorState.config;
    if(!config){ renderRhWorkflowEditorLoading(rhEditorMode === 'app' ? '应用参数未加载' : '工作流未加载'); return; }
    if(rhWorkflowEditorTitle) rhWorkflowEditorTitle.textContent = config.title || (rhEditorMode === 'app' ? 'RunningHub AI 应用' : 'RunningHub 工作流');
    if(rhWorkflowEditorSub) rhWorkflowEditorSub.textContent = '';
    if(rhWorkflowEditName) rhWorkflowEditName.value = config.title || '';
    if(rhWorkflowEditNote) rhWorkflowEditNote.value = config.description || '';
    applyRhImageSlotDefaults(config);
    renderRhMappedPreview();
    renderRhEditorSourcePane();
    refreshIcons();
}
function renderRhMappedPreview(){
    const config = rhWorkflowEditorState.config;
    if(!config || !rhWorkflowEditorSummary || !rhWorkflowEditorNodeList) return;
    renderRhWorkflowEditorSummary();
    rhWorkflowEditorNodeList.innerHTML = renderRhMappedPreviewHtml(config);
    refreshIcons();
}
function renderRhMappedPreviewHtml(config){
    const enabledFields = rhEditorSortedFields((config.fields || []).filter(field => field.enabled === true));
    const title = config.title || (rhEditorMode === 'app' ? 'RunningHub AI 应用' : 'RunningHub 工作流');
    const mediaCounts = enabledFields.reduce((acc, field) => {
        const kind = rhWorkflowFieldKind(field);
        if(kind === 'IMAGE') acc.image += 1;
        else if(kind === 'VIDEO') acc.video += 1;
        else if(kind === 'AUDIO') acc.audio += 1;
        else acc.setting += 1;
        return acc;
    }, {image:0, video:0, audio:0, setting:0});
    const fieldsHtml = enabledFields.length
        ? enabledFields.map(field => renderRhPreviewControl(field)).join('')
        : `<div class="rh-preview-empty">勾选右侧参数后，这里会显示画布节点上的效果</div>`;
    const statusHtml = rhWorkflowEditorState.previewStatus
        ? `<div class="rh-preview-status">${escapeHtml(rhWorkflowEditorState.previewStatus)}</div>`
        : '';
    const outputsHtml = (rhWorkflowEditorState.previewOutputs || []).length
        ? `<div class="rh-preview-output-list">${rhWorkflowEditorState.previewOutputs.map(url => renderRhPreviewOutput(url)).join('')}</div>`
        : '';
    const workflowOptionsHtml = rhEditorMode === 'workflow' ? `
        <div class="rh-workflow-run-mode">
            <label>
                <span>空可选图</span>
                <select onchange="setRhWorkflowOptionalImageMode(this.value)">
                    <option value="prune-workflow" ${String(config.optionalImageMode || 'prune-workflow') === 'prune-workflow' ? 'selected' : ''}>裁剪 workflow JSON</option>
                    <option value="skip" ${String(config.optionalImageMode || '') === 'skip' ? 'selected' : ''}>不提交字段</option>
                </select>
            </label>
            <small>仅工作流生效。可选图片为空时，裁剪模式会移除该图片输入及相关连接。</small>
        </div>
    ` : '';
    return `
        <div class="rh-mapped-card">
            <div class="rh-mapped-head">
                <div class="rh-mapped-icon"><i data-lucide="${rhEditorMode === 'app' ? 'sparkles' : 'workflow'}" class="w-4 h-4"></i></div>
                <div>
                    <div class="rh-mapped-title">${escapeHtml(title)}</div>
                </div>
            </div>
            <div class="rh-mapped-stats">
                <span>图片 ${mediaCounts.image}</span>
                <span>视频 ${mediaCounts.video}</span>
                <span>音频 ${mediaCounts.audio}</span>
                <span>参数 ${mediaCounts.setting}</span>
            </div>
            <div class="rh-preview-fields">${fieldsHtml}</div>
            ${workflowOptionsHtml}
            <button class="rh-preview-run ${rhWorkflowEditorState.previewRunning ? 'running' : ''}" type="button" onclick="testRhMappedPreview()" ${rhWorkflowEditorState.previewRunning ? 'disabled' : ''}><i data-lucide="${rhWorkflowEditorState.previewRunning ? 'loader-2' : 'play'}" class="w-3.5 h-3.5 ${rhWorkflowEditorState.previewRunning ? 'spin-icon' : ''}"></i><span>${rhWorkflowEditorState.previewRunning ? '测试中...' : '测试'}</span></button>
            ${statusHtml}
            ${outputsHtml}
        </div>
    `;
}
function renderRhPreviewOutput(url){
    const safe = escapeAttr(url || '');
    if(/\.(mp4|webm|mov|m4v)(\?|$)/i.test(safe)) return `<video src="${safe}" controls muted playsinline preload="metadata"></video>`;
    if(/\.(mp3|wav|ogg|m4a|flac|aac)(\?|$)/i.test(safe)) return `<audio src="${safe}" controls preload="metadata"></audio>`;
    return `<img src="${safe}" alt="">`;
}
function renderRhPreviewControl(field){
    const key = rhWorkflowFieldKey(field);
    const label = escapeHtml(field.label || field.fieldName);
    const kind = rhWorkflowFieldKind(field);
    const previewState = rhWorkflowEditorState.previewParams[key] || {};
    if(field.sourceFromUpstream === false && !['IMAGE','VIDEO','AUDIO'].includes(kind)){
        return `<div class="rh-preview-field keep-original"><div class="rh-preview-label">${label}</div><div class="rh-preview-keep"><i data-lucide="lock" class="w-3.5 h-3.5"></i><span>保留工作流原设置</span></div></div>`;
    }
    const randomActive = field.random_enabled === true && previewState.randomActive !== false;
    const value = previewState.value ?? field.fieldValue ?? '';
    const options = Array.isArray(field.options) ? field.options : [];
    if(['IMAGE','VIDEO','AUDIO'].includes(kind)){
        const slot = rhEditorMode === 'workflow' && kind === 'IMAGE'
            ? `<span class="rh-preview-slot">图 ${Number(field.imageOrder) || 1} · ${field.required === true ? '必选' : '可选'}</span>`
            : '';
        const icon = kind === 'VIDEO' ? 'file-video' : kind === 'AUDIO' ? 'file-audio' : 'image';
        const media = previewState.url
            ? renderRhPreviewMedia(previewState.url, kind, previewState.name || value)
            : `<i data-lucide="${icon}" class="w-5 h-5"></i><span>点击上传</span>`;
        return `<div class="rh-preview-field"><div class="rh-preview-label">${label}${slot}</div><button class="rh-preview-media ${previewState.url ? 'has-media' : ''}" type="button" onclick="pickRhPreviewMedia('${escapeAttr(key)}','${kind}')">${media}</button></div>`;
    }
    if(kind === 'BOOLEAN'){
        const on = String(value).toLowerCase() === 'true';
        return `<div class="rh-preview-field"><div class="rh-preview-label">${label}</div><div class="rh-preview-switch ${on ? 'on' : ''}"><span></span></div></div>`;
    }
    if(kind === 'SLIDER'){
        const min = Number.isFinite(Number(field.min)) ? Number(field.min) : 0;
        const max = Number.isFinite(Number(field.max)) && Number(field.max) > min ? Number(field.max) : 1;
        const step = Number.isFinite(Number(field.step)) && Number(field.step) > 0 ? Number(field.step) : 0.01;
        const numericValue = Number.isFinite(Number(value)) ? Number(value) : min;
        return `<div class="rh-preview-field"><div class="rh-preview-label"><span>${label}</span><span class="rh-preview-slider-val">${escapeHtml(numericValue)}</span></div><input class="rh-preview-slider" type="range" min="${escapeAttr(min)}" max="${escapeAttr(max)}" step="${escapeAttr(step)}" value="${escapeAttr(numericValue)}" oninput="updateRhPreviewValue('${escapeAttr(key)}', this.value); const val=this.closest('.rh-preview-field')?.querySelector('.rh-preview-slider-val'); if(val) val.textContent=this.value;"></div>`;
    }
    if(options.length || kind === 'SELECT'){
        return `<div class="rh-preview-field"><div class="rh-preview-label">${label}</div><select disabled>${(options.length ? options : [value || '选项']).map(option => `<option>${escapeHtml(option)}</option>`).join('')}</select></div>`;
    }
    const randomButton = kind === 'NUMBER' && field.random_enabled
        ? `<button class="random-btn rh-preview-random-btn ${randomActive ? 'active' : ''}" type="button" onclick="toggleRhPreviewRandom('${escapeAttr(key)}')" title="${randomActive ? '使用随机数' : '使用固定数'}"><i data-lucide="dice-5" class="w-4 h-4"></i></button>`
        : '';
    const readonly = randomActive ? 'disabled' : '';
    return `<div class="rh-preview-field"><div class="rh-preview-label">${label}</div><div class="rh-preview-random-row" style="${randomButton ? '' : 'grid-template-columns:1fr'}"><input ${readonly} type="${kind === 'NUMBER' ? 'number' : 'text'}" value="${escapeAttr(value)}" placeholder="${kind === 'NUMBER' && randomActive ? '随机数' : ''}" oninput="updateRhPreviewValue('${escapeAttr(key)}', this.value)">${randomButton}</div></div>`;
}
function renderRhPreviewMedia(url, kind, name=''){
    const safe = escapeAttr(url || '');
    if(kind === 'VIDEO') return `<video src="${safe}" muted preload="metadata" playsinline controls></video>`;
    if(kind === 'AUDIO') return `<span class="rh-preview-audio"><i data-lucide="file-audio" class="w-5 h-5"></i>${escapeHtml(name || '音频')}</span><audio src="${safe}" controls preload="metadata"></audio>`;
    return `<img src="${safe}" alt="">`;
}
function mediaAcceptForRhKind(kind){
    if(kind === 'VIDEO') return 'video/*';
    if(kind === 'AUDIO') return 'audio/*';
    return 'image/*';
}
async function pickRhPreviewMedia(key, kind){
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = mediaAcceptForRhKind(kind);
    input.onchange = async () => {
        const file = input.files?.[0];
        if(!file) return;
        const localUrl = URL.createObjectURL(file);
        rhWorkflowEditorState.previewParams[key] = {...(rhWorkflowEditorState.previewParams[key] || {}), url:localUrl, name:file.name, uploading:true};
        renderRhMappedPreview();
        const form = new FormData();
        form.append('files', file);
        try {
            const data = await fetch('/api/ai/upload', {method:'POST', body:form}).then(async r => {
                const json = await r.json();
                if(!r.ok) throw new Error(json.detail || '上传失败');
                return json;
            });
            const uploaded = data.files?.[0];
            rhWorkflowEditorState.previewParams[key] = {
                ...(rhWorkflowEditorState.previewParams[key] || {}),
                url:uploaded?.url || localUrl,
                name:uploaded?.name || file.name,
                kind:uploaded?.kind || kind.toLowerCase(),
                uploading:false
            };
            withRhEditorScrollPreserved(() => renderRhMappedPreview());
        } catch(err) {
            rhWorkflowEditorState.previewParams[key] = {...(rhWorkflowEditorState.previewParams[key] || {}), uploading:false};
            withRhEditorScrollPreserved(() => renderRhMappedPreview());
            await StudioDialog.alert(err.message || '上传失败', {type:'warning'});
        }
    };
    input.click();
}
function toggleRhPreviewRandom(key){
    const state = rhWorkflowEditorState.previewParams[key] || {};
    const field = (rhWorkflowEditorState.config?.fields || []).find(item => rhWorkflowFieldKey(item) === key);
    rhWorkflowEditorState.previewParams[key] = {
        ...state,
        value:state.value ?? field?.fieldValue ?? '',
        randomActive:state.randomActive === false
    };
    withRhEditorScrollPreserved(() => renderRhMappedPreview());
}
function updateRhPreviewValue(key, value){
    const state = rhWorkflowEditorState.previewParams[key] || {};
    rhWorkflowEditorState.previewParams[key] = {...state, value, randomActive:false};
}
function rhPreviewRandomValue(field){
    const isFloat = Number(field.step) > 0 && Number(field.step) < 1;
    let min = Number.isFinite(Number(field.min)) ? Number(field.min) : null;
    let max = Number.isFinite(Number(field.max)) ? Number(field.max) : null;
    const name = `${field.fieldName || ''} ${field.label || ''}`.toLowerCase();
    const looksSeed = name.includes('seed') || name.includes('noise') || name.includes('随机') || name.includes('种子');
    if(min === null) min = looksSeed ? 1 : 0;
    if(max === null || max <= min) max = looksSeed ? 4294967295 : 999999;
    if(looksSeed) max = Math.min(max, 4294967295);
    const value = min + Math.random() * (max - min);
    if(isFloat){
        const precision = Math.min(8, Math.max(1, String(field.step).split('.')[1]?.length || 2));
        return Number(value.toFixed(precision));
    }
    return Math.floor(value);
}
async function rhPreviewUploadValueIfNeeded(value){
    const text = String(value || '').trim();
    if(!text) return '';
    if(!/^https?:\/\//i.test(text) && !text.startsWith('/output/') && !text.startsWith('/assets/')) return text;
    const res = await fetch('/api/runninghub/upload-asset', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({url:text, region:currentRunningHubRegion(provider())})
    });
    const data = await res.json();
    if(!res.ok || data.success === false) throw new Error(data.detail || data.error || 'RunningHub 素材上传失败');
    return data.data?.fileName || text;
}
async function buildRhPreviewNodeInfoList(){
    const config = rhWorkflowEditorState.config;
    const fields = rhEditorSortedFields((config?.fields || []).filter(field => field.enabled === true));
    const imageFields = fields.filter(field => rhWorkflowFieldKind(field) === 'IMAGE');
    const imageSlotPreview = {};
    const imageIndexPreview = {};
    imageFields.forEach((field, index) => {
        const key = rhWorkflowFieldKey(field);
        const slot = Number(field.imageOrder) || 1;
        const preview = rhWorkflowEditorState.previewParams[key] || {};
        if((preview.url || preview.value) && !imageSlotPreview[slot]) imageSlotPreview[slot] = preview;
        if((preview.url || preview.value) && !imageIndexPreview[index]) imageIndexPreview[index] = preview;
    });
    const result = [];
    for(const field of fields){
        const key = rhWorkflowFieldKey(field);
        const kind = rhWorkflowFieldKind(field);
        if(field.sourceFromUpstream === false && !['IMAGE','VIDEO','AUDIO'].includes(kind)) continue;
        const ownPreview = rhWorkflowEditorState.previewParams[key] || {};
        const imageIndex = kind === 'IMAGE' ? imageFields.findIndex(item => rhWorkflowFieldKey(item) === key) : -1;
        const preview = kind === 'IMAGE'
            ? (ownPreview.url || ownPreview.value ? ownPreview : (imageSlotPreview[Number(field.imageOrder) || 1] || imageIndexPreview[imageIndex] || ownPreview))
            : ownPreview;
        let value = preview.value ?? field.fieldValue ?? '';
        if(['IMAGE','VIDEO','AUDIO'].includes(kind)){
            if(rhEditorMode === 'workflow' && kind === 'IMAGE' && field.required !== true && !preview.url) continue;
            if(rhEditorMode === 'workflow' && kind === 'IMAGE' && field.required === true && !preview.url && !value) throw new Error(`缺少必选图片：${field.label || field.fieldName}`);
            value = await rhPreviewUploadValueIfNeeded(preview.url || value);
        } else if(kind === 'NUMBER' && field.random_enabled === true && preview.randomActive !== false) {
            value = rhPreviewRandomValue(field);
        } else if(['NUMBER','SLIDER'].includes(kind) && String(value ?? '').trim() !== '' && !Number.isNaN(Number(value))) {
            value = Number(value);
        }
        // TEXT 自由文本要保留换行（多行提示词不能被截断成第一行）；其它单值字段才去换行。
        if(typeof value === 'string' && kind !== 'TEXT' && /[\r\n]/.test(value)) value = value.split(/\r?\n/).map(s => s.trim()).filter(Boolean)[0] || '';
        result.push({nodeId:field.nodeId, fieldName:field.fieldName, fieldValue:value});
    }
    return result;
}
function rhPreviewPruneWorkflow(nodeInfoList){
    const config = rhWorkflowEditorState.config;
    if(rhEditorMode !== 'workflow' || (config?.optionalImageMode || 'prune-workflow') !== 'prune-workflow') return null;
    const submitted = new Set((nodeInfoList || []).map(item => rhWorkflowFieldKey(item)));
    const missing = rhEditorSortedFields(config.fields || []).filter(field => field.enabled === true && rhWorkflowFieldKind(field) === 'IMAGE' && field.required !== true && !submitted.has(rhWorkflowFieldKey(field)));
    if(!missing.length || !config.workflowJson) return null;
    const workflow = JSON.parse(JSON.stringify(config.workflowJson));
    const removeIds = new Set();
    missing.forEach(field => {
        const node = workflow[String(field.nodeId)];
        if(node?.inputs && Object.prototype.hasOwnProperty.call(node.inputs, field.fieldName)) delete node.inputs[field.fieldName];
        if(node?.inputs && !Object.keys(node.inputs).length) removeIds.add(String(field.nodeId));
    });
    removeIds.forEach(id => delete workflow[id]);
    Object.values(workflow).forEach(node => {
        Object.entries(node?.inputs || {}).forEach(([name, value]) => {
            if(Array.isArray(value) && removeIds.has(String(value[0]))) delete node.inputs[name];
        });
    });
    return workflow;
}
async function testRhMappedPreview(){
    const config = rhWorkflowEditorState.config;
    if(!config || rhWorkflowEditorState.previewRunning) return;
    rhWorkflowEditorState.previewRunning = true;
    rhWorkflowEditorState.previewStatus = '正在提交 RunningHub 任务...';
    rhWorkflowEditorState.previewOutputs = [];
    renderRhMappedPreview();
    try {
        const nodeInfoList = await buildRhPreviewNodeInfoList();
        const endpoint = rhEditorMode === 'workflow' ? '/api/runninghub/workflow-submit' : '/api/runninghub/submit';
        const workflow = rhPreviewPruneWorkflow(nodeInfoList);
        const body = rhEditorMode === 'workflow'
            ? {workflowId:String(config.workflowId || '').trim(), nodeInfoList, ...(workflow ? {workflow} : {})}
            : {webappId:String(config.appId || '').trim(), nodeInfoList};
        body.region = currentRunningHubRegion(provider());
        if(rhEditorMode === 'workflow' && !body.workflowId) throw new Error('workflowId 为空');
        if(rhEditorMode === 'app' && !body.webappId) throw new Error('webappId 为空');
        const submit = await fetch(endpoint, {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify(body)
        }).then(async r => {
            const data = await r.json();
            if(!r.ok || data.success === false) throw new Error(data.detail || data.error || 'RunningHub 提交失败');
            return data.data || data;
        });
        const taskId = submit.taskId;
        if(!taskId) throw new Error('RunningHub 没有返回 taskId');
        rhWorkflowEditorState.previewStatus = `任务已提交：${taskId}`;
        renderRhMappedPreview();
        let result = null;
        for(let i = 0; i < 720; i++){
            await new Promise(resolve => setTimeout(resolve, 2500));
            const data = await fetch(`/api/runninghub/query?taskId=${encodeURIComponent(taskId)}&region=${encodeURIComponent(currentRunningHubRegion(provider()))}`).then(async r => {
                const json = await r.json();
                if(!r.ok || json.success === false) throw new Error(json.detail || json.error || 'RunningHub 查询失败');
                return json.data || json;
            });
            if(data.status === 'SUCCESS'){
                result = data;
                break;
            }
            if(data.status === 'FAILED') throw new Error(data.failReason || 'RunningHub 任务失败');
            rhWorkflowEditorState.previewStatus = data.status === 'QUEUED' ? '排队中...' : '运行中...';
            renderRhMappedPreview();
        }
        if(!result) throw new Error('RunningHub 任务超时');
        const outputs = result.urls || [];
        if(!outputs.length) throw new Error('RunningHub 没有返回产物');
        rhWorkflowEditorState.previewOutputs = outputs;
        rhWorkflowEditorState.previewStatus = '测试完成';
        setStatus('RunningHub 测试完成');
    } catch(err) {
        rhWorkflowEditorState.previewStatus = err.message || String(err);
        setStatus(rhWorkflowEditorState.previewStatus);
        await StudioDialog.alert(rhWorkflowEditorState.previewStatus, {type:'warning'});
    } finally {
        rhWorkflowEditorState.previewRunning = false;
        renderRhMappedPreview();
    }
}
function renderRhEditorSourcePane(){
    if(rhEditorMode === 'app') renderRhAppFieldCards();
    else renderRhWorkflowEditorGraph();
}
function renderRhWorkflowEditorSummary(){
    const config = rhWorkflowEditorState.config;
    if(!config || !rhWorkflowEditorSummary) return;
    const fields = config.fields || [];
    const enabled = fields.filter(field => field.enabled === true).length;
    const nodes = rhEditorMode === 'app' ? 1 : Object.keys(config.workflowJson || {}).length;
    const imageFields = fields.filter(field => field.enabled === true && rhWorkflowFieldKind(field) === 'IMAGE');
    const optionalImages = imageFields.filter(field => field.required !== true).length;
    rhWorkflowEditorSummary.innerHTML = `
        <div><span>${rhEditorMode === 'app' ? '应用' : '节点'}</span><strong>${nodes}</strong></div>
        <div><span>字段</span><strong>${enabled} / ${fields.length}</strong></div>
        ${rhEditorMode === 'workflow' ? `<div><span>可选图</span><strong>${optionalImages} / ${imageFields.length}</strong></div>` : ''}
    `;
}
function renderRhWorkflowEditorNodeList(){
    const config = rhWorkflowEditorState.config;
    if(!config || !rhWorkflowEditorNodeList) return;
    const groups = {};
    (config.fields || []).forEach(field => {
        const key = rhWorkflowGroupKey(field);
        (groups[key] = groups[key] || { field, items:[] }).items.push(field);
    });
    const values = Object.entries(groups);
    if(!values.length){
        rhWorkflowEditorNodeList.innerHTML = `<div class="rh-editor-empty">没有可配置字段</div>`;
        return;
    }
    rhWorkflowEditorNodeList.innerHTML = values.map(([groupKey, group]) => {
        const safeGroup = groupKey.replace(/[^a-zA-Z0-9_-]/g, '_');
        const expanded = rhWorkflowEditorState.expanded[safeGroup] !== false;
        const enabledCount = group.items.filter(field => field.enabled === true).length;
        return `
            <div class="rh-editor-node ${expanded ? 'expanded' : ''} ${String(group.field.nodeId) === rhWorkflowEditorState.activeNodeId ? 'is-focused' : ''}" data-node-id="${escapeAttr(group.field.nodeId)}">
                <button class="rh-editor-node-head" type="button" onclick="toggleRhWorkflowEditorGroup('${escapeAttr(safeGroup)}')">
                    <span>
                        <strong>${escapeHtml(group.field.group || `Node #${group.field.nodeId}`)}</strong>
                        <small>#${escapeHtml(group.field.nodeId)} · ${enabledCount}/${group.items.length}</small>
                    </span>
                    <i data-lucide="chevron-down" class="w-4 h-4"></i>
                </button>
                <div class="rh-editor-node-body">
                    ${group.items.map(field => renderRhWorkflowEditorField(field)).join('')}
                </div>
            </div>
        `;
    }).join('');
}
function renderRhWorkflowEditorField(field){
    const key = rhWorkflowFieldKey(field);
    const checked = field.enabled === true;
    const type = rhWorkflowFieldKind(field);
    const optionsText = Array.isArray(field.options) ? field.options.join('\n') : '';
    const randomOn = field.random_enabled === true;
    const keepOriginal = field.sourceFromUpstream === false;
    const imageSlotControls = rhEditorMode === 'workflow' && type === 'IMAGE' ? `
        <div class="rh-image-slot-row">
            <label><span>排序</span><input type="number" min="1" step="1" value="${escapeAttr(field.imageOrder || '')}" oninput="updateRhWorkflowEditorField('${escapeAttr(key)}','imageOrder',this.value)"></label>
            <button class="rh-editor-required ${field.required === true ? 'active' : ''}" type="button" onclick="updateRhWorkflowEditorField('${escapeAttr(key)}','required',${field.required === true ? 'false' : 'true'})">
                <span class="check-dot"></span>${field.required === true ? '必选' : '可选'}
            </button>
        </div>
    ` : '';
    return `
        <div class="rh-editor-field-row ${checked ? 'active' : ''}">
            <button class="rh-editor-check ${checked ? 'checked' : ''}" type="button" onclick="toggleRhWorkflowEditorField('${escapeAttr(key)}')">${checked ? '<i data-lucide="check" class="w-3 h-3"></i>' : ''}</button>
            <div class="rh-editor-field-main">
                <div class="rh-editor-field-name">${escapeHtml(field.label || field.fieldName)}</div>
                <div class="rh-editor-field-meta">${escapeHtml(field.fieldName)} · ${escapeHtml(type)}</div>
                <button class="rh-editor-keep ${keepOriginal ? 'active' : ''}" type="button" onclick="updateRhWorkflowEditorField('${escapeAttr(key)}','sourceFromUpstream',${keepOriginal ? 'true' : 'false'})">
                    <span class="check-dot"></span>${keepOriginal ? '保留工作流原设置' : '暴露并覆盖参数'}
                </button>
                <div class="rh-editor-field-controls">
                    <input type="text" value="${escapeAttr(field.label || '')}" placeholder="显示名称" oninput="updateRhWorkflowEditorField('${escapeAttr(key)}','label',this.value)">
                    <select onchange="updateRhWorkflowEditorField('${escapeAttr(key)}','fieldType',this.value)">
                        ${['TEXT','NUMBER','SLIDER','BOOLEAN','SELECT','IMAGE','VIDEO','AUDIO'].map(option => `<option value="${option}" ${String(field.fieldType || type).toUpperCase() === option ? 'selected' : ''}>${rhWorkflowFieldTypeLabel(option)}</option>`).join('')}
                    </select>
                </div>
                ${imageSlotControls}
                <div class="rh-editor-field-controls rh-editor-wide-controls">
                    <textarea placeholder="下拉选项：每行一个，例如 1024x1024" oninput="updateRhWorkflowEditorField('${escapeAttr(key)}','options',this.value)">${escapeHtml(optionsText)}</textarea>
                </div>
                <div class="rh-editor-random-row">
                    <button class="rh-editor-random ${randomOn ? 'active' : ''}" type="button" onclick="updateRhWorkflowEditorField('${escapeAttr(key)}','random_enabled',${randomOn ? 'false' : 'true'})"><i data-lucide="dice-5" class="w-3.5 h-3.5"></i><span>随机数</span></button>
                    <input type="number" value="${escapeAttr(field.min ?? '')}" placeholder="最小" oninput="updateRhWorkflowEditorField('${escapeAttr(key)}','min',this.value)">
                    <input type="number" value="${escapeAttr(field.max ?? '')}" placeholder="最大" oninput="updateRhWorkflowEditorField('${escapeAttr(key)}','max',this.value)">
                    <input type="number" value="${escapeAttr(field.step ?? '')}" placeholder="步长" oninput="updateRhWorkflowEditorField('${escapeAttr(key)}','step',this.value)">
                </div>
            </div>
        </div>
    `;
}
function renderRhAppFieldCards(){
    const config = rhWorkflowEditorState.config;
    if(!rhWorkflowEditorGraphWrap || !config) return;
    closeRhNodePopover();
    rhWorkflowEditorGraphWrap.classList.add('rh-app-field-wrap');
    rhWorkflowEditorGraphWrap.innerHTML = `
        <div class="rh-app-field-list">
            ${(config.fields || []).length
                ? (config.fields || []).map(field => renderRhAppFieldCard(field)).join('')
                : `<div class="rh-editor-empty">没有拉取到应用参数</div>`}
        </div>
    `;
    refreshIcons();
}
function restoreRhGraphWrap(){
    if(!rhWorkflowEditorGraphWrap || rhWorkflowEditorGraphSvg?.parentElement === rhWorkflowEditorGraphWrap) return;
    rhWorkflowEditorGraphWrap.classList.remove('rh-app-field-wrap');
    rhWorkflowEditorGraphWrap.innerHTML = `
        <svg id="rhWorkflowEditorGraphSvg" class="rh-editor-graph-svg"></svg>
        <div class="rh-editor-graph-controls">
            <button type="button" onclick="rhEditorGraphZoom(-1)" title="缩小"><i data-lucide="zoom-out" class="w-4 h-4"></i></button>
            <span id="rhWorkflowEditorZoom">100%</span>
            <button type="button" onclick="rhEditorGraphZoom(1)" title="放大"><i data-lucide="zoom-in" class="w-4 h-4"></i></button>
            <button type="button" onclick="rhEditorGraphFit()" title="适应窗口"><i data-lucide="maximize" class="w-4 h-4"></i></button>
        </div>
    `;
    rhWorkflowEditorGraphSvg = document.getElementById('rhWorkflowEditorGraphSvg');
    rhWorkflowEditorZoom = document.getElementById('rhWorkflowEditorZoom');
}
function renderRhAppFieldCard(field){
    const key = rhWorkflowFieldKey(field);
    const checked = field.enabled === true;
    return `
        <div class="rh-app-field-card ${checked ? 'active' : ''}" data-field-key="${escapeAttr(key)}" onclick="openRhAppFieldPopover('${escapeAttr(key)}', this)">
            <button class="rh-editor-check ${checked ? 'checked' : ''}" type="button" onclick="event.stopPropagation();toggleRhWorkflowEditorField('${escapeAttr(key)}')">${checked ? '<i data-lucide="check" class="w-3 h-3"></i>' : ''}</button>
            <div>
                <strong>${escapeHtml(field.label || field.fieldName)}</strong>
                <span>${escapeHtml(field.fieldName)} · ${escapeHtml(rhWorkflowFieldKind(field))}</span>
            </div>
            <i data-lucide="settings-2" class="w-4 h-4"></i>
        </div>
    `;
}
function openRhAppFieldPopover(key, anchorEl){
    const config = rhWorkflowEditorState.config;
    const field = (config?.fields || []).find(item => rhWorkflowFieldKey(item) === key);
    if(!field) return;
    closeRhNodePopover();
    const pop = document.createElement('div');
    pop.id = 'rhNodePopover';
    pop.className = 'rh-node-popover rh-app-popover';
    pop.dataset.fieldKey = String(key || '');
    pop.innerHTML = `
        <div class="rh-popover-head">
            <div>
                <strong>${escapeHtml(field.label || field.fieldName)}</strong>
                <span>${escapeHtml(field.fieldName)}</span>
            </div>
            <button type="button" onclick="closeRhNodePopover()"><i data-lucide="x" class="w-3.5 h-3.5"></i></button>
        </div>
        <div class="rh-popover-body">${renderRhWorkflowEditorField(field)}</div>
    `;
    document.body.appendChild(pop);
    const rect = anchorEl?.getBoundingClientRect?.();
    const modalRect = rhWorkflowEditorOverlay?.getBoundingClientRect?.() || {left:0, top:0, right:window.innerWidth, bottom:window.innerHeight};
    const width = 390;
    let left = rect ? rect.left : window.innerWidth / 2 - 190;
    let top = rect ? rect.bottom + 10 : window.innerHeight / 2 - 180;
    if(left + width > modalRect.right - 16) left = modalRect.right - width - 16;
    if(top + 420 > modalRect.bottom - 16) top = Math.max(modalRect.top + 74, (rect?.top || top) - 420);
    pop.style.left = `${Math.max(modalRect.left + 16, left)}px`;
    pop.style.top = `${top}px`;
    refreshIcons();
}
function computeRhWorkflowEditorLayers(workflow){
    const ids = Object.keys(workflow || {});
    const incoming = {}, outgoing = {};
    ids.forEach(id => { incoming[id] = new Set(); outgoing[id] = new Set(); });
    ids.forEach(id => {
        Object.values(workflow[id]?.inputs || {}).forEach(value => {
            if(Array.isArray(value) && value.length === 2 && typeof value[0] === 'string' && workflow[value[0]]){
                incoming[id].add(value[0]);
                outgoing[value[0]].add(id);
            }
        });
    });
    const layer = {};
    const visiting = new Set();
    function dfs(id, lv){
        if(visiting.has(id)) return;
        layer[id] = Math.max(layer[id] || 0, lv);
        visiting.add(id);
        outgoing[id].forEach(child => dfs(child, lv + 1));
        visiting.delete(id);
    }
    ids.forEach(id => { if(incoming[id].size === 0) dfs(id, 0); });
    ids.forEach(id => { if(!(id in layer)) layer[id] = 0; });
    const buckets = {};
    ids.forEach(id => { (buckets[layer[id]] = buckets[layer[id]] || []).push(id); });
    return { buckets };
}
function renderRhWorkflowEditorGraph(){
    const config = rhWorkflowEditorState.config;
    restoreRhGraphWrap();
    closeRhNodePopover();
    const workflow = config?.workflowJson || {};
    const svg = rhWorkflowEditorGraphSvg;
    const wrap = rhWorkflowEditorGraphWrap;
    if(!svg || !wrap) return;
    if(!workflow || !Object.keys(workflow).length){
        svg.innerHTML = `<text x="24" y="42" fill="currentColor">暂无工作流预览</text>`;
        return;
    }
    const { buckets } = computeRhWorkflowEditorLayers(workflow);
    const NODE_W = 136, NODE_H = 52, X_GAP = 42, Y_GAP = 16;
    const positions = {};
    const levels = Object.keys(buckets).map(Number).sort((a,b)=>a-b);
    let maxRows = 0;
    levels.forEach(lv => {
        const ids = buckets[lv].sort((a,b)=>parseInt(a,10)-parseInt(b,10));
        ids.forEach((id, idx) => positions[id] = { x:lv * (NODE_W + X_GAP) + 18, y:idx * (NODE_H + Y_GAP) + 18 });
        maxRows = Math.max(maxRows, ids.length);
    });
    const edges = [];
    Object.keys(workflow).forEach(toId => {
        const seen = new Set();
        Object.values(workflow[toId]?.inputs || {}).forEach(value => {
            if(Array.isArray(value) && value.length === 2 && typeof value[0] === 'string' && positions[value[0]] && positions[toId]){
                if(seen.has(value[0])) return;
                seen.add(value[0]);
                const from = positions[value[0]], to = positions[toId];
                const x1 = from.x + NODE_W, y1 = from.y + NODE_H / 2;
                const x2 = to.x, y2 = to.y + NODE_H / 2;
                const cx = (x1 + x2) / 2;
                edges.push(`<path class="rh-editor-edge" d="M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}"></path>`);
            }
        });
    });
    const activeNodes = new Set((config.fields || []).filter(field => field.enabled === true).map(field => String(field.nodeId)));
    const nodes = Object.entries(workflow).map(([id, node]) => {
        const pos = positions[id];
        const title = workflowNodeTitle(node);
        const klass = workflowNodeClass(node);
        const cat = workflowNodeCategory(node);
        const count = (config.fields || []).filter(field => field.enabled === true && String(field.nodeId) === String(id)).length;
        return `
            <g class="rh-editor-gnode cat-${cat} ${activeNodes.has(String(id)) ? 'has-exposed' : ''} ${String(id) === rhWorkflowEditorState.activeNodeId ? 'is-active' : ''}" data-node-id="${escapeAttr(id)}" transform="translate(${pos.x},${pos.y})" onclick="openRhWorkflowNodePopover('${escapeAttr(id)}', this)">
                <rect width="${NODE_W}" height="${NODE_H}" rx="8"></rect>
                <text class="rh-editor-gtitle" x="10" y="20">${escapeHtml(title.length > 15 ? title.slice(0, 15) + '...' : title)}</text>
                <text class="rh-editor-gsub" x="10" y="36">${escapeHtml(klass.length > 18 ? klass.slice(0, 18) + '...' : klass)}</text>
                <text class="rh-editor-gsub" x="${NODE_W - 8}" y="20" text-anchor="end">#${escapeHtml(id)}</text>
                ${count ? `<text class="rh-editor-gbadge" x="${NODE_W - 8}" y="43" text-anchor="end">${count}</text>` : ''}
            </g>
        `;
    }).join('');
    rhWorkflowEditorState.graph.w = levels.length * (NODE_W + X_GAP) + 18;
    rhWorkflowEditorState.graph.h = maxRows * (NODE_H + Y_GAP) + 18;
    svg.setAttribute('viewBox', `0 0 ${wrap.clientWidth || 800} ${wrap.clientHeight || 520}`);
    svg.innerHTML = `<g id="rhWorkflowEditorViewport" transform="translate(${rhWorkflowEditorState.graph.x},${rhWorkflowEditorState.graph.y}) scale(${rhWorkflowEditorState.graph.k})">${edges.join('')}${nodes}</g>`;
    bindRhWorkflowEditorPanZoom();
    updateRhEditorZoom();
}
function updateRhEditorZoom(){
    if(rhWorkflowEditorZoom) rhWorkflowEditorZoom.textContent = Math.round((rhWorkflowEditorState.graph.k || 1) * 100) + '%';
}
function applyRhEditorGraphTransform(){
    const vp = document.getElementById('rhWorkflowEditorViewport');
    const g = rhWorkflowEditorState.graph;
    if(vp) vp.setAttribute('transform', `translate(${g.x},${g.y}) scale(${g.k})`);
    updateRhEditorZoom();
}
function rhEditorGraphZoom(dir){
    const wrap = rhWorkflowEditorGraphWrap;
    if(!wrap) return;
    const g = rhWorkflowEditorState.graph;
    const factor = dir > 0 ? 1.2 : 1 / 1.2;
    const newK = Math.max(0.2, Math.min(3, g.k * factor));
    const cx = wrap.clientWidth / 2;
    const cy = wrap.clientHeight / 2;
    g.x = cx - (cx - g.x) * (newK / g.k);
    g.y = cy - (cy - g.y) * (newK / g.k);
    g.k = newK;
    applyRhEditorGraphTransform();
}
function rhEditorGraphFit(){
    const wrap = rhWorkflowEditorGraphWrap;
    const g = rhWorkflowEditorState.graph;
    if(!wrap || !g.w || !g.h) return;
    const pad = 24;
    const k = Math.max(0.2, Math.min(2, Math.min((wrap.clientWidth - pad * 2) / g.w, (wrap.clientHeight - pad * 2) / g.h)));
    g.k = k;
    g.x = (wrap.clientWidth - g.w * k) / 2;
    g.y = (wrap.clientHeight - g.h * k) / 2;
    applyRhEditorGraphTransform();
}
function bindRhWorkflowEditorPanZoom(){
    const svg = rhWorkflowEditorGraphSvg;
    const wrap = rhWorkflowEditorGraphWrap;
    if(!svg || !wrap || svg.dataset.editorPanZoomBound) return;
    svg.dataset.editorPanZoomBound = '1';
    rhWorkflowEditorState.bound = true;
    wrap.addEventListener('wheel', event => {
        if(!rhWorkflowEditorState.open) return;
        event.preventDefault();
        const g = rhWorkflowEditorState.graph;
        const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
        const newK = Math.max(0.2, Math.min(3, g.k * factor));
        const rect = wrap.getBoundingClientRect();
        const mx = event.clientX - rect.left;
        const my = event.clientY - rect.top;
        g.x = mx - (mx - g.x) * (newK / g.k);
        g.y = my - (my - g.y) * (newK / g.k);
        g.k = newK;
        applyRhEditorGraphTransform();
    }, { passive:false });
    svg.addEventListener('mousedown', event => {
        if(!rhWorkflowEditorState.open) return;
        event.preventDefault();
        rhWorkflowEditorState.pan = { sx:event.clientX, sy:event.clientY, ox:rhWorkflowEditorState.graph.x, oy:rhWorkflowEditorState.graph.y };
        wrap.classList.add('is-panning');
    });
    window.addEventListener('mousemove', event => {
        const pan = rhWorkflowEditorState.pan;
        if(!pan) return;
        rhWorkflowEditorState.graph.x = pan.ox + event.clientX - pan.sx;
        rhWorkflowEditorState.graph.y = pan.oy + event.clientY - pan.sy;
        applyRhEditorGraphTransform();
    });
    window.addEventListener('mouseup', () => {
        if(rhWorkflowEditorState.pan){
            rhWorkflowEditorState.pan = null;
            wrap.classList.remove('is-panning');
        }
    });
}
function renderRunningHubCards(){
    const item = provider();
    if(!item || item.id !== 'runninghub'){
        if(rhGlobalAppsList) rhGlobalAppsList.innerHTML = '';
        if(rhCnAppsList) rhCnAppsList.innerHTML = '';
        if(rhWorkflowsList) rhWorkflowsList.innerHTML = '';
        return;
    }
    ensureRunningHubRegions(item);
    Object.keys(RUNNINGHUB_REGIONS).forEach(region => {
        const state = runningHubRegionState(item, region);
        const enabled = state?.enabled === true;
        const apps = runningHubRegionEntries(item, region, 'app')
            .map((entry, index) => ({...entry, _rhIndex:index}))
            .filter(entry => entry?.hidden !== true)
            .filter(entry => !(rhAppSyncState?.region === region && String(entry?.id || entry?.appId || '') === rhAppSyncState.id));
        const target = runningHubRegionUi(region, 'apps');
        const count = runningHubRegionUi(region, 'count');
        const card = document.querySelector(`[data-rh-app-region="${region}"]`);
        const status = card?.querySelector?.(`[data-rh-app-status="${region}"]`);
        const input = runningHubRegionAppInput(region);
        const addButton = card?.querySelector?.(`[data-rh-app-add="${region}"]`);
        const busy = rhAppSyncState?.region === region && Boolean(rhAppSyncState);
        card?.classList?.toggle('is-disabled', !enabled);
        if(status) status.textContent = enabled ? '' : tr('api.rhSiteDisabled');
        if(input) input.disabled = !enabled || busy;
        if(addButton) addButton.disabled = !enabled || busy;
        if(count) count.textContent = apps.length;
        renderRhEntryList(target, apps, 'app', busy ? rhAppSyncState : null, region, enabled);
    });
    refreshIcons();
}
function rhEntryThumbnailCandidates(kind, entry){
    const id = String((kind === 'workflow' ? (entry?.workflowId || entry?.id) : (entry?.appId || entry?.id)) || '').trim().replace(/[^0-9A-Za-z_-]/g, '');
    if(!id) return [];
    const prefix = kind === 'workflow' ? 'workflow' : 'app';
    const exts = ['jpg'];
    const names = [`${prefix}-${id}`, id];
    const roots = ['/static/runninghub/thumbnails', '/static/runninghub'];
    const urls = [];
    names.forEach(name => {
        exts.forEach(ext => {
            roots.forEach(root => urls.push(`${root}/${name}.${ext}`));
        });
    });
    return urls;
}
function renderRhEntryThumbnail(kind, entry){
    const icon = kind === 'app' ? 'sparkles' : 'workflow';
    const candidates = rhEntryThumbnailCandidates(kind, entry);
    const thumbnail = String(entry?.thumbnail || '').trim();
    const src = thumbnail || candidates[0] || '';
    if(!src) return `<i data-lucide="${icon}" class="w-5 h-5"></i>`;
    const fallbacks = thumbnail ? candidates : candidates.slice(1);
    return `<img src="${escapeAttr(src)}" alt="" data-rh-thumb-fallbacks="${escapeAttr(fallbacks.join('|'))}" onerror="fallbackRhEntryThumbnail(this,'${icon}')">`;
}
function fallbackRhEntryThumbnail(img, icon){
    const fallbacks = String(img?.dataset?.rhThumbFallbacks || '').split('|').filter(Boolean);
    const next = fallbacks.shift();
    if(next){
        img.dataset.rhThumbFallbacks = fallbacks.join('|');
        img.src = next;
        return;
    }
    const parent = img?.parentElement;
    if(parent){
        parent.innerHTML = `<i data-lucide="${icon === 'sparkles' ? 'sparkles' : 'workflow'}" class="w-5 h-5"></i>`;
        refreshIcons();
    }
}
function renderRhSyncCard(state){
    if(!state?.id) return '';
    const siteName = tr(state.region === 'cn' ? 'api.rhRegionCn' : 'api.rhRegionGlobal');
    return [
        '<div class="rh-config-card rh-sync-card" data-rh-sync-card aria-live="polite" aria-busy="true">',
        '<div class="rh-thumb rh-sync-thumb"><i data-lucide="loader-circle" class="rh-sync-spinner w-5 h-5"></i></div>',
        '<div class="rh-card-main">',
        '<div class="rh-card-title-field"><span>' + escapeHtml(tr('api.rhAppSyncTitle')) + '</span><strong>' + escapeHtml(state.phase || tr('api.rhAppSyncing')) + '</strong></div>',
        '<div class="rh-id-line"><i data-lucide="hash" class="w-3 h-3"></i><span>' + escapeHtml(state.id) + '</span></div>',
        '<div class="rh-card-note">' + escapeHtml(trf('api.rhAppSyncDescription', {region:siteName})) + '</div>',
        '</div>',
        '<div class="rh-sync-status" title="' + escapeAttr(tr('api.rhAppSyncStatus')) + '"><span></span></div>',
        '</div>'
    ].join('');
}
function renderRhEntryList(target, list, kind, syncState=null, region='', enabled=true){
    if(!target) return;
    if(!enabled && !list.length && !syncState){
        target.innerHTML = '';
        return;
    }
    if(!list.length && !(kind === 'app' && syncState)){
        target.innerHTML = `<div class="rh-empty">${kind === 'app' ? '输入 AI 应用 ID 后点击添加并同步' : '粘贴 /run/workflow/... 后点击创建工作流卡片'}</div>`;
        return;
    }
    const pendingCard = kind === 'app' ? renderRhSyncCard(syncState) : '';
    const regionBadge = kind === 'app' ? runningHubRegionBadge(region || currentRunningHubRegion(provider())) : '';
    const regionArg = region ? `, '${escapeAttr(region)}'` : '';
    const disabledAttr = enabled ? '' : ' disabled';
    target.innerHTML = pendingCard + list.map((entry, index) => `
        <div class="rh-config-card">
            ${kind === 'app'
                ? `<div class="rh-thumb" title="RunningHub 官方封面">${renderRhEntryThumbnail(kind, entry)}</div>`
                : `<button class="rh-thumb" type="button" onclick="pickRhThumbnail('${kind}', ${entry._rhIndex ?? index})" title="上传缩略图">${renderRhEntryThumbnail(kind, entry)}</button>`}
            <div class="rh-card-main">
                ${kind === 'app'
                    ? `<div class="rh-card-title-field"><span>RunningHub 官方应用 <em class="rh-region-badge">${escapeHtml(regionBadge)}</em></span><strong>${escapeHtml(runningHubLocalizedTitle(entry, region) || `AI 应用 ${entry.id || ''}`)}</strong></div>`
                    : `<label class="rh-card-title-field"><span>名称</span><input type="text" value="${escapeAttr(entry.title || '')}" oninput="updateRhEntry('${kind}', ${entry._rhIndex ?? index}, 'title', this.value${regionArg})" placeholder="工作流名称"${disabledAttr}></label>`}
                <div class="rh-id-line"><i data-lucide="hash" class="w-3 h-3"></i><span>${escapeHtml(entry.id)}</span></div>
                ${kind === 'app'
                    ? `<div class="rh-card-note">${escapeHtml(String(entry.note || '').replace(/<[^>]*>/g, ' ') || '官方参数将在画布中自动生成')}</div>`
                    : `<textarea oninput="updateRhEntry('${kind}', ${entry._rhIndex ?? index}, 'note', this.value${regionArg})" placeholder="备注、用途、参数说明"${disabledAttr}>${escapeHtml(entry.note || '')}</textarea>`}
            </div>
            <div class="rh-card-actions">
                ${kind === 'workflow'
                    ? `<button class="rh-card-action" type="button" onclick="openRhWorkflowEditor(${entry._rhIndex ?? index})" title="编辑工作流"${disabledAttr}><i data-lucide="settings-2" class="w-3.5 h-3.5"></i></button>`
                    : `<button class="rh-card-action" type="button" onclick="syncRhAppFromOfficial(${entry._rhIndex ?? index}, '${escapeAttr(region)}').catch(error => StudioDialog.alert(error.message || '同步失败', {type:'warning'}))" title="重新同步官方应用信息"${disabledAttr}><i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i></button>`}
                <button class="rh-card-action danger" type="button" onclick="removeRhEntry('${kind}', ${entry._rhIndex ?? index}${regionArg})" title="删除"${disabledAttr}><i data-lucide="trash-2" class="w-3.5 h-3.5"></i></button>
            </div>
        </div>
    `).join('');
}
function openRecommendApi(){
    recommendInlineOpen = true;
    syncRecommendView();
    renderRecommendApi();
    renderProviderOnboarding(provider());
}
function closeRecommendApi(){
    if(recommendApiOverlay) recommendApiOverlay.style.display = 'none';
    recommendInlineOpen = false;
    syncRecommendView();
    renderRecommendApi();
    renderEditor();
}
function syncRecommendView(){
    if(settingsContent) settingsContent.hidden = recommendInlineOpen;
    if(recommendContent) recommendContent.hidden = !recommendInlineOpen;
    const recommendTitle = recommendContent?.querySelector('.editor-title');
    const recommendSub = recommendContent?.querySelector('.editor-sub');
    if(recommendTitle) recommendTitle.textContent = tr('api.recommendPanelTitle');
    if(recommendSub) recommendSub.textContent = tr('api.recommendPanelSub');
    document.body.classList.toggle('show-recommend-mode', recommendInlineOpen);
}
function focusRecommendKey(event, index){
    if(event?.target?.closest?.('a,button,input,textarea,select,label')) return;
    const input = recommendPanel?.querySelector(`[data-recommend-key="${index}"]`);
    if(input){
        input.focus();
        input.scrollIntoView({block:'nearest', inline:'nearest'});
    }
}
function renderRecommendApi(){
    if(!recommendPanel) return;
    if(!recommendInlineOpen){
        recommendPanel.innerHTML = '';
        return;
    }
    const recommendProtocolBadge = api => api.id === 'runninghub' || api.protocol === 'runninghub'
        ? 'RH'
        : api.id === 'modelscope'
        ? 'ModelScope'
        : api.protocol === 'apimart'
        ? 'APIMart'
        : 'OpenAI';
    const legacyRecommendCard = (api, index) => `
        <section class="recommend-card recommend-platform-card" style="--recommend-index:${index}" onclick="focusRecommendKey(event, ${index})">
            <div class="recommend-platform-info">
                <div class="recommend-platform-head">
                    <div>
                        <div class="recommend-name"><span>${escapeHtml(api.name)}</span></div>
                    </div>
                    <span class="recommend-badge">${escapeHtml(recommendProtocolBadge(api))}</span>
                </div>
                <p class="recommend-platform-summary">${escapeHtml(tr(api.summaryKey))}</p>
                <div class="recommend-tags">
                    ${(api.perks || (api.perkKey ? [{key:api.perkKey, className:api.perkClass || ''}] : [])).map(perk => `<span class="recommend-tag recommend-perk-tag ${escapeAttr(perk.className || '')}"><i data-lucide="gift" class="w-3 h-3"></i><span>${escapeHtml(tr(perk.key))}</span></span>`).join('')}
                    ${(api.tagKeys || []).map(tag => tag === 'api.tagSeedance'
                        ? `<span class="recommend-tag recommend-seedance-tag"><i data-lucide="video" class="w-3 h-3"></i><span>${escapeHtml(tr(tag))}</span></span>`
                        : `<span class="recommend-tag">${escapeHtml(tag.startsWith('api.') ? tr(tag) : tag)}</span>`
                    ).join('')}
                </div>
            </div>
            ${api.add_without_key ? `
            <div class="recommend-platform-setup recommend-platform-add">
                <div>
                    <div class="recommend-setup-title">${escapeHtml(tr('api.recommendAddTitle'))}</div>
                    <p class="recommend-platform-summary">${escapeHtml(tr('api.recommendAddDesc'))}</p>
                </div>
                <button class="action-btn recommend-add-platform-btn" type="button" onclick="addRecommendedApi(${index})">
                    <i data-lucide="plus" class="w-3.5 h-3.5"></i>
                    <span>${escapeHtml(tr(providers.some(provider => provider.id === api.id) ? 'api.openPlatformConfig' : 'api.addPlatform'))}</span>
                </button>
            </div>
            ` : `<div class="recommend-platform-setup">
                <div class="recommend-setup-title">${escapeHtml(tr('api.recommendQuickSetup'))}</div>
                <div class="recommend-quick-stack recommend-setup-flow">
                    <div class="recommend-guide-source onboarding-rh-source-group">
                        <div class="onboarding-rh-source-label">${escapeHtml(tr('api.getKey'))}</div>
                        <div class="onboarding-key-actions onboarding-rh-key-actions ${api.register_url_cn ? 'recommend-guide-key-stack' : 'recommend-single-action'}">
                            ${api.register_url_cn ? `
                            <a class="onboarding-key-btn recommend-guide-key-btn" href="${escapeAttr(api.register_url)}" target="_blank" rel="noopener noreferrer"><i data-lucide="key-round" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr('api.getKeyGlobal'))}</span></a>
                            <a class="onboarding-key-btn recommend-guide-key-btn" href="${escapeAttr(api.register_url_cn)}" target="_blank" rel="noopener noreferrer"><i data-lucide="key-round" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr('api.getKeyCn'))}</span></a>
                            ` : `
                            <a class="onboarding-key-btn recommend-guide-key-btn" href="${escapeAttr(api.register_url)}" target="_blank" rel="noopener noreferrer"><i data-lucide="key-round" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr('api.getKey'))}</span></a>
                            `}
                        </div>
                    </div>
                    <div class="recommend-flow-arrow onboarding-flow-arrow recommend-guide-arrow" aria-hidden="true"><span></span><b></b></div>
                    <div class="recommend-guide-save">
                        <label class="onboarding-key-field onboarding-rh-row-field">
                            <span class="recommend-api-key-label">API Key${api.keyHint ? `<em class="recommend-key-inline-hint">${escapeHtml(api.keyHint)}</em>` : ''}</span>
                            <input type="password" data-recommend-key="${index}" placeholder="${escapeAttr(trf('api.recommendKeyPlaceholder', {name:api.name}))}" oninput="queueRecommendedApiKey(${index}, this.value)">
                        </label>
                        <span class="onboarding-autosave-note"><i data-lucide="cloud-check" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr('api.autosaveHint'))}</span></span>
                    </div>
                </div>
            </div>`}
        </section>
    `;
    // 按分组分节渲染（稳定 / 便宜）；index 始终取原数组下标，保证 saveRecommendedApi(index) 正确
    const html = RECOMMEND_GROUPS.map(group => {
        const items = RECOMMENDED_APIS
            .map((api, index) => ({api, index}))
            .filter(item => !HIDDEN_RECOMMENDED_API_IDS.has(String(item.api.id || '').toLowerCase()))
            .filter(item => (item.api.category || 'cheap') === group.key);
        if(!items.length) return '';
        return `
        <div class="recommend-group">
            <div class="recommend-group-head recommend-group-${escapeAttr(group.key)}">
                <i data-lucide="${escapeAttr(group.icon)}" class="w-3.5 h-3.5"></i>
                <span>${escapeHtml(tr(group.titleKey))}</span>
            </div>
            ${items.map(item => legacyRecommendCard(item.api, item.index)).join('')}
        </div>`;
    }).join('');
    recommendPanel.innerHTML = `
        <div class="onboarding-head">
            <div>
                <div class="onboarding-title">${escapeHtml(tr('api.recommendPanelHintTitle'))}</div>
                <div class="onboarding-desc">${escapeHtml(tr('api.recommendPanelHintDesc'))}</div>
            </div>
        </div>
        <div class="recommend-api-body recommend-inline-body">${html}</div>
    `;
    refreshIcons();
}
function recommendedProviderForApi(api){
    if(!api || HIDDEN_RECOMMENDED_API_IDS.has(String(api.id || '').toLowerCase())) return null;
    let item = providers.find(provider =>
        (api.id && String(provider.id || '').toLowerCase() === String(api.id).toLowerCase())
        || String(provider.name || '').toLowerCase() === api.name.toLowerCase()
    );
    if(item){
        item.enabled = api.add_without_key ? Boolean(item.has_key) : true;
        item.base_url = api.base_url || item.base_url || '';
        item.protocol = api.protocol || item.protocol || 'openai';
        item.image_request_mode = normalizeImageRequestMode(api.image_request_mode || item.image_request_mode);
        item.image_edit_route = normalizeImageEditRoute(api.image_edit_route || item.image_edit_route);
        if(Array.isArray(api.image_models)) item.image_models = [...api.image_models];
        if(Array.isArray(api.chat_models)) item.chat_models = [...api.chat_models];
        if(Array.isArray(api.video_models)) item.video_models = [...api.video_models];
        if(Array.isArray(api.audio_models)) item.audio_models = [...api.audio_models];
        if(api.empty_models_on_save){
            item.image_models = [];
            item.chat_models = [];
            item.video_models = [];
            item.audio_models = [];
            item.model_protocols = {};
        }
        return item;
    }
    const baseId = normalizeId(api.id || api.name) || 'custom-api';
    let id = baseId;
    let suffix = 2;
    while(providers.some(provider => provider.id === id)) id = `${baseId}-${suffix++}`;
    item = {
        id,
        name:api.name,
        base_url:api.base_url,
        protocol:api.protocol,
        image_request_mode:normalizeImageRequestMode(api.image_request_mode),
        image_edit_route:normalizeImageEditRoute(api.image_edit_route),
        image_generation_endpoint:'',
        image_edit_endpoint:'',
        enabled:api.add_without_key ? false : true,
        primary:false,
        image_models:api.empty_models_on_save ? [] : (Array.isArray(api.image_models) ? [...api.image_models] : []),
        chat_models:api.empty_models_on_save ? [] : (Array.isArray(api.chat_models) ? [...api.chat_models] : []),
        video_models:api.empty_models_on_save ? [] : (Array.isArray(api.video_models) ? [...api.video_models] : []),
        audio_models:api.empty_models_on_save ? [] : (Array.isArray(api.audio_models) ? [...api.audio_models] : []),
        model_protocols:api.empty_models_on_save ? {} : ((api.model_protocols && typeof api.model_protocols === 'object') ? {...api.model_protocols} : {}),
        has_key:false,
        key_preview:''
    };
    providers.push(item);
    return item;
}
async function addRecommendedApi(index){
    const api = RECOMMENDED_APIS[index];
    if(!api || HIDDEN_RECOMMENDED_API_IDS.has(String(api.id || '').toLowerCase())) return;
    syncEditor();
    const previousProviders = JSON.parse(JSON.stringify(providers));
    const previousSelectedId = selectedId;
    const item = recommendedProviderForApi(api);
    if(!item) return;
    clearFetchedModelState();
    selectedId = item.id;
    recommendInlineOpen = false;
    syncRecommendView();
    renderProviderList();
    renderEditor();
    const ok = await saveProviders();
    if(ok){
        selectedId = item.id;
        renderEditor();
        setStatus(trf('api.recommendAdded', {name:api.name}));
    } else {
        providers = previousProviders;
        selectedId = previousSelectedId;
        renderProviderList();
        renderEditor();
    }
}
function queueRecommendedApiKey(index, value){
    const previous = recommendedKeySaveTimers.get(index);
    if(previous) clearTimeout(previous);
    const timer = setTimeout(() => {
        recommendedKeySaveTimers.delete(index);
        void saveRecommendedApi(index, value);
    }, API_AUTOSAVE_DELAY);
    recommendedKeySaveTimers.set(index, timer);
}
async function saveRecommendedApi(index, suppliedKey=''){
    const api = RECOMMENDED_APIS[index];
    if(!api || HIDDEN_RECOMMENDED_API_IDS.has(String(api.id || '').toLowerCase())) return;
    const input = recommendPanel?.querySelector(`[data-recommend-key="${index}"]`);
    const key = String(suppliedKey || input?.value || '').trim();
    if(!key){ await StudioDialog.alert(tr('api.enterApiKey'), {type:'warning'}); return; }
    syncEditor();
    const previousProviders = JSON.parse(JSON.stringify(providers));
    const previousSelectedId = selectedId;
    const item = recommendedProviderForApi(api);
    if(!item) return;
    clearFetchedModelState();
    selectedId = item.id;
    recommendInlineOpen = false;
    syncRecommendView();
    renderProviderList();
    renderEditor();
    keyInput.value = key;
    if(protocolInput){
        protocolInput.value = api.protocol;
        protocolInput.dispatchEvent(new Event('change'));
    }
    if(imageRequestModeInput){
        imageRequestModeInput.value = normalizeImageRequestMode(api.image_request_mode);
        imageRequestModeInput.dispatchEvent(new Event('change'));
    }
    syncEditor();
    const ok = await saveProviders();
    if(ok) setStatus(trf('api.recommendSaved', {name:api.name}));
    else {
        providers = previousProviders;
        selectedId = previousSelectedId;
        renderProviderList();
        renderEditor();
    }
}
function sortedProviders(){
    const order = ['modelscope', 'runninghub', 'volcengine', 'ai-money', 'agnes'];
    return visibleProviders().filter(item => !isCliProvider(item)).sort((a, b) => {
        const ai = order.indexOf(a.id);
        const bi = order.indexOf(b.id);
        if(ai === -1 && bi === -1) return 0;
        if(ai === -1) return 1;
        if(bi === -1) return -1;
        return ai - bi;
    });
}
function sortedCliProviders(){
    return visibleProviders().filter(item => isCliProvider(item));
}
function providerDragAttrs(item){
    if(isFixedProvider(item)) return '';
    const id = escapeAttr(item.id);
    return ` draggable="true" data-provider-id="${id}" ondragstart="handleProviderDragStart(event,'${id}')" ondragover="handleProviderDragOver(event,'${id}')" ondrop="handleProviderDrop(event,'${id}')" ondragend="handleProviderDragEnd()"`;
}
function renderProviderList(){
    if(!providerList) return;
    providerList.innerHTML = sortedProviders().map(item => {
        const active = item.id === selectedId ? 'active' : '';
        const itemProtocol = String(item.protocol || 'openai').toLowerCase();
        const stateClass = item.id === 'runninghub'
            ? (runningHubHasEnabledRegion(item) ? '' : 'is-disabled')
            : item.enabled === false ? 'is-disabled' : (item.has_key || item.has_wallet_key || CLI_PROTOCOLS.has(itemProtocol) ? 'has-key' : 'missing-key');
        const protocolLabel = item.id === 'runninghub' ? 'RH' : String(item.protocol || 'openai').toUpperCase();
        if(item.id === 'modelscope'){
            return `
                <button class="provider-card provider-card-banner ${active} ${stateClass}" type="button" onclick="selectProvider('${escapeHtml(item.id)}')">
                    <span class="provider-banner-inner">
                        <span class="provider-logo-wrap">
                            <img src="/static/images/modelscope.gif" alt="ModelScope" class="ms-icon-light">
                            <img src="/static/images/modelscope-1.gif" alt="ModelScope" class="ms-icon-dark">
                            <span class="provider-logo-fallback">ModelScope</span>
                        </span>
                        <span class="provider-protocol-pill">OpenAI</span>
                    </span>
                </button>
            `;
        }
        if(item.id === 'runninghub'){
            return `
                <div class="provider-card provider-card-banner runninghub-provider-card ${active} ${stateClass}">
                    <button class="provider-card-main" type="button" onclick="selectProvider('${escapeHtml(item.id)}')">
                        <span class="provider-banner-inner">
                            <span class="provider-logo-wrap">
                                <img src="/static/images/RunningHub-B.png" alt="RunningHub" class="runninghub-icon ms-icon-light">
                                <img src="/static/images/RunningHub-W.png" alt="RunningHub" class="runninghub-icon ms-icon-dark">
                                <span class="provider-logo-fallback">RunningHub</span>
                            </span>
                            <span class="provider-protocol-pill">RH</span>
                        </span>
                    </button>
                </div>
            `;
        }
        if(item.id === 'volcengine'){
            return `
                <button class="provider-card provider-card-banner ${active} ${stateClass}" type="button" onclick="selectProvider('${escapeHtml(item.id)}')">
                    <span class="provider-banner-inner">
                        <span class="provider-logo-wrap">
                            <img src="/static/images/volcengine-theme-light.svg" alt="火山引擎" class="volcengine-icon ms-icon-light">
                            <img src="/static/images/volcengine-theme-dark.svg" alt="火山引擎" class="volcengine-icon ms-icon-dark">
                            <span class="provider-logo-fallback">火山引擎</span>
                        </span>
                        <span class="provider-protocol-pill">Ark</span>
                    </span>
                </button>
            `;
        }
        if(item.id === 'ai-money'){
            return `
                <button class="provider-card provider-card-banner provider-card-ai-money ${active} ${stateClass}" type="button" onclick="selectProvider('${escapeHtml(item.id)}')">
                    <span class="provider-banner-inner">
                        <span class="provider-logo-wrap provider-logo-ai-money">
                            <img src="/static/images/ai-money.png" alt="" aria-hidden="true" class="ai-money-icon">
                            <img src="/static/images/laohu-wordmark.png" alt="laohu" class="laohu-wordmark">
                        </span>
                        <span class="provider-protocol-pill">API</span>
                    </span>
                </button>
            `;
        }
        return `
            <button class="provider-card provider-card-sortable ${active} ${stateClass}" type="button" onclick="selectProvider('${escapeHtml(item.id)}')"${providerDragAttrs(item)}>
                <span class="provider-drag-handle" aria-hidden="true"><i data-lucide="grip-vertical" class="w-3.5 h-3.5"></i></span>
                <span class="provider-mark"><i data-lucide="${CLI_PROTOCOLS.has(itemProtocol) ? 'terminal' : item.has_key ? 'key-round' : 'key'}" class="w-4 h-4"></i></span>
                <span class="provider-info">
                    <div class="provider-name">${escapeHtml(item.name || item.id)}</div>
                    <div class="provider-meta">${escapeHtml(CLI_PROTOCOLS.has(itemProtocol) ? '本机 CLI · 无需 API Key' : (item.base_url || '未配置地址'))}</div>
                </span>
                <span class="provider-side-meta">
                    <span class="provider-status-dot"></span>
                    <span class="provider-protocol-pill">${escapeHtml(protocolLabel)}</span>
                </span>
            </button>
        `;
    }).join('');
    refreshIcons();
    renderCliProviderList();
}
function cliCapabilityLabel(item){
    const protocol = String(item?.protocol || item?.id || '').toLowerCase();
    if(protocol === 'jimeng') return tr('api.cliJimengCapabilities');
    if(protocol === 'codex') return tr('api.cliCodexCapabilities');
    if(protocol === 'gemini-cli') return tr('api.cliGeminiCapabilities');
    return tr('api.cliLocalSession');
}
function syncCliQuickActions(){
    const configuredIds = new Set(sortedCliProviders().map(item => String(item.id || item.protocol || '').toLowerCase()));
    document.querySelectorAll('.cli-quick-btn[data-cli-kind]').forEach(button => {
        const kind = String(button.dataset.cliKind || '').toLowerCase();
        const preset = CLI_PROVIDER_PRESETS[kind];
        const configured = Boolean(preset && (configuredIds.has(String(preset.id).toLowerCase()) || configuredIds.has(String(preset.protocol).toLowerCase())));
        button.hidden = configured;
    });
    const note = document.querySelector('.cli-quick-note');
    if(note) note.hidden = ![...document.querySelectorAll('.cli-quick-btn[data-cli-kind]')].some(button => !button.hidden);
}
function renderCliProviderList(){
    if(!cliProviderList) return;
    const items = sortedCliProviders();
    cliProviderList.innerHTML = items.length ? items.map(item => {
        const active = item.id === selectedId ? 'active' : '';
        const stateClass = item.enabled === false ? 'is-disabled' : 'has-key';
        return `
            <button class="provider-card cli-provider-card ${active} ${stateClass}" type="button" onclick="selectProvider('${escapeHtml(item.id)}')">
                <span class="provider-mark"><i data-lucide="terminal" class="w-4 h-4"></i></span>
                <span class="provider-info">
                    <span class="provider-name">${escapeHtml(item.name || item.id)}</span>
                    <span class="provider-meta">${escapeHtml(cliCapabilityLabel(item))}</span>
                </span>
                <span class="provider-status-dot"></span>
            </button>
        `;
    }).join('') : `<div class="cli-provider-empty" data-i18n="api.cliNone">${escapeHtml(tr('api.cliNone'))}</div>`;
    refreshIcons();
    syncCliQuickActions();
}
function handleProviderDragStart(event, id){
    const item = providers.find(provider => provider.id === id);
    if(!item || isFixedProvider(item)){
        event.preventDefault();
        return;
    }
    providerDragId = id;
    event.currentTarget.classList.add('is-dragging');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', id);
}
function handleProviderDragOver(event, id){
    if(!providerDragId || providerDragId === id || isFixedProvider(id)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    providerList?.querySelectorAll('.provider-card-drop-target').forEach(el => el.classList.remove('provider-card-drop-target'));
    event.currentTarget.classList.add('provider-card-drop-target');
}
async function handleProviderDrop(event, targetId){
    event.preventDefault();
    providerList?.querySelectorAll('.provider-card-drop-target').forEach(el => el.classList.remove('provider-card-drop-target'));
    const sourceId = providerDragId || event.dataTransfer.getData('text/plain');
    providerDragId = '';
    if(!sourceId || sourceId === targetId || isFixedProvider(sourceId) || isFixedProvider(targetId)) return;
    const sourceIndex = providers.findIndex(item => item.id === sourceId);
    const targetIndex = providers.findIndex(item => item.id === targetId);
    if(sourceIndex < 0 || targetIndex < 0) return;
    const previousProviders = [...providers];
    const [moved] = providers.splice(sourceIndex, 1);
    const adjustedTargetIndex = providers.findIndex(item => item.id === targetId);
    providers.splice(adjustedTargetIndex, 0, moved);
    renderProviderList();
    if(!await saveProviders()){
        providers = previousProviders;
        renderProviderList();
        renderEditor();
    }
}
function handleProviderDragEnd(){
    providerDragId = '';
    providerList?.querySelectorAll('.is-dragging,.provider-card-drop-target').forEach(el => {
        el.classList.remove('is-dragging', 'provider-card-drop-target');
    });
}
function renderCanvasModelProviderSelect(){
    if(!canvasModelProviderSelect) return;
    const items = visibleProviders();
    canvasModelProviderSelect.innerHTML = items.map(item => `<option value="${escapeAttr(item.id)}">${escapeHtml(item.name || item.id)}</option>`).join('');
    const selected = items.some(item => item.id === selectedId) ? selectedId : (items[0]?.id || '');
    canvasModelProviderSelect.value = selected;
    canvasModelProviderSelect.disabled = !items.length;
}
function renderEditor(){
    const item = provider();
    if(!item) return;
    syncApiSettingsView();
    editorTitle.textContent = comfyuiSettingsMode
        ? tr('api.aiAppsTitle')
        : apiSettingsSection === 'models'
        ? tr('api.canvasModelsTitle')
        : (item.name || item.id);
    if(editorSub) editorSub.textContent = '';
    nameInput.value = item.name || '';
    idInput.value = item.id || '';
    updateIdPreview();
    clearVerifyResult();
    baseInput.placeholder = EXAMPLE_BASE_URL;
    baseInput.value = item.base_url || '';
    const lockedApi = lockedRecommendedApi(item);
    if(lockedApi) applyLockedRecommendedProtocol(item);
    if(protocolInput){
        const protocolValue = String(item.protocol || 'openai').toLowerCase();
        protocolInput.value = item.id === 'runninghub'
            ? 'runninghub'
            : item.id === 'volcengine'
            ? 'volcengine'
            : item.id === 'ai-money'
            ? 'openai'
            : API_PROTOCOLS.includes(protocolValue)
            ? protocolValue
            : 'openai';
        protocolInput.disabled = FIXED_PROTOCOL_PROVIDER_IDS.has(item.id) || Boolean(lockedApi);
        protocolInput.title = lockedApi ? '推荐平台使用固定协议' : (protocolInput.disabled ? '内置平台使用固定协议' : '');
    }
    if(imageRequestModeInput){
        const requestedMode = normalizeImageRequestMode(item.image_request_mode);
        imageRequestModeInput.value = requestedMode;
        imageRequestModeInput.disabled = Boolean(lockedApi) || item.id === 'modelscope' || item.id === 'runninghub' || item.id === 'volcengine' || item.id === 'ai-money' || CLI_PROTOCOLS.has(String(protocolInput?.value || item.protocol || '').toLowerCase());
        imageRequestModeInput.title = lockedApi ? '推荐平台使用固定图片协议' : '';
    }
    if(imageEditRouteInput){
        imageEditRouteInput.value = normalizeImageEditRoute(item.image_edit_route);
        imageEditRouteInput.disabled = item.id === 'modelscope' || item.id === 'runninghub' || item.id === 'volcengine' || item.id === 'ai-money' || CLI_PROTOCOLS.has(String(protocolInput?.value || item.protocol || '').toLowerCase());
    }
    keyInput.value = item.api_key || '';
    keyInput.placeholder = item.has_key ? `${tr('api.keepCurrentKey')} ${item.key_preview || ''}` : tr('api.enterKey');
    keyHint.textContent = keyStatusText(item.has_key);
    const isModelScope = item.id === 'modelscope';
    const isRunningHub = item.id === 'runninghub';
    const isVolcengine = item.id === 'volcengine' || String(protocolInput?.value || item.protocol || '').toLowerCase() === 'volcengine';
    const isStandaloneVolcengine = item.id === 'volcengine';
    const isAiMoney = item.id === 'ai-money';
    const isAgnes = item.id === 'agnes';
    const isJimeng = String(protocolInput?.value || item.protocol || '').toLowerCase() === 'jimeng';
    const isCodex = String(protocolInput?.value || item.protocol || '').toLowerCase() === 'codex';
    const isGeminiCli = String(protocolInput?.value || item.protocol || '').toLowerCase() === 'gemini-cli';
    const showCustomGuide = isCustomApiProvider(item);
    nameInput.disabled = isAiMoney || isAgnes;
    baseInput.disabled = isModelScope || isRunningHub || isVolcengine || isAiMoney || isAgnes;
    if(isRunningHub){
        ensureRunningHubRegions(item);
        if(!RUNNINGHUB_REGIONS[runningHubModelRegion]) runningHubModelRegion = runningHubRegionFromItem(item);
        activateRunningHubRegion(item, runningHubModelRegion);
        syncRunningHubRegion();
        Object.keys(RUNNINGHUB_REGIONS).forEach(region => {
            const regionState = runningHubRegionPublicState(item, region);
            const enabledInput = runningHubRegionEnabledInput(region);
            const freeInput = runningHubRegionInput(region, 'free');
            const walletInput = runningHubRegionInput(region, 'wallet');
            const freeHint = runningHubRegionUi(region, 'freeHint');
            const walletHint = runningHubRegionUi(region, 'walletHint');
            if(enabledInput) enabledInput.checked = regionState.enabled === true;
            if(freeInput){
                freeInput.value = '';
                freeInput.placeholder = regionState.has_key
                    ? `${tr('api.keepCurrentKey')} ${regionState.key_preview || ''}`
                    : tr('api.rhEnterCoinKey');
            }
            if(walletInput){
                walletInput.value = '';
                walletInput.placeholder = regionState.has_wallet_key
                    ? `${tr('api.keepCurrentKey')} ${regionState.wallet_key_preview || ''}`
                    : tr('api.rhEnterWalletKey');
            }
            if(freeHint) freeHint.textContent = rhFreeKeyHintText(regionState);
            if(walletHint) walletHint.textContent = rhWalletKeyHintText(regionState);
        });
        renderRunningHubCards();
    }
    if(isVolcengine){
        item.base_url = item.base_url || VOLCENGINE_DEFAULT_BASE_URL;
        item.protocol = 'volcengine';
        item.volcengine_project_name = item.volcengine_project_name || VOLCENGINE_DEFAULT_PROJECT_NAME;
        item.volcengine_region = item.volcengine_region || VOLCENGINE_DEFAULT_REGION;
        keyInput.placeholder = item.has_key ? `保持当前方舟 API Key ${item.key_preview || ''}` : '输入方舟 API Key';
        keyHint.textContent = volcengineArkKeyHintText(item);
        if(volcArkKeyHint) volcArkKeyHint.textContent = volcengineArkKeyHintText(item);
        if(volcAkInput){
            volcAkInput.value = '';
            volcAkInput.placeholder = item.has_volcengine_access_key ? `保持当前 AK ${item.volcengine_access_key_preview || ''}` : 'Access Key ID';
        }
        if(volcSkInput){
            volcSkInput.value = '';
            volcSkInput.placeholder = item.has_volcengine_secret_key ? `保持当前 SK ${item.volcengine_secret_key_preview || ''}` : 'Secret Access Key';
        }
        if(volcAssetKeyHint) volcAssetKeyHint.textContent = volcengineAssetKeyHintText(item);
        if(volcProjectInput) volcProjectInput.value = item.volcengine_project_name || VOLCENGINE_DEFAULT_PROJECT_NAME;
        if(volcRegionInput) volcRegionInput.value = item.volcengine_region || VOLCENGINE_DEFAULT_REGION;
    }
    if(isAiMoney){
        item.name = 'laohu';
        item.base_url = AI_MONEY_DEFAULT_BASE_URL;
        item.protocol = 'openai';
        item.image_request_mode = 'openai';
        nameInput.value = item.name;
        baseInput.value = item.base_url;
        keyInput.placeholder = item.has_key ? `${tr('api.keepCurrentKey')} ${item.key_preview || ''}` : tr('api.aiMoneyKeyPlaceholder');
        keyHint.textContent = keyStatusText(item.has_key);
    }
    if(isJimeng){
        applyCliProtocolDefaults(item, 'jimeng');
        keyInput.placeholder = '即梦 CLI 使用本机 dreamina login，无需 API Key';
        keyHint.textContent = '请先在终端安装 dreamina CLI，并执行 dreamina login';
    }
    if(isCodex){
        applyCliProtocolDefaults(item, 'codex');
        keyInput.placeholder = 'GPT CLI 自动跟随当前 Codex 登录，无需在此填写 API Key';
        keyHint.textContent = 'GPT CLI 只支持文本生成；auto 跟随当前 Codex 默认模型，具体模型只覆盖当前节点的本次调用，不修改桌面端或其他节点；画布不保存、恢复或覆盖登录凭据';
    }
    if(isGeminiCli){
        applyCliProtocolDefaults(item, 'gemini-cli');
        keyInput.placeholder = 'Antigravity CLI 使用本机 agy 登录态，无需 API Key';
        keyHint.textContent = '请先安装 Antigravity CLI，并在终端执行 agy 完成登录';
    }
    document.body.classList.toggle('show-ms', isModelScope);
    document.body.classList.toggle('show-runninghub', isRunningHub);
    document.body.classList.toggle('show-volcengine', isVolcengine);
    document.body.classList.toggle('show-volcengine-standalone', isStandaloneVolcengine);
    document.body.classList.toggle('show-ai-money', isAiMoney);
    document.body.classList.toggle('show-jimeng', isJimeng);
    document.body.classList.toggle('show-codex', isCodex);
    document.body.classList.toggle('show-gemini-cli', isGeminiCli);
    document.body.classList.toggle('show-custom-provider-guide', showCustomGuide);
    if(customProviderGuide){
        customProviderGuide.hidden = !showCustomGuide;
        customProviderGuide.style.display = showCustomGuide ? 'grid' : 'none';
    }
    updateApimartDomesticHint(item);
    renderProviderOnboarding(item);
    renderRecommendApi();
    if(runninghubConfigBlock){
        const showRunningHubConfig = comfyuiSettingsMode && comfyuiSettingsSection === 'runninghub' && isRunningHub;
        runninghubConfigBlock.hidden = !showRunningHubConfig;
        runninghubConfigBlock.style.display = showRunningHubConfig ? 'flex' : 'none';
    }
    if(!isRunningHub){
        Object.keys(RUNNINGHUB_REGIONS).forEach(region => {
            const input = runningHubRegionAppInput(region);
            const list = runningHubRegionUi(region, 'apps');
            const count = runningHubRegionUi(region, 'count');
            if(input) input.value = '';
            if(list) list.innerHTML = '';
            if(count) count.textContent = '0';
        });
        if(rhWorkflowsList) rhWorkflowsList.innerHTML = '';
        if(rhWorkflowsCount) rhWorkflowsCount.textContent = '0';
    }
    if(runningHubModelRegionTabs){
        const showRegionTabs = !comfyuiSettingsMode && apiSettingsSection === 'models' && isRunningHub;
        runningHubModelRegionTabs.hidden = !showRegionTabs;
        runningHubModelRegionTabs.querySelectorAll?.('button[data-region]').forEach(button => {
            const active = showRegionTabs && button.dataset.region === runningHubModelRegion;
            button.classList.toggle('active', active);
            button.setAttribute('aria-selected', active ? 'true' : 'false');
        });
    }
    if(msLoraBlock) msLoraBlock.style.display = isModelScope ? 'flex' : 'none';
    if(jimengCliPanel){
        jimengCliPanel.hidden = !isJimeng;
        jimengCliPanel.style.display = isJimeng ? 'flex' : 'none';
        if(isJimeng) refreshJimengStatus(false);
    }
    if(codexCliPanel){
        codexCliPanel.hidden = !isCodex;
        codexCliPanel.style.display = isCodex ? 'flex' : 'none';
        if(isCodex) refreshCodexStatus(false);
    }
    if(geminiCliPanel){
        geminiCliPanel.hidden = !isGeminiCli;
        geminiCliPanel.style.display = isGeminiCli ? 'flex' : 'none';
        if(isGeminiCli) refreshGeminiCliStatus(false);
    }
    const deleteBtn = document.getElementById('deleteBtn');
    if(deleteBtn) deleteBtn.style.display = (apiSettingsSection === 'models' || comfyuiSettingsMode || isFixedProvider(item)) ? 'none' : 'inline-flex';
    renderModels('image');
    renderModels('chat');
    renderModels('video');
    renderModels('audio');
    renderModels('music');
    if(isModelScope) renderMsLoras();
    else if(msLoraList) msLoraList.innerHTML = '';
    renderCanvasModelProviderSelect();
    syncCanvasModelCategoryAvailability(item);
    selectCanvasModelCategory(canvasModelCategory);
    renderProviderList();
}
function showVerifyResult(html){ const el = document.getElementById('verifyResult'); if(el){ el.style.display = 'block'; el.innerHTML = html; } }
function clearVerifyResult(){ const el = document.getElementById('verifyResult'); if(el){ el.style.display = 'none'; el.innerHTML = ''; } }
function prettyJson(value){
    try { return JSON.stringify(value, null, 2); } catch(_) { return String(value || ''); }
}
function jimengCreditText(raw){
    if(!raw) return '';
    const parts = [];
    const seen = new Set();
    const visit = value => {
        if(!value || typeof value !== 'object') return;
        Object.entries(value).forEach(([key, item]) => {
            const low = key.toLowerCase();
            if(/credit|balance|quota|point|coin|积分|余额/.test(low) && item !== null && typeof item !== 'object'){
                const label = `${key}: ${item}`;
                if(!seen.has(label)){ seen.add(label); parts.push(label); }
            }
            if(item && typeof item === 'object') visit(item);
        });
    };
    visit(raw);
    return parts.join(' · ') || prettyJson(raw);
}
function setJimengStatus(text, ok=null){
    if(!jimengCliStatus) return;
    jimengCliStatus.textContent = text || '未检测';
    jimengCliStatus.classList.toggle('ok', ok === true);
    jimengCliStatus.classList.toggle('bad', ok === false);
}
function renderJimengLoginBox(data){
    if(!jimengLoginBox) return;
    jimengLoginBox.hidden = false;
    if(data?.logged_in){
        jimengLoginBox.innerHTML = `
            <div class="jimeng-login-success"><i data-lucide="circle-check" class="w-5 h-5"></i><span>${escapeHtml(tr('api.jimengVerified'))}</span></div>
        `;
        refreshIcons();
        return;
    }
    if(data?.state === 'expired' || data?.state === 'failed'){
        const message = data?.message || tr(data.state === 'expired' ? 'api.jimengExpired' : 'api.jimengFailed');
        jimengLoginBox.innerHTML = `
            <div class="jimeng-login-terminal">
                <i data-lucide="triangle-alert" class="w-5 h-5"></i>
                <span>${escapeHtml(message)}</span>
                <button class="action-btn" type="button" onclick="startJimengLogin()"><i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr('api.jimengRetry'))}</span></button>
            </div>
        `;
        refreshIcons();
        return;
    }
    const ready = data?.has_qr === true;
    const qrVersion = encodeURIComponent(String(data?.started_at || Date.now()));
    const qrHtml = ready
        ? `<img class="jimeng-qr-img" src="/api/jimeng/login/qr?v=${qrVersion}" alt="${escapeAttr(tr('api.jimengQrAlt'))}">`
        : `<div class="jimeng-qr-wait"><i data-lucide="loader-circle" class="w-6 h-6"></i><span>${escapeHtml(tr('api.jimengQrWaiting'))}</span></div>`;
    const codeHtml = data?.user_code
        ? `<div class="jimeng-user-code"><span>${escapeHtml(tr('api.jimengUserCode'))}</span><strong>${escapeHtml(data.user_code)}</strong></div>`
        : '';
    const expiresHtml = data?.expires_at
        ? `<div class="jimeng-login-expiry">${escapeHtml(tr('api.jimengExpiresAt'))} ${escapeHtml(data.expires_at)}</div>`
        : '';
    jimengLoginBox.innerHTML = `
        <div class="jimeng-qr-wrap">${qrHtml}</div>
        <div class="jimeng-login-guide">
            <div class="jimeng-login-title">${escapeHtml(tr('api.jimengScanTitle'))}</div>
            <div class="jimeng-login-desc">${escapeHtml(tr('api.jimengBrowserDesc'))}</div>
            <button class="action-btn jimeng-browser-btn" type="button" onclick="openJimengVerification()" ${ready ? '' : 'disabled'}>
                <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
                <span>${escapeHtml(tr('api.jimengOpenBrowser'))}</span>
            </button>
            ${codeHtml}
            ${expiresHtml}
        </div>
    `;
    refreshIcons();
}
let jimengLoginTimer = null;
async function refreshJimengStatus(showCredit=true){
    if(!jimengCliPanel || jimengCliPanel.hidden) return;
    setJimengStatus('检测中...');
    try {
        const data = await fetch('/api/jimeng/status').then(r => r.json());
        setJimengStatus(data.logged_in ? '已登录' : (data.installed ? '未登录' : '未安装'), data.logged_in === true);
        if(data.installed && data.version_ok === false && jimengCredit){
            jimengCredit.textContent = `⚠ 检测到 dreamina CLI 版本 ${data.cli_version || '未知'}，低于推荐的 ${data.min_version || '1.4.2'}。旧版本任务状态可能无法更新，请升级 CLI。`;
        } else if(showCredit && data.raw && jimengCredit){
            jimengCredit.textContent = jimengCreditText(data.raw);
        }
    } catch(e){
        setJimengStatus('检测失败', false);
        if(jimengCredit) jimengCredit.textContent = e.message || String(e);
    }
}
async function startJimengLogin(){
    setJimengStatus(tr('api.jimengWaitingVerify'));
    if(jimengCredit) jimengCredit.textContent = '';
    try {
        const data = await fetch('/api/jimeng/login/start', {method:'POST'}).then(async r => {
            const json = await r.json();
            if(!r.ok) throw new Error(json.detail || '启动登录失败');
            return json;
        });
        renderJimengLoginBox(data);
        clearInterval(jimengLoginTimer);
        jimengLoginTimer = setInterval(pollJimengLogin, 2500);
        refreshIcons();
    } catch(e){
        setJimengStatus('登录失败', false);
        if(jimengLoginBox){
            jimengLoginBox.hidden = false;
            jimengLoginBox.innerHTML = `<pre>${escapeHtml(e.message || String(e))}</pre>`;
        }
    }
}
async function openJimengVerification(){
    try {
        const response = await fetch('/api/jimeng/login/open-verification', {method:'POST'});
        await readApiResponse(response, tr('api.jimengOpenFailed'));
        setJimengStatus(tr('api.jimengWaitingVerify'));
    } catch(e){
        setJimengStatus(tr('api.jimengOpenFailed'), false);
        if(jimengCredit) jimengCredit.textContent = e.message || String(e);
    }
}
async function pollJimengLogin(){
    try {
        const data = await fetch('/api/jimeng/login/status').then(r => r.json());
        renderJimengLoginBox(data);
        if(data.logged_in){
            clearInterval(jimengLoginTimer);
            setJimengStatus('已登录', true);
            if(jimengCredit) jimengCredit.textContent = jimengCreditText(data.raw);
        } else if(data.running){
            setJimengStatus(tr('api.jimengWaitingVerify'));
        } else if(data?.state === 'expired'){
            clearInterval(jimengLoginTimer);
            setJimengStatus(tr('api.jimengExpired'), false);
        } else if(data?.state === 'failed'){
            clearInterval(jimengLoginTimer);
            setJimengStatus(tr('api.jimengFailed'), false);
        } else {
            clearInterval(jimengLoginTimer);
            setJimengStatus('未登录', false);
        }
    } catch(e){
        clearInterval(jimengLoginTimer);
        setJimengStatus('登录检测失败', false);
    }
}
async function refreshJimengCredit(){
    setJimengStatus('查询余额...');
    try {
        const data = await fetch('/api/jimeng/credit').then(async r => {
            const json = await r.json();
            if(!r.ok) throw new Error(json.detail || '查询余额失败');
            return json;
        });
        setJimengStatus('已登录', true);
        if(jimengCredit) jimengCredit.textContent = jimengCreditText(data.raw);
    } catch(e){
        setJimengStatus('未登录', false);
        if(jimengCredit) jimengCredit.textContent = e.message || String(e);
    }
}
async function logoutJimeng(){
    if(!await StudioDialog.confirm('确认退出即梦 CLI 登录？', {type:'danger'})) return;
    try {
        const data = await fetch('/api/jimeng/logout', {method:'POST'}).then(async r => {
            const json = await r.json();
            if(!r.ok) throw new Error(json.detail || '退出登录失败');
            return json;
        });
        setJimengStatus('已退出', false);
        if(jimengCredit) jimengCredit.textContent = prettyJson(data.raw);
        if(jimengLoginBox) jimengLoginBox.hidden = true;
    } catch(e){
        setJimengStatus('退出失败', false);
        if(jimengCredit) jimengCredit.textContent = e.message || String(e);
    }
}
function openJimengHelp(){
    if(!jimengHelpOverlay) return;
    jimengHelpOverlay.style.display = 'flex';
    loadJimengHelp();
}
function closeJimengHelp(){
    if(jimengHelpOverlay) jimengHelpOverlay.style.display = 'none';
}
async function loadJimengHelp(){
    if(!jimengHelpOutput) return;
    jimengHelpOutput.textContent = '加载中...';
    try {
        const command = jimengHelpCommand?.value || '';
        const data = await fetch('/api/jimeng/help', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({command})
        }).then(async r => {
            const json = await r.json();
            if(!r.ok) throw new Error(json.detail || '加载帮助失败');
            return json;
        });
        jimengHelpOutput.textContent = data.text || prettyJson(data.raw);
    } catch(e){
        jimengHelpOutput.textContent = e.message || String(e);
    }
}
function setCodexStatus(text, ok=null){
    if(!codexCliStatus) return;
    codexCliStatus.textContent = text || '未检测';
    codexCliStatus.classList.toggle('ok', ok === true);
    codexCliStatus.classList.toggle('bad', ok === false);
    codexCliStatus.classList.toggle('pending', ok === null);
}
async function refreshCodexStatus(showInfo=true){
    if(!codexCliPanel || codexCliPanel.hidden) return;
    setCodexStatus('检测中...');
    try {
        const data = await fetch('/api/codex/status').then(r => r.json());
        const statusText = !data.installed
            ? '未安装'
            : data.logged_in === true
            ? '已安装 · 已登录'
            : data.logged_in === false
            ? '已安装 · 未登录'
            : '已安装 · 登录待确认';
        setCodexStatus(statusText, data.installed ? (data.logged_in === false ? false : true) : false);
        if(showInfo && codexCliInfo){
            const parts = [];
            if(data.version) parts.push(data.version);
            if(data.path) parts.push(data.path);
            if(data.message) parts.push(data.message);
            codexCliInfo.textContent = parts.join(' · ');
        }
        if(codexCliPanel && data.logged_in === false) codexCliPanel.classList.add('codex-needs-login');
        else codexCliPanel?.classList.remove('codex-needs-login');
    } catch(e){
        setCodexStatus('检测失败', false);
        if(codexCliInfo) codexCliInfo.textContent = e.message || String(e);
    }
}
function openCodexHelp(){
    if(!codexHelpOverlay) return;
    codexHelpOverlay.style.display = 'flex';
    loadCodexHelp();
}
function closeCodexHelp(){
    if(codexHelpOverlay) codexHelpOverlay.style.display = 'none';
}
async function loadCodexHelp(){
    if(!codexHelpOutput) return;
    codexHelpOutput.textContent = '加载中...';
    try {
        const command = codexHelpCommand?.value || '';
        const data = await fetch('/api/codex/help', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({command})
        }).then(async r => {
            const json = await r.json();
            if(!r.ok) throw new Error(json.detail || '加载帮助失败');
            return json;
        });
        codexHelpOutput.textContent = data.text || prettyJson(data.raw);
    } catch(e){
        codexHelpOutput.textContent = e.message || String(e);
    }
}
function setGeminiCliStatus(text, ok=null){
    if(!geminiCliStatus) return;
    geminiCliStatus.textContent = text || '未检测';
    geminiCliStatus.classList.toggle('ok', ok === true);
    geminiCliStatus.classList.toggle('bad', ok === false);
}
async function refreshGeminiCliStatus(showInfo=true){
    if(!geminiCliPanel || geminiCliPanel.hidden) return;
    setGeminiCliStatus('检测中...');
    try {
        const data = await fetch('/api/gemini-cli/status').then(r => r.json());
        setGeminiCliStatus(data.installed ? '已安装' : '未安装', data.installed === true);
        if(showInfo && geminiCliInfo){
            const parts = [];
            if(data.version) parts.push(data.version);
            if(data.path) parts.push(data.path);
            if(data.message) parts.push(data.message);
            geminiCliInfo.textContent = parts.join(' · ');
        }
    } catch(e){
        setGeminiCliStatus('检测失败', false);
        if(geminiCliInfo) geminiCliInfo.textContent = e.message || String(e);
    }
}
function openGeminiCliHelp(){
    if(!geminiCliHelpOverlay) return;
    geminiCliHelpOverlay.style.display = 'flex';
    loadGeminiCliHelp();
}
function closeGeminiCliHelp(){
    if(geminiCliHelpOverlay) geminiCliHelpOverlay.style.display = 'none';
}
async function loadGeminiCliHelp(){
    if(!geminiCliHelpOutput) return;
    geminiCliHelpOutput.textContent = '加载中...';
    try {
        const command = geminiCliHelpCommand?.value || '';
        const data = await fetch('/api/gemini-cli/help', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({command})
        }).then(async r => {
            const json = await r.json();
            if(!r.ok) throw new Error(json.detail || '加载帮助失败');
            return json;
        });
        geminiCliHelpOutput.textContent = data.text || prettyJson(data.raw);
    } catch(e){
        geminiCliHelpOutput.textContent = e.message || String(e);
    }
}
function currentProviderApiKey(item, region=''){
    if(item?.id === 'runninghub'){
        const targetRegion = RUNNINGHUB_REGIONS[region] ? region : currentRunningHubRegion(item);
        return runningHubRegionInput(targetRegion, 'wallet')?.value.trim()
            || runningHubRegionInput(targetRegion, 'free')?.value.trim()
            || '';
    }
    return keyInput.value.trim();
}
function currentRunningHubRegion(item){
    return item?.id === 'runninghub' ? runningHubRegionFromItem(item) : '';
}
function runningHubRegionPublicState(item, region){
    const regions = item?.rh_regions && typeof item.rh_regions === 'object' ? item.rh_regions : {};
    return regions[region] && typeof regions[region] === 'object' ? regions[region] : {};
}
function normalizeImageRequestMode(value){
    const mode = String(value || '').trim().toLowerCase();
    return ['openai', 'openai-json', 'openai-video-proxy', 'openai-responses', 'tudou-async'].includes(mode) ? mode : 'openai';
}
function normalizeImageEditRoute(value){
    const route = String(value || '').trim().toLowerCase();
    return ['general', 'auto', 'chat'].includes(route) ? route : 'general';
}
function imageRequestModeLabel(mode){
    const normalized = normalizeImageRequestMode(mode);
    if(normalized === 'openai-json') return 'OpenAI JSON';
    if(normalized === 'openai-video-proxy') return 'OpenAI 中转';
    if(normalized === 'openai-responses') return 'OpenAI RS';
    if(normalized === 'tudou-async') return '土豆 GPT-Image-2 异步';
    return 'OpenAI 标准';
}
function isRunningHubContext(item, baseUrl=''){
    const protocol = String(protocolInput?.value || item?.protocol || '').trim().toLowerCase();
    const url = String(baseUrl || baseInput?.value || item?.base_url || '').trim().toLowerCase();
    return item?.id === 'runninghub'
        || protocol === 'runninghub'
        || url.includes('runninghub.cn')
        || url.includes('runninghub.ai');
}
function applyDetectedImageRequestMode(mode){
    const item = provider();
    if(!item || !imageRequestModeInput) return false;
    if(applyLockedRecommendedProtocol(item)){
        if(protocolInput) protocolInput.value = item.protocol;
        imageRequestModeInput.value = item.image_request_mode;
        return false;
    }
    const detected = normalizeImageRequestMode(mode);
    const changed = normalizeImageRequestMode(item.image_request_mode) !== detected || normalizeImageRequestMode(imageRequestModeInput.value) !== detected;
    imageRequestModeInput.value = detected;
    item.image_request_mode = detected;
    return changed;
}
function applyDetectedProtocol(protocol){
    const item = provider();
    const detected = String(protocol || '').toLowerCase();
    if(!item || !protocolInput || !API_PROTOCOLS.includes(detected)) return false;
    if(applyLockedRecommendedProtocol(item)){
        protocolInput.value = item.protocol;
        if(imageRequestModeInput) imageRequestModeInput.value = item.image_request_mode;
        return false;
    }
    if(String(protocolInput.value || '').toLowerCase() === detected && String(item.protocol || '').toLowerCase() === detected) return false;
    protocolInput.value = detected;
    item.protocol = detected;
    item.base_url = CLI_PROTOCOLS.has(detected) ? '' : (baseInput?.value.trim() || item.base_url || '');
    if(detected === 'volcengine'){
        item.video_models = unique(item.video_models || []);
        item.volcengine_project_name = item.volcengine_project_name || VOLCENGINE_DEFAULT_PROJECT_NAME;
        item.volcengine_region = item.volcengine_region || VOLCENGINE_DEFAULT_REGION;
    }
    if(detected === 'runninghub'){
        item.base_url = normalizeRunningHubBaseUrl(item.base_url);
        item.image_models = unique(item.image_models || []);
        item.chat_models = unique(item.chat_models || []);
        item.video_models = unique(item.video_models || []);
    }
    applyCliProtocolDefaults(item, detected, true);
    protocolInput.dispatchEvent(new Event('change'));
    return true;
}

function runninghubModelSourceNote(data){
    const raw = data?.raw || {};
    const source = String(raw.source || '').toLowerCase();
    const sourceLabel = source === 'official-remote'
        ? tr('api.rhOfficialRegistryOnline')
        : source === 'official-snapshot'
        ? tr('api.rhOfficialRegistrySnapshot')
        : source === 'emergency-fallback'
        ? tr('api.rhEmergencyFallback')
        : '';
    const parts = [];
    if(sourceLabel) parts.push(`来源：${sourceLabel}`);
    if(raw.registry_count !== undefined) parts.push(`Schema ${Number(raw.registry_count || 0)}`);
    if(raw.confirmed_count !== undefined) parts.push(`${tr('api.rhModelConfirmed')} ${Number(raw.confirmed_count || 0)}`);
    if(raw.unverified_count !== undefined) parts.push(`${tr('api.rhModelUnverified')} ${Number(raw.unverified_count || 0)}`);
    if(raw.llm_count !== undefined) parts.push(`LLM ${Number(raw.llm_count || 0)}`);
    const text = parts.join(' · ');
    const warning = source === 'emergency-fallback' ? ` · ${tr('api.rhCatalogFallbackWarning')}` : '';
    return text ? ` · ${text}${warning}` : '';
}

async function probeAsync(){
    const item = provider();
    if(!item) return;
    const btn = document.getElementById('probeAsyncBtn');
    const baseUrl = baseInput.value.trim();
    let isTudouHost = false;
    try {
        const host = new URL(baseUrl).hostname.toLowerCase();
        isTudouHost = host === 'api.ai-tudou.net' || host.endsWith('.ai-tudou.net');
    } catch(e) {}
    // The official Tudou host has a dedicated GPT-Image-2 async image route.
    // Select it before the network check so a failed probe never leaves this
    // known platform displayed as the generic OpenAI image interface.
    if(isTudouHost && imageRequestModeInput){
        item.image_request_mode = 'tudou-async';
        imageRequestModeInput.value = 'tudou-async';
    }
    const isCliProtocol = CLI_PROTOCOLS.has(String(protocolInput?.value || item.protocol || '').toLowerCase());
    if(!baseUrl && !isCliProtocol){ await StudioDialog.alert('请先填写请求地址', {type:'warning'}); return; }
    if(btn){ btn.disabled = true; btn.querySelector('span').textContent = '检测中...'; }
    showVerifyResult(`<span style="color:var(--muted);font-size:11px;font-weight:700">正在检测协议类型...</span>`);
    try {
        const apiKey = currentProviderApiKey(item);
        const currentProtocol = String(protocolInput?.value || item.protocol || 'openai').toLowerCase();
        if(isRunningHubContext(item, baseUrl)){
            const data = await fetch('/api/providers/test-connection', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({
                    base_url:baseUrl,
                    api_key:apiKey,
                    provider_id:'runninghub',
                    protocol:'runninghub',
                    image_request_mode:'openai',
                    region:currentRunningHubRegion(item)
                })
            }).then(async r => {
                return readApiResponse(r, 'RunningHub 验证失败');
            });
            applyDetectedProtocol('runninghub');
            setFetchedModelState(data);
            const openBtn = document.getElementById('openPickerBtn');
            if(openBtn){ openBtn.disabled = false; openBtn.style.opacity = '1'; }
            showVerifyResult(`<span style="color:#15803d;font-size:11px;font-weight:800">✓ ${escapeHtml(trf('api.rhCatalogLoaded', {count:data.model_count || data.total || 0}))}${runninghubModelSourceNote(data)}</span>`);
            return;
        }
        const data = await fetch('/api/providers/probe-async', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                base_url: baseUrl,
                api_key: apiKey,
                provider_id: item.id,
                protocol: currentProtocol,
                image_request_mode: imageRequestModeInput?.value || item.image_request_mode || 'openai'
            })
        }).then(async r => {
            return readApiResponse(r, '协议检测失败');
        });
        const detectedProtocol = String(data.protocol || '').toLowerCase();
        const isAsync = data.ok === true && detectedProtocol === 'apimart';
        const isOpenAiCompat = data.ok === true && detectedProtocol === 'openai';
        const keepManualProtocol = ['gemini', 'volcengine', 'jimeng', 'codex', 'gemini-cli'].includes(currentProtocol);
        if(protocolInput && !keepManualProtocol){
            applyDetectedProtocol(detectedProtocol || (isAsync ? 'apimart' : 'openai'));
        }
        if(data.image_request_mode) applyDetectedImageRequestMode(data.image_request_mode);
        if(isTudouHost) applyDetectedImageRequestMode('tudou-async');
        const rawJson = JSON.stringify(data.raw, null, 2);
        const probeMessage = String(data.message || '');
        const hideTasksEndpointTip = probeMessage.includes('/v1/tasks/');
        const color = (isAsync || isOpenAiCompat || data.ok === true) ? '#15803d' : data.ok === null ? '#b45309' : '#64748b';
        const icon = (isAsync || isOpenAiCompat || data.ok === true) ? '✓' : '⚠';
        const proto = detectedProtocol === 'volcengine'
            ? '方舟/Ark 任务协议'
            : isAsync
                ? 'APIMart 异步'
                : detectedProtocol === 'openai'
                    ? 'OpenAI 兼容'
                    : keepManualProtocol
                    ? (currentProtocol === 'gemini' ? 'Gemini' : currentProtocol.toUpperCase())
                    : 'OpenAI 兼容';
        showVerifyResult(`
            ${hideTasksEndpointTip ? '' : `<div style="font-size:11px;font-weight:800;color:${color}">${icon} ${escapeHtml(probeMessage)}</div>`}
            <div style="font-size:11px;color:var(--muted);font-weight:700;margin-top:2px">${keepManualProtocol ? '协议已验证为' : '协议已自动设置为'}：<strong style="color:var(--text)">${proto}</strong> · 图片接口：<strong style="color:var(--text)">${imageRequestModeLabel(imageRequestModeInput?.value || item.image_request_mode)}</strong></div>
            <details style="margin-top:6px">
                <summary style="font-size:10.5px;color:var(--muted);cursor:pointer;font-weight:700;user-select:none">▸ 查看原始响应 (HTTP ${data.status_code})</summary>
                <pre style="margin-top:6px;padding:10px 12px;border-radius:10px;background:var(--soft);border:1px solid var(--line-2);font-size:10.5px;font-family:ui-monospace,Menlo,monospace;white-space:pre-wrap;word-break:break-all;color:var(--text);max-height:200px;overflow:auto">${escapeHtml(rawJson)}</pre>
            </details>`);
    } catch(e){
        const keepManualProtocol = ['gemini', 'volcengine', 'jimeng', 'codex', 'gemini-cli'].includes(String(protocolInput?.value || item.protocol || '').toLowerCase());
        if(protocolInput && !keepManualProtocol){ protocolInput.value = 'openai'; protocolInput.dispatchEvent(new Event('change')); }
        const suffix = keepManualProtocol ? '，已保留当前手动选择的协议' : '，协议已设为 OpenAI 兼容';
        showVerifyResult(`<div style="font-size:11px;font-weight:800;color:#b45309">⚠ ${escapeHtml(e.message || String(e))}${suffix}</div>`);
    } finally {
        if(btn){ btn.disabled = false; btn.querySelector('span').textContent = '验证协议'; refreshIcons(); }
    }
}

async function testConnection(){
    const item = provider();
    if(!item) return;
    const btn = document.getElementById('testUrlBtn');
    const baseUrl = baseInput.value.trim();
    const isJimeng = (protocolInput?.value || '') === 'jimeng';
    const currentProtocol = String(protocolInput?.value || item.protocol || '').toLowerCase();
    const isCliProtocol = CLI_PROTOCOLS.has(currentProtocol);
    if(!baseUrl && !isJimeng && !isCliProtocol){ await StudioDialog.alert('请先填写请求地址', {type:'warning'}); return; }
    if(btn){ btn.disabled = true; btn.querySelector('span').textContent = tr('api.testingUrl') || '验证中...'; }
    showVerifyResult(`<span style="color:var(--muted);font-size:11px;font-weight:700">验证中...</span>`);
    try {
        const apiKey = currentProviderApiKey(item);
        const runninghubContext = isRunningHubContext(item, baseUrl);
        const data = await fetch('/api/providers/test-connection', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({
                base_url: baseUrl,
                api_key: apiKey,
                provider_id: runninghubContext ? 'runninghub' : item.id,
                protocol: runninghubContext ? 'runninghub' : (protocolInput?.value || 'openai'),
                image_request_mode: imageRequestModeInput?.value || item.image_request_mode || 'openai',
                region:runninghubContext ? currentRunningHubRegion(item) : ''
            })
        }).then(async r => {
            return readApiResponse(r, tr('api.urlInvalid') || '验证失败');
        });
        if(data.ok){
            const detectedProtocol = String(data.protocol || '').toLowerCase();
            if(detectedProtocol && detectedProtocol !== String(protocolInput?.value || '').toLowerCase()){
                applyDetectedProtocol(detectedProtocol);
            }
            // "验证地址" only checks reachability. Protocol and image-interface
            // selection are intentionally left untouched for this action.
            // 存入 picker 状态并启用「选择模型」按钮，但不自动弹出
            setFetchedModelState(data);
            const openBtn = document.getElementById('openPickerBtn');
            if(openBtn){ openBtn.disabled = false; openBtn.style.opacity = '1'; }
            const isRunningHubNow = runninghubContext || detectedProtocol === 'runninghub';
            const isVolcengineNow = !isRunningHubNow && (detectedProtocol === 'volcengine' || isVolcengineProvider(item));
            const volcengineNote = isVolcengineNow
                ? `<div style="margin-top:6px;color:#92400e;font-size:11px;font-weight:700">${detectedProtocol === 'volcengine' ? '已自动识别为方舟/Ark 任务协议。' : ''}火山协议提示：模型列表只代表可见模型，聊天模型建议填写你在方舟控制台创建的 <code>ep-...</code> 推理接入点。</div>`
                : '';
            const jimengNote = isJimeng ? `<div style="margin-top:6px;color:#15803d;font-size:11px;font-weight:700">即梦 CLI 已可用，可在画布里选择“即梦 CLI”生成。</div>` : '';
            const codexNote = currentProtocol === 'codex' ? `<div style="margin-top:6px;color:#15803d;font-size:11px;font-weight:700">OpenAI Codex CLI 已可用，可在画布的提示词节点中选择文本模型。</div>` : '';
            const geminiCliNote = currentProtocol === 'gemini-cli' ? `<div style="margin-top:6px;color:#15803d;font-size:11px;font-weight:700">Antigravity CLI 已可用，可在画布里选择“Antigravity CLI”聊天或测试生图。</div>` : '';
            const imageModeNote = ` · 图片接口：${imageRequestModeLabel(imageRequestModeInput?.value || item.image_request_mode)}`;
            const runninghubNote = isRunningHubNow
                ? ` · RunningHub OpenAPI${runninghubModelSourceNote(data)}`
                : imageModeNote;
            showVerifyResult(`<span style="color:#15803d;font-size:11px;font-weight:800">✓ 地址验证通过 · 找到 ${data.model_count} 个模型${runninghubNote}</span>${volcengineNote}${jimengNote}${codexNote}${geminiCliNote}`);
        } else {
            showVerifyResult(`
                <div style="font-size:11px;font-weight:800;color:#b45309">⚠ 地址验证未通过 (HTTP ${data.status})</div>
                <div style="font-size:11px;color:var(--muted);font-weight:600;margin-top:3px">${escapeHtml((data.message || '').slice(0,200))}</div>`);
        }
    } catch(e){
        showVerifyResult(`<div style="font-size:11px;font-weight:800;color:#b45309">⚠ ${escapeHtml(e.message || String(e))}</div>`);
    } finally {
        if(btn){ btn.disabled = false; btn.querySelector('span').textContent = tr('api.testUrl') || '验证地址'; }
    }
}
let lastFetchedAll = [];          // 全部模型 id 列表
let lastFetchedSuggestion = null; // 后端自动分类建议
let lastFetchedModelNames = {};   // {模型 id: 展示名}
let lastFetchedModelAvailability = {}; // RunningHub: confirmed | unverified

function clearFetchedModelState(){
    lastFetchedAll = [];
    lastFetchedSuggestion = null;
    lastFetchedModelNames = {};
    lastFetchedModelAvailability = {};
    const openBtn = document.getElementById('openPickerBtn');
    if(openBtn){
        openBtn.disabled = true;
        openBtn.style.opacity = '0.55';
    }
    closeModelPicker();
}

function setFetchedModelState(data){
    lastFetchedAll = Array.isArray(data?.all) ? data.all : [];
    lastFetchedSuggestion = {
        image: new Set(data?.image_models || []),
        chat: new Set(data?.chat_models || []),
        text: new Set(data?.chat_models || []),
        video: new Set(data?.video_models || []),
        audio: new Set(data?.audio_models || []),
    };
    lastFetchedModelNames = (data?.model_names && typeof data.model_names === 'object') ? {...data.model_names} : {};
    lastFetchedModelAvailability = (data?.model_availability && typeof data.model_availability === 'object') ? {...data.model_availability} : {};
}
function modelPickerCapabilityCategories(item, model){
    const nodeTypeToCategory = {
        text_generation:'text',
        image_generation:'image',
        video_generation:'video',
        audio_generation:'audio',
        music_generation:'music'
    };
    const itemId = String(item?.id || '').trim().toLowerCase();
    const protocol = String(item?.protocol || '').trim().toLowerCase();
    const aliases = {jimeng:'jimeng-cli', codex:'codex-cli'};
    const accepted = new Set([itemId, protocol, aliases[itemId], aliases[protocol]].filter(Boolean));
    const provider = (modelCapabilityCatalog.providers || []).find(entry => [entry?.id, entry?.capability_provider_id]
        .map(value => String(value || '').trim().toLowerCase())
        .some(id => accepted.has(id)));
    const categories = new Set();
    (provider?.models || []).forEach(profile => {
        if(String(profile?.model_id || '').trim() !== String(model || '').trim()) return;
        const category = nodeTypeToCategory[profile?.node_type];
        if(category) categories.add(category);
    });
    return categories;
}
function modelListForKind(item, kind){
    if(!item) return [];
    if(kind !== 'music'){
        const key = kind === 'image' ? 'image_models' : kind === 'video' ? 'video_models' : kind === 'audio' ? 'audio_models' : 'chat_models';
        const models = Array.isArray(item[key]) ? item[key] : [];
        if(kind !== 'audio') return models;
        return models.filter(model => {
            const categories = modelPickerCapabilityCategories(item, model);
            return !categories.has('music');
        });
    }
    return (Array.isArray(item.audio_models) ? item.audio_models : []).filter(model =>
        modelPickerCapabilityCategories(item, model).has('music') || lastFetchedSuggestion?.music?.has(model)
    );
}
function modelStorageIndex(item, kind, index){
    if(kind !== 'music') return index;
    const model = modelListForKind(item, kind)[index];
    return Array.isArray(item?.audio_models) ? item.audio_models.indexOf(model) : -1;
}
const RH_KNOWN_MODEL_LABELS = {
    'gpt-image-2.0/text-to-image-channel-low-price':'全能图片G2 · 文生图 · 低价渠道版',
    'gpt-image-2.0/edit-channel-low-price':'全能图片G2 · 图片编辑 · 低价渠道版',
    'gpt-image-2/text-to-image-official-stable':'全能图片G2 · 文生图 · 官方稳定版',
    'gpt-image-2/image-to-image-official-stable':'全能图片G2 · 图生图 · 官方稳定版',
    'nano-banana/text-to-image-official-stable':'全能图片 · 文生图 · 官方稳定版',
    'nano-banana/image-to-image-official-stable':'全能图片 · 图生图 · 官方稳定版',
    'nano-banana-pro/text-to-image-official-stable':'全能图片Pro · 文生图 · 官方稳定版',
    'nano-banana-pro/image-to-image-official-stable':'全能图片Pro · 图生图 · 官方稳定版',
};
function isRunningHubLike(item){
    const base = String(item?.base_url || '').toLowerCase();
    return item?.id === 'runninghub' || String(item?.protocol || '').toLowerCase() === 'runninghub' || base.includes('runninghub.cn') || base.includes('runninghub.ai');
}
function rhActionLabel(text){
    const value = String(text || '').toLowerCase().replace(/[_/-]+/g, ' ');
    if(/start\s+end\s+to\s+video/.test(value)) return '首尾帧视频';
    if(/multimodal\s+video/.test(value)) return '多模态视频';
    if(/image\s+to\s+video|图生视频/.test(value)) return '图生视频';
    if(/text\s+to\s+video|文生视频/.test(value)) return '文生视频';
    if(/image\s+to\s+image|image\s+edit|edit|图生图|图片编辑/.test(value)) return '图片编辑';
    if(/text\s+to\s+image|文生图/.test(value)) return '文生图';
    return '';
}
function runningHubReadableModelName(model, item){
    const raw = String(model || '').trim();
    if(!raw) return '';
    const saved = item?.model_names && typeof item.model_names === 'object' ? item.model_names[raw] : '';
    if(saved && saved !== raw) return saved;
    const fetched = lastFetchedModelNames?.[raw];
    if(fetched && fetched !== raw) return fetched;
    if(RH_KNOWN_MODEL_LABELS[raw]) return RH_KNOWN_MODEL_LABELS[raw];
    const lower = raw.toLowerCase();
    const action = rhActionLabel(raw);
    const normalized = raw.replace(/[_/-]+/g, ' ').replace(/\s+/g, ' ').trim();
    if(lower.includes('alibaba') || lower.includes('wan-') || lower.includes('wan ')){
        const version = (normalized.match(/wan\s*(\d+(?:\.\d+)?)/i) || [])[1];
        return `阿里 · 万相${version ? ' ' + version : ''}${action ? ' · ' + action : ''}`;
    }
    if(lower.includes('bytedance') || lower.includes('jimeng')){
        const version = (normalized.match(/jimeng\s*(\d+(?:\.\d+)?)/i) || [])[1];
        return `字节 · 即梦${version ? ' ' + version : ''}${action ? ' · ' + action : ''}`;
    }
    if(lower.includes('seedance')){
        const version = (normalized.match(/seedance\s*(\d+(?:\.\d+)?)/i) || [])[1];
        const fast = /fast/i.test(raw) ? ' · Fast' : '';
        return `Seedance${version ? ' · ' + version : ''}${fast}${action ? ' · ' + action : ''}`;
    }
    if(lower.includes('kling')) return `可灵${normalized.match(/\d+(?:\.\d+)?/) ? ' ' + normalized.match(/\d+(?:\.\d+)?/)[0] : ''}${/standard/i.test(raw) ? ' 标准版' : ''}${action ? ' · ' + action : ''}`;
    if(lower.includes('hailuo')) return `海螺${action ? ' · ' + action : ''}`;
    if(lower.includes('luma')) return normalized.replace(/^luma/i, 'Luma').replace(/\bimage edit\b/i, '图片编辑').replace(/\bimage to video\b/i, '图生视频').replace(/\btext to video\b/i, '文生视频');
    if(lower.includes('vidu')) return normalized.replace(/^vidu/i, 'Vidu').replace(/\bimage edit\b/i, '图片编辑').replace(/\bimage to video\b/i, '图生视频').replace(/\btext to video\b/i, '文生视频');
    if(lower.includes('gpt-image-2')) return `全能图片G2${action ? ' · ' + action : ''}`;
    if(lower.includes('nano-banana-pro')) return `全能图片Pro${action ? ' · ' + action : ''}`;
    if(lower.includes('nano-banana')) return `全能图片${action ? ' · ' + action : ''}`;
    if(lower.includes('qwen-image')) return `通义千问图像${lower.includes('pro') ? ' Pro' : ''}${action ? ' · ' + action : ''}`;
    if(lower.includes('seedream')) return `即梦 Seedream${action ? ' · ' + action : ''}`;
    return raw;
}
function modelDisplayName(model, item){
    const raw = String(model || '').trim();
    if(!raw) return '';
    if(isRunningHubLike(item)) return runningHubReadableModelName(raw, item);
    const saved = item?.model_names && typeof item.model_names === 'object' ? item.model_names[raw] : '';
    const fetched = lastFetchedModelNames?.[raw];
    return saved || fetched || raw;
}
function providerModelBadge(model, label){
    const text = `${model || ''} ${label || ''}`.toLowerCase();
    if(text.includes('gpt-image')) return 'G';
    if(String(model || '').toLowerCase() === 'auto' || text.includes('codex')) return 'C';
    if(text.includes('gpt-')) return 'GPT';
    if(text.includes('nano')) return 'N';
    if(text.includes('qwen')) return 'Q';
    if(text.includes('seedream')) return 'S';
    if(text.includes('seedance')) return 'SD';
    if(text.includes('wan') || text.includes('万相')) return 'W';
    if(text.includes('jimeng') || text.includes('即梦')) return 'J';
    if(text.includes('luma')) return 'L';
    if(text.includes('vidu')) return 'V';
    if(text.includes('alibaba') || text.includes('阿里')) return 'A';
    if(text.includes('bytedance') || text.includes('字节')) return 'B';
    return 'RH';
}

function runningHubAvailabilityBadge(model, item){
    if(!isRunningHubLike(item)) return '';
    const status = lastFetchedModelAvailability?.[model] === 'confirmed' ? 'confirmed' : 'unverified';
    const label = status === 'confirmed' ? tr('api.rhModelConfirmed') : tr('api.rhModelUnverified');
    const hint = status === 'confirmed' ? tr('api.rhModelConfirmedHint') : tr('api.rhModelUnverifiedHint');
    return `<span class="picker-model-availability picker-availability-${status}" title="${escapeAttr(hint)}">${escapeHtml(label)}</span>`;
}

async function fetchModels(){
    const item = provider();
    if(!item) return;
    if(fetchModelsController){
        fetchModelsController.abort();
        fetchModelsController = null;
        setStatus('已取消拉取模型');
        return;
    }
    syncEditor();
    const btn = document.getElementById('fetchModelsBtn');
    const baseUrl = baseInput.value.trim();
    const apiKey = currentProviderApiKey(item);
    const isJimeng = (protocolInput?.value || '') === 'jimeng';
    const isCliProtocol = CLI_PROTOCOLS.has(String(protocolInput?.value || item.protocol || '').toLowerCase());
    if(!baseUrl && !isJimeng && !isCliProtocol){ await StudioDialog.alert('请先填写请求地址', {type:'warning'}); return; }
    fetchModelsController = new AbortController();
    if(btn){ btn.disabled = false; btn.classList.add('is-cancel'); btn.querySelector('span').textContent = '取消拉取'; }
    setStatus(tr('api.fetchingModels') || '正在从上游拉取模型列表...');
    try {
        const runninghubContext = isRunningHubContext(item, baseUrl);
        const data = await fetch('/api/providers/fetch-models', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            signal:fetchModelsController.signal,
            body:JSON.stringify({
                base_url:baseUrl,
                api_key:apiKey,
                provider_id:runninghubContext ? 'runninghub' : item.id,
                protocol:runninghubContext ? 'runninghub' : (protocolInput?.value || 'openai'),
                image_request_mode:imageRequestModeInput?.value || item.image_request_mode || 'openai',
                region:runninghubContext ? currentRunningHubRegion(item) : ''
            })
        }).then(async r => {
            return readApiResponse(r, tr('api.urlInvalid') || '拉取失败');
        });
        setFetchedModelState(data);
        const detectedProtocol = String(data.protocol || '').toLowerCase();
        if(detectedProtocol && detectedProtocol !== String(protocolInput?.value || '').toLowerCase()){
            applyDetectedProtocol(detectedProtocol);
        }
        if(data.image_request_mode) applyDetectedImageRequestMode(data.image_request_mode);
        // 启用「选择模型」按钮，并 statusbar 显示已拉取数量
        const openBtn = document.getElementById('openPickerBtn');
        if(openBtn){ openBtn.disabled = false; openBtn.style.opacity = '1'; }
        const extra = (runninghubContext || detectedProtocol === 'runninghub' || item.id === 'runninghub')
            ? ` · RunningHub${runninghubModelSourceNote(data)}`
            : (detectedProtocol === 'volcengine' || isVolcengineProvider(item)) ? ' · 已识别方舟协议，火山聊天建议改填 ep-... 接入点' : '';
        const imageModeExtra = normalizeImageRequestMode(imageRequestModeInput?.value || item.image_request_mode) === 'openai-json' ? ' · 图片接口已设为 OpenAI JSON' : '';
        setStatus(`已拉取 ${data.total} 个模型 · 点「选择模型」勾选要导入的${extra}${imageModeExtra}`);
        openModelPicker();
    } catch(e){
        if(e?.name === 'AbortError') setStatus('已取消拉取模型');
        else {
            await StudioDialog.alert('拉取失败：' + (e.message || e), {type:'warning'});
            setStatus('拉取失败');
        }
    } finally {
        fetchModelsController = null;
        if(btn){ btn.disabled = false; btn.classList.remove('is-cancel'); btn.querySelector('span').textContent = tr('api.fetchModels') || '拉取模型'; refreshIcons(); }
    }
}

// —— 模型选择器浮层 ——
// 每个模型只归一类（根据用户已配置 或 关键字猜测）；勾选 = 纳入该分类
let pickerState = { category: {}, selected: {} };
let pickerVisibleIds = [];
function openModelPicker(){
    const item = provider();
    if(!item || !lastFetchedAll.length){ StudioDialog.alert('没有拉取到模型', {type:'warning'}); return; }
    const overlay = document.getElementById('modelPickerOverlay');
    // API 设置页会按用户界面缩放 body；弹层提升到 html 根层后才真正相对视口定位。
    if(overlay && overlay.parentElement !== document.documentElement){
        document.documentElement.appendChild(overlay);
    }
    const existing = { image: new Set(item.image_models||[]), text: new Set(item.chat_models||[]), chat: new Set(item.chat_models||[]), video: new Set(item.video_models||[]), audio: new Set(item.audio_models||[]), music: new Set(item.audio_models||[]) };
    const allIds = new Set([...lastFetchedAll, ...(item.image_models||[]), ...(item.chat_models||[]), ...(item.video_models||[]), ...(item.audio_models||[])]);
    pickerState = { category: {}, selected: {} };
    allIds.forEach(id => {
        // 类别归属：能力档案 > 用户已配置 > 后端建议 > 默认文本；不把 AI 应用或本地工作流放进来。
        let cat;
        const capabilityCategories = modelPickerCapabilityCategories(item, id);
        if(capabilityCategories.has('music')) cat = 'music';
        else if(capabilityCategories.has('image') || existing.image.has(id)) cat = 'image';
        else if(capabilityCategories.has('video') || existing.video.has(id)) cat = 'video';
        else if(capabilityCategories.has('audio') || existing.audio.has(id)) cat = 'audio';
        else if(capabilityCategories.has('text') || existing.text.has(id)) cat = 'text';
        else if(lastFetchedSuggestion?.image?.has(id)) cat = 'image';
        else if(lastFetchedSuggestion?.video?.has(id)) cat = 'video';
        else if(lastFetchedSuggestion?.audio?.has(id)) cat = 'audio';
        else if(lastFetchedSuggestion?.text?.has(id) || lastFetchedSuggestion?.chat?.has(id)) cat = 'text';
        else cat = 'text';
        pickerState.category[id] = cat;
        // 默认勾选状态：已在用户配置里的 = 勾选；新拉的 = 不勾选（让用户主动选）
        pickerState.selected[id] = existing.image.has(id) || existing.chat.has(id) || existing.video.has(id) || existing.audio.has(id);
    });
    // 默认 tab 切回「全部」
    document.querySelectorAll('.picker-cat-tab').forEach(t => t.classList.toggle('active', t.dataset.cat === 'all'));
    overlay.style.display = 'flex';
    renderModelPicker();
}
function closeModelPicker(){
    const overlay = document.getElementById('modelPickerOverlay');
    if(overlay) overlay.style.display = 'none';
}
function renderModelPicker(){
    const item = provider();
    const filter = (document.getElementById('pickerFilter')?.value || '').toLowerCase();
    const currentTab = document.querySelector('.picker-cat-tab.active')?.dataset.cat || 'all';
    const ids = Object.keys(pickerState.category).sort();
    // 各分类总数 / 已选数
    const totals = { all: ids.length, text:0, image:0, video:0, audio:0, music:0 };
    const selecteds = { all:0, text:0, image:0, video:0, audio:0, music:0 };
    ids.forEach(id => {
        const cat = pickerState.category[id];
        totals[cat]++;
        if(pickerState.selected[id]){ selecteds[cat]++; selecteds.all++; }
    });
    // 过滤显示
    const list = ids.filter(id => {
        const label = modelDisplayName(id, item);
        if(filter && !id.toLowerCase().includes(filter) && !label.toLowerCase().includes(filter)) return false;
        if(currentTab === 'all') return true;
        return pickerState.category[id] === currentTab;
    });
    pickerVisibleIds = list;
    const availabilityGuide = document.getElementById('pickerAvailabilityGuide');
    if(availabilityGuide) availabilityGuide.hidden = !isRunningHubLike(item);
    document.getElementById('pickerCount').textContent = trf('api.modelPickerCount', {total:totals.all, visible:list.length});
    document.querySelectorAll('.picker-cat-tab').forEach(tab => {
        const cat = tab.dataset.cat;
        tab.querySelector('.cat-count').textContent = `${selecteds[cat]}/${totals[cat]}`;
    });
    // 列表
    const html = list.map((id, index) => {
        const checked = pickerState.selected[id];
        const label = modelDisplayName(id, item);
        const badge = providerModelBadge(id, label);
        return `
            <div class="picker-row ${checked?'has-sel':''}" onclick="togglePickerRowByIndex(${index})">
                <div class="picker-checkbox ${checked?'checked':''}">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                </div>
                <div class="picker-model-badge">${escapeHtml(badge)}</div>
                <div class="picker-model-name" title="${escapeAttr(id)}">
                    <div class="picker-model-label">${escapeHtml(label || id)} ${runningHubAvailabilityBadge(id, item)}</div>
                    ${label && label !== id ? `<div class="picker-model-id">${escapeHtml(id)}</div>` : ''}
                </div>
            </div>
        `;
    }).join('');
    document.getElementById('pickerList').innerHTML = html || `<div style="padding:32px;text-align:center;color:var(--faint);font-size:12px">${escapeHtml(tr('api.modelPickerNoMatch'))}</div>`;
    // 底部汇总
    const sumImage = document.getElementById('sumImage');
    const sumVideo = document.getElementById('sumVideo');
    const sumAudio = document.getElementById('sumAudio');
    const sumUnsel = document.getElementById('sumUnsel');
    if(sumImage){ sumImage.textContent = `${tr('api.modelCategoryImage')} ${selecteds.image}`; sumImage.classList.toggle('picker-sum-chip-empty', selecteds.image === 0); }
    const sumText = document.getElementById('sumText');
    if(sumText){ sumText.textContent = `${tr('api.modelCategoryText')} ${selecteds.text}`; sumText.classList.toggle('picker-sum-chip-empty', selecteds.text === 0); }
    if(sumVideo){ sumVideo.textContent = `${tr('api.modelCategoryVideo')} ${selecteds.video}`; sumVideo.classList.toggle('picker-sum-chip-empty', selecteds.video === 0); }
    if(sumAudio){ sumAudio.textContent = `${tr('api.modelCategoryAudio')} ${selecteds.audio}`; sumAudio.classList.toggle('picker-sum-chip-empty', selecteds.audio === 0); }
    const sumMusic = document.getElementById('sumMusic');
    if(sumMusic){ sumMusic.textContent = `${tr('api.modelCategoryMusic')} ${selecteds.music}`; sumMusic.classList.toggle('picker-sum-chip-empty', selecteds.music === 0); }
    if(sumUnsel){ sumUnsel.textContent = trf('api.modelPickerUnselected', {count:totals.all - selecteds.all}); }
}
function togglePickerRow(id){
    pickerState.selected[id] = !pickerState.selected[id];
    renderModelPicker();
    void autosavePickerSelection();
}
function togglePickerRowByIndex(index){
    const id = pickerVisibleIds[index];
    if(typeof id !== 'string') return;
    togglePickerRow(id);
}
function buildPickerBulkSelection(ids, current, availability, mode, requireConfirmed){
    const next = {...(current || {})};
    (ids || []).forEach(id => {
        if(mode === 'clear') next[id] = false;
        else if(mode === 'all') next[id] = true;
        else if(mode === 'recommended') next[id] = !requireConfirmed || availability?.[id] === 'confirmed';
    });
    return next;
}
function selectPickerModels(mode){
    const item = provider();
    const ids = Object.keys(pickerState.category);
    pickerState.selected = buildPickerBulkSelection(
        ids,
        pickerState.selected,
        lastFetchedModelAvailability,
        mode,
        isRunningHubLike(item)
    );
    renderModelPicker();
    void autosavePickerSelection();
}
function selectPickerCat(cat){
    document.querySelectorAll('.picker-cat-tab').forEach(t => t.classList.toggle('active', t.dataset.cat === cat));
    renderModelPicker();
}
function pickerSelectionForProvider(item){
    const image = [], chat = [], video = [], audio = [];
    const modelNames = {};
    const previouslyEnabled = new Set([
        ...(item.image_models || []), ...(item.chat_models || []),
        ...(item.video_models || []), ...(item.audio_models || [])
    ]);
    const newlySelectedUnverified = [];
    Object.entries(pickerState.selected).forEach(([id, sel]) => {
        if(!sel) return;
        const cat = pickerState.category[id];
        if(cat === 'image') image.push(id);
        else if(cat === 'video') video.push(id);
        else if(cat === 'audio') audio.push(id);
        else if(cat === 'music') audio.push(id);
        else chat.push(id);
        const label = modelDisplayName(id, item);
        if(label && label !== id) modelNames[id] = label;
        if(isRunningHubLike(item) && !previouslyEnabled.has(id) && lastFetchedModelAvailability?.[id] !== 'confirmed'){
            newlySelectedUnverified.push(label || id);
        }
    });
    return {image, chat, video, audio, modelNames, newlySelectedUnverified};
}
function applyPickerSelectionToProvider(item){
    const selection = pickerSelectionForProvider(item);
    item.image_models = selection.image;
    item.chat_models = selection.chat;
    item.video_models = selection.video;
    item.audio_models = selection.audio;
    item.model_names = selection.modelNames;
    return selection;
}
function renderPickerSelection(item, selection){
    renderModels('image'); renderModels('chat'); renderModels('video'); renderModels('audio'); renderModels('music');
    renderMsLoras();
    return `${tr('api.modelCategoryImage')} ${selection.image.length} / ${tr('api.modelCategoryText')} ${selection.chat.length} / ${tr('api.modelCategoryVideo')} ${selection.video.length} / ${tr('api.modelCategoryAudio')} ${selection.audio.length} / ${tr('api.modelCategoryMusic')} ${selection.audio.filter(model => pickerState.category[model] === 'music').length}`;
}
async function autosavePickerSelection(){
    const item = provider();
    if(!item) return false;
    const previousModels = {
        image_models:[...(item.image_models || [])],
        chat_models:[...(item.chat_models || [])],
        video_models:[...(item.video_models || [])],
        audio_models:[...(item.audio_models || [])],
        model_names:{...((item.model_names && typeof item.model_names === 'object') ? item.model_names : {})}
    };
    const selection = applyPickerSelectionToProvider(item);
    if(selection.newlySelectedUnverified.length && !await StudioDialog.confirm(trf('api.rhEnableUnverifiedConfirm', {count:selection.newlySelectedUnverified.length}), {type:'warning'})){
        Object.assign(item, previousModels);
        renderPickerSelection(item, {image:previousModels.image_models, chat:previousModels.chat_models, video:previousModels.video_models, audio:previousModels.audio_models, modelNames:previousModels.model_names});
        return false;
    }
    const summary = renderPickerSelection(item, selection);
    const saved = await scheduleProviderAutosave({providerId:item.id, region:apiAutosaveRegion(item), immediate:true, sync:false});
    if(!saved){
        Object.assign(item, previousModels);
        renderPickerSelection(item, {image:previousModels.image_models, chat:previousModels.chat_models, video:previousModels.video_models, audio:previousModels.audio_models, modelNames:previousModels.model_names});
        return false;
    }
    setStatus(`${tr('api.autosaved')} · ${summary}`);
    return true;
}
async function applyModelPicker(){
    // 保留脚本调用兼容；实际勾选已在每次变化时自动保存。
    const item = provider(); if(!item) return;
    const previousModels = {
        image_models:[...(item.image_models || [])],
        chat_models:[...(item.chat_models || [])],
        video_models:[...(item.video_models || [])],
        audio_models:[...(item.audio_models || [])],
        model_names:{...((item.model_names && typeof item.model_names === 'object') ? item.model_names : {})}
    };
    const selection = applyPickerSelectionToProvider(item);
    if(selection.newlySelectedUnverified.length && !await StudioDialog.confirm(trf('api.rhEnableUnverifiedConfirm', {count:selection.newlySelectedUnverified.length}), {type:'warning'})){
        Object.assign(item, previousModels);
        renderPickerSelection(item, {image:previousModels.image_models, chat:previousModels.chat_models, video:previousModels.video_models, audio:previousModels.audio_models, modelNames:previousModels.model_names});
        return false;
    }
    const summary = renderPickerSelection(item, selection);
    const saved = await scheduleProviderAutosave({providerId:item.id, region:apiAutosaveRegion(item), immediate:true, sync:false});
    if(saved){
        closeModelPicker();
        setStatus(`${tr('api.autosaved')} · ${summary}`);
    } else {
        Object.assign(item, previousModels);
        renderPickerSelection(item, {image:previousModels.image_models, chat:previousModels.chat_models, video:previousModels.video_models, audio:previousModels.audio_models, modelNames:previousModels.model_names});
    }
}
async function saveKeyOnly(){
    const item = provider();
    if(!item) return;
    const key = keyInput.value.trim();
    if(!key){ await StudioDialog.alert(tr('api.enterKeyAlert') || '请输入 Key', {type:'warning'}); return; }
    if(item.id === 'agnes') item.enabled = true;
    item.api_key = key;
    const ok = await saveProviders();
    if(ok) keyInput.value = '';
}
async function clearKeyOnly(){
    const item = provider();
    if(!item) return;
    if(!item.has_key && !keyInput.value){ return; }
    if(!await StudioDialog.confirm(tr('api.confirmClearKey') || '确认清除当前 Key？', {type:'danger'})) return;
    const previousEnabled = item.enabled;
    const previousClearKey = item._clearKey;
    if(item.id === 'agnes') item.enabled = false;
    item._clearKey = true;
    const ok = await saveProviders();
    if(ok) keyInput.value = '';
    else {
        item.enabled = previousEnabled;
        item._clearKey = previousClearKey;
    }
}
const FIXED_PROTOCOL_PROVIDER_IDS = new Set(['modelscope', 'volcengine', 'runninghub', 'ai-money', 'agnes']);
function providerSupportsModelProtocol(item){
    return Boolean(item) && !FIXED_PROTOCOL_PROVIDER_IDS.has(item.id);
}
function modelProtocolSelectHtml(kind, index, model, item){
    if(kind === 'video' || !providerSupportsModelProtocol(item)) return '';
    const map = (item.model_protocols && typeof item.model_protocols === 'object') ? item.model_protocols : {};
    const current = String(map[String(model || '').trim()] || '').toLowerCase();
    const opt = (val, label) => `<option value="${val}" ${current === val ? 'selected' : ''}>${label}</option>`;
    return `<select class="model-protocol-select" title="该模型使用的协议，默认跟随平台全局协议" onchange="updateModelProtocol('${kind}', ${index}, this.value)">
        <option value="" ${current === '' ? 'selected' : ''}>默认</option>
        ${opt('openai', 'OpenAI')}
        ${opt('gemini', 'Gemini')}
    </select>`;
}
function modelCapabilityStatus(item, kind, model){
    const nodeType = kind === 'image'
        ? 'image_generation'
        : kind === 'video'
        ? 'video_generation'
        : kind === 'audio'
        ? 'audio_generation'
        : kind === 'music'
        ? 'music_generation'
        : 'text_generation';
    const providerAliases = {jimeng:'jimeng-cli', codex:'codex-cli'};
    const itemId = String(item?.id || '').trim().toLowerCase();
    const protocol = String(item?.protocol || '').trim().toLowerCase();
    const acceptedIds = new Set([itemId, protocol, providerAliases[itemId], providerAliases[protocol]].filter(Boolean));
    const capabilityProvider = (modelCapabilityCatalog.providers || []).find(entry => {
        const ids = [entry?.id, entry?.capability_provider_id].map(value => String(value || '').trim().toLowerCase());
        return ids.some(id => acceptedIds.has(id));
    });
    const capability = (capabilityProvider?.models || []).find(entry =>
        String(entry?.model_id || '').trim() === String(model || '').trim()
        && entry?.node_type === nodeType
    );
    const readiness = capability?.runnable
        ? 'ready'
        : capability?.readiness === 'adapter_missing'
        ? 'adapter_missing'
        : 'needs_profile';
    const textKey = readiness === 'ready'
        ? 'api.modelReady'
        : readiness === 'adapter_missing'
        ? 'api.modelAdapterMissing'
        : 'api.modelNeedsProfile';
    const titleKey = readiness === 'ready'
        ? 'api.modelReadyHint'
        : readiness === 'adapter_missing'
        ? 'api.modelAdapterMissingHint'
        : 'api.modelNeedsProfileHint';
    return {readiness, label:tr(textKey), title:tr(titleKey)};
}
function renderModels(kind){
    const item = provider();
    const list = kind === 'image' ? imageModelList : kind === 'video' ? videoModelList : kind === 'audio' ? audioModelList : kind === 'music' ? musicModelList : chatModelList;
    if(!list) return;
    const models = modelListForKind(item, kind);
    if(!models.length){
        list.innerHTML = `<div class="empty">${tr('api.noModels')}</div>`;
        return;
    }
    const showProtocol = kind !== 'video' && providerSupportsModelProtocol(item);
    list.innerHTML = models.map((model, index) => {
        const label = modelDisplayName(model, item);
        const regionBadge = isRunningHubLike(item)
            ? `<span class="model-region-badge">${escapeHtml(runningHubRegionBadge(currentRunningHubRegion(item)))}</span>`
            : '';
        const capabilityStatus = modelCapabilityStatus(item, kind, model);
        const preflightButton = capabilityStatus.readiness === 'ready' && String(model || '').trim()
            ? `<button class="model-preflight-btn" type="button" onclick="preflightModel('${kind}', ${index})" title="${escapeAttr(tr('api.preflightModelHint'))}"><i data-lucide="shield-check" class="w-3.5 h-3.5"></i><span>${escapeHtml(tr('api.preflightModel'))}</span></button>`
            : '';
        return `
            <div class="model-row${showProtocol ? ' has-protocol' : ''}${preflightButton ? ' has-preflight' : ''}">
                <div class="model-id-field">
                    <div class="model-meta-line">
                        ${label && label !== model ? `<div class="model-display-name">${escapeHtml(label)}</div>` : '<span></span>'}
                        ${regionBadge}
                        <span class="model-capability-status is-${escapeAttr(capabilityStatus.readiness)}" title="${escapeAttr(capabilityStatus.title)}">${escapeHtml(capabilityStatus.label)}</span>
                    </div>
                    <input value="${escapeAttr(model)}" oninput="updateModel('${kind}', ${index}, this.value)">
                </div>
                ${modelProtocolSelectHtml(kind, index, model, item)}
                ${preflightButton}
                <button class="icon-btn" type="button" onclick="removeModel('${kind}', ${index})" title="${escapeAttr(tr('common.delete'))}"><i data-lucide="trash-2" class="w-4 h-4"></i></button>
            </div>
        `;
    }).join('');
    refreshIcons();
}
async function preflightModel(kind, index){
    const item = provider();
    if(!item) return;
    const model = String(modelListForKind(item, kind)[index] || '').trim();
    if(!model) return;
    const nodeType = kind === 'image'
        ? 'image_generation'
        : kind === 'video'
        ? 'video_generation'
        : kind === 'audio'
        ? 'audio_generation'
        : kind === 'music'
        ? 'music_generation'
        : 'text_generation';
    const providerId = String(item.id || '').trim();
    setStatus(`${tr('api.preflightRunning')} · ${model}`);
    try {
        const result = await fetch('/api/canvas-preflight', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({
                provider_id:providerId,
                model_id:model,
                node_type:nodeType,
                inputs:{prompt:'本地预检'},
                input_counts:{text:1},
                input_roles:{prompt:1},
                parameters:{},
                nodes:[],
                connections:[]
            })
        }).then(response => readApiResponse(response, tr('api.preflightFailed')));
        if(result.network_requested !== false) throw new Error(tr('api.preflightNetworkRejected'));
        const standard = result.standard_request || {};
        const resolved = standard.model_id && standard.model_id !== model ? ` · ${standard.model_id}` : '';
        setStatus(`${tr('api.preflightPassed')} · ${item.name || providerId} · ${standard.variant_id || standard.operation || model}${resolved} · network_requested=false`);
    } catch(error){
        setStatus(`${tr('api.preflightFailed')} · ${error?.message || error}`);
    }
}
function msLoraTargetOptions(selected){
    const item = provider();
    const models = unique([selected, ...MS_BUILTIN_IMAGE_MODELS, ...((item?.image_models) || [])]);
    return models.filter(Boolean).map(model => `<option value="${escapeAttr(model)}" ${model === selected ? 'selected' : ''}>${escapeHtml(model)}</option>`).join('');
}
function normalizeLoraStrength(value){
    const n = Number(value);
    if(!Number.isFinite(n)) return 0.8;
    return Math.max(0, Math.min(2, n));
}
function renderMsLoras(){
    const item = provider();
    if(!msLoraList || !item || item.id !== 'modelscope') return;
    item.ms_loras = Array.isArray(item.ms_loras) ? item.ms_loras : [];
    if(!item.ms_loras.length){
        msLoraList.innerHTML = `<div class="lora-empty">${tr('api.loraEmpty')}</div>`;
        return;
    }
    msLoraList.innerHTML = item.ms_loras.map((lora, index) => {
        const target = lora.target_model || lora.model || MS_BUILTIN_IMAGE_MODELS[0];
        const strength = normalizeLoraStrength(lora.strength ?? lora.default_strength ?? 0.8);
        return `
            <div class="lora-row">
                <label class="lora-field">
                    <span>${tr('api.loraId')}</span>
                    <input value="${escapeAttr(lora.id || '')}" placeholder="${escapeAttr(tr('api.loraIdPlaceholder'))}" oninput="updateMsLora(${index}, 'id', this.value)">
                </label>
                <label class="lora-field">
                    <span>${tr('api.loraTargetModel')}</span>
                    <select onchange="updateMsLora(${index}, 'target_model', this.value)">${msLoraTargetOptions(target)}</select>
                </label>
                <label class="lora-field">
                    <span>${tr('api.loraDefaultStrength')}</span>
                    <input type="number" min="0" max="2" step="0.05" value="${strength}" oninput="updateMsLora(${index}, 'strength', this.value)">
                </label>
                <button class="icon-btn" type="button" onclick="removeMsLora(${index})" title="${escapeAttr(tr('common.delete'))}"><i data-lucide="trash-2" class="w-4 h-4"></i></button>
            </div>
        `;
    }).join('');
    refreshIcons();
}
function addMsLora(){
    const item = provider();
    if(!item || item.id !== 'modelscope') return;
    item.ms_loras = Array.isArray(item.ms_loras) ? item.ms_loras : [];
    item.ms_loras.push({
        id:'',
        name:'',
        target_model: (item.image_models || [])[0] || MS_BUILTIN_IMAGE_MODELS[0],
        strength:0.8,
        enabled:true,
        note:''
    });
    renderMsLoras();
    void scheduleProviderAutosave({providerId:item.id, immediate:true, sync:false});
}
function updateMsLora(index, field, value){
    const item = provider();
    if(!item || item.id !== 'modelscope') return;
    item.ms_loras = Array.isArray(item.ms_loras) ? item.ms_loras : [];
    const lora = item.ms_loras[index];
    if(!lora) return;
    if(field === 'strength') lora.strength = normalizeLoraStrength(value);
    else lora[field] = value;
    void scheduleProviderAutosave({providerId:item.id, immediate:false, sync:false});
}
function removeMsLora(index){
    const item = provider();
    if(!item || item.id !== 'modelscope') return;
    item.ms_loras = Array.isArray(item.ms_loras) ? item.ms_loras : [];
    item.ms_loras.splice(index, 1);
    renderMsLoras();
    void scheduleProviderAutosave({providerId:item.id, immediate:true, sync:false});
}
function selectProvider(id){
    closeHypitSettingsForApiNavigation();
    if(comfyuiSettingsMode) closeComfyUiSettings();
    if(isProviderTemporarilyHidden(providers.find(item => item.id === id))) return;
    void captureApiObjectBeforeNavigation({immediate:true});
    apiSettingsSection = 'connections';
    recommendInlineOpen = false;
    syncRecommendView();
    renderRecommendApi();
    clearFetchedModelState();
    selectedId = id;
    syncApiSettingsView();
    renderEditor();
}
function addProvider(){
    closeHypitSettingsForApiNavigation();
    void captureApiObjectBeforeNavigation({immediate:true});
    apiSettingsSection = 'connections';
    recommendInlineOpen = false;
    syncRecommendView();
    renderRecommendApi();
    syncEditor();
    let id = 'custom-api';
    let index = 2;
    while(providers.some(item => item.id === id)) id = `custom-api-${index++}`;
    providers.push({id, name:'API', base_url:'', protocol:'openai', image_request_mode:'openai', image_edit_route:'general', image_generation_endpoint:'', image_edit_endpoint:'', enabled:true, primary:false, image_models:[], chat_models:[], video_models:[], audio_models:[], has_key:false, key_preview:''});
    clearFetchedModelState();
    selectedId = id;
    renderEditor();
}
async function addCliProvider(kind){
    const preset = CLI_PROVIDER_PRESETS[kind];
    if(!preset) return;
    closeHypitSettingsForApiNavigation();
    void captureApiObjectBeforeNavigation({immediate:true});
    recommendInlineOpen = false;
    syncRecommendView();
    renderRecommendApi();
    syncEditor();
    const previousProviders = JSON.parse(JSON.stringify(providers));
    const previousSelectedId = selectedId;
    let item = providers.find(provider => provider.id === preset.id);
    if(!item) item = providers.find(provider => String(provider.protocol || '').toLowerCase() === preset.protocol);
    let created = false;
    if(!item){
        created = true;
        item = {
            id:preset.id,
            name:preset.name,
            base_url:'',
            protocol:preset.protocol,
            image_request_mode:'openai',
            image_edit_route:'general',
            image_generation_endpoint:'',
            image_edit_endpoint:'',
            enabled:true,
            primary:false,
            image_models:[],
            chat_models:[],
            video_models:[],
            audio_models:[],
            model_protocols:{},
            has_key:false,
            key_preview:''
        };
        providers.push(item);
    }
    item.id = preset.id;
    item.name = item.name || preset.name;
    item.base_url = '';
    item.protocol = preset.protocol;
    applyCliProtocolDefaults(item, preset.protocol, created);
    clearFetchedModelState();
    selectedId = item.id;
    renderProviderList();
    renderEditor();
    if(protocolInput) protocolInput.value = preset.protocol;
    const ok = await saveProviders();
    if(ok){
        selectedId = item.id;
        renderEditor();
        if(protocolInput) protocolInput.value = preset.protocol;
        setStatus(`${preset.name} 已添加，使用本机登录态，无需填写 API Key。`);
    } else {
        providers = previousProviders;
        selectedId = previousSelectedId;
        renderProviderList();
        renderEditor();
    }
}
async function deleteProvider(){
    const item = provider();
    if(!item) return;
    if(isFixedProvider(item)){ await StudioDialog.alert(tr('api.defaultNoDelete') || '默认平台不能删除', {type:'warning'}); return; }
    if(providers.length <= 1){ await StudioDialog.alert(tr('api.keepOne'), {type:'warning'}); return; }
    if(!await StudioDialog.confirm(`确认删除平台「${item.name || item.id}」？`, {type:'danger'})) return;
    syncEditor();
    (item.id === 'runninghub' ? ['cn','global'] : [apiAutosaveRegion(item)])
        .forEach(region => discardProviderAutosave(item.id, region));
    const previousProviders = providers;
    const previousSelectedId = selectedId;
    providers = providers.filter(p => p.id !== item.id);
    clearFetchedModelState();
    selectedId = providers[0]?.id || '';
    renderProviderList();
    renderEditor();
    if(!await saveProviders()){
        providers = previousProviders;
        selectedId = previousSelectedId;
        renderProviderList();
        renderEditor();
    }
}
async function clearRhKeyOnly(kind, region=''){
    const item = provider();
    if(!item || item.id !== 'runninghub') return;
    if(!await StudioDialog.confirm(tr('api.confirmClearKey') || '确认清除当前 Key？', {type:'danger'})) return;
    const targetRegion = RUNNINGHUB_REGIONS[region] ? region : runningHubRegionFromItem(item);
    const input = runningHubRegionInput(targetRegion, kind);
    const previousApiClears = [...(item._clearRhApiKeys || [])];
    const previousWalletClears = [...(item._clearRhWalletKeys || [])];
    if(kind === 'wallet') item._clearRhWalletKeys = [...new Set([...(item._clearRhWalletKeys || []), targetRegion])];
    else item._clearRhApiKeys = [...new Set([...(item._clearRhApiKeys || []), targetRegion])];
    const ok = await saveProviders();
    if(ok){
        if(input) input.value = '';
    } else {
        item._clearRhApiKeys = previousApiClears;
        item._clearRhWalletKeys = previousWalletClears;
    }
}
async function saveVolcengineAssetKeys(){
    const item = provider();
    if(!item || item.id !== 'volcengine') return;
    const ak = volcAkInput?.value.trim() || '';
    const sk = volcSkInput?.value.trim() || '';
    if(!ak && !sk){ await StudioDialog.alert('请输入火山素材库 AK 或 SK', {type:'warning'}); return; }
    syncEditor();
    const ok = await saveProviders();
    if(ok){
        if(volcAkInput) volcAkInput.value = '';
        if(volcSkInput) volcSkInput.value = '';
    }
}
async function clearVolcengineAssetKeys(){
    const item = provider();
    if(!item || item.id !== 'volcengine') return;
    if(!await StudioDialog.confirm('确认清除火山素材库 AK/SK？', {type:'danger'})) return;
    const previousAccessClear = item._clearVolcengineAccessKey;
    const previousSecretClear = item._clearVolcengineSecretKey;
    item._clearVolcengineAccessKey = true;
    item._clearVolcengineSecretKey = true;
    const ok = await saveProviders();
    if(ok){
        if(volcAkInput) volcAkInput.value = '';
        if(volcSkInput) volcSkInput.value = '';
    } else {
        item._clearVolcengineAccessKey = previousAccessClear;
        item._clearVolcengineSecretKey = previousSecretClear;
    }
}
function addModel(kind){
    const item = provider();
    const key = kind === 'image' ? 'image_models' : kind === 'video' ? 'video_models' : ['audio','music'].includes(kind) ? 'audio_models' : 'chat_models';
    item[key] = [...(item[key] || []), ''];
    renderModels(kind);
    if(kind === 'image') renderMsLoras();
    void scheduleProviderAutosave({providerId:item.id, immediate:true, sync:false});
}
function modelProtocolStillUsed(item, name){
    if(!item || !name) return false;
    const lists = ['image_models', 'chat_models', 'video_models', 'audio_models'];
    return lists.some(k => Array.isArray(item[k]) && item[k].includes(name));
}
function updateModel(kind, index, value){
    const item = provider();
    const key = kind === 'image' ? 'image_models' : kind === 'video' ? 'video_models' : ['audio','music'].includes(kind) ? 'audio_models' : 'chat_models';
    const storageIndex = modelStorageIndex(item, kind, index);
    if(storageIndex < 0) return;
    const oldName = String(item[key][storageIndex] || '').trim();
    const newName = String(value || '').trim();
    item[key][storageIndex] = value;
    // 重命名时迁移该模型的协议覆盖
    if(item.model_protocols && typeof item.model_protocols === 'object' && oldName && oldName !== newName){
        if(Object.prototype.hasOwnProperty.call(item.model_protocols, oldName)){
            const proto = item.model_protocols[oldName];
            // 旧名称在其他列表里不再使用时才删除旧键
            const stillUsedElsewhere = (() => {
                const lists = ['image_models', 'chat_models', 'video_models', 'audio_models'];
                return lists.some(k => Array.isArray(item[k]) && item[k].some((m, i) => !(k === key && i === storageIndex) && String(m || '').trim() === oldName));
            })();
            if(!stillUsedElsewhere) delete item.model_protocols[oldName];
            if(newName) item.model_protocols[newName] = proto;
        }
    }
    if(item.model_names && typeof item.model_names === 'object' && oldName && oldName !== newName){
        if(Object.prototype.hasOwnProperty.call(item.model_names, oldName)){
            const label = item.model_names[oldName];
            if(!modelProtocolStillUsed(item, oldName)) delete item.model_names[oldName];
            if(newName && label && label !== newName) item.model_names[newName] = label;
        }
    }
    if(kind === 'image') renderMsLoras();
    void scheduleProviderAutosave({providerId:item.id, immediate:false, sync:false});
}
function updateModelProtocol(kind, index, value){
    const item = provider();
    const key = kind === 'image' ? 'image_models' : kind === 'video' ? 'video_models' : ['audio','music'].includes(kind) ? 'audio_models' : 'chat_models';
    const storageIndex = modelStorageIndex(item, kind, index);
    const name = String(item[key]?.[storageIndex] || '').trim();
    if(!name) return;
    if(!item.model_protocols || typeof item.model_protocols !== 'object') item.model_protocols = {};
    const proto = String(value || '').trim().toLowerCase();
    if(proto === 'openai' || proto === 'gemini'){
        item.model_protocols[name] = proto;
    } else {
        delete item.model_protocols[name];
    }
    void scheduleProviderAutosave({providerId:item.id, immediate:true, sync:false});
}
function removeModel(kind, index){
    const item = provider();
    const key = kind === 'image' ? 'image_models' : kind === 'video' ? 'video_models' : ['audio','music'].includes(kind) ? 'audio_models' : 'chat_models';
    const storageIndex = modelStorageIndex(item, kind, index);
    if(storageIndex < 0) return;
    const removed = String(item[key][storageIndex] || '').trim();
    item[key].splice(storageIndex, 1);
    // 清理不再使用的协议覆盖
    if(removed && item.model_protocols && typeof item.model_protocols === 'object' && !modelProtocolStillUsed(item, removed)){
        delete item.model_protocols[removed];
    }
    if(removed && item.model_names && typeof item.model_names === 'object' && !modelProtocolStillUsed(item, removed)){
        delete item.model_names[removed];
    }
    renderModels(kind);
    if(kind === 'image') renderMsLoras();
    void scheduleProviderAutosave({providerId:item.id, immediate:true, sync:false});
}
async function loadProviders(){
    setStatus(tr('api.loading'));
    try {
        const capabilityRequest = fetch('/api/model-capabilities')
            .then(response => response.ok ? response.json() : null)
            .catch(() => null);
        const data = await fetch('/api/providers').then(r => readApiResponse(r, tr('api.loadFailed') || '加载平台失败'));
        providers = data.providers || [];
        const capabilityData = await capabilityRequest;
        if(capabilityData?.providers) modelCapabilityCatalog = capabilityData;
        clearFetchedModelState();
        selectedId = sortedProviders()[0]?.id || '';
        renderEditor();
        closeRecommendApi();
        setStatus('');
    } catch(err) {
        setStatus(tr('api.loadFailed'));
    }
}
async function saveProviders(draft=null){
    let saveDraft = draft;
    if(!saveDraft){
        syncEditor();
        const item = provider();
        if(!item) return false;
        const revision = ++apiAutosaveRevision;
        saveDraft = captureApiAutosaveDraft(item, apiAutosaveRegion(item), revision);
        clearProviderAutosaveTimer(saveDraft.objectId);
        apiAutosavePendingByKey.delete(saveDraft.objectId);
        const write = apiAutosaveSerial.then(() => saveProviders(saveDraft));
        apiAutosaveSerial = write.catch(() => false);
        return write;
    }
    // 每个请求包含完整配置；较早的防抖任务不能回写覆盖较新的即时修改。
    if(saveDraft.revision < apiAutosaveLastWriteRevision) return true;
    apiAutosaveLastWriteRevision = saveDraft.revision;
    const requestProviders = cloneApiSettingsValue(saveDraft.providers || providers) || [];
    requestProviders.forEach(item => {
        item.id = normalizeId(item.id);
        applyLockedRecommendedProtocol(item);
        item.protocol = item.id === 'runninghub'
            ? 'runninghub'
            : item.id === 'volcengine'
            ? 'volcengine'
            : item.id === 'ai-money'
            ? 'openai'
            : API_PROTOCOLS.includes(String(item.protocol || '').toLowerCase()) ? String(item.protocol).toLowerCase() : 'openai';
        const isCliProtocol = CLI_PROTOCOLS.has(item.protocol);
        item.image_request_mode = normalizeImageRequestMode(
            item.id === 'modelscope' || item.id === 'runninghub' || item.id === 'volcengine' || item.id === 'ai-money' || isCliProtocol
                ? 'openai'
                : item.image_request_mode
        );
        item.image_edit_route = normalizeImageEditRoute(
            item.id === 'modelscope' || item.id === 'runninghub' || item.id === 'volcengine' || item.id === 'ai-money' || isCliProtocol
                ? 'general'
                : item.image_edit_route
        );
        if(isCliProtocol) applyCliProtocolDefaults(item, item.protocol, false);
        if(item.id === 'runninghub'){
            item.base_url = normalizeRunningHubBaseUrl(item.base_url);
            ensureRunningHubRegions(item);
            syncRunningHubProviderEnabled(item);
            activateRunningHubRegion(item, runningHubRegionFromItem(item));
            item.image_models = unique(item.image_models || []);
            item.chat_models = unique(item.chat_models || []);
            item.video_models = unique(item.video_models || []);
            item.audio_models = unique(item.audio_models || []);
        }
        if(item.id === 'ai-money'){
            item.name = 'laohu';
            item.base_url = AI_MONEY_DEFAULT_BASE_URL;
            item.protocol = 'openai';
        }
        if(item.id === 'agnes'){
            item.name = 'Agnes AI';
            item.base_url = AGNES_DEFAULT_BASE_URL;
            item.protocol = 'openai';
            item.image_request_mode = 'openai-json';
        }
        item.image_generation_endpoint = '';
        item.image_edit_endpoint = '';
        item.image_models = unique(item.image_models || []);
        item.chat_models = unique(item.chat_models || []);
        item.video_models = unique(item.video_models || []);
        item.audio_models = unique(item.audio_models || []);
        const modelNameSource = (item.model_names && typeof item.model_names === 'object') ? item.model_names : {};
        const modelNameMap = {};
        [...item.image_models, ...item.chat_models, ...item.video_models, ...item.audio_models].forEach(model => {
            const raw = String(model || '').trim();
            const label = String(modelNameSource[raw] || modelDisplayName(raw, item) || '').trim();
            if(raw && label && label !== raw) modelNameMap[raw] = label;
        });
        item.model_names = modelNameMap;
        item.rh_apps = normalizeRhEntries(item.rh_apps || [], 'app');
        item.rh_workflows = normalizeRhEntries(item.rh_workflows || [], 'workflow');
        item.ms_loras = (Array.isArray(item.ms_loras) ? item.ms_loras : []).map(lora => ({
            id:String(lora.id || '').trim(),
            name:String(lora.name || lora.id || '').trim(),
            target_model:String(lora.target_model || '').trim(),
            strength:normalizeLoraStrength(lora.strength ?? 0.8),
            enabled:lora.enabled !== false,
            note:String(lora.note || '').trim()
        })).filter(lora => lora.id && lora.target_model);
        if(item.id === 'runninghub') persistActiveRunningHubRegion(item);
    });
    if(new Set(requestProviders.map(item => item.id)).size !== requestProviders.length){
        await StudioDialog.alert(tr('api.duplicateId'), {type:'warning'});
        if(draft) apiAutosaveDirtyObjects.delete(saveDraft.objectId);
        return false;
    }
    const isLatestDraft = () => saveDraft.revision === apiAutosaveRevision
        && saveDraft.objectRevision === apiAutosaveObjectRevision.get(saveDraft.objectId);
    setStatus(draft ? (tr('api.autosaving') || tr('api.saving')) : tr('api.saving'));
    try {
        const res = await fetch('/api/providers', {
            method:'PUT',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify(requestProviders.map(item => ({
                id:item.id,
                name:item.name,
                base_url:item.base_url,
                protocol:(item.id === 'modelscope' || item.id === 'ai-money') ? 'openai' : item.id === 'runninghub' ? 'runninghub' : item.id === 'volcengine' ? 'volcengine' : (item.protocol || 'openai'),
                image_request_mode:item.image_request_mode || 'openai',
                image_edit_route:item.image_edit_route || 'general',
                image_generation_endpoint:item.image_generation_endpoint || '',
                image_edit_endpoint:item.image_edit_endpoint || '',
                enabled:item.id === 'runninghub' ? runningHubHasEnabledRegion(item) : item.enabled !== false,
                primary:false,
                image_models:item.image_models || [],
                chat_models:item.chat_models || [],
                video_models:item.video_models || [],
                audio_models:item.audio_models || [],
                model_names:(item.model_names && typeof item.model_names === 'object') ? item.model_names : {},
                model_protocols:(item.model_protocols && typeof item.model_protocols === 'object') ? item.model_protocols : {},
                ms_loras:item.id === 'modelscope' ? (item.ms_loras || []) : [],
                ms_defaults_version:item.id === 'modelscope' ? (item.ms_defaults_version || 1) : 0,
                rh_apps:item.id === 'runninghub' ? (item.rh_apps || []) : [],
                rh_workflows:item.id === 'runninghub' ? (item.rh_workflows || []) : [],
                rh_region:item.id === 'runninghub' ? runningHubRegionFromItem(item) : '',
                rh_regions:item.id === 'runninghub' ? (item.rh_regions || {}) : {},
                volcengine_project_name:item.id === 'volcengine' ? (item.volcengine_project_name || VOLCENGINE_DEFAULT_PROJECT_NAME) : '',
                volcengine_region:item.id === 'volcengine' ? (item.volcengine_region || VOLCENGINE_DEFAULT_REGION) : '',
                volcengine_access_key_id:item.volcengine_access_key_id || undefined,
                volcengine_secret_access_key:item.volcengine_secret_access_key || undefined,
                api_key:item.api_key || undefined,
                wallet_api_key:item.wallet_api_key || undefined,
                rh_api_keys:item.id === 'runninghub' ? (item._pendingRhApiKey || {}) : {},
                rh_wallet_api_keys:item.id === 'runninghub' ? (item._pendingRhWalletKey || {}) : {},
                clear_rh_api_keys:item.id === 'runninghub' ? (item._clearRhApiKeys || []) : [],
                clear_rh_wallet_api_keys:item.id === 'runninghub' ? (item._clearRhWalletKeys || []) : [],
                clear_key:item._clearKey === true,
                clear_wallet_key:item._clearWalletKey === true,
                clear_volcengine_access_key_id:item._clearVolcengineAccessKey === true,
                clear_volcengine_secret_access_key:item._clearVolcengineSecretKey === true
            })))
        });
        const data = await readApiResponse(res, tr('api.saveFailed'));
        if(isLatestDraft()){
            apiAutosaveDirtyObjects.clear();
            apiAutosavePendingByKey.forEach((_, key) => clearProviderAutosaveTimer(key));
            apiAutosavePendingByKey.clear();
            providers = data.providers || providers;
            providers.forEach(item => {
                delete item.api_key;
                delete item.wallet_api_key;
                delete item.volcengine_access_key_id;
                delete item.volcengine_secret_access_key;
                delete item._clearKey;
                delete item._clearWalletKey;
                delete item._pendingRhApiKey;
                delete item._pendingRhWalletKey;
                delete item._clearRhApiKeys;
                delete item._clearRhWalletKeys;
                delete item._clearVolcengineAccessKey;
                delete item._clearVolcengineSecretKey;
            });
            selectedId = provider()?.id || providers[0]?.id || '';
            renderEditor();
            setStatus(draft ? (tr('api.autosaved') || tr('api.saved')) : tr('api.saved'));
            // 广播变更，画布等其他 iframe 立即重新拉取最新平台/模型列表
            broadcastStudioApiChange('providers-changed');
        }
        return true;
    } catch(err) {
        if(isLatestDraft()){
            apiAutosaveDirtyObjects.add(saveDraft.objectId);
            apiAutosavePendingByKey.set(saveDraft.objectId, saveDraft);
            setStatus(draft ? (tr('api.autosaveFailed') || tr('api.saveFailed')) : (err.message || tr('api.saveFailed')));
        }
        return false;
    }
}
function escapeHtml(str){
    return String(str || '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
}
function escapeAttr(str){ return escapeHtml(str).replace(/`/g, '&#96;'); }
window.addEventListener('message', event => {
    if(event.data?.type === 'studio-theme' && window.StudioTheme) window.StudioTheme.set(event.data.theme);
    if(event.data?.type === 'studio-lang' && window.StudioI18n) {
        window.StudioI18n.set(event.data.lang);
        if(recommendInlineOpen) renderRecommendApi();
        else renderEditor();
    }
});
rhWorkflowEditorOverlay?.addEventListener('mousedown', event => {
    if(event.target === rhWorkflowEditorOverlay) closeRhWorkflowEditor();
});
document.addEventListener('keydown', event => {
    if(event.key === 'Escape' && rhWorkflowEditorState.open) closeRhWorkflowEditor();
});
document.addEventListener('mousedown', event => {
    if(!rhWorkflowEditorState.open) return;
    const pop = document.getElementById('rhNodePopover');
    if(!pop) return;
    if(pop.contains(event.target)) return;
    if(event.target.closest('.rh-editor-gnode,.rh-app-field-card')) return;
    closeRhNodePopover();
});
recommendApiOverlay?.addEventListener('mousedown', event => {
    if(event.target === recommendApiOverlay) closeRecommendApi();
});
document.querySelectorAll('.picker-overlay').forEach(overlay => {
    overlay.addEventListener('mousedown', event => {
        if(event.target !== overlay) return;
        if(overlay.id === 'modelPickerOverlay') closeModelPicker();
        if(overlay.id === 'jimengHelpOverlay') closeJimengHelp();
        if(overlay.id === 'codexHelpOverlay') closeCodexHelp();
        if(overlay.id === 'geminiCliHelpOverlay') closeGeminiCliHelp();
    });
});
document.addEventListener('keydown', event => {
    if(event.key !== 'Escape') return;
    if(fetchModelsController){ fetchModelsController.abort(); return; }
    const modelPicker = document.getElementById('modelPickerOverlay');
    if(modelPicker && getComputedStyle(modelPicker).display !== 'none') closeModelPicker();
    if(recommendApiOverlay && getComputedStyle(recommendApiOverlay).display !== 'none') closeRecommendApi();
});
window.addEventListener('studio-lang-change', () => {
    document.title = tr('api.title');
    syncRecommendView();
    if(recommendInlineOpen) renderRecommendApi();
    else renderEditor();
});
window.onload = () => {
    if(window.StudioTheme) window.StudioTheme.apply();
    if(window.StudioI18n) window.StudioI18n.apply();
    document.title = tr('api.title');
    syncRecommendView();
    loadProviders();
    // 平台名输入时实时预览生成的 ID
    if(nameInput) nameInput.addEventListener('input', () => {
        updateIdPreview();
        void scheduleCurrentProviderAutosave(false);
    });
    if(protocolInput) protocolInput.addEventListener('change', updateProtocolFromInput);
    if(baseInput) baseInput.addEventListener('input', () => {
        syncRunningHubRegion();
        updateApimartDomesticHint();
        void scheduleCurrentProviderAutosave(false);
    });
    Object.keys(RUNNINGHUB_REGIONS).forEach(region => {
        ['free', 'wallet'].forEach(kind => {
            const input = runningHubRegionInput(region, kind);
            if(input) input.addEventListener('input', event => {
                updateRunningHubKeyInput(region, kind, event?.target?.value ?? input.value);
            });
        });
    });
    if(imageRequestModeInput) imageRequestModeInput.addEventListener('change', () => {
        const item = provider();
        if(!item) return;
        if(applyLockedRecommendedProtocol(item)){
            if(protocolInput) protocolInput.value = item.protocol;
            imageRequestModeInput.value = item.image_request_mode;
            return;
        }
        item.image_request_mode = normalizeImageRequestMode(imageRequestModeInput.value);
        void scheduleCurrentProviderAutosave(true);
    });
    if(imageEditRouteInput) imageEditRouteInput.addEventListener('change', () => {
        const item = provider();
        if(!item) return;
        item.image_edit_route = normalizeImageEditRoute(imageEditRouteInput.value);
        void scheduleCurrentProviderAutosave(true);
    });
    [keyInput].forEach(input => {
        if(input) input.addEventListener('input', () => {
            refreshProviderOnboarding();
            if(input === keyInput) updateApimartDomesticHint();
            void scheduleCurrentProviderAutosave(false);
        });
    });
    [volcAkInput, volcSkInput, volcProjectInput, volcRegionInput].forEach(input => {
        if(input) input.addEventListener('input', () => void scheduleCurrentProviderAutosave(false));
    });
};
