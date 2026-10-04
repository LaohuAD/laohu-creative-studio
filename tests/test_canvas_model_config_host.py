"""P5 画布接入的行为回归。

对应《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§7.2、§8.4、§9.2、§16 P5、§17 B/F 系列。

全部使用虚构图数据（纯 JS 对象），不读真实画布、不写用户数据、不发请求。
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BINDINGS = ROOT / "static" / "js" / "canvas-input-bindings.js"
HOST = ROOT / "static" / "js" / "canvas-model-config-host.js"
CANVAS = ROOT / "static" / "js" / "smart-canvas.js"


def run_node(script: str, timeout: int = 60):
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True, timeout=timeout
    )
    return json.loads(result.stdout)


PRELUDE = r'''
require('./static/js/model-config-core.js');
const Inputs = require('./static/js/canvas-input-bindings.js');
const Host = require('./static/js/canvas-model-config-host.js');
'''


class InputBindingCollectionTests(unittest.TestCase):
    """§7.2 逐素材计数、连线语义、角色不猜测。"""

    def test_one_edge_with_three_outputs_counts_as_three_inputs(self):
        result = run_node(PRELUDE + r'''
const nodes = [
  { id:'src', images:[{url:'/a.png', resultId:'r1'},{url:'/b.png', resultId:'r1'},{url:'/c.png', resultId:'r1'}] },
  { id:'dst' }
];
const connections = [{ id:'e1', from:'src', to:'dst', kind:'flow' }];
const bindings = Inputs.collectInputBindings({ node:{id:'dst'}, nodes, connections });
console.log(JSON.stringify({count:bindings.length, ids:bindings.map(b=>b.binding_id), counts:Inputs.countBindings(bindings)}));
''')
        self.assertEqual(result["count"], 3, "B08：一根边的 3 个输出必须算 3 项输入")
        self.assertEqual(result["counts"], {"image": 3})
        self.assertEqual(result["ids"], ["e1:output-0", "e1:output-1", "e1:output-2"])

    def test_only_selected_outputs_are_collected(self):
        result = run_node(PRELUDE + r'''
const nodes = [{ id:'src', images:[{url:'/a.png'},{url:'/b.png'},{url:'/c.png'}] }, { id:'dst' }];
const connections = [{ id:'e1', from:'src', to:'dst', kind:'flow' }];
const bindings = Inputs.collectInputBindings({ node:{id:'dst'}, nodes, connections, selectedOutputs:{ src:[2] } });
console.log(JSON.stringify({ids:bindings.map(b=>b.binding_id)}));
''')
        self.assertEqual(result["ids"], ["e1:output-2"], "只收集用户明确选中的输出，不默认发送全部历史输出")

    def test_relation_connections_never_feed_model_input(self):
        result = run_node(PRELUDE + r'''
const nodes = [{ id:'src', images:[{url:'/a.png'}] }, { id:'dst' }];
const connections = [
  { id:'story', from:'src', to:'dst', kind:'story' },
  { id:'history', from:'src', to:'dst', kind:'history' },
  { id:'flow', from:'src', to:'dst', kind:'flow' }
];
const bindings = Inputs.collectInputBindings({ node:{id:'dst'}, nodes, connections });
console.log(JSON.stringify({ids:bindings.map(b=>b.binding_id), kinds:connections.map(c=>Inputs.isExecutionConnection(c))}));
''')
        self.assertEqual(result["ids"], ["flow:output-0"], "虚线关系不得参与模型输入")
        self.assertEqual(result["kinds"], [False, False, True])

    def test_outgoing_connections_are_ignored(self):
        result = run_node(PRELUDE + r'''
const nodes = [{ id:'src', images:[{url:'/a.png'}] }, { id:'dst' }];
const connections = [{ id:'e1', from:'dst', to:'src', kind:'flow' }];
const bindings = Inputs.collectInputBindings({ node:{id:'dst'}, nodes, connections });
console.log(JSON.stringify({count:bindings.length}));
''')
        self.assertEqual(result["count"], 0, "只收集指向目标节点的输入")

    def test_single_image_is_not_auto_assigned_a_role(self):
        result = run_node(PRELUDE + r'''
const nodes = [{ id:'src', images:[{url:'/a.png'}] }, { id:'dst' }];
const connections = [{ id:'e1', from:'src', to:'dst', kind:'flow' }];
const b = Inputs.collectInputBindings({ node:{id:'dst'}, nodes, connections })[0];
console.log(JSON.stringify({role:b.role, role_origin:b.role_origin}));
''')
        self.assertEqual(result["role"], "unassigned", "B02：单图不得被无条件锁定为首帧")
        self.assertEqual(result["role_origin"], "unassigned", "推断结果不得伪装成用户明确指定")

    def test_explicit_role_is_kept_and_marked_as_legacy_mapping(self):
        result = run_node(PRELUDE + r'''
const nodes = [{ id:'src', images:[{url:'/a.png', role:'first_frame'}] }, { id:'dst' }];
const connections = [{ id:'e1', from:'src', to:'dst', kind:'flow' }];
const b = Inputs.collectInputBindings({ node:{id:'dst'}, nodes, connections })[0];
console.log(JSON.stringify({role:b.role, role_origin:b.role_origin, roles:Inputs.roleCounts([b])}));
''')
        self.assertEqual(result["role"], "first_frame")
        self.assertEqual(result["role_origin"], "legacy_mapping")
        self.assertEqual(result["roles"], {"first_frame": 1})

    def test_source_result_id_filters_the_edge(self):
        result = run_node(PRELUDE + r'''
const nodes = [{ id:'src', images:[{url:'/a.png', resultId:'r1'},{url:'/b.png', resultId:'r2'}] }, { id:'dst' }];
const connections = [{ id:'e1', from:'src', to:'dst', kind:'flow', sourceResultId:'r2' }];
const bindings = Inputs.collectInputBindings({ node:{id:'dst'}, nodes, connections });
console.log(JSON.stringify({ids:bindings.map(b=>b.binding_id), assets:bindings.map(b=>b.asset_id)}));
''')
        self.assertEqual(result["ids"], ["e1:output-1"])
        self.assertEqual(result["assets"], ["/b.png"])

    def test_pending_upstream_is_marked_not_dropped(self):
        result = run_node(PRELUDE + r'''
const nodes = [{ id:'src', runStatus:'running', images:[] }, { id:'dst' }];
const running = Inputs.upstreamPending(nodes[0]);
const nodes2 = [{ id:'src2', images:[{url:''}] }, { id:'dst' }];
const connections = [{ id:'e', from:'src', to:'dst', kind:'flow' }, { id:'e2', from:'src2', to:'dst', kind:'flow' }];
const bindings = Inputs.collectInputBindings({ node:{id:'dst'}, nodes:nodes2.concat([nodes[0]]), connections });
console.log(JSON.stringify({running, materializations:bindings.map(b=>b.materialization)}));
''')
        self.assertTrue(result["running"], "B15：上游未完成必须被识别为计划态")
        self.assertIn("pending", result["materializations"], "未落地的输入不得被当作没有输入")

    def test_collection_does_not_mutate_inputs(self):
        result = run_node(PRELUDE + r'''
const nodes = [{ id:'src', images:[{url:'/a.png'}] }, { id:'dst' }];
const connections = [{ id:'e1', from:'src', to:'dst', kind:'flow' }];
const before = JSON.stringify({nodes, connections});
Inputs.collectInputBindings({ node:{id:'dst'}, nodes, connections });
console.log(JSON.stringify({unchanged: JSON.stringify({nodes, connections}) === before}));
''')
        self.assertTrue(result["unchanged"])


class CanvasHostTests(unittest.TestCase):
    """§8.4 选择记录、§9.2 宿主职责、§12.4 撤销。"""

    HARNESS = PRELUDE + r'''
function makeGraph() {
  const nodes = [
    { id:'src', images:[{url:'/a.png'},{url:'/b.png'}] },
    { id:'dst', type:'image_generation', provider_id:'old', model:'old-model' }
  ];
  const connections = [{ id:'e1', from:'src', to:'dst', kind:'flow' }];
  const catalog = { options: [
    { option_id:'opt_aaaaaaaaaaaaaaaa', connection_id:'conn-a', region_id:'global', operation:'text_to_image',
      catalog_model_id:'model-a', capability_provider_id:'p-a', canonical_family_id:'fam', profile_revision:'3',
      readiness:'ready', selectable:true, runnable:true, reasons:[] },
    { option_id:'opt_bbbbbbbbbbbbbbbb', connection_id:'conn-b', region_id:'cn', operation:'text_to_image',
      catalog_model_id:'model-b', capability_provider_id:'p-b', canonical_family_id:'fam', profile_revision:'1',
      readiness:'adapter_missing', selectable:false, runnable:false,
      reasons:[{code:'ADAPTER_MISSING', message:{zh:'适配器未完成', en:'adapter'}}] }
  ], profiles: [] };
  const undos = [];
  const writes = [];
  const host = Host.createCanvasModelConfigHost({
    nodes, connections, catalog,
    readNode: id => nodes.find(n => n.id === id) || null,
    writeNode: (id, patch) => { writes.push({id, patch}); Object.assign(nodes.find(n => n.id === id), patch); },
    pushUndo: command => undos.push(command)
  });
  return {nodes, connections, catalog, host, undos, writes};
}
'''

    def test_unmigrated_node_has_no_selection(self):
        result = run_node(self.HARNESS + r'''
const g = makeGraph();
console.log(JSON.stringify({selection: g.host.selectionForNode(g.nodes[1]), invalid: g.host.invalidStateForNode('dst')}));
''')
        self.assertIsNone(result["selection"], "未迁移节点不得被猜测出一个选择")
        self.assertFalse(result["invalid"]["migrated"])

    def test_commit_writes_selection_and_derives_legacy_fields(self):
        result = run_node(self.HARNESS + r'''
const g = makeGraph();
g.host.commit('dst', { selection:{ optionId:'opt_aaaaaaaaaaaaaaaa', parameters:{ duration:5 } } });
const node = g.nodes[1];
console.log(JSON.stringify({
  selection: node.modelSelection, legacy: {provider_id:node.provider_id, model:node.model, rhRegion:node.rhRegion},
  undoCount: g.undos.length, writeCount: g.writes.length
}));
''')
        self.assertEqual(result["selection"]["option_id"], "opt_aaaaaaaaaaaaaaaa")
        self.assertEqual(result["selection"]["schema_version"], 2)
        self.assertEqual(result["selection"]["parameters"], {"duration": 5})
        self.assertEqual(result["legacy"], {"provider_id": "conn-a", "model": "model-a", "rhRegion": "global"},
                         "旧字段必须由新选择派生，供旧读取路径使用")
        self.assertEqual(result["undoCount"], 1, "一次模型切换只记一条撤销命令")
        self.assertEqual(result["writeCount"], 1, "只写该节点，不动其他节点或连线")

    def test_commit_rejects_unknown_option(self):
        result = run_node(self.HARNESS + r'''
const g = makeGraph();
let error = '';
try { g.host.commit('dst', { selection:{ optionId:'opt_ffffffffffffffff', parameters:{} } }); }
catch (e) { error = e.message; }
console.log(JSON.stringify({error, writes:g.writes.length, undos:g.undos.length}));
''')
        self.assertIn("不属于当前目录", result["error"])
        self.assertEqual(result["writes"], 0, "目录外的选择不得写入节点")
        self.assertEqual(result["undos"], 0)

    def test_parameters_only_touch_parameters(self):
        result = run_node(self.HARNESS + r'''
const g = makeGraph();
g.host.commit('dst', { selection:{ optionId:'opt_aaaaaaaaaaaaaaaa', parameters:{ duration:5 } } });
g.host.applyParameters('dst', { resolution:'720p' });
const node = g.nodes[1];
console.log(JSON.stringify({selection: node.modelSelection, undoCount: g.undos.length}));
''')
        self.assertEqual(result["selection"]["option_id"], "opt_aaaaaaaaaaaaaaaa", "改参数不得换模型")
        self.assertEqual(result["selection"]["parameters"], {"duration": 5, "resolution": "720p"})
        self.assertEqual(result["selection"]["parameter_origins"]["resolution"], "user")
        self.assertEqual(result["undoCount"], 1, "参数草案不新增模型切换命令")

    def test_invalid_selection_keeps_original_id_and_reason(self):
        result = run_node(self.HARNESS + r'''
const g = makeGraph();
g.host.commit('dst', { selection:{ optionId:'opt_aaaaaaaaaaaaaaaa', parameters:{} } });
g.catalog.options = [g.catalog.options[1]];
const state = g.host.invalidStateForNode('dst');
console.log(JSON.stringify({missing:state.missing, kept:state.keptOptionId, codes:state.reasons.map(r=>r.code)}));
''')
        self.assertTrue(result["missing"], "A10/E13：目录移除后必须保留原选择")
        self.assertEqual(result["kept"], "opt_aaaaaaaaaaaaaaaa", "不得自动换模型")
        self.assertEqual(result["codes"], ["OPTION_NOT_FOUND"])

    def test_context_passes_only_what_the_component_needs(self):
        result = run_node(self.HARNESS + r'''
const g = makeGraph();
const ctx = g.host.buildContext('dst', 'live');
console.log(JSON.stringify({
  keys: Object.keys(ctx).sort(),
  nodeId: ctx.nodeId, phase: ctx.phase, counts: ctx.inputCounts,
  bindingCount: ctx.inputBindings.length,
  hasCanvasState: 'canvas' in ctx || 'settings' in ctx || 'nodes' in ctx
}));
''')
        self.assertFalse(result["hasCanvasState"], "§9.1：不得把整个 canvas 状态传进公共组件")
        self.assertEqual(result["nodeId"], "dst")
        self.assertEqual(result["counts"], {"image": 2})
        self.assertEqual(result["bindingCount"], 2)

    def test_blocked_option_stays_unselectable_in_catalog(self):
        result = run_node(self.HARNESS + r'''
const g = makeGraph();
const ctx = g.host.buildContext('dst', 'live');
const evaluated = g.catalog.options.map(option => Object.assign({}, option, {
  selectable: option.selectable !== false, reasons: option.reasons || []
}));
console.log(JSON.stringify(evaluated.map(o => ({id:o.option_id, selectable:o.selectable, code:(o.reasons[0]||{}).code||''}))));
''')
        self.assertFalse(result[1]["selectable"], "适配器缺口选项不得可选")
        self.assertEqual(result[1]["code"], "ADAPTER_MISSING")


class RunBlockWiringTests(unittest.TestCase):
    """§16 P5：参数阻断必须接在运行路径上；独立执行链路不得被牵连。"""

    SOURCE = CANVAS.read_text(encoding="utf-8")

    def test_three_generation_paths_block_on_parameter_issues(self):
        for marker in (
            "async function runApiGeneration(",
            "async function runApiVideoGeneration(",
        ):
            self.assertIn(marker, self.SOURCE)
        self.assertEqual(
            self.SOURCE.count("assertCapabilityRunParameters(profile, capabilityParameterSubmissionValues("), 3,
            "图片、视频、音频/音乐三条运行路径都必须先做参数校验",
        )

    def test_block_uses_shared_parameter_rules(self):
        start = self.SOURCE.index("function assertCapabilityRunParameters(")
        body = self.SOURCE[start:start + 900]
        self.assertIn("parameterIssues", body, "必须复用 P3 的共享参数规则，不能另写一套")
        self.assertIn("canvasParameterBlocked", body, "阻断错误必须可被调用方识别")
        self.assertIn("parameterIssues", body)

    def test_independent_execution_paths_are_not_wired(self):
        for name in ("async function runRunningHubGeneration(", "async function runComfyGeneration("):
            start = self.SOURCE.index(name)
            body = self.SOURCE[start:start + 4000]
            self.assertNotIn("assertCapabilityRunParameters", body,
                             f"{name} 使用独立配置对象，不得被普通参数规则牵连（F14）")

    def test_i18n_keys_exist_in_both_languages(self):
        source = (ROOT / "static" / "js" / "i18n" / "smart-canvas.js").read_text(encoding="utf-8")
        for key in ("smart.paramRequired", "smart.paramInvalid", "smart.errParameterBlocked"):
            self.assertIn(key, source, f"缺少 i18n 键 {key}")
        self.assertGreaterEqual(source.count("en:"), 3)

    def test_mount_hook_is_wired_into_the_render_pipeline(self):
        self.assertIn("function mountCanvasModelConfigPickers(", self.SOURCE)
        self.assertIn("mountCanvasModelConfigPickers(subject);", self.SOURCE,
                      "必须在 renderDynamicParamsContent 的后处理里挂载公共控件")
        # 五个渲染函数都经由 renderCapabilityModelPicker 进入同一入口
        for renderer in ("renderTextGenerationParams", "renderApiParams", "renderApiVideoParams",
                         "renderApiAudioParams", "renderApiMusicParams"):
            self.assertIn(f"function {renderer}(", self.SOURCE)
        self.assertIn("[data-capability-model-picker]", self.SOURCE,
                      "挂载点必须锚定到五类节点共用的选择器容器")

    def test_canvas_page_loads_the_shared_modules(self):
        html = (ROOT / "static" / "smart-canvas.html").read_text(encoding="utf-8")
        for asset in ("model-config-core.js", "model-config-control.js",
                      "canvas-input-bindings.js", "canvas-model-config-host.js",
                      "model-config-control.css"):
            self.assertIn(asset, html, f"画布页面必须加载 {asset}")

    def test_commit_derives_legacy_fields_and_records_undo(self):
        start = self.SOURCE.index("function canvasCommitModelSelection(")
        body = self.SOURCE[start:start + 1400]
        self.assertIn("pushUndo()", body, "一次模型切换必须记撤销")
        self.assertIn("modelSelection", body, "新记录是真相源")
        self.assertIn("settings.provider_id", body, "旧字段由新选择派生（§8.4）")

    def test_new_modules_parse(self):
        for path in (BINDINGS, HOST):
            subprocess.run(["node", "--check", str(path)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
