/* 项目页只展示原生作品；准备、模型配置与 Agent 接入集中在项目管理页。 */
(() => {
  'use strict';
  const id = new URLSearchParams(location.search).get('id');
  const prefix = `/api/studio/hypit/projects/${encodeURIComponent(id || '')}`;
  const el = name => document.getElementById(name);
  const text = (zh,en) => String(window.StudioI18n?.lang?.() || document.documentElement.lang).startsWith('en') ? en : zh;
  let openedSource = '', failedSource = '', nativeOrigin = '', refreshing = false;
  function currentTheme(fallback) {
    if (fallback === 'dark' || fallback === 'light') return fallback;
    return document.documentElement.classList.contains('studio-theme-dark') || document.body.classList.contains('studio-theme-dark') ? 'dark' : 'light';
  }
  function notifyNativeTheme(event) {
    const frame = el('nativeStudio');
    if (!frame?.contentWindow || !nativeOrigin) return;
    frame.contentWindow.postMessage({type: 'laohu-theme', theme: currentTheme(event?.detail?.theme)}, nativeOrigin);
  }
  function themedStudioUrl(value) {
    const url = new URL(value);
    if (!['localhost','127.0.0.1'].includes(url.hostname) || url.protocol !== 'http:') throw new Error('Invalid Studio URL');
    url.searchParams.set('laohu_theme', currentTheme());
    nativeOrigin = url.origin;
    return url;
  }
  async function api(url,body){
    const response=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
    const data=await response.json();
    if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
    return data;
  }
  function labels(){
    el('back').textContent=text('项目管理','Projects');
    el('refresh').textContent=text('刷新作品','Refresh work');
    el('run').setAttribute('aria-label',text('制作方案','Production plan'));
    el('emptyTitle').textContent=text('尚无制作内容','No creative content yet');
    el('emptyCopy').textContent=text('此项目的制作内容准备好后，会自动显示在这里。','Your project content will appear here when it is ready.');
    el('emptyBack').textContent=text('返回项目管理','Back to projects');
  }
  async function openSource(source){
    if(!source || source===openedSource || source===failedSource)return;
    try{
      const value=await api(prefix+'/studio',{source});
      const url=themedStudioUrl(value.url);
      el('nativeStudio').src=url.href;el('nativeStudio').hidden=false;el('empty').hidden=true;openedSource=source;
    }catch(error){failedSource=source;throw error;}
  }
  async function refresh(){
    if(refreshing)return;
    refreshing=true;
    try{
      if(!id) throw new Error(text('缺少项目 ID','Missing project ID'));
      const [project,files,runtime]=await Promise.all([api(`/api/studio/projects/${encodeURIComponent(id)}?module=hypit`),api(prefix+'/files'),api('/api/studio/hypit/runtime')]);
      el('projectName').textContent=project.project.name;
      const selected=el('run').value;
      const sources=files.files.filter(p=>p.endsWith('.svrun'));
      if(JSON.stringify(sources)!==JSON.stringify([...el('run').options].map(o=>o.value))){
        el('run').replaceChildren(...sources.map(path=>new Option(path.replace(/\.svrun$/,''),path)));
        if(sources.includes(selected))el('run').value=selected;
      }
      el('run').hidden=sources.length<2;
      el('status').textContent=!runtime.ready?text('请在项目管理页安装预览组件。','Install the preview component from project management.'):'';
      if(runtime.ready)await openSource(el('run').value);
    }catch(error){el('status').textContent=error.message;}
    finally{refreshing=false;}
  }
  el('refresh').onclick=()=>{failedSource='';if(openedSource){el('nativeStudio').src=el('nativeStudio').src;}refresh();};
  el('run').onchange=()=>{failedSource='';openSource(el('run').value).catch(error=>{el('status').textContent=error.message;});};
  el('nativeStudio').addEventListener('load', notifyNativeTheme);
  labels();window.addEventListener('studio-lang-change',labels);
  window.addEventListener('studio-theme-change', notifyNativeTheme);
  refresh();const timer=setInterval(()=>{if(!document.hidden)refresh();},5000);
  window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});
})();
