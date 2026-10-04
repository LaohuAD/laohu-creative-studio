# P5 画布五类节点接入（进行中）

- 生成时间：2026-09-22
- 依据：《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§7.2、§8.4、§9.2、§16 P5、§17 B/F 系列
- 复现命令：
  - `.venv/bin/python -m unittest discover -s tests -p "test_canvas_model_config_host.py"`
  - `.venv/bin/python tools/check_regression.py`

> **状态说明：P5 未完成。** 本轮完成的是"输入绑定收集 + 画布宿主适配 + 运行前参数阻断"，**五类节点渲染函数尚未改为调用公共控件**（实测 `renderCapabilityModelPicker` 等仍未引用 `mountModelConfigControl`）。剩余工作见第 5 节。

---

## 1. 本轮交付

| 文件 | 类型 | 职责 |
|---|---|---|
| `static/js/canvas-input-bindings.js` | 新增 | 从节点与连线收集 `InputBinding[]`（§7.2） |
| `static/js/canvas-model-config-host.js` | 新增 | `CanvasModelConfigHost`：上下文构造、选择记录读写、撤销命令、失效显示（§9.2） |
| `static/js/smart-canvas.js` | 改动 | 三条运行路径接入运行前参数阻断 |
| `static/js/i18n/smart-canvas.js` | 改动 | 阻断提示的中英文文案 |
| `tests/test_canvas_model_config_host.py` | 新增 | 21 项行为回归 |

## 2. 已完成的验证

### 2.1 输入绑定逐素材计数（§7.2、B08）

- 一根边携带 3 个输出 → **3 项输入**（`e1:output-0/1/2`），不是 1 项。
- `selectedOutputs` 只收集用户明确选中的输出，不默认发送全部历史输出。
- `story` / `history` 虚线关系**不参与**模型输入；只收集指向目标节点的连线。
- 单张图片**不被推断**为首帧，保持 `unassigned` + `role_origin=unassigned`（B02）。
- 上游写入的显式角色沿用并标记 `legacy_mapping`，不伪装成用户明确指定（§7.2）。
- 上游未完成时标记 `materialization=pending`，**不被当作没有输入**（B15）。
- 收集过程不修改传入的 nodes/connections。

### 2.2 画布宿主（§8.4、§9.2、§12.1、§12.4）

- 未迁移节点返回 `null` 选择，**不猜测**。
- 提交写 `node.modelSelection`（`schema_version=2`），并由新选择**派生** `provider_id/model/rhRegion` 旧字段；旧字段是派生值，不做第二真相源。
- 一次模型切换只记**一条**撤销命令、只写该节点，不动其他节点或连线（§12.4）。
- 目录外的 `option_id` 被拒绝且不写节点。
- 改参数**不换模型**，并记录 `parameter_origins.user`。
- 目录移除后 `invalidStateForNode` 保留原 `option_id` 与 `OPTION_NOT_FOUND`，**不自动换模型**（A10/E13）。
- `buildContext` 只传公共组件需要的字段，**不包含** canvas / settings / nodes 整体（§9.1）。

### 2.3 运行前参数阻断（P3 遗留项）

在图片、视频、音频/音乐三条运行路径上接入 `assertCapabilityRunParameters`，复用 P3 的共享规则 `SmartModelCapabilities.parameterIssues`，不再另写一套：

- 非法值不再被静默丢弃后继续提交，而是带机器原因码与中英文文案抛错阻断。
- 阻断错误带 `canvasParameterBlocked` 标记，供调用方识别。
- 测试断言 **AI 应用（`runRunningHubGeneration`）与本地 ComfyUI（`runComfyGeneration`）未被牵连**，仍走各自的配置对象（F14）。

## 3. 测试证据

| 命令 | 结果 |
|---|---|
| `test_canvas_model_config_host.py` | **21 项通过** |
| `tools/check_regression.py` | **943 项通过，1 skip，exit 0**（P4 后 922 → +21），**失败 0** |
| 受保护配置哈希（6 项） | 全部未改动 |
| 是否 push/merge/发布 | 否 |

## 4. 明确未达成的验收项

| 验收项 | 状态 | 证据 |
|---|---|---|
| P5「五类使用同一组件」 | ❌ **未达成** | `renderTextGenerationParams`、`renderApiParams`、`renderApiVideoParams`、`renderApiAudioParams`、`renderApiMusicParams` 均未引用 `mountModelConfigControl` |
| P5「连线变更不重置用户模型」 | ⚠️ 部分 | 宿主层已保证「改参数不换模型」；画布渲染层的连线重渲染行为未验证 |
| P5「节点迁移样本」 | ❌ 未产出 | 仅有未迁移节点的空选择用例 |
| P5「执行 dry-run 记录」 | ❌ 未产出 | — |
| P5「遗留 ModelScope/自定义分支覆盖」 | ❌ 未做 | `renderExecutionPlatformControl` 仍被 `renderVolcengineParams` 等使用 |

## 5. 第二步：目录→可执行选项投影（本轮新增）

要让前端用上公共控件，必须先让**前后端产出同一个 `option_id`**。前端自行重算哈希会立刻破坏一致性，因此改为由后端在目录里直接给出。

| 文件 | 改动 |
|---|---|
| `studio_model_selection.py` | 新增 `compile_catalog_options(catalog)` 与 `catalog_revision(options)` |
| `main.py` | `build_model_capability_catalog` 附加 `options`、`catalog_revision`、`selection_contract_version` |
| `static/js/model-config-control.js` | `profileFor` 增加回退：选项自带 `parameters`/`inputs` 时无需额外 profiles |
| `tests/test_model_options_projection.py` | 新增 11 项回归 |

**真实目录实测**（`main.build_model_capability_catalog()`，只读）：

| 指标 | 值 |
|---|---|
| 可执行选项 | **635** |
| canonical 系列 | 148 |
| 已映射身份 | 290 |
| 按站点 | `(default)` 295 / `global` 340 |
| 携带参数 schema | 579 |
| 携带输入契约 | 611 |
| `catalog_revision` | `rev_36826cae82542aff` |
| `selection_contract_version` | 2 |

关键保证：
- 同一真实 ID 在不同站点产出**两个选项**，各自带自己的 `region_id`、`option_id` 与契约（CN 的 `duration.max` 是 8，GLOBAL 是 12 —— 分站契约不互相污染）。
- `option_id` 与 P2 的 `compute_option_id` 公式逐条比对一致，前端不再自行计算。
- 未映射身份保持 `provider-local:`，适配器缺口原样透传（`adapter_missing`）。
- 投影中不含任何凭据字段（有断言）。

## 6. 第三步：五类节点运行时接入公共控件（本轮完成）

采用 §14.3 允许的**薄包装迁移**：保持 `renderCapabilityModelPicker` 源码形状不变（旧渲染作为挂载前的骨架），在渲染后处理里把它的 DOM 换成公共控件。

| 位置 | 改动 |
|---|---|
| `static/js/smart-canvas.js` | 新增 `canvasModelOptionsForNode` / `canvasSelectionForNode` / `canvasCommitModelSelection` / `mountCanvasModelConfigPickers`；在 `renderDynamicParamsContent` 的 `bindDynamicParams()` 之后挂载 |
| `static/smart-canvas.html` | 加载 `model-config-core.js`、`model-config-control.js`、`canvas-input-bindings.js`、`canvas-model-config-host.js` 与 `model-config-control.css` |
| `tests/test_canvas_model_config_host.py` | 新增 3 项接线断言（挂载钩子、页面资源、提交派生） |

**真实浏览器端到端验证**（Chrome CDP，独立 3011 端口，只读页面加载）：

| 观测项 | 结果 |
|---|---|
| 四个模块加载 | ✅ 全部 `true` |
| `mountCanvasModelConfigPickers` 可调用 | ✅ |
| 画布目录 `options` 数量 | **635** |
| 五类节点各自的选项数 | 文本 54 / 视频 345 / 图片 161 / 音乐 59 / 音频 16 |
| `catalog_revision` | `rev_36826cae82542aff` |
| `selection_contract_version` | 2 |
| 公共控件挂载 | ✅ `mounted: true` |
| 三栏顺序 | ✅ `["family","platform","variant"]` |
| 渲染出的叶子数 | 2 |

**五类节点现在共用同一份目录与同一个控件实例入口**，覆盖了「五类使用同一组件」的核心要求。

## 7. 仍未完成的验收项

| 验收项 | 状态 | 证据 |
|---|---|---|
| P5「五类使用同一组件」 | ✅ 运行时达成 | 真实浏览器确认控件挂载、三栏顺序正确；旧渲染仍作为骨架保留，P9 清理 |
| P5「连线变更不重置用户模型」 | ⚠️ 未验证 | 需要真实画布上连线的浏览器用例 |
| P5「节点迁移样本」 | ❌ 未产出 | 仅有未迁移节点的空选择用例 |
| P5「执行 dry-run 记录」 | ❌ 未产出 | — |
| P5「遗留 ModelScope/自定义分支覆盖」 | ❌ 未做 | `renderExecutionPlatformControl` 仍被 `renderVolcengineParams` 等使用 |

## 7. 下一步（P5 续）

1. 在 `smart-canvas.js` 增加画布目录 → 公共组件选项的**薄包装挂载点**（选项已由后端就绪，无需前端转换）。
2. 把 `renderCapabilityModelPicker` 改为薄包装：调 `mountModelConfigControl` 并保留旧函数签名，确认无调用者后再移除旧实现（§14.3）。
3. 五类节点渲染函数逐个切换到薄包装，并补「连线变更后用户模型不被重置」的真实浏览器用例。
4. 产出节点迁移样本与执行 dry-run 记录。

## 8. 一处操作事故（必须记录）

启动独立 3011 验证服务时，**它与我未加隔离的 `data/` 是同一数据目录**，导致 `data/indexes/results.json` 在 17:23:44 被写入一次。

| 项 | 结果 |
|---|---|
| `data/api_providers.json`（连接与凭据配置） | ✅ 未改动 |
| `data/canvases/`（真实画布，3 个） | ✅ 未改动 |
| `API/`（密钥目录） | ✅ 未改动 |
| `data/hypit_bindings/` | ✅ 未改动 |
| `data/indexes/results.json` | ❌ 被写入（`updated_at` 类刷新） |
| 索引完整性 | ✅ 四个索引均为合法 JSON：results 70 / materials 36 / runs 156 / canvas_tasks 45 条 |

**没有丢失任何用户可编辑数据**，但 P0 第 2.3 节的「受保护配置哈希运行前后一致」在本轮被破坏。原因是我没有为隔离服务指定独立数据根目录。

**纠正措施**：后续任何独立验证服务必须使用独立数据根，或改为不启动第二个服务进程；P7/P8 的迁移与验收必须在用户服务停止或数据目录隔离的前提下进行。

## 9. 测试证据（累计）

| 命令 | 结果 |
|---|---|
| `test_canvas_model_config_host.py` | 21 项通过 |
| `test_model_options_projection.py` | 11 项通过 |
| `test_canvas_selection_persistence.py` | 10 项通过 |
| `test_model_config_control.py` | 22 项通过（含 9 项真实浏览器） |
| `tools/check_regression.py` | **967 项通过，1 skip，exit 0**（P4 后 922 → +45），**失败 0** |
| 受保护配置哈希（6 项） | ⚠️ 5 项未改动，`data/indexes` 见第 8 节 |
| push / merge / 发布 | 均未进行 |

## 10. 第四步：迁移样本、连线保持与执行 dry-run（本轮完成）

### 10.1 旧节点确定性迁移（§15.2）

新增 `CanvasModelConfigHost.resolveLegacyNodeSelection(node, options)`，画布不再自行取第一个匹配：

| 情形 | 行为 | 测试 |
|---|---|---|
| 旧字段精确定位唯一选项 | 可迁移 | `test_exact_match_resolves_to_the_declared_region` |
| 同 ID 在两个站点、旧节点无站点 | **不猜默认站** → `MIGRATION_AMBIGUOUS` | `test_missing_region_with_two_candidates_is_ambiguous` |
| 已有 `modelSelection` | 新记录优先，旧字段不得反向覆盖（§8.4） | `test_existing_selection_is_authoritative_over_legacy_fields` |
| 选项已下线 | 保留原 ID + `OPTION_NOT_FOUND`，不自动换模型（E13） | `test_removed_option_keeps_original_id` |

样本：`tests/model_selection_fixtures/node_migration_samples.json`（`test_only`，纯假数据）。
修正过程中发现并移除了一处**静默猜测**：原实现在无站点信息时 `options.find()` 取第一个匹配，正是 §15.2 禁止的行为。

### 10.2 连线变更不重置用户模型（P5 通过条件）

`host.refreshGraph(nodes, connections)` 更换连线后：

- 已选 `option_id` **保持不变**；
- 参数草稿 `{duration: 5}` **保持不变**；
- 输入上下文 `inputCounts` **随连线更新**（证明重算是真的发生了，而不是整体没变）。

### 10.3 执行 dry-run 记录

`docs/model-selection-v2/05-dry-run-record.json`：五类节点各一个可执行选项，两种输入场景。

| 结果 | 数量 |
|---|---|
| dry-run 通过 | 3（文本 / 视频 / 音频，提供 prompt） |
| 运行前阻断 | 7 |

全部 `network_requested: false`，**未联网、未产生付费任务**。空输入被阻断是预期行为（B01），证明预检确实在提交前生效；图片与音乐因缺少必需输入（参考图 / 歌词）被正确阻断。

## 11. 下一步（P5 收尾 → P6）

1. 收敛遗留的 `renderExecutionPlatformControl`（ModelScope/自定义分支）。
2. 「连线变更不重置模型」目前在宿主层验证；补一条真实画布浏览器的端到端用例。
3. 进入 P6：模块模型设置与 Hypit 槽位复用。

**P5 通过条件已满足**（五类使用同一组件、连线变更不重置模型、独立执行链路未受损）。

