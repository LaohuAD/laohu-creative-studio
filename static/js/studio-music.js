(function(){
    'use strict';

    const params=new URLSearchParams(location.search);
    const projectId=params.get('id')||'';
    const $=selector=>document.querySelector(selector);
    const state={music:null,project:null,tab:'lyrics',scoreId:'',scoreLoading:false,activeAudio:null,activeLyricIndex:-1,generations:[],pollingRuns:new Set(),submittingPurposes:new Set(),loading:false,saveBusy:false,mappingResolve:null,pollTimer:0,refreshTimer:0};
    const words={
        zh:{kicker:'音乐创作',reading:'正在读取作品…',missingId:'链接缺少音乐项目 ID，请从项目列表重新打开。',load:'正在读取音乐作品…',loadError:'音乐作品读取失败',retry:'重新读取',refresh:'重新读取',switchLanguage:'切换语言',switchTheme:'切换明暗模式',updated:'最近更新',noTitle:'未命名歌曲',song:'歌曲',titleSection:'01 · SONG',titles:'标题备选',noTitles:'没有其他标题版本',titleAdopted:'已采用这个标题',selectionFailed:'选择没有保存，请重新读取后再试。',conflict:'作品已在其他标签页更新，页面已重新读取；请重新选择。',tabs:['歌词与风格','乐谱','创作备注'],lyrics:'歌词',style:'风格与编曲',notes:'创作备注',references:'参考音频',noLyrics:'还没有保存歌词。',noStyle:'还没有保存风格信息。',noNotes:'还没有创作备注。',noReferences:'没有参考音频。',noScores:'暂时没有乐谱文件。',noAudio:'暂时没有音频结果。',scores:'乐谱文件',noScoreData:'请选择一份乐谱查看。',scoreUnavailable:'无法读取这份乐谱。请检查共享素材引用后重试。',scoreParseFailed:'没有识别到可检查的音符或小节。下面保留实际文件内容。',scoreMeasures:'小节',scorePart:'声部',scoreTrack:'轨道',scorePitch:'音高',scoreDuration:'时值',scoreStart:'起始 tick',scoreTicks:'时值 tick',scoreRest:'休止',scoreView:'查看',scoreSource:'原始内容',audio:'音频结果',audioHint:'试听不会自动采用音频版本。',generate:'按配置生成音频',generateCover:'按配置生成封面',configure:'配置生成流程',configureError:'请先在 API 设置的“音乐创作”中连接音乐输出节点。',generating:'正在提交音乐任务…',recover:'恢复上次生成请求',recovering:'正在查询原任务…',generationWorking:'音乐任务仍在运行；此页面会继续查询同一个任务。',generationQueued:'任务已提交，等待执行。',generationDone:'音频已关联到作品。',coverDone:'封面已关联到作品。',generationAssociationError:'任务已完成，但结果关联暂时失败；重试查询同一任务。',generationFailed:'音乐任务失败',generationCancelled:'音乐任务已取消',generationUnknown:'任务状态仍可查询；可恢复原请求。',generationNoOutput:'配置图中没有连接的用途输出端口。请先添加并连接相应用途输出。',generationConfigLink:'配置生成流程',generationNetworkUncertain:'提交结果不确定。恢复时会复用同一操作编号，不会创建新的任务。',generationStarted:'请求已提交，正在查询任务。',audioCount:'个音频版本',cover:'封面',coverEmpty:'还没有保存封面；可以由 Agent 写入，也可按配置明确生成。',coverCount:'张封面',coverSelect:'采用此封面',audioSelect:'采用此音频',selected:'已采用',play:'试听',pause:'暂停',expand:'展开播放器',download:'下载',downloadStarted:'已开始下载',downloadFailed:'下载失败，请确认素材仍可访问。',playError:'无法播放此音频，请下载文件后检查。',openPlayer:'展开播放器',closePlayer:'关闭播放器',playing:'正在播放',lyricsSync:'同步歌词',noTimedLyrics:'这份音频没有保存同步歌词。',lyricNotSynced:'未同步',managedOnly:'此文件没有可访问的共享素材链接。',audioSource:'音频来源',reference:'参考音频',readOnly:'内容由外部 Agent 保存；此页用于查看、试听和明确选择结果。',mappingTitle:'本次输入',mappingHint:'为本次任务选择画布动态节点的精确输入字段。映射只用于这次提交，不会保存到作品。',mappingMissing:'请选择所有带 * 的输入字段。若字段不合适，请返回配置画布检查节点 Schema。',mappingDuplicate:'同一动态字段不能接收多个输入，请为每项选择不同字段。',mappingCancel:'取消',mappingSubmit:'继续提交',mappingOptional:'不传此项',mappingSelectField:'请选择精确输入字段',mappingTitleRole:'歌曲标题',mappingLyrics:'歌词',mappingStyle:'风格',mappingNotes:'创作备注',mappingCoverPrompt:'封面提示词',mappingReferenceAudio:'参考音频',mappingNoFields:'当前配置输出依赖中没有可用的动态文本/音频字段。请在配置画布中读取并保存 AI 应用或工作流字段后重试。',mappingNoText:'当前歌曲没有歌词或风格内容，无法映射到动态文本节点。',mappingCoverMissing:'请先让 Agent 保存封面提示词，再提交封面生成。',mappingReadError:'无法读取本次配置图字段。请重新读取配置后重试。'},
        en:{kicker:'MUSIC CREATION',reading:'Loading project…',missingId:'This link has no music project ID. Reopen it from the project list.',load:'Loading music work…',loadError:'Could not load this music project',retry:'Reload',refresh:'Reload',switchLanguage:'Switch language',switchTheme:'Switch theme',updated:'Updated',noTitle:'Untitled song',song:'Song',titleSection:'01 · SONG',titles:'Title options',noTitles:'No alternate title versions',titleAdopted:'Title selected',selectionFailed:'Selection was not saved. Reload the project and try again.',conflict:'This work changed in another tab. It has been reloaded; choose again.',tabs:['Lyrics & style','Scores','Notes'],lyrics:'Lyrics',style:'Style & arrangement',notes:'Creative notes',references:'Reference audio',noLyrics:'No lyrics have been saved.',noStyle:'No style details have been saved.',noNotes:'No creative notes have been saved.',noReferences:'No reference audio.',noScores:'No score files yet.',noAudio:'No audio results yet.',scores:'Score files',noScoreData:'Choose a score to inspect it.',scoreUnavailable:'Could not read this score. Check its shared media reference and try again.',scoreParseFailed:'No inspectable notes or measures were found. The actual file content is shown below.',scoreMeasures:'Measures',scorePart:'Part',scoreTrack:'Track',scorePitch:'Pitch',scoreDuration:'Duration',scoreStart:'Start tick',scoreTicks:'Ticks',scoreRest:'Rest',scoreView:'View',scoreSource:'Source',audio:'Audio results',audioHint:'Listening does not select a version.',generate:'Generate audio from setup',generateCover:'Generate cover from setup',configure:'Configure generation',configureError:'Connect the required output node under Music Creation in API Settings first.',generating:'Submitting music task…',recover:'Recover last request',recovering:'Checking the existing task…',generationWorking:'The music task is still running. This page will keep checking the same task.',generationQueued:'Task submitted and waiting to run.',generationDone:'Audio was linked to this project.',coverDone:'Cover was linked to this project.',generationAssociationError:'The task finished, but linking its result failed. Retry the same task lookup.',musicGenerationFailed:'Music generation failed',generationFailed:'Music task failed',generationCancelled:'Music task was cancelled',generationUnknown:'This task can still be queried. Recover the original request.',generationNoOutput:'No connected purpose output exists in the setup graph. Add and connect the matching output first.',generationConfigLink:'Configure generation',generationNetworkUncertain:'The submission result is uncertain. Recovery reuses the same operation ID and will not create another task.',generationStarted:'Request submitted; checking task status.',audioCount:'audio versions',cover:'Cover',coverEmpty:'No cover saved yet. An Agent can add one, or you can explicitly generate one from the setup.',coverCount:'covers',coverSelect:'Use cover',audioSelect:'Use audio',selected:'Selected',play:'Listen',pause:'Pause',expand:'Open player',download:'Download',downloadStarted:'Download started',downloadFailed:'Download failed. Check that the shared asset is still available.',playError:'Audio could not play. Try downloading it to inspect the file.',openPlayer:'Open player',closePlayer:'Close player',playing:'Now playing',lyricsSync:'Timed lyrics',noTimedLyrics:'No timed lyrics were saved with this audio.',lyricNotSynced:'Not synced',managedOnly:'This file has no accessible shared-media URL.',audioSource:'Audio source',reference:'Reference audio',readOnly:'Content is saved by an external Agent. Use this page to review, listen and explicitly select results.',mappingTitle:'Inputs for this run',mappingHint:'Choose exact input fields on dynamic canvas nodes. These mappings apply only to this submission and are not saved with the song.',mappingMissing:'Choose every field marked *. If the available fields are wrong, review the node schema in the setup canvas.',mappingDuplicate:'A dynamic input field can receive one value. Choose a different field for each selected role.',mappingCancel:'Cancel',mappingSubmit:'Continue',mappingOptional:'Do not send this value',mappingSelectField:'Choose an exact input field',mappingTitleRole:'Song title',mappingLyrics:'Lyrics',mappingStyle:'Style',mappingNotes:'Creative notes',mappingCoverPrompt:'Cover prompt',mappingReferenceAudio:'Reference audio',mappingNoFields:'No usable dynamic text/audio fields were found in this output’s dependency graph. Load and save the app or workflow fields in the setup canvas, then retry.',mappingNoText:'This song has no lyrics or style text to map to the dynamic node.',mappingCoverMissing:'Ask the Agent to save a cover prompt before submitting cover generation.',mappingReadError:'Could not read fields for this setup. Reload the configuration and try again.'}
    };
    const L=(zh,en)=>lang()==='en'?en:zh;
    const lang=()=>String(window.StudioI18n?.lang?.()||document.documentElement.lang||'zh').toLowerCase().startsWith('en')?'en':'zh';
    const W=()=>words[lang()];
    const escapeHtml=value=>String(value==null?'':value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const apiError=async response=>{let payload={};try{payload=await response.json();}catch(_){}const detail=payload?.detail?.message||payload?.detail||payload?.message||`${response.status} ${response.statusText}`;const error=new Error(String(detail));error.status=response.status;return error;};
    async function api(path,options={}){const response=await fetch(path,{cache:'no-store',...options});if(!response.ok)throw await apiError(response);return response.json();}
    function setStatus(message='',kind=''){const node=$('#musicStatus');if(!node)return;node.textContent=message;node.hidden=!message;node.dataset.kind=kind;}
    function notify(message,kind='success'){setStatus(message,kind);window.clearTimeout(state.statusTimer);state.statusTimer=window.setTimeout(()=>setStatus(''),5500);}
    function refreshIcons(){window.lucide?.createIcons?.();}
    function timeLabel(value){const n=Number(value||0);if(!n||!Number.isFinite(n))return'—';const date=new Date(n<1e12?n*1000:n);return Number.isNaN(date.getTime())?'—':date.toLocaleString(lang()==='en'?'en-US':'zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});}
    function fileName(value,fallback='download'){return String(value||fallback).replace(/[\\/:*?"<>|]+/g,'_').trim().slice(0,100)||fallback;}
    function safeMediaUrl(ref){
        const raw=String(ref?.url||'').trim();if(!raw)return'';
        try{const url=new URL(raw,location.origin);if(url.origin!==location.origin||url.username||url.password||url.search||url.hash)return'';if(!/^\/api\/(?:results|materials)\/[A-Za-z0-9._~-]+$/.test(url.pathname))return'';return url.pathname;}catch(_){return'';}
    }
    function formatDuration(seconds){const n=Math.max(0,Math.floor(Number(seconds)||0));const mm=Math.floor(n/60);return`${mm}:${String(n%60).padStart(2,'0')}`;}
    function titleText(item){if(typeof item==='string')return item;return String(item?.title||item?.name||'');}
    function titleChoices(){const raw=state.music?.title_candidates;if(Array.isArray(raw))return raw.map((item,index)=>typeof item==='string'?{id:String(index),title:item}:item);if(raw&&typeof raw==='object')return Object.entries(raw).map(([id,item])=>typeof item==='string'?{id,title:item}:{...item,id:item?.id||id});return[];}
    function currentTitle(){const choices=titleChoices();const chosen=choices.find(item=>String(item?.id||'')===String(state.music?.selected_title_candidate_id||''));return titleText(chosen)||String(state.music?.title||'')||W().noTitle;}
    function idsFor(projectId,purpose='song'){return`studio_music_operation_v1:${projectId}:${purpose}`;}
    function readOperation(purpose='song'){try{return JSON.parse(localStorage.getItem(idsFor(projectId,purpose))||'null');}catch(_){return null;}}
    function writeOperation(op){try{const saved={...op};if(saved.run_id)saved.request={};localStorage.setItem(idsFor(projectId,op.purpose),JSON.stringify(saved));}catch(_){}}
    function operationId(){return`music_${projectId}_${crypto.randomUUID?.()||`${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`}`;}
    function titleMarkup(){
        const choices=titleChoices();
        const list=$('#musicTitleChoices');
        $('#musicCurrentTitle').textContent=currentTitle();
        list.innerHTML=choices.length?choices.map((item,index)=>{const id=String(item?.id||'');const text=titleText(item);if(!text)return'';const selected=id&&id===String(state.music.selected_title_candidate_id||'');return`<button class="music-title-choice" type="button" data-title-id="${escapeHtml(id)}" aria-pressed="${selected?'true':'false'}" ${!id?'disabled':''}>${escapeHtml(text)}</button>`;}).join(''):`<span class="music-muted">${escapeHtml(W().noTitles)}</span>`;
    }
    function audioCardMarkup(item,index){
        const id=String(item?.id||'');const url=safeMediaUrl(item);const selected=String(state.music?.selected_audio_variant_id||'')===id;const title=String(item?.snapshot?.title||currentTitle()||item?.name||W().audio);const name=String(item?.name||`${W().audio} ${index+1}`);const mime=String(item?.mime||'');
        return`<article class="music-audio-card" data-selected="${selected?'true':'false'}" data-audio-id="${escapeHtml(id)}">
            <button class="music-audio-play" type="button" data-audio-action="play" data-audio-id="${escapeHtml(id)}" aria-label="${escapeHtml(W().play)}" ${!url?'disabled':''}><i data-lucide="play" aria-hidden="true"></i></button>
            <div class="music-audio-copy"><strong title="${escapeHtml(title)}">${escapeHtml(title)}</strong><small>${escapeHtml(name)} · ${escapeHtml(timeLabel(item?.created_at))}</small></div>
            <div class="music-audio-actions"><button type="button" data-audio-action="expand" data-audio-id="${escapeHtml(id)}" ${!url?'disabled':''}><i data-lucide="maximize-2" aria-hidden="true"></i>${escapeHtml(W().expand)}</button><button type="button" data-audio-action="select" data-audio-id="${escapeHtml(id)}" aria-pressed="${selected?'true':'false'}" ${!id?'disabled':''}>${escapeHtml(selected?W().selected:W().audioSelect)}</button>${url?`<a href="${escapeHtml(url)}" download="${escapeHtml(fileName(name,'song-audio'))}" data-audio-action="download" data-audio-id="${escapeHtml(id)}"><i data-lucide="download" aria-hidden="true"></i>${escapeHtml(W().download)}</a>`:`<span>${escapeHtml(W().managedOnly)}</span>`}</div>
        </article>`;
    }
    function coverCardMarkup(item,index){
        const id=String(item?.id||'');const url=safeMediaUrl(item);const selected=String(state.music?.selected_cover_variant_id||'')===id;const mime=String(item?.mime||'');const isImage=mime.toLowerCase().startsWith('image/');const name=String(item?.name||`${W().cover} ${index+1}`);
        return`<article class="music-cover-card" data-selected="${selected?'true':'false'}"><div class="music-cover-image">${url&&isImage?`<img src="${escapeHtml(url)}" alt="${escapeHtml(name)}" loading="lazy" referrerpolicy="same-origin">`:`<i data-lucide="image" aria-hidden="true"></i>`}</div><strong title="${escapeHtml(name)}">${escapeHtml(name)}</strong><button class="music-cover-select" type="button" data-cover-id="${escapeHtml(id)}" aria-pressed="${selected?'true':'false'}" ${!id?'disabled':''}>${escapeHtml(selected?W().selected:W().coverSelect)}</button></article>`;
    }
    function referenceMarkup(ref,index){const url=safeMediaUrl(ref),name=String(ref?.name||`${W().reference} ${index+1}`);return`<div class="music-reference-item"><span title="${escapeHtml(name)}">${escapeHtml(name)}</span>${url?`<button type="button" data-reference-play="${escapeHtml(ref.id)}" aria-label="${escapeHtml(W().play)}">${escapeHtml(W().play)}</button><button type="button" data-reference-download="${escapeHtml(ref.id)}">${escapeHtml(W().download)}</button>`:`<small>${escapeHtml(W().managedOnly)}</small>`}</div>`;}
    function renderAudio(){
        const list=Array.isArray(state.music?.audio_variants)?state.music.audio_variants:[];
        $('#musicAudioCount').textContent=String(list.length);
        const generation=currentGeneration('song');const recoverable=generation&&!generation.run_id&&['uncertain','submitting'].includes(generation.phase);
        $('#musicAudioState').hidden=list.length>0||generation?true:false;
        $('#musicAudioState').textContent=list.length?'':generationMessage('song')||W().noAudio;
        $('#musicAudioList').innerHTML=list.map(audioCardMarkup).join('');
        $('#musicGenerateLabel').textContent=recoverable?W().recover:generation?generationLabel('song'):W().generate;
        $('#musicGenerateButton').disabled=!!generation&&!recoverable||state.loading||state.submittingPurposes.has('song');
        $('#musicGenerateButton').setAttribute('aria-busy',generation&&!recoverable?'true':'false');
        $('#musicGenerateButton').dataset.recover=recoverable?'true':'false';
        refreshIcons();
    }
    function renderCovers(){const list=Array.isArray(state.music?.cover_variants)?state.music.cover_variants:[];const generation=currentGeneration('cover');const recoverable=generation&&!generation.run_id&&['uncertain','submitting'].includes(generation.phase);$('#musicCoverCount').textContent=String(list.length);$('#musicCoverState').textContent=list.length?'':generationMessage('cover')||W().coverEmpty;$('#musicCoverState').hidden=list.length>0&&!generation;$('#musicCoverList').innerHTML=list.map(coverCardMarkup).join('');$('#musicGenerateCoverLabel').textContent=recoverable?W().recover:generation?generationLabel('cover'):W().generateCover;$('#musicGenerateCoverButton').disabled=!!generation&&!recoverable||state.loading||state.submittingPurposes.has('cover');$('#musicGenerateCoverButton').dataset.recover=recoverable?'true':'false';refreshIcons();}
    function renderReferences(){const refs=Array.isArray(state.music?.reference_audio_refs)?state.music.reference_audio_refs:[];const block=$('#musicReferencesBlock');block.hidden=!refs.length;$('#musicReferences').innerHTML=refs.map(referenceMarkup).join('');}
    function applyLanguage(){
        const w=W();document.documentElement.lang=lang()==='en'?'en':'zh-CN';
        $('#musicKicker').textContent=w.kicker;$('#musicRefreshButton').title=w.refresh;$('#musicRefreshButton').setAttribute('aria-label',w.refresh);$('#musicLanguageButton').textContent=lang()==='en'?'EN':'中';$('#musicLanguageButton').title=w.switchLanguage;$('#musicLanguageButton').setAttribute('aria-label',w.switchLanguage);$('#musicThemeButton').title=w.switchTheme;$('#musicThemeButton').setAttribute('aria-label',w.switchTheme);
        document.querySelectorAll('.music-toolbar-actions .music-icon-button').forEach(button=>{
            if(document.documentElement.dataset.studioAppearance==='dark'){
                button.style.setProperty('background-color','var(--music-surface)','important');
                button.style.setProperty('color','var(--music-text)','important');
                button.style.setProperty('border-color','var(--music-line-strong)','important');
            }else{
                button.style.removeProperty('background-color');button.style.removeProperty('color');button.style.removeProperty('border-color');
            }
        });
        $('#musicTitleHeading').textContent=w.song;$('#musicUpdatedAt').textContent=state.music?.updated_at?`${w.updated} ${timeLabel(state.music.updated_at)}`:'';
        const tabWords=w.tabs;[['lyrics',tabWords[0]],['scores',tabWords[1]],['notes',tabWords[2]]].forEach(([name,label])=>{const button=$(`[data-music-tab="${name}"]`);if(button?.querySelector('span'))button.querySelector('span').textContent=label;});
        $('#musicLyricsLabel').textContent=w.lyrics;$('#musicStyleLabel').textContent=w.style;$('#musicNotesLabel').textContent=w.notes;$('#musicReferencesLabel').textContent=w.references;
        $('#musicMappingTitle').textContent=w.mappingTitle;$('#musicMappingHint').textContent=w.mappingHint;$('#musicMappingCancel').textContent=w.mappingCancel;$('#musicMappingSubmit').textContent=w.mappingSubmit;$('#musicMappingClose').setAttribute('aria-label',w.mappingCancel);
        $('#musicAudioHeading').textContent=w.audio;$('#musicConfigureLabel').textContent=w.configure;$('#musicCoverHeading').textContent=w.cover;
        $('#musicPlayerClose').setAttribute('aria-label',w.closePlayer);
        $('#musicLyrics').textContent=String(state.music?.lyrics||'')||w.noLyrics;$('#musicStyle').textContent=String(state.music?.style_prompt||'')||w.noStyle;$('#musicNotes').textContent=String(state.music?.notes||'')||w.noNotes;
        $('#musicScoreCount').textContent=String(Array.isArray(state.music?.score_refs)?state.music.score_refs.length:0);
        renderReferences();titleMarkup();renderAudio();renderCovers();renderScoreDirectory();
        document.title=state.project?.name?`${state.project.name} · ${w.kicker}`:w.kicker;refreshIcons();
    }
    async function loadProjectName(){try{const response=await api('/api/studio/projects?module=music');const project=(response?.projects||[]).find(item=>String(item.id)===projectId);if(project){state.project=project;$('#musicProjectName').textContent=project.name||W().noTitle;}}catch(_) {}}
    async function loadMusic({background=false}={}){
        if(!projectId){setStatus(W().missingId,'error');$('#musicProjectName').textContent=W().noTitle;return false;}
        if(state.loading)return false;
        state.loading=true;if(!background)setStatus(W().load);
        try{
            const data=await api(`/api/studio/music/${encodeURIComponent(projectId)}`);
            if(data?.project_id&&String(data.project_id)!==projectId)throw new Error('音乐项目 ID 与当前地址不匹配');
            state.music=data;state.loading=false;if(!background)setStatus('');applyLanguage();
            return true;
        }catch(error){state.loading=false;if(error.status===409){setStatus(W().conflict,'error');return false;}if(!background){setStatus(`${W().loadError}：${error.message||''}`, 'error');const node=$('#musicStatus');node.insertAdjacentHTML('beforeend',` <button class="music-secondary-button" id="musicRetry" type="button">${escapeHtml(W().retry)}</button>`);}return false;}
    }
    async function updateSelection(field,value,success){
        if(!state.music||state.saveBusy)return false;state.saveBusy=true;
        try{
            const response=await fetch(`/api/studio/music/${encodeURIComponent(projectId)}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_revision:Number(state.music.revision),[field]:value})});
            if(response.status===409){await loadMusic({background:true});notify(W().conflict,'error');return false;}
            if(!response.ok)throw await apiError(response);
            const result=await response.json();state.music=result?.music||result;applyLanguage();notify(success);return true;
        }catch(error){notify(`${W().selectionFailed}${error?.message||''}`,'error');return false;}finally{state.saveBusy=false;}
    }
    function setTab(tab,{focus=false}={}){state.tab=tab;document.querySelectorAll('[data-music-tab]').forEach(button=>{const active=button.dataset.musicTab===tab;button.classList.toggle('active',active);button.setAttribute('aria-selected',active?'true':'false');button.tabIndex=active?0:-1;});document.querySelectorAll('.music-tab-panel').forEach(panel=>{panel.hidden=panel.id!==`musicPanel${tab[0].toUpperCase()}${tab.slice(1)}`;});if(focus)$(`[data-music-tab="${tab}"]`)?.focus();}
    function renderScoreDirectory(){
        const refs=Array.isArray(state.music?.score_refs)?state.music.score_refs:[];const directory=$('#musicScoreList');
        if(!refs.length){directory.innerHTML=`<div class="music-empty-inline">${escapeHtml(W().noScores)}</div>`;$('#musicScoreViewer').innerHTML=`<div class="music-empty-inline">${escapeHtml(W().noScoreData)}</div>`;return;}
        if(!refs.some(ref=>String(ref.id)===state.scoreId))state.scoreId=String(refs[0]?.id||'');
        directory.innerHTML=refs.map(ref=>`<button class="music-score-choice" type="button" data-score-id="${escapeHtml(ref.id)}" aria-pressed="${String(ref.id)===state.scoreId?'true':'false'}"><strong>${escapeHtml(ref.name||ref.format?.toUpperCase()||W().scores)}</strong><small>${escapeHtml(String(ref.format||'').toUpperCase())}</small></button>`).join('');
        if(!state.scoreLoading&&!$('#musicScoreViewer').dataset.scoreId){void inspectScore(state.scoreId);}
    }
    function musicXmlScore(xmlText){
        if(/<!DOCTYPE|<!ENTITY/i.test(xmlText))throw new Error('External declarations are not accepted');
        const doc=new DOMParser().parseFromString(xmlText,'application/xml');if(doc.querySelector('parsererror'))throw new Error('Malformed MusicXML');
        if(doc.documentElement?.localName!=='score-partwise')throw new Error('This viewer supports partwise MusicXML only');
        const local=(node,name)=>[...node.getElementsByTagName('*')].find(el=>el.localName===name);
        const parts=[...doc.getElementsByTagName('*')].filter(node=>node.localName==='part');const names=new Map();
        for(const part of [...doc.getElementsByTagName('*')].filter(node=>node.localName==='score-part')){const id=part.getAttribute('id')||'';const nm=local(part,'part-name')?.textContent?.trim();if(id&&nm)names.set(id,nm);}
        const measures=[];for(let pi=0;pi<parts.length;pi++){const part=parts[pi],partId=part.getAttribute('id')||String(pi+1),partName=names.get(partId)||`${W().scorePart} ${pi+1}`;const partMeasures=[...part.children].filter(node=>node.localName==='measure');for(let mi=0;mi<partMeasures.length;mi++){const measure=partMeasures[mi];const notes=[...measure.children].filter(node=>node.localName==='note').map(note=>{const pitch=local(note,'pitch'),step=local(pitch||note,'step')?.textContent?.trim()||'',alter=Number(local(pitch||note,'alter')?.textContent||0),octave=local(pitch||note,'octave')?.textContent?.trim()||'',dur=local(note,'duration')?.textContent?.trim()||'',rest=[...note.children].some(el=>el.localName==='rest');return{part:partName,measure:measure.getAttribute('number')||String(mi+1),pitch:rest?W().scoreRest:`${step}${alter>0?`+${alter}`:alter<0?alter:''}${octave}`,duration:dur,rest};});measures.push(...notes);if(measures.length>50000)throw new Error('MusicXML note limit exceeded');}}
        return{kind:'musicxml',rows:measures,parts:parts.length,source:xmlText};
    }
    const MAX_SCORE_BYTES=5*1024*1024;
    async function readScoreBytes(response){
        const announced=Number(response.headers.get('content-length')||0);
        if(announced>MAX_SCORE_BYTES)throw new Error('Score file is larger than the 5 MB inspection limit');
        if(!response.body?.getReader){const buffer=await response.arrayBuffer();if(buffer.byteLength>MAX_SCORE_BYTES)throw new Error('Score file is larger than the 5 MB inspection limit');return new Uint8Array(buffer);}
        const reader=response.body.getReader(),parts=[];let total=0;
        try{while(true){const {done,value}=await reader.read();if(done)break;total+=value.byteLength;if(total>MAX_SCORE_BYTES){await reader.cancel();throw new Error('Score file is larger than the 5 MB inspection limit');}parts.push(value);}}
        finally{reader.releaseLock?.();}
        const bytes=new Uint8Array(total);let offset=0;for(const part of parts){bytes.set(part,offset);offset+=part.byteLength;}return bytes;
    }
    function parseAbc(source){
        const lines=source.split(/\r?\n/);let bodyStart=-1,unitNumerator=1,unitDenominator=8,defaultLength=.5,measure=1,octaveBase=4,notes=[];const headers={};
        for(let i=0;i<lines.length;i++){const match=lines[i].match(/^([A-Za-z]):\s*(.*)$/);if(match){headers[match[1].toUpperCase()]=match[2].trim();if(match[1].toUpperCase()==='L'){const f=match[2].trim().match(/^(\d+)\s*\/\s*(\d+)$/);if(f){unitNumerator=Number(f[1]);unitDenominator=Number(f[2]);defaultLength=unitNumerator/unitDenominator*4;}}if(match[1].toUpperCase()==='K'){bodyStart=i+1;break;}}}
        if(bodyStart<0)throw new Error('ABC key header (K:) was not found');
        let text=lines.slice(bodyStart).join('\n').replace(/%[^\n]*/g,'').replace(/\[[A-Za-z]:[^\]]*\]/g,'');
        let i=0;while(i<text.length){const ch=text[i];if(ch==='|'){measure++;i++;continue;}if(ch===':'){i++;continue;}if(ch==='['){i++;continue;}if(/[\s,()!{}]/.test(ch)){i++;continue;}if(ch==='>'||ch==='<'){i++;continue;}if(ch==='"'){const end=text.indexOf('"',i+1);i=end<0?text.length:end+1;continue;}if(/[=_^]/.test(ch)||/[A-Ga-g]/.test(ch)||ch==='z'||ch==='x'){
                let accidental='';while(/[=_^]/.test(text[i]||'')){accidental+=text[i++];}let note=text[i];if(!/[A-Ga-gzZxX]/.test(note||'')){i++;continue;}i++;let octave=note===note.toLowerCase()?octaveBase+1:octaveBase;while(text[i]==="'"){octave++;i++;}while(text[i]===','){octave--;i++;}let multiplier='';while(/[0-9/]/.test(text[i]||'')){multiplier+=text[i++];}
                let length=defaultLength;if(multiplier){const frac=multiplier.match(/^(\d*)(?:\/(\d*))?$/);if(frac){const a=Number(frac[1]||1),b=frac[2]===undefined?1:Number(frac[2]||2);length*=a/b;}}
                const rest=/[zZxX]/.test(note);const pitch=rest?W().scoreRest:`${accidental}${note.toUpperCase()}${octave}`;notes.push({part:headers.T||W().song,measure,pitch,duration:Number((length*4).toFixed(3)),rest});if(notes.length>50000)throw new Error('ABC note limit exceeded');continue;
            }i++;}
        return{kind:'abc',rows:notes,measures:notes.reduce((max,n)=>Math.max(max,n.measure),0),source,unit:`${unitNumerator}/${unitDenominator}`};
    }
    function readUint32(view,offset){return view.getUint32(offset,false);}
    function parseMidi(buffer){
        const bytes=new Uint8Array(buffer),view=new DataView(buffer);if(bytes.length<14||String.fromCharCode(...bytes.slice(0,4))!=='MThd')throw new Error('Invalid MIDI header');
        const headerLength=readUint32(view,4);if(headerLength<6||8+headerLength>bytes.length)throw new Error('Invalid MIDI header length');
        const format=view.getUint16(8,false),trackCount=view.getUint16(10,false),division=view.getUint16(12,false);if(trackCount>256)throw new Error('MIDI track limit exceeded');if(!division||division&0x8000)throw new Error('SMPTE MIDI timing is not supported by this viewer');
        let offset=8+headerLength;const tracks=[];let noteCount=0;
        function vlq(pos,end){let value=0,count=0,b;do{if(pos>=end||count++>4)throw new Error('Invalid MIDI variable-length quantity');b=bytes[pos++];value=(value<<7)|(b&0x7f);}while(b&0x80);return{value,pos};}
        for(let track=0;track<trackCount;track++){
            if(offset+8>bytes.length||String.fromCharCode(...bytes.slice(offset,offset+4))!=='MTrk')throw new Error('Missing MIDI track');
            const length=readUint32(view,offset+4),start=offset+8,end=start+length;if(end>bytes.length)throw new Error('Truncated MIDI track');offset=end;let pos=start,tick=0,running=0;const active=new Map(),events=[];let trackName=`${W().scoreTrack} ${track+1}`;
            while(pos<end){const delta=vlq(pos,end);tick+=delta.value;pos=delta.pos;let status=bytes[pos];if(status<0x80){if(!running)throw new Error('Invalid MIDI running status');status=running;}else pos++;
                if(status===0xff){running=0;if(pos>=end)break;const type=bytes[pos++],len=vlq(pos,end);pos=len.pos;if(pos+len.value>end)throw new Error('Truncated MIDI meta event');const data=bytes.slice(pos,pos+len.value);pos+=len.value;if(type===0x03&&data.length)trackName=new TextDecoder().decode(data);continue;}
                if(status===0xf0||status===0xf7){running=0;const len=vlq(pos,end);pos=len.pos+len.value;if(pos>end)throw new Error('Truncated MIDI sysex');continue;}
                const kind=status&0xf0;if(kind<0x80||kind>0xe0)throw new Error('Unsupported MIDI event');running=status;const dataLength=(kind===0xc0||kind===0xd0)?1:2;if(pos+dataLength>end)throw new Error('Truncated MIDI channel event');const one=bytes[pos++];const two=dataLength===1?0:bytes[pos++];
                if(kind===0x90&&two>0){const key=`${status&15}:${one}`;if(!active.has(key))active.set(key,[]);active.get(key).push({tick,pitch:one,velocity:two});if(++noteCount>50000)throw new Error('MIDI note event limit exceeded');}
                else if(kind===0x80||(kind===0x90&&two===0)){const key=`${status&15}:${one}`,queue=active.get(key)||[];const onset=queue.shift();if(onset)events.push({...onset,endTick:tick,channel:status&15,track:trackName});}
            }
            for(const queue of active.values())for(const onset of queue)events.push({...onset,endTick:tick,channel:0,track:trackName});tracks.push(...events);
        }
        if(!tracks.length)throw new Error('No note events in MIDI file');return{kind:'midi',rows:tracks,division,format,trackCount};
    }
    function pitchMidi(value){const match=String(value).match(/^([A-G])([#b]?)(-?\d+)$/);if(!match)return NaN;const base={C:0,D:2,E:4,F:5,G:7,A:9,B:11}[match[1]];return(Number(match[3])+1)*12+base+(match[2]==='#'?1:match[2]==='b'?-1:0);}
    function renderMidi(data){const container=$('#musicScoreViewer');const canvas=document.createElement('canvas');canvas.className='music-piano-roll';canvas.setAttribute('role','img');canvas.setAttribute('aria-label',`${W().scores} piano roll`);container.append(canvas);const rows=data.rows;const dpr=window.devicePixelRatio||1;const width=Math.max(360,container.clientWidth-26),height=210;canvas.width=width*dpr;canvas.height=height*dpr;canvas.style.width='100%';canvas.style.height=`${height}px`;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);const pitches=rows.map(row=>row.pitch),min=Math.max(0,Math.min(...pitches)-2),max=Math.min(127,Math.max(...pitches)+2),range=Math.max(1,max-min),maxTick=Math.max(...rows.map(row=>row.endTick),1),left=34,top=12,chartW=width-left-8,chartH=height-top-22;ctx.fillStyle=getComputedStyle(document.documentElement).getPropertyValue('--music-surface').trim();ctx.fillRect(0,0,width,height);ctx.font='9px sans-serif';for(let p=min;p<=max;p++){const y=top+(max-p)/range*chartH;ctx.strokeStyle=getComputedStyle(document.documentElement).getPropertyValue('--music-line').trim();ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(width-8,y);ctx.stroke();if(p%12===0){ctx.fillStyle=getComputedStyle(document.documentElement).getPropertyValue('--music-muted').trim();ctx.fillText(`C${Math.floor(p/12)-1}`,2,y+3);}}ctx.fillStyle=getComputedStyle(document.documentElement).getPropertyValue('--music-accent').trim();for(const row of rows){const x=left+row.tick/maxTick*chartW,w=Math.max(2,(row.endTick-row.tick)/maxTick*chartW);const y=top+(max-row.pitch)/range*chartH;ctx.fillRect(x,y,Math.max(w,2),Math.max(2,chartH/range*.68));}ctx.fillStyle=getComputedStyle(document.documentElement).getPropertyValue('--music-muted').trim();ctx.fillText(`${W().scoreTrack} · ${data.trackCount} · ${data.division} ticks/quarter`,left,height-5);}
    function renderScoreRows(data){const container=$('#musicScoreViewer');container.replaceChildren();const summary=document.createElement('div');summary.className='music-score-toolbar';const label=document.createElement('strong');label.textContent=data.kind==='abc'?`${W().scores} · ABC (${data.rows.length})`:`${W().scores} · MusicXML (${data.parts} ${W().scorePart})`;summary.append(label);container.append(summary);
        if(data.kind==='midi'){renderMidi(data);const note=document.createElement('p');note.className='music-score-note';note.textContent=`${data.rows.length} ${W().scorePitch} events · ${data.division} ticks/quarter`;container.append(note);return;}
        if(data.rows.length){const table=document.createElement('table');table.className='music-score-table';const thead=document.createElement('thead'),tr=document.createElement('tr');[W().scorePart,W().scoreMeasures,W().scorePitch,W().scoreDuration].forEach(text=>{const th=document.createElement('th');th.textContent=text;tr.append(th);});thead.append(tr);table.append(thead);const tbody=document.createElement('tbody');data.rows.slice(0,1000).forEach(row=>{const line=document.createElement('tr');[row.part||'—',row.measure||'—',row.pitch||'—',row.duration||'—'].forEach(value=>{const td=document.createElement('td');td.textContent=String(value);line.append(td);});tbody.append(line);});table.append(tbody);container.append(table);}else{const warn=document.createElement('p');warn.className='music-score-note';warn.textContent=W().scoreParseFailed;container.append(warn);}
        const details=document.createElement('details');const summaryEl=document.createElement('summary');summaryEl.textContent=W().scoreSource;const pre=document.createElement('pre');pre.className='music-score-source';pre.textContent=data.source;details.append(summaryEl,pre);container.append(details);
    }
    async function inspectScore(id){
        const ref=(state.music?.score_refs||[]).find(item=>String(item.id)===String(id));if(!ref)return;state.scoreLoading=true;state.scoreId=String(id);const viewer=$('#musicScoreViewer');viewer.dataset.scoreId=state.scoreId;viewer.replaceChildren();const status=document.createElement('div');status.className='music-empty-inline';status.textContent=W().load;viewer.append(status);renderScoreDirectory();
        let source='';
        try{const url=safeMediaUrl(ref);if(!url)throw new Error(W().managedOnly);if(!['abc','musicxml','midi'].includes(String(ref.format||'')))throw new Error('Unknown score format');const response=await fetch(url,{cache:'no-store',credentials:'same-origin'});if(!response.ok)throw await apiError(response);const bytes=await readScoreBytes(response);let parsed;if(ref.format==='midi'){const buffer=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);parsed=parseMidi(buffer);}else{source=new TextDecoder('utf-8').decode(bytes);parsed=ref.format==='musicxml'?musicXmlScore(source):parseAbc(source);}if(state.scoreId!==String(id))return;renderScoreRows(parsed);}
        catch(error){if(state.scoreId===String(id)){viewer.replaceChildren();const fail=document.createElement('div');fail.className='music-empty-inline';fail.textContent=`${W().scoreUnavailable}${error.message?` · ${error.message}`:''}`;viewer.append(fail);if(source){const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent=W().scoreSource;const pre=document.createElement('pre');pre.className='music-score-source';pre.textContent=source;details.append(summary,pre);viewer.append(details);}}}
        finally{state.scoreLoading=false;renderScoreDirectory();refreshIcons();}
    }
    function normalizeTimedLyrics(value){
        if(!Array.isArray(value))return[];return value.filter(item=>item&&Number.isFinite(Number(item.start))&&Number(item.start)>=0&&String(item.text||'').trim()).map(item=>({start:Number(item.start),end:Number.isFinite(Number(item.end))?Number(item.end):null,text:String(item.text)})).sort((a,b)=>a.start-b.start);
    }
    function activeGeneration(purpose='song'){const list=state.generations||[];return list.find(item=>String(item.purpose||item.request?.purpose||'song')===purpose&&!isTerminal(item.status))||null;}
    function currentGeneration(purpose='song'){return activeGeneration(purpose);}
    function isTerminal(status){return['succeeded','success','completed','complete','failed','error','cancelled','canceled','rejected'].includes(String(status||'').toLowerCase());}
    function isSuccess(status){return['succeeded','success','completed','complete'].includes(String(status||'').toLowerCase());}
    function generationLabel(purpose='song'){const gen=currentGeneration(purpose);if(!gen)return purpose==='cover'?W().generateCover:W().generate;const status=String(gen.status||'').toLowerCase();return status==='queued'||status==='pending'?W().generationQueued:W().generationWorking;}
    function generationMessage(purpose='song'){const gen=currentGeneration(purpose);if(!gen)return'';const status=String(gen.status||'').toLowerCase();if(status==='queued'||status==='pending')return W().generationQueued;return W().generationWorking;}
    function renderGenerationState(){renderAudio();renderCovers();}
    async function getMusicSettings(){const data=await api('/api/studio/music/settings-canvas');if(data?.id!=='music-settings'||data?.canvas?.id!=='music-settings')throw new Error(W().configureError);return data.canvas;}
    function findOutputNode(canvas,slot){const nodes=Array.isArray(canvas?.nodes)?canvas.nodes:[];return nodes.find(node=>node?.type==='smart-hypit-output'&&node?.hypitSlot===slot&&Array.isArray(canvas.connections)&&canvas.connections.some(edge=>edge.to===node.id&&(edge.kind==='input'||edge.kind==='flow')))||null;}
    function operationPayload(purpose,slot,output,request={}){return{purpose,slot,output_node_id:output.id,client_operation_id:operationId(),base_revision:Number(state.music?.revision),request};}
    function generationRoles(purpose){
        const music=state.music||{},roles=[];
        const choices=titleChoices(),chosen=choices.find(item=>String(item?.id||'')===String(music.selected_title_candidate_id||''));
        const title=titleText(chosen)||String(music.title||'').trim();
        const lyrics=String(music.lyrics||'').trim(),style=String(music.style_prompt||'').trim(),notes=String(music.notes||'').trim(),coverPrompt=String(music.cover_prompt||'').trim();
        const refs=Array.isArray(music.reference_audio_refs)?music.reference_audio_refs:[];
        if(purpose==='song'){
            if(title)roles.push({key:'title',label:W().mappingTitleRole,value:title,required:false,kind:'text'});
            if(lyrics)roles.push({key:'lyrics',label:W().mappingLyrics,value:lyrics,required:true,kind:'text'});
            if(style)roles.push({key:'style_prompt',label:W().mappingStyle,value:style,required:true,kind:'text'});
            if(notes)roles.push({key:'notes',label:W().mappingNotes,value:notes,required:false,kind:'text'});
        }else if(coverPrompt)roles.push({key:'cover_prompt',label:W().mappingCoverPrompt,value:coverPrompt,required:true,kind:'text'});
        if(refs.length)roles.push({key:'reference_audio',label:W().mappingReferenceAudio,value:refs,required:true,kind:'audio'});
        return roles;
    }
    function normalizeProjection(data){
        const nodes=Array.isArray(data?.nodes)?data.nodes:[];
        return nodes.map(node=>({node_id:String(node?.node_id||''),node_type:String(node?.node_type||''),title:String(node?.title||node?.node_type||''),fields:(Array.isArray(node?.fields)?node.fields:[]).filter(field=>String(field?.targetFieldKey||'').trim()&&['text','audio'].includes(String(field?.kind||''))).map(field=>({node_id:String(node.node_id||''),node_title:String(node.title||node.node_type||''),targetFieldKey:String(field.targetFieldKey),label:String(field.label||field.targetFieldKey),kind:String(field.kind),required:field.required===true}))})).filter(node=>node.node_id);
    }
    function mappingFieldOptions(roles,projection){
        const fields=projection.flatMap(node=>node.fields);return roles.map(role=>({role,options:fields.filter(field=>field.kind===role.kind)}));
    }
    function openDynamicMappingDialog(purpose,projection){
        const roles=generationRoles(purpose),fields=mappingFieldOptions(roles,projection);const host=$('#musicMappingFields');host.replaceChildren();$('#musicMappingError').hidden=true;$('#musicMappingError').textContent='';
        if(!roles.some(role=>role.kind==='text')){notify(purpose==='cover'?W().mappingCoverMissing:W().mappingNoText,'error');return Promise.resolve(null);}
        if(!fields.some(row=>row.options.length)){notify(W().mappingNoFields,'error');return Promise.resolve(null);}
        if(fields.some(row=>row.role.required&&!row.options.length)){notify(W().mappingNoFields,'error');return Promise.resolve(null);}
        fields.forEach(({role,options})=>{
            const row=document.createElement('label');row.className='music-mapping-row';row.dataset.mappingRole=role.key;
            const copy=document.createElement('span');copy.className='music-mapping-role';copy.textContent=role.label+(role.required?' *':'');
            const summary=document.createElement('small');summary.className='music-mapping-preview';summary.textContent=role.kind==='audio'?`${role.value.length} · ${role.value.map(item=>String(item.name||W().reference)).join('、')}`:String(role.value).slice(0,140);
            const select=document.createElement('select');select.dataset.mappingSelect=role.key;select.dataset.required=role.required?'true':'false';select.dataset.mappingKind=role.kind;
            const blank=document.createElement('option');blank.value='';blank.textContent=role.required?W().mappingSelectField:W().mappingOptional;select.append(blank);
            options.forEach((field,index)=>{const option=document.createElement('option');option.value=String(index);option.dataset.nodeId=field.node_id;option.dataset.targetFieldKey=field.targetFieldKey;option.textContent=`${field.node_title} · ${field.label} (${field.targetFieldKey})`;select.append(option);});
            row.append(copy,summary,select);host.append(row);
        });
        if(!fields.some(row=>row.role.required&&row.options.length)){$('#musicMappingError').textContent=W().mappingNoFields;$('#musicMappingError').hidden=false;}
        $('#musicMappingDialog').showModal();
        return new Promise(resolve=>{state.mappingResolve=resolve;});
    }
    function finishMappingDialog(value){const dialog=$('#musicMappingDialog');if(!dialog.open)return;dialog.close();const resolve=state.mappingResolve;state.mappingResolve=null;if(resolve)resolve(value);}
    function confirmDynamicMappings(){
        const error=$('#musicMappingError');const selections=[...$('#musicMappingFields').querySelectorAll('[data-mapping-select]')];error.hidden=true;error.textContent='';
        const chosen=selections.filter(select=>select.value).map(select=>select.options[Number(select.value)+1]);
        if(selections.some(select=>select.dataset.required==='true'&&!select.value)){error.textContent=W().mappingMissing;error.hidden=false;return;}
        const unique=new Set(chosen.map(option=>`${option.dataset.nodeId}\u0000${option.dataset.targetFieldKey}`));if(unique.size!==chosen.length){error.textContent=W().mappingDuplicate;error.hidden=false;return;}
        const input_fields={};selections.forEach(select=>{if(!select.value)return;const option=select.options[Number(select.value)+1];input_fields[select.dataset.mappingSelect]={node_id:option.dataset.nodeId,targetFieldKey:option.dataset.targetFieldKey};});
        finishMappingDialog({input_fields});
    }
    async function inputFieldProjection(output){
        return api(`/api/studio/music/settings-canvas/input-fields?output_node_id=${encodeURIComponent(output.id)}`);
    }
    async function loadGenerationHistory(){
        try{const data=await api(`/api/studio/music/${encodeURIComponent(projectId)}/generations`);state.generations=Array.isArray(data?.generations)?data.generations:[];for(const purpose of ['song','cover']){const fallback=readOperation(purpose);if(fallback){if(!fallback.run_id&&fallback.phase==='submitting')fallback.phase='uncertain';if(!state.generations.some(item=>item.client_operation_id===fallback.client_operation_id))state.generations.push(fallback);}}state.generations.sort((a,b)=>Number(b.created_at||0)-Number(a.created_at||0));renderGenerationState();for(const purpose of ['song','cover']){const active=activeGeneration(purpose);if(active?.run_id)void pollGeneration(active.run_id,{background:true});}}
        catch(error){state.generations=['song','cover'].map(readOperation).filter(Boolean);for(const item of state.generations){if(item.run_id)void pollGeneration(item.run_id,{background:true});}renderGenerationState();}
    }
    async function submitOrRecover(options={}){
        const purpose=options.purpose||'song';if(state.submittingPurposes.has(purpose))return;state.submittingPurposes.add(purpose);renderGenerationState();
        try{return await submitOrRecoverImpl(options);}finally{state.submittingPurposes.delete(purpose);renderGenerationState();}
    }
    async function submitOrRecoverImpl({purpose='song',recover=false}={}){
        const slot=purpose==='cover'?'image':'music';const existing=readOperation(purpose);let op;
        if(recover){if(!existing||existing.run_id)return;op=existing;notify(W().recovering,'');}
        else{
            if(currentGeneration(purpose)){notify(W().generationWorking,'');return;}
            let canvas;try{canvas=await getMusicSettings();}catch(error){notify(`${W().configureError} ${error.message||''}`,'error');return;}
            const output=findOutputNode(canvas,slot);if(!output){notify(W().generationNoOutput,'error');return;}
            let request={};
            try{
                const projection=await inputFieldProjection(output);const dynamicNodes=normalizeProjection(projection);
                if(dynamicNodes.length){const selected=await openDynamicMappingDialog(purpose,dynamicNodes);if(!selected)return;request=selected;}
            }catch(error){notify(`${W().mappingReadError} ${error.message||''}`,'error');return;}
            op=operationPayload(purpose,slot,output,request);op.phase='submitting';writeOperation(op);state.generations=[op,...state.generations.filter(item=>String(item.client_operation_id)!==op.client_operation_id)];renderGenerationState();
        }
        try{
            const response=await api(`/api/studio/music/${encodeURIComponent(projectId)}/generations`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({purpose:op.purpose,slot:op.slot,output_node_id:op.output_node_id,client_operation_id:op.client_operation_id,...(Number.isInteger(op.base_revision)&&op.base_revision>0?{base_revision:op.base_revision}:{}),request:op.request})});
            const result=response?.generation||response;
            op.run_id=String(result?.run_id||'');op.status=String(result?.status||'accepted');op.phase='accepted';writeOperation(op);
            if(!op.run_id){op.phase='uncertain';writeOperation(op);notify(W().generationUnknown,'error');await loadGenerationHistory();return;}
            state.generations=[result,...state.generations.filter(item=>String(item.run_id)!==op.run_id&&String(item.client_operation_id||'')!==op.client_operation_id)];renderGenerationState();notify(W().generationStarted,'');void pollGeneration(op.run_id);
        }catch(error){
            op.phase=error.status&&error.status<500?'failed':'uncertain';op.status=op.phase==='failed'?'failed':'accepted';op.error=error.message||'';writeOperation(op);state.generations=[op,...state.generations.filter(item=>String(item.client_operation_id)!==op.client_operation_id)];if(error.status===409){await loadMusic({background:true});notify(W().conflict,'error');}else if(op.phase==='uncertain'){notify(W().generationNetworkUncertain,'error');renderGenerationState();}else{notify(`${W().generationFailed} · ${error.message||''}`,'error');renderGenerationState();}
        }
    }
    async function pollGeneration(runId,{background=false}={}){
        if(state.pollingRuns.has(String(runId)))return;
        state.pollingRuns.add(String(runId));
        const url=`/api/studio/music/${encodeURIComponent(projectId)}/generations/${encodeURIComponent(runId)}`;
        try{
            for(let attempt=0;attempt<80;attempt++){
                try{
                    const payload=await api(url);const result={...(payload?.generation||payload)};if(payload?.music&&!result.music)result.music=payload.music;
                    const purpose=String(result.purpose||'song');const op=readOperation(purpose);const operationKey=String(result.client_operation_id||op?.client_operation_id||'');
                    state.generations=[result,...state.generations.filter(item=>String(item.run_id)!==String(runId)&&(!operationKey||String(item.client_operation_id||'')!==operationKey))];
                    if(op&&String(op.run_id||'')===String(runId)){op.status=result.status;op.phase=isTerminal(result.status)?'terminal':'accepted';writeOperation(op);}
                    if(result.music&&Number(result.music.revision||0)>=Number(state.music?.revision||0))state.music=result.music;
                    renderGenerationState();if(isTerminal(result.status)){if(isSuccess(result.status)){const done=purpose==='cover'?W().coverDone:W().generationDone;setStatus(result.music_association_error?W().generationAssociationError:done,result.music_association_error?'error':'success');await loadMusic({background:true});}else{notify(`${String(result.status).toLowerCase().includes('cancel')?W().generationCancelled:W().generationFailed}${result.error?` · ${result.error}`:''}`,'error');}return;}
                }catch(error){if(!background)notify(`${W().generationUnknown} ${error.message||''}`,'error');}
                await new Promise(resolve=>setTimeout(resolve,2500));
            }
            if(!background)notify(W().generationUnknown,'error');
        }finally{state.pollingRuns.delete(String(runId));}
    }
    function loadAudio(item,{open=false}={}){
        const url=safeMediaUrl(item);if(!url){notify(W().managedOnly,'error');return false;}
        const audio=$('#musicAudioElement');const wasSame=state.activeAudio?.id&&String(state.activeAudio.id)===String(item.id);state.activeAudio=item;state.activeLyricIndex=-1;
        if(audio.src!==new URL(url,location.origin).href)audio.src=url;
        $('#musicMiniPlayer').hidden=false;$('#musicMiniTitle').textContent=String(item.snapshot?.title||currentTitle());$('#musicMiniMeta').textContent=String(item.name||W().audio);$('#musicPlayerTrackTitle').textContent=String(item.snapshot?.title||currentTitle());$('#musicPlayerTrackMeta').textContent=`${String(item.name||W().audio)} · ${timeLabel(item.created_at)}`;
        renderTimedLyrics(item);
        if(open)$('#musicPlayerDialog').showModal();
        if(!wasSame||audio.paused)audio.play().catch(()=>notify(W().playError,'error'));
        return true;
    }
    function renderTimedLyrics(item){const lines=normalizeTimedLyrics(item?.timed_lyrics);const host=$('#musicTimedLyrics');host.replaceChildren();if(!lines.length){const label=document.createElement('span');label.className='music-lyric-sync-note';label.textContent=W().lyricNotSynced;host.append(label);const lyrics=String(item?.snapshot?.lyrics||'').trim();if(lyrics){const source=document.createElement('pre');source.className='music-static-lyrics';source.textContent=lyrics;host.append(source);}else{const empty=document.createElement('span');empty.textContent=W().noTimedLyrics;host.append(empty);}return;}lines.forEach((line,index)=>{const el=document.createElement('div');el.className='music-lyric-line';el.dataset.lyricIndex=String(index);el.dataset.start=String(line.start);el.textContent=line.text;host.append(el);});}
    function syncPlayer(){const audio=$('#musicAudioElement');const current=Number(audio.currentTime||0),duration=Number(audio.duration||0);const pct=duration>0?Math.round(current/duration*1000):0;$('#musicMiniCurrent').textContent=formatDuration(current);$('#musicMiniDuration').textContent=formatDuration(duration);$('#musicExpandedCurrent').textContent=formatDuration(current);$('#musicExpandedDuration').textContent=formatDuration(duration);$('#musicMiniSeek').value=String(pct);$('#musicExpandedSeek').value=String(pct);const playIcon=audio.paused?'play':'pause';$('#musicMiniToggle').innerHTML=`<i data-lucide="${playIcon}" aria-hidden="true"></i>`;$('#musicExpandedToggle').innerHTML=`<i data-lucide="${playIcon}" aria-hidden="true"></i>`;$('#musicMiniToggle').setAttribute('aria-label',audio.paused?W().play:W().pause);$('#musicExpandedToggle').setAttribute('aria-label',audio.paused?W().play:W().pause);
        const lines=[...$('#musicTimedLyrics').querySelectorAll('.music-lyric-line')];let active=-1;lines.forEach((line,index)=>{const start=Number(line.dataset.start);if(start<=current)active=index;line.classList.toggle('active',index===active);});const lyricChanged=active!==state.activeLyricIndex;state.activeLyricIndex=active;if(lyricChanged&&active>=0&&$('#musicPlayerDialog').open){const activeLine=lines[active],box=$('#musicTimedLyrics');const top=activeLine.offsetTop-box.offsetTop;box.scrollTo({top:Math.max(0,top-box.clientHeight*.45),behavior:'smooth'});}refreshIcons();
    }
    function seekFromRange(range){const audio=$('#musicAudioElement');if(audio.duration>0)audio.currentTime=Number(range.value)/1000*audio.duration;}
    async function downloadRef(item){const url=safeMediaUrl(item);if(!url){notify(W().managedOnly,'error');return;}try{const response=await fetch(url,{credentials:'same-origin'});if(!response.ok)throw await apiError(response);const blob=await response.blob();const objectUrl=URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=objectUrl;anchor.download=fileName(item.name,'music-result');document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(objectUrl),1500);notify(W().downloadStarted);}catch(error){notify(`${W().downloadFailed} ${error.message||''}`,'error');}}
    function bind(){
        $('#musicRefreshButton').addEventListener('click',()=>{void Promise.all([loadMusic(),loadProjectName(),loadGenerationHistory()]);});
        $('#musicLanguageButton').addEventListener('click',()=>window.StudioI18n?.toggle?.());
        $('#musicThemeButton').addEventListener('click',()=>{const appearance=document.documentElement.dataset.studioAppearance||'light';window.StudioTheme?.set?.(appearance==='dark'?'light':'dark');});
        document.querySelector('.music-main').addEventListener('click',event=>{
            const retry=event.target.closest('#musicRetry');if(retry){void loadMusic();return;}
            const tab=event.target.closest('[data-music-tab]');if(tab){setTab(tab.dataset.musicTab);return;}
            const title=event.target.closest('[data-title-id]');if(title){if(title.dataset.titleId)void updateSelection('selected_title_candidate_id',title.dataset.titleId,W().titleAdopted);return;}
            const cover=event.target.closest('[data-cover-id]');if(cover){if(cover.dataset.coverId)void updateSelection('selected_cover_variant_id',cover.dataset.coverId,W().coverSelected);return;}
            const score=event.target.closest('[data-score-id]');if(score){void inspectScore(score.dataset.scoreId);return;}
            const audioButton=event.target.closest('[data-audio-action]');if(audioButton){const item=(state.music?.audio_variants||[]).find(ref=>String(ref.id)===String(audioButton.dataset.audioId));if(!item)return;switch(audioButton.dataset.audioAction){case'play':loadAudio(item);break;case'expand':loadAudio(item,{open:true});break;case'select':void updateSelection('selected_audio_variant_id',String(item.id),W().selected);break;case'download':event.preventDefault();void downloadRef(item);break;}return;}
            const refButton=event.target.closest('[data-reference-play],[data-reference-download]');if(refButton){const id=refButton.dataset.referencePlay||refButton.dataset.referenceDownload;const item=(state.music?.reference_audio_refs||[]).find(ref=>String(ref.id)===String(id));if(!item)return;if(refButton.dataset.referencePlay)loadAudio(item,{open:true});else void downloadRef(item);}
        });
        $('#musicGenerateButton').addEventListener('click',()=>void submitOrRecover({purpose:'song',recover:$('#musicGenerateButton').dataset.recover==='true'}));
        $('#musicGenerateCoverButton').addEventListener('click',()=>void submitOrRecover({purpose:'cover',recover:$('#musicGenerateCoverButton').dataset.recover==='true'}));
        $('#musicMappingSubmit').addEventListener('click',confirmDynamicMappings);$('#musicMappingCancel').addEventListener('click',()=>finishMappingDialog(null));$('#musicMappingClose').addEventListener('click',()=>finishMappingDialog(null));$('#musicMappingDialog').addEventListener('cancel',event=>{event.preventDefault();finishMappingDialog(null);});
        $('#musicMiniToggle').addEventListener('click',()=>{$('#musicAudioElement').paused?$('#musicAudioElement').play().catch(()=>notify(W().playError,'error')):$('#musicAudioElement').pause();});$('#musicExpandedToggle').addEventListener('click',()=>{$('#musicAudioElement').paused?$('#musicAudioElement').play().catch(()=>notify(W().playError,'error')):$('#musicAudioElement').pause();});
        $('#musicMiniSeek').addEventListener('input',event=>seekFromRange(event.currentTarget));$('#musicExpandedSeek').addEventListener('input',event=>seekFromRange(event.currentTarget));$('#musicOpenPlayer').addEventListener('click',()=>{if(state.activeAudio){renderTimedLyrics(state.activeAudio);$('#musicPlayerDialog').showModal();}});$('#musicPlayerClose').addEventListener('click',()=>$('#musicPlayerDialog').close());
        const audio=$('#musicAudioElement');['timeupdate','durationchange','play','pause','ended','loadedmetadata'].forEach(type=>audio.addEventListener(type,syncPlayer));
        window.addEventListener('studio-lang-change',applyLanguage);window.addEventListener('studio-theme-change',()=>{if(state.music)applyLanguage();});
        window.addEventListener('message',event=>{if(event.origin!==location.origin||event.source!==window.parent)return;if(event.data?.type==='studio-lang'&&event.data.lang)window.StudioI18n?.set?.(event.data.lang);if(event.data?.type==='studio-theme')window.StudioTheme?.applyPreference?.(event.data.preference);});
        window.addEventListener('focus',()=>{void Promise.all([loadMusic({background:true}),loadGenerationHistory()]);});document.addEventListener('visibilitychange',()=>{if(!document.hidden){void Promise.all([loadMusic({background:true}),loadGenerationHistory()]);}});
        document.addEventListener('keydown',event=>{if(event.key==='Escape'&&$('#musicPlayerDialog').open)$('#musicPlayerDialog').close();});
    }
    async function initialize(){refreshIcons();bind();if(!projectId){applyLanguage();setStatus(W().missingId,'error');return;}$('#musicProjectName').textContent=W().reading;setStatus(W().load);await Promise.all([loadMusic(),loadProjectName(),loadGenerationHistory()]);state.pollTimer=window.setInterval(()=>{if(!document.hidden){for(const purpose of ['song','cover']){const active=currentGeneration(purpose);if(active?.run_id)void pollGeneration(active.run_id,{background:true});}}},12000);state.refreshTimer=window.setInterval(()=>{if(!document.hidden)void loadMusic({background:true});},25000);}
    initialize();
})();
