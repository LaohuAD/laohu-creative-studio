/* 文章项目的预览、主题版本选择与复制；正文由后端/外部 Agent 维护。 */
(function(){
    'use strict';

    const params = new URLSearchParams(location.search);
    const articleId = String(params.get('id') || '').trim();
    const state = {
        article: null, selectedThemeId: '', selectedTitleVariantId: '', selectedCoverVariantId: '',
        revision: 0, loadSequence: 0, selectionSequence: 0, pendingSaves: 0,
        saveChain: Promise.resolve(), lastPreviewKey: '', status: null, syncTimer: 0, unsavedSelection: null,
        busyActions: new Set(), actionFeedback: {},
    };

    const $ = selector => document.querySelector(selector);
    const isEnglish = () => String(window.StudioI18n?.lang?.() || document.documentElement.lang || 'zh').toLowerCase().startsWith('en');
    const L = (zh, en) => isEnglish() ? en : zh;
    const escapeHtml = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

    async function api(path, options){
        const response = await fetch(path, options);
        let payload = null;
        try { payload = await response.json(); } catch(e) {}
        if(!response.ok){
            const detail = payload?.detail;
            const error = new Error(typeof detail === 'string' ? detail : detail?.message || `${response.status} ${response.statusText}`);
            error.status = response.status;
            throw error;
        }
        return payload;
    }

    function setStatus(zh, en, kind='', retry=false){
        state.status = {zh, en, kind, retry};
        renderStatus();
    }

    function setActionFeedback(id, zh='', en='', kind=''){
        state.actionFeedback[id]=zh||en?{zh,en,kind}:null;
        renderActionFeedback(id);
    }

    function renderActionFeedback(id){
        const node=$(`#${id}`);
        const message=state.actionFeedback[id];
        if(!node)return;
        node.textContent=message?(isEnglish()?message.en:message.zh):'';
        node.dataset.state=message?.kind||'';
        node.hidden=!message;
        if(message?.kind==='pending')node.setAttribute('aria-busy','true');
        else node.removeAttribute('aria-busy');
    }

    function beginAction(key,buttonId,feedbackId,pendingZh,pendingEn){
        const button=$(`#${buttonId}`);
        if(state.busyActions.has(key)||!button||button.disabled)return false;
        state.busyActions.add(key);
        refreshActionButtons();
        button.setAttribute('aria-busy','true');
        setActionFeedback(feedbackId,pendingZh,pendingEn,'pending');
        return true;
    }

    function finishAction(key,buttonId,feedbackId,zh,en,kind){
        state.busyActions.delete(key);
        $(`#${buttonId}`)?.removeAttribute('aria-busy');
        refreshActionButtons();
        setActionFeedback(feedbackId,zh,en,kind);
    }

    function refreshActionButtons(){
        const titleButton=$('#articleCopyTitleButton');
        if(titleButton)titleButton.disabled=!currentTitle()||state.busyActions.has('copy-title');
        const coverAvailable=!!currentCover();
        const coverBusy=state.busyActions.has('copy-cover')||state.busyActions.has('download-cover');
        const copyCover=$('#articleCopyCoverButton');
        const downloadCover=$('#articleDownloadCoverButton');
        if(copyCover)copyCover.disabled=!coverAvailable||coverBusy;
        if(downloadCover)downloadCover.disabled=!coverAvailable||coverBusy;
        const content=articleClipboardContent();
        const bodyBusy=state.busyActions.has('copy-article')||state.busyActions.has('export-html');
        const copyButton=$('#articleCopyButton');
        const exportButton=$('#articleExportButton');
        if(copyButton)copyButton.disabled=!content?.html||!content?.text||bodyBusy;
        if(exportButton)exportButton.disabled=!content?.html||bodyBusy;
    }

    function renderStatus(){
        const node = $('[data-article-status]');
        if(!node) return;
        node.replaceChildren();
        if(state.status){
            const message=document.createElement('span');message.textContent=isEnglish()?state.status.en:state.status.zh;node.appendChild(message);
            if(state.status.retry){const button=document.createElement('button');button.id='articleRetrySelectionButton';button.className='article-inline-retry';button.type='button';button.textContent=L('重试保存','Retry save');node.appendChild(button);}
        }
        node.className = `article-status${state.status?.kind ? ` is-${state.status.kind}` : ''}`;
        if(!state.status) node.hidden = true; else node.hidden = false;
    }

    const THEME_LABELS = {
        'moyu-green': {zh:'摸鱼绿',en:'Moyu Green',color:'#6d9e76'},
        'red-white': {zh:'红白色系',en:'Red and White',color:'#ad3838'},
        'graphite-minimal': {zh:'石墨极简风',en:'Graphite Minimal',color:'#343434'},
        'zen-whitespace': {zh:'留白禅意风',en:'Zen Whitespace',color:'#d8d0be'},
        'moyu-ticket': {zh:'摸鱼票据风',en:'Moyu Ticket',color:'#d6a744'},
        'olive-journal': {zh:'橄榄手记',en:'Olive Journal',color:'#69734a'},
    };

    function themeLabel(id){
        const item=THEME_LABELS[id];
        return item?(isEnglish()?item.en:item.zh):String(id||'');
    }

    function themeColor(id){return THEME_LABELS[id]?.color||'var(--article-accent)';}

    function variantEntries(){
        const variants=state.article?.variants;
        return variants&&typeof variants==='object'&&!Array.isArray(variants)?Object.entries(variants):[];
    }

    function selectedVariant(){
        const article=state.article;
        if(!article||!state.selectedThemeId)return null;
        const variant=article.variants?.[state.selectedThemeId];
        if(!variant||typeof variant.body_html!=='string'||!variant.body_html.trim())return variant?{variant,current:false,previewable:false,unsafe:false}:null;
        const current=variant.valid===true&&!!variant.source_sha256&&variant.source_sha256===article.source_sha256;
        try{
            validateArticleHtml(variant.body_html);
            return {variant,current,previewable:true,unsafe:false};
        }catch(error){return {variant,current:false,previewable:false,unsafe:true,error};}
    }

    function currentVariant(){
        const selected=selectedVariant();
        return selected?.current&&selected.previewable?selected.variant:null;
    }

    function articlePreviewKey(themeId,variant){
        if(!themeId||!variant)return '';
        return `${themeId}:${variant.source_sha256}:${variant.html_sha256||variant.body_html}`;
    }

    function currentTitle(){
        const article=state.article;
        if(!article) return null;
        const variant=article.title_variants?.[state.selectedTitleVariantId];
        // 标题是用户可主动复用的历史内容；与当前原文不匹配只表示来源不同，不应禁用历史标题。
        if(variant && variant.valid===true && typeof variant.title==='string' && variant.title.trim()) return variant.title;
        return typeof article.title==='string'?article.title:'';
    }

    function currentCover(){
        const item=state.article?.cover_variants?.find(cover=>String(cover.id)===String(state.selectedCoverVariantId));
        if(!item || item.valid!==true || !/^image\//i.test(String(item.mime||''))) return null;
        const url=sameOriginUrl(item.url);
        return url?{...item,url}:null;
    }

    function sameOriginUrl(value){
        try{const url=new URL(String(value||''),location.href);return url.origin===location.origin&&['http:','https:'].includes(url.protocol)?url.href:'';}catch(e){return '';}
    }

    function coverDisplayName(item,index){
        const name=String(item?.name||'').trim();
        const stem=name.replace(/\.[a-z0-9]{2,6}$/i,'');
        const opaque=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}(?:_(?:image|img|cover)_?\d*)?$/i.test(stem)||/^[a-f0-9]{20,}(?:[-_. ]*(?:image|img|cover)\d*)?$/i.test(stem)||/^[a-f0-9-]{32,}$/i.test(stem);
        return !name||opaque?`${L('封面','Cover')} ${index+1}`:name;
    }

    function validateArticleHtml(value){
        const parsed = new DOMParser().parseFromString(String(value || ''), 'text/html');
        const blocked = parsed.querySelector('script,iframe,frame,frameset,form,button,input,select,textarea,object,embed,base,meta[http-equiv],link[rel="import"]');
        if(blocked) throw new Error(L('文章包含不允许的交互内容，已停止预览和复制。','The article contains active content that is not allowed. Preview and copy are blocked.'));
        parsed.querySelectorAll('*').forEach(node => {
            for(const attribute of [...node.attributes]){
                const key = attribute.name.toLowerCase();
                const val = attribute.value.trim();
                if(key.startsWith('on') || key === 'srcdoc' || ((key === 'href' || key === 'src' || key === 'xlink:href') && /^\s*javascript:/i.test(val))) throw new Error(L('文章包含不安全链接或事件，已停止预览和复制。','The article contains an unsafe link or event handler. Preview and copy are blocked.'));
                if(key === 'style' && /url\s*\(|expression\s*\(/i.test(val)) throw new Error(L('文章样式包含外部资源或表达式，已停止预览和复制。','The article styles contain an external resource or expression. Preview and copy are blocked.'));
            }
        });
        return String(value || '').trim();
    }

    function previewDocument(bodyHtml){
        const content = validateArticleHtml(bodyHtml);
        const baseAppearance = document.documentElement.dataset.studioAppearance === 'dark' ? 'dark' : 'light';
        return `<!doctype html><html lang="${isEnglish()?'en':'zh-CN'}" data-appearance="${baseAppearance}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
            *{box-sizing:border-box}html,body{margin:0;min-height:100%;background:#fff;color:#28252a;font:16px/1.8 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}body{padding:clamp(22px,5vw,68px)}#articlePreviewContent{max-width:760px;margin:0 auto;overflow-wrap:anywhere}img{max-width:100%;height:auto}pre{max-width:100%;overflow:auto;padding:14px;background:#f4f1ed;border-radius:8px;white-space:pre-wrap}code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}table{max-width:100%;border-collapse:collapse}blockquote{margin-inline:0;padding-inline:16px;border-inline-start:3px solid #c8bdd3;color:#595260}
        </style></head><body><main id="articlePreviewContent">${content}</main></body></html>`;
    }

    function renderThemeChoices(){
        const root = $('#articleThemeChoices');
        if(!root) return;
        const entries=variantEntries();
        if(!entries.length){
            root.innerHTML=`<p class="article-theme-empty">${escapeHtml(L('暂无已保存的正文排版。新文章未指定主题时默认使用摸鱼绿。','No saved article layouts yet. New articles default to Moyu Green unless you choose a theme.'))}</p>`;
            return;
        }
        root.innerHTML = entries.map(([id,variant]) => {
            const current=variant?.valid===true&&variant?.source_sha256===state.article?.source_sha256;
            const previewable=typeof variant?.body_html==='string'&&!!variant.body_html.trim();
            const status=current?L('当前原文','Current source'):previewable?L('历史版本','Historical version'):L('无法预览','Unavailable');
            return `<button class="article-theme-choice" type="button" data-theme-id="${escapeHtml(id)}" data-ready="${current?'true':'false'}" aria-pressed="${state.selectedThemeId===id?'true':'false'}" style="--article-theme-color:${escapeHtml(themeColor(id))}"><span class="article-theme-choice-swatch" aria-hidden="true"></span><span class="article-theme-choice-copy"><strong>${escapeHtml(themeLabel(id))}</strong><small>${escapeHtml(status)}</small></span><span class="article-theme-choice-state">${state.selectedThemeId===id?escapeHtml(L('已选','Selected')):''}</span></button>`;
        }).join('');
    }

    function renderArticle(){
        const article = state.article;
        const title = $('#articleTitle');
        const selectedTitle = $('#articleSelectedTitle');
        const source = $('#articleSourceMarkdown');
        const themeNameNode = $('#articlePreviewThemeName');
        const meta = $('#articlePreviewMeta');
        const badge = $('#articlePreviewBadge');
        const historyNote = $('#articlePreviewHistoryNote');
        const frame = $('#articlePreviewFrame');
        const empty = $('#articlePreviewEmpty');
        const copyButton = $('#articleCopyButton');
        const exportButton = $('#articleExportButton');
        if(title) title.textContent = article?.title || L('文章','Article');
        document.title = `${article?.title || L('文章','Article')} · ${L('公众号文章','Articles')}`;
        if(source) source.textContent = article?.source_markdown || '';
        const selected=selectedVariant();
        const variant = selected?.variant||null;
        const titleText=currentTitle();
        const titleCopy=$('#articleCopyTitleButton');
        const titleChoices=$('#articleTitleChoices');
        const titleVariants=article?.title_variants&&typeof article.title_variants==='object'?Object.entries(article.title_variants):[];
        if(selectedTitle)selectedTitle.textContent=titleText||L('暂无标题','No title');
        if(titleCopy)titleCopy.disabled=!titleText||state.busyActions.has('copy-title');
        if(titleChoices)titleChoices.innerHTML=titleVariants.map(([id,item])=>{
            const ready=item?.valid===true&&typeof item?.title==='string'&&item.title.trim();
            const titleVariant=ready?item.title:L('不可用','Unavailable');
            const sourceNote=ready&&item.source_matches===false?L('历史标题','Historical title'):'';
            return `<button class="article-title-choice" type="button" data-title-variant-id="${escapeHtml(id)}" aria-pressed="${state.selectedTitleVariantId===id?'true':'false'}" ${ready?'':'disabled'}><span>${escapeHtml(titleVariant)}</span>${sourceNote?`<small>${escapeHtml(sourceNote)}</small>`:''}</button>`;
        }).join('');
        renderCoverHistory();
        const themeName = state.selectedThemeId ? themeLabel(state.selectedThemeId) : '—';
        if(themeNameNode) themeNameNode.textContent = themeName;
        if(meta) meta.textContent = article ? `${L(`原文修订 ${article.revision}`, `Source revision ${article.revision}`)}${selected?.previewable&&!selected.current?` · ${L('历史版本','Historical version')}`:''}` : '';
        if(badge){ badge.textContent = selected?.previewable?(selected.current?L('当前排版','Current layout'):L('历史排版','Historical layout')):L('尚无可用排版','No available layout'); badge.dataset.ready = selected?.current&&selected.previewable ? 'true' : 'false'; }
        if(historyNote){historyNote.hidden=!(selected?.previewable&&!selected.current);historyNote.textContent=L('当前显示的是未通过文章版本匹配校验的历史排版；可查看，但不能复制或导出为当前版本。','This saved layout did not pass the current article version check. You can preview it, but cannot copy or export it as the current version.');}
        const previewKey=selected?.previewable?articlePreviewKey(state.selectedThemeId,variant):'';
        if(selected?.unsafe){const message=selected.error?.message||L('此排版无法安全预览。','This layout cannot be previewed safely.');setStatus(message,message,'error');}
        if(frame){
            if(variant && previewKey){
                if(previewKey !== state.lastPreviewKey){ frame.dataset.previewKey=previewKey;frame.dataset.loadedPreviewKey='';frame.dataset.previewKind=selected.current?'current':'historical';frame.srcdoc = previewDocument(variant.body_html); state.lastPreviewKey = previewKey; }
                frame.hidden = false;
            } else { frame.removeAttribute('srcdoc'); frame.hidden = true; frame.dataset.previewKey='';frame.dataset.loadedPreviewKey='';frame.dataset.previewKind='';state.lastPreviewKey = ''; }
        }
        if(empty){
            empty.hidden = !!(selected?.previewable&&previewKey);
            empty.textContent = selected?.unsafe ? L('此排版包含不安全内容，已停止预览。可重新读取文章以确认最新版本。','This layout contains unsafe content, so its preview is blocked. Reload the article to check the latest version.') : selected ? L('当前主题的已保存排版不可读取。可重新读取文章以确认状态。','The saved layout for this theme is unavailable. Reload the article to check its status.') : !variantEntries().length ? L('当前文章还没有已保存的正文排版。新文章未指定主题时默认使用摸鱼绿；Markdown 原文可在下方查看。','This article has no saved body layout yet. New articles default to Moyu Green unless you choose a theme. View the Markdown source below.') : L('请选择左侧已保存的排版版本。','Choose a saved layout version on the left.');
        }
        const currentPreviewReady=!!(selected?.current&&selected.previewable&&previewKey&&frame?.dataset.loadedPreviewKey===previewKey);
        const anyPreviewReady=!!(selected?.previewable&&previewKey&&frame?.dataset.loadedPreviewKey===previewKey);
        const bodyBusy=state.busyActions.has('copy-article')||state.busyActions.has('export-html');
        if(copyButton) copyButton.disabled = !currentPreviewReady||bodyBusy;
        if(exportButton) exportButton.disabled = !currentPreviewReady||bodyBusy;
        const fullPreviewButton=$('#articleFullPreviewButton');
        if(fullPreviewButton)fullPreviewButton.disabled=!anyPreviewReady;
        renderThemeChoices();
    }

    function renderCoverHistory(){
        const root=$('#articleCoverHistory');
        const copyButton=$('#articleCopyCoverButton');
        const downloadButton=$('#articleDownloadCoverButton');
        if(!root)return;
        const covers=Array.isArray(state.article?.cover_variants)?state.article.cover_variants:[];
        const usable=covers.filter(item=>item&&item.valid===true&&/^image\//i.test(String(item.mime||''))&&sameOriginUrl(item.url));
        if(!covers.length){root.innerHTML=`<div class="article-cover-empty">${escapeHtml(L('暂时没有封面记录。','No cover history is available yet.'))}</div>`;}
        else if(!usable.length){root.innerHTML=`<div class="article-cover-empty">${escapeHtml(L('封面历史没有可读取的图片引用。','Cover history has no readable image references.'))}</div>`;}
        else root.innerHTML=usable.map((item,index)=>{
            const selected=String(state.selectedCoverVariantId)===String(item.id);
            const note=item.source_matches===false?L('历史封面','Historical cover'):selected?L('当前封面','Selected cover'):L('封面历史','Cover history');
            const displayName=coverDisplayName(item,index);
            return `<article class="article-cover-choice" data-selected="${selected?'true':'false'}"><button type="button" class="article-cover-zoom" data-cover-preview-id="${escapeHtml(item.id)}" aria-label="${escapeHtml(L('放大预览','Open full image preview'))}" title="${escapeHtml(item.name||displayName)}"><img src="${escapeHtml(sameOriginUrl(item.url))}" alt="${escapeHtml(displayName)}" loading="${selected?'eager':'lazy'}"></button><div class="article-cover-choice-copy"><strong>${escapeHtml(displayName)}</strong><small>${escapeHtml(note)}</small></div><button type="button" class="article-cover-select" data-cover-variant-id="${escapeHtml(item.id)}" aria-pressed="${selected?'true':'false'}">${escapeHtml(selected?L('当前封面','Selected cover'):L('采用此封面','Use this cover'))}</button></article>`;
        }).join('');
        const selected=currentCover();
        const coverBusy=state.busyActions.has('copy-cover')||state.busyActions.has('download-cover');
        if(copyButton)copyButton.disabled=!selected||coverBusy;
        if(downloadButton)downloadButton.disabled=!selected||coverBusy;
    }

    function openCoverLightbox(item){
        const url=sameOriginUrl(item?.url);
        const dialog=$('#articleCoverLightbox');
        const image=$('#articleCoverLightboxImage');
        if(!dialog||!image||!url)return;
        dialog.dataset.coverId=String(item.id||'');
        image.src=url;
        const usable=(state.article?.cover_variants||[]).filter(cover=>cover&&cover.valid===true&&/^image\//i.test(String(cover.mime||''))&&sameOriginUrl(cover.url));
        const index=usable.findIndex(cover=>String(cover.id)===String(item.id));
        const label=coverDisplayName(item,Math.max(0,index));
        image.alt=label;
        $('#articleCoverLightboxCaption').textContent=label;
        if(!dialog.open)dialog.showModal();
        $('#articleCoverLightboxClose')?.focus();
    }

    async function loadArticle({background=false,preserveSelection=false,allowPending=false}={}){
        if(!articleId){setStatus('文章项目 ID 缺失。','Article project ID is missing.','error');return false;}
        if(state.pendingSaves&&!background&&!allowPending){setStatus('正在保存当前选择，请稍后再读取。','Saving the current selection. Reload in a moment.');return false;}
        const sequence=++state.loadSequence;
        const selectionSequenceAtStart=state.selectionSequence;
        if(!background)setStatus('正在读取文章…','Loading article…');
        try{
            const data=await api(`/api/studio/articles/${encodeURIComponent(articleId)}`);
            if(sequence!==state.loadSequence)return false;
            const article=data?.article;
            if(!article||String(article.project_id)!==articleId)throw new Error(L('文章项目不存在或无法读取。','This article project does not exist or could not be loaded.'));
            if(background&&state.pendingSaves)return false;
            if(Number(article.revision||0)<state.revision)return false;
            if(background&&state.article&&Number(article.revision||0)<=Number(state.article.revision||0)&&article.source_sha256===state.article.source_sha256)return false;
            const keepLocal=preserveSelection||selectionSequenceAtStart!==state.selectionSequence;
            const local={theme:state.selectedThemeId,title:state.selectedTitleVariantId,cover:state.selectedCoverVariantId};
            state.article=article;state.revision=Number(article.revision||0);
            if(!keepLocal){
                const savedThemes=variantEntries();
                state.selectedThemeId=article.selected_theme_id||(
                    savedThemes.some(([id])=>id==='moyu-green')?'moyu-green':savedThemes[0]?.[0]||'moyu-green'
                );
                state.selectedTitleVariantId=article.selected_title_variant_id||'';
                state.selectedCoverVariantId=article.selected_cover_variant_id||'';
                state.unsavedSelection=null;
            }else{
                state.selectedThemeId=local.theme;state.selectedTitleVariantId=local.title;state.selectedCoverVariantId=local.cover;
            }
            if(!background)setStatus('文章已读取。','Article loaded.','success');else state.status=null;
            renderArticle();
            return true;
        }catch(error){
            if(sequence!==state.loadSequence)return false;
            const message=error?.message||L('文章读取失败，请重试。','Could not load the article. Try again.');
            setStatus(message,message,'error');
            return false;
        }
    }

    function persistSelection(field,value,{force=false}={}){
        const definition={
            theme:{local:'selectedThemeId',localKey:'theme',payload:'selected_theme_id',zh:'排版选择已保存。',en:'Layout selection saved.'},
            title:{local:'selectedTitleVariantId',localKey:'title',payload:'selected_title_variant_id',zh:'标题版本已保存。',en:'Title selection saved.'},
            cover:{local:'selectedCoverVariantId',localKey:'cover',payload:'selected_cover_variant_id',zh:'封面选择已保存。',en:'Cover selection saved.'},
        }[field];
        if(!definition||!state.article||(!force&&state[definition.local]===value))return;
        state[definition.local]=value;
        const sequence=++state.selectionSequence;
        state.unsavedSelection={field,value};
        renderArticle();
        state.pendingSaves++;
        state.saveChain=state.saveChain.catch(()=>{}).then(async()=>{
            const response=await api(`/api/studio/articles/${encodeURIComponent(articleId)}`,{
                method:'PUT',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({expected_revision:state.revision,[definition.payload]:value}),
            });
            const updated=response?.article;
            if(updated?.project_id!==articleId||!Number.isFinite(Number(updated?.revision)))throw new Error(L('文章保存响应无效。','The article save response was invalid.'));
            const local={theme:state.selectedThemeId,title:state.selectedTitleVariantId,cover:state.selectedCoverVariantId};
            state.revision=Number(updated.revision);
            state.article={...state.article,...updated,revision:state.revision};
            state.article.selected_theme_id=local.theme;
            state.article.selected_title_variant_id=local.title;
            state.article.selected_cover_variant_id=local.cover;
            if(sequence===state.selectionSequence){
                const returned=updated[definition.payload];
                const canonical=Object.prototype.hasOwnProperty.call(updated,definition.payload)?String(returned||''):local[definition.localKey];
                state[definition.local]=canonical;
                state.article[definition.payload]=returned===undefined?canonical:(returned??null);
                state.unsavedSelection=null;setStatus(definition.zh,definition.en,'success');renderArticle();
            }
        }).catch(async error=>{
            if(sequence!==state.selectionSequence)return;
            if(error?.status===409){
                setStatus(L('文章已被更新。正在读取最新内容；当前选择仍是未保存草稿。','The article changed elsewhere. Loading the latest content; your selection remains an unsaved draft.'),'The article changed elsewhere. Loading the latest content; your selection remains an unsaved draft.','error',true);
                const reloaded=await loadArticle({preserveSelection:true,allowPending:true});
                if(sequence!==state.selectionSequence)return;
                const zh=reloaded?'文章已更新，当前选择仍是未保存草稿。':'文章已更新，但最新内容读取失败；当前选择仍是未保存草稿。';
                const en=reloaded?'The article was updated. Your selection remains an unsaved draft.':'The article was updated, but the latest content could not be loaded. Your selection remains an unsaved draft.';
                setStatus(zh,en,'error',true);
                return;
            }
            const message=error?.message||L('选择未保存，请重试。','The selection was not saved. Try again.');
            setStatus(message,message,'error',true);
        }).finally(()=>{state.pendingSaves=Math.max(0,state.pendingSaves-1);});
    }

    function selectTheme(id){if(Object.prototype.hasOwnProperty.call(state.article?.variants||{},id))persistSelection('theme',id);}
    function selectTitleVariant(id){
        const item=state.article?.title_variants?.[id];
        if(item?.valid===true&&typeof item.title==='string'&&item.title.trim())persistSelection('title',id);
    }
    function selectCoverVariant(id){
        const item=state.article?.cover_variants?.find(cover=>String(cover.id)===String(id));
        if(item?.valid===true&&sameOriginUrl(item.url))persistSelection('cover',id);
    }
    function retrySelection(){if(state.unsavedSelection)persistSelection(state.unsavedSelection.field,state.unsavedSelection.value,{force:true});}

    function textFromArticleRoot(root){
        if(!root) return '';
        return String(root.innerText || root.textContent || '').replace(/\u00a0/g,' ').trim();
    }

    function articleClipboardContent(){
        const variant=currentVariant();
        const key=articlePreviewKey(state.selectedThemeId,variant);
        const doc = $('#articlePreviewFrame')?.contentDocument;
        const root = doc?.getElementById('articlePreviewContent');
        const frame=$('#articlePreviewFrame');
        if(!root||!variant||!key||frame?.dataset.previewKey!==key||frame?.dataset.loadedPreviewKey!==key)return null;
        try{validateArticleHtml(variant.body_html);}catch(e){return null;}
        return {html:variant.body_html.trim(),text:textFromArticleRoot(root),key};
    }

    function portableSnapshot(content){
        return {articleId:String(state.article?.project_id||articleId),revision:state.revision,themeId:state.selectedThemeId,key:content?.key||''};
    }

    function assertPortableSnapshot(snapshot){
        const current=articleClipboardContent();
        if(!current||!snapshot||String(state.article?.project_id||articleId)!==snapshot.articleId
            ||state.revision!==snapshot.revision||state.selectedThemeId!==snapshot.themeId||current.key!==snapshot.key){
            const error=new Error('article version changed while preparing portable content');
            error.code='article-changed';
            throw error;
        }
        return current;
    }

    function portableImageSource(value){
        const raw=String(value||'').trim();
        if(/^data:image\//i.test(raw))return {kind:'embedded',value:raw};
        let url;
        try{url=new URL(raw,location.href);}catch(e){return {kind:'unsupported'};}
        if(url.username||url.password)return {kind:'unsupported'};
        if(url.protocol==='https:'&&url.origin!==location.origin)return {kind:'remote',value:url.href};
        if(url.origin!==location.origin||!['http:','https:'].includes(url.protocol))return {kind:'unsupported'};
        if(url.search||url.hash)return {kind:'unsupported'};
        const match=url.pathname.match(/^\/api\/(results|materials)\/([^/]+)$/i);
        if(!match)return {kind:'unsupported'};
        let id='';
        try{id=decodeURIComponent(match[2]);}catch(e){return {kind:'unsupported'};}
        if(!id||id==='.'||id==='..'||/[\\/\u0000]/.test(id))return {kind:'unsupported'};
        return {kind:'managed',value:url.href};
    }

    function readBlobAsDataUrl(blob,mime){
        return new Promise((resolve,reject)=>{
            const reader=new FileReader();
            reader.onerror=()=>reject(new Error('image data could not be encoded'));
            reader.onload=()=>typeof reader.result==='string'?resolve(reader.result):reject(new Error('image data could not be encoded'));
            reader.readAsDataURL(new Blob([blob],{type:mime}));
        });
    }

    function verifyEmbeddedImage(dataUrl){
        return new Promise((resolve,reject)=>{
            const image=new Image();
            const timer=setTimeout(()=>{image.onload=image.onerror=null;reject(new Error('image decode timed out'));},10000);
            image.onload=()=>{clearTimeout(timer);image.onload=image.onerror=null;image.naturalWidth>0&&image.naturalHeight>0?resolve():reject(new Error('image has no visible pixels'));};
            image.onerror=()=>{clearTimeout(timer);image.onload=image.onerror=null;reject(new Error('image could not be decoded'));};
            image.src=dataUrl;
        });
    }

    async function fetchPortableImage(url){
        const controller=new AbortController();
        const timeout=setTimeout(()=>controller.abort(),30000);
        let response,headerMime,blob;
        try{
            response=await fetch(url,{credentials:'same-origin',redirect:'error',signal:controller.signal});
            const finalSource=portableImageSource(response.url||url);
            if(!response.ok||finalSource.kind!=='managed'){
                const error=new Error('managed article image could not be read');error.code='article-image-fetch';throw error;
            }
            headerMime=String(response.headers.get('content-type')||'').split(';')[0].trim().toLowerCase();
            if(!/^image\/[a-z0-9.+-]+$/i.test(headerMime)){
                const error=new Error('managed article image response is not an image');error.code='article-image-invalid';throw error;
            }
            blob=await response.blob();
        }catch(e){
            if(e?.code)throw e;
            const error=new Error('managed article image could not be read');error.code='article-image-fetch';throw error;
        }finally{clearTimeout(timeout);}
        if(!blob.size){const error=new Error('managed article image is empty');error.code='article-image-invalid';throw error;}
        let dataUrl;
        try{dataUrl=await readBlobAsDataUrl(blob,headerMime);await verifyEmbeddedImage(dataUrl);}catch(e){const error=new Error('managed article image is not a decodable image');error.code='article-image-invalid';throw error;}
        return dataUrl;
    }

    async function preparePortableContent(content,snapshot,onProgress){
        const parsed=new DOMParser().parseFromString(content.html,'text/html');
        try{validateArticleHtml(parsed.body.innerHTML);}catch(e){const error=new Error('article markup could not be validated for export');error.code='portable-markup';throw error;}
        const images=[...parsed.body.querySelectorAll('img')];
        const pictureSources=[...parsed.body.querySelectorAll('picture source[srcset]')];
        pictureSources.forEach(source=>source.remove());
        let prepared=0;
        for(let index=0;index<images.length;index++){
            assertPortableSnapshot(snapshot);
            const image=images[index];
            image.removeAttribute('srcset');
            image.removeAttribute('sizes');
            for(const attribute of [...image.attributes]){
                if(attribute.name.toLowerCase().startsWith('data-')&&/src/i.test(attribute.name))image.removeAttribute(attribute.name);
            }
            const source=portableImageSource(image.getAttribute('src'));
            if(!source.value){const error=new Error('article image does not have a portable source');error.code='portable-source';throw error;}
            if(source.kind==='managed'){
                try{image.setAttribute('src',await fetchPortableImage(source.value));}
                catch(error){error.imageLabel=image.getAttribute('alt')?.trim()||`#${index+1}`;throw error;}
            }
            else if(source.kind==='embedded'){
                try{await verifyEmbeddedImage(source.value);}catch(e){const error=new Error('embedded article image is not decodable');error.code='article-image-invalid';error.imageLabel=image.getAttribute('alt')?.trim()||`#${index+1}`;throw error;}
            }
            else if(source.kind==='unsupported'){const error=new Error('article image source is not a managed media URL or portable remote image');error.code='portable-source';error.imageLabel=image.getAttribute('alt')?.trim()||`#${index+1}`;throw error;}
            prepared++;
            onProgress?.(prepared,images.length);
        }
        assertPortableSnapshot(snapshot);
        return {...content,html:parsed.body.innerHTML};
    }

    function portableFailureMessage(error,action){
        const imageLabel=error?.imageLabel?`「${error.imageLabel}」`:(error?.imageIndex?` #${error.imageIndex}`:'');
        if(error?.code==='article-changed')return ['准备期间文章版本已变化，请重新复制或导出当前正文。','The article changed while it was being prepared. Copy or export the current version again.'];
        if(error?.code==='article-image-fetch'||error?.code==='article-image-invalid')return [`正文图片${imageLabel}读取或校验失败，未${action==='copy'?'复制':'导出'}；请检查素材是否仍可读取后重试。`,`Article image${imageLabel} could not be read or verified. Nothing was ${action==='copy'?'copied':'exported'}; check the media and try again.`];
        if(error?.code==='portable-source')return [`正文图片${imageLabel}含有无法安全携带的地址，未${action==='copy'?'复制':'导出'}；请确认图片引用的是文章共享素材或 HTTPS 图片。`,`Article image${imageLabel} uses an unsupported source. Nothing was ${action==='copy'?'copied':'exported'}; use a shared article asset or an HTTPS image.`];
        return ['正文内容准备失败，未'+(action==='copy'?'复制':'导出')+'；请重试。','The article could not be prepared. Nothing was '+(action==='copy'?'copied':'exported')+'; try again.'];
    }

    async function fallbackRichCopy(content){
        let holder = null;
        const onCopy = event => {
            try {
                event.clipboardData?.setData('text/html', content.html);
                event.clipboardData?.setData('text/plain', content.text);
                event.preventDefault();
            } catch(e) {}
        };
        try {
            holder = document.createElement('div');
            holder.contentEditable = 'true'; holder.tabIndex = -1; holder.setAttribute('aria-hidden','true');
            holder.innerHTML = content.html;
            Object.assign(holder.style,{position:'fixed',left:'-10000px',top:'0',width:'1px',height:'1px',overflow:'hidden'});
            document.body.appendChild(holder);
            document.addEventListener('copy', onCopy, true);
            const range=document.createRange();range.selectNodeContents(holder);
            const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
            holder.focus();
            return document.execCommand('copy');
        } catch(e){ return false; }
        finally {
            document.removeEventListener('copy', onCopy, true);
            window.getSelection()?.removeAllRanges();
            holder?.remove();
        }
    }

    async function copyCurrentArticle(){
        const content=articleClipboardContent();
        if(!content?.html || !content.text){setActionFeedback('articleCopyFeedback','当前排版没有可复制的正文。','The current layout has no article content to copy.','error');return;}
        if(!beginAction('copy-article','articleCopyButton','articleCopyFeedback','正在复制正文…','Copying article…'))return;
        const snapshot=portableSnapshot(content);
        let preparedPromise=null,copied=false;
        try {
            const totalImages=(new DOMParser().parseFromString(content.html,'text/html')).querySelectorAll('img').length;
            if(totalImages)setActionFeedback('articleCopyFeedback',`正在准备图片 0/${totalImages}…`,`Preparing images 0/${totalImages}…`,'pending');
            preparedPromise=preparePortableContent(content,snapshot,(done,total)=>setActionFeedback('articleCopyFeedback',`正在准备图片 ${done}/${total}…`,`Preparing images ${done}/${total}…`,'pending'));
            if(navigator.clipboard?.write && window.ClipboardItem){
                const htmlBlob=preparedPromise.then(prepared=>new Blob([prepared.html],{type:'text/html'}));
                htmlBlob.catch(()=>{});
                try{
                    const item=new ClipboardItem({
                        'text/html':htmlBlob,
                        'text/plain':new Blob([content.text],{type:'text/plain'}),
                    });
                    await navigator.clipboard.write([item]);copied=true;
                }catch(e){}
            }
            const prepared=await (preparedPromise||preparePortableContent(content,snapshot));
            assertPortableSnapshot(snapshot);
            if(!copied)copied=await fallbackRichCopy(prepared);
        if(copied){
            finishAction('copy-article','articleCopyButton','articleCopyFeedback','正文已复制。粘贴到公众号编辑器后，请检查图片显示与排版。','Article copied. Check image rendering and layout after pasting into the WeChat editor.','success');
        } else {
            finishAction('copy-article','articleCopyButton','articleCopyFeedback','正文复制失败，未写入剪贴板；请重试或导出 HTML。','Article copy failed; nothing was written to the clipboard. Try again or export HTML.','error');
        }
        }catch(error){
            const [zh,en]=portableFailureMessage(error,'copy');
            finishAction('copy-article','articleCopyButton','articleCopyFeedback',zh,en,'error');
        }
    }

    async function copyPlainText(text){
        const value=String(text||'').trim();
        if(!value)return false;
        let copied=false;
        try{if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(value);copied=true;}}catch(e){}
        if(!copied){
            let area=null;
            try{area=document.createElement('textarea');area.value=value;area.readOnly=true;area.style.position='fixed';area.style.left='-10000px';document.body.appendChild(area);area.select();copied=document.execCommand('copy');}
            catch(e){}
            finally{area?.remove();}
        }
        return copied;
    }

    function selectElementForManualCopy(selector){
        try{
            const element=$(selector);
            if(!element)return false;
            const range=element.ownerDocument.createRange();range.selectNodeContents(element);
            const selection=element.ownerDocument.getSelection();selection.removeAllRanges();selection.addRange(range);
            return true;
        }catch(e){return false;}
    }

    async function copyCurrentTitle(){
        const title=currentTitle();
        if(!title){setActionFeedback('articleTitleFeedback','没有可复制的标题。','There is no title to copy.','error');return;}
        if(!beginAction('copy-title','articleCopyTitleButton','articleTitleFeedback','正在复制标题…','Copying title…'))return;
        let copied=false;
        try{copied=await copyPlainText(title);}catch(e){}
        if(copied)finishAction('copy-title','articleCopyTitleButton','articleTitleFeedback','标题已复制。','Title copied.','success');
        else{
            selectElementForManualCopy('#articleSelectedTitle');
            finishAction('copy-title','articleCopyTitleButton','articleTitleFeedback','标题复制失败，标题已选中，请手动复制。','Title copy failed. The title is selected; copy it manually.','error');
        }
    }

    async function copyCurrentCover(){
        const cover=currentCover();
        if(!cover){setActionFeedback('articleCoverStatus','没有可复制的封面图片。','There is no cover image to copy.','error');return;}
        if(!navigator.clipboard?.write||!window.ClipboardItem){
            setActionFeedback('articleCoverStatus','浏览器不支持直接复制图片，请使用“下载图片”。','This browser cannot copy images directly. Use Download image instead.','error');
            return;
        }
        if(!beginAction('copy-cover','articleCopyCoverButton','articleCoverStatus','正在准备复制封面…','Preparing cover image…'))return;
        let message=['无法复制此封面图片，请尝试下载。','Could not copy this cover image. Try downloading it.','error'];
        try{
            const response=await fetch(cover.url);
            if(!response.ok)throw new Error('image unavailable');
            const blob=await response.blob();
            const mime=String(cover.mime||blob.type||'').split(';')[0].toLowerCase();
            if(!mime.startsWith('image/')||!blob.type.startsWith('image/'))throw new Error('unsupported image');
            await navigator.clipboard.write([new ClipboardItem({[mime]:blob})]);
            message=['封面图片已复制。','Cover image copied.','success'];
        }catch(e){}
        finishAction('copy-cover','articleCopyCoverButton','articleCoverStatus',...message);
    }

    function downloadCurrentCover(){
        const cover=currentCover();
        if(!cover){setActionFeedback('articleCoverStatus','没有可下载的封面图片。','There is no cover image to download.','error');return;}
        if(!beginAction('download-cover','articleDownloadCoverButton','articleCoverStatus','正在启动下载…','Starting download…'))return;
        const filename=String(cover.name||`cover-${cover.id}`).replace(/[\\/:*?"<>|]+/g,'_').slice(0,100)||'cover';
        let link=null;
        try{
            link=document.createElement('a');link.href=cover.url;link.download=filename;link.rel='noopener';document.body.appendChild(link);link.click();
            finishAction('download-cover','articleDownloadCoverButton','articleCoverStatus',`已开始下载：${filename}`,`Download started: ${filename}`,'success');
        }catch(e){
            finishAction('download-cover','articleDownloadCoverButton','articleCoverStatus','下载未能启动，请重试。','The download could not be started. Try again.','error');
        }finally{link?.remove();}
    }

    function setFullPreview(open){
        const region=$('.article-preview-region');
        const button=$('#articleFullPreviewButton');
        const close=$('#articleFullPreviewClose');
        if(!region)return;
        region.classList.toggle('is-full-preview',!!open);
        button?.setAttribute('aria-pressed',open?'true':'false');
        if(close)close.hidden=!open;
        document.body.classList.toggle('article-full-preview-open',!!open);
        if(open)close?.focus();else button?.focus();
    }

    async function exportHtml(){
        const content=articleClipboardContent();
        if(!content?.html){setActionFeedback('articleCopyFeedback','当前排版未通过版本匹配校验，不能导出。','The current layout does not match this article version and cannot be exported.','error');return;}
        if(!beginAction('export-html','articleExportButton','articleCopyFeedback','正在准备 HTML 下载…','Preparing HTML download…'))return;
        const snapshot=portableSnapshot(content);
        let url='',link=null;
        try{
            const totalImages=(new DOMParser().parseFromString(content.html,'text/html')).querySelectorAll('img').length;
            if(totalImages)setActionFeedback('articleCopyFeedback',`正在准备图片 0/${totalImages}…`,`Preparing images 0/${totalImages}…`,'pending');
            const prepared=await preparePortableContent(content,snapshot,(done,total)=>setActionFeedback('articleCopyFeedback',`正在准备图片 ${done}/${total}…`,`Preparing images ${done}/${total}…`,'pending'));
            assertPortableSnapshot(snapshot);
            const name=(themeLabel(state.selectedThemeId)||state.article?.title||'article').replace(/[\\/:*?"<>|]+/g,'_').slice(0,80);
            const html=`<!doctype html><html lang="${isEnglish()?'en':'zh-CN'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(state.article?.title||'')}</title></head><body>${prepared.html}</body></html>`;
            url=URL.createObjectURL(new Blob([html],{type:'text/html;charset=utf-8'}));
            link=document.createElement('a');link.href=url;link.download=`${name}.html`;document.body.appendChild(link);link.click();
            setTimeout(()=>URL.revokeObjectURL(url),1200);
            finishAction('export-html','articleExportButton','articleCopyFeedback',`已开始下载：${name}.html`,`Download started: ${name}.html`,'success');
        }catch(e){
            if(url)URL.revokeObjectURL(url);
            const [zh,en]=portableFailureMessage(e,'export');
            finishAction('export-html','articleExportButton','articleCopyFeedback',e?.code==='article-image-fetch'||e?.code==='article-image-invalid'||e?.code==='portable-source'||e?.code==='article-changed'?zh:'HTML 导出未能启动，请重试。',e?.code==='article-image-fetch'||e?.code==='article-image-invalid'||e?.code==='portable-source'||e?.code==='article-changed'?en:'The HTML export could not be started. Try again.','error');
        }finally{link?.remove();}
    }

    function applyLanguage(){
        const en=isEnglish();
        document.documentElement.lang=en?'en':'zh-CN';
        $('#articleBackLink span').textContent=en?'Article projects':'文章项目';
        $('.article-kicker').textContent=en?'WECHAT ARTICLE':'公众号文章';
        $('#articleLayoutsTitle').textContent=en?'Saved layouts':'已有排版';
        $('#articleLayoutHint').textContent=en?'Select a saved layout. Historical versions can be previewed; only layouts matching the current source can be copied or exported.':'选择已保存的排版。历史版本可预览；只有与当前原文匹配的排版可以复制或导出。';
        $('#articlePreviewFrame').title=en?'Article preview':'文章正文预览';
        $('#articleCopyButton span').textContent=en?'Copy article':'复制正文';
        $('#articleExportButton span').textContent=en?'Export HTML':'导出 HTML';
        $('#articleRefreshButton').title=en?'Reload article':'重新读取文章';
        $('#articleRefreshButton').setAttribute('aria-label',$('#articleRefreshButton').title);
        $('#articleLanguageButton').textContent=en?'EN':'中';
        $('#articleLanguageButton').title=en?'Switch language':'切换语言';
        $('#articleLanguageButton').setAttribute('aria-label',$('#articleLanguageButton').title);
        $('#articleThemeButton').title=en?'Switch theme':'切换主题';
        $('#articleThemeButton').setAttribute('aria-label',$('#articleThemeButton').title);
        $('#articleSourceDetails summary').textContent=en?'View the Markdown source from the Agent':'查看 Agent 提供的 Markdown 原文';
        $('#articleImageNote').textContent=en?'After pasting, check how images and layout appear in the WeChat editor.':'复制后请在公众号编辑器中检查图片显示与样式。';
        $('#articleTitleSectionHeading').textContent=en?'Title':'标题';
        $('#articleCoverSectionHeading').textContent=en?'Cover':'封面';
        $('#articleBodySectionHeading').textContent=en?'Body':'正文';
        $('#articleCopyTitleButton span').textContent=en?'Copy title':'复制标题';
        $('#articleCopyCoverButton span').textContent=en?'Copy image':'复制图片';
        $('#articleDownloadCoverButton span').textContent=en?'Download image':'下载图片';
        $('#articleFullPreviewButton span').textContent=en?'Full preview':'完整预览';
        $('#articleFullPreviewClose').title=en?'Close full preview':'关闭完整预览';
        $('#articleFullPreviewClose').setAttribute('aria-label',$('#articleFullPreviewClose').title);
        $('#articleCoverHint').textContent=en?'Choose the cover to use. You can copy or download the original image.':'选择本次要采用的封面，可复制或下载原图。';
        $('#articleCoverLightboxClose').setAttribute('aria-label',en?'Close image preview':'关闭图片预览');
        $('#articleCoverLightboxTitle').textContent=en?'Cover preview':'封面预览';
        $('#articleCoverLightboxHint').textContent=en?'Click outside or press Escape to close.':'点击空白处或按 Esc 关闭。';
        renderStatus();
        ['articleTitleFeedback','articleCoverStatus','articleCopyFeedback'].forEach(renderActionFeedback);
        renderArticle();
    }

    function bindEvents(){
        $('#articleThemeChoices')?.addEventListener('click',event=>{
            const button=event.target.closest('[data-theme-id]');
            if(button) selectTheme(button.dataset.themeId);
        });
        $('#articleTitleChoices')?.addEventListener('click',event=>{
            const button=event.target.closest('[data-title-variant-id]');if(button)selectTitleVariant(button.dataset.titleVariantId);
        });
        $('#articleCoverHistory')?.addEventListener('click',event=>{
            const preview=event.target.closest('[data-cover-preview-id]');
            if(preview){
                const item=state.article?.cover_variants?.find(cover=>String(cover.id)===String(preview.dataset.coverPreviewId));
                if(item)openCoverLightbox(item);
                return;
            }
            const button=event.target.closest('[data-cover-variant-id]');
            if(button)selectCoverVariant(button.dataset.coverVariantId);
        });
        $('[data-article-status]')?.addEventListener('click',event=>{if(event.target.closest('#articleRetrySelectionButton'))retrySelection();});
        $('#articleCopyButton')?.addEventListener('click',copyCurrentArticle);
        $('#articleCopyTitleButton')?.addEventListener('click',copyCurrentTitle);
        $('#articleCopyCoverButton')?.addEventListener('click',copyCurrentCover);
        $('#articleDownloadCoverButton')?.addEventListener('click',downloadCurrentCover);
        $('#articleExportButton')?.addEventListener('click',exportHtml);
        $('#articleFullPreviewButton')?.addEventListener('click',()=>setFullPreview(true));
        $('#articleFullPreviewClose')?.addEventListener('click',()=>setFullPreview(false));
        $('#articleCoverLightboxClose')?.addEventListener('click',()=>$('#articleCoverLightbox')?.close());
        $('#articleCoverLightbox')?.addEventListener('click',event=>{if(event.target===event.currentTarget)event.currentTarget.close();});
        $('#articleCoverLightbox')?.addEventListener('close',()=>{
            const coverId=$('#articleCoverLightbox')?.dataset.coverId||'';
            [...document.querySelectorAll('[data-cover-preview-id]')].find(button=>String(button.dataset.coverPreviewId)===coverId)?.focus();
        });
        $('#articleRefreshButton')?.addEventListener('click',()=>loadArticle());
        $('#articleLanguageButton')?.addEventListener('click',()=>window.StudioI18n?.toggle?.());
        $('#articleThemeButton')?.addEventListener('click',()=>{
            const appearance=window.StudioTheme?.get?.()||'light';
            window.StudioTheme?.set?.(appearance==='dark'?'light':'dark');
        });
        $('#articlePreviewFrame')?.addEventListener('load',()=>{
            const frame=$('#articlePreviewFrame');
            const key=frame?.dataset.previewKey||'';
            if(!key)return;
            try{if(frame.contentDocument?.getElementById('articlePreviewContent')){frame.dataset.loadedPreviewKey=key;renderArticle();}}catch(e){}
        });
        document.addEventListener('keydown',event=>{if(event.key==='Escape'&&$('.article-preview-region.is-full-preview'))setFullPreview(false);});
        window.addEventListener('studio-lang-change',applyLanguage);
        window.addEventListener('studio-theme-change',renderArticle);
        window.addEventListener('message',event=>{
            if(event.origin!==location.origin||event.source!==window.parent)return;
            if(event.data?.type==='studio-lang'&&event.data.lang)window.StudioI18n?.set?.(event.data.lang);
            if(event.data?.type==='studio-theme')window.StudioTheme?.applyPreference?.(event.data.preference);
        });
        window.addEventListener('focus',()=>loadArticle({background:true}));
        document.addEventListener('visibilitychange',()=>{if(!document.hidden)loadArticle({background:true});});
    }

    async function initialize(){
        if(window.lucide?.createIcons)window.lucide.createIcons();
        bindEvents();applyLanguage();
        await loadArticle();
        state.syncTimer=window.setInterval(()=>{if(!document.hidden&&!state.pendingSaves)loadArticle({background:true});},20000);
    }

    initialize();
})();
