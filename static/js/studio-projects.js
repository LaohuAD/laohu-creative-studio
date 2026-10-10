/* 共用项目列表：各模块共用项目存储和交互，不复制项目数据。 */
(function(){
    'use strict';

    const page = document.querySelector('.studio-project-page');
    if(!page) return;

    const params = new URLSearchParams(location.search);
    const supportedModules = ['canvas','hypit','article','music'];
    const requestedModule = String(params.has('module') ? params.get('module') : (document.body?.dataset?.studioModule || 'canvas')).trim().toLowerCase();
    const moduleIsValid = supportedModules.includes(requestedModule);
    const module = moduleIsValid ? requestedModule : null;
    const focusedProjectId = params.get('id') || '';
    const state = { projects: [], loading: true, query: '', blockedProject: null, trashCount: 0, loadError: '', templates: [], templatesLoading: true, templatesError: '', selectedTemplateId: '' };

    const moduleCopy = {
        canvas: {
            zh: { title:'画布', description:'整理素材、连接画布节点，逐步完成作品。', listTitle:'画布项目', empty:'还没有画布项目', emptyHint:'创建项目后，点击项目卡片上的“打开项目”进入画布。', newName:'新画布项目', prepared:'画布环境', module:'画布' },
            en: { title:'Canvas', description:'Organise assets, connect canvas nodes and build each piece step by step.', listTitle:'Canvas projects', empty:'No canvas projects yet', emptyHint:'Create a project, then choose Open project on its card.', newName:'New canvas project', prepared:'Canvas environment', module:'Canvas' }
        },
        hypit: {
            zh: { title:'Hypit克隆', description:'管理 Hypit 视频复刻项目，连接外部 Agent，并查看制作内容与结果。', listTitle:'Hypit克隆项目', empty:'还没有 Hypit克隆项目', emptyHint:'创建项目后，点击卡片上的“Agent 接入”复制指令，或点击“打开项目”查看作品。', newName:'新 Hypit克隆项目', prepared:'准备创作技能', module:'Hypit克隆' },
            en: { title:'Hypit Clone', description:'Manage Hypit video recreation projects, connect an external Agent and review the work.', listTitle:'Hypit Clone projects', empty:'No Hypit Clone projects yet', emptyHint:'Create a project, then choose Connect Agent to copy the instructions or Open project to review your work.', newName:'New Hypit Clone project', prepared:'Prepare creative skills', module:'Hypit Clone' }
        },
        article: {
            zh: { title:'公众号文章', description:'创建文章项目，接入外部 Agent，按需准备技能，再打开文章复制标题、封面和正文。', listTitle:'文章项目', empty:'还没有文章项目', emptyHint:'创建并命名文章项目后，接入 Agent；完成文章后点击“打开项目”预览和复制。', newName:'新文章项目', prepared:'准备创作技能', module:'文章', templateTitle:'排版示例', templateDescription:'了解正文的结构、色彩与排版；封面和标题在文章页单独管理。示例不等于已为当前文章生成排版。', templateLoading:'正在读取版式示例…', templateFailed:'版式示例读取失败', templateEmpty:'暂时没有可用的版式示例', templateRetry:'重试读取示例', templatePreview:'当前示例预览', templateExample:'示例', templateDirectory:'六种正文版式', templateUnavailable:'预览暂不可用' },
            en: { title:'Articles', description:'Create an article project, connect an external Agent, prepare skills if needed, then open the article to copy its title, cover and body.', listTitle:'Article projects', empty:'No article projects yet', emptyHint:'Create and name a project, connect an Agent, then choose Open project to review and copy the article.', newName:'New article project', prepared:'Prepare creative skills', module:'Articles', templateTitle:'Layout examples', templateDescription:'Explore body structure, color and layout. Titles and covers are managed separately on the article page. Examples are not layouts generated for your article.', templateLoading:'Loading layout examples…', templateFailed:'Could not load layout examples', templateEmpty:'No layout examples are available yet', templateRetry:'Retry loading examples', templatePreview:'Selected example', templateExample:'Example', templateDirectory:'Six body layouts', templateUnavailable:'Preview unavailable' }
        },
        music: {
            zh: { title:'音乐创作', description:'管理歌曲作品，接入外部 Agent，并查看歌词、乐谱与音频结果。', listTitle:'音乐项目', empty:'还没有音乐项目', emptyHint:'新建并命名音乐项目，再从项目卡片复制接入指令。创作完成后打开项目查看内容与试听。', newName:'新音乐项目', prepared:'准备创作技能', module:'音乐创作' },
            en: { title:'Music Creation', description:'Manage song projects, connect an external Agent, and review lyrics, scores and audio results.', listTitle:'Music projects', empty:'No music projects yet', emptyHint:'Create and name a music project, then copy its Agent instructions. Open the project to review the content and listen to results.', newName:'New music project', prepared:'Prepare creative skills', module:'Music Creation' }
        }
    };

    const commonCopy = {
        zh: {
            workspace:'创意工作台', projects:'项目', canvasTools:'画布工具', canvasToolsTitle:'导入工程与回收站', canvasToolsHint:'导入与导出使用同一套工程 ZIP 结构；打开画布后可在工作流工具中导入工程，删除的画布可从回收站恢复。', trashKicker:'画布回收站', trashTitle:'可恢复的画布', search:'搜索项目', prepare:'准备创作技能', newProject:'新建项目', loading:'正在读取项目', loadingHint:'正在读取作品…', loadFailed:'项目列表读取失败', retry:'重新读取', open:'打开项目', rename:'改名', connect:'Agent 接入', remove:'删除', updated:'最近更新', id:'项目 ID', copyDone:'连接信息已复制到剪贴板。', connection:'项目连接信息', copyFailed:'无法自动复制，下面是连接信息：', prepareTitle:'准备创作环境', prepareFailed:'准备环境接口暂不可用', importTitle:'导入工程', importHint:'工程导入与导出使用同一套 ZIP 结构。请先打开一个画布，再从工作流工具导入完整工程 ZIP。', trash:'回收站', trashEmpty:'回收站为空', restore:'恢复', purge:'彻底删除', purgeConfirm:'彻底删除后无法恢复，确认继续吗？', restoreDone:'已恢复画布', purgeDone:'已彻底删除', operationFailed:'操作失败', popupTitle:'浏览器拦截了新标签', popupHint:'点击下面的按钮打开项目。', popupOpen:'打开项目', close:'关闭', exportJson:'导出 JSON', exportZip:'导出工程', exporting:'正在导出...', exported:'已导出', exportFailed:'导出失败', zipHint:'已导出工程 ZIP；在画布的工作流工具中导入即可恢复节点、连线和资源。', confirmRename:'重命名项目', renamePlaceholder:'项目名称', renameRequired:'请输入项目名称', confirmDelete:name => `删除「${name}」？项目保存的数据会按模块规则处理。`, selected:'当前项目' },
        en: {
            workspace:'Creative workspace', projects:'Projects', canvasTools:'Canvas tools', canvasToolsTitle:'Import project and trash', canvasToolsHint:'Import and export use the same project ZIP structure. Open a canvas to import a project from Workflow tools; deleted canvases can be restored from Trash.', trashKicker:'Canvas trash', trashTitle:'Recoverable canvases', search:'Search projects', prepare:'Prepare creative skills', newProject:'New project', loading:'Loading projects', loadingHint:'Loading your work…', loadFailed:'Could not load projects', retry:'Retry', open:'Open project', rename:'Rename', connect:'Connect Agent', remove:'Delete', updated:'Updated', id:'Project ID', copyDone:'Connection details copied to the clipboard.', connection:'Project connection', copyFailed:'Automatic copy was unavailable. Connection details:', prepareTitle:'Prepare creative environment', prepareFailed:'The preparation endpoint is not available yet', importTitle:'Import project', importHint:'Import and export use the same project ZIP structure. Open a canvas, then import the complete project ZIP from Workflow tools.', trash:'Trash', trashEmpty:'Trash is empty', restore:'Restore', purge:'Delete permanently', purgeConfirm:'This cannot be undone. Continue?', restoreDone:'Canvas restored', purgeDone:'Deleted permanently', operationFailed:'Operation failed', popupTitle:'The browser blocked the new tab', popupHint:'Use the button below to open the project.', popupOpen:'Open project', close:'Close', exportJson:'Export JSON', exportZip:'Export project', exporting:'Exporting...', exported:'Exported', exportFailed:'Export failed', zipHint:'Project ZIP exported. Import it from canvas Workflow tools to restore nodes, connections, and assets.', confirmRename:'Rename project', renamePlaceholder:'Project name', renameRequired:'Enter a project name', confirmDelete:name => `Delete “${name}”? Saved data will follow the module rules.`, selected:'Current project' }
    };

    function isEnglish(){ return String(window.StudioI18n?.lang?.() || document.documentElement.lang || 'zh').toLowerCase().startsWith('en'); }
    function copy(){ return commonCopy[isEnglish() ? 'en' : 'zh']; }
    function moduleText(){ return moduleCopy[module][isEnglish() ? 'en' : 'zh']; }
    function L(zh, en){ return isEnglish() ? en : zh; }
    function escapeHtml(value){ return String(value == null ? '' : value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])); }
    function refreshIcons(){ if(window.lucide?.createIcons) window.lucide.createIcons(); }
    function setText(id, value){ const node = document.getElementById(id); if(node) node.textContent = value; }

    function renderUnavailableModule(){
        const english = isEnglish();
        const text = english
            ? {title:'Module unavailable', heading:'This creative module is unavailable', hint:'The module identifier in this link is invalid. Choose a module from the main navigation and try again.'}
            : {title:'模块不可用', heading:'无法打开这个创作模块', hint:'链接中的模块标识无效。请从主菜单选择模块后再试。'};
        document.documentElement.lang = english ? 'en' : 'zh-CN';
        document.title = text.title;
        setText('studioProjectListTitle', text.title);
        setText('studioProjectDescription', text.hint);
        const actions = page.querySelector('.studio-project-toolbar-actions');
        if(actions){ actions.hidden = true; actions.style.display = 'none'; }
        const stateNode = document.getElementById('studioProjectState');
        if(stateNode){ stateNode.hidden = false; }
        const grid = document.getElementById('studioProjectGrid');
        if(grid) grid.replaceChildren();
        document.getElementById('studioProjectGuide')?.remove();
        page.querySelectorAll('button, input').forEach(control => { control.disabled = true; });
        setState('error', text.heading, text.hint);
        refreshIcons();
    }

    if(!moduleIsValid){
        window.addEventListener('studio-lang-change', renderUnavailableModule);
        window.addEventListener('message', event => {
            if(event.origin !== location.origin || event.source !== window.parent) return;
            if(event.data?.type === 'studio-lang' && event.data.lang && window.StudioI18n) window.StudioI18n.set(event.data.lang);
            renderUnavailableModule();
        });
        renderUnavailableModule();
        return;
    }

    function formatTime(value){
        const numeric = Number(value || 0);
        if(!numeric) return '--';
        const date = new Date(numeric < 10000000000 ? numeric * 1000 : numeric);
        if(Number.isNaN(date.getTime())) return '--';
        return date.toLocaleString(isEnglish() ? 'en-US' : 'zh-CN', {year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'});
    }

    async function responseError(response){
        let detail = '';
        try {
            const payload = await response.json();
            detail = payload?.detail;
            if(detail && typeof detail === 'object') detail = detail.message || JSON.stringify(detail);
        } catch(e) {}
        const error = new Error(detail || `${response.status} ${response.statusText}`);
        error.status = response.status;
        return error;
    }

    async function api(path, options){
        const response = await fetch(path, options);
        if(!response.ok) throw await responseError(response);
        const type = response.headers.get('content-type') || '';
        if(type.includes('application/json')) return response.json();
        return response.text();
    }

    async function dialogAlert(message, options={}){
        if(window.StudioDialog?.alert) return window.StudioDialog.alert(String(message || ''), options);
        setState('error', String(message || copy().operationFailed), '');
        return null;
    }

    async function dialogConfirm(message, options={}){
        if(window.StudioDialog?.confirm) return window.StudioDialog.confirm(String(message || ''), options);
        return false;
    }

    async function dialogPrompt(message, options={}){
        if(window.StudioDialog?.prompt) return window.StudioDialog.prompt(String(message || ''), options);
        return null;
    }

    function setState(kind, title, hint){
        const node = document.getElementById('studioProjectState');
        if(!node) return;
        node.hidden = false;
        node.className = `studio-project-state ${kind || ''}`.trim();
        const icon = kind === 'error' ? 'triangle-alert' : kind === 'empty' ? 'folder-open' : 'loader-circle';
        node.innerHTML = `<div class="studio-state-icon"><i data-lucide="${icon}" aria-hidden="true"></i></div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(hint || '')}</span>`;
        refreshIcons();
    }

    function hideState(){
        const node = document.getElementById('studioProjectState');
        if(node) node.hidden = true;
    }

    function updateLanguage(){
        const text = moduleText();
        const common = copy();
        document.documentElement.lang = isEnglish() ? 'en' : 'zh-CN';
        document.title = text.title;
        page.querySelectorAll('[data-copy="workspace"]').forEach(node => { node.textContent = common.workspace; });
        page.querySelectorAll('[data-copy="projects"]').forEach(node => { node.textContent = common.projects; });
        page.querySelectorAll('[data-copy="canvasTools"]').forEach(node => { node.textContent = common.canvasTools; });
        page.querySelectorAll('[data-copy="canvasToolsTitle"]').forEach(node => { node.textContent = common.canvasToolsTitle; });
        page.querySelectorAll('[data-copy="canvasToolsHint"]').forEach(node => { node.textContent = common.canvasToolsHint; });
        page.querySelectorAll('[data-copy="trashKicker"]').forEach(node => { node.textContent = common.trashKicker; });
        page.querySelectorAll('[data-copy="trashTitle"]').forEach(node => { node.textContent = common.trashTitle; });
        page.querySelectorAll('[data-module-label="canvas"]').forEach(node => { node.textContent = L('画布','Canvas'); });
        page.querySelectorAll('[data-module-label="hypit"]').forEach(node => { node.textContent = L('Hypit克隆','Hypit Clone'); });
        page.querySelectorAll('[data-module-label="article"]').forEach(node => { node.textContent = L('公众号文章','Articles'); });
        page.querySelectorAll('[data-module-label="music"]').forEach(node => { node.textContent = L('音乐创作','Music Creation'); });
        const tabs = page.querySelector('[data-role="module-tabs"]');
        if(tabs) tabs.setAttribute('aria-label', L('创作模块','Creative modules'));
        setText('studioModuleTitle', text.title);
        setText('studioProjectDescription', text.description);
        setText('studioProjectListTitle', text.listTitle);
        setText('studioNewProjectButton', common.newProject);
        const newButton = document.getElementById('studioNewProjectButton');
        if(newButton) newButton.innerHTML = `<i data-lucide="plus" aria-hidden="true"></i><span>${escapeHtml(common.newProject)}</span>`;
        const search = document.getElementById('studioProjectSearch');
        if(search){ search.placeholder = common.search; search.setAttribute('aria-label', common.search); }
        const prepare = document.getElementById('studioPrepareButton');
        if(prepare) prepare.innerHTML = `<i data-lucide="book-open-check" aria-hidden="true"></i><span>${escapeHtml(common.prepare)}</span>`;
        const trash = document.getElementById('studioTrashButton');
        if(trash) trash.innerHTML = `<i data-lucide="trash-2" aria-hidden="true"></i><span>${escapeHtml(common.trash)}</span><b id="studioTrashBadge" class="studio-trash-badge" ${state.trashCount ? '' : 'hidden'}>${state.trashCount}</b>`;
        const importButton = document.getElementById('studioImportGuide');
        if(importButton) importButton.innerHTML = `<i data-lucide="file-input" aria-hidden="true"></i><span>${escapeHtml(L('导入工程','Import project'))}</span>`;
        const langButton = document.getElementById('studioLanguageToggle');
        if(langButton){ langButton.textContent = isEnglish() ? 'EN' : '中'; langButton.title = L('切换语言','Switch language'); langButton.setAttribute('aria-label', langButton.title); }
        const themeButton = document.getElementById('studioThemeToggle');
        if(themeButton){ themeButton.title = L('切换明暗模式','Switch theme'); themeButton.setAttribute('aria-label', themeButton.title); }
        const trashClose = document.getElementById('studioTrashClose');
        if(trashClose){ trashClose.title = L('关闭回收站','Close trash'); trashClose.setAttribute('aria-label', trashClose.title); }
        page.querySelectorAll('[data-module-link]').forEach(link => {
            const isActive = link.dataset.moduleLink === module;
            link.classList.toggle('active', isActive);
            if(isActive) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
        });
        if(state.loading) setState('loading', common.loading, common.loadingHint);
        renderGuide();
        renderArticleTemplates();
        refreshIcons();
        renderProjects();
    }

    function filteredProjects(){
        const query = state.query.trim().toLocaleLowerCase();
        if(!query) return state.projects.slice();
        return state.projects.filter(project => `${project.name || ''} ${project.id || ''}`.toLocaleLowerCase().includes(query));
    }

    function cardMarkup(project){
        const isHypit = project.module === 'hypit';
        const isArticle = module === 'article' || project.module === 'article';
        const isMusic = project.module === 'music';
        const selected = focusedProjectId && focusedProjectId === project.id ? ' selected' : '';
        const icon = isHypit ? 'flask-conical' : isArticle ? 'notebook-pen' : isMusic ? 'music-2' : 'layers-3';
        const utility = isHypit || isArticle || isMusic ? '' : `<div class="studio-card-utilities">
                <button class="studio-card-utility" type="button" data-card-action="export-json" data-project-id="${escapeHtml(project.id)}">${escapeHtml(copy().exportJson)}</button>
                <button class="studio-card-utility" type="button" data-card-action="export-zip" data-project-id="${escapeHtml(project.id)}">${escapeHtml(copy().exportZip)}</button>
            </div>`;
        return `<article class="studio-project-card${selected}" data-project-id="${escapeHtml(project.id)}">
            <div class="studio-project-card-head">
            <div class="studio-project-card-icon${isHypit ? ' hypit' : isArticle ? ' article' : isMusic ? ' music' : ''}"><i data-lucide="${icon}" aria-hidden="true"></i></div>
                <div class="studio-project-card-head-copy">
                    <h3 class="studio-project-card-title">${escapeHtml(project.name || '')}</h3>
                </div>
            </div>
            <div class="studio-project-card-meta"><i data-lucide="clock-3" aria-hidden="true"></i><span>${escapeHtml(copy().updated)} ${escapeHtml(formatTime(project.updated_at))}</span></div>
            <div class="studio-project-card-actions">
                <button class="studio-card-action open" type="button" data-card-action="open" data-project-id="${escapeHtml(project.id)}" title="${escapeHtml(copy().open)}"><i data-lucide="external-link" aria-hidden="true"></i><span>${escapeHtml(copy().open)}</span></button>
                <button class="studio-card-action" type="button" data-card-action="rename" data-project-id="${escapeHtml(project.id)}" title="${escapeHtml(copy().rename)}"><i data-lucide="pencil" aria-hidden="true"></i><span>${escapeHtml(copy().rename)}</span></button>
                <button class="studio-card-action" type="button" data-card-action="connect" data-project-id="${escapeHtml(project.id)}" title="${escapeHtml(copy().connect)}"><i data-lucide="plug-zap" aria-hidden="true"></i><span>${escapeHtml(copy().connect)}</span></button>
                <button class="studio-card-action danger" type="button" data-card-action="delete" data-project-id="${escapeHtml(project.id)}" title="${escapeHtml(copy().remove)}"><i data-lucide="trash-2" aria-hidden="true"></i><span>${escapeHtml(copy().remove)}</span></button>
            </div>
            ${utility}
        </article>`;
    }

    function renderProjects(){
        const grid = document.getElementById('studioProjectGrid');
        if(!grid) return;
        if(state.loading) return;
        if(state.loadError){ setState('error', copy().loadFailed, state.loadError); return; }
        const visible = filteredProjects();
        if(!state.projects.length){
            grid.innerHTML = '';
            setState('empty', moduleText().empty, moduleText().emptyHint);
            return;
        }
        if(!visible.length){
            grid.innerHTML = '';
            setState('empty', L('没有匹配的项目','No matching projects'), L('换一个搜索词试试。','Try a different search term.'));
            return;
        }
        hideState();
        grid.innerHTML = visible.map(cardMarkup).join('');
        refreshIcons();
    }

    function safePreviewUrl(value){
        try {
            const url = new URL(String(value || ''), location.href);
            if(url.origin !== location.origin || !['http:','https:'].includes(url.protocol)) return '';
            return url.href;
        } catch(e){ return ''; }
    }

    function templateOptionMarkup(template){
        const english = isEnglish();
        const name = english ? (template.name_en || template.name || template.id) : (template.name || template.name_en || template.id);
        const description = english ? (template.description_en || template.description || '') : (template.description || template.description_en || '');
        const color = /^#[0-9a-f]{3,8}$/i.test(String(template.color || '')) ? String(template.color) : 'var(--sp-accent)';
        const selected = template.id === state.selectedTemplateId;
        const tabId = `articleTemplateTab-${encodeURIComponent(String(template.id || ''))}`;
        return `<button class="article-template-option${selected ? ' selected' : ''}" id="${escapeHtml(tabId)}" type="button" role="tab" data-template-id="${escapeHtml(template.id)}" aria-selected="${selected ? 'true' : 'false'}" aria-controls="articleTemplatePanel" aria-label="${escapeHtml(`${name}. ${description}`)}" tabindex="${selected ? '0' : '-1'}" style="--article-template-color:${color}">
            <span class="article-template-option-swatch" aria-hidden="true"></span>
            <span class="article-template-option-copy"><span class="article-template-example">${escapeHtml(moduleText().templateExample)}</span><strong>${escapeHtml(name)}</strong><span class="article-template-option-hint">${escapeHtml(description)}</span></span>
            <span class="article-template-option-check" aria-hidden="true">✓</span>
        </button>`;
    }

    function selectedTemplateMarkup(template){
        if(!template) return '';
        const english = isEnglish();
        const name = english ? (template.name_en || template.name || template.id) : (template.name || template.name_en || template.id);
        const description = english ? (template.description_en || template.description || '') : (template.description || template.description_en || '');
        const color = /^#[0-9a-f]{3,8}$/i.test(String(template.color || '')) ? String(template.color) : 'var(--sp-accent)';
        const preview = safePreviewUrl(template.preview_url);
        const tabId = `articleTemplateTab-${encodeURIComponent(String(template.id || ''))}`;
        const previewMarkup = preview
            ? `<iframe id="articleTemplatePreview" title="${escapeHtml(name)} · ${escapeHtml(moduleText().templatePreview)}" sandbox="" referrerpolicy="no-referrer" loading="eager" src="${escapeHtml(preview)}"></iframe>`
            : `<div id="articleTemplatePreviewUnavailable" class="article-template-unavailable">${escapeHtml(moduleText().templateUnavailable)}</div>`;
        return `<section id="articleTemplatePanel" class="article-template-preview-pane" role="tabpanel" aria-labelledby="${escapeHtml(tabId)}" data-template-id="${escapeHtml(template.id)}" style="--article-template-color:${color}">
            <header class="article-template-preview-heading"><span class="article-template-preview-mark" aria-hidden="true"></span><div><span class="article-template-example">${escapeHtml(moduleText().templateExample)} · ${escapeHtml(moduleText().templatePreview)}</span><h3>${escapeHtml(name)}</h3><p>${escapeHtml(description)}</p></div></header>
            <div class="article-template-preview-frame">${previewMarkup}</div>
        </section>`;
    }

    function selectArticleTemplate(id, {focus=false}={}){
        if(!state.templates.some(template => template.id === id)) return;
        state.selectedTemplateId = id;
        renderArticleTemplates();
        if(focus){
            const button = [...(document.getElementById('articleTemplateGrid')?.querySelectorAll('.article-template-option') || [])].find(item => item.dataset.templateId === id);
            button?.focus({preventScroll:true});
        }
    }

    function renderArticleTemplates(){
        if(module !== 'article') return;
        const title = document.getElementById('articleTemplateTitle');
        const description = document.getElementById('articleTemplateDescription');
        const grid = document.getElementById('articleTemplateGrid');
        const stateNode = document.getElementById('articleTemplateState');
        if(title) title.textContent = moduleText().templateTitle;
        if(description) description.textContent = moduleText().templateDescription;
        if(!grid || !stateNode) return;
        if(state.templatesLoading){ stateNode.hidden = false; stateNode.textContent = moduleText().templateLoading; grid.innerHTML = ''; return; }
        if(state.templatesError){
            stateNode.hidden = false; stateNode.textContent = state.templatesError;
            grid.innerHTML = `<button class="studio-secondary-button" type="button" id="articleTemplateRetry">${escapeHtml(moduleText().templateRetry)}</button>`;
            document.getElementById('articleTemplateRetry')?.addEventListener('click', loadArticleTemplates);
            return;
        }
        if(!state.templates.length){ stateNode.hidden = false; stateNode.textContent = moduleText().templateEmpty; grid.innerHTML = ''; return; }
        if(!state.templates.some(template => template.id === state.selectedTemplateId)) state.selectedTemplateId = state.templates[0].id;
        stateNode.hidden = true;
        const selected = state.templates.find(template => template.id === state.selectedTemplateId);
        grid.innerHTML = `<nav id="articleTemplateDirectory" class="article-template-directory" role="tablist" aria-orientation="vertical" aria-label="${escapeHtml(moduleText().templateDirectory)}" data-selected-template-id="${escapeHtml(state.selectedTemplateId)}">
            <div class="article-template-directory-heading"><span>${escapeHtml(moduleText().templateDirectory)}</span><small>${state.templates.length}</small></div>
            <div class="article-template-options">${state.templates.map(templateOptionMarkup).join('')}</div>
        </nav>${selectedTemplateMarkup(selected)}`;
    }

    async function loadArticleTemplates(){
        if(module !== 'article') return;
        state.templatesLoading = true; state.templatesError = ''; renderArticleTemplates();
        try {
            const data = await api('/api/studio/articles/templates');
            state.templates = Array.isArray(data?.templates) ? data.templates : [];
            if(!state.templates.some(template => template.id === state.selectedTemplateId)) state.selectedTemplateId = state.templates[0]?.id || '';
            state.templatesLoading = false;
            renderArticleTemplates();
        } catch(error){
            state.templatesLoading = false;
            state.templatesError = error?.message || moduleText().templateFailed;
            renderArticleTemplates();
        }
    }

    async function loadProjects(){
        state.loading = true;
        state.loadError = '';
        setState('loading', copy().loading, copy().loadingHint);
        try {
            const data = await api(`/api/studio/projects?module=${encodeURIComponent(module)}`);
            state.projects = Array.isArray(data?.projects) ? data.projects : [];
            state.loading = false;
            renderProjects();
            await refreshTrashBadge();
        } catch(error){
            state.loading = false;
            const hint = error?.message || L('请确认服务端已装配共用项目路由。','Check that the shared project router is mounted on the server.');
            state.loadError = hint;
            setState('error', copy().loadFailed, hint);
            const grid = document.getElementById('studioProjectGrid');
            if(grid) grid.innerHTML = `<button class="studio-secondary-button" type="button" id="studioRetryButton">${escapeHtml(copy().retry)}</button>`;
            document.getElementById('studioRetryButton')?.addEventListener('click', loadProjects);
        }
    }

    function openFallback(project){
        state.blockedProject = project;
        const box = document.getElementById('studioOpenFallback');
        if(!box) return;
        box.hidden = false;
        setText('studioOpenFallbackTitle', copy().popupTitle);
        setText('studioOpenFallbackText', copy().popupHint);
        const button = document.getElementById('studioOpenFallbackButton');
        if(button) button.textContent = copy().popupOpen;
        const close = document.getElementById('studioOpenFallbackClose');
        if(close) close.textContent = copy().close;
        refreshIcons();
    }

    function navigatePopup(popup, project){
        const path = project?.url || (module === 'article' ? `/static/article.html?id=${encodeURIComponent(project?.id || '')}` : module === 'music' ? `/static/music.html?id=${encodeURIComponent(project?.id || '')}` : '');
        if(!path) return;
        const target = new URL(path, location.origin).href;
        if(popup){
            try { popup.document.title = moduleText().title; } catch(e) {}
            popup.location.href = target;
            return;
        }
        openFallback(project);
    }

    function openProject(project, popup=null){
        if(!project) return;
        navigatePopup(popup || window.open('', '_blank'), project);
    }

    async function createProject(){
        // 命名并保存成功后才开标签；慢请求被浏览器拦截时保留明确的打开入口。
        const name = await dialogPrompt(L('项目名称','Project name'), { title: L('新建项目','New project'), confirmText: L('创建项目','Create project'), placeholder: L('项目名称','Project name'), defaultValue: moduleText().newName });
        if(name == null) return;
        try {
            const data = await api('/api/studio/projects', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({module, name:String(name).trim()}) });
            const project = data?.project;
            await loadProjects();
            // 创建只更新列表；由用户在项目卡片上打开。
        } catch(error){
            await dialogAlert(error?.message || copy().operationFailed, {type:'warning'});
        }
    }

    async function renameProject(project){
        const name = await dialogPrompt(copy().confirmRename, { title: copy().confirmRename, defaultValue: project.name || '', placeholder: copy().renamePlaceholder });
        if(name == null) return;
        if(!String(name).trim()){
            await dialogAlert(copy().renameRequired, {type:'warning'});
            return;
        }
        try {
            await api(`/api/studio/projects/${encodeURIComponent(project.id)}?module=${encodeURIComponent(module)}`, { method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({module, name:String(name).trim(), revision:project.revision}) });
            await loadProjects();
        } catch(error){ await dialogAlert(error?.message || copy().operationFailed, {type:'warning'}); }
    }

    async function deleteProject(project){
        if(!await dialogConfirm(copy().confirmDelete(project.name || ''), {type:'danger', title:copy().remove})) return;
        try {
            await api(`/api/studio/projects/${encodeURIComponent(project.id)}?module=${encodeURIComponent(module)}${project.revision ? `&revision=${encodeURIComponent(project.revision)}` : ''}`, { method:'DELETE' });
            await loadProjects();
        } catch(error){ await dialogAlert(error?.message || copy().operationFailed, {type:'warning'}); }
    }

    async function copyText(value){
        try {
            if(navigator.clipboard?.writeText){ await navigator.clipboard.writeText(value); return true; }
        } catch(e) {}
        try {
            const textarea = document.createElement('textarea');
            textarea.value = value; textarea.setAttribute('readonly',''); textarea.style.position = 'fixed'; textarea.style.opacity = '0';
            document.body.appendChild(textarea); textarea.select();
            const copied = document.execCommand('copy'); textarea.remove(); return copied;
        } catch(e){ return false; }
    }

    function renderGuide(){
        let guide = document.getElementById('studioProjectGuide');
        if(!guide){guide=document.createElement('section');guide.id='studioProjectGuide';guide.className='studio-project-guide';document.querySelector('.studio-project-toolbar').after(guide);}
        const steps = module === 'music' ? [
            [L('创建项目','Create a project'),L('点击“新建项目”并命名；项目会保存在音乐项目列表中。','Choose New project and name it. The project stays in the music list.')],
            [L('准备创作技能 · 可选','Prepare creative skills · optional'),L('点击“准备创作技能”，把共享准备说明交给外部 Agent；它会检查官方仓库和入口，发现更新先告知并询问。此操作不会自动开始创作。','Choose Prepare creative skills to share the common preparation guide with your Agent. It checks the official repository and entry, and asks before updating. This does not start creative work.')],
            [L('接入外部 Agent','Connect an external Agent'),L('从项目卡片复制该歌曲的接入说明。Agent 负责创作歌词、歌名、乐谱和风格内容。','Copy the project-specific instructions from its card. Your Agent creates titles, lyrics, style and scores.')],
            [L('查看与试听','Review and listen'),L('打开项目查看已保存内容与真实音频结果；选中结果或播放音频不会改写作品。','Open the project to review saved content and audio. Listening does not change the work.')]
        ] : module === 'article' ? [
            [L('创建项目','Create a project'),L('点击“新建项目”并命名；项目卡片会留在当前列表。','Choose New project and name it. The project card stays in this list.')],
            [L('接入 Agent','Connect an Agent'),L('从项目卡片复制接入说明给外部 Agent；连接本身不会创作文章。','Copy the connection instructions from the project card to an external Agent. Connecting does not create the article.')],
            [L('准备创作技能 · 可选','Prepare creative skills · optional'),L('点击“准备创作技能”，让 Agent 检查已安装技能和可选更新；是否更新由你确认，不会自动覆盖。','Choose Prepare creative skills to have your Agent check installed skills and available updates. You decide whether to update; nothing is overwritten automatically.')],
            [L('打开并复制文章','Open and copy the article'),L('点击“打开项目”，按需切换已有标题、封面和正文版本，再复制或导出。','Choose Open project, select available title, cover and body variants, then copy or export them.')]
        ] : module === 'hypit' ? [
            [L('创建项目','Create project'),L('点击“新建项目”并命名。创建后留在这里，不会自动打开新标签。','Choose New project and name it. You stay on this page after creation.')],
            [L('准备创作技能 · 可选','Prepare creative skills · optional'),L('点击“准备创作技能”，让 Agent 检查已安装的 Hypit 技能和可选更新；是否更新由你确认，不会自动覆盖。','Choose Prepare creative skills to have your Agent check installed Hypit skills and available updates. You decide whether to update; nothing is overwritten automatically.')],
            [L('接入项目并创作','Connect and create'),L('点击项目卡片的“Agent 接入”，复制指令到 Agent 对话，再告诉它你想做什么。','Choose Connect Agent on the card, copy the instructions to your Agent, and describe your work.')],
            [L('打开作品','Open your work'),L('点击“打开项目”查看制作内容和结果。Agent 写入内容后页面会更新；关闭标签不影响后台任务。','Choose Open project to see the work and results. Content updates as your Agent writes; closing the tab does not stop background tasks.')]
        ] : [
            [L('创建项目','Create project'),L('点击“新建项目”并命名，项目卡片会出现在下方。','Choose New project and name it. A project card appears below.')],
            [L('打开画布','Open canvas'),L('点击卡片上的“打开项目”，在新标签中添加节点、连接素材并生成。可以完全手动操作。','Choose Open project to add nodes, connect media and generate in a new tab. You can work entirely manually.')],
            [L('技能准备与 Agent 协助 · 可选','Prepare skills and use an Agent · optional'),L('可按需点击“准备创作技能”检查现有技能和可选更新；是否更新由你确认。也可点击卡片上的“Agent 接入”复制项目指令。画布仍可完全手动操作。','Choose Prepare creative skills to check installed skills and available updates; you decide whether to update. Or choose Connect Agent on a project card to copy project instructions. Canvas remains fully usable by hand.')]
        ];
        guide.innerHTML=steps.map(([title,body],i)=>`<div><b>${i+1}</b><section><strong>${escapeHtml(title)}</strong><p>${escapeHtml(body)}</p></section></div>`).join('');
    }

    async function showInstructions(title, intro, value){
        let dialog=document.getElementById('studioConnectionDialog');
        if(!dialog){
            dialog=document.createElement('dialog');dialog.id='studioConnectionDialog';dialog.className='studio-instructions';
            dialog.innerHTML='<h2></h2><p></p><textarea readonly></textarea><div><button data-copy class="studio-primary-button"></button><button data-close class="studio-secondary-button"></button></div>';
            document.body.append(dialog);
            dialog.querySelector('[data-close]').onclick=()=>dialog.close();
        }
        dialog.querySelector('h2').textContent=title;dialog.querySelector('p').textContent=intro;
        dialog.querySelector('textarea').value=value;dialog.querySelector('textarea').setAttribute('aria-label',title);
        const button=dialog.querySelector('[data-copy]');button.textContent=L('复制指令','Copy instructions');
        button.onclick=async()=>{button.textContent=await copyText(value)?L('已复制，请粘贴给 Agent','Copied — paste into your Agent'):L('请选中上方内容复制','Select the text above to copy');};
        dialog.querySelector('[data-close]').textContent=L('关闭','Close');dialog.showModal();
    }

    async function connectProject(project){
        try {
            const response = await api(`/api/studio/projects/${encodeURIComponent(project.id)}/connection?module=${encodeURIComponent(module)}&lang=${isEnglish()?'en':'zh'}`);
            const text = typeof response === 'string' ? response : String(response?.text || response?.connection || response?.content || JSON.stringify(response, null, 2));
            await showInstructions(L('接入：','Connect: ')+project.name, L('复制下面的指令，粘贴到你使用的 Agent 对话中。它会读取这个项目；随后告诉它你的创作需求。复制或接入本身不会开始生成。','Copy these instructions into your Agent conversation. It will read this project; then describe your creative request. Connecting does not start generation.'), text);
        } catch(error){ await dialogAlert(error?.message || copy().operationFailed, {type:'warning'}); }
    }

    async function prepareEnvironment(){
        try {
            const response = await api(`/api/studio/modules/${encodeURIComponent(module)}/preparation?lang=${isEnglish()?'en':'zh'}`);
            const text = typeof response === 'string' ? response : String(response?.text || response?.instructions || JSON.stringify(response, null, 2));
            const title = L('准备创作技能','Prepare creative skills');
            const intro = L('把说明交给外部 Agent，检查已安装的技能和可选更新。是否更新由你确认，不会自动覆盖；你也可以跳过。技能准备不会自动开始创作。','Give these instructions to your external Agent to check installed skills and available updates. You decide whether to update; nothing is overwritten automatically, and you can skip. Preparing skills does not start creative work.');
            await showInstructions(title, intro, text);
        } catch(error){ await dialogAlert(error?.message || copy().prepareFailed, {type:'warning', title:copy().prepareTitle}); }
    }

    function downloadBlob(blob, filename){
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1500);
    }

    function safeName(value, fallback='canvas'){
        return String(value || fallback).replace(/[\\/:*?"<>|]+/g, '_').trim().slice(0, 60) || fallback;
    }

    async function readCanvas(project){
        const response = await api(`/api/canvases/${encodeURIComponent(project.id)}`);
        return response?.canvas || response;
    }

    async function exportCanvasJson(project){
        try {
            const canvas = await readCanvas(project);
            downloadBlob(new Blob([JSON.stringify(canvas, null, 2)], {type:'application/json'}), `${safeName(canvas?.title || project.name)}.json`);
        } catch(error){ await dialogAlert(error?.message || copy().exportFailed, {type:'warning'}); }
    }

    async function exportCanvasZip(project){
        try {
            const canvas = await readCanvas(project);
            const response = await fetch('/api/canvas-workflows/export', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({nodes:canvas?.nodes || [], connections:canvas?.connections || [], settings:canvas?.settings || {}, name:canvas?.title || project.name, filename:`${safeName(canvas?.title || project.name)}.zip`, include_resources:true})});
            if(!response.ok) throw await responseError(response);
            downloadBlob(await response.blob(), `${safeName(canvas?.title || project.name)}.zip`);
            await dialogAlert(copy().zipHint, {type:'info', title:copy().exported});
        } catch(error){ await dialogAlert(error?.message || copy().exportFailed, {type:'warning'}); }
    }

    async function showImportGuide(){
        await dialogAlert(copy().importHint, {type:'info', title:copy().importTitle});
    }

    async function refreshTrashBadge(){
        if(module !== 'canvas') return;
        try {
            const data = await api('/api/canvases/trash');
            const badge = document.getElementById('studioTrashBadge');
            const count = Array.isArray(data?.canvases) ? data.canvases.length : 0;
            state.trashCount = count;
            if(badge){ badge.textContent = String(count); badge.hidden = count < 1; }
        } catch(e) {}
    }

    function trashCardMarkup(canvas){
        return `<article class="studio-trash-card" data-trash-id="${escapeHtml(canvas.id)}">
            <h3>${escapeHtml(canvas.title || canvas.name || L('未命名画布','Untitled canvas'))}</h3>
            <p>${escapeHtml(copy().updated)} ${escapeHtml(formatTime(canvas.deleted_at || canvas.updated_at))}</p>
            <div class="studio-trash-card-actions">
                <button class="studio-card-action" type="button" data-trash-action="restore" data-trash-id="${escapeHtml(canvas.id)}">${escapeHtml(copy().restore)}</button>
                <button class="studio-card-action danger" type="button" data-trash-action="purge" data-trash-id="${escapeHtml(canvas.id)}">${escapeHtml(copy().purge)}</button>
            </div>
        </article>`;
    }

    async function openTrash(){
        const panel = document.getElementById('studioTrashPanel');
        const list = document.getElementById('studioTrashList');
        if(!panel || !list) return;
        panel.hidden = false;
        list.innerHTML = `<div class="studio-trash-empty">${escapeHtml(copy().loading)}</div>`;
        try {
            const data = await api('/api/canvases/trash');
            const items = Array.isArray(data?.canvases) ? data.canvases : [];
            list.innerHTML = items.length ? items.map(trashCardMarkup).join('') : `<div class="studio-trash-empty">${escapeHtml(copy().trashEmpty)}</div>`;
            refreshIcons();
            await refreshTrashBadge();
        } catch(error){ list.innerHTML = `<div class="studio-trash-empty">${escapeHtml(error?.message || copy().operationFailed)}</div>`; }
    }

    function closeTrash(){ const panel = document.getElementById('studioTrashPanel'); if(panel) panel.hidden = true; }

    async function restoreCanvas(id){
        try {
            await api(`/api/canvases/${encodeURIComponent(id)}/restore`, {method:'POST'});
            await openTrash(); await loadProjects();
            await dialogAlert(copy().restoreDone, {type:'info'});
        } catch(error){ await dialogAlert(error?.message || copy().operationFailed, {type:'warning'}); }
    }

    async function purgeCanvas(id){
        if(!await dialogConfirm(copy().purgeConfirm, {type:'danger'})) return;
        try {
            await api(`/api/canvases/${encodeURIComponent(id)}/purge`, {method:'DELETE'});
            await openTrash(); await refreshTrashBadge();
            await dialogAlert(copy().purgeDone, {type:'info'});
        } catch(error){ await dialogAlert(error?.message || copy().operationFailed, {type:'warning'}); }
    }

    function projectById(id){ return state.projects.find(project => String(project.id) === String(id)); }

    page.addEventListener('click', event => {
        const templateOption = event.target.closest('.article-template-option');
        if(templateOption && page.contains(templateOption)){
            selectArticleTemplate(templateOption.dataset.templateId, {focus:true});
            return;
        }
        const action = event.target.closest('[data-card-action]');
        if(action){
            const project = projectById(action.dataset.projectId);
            if(!project) return;
            const type = action.dataset.cardAction;
            if(type === 'models') window.open('/static/api-settings.html?section=hypit','_blank','noopener');
            if(type === 'open') openProject(project);
            if(type === 'rename') renameProject(project);
            if(type === 'delete') deleteProject(project);
            if(type === 'connect') connectProject(project);
            if(type === 'export-json') exportCanvasJson(project);
            if(type === 'export-zip') exportCanvasZip(project);
            return;
        }
        const trashAction = event.target.closest('[data-trash-action]');
        if(trashAction){
            if(trashAction.dataset.trashAction === 'restore') restoreCanvas(trashAction.dataset.trashId);
            if(trashAction.dataset.trashAction === 'purge') purgeCanvas(trashAction.dataset.trashId);
        }
    });

    document.getElementById('articleTemplateGrid')?.addEventListener('keydown', event => {
        const active = event.target.closest('.article-template-option');
        if(!active) return;
        const options = [...(document.getElementById('articleTemplateGrid')?.querySelectorAll('.article-template-option') || [])];
        const index = options.indexOf(active);
        let next = -1;
        if(event.key === 'ArrowDown' || event.key === 'ArrowRight') next = (index + 1) % options.length;
        else if(event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = (index - 1 + options.length) % options.length;
        else if(event.key === 'Home') next = 0;
        else if(event.key === 'End') next = options.length - 1;
        if(next < 0 || !options.length) return;
        event.preventDefault();
        selectArticleTemplate(options[next].dataset.templateId, {focus:true});
    });

    document.getElementById('studioProjectSearch')?.addEventListener('input', event => { state.query = event.target.value || ''; renderProjects(); });
    document.getElementById('studioNewProjectButton')?.addEventListener('click', createProject);
    document.getElementById('studioPrepareButton')?.addEventListener('click', prepareEnvironment);
    document.getElementById('studioImportGuide')?.addEventListener('click', showImportGuide);
    document.getElementById('studioTrashButton')?.addEventListener('click', openTrash);
    document.getElementById('studioTrashClose')?.addEventListener('click', closeTrash);
    document.getElementById('studioOpenFallbackClose')?.addEventListener('click', () => { const node = document.getElementById('studioOpenFallback'); if(node) node.hidden = true; state.blockedProject = null; });
    document.getElementById('studioOpenFallbackButton')?.addEventListener('click', () => {
        if(state.blockedProject) navigatePopup(window.open('', '_blank'), state.blockedProject);
    });
    document.getElementById('studioThemeToggle')?.addEventListener('click', () => {
        const current = window.StudioTheme?.get?.() || 'light';
        window.StudioTheme?.set?.(current === 'dark' ? 'light' : 'dark');
        updateLanguage();
    });
    document.getElementById('studioLanguageToggle')?.addEventListener('click', () => {
        window.StudioI18n?.toggle?.();
        updateLanguage();
    });
    document.addEventListener('keydown', event => { if(event.key === 'Escape') closeTrash(); });
    window.addEventListener('studio-lang-change', updateLanguage);
    window.addEventListener('message', event => {
        if(event.origin !== location.origin || event.source !== window.parent) return;
        if(event.data?.type === 'studio-lang' && event.data.lang && window.StudioI18n) window.StudioI18n.set(event.data.lang);
        updateLanguage();
    });

    async function runtimeSetup(){
        if(module!=='hypit')return;
        try{
            const status=await api('/api/studio/hypit/runtime');
            if(status.ready)return;
            const button=document.createElement('button');button.className='studio-secondary-button';button.type='button';
            button.textContent=L('安装预览组件','Install preview component');
            document.getElementById('studioPrepareButton').after(button);
            button.onclick=async()=>{
                if(!await dialogConfirm(L('首次使用需要下载 Hypit 预览组件到工作台。它用于打开作品，与 Agent 端的创作技能不同。现在安装？','Download the Hypit preview component into this workbench? It opens your work and is separate from the creative skills in your Agent.'),{title:L('安装预览组件','Install preview component')}))return;
                button.disabled=true;button.textContent=L('正在安装…','Installing…');
                try{await api('/api/studio/hypit/runtime/prepare',{method:'POST'});button.remove();}
                catch(error){button.disabled=false;button.textContent=L('重试安装','Retry installation');await dialogAlert(error.message,{type:'warning'});}
            };
        }catch(error){await dialogAlert(error.message,{type:'warning'});}
    }
    updateLanguage();
    refreshIcons();
    loadProjects();
    loadArticleTemplates();
    runtimeSetup();
})();
