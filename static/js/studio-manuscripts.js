/* 剧本与小说工作页：呈现和维护已保存正文，创作由外部 Agent 按用户指令完成。 */
(function(){
    'use strict';
    const module=document.body?.dataset?.manuscriptModule;
    if(!['script','novel'].includes(module))return;
    const isNovel=module==='novel', projectId=new URLSearchParams(location.search).get('id')||'';
    const root='/api/studio/'+(isNovel?'novels':'scripts')+'/'+encodeURIComponent(projectId);
    const state={summary:null,revision:1,selection:{scope:'root',nodeId:''},documentPane:'body',outlineRecord:null,outlineLoading:false,outlineError:false,outlineCountToken:0,blocks:[],cursor:'',settingsIndex:null,settingsCategory:'',setting:null,handoff:null,historyMode:false,settingRevisions:[],handoffRevisions:[],tab:'text',search:'',expanded:new Set(),tabStates:{text:null,settings:null},editor:null,saveTimer:0,saving:false,dirty:false,conflicted:false,inlineDrafts:new Map(),inlineTimer:0,inlineSaving:false,inlinePending:null,inlineComposing:new Set(),optimizationRuns:new Map(),optimizationDialog:null,readerScopeKey:'',requestEpoch:0,syncTimer:0,syncBusy:false,remoteChanged:false,outlineMenu:null,outlineDialog:null,pendingOutlineCommand:null,characterCount:null,characterCountToken:0};
    const $=id=>document.getElementById(id);
    const en=()=>String(window.StudioI18n?.lang?.()||document.documentElement.lang||'zh').toLowerCase().startsWith('en');
    const L=(zh,english)=>en()?english:zh;
    const esc=value=>String(value==null?'':value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const enc=value=>encodeURIComponent(String(value||''));
    const titleOf=item=>String(item?.title||L('未命名','Untitled'));
    const categoryKey=value=>value==null?'uncategorized':String(value);
    const categoryName=item=>{const title=item?.title;if(title&&typeof title==='object')return title[en()?'en':'zh']||title.zh||title.en||L('未命名分类','Untitled category');return String(title||item?.name||L('未命名分类','Untitled category'));};
    function route(path,params){const url=new URL(root+path,location.origin);Object.entries(params||{}).forEach(([key,value])=>{if(value!==''&&value!=null)url.searchParams.set(key,String(value));});return url.pathname+url.search;}
    async function api(path,options){
        const response=await fetch(path,options||{});
        if(!response.ok){let detail='';try{const payload=await response.json();detail=payload?.detail;if(detail&&typeof detail==='object')detail=detail.message||JSON.stringify(detail);}catch(e){}const error=new Error(detail||response.status+' '+response.statusText);error.status=response.status;throw error;}
        return (response.headers.get('content-type')||'').includes('application/json')?response.json():response.text();
    }
    async function sha256Text(value){
        const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(String(value||'')));
        return[...new Uint8Array(digest)].map(byte=>byte.toString(16).padStart(2,'0')).join('');
    }
    const post=(path,body)=>api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    function setStatus(message,kind){const node=$('smStatus');node.textContent=message||'';node.className=('sm-status '+(kind||'')).trim();node.hidden=!message;}
    function setEditorError(message){$('smEditorError').textContent=message||'';$('smEditorError').hidden=!message;$('smRetrySaveButton').hidden=!message||state.conflicted;$('smCopyDraftButton').hidden=!message||!state.conflicted;$('smReloadConflictButton').hidden=!message||!state.conflicted;}
    function setRevision(value){if(Number.isInteger(Number(value))&&Number(value)>0){const next=Number(value);if(next!==state.revision){state.revision=next;state.characterCountToken++;state.characterCount=null;updateCharacterCount();}}}
    function projectName(){return state.summary?.project?.name||L('未命名作品','Untitled work');}
    function icons(){window.lucide?.createIcons?.();}
    function bodyText(){return $('smMarkdownInput').value;}
    const inlineKey=(kind,id)=>kind+':'+String(id||'root');
    const optimizationStorageKey=()=>`studio-manuscript-optimization:${module}:${projectId}`;
    let optimizationStorageLoaded=false;
    function restoreOptimizationRuns(){
        if(optimizationStorageLoaded)return;
        optimizationStorageLoaded=true;
        try{
            const stored=JSON.parse(localStorage.getItem(optimizationStorageKey())||'{}');
            if(!stored||typeof stored!=='object'||Array.isArray(stored))return;
            for(const [key,value] of Object.entries(stored)){
                const body=value?.requestBody,scope=String(value?.scope||''),sourceId=String(value?.sourceId||'');
                if(value?.projectId!==projectId||value?.module!==module||!key||!body||body.scope!==scope||body.source_id!==sourceId
                    ||body.client_operation_id==null||body.expected_source_sha256==null||body.expected_source_revision==null
                    ||!Number.isSafeInteger(Number(body.expected_source_revision)))continue;
                state.optimizationRuns.set(key,{...value,key,sourceBody:'',resultText:'',error:'',pollPromise:null});
            }
        }catch(_){/* A damaged local recovery hint must not block reading the saved work. */}
    }
    function persistOptimizationRun(run){
        if(!run?.key||!run.requestBody)return;
        try{
            restoreOptimizationRuns();
            const stored=JSON.parse(localStorage.getItem(optimizationStorageKey())||'{}');
            stored[run.key]={projectId,module,key:run.key,phase:run.phase,scope:run.scope,sourceId:run.sourceId,
                sourceSha256:run.sourceSha256,sourceObjectSha256:run.sourceObjectSha256,sourceRevision:run.sourceRevision,projectRevision:run.projectRevision,
                outputNodeId:run.outputNodeId,requestBody:run.requestBody,runId:run.runId||'',resultId:run.resultId||'',
                applyRequestId:run.applyRequestId||'',applyRevision:Number.isSafeInteger(Number(run.applyRevision))?Number(run.applyRevision):null,
                applyBlocked:run.applyBlocked===true,sourceChanged:run.sourceChanged===true,applied:run.applied===true};
            const entries=Object.entries(stored).slice(-30);
            localStorage.setItem(optimizationStorageKey(),JSON.stringify(Object.fromEntries(entries)));
        }catch(_){/* Recovery storage is best-effort; the live run remains usable. */}
    }
    function outlineEligible(){return state.tab==='text'&&(isNovel?state.selection.scope==='chapter':state.selection.scope==='episode');}
    function outlineEntry(){return isNovel?findChapter(state.selection.nodeId)?.chapter:(state.summary?.directory?.episodes||[]).find(item=>item.id===state.selection.nodeId);}
    function outlineInlineKey(){return inlineKey(isNovel?'novel-chapter-outline':'script-episode-outline',state.selection.nodeId);}
    function documentScopeKey(){return inlineScopeKey()+'|'+state.documentPane;}
    function inlineHasDirty(){return[...state.inlineDrafts.values()].some(item=>item.dirty||item.conflicted||item.uncertain);}
    function inlineBucket(field){
        restoreOptimizationRuns();
        let item=state.inlineDrafts.get(field.key);
        if(!item){item={...field,savedBody:field.body,value:field.body,dirty:false,conflicted:false,conflictAcknowledged:false,uncertain:false,error:'',remoteBody:null};state.inlineDrafts.set(field.key,item);}
        else{
            item.action=field.action;item.args=field.args;item.label=field.label;item.optimization=field.optimization||null;
            const focused=document.activeElement?.dataset?.inlineKey===field.key;
            if(!item.dirty&&!item.conflicted&&!item.uncertain){
                if(focused&&field.body!==item.savedBody){item.remoteBody=field.body;item.conflicted=true;item.staleOnly=true;item.conflictAcknowledged=false;item.error=L('此正文已在别处更新。为保护新内容，先读取最新正文，再继续编辑。','This text changed elsewhere. Read the latest text before editing to avoid overwriting it.');}
                else{item.savedBody=field.body;item.value=field.body;item.error='';item.remoteBody=null;}
            }
            else if(field.body!==item.savedBody){item.remoteBody=field.body;}
        }
        return item;
    }
    function inlineFieldMarkup(field){
        const item=field,remote=item.remoteBody==null?'':'<details class="sm-inline-remote"><summary>'+esc(L('查看最新保存内容','View latest saved text'))+'</summary><pre>'+esc(item.remoteBody)+'</pre></details>';
        const error=item.error?'<p class="sm-inline-error" role="alert">'+esc(item.error)+'</p>':'';
        const conflict=item.conflicted?(item.dirty?'<button class="sm-inline-action" type="button" data-inline-confirm="'+esc(item.key)+'">'+esc(L('对照后保存这份草稿','Save this draft after review'))+'</button><button class="sm-inline-action" type="button" data-inline-copy="'+esc(item.key)+'">'+esc(L('复制草稿','Copy draft'))+'</button>':'<button class="sm-inline-action" type="button" data-inline-reload="'+esc(item.key)+'">'+esc(L('读取最新正文','Load latest text'))+'</button>'):'';
        const retry=item.uncertain||item.error&&!item.conflicted?'<button class="sm-inline-action" type="button" data-inline-retry="'+esc(item.key)+'">'+esc(L('重试保存','Retry save'))+'</button>':'';
        const stateVisible=item.saving||item.dirty||item.error||item.conflicted||item.uncertain;
        const status=item.saving?L('正在保存…','Saving…'):item.conflicted?L('需要核对','Review needed'):item.error||item.uncertain?L('未保存','Not saved'):L('未保存','Unsaved');
        const feedback=stateVisible?'<div class="sm-inline-feedback"><span class="sm-inline-state" data-inline-state="'+esc(item.key)+'" role="status" aria-live="polite">'+esc(status)+'</span>'+retry+conflict+'</div>':'';
        const optimization=optimizationFieldMarkup(item);
        return '<div class="sm-inline-field" data-inline-field="'+esc(item.key)+'"><label class="sm-sr-only" for="smInline_'+esc(item.key)+'">'+esc(field.label||L('正文','Text'))+'</label><textarea class="sm-markdown-input sm-inline-input" id="smInline_'+esc(item.key)+'" data-inline-key="'+esc(item.key)+'" spellcheck="false" autocapitalize="off" aria-label="'+esc(field.label||L('正文','Text'))+'">'+esc(item.value)+'</textarea>'+optimization+feedback+error+remote+'</div>';
    }
    function optimizationStatusText(run){
        if(!run)return'';
        if(run.phase==='submitting'||run.phase==='running')return L('正在优化…','Optimizing…');
        if(run.phase==='uncertain')return L('结果待确认，可恢复同一任务。','Result not confirmed. Recover the same task.');
        if(run.phase==='preview')return L('已有优化结果','Optimization ready');
        if(run.phase==='applying')return L('正在采用…','Applying…');
        if(run.phase==='apply-uncertain')return L('采用状态待确认，可恢复同一请求。','Adoption not confirmed. Recover the same request.');
        if(run.phase==='applied')return L('已采用','Applied');
        if(run.phase==='error')return run.error||L('优化失败','Optimization failed');
        return'';
    }
    function optimizationFieldMarkup(item){
        if(!item.optimization)return'';
        const run=state.optimizationRuns.get(item.key),disabled=item.value.trim()===''&&!item.dirty;
        const label=run?.phase==='preview'?L('查看优化结果','View result'):L('文本优化','Optimize text');
        const stateText=optimizationStatusText(run);
        return '<div class="sm-inline-tools"><button class="sm-inline-action sm-inline-optimize" type="button" data-inline-optimize="'+esc(item.key)+'"'+(disabled?' disabled':'')+'>'+esc(label)+'</button><span class="sm-inline-optimize-state" data-inline-optimize-state="'+esc(item.key)+'" role="status" aria-live="polite">'+esc(stateText)+'</span></div>';
    }
    function updateGlobalInlineState(){
        const items=[...state.inlineDrafts.values()],active=items.some(item=>item.dirty||item.saving||item.error||item.conflicted||item.uncertain);
        $('smRevisionLabel').textContent=state.inlineSaving?L('正在保存…','Saving…'):items.some(item=>item.error||item.conflicted||item.uncertain)?L('未保存','Not saved'):items.some(item=>item.dirty)?L('未保存','Unsaved'):L('已保存','Saved');
        if(!active&&!state.inlineSaving)$('smRevisionLabel').textContent=L('已保存','Saved');
    }
    function updateInlineFieldNode(key){
        const item=state.inlineDrafts.get(key),field=[...$('smReader').querySelectorAll('.sm-inline-field')].find(node=>node.dataset.inlineField===key);
        if(!item||!field)return;
        const input=field.querySelector('.sm-inline-input');
        if(input&&document.activeElement!==input&&!item.dirty&&!item.conflicted&&!item.uncertain)input.value=item.value;
        const stateNode=field.querySelector('[data-inline-state]');if(stateNode)stateNode.textContent=item.saving?L('正在保存…','Saving…'):item.conflicted?L('需要核对','Review needed'):L('未保存','Unsaved');
        let actions=field.querySelector('.sm-inline-feedback');
        const template=document.createElement('template');template.innerHTML=inlineFieldMarkup(item);
        const fresh=template.content.firstElementChild;
        const freshActions=fresh.querySelector('.sm-inline-feedback');
        if(actions&&freshActions)actions.replaceWith(freshActions);else if(actions&&!freshActions)actions.remove();else if(!actions&&freshActions)field.querySelector('.sm-inline-input')?.after(freshActions);
        const oldError=field.querySelector('.sm-inline-error'),newError=fresh.querySelector('.sm-inline-error');if(oldError)oldError.remove();if(newError)field.append(newError);
        const oldRemote=field.querySelector('.sm-inline-remote'),newRemote=fresh.querySelector('.sm-inline-remote');if(oldRemote)oldRemote.remove();if(newRemote)field.append(newRemote);
        const oldOptimization=field.querySelector('.sm-inline-tools'),newOptimization=fresh.querySelector('.sm-inline-tools');if(oldOptimization&&newOptimization)oldOptimization.replaceWith(newOptimization);else if(oldOptimization&&!newOptimization)oldOptimization.remove();else if(!oldOptimization&&newOptimization)field.querySelector('.sm-inline-input')?.after(newOptimization);
        updateGlobalInlineState();
        updateCharacterCount();
    }
    function installInlineFields(fields,emptyHtml,append,scopeKey){
        const reader=$('smReader'),same=state.readerScopeKey===scopeKey;
        if(!append&&!same){reader.replaceChildren();state.readerScopeKey=scopeKey;}
        const existing=new Map([...reader.querySelectorAll('.sm-inline-field')].map(node=>[node.dataset.inlineField,node]));
        const wanted=[];
        for(const field of fields){
            const item=inlineBucket(field);wanted.push(item.key);
            const previous=existing.get(item.key);
            if(previous){
                const input=previous.querySelector('.sm-inline-input');
                if(input&&document.activeElement!==input&&!item.dirty&&!item.conflicted&&!item.uncertain)input.value=item.value;
                updateInlineFieldNode(item.key);
            }else{
                const template=document.createElement('template');template.innerHTML=inlineFieldMarkup(item);
                const node=template.content.firstElementChild;if(node)reader.append(node);
            }
        }
        if(!fields.length&&!append&&!reader.querySelector('.sm-inline-field')){reader.innerHTML=emptyHtml;state.readerScopeKey=scopeKey;return;}
        if(!append&&same){
            for(const [key,node] of existing)if(!wanted.includes(key))node.remove();
            const current=[...reader.querySelectorAll('.sm-inline-field')].map(node=>node.dataset.inlineField);
            if(current.length!==wanted.length||current.some((key,index)=>key!==wanted[index])){
                const nodes=new Map([...reader.querySelectorAll('.sm-inline-field')].map(node=>[node.dataset.inlineField,node]));
                for(const key of wanted){const node=nodes.get(key);if(node)reader.append(node);}
            }
        }
    }
    function inlineFieldsForBlocks(blocks){
        const s=state.selection;
        if(!isNovel){
            if(s.scope==='segment'){
                const block=blocks[0];return block?[{key:inlineKey('script-segment',s.nodeId),action:'replace_segment_text',args:{segment_id:s.nodeId},body:block.body_markdown||'',label:outlineDisplayTitle('segment',outlineItem('segment',s.nodeId)),optimization:{scope:'segment',sourceId:s.nodeId,sourceSha256:block.source_sha256||''}}]:[];
            }
            if(s.scope==='root'&&state.summary?.state==='draft'){
                const body=blocks[0]?.body_markdown||state.summary?.draft||'';
                return[{key:inlineKey('script-draft','root'),action:'set_draft',args:{},body,label:L('完整剧本正文','Full script text')}];
            }
            return blocks.map(block=>({key:inlineKey('script-scene',block.id),action:'update_scene',args:{scene_id:block.id},body:block.editable_markdown??block.body_markdown??'',label:titleOf(block),optimization:{scope:'scene',sourceId:block.id,sourceSha256:block.content_sha256||''}}));
        }
        return blocks.map(block=>({key:inlineKey('novel-chapter',block.id),action:'update_chapter',args:{chapter_id:block.id},body:block.body_markdown||'',label:titleOf(block),optimization:{scope:'chapter',sourceId:block.id,sourceSha256:block.content_sha256||''}}));
    }
    function inlineScopeKey(){return module+'|'+state.tab+'|'+state.selection.scope+'|'+state.selection.nodeId;}
    function inlineEmptyText(){
        if(isNovel)return empty(L('正文还没有保存','No saved text'),L('当前范围还没有章节正文。可从目录中新建章节。','There is no chapter text in this scope yet. Add a chapter from the outline.'));
        return empty(L('尚无剧本正文','No script text'),L('当前范围还没有场次正文。可从目录中新建场次。','There is no scene text in this scope yet. Add a scene from the outline.'));
    }
    function queryState(){return matchMedia('(max-width: 1020px)').matches;}

    /* 只生成受控标签；原始 HTML 一律作为文字显示。 */
    function safeLink(raw){
        const value=String(raw||'').trim();
        if(!value||/[\u0000-\u001f\\]/.test(value))return '';
        try{const url=new URL(value,location.href);if(!['http:','https:'].includes(url.protocol))return '';if(!/^(https?:\/\/|\/|#)/i.test(value))return '';return url.href;}catch(e){return '';}
    }
    function inlineMarkdown(value){
        let text=esc(value),tokens=[];
        const stash=html=>{const key='\u0000'+tokens.length+'\u0000';tokens.push(html);return key;};
        text=text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g,(_m,alt,url)=>{const href=safeLink(url);return href?stash('<a class="sm-markdown-image" href="'+esc(href)+'" target="_blank" rel="noopener noreferrer">'+esc(alt||url)+'</a>'):esc(alt||url);});
        text=text.replace(/\[([^\]]+)\]\(([^)]+)\)/g,(_m,label,url)=>{const href=safeLink(url);return href?stash('<a href="'+esc(href)+'" target="_blank" rel="noopener noreferrer">'+inlineMarkdown(label)+'</a>'):esc(label);});
        text=text.replace(/\x60([^\x60]+)\x60/g,(_m,code)=>stash('<code>'+code+'</code>'));
        text=text.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/__([^_]+)__/g,'<strong>$1</strong>');
        text=text.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g,'$1<em>$2</em>').replace(/(^|[^_])_([^_]+)_(?!_)/g,'$1<em>$2</em>');
        text=text.replace(/~~([^~]+)~~/g,'<del>$1</del>');
        return text.replace(/\u0000(\d+)\u0000/g,(_m,index)=>tokens[Number(index)]||'');
    }
    function markdown(markdownText){
        const lines=String(markdownText||'').replace(/\r\n?/g,'\n').split('\n'),out=[];
        let paragraph=[],listType='',listItems=[],quote=[],code=[],inCode=false;
        const flushP=()=>{if(paragraph.length){out.push('<p>'+paragraph.map(inlineMarkdown).join('<br>')+'</p>');paragraph=[];}};
        const flushL=()=>{if(listType){out.push('<'+listType+'>'+listItems.map(item=>'<li>'+inlineMarkdown(item)+'</li>').join('')+'</'+listType+'>');listType='';listItems=[];}};
        const flushQ=()=>{if(quote.length){out.push('<blockquote><p>'+quote.map(inlineMarkdown).join('<br>')+'</p></blockquote>');quote=[];}};
        const cells=line=>line.trim().replace(/^\|/,'').replace(/\|$/,'').split(/(?<!\\)\|/).map(cell=>cell.replace(/\\\|/g,'|').trim());
        const tableDivider=line=>cells(line).length>1&&cells(line).every(cell=>/^:?-{3,}:?$/.test(cell));
        for(let i=0;i<lines.length;i++){
            const line=lines[i];
            if(inCode){if(/^\s*\x60\x60\x60/.test(line)){out.push('<pre><code>'+esc(code.join('\n'))+'</code></pre>');code=[];inCode=false;}else code.push(line);continue;}
            if(/^\s*\x60\x60\x60/.test(line)){flushP();flushL();flushQ();inCode=true;continue;}
            if(line.includes('|')&&i+1<lines.length&&tableDivider(lines[i+1])){
                flushP();flushL();flushQ();
                const headings=cells(line),alignments=cells(lines[++i]).map(cell=>cell.startsWith(':')&&cell.endsWith(':')?'center':cell.endsWith(':')?'right':cell.startsWith(':')?'left':'');
                const makeRow=(row,tag)=>'<tr>'+headings.map((_cell,index)=>'<'+tag+(alignments[index]?' style="text-align:'+alignments[index]+'"':'')+'>'+(row[index]!==undefined?inlineMarkdown(row[index]):'')+'</'+tag+'>').join('')+'</tr>';
                const head='<thead>'+makeRow(headings,'th')+'</thead>',rows=[];
                while(i+1<lines.length&&lines[i+1].includes('|'))rows.push(makeRow(cells(lines[++i]),'td'));
                out.push('<div class="sm-table-scroll"><table>'+head+'<tbody>'+rows.join('')+'</tbody></table></div>');continue;
            }
            const heading=line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
            if(heading){flushP();flushL();flushQ();const level=heading[1].length;out.push('<h'+level+'>'+inlineMarkdown(heading[2])+'</h'+level+'>');continue;}
            if(/^\s{0,3}(?:---+|\*\*\*+|___+)\s*$/.test(line)){flushP();flushL();flushQ();out.push('<hr>');continue;}
            const quoteLine=line.match(/^\s{0,3}>\s?(.*)$/);
            if(quoteLine){flushP();flushL();quote.push(quoteLine[1]);continue;}else flushQ();
            const list=line.match(/^\s{0,3}([-*+] |\d+[.)] )(.*)$/);
            if(list){flushP();const next=/^\d/.test(list[1])?'ol':'ul';if(listType!==next){flushL();listType=next;}listItems.push(list[2]);continue;}else flushL();
            if(!line.trim()){flushP();continue;}paragraph.push(line);
        }
        if(inCode)out.push('<pre><code>'+esc(code.join('\n'))+'</code></pre>');
        flushP();flushL();flushQ();
        return '<div class="sm-markdown">'+out.join('')+'</div>';
    }
    function markdownTextForCharacterCount(markdownText){
        const template=document.createElement('template');template.innerHTML=markdown(markdownText);
        template.content.querySelectorAll('.sm-markdown-image').forEach(node=>node.remove());
        return template.content.textContent||'';
    }
    function markdownCharacterCount(markdownText){return(markdownTextForCharacterCount(markdownText).match(/[\p{L}\p{N}]/gu)||[]).length;}
    function updateDocumentPaneTabs(){
        const nav=$('smDocumentTabs');if(!nav)return;
        const visible=outlineEligible();nav.hidden=!visible;
        if(!visible&&state.documentPane==='outline')state.documentPane='body';
        for(const button of nav.querySelectorAll('[data-document-pane]')){
            const active=button.dataset.documentPane===state.documentPane;
            button.classList.toggle('active',active);button.setAttribute('aria-selected',active?'true':'false');button.tabIndex=active?0:-1;
        }
        $('smReader')?.setAttribute('aria-labelledby',state.documentPane==='outline'?'smDocumentTabOutline':'smDocumentTabBody');
        if(state.documentPane==='outline')$('smLoadMoreButton').hidden=true;
    }
    function updateOutlineCharacterCount(){
        const node=$('smCharacterCount');if(!node)return;
        node.hidden=!outlineEligible()||state.documentPane!=='outline';
        node.title=L('统计章纲中的 Unicode 字母和数字；不计标点、空白、Markdown 语法或图片说明。','Counts Unicode letters and numbers in the outline; excludes punctuation, whitespace, Markdown syntax, and image alt text.');
        if(node.hidden)return;
        const record=state.outlineRecord,key=outlineInlineKey(),draft=state.inlineDrafts.get(key);
        if(draft){node.textContent=L('字符数：'+markdownCharacterCount(draft.value),'Characters: '+markdownCharacterCount(draft.value));return;}
        if(state.outlineLoading){node.textContent=L('字符数：统计中…','Characters: counting…');return;}
        if(state.outlineError||!record){node.textContent=L('字符数：暂不可用','Characters: unavailable');return;}
        node.textContent=L('字符数：'+markdownCharacterCount(record.outline_markdown||''),'Characters: '+markdownCharacterCount(record.outline_markdown||''));
    }
    function characterCountKey(block){
        const selection=state.selection;
        if(isNovel)return inlineKey('novel-chapter',block.id);
        if(selection.scope==='segment')return inlineKey('script-segment',selection.nodeId);
        if(selection.scope==='root'&&state.summary?.state==='draft')return inlineKey('script-draft','root');
        return inlineKey('script-scene',block.id);
    }
    function updateCharacterCount(){
        const node=$('smCharacterCount');if(!node)return;
        if(state.documentPane==='outline'&&outlineEligible()){updateOutlineCharacterCount();return;}
        node.hidden=state.tab!=='text';
        node.title=L('统计正文中 Unicode 字母和数字；不计标点、空白、Markdown 语法或图片说明。','Counts Unicode letters and numbers in body text; excludes punctuation, whitespace, Markdown syntax, and image alt text.');
        if(state.tab!=='text')return;
        const snapshot=state.characterCount;
        if(!snapshot||snapshot.scopeKey!==inlineScopeKey()||snapshot.revision!==state.revision||snapshot.error){node.textContent=L('字符数：暂不可用','Characters: unavailable');return;}
        if(snapshot.loading){node.textContent=L('字符数：统计中…','Characters: counting…');return;}
        let total=snapshot.total;
        const visible=new Set([...$('smReader').querySelectorAll('.sm-inline-input')].map(input=>input.dataset.inlineKey));
        for(const [key,baseCount] of snapshot.counts){
            const item=state.inlineDrafts.get(key),focused=document.activeElement?.dataset?.inlineKey===key;
            if(item&&(visible.has(key)||focused||item.dirty||item.saving||item.conflicted||item.uncertain))total+=markdownCharacterCount(item.value)-baseCount;
        }
        node.textContent=L('字符数：'+total,'Characters: '+total);
    }
    function beginCharacterCount(){
        const scope={scope:state.selection.scope,nodeId:state.selection.nodeId};
        state.characterCountToken++;
        state.characterCount={scopeKey:module+'|text|'+scope.scope+'|'+scope.nodeId,revision:state.revision,loading:true,error:false};
        updateCharacterCount();
    }
    function ensureCharacterCount(){
        if(state.tab!=='text')return updateCharacterCount();
        const scopeKey=inlineScopeKey(),snapshot=state.characterCount;
        if(snapshot&&snapshot.scopeKey===scopeKey&&snapshot.revision===state.revision&&!snapshot.error){updateCharacterCount();return;}
        void loadCharacterCount(state.blocks,state.cursor,Boolean(state.cursor),state.revision,{scope:state.selection.scope,nodeId:state.selection.nodeId});
    }
    async function loadCharacterCount(blocks,cursor,hasMore,revision,scope){
        const token=++state.characterCountToken,scopeKey=module+'|text|'+scope.scope+'|'+scope.nodeId;
        const snapshot={scopeKey,revision:Number(revision),loading:true,error:false};
        const collected=blocks.slice();
        state.characterCount=snapshot;updateCharacterCount();
        const isCurrent=()=>token===state.characterCountToken&&scopeKey===inlineScopeKey()&&state.tab==='text'&&state.revision===snapshot.revision;
        try{
            let next=cursor||'';
            const seenCursors=new Set();
            if(hasMore&&!next)throw new Error('missing next page cursor');
            const params={scope:scope.scope,node_id:scope.nodeId,limit:30};
            while(next){
                if(!isCurrent())return;
                if(seenCursors.has(next))throw new Error('repeated page cursor');
                seenCursors.add(next);
                const data=await api(route('/view',{...params,cursor:next}),{cache:'no-store'});
                if(token!==state.characterCountToken||scopeKey!==inlineScopeKey()||state.tab!=='text')return;
                if(Number(data.revision)!==snapshot.revision||state.revision!==snapshot.revision||data.project_id!==projectId||data.scope!==scope.scope){
                    if(token===state.characterCountToken){state.characterCount={...snapshot,blocks:[],loading:false,error:true};updateCharacterCount();}
                    return;
                }
                collected.push(...(data.blocks||[]));
                next=data.next_cursor||'';
                if(data.has_more&&!next)throw new Error('missing next page cursor');
            }
            if(!isCurrent())return;
            snapshot.counts=new Map();
            for(const block of collected){const key=characterCountKey(block);snapshot.counts.set(key,markdownCharacterCount(block.body_markdown||''));}
            snapshot.total=[...snapshot.counts.values()].reduce((sum,count)=>sum+count,0);
            snapshot.loading=false;state.characterCount=snapshot;updateCharacterCount();
        }catch(_error){
            if(token!==state.characterCountToken||scopeKey!==inlineScopeKey()||state.tab!=='text')return;
            state.characterCount={...snapshot,blocks:[],loading:false,error:true};updateCharacterCount();
        }
    }
    function empty(title,hint){return '<div class="sm-empty-state"><strong>'+esc(title)+'</strong><p>'+esc(hint||'')+'</p></div>';}

    function findScene(id){
        for(const episode of state.summary?.directory?.episodes||[])for(const scene of episode.scenes||[])if(scene.id===id||(scene.segments||[]).some(item=>item.id===id))return{episode,scene};
        return null;
    }
    function findChapter(id){
        for(const volume of state.summary?.directory?.volumes||[])for(const chapter of volume.chapters||[])if(chapter.id===id)return{volume,chapter};
        return null;
    }
    function treeButton(scope,id,title,icon,current,level){
        return '<button class="sm-tree-select" type="button" data-scope="'+esc(scope)+'" data-node-id="'+esc(id||'')+'" style="--sm-depth:'+Number(level||0)+'" '+(current?'aria-current="page"':'')+'><i data-lucide="'+icon+'" aria-hidden="true"></i><span>'+esc(title)+'</span></button>';
    }
    function matches(list){const query=state.search.trim().toLocaleLowerCase();return !query?list:(list||[]).filter(item=>titleOf(item).toLocaleLowerCase().includes(query));}
    function outlineMenuActions(scope){
        if(scope==='episode')return[['scene-child','plus','添加场次','Add scene'],['episode-sibling','copy-plus','添加同级集','Add episode at same level'],['rename','pencil','重命名集','Rename episode'],['delete','trash-2','删除集','Delete episode']];
        if(scope==='scene')return[['segment-child','plus','添加片段','Add segment'],['scene-sibling','copy-plus','添加同级场','Add scene at same level'],['rename','pencil','重命名场','Rename scene'],['delete','trash-2','删除场','Delete scene']];
        if(scope==='segment')return[['segment-sibling','copy-plus','添加同级片段','Add segment at same level'],['delete','trash-2','删除片段','Delete segment']];
        if(scope==='volume')return[['chapter-child','plus','添加章节','Add chapter'],['volume-sibling','copy-plus','添加同级卷','Add volume at same level'],['rename','pencil','重命名卷','Rename volume'],['delete','trash-2','删除卷','Delete volume']];
        if(scope==='chapter')return[['chapter-sibling','copy-plus','添加同级章节','Add chapter at same level'],['rename','pencil','重命名章节','Rename chapter'],['delete','trash-2','删除章节','Delete chapter']];
        return[];
    }
    function outlineDisplayTitle(scope,item){
        if(scope==='segment'&&item){
            const found=findScene(item.id),index=found?.scene?.segments?.findIndex(segment=>segment.id===item.id)??-1;
            if(index>=0)return L('第'+(index+1)+'段','Segment '+(index+1));
        }
        return titleOf(item);
    }
    function outlineMenuMarkup(scope,id){
        const open=state.outlineMenu?.scope===scope&&state.outlineMenu?.id===id,actions=outlineMenuActions(scope);
        const menu=open?'<div class="sm-outline-menu'+(state.outlineMenu?.above?' is-above':'')+'" role="menu" aria-label="'+esc(L('目录操作','Outline actions'))+'">'+actions.map(([action,icon,zh,en])=>'<button class="sm-outline-menu-item" type="button" role="menuitem" data-outline-menu-action="'+action+'" data-outline-scope="'+esc(scope)+'" data-outline-node-id="'+esc(id)+'"><i data-lucide="'+icon+'" aria-hidden="true"></i><span>'+esc(L(zh,en))+'</span></button>').join('')+'</div>':'';
        const item=outlineItem(scope,id),displayTitle=outlineDisplayTitle(scope,item),label=L(displayTitle+'操作',displayTitle+' actions');
        return '<button class="sm-outline-menu-toggle" type="button" data-outline-menu-toggle data-outline-scope="'+esc(scope)+'" data-outline-node-id="'+esc(id)+'" aria-haspopup="menu" aria-expanded="'+(open?'true':'false')+'" aria-label="'+esc(label)+'"><i data-lucide="ellipsis" aria-hidden="true"></i></button>'+menu;
    }
    function outlineRow(scope,item,icon,current,level,disclosure){
        const id=item.id,open=state.expanded.has(id);
        const disclosureMarkup=disclosure?'<button class="sm-tree-disclosure" type="button" data-expand="'+esc(id)+'" aria-expanded="'+(open?'true':'false')+'" aria-label="'+esc(open?L('收起','Collapse'):L('展开','Expand'))+'"><i data-lucide="chevron-right" aria-hidden="true"></i></button>':'';
        return '<div class="sm-tree-row">'+disclosureMarkup+treeButton(scope,id,outlineDisplayTitle(scope,item),icon,current,level)+outlineMenuMarkup(scope,id)+'</div>';
    }
    function renderOutlineDirectory(){
        const nav=$('smDirectory');if(!nav)return;
        if(!isNovel){
            const episodes=state.summary?.directory?.episodes||[];
            let html=treeButton('root','',L('完整剧本','Full script'),'scroll-text',state.selection.scope==='root',0);
            for(const episode of matches(episodes)){
                const open=state.expanded.has(episode.id), scenes=matches(episode.scenes||[]);
                html+='<div class="sm-tree-group">'+outlineRow('episode',episode,'clapperboard',state.selection.scope==='episode'&&state.selection.nodeId===episode.id,0,true);
                if(open){html+='<div class="sm-tree-children">';if(!scenes.length)html+='<p class="sm-tree-empty">'+esc(L('暂无场次','No scenes'))+'</p>';
                    for(const scene of scenes){const sceneOpen=state.expanded.has(scene.id),segments=matches(scene.segments||[]);html+='<div class="sm-tree-group sm-tree-nested-group">'+outlineRow('scene',scene,'clapperboard',state.selection.scope==='scene'&&state.selection.nodeId===scene.id,1,true);if(sceneOpen){html+='<div class="sm-tree-children">';if(!segments.length)html+='<p class="sm-tree-empty">'+esc(L('暂无片段','No segments'))+'</p>';for(const segment of segments)html+=outlineRow('segment',segment,'text',state.selection.scope==='segment'&&state.selection.nodeId===segment.id,2,false);html+='</div>';}
                    html+='</div>';}
                    html+='</div>';}
                html+='</div>';
            }
            if(!episodes.length)html+='<p class="sm-tree-empty">'+esc(L('尚未整理集场目录。完整剧本仍可保存在根目录。','No episode outline yet. The full script can remain at the root.'))+'</p>';
            nav.innerHTML=html;
        }else{
            const volumes=state.summary?.directory?.volumes||[];
            let html=treeButton('root','',L('全书','Whole novel'),'library-big',state.selection.scope==='root',0);
            for(const volume of matches(volumes)){
                const open=state.expanded.has(volume.id), chapters=matches(volume.chapters||[]);
                html+='<div class="sm-tree-group">'+outlineRow('volume',volume,'book-marked',state.selection.scope==='volume'&&state.selection.nodeId===volume.id,0,true);
                if(open){html+='<div class="sm-tree-children">';if(!chapters.length)html+='<p class="sm-tree-empty">'+esc(L('此卷还没有章节','No chapters in this volume'))+'</p>';for(const chapter of chapters)html+=outlineRow('chapter',chapter,'file-text',state.selection.scope==='chapter'&&state.selection.nodeId===chapter.id,1,false);html+='</div>';}
                html+='</div>';
            }
            if(!volumes.length)html+='<p class="sm-tree-empty">'+esc(L('尚无卷章目录。','No volume or chapter outline yet.'))+'</p>';
            nav.innerHTML=html;
        }
        icons();
    }
    function renderSettingsDirectory(){
        const nav=$('smDirectory');if(!nav)return;
        const categories=state.settingsIndex?.categories||[],entries=state.settingsIndex?.entries||[];
        const query=state.search.trim().toLocaleLowerCase();
        const categoryHtml=categories.map(category=>{
            const key=categoryKey(category.id),name=categoryName(category);
            const relevant=entries.filter(entry=>categoryKey(entry.category_id)===key);
            if(query&&!name.toLocaleLowerCase().includes(query)&&!relevant.some(entry=>titleOf(entry).toLocaleLowerCase().includes(query)))return'';
            return '<button class="sm-category-select" type="button" data-category-id="'+esc(key)+'" '+(key===state.settingsCategory&&!state.setting&&!state.handoff?'aria-current="page"':'')+'><i data-lucide="folder" aria-hidden="true"></i><span>'+esc(name)+'</span></button>';
        }).join('');
        const shownCategories=state.settingsCategory?categories.filter(item=>categoryKey(item.id)===state.settingsCategory):categories;
        const entryHtml=shownCategories.map(category=>{
            const key=categoryKey(category.id),rows=entries.filter(entry=>categoryKey(entry.category_id)===key&&(!query||titleOf(entry).toLocaleLowerCase().includes(query)));
            if(!rows.length)return '';
            return '<section class="sm-settings-category-group"><h3>'+esc(categoryName(category))+'</h3>'+rows.map(entry=>'<button class="sm-setting-select" type="button" data-setting-id="'+esc(entry.id)+'" '+(state.setting?.entry?.id===entry.id?'aria-current="page"':'')+'><i data-lucide="file-text" aria-hidden="true"></i><span>'+esc(titleOf(entry))+'</span></button>').join('')+'</section>';
        }).join('');
        let html='<div class="sm-tree-group"><button class="sm-category-select" type="button" data-category-id="" '+(!state.settingsCategory&&!state.setting&&!state.handoff?'aria-current="page"':'')+'><i data-lucide="library-big" aria-hidden="true"></i><span>'+esc(L('全部设定','All settings'))+'</span></button>'+categoryHtml+'</div><div class="sm-settings-entry-list">'+entryHtml;
        if(state.settingsIndex?.has_more)html+='<button type="button" class="sm-load-more sm-settings-more" data-action="settings-more">'+esc(L('继续加载条目','Load more entries'))+'</button>';
        if(!entryHtml&&!state.settingsIndex?.has_more)html+='<p class="sm-tree-empty">'+esc(query?L('没有匹配的条目','No matching entries'):L('此分类还没有设定条目','No entries in this category'))+'</p>';
        html+='</div><div class="sm-tree-group sm-handoff-group"><button class="sm-category-select" type="button" data-action="handoff" '+(state.handoff?'aria-current="page"':'')+'><i data-lucide="notebook-tabs" aria-hidden="true"></i><span>'+esc(L('创作记录','Handoff note'))+'</span></button></div>';
        nav.innerHTML=html;icons();
    }
    function renderDirectory(){
        $('smDirectoryTitle').textContent=state.tab==='settings'?L('设定库目录','Settings'):L(isNovel?'小说目录':'剧本目录',isNovel?'Novel outline':'Script outline');
        $('smDirectory').setAttribute('aria-label',state.tab==='settings'?L('设定库目录','Settings directory'):L(isNovel?'小说目录':'剧本目录',isNovel?'Novel outline':'Script outline'));
        $('smDirectorySearch').placeholder=L('搜索目录标题','Search titles');$('smDirectorySearch').setAttribute('aria-label',L('搜索目录标题','Search titles'));
        const rootAdd=$('smOutlineRootAdd');if(rootAdd){rootAdd.hidden=state.tab==='settings';rootAdd.querySelector('span').textContent=L(isNovel?'新增卷':'新增集',isNovel?'Add volume':'Add episode');rootAdd.setAttribute('aria-label',L(isNovel?'新增卷':'新增集',isNovel?'Add volume':'Add episode'));}
        if(state.tab==='settings')renderSettingsDirectory();else renderOutlineDirectory();
        $('smDirectoryFooter').textContent='';
    }
    function outlineItem(scope,id){
        if(scope==='episode')return(state.summary?.directory?.episodes||[]).find(item=>item.id===id)||null;
        if(scope==='scene')return findScene(id)?.scene||null;
        if(scope==='segment')return findScene(id)?.scene?.segments?.find(item=>item.id===id)||null;
        if(scope==='volume')return(state.summary?.directory?.volumes||[]).find(item=>item.id===id)||null;
        if(scope==='chapter')return findChapter(id)?.chapter||null;
        return null;
    }
    function outlineDefaultName(kind,parentId){
        let count=0;
        if(kind==='episode')count=state.summary?.directory?.episodes?.length||0;
        else if(kind==='scene')count=outlineItem('episode',parentId)?.scenes?.length||0;
        else if(kind==='segment')count=findScene(parentId)?.scene?.segments?.length||0;
        else if(kind==='volume')count=state.summary?.directory?.volumes?.length||0;
        else if(kind==='chapter')count=outlineItem('volume',parentId)?.chapters?.length||0;
        const number=count+1;
        if(kind==='episode')return L('第'+number+'集','Episode '+number);
        if(kind==='scene')return L('第'+number+'场','Scene '+number);
        if(kind==='segment')return L('第'+number+'段','Segment '+number);
        if(kind==='volume')return L('第'+number+'卷','Volume '+number);
        return L('第'+number+'章','Chapter '+number);
    }
    function outlineKindLabel(kind){
        const labels={episode:['集','episode'],scene:['场','scene'],segment:['片段','segment'],volume:['卷','volume'],chapter:['章','chapter']};
        return labels[kind]?.[en()?1:0]||kind;
    }
    function outlineDialogDescriptor(action,scope,id){
        const item=outlineItem(scope,id),foundScene=scope==='scene'||scope==='segment'?findScene(id):null,foundChapter=scope==='chapter'?findChapter(id):null;
        if(action==='delete'){
            if(!item)return null;
            let selectedScope='root',selectedId='',includeDescendants=false,counts={};
            if(scope==='episode'){
                const scenes=item.scenes||[];counts={episodes:1,scenes:scenes.length,segments:scenes.reduce((sum,scene)=>sum+(scene.segments||[]).length,0)};
                includeDescendants=true;
            }else if(scope==='scene'){
                counts={scenes:1,segments:(item.segments||[]).length};selectedScope='episode';selectedId=foundScene?.episode?.id||'';includeDescendants=true;
            }else if(scope==='segment'){
                counts={segments:1};selectedScope='scene';selectedId=foundScene?.scene?.id||'';
            }else if(scope==='volume'){
                counts={volumes:1,chapters:(item.chapters||[]).length};includeDescendants=true;
            }else if(scope==='chapter'){
                counts={chapters:1};selectedScope='volume';selectedId=foundChapter?.volume?.id||'';
            }else return null;
            const englishCounts=[['episodes','episode','episodes'],['scenes','scene','scenes'],['segments','segment','segments'],['volumes','volume','volumes'],['chapters','chapter','chapters']]
                .filter(([key])=>Number(counts[key])>0)
                .map(([key,singular,plural])=>counts[key]+' '+(counts[key]===1?singular:plural)).join(', ');
            const chineseCounts=[['episodes','集'],['scenes','场'],['segments','段'],['volumes','卷'],['chapters','章']]
                .filter(([key])=>Number(counts[key])>0).map(([key,label])=>counts[key]+label).join('、');
            const displayTitle=outlineDisplayTitle(scope,item);
            const hasDescendants=(scope==='episode'&&Number(counts.scenes)>0)||(scope==='scene'&&Number(counts.segments)>0)||(scope==='volume'&&Number(counts.chapters)>0);
            const message=en()
                ?'Delete “'+displayTitle+'”'+(hasDescendants?' and its descendants':'')+' ('+englishCounts+')? Text will be removed from this work; archived history will remain. Imported canvas content will remain.'
                :'确定删除“'+displayTitle+'”'+(hasDescendants?'及其下级':'')+'（共 '+chineseCounts+'）？正文将从当前作品移除，历史记录保留。已导入画布的内容不会删除。';
            return{mode:'delete',kind:scope,scope,id,itemType:scope,includeDescendants,selectedScope,selectedId,
                title:L('删除'+outlineKindLabel(scope),'Remove '+outlineKindLabel(scope)),message,
                returnFocus:{kind:'menu',scope,id}};
        }
        if(action==='rename'){
            if(!item)return null;
            const kind=scope;
            return{mode:'rename',kind,scope,id,initial:titleOf(item),title:L('重命名'+outlineKindLabel(kind),'Rename '+outlineKindLabel(kind)),label:L(outlineKindLabel(kind)+'名称',outlineKindLabel(kind)+' name')};
        }
        let kind='',parentId='',afterId='',selectedScope='';
        if(action==='root-create'){kind=isNovel?'volume':'episode';selectedScope=kind;}
        else if(action==='episode-sibling'){kind='episode';afterId=id;selectedScope='episode';}
        else if(action==='scene-child'){kind='scene';parentId=id;selectedScope='scene';}
        else if(action==='scene-sibling'&&foundScene){kind='scene';parentId=foundScene.episode.id;afterId=id;selectedScope='scene';}
        else if(action==='segment-child'){kind='segment';parentId=id;selectedScope='segment';}
        else if(action==='segment-sibling'&&foundScene){kind='segment';parentId=foundScene.scene.id;afterId=id;selectedScope='segment';}
        else if(action==='volume-sibling'){kind='volume';afterId=id;selectedScope='volume';}
        else if(action==='chapter-child'){kind='chapter';parentId=id;selectedScope='chapter';}
        else if(action==='chapter-sibling'&&foundChapter){kind='chapter';parentId=foundChapter.volume.id;afterId=id;selectedScope='chapter';}
        if(!kind)return null;
        return{mode:'create',kind,parentId,afterId,selectedScope,scope,id,initial:outlineDefaultName(kind,parentId),title:L('新建'+outlineKindLabel(kind),'Add '+outlineKindLabel(kind)),label:L(outlineKindLabel(kind)+'名称',outlineKindLabel(kind)+' name'),clientRef:newOutlineRef()};
    }
    function newOutlineRef(){const raw=crypto.randomUUID?crypto.randomUUID():Date.now()+'_'+Math.random().toString(36).slice(2);return'ui_ref_'+raw.replace(/[^A-Za-z0-9_-]/g,'');}
    function renderOutlineDialog(){
        const dialog=state.outlineDialog;if(!dialog)return;
        const deleting=dialog.mode==='delete';
        $('smOutlineDialogTitle').textContent=dialog.title;
        $('smOutlineDialogLabel').textContent=dialog.label;
        $('smOutlineDialogLabel').hidden=deleting;
        if(!deleting)$('smOutlineDialogInput').value=dialog.value??dialog.initial;
        $('smOutlineDialogInput').hidden=deleting;
        $('smOutlineDialogInput').placeholder=dialog.label;
        $('smOutlineDialogInput').setAttribute('aria-describedby',deleting?'smOutlineDialogMessage smOutlineDialogError':'smOutlineDialogError');
        const message=$('smOutlineDialogMessage');message.textContent=dialog.message||'';message.hidden=!deleting;
        const close=$('smOutlineDialog').querySelector('[data-outline-dialog-close]');
        close.title=close.ariaLabel=L('关闭','Close');
        $('smOutlineDialog').setAttribute('aria-label',dialog.title);
        $('smOutlineDialogForm').setAttribute('aria-describedby',deleting?'smOutlineDialogMessage smOutlineDialogError':'smOutlineDialogError');
        $('smOutlineDialogError').hidden=!dialog.error;$('smOutlineDialogError').textContent=dialog.error||'';
        $('smOutlineDialogSubmit').querySelector('span').textContent=dialog.busy?L(deleting?'正在移除…':'正在保存…',deleting?'Removing…':'Saving…'):deleting?L('确认删除','Confirm delete'):L(dialog.mode==='rename'?'保存':'创建',dialog.mode==='rename'?'Save':'Create');
        $('smOutlineDialogSubmit').classList.toggle('is-danger',deleting);
        $('smOutlineDialogSubmit').disabled=Boolean(dialog.busy||dialog.invalid);
        $('smOutlineDialogInput').disabled=Boolean(dialog.busy||dialog.uncertain);
        document.querySelectorAll('[data-outline-dialog-close]').forEach(button=>button.disabled=Boolean(dialog.busy||dialog.uncertain));
        $('smOutlineDialog').hidden=false;icons();
    }
    function findOutlineMenuButton(scope,id){return[...document.querySelectorAll('[data-outline-menu-toggle]')].find(button=>button.dataset.outlineScope===scope&&button.dataset.outlineNodeId===id)||null;}
    function restoreOutlineFocus(target){
        requestAnimationFrame(()=>{
            if(target?.kind==='root'){$('smOutlineRootAdd')?.focus();return;}
            if(target?.kind==='item'){[...document.querySelectorAll('[data-scope]')].find(item=>item.dataset.scope===target.scope&&item.dataset.nodeId===target.id)?.focus();return;}
            if(target?.kind==='menu'){findOutlineMenuButton(target.scope,target.id)?.focus();return;}
            $('smDirectoryToggle')?.focus();
        });
    }
    function closeOutlineDialog(){
        const dialog=state.outlineDialog;if(!dialog||dialog.busy||dialog.uncertain)return;
        state.outlineDialog=null;$('smOutlineDialog').hidden=true;$('smOutlineDialogError').hidden=true;$('smOutlineDialogError').textContent='';
        restoreOutlineFocus(dialog.returnFocus);
    }
    async function prepareOutlineMutation(){
        if(!await beforeNavigate())return false;
        if(state.editor){await closeEditor();if(state.editor||state.dirty||state.conflicted)return false;}
        return true;
    }
    async function beginOutlineDialog(action,scope,id,returnFocus){
        state.outlineMenu=null;renderDirectory();
        if(!await prepareOutlineMutation())return;
        const descriptor=outlineDialogDescriptor(action,scope,id);
        if(!descriptor){setStatus(L('这个目录项已不存在，请重新读取目录。','This outline item no longer exists. Refresh the outline.'),'error');return;}
        state.outlineDialog={...descriptor,value:descriptor.initial,error:'',busy:false,uncertain:false,returnFocus:returnFocus||{kind:'menu',scope,id}};
        renderOutlineDialog();
        requestAnimationFrame(()=>{if(descriptor.mode==='delete')$('smOutlineDialogSubmit').focus();else{$('smOutlineDialogInput').focus();$('smOutlineDialogInput').select();}});
    }
    function buildOutlineCommand(dialog,title){
        const args={};let action='';
        if(dialog.mode==='delete'){
            return{action:'delete_item',args:{item_type:dialog.itemType,item_id:dialog.id,include_descendants:dialog.includeDescendants},selectedScope:dialog.selectedScope,selectedId:dialog.selectedId};
        }
        if(dialog.mode==='rename'){
            const itemTypes={episode:'episode',scene:'scene',segment:'segment',volume:'volume',chapter:'chapter'};
            action='rename_item';Object.assign(args,{item_type:itemTypes[dialog.kind],item_id:dialog.id,title});
            return{action,args,selectedScope:dialog.scope,selectedId:dialog.id};
        }
        args.title=title;args.client_ref=dialog.clientRef;
        if(dialog.kind==='episode'){
            action='create_episode';if(dialog.afterId)args.after_episode_id=dialog.afterId;
        }else if(dialog.kind==='scene'){
            action='create_scene';args.episode_id=dialog.parentId;args.body_markdown='';if(dialog.afterId)args.after_scene_id=dialog.afterId;
        }else if(dialog.kind==='segment'){
            action='create_segment';args.scene_id=dialog.parentId;args.body_markdown='';if(dialog.afterId)args.after_segment_id=dialog.afterId;
        }else if(dialog.kind==='volume'){
            action='create_volume';if(dialog.afterId)args.after_volume_id=dialog.afterId;
        }else if(dialog.kind==='chapter'){
            action='create_chapter';args.volume_id=dialog.parentId;args.body_markdown='';if(dialog.afterId)args.after_chapter_id=dialog.afterId;
        }
        return{action,args,selectedScope:dialog.selectedScope,parentId:dialog.parentId,clientRef:dialog.clientRef};
    }
    function validCommandReceipt(receipt,payload){
        const revision=Number(receipt?.revision);
        return receipt?.status==='succeeded'&&receipt.request_id===payload.request_id&&receipt.project_id===projectId&&Number.isSafeInteger(revision)&&revision>Number(payload.expected_revision);
    }
    async function postOutlineCommand(operation){
        const semantic=JSON.stringify({action:operation.action,args:operation.args});
        let pending=state.pendingOutlineCommand;
        if(!pending||pending.semantic!==semantic){
            const payload=commandPayload(operation.action,operation.args,null,state.revision);
            pending={semantic,payload};state.pendingOutlineCommand=pending;
        }
        const payload=pending.payload;
        let receipt;
        try{receipt=await post(root+'/commands',payload);}
        catch(error){
            if(error.status===409){
                state.pendingOutlineCommand=null;
                try{await refreshPage();}catch(_){}
                const conflict=new Error(L('作品已在别处更新。当前目录已重新读取，请确认目标后再次提交目录操作。','This work changed elsewhere. The outline was refreshed; check the target before submitting the outline change again.'));
                conflict.status=409;throw conflict;
            }
            if(error.status&&error.status<500){state.pendingOutlineCommand=null;throw error;}
            try{receipt=await api(root+'/commands/'+encodeURIComponent(payload.request_id));}
            catch(receiptError){const unknown=new Error(L('暂时无法确认目录操作结果。此窗口会保留操作；点重试会复用同一请求，不会重复执行。','The outline change is not confirmed. This dialog keeps it; retry reuses the same request and will not repeat the operation.'));unknown.uncertain=true;throw unknown;}
        }
        if(!validCommandReceipt(receipt,payload)){const unknown=new Error(L('暂时无法确认目录操作结果。此窗口会保留操作；点重试会复用同一请求，不会重复执行。','The outline change is not confirmed. This dialog keeps it; retry reuses the same request and will not repeat the operation.'));unknown.uncertain=true;throw unknown;}
        return{receipt,pending,operation};
    }
    async function submitOutlineDialog(event){
        event.preventDefault();const dialog=state.outlineDialog;if(!dialog||dialog.busy)return;
        const title=dialog.mode==='delete'?'':String($('smOutlineDialogInput').value||'').trim();dialog.value=title;
        if(dialog.mode!=='delete'&&!title){dialog.error=L('请输入名称。','Enter a name.');renderOutlineDialog();$('smOutlineDialogInput').focus();return;}
        if(dialog.mode!=='delete'&&title.length>120){dialog.error=L('名称不能超过 120 个字符。','Name must be 120 characters or fewer.');renderOutlineDialog();$('smOutlineDialogInput').focus();return;}
        const operation=buildOutlineCommand(dialog,title);if(!operation.action){dialog.error=L('无法识别此操作，请刷新后重试。','This action is unavailable. Refresh and try again.');renderOutlineDialog();return;}
        dialog.busy=true;dialog.error='';renderOutlineDialog();
        try{
            const result=await postOutlineCommand(operation),receipt=result.receipt;
            const createdId=operation.clientRef?String(receipt.created_ids?.[operation.clientRef]||''):'';
            state.pendingOutlineCommand=null;state.outlineDialog=null;$('smOutlineDialog').hidden=true;
            setRevision(receipt.revision);
            if(operation.clientRef&&!createdId){
                state.search='';$('smDirectorySearch').value='';state.requestEpoch++;await loadSummary(true);
                setStatus(L('目录操作已保存，服务器未返回新条目的定位信息；目录已重新读取。','The outline change was saved, but the server did not return the new item ID. The outline was refreshed.'),'error');
                restoreOutlineFocus({kind:'root'});return;
            }
            state.selection={scope:operation.selectedScope,nodeId:createdId||operation.selectedId||''};
            state.search='';$('smDirectorySearch').value='';state.outlineMenu=null;
            if(operation.selectedScope==='scene'){const parent=operation.parentId||findScene(operation.selectedId||createdId)?.episode?.id||'';state.expanded.add(parent);if(createdId)state.expanded.add(createdId);}
            if(operation.selectedScope==='segment'){const found=findScene(operation.parentId||operation.selectedId||createdId);state.expanded.add(found?.episode?.id||'');state.expanded.add(found?.scene?.id||'');}
            if(operation.selectedScope==='chapter')state.expanded.add(operation.parentId||findChapter(operation.selectedId||createdId)?.volume?.id||'');
            if(operation.action==='delete_item'){
                if(operation.selectedScope==='episode')state.expanded.add(operation.selectedId);
                if(operation.selectedScope==='scene'){const found=findScene(operation.selectedId);state.expanded.add(found?.episode?.id||'');state.expanded.add(operation.selectedId);}
                if(operation.selectedScope==='volume')state.expanded.add(operation.selectedId);
            }
            state.requestEpoch++;await loadSummary(true);setStatus('');closeDrawerForOverlay();
            restoreOutlineFocus({kind:'item',scope:state.selection.scope,id:state.selection.nodeId});
        }catch(error){
            dialog.busy=false;dialog.error=error.message||L('目录操作失败；输入仍保留，可重试。','Could not update the outline. Your input is still here and can be retried.');
            dialog.uncertain=Boolean(error.uncertain||error.status>=500);
            if(error.status===409&&dialog.mode==='delete'){
                const latest=outlineDialogDescriptor('delete',dialog.scope,dialog.id);
                if(latest){dialog.message=latest.message;dialog.includeDescendants=latest.includeDescendants;dialog.selectedScope=latest.selectedScope;dialog.selectedId=latest.selectedId;}
                else{dialog.invalid=true;dialog.error=L('此目录项已被移除。请取消对话框并重新读取目录。','This outline item was removed elsewhere. Cancel and refresh the outline.');}
            }
            renderOutlineDialog();
            if(!dialog.uncertain){if(dialog.mode==='delete')$('smOutlineDialogSubmit').focus();else $('smOutlineDialogInput').focus();}
        }
    }
    function toggleOutlineMenu(scope,id,button){
        const open=state.outlineMenu?.scope===scope&&state.outlineMenu?.id===id;
        let above=false;
        if(!open){
            const row=button?.closest('.sm-tree-row'),tree=$('smDirectory'),rowRect=row?.getBoundingClientRect(),treeRect=tree?.getBoundingClientRect();
            const height=outlineMenuActions(scope).length*36+16;
            above=Boolean(rowRect&&treeRect&&treeRect.bottom-rowRect.bottom<height+4);
        }
        state.outlineMenu=open?null:{scope,id,above};renderDirectory();
        if(!open)requestAnimationFrame(()=>document.querySelector('.sm-outline-menu [role="menuitem"]')?.focus());
        else findOutlineMenuButton(scope,id)?.focus();
        if(button)button.blur();
    }
    function closeOutlineMenu(restoreFocus){
        const target=state.outlineMenu;if(!target)return;
        state.outlineMenu=null;renderDirectory();
        if(restoreFocus)findOutlineMenuButton(target.scope,target.id)?.focus();
    }
    function handleOutlineMenuKeydown(event){
        if(!state.outlineMenu)return;
        const menu=event.target.closest('.sm-outline-menu');if(!menu)return;
        const items=[...menu.querySelectorAll('[role="menuitem"]')],current=items.indexOf(document.activeElement);if(!items.length)return;
        let next=-1;
        if(event.key==='ArrowDown')next=(current+1+items.length)%items.length;
        else if(event.key==='ArrowUp')next=(current-1+items.length)%items.length;
        else if(event.key==='Home')next=0;
        else if(event.key==='End')next=items.length-1;
        else if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeOutlineMenu(true);return;}
        if(next>=0){event.preventDefault();items[next].focus();}
    }
    function handleOutlineDialogKeydown(event){
        if(!state.outlineDialog)return;
        if(event.key==='Escape'){event.preventDefault();closeOutlineDialog();return;}
        if(event.key!=='Tab')return;
        const dialog=$('smOutlineDialogForm'),focusable=[...dialog.querySelectorAll('input:not([disabled]),button:not([disabled])')];
        if(!focusable.length)return;
        const first=focusable[0],last=focusable[focusable.length-1];
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    }
    function selectionTitle(){
        const s=state.selection;
        if(isNovel){
            if(s.scope==='root')return L('全书正文','Whole novel');
            if(s.scope==='volume')return titleOf((state.summary?.directory?.volumes||[]).find(item=>item.id===s.nodeId));
            const found=findChapter(s.nodeId);return titleOf(found?.chapter);
        }
        if(s.scope==='root')return L('完整剧本','Full script');
        if(s.scope==='episode')return titleOf((state.summary?.directory?.episodes||[]).find(item=>item.id===s.nodeId));
        const found=findScene(s.nodeId);
        return s.scope==='scene'?titleOf(found?.scene):outlineDisplayTitle('segment',(found?.scene?.segments||[]).find(item=>item.id===s.nodeId));
    }
    function updateHeading(){
        const s=state.selection,hint=!isNovel&&s.scope==='root'&&state.summary?.state==='draft'?L('完整剧本草稿','Complete script draft'):'';
        $('smScopeTitle').textContent=selectionTitle();$('smScopeHint').textContent=hint;
        $('smContentHeading').hidden=false;
        updateDocumentPaneTabs();
        const parts=isNovel?(s.scope==='root'?[L('全书','Whole novel')]:s.scope==='volume'?[L('全书','Whole novel'),selectionTitle()]:[L('全书','Whole novel'),titleOf(findChapter(s.nodeId)?.volume),selectionTitle()]):(s.scope==='root'?[L('完整剧本','Full script')]:s.scope==='episode'?[L('完整剧本','Full script'),selectionTitle()]:s.scope==='scene'?[L('完整剧本','Full script'),titleOf(findScene(s.nodeId)?.episode),selectionTitle()]:[L('完整剧本','Full script'),titleOf(findScene(s.nodeId)?.episode),titleOf(findScene(s.nodeId)?.scene),selectionTitle()]);
        $('smBreadcrumb').hidden=state.tab==='text';
        $('smBreadcrumb').innerHTML=state.tab==='text'?'':parts.map((item,index)=>((index?'<span aria-hidden="true">/</span>':'')+'<span '+(index===parts.length-1?'aria-current="page"':'')+'>'+esc(item)+'</span>')).join('');
        if(state.tab==='text')updateGlobalInlineState();else $('smRevisionLabel').textContent=L('已保存','Saved');
        $('smEditButton').hidden=state.tab==='text'||!(isNovel&&state.tab==='settings'&&(state.setting||state.handoff)&&!state.historyMode);
        const copyable=isNovel?state.tab==='text'&&s.scope==='chapter':s.scope==='scene'||s.scope==='segment';
        $('smCopyButton').hidden=state.tab!=='text'||state.documentPane!=='body'||Boolean(state.editor)||!copyable||!state.blocks.length;
        updateCharacterCount();
    }
    function sliceScript(body,segments){
        const chars=Array.from(String(body||'')),ranges=(segments||[]).map(item=>({...item,start:Math.max(0,Math.min(chars.length,Number(item.start)||0)),end:Math.max(0,Math.min(chars.length,Number(item.end)||0))})).filter(item=>item.end>=item.start).sort((a,b)=>a.start-b.start||a.end-b.end);
        let cursor=0,html='';
        for(const segment of ranges){
            if(segment.start<cursor)continue;
            if(segment.start>cursor){const gap=chars.slice(cursor,segment.start).join('');if(gap)html+='<div class="sm-unsegmented"><span class="sm-unsegmented-label">'+esc(L('未分段正文','Unsegmented text'))+'</span>'+markdown(gap)+'</div>';}
            html+='<section class="sm-segment"><div class="sm-segment-heading"><code>'+esc(L('分段','Segment'))+'</code><strong>'+esc(titleOf(segment))+'</strong></div>'+markdown(chars.slice(segment.start,segment.end).join(''))+'</section>';
            cursor=segment.end;
        }
        if(cursor<chars.length){const gap=chars.slice(cursor).join('');if(gap)html+='<div class="sm-unsegmented"><span class="sm-unsegmented-label">'+esc(L('未分段正文','Unsegmented text'))+'</span>'+markdown(gap)+'</div>';}
        if(!ranges.length&&chars.length)return markdown(chars.join(''));
        return html||empty(L('场次正文为空','Scene is empty'));
    }
    function renderScriptBlocks(blocks,append){
        const scopeKey=documentScopeKey();
        let fields=inlineFieldsForBlocks(blocks);
        if(!isNovel&&state.selection.scope==='root'&&state.summary?.state==='draft'&&!fields.length)fields=inlineFieldsForBlocks([{}]);
        installInlineFields(fields,emptyHtmlForReader(blocks),append,scopeKey);
    }
    function renderNovelBlocks(blocks,append){
        installInlineFields(inlineFieldsForBlocks(blocks),inlineEmptyText(),append,documentScopeKey());
    }
    function emptyHtmlForReader(){
        if(!isNovel&&state.selection.scope==='root'&&state.summary?.state==='draft')return empty(L('完整剧本尚未保存','No saved script yet'),L('可在此直接记录完整剧本，也可通过目录整理集场。','Write the full script here, or organize it by episode and scene in the outline.'));
        return inlineEmptyText();
    }
    async function loadView(append){
        $('smLoadMoreButton').hidden=true;
        if(!append)beginCharacterCount();
        const epoch=state.requestEpoch;
        try{
            const countScope={scope:state.selection.scope,nodeId:state.selection.nodeId};
            const params={scope:countScope.scope,node_id:countScope.nodeId,limit:30};
            if(append&&state.cursor)params.cursor=state.cursor;
            const data=await api(route('/view',params));if(epoch!==state.requestEpoch)return;setRevision(data.revision);
            state.cursor=data.next_cursor||'';state.blocks=append?state.blocks.concat(data.blocks||[]):(data.blocks||[]);
            updateHeading();
            if(isNovel)renderNovelBlocks(data.blocks||[],Boolean(append));else renderScriptBlocks(data.blocks||[],Boolean(append));
            $('smLoadMoreButton').hidden=!data.has_more;$('smLoadMoreButton').disabled=false;$('smLoadMoreButton').textContent=L('继续加载','Load more');
            renderDirectory();
            if(append)updateCharacterCount();
            else void loadCharacterCount(state.blocks,state.cursor,Boolean(data.has_more),Number(data.revision),countScope);
        }catch(error){
            if(epoch!==state.requestEpoch)return;
            state.characterCountToken++;state.characterCount=null;updateCharacterCount();
            setStatus(L('读取正文失败：','Could not read the text: ')+(error.message||''),'error');
            $('smReader').innerHTML=empty(L('暂时无法读取','Could not load this view'),L('请重新读取。已保存内容没有被修改。','Refresh to try again. Saved content has not been changed.'));
        }
    }
    function outlinePath(id){return'/'+(isNovel?'chapters':'episodes')+'/'+enc(id)+'/outline';}
    function outlineField(record){
        const id=state.selection.nodeId;
        return{key:inlineKey(isNovel?'novel-chapter-outline':'script-episode-outline',id),
            action:isNovel?'set_chapter_outline':'set_episode_outline',
            args:isNovel?{chapter_id:id}:{episode_id:id},body:record.outline_markdown||'',
            label:L('章纲','Outline'),optimization:{scope:isNovel?'chapter_outline':'episode_outline',sourceId:id,sourceSha256:record.outline_sha256||''}};
    }
    async function loadOutlinePane(options){
        if(!outlineEligible())return false;
        const epoch=Number.isInteger(options?.epoch)?options.epoch:state.requestEpoch,id=state.selection.nodeId,scopeKey=documentScopeKey();
        state.outlineLoading=true;state.outlineError=false;updateCharacterCount();
        try{
            let record=await api(route(outlinePath(id)),{cache:'no-store'});
            if(epoch!==state.requestEpoch||scopeKey!==documentScopeKey())return false;
            if(record.project_id!==projectId||record.parent_id!==id)throw new Error(L('章纲对应的作品或章节已变化，请重新读取。','The outline’s work or chapter changed. Refresh and try again.'));
            if(Number(record.revision)!==state.revision){
                const summary=await api(root,{cache:'no-store'});
                if(epoch!==state.requestEpoch||scopeKey!==documentScopeKey())return false;
                state.summary=summary;setRevision(summary.revision);$('smProjectName').textContent=projectName();renderDirectory();
                record=await api(route(outlinePath(id)),{cache:'no-store'});
                if(epoch!==state.requestEpoch||scopeKey!==documentScopeKey())return false;
                if(record.project_id!==projectId||record.parent_id!==id||Number(record.revision)!==state.revision)throw new Error(L('作品仍在更新，请重新读取。','The work is still updating. Refresh and try again.'));
            }
            const outlineRevision=Number(record.outline_revision),currentRevision=Number(record.current_outline_revision);
            if(!Number.isSafeInteger(outlineRevision)||outlineRevision<0||!Number.isSafeInteger(currentRevision)||outlineRevision!==currentRevision||record.selected_revision!=='current')throw new Error(L('章纲版本不完整，暂时无法安全编辑。','The outline version is incomplete and cannot be edited safely.'));
            state.outlineRecord=record;state.outlineLoading=false;state.outlineError=false;
            installInlineFields([outlineField(record)],empty(L('章纲暂不可用','Outline unavailable'),L('请重新读取后再编辑。','Refresh before editing.')),false,scopeKey);
            updateHeading();setStatus('');return true;
        }catch(error){
            if(epoch!==state.requestEpoch||scopeKey!==documentScopeKey())return false;
            state.outlineLoading=false;state.outlineError=true;
            const key=outlineInlineKey(),cached=state.inlineDrafts.get(key);
            if(cached)installInlineFields([{...cached,key,action:isNovel?'set_chapter_outline':'set_episode_outline',args:isNovel?{chapter_id:id}:{episode_id:id},label:L('章纲','Outline')}],'',false,scopeKey);
            else{$('smReader').innerHTML=empty(L('暂时无法读取章纲','Could not load the outline'),L('请重新读取。已保存的正文和章纲没有被修改。','Refresh to try again. Saved text and outline were not changed.'));state.readerScopeKey=scopeKey;}
            updateCharacterCount();setStatus(L('读取章纲失败：','Could not read the outline: ')+(error.message||''),'error');return false;
        }
    }
    async function selectDocumentPane(pane){
        if(!['body','outline'].includes(pane)||pane===state.documentPane||pane==='outline'&&!outlineEligible())return;
        if(!await beforeNavigate())return;
        clearCopyFeedback();state.requestEpoch++;const epoch=state.requestEpoch;
        state.documentPane=pane;state.outlineLoading=false;state.outlineError=false;state.readerScopeKey='';
        $('smReader').innerHTML=empty(pane==='outline'?L('正在读取章纲','Loading outline'):L('正在读取正文','Loading text'),pane==='outline'?L('正在读取当前项目章纲。','Loading the selected item outline.'):L('正在读取当前正文。','Loading the selected text.'));
        $('smLoadMoreButton').hidden=true;
        updateHeading();
        if(pane==='outline')await loadOutlinePane({epoch});
        else{state.outlineRecord=null;await loadView(false);}
    }
    async function loadSummary(preserve){
        const epoch=state.requestEpoch;
        const data=await api(root);if(epoch!==state.requestEpoch)return;state.summary=data;setRevision(data.revision);
        $('smProjectName').textContent=projectName();
        document.title=L(isNovel?'小说创作':'剧本创作',isNovel?'Novel Writing':'Script Writing');
        if(isNovel)$('smNovelTabs').hidden=false;else $('smNovelTabs').hidden=true;
        if(!preserve){state.selection={scope:'root',nodeId:''};state.tab='text';state.documentPane='body';state.outlineRecord=null;}
        const rows=isNovel?data.directory?.volumes:data.directory?.episodes;
        (rows||[]).forEach(item=>{state.expanded.add(item.id);if(!isNovel)(item.scenes||[]).forEach(scene=>state.expanded.add(scene.id));});
        renderDirectory();
        if(isNovel&&state.tab==='settings'){
            await loadSettingsIndex(state.settingsCategory);
            if(epoch!==state.requestEpoch)return;
            return;
        }
        if(epoch!==state.requestEpoch)return;
        if(state.documentPane==='outline'&&outlineEligible())await loadOutlinePane({epoch});else await loadView(false);setStatus('');
    }
    async function loadSettingsIndex(category,cursor,append){
        const selected=category===undefined?state.settingsCategory:category;
        const epoch=state.requestEpoch;
        const params={limit:100,category_id:selected};if(cursor)params.cursor=cursor;
        const data=await api(route('/settings',params));if(epoch!==state.requestEpoch)return null;setRevision(data.revision);
        state.settingsCategory=selected||'';
        state.settingsIndex={...data,entries:append?(state.settingsIndex?.entries||[]).concat(data.entries||[]):(data.entries||[]),cursor:data.next_cursor||'',has_more:Boolean(data.has_more)};
        renderDirectory();return data;
    }
    async function beforeNavigate(){
        if(!await saveInlineBatch())return false;
        if(state.saving)return false;
        if(state.dirty){const saved=await saveEditor();if(!saved||state.saving||state.dirty||state.conflicted)return false;}
        return !state.conflicted;
    }
    async function selectOutline(scope,nodeId){
        if(!await beforeNavigate())return;
        clearCopyFeedback();
        state.outlineMenu=null;
        state.requestEpoch++;
        state.editor=null;state.dirty=false;
        state.selection={scope:scope,nodeId:nodeId||''};state.documentPane='body';state.outlineRecord=null;state.outlineLoading=false;state.outlineError=false;state.cursor='';state.blocks=[];state.historyMode=false;
        if(!isNovel&&(scope==='scene'||scope==='segment')){const found=findScene(nodeId);if(found){state.expanded.add(found.episode.id);state.expanded.add(found.scene.id);}}
        if(isNovel&&scope==='chapter'){const found=findChapter(nodeId);if(found)state.expanded.add(found.volume.id);}
        state.readerScopeKey='';
        $('smReader').innerHTML=empty(L('正在读取正文','Loading text'),L('正在读取当前范围。','Loading the selected scope.'));
        updateDocumentPaneTabs();
        $('smEditor').hidden=true;$('smReader').hidden=false;$('smVersionTools').hidden=true;
        await loadView(false);closeDrawerForOverlay();
    }
    function rememberTabState(tab){
        const scrollTop=$('smMainContent').scrollTop;
        if(tab==='text')state.tabStates.text={selection:{...state.selection},cursor:state.cursor,blocks:state.blocks.slice(),search:state.search,expanded:new Set(state.expanded),scrollTop,revision:state.revision};
        else state.tabStates.settings={settingsCategory:state.settingsCategory,settingsIndex:state.settingsIndex,setting:state.setting,handoff:state.handoff,historyMode:state.historyMode,settingRevisions:state.settingRevisions.slice(),search:state.search,scrollTop,revision:state.revision};
    }
    function restoreTabState(tab){
        const snapshot=state.tabStates[tab];if(!snapshot)return false;
        state.search=snapshot.search;state.expanded=new Set(snapshot.expanded||[]);$('smDirectorySearch').value=state.search;
        if(tab==='text'){
            state.selection={...snapshot.selection};state.cursor=snapshot.cursor||'';state.blocks=snapshot.blocks||[];
            $('smVersionTools').hidden=true;$('smEditor').hidden=true;$('smReader').hidden=false;$('smLoadMoreButton').hidden=!state.cursor;
            renderDirectory();renderNovelBlocks(state.blocks,false);updateHeading();
        }else{
            state.settingsCategory=snapshot.settingsCategory||'';state.settingsIndex=snapshot.settingsIndex;state.setting=snapshot.setting;state.handoff=snapshot.handoff;state.historyMode=snapshot.historyMode;state.settingRevisions=snapshot.settingRevisions||[];
            $('smEditor').hidden=true;$('smReader').hidden=false;$('smVersionTools').hidden=true;
            renderDirectory();
            if(state.setting)renderSetting(state.setting);
            else if(state.handoff)renderHandoff(state.handoff);
            else{
                $('smScopeTitle').textContent=L('设定库','Settings');$('smScopeHint').textContent='';
                $('smBreadcrumb').innerHTML='<span aria-current="page">'+esc(L('设定库','Settings'))+'</span>';
                $('smReader').innerHTML=empty(L('选择一条设定','Choose a setting'),L('选择分类中的条目查看正文和故事阶段版本。','Choose an entry to read its text and story-stage versions.'));
                updateHeadingActions();
            }
        }
        $('smMainContent').scrollTop=snapshot.scrollTop||0;
        return snapshot.revision===state.revision;
    }
    async function selectTab(tab){
        if(!isNovel)return;
        if(tab===state.tab)return;
        if(!await beforeNavigate())return;
        clearCopyFeedback();
        state.characterCountToken++;state.characterCount=null;
        rememberTabState(state.tab);
        state.requestEpoch++;
        const epoch=state.requestEpoch;
        state.tab=tab;state.documentPane='body';state.outlineRecord=null;state.outlineLoading=false;state.outlineError=false;state.editor=null;state.dirty=false;state.conflicted=false;
        updateDocumentPaneTabs();
        document.querySelectorAll('[data-sm-tab]').forEach(button=>{const active=button.dataset.smTab===tab;button.classList.toggle('active',active);button.setAttribute('aria-selected',active?'true':'false');button.tabIndex=active?0:-1;});
        $('smMainContent').setAttribute('aria-labelledby',tab==='text'?'smTabText':'smTabSettings');
        $('smEditor').hidden=true;$('smReader').hidden=false;$('smVersionTools').hidden=true;$('smLoadMoreButton').hidden=true;
        const hasSnapshot=Boolean(state.tabStates[tab]),current=hasSnapshot?restoreTabState(tab):false;
        if(!hasSnapshot){
            if(tab==='text'){
                state.selection={scope:'root',nodeId:''};state.blocks=[];state.cursor='';state.search='';renderDirectory();
                await loadView(false);
            }else{
                state.settingsCategory='';state.search='';state.setting=null;state.handoff=null;state.historyMode=false;state.settingRevisions=[];
                try{await loadSettingsIndex('');}catch(error){if(epoch===state.requestEpoch)setStatus(error.message,'error');}
                if(epoch!==state.requestEpoch)return;
                $('smScopeTitle').textContent=L('设定库','Settings');$('smScopeHint').textContent='';
                $('smBreadcrumb').innerHTML='<span aria-current="page">'+esc(L('设定库','Settings'))+'</span>';
                $('smReader').innerHTML=empty(L('选择一条设定','Choose a setting'),L('选择分类中的条目查看正文和故事阶段版本。','Choose an entry to read its text and story-stage versions.'));
                updateHeadingActions();
            }
        }else if(!current&&tab==='text'){
            state.cursor='';await loadView(false);
        }else if(!current&&tab==='settings'){
            try{
                await loadSettingsIndex(state.settingsCategory);
                if(epoch!==state.requestEpoch)return;
                if(state.setting)await loadSetting(state.setting.entry.id,state.setting.selectedVersion.id,state.historyMode?state.setting.selectedVersion.selected_edit_revision:undefined);
                else if(state.handoff)await loadHandoff(state.historyMode?state.handoff.record?.revision:undefined);
            }catch(error){if(epoch===state.requestEpoch)setStatus(error.message,'error');}
        }
        closeDrawerForOverlay();
        if(tab==='text'&&current)ensureCharacterCount();
        else updateCharacterCount();
    }
    function updateHeadingActions(){
        if(state.editor){$('smEditButton').hidden=true;$('smCopyButton').hidden=true;return;}
        const settingIsCurrent=state.setting&&state.setting.selectedVersion?.id===state.setting.entry?.current_version_id;
        const handoffIsCurrent=state.handoff&&!state.historyMode&&Number(state.handoff.record?.revision)===Number(state.handoffCurrentRevision||state.handoff.record?.revision);
        $('smEditButton').hidden=!(state.tab==='settings'&&isNovel&&(settingIsCurrent||handoffIsCurrent)&&!state.historyMode);
        $('smCopyButton').hidden=true;
    }
    async function selectSettingsCategory(category){
        if(!await beforeNavigate())return;
        clearCopyFeedback();
        state.requestEpoch++;
        const epoch=state.requestEpoch;
        state.editor=null;state.dirty=false;
        state.settingsCategory=category;state.setting=null;state.handoff=null;state.historyMode=false;
        $('smEditor').hidden=true;$('smReader').hidden=false;$('smVersionTools').hidden=true;
        try{await loadSettingsIndex(category);}
        catch(error){if(epoch===state.requestEpoch)setStatus(error.message||L('读取设定分类失败','Could not load this settings category'),'error');return;}
        if(epoch!==state.requestEpoch)return;
        const selected=(state.settingsIndex?.categories||[]).find(item=>categoryKey(item.id)===category);
        const selectedName=category?categoryName(selected):L('全部设定','All settings');
        $('smScopeTitle').textContent=selectedName;$('smScopeHint').textContent=L('本分类中的自由 Markdown 条目。','Free-form Markdown entries in this category.');
        $('smBreadcrumb').innerHTML='<span>'+esc(L('设定库','Settings'))+'</span><span aria-hidden="true">/</span><span aria-current="page">'+esc(selectedName)+'</span>';
        $('smReader').innerHTML=empty(L('选择一条设定','Choose a setting'),L('选中条目后可阅读、编辑或查看文字修订。','Choose an entry to read it, edit it, or review text revisions.'));
        updateHeadingActions();
    }
    function versionLabel(version){
        const number=version.story_version??version.number??'?';
        const status=version.use_state==='confirmed'?L('已确认','Confirmed'):L('草案','Draft');
        const anchor=version.story_anchor?.kind==='baseline'?L('基线','Baseline'):version.story_anchor?.kind==='unspecified'?L('未指定','Unspecified'):String(version.story_anchor?.kind||'');
        return L('故事版本 ','Story version ')+number+' · '+status+' · '+anchor;
    }
    function renderVersionSelector(label,guidance,options,current){
        $('smVersionTools').hidden=false;$('smVersionLabel').textContent=label;
        $('smVersionGuidance').textContent=guidance;
        const select=$('smVersionSelect');select.replaceChildren();
        options.forEach(item=>select.add(new Option(item.label,String(item.value),false,String(item.value)===String(current))));
    }
    function renderSetting(data){
        const entry=data.entry,selected=data.selectedVersion||data.selected_version;
        const selectedSummary=(entry.versions||[]).find(item=>item.id===selected.id);
        const savedEditRevision=Number(selectedSummary?.edit_revision??selected.edit_revision??selected.selected_edit_revision??1);
        const currentEditRevision=Number.isSafeInteger(savedEditRevision)&&savedEditRevision>0?savedEditRevision:1;
        $('smReader').hidden=false;$('smEditor').hidden=true;$('smLoadMoreButton').hidden=true;
        if(state.historyMode){
            const seenRevisions=new Set([currentEditRevision]),historicalRevisions=[];
            for(const item of state.settingRevisions||[]){const revision=Number(item.revision);if(!Number.isSafeInteger(revision)||revision<1||seenRevisions.has(revision))continue;seenRevisions.add(revision);historicalRevisions.push(revision);}
            const revisionOptions=[{value:currentEditRevision,label:L('当前修订 ','Current revision ')+currentEditRevision}].concat(historicalRevisions.map(revision=>({value:revision,label:L('文字修订 ','Text revision ')+revision})));
            renderVersionSelector(L('文字修订','Text revision'),L('历史文字修订只读；查看历史不会切换故事阶段版本。','Historical text revisions are read-only and do not switch the story-stage version.'),revisionOptions,selected.selected_edit_revision);
            $('smRevisionHistoryButton').querySelector('span').textContent=L('返回故事版本','Back to story versions');
        }else{
            renderVersionSelector(L('故事阶段版本','Story-stage version'),L('查看版本不表示它适用于当前章节。','Viewing a version does not make it applicable to the current chapter.'),(entry.versions||[]).map(version=>({value:version.id,label:versionLabel(version)})),selected.id);
            $('smRevisionHistoryButton').querySelector('span').textContent=L('文字修订','Text revisions');
        }
        $('smRevisionHistoryButton').hidden=!state.historyMode&&!((selectedSummary?.edit_revision||1)>1);
        $('smVersionTools').dataset.entryId=entry.id;$('smVersionTools').dataset.versionId=selected.id;
        $('smScopeTitle').textContent=entry.title||L('无标题条目','Untitled setting');
        const category=(state.settingsIndex?.categories||[]).find(item=>categoryKey(item.id)===categoryKey(entry.category_id));
        $('smScopeHint').textContent=categoryName(category);
        $('smRevisionLabel').textContent=L('已保存','Saved');
        $('smBreadcrumb').innerHTML='<span>'+esc(L('设定库','Settings'))+'</span><span aria-hidden="true">/</span><span aria-current="page">'+esc(entry.title||L('无标题条目','Untitled setting'))+'</span>';
        $('smReader').innerHTML=markdown(selected.body_markdown);
        renderDirectory();updateHeadingActions();
    }
    async function loadSetting(entryId,versionId,editRevision){
        const epoch=state.requestEpoch;
        const data=await api(route('/settings/'+enc(entryId),{version_id:versionId,edit_revision:editRevision}));if(epoch!==state.requestEpoch)return;setRevision(data.revision);
        state.setting={...data,entry:data.entry,selectedVersion:data.selected_version};state.handoff=null;state.historyMode=editRevision!==undefined&&editRevision!==null;
        renderSetting(state.setting);
    }
    async function loadSettingRevisions(entryId,versionId,epoch){
        const data=await api(route('/settings/'+enc(entryId)+'/revisions',{version_id:versionId,limit:100}));
        if(epoch!==undefined&&epoch!==state.requestEpoch)return null;
        state.settingRevisions=data.revisions||[];
        return data;
    }
    function renderHandoff(data){
        const record=data.record;
        if(record&&!state.historyMode)state.handoffCurrentRevision=Number(record.revision);
        $('smScopeTitle').textContent=record?.title||L('创作记录','Handoff note');
        $('smScopeHint').textContent='';
        $('smRevisionLabel').textContent=L('已保存','Saved');
        $('smBreadcrumb').innerHTML='<span>'+esc(L('设定库','Settings'))+'</span><span aria-hidden="true">/</span><span aria-current="page">'+esc(L('创作记录','Handoff note'))+'</span>';
        $('smReader').innerHTML=record?markdown(record.body_markdown):empty(L('还没有创作记录','No handoff note yet'),L('可通过自由 Markdown 编辑记录接续信息。','Use the Markdown editor to keep handoff notes.'));
        $('smVersionTools').hidden=!record;
        if(record){
            const currentRevision=Number(state.handoffCurrentRevision||record.revision),revisions=Array.from({length:Math.max(0,currentRevision-1)},(_,index)=>({value:index+1,label:L('文字修订 ','Text revision ')+(index+1)}));
            const opts=[{value:currentRevision,label:L('当前修订 ','Current revision ')+currentRevision}].concat(revisions);
            renderVersionSelector(L('文字修订','Text revision'),state.historyMode?L('历史接续记录只读。','Historical handoff notes are read-only.'):L('编辑会保留当前记录的来源引用。','Editing preserves the current note’s source references.'),opts,record.revision);
            $('smRevisionHistoryButton').querySelector('span').textContent=state.historyMode?L('返回当前记录','Back to current note'):L('文字修订','Text revisions');
            $('smRevisionHistoryButton').hidden=currentRevision<2;
        }
        renderDirectory();updateHeadingActions();
    }
    async function loadHandoff(editRevision){
        const epoch=state.requestEpoch;
        const data=await api(route('/handoff',{edit_revision:editRevision}));if(epoch!==state.requestEpoch)return;setRevision(data.revision);
        state.handoff=data;state.setting=null;state.historyMode=editRevision!==undefined&&editRevision!==null;
        renderHandoff(data);
    }
    async function chooseVersion(){
        if(!await beforeNavigate())return;
        state.requestEpoch++;
        const selected=$('smVersionSelect').value;
        if(state.setting){
            if(state.historyMode)await loadSetting(state.setting.entry.id,state.setting.selectedVersion.id,Number(selected));
            else await loadSetting(state.setting.entry.id,selected);
        }else if(state.handoff){
            if(state.historyMode)await loadHandoff(Number(selected));
            else if(Number(selected)!==Number(state.handoff.record?.revision))await loadHandoff(Number(selected));
        }
    }
    async function toggleHistory(){
        if(!await beforeNavigate())return;
        state.requestEpoch++;
        const epoch=state.requestEpoch;
        if(state.setting){
            if(state.historyMode){state.settingRevisions=[];await loadSetting(state.setting.entry.id,state.setting.selectedVersion.id);return;}
            const entry=state.setting.entry,version=state.setting.selectedVersion;
            await loadSettingRevisions(entry.id,version.id,epoch);
            if(epoch!==state.requestEpoch||state.setting?.entry?.id!==entry.id)return;
            if(!state.settingRevisions.length){setStatus(L('此故事阶段版本还没有旧文字修订。','This story-stage version has no earlier text revisions.'));return;}
            await loadSetting(entry.id,version.id,version.selected_edit_revision);return;
        }
        if(state.handoff){
            if(state.historyMode){await loadHandoff();return;}
            const record=state.handoff.record;if(!record||Number(record.revision)<2){setStatus(L('创作记录还没有旧文字修订。','The handoff note has no earlier revisions.'));return;}
            await loadHandoff(record.revision);
        }
    }
    function startEdit(){
        if(state.editor)return;
        if(state.tab==='text')return;
        const s=state.selection;let mode='',content='',meta={};
        if(!isNovel){
            if(s.scope==='root'&&state.summary?.state==='draft'){mode='script-draft';content=state.blocks[0]?.body_markdown||'';}
            else if(s.scope==='scene'){
                const found=findScene(s.nodeId);if(!found)return;
                mode='script-scene';const block=state.blocks.find(item=>item.id===s.nodeId);content=block?.editable_markdown??block?.body_markdown??'';
                meta.sceneId=s.nodeId;
            }else if(s.scope==='segment'){
                const block=state.blocks[0];if(!block)return;
                mode='script-segment';content=block.body_markdown||'';meta.segmentId=s.nodeId;
            }
        }else if(state.tab==='text'&&s.scope==='chapter'){
            if(!state.blocks[0])return;mode='novel-chapter';content=state.blocks[0].body_markdown||'';meta.chapterId=s.nodeId;
        }else if(state.tab==='settings'&&state.setting&&!state.historyMode){
            mode='setting-revision';content=state.setting.selectedVersion.body_markdown||'';meta.entryId=state.setting.entry.id;meta.versionId=state.setting.selectedVersion.id;
        }else if(state.tab==='settings'&&state.handoff&&!state.historyMode){
            mode='handoff';content=state.handoff.record?.body_markdown||'';meta.sourceRefs=state.handoff.record?.source_refs||[];
        }
        if(!mode)return;
        state.editor={mode,...meta,original:content,baseRevision:state.revision};
        state.dirty=false;state.conflicted=false;
        $('smMarkdownInput').value=content;$('smEditorError').hidden=true;$('smRetrySaveButton').hidden=true;
        $('smEditorTitle').textContent=L('编辑 Markdown 正文','Edit Markdown text');
        $('smEditorHint').textContent=mode==='script-scene'?L('独立一行的 --- 用来划分片段；保存后可在目录中逐段编辑。','A standalone --- marks a segment boundary; after saving, edit each segment from the outline.'):
            mode==='script-segment'?L('片段正文不包含独立 ---；需要调整边界时，请编辑场次正文。','A segment cannot contain a standalone ---; edit the scene text to change its boundaries.'):
            L('修改会在短暂停顿后自动保存。','Changes save automatically after a short pause.');
        $('smReader').hidden=true;$('smEditor').hidden=false;$('smEditButton').hidden=true;
        $('smMarkdownInput').focus();
    }
    function commandPayload(action,args,expectedSources,expectedRevision){
        const random=(crypto.randomUUID?crypto.randomUUID():Date.now()+'_'+Math.random().toString(36).slice(2)).replace(/[^A-Za-z0-9_-]/g,'');
        const payload={request_id:'ui_'+random,expected_revision:expectedRevision??state.editor?.baseRevision??state.revision,action:action,args:args};
        if(expectedSources)payload.expected_sources=expectedSources;
        return payload;
    }
    async function buildCommand(){
        const editor=state.editor,body=bodyText(),mode=editor?.mode;
        if(!editor)return null;
        if(body===editor.original)return null;
        if(mode==='script-draft')return{action:'set_draft',args:{body_markdown:body}};
        if(mode==='script-scene'){
            return{action:'update_scene',args:{scene_id:editor.sceneId,body_markdown:body}};
        }
        if(mode==='script-segment')return{action:'replace_segment_text',args:{segment_id:editor.segmentId,body_markdown:body}};
        if(mode==='novel-chapter')return{action:'update_chapter',args:{chapter_id:editor.chapterId,body_markdown:body}};
        if(mode==='setting-revision')return{action:'revise_setting_version',args:{entry_id:editor.entryId,version_id:editor.versionId,body_markdown:body}};
        if(mode==='handoff')return{action:'update_handoff_record',args:{body_markdown:body,source_refs:editor.sourceRefs||[]}};
        throw new Error(L('当前编辑类型不可保存。','This edit cannot be saved.'));
    }
    function inlineOperation(item){return{action:item.action,args:{...item.args,body_markdown:item.value}};}
    function setInlineSaving(items,saving){for(const item of items){item.saving=saving;updateInlineFieldNode(item.key);}}
    async function readCurrentInlineRevision(){
        try{const data=await api(root,{cache:'no-store'});state.summary=data;setRevision(data.revision);$('smProjectName').textContent=projectName();renderDirectory();return data;}
        catch(_){return null;}
    }
    async function fetchInlineRemote(item){
        try{
            if(item.action==='set_episode_outline'||item.action==='set_chapter_outline'){
                const id=item.args.episode_id||item.args.chapter_id;
                const data=await api(route(outlinePath(id)),{cache:'no-store'});
                if(data.project_id!==projectId||data.parent_id!==id)return null;
                if(state.selection.nodeId===id&&state.documentPane==='outline')state.outlineRecord=data;
                return data.outline_markdown||'';
            }
            const scope=item.action==='update_scene'?'scene':item.action==='replace_segment_text'?'segment':item.action==='update_chapter'?'chapter':'root';
            const id=scope==='scene'?item.args.scene_id:scope==='segment'?item.args.segment_id:scope==='chapter'?item.args.chapter_id:'';
            const data=await api(route('/view',{scope,node_id:id,limit:1}),{cache:'no-store'});
            if(scope==='scene')return data.blocks?.[0]?.editable_markdown??data.blocks?.[0]?.body_markdown??'';
            return data.blocks?.[0]?.body_markdown??'';
        }catch(_){return null;}
    }
    async function saveInlineBatch(options){
        const explicit=options?.explicit===true;
        if(state.inlineSaving)return false;
        if(state.inlineComposing.size){clearTimeout(state.inlineTimer);return false;}
        const pending=state.inlinePending;
        let items;
        if(pending){
            if(!explicit)return false;
            items=pending.snapshots.map(snapshot=>state.inlineDrafts.get(snapshot.key)).filter(Boolean);
        }else{
            items=[...state.inlineDrafts.values()].filter(item=>item.dirty);
            if(!items.length)return !inlineHasDirty();
            const unresolved=items.filter(item=>item.conflicted&&!item.conflictAcknowledged);
            if(unresolved.length)return false;
            const payload=commandPayload('batch',{operations:items.map(inlineOperation)} ,null,state.revision);
            state.inlinePending={payload,snapshots:items.map(item=>({key:item.key,value:item.value}))};
        }
        if(!items.length)return false;
        clearTimeout(state.inlineTimer);state.inlineSaving=true;setInlineSaving(items,true);
        for(const item of items){item.error='';updateInlineFieldNode(item.key);}
        let succeeded=false;
        try{
            const payload=state.inlinePending.payload;let receipt;
            try{receipt=await post(root+'/commands',payload);}
            catch(error){
                if(error.status===409){
                    await readCurrentInlineRevision();
                    for(const item of items){item.conflicted=true;item.conflictAcknowledged=false;item.error=L('作品已在别处更新。请对照最新正文，必要时先合并，再明确确认保存。','This work changed elsewhere. Compare the latest text, merge if needed, then explicitly confirm saving this draft.');item.remoteBody=await fetchInlineRemote(item);updateInlineFieldNode(item.key);}
                    state.inlinePending=null;state.remoteChanged=true;return false;
                }
                if(error.status&&error.status<500){state.inlinePending=null;throw error;}
                try{receipt=await api(root+'/commands/'+encodeURIComponent(payload.request_id));}
                catch(_){for(const item of items){item.uncertain=true;item.error=L('保存结果暂时无法确认。草稿仍保留；重试会恢复同一请求。','The save result is not confirmed. Your draft is safe; retry will recover the same request.');updateInlineFieldNode(item.key);}return false;}
            }
            if(!validCommandReceipt(receipt,payload)){
                for(const item of items){item.uncertain=true;item.error=L('保存结果暂时无法确认。草稿仍保留；重试会恢复同一请求。','The save result is not confirmed. Your draft is safe; retry will recover the same request.');updateInlineFieldNode(item.key);}
                return false;
            }
            setRevision(receipt.revision);
            for(const snapshot of state.inlinePending.snapshots){
                const item=state.inlineDrafts.get(snapshot.key);if(!item)continue;
                item.savedBody=snapshot.value;item.dirty=item.value!==snapshot.value;item.conflicted=false;item.conflictAcknowledged=false;item.uncertain=false;item.error='';item.remoteBody=null;
            }
            state.inlinePending=null;state.remoteChanged=false;succeeded=true;
            await refreshInlineAfterSave();
            return true;
        }catch(error){
            for(const item of items){item.error=error.message||L('保存失败，草稿仍保留，可重试。','Save failed. Your draft is safe and can be retried.');item.uncertain=false;updateInlineFieldNode(item.key);}
            return false;
        }finally{
            state.inlineSaving=false;setInlineSaving(items,false);
            if(succeeded&&[...state.inlineDrafts.values()].some(item=>item.dirty&&!item.conflicted&&!item.uncertain)){
                clearTimeout(state.inlineTimer);state.inlineTimer=setTimeout(()=>{void saveInlineBatch();},800);
            }
        }
    }
    async function refreshInlineAfterSave(){
        const epoch=state.requestEpoch,scopeKey=inlineScopeKey(),loadedCount=Math.max(1,state.blocks.length);
        try{
            const summary=await api(root,{cache:'no-store'});if(epoch!==state.requestEpoch)return;
            state.summary=summary;setRevision(summary.revision);$('smProjectName').textContent=projectName();renderDirectory();
            if(state.documentPane==='outline'&&outlineEligible()){
                await loadOutlinePane({epoch});
                return;
            }
            const params={scope:state.selection.scope,node_id:state.selection.nodeId,limit:30};
            let data=await api(route('/view',params),{cache:'no-store'});if(epoch!==state.requestEpoch||scopeKey!==inlineScopeKey())return;
            const blocks=[...(data.blocks||[])];
            while(blocks.length<loadedCount&&data.has_more&&data.next_cursor){
                data=await api(route('/view',{...params,cursor:data.next_cursor}),{cache:'no-store'});
                if(epoch!==state.requestEpoch||scopeKey!==inlineScopeKey())return;
                blocks.push(...(data.blocks||[]));
            }
            setRevision(data.revision);state.cursor=data.next_cursor||'';state.blocks=blocks;
            updateHeading();if(isNovel)renderNovelBlocks(blocks,false);else renderScriptBlocks(blocks,false);
            $('smLoadMoreButton').hidden=!data.has_more;$('smLoadMoreButton').disabled=false;$('smLoadMoreButton').textContent=L('继续加载','Load more');
            void loadCharacterCount(blocks,state.cursor,Boolean(data.has_more),Number(data.revision),{scope:state.selection.scope,nodeId:state.selection.nodeId});
        }catch(_){/* 成功回执已经确认；刷新失败不回滚草稿或保存状态。 */}
    }
    function handleInlineInput(event){
        const input=event.target.closest('.sm-inline-input');if(!input)return;
        const item=state.inlineDrafts.get(input.dataset.inlineKey);if(!item)return;
        item.value=input.value;item.dirty=item.value!==item.savedBody;
        if(!item.conflicted&&!item.uncertain)item.error='';
        updateInlineFieldNode(item.key);
        updateCharacterCount();
        if(!item.dirty){
            const otherDirty=[...state.inlineDrafts.values()].some(row=>row.dirty&&!row.conflicted&&!row.uncertain);
            clearTimeout(state.inlineTimer);
            if(otherDirty&&!state.inlineComposing.size)state.inlineTimer=setTimeout(()=>{void saveInlineBatch();},800);
            return;
        }
        if(event.isComposing||state.inlineComposing.has(item.key))return;
        if(!item.conflicted&&!item.uncertain){clearTimeout(state.inlineTimer);state.inlineTimer=setTimeout(()=>{void saveInlineBatch();},800);}
    }
    async function confirmInlineConflict(key){
        const item=state.inlineDrafts.get(key);if(!item||!item.conflicted)return;
        item.conflictAcknowledged=true;
        const remaining=[...state.inlineDrafts.values()].some(row=>row.conflicted&&!row.conflictAcknowledged);
        updateInlineFieldNode(key);
        if(!remaining){for(const row of state.inlineDrafts.values())if(row.conflicted)row.conflicted=false;await saveInlineBatch();}
    }
    function reloadInlineLatest(key){
        const item=state.inlineDrafts.get(key);if(!item||item.remoteBody==null)return;
        const input=[...$('smReader').querySelectorAll('.sm-inline-input')].find(node=>node.dataset.inlineKey===key),focused=input&&document.activeElement===input,start=input?.selectionStart??0,end=input?.selectionEnd??0;
        item.value=item.remoteBody;item.savedBody=item.remoteBody;item.remoteBody=null;item.dirty=false;item.conflicted=false;item.conflictAcknowledged=false;item.staleOnly=false;item.error='';
        if(input){input.value=item.value;if(focused){input.focus();input.setSelectionRange(Math.min(start,input.value.length),Math.min(end,input.value.length));}}
        updateInlineFieldNode(key);
        updateCharacterCount();
    }
    function optimizationApiBase(){return'/api/studio/'+(isNovel?'novels':'scripts');}
    function optimizationSettingsId(){return isNovel?'novel-settings':'script-settings';}
    function optimizationOperationId(prefix){const random=(crypto.randomUUID?crypto.randomUUID():Date.now()+'_'+Math.random().toString(36).slice(2)).replace(/[^A-Za-z0-9_-]/g,'');return prefix+'_'+random;}
    async function readOptimizationSource(item){
        const spec=item.optimization;if(!spec)return null;
        if(spec.scope==='episode_outline'||spec.scope==='chapter_outline'){
            const record=await api(route(outlinePath(spec.sourceId)),{cache:'no-store'});
            if(record.project_id!==projectId||record.parent_id!==spec.sourceId||record.selected_revision!=='current'||Number(record.outline_revision)!==Number(record.current_outline_revision))throw new Error(L('章纲已切换或更新，请刷新后再试。','The outline changed or is no longer current. Refresh and try again.'));
            return{body:String(record.outline_markdown||''),sha256:String(record.outline_sha256||''),revision:Number(record.revision),sourceRevision:Number(record.outline_revision)};
        }
        const scope=spec.scope,id=spec.sourceId;
        if(scope==='scene'||scope==='segment'){
            const sceneId=scope==='scene'?id:findScene(id)?.scene?.id;
            if(!sceneId)throw new Error(L('场次已不在当前目录中，请刷新后再试。','The scene is no longer in this outline. Refresh and try again.'));
            const data=await api(route('/scenes/'+enc(sceneId)),{cache:'no-store'}),scene=data.scene;
            if(data.project_id!==projectId||scene?.id!==sceneId||scene.selected_revision!=='current')throw new Error(L('场次已切换或更新，请刷新后再试。','The scene changed or is no longer current. Refresh and try again.'));
            const segment=scope==='segment'?(scene.segments||[]).find(item=>item.id===id):null;
            if(scope==='segment'&&!segment)throw new Error(L('分段已不在当前场次中，请刷新后再试。','The segment is no longer in this scene. Refresh and try again.'));
            return{body:String(scope==='scene'?(scene.editable_markdown??scene.body_markdown??''):segment.body_markdown||''),sha256:String(scene.content_sha256||''),revision:Number(data.revision),sourceRevision:Number(scene.revision)};
        }
        if(scope==='chapter'){
            const data=await api(route('/chapters/'+enc(id)),{cache:'no-store'}),chapter=data.chapter;
            if(data.project_id!==projectId||chapter?.id!==id)throw new Error(L('章节已不在当前目录中，请刷新后再试。','The chapter is no longer in this outline. Refresh and try again.'));
            return{body:String(chapter.body_markdown||''),sha256:String(chapter.content_sha256||''),revision:Number(data.revision),sourceRevision:Number(chapter.revision)};
        }
        throw new Error(L('不支持此文本优化范围。','This text scope cannot be optimized.'));
    }
    async function readTextOptimizationOutputNode(){
        const moduleName=isNovel?'novels':'scripts',expectedId=optimizationSettingsId();
        const payload=await api(`/api/studio/${moduleName}/settings-canvas`,{cache:'no-store'});
        if(payload?.id!==expectedId||payload?.canvas?.id!==expectedId)throw new Error(L('文本优化配置图身份不匹配，请在 API 设置中重新读取。','The text optimization canvas identity did not match. Reload it from API settings.'));
        const nodes=Array.isArray(payload.canvas.nodes)?payload.canvas.nodes:[];
        const outputs=nodes.filter(node=>node?.type==='smart-hypit-output'&&node?.hypitSlot==='text');
        if(outputs.length!==1)throw new Error(L('请先在 API 设置的对应模块配置图中添加一个文本输出。','Add one text output in this module’s API settings canvas first.'));
        const output=outputs[0],connections=Array.isArray(payload.canvas.connections)?payload.canvas.connections:[];
        if(!connections.some(edge=>edge?.to===output.id&&['input','flow'].includes(edge.kind||'flow')))throw new Error(L('请先把文本生成节点连接到文本输出，再开始优化。','Connect a text-generation node to the text output before optimizing.'));
        return String(output.id||'');
    }
    function closeOptimizationDialog(){
        const dialog=state.optimizationDialog;if(!dialog)return;
        state.optimizationDialog=null;dialog.overlay.remove();document.body.classList.remove('sm-optimization-open');
        if(dialog.returnFocus?.isConnected)dialog.returnFocus.focus();
    }
    function renderOptimizationDialog(run){
        const dialog=state.optimizationDialog;if(!dialog||dialog.key!==run.key)return;
        persistOptimizationRun(run);
        const status=optimizationStatusText(run);
        dialog.status.textContent=run.error||status;
        dialog.status.dataset.state=run.phase;
        dialog.source.value=run.sourceBody||'';
        dialog.result.value=run.resultText||'';
        dialog.result.hidden=!run.resultText;
        dialog.resultLabel.hidden=!run.resultText;
        const busy=['submitting','running','applying'].includes(run.phase);
        dialog.runButton.disabled=busy;
        dialog.runButton.textContent=run.phase==='preview'||run.phase==='error'?L('再次优化','Run again'):L('运行优化','Run optimization');
        dialog.recoverButton.hidden=!['uncertain','running','apply-uncertain'].includes(run.phase)&&!(run.phase==='preview'&&run.resultId&&!run.resultText);
        dialog.recoverButton.disabled=busy;
        dialog.recoverButton.textContent=run.phase==='apply-uncertain'?L('恢复采用请求','Recover adoption'):L('恢复同一任务','Recover same run');
        dialog.applyButton.hidden=run.phase!=='preview';
        dialog.applyButton.disabled=run.applyBlocked===true||run.phase==='applying';
        dialog.applyButton.textContent=run.phase==='applying'?L('正在采用…','Applying…'):L('采用这版正文','Apply this version');
        dialog.prompt.disabled=busy||run.phase==='uncertain'||run.phase==='apply-uncertain';
        updateInlineFieldNode(run.key);
    }
    function openOptimizationDialog(item,source){
        closeOptimizationDialog();
        const existing=state.optimizationRuns.get(item.key);
        const run=existing||{key:item.key,phase:'draft',sourceBody:source.body,sourceSha256:source.sha256,sourceRevision:source.sourceRevision,projectRevision:source.revision,prompt:'',resultText:'',resultId:'',error:''};
        if(!existing){run.sourceBody=source.body;run.sourceSha256=source.sha256;run.sourceRevision=source.sourceRevision;run.projectRevision=source.revision;state.optimizationRuns.set(item.key,run);}
        const overlay=document.createElement('div');overlay.className='sm-optimization-overlay';overlay.dataset.optimizationDialog='true';
        const panel=document.createElement('section');panel.className='sm-optimization-dialog';panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-labelledby','smOptimizationTitle');panel.tabIndex=-1;
        const header=document.createElement('header');header.className='sm-optimization-heading';
        const title=document.createElement('h2');title.id='smOptimizationTitle';title.textContent=L('文本优化','Text optimization');
        const close=document.createElement('button');close.type='button';close.className='sm-inline-action';close.textContent=L('关闭','Close');close.setAttribute('aria-label',L('关闭文本优化','Close text optimization'));
        header.append(title,close);
        const intro=document.createElement('p');intro.className='sm-optimization-intro';intro.textContent=L('结果会先单独预览；确认采用后才会替换当前正文。','The result is shown separately first. The current text changes only after you apply it.');
        const promptLabel=document.createElement('label');promptLabel.className='sm-optimization-label';promptLabel.textContent=L('本次优化要求','Your request');
        const prompt=document.createElement('textarea');prompt.className='sm-optimization-prompt';prompt.rows=3;prompt.value=run.prompt||L('请优化这段文字，保持原意、人物设定、事实与 Markdown 结构。','Improve this text while preserving its meaning, character details, facts, and Markdown structure.');
        const sourceLabel=document.createElement('label');sourceLabel.className='sm-optimization-label';sourceLabel.textContent=L('当前保存的原文','Currently saved source');
        const sourceArea=document.createElement('textarea');sourceArea.className='sm-optimization-preview';sourceArea.readOnly=true;sourceArea.setAttribute('aria-label',sourceLabel.textContent);
        const resultLabel=document.createElement('label');resultLabel.className='sm-optimization-label';resultLabel.textContent=L('优化结果预览','Optimized result preview');resultLabel.hidden=true;
        const resultArea=document.createElement('textarea');resultArea.className='sm-optimization-preview';resultArea.readOnly=true;resultArea.setAttribute('aria-label',resultLabel.textContent);resultArea.hidden=true;
        const status=document.createElement('p');status.className='sm-optimization-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
        const actions=document.createElement('div');actions.className='sm-optimization-actions';
        const recoverButton=document.createElement('button');recoverButton.type='button';recoverButton.className='sm-inline-action';
        const runButton=document.createElement('button');runButton.type='button';runButton.className='sm-inline-action sm-optimization-primary';
        const applyButton=document.createElement('button');applyButton.type='button';applyButton.className='sm-inline-action sm-optimization-primary';
        const cancelButton=document.createElement('button');cancelButton.type='button';cancelButton.className='sm-inline-action';cancelButton.textContent=L('关闭','Close');
        actions.append(recoverButton,runButton,applyButton,cancelButton);
        panel.append(header,intro,promptLabel,prompt,sourceLabel,sourceArea,resultLabel,resultArea,status,actions);overlay.append(panel);document.body.append(overlay);document.body.classList.add('sm-optimization-open');
        const returnFocus=[...$('smReader').querySelectorAll('[data-inline-optimize]')].find(button=>button.dataset.inlineOptimize===item.key);
        state.optimizationDialog={key:item.key,overlay,panel,prompt,source:sourceArea,result:resultArea,resultLabel,status,runButton,recoverButton,applyButton,returnFocus};
        close.addEventListener('click',closeOptimizationDialog);cancelButton.addEventListener('click',closeOptimizationDialog);
        overlay.addEventListener('click',event=>{if(event.target===overlay)closeOptimizationDialog();});
        panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();closeOptimizationDialog();}});
        runButton.addEventListener('click',()=>{void submitTextOptimization(item.key);});
        recoverButton.addEventListener('click',()=>{void recoverTextOptimization(item.key);});
        applyButton.addEventListener('click',()=>{void applyTextOptimization(item.key);});
        run.prompt=prompt.value;renderOptimizationDialog(run);prompt.focus();
        if(['running','uncertain','applied'].includes(run.phase)||(run.phase==='preview'&&run.resultId&&!run.resultText))void recoverTextOptimization(item.key);
    }
    async function openTextOptimization(key){
        const item=state.inlineDrafts.get(key);if(!item?.optimization)return;
        const existing=state.optimizationRuns.get(key);
        if(existing&&['submitting','running','uncertain','preview','applying','apply-uncertain','applied','error'].includes(existing.phase)
            &&(existing.requestBody||existing.runId||existing.resultText)){
            openOptimizationDialog(item,{body:existing.sourceBody||'',sha256:existing.sourceSha256||'',sourceRevision:existing.sourceRevision,revision:existing.projectRevision});
            return;
        }
        if(inlineHasDirty()){
            const saved=await saveInlineBatch({explicit:true});
            if(!saved||inlineHasDirty()){
                item.error=L('先解决未保存的正文，再运行文本优化。','Resolve unsaved text before running optimization.');updateInlineFieldNode(key);return;
            }
        }
        try{
            const source=await readOptimizationSource(item);
            if(source.body!==item.savedBody||(item.optimization.sourceRevision!=null&&Number(source.sourceRevision)!==Number(item.optimization.sourceRevision))){item.conflicted=true;item.conflictAcknowledged=false;item.staleOnly=true;item.remoteBody=source.body;item.error=L('正文已在别处更新。读取最新正文后，再运行文本优化。','This text changed elsewhere. Read the latest text before optimizing.');updateInlineFieldNode(key);return;}
            if(!source.body.trim())throw new Error(L('先填写并保存正文或章纲，再运行文本优化。','Write and save the text or outline before optimizing.'));
            if(!source.sha256&&item.optimization.scope!=='episode_outline'&&item.optimization.scope!=='chapter_outline')throw new Error(L('正文摘要无效，请重新读取作品。','The text digest is missing. Refresh the work and try again.'));
            item.optimization.sourceSha256=source.sha256;item.optimization.sourceRevision=source.sourceRevision;setRevision(source.revision);
            openOptimizationDialog(item,source);
        }catch(error){item.error=error.message||L('无法读取当前正文。','Could not read the current text.');updateInlineFieldNode(key);}
    }
    async function submitTextOptimization(key){
        const dialog=state.optimizationDialog,item=state.inlineDrafts.get(key);if(!dialog||dialog.key!==key||!item?.optimization)return;
        const prompt=dialog.prompt.value.trim();if(!prompt){dialog.status.textContent=L('先写下本次优化要求。','Enter your request first.');dialog.prompt.focus();return;}
        if(inlineHasDirty()){
            const saved=await saveInlineBatch({explicit:true});
            if(!saved||inlineHasDirty()){dialog.status.textContent=L('正文尚未保存，已停止提交优化。草稿仍保留。','The text is not saved, so optimization was not submitted. Your draft is preserved.');return;}
        }
        let source,outputNodeId;
        try{
            source=await readOptimizationSource(item);
            if(source.body!==item.savedBody||source.sha256!==item.optimization.sourceSha256||Number(source.sourceRevision)!==Number(item.optimization.sourceRevision)){item.conflicted=true;item.remoteBody=source.body;item.error=L('正文已更新。请读取最新正文后重新打开优化。','The text changed. Read the latest text, then reopen optimization.');updateInlineFieldNode(key);dialog.status.textContent=item.error;return;}
            if(!source.body.trim())throw new Error(L('正文为空，无法优化。','The source is empty and cannot be optimized.'));
            outputNodeId=await readTextOptimizationOutputNode();
        }catch(error){dialog.status.textContent=error.message||L('无法读取文本优化配置。','Could not read text optimization settings.');return;}
        setRevision(source.revision);
        const sourceObjectSha256=await sha256Text(source.body);
        const run={key,phase:'submitting',sourceBody:source.body,sourceSha256:source.sha256,sourceRevision:source.sourceRevision,projectRevision:source.revision,
            sourceObjectSha256,scope:item.optimization.scope,sourceId:item.optimization.sourceId,outputNodeId,prompt,
            requestBody:{scope:item.optimization.scope,source_id:item.optimization.sourceId,expected_source_sha256:source.sha256,output_node_id:outputNodeId,
                expected_source_revision:source.sourceRevision,client_operation_id:optimizationOperationId('ui_optimize'),request:{prompt},base_revision:source.revision},
            resultId:'',resultText:'',error:'',applyRequestId:'',applyBlocked:false};
        state.optimizationRuns.set(key,run);renderOptimizationDialog(run);
        await sendTextOptimization(run);
    }
    async function validateOptimizationRunResponse(run,payload){
        const acceptedRevision=Number(payload?.accepted_revision),sourceRevision=Number(payload?.source_revision),settingsRevision=Number(payload?.settings_revision);
        if(payload?.project_id!==projectId||payload?.module_id!==(isNovel?'novel':'script')||payload?.purpose!=='optimize'
            ||payload?.scope!==run.scope||payload?.source_id!==run.sourceId||payload?.client_operation_id!==run.requestBody.client_operation_id
            ||payload?.slot!=='text'||payload?.output_node_id!==run.outputNodeId||!payload?.run_id
            ||payload?.source_sha256!==run.sourceSha256||sourceRevision!==Number(run.sourceRevision)
            ||payload?.source_object_sha256!==run.sourceObjectSha256
            ||!Number.isSafeInteger(acceptedRevision)||acceptedRevision!==Number(run.projectRevision)
            ||!Number.isSafeInteger(settingsRevision)||settingsRevision<0){
            throw new Error(L('服务返回的优化任务与当前正文不匹配；未采用任何结果。','The service returned a run for a different source. Nothing was applied.'));
        }
        run.runId=String(payload.run_id);
        const status=String(payload.status||'').toLowerCase();
        run.phase=['failed','cancelled','canceled','rejected'].includes(status)?'error':'running';
        if(run.phase==='error')run.error=payload.error?.message||payload.error||L('优化任务未成功完成。','The optimization run did not succeed.');
    }
    async function sendTextOptimization(run){
        try{
            const payload=await api(root+'/generations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(run.requestBody)});
            await validateOptimizationRunResponse(run,payload);
            run.error=run.sourceChanged?L('原文已变化，结果可预览，但不能覆盖新正文。','The source changed. You can preview the result, but it cannot replace the newer text.'):'';
            renderOptimizationDialog(run);await pollTextOptimization(run);
        }catch(error){
            if(error.status&&error.status<500){run.phase='error';run.error=error.status===409?L('正文或配置已变化；请重新读取后再开始优化。','The source or settings changed. Refresh before starting again.'):error.message;}
            else{run.phase='uncertain';run.error=L('暂时无法确认任务是否已提交；恢复会使用同一请求，不会新建任务。','The submission is unconfirmed. Recovery reuses the same request and will not create a second run.');}
            renderOptimizationDialog(run);
        }
    }
    async function recoverTextOptimization(key){
        const run=state.optimizationRuns.get(key);if(!run||state.optimizationDialog?.key!==key)return;
        if(run.phase==='apply-uncertain'){await applyTextOptimization(key,true);return;}
        if(run.runId){
            if(!run.applied){
                try{
                    const item=state.inlineDrafts.get(key),current=item?await readOptimizationSource(item):null;
                    if(current&&current.sha256===run.sourceSha256&&Number(current.sourceRevision)===Number(run.sourceRevision)){
                        run.sourceBody=current.body;run.sourceChanged=false;run.applyBlocked=false;
                    }else{
                        run.sourceBody='';run.sourceChanged=true;run.applyBlocked=true;
                        run.error=L('原文已变化，结果仍可预览，但不能覆盖新正文。','The source has changed. You can preview the result, but it cannot replace the newer text.');
                    }
                }catch(error){
                    run.sourceBody='';run.sourceChanged=true;run.applyBlocked=true;
                    run.error=error.message||L('无法核对当前原文，结果仍可恢复。','The current source could not be verified; the result can still be recovered.');
                }
            }
            run.phase='running';renderOptimizationDialog(run);await pollTextOptimization(run);return;
        }
        if(run.requestBody){
            try{
                const item=state.inlineDrafts.get(key),current=item?await readOptimizationSource(item):null;
                const objectDigest=current?await sha256Text(current.body):'';
                if(current&&current.sha256===run.sourceSha256&&Number(current.sourceRevision)===Number(run.sourceRevision)
                    &&(!run.sourceObjectSha256||objectDigest===run.sourceObjectSha256)){
                    run.sourceBody=current.body;run.sourceChanged=false;run.applyBlocked=false;
                }else{
                    run.sourceBody='';run.sourceChanged=true;run.applyBlocked=true;
                    run.error=L('原文已变化，仍会恢复原任务，但不能采用其结果覆盖新正文。','The source changed. The original run will still be recovered, but its result cannot replace the newer text.');
                }
            }catch(error){
                run.sourceBody='';run.sourceChanged=true;run.applyBlocked=true;
                run.error=error.message||L('无法核对当前原文，仍会恢复原任务。','Could not verify the current source; the original run will still be recovered.');
            }
            run.phase='submitting';renderOptimizationDialog(run);await sendTextOptimization(run);
        }
    }
    async function pollTextOptimization(run){
        if(run.pollPromise)return run.pollPromise;
        run.pollPromise=(async()=>{
            const path=root+'/generations/'+enc(run.runId);
            while(state.optimizationDialog?.key===run.key){
                try{
                    const payload=await api(path,{cache:'no-store'});
                    if(payload?.project_id!==projectId||payload?.run_id!==run.runId||payload?.module_id!==(isNovel?'novel':'script')
                        ||payload?.purpose!=='optimize'||payload?.scope!==run.scope||payload?.source_id!==run.sourceId
                        ||payload?.client_operation_id!==run.requestBody?.client_operation_id||payload?.slot!=='text'
                        ||payload?.source_sha256!==run.sourceSha256||Number(payload?.source_revision)!==Number(run.sourceRevision)
                        ||payload?.source_object_sha256!==run.sourceObjectSha256)throw new Error(L('服务返回的任务状态与当前正文不匹配。','The task status did not match the selected text.'));
                    const status=String(payload.status||'').toLowerCase();
                    if(status==='succeeded'){
                        const result=(payload.media||[]).find(item=>String(item.kind||'').toLowerCase()==='text'&&(item.result_id||item.resultId));
                        const resultId=String(result?.result_id||result?.resultId||'');
                        let text=typeof result?.text==='string'?result.text:typeof result?.content==='string'?result.content:'';
                        if(!resultId)throw new Error(L('任务完成，但没有可读取的文本结果。','The run completed without a managed text result.'));
                        if(!text){const response=await fetch('/api/results/'+enc(resultId),{cache:'no-store'});if(!response.ok)throw new Error(L('文本结果暂时无法读取；请稍后恢复同一任务。','The text result is not available yet. Recover the same run later.'));text=await response.text();}
                        if(!text.trim())throw new Error(L('文本结果为空，不能采用。','The text result is empty and cannot be applied.'));
                        run.resultId=resultId;run.resultText=text;run.phase=run.applied?'applied':'preview';if(!run.sourceChanged)run.error='';renderOptimizationDialog(run);return;
                    }
                    if(['failed','cancelled','canceled','rejected'].includes(status)){run.phase='error';run.error=payload.error?.message||payload.error||L('优化任务未成功完成。','The optimization run did not succeed.');renderOptimizationDialog(run);return;}
                    run.phase='running';run.error='';renderOptimizationDialog(run);
                }catch(error){run.phase='uncertain';run.error=error.message||L('读取任务状态失败，可恢复同一任务。','Could not read run status. Recover the same run.');renderOptimizationDialog(run);return;}
                await new Promise(resolve=>setTimeout(resolve,1200));
            }
        })().finally(()=>{run.pollPromise=null;});
        return run.pollPromise;
    }
    async function applyTextOptimization(key,recover=false){
        const run=state.optimizationRuns.get(key),item=state.inlineDrafts.get(key),dialog=state.optimizationDialog;
        if(!run||!item||!dialog||dialog.key!==key||!run.runId||!run.resultId||!run.resultText)return;
        if(!recover){
            if(item.dirty||item.conflicted||item.uncertain||inlineHasDirty()){
                run.error=L('请先保存当前正文草稿，再采用优化结果。','Save the current text draft before applying the result.');renderOptimizationDialog(run);return;
            }
            try{
                const current=await readOptimizationSource(item);
                if(current.body!==run.sourceBody||current.sha256!==run.sourceSha256||Number(current.sourceRevision)!==Number(run.sourceRevision)){run.phase='preview';run.applyBlocked=true;run.sourceChanged=true;run.error=L('原文已经变化，不能把此结果覆盖到新正文。可保留预览并重新运行优化。','The source changed, so this result cannot replace the newer text. Keep the preview or run optimization again.');renderOptimizationDialog(run);return;}
                run.applyRevision=current.revision;
            }catch(error){run.phase='preview';run.error=error.message||L('无法核对当前正文。','Could not verify the current text.');renderOptimizationDialog(run);return;}
        }
        if(!run.applyRequestId)run.applyRequestId=optimizationOperationId('ui_apply');
        run.phase='applying';run.error='';renderOptimizationDialog(run);
        const body={result_id:run.resultId,request_id:run.applyRequestId};
        try{
            const receipt=await api(root+'/generations/'+enc(run.runId)+'/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
            const revision=Number(receipt?.revision);
            if(receipt?.status!=='succeeded'||receipt?.request_id!==run.applyRequestId||receipt?.project_id!==projectId||receipt?.generation_run_id!==run.runId||receipt?.result_id!==run.resultId||receipt?.source_scope!==run.scope||receipt?.source_id!==run.sourceId||receipt?.source_sha256!==run.sourceSha256||!Number.isSafeInteger(revision)||revision<=Number(run.applyRevision||run.projectRevision))throw new Error(L('采用回执无法核验；请恢复同一采用请求，原文草稿已保留。','The adoption receipt could not be verified. Recover the same request; the source draft is preserved.'));
            setRevision(revision);item.value=run.resultText;item.savedBody=run.resultText;item.dirty=false;item.conflicted=false;item.uncertain=false;item.error='';item.remoteBody=null;
            run.phase='applied';run.applied=true;run.error='';run.applyBlocked=false;updateInlineFieldNode(key);renderOptimizationDialog(run);await refreshInlineAfterSave();
            try{const updated=await readOptimizationSource(item);item.optimization.sourceSha256=updated.sha256;item.optimization.sourceRevision=updated.sourceRevision;}catch(_){/* The saved result remains authoritative; the next open will re-read it. */}
        }catch(error){
            if(error.status===409){run.phase='preview';run.applyBlocked=true;run.error=L('原文已更新，此结果没有覆盖新内容。保留结果预览后可重新运行优化。','The source changed. This result did not replace it. Keep the preview or run optimization again.');}
            else if(error.status&&error.status<500){run.phase='preview';run.error=error.message||L('无法采用这份结果。','Could not apply this result.');}
            else{run.phase='apply-uncertain';run.error=L('采用状态暂时无法确认；恢复会使用同一请求，不会重复写入。','Adoption is unconfirmed. Recovery reuses the same request and will not apply it twice.');}
            renderOptimizationDialog(run);
        }
    }
    function updateOptimizationFromInput(key){
        const run=state.optimizationRuns.get(key);if(run?.phase==='preview'||run?.phase==='applied')return;
        updateInlineFieldNode(key);
    }
    async function copyInlineDraft(key){
        const item=state.inlineDrafts.get(key);if(!item)return;
        try{await navigator.clipboard.writeText(item.value);showCopyFeedback('draft-copied');}
        catch(_){showCopyFeedback('copy-error');}
    }
    async function saveEditor(){
        if(!state.editor||state.saving||state.conflicted)return;
        clearTimeout(state.saveTimer);
        let saveSucceeded=false;
        state.saving=true;$('smSaveState').textContent=L('正在保存…','Saving…');$('smRetrySaveButton').hidden=true;setEditorError('');
        try{
            const submittedBody=bodyText();
            const operation=await buildCommand();
            if(!operation){state.dirty=false;$('smSaveState').textContent=L('已保存','Saved');state.saving=false;return true;}
            const payload=state.pendingSave?.body===submittedBody?state.pendingSave.payload:commandPayload(operation.action,operation.args);
            state.pendingSave={body:submittedBody,payload:payload};
            let receipt;
            try{receipt=await post(root+'/commands',payload);}
            catch(error){
                if(error.status===409){state.conflicted=true;throw error;}
                /* 命令写入结果不确定时，恢复同一个 request_id，避免提交不同正文覆盖原请求。 */
                try{receipt=await api(root+'/commands/'+encodeURIComponent(payload.request_id));}
                catch(receiptError){throw new Error(L('保存结果暂时无法确认。草稿仍在编辑框中；点“重试保存”可查询或恢复同一条命令。','The save result is not confirmed. Your draft remains here; Retry save will recover the same command.'));}
            }
            const receiptRevision=Number(receipt?.revision);
            if(receipt?.status!=='succeeded'||receipt.request_id!==payload.request_id||receipt.project_id!==projectId||!Number.isSafeInteger(receiptRevision)||receiptRevision<=Number(payload.expected_revision)){
                throw new Error(L('保存结果暂时无法确认。草稿仍在编辑框中；点“重试保存”可查询或恢复同一条命令。','The save result is not confirmed. Your draft remains here; Retry save will recover the same command.'));
            }
            setRevision(receiptRevision);state.editor.baseRevision=receiptRevision;state.editor.original=submittedBody;
            state.pendingSave=null;state.dirty=bodyText()!==submittedBody;state.conflicted=false;$('smSaveState').textContent=state.dirty?L('有未保存修改','Unsaved changes'):L('已保存','Saved');
            saveSucceeded=true;
            await refreshAfterSave();
            return true;
        }catch(error){
            const isConflict=error.status===409;
            state.conflicted=isConflict;
            const hint=isConflict
                ?L('保存冲突：此作品已在另一处更新。草稿仍保留在编辑框中；复制后重新读取并手动合并。','Save conflict: this work changed elsewhere. Your draft remains here. Copy it, reload the current text, and merge manually.')
                :(error.message||L('保存失败。草稿仍保留在编辑框中，可重试。','Save failed. Your draft remains here and can be retried.'));
            setEditorError(hint);$('smSaveState').textContent=isConflict?L('有冲突','Conflict'):L('未保存','Not saved');
            return false;
        }finally{state.saving=false;if(saveSucceeded&&state.dirty&&!state.conflicted){clearTimeout(state.saveTimer);state.saveTimer=setTimeout(()=>{void saveEditor();},800);}}
    }
    async function refreshAfterSave(){
        try{
            if(isNovel&&state.tab==='settings'){
                await loadSettingsIndex(state.settingsCategory);
                if(state.editor?.mode==='setting-revision')await loadSetting(state.editor.entryId,state.editor.versionId);
                else if(state.editor?.mode==='handoff')await loadHandoff();
            }else{
                await api(root).then(data=>{state.summary=data;setRevision(data.revision);$('smProjectName').textContent=projectName();});
                renderDirectory();
                if(state.selection.scope==='root'&&state.summary?.state==='draft'){
                    state.blocks=[];await loadView(false);
                }else await loadView(false);
            }
        }catch(e){/* 已保存的正文不会因目录刷新失败而回滚；页面保留编辑器草稿。 */}
        $('smEditor').hidden=false;$('smReader').hidden=true;
    }
    function scheduleSave(event){
        if(!state.editor||state.conflicted)return;
        state.dirty=bodyText()!==state.editor.original;
        if(!state.dirty){clearTimeout(state.saveTimer);$('smSaveState').textContent=L('已保存','Saved');$('smEditorError').hidden=true;return;}
        $('smSaveState').textContent=L('有未保存修改','Unsaved changes');$('smEditorError').hidden=true;
        if(event?.isComposing||state.composing)return;
        clearTimeout(state.saveTimer);state.saveTimer=setTimeout(()=>{void saveEditor();},800);
    }
    async function closeEditor(){
        if(state.saving){return;}
        if(state.dirty&&!state.conflicted){const saved=await saveEditor();if(!saved)return;}
        if(state.dirty||state.conflicted)return;
        clearTimeout(state.saveTimer);state.editor=null;state.pendingSave=null;$('smEditor').hidden=true;$('smReader').hidden=false;$('smSaveState').textContent='';
        updateHeading();$('smEditButton').focus();
    }
    async function copyDraft(){
        try{await navigator.clipboard.writeText(bodyText());setStatus(L('草稿已复制。','Draft copied.'),'success');}
        catch(e){$('smMarkdownInput').focus();$('smMarkdownInput').select();setStatus(L('自动复制不可用，草稿已选中，可按 Command/Ctrl+C 复制。','Clipboard unavailable. The draft is selected; press Command/Ctrl+C to copy it.'));}
    }
    async function reloadAfterConflict(){
        if(!window.confirm(L('重新读取会丢弃当前草稿。请先复制需要保留的文字。是否继续？','Reloading will discard the draft. Copy any text you want to keep first. Continue?')))return;
        clearTimeout(state.saveTimer);state.editor=null;state.dirty=false;state.conflicted=false;state.pendingSave=null;state.remoteChanged=false;
        $('smEditor').hidden=true;$('smReader').hidden=false;setEditorError('');$('smSaveState').textContent='';
        await refreshPage();
    }
    async function selectDirectory(event){
        const menuAction=event.target.closest('[data-outline-menu-action]');
        if(menuAction){
            event.preventDefault();const action=menuAction.dataset.outlineMenuAction,scope=menuAction.dataset.outlineScope,id=menuAction.dataset.outlineNodeId||'';
            void beginOutlineDialog(action,scope,id,{kind:'menu',scope,id});return;
        }
        const menuToggle=event.target.closest('[data-outline-menu-toggle]');
        if(menuToggle){event.preventDefault();toggleOutlineMenu(menuToggle.dataset.outlineScope,menuToggle.dataset.outlineNodeId||'',menuToggle);return;}
        const disclosure=event.target.closest('[data-expand]');
        if(disclosure){const id=disclosure.dataset.expand;state.outlineMenu=null;state.expanded.has(id)?state.expanded.delete(id):state.expanded.add(id);renderDirectory();return;}
        const item=event.target.closest('[data-scope]');
        if(item){await selectOutline(item.dataset.scope,item.dataset.nodeId||'');return;}
        const category=event.target.closest('[data-category-id]');
        if(category){await selectSettingsCategory(category.dataset.categoryId);return;}
        const entry=event.target.closest('[data-setting-id]');
        if(entry){if(!await beforeNavigate())return;clearCopyFeedback();state.requestEpoch++;const epoch=state.requestEpoch;state.editor=null;state.dirty=false;try{state.settingRevisions=[];state.handoff=null;await loadSetting(entry.dataset.settingId);}catch(error){if(epoch===state.requestEpoch)setStatus(error.message,'error');}closeDrawerForOverlay();return;}
        const action=event.target.closest('[data-action]')?.dataset.action;
        if(action==='handoff'){if(!await beforeNavigate())return;clearCopyFeedback();state.requestEpoch++;const epoch=state.requestEpoch;state.editor=null;state.dirty=false;try{await loadHandoff();}catch(error){if(epoch===state.requestEpoch)setStatus(error.message,'error');}closeDrawerForOverlay();return;}
        if(action==='settings-more'){
        const next=state.settingsIndex?.cursor;if(next){try{await loadSettingsIndex(state.settingsCategory,next,true);}catch(error){setStatus(error.message,'error');}}return;
        }
    }
    async function refreshPage(){
        if(!await beforeNavigate())return;
        state.requestEpoch++;
        const epoch=state.requestEpoch;
        try{
            await loadSummary(true);
            if(epoch!==state.requestEpoch)return;
            if(isNovel&&state.tab==='settings'){
                if(state.setting)await loadSetting(state.setting.entry.id,state.setting.selectedVersion.id,state.historyMode?state.setting.selectedVersion.selected_edit_revision:undefined);
                else if(state.handoff)await loadHandoff();
            }
            setStatus('');
        }catch(error){if(epoch===state.requestEpoch)setStatus(error.message||L('重新读取失败','Refresh failed'),'error');}
    }
    async function syncRemote(){
        if(state.syncBusy||document.hidden||!projectId)return;
        state.syncBusy=true;
        const startEpoch=state.requestEpoch;
        try{
            const probe=await api(isNovel?root+'/manifest':root,{cache:'no-store'});
            if(startEpoch!==state.requestEpoch||Number(probe.revision||0)<=state.revision)return;
            if(state.dirty||state.saving||state.conflicted||inlineHasDirty()||state.inlineSaving||state.inlinePending){
                state.remoteChanged=true;
                setStatus(L('此作品已在其他对话更新；你的草稿仍保留。保存时会检查冲突。','This work changed in another session. Your draft is safe; saving will check for a conflict.'));
                return;
            }
            const wasEditing=Boolean(state.editor),focusEditor=document.activeElement===$('smMarkdownInput');
            const target={tab:state.tab,selection:{...state.selection},documentPane:state.documentPane,settingId:state.setting?.entry?.id,versionId:state.setting?.selectedVersion?.id,settingRevision:state.setting?.selectedVersion?.selected_edit_revision,handoffRevision:state.handoff?.record?.revision,historyMode:state.historyMode};
            state.editor=null;state.remoteChanged=false;state.requestEpoch++;
            const epoch=state.requestEpoch,data=await api(root,{cache:'no-store'});
            if(epoch!==state.requestEpoch)return;
            state.summary=data;setRevision(data.revision);$('smProjectName').textContent=projectName();
            if(target.tab==='settings'){
                await loadSettingsIndex(state.settingsCategory);
                if(epoch!==state.requestEpoch)return;
            }
            renderDirectory();
            if(target.tab==='text'){
                state.selection=target.selection;state.documentPane=target.documentPane==='outline'&&outlineEligible()?'outline':'body';state.outlineRecord=null;state.cursor='';updateDocumentPaneTabs();
                if(state.documentPane==='outline')await loadOutlinePane({epoch});else await loadView(false);
            }else if(target.settingId){
                await loadSetting(target.settingId,target.versionId,target.historyMode?target.settingRevision:undefined);
            }else if(state.handoff){
                await loadHandoff(target.historyMode?target.handoffRevision:undefined);
            }else{
                $('smScopeTitle').textContent=L('设定库','Settings');$('smScopeHint').textContent='';
                $('smBreadcrumb').innerHTML='<span aria-current="page">'+esc(L('设定库','Settings'))+'</span>';
                $('smReader').innerHTML=empty(L('选择一条设定','Choose a setting'),L('选择分类中的条目查看正文和故事阶段版本。','Choose an entry to read its text and story-stage versions.'));
                updateHeadingActions();
            }
            if(epoch!==state.requestEpoch)return;
            if(wasEditing){startEdit();if(focusEditor)$('smMarkdownInput').focus();}
            setStatus('');
        }catch(error){if(startEpoch===state.requestEpoch)setStatus(error.message||L('同步更新失败','Could not sync updates'),'error');}
        finally{state.syncBusy=false;}
    }
    function openDrawer(){
        $('smWorkspace').classList.add('sm-drawer-open');$('smWorkspace').classList.remove('is-directory-collapsed');
        $('smDirectoryToggle').setAttribute('aria-expanded','true');
        if(queryState())$('smDirectorySearch').focus();
    }
    function closeDrawer(){
        const overlay=queryState(),wasOpen=$('smWorkspace').classList.contains('sm-drawer-open');
        $('smWorkspace').classList.remove('sm-drawer-open');
        if(!overlay)$('smWorkspace').classList.add('is-directory-collapsed');
        $('smDirectoryToggle').setAttribute('aria-expanded','false');
        if(overlay&&wasOpen)$('smDirectoryToggle').focus();
    }
    function closeDrawerForOverlay(){if(queryState()&&$('smWorkspace').classList.contains('sm-drawer-open'))closeDrawer();}
    function toggleDrawer(){
        const workspace=$('smWorkspace');
        if(queryState()){workspace.classList.contains('sm-drawer-open')?closeDrawer():openDrawer();return;}
        if(workspace.classList.contains('is-directory-collapsed'))openDrawer();else closeDrawer();
    }
    function showCopyFeedback(kind){
        const feedback=$('smCopyFeedback');if(!feedback)return;
        const copyText={copied:L('已复制','Copied'),'draft-copied':L('草稿已复制','Draft copied'),'copy-error':L('复制失败，请检查剪贴板权限后重试。','Copy failed. Check clipboard permission and try again.'),'blocked-unsaved':L('正文尚未保存，已阻止复制；请先解决保存状态。','Text is not saved, so copying was stopped. Resolve the save status first.')};
        feedback.dataset.feedbackKind=kind;feedback.textContent=copyText[kind]||L('复制失败','Copy failed');feedback.className='sm-copy-feedback '+(kind==='copy-error'||kind==='blocked-unsaved'?'error':'success');feedback.hidden=false;
    }
    function clearCopyFeedback(){const feedback=$('smCopyFeedback');if(!feedback)return;feedback.hidden=true;feedback.textContent='';feedback.dataset.feedbackKind='';feedback.className='sm-copy-feedback';}
    async function copyCurrent(){
        if(state.editor)return;
        if(isNovel&&state.tab==='settings'){
            const content=state.setting?.selectedVersion?.body_markdown??state.handoff?.record?.body_markdown??'';
            if(!content){showCopyFeedback('copy-error');return;}
            try{await navigator.clipboard.writeText(content);showCopyFeedback('copied');}catch(_){showCopyFeedback('copy-error');}
            return;
        }
        const s=state.selection,key=isNovel?inlineKey('novel-chapter',s.nodeId):s.scope==='segment'?inlineKey('script-segment',s.nodeId):inlineKey('script-scene',s.nodeId);
        const bucket=state.inlineDrafts.get(key),feedback=$('smCopyFeedback');
        if(bucket?.dirty||bucket?.conflicted||bucket?.uncertain){
            const saved=await saveInlineBatch();
            if(!saved||bucket.dirty||bucket.conflicted||bucket.uncertain){showCopyFeedback('blocked-unsaved');return;}
        }
        const content=bucket?.savedBody??'';
        if(!content){showCopyFeedback('copy-error');return;}
        try{await navigator.clipboard.writeText(content);showCopyFeedback('copied');}
        catch(e){showCopyFeedback('copy-error');}
    }
    function applyLanguage(){
        const english=en();document.documentElement.lang=english?'en':'zh-CN';
        $('smModuleKicker').textContent=L(isNovel?'小说创作':'剧本创作',isNovel?'Novel Writing':'Script Writing');
        $('smRefreshButton').title=$('smRefreshButton').ariaLabel=L('重新读取','Refresh');
        $('smLanguageButton').textContent=english?'EN':'中';$('smLanguageButton').title=$('smLanguageButton').ariaLabel=L('切换语言','Switch language');
        $('smThemeButton').title=$('smThemeButton').ariaLabel=L('切换明暗模式','Switch appearance');
        $('smDirectoryToggle').title=$('smDirectoryToggle').ariaLabel=L('打开或收起目录','Toggle outline');
        $('smDirectoryClose').title=$('smDirectoryClose').ariaLabel=L('关闭目录','Close outline');
        $('smEditButton').querySelector('span').textContent=L('编辑正文','Edit text');
        $('smCopyButton').querySelector('span').textContent=L('复制正文','Copy text');
        const feedbackKind=$('smCopyFeedback')?.dataset.feedbackKind;
        if(feedbackKind)showCopyFeedback(feedbackKind);
        $('smCancelEditButton').textContent=L('完成','Done');
        $('smRetrySaveButton').querySelector('span').textContent=L('重试保存','Retry save');
        $('smCopyDraftButton').textContent=L('复制草稿','Copy draft');$('smReloadConflictButton').textContent=L('放弃草稿并重新读取','Discard draft and reload');
        $('smEditorTitle').textContent=L('编辑 Markdown 正文','Edit Markdown text');
        $('smEditorHint').textContent=L('修改会在短暂停顿后自动保存。','Changes save automatically after a short pause.');
        $('smMarkdownLabel').textContent=L('Markdown 正文','Markdown text');
        $('smRefreshButton').setAttribute('aria-label',$('smRefreshButton').title);
        document.querySelectorAll('[data-sm-tab]').forEach(button=>{button.querySelector('span').textContent=button.dataset.smTab==='text'?L('正文','Text'):L('设定库','Settings');});
        $('smNovelTabs').setAttribute('aria-label',L('小说工作区','Novel workspace'));
        document.querySelectorAll('[data-document-pane]').forEach(button=>{button.querySelector('span').textContent=button.dataset.documentPane==='body'?L('正文','Text'):L('章纲','Outline');});
        $('smDocumentTabs').setAttribute('aria-label',L('正文与章纲','Text and outline'));
        updateDocumentPaneTabs();
        $('smDirectorySearch').placeholder=L('搜索目录标题','Search titles');
        updateCharacterCount();
        if(state.summary)renderDirectory();
        if(state.outlineDialog)renderOutlineDialog();
        if(state.setting&&!state.editor)renderSetting(state.setting);
        else if(state.handoff&&!state.editor)renderHandoff(state.handoff);
        else if(state.summary&&state.tab==='text')updateHeading();
    }
    function toggleLanguage(){window.StudioI18n?.toggle?.();}
    function toggleTheme(){const current=window.StudioTheme?.get?.()||'light';window.StudioTheme?.set?.(current==='dark'?'light':'dark');}
    function bind(){
        $('smDirectory').addEventListener('click',event=>{void selectDirectory(event);});
        $('smDirectory').addEventListener('keydown',handleOutlineMenuKeydown);
        $('smDirectorySearch').addEventListener('input',event=>{state.search=event.target.value||'';renderDirectory();});
        $('smOutlineRootAdd').addEventListener('click',()=>{void beginOutlineDialog('root-create','root','',{kind:'root'});});
        $('smOutlineDialogForm').addEventListener('submit',event=>{void submitOutlineDialog(event);});
        $('smOutlineDialogInput').addEventListener('input',event=>{if(state.outlineDialog)state.outlineDialog.value=event.target.value;});
        $('smOutlineDialog').addEventListener('click',event=>{
            if(event.target===$('smOutlineDialog')){closeOutlineDialog();return;}
            if(event.target.closest('[data-outline-dialog-close]'))closeOutlineDialog();
        });
        document.addEventListener('click',event=>{
            if(state.outlineMenu&&!event.target.closest('.sm-outline-menu,.sm-outline-menu-toggle'))closeOutlineMenu(false);
        });
        $('smDirectoryToggle').addEventListener('click',toggleDrawer);
        $('smDirectoryClose').addEventListener('click',closeDrawer);$('smDrawerScrim').addEventListener('click',closeDrawer);
        $('smLoadMoreButton').addEventListener('click',async()=>{if($('smLoadMoreButton').disabled)return;$('smLoadMoreButton').disabled=true;$('smLoadMoreButton').textContent=L('正在读取…','Loading…');await loadView(true);});
        $('smEditButton').addEventListener('click',startEdit);$('smCopyButton').addEventListener('click',copyCurrent);
        $('smCancelEditButton').addEventListener('click',()=>{void closeEditor();});
        $('smRetrySaveButton').addEventListener('click',()=>{state.conflicted=false;void saveEditor();});
        $('smCopyDraftButton').addEventListener('click',copyDraft);$('smReloadConflictButton').addEventListener('click',reloadAfterConflict);
        $('smReader').addEventListener('input',handleInlineInput);
        $('smReader').addEventListener('compositionstart',event=>{const key=event.target.closest('.sm-inline-input')?.dataset.inlineKey;if(key){state.inlineComposing.add(key);clearTimeout(state.inlineTimer);}});
        $('smReader').addEventListener('compositionend',event=>{const key=event.target.closest('.sm-inline-input')?.dataset.inlineKey;if(key){state.inlineComposing.delete(key);handleInlineInput({target:event.target,isComposing:false});}});
        $('smReader').addEventListener('click',event=>{
            const optimize=event.target.closest('[data-inline-optimize]');if(optimize){void openTextOptimization(optimize.dataset.inlineOptimize);return;}
            const retry=event.target.closest('[data-inline-retry]');if(retry){void saveInlineBatch({explicit:true});return;}
            const confirm=event.target.closest('[data-inline-confirm]');if(confirm){void confirmInlineConflict(confirm.dataset.inlineConfirm);return;}
            const reload=event.target.closest('[data-inline-reload]');if(reload){reloadInlineLatest(reload.dataset.inlineReload);return;}
            const copy=event.target.closest('[data-inline-copy]');if(copy){void copyInlineDraft(copy.dataset.inlineCopy);}
        });
        $('smMarkdownInput').addEventListener('input',event=>scheduleSave(event));
        $('smMarkdownInput').addEventListener('compositionstart',()=>{state.composing=true;clearTimeout(state.saveTimer);});
        $('smMarkdownInput').addEventListener('compositionend',()=>{state.composing=false;scheduleSave();});
        $('smRefreshButton').addEventListener('click',refreshPage);
        $('smLanguageButton').addEventListener('click',toggleLanguage);$('smThemeButton').addEventListener('click',toggleTheme);
        $('smNovelTabs').addEventListener('click',event=>{const tab=event.target.closest('[data-sm-tab]');if(tab)void selectTab(tab.dataset.smTab);});
        $('smNovelTabs').addEventListener('keydown',async event=>{
            if(!['ArrowLeft','ArrowRight'].includes(event.key))return;
            const tabs=[...$('smNovelTabs').querySelectorAll('[data-sm-tab]')],current=tabs.indexOf(event.target.closest('[data-sm-tab]'));
            if(current<0)return;
            event.preventDefault();
            const delta=event.key==='ArrowRight'?1:-1,next=tabs[(current+delta+tabs.length)%tabs.length];
            await selectTab(next.dataset.smTab);
            if(state.tab===next.dataset.smTab)next.focus();
        });
        $('smDocumentTabs').addEventListener('click',event=>{const tab=event.target.closest('[data-document-pane]');if(tab)void selectDocumentPane(tab.dataset.documentPane);});
        $('smDocumentTabs').addEventListener('keydown',async event=>{
            if(!['ArrowLeft','ArrowRight'].includes(event.key))return;
            const tabs=[...$('smDocumentTabs').querySelectorAll('[data-document-pane]')],current=tabs.indexOf(event.target.closest('[data-document-pane]'));
            if(current<0)return;event.preventDefault();
            const next=tabs[(current+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length];
            await selectDocumentPane(next.dataset.documentPane);
            if(state.documentPane===next.dataset.documentPane)next.focus();
        });
        $('smVersionSelect').addEventListener('change',()=>{void chooseVersion().catch(error=>setStatus(error.message,'error'));});
        $('smRevisionHistoryButton').addEventListener('click',()=>{void toggleHistory().catch(error=>setStatus(error.message,'error'));});
        document.addEventListener('keydown',event=>{
            if(state.outlineDialog){handleOutlineDialogKeydown(event);return;}
            if(event.key==='Escape'&&state.outlineMenu){event.preventDefault();closeOutlineMenu(true);return;}
            if(event.key==='Escape'&&$('smWorkspace').classList.contains('sm-drawer-open')){event.preventDefault();closeDrawer();}
        });
        window.addEventListener('beforeunload',event=>{if(state.dirty||state.saving||inlineHasDirty()||state.inlineSaving||state.inlinePending){event.preventDefault();event.returnValue='';}});
        window.addEventListener('studio-lang-change',applyLanguage);
        window.addEventListener('message',event=>{if(event.origin!==location.origin||event.source!==window.parent)return;if(event.data?.type==='studio-lang'&&event.data.lang)window.StudioI18n?.set?.(event.data.lang);if(event.data?.type==='studio-theme')window.StudioTheme?.applyPreference?.(event.data.preference);});
        window.addEventListener('resize',()=>{if(!queryState())$('smWorkspace').classList.remove('sm-drawer-open');});
        document.addEventListener('visibilitychange',()=>{if(!document.hidden)void syncRemote();});
    }
    async function init(){
        bind();applyLanguage();
        if(queryState()){$('smWorkspace').classList.remove('sm-drawer-open');$('smDirectoryToggle').setAttribute('aria-expanded','false');}
        if(!projectId){$('smProjectName').textContent=L('缺少项目 ID','Project ID required');setStatus(L('项目链接缺少 id 参数。请从对应模块的项目列表打开作品。','The project link has no id parameter. Open this work from its module list.'),'error');return;}
        try{await loadSummary(false);}catch(error){$('smProjectName').textContent=L('暂时无法读取作品','Could not load work');setStatus(L('读取作品失败：','Could not open work: ')+(error.message||''),'error');}
        state.syncTimer=window.setInterval(()=>{void syncRemote();},5000);
        icons();
    }
    init();
})();
