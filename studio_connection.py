"""根据项目真实身份生成接入说明；创作技能准备与作品执行互相独立。"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from studio_modules import CONNECTION_MODULE_IDS, PREPARATION_MODULE_IDS


def create_connection_router(get_project):
    router = APIRouter(prefix='/api/studio', tags=['Project connection'])

    @router.get('/modules/{module}/preparation.md')
    async def preparation_document(module: str, lang: str = 'zh'):
        if module not in PREPARATION_MODULE_IDS:
            raise HTTPException(404, '模块不存在')
        prep = ('先检查 Agent 是否已有官方老胡造梦技能仓库和 `/laohu` 入口。已有时按 `/laohu-update` 的官方检查流程核对新版；发现更新先说明版本与主要变化并询问，只有用户同意后才更新。'
                '获准更新时使用完整仓库比较与合并流程，保留本地修改，不重置、强制覆盖或清理；用户不同意则沿用当前版本。仓库缺失时才按官方仓库 '
                'https://github.com/LaohuAD/laohu-creative-skills.git 的 README 与 tools/install.py 为所选 Agent 宿主准备全局入口；已有仓库但宿主入口缺失时，先预览再按安装器登记。'
                'Windows 使用 py 或 python 调用安装器；实际权限不足或同名冲突时报告阻碍，不绕过权限。不得把 Skill 安装到工作台工程，也不得假称不存在的能力可用。')
        if module == 'canvas':
            text = ('画布手动编辑节点、参数和素材不要求 Skill。' + prep +
                    '需要专业创作能力时，再从 `/laohu` 发现实际已实现的能力；没有适用能力就说明缺口。完成准备后等待用户选择项目与创作要求。')
        elif module == 'article':
            text = (prep + '只有用户明确要求公众号排版时，才可通过 `/laohu-htmlshow` 发现内部 `laohu-htmlshow-gzh` 能力；三级能力不单独注册，连接文章项目本身不调用 Skill。'
                    '工作台只提供主题目录和示例，不包含 Skill，也不直接发布公众号。完成准备后等待用户选择文章项目与创作要求。')
        elif module == 'music':
            text = (prep + '音乐项目用于管理歌曲标题、歌词、风格、乐谱和共享音频/封面版本；工作台复用共享音乐配置图、模型目录与任务执行器，不打包创作 Skill。'
                    '只有用户明确要求创作时才从 `/laohu` 发现适用能力；连接、读取或保存内容都不触发生成。完成准备后等待用户选择歌曲项目与创作要求。')
        else:
            text = (prep + 'Hypit 项目优先使用工作台提供的原生项目与执行契约；不要求另装一套 Hypit 程序，不启动独立 Studio。是否使用仓库内其他创作能力由用户后续任务决定。完成准备后等待用户选择项目与创作要求。')
        if lang.startswith('en'):
            prep_en = ('Check whether this Agent has the official Laohu creative skills repository and `/laohu` entry. If present, use the official `/laohu-update` check procedure to look for a newer version; report the version and relevant changes and ask before updating. '
                       'Update only with the user’s approval, using the full-repository compare/merge process; preserve local changes and never reset, force-overwrite, or clean them. If the user declines, reuse the current version. '
                       'Install the full repository only when it is missing, following the README and `tools/install.py` at https://github.com/LaohuAD/laohu-creative-skills.git. If the repository exists but this host entry is missing, preview the installer before registering it. '
                       'On Windows invoke the installer with `py` or `python`. Report actual permission or name-collision blockers instead of bypassing them. Do not install Skills inside the workbench or claim an unavailable capability exists. ')
            if module == 'canvas':
                text = ('Manual canvas editing of nodes, parameters, and materials does not require a Skill. ' + prep_en +
                        'For specialist creative work, discover a capability that actually exists through `/laohu`; explain the gap if none applies. After preparation, wait for the user to choose a project and provide the creative request.')
            elif module == 'article':
                text = (prep_en + 'For WeChat typesetting, `/laohu-htmlshow` may discover its internal `laohu-htmlshow-gzh` capability; this is optional and must not be registered separately or invoked merely because the article project was connected. '
                        'The workbench contains only a theme catalog and examples, not a Skill, and does not publish to WeChat. After preparation, wait for the user to choose an article project and provide the creative request.')
            elif module == 'music':
                text = (prep_en + 'Music projects manage song titles, lyrics, style, scores, and shared audio/cover versions. The workbench reuses its shared music settings graph, model catalog, and task executor; it does not bundle a creative Skill. '
                        'Discover a suitable capability through `/laohu` only when the user explicitly asks for creative work. Connecting, reading, or saving never starts generation. After preparation, wait for the user to choose a song project and provide the creative request.')
            else:
                text = (prep_en + 'Hypit projects use the workbench’s native project and execution contracts; do not install another Hypit distribution or launch a separate Studio. Other creative capabilities are chosen later by the user. After preparation, wait for the user to choose a project and provide the creative request.')
        return PlainTextResponse('# '+('Creative skills preparation' if lang.startswith('en') else '创作技能准备')+'\n\n'+text+'\n', media_type='text/markdown; charset=utf-8')

    @router.get('/projects/{project_id}/connection.md')
    async def connection_document(project_id: str, request: Request, module: str = 'canvas', lang: str = 'zh'):
        if module not in CONNECTION_MODULE_IDS:
            raise HTTPException(404, '模块不存在')
        project = get_project(project_id, module)
        base = str(request.base_url).rstrip('/')
        common = (f'接入老胡画梦枋（laohu-creative-studio）当前项目。模块：{module}；项目 ID：{project_id}；'
                  f'名称：{project.get("name") or project.get("title") or project_id}。\n'
                  '按准备文档检查官方仓库版本：发现新版先告知并询问，获准后才按 `/laohu-update` 流程更新并保留本地修改；拒绝则复用当前版本。缺少仓库时才按官方 README 与 tools/install.py 安装完整仓库；不重置、覆盖或清理本地内容，不安装到工作台。'
                  '然后按下面地址关联项目并读取真实能力、存储与执行契约。本次连接只做读取和确认，不自动创作或固定调用某个 Skill；具体 Skill 组合由用户后续选择。'
                  '保存内容与执行模型是独立操作，用户只要求修改时不能生成。'
                  'URL 中的项目 ID 是唯一作用域，不根据浏览器标题或当前选中对象猜测目标。\n')
        if module == 'canvas':
            common += (f'能力和操作：{base}/api/agent/capabilities\n完整说明：{base}/api/agent/guide\n'
                       f'节点目录：{base}/api/agent/canvases/{project_id}/nodes\n'
                       f'节点内容：{base}/api/agent/canvases/{project_id}/nodes/{{node_id}}\n'
                       f'命令：POST {base}/api/agent/canvases/{project_id}/commands，'
                       'JSON 为 {request_id, action, args}。先读取现有节点和修订号再修改；'
                       '同一 request_id 不重复提交不同内容，超时查询原命令。\n')
            common += ('页面只是展示，同项目允许多开或全部关闭，服务端保存与任务继续有效。'
                       '使用 node_number 指定稳定节点编号；不要根据数组位置推算。'
                       f'生成后通过 GET {base}/api/studio/tasks/{{task_id}} 查询实际任务。\n')
        elif module == 'hypit':
            endpoint = f'{base}/api/studio/hypit/projects/{project_id}'
            common += (f'使用工作台已有 Hypit 原生工程，不另建替代工程、另装程序或独立 Studio。\n'
                       f'运行环境检查：{base}/api/studio/hypit/runtime\n'
                       f'文件列表：GET {endpoint}/files；读取文件增加 ?path=相对路径。\n'
                       f'写文件：PUT {endpoint}/files，JSON {{path,content,expected_sha256}}；'
                       '新文件 expected_sha256 为空，旧文件使用读取返回的哈希；409 时重新读取合并。\n'
                       f'操作：POST {endpoint}/operations，JSON {{request_id,operation,source,build_id}}。'
                       'operation 支持 check、plan、build、builds、history、status、cancel、inspect、'
                       'runtime-init、runtime-up、runtime-status；不要把准备与生成混在一起。\n'
                       f'查询原操作：GET {endpoint}/operations/{{request_id}}。\n'
                       f'打开原生预览：POST {endpoint}/studio，JSON {{source:"main.svrun"}}。'
                       '使用当前工作台项目页展示，不额外创建脱离项目管理的制作界面。\n'
                       '原生评论在工程 FEEDBACK.json，保留 Run 对应关系。工程删除不删除素材。'
                       '普通文件读写不能移动结果仓库，也不接受绝对路径。\n')
        elif module == 'article':
            article_url = f'{base}/api/studio/articles/{project_id}'
            common += ('文章卡片、列表与改名复用工作台项目目录。先读取当前服务 OpenAPI 并按实际路由操作；不得猜接口、直接写文件或绕过工作台读取密钥/磁盘。\n'
                       f'模板目录：GET {base}/api/studio/articles/templates，返回 templates 与 catalog_fingerprint；按条目的 id、name、description、preview_url 展示主题和示例。预览示例仅供浏览，不是当前文章正文。用户选择主题时，在文章 PUT 中提交 selected_theme_id 和 expected_revision，并使用模板目录返回的 catalog_fingerprint 填 expected_catalog_fingerprint；只有文章记录中实际保存且有效的 variants 才能复制或导出。缺少有效版本时，仅在用户明确要求排版后才按所选主题生成并保存正文版本。\n'
                       f'文章：GET {article_url}；使用返回的 title、source_markdown、source_sha256、revision、catalog_fingerprint、selected_theme_id、variants、title_variants、selected_title_variant_id、cover_variants、selected_cover_variant_id 与 media_refs。source_sha256 是服务端对当前完整标题和 Markdown 正文计算的指纹，不自行猜算法。\n'
                       '文章有三类独立历史：title_variants 保存标题版本；cover_variants 保存封面图片引用；variants 按主题保存真实 HTML 正文片段。标题/正文来源及各历史均留在同一文章 revision 下。标题版本按备选标题与当前 Markdown 的指纹校验；正文变化会让基于旧正文的标题版本失配。HTML 排版版本绑定完整标题和正文，任一改变都会让旧排版版本过期。旧历史保留但不得冒充当前有效版本；旧封面保留其来源指纹和共享素材身份，不复制媒体文件。工作台的六个 gallery 是带来源说明的预览示例，不是可直接提交的文章，也不包含排版 Skill。\n'
                       f'PUT {article_url} 必须带 expected_revision；可按需提交 title、source_markdown、title_variants、selected_title_variant_id、cover_variants、selected_cover_variant_id、selected_theme_id、variants、media_refs。标题历史项形如 {{id:{{title,source_sha256}}}}，封面历史项引用一个 asset_id 或 result_id，主题版本项形如 {{theme_id:{{body_html,source_sha256?}}}}；需要时用 GET 响应的 catalog_fingerprint 填 expected_catalog_fingerprint。主题项 source_sha256 可省略：原文标题和 Markdown 不变时可使用 GET 的当前 source_sha256；同一次 PUT 原子更新标题/Markdown并提交新 HTML 时不要带旧 source_sha256，让服务端按本次内容计算并绑定，不猜算法或复用旧哈希。服务端校验引用和 HTML；同一历史 ID 不可被另一内容覆盖。409 时重读 current article/revision，合并后再写，绝不以旧 revision 覆盖。\n'
                       '文章页只列出 variants 中真实保存过的主题版本，不读取主题目录来展示空白占位。历史 HTML 可明确标记后预览；只有 valid=true 且 source_sha256 匹配当前文章的版本才能复制或导出。选择历史主题只保存 selected_theme_id，不得覆盖 source_markdown。用户明确要求完整创作时，采用用户指定主题；未指定时默认 moyu-green，并在一次 revision 保护的 PUT 中提交完整创作结果：标题、封面版本及其共享素材引用和选中 ID、完整 Markdown、该主题的真实 HTML 片段与 selected_theme_id。用户明确只要求排版时，仅保存所选主题的真实 HTML 和 selected_theme_id，沿用现有标题、封面与 Markdown；不得因排版而生成或覆盖这些字段。用户只要求修改标题/原文时只写对应字段，不顺带创作排版；接入、读取或查看历史也不触发新内容/版本。按 `/laohu` 查找适用创作能力仅限用户明确要求相关创作时；保留来源内容、段落顺序和真实引用，不伪造素材或结论；预览/复制不等于微信后台验收，也不发布。\n'
                       '实际文章素材必须使用共享素材/结果库和稳定 asset_id/result_id。文章服务会将通过安全校验的 PNG/JPEG/WebP/GIF/AVIF 栅格 data:image 按内容哈希登记为共享图片结果并加入 media_refs；不会自动抓取任意 HTTPS 图片。外链图先通过共享上传/导入获得稳定 ID，再在 media_refs 中保留引用；正文中的字节或 URL 本身不等于素材已入库。\n'
                       f'文章配置图：GET /api/studio/articles/settings-canvas；重置：POST /api/studio/articles/settings-canvas/reset；Agent 命令：POST /api/agent/canvases/article-settings/commands。只有当前 OpenAPI 列出后才调用；配置图 ID 固定为 article-settings，与 Hypit 设置图分开，使用共享画布节点、模型预检、任务与结果收集，不保存第二套生成链。重置只清空该配置图，不删除文章正文、标题/封面/排版历史、共享素材或既有任务/结果。普通配置图 run_node 记录为画布任务；要把生成结果关联到文章，必须使用下面的文章 generations 接口，不能把普通画布运行描述为已自动写入文章历史。\n'
                       f'生成：POST /api/studio/articles/{project_id}/generations，JSON {{purpose,slot,output_node_id,client_operation_id,request,base_revision?}}；purpose 为 cover、illustration 或 knowledge，slot 为 text/image/video/audio/music/voice，cover 必须使用 image。request 承载共享执行器支持的本次提示、参数和输入；base_revision 可用来拒绝过期文章。服务端接受时固定文章 revision/source_sha256 与配置图/任务快照。响应读取 generation.run_id 后，以 GET /api/studio/articles/{project_id}/generations/{{run_id}} 查询原任务。\n'
                       '普通生成成功只会把实际收集到的受管媒体引用追加到 media_refs；cover 图片同时写入 cover_variants，若接受时的文章 revision 和来源指纹仍是当前版本才自动选中。标题和正文 HTML 不会由文本/媒体任务自动改写，标题/正文版本须由用户要求的内容工作经上述 PUT 保存。若文章在任务期间更新，旧生成结果仍留作历史引用，不替换新版本的封面选择。\n'
                       '提交超时或刷新后，若已知 run_id 就查询原 generation；若 POST 响应不确定，使用完全相同的 client_operation_id 和请求查询/恢复同一幂等操作，不自动用新 ID 重发。状态为运行中或可恢复时继续查询原任务。只有确定任务终态失败/取消且用户明确要求重试，才以新 operation ID 发起新任务并保留旧记录。成功任务若仅关联文章失败，查询同一 generation 会重试关联，不会重新提交模型。\n')
        else:
            music_url = f'{base}/api/studio/music/{project_id}'
            common += ('歌曲项目、列表、改名和删除复用共享 StudioProjectStore；音乐内容与项目元数据分开按项目 ID 读取。先读取当前服务 OpenAPI 并按实际路由操作，不得猜接口、直接写文件或绕过工作台读取密钥/磁盘。连接、读取和保存都不自动创作或生成。\n'
                       f'歌曲内容：GET {music_url}；响应包含 revision、source_sha256、title、lyrics、style_prompt、notes、cover_prompt、title_candidates、selected_title_candidate_id、score_refs、reference_audio_refs、audio_variants、cover_variants、selected_audio_variant_id、selected_cover_variant_id。source_versions 保留歌词/风格/说明等来源的不可变快照；source_sha256 是服务端指纹，不自行猜算法。\n'
                       f'保存：PUT {music_url}，必须携带 expected_revision。只提交要修改的歌曲字段；标题候选使用 title_candidates 与 selected_title_candidate_id，乐谱/参考音频用共享 asset_id 或 result_id 作为 score_refs/reference_audio_refs。乐谱格式限 abc、musicxml、midi，服务端会核对共享文件的名称、MIME 与实际内容。外部 Agent 添加现成作品时可提交 audio_refs/cover_refs，它们只接受可解析的共享素材/结果引用；run_id、来源快照和历史状态由服务端生成，不能伪造。409 时重新读取当前版本并合并，不能用旧 revision 覆盖。\n'
                       '每个歌曲/封面结果版本保存生成时的标题、歌词、风格、备注、来源指纹和接受 revision；编辑歌曲源文不会改写已有版本。timed_lyrics 按音频版本 ID 保存，时间单位为秒，行结构为 {start,end?,text}。选中历史版本必须通过独立字段明确保存；生成或接入历史本身不自动替用户选择。媒体只引用共享结果 ID，不复制文件或暴露磁盘路径。\n'
                       f'音乐配置图：GET {base}/api/studio/music/settings-canvas；重置：POST {base}/api/studio/music/settings-canvas/reset；Agent 命令路由：POST {base}/api/agent/canvases/{{canvas_id}}/commands，canvas_id 固定为 music-settings。配置图与歌曲项目内容分开；它复用共享画布节点、模型启用清单、预检、任务和受管结果收集，不创建第二套凭据、模型目录或执行器。重置只清空配置图，不删除歌曲、版本、共享素材或已有任务/结果。\n'
                       f'明确要求生成歌曲时：POST {music_url}/generations，JSON {{purpose:"song",slot:"music",output_node_id,client_operation_id,request,base_revision?}}；封面使用 purpose:"cover" 与 slot:"image"。request 是本次用户输入，歌词、风格、参考音频及其他必要字段按当前共享节点/模型契约显式映射。服务端在接受时固定来源内容与配置图 revision 的私有快照。\n'
                       f'生成列表：GET {music_url}/generations；提交返回 run_id 后查询 GET {music_url}/generations/{{run_id}}。超时或重连后优先查询原 run_id；若 POST 结果不确定，用完全相同的 client_operation_id 和请求恢复，不能自动换 ID 重交。只有确认原任务已终态失败/取消且用户明确要求重试时才使用新 ID。实际受管音频/图片结果关联失败时，重复查询同一任务只重试关联，不重复调用模型。\n')
        if lang.startswith('en'):
            common = (f'Connect to the current Laohu Creative Studio (laohu-creative-studio) project. Module: {module}; project ID: {project_id}; '
                      f'name: {project.get("name") or project.get("title") or project_id}.\n'
                      'Follow the preparation guide to check the official repository version. Report a newer version and ask first; update only with approval through `/laohu-update`, preserving local changes. If declined, reuse the current version. Install the full repository only when missing; never reset, overwrite, or clean local content, and keep Skills outside the workbench. '
                      'Then connect to this project and read its real capability, storage, and execution contracts below. Connecting only reads and confirms; it does not create content or automatically invoke a fixed Skill. The user chooses the Skill combination later. '
                      'Saving and model execution are separate operations; do not generate when asked only to edit. '
                      'The project ID in the URL is the scope, independent of browser tabs or selection.\n')
            if module == 'canvas':
                common += (f'Capabilities: {base}/api/agent/capabilities\nGuide: {base}/api/agent/guide\n'
                           f'Nodes: {base}/api/agent/canvases/{project_id}/nodes\n'
                           f'Node details: {base}/api/agent/canvases/{project_id}/nodes/{{node_id}}\n'
                           f'POST {base}/api/agent/canvases/{project_id}/commands with {{request_id, action, args}}. '
                           'Read the revision before editing; use node_number for stable visible numbers. '
                           'Never reuse a request_id for different content. Query the original command after a timeout. '
                           'Multiple editable tabs are allowed; saving and execution also work with all tabs closed.\n'
                           f'Task status: GET {base}/api/studio/tasks/{{task_id}}.\n')
            elif module == 'hypit':
                endpoint = f'{base}/api/studio/hypit/projects/{project_id}'
                common += ('Use the existing managed Hypit workspace and native Studio. Do not install another distribution or create a replacement workspace.\n'
                           f'Runtime: GET {base}/api/studio/hypit/runtime\n'
                           f'Files: GET {endpoint}/files; add ?path=relative-path to read one file.\n'
                           f'Write: PUT {endpoint}/files with {{path,content,expected_sha256}}. Use an empty hash for a new file; '
                           'use the returned hash for edits. On 409, reread and merge.\n'
                           f'Operations: POST {endpoint}/operations with {{request_id,operation,source,build_id}}. '
                           'Operations: check, plan, build, builds, history (source is output name), status, cancel, inspect, runtime-init, runtime-up, runtime-status. '
                           'Preparation must not imply generation.\n'
                           f'Operation status: GET {endpoint}/operations/{{request_id}}\n'
                           f'Native preview: POST {endpoint}/studio with {{source:"main.svrun"}}. Display in this project page.\n'
                           'Preserve native FEEDBACK.json and its Run references. Project deletion preserves generated media. '
                           'Use relative paths; do not move the managed result repository through file editing.\n')
            elif module == 'article':
                article_url = f'{base}/api/studio/articles/{project_id}'
                common += ('Article cards, listing, and rename use the shared project store. Read the running service OpenAPI first and follow its actual routes; never guess an endpoint, write files directly, or bypass the workbench to read keys or disk.\n'
                           f'Theme catalog: GET {base}/api/studio/articles/templates returns templates and catalog_fingerprint. Use each item’s id, name, description, and preview_url to present the themes and examples. Previews are for browsing, not the current article body. When the user selects a theme, submit selected_theme_id and expected_revision in the article PUT, and pass the catalog_fingerprint from the catalog response as expected_catalog_fingerprint. Only valid variants actually saved in the article may be copied or exported. If no valid version exists, create and save the selected layout only after the user explicitly asks for typesetting.\n'
                           f'Article: GET {article_url}; use its title, source_markdown, source_sha256, revision, catalog_fingerprint, selected_theme_id, variants, title_variants, selected_title_variant_id, cover_variants, selected_cover_variant_id, and media_refs. source_sha256 is the server fingerprint of the full current title and Markdown source; do not guess its algorithm.\n'
                           'The article keeps three separate histories in one revisioned record: title_variants, cover_variants, and actual HTML body variants keyed by theme. A title variant is checked against its own title plus the current Markdown, so other title alternatives can remain valid when only the selected title changes; changing the Markdown makes variants based on the old body mismatch. HTML body variants are bound to the full current title and body, so either changing makes an old layout stale. Preserve old history without presenting a stale body as current. Covers retain their source fingerprint and shared-media identity without copying files. Gallery pages are attributed preview examples, not submit-ready article variants or a bundled layout Skill.\n'
                           f'PUT {article_url} requires expected_revision. Optional fields include title, source_markdown, title_variants, selected_title_variant_id, cover_variants, selected_cover_variant_id, selected_theme_id, variants, media_refs, and expected_catalog_fingerprint (use catalog_fingerprint from GET). A title item is {{id:{{title,source_sha256}}}}, a cover references exactly one asset_id or result_id, and a theme body item is {{theme_id:{{body_html,source_sha256?}}}}. A theme item may omit source_sha256: for unchanged title/Markdown, use the current GET source_sha256 if supplied; when atomically updating title/Markdown and new HTML in one PUT, omit the old hash so the server binds the HTML to the resulting source. Never guess the hash or reuse an old one. The server checks references and HTML; an existing history ID cannot be overwritten with different content. On 409 reread current article/revision, merge changes, then write; never overwrite with an old revision.\n'
                           'The article page lists only theme variants actually saved in the record. A historical HTML body may be previewed when clearly labeled, but only valid=true with a source_sha256 matching the current article may be copied or exported. Selecting a historical theme only saves selected_theme_id; never replace source_markdown. For complete creation explicitly requested by the user, use the user-selected theme or default to moyu-green, then save the complete result in one revision-protected PUT: title, cover variant and its shared asset/result reference plus selected ID, full Markdown source, actual HTML body for that theme, and selected_theme_id. If the user explicitly requests layout only, save only the selected theme’s actual HTML body and selected_theme_id, keeping the existing title, cover, and Markdown unchanged. If the user asks to edit only the title/source, write only the requested fields and do not create a layout. Connecting, reading, or viewing history never creates new content or variants. Use `/laohu` to discover an appropriate writing/layout capability only for explicitly requested work. Preserve source text, paragraph order, and real references. Preview/copy is not WeChat backend verification and does not publish.\n'
                           'Actual article media must use the shared material/result store and stable asset_id/result_id references. The article service registers accepted PNG/JPEG/WebP/GIF/AVIF raster data:image content by hash as a shared image result and adds its ID to media_refs. It does not fetch arbitrary HTTPS images; upload/import them through the shared media interface first, then preserve their stable IDs in media_refs. Embedded bytes or a URL alone do not count as shared-media registration.\n'
                           f'Article settings graph: GET /api/studio/articles/settings-canvas; reset: POST /api/studio/articles/settings-canvas/reset; Agent commands: POST /api/agent/canvases/article-settings/commands. Call them only when listed by the running service OpenAPI. Its ID is article-settings, separate from Hypit settings, and it reuses the shared canvas nodes, model preflight, task, and result collector. Reset clears only this configuration graph; it preserves article source, title/cover/layout histories, shared media, and existing tasks/results. An ordinary config-graph run_node is recorded as a canvas task; use the article generations API below for article association, and do not claim a direct canvas run automatically wrote article history.\n'
                           f'Generation: POST /api/studio/articles/{project_id}/generations with {{purpose,slot,output_node_id,client_operation_id,request,base_revision?}}. purpose is cover, illustration, or knowledge; slot is text/image/video/audio/music/voice, and cover requires image. request carries this task’s prompt, parameters, and inputs for the shared executor. The server captures the accepted article revision/source_sha256 and configuration/task snapshot. Read generation.run_id, then poll GET /api/studio/articles/{project_id}/generations/{{run_id}}.\n'
                           'On ordinary generation success, only collected managed-media references are appended to media_refs. An image cover also enters cover_variants and is selected only while the accepted article revision and source hash remain current. Text generation does not rewrite the title or Markdown/HTML body; title/body variants are saved through PUT after the user requests that work. If the article changes while a task runs, the old output remains a historical media reference and does not replace the current cover selection.\n'
                           'After a timeout or refresh, query the known run_id. If the POST response is uncertain, retry/query with the identical client_operation_id and request so the operation remains idempotent; do not automatically resubmit with a new ID. Continue polling a running or recoverable task. Only after a confirmed failed/cancelled terminal state and an explicit user request may a new operation ID start a retry, preserving the old record. If generation succeeded but article association failed, GET on that same generation retries association without submitting another model task.\n')
            else:
                music_url = f'{base}/api/studio/music/{project_id}'
                common += ('Music project metadata and listing use the shared StudioProjectStore; musical content is loaded separately by project ID. Read the running service OpenAPI first and follow its actual routes. Never guess endpoints, write files directly, or bypass the workbench to read keys or disk. Connecting, reading, and saving do not create content or run a model.\n'
                           f'Song content: GET {music_url}. The response includes revision, source_sha256, title, lyrics, style_prompt, notes, cover_prompt, title_candidates, selected_title_candidate_id, score_refs, reference_audio_refs, audio_variants, cover_variants, selected_audio_variant_id, and selected_cover_variant_id. source_versions preserve immutable lyric/style/source snapshots; source_sha256 is computed by the server, so do not guess its algorithm.\n'
                           f'Save with PUT {music_url} and expected_revision. Send only fields to change. Title candidates use title_candidates and selected_title_candidate_id; scores and reference audio use shared asset_id or result_id references. Score formats are abc, musicxml, or midi, and the server checks the shared file name, MIME, and actual content. An external Agent may attach existing work through audio_refs/cover_refs, but only resolvable shared media/result references are accepted. The server creates run IDs, source snapshots, and history metadata; clients cannot forge them. On 409 reread and merge against the current revision.\n'
                           'Each song/cover version keeps its accepted title, lyrics, style, notes, source hash, and project revision. Editing the current song never rewrites existing versions. Save timed_lyrics by audio variant ID; times are seconds and each row is {start,end?,text}. Select a historical version only through its explicit selection field. Generated or attached history is not selected automatically. Media points to shared result IDs; do not copy files or expose disk paths.\n'
                           f'Music settings graph: GET {base}/api/studio/music/settings-canvas; reset: POST {base}/api/studio/music/settings-canvas/reset; Agent command route: POST {base}/api/agent/canvases/{{canvas_id}}/commands with canvas_id fixed to music-settings. The graph is separate from song content. It reuses shared canvas nodes, enabled model options, preflight, task execution, and managed-result collection; it creates no second credentials, model catalog, or executor. Reset clears only the graph and preserves songs, versions, shared media, and existing tasks/results.\n'
                           f'Only after an explicit generation request, POST {music_url}/generations. A song uses {{purpose:"song",slot:"music",output_node_id,client_operation_id,request,base_revision?}}; a cover uses purpose:"cover" and slot:"image". request carries this task’s inputs and follows the current shared node/model contract. At acceptance the server captures a private snapshot of the song source and settings-graph revision.\n'
                           f'List generations with GET {music_url}/generations; after submit, query the returned run_id with GET {music_url}/generations/{{run_id}}. After timeout or reconnect, query the original run_id. If the POST outcome is uncertain, recover using the exact same client_operation_id and request; never automatically retry with a new ID. Use a new ID only after a confirmed terminal failure/cancellation and an explicit user retry request. If attaching a managed audio/image result fails, querying that same task retries association without resubmitting the model.\n')
        if module == 'hypit':
            models = f'{base}/api/studio/hypit/models'
            if lang.startswith('en'):
                common += (f'Model catalog: GET {models}/capabilities. Unified module model settings: GET {models}/settings and PUT {models}/settings with {{defaults,expected_revision}}. '
                           'After a module setting changes, later runs in every project use the new setting; a submitted task keeps the model captured at submission. On 409 reread the settings and merge. '
                           f'Project binding: GET {models}/projects/{project_id}/binding is a compatibility read of the same module settings; its PUT compatibility route updates that same shared setting with revision protection, not a project snapshot. '
                           'Select one actual model for each supported capability; do not treat a workflow as a model. '
                           'Models must be enabled in API settings and have a confirmed adapter. Never copy keys into the project.\n'
                           'Use <import as="studio" from="@laohu/studio-models@1"/>. Native surfaces: studio:Image, studio:Video, studio:Speech, studio:Audio, studio:Music. '
                           'Each takes id and prompt={textReference}; use text:Value from @hypit/text@1 for text. '
                           'An optional parameters attribute accepts a JSON object for this task. Read the selected model schema before supplying values; legacy module parameters are not inherited. '
                           'Output references are id.image, id.video or id.audio. Image accepts child studio:images; Video accepts '
                           'studio:referenceImage, studio:referenceVideo, studio:referenceAudio, studio:firstFrame, studio:lastFrame; '
                           'Speech/Audio/Music accept studio:referenceAudio. Each child uses source={blobReference}. '
                           'The runtime command installs the real local adapter files before check/plan/build. '
                           'Run check then plan, inspect model settings, and build only when generation is requested. '
                           'Bridge requests may call paid providers; native local rendering does not imply free model inference.\n')
            else:
                common += (f'模型目录：GET {models}/capabilities；统一模块模型设置：GET {models}/settings、PUT {models}/settings，JSON 为 {{defaults,expected_revision}}。'
                           '修改模块设置后，所有项目的后续执行使用新设置；已经提交的任务保持提交时记录的原模型；409 时重新读取并合并。'
                           f'项目 binding：GET {models}/projects/{project_id}/binding 只是读取同一模块设置的兼容入口；其 PUT 兼容入口更新同一份共享设置并做 revision 冲突保护，不再形成项目快照。'
                           '每项已支持的实际能力各选择一个模型，不要把工作流当作模型。模型必须在 API 设置启用且具备确认的适配器；工程中不保存密钥。\n'
                           '工程导入 <import as="studio" from="@laohu/studio-models@1"/>。原生表面为 studio:Image、studio:Video、studio:Speech、studio:Audio、studio:Music；'
                           '均填写 id 和 prompt={文本引用}，文本由 @hypit/text@1 的 text:Value 提供。输出为 id.image、id.video 或 id.audio。'
                           '可选 parameters 属性填写本次任务的 JSON 参数对象；先读取已选模型的参数契约再填写，旧模块参数不再继承。'
                           '图片可用子元素 studio:images；视频可用 studio:referenceImage、studio:referenceVideo、studio:referenceAudio、studio:firstFrame、studio:lastFrame；'
                           '语音/音频/音乐可用 studio:referenceAudio。各子元素使用 source={Blob引用}。'
                           '运行命令在 check/plan/build 前准备真实本地适配文件。先 check、plan 并核对模型设置；用户要求生成时才 build。'
                           '模型桥接可能调用收费供应商，本地渲染不代表模型推理免费。history 的 source 是输出名称，例如 final.video。\n')
        return PlainTextResponse('# '+('Project integration guide' if lang.startswith('en') else '项目对接文档')+'\n\n'+common, media_type='text/markdown; charset=utf-8')

    @router.get('/projects/{project_id}/connection')
    async def connection(project_id: str, request: Request, module: str = 'canvas', lang: str = 'zh'):
        if module not in CONNECTION_MODULE_IDS:
            raise HTTPException(404, '模块不存在')
        project = get_project(project_id, module)
        base = str(request.base_url).rstrip('/')
        language = 'en' if lang.startswith('en') else 'zh'
        document = f'{base}/api/studio/projects/{project_id}/connection.md?module={module}&lang={language}'
        name = project.get('name') or project.get('title') or project_id
        text = (f'我使用老胡画梦枋（laohu-creative-studio）的 {module} 模块。当前项目：{name}（ID：{project_id}）。\n'
                f'请先读取对接文档：{document}\n按文档检查技能仓库版本、准备并关联项目；发现新版先告知并询问，未获准不更新。确认后等待我的创作要求。')
        if language == 'en':
            text = (f'I use the {module} module in Laohu Creative Studio (laohu-creative-studio). Project: {name} (ID: {project_id}).\n'
                    f'Read the integration guide: {document}\nCheck the skills version, prepare and connect as documented; ask before any update. Then confirm and wait for my request.')
        if module == 'article':
            text = (f'我在老胡画梦枋公众号文章模块工作。文章：{name}（ID：{project_id}）。\n'
                    f'先按文档检查技能版本并读取文章契约，关联当前文章：{document}\n'
                    '有新版先告知并询问，未获准不更新；接入只准备和读取，不自动创作、固定调用 Skill 或发布。等待我的具体任务。')
            if language == 'en':
                text = (f'I use Laohu Creative Studio articles. Project: {name} (ID: {project_id}).\n'
                        f'Check the skills version, read the article contract, then connect this article: {document}\n'
                        'Report newer versions and ask before updating. Connection only prepares and reads; do not create content, invoke a fixed Skill, or publish.')
        elif module == 'music':
            text = (f'我在老胡画梦枋音乐模块工作。歌曲项目：{name}（ID：{project_id}）。\n'
                    f'先读取歌曲项目契约并关联当前歌曲：{document}\n'
                    '接入只准备并读取；不要自动创作或生成。只在我明确提出创作要求后，按共享音乐配置图和任务契约执行；等待我的具体任务。')
            if language == 'en':
                text = (f'I use Laohu Creative Studio music. Song project: {name} (ID: {project_id}).\n'
                        f'Read the music project contract and connect this song: {document}\n'
                        'Connection only prepares and reads; do not create content or run generation. Use the shared music settings graph and task contract only after I explicitly request creative work.')
        return {'project_id':project_id, 'module':module, 'project':project, 'text':text, 'document_url':document}

    @router.get('/modules/{module}/preparation')
    async def preparation(module: str, request: Request, lang: str = 'zh'):
        if module not in PREPARATION_MODULE_IDS:
            raise HTTPException(404, '模块不存在')
        language='en' if lang.startswith('en') else 'zh'
        document=f"{str(request.base_url).rstrip('/')}/api/studio/modules/{module}/preparation.md?lang={language}"
        text=f'我准备使用老胡画梦枋（laohu-creative-studio）的 {module} 模块。请读取技能准备文档：{document}\n检查官方仓库版本；发现新版先告知并询问，仅获准后才更新并保留本地改动。缺仓库才安装，完成准备后等待我选择项目与创作要求，不自动创作。'
        if language=='en':
            text=f'I plan to use the {module} module in Laohu Creative Studio (laohu-creative-studio). Read the preparation guide: {document}\nCheck the official version; report newer releases and ask before updating. Update only with approval and preserve local changes; install only if missing, then wait for me to choose a project and provide the creative request.'
        if module == 'article':
            text=f'我准备使用老胡画梦枋的公众号文章模块。请读取技能准备文档：{document}\n先检查官方仓库版本；发现新版先告知并询问，未经同意不更新。缺仓库才安装；后续明确要求排版时再选 `/laohu-htmlshow`，不单独注册三级能力。完成准备后等待我选择文章项目与创作要求。'
            if language == 'en':
                text=f'I plan to use Laohu Creative Studio’s WeChat article module. Read the preparation guide: {document}\nCheck the official version and ask before updating; install only if missing. Choose `/laohu-htmlshow` only for a later layout request; do not register its level-three Skill separately. Then wait for me to choose an article project and provide the creative request.'
        elif module == 'music':
            text=f'我准备使用老胡画梦枋的音乐模块。请读取技能准备文档：{document}\n只在后续明确要求创作时再查找适用能力；不把 Skill 打包进工作台。完成准备后等待我选择歌曲项目与创作要求，不自动生成。'
            if language == 'en':
                text=f'I plan to use Laohu Creative Studio’s music module. Read the preparation guide: {document}\nDiscover a suitable capability only for a later explicit creative request; do not bundle Skills in the workbench. Then wait for me to choose a song project and provide the request. Do not generate automatically.'
        return {'module':module, 'optional':True, 'text':text, 'document_url':document}

    return router
