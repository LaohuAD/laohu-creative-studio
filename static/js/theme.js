(function(){
    const KEY = 'studio_theme';
    const LEGACY_KEY = 'canvas_theme';
    const PREFERENCE_KEY = 'studio_theme_preference_v1';
    const DEFAULT_THEME_ID = 'studio-violet';
    const APPEARANCES = ['light', 'dark', 'system'];
    const THEMES = [
        { id:'studio-violet', name:{zh:'紫色画室', en:'Violet Atelier'}, palette:{zh:'薰衣草紫 · 暖纸白 · 明黄', en:'Lavender · warm paper · marigold'} },
        { id:'sunlit', name:{zh:'日光画坊', en:'Sunlit Atelier'}, palette:{zh:'燕麦米 · 莳萝绿 · 奶油黄', en:'Oat · dill green · butter'} },
        { id:'vermilion', name:{zh:'朱砂创作', en:'Vermilion Studio'}, palette:{zh:'陶土红 · 玫瑰纸 · 麦芽金', en:'Terracotta · rose paper · malt gold'} },
        { id:'forest', name:{zh:'森林工坊', en:'Forest Workshop'}, palette:{zh:'鼠尾草 · 深林绿 · 麦穗金', en:'Sage · forest green · wheat'} },
        { id:'classic', name:{zh:'经典暖白', en:'Classic Warm'}, palette:{zh:'矿物灰 · 蓝绿石色 · 羊皮纸', en:'Mineral gray · blue teal · parchment'} }
    ];
    const THEME_IDS = new Set(THEMES.map(theme => theme.id));
    const SCALE_KEY = 'studio_ui_scale_mode';
    const SCALE_OPTIONS = ['auto', '60', '65', '70', '75', '80', '85', '90', '95', '100', '115', '125', '140'];
    const studioDialogQueue = [];
    let studioDialogActive = false;

    function studioDialogLanguage(){
        const value = String(window.StudioI18n?.lang?.() || document.documentElement.lang || 'zh').toLowerCase();
        return value.startsWith('en') ? 'en' : 'zh';
    }

    function studioDialogText(key){
        const copy = {
            confirm:{zh:'确定', en:'Confirm'},
            cancel:{zh:'取消', en:'Cancel'},
            info:{zh:'提示', en:'Notice'},
            warning:{zh:'请确认', en:'Please confirm'},
            danger:{zh:'危险操作', en:'Dangerous action'},
            input:{zh:'请输入内容', en:'Enter a value'}
        };
        return copy[key]?.[studioDialogLanguage()] || copy[key]?.zh || '';
    }

    function ensureStudioDialogStyle(){
        if(document.getElementById('studio-dialog-style')) return;
        const style = document.createElement('style');
        style.id = 'studio-dialog-style';
        style.textContent = `
            .studio-dialog-overlay {
                --studio-dialog-panel: var(--panel, var(--card, #fff));
                --studio-dialog-card: var(--card, var(--soft, rgba(127, 140, 160, .08)));
                --studio-dialog-text: var(--text, #172033);
                --studio-dialog-muted: var(--muted, #667085);
                --studio-dialog-line: var(--line, rgba(95, 109, 132, .24));
                --studio-dialog-strong: var(--strong, var(--accent, #172033));
                --studio-dialog-strong-text: var(--strong-text, #fff);
                position: fixed;
                inset: 0;
                z-index: 2147483000;
                display: grid;
                place-items: center;
                padding: 24px;
                background: rgba(5, 10, 18, .62);
                backdrop-filter: blur(10px) saturate(.88);
                -webkit-backdrop-filter: blur(10px) saturate(.88);
                animation: studio-dialog-fade-in 150ms ease-out both;
            }
            html.studio-theme-dark > .studio-dialog-overlay,
            html.theme-dark > .studio-dialog-overlay {
                --studio-dialog-panel: #1c1e26;
                --studio-dialog-card: #272a33;
                --studio-dialog-text: #e8e8ea;
                --studio-dialog-muted: #a4adbf;
                --studio-dialog-line: #3f424d;
                --studio-dialog-strong: #f5f6f8;
                --studio-dialog-strong-text: #0e1014;
            }
            .studio-dialog-panel {
                width: min(440px, calc(100vw - 32px));
                max-height: min(78vh, 620px);
                overflow: auto;
                box-sizing: border-box;
                color: var(--studio-dialog-text);
                background: var(--studio-dialog-panel);
                border: 1px solid var(--studio-dialog-line);
                border-radius: 18px;
                box-shadow: 0 24px 72px rgba(4, 10, 22, .28), 0 2px 10px rgba(4, 10, 22, .12);
                padding: 20px;
                animation: studio-dialog-panel-in 180ms cubic-bezier(.2,.78,.25,1) both;
            }
            .studio-dialog-heading {
                display: grid;
                grid-template-columns: 30px minmax(0, 1fr);
                align-items: center;
                gap: 11px;
                margin-bottom: 12px;
            }
            .studio-dialog-mark {
                width: 30px;
                height: 30px;
                display: grid;
                place-items: center;
                border-radius: 10px;
                color: var(--studio-dialog-strong-text);
                background: var(--studio-dialog-strong);
                font: 700 14px/1 ui-sans-serif, system-ui, sans-serif;
            }
            .studio-dialog-overlay[data-type="warning"] .studio-dialog-mark {
                color: #5c3900;
                background: #ffd98a;
            }
            .studio-dialog-overlay[data-type="danger"] .studio-dialog-mark {
                color: #fff;
                background: var(--danger, #d84b55);
            }
            .studio-dialog-title {
                margin: 0;
                min-width: 0;
                color: var(--studio-dialog-text);
                font: 700 15px/1.35 ui-sans-serif, system-ui, -apple-system, "PingFang SC", sans-serif;
                letter-spacing: -.01em;
            }
            .studio-dialog-message {
                margin: 0;
                color: var(--studio-dialog-muted);
                white-space: pre-wrap;
                overflow-wrap: anywhere;
                font: 500 13px/1.65 ui-sans-serif, system-ui, -apple-system, "PingFang SC", sans-serif;
            }
            .studio-dialog-input {
                width: 100%;
                box-sizing: border-box;
                margin-top: 14px;
                padding: 10px 12px;
                color: var(--studio-dialog-text);
                background: var(--studio-dialog-card);
                border: 1px solid var(--studio-dialog-line);
                border-radius: 10px;
                outline: none;
                font: 500 13px/1.4 ui-sans-serif, system-ui, -apple-system, "PingFang SC", sans-serif;
                transition: border-color 140ms ease, box-shadow 140ms ease;
            }
            .studio-dialog-input:focus {
                border-color: var(--studio-dialog-strong);
                box-shadow: 0 0 0 3px color-mix(in srgb, var(--studio-dialog-strong) 16%, transparent);
            }
            .studio-dialog-actions {
                display: flex;
                justify-content: flex-end;
                gap: 9px;
                margin-top: 18px;
            }
            .studio-dialog-btn {
                min-width: 76px;
                min-height: 36px;
                padding: 8px 15px;
                color: var(--studio-dialog-text);
                background: transparent;
                border: 1px solid var(--studio-dialog-line);
                border-radius: 10px;
                cursor: pointer;
                font: 650 13px/1 ui-sans-serif, system-ui, -apple-system, "PingFang SC", sans-serif;
                transition: transform 120ms ease, background 120ms ease, border-color 120ms ease;
            }
            .studio-dialog-btn:hover { background: var(--studio-dialog-card); }
            .studio-dialog-btn:active { transform: translateY(1px); }
            .studio-dialog-btn:focus-visible { outline: 2px solid var(--studio-dialog-strong); outline-offset: 2px; }
            .studio-dialog-btn.primary {
                color: var(--studio-dialog-strong-text);
                background: var(--studio-dialog-strong);
                border-color: var(--studio-dialog-strong);
            }
            .studio-dialog-btn.danger {
                color: #fff;
                background: var(--danger, #d84b55);
                border-color: var(--danger, #d84b55);
            }
            @keyframes studio-dialog-fade-in { from { opacity: 0; } to { opacity: 1; } }
            @keyframes studio-dialog-panel-in { from { opacity: 0; transform: translateY(8px) scale(.985); } to { opacity: 1; transform: none; } }
            @media (prefers-reduced-motion: reduce) {
                .studio-dialog-overlay, .studio-dialog-panel { animation: none; }
            }
        `;
        document.head.appendChild(style);
    }

    function ensureStudioDialogRoot(request, settle){
        ensureStudioDialogStyle();
        const type = ['info', 'warning', 'danger'].includes(request.type) ? request.type : 'info';
        const previousFocus = document.activeElement;
        const overlay = document.createElement('div');
        overlay.className = 'studio-dialog-overlay';
        overlay.dataset.type = type;
        const panel = document.createElement('section');
        panel.className = 'studio-dialog-panel';
        panel.setAttribute('role', request.kind === 'alert' ? 'alertdialog' : 'dialog');
        panel.setAttribute('aria-modal', 'true');
        const titleId = `studio-dialog-title-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        const messageId = `${titleId}-message`;
        panel.setAttribute('aria-labelledby', titleId);
        panel.setAttribute('aria-describedby', messageId);

        const heading = document.createElement('div');
        heading.className = 'studio-dialog-heading';
        const mark = document.createElement('span');
        mark.className = 'studio-dialog-mark';
        mark.setAttribute('aria-hidden', 'true');
        mark.textContent = type === 'danger' ? '!' : type === 'warning' ? '!' : 'i';
        const title = document.createElement('h2');
        title.id = titleId;
        title.className = 'studio-dialog-title';
        title.textContent = String(request.title || studioDialogText(type === 'info' && request.kind === 'prompt' ? 'input' : type));
        heading.append(mark, title);

        const message = document.createElement('p');
        message.id = messageId;
        message.className = 'studio-dialog-message';
        message.textContent = String(request.message ?? '');
        panel.append(heading, message);

        let input = null;
        if(request.kind === 'prompt'){
            input = document.createElement('input');
            input.className = 'studio-dialog-input';
            input.type = 'text';
            input.value = String(request.defaultValue ?? '');
            input.placeholder = String(request.placeholder || '');
            panel.appendChild(input);
        }

        const actions = document.createElement('div');
        actions.className = 'studio-dialog-actions';
        let closed = false;
        function close(value){
            if(closed) return;
            closed = true;
            document.removeEventListener('keydown', onKeyDown, true);
            overlay.remove();
            try { previousFocus?.focus?.({preventScroll:true}); } catch(_) { previousFocus?.focus?.(); }
            settle(value);
        }
        function cancel(){
            close(request.kind === 'confirm' ? false : request.kind === 'prompt' ? null : undefined);
        }
        function confirm(){
            close(request.kind === 'confirm' ? true : request.kind === 'prompt' ? input.value : undefined);
        }
        function onKeyDown(event){
            if(event.key === 'Escape'){
                event.preventDefault();
                cancel();
                return;
            }
            if(event.key === 'Enter' && !event.isComposing){
                event.preventDefault();
                confirm();
                return;
            }
            if(event.key === 'Tab'){
                const focusable = [...panel.querySelectorAll('button:not([disabled]), input:not([disabled])')];
                if(!focusable.length) return;
                const first = focusable[0];
                const last = focusable[focusable.length - 1];
                if(event.shiftKey && document.activeElement === first){ event.preventDefault(); last.focus(); }
                else if(!event.shiftKey && document.activeElement === last){ event.preventDefault(); first.focus(); }
            }
        }

        if(request.kind !== 'alert'){
            const cancelButton = document.createElement('button');
            cancelButton.type = 'button';
            cancelButton.className = 'studio-dialog-btn';
            cancelButton.textContent = String(request.cancelText || studioDialogText('cancel'));
            cancelButton.addEventListener('click', cancel);
            actions.appendChild(cancelButton);
        }
        const confirmButton = document.createElement('button');
        confirmButton.type = 'button';
        confirmButton.className = `studio-dialog-btn ${type === 'danger' ? 'danger' : 'primary'}`;
        confirmButton.textContent = String(request.confirmText || studioDialogText('confirm'));
        confirmButton.addEventListener('click', confirm);
        actions.appendChild(confirmButton);
        panel.appendChild(actions);
        overlay.appendChild(panel);
        overlay.addEventListener('pointerdown', event => {
            if(event.target === overlay) cancel();
        });
        document.documentElement.appendChild(overlay);
        document.addEventListener('keydown', onKeyDown, true);
        requestAnimationFrame(() => (input || confirmButton).focus());
        return overlay;
    }

    function showNextStudioDialog(){
        if(studioDialogActive || !studioDialogQueue.length) return;
        studioDialogActive = true;
        const item = studioDialogQueue.shift();
        ensureStudioDialogRoot(item.request, value => {
            studioDialogActive = false;
            item.resolve(value);
            showNextStudioDialog();
        });
    }

    function enqueueStudioDialog(request){
        return new Promise(resolve => {
            studioDialogQueue.push({request, resolve});
            showNextStudioDialog();
        });
    }

    window.StudioDialog = {
        alert(message, options={}) {
            return enqueueStudioDialog({kind:'alert', message, ...options});
        },
        confirm(message, options={}) {
            return enqueueStudioDialog({kind:'confirm', message, ...options});
        },
        prompt(message, options={}) {
            return enqueueStudioDialog({kind:'prompt', message, ...options});
        }
    };

    let remotePreference = null;
    let systemColorScheme = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
    let systemSchemeListener = null;
    let systemWindowListenersAttached = false;

    function safeStorageGet(key){
        try { return localStorage.getItem(key); } catch(e) { return null; }
    }

    function safeStorageSet(key, value){
        try { localStorage.setItem(key, value); return true; } catch(e) { return false; }
    }

    function validAppearance(value){
        return APPEARANCES.includes(value) ? value : null;
    }

    function legacyAppearance(){
        for(const key of [KEY, LEGACY_KEY]){
            const value = safeStorageGet(key);
            if(value === 'dark' || value === 'light') return value;
        }
        return 'light';
    }

    function normalizeStoredPreference(value){
        if(!value || typeof value !== 'object' || value.version !== 1) return null;
        const appearance = validAppearance(value.appearance);
        if(!appearance) return null;
        return {
            version: 1,
            themeId: THEME_IDS.has(value.themeId) ? value.themeId : DEFAULT_THEME_ID,
            appearance
        };
    }

    function readPreference(){
        const saved = safeStorageGet(PREFERENCE_KEY);
        if(saved !== null){
            try {
                const normalized = normalizeStoredPreference(JSON.parse(saved));
                if(normalized) return normalized;
            } catch(e) {}
            return { version:1, themeId:DEFAULT_THEME_ID, appearance:legacyAppearance() };
        }
        const migrated = { version:1, themeId:DEFAULT_THEME_ID, appearance:legacyAppearance() };
        safeStorageSet(PREFERENCE_KEY, JSON.stringify(migrated));
        return migrated;
    }

    function currentPreference(){
        return {...(remotePreference || readPreference())};
    }

    function resolvedAppearance(preference){
        if(preference.appearance !== 'system') return preference.appearance;
        return systemColorScheme?.matches ? 'dark' : 'light';
    }

    function currentTheme(){
        return resolvedAppearance(currentPreference());
    }

    function emitThemeChange(preference){
        const resolved = resolvedAppearance(preference);
        window.dispatchEvent(new CustomEvent('studio-theme-change', {
            detail:{ theme:resolved, themeId:preference.themeId, appearance:preference.appearance, resolvedAppearance:resolved }
        }));
    }

    function applyPreferenceToDocument(preference, emit=true){
        const resolved = resolvedAppearance(preference);
        const dark = resolved === 'dark';
        const root = document.documentElement;
        root.dataset.studioTheme = preference.themeId;
        root.dataset.studioAppearance = resolved;
        root.dataset.studioAppearanceMode = preference.appearance;
        root.style.colorScheme = resolved;
        root.classList.toggle('studio-theme-dark', dark);
        root.classList.toggle('theme-dark', dark);
        if(document.body){
            document.body.dataset.studioTheme = preference.themeId;
            document.body.dataset.studioAppearance = resolved;
            document.body.dataset.studioAppearanceMode = preference.appearance;
            document.body.classList.toggle('studio-theme-dark', dark);
            document.body.classList.toggle('theme-dark', dark);
        }
        if(emit) emitThemeChange(preference);
        return resolved;
    }

    function applyTheme(theme){
        if(theme !== 'dark' && theme !== 'light') return false;
        const preference = {...currentPreference(), appearance:theme};
        remotePreference = preference;
        applyPreferenceToDocument(preference);
        return true;
    }

    function applyPreference(preference){
        const normalized = normalizeStoredPreference({...preference, version:1});
        if(!normalized || !THEME_IDS.has(preference?.themeId) || !validAppearance(preference?.appearance)) return false;
        if(normalized.appearance === 'system') ensureSystemSchemeListener(true);
        remotePreference = normalized;
        applyPreferenceToDocument(normalized);
        return true;
    }

    function persistPreference(preference){
        const serialized = JSON.stringify(preference);
        const stored = safeStorageSet(PREFERENCE_KEY, serialized);
        const resolved = resolvedAppearance(preference);
        safeStorageSet(KEY, resolved);
        safeStorageSet(LEGACY_KEY, resolved);
        return stored;
    }

    function setPreference(preference){
        const normalized = normalizeStoredPreference({...preference, version:1});
        if(!normalized || !THEME_IDS.has(preference?.themeId) || !validAppearance(preference?.appearance)){
            throw new TypeError('无效的工作台主题偏好');
        }
        if(normalized.appearance === 'system') ensureSystemSchemeListener(true);
        remotePreference = null;
        if(!persistPreference(normalized)) remotePreference = normalized;
        applyPreferenceToDocument(normalized);
        return {...normalized};
    }

    function receiveThemeMessage(event){
        if(!event || event.origin !== window.location.origin) return false;
        const fromParent = window.parent !== window && event.source === window.parent;
        const fromOpener = window.opener && event.source === window.opener;
        if(!fromParent && !fromOpener) return false;
        const data = event.data;
        if(data?.type !== 'studio-theme') return false;
        if(data.preference) return applyPreference(data.preference);
        if(data.themeId && data.appearance) return applyPreference(data);
        return applyTheme(data.theme);
    }

    function ensureScaleStyle(){
        if(document.getElementById('studio-scale-style')) return;
        const style = document.createElement('style');
        style.id = 'studio-scale-style';
        style.textContent = `
            html.studio-scale-managed {
                --studio-ui-scale: 1;
            }
            html.studio-ui-scaled,
            html.studio-ui-scaled body {
                overscroll-behavior-x: none;
            }
            html.studio-ui-scaled {
                overflow-x: hidden !important;
            }
            html.studio-ui-scaled::-webkit-scrollbar:horizontal,
            html.studio-ui-scaled body::-webkit-scrollbar:horizontal {
                height: 0 !important;
            }
            html.studio-ui-scaled body:not(.studio-scale-host) {
                width: calc(100% / var(--studio-ui-scale)) !important;
                min-height: calc(100vh / var(--studio-ui-scale)) !important;
                transform: scale(var(--studio-ui-scale));
                transform-origin: 0 0;
            }
            html.studio-ui-scaled body.studio-scale-viewport:not(.studio-scale-host) {
                height: calc(100vh / var(--studio-ui-scale)) !important;
            }
            html.studio-ui-scaled body:not(.studio-scale-host) > .app-shell,
            html.studio-ui-scaled body:not(.studio-scale-host) > .shell,
            html.studio-ui-scaled body:not(.studio-scale-host) > .asset-page {
                width: 100% !important;
            }
            html.studio-ui-scaled body:not(.studio-scale-host) > .app-shell,
            html.studio-ui-scaled body:not(.studio-scale-host) > .shell {
                height: calc(100vh / var(--studio-ui-scale)) !important;
            }
            html.studio-ui-scaled body:not(.studio-scale-host) > .asset-page {
                min-height: calc(100vh / var(--studio-ui-scale)) !important;
            }
        `;
        document.head.appendChild(style);
    }

    function isFramed(){
        try {
            return window.self !== window.top;
        } catch(e) {
            return true;
        }
    }

    function normalizeScaleMode(mode){
        return SCALE_OPTIONS.includes(mode) ? mode : 'auto';
    }

    function currentScaleMode(){
        try {
            return normalizeScaleMode(localStorage.getItem(SCALE_KEY) || 'auto');
        } catch(e) {
            return 'auto';
        }
    }

    function autoScale(){
        // auto 只表示跟随当前 CSS 视口，不再用整页 transform 缩小内容。
        // 小屏断点由各页面响应式布局处理；显式百分比模式仍由 scaleForMode 单独应用。
        return 1;
    }

    function scaleForMode(mode){
        const next = normalizeScaleMode(mode);
        if(next === 'auto' && Number.isFinite(externalScaleValue)) return externalScaleValue;
        if(next === 'auto') return autoScale();
        return Math.max(0.58, Math.min(1.4, Number(next) / 100));
    }

    let externalScaleValue = null;
    function normalizeExternalScale(value){
        const next = Number(value);
        return Number.isFinite(next) ? Math.max(0.58, Math.min(1.4, next)) : null;
    }

    function appliedScale(){
        const cssValue = Number(getComputedStyle(document.documentElement).getPropertyValue('--studio-ui-scale'));
        return Number.isFinite(cssValue) && cssValue > 0 ? cssValue : scaleForMode(currentScaleMode());
    }

    function updateScaleBodyClasses(){
        if(!document.body) return;
        const hasFrameHost = !!document.querySelector('.app-shell iframe, iframe.active');
        document.body.classList.toggle('studio-scale-host', hasFrameHost && !isFramed());
        const computed = window.getComputedStyle(document.body);
        const viewportLocked = computed.overflow === 'hidden' || computed.overflowY === 'hidden' || !!document.querySelector('.app-shell, .shell');
        document.body.classList.toggle('studio-scale-viewport', viewportLocked);
    }

    function scaleOptedOut(){
        return document.documentElement.dataset.studioScale === 'off';
    }

    function contentFitOptedOut(){
        return document.documentElement.dataset.studioFitScale === 'off';
    }

    let horizontalScrollLockPending = false;
    function lockScaledHorizontalScroll(){
        if(horizontalScrollLockPending || !document.documentElement.classList.contains('studio-ui-scaled')) return;
        if(Math.abs(window.scrollX || 0) < 1) return;
        horizontalScrollLockPending = true;
        requestAnimationFrame(() => {
            horizontalScrollLockPending = false;
            if(document.documentElement.classList.contains('studio-ui-scaled') && Math.abs(window.scrollX || 0) >= 1) {
                window.scrollTo(0, window.scrollY || 0);
            }
        });
    }

    let contentFitTimer = null;
    function scheduleContentFit(mode){
        clearTimeout(contentFitTimer);
        if(mode !== 'auto' || scaleOptedOut() || contentFitOptedOut() || Number.isFinite(externalScaleValue)) return;
        contentFitTimer = setTimeout(() => {
            const root = document.documentElement;
            if(!root.classList.contains('studio-ui-scaled')) return;
            const current = Number(getComputedStyle(root).getPropertyValue('--studio-ui-scale')) || 1;
            const viewportWidth = Math.max(320, Number(window.innerWidth || 0));
            const contentWidth = Math.max(
                viewportWidth,
                root.scrollWidth || 0,
                document.body?.scrollWidth || 0,
                document.body?.offsetWidth || 0
            );
            const fitted = Math.max(0.58, Math.min(current, viewportWidth / contentWidth));
            if(fitted < current - 0.006) {
                root.style.setProperty('--studio-ui-scale', fitted.toFixed(3));
                lockScaledHorizontalScroll();
            }
        }, 80);
    }

    function applyScale(mode){
        ensureScaleStyle();
        const next = normalizeScaleMode(mode);
        const optedOut = scaleOptedOut();
        const value = scaleForMode(next);
        const scaled = !optedOut && Math.abs(value - 1) > 0.01;
        document.documentElement.classList.add('studio-scale-managed');
        document.documentElement.classList.toggle('studio-ui-scaled', scaled);
        document.documentElement.style.setProperty('--studio-ui-scale', value.toFixed(3));
        updateScaleBodyClasses();
        lockScaledHorizontalScroll();
        scheduleContentFit(next);
        window.dispatchEvent(new CustomEvent('studio-ui-scale-change', { detail: { mode: next, scale: value } }));
    }

    function broadcastScale(mode){
        const scale = appliedScale();
        document.querySelectorAll('iframe').forEach(frame => {
            try {
                frame.contentWindow?.postMessage({ type: 'studio-ui-scale', mode, scale }, '*');
            } catch(e) {}
        });
    }

    function setScaleMode(mode, shouldBroadcast = true){
        const next = normalizeScaleMode(mode);
        try {
            localStorage.setItem(SCALE_KEY, next);
        } catch(e) {}
        applyScale(next);
        if(shouldBroadcast) broadcastScale(next);
    }

    let resizeTimer = null;
    let autoScalePausedUntil = 0;
    function pauseAutoScale(duration = 650){
        autoScalePausedUntil = Math.max(autoScalePausedUntil, Date.now() + Math.max(0, Number(duration) || 0));
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(scheduleAutoScaleRefresh, Math.max(0, autoScalePausedUntil - Date.now()) + 40);
    }

    function scheduleAutoScaleRefresh(){
        clearTimeout(resizeTimer);
        const wait = autoScalePausedUntil - Date.now();
        if(wait > 0) {
            resizeTimer = setTimeout(scheduleAutoScaleRefresh, wait + 40);
            return;
        }
        resizeTimer = setTimeout(() => {
            if(currentScaleMode() === 'auto') {
                applyScale('auto');
                broadcastScale('auto');
            }
        }, 160);
    }

    window.StudioTheme = {
        key: KEY,
        preferenceKey: PREFERENCE_KEY,
        appearances: APPEARANCES.slice(),
        get: currentTheme,
        getPreference: currentPreference,
        listThemes(){ return THEMES.map(theme => ({id:theme.id, name:{...theme.name}, palette:{...theme.palette}})); },
        apply(theme){
            if(theme && typeof theme === 'object') return applyPreference(theme);
            return applyTheme(theme);
        },
        applyPreference,
        set(theme){
            if(theme !== 'dark' && theme !== 'light') return false;
            return setPreference({...currentPreference(), appearance:theme});
        },
        setPreference
    };

    window.StudioScale = {
        key: SCALE_KEY,
        options: SCALE_OPTIONS.slice(),
        getMode: currentScaleMode,
        getScale: () => scaleForMode(currentScaleMode()),
        apply: applyScale,
        set: setScaleMode
    };

    applyPreferenceToDocument(currentPreference());
    applyScale(currentScaleMode());

    document.addEventListener('DOMContentLoaded', () => {
        applyPreferenceToDocument(currentPreference());
        applyScale(currentScaleMode());
    });
    window.addEventListener('message', event => {
        receiveThemeMessage(event);
        if(event.data?.type === 'studio-ui-scale') {
            const incomingScale = normalizeExternalScale(event.data.scale);
            if(incomingScale !== null) externalScaleValue = incomingScale;
            setScaleMode(event.data.mode, false);
        }
        if(event.data?.type === 'studio-ui-scale-pause') pauseAutoScale(event.data.duration);
    });
    window.addEventListener('storage', event => {
        if(event.key === PREFERENCE_KEY){
            remotePreference = null;
            applyPreferenceToDocument(currentPreference());
        } else if((event.key === KEY || event.key === LEGACY_KEY) && !safeStorageGet(PREFERENCE_KEY)){
            remotePreference = null;
            applyPreferenceToDocument(currentPreference());
        }
        if(event.key === SCALE_KEY) applyScale(currentScaleMode());
    });
    function refreshSystemAppearance(){
        const preference = currentPreference();
        if(preference.appearance !== 'system') return;
        const resolved = resolvedAppearance(preference);
        if(document.documentElement.dataset.studioAppearance !== resolved) applyPreferenceToDocument(preference);
    }
    function ensureSystemSchemeListener(force=false){
        if(!window.matchMedia) return;
        if(force && systemColorScheme && systemSchemeListener){
            if(typeof systemColorScheme.removeEventListener === 'function'){
                systemColorScheme.removeEventListener('change', systemSchemeListener);
            } else if(typeof systemColorScheme.removeListener === 'function'){
                systemColorScheme.removeListener(systemSchemeListener);
            } else if(systemColorScheme.onchange === systemSchemeListener){
                systemColorScheme.onchange = null;
            }
        }
        if(force || !systemColorScheme) systemColorScheme = window.matchMedia('(prefers-color-scheme: dark)');
        if(!systemColorScheme || systemSchemeListener && !force) return;
        systemSchemeListener = refreshSystemAppearance;
        if(typeof systemColorScheme.addEventListener === 'function'){
            systemColorScheme.addEventListener('change', systemSchemeListener);
        } else if(typeof systemColorScheme.addListener === 'function'){
            systemColorScheme.addListener(systemSchemeListener);
        } else {
            systemColorScheme.onchange = systemSchemeListener;
        }
        if(!systemWindowListenersAttached){
            window.addEventListener('focus', refreshSystemAppearance);
            document.addEventListener('visibilitychange', refreshSystemAppearance);
            systemWindowListenersAttached = true;
        }
    }
    ensureSystemSchemeListener();
    window.addEventListener('resize', scheduleAutoScaleRefresh);
    window.addEventListener('scroll', lockScaledHorizontalScroll, { passive: true });
})();
