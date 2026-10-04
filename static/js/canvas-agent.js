/* 画布只保留新节点默认参数编辑；项目接入说明由项目管理页提供。 */
(() => {
    'use strict';
    const text = (zh, en) => capabilityUiText(zh, en);
    const nodeKinds = {material:'smart-material', text:'smart-text-generator', image:'smart-image-generator', video:'smart-video-generator', audio:'smart-audio-generator', music:'smart-music-generator', app:'smart-ai-app', comfy:'smart-comfy-workflow'};
    const fields = {text:['textProvider','textModel','textFamilyId','text_generation'], image:['provider_id','model','imageFamilyId','image_generation'], video:['videoProvider','videoModel','videoFamilyId','video_generation'], audio:['audioProvider','audioModel','audioFamilyId','audio_generation'], music:['musicProvider','musicModel','musicFamilyId','music_generation']};
    const endpoint = () => `/api/agent/canvases/${encodeURIComponent(canvasId)}`;
    async function api(path, payload){
        const response = await fetch(path, {method:payload ? 'POST' : 'GET', headers:{'Content-Type':'application/json'}, ...(payload ? {body:JSON.stringify(payload)} : {})});
        const data = await response.json();
        if(!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
        return data;
    }
    async function persist(){
        clearTimeout(saveTimer);
        await saveCanvas();
    }
    const button = document.getElementById('canvasAgentToggle');
    window.addEventListener('canvas-ready', () => { button.disabled = false; });
    const dialog = document.getElementById('canvasAgentDialog');
    const defaultsRoot = document.getElementById('canvasAgentDefaults');
    const feedback = document.getElementById('canvasAgentFeedback');
    let defaultDraft = {}, defaultKind = 'image', defaultModelControl = null;
    const kindLabels = () => ({text:text('文本 / LLM','Text / LLM'), image:text('图片','Image'), video:text('视频','Video'), audio:text('音频','Audio'), music:text('音乐','Music'), app:text('AI 应用','AI app'), comfy:'ComfyUI'});
    const profilesFor = kind => (modelCapabilityCatalog?.providers || []).flatMap(provider => (provider.models || []).filter(profile => profile.node_type === fields[kind]?.[3] && profile.runnable).map(profile => ({...profile, provider_id:provider.id || provider.provider_id})));
    function defaultOptionsFor(kind) {
        const nodeType = fields[kind]?.[3];
        const projected = Array.isArray(modelCapabilityCatalog?.options) ? modelCapabilityCatalog.options
            .filter(option => option.node_type === nodeType && option.runnable !== false && option.selectable !== false) : [];
        if (projected.length) return projected;
        return profilesFor(kind).map(profile => ({
            schema_version: 2, option_id: `legacy-${profile.provider_id}-${profile.model_id}`,
            canonical_family_id: profile.family_id || profile.model_id,
            canonical_family_label: {zh: profile.family_name || profile.display_name || profile.model_id, en: profile.family_name_en || profile.family_name || profile.display_name || profile.model_id},
            display_label: {zh: profile.variant_name || profile.display_name || profile.model_id, en: profile.variant_name_en || profile.variant_name || profile.display_name || profile.model_id},
            operation: profile.operation || '', node_type: nodeType, connection_id: profile.provider_id,
            capability_provider_id: profile.provider_id, platform_label: apiProviders.find(provider => provider.id === profile.provider_id)?.name || profile.provider_id,
            region_id: profile.region || '', catalog_model_id: profile.model_id, profile_revision: profile.version || '',
            readiness: profile.readiness || 'ready', runnable: profile.runnable !== false, selectable: true,
            capability_tags: profile.capability_tags || [], capability_tags_en: profile.capability_tags_en || [], parameters: profile.parameters || {}, inputs: profile.inputs || {}
        }));
    }
    function defaultOptionFor(current, options) {
        const optionId = current?.option_id || current?.optionId;
        if (optionId) { const exact = options.find(option => option.option_id === optionId); if (exact) return exact; }
        const candidates = options.filter(option => option.connection_id === current?.provider_id && option.catalog_model_id === current?.model
            && (!current?.region || option.region_id === current.region));
        return candidates.length === 1 ? candidates[0] : null;
    }
    function destroyDefaultModelControl() { if (defaultModelControl?.destroy) defaultModelControl.destroy(); defaultModelControl = null; }
    function defaultProfile(){
        const current = defaultDraft[defaultKind] || {};
        if(fields[defaultKind]) return profilesFor(defaultKind).find(p => p.provider_id === current.provider_id && p.model_id === current.model);
        const source=current.run_settings || {};
        const app=runningHubEntries('app').find(entry=>runningHubEntryId(entry,'app')===source.rhAppId);
        const definitions=defaultKind==='app' ? rhEntryFields(app) : (comfyWorkflowCache[source.comfyWorkflow]?.config?.fields || []);
        const parameters={};
        definitions.forEach(field=>{
            const kind=defaultKind==='app' ? rhFieldRole(field) : comfyFieldKind(field);
            if(['image','video','audio','prompt','text'].includes(kind)) return;
            const key=defaultKind==='app' ? rhParamKey(field.nodeId,field.fieldName) : field.id;
            parameters[key]=externalParameterSpec(field,defaultKind==='app'?'rh':'comfy');
        });
        return {model_id:source.rhAppId || source.comfyWorkflow || '',parameters};
    }
    function renderDefaultEditor(openKey=''){
        destroyDefaultModelControl();
        const current = defaultDraft[defaultKind] || {};
        if(fields[defaultKind]) {
            const options = defaultOptionsFor(defaultKind);
            const selected = defaultOptionFor(current, options);
            defaultsRoot.innerHTML = `<div class="agent-default-heading"><h3>${text('新建节点默认值','New node defaults')}</h3><span>${text('仅当前画布','This canvas')}</span></div><p>${text('先设好每类节点。Agent 创建此类节点时会沿用这里选定的模型和参数；未设置的类型会提示先配置。','Set each node type once. Agents use this model and its parameters when creating nodes; unconfigured types require setup first.')}</p><div class="agent-default-tabs" role="tablist">${Object.entries(kindLabels()).map(([kind,label]) => `<button type="button" role="tab" aria-selected="${kind === defaultKind}" data-agent-kind="${kind}">${label}${defaultDraft[kind] ? ' ·' : ''}</button>`).join('')}</div><div class="agent-default-model-host" data-agent-model-host></div><div class="agent-default-actions"><button type="button" data-agent-save>${text('保存默认设置','Save defaults')}</button></div>`;
            const host = defaultsRoot.querySelector('[data-agent-model-host]');
            if(host && options.length && window.mountModelConfigControl) {
                defaultModelControl = window.mountModelConfigControl(host, {
                    context:{host:'canvas-agent-defaults',moduleId:'canvas',slotId:fields[defaultKind][3],phase:'template'},
                    catalog:{options,profiles:[]}, selection:{optionId:selected?.option_id || '',parameters:current.parameters || {}}, presentation:'module',
                    onCommit: payload => {
                        const picked = options.find(option => option.option_id === payload.selection.optionId);
                        if(!picked) return Promise.reject(new Error(text('选择不属于当前节点类型','Selection is not valid for this node type')));
                        defaultDraft[defaultKind] = {provider_id:picked.connection_id || '',model:picked.catalog_model_id || '',region:picked.region_id || '',option_id:picked.option_id || '',parameters:{...(payload.selection.parameters || {})}};
                        feedback.textContent = text('设置已修改，请保存。','Changes pending. Save defaults to apply.');
                        return Promise.resolve();
                    },
                    onParametersChange: payload => {
                        if(!defaultDraft[defaultKind]) defaultDraft[defaultKind]={provider_id:selected?.connection_id || '',model:selected?.catalog_model_id || '',region:selected?.region_id || '',option_id:selected?.option_id || '',parameters:{}};
                        defaultDraft[defaultKind].parameters = {...(payload.parameters || {})};
                        feedback.textContent = text('设置已修改，请保存。','Changes pending. Save defaults to apply.');
                    }
                });
            } else if(host) host.innerHTML = `<p>${escapeHtml(text('暂无可用模型，请先在 API 设置中启用模型。','No usable models. Enable a model in API settings first.'))}</p>`;
            refreshIcons();
            return;
        }
        const profiles = profilesFor(defaultKind);
        const profile = defaultProfile();
        const providerIds = [...new Set(profiles.map(p => p.provider_id))];
        const providerProfiles = profiles.filter(p => p.provider_id === current.provider_id);
        const families = [...new Map(providerProfiles.map(p => [p.family_id || p.model_id,p])).values()];
        const variants = providerProfiles.filter(p => (p.family_id || p.model_id) === (profile?.family_id || profile?.model_id));
        const option = (value,label,chosen) => `<option value="${escapeAttr(value)}" ${value === chosen ? 'selected' : ''}>${escapeHtml(label)}</option>`;
        const empty = option('',text('请选择','Select'),'');
        const select = (id,label,options) => `<label><span>${escapeHtml(label)}</span><select data-agent-select="${id}" aria-label="${escapeAttr(label)}">${empty}${options}</select></label>`;
        let editor;
        if(fields[defaultKind]){
            editor = `<div class="agent-default-selectors">${select('provider',text('平台','Provider'),providerIds.map(id => option(id,apiProviders.find(p => p.id === id)?.name || id,current.provider_id)).join(''))}${select('family',text('模型','Model'),families.map(p => option(p.family_id || p.model_id,text(p.family_name || p.display_name || p.model_id,p.family_name_en || p.family_name || p.display_name || p.model_id),profile?.family_id || profile?.model_id)).join(''))}${select('model',text('运行模式','Mode'),variants.map(p => option(p.model_id,capabilityVariantLabel(p),current.model)).join(''))}</div>`;
            if(profile){
                const values = capabilityParameterValues(profile,{capabilityParameters:{[profile.model_id]:current.parameters || {}}});
                editor += `<div class="agent-default-params">${Object.entries(profile.parameters || {}).filter(([,spec]) => spec.ui_hidden !== true).map(([key,spec]) => {
                    const entry = renderCapabilityParameterEditor(key,spec,profile,values);
                    const label = entry.unset ? entry.label : `${entry.label} · ${capabilityParameterPreview(key,spec,entry.value,false)}`;
                    return `<details class="agent-default-param" data-agent-param="${escapeAttr(key)}" ${key === openKey ? 'open' : ''}><summary>${escapeHtml(label)}</summary><div class="agent-param-body"><strong>${escapeHtml(entry.label)}</strong><p>${escapeHtml(entry.description)}</p>${entry.body}</div></details>`;
                }).join('')}</div>`;
            } else editor += `<p>${escapeHtml(current.model ? text('已保存的模型当前不可用，请重新选择。','The saved model is unavailable. Select a model.') : text('选择后，Agent 创建此类节点就会使用这里的模型和参数。','Once configured, agents use this model and its parameters for new nodes.'))}</p>`;
        } else {
            const source = current.run_settings || {};
            const entries=defaultKind==='app' ? runningHubEntries('app').map(entry=>({id:runningHubEntryId(entry,'app'),name:runningHubEntryLabel(entry,'app')})) : comfyWorkflows.map(entry=>({id:entry.name,name:entry.title || entry.name}));
            editor=`<div class="agent-default-selectors">${select('custom',defaultKind==='app'?text('AI 应用','AI app'):text('工作流','Workflow'),entries.map(entry=>option(entry.id,entry.name,source.rhAppId || source.comfyWorkflow)).join(''))}</div>`;
            if(!entries.length) editor+=`<p>${text('请先在 API 设置中添加应用或工作流。','Add an app or workflow in API settings first.')}</p>`;
            if(profile?.model_id){
                const values=capabilityParameterValues(profile,{capabilityParameters:{[profile.model_id]:source.rhParams || source.comfyParams || {}}});
                editor+=`<div class="agent-default-params">${Object.entries(profile.parameters).map(([key,spec])=>{
                    const entry=renderCapabilityParameterEditor(key,spec,profile,values);
                    return `<details class="agent-default-param" data-agent-param="${escapeAttr(key)}" ${key===openKey?'open':''}><summary>${escapeHtml(entry.label)} · ${escapeHtml(capabilityParameterPreview(key,spec,entry.value,entry.unset))}</summary><div class="agent-param-body"><strong>${escapeHtml(entry.label)}</strong>${entry.body}</div></details>`;
                }).join('')}</div>`;
            }

        }
        defaultsRoot.innerHTML = `<div class="agent-default-heading"><h3>${text('新建节点默认值','New node defaults')}</h3><span>${text('仅当前画布','This canvas')}</span></div><p>${text('先设好每类节点。Agent 会沿用这些设置；你明确指定时，只修改指定项。未设置的类型会提示先配置。','Set each node type once. Agents keep these defaults and override only explicitly requested fields. Unconfigured types require setup first.')}</p><div class="agent-default-tabs" role="tablist">${Object.entries(kindLabels()).map(([kind,label]) => `<button type="button" role="tab" aria-selected="${kind === defaultKind}" data-agent-kind="${kind}">${label}${defaultDraft[kind] ? ' ·' : ''}</button>`).join('')}</div>${editor}<div class="agent-default-actions"><button type="button" data-agent-save>${text('保存默认设置','Save defaults')}</button></div>`;
        defaultsRoot.querySelectorAll('.capability-option').forEach(option => option.setAttribute('aria-label',option.title || option.textContent.trim()));
        defaultsRoot.querySelectorAll('details').forEach(item => item.addEventListener('toggle',() => {
            if(!item.open) return;
            const body=item.querySelector('.agent-param-body');
            body.style.left='0px';
            const bounds=dialog.getBoundingClientRect();
            body.style.maxHeight=`${Math.max(80,Math.min(320,item.getBoundingClientRect().top-bounds.top-16))}px`;
            const rect=body.getBoundingClientRect();
            if(rect.right > bounds.right-20) body.style.left=`${bounds.right-20-rect.right}px`;
        }));
        refreshIcons();
    }
    function setDefaultValue(key,value){
        const current = defaultDraft[defaultKind];
        if(!current) return;
        if(fields[defaultKind]) current.parameters = {...current.parameters,[key]:value};
        else {
            const field=defaultKind==='app'?'rhParams':'comfyParams';
            current.run_settings[field]={...current.run_settings[field],[key]:value};
        }
        feedback.textContent = text('设置已修改，请保存。','Changes pending. Save defaults to apply.');
    }
    defaultsRoot.addEventListener('change', async e => {
        const select = e.target.closest('[data-agent-select]');
        if(!select) return;
        const current = defaultDraft[defaultKind] || {};
        let profile;
        const profiles = profilesFor(defaultKind);
        if(select.dataset.agentSelect === 'custom'){
            if(!select.value) delete defaultDraft[defaultKind];
            else if(defaultKind==='app') defaultDraft.app={run_settings:{rhAppId:select.value,rhConfigKey:runningHubEntryKey('app',select.value),rhParams:{}}};
            else {await ensureComfyWorkflow(select.value);defaultDraft.comfy={run_settings:{comfyWorkflow:select.value,comfyParams:{}}};}
            renderDefaultEditor();return;
        }
        if(select.dataset.agentSelect === 'provider'){
            profile = profiles.find(p=>p.provider_id===select.value);
            if(profile) defaultDraft[defaultKind] = {provider_id:select.value,model:profile.model_id,parameters:{}};
            else delete defaultDraft[defaultKind];
        } else {
            profile = profiles.find(p => p.provider_id === current.provider_id && (select.dataset.agentSelect === 'family' ? (p.family_id || p.model_id) === select.value : p.model_id === select.value));
            defaultDraft[defaultKind] = {provider_id:current.provider_id,model:profile?.model_id || '',parameters:{}};
        }
        renderDefaultEditor();
        feedback.textContent = text('设置已修改，请保存。','Changes pending. Save defaults to apply.');
    });
    defaultsRoot.addEventListener('input', e => {
        const control = e.target.closest('input[data-capability-param],textarea[data-capability-param]');
        if(!control) return;
        const spec = defaultProfile()?.parameters?.[control.dataset.capabilityParam];
        let value = capabilityInputValue(control);
        if(value === undefined) return;
        syncCapabilityNumericControls(control,value);
        if(value === '' && capabilityParameterIsOptional(spec)) value = CAPABILITY_PARAMETER_UNSET;
        setDefaultValue(control.dataset.capabilityParam,value);
        const summary=control.closest('details')?.querySelector('summary');
        if(summary) summary.textContent=capabilityParameterLabel(control.dataset.capabilityParam,spec,defaultProfile())+' · '+capabilityParameterPreview(control.dataset.capabilityParam,spec,value,false);
        const output = control.closest('.capability-range-field')?.querySelector('output');
        if(output) output.textContent = String(value);
    });
    defaultsRoot.addEventListener('click', async e => {
        const button = e.target.closest('button');
        const summary = e.target.closest('summary');
        if(summary){
            defaultsRoot.querySelectorAll('details[open]').forEach(item => {if(item !== summary.parentElement) item.open = false;});
            return;
        }
        if(!button) return;
        e.preventDefault(); e.stopPropagation();
        if(!button.closest('.agent-default-param')) defaultsRoot.querySelectorAll('details[open]').forEach(item=>item.open=false);
        if(button.dataset.agentKind){ defaultKind = button.dataset.agentKind; if(defaultKind==='comfy' && defaultDraft.comfy?.run_settings?.comfyWorkflow) await ensureComfyWorkflow(defaultDraft.comfy.run_settings.comfyWorkflow); renderDefaultEditor(); return; }
        if(button.hasAttribute('data-agent-save')){
            for(const [kind,value] of Object.entries(defaultDraft)){
                if(fields[kind] && !profilesFor(kind).some(p => p.provider_id === value.provider_id && p.model_id === value.model)){
                    feedback.textContent=text(`请先选好“${kindLabels()[kind]}”的模型。`,`Choose a model for ${kindLabels()[kind]}.`);return;
                }
            }
            button.disabled = true;
            try {
                canvasDefaultSmartSettings.agentDefaults = JSON.parse(JSON.stringify(defaultDraft));
                await persist();
                const saved = await api(`${endpoint()}/defaults`);
                if(JSON.stringify(saved.defaults) !== JSON.stringify(defaultDraft)) throw new Error(text('保存尚未确认，请重试。','Save is unconfirmed. Please try again.'));
                feedback.textContent=text('默认设置已保存，Agent 创建新节点时会自动使用。','Defaults saved. Agents will use them for new nodes.');
            } catch(error){feedback.textContent=error.message;}
            finally {button.disabled=false;}
            return;
        }
        const key = button.dataset.capabilityParam, profile = defaultProfile();
        if(!key || !profile) return;
        const spec = profile.parameters[key], current = defaultDraft[defaultKind];
        let value;
        if(button.hasAttribute('data-capability-unset')) value=CAPABILITY_PARAMETER_UNSET;
        else if(button.hasAttribute('data-capability-step')){
            const old=capabilityParameterValues(profile,{capabilityParameters:{[profile.model_id]:current.parameters || current.run_settings?.rhParams || current.run_settings?.comfyParams || {}}})[key];
            value=(Number(old) || 0)+Number(button.dataset.capabilityStep)*Number(button.dataset.capabilityDelta || 1);
            if(spec.min !== undefined) value=Math.max(spec.min,value);
            if(spec.max !== undefined) value=Math.min(spec.max,value);
        } else {
            const raw=button.dataset.capabilityValue;
            value=spec.type === 'boolean' ? raw === 'true' : ['integer','number'].includes(spec.type) ? Number(raw) : raw;
        }
        setDefaultValue(key,value); renderDefaultEditor(key);
    });
    dialog.addEventListener('click', e => {
        if(!e.target.closest('.agent-default-param')) defaultsRoot.querySelectorAll('details[open]').forEach(item => item.open=false);
    });
    const refreshLabels = () => {
        button.querySelector('span').textContent = text('节点默认设置','Node defaults');
        button.title = text('设置新建节点的默认模型和参数','Set default models and parameters for new nodes');
        document.getElementById('canvasAgentHeading').textContent = text('节点默认设置','Node defaults');
        document.getElementById('canvasAgentClose').ariaLabel = text('关闭','Close');
    };
    button.addEventListener('click', () => {
        refreshLabels();
        defaultDraft = JSON.parse(JSON.stringify(canvasDefaultSmartSettings.agentDefaults || {}));
        feedback.textContent = "";
        renderDefaultEditor();
        dialog.showModal();
        dialog.scrollTop=0;
    });
    document.getElementById('canvasAgentClose').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', e => { if(e.target === dialog) dialog.close(); });
    ['wheel','pointerdown','dblclick'].forEach(event => dialog.addEventListener(event, e => e.stopPropagation()));
    refreshLabels();
    window.addEventListener('canvas-capabilities-ready', () => { if(dialog.open) renderDefaultEditor(); });
    window.addEventListener('studio-lang-change', () => { refreshLabels(); if(dialog.open) renderDefaultEditor(); });
})();
