const root = document.getElementById('assetManagerRoot');
const statusEl = document.getElementById('assetStatus');
const refreshBtn = document.getElementById('refreshBtn');
const uploadInput = document.getElementById('assetUploadInput');

const LOCAL_CAPTION_SETTINGS_KEY = 'asset_manager_local_caption_settings_v1';
const PROMPT_UNCATEGORIZED_CATEGORY_ID = 'uncategorized';
const PROMPT_UNCATEGORIZED_CATEGORY_NAME = '未分类';
const PROMPT_LIBRARY_UPDATED_KEY = 'prompt_library_updated_at';
function notifyPromptLibraryUpdated(){
    try { localStorage.setItem(PROMPT_LIBRARY_UPDATED_KEY, String(Date.now())); } catch(_) {}
}
function siteTextInput({title='请输入内容', value='', placeholder='', confirmLabel='保存'}={}){
    return new Promise(resolve => {
        const backdrop = document.createElement('div');
        backdrop.className = 'asset-input-dialog-backdrop';
        backdrop.innerHTML = `<form class="asset-input-dialog" role="dialog" aria-modal="true" aria-label="${escapeAttr(title)}">
            <div class="asset-input-dialog-head"><strong>${escapeHtml(title)}</strong><button type="button" data-site-input-cancel title="取消"><i data-lucide="x"></i></button></div>
            <input data-site-input-value type="text" value="${escapeAttr(value)}" placeholder="${escapeAttr(placeholder)}" autocomplete="off">
            <div class="asset-input-dialog-actions"><button type="button" data-site-input-cancel>取消</button><button type="submit" class="primary">${escapeHtml(confirmLabel)}</button></div>
        </form>`;
        document.body.appendChild(backdrop);
        refreshIcons();
        const input = backdrop.querySelector('[data-site-input-value]');
        let settled = false;
        const finish = result => {
            if(settled) return;
            settled = true;
            backdrop.remove();
            resolve(result);
        };
        backdrop.addEventListener('pointerdown', event => {
            if(event.target === backdrop) finish('');
        });
        backdrop.addEventListener('click', event => {
            if(event.target.closest('[data-site-input-cancel]')) finish('');
        });
        backdrop.querySelector('form').addEventListener('submit', event => {
            event.preventDefault();
            finish(String(input?.value || '').trim());
        });
        backdrop.addEventListener('keydown', event => {
            if(event.key === 'Escape'){ event.preventDefault(); finish(''); }
        });
        requestAnimationFrame(() => { input?.focus(); input?.select(); });
    });
}
function readLocalCaptionSettings(){
    try {
        const data = JSON.parse(localStorage.getItem(LOCAL_CAPTION_SETTINGS_KEY) || '{}');
        return data && typeof data === 'object' ? data : {};
    } catch(_) {
        return {};
    }
}
function writeLocalCaptionSettings(){
    try {
        localStorage.setItem(LOCAL_CAPTION_SETTINGS_KEY, JSON.stringify({
            provider:localCaptionProvider || '',
            model:localCaptionModel || '',
            captionPrompt:localCaptionPrompt || '描述图片',
        }));
    } catch(_) {}
}
const savedLocalCaptionSettings = readLocalCaptionSettings();

let activeTab = 'assets';
let activeInputScope = 'asset';
let assetLibrary = {libraries:[], categories:[]};
let promptLibrary = {libraries:[]};
let apiProviders = [];
let activeAssetLibraryId = '';
let activeAssetCategoryId = '';
let activeWorkflowLibraryId = '';
let activeWorkflowCategoryId = '';
let activePromptLibraryId = '';
let activePromptCategory = 'all';
let assetTreeFocus = 'category';
let promptTreeFocus = 'category';
let selectedAssetId = '';
let selectedWorkflowId = '';
let selectedPromptId = '';
let selectedAssetIds = new Set();
let selectedWorkflowIds = new Set();
let selectedPromptIds = new Set();
let assetQuery = '';
let workflowQuery = '';
let promptQuery = '';
let assetManageMode = false;
let workflowManageMode = false;
let promptManageMode = false;
let assetMoveTarget = '';
let assetClipboard = null;
let managedSelectionPointerGuard = null;
let assetEditMode = false;
let promptEditMode = false;
let promptCreateMode = false;
let pendingDeleteAssetId = '';
let pendingDeletePromptId = '';
let pendingBatchDelete = '';
let assetTreeEdit = null;
let workflowTreeEdit = null;
let promptTreeEdit = null;
let pendingTreeDelete = '';
let marqueeState = null;
let sharedFolders = [];
let activeSharedFolderId = '';
let activeSharedFolderName = '';
let localFolders = [];
let localFolderMap = new Map();
let localItemMap = new Map();
let activeLocalFolderId = '';
let selectedLocalId = '';
let selectedLocalIds = new Set();
let localQuery = '';
let localManageMode = false;
let localClipboard = null;
let localCaptionBusy = false;
let localCaptionProvider = savedLocalCaptionSettings.provider || '';
let localCaptionModel = savedLocalCaptionSettings.model || '';
let localCaptionPrompt = savedLocalCaptionSettings.captionPrompt || '描述图片';
let localAssets = [];
let localAssetsLoaded = false;
let localUploadTree = null;
let activeLocalUploadFolder = '';
let selectedLocalUploadId = '';
let selectedLocalUploadIds = new Set();
let localUploadQuery = '';
let localUploadManageMode = false;
let localUploadClipboard = null;
let lightboxPanState = null;
let canvasAssetsData = {counts:{all:0,image:0,video:0,audio:0,text:0}, items:[]};
let activeCanvasAssetCategory = 'all';
let activeCanvasAssetCanvasId = '';
let selectedCanvasAssetId = '';
let selectedCanvasAssetIds = new Set();
let canvasAssetQuery = '';
let canvasAssetSort = 'updated_desc';
let canvasAssetManageMode = false;
let searchCompositionActive = false;
let searchRenderTimer = null;
let lastSearchCompositionEndAt = 0;

const LOCAL_MEDIA_EXTS = /\.(png|jpe?g|webp|gif|bmp|avif|svg|mp4|webm|mov|m4v|mp3|wav|flac|ogg|m4a|aac)(\?|#|$)/i;
const SEARCH_INPUT_IDS = new Set(['assetSearch','workflowSearch','promptSearch','localSearch','localUploadSearch','canvasAssetSearch']);

function refreshIcons(){
    if(window.lucide) lucide.createIcons();
    window.StudioMedia?.bindVideoPosters(root);
    window.StudioI18n?.apply?.(root);
}
function i18nText(key, fallback){ return window.StudioI18n?.t?.(key) || fallback; }
function setStatus(text='准备就绪'){ if(statusEl) statusEl.textContent = text || '准备就绪'; }
function escapeHtml(value=''){
    return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function escapeAttr(value=''){ return escapeHtml(value); }
async function copyTextToClipboard(text){
    const value = String(text || '');
    if(!value) return false;
    try {
        if(navigator.clipboard?.writeText){ await navigator.clipboard.writeText(value); return true; }
    } catch(_) {}
    try {
        const ta = document.createElement('textarea');
        ta.value = value;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        ta.style.top = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        const ok = document.execCommand('copy');
        ta.remove();
        return ok;
    } catch(_) { return false; }
}
async function apiJson(url, options={}){
    const res = await fetch(url, options);
    const data = await res.json().catch(() => ({}));
    if(!res.ok) throw new Error(data.detail || data.message || '操作失败');
    return data;
}
const STORAGE_KIND_LABELS = {upload:'上传素材', generated:'生成素材', local:'本地素材'};
function formatDate(value){
    const num = Number(value || 0);
    if(!num) return '未知';
    try { return new Date(num).toLocaleString('zh-CN', {hour12:false}); }
    catch(e) { return '未知'; }
}
function formatFileSize(bytes=0){
    const size = Number(bytes || 0);
    if(!size) return '0 B';
    const units = ['B','KB','MB','GB','TB'];
    const idx = Math.min(units.length - 1, Math.floor(Math.log(size) / Math.log(1024)));
    return `${(size / Math.pow(1024, idx)).toFixed(idx ? 1 : 0)} ${units[idx]}`;
}
function assetLibraries(){
    return Array.isArray(assetLibrary.libraries) && assetLibrary.libraries.length
        ? assetLibrary.libraries
        : [{id:'default', name:'默认资产库', categories:assetLibrary.categories || []}];
}
function activeAssetLibrary(){
    const libs = assetLibraries();
    return libs.find(lib => lib.id === activeAssetLibraryId) || libs[0] || null;
}
function activeWorkflowLibrary(){
    const libs = assetLibraries();
    return libs.find(lib => lib.id === activeWorkflowLibraryId) || libs[0] || null;
}
function assetCategories(){
    return (activeAssetLibrary()?.categories || []).filter(cat => (cat.type || 'image') === 'image');
}
function workflowCategories(){
    const cats = [];
    assetLibraries().forEach(lib => {
        (lib.categories || []).filter(cat => (cat.type || '') === 'workflow').forEach(cat => {
            cats.push({...cat, __libraryId:lib.id, __libraryName:lib.name || '资产库'});
        });
    });
    return cats;
}
function activeAssetCategory(){
    const cats = assetCategories();
    return cats.find(cat => cat.id === activeAssetCategoryId) || cats[0] || null;
}
function assetViewTitle(){
    return activeAssetCategory()?.name || '资产素材';
}
function assetViewSubtitle(items){
    const libName = activeAssetLibrary()?.name || '资产库';
    return `${libName} / ${items.length} 个素材`;
}
function activeWorkflowCategory(){
    const cats = workflowCategories();
    return cats.find(cat => cat.id === activeWorkflowCategoryId && cat.__libraryId === activeWorkflowLibraryId)
        || cats.find(cat => cat.id === activeWorkflowCategoryId)
        || cats[0]
        || null;
}
function workflowCount(){
    return workflowCategories().reduce((sum, cat) => sum + ((cat.items || []).length), 0);
}
function assetCountForLibrary(lib){
    return (lib?.categories || [])
        .filter(cat => (cat.type || 'image') === 'image')
        .reduce((sum, cat) => sum + ((cat.items || []).length), 0);
}
function promptLibraries(){
    const libs = Array.isArray(promptLibrary.libraries) ? promptLibrary.libraries.filter(Boolean) : [];
    if(!libs.length) return [{id:'system', name:'系统提示词库', system:true, items:[], categories:[]}];
    const system = libs.filter(lib => lib.id === 'system');
    const others = libs.filter(lib => lib.id !== 'system');
    return [...system, ...others];
}
function isSystemPromptLibrary(lib){
    return !lib || lib.id === 'system';
}

function activePromptLibrary(){
    const libs = promptLibraries();
    return libs.find(lib => lib.id === activePromptLibraryId) || libs[0] || null;
}
function promptCategoriesFor(lib){
    const fromLib = Array.isArray(lib?.categories) ? lib.categories.filter(c => c?.id) : [];
    if(fromLib.length) return fromLib;
    return [{id:PROMPT_UNCATEGORIZED_CATEGORY_ID, name:PROMPT_UNCATEGORIZED_CATEGORY_NAME}];
}
function activePromptCategories(){
    return promptCategoriesFor(activePromptLibrary());
}
const PROMPT_BUILTIN_CATEGORY_IDS = new Set(['view','storyboard','character','product','lighting','custom']);
function promptCategoryLabel(category=PROMPT_UNCATEGORIZED_CATEGORY_ID){
    const found = activePromptCategories().find(cat => cat.id === category);
    if(found?.name) return found.name;
    const map = {view:'视角', storyboard:'分镜', character:'角色', product:'产品', lighting:'光影', mine:'我的', custom:'我的', [PROMPT_UNCATEGORIZED_CATEGORY_ID]:PROMPT_UNCATEGORIZED_CATEGORY_NAME};
    return map[category] || category || '自定义';
}
function promptCountForCategory(category, lib=activePromptLibrary()){
    const items = lib?.items || [];
    if(category === 'all') return items.length;
    return items.filter(item => (item.category || PROMPT_UNCATEGORIZED_CATEGORY_ID) === category).length;
}
function assetKind(item){
    const url = String(item?.url || '').toLowerCase();
    const kind = String(item?.kind || item?.type || '').toLowerCase();
    if(kind.includes('video') || /\.(mp4|webm|mov|m4v)(\?|#|$)/.test(url)) return 'video';
    if(kind.includes('audio') || /\.(mp3|wav|flac|ogg|m4a)(\?|#|$)/.test(url)) return 'audio';
    if(kind.includes('text') || /\.(txt|json|csv|srt|vtt|md)(\?|#|$)/.test(url)) return 'text';
    return 'image';
}
function materialNameParts(item){
    item = item || {};
    const knownExtensions = /\.(png|jpe?g|webp|gif|bmp|avif|svg|mp4|webm|mov|m4v|avi|mkv|flv|mp3|wav|m4a|aac|ogg|flac|txt|md|markdown|json|csv|yaml|yml|log)$/i;
    const candidates = [item.extension, item.original_name, item.filename, item.display_name, item.file, item.path, item.name]
        .map(value => String(value || '').split('?')[0].split('#')[0])
        .filter(Boolean);
    let extension = String(item.extension || '');
    if(!extension){
        const source = candidates.find(value => knownExtensions.test(value));
        extension = source ? (source.match(knownExtensions)?.[0] || '') : '';
    }
    const rawName = String(item.name || item.display_name || item.original_name || item.filename || item.file || '素材');
    const stem = extension && rawName.toLowerCase().endsWith(extension.toLowerCase())
        ? rawName.slice(0, -extension.length)
        : rawName.replace(knownExtensions, '');
    const cleanStem = stem || '素材';
    return {stem:cleanStem, extension, fullName:`${cleanStem}${extension}`};
}
function materialNameStem(value){
    return String(value || '').trim().replace(/\.(png|jpe?g|webp|gif|bmp|avif|svg|mp4|webm|mov|m4v|avi|mkv|flv|mp3|wav|m4a|aac|ogg|flac|txt|md|markdown|json|csv|yaml|yml|log)$/i, '');
}
function workflowKindLabel(item){
    const format = String(item?.format || '').toLowerCase();
    const url = String(item?.url || '').toLowerCase();
    if(format === 'json' || url.endsWith('.json')) return 'JSON 工作流';
    return 'ZIP 工作流包';
}
function assetKindLabel(item){
    if(window.StudioMedia?.category(item) === 'music') return i18nText('asset.music','音乐');
    const kind = assetKind(item);
    if(kind === 'video') return '视频';
    if(kind === 'audio') return '音频';
    if(kind === 'text') return '文本';
    return '图片';
}
function renderMaterialNameEditor(item, attribute, id){
    const parts = materialNameParts(item);
    return `<div class="asset-name-editor"><input class="detail-name-input" ${attribute}="${escapeAttr(id)}" type="text" value="${escapeAttr(parts.stem)}" title="只修改文件名主体"><span class="asset-name-extension">${escapeHtml(parts.extension)}</span></div>`;
}
// 缩略图走服务端缩放代理（/api/media-preview），把大原图降到 ~256px 再传给浏览器。素材多时滚动只解码小图，
// 不再因为加载/解码整张原图而卡。仅对本地 /output、/assets 的图片/视频生效，其它地址原样返回。
function assetPreviewUrl(url, w=256){
    const raw = String(url || '');
    if(!raw || raw.startsWith('data:') || raw.startsWith('blob:')) return raw;
    let path = raw;
    if(/^https?:\/\//i.test(raw)){
        try { path = new URL(raw).pathname; } catch(e) { return raw; }
    }
    const stableMedia = path.startsWith('/api/materials/') || path.startsWith('/api/results/');
    if(!stableMedia && !(path.startsWith('/output/') || path.startsWith('/assets/'))) return raw;
    if(!stableMedia && !/\.(png|jpe?g|webp|gif|bmp|avif|tiff?|mp4|webm|mov|m4v|mkv)(\?|#|$)/i.test(path)) return raw;
    const width = Math.max(64, Math.min(2048, Math.round(Number(w) || 256)));
    return `/api/media-preview?w=${width}&url=${encodeURIComponent(path)}`;
}
function assetThumb(item){
    const kind = assetKind(item);
    // 视频用 poster（服务端生成的一帧）+ preload=none：不再为每个视频加载元数据，素材多时滚动顺畅。
    if(kind === 'video') return `<img src="${escapeAttr(assetPreviewUrl(item.url, 256))}" data-video-poster="${escapeAttr(item.url)}" alt="${escapeAttr(i18nText('asset.videoCover','视频封面'))}" loading="lazy">`;
    if(window.StudioMedia?.category(item) === 'music') return `<div class="asset-file-icon asset-music-icon"><i data-lucide="music-2"></i><span>${i18nText('asset.music','音乐')}</span></div>`;
    if(kind === 'audio') return `<div class="asset-audio-waveform" aria-label="音频">
        <div class="asset-audio-bars" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
        <i data-lucide="audio-lines"></i><strong>音频</strong><small>双击播放</small>
    </div>`;
    if(kind === 'text') return `<div class="asset-file-icon"><i data-lucide="file-text"></i><span>文本</span></div>`;
    return `<img src="${escapeAttr(assetPreviewUrl(item.url, 256))}" alt="${escapeAttr(item.name || 'asset')}" loading="lazy" decoding="async">`;
}
function assetPreviewCue(item){
    const kind = assetKind(item);
    const icon = ['video','audio'].includes(kind) ? 'play' : kind === 'text' ? 'file-text' : 'maximize-2';
    const label = ['video','audio'].includes(kind) ? i18nText('asset.doubleClickPlay', '双击播放') : i18nText('asset.doubleClickExpand', '双击展开');
    return `<div class="asset-card-hover-cue" aria-hidden="true"><i data-lucide="${icon}"></i><span>${label}</span></div>`;
}
function workflowThumb(item){
    return `<div class="asset-file-icon workflow-file-icon"><i data-lucide="workflow"></i><span>${escapeHtml(workflowKindLabel(item))}</span></div>`;
}
function isLocalMediaFile(file){
    if(!file) return false;
    const type = String(file.type || '').toLowerCase();
    if(type.startsWith('image/') || type.startsWith('video/') || type.startsWith('audio/')) return true;
    return LOCAL_MEDIA_EXTS.test(file.name || '');
}
function localItemKind(item){
    // 共享文件夹的 item 已带 kind；兜底按名称判断
    if(item && item.kind) return item.kind;
    const name = String(item?.name || '').toLowerCase();
    if(/\.(mp4|webm|mov|m4v|mkv)(\?|#|$)/i.test(name)) return 'video';
    if(/\.(mp3|wav|flac|ogg|m4a|aac)(\?|#|$)/i.test(name)) return 'audio';
    return 'image';
}
function localObjectUrl(item){
    // 共享文件夹素材直接走后端 URL（局域网也可访问），不再用 createObjectURL
    return item?.url || '';
}
function localAssetThumb(item){
    return assetThumb({url:localObjectUrl(item), name:item?.name || 'local', kind:item?.kind || localItemKind(item)});
}
function activeLocalFolder(){
    return localFolderMap.get(activeLocalFolderId) || localFolders[0] || null;
}
function localItemsForFolder(folderId=activeLocalFolderId){
    const query = localQuery.trim().toLowerCase();
    const folder = localFolderMap.get(folderId) || activeLocalFolder();
    const items = folder?.items || [];
    return items.filter(item => {
        if(!query) return true;
        return [item.name, item.relativePath, assetKindLabel(item)].join(' ').toLowerCase().includes(query);
    });
}
function localCaptionProviders(){
    return (apiProviders || []).filter(p => p && p.enabled !== false && Array.isArray(p.chat_models) && p.chat_models.length);
}
function normalizeLocalCaptionSettings(){
    const providers = localCaptionProviders();
    const beforeProvider = localCaptionProvider;
    const beforeModel = localCaptionModel;
    if(!providers.length){
        localCaptionProvider = '';
        localCaptionModel = '';
        if(beforeProvider || beforeModel) writeLocalCaptionSettings();
        return;
    }
    let provider = providers.find(p => p.id === localCaptionProvider) || providers[0];
    localCaptionProvider = provider.id || '';
    const models = (provider.chat_models || []).filter(Boolean);
    if(!models.includes(localCaptionModel)) localCaptionModel = models[0] || '';
    if(beforeProvider !== localCaptionProvider || beforeModel !== localCaptionModel) writeLocalCaptionSettings();
}
function localCaptionModels(){
    normalizeLocalCaptionSettings();
    const provider = localCaptionProviders().find(p => p.id === localCaptionProvider);
    return (provider?.chat_models || []).filter(Boolean);
}
function renderLocalCaptionTools(imageCount){
    normalizeLocalCaptionSettings();
    const providers = localCaptionProviders();
    const models = localCaptionModels();
    const captionDisabled = !imageCount || !providers.length || !localCaptionModel || localCaptionBusy;
    return `
        <div class="local-caption-tools">
            <div class="local-caption-main-row">
            <select id="localCaptionProvider" class="manage-select" title="平台" ${providers.length ? '' : 'disabled'}>
                ${providers.length ? providers.map(p => `<option value="${escapeAttr(p.id)}" ${p.id === localCaptionProvider ? 'selected' : ''}>${escapeHtml(p.name || p.id)}</option>`).join('') : '<option value="">暂无聊天平台</option>'}
            </select>
            <select id="localCaptionModel" class="manage-select" title="模型" ${models.length ? '' : 'disabled'}>
                ${models.length ? models.map(m => `<option value="${escapeAttr(m)}" ${m === localCaptionModel ? 'selected' : ''}>${escapeHtml(m)}</option>`).join('') : '<option value="">暂无模型</option>'}
            </select>
            <input id="localCaptionPrompt" class="local-caption-prompt-input" type="text" value="${escapeAttr(localCaptionPrompt || '描述图片')}" placeholder="描述图片">
            <button class="asset-btn primary" type="button" data-local-caption-run ${captionDisabled ? 'disabled' : ''}><i data-lucide="${localCaptionBusy ? 'loader-2' : 'wand-sparkles'}"></i><span>${localCaptionBusy ? '反推中' : '提示词反推'}</span></button>
            </div>
        </div>
    `;
}
function findLocalItem(id){
    return localItemMap.get(id) || null;
}
function normalizeLocalState(){
    if(!activeLocalFolderId || !localFolderMap.has(activeLocalFolderId)) activeLocalFolderId = localFolders[0]?.id || '';
    const items = localItemsForFolder();
    if(selectedLocalId && !localItemMap.has(selectedLocalId)) selectedLocalId = '';
    if(!selectedLocalId && items.length) selectedLocalId = items[0].id;
    selectedLocalIds = new Set([...selectedLocalIds].filter(id => localItemMap.has(id)));
}
function localFolderTotal(folder){
    if(!folder) return 0;
    return (folder.items || []).length + (folder.children || []).reduce((sum, child) => sum + localFolderTotal(child), 0);
}
function localFolderId(path=''){
    return path || '__root__';
}
function localChildPath(parentPath='', name=''){
    return parentPath ? `${parentPath}/${name}` : name;
}
// ---------------- 共享文件夹（服务端登记 + 只读浏览/引用，局域网可用） ----------------
async function loadSharedFolders(){
    try {
        const data = await apiJson('/api/shared-folders');
        sharedFolders = Array.isArray(data.folders) ? data.folders : [];
    } catch(err) {
        sharedFolders = [];
    }
    return sharedFolders;
}
async function loadLocalAssets(){
    try {
        const data = await apiJson('/api/local-assets');
        localAssets = Array.isArray(data.items) ? data.items : [];
        localUploadTree = data.tree || {id:'__root__', path:'', name:'全部上传', count:localAssets.length, items:[], children:[]};
    } catch(err) {
        localAssets = [];
        localUploadTree = {id:'__root__', path:'', name:'全部上传', count:0, items:[], children:[]};
    }
    if(activeLocalUploadFolder && !localUploadFolderExists(activeLocalUploadFolder)) activeLocalUploadFolder = '';
    selectedLocalUploadIds = new Set([...selectedLocalUploadIds].filter(id => localAssets.some(item => item.id === id)));
    localAssetsLoaded = true;
    return localAssets;
}
async function registerSharedFolder(){
    const tip = '请输入要登记的共享文件夹路径（必须位于项目目录内，例如 assets\\library 或 output）：';
    const path = await siteTextInput({title:'登记共享文件夹', placeholder:tip, confirmLabel:'登记'});
    if(!String(path || '').trim()) return;
    try {
        setStatus('正在登记共享文件夹...');
        const data = await apiJson('/api/shared-folders', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({path})
        });
        await loadSharedFolders();
        const folder = data.folder;
        if(folder?.id) await openSharedFolder(folder.id);
        else render();
        setStatus(`已登记「${folder?.name || '共享文件夹'}」`);
    } catch(err) {
        setStatus(err.message || '登记共享文件夹失败');
    }
}
async function unregisterSharedFolder(folderId){
    if(!folderId) return;
    try {
        await apiJson(`/api/shared-folders/${encodeURIComponent(folderId)}`, {method:'DELETE'});
        if(activeSharedFolderId === folderId){
            activeSharedFolderId = '';
            activeSharedFolderName = '';
            localFolders = [];
            localFolderMap = new Map();
            localItemMap = new Map();
            activeLocalFolderId = '';
            selectedLocalId = '';
            selectedLocalIds.clear();
            localClipboard = null;
        }
        await loadSharedFolders();
        render();
        setStatus('已移除共享文件夹登记（不会删除磁盘文件）');
    } catch(err) {
        setStatus(err.message || '移除共享文件夹失败');
    }
}
function indexSharedTree(node){
    if(!node) return;
    localFolderMap.set(node.id, node);
    (node.items || []).forEach(item => localItemMap.set(item.id, item));
    (node.children || []).forEach(child => indexSharedTree(child));
}
async function openSharedFolder(folderId){
    if(!folderId) return;
    try {
        setStatus('正在读取共享文件夹...');
        const data = await apiJson(`/api/shared-folders/${encodeURIComponent(folderId)}/tree`);
        const tree = data.tree;
        localFolders = tree ? [tree] : [];
        localFolderMap = new Map();
        localItemMap = new Map();
        if(tree) indexSharedTree(tree);
        activeSharedFolderId = folderId;
        activeSharedFolderName = data.folder?.name || tree?.name || '共享文件夹';
        activeLocalFolderId = tree?.id || '';
        selectedLocalId = '';
        selectedLocalIds.clear();
        localClipboard = null;
        normalizeLocalState();
        render();
        setStatus(`已读取「${activeSharedFolderName}」`);
    } catch(err) {
        setStatus(err.message || '读取共享文件夹失败');
    }
}
function currentAssetItems(){
    const query = assetQuery.trim().toLowerCase();
    const source = query
            ? assetCategories().flatMap(cat => cat.items || [])
            : (activeAssetCategory()?.items || []);
    return source.filter(item => {
        if(!query) return true;
        return [item.name, item.url, assetKindLabel(item)].join(' ').toLowerCase().includes(query);
    });
}
function currentWorkflowItems(){
    const query = workflowQuery.trim().toLowerCase();
    return (activeWorkflowCategory()?.items || []).filter(item => {
        if(!query) return true;
        return [item.name, item.url, workflowKindLabel(item)].join(' ').toLowerCase().includes(query);
    });
}
function canvasAssetCategories(){
    const items = canvasAssetsData.items || [];
    return [['all','全部'],['text','文本'],['image','图片'],['video','视频'],['audio','音频'],['music','音乐']].map(([id,name]) => ({id,name:id==='music'?i18nText('asset.music',name):name,count:items.filter(item=>id==='all'||StudioMedia.category(item)===id).length}));
}
function activeCanvasAssetCategoryInfo(){
    return canvasAssetCategories().find(cat => cat.id === activeCanvasAssetCategory) || canvasAssetCategories()[0];
}
function defaultCanvasAssetCategory(){
    return 'all';
}
function uniqueCanvasAssets(items){
    const seen = new Set();
    const result = [];
    (items || []).forEach(item => {
        const key = item.id || item.url;
        if(!item?.url || seen.has(key)) return;
        seen.add(key);
        result.push(item);
    });
    return result;
}
function canvasAssetViewTitle(){
    return activeCanvasAssetCategoryInfo()?.name || '生成结果';
}
function canvasAssetViewSubtitle(items){
    return `${items.length} 个结果 / ${escapeHtml(canvasAssetSortLabel())}`;
}
function canvasAssetKindLabel(item){
    if(StudioMedia.category(item)==='music') return i18nText('asset.music','音乐');
    const kind = String(item?.kind || assetKind(item)).toLowerCase();
    if(kind === 'video') return '视频';
    if(kind === 'audio') return '音频';
    if(kind === 'text') return '文本';
    if(kind === 'file') return '文件';
    return '图片';
}
function canvasAssetSortLabel(){
    const map = {updated_desc:'最近生成', updated_asc:'最早生成', name_asc:'名称 A-Z', kind:'类型'};
    return map[canvasAssetSort] || map.updated_desc;
}
function currentCanvasAssetItems(){
    const q = String(canvasAssetQuery || '').trim().toLowerCase();
    let list = uniqueCanvasAssets(canvasAssetsData.items || []).filter(item => {
        if(activeCanvasAssetCategory !== 'all' && StudioMedia.category(item) !== activeCanvasAssetCategory) return false;
        if(!q) return true;
        return [item.name, item.display_name, item.original_name, item.url, canvasAssetKindLabel(item)].join(' ').toLowerCase().includes(q);
    });
    list = list.slice();
    const byTime = item => Number(item.created_at || item.updated_at || 0);
    if(canvasAssetSort === 'updated_asc') list.sort((a, b) => byTime(a) - byTime(b));
    else if(canvasAssetSort === 'name_asc') list.sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh-Hans-CN', {numeric:true, sensitivity:'base'}));
    else if(canvasAssetSort === 'kind') list.sort((a, b) => canvasAssetKindLabel(a).localeCompare(canvasAssetKindLabel(b), 'zh-Hans-CN') || byTime(b) - byTime(a));
    else list.sort((a, b) => byTime(b) - byTime(a));
    return list;
}
function groupCanvasAssetItems(items){
    const groups = new Map();
    items.forEach(item => {
        const source = item?.source_canvas || {};
        const key = String(source.id || '__unknown__');
        if(!groups.has(key)){
            const known = key !== '__unknown__';
            groups.set(key, {
                key,
                title:known ? (source.title || '未命名画布') : '未记录来源',
                subtitle:known ? '智能画布生成' : '这些结果暂时无法确认来源画布',
                items:[]
            });
        }
        groups.get(key).items.push(item);
    });
    return [...groups.values()];
}
function assetMoveTargets(){
    const currentKey = `${activeAssetLibraryId}::${activeAssetCategoryId}`;
    const targets = [];
    assetLibraries().forEach(lib => {
        (lib.categories || []).filter(cat => (cat.type || 'image') === 'image').forEach(cat => {
            const key = `${lib.id}::${cat.id}`;
            if(key !== currentKey) targets.push({key, libraryId:lib.id, categoryId:cat.id, label:`${lib.name || '资产库'} / ${cat.name || '分组'}`});
        });
    });
    return targets;
}
function normalizeAssetMoveTarget(){
    const targets = assetMoveTargets();
    if(!targets.some(item => item.key === assetMoveTarget)) assetMoveTarget = targets[0]?.key || '';
    return targets;
}
function currentPromptItems(){
    const lib = activePromptLibrary();
    const query = promptQuery.trim().toLowerCase();
    return (lib?.items || []).filter(item => {
        if(activePromptCategory !== 'all' && (item.category || PROMPT_UNCATEGORIZED_CATEGORY_ID) !== activePromptCategory) return false;
        if(!query) return true;
        return [item.name, item.scene, item.positive, item.negative, item.category].join(' ').toLowerCase().includes(query);
    });
}
// 列出 API 设置里所有启用的 provider 作为认证候选（以 API 设置为中心，由用户自己选平台）；
// 不支持的平台也列出，在下拉里标注「待接入」，避免用户以为漏了。
// 找出某平台当前可用的 provider_id（优先注册时记录的，其次同平台任一启用 provider）
function findAssetItem(id){
    for(const lib of assetLibraries()) for(const cat of lib.categories || []) for(const item of cat.items || []) if(item.id === id) return item;
    return null;
}
function findWorkflowItem(id){
    for(const lib of assetLibraries()) for(const cat of lib.categories || []) {
        if((cat.type || '') !== 'workflow') continue;
        for(const item of cat.items || []) if(item.id === id) return item;
    }
    return null;
}
function findPromptItem(id){
    for(const lib of promptLibraries()) for(const item of lib.items || []) if(item.id === id) return item;
    return null;
}
function findCanvasAssetItem(id){
    return (canvasAssetsData.items || []).find(item => item.id === id) || null;
}
function selectedAsset(){
    const items = currentAssetItems();
    return items.find(item => item.id === selectedAssetId) || items[0] || null;
}
function selectedWorkflow(){
    const items = currentWorkflowItems();
    return items.find(item => item.id === selectedWorkflowId) || items[0] || null;
}
function selectedPrompt(){
    const items = currentPromptItems();
    return items.find(item => item.id === selectedPromptId) || items[0] || null;
}
function selectedCanvasAsset(){
    const items = currentCanvasAssetItems();
    return items.find(item => item.id === selectedCanvasAssetId) || items[0] || null;
}
function toggleSelectionSet(set, id){
    if(!id) return false;
    if(set.has(id)){
        set.delete(id);
        return false;
    }
    set.add(id);
    return true;
}
function managedSelectionTarget(target){
    if(activeTab === 'assets' && activeInputScope === 'asset' && assetManageMode){
        const check = target.closest?.('[data-asset-check]');
        const card = target.closest?.('[data-asset-card]');
        const id = check?.dataset.assetCheck || card?.dataset.assetCard || '';
        if(id) return {kind:'asset', id};
    }
    if(activeTab === 'assets' && activeInputScope === 'temporary' && localUploadManageMode){
        const check = target.closest?.('[data-localup-check]');
        const card = target.closest?.('[data-localup-card]');
        const id = check?.dataset.localupCheck || card?.dataset.localupCard || '';
        if(id) return {kind:'localup', id};
    }
    if(activeTab === 'assets' && activeInputScope === 'temporary' && localManageMode){
        const check = target.closest?.('[data-local-check]');
        const card = target.closest?.('[data-local-card]');
        const id = check?.dataset.localCheck || card?.dataset.localCard || '';
        if(id) return {kind:'local', id};
    }
    if(activeTab === 'workflows' && workflowManageMode){
        const check = target.closest?.('[data-workflow-check]');
        const card = target.closest?.('[data-workflow-card]');
        const id = check?.dataset.workflowCheck || card?.dataset.workflowCard || '';
        if(id) return {kind:'workflow', id};
    }
    if(activeTab === 'prompts' && promptManageMode){
        const check = target.closest?.('[data-prompt-check]');
        const row = target.closest?.('[data-prompt-row]');
        const id = check?.dataset.promptCheck || row?.dataset.promptRow || '';
        if(id) return {kind:'prompt', id};
    }
    if(activeTab === 'results' && canvasAssetManageMode){
        const check = target.closest?.('[data-canvas-asset-check]');
        const card = target.closest?.('[data-canvas-asset-card]');
        const id = check?.dataset.canvasAssetCheck || card?.dataset.canvasAssetCard || '';
        if(id) return {kind:'canvasAsset', id};
    }
    return null;
}
function applyManagedSelection(kind, id){
    if(kind === 'asset'){
        const selected = toggleSelectionSet(selectedAssetIds, id);
        selectedAssetId = selected ? id : (selectedAssetId === id ? '' : selectedAssetId);
    } else if(kind === 'localup'){
        const selected = toggleSelectionSet(selectedLocalUploadIds, id);
        selectedLocalUploadId = selected ? id : (selectedLocalUploadId === id ? '' : selectedLocalUploadId);
    } else if(kind === 'local'){
        const selected = toggleSelectionSet(selectedLocalIds, id);
        selectedLocalId = selected ? id : (selectedLocalId === id ? '' : selectedLocalId);
    } else if(kind === 'workflow'){
        const selected = toggleSelectionSet(selectedWorkflowIds, id);
        selectedWorkflowId = selected ? id : (selectedWorkflowId === id ? '' : selectedWorkflowId);
    } else if(kind === 'prompt'){
        const selected = toggleSelectionSet(selectedPromptIds, id);
        selectedPromptId = selected ? id : (selectedPromptId === id ? '' : selectedPromptId);
        promptEditMode = false;
        promptCreateMode = false;
    } else if(kind === 'canvasAsset'){
        const selected = toggleSelectionSet(selectedCanvasAssetIds, id);
        selectedCanvasAssetId = selected ? id : (selectedCanvasAssetId === id ? '' : selectedCanvasAssetId);
    }
    pendingBatchDelete = '';
}
function guardMatchesManagedSelection(target){
    const current = managedSelectionTarget(target);
    return !!current
        && !!managedSelectionPointerGuard
        && current.kind === managedSelectionPointerGuard.kind
        && current.id === managedSelectionPointerGuard.id
        && Date.now() - managedSelectionPointerGuard.at < 600;
}
function normalizeAssetState(){
    const libs = assetLibraries();
    if(!activeAssetLibraryId || !libs.some(lib => lib.id === activeAssetLibraryId)) activeAssetLibraryId = assetLibrary.active_library_id || libs[0]?.id || '';
    const cats = assetCategories();
    if(!activeAssetCategoryId || !cats.some(cat => cat.id === activeAssetCategoryId)) activeAssetCategoryId = cats[0]?.id || '';
    const items = currentAssetItems();
    if(selectedAssetId && !items.some(item => item.id === selectedAssetId)) selectedAssetId = '';
    if(!selectedAssetId && items.length) selectedAssetId = items[0].id;
    selectedAssetIds = new Set([...selectedAssetIds].filter(id => findAssetItem(id)));
}
function normalizeWorkflowState(){
    const libs = assetLibraries();
    if(!activeWorkflowLibraryId || !libs.some(lib => lib.id === activeWorkflowLibraryId)) activeWorkflowLibraryId = assetLibrary.active_library_id || libs[0]?.id || '';
    const cats = workflowCategories();
    if(
        !activeWorkflowCategoryId
        || !cats.some(cat => cat.id === activeWorkflowCategoryId && cat.__libraryId === activeWorkflowLibraryId)
    ){
        activeWorkflowCategoryId = cats[0]?.id || '';
        activeWorkflowLibraryId = cats[0]?.__libraryId || activeWorkflowLibraryId;
    }
    const activeCat = cats.find(cat => cat.id === activeWorkflowCategoryId && cat.__libraryId === activeWorkflowLibraryId) || null;
    if(activeCat?.__libraryId) activeWorkflowLibraryId = activeCat.__libraryId;
    const items = currentWorkflowItems();
    if(selectedWorkflowId && !items.some(item => item.id === selectedWorkflowId)) selectedWorkflowId = '';
    if(!selectedWorkflowId && items.length) selectedWorkflowId = items[0].id;
    selectedWorkflowIds = new Set([...selectedWorkflowIds].filter(id => findWorkflowItem(id)));
}
function normalizePromptState(){
    const libs = promptLibraries();
    if(!activePromptLibraryId || !libs.some(lib => lib.id === activePromptLibraryId)) activePromptLibraryId = promptLibrary.active_library_id || libs[0]?.id || '';
    const cats = activePromptCategories();
    if(activePromptCategory !== 'all' && !cats.some(cat => cat.id === activePromptCategory)) activePromptCategory = 'all';
    const items = currentPromptItems();
    if(selectedPromptId && !items.some(item => item.id === selectedPromptId)) selectedPromptId = '';
    if(!selectedPromptId && items.length) selectedPromptId = items[0].id;
    selectedPromptIds = new Set([...selectedPromptIds].filter(id => findPromptItem(id)));
}
function normalizeCanvasAssetState(){
    const cats = canvasAssetCategories();
    if(!cats.some(cat => cat.id === activeCanvasAssetCategory)) activeCanvasAssetCategory = defaultCanvasAssetCategory();
    activeCanvasAssetCanvasId = '';
    const items = currentCanvasAssetItems();
    if(selectedCanvasAssetId && !items.some(item => item.id === selectedCanvasAssetId)) selectedCanvasAssetId = '';
    if(!selectedCanvasAssetId && items.length) selectedCanvasAssetId = items[0].id;
    selectedCanvasAssetIds = new Set([...selectedCanvasAssetIds].filter(id => findCanvasAssetItem(id)));
}
async function refreshCanvasAssets(){
    try {
        setStatus('正在刷新生成结果...');
        const data = await apiJson('/api/results');
        canvasAssetsData = {
            counts:data.counts || {all:0,image:0,video:0,audio:0,text:0},
            items:Array.isArray(data.items) ? data.items : []
        };
        normalizeCanvasAssetState();
        render();
        setStatus('生成结果已刷新');
    } catch(err) {
        setStatus(err.message || '刷新生成结果失败');
    }
}
async function refreshPromptLibraries(){
    const data = await apiJson('/api/prompt-libraries');
    promptLibrary = data.library || {libraries:[]};
    normalizePromptState();
    if(activeTab === 'prompts') render();
}
async function loadAll(){
    setStatus('加载中...');
    const [assetData, promptData, providerData, canvasAssetData] = await Promise.all([
        apiJson('/api/asset-library'),
        apiJson('/api/prompt-libraries'),
        apiJson('/api/providers').catch(() => ({providers:[]})),
        apiJson('/api/results').catch(() => ({counts:{all:0,image:0,video:0,audio:0,text:0}, items:[]})),
        loadSharedFolders(),
        loadLocalAssets()
    ]);
    assetLibrary = assetData.library || {libraries:[], categories:[]};
    promptLibrary = promptData.library || {libraries:[]};
    apiProviders = Array.isArray(providerData.providers) ? providerData.providers : [];
    canvasAssetsData = {
        counts:canvasAssetData.counts || {all:0,image:0,video:0,audio:0,text:0},
        items:Array.isArray(canvasAssetData.items) ? canvasAssetData.items : []
    };
    // 刷新时默认回到「默认资产库」
    const libs = assetLibraries();
    activeAssetLibraryId = (libs.find(lib => lib.id === 'default') || libs[0])?.id || '';
    activeWorkflowLibraryId = (libs.find(lib => lib.id === 'default') || libs[0])?.id || '';
    activeAssetCategoryId = '';
    activeWorkflowCategoryId = '';
    selectedAssetId = '';
    selectedWorkflowId = '';
    selectedAssetIds.clear();
    selectedWorkflowIds.clear();
    selectedPromptIds.clear();
    selectedCanvasAssetIds.clear();
    render();
    setStatus('准备就绪');
}
function render(){
    const scrollState = [...document.querySelectorAll('.nav-scroll,.content-scroll,.detail-scroll')]
        .map((el, index) => ({index, top:el.scrollTop, left:el.scrollLeft}));
    document.querySelectorAll('[data-tab]').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === activeTab));
    if(activeTab === 'prompts') renderPromptManager();
    else if(activeTab === 'workflows') renderWorkflowManager();
    else if(activeTab === 'results') renderCanvasAssetsManager();
    else renderInputMaterialsManager();
    refreshIcons();
    if(scrollState.length){
        requestAnimationFrame(() => {
            document.querySelectorAll('.nav-scroll,.content-scroll,.detail-scroll').forEach((el, index) => {
                const saved = scrollState.find(item => item.index === index);
                if(!saved) return;
                el.scrollTop = saved.top;
                el.scrollLeft = saved.left;
            });
        });
    }
}
function renderInputMaterialsManager(){
    if(activeInputScope === 'temporary'){
        activeLocalUploadFolder = '';
        renderLocalManager();
    }
    else renderAssetManager();
    const navigation = root.querySelector('.asset-nav');
    if(navigation) navigation.outerHTML = renderUnifiedInputNavigation();
}
function renderUnifiedInputNavigation(){
    const assetActive = activeInputScope === 'asset';
    const libraries = assetLibraries();
    const assetTotal = libraries.reduce((total, library) => total + assetCountForLibrary(library), 0);
    const temporaryTotal = (localAssets || []).length;
    const actions = assetActive
        ? `${assetTreeEdit?.placement === 'head' ? '' : '<button class="asset-icon-btn" type="button" data-asset-lib-new title="新建资产库"><i data-lucide="plus"></i></button>'}
            ${renderHeadTreeInlineEdit(assetTreeEdit, 'assetTreeEditInput', 'data-asset-tree-edit-save', 'data-asset-tree-edit-cancel')}`
        : '';
    return `<aside class="asset-panel asset-nav input-material-nav">
        <div class="panel-head">
            <div class="panel-title"><strong>${escapeHtml(i18nText('asset.inputMaterials', '输入素材'))}</strong><span>${escapeHtml(i18nText('asset.inputNavigationHint', '选择分类后管理素材'))}</span></div>
            <div class="panel-actions compact-actions">${actions}</div>
        </div>
        <div class="nav-scroll">
            <div class="nav-tree input-material-tree">
                <div class="tree-branch input-scope-branch ${assetActive ? 'expanded' : ''}">
                    <button class="tree-row tree-parent input-scope-root ${assetActive ? 'active' : ''}" type="button" data-input-scope="asset" aria-expanded="${assetActive}">
                        <span class="tree-row-icon"><i data-lucide="archive"></i></span>
                        <span class="tree-row-name">${escapeHtml(i18nText('asset.assetMaterials', '资产素材'))}</span>
                        <span class="tree-row-count">${assetTotal}</span>
                    </button>
                    ${assetActive ? `<div class="tree-children input-scope-children">${libraries.map(library => renderAssetTreeBranch(library)).join('')}</div>` : ''}
                </div>
                <div class="tree-branch input-scope-branch ${assetActive ? '' : 'expanded'}">
                    <button class="tree-row tree-parent input-scope-root ${assetActive ? '' : 'active'}" type="button" data-input-scope="temporary" aria-expanded="${!assetActive}">
                        <span class="tree-row-icon"><i data-lucide="clock-3"></i></span>
                        <span class="tree-row-name">${escapeHtml(i18nText('asset.temporaryMaterials', '临时素材'))}</span>
                        <span class="tree-row-count">${temporaryTotal}</span>
                    </button>
                </div>
            </div>
            ${assetActive ? '' : '<div class="nav-hint" style="padding:10px 12px;font-size:12px;opacity:.7;">上传内容保存在 assets/input/temporary；相同文件会自动复用，不会重复占用空间。</div>'}
        </div>
    </aside>`;
}
function updateSearchQueryFromInput(id, value){
    if(id === 'assetSearch') assetQuery = value || '';
    else if(id === 'workflowSearch') workflowQuery = value || '';
    else if(id === 'promptSearch') promptQuery = value || '';
    else if(id === 'localSearch') localQuery = value || '';
    else if(id === 'localUploadSearch') localUploadQuery = value || '';
    else if(id === 'canvasAssetSearch') canvasAssetQuery = value || '';
}
function clearSearchSelection(id){
    if(id === 'assetSearch') selectedAssetId = '';
    else if(id === 'workflowSearch') selectedWorkflowId = '';
    else if(id === 'promptSearch') selectedPromptId = '';
    else if(id === 'localSearch') selectedLocalId = '';
    else if(id === 'localUploadSearch') selectedLocalUploadId = '';
    else if(id === 'canvasAssetSearch') selectedCanvasAssetId = '';
}
function scheduleSearchRender(id, pos=0, delay=140){
    clearTimeout(searchRenderTimer);
    searchRenderTimer = setTimeout(() => {
        clearSearchSelection(id);
        render();
        requestAnimationFrame(() => {
            const input = document.getElementById(id);
            input?.focus();
            try { input?.setSelectionRange?.(pos, pos); } catch(_) {}
        });
    }, Math.max(0, delay));
}
function renderCanvasAssetsManager(){
    normalizeCanvasAssetState();
    const items = currentCanvasAssetItems();
    const groups = groupCanvasAssetItems(items);
    const total = uniqueCanvasAssets(canvasAssetsData.items || []).length;
    const detail = selectedCanvasAsset();
    root.innerHTML = `
        <aside class="asset-panel asset-nav">
            <div class="panel-head"><div class="panel-title"><strong>结果类型</strong><span>按文件类型筛选</span></div></div>
            <div class="nav-scroll">
                <div class="nav-tree canvas-asset-tree">
                    ${canvasAssetCategories().map(cat => renderCanvasAssetTreeBranch(cat)).join('')}
                </div>
                <div class="nav-hint">共 ${total} 个生成结果。删除画布不会影响这里已经保存的内容。</div>
            </div>
        </aside>
        <section class="asset-panel asset-content ${canvasAssetManageMode ? 'manage-on' : ''}">
            <div class="content-toolbar">
                <div class="content-heading">
                    <strong>${escapeHtml(canvasAssetViewTitle())}</strong>
                    <span>${canvasAssetViewSubtitle(items)}</span>
                </div>
                <div class="asset-tools">
                    <button class="asset-btn" type="button" data-canvas-asset-refresh title="重新读取已保存的生成结果"><i data-lucide="refresh-cw"></i><span>刷新结果</span></button>
                    <label class="asset-search-wrap"><i data-lucide="search"></i><input id="canvasAssetSearch" class="asset-search" type="search" value="${escapeAttr(canvasAssetQuery)}" placeholder="搜索生成结果"></label>
                    <select id="canvasAssetSort" class="manage-select canvas-sort-select" title="排序方法">
                        <option value="updated_desc" ${canvasAssetSort === 'updated_desc' ? 'selected' : ''}>最近生成</option>
                        <option value="updated_asc" ${canvasAssetSort === 'updated_asc' ? 'selected' : ''}>最早生成</option>
                        <option value="name_asc" ${canvasAssetSort === 'name_asc' ? 'selected' : ''}>结果名称</option>
                        <option value="kind" ${canvasAssetSort === 'kind' ? 'selected' : ''}>类型</option>
                    </select>
                    <button class="asset-btn ${canvasAssetManageMode ? 'primary' : ''}" type="button" data-canvas-asset-manage ${total ? '' : 'disabled'}><i data-lucide="list-checks"></i><span>${canvasAssetManageMode ? '完成管理' : '批量管理'}</span></button>
                </div>
            </div>
            <div class="manage-tools">
                <span>已选择 ${selectedCanvasAssetIds.size} 个生成结果，支持拖拽框选或逐个勾选。</span>
                <div class="asset-tools">
                    ${renderSelectToggle("canvas-asset", items, selectedCanvasAssetIds)}
                    <button class="asset-btn primary" type="button" data-canvas-asset-download-selected ${selectedCanvasAssetIds.size ? '' : 'disabled'}><i data-lucide="download"></i><span>下载所选</span></button>
                    <button class="asset-btn danger" type="button" data-result-delete-selected ${selectedCanvasAssetIds.size ? '' : 'disabled'}><i data-lucide="trash-2"></i><span>删除所选</span></button>
                </div>
            </div>
            <div class="content-scroll">
                <div class="asset-grid">
                    ${groups.map(group => renderCanvasAssetGroup(group)).join('')}
                    ${items.length ? '' : '<div class="empty-state">当前分类还没有生成结果。画布完成图片、视频、音频或文本生成后，会自动保存到这里。</div>'}
                </div>
            </div>
        </section>
        <aside class="asset-panel asset-detail">
            ${renderCanvasAssetDetail(detail)}
        </aside>
    `;
}
function renderCanvasAssetTreeBranch(cat){
    const icons = {all:'layers-3', text:'file-text', image:'image', video:'video', audio:'audio-lines', music:'music-2'};
    return `<div class="tree-branch">
        <button class="tree-row tree-parent ${cat.id === activeCanvasAssetCategory ? 'active' : ''}" type="button" data-canvas-asset-cat="${escapeAttr(cat.id)}">
            <span class="tree-row-icon"><i data-lucide="${icons[cat.id] || 'file'}"></i></span>
            <span class="tree-row-name">${escapeHtml(cat.name || '全部')}</span>
            <span class="tree-row-count">${Number(cat.count || 0)}</span>
        </button>
    </div>`;
}
function renderCanvasAssetGroup(group){
    if(!group?.title) return (group?.items || []).map(item => renderCanvasAssetCard(item)).join('');
    return `<section class="canvas-asset-group">
        <div class="canvas-asset-group-head">
            <div>
                <strong title="${escapeAttr(group.title)}">${escapeHtml(group.title)}</strong>
                <span>${escapeHtml(group.subtitle || '')}</span>
            </div>
            <small>${(group.items || []).length} 个结果</small>
        </div>
        <div class="canvas-asset-group-grid">
            ${(group.items || []).map(item => renderCanvasAssetCard(item)).join('')}
        </div>
    </section>`;
}
function renderCanvasAssetCard(item){
    return `<article class="asset-card canvas-asset-card ${item.id === selectedCanvasAssetId ? 'active' : ''}" data-canvas-asset-card="${escapeAttr(item.id)}">
        <input class="asset-card-check" type="checkbox" data-canvas-asset-check="${escapeAttr(item.id)}" ${selectedCanvasAssetIds.has(item.id) ? 'checked' : ''}>
        <div class="asset-thumb canvas-asset-thumb">${assetThumb(item)}${renderCanvasAssetKindBadge(item)}${assetPreviewCue(item)}</div>
        <div class="asset-card-body">
            <div class="asset-card-name" data-result-rename="${escapeAttr(item.id)}" title="编辑名称" data-i18n-title="asset.rename">${escapeHtml(item.name || item.display_name || '生成结果')}</div>
            <div class="asset-card-meta">${escapeHtml(canvasAssetKindLabel(item))} · ${escapeHtml(formatDate(item.created_at))}</div>
        </div>
    </article>`;
}
function renderCanvasAssetKindBadge(item){
    const kind = assetKind(item);
    const icon = StudioMedia.category(item)==='music' ? 'music-2' : kind === 'video' ? 'play' : kind === 'audio' ? 'audio-lines' : kind === 'text' ? 'file-text' : 'image';
    return `<span class="asset-kind-badge ${escapeAttr(kind)}" title="${escapeAttr(canvasAssetKindLabel(item))}"><i data-lucide="${icon}"></i></span>`;
}
function renderCanvasAssetDetail(item){
    if(!item) return `<div class="panel-head"><div class="panel-title"><strong>生成结果详情</strong><span>选择一个结果查看详情</span></div></div><div class="detail-scroll"><div class="detail-empty"><i data-lucide="sparkles"></i><span>暂无生成结果</span></div></div>`;
    const kind = assetKind(item);
    const canPreview = ['image','video','audio','text'].includes(kind);
    const canEditText = kind === 'text';
    const previewIcon = ['video','audio'].includes(kind) ? 'play' : kind === 'text' ? 'file-text' : 'maximize-2';
    const previewTitle = ['video','audio'].includes(kind) ? i18nText('asset.play', '播放') : kind === 'text' ? i18nText('asset.expandText', '展开文本') : i18nText('asset.expandImage', '展开图片');
    return `
        <div class="panel-head">
            <div class="panel-title"><strong>生成结果详情</strong><span>${escapeHtml(canvasAssetKindLabel(item))}</span></div>
            <div class="panel-actions">
                ${canPreview ? `<button class="asset-icon-btn" type="button" data-canvas-asset-preview="${escapeAttr(item.id)}" title="${previewTitle}"><i data-lucide="${previewIcon}"></i></button>` : ''}
                ${canEditText ? `<button class="asset-icon-btn" type="button" data-text-edit="canvas-asset:${escapeAttr(item.id)}" title="编辑文本内容" data-i18n-title="asset.editText"><i data-lucide="pencil-line"></i></button>` : ''}
                <button class="asset-icon-btn" type="button" data-canvas-asset-download="${escapeAttr(item.id)}" title="下载素材" data-i18n-title="asset.download"><i data-lucide="download"></i></button>
                <button class="asset-icon-btn" type="button" data-result-rename="${escapeAttr(item.id)}" title="编辑名称" data-i18n-title="asset.rename"><i data-lucide="pencil"></i></button>
                <button class="asset-icon-btn" type="button" data-result-promote="${escapeAttr(item.id)}" title="收藏到资产素材" data-i18n-title="asset.promote"><i data-lucide="bookmark-plus"></i></button>
                <button class="asset-icon-btn danger" type="button" data-result-delete="${escapeAttr(item.id)}" title="删除结果" data-i18n-title="asset.deleteResult"><i data-lucide="trash-2"></i></button>
            </div>
        </div>
        <div class="detail-scroll">
            <div class="detail-media">
                ${canPreview
                    ? `<button class="detail-media-frame detail-media-zoomable" type="button" data-canvas-asset-preview="${escapeAttr(item.id)}" title="${previewTitle}">${assetThumb(item)}</button>`
                    : `<div class="detail-media-frame">${assetThumb(item)}</div>`}
            </div>
            <div class="detail-body">
                ${renderMaterialNameEditor(item, 'data-result-inline-name', item.id)}
                <div class="detail-meta-grid">
                    <div class="detail-meta"><span>类型</span><strong>${escapeHtml(canvasAssetKindLabel(item))}</strong></div>
                    <div class="detail-meta"><span>大小</span><strong>${escapeHtml(formatFileSize(item.size))}</strong></div>
                    <div class="detail-meta"><span>生成时间</span><strong>${escapeHtml(formatDate(item.created_at))}</strong></div>
                    <div class="detail-meta"><span>保存位置</span><strong title="${escapeAttr(item.path || '')}">${escapeHtml(item.path || '生成结果')}</strong></div>
                </div>
                <div class="detail-url">${escapeHtml(item.url || '')}</div>
            </div>
        </div>
    `;
}
function refreshCanvasAssetSelectionOnly(){
    document.querySelectorAll('[data-canvas-asset-card]').forEach(card => {
        card.classList.toggle('active', card.dataset.canvasAssetCard === selectedCanvasAssetId);
    });
    document.querySelectorAll('[data-canvas-asset-check]').forEach(input => {
        input.checked = selectedCanvasAssetIds.has(input.dataset.canvasAssetCheck);
    });
    const detail = root.querySelector('.asset-detail');
    if(detail){
        detail.innerHTML = renderCanvasAssetDetail(selectedCanvasAsset());
        refreshIcons();
    }
}
function renderHeadTreeInlineEdit(edit, inputId, saveAttr, cancelAttr){
    if(!edit || edit.placement !== 'head') return '';
    const label = edit.label || '名称';
    return `<div class="head-inline-edit">
        <input id="${escapeAttr(inputId)}" type="text" value="${escapeAttr(edit.value || '')}" placeholder="${escapeAttr(label)}">
        <button type="button" class="primary" ${saveAttr} title="保存"><i data-lucide="check"></i><span>保存</span></button>
        <button type="button" ${cancelAttr} title="取消"><i data-lucide="x"></i><span>取消</span></button>
    </div>`;
}
function focusTreeEditInput(id){
    requestAnimationFrame(() => {
        const input = document.getElementById(id);
        input?.focus();
        input?.select?.();
    });
}
function localUploadItems(){
    const q = String(localUploadQuery || '').trim().toLowerCase();
    let list = Array.isArray(localAssets) ? localAssets.slice() : [];
    if(q) list = list.filter(it => {
        return [it.name, it.file, assetKindLabel(it)].join(' ').toLowerCase().includes(q);
    });
    return list;
}
function findLocalUpload(id){
    return (localAssets || []).find(it => it.id === id) || null;
}
function localUploadFolderExists(path=''){
    const target = String(path || '');
    let found = !target;
    function walk(node){
        if(!node || found) return;
        if(String(node.path || '') === target){ found = true; return; }
        (node.children || []).forEach(walk);
    }
    walk(localUploadTree);
    return found;
}
function localUploadFolderByPath(path=''){
    const target = String(path || '');
    let match = null;
    function walk(node){
        if(!node || match) return;
        if(String(node.path || '') === target){ match = node; return; }
        (node.children || []).forEach(walk);
    }
    walk(localUploadTree);
    return match;
}
function localUploadFolderTitle(){
    if(!activeLocalUploadFolder) return '临时素材';
    return localUploadFolderByPath(activeLocalUploadFolder)?.name || activeLocalUploadFolder.split('/').pop() || '临时素材';
}
function localUploadViewSubtitle(items){
    return `${items.length} / ${(localAssets || []).length} 个素材`;
}
function renderLocalUploadFolderBranch(folder, depth=0){
    if(!folder) return '';
    const path = folder.path || '';
    const active = path === activeLocalUploadFolder;
    const contains = !active && (folder.children || []).some(child => localUploadFolderContainsActive(child));
    return `<div class="tree-branch">
        <button class="tree-row ${depth ? 'tree-child' : 'tree-parent'} ${active ? 'active' : ''} ${contains ? 'contains-active' : ''}" type="button" data-localup-folder="${escapeAttr(path)}">
            ${depth ? '<span class="tree-elbow"></span>' : ''}
            <span class="tree-row-icon"><i data-lucide="${active ? 'folder-open' : (depth ? 'folder' : 'upload-cloud')}"></i></span>
            <span class="tree-row-name">${escapeHtml(folder.name || '文件夹')}</span>
            <span class="tree-row-count">${Number(folder.count || 0)}</span>
        </button>
        ${(folder.children || []).length ? `<div class="tree-children">${folder.children.map(child => renderLocalUploadFolderBranch(child, depth + 1)).join('')}</div>` : ''}
    </div>`;
}
function localUploadFolderContainsActive(folder){
    if(!folder) return false;
    if(String(folder.path || '') === activeLocalUploadFolder) return true;
    return (folder.children || []).some(child => localUploadFolderContainsActive(child));
}
function selectedLocalUploadImageItems(){
    return [...selectedLocalUploadIds].map(id => findLocalUpload(id)).filter(item => item && assetKind(item) === 'image');
}
function selectedAssetImageItems(){
    return [...selectedAssetIds].map(id => findAssetItem(id)).filter(item => item && assetKind(item) === 'image');
}
function renderLocalManager(){
    normalizeLocalCaptionSettings();
    const items = localUploadItems();
    // 只有当选中的素材"真的不存在了"(被删除)才清空；只是被分类/筛选挡住时仍保留预览，
    // 这样切换分类时中间预览不会跳回第一张，方便对照着找相似图片。
    if(selectedLocalUploadId && !findLocalUpload(selectedLocalUploadId)) selectedLocalUploadId = '';
    if(!selectedLocalUploadId && items.length) selectedLocalUploadId = items[0].id;
    const detail = findLocalUpload(selectedLocalUploadId);
    const total = (localAssets || []).length;
    const imageCount = selectedLocalUploadImageItems().length;
    root.innerHTML = `
        <aside class="asset-panel asset-nav">
            <div class="panel-head">
                <div class="panel-title"><strong>临时素材</strong><span>上传、调用与整理输入素材</span></div>
            </div>
            <div class="nav-scroll">
                <div class="nav-tree"></div>
                <div class="nav-hint" style="padding:10px 12px;font-size:12px;opacity:.7;">上传内容保存在 assets/input/temporary；相同文件会自动复用，不会重复占用空间。</div>
            </div>
        </aside>
        <section class="asset-panel asset-content ${localUploadManageMode ? 'manage-on' : ''}">
            <div class="content-toolbar">
                <div class="content-heading">
                    <strong>临时素材</strong>
                    <span>${localUploadViewSubtitle(items)}</span>
                </div>
                <div class="asset-tools">
                    <label class="asset-search-wrap"><i data-lucide="search"></i><input id="localUploadSearch" class="asset-search" type="search" value="${escapeAttr(localUploadQuery)}" placeholder="搜索临时素材"></label>
                    <button class="asset-btn primary" type="button" data-localup-upload><i data-lucide="upload"></i><span>上传文件</span></button>
                    <button class="asset-btn ${localUploadManageMode ? 'primary' : ''}" type="button" data-localup-manage ${total ? '' : 'disabled'}><i data-lucide="list-checks"></i><span>${localUploadManageMode ? '完成管理' : '批量管理'}</span></button>
                </div>
            </div>
            <div class="manage-tools local-manage-tools">
                <div class="manage-group manage-select-group">
                    <span class="manage-group-title">管理</span>
                    <span class="manage-summary">已选 ${selectedLocalUploadIds.size} 个，其中 ${imageCount} 张图片</span>
                    <div class="asset-tools local-manage-actions">
                        ${renderSelectToggle("localup", items, selectedLocalUploadIds)}
                        <button class="asset-btn" type="button" data-localup-download-selected ${selectedLocalUploadIds.size ? '' : 'disabled'}><i data-lucide="download"></i><span>下载所选</span></button>
                        <button class="asset-btn danger" type="button" data-localup-delete-selected ${selectedLocalUploadIds.size ? '' : 'disabled'}><i data-lucide="trash-2"></i><span>删除所选</span></button>
                    </div>
                </div>

            </div>
            <div class="content-scroll">
                <div class="asset-grid">
                    ${renderLocalUploadAddCard()}
                    ${items.map(item => renderLocalUploadCard(item)).join('')}
                </div>
            </div>
        </section>
        <aside class="asset-panel asset-detail">
            ${renderLocalUploadDetail(detail)}
        </aside>
    `;
}
function renderLocalUploadAddCard(){
    return `<button id="localUploadDrop" class="upload-grid-card" type="button" data-localup-upload>
        <span class="upload-thumb"><i data-lucide="upload-cloud"></i></span>
        <span class="upload-body">
            <strong>上传本地素材</strong>
            <small>拖入文件或点击上传</small>
        </span>
    </button>`;
}
function renderLocalUploadCard(item){
    const hasCaption = assetKind(item) === 'image' && String(item.caption || '').trim();
    const parts = materialNameParts(item);
    return `<article class="asset-card ${item.id === selectedLocalUploadId ? 'active' : ''}" data-localup-card="${escapeAttr(item.id)}">
        <input class="asset-card-check" type="checkbox" data-localup-check="${escapeAttr(item.id)}" ${selectedLocalUploadIds.has(item.id) ? 'checked' : ''}>
        <div class="asset-thumb">${assetThumb(item)}${assetPreviewCue(item)}</div>
        <div class="asset-card-body">
            <div class="asset-card-name" data-localup-rename="${escapeAttr(item.id)}" title="${escapeAttr(parts.fullName)}">${escapeHtml(parts.fullName)}</div>
            <div class="asset-card-meta">${escapeHtml(assetKindLabel(item))} · ${escapeHtml(formatFileSize(item.size))}${hasCaption ? ' · 有提示词' : ''}</div>
        </div>
    </article>`;
}
function renderLocalUploadDetail(item){
    if(!item) return `<div class="panel-head"><div class="panel-title"><strong>素材预览</strong><span>选择一个素材查看详情</span></div></div><div class="detail-scroll"><div class="detail-empty"><i data-lucide="image"></i><span>暂无可预览素材</span></div></div>`;
    const isImage = assetKind(item) === 'image';
    const kind = assetKind(item);
    const canEditText = kind === 'text';
    const previewIcon = ['video','audio'].includes(kind) ? 'play' : kind === 'text' ? 'file-text' : 'maximize-2';
    const previewTitle = ['video','audio'].includes(kind) ? i18nText('asset.play', '播放') : kind === 'text' ? i18nText('asset.expandText', '展开文本') : i18nText('asset.expandImage', '展开图片');
    return `
        <div class="panel-head">
            <div class="panel-title"><strong>素材预览</strong><span>${escapeHtml(assetKindLabel(item))}</span></div>
            <div class="panel-actions">
                <button class="asset-icon-btn" type="button" data-localup-preview="${escapeAttr(item.id)}" title="${previewTitle}"><i data-lucide="${previewIcon}"></i></button>
                ${canEditText ? `<button class="asset-icon-btn" type="button" data-text-edit="localup:${escapeAttr(item.id)}" title="编辑文本内容" data-i18n-title="asset.editText"><i data-lucide="pencil-line"></i></button>` : ''}
                <button class="asset-icon-btn" type="button" data-localup-download="${escapeAttr(item.id)}" title="下载素材" data-i18n-title="asset.download"><i data-lucide="download"></i></button>
                <button class="asset-icon-btn" type="button" data-localup-rename="${escapeAttr(item.id)}" title="编辑名称" data-i18n-title="asset.rename"><i data-lucide="pencil"></i></button>
                <button class="asset-icon-btn" type="button" data-localup-promote="${escapeAttr(item.id)}" title="收藏到资产素材" data-i18n-title="asset.promote"><i data-lucide="bookmark-plus"></i></button>
                <button class="asset-icon-btn danger" type="button" data-localup-delete-one="${escapeAttr(item.id)}" title="删除"><i data-lucide="trash-2"></i></button>
            </div>
        </div>
        <div class="detail-scroll">
            <div class="detail-media"><button class="detail-media-frame detail-media-zoomable" type="button" data-localup-preview="${escapeAttr(item.id)}" title="${previewTitle}">${assetThumb(item)}</button></div>
            <div class="detail-body">
                ${renderMaterialNameEditor(item, 'data-localup-inline-name', item.id)}
                <div class="detail-meta-grid">
                    <div class="detail-meta"><span>类型</span><strong>${escapeHtml(assetKindLabel(item))}</strong></div>
                    <div class="detail-meta"><span>大小</span><strong>${escapeHtml(formatFileSize(item.size))}</strong></div>
                    <div class="detail-meta"><span>上传时间</span><strong>${escapeHtml(formatDate(item.created_at))}</strong></div>
                    <div class="detail-meta"><span>来源</span><strong>本地上传</strong></div>
                </div>
                <div class="detail-url">${escapeHtml(item.url || '')}</div>
                ${isImage ? `
                    <div class="detail-caption-card">
                        <div class="detail-caption-head">
                            <strong>反推提示词</strong>
                            <div class="detail-caption-actions">
                                <button class="asset-btn" type="button" data-localup-caption-one="${escapeAttr(item.id)}" ${localCaptionBusy ? 'disabled' : ''}><i data-lucide="${localCaptionBusy ? 'loader-2' : 'wand-sparkles'}"></i><span>${localCaptionBusy ? '反推中' : '反推'}</span></button>
                                <button class="asset-btn" type="button" data-localup-caption-copy="${escapeAttr(item.id)}"><i data-lucide="copy"></i><span>复制</span></button>
                                <button class="asset-btn primary" type="button" data-localup-caption-save="${escapeAttr(item.id)}"><i data-lucide="save"></i><span>保存</span></button>
                            </div>
                        </div>
                        <textarea id="localUploadCaptionEdit" class="detail-caption-textarea" placeholder="暂无反推提示词，可以批量反推后自动写入，也可以在这里手动编辑。">${escapeHtml(item.caption || '')}</textarea>
                    </div>
                ` : ''}
            </div>
        </div>
    `;
}
function refreshLocalUploadSelectionOnly(){
    document.querySelectorAll('[data-localup-card]').forEach(card => {
        card.classList.toggle('active', card.dataset.localupCard === selectedLocalUploadId);
    });
    document.querySelectorAll('[data-localup-check]').forEach(input => {
        input.checked = selectedLocalUploadIds.has(input.dataset.localupCheck);
    });
    const detail = root.querySelector('.asset-detail');
    if(detail){
        detail.innerHTML = renderLocalUploadDetail(findLocalUpload(selectedLocalUploadId));
        refreshIcons();
    }
}
function renderLocalFolderBranch(folder, depth=0){
    const active = folder.id === activeLocalFolderId;
    const contains = !active && (folder.children || []).some(child => child.id === activeLocalFolderId || folderContainsLocalActive(child));
    return `<div class="tree-branch">
        <button class="tree-row ${depth ? 'tree-child' : 'tree-parent'} ${active ? 'active' : ''} ${contains ? 'contains-active' : ''}" type="button" data-local-folder="${escapeAttr(folder.id)}">
            ${depth ? '<span class="tree-elbow"></span>' : ''}
            <span class="tree-row-icon"><i data-lucide="${active ? 'folder-open' : 'folder'}"></i></span>
            <span class="tree-row-name">${escapeHtml(folder.name || '文件夹')}</span>
            <span class="tree-row-count">${localFolderTotal(folder)}</span>
        </button>
        ${(folder.children || []).length ? `<div class="tree-children">${folder.children.map(child => renderLocalFolderBranch(child, depth + 1)).join('')}</div>` : ''}
    </div>`;
}
function folderContainsLocalActive(folder){
    if(!folder) return false;
    if(folder.id === activeLocalFolderId) return true;
    return (folder.children || []).some(child => folderContainsLocalActive(child));
}
function renderLocalCard(item){
    const hasCaption = localItemKind(item) === 'image' && String(item.caption || '').trim();
    return `<article class="asset-card ${item.id === selectedLocalId ? 'active' : ''}" data-local-card="${escapeAttr(item.id)}">
        <input class="asset-card-check" type="checkbox" data-local-check="${escapeAttr(item.id)}" ${selectedLocalIds.has(item.id) ? 'checked' : ''}>
        <div class="asset-thumb">${localAssetThumb(item)}${assetPreviewCue(item)}</div>
        <div class="asset-card-body">
            <div class="asset-card-name" title="${escapeAttr(item.relativePath || item.name || '')}">${escapeHtml(item.name || 'local')}</div>
            <div class="asset-card-meta">${escapeHtml(assetKindLabel(item))} · ${escapeHtml(formatFileSize(item.size))}${hasCaption ? ' · 有提示词' : ''}</div>
        </div>
    </article>`;
}
function renderLocalClipboardBar(){
    if(!localClipboard?.items?.length) return '';
    const modeLabel = localClipboard.mode === 'cut' ? '剪切' : '复制';
    const target = activeAssetCategory();
    return `<div class="asset-clipboard-bar">
        <div class="asset-clipboard-info"><i data-lucide="clipboard"></i><span>${escapeHtml(modeLabel)}了 ${localClipboard.items.length} 个本地素材，目标：${escapeHtml(activeAssetLibrary()?.name || '资产素材')} / ${escapeHtml(target?.name || '未选择分组')}</span></div>
        <div class="asset-tools">
            <button class="asset-btn primary" type="button" data-local-import-clipboard ${target ? '' : 'disabled'}><i data-lucide="clipboard-paste"></i><span>导入到资产素材</span></button>
            <button class="asset-icon-btn" type="button" data-local-clear-clipboard title="清空本地剪贴板"><i data-lucide="x"></i></button>
        </div>
    </div>`;
}
function renderLocalDetail(item){
    if(!item) return `<div class="panel-head"><div class="panel-title"><strong>本地预览</strong><span>选择一个本地素材查看详情</span></div></div><div class="detail-scroll"><div class="detail-empty"><i data-lucide="folder-open"></i><span>暂无可预览素材</span></div></div>`;
    const kind = localItemKind(item);
    const canEditText = kind === 'text';
    const previewIcon = ['video','audio'].includes(kind) ? 'play' : kind === 'text' ? 'file-text' : 'maximize-2';
    const previewTitle = ['video','audio'].includes(kind) ? i18nText('asset.play', '播放') : kind === 'text' ? i18nText('asset.expandText', '展开文本') : i18nText('asset.expandImage', '展开图片');
    return `
        <div class="panel-head">
            <div class="panel-title"><strong>本地预览</strong><span>${escapeHtml(assetKindLabel(item))}</span></div>
            <div class="panel-actions">
                <button class="asset-icon-btn" type="button" data-local-preview="${escapeAttr(item.id)}" title="${previewTitle}"><i data-lucide="${previewIcon}"></i></button>
                ${canEditText ? `<button class="asset-icon-btn" type="button" data-text-edit="local:${escapeAttr(item.id)}" title="编辑文本内容" data-i18n-title="asset.editText"><i data-lucide="pencil-line"></i></button>` : ''}
                <button class="asset-btn primary" type="button" data-local-import-one="${escapeAttr(item.id)}"><i data-lucide="download"></i><span>导入</span></button>
            </div>
        </div>
        <div class="detail-scroll">
            <div class="detail-media"><button class="detail-media-frame detail-media-zoomable" type="button" data-local-preview="${escapeAttr(item.id)}" title="${previewTitle}">${localAssetThumb(item)}</button></div>
            <div class="detail-body">
                <div class="detail-name">${escapeHtml(item.name || '本地素材')}</div>
                <div class="detail-meta-grid">
                    <div class="detail-meta"><span>类型</span><strong>${escapeHtml(assetKindLabel(item))}</strong></div>
                    <div class="detail-meta"><span>大小</span><strong>${escapeHtml(formatFileSize(item.size))}</strong></div>
                    <div class="detail-meta"><span>修改时间</span><strong>${escapeHtml(formatDate(item.lastModified))}</strong></div>
                    <div class="detail-meta"><span>来源</span><strong>${escapeHtml(activeSharedFolderName || '共享文件夹')}</strong></div>
                </div>
                <div class="detail-url">${escapeHtml(item.relativePath || item.name || '')}</div>
            </div>
        </div>
    `;
}
function refreshLocalSelectionOnly(){
    document.querySelectorAll('[data-local-card]').forEach(card => {
        card.classList.toggle('active', card.dataset.localCard === selectedLocalId);
    });
    document.querySelectorAll('[data-local-check]').forEach(input => {
        input.checked = selectedLocalIds.has(input.dataset.localCheck);
    });
    const detail = root.querySelector('.asset-detail');
    if(detail){
        detail.innerHTML = renderLocalDetail(findLocalItem(selectedLocalId));
        refreshIcons();
    }
}
function renderAssetManager(){
    normalizeAssetState();
    const libs = assetLibraries();
    const cats = assetCategories();
    const lib = activeAssetLibrary();
    const cat = activeAssetCategory();
    const items = currentAssetItems();
    const detail = selectedAsset();
    const imageCount = selectedAssetImageItems().length;
    root.innerHTML = `
        <aside class="asset-panel asset-nav">
            <div class="panel-head">
                <div class="panel-title"><strong>资产层级</strong><span>先选库，再选分组</span></div>
                <div class="panel-actions compact-actions">
                    ${assetTreeEdit?.placement === 'head' ? '' : '<button class="asset-icon-btn" type="button" data-asset-lib-new title="新建资产库"><i data-lucide="plus"></i></button>'}
                    ${renderHeadTreeInlineEdit(assetTreeEdit, 'assetTreeEditInput', 'data-asset-tree-edit-save', 'data-asset-tree-edit-cancel')}
                </div>
            </div>
            <div class="nav-scroll">
                <div class="nav-tree">
                    ${libs.map(item => renderAssetTreeBranch(item)).join('')}
                </div>
            </div>
        </aside>
        <section class="asset-panel asset-content ${assetManageMode ? 'manage-on' : ''}">
            <div class="content-toolbar">
                <div class="content-heading">
                    <strong>${escapeHtml(assetViewTitle())}</strong>
                    <span>${assetViewSubtitle(items)}</span>
                </div>
                <div class="asset-tools">
                    <label class="asset-search-wrap"><i data-lucide="search"></i><input id="assetSearch" class="asset-search" type="search" value="${escapeAttr(assetQuery)}" placeholder="搜索素材"></label>
                    <button class="asset-btn ${assetManageMode ? 'primary' : ''}" type="button" data-asset-manage><i data-lucide="list-checks"></i><span>${assetManageMode ? '完成管理' : '批量管理'}</span></button>
                </div>
            </div>
            ${renderAssetClipboardBar()}
            ${renderLocalClipboardBar()}
            <div class="manage-tools">
                <div class="manage-group manage-select-group">
                    <span class="manage-group-title">管理</span>
                    <span class="manage-summary">已选 ${selectedAssetIds.size} 个，其中 ${imageCount} 张图片</span>
                    <div class="asset-tools">
                        ${renderSelectToggle("asset", items, selectedAssetIds)}
                        <button class="asset-btn" type="button" data-asset-download-selected ${selectedAssetIds.size ? '' : 'disabled'}><i data-lucide="download"></i><span>下载所选</span></button>
                        <button class="asset-btn danger" type="button" data-asset-delete-selected ${selectedAssetIds.size ? '' : 'disabled'}><i data-lucide="trash-2"></i><span>删除所选</span></button>
                    </div>
                </div>

            </div>
            <div class="content-scroll">
                <div class="asset-grid">
                    ${renderUploadCard(cat)}
                    ${items.map(item => renderAssetCard(item)).join('')}
                    ${items.length ? '' : '<div class="empty-state">当前分组还没有素材，可以上传，或从智能画布输出保存到素材库。</div>'}
                </div>
            </div>
        </section>
        <aside class="asset-panel asset-detail">
            ${renderAssetDetail(detail)}
        </aside>
    `;
}
function renderWorkflowManager(){
    normalizeWorkflowState();
    const cats = workflowCategories();
    const cat = activeWorkflowCategory();
    const items = currentWorkflowItems();
    const detail = selectedWorkflow();
    root.innerHTML = `
        <aside class="asset-panel asset-nav">
            <div class="panel-head">
                <div class="panel-title"><strong>工作流层级</strong><span>独立管理工作流分组</span></div>
                <div class="panel-actions compact-actions">
                    ${workflowTreeEdit?.placement === 'head' ? '' : '<button class="asset-icon-btn" type="button" data-workflow-cat-new title="新建工作流分组"><i data-lucide="folder-plus"></i></button>'}
                    ${renderHeadTreeInlineEdit(workflowTreeEdit, 'workflowTreeEditInput', 'data-workflow-tree-edit-save', 'data-workflow-tree-edit-cancel')}
                </div>
            </div>
            <div class="nav-scroll">
                <div class="nav-tree">
                    <div class="tree-branch expanded">
                        <button class="tree-row tree-parent contains-active" type="button" data-workflow-root>
                            <span class="tree-row-icon"><i data-lucide="folder-open"></i></span>
                            <span class="tree-row-name">工作流库</span>
                            <span class="tree-row-count">${workflowCount()}</span>
                        </button>
                        <div class="tree-children">
                            ${cats.length ? cats.map(c => {
                                const active = c.id === activeWorkflowCategoryId && c.__libraryId === activeWorkflowLibraryId;
                                return `<button class="tree-row tree-child ${active ? 'active' : ''}" type="button" data-workflow-cat="${escapeAttr(c.id)}" data-workflow-cat-lib="${escapeAttr(c.__libraryId || '')}">
                                <span class="tree-elbow"></span>
                                <span class="tree-row-icon"><i data-lucide="workflow"></i></span>
                                <span class="tree-row-name">${escapeHtml(c.name || '工作流')}</span>
                                <span class="tree-row-count">${(c.items || []).length}</span>
                            </button>${active ? renderWorkflowTreeActionBar() : ''}`;
                            }).join('') : '<div class="tree-empty">暂无工作流分组</div>'}
                        </div>
                    </div>
                </div>
            </div>
        </aside>
        <section class="asset-panel asset-content ${workflowManageMode ? 'manage-on' : ''}">
            <div class="content-toolbar">
                <div class="content-heading">
                    <strong>${escapeHtml(cat?.name || '画布工作流')}</strong>
                    <span>工作流库 / ${items.length} 个工作流</span>
                </div>
                <div class="asset-tools">
                    <label class="asset-search-wrap"><i data-lucide="search"></i><input id="workflowSearch" class="asset-search" type="search" value="${escapeAttr(workflowQuery)}" placeholder="搜索工作流"></label>
                    <button class="asset-btn ${workflowManageMode ? 'primary' : ''}" type="button" data-workflow-manage><i data-lucide="list-checks"></i><span>${workflowManageMode ? '完成管理' : '批量管理'}</span></button>
                </div>
            </div>
            <div class="manage-tools">
                <span>已选择 ${selectedWorkflowIds.size} 个工作流。</span>
                <div class="asset-tools">
                    ${renderSelectToggle("workflow", items, selectedWorkflowIds)}
                    <button class="asset-btn" type="button" data-workflow-export-selected ${selectedWorkflowIds.size ? '' : 'disabled'}><i data-lucide="download"></i><span>导出所选</span></button>
                    <button class="asset-btn danger" type="button" data-workflow-delete-selected ${selectedWorkflowIds.size ? '' : 'disabled'}><i data-lucide="trash-2"></i><span>删除所选</span></button>
                </div>
            </div>
            <div class="content-scroll">
                <div class="asset-grid">
                    ${renderWorkflowUploadCard(cat)}
                    ${items.map(item => renderWorkflowCard(item)).join('')}
                    ${items.length ? '' : '<div class="empty-state">当前分组还没有工作流，可以上传 JSON / ZIP，或从传统画布导出到资产库。</div>'}
                </div>
            </div>
        </section>
        <aside class="asset-panel asset-detail">
            ${renderWorkflowDetail(detail)}
        </aside>
    `;
}
function renderWorkflowUploadCard(cat){
    return `<button id="workflowDrop" class="upload-grid-card" type="button" data-workflow-upload ${!cat ? 'disabled' : ''}>
        <span class="upload-thumb"><i data-lucide="upload-cloud"></i></span>
        <span class="upload-body">
            <strong>上传工作流</strong>
            <small>支持 JSON / ZIP</small>
        </span>
    </button>`;
}
function renderWorkflowTreeActionBar(){
    const editHtml = renderWorkflowTreeInlineEdit();
    if(editHtml) return editHtml;
    const deleteKey = `workflow-cat:${activeWorkflowLibraryId}:${activeWorkflowCategoryId}`;
    return `<div class="tree-action-bar child-actions">
        <button type="button" data-workflow-cat-rename><i data-lucide="pencil"></i><span data-i18n="asset.rename">重命名</span></button>
        <button type="button" class="danger ${pendingTreeDelete === deleteKey ? 'detail-confirm' : ''}" data-workflow-cat-delete><i data-lucide="trash-2"></i><span>${pendingTreeDelete === deleteKey ? '确认删除' : '删除'}</span></button>
    </div>`;
}
function renderWorkflowTreeInlineEdit(){
    if(!workflowTreeEdit || workflowTreeEdit.placement === 'head') return '';
    if(workflowTreeEdit.kind !== 'category-rename') return '';
    const label = workflowTreeEdit.label || '名称';
    return `<div class="tree-inline-edit child-actions">
        <input id="workflowTreeEditInput" type="text" value="${escapeAttr(workflowTreeEdit.value || '')}" placeholder="${escapeAttr(label)}">
        <button type="button" class="primary" data-workflow-tree-edit-save><i data-lucide="check"></i><span>保存</span></button>
        <button type="button" data-workflow-tree-edit-cancel><i data-lucide="x"></i><span>取消</span></button>
    </div>`;
}
function renderWorkflowCard(item){
    return `<article class="asset-card workflow-card ${item.id === selectedWorkflowId ? 'active' : ''}" data-workflow-card="${escapeAttr(item.id)}">
        <input class="asset-card-check" type="checkbox" data-workflow-check="${escapeAttr(item.id)}" ${selectedWorkflowIds.has(item.id) ? 'checked' : ''}>
        <div class="asset-thumb">${workflowThumb(item)}</div>
        <div class="asset-card-body">
            <div class="asset-card-name" title="${escapeAttr(item.name || '')}">${escapeHtml(item.name || 'workflow')}</div>
            <div class="asset-card-meta">${escapeHtml(workflowKindLabel(item))} · ${escapeHtml(formatDate(item.created_at))}</div>
        </div>
    </article>`;
}
function renderWorkflowDetail(item){
    if(!item) return `<div class="panel-head"><div class="panel-title"><strong>工作流详情</strong><span>选择一个工作流查看详情</span></div></div><div class="detail-scroll"><div class="detail-empty"><i data-lucide="workflow"></i><span>暂无工作流</span></div></div>`;
    return `
        <div class="panel-head">
            <div class="panel-title"><strong>工作流详情</strong><span>${escapeHtml(workflowKindLabel(item))}</span></div>
            <div class="panel-actions">
                <button class="asset-icon-btn" type="button" data-workflow-download="${escapeAttr(item.id)}" title="导出工作流"><i data-lucide="download"></i></button>
                <button class="asset-icon-btn" type="button" data-workflow-rename="${escapeAttr(item.id)}" title="编辑名称" data-i18n-title="asset.rename"><i data-lucide="pencil"></i></button>
                <button class="asset-icon-btn danger ${pendingDeleteAssetId === item.id ? 'detail-confirm' : ''}" type="button" data-workflow-delete="${escapeAttr(item.id)}" title="${pendingDeleteAssetId === item.id ? '再次点击确认删除' : '删除'}"><i data-lucide="trash-2"></i></button>
            </div>
        </div>
        <div class="detail-scroll">
            <div class="detail-media"><div class="detail-media-frame">${workflowThumb(item)}</div></div>
            <div class="detail-body">
                <input class="detail-name-input" data-workflow-inline-name="${escapeAttr(item.id)}" type="text" value="${escapeAttr(item.name || 'workflow')}" title="直接修改名称">
                <div class="detail-meta-grid">
                    <div class="detail-meta"><span>类型</span><strong>${escapeHtml(workflowKindLabel(item))}</strong></div>
                    <div class="detail-meta"><span>创建时间</span><strong>${escapeHtml(formatDate(item.created_at))}</strong></div>
                    <div class="detail-meta"><span>位置</span><strong>工作流库</strong></div>
                    <div class="detail-meta"><span>分组</span><strong>${escapeHtml(activeWorkflowCategory()?.name || '工作流')}</strong></div>
                </div>
                <div class="detail-url">${escapeHtml(item.url || '')}</div>
            </div>
        </div>
    `;
}
function renderUploadCard(cat){
    return `<button id="assetDrop" class="upload-grid-card" type="button" data-asset-upload ${!cat ? 'disabled' : ''}>
        <span class="upload-thumb"><i data-lucide="upload-cloud"></i></span>
        <span class="upload-body">
            <strong>上传到当前分组</strong>
            <small>拖入文件或点击上传</small>
        </span>
    </button>`;
}
function renderAssetClipboardBar(){
    if(!assetClipboard?.ids?.length) return '';
    const modeLabel = assetClipboard.mode === 'cut' ? '剪切' : '复制';
    const sameTarget = assetClipboard.sourceLibraryId === activeAssetLibraryId && assetClipboard.sourceCategoryId === activeAssetCategoryId;
    const pasteText = sameTarget && assetClipboard.mode === 'cut' ? '选择其他分组后粘贴' : '粘贴到当前分组';
    return `<div class="asset-clipboard-bar">
        <div class="asset-clipboard-info"><i data-lucide="clipboard"></i><span>${escapeHtml(modeLabel)}了 ${assetClipboard.ids.length} 个素材</span></div>
        <div class="asset-tools">
            <button class="asset-btn primary" type="button" data-asset-paste-clipboard ${sameTarget && assetClipboard.mode === 'cut' ? 'disabled' : ''}><i data-lucide="clipboard-paste"></i><span>${escapeHtml(pasteText)}</span></button>
            <button class="asset-icon-btn" type="button" data-asset-clear-clipboard title="清空剪贴板"><i data-lucide="x"></i></button>
        </div>
    </div>`;
}
function renderAssetTreeBranch(lib){
    const isActiveLib = lib.id === activeAssetLibraryId;
    const cats = (lib.categories || []).filter(cat => (cat.type || 'image') === 'image');
    const showLibActions = isActiveLib && assetTreeFocus === 'library';
    return `<div class="tree-branch ${isActiveLib ? 'expanded' : ''}">
        <button class="tree-row tree-parent ${isActiveLib ? 'contains-active' : ''} ${showLibActions ? 'active' : ''}" type="button" data-asset-lib="${escapeAttr(lib.id)}">
            <span class="tree-row-icon"><i data-lucide="${isActiveLib ? 'folder-open' : 'folder'}"></i></span>
            <span class="tree-row-name">${escapeHtml(lib.name || '资产库')}</span>
            <span class="tree-row-count">${assetCountForLibrary(lib)}</span>
        </button>
        ${showLibActions ? renderAssetTreeActionBar('library') : ''}
        <div class="tree-children">
            ${cats.length ? cats.map(cat => `<button class="tree-row tree-child ${isActiveLib && cat.id === activeAssetCategoryId && assetTreeFocus === 'category' ? 'active' : ''}" type="button" data-asset-cat="${escapeAttr(cat.id)}" data-asset-cat-lib="${escapeAttr(lib.id)}">
                <span class="tree-elbow"></span>
                <span class="tree-row-icon"><i data-lucide="image"></i></span>
                <span class="tree-row-name">${escapeHtml(cat.name || '分组')}</span>
                <span class="tree-row-count">${(cat.items || []).length}</span>
            </button>${isActiveLib && cat.id === activeAssetCategoryId && assetTreeFocus === 'category' ? renderAssetTreeActionBar('category') : ''}`).join('') : '<div class="tree-empty">暂无分组</div>'}

        </div>
    </div>`;
}
function renderAssetTreeActionBar(kind){
    const editHtml = renderAssetTreeInlineEdit(kind);
    if(editHtml) return editHtml;
    const deleteKey = kind === 'library' ? `asset-lib:${activeAssetLibraryId}` : `asset-cat:${activeAssetCategoryId}`;
    if(kind === 'library'){
        const isDefaultLibrary = activeAssetLibraryId === 'default';
        return `<div class="tree-action-bar library-actions">
            <button type="button" data-asset-cat-new><i data-lucide="folder-plus"></i><span data-i18n="asset.newGroup">新分组</span></button>
            <button type="button" data-asset-lib-rename><i data-lucide="pencil"></i><span data-i18n="asset.rename">重命名</span></button>
            ${isDefaultLibrary ? '' : `<button type="button" class="danger ${pendingTreeDelete === deleteKey ? 'detail-confirm' : ''}" data-asset-lib-delete><i data-lucide="trash-2"></i><span>${pendingTreeDelete === deleteKey ? '确认删除' : '删除库'}</span></button>`}
        </div>`;
    }
    return `<div class="tree-action-bar child-actions">
        <button type="button" data-asset-cat-rename><i data-lucide="pencil"></i><span data-i18n="asset.rename">重命名</span></button>
        <button type="button" class="danger ${pendingTreeDelete === deleteKey ? 'detail-confirm' : ''}" data-asset-cat-delete><i data-lucide="trash-2"></i><span>${pendingTreeDelete === deleteKey ? '确认删除' : '删除'}</span></button>
    </div>`;
}
function renderAssetTreeInlineEdit(kind){
    if(!assetTreeEdit) return '';
    if(assetTreeEdit.placement === 'head') return '';
    const expectedKinds = kind === 'library'
        ? ['library-new', 'library-rename', 'category-new']
        : ['category-rename'];
    if(!expectedKinds.includes(assetTreeEdit.kind)) return '';
    const label = assetTreeEdit.label || '名称';
    return `<div class="tree-inline-edit ${kind === 'category' ? 'child-actions' : 'library-actions'}">
        <input id="assetTreeEditInput" type="text" value="${escapeAttr(assetTreeEdit.value || '')}" placeholder="${escapeAttr(label)}">
        <button type="button" class="primary" data-asset-tree-edit-save><i data-lucide="check"></i><span>保存</span></button>
        <button type="button" data-asset-tree-edit-cancel><i data-lucide="x"></i><span>取消</span></button>
    </div>`;
}
function renderAssetCard(item){
    const parts = materialNameParts(item);
    return `<article class="asset-card ${item.id === selectedAssetId ? 'active' : ''}" data-asset-card="${escapeAttr(item.id)}">
        <input class="asset-card-check" type="checkbox" data-asset-check="${escapeAttr(item.id)}" ${selectedAssetIds.has(item.id) ? 'checked' : ''}>
        <div class="asset-thumb">${assetThumb(item)}${assetPreviewCue(item)}</div>
        <div class="asset-card-body">
            <div class="asset-card-name" data-asset-rename="${escapeAttr(item.id)}" title="${escapeAttr(parts.fullName)}">${escapeHtml(parts.fullName)}</div>
            <div class="asset-card-meta">${escapeHtml(assetKindLabel(item))} · ${escapeHtml(formatDate(item.created_at))}</div>
        </div>
    </article>`;
}
function renderAssetDetail(item){
    if(!item) return `<div class="panel-head"><div class="panel-title"><strong>素材预览</strong><span>选择一个素材查看详情</span></div></div><div class="detail-scroll"><div class="detail-empty"><i data-lucide="image"></i><span>暂无可预览素材</span></div></div>`;
    const kind = assetKind(item);
    const isImage = kind === 'image';
    const canEditText = kind === 'text';
    const previewIcon = ['video','audio'].includes(kind) ? 'play' : kind === 'text' ? 'file-text' : 'maximize-2';
    const previewTitle = ['video','audio'].includes(kind) ? i18nText('asset.play', '播放') : kind === 'text' ? i18nText('asset.expandText', '展开文本') : i18nText('asset.expandImage', '展开图片');
    if(assetEditMode && item.id === selectedAssetId){
        return `
            <div class="panel-head">
                <div class="panel-title"><strong>编辑素材</strong><span>当前分组内直接保存</span></div>
                <div class="panel-actions">
                    <button class="asset-btn primary" type="button" data-asset-edit-save="${escapeAttr(item.id)}"><i data-lucide="check"></i><span>保存</span></button>
                    <button class="asset-icon-btn" type="button" data-asset-edit-cancel title="取消"><i data-lucide="x"></i></button>
                </div>
            </div>
            <div class="detail-scroll">
                <div class="detail-media"><button class="detail-media-frame detail-media-zoomable" type="button" data-asset-preview="${escapeAttr(item.id)}" title="${previewTitle}">${assetThumb(item)}</button></div>
                <div class="inline-edit-form">
                    <label class="inline-edit-field"><span>素材名称</span><input id="assetEditName" type="text" value="${escapeAttr(item.name || '')}" placeholder="素材名称"></label>
                    <div class="detail-meta-grid">
                        <div class="detail-meta"><span>类型</span><strong>${escapeHtml(assetKindLabel(item))}</strong></div>
                        <div class="detail-meta"><span>创建时间</span><strong>${escapeHtml(formatDate(item.created_at))}</strong></div>
                    </div>
                    <div class="detail-url">${escapeHtml(item.url || '')}</div>
                </div>
            </div>
        `;
    }
    return `
        <div class="panel-head">
            <div class="panel-title"><strong>素材预览</strong><span>${escapeHtml(assetKindLabel(item))}</span></div>
            <div class="panel-actions">
                <button class="asset-icon-btn" type="button" data-asset-preview="${escapeAttr(item.id)}" title="${previewTitle}"><i data-lucide="${previewIcon}"></i></button>
                ${canEditText ? `<button class="asset-icon-btn" type="button" data-text-edit="asset:${escapeAttr(item.id)}" title="编辑文本内容" data-i18n-title="asset.editText"><i data-lucide="pencil-line"></i></button>` : ''}
                <button class="asset-icon-btn" type="button" data-asset-download="${escapeAttr(item.id)}" title="下载素材" data-i18n-title="asset.download"><i data-lucide="download"></i></button>
                <button class="asset-icon-btn" type="button" data-asset-rename="${escapeAttr(item.id)}" title="编辑名称" data-i18n-title="asset.rename"><i data-lucide="pencil"></i></button>
                <button class="asset-icon-btn danger ${pendingDeleteAssetId === item.id ? 'detail-confirm' : ''}" type="button" data-asset-delete="${escapeAttr(item.id)}" title="${pendingDeleteAssetId === item.id ? '再次点击确认删除' : '删除'}"><i data-lucide="trash-2"></i></button>
            </div>
        </div>
        <div class="detail-scroll">
            <div class="detail-media"><button class="detail-media-frame detail-media-zoomable" type="button" data-asset-preview="${escapeAttr(item.id)}" title="${previewTitle}">${assetThumb(item)}</button></div>
            <div class="detail-body">
                ${renderMaterialNameEditor(item, 'data-asset-inline-name', item.id)}
                <div class="detail-meta-grid">
                    <div class="detail-meta"><span>类型</span><strong>${escapeHtml(assetKindLabel(item))}</strong></div>
                    <div class="detail-meta"><span>创建时间</span><strong>${escapeHtml(formatDate(item.created_at))}</strong></div>
                    <div class="detail-meta"><span>资产库</span><strong>${escapeHtml(activeAssetLibrary()?.name || '资产库')}</strong></div>
                    <div class="detail-meta"><span>分组</span><strong>${escapeHtml(activeAssetCategory()?.name || '分组')}</strong></div>
                </div>
                <div class="detail-url">${escapeHtml(item.url || '')}</div>
            </div>
        </div>
    `;
}
function refreshAssetSelectionOnly(){
    document.querySelectorAll('[data-asset-card]').forEach(card => {
        card.classList.toggle('active', card.dataset.assetCard === selectedAssetId);
    });
    document.querySelectorAll('[data-asset-check]').forEach(input => {
        input.checked = selectedAssetIds.has(input.dataset.assetCheck);
    });
    const detail = root.querySelector('.asset-detail');
    if(detail){
        detail.innerHTML = renderAssetDetail(selectedAsset());
        refreshIcons();
    }
}
function renderPromptManager(){
    normalizePromptState();
    const libs = promptLibraries();
    const lib = activePromptLibrary();
    const readonly = Boolean(lib?.readonly);
    const cats = activePromptCategories();
    const items = currentPromptItems();
    const detail = promptCreateMode ? null : selectedPrompt();
    const promptEmptyText = (lib?.items || []).length
        ? `当前条件下没有提示词。可以切换分类或清空搜索条件。`
        : `${lib?.name || '当前提示词库'} 暂无提示词，点击「新增」添加。`;
    root.innerHTML = `
        <aside class="asset-panel asset-nav">
            <div class="panel-head">
                <div class="panel-title"><strong>提示词库</strong><span>可创建多个词库</span></div>
                <div class="panel-actions compact-actions">
                    ${promptTreeEdit?.placement === 'head' ? '' : '<button class="asset-icon-btn" type="button" data-prompt-lib-new title="新建提示词库"><i data-lucide="plus"></i></button>'}
                    ${renderHeadTreeInlineEdit(promptTreeEdit, 'promptTreeEditInput', 'data-prompt-tree-edit-save', 'data-prompt-tree-edit-cancel')}
                </div>
            </div>
            <div class="nav-scroll">
                <div class="nav-tree">
                    ${libs.map(item => renderPromptTreeBranch(item)).join('')}
                </div>
            </div>
        </aside>
        <section class="asset-panel asset-content ${promptManageMode ? 'manage-on' : ''}">
            <div class="content-toolbar">
                <div class="content-heading">
                    <strong>${escapeHtml(lib?.name || '提示词库')}</strong>
                    <span>共 ${items.length} 条提示词</span>
                </div>
                <div class="asset-tools">
                    <label class="asset-search-wrap"><i data-lucide="search"></i><input id="promptSearch" class="asset-search" type="search" value="${escapeAttr(promptQuery)}" placeholder="搜索名称、说明或正文"></label>
                    <button class="asset-btn primary" type="button" data-prompt-new ${readonly ? 'disabled' : ''}><i data-lucide="file-plus-2"></i><span>新增</span></button>
                    <button class="asset-btn ${promptManageMode ? 'primary' : ''}" type="button" data-prompt-manage><i data-lucide="list-checks"></i><span>${promptManageMode ? '完成管理' : '批量管理'}</span></button>
                </div>
            </div>
            <div class="manage-tools">
                <span>已选择 ${selectedPromptIds.size} 条提示词，支持拖拽框选或逐个勾选。</span>
                <div class="asset-tools">
                    ${renderSelectToggle("prompt", items, selectedPromptIds)}
                    <button class="asset-btn danger" type="button" data-prompt-delete-selected ${readonly || !selectedPromptIds.size ? 'disabled' : ''}><i data-lucide="trash-2"></i><span>删除所选</span></button>
                </div>
            </div>
            <div class="content-scroll">
                ${items.length ? `<div class="prompt-list">${items.map(item => renderPromptRow(item, readonly)).join('')}</div>` : `<div class="empty-state">${escapeHtml(promptEmptyText)}</div>`}
            </div>
        </section>
        <aside class="asset-panel asset-detail">
            ${renderPromptDetail(detail, readonly)}
        </aside>
    `;
}
function renderPromptTreeBranch(lib){
    const isActiveLib = lib.id === activePromptLibraryId;
    // 每个库渲染自己的分类，不再回退到激活库/系统库的分类（修复新库错显系统分类）。
    const cats = promptCategoriesFor(lib);
    const libId = escapeAttr(lib.id);
    const readonly = Boolean(lib.readonly);
    const showLibActions = isActiveLib && promptTreeFocus === 'library';
    return `<div class="tree-branch ${isActiveLib ? 'expanded' : ''}">
        <button class="tree-row tree-parent ${isActiveLib ? 'contains-active' : ''} ${showLibActions ? 'active' : ''}" type="button" data-prompt-lib="${libId}">
            <span class="tree-row-icon"><i data-lucide="${lib.id === 'system' ? 'sparkles' : 'book-open'}"></i></span>
            <span class="tree-row-name">${escapeHtml(lib.name || '提示词库')}</span>
            <span class="tree-row-count">${(lib.items || []).length}</span>
        </button>
        ${showLibActions ? renderPromptTreeActionBar('library') : ''}
        <div class="tree-children">
            <button class="tree-row tree-child ${isActiveLib && activePromptCategory === 'all' && promptTreeFocus === 'category' ? 'active' : ''}" type="button" data-prompt-cat="all" data-prompt-cat-lib="${libId}">
                <span class="tree-elbow"></span>
                <span class="tree-row-icon"><i data-lucide="layout-list"></i></span>
                <span class="tree-row-name">全部提示词</span>
                <span class="tree-row-count">${promptCountForCategory('all', lib)}</span>
            </button>
            ${cats.map(cat => {
                const active = isActiveLib && cat.id === activePromptCategory && promptTreeFocus === 'category';
                const protectedCategory = cat.id === PROMPT_UNCATEGORIZED_CATEGORY_ID;
                return `<button class="tree-row tree-child ${active ? 'active' : ''}" type="button" data-prompt-cat="${escapeAttr(cat.id)}" data-prompt-cat-lib="${libId}">
                <span class="tree-elbow"></span>
                <span class="tree-row-icon"><i data-lucide="${protectedCategory ? 'lock' : 'tag'}"></i></span>
                <span class="tree-row-name">${escapeHtml(cat.name || promptCategoryLabel(cat.id))}</span>
                <span class="tree-row-count">${promptCountForCategory(cat.id, lib)}</span>
            </button>${active ? renderPromptTreeActionBar('category') : ''}`;
            }).join('')}
        </div>
    </div>`;
}
function renderPromptTreeActionBar(kind){
    const editHtml = renderPromptTreeInlineEdit(kind);
    if(editHtml) return editHtml;
    if(kind === 'library'){
        const lib = activePromptLibrary();
        const isSystem = isSystemPromptLibrary(lib);
        const deleteKey = `prompt-lib:${lib?.id || ''}`;
        return `<div class="tree-action-bar library-actions">
            <button type="button" data-prompt-cat-new><i data-lucide="folder-plus"></i><span data-i18n="asset.newGroup">新分组</span></button>
            <button type="button" data-prompt-lib-rename><i data-lucide="pencil"></i><span data-i18n="asset.rename">重命名</span></button>
            ${isSystem ? '' : `<button type="button" class="danger" data-prompt-lib-delete><i data-lucide="trash-2"></i><span>删除库</span></button>`}
        </div>`;
    }
    if(activePromptCategory === 'all'){
        return `<div class="tree-action-bar child-actions muted-actions"><span><i data-lucide="lock"></i>请选择具体分组后编辑</span></div>`;
    }
    if(activePromptCategory === PROMPT_UNCATEGORIZED_CATEGORY_ID){
        return `<div class="tree-action-bar child-actions muted-actions"><span><i data-lucide="lock"></i>未分类不可删除或重命名</span></div>`;
    }
    return `<div class="tree-action-bar child-actions">
        <button type="button" data-prompt-cat-rename><i data-lucide="pencil"></i><span data-i18n="asset.rename">重命名</span></button>
        <button type="button" class="danger" data-prompt-cat-delete><i data-lucide="trash-2"></i><span>删除</span></button>
    </div>`;
}
function renderPromptTreeInlineEdit(kind){
    if(!promptTreeEdit) return '';
    if(promptTreeEdit.placement === 'head') return '';
    const expectedKinds = kind === 'library' ? ['library-new', 'library-rename', 'category-new'] : ['category-rename'];
    if(!expectedKinds.includes(promptTreeEdit.kind)) return '';
    const label = promptTreeEdit.label || '名称';
    return `<div class="tree-inline-edit ${kind === 'category' ? 'child-actions' : 'library-actions'}">
        <input id="promptTreeEditInput" type="text" value="${escapeAttr(promptTreeEdit.value || '')}" placeholder="${escapeAttr(label)}">
        <button type="button" class="primary" data-prompt-tree-edit-save><i data-lucide="check"></i><span>保存</span></button>
        <button type="button" data-prompt-tree-edit-cancel><i data-lucide="x"></i><span>取消</span></button>
    </div>`;
}
function renderPromptRow(item, readonly){
    return `<article class="prompt-row ${item.id === selectedPromptId ? 'active' : ''}" data-prompt-row="${escapeAttr(item.id)}">
        <input class="prompt-row-check" type="checkbox" data-prompt-check="${escapeAttr(item.id)}" ${selectedPromptIds.has(item.id) ? 'checked' : ''} ${readonly ? 'disabled' : ''}>
        <div class="prompt-row-main">
            <div class="prompt-row-title"><strong>${escapeHtml(item.name || '提示词')}</strong><span class="prompt-tag">${escapeHtml(promptCategoryLabel(item.category || PROMPT_UNCATEGORIZED_CATEGORY_ID))}</span></div>
            <div class="prompt-row-scene">${escapeHtml(item.scene || '未填写用途说明')}</div>
            <div class="prompt-row-text">${escapeHtml(item.positive || '')}</div>
        </div>
    </article>`;
}
function renderPromptDetail(item, readonly){
    if(promptCreateMode && !readonly){
        return `
            <div class="panel-head">
                <div class="panel-title"><strong>新增提示词</strong><span>保存到当前提示词库</span></div>
                <div class="panel-actions">
                    <button class="asset-btn primary" type="button" data-prompt-create-save><i data-lucide="check"></i><span>保存</span></button>
                    <button class="asset-icon-btn" type="button" data-prompt-edit-cancel title="取消"><i data-lucide="x"></i></button>
                </div>
            </div>
            <div class="detail-scroll">
                <div class="inline-edit-form">
                    <label class="inline-edit-field"><span>名称</span><input id="promptEditName" type="text" value="" placeholder="提示词名称"></label>
                    <label class="inline-edit-field"><span>用途说明</span><textarea id="promptEditScene" placeholder="用途说明"></textarea></label>
                    <label class="inline-edit-field"><span>正向提示词</span><textarea id="promptEditPositive" placeholder="正向提示词"></textarea></label>
                    <label class="inline-edit-field"><span>负向提示词</span><textarea id="promptEditNegative" placeholder="负向提示词"></textarea></label>
                </div>
            </div>
        `;
    }
    if(!item) return `<div class="panel-head"><div class="panel-title"><strong>提示词预览</strong><span>选择一条提示词查看全文</span></div></div><div class="detail-scroll"><div class="detail-empty"><i data-lucide="text-cursor-input"></i><span>暂无可预览提示词</span></div></div>`;
    if(promptEditMode && item.id === selectedPromptId && !readonly){
        return `
            <div class="panel-head">
                <div class="panel-title"><strong>编辑提示词</strong><span>在当前库内保存</span></div>
                <div class="panel-actions">
                    <button class="asset-btn primary" type="button" data-prompt-edit-save="${escapeAttr(item.id)}"><i data-lucide="check"></i><span>保存</span></button>
                    <button class="asset-icon-btn" type="button" data-prompt-edit-cancel title="取消"><i data-lucide="x"></i></button>
                </div>
            </div>
            <div class="detail-scroll">
                <div class="inline-edit-form">
                    <label class="inline-edit-field"><span>名称</span><input id="promptEditName" type="text" value="${escapeAttr(item.name || '')}" placeholder="提示词名称"></label>
                    <label class="inline-edit-field"><span>用途说明</span><textarea id="promptEditScene" placeholder="用途说明">${escapeHtml(item.scene || '')}</textarea></label>
                    <label class="inline-edit-field"><span>正向提示词</span><textarea id="promptEditPositive" placeholder="正向提示词">${escapeHtml(item.positive || '')}</textarea></label>
                    <label class="inline-edit-field"><span>负向提示词</span><textarea id="promptEditNegative" placeholder="负向提示词">${escapeHtml(item.negative || '')}</textarea></label>
                </div>
            </div>
        `;
    }
    const params = item.params && typeof item.params === 'object' ? Object.entries(item.params) : [];
    return `
        <div class="panel-head">
            <div class="panel-title"><strong>提示词预览</strong><span>${escapeHtml(promptCategoryLabel(item.category || PROMPT_UNCATEGORIZED_CATEGORY_ID))}</span></div>
            <div class="panel-actions">
                <button class="asset-icon-btn" type="button" data-prompt-edit-start="${escapeAttr(item.id)}" ${readonly ? 'disabled' : ''} title="编辑"><i data-lucide="pencil"></i></button>
                <button class="asset-icon-btn danger" type="button" data-prompt-delete="${escapeAttr(item.id)}" ${readonly ? 'disabled' : ''} title="删除"><i data-lucide="trash-2"></i></button>
            </div>
        </div>
        <div class="detail-scroll">
            <div class="prompt-detail-head">
                <div class="prompt-detail-title">${escapeHtml(item.name || '提示词')}</div>
                <div class="prompt-detail-scene">${escapeHtml(item.scene || '未填写用途说明')}</div>
            </div>
            <section class="prompt-block">
                <div class="prompt-block-head"><span>正向提示词</span><span>${String(item.positive || '').length} 字符</span></div>
                <textarea class="prompt-block-body" readonly spellcheck="false">${escapeHtml(item.positive || '未填写')}</textarea>
            </section>
            <section class="prompt-block">
                <div class="prompt-block-head"><span>负向提示词</span><span>${String(item.negative || '').length} 字符</span></div>
                <textarea class="prompt-block-body negative" readonly spellcheck="false">${escapeHtml(item.negative || '未填写')}</textarea>
            </section>
            ${params.length ? `<div class="params-list">${params.map(([key, value]) => `<div class="param-row"><strong>${escapeHtml(key)}</strong><span>${escapeHtml(value)}</span></div>`).join('')}</div>` : ''}
        </div>
    `;
}
async function uploadFiles(files){
    const cat = activeAssetCategory();
    if(!cat) throw new Error('请先创建图片分组');
    const form = new FormData();
    [...files].forEach(file => form.append('files', file));
    const uploaded = await apiJson('/api/ai/upload', {method:'POST', body:form});
    const items = (uploaded.files || []).filter(file => file?.url).map(file => ({
        library_id:activeAssetLibraryId,
        category_id:activeAssetCategoryId,
        url:file.url,
        name:file.name || 'asset'
    }));
    if(!items.length) throw new Error('没有可保存的素材');
    const data = await apiJson('/api/asset-library/items/batch', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({library_id:activeAssetLibraryId, category_id:activeAssetCategoryId, items})
    });
    assetLibrary = data.library || assetLibrary;
    selectedAssetIds.clear();
    selectedAssetId = data.items?.[0]?.id || selectedAssetId;
    render();
    setStatus(`已上传 ${items.length} 个素材`);
    return {count:items.length, items:data.items || []};
}
async function uploadWorkflowFiles(files){
    const cat = activeWorkflowCategory();
    if(!cat) throw new Error('请先创建工作流分组');
    const list = [...files].filter(file => /\.(json|zip)$/i.test(file.name || '') || ['application/json','application/zip','application/x-zip-compressed'].includes(String(file.type || '').toLowerCase()));
    if(!list.length) throw new Error('没有可上传的工作流文件');
    const form = new FormData();
    form.append('library_id', activeWorkflowLibraryId || '');
    form.append('category_id', activeWorkflowCategoryId || '');
    list.forEach(file => form.append('files', file));
    const data = await apiJson('/api/asset-library/workflows/upload', {method:'POST', body:form});
    assetLibrary = data.library || assetLibrary;
    selectedWorkflowIds.clear();
    selectedWorkflowId = data.items?.[0]?.id || selectedWorkflowId;
    render();
    setStatus(`已上传 ${data.items?.length || 0} 个工作流`);
}
function downloadUrl(url, filename='download'){
    if(!url) return;
    const link = document.createElement('a');
    link.href = url;
    link.download = filename || '';
    link.target = '_blank';
    document.body.appendChild(link);
    link.click();
    link.remove();
}
async function exportWorkflowItems(ids){
    const items = (ids || []).map(id => findWorkflowItem(id)).filter(item => item?.url);
    if(!items.length) return;
    if(items.length === 1){
        const item = items[0];
        const ext = String(item.url || '').toLowerCase().split('?')[0].endsWith('.json') ? '.json' : '.zip';
        downloadUrl(item.url, `${item.name || 'workflow'}${ext}`);
        setStatus('已导出工作流');
        return;
    }
    const res = await fetch('/api/canvas-assets/download', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({filename:'workflows.zip', items:items.map(item => ({url:item.url, name:item.name || 'workflow'}))})
    });
    if(!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '导出工作流失败');
    const blob = await res.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'workflows.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1200);
    setStatus(`已导出 ${items.length} 个工作流`);
}
async function downloadCanvasAssetItems(ids){
    const items = (ids || []).map(id => findCanvasAssetItem(id)).filter(item => item?.url);
    if(!items.length){
        setStatus('没有可下载的生成结果');
        return;
    }
    if(items.length === 1){
        const item = items[0];
        downloadUrl(item.url, item.name || item.display_name || 'generation-result');
        setStatus('已下载生成结果');
        return;
    }
    setStatus(`正在打包 ${items.length} 个生成结果...`);
    const res = await fetch('/api/canvas-assets/download', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({filename:'generation-results.zip', items:items.map(item => ({url:item.url, name:item.name || item.display_name || 'generation-result'}))})
    });
    if(!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '下载生成结果失败');
    const blob = await res.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'generation-results.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1200);
    setStatus(`已下载 ${items.length} 个生成结果`);
}
async function deleteGenerationResults(ids){
    const resultIds = [...new Set((ids || []).filter(id => findCanvasAssetItem(id)))];
    if(!resultIds.length) return;
    const data = await apiJson('/api/results/delete', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({ids:resultIds})
    });
    selectedCanvasAssetIds.clear();
    if(resultIds.includes(selectedCanvasAssetId)) selectedCanvasAssetId = '';
    await refreshCanvasAssets();
    setStatus(`已删除 ${Number(data.removed || 0)} 个生成结果`);
}
function assetDownloadName(item){
    return materialNameParts(item).fullName || 'asset';
}
function downloadAssetItem(id){
    const item = findAssetItem(id);
    if(!item || !item.url){ setStatus('没有可下载的素材'); return; }
    const name = assetDownloadName(item);
    // 走 /api/download-output 强制以附件形式下载（带正确文件名/后缀），而不是在浏览器里打开预览。
    downloadUrl(`/api/download-output?url=${encodeURIComponent(item.url)}&name=${encodeURIComponent(name)}`, name);
    setStatus('已开始下载');
}
const SMART_CANVAS_ASSET_INBOX_KEY = 'smart_canvas_asset_inbox';
const SMART_CANVAS_CLIPBOARD_INTENT_KEY = 'smart_canvas_clipboard_intent';
function canvasInboxAssetFromItem(item){
    const out = {url:item?.url || '', name:item?.name || '素材', kind:item?.kind || ''};
    ['natural_w','natural_h','width','height','w','h','layout_w','layout_h'].forEach(key => {
        const n = Number(item?.[key]);
        if(Number.isFinite(n) && n > 0) out[key] = n;
    });
    return out;
}
function copySelectedAssetsToCanvas(){
    const items = [...selectedAssetIds]
        .map(id => findAssetItem(id))
        .filter(it => it?.url)
        .map(canvasInboxAssetFromItem);
    if(!items.length){ setStatus('没有可复制的素材'); return; }
    try {
        // 跨页复制也更新最近剪贴板意图，旧节点缓存不能盖过这次素材复制。
        const ts = Date.now();
        localStorage.setItem(SMART_CANVAS_ASSET_INBOX_KEY, JSON.stringify({items, ts}));
        localStorage.setItem(SMART_CANVAS_CLIPBOARD_INTENT_KEY, JSON.stringify({kind:'media', source:'asset-library', count:items.length, kinds:[...new Set(items.map(item => item.kind || 'image'))], ts}));
    } catch(err){
        setStatus('复制失败：' + (err?.message || err));
        return;
    }
    setStatus(`已复制 ${items.length} 个素材，去智能画布按 Ctrl+V 粘贴`);
}
async function downloadSelectedAssets(){
    const items = [...selectedAssetIds].map(id => findAssetItem(id)).filter(it => it?.url);
    if(!items.length){ setStatus('没有可下载的素材'); return; }
    if(items.length === 1){ downloadAssetItem(items[0].id); return; }
    setStatus(`正在打包 ${items.length} 个素材...`);
    try {
        const res = await fetch('/api/canvas-assets/download', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({filename:'assets.zip', items:items.map(it => ({url:it.url, name:assetDownloadName(it)}))})
        });
        if(!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '下载失败');
        const blob = await res.blob();
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = 'assets.zip';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 1200);
        setStatus(`已下载 ${items.length} 个素材`);
    } catch(err){
        setStatus(err.message || '下载失败');
    }
}
function downloadLocalUpload(id){
    const item = findLocalUpload(id);
    if(!item || !item.url){ setStatus('没有可下载的素材'); return; }
    const name = assetDownloadName(item);
    downloadUrl(`/api/download-output?url=${encodeURIComponent(item.url)}&name=${encodeURIComponent(name)}`, name);
    setStatus('已开始下载');
}
async function promoteLocalUploadItem(id){
    const item = findLocalUpload(id);
    const materialId = item?.material_id || window.MaterialPromote?.materialIdFromUrl?.(item?.url || '');
    if(!item || !materialId){
        setStatus('这个素材暂时不能收藏');
        return;
    }
    await window.MaterialPromote.open({
        materialId,
        name:item.name || '',
        onSuccess:async data => {
            assetLibrary = data.library || assetLibrary;
            await loadLocalAssets();
            selectedLocalUploadId = '';
            selectedLocalUploadIds.delete(id);
            render();
            setStatus('已收藏到资产素材');
        },
        onError:error => setStatus(error?.message || '收藏失败')
    });
}
async function promoteCanvasAssetItem(id){
    const item = findCanvasAssetItem(id);
    const resultId = item?.id || '';
    if(!item || !resultId){
        setStatus('这个生成结果暂时不能收藏');
        return;
    }
    await window.MaterialPromote.open({
        resultId,
        name:item.name || item.display_name || '',
        onSuccess:async data => {
            assetLibrary = data.library || assetLibrary;
            await refreshCanvasAssets();
            setStatus('已收藏到资产素材');
        },
        onError:error => setStatus(error?.message || '收藏失败')
    });
}
async function downloadSelectedLocalUploads(){
    const items = [...selectedLocalUploadIds].map(id => findLocalUpload(id)).filter(it => it?.url);
    if(!items.length){ setStatus('没有可下载的素材'); return; }
    if(items.length === 1){ downloadLocalUpload(items[0].id); return; }
    setStatus(`正在打包 ${items.length} 个素材...`);
    try {
        const res = await fetch('/api/canvas-assets/download', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({filename:'local-assets.zip', items:items.map(it => ({url:it.url, name:assetDownloadName(it)}))})
        });
        if(!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '下载失败');
        const blob = await res.blob();
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = 'local-assets.zip';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 1200);
        setStatus(`已下载 ${items.length} 个素材`);
    } catch(err){
        setStatus(err.message || '下载失败');
    }
}
function copySelectedLocalUploadsToCanvas(){
    const items = [...selectedLocalUploadIds].map(id => findLocalUpload(id)).filter(it => it?.url).map(canvasInboxAssetFromItem);
    if(!items.length){ setStatus('没有可复制的素材'); return; }
    try {
        const ts = Date.now();
        localStorage.setItem(SMART_CANVAS_ASSET_INBOX_KEY, JSON.stringify({items, ts}));
        localStorage.setItem(SMART_CANVAS_CLIPBOARD_INTENT_KEY, JSON.stringify({kind:'media', source:'asset-library', count:items.length, kinds:[...new Set(items.map(item => item.kind || 'image'))], ts}));
    } catch(err){
        setStatus('复制失败：' + (err?.message || err));
        return;
    }
    setStatus(`已复制 ${items.length} 个素材，去智能画布按 Ctrl+V 粘贴`);
}
function renderLocalUploadClipboardBar(){
    if(!localUploadClipboard?.ids?.length) return '';
    const sameFolder = String(localUploadClipboard.sourceFolder || '') === String(activeLocalUploadFolder || '');
    const hereLabel = activeLocalUploadFolder ? localUploadFolderTitle() : '根目录';
    return `<div class="asset-clipboard-bar">
        <div class="asset-clipboard-info"><i data-lucide="clipboard"></i><span>已剪切 ${localUploadClipboard.ids.length} 个素材</span></div>
        <div class="asset-tools">
            <button class="asset-btn primary" type="button" data-localup-paste-clipboard ${sameFolder ? 'disabled' : ''}><i data-lucide="clipboard-paste"></i><span>${sameFolder ? '切到其他文件夹后移动' : `移动到「${escapeHtml(hereLabel)}」`}</span></button>
            <button class="asset-icon-btn" type="button" data-localup-clear-clipboard title="取消剪切"><i data-lucide="x"></i></button>
        </div>
    </div>`;
}
function setLocalUploadClipboard(){
    const ids = [...selectedLocalUploadIds];
    if(!ids.length){ setStatus('没有选中的素材'); return; }
    localUploadClipboard = {ids, sourceFolder: activeLocalUploadFolder || ''};
    selectedLocalUploadIds.clear();
    render();
    setStatus(`已剪切 ${ids.length} 个素材，切换到目标文件夹后点"移动到此文件夹"`);
}
async function pasteLocalUploadClipboard(){
    if(!localUploadClipboard?.ids?.length) return;
    const names = localUploadClipboard.ids.map(id => findLocalUpload(id)?.file).filter(Boolean);
    if(!names.length){ localUploadClipboard = null; render(); return; }
    setStatus('正在移动...');
    try {
        const data = await apiJson('/api/local-assets/move', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({names, folder: activeLocalUploadFolder || ''})
        });
        await loadLocalAssets();
        localUploadClipboard = null;
        selectedLocalUploadIds.clear();
        render();
        setStatus(`已移动 ${data?.moved ?? names.length} 个素材`);
    } catch(err){
        setStatus(err.message || '移动失败');
    }
}
async function renameWorkflowItem(id){
    const item = findWorkflowItem(id);
    const name = await siteTextInput({title:'重命名工作流', value:item?.name || '', placeholder:'工作流名称'});
    if(!item || !String(name || '').trim()) return;
    const data = await apiJson(`/api/asset-library/items/${encodeURIComponent(id)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
    assetLibrary = data.library || assetLibrary;
    render();
    setStatus('已重命名工作流');
}
async function deleteWorkflowItem(id){
    const item = findWorkflowItem(id);
    if(!item) return;
    if(pendingDeleteAssetId !== id){
        pendingDeleteAssetId = id;
        render();
        setStatus('再次点击确认删除工作流');
        return;
    }
    const data = await apiJson(`/api/asset-library/items/${encodeURIComponent(id)}`, {method:'DELETE'});
    assetLibrary = data.library || assetLibrary;
    selectedWorkflowIds.delete(id);
    selectedWorkflowId = '';
    pendingDeleteAssetId = '';
    render();
    setStatus('已删除工作流');
}
async function deleteSelectedWorkflows(){
    const ids = [...selectedWorkflowIds];
    if(!ids.length) return;
    const data = await apiJson('/api/asset-library/items/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({library_id:activeWorkflowLibraryId, ids})});
    assetLibrary = data.library || assetLibrary;
    selectedWorkflowIds.clear();
    selectedWorkflowId = '';
    render();
    setStatus(`已删除 ${data.removed || 0} 个工作流`);
}
async function uploadLocalAssets(files){
    const list = [...files].filter(f => isLocalMediaFile(f));
    if(!list.length){ setStatus('没有可上传的图片/视频/音频文件'); return; }
    const form = new FormData();
    form.append('folder', activeLocalUploadFolder || '');
    list.forEach(file => form.append('files', file));
    setStatus('正在上传...');
    try {
        const data = await apiJson('/api/local-assets/upload', {method:'POST', body:form});
        const uploaded = Array.isArray(data.files) ? data.files : [];
        await loadLocalAssets();
        selectedLocalUploadId = uploaded[0]?.id || selectedLocalUploadId;
        render();
        setStatus(`已上传 ${uploaded.length} 个素材`);
    } catch(err) {
        setStatus(err.message || '上传失败');
    }
}
async function deleteLocalAssets(ids){
    const names = (ids || []).map(id => findLocalUpload(id)?.file).filter(Boolean);
    if(!names.length) return;
    setStatus('正在删除...');
    try {
        await apiJson('/api/local-assets/delete', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({names})
        });
        await loadLocalAssets();
        selectedLocalUploadIds.clear();
        if(selectedLocalUploadId && !findLocalUpload(selectedLocalUploadId)) selectedLocalUploadId = '';
        render();
        setStatus(`已删除 ${names.length} 个素材`);
    } catch(err) {
        setStatus(err.message || '删除失败');
    }
}
async function saveLocalUploadInlineName(id, name){
    const item = findLocalUpload(id);
    name = materialNameStem(name);
    if(!item) return;
    if(!String(name || '').trim()) return;
    if(materialNameParts(item).stem === String(name || '').trim()) return;
    try {
        const data = await apiJson('/api/local-assets/items', {
            method:'PATCH',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({path:item.file || item.id, name})
        });
        localAssets = Array.isArray(data.items) ? data.items : localAssets;
        localUploadTree = data.tree || localUploadTree;
        selectedLocalUploadId = data.item?.id || data.item?.file || selectedLocalUploadId;
        if(selectedLocalUploadIds.has(id)){
            selectedLocalUploadIds.delete(id);
            if(data.item?.id) selectedLocalUploadIds.add(data.item.id);
        }
        render();
        setStatus('已重命名素材，反推提示词和分类索引已同步');
    } catch(err) {
        setStatus(err.message || '重命名失败');
    }
}
function beginLocalUploadInlineRename(id){
    const item = findLocalUpload(id);
    const card = [...root.querySelectorAll('[data-localup-card]')].find(el => el.dataset.localupCard === id);
    const nameEl = card?.querySelector('.asset-card-name');
    if(!item || !card || !nameEl || card.querySelector('.asset-card-name-input')) return;
    const previousName = materialNameParts(item).stem;
    const extension = materialNameParts(item).extension;
    const input = document.createElement('input');
    input.className = 'asset-card-name-input';
    input.type = 'text';
    input.value = previousName;
    input.setAttribute('aria-label', '素材名称');
    const editor = document.createElement('div');
    editor.className = 'asset-name-editor';
    editor.append(input);
    const suffix = document.createElement('span');
    suffix.className = 'asset-name-extension';
    suffix.textContent = extension;
    editor.append(suffix);
    nameEl.replaceWith(editor);
    input.focus();
    input.select();
    let done = false;
    const restore = () => {
        if(editor.isConnected) editor.replaceWith(nameEl);
    };
    const finish = async save => {
        if(done) return;
        done = true;
        const name = materialNameStem(input.value);
        if(!save || !name || name === previousName){
            restore();
            return;
        }
        input.disabled = true;
        await saveLocalUploadInlineName(id, name);
    };
    input.addEventListener('keydown', event => {
        event.stopPropagation();
        if(event.key === 'Enter'){
            event.preventDefault();
            finish(true);
        } else if(event.key === 'Escape'){
            event.preventDefault();
            finish(false);
        }
    });
    input.addEventListener('pointerdown', event => event.stopPropagation());
    input.addEventListener('mousedown', event => event.stopPropagation());
    input.addEventListener('click', event => event.stopPropagation());
    input.addEventListener('blur', () => finish(true));
}
function beginAssetInlineRename(id){
    const item = findAssetItem(id);
    const card = [...root.querySelectorAll('[data-asset-card]')].find(el => el.dataset.assetCard === id);
    const nameEl = card?.querySelector('.asset-card-name');
    if(!item || !card || !nameEl || card.querySelector('.asset-card-name-input')) return;
    const previousName = materialNameParts(item).stem;
    const extension = materialNameParts(item).extension;
    const input = document.createElement('input');
    input.className = 'asset-card-name-input';
    input.type = 'text';
    input.value = previousName;
    input.setAttribute('aria-label', '素材名称');
    const editor = document.createElement('div');
    editor.className = 'asset-name-editor';
    editor.append(input);
    const suffix = document.createElement('span');
    suffix.className = 'asset-name-extension';
    suffix.textContent = extension;
    editor.append(suffix);
    nameEl.replaceWith(editor);
    input.focus();
    input.select();
    let done = false;
    const restore = () => { if(editor.isConnected) editor.replaceWith(nameEl); };
    const finish = async save => {
        if(done) return;
        done = true;
        const name = materialNameStem(input.value);
        if(!save || !name || name === previousName){ restore(); return; }
        input.disabled = true;
        await saveAssetInlineName(id, name);
    };
    input.addEventListener('keydown', event => {
        event.stopPropagation();
        if(event.key === 'Enter'){ event.preventDefault(); finish(true); }
        else if(event.key === 'Escape'){ event.preventDefault(); finish(false); }
    });
    input.addEventListener('pointerdown', event => event.stopPropagation());
    input.addEventListener('mousedown', event => event.stopPropagation());
    input.addEventListener('click', event => event.stopPropagation());
    input.addEventListener('blur', () => finish(true));
}
function beginResultInlineRename(id){
    const item = findCanvasAssetItem(id);
    const card = [...root.querySelectorAll('[data-canvas-asset-card]')].find(el => el.dataset.canvasAssetCard === id);
    const nameEl = card?.querySelector('.asset-card-name');
    if(!item || !card || !nameEl || card.querySelector('.asset-card-name-input')) return;
    const previousName = materialNameParts(item).stem;
    const extension = materialNameParts(item).extension;
    const input = document.createElement('input');
    input.className = 'asset-card-name-input';
    input.type = 'text';
    input.value = previousName;
    input.setAttribute('aria-label', '生成结果名称');
    const editor = document.createElement('div');
    editor.className = 'asset-name-editor';
    editor.append(input);
    const suffix = document.createElement('span');
    suffix.className = 'asset-name-extension';
    suffix.textContent = extension;
    editor.append(suffix);
    nameEl.replaceWith(editor);
    input.focus();
    input.select();
    let done = false;
    const restore = () => { if(editor.isConnected) editor.replaceWith(nameEl); };
    const finish = async save => {
        if(done) return;
        done = true;
        const name = materialNameStem(input.value);
        if(!save || !name || name === previousName){ restore(); return; }
        input.disabled = true;
        await saveResultInlineName(id, name);
    };
    input.addEventListener('keydown', event => {
        event.stopPropagation();
        if(event.key === 'Enter'){ event.preventDefault(); finish(true); }
        else if(event.key === 'Escape'){ event.preventDefault(); finish(false); }
    });
    input.addEventListener('pointerdown', event => event.stopPropagation());
    input.addEventListener('mousedown', event => event.stopPropagation());
    input.addEventListener('click', event => event.stopPropagation());
    input.addEventListener('blur', () => finish(true));
}
async function renameResultItem(id){
    if(!findCanvasAssetItem(id)) return;
    selectedCanvasAssetId = id;
    refreshCanvasAssetSelectionOnly();
    requestAnimationFrame(() => beginResultInlineRename(id));
}
async function saveResultInlineName(id, name){
    const item = findCanvasAssetItem(id);
    name = materialNameStem(name);
    if(!item || !String(name || '').trim()) return;
    if(materialNameParts(item).stem === String(name || '').trim()) return;
    const data = await apiJson(`/api/results/${encodeURIComponent(id)}`, {
        method:'PATCH',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name})
    });
    const updated = data.item || {};
    canvasAssetsData.items = (canvasAssetsData.items || []).map(entry => entry.id === id ? {...entry, ...updated} : entry);
    refreshCanvasAssetSelectionOnly();
    render();
    setStatus('生成结果名称已保存');
}
async function createLocalUploadFolder(){
    const name = await siteTextInput({title:'新建文件夹', value:'新文件夹', placeholder:'文件夹名称', confirmLabel:'新建'});
    if(!String(name || '').trim()) return;
    try {
        const data = await apiJson('/api/local-assets/folders', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({parent:activeLocalUploadFolder || '', name})
        });
        localAssets = Array.isArray(data.items) ? data.items : localAssets;
        localUploadTree = data.tree || localUploadTree;
        activeLocalUploadFolder = data.folder?.path || activeLocalUploadFolder;
        selectedLocalUploadId = '';
        selectedLocalUploadIds.clear();
        render();
        setStatus('已新建本地素材文件夹');
    } catch(err) {
        setStatus(err.message || '新建文件夹失败');
    }
}
async function renameLocalUploadFolder(){
    if(!activeLocalUploadFolder){
        setStatus('根目录不能重命名');
        return;
    }
    const current = localUploadFolderTitle();
    const name = await siteTextInput({title:'重命名文件夹', value:current, placeholder:'文件夹名称'});
    if(!String(name || '').trim() || name === current) return;
    try {
        const data = await apiJson('/api/local-assets/folders', {
            method:'PATCH',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({path:activeLocalUploadFolder, name})
        });
        localAssets = Array.isArray(data.items) ? data.items : localAssets;
        localUploadTree = data.tree || localUploadTree;
        activeLocalUploadFolder = data.folder?.path || activeLocalUploadFolder;
        selectedLocalUploadId = '';
        selectedLocalUploadIds.clear();
        render();
        setStatus('已重命名本地素材文件夹');
    } catch(err) {
        setStatus(err.message || '重命名文件夹失败');
    }
}
async function runLocalUploadCaptionSelected(){
    const images = selectedLocalUploadImageItems();
    if(!images.length || localCaptionBusy) return;
    normalizeLocalCaptionSettings();
    if(!localCaptionProvider || !localCaptionModel){
        setStatus('请先在 API 设置中配置可用的聊天/视觉模型');
        return;
    }
    localCaptionBusy = true;
    render();
    setStatus(`正在反推 ${images.length} 张本地图片的提示词...`);
    try {
        const data = await apiJson('/api/local-assets/caption', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({
                names:images.map(item => item.file || item.id),
                provider:localCaptionProvider,
                model:localCaptionModel,
                prompt:(localCaptionPrompt || '描述图片').trim() || '描述图片'
            })
        });
        await loadLocalAssets();
        selectedLocalUploadIds.clear();
        if(images[0]?.id) selectedLocalUploadId = images[0].id;
        render();
        const failed = (data.items || []).filter(item => !item.ok);
        setStatus(failed.length ? `已完成 ${data.count || 0} 张，${failed.length} 张失败：${failed[0].error || '反推失败'}` : `已反推并保存 ${data.count || images.length} 张图片提示词`);
    } catch(err) {
        setStatus(err.message || '提示词反推失败');
    } finally {
        localCaptionBusy = false;
        render();
    }
}
async function runLocalUploadCaptionOne(id){
    const item = findLocalUpload(id);
    if(!item || assetKind(item) !== 'image' || localCaptionBusy) return;
    normalizeLocalCaptionSettings();
    if(!localCaptionProvider || !localCaptionModel){
        setStatus('请先在 API 设置中配置可用的聊天/视觉模型');
        return;
    }
    localCaptionBusy = true;
    selectedLocalUploadId = item.id;
    render();
    setStatus(`正在反推「${item.name || '本地图片'}」的提示词...`);
    try {
        const data = await apiJson('/api/local-assets/caption', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({
                names:[item.file || item.id],
                provider:localCaptionProvider,
                model:localCaptionModel,
                prompt:(localCaptionPrompt || '描述图片').trim() || '描述图片'
            })
        });
        const result = (data.items || [])[0] || null;
        if(result && !result.ok) throw new Error(result.error || '反推失败');
        await loadLocalAssets();
        selectedLocalUploadId = item.id;
        render();
        setStatus('已反推并保存当前图片提示词');
    } catch(err) {
        setStatus(err.message || '提示词反推失败');
    } finally {
        localCaptionBusy = false;
        render();
    }
}
async function copyLocalUploadCaption(id){
    const item = findLocalUpload(id);
    if(!item || assetKind(item) !== 'image') return;
    const textarea = document.getElementById('localUploadCaptionEdit');
    const text = textarea ? textarea.value : (item.caption || '');
    if(!String(text || '').trim()){
        setStatus('当前图片暂无可复制的提示词');
        return;
    }
    const ok = await copyTextToClipboard(text);
    setStatus(ok ? '已复制提示词' : '复制失败，请手动复制');
}
async function saveLocalUploadCaption(id){
    const item = findLocalUpload(id);
    if(!item || assetKind(item) !== 'image') return;
    const textarea = document.getElementById('localUploadCaptionEdit');
    const caption = textarea ? textarea.value : (item.caption || '');
    try {
        const data = await apiJson('/api/local-assets/caption', {
            method:'PATCH',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({name:item.file || item.id, caption})
        });
        item.caption = data.caption || '';
        item.caption_file = data.caption_file || item.caption_file || '';
        render();
        setStatus('已保存反推提示词');
    } catch(err) {
        setStatus(err.message || '保存提示词失败');
    }
}
async function handleClick(event){
    const target = event.target;
    if(guardMatchesManagedSelection(target)){
        event.preventDefault();
        event.stopPropagation();
        return;
    }
    if(activeTab === 'assets' && activeInputScope === 'asset' && assetManageMode){
        const assetCheck = target.closest?.('[data-asset-check]');
        const assetCard = target.closest?.('[data-asset-card]');
        if(assetCheck || assetCard){
            event.preventDefault();
            event.stopPropagation();
            const id = assetCheck?.dataset.assetCheck || assetCard?.dataset.assetCard || '';
            const selected = toggleSelectionSet(selectedAssetIds, id);
            selectedAssetId = selected ? id : (selectedAssetId === id ? '' : selectedAssetId);
            pendingBatchDelete = '';
            render();
            return;
        }
    }
    if(activeTab === 'assets' && activeInputScope === 'temporary' && localUploadManageMode){
        const localUpCheck = target.closest?.('[data-localup-check]');
        const localUpCard = target.closest?.('[data-localup-card]');
        if(localUpCheck || localUpCard){
            event.preventDefault();
            event.stopPropagation();
            const id = localUpCheck?.dataset.localupCheck || localUpCard?.dataset.localupCard || '';
            const selected = toggleSelectionSet(selectedLocalUploadIds, id);
            selectedLocalUploadId = selected ? id : (selectedLocalUploadId === id ? '' : selectedLocalUploadId);
            pendingBatchDelete = '';
            render();
            return;
        }
    }
    if(activeTab === 'assets' && activeInputScope === 'temporary' && localManageMode){
        const localCheck = target.closest?.('[data-local-check]');
        const localCard = target.closest?.('[data-local-card]');
        if(localCheck || localCard){
            event.preventDefault();
            event.stopPropagation();
            const id = localCheck?.dataset.localCheck || localCard?.dataset.localCard || '';
            const selected = toggleSelectionSet(selectedLocalIds, id);
            selectedLocalId = selected ? id : (selectedLocalId === id ? '' : selectedLocalId);
            pendingBatchDelete = '';
            render();
            return;
        }
    }
    if(activeTab === 'workflows' && workflowManageMode){
        const workflowCheck = target.closest?.('[data-workflow-check]');
        const workflowCard = target.closest?.('[data-workflow-card]');
        if(workflowCheck || workflowCard){
            event.preventDefault();
            event.stopPropagation();
            const id = workflowCheck?.dataset.workflowCheck || workflowCard?.dataset.workflowCard || '';
            const selected = toggleSelectionSet(selectedWorkflowIds, id);
            selectedWorkflowId = selected ? id : (selectedWorkflowId === id ? '' : selectedWorkflowId);
            pendingBatchDelete = '';
            render();
            return;
        }
    }
    if(activeTab === 'prompts' && promptManageMode){
        const promptCheck = target.closest?.('[data-prompt-check]');
        const promptRow = target.closest?.('[data-prompt-row]');
        if(promptCheck || promptRow){
            event.preventDefault();
            event.stopPropagation();
            const id = promptCheck?.dataset.promptCheck || promptRow?.dataset.promptRow || '';
            const selected = toggleSelectionSet(selectedPromptIds, id);
            selectedPromptId = selected ? id : (selectedPromptId === id ? '' : selectedPromptId);
            promptEditMode = false;
            promptCreateMode = false;
            pendingBatchDelete = '';
            render();
            return;
        }
    }
    if(activeTab === 'results' && canvasAssetManageMode){
        const canvasCheck = target.closest?.('[data-canvas-asset-check]');
        const canvasCard = target.closest?.('[data-canvas-asset-card]');
        if(canvasCheck || canvasCard){
            event.preventDefault();
            event.stopPropagation();
            const id = canvasCheck?.dataset.canvasAssetCheck || canvasCard?.dataset.canvasAssetCard || '';
            const selected = toggleSelectionSet(selectedCanvasAssetIds, id);
            selectedCanvasAssetId = selected ? id : (selectedCanvasAssetId === id ? '' : selectedCanvasAssetId);
            refreshCanvasAssetSelectionOnly();
            return;
        }
    }
    const tabBtn = target.closest?.('[data-tab]');
    if(tabBtn){ activeTab = tabBtn.dataset.tab || 'assets'; selectedAssetIds.clear(); selectedWorkflowIds.clear(); selectedPromptIds.clear(); selectedLocalIds.clear(); selectedLocalUploadIds.clear(); selectedCanvasAssetIds.clear(); render(); return; }
    const inputScope = target.closest?.('[data-input-scope]');
    if(inputScope){
        activeInputScope = inputScope.dataset.inputScope === 'temporary' ? 'temporary' : 'asset';
        selectedAssetIds.clear();
        selectedLocalUploadIds.clear();
        render();
        return;
    }
    if(target.closest?.('#refreshBtn')){ await loadAll(); return; }
    const textEdit = target.closest?.('[data-text-edit]');
    if(textEdit){
        const [source, id] = String(textEdit.dataset.textEdit || '').split(':', 2);
        await openTextContentEditor(source || 'asset', id || '');
        return;
    }
    const assetPreview = target.closest?.('[data-asset-preview]');
    if(assetPreview){ showDetailPreview('asset', assetPreview.dataset.assetPreview || ''); return; }
    const canvasAssetPreview = target.closest?.('[data-canvas-asset-preview]');
    if(canvasAssetPreview){ showDetailPreview('canvas-asset', canvasAssetPreview.dataset.canvasAssetPreview || ''); return; }
    const localPreview = target.closest?.('[data-local-preview]');
    if(localPreview){ showDetailPreview('local', localPreview.dataset.localPreview || ''); return; }
    const localUpPreview = target.closest?.('[data-localup-preview]');
    if(localUpPreview){ showDetailPreview('localup', localUpPreview.dataset.localupPreview || ''); return; }
    const localUpPromote = target.closest?.('[data-localup-promote]');
    if(localUpPromote){ await promoteLocalUploadItem(localUpPromote.dataset.localupPromote || ''); return; }
    if(target.closest?.('[data-localup-upload]')){ uploadInput?.click(); return; }
    if(target.closest?.('[data-localup-folder-new]')){ await createLocalUploadFolder(); return; }
    if(target.closest?.('[data-localup-folder-rename]')){ await renameLocalUploadFolder(); return; }
    const localUpFolder = target.closest?.('[data-localup-folder]');
    if(localUpFolder){
        activeLocalUploadFolder = localUpFolder.dataset.localupFolder || '';
        selectedLocalUploadId = '';
        selectedLocalUploadIds.clear();
        pendingBatchDelete = '';
        render();
        return;
    }
    if(target.closest?.('[data-localup-manage]')){
        localUploadManageMode = !localUploadManageMode;
        if(!localUploadManageMode) selectedLocalUploadIds.clear();
        render();
        return;
    }
    if(target.closest?.('[data-localup-select-all]')){ toggleMaterialSelection(localUploadItems(), selectedLocalUploadIds); render(); return; }
    if(target.closest?.('[data-localup-clear]')){ selectedLocalUploadIds.clear(); render(); return; }
    if(target.closest?.('[data-localup-download-selected]')){ await downloadSelectedLocalUploads(); return; }
    if(target.closest?.('[data-localup-canvas-selected]')){ copySelectedLocalUploadsToCanvas(); return; }
    if(target.closest?.('[data-localup-cut-selected]')){ setLocalUploadClipboard(); return; }
    if(target.closest?.('[data-localup-paste-clipboard]')){ await pasteLocalUploadClipboard(); return; }
    if(target.closest?.('[data-localup-clear-clipboard]')){ localUploadClipboard = null; render(); return; }
    const localUpDownload = target.closest?.('[data-localup-download]');
    if(localUpDownload){ downloadLocalUpload(localUpDownload.dataset.localupDownload || ''); return; }
    if(target.closest?.('[data-localup-delete-selected]')){ await deleteLocalAssets([...selectedLocalUploadIds]); return; }
    if(target.closest?.('[data-local-caption-run]')){ await runLocalUploadCaptionSelected(); return; }
    const localUpCaptionOne = target.closest?.('[data-localup-caption-one]');
    if(localUpCaptionOne){ await runLocalUploadCaptionOne(localUpCaptionOne.dataset.localupCaptionOne || ''); return; }
    const localUpCaptionCopy = target.closest?.('[data-localup-caption-copy]');
    if(localUpCaptionCopy){ await copyLocalUploadCaption(localUpCaptionCopy.dataset.localupCaptionCopy || ''); return; }
    const localUpCaptionSave = target.closest?.('[data-localup-caption-save]');
    if(localUpCaptionSave){ await saveLocalUploadCaption(localUpCaptionSave.dataset.localupCaptionSave || ''); return; }
    const localUpRename = target.closest?.('[data-localup-rename]');
    if(localUpRename){ event.stopPropagation(); beginLocalUploadInlineRename(localUpRename.dataset.localupRename || ''); return; }
    const localUpDeleteOne = target.closest?.('[data-localup-delete-one]');
    if(localUpDeleteOne){ await deleteLocalAssets([localUpDeleteOne.dataset.localupDeleteOne || '']); return; }
    const localUpCheck = target.closest?.('[data-localup-check]');
    if(localUpCheck){
        const id = localUpCheck.dataset.localupCheck || '';
        const selected = toggleSelectionSet(selectedLocalUploadIds, id);
        selectedLocalUploadId = selected ? id : (selectedLocalUploadId === id ? '' : selectedLocalUploadId);
        pendingBatchDelete = '';
        render();
        return;
    }
    const localUpOpen = target.closest?.('[data-localup-open]');
    if(localUpOpen){ const it = findLocalUpload(localUpOpen.dataset.localupOpen || ''); if(it?.url) window.open(it.url, '_blank'); return; }
    const localUpCopy = target.closest?.('[data-localup-copy]');
    if(localUpCopy){ const it = findLocalUpload(localUpCopy.dataset.localupCopy || ''); const ok = await copyTextToClipboard(it?.url || ''); setStatus(ok ? '已复制链接' : '复制失败'); return; }
    const localUpCard = target.closest?.('[data-localup-card]');
    if(localUpCard){
        const id = localUpCard.dataset.localupCard || '';
        if(localUploadManageMode){
            const selected = toggleSelectionSet(selectedLocalUploadIds, id);
            selectedLocalUploadId = selected ? id : (selectedLocalUploadId === id ? '' : selectedLocalUploadId);
            pendingBatchDelete = '';
            render();
        } else {
            selectedLocalUploadId = id;
            pendingBatchDelete = '';
            refreshLocalUploadSelectionOnly();
        }
        return;
    }
    if(target.closest?.('[data-local-pick-folder]')){ await registerSharedFolder(); return; }
    const canvasAssetCat = target.closest?.('[data-canvas-asset-cat]');
    if(canvasAssetCat){
        activeCanvasAssetCategory = canvasAssetCat.dataset.canvasAssetCat || defaultCanvasAssetCategory();
        activeCanvasAssetCanvasId = '';
        selectedCanvasAssetId = '';
        selectedCanvasAssetIds.clear();
        render();
        return;
    }
    const canvasAssetCanvas = target.closest?.('[data-canvas-asset-canvas]');
    if(canvasAssetCanvas){
        activeCanvasAssetCategory = canvasAssetCanvas.dataset.canvasAssetCanvasCat || activeCanvasAssetCategory || 'all';
        activeCanvasAssetCanvasId = canvasAssetCanvas.dataset.canvasAssetCanvas || '';
        selectedCanvasAssetId = '';
        selectedCanvasAssetIds.clear();
        render();
        return;
    }
    if(target.closest?.('[data-canvas-asset-manage]')){
        canvasAssetManageMode = !canvasAssetManageMode;
        if(!canvasAssetManageMode) selectedCanvasAssetIds.clear();
        render();
        return;
    }
    if(target.closest?.('[data-canvas-asset-refresh]')){ await refreshCanvasAssets(); return; }
    if(target.closest?.('[data-canvas-asset-select-all]')){ toggleMaterialSelection(currentCanvasAssetItems(), selectedCanvasAssetIds); render(); return; }
    if(target.closest?.('[data-canvas-asset-clear-selection]')){ selectedCanvasAssetIds.clear(); render(); return; }
    if(target.closest?.('[data-canvas-asset-download-selected]')){ await downloadCanvasAssetItems([...selectedCanvasAssetIds]); return; }
    if(target.closest?.('[data-result-delete-selected]')){ await deleteGenerationResults([...selectedCanvasAssetIds]); return; }
    const resultRename = target.closest?.('[data-result-rename]');
    if(resultRename){ event.stopPropagation(); await renameResultItem(resultRename.dataset.resultRename || ''); return; }
    const resultPromote = target.closest?.('[data-result-promote]');
    if(resultPromote){ await promoteCanvasAssetItem(resultPromote.dataset.resultPromote || ''); return; }
    const canvasAssetDownload = target.closest?.('[data-canvas-asset-download]');
    if(canvasAssetDownload){ await downloadCanvasAssetItems([canvasAssetDownload.dataset.canvasAssetDownload || '']); return; }
    const resultDelete = target.closest?.('[data-result-delete]');
    if(resultDelete){ await deleteGenerationResults([resultDelete.dataset.resultDelete || '']); return; }
    const canvasAssetCheck = target.closest?.('[data-canvas-asset-check]');
    if(canvasAssetCheck){
        event.preventDefault();
        event.stopPropagation();
        if(canvasAssetManageMode){
            const id = canvasAssetCheck.dataset.canvasAssetCheck || '';
            const selected = toggleSelectionSet(selectedCanvasAssetIds, id);
            selectedCanvasAssetId = selected ? id : (selectedCanvasAssetId === id ? '' : selectedCanvasAssetId);
            refreshCanvasAssetSelectionOnly();
        }
        return;
    }
    const canvasAssetCard = target.closest?.('[data-canvas-asset-card]');
    if(canvasAssetCard){
        const id = canvasAssetCard.dataset.canvasAssetCard || '';
        if(canvasAssetManageMode){
            const selected = toggleSelectionSet(selectedCanvasAssetIds, id);
            selectedCanvasAssetId = selected ? id : (selectedCanvasAssetId === id ? '' : selectedCanvasAssetId);
        } else {
            selectedCanvasAssetId = id;
        }
        refreshCanvasAssetSelectionOnly();
        return;
    }
    const sharedRemove = target.closest?.('[data-shared-remove]');
    if(sharedRemove){ event.stopPropagation(); await unregisterSharedFolder(sharedRemove.dataset.sharedRemove || ''); return; }
    const sharedOpen = target.closest?.('[data-shared-open]');
    if(sharedOpen){ await openSharedFolder(sharedOpen.dataset.sharedOpen || ''); return; }
    if(target.closest?.('[data-local-manage]')){
        localManageMode = !localManageMode;
        pendingBatchDelete = '';
        if(!localManageMode) selectedLocalIds.clear();
        render();
        return;
    }
    if(target.closest?.('[data-local-select-all]')){ localItemsForFolder().forEach(item => selectedLocalIds.add(item.id)); pendingBatchDelete = ''; render(); return; }
    if(target.closest?.('[data-local-clear-selection]')){ selectedLocalIds.clear(); pendingBatchDelete = ''; render(); return; }
    if(target.closest?.('[data-local-copy-selected]')){ setLocalClipboard('copy'); return; }
    if(target.closest?.('[data-local-import-clipboard]')){ await pasteLocalClipboardToAssets(); return; }
    if(target.closest?.('[data-local-clear-clipboard]')){ localClipboard = null; render(); return; }
    const localImportOne = target.closest?.('[data-local-import-one]');
    if(localImportOne){ setLocalClipboard('copy', [localImportOne.dataset.localImportOne || '']); await pasteLocalClipboardToAssets(); return; }
    const localOpen = target.closest?.('[data-local-open]');
    if(localOpen){ openLocalItem(localOpen.dataset.localOpen || ''); return; }
    const localFolder = target.closest?.('[data-local-folder]');
    if(localFolder){ activeLocalFolderId = localFolder.dataset.localFolder || ''; selectedLocalId = ''; selectedLocalIds.clear(); pendingBatchDelete = ''; render(); return; }
    const localCheck = target.closest?.('[data-local-check]');
    if(localCheck){
        event.preventDefault();
        event.stopPropagation();
        if(localManageMode){
            const id = localCheck.dataset.localCheck || '';
            const selected = toggleSelectionSet(selectedLocalIds, id);
            selectedLocalId = selected ? id : (selectedLocalId === id ? '' : selectedLocalId);
            pendingBatchDelete = '';
            render();
        }
        return;
    }
    const localCard = target.closest?.('[data-local-card]');
    if(localCard){
        const id = localCard.dataset.localCard || '';
        if(localManageMode){
            const selected = toggleSelectionSet(selectedLocalIds, id);
            selectedLocalId = selected ? id : (selectedLocalId === id ? '' : selectedLocalId);
            pendingBatchDelete = '';
            render();
        } else {
            selectedLocalId = id;
            pendingBatchDelete = '';
            refreshLocalSelectionOnly();
        }
        return;
    }
    if(target.closest?.('[data-workflow-manage]')){
        workflowManageMode = !workflowManageMode;
        if(!workflowManageMode) selectedWorkflowIds.clear();
        pendingDeleteAssetId = '';
        render();
        return;
    }
    if(target.closest?.('[data-workflow-select-all]')){ toggleMaterialSelection(currentWorkflowItems(), selectedWorkflowIds); render(); return; }
    if(target.closest?.('[data-workflow-clear-selection]')){ selectedWorkflowIds.clear(); render(); return; }
    if(target.closest?.('[data-workflow-export-selected]')){ await exportWorkflowItems([...selectedWorkflowIds]); return; }
    if(target.closest?.('[data-workflow-delete-selected]')){ await deleteSelectedWorkflows(); return; }
    if(target.closest?.('[data-workflow-upload]')){
        if(uploadInput) uploadInput.accept = '.json,.zip,application/json,application/zip,application/x-zip-compressed';
        uploadInput?.click();
        return;
    }
    const workflowDownload = target.closest?.('[data-workflow-download]');
    if(workflowDownload){ await exportWorkflowItems([workflowDownload.dataset.workflowDownload || '']); return; }
    const workflowRename = target.closest?.('[data-workflow-rename]');
    if(workflowRename){ await renameWorkflowItem(workflowRename.dataset.workflowRename || ''); return; }
    const workflowDelete = target.closest?.('[data-workflow-delete]');
    if(workflowDelete){ await deleteWorkflowItem(workflowDelete.dataset.workflowDelete || ''); return; }
    if(target.closest?.('[data-workflow-cat-new]')){
        workflowTreeEdit = {kind:'category-new', placement:'head', value:'新工作流分组', label:'工作流分组名称'};
        pendingTreeDelete = '';
        render();
        focusTreeEditInput('workflowTreeEditInput');
        return;
    }
    if(target.closest?.('[data-workflow-cat-rename]')){
        const cat = activeWorkflowCategory();
        if(!cat) return;
        workflowTreeEdit = {kind:'category-rename', value:cat.name || '', label:'工作流分组名称', categoryId:cat.id};
        pendingTreeDelete = '';
        render();
        focusTreeEditInput('workflowTreeEditInput');
        return;
    }
    if(target.closest?.('[data-workflow-cat-delete]')){ await deleteWorkflowCategory(); return; }
    const workflowLib = target.closest?.('[data-workflow-lib]');
    if(workflowLib){ activeWorkflowLibraryId = workflowLib.dataset.workflowLib || ''; activeWorkflowCategoryId = ''; selectedWorkflowId = ''; selectedWorkflowIds.clear(); render(); return; }
    const workflowCat = target.closest?.('[data-workflow-cat]');
    if(workflowCat){ activeWorkflowLibraryId = workflowCat.dataset.workflowCatLib || activeWorkflowLibraryId; activeWorkflowCategoryId = workflowCat.dataset.workflowCat || ''; selectedWorkflowId = ''; selectedWorkflowIds.clear(); render(); return; }
    const workflowCard = target.closest?.('[data-workflow-card]');
    if(workflowCard){
        const id = workflowCard.dataset.workflowCard || '';
        if(workflowManageMode){
            const selected = toggleSelectionSet(selectedWorkflowIds, id);
            selectedWorkflowId = selected ? id : (selectedWorkflowId === id ? '' : selectedWorkflowId);
        } else {
            selectedWorkflowId = id;
        }
        pendingDeleteAssetId = '';
        render();
        return;
    }
    if(target.closest?.('[data-asset-tree-edit-save]')){ await saveAssetTreeEdit(); return; }
    if(target.closest?.('[data-asset-tree-edit-cancel]')){ assetTreeEdit = null; render(); return; }
    if(target.closest?.('[data-workflow-tree-edit-save]')){ await saveWorkflowTreeEdit(); return; }
    if(target.closest?.('[data-workflow-tree-edit-cancel]')){ workflowTreeEdit = null; render(); return; }
    if(target.closest?.('[data-prompt-tree-edit-save]')){ await savePromptTreeEdit(); return; }
    if(target.closest?.('[data-prompt-tree-edit-cancel]')){ promptTreeEdit = null; render(); return; }
    const assetEditSave = target.closest?.('[data-asset-edit-save]');
    if(assetEditSave){ await saveAssetEdit(assetEditSave.dataset.assetEditSave || ''); return; }
    if(target.closest?.('[data-asset-edit-cancel]')){ assetEditMode = false; render(); return; }
    const assetEditStart = target.closest?.('[data-asset-edit-start]');
    if(assetEditStart){ selectedAssetId = assetEditStart.dataset.assetEditStart || selectedAssetId; pendingDeleteAssetId = ''; render(); requestAnimationFrame(() => beginAssetInlineRename(selectedAssetId)); return; }
    if(target.closest?.('[data-asset-manage]')){
        assetManageMode = !assetManageMode;
        pendingBatchDelete = '';
        if(!assetManageMode) selectedAssetIds.clear();
        render();
        return;
    }
    if(target.closest?.('[data-asset-select-all]')){ toggleMaterialSelection(currentAssetItems(), selectedAssetIds); pendingBatchDelete = ''; render(); return; }
    if(target.closest?.('[data-asset-clear-selection]')){ selectedAssetIds.clear(); pendingBatchDelete = ''; render(); return; }
    if(target.closest?.('[data-asset-cut-selected]')){ setAssetClipboard('cut'); return; }
    if(target.closest?.('[data-asset-copy-selected]')){ setAssetClipboard('copy'); return; }
    if(target.closest?.('[data-asset-paste-clipboard]')){ await pasteAssetClipboard(); return; }
    if(target.closest?.('[data-asset-clear-clipboard]')){ assetClipboard = null; render(); return; }
    const assetRename = target.closest?.('[data-asset-rename]');
    if(assetRename){ await renameAssetItem(assetRename.dataset.assetRename || ''); return; }
    const assetDelete = target.closest?.('[data-asset-delete]');
    if(assetDelete){ await deleteAssetItem(assetDelete.dataset.assetDelete || ''); return; }
    const assetDownload = target.closest?.('[data-asset-download]');
    if(assetDownload){ downloadAssetItem(assetDownload.dataset.assetDownload || ''); return; }
    const assetOpen = target.closest?.('[data-asset-open]');
    if(assetOpen){ openAssetItem(assetOpen.dataset.assetOpen || ''); return; }
    if(target.closest?.('[data-asset-download-selected]')){ await downloadSelectedAssets(); return; }
    if(target.closest?.('[data-asset-copy-to-canvas]')){ copySelectedAssetsToCanvas(); return; }
    if(target.closest?.('[data-asset-delete-selected]')){ await deleteSelectedAssets(); return; }
    if(target.closest?.('[data-asset-upload]')){
        if(uploadInput) uploadInput.accept = 'image/*,video/*,audio/*';
        uploadInput?.click();
        return;
    }
    if(target.closest?.('[data-asset-lib-new]')){ assetTreeFocus = 'library'; assetTreeEdit = {kind:'library-new', placement:'head', value:'新资产库', label:'资产库名称'}; render(); focusTreeEditInput('assetTreeEditInput'); return; }
    if(target.closest?.('[data-asset-lib-rename]')){
        const row = target.closest('[data-asset-lib]');
        if(row) activeAssetLibraryId = row.dataset.assetLib || activeAssetLibraryId;
        assetTreeFocus = 'library';
        assetTreeEdit = {kind:'library-rename', value:activeAssetLibrary()?.name || '', label:'资产库名称'};
        pendingTreeDelete = '';
        render(); return;
    }
    if(target.closest?.('[data-asset-lib-delete]')){
        const row = target.closest('[data-asset-lib]');
        if(row) activeAssetLibraryId = row.dataset.assetLib || activeAssetLibraryId;
        await deleteAssetLibrary(); return;
    }
    if(target.closest?.('[data-asset-cat-new]')){
        const row = target.closest('[data-asset-lib]');
        if(row) activeAssetLibraryId = row.dataset.assetLib || activeAssetLibraryId;
        assetTreeFocus = 'library';
        assetTreeEdit = {kind:'category-new', value:'新分组', label:'分组名称'};
        pendingTreeDelete = '';
        render(); focusTreeEditInput('assetTreeEditInput'); return;
    }
    if(target.closest?.('[data-asset-cat-rename]')){
        const row = target.closest('[data-asset-cat]');
        if(row){ activeAssetLibraryId = row.dataset.assetCatLib || activeAssetLibraryId; activeAssetCategoryId = row.dataset.assetCat || activeAssetCategoryId; }
        assetTreeFocus = 'category';
        assetTreeEdit = {kind:'category-rename', value:activeAssetCategory()?.name || '', label:'分组名称'};
        pendingTreeDelete = '';
        render(); return;
    }
    if(target.closest?.('[data-asset-cat-delete]')){
        const row = target.closest('[data-asset-cat]');
        if(row){ activeAssetLibraryId = row.dataset.assetCatLib || activeAssetLibraryId; activeAssetCategoryId = row.dataset.assetCat || activeAssetCategoryId; }
        await deleteAssetCategory(); return;
    }
    const assetLib = target.closest?.('[data-asset-lib]');
    if(assetLib){ activeAssetLibraryId = assetLib.dataset.assetLib || ''; assetTreeFocus = 'library'; activeAssetCategoryId = assetCategories()[0]?.id || ''; selectedAssetId = ''; selectedAssetIds.clear(); render(); return; }
    const assetCat = target.closest?.('[data-asset-cat]');
    if(assetCat){ activeAssetLibraryId = assetCat.dataset.assetCatLib || activeAssetLibraryId; activeAssetCategoryId = assetCat.dataset.assetCat || ''; assetTreeFocus = 'category'; selectedAssetId = ''; selectedAssetIds.clear(); render(); return; }
    const assetCheck = target.closest?.('[data-asset-check]');
    if(assetCheck){
        event.preventDefault();
        event.stopPropagation();
        if(assetManageMode){
            const id = assetCheck.dataset.assetCheck || '';
            const selected = toggleSelectionSet(selectedAssetIds, id);
            selectedAssetId = selected ? id : (selectedAssetId === id ? '' : selectedAssetId);
            pendingBatchDelete = '';
            render();
        }
        return;
    }
    const assetCard = target.closest?.('[data-asset-card]');
    if(assetCard){
        const id = assetCard.dataset.assetCard || '';
        if(assetManageMode){
            const selected = toggleSelectionSet(selectedAssetIds, id);
            selectedAssetId = selected ? id : (selectedAssetId === id ? '' : selectedAssetId);
            assetEditMode = false;
            pendingDeleteAssetId = '';
            pendingBatchDelete = '';
            render();
        } else {
            selectedAssetId = id;
            assetEditMode = false;
            pendingDeleteAssetId = '';
            pendingBatchDelete = '';
            refreshAssetSelectionOnly();
        }
        return;
    }

    const promptEditSave = target.closest?.('[data-prompt-edit-save]');
    if(promptEditSave){ await savePromptEdit(promptEditSave.dataset.promptEditSave || ''); return; }
    if(target.closest?.('[data-prompt-create-save]')){ await savePromptCreate(); return; }
    if(target.closest?.('[data-prompt-edit-cancel]')){ promptEditMode = false; promptCreateMode = false; render(); return; }
    const promptEditStart = target.closest?.('[data-prompt-edit-start]');
    if(promptEditStart){ selectedPromptId = promptEditStart.dataset.promptEditStart || selectedPromptId; promptEditMode = true; promptCreateMode = false; pendingDeletePromptId = ''; render(); return; }
    if(target.closest?.('[data-prompt-manage]')){
        promptManageMode = !promptManageMode;
        pendingBatchDelete = '';
        if(!promptManageMode) selectedPromptIds.clear();
        render();
        return;
    }
    if(target.closest?.('[data-prompt-select-all]')){ toggleMaterialSelection(currentPromptItems(), selectedPromptIds); pendingBatchDelete = ''; render(); return; }
    if(target.closest?.('[data-prompt-clear-selection]')){ selectedPromptIds.clear(); pendingBatchDelete = ''; render(); return; }
    const promptEdit = target.closest?.('[data-prompt-edit]');
    if(promptEdit){ await editPromptItem(promptEdit.dataset.promptEdit || ''); return; }
    const promptDelete = target.closest?.('[data-prompt-delete]');
    if(promptDelete){ await deletePromptItem(promptDelete.dataset.promptDelete || ''); return; }
    if(target.closest?.('[data-prompt-delete-selected]')){ await deleteSelectedPrompts(); return; }
    const promptNewBtn = target.closest?.('[data-prompt-new]');
    if(promptNewBtn){
        const libId = promptNewBtn.dataset.libId || target.closest('[data-prompt-lib]')?.dataset.promptLib;
        const catRow = target.closest('[data-prompt-cat]');
        if(libId){ activePromptLibraryId = libId; activePromptCategory = 'all'; }
        if(catRow){ activePromptLibraryId = catRow.dataset.promptCatLib || activePromptLibraryId; activePromptCategory = catRow.dataset.promptCat || activePromptCategory; }
        promptCreateMode = true; promptEditMode = false; pendingDeletePromptId = ''; render(); return;
    }
    if(target.closest?.('[data-prompt-lib-new]')){ promptTreeFocus = 'library'; promptTreeEdit = {kind:'library-new', placement:'head', value:'新提示词库', label:'提示词库名称'}; render(); focusTreeEditInput('promptTreeEditInput'); return; }
    if(target.closest?.('[data-prompt-cat-new]')){
        const libRow = target.closest('[data-prompt-lib]');
        if(libRow) activePromptLibraryId = libRow.dataset.promptLib || activePromptLibraryId;
        promptTreeFocus = 'library';
        promptTreeEdit = {kind:'category-new', value:'新分组', label:'分组名称'};
        pendingTreeDelete = '';
        render(); return;
    }
    if(target.closest?.('[data-prompt-cat-rename]')){
        promptTreeFocus = 'category';
        const cat = activePromptCategories().find(c => c.id === activePromptCategory);
        promptTreeEdit = {kind:'category-rename', value:cat?.name || '', label:'分组名称'};
        pendingTreeDelete = '';
        render(); return;
    }
    if(target.closest?.('[data-prompt-cat-delete]')){ await deletePromptCategory(); return; }
    const promptLibRenameBtn = target.closest?.('[data-prompt-lib-rename]');
    if(promptLibRenameBtn){
        const libRow = target.closest('[data-prompt-lib]');
        if(promptLibRenameBtn.dataset.libId) activePromptLibraryId = promptLibRenameBtn.dataset.libId;
        if(libRow) activePromptLibraryId = libRow.dataset.promptLib || activePromptLibraryId;
        promptTreeFocus = 'library';
        promptTreeEdit = {kind:'library-rename', value:activePromptLibrary()?.name || '', label:'提示词库名称'};
        render(); return;
    }
    const promptLibDeleteBtn = target.closest?.('[data-prompt-lib-delete]');
    if(promptLibDeleteBtn){
        if(promptLibDeleteBtn.dataset.libId) activePromptLibraryId = promptLibDeleteBtn.dataset.libId;
        await deletePromptLibrary(); return;
    }
    const promptLib = target.closest?.('[data-prompt-lib]');
    if(promptLib){ activePromptLibraryId = promptLib.dataset.promptLib || ''; activePromptCategory = 'all'; promptTreeFocus = 'library'; selectedPromptId = ''; promptCreateMode = false; promptEditMode = false; selectedPromptIds.clear(); render(); return; }
    const promptCat = target.closest?.('[data-prompt-cat]');
    if(promptCat){ activePromptLibraryId = promptCat.dataset.promptCatLib || activePromptLibraryId; activePromptCategory = promptCat.dataset.promptCat || 'all'; promptTreeFocus = 'category'; selectedPromptId = ''; promptCreateMode = false; promptEditMode = false; selectedPromptIds.clear(); render(); return; }
    const promptRow = target.closest?.('[data-prompt-row]');
    if(promptRow){
        const id = promptRow.dataset.promptRow || '';
        if(promptManageMode){
            const selected = toggleSelectionSet(selectedPromptIds, id);
            selectedPromptId = selected ? id : (selectedPromptId === id ? '' : selectedPromptId);
        } else {
            selectedPromptId = id;
        }
        promptEditMode = false;
        promptCreateMode = false;
        pendingDeletePromptId = '';
        pendingBatchDelete = '';
        render();
        return;
    }
}
function openAssetItem(id){
    const item = findAssetItem(id);
    if(item?.url) window.open(item.url, '_blank', 'noopener');
}
function materialOverlayHost(){
    return document.documentElement || document.body;
}
async function showDetailPreview(source, id){
    const item = source === 'local'
        ? findLocalItem(id)
        : source === 'localup'
            ? findLocalUpload(id)
            : source === 'canvas-asset'
                ? findCanvasAssetItem(id)
                : findAssetItem(id);
    if(!item) return;
    const kind = source === 'local' ? (item.kind || localItemKind(item)) : assetKind(item);
    if(!['image','video','audio','text'].includes(kind)){
        setStatus('这个文件暂不支持预览');
        return;
    }
    const url = source === 'local' ? localObjectUrl(item) : item.url;
    if(!url) return;
    document.querySelector('.asset-lightbox')?.remove();
    const overlay = document.createElement('div');
    overlay.className = 'asset-lightbox';
    overlay.dataset.scale = '1';
    overlay.dataset.x = '0';
    overlay.dataset.y = '0';
    overlay.innerHTML = `
        <div class="media-preview-exit-hints"><span>${i18nText("asset.previewEsc","ESC 退出预览")}</span><span>${i18nText("asset.previewBackdrop","点击黑色区域也可退出")}</span></div>
        <div class="asset-lightbox-inner" role="dialog" aria-modal="true" aria-label="${kind === 'video' ? '视频预览' : kind === 'audio' ? '音频播放' : kind === 'text' ? '文本预览' : '图片预览'}">
            ${kind === 'video'
                ? `<video class="asset-lightbox-video" src="${escapeAttr(url)}" controls autoplay playsinline preload="metadata"></video>`
                : kind === 'audio'
                    ? `<div class="asset-lightbox-audio">
                        <div class="asset-audio-waveform" aria-hidden="true"><div class="asset-audio-bars"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div><i data-lucide="${StudioMedia.category(item)==='music'?'music-2':'audio-lines'}"></i></div>
                        <strong>${escapeHtml(item.name || '音频素材')}</strong>
                        <audio src="${escapeAttr(url)}" controls autoplay preload="metadata"></audio>
                    </div>`
                    : kind === 'text'
                        ? `<div class="asset-lightbox-text"><strong>${escapeHtml(item.name || '文本素材')}</strong><pre data-lightbox-text-content>${escapeHtml(i18nText('asset.loadingText', '正在读取文本...'))}</pre></div>`
                        : `<img class="asset-lightbox-image" src="${escapeAttr(url)}" alt="${escapeAttr(item.name || 'preview')}" draggable="false">`}
        </div>
    `;
    materialOverlayHost().appendChild(overlay);
    document.body.classList.add('asset-lightbox-open');
    refreshIcons();
    if(kind === 'text'){
        const content = overlay.querySelector('[data-lightbox-text-content]');
        const embedded = [item.text, item.content, item.value, item.prompt].find(value => typeof value === 'string' && value.trim());
        if(embedded){
            content.textContent = embedded;
        } else {
            try {
                const response = await fetch(url);
                const value = await response.text();
                if(!response.ok) throw new Error('文本读取失败');
                content.textContent = value || i18nText('asset.emptyText', '这个文本文件是空的。');
            } catch(error) {
                content.textContent = error?.message || i18nText('asset.textReadFailed', '文本读取失败');
            }
        }
    }
}
let assetTextEditorState = null;
function textEditorItem(source, id){
    if(source === 'local') return findLocalItem(id);
    if(source === 'localup') return findLocalUpload(id);
    if(source === 'canvas-asset') return findCanvasAssetItem(id);
    return findAssetItem(id);
}
async function readTextEditorContent(item, source){
    const embedded = [item?.text, item?.content, item?.value, item?.prompt]
        .find(value => typeof value === 'string' && value.trim());
    if(embedded) return embedded;
    const url = source === 'local' ? localObjectUrl(item) : item?.url;
    if(!url) return '';
    const response = await fetch(url);
    const value = await response.text();
    if(!response.ok) throw new Error('文本读取失败');
    return value;
}
async function openTextContentEditor(source, id){
    const item = textEditorItem(source, id);
    if(!item) return;
    closeDetailPreview();
    document.querySelector('.asset-text-editor-overlay')?.remove();
    const overlay = document.createElement('div');
    overlay.className = 'asset-text-editor-overlay';
    overlay.innerHTML = `<section class="asset-text-editor" role="dialog" aria-modal="true" aria-label="编辑文本素材">
        <header><div><strong>编辑文本素材</strong><span>${escapeHtml(item.name || item.display_name || '文本素材')}</span></div><button class="asset-icon-btn" type="button" data-text-editor-close title="关闭"><i data-lucide="x"></i></button></header>
        <textarea data-text-editor-content spellcheck="false" placeholder="正在读取文本..."></textarea>
        <footer><span>保存后生成新的文本结果，原文件保持不变。</span><div><button class="asset-btn" type="button" data-text-editor-close>取消</button><button class="asset-btn primary" type="button" data-text-editor-save><i data-lucide="save"></i><span>保存为新结果</span></button></div></footer>
    </section>`;
    materialOverlayHost().appendChild(overlay);
    refreshIcons();
    const textarea = overlay.querySelector('[data-text-editor-content]');
    const saveButton = overlay.querySelector('[data-text-editor-save]');
    assetTextEditorState = {source, id, item, overlay};
    overlay.addEventListener('pointerdown', event => {
        if(event.target === overlay) closeTextContentEditor();
    });
    overlay.addEventListener('click', event => {
        if(event.target.closest('[data-text-editor-close]')) closeTextContentEditor();
        if(event.target.closest('[data-text-editor-save]')) saveTextContentEditor();
    });
    try {
        textarea.value = await readTextEditorContent(item, source);
        textarea.placeholder = '输入文本内容';
        textarea.focus({preventScroll:true});
        textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    } catch(error) {
        textarea.placeholder = error?.message || '文本读取失败';
        saveButton.disabled = true;
        setStatus(error?.message || '文本读取失败');
    }
}
function closeTextContentEditor(){
    assetTextEditorState?.overlay?.remove();
    assetTextEditorState = null;
}
async function saveTextContentEditor(){
    const state = assetTextEditorState;
    const textarea = state?.overlay?.querySelector('[data-text-editor-content]');
    const saveButton = state?.overlay?.querySelector('[data-text-editor-save]');
    const text = String(textarea?.value || '').trim();
    if(!state || !text){
        setStatus('文本内容不能为空');
        return;
    }
    saveButton.disabled = true;
    try {
        const parts = materialNameParts(state.item);
        const sourceCanvas = state.item?.source_canvas || {};
        const response = await apiJson('/api/canvas-text-results', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({
                text,
                name:`${parts.stem || '文本结果'}-编辑.md`,
                canvas_id:sourceCanvas.id || '',
                canvas_title:sourceCanvas.title || ''
            })
        });
        closeTextContentEditor();
        await refreshCanvasAssets();
        selectedCanvasAssetId = response.id || selectedCanvasAssetId;
        if(activeTab === 'results') render();
        setStatus('已生成新的文本结果，原文保留');
    } catch(error) {
        saveButton.disabled = false;
        setStatus(error?.message || '文本保存失败');
    }
}
function closeDetailPreview(){
    document.querySelector('.asset-lightbox')?.remove();
    document.body.classList.remove('asset-lightbox-open');
    lightboxPanState = null;
}
function applyLightboxTransform(overlay){
    const image = overlay?.querySelector?.('.asset-lightbox-image');
    if(!image) return;
    const scale = Number(overlay.dataset.scale || 1);
    const x = Number(overlay.dataset.x || 0);
    const y = Number(overlay.dataset.y || 0);
    image.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
    overlay.classList.toggle('zoomed', scale > 1.01);
}
function zoomDetailPreview(event){
    const overlay = event.target.closest?.('.asset-lightbox');
    const image = event.target.closest?.('.asset-lightbox-image');
    if(!overlay || !image) return;
    event.preventDefault();
    const current = Number(overlay.dataset.scale || 1);
    const next = Math.max(0.25, Math.min(8, current * (event.deltaY < 0 ? 1.15 : 0.87)));
    const rect = overlay.getBoundingClientRect();
    const anchorX = event.clientX - (rect.left + rect.width / 2);
    const anchorY = event.clientY - (rect.top + rect.height / 2);
    const currentX = Number(overlay.dataset.x || 0);
    const currentY = Number(overlay.dataset.y || 0);
    const ratio = next / current;
    overlay.dataset.scale = String(next);
    if(next <= 1.01){
        overlay.dataset.x = '0';
        overlay.dataset.y = '0';
    } else {
        overlay.dataset.x = String(anchorX - ratio * (anchorX - currentX));
        overlay.dataset.y = String(anchorY - ratio * (anchorY - currentY));
    }
    applyLightboxTransform(overlay);
}
function beginLightboxPan(event){
    const image = event.target.closest?.('.asset-lightbox-image');
    const overlay = event.target.closest?.('.asset-lightbox');
    if(!image || !overlay) return;
    const scale = Number(overlay.dataset.scale || 1);
    if(scale <= 1.01) return;
    event.preventDefault();
    lightboxPanState = {
        overlay,
        pointerId:event.pointerId,
        startX:event.clientX,
        startY:event.clientY,
        originX:Number(overlay.dataset.x || 0),
        originY:Number(overlay.dataset.y || 0)
    };
    image.setPointerCapture?.(event.pointerId);
    overlay.classList.add('dragging');
}
function updateLightboxPan(event){
    if(!lightboxPanState || event.pointerId !== lightboxPanState.pointerId) return;
    const {overlay, startX, startY, originX, originY} = lightboxPanState;
    overlay.dataset.x = String(originX + event.clientX - startX);
    overlay.dataset.y = String(originY + event.clientY - startY);
    applyLightboxTransform(overlay);
}
function endLightboxPan(event){
    if(!lightboxPanState || event.pointerId !== lightboxPanState.pointerId) return;
    lightboxPanState.overlay?.classList.remove('dragging');
    lightboxPanState = null;
}
function rectsIntersect(a, b){
    return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}
function marqueeTargetSelector(){
    if(activeTab === 'assets' && activeInputScope === 'asset' && assetManageMode) return '[data-asset-card]';
    if(activeTab === 'prompts' && promptManageMode) return '[data-prompt-row]';
    if(activeTab === 'assets' && activeInputScope === 'temporary' && localUploadManageMode) return '[data-localup-card]';
    if(activeTab === 'results' && canvasAssetManageMode) return '[data-canvas-asset-card]';
    return '';
}
function beginMarqueeSelection(event){
    const selector = marqueeTargetSelector();
    if(!selector) return;
    if(event.button !== 0) return;
    if(event.target.closest?.('button,input,textarea,select,.side-upload-card,.upload-grid-card,.asset-search-wrap')) return;
    const area = event.target.closest?.('.content-scroll');
    if(!area) return;
    event.preventDefault();
    const box = document.createElement('div');
    box.className = 'selection-marquee';
    area.appendChild(box);
    marqueeState = {
        startX:event.clientX,
        startY:event.clientY,
        area,
        box,
        selector,
        baseAsset:new Set(selectedAssetIds),
        basePrompt:new Set(selectedPromptIds),
        baseLocal:new Set(selectedLocalUploadIds),
        baseCanvasAsset:new Set(selectedCanvasAssetIds)
    };
    updateMarqueeSelection(event);
}
function updateMarqueeSelection(event){
    if(!marqueeState) return;
    const left = Math.min(marqueeState.startX, event.clientX);
    const top = Math.min(marqueeState.startY, event.clientY);
    const right = Math.max(marqueeState.startX, event.clientX);
    const bottom = Math.max(marqueeState.startY, event.clientY);
    const areaRect = marqueeState.area.getBoundingClientRect();
    const boxLeft = left - areaRect.left + marqueeState.area.scrollLeft;
    const boxTop = top - areaRect.top + marqueeState.area.scrollTop;
    Object.assign(marqueeState.box.style, {
        left:`${boxLeft}px`,
        top:`${boxTop}px`,
        width:`${Math.max(1, right - left)}px`,
        height:`${Math.max(1, bottom - top)}px`
    });
    const rect = {left, top, right, bottom};
    if(activeTab === 'assets' && activeInputScope === 'asset'){
        selectedAssetIds = new Set(marqueeState.baseAsset);
        document.querySelectorAll(marqueeState.selector).forEach(el => {
            if(rectsIntersect(rect, el.getBoundingClientRect())) selectedAssetIds.add(el.dataset.assetCard);
        });
    } else if(activeTab === 'prompts') {
        selectedPromptIds = new Set(marqueeState.basePrompt);
        document.querySelectorAll(marqueeState.selector).forEach(el => {
            if(rectsIntersect(rect, el.getBoundingClientRect())) selectedPromptIds.add(el.dataset.promptRow);
        });
    } else if(activeTab === 'assets' && activeInputScope === 'temporary') {
        selectedLocalUploadIds = new Set(marqueeState.baseLocal);
        document.querySelectorAll(marqueeState.selector).forEach(el => {
            if(rectsIntersect(rect, el.getBoundingClientRect())) selectedLocalUploadIds.add(el.dataset.localupCard);
        });
    } else if(activeTab === 'results') {
        selectedCanvasAssetIds = new Set(marqueeState.baseCanvasAsset);
        document.querySelectorAll(marqueeState.selector).forEach(el => {
            if(rectsIntersect(rect, el.getBoundingClientRect())) selectedCanvasAssetIds.add(el.dataset.canvasAssetCard);
        });
    }
    document.querySelectorAll('[data-asset-check]').forEach(input => { input.checked = selectedAssetIds.has(input.dataset.assetCheck); });
    document.querySelectorAll('[data-prompt-check]').forEach(input => { input.checked = selectedPromptIds.has(input.dataset.promptCheck); });
    document.querySelectorAll('[data-localup-check]').forEach(input => { input.checked = selectedLocalUploadIds.has(input.dataset.localupCheck); });
    document.querySelectorAll('[data-canvas-asset-check]').forEach(input => { input.checked = selectedCanvasAssetIds.has(input.dataset.canvasAssetCheck); });
}
function endMarqueeSelection(){
    if(!marqueeState) return;
    marqueeState.box.remove();
    marqueeState = null;
    pendingBatchDelete = '';
    render();
}
async function createAssetLibrary(){
    assetTreeFocus = 'library';
    assetTreeEdit = {kind:'library-new', placement:'head', value:'新资产库', label:'资产库名称'};
    pendingTreeDelete = '';
    render();
    focusTreeEditInput('assetTreeEditInput');
}
async function saveAssetTreeEdit(){
    if(!assetTreeEdit) return;
    const name = document.getElementById('assetTreeEditInput')?.value || '';
    if(!String(name || '').trim()){
        setStatus('名称不能为空');
        return;
    }
    let data = null;
    if(assetTreeEdit.kind === 'library-new'){
        data = await apiJson('/api/asset-library/libraries', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
        assetLibrary = data.library || assetLibrary;
        activeAssetLibraryId = data.asset_library?.id || activeAssetLibraryId;

        assetTreeFocus = 'library';
    } else if(assetTreeEdit.kind === 'library-rename'){
        const lib = activeAssetLibrary();
        if(!lib) return;
        data = await apiJson(`/api/asset-library/libraries/${encodeURIComponent(lib.id)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
        assetLibrary = data.library || assetLibrary;
        assetTreeFocus = 'library';
    } else if(assetTreeEdit.kind === 'category-new'){
        data = await apiJson('/api/asset-library/categories', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({library_id:activeAssetLibraryId, name, type:'image'})});
        assetLibrary = data.library || assetLibrary;
        activeAssetCategoryId = data.category?.id || activeAssetCategoryId;

        assetTreeFocus = 'category';
    } else if(assetTreeEdit.kind === 'category-rename'){
        const cat = activeAssetCategory();
        if(!cat) return;
        data = await apiJson(`/api/asset-library/categories/${encodeURIComponent(cat.id)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
        assetLibrary = data.library || assetLibrary;
        assetTreeFocus = 'category';
    }
    assetTreeEdit = null;
    pendingTreeDelete = '';
    render();
    setStatus('已保存');
}
async function saveWorkflowTreeEdit(){
    if(!workflowTreeEdit) return;
    const name = document.getElementById('workflowTreeEditInput')?.value || '';
    if(!String(name || '').trim()){
        setStatus('名称不能为空');
        return;
    }
    if(workflowTreeEdit.kind === 'category-new'){
        const lib = activeWorkflowLibrary();
        if(!lib){
            setStatus('请先选择资产库');
            return;
        }
        activeWorkflowLibraryId = lib.id || activeWorkflowLibraryId;
        const data = await apiJson('/api/asset-library/categories', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({library_id:activeWorkflowLibraryId, name, type:'workflow'})
        });
        assetLibrary = data.library || assetLibrary;
        activeWorkflowCategoryId = data.category?.id || activeWorkflowCategoryId;
    } else if(workflowTreeEdit.kind === 'category-rename'){
        const cat = activeWorkflowCategory();
        const categoryId = workflowTreeEdit.categoryId || cat?.id || activeWorkflowCategoryId;
        if(!categoryId) return;
        const data = await apiJson(`/api/asset-library/categories/${encodeURIComponent(categoryId)}`, {
            method:'PATCH',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({name, library_id:activeWorkflowLibraryId})
        });
        assetLibrary = data.library || assetLibrary;
        activeWorkflowCategoryId = categoryId;
    }
    workflowTreeEdit = null;
    pendingTreeDelete = '';
    render();
    setStatus('已保存');
}
async function deleteWorkflowCategory(){
    const cat = activeWorkflowCategory();
    if(!cat) return;
    const libraryId = cat.__libraryId || activeWorkflowLibraryId;
    const key = `workflow-cat:${libraryId}:${cat.id}`;
    if(pendingTreeDelete !== key){
        pendingTreeDelete = key;
        workflowTreeEdit = null;
        render();
        setStatus('再次点击确认删除工作流分组');
        return;
    }
    const data = await apiJson(`/api/asset-library/categories/${encodeURIComponent(cat.id)}?library_id=${encodeURIComponent(libraryId)}`, {method:'DELETE'});
    assetLibrary = data.library || assetLibrary;
    activeWorkflowCategoryId = '';
    selectedWorkflowId = '';
    selectedWorkflowIds.clear();
    pendingTreeDelete = '';
    render();
    setStatus('工作流分组已删除');
}
async function renameAssetLibrary(){
    const lib = activeAssetLibrary();
    if(!lib) return;
    assetTreeFocus = 'library';
    assetTreeEdit = {kind:'library-rename', value:lib.name || '', label:'资产库名称'};
    pendingTreeDelete = '';
    render();
    focusTreeEditInput('assetTreeEditInput');
}
async function deleteAssetLibrary(){
    const lib = activeAssetLibrary();
    if(!lib) return;
    const key = `asset-lib:${lib.id}`;
    if(pendingTreeDelete !== key){
        pendingTreeDelete = key;
        assetTreeEdit = null;
        render();
        setStatus('再次点击确认删除资产库');
        return;
    }
    const data = await apiJson(`/api/asset-library/libraries/${encodeURIComponent(lib.id)}`, {method:'DELETE'});
    assetLibrary = data.library || assetLibrary;
    activeAssetLibraryId = assetLibrary.active_library_id || assetLibraries()[0]?.id || '';
    activeAssetCategoryId = '';

    selectedAssetId = '';
    selectedAssetIds.clear();
    pendingTreeDelete = '';
    render();
}
async function createAssetCategory(){
    assetTreeEdit = {kind:'category-new', value:'新分组', label:'分组名称'};
    pendingTreeDelete = '';
    render();
}
async function renameAssetCategory(){
    const cat = activeAssetCategory();
    if(!cat) return;
    assetTreeFocus = 'category';
    assetTreeEdit = {kind:'category-rename', value:cat.name || '', label:'分组名称'};
    pendingTreeDelete = '';
    render();
}
async function deleteAssetCategory(){
    const cat = activeAssetCategory();
    if(!cat) return;
    const key = `asset-cat:${cat.id}`;
    if(pendingTreeDelete !== key){
        pendingTreeDelete = key;
        assetTreeEdit = null;
        render();
        setStatus('再次点击确认删除分组');
        return;
    }
    const data = await apiJson(`/api/asset-library/categories/${encodeURIComponent(cat.id)}`, {method:'DELETE'});
    assetLibrary = data.library || assetLibrary;
    activeAssetCategoryId = '';

    selectedAssetId = '';
    selectedAssetIds.clear();
    pendingTreeDelete = '';
    render();
}
async function renameAssetItem(id){
    const item = findAssetItem(id);
    if(!item) return;
    selectedAssetId = id;
    render();
    requestAnimationFrame(() => beginAssetInlineRename(id));
}
async function saveAssetEdit(id){
    const item = findAssetItem(id);
    const name = document.getElementById('assetEditName')?.value || '';
    if(!item || !String(name || '').trim()) {
        setStatus('素材名称不能为空');
        return;
    }
    const data = await apiJson(`/api/asset-library/items/${encodeURIComponent(id)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
    assetLibrary = data.library || assetLibrary;
    selectedAssetId = id;
    assetEditMode = false;
    render();
    setStatus('素材已保存');
}
async function saveAssetInlineName(id, name){
    const item = findAssetItem(id);
    name = materialNameStem(name);
    if(!item || !String(name || '').trim()) return;
    if(materialNameParts(item).stem === String(name || '').trim()) return;
    const data = await apiJson(`/api/asset-library/items/${encodeURIComponent(id)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
    assetLibrary = data.library || assetLibrary;
    selectedAssetId = id;
    render();
    setStatus('素材名称已保存');
}
async function deleteAssetItem(id){
    const item = findAssetItem(id);
    if(!item) return;
    const data = await apiJson(`/api/asset-library/items/${encodeURIComponent(id)}`, {method:'DELETE'});
    assetLibrary = data.library || assetLibrary;
    selectedAssetIds.delete(id);
    if(selectedAssetId === id) selectedAssetId = '';
    pendingDeleteAssetId = '';
    render();
    setStatus('素材已删除');
}
async function deleteSelectedAssets(){
    if(!selectedAssetIds.size) return;
    const ids = [...selectedAssetIds];
    const data = await apiJson('/api/asset-library/items/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({library_id:activeAssetLibraryId, ids})});
    assetLibrary = data.library || assetLibrary;
    if(ids.includes(selectedAssetId)) selectedAssetId = '';
    selectedAssetIds.clear();
    pendingBatchDelete = '';
    render();
    setStatus(`已删除 ${data.removed || ids.length} 个素材`);
}
function setAssetClipboard(mode){
    if(!selectedAssetIds.size) return;
    assetClipboard = {
        mode,
        ids:[...selectedAssetIds],
        sourceLibraryId:activeAssetLibraryId,
        sourceCategoryId:activeAssetCategoryId,
        items:[...selectedAssetIds].map(id => findAssetItem(id)).filter(Boolean)
    };
    selectedAssetIds.clear();
    pendingBatchDelete = '';
    render();
    const label = mode === 'cut' ? '剪切' : '复制';
    setStatus(`${label}了 ${assetClipboard.ids.length} 个素材，切换分组后粘贴`);
}
async function pasteAssetClipboard(){
    if(!assetClipboard?.ids?.length) return;
    if(assetClipboard.mode === 'cut'){
        if(assetClipboard.sourceLibraryId === activeAssetLibraryId && assetClipboard.sourceCategoryId === activeAssetCategoryId) return;
        const data = await apiJson('/api/asset-library/items/move', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({library_id:assetClipboard.sourceLibraryId, target_library_id:activeAssetLibraryId, target_category_id:activeAssetCategoryId, ids:assetClipboard.ids})
        });
        assetLibrary = data.library || assetLibrary;
        setStatus(`已移动 ${data.moved || 0} 个素材`);
    } else {
        const items = (assetClipboard.items || []).map(item => ({url:item.url, name:item.name || 'asset'})).filter(item => item.url);
        const data = await apiJson('/api/asset-library/items/batch', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({library_id:activeAssetLibraryId, category_id:activeAssetCategoryId, items})
        });
        assetLibrary = data.library || assetLibrary;
        setStatus(`已复制 ${data.items?.length || 0} 个素材`);
    }
    assetClipboard = null;
    selectedAssetIds.clear();
    selectedAssetId = '';
    render();
}
function setLocalClipboard(mode, ids=null){
    // 共享文件夹只读，仅支持「复制」（引用导入），不支持剪切删除源文件
    const sourceIds = Array.isArray(ids) ? ids.filter(Boolean) : [...selectedLocalIds];
    if(!sourceIds.length) return;
    const items = sourceIds.map(id => findLocalItem(id)).filter(Boolean);
    if(!items.length) return;
    localClipboard = {
        mode:'copy',
        ids:items.map(item => item.id),
        items,
        sourceRootName:activeSharedFolderName || '共享文件夹'
    };
    selectedLocalIds.clear();
    pendingBatchDelete = '';
    render();
    setStatus(`复制了 ${items.length} 个共享素材，导入后会保存到资产素材分组（共享文件夹原文件保留）`);
}
async function pasteLocalClipboardToAssets(){
    if(!localClipboard?.items?.length) return;
    if(!activeAssetCategory()){
        setStatus('请先在资产素材中创建或选择分组');
        return;
    }
    const clip = localClipboard;
    // 按所属共享文件夹分组，调用后端按路径导入（复制到素材库，无需走浏览器文件对象）
    const groups = new Map();
    clip.items.forEach(item => {
        if(!item || !item.folderId || !item.relativePath) return;
        if(!groups.has(item.folderId)) groups.set(item.folderId, []);
        groups.get(item.folderId).push(item.relativePath);
    });
    if(!groups.size) return;
    setStatus('正在导入共享素材...');
    let imported = 0;
    try {
        for(const [folderId, paths] of groups){
            const data = await apiJson('/api/shared-folders/import', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({library_id:activeAssetLibraryId, category_id:activeAssetCategoryId, folder_id:folderId, paths})
            });
            assetLibrary = data.library || assetLibrary;
            imported += (data.items?.length || 0);
        }
    } catch(err) {
        setStatus(err.message || '导入共享素材失败');
        return;
    }
    localClipboard = null;
    selectedLocalIds.clear();
    selectedLocalId = '';
    render();
    setStatus(`已导入 ${imported} 个素材到资产素材`);
}
async function moveSelectedAssets(){
    if(!selectedAssetIds.size || !assetMoveTarget) return;
    const [targetLibraryId, targetCategoryId] = assetMoveTarget.split('::');
    if(!targetLibraryId || !targetCategoryId) return;
    const ids = [...selectedAssetIds];
    const data = await apiJson('/api/asset-library/items/move', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({library_id:activeAssetLibraryId, target_library_id:targetLibraryId, target_category_id:targetCategoryId, ids})
    });
    assetLibrary = data.library || assetLibrary;
    selectedAssetIds.clear();
    if(ids.includes(selectedAssetId)) selectedAssetId = '';
    render();
    setStatus(`已移动 ${data.moved || 0} 个素材`);
}
function openLocalItem(id){
    const item = findLocalItem(id);
    if(!item) return;
    const url = localObjectUrl(item);
    if(url) window.open(url, '_blank', 'noopener');
}
async function createPromptLibrary(){
    promptTreeFocus = 'library';
    promptTreeEdit = {kind:'library-new', placement:'head', value:'新提示词库', label:'提示词库名称'};
    pendingTreeDelete = '';
    render();
    focusTreeEditInput('promptTreeEditInput');
}
async function savePromptTreeEdit(){
    if(!promptTreeEdit) return;
    const name = document.getElementById('promptTreeEditInput')?.value || '';
    if(!String(name || '').trim()){
        setStatus('名称不能为空');
        return;
    }
    let data = null;
    if(promptTreeEdit.kind === 'library-new'){
        data = await apiJson('/api/prompt-libraries', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
        promptLibrary = data.library || promptLibrary;
        activePromptLibraryId = data.prompt_library?.id || activePromptLibraryId;
        activePromptCategory = 'all';
        promptTreeFocus = 'library';
    } else if(promptTreeEdit.kind === 'library-rename'){
        const lib = activePromptLibrary();
        if(!lib) return;
        data = await apiJson(`/api/prompt-libraries/${encodeURIComponent(lib.id)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
        promptLibrary = data.library || promptLibrary;
        promptTreeFocus = 'library';
    } else if(promptTreeEdit.kind === 'category-new'){
        const lib = activePromptLibrary();
        data = await apiJson('/api/prompt-libraries/categories', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({library_id:lib?.id || 'system', name})});
        promptLibrary = data.library || promptLibrary;
        activePromptCategory = data.category?.id || activePromptCategory;
        promptTreeFocus = 'category';
    } else if(promptTreeEdit.kind === 'category-rename'){
        data = await apiJson(`/api/prompt-libraries/categories/${encodeURIComponent(activePromptCategory)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
        promptLibrary = data.library || promptLibrary;
        promptTreeFocus = 'category';
    }
    promptTreeEdit = null;
    pendingTreeDelete = '';
    notifyPromptLibraryUpdated();
    render();
    setStatus('已保存');
}
async function deletePromptCategory(){
    if(activePromptCategory === 'all'){
        setStatus('请选择具体分组后删除');
        return;
    }
    if(activePromptCategory === PROMPT_UNCATEGORIZED_CATEGORY_ID){
        setStatus('未分类不可删除');
        return;
    }
    const data = await apiJson(`/api/prompt-libraries/categories/${encodeURIComponent(activePromptCategory)}`, {method:'DELETE'});
    promptLibrary = data.library || promptLibrary;
    activePromptCategory = 'all';
    pendingTreeDelete = '';
    notifyPromptLibraryUpdated();
    render();
    setStatus('分组已删除');
}
async function renamePromptLibrary(){
    const lib = activePromptLibrary();
    if(!lib) return;
    promptTreeFocus = 'library';
    promptTreeEdit = {kind:'library-rename', value:lib.name || '', label:'提示词库名称'};
    pendingTreeDelete = '';
    render();
    focusTreeEditInput('promptTreeEditInput');
}
async function deletePromptLibrary(){
    const lib = activePromptLibrary();
    if(!lib) return;
    if(isSystemPromptLibrary(lib)){ setStatus('系统提示词库不能删除'); return; }
    const data = await apiJson(`/api/prompt-libraries/${encodeURIComponent(lib.id)}`, {method:'DELETE'});
    promptLibrary = data.library || promptLibrary;
    activePromptLibraryId = promptLibrary.active_library_id || promptLibraries()[0]?.id || 'system';
    activePromptCategory = 'all';
    selectedPromptId = '';
    selectedPromptIds.clear();
    pendingTreeDelete = '';
    notifyPromptLibraryUpdated();
    render();
    setStatus('提示词库已删除');
}
async function createPromptItem(){
    if(!activePromptLibrary()) return;
    promptCreateMode = true;
    promptEditMode = false;
    pendingDeletePromptId = '';
    render();
}
async function savePromptCreate(){
    const lib = activePromptLibrary();
    const name = document.getElementById('promptEditName')?.value || '';
    const scene = document.getElementById('promptEditScene')?.value || '';
    const positive = document.getElementById('promptEditPositive')?.value || '';
    const negative = document.getElementById('promptEditNegative')?.value || '';
    if(!lib) return;
    if(!String(name || '').trim() || !String(positive || '').trim()){
        setStatus('名称和正向提示词不能为空');
        return;
    }
    const category = activePromptCategory === 'all' ? PROMPT_UNCATEGORIZED_CATEGORY_ID : activePromptCategory;
    const data = await apiJson('/api/prompt-libraries/items', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({library_id:lib.id, name, positive, negative, category, scene})});
    promptLibrary = data.library || promptLibrary;
    selectedPromptId = data.item?.id || selectedPromptId;
    promptCreateMode = false;
    notifyPromptLibraryUpdated();
    render();
    setStatus('提示词已新增');
}
async function editPromptItem(id){
    const item = findPromptItem(id);
    const lib = activePromptLibrary();
    if(!item || !lib) return;
    selectedPromptId = id;
    promptEditMode = true;
    promptCreateMode = false;
    pendingDeletePromptId = '';
    render();
}
async function savePromptEdit(id){
    const item = findPromptItem(id);
    const lib = activePromptLibrary();
    const name = document.getElementById('promptEditName')?.value || '';
    const scene = document.getElementById('promptEditScene')?.value || '';
    const positive = document.getElementById('promptEditPositive')?.value || '';
    const negative = document.getElementById('promptEditNegative')?.value || '';
    if(!item || !lib) return;
    if(!String(name || '').trim() || !String(positive || '').trim()){
        setStatus('名称和正向提示词不能为空');
        return;
    }
    const data = await apiJson(`/api/prompt-libraries/items/${encodeURIComponent(id)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({library_id:lib.id, name, positive, negative, category:item.category || PROMPT_UNCATEGORIZED_CATEGORY_ID, scene})});
    promptLibrary = data.library || promptLibrary;
    selectedPromptId = id;
    promptEditMode = false;
    notifyPromptLibraryUpdated();
    render();
    setStatus('提示词已保存');
}
async function deletePromptItem(id){
    const item = findPromptItem(id);
    if(!item) return;
    const data = await apiJson(`/api/prompt-libraries/items/${encodeURIComponent(id)}`, {method:'DELETE'});
    promptLibrary = data.library || promptLibrary;
    selectedPromptIds.delete(id);
    if(selectedPromptId === id) selectedPromptId = '';
    pendingDeletePromptId = '';
    notifyPromptLibraryUpdated();
    render();
    setStatus('提示词已删除');
}
async function deleteSelectedPrompts(){
    if(!selectedPromptIds.size) return;
    const ids = [...selectedPromptIds];
    const data = await apiJson('/api/prompt-libraries/items/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ids})});
    promptLibrary = data.library || promptLibrary;
    if(ids.includes(selectedPromptId)) selectedPromptId = '';
    selectedPromptIds.clear();
    pendingBatchDelete = '';
    notifyPromptLibraryUpdated();
    render();
}
root.addEventListener('pointerdown', event => {
    if(event.button !== 0) return;
    const target = managedSelectionTarget(event.target);
    if(!target) return;
    event.preventDefault();
    event.stopPropagation();
    applyManagedSelection(target.kind, target.id);
    managedSelectionPointerGuard = {...target, at:Date.now()};
    render();
}, true);
root.addEventListener('dblclick', event => {
    if(event.target.closest?.('button,input,textarea,select')) return;
    const localUploadCard = event.target.closest?.('[data-localup-card]');
    if(localUploadCard && !localUploadManageMode){
        showDetailPreview('localup', localUploadCard.dataset.localupCard || '');
        return;
    }
    const assetCard = event.target.closest?.('[data-asset-card]');
    if(assetCard && !assetManageMode){
        showDetailPreview('asset', assetCard.dataset.assetCard || '');
        return;
    }
    const canvasAssetCard = event.target.closest?.('[data-canvas-asset-card]');
    if(canvasAssetCard && !canvasAssetManageMode){
        showDetailPreview('canvas-asset', canvasAssetCard.dataset.canvasAssetCard || '');
        return;
    }
    const localCard = event.target.closest?.('[data-local-card]');
    if(localCard && !localManageMode){
        showDetailPreview('local', localCard.dataset.localCard || '');
    }
});
root.addEventListener('click', event => {
    handleClick(event).catch(err => setStatus(err.message || '操作失败'));
});
document.addEventListener('click', event => {
    if(event.target.closest?.('.asset-lightbox') && !event.target.closest?.('.asset-lightbox-image,.asset-lightbox-video,.asset-lightbox-audio,.asset-lightbox-text')) closeDetailPreview();
});
document.addEventListener('keydown', event => {
    if(event.key === 'Escape'){
        closeDetailPreview();
        closeTextContentEditor();
    }
    if(event.target?.id === 'assetTreeEditInput'){
        if(event.key === 'Enter'){ event.preventDefault(); saveAssetTreeEdit().catch(err => setStatus(err.message || '保存失败')); }
        if(event.key === 'Escape'){ event.preventDefault(); assetTreeEdit = null; render(); }
    }
    if(event.target?.id === 'workflowTreeEditInput'){
        if(event.key === 'Enter'){ event.preventDefault(); saveWorkflowTreeEdit().catch(err => setStatus(err.message || '保存失败')); }
        if(event.key === 'Escape'){ event.preventDefault(); workflowTreeEdit = null; render(); }
    }
    if(event.target?.id === 'promptTreeEditInput'){
        if(event.key === 'Enter'){ event.preventDefault(); savePromptTreeEdit().catch(err => setStatus(err.message || '保存失败')); }
        if(event.key === 'Escape'){ event.preventDefault(); promptTreeEdit = null; render(); }
    }
});
document.addEventListener('wheel', zoomDetailPreview, {passive:false});
document.addEventListener('pointerdown', beginLightboxPan);
document.addEventListener('pointermove', updateLightboxPan);
document.addEventListener('pointerup', endLightboxPan);
document.addEventListener('pointercancel', endLightboxPan);
root.addEventListener('pointerdown', beginMarqueeSelection);
document.addEventListener('pointermove', event => updateMarqueeSelection(event));
document.addEventListener('pointerup', endMarqueeSelection);
window.addEventListener('storage', event => {
    if(event.key !== PROMPT_LIBRARY_UPDATED_KEY) return;
    refreshPromptLibraries().catch(error => setStatus(error.message || '提示词库同步失败'));
});
root.addEventListener('compositionstart', event => {
    if(SEARCH_INPUT_IDS.has(event.target?.id || '')){
        searchCompositionActive = true;
        clearTimeout(searchRenderTimer);
    }
});
root.addEventListener('compositionend', event => {
    const id = event.target?.id || '';
    if(!SEARCH_INPUT_IDS.has(id)) return;
    searchCompositionActive = false;
    lastSearchCompositionEndAt = Date.now();
    updateSearchQueryFromInput(id, event.target.value || '');
    scheduleSearchRender(id, event.target.selectionStart || String(event.target.value || '').length, 0);
});
root.addEventListener('input', event => {
    const searchId = event.target?.id || '';
    if(SEARCH_INPUT_IDS.has(searchId)){
        updateSearchQueryFromInput(searchId, event.target.value || '');
        if(event.isComposing || searchCompositionActive) return;
        if(Date.now() - lastSearchCompositionEndAt < 40) return;
        scheduleSearchRender(searchId, event.target.selectionStart || 0);
        return;
    }
    if(event.target?.id === 'localCaptionPrompt'){
        localCaptionPrompt = event.target.value || '';
        writeLocalCaptionSettings();
    }
});
root.addEventListener('change', event => {
    const inlineLocalUploadName = event.target.closest?.('[data-localup-inline-name]');
    if(inlineLocalUploadName){
        saveLocalUploadInlineName(inlineLocalUploadName.dataset.localupInlineName || '', inlineLocalUploadName.value || '').catch(err => setStatus(err.message || '保存失败'));
        return;
    }
    const inlineAssetName = event.target.closest?.('[data-asset-inline-name]');
    if(inlineAssetName){
        saveAssetInlineName(inlineAssetName.dataset.assetInlineName || '', inlineAssetName.value || '').catch(err => setStatus(err.message || '保存失败'));
        return;
    }
    const inlineResultName = event.target.closest?.('[data-result-inline-name]');
    if(inlineResultName){
        saveResultInlineName(inlineResultName.dataset.resultInlineName || '', inlineResultName.value || '').catch(err => setStatus(err.message || '保存失败'));
        return;
    }
    const inlineWorkflowName = event.target.closest?.('[data-workflow-inline-name]');
    if(inlineWorkflowName){
        apiJson(`/api/asset-library/items/${encodeURIComponent(inlineWorkflowName.dataset.workflowInlineName || '')}`, {
            method:'PATCH',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({name:inlineWorkflowName.value || ''})
        }).then(data => {
            assetLibrary = data.library || assetLibrary;
            render();
            setStatus('已保存工作流名称');
        }).catch(err => setStatus(err.message || '保存失败'));
        return;
    }
    if(event.target?.id === 'canvasAssetSort'){
        canvasAssetSort = event.target.value || 'updated_desc';
        selectedCanvasAssetId = '';
        render();
    }
    if(event.target?.id === 'assetMoveTarget'){
        assetMoveTarget = event.target.value || '';
        pendingBatchDelete = '';
        render();
    }
    if(event.target?.id === 'localCaptionProvider'){
        localCaptionProvider = event.target.value || '';
        localCaptionModel = '';
        normalizeLocalCaptionSettings();
        writeLocalCaptionSettings();
        render();
    }
    if(event.target?.id === 'localCaptionModel'){
        localCaptionModel = event.target.value || '';
        writeLocalCaptionSettings();
        render();
    }
});
root.addEventListener('dragover', event => {
    const drop = event.target.closest?.('#assetDrop, #localUploadDrop, #workflowDrop');
    if(!drop) return;
    event.preventDefault();
    drop.classList.add('drag-over');
});
root.addEventListener('dragleave', event => {
    event.target.closest?.('#assetDrop, #localUploadDrop, #workflowDrop')?.classList.remove('drag-over');
});
root.addEventListener('drop', event => {
    const drop = event.target.closest?.('#assetDrop, #localUploadDrop, #workflowDrop');
    if(!drop) return;
    event.preventDefault();
    drop.classList.remove('drag-over');
    if(drop.id === 'localUploadDrop') uploadLocalAssets(event.dataTransfer.files);
    else if(drop.id === 'workflowDrop') uploadWorkflowFiles(event.dataTransfer.files).catch(err => setStatus(err.message || '上传失败'));
    else uploadFiles(event.dataTransfer.files).catch(err => setStatus(err.message || '上传失败'));
});
uploadInput?.addEventListener('change', event => {
    const files = event.target.files;
    if(files?.length){
        if(activeTab === 'assets' && activeInputScope === 'temporary') uploadLocalAssets(files);
        else if(activeTab === 'workflows') uploadWorkflowFiles(files).catch(err => setStatus(err.message || '上传失败'));
        else uploadFiles(files).catch(err => setStatus(err.message || '上传失败'));
    }
    event.target.value = '';
});
document.querySelectorAll('[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
        activeTab = btn.dataset.tab || 'assets';
        selectedAssetIds.clear();
        selectedWorkflowIds.clear();
        selectedPromptIds.clear();
        selectedLocalIds.clear();
        selectedLocalUploadIds.clear();
        selectedCanvasAssetIds.clear();
        render();
    });
});
refreshBtn?.addEventListener('click', () => loadAll().catch(err => setStatus(err.message || '加载失败')));
document.addEventListener('DOMContentLoaded', () => loadAll().catch(err => setStatus(err.message || '加载失败')));

function renderSelectToggle(prefix, items, selected){
    const all = items.length > 0 && items.every(item=>selected.has(item.id));
    return `<button class="asset-btn" type="button" data-${prefix}-select-all role="checkbox" aria-checked="${all?'true':selected.size?'mixed':'false'}" ${items.length?'':'disabled'}><i data-lucide="${all?'check-square':selected.size?'minus-square':'square'}"></i><span>${all?i18nText('asset.clear','清空'):i18nText('asset.selectAll','全选')}</span></button>`;
}
function toggleMaterialSelection(items, selected){
    if(items.length && items.every(item=>selected.has(item.id))) selected.clear();
    else items.forEach(item=>selected.add(item.id));
}
async function copyLibraryMaterials(){
    let items=[], selected=new Set(), focused='';
    if(activeTab==='results'){ items=currentCanvasAssetItems();selected=selectedCanvasAssetIds;focused=selectedCanvasAssetId; }
    else if(activeTab==='assets' && activeInputScope==='temporary'){ items=localUploadItems();selected=selectedLocalUploadIds;focused=selectedLocalUploadId; }
    else if(activeTab==='assets'){ items=currentAssetItems();selected=selectedAssetIds;focused=selectedAssetId; }
    else if(activeTab==='workflows'){ items=currentWorkflowItems();selected=selectedWorkflowIds;focused=selectedWorkflowId; }
    else if(activeTab==='prompts'){ items=currentPromptItems().map(item=>({...item,kind:'text',text:[item.positive,item.negative].filter(Boolean).join('\n\n')}));selected=selectedPromptIds;focused=selectedPromptId; }
    const chosen=items.filter(item=>selected.size?selected.has(item.id):item.id===focused);
    if(!chosen.length) return;
    try { await StudioMedia.copy(chosen);setStatus(i18nText('asset.copiedMaterials','素材已复制，可粘贴到其他应用')); }
    catch(error){setStatus(error.message);}
}
document.addEventListener('keydown',event=>{
    if((event.metaKey||event.ctrlKey)&&!event.shiftKey&&event.key.toLowerCase()==='c'&&!event.target.closest('textarea,[contenteditable="true"],input:not([type=checkbox]):not([type=radio]):not([type=button])')){
        event.preventDefault();copyLibraryMaterials();
    }
});
// 浏览器菜单“复制”和系统原生复制命令也使用同一素材出口。
document.addEventListener('copy',event=>{
    if(event.target.closest?.('textarea,[contenteditable="true"],input:not([type=checkbox]):not([type=radio]):not([type=button])') || window.getSelection()?.toString()) return;
    event.preventDefault();copyLibraryMaterials();
});
