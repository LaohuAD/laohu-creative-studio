(function(root, factory){
    const api = factory();
    if(typeof module === 'object' && module.exports) module.exports = api;
    if(root) root.SmartNodeContract = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function(){
    'use strict';

    const SCHEMA_VERSION = 7;
    const EXECUTION_NODE_SIZE = Object.freeze({width:316, height:194});
    const NODE_TYPES = Object.freeze({
        material:'smart-material',
        textGenerator:'smart-text-generator',
        imageGenerator:'smart-image-generator',
        videoGenerator:'smart-video-generator',
        audioGenerator:'smart-audio-generator',
        musicGenerator:'smart-music-generator',
        aiApp:'smart-ai-app',
        comfyWorkflow:'smart-comfy-workflow',
        videoDirector:'smart-video-director',
        minimaxDirector:'smart-minimax-director',
        angleControl:'smart-angle-control',
        imageCompare:'smart-image-compare',
        resultGroup:'smart-result-group'
    });
    const EXECUTION_TYPES = new Set([
        NODE_TYPES.textGenerator,
        NODE_TYPES.imageGenerator,
        NODE_TYPES.videoGenerator,
        NODE_TYPES.audioGenerator,
        NODE_TYPES.musicGenerator,
        NODE_TYPES.aiApp,
        NODE_TYPES.comfyWorkflow
    ]);
    const TOOL_TYPES = new Set([NODE_TYPES.angleControl, NODE_TYPES.imageCompare]);
    const ANGLE_HORIZONTAL_LABELS = Object.freeze([
        [0, 'front view'],
        [45, 'front-right quarter view'],
        [90, 'right side view'],
        [135, 'back-right quarter view'],
        [180, 'back view'],
        [-135, 'back-left quarter view'],
        [-90, 'left side view'],
        [-45, 'front-left quarter view']
    ]);
    const ANGLE_VERTICAL_LABELS = Object.freeze([
        [-45, 'low-angle shot'],
        [0, 'eye-level shot'],
        [30, 'elevated shot'],
        [60, 'high-angle shot']
    ]);
    const ANGLE_DISTANCE_LABELS = Object.freeze([
        [0, 'wide shot'],
        [4, 'medium shot'],
        [8, 'close-up']
    ]);
    const ANGLE_HORIZONTAL_LABELS_ZH = Object.freeze([
        [0, '正面视角'],
        [45, '右前方四分之三视角'],
        [90, '右侧面视角'],
        [135, '右后方四分之三视角'],
        [180, '背面视角'],
        [-135, '左后方四分之三视角'],
        [-90, '左侧面视角'],
        [-45, '左前方四分之三视角']
    ]);
    const ANGLE_VERTICAL_LABELS_ZH = Object.freeze([
        [-45, '低机位仰拍'],
        [0, '平视'],
        [30, '高机位视角'],
        [60, '高机位俯拍']
    ]);
    const ANGLE_DISTANCE_LABELS_ZH = Object.freeze([
        [0, '全景'],
        [4, '中景'],
        [8, '特写']
    ]);
    const LEGACY_TYPES = new Set(['', 'smart-image', 'smart-container']);
    const EXECUTION_FIELDS = [
        'runSettings', 'promptDraftHtml', 'promptDraftText', 'promptDraftTouched',
        'manualInputRefs', 'blockedInputRefs', 'inputRefOrder', 'runPrompt', 'runModelPrompt',
        'runPromptRefs', 'runInputRefs', 'outpaintSize'
    ];
    const RESULT_FIELDS = [
        'images', 'outputKind', 'pending', 'pendingTasks', 'queued', 'jimengPending',
        'runStartedAt', 'runFinishedAt', 'runElapsedMs', 'runTimerHidden', 'running'
    ];

    function clone(value){
        return value == null ? value : JSON.parse(JSON.stringify(value));
    }
    function normalizeQueueInfo(queueInfo){
        const next = queueInfo && typeof queueInfo === 'object' && !Array.isArray(queueInfo)
            ? clone(queueInfo)
            : {};
        const rawPosition = next.queue_idx ?? next.queue_index ?? next.queue_position ?? next.position;
        const rawTotal = next.queue_length ?? next.queue_total ?? next.total;
        const position = Number(rawPosition);
        const total = Number(rawTotal);
        ['queue_idx','queue_index','queue_position','position','queue_length','queue_total','total'].forEach(key => delete next[key]);
        if(typeof rawPosition !== 'boolean' && typeof rawTotal !== 'boolean' && Number.isInteger(position) && Number.isInteger(total) && position > 0 && total > 0 && position <= total){
            next.queue_idx = position;
            next.queue_length = total;
        }
        return next;
    }
    function trustedQueueProgress(queueInfo){
        const normalized = normalizeQueueInfo(queueInfo);
        if(!normalized.queue_idx || !normalized.queue_length) return null;
        return {position:normalized.queue_idx, total:normalized.queue_length};
    }
    function nodeType(node){
        return String(node?.type || '').trim();
    }
    function normalizeInputRole(value){
        const role = String(value || '').trim().toLowerCase().replace(/-/g, '_');
        return ({first:'first_frame',last:'last_frame',reference_image:'reference',image_reference:'reference',audio_reference:'reference_audio'})[role] || role;
    }
    function isLegacyNode(node){
        return Boolean(node && LEGACY_TYPES.has(nodeType(node)));
    }
    function isMaterialNode(node){
        return Boolean(node && [NODE_TYPES.material, 'smart-image'].includes(nodeType(node)));
    }
    function isExecutionNode(node){
        return Boolean(node && EXECUTION_TYPES.has(nodeType(node)));
    }
    function isToolNode(node){
        return Boolean(node && TOOL_TYPES.has(nodeType(node)));
    }
    function isResultGroupNode(node){
        return Boolean(node && nodeType(node) === NODE_TYPES.resultGroup);
    }
    function connectionKind(connection){
        return String(connection?.kind || 'flow');
    }
    function isWorkflowConnection(connection){
        return ['input', 'flow'].includes(connectionKind(connection));
    }
    function isOutputLayoutConnection(connection){
        return ['input', 'flow', 'result'].includes(connectionKind(connection));
    }
    function connectionKindForNodes(fromNode, toNode){
        if(isExecutionNode(fromNode) && isMaterialNode(toNode) && toNode.isRunPlaceholder) return 'result';
        if(isToolNode(fromNode) && isMaterialNode(toNode) && textContentForNode(toNode)) return 'result';
        return 'input';
    }
    function isGeneratedMaterialNode(node){
        return isMaterialNode(node) && String(node?.sourceKind || '').toLowerCase() === 'result';
    }
    function canConnectNodes(fromNode, toNode){
        if(!fromNode || !toNode || fromNode.id === toNode.id) return false;
        const fromType = nodeType(fromNode);
        const toType = nodeType(toNode);
        if(toType === 'smart-group' || toType === 'smart-result-group') return false;
        if(isMaterialNode(fromNode)){
            if(isToolNode(toNode)) return (fromNode.images || []).some(item => mediaKindForReference(item) === 'image' && (item.url || item.path || item.src || item.uri));
            if(isMaterialNode(toNode)) return true;
            return isExecutionNode(toNode) || [
                'smart-prompt',
                'smart-loop',
                'smart-minimax',
                NODE_TYPES.videoDirector,
                NODE_TYPES.minimaxDirector
            ].includes(toType);
        }
        if(isExecutionNode(fromNode)) return isMaterialNode(toNode) || isExecutionNode(toNode) || isToolNode(toNode) || toType === 'smart-loop';
        if(isToolNode(fromNode)){
            if(fromType === NODE_TYPES.imageCompare) return false;
            return isMaterialNode(toNode) && Boolean(textContentForNode(toNode) || !toNode.images?.length);
        }
        if(isResultGroupNode(fromNode)) return isExecutionNode(toNode) || toType === 'smart-loop';
        if(fromType === 'smart-prompt') return isExecutionNode(toNode) || toType === 'smart-loop';
        if(fromType === 'smart-loop') return isExecutionNode(toNode) || isMaterialNode(toNode);
        if(fromType === 'smart-group') return isExecutionNode(toNode) || toType === 'smart-loop';
        return false;
    }
    function imageCompareTargetSlot(connections, targetId, preferred=''){
        const slots = ['left', 'right'];
        const requested = String(preferred || '').trim().toLowerCase();
        const incoming = (connections || []).filter(connection => !targetId || connection?.to === targetId);
        const occupied = new Set(incoming
            .map(connection => String(connection?.targetFieldKey || connection?.target_field_key || '').trim().toLowerCase())
            .filter(slot => slots.includes(slot)));
        let unassigned = incoming.filter(connection => {
            const slot = String(connection?.targetFieldKey || connection?.target_field_key || '').trim().toLowerCase();
            return !slots.includes(slot);
        }).length;
        slots.forEach(slot => {
            if(!occupied.has(slot) && unassigned > 0){
                occupied.add(slot);
                unassigned -= 1;
            }
        });
        if(slots.includes(requested)) return occupied.has(requested) ? '' : requested;
        return slots.find(slot => !occupied.has(slot)) || '';
    }
    function nearestAngleLabel(value, labels){
        const number = Number(value);
        if(!Number.isFinite(number)) return labels[0][1];
        return labels.reduce((best, item) => Math.abs(item[0] - number) < Math.abs(best[0] - number) ? item : best, labels[0])[1];
    }
    function anglePromptFor(options={}){
        const horizontal = Number(options.horizontalAngle || 0);
        const vertical = Number(options.verticalAngle || 0);
        const zoom = Number(options.zoom ?? 5);
        const chinese = String(options.language || options.lang || '').toLowerCase().startsWith('zh');
        const horizontalLabels = chinese ? ANGLE_HORIZONTAL_LABELS_ZH : ANGLE_HORIZONTAL_LABELS;
        const verticalLabels = chinese ? ANGLE_VERTICAL_LABELS_ZH : ANGLE_VERTICAL_LABELS;
        const distanceLabels = chinese ? ANGLE_DISTANCE_LABELS_ZH : ANGLE_DISTANCE_LABELS;
        return `<sks> ${nearestAngleLabel(horizontal, horizontalLabels)} ${nearestAngleLabel(vertical, verticalLabels)} ${nearestAngleLabel(zoom, distanceLabels)}`;
    }
    function normalizeExecutionSettings(node, settings){
        const next = clone(settings) || {};
        const type = nodeType(node);
        if(type !== NODE_TYPES.aiApp && next.engine === 'runninghub'){
            const match = String(next.rhConfigKey || '').match(/^model:(.+)$/);
            next.engine = 'api';
            next.provider_id = 'runninghub';
            if(match?.[1]) next.model = match[1];
        }
        if(type === NODE_TYPES.imageGenerator){
            next.apiKind = 'image';
            [
                'ratio', 'resolution', 'customRatio', 'customRatioWidth', 'customRatioHeight',
                'customSize', 'customWidth', 'customHeight', 'capabilityAspectRatio'
            ].forEach(key => delete next[key]);
        }
        if(type === NODE_TYPES.textGenerator) next.apiKind = 'text';
        if(type === NODE_TYPES.videoGenerator){
            next.apiKind = 'video';
            [
                'videoDuration', 'videoAspect', 'videoResolution', 'videoEnhancePrompt',
                'videoEnableUpsample', 'videoWatermark', 'videoCameraFixed',
                'videoGenerateAudio'
            ].forEach(key => delete next[key]);
        }
        if(type === NODE_TYPES.audioGenerator){
            next.engine = 'api';
            next.apiKind = 'audio';
        }
        if(type === NODE_TYPES.musicGenerator){
            next.engine = 'api';
            next.apiKind = 'music';
        }
        if(type === NODE_TYPES.aiApp){
            next.engine = 'runninghub';
            next.apiKind = 'image';
        }
        if(type === NODE_TYPES.comfyWorkflow){
            next.engine = 'comfy';
            next.apiKind = 'image';
            next.comfyMode = 'custom';
        }
        return next;
    }
    function normalizeExecutionNode(node){
        const copy = clone(node) || {};
        if(!isExecutionNode(copy)) return copy;
        copy.w = Math.max(EXECUTION_NODE_SIZE.width, Number(copy.w) || 0);
        copy.h = Math.max(EXECUTION_NODE_SIZE.height, Number(copy.h) || 0);
        copy.title = copy.title || titleForType(nodeType(copy));
        copy.outputKind = outputKindForType(nodeType(copy));
        copy.runSettings = normalizeExecutionSettings(copy, copy.runSettings || {});
        delete copy.scale;
        return copy;
    }
    function runningHubEntryKindsForType(type){
        return type === NODE_TYPES.aiApp ? ['app'] : ['model'];
    }
    function mediaItems(node){
        if(Array.isArray(node?.images)) return node.images;
        if(node?.inputImage?.url) return [node.inputImage];
        return [];
    }
    function hasMedia(node){
        return mediaItems(node).some(item => item?.url || item?.text || item?.content);
    }
    function runningHubApplicationConfigured(settings){
        if(String(settings?.engine || '').toLowerCase() !== 'runninghub') return false;
        return Boolean(
            settings?.rhAppId
            || settings?.rhWorkflowId
            || settings?.rhConfigKey
            || ['app', 'workflow'].includes(String(settings?.rhMode || '').toLowerCase())
        );
    }
    function executionTypeForSettings(settings, node={}){
        const apiKind = String(settings?.apiKind || node?.outputKind || '').toLowerCase();
        if(runningHubApplicationConfigured(settings)) return NODE_TYPES.aiApp;
        if(apiKind === 'music') return NODE_TYPES.musicGenerator;
        if(apiKind === 'audio') return NODE_TYPES.audioGenerator;
        if(apiKind === 'video') return NODE_TYPES.videoGenerator;
        return NODE_TYPES.imageGenerator;
    }
    function outputKindForType(type){
        if(type === NODE_TYPES.textGenerator) return 'text';
        if(type === NODE_TYPES.videoGenerator) return 'video';
        if(type === NODE_TYPES.audioGenerator) return 'audio';
        if(type === NODE_TYPES.musicGenerator) return 'audio';
        if(type === NODE_TYPES.aiApp) return 'dynamic';
        if(type === NODE_TYPES.comfyWorkflow) return 'dynamic';
        return 'image';
    }
    function mediaKindForReference(item){
        const explicit = String(item?.kind || item?.mediaKind || item?.media_type || item?.mediaType || item?.type || item?.outputType || item?.output_type || '').toLowerCase();
        if(['image', 'video', 'audio', 'text', 'file'].includes(explicit)) return explicit;
        const value = String(item?.url || item?.path || item?.src || item?.uri || '').toLowerCase().split('#')[0].split('?')[0];
        if(/\.(mp4|webm|mov|m4v|avi|mkv)$/.test(value)) return 'video';
        if(/\.(mp3|wav|m4a|aac|ogg|flac)$/.test(value)) return 'audio';
        if(/\.(txt|json|csv|srt|vtt|md)$/.test(value)) return 'text';
        return 'image';
    }
    function normalizeMediaReference(item, index=0, extra={}){
        const copy = clone(item) || {};
        const kind = mediaKindForReference(copy);
        const position = Math.max(0, Number(index) || 0) + 1;
        const url = String(copy.url || copy.path || copy.src || copy.uri || '');
        const resultUrlMatch = url.match(/^\/api\/results\/([^/?#]+)/i);
        const resultId = String(copy.result_id || copy.resultId || (resultUrlMatch ? decodeURIComponent(resultUrlMatch[1]) : '') || '').trim();
        return {
            ...copy,
            ...extra,
            kind,
            role:copy.role || `${kind}_${position}`,
            ...(resultId ? {resultId} : {})
        };
    }
    function runningHubUploadSource(value){
        const text = String(value || '').trim();
        if(!text) return '';
        let source = text;
        try{
            const parsed = new URL(text, 'http://localhost');
            if(parsed.pathname === '/api/media-preview') source = parsed.searchParams.get('url') || text;
        }catch(_error){}
        if(/^https?:\/\//i.test(source)) return source;
        if(/^\/(?:output|assets|api\/(?:materials|results|storage-files))\//i.test(source)) return source;
        return '';
    }
    function textContentForMediaItem(item){
        if(mediaKindForReference(item) !== 'text') return '';
        return String(item?.text ?? item?.content ?? '').trim();
    }
    function textContentForNode(node){
        return mediaItems(node)
            .map(textContentForMediaItem)
            .filter(Boolean)
            .join('\n\n');
    }
    function createTextMaterial(options={}){
        const id = String(options.id || '').trim();
        if(!id) return null;
        const text = String(options.text ?? options.content ?? '');
        const name = String(options.name || '未命名文本.md').trim() || '未命名文本.md';
        return {
            id,
            type:NODE_TYPES.material,
            sourceKind:String(options.sourceKind || 'input'),
            x:Number(options.x) || 0,
            y:Number(options.y) || 0,
            title:name,
            images:[normalizeMediaReference({
                kind:'text',
                name,
                text,
                content:text,
                url:String(options.url || '')
            }, 0)],
            created_at:Number(options.createdAt || options.created_at) || Date.now()
        };
    }
    function createTextGenerationRequest(localCommand, connectedTexts=[], media=[]){
        const command = String(localCommand || '').trim();
        const external = (connectedTexts || []).map(value => String(value || '').trim()).filter(Boolean);
        const message = [command, ...external].filter(Boolean).join('\n\n');
        const refs = {image:[], video:[], audio:[]};
        const references = (media || []).filter(item => item && (item.url || item.path || item.src || item.uri));
        const inputRoles = {prompt:message ? 1 : 0};
        references.forEach(item => {
            const kind = mediaKindForReference(item);
            const url = String(item?.url || item?.path || item?.src || item?.uri || '').trim();
            if(url && refs[kind]) refs[kind].push(url);
            if(!url) return;
            const explicitRole = normalizeInputRole(item?.role || '');
            const role = explicitRole && !new RegExp(`^${kind}_\\d+$`).test(explicitRole)
                ? explicitRole
                : kind === 'image' ? 'reference' : kind === 'video' ? 'source_video' : kind === 'audio' ? 'reference_audio' : '';
            if(role) inputRoles[role] = (inputRoles[role] || 0) + 1;
        });
        return {
            message,
            connectedTexts:external,
            references:clone(references),
            connectedTextCount:external.length,
            images:refs.image,
            videos:refs.video,
            audios:refs.audio,
            inputCounts:{
                text:message ? 1 : 0,
                image:refs.image.length,
                video:refs.video.length,
                audio:refs.audio.length
            },
            inputRoles
        };
    }
    function preflightGraphForNode(node, graphNodes=[], graphConnections=[]){
        const targetId = String(node?.id || '').trim();
        if(!targetId) return {nodes:[], connections:[]};
        const nodeMap = new Map((graphNodes || [])
            .filter(item => item && String(item.id || '').trim())
            .map(item => [String(item.id), item]));
        if(!nodeMap.has(targetId)) nodeMap.set(targetId, node);
        const included = new Set([targetId]);
        const relevant = [];
        const connections = Array.isArray(graphConnections) ? graphConnections : [];
        let changed = true;
        while(changed){
            changed = false;
            connections.forEach(connection => {
                const from = String(connection?.from || connection?.source || '').trim();
                const to = String(connection?.to || connection?.target || '').trim();
                if(!from || !to || !included.has(to) || included.has(from)) return;
                if(!nodeMap.has(from)) return;
                included.add(from);
                changed = true;
            });
        }
        connections.forEach(connection => {
            const from = String(connection?.from || connection?.source || '').trim();
            const to = String(connection?.to || connection?.target || '').trim();
            if(included.has(from) && included.has(to)) relevant.push(clone(connection));
        });
        const orderedNodes = (graphNodes || [])
            .filter(item => included.has(String(item?.id || '')))
            .map(clone);
        if(!orderedNodes.some(item => String(item?.id || '') === targetId)) orderedNodes.push(clone(node));
        return {nodes:orderedNodes, connections:relevant};
    }
    function createCanvasPreflightRequest(options={}){
        const graph = preflightGraphForNode(options.graphNode || options.node, options.graphNodes, options.graphConnections);
        const values = value => value && typeof value === 'object' ? clone(value) : {};
        return {
            canvas_id:String(options.canvasId || options.canvas_id || '').trim(),
            node_id:String(options.nodeId || options.node_id || options.node?.id || '').trim(),
            client_operation_id:String(options.clientOperationId || options.client_operation_id || '').trim(),
            provider_id:String(options.providerId || options.provider_id || '').trim(),
            model_id:String(options.modelId || options.model_id || '').trim(),
            family_id:String(options.familyId || options.family_id || '').trim(),
            operation:String(options.operation || '').trim(),
            node_type:String(options.nodeType || options.node_type || '').trim(),
            inputs:values(options.inputs),
            input_counts:values(options.inputCounts || options.input_counts),
            input_roles:values(options.inputRoles || options.input_roles),
            input_metadata:values(options.inputMetadata || options.input_metadata),
            parameters:values(options.parameters),
            nodes:graph.nodes,
            connections:graph.connections,
            ai_app_id:String(options.aiAppId || options.ai_app_id || '').trim(),
            app_field_values:values(options.appFieldValues || options.app_field_values)
        };
    }
    function createTextResultMaterial(sourceNode, text, options={}){
        const content = String(text || '').trim();
        const id = String(options.id || '').trim();
        const sourceId = String(sourceNode?.id || '').trim();
        if(!id || !sourceId || !content) return null;
        const resultId = String(options.resultId || options.result_id || '').trim();
        const url = String(options.url || '').trim();
        const name = String(options.name || '文本结果.md').trim() || '文本结果.md';
        const media = normalizeMediaReference({
            url,
            kind:'text',
            name,
            text:content,
            content,
            ...(resultId ? {resultId, result_id:resultId} : {}),
            provider:String(options.provider || '').trim(),
            model:String(options.model || '').trim()
        }, 0);
        return {
            node:{
                id,
                type:NODE_TYPES.material,
                sourceKind:'result',
                x:Number(options.x) || 0,
                y:Number(options.y) || 0,
                title:name,
                images:[media],
                created_at:Number(options.createdAt || options.created_at) || Date.now()
            },
            connection:{from:sourceId, to:id, kind:'result'}
        };
    }
    function createExecutionResultMaterial(sourceNode, media=[], options={}){
        const sourceId = String(sourceNode?.id || '').trim();
        const id = String(options.id || '').trim();
        if(!sourceId || !id || !isExecutionNode(sourceNode)) return null;
        const items = (Array.isArray(media) ? media : [media])
            .map((item, index) => normalizeMediaReference(item, index))
            .filter(item => item.url || textContentForMediaItem(item));
        if(!items.length) return null;
        const title = String(options.title || options.name || items[0]?.name || '生成结果').trim() || '生成结果';
        const runId = String(options.runId || options.run_id || sourceNode?.runRef?.runId || '').trim();
        return {
            node:{
                id,
                type:NODE_TYPES.material,
                sourceKind:'result',
                sourceExecutionNodeId:sourceId,
                ...(runId ? {sourceRunId:runId} : {}),
                x:Number(options.x) || 0,
                y:Number(options.y) || 0,
                title,
                images:items,
                created_at:Number(options.createdAt || options.created_at) || Date.now()
            },
            connection:{from:sourceId, to:id, kind:'result'}
        };
    }
    function executionRunErrorText(error, fallback='运行失败'){
        const value = error && typeof error === 'object' ? error.message : error;
        return String(value || fallback || '运行失败').trim() || '运行失败';
    }
    function isExecutionRunSubject(node){
        return Boolean(isExecutionNode(node) || (node?.type === NODE_TYPES.material && node?.sourceExecutionNodeId));
    }
    function markExecutionRunStarted(node, startedAt=Date.now()){
        if(!isExecutionRunSubject(node)) return node;
        node.runStatus = 'validating';
        node.runStartedAt = Number(startedAt) || Date.now();
        delete node.runFinishedAt;
        delete node.runElapsedMs;
        delete node.runError;
        delete node.runErrorAt;
        return node;
    }
    function markExecutionRunSucceeded(node, status='succeeded', finishedAt=Date.now()){
        if(!isExecutionRunSubject(node)) return node;
        node.runStatus = String(status || 'succeeded');
        node.runFinishedAt = Number(finishedAt) || Date.now();
        if(!node.runStartedAt) node.runStartedAt = node.runFinishedAt;
        node.runElapsedMs = Math.max(0, node.runFinishedAt - Number(node.runStartedAt || node.runFinishedAt));
        node.running = false;
        node.pending = 0;
        node.queued = false;
        delete node.runError;
        delete node.runErrorAt;
        return node;
    }
    function markExecutionRunFailed(node, error, failedAt=Date.now()){
        if(!isExecutionRunSubject(node)) return node;
        node.runStatus = 'failed';
        node.runError = executionRunErrorText(error);
        node.runErrorAt = Number(failedAt) || Date.now();
        node.running = false;
        node.pending = 0;
        node.queued = false;
        return node;
    }
    function resultGroupItems(group){
        return Array.isArray(group?.items) ? group.items : [];
    }
    function expandResultGroup(group, resolveNode){
        if(!isResultGroupNode(group) || typeof resolveNode !== 'function') return [];
        const refs = [];
        resultGroupItems(group).forEach((entry, groupIndex) => {
            const nodeId = String(entry?.nodeId || entry?.node_id || '').trim();
            const member = nodeId ? resolveNode(nodeId) : null;
            const media = mediaItems(member);
            const allowedResultIds = new Set(
                (entry?.resultIds || entry?.result_ids || [])
                    .map(value => String(value || '').trim())
                    .filter(Boolean)
            );
            media.forEach((item, mediaIndex) => {
                const resultId = String(item?.result_id || item?.resultId || '').trim();
                if(allowedResultIds.size && (!resultId || !allowedResultIds.has(resultId))) return;
                refs.push(normalizeMediaReference(item, refs.length, {
                    nodeId,
                    imageIndex:mediaIndex,
                    resultId,
                    resultGroupId:group.id || '',
                    resultGroupIndex:groupIndex,
                    round:Number(entry?.round || entry?.roundIndex || 0) || 0
                }));
            });
        });
        return refs;
    }
    function resultGroupMediaForConnection(group, connection, resolveNode){
        const refs = expandResultGroup(group, resolveNode);
        const resultId = String(connection?.sourceResultId || connection?.source_result_id || '').trim();
        if(!resultId) return refs;
        return refs.filter(item => String(item?.resultId || item?.result_id || '').trim() === resultId);
    }
    function runningHubFieldKey(field){
        return `${field?.nodeId ?? ''}::${field?.fieldName ?? ''}`;
    }
    function runningHubFieldMediaKind(field){
        const type = String(field?.fieldType || field?.type || '').trim().toLowerCase();
        if(['string','text'].includes(type)) return 'text';
        if(type === 'image') return 'image';
        if(type === 'video') return 'video';
        if(type === 'audio') return 'audio';
        return '';
    }
    function runningHubFieldSchemaKind(field){
        const mediaKind = runningHubFieldMediaKind(field);
        if(mediaKind) return mediaKind;
        const type = String(field?.fieldType || field?.type || '').trim().toLowerCase();
        if(['switch','select','combo','dropdown'].includes(type)) return 'select';
        if(['float','number','integer','int','slider'].includes(type)) return 'number';
        if(['boolean','bool'].includes(type)) return 'boolean';
        return type;
    }
    function runningHubTextFieldRole(field){
        const explicit = [field?.inputRole, field?.input_role, field?.semanticRole, field?.semantic_role, field?.role]
            .map(value => String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_'))
            .find(Boolean) || '';
        if(['prompt','positive_prompt','negative_prompt','caption','description','instruction'].includes(explicit)) return 'prompt';
        return 'text';
    }
    function runningHubCoerceFieldValue(field, value){
        const type = String(field?.fieldType || field?.type || '').trim().toUpperCase();
        if(value === undefined || value === null || String(value).trim() === '') return value;
        if(['FLOAT','NUMBER','SLIDER','INT','INTEGER'].includes(type)){
            const numberValue = typeof value === 'number' ? value : Number(String(value).trim());
            const key = runningHubFieldKey(field);
            const label = String(field?.label || field?.description || field?.fieldName || key).trim();
            if(!Number.isFinite(numberValue)) throw new Error(`RunningHub 字段“${label}”（${key}）要求数字，当前值为“${String(value)}”`);
            if(['INT','INTEGER'].includes(type) && !Number.isInteger(numberValue)) throw new Error(`RunningHub 字段“${label}”（${key}）要求整数，当前值为“${String(value)}”`);
            return numberValue;
        }
        return value;
    }
    function parseRunningHubOfficialFieldData(value){
        const result = {
            type:'',
            role:'',
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
        optionSource.filter(item => {
            if(item == null || item === metadata) return false;
            if(typeof item === 'object') return 'index' in item || 'value' in item || 'name' in item || 'label' in item;
            return Array.isArray(metadata?.options) && !knownTypes.has(String(item).trim().toUpperCase());
        }).forEach(item => {
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
    function normalizedRunningHubFieldType(official, fallback='TEXT'){
        const type = String(official?.type || fallback || 'TEXT').trim().toUpperCase();
        if(['IMAGE','VIDEO','AUDIO'].includes(type)) return type;
        if(official?.options?.length || ['SWITCH','SELECT','COMBO'].includes(type)) return 'SELECT';
        if(['BOOLEAN','BOOL'].includes(type)) return 'BOOLEAN';
        if(['FLOAT','NUMBER','INT','INTEGER'].includes(type)) return 'NUMBER';
        return 'TEXT';
    }
    function hydrateRunningHubAppEntry(entry){
        const copy = clone(entry) || {};
        const rawFields = Array.isArray(copy?.raw?.nodeInfoList) ? copy.raw.nodeInfoList : [];
        if(!rawFields.length) return copy;
        const officialByKey = new Map(rawFields.map(field => [runningHubFieldKey(field), field]));
        const savedByKey = new Map((Array.isArray(copy.fields) ? copy.fields : []).map(field => [runningHubFieldKey(field), field]));
        copy.fields = rawFields.map((rawField, index) => {
            const key = runningHubFieldKey(rawField);
            const saved = savedByKey.get(key) || {};
            const official = parseRunningHubOfficialFieldData(rawField?.fieldData);
            const label = String(rawField?.label || rawField?.title || rawField?.description || rawField?.name || saved?.label || rawField?.fieldName || '').trim();
            let fieldValue = saved?.fieldValue;
            if(fieldValue === undefined) fieldValue = rawField?.fieldValue ?? rawField?.defaultValue ?? rawField?.value ?? official.defaultValue ?? '';
            if(fieldValue && typeof fieldValue === 'object') fieldValue = JSON.stringify(fieldValue);
            return {
                ...saved,
                id:String(saved?.id || rawField?.id || key),
                nodeId:String(rawField?.nodeId ?? saved?.nodeId ?? ''),
                fieldName:String(rawField?.fieldName ?? saved?.fieldName ?? ''),
                fieldValue:fieldValue == null ? '' : String(fieldValue),
                fieldType:normalizedRunningHubFieldType(official, rawField?.fieldType || saved?.fieldType),
                inputRole:String(rawField?.inputRole ?? rawField?.input_role ?? rawField?.semanticRole ?? rawField?.semantic_role ?? rawField?.role ?? official.role ?? saved?.inputRole ?? saved?.input_role ?? '').trim(),
                label,
                enabled:saved?.enabled !== false,
                sourceFromUpstream:saved?.sourceFromUpstream !== false,
                group:String(saved?.group || rawField?.group || rawField?.category || 'AI 应用参数'),
                note:String(saved?.note || rawField?.note || rawField?.description || ''),
                options:official.options,
                optionLabels:official.optionLabels,
                acceptsUpload:official.acceptsUpload || ['IMAGE','VIDEO','AUDIO'].includes(String(rawField?.fieldType || '').toUpperCase()),
                required:rawField?.required === true || official.required,
                min:official.min !== '' ? official.min : rawField?.min ?? '',
                max:official.max !== '' ? official.max : rawField?.max ?? '',
                step:official.step !== '' ? official.step : rawField?.step ?? '',
                schemaOrder:index,
                imageOrder:Number(saved?.imageOrder ?? rawField?.imageOrder ?? rawField?.image_order ?? index) || 0
            };
        });
        (Array.isArray(entry?.fields) ? entry.fields : []).forEach((field, index) => {
            if(!officialByKey.has(runningHubFieldKey(field))){
                copy.fields.push({...clone(field), schemaOrder:rawFields.length + index});
            }
        });
        return copy;
    }
    function hydrateRunningHubProviderApps(provider){
        const copy = clone(provider) || {};
        if(String(copy.id || '').trim().toLowerCase() !== 'runninghub') return copy;
        if(Array.isArray(copy.rh_apps)) copy.rh_apps = copy.rh_apps.map(hydrateRunningHubAppEntry);
        if(copy.rh_regions && typeof copy.rh_regions === 'object' && !Array.isArray(copy.rh_regions)){
            Object.values(copy.rh_regions).forEach(region => {
                if(!region || typeof region !== 'object') return;
                if(Array.isArray(region.rh_apps)) region.rh_apps = region.rh_apps.map(hydrateRunningHubAppEntry);
            });
        }
        return copy;
    }
    function runningHubSchemaSnapshot(fields){
        return (fields || []).map((field, index) => {
            const savedKey = String(field?.key || '').trim();
            return {
                key:savedKey || runningHubFieldKey(field),
                kind:savedKey ? runningHubFieldSchemaKind({fieldType:field?.kind}) : runningHubFieldSchemaKind(field),
                required:field?.required === true,
                order:Number.isFinite(Number(field?.order ?? field?.schemaOrder ?? field?.imageOrder)) ? Number(field.order ?? field.schemaOrder ?? field.imageOrder) : index
            };
        }).filter(field => field.key !== '::');
    }
    function diffRunningHubSchema(savedFields, currentFields){
        const saved = runningHubSchemaSnapshot(savedFields);
        const current = runningHubSchemaSnapshot(currentFields);
        const savedHasMeaningfulOrder = new Set(saved.map(field => field.order)).size > 1;
        const savedByKey = new Map(saved.map(field => [field.key, field]));
        const currentByKey = new Map(current.map(field => [field.key, field]));
        const removed = saved.filter(field => !currentByKey.has(field.key)).map(field => field.key);
        const added = current.filter(field => !savedByKey.has(field.key)).map(field => field.key);
        const shared = current.filter(field => savedByKey.has(field.key));
        const typeChanged = shared.filter(field => savedByKey.get(field.key).kind !== field.kind).map(field => field.key);
        const requiredChanged = shared.filter(field => savedByKey.get(field.key).required !== field.required).map(field => field.key);
        const orderChanged = savedHasMeaningfulOrder
            ? shared.filter(field => savedByKey.get(field.key).order !== field.order).map(field => field.key)
            : [];
        return {
            changed:Boolean(removed.length || added.length || typeChanged.length || requiredChanged.length || orderChanged.length),
            removed,
            added,
            typeChanged,
            requiredChanged,
            orderChanged,
            saved,
            current
        };
    }
    function normalizeRunningHubOutputs(payload){
        const results = [];
        const seen = new Set();
        const explicitKind = (value, fallback='') => {
            const kind = String(value || '').trim().toLowerCase();
            if(kind.includes('video')) return 'video';
            if(kind.includes('audio')) return 'audio';
            if(kind.includes('text')) return 'text';
            if(kind.includes('image')) return 'image';
            return fallback;
        };
        const visit = (value, inheritedKind='') => {
            if(!value) return;
            if(Array.isArray(value)){
                value.forEach(item => visit(item, inheritedKind));
                return;
            }
            if(typeof value === 'string'){
                if(seen.has(value)) return;
                seen.add(value);
                results.push(normalizeMediaReference({url:value, kind:inheritedKind || mediaKindForReference({url:value})}, results.length));
                return;
            }
            if(typeof value !== 'object') return;
            const kindFromUrlKey = (value.audioUrl || value.audio_url) ? 'audio'
                : (value.videoUrl || value.video_url) ? 'video'
                : (value.imageUrl || value.image_url) ? 'image'
                : '';
            const kind = explicitKind(value.kind || value.type || value.mediaKind || value.media_type || value.outputType || value.output_type, kindFromUrlKey || inheritedKind);
            const url = value.url || value.path || value.src || value.uri || value.fileUrl || value.file_url || value.imageUrl || value.image_url || value.videoUrl || value.video_url || value.audioUrl || value.audio_url || value.downloadUrl || value.download_url || '';
            if(url && !seen.has(url)){
                seen.add(url);
                results.push(normalizeMediaReference({
                    ...value,
                    url,
                    kind:kind || mediaKindForReference({...value, url}),
                    name:value.name || value.filename || value.fileName || ''
                }, results.length));
            }
            const groups = [
                ['image_items','image'], ['images','image'],
                ['video_items','video'], ['videos','video'],
                ['audio_items','audio'], ['audios','audio'],
                ['text_items','text'], ['texts','text'],
                ['media_items',''], ['items',''], ['outputs',''], ['results',''], ['urls',''], ['data',''], ['result',''], ['output','']
            ];
            groups.forEach(([key, childKind]) => {
                if(value[key] !== undefined) visit(value[key], childKind || kind);
            });
        };
        visit(payload);
        return results;
    }
    function mediaReferenceKey(item, index=0){
        const resultId = String(item?.resultId || item?.result_id || '').trim();
        if(resultId) return `result:${resultId}`;
        const nodeId = String(item?.nodeId || item?.node_id || '').trim();
        const imageIndex = Number.isFinite(Number(item?.imageIndex ?? item?.image_index))
            ? Number(item?.imageIndex ?? item?.image_index)
            : Number(index) || 0;
        if(nodeId) return `node:${nodeId}:${imageIndex}`;
        const materialId = String(item?.materialId || item?.material_id || item?.assetId || item?.asset_id || '').trim();
        if(materialId) return `material:${materialId}`;
        const text = String(item?.text ?? item?.content ?? '').trim();
        if(text) return `text:${text}`;
        return `url:${String(item?.url || item?.path || item?.src || item?.uri || '')}`;
    }
    function referenceSlotEntryKey(entry, index=0){
        const explicit = String(entry?.key || '').trim();
        return explicit || mediaReferenceKey(entry?.item || entry, index);
    }
    function applyReferenceSlotOrder(entries, orderKeys){
        const normalized = (entries || []).map((entry, index) => ({entry, key:referenceSlotEntryKey(entry, index)}));
        const remaining = normalized.slice();
        const ordered = [];
        (orderKeys || []).forEach(value => {
            const key = String(value || '').trim();
            const index = remaining.findIndex(item => item.key === key);
            if(index < 0) return;
            ordered.push(remaining.splice(index, 1)[0].entry);
        });
        return [...ordered, ...remaining.map(item => item.entry)];
    }
    function swapReferenceSlotOrder(entries, orderKeys, firstKey, secondKey){
        const ordered = applyReferenceSlotOrder(entries, orderKeys);
        const keys = ordered.map(referenceSlotEntryKey);
        const first = keys.indexOf(String(firstKey || '').trim());
        const second = keys.indexOf(String(secondKey || '').trim());
        if(first < 0 || second < 0 || first === second) return keys;
        [keys[first], keys[second]] = [keys[second], keys[first]];
        return keys;
    }
    function runningHubMediaFields(fields){
        return (fields || []).filter(field => runningHubFieldMediaKind(field));
    }
    function reconcileRunningHubInputBindings(fields, refs, bindings){
        const normalizedRefs = (refs || []).map((item, index) => ({
            item,
            key:mediaReferenceKey(item, index),
            kind:mediaKindForReference(item)
        })).filter(entry => entry.key && entry.item);
        const refByKey = new Map(normalizedRefs.map(entry => [entry.key, entry]));
        const used = new Set();
        const next = {};
        const mediaFields = runningHubMediaFields(fields);
        mediaFields.forEach(field => {
            const fieldKey = runningHubFieldKey(field);
            const kind = runningHubFieldMediaKind(field);
            const requested = String(bindings?.[fieldKey] || '').trim();
            const requestedRef = refByKey.get(requested);
            if(requestedRef?.kind === kind && !used.has(requested)){
                next[fieldKey] = requested;
                used.add(requested);
            }
        });
        mediaFields.forEach(field => {
            const fieldKey = runningHubFieldKey(field);
            if(next[fieldKey]) return;
            const kind = runningHubFieldMediaKind(field);
            const sameKindFields = mediaFields.filter(item => runningHubFieldMediaKind(item) === kind);
            const sameKindRefs = normalizedRefs.filter(entry => entry.kind === kind);
            if(sameKindFields.length !== 1 || sameKindRefs.length !== 1) return;
            const fallback = normalizedRefs.find(entry => entry.kind === kind && !used.has(entry.key));
            if(!fallback) return;
            next[fieldKey] = fallback.key;
            used.add(fallback.key);
        });
        return next;
    }
    function runningHubBoundMedia(fields, refs, bindings){
        const resolvedBindings = reconcileRunningHubInputBindings(fields, refs, bindings);
        const refByKey = new Map((refs || []).map((item, index) => [mediaReferenceKey(item, index), item]));
        return Object.fromEntries(Object.entries(resolvedBindings).map(([fieldKey, refKey]) => [fieldKey, refByKey.get(refKey)]).filter(([, item]) => item));
    }
    function runningHubBindingsFromConnections(targetId, fields, refs, connections){
        const fieldByKey = new Map(runningHubMediaFields(fields).map(field => [runningHubFieldKey(field), field]));
        const entries = (refs || []).map((item, index) => ({
            item,
            key:mediaReferenceKey(item, index),
            kind:mediaKindForReference(item),
            sourceId:String(item?.inputSourceNodeId || item?.groupNodeId || item?.resultGroupId || item?.nodeId || item?.node_id || '').trim(),
            resultId:String(item?.resultId || item?.result_id || '').trim()
        })).filter(entry => entry.key && entry.item);
        const used = new Set();
        const bindings = {};
        (connections || []).forEach(connection => {
            if(targetId && String(connection?.to || '') !== String(targetId)) return;
            const fieldKey = String(connection?.targetFieldKey || connection?.target_field_key || '').trim();
            const field = fieldByKey.get(fieldKey);
            if(!field || bindings[fieldKey]) return;
            const sourceId = String(connection?.from || '').trim();
            const sourceResultId = String(connection?.sourceResultId || connection?.source_result_id || '').trim();
            const sourceMediaKey = String(connection?.sourceMediaKey || connection?.source_media_key || '').trim();
            const kind = runningHubFieldMediaKind(field);
            const matches = entries.filter(entry => {
                if(entry.kind !== kind || entry.sourceId !== sourceId) return false;
                if(sourceResultId && entry.resultId !== sourceResultId) return false;
                if(sourceMediaKey && entry.key !== sourceMediaKey) return false;
                return true;
            });
            const candidate = matches.find(entry => !used.has(entry.key)) || matches[0];
            if(!candidate) return;
            bindings[fieldKey] = candidate.key;
            used.add(candidate.key);
        });
        return bindings;
    }
    function assignRunningHubInputBinding(fields, refs, bindings, fieldKey, refKey){
        const mediaFields = runningHubMediaFields(fields);
        const field = mediaFields.find(item => runningHubFieldKey(item) === fieldKey);
        if(!field) return reconcileRunningHubInputBindings(fields, refs, bindings);
        const kind = runningHubFieldMediaKind(field);
        const entries = (refs || []).map((item, index) => ({
            key:mediaReferenceKey(item, index),
            kind:mediaKindForReference(item)
        }));
        const selected = entries.find(entry => entry.key === refKey && entry.kind === kind);
        if(!selected) return reconcileRunningHubInputBindings(fields, refs, bindings);
        const next = reconcileRunningHubInputBindings(fields, refs, bindings);
        const occupiedField = Object.keys(next).find(key => key !== fieldKey && next[key] === refKey);
        const previous = next[fieldKey];
        next[fieldKey] = refKey;
        if(occupiedField){
            if(previous) next[occupiedField] = previous;
            else delete next[occupiedField];
        }
        return reconcileRunningHubInputBindings(fields, refs, next);
    }
    function swapRunningHubInputBinding(fields, refs, bindings, fieldKey, direction){
        const mediaFields = runningHubMediaFields(fields);
        const fieldIndex = mediaFields.findIndex(field => runningHubFieldKey(field) === fieldKey);
        if(fieldIndex < 0) return reconcileRunningHubInputBindings(fields, refs, bindings);
        const kind = runningHubFieldMediaKind(mediaFields[fieldIndex]);
        const sameKind = mediaFields.filter(field => runningHubFieldMediaKind(field) === kind);
        const sameKindIndex = sameKind.findIndex(field => runningHubFieldKey(field) === fieldKey);
        const target = sameKind[sameKindIndex + (Number(direction) < 0 ? -1 : 1)];
        const next = reconcileRunningHubInputBindings(fields, refs, bindings);
        if(!target) return next;
        const targetKey = runningHubFieldKey(target);
        [next[fieldKey], next[targetKey]] = [next[targetKey], next[fieldKey]];
        return next;
    }
    function runningHubTargetFieldPlan(fields, sourceKind, connections=[], targetId=''){
        const kind = String(sourceKind || '').trim().toLowerCase();
        const choices = runningHubMediaFields(fields)
            .filter(field => runningHubFieldMediaKind(field) === kind)
            .map(field => ({
                key:runningHubFieldKey(field),
                label:String(field?.label || field?.description || field?.fieldName || runningHubFieldKey(field)),
                kind
            }));
        if(!choices.length) return {mode:'none', choices:[]};
        const occupied = new Set((connections || [])
            .filter(connection => !targetId || connection?.to === targetId)
            .map(connection => String(connection?.targetFieldKey || connection?.target_field_key || '').trim())
            .filter(Boolean));
        const available = choices.filter(choice => !occupied.has(choice.key));
        if(available.length === 1) return {mode:'auto', targetFieldKey:available[0].key, choices:available};
        if(available.length > 1) return {mode:'choose', choices:available};
        return {mode:'replace', choices:choices.map(choice => ({...choice, occupied:true}))};
    }
    function titleForType(type){
        if(type === NODE_TYPES.textGenerator) return '文本生成';
        if(type === NODE_TYPES.imageGenerator) return '图片生成';
        if(type === NODE_TYPES.videoGenerator) return '视频生成';
        if(type === NODE_TYPES.audioGenerator) return '音频生成';
        if(type === NODE_TYPES.musicGenerator) return '音乐生成';
        if(type === NODE_TYPES.aiApp) return 'AI 应用';
        if(type === NODE_TYPES.comfyWorkflow) return '本地 ComfyUI';
        if(type === NODE_TYPES.imageCompare) return '图像对比';
        if(type === NODE_TYPES.resultGroup) return '结果组';
        return '素材';
    }
    function legacyHasExecutionEvidence(node, incoming=[]){
        const settings = node?.runSettings;
        if(!settings || typeof settings !== 'object') return false;
        if(!hasMedia(node)) return true;
        if(node?.outputKind || node?.runAt || node?.sourceNodeId || node?.pendingTasks?.length) return true;
        if(node?.runInputRefs?.length || node?.runPromptRefs?.length || node?.promptDraftTouched) return true;
        if(String(node?.runPrompt || node?.runModelPrompt || node?.promptDraftText || '').trim()) return true;
        if(mediaItems(node).some(item => item?.generatedResult || item?.derived_from || item?.source_run_id)) return true;
        return incoming.some(connection => ['input', 'flow'].includes(String(connection?.kind || 'flow')));
    }
    function sourceKindForLegacy(node){
        const generated = Boolean(
            node?.outputKind
            || node?.runAt
            || node?.sourceNodeId
            || node?.runInputRefs?.length
            || mediaItems(node).some(item => item?.generatedResult || item?.derived_from || item?.source_run_id)
        );
        return generated ? 'result' : 'input';
    }
    function normalizeLegacyMedia(node){
        const copy = clone(node) || {};
        const items = mediaItems(copy);
        copy.type = NODE_TYPES.material;
        copy.images = items;
        copy.sourceKind = sourceKindForLegacy(copy);
        copy.title = copy.title || (items.length > 1 ? '素材组' : items[0]?.name || '素材');
        delete copy.inputImage;
        delete copy.steps;
        delete copy.resultGrouping;
        delete copy.imageMode;
        EXECUTION_FIELDS.forEach(field => delete copy[field]);
        copy.inputNodeIds = [];
        return copy;
    }
    function normalizeLegacyExecution(node, type, id){
        const copy = clone(node) || {};
        copy.id = id || copy.id;
        copy.type = type;
        copy.title = titleForType(type);
        copy.outputKind = outputKindForType(type);
        copy.w = Math.max(EXECUTION_NODE_SIZE.width, Number(copy.w) || 0);
        copy.h = Math.max(EXECUTION_NODE_SIZE.height, Number(copy.h) || 0);
        copy.runSettings = normalizeExecutionSettings(copy, copy.runSettings || {});
        RESULT_FIELDS.forEach(field => delete copy[field]);
        delete copy.inputImage;
        delete copy.scale;
        delete copy.historyFor;
        delete copy.isHistoryGroup;
        return copy;
    }
    function uniqueExecutionId(baseId, usedIds){
        const base = `${baseId || 'smart'}__run`;
        let value = base;
        let index = 2;
        while(usedIds.has(value)) value = `${base}_${index++}`;
        usedIds.add(value);
        return value;
    }
    function dedupeConnections(connections){
        const seen = new Set();
        return (connections || []).filter(connection => {
            if(!connection?.from || !connection?.to || connection.from === connection.to) return false;
            const sourceResultId = String(connection.sourceResultId || connection.source_result_id || '').trim();
            const sourceMediaKey = String(connection.sourceMediaKey || connection.source_media_key || '').trim();
            const targetFieldKey = String(connection.targetFieldKey || connection.target_field_key || '').trim();
            const key = `${connection.from}|${connection.to}|${connection.kind || 'flow'}|${sourceResultId}|${sourceMediaKey}|${targetFieldKey}`;
            if(seen.has(key)) return false;
            seen.add(key);
            return true;
        });
    }
    function migrateLegacyCanvas(rawNodes, rawConnections){
        const originalNodes = Array.isArray(rawNodes) ? rawNodes : [];
        let connections = clone(Array.isArray(rawConnections) ? rawConnections : []);
        const usedIds = new Set(originalNodes.map(node => node?.id).filter(Boolean));
        const nodes = [];
        let changed = false;

        originalNodes.forEach(rawNode => {
            if(!isLegacyNode(rawNode)){
                const current = clone(rawNode);
                nodes.push(isExecutionNode(current) ? normalizeExecutionNode(current) : current);
                return;
            }
            changed = true;
            const node = clone(rawNode) || {};
            const incoming = connections.filter(connection => connection.to === node.id);
            const executionType = executionTypeForSettings(node.runSettings || {}, node);
            const splitResult = hasMedia(node) && legacyHasExecutionEvidence(node, incoming);

            if(splitResult){
                const executionId = uniqueExecutionId(node.id, usedIds);
                const execution = normalizeLegacyExecution(node, executionType, executionId);
                const material = normalizeLegacyMedia(node);
                execution.x = Number(node.x || 0) - Math.max(396, Number(execution.w || 316) + 80);
                execution.y = Number(node.y || 0);
                execution.inputNodeIds = (node.inputNodeIds || []).filter(id => id && id !== node.id);
                material.sourceKind = 'result';
                material.inputNodeIds = [];
                connections = connections.map(connection => connection.to === node.id
                    ? {...connection, to:executionId}
                    : connection
                );
                connections.push({from:executionId, to:node.id, kind:'result'});
                nodes.push(execution, material);
                return;
            }

            if(hasMedia(node)){
                nodes.push(normalizeLegacyMedia(node));
                return;
            }
            if(node.runSettings && typeof node.runSettings === 'object'){
                nodes.push(normalizeLegacyExecution(node, executionType, node.id));
                return;
            }
            nodes.push(normalizeLegacyMedia(node));
        });

        return {
            schemaVersion:SCHEMA_VERSION,
            changed,
            nodes,
            connections:dedupeConnections(connections)
        };
    }

    return Object.freeze({
        SCHEMA_VERSION,
        EXECUTION_NODE_SIZE,
        NODE_TYPES,
        isLegacyNode,
        isMaterialNode,
        isGeneratedMaterialNode,
        isExecutionNode,
        isToolNode,
        isResultGroupNode,
        canConnectNodes,
        isWorkflowConnection,
        isOutputLayoutConnection,
        connectionKindForNodes,
        imageCompareTargetSlot,
        anglePromptFor,
        normalizeExecutionSettings,
        normalizeExecutionNode,
        normalizeQueueInfo,
        trustedQueueProgress,
        runningHubEntryKindsForType,
        executionTypeForSettings,
        outputKindForType,
        mediaKindForReference,
        normalizeInputRole,
        normalizeMediaReference,
        runningHubUploadSource,
        textContentForMediaItem,
        textContentForNode,
        createTextMaterial,
        createTextGenerationRequest,
        createCanvasPreflightRequest,
        createTextResultMaterial,
        createExecutionResultMaterial,
        executionRunErrorText,
        markExecutionRunStarted,
        markExecutionRunSucceeded,
        markExecutionRunFailed,
        expandResultGroup,
        resultGroupMediaForConnection,
        runningHubFieldKey,
        runningHubFieldMediaKind,
        runningHubTextFieldRole,
        runningHubCoerceFieldValue,
        parseRunningHubOfficialFieldData,
        hydrateRunningHubProviderApps,
        runningHubSchemaSnapshot,
        diffRunningHubSchema,
        normalizeRunningHubOutputs,
        mediaReferenceKey,
        applyReferenceSlotOrder,
        swapReferenceSlotOrder,
        reconcileRunningHubInputBindings,
        runningHubBoundMedia,
        runningHubBindingsFromConnections,
        assignRunningHubInputBinding,
        swapRunningHubInputBinding,
        runningHubTargetFieldPlan,
        titleForType,
        migrateLegacyCanvas
    });
});
