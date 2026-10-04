"""根据项目真实身份生成接入说明；创作技能准备与作品执行互相独立。"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse


def create_connection_router(get_project):
    router = APIRouter(prefix='/api/studio', tags=['Project connection'])

    @router.get('/modules/{module}/preparation.md')
    async def preparation_document(module: str, lang: str = 'zh'):
        if module not in {'canvas', 'hypit'}:
            raise HTTPException(404, '模块不存在')
        text = ('请使用自己的 Agent 创作环境和已有 Skills。画布无需专用 Skill。'
                if module == 'canvas' else
                '请先检查用户 Agent 环境是否已有可用 Hypit Skill，已有则复用，不顺带升级。'
                '缺少时可在用户选择的创作目录运行 npx skills add hypit-ai/hypit --skill hypit --agent codex --copy。'
                '其他 Agent 请使用对应安装目标。只准备 Skill，不安装另一套 Hypit 程序，不启动独立 Studio，'
                '不把 Skill 安装在工作台目录。准备后等待接入当前项目。')
        if lang.startswith('en'):
            text = ('Use your own Agent environment and existing skills. Canvas requires no dedicated skill.'
                    if module == 'canvas' else
                    'Check for an existing usable Hypit skill in the user’s Agent environment first; reuse it without upgrading. '
                    'If missing, run npx skills add hypit-ai/hypit --skill hypit --agent codex --copy in the user-selected creative directory. '
                    'Choose the matching installation target for other Agents. Install only the skill, outside the workbench. '
                    'Do not install another Hypit distribution or open a separate Studio. Then connect to the current project.')
        return PlainTextResponse('# '+('Creative skills preparation' if lang.startswith('en') else '创作技能准备')+'\n\n'+text+'\n', media_type='text/markdown; charset=utf-8')

    @router.get('/projects/{project_id}/connection.md')
    async def connection_document(project_id: str, request: Request, module: str = 'canvas', lang: str = 'zh'):
        if module not in {'canvas', 'hypit'}:
            raise HTTPException(404, '模块不存在')
        project = get_project(project_id, module)
        base = str(request.base_url).rstrip('/')
        common = (f'接入老胡画梦枋（laohu-creative-studio）当前项目。模块：{module}；项目 ID：{project_id}；'
                  f'名称：{project.get("name") or project.get("title") or project_id}。\n'
                  '先读取接口确认项目身份，本次接入不开始生成。创作方法和 Skills 由用户选择。'
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
        else:
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
        if lang.startswith('en'):
            common = (f'Connect to the current Laohu Creative Studio (laohu-creative-studio) project. Module: {module}; project ID: {project_id}; '
                      f'name: {project.get("name") or project.get("title") or project_id}.\n'
                      'Read the project identity before editing. Connecting does not start generation. The user chooses creative methods and skills. '
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
            else:
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
        if module not in {'canvas', 'hypit'}:
            raise HTTPException(404, '模块不存在')
        project = get_project(project_id, module)
        base = str(request.base_url).rstrip('/')
        language = 'en' if lang.startswith('en') else 'zh'
        document = f'{base}/api/studio/projects/{project_id}/connection.md?module={module}&lang={language}'
        name = project.get('name') or project.get('title') or project_id
        text = (f'我使用老胡画梦枋（laohu-creative-studio）的 {module} 模块。当前项目：{name}（ID：{project_id}）。\n'
                f'请先读取对接文档：{document}\n按文档接入这个项目，确认后等待我的创作要求。')
        if language == 'en':
            text = (f'I use the {module} module in Laohu Creative Studio (laohu-creative-studio). Project: {name} (ID: {project_id}).\n'
                    f'Read the integration guide: {document}\nConnect to this project as documented, confirm, and wait for my creative request.')
        return {'project_id':project_id, 'module':module, 'project':project, 'text':text, 'document_url':document}

    @router.get('/modules/{module}/preparation')
    async def preparation(module: str, request: Request, lang: str = 'zh'):
        if module not in {'canvas', 'hypit'}:
            raise HTTPException(404, '模块不存在')
        language='en' if lang.startswith('en') else 'zh'
        document=f"{str(request.base_url).rstrip('/')}/api/studio/modules/{module}/preparation.md?lang={language}"
        text=f'我准备使用老胡画梦枋（laohu-creative-studio）的 {module} 模块。请读取技能准备文档：{document}\n检查我的 Agent 环境，并按文档完成必要准备；已有可用技能则复用。'
        if language=='en':
            text=f'I plan to use the {module} module in Laohu Creative Studio (laohu-creative-studio). Read the skills preparation guide: {document}\nCheck my Agent environment and prepare only what is missing; reuse existing skills.'
        return {'module':module, 'optional':True, 'text':text, 'document_url':document}

    return router
