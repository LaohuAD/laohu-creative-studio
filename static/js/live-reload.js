(function () {
    if (!['localhost', '127.0.0.1', '::1'].includes(location.hostname)) return;
    let revision = '';
    let files = {};
    let refreshing = false;
    let pendingRevision = null;
    let pendingTimer = null;
    function userIsEditing() {
        const active = document.activeElement;
        return Boolean(document.hidden || active?.matches?.('input,textarea,select,[contenteditable="true"]'));
    }
    function userIsBusy() {
        const active = document.activeElement;
        return Boolean(document.hidden || active?.matches?.('input,textarea,select,[contenteditable="true"]') || document.querySelector('.smart-popover.pinned,.modal.open,.dialog.open'));
    }
    function applyCssUpdates(previous, next) {
        const changed = Object.keys(next).filter(path => path.endsWith('.css') && previous[path] !== next[path]);
        if(!changed.length) return false;
        changed.forEach(path => document.querySelectorAll(`link[rel="stylesheet"][href*="/${path}"]`).forEach(link => {
            const url = new URL(link.href); url.searchParams.set('hot', next[path]); link.href = url.toString();
        }));
        return Object.keys(next).every(path => previous[path] === next[path] || path.endsWith('.css'));
    }
    async function check() {
        if (refreshing || document.visibilityState === 'hidden') return;
        try {
            const response = await fetch('/api/static-revision', { cache: 'no-store' });
            if (!response.ok) return;
            const payload = await response.json();
            const next = String(payload.revision || '');
            const nextFiles = payload.files && typeof payload.files === 'object' ? payload.files : {};
            if (!revision) { revision = next; files = nextFiles; }
            else if (next && next !== revision) {
                if(applyCssUpdates(files, nextFiles)){ revision = next; files = nextFiles; return; }
                if(userIsBusy()){
                    pendingRevision = {revision:next, files:nextFiles};
                    // An open popover is safe to discard; only an active text
                    // edit needs to wait for focusout. Avoid stale pages when a
                    // pinned parameter menu remains open indefinitely.
                    clearTimeout(pendingTimer);
                    pendingTimer = window.setTimeout(() => {
                        if(pendingRevision && !userIsEditing()){
                            refreshing = true;
                            location.reload();
                        }
                    }, 1200);
                    return;
                }
                refreshing = true;
                location.reload();
            }
        } catch (_) { /* 服务重启期间暂不打断页面 */ }
    }
    check();
    window.setInterval(check, 1500);
    // 页面在后台时暂停轮询，回到标签页后立即检查一次，避免用户必须手动刷新。
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') check();
    });
    window.addEventListener('focus', check);
    window.addEventListener('blur', () => {});
    document.addEventListener('focusout', () => {
        if(!pendingRevision) return;
        window.setTimeout(() => {
            if(pendingRevision && !userIsEditing()){ refreshing = true; location.reload(); }
        }, 500);
    });
})();
