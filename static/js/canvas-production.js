/* 创作进度：节点上的稳定关联是数据源，表格只派生导航与当前状态。 */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;if(root)root.CanvasProduction=api;})(typeof globalThis==='undefined'?this:globalThis,function(){
    'use strict';
    const columns={imageNodeIds:'image',audioNodeIds:'audio',videoNodeIds:'video'};
    const allowed=new Set(['role','order','sourceNodeId','sourceStart','sourceEnd',...Object.keys(columns)]);
    const textOf=n=>(n?.images||[]).filter(m=>m.kind==='text'||typeof m.text==='string'||typeof m.content==='string').map(m=>m.text??m.content??'').join('\n');
    function kind(n){
        const type=n?.type||'';
        if(type==='smart-material'){
            const media=n.images?.[0];return media?.kind==='music'?'audio':media?.kind||n.outputKind||'';
        }
        if(/audio|music/.test(type))return 'audio';
        if(/video/.test(type))return 'video';
        if(/image|ai-app|comfy/.test(type))return n.outputKind||'image';
        return /text/.test(type)?'text':'';
    }
    function update(node,patch,nodes,connections){
        if(!patch||typeof patch!=='object'||Array.isArray(patch))throw Error('production 必须是关联对象 / Expected production object');
        if(Object.keys(patch).some(key=>!allowed.has(key)))throw Error('不支持的生产关联字段 / Unsupported production field');
        const value={...(node.production||{}),...patch};
        if(!['script','segment','asset','video','none'].includes(value.role))throw Error('请选择剧本、分段、资产或视频角色 / Invalid production role');
        if(['script','segment'].includes(value.role)&&kind(node)!=='text')throw Error('剧本和分段须使用文本节点 / Scripts and segments require text nodes');
        if(value.role==='segment'&&(!Number.isSafeInteger(value.order)||value.order<1))throw Error('分段序号须为正整数 / Segment number must be a positive integer');
        if(value.role==='segment'&&nodes.some(n=>n.id!==node.id&&n.production?.role==='segment'&&n.production.order===value.order))throw Error('分段序号重复 / Duplicate segment number');
        for(const [field,wanted] of Object.entries(columns)){
            if(value[field]===undefined)continue;
            if(!Array.isArray(value[field]))throw Error(`${field} 须为节点 ID 数组 / Expected node ID array`);
            value[field]=[...new Set(value[field])];
            for(const id of value[field]){
                const target=nodes.find(n=>n.id===id);
                if(!target||kind(target)!==wanted)throw Error(`关联节点不存在或类型不符：${id} / Missing or incompatible node`);
            }
        }
        if(value.sourceNodeId){
            const source=nodes.find(n=>n.id===value.sourceNodeId);
            if(!source||source.id===node.id||kind(source)!=='text')throw Error('来源剧本不存在 / Source script not found');
            const full=textOf(source),excerpt=textOf(node);
            if(!excerpt||!full)throw Error('请先读取完整剧本与分段正文 / Load the complete source and segment text first');
            if(value.sourceStart===undefined&&value.sourceEnd===undefined){
                const start=full.indexOf(excerpt);
                if(start<0||full.indexOf(excerpt,start+1)>=0)throw Error('请提供能唯一定位原文的起止范围 / Supply an unambiguous source range');
                value.sourceStart=Array.from(full.slice(0,start)).length;value.sourceEnd=value.sourceStart+Array.from(excerpt).length;
            }
            const chars=Array.from(full);
            if(!Number.isSafeInteger(value.sourceStart)||!Number.isSafeInteger(value.sourceEnd)||value.sourceStart<0||value.sourceEnd<=value.sourceStart||value.sourceEnd>chars.length||chars.slice(value.sourceStart,value.sourceEnd).join('')!==excerpt)throw Error('分段必须与选取的剧本原文一致，不得改写 / Segment must match the source text exactly');
        }
        if(connections)for(const field of Object.keys(columns))if(Array.isArray(patch[field])){
            for(let i=connections.length-1;i>=0;i--){const c=connections[i];if(c.kind==='story'&&c.from===node.id&&kind(nodes.find(n=>n.id===c.to))===columns[field])connections.splice(i,1);}
            for(const id of value[field])connections.push({from:node.id,to:id,kind:'story'});
            delete value[field];
        }
        node.production=JSON.parse(JSON.stringify(value));
        node.creationRevision=Number(node.creationRevision||0)+1;
        return node;
    }
    // 旧登记数组单向迁移为 story 连线，连线是关联的唯一运行时来源。
    function migrateRelations(nodes,connections){
        let changed=false;
        for(const node of nodes)for(const field of Object.keys(columns)){
            if(!Array.isArray(node.production?.[field]))continue;
            for(const id of node.production[field])if(nodes.some(n=>n.id===id)&&id!==node.id&&!connections.some(c=>c.from===node.id&&c.to===id&&c.kind==='story')){
                connections.push({from:node.id,to:id,kind:'story'});changed=true;
            }
            delete node.production[field];changed=true;
        }
        return changed;
    }
    function summary(node,nodes,taskIndex){
        const media=node.images?.[0]||null;
        const related=taskIndex?taskIndex(node):nodes.flatMap(n=>(n.creationTasks||[]).filter(t=>n.id===node.id||node.creationId&&t.creationId===node.creationId));
        const active=related.find(t=>!['succeeded','partially_succeeded','failed','cancelled'].includes(t.runStatus));
        const last=related.slice().sort((a,b)=>Number(b.runStartedAt||0)-Number(a.runStartedAt||0))[0];
        const status=active||node.pending||node.running?'running':last?.runStatus==='failed'?'failed':media&&(media.url||textOf(node))?'ready':'not_generated';
        return {id:node.id,title:node.title||media?.name||node.id,kind:kind(node),status,media,error:last?.runStatus==='failed'?last.runError||'':'',creationId:node.creationId||''};
    }
    function rows(nodes,connections){
        const byId=new Map(nodes.map(n=>[n.id,n])),byCreation=new Map(),summaries=new Map(),sourceChars=new Map();
        for(const n of nodes)for(const task of n.creationTasks||[]){
            if(task.creationId){if(!byCreation.has(task.creationId))byCreation.set(task.creationId,[]);byCreation.get(task.creationId).push(task);}
        }
        const describe=n=>{if(!summaries.has(n.id))summaries.set(n.id,summary(n,nodes,node=>[...new Set([...(node.creationTasks||[]),...(byCreation.get(node.creationId)||[])]) ]));return summaries.get(n.id);};
        return nodes.filter(n=>n.production?.role==='segment').sort((a,b)=>a.production.order-b.production.order).map(node=>{
            const spec=node.production,source=byId.get(spec.sourceNodeId);
            if(source&&!sourceChars.has(source.id))sourceChars.set(source.id,Array.from(textOf(source)));
            const slice=source?(sourceChars.get(source.id)||[]).slice(spec.sourceStart,spec.sourceEnd).join(''):'';
            const cells=field=>(connections ? [...new Set(connections.filter(c=>c.kind==='story'&&c.from===node.id).map(c=>c.to))] : spec[field]||[]).map(id=>byId.get(id)).filter(n=>n&&kind(n)===columns[field]).map(describe);
            return {number:spec.order,script:describe(node),sourceStatus:!spec.sourceNodeId?'unlinked':!source?'missing':slice===textOf(node)?'current':'changed',images:cells('imageNodeIds'),audio:cells('audioNodeIds'),videos:cells('videoNodeIds')};
        });
    }
    function registerSegments(nodes,nodeIds,connections){
        const eligible=[...new Set(nodeIds)].map(id=>nodes.find(node=>node.id===id)).filter(node=>node&&kind(node)==='text'&&!['script','segment'].includes(node.production?.role));
        let order=Math.max(0,...rows(nodes,connections).map(row=>row.number));
        eligible.forEach(node=>update(node,{role:'segment',order:++order},nodes));
        return eligible;
    }
    function mount({container,button,getNodes,getConnections,focus,text,bindPosters}){
        const el=document.createElement('div');el.className='canvas-production-panel';el.setAttribute('role','dialog');el.setAttribute('aria-modal','true');el.setAttribute('aria-hidden','true');
        el.innerHTML='<section class="production-dialog"><div class="production-head"><strong data-heading></strong><span data-count></span></div><div class="production-table-scroll"><table><thead></thead><tbody></tbody></table><p data-empty></p></div></section>';
        container.appendChild(el);const body=el.querySelector('tbody');
        let signature='';
        const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
        const labels=()=>({ready:text('已生成','Ready'),running:text('生成中','Running'),failed:text('失败','Failed'),not_generated:text('未生成','Not generated')});
        function open(value){el.classList.toggle('open',value);el.setAttribute('aria-hidden',String(!value));button.classList.toggle('active',value);button.setAttribute('aria-expanded',String(value));if(value)refresh();}
        function icon(kind){return kind==='audio'?'<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M5 13v6M10 7v18M16 3v26M22 8v16M27 13v6"/></svg>':kind==='video'?'▷':kind==='text'?'≡':'◇';}
        function chip(item){
            const caption=`${item.title} · ${labels()[item.status]}`;
            const url=item.media?.url||'';
            // 拒绝脚本 URL；外部媒体仍遵守页面现有 CSP 与来源政策。
            const safe=/^(?:https?:\/\/|\/|blob:|data:image\/)/i.test(url)?url:'';
            const content=safe&&item.kind==='image'?`<img src="${escape(safe)}" alt="" loading="lazy">`:safe&&item.kind==='video'?`<img data-video-poster="${escape(safe)}" alt="" loading="lazy">${icon('video')}`:icon(item.kind);
            return `<button type="button" class="production-chip is-${item.status}" data-node-id="${escape(item.id)}" title="${escape(caption+(item.error?'\n'+item.error:''))}" aria-label="${escape(caption)}"><span class="production-thumb">${content}<span class="production-status" aria-hidden="true">${item.status==='running'?'…':item.status==='failed'?'!':item.status==='ready'?'✓':''}</span></span><span class="production-chip-name">${escape(item.title)}</span></button>`;
        }
        function refresh(){
            const data=rows(getNodes(),getConnections?.());
            const label=text('创作进度','Production');button.querySelector('span').textContent=label;button.title=label;
            el.querySelector('[data-heading]').textContent=label;el.querySelector('[data-count]').textContent=text(`${data.length} 段`,`${data.length} segments`);
            el.querySelector('[data-empty]').textContent=text('登记文本节点后，创作分段会显示在这里。','Registered text segments appear here.');
            el.querySelector('[data-empty]').hidden=!!data.length;
            const next=JSON.stringify([data,label]);if(next===signature)return;signature=next;
            el.querySelector('thead').innerHTML='<tr>'+[text('序号','No.'),text('分段剧本','Segment script'),text('图片资产','Image assets'),text('音频 / 音色','Audio / voice'),text('视频','Video')].map(v=>`<th scope="col">${escape(v)}</th>`).join('')+'</tr>';
            body.innerHTML=data.map(row=>`<tr><td>${row.number}</td><td><button type="button" class="production-script" data-node-id="${escape(row.script.id)}">${escape(row.script.title)}</button>${['changed','missing'].includes(row.sourceStatus)?`<small class="production-source-warning">${escape(text('源剧本有变化，请复核分段','Source changed; review segment'))}</small>`:''}</td>${[row.images,row.audio,row.videos].map(items=>`<td><div class="production-chips">${items.length?items.map(chip).join(''):'<span class="production-none">—</span>'}</div></td>`).join('')}</tr>`).join('');
            bindPosters?.(body);
        }
        button.addEventListener('click',()=>{const next=!el.classList.contains('open');if(next) window.closeSmartTopPanels?.('production');open(next);});
        body.addEventListener('click',event=>{const target=event.target.closest('[data-node-id]');if(target)focus(target.dataset.nodeId,0);});
        ['pointerdown','mousedown','dblclick','wheel'].forEach(type=>el.addEventListener(type,event=>event.stopPropagation()));
        return {refresh,open,element:el};
    }
    return {textOf,kind,update,rows,summary,migrateRelations,registerSegments,mount};
});
