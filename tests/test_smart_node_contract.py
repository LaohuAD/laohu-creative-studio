import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "static/js/smart-node-contract.js"


def run_node(source):
    try:
        result = subprocess.run(
            ["node", "-e", source],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "Node fixture failed").strip()
        raise AssertionError(detail[:2000]) from exc
    return json.loads(result.stdout)


def capability_identity_expression(source):
    """连同真实目录投影 helper 一起执行模型身份映射，避免空壳全局变量掩盖依赖。"""
    catalog_start = source.index("function capabilityPickerCatalog")
    catalog_end = source.index("function managementOptionForProfile", catalog_start)
    identity_start = source.index("function capabilitySelectionIdentity")
    identity_end = source.index("function resolveCapabilityFamilySelection", identity_start)
    block = source[catalog_start:catalog_end] + "\n" + source[identity_start:identity_end]
    return json.dumps(block + "\ncapabilitySelectionIdentity")


class SmartNodeContractTests(unittest.TestCase):
    def test_api_model_picker_keeps_reviewed_laohu_image_badges_distinct(self):
        source = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        badge = source[source.index("function providerModelBadge"):source.index("function runningHubAvailabilityBadge")]
        categories = source[source.index("function modelPickerCapabilityCategories"):source.index("function modelListForKind")]
        badge_literal = json.dumps(badge)
        categories_literal = json.dumps(categories)
        data = run_node(f"""
const vm=require('vm');
const reviewed=new Set([
  'laohu-image-g-v2.5-flare','laohu-image-g-v2.5-lowprice','laohu-image-g-v2.5-sunburst',
  'laohu-image-g2-i2i','laohu-image-g2-t2i','laohu-image-g-v2-lowprice'
]);
const badge=vm.runInNewContext('('+{badge_literal}+')',{{LAOHU_GPT_IMAGE_MODEL_IDS:reviewed}});
const capabilityCategories=vm.runInNewContext('('+{categories_literal}+')',{{
  LAOHU_GPT_IMAGE_MODEL_IDS:reviewed,
  modelCapabilityCatalog:{{providers:[]}}
}});
const imageCategories={{}};
for(const model of reviewed) imageCategories[model]=[...capabilityCategories({{id:'ai-money'}},model)];
console.log(JSON.stringify({{
  gpt:badge('laohu-image-g-v2.5-flare',''),
  grok:badge('laohu-image-gk-v2-edit',''),
  unreviewed:badge('laohu-image-g-v9-alpha',''),
  imageCategories
}}));
""")
        self.assertEqual(data["gpt"], "G")
        self.assertEqual(data["grok"], "GK")
        self.assertNotEqual(data["unreviewed"], "G")
        self.assertTrue(all(categories == ["image"] for categories in data["imageCategories"].values()))

    def test_smart_canvas_reads_structured_runninghub_error_message(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        block = source[
            source.index("async function smartResponseErrorMessage"):
            source.index("function smartDropDataTypes")
        ]

        self.assertIn("detail.message", block)
        self.assertIn("detail.message_en", block)
        self.assertIn("capabilityUiText", block)

    def test_queue_progress_only_exposes_trustworthy_positive_positions(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
console.log(JSON.stringify({
  valid:c.normalizeQueueInfo({queue_idx:'3',queue_length:'12',queue_status:'pending'}),
  zero:c.normalizeQueueInfo({queue_idx:0,queue_length:0,queue_status:'pending'}),
  reversed:c.trustedQueueProgress({queue_idx:9,queue_length:4}),
  aliases:c.trustedQueueProgress({queue_position:2,queue_total:8})
}));
"""
        data = run_node(script)

        self.assertEqual(data["valid"], {"queue_idx": 3, "queue_length": 12, "queue_status": "pending"})
        self.assertEqual(data["zero"], {"queue_status": "pending"})
        self.assertIsNone(data["reversed"])
        self.assertEqual(data["aliases"], {"position": 2, "total": 8})

        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        queue_renderer = source[source.index("function jimengQueueText"):source.index("function setNodeJimengPending")]
        self.assertIn("SMART_NODE_CONTRACT.trustedQueueProgress(queueInfo)", queue_renderer)
        self.assertIn("即梦云端处理中", queue_renderer)
        self.assertNotIn("idx != null", queue_renderer)
        self.assertIn("normalizeQueueInfo(data.queue_info || {})", source)

    def test_contract_defines_material_execution_and_result_group_types(self):
        data = run_node(
            "const c=require('./static/js/smart-node-contract.js');"
            "console.log(JSON.stringify(c.NODE_TYPES));"
        )

        self.assertEqual(data["material"], "smart-material")
        self.assertEqual(data["imageGenerator"], "smart-image-generator")
        self.assertEqual(data["videoGenerator"], "smart-video-generator")
        self.assertEqual(data["audioGenerator"], "smart-audio-generator")
        self.assertEqual(data["musicGenerator"], "smart-music-generator")
        self.assertEqual(data["aiApp"], "smart-ai-app")
        self.assertEqual(data["comfyWorkflow"], "smart-comfy-workflow")
        self.assertEqual(data["resultGroup"], "smart-result-group")
        self.assertEqual(data["videoDirector"], "smart-video-director")
        self.assertEqual(data["minimaxDirector"], "smart-minimax-director")

    def test_materials_connect_to_both_director_entries(self):
        data = run_node("""
const c=require('./static/js/smart-node-contract.js');
const material={id:'asset',type:c.NODE_TYPES.material,images:[{kind:'video',url:'/api/materials/asset'}]};
console.log(JSON.stringify({
  generic:c.canConnectNodes(material,{id:'generic',type:c.NODE_TYPES.videoDirector}),
  minimax:c.canConnectNodes(material,{id:'minimax',type:c.NODE_TYPES.minimaxDirector}),
  legacy:c.canConnectNodes(material,{id:'legacy',type:'smart-minimax'})
}));
""")

        self.assertTrue(data["generic"])
        self.assertTrue(data["minimax"])
        self.assertTrue(data["legacy"])

    def test_retired_directors_are_not_new_canvas_entry_points(self):
        html = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        self.assertNotIn('data-create-type="video-director"', html)
        self.assertNotIn('data-create-type="minimax-director"', html)
        self.assertNotIn("else if(type === 'video-director')", source)
        self.assertNotIn("else if(type === 'minimax-director')", source)
        # 历史数据是否保留由 test_workbench_migration 的真实迁移案例验收。

    def test_director_reuses_video_capabilities_and_exports_independent_clips(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        runner = source[source.index("async function runMinimaxNode"):source.index("async function exportMinimaxTimeline")]
        exporter = source[source.index("async function exportMinimaxTimeline"):source.index("function smartPendingTasks")]

        self.assertIn("capabilityModelsForProvider(provider.id, 'video_generation'", source)
        self.assertIn("await smartDirectorMaterializeTimelineRefs(node, activeSegment)", runner)
        self.assertIn("runApiVideoGeneration", runner)
        self.assertIn("runPersonalizedDirectorClip(node, activeSegment)", runner)
        self.assertIn("activeSegment.running = true", runner)
        self.assertNotIn("node.running = true", runner)
        self.assertIn("renderCapabilityParameterBundleForSource(profile, smartDirectorCapabilityParameterSource", source)
        generic_settings = source[source.index("function smartDirectorGenericRunSettings"):source.index("function smartMinimaxRunSnapshot")]
        self.assertIn("SMART_DIRECTOR_CORE.isolatedVideoRunSettings", generic_settings)
        self.assertNotIn("smartSettingsForNode", generic_settings)
        director_renderer = source[source.index("function smartMinimaxBodyHtml"):source.index("function nodeBodyHtml")]
        self.assertIn("directorParameterHtml", director_renderer)
        self.assertNotIn('${isMiniMaxDirectorNode(node) ? \'\' : \'\'}<label><span>Duration</span>', director_renderer)
        self.assertIn("/api/smart-canvas/director-export", exporter)
        self.assertNotIn("/api/smart-canvas/minimax-export", exporter)

    def test_director_timeline_uses_shared_scroll_viewport_and_core_mutations(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn('data-director-timeline-scroll="1"', source)
        self.assertIn("SMART_DIRECTOR_CORE.moveOrdinaryClip", source)
        self.assertIn("SMART_DIRECTOR_CORE.resizeOrdinaryClip", source)
        self.assertIn("timelineScrollMs", source)
        self.assertIn("smartDirectorReplaceTimelineClips", source)
        self.assertIn("smartDirectorDurationConstraint", source)
        self.assertIn("smartDirectorZoomAtPointer", source)
        self.assertIn("smartDirectorScrollTimelineByWheel", source)
        delete_handlers = source[
            source.index("el.querySelectorAll('[data-minimax-delete-segment]')"):
            source.index("el.querySelectorAll('[data-minimax-number]')")
        ]
        self.assertNotIn("smartMinimaxCompactSegments(node);", delete_handlers)
        self.assertIn(".director-timeline-scroll", css)
        self.assertIn("if(renderedSegmentId !== seg?.id)", source)
        refs = source[source.index("function smartMinimaxRefsForKind"):source.index("function smartMinimaxAllRefs")]
        self.assertIn("legacyFallback", refs)
        self.assertNotIn("(clipRefs.length || timelineRefs.length) ? local", refs)

    def test_director_add_clip_uses_fresh_core_state_and_selects_it(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        handler = source[
            source.index("el.querySelectorAll('[data-minimax-add-segment]')"):
            source.index("el.querySelectorAll('[data-minimax-add-connection]')")
        ]

        self.assertIn("SMART_DIRECTOR_CORE.appendFreshOrdinaryClip", handler)
        self.assertIn("node.selectedSegmentId = director.selectedClipId", handler)
        self.assertNotIn("current?.aspectRatio", handler)
        self.assertNotIn("current?.megapixels", handler)

    def test_director_toolbar_and_workspace_follow_approved_layout(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        toolbar = source[
            source.index('<div class="minimax-wb-toolbar">'):
            source.index('<div class="minimax-wb-body"')
        ]

        self.assertIn("data-minimax-add-segment", toolbar)
        self.assertIn("data-minimax-add-connection", toolbar)
        self.assertIn("data-director-shortcuts", toolbar)
        self.assertIn("下载当前 Clip", toolbar)
        self.assertIn("Download selected Clip", toolbar)
        self.assertNotIn("导出当前 Clip", toolbar)
        self.assertNotIn("Export selected Clip", toolbar)
        timeline = source[source.index('<div class="minimax-edit-timeline"'):source.index('<div class="minimax-current-panel"')]
        self.assertNotIn("director-add-actions", timeline)
        self.assertIn("director-clip-assets-column", source)
        self.assertIn("director-prompt-column", source)
        self.assertIn("director-settings-column", source)
        self.assertIn(".director-clip-workspace", css)
        self.assertIn(".director-shortcuts-popover", css)

    def test_personalized_director_uses_local_workflows_or_runninghub_apps_only(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        adapter = source[
            source.index("function smartDirectorPersonalizedAdapter"):
            source.index("function smartDirectorPersonalizedSettingHtml")
        ]
        renderer = source[
            source.index("function smartDirectorPersonalizedSettingHtml"):
            source.index("function smartMinimaxBodyHtml")
        ]
        runner = source[
            source.index("async function runPersonalizedDirectorClip"):
            source.index("async function runMinimaxNode")
        ]

        self.assertIn("runningHubEntries('app', {rhRegion:region})", adapter)
        self.assertIn("adapter.region", adapter)
        self.assertIn("comfyWorkflows", adapter)
        self.assertNotIn("runningHubEntries('workflow')", adapter)
        self.assertIn("key:'engine'", renderer)
        self.assertIn("key:'source'", renderer)
        self.assertIn("runRunningHubGeneration", runner)
        self.assertIn("runQueuedSmartComfyGenerate", runner)
        self.assertNotIn("runLegacyRunningHubWorkflowGeneration", runner)

    def test_personalized_director_merges_media_into_schema_ordered_clip_settings(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        renderer = source[
            source.index("function smartDirectorPersonalizedSettingHtml"):
            source.index("function smartMinimaxBodyHtml")
        ]
        choice = source[
            source.index("function smartDirectorPersonalizedChoiceHtml"):
            source.index("function smartDirectorPersonalizedFieldHtml")
        ]
        workspace = source[
            source.index('<div class="director-clip-workspace'):
            source.index('</div>\n                </div>\n            </div>\n        </div>\n    </div>`;', source.index('<div class="director-clip-workspace'))
        ]

        self.assertIn("smartDirectorPersonalizedSchemaFieldHtml", renderer)
        self.assertIn("adapterState.fields.map", renderer)
        self.assertIn("smartDirectorPersonalizedChoiceHtml", renderer)
        self.assertIn("data-director-personalized-choice", choice)
        self.assertIn("is-personalized", workspace)
        self.assertIn("isMiniMaxDirectorNode(node) ? ''", workspace)
        self.assertIn(".director-clip-workspace.is-personalized", css)

    def test_director_setting_controls_use_compact_director_specific_typography(self):
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn(".director-choice-option {", css)
        self.assertIn("font-size:9.5px", css)
        self.assertIn(".director-settings-column .director-choice-popover", css)
        self.assertIn(".director-settings-column .director-choice-trigger", css)
        self.assertIn(".minimax-workbench .director-choice-popover {", css)
        self.assertIn("background:#202328", css)

    def test_ordinary_clip_trim_handles_keep_a_wide_hit_target_inside_the_clip(self):
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn(".director-ordinary-clip .minimax-trim", css)
        self.assertIn("width:10px", css)
        self.assertIn(".director-ordinary-clip .minimax-trim-right", css)
        self.assertIn("right:0", css)

    def test_personalized_director_keeps_non_prompt_text_fields_as_schema_parameters(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        schema_renderer = source[
            source.index("function smartDirectorPersonalizedSchemaFieldHtml"):
            source.index("function smartDirectorPersonalizedSettingHtml")
        ]
        body = source[
            source.index("const personalizedMediaFields"):
            source.index("let personalizedBoundByField")
        ]

        self.assertIn("rhFieldRole(field) === 'prompt'", schema_renderer)
        self.assertIn("['image','video','audio'].includes", body)
        self.assertNotIn("['text','image','video','audio'].includes", body)

    def test_runninghub_upload_source_covers_all_project_media_routes(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
console.log(JSON.stringify({
  material:c.runningHubUploadSource('/api/materials/mat-image'),
  result:c.runningHubUploadSource('/api/results/res-video'),
  storage:c.runningHubUploadSource('/api/storage-files/upload/audio.wav'),
  assets:c.runningHubUploadSource('/assets/input/image.png'),
  output:c.runningHubUploadSource('/output/generated/video.mp4'),
  preview:c.runningHubUploadSource('/api/media-preview?url=%2Fapi%2Fresults%2Fres-audio'),
  remote:c.runningHubUploadSource('https://example.com/image.png'),
  uploaded:c.runningHubUploadSource('pasted/uploaded.png'),
  unsupported:c.runningHubUploadSource('/api/canvas/preview')
}));
"""
        data = run_node(script)

        self.assertEqual(data["material"], "/api/materials/mat-image")
        self.assertEqual(data["result"], "/api/results/res-video")
        self.assertEqual(data["storage"], "/api/storage-files/upload/audio.wav")
        self.assertEqual(data["assets"], "/assets/input/image.png")
        self.assertEqual(data["output"], "/output/generated/video.mp4")
        self.assertEqual(data["preview"], "/api/results/res-audio")
        self.assertEqual(data["remote"], "https://example.com/image.png")
        self.assertEqual(data["uploaded"], "")
        self.assertEqual(data["unsupported"], "")

        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        self.assertIn("SMART_NODE_CONTRACT.runningHubUploadSource(text)", source)
        self.assertNotIn("!text.startsWith('/output/') && !text.startsWith('/assets/')", source)

    def test_runninghub_field_roles_only_use_explicit_official_schema(self):
        data = run_node("""
const c=require('./static/js/smart-node-contract.js');
console.log(JSON.stringify({
  start:c.runningHubTextFieldRole({fieldName:'text',fieldType:'STRING',label:'音频开始时间'}),
  end:c.runningHubTextFieldRole({fieldName:'text',fieldType:'STRING',label:'音频结束时间'}),
  labelOnly:c.runningHubTextFieldRole({fieldName:'text',fieldType:'STRING',label:'提示词文本'}),
  explicit:c.runningHubTextFieldRole({fieldName:'text',fieldType:'STRING',label:'普通文本',inputRole:'prompt'}),
  parsed:c.parseRunningHubOfficialFieldData('["STRING", {"role":"negative_prompt"}]').role
}));
""")

        self.assertEqual(data["start"], "text")
        self.assertEqual(data["end"], "text")
        self.assertEqual(data["labelOnly"], "text")
        self.assertEqual(data["explicit"], "prompt")
        self.assertEqual(data["parsed"], "negative_prompt")

        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        self.assertIn("return SMART_NODE_CONTRACT.runningHubTextFieldRole(field)", source)
        self.assertNotIn("media?.prompt || rhDefaultValue(field)", source)

    def test_runninghub_field_types_and_numeric_values_are_schema_driven(self):
        data = run_node("""
const c=require('./static/js/smart-node-contract.js');
const values={
  namedImage:c.runningHubFieldMediaKind({fieldName:'reference_image',label:'参考图片',fieldType:'STRING'}),
  officialImage:c.runningHubFieldMediaKind({fieldName:'value',label:'普通字段',fieldType:'IMAGE'}),
  float:c.runningHubCoerceFieldValue({nodeId:'105',fieldName:'megapixels',fieldType:'FLOAT',label:'一采参数 分辨率'},'0.6')
};
try{
  c.runningHubCoerceFieldValue({nodeId:'105',fieldName:'megapixels',fieldType:'FLOAT',label:'一采参数 分辨率'},'这个女人在录音棚里面唱歌');
}catch(error){ values.error=error.message; }
console.log(JSON.stringify(values));
""")

        self.assertEqual(data["namedImage"], "text")
        self.assertEqual(data["officialImage"], "image")
        self.assertEqual(data["float"], 0.6)
        self.assertIn("105::megapixels", data["error"])
        self.assertIn("要求数字", data["error"])

    def test_angle_control_is_a_tool_with_image_input_and_text_output(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const material={id:'image-1',type:c.NODE_TYPES.material,images:[{kind:'image',url:'/api/assets/image-1'}]};
const angle={id:'angle-1',type:c.NODE_TYPES.angleControl};
const text={id:'text-1',type:c.NODE_TYPES.material,images:[{kind:'text',text:'prompt'}]};
console.log(JSON.stringify({
  angleType:c.NODE_TYPES.angleControl,
  isTool:c.isToolNode(angle),
  isExecution:c.isExecutionNode(angle),
  imageToAngle:c.canConnectNodes(material, angle),
  angleToText:c.canConnectNodes(angle, text),
  kind:c.connectionKindForNodes(angle, text),
  prompt:c.anglePromptFor({horizontalAngle:45,verticalAngle:30,zoom:5}),
  reset:c.anglePromptFor({horizontalAngle:0,verticalAngle:0,zoom:5})
}));
"""
        data = run_node(script)

        self.assertEqual(data["angleType"], "smart-angle-control")
        self.assertTrue(data["isTool"])
        self.assertFalse(data["isExecution"])
        self.assertTrue(data["imageToAngle"])
        self.assertTrue(data["angleToText"])
        self.assertEqual(data["kind"], "result")
        self.assertEqual(data["prompt"], "<sks> front-right quarter view elevated shot medium shot")
        self.assertEqual(data["reset"], "<sks> front view eye-level shot medium shot")

    def test_text_generator_preserves_resized_creation_preview(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const node=c.normalizeExecutionNode({type:c.NODE_TYPES.textGenerator,w:900,h:700,runSettings:{provider_id:'codex-cli'}});
console.log(JSON.stringify({types:c.NODE_TYPES,node,isExecution:c.isExecutionNode(node),title:c.titleForType(node.type),output:c.outputKindForType(node.type)}));
"""
        data = run_node(script)

        self.assertEqual(data["types"]["textGenerator"], "smart-text-generator")
        self.assertTrue(data["isExecution"])
        self.assertEqual((data["node"]["w"], data["node"]["h"]), (900, 700))
        self.assertEqual(data["title"], "文本生成")
        self.assertEqual(data["output"], "text")

    def test_text_material_factory_preserves_empty_editable_text(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
console.log(JSON.stringify({
  empty:c.createTextMaterial({id:'material-empty',name:'未命名文本.md',text:''}),
  pasted:c.createTextMaterial({id:'material-paste',name:'剪贴板文本.md',text:'# 标题\\n正文'})
}));
"""
        data = run_node(script)

        self.assertEqual(data["empty"]["type"], "smart-material")
        self.assertEqual(data["empty"]["images"][0]["kind"], "text")
        self.assertEqual(data["empty"]["images"][0]["text"], "")
        self.assertEqual(data["pasted"]["images"][0]["text"], "# 标题\n正文")

    def test_canvas_material_menu_paste_and_text_files_share_text_material_path(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        menu = source[source.index("function createNodeFromMenu"):source.index("shell.addEventListener('mousedown'", source.index("function createNodeFromMenu"))]
        paste_start = source.index("window.addEventListener('paste'")
        paste = source[paste_start:source.index("window.addEventListener('keydown'", paste_start)]

        self.assertIn("createTextMaterialNodeAt", menu)
        self.assertNotIn("pickMediaForSmartNode(created.id)", menu)
        self.assertIn("clipboardData?.getData('text/plain')", paste)
        self.assertIn("createTextMaterialNodeAt", paste)

    def test_recent_canvas_node_copy_beats_stale_external_image_and_never_replaces_selection(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        paste_start = source.index("window.addEventListener('paste'")
        paste = source[paste_start:source.index("window.addEventListener('copy'", paste_start)]
        node_intent = paste.index("intent?.kind === 'nodes'")
        external_image = paste.index("const externalImageItems")
        self.assertLess(node_intent, external_image)
        self.assertIn("pasteNodes();", paste)
        self.assertIn("handleFiles(externalImageItems, '')", paste)
        self.assertIn("handleFiles(files, '')", paste)
        self.assertNotIn("handleFiles(externalImageItems, selectedId)", paste)

    def test_canvas_node_copy_updates_shared_recent_intent(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        copy = source[source.index("function copySelectedNodes"):source.index("function selectedClipboardMedia")]
        self.assertIn("saveSmartClipboardIntent({kind:'nodes'", copy)
        self.assertNotIn("navigator.clipboard.write", copy)
        self.assertIn("Do not overwrite the OS media", copy)
        self.assertIn("isSupportedTextFile", source)
        self.assertIn("await file.text()", source)

    def test_text_generator_uses_execution_card_and_unified_composer(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        menu = source[source.index("function createNodeFromMenu"):source.index("shell.addEventListener('mousedown'", source.index("function createNodeFromMenu"))]
        body = source[source.index("function nodeBodyHtml"):source.index("function smartExecutionNodeMeta")]

        self.assertIn("SMART_NODE_TYPES.textGenerator", menu)
        self.assertNotIn("createPromptNode", menu)
        self.assertIn("if(node.type === 'smart-prompt') return promptNodeBodyHtml(node)", body)
        self.assertIn("fusedCreationBodyHtml(node, layout)", body)
        self.assertLess(body.index("promptNodeBodyHtml(node)"), body.index("isSmartExecutionNode(node)"))
        self.assertIn("async function runSelectedNode", source)
        self.assertIn("runPromptLLMNode(node.id)", source)
        self.assertIn("function renderTextGenerationParams", source)
        self.assertIn("chatProviderOptions", source)
        self.assertIn("chatModelOptions", source)
        self.assertIn("data-text-system-prompt", source)
        self.assertIn("data-text-system-template", source)

    def test_text_system_prompt_uses_an_inset_focus_ring_and_compact_template_icon(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        section = source[source.index('<div class="text-generation-system-row">'):source.index("</div>` : ''}", source.index('<div class="text-generation-system-row">'))]

        self.assertIn('class="text-generation-template-btn"', section)
        self.assertIn('data-text-system-template', section)
        self.assertIn('aria-label="${escapeAttr(tr(\'smart.systemTemplate\'))}"', section)
        self.assertNotIn('<span>${escapeHtml(tr(\'smart.template\'))}</span>', section)
        self.assertIn(".text-generation-system-row { grid-column:1 / -1; position:relative; overflow:visible;", css)
        self.assertIn("padding:8px 42px 8px 10px", css)
        self.assertIn(".dynamic-params .text-generation-system-row textarea:focus", css)
        self.assertIn("box-shadow:inset 0 0 0 1px var(--strong)", css)
        self.assertIn(".text-generation-template-btn { position:absolute; top:8px; right:8px; width:28px; height:28px;", css)

    def test_execution_model_picker_uses_compatible_providers_without_silently_replacing_saved_choice(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        image = source[source.index("function renderApiParams"):source.index("function renderJimengUpscaleControl")]
        video = source[source.index("function renderApiVideoParams"):source.index("function renderApiAudioParams")]
        audio = source[source.index("function renderApiAudioParams"):source.index("function renderVolcengineParams")]

        self.assertIn("renderCapabilityModelPicker(selection, descriptor)", image)
        self.assertIn("renderCapabilityModelPicker(selection, descriptor)", video)
        self.assertIn("renderCapabilityModelPicker(selection, descriptor)", audio)
        self.assertIn("region: data.region || ''", source)
        self.assertIn("data-capability-picker-option", source)
        self.assertIn("if(!settings.provider_id)", image)
        self.assertNotIn("!providers.some", image)
        self.assertIn("if(!settings.videoProvider)", video)
        self.assertNotIn("!providers.some", video)
        self.assertIn("if(!settings.audioProvider)", audio)
        self.assertNotIn("!providers.some", audio)
        self.assertIn("configuredCapabilityModelIds(providerId, nodeType, region)", source)
        self.assertIn("enabledIds.has(String(variant.model_id", source)

    def test_generation_error_toast_is_centered_and_opens_logs(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        i18n = (ROOT / "static/js/i18n/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("function errorToast", source)
        self.assertIn("addSmartCanvasNoticeLog(message", source[source.index("function errorToast"):source.index("let generationCompleteSoundAt")])
        self.assertIn("function addSmartCanvasNoticeLog", source)
        self.assertIn("Date.now() - Number(log?.createdAt || 0) < 5000", source)
        self.assertIn("openSmartCanvasLog()", source[source.index("function toast"):source.index("let generationCompleteSoundAt")])
        self.assertIn("toast-action", source)
        self.assertIn("errorToast((e.message || tr('smart.errRunFailed')).slice(0, 160))", source)
        self.assertIn("position:fixed", css[css.index(".toast {"):css.index(".selection-box")])
        self.assertIn("left:50%", css[css.index(".toast {"):css.index(".selection-box")])
        self.assertIn(".toast-action", css)
        self.assertIn('"canvas.openLogs"', i18n)

    def test_strict_model_parameters_are_rendered_from_one_schema_source(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        renderer = source[source.index("function renderCapabilityParameters"):source.index("const CAPABILITY_PARAMETER_UNSET")]

        self.assertIn("renderCapabilityParameterBundle(profile)", renderer)
        self.assertNotIn("renderVideoResolutionControl", renderer)
        self.assertNotIn("renderAudioSpeakerControl", renderer)
        self.assertNotIn("renderCountVisualControl", renderer)
        self.assertIn("if(!subject){", source)
        self.assertIn("dynamicParams.hidden = true;", source)
        self.assertIn(".composer:not(.ai-app-composer) .dynamic-params", css)

    def test_execution_parameters_use_compact_presets_help_and_cost_panel(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        renderer = source[
            source.index("function renderCapabilityParameterEditor"):
            source.index("function volcengineProvider")
        ]

        self.assertIn("capability-option-grid", renderer)
        self.assertIn("data-capability-option", renderer)
        self.assertIn('type="range"', renderer)
        self.assertIn('type="number"', renderer)
        self.assertIn("function renderExecutionConfigPanel", source)
        self.assertIn("function renderCapabilityModelHelp", source)
        self.assertIn("function renderCapabilityCostEstimate", source)
        self.assertIn("const SUNO_ACTION_INFO", source)
        self.assertIn("suno-generation", source)
        self.assertIn("歌曲续写", source)
        self.assertIn("renderExecutionConfigPanel", source[source.index("function renderApiParams"):source.index("function renderVolcengineParams")])
        self.assertIn(".execution-config-panel", css)
        self.assertIn(".capability-option-grid", css)
        self.assertIn(".capability-cost-estimate", css)

    def test_price_comparison_uses_official_records_and_explicit_billing_states(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        html = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")
        pricing = json.loads((ROOT / "data/model_capabilities/pricing.json").read_text(encoding="utf-8"))

        self.assertIn('data-lucide="circle-dollar-sign"', html)
        self.assertIn("flex:0 0 16px", css)
        self.assertIn("modelPricingCatalog.provider_defaults", source)
        self.assertIn("modelPricingCatalog.rules", source)
        self.assertIn('data-provider-label=', source)
        self.assertIn("smartPriceComparisonPanel?.classList.contains('open')", source)
        self.assertIn("official public price", source)
        self.assertIn("unpublished", source)
        self.assertEqual(pricing["schema_version"], 2)
        self.assertIn("runninghub", pricing["provider_defaults"])
        self.assertIn("ai-money", pricing["provider_defaults"])
        self.assertTrue(any(rule.get("record", {}).get("status") == "formula" for rule in pricing["rules"]))
        image_prices = pricing["image_reference_prices"]
        self.assertEqual(len(image_prices["rows"]), 9)
        self.assertEqual(image_prices["rows"][0]["text_to_image"]["label_zh"], "≈¥0.05")
        self.assertEqual(image_prices["rows"][1]["image_to_image"]["label_zh"], "≈¥0.59")
        self.assertEqual(image_prices["rows"][-1]["image_to_image"]["status"], "unsupported")
        self.assertIn("renderImageReferencePriceTable", source)
        self.assertIn("Text-to-image", source)
        self.assertIn("Image-to-image", source)

    def test_concrete_parameter_values_and_manual_creation_are_independent_from_agent(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        defaults = source[source.index("const CAPABILITY_PARAMETER_UNSET"):source.index("function setCapabilityParameter")]
        schema_default = source[source.index("function capabilitySchemaDefaultIsValid"):source.index("\nfunction capabilityDefaultsForReset")]
        memory = source[source.index("const manualNodeSettingsFingerprints"):source.index("function smartSettingsModeKey")]
        descriptor = source[source.index("function executionSelectionDescriptor"):source.index("function executionSelectionInputState")]
        create = source[source.index("function createExecutionNode"):source.index("function resultIdsForMediaItems")]
        data = run_node("""
const assert=require('node:assert/strict');
const SMART_NODE_CONTRACT=require('./static/js/smart-node-contract.js');
const CanvasCreation=require('./static/js/canvas-creation.js');
// 用真实模型契约核心验证必填默认值，不能用空对象掩盖必填参数护栏。
global.window={};
global.window.ModelConfigCore=require('./static/js/model-config-core.js');
const SMART_NODE_TYPES=SMART_NODE_CONTRACT.NODE_TYPES;
const cloneSmartSettings=s=>JSON.parse(JSON.stringify(s||{}));
let settings={}, recentSmartSettingsByMode={}, selectedId='', nodes=[];
const canvasDefaultSmartSettings={engine:'api',provider_id:'platform',model:'initial',count:1};
const initialSmartSettings=canvasDefaultSmartSettings;
const saveRecentSmartSettings=()=>{};
const capabilityRegionForProvider=()=>'';
const capabilityProfileFor=()=>null;
const sanitizeSmartApiSelection=()=>{};
const ensureExecutionSelectionDefaults=(s,n,opts)=>{if(opts.resetSelection)s.model='initial';};
const uid=()=>String(nodes.length),pushUndo=()=>{},render=()=>{},scheduleSave=()=>{};
""" + schema_default + defaults + descriptor + memory + create + """
const profile={model_id:'m',parameters:{
 resolution:{level:'optional',type:'string',options:['1K','2K']},
 audio:{level:'optional',type:'boolean',default:false},
 strength:{level:'optional',type:'number',default:0,min:0,max:1},
 note:{level:'optional',type:'text'},
 task_id:{level:'required',type:'text'}
}};
const values=capabilityParameterSubmissionValues(profile,{capabilityParameters:{m:{resolution:CAPABILITY_PARAMETER_UNSET}}});
assert.deepEqual(values,{audio:false,strength:0});
const image={id:'old-image',type:SMART_NODE_TYPES.imageGenerator};
const original={engine:'api',provider_id:'chosen-platform',model:'chosen',imageFamilyId:'family',count:3,
 capabilityParameters:{chosen:{resolution:'2K',audio:false,strength:0,prompt:'do not copy',task_id:'old-run'}},
 promptDraftText:'do not copy',videoTempShLinks:[{url:'/old'}]};
rememberManualExecutionSettings(image,original);
rememberManualExecutionSettings({id:'old-video',type:SMART_NODE_TYPES.videoGenerator},{engine:'api',videoProvider:'vp',videoModel:'vm',count:1});
const manual=createExecutionNode(10,20,image.type,{inheritManual:true});
assert.equal(manual.runSettings.model,'chosen');
assert.equal(manual.runSettings.count,3);
assert.equal(manual.runSettings.capabilityParameters.chosen.strength,0);
assert.equal(manual.runSettings.capabilityParameters.chosen.audio,false);
assert.equal(manual.runSettings.capabilityParameters.chosen.prompt,undefined);
assert.equal(manual.runSettings.capabilityParameters.chosen.task_id,undefined);
assert.equal(manual.promptDraftText,'');
manual.runSettings.capabilityParameters.chosen.resolution='4K';
assert.equal(manualExecutionSettingsForType(image.type).capabilityParameters.chosen.resolution,'2K');
const agent=createExecutionNode(30,40,image.type,{select:false});
assert.equal(agent.runSettings.model,'initial');
assert.equal(agent.runSettings.count,1);
console.log(JSON.stringify({ok:true}));
""")
        self.assertTrue(data["ok"])

    def test_execution_parameter_controls_are_stable_and_optional_values_can_be_omitted(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        renderer = source[
            source.index("function renderCapabilityParameterEditor"):
            source.index("function volcengineProvider")
        ]

        self.assertIn("CAPABILITY_PARAMETER_UNSET", source)
        self.assertIn("function capabilityParameterControlKind", source)
        self.assertIn("if(capabilityParameterSemantic(key, spec) === 'duration') return 'select'", source)
        self.assertIn("function capabilityParameterSubmissionValues", source)
        self.assertIn("renderCapabilityUnsetChoice", renderer)
        self.assertIn("data-capability-unset", source)
        self.assertNotIn("spec.options.length <= 12", renderer)
        self.assertIn("capabilityParameterSubmissionValues(textCapabilitySelection.profile, runSettings)", source)

    def test_required_parameters_do_not_invent_defaults(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        defaults = source[source.index("function capabilityParameterDefaultValue"):source.index("function capabilityProfileHasParameterDefaults")]
        editor = source[source.index("function renderCapabilityParameterEditor"):source.index("function renderCapabilitySettingsControl")]
        self.assertNotIn("options[0]", defaults)
        self.assertNotIn("Number(spec.min)", defaults)
        self.assertIn("保持未设置", defaults)
        self.assertIn("storedValue ?? (defaultIsValid ? spec?.default : '')", editor)
        self.assertIn("defaultIsValid ? spec?.default : ''", editor)
        self.assertNotIn("spec?.default ?? spec?.min ?? ''", editor)

    def test_new_model_candidates_do_not_inherit_previous_model_parameter_constraints(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        initialize = source[source.index("function ensureExecutionSelectionDefaults"):source.index("function capabilityFamilyLabel")]
        data = run_node("""
const assert=require('node:assert/strict');
const isCanvasSettingsMode=false;
const window={};
const executionSelectionDescriptor=()=>({kind:'image',nodeType:'image_generation',providerKey:'provider_id',modelKey:'model',familyKey:'imageFamilyId'});
const executionSelectionInputState=()=>({inputCounts:{text:1},inputRoles:[]});
const capabilityRegionForProvider=()=>'';
const capabilityProfileFor=()=>null;
const capabilityParameterIntent=()=>({style:'manga',webSearch:false,outputFormat:'png'});
const executionCompatibleProviderIds=(d,c,r,p)=>Object.keys(p).length?[]:['other-platform'];
const resolveCapabilityFamilySelection=(p,t,c,f,m,s,r,parameters)=>{
 assert.deepEqual(parameters,{});
 return {family:{family_id:'new-family'},profile:{model_id:'new-model'}};
};
""" + initialize + """
const current={engine:'api',provider_id:'old-platform',model:'old-model'};
ensureExecutionSelectionDefaults(current,{}, {resetSelection:true});
assert.equal(current.model,'new-model');
const inherited={engine:'api',provider_id:'removed-platform',model:'removed-model'};
ensureExecutionSelectionDefaults(inherited,{}, {resetSelection:false});
assert.equal(inherited.model,'removed-model');
console.log(JSON.stringify({ok:true}));
""")
        self.assertTrue(data["ok"])
        renderers = source[source.index("function verifiedTextGenerationModels"):source.index("function renderApiMusicParams")]
        self.assertNotIn("capabilityParameterIntent(", renderers)

    def test_execution_nodes_initialize_compatible_model_mode_and_parameter_defaults(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        create = source[source.index("function createExecutionNode"):source.index("function resultIdsForMediaItems")]
        load = source[source.index("async function loadCanvas"):source.index("function migrateLegacyMusicGeneratorNodes")]
        defaults = source[source.index("const CAPABILITY_PARAMETER_UNSET"):source.index("function generatedCapabilityParameterLabel")]

        self.assertIn("ensureExecutionSelectionDefaults(node.runSettings, node, {resetSelection:!hasInherited})", create)
        self.assertGreaterEqual(create.count("node.runSettings.engine = 'api'"), 5)
        self.assertIn("initializedExecutionDefaults", load)
        self.assertIn("ensureExecutionSelectionDefaults(node.runSettings, node)", load)
        self.assertIn("capabilitySafeDefaultProfileForFamily", source)
        self.assertIn("if(spec.ui_hidden === true && capabilityParameterIsOptional(spec)) return CAPABILITY_PARAMETER_UNSET", defaults)
        self.assertNotIn("if(options.length) return options[0]", defaults)
        self.assertNotIn("if(type === 'boolean') return false", defaults)
        default_fn = defaults[defaults.index("function capabilityParameterDefaultValue"):defaults.index("function capabilityProfileHasParameterDefaults")]
        self.assertNotIn("Number(spec.min)", default_fn)
        self.assertIn("value !== CAPABILITY_PARAMETER_UNSET", defaults)

    def test_model_family_and_platform_changes_persist_the_default_run_mode(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        bindings = source[source.index("function bindDynamicParams"):source.index("async function loadConfig")]

        family_handler = bindings[bindings.index("[data-execution-family-option]"):bindings.index("[data-execution-variant-option]")]
        provider_handler = bindings[bindings.index("[data-text-provider-option]"):bindings.index("[data-text-model]")]
        self.assertLess(family_handler.index("ensureExecutionSelectionDefaults"), family_handler.index("persistActiveSmartSettings"))
        self.assertLess(provider_handler.index("ensureExecutionSelectionDefaults"), provider_handler.index("persistActiveSmartSettings"))

    def test_execution_parameters_use_compact_upward_popovers_instead_of_expanded_cards(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        renderer = source[
            source.index("function renderGenericCapabilityParameters"):
            source.index("function volcengineProvider")
        ]

        self.assertIn("function renderCapabilityParameterControl", source)
        self.assertIn("smart-control capability-param-control", source)
        self.assertIn("smart-control capability-summary-control", source)
        self.assertIn("smart-popover capability-summary-popover", source)
        self.assertIn("smart-pill capability-param-pill", source)
        self.assertIn("smart-popover capability-param-popover", source)
        self.assertIn("capability-param-label", source)
        parameter_control = source[
            source.index("function renderCapabilityParameterControl"):
            source.index("function renderGenericCapabilityParameters")
        ]
        self.assertNotIn("capability-pill-copy", parameter_control)
        self.assertNotIn('<div class="capability-field"', renderer)
        self.assertIn(".capability-fields .capability-param-control", css)
        self.assertIn(".capability-summary-control", css)
        self.assertIn("grid-column:1 / -1", css[css.index(".capability-summary-control"):css.index(".capability-summary-control") + 240])
        self.assertIn(".capability-summary-popover", css)
        self.assertIn(".execution-config-grid > .smart-control { grid-column:1 / -1; width:100%; }", css)
        self.assertIn("max-height:none", css[css.index(".composer:not(.ai-app-composer) .dynamic-params {"):css.index(".composer:not(.ai-app-composer) .dynamic-params {") + 260])
        self.assertIn("scrollbar-width:none", css[css.index(".composer:not(.ai-app-composer) .dynamic-params {"):css.index(".composer:not(.ai-app-composer) .dynamic-params {") + 260])
        self.assertIn("text-align:center", css[css.index(".capability-model-name {"):css.index(".capability-model-name {") + 320])
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", css)
        self.assertIn(".smart-popover { position:absolute; left:50%; bottom:calc(100% + 8px)", css)
        self.assertIn("renderCapabilityParameters(profile, 'image')", source)
        self.assertIn("renderCapabilityParameters(profile, 'video')", source)
        self.assertIn("renderCapabilityParameters(profile, 'audio')", source)
        self.assertIn("renderCapabilityParameters(profile, 'music')", source)
        text_renderer = source[
            source.index("function renderTextGenerationParams"):
            source.index("function renderApiParams")
        ]
        self.assertIn("renderCapabilityParameterBundle(selection.profile)", text_renderer)

    def test_execution_settings_explain_parameters_and_keep_shortcuts_ordered(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        codex_profile = json.loads((ROOT / "data/model_capabilities/providers/codex-cli.json").read_text(encoding="utf-8"))

        self.assertIn("function capabilityParameterDescription", source)
        self.assertIn("function showCapabilityParameterTooltip", source)
        self.assertIn("data-capability-help", source)
        self.assertIn("data-capability-help-text", source)
        self.assertIn('data-lucide="circle-help"', source)
        self.assertIn("shortcutOrder = {resolution:0, duration:1, aspect_ratio:2}", source)
        self.assertIn("<div class=\"execution-config-panel-title\">", source)
        self.assertIn("${settingsControl}", source[source.index("function renderExecutionConfigPanel"):source.index("function capabilityParameterControlKind")])
        self.assertIn(".execution-config-panel-title .capability-settings-control", css)
        self.assertIn(".capability-parameter-tooltip { position:fixed;", css)
        self.assertIn("z-index:1200", css)
        self.assertNotIn("help-open", source)
        self.assertNotIn("help-open", css)
        self.assertIn("决定一次运行返回多少个结果", source)
        self.assertIn("限制模型最多生成多少文本", source)
        self.assertNotIn("设置“${capabilityParameterLabel", source)
        codex_models = {model["model_id"]: model for model in codex_profile["models"]}
        self.assertEqual(codex_models["auto"]["parameters"], {})
        self.assertTrue(codex_models["gpt-5.5"]["parameters"]["model"]["ui_hidden"])
        self.assertIn("spec?.ui_hidden !== true", source)

    def test_execution_parameter_values_reorder_without_a_layout_mode_button(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        panel = source[
            source.index("function renderExecutionConfigPanel"):
            source.index("function renderExecutionCountControl")
        ]
        renderer = source[
            source.index("function renderCapabilityParameterControl"):
            source.index("function capabilityParameterDescription")
        ]
        reorder = source[
            source.index("function capabilityOptionLayout"):
            source.index("function bindPreferenceSortDrag")
        ]

        self.assertNotIn("renderExecutionLayoutControl", panel)
        self.assertNotIn("data-capability-drag-handle", renderer)
        self.assertIn("${renderCapabilityModelHelp(profile)}${settingsControl}", panel)
        self.assertIn("data-capability-option-sort", source)
        self.assertNotIn("data-capability-option-drag-handle", reorder)
        self.assertNotIn("document.createElement('span')", source[source.index("function bindCapabilityOptionSort"):source.index("function preferenceListButtons")])
        self.assertIn("function capabilityOptionLayout", reorder)
        self.assertIn("function capabilityOptionVerticalInsertionTarget", reorder)
        self.assertIn("if(layout === 'vertical') return capabilityOptionVerticalInsertionTarget(items, clientY);", reorder)
        self.assertIn("capabilityOptionInsertionTarget", reorder)
        self.assertIn("animateCapabilityOptionShift", reorder)
        self.assertIn("capability-option-drag-preview", reorder)
        self.assertIn("capability-option-drop-placeholder", reorder)
        self.assertIn("saveCapabilityOptionOrder", reorder)
        self.assertNotIn("addEventListener('dragstart'", reorder)
        self.assertIn("function preferenceListButtons", reorder)
        self.assertIn("function preferenceInsertionTarget", reorder)
        self.assertIn("function startPreferencePointerDrag", reorder)
        self.assertIn("function movePreferencePointerDrag", reorder)
        self.assertIn("function finishPreferencePointerDrag", reorder)
        self.assertIn("function cancelPreferencePointerDrag", reorder)
        self.assertIn("handle.closest('button[data-preference-id]')", reorder)
        self.assertIn("pointermove", reorder)
        self.assertIn("pointerup", reorder)
        self.assertIn("preference-drag-preview", reorder)
        self.assertIn("is-preference-reordering", css)
        self.assertNotIn('draggable="true"', reorder)
        self.assertIn("currentIndexWithoutDragged", reorder)
        self.assertIn(".capability-option-drag-preview", css)
        self.assertIn(".capability-option.capability-option-drop-placeholder", css)
        self.assertIn(".capability-option-grid.capability-resolution-options", css)
        self.assertIn("touch-action:none", css)
        self.assertIn("width:28px !important", css[css.index(".execution-config-panel-title .capability-settings-control"):])

    def test_execution_settings_gear_matches_the_round_model_help_control(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        gear_rule = css[
            css.index(".dynamic-params .capability-settings-pill {"):
            css.index("}", css.index(".dynamic-params .capability-settings-pill {")) + 1
        ]
        panel = source[
            source.index("function renderExecutionConfigPanel"):
            source.index("function renderExecutionCountControl")
        ]
        count = source[
            source.index("function renderExecutionCountControl"):
            source.index("function bindExecutionCountControl")
        ]
        placement = source[
            source.index("function placeExecutionCountControl"):
            source.index("function capabilityParameterControlKind")
        ]

        self.assertIn("width:28px", gear_rule)
        self.assertIn("height:28px", gear_rule)
        self.assertIn("border:1px solid var(--line)", gear_rule)
        self.assertIn("border-radius:50%", gear_rule)
        self.assertIn("background:var(--card)", gear_rule)
        self.assertIn("${renderCapabilityModelHelp(profile)}${settingsControl}", panel)
        self.assertIn("${renderCapabilityModelName(profile)}", panel)
        self.assertLess(panel.index("${renderCapabilityModelHelp(profile)}"), panel.index("${settingsControl}</div>"))
        self.assertNotIn("chevron-down", count)
        self.assertIn("width:42px", css[css.index(".execution-count-control {"):css.index(".execution-count-options {")])
        self.assertIn("headerActions.appendChild(smartExecutionCountControl)", placement)
        self.assertIn("composerActions.insertBefore(smartExecutionCountControl, runBtn)", placement)
        self.assertIn("padding-right:76px", css)
        self.assertNotIn("padding-right:138px", css)

    def test_price_comparison_supports_provider_lookup_search_and_wheel_scroll(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn("function priceLookupUrl", source)
        self.assertIn("https://api.lao-hu.com/pricing", source)
        self.assertIn("https://www.runninghub.cn/call-api/search-api/standard-model?search=", source)
        self.assertIn("https://www.runninghub.ai/call-api/search-api/standard-model?search=", source)
        self.assertIn("provider?.rh_region === 'global'", source)
        self.assertIn("data-price-lookup", source)
        self.assertIn("await copyTextToClipboard(modelId)", source)
        self.assertIn("window.open(url, '_blank', 'noopener,noreferrer')", source)
        self.assertIn("smartPriceComparisonSearch?.addEventListener('search', renderPriceComparisonTable)", source)
        self.assertIn("smartPriceComparisonPanel?.addEventListener('wheel'", source)
        self.assertIn(".price-comparison-panel", source[source.index("shell.addEventListener('wheel'"):source.index("}, {passive:false});", source.index("shell.addEventListener('wheel'"))])
        self.assertIn(".price-lookup-btn", css)

    def test_video_execution_only_exposes_verified_schema_parameters(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        video = source[
            source.index("function renderApiVideoParams"):
            source.index("function renderApiAudioParams")
        ]
        volcengine = source[
            source.index("function renderVolcengineVideoParams"):
            source.index("function renderRunningHubParams")
        ]

        self.assertIn("renderCapabilityParameters(profile, 'video')", video)
        self.assertNotIn("compatibleControls", video)
        self.assertNotIn("renderVideoTrustedAssetControl", video)
        self.assertNotIn("renderVideoTrustedAssetControl", volcengine)
        self.assertNotIn("function renderVideoTrustedAssetControl", source)
        for legacy_copy in ("素材库链接", "上传云端", "输入网址"):
            self.assertNotIn(legacy_copy, video)
            self.assertNotIn(legacy_copy, volcengine)

    def test_capability_protocol_parameter_names_are_localized(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        labels = source[
            source.index("function capabilityParameterLabel"):
            source.index("function capabilityRunValue")
        ]

        expected = {
            "pronunciation_dict": "发音词典",
            "enable_base64_output": "Base64 输出",
            "english_normalization": "英文文本规范化",
            "webSearch": "联网搜索",
            "returnLastFrame": "返回尾帧",
            "realPersonMode": "真人保护模式",
            "conversionSlots": "真人转换范围",
            "bitrateMode": "码率模式",
            "outputFormat": "输出格式",
        }
        for key, label in expected.items():
            self.assertIn(f"{key}:'{label}'", labels)

        self.assertIn("knownEn", labels)
        self.assertIn("capabilityUiText", labels)

    def test_capability_parameters_keep_visual_shortcuts_and_group_the_rest_in_settings(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        renderer = source[
            source.index("function capabilityParameterSemantic"):
            source.index("function volcengineProvider")
        ]

        self.assertIn("function capabilityParameterSemantic", renderer)
        self.assertIn("resolution", renderer)
        self.assertIn("duration", renderer)
        self.assertIn("aspect_ratio", renderer)
        self.assertIn("function renderCapabilitySettingsControl", renderer)
        self.assertIn('data-capability-settings', renderer)
        self.assertIn('data-capability-option', renderer)
        self.assertIn("capabilityParameterChoiceOptions(key, spec)", renderer)
        self.assertIn("profile.parameters", renderer)
        self.assertIn("capability-aspect-option", renderer)
        self.assertIn("capability-duration-options", renderer)
        self.assertIn("capability-settings-popover", renderer)
        self.assertIn(".capability-settings-popover", css)
        self.assertIn(".capability-aspect-icon", css)
        self.assertIn(".capability-duration-options", css)

    def test_model_help_reflects_current_parameters_for_all_execution_nodes(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        help_renderer = source[
            source.index("function capabilityInputOutputSummary"):
            source.index("function renderCapabilityCostEstimate")
        ]

        self.assertIn("function capabilityActiveParameterSummary", help_renderer)
        self.assertIn("capability-help-current", help_renderer)
        self.assertIn("function refreshCapabilityModelHelp", source)
        for renderer_name in (
            "function renderTextGenerationParams",
            "function renderApiParams",
            "function renderApiVideoParams",
            "function renderApiAudioParams",
            "function renderApiMusicParams",
        ):
            section_start = source.index(renderer_name)
            section_end = source.index("\nfunction ", section_start + len(renderer_name))
            self.assertIn("renderExecutionConfigPanel", source[section_start:section_end])

        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        scrollbars = css[css.index(".composer:not(.ai-app-composer) .dynamic-params") :]
        self.assertIn("scrollbar-width:thin", scrollbars)
        self.assertIn("::-webkit-scrollbar", scrollbars)

    def test_execution_platform_click_is_applied_after_recent_settings_restore(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        section = source[source.index("function selectExecutionPlatform"):source.index("function runningHubRegion")]
        self.assertLess(section.index("if(providerId === 'modelscope')"), section.index("sanitizeSmartApiSelection(settings);"))
        self.assertLess(section.index("sanitizeSmartApiSelection(settings);"), section.index("subject.runSettings = settingsForStorage(settings);"))
        self.assertNotIn("applyRecentSmartSettingsForCurrentMode();", section)
        self.assertIn("settings.imageFamilyId = '';", section)
        self.assertIn("settings.videoFamilyId = '';", section)
        self.assertIn("settings.audioFamilyId = '';", section)
        self.assertIn("resolveCapabilityFamilySelection(providerId, 'image_generation'", section)
        self.assertIn("resolveCapabilityFamilySelection(providerId, 'video_generation'", section)
        self.assertIn("resolveCapabilityFamilySelection(providerId, 'audio_generation'", section)

    def test_text_generator_collects_connected_text_in_connection_order(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        runner = source[source.index("async function runPromptLLMNode"):source.index("function comfyFieldKind")]

        self.assertIn("upstreamConnectionsForKinds(node, ['input'])", source)
        self.assertIn("SMART_NODE_CONTRACT.createTextGenerationRequest", runner)
        self.assertIn("request.connectedTexts", runner)
        self.assertIn("const textInputs = isTextGenerator ? textGenerationMediaForNode(node) : null", runner)
        self.assertIn("textInputs.texts", runner)
        self.assertNotIn(".map(connection => textForNode", runner)

    def test_text_generator_request_orders_local_command_before_connected_text(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const request=c.createTextGenerationRequest(
  '先总结，再列出风险',
  ['较早连接的文本', '较晚连接的文本'],
  [
    {kind:'image',url:'/assets/a.png'},
    {kind:'video',url:'/assets/b.mp4'},
    {kind:'audio',url:'/assets/c.mp3'}
  ]
);
console.log(JSON.stringify(request));
"""
        data = run_node(script)

        self.assertEqual(data["message"], "先总结，再列出风险\n\n较早连接的文本\n\n较晚连接的文本")
        self.assertEqual(data["images"], ["/assets/a.png"])
        self.assertEqual(data["videos"], ["/assets/b.mp4"])
        self.assertEqual(data["audios"], ["/assets/c.mp3"])
        self.assertEqual(data["inputCounts"], {"text": 1, "image": 1, "video": 1, "audio": 1})
        self.assertEqual(data["connectedTextCount"], 2)

    def test_text_generator_request_exposes_stable_media_input_roles(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
console.log(JSON.stringify(c.createTextGenerationRequest(
  '分析这些素材', [],
  [
    {kind:'image',url:'/assets/a.png'},
    {kind:'video',url:'/assets/b.mp4'},
    {kind:'audio',url:'/assets/c.mp3'}
  ]
)));
"""
        data = run_node(script)
        self.assertEqual(data["inputRoles"], {
            "prompt": 1,
            "reference": 1,
            "source_video": 1,
            "reference_audio": 1,
        })

    def test_canvas_preflight_request_keeps_runtime_payload_and_minimal_graph(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const source={id:'material-1',type:c.NODE_TYPES.material};
const target={id:'generator-1',type:c.NODE_TYPES.imageGenerator};
const request=c.createCanvasPreflightRequest({
  node:target,
  canvasId:'canvas-1',
  clientOperationId:'operation-1',
  graphNodes:[source,target,{id:'unrelated',type:c.NODE_TYPES.videoGenerator}],
  graphConnections:[
    {id:'input-1',from:source.id,to:target.id,kind:'input'},
    {id:'unrelated-1',from:'unrelated',to:'missing',kind:'input'}
  ],
  providerId:'runninghub',
  modelId:'model/image-edit',
  familyId:'family/image',
  operation:'image_to_image',
  nodeType:'image_generation',
  inputs:{prompt:'重绘',reference:['/assets/input.png']},
  inputCounts:{text:1,image:1,video:0,audio:0},
  inputRoles:{prompt:1,reference:1},
  inputMetadata:{
    prompt:[{name:'节点提示词',characters:2,bytes:6}],
    reference:[{name:'输入图.png',bytes:1024,width:512,height:512}]
  },
  parameters:{resolution:'1k',aspect_ratio:'1:1'}
});
console.log(JSON.stringify(request));
"""
        data = run_node(script)

        self.assertEqual(data["provider_id"], "runninghub")
        self.assertEqual(data["canvas_id"], "canvas-1")
        self.assertEqual(data["node_id"], "generator-1")
        self.assertEqual(data["client_operation_id"], "operation-1")
        self.assertEqual(data["model_id"], "model/image-edit")
        self.assertEqual(data["family_id"], "family/image")
        self.assertEqual(data["operation"], "image_to_image")
        self.assertEqual(data["node_type"], "image_generation")
        self.assertEqual(data["inputs"], {"prompt": "重绘", "reference": ["/assets/input.png"]})
        self.assertEqual(data["input_metadata"]["reference"][0]["width"], 512)
        self.assertEqual(data["parameters"], {"resolution": "1k", "aspect_ratio": "1:1"})
        self.assertEqual([node["id"] for node in data["nodes"]], ["material-1", "generator-1"])
        self.assertEqual([connection["id"] for connection in data["connections"]], ["input-1"])

    def test_canvas_preflight_collects_input_metadata_before_submission(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        preflight = source[
            source.index("function canvasInputMetadataForPreflight"):
            source.index("async function runApiGeneration")
        ]

        self.assertIn("inputMetadata:options.inputMetadata || canvasInputMetadataForPreflight(options.inputs || {})", preflight)
        self.assertIn("new TextEncoder().encode(rawItem).length", preflight)
        self.assertIn("duration_seconds", preflight)

    def test_canvas_runtime_preflights_every_api_submission_before_network_call(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        cases = [
            ("async function runPromptLLMNode", "async function runSelectedNode", "await preflightCanvasNodeRun", "fetch('/api/canvas-llm'"),
            ("async function runApiGeneration", "function smartCompactJson", "await preflightCanvasNodeRun", "canvasModelClient.submitMany('/api/canvas-image-tasks'"),
            ("async function runRunningHubGeneration", "async function runApiVideoGeneration", "await preflightCanvasNodeRun", "submitAndPollRunningHub(endpoint"),
            ("async function runApiVideoGeneration", "async function runApiAudioGeneration", "await preflightCanvasNodeRun", "canvasModelClient.post('/api/canvas-video'"),
            ("async function runApiAudioMediaGeneration", "async function runModelscopeGeneration", "await preflightCanvasNodeRun", "canvasModelClient.post(isMusic ? '/api/canvas-music' : '/api/canvas-audio'"),
            ("async function runModelscopeGeneration", "async function urlToBase64", "await preflightCanvasNodeRun", "fetch('/api/canvas-image-tasks'"),
        ]

        self.assertIn("async function preflightCanvasNodeRun", source)
        self.assertIn("'/api/canvas-preflight'", source)
        for start, end, preflight, submission in cases:
            section = source[source.index(start):source.index(end, source.index(start))]
            self.assertIn(preflight, section)
            self.assertIn(submission, section)
            self.assertLess(section.index(preflight), section.index(submission))

    def test_canvas_runtime_reuses_one_operation_id_for_each_node_run(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        generation = source[source.index("async function runGeneration"):source.index("async function runPromptLLMNode")]
        text_generation = source[source.index("async function runPromptLLMNode"):source.index("async function runSelectedNode")]
        preflight = source[source.index("async function preflightCanvasNodeRun"):source.index("async function runApiGeneration")]

        self.assertIn("const clientOperationId = createCanvasOperationId(node.id)", generation)
        self.assertIn("clientOperationId", generation)
        self.assertIn("const clientOperationId = createCanvasOperationId(node.id)", text_generation)
        self.assertIn("clientOperationId", text_generation)
        self.assertNotIn("Date.now().toString(36)", preflight)

    def test_canvas_runtime_persists_local_run_lifecycle_and_result_ids(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        helpers = source[source.index("function createCanvasOperationId"):source.index("async function runApiGeneration")]
        image = source[source.index("async function runApiGeneration"):source.index("function smartCompactJson")]
        pending = source[source.index("async function resumeSmartPendingNode"):source.index("function resumeSmartPendingTasks")]
        text_generation = source[source.index("async function runPromptLLMNode"):source.index("async function runSelectedNode")]

        self.assertIn("'/api/canvas-runs/", helpers)
        self.assertIn("/status'", helpers)
        self.assertIn("/results'", helpers)
        self.assertIn("resultIdsForMediaItems", helpers)
        self.assertIn("await queueCanvasRun", image)
        self.assertLess(image.index("await queueCanvasRun"), image.index("canvasModelClient.submitMany('/api/canvas-image-tasks'"))
        self.assertIn("await submitCanvasRun", image)
        self.assertIn("await processCanvasRun", pending)
        self.assertIn("await finishCanvasRun", pending)
        self.assertIn("await finishCanvasRun(runSubject, [stored])", text_generation)

    def test_image_batch_submission_keeps_successful_task_ids_when_one_creation_fails(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        image = source[source.index("async function runApiGeneration"):source.index("function smartCompactJson")]
        generation = source[source.index("async function runGeneration"):source.index("async function runPromptLLMNode")]
        pending = source[source.index("async function resumeSmartPendingNode"):source.index("function resumeSmartPendingTasks")]

        self.assertIn("canvasModelClient.submitMany", image)
        self.assertIn("Promise.allSettled", (ROOT / "static/js/canvas-model-client.js").read_text())
        self.assertIn("submissionFailures", image)
        self.assertIn("await recoverCanvasRun(activeRunNode", image)
        self.assertIn("runSubmissionFailures", generation)
        self.assertIn("'partially_succeeded'", pending)

    def test_failed_pending_run_keeps_result_placeholder_with_error_state(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        helpers = source[
            source.index("function createPendingOutputFromSource"):
            source.index("function createParallelLoopOutputNode")
        ]
        pending = source[source.index("async function resumeSmartPendingNode"):source.index("function resumeSmartPendingTasks")]
        generation = source[source.index("async function runGeneration"):source.index("async function runPromptLLMNode")]

        self.assertIn("isRunPlaceholder:true", helpers)
        self.assertIn("function removeEmptyRunPlaceholder", source)
        self.assertIn("await failCanvasRun(node, allFailures[0])", pending)
        self.assertNotIn("removeEmptyRunPlaceholder(node)", pending)
        self.assertIn("await failCanvasRun(pendingNode, e)", generation)
        self.assertNotIn("removeEmptyRunPlaceholder(branchNode)", generation)

    def test_runninghub_run_status_distinguishes_pre_submit_failure_recovery_and_platform_failure(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        generation = source[source.index("async function runGeneration"):source.index("async function runPromptLLMNode")]
        runninghub = source[source.index("async function runRunningHubGeneration"):source.index("async function runApiVideoGeneration")]

        self.assertIn("delete runSettings.rhTaskId", runninghub)
        self.assertIn("const knownTaskId", runninghub)
        self.assertIn("stage !== '执行'", runninghub)
        self.assertIn("await recoverCanvasRun(node, error)", runninghub)
        self.assertIn("await failCanvasRun(node, error)", runninghub)
        self.assertIn("error.canvasRunStatusHandled = true", runninghub)
        self.assertIn("if(!e?.canvasRunStatusHandled) await failCanvasRun(pendingNode, e)", generation)

    def test_canvas_load_restores_run_state_from_backend_ledger(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        restore_start = source.index("async function restoreCanvasRuns")
        load_start = source.index("async function loadCanvas()", restore_start)
        load = source[load_start:source.index("function scheduleSave", load_start)]
        restore = source[restore_start:load_start]

        self.assertIn("fetch(`/api/canvas-runs?canvas_id=", restore)
        self.assertIn("runById.get(canvasRunId(node))", restore)
        self.assertIn("node.runStatus = status", restore)
        self.assertIn("['queued','submitted','processing'].includes(status)", restore)
        self.assertIn("status === 'recoverable'", restore)
        self.assertIn("await restoreCanvasRuns()", load)
        self.assertLess(load.index("await restoreCanvasRuns()"), load.index("render()"))

    def test_recoverable_local_task_stops_polling_without_resubmission(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        poller = source[source.index("async function pollSmartCanvasTask"):source.index("function finalizeSmartPendingTask")]
        recovery = source[source.index("function smartRecoverableImageTask"):source.index("function smartNodeToolbarImageIndex")]
        resume = source[source.index("async function resumeSmartPendingNode"):source.index("function resumeSmartPendingTasks")]

        self.assertIn("task.status === 'recoverable'", poller)
        self.assertIn("new ImageTaskRecoverSignal", poller)
        self.assertIn("task.recoveryBlocked", recovery)
        self.assertIn("e && e.imageTaskRecover", resume)
        self.assertIn("task.recoveryBlocked = !e.recoverTaskId", resume)

    def test_text_generator_collects_connected_media_without_image_only_helper(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        request_builder = source[
            source.index("function textGenerationRequestForNode"):
            source.index("function verifiedTextGenerationModels")
        ]

        self.assertIn("function textGenerationMediaForNode", source)
        self.assertIn("textGenerationMediaForNode(node)", request_builder)
        self.assertNotIn("visibleReferenceImagesFor(node)", request_builder)

    def test_text_generator_lists_only_enabled_llms_before_prompt_entry(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        candidate_filter = source[
            source.index("function verifiedTextGenerationModels"):
            source.index("function renderTextGenerationParams")
        ]
        renderer = source[
            source.index("function renderTextGenerationParams"):
            source.index("function renderApiParams")
        ]

        self.assertIn("textGenerationCandidateInputCounts(request)", candidate_filter)
        self.assertIn("const sourceSettings = node?.runSettings || settings", candidate_filter)
        self.assertIn("configuredCapabilityModelIds(model.provider_id, 'text_generation', region)", candidate_filter)
        self.assertIn("enabledIds.has(String(model.model_id", candidate_filter)
        self.assertIn("const inputCounts = textGenerationCandidateInputCounts(request)", renderer)
        self.assertIn("resolveCapabilityFamilySelection(settings.textProvider, 'text_generation', inputCounts", renderer)

        from tests.provider_fixture import configured_providers
        providers = configured_providers()
        codex = next(item for item in providers if item["id"] == "codex")
        codex_profile = json.loads((ROOT / "data/model_capabilities/providers/codex-cli.json").read_text(encoding="utf-8"))
        codex_text_models = {
            item["model_id"]
            for item in codex_profile["models"]
            if item.get("node_type") == "text_generation" and item.get("runnable") is not False
        }

        self.assertEqual(codex["chat_models"][0], "auto")
        self.assertIn("gpt-5.5", codex["chat_models"])
        self.assertTrue(codex_text_models.issubset(set(codex["chat_models"])))

    def test_text_generator_lists_only_providers_compatible_with_current_inputs(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        platform_control = source[
            source.index("function renderTextExecutionPlatformControl"):
            source.index("function chatModelOptions")
        ]
        renderer = source[
            source.index("function renderTextGenerationParams"):
            source.index("function renderApiParams")
        ]

        self.assertIn("const providers = chatApiProviders().filter", platform_control)
        self.assertIn("textProviderCompatibleModelCount", platform_control)
        self.assertNotIn("data-text-provider-unavailable", platform_control)
        self.assertIn("if(!settings.textProvider)", renderer)
        self.assertNotIn("if(!providerIds.includes(settings.textProvider))", renderer)

    def test_canvas_llm_accepts_audio_but_validates_all_connected_media(self):
        main_source = (ROOT / "main.py").read_text(encoding="utf-8")

        request_model = main_source[main_source.index("class CanvasLLMRequest"):main_source.index("class CanvasTextResultRequest")]
        endpoint = main_source[main_source.index('async def canvas_llm(payload: CanvasLLMRequest)'):main_source.index("# --- 对话管理 ---")]
        self.assertIn("audios: List[str]", request_model)
        self.assertIn("resolve_model_capability_request", endpoint)
        self.assertIn('"audio": len(payload.audios or [])', endpoint)

    def test_text_material_reuses_toolbar_and_saves_versions_in_place(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        toolbar = source[source.index("function smartNodeToolbarHtml"):source.index("function duplicateSmartNodeMediaToCanvas")]
        saver = source[source.index("async function saveTextMaterialEditor"):source.index("function openGroupImagePreview")]
        renderer = source[source.index("function singleMediaHtml"):source.index("function smartNodeHasLiveMedia")]

        self.assertIn("key:'replace'", toolbar)
        self.assertIn("label:capabilityUiText('上传素材','Upload material')", toolbar)
        self.assertNotIn("上传并替换", toolbar)
        self.assertIn("key:'template'", toolbar)
        self.assertNotIn("media-text-head", renderer)
        self.assertIn("source.resultVersions.push", saver)
        self.assertIn("source.images=", saver)
        self.assertNotIn("nodes.push", saver)

    def test_text_result_content_survives_result_normalization_and_canvas_reload(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        finalizer = source[source.index("function finalizePendingNode"):source.index("function restoreFromExtraction")]
        loader = source[source.index("async function hydrateTextResultMediaContent"):source.index("function bindImageProxyFallback")]
        canvas_loader = source[source.index("async function loadCanvas"):source.index("function migrateLegacyMusicGeneratorNodes")]

        self.assertIn("const source = item && typeof item === 'object' ? item : {};", finalizer)
        self.assertIn("{...source, url, name:pendingNode.creationTask", finalizer)
        self.assertIn("entry.item.text = content", loader)
        self.assertIn("entry.item.content = content", loader)
        self.assertIn("fetch(entry.url, {cache:'no-store'})", loader)
        self.assertIn("const hydratedTextResults = await hydrateTextResultMediaContent(nodes);", canvas_loader)

    def test_alt_drag_duplicates_the_whole_selection_as_one_undo_transaction(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        duplicate = source[source.index("function duplicateForAltDrag"):source.index("function shellPoint")]
        drag = source[source.index("const beginNodeDrag = e =>"):source.index("el.querySelectorAll('.node-port')", source.index("const beginNodeDrag = e =>"))]

        self.assertIn("selectedIds = copies.length > 1 ? copies.map", duplicate)
        self.assertNotIn("pushUndo()", duplicate)
        self.assertNotIn("scheduleSave()", duplicate)
        self.assertLess(drag.index("capturePendingUndo()"), drag.index("duplicateForAltDrag"))
        self.assertIn("altDuplicated:Boolean(e.altKey)", drag)

    def test_new_material_nodes_use_compact_dimensions_without_migrating_existing_nodes(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        creator = source[source.index("function createNode(x, y"):source.index("function createExecutionNode")]
        text_creator = source[source.index("function createTextMaterialNodeAt"):source.index("function smartGroupLayoutSize")]

        self.assertIn("defaultSingleMaterialSize", creator)
        self.assertIn("node.w = defaultSize.width", creator)
        self.assertIn("node.h = defaultSize.height", creator)
        self.assertIn("node.w = EMPTY_UPLOAD_NODE_WIDTH", text_creator)
        self.assertIn("node.h = EMPTY_UPLOAD_NODE_HEIGHT", text_creator)

    def test_canvas_pan_uses_a_composited_transform_without_rerendering_nodes(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        viewport = source[source.index("function applyViewport"):source.index("function screenToWorld")]
        mousemove = source[source.index("window.onmousemove"):source.index("window.onmouseup")]
        pan = mousemove[mousemove.index("if(panState)"):mousemove.index("if(!dragState)")]

        self.assertIn("translate3d", viewport)
        self.assertIn("applyViewport()", pan)
        self.assertNotIn("render()", pan)

    def test_space_left_drag_temporarily_pans_over_every_canvas_control_without_clicking_it(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        html = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")
        i18n = (ROOT / "static/js/i18n/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("function beginSpaceCanvasPan", source)
        start = source.index("function beginSpaceCanvasPan")
        end = source.index("shell.addEventListener('mousedown'", start)
        behavior = source[start:end]
        keydown = source[source.index("window.addEventListener('keydown'"):source.index("window.addEventListener('keyup'")]

        self.assertIn("event.button !== 0", behavior)
        self.assertIn("isSpacePanKeyDown", behavior)
        self.assertIn("event.preventDefault()", behavior)
        self.assertIn("event.stopImmediatePropagation", behavior)
        self.assertIn("spacePan:true", behavior)
        self.assertIn("function moveSpaceCanvasPan", behavior)
        self.assertIn("function finishSpaceCanvasPan", behavior)
        self.assertIn("function suppressSpaceCanvasPanClick", behavior)
        self.assertIn("spacePanGestureToken", behavior)
        self.assertIn("SPACE_PAN_CLICK_GUARD_MS", behavior)
        self.assertNotIn("closeCreateMenu", behavior)
        self.assertNotIn("clearSelection", behavior)
        self.assertIn("window.addEventListener('pointerdown', beginSpaceCanvasPan, true)", source)
        self.assertIn("window.addEventListener('mousedown', beginSpaceCanvasPan, true)", source)
        self.assertIn("window.addEventListener('pointermove', moveSpaceCanvasPan, true)", source)
        self.assertIn("window.addEventListener('mousemove', moveSpaceCanvasPan, true)", source)
        self.assertIn("window.addEventListener('pointerup', finishSpaceCanvasPan, true)", source)
        self.assertIn("window.addEventListener('pointercancel', finishSpaceCanvasPan, true)", source)
        self.assertIn("window.addEventListener('click', suppressSpaceCanvasPanClick, true)", source)
        self.assertIn("e.code === 'Space'", keydown)
        self.assertIn("!canvasTextEditableForTarget(e.target)", keydown)
        self.assertIn("setSpaceCanvasPanReady(true)", keydown)
        self.assertNotIn("data-minimax-play-timeline", keydown)
        self.assertIn(".shell.space-pan-ready", css)
        self.assertIn(".shell.space-panning", css)
        self.assertIn('data-i18n="smart.shortcutSpacePan"', html)
        self.assertIn('"smart.shortcutSpacePan": { zh: "按住空格并拖动：从任意画布内容平移画布", en: "Hold Space and drag: pan from anywhere on the canvas" }', i18n)

    def test_files_dropped_on_text_material_replace_instead_of_append(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        handler = source[source.index("async function handleFiles"):source.index("async function importSmartLocalImages")]

        self.assertIn("replaceTextMaterialFromFiles", handler)
        self.assertIn("targetId", handler)

    def test_execution_nodes_preserve_preview_dimensions(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const types=[c.NODE_TYPES.imageGenerator,c.NODE_TYPES.videoGenerator,c.NODE_TYPES.audioGenerator,c.NODE_TYPES.aiApp,c.NODE_TYPES.comfyWorkflow];
console.log(JSON.stringify(types.map(type=>c.normalizeExecutionNode({type,w:900,h:700}))));
"""
        data = run_node(script)

        self.assertEqual([(node["w"], node["h"]) for node in data], [(900, 700)] * 5)

    def test_runninghub_comfyui_only_accepts_ai_apps(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
console.log(JSON.stringify({
  title:c.titleForType(c.NODE_TYPES.aiApp),
  kinds:c.runningHubEntryKindsForType(c.NODE_TYPES.aiApp),
  localTitle:c.titleForType(c.NODE_TYPES.comfyWorkflow),
  localSettings:c.normalizeExecutionSettings({type:c.NODE_TYPES.comfyWorkflow},{engine:'api',comfyMode:'text'})
}));
"""
        data = run_node(script)

        self.assertEqual(data["title"], "AI 应用")
        self.assertEqual(data["kinds"], ["app"])
        self.assertEqual(data["localTitle"], "本地 ComfyUI")
        self.assertEqual(data["localSettings"]["engine"], "comfy")
        self.assertEqual(data["localSettings"]["comfyMode"], "custom")

    def test_runninghub_ai_app_is_selected_from_api_settings_registry(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        picker = source[source.index("function renderRhConfigControl"):source.index("function renderRhPaymentControl")]
        self.assertIn("runningHubEnabledRegions()", picker)
        self.assertIn("runningHubEntries('app', {...settings, rhRegion:region})", picker)
        self.assertIn("data-rh-region", picker)
        self.assertIn("RunningHub · CN", picker)
        self.assertIn("RunningHub · AI", picker)
        self.assertIn("data-smart-param=\"rhConfigKey\"", picker)
        self.assertNotIn("runningHubEntries('workflow')", picker)
        self.assertNotIn("data-rh-app-id-input", picker)
        self.assertNotIn("data-rh-app-fetch", picker)

    def test_runninghub_canvas_passes_selected_region_to_runtime_requests(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("function runningHubRegion(sourceSettings=null)", source)
        self.assertIn("runningHubRegion(runSettings)", source)
        self.assertIn("rhRegion", source)
        self.assertIn("runningHubProviderForRegion", source)
        self.assertIn("runningHubWorkflowCacheKey", source)
        self.assertNotIn("&region=${encodeURIComponent(runningHubRegion())}", source)

    def test_api_settings_runninghub_registry_only_accepts_ai_apps(self):
        html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")
        source = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/api-settings.css").read_text(encoding="utf-8")

        self.assertIn('id="runninghubConfigBlock"', html)
        self.assertIn('id="rhGlobalAppsList"', html)
        self.assertIn('id="rhCnAppsList"', html)
        self.assertNotIn('id="rhWorkflowsList"', html)
        runninghub_block = html[html.index('id="runninghubConfigBlock"'):html.index('id="modelsHead"')]
        self.assertIn("AI 应用", runninghub_block)
        self.assertNotIn("工作流", runninghub_block)
        self.assertNotIn("/run/workflow/", runninghub_block)
        self.assertIn("if(/^[0-9A-Za-z_-]{4,}$/.test(text)) return { type:'app', id:text }", source)
        create_entry = source[source.index("async function createRhEntryFromPaste"):source.index("function updateRhEntry")]
        self.assertIn("parsed.type !== 'app'", create_entry)
        self.assertIn("runningHubRegionEntries(item, targetRegion, 'app')", create_entry)
        self.assertNotIn("'rh_workflows'", create_entry)
        self.assertIn("await syncRhAppFromOfficial(targetIndex, targetRegion)", create_entry)
        self.assertNotIn("openRhAppEditor(targetIndex)", create_entry)
        self.assertIn("function syncRhAppFromOfficial", source)
        self.assertIn("entry.title = officialTitle", source)
        self.assertIn("entry.thumbnail = String(raw.covers?.[0]?.thumbnailUri", source)
        self.assertIn("entry.fields = rhAppFieldSourceList(raw).map(normalizeFetchedRhAppField)", source)
        self.assertIn("entry.raw = raw", source)
        self.assertIn("function parseRhOfficialFieldData", source)
        self.assertIn("const official = parseRhOfficialFieldData(field?.fieldData)", source)
        self.assertIn("options:official.options", source)
        self.assertIn("min:official.min", source)
        self.assertIn("max:official.max", source)
        self.assertIn("step:official.step", source)
        self.assertNotIn("onclick=\"pickRhThumbnail('app'", source)
        self.assertNotIn("updateRhEntry('app'", source)
        self.assertNotIn("function openRhAppEditor", source)
        self.assertNotIn("function fetchRhAppEditor", source)
        self.assertIn("官方封面", source)
        self.assertIn("RunningHub 官方应用", source)
        self.assertIn("syncRhAppFromOfficial", source)
        self.assertIn(".rh-card-columns { display:grid; grid-template-columns:minmax(0,1fr);", css)

    def test_runninghub_model_picker_distinguishes_region_availability(self):
        source = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/api-settings.css").read_text(encoding="utf-8")
        i18n = (ROOT / "static/js/i18n/api-settings.js").read_text(encoding="utf-8")

        self.assertIn("let lastFetchedModelAvailability = {};", source)
        self.assertIn("data?.model_availability", source)
        self.assertIn("runningHubAvailabilityBadge", source)
        self.assertIn("picker-availability-${status}", source)
        self.assertIn(".picker-availability-confirmed", css)
        self.assertIn(".picker-availability-unverified", css)
        self.assertIn("api.rhModelConfirmed", i18n)
        self.assertIn("api.rhModelUnverified", i18n)
        self.assertIn(".picker-model-availability", css)

    def test_model_picker_bulk_selection_replaces_the_complete_selection_state(self):
        source = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        helper = source[
            source.index("function buildPickerBulkSelection"):
            source.index("function selectPickerModels")
        ]
        data = run_node(
            helper
            + "\nconst ids=['listed','unknown'];"
            + "\nconst current={listed:false,unknown:true};"
            + "\nconst availability={listed:'confirmed',unknown:'unverified'};"
            + "\nconsole.log(JSON.stringify({"
            + "recommended:buildPickerBulkSelection(ids,current,availability,'recommended',true),"
            + "all:buildPickerBulkSelection(ids,current,availability,'all',true),"
            + "clear:buildPickerBulkSelection(ids,current,availability,'clear',true)"
            + "}));"
        )

        self.assertEqual(data["recommended"], {"listed": True, "unknown": False})
        self.assertEqual(data["all"], {"listed": True, "unknown": True})
        self.assertEqual(data["clear"], {"listed": False, "unknown": False})

    def test_runninghub_connection_copy_does_not_claim_catalog_fetch_verified_key(self):
        source = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")

        self.assertNotIn("RunningHub Key 已验证", source)
        self.assertNotIn("✓ RunningHub OpenAPI 验证通过", source)
        self.assertIn("api.rhCatalogLoaded", source)

    def test_runninghub_region_switch_clears_stale_picker_catalog(self):
        source = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        switch_block = source[source.index("function selectRunningHubModelRegion"):source.index("function updateRunningHubKeyInput")]

        self.assertIn("clearFetchedModelState();", switch_block)
        self.assertIn("function clearFetchedModelState()", source)
        self.assertIn("lastFetchedModelAvailability = {};", source)
        self.assertIn("openBtn.disabled = true", source)

    def test_api_provider_switch_cannot_reuse_previous_provider_catalog(self):
        source = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        select_block = source[source.index("function selectProvider"):source.index("function addProvider")]

        self.assertIn("clearFetchedModelState();", select_block)
        self.assertLess(select_block.index("clearFetchedModelState();"), select_block.index("selectedId = id;"))

    def test_runninghub_official_field_data_preserves_labels_and_submit_values(self):
        source = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        parser = source[
            source.index("function parseRhOfficialFieldData"):
            source.index("function normalizeFetchedRhAppField")
        ]
        data = run_node(
            parser
            + "\nconst toggle=parseRhOfficialFieldData(['SWITCH',["
            + "{name:'input2',index:2,description:'否'},"
            + "{name:'input1',index:1,description:'是'}]]);"
            + "const number=parseRhOfficialFieldData(['FLOAT',{min:-100,max:100,step:0.01,default:1,required:true}]);"
            + "const serialized=parseRhOfficialFieldData('[{\"name\":\"input3\",\"index\":3.0,\"description\":\"720p\"},{\"name\":\"input1\",\"index\":1.0,\"description\":\"480p\"}]');"
            + "const audio=parseRhOfficialFieldData('[\"COMBO\",{\"options\":[\"None\"],\"audio_upload\":true}]');"
            + "console.log(JSON.stringify({toggle,number,serialized,audio}));"
        )

        self.assertEqual(data["toggle"]["options"], ["2", "1"])
        self.assertEqual(data["toggle"]["optionLabels"], {"1": "是", "2": "否"})
        self.assertEqual(data["number"]["min"], -100)
        self.assertEqual(data["number"]["max"], 100)
        self.assertEqual(data["number"]["step"], 0.01)
        self.assertEqual(data["number"]["defaultValue"], 1)
        self.assertTrue(data["number"]["required"])
        self.assertEqual(data["serialized"]["options"], ["3", "1"])
        self.assertEqual(data["serialized"]["optionLabels"], {"3": "720p", "1": "480p"})
        self.assertEqual(data["audio"]["type"], "AUDIO")
        self.assertTrue(data["audio"]["acceptsUpload"])

    def test_runninghub_legacy_app_snapshot_recovers_official_field_schema(self):
        script = r"""
const c=require('./static/js/smart-node-contract.js');
const provider={
  id:'runninghub',
  rh_apps:[{
    id:'app-1',
    fields:[
      {nodeId:'517',fieldName:'image',fieldType:'TEXT',label:'image'},
      {nodeId:'720',fieldName:'select',fieldType:'TEXT',label:'是否高清视频？',fieldValue:'1'}
    ],
    raw:{nodeInfoList:[
      {nodeId:'517',fieldName:'image',description:'数字人图片',fieldData:'["COMBO",{"image_upload":true}]'},
      {nodeId:'720',fieldName:'select',description:'是否高清视频？',fieldData:'["SWITCH",[{"name":"input2","index":2,"description":"否"},{"name":"input1","index":1,"description":"是"}]]'}
    ]}
  }]
};
console.log(JSON.stringify(c.hydrateRunningHubProviderApps(provider)));
"""
        data = run_node(script)
        fields = data["rh_apps"][0]["fields"]

        self.assertEqual(fields[0]["fieldType"], "IMAGE")
        self.assertEqual(fields[0]["label"], "数字人图片")
        self.assertTrue(fields[0]["acceptsUpload"])
        self.assertEqual(fields[1]["fieldType"], "SELECT")
        self.assertEqual(fields[1]["options"], ["2", "1"])
        self.assertEqual(fields[1]["optionLabels"], {"1": "是", "2": "否"})
        self.assertEqual(fields[1]["fieldValue"], "1")
        self.assertEqual([field["schemaOrder"] for field in fields], [0, 1])

        canvas_source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        settings_html = (ROOT / "static/api-settings.html").read_text(encoding="utf-8")
        settings_source = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
        self.assertIn("SMART_NODE_CONTRACT.hydrateRunningHubProviderApps(provider)", canvas_source)
        self.assertLess(settings_html.index("smart-node-contract.js"), settings_html.index("api-settings.js"))
        self.assertIn("SmartNodeContract.parseRunningHubOfficialFieldData(value)", settings_source)

    def test_runninghub_schema_diff_treats_legacy_type_names_as_equivalent(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const legacy=[
  {nodeId:'603',fieldName:'select',fieldType:'SWITCH',imageOrder:0},
  {nodeId:'543',fieldName:'text',fieldType:'STRING',imageOrder:0},
  {nodeId:'740',fieldName:'strength_model',fieldType:'FLOAT',imageOrder:0}
];
const normalized=[
  {nodeId:'603',fieldName:'select',fieldType:'SELECT',imageOrder:0},
  {nodeId:'543',fieldName:'text',fieldType:'TEXT',imageOrder:0},
  {nodeId:'740',fieldName:'strength_model',fieldType:'NUMBER',imageOrder:0}
];
console.log(JSON.stringify({
  fields:c.diffRunningHubSchema(legacy, normalized),
  snapshot:c.diffRunningHubSchema([
    {key:'603::select',kind:'switch',required:false,order:0},
    {key:'543::text',kind:'string',required:false,order:0},
    {key:'740::strength_model',kind:'float',required:false,order:0}
  ], normalized)
}));
"""
        data = run_node(script)

        self.assertFalse(data["fields"]["changed"])
        self.assertEqual(data["fields"]["typeChanged"], [])
        self.assertFalse(data["snapshot"]["changed"])
        self.assertEqual(data["snapshot"]["typeChanged"], [])

    def test_runninghub_schema_diff_treats_uniform_legacy_order_as_array_order(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const legacy=[
  {key:'453::audio',kind:'audio',required:false,order:0},
  {key:'592::text',kind:'text',required:false,order:0},
  {key:'517::image',kind:'image',required:false,order:0}
];
const current=[
  {nodeId:'453',fieldName:'audio',fieldType:'AUDIO',schemaOrder:0},
  {nodeId:'592',fieldName:'text',fieldType:'TEXT',schemaOrder:1},
  {nodeId:'517',fieldName:'image',fieldType:'IMAGE',schemaOrder:2}
];
console.log(JSON.stringify(c.diffRunningHubSchema(legacy,current)));
"""
        data = run_node(script)

        self.assertFalse(data["changed"])
        self.assertEqual(data["orderChanged"], [])

    def test_runninghub_connections_keep_distinct_target_field_keys(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const migrated=c.migrateLegacyCanvas(
  [
    {id:'material-1',type:c.NODE_TYPES.material,images:[{kind:'image',url:'/a.png'}]},
    {id:'app-1',type:c.NODE_TYPES.aiApp,runSettings:{}}
  ],
  [
    {from:'material-1',to:'app-1',kind:'input',targetFieldKey:'517::image'},
    {from:'material-1',to:'app-1',kind:'input',target_field_key:'518::image'}
  ]
);
console.log(JSON.stringify(migrated.connections));
"""
        data = run_node(script)

        self.assertEqual(len(data), 2)
        self.assertEqual(
            {item.get("targetFieldKey") or item.get("target_field_key") for item in data},
            {"517::image", "518::image"},
        )

    def test_runninghub_target_plan_auto_binds_one_slot_and_asks_for_multiple(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const fields=[
  {nodeId:'517',fieldName:'image',fieldType:'IMAGE',label:'数字人图片'},
  {nodeId:'518',fieldName:'image',fieldType:'IMAGE',label:'背景图片'},
  {nodeId:'453',fieldName:'audio',fieldType:'AUDIO',label:'音频'}
];
const occupied=[{from:'old',to:'app',kind:'input',targetFieldKey:'517::image'}];
console.log(JSON.stringify({
  empty:c.runningHubTargetFieldPlan(fields,'image',[], 'app'),
  oneLeft:c.runningHubTargetFieldPlan(fields,'image',occupied,'app'),
  audio:c.runningHubTargetFieldPlan(fields,'audio',[], 'app')
}));
"""
        data = run_node(script)

        self.assertEqual(data["empty"]["mode"], "choose")
        self.assertEqual([field["key"] for field in data["empty"]["choices"]], ["517::image", "518::image"])
        self.assertEqual(data["oneLeft"]["mode"], "auto")
        self.assertEqual(data["oneLeft"]["targetFieldKey"], "518::image")
        self.assertEqual(data["audio"]["mode"], "auto")
        self.assertEqual(data["audio"]["targetFieldKey"], "453::audio")

    def test_runninghub_field_picker_survives_the_drop_click_that_opens_it(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        picker = source[
            source.index("function closeRunningHubFieldPicker"):
            source.index("function rhMediaKindLabel")
        ]
        document_click_start = source.index("document.addEventListener('click', event => {")
        document_click = source[
            document_click_start:
            source.index("document.addEventListener('keydown', event => {", document_click_start)
        ]

        self.assertIn("runningHubFieldPickerOpeningEvent", picker)
        self.assertIn("runningHubFieldPickerOpeningEvent = event", picker)
        self.assertIn("function runningHubFieldPickerOpenedByDropClick(event)", picker)
        self.assertIn("runningHubFieldPickerOpeningStamp", picker)
        self.assertIn("runningHubFieldPickerOpenedByDropClick(event)", document_click)
        self.assertIn("closeRunningHubFieldPicker(true)", document_click)

    def test_runninghub_ai_app_only_replaces_the_middle_detail_area(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        body = source[source.index("function smartExecutionNodeBodyHtml"):source.index("function runningHubTargetBadgesHtml")]
        meta = source[source.index("function smartExecutionNodeMeta"):source.index("function smartExecutionNodeBodyHtml")]
        self.assertIn("smart-ai-app-card", body)
        self.assertIn("smart-execution-icon", body)
        self.assertIn("smart-execution-title", body)
        self.assertIn("smart-execution-provider", body)
        self.assertIn("smart-execution-app-id", body)
        self.assertIn("smart-execution-footer", body)
        self.assertIn("smart-ai-app-name", body)
        self.assertIn("meta.model", body)
        self.assertIn("meta.appId", body)
        self.assertIn("runningHubEntryLabel(selectedRhRef.entry, selectedRhRef.kind)", meta)
        self.assertIn("appId:selectedRhRef?.id", meta)
        self.assertNotIn("runningHubNamedSlotsHtml", body)
        self.assertNotIn("smart-ai-app-slots", body)
        self.assertIn("connectionTargetFieldKey(connection)", source)
        self.assertIn("composer.classList.toggle('ai-app-composer'", source)
        self.assertIn(".composer.ai-app-composer .prompt-row", css)
        self.assertIn(".smart-ai-app-card", css)
        self.assertIn(".smart-ai-app-name", css)

    def test_runninghub_parameter_rows_stack_labels_above_self_sizing_controls(self):
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn(".rh-ai-app-param-list .rh-ai-app-param-row", css)
        self.assertIn("grid-template-columns:minmax(0,1fr)", css)
        self.assertIn("align-items:stretch", css)
        self.assertIn("box-sizing:border-box", css)
        self.assertIn("flex:0 0 auto", css)
        self.assertIn(".rh-ai-app-param-list .rh-ai-app-media-control", css)
        self.assertIn("width:100%", css)
        self.assertIn("renderRhUnconnectedInputControl", source)
        self.assertIn(".rh-ai-app-unconnected-card", css)

    def test_result_connection_is_layout_output_but_not_workflow_input(self):
        data = run_node(
            "const c=require('./static/js/smart-node-contract.js');"
            "const result={from:'run',to:'material',kind:'result'};"
            "const input={from:'material',to:'run',kind:'input'};"
            "console.log(JSON.stringify({"
            "resultLayout:c.isOutputLayoutConnection(result),"
            "resultWorkflow:c.isWorkflowConnection(result),"
            "inputLayout:c.isOutputLayoutConnection(input),"
            "inputWorkflow:c.isWorkflowConnection(input)"
            "}));"
        )

        self.assertTrue(data["resultLayout"])
        self.assertFalse(data["resultWorkflow"])
        self.assertTrue(data["inputLayout"])
        self.assertTrue(data["inputWorkflow"])

    def test_execution_settings_are_normalized_by_node_type(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const source={engine:'api',apiKind:'video'};
console.log(JSON.stringify({
  image:c.normalizeExecutionSettings({type:c.NODE_TYPES.imageGenerator},source),
  video:c.normalizeExecutionSettings({type:c.NODE_TYPES.videoGenerator},source),
  audio:c.normalizeExecutionSettings({type:c.NODE_TYPES.audioGenerator},source),
  music:c.normalizeExecutionSettings({type:c.NODE_TYPES.musicGenerator},source),
  app:c.normalizeExecutionSettings({type:c.NODE_TYPES.aiApp},source)
}));
"""
        data = run_node(script)

        self.assertEqual(data["image"]["apiKind"], "image")
        self.assertEqual(data["video"]["apiKind"], "video")
        self.assertEqual(data["audio"]["apiKind"], "audio")
        self.assertEqual(data["music"]["apiKind"], "music")
        self.assertEqual(data["app"]["engine"], "runninghub")
        self.assertEqual(data["app"]["apiKind"], "image")

    def test_legacy_empty_nodes_migrate_by_runtime_kind(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const nodes=[
  {id:'image',type:'smart-image',images:[],runSettings:{engine:'api',apiKind:'image'}},
  {id:'video',type:'smart-image',images:[],runSettings:{engine:'api',apiKind:'video'}},
  {id:'audio',type:'smart-image',images:[],runSettings:{apiKind:'audio'}},
  {id:'music',type:'smart-image',images:[],runSettings:{apiKind:'music'}},
  {id:'app',type:'smart-image',images:[],runSettings:{engine:'runninghub',rhMode:'app',rhAppId:'123'}}
];
console.log(JSON.stringify(c.migrateLegacyCanvas(nodes,[]).nodes.map(node=>node.type)));
"""
        self.assertEqual(
            run_node(script),
            [
                "smart-image-generator",
                "smart-video-generator",
                "smart-audio-generator",
                "smart-music-generator",
                "smart-ai-app",
            ],
        )

    def test_generated_legacy_result_is_split_without_breaking_result_links(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const nodes=[
  {id:'prompt',type:'smart-prompt'},
  {id:'mixed',type:'smart-image',x:500,y:100,images:[{url:'/output/a.png',generatedResult:true}],runSettings:{engine:'api',apiKind:'image'},promptDraftTouched:true},
  {id:'next',type:'smart-image',images:[{url:'/assets/input/b.png'}]}
];
const connections=[
  {from:'prompt',to:'mixed',kind:'input'},
  {from:'mixed',to:'next',kind:'input'}
];
console.log(JSON.stringify(c.migrateLegacyCanvas(nodes,connections)));
"""
        migrated = run_node(script)
        by_id = {node["id"]: node for node in migrated["nodes"]}
        result_node = by_id["mixed"]
        execution = next(node for node in migrated["nodes"] if node["id"] != "mixed" and node["type"] == "smart-image-generator")

        self.assertEqual(result_node["type"], "smart-material")
        self.assertEqual(result_node["sourceKind"], "result")
        self.assertNotIn("runSettings", result_node)
        self.assertEqual(execution["runSettings"]["apiKind"], "image")
        self.assertTrue(any(item["from"] == "prompt" and item["to"] == execution["id"] for item in migrated["connections"]))
        self.assertTrue(any(item["from"] == execution["id"] and item["to"] == "mixed" and item["kind"] == "result" for item in migrated["connections"]))
        self.assertTrue(any(item["from"] == "mixed" and item["to"] == "next" for item in migrated["connections"]))

    def test_existing_special_nodes_are_not_rewritten(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const nodes=['smart-prompt','smart-loop','smart-group','smart-minimax'].map((type,index)=>({id:String(index),type}));
console.log(JSON.stringify(c.migrateLegacyCanvas(nodes,[]).nodes));
"""
        migrated = run_node(script)

        self.assertEqual([node["type"] for node in migrated], ["smart-prompt", "smart-loop", "smart-group", "smart-minimax"])

    def test_image_compare_tool_assigns_stable_left_and_right_inputs(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const material={id:'image',type:c.NODE_TYPES.material,images:[{kind:'image',url:'asset://image.png'}]};
const compare={id:'compare',type:c.NODE_TYPES.imageCompare,comparePosition:37};
const migrated=c.migrateLegacyCanvas([compare],[]);
console.log(JSON.stringify({
  type:c.NODE_TYPES.imageCompare,
  tool:c.isToolNode(compare),
  acceptsImage:c.canConnectNodes(material,compare),
  hasOutput:c.canConnectNodes(compare,material),
  slots:[
    c.imageCompareTargetSlot([],compare.id),
    c.imageCompareTargetSlot([{to:compare.id,targetFieldKey:'left'}],compare.id),
    c.imageCompareTargetSlot([{to:compare.id,targetFieldKey:'left'},{to:compare.id,targetFieldKey:'right'}],compare.id)
  ],
  migrated:migrated.nodes[0]
}));
"""
        data = run_node(script)

        self.assertEqual(data["type"], "smart-image-compare")
        self.assertTrue(data["tool"])
        self.assertTrue(data["acceptsImage"])
        self.assertFalse(data["hasOutput"])
        self.assertEqual(data["slots"], ["left", "right", ""])
        self.assertEqual(data["migrated"]["comparePosition"], 37)

    def test_image_compare_node_is_available_in_tool_menu_and_uses_left_right_labels(self):
        html = (ROOT / "static" / "smart-canvas.html").read_text(encoding="utf-8")
        source = (ROOT / "static" / "js" / "smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "css" / "smart-canvas.css").read_text(encoding="utf-8")
        i18n = (ROOT / "static" / "js" / "i18n" / "smart-canvas.js").read_text(encoding="utf-8")
        compare_layer = source[source.index("function imageCompareLayerHtml"):source.index("function imageCompareBodyHtml")]
        compare_body = source[source.index("function imageCompareBodyHtml"):source.index("function bindImageCompare")]

        tools_menu = html[html.index('<div class="create-menu-heading">工具节点</div>'):html.index('</div>\n            </div>\n        </div>\n        <input id="fileInput"')]
        self.assertIn('data-create-type="image-compare"', tools_menu)
        self.assertIn('data-i18n="smart.createImageCompare"', tools_menu)
        self.assertIn("function createImageCompareNode", source)
        self.assertIn("function imageCompareInputs", source)
        self.assertIn("function bindImageCompare", source)
        self.assertIn("data-image-compare-handle", source)
        self.assertIn("data-image-compare-original", compare_layer)
        self.assertIn("displayMediaUrl", compare_layer)
        self.assertNotIn("smartPreviewImgHtml", compare_layer)
        self.assertIn("stage.addEventListener('pointerdown'", source)
        self.assertIn("targetFieldKey:slot", source)
        self.assertIn(".image-compare-node", css)
        self.assertIn(".image-compare-handle", css)
        self.assertIn("background:rgba(255,255,255,.28)", css)
        self.assertNotIn("image-compare-grip", compare_body)
        self.assertNotIn(".image-compare-grip", css)
        self.assertIn(".preview-compare-handle::after { content:none;", css)
        self.assertIn("previewCompareGrabOffset", source)
        self.assertIn('"smart.compareLeft": { zh: "左侧", en: "Left" }', i18n)
        self.assertIn('"smart.compareRight": { zh: "右侧", en: "Right" }', i18n)
        self.assertNotIn("图一", compare_body)
        self.assertNotIn("图二", compare_body)

    def test_image_compare_stage_clicks_to_position_and_drags_from_anywhere(self):
        script = r"""
const fs=require('fs');
const source=fs.readFileSync('./static/js/smart-canvas.js','utf8');
const start=source.indexOf('function bindImageCompare');
const end=source.indexOf('function angleControlInputImage', start);
let saves=0;
global.scheduleSave=()=>{ saves += 1; };
eval(source.slice(start,end));

class FakeTarget {
  constructor(){
    this.listeners={};
    this.attrs={};
    this.style={values:{},setProperty:(name,value)=>{this.style.values[name]=value;}};
    this.capture=null;
  }
  addEventListener(type,listener){ (this.listeners[type] ||= []).push(listener); }
  dispatch(type,extra={}){
    const event={
      button:0, clientX:100, pointerId:7, key:'', shiftKey:false,
      currentTarget:this, target:this,
      preventDefault(){}, stopPropagation(){},
      ...extra
    };
    for(const listener of this.listeners[type] || []) listener(event);
  }
  getBoundingClientRect(){ return {left:100,width:400}; }
  setPointerCapture(id){ this.capture=id; }
  releasePointerCapture(id){ if(this.capture===id) this.capture=null; }
  setAttribute(name,value){ this.attrs[name]=value; }
}
const stage=new FakeTarget();
const handle=new FakeTarget();
const node={comparePosition:50};
const nodeEl={querySelector:selector=>selector.includes('stage') ? stage : handle};
bindImageCompare(nodeEl,node);
stage.dispatch('pointerdown',{clientX:200});
const afterClick=node.comparePosition;
stage.dispatch('pointermove',{clientX:420});
const afterDrag=node.comparePosition;
stage.dispatch('pointerup',{clientX:420});
console.log(JSON.stringify({
  afterClick,
  afterDrag,
  aria:handle.attrs['aria-valuenow'],
  css:stage.style.values['--image-compare-position'],
  capture:stage.capture,
  saves
}));
"""
        data = run_node(script)

        self.assertEqual(data, {
            "afterClick": 25,
            "afterDrag": 80,
            "aria": "80",
            "css": "80%",
            "capture": None,
            "saves": 1,
        })

    def test_canvas_list_uses_a_fresh_url_when_opening_smart_canvas(self):
        source = (ROOT / "static" / "js" / "canvas-list.js").read_text(encoding="utf-8")

        self.assertIn("v=${Date.now()}", source)
        self.assertNotIn("v=2026.07.03.4", source)

    def test_smart_canvas_loads_contract_before_main_script_and_exposes_new_menu(self):
        html = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")

        contract_index = html.index("/static/js/smart-node-contract.js")
        canvas_index = html.index("/static/js/smart-canvas.js")
        self.assertLess(contract_index, canvas_index)
        for node_type in ("material", "image-generator", "video-generator", "audio-generator", "music-generator", "ai-app", "comfy-workflow"):
            self.assertIn(f'data-create-type="{node_type}"', html)
        self.assertNotIn('data-create-type="image"', html)

    def test_create_menu_is_vertical_grouped_and_excludes_group_creation(self):
        html = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        menu = html[html.index('<div id="createMenu"'):html.index('<input id="fileInput"')]
        headings = ["添加资源", "常规节点", "应用与工作流", "工具节点"]
        self.assertEqual([menu.index(heading) for heading in headings], sorted(menu.index(heading) for heading in headings))
        regular_types = ["prompt", "image-generator", "video-generator", "audio-generator", "music-generator"]
        self.assertEqual(
            [menu.index(f'data-create-type="{node_type}"') for node_type in regular_types],
            sorted(menu.index(f'data-create-type="{node_type}"') for node_type in regular_types),
        )
        for label in ("文本生成", "图片生成", "视频生成", "音频生成", "音乐生成"):
            self.assertIn(label, menu)
        self.assertNotIn('data-create-type="group"', menu)
        create_menu_css = css[css.index(".create-menu {"):css.index(".node-head {")]
        self.assertIn(".create-menu-section", create_menu_css)
        self.assertIn(".create-menu-list", create_menu_css)
        self.assertIn(".create-card", create_menu_css)
        self.assertNotIn("grid-template-columns", create_menu_css)

    def test_music_generation_keeps_music_model_selection_and_endpoint_separate(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        html = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")

        self.assertIn("function renderApiMusicParams", source)
        self.assertIn("musicProvider", source)
        self.assertIn("musicFamilyId", source)
        self.assertIn("musicModel", source)
        self.assertIn("music_generation", source)
        self.assertIn("/api/canvas-music", source)
        self.assertIn('data-create-type="music-generator"', html)

    def test_blank_port_drop_opens_create_menu_and_connects_after_choice(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        port_drop = source[source.index("function handlePortDrop"):source.index("function pickMediaForSmartNode")]
        create_menu = source[source.index("function createNodeFromMenu"):source.index("shell.addEventListener('mousedown'")]

        self.assertNotIn("createImageNodeAt(p, [], {select:true, skipUndo:true})", port_drop)
        self.assertIn("createMenuConnection = {", port_drop)
        self.assertIn("openCreateMenu(e, {connection:createMenuConnection, keepOpenOnNextClick:true})", port_drop)
        self.assertIn("const pendingConnection = createMenuConnection", create_menu)
        self.assertIn("connectInputNodeWithTargetField(fromId, toId, {sourceResultId:pendingConnection.sourceResultId})", create_menu)
        self.assertIn("if(createMenuKeepOpenOnNextClick)", source)

    def test_create_menu_closes_on_any_pointer_outside_the_menu(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        handler = source[
            source.index("function closeCreateMenuOnOutsidePointer"):
            source.index("function closeMentionPickerOnOutsidePointer")
        ]
        self.assertIn("createMenu?.classList.contains('open')", handler)
        self.assertIn("event.target?.closest?.('.create-menu')", handler)
        self.assertIn("closeCreateMenu()", handler)
        self.assertIn("document.addEventListener('pointerdown', closeCreateMenuOnOutsidePointer, true)", handler)

    def test_model_family_and_run_mode_labels_follow_canvas_language(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        family_control = source[
            source.index("function capabilityFamilyLabel"):
            source.index("const SUNO_ACTION_INFO")
        ]
        self.assertIn("family?.display_name_en", family_control)
        self.assertIn("capabilityFamilyLabel(family)", family_control)
        variant_label = source[
            source.index("function capabilityVariantLabel"):
            source.index("function renderCapabilityVariantControl")
        ]
        self.assertIn("variant?.variant_name_en", variant_label)

    def test_video_picker_does_not_expose_input_purpose_as_model_parameter(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        start = source.index("function renderVideoInputModeControl")
        end = source.index("\nfunction optionHtml", start)
        control = source[start:end]
        self.assertIn("return '';", control)
        self.assertNotIn("图片用途", control)
        self.assertNotIn("data-video-input-mode", control)
        self.assertIn("function videoShouldUseFrameRoles", source)
        self.assertIn("videoShouldUseFrameRoles([...refImages", source)
        roles_start = source.index("function videoCapabilityInputRoles")
        roles_end = source.index("\nfunction capabilityInputCounts", roles_start)
        self.assertNotIn("videoUseFrameRoles", source[roles_start:roles_end])

    def test_text_material_toolbar_exposes_segment_registration_action(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        start = source.index("function smartNodeToolbarHtml(node)")
        end = source.index("function duplicateSmartNodeMediaToCanvas", start)
        toolbar = source[start:end]
        self.assertIn("key:'register-segment'", toolbar)
        self.assertIn("if(action === 'register-segment')", source)
        self.assertIn("CanvasProduction.registerSegments", source)

    def test_video_series_aliases_merge_vidu_kling_versions_and_pixverse_c1(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        identity_literal = capability_identity_expression(source)
        self.assertIn("reviewedVideoFamilies", source[source.index("function capabilitySelectionIdentity"):source.index("function resolveCapabilityFamilySelection")])
        data = run_node(f"""
const vm=require('node:vm');
const identity=vm.runInNewContext({identity_literal},{{window:{{}},modelCapabilityCatalog:{{options:[]}},isCanvasSettingsMode:false}});
const resolve=(model_id,family_name)=>identity({{provider_id:'runninghub',model_id,family_name}},'video_generation');
console.log(JSON.stringify({{
  viduA:resolve('Vidu-reference-to-video-q2-pro','Vidu'),
  viduB:resolve('vidu-text-to-video-q3-pro','Vidu Q3'),
  klingO1:resolve('kling-video-o1/text-to-video','可灵 O1'),
  klingO3:resolve('kling-video-o3-pro/text-to-video','可灵 O3'),
  pixverse:resolve('pixverse-v6/text-to-video','PixVerse'),
  pixverseC1:resolve('pixverse-c1/text-to-video','PixVerse C1')
}}));
""")
        for actual, expected in (("viduA", "viduB"), ("klingO1", "klingO3"), ("pixverse", "pixverseC1")):
            self.assertEqual(data[actual]["canonical_family_id"], data[expected]["canonical_family_id"])

    def test_model_id_repairs_only_incomplete_or_wrong_family_mappings(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        identity_literal = capability_identity_expression(source)
        data = run_node(f"""
const vm=require('vm');
const identity=vm.runInNewContext({identity_literal},{{window:{{}},modelCapabilityCatalog:{{options:[]}},isCanvasSettingsMode:false}});
const resolve=(model_id,family_name,node_type='image_generation')=>identity({{provider_id:'laohu',model_id,family_name}},node_type);
console.log(JSON.stringify({{
  jimeng:resolve('bytedance/jimeng-4.6/text-to-image','Seedream'),
  jimengCli:identity({{provider_id:'jimeng-cli',model_id:'5.0Pro',family_id:'jimeng-image-5.0-pro',family_name:'即梦图片 5.0 Pro'}},'image_generation'),
  banana:resolve('nano-banana-pro/text-to-image','全能图片 G'),
          grok:resolve('xai/grok-imagine-image/text-to-image','海螺'),
          laohuGptFlare:resolve('laohu-image-g-v2.5-flare','provider-local-image-g'),
          laohuGptLowprice:resolve('laohu-image-g-v2.5-lowprice','provider-local-image-g'),
          laohuGptSunburst:resolve('laohu-image-g-v2.5-sunburst','provider-local-image-g'),
          laohuGptI2i:resolve('laohu-image-g2-i2i','provider-local-image-g'),
          laohuGptT2i:resolve('laohu-image-g2-t2i','provider-local-image-g'),
          laohuGptLegacy:resolve('laohu-image-g-v2-lowprice','provider-local-image-g'),
          laohuGrok:resolve('laohu-image-gk-v2-edit','provider-local-image-g'),
          laohuUnreviewed:resolve('laohu-image-g-v9-alpha','provider-local-image-g'),
          qwen:resolve('Qwen/Qwen-Image-2512','Qwen Image'),
  hailuo:resolve('hailuo-h3-global-i2v','MiniMax H3','video_generation'),
  minimax:resolve('minimax-h3-ow-i2v','MiniMax H3','video_generation'),
  horse:resolve('happyhorse-1.1-t2v','HappyHorse','video_generation'),
  grokVideo:resolve('xai/grok-imagine-video-v1.5/text-to-video','MiniMax','video_generation')
}}));
""")
        expected = {
            "jimeng": "series-image-seedream",
            "jimengCli": "series-image-seedream",
            "banana": "series-image-nano-banana",
            "grok": "series-image-grok-image",
            "laohuGptFlare": "series-image-gpt-image",
            "laohuGptLowprice": "series-image-gpt-image",
            "laohuGptSunburst": "series-image-gpt-image",
            "laohuGptI2i": "series-image-gpt-image",
            "laohuGptT2i": "series-image-gpt-image",
            "laohuGptLegacy": "series-image-gpt-image",
            "laohuGrok": "series-image-grok-image",
            "qwen": "series-image-qwen-image",
            "hailuo": "series-video-minimax",
            "minimax": "series-video-minimax",
            "horse": "series-video-happyhorse",
            "grokVideo": "series-video-grok",
        }
        for key, family_id in expected.items():
            self.assertEqual(data[key]["canonical_family_id"], family_id, key)
        self.assertNotIn(data["laohuUnreviewed"]["canonical_family_id"], {
            "series-image-gpt-image", "series-image-grok-image"
        })

    def test_canvas_picker_uses_reviewed_identity_before_provider_family(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        block = capability_identity_expression(source)
        script = f"""
const vm=require('vm');
const options=[
 {{capability_provider_id:'runninghub',catalog_model_id:'xai/rhart-imagine-image-quality/text-to-image-official-stable',node_type:'image_generation',operation:'text_to_image',canonical_family_id:'series-image-grok-image',canonical_family_label:{{zh:'Grok Image',en:'Grok Image'}},display_mode:'高质量 · 文生图'}},
 {{capability_provider_id:'runninghub',catalog_model_id:'Luma uni-1-max Text to Image',node_type:'image_generation',operation:'text_to_image',canonical_family_id:'series-image-luma',canonical_family_label:{{zh:'Luma',en:'Luma'}},display_mode:'Uni-1 · Max · 文生图'}},
 {{capability_provider_id:'ai-money',catalog_model_id:'laohu-image-nb-pro',node_type:'image_generation',operation:'text_to_image',canonical_family_id:'series-image-nano-banana',canonical_family_label:{{zh:'Nano Banana',en:'Nano Banana'}},display_mode:'Pro · 文生图'}},
 {{capability_provider_id:'ai-money',catalog_model_id:'laohu-image-g-v2.5-flare',node_type:'image_generation',operation:'text_to_image',canonical_family_id:'series-image-grok-image',canonical_family_label:{{zh:'Grok Image',en:'Grok Image'}},display_mode:'文生图'}},
 {{capability_provider_id:'jimeng-cli',catalog_model_id:'5.0Pro',node_type:'image_generation',operation:'text_to_image_or_image_to_image',canonical_family_id:'series-image-seedream',canonical_family_label:{{zh:'Seedream',en:'Seedream'}},display_mode:'5.0 · Pro · 文生图／图生图'}}
];
const identity=vm.runInNewContext({block},{{window:{{}},modelCapabilityCatalog:{{options}},isCanvasSettingsMode:false}});
console.log(JSON.stringify([
 identity({{provider_id:'runninghub',model_id:options[0].catalog_model_id,family_name:'全能图片X 高质量',operation:'text_to_image'}},'image_generation'),
 identity({{provider_id:'runninghub',model_id:options[1].catalog_model_id,family_name:'Luma Uni max',operation:'text_to_image'}},'image_generation'),
 identity({{provider_id:'ai-money',model_id:options[2].catalog_model_id,family_name:'Nano Banana Pro',operation:'text_to_image'}},'image_generation'),
 identity({{provider_id:'ai-money',model_id:options[3].catalog_model_id,family_name:'Grok Image',operation:'text_to_image'}},'image_generation'),
 identity({{provider_id:'jimeng',model_id:options[4].catalog_model_id,family_name:'即梦图片 Pro',operation:'text_to_image_or_image_to_image'}},'image_generation')
]));
"""
        result = run_node(script)
        self.assertEqual([item["canonical_family_id"] for item in result], [
            "series-image-grok-image", "series-image-luma", "series-image-nano-banana",
            "series-image-gpt-image", "series-image-seedream",
        ])
        self.assertEqual(result[-1]["display_mode"], "5.0 · Pro · 文生图／图生图")

    def test_mixed_image_mode_remains_available_with_and_without_reference(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        block = source[source.index("function capabilityProfileMatchesCurrentInput"):source.index("function capabilityProfileVisibleInPicker")]
        script = f"""
const vm=require('vm');
const matches=vm.runInNewContext('('+{json.dumps(block)}+')');
const mixed={{node_type:'image_generation',operation:'text_to_image_or_image_to_image'}};
const imageOnly={{node_type:'image_generation',operation:'image_to_image'}};
console.log(JSON.stringify([matches(mixed,'image_generation',{{image:0}}),matches(mixed,'image_generation',{{image:1}}),matches(imageOnly,'image_generation',{{image:0}})]));
"""
        self.assertEqual(run_node(script), [True, True, False])

    def test_jimeng_seedream_identity_modes_are_concise_and_keep_mixed_input(self):
        identities = json.loads((ROOT / "data/model_capabilities/model-identities.json").read_text(encoding="utf-8"))
        bindings = [item for item in identities["bindings"] if (
            item["match"].get("capability_provider_id") == "jimeng-cli"
            and item["match"].get("node_type") == "image_generation"
        )]
        self.assertTrue(bindings)
        self.assertTrue(all(item["canonical_family_id"] == "series-image-seedream" for item in bindings))
        by_model = {item["match"]["model_id"]:item["display_mode"] for item in bindings}
        self.assertEqual(by_model["5.0Pro"], "5.0 · Pro · 文生图／图生图")
        self.assertEqual(by_model["5.0"], "5.0 · 文生图／图生图")
        self.assertNotIn("5.0 · Pro · 图生图 / 5.0 · Pro · 文生图", by_model.values())

    def test_text_model_aliases_are_grouped_into_the_nine_requested_families(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        identity_literal = capability_identity_expression(source)
        script = f"""
const vm=require('vm');
const identity=vm.runInNewContext({identity_literal},{{window:{{}},modelCapabilityCatalog:{{options:[]}},isCanvasSettingsMode:false}});
const resolve=(model_id,family_name)=>identity({{provider_id:'ai-money',model_id,family_name}},'text_generation');
console.log(JSON.stringify({{
  g5:resolve('laohu/g5.6-sol','provider-local-g5'),
  g6:resolve('laohu/g6-astra','provider-local-g6'),
  gk:resolve('laohu/gk-4.6','provider-local-gk'),
  gm:resolve('laohu/gm-3.8-flash','provider-local-gm'),
  doubao:resolve('bytedance/doubao-seed-2.1-pro','provider-local-doubao'),
  minimax:resolve('minmax-h3-context-ir-text','provider-local-minmax'),
  kimi:resolve('moonshotai/kimi-k3','provider-local-kimi'),
  qwen:resolve('Qwen/Qwen3.8-Max','provider-local-qwen'),
  glm:resolve('glm-5.3-flash','provider-local-glm'),
  deepseek:resolve('deepseek/deepseek-v4.1-flash','provider-local-deepseek')
}}));
"""
        result = run_node(script)
        expected = {
            "g5": "series-text-gpt", "g6": "series-text-gpt", "gk": "series-text-grok",
            "gm": "series-text-gemini", "doubao": "series-text-doubao-seed",
            "minimax": "series-text-minimax", "kimi": "series-text-kimi",
            "qwen": "series-text-qwen", "glm": "series-text-glm", "deepseek": "series-text-deepseek",
        }
        for key, family_id in expected.items():
            self.assertEqual(result[key]["canonical_family_id"], family_id, key)

    def test_text_alias_mode_labels_keep_versions_without_alias_fragments(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        block = source[source.index("function capabilityVariantLabel"):source.index("function renderCapabilityVariantControl")]
        result = run_node(f"""
const vm=require('vm');
const context={{window:{{StudioI18n:{{lang:()=> 'zh'}}}},capabilityUiText:(zh,en)=>zh}};
const label=vm.runInNewContext('('+{json.dumps(block)}+')',context);
console.log(JSON.stringify(['laohu/g5.6-sol','laohu/g6-astra','laohu/gk-4.6','laohu/gm-3.8-flash'].map(model_id=>label({{node_type:'text_generation',model_id}}))));
""")
        self.assertEqual(result, ["5.6 · Sol", "6 · Astra", "4.6", "3.8 · Flash"])

    def test_text_picker_excludes_specialized_tools(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        block = source[source.index("function capabilityProfileMatchesCurrentInput"):source.index("function capabilityProfileVisibleInPicker")]
        script = f"""
const vm=require('vm');
const matches=vm.runInNewContext('('+{json.dumps(block)}+')');
console.log(JSON.stringify([
  matches({{operation:'chat'}},'text_generation',{{text:1}}),
  matches({{operation:'multimodal_chat'}},'text_generation',{{text:1,image:1}}),
  matches({{operation:'prompt_enhancement'}},'text_generation',{{text:1}}),
  matches({{operation:'image_description'}},'text_generation',{{text:1}}),
  matches({{operation:'transcription'}},'text_generation',{{text:1}}),
  matches({{operation:'text_to_3d'}},'text_generation',{{text:1}})
]));
"""
        self.assertEqual(run_node(script), [True, True, True, False, False, False])

    def test_management_picker_ignores_inputs_while_formal_picker_keeps_required_reference_gate(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        start = source.index("function capabilityProfileMatchesCurrentInput")
        middle = source.index("function capabilityProfileVisibleInPicker")
        end = source.index("function resolveCapabilityFamilyPickerSelection")
        helpers = source[start:middle] + source[middle:end]
        script = f"""
const vm=require('vm');
const context={{
  isCanvasSettingsMode:true,
  capabilityProviderEnabled:()=>true,
  managementOptionForProfile:profile=>profile.option_id==='fixture-required-reference'?profile:null
}};
const visible=vm.runInNewContext('(()=>{{'+{json.dumps(helpers)}+';return capabilityProfileVisibleInPicker;}})()',context);
const profile={{option_id:'fixture-required-reference',node_type:'image_generation',operation:'image_to_image',inputs:{{reference:{{media_type:'image',role:'reference',min:1}}}}}};
const managerWithoutInput=visible(profile,'image_generation',{{image:0}});
const managerWithWrongInput=visible(profile,'image_generation',{{audio:1,image:0}});
context.isCanvasSettingsMode=false;
const formalWithoutInput=visible(profile,'image_generation',{{image:0}});
const formalWithReference=visible(profile,'image_generation',{{image:1}});
context.isCanvasSettingsMode=true;
context.managementOptionForProfile=()=>null;
const managerWithoutStrictOption=visible(profile,'image_generation',{{image:0}});
console.log(JSON.stringify([managerWithoutInput,managerWithWrongInput,formalWithoutInput,formalWithReference,managerWithoutStrictOption]));
"""
        self.assertEqual(run_node(script), [True, True, False, True, False])

    def test_result_connections_have_dedicated_layout_and_visual_semantics(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("SMART_NODE_CONTRACT.isOutputLayoutConnection(conn)", source)
        self.assertIn("isResult ? 'conn-result'", source)

    def test_execution_nodes_hide_the_image_video_kind_toggle(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        html = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")

        self.assertIn("const fixedExecutionKind = isSmartExecutionNode(subject);", source)
        self.assertIn("!fixedExecutionKind && isApiLikeEngine(settings.engine)", source)
        self.assertNotIn('id="engineSelect"', html)
        self.assertNotIn("engineSelect.onchange", source)

    def test_creation_nodes_render_resize_handles(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("const canResize = !isAngle", source)

    def test_group_is_organization_only_and_arranges_on_explicit_action(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        runnable = source[source.index("function isSmartRunnableNode"):source.index("function normalizeSmartMediaReference")]
        grouping = source[source.index("function groupSelectedNodes"):source.index("function ungroupNode")]
        self.assertNotIn("isSmartGroupNode(node)", runnable)
        self.assertNotIn("arrangeSmartGroupMembers(group", grouping)
        self.assertIn("data-smart-group-action=\"${escapeAttr(action.key)}\"", source)
        arrange = source[source.index("function arrangeSmartGroupMembers"):source.index("function mediaLayoutSize")]
        self.assertNotIn("partitionSmartGroupMembers", arrange)
        self.assertIn("resizeSmartGroupMember", arrange)
        self.assertIn("mode === 'vertical'", arrange)
        self.assertIn("mode === 'horizontal'", arrange)
        self.assertIn("group.arrangeMode = mode", arrange)
        group_double_click = source[source.index("if(nodeForControls?.type === 'smart-group') el.ondblclick"):source.index("el.onclick = e =>")]
        self.assertNotIn("openCreateMenu", group_double_click)

    def test_group_and_single_image_expose_distinct_grid_actions(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        node_toolbar = source[source.index("function smartNodeToolbarHtml"):source.index("function duplicateSmartNodeMediaToCanvas")]
        group_toolbar = source[source.index("function smartGroupToolbarHtml"):source.index("function runSmartGroupToolbarAction")]
        group_action = source[source.index("function runSmartGroupToolbarAction"):source.index("function nowMs")]

        self.assertIn("label:capabilityUiText('图片宫格切分','Split grid')", node_toolbar)
        self.assertNotIn("宫格拼接", node_toolbar)
        for label in ("预览", "收藏到资产素材", "图片宫格拼接", "下载", "整理排版"):
            self.assertIn(f"label:'{label}'", group_toolbar)
        for label in ("整理排列", "解散分组"):
            self.assertNotIn(f"label:'{label}'", group_toolbar)
        self.assertIn("const imageRefs = smartGroupImageRefs(node)", group_toolbar)
        self.assertIn("(group.images || []).forEach((img, index) => {", source)
        self.assertIn("openGroupGridJoin(group)", group_action)

    def test_material_toolbar_routes_preview_and_trim_by_media_type(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        toolbar = source[source.index("function smartNodeToolbarHtml"):source.index("function duplicateSmartNodeMediaToCanvas")]
        action = source[source.index("async function runSmartNodeToolbarAction"):source.index("async function promoteSmartMaterial")]

        self.assertIn("enabled:true", toolbar)
        self.assertIn("const canTrimMedia = ['image','video','audio'].includes(kind)", toolbar)
        self.assertIn("openSmartMaterialPreview(nodeId, index)", action)
        self.assertIn("if(action === 'crop' && kind === 'audio')", action)
        self.assertIn("openAudioMaterialPreview(nodeId, index)", action)
        self.assertIn("if(action === 'crop' && kind === 'video')", action)
        self.assertIn("openImageEditor(nodeId, index)", action)

    def test_group_arrange_menu_is_anchored_to_button_and_above_members(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        toolbar = source[source.index("function smartGroupToolbarHtml"):source.index("async function runSmartGroupToolbarAction")]
        self.assertIn("smart-group-arrange-control", toolbar)
        self.assertIn("arrange-menu-open", source)
        self.assertIn(".smart-group-arrange-control", css)
        self.assertIn(".smart-group-node.arrange-menu-open", css)
        self.assertIn("z-index:120", css)

    def test_group_dragging_uses_reversible_intersection_preview(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        target = source[source.index("function smartGroupTargetForDraggedNode"):source.index("function addDraggedNodeToSmartGroup")]
        drag_move = source[source.index("if(!dragState) return;"):source.index("window.onmouseup = e =>")]
        drag_end_start = source.index("if(dragState){", source.index("window.onmouseup = e =>"))
        drag_end = source[drag_end_start:source.index("shell.addEventListener('wheel'", drag_end_start)]

        self.assertIn("rectsIntersect", target)
        self.assertIn("expandRect(nodeRect(group), SMART_GROUP_ARRANGE_PADDING)", target)
        self.assertNotIn("const cx =", target)
        self.assertIn("updateSmartGroupDropPreview", drag_move)
        self.assertIn("clearSmartGroupDropPreview", drag_end)
        group_target = drag_end[drag_end.index("const groupTarget ="):drag_end.index("const draggedNodes =")]
        self.assertNotIn("(draggedNode.images || []).length", group_target)

    def test_group_members_leave_only_after_full_exit_and_restore_layout(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        prune = source[source.index("function pruneSmartGroupMembershipsForNode"):source.index("function clearDropHighlight")]

        self.assertIn("rectContainsRect", prune)
        self.assertIn("restoreSmartGroupMemberOriginalLayout", prune)
        self.assertIn("fitSmartGroupBounds", prune)

    def test_execution_node_shell_has_no_generic_body_spacing(self):
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn(".image-node.smart-execution-node .node-head", css)
        self.assertIn(".image-node.smart-execution-node .node-hint", css)
        self.assertIn(".image-node.smart-execution-node .node-body", css)
        self.assertIn("min-height:0", css)
        self.assertIn("padding:0", css)

    def test_grid_outputs_are_persisted_as_generation_results(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        backend = (ROOT / "main.py").read_text(encoding="utf-8")
        grid = source[source.index("async function uploadCroppedBlob"):source.index("async function applyImageResize")]

        self.assertIn("/api/canvas-media-results", grid)
        self.assertIn("sourceKind:'result'", grid)
        self.assertIn("addConnection(node.id, outputNode.id, 'result')", grid)
        self.assertIn("addConnection(sourceNode.id, outputNode.id, 'result')", grid)
        self.assertIn('@app.post("/api/canvas-media-results")', backend)
        self.assertIn("PROJECT_STORAGE.store_result_file", backend)

    def test_image_edits_create_result_nodes_without_replacing_source(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        editing_start = source.index("function createEditedResultNode")
        editing = source[editing_start:source.index("function applyImageEdit()", editing_start)]

        self.assertIn("createImageNodeAt", editing)
        self.assertIn("addConnection(sourceNode.id, outputNode.id, 'result')", editing)
        self.assertNotIn("function replaceEditedImage", source)
        self.assertNotIn("node.images[index] =", editing)

    def test_grid_presets_are_draggable_and_join_supports_empty_slots(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("function beginPresetGridLineDrag", source)
        self.assertIn("gridCustomLines = gridPresetLines()", source)
        self.assertIn("function gridJoinDropSlot", source)
        self.assertIn("dragged.x = slot.x", source)

    def test_group_resize_changes_only_the_container(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        resize_block = source[source.index("if(resizeState){"):source.index("if(llmInstructionResizeState){")]

        self.assertNotIn("resizeState.members", source)
        self.assertNotIn("smartGroupZoom", source)
        self.assertNotIn("member.w =", resize_block)
        self.assertNotIn("member.h =", resize_block)
        self.assertIn("node.w = Math.max(minW, Math.round(resizeState.startW + dx));", resize_block)
        self.assertIn("node.h = Math.max(minH, Math.round(resizeState.startH + dy));", resize_block)

    def test_workflow_export_defaults_to_the_whole_canvas(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        payload = source[source.index("function selectedSmartWorkflowPayload"):source.index("function normalizeImportedSmartWorkflow")]
        export = source[source.index("async function exportSelectedSmartWorkflow"):source.index("function insertSmartWorkflowIntoCanvas")]
        self.assertIn("const ids = selectedNodeIds();", payload)
        self.assertIn("const exportNodes = ids.length", payload)
        self.assertIn("nodes.map(serializableSmartNode)", payload)
        self.assertNotIn("未选择节点，请先选中要导出的组件", export)

    def test_top_right_panels_are_mutually_exclusive(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        html = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn("function closeSmartTopPanels", source)
        self.assertIn("function toggleSmartCanvasShortcuts", source)
        self.assertIn("function toggleSmartCanvasLog", source)
        self.assertIn("closeSmartTopPanels('workflow')", source)
        self.assertIn("closeSmartTopPanels('shortcuts')", source)
        self.assertIn("closeSmartTopPanels('logs')", source)
        self.assertIn("closeSmartTopPanels('assets')", source)
        self.assertIn('onclick="toggleSmartCanvasShortcuts()"', html)
        self.assertIn('onclick="toggleSmartCanvasLog()"', html)
        self.assertIn("z-index:90", css)

    def test_asset_panel_separates_inputs_workflows_and_results(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        html = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")

        self.assertIn('data-asset-tab="image"', html)
        self.assertIn('data-asset-tab="workflow"', html)
        self.assertIn('data-asset-tab="result"', html)
        self.assertIn("画布工作流", html)
        self.assertIn("生成结果", html)

        load_block = source[
            source.index("async function loadAssetLibrary"):
            source.index("function refreshAssetLibrarySoon")
        ]
        self.assertIn("Promise.allSettled([", load_block)
        self.assertIn("fetch('/api/asset-library'", load_block)
        self.assertIn("fetch('/api/local-assets'", load_block)
        self.assertIn("fetch('/api/results?kind=all'", load_block)
        self.assertIn("setAssetLibraryFromResponse(libraryResult.value", load_block)
        self.assertIn("localAssetLibrary={items:Array.isArray(localResult.value.items)", load_block)
        self.assertIn("generationResults={", load_block)
        self.assertIn("items:Array.isArray(resultResult.value.items)", load_block)
        self.assertIn("canvases:Array.isArray(resultResult.value.canvases)", load_block)

        workflow_library = source[
            source.index("function workflowAssetLibraries"):
            source.index("function assetLibraries")
        ]
        self.assertIn("assetLibraries().filter", workflow_library)
        self.assertIn("cat.type || 'image') === 'workflow'", workflow_library)
        workflow_loader = source[
            source.index("async function loadConfigAuxiliary"):
            source.index("async function refreshSmartConfigFromSettings")
        ]
        self.assertIn("fetch('/api/workflows'", workflow_loader)
        self.assertIn("comfyWorkflows=workflowsResult.value.workflows", workflow_loader)

        render_block = source[
            source.index("function renderAssetLibrary"):
            source.index("function bindResultAssetItemEvents", source.index("function renderAssetLibrary"))
        ]
        self.assertIn("const imageMode = assetTab === 'image'", render_block)
        self.assertIn("const workflowMode = assetTab === 'workflow'", render_block)
        self.assertIn("const resultMode = assetTab === 'result'", render_block)
        self.assertIn("(generationResults.items || []).forEach", render_block)
        self.assertIn('data-source-kind="result"', render_block)

    def test_workflow_library_mutations_use_the_workflow_library_id(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        add_start = source.index("if(assetAddCategoryBtn) assetAddCategoryBtn.onclick")
        add_handler = source[add_start:source.index("if(assetRenameCategoryBtn) assetRenameCategoryBtn.onclick", add_start)]
        self.assertIn("const libraryId = workflowMode ? activeWorkflowAssetLibraryId : activeAssetLibraryId", add_handler)
        self.assertIn("library_id:libraryId", add_handler)

    def test_shortcuts_show_windows_and_mac_columns(self):
        html = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")

        self.assertIn("Windows", html)
        self.assertIn("Mac", html)
        self.assertIn("Ctrl</kbd><kbd>Shift</kbd><kbd>C", html)
        self.assertIn("Cmd</kbd><kbd>Shift</kbd><kbd>C", html)
        self.assertIn("鼠标位于节点上时拖出连线", html)

    def test_log_errors_have_an_explicit_copy_affordance(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn("点击复制错误信息", source)
        self.assertIn("data-copy-error", source)
        self.assertIn(".log-error-copy-hint", css)

    def test_material_double_click_previews_all_media_and_execution_focuses(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("function openSmartMaterialPreview", source)
        preview = source[source.index("function openSmartMaterialPreview"):source.index("function focusSmartNodeInViewport")]
        self.assertIn("openAudioMaterialPreview(nodeId, imageIndex)", preview)
        self.assertIn("function focusSmartNodeInViewport", source)
        self.assertIn("if(isSmartExecutionNode(nodeForControls))", source)
        self.assertIn("openSmartMaterialPreview(target.targetNodeId, target.imageIndex", source)

    def test_shift_double_click_focuses_every_node_and_keeps_open_overlays_in_view(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        html = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        i18n = (ROOT / "static/js/i18n/smart-canvas.js").read_text(encoding="utf-8")
        focus = source[source.index("function smartNodeFocusBounds"):source.index("function ensureSmartTextEditorModal")]
        binding = source[source.index("function bindNodeEvents"):source.index("function deleteNode")]

        self.assertIn("if(!event.shiftKey) return", binding)
        self.assertIn("focusSmartNodeInViewport(id)", binding)
        self.assertIn("event.stopImmediatePropagation()", binding)
        self.assertIn("function handleSmartNodeShiftDoubleClick", source)
        self.assertIn("world.addEventListener('dblclick', handleSmartNodeShiftDoubleClick, true)", source)
        self.assertIn("const nodeEl = event.target?.closest?.('.image-node')", source)
        self.assertIn("nodeEl?.querySelectorAll('.node-head,.result-version-switcher,.smart-node-floating-menu,.smart-popover", focus)
        self.assertIn("[data-smart-node-id=", focus)
        self.assertIn("const targetScale = Math.max(0.35", focus)
        self.assertIn("cubic-bezier(.22,1,.36,1)", css)
        self.assertIn('data-i18n="smart.shortcutFocusNode"', html)
        self.assertIn('"smart.shortcutFocusNode": { zh: "聚焦并放大任意画布节点", en: "Center and enlarge any canvas node" }', i18n)
        shift_drag = html.index('鼠标位于节点上时拖出连线')
        shift_focus = html.index('data-i18n="smart.shortcutFocusNode"')
        plain_double_click = html.index('预览素材、聚焦执行节点或在空白处打开快捷菜单')
        self.assertLess(shift_drag, shift_focus)
        self.assertLess(shift_focus, plain_double_click)

    def test_audio_preview_exposes_playback_controls_and_metadata(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        i18n = (ROOT / "static/js/i18n/smart-canvas.js").read_text(encoding="utf-8")

        modal = source[source.index("function ensureSmartAudioPreviewModal"):source.index("function mediaTransformValues")]
        self.assertIn("data-audio-preview-mute", modal)
        self.assertIn("data-audio-preview-volume", modal)
        self.assertIn("data-audio-preview-speed", modal)
        self.assertIn("data-audio-preview-loop", modal)
        self.assertIn("data-audio-preview-meta", modal)
        self.assertIn("audio.muted", modal)
        self.assertIn("audio.volume", modal)
        self.assertIn("audio.playbackRate", modal)
        self.assertIn("audio.loop", modal)
        self.assertIn("loadedmetadata", modal)
        self.assertIn("volumechange", modal)
        self.assertIn("ratechange", modal)
        self.assertIn("audio-preview-controls", css)
        self.assertIn("smart.audioPreviewMute", i18n)
        self.assertIn("smart.audioPreviewSpeed", i18n)
        self.assertIn("smart.audioPreviewLoop", i18n)
        self.assertIn("smart.audioPreviewDuration", i18n)
        self.assertIn("smart.audioPreviewFormat", i18n)

    def test_text_materials_resize_preview_edit_inline_and_hide_finished_timer(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn('data-text-preview="1"', source)
        self.assertIn("function beginSmartInlineTextEdit", source)
        self.assertIn("function finishSmartInlineTextEdit", source)
        self.assertIn("document.addEventListener('pointerdown', closeSmartInlineTextEditOnOutsidePointer, true)", source)
        self.assertIn("nodeForControls?.type === SMART_NODE_TYPES.material", source)
        self.assertIn("event.preventDefault();\n                event.stopPropagation();\n                beginSmartInlineTextEdit(id, 0);", source)
        self.assertIn("if(!running) return '';", source)
        self.assertIn(".media-text-preview.is-inline-editing", css)
        self.assertIn(".media-text-inline-editor", css)
        self.assertIn("creation-text-columns", source)
        self.assertIn(".media-text-inline-editor')) return", source)
        self.assertIn("justify-content:flex-start", css)

    def test_media_transform_checks_environment_before_enabling_actions(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        html = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn("/api/canvas-media-capabilities", source)
        self.assertIn("function loadSmartMediaToolCapabilities", source)
        self.assertIn("function applySmartMediaToolCapabilities", source)
        self.assertIn("data-media-transform-capability", source)
        self.assertIn("data-media-transform-action", html)
        self.assertIn(".media-transform-capability.is-unavailable", css)
        transform = source[source.index("async function runSmartMediaTransform"):source.index("function openAudioMaterialPreview")]
        self.assertIn("await loadSmartMediaToolCapabilities()", transform)
        self.assertIn("if(!capabilities.media_transform)", transform)
        video = source[source.index("function openImageEditor"):source.index("function closeImageEditor")]
        self.assertIn("loadSmartMediaToolCapabilities().then", video)

    def test_inline_video_control_hides_after_play_then_shows_pause_on_fresh_hover(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        polish = (ROOT / "static/css/studio-ui-polish.css").read_text(encoding="utf-8")

        self.assertIn("function bindSmartInlineVideoControls", source)
        self.assertIn("function toggleSmartInlineVideoPlayback", source)
        self.assertIn("bindSmartInlineVideoControls(video, image)", source)
        self.assertIn("btn.dataset.smartVideoPlayBound", source)
        self.assertIn("video.addEventListener('play'", source)
        self.assertIn("video.addEventListener('pause'", source)
        self.assertIn("card.addEventListener('mouseenter'", source)
        self.assertIn("card.addEventListener('mouseleave'", source)
        self.assertIn("is-control-suppressed", source)
        self.assertIn("video[data-inline-video-active=\"1\"]", source)
        self.assertIn("smartVideoPlayerHtml", source)
        self.assertIn(".media-video-card.is-playing.is-control-suppressed .smart-video-play", css)
        self.assertIn(".media-video-card.is-playing:not(.is-control-suppressed):hover .smart-video-play", css)
        self.assertIn(".smart-video-play.is-playing::before", css)
        self.assertIn(":not(.smart-video-play)", polish)
        self.assertIn(":not(.image-compare-handle)", polish)
        self.assertIn(":not(.preview-nav-btn)", polish)
        self.assertIn(":not(.node-port)", polish)

    def test_inline_video_controls_rebind_after_media_dom_transplant(self):
        script = r"""
const fs=require('fs');
const source=fs.readFileSync('./static/js/smart-canvas.js','utf8');
const start=source.indexOf('function bindSmartInlineVideoControls');
const end=source.indexOf('function toggleSmartInlineVideoPlayback', start);
eval(source.slice(start,end));

class FakeClassList {
  constructor(){ this.values=new Set(); }
  toggle(name,on){ if(on) this.values.add(name); else this.values.delete(name); }
  add(name){ this.values.add(name); }
  remove(name){ this.values.delete(name); }
  contains(name){ return this.values.has(name); }
}
class FakeTarget {
  constructor(){ this.dataset={}; this.classList=new FakeClassList(); this.listeners={}; }
  addEventListener(type,listener){ (this.listeners[type] ||= []).push(listener); }
  dispatch(type){ for(const listener of this.listeners[type] || []) listener({currentTarget:this}); }
}
function makeCard(){
  const card=new FakeTarget();
  const button=new FakeTarget();
  button.setAttribute=(name,value)=>{ button[name]=value; };
  card.button=button;
  card.querySelector=selector=>selector === '.smart-video-play' ? button : null;
  return card;
}
const oldCard=makeCard();
const newCard=makeCard();
let currentCard=oldCard;
const video=new FakeTarget();
video.paused=true;
video.ended=false;
video.closest=()=>currentCard;
video.parentElement=currentCard;
global.toast=()=>{};

bindSmartInlineVideoControls(video,null);
video.paused=false;
video.dispatch('play');
currentCard=newCard;
video.parentElement=newCard;
bindSmartInlineVideoControls(video,null);
const suppressedImmediatelyAfterTransplant=newCard.classList.contains('is-control-suppressed');
newCard.dispatch('mouseenter');
const suppressedAfterTransplantEnter=newCard.classList.contains('is-control-suppressed');
newCard.dispatch('mouseleave');
const suppressedAfterRealLeave=newCard.classList.contains('is-control-suppressed');
newCard.dispatch('mouseenter');
const playingAfterTransplant={
  card:newCard.classList.contains('is-playing'),
  button:newCard.button.classList.contains('is-playing'),
  suppressed:newCard.classList.contains('is-control-suppressed'),
  hoverBound:newCard.dataset.smartInlineHoverBound === '1'
};
video.paused=true;
video.dispatch('pause');
console.log(JSON.stringify({
  suppressedImmediatelyAfterTransplant,
  suppressedAfterTransplantEnter,
  suppressedAfterRealLeave,
  playingAfterTransplant,
  pausedAfterTransplant:{
    card:newCard.classList.contains('is-playing'),
    button:newCard.button.classList.contains('is-playing'),
    suppressed:newCard.classList.contains('is-control-suppressed'),
    title:newCard.button.title
  }
}));
"""
        data = run_node(script)

        self.assertTrue(data["suppressedImmediatelyAfterTransplant"])
        self.assertTrue(data["suppressedAfterTransplantEnter"])
        self.assertTrue(data["suppressedAfterRealLeave"])
        self.assertEqual(data["playingAfterTransplant"], {
            "card": True,
            "button": True,
            "suppressed": False,
            "hoverBound": True,
        })
        self.assertEqual(data["pausedAfterTransplant"], {
            "card": False,
            "button": False,
            "suppressed": False,
            "title": "播放",
        })

    def test_group_renders_four_corner_resize_handles(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("data-resize-corner=\"nw\"", source)
        self.assertIn("data-resize-corner=\"ne\"", source)
        self.assertIn("data-resize-corner=\"sw\"", source)
        self.assertIn("data-resize-corner=\"se\"", source)

    def test_shift_drag_can_start_from_hovered_node_without_selection(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("function beginNodeConnectionDrag(event, sourceNodeId='')", source)
        self.assertIn("const sourceIsSelected = selected.includes(sourceNodeId)", source)
        self.assertIn("const fromIds = sourceIsSelected ? selected : [sourceNodeId]", source)
        self.assertIn("function beginShiftConnectionFromPointer(event)", source)
        self.assertIn("const hit = connectionNodeHitAtPoint(event.clientX, event.clientY, event.target)", source)
        self.assertIn("shell.addEventListener('mousedown', beginShiftConnectionFromPointer, true)", source)
        self.assertIn("if(![0,2].includes(event.button) || !event.shiftKey) return false", source)
        self.assertIn("if(!hit.nodeId) return false", source)
        self.assertIn("if(event.button===0&&event.target?.closest?.('.node-port')) return false", source)
        self.assertIn("if(e.button === 0 && e.shiftKey)", source)

    def test_shift_left_double_click_wins_over_connection_drag(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        handler = source[source.index("function beginShiftConnectionFromPointer"):source.index("shell.addEventListener('mousedown', beginShiftConnectionFromPointer")]
        finish = source[source.index("function finishPortDragPointer"):source.index("window.addEventListener('mousemove', handlePortDragPointerMove")]

        self.assertIn("let shiftNodeClickCandidate = null", source)
        self.assertIn("let lastShiftConnectionDragAt = 0", source)
        self.assertIn("previous.nodeId === hit.nodeId", handler)
        self.assertIn("Date.now() - previous.at <= 420", handler)
        self.assertIn("portDragState.shiftNodeClick = event.button===0", handler)
        self.assertIn("portDragState.shiftNodeDoubleClick = Boolean(isDoubleClick)", handler)
        self.assertIn("drag.shiftNodeDoubleClick && !drag.moved", finish)
        self.assertIn("focusSmartNodeInViewport(drag.fromId)", finish)
        self.assertIn("drag.shiftNodeClick && !drag.moved", finish)
        self.assertIn("shiftNodeClickCandidate = {nodeId:drag.fromId", finish)
        self.assertIn("lastShiftConnectionDragAt = Date.now()", finish)
        self.assertIn("if(Date.now() - lastShiftConnectionDragAt < 500) return", source)

    def test_multi_source_connection_drag_renders_and_preserves_every_selected_output(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        visual = source[source.index("function updatePortDragVisual"):source.index("function beginNodeConnectionDrag")]
        drag = source[source.index("function beginNodeConnectionDrag"):source.index("function handlePortDrop")]
        drop = source[source.index("function handlePortDrop"):source.index("function pickMediaForSmartNode")]

        self.assertIn("ensurePortDragPathElements", visual)
        self.assertIn("portDragState.fromIds", visual)
        self.assertIn("path.setAttribute('data-source-node-id'", visual)
        self.assertIn("fromIds", drag)
        self.assertIn("sourceResultIds", drag)
        self.assertIn("drag.sourceResultIds?.[fromId]", drop)
        self.assertIn("connectInputNodeWithTargetField(fromId, toId", drop)
        self.assertIn("startRunningHubConnectionQueue", drop)
        self.assertIn("advanceRunningHubConnectionQueue", source)

    def test_first_single_uploaded_media_uses_execution_height(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        append = source[source.index("function appendImagesToSmartNode"):source.index("async function handleFiles")]

        self.assertIn("previousCount === 0", append)
        self.assertIn("const size = defaultSingleMaterialSize(node.images[0])", append)
        self.assertIn("node.w = size.width", append)
        self.assertIn("node.h = size.height", append)
        self.assertIn("if(node.images.length > 1)", append)

    def test_connection_drag_treats_node_controls_as_their_owner_node(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        styles = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn("shell.classList.add('port-dragging')", source)
        self.assertIn("shell.classList.remove('port-dragging')", source)
        self.assertIn(".shell.port-dragging .image-node > :not(.node-port)", styles)
        self.assertIn(".shell.port-dragging .smart-node-owned-overlay > *", styles)
        self.assertIn("pointer-events:none", styles)

    def test_shift_connection_prefers_actual_control_or_popover_owner(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        handler = source[source.index("function beginShiftConnectionFromPointer"):source.index("function handlePortDragPointerMove")]
        hit_test = source[source.index("function connectionNodeHitAtPoint"):source.index("function updatePortDragVisual")]

        self.assertIn("function connectionNodeHitAtPoint(clientX, clientY, eventTarget=null)", hit_test)
        self.assertIn("const targetNodeEl = targetEl?.closest?.('.image-node')", hit_test)
        self.assertIn("const targetOwnedOverlay = targetEl?.closest?.('[data-smart-node-id]')", hit_test)
        self.assertIn("const targetOwnedNodeId", hit_test)
        self.assertIn("if(targetNodeEl) nodeEl = targetNodeEl", hit_test)
        self.assertIn("else if(targetOwnedNodeId && world)", hit_test)
        self.assertIn("const hit = connectionNodeHitAtPoint(event.clientX, event.clientY, event.target)", handler)
        self.assertIn("const started = beginNodeConnectionDrag(event, hit.nodeId)", handler)
        self.assertIn("return started", handler)
        self.assertIn("setSmartNodeOverlayOwner(composer, subject.id)", source)
        self.assertIn("setSmartNodeOverlayOwner(promptPresetPanel, nodeId)", source)
        self.assertIn("setSmartNodeOverlayOwner(promptTemplatePanel, nodeId)", source)

    def test_connection_hit_resolves_controls_popovers_and_visual_node_bounds(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        hit_test = source[source.index("function connectionNodeHitAtPoint"):source.index("function updatePortDragVisual")]

        self.assertIn("document.elementsFromPoint(clientX, clientY)", hit_test)
        self.assertIn("const hitStack = [...stack, topHit].filter(Boolean)", hit_test)
        self.assertIn("el?.closest?.('.image-node')", hit_test)
        self.assertIn("el?.closest?.('[data-smart-node-id]')", hit_test)
        self.assertIn("ownedOverlay?.dataset?.smartNodeId", hit_test)
        self.assertIn("topHit?.closest?.('.composer')", hit_test)
        self.assertIn("activeComposerNode()", hit_test)
        self.assertIn("getBoundingClientRect()", hit_test)
        self.assertIn("connectionNodeHitAtPoint(e.clientX, e.clientY, e.target)", source)
        self.assertIn("if(!nodeEl){", hit_test)
        self.assertIn("candidate.getBoundingClientRect()", hit_test)

    def test_runninghub_connections_preserve_all_media_kinds_and_localized_fields(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        connection = source[source.index("function runningHubSourceRefs"):source.index("function rhMediaKindLabel")]
        self.assertIn("item?.localUrl", connection)
        self.assertIn("item?.originalLocalUrl", connection)
        self.assertIn("isSmartMaterialNode(from) || isSmartResultGroupNode(from)", connection)
        self.assertIn("SMART_NODE_CONTRACT.textContentForMediaItem(ref)", connection)

        field_kind = source[source.index("function rhFieldKind"):source.index("function rhFieldRole")]
        self.assertIn("['STRING','TEXT'].includes(type)", field_kind)
        self.assertIn("type === 'IMAGE'", field_kind)
        self.assertNotIn("field?.label", field_kind)
        self.assertNotIn("field?.fieldName", field_kind)
        self.assertIn("title_en", source)
        self.assertIn("title_zh", source)

    def test_node_owned_overlays_keep_connection_hit_ownership(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("function setSmartNodeOverlayOwner(element, nodeId='')", source)
        self.assertIn("element.dataset.smartNodeId = id", source)
        self.assertIn("setSmartNodeOverlayOwner(composer, subject.id)", source)
        self.assertIn("setSmartNodeOverlayOwner(promptPresetPanel, nodeId)", source)
        self.assertIn("setSmartNodeOverlayOwner(promptTemplatePanel, nodeId)", source)
        self.assertIn(".image-node,.smart-node-owned-overlay,.composer", source)

    def test_composer_stays_inside_viewport_and_repositions_after_params_render(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        position = source[source.index("function positionComposerForNode"):source.index("function setSmartNodeOverlayOwner")]
        dynamic = source[source.index("function renderDynamicParams"):source.index("function bindDynamicParams")]

        self.assertIn("const hasRoomBelow = belowTop + cardH <= visibleBottom", position)
        self.assertIn("const hasRoomAbove = aboveTop >= visibleTop", position)
        self.assertIn("visibleRight - cardW", position)
        self.assertIn("visibleBottom - cardH", position)
        self.assertIn("composer.classList.toggle('composer-above'", position)
        self.assertIn("requestAnimationFrame(() =>", dynamic)
        self.assertIn("positionComposerForNode(active)", dynamic)
        self.assertIn("window.addEventListener('resize', () =>", source)

    def test_toolbar_double_click_does_not_open_canvas_create_menu(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        handler = source[source.index("shell.ondblclick = e =>"):source.index("shell.onclick = e =>", source.index("shell.ondblclick = e =>"))]
        for selector in (".smart-production-toggle", ".smart-agent-toggle", ".smart-price-toggle", ".smart-log-toggle", ".smart-shortcut-toggle", ".smart-workflow-toggle"):
            self.assertIn(selector, handler)

    def test_port_drop_uses_whole_target_node_including_controls(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        port_drop = source[source.index("function handlePortDrop"):source.index("function pickMediaForSmartNode")]
        hover = source[source.index("function updatePortDragFromPointer"):source.index("function handlePortDragPointerMove")]

        self.assertIn("connectionNodeHitAtPoint(e.clientX, e.clientY, e.target)", port_drop)
        self.assertIn("drag.hoverTargetId", port_drop)
        self.assertIn("hoveredAtDrop", port_drop)
        self.assertIn("connectionNodeHitAtPoint(e.clientX, e.clientY, e.target)", hover)
        self.assertIn("port = drag.fromPort === 'out' ? 'in' : 'out'", port_drop)
        self.assertNotIn("(e.clientX - rect.left) < rect.width / 2", port_drop)
        self.assertIn("portEl?.dataset.port || (portDragState.fromPort === 'out' ? 'in' : 'out')", hover)
        self.assertNotIn("(e.clientX - rect.left) < rect.width / 2", hover)
        self.assertIn("window.addEventListener('mousemove', handlePortDragPointerMove, true)", source)
        self.assertIn("window.addEventListener('mouseup', finishPortDragPointer, true)", source)

    def test_ctrl_shift_c_copies_selected_media_to_system_clipboard(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("async function copySelectedMediaToSystemClipboard", source)
        self.assertIn("navigator.clipboard.write", source)
        self.assertIn("e.shiftKey && key === 'c'", source)
        clipboard = source[source.index("function selectedClipboardMedia"):source.index("function pasteNodes")]
        self.assertIn(".filter(entry => isSmartImageNode(entry.node))", clipboard)
        self.assertIn("entries.length > 1", clipboard)
        self.assertIn("StudioMedia.copy(entries.map", clipboard)
        self.assertIn("window.addEventListener('copy', event =>", source)
        self.assertIn("event.defaultPrevented || isEditableTarget(event.target)", source)
        self.assertNotIn("已复制第 1 个素材", clipboard)

    def test_recent_clipboard_intent_selects_node_or_external_media(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        paste = source[source.index("window.addEventListener('paste'"):source.index("window.addEventListener('copy'")]

        image_file_branch = paste.index("const externalImageItems =")
        node_branch = paste.index("if(hasNodeClipboard && intent?.kind === 'nodes'")
        self.assertLess(node_branch, image_file_branch)
        self.assertIn("e.preventDefault();\n        pasteNodes();\n        return;", paste)
        self.assertIn("loadSmartClipboardIntent()", paste)
        self.assertIn("invalidateCanvasNodeClipboardOnFocusLoss", source)
        self.assertIn("!value.invalidatedAt", source)
        self.assertIn("saveSmartClipboardIntent({kind:'nodes', source:'canvas'", source)
        self.assertIn("handleFiles(externalImageItems, '')", paste)
        self.assertNotIn("handleFiles(externalImageItems, selectedId)", paste)

    def test_display_numbers_reuse_current_canvas_sequence_after_deletion(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        allocator = source[source.index("function allocateCanvasNodeDisplayNumber"):source.index("function mergeSmartImageLists")]
        self.assertIn("used.size ? Math.max(...used) + 1 : 1", allocator)
        self.assertIn("canvas.nextNodeNumber = next", allocator)
        self.assertNotIn("Number(canvas?.nextNodeNumber) || 1, ...used", allocator)

    def test_clipboard_media_paste_preserves_mixed_media_kinds_and_counts(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        asset_paste = source[source.index("function pasteMediaItemsToCanvas"):source.index("function duplicateForAltDrag")]
        copy_selection = source[source.index("function selectedClipboardMedia"):source.index("function copySelectedMediaToSystemClipboard")]

        self.assertIn("kind:mediaKindForItem(item)", copy_selection)
        self.assertIn("item.kind === 'text'", asset_paste)
        self.assertIn("createImageNodeAt(point, [assetNodeImageFromItem(item)]", asset_paste)
        self.assertIn("mediaKindForItem(item)", asset_paste)
        self.assertIn("count:entries.length", source)

    def test_asset_library_copy_marks_the_latest_clipboard_intent(self):
        source = (ROOT / "static/js/asset-manager.js").read_text(encoding="utf-8")
        copy = source[source.index("function copySelectedAssetsToCanvas"):source.index("async function downloadSelectedAssets")]

        self.assertIn("SMART_CANVAS_CLIPBOARD_INTENT_KEY", copy)
        self.assertIn("source:'asset-library'", copy)
        self.assertIn("count:items.length", copy)

    def test_legacy_provider_names_are_removed_from_family_labels(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        labels = source[source.index("function laohuDisplayText"):source.index("function renderCapabilityFamilyControl")]

        self.assertIn("laohuaimoney", labels)
        self.assertIn("ai[-_ ]?money", labels)
        self.assertIn("zhenzhen", labels)
        self.assertIn("capabilityFamilyLabel", labels)

    def test_group_bounds_and_dragging_use_every_member_type(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        members = source[source.index("function smartGroupMembers"):source.index("function smartGroupCompactMembers")]
        fit_bounds = source[source.index("function fitSmartGroupBounds"):source.index("function smartGroupMembers")]
        begin_drag = source[source.index("const beginNodeDrag = e =>"):source.index("el.querySelectorAll('.node-port')")]

        self.assertNotIn("isSmartExecutionNode", members)
        self.assertIn("const rects = members.map(nodeRect);", fit_bounds)
        self.assertIn("const memberIds = smartGroupMembers(node).map(member => member.id);", begin_drag)

    def test_platform_choice_is_presented_once_in_bottom_controls(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        i18n = (ROOT / "static/js/i18n/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("renderExecutionPlatformControl", source)
        self.assertIn("data-smart-platform", source)
        self.assertIn('zh: "平台选择"', i18n)

    def test_canvas_save_contract_can_request_a_migration_snapshot(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        canvas_source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("migration_version: int = 0", source)
        self.assertIn("save_canvas_migration_snapshot", source)
        self.assertIn("migration_version:smartNodeMigrationPending ? SMART_NODE_SCHEMA_VERSION : 0", canvas_source)
        self.assertIn("smartNodeMigrationPending = Number(canvas.node_schema_version || 0) < SMART_NODE_SCHEMA_VERSION;", canvas_source)
        self.assertIn("Number(data.canvas?.node_schema_version || 0) >= SMART_NODE_SCHEMA_VERSION", canvas_source)
        self.assertIn("smart.toastMigrationRestart", canvas_source)

    def test_canvas_save_contract_uses_revision_for_conflicts_and_atomic_writes(self):
        backend = (ROOT / "main.py").read_text(encoding="utf-8")
        frontend = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("base_revision", backend)
        self.assertIn('canvas["revision"]', backend)
        self.assertIn("from canvas_core.json_store import", backend)
        self.assertIn("os.fsync", (ROOT / "canvas_core/json_store.py").read_text(encoding="utf-8"))
        self.assertIn("os.replace", backend)
        self.assertIn("base_revision:storageCanvas.revision", frontend)
        self.assertIn("canvas.revision = Number(data.canvas?.revision", frontend)
        merge_start = frontend.index("function applyMergedServerCanvas")
        merge_end = frontend.index("async function mergeReloadCanvasNow", merge_start)
        merge = frontend[merge_start:merge_end]
        self.assertIn("const incomingRevision = Number(serverCanvas.revision)", merge)
        self.assertIn("Number(canvasSyncBase?.revision)", merge)
        self.assertIn("return {stale:true, conflicts:[]}", merge)
        self.assertIn("CANVAS_SYNC.merge(base, local, remote)", merge)
        self.assertIn("canvasSyncSaveBlocked = Boolean(merged.conflicts.length)", merge)

    def test_classic_canvas_entrypoint_is_retired(self):
        self.assertFalse((ROOT / "static/canvas.html").exists())
        self.assertFalse((ROOT / "static/js/canvas.js").exists())
        self.assertFalse((ROOT / "static/css/canvas.css").exists())
        backend = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("当前只支持新建智能画布", backend)
        self.assertIn("普通画布已停用，请使用智能画布", backend)

    def test_new_smart_canvases_start_on_the_current_node_schema(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("SMART_CANVAS_NODE_SCHEMA_VERSION = 7", source)
        self.assertIn('canvas["node_schema_version"] = SMART_CANVAS_NODE_SCHEMA_VERSION', source)

    def test_media_references_preserve_audio_video_text_and_image_types(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const items=[
  {url:'/assets/output/a.wav'},
  {url:'/assets/output/b.mp4'},
  {url:'/assets/output/c.md'},
  {url:'/assets/output/d.png'}
];
console.log(JSON.stringify(items.map((item,index)=>c.normalizeMediaReference(item,index))));
"""
        data = run_node(script)

        self.assertEqual([item["kind"] for item in data], ["audio", "video", "text", "image"])
        self.assertEqual([item["role"] for item in data], ["audio_1", "video_2", "text_3", "image_4"])

    def test_result_group_expands_stable_member_references_without_copying_files(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const nodes={
  image:{id:'image',images:[{url:'/assets/output/a.png',result_id:'r1'}]},
  audio:{id:'audio',images:[{url:'/assets/output/a.wav',kind:'audio',result_id:'r2'}]}
};
const group={
  id:'group',
  type:c.NODE_TYPES.resultGroup,
  items:[
    {nodeId:'image',resultIds:['r1'],round:1},
    {nodeId:'audio',resultIds:['r2'],round:2}
  ]
};
console.log(JSON.stringify(c.expandResultGroup(group,id=>nodes[id])));
"""
        data = run_node(script)

        self.assertEqual([item["url"] for item in data], ["/assets/output/a.png", "/assets/output/a.wav"])
        self.assertEqual([item["kind"] for item in data], ["image", "audio"])
        self.assertEqual([item["resultGroupId"] for item in data], ["group", "group"])
        self.assertEqual([item["resultId"] for item in data], ["r1", "r2"])
        self.assertEqual([item["round"] for item in data], [1, 2])

    def test_result_group_connection_can_select_one_stable_result(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const nodes={
  image:{id:'image',images:[
    {url:'/api/results/r1',result_id:'r1'},
    {url:'/api/results/r2',result_id:'r2'}
  ]}
};
const group={
  id:'group',
  type:c.NODE_TYPES.resultGroup,
  items:[{nodeId:'image',resultIds:['r1','r2'],round:1}]
};
const all=c.resultGroupMediaForConnection(group,{},id=>nodes[id]);
const selected=c.resultGroupMediaForConnection(group,{sourceResultId:'r2'},id=>nodes[id]);
console.log(JSON.stringify({all,selected}));
"""
        data = run_node(script)

        self.assertEqual([item["resultId"] for item in data["all"]], ["r1", "r2"])
        self.assertEqual([item["resultId"] for item in data["selected"]], ["r2"])

    def test_result_group_connections_keep_distinct_single_item_outputs(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const group={id:'group',type:c.NODE_TYPES.resultGroup,items:[]};
const target={id:'target',type:c.NODE_TYPES.imageGenerator};
const migrated=c.migrateLegacyCanvas(
  [group,target],
  [
    {from:'group',to:'target',kind:'input',sourceResultId:'r1'},
    {from:'group',to:'target',kind:'input',sourceResultId:'r2'}
  ]
);
console.log(JSON.stringify(migrated.connections));
"""
        data = run_node(script)

        self.assertEqual(len(data), 2)
        self.assertEqual([item["sourceResultId"] for item in data], ["r1", "r2"])

    def test_runninghub_input_bindings_keep_stable_media_field_assignments(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const fields=[
  {nodeId:'100',fieldName:'image',fieldType:'IMAGE',imageOrder:1},
  {nodeId:'112',fieldName:'image',fieldType:'IMAGE',imageOrder:2},
  {nodeId:'200',fieldName:'audio',fieldType:'AUDIO'}
];
const refs=[
  {url:'/api/results/r1',resultId:'r1',kind:'image',name:'人物.png'},
  {url:'/api/results/r2',resultId:'r2',kind:'image',name:'风格.png'},
  {url:'/api/results/r3',resultId:'r3',kind:'audio',name:'旁白.wav'}
];
const ambiguous=c.reconcileRunningHubInputBindings(fields,refs,{});
const initial=c.reconcileRunningHubInputBindings(fields,refs,{'100::image':'result:r1','112::image':'result:r2'});
const swapped=c.swapRunningHubInputBinding(fields,refs,initial,'112::image',-1);
const assigned=c.assignRunningHubInputBinding(fields,refs,swapped,'100::image','result:r1');
const reordered=c.reconcileRunningHubInputBindings(fields,[refs[1],refs[0],refs[2]],swapped);
console.log(JSON.stringify({ambiguous,initial,swapped,assigned,reordered,resolved:c.runningHubBoundMedia(fields,refs,reordered)}));
"""
        data = run_node(script)

        self.assertNotIn("100::image", data["ambiguous"])
        self.assertNotIn("112::image", data["ambiguous"])
        self.assertEqual(data["ambiguous"]["200::audio"], "result:r3")
        self.assertEqual(data["initial"]["100::image"], "result:r1")
        self.assertEqual(data["initial"]["112::image"], "result:r2")
        self.assertEqual(data["swapped"]["100::image"], "result:r2")
        self.assertEqual(data["swapped"]["112::image"], "result:r1")
        self.assertEqual(data["assigned"]["100::image"], "result:r1")
        self.assertEqual(data["assigned"]["112::image"], "result:r2")
        self.assertEqual(data["reordered"], data["swapped"])
        self.assertEqual(data["resolved"]["100::image"]["resultId"], "r2")
        self.assertEqual(data["resolved"]["112::image"]["resultId"], "r1")

    def test_runninghub_input_bindings_drop_stale_or_wrong_media_types(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const fields=[
  {nodeId:'10',fieldName:'image',fieldType:'IMAGE'},
  {nodeId:'20',fieldName:'video',fieldType:'VIDEO'}
];
const refs=[
  {url:'/api/results/image',resultId:'image',kind:'image'},
  {url:'/api/results/video',resultId:'video',kind:'video'}
];
console.log(JSON.stringify(c.reconcileRunningHubInputBindings(fields,refs,{
  '10::image':'result:video',
  '20::video':'result:missing',
  'stale::field':'result:image'
})));
"""
        data = run_node(script)

        self.assertEqual(data, {
            "10::image": "result:image",
            "20::video": "result:video",
        })

    def test_ai_app_ui_and_request_share_runninghub_field_bindings(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        translations = (ROOT / "static/js/i18n/smart-canvas.js").read_text(encoding="utf-8")

        params = source[source.index("function renderRunningHubParams"):source.index("function rhSchemaDiffForSettings")]
        runner = source[source.index("async function runRunningHubGeneration"):source.index("async function runApiVideoGeneration")]
        selector = source[source.index("function selectedRunningHubRef"):source.index("function rhEntryFields")]
        self.assertNotIn("renderRhMachineControl()", params)
        self.assertNotIn("instanceType", runner)
        self.assertNotIn("workflow-submit", runner)
        self.assertNotIn("runningHubEntries('workflow')", selector)
        self.assertIn("['text','image','video','audio'].includes", source)
        self.assertNotIn("function renderRhInputMappingControl", source)
        self.assertNotIn("data-rh-binding-select", source)
        self.assertNotIn("data-rh-binding-move", source)
        self.assertIn("rhPrepareMediaBindings(rhMediaForRun(prompt, refs), runSettings, fields, node)", source)
        self.assertIn("runningHubBindingsFromConnections(node, refs, fields)", source)
        self.assertIn("media?.boundByField?.[key]", source)
        self.assertIn("media?.boundByField?.[key] || media?.[kind]?.[idx]", source)
        self.assertIn("rhSchemaSnapshot", source)
        self.assertIn("diffRunningHubSchema", source)
        self.assertIn("data-rh-schema-accept", source)
        for key in (
            "smart.rhInputMapping",
            "smart.rhInputMappingHint",
            "smart.rhInputRequired",
            "smart.rhInputMissing",
        ):
            self.assertIn(f'"{key}"', translations)

    def test_runninghub_ai_app_parameters_use_vertical_scrolling_layout(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        params = source[source.index("function renderRunningHubParams"):source.index("function rhSchemaDiffForSettings")]
        field = source[source.index("function renderRhSettingField"):source.index("function comfyRandomEnabledField")]
        self.assertIn('class="rh-ai-app-params"', params)
        self.assertIn('class="rh-ai-app-param-list"', params)
        self.assertIn("renderExternalParameterControl(field,'rh')", field)
        self.assertIn('function externalParameterSpec', source)
        self.assertIn(".composer.ai-app-composer .composer-card", css)
        self.assertIn("grid-template-areas:\"thumbs\" \"params\" \"run\"", css)
        self.assertIn(".rh-ai-app-param-list", css)
        self.assertIn("overflow-y:auto", css)
        self.assertIn(".composer.ai-app-composer { z-index:60", css)
        self.assertIn("background:var(--card)", css)
        self.assertIn("max-height:min(680px", css)
        position = source[source.index("function positionComposerForNode"):source.index("function setSmartNodeOverlayOwner")]
        self.assertNotIn("preferSide", position)
        self.assertNotIn("hasRoomRight", position)
        self.assertNotIn("classList.toggle('composer-side'", position)
        self.assertIn("classList.remove('composer-side'", position)
        self.assertIn("const forceBelow = isSmartExecutionNode(node) || isSmartMaterialNode(node)", position)
        self.assertIn("const belowTop = rect.y + rect.height + gap", position)
        self.assertIn("top = forceBelow ? belowTop", position)
        self.assertIn("if(!forceBelow) top = Math.min", position)

    def test_runninghub_connection_bindings_keep_each_media_item_and_field_stable(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const fields=[
  {nodeId:'10',fieldName:'prompt',fieldType:'TEXT'},
  {nodeId:'11',fieldName:'negative',fieldType:'STRING'},
  {nodeId:'20',fieldName:'image_a',fieldType:'IMAGE'},
  {nodeId:'21',fieldName:'image_b',fieldType:'IMAGE'},
  {nodeId:'22',fieldName:'result_image',fieldType:'IMAGE'},
  {nodeId:'30',fieldName:'video',fieldType:'VIDEO'},
  {nodeId:'40',fieldName:'audio',fieldType:'AUDIO'}
];
const refs=[
  {nodeId:'text-1',inputSourceNodeId:'text-1',imageIndex:0,kind:'text',text:'第一段'},
  {nodeId:'text-2',inputSourceNodeId:'text-2',imageIndex:0,kind:'text',text:'第二段'},
  {nodeId:'image-group',inputSourceNodeId:'image-group',imageIndex:0,materialId:'same-file',kind:'image',url:'/assets/a.png'},
  {nodeId:'image-group',inputSourceNodeId:'image-group',imageIndex:1,materialId:'same-file',kind:'image',url:'/assets/a.png'},
  {nodeId:'video-1',inputSourceNodeId:'video-1',imageIndex:0,kind:'video',url:'/assets/a.mp4'},
  {nodeId:'audio-1',inputSourceNodeId:'audio-1',imageIndex:0,kind:'audio',url:'/assets/a.mp3'},
  {nodeId:'result-child',inputSourceNodeId:'result-group',resultId:'result-2',imageIndex:0,kind:'image',url:'/assets/result.png'}
];
const connections=[
  {from:'text-1',to:'app',kind:'input',targetFieldKey:'10::prompt'},
  {from:'text-2',to:'app',kind:'input',targetFieldKey:'11::negative'},
  {from:'image-group',to:'app',kind:'input',sourceMediaKey:'node:image-group:0',targetFieldKey:'20::image_a'},
  {from:'image-group',to:'app',kind:'input',sourceMediaKey:'node:image-group:1',targetFieldKey:'21::image_b'},
  {from:'video-1',to:'app',kind:'input',targetFieldKey:'30::video'},
  {from:'audio-1',to:'app',kind:'input',targetFieldKey:'40::audio'},
  {from:'result-group',to:'app',kind:'input',sourceResultId:'result-2',targetFieldKey:'22::result_image'}
];
const explicit=c.runningHubBindingsFromConnections('app',fields,refs,connections);
const resolved=c.reconcileRunningHubInputBindings(fields,refs,explicit);
console.log(JSON.stringify({explicit,resolved}));
"""
        data = run_node(script)

        self.assertEqual(data["explicit"], {
            "10::prompt": "node:text-1:0",
            "11::negative": "node:text-2:0",
            "20::image_a": "node:image-group:0",
            "21::image_b": "node:image-group:1",
            "22::result_image": "result:result-2",
            "30::video": "node:video-1:0",
            "40::audio": "node:audio-1:0",
        })
        self.assertEqual(data["resolved"], {
            "10::prompt": "node:text-1:0",
            "11::negative": "node:text-2:0",
            "20::image_a": "node:image-group:0",
            "21::image_b": "node:image-group:1",
            "22::result_image": "result:result-2",
            "30::video": "node:video-1:0",
            "40::audio": "node:audio-1:0",
        })

        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        sync = source[
            source.index("function syncRunningHubInputBindings"):
            source.index("function closeRunningHubFieldPicker")
        ]
        self.assertIn("defaultReferenceImagesFor(node)", sync)
        self.assertIn("node.runSettings = settingsForStorage(sourceSettings)", sync)

        picker = source[
            source.index("function connectInputNodeWithTargetField"):
            source.index("function rhMediaKindLabel")
        ]
        self.assertIn("sourceMediaKey", picker)
        self.assertIn("startRunningHubConnectionQueue", picker)
        self.assertNotIn("sourceRefs.length > 1 || new Set(sourceRefs.map(mediaKindForItem)).size > 1", picker)

    def test_runninghub_ai_app_lists_media_and_settings_in_official_order(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        params = source[source.index("function renderRunningHubParams"):source.index("function rhSchemaDiffForSettings")]
        sorter = source[source.index("function sortRunningHubFields"):source.index("function chatApiProviders")]
        field = source[source.index("function renderRhAiAppFieldRow"):source.index("function renderRhSettingField")]

        self.assertIn("fields.map(field => renderRhAiAppFieldRow(field, fields, refs))", params)
        self.assertNotIn("settingFields.map", params)
        self.assertNotIn("renderRhInputMappingControl(fields)", params)
        self.assertIn("renderRhConnectedInputControl", field)
        self.assertIn("schemaOrder", sorter)
        self.assertIn("return aOrder - bOrder || a.index - b.index", sorter)

    def test_runninghub_ai_app_media_fields_follow_connection_state(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        field = source[source.index("function renderRhAiAppFieldRow"):source.index("function renderRhSettingField")]
        self.assertIn("const connected = bound[key]", field)
        self.assertIn("renderRhConnectedInputControl", field)
        self.assertIn("renderRhUnconnectedInputControl", field)
        self.assertNotIn("data-rh-direct-text", field)
        self.assertNotIn("data-rh-direct-upload", field)
        self.assertNotIn("data-rh-direct-url", field)
        self.assertNotIn("data-rh-binding-select", field)
        self.assertNotIn("data-rh-input-mode", field)
        self.assertNotIn("直接输入", field)
        self.assertNotIn("外部节点", field)
        self.assertIn(".rh-ai-app-media-row.is-missing", css)
        self.assertIn(".rh-ai-app-media-row.is-mapped", css)
        self.assertNotIn(".rh-ai-app-direct-text", css)
        self.assertNotIn(".rh-ai-app-direct-media", css)
        self.assertIn(".rh-ai-app-connected-card", css)

    def test_runninghub_ai_app_config_popovers_are_not_clipped(self):
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        context_list_rule = css[
            css.index(".composer.ai-app-composer .rh-ai-app-context-list {"):
            css.index("}", css.index(".composer.ai-app-composer .rh-ai-app-context-list {")) + 1
        ]
        context_row_rule = css[
            css.index(".composer.ai-app-composer .rh-ai-app-context-row {"):
            css.index("}", css.index(".composer.ai-app-composer .rh-ai-app-context-row {")) + 1
        ]
        self.assertIn("overflow:visible", context_list_rule)
        self.assertIn("overflow:visible", context_row_rule)
        self.assertIn(".composer.ai-app-composer .rh-picker-popover", css)
        self.assertIn("top:calc(100% + 6px)", css)
        self.assertIn(".composer.ai-app-composer .smart-control::before", css)
        self.assertIn(".composer.ai-app-composer .rh-picker-popover::before", css)

    def test_execution_popovers_open_only_on_click_and_only_one_at_a_time(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        bindings = source[
            source.index("function bindDynamicParams"):
            source.index("dynamicParams.querySelectorAll('[data-smart-param]')")
        ]
        popover_rule = css[
            css.index(".smart-control.pinned .smart-popover"):
            css.index(".smart-popover-title")
        ]

        self.assertNotIn("ctrl.onmouseenter", bindings)
        self.assertNotIn("ctrl.onmouseleave", bindings)
        self.assertNotIn("interacting", bindings)
        self.assertIn("closeAllSmartPopovers();", bindings)
        self.assertIn("ctrl.classList.add('pinned')", bindings)
        self.assertNotIn(":hover .smart-popover", popover_rule)
        self.assertNotIn(":focus-within .smart-popover", popover_rule)
        self.assertNotIn(".interacting .smart-popover", popover_rule)

    def test_execution_controls_show_valid_default_values(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        platform = source[
            source.index("function renderExecutionPlatformControl"):
            source.index("function selectExecutionPlatform")
        ]
        family = source[
            source.index("function renderCapabilityFamilyControl"):
            source.index("const SUNO_ACTION_INFO")
        ]
        choice_control = source[
            source.index("function renderExecutionChoiceControl"):
            source.index("function renderExecutionPlatformControl")
        ]

        self.assertIn('class="smart-control ${escapeAttr(className)}', choice_control)
        self.assertIn("renderExecutionChoiceControl", platform)
        self.assertIn("'execution-platform-control'", platform)
        self.assertIn("data-execution-platform-option", platform)
        self.assertNotIn("<select", platform)
        self.assertIn("renderExecutionChoiceControl", family)
        self.assertIn("'model-control'", family)
        self.assertIn("data-execution-family-option", family)
        self.assertNotIn("<select", family)
        self.assertIn("execution-control-label", source)
        self.assertIn("displayValue", choice_control)
        self.assertIn("displayValue || label", choice_control)
        parameter_control = source[
            source.index("function renderCapabilityParameterControl"):
            source.index("function renderGenericCapabilityParameters")
        ]
        self.assertIn("capabilityParameterPreview", parameter_control)
        self.assertIn("capability-number-value", parameter_control)
        self.assertIn("value === undefined || value === ''", parameter_control)
        full_span_rule = css[
            css.index(".execution-config-grid > .capability-fields"):
            css.index("}", css.index(".execution-config-grid > .capability-fields")) + 1
        ]
        self.assertNotIn(".execution-config-grid > .smart-control", full_span_rule)
        self.assertIn("height:34px", css)

    def test_execution_header_uses_one_alignment_grid_for_title_help_and_run(self):
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        header_rules = css[
            css.index(".composer:not(.ai-app-composer) .composer-card:has(.execution-config-panel) .composer-actions"):
            css.index(".capability-help-popover", css.index(".execution-config-panel-head"))
        ]

        self.assertIn("margin:6px 2px 0 0", header_rules)
        self.assertIn("height:40px", header_rules)
        self.assertIn("height:28px", header_rules)
        self.assertIn("width:28px", header_rules)
        self.assertNotIn("margin:9px 12px 0 0", header_rules)

    def test_open_execution_parameter_popover_owns_the_top_stacking_layer(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn(".composer:has(.smart-control.pinned) { z-index:140; }", css)
        self.assertIn(".composer-card:has(.smart-control.pinned) .param-row { position:relative; z-index:180;", css)
        self.assertIn(".dynamic-params:has(.smart-control.pinned) { max-height:none; overflow:visible; }", css)
        self.assertIn(".smart-control.pinned { z-index:200 !important; }", css)
        self.assertIn(".smart-control.pinned .smart-popover {", css)
        pinned_rule = css[
            css.index(".smart-control.pinned .smart-popover {"):
            css.index("}", css.index(".smart-control.pinned .smart-popover {")) + 1
        ]
        self.assertRegex(pinned_rule, r"z-index:(?:2[2-9]0|[3-9]\d{2,})")
        self.assertIn("function positionPinnedSmartPopover", source)
        self.assertIn("positionPinnedSmartPopover(ctrl)", source)
        self.assertIn(".smart-control.popover-below .smart-popover", css)
        self.assertIn("--smart-popover-available", css)
        self.assertIn("--smart-popover-shift-x", source)
        self.assertIn("margin-left:var(--smart-popover-shift-x, 0px)", css)

    def test_all_execution_nodes_keep_platform_model_and_mode_controls_visible(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        variant_control = source[
            source.index("function renderCapabilityVariantControl"):
            source.index("function capabilityFamilySelectionNote")
        ]

        self.assertNotIn("variants.length <= 1", variant_control)
        self.assertNotIn("if(!selection?.family) return '';", variant_control)
        self.assertIn("selection.profile || variants[0]", variant_control)
        for renderer_name, next_name in (
            ("function renderTextGenerationParams", "function renderApiParams"),
            ("function renderApiParams", "function renderJimengUpscaleControl"),
            ("function renderApiVideoParams", "function renderApiAudioParams"),
            ("function renderApiAudioParams", "function renderVolcengineParams"),
        ):
            renderer = source[source.index(renderer_name):source.index(next_name)]
            self.assertIn("renderCapabilityModelPicker(selection, descriptor)", renderer)
            self.assertNotIn("renderCapabilityVariantControl", renderer)
        video_renderer = source[
            source.index("function renderApiVideoParams"):
            source.index("function renderApiAudioParams")
        ]
        self.assertIn("videoCapabilityInputRoles(refs, settings, true)", video_renderer)
        self.assertIn("renderVideoInputModeControl(profile, refs)", video_renderer)
        self.assertIn("data-video-input-mode", source)
        self.assertIn("function resolveCapabilityForRun(providerId, nodeType, inputCounts, familyId='', legacyModelId='', operation='', inputRoles={}, parameters={}, region='')", source)
        self.assertIn("resolveCapabilityFamilySelection(providerId, nodeType, inputCounts, familyId, legacyModelId, operation, inputRoles, parameters, region)", source)
        self.assertIn("capabilityProvidersFor(descriptor.nodeType, inputCounts, [], inputRoles, parameters, region)", source)
        self.assertIn("capabilityParameterIntent(runSettings.videoProvider, runSettings.videoModel, 'video_generation', runSettings)", source)
        text_renderer = source[
            source.index("function renderTextGenerationParams"):
            source.index("function renderApiParams")
        ]
        self.assertNotIn("${models.length ? `", text_renderer)
        self.assertIn("${!models.length ? `", text_renderer)
        text_platform = source[
            source.index("function renderTextExecutionPlatformControl"):
            source.index("function chatModelOptions")
        ]
        self.assertIn("const providers = chatApiProviders().filter", text_platform)
        self.assertNotIn("data-text-provider-unavailable", text_platform)
        volcengine_video = source[
            source.index("function renderVolcengineVideoParams"):
            source.index("function renderRunningHubParams")
        ]
        self.assertIn("renderExecutionModeFallbackControl", volcengine_video)
        self.assertIn(".execution-config-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr))", css)
        self.assertIn(".dynamic-params .text-generation-params { display:grid; grid-template-columns:repeat(3,minmax(0,1fr))", css)

    def test_execution_reference_slots_support_local_pairwise_swap(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const entries=[
  {key:'node:a:0',item:{url:'a'}},
  {key:'node:b:0',item:{url:'b'}},
  {key:'node:c:0',item:{url:'c'}}
];
const available=typeof c.applyReferenceSlotOrder==='function' && typeof c.swapReferenceSlotOrder==='function';
console.log(JSON.stringify({
  available,
  applied:available ? c.applyReferenceSlotOrder(entries,['node:b:0','node:a:0','stale']).map(entry=>entry.key) : null,
  swapped:available ? c.swapReferenceSlotOrder(entries,['node:a:0','node:b:0','node:c:0'],'node:a:0','node:c:0') : null
}));
"""
        data = run_node(script)

        self.assertTrue(data["available"])
        self.assertEqual(data["applied"], ["node:b:0", "node:a:0", "node:c:0"])
        self.assertEqual(data["swapped"], ["node:c:0", "node:b:0", "node:a:0"])

    def test_input_thumb_shift_swap_is_global_and_never_starts_connection_drag(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        drag = source[
            source.index("function bindInputThumbsDrag"):
            source.index("function bindInputThumbVideoActions")
        ]
        thumbs = source[
            source.index("function renderInputThumbsRow"):
            source.index("function bindInputThumbReferenceActions")
        ]
        reorder = source[
            source.index("function reorderInputThumb"):
            source.index("function isSupportedUploadFile")
        ]
        shift_connection = source[
            source.index("function beginShiftConnectionFromPointer"):
            source.index("shell.addEventListener('mousedown', beginShiftConnectionFromPointer")
        ]

        self.assertIn("e.shiftKey", drag)
        self.assertIn("hasMentionReferenceContent", drag)
        self.assertNotIn("isConnectedInputReference", drag)
        self.assertIn("data-input-ref-swappable", thumbs)
        self.assertIn("swapGlobalInputReferences", reorder)
        self.assertIn("inputRefOrder", reorder)
        self.assertIn("mediaKindForItem(fromImg) !== mediaKindForItem(toImg)", reorder)
        self.assertNotIn("src.images", reorder)
        self.assertNotIn("a.x", reorder)
        self.assertNotIn("canvas.connections", reorder)
        self.assertIn(".input-thumb[data-input-ref-swappable=\"1\"]", shift_connection)

    def test_connected_reference_thumbnails_disconnect_the_matching_input_line(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        thumbs = source[
            source.index("function renderInputThumbsRow"):
            source.index("function bindInputThumbsDrag")
        ]
        removal = source[
            source.index("function connectionIndicesForInputReference"):
            source.index("function removeManualReferenceFromSelectedNode")
        ]
        remove_css = css[
            css.index(".input-thumb-remove"):
            css.index(".input-thumb.input-self")
        ]

        self.assertIn("manualRefKeys.has(key) || connectedRefKeys.has(key)", thumbs)
        self.assertIn("data-input-remove-index", thumbs)
        self.assertIn("removeInputReferenceFromSelectedNode", thumbs)
        self.assertIn("disconnectConnections(indices)", removal)
        self.assertIn("connectionTargetFieldKey", removal)
        self.assertIn("opacity:0", remove_css)
        self.assertIn("pointer-events:none", remove_css)
        self.assertIn("pointer-events:auto", remove_css)

    def test_mentions_expand_text_and_preview_audio_video_on_hover(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        candidates = source[
            source.index("function inputMentionCandidateImages"):
            source.index("function assetRegisteredUris")
        ]
        parts = source[
            source.index("function collectPromptParts"):
            source.index("function originalPromptTextFromParts")
        ]
        request = source[
            source.index("function buildPromptRequest"):
            source.index("function outgoingConnectionsFor")
        ]
        hover = source[
            source.index("function hideReferenceHoverPreview"):
            source.index("mentionPicker.addEventListener('mousedown'")
        ]

        self.assertIn("hasMentionReferenceContent", candidates)
        self.assertIn("textContentForMediaItem", parts)
        self.assertIn("part.kind === 'text'", request)
        self.assertIn("mention-preview-text", hover)
        self.assertIn("document.createElement('audio')", hover)
        self.assertIn("document.createElement('video')", hover)
        self.assertIn("media.muted = false", hover)
        self.assertIn("media.controls = true", hover)
        self.assertIn("media.play?.()", hover)
        self.assertIn("showReferenceHoverPreview(token", hover)
        self.assertIn("showReferenceHoverPreview(thumb", source)
        self.assertIn(".mention-preview-text", css)

    def test_removing_an_execution_reference_closes_its_hover_preview(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        renderer = source[
            source.index("function renderInputThumbsRow"):
            source.index("function bindInputThumbReferenceActions")
        ]
        removal = source[
            source.index("function removeInputReferenceFromSelectedNode"):
            source.index("function removeManualReferenceFromSelectedNode")
        ]

        self.assertIn("hideReferenceHoverPreview();", renderer)
        self.assertLess(renderer.index("hideReferenceHoverPreview();"), renderer.index("inputThumbsRow.innerHTML"))
        self.assertIn("hideReferenceHoverPreview();", removal)
        self.assertLess(removal.index("hideReferenceHoverPreview();"), removal.index("disconnectConnections(indices)"))

    def test_execution_references_hide_upstream_preview_and_use_numbered_labels(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        html = (ROOT / "static/smart-canvas.html").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        candidates = source[
            source.index("function inputMentionCandidateImages"):
            source.index("function mentionCandidateImages")
        ]
        thumbs = source[
            source.index("function inputThumbLabel"):
            source.index("function bindInputThumbReferenceActions")
        ]

        self.assertNotIn('id="inputPromptPreview"', html)
        self.assertNotIn("function renderInputPromptPreview", source)
        self.assertNotIn("prompt-preview", css)
        self.assertIn("function numberedReferenceItems", source)
        self.assertIn("inputThumbLabel(kind, count)", source)
        self.assertIn("numberedReferenceItems", candidates)
        self.assertNotIn("alias:img.name", candidates)
        self.assertIn("syncNodeMentionLabels", thumbs)
        ordered = source[
            source.index("function orderedInputReferencesForNode"):
            source.index("function blockedInputRefKeys")
        ]
        visible = source[
            source.index("function visibleReferenceImagesFor"):
            source.index("function inputMentionCandidateImages")
        ]
        self.assertIn("REFERENCE_MEDIA_ORDER", ordered)
        self.assertIn("groupReferenceItemsByMediaKind", ordered)
        self.assertIn("orderedInputReferencesForNode", visible)
        media_kind = source[
            source.index("function mediaKindForItem"):
            source.index("function localDisplayUrlForMediaItem")
        ]
        self.assertLess(media_kind.index("isTextMediaItem"), media_kind.index("isFileMediaItem"))
        option_media = source[
            source.index("function mentionOptionMediaHtml"):
            source.index("function promptHtmlWithMentionTokens")
        ]
        self.assertNotIn("<span>${escapeHtml", option_media)

    def test_disconnected_source_mentions_are_pruned_from_execution_drafts(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        pruning = source[
            source.index("function pruneDisconnectedMentionTokens"):
            source.index("function sourceMediaSlotForReference")
        ]
        disconnect = source[
            source.index("function disconnectConnections"):
            source.index("function connectionIndexSpecFromPoint")
        ]
        erase = source[
            source.index("function finishConnectionErase"):
            source.index("function eraseConnectionsAtPoint")
        ]

        self.assertIn("lineImagesFor(node)", pruning)
        self.assertIn("token.remove()", pruning)
        self.assertIn("pruneDisconnectedMentionTokensForAllNodes()", disconnect)
        self.assertIn("pruneDisconnectedMentionTokensForAllNodes()", erase)
        composer_update = source[
            source.index("function updateComposer"):
            source.index("function inputThumbLabel")
        ]
        self.assertIn("pruneDisconnectedMentionTokensForAllNodes()", composer_update)

    def test_raw_at_mention_picker_closes_globally_and_space_reopens_it(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        prompt_events = source[
            source.index("promptInput.addEventListener('input', maybeOpenMentionPicker)"):
            source.index("promptInput.addEventListener('mouseover'")
        ]
        outside_close = source[
            source.index("function closeMentionPickerOnOutsidePointer"):
            source.index("promptInput.addEventListener('input', maybeOpenMentionPicker)")
        ]

        self.assertIn("event.key === ' '", prompt_events)
        self.assertIn("/@$/.test(textBeforeCaret())", prompt_events)
        self.assertIn("showMentionPicker()", prompt_events)
        self.assertIn("document.addEventListener('pointerdown', closeMentionPickerOnOutsidePointer, true)", outside_close)
        self.assertNotIn("textContent", outside_close)
        insert = source[
            source.index("function insertMentionToken"):
            source.index("function collectPromptParts")
        ]
        self.assertIn("savePromptDraftForCurrent()", insert)
        self.assertIn("scheduleSave()", insert)

    def test_all_node_editors_share_the_canvas_scrollbar_style(self):
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        scrollbar = css[
            css.index("/* 节点编辑区统一滚动条 */"):
            css.index("/* 节点编辑区统一滚动条结束 */")
        ]

        self.assertIn(".image-node textarea", scrollbar)
        self.assertIn('.image-node [contenteditable="true"]', scrollbar)
        self.assertIn(".composer textarea", scrollbar)
        self.assertIn('.composer [contenteditable="true"]', scrollbar)
        self.assertIn("scrollbar-width:thin", scrollbar)
        self.assertIn("::-webkit-scrollbar", scrollbar)
        self.assertIn("::-webkit-scrollbar-thumb:hover", scrollbar)

    def test_runninghub_coin_user_facing_name_is_rh_coin(self):
        visible_sources = [
            ROOT / "static/api-settings.html",
            ROOT / "static/js/i18n/api-settings.js",
            ROOT / "static/js/i18n/smart-canvas.js",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in visible_sources)

        self.assertNotIn("RunningHub币", combined)
        self.assertNotIn("Running Hub币", combined)
        self.assertIn("RH币", combined)

    def test_runninghub_multiple_same_type_fields_require_explicit_slot_bindings(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const fields=[
  {nodeId:'1',fieldName:'text',fieldType:'STRING'},
  {nodeId:'2',fieldName:'text',fieldType:'TEXT'},
  {nodeId:'3',fieldName:'image',fieldType:'IMAGE'},
  {nodeId:'4',fieldName:'audio',fieldType:'AUDIO'}
];
const refs=[
  {materialId:'t1',kind:'text',text:'第一段'},
  {materialId:'t2',kind:'text',text:'第二段'},
  {materialId:'i1',kind:'image',url:'/assets/a.png'},
  {materialId:'a1',kind:'audio',url:'/assets/a.mp3'}
];
const automatic=c.reconcileRunningHubInputBindings(fields,refs,{});
const explicit=c.reconcileRunningHubInputBindings(fields,refs,{
  '1::text':'material:t1',
  '2::text':'material:t2'
});
console.log(JSON.stringify({automatic,explicit}));
"""
        data = run_node(script)

        self.assertEqual(data["automatic"], {
            "3::image": "material:i1",
            "4::audio": "material:a1",
        })
        self.assertEqual(data["explicit"], {
            "1::text": "material:t1",
            "2::text": "material:t2",
            "3::image": "material:i1",
            "4::audio": "material:a1",
        })

    def test_runninghub_explicit_text_target_is_not_stolen_by_earlier_string_fields(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const fields=[
  {nodeId:'361',fieldName:'text',fieldType:'STRING',label:'音频开始时间'},
  {nodeId:'362',fieldName:'text',fieldType:'STRING',label:'音频结束时间'},
  {nodeId:'360',fieldName:'text',fieldType:'STRING',label:'提示词文本'},
  {nodeId:'105',fieldName:'megapixels',fieldType:'FLOAT',label:'一采参数 分辨率'}
];
const refs=[{materialId:'prompt',kind:'text',text:'这个女人在录音棚里面唱歌'}];
console.log(JSON.stringify(c.reconcileRunningHubInputBindings(fields,refs,{'360::text':'material:prompt'})));
"""

        data = run_node(script)

        self.assertEqual(data, {"360::text": "material:prompt"})

    def test_runninghub_schema_diff_detects_structural_changes(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const saved=[
  {nodeId:'100',fieldName:'image',fieldType:'IMAGE',required:true,imageOrder:1},
  {nodeId:'112',fieldName:'image',fieldType:'IMAGE',required:false,imageOrder:2},
  {nodeId:'14',fieldName:'seed',fieldType:'INT',required:false}
];
const current=[
  {nodeId:'100',fieldName:'image',fieldType:'VIDEO',required:true,imageOrder:1},
  {nodeId:'112',fieldName:'image',fieldType:'IMAGE',required:true,imageOrder:1},
  {nodeId:'99',fieldName:'strength',fieldType:'FLOAT',required:false}
];
console.log(JSON.stringify({
  snapshot:c.runningHubSchemaSnapshot(saved),
  diff:c.diffRunningHubSchema(saved,current),
  same:c.diffRunningHubSchema(saved,saved)
}));
"""
        data = run_node(script)

        self.assertEqual(data["snapshot"][0]["key"], "100::image")
        self.assertTrue(data["diff"]["changed"])
        self.assertEqual(data["diff"]["removed"], ["14::seed"])
        self.assertEqual(data["diff"]["added"], ["99::strength"])
        self.assertEqual(data["diff"]["typeChanged"], ["100::image"])
        self.assertEqual(data["diff"]["requiredChanged"], ["112::image"])
        self.assertEqual(data["diff"]["orderChanged"], ["112::image"])
        self.assertFalse(data["same"]["changed"])

    def test_runninghub_outputs_preserve_media_types_for_result_grouping(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const payload={
  data:{results:[
    {url:'/api/results/image-result',type:'image'},
    {fileUrl:'/api/results/video-result',mediaType:'video'},
    {audioUrl:'/api/results/audio-result'},
    'https://example.com/fallback.png'
  ]}
};
console.log(JSON.stringify(c.normalizeRunningHubOutputs(payload)));
"""
        data = run_node(script)

        self.assertEqual([item["kind"] for item in data], ["image", "video", "audio", "image"])
        self.assertEqual(data[0]["url"], "/api/results/image-result")
        self.assertEqual(data[1]["url"], "/api/results/video-result")
        self.assertEqual(data[2]["url"], "/api/results/audio-result")

    def test_result_group_single_item_drag_keeps_result_id_for_existing_and_new_nodes(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn('data-source-result-id="${escapeAttr(item.resultId)}"', source)
        self.assertIn("sourceResultId:String(port.dataset.sourceResultId || '').trim()", source)
        self.assertIn("connectInputNodeWithTargetField(fromId, toId, {sourceResultId}, e)", source)
        self.assertIn(
            "connectInputNodeWithTargetField(fromId, toId, {sourceResultId:pendingConnection.sourceResultId})",
            source,
        )

    def test_execution_node_counts_expanded_media_inputs_before_source_nodes(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("Object.values(textGenerationRequestForNode(node).inputCounts || {})", source)
        self.assertIn(": inputImagesFor(node).filter(item => item?.url).length;", source)
        self.assertIn("inputCount:mediaInputCount || inputNodesFor(node).length", source)

    def test_input_thumbnails_use_media_specific_labels_and_previews(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn("function inputThumbLabel(kind, count)", source)
        self.assertIn("smart.inputTextNum", source)
        self.assertIn("smart.inputVideoNum", source)
        self.assertIn("smart.inputAudioNum", source)
        self.assertIn("smart.inputImageNum", source)
        self.assertIn('kind === \'text\'\n            ? `<div class="input-thumb-text"', source)
        self.assertIn('<div class="input-thumb-media">${inner}</div>', source)
        self.assertIn('.input-thumb-media {', css)
        self.assertIn('scrollbar-width:none !important', css)

    def test_text_generation_hides_redundant_input_summary_row(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        renderer = source[
            source.index("function renderTextGenerationParams"):
            source.index("function renderApiParams")
        ]

        self.assertNotIn("text-generation-input-summary", renderer)
        self.assertNotIn("smart.textInputNone", renderer)
        self.assertIn("errorToast((error.message || tr('smart.noVerifiedTextModel'))", source)

    def test_connection_kind_keeps_execution_outputs_out_of_model_inputs(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const execution={type:c.NODE_TYPES.imageGenerator};
const material={type:c.NODE_TYPES.material};
const group={type:c.NODE_TYPES.resultGroup};
console.log(JSON.stringify({
  executionToMaterial:c.connectionKindForNodes(execution,material),
  materialToExecution:c.connectionKindForNodes(material,execution),
  groupToExecution:c.connectionKindForNodes(group,execution)
}));
"""
        data = run_node(script)

        self.assertEqual(data["executionToMaterial"], "input")
        self.assertEqual(data["materialToExecution"], "input")
        self.assertEqual(data["groupToExecution"], "input")

    def test_connection_matrix_covers_material_execution_results_and_tool_nodes(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const node=(type,id=type)=>({id,type});
const types={
  material:c.NODE_TYPES.material,
  image:c.NODE_TYPES.imageGenerator,
  video:c.NODE_TYPES.videoGenerator,
  audio:c.NODE_TYPES.audioGenerator,
  aiApp:c.NODE_TYPES.aiApp,
  comfy:c.NODE_TYPES.comfyWorkflow,
  resultGroup:c.NODE_TYPES.resultGroup,
  prompt:'smart-prompt',
  loop:'smart-loop',
  group:'smart-group',
  minimax:'smart-minimax'
};
const pairs=[
  ['material','image'],['material','video'],['material','audio'],['material','aiApp'],['material','comfy'],
  ['material','prompt'],['material','loop'],['material','minimax'],
  ['image','material'],['video','material'],['audio','material'],['aiApp','material'],['comfy','material'],
  ['resultGroup','image'],['resultGroup','video'],['resultGroup','audio'],['resultGroup','aiApp'],['resultGroup','comfy'],['resultGroup','loop'],
  ['prompt','image'],['prompt','video'],['prompt','audio'],['prompt','aiApp'],['prompt','comfy'],['prompt','loop'],
  ['loop','image'],['loop','video'],['loop','audio'],['loop','aiApp'],['loop','comfy'],['loop','material'],
  ['group','image'],['group','video'],['group','audio'],['group','aiApp'],['group','comfy'],['group','loop']
];
const allowed=Object.fromEntries(pairs.map(([from,to])=>[`${from}->${to}`,c.canConnectNodes(node(types[from],from),node(types[to],to))]));
const denied={
  executionToExecution:c.canConnectNodes(node(types.image,'a'),node(types.video,'b')),
  materialToMaterial:c.canConnectNodes(node(types.material,'a'),node(types.material,'b')),
  resultGroupToPrompt:c.canConnectNodes(node(types.resultGroup,'a'),node(types.prompt,'b')),
  self:c.canConnectNodes(node(types.material,'same'),node(types.image,'same'))
};
console.log(JSON.stringify({allowed,denied}));
"""
        data = run_node(script)

        self.assertTrue(all(data["allowed"].values()))
        self.assertTrue(data["denied"]["executionToExecution"])
        self.assertTrue(data["denied"]["materialToMaterial"])
        self.assertFalse(data["denied"]["self"])
        self.assertFalse(data["denied"]["resultGroupToPrompt"])

    def test_canvas_line_and_drag_connections_share_the_contract_matrix(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        connect = source[source.index("function connectInputNode"):source.index("function upstreamConnectionsForKinds")]
        auto_connect = source[source.index("function canAutoConnectDraggedNode"):source.index("function restoreDraggedNodePosition")]

        self.assertIn("SMART_NODE_CONTRACT.canConnectNodes(from, to)", connect)
        self.assertIn("SMART_NODE_CONTRACT.canConnectNodes(sourceNode, targetNode)", auto_connect)

    def test_result_id_is_inferred_from_stable_local_result_url(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
console.log(JSON.stringify(c.normalizeMediaReference({url:'/api/results/res_abc123'},0)));
"""
        data = run_node(script)

        self.assertEqual(data["resultId"], "res_abc123")

    def test_text_execution_result_creates_material_and_result_connection(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const result=c.createTextResultMaterial(
  {id:'prompt-1'},
  '# 标题\\n\\n正文',
  {
    id:'material-1',
    x:480,
    y:120,
    url:'/api/results/res_text_1',
    resultId:'res_text_1',
    provider:'codex',
    model:'gpt-5.5'
  }
);
console.log(JSON.stringify(result));
"""
        data = run_node(script)

        self.assertEqual(data["node"]["type"], "smart-material")
        self.assertEqual(data["node"]["sourceKind"], "result")
        self.assertEqual(data["node"]["images"][0]["kind"], "text")
        self.assertEqual(data["node"]["images"][0]["text"], "# 标题\n\n正文")
        self.assertEqual(data["node"]["images"][0]["resultId"], "res_text_1")
        self.assertEqual(data["connection"], {"from": "prompt-1", "to": "material-1", "kind": "result"})

    def test_all_execution_types_create_independent_result_materials(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const types=[
  c.NODE_TYPES.textGenerator,
  c.NODE_TYPES.imageGenerator,
  c.NODE_TYPES.videoGenerator,
  c.NODE_TYPES.audioGenerator,
  c.NODE_TYPES.musicGenerator,
  c.NODE_TYPES.aiApp,
  c.NODE_TYPES.comfyWorkflow
];
const results=types.map((type,index)=>c.createExecutionResultMaterial(
  {id:`run-${index}`,type,runRef:{runId:`ledger-${index}`}},
  [{url:`/api/results/result-${index}`,kind:index===0?'text':'image',text:index===0?'文本结果':''}],
  {id:`material-${index}`,x:400,y:index*80,title:'生成结果'}
));
console.log(JSON.stringify(results));
"""
        data = run_node(script)

        self.assertEqual(len(data), 7)
        for index, result in enumerate(data):
            self.assertEqual(result["node"]["type"], "smart-material")
            self.assertEqual(result["node"]["sourceKind"], "result")
            self.assertEqual(result["node"]["sourceExecutionNodeId"], f"run-{index}")
            self.assertEqual(result["node"]["sourceRunId"], f"ledger-{index}")
            self.assertEqual(result["connection"], {"from": f"run-{index}", "to": f"material-{index}", "kind": "result"})

    def test_execution_run_state_clears_old_errors_and_keeps_failure_details(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const node={id:'run-1',type:c.NODE_TYPES.videoGenerator,runError:'旧错误',runErrorAt:1};
c.markExecutionRunStarted(node,100);
const started=JSON.parse(JSON.stringify(node));
c.markExecutionRunFailed(node,new Error('平台拒绝了请求'),160);
const failed=JSON.parse(JSON.stringify(node));
c.markExecutionRunStarted(node,200);
c.markExecutionRunSucceeded(node,'succeeded',260);
console.log(JSON.stringify({started,failed,succeeded:node}));
"""
        data = run_node(script)

        self.assertEqual(data["started"]["runStatus"], "validating")
        self.assertNotIn("runError", data["started"])
        self.assertEqual(data["failed"]["runStatus"], "failed")
        self.assertEqual(data["failed"]["runError"], "平台拒绝了请求")
        self.assertEqual(data["failed"]["runErrorAt"], 160)
        self.assertEqual(data["succeeded"]["runStatus"], "succeeded")
        self.assertNotIn("runError", data["succeeded"])

    def test_execution_result_material_owns_its_independent_run_state(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const source={id:'text-runner',type:c.NODE_TYPES.textGenerator};
const result={id:'result-1',type:c.NODE_TYPES.material,sourceExecutionNodeId:source.id};
c.markExecutionRunStarted(result,100);
c.markExecutionRunFailed(result,new Error('本次调用失败'),180);
console.log(JSON.stringify({source,result}));
"""
        data = run_node(script)

        self.assertNotIn("runStatus", data["source"])
        self.assertEqual(data["result"]["runStatus"], "failed")
        self.assertEqual(data["result"]["runError"], "本次调用失败")
        self.assertEqual(data["result"]["sourceExecutionNodeId"], "text-runner")

    def test_all_execution_nodes_route_each_run_through_a_result_placeholder(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        generation = source[source.index("async function runGeneration"):source.index("async function runPromptLLMNode")]
        text_generation = source[source.index("async function runPromptLLMNode"):source.index("async function runSelectedNode")]

        self.assertIn("branchNode = createPendingOutputFromSource(node", generation)
        self.assertIn("runApiVideoGeneration(prompt, refs, settings, pendingNode", generation)
        self.assertIn("runApiAudioGeneration(prompt, refs, settings, pendingNode", generation)
        self.assertIn("runApiMusicGeneration(prompt, refs, settings, pendingNode", generation)
        self.assertIn("runRunningHubGeneration(prompt, runningHubRefsForNode(node, refs), settings, pendingNode", generation)
        self.assertIn("await failCanvasRun(pendingNode, e)", generation)
        self.assertIn("pendingNode = createPendingOutputFromSource(node, 1", text_generation)
        self.assertIn("const runSubject = pendingNode || node", text_generation)
        self.assertIn("finalizePendingNode(pendingNode, [textMedia], pendingMeta, 'text')", text_generation)
        self.assertIn("executionResultAbortControllers.set(pendingNode.id", text_generation)
        self.assertGreaterEqual(text_generation.count("signal:requestAbortController?.signal"), 2)
        self.assertNotIn("createExecutionResultMaterial(node", text_generation)

    def test_execution_failure_is_rendered_on_result_placeholder(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        i18n = (ROOT / "static/js/i18n/smart-canvas.js").read_text(encoding="utf-8")
        helpers = source[source.index("function createPendingOutputFromSource"):source.index("function createParallelLoopOutputNode")]
        lifecycle = source[source.index("async function recoverCanvasRun"):source.index("function canvasInputMetadataSource")]

        self.assertIn("sourceExecutionNodeId:sourceNode.id", helpers)
        self.assertIn("SMART_NODE_CONTRACT.markExecutionRunFailed(node, error)", lifecycle)
        self.assertIn("node.runStatus = 'failed'", lifecycle)
        self.assertIn("function runPlaceholderFailureHtml", source)
        self.assertIn("run-placeholder-failure-content", source)
        self.assertIn(".run-placeholder-failure-content", css)
        self.assertNotIn("removeFailedExecutionPlaceholders", source)
        self.assertIn('"smart.runFailedBadge": { zh: "运行失败", en: "Run failed" }', i18n)

    def test_running_result_placeholder_can_cancel_without_becoming_failure(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        i18n = (ROOT / "static/js/i18n/smart-canvas.js").read_text(encoding="utf-8")
        backend = (ROOT / "main.py").read_text(encoding="utf-8")
        cancel_flow = source[source.index("class CanvasRunCancelledSignal"):source.index("function executionNodeForRunSubject")]
        poller = source[source.index("async function pollSmartCanvasTask"):source.index("function finalizeSmartPendingTask")]

        self.assertIn('data-cancel-run="${escapeAttr(node.id)}"', source)
        self.assertIn("async function cancelExecutionResultRun", cancel_flow)
        self.assertIn("cancelledExecutionResultNodeIds.add(resultNode.id)", cancel_flow)
        self.assertIn("clearSmartNodeBusyState(resultNode)", cancel_flow)
        self.assertIn("removeEmptyRunPlaceholder(resultNode)", cancel_flow)
        self.assertIn("updateCanvasRunStatus(resultNode, 'cancelled')", cancel_flow)
        self.assertIn("executionResultAbortControllers.get(resultNode.id)?.abort()", cancel_flow)
        self.assertIn("new CanvasRunCancelledSignal", poller)
        self.assertIn("task.status === 'cancelled'", poller)
        self.assertIn("String(node.runStatus || '') === 'failed'", source)
        self.assertIn(".run-placeholder-cancel", css)
        self.assertIn('"smart.cancelRun": { zh: "停止运行", en: "Stop run" }', i18n)
        self.assertIn('"smart.runCancelled": { zh: "已取消运行", en: "Run cancelled" }', i18n)
        self.assertIn('CANVAS_TASK_HANDLES: Dict[str, asyncio.Task] = {}', backend)
        self.assertIn('@app.post("/api/canvas-tasks/{task_id}/cancel")', backend)
        self.assertIn("handle.cancel()", backend)
        self.assertIn("from canvas_core.task_execution import execute_task", backend)
        self.assertIn("except asyncio.CancelledError", (ROOT / "canvas_core/task_execution.py").read_text())

    def test_text_material_content_can_feed_downstream_execution(self):
        script = """
const c=require('./static/js/smart-node-contract.js');
const node={
  id:'material-1',
  type:c.NODE_TYPES.material,
  images:[
    {kind:'text',text:'第一段'},
    {url:'/api/results/res_text_2',kind:'text',content:'第二段'}
  ]
};
console.log(JSON.stringify({text:c.textContentForNode(node)}));
"""
        data = run_node(script)

        self.assertEqual(data["text"], "第一段\n\n第二段")

    def test_text_material_renders_markdown_and_edits_as_new_result(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn("function safeMarkdownPreviewHtml", source)
        markdown_preview = source[
            source.index("function safeMarkdownPreviewHtml"):
            source.index("function imageResolutionLabel")
        ]
        self.assertNotIn(".slice(", markdown_preview)
        self.assertIn('class="node-img media-card media-text-card"', source)
        self.assertIn("openTextMaterialEditor(nodeId, imageIndex)", source)
        self.assertIn("/api/canvas-text-results", source)
        self.assertIn("SMART_NODE_CONTRACT.createTextResultMaterial(sourceNode", source)
        self.assertIn("source.resultVersions.push(CanvasCreation.snapshot", source)
        self.assertIn(".media-text-card", css)
        self.assertIn(".smart-text-editor-modal", css)

    def test_text_material_is_prompt_content_not_media_reference(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("if(isSmartMaterialNode(node) || isSmartExecutionNode(node)) return SMART_NODE_CONTRACT.textContentForNode(node);", source)
        self.assertIn("const inputPrompt = inputPromptTextFor(node, ctx).trim();", source)
        self.assertIn("function imageRefsOnly(refs)", source)
        self.assertIn("mediaKindForItem(ref) === 'image'", source)
        self.assertIn("function videoRefsOnly(refs)", source)
        self.assertIn("mediaKindForItem(ref) === 'video'", source)
        self.assertIn("function audioRefsOnly(refs)", source)
        self.assertIn("mediaKindForItem(ref) === 'audio'", source)

    def test_generation_info_keeps_references_and_supports_draft_regeneration(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")

        self.assertIn("function smartGenerationSnapshotRefs(snapshot)", source)
        snapshot = source[source.index("function smartGenerationSnapshotFromNode"):source.index("function smartGenerationVersions")]
        self.assertIn("const stableSnapshotId", snapshot)
        self.assertIn("id:stableSnapshotId ? `node:${stableSnapshotId}`", snapshot)
        refs = source[source.index("function smartGenerationSnapshotRefs"):source.index("function smartGenerationSnapshotFromNode")]
        self.assertIn("runInputRefs", refs)
        self.assertIn("runPromptRefs", refs)
        self.assertIn("runSnapshot?.refs", refs)
        self.assertIn("runSnapshot?.images", refs)
        self.assertIn("runSnapshot?.videos", refs)
        self.assertIn("runSnapshot?.audios", refs)
        self.assertIn("sources.flat()", refs)
        self.assertIn("hasMentionReferenceContent(ref)", refs)
        self.assertNotIn("snapshot?.runInputRefs || snapshot?.runPromptRefs", source)

        info = source[source.index("function smartGenerationInfoPromptValue"):source.index("async function runFixedTextGenerationSnapshot")]
        self.assertIn('data-generation-info-prompt', info)
        self.assertIn("function smartGenerationInfoSnapshotWithDraft", info)
        self.assertIn("function smartGenerationInfoPromptFromEditor", info)
        self.assertIn("data-capability-param", info)
        self.assertIn('contenteditable="${profile ? \'true\' : \'false\'}"', info)
        self.assertIn("smartGenerationInfoSnapshotWithDraft(baseSnapshot, draft)", source)
        self.assertIn("rerunSmartGeneratedMaterial(smartGenerationInfoNodeId, smartGenerationInfoDraft)", source)
        self.assertIn("function generationRerunOverlayHtml(node)", source)
        self.assertIn('data-cancel-generation-rerun', source)
        self.assertIn("function cancelSmartGenerationRerun(nodeId)", source)
        self.assertIn("generationRerunCancelRequested", source)
        self.assertIn('data-generation-info-reference="1"', source)
        self.assertIn("showReferenceHoverPreview(token, referenceFromMentionToken(token))", info)
        self.assertIn("runInputRefs = cloneSmartSettings(refs)", info)
        self.assertIn("runPromptRefs = cloneSmartSettings(refs)", info)
        self.assertIn(".generation-info-prompt-editor", css)
        self.assertIn(".generation-info-parameter-editor", css)
        self.assertIn(".generation-rerun-overlay", css)
        self.assertIn(".mention-preview { position:fixed; z-index:2600", css)

        attach = source[source.index("function attachRunMeta"):source.index("function stripRunInputMeta")]
        self.assertIn("meta.inputRefs) && meta.inputRefs.length", attach)
        self.assertIn("meta.promptRefs || []", attach)

        stripped = source[source.index("function stripRunInputMeta"):source.index("function connectionSourceResultId")]
        self.assertIn("meta.inputRefs) && meta.inputRefs.length", stripped)
        self.assertNotIn("inputRefs:meta.inputRefs || meta.promptRefs", stripped)

        restore_start = source.index("async function restoreCanvasRuns")
        load_start = source.index("async function loadCanvas()", restore_start)
        restored = source[restore_start:load_start]
        self.assertIn("function smartRunRecordedReferences", restored)
        self.assertIn("run?.standard_request?.inputs", restored)
        self.assertIn("target.runInputRefs = cloneSmartSettings(refs)", restored)
        self.assertIn("(node.resultVersions || []).forEach(restoreGenerationReferences)", restored)

    def test_generated_material_accepts_input_connections_and_merges_result_versions(self):
        contract = """
const c=require('./static/js/smart-node-contract.js');
const source={id:'source',type:'smart-material',sourceKind:'input',images:[{url:'/assets/input/a.png',kind:'image'}]};
const target={id:'result',type:'smart-material',sourceKind:'result',images:[{url:'/api/results/res-1',kind:'image'}]};
console.log(JSON.stringify({can:c.canConnectNodes(source,target),kind:c.connectionKindForNodes(source,target)}));
"""
        self.assertEqual(run_node(contract), {"can": True, "kind": "input"})

        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
        self.assertIn("function mergeSmartGenerationVersions", source)
        self.assertIn("const resultVersions = mergeSmartGenerationVersions(local.resultVersions, remote.resultVersions)", source)
        self.assertIn("function smartGenerationInfoInputRefs", source)
        self.assertIn("inputImagesFor(node)", source)
        self.assertIn("manualReferenceImagesFor(node)", source[source.index("function smartGenerationInfoInputRefs"):source.index("function smartGenerationReferenceHtml")])
        self.assertIn("connectionBacked:true", source[source.index("function smartGenerationInfoInputRefs"):source.index("function smartGenerationReferenceHtml")])
        self.assertNotIn("data-generation-info-add-reference", source)
        self.assertNotIn("openSmartGenerationInfoReferencePicker", source)
        self.assertNotIn("generationInfoMentionTargetNodeId", source)
        self.assertIn("preferredVersionSource", source[source.index("function mergeSmartNode"):source.index("function mergeSmartNodeLists")])

    def test_material_node_copy_does_not_claim_generation_capability(self):
        source = (ROOT / "static/js/i18n/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn('"smart.createImportNode": { zh: "素材", en: "Material" }', source)
        self.assertIn('"smart.hintEmpty": { zh: "支持文本、图片、视频和音频素材"', source)
        self.assertNotIn("也可直接文生图", source)
        self.assertNotIn("run text-to-image directly", source)

    def test_new_execution_nodes_use_contract_normalization(self):
        source = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

        self.assertIn("runSettings:SMART_NODE_CONTRACT.normalizeExecutionSettings({type}, cloneSmartSettings", source)
        self.assertIn("if(!target.videoProvider) target.videoModel = '';", source)
        self.assertIn("if(!target.audioProvider) target.audioModel = '';", source)


if __name__ == "__main__":
    unittest.main()
