(function(root, factory){
    const api = factory();
    if(typeof module === 'object' && module.exports) module.exports = api;
    if(root) root.SmartModelCapabilities = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function(){
    'use strict';

    function normalizeRegion(value){
        const region = String(value || '').trim().toLowerCase();
        return region === 'cn' || region === 'global' ? region : '';
    }

    function profileForRegion(model, region=''){
        const rawRegion = String(region || '').trim().toLowerCase();
        const wanted = normalizeRegion(rawRegion);
        if(!rawRegion || !model || typeof model !== 'object') return model || null;
        if(!wanted) return null;
        const regions = Array.isArray(model.regions)
            ? model.regions.map(normalizeRegion).filter(Boolean)
            : [];
        if(regions.length && !regions.includes(wanted)) return null;
        const scoped = model.region_profiles?.[wanted];
        if(scoped && typeof scoped === 'object') return {...model, ...scoped, region:wanted};
        return regions.length ? {...model, region:wanted} : model;
    }

    function providersForNodeType(catalog, nodeType, region=''){
        return (catalog?.providers || []).map(provider => ({
            ...provider,
            models:(provider.models || [])
                .map(model => profileForRegion(model, region))
                .filter(model => model && model.node_type === nodeType)
        })).filter(provider => provider.models.length);
    }

    function mediaLimits(inputs){
        const limits = {};
        Object.values(inputs || {}).forEach(spec => {
            const mediaType = String(spec?.media_type || '').trim();
            if(!mediaType) return;
            const current = limits[mediaType] || {min:0, max:0};
            current.min += Math.max(0, Number(spec?.min) || 0);
            current.max += Math.max(0, spec?.max == null ? 1 : Number(spec.max) || 0);
            limits[mediaType] = current;
        });
        return limits;
    }

    function normalizeInputRole(value){
        const role = String(value || '').trim().toLowerCase().replace(/-/g, '_');
        return ({first:'first_frame',last:'last_frame',reference_image:'reference',image_reference:'reference',audio_reference:'reference_audio'})[role] || role;
    }

    function roleLimits(inputs){
        const limits = {};
        Object.entries(inputs || {}).forEach(([key, spec]) => {
            const role = normalizeInputRole(spec?.role || key);
            if(!role) return;
            const current = limits[role] || {min:0,max:0,media_type:String(spec?.media_type || '').trim()};
            current.min += Math.max(0, Number(spec?.min) || 0);
            current.max += Math.max(0, spec?.max == null ? 1 : Number(spec.max) || 0);
            limits[role] = current;
        });
        return limits;
    }

    function modelSupportsParameters(model, parameters={}){
        if(model?.validation_mode !== 'strict') return false;
        const specs = model.parameters || {};
        return Object.entries(parameters || {}).every(([key, value]) => {
            if(key === '__execution_mode') return true;
            if(value === undefined || value === null || value === '' || value === '__canvas_unset__') return true;
            const spec = specs[key];
            if(!spec) return false;
            return !parameterIssue(spec, value);
        });
    }

    function modelExecutionMode(model){
        const operation = String(model?.operation || '').trim().toLowerCase().replace(/-/g, '_');
        return {
            text_to_video:'text2video',
            image_to_video:'image2video',
            multimodal_to_video:'multimodal2video',
            reference_to_video:'multimodal2video',
            compatible_video:'multimodal2video',
            start_end_to_video:'frames2video'
        }[operation] || '';
    }

    function modelSupportsExecutionMode(model, executionMode){
        const requested = String(executionMode || '').trim();
        if(!requested || model?.node_type !== 'video_generation') return true;
        const commands = (model?.platform?.commands || [])
            .map(command => String(command || '').trim())
            .filter(Boolean);
        // 本地 CLI 可能用一个聚合 operation 表示多条真实命令；命令白名单是更精确的运行依据。
        if(commands.length) return commands.includes(requested);
        const declared = modelExecutionMode(model);
        return !declared || declared === requested;
    }

    function modelSupportsInputs(model, inputCounts={}, inputRoles={}, parameters={}, region=''){
        model = profileForRegion(model, region);
        if(!model) return false;
        if(model?.validation_mode !== 'strict') return false;
        if(model?.readiness && model.readiness !== 'ready') return false;
        if(model?.runnable === false) return false;
        if(model?.selectable === false) return false;
        if(!modelSupportsExecutionMode(model, parameters?.__execution_mode)) return false;
        if(!modelSupportsParameters(model, parameters)) return false;
        const limits = mediaLimits(model.inputs);
        for(const [mediaType, rawCount] of Object.entries(inputCounts || {})){
            const count = Math.max(0, Number(rawCount) || 0);
            const limit = limits[mediaType];
            if(count > 0 && !limit) return false;
            if(limit && count > limit.max) return false;
        }
        if(!Object.entries(limits).every(([mediaType, limit]) => (Number(inputCounts?.[mediaType]) || 0) >= limit.min)) return false;
        const normalizedRoles = {};
        Object.entries(inputRoles || {}).forEach(([rawRole, rawCount]) => {
            const role = normalizeInputRole(rawRole);
            const count = Math.max(0, Number(rawCount) || 0);
            if(role && count) normalizedRoles[role] = (normalizedRoles[role] || 0) + count;
        });
        if(!Object.keys(normalizedRoles).length) return true;
        const declaredRoles = roleLimits(model.inputs);
        const roleMediaCounts = {};
        for(const [role, count] of Object.entries(normalizedRoles)){
            const limit = declaredRoles[role];
            if(!limit){
                const genericMediaType = role === 'reference' ? 'image' : '';
                const hasAssignableRole = genericMediaType && Object.values(declaredRoles).some(item => item.media_type === genericMediaType);
                if(hasAssignableRole && count <= (Number(inputCounts?.[genericMediaType]) || 0)) continue;
                return false;
            }
            if(count > limit.max) return false;
            if(limit.media_type) roleMediaCounts[limit.media_type] = (roleMediaCounts[limit.media_type] || 0) + count;
        }
        const coveredMediaTypes = new Set(Object.keys(roleMediaCounts));
        if(!Object.entries(declaredRoles).every(([role, limit]) => !coveredMediaTypes.has(limit.media_type) || (normalizedRoles[role] || 0) >= limit.min)) return false;
        return Object.entries(roleMediaCounts).every(([mediaType, count]) => count <= (Number(inputCounts?.[mediaType]) || 0));
    }

    function modelsForInputs(catalog, nodeType, inputCounts={}, inputRoles={}, parameters={}, region=''){
        return providersForNodeType(catalog, nodeType, region).flatMap(provider =>
            provider.models.filter(model => modelSupportsInputs(model, inputCounts, inputRoles, parameters, region)).map(model => ({
                ...model,
                provider_id:provider.id,
                provider_name:provider.name,
                protocol:provider.protocol
            }))
        );
    }

    function modelsForVerifiedInputs(catalog, nodeType, inputCounts={}, inputRoles={}, parameters={}, region=''){
        return providersForNodeType(catalog, nodeType, region).flatMap(provider =>
            provider.models.filter(model => {
                if(model?.validation_mode !== 'strict') return false;
                return modelSupportsInputs(model, inputCounts, inputRoles, parameters, region);
            }).map(model => ({
                ...model,
                provider_id:provider.id,
                provider_name:provider.name,
                protocol:provider.protocol
            }))
        );
    }

    function compatibleFamilyVariants(family, inputCounts={}, inputRoles={}, parameters={}, region=''){
        return (family?.variants || [])
            .map(model => profileForRegion(model, region))
            .filter(model => model && modelSupportsInputs(model, inputCounts, inputRoles, parameters, region));
    }

    function resolveFamilyVariant(family, inputCounts={}, operation='', inputRoles={}, parameters={}, region=''){
        const variants = compatibleFamilyVariants(family, inputCounts, inputRoles, parameters, region).filter(model => {
            if(!operation) return true;
            return model.operation === operation || model.variant_id === operation || model.model_id === operation;
        });
        if(variants.length === 1) return variants[0];
        if(!variants.length) return null;
        const exact = variants.filter(model => {
            const limits = mediaLimits(model.inputs);
            return ['text','image','video','audio'].every(mediaType => {
                const count = Number(inputCounts?.[mediaType]) || 0;
                const limit = limits[mediaType];
                return count === 0 ? !limit || limit.min === 0 : Boolean(limit && count >= limit.min && count <= limit.max);
            });
        });
        return exact.length === 1 ? exact[0] : null;
    }

    function familiesForInputs(catalog, nodeType, inputCounts={}, providerId='', operation='', inputRoles={}, parameters={}, region=''){
        return (catalog?.providers || []).filter(provider => !providerId || provider.id === providerId).flatMap(provider =>
            (provider.families || []).filter(family => family.node_type === nodeType).map(family => {
                const compatibleVariants = compatibleFamilyVariants(family, inputCounts, inputRoles, parameters, region);
                if(!compatibleVariants.length) return null;
                const resolved = resolveFamilyVariant(family, inputCounts, operation, inputRoles, parameters, region);
                return {
                    ...family,
                    provider_id:provider.id,
                    provider_name:provider.name,
                    protocol:provider.protocol,
                    compatible_variants:compatibleVariants,
                    resolved_variant:resolved
                };
            }).filter(Boolean)
        );
    }

    // 选择器按用户可见的模型系列合并跨平台条目；平台和真实 model_id
    // 仍保留在 variants 中，分别由第二、第三栏继续选择。
    function familiesAcrossProviders(catalog, nodeType, inputCounts={}, providerIds=[], operation='', inputRoles={}, parameters={}, region=''){
        const allowed = new Set((Array.isArray(providerIds) ? providerIds : [providerIds])
            .map(value => String(value || '').trim())
            .filter(Boolean));
        const merged = new Map();
        (catalog?.providers || []).forEach(provider => {
            const providerId = String(provider?.id || '').trim();
            if(!providerId || (allowed.size && !allowed.has(providerId))) return;
            const families = familiesForInputs(catalog, nodeType, inputCounts, providerId, operation, inputRoles, parameters, region);
            families.forEach(family => {
                const familyId = String(family?.family_id || '').trim();
                if(!familyId) return;
                const familyLabel = String(
                    family?.canonical_family_label?.zh || family?.display_name || family?.family_name ||
                    family?.canonical_family_label?.en || family?.display_name_en || family?.family_name_en || familyId
                ).trim();
                // 同名系列跨平台合并；去掉版本、档次等后缀只由能力档案负责，
                // 这里不根据 model_id 猜测系列，避免把不同系列误合并。
                const normalizedLabel = familySeriesKey(familyLabel, familyId);
                const key = `${nodeType}::${normalizedLabel || familyId.toLocaleLowerCase()}`;
                const variants = (family.compatible_variants || []).map(variant => ({
                    ...variant,
                    provider_id:providerId,
                    provider_name:provider.name,
                    protocol:provider.protocol,
                    family_id:familyId,
                    family_name:family.display_name || family.family_name || '',
                    family_name_en:family.display_name_en || family.family_name_en || ''
                }));
                if(!variants.length) return;
                let item = merged.get(key);
                if(!item){
                    item = {
                        ...family,
                        family_id:familyId,
                        canonical_family_label:family.canonical_family_label || {
                            zh:family.display_name || family.family_name || familyId,
                            en:family.display_name_en || family.family_name_en || familyId
                        },
                        provider_id:providerId,
                        provider_name:provider.name,
                        protocol:provider.protocol,
                        providers:[],
                        provider_ids:[],
                        variants:[],
                        compatible_variants:[]
                    };
                    merged.set(key, item);
                }
                if(!item.provider_ids.includes(providerId)){
                    item.provider_ids.push(providerId);
                    item.providers.push({id:providerId, name:provider.name, protocol:provider.protocol});
                }
                item.family_aliases = [...new Set([...(item.family_aliases || []), familyId])];
                variants.forEach(variant => {
                    const variantKey = `${variant.provider_id}::${variant.model_id || variant.variant_id || ''}`;
                    if(item.compatible_variants.some(existing => `${existing.provider_id}::${existing.model_id || existing.variant_id || ''}` === variantKey)) return;
                    item.compatible_variants.push(variant);
                    item.variants.push(variant);
                });
                item.resolved_variant = resolveFamilyVariant(item, inputCounts, operation, inputRoles, parameters, region);
            });
        });
        return [...merged.values()];
    }

    function familySeriesKey(label, familyId=''){
        let value = String(label || familyId || '').trim().toLocaleLowerCase();
        const aliases = [
            [/gpt\s*image|image[-_ ]?g|gpt[-_ ]?img/, 'gpt-image'],
            [/seedream|jimeng/, 'seedream'], [/seedance/, 'seedance'],
            [/minimax/, 'minimax'], [/hailuo|全能视频/, 'hailuo'],
            [/deepseek/, 'deepseek'], [/qwen/, 'qwen'], [/doubao|bytedance/, 'doubao'],
            [/glm/, 'glm'], [/kimi/, 'kimi'], [/kling/, 'kling'], [/vidu/, 'vidu'],
            [/nano[-_ ]?banana/, 'nano-banana'], [/wan/, 'wan'], [/suno/, 'suno'],
            [/mureka/, 'mureka'], [/flowmusic/, 'flowmusic'], [/whisper/, 'whisper']
        ];
        const alias = aliases.find(([pattern]) => pattern.test(value));
        if(alias) return alias[1];
        // 版本、档次和渠道属于第三栏，不应制造新的模型系列。
        value = value
            .replace(/\b(v|ver|version)[ ._-]*\d+(?:\.\d+)*\b/gi, '')
            .replace(/\b\d+(?:\.\d+)+(?:[- ]?(?:pro|lite|flash|turbo|fast|mini|max|plus|preview|global|standard))?\b/gi, '')
            .replace(/\s+\d{1,2}(?:\.\d+)*\b/gi, '')
            .replace(/\b(?:pro|lite|flash|turbo|fast|mini|max|plus|preview|global|standard)\b/gi, '');
        return value.replace(/[\s·•_./-]+/g, '') || String(familyId || '').toLocaleLowerCase();
    }

    function variantsAcrossProviders(catalog, nodeType, familyId, inputCounts={}, providerIds=[], operation='', inputRoles={}, parameters={}, region=''){
        const family = familiesAcrossProviders(catalog, nodeType, inputCounts, providerIds, operation, inputRoles, parameters, region)
            .find(item => item.family_id === familyId);
        return family ? [...(family.compatible_variants || [])] : [];
    }

    // 稳定机器标识：只使用机器字段，显示名与语言不参与，改文案或切换语言不改选择身份。
    function variantSelectionKey(variant){
        const providerId = String(variant?.provider_id || '').trim();
        const modelId = String(variant?.model_id || '').trim();
        const variantId = String(variant?.variant_id || '').trim();
        const operation = String(variant?.operation || '').trim();
        const machine = [providerId, variantId, operation, modelId].filter(Boolean).join('::');
        // 只有缺少 model_id 的退化数据才回退旧 key，保证同一 variant_id 下的 Fast/Mini 不被合并。
        return machine && modelId ? machine : (legacyVariantSelectionKey(variant) || machine);
    }

    // 旧 key：兼容历史数据与缺少 model_id 的退化档案，不得作为新数据的身份来源。
    function legacyVariantSelectionKey(variant){
        const variantId = String(variant?.variant_id || '').trim();
        const variantName = String(variant?.variant_name || '').trim();
        const variantNameEn = String(variant?.variant_name_en || '').trim();
        return [variantId, variantName, variantNameEn].filter(Boolean).join('::')
            || String(variant?.model_id || '').trim();
    }

    function matchesSearch(value, query){
        const tokens = String(query || '').trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
        if(!tokens.length) return true;
        const haystack = String(value || '').toLocaleLowerCase();
        return tokens.every(token => haystack.includes(token));
    }

    function familyForModel(provider, modelId, nodeType='', region=''){
        return (provider?.families || []).find(family =>
            (!nodeType || family.node_type === nodeType) &&
            (family.variants || []).some(variant => {
                const profile = profileForRegion(variant, region);
                return profile?.model_id === modelId;
            })
        ) || null;
    }

    function findModel(catalog, providerId, modelId, nodeType='', region=''){
        const provider = (catalog?.providers || []).find(item => item.id === providerId);
        return (provider?.models || [])
            .map(model => profileForRegion(model, region))
            .find(model => model && model.model_id === modelId && (!nodeType || model.node_type === nodeType)) || null;
    }

    // 单字段合法性判定：返回原因码或空串。只判断，不修改用户值。
    function parameterIssue(spec, value){
        if(!spec) return 'PARAM_INVALID';
        if(value === undefined || value === null) return spec.required || spec.level === 'required' ? 'PARAM_REQUIRED' : '';
        const type = String(spec.type || '').toLowerCase();
        const options = Array.isArray(spec.options) ? spec.options.map(String) : [];
        if(type === 'boolean'){
            // 只接受真实布尔值；已知字面量由迁移阶段转换，运行路径不做隐式强转（C18）。
            return typeof value === 'boolean' ? '' : 'PARAM_INVALID';
        }
        if(type === 'enum'){
            return options.includes(String(value)) ? '' : 'PARAM_INVALID';
        }
        if(options.length && !options.includes(String(value))) return 'PARAM_INVALID';
        if(type === 'integer' || type === 'number'){
            if(typeof value === 'boolean' || (typeof value !== 'number' && typeof value !== 'string') || String(value).trim() === '') return 'PARAM_INVALID';
            const numeric = Number(value);
            if(!Number.isFinite(numeric)) return 'PARAM_INVALID';
            if(type === 'integer' && !Number.isInteger(numeric)) return 'PARAM_INVALID';
            const step = Number(spec.step);
            const base = Number.isFinite(Number(spec.min)) ? Number(spec.min) : 0;
            if(Number.isFinite(step) && step > 0){
                const ratio = (numeric - base) / step;
                if(Math.abs(ratio - Math.round(ratio)) > 1e-9) return 'PARAM_INVALID';
            }
            if(spec.min != null && Number.isFinite(Number(spec.min)) && numeric < Number(spec.min)) return 'PARAM_INVALID';
            if(spec.max != null && Number.isFinite(Number(spec.max)) && numeric > Number(spec.max)) return 'PARAM_INVALID';
            return '';
        }
        return '';
    }

    // 报出非法或必填缺失的字段，供界面标红与运行前阻断使用。
    function parameterIssues(profile, values={}){
        const specs = (profile && profile.parameters) || {};
        const issues = {};
        Object.entries(specs).forEach(([key, spec]) => {
            const value = values?.[key] ?? (spec.ui_hidden ? (spec.type === 'model' ? profile.model_id : spec.default) : undefined);
            const issue = parameterIssue(spec, value);
            if(issue) issues[key] = issue;
        });
        return issues;
    }

    // 严格取值：只放行当前契约下本来就合法的值。
    // 不四舍五入、不裁剪到 min/max、不做字符串 truthy 转换——非法值交给 parameterIssues
    // 报出并由运行前校验阻断，绝不无提示地改变用户意图（§1.3、§6.6、C07/C09）。
    function effectiveParameters(profile, values={}){
        if(!profile || profile.validation_mode !== 'strict') return {...(values || {})};
        const specs = profile.parameters || {};
        const result = {};
        Object.entries(values || {}).forEach(([key, value]) => {
            if(value === undefined || value === null || value === '') return;
            const spec = specs[key];
            if(!spec) return;   // 档案未声明的参数一律不提交
            if(parameterIssue(spec, value)) return;
            result[key] = value;
        });
        return result;
    }

    function mediaAspectRatio(item){
        const width = Number(item?.natural_w || item?.naturalWidth || item?.width || item?.w || 0);
        const height = Number(item?.natural_h || item?.naturalHeight || item?.height || item?.h || 0);
        return width > 0 && height > 0 ? width / height : 0;
    }

    function requestedAspectRatio(value){
        const parts = String(value || '').trim().split(':').map(Number);
        return parts.length === 2 && parts[0] > 0 && parts[1] > 0 ? parts[0] / parts[1] : 0;
    }

    function resolveVideoExecutionMode(options={}){
        const imageRefs = Array.isArray(options.imageRefs) ? options.imageRefs.filter(Boolean) : [];
        const videoCount = Math.max(0, Number(options.videoCount) || 0);
        const audioCount = Math.max(0, Number(options.audioCount) || 0);
        if(options.useFrameRoles && imageRefs.length === 2 && !videoCount && !audioCount) return 'frames2video';
        if(options.forceMultimodal || videoCount || audioCount || imageRefs.length > 1) return 'multimodal2video';
        if(imageRefs.length === 1){
            const desiredRatio = requestedAspectRatio(options.parameters?.aspect_ratio);
            if(desiredRatio){
                const sourceRatio = mediaAspectRatio(imageRefs[0]);
                if(!sourceRatio || Math.abs(sourceRatio - desiredRatio) / desiredRatio > 0.01) return 'multimodal2video';
            }
            return 'image2video';
        }
        return 'text2video';
    }

    function capabilitySnapshot(profile, inputCounts={}, values={}){
        const sourceValues = values && typeof values === 'object' ? values : {};
        const effective = effectiveParameters(profile, sourceValues);
        const omitted = {};
        if(profile?.validation_mode === 'strict'){
            Object.entries(sourceValues).forEach(([key, value]) => {
                if(value === undefined || value === null || value === '') return;
                if(!Object.prototype.hasOwnProperty.call(effective, key)) omitted[key] = value;
            });
        }
        return {
            provider_id:profile?.provider_id || '',
            capability_provider_id:profile?.capability_provider_id || '',
            family_id:profile?.family_id || profile?.model_id || '',
            variant_id:profile?.variant_id || profile?.operation || '',
            model_id:profile?.model_id || '',
            node_type:profile?.node_type || '',
            operation:profile?.operation || '',
            profile_version:profile?.version ?? 0,
            validation_mode:profile?.validation_mode || 'compatible',
            evidence_level:profile?.evidence_level || '',
            input_counts:{...(inputCounts || {})},
            effective_parameters:effective,
            omitted_parameters:omitted,
            request_mapping:{...(profile?.request_mapping || {})}
        };
    }

    function compactRequest(values={}){
        return Object.fromEntries(Object.entries(values || {}).filter(([, value]) => value !== undefined));
    }

    function buildVideoRequest(profile, base={}, values={}){
        const effective = effectiveParameters(profile, values);
        const strict = profile?.validation_mode === 'strict';
        return compactRequest({
            ...(base || {}),
            duration:effective.duration ?? (strict ? undefined : 5),
            aspect_ratio:effective.aspect_ratio ?? (strict ? undefined : ''),
            resolution:effective.resolution ?? (strict ? undefined : ''),
            generate_audio:effective.generate_audio ?? (strict ? undefined : false),
            return_last_frame:effective.return_last_frame,
            seed:effective.seed,
            enhance_prompt:strict ? undefined : Boolean(effective.enhance_prompt),
            enable_upsample:strict ? undefined : Boolean(effective.enable_upsample),
            watermark:strict ? undefined : Boolean(effective.watermark),
            camerafixed:strict ? undefined : Boolean(effective.camerafixed),
            multimodal:base.multimodal !== undefined ? Boolean(base.multimodal) : (strict ? undefined : Boolean(effective.multimodal))
        });
    }

    function buildAudioRequest(profile, base={}, values={}){
        const effective = effectiveParameters(profile, values);
        const strict = profile?.validation_mode === 'strict';
        return compactRequest({
            ...(base || {}),
            speaker:effective.speaker ?? (strict ? undefined : ''),
            audio_format:effective.format ?? (strict ? undefined : 'mp3'),
            sample_rate:effective.sample_rate ?? (strict ? undefined : 24000),
            speech_rate:effective.speech_rate ?? (strict ? undefined : 0),
            loudness_rate:effective.loudness_rate ?? (strict ? undefined : 0),
            pitch_rate:effective.pitch_rate ?? (strict ? undefined : 0)
        });
    }

    return Object.freeze({
        providersForNodeType,
        normalizeRegion,
        profileForRegion,
        mediaLimits,
        normalizeInputRole,
        roleLimits,
        modelSupportsParameters,
        modelExecutionMode,
        modelSupportsExecutionMode,
        modelSupportsInputs,
        modelsForInputs,
        modelsForVerifiedInputs,
        compatibleFamilyVariants,
        resolveFamilyVariant,
        familiesForInputs,
        familyForModel,
        findModel,
        effectiveParameters,
        parameterIssue,
        parameterIssues,
        familiesAcrossProviders,
        variantsAcrossProviders,
        variantSelectionKey,
        legacyVariantSelectionKey,
        matchesSearch,
        resolveVideoExecutionMode,
        capabilitySnapshot,
        buildVideoRequest,
        buildAudioRequest
    });
});
