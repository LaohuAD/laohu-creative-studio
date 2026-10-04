"""P5 收尾：旧节点确定性迁移与「连线变更不重置用户模型」。

对应《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§15.2、§15.6、§16 P5。

全部使用虚构图数据，不读真实画布、不写用户数据、不发请求。
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CANVAS = ROOT / "static" / "js" / "smart-canvas.js"
HOST = ROOT / "static" / "js" / "canvas-model-config-host.js"
FIXTURE = ROOT / "tests" / "model_selection_fixtures" / "node_migration_samples.json"

PRELUDE = r"""
require('./static/js/model-config-core.js');
require('./static/js/canvas-input-bindings.js');
const Host = require('./static/js/canvas-model-config-host.js');
"""

OPTIONS = [
    {"option_id": "opt_0000000000000001", "connection_id": "fixture-conn",
     "catalog_model_id": "fixture-video-m", "region_id": "global", "operation": "text_to_video"},
    {"option_id": "opt_0000000000000002", "connection_id": "fixture-conn",
     "catalog_model_id": "fixture-video-m", "region_id": "cn", "operation": "text_to_video"},
    {"option_id": "opt_0000000000000003", "connection_id": "fixture-conn",
     "catalog_model_id": "fixture-other", "region_id": "global", "operation": "text_to_video"},
]


def run_node(script: str, timeout: int = 60):
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True, timeout=timeout
    )
    return json.loads(result.stdout)


def resolve(node: dict) -> dict:
    script = (
        PRELUDE
        + "\nconst node = " + json.dumps(node, ensure_ascii=False)
        + ";\nconst options = " + json.dumps(OPTIONS, ensure_ascii=False)
        + ";\nconsole.log(JSON.stringify(Host.resolveLegacyNodeSelection(node, options)));"
    )
    return run_node(script)


class LegacyMigrationSampleTests(unittest.TestCase):
    """§15.2：只做确定性映射，出现歧义就报待确认，绝不猜第一个候选。"""

    def test_fixture_is_test_only(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertTrue(payload["test_only"])
        self.assertTrue(payload["cases"])

    def test_exact_match_resolves_to_the_declared_region(self):
        result = resolve({"id": "n", "provider_id": "fixture-conn", "model": "fixture-video-m", "rhRegion": "cn"})
        self.assertTrue(result["resolved"])
        self.assertEqual(result["optionId"], "opt_0000000000000002", "必须落到声明的站点，不能落到 global")

    def test_missing_region_with_two_candidates_is_ambiguous(self):
        result = resolve({"id": "n", "provider_id": "fixture-conn", "model": "fixture-video-m", "rhRegion": ""})
        self.assertFalse(result["resolved"], "两个站点都可能时不得猜当前默认站（E12）")
        self.assertTrue(result["ambiguous"])
        self.assertEqual(result["reason"], "MIGRATION_AMBIGUOUS")

    def test_existing_selection_is_authoritative_over_legacy_fields(self):
        result = resolve({
            "id": "n", "provider_id": "stale", "model": "stale-model",
            "modelSelection": {"schema_version": 2, "option_id": "opt_0000000000000003", "revision": 3},
        })
        self.assertTrue(result["resolved"])
        self.assertEqual(result["optionId"], "opt_0000000000000003", "新记录优先，旧字段不得反向覆盖（§8.4）")

    def test_removed_option_keeps_original_id(self):
        result = resolve({"id": "n", "modelSelection": {"option_id": "opt_ffffffffffffffff"}})
        self.assertFalse(result["resolved"])
        self.assertEqual(result["keptOptionId"], "opt_ffffffffffffffff", "E13：下线选项必须保留原 ID")
        self.assertEqual(result["reason"], "OPTION_NOT_FOUND")
        self.assertFalse(result["ambiguous"], "下线不是歧义，需要的是修复入口而不是重新确认")

    def test_missing_positioning_fields_are_not_guessed(self):
        result = resolve({"id": "n", "provider_id": "", "model": ""})
        self.assertFalse(result["resolved"])
        self.assertEqual(result["reason"], "MIGRATION_AMBIGUOUS")

    def test_unknown_model_reports_option_not_found(self):
        result = resolve({"id": "n", "provider_id": "fixture-conn", "model": "never-existed"})
        self.assertFalse(result["resolved"])
        self.assertEqual(result["reason"], "OPTION_NOT_FOUND")


class SelectionSurvivesEdgeChangesTests(unittest.TestCase):
    """P5 通过条件：连线变更不得重置用户已选模型。"""

    def test_graph_refresh_keeps_committed_selection(self):
        result = run_node(PRELUDE + """
const nodes = [
  { id:'src', images:[{url:'/a.png'}] },
  { id:'src2', images:[{url:'/b.png'},{url:'/c.png'}] },
  { id:'dst', type:'image_generation', provider_id:'old', model:'old-model' }
];
let connections = [{ id:'e1', from:'src', to:'dst', kind:'flow' }];
const catalog = { options: [
  { option_id:'opt_cccccccccccccccc', connection_id:'conn-a', region_id:'global', operation:'text_to_image',
    catalog_model_id:'model-a', capability_provider_id:'p-a', canonical_family_id:'fam', readiness:'ready',
    selectable:true, runnable:true, reasons:[] }
], profiles: [] };
const host = Host.createCanvasModelConfigHost({
  nodes, connections, catalog,
  readNode: id => nodes.find(n => n.id === id) || null,
  writeNode: (id, patch) => Object.assign(nodes.find(n => n.id === id), patch),
  pushUndo: () => {}
});
host.commit('dst', { selection:{ optionId:'opt_cccccccccccccccc', parameters:{ duration:5 } } });
const afterCommit = host.selectionForNode(nodes[2]);
const contextBefore = host.buildContext('dst', 'live');

connections = [{ id:'e2', from:'src2', to:'dst', kind:'flow' }];
host.refreshGraph(nodes, connections);
const contextAfter = host.buildContext('dst', 'live');
const afterEdgeChange = host.selectionForNode(nodes[2]);

console.log(JSON.stringify({
  afterCommit: afterCommit.optionId,
  afterEdgeChange: afterEdgeChange.optionId,
  parameters: afterEdgeChange.parameters,
  countsBefore: contextBefore.inputCounts,
  countsAfter: contextAfter.inputCounts
}));
""")
        self.assertEqual(result["afterCommit"], "opt_cccccccccccccccc")
        self.assertEqual(result["afterEdgeChange"], "opt_cccccccccccccccc", "连线变更后已选模型必须保持不变")
        self.assertEqual(result["parameters"], {"duration": 5}, "参数草稿也不得被连线变更清空")
        self.assertNotEqual(result["countsBefore"], result["countsAfter"], "输入上下文应随连线更新")

    def test_canvas_delegates_selection_reading_to_the_host(self):
        source = CANVAS.read_text(encoding="utf-8")
        start = source.index("function canvasSelectionForNode(")
        body = source[start:start + 900]
        self.assertIn("resolveLegacyNodeSelection", body,
                      "已选读取必须走宿主确定性解析，不在画布内重写规则")
        self.assertNotIn("options.find(", body, "不得在画布内直接取第一个匹配")

    def test_host_module_exports_the_resolver(self):
        source = HOST.read_text(encoding="utf-8")
        self.assertIn("resolveLegacyNodeSelection: resolveLegacyNodeSelection", source)
        subprocess.run(["node", "--check", str(HOST)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
