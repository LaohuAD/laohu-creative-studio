# P2 稳定身份、操作与契约投影

- 生成时间：2026-09-22
- 依据：《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§8、§16 P2、§17 A11/E01/E06
- 复现命令：
  - `.venv/bin/python -m unittest discover -s tests -p "test_model_selection_v2.py"`
  - `.venv/bin/python tools/audit_model_coverage.py --include-config`

---

## 1. 新增与改动清单

| 文件 | 类型 | 职责 |
|---|---|---|
| `studio_model_selection.py` | 新增 | 身份解析、`ExecutionOption` 投影、稳定 `option_id`、标签生成、冲突报告、身份索引生成 |
| `data/model_capabilities/model-selection.schema.json` | 新增 | 身份索引 / 可执行选项 / 选择记录 / 参数 schema 增量字段的契约（受限条件表达式） |
| `data/model_capabilities/model-identities.json` | 新增（生成物） | 175 个 canonical 系列 + 605 条带证据的映射 |
| `tests/model_selection_fixtures/fixture_options.json` | 新增 | 纯假数据黄金样本（`test_only=true`） |
| `tests/test_model_selection_v2.py` | 新增 | 23 项 P2 行为回归 |
| `static/js/smart-model-capabilities.js` | **改动** | `variantSelectionKey` 改为机器字段优先；新增 `legacyVariantSelectionKey` 兼容回退 |

## 2. 解决的问题

### 2.1 跨平台聚合（P1 决定性问题）

**改造前**：`family_id` 全部是平台内局部命名空间，248 个 family 中跨平台数为 **0**；Seedance 被拆成 3 平台 / 8 个 family，第一栏显示成 8 个互不相干的“模型”。

**改造后**：以显式规则表把可证据化的产品系列归并到 `canonical_family_id`：

| canonical 系列 | 聚合平台 | 选项数 |
|---|---|---|
| `seedance` | `ai-money`、`jimeng-cli`、`runninghub` | 81 |
| `kling` | `ai-money`、`runninghub` | 156 |
| `vidu` | `ai-money`、`runninghub` | — |
| `minimax-h3` | `ai-money`、`runninghub` | — |
| `wan-video` | `ai-money`、`runninghub` | — |

共 **14 个系列实现跨平台聚合**；canonical 系列总数从 248 降到 **175**。

**证据规则**（避免 §3.4 禁止的“按名字删后缀”）：每条规则必须声明 `tokens`、适用 `node_types` 与 `source_ref`，并逐条写入 `model-identities.json` 的 `bindings[].evidence`。未命中规则的模型**保留 `provider-local:<adapter>:<family>` 身份**（739 个选项），不伪造跨平台等价（§8.1、§19.4）。

### 2.2 稳定 option_id（A11）

`option_id` = `connection_id + region_id + deployment_id + node_type + catalog_model_id + endpoint_id + operation + fixed_variant_id` 的**稳定 JSON 编码**再取 SHA-256 前 16 位（`opt_xxxxxxxxxxxxxxxx`）。

- 不用 `::` 拼接，避免碰撞（§8.3）。
- **显示名与语言不参与**：`test_option_id_ignores_display_labels_and_language` 证明改中文名、改英文名、切换语言均不改变 `option_id`。
- 原始模型 ID **大小写原样保留**（`test_raw_model_id_case_is_preserved`，用 `Seedance2.0 Fast Image to Video` 验证）。
- `profile_revision` **不进** `option_id`，单独放入选择快照（§8.3），档案更新不会让已保存选择失效。

### 2.3 前端 key 不再依赖显示名（§8.3、A11）

**改造前**（`smart-model-capabilities.js:285`）：

```js
return [variantId, variantName, variantNameEn].filter(Boolean).join('::') || modelId;
```

中英文显示名直接构成选择身份——**改文案或切换语言会改变选中项**。

**改造后**：机器字段优先 `provider_id::variant_id::operation::model_id`；仅当 `model_id` 缺失（退化数据）时才回退 `legacyVariantSelectionKey`。新增测试证明：

- 同一机器的中文名与英文名产生**相同** key；
- 不同 `model_id` 产生不同 key；
- 缺 `model_id` 的退化数据仍区分 Fast/Mini（既有断言 `tests/test_workbench_model_picker.py:51` 继续通过，未删除任何旧保护）。

> 回退分支是**显式兼容层**，不是新数据的身份来源；`legacyVariantSelectionKey` 已单独导出以便审计。

### 2.4 同 ID 跨站 / 跨操作不丢失（E01、E06、§8.3.1）

- **跨站**：345 个 `model_id` 同时存在于 AI/CN 两站，投影后保留为**两个不同 `option_id`**（region 进哈希），缓存与选择不串站。
- **跨操作**：`ai-money / doubao-seed-audio-1.0 / audio_generation` 的两个 operation（`speech_or_audio`、`text_to_audio`）保留为两个叶子；黄金样本中 `fixtureaudio-dual` 同样验证。
- 投影按 `option_id` 去重（1344 条），同时保留 `source_record_count`，**去重前的记录数不丢失**（1390 → 1344 的差额可追溯）。

## 3. 测试证据

| 命令 | 结果 |
|---|---|
| `.venv/bin/python -m unittest discover -s tests -p "test_model_selection_v2.py"` | **23 项通过** |
| `.venv/bin/python -m unittest discover -s tests -p "test_workbench_model_picker.py"` | 5 项通过（含旧 key 断言） |
| `.venv/bin/python -m unittest discover -s tests -p "test_studio_model_picker.py"` | 9 项通过 |
| `.venv/bin/python tools/check_regression.py` | **854 项通过，1 skip，exit 0**（P0 基线 831 → +23） |
| `node --check static/js/smart-model-capabilities.js` | 通过 |

### 用例与验收项对应

| 用例 | 覆盖验收项 |
|---|---|
| `test_seedance_aggregates_across_three_providers` | 同产品可跨平台聚合 |
| `test_same_id_in_two_regions_yields_two_options` | E01 同 ID 跨站不误合并 |
| `test_same_id_two_operations_yields_two_options` | E06 同 ID 多操作不丢失 |
| `test_option_id_ignores_display_labels_and_language` | A11 改名/换语言不改身份 |
| `test_variant_key_is_machine_only_with_legacy_fallback` | A11 前端 key |
| `test_unmapped_model_keeps_provider_local_identity` | §19.4 unknown 不等于禁用 |
| `test_unmapped_does_not_gain_capability` | 无未经证明的能力扩展 |
| `test_identity_rule_respects_node_type` | 防能力外扩 |
| `test_raw_model_id_case_is_preserved` | §8.3 大小写不规范化 |
| `test_document_never_contains_credentials` | §13.1 密钥不入目录 |
| `test_schema_file_is_valid_and_has_required_defs` | §8.5 受限条件表达式 |

## 4. 安全与隔离

| 项 | 结果 |
|---|---|
| 测试是否写入真实用户数据 | 否。全部使用 `tests/model_selection_fixtures/` 假数据或只读快照 |
| 受保护配置哈希（P0 基线 6 项） | **全部未改动** |
| 是否含凭据 | 身份索引、选项、schema 均无 `api_key`/`authorization`/`cookie`（有断言） |
| 是否发起付费生成 | 否 |
| 是否 push/merge/发布 | 否 |

## 5. 未完成的 P2 边界（留给后续阶段）

| 项 | 状态 | 归属 |
|---|---|---|
| `fixed_parameters` 与可调参数分离 | 字段已定义，未填充实际数据 | §16 P2 第 5 项 → 随 P3 参数协调一起落地 |
| `identity_mapping_status` 的 `unresolved` 分支 | 已定义，当前实现只产出 `mapped`/`provider_local` | P7 迁移时用于无法归类的旧选择 |
| `execution option` 的 `input_contract_ref` / `capability_tags` | 未填充 | P3（输入契约）与 P4（标签） |
| `model_capabilities.py` 内 `normalize_model_classifications` 的名称解析 | 未改动（§1.3 要求仅作兼容输入） | P3/P5 收敛 |
| 规则表覆盖的产品系列 | 14 条；其余保持 provider-local | 后续按证据逐条补充，不批量猜测 |

**P2 完成。下一步：P3 输入/参数决策核心。**
