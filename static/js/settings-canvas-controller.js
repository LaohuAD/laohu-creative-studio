(function () {
    'use strict';

    const supportedCanvasIds = new Set([
        'hypit-settings', 'article-settings', 'music-settings', 'canvas-settings',
    ]);

    function detailMessage(payload, fallback) {
        const detail = payload?.detail;
        if (detail && typeof detail === 'object' && detail.message) return String(detail.message);
        if (typeof detail === 'string' && detail) return detail;
        return fallback;
    }

    function create(options = {}) {
        const id = String(options.id || '');
        const mode = String(options.mode || '');
        const endpoint = String(options.endpoint || '');
        const frame = options.frame;
        if (!supportedCanvasIds.has(id) || mode !== id) {
            throw new TypeError('Settings canvas identity must use one exact module settings ID and mode.');
        }
        if (!endpoint.startsWith('/api/') || endpoint.startsWith('//') || !frame) {
            throw new TypeError('Settings canvas requires a same-origin API path and iframe.');
        }

        let bootstrap = null;
        let bootstrapPromise = null;
        let loadPromise = null;
        let loaded = false;
        let active = false;
        let requestSequence = 0;
        let frameWaitCancel = null;

        function canvasUrl(payload, { embedded = true } = {}) {
            const url = new URL(String(payload?.url || ''), location.href);
            const ids = url.searchParams.getAll('id');
            const modes = url.searchParams.getAll('mode');
            if (url.origin !== location.origin
                || url.pathname !== '/static/smart-canvas.html'
                || ids.length !== 1 || ids[0] !== id
                || modes.length !== 1 || modes[0] !== mode
                || url.username || url.password || url.hash) {
                throw new Error(options.invalidUrlMessage?.() || 'The settings canvas address is invalid.');
            }
            if (embedded) url.searchParams.set('embedded', '1');
            else url.searchParams.delete('embedded');
            return `${url.pathname}${url.search}`;
        }

        async function loadBootstrap({ force = false } = {}) {
            if (bootstrapPromise) return bootstrapPromise;
            if (!force && bootstrap) return bootstrap;
            bootstrapPromise = (async () => {
                const response = await fetch(endpoint, { cache: 'no-store' });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(detailMessage(payload, `HTTP ${response.status}`));
                }
                if (payload?.id !== id || payload?.canvas?.id !== id) {
                    throw new Error(options.invalidPayloadMessage?.() || 'The settings canvas response has an invalid identity.');
                }
                canvasUrl(payload);
                bootstrap = payload;
                return payload;
            })().finally(() => { bootstrapPromise = null; });
            return bootstrapPromise;
        }

        function syncContext() {
            if (!active) return false;
            const target = frame?.contentWindow;
            if (!target || target === window) return false;
            try {
                const current = new URL(frame.getAttribute('src') || frame.src || '', location.href);
                if (current.origin !== location.origin
                    || current.pathname !== '/static/smart-canvas.html'
                    || current.searchParams.getAll('id').length !== 1
                    || current.searchParams.get('id') !== id
                    || current.searchParams.getAll('mode').length !== 1
                    || current.searchParams.get('mode') !== mode) return false;
                const preference = window.StudioTheme?.getPreference?.();
                if (preference) target.postMessage({ type: 'studio-theme', preference }, location.origin);
                target.postMessage({ type: 'studio-lang', lang: window.StudioI18n?.lang?.() || 'zh' }, location.origin);
                return true;
            } catch (_) {
                return false;
            }
        }

        function waitForFrame(src, sequence) {
            return new Promise((resolve, reject) => {
                let settled = false;
                const timer = setTimeout(() => finish(reject, new Error(options.timeoutMessage?.() || 'Canvas load timed out.')),
                    Number.isFinite(options.timeoutMs) ? options.timeoutMs : 15000);
                const cleanup = () => {
                    clearTimeout(timer);
                    frame.removeEventListener('load', onLoad);
                    frame.removeEventListener('error', onError);
                    if (frameWaitCancel === cancel) frameWaitCancel = null;
                };
                const finish = (complete, value) => {
                    if (settled) return;
                    settled = true;
                    cleanup();
                    complete(value);
                };
                const onLoad = () => finish(resolve, sequence === requestSequence && active);
                const onError = () => finish(reject, new Error(options.frameErrorMessage?.() || 'Canvas could not be opened.'));
                const cancel = () => finish(resolve, false);
                frameWaitCancel = cancel;
                frame.addEventListener('load', onLoad, { once: true });
                frame.addEventListener('error', onError, { once: true });
                frame.src = src;
            });
        }

        async function load({ force = false } = {}) {
            if (!active) return false;
            if (loadPromise) return loadPromise;
            if (!force && loaded && (frame?.getAttribute('src') || frame?.src)) {
                frame?.removeAttribute('hidden');
                options.onReady?.();
                syncContext();
                return true;
            }

            const sequence = ++requestSequence;
            frame?.setAttribute('hidden', 'hidden');
            options.onLoading?.();
            loadPromise = (async () => {
                try {
                    const payload = await loadBootstrap({ force });
                    if (sequence !== requestSequence || !active) return false;
                    const src = canvasUrl(payload);
                    const current = frame?.getAttribute('src') || '';
                    frame?.removeAttribute('hidden');
                    if (!loaded || current !== src || force) {
                        loaded = false;
                        const completed = await waitForFrame(src, sequence);
                        if (!completed) return false;
                    }
                    if (sequence !== requestSequence || !active) return false;
                    loaded = true;
                    syncContext();
                    options.onReady?.();
                    return true;
                } catch (error) {
                    if (sequence === requestSequence && active) {
                        loaded = false;
                        frame?.setAttribute('hidden', 'hidden');
                        options.onError?.(error);
                    }
                    return false;
                } finally {
                    if (sequence === requestSequence) loadPromise = null;
                }
            })();
            return loadPromise;
        }

        function activate() {
            active = true;
        }

        function deactivate() {
            active = false;
            requestSequence += 1;
            loadPromise = null;
            frameWaitCancel?.();
        }

        async function openInNewTab({ onBlocked, onError } = {}) {
            const opened = window.open('about:blank', '_blank');
            if (!opened) {
                onBlocked?.();
                return false;
            }
            const sequence = requestSequence;
            try { opened.opener = null; } catch (_) {}
            try {
                const payload = await loadBootstrap();
                const url = canvasUrl(payload, { embedded: false });
                opened.location.replace(new URL(url, location.origin).href);
                return true;
            } catch (error) {
                try { opened.close(); } catch (_) {}
                if (active && sequence === requestSequence) onError?.(error);
                return false;
            }
        }

        return Object.freeze({
            id,
            mode,
            activate,
            deactivate,
            load,
            loadBootstrap,
            canvasUrl,
            syncContext,
            openInNewTab,
            state: () => ({ active, loaded, loading: !!loadPromise, bootstrapped: !!bootstrap }),
        });
    }

    window.StudioSettingsCanvasController = Object.freeze({ create });
})();
