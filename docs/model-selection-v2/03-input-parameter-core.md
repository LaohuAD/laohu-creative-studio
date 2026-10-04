# P3 输入/参数决策核心

- 生成时间：2026-09-22
- 依据：《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§6、§7、§11.3、§16 P3、§17 B/C 系列、§18
- 复现命令：
  - `.venv/bin/python -m unittest discover -s tests -p "test_model_input_evaluation.py"`
  - `.venv/bin/python tools/check_regression.py`

---

## 1. 新增与改动清单

| 文件 | 类型 | 职责 |
|---|---|---|
| `studio_model_evaluation.py` | 新增 | 输入绑定、角色分配、兼容性评估、原因码、参数默认/校验/协调、运行前校验与快照冻结 |
| `tests/test_model_input_evaluation.py` | 新增 | 45 项 P3 行为回归 |
| `tests/model_selection_fixtures/parameter_vectors.json` | 新增 | **前后端共享**参数校验测试向量（17 例） |
| `static/js/smart-model-capabilities.js` | **改动** | `effectiveParameters` 取消静默取整/裁剪/truthy 转换；新增 `parameterIssue` / `parameterIssues` |
| `tests/test_model_capabilities.py` | **改动** | 6 项旧断言按新契约更新（见第 5 节，未删除任何保护意图） |

## 2. 原因码表（§18.2 全覆盖，共 25 个）

| 原因码 | 用户文字方向 |
|---|---|
| `OPTION_NOT_FOUND` | 原模型选项已不存在，配置已保留待修复 |
| `CONNECTION_DISABLED` / `REGION_DISABLED` | 当前连接 / 站点已停用 |
| `CREDENTIAL_NOT_CONFIGURED` | 请先配置当前连接凭据 |
| `PROFILE_UNCONFIRMED` / `ADAPTER_MISSING` | 能力待确认 / 适配器未完成 |
| `HOST_OUTPUT_UNSUPPORTED` | 此模块不能接收该结果类型 |
| `OPERATION_NOT_ALLOWED` | 当前槽位不允许此任务模式 |
| `INPUT_TYPE_UNSUPPORTED` | 不支持这类输入素材 |
| `ROLE_AMBIGUOUS` / `ROLE_CONFLICT` | 请分配素材用途 / 显式用途与模式冲突 |
| `INPUT_REQUIRED` / `INPUT_COUNT_EXCEEDED` | 缺少必要输入 / 输入超出数量 |
| `INPUT_COMBINATION_INVALID` | 当前素材组合不符合接口要求 |
| `INPUT_METADATA_MISSING` / `INPUT_SPEC_EXCEEDED` | 无法读取素材规格 / 规格超限 |
| `UNCONSUMED_INPUT` | 存在尚未被使用的已选素材 |
| `PARAM_REQUIRED` / `PARAM_INVALID` | 必填参数未填 / 值不合法 |
| `PARAM_DEPENDENCY_CONFLICT` | 与当前模式或其它参数冲突 |
| `FIXED_PARAM_OVERRIDE` | 该字段由运行模式固定，不能单独覆盖 |
| `CATALOG_CHANGED` / `REVISION_CONFLICT` | 档案已更新 / 配置已在别处更新 |
| `MIGRATION_AMBIGUOUS` | 旧选择可对应多个接口，需要确认 |
| `EXECUTION_ACCEPTANCE_UNKNOWN` | 上游是否受理待核对，不自动重发 |

每个原因都带机器码 + 中英文文字，并可附具体数值（如「当前 4 张图片，最多 3 张」），不返回裸 `false`（§7.7）。

## 3. 规划表 7.9 场景覆盖

| 场景 | 实现行为 | 测试 |
|---|---|---|
| 没素材、未填提示词 | `selectable=true`，`runnable=false`，报 `INPUT_REQUIRED` | `test_b01_*` |
| 一张图片，无指定用途 | 保留首帧与参考两种合法解读 → `needs_binding` + `ROLE_AMBIGUOUS`，**不无条件锁定首帧** | `test_b02_*` |
| 两张图片，显式首/尾 | 仅匹配能消费两种角色的模式，三个素材全部被消费 | `test_b03_*` |
| 两张图片，无角色 | 要求确认，**不用连线先后顺序指定首尾** | `test_b04_*` |
| 图片＋驱动音频 | 只有声明 `driving_audio` 的契约可接受；普通参考音频契约报 `ROLE_CONFLICT` | `test_b06_*` |
| 只有尾帧 | 报 `ROLE_CONFLICT` + `INPUT_REQUIRED(role=first_frame)`，**不把尾帧改首帧** | `test_b07_*` |
| 一根边选中 3 个输出 | 按 3 份素材计数并全部消费 | `test_b08_*` |
| 4 张参考图，上限 3 | `INPUT_COUNT_EXCEEDED` + `UNCONSUMED_INPUT`，**不丢弃第 4 张继续运行** | `test_b09_*` |
| 各角色单独不超限、合计超全局上限 | `INPUT_COMBINATION_INVALID`，按宿主声明的总量上限判定 | `test_b10_*` |
| 任一未被消费的素材 | `UNCONSUMED_INPUT` 并列出 `unconsumed_binding_ids` | `test_b11_*` |
| 图片＋mask 但叶子不支持 | `ROLE_CONFLICT`，`runnable=false` | `test_b13_*` |
| 约束要求规格但元数据读取失败 | `INPUT_METADATA_MISSING`，运行阻断、配置保留 | `test_b14_*` |
| 上游未完成 | `planned` 上下文可配置，运行前再校验 | `test_b15_*` |
| 输出类型与宿主不符 | `HOST_OUTPUT_UNSUPPORTED` | `test_b19_*` |
| 槽位不允许该任务模式 | `OPERATION_NOT_ALLOWED` | `test_operation_not_allowed_by_host_slot` |

## 4. 关键实现决定

### 4.1 角色容量不得相加（§B10、§19.2）

后端原有的 `ModelCapabilityRegistry._media_limits` 把各角色的 `max` **相加**当成媒体类型总上限，会放行「每个角色都不超限、合计却超限」的组合。

新实现分两层独立检查：

1. **媒体容量** = 能接受该媒体的所有角色 `max` 之和；超出 → `INPUT_COUNT_EXCEEDED`。修正过程中发现我第一版错用「单个角色 max 比对媒体总数」，会让 `reference(1)+mask(1)` 的双角色场景误报为超量 —— 已由 `test_b11_*` 捕获并修正。
2. **宿主总量上限** 只读档案显式声明的 `input_total_max` / `input_max` / `input_contract.total_max`，缺失时**不做任何推断**；超出 → `INPUT_COMBINATION_INVALID`。

### 4.2 未被消费的素材必须阻断（§7.10）

新增 `_max_partial_assignment`：当不存在完整分配方案时求「最多能消费多少份」，据此给出未被消费的 binding 列表。三种结果对象都携带 `consumed_binding_ids` 与 `unconsumed_binding_ids`，后者非空即 `runnable=false`。

### 4.3 角色语义不被合并（§7.3）

`ROLE_ALIASES` 只归一化**同一语义的不同拼写**（`first`→`first_frame`、`reference_image`→`reference`）。`reference_video` / `motion_video` / `source_video` 保持三个独立角色，不被全局函数抹平。

### 4.4 参数只判定、不改写（§1.3、§16 P3 第 4 项）

`effectiveParameters` 原实现在运行路径上做三件无提示的修改：

| 原行为 | 新行为 |
|---|---|
| `Math.round()` 取整 | 非整数拒绝 |
| `Math.max/min` 裁剪到 min/max | 越界拒绝 |
| `['true','1'].includes(...)` 字符串 truthy 转换 | 只接受真实布尔值 |

现在非法值**不进入请求**，同时由 `parameterIssues` 逐字段报出，供界面标红与运行前阻断（§6.6「保留可见原值并标红，运行阻断，禁止自动压到最大值」）。档案未声明的参数仍然丢弃（原有不变量，未改动）。

> 注意：这里只解决「不静默改写」。**把 `parameterIssues` 接到画布运行按钮的阻断路径属于 P5**（画布五类节点接入），本轮未接。

### 4.5 条件表达式受限（§8.5）

只允许 `eq / in / all / any / not / count_lte`；非法操作符**显式抛错**，不静默降级为无限制（`test_c11_illegal_condition_operator_raises`）。

### 4.6 字符计数契约（C19）

`text_length()` 以 **Unicode 码点**计（Python `len()`）。前端必须使用 `[...text].length` 而不是 `text.length`，否则 emoji 等增补平面字符会得出更大的值，造成前后端漏检不一致。

## 5. 既有断言的更新说明（透明记录）

改动 `effectiveParameters` 后 6 项既有测试失败。按 §14.1「不得删除旧保护断言只为让测试变绿」，逐条核对后处理如下：

| 测试 | 原断言 | 处理 | 理由 |
|---|---|---|---|
| `test_frontend_drops_parameters_not_declared_by_strict_profile` | `resolution:{type:'enum'}`（无 options）下放行 `2k` | 给 profile 补上 `options:['1k','2k']`，断言不变 | 「未声明参数被丢弃」的保护**完整保留**；枚举无来源时拒绝是新增的 §6.2 约束 |
| `test_frontend_normalizes_strict_parameter_values` | 期望 `{count:4, generate_audio:true}`（裁剪+强转） | 更名 `test_frontend_rejects_invalid_strict_parameters_instead_of_normalizing`，断言 `{}` + 三个字段全部报 `PARAM_INVALID` | 该断言编码的正是规划要求废除的行为；更名避免误导 |
| `test_frontend_builds_strict_video_request_from_declared_parameters_only` | `duration:30` → 期望 `10` | 输入改 `8`，期望 `8`，并加注释 | 保留「只有声明参数进请求」的意图；越界不再裁剪 |
| `test_frontend_builds_strict_audio_request_with_endpoint_field_names` | `pitch_rate:99` → 期望 `12` | 输入改 `12`，并加注释 | 同上 |
| `test_frontend_builds_traceable_capability_snapshot` | 未声明参数进 `effective_parameters` | 无需改断言，修正代码后即通过 | 暴露了我把未声明参数放行的实现 bug（已修） |
| `test_frontend_snapshot_keeps_omitted_parameters_separate_from_effective_values` | 同上 | 同上 | 同上 |

新增 `test_frontend_keeps_legal_strict_parameter_values_unchanged` 补上「合法值原样通过、`false` 与真实枚举值不被改写」的正向保护。

## 6. 测试证据

| 命令 | 结果 |
|---|---|
| `test_model_input_evaluation.py` | **45 项通过** |
| `tools/check_regression.py` | **900 项通过，1 skip，exit 0**（P2 后 854 → +46） |
| 其中前后端共享向量 | 17 例，Python 与 Node 判定**全部一致** |
| 失败数 | **0** |

### 用例对应

| 用例组 | 覆盖验收项 |
|---|---|
| `InputScenarioTests`（B01–B19） | 表 7.9 全部输入场景；`UNCONSUMED_INPUT` 不变量 |
| `StatusDimensionTests` | §7.5 七个状态维度分别返回；原因码统一表 |
| `ParameterTests`（C01–C20） | 默认值/必填/0 与 false/null 区分/离散枚举/整数范围/步长/冲突保留/草稿/条件适用/固定值/本地化枚举/恢复默认/NaN/字符计数 |
| `SharedVectorConsistencyTests` | §13.5 前后端同一份约束数据；§16 P3 第 5 项共享测试向量 |
| `EvaluationVectorTests` | 评估确定性与无副作用；冻结快照不含凭据 |

## 7. 安全与隔离

| 项 | 结果 |
|---|---|
| 测试是否写入真实用户数据 | 否（全部虚构 fixture 与只读快照） |
| 受保护配置哈希（6 项） | **全部未改动** |
| 是否发起付费生成 | 否 |
| 是否 push/merge/发布 | 否 |

## 8. 未完成的 P3 边界

| 项 | 状态 | 归属 |
|---|---|---|
| `INPUT_SPEC_EXCEEDED`（尺寸/时长/大小超限） | 原因码与 `_profile_declares_specs` 已就位；实际规格比对依赖可信素材元数据读取 | P5/P7（配合后端 `validate_input_metadata`） |
| `parameterIssues` 接入运行按钮阻断 | 未接 | P5 |
| `PARAM_DEPENDENCY_CONFLICT` 的跨字段联动求解 | 已支持 `applicable_if`/`visible_if` 单字段条件；跨字段互斥组的完整求解 | P4（参数联动 UI）+ P7 |
| 前端 `capabilitySnapshot` 的 omitted/effective 分离 | 保持原语义，未改动 | 无需改动 |
| `resolve_saved_selection` 的 `CATALOG_CHANGED` 触发 | 函数已实现；`catalog_revision` 变化时的差异判定 | P7 |

**P3 完成。下一步：P4 公共控件与紧凑样式。**
