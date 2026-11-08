(function(){
    const ROOT_ID = 'laohuAccountCard';
    const API_ORIGIN = 'https://api.lao-hu.com';
    const LINKS = {
        console:`${API_ORIGIN}/keys`,
        wallet:`${API_ORIGIN}/wallet`,
        usage:`${API_ORIGIN}/usage-logs`
    };
    const byId = id => document.getElementById(id);
    const state = {
        active:false,
        epoch:0,
        readRevision:0,
        mutationRevision:0,
        status:null,
        readError:'',
        message:'',
        busy:'',
        readController:null,
        flowController:null,
        flow:null,
        flowTimer:null,
        providerRefresh:null,
        bound:false
    };

    function t(key, values={}){
        let result = window.StudioI18n?.t?.(key) || key;
        Object.entries(values).forEach(([name, value]) => {
            result = result.replaceAll(`{${name}}`, String(value ?? ''));
        });
        return result;
    }

    async function readResponse(response){
        let data = {};
        try { data = await response.json(); } catch(_error) {}
        if(!response.ok){
            const detail = data?.detail || data?.message || `${response.status} ${response.statusText || ''}`.trim();
            const error = new Error(String(detail || t('api.laohuLoadingFailed')));
            error.status = response.status;
            error.payload = data;
            throw error;
        }
        return data;
    }

    function statusPayload(data){
        if(data?.status && typeof data.status === 'object') return data.status;
        return data || {};
    }

    function credentialDisplay(current=state.status){
        const reauthRequired = current?.reauth_required === true || current?.connection_state === 'reauth_required';
        if(current?.mode === 'account' && (reauthRequired || (current?.connected !== true && current?.connection_state !== 'refresh_unavailable'))){
            return {kind:'none', configured:false, preview:t('api.laohuCredentialNone'), status:t('api.laohuCredentialNone')};
        }
        const credential = current?.active_credential && typeof current.active_credential === 'object'
            ? current.active_credential : null;
        if(credential?.configured === true && credential.kind === 'account'){
            return {kind:'account', configured:true, preview:'••••••••', status:t('api.laohuCredentialLoaded')};
        }
        if(credential?.configured === true && credential.kind === 'manual'){
            const candidate = String(credential.preview || '');
            const preview = /^••••••••.{0,4}$/u.test(candidate) ? candidate : '••••••••';
            return {kind:'manual', configured:true, preview, status:t('api.laohuCredentialManualEnabled')};
        }
        return {kind:'none', configured:false, preview:t('api.laohuCredentialNone'), status:t('api.laohuCredentialNone')};
    }

    function setMessage(message=''){
        state.message = String(message || '');
        const messageEl = byId('laohuAccountMessage');
        if(messageEl){
            messageEl.textContent = state.message;
            messageEl.hidden = !state.message;
        }
    }

    function checkedLaohuLink(value, fallback){
        if(!value) return fallback;
        try {
            const url = new URL(String(value), API_ORIGIN);
            const expected = new URL(fallback);
            if(url.origin !== API_ORIGIN || url.pathname !== expected.pathname || url.port || url.username || url.password || url.search || url.hash) return fallback;
            return url.href;
        } catch(_error){ return fallback; }
    }

    function loginUnavailableReason(current=state.status){
        const reason = String(current?.login_unavailable_reason || '').trim();
        if(!reason || reason === '登录服务尚未接入，请先使用手动 Key') return t('api.laohuLoginUnavailable');
        return reason;
    }

    function setLink(id, value, fallback){
        const link = byId(id);
        if(link) link.href = checkedLaohuLink(value, fallback);
    }

    function busyLabel(){
        if(state.busy === 'refresh') return t('api.laohuRefreshing');
        if(state.busy === 'logout') return t('api.laohuLoggingOut');
        if(state.busy === 'mode') return t('api.laohuSwitchingMode');
        if(state.busy === 'login') return t('api.laohuLoginStarting');
        return '';
    }

    function render(){
        const root = byId(ROOT_ID);
        if(!root) return;
        const current = state.status;
        const connected = current?.connected === true;
        const mode = current?.mode === 'account' ? 'account' : 'manual';
        const reauthRequired = current?.reauth_required === true || current?.connection_state === 'reauth_required';
        const refreshUnavailable = current?.connection_state === 'refresh_unavailable';
        const loginAvailable = current?.login_available === true;
        const accountSummaryVisible = connected || refreshUnavailable || (mode === 'account' && reauthRequired);
        const account = accountSummaryVisible && current?.account && typeof current.account === 'object' ? current.account : null;
        const connection = byId('laohuAccountConnection');
        const profile = byId('laohuAccountProfile');
        const username = byId('laohuAccountUsername');
        const balance = byId('laohuAccountBalance');
        const login = byId('laohuAccountLogin');
        const wallet = byId('laohuAccountWallet');
        const refresh = byId('laohuAccountRefresh');
        const logout = byId('laohuAccountLogout');
        const useAccount = byId('laohuAccountUseAccount');
        const savedManualKeyAvailable = current?.has_manual_key === true;
        const modelNotReady = connected && (current.model_authorized === false || current.execution_ready === false);
        let defaultMessage = '';

        root.hidden = !state.active;
        if(!state.active) return;
        if(connection){
            if(!current){
                connection.textContent = state.readError || t('api.laohuAccountLoading');
                connection.dataset.state = state.readError ? 'error' : 'loading';
            } else if(connected){
                connection.textContent = '';
                connection.dataset.state = 'connected';
                connection.hidden = true;
            } else {
                connection.textContent = '';
                connection.dataset.state = 'disconnected';
                connection.hidden = true;
            }
            if(!current) connection.hidden = false;
        }
        if(profile){
            profile.hidden = !account;
            if(account){
                if(username) username.textContent = String(account.username || account.id || '');
                if(balance) balance.textContent = String(account.balance_display ?? '—');
            }
        }
        if(login){
            login.hidden = connected || !loginAvailable || refreshUnavailable;
            login.disabled = Boolean(state.busy) || Boolean(state.flow);
            login.classList.toggle('primary-btn', !connected && loginAvailable);
            login.title = current && !loginAvailable
                ? loginUnavailableReason(current)
                : '';
            login.textContent = state.busy === 'login' ? t('api.laohuLoginStarting')
                : reauthRequired ? t('api.laohuReconnect') : t('api.laohuAccountLogin');
        }
        if(wallet) wallet.classList.toggle('primary-btn', connected || !loginAvailable);
        if(refresh){
            refresh.hidden = !connected;
            refresh.disabled = Boolean(state.busy);
            refresh.textContent = state.busy === 'refresh' ? t('api.laohuRefreshing') : t('api.laohuAccountRefresh');
        }
        if(logout){
            logout.hidden = !connected;
            logout.disabled = Boolean(state.busy);
            logout.textContent = state.busy === 'logout' ? t('api.laohuLoggingOut') : t('api.laohuAccountLogout');
        }
        if(useAccount){
            useAccount.hidden = !(connected && mode === 'manual');
            useAccount.disabled = Boolean(state.busy);
        }
        const keyInput = byId('keyInput');
        if(keyInput) keyInput.disabled = state.busy === 'mode';
        if(current){
            if(mode === 'manual'){
                if(savedManualKeyAvailable) defaultMessage = t('api.laohuManualKeyActive');
                else if(!connected && !loginAvailable) defaultMessage = loginUnavailableReason(current);
                else defaultMessage = t('api.laohuManualKeyMissing');
            } else if(reauthRequired){
                defaultMessage = t('api.laohuReauthRequired');
            } else if(refreshUnavailable && !connected){
                defaultMessage = t('api.laohuStatusTemporarilyUnavailable');
            } else if(!connected){
                defaultMessage = t('api.laohuAccountUnavailable');
            } else if(modelNotReady){
                defaultMessage = t('api.laohuModelUnauthorized');
            } else if(mode === 'account' && current.model_authorized === true && current.execution_ready === true){
                defaultMessage = t('api.laohuAccountActive');
            } else if(mode === 'account'){
                defaultMessage = t('api.laohuAccountConnected');
            }
        }
        const modeMessageEl = byId('laohuAccountModeMessage');
        if(modeMessageEl){
            modeMessageEl.textContent = defaultMessage;
            modeMessageEl.hidden = !defaultMessage;
        }
        const messageEl = byId('laohuAccountMessage');
        if(messageEl){
            messageEl.textContent = state.message;
            messageEl.hidden = !state.message;
        }
        setLink('laohuAccountConsole', current?.links?.console, LINKS.console);
        setLink('laohuAccountWallet', current?.links?.wallet, LINKS.wallet);
        setLink('laohuAccountUsage', current?.links?.usage, LINKS.usage);
        if(state.busy && state.busy !== 'login' && connection){
            connection.textContent = busyLabel();
            connection.dataset.state = 'busy';
        }
    }

    function visible(){
        return document.visibilityState !== 'hidden';
    }

    function stopFlowTimer(){
        if(state.flowTimer) clearTimeout(state.flowTimer);
        state.flowTimer = null;
    }

    function pauseReads(){
        if(state.readController){
            state.readController.abort();
            state.readController = null;
        }
    }

    async function refreshStatus({refreshProvider=true, allowHidden=false, expectedEpoch=null}={}){
        if(!state.active || (!visible() && !allowHidden) || (expectedEpoch != null && expectedEpoch !== state.epoch)) return null;
        const epoch = state.epoch;
        const revision = ++state.readRevision;
        if(state.readController) state.readController.abort();
        const controller = new AbortController();
        state.readController = controller;
        try {
            const data = await readResponse(await fetch('/api/laohu/account/status', {
                method:'GET',
                credentials:'same-origin',
                signal:controller.signal,
                cache:'no-store'
            }));
            if(!state.active || epoch !== state.epoch || revision !== state.readRevision || (expectedEpoch != null && expectedEpoch !== state.epoch) || (!visible() && !allowHidden)) return null;
            state.status = statusPayload(data);
            state.readError = '';
            setMessage(state.status?.connection_state === 'refresh_unavailable' && state.status?.connected === true
                ? t('api.laohuStatusRefreshStale')
                : '');
            render();
            window.dispatchEvent(new Event('laohu-account-status'));
            const manualCredentialActive = state.status?.mode === 'manual'
                && state.status?.active_credential?.kind === 'manual'
                && state.status?.active_credential?.configured === true;
            const accountCredentialReady = state.status?.connected === true
                && state.status?.model_authorized !== false
                && state.status?.execution_ready !== false;
            if(refreshProvider && (manualCredentialActive || accountCredentialReady) && typeof state.providerRefresh === 'function'){
                await state.providerRefresh({epoch});
            }
            return state.status;
        } catch(error){
            if(error?.name === 'AbortError' || !state.active || epoch !== state.epoch || revision !== state.readRevision) return null;
            state.readError = t('api.laohuStatusTemporarilyUnavailable');
            setMessage(state.readError);
            render();
            return null;
        } finally {
            if(state.readController === controller) state.readController = null;
        }
    }

    function actionHeaders(){
        return {'Content-Type':'application/json', 'X-Laohu-Account-Action':'1'};
    }

    async function runMutation(kind, path, body={}){
        if(!state.active || state.busy) return null;
        const epoch = state.epoch;
        const revision = ++state.mutationRevision;
        state.busy = kind;
        setMessage('');
        render();
        try {
            const data = await readResponse(await fetch(path, {
                method:'POST',
                credentials:'same-origin',
                headers:actionHeaders(),
                body:JSON.stringify(body)
            }));
            if(!state.active || epoch !== state.epoch || revision !== state.mutationRevision) return null;
            if(data?.mode || data?.connected != null || data?.account || data?.links){
                state.status = statusPayload(data);
            } else if(data?.status && typeof data.status === 'object'){
                state.status = data.status;
            }
            state.busy = '';
            render();
            await refreshStatus();
            return data;
        } catch(error){
            if(!state.active || epoch !== state.epoch || revision !== state.mutationRevision) return null;
            if(kind === 'refresh'){
                const updated = await refreshStatus({refreshProvider:false, expectedEpoch:epoch});
                if(!state.active || epoch !== state.epoch || revision !== state.mutationRevision) return null;
                if(updated){
                    const reauthRequired = updated.reauth_required === true || updated.connection_state === 'reauth_required';
                    if(reauthRequired){
                        setMessage(updated.mode === 'account' ? '' : t('api.laohuReauthRequired'));
                    } else if(updated.connection_state === 'refresh_unavailable'){
                        setMessage(updated.connected === true
                            ? t('api.laohuStatusRefreshStale')
                            : t('api.laohuStatusTemporarilyUnavailable'));
                    } else {
                        setMessage(t('api.laohuStatusTemporarilyUnavailable'));
                    }
                }
                state.busy = '';
                render();
                return null;
            }
            state.busy = '';
            render();
            setMessage(t('api.laohuRequestFailed', {message:error.message || 'Request failed'}));
            return null;
        }
    }

    function operationId(){
        try { if(window.crypto?.randomUUID) return window.crypto.randomUUID(); } catch(_error) {}
        return `laohu-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }

    function closePopup(popup){
        try { if(popup && !popup.closed) popup.close(); } catch(_error) {}
    }

    function safeAuthorizationUrl(value){
        try {
            const url = new URL(String(value || ''));
            if(url.origin !== API_ORIGIN || url.pathname !== '/authorize' || url.port || url.username || url.password || url.hash) return '';
            return url.href;
        } catch(_error){ return ''; }
    }

    function scheduleFlowPoll(){
        stopFlowTimer();
        if(!state.flow || !state.active || state.flow.epoch !== state.epoch) return;
        if(state.flowController) return;
        if(Date.now() >= state.flow.expiresAt){
            void finishFlow('expired');
            return;
        }
        state.flowTimer = setTimeout(() => { void pollFlow(); }, 1100);
    }

    async function finishFlow(result, message=''){
        const flow = state.flow;
        if(!flow) return;
        state.flow = null;
        stopFlowTimer();
        if(result === 'succeeded'){
            closePopup(flow?.popup);
            setMessage('');
            state.busy = 'login';
            render();
            const updated = await refreshStatus({allowHidden:true, expectedEpoch:flow.epoch});
            if(!state.active || flow.epoch !== state.epoch) return;
            state.busy = '';
            render();
            if(updated && updated.connected !== true){
                setMessage(t('api.laohuLoginStatusNotConnected'));
            }
            render();
            return;
        }
        closePopup(flow?.popup);
        if(result === 'expired') setMessage(t('api.laohuLoginExpired'));
        else setMessage(t('api.laohuLoginFailed', {message:message || t('api.laohuRequestFailed', {message:'Unknown error'})}));
        render();
    }

    async function pollFlow(){
        const flow = state.flow;
        if(!flow || !state.active || flow.epoch !== state.epoch || state.flowController) return;
        if(Date.now() >= flow.expiresAt){
            await finishFlow('expired');
            return;
        }
        const controller = new AbortController();
        state.flowController = controller;
        try {
            const data = await readResponse(await fetch(`/api/laohu/account/login/${encodeURIComponent(flow.id)}`, {
                method:'GET', credentials:'same-origin', signal:controller.signal, cache:'no-store'
            }));
            if(state.flow !== flow || !state.active || flow.epoch !== state.epoch) return;
            const result = statusPayload(data);
            if(result.status === 'succeeded'){
                await finishFlow('succeeded');
                return;
            }
            if(result.status === 'failed'){
                await finishFlow('failed', result.message || '');
                return;
            }
            if(result.status !== 'pending'){
                await finishFlow('failed', result.message || String(result.status || 'Unexpected login state'));
                return;
            }
            setMessage(t('api.laohuLoginWaiting'));
            render();
            if(state.flowController === controller) state.flowController = null;
            scheduleFlowPoll();
        } catch(error){
            if(error?.name !== 'AbortError' && state.flow === flow && state.active && flow.epoch === state.epoch){
                await finishFlow('failed', error.message || 'Request failed');
            }
        } finally {
            if(state.flowController === controller) state.flowController = null;
        }
    }

    async function login(){
        if(!state.active || state.busy || state.flow) return;
        if(state.status?.login_available !== true){
            setMessage(loginUnavailableReason());
            return;
        }
        // 必须在点击事件同步阶段预开标签，避免异步拿到授权 URL 后被浏览器拦截。
        let popup = null;
        try { popup = window.open('about:blank', 'laohu-account-login'); } catch(_error) {}
        if(!popup){
            setMessage(t('api.laohuPopupBlocked'));
            return;
        }
        try { popup.document.title = 'laohu'; } catch(_error) {}
        const epoch = state.epoch;
        const revision = ++state.mutationRevision;
        state.busy = 'login';
        setMessage('');
        render();
        try {
            const data = await readResponse(await fetch('/api/laohu/account/login', {
                method:'POST', credentials:'same-origin', headers:actionHeaders(),
                body:JSON.stringify({client_operation_id:operationId()})
            }));
            if(!state.active || epoch !== state.epoch || revision !== state.mutationRevision){ closePopup(popup); return; }
            const authorizationUrl = safeAuthorizationUrl(data.authorization_url);
            if(!authorizationUrl || !data.flow_id){
                closePopup(popup);
                throw new Error(t('api.laohuRequestFailed', {message:'Invalid login response'}));
            }
            try { popup.opener = null; popup.location.replace(authorizationUrl); }
            catch(_error){ closePopup(popup); throw new Error(t('api.laohuPopupBlocked')); }
            const expiresAt = Date.parse(data.expires_at || '') || (Date.now() + 5 * 60 * 1000);
            state.flow = {id:String(data.flow_id), popup, expiresAt, epoch};
            state.busy = '';
            setMessage(t('api.laohuLoginWaiting'));
            render();
            scheduleFlowPoll();
        } catch(error){
            closePopup(popup);
            if(!state.active || epoch !== state.epoch || revision !== state.mutationRevision) return;
            state.busy = '';
            render();
            setMessage(t('api.laohuRequestFailed', {message:error.message || 'Request failed'}));
        }
    }

    async function switchMode(mode){
        if(mode !== 'account' && mode !== 'manual') return;
        if(mode === 'account' && state.status?.connected !== true){
            setMessage(t('api.laohuLoginRequired'));
            return;
        }
        return await runMutation('mode', '/api/laohu/account/mode', {mode});
    }

    async function refresh(){
        if(!state.active || state.busy) return;
        await runMutation('refresh', '/api/laohu/account/refresh', {});
    }

    async function logout(){
        await runMutation('logout', '/api/laohu/account/logout', {});
    }

    function setActive(active){
        const next = Boolean(active);
        if(state.active === next){
            render();
            return;
        }
        state.active = next;
        state.epoch += 1;
        state.readRevision += 1;
        if(!next){
            pauseReads();
            stopFlowTimer();
            if(state.flowController){
                state.flowController.abort();
                state.flowController = null;
            }
            closePopup(state.flow?.popup);
            state.flow = null;
            state.busy = '';
            render();
            return;
        }
        state.status = null;
        state.message = '';
        render();
        void refreshStatus();
    }

    function bind(){
        if(state.bound) return;
        state.bound = true;
        byId('laohuAccountLogin')?.addEventListener('click', () => { void login(); });
        byId('laohuAccountRefresh')?.addEventListener('click', () => { void refresh(); });
        byId('laohuAccountLogout')?.addEventListener('click', () => { void logout(); });
        byId('laohuAccountUseAccount')?.addEventListener('click', () => { void switchMode('account'); });
        document.addEventListener('visibilitychange', () => {
            if(!state.active) return;
            if(!visible()) pauseReads();
            else if(state.flow) scheduleFlowPoll();
            else void refreshStatus();
        });
        window.addEventListener('pagehide', pauseReads);
        window.addEventListener('pageshow', () => {
            if(state.active && visible()){
                if(state.flow) scheduleFlowPoll();
                else void refreshStatus();
            }
        });
        window.addEventListener('studio-lang-change', render);
    }

    bind();
    window.LaohuAccount = {
        setActive,
        refreshStatus,
        getCredentialDisplay(){ return credentialDisplay(); },
        isBusy(){ return Boolean(state.busy); },
        setProviderRefreshCallback(callback){ state.providerRefresh = typeof callback === 'function' ? callback : null; },
        showMessage(message=''){ setMessage(message); },
        login,
        refresh,
        logout,
        switchMode,
        getStatus(){ return state.status ? {...state.status} : null; }
    };
})();
