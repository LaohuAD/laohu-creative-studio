// 画布公开入口。只读取发布目录，存储桶本身保持私有。
const home = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>老胡无限画布 · Infinite Canvas</title><style>body{margin:0;background:#0d121a;color:#edf1f7;font:16px/1.8 system-ui,sans-serif}main{max-width:900px;margin:12vh auto;padding:32px}small{color:#96a6bc;letter-spacing:3px}h1{font-size:clamp(36px,7vw,72px);line-height:1.15;letter-spacing:-2px}p{max-width:640px;color:#b4bfce}nav{display:flex;gap:16px;flex-wrap:wrap;margin:36px 0}a{color:inherit;text-decoration:none;border:1px solid #455266;border-radius:12px;padding:12px 22px}a:first-child{background:#e4ecf8;color:#172131}footer{margin-top:90px;color:#8391a4;font-size:13px}</style><main><small>LAOHU / INFINITE CANVAS</small><h1>把创作的想法，<br>连成一张画布。</h1><p>老胡无限画布，将文本、图片、视频与声音的 AI 创作组织在同一个工作空间。从素材到生成，把你的工作流连接起来。</p><nav><a href="https://github.com/LaohuAD/laohu-creative-studio">查看项目与安装说明</a><a href="/downloads/">下载与更新</a></nav><footer>老胡无限画布 · Infinite Canvas</footer></main></html>`;
export default {
  async fetch(request, env) {
    if (!['GET', 'HEAD'].includes(request.method)) return new Response('Method not allowed', {status:405,headers:{Allow:'GET, HEAD'}});
    const path = new URL(request.url).pathname;
    const html = text => new Response(request.method === 'HEAD' ? null : text, {headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-cache','X-Content-Type-Options':'nosniff'}});
    if (path === '/') return html(home);
    if (path === '/downloads/' || path === '/downloads') return html(home.replace('老胡无限画布，将文本、图片、视频与声音的 AI 创作组织在同一个工作空间。从素材到生成，把你的工作流连接起来。','自动更新服务正在接入。当前请前往 GitHub 项目页，按照安装说明获取程序。'));
    let key = path.slice(1);
    if (path === '/updates/latest.json') key = 'canvas-releases/latest.json';
    if (!/^canvas-releases\/(latest\.json|[A-Za-z0-9._-]+\/(update\.zip|manifest\.json))$/.test(key)) return new Response('Not found', {status:404});
    if (!env.RELEASES) return new Response('Update service unavailable', {status:503,headers:{'Cache-Control':'no-store'}});
    const object = request.method === 'HEAD' ? await env.RELEASES.head(key) : await env.RELEASES.get(key);
    if (!object) return Response.json({error:'release_not_published',message:'尚未发布更新包'}, {status:404,headers:{'Cache-Control':'no-store'}});
    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set('ETag', object.httpEtag);
    headers.set('Content-Type', key.endsWith('.json') ? 'application/json; charset=utf-8' : 'application/zip');
    headers.set('X-Content-Type-Options','nosniff');
    headers.set('Cache-Control',key.endsWith('/latest.json')?'no-store':'public, max-age=31536000, immutable');
    return new Response(request.method === 'HEAD' ? null : object.body, {headers});
  }
};
