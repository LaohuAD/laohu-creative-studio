/* 文章项目的预览、主题版本选择与复制；正文由后端/外部 Agent 维护。 */
(function(){
    'use strict';

    const params = new URLSearchParams(location.search);
    const articleId = String(params.get('id') || '').trim();
    const state = {
        article: null, selectedThemeId: '', selectedTitleVariantId: '', selectedCoverVariantId: '',
        revision: 0, loadSequence: 0, selectionSequence: 0, pendingSaves: 0,
        saveChain: Promise.resolve(), lastPreviewKey: '', status: null, syncTimer: 0, unsavedSelection: null,
        busyActions: new Set(), actionFeedback: {}, actionFeedbackTimers: {}, statusTimer: 0, bodyView: 'preview', coverPreviewOpener: null,
        compareTarget: 'left', compareInitialized: false,
        comparePanes: {
            left: {entry: null, sequence: 0, pending: false, error: ''},
            right: {entry: null, sequence: 0, pending: false, error: ''},
        },
        versionManifest: null, versionLoadSequence: 0, versionDetails: new Map(),
        versionLoadState: 'idle', versionRestoreBusy: false,
        layoutPreviewObserver: null, layoutPreviewQueue: [], layoutPreviewInFlight: 0,
        layoutPreviewCache: new Map(), layoutPreviewGeneration: 0, layoutPreviewResizeObservers: new Map(),
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
        if(state.statusTimer)clearTimeout(state.statusTimer);
        state.status = {zh, en, kind, retry};
        renderStatus();
        if(kind==='success'){
            const current=state.status;
            state.statusTimer=setTimeout(()=>{if(state.status===current){state.status=null;renderStatus();}},3500);
        }
    }

    function clearStatus(){
        if(state.statusTimer)clearTimeout(state.statusTimer);
        state.statusTimer=0;
        state.status=null;
        renderStatus();
    }

    function clearLoadingStatus(){
        if(state.status?.kind!=='loading')return;
        if(state.statusTimer)clearTimeout(state.statusTimer);
        state.statusTimer=0;
        state.status=null;
        renderStatus();
    }

    function setActionFeedback(id, zh='', en='', kind=''){
        if(state.actionFeedbackTimers[id])clearTimeout(state.actionFeedbackTimers[id]);
        state.actionFeedback[id]=zh||en?{zh,en,kind}:null;
        renderActionFeedback(id);
        if((zh||en)&&kind==='success'){
            const current=state.actionFeedback[id];
            state.actionFeedbackTimers[id]=setTimeout(()=>{if(state.actionFeedback[id]===current){state.actionFeedback[id]=null;renderActionFeedback(id);}},3500);
        }
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

    function isLayoutHistoryView(){return state.bodyView==='preview'||state.bodyView==='compare';}

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
        // `valid` means the saved HTML belongs to this theme and passed its digest/safety checks.
        // The composite source hash is provenance only; title and Markdown have independent histories.
        const current=variant.valid===true;
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
        return `${themeId}:${variant.html_sha256||variant.body_html}`;
    }

    function currentTitle(){
        const article=state.article;
        if(!article) return null;
        const variant=article.title_variants?.[state.selectedTitleVariantId];
        // 标题是用户可主动复用的历史内容；与当前原文不匹配只表示来源不同，不应禁用历史标题。
        if(variant && variant.valid===true && typeof variant.title==='string' && variant.title.trim()) return variant.title.trim();
        return typeof article.title==='string'?article.title.trim():'';
    }

    function titleChoiceEntries(article){
        const entries=article?.title_variants&&typeof article.title_variants==='object'?Object.entries(article.title_variants):[];
        const groups=new Map();
        for(const [id,item] of entries){
            if(item?.valid!==true||typeof item.title!=='string'||!item.title.trim())continue;
            const title=item.title.trim();
            if(!groups.has(title))groups.set(title,[]);
            groups.get(title).push({id,item,title,ready:true});
        }
        const representatives=new Map();
        for(const [title,group] of groups){
            const selected=group.find(entry=>String(entry.id)===String(state.selectedTitleVariantId));
            const current=group.find(({item})=>item.source_matches===true||(
                item.source_matches!==false&&typeof item.source_sha256==='string'&&item.source_sha256===article?.source_sha256
            ));
            representatives.set(title,selected||current||group[0]);
        }
        const emitted=new Set();
        const choices=[];
        for(const [id,item] of entries){
            const ready=item?.valid===true&&typeof item.title==='string'&&!!item.title.trim();
            if(!ready){
                // Each invalid record remains independently visible; the localized “Unavailable” label is not a dedupe key.
                choices.push({id,item,ready:false,title:L('不可用','Unavailable')});
                continue;
            }
            const title=item.title.trim();
            if(emitted.has(title))continue;
            emitted.add(title);
            choices.push(representatives.get(title));
        }
        return choices;
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

    function versionsFor(kind){
        const stream=state.versionManifest?.streams?.find(item=>item?.kind===kind);
        return Array.isArray(stream?.versions)?stream.versions:[];
    }

    function historyVersionsFor(kind){
        const entries=versionsFor(kind);
        if(kind!=='title')return entries;
        const output=[],indices=new Map();
        entries.forEach(item=>{
            const title=String(item?.label||'').trim();
            if(!title){output.push(item);return;}
            const existingIndex=indices.get(title);
            if(existingIndex===undefined){indices.set(title,output.length);output.push(item);return;}
            if(item?.active===true&&output[existingIndex]?.active!==true)output[existingIndex]=item;
        });
        return output;
    }

    function versionIsActive(kind,item){
        if(kind==='body')return typeof item?.layout_active==='boolean'?item.layout_active:item?.active===true;
        return item?.active===true;
    }

    function activeVersion(kind){return versionsFor(kind).find(item=>versionIsActive(kind,item))||null;}

    function versionNumberLabel(item){
        const number=Number(item?.number);
        return Number.isFinite(number)&&number>0?`V${number}`:L('版本','Version');
    }

    function versionDateLabel(item){
        const value=Number(item?.created_at);
        if(!Number.isFinite(value)||value<=0)return L('既有记录 · 时间未知','Legacy entry · time unknown');
        try{return new Intl.DateTimeFormat(isEnglish()?'en':'zh-TW',{year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));}
        catch(e){return L('已保存','Saved');}
    }

    function versionUnavailable(item){
        const value=item?.availability;
        return value===false||value==='unavailable'||value?.available===false||value?.status==='unavailable';
    }

    function versionRestoreUnavailable(kind,item){
        if(kind==='body'){
            return item?.layout_available!==true||!String(item?.preview_theme_id||'').trim();
        }
        if(kind==='cover'){
            const media=item?.public_media;
            return media?.available!==true||!sameOriginUrl(media?.url)||!/^image\//i.test(String(media?.mime||''));
        }
        return versionUnavailable(item);
    }

    function setHistoryPreviewCache(key,value){
        state.layoutPreviewCache.delete(key);
        state.layoutPreviewCache.set(key,value);
        while(state.layoutPreviewCache.size>5)state.layoutPreviewCache.delete(state.layoutPreviewCache.keys().next().value);
    }

    function invalidateHistoryLayoutPreviews(){
        state.layoutPreviewGeneration++;
        state.layoutPreviewQueue=[];
        state.layoutPreviewCache.clear();
        state.layoutPreviewObserver?.disconnect();
        state.layoutPreviewObserver=null;
        state.layoutPreviewResizeObservers.forEach(observer=>observer.disconnect());
        state.layoutPreviewResizeObservers.clear();
    }

    function fitHistoryLayoutFrame(card){
        const frame=card?.querySelector('[data-history-layout-frame]');
        const wrapper=frame?.parentElement;
        if(!frame||!wrapper)return;
        const width=wrapper.clientWidth||wrapper.getBoundingClientRect().width;
        const height=wrapper.clientHeight||wrapper.getBoundingClientRect().height;
        if(width<1||height<1)return;
        const virtualWidth=360;
        const scale=Math.min(1,width/virtualWidth);
        frame.style.width=`${virtualWidth}px`;
        frame.style.height=`${Math.max(1,height/scale)}px`;
        frame.style.transform=`scale(${scale})`;
        frame.style.transformOrigin='top left';
    }

    function renderLayoutPreview(card,cached){
        if(!card?.isConnected)return;
        const frame=card.querySelector('[data-history-layout-frame]');
        const placeholder=card.querySelector('[data-history-layout-excerpt]');
        const failure=card.querySelector('[data-history-layout-failure]');
        if(!frame||!cached?.document)return;
        fitHistoryLayoutFrame(card);
        if(typeof ResizeObserver!=='undefined'&&!state.layoutPreviewResizeObservers.has(card)){
            const observer=new ResizeObserver(()=>fitHistoryLayoutFrame(card));
            observer.observe(frame.parentElement);
            state.layoutPreviewResizeObservers.set(card,observer);
        }
        frame.onload=()=>{
            try{
                const documentBody=frame.contentDocument?.body;
                if(!documentBody||(!documentBody.textContent.trim()&&!documentBody.querySelector('img,svg,table,hr'))){
                    throw new Error('empty history preview');
                }
                card.dataset.previewState='ready';
                if(placeholder)placeholder.hidden=true;
                if(failure)failure.hidden=true;
            }catch(error){
                frame.hidden=true;
                card.dataset.previewState='error';
                if(failure){failure.hidden=false;failure.textContent=L('缩略预览暂不可用，点击此卡片仍可恢复该版本。','Thumbnail unavailable. Click this card to restore the saved version.');}
            }
        };
        frame.srcdoc=cached.document;
        frame.hidden=false;
    }

    function pumpLayoutPreviewQueue(){
        while(state.layoutPreviewInFlight<2&&state.layoutPreviewQueue.length){
            const job=state.layoutPreviewQueue.shift();
            if(!job.card?.isConnected||job.generation!==state.layoutPreviewGeneration||job.revision!==state.revision||!isLayoutHistoryView())continue;
            state.layoutPreviewInFlight++;
            (async()=>{
                const data=await api(`/api/studio/articles/${encodeURIComponent(articleId)}/versions/body/${encodeURIComponent(job.id)}`);
                if(data?.project_id!==articleId||data?.kind!=='body'||String(data?.id)!==job.id||Number(data?.current_revision)!==job.revision||!data?.snapshot||typeof data.snapshot!=='object'){
                    throw new Error('invalid history preview response');
                }
                const layout=(Array.isArray(data.snapshot.layouts)?data.snapshot.layouts:[]).find(item=>String(item?.theme_id||'')===job.themeId);
                if(layout?.available!==true||typeof layout.body_html!=='string'||!layout.body_html.trim())throw new Error('history layout unavailable');
                const safeHtml=validateArticleHtml(layout.body_html);
                return {document:previewDocument(safeHtml,{thumbnail:true})};
            })().then(cached=>{
                if(job.generation!==state.layoutPreviewGeneration||job.revision!==state.revision)return;
                setHistoryPreviewCache(job.key,cached);
                if(job.card.isConnected)renderLayoutPreview(job.card,cached);
            }).catch(error=>{
                if(job.generation!==state.layoutPreviewGeneration||job.revision!==state.revision||!job.card.isConnected)return;
                job.card.dataset.previewState='error';
                const failure=job.card.querySelector('[data-history-layout-failure]');
                if(failure){failure.hidden=false;failure.textContent=L('缩略预览读取失败；点击此卡片可直接恢复，或刷新文章后重试。','Could not load the preview. Click the card to restore, or reload the article and try again.');}
            }).finally(()=>{
                state.layoutPreviewInFlight=Math.max(0,state.layoutPreviewInFlight-1);
                pumpLayoutPreviewQueue();
            });
        }
    }

    function scheduleLayoutPreview(card){
        if(!card||!isLayoutHistoryView()||card.dataset.previewState==='loading'||card.dataset.previewState==='ready')return;
        const id=String(card.dataset.layoutPreviewVersion||'');
        const themeId=String(card.dataset.layoutPreviewTheme||'');
        if(!id||!themeId)return;
        const revision=Number(state.versionManifest?.revision);
        if(!Number.isFinite(revision)||revision!==Number(state.revision))return;
        const key=`${revision}:${id}:${themeId}`;
        const cached=state.layoutPreviewCache.get(key);
        if(cached){renderLayoutPreview(card,cached);return;}
        if(state.layoutPreviewQueue.some(job=>job.key===key)||card.dataset.previewState==='queued')return;
        card.dataset.previewState='queued';
        state.layoutPreviewQueue.push({card,id,themeId,key,revision,generation:state.layoutPreviewGeneration});
        pumpLayoutPreviewQueue();
    }

    function observeLayoutPreviews(root){
        state.layoutPreviewObserver?.disconnect();
        state.layoutPreviewObserver=null;
        for(const [card,observer] of state.layoutPreviewResizeObservers){
            if(!card.isConnected){observer.disconnect();state.layoutPreviewResizeObservers.delete(card);}
        }
        if(!isLayoutHistoryView()||!$('#articleBodyHistoryDetails')?.open||!root)return;
        if(typeof IntersectionObserver==='undefined'){
            root.querySelectorAll('[data-layout-preview-version]').forEach(scheduleLayoutPreview);
            return;
        }
        state.layoutPreviewObserver=new IntersectionObserver(entries=>{
            entries.forEach(entry=>{
                if(!entry.isIntersecting)return;
                state.layoutPreviewObserver?.unobserve(entry.target);
                scheduleLayoutPreview(entry.target);
            });
        },{root,rootMargin:'80px 0px',threshold:0.01});
        root.querySelectorAll('[data-layout-preview-version]').forEach(card=>{
            const cached=state.layoutPreviewCache.get(`${state.revision}:${card.dataset.layoutPreviewVersion}:${card.dataset.layoutPreviewTheme}`);
            if(cached)renderLayoutPreview(card,cached);
            else state.layoutPreviewObserver.observe(card);
        });
    }

    function versionHistoryRow(kind,item){
        const id=String(item?.id||'');
        const number=versionNumberLabel(item);
        const rawLabel=String(item?.label||'').trim();
        const label=kind==='title'?rawLabel:'';
        const active=versionIsActive(kind,item);
        const unavailable=versionRestoreUnavailable(kind,item);
        const details=[number,versionDateLabel(item)];
        if(label&&label!==number)details.unshift(label);
        let heading=details.join(' · '),preview='';
        if(kind==='body'){
            const themeId=String(item?.preview_theme_id||'');
            const excerpt=String(item?.layout_excerpt||'');
            heading=`${themeLabel(themeId)} · ${number} · ${versionDateLabel(item)}`;
            preview=`<div class="article-history-layout-preview" data-layout-preview-version="${escapeHtml(id)}" data-layout-preview-theme="${escapeHtml(themeId)}" data-preview-state="idle" aria-hidden="true"><p data-history-layout-excerpt>${escapeHtml(excerpt||L('正在载入排版预览…','Loading layout preview…'))}</p><iframe data-history-layout-frame title="" tabindex="-1" aria-hidden="true" inert sandbox="allow-same-origin" loading="lazy" hidden></iframe><small data-history-layout-failure hidden></small></div>`;
        }
        const media=item?.public_media;
        if(kind==='cover'&&media?.available===true&&sameOriginUrl(media.url)&&/^image\//i.test(String(media.mime||''))){
            preview=`<img class="article-history-cover-thumb" src="${escapeHtml(sameOriginUrl(media.url))}" alt="" aria-hidden="true" loading="lazy" draggable="false">`;
        }
        const currentLabel=active?L('当前版本','Current version'):'';
        const visibleLabel=kind==='title'&&label?label:heading;
        const compareSelection=kind==='body'&&state.bodyView==='compare';
        const actionVerb=kind==='body'?(compareSelection?L(`载入到${state.compareTarget==='left'?'左栏':'右栏'}`,`Load into ${state.compareTarget} pane`):L('恢复此排版','Restore this layout')):kind==='title'?L('恢复此标题','Restore this title'):L('采用此封面','Use this cover');
        const ariaLabel=compareSelection?`${actionVerb} · ${visibleLabel}`:active?`${L('当前版本','Current version')} · ${visibleLabel}`:`${actionVerb} · ${visibleLabel}`;
        const unavailableText=unavailable?`<small class="article-version-unavailable">${escapeHtml(L('内容暂不可用','Content unavailable'))}</small>`:'';
        const pressed=active?'true':'false';
        const disabled=unavailable||state.versionRestoreBusy||(!compareSelection&&(active||state.pendingSaves>0));
        const button=`<button class="article-version-card-action" type="button" data-restore-kind="${escapeHtml(kind)}" data-version-id="${escapeHtml(id)}" aria-label="${escapeHtml(ariaLabel)}" aria-pressed="${pressed}" ${active?'aria-current="true"':''} ${state.versionRestoreBusy?'aria-busy="true"':''} ${disabled?'disabled':''}></button>`;
        const titleMeta=kind==='title'?`<small class="article-version-title-meta">${escapeHtml(`${number} · ${versionDateLabel(item)}`)}</small>`:'';
        return `<article class="article-version-row article-version-card" data-version-kind="${escapeHtml(kind)}" data-version-id="${escapeHtml(id)}" data-active="${active?'true':'false'}"><div class="article-version-row-copy"><strong>${escapeHtml(visibleLabel)}</strong>${titleMeta}${currentLabel?`<small class="article-version-current-mark">${escapeHtml(currentLabel)}</small>`:''}${unavailableText}</div>${preview}${button}</article>`;
    }

    function syncVersionRestoreButtons(){
        document.querySelectorAll('button[data-restore-kind][data-version-id]').forEach(button=>{
            const kind=button.dataset.restoreKind;
            const item=versionsFor(kind).find(entry=>String(entry.id)===String(button.dataset.versionId));
            const unavailable=versionRestoreUnavailable(kind,item);
            const active=versionIsActive(kind,item);
            const compareSelection=kind==='body'&&state.bodyView==='compare';
            button.disabled=state.versionRestoreBusy||unavailable||(!compareSelection&&(state.pendingSaves>0||active));
            button.setAttribute('aria-pressed',active?'true':'false');
            if(compareSelection){
                const label=`${versionNumberLabel(item)} · ${themeLabel(item?.preview_theme_id||'')}`;
                button.setAttribute('aria-label',`${L(`载入到${state.compareTarget==='left'?'左栏':'右栏'}`,`Load into ${state.compareTarget} pane`)} · ${label}`);
            }
            if(active)button.setAttribute('aria-current','true');else button.removeAttribute('aria-current');
            if(state.versionRestoreBusy)button.setAttribute('aria-busy','true');else button.removeAttribute('aria-busy');
        });
    }

    function renderVersionLists(){
        const titleCurrent=$('#articleTitleVersionCurrent');
        const titleMeta=$('#articleTitleVersionCurrentMeta');
        const coverMeta=$('#articleCoverVersionCurrentMeta');
        const bodyCurrent=$('#articleBodyVersionCurrent');
        const titleHistory=$('#articleTitleHistory');
        const coverHistory=$('#articleCoverHistory');
        const bodyHistory=$('#articleBodyHistory');
        const titleCount=$('#articleTitleHistoryCount');
        const coverCount=$('#articleCoverHistoryCount');
        const bodyCount=$('#articleBodyHistoryCount');
        const streamsReady=state.versionLoadState==='ready';
        const loadingText=L('正在读取版本…','Loading versions…');
        const failureText=L('版本读取失败。','Could not load versions.');
        const titleActive=activeVersion('title');
        const coverActive=activeVersion('cover');
        const bodyActive=activeVersion('body');
        if(titleCurrent)titleCurrent.textContent=currentTitle()||L('暂无标题','No title');
        if(titleMeta)titleMeta.textContent=titleActive?`${L('当前','Current')} · ${versionNumberLabel(titleActive)}`:L('当前标题','Current title');
        if(coverMeta)coverMeta.textContent=coverActive?`${L('当前','Current')} · ${versionNumberLabel(coverActive)}`:L('当前封面','Current cover');
        if(bodyCurrent)bodyCurrent.textContent=bodyActive?`${versionNumberLabel(bodyActive)} · ${L('正文排版','Body layout')}`:L('当前正文','Current body');
        const setCount=(node,items)=>{if(node)node.textContent=streamsReady&&items.length?String(items.length):'';};
        const renderList=(node,kind)=>{
            if(!node)return;
            if(state.versionLoadState==='loading'||state.versionLoadState==='idle'){
                node.innerHTML=`<p class="article-version-empty">${escapeHtml(loadingText)}</p>`;return;
            }
            if(state.versionLoadState==='error'){
                node.innerHTML=`<div class="article-version-empty">${escapeHtml(failureText)} <button class="article-inline-retry" type="button" data-retry-versions>${escapeHtml(L('重试','Retry'))}</button></div>`;return;
            }
            const entries=historyVersionsFor(kind);
            if(!entries.length){node.innerHTML=`<p class="article-version-empty">${escapeHtml(L('暂无保存的版本。','No saved versions yet.'))}</p>`;return;}
            node.innerHTML=entries.map(item=>versionHistoryRow(kind,item)).join('');
        };
        const titleItems=historyVersionsFor('title'),coverItems=versionsFor('cover'),bodyItems=versionsFor('body');
        setCount(titleCount,titleItems);setCount(coverCount,coverItems);setCount(bodyCount,bodyItems);
        renderList(titleHistory,'title');
        renderList(coverHistory,'cover');
        renderList(bodyHistory,'body');
        observeLayoutPreviews(bodyHistory);
        syncVersionRestoreButtons();
        const titleHeading=$('#articleTitleHistoryHeading');
        if(titleHeading)titleHeading.textContent=L('标题历史','Title history');
        const bodyHeading=$('#articleBodyHistoryHeading');
        if(bodyHeading)bodyHeading.textContent=L('正文历史','Body history');
        const coverHeading=$('#articleCoverSectionHeading');
        if(coverHeading)coverHeading.textContent=L('封面历史','Cover history');
    }

    async function loadVersionManifest(){
        if(!articleId||!state.article)return false;
        const sequence=++state.versionLoadSequence;
        const expectedRevision=state.revision;
        state.versionLoadState='loading';
        renderVersionLists();
        try{
            const data=await api(`/api/studio/articles/${encodeURIComponent(articleId)}/versions`);
            if(sequence!==state.versionLoadSequence)return false;
            if(data?.project_id!==articleId||!Array.isArray(data?.streams))throw new Error('invalid version manifest');
            if(Number(data.revision)!==Number(state.revision)||Number(data.revision)!==Number(expectedRevision)){
                state.versionLoadState='error';
                renderVersionLists();
                return false;
            }
            const allowed=['title','cover','body'];
            if(data.streams.length!==allowed.length||data.streams.some((stream,index)=>stream?.kind!==allowed[index])||
                data.streams.some(stream=>!Array.isArray(stream?.versions)))throw new Error('invalid version stream');
            state.versionManifest=data;
            state.versionLoadState='ready';
            renderVersionLists();
            return true;
        }catch(error){
            if(sequence!==state.versionLoadSequence)return false;
            state.versionLoadState='error';
            renderVersionLists();
            return false;
        }
    }

    async function readVersionDetail(kind,id){
        const key=`${kind}:${id}`;
        if(state.versionDetails.has(key))return state.versionDetails.get(key);
        const data=await api(`/api/studio/articles/${encodeURIComponent(articleId)}/versions/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`);
        if(data?.project_id!==articleId||data?.kind!==kind||String(data?.id)!==String(id)||!data?.snapshot||typeof data.snapshot!=='object'){
            throw new Error(L('版本详情无法读取。','Version details could not be loaded.'));
        }
        if(Number.isFinite(Number(data.current_revision))&&Number(data.current_revision)!==Number(state.revision)){
            const error=new Error(L('文章版本已更新，正在读取当前状态。','The article changed while loading this version. Reloading current state.'));
            error.code='article-version-stale';
            throw error;
        }
        state.versionDetails.set(key,data);
        return data;
    }

    function makeCurrentCompareEntry(){
        const selected=selectedVariant();
        if(!selected?.current||!selected.previewable||!state.selectedThemeId)return null;
        const html=String(selected.variant.body_html||'');
        const hash=String(selected.variant.html_sha256||'');
        return {id:'',number:null,themeId:state.selectedThemeId,html,htmlHash:hash,key:`current:${state.selectedThemeId}:${hash||html}`};
    }

    function ensureCompareInitialized(){
        if(state.compareInitialized)return;
        state.compareInitialized=true;
        state.comparePanes.left.entry=makeCurrentCompareEntry();
    }

    function renderComparePane(lane){
        const pane=state.comparePanes[lane];
        const root=$(`[data-compare-lane="${lane}"]`);
        const frame=$(`#articleCompare${lane==='left'?'Left':'Right'}Frame`);
        const empty=$(`[data-compare-empty="${lane}"]`);
        const status=$(`[data-compare-status="${lane}"]`);
        const label=root?.querySelector('[data-compare-version-label]');
        if(!pane||!root||!frame||!empty||!status)return;
        const entry=pane.entry;
        if(label)label.textContent=entry
            ?(entry.number?`${versionNumberLabel({number:entry.number})} · ${themeLabel(entry.themeId)}`:`${L('当前排版','Current layout')} · ${themeLabel(entry.themeId)}`)
            :lane==='right'?L('选择一个历史正文','Choose a saved body version'):L('当前排版不可用','Current layout unavailable');
        root.classList.toggle('is-target',state.compareTarget===lane);
        root.querySelector('[data-compare-select]')?.setAttribute('aria-pressed',state.compareTarget===lane?'true':'false');
        root.setAttribute('aria-label',lane==='left'?L('左栏正文对比','Left comparison pane'):L('右栏正文对比','Right comparison pane'));
        const showEmpty=!entry&&!pane.pending;
        empty.hidden=!showEmpty;
        if(showEmpty)empty.textContent=lane==='right'
            ?L('先选择右栏，再点击左侧正文历史。','Select the right pane, then click a body-history card.')
            :L('当前没有可读取的正文排版。','The current saved layout is unavailable.');
        if(entry){
            frame.hidden=false;
            if(frame.dataset.compareKey!==entry.key){
                frame.dataset.compareKey=entry.key;
                frame.dataset.compareLoadedKey='';
                frame.title=lane==='left'?L('左栏正文对比预览','Left article comparison preview'):L('右栏正文对比预览','Right article comparison preview');
                try{frame.srcdoc=previewDocument(entry.html);}catch(error){
                    pane.error=L('此排版无法安全预览。','This layout cannot be previewed safely.');
                    frame.hidden=true;
                }
            }
        }else{
            frame.hidden=true;
            if(!pane.pending){frame.removeAttribute('srcdoc');frame.dataset.compareKey='';frame.dataset.compareLoadedKey='';}
        }
        status.hidden=!pane.pending&&!pane.error;
        status.dataset.state=pane.error?'error':pane.pending?'pending':'';
        status.textContent=pane.error||(pane.pending?L('正在读取历史排版…','Loading saved layout…'):'');
        root.querySelector(`[data-compare-content="${lane}"]`)?.setAttribute('aria-busy',pane.pending?'true':'false');
    }

    function renderComparePanel(){
        renderComparePane('left');
        renderComparePane('right');
        const hint=$('#articleCompareActionHint');
        if(hint)hint.textContent=L('正文对比为只读视图。切回排版预览后可复制或导出正文。','Body comparison is read-only. Return to layout preview to copy or export the article.');
    }

    function selectCompareTarget(lane){
        if(!['left','right'].includes(lane))return;
        state.compareTarget=lane;
        renderComparePanel();
        syncVersionRestoreButtons();
    }

    async function compareBodyVersion(id){
        const lane=state.compareTarget;
        const pane=state.comparePanes[lane];
        const preferred=String(state.selectedThemeId||'');
        const sequence=++pane.sequence;
        pane.pending=true;
        pane.error='';
        renderComparePane(lane);
        try{
            // Comparison reads immutable history directly and is not gated by the article's later revision.
            const detail=await api(`/api/studio/articles/${encodeURIComponent(articleId)}/versions/body/${encodeURIComponent(id)}`);
            if(sequence!==pane.sequence)return;
            if(detail?.project_id!==articleId||detail?.kind!=='body'||String(detail?.id)!==String(id)||!detail?.snapshot||typeof detail.snapshot!=='object'){
                throw new Error(L('正文历史详情无法确认。','The saved body details could not be verified.'));
            }
            const layouts=Array.isArray(detail.snapshot.layouts)?detail.snapshot.layouts:[];
            const ordered=[...layouts].sort((a,b)=>Number(String(b?.theme_id||'')===preferred)-Number(String(a?.theme_id||'')===preferred));
            let picked=null;
            for(const layout of ordered){
                if(layout?.available!==true||typeof layout.body_html!=='string'||!layout.body_html.trim())continue;
                const digest=String(layout.html_sha256||'').toLowerCase();
                if(!/^[a-f0-9]{64}$/.test(digest))continue;
                const actual=await sha256Hex(layout.body_html);
                if(sequence!==pane.sequence)return;
                if(actual!==digest)continue;
                try{
                    const safeHtml=validateArticleHtml(layout.body_html);
                    picked={themeId:String(layout.theme_id||''),html:safeHtml,htmlHash:digest};
                    break;
                }catch(error){}
            }
            if(sequence!==pane.sequence)return;
            if(!picked)throw new Error(L('此正文历史没有通过完整性检查的排版。','This body version has no layout that passed integrity checks.'));
            pane.entry={id:String(id),number:detail.number,themeId:picked.themeId,html:picked.html,htmlHash:picked.htmlHash,key:`history:${id}:${picked.themeId}:${picked.htmlHash}`};
            pane.error='';
        }catch(error){
            if(sequence!==pane.sequence)return;
            pane.error=error?.message||L('历史排版读取失败，请重试。','Could not load the saved layout. Try again.');
        }finally{
            if(sequence===pane.sequence){pane.pending=false;renderComparePane(lane);}
        }
    }

    async function sha256Hex(value){
        if(!window.crypto?.subtle)throw new Error(L('当前环境无法校验正文摘要。','This browser cannot verify the saved layout digest.'));
        const digest=await window.crypto.subtle.digest('SHA-256',new TextEncoder().encode(String(value)));
        return [...new Uint8Array(digest)].map(byte=>byte.toString(16).padStart(2,'0')).join('');
    }

    async function viewCoverVersion(id,opener){
        try{
            const detail=await readVersionDetail('cover',id);
            const media=detail.snapshot?.public_media;
            const url=media?.available===true?sameOriginUrl(media.url):'';
            if(!url||!/^image\//i.test(String(media?.mime||'')))throw new Error(L('这张封面暂不可预览。','This cover cannot be previewed.'));
            openCoverLightbox({id:detail.snapshot.cover_variant_id||id,url,name:media.name||'',mime:media.mime,valid:true},opener);
        }catch(error){
            if(error?.code==='article-version-stale')void loadArticle({background:true,allowPending:true});
            setStatus(error?.message||L('封面历史暂不可读取。','This cover history is unavailable.'),error?.message||'This cover history is unavailable.','error');
        }
    }

    async function restoreArticleVersion(kind,id){
        if(!['title','cover','body'].includes(kind)||!id||!state.article||state.versionRestoreBusy||state.pendingSaves)return;
        const restoreBodyView=kind==='body'?'preview':'';
        const item=versionsFor(kind).find(entry=>String(entry.id)===String(id));
        if(versionIsActive(kind,item)||versionRestoreUnavailable(kind,item))return;
        invalidateHistoryLayoutPreviews();
        state.versionRestoreBusy=true;
        syncVersionRestoreButtons();
        const button=document.querySelector(`[data-restore-kind="${CSS.escape(kind)}"][data-version-id="${CSS.escape(String(id))}"]`);
        button?.setAttribute('aria-busy','true');
        try{
            const restoreBody={expected_revision:state.revision};
            if(kind==='body')restoreBody.body_view=restoreBodyView;
            const response=await api(`/api/studio/articles/${encodeURIComponent(articleId)}/versions/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/restore`,{
                method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(restoreBody),
            });
            const article=response?.article;
            if(!article||article.project_id!==articleId||!Number.isFinite(Number(article.revision))||response?.restored?.kind!==kind||String(response?.restored?.id)!==String(id)||(kind==='body'&&response?.restored?.body_view!==restoreBodyView)){
                throw new Error(L('版本采用响应无法确认，请重新读取。','The version response could not be confirmed. Reload to check.'));
            }
            state.versionDetails.clear();
            state.versionManifest=null;
            invalidateHistoryLayoutPreviews();
            state.article=article;state.revision=Number(article.revision);
            state.selectedThemeId=article.selected_theme_id||state.selectedThemeId;
            state.selectedTitleVariantId=article.selected_title_variant_id||'';
            state.selectedCoverVariantId=article.selected_cover_variant_id||'';
            if(kind==='body'){
                state.bodyView=restoreBodyView;
                setArticleBodyView(restoreBodyView,false);
            }
            state.versionLoadState='loading';
            setActionFeedback('articleVersionPreviewFeedback');
            renderArticle();
            clearStatus();
            await loadVersionManifest();
        }catch(error){
            if(error?.status===409){
                await loadArticle({background:true,allowPending:true});
                const zh='文章已更新，未采用此历史版本。请检查当前内容后再选择。';
                const en='The article changed, so this history entry was not applied. Review the current content before selecting again.';
                setActionFeedback('articleVersionPreviewFeedback',zh,en,'error');
                setStatus(zh,en,'error');
            }else{
                const message=error?.message||L('版本采用失败；当前内容未更改。','Could not apply the saved version. The current article was not changed.');
                setActionFeedback('articleVersionPreviewFeedback',message,message,'error');
                setStatus(message,message,'error');
            }
        }finally{
            state.versionRestoreBusy=false;
            renderArticle();
        }
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

    function previewDocument(bodyHtml,options={}){
        const content = validateArticleHtml(bodyHtml);
        const baseAppearance = document.documentElement.dataset.studioAppearance === 'dark' ? 'dark' : 'light';
        const thumbnail=options.thumbnail===true;
        return `<!doctype html><html lang="${isEnglish()?'en':'zh-CN'}" data-appearance="${baseAppearance}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
            *{box-sizing:border-box}html,body{margin:0;min-height:100%;background:#fff;color:#28252a;font:16px/1.8 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}body{padding:${thumbnail?'8px':'clamp(22px,5vw,68px)'}}#articlePreviewContent{max-width:${thumbnail?'340px':'760px'};margin:0 auto;overflow-wrap:anywhere}img{max-width:100%;height:auto}pre{max-width:100%;overflow:auto;padding:${thumbnail?'7px':'14px'};background:#f4f1ed;border-radius:8px;white-space:pre-wrap}code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}table{max-width:100%;border-collapse:collapse}blockquote{margin-inline:0;padding-inline:16px;border-inline-start:3px solid #c8bdd3;color:#595260}${thumbnail?'html,body{font-size:14px;line-height:1.4}h1{font-size:19px!important;margin-block:0 6px!important}h2{font-size:16px!important;margin-block:0 5px!important}p{margin-block:0 5px!important}ul,ol{margin-block:3px!important;padding-inline-start:20px!important}#articlePreviewContent>*:first-child{margin-top:0!important}':''}
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
            const usable=variant?.valid===true&&typeof variant?.body_html==='string'&&!!variant.body_html.trim();
            const current=String(state.selectedThemeId)===String(id)&&usable;
            const status=current?L('当前排版','Current layout'):usable?L('已保存排版','Saved layout'):L('无法预览','Unavailable');
            return `<button class="article-theme-choice" type="button" data-theme-id="${escapeHtml(id)}" data-ready="${usable?'true':'false'}" aria-pressed="${state.selectedThemeId===id?'true':'false'}" style="--article-theme-color:${escapeHtml(themeColor(id))}"><span class="article-theme-choice-swatch" aria-hidden="true"></span><span class="article-theme-choice-copy"><strong>${escapeHtml(themeLabel(id))}</strong><small>${escapeHtml(status)}</small></span><span class="article-theme-choice-state">${state.selectedThemeId===id?escapeHtml(L('已选','Selected')):''}</span></button>`;
        }).join('');
    }

    function renderArticle(){
        const article=state.article;
        const title=$('#articleTitle');
        const compareTab=$('#articleCompareTab');
        const selectedTitle=$('#articleSelectedTitle');
        const themeNameNode=$('#articlePreviewThemeName');
        const meta=$('#articlePreviewMeta');
        const badge=$('#articlePreviewBadge');
        const historyNote=$('#articlePreviewHistoryNote');
        const frame=$('#articlePreviewFrame');
        const empty=$('#articlePreviewEmpty');
        const copyButton=$('#articleCopyButton');
        const exportButton=$('#articleExportButton');
        const selected=selectedVariant();
        const variant=selected?.variant||null;
        const html=variant?.body_html||'';
        if(title)title.textContent=L('公众号文章','WeChat articles');
        if(compareTab)compareTab.disabled=!article;
        document.title=L('公众号文章','WeChat articles');
        const titleText=currentTitle();
        const titleCopy=$('#articleCopyTitleButton');
        const titleChoices=$('#articleTitleChoices');
        const titleVariants=titleChoiceEntries(article);
        if(selectedTitle)selectedTitle.textContent=titleText||L('暂无标题','No title');
        const titleSummary=$('#articleTitleSummaryValue');
        if(titleSummary)titleSummary.textContent=titleText||L('暂无标题','No title');
        if(titleCopy)titleCopy.disabled=!titleText||state.busyActions.has('copy-title');
        if(titleChoices)titleChoices.innerHTML=titleVariants.map(({id,item,ready,title})=>{
            const sourceNote=ready&&item.source_matches===false?L('历史标题','Historical title'):'';
            return `<button class="article-title-choice" type="button" data-title-variant-id="${escapeHtml(id)}" aria-pressed="${state.selectedTitleVariantId===id?'true':'false'}" ${ready?'':'disabled'}><span>${escapeHtml(title)}</span>${sourceNote?`<small>${escapeHtml(sourceNote)}</small>`:''}</button>`;
        }).join('');
        const titlePickerSummary=$('.article-current-title-summary');
        if(titlePickerSummary)titlePickerSummary.setAttribute('aria-label',titleText?L(`当前标题：${titleText}。展开选择标题版本。`,`Current title: ${titleText}. Expand to choose a title version.`):L('暂无标题。展开选择标题版本。','No title is selected. Expand to choose a title version.'));
        renderCoverHistory();
        if(themeNameNode)themeNameNode.textContent=state.selectedThemeId?themeLabel(state.selectedThemeId):'—';
        if(meta)meta.textContent=article?`${L(`文章修订 ${article.revision}`,`Article revision ${article.revision}`)}${selected?.previewable&&!selected.current?` · ${L('排版未通过校验','Layout integrity check failed')}`:''}`:'';
        const previewable=!!selected?.previewable;
        if(badge){badge.textContent=selected?.previewable?(selected.current?L('当前排版','Current layout'):L('已保存排版','Saved layout')):L('尚无可用排版','No available layout');badge.dataset.ready=selected?.current&&selected.previewable?'true':'false';}
        if(historyNote){
            historyNote.hidden=!(selected?.previewable&&!selected.current);
            historyNote.textContent=L('此排版未通过完整性校验；可以查看，但不能复制或导出。请重新读取或选择其他已保存排版。','This layout did not pass its integrity check. You can view it, but cannot copy or export it. Reload or choose another saved layout.');
        }
        const previewKey=selected?.previewable?articlePreviewKey(state.selectedThemeId,selected.variant):'';
        if(selected?.unsafe){const message=selected.error?.message||L('此排版无法安全预览。','This layout cannot be previewed safely.');setStatus(message,message,'error');}
        if(frame){
            if(variant&&html&&previewKey){
                if(previewKey!==state.lastPreviewKey){frame.dataset.previewKey=previewKey;frame.dataset.loadedPreviewKey='';frame.dataset.previewKind=selected.current?'current':'historical';frame.srcdoc=previewDocument(html);state.lastPreviewKey=previewKey;}
                frame.hidden=false;
            }else{frame.removeAttribute('srcdoc');frame.hidden=true;frame.dataset.previewKey='';frame.dataset.loadedPreviewKey='';frame.dataset.previewKind='';state.lastPreviewKey='';}
        }
        if(empty){
            empty.hidden=!!(previewable&&previewKey);
            empty.textContent=selected?.error?.message||(selected?.unsafe?L('此排版包含不安全内容，已停止预览。可重新读取文章以确认最新版本。','This layout contains unsafe content, so its preview is blocked. Reload the article to check its status.'):
                selected?L('当前主题的已保存排版不可读取。可重新读取文章以确认状态。','The saved layout for this theme is unavailable. Reload the article to check its status.'):
                !variantEntries().length?L('当前文章还没有已保存的正文排版。','This article has no saved body layout yet.'):
                L('当前主题没有可读取的已保存排版。','No readable saved layout is available for this theme.'));
        }
        const currentPreviewReady=!!(selected?.current&&selected.previewable&&previewKey&&frame?.dataset.loadedPreviewKey===previewKey);
        const anyPreviewReady=!!(previewable&&previewKey&&frame?.dataset.loadedPreviewKey===previewKey);
        const compareMode=state.bodyView==='compare';
        const bodyBusy=state.busyActions.has('copy-article')||state.busyActions.has('export-html');
        if(copyButton){
            copyButton.hidden=compareMode;
            copyButton.disabled=compareMode||!currentPreviewReady||bodyBusy;
            copyButton.title=compareMode?L('切回单篇正文视图后可复制','Return to a single article view to copy'):L('复制当前文章正文','Copy the current article');
            copyButton.setAttribute('aria-label',copyButton.title);
            copyButton.removeAttribute('aria-describedby');
        }
        if(exportButton){
            exportButton.hidden=compareMode;
            exportButton.disabled=compareMode||!currentPreviewReady||bodyBusy;
            exportButton.title=compareMode?L('切回单篇正文视图后可导出','Return to a single article view to export'):L('导出当前文章正文','Export the current article');
            exportButton.setAttribute('aria-label',exportButton.title);
            exportButton.removeAttribute('aria-describedby');
        }
        const fullPreviewButton=$('#articleFullPreviewButton');
        if(fullPreviewButton){fullPreviewButton.hidden=compareMode;fullPreviewButton.disabled=compareMode||!anyPreviewReady;fullPreviewButton.title=compareMode?L('对比视图不支持完整预览','Full preview is unavailable in comparison view'):L('完整预览','Full preview');}
        renderThemeChoices();
        renderVersionLists();
        renderComparePanel();
    }

    function renderCoverHistory(){
        const root=$('#articleCoverHistory');
        const copyButton=$('#articleCopyCoverButton');
        const downloadButton=$('#articleDownloadCoverButton');
        const covers=Array.isArray(state.article?.cover_variants)?state.article.cover_variants:[];
        const selected=currentCover();
        const currentPreview=$('#articleCurrentCoverPreview');
        const summaryImage=$('#articleCoverSummaryImage');
        const summaryEmpty=$('#articleCoverSummaryEmpty');
        const selectedIndex=selected?Math.max(0,covers.findIndex(cover=>String(cover.id)===String(selected.id))):-1;
        const selectedName=selected?coverDisplayName(selected,selectedIndex):'';
        if(currentPreview){
            currentPreview.hidden=!selected;
            currentPreview.dataset.coverPreviewId=selected?String(selected.id):'';
            currentPreview.title=selectedName?L(`放大预览：${selectedName}`,`Preview: ${selectedName}`):L('放大预览当前封面','Preview current cover');
            currentPreview.setAttribute('aria-label',currentPreview.title);
        }
        if(summaryImage){summaryImage.hidden=!selected;summaryImage.src=selected?.url||'';summaryImage.alt=selected?selectedName:'';}
        if(summaryEmpty){summaryEmpty.hidden=!!selected;summaryEmpty.textContent=L('暂未选择封面','No cover selected');}
        const active=activeVersion('cover');
        const coverMeta=$('#articleCoverVersionCurrentMeta');
        if(coverMeta)coverMeta.textContent=active?`${L('当前','Current')} · ${versionNumberLabel(active)}`:'';
        if(root&&state.versionLoadState==='ready'&&!versionsFor('cover').length)root.innerHTML=`<div class="article-version-empty">${escapeHtml(L('暂无保存的封面版本。','No saved cover versions yet.'))}</div>`;
        const coverBusy=state.busyActions.has('copy-cover')||state.busyActions.has('download-cover');
        if(copyButton)copyButton.disabled=!selected||coverBusy;
        if(downloadButton)downloadButton.disabled=!selected||coverBusy;
    }

    function openCoverLightbox(item,opener=null){
        const url=sameOriginUrl(item?.url);
        const dialog=$('#articleCoverLightbox');
        const image=$('#articleCoverLightboxImage');
        if(!dialog||!image||!url)return;
        state.coverPreviewOpener=opener||document.activeElement;
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
        if(!background)setStatus('正在读取文章…','Loading article…','loading');
        try{
            const data=await api(`/api/studio/articles/${encodeURIComponent(articleId)}`);
            if(sequence!==state.loadSequence)return false;
            const article=data?.article;
            if(!article||String(article.project_id)!==articleId)throw new Error(L('文章项目不存在或无法读取。','This article project does not exist or could not be loaded.'));
            if(background&&state.pendingSaves){clearLoadingStatus();return false;}
            if(Number(article.revision||0)<state.revision){clearLoadingStatus();return false;}
            if(background&&state.article&&Number(article.revision||0)<=Number(state.article.revision||0)&&article.source_sha256===state.article.source_sha256){clearLoadingStatus();return false;}
            const keepLocal=preserveSelection||selectionSequenceAtStart!==state.selectionSequence;
            const local={theme:state.selectedThemeId,title:state.selectedTitleVariantId,cover:state.selectedCoverVariantId};
            const previousRevision=state.revision;
            state.article=article;state.revision=Number(article.revision||0);
            if(previousRevision!==state.revision){
                state.versionManifest=null;
                state.versionDetails.clear();
                state.versionLoadState='loading';
                invalidateHistoryLayoutPreviews();
            }
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
            clearLoadingStatus();
            if(!background){if(state.statusTimer)clearTimeout(state.statusTimer);state.status=null;renderStatus();}
            else if(state.status?.kind==='success'){state.status=null;renderStatus();}
            renderArticle();
            void loadVersionManifest();
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
                state.unsavedSelection=null;
                invalidateHistoryLayoutPreviews();
                state.versionManifest=null;state.versionLoadState='loading';
                clearStatus();renderArticle();
                await loadVersionManifest();
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
        }).finally(()=>{
            state.pendingSaves=Math.max(0,state.pendingSaves-1);
            syncVersionRestoreButtons();
        });
    }

    function selectTheme(id){if(Object.prototype.hasOwnProperty.call(state.article?.variants||{},id))persistSelection('theme',id);}
    function selectTitleVariant(id){
        const item=state.article?.title_variants?.[id];
        if(item?.valid===true&&typeof item.title==='string'&&item.title.trim()){
            const picker=$('#articleTitleDetails');if(picker)picker.open=false;
            persistSelection('title',id);
            $('.article-current-title-summary')?.focus({preventScroll:true});
        }
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
        if(state.bodyView==='compare')return null;
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
        return {articleId:String(state.article?.project_id||articleId),themeId:state.selectedThemeId,key:content?.key||'',html:content?.html||''};
    }

    function assertPortableSnapshot(snapshot){
        const current=articleClipboardContent();
        if(!current||!snapshot||String(state.article?.project_id||articleId)!==snapshot.articleId
            ||state.selectedThemeId!==snapshot.themeId||current.key!==snapshot.key||current.html!==snapshot.html){
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

    function setArticleBodyView(view,focus=true){
        const next=view==='compare'?'compare':'preview';
        if(next==='compare'&&!state.article)return;
        if(next==='compare'&&$('.article-preview-region.is-full-preview'))setFullPreview(false);
        if(next==='compare')ensureCompareInitialized();
        state.bodyView=next;
        const preview=next==='preview';
        const compare=next==='compare';
        const previewTab=$('#articlePreviewTab');
        const compareTab=$('#articleCompareTab');
        const previewPanel=$('#articlePreviewPanel');
        const comparePanel=$('#articleComparePanel');
        if(previewTab)previewTab.setAttribute('aria-selected',preview?'true':'false');
        if(compareTab)compareTab.setAttribute('aria-selected',compare?'true':'false');
        if(previewPanel)previewPanel.hidden=!preview;
        if(comparePanel)comparePanel.hidden=!compare;
        renderArticle();
        if(focus)(preview?previewTab:compareTab)?.focus();
    }

    function syncManagementDrawer(){
        const drawer=$('#articleManagementDrawer');
        if(!drawer)return;
        drawer.open=!window.matchMedia('(max-width: 850px)').matches;
    }

    async function exportHtml(){
        const content=articleClipboardContent();
        if(!content?.html){setActionFeedback('articleCopyFeedback','当前排版不可用，不能导出。','The current layout is unavailable and cannot be exported.','error');return;}
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
        $('#articleTitle').textContent=en?'WeChat articles':'公众号文章';
        $('#articleLayoutsTitle').textContent=en?'Theme':'主题';
        $('#articleLayoutHint').textContent=en?'Choose a saved layout. HTML integrity is checked before copy or export.':'选择已保存的排版；复制或导出前会检查 HTML 完整性。';
        $('#articlePreviewFrame').title=en?'Article preview':'文章正文预览';
        $('#articleCopyButton span').textContent=en?'Copy article':'复制正文';
        $('#articleExportButton span').textContent=en?'Export':'导出';
        $('#articleRefreshButton').title=en?'Reload article':'重新读取文章';
        $('#articleRefreshButton').setAttribute('aria-label',$('#articleRefreshButton').title);
        $('#articleLanguageButton').textContent=en?'EN':'中';
        $('#articleLanguageButton').title=en?'Switch language':'切换语言';
        $('#articleLanguageButton').setAttribute('aria-label',$('#articleLanguageButton').title);
        $('#articleThemeButton').title=en?'Switch theme':'切换主题';
        $('#articleThemeButton').setAttribute('aria-label',$('#articleThemeButton').title);
        $('#articlePreviewTab').textContent=en?'Layout preview':'排版预览';
        $('#articleCompareTab').textContent=en?'Compare body':'正文对比';
        $('#articleManagementSummary').textContent=en?'Article management and history':'文章管理与历史';
        $('#articleRevisionSummary').textContent=en?'Details':'详情';
        $('#articleTitleVersionsHeading').textContent=en?'Title':'标题';
        $('#articleTitleHistoryHeading').textContent=en?'Title history':'标题历史';
        $('#articleCoverCurrentHeading').textContent=en?'Cover':'封面';
        $('#articleCoverSectionHeading').textContent=en?'Cover history':'封面历史';
        $('#articleBodyVersionsHeading').textContent=en?'Body':'正文';
        $('#articleBodyHistoryHeading').textContent=en?'Body history':'正文历史';
        $('#articleTitleHistory').setAttribute('aria-label',en?'Title history':'标题历史');
        $('#articleCoverHistory').setAttribute('aria-label',en?'Cover history':'封面历史');
        $('#articleBodyHistory').setAttribute('aria-label',en?'Body history':'正文历史');
        $('#articleImageNote').textContent=en?'After pasting, check how images and layout appear in the WeChat editor.':'复制后请在公众号编辑器中检查图片显示与样式。';
        $('#articleBodySectionHeading').textContent=en?'Body':'正文';
        $('#articleCopyTitleButton span').textContent=en?'Copy title':'复制标题';
        $('#articleCopyCoverButton span').textContent=en?'Copy image':'复制图片';
        $('#articleDownloadCoverButton span').textContent=en?'Download image':'下载图片';
        $('#articleFullPreviewButton span').textContent=en?'Full preview':'完整预览';
        $('#articleFullPreviewClose').title=en?'Close full preview':'关闭完整预览';
        $('#articleFullPreviewClose').setAttribute('aria-label',$('#articleFullPreviewClose').title);
        $('#articleCoverHint').textContent=en?'Click the image to preview. Copy or download the selected cover.':'点击图片可放大预览；当前选择的封面可复制或下载。';
        $('#articleCoverLightboxClose').setAttribute('aria-label',en?'Close image preview':'关闭图片预览');
        $('#articleCoverLightboxTitle').textContent=en?'Cover preview':'封面预览';
        $('#articleCoverLightboxHint').textContent=en?'Click outside or press Escape to close.':'点击空白处或按 Esc 关闭。';
        setArticleBodyView(state.bodyView,false);
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
        $('.article-workspace')?.addEventListener('click',event=>{
            const retry=event.target.closest('[data-retry-versions]');
            if(retry){void loadVersionManifest();return;}
            const compareSelect=event.target.closest('[data-compare-select]');
            if(compareSelect){selectCompareTarget(compareSelect.dataset.compareSelect);return;}
            const compareLane=event.target.closest('[data-compare-lane]');
            if(compareLane){selectCompareTarget(compareLane.dataset.compareLane);return;}
            const restore=event.target.closest('[data-restore-kind][data-version-id]');
            if(restore){
                if(!restore.disabled){
                    if(restore.dataset.restoreKind==='body'&&state.bodyView==='compare')void compareBodyVersion(restore.dataset.versionId);
                    else void restoreArticleVersion(restore.dataset.restoreKind,restore.dataset.versionId);
                }
                return;
            }
        });
        $('#articleCurrentCoverPreview')?.addEventListener('click',event=>{const item=currentCover();if(item)openCoverLightbox(item,event.currentTarget);});
        $('[data-article-status]')?.addEventListener('click',event=>{if(event.target.closest('#articleRetrySelectionButton'))retrySelection();});
        $('#articleCopyButton')?.addEventListener('click',copyCurrentArticle);
        $('#articleCopyTitleButton')?.addEventListener('click',copyCurrentTitle);
        $('#articleCopyCoverButton')?.addEventListener('click',copyCurrentCover);
        $('#articleDownloadCoverButton')?.addEventListener('click',downloadCurrentCover);
        $('#articleExportButton')?.addEventListener('click',exportHtml);
        $('#articleFullPreviewButton')?.addEventListener('click',()=>{setArticleBodyView('preview',false);setFullPreview(true);});
        $('#articleFullPreviewClose')?.addEventListener('click',()=>setFullPreview(false));
        $('#articleBodyViewTabs')?.addEventListener('click',event=>{
            const tab=event.target.closest('[role="tab"]');
            if(tab?.id==='articlePreviewTab')setArticleBodyView('preview',false);
            if(tab?.id==='articleCompareTab'){
                if($('.article-preview-region.is-full-preview'))setFullPreview(false);
                setArticleBodyView('compare',true);
            }
        });
        $('#articleBodyViewTabs')?.addEventListener('keydown',event=>{
            if(event.key!=='ArrowLeft'&&event.key!=='ArrowRight')return;
            const views=['preview','compare'];
            const current=views.indexOf(state.bodyView);
            const delta=event.key==='ArrowRight'?1:-1;
            const next=views[(Math.max(0,current)+delta+views.length)%views.length];
            event.preventDefault();setArticleBodyView(next,true);
        });
        $('#articleBodyHistoryDetails')?.addEventListener('toggle',()=>{
            const history=$('#articleBodyHistory');
            if($('#articleBodyHistoryDetails')?.open&&isLayoutHistoryView())observeLayoutPreviews(history);
            else{state.layoutPreviewObserver?.disconnect();state.layoutPreviewObserver=null;}
        });
        $('#articleCoverLightboxClose')?.addEventListener('click',()=>$('#articleCoverLightbox')?.close());
        $('#articleCoverLightbox')?.addEventListener('click',event=>{if(event.target===event.currentTarget)event.currentTarget.close();});
        $('#articleCoverLightbox')?.addEventListener('close',()=>{
            const opener=state.coverPreviewOpener;
            state.coverPreviewOpener=null;
            if(opener?.isConnected){opener.focus();return;}
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
        [['left','#articleCompareLeftFrame'],['right','#articleCompareRightFrame']].forEach(([lane,selector])=>{
            $(selector)?.addEventListener('load',()=>{
                const frame=$(selector);
                const entry=state.comparePanes[lane].entry;
                const key=frame?.dataset.compareKey||'';
                if(!frame||!key||entry?.key!==key)return;
                try{
                    const doc=frame.contentDocument;
                    if(!doc?.getElementById('articlePreviewContent'))return;
                    frame.dataset.compareLoadedKey=key;
                    doc.addEventListener('pointerdown',()=>selectCompareTarget(lane),{passive:true});
                    doc.addEventListener('focusin',()=>selectCompareTarget(lane));
                    doc.addEventListener('click',event=>{
                        const link=event.target?.closest?.('a[href]');
                        if(link){event.preventDefault();event.stopPropagation();}
                    },true);
                }catch(error){
                    state.comparePanes[lane].error=L('此排版无法在安全预览中打开。','This layout could not be opened in the safe preview.');
                    renderComparePane(lane);
                }
            });
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
        const managementMedia=window.matchMedia('(max-width: 850px)');
        syncManagementDrawer();
        managementMedia.addEventListener?.('change',syncManagementDrawer);
    }

    async function initialize(){
        if(window.lucide?.createIcons)window.lucide.createIcons();
        bindEvents();applyLanguage();
        await loadArticle();
        state.syncTimer=window.setInterval(()=>{if(!document.hidden&&!state.pendingSaves)loadArticle({background:true});},20000);
    }

    initialize();
})();
