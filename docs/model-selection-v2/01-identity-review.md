# P1 身份审阅与全平台覆盖结论

- 生成时间：2026-09-22
- 依据：《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§4、§16 P1
- 数据来源：`tools/audit_model_coverage.py --include-config` 输出
  - `01-provider-coverage.json`（1390 条发现记录 + 635 条启用投影）
  - `01-provider-coverage.csv`（同一数据的表格形式，已做 CSV 公式注入防护）
- 复现命令：`.venv/bin/python tools/audit_model_coverage.py --include-config`

---

## 1. 两条审计线必须分开报告（§4.5）

| 审计线 | 含义 | 记录数 |
|---|---|---|
| `discovery` 全量发现目录 | 只读仓库存量静态档案与区域快照，不经用户启用过滤 | 1390 |
| `enabled` 用户启用投影 | 走 `ModelCapabilityRegistry.build_catalog`，与应用运行时同一代码路径 | 635 |

**两类计数不可相互比较得出“遗漏”结论**（§4.5）。例如 ModelScope 发现目录 7 条全部 `needs_profile`，而启用投影 7 条全部 `ready`——这不是矛盾，而是动态档案补齐的结果（见 §4 E07）。

## 2. 全平台覆盖表

| 平台 | 发现源状态 | 发现条目 | 发现可执行 | 发现待补 | 发现适配缺口 | 启用条目 | 启用可执行 | 启用待补 | 启用适配缺口 |
|---|---|---|---|---|---|---|---|---|---|
| `ai-money`（laohu） | 存量快照：`ai-money-catalog.json` | 310 | 303 | 2 | 5 | 263 | 260 | 0 | 3 |
| `runninghub` | 存量快照：`runninghub-{global,cn}.json` + `runninghub-official-public.json` | 1066 | 1054 | 12 | 0 | 340 | 336 | 4 | 0 |
| `modelscope` | **not_observed** | 7 | 0 | 7 | 0 | 7 | **7** | 0 | 0 |
| `volcengine` | **not_observed** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `jimeng-cli` | **not_observed** | 3 | 3 | 0 | 0 | 15 | 15 | 0 | 0 |
| `codex-cli` | **not_observed** | 2 | 2 | 0 | 0 | 8 | 8 | 0 | 0 |
| `agnes` | **not_observed** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `gemini-cli` | **not_observed** | 2 | 2 | 0 | 0 | 2 | 2 | 0 | 0 |

全局：去重后接口 **1344** 条；能力档案 **1369**；可执行选项（发现线）**1364**、（启用线）**628**；模块候选 `not_implemented`（P6 未落地）。

**`not_observed` 的诚实含义**：这 5 个平台在本机**没有存量全量目录快照**，唯一可知的来源是静态档案 ∪ 用户配置。不得据此宣称“该平台只有这些模型”，也不得标绿（§16 P1 停止条件）。

## 3. 用户连接现状（只读，无凭据）

| 连接 | 能力平台 | 启用 | 站点 | chat | image | video | audio |
|---|---|---|---|---|---|---|---|
| `modelscope` | modelscope | ✅ | — | 3 | 4 | 0 | 0 |
| `runninghub` | runninghub | ✅ | `global` | 4 | 98 | 218 | 20 |
| `volcengine` | volcengine | ✅ | — | 0 | 0 | 0 | 0 |
| `ai-money` | ai-money | ✅ | — | 38 | 49 | 121 | 55 |
| `jimeng` | jimeng-cli | ✅ | — | 0 | 9 | 6 | 0 |
| `codex` | codex-cli | ✅ | — | 8 | 0 | 0 | 0 |
| `agnes` | agnes | ❌ **停用** | — | 1 | 2 | 1 | 0 |
| `openai-compatible` | `openai-compatible` | ❌ **停用** | — | 0 | 0 | 0 | 0 |
| `gemini-cli` | gemini-cli | ✅ | — | 1 | 1 | 0 | 0 |

**修正 P0 基线中的 C-03 定性**：`agnes` 与 `openai-compatible` 均为**已配置但停用**。隐藏它们不删除已有配置，但用户**无法再通过界面查看或重新启用**该配置。这与 §10.2.1「用户已删除或停用的条目不得因档案更新自动恢复」不冲突，但与 AGENTS.md「不删除已有配置」的可见性边界仍冲突，需在 P6 恢复为可查看的停用平台。

## 4. 规划预言的验证结果

| 编号 | 规划论断 | 本地实测 | 结论 |
|---|---|---|---|
| E07 | ModelScope 静态 pending 可被动态档案补齐，必须审计合成后的最终 profile | 发现线 7 条 `needs_profile` → 启用线 **7 条全部 `ready`** | ✅ **证实**，必须以合成后状态为准 |
| E08 | Agnes 静态 models 为空但动态模型存在，不得遗漏 | `providers/agnes.json` 确为空列表；动态档案代码存在，但**连接停用**故未进入启用投影 | ⚠️ 部分证实：动态能力存在，但因停用不可观测 |
| E09 | 火山没有用户接入点，不自动添加热门模型或伪造可调用列表 | `providers/volcengine.json` 空列表；用户配置该连接各列表均为 0 | ✅ **证实** |
| E06 | Antigravity `auto` 同时用于文本/图片，不能按 `model_id` 去重成一个叶子 | 发现同 ID+同站**多 operation** 实测 2 例，其一为 `gemini-cli / auto`：`chat` + `text_or_image_to_image` | ✅ **证实**，已作为 P2 黄金样本 |
| E01 | RunningHub 同 ID 同时在 AI/CN 出现，缓存不串站 | **337 个 `model_id` 同时存在于两站快照** | ✅ **证实**，区域维度不可省 |
| R03 | laohu 目录 262 项，其中 259 可运行、3 项适配器缺口 | 原始目录 262 条（38+49+120+55，与规划逐项计数一致）；唯一适配缺口 **3 个模型**：`hunyuan3d-v3.1-text-to-3d`、`hunyuan3d-v3.1-image-to-3d`、`kling-lip-sync-tts` | ✅ **完全吻合** |

## 5. 身份碎片化：P2 的核心问题（决定性问题）

**实测：发现目录 1377 条有 `family_id` 的记录中，唯一 `family_id` 共 248 个，其中跨 ≥2 个平台的 = `0`。**

现有 `family_id` **全部是平台命名空间内的局部标识**（`<provider>-<product>-<version>`），没有任何一个真正跨平台共享。因此：

- 前端 `familiesAcrossProviders`（`smart-model-capabilities.js:225`）的跨平台聚合**当前没有数据支撑**；
- 规划 §1.3 的怀疑成立：**不能假设各平台旧 `family_id` 已一致**。

### Seedance 实例（同一产品系列，3 平台 / 8 个 family_id）

| 平台 | family_id | 目录条目标识样例 |
|---|---|---|
| `ai-money` | `ai-money-seedance-2-0` | `seedance-2.0-standard-t2v`、`seedance-2.0-global-mini-multi` |
| `ai-money` | `ai-money-seedance-2-5` | `seedance-2.5-standard-i2v` |
| `runninghub` | `runninghub-seedance-1` | `seedance-v1-lite-reference-to-video` |
| `runninghub` | `runninghub-seedance-1.5` | `seedance-v1.5-pro-text-to-video-fast` |
| `runninghub` | `runninghub-seedance-2.0` | `seedance-2.0-mini/text-to-video`、`Seedance2.0 Text to Video`、`Stephen Chow IP Video Gen(Seedance 2.0)` |
| `runninghub` | `runninghub-seedance-2.5` | `seedance-2.5/text-to-video Token` |
| `jimeng-cli` | `jimeng-seedance-2.0` | `seedance2.0` |
| `jimeng-cli` | `jimeng-seedance-2.5` | `seedance2.5` |

**用户影响**：第一栏会显示成 8 个互不相干的“模型”，而不是 1 个 Seedance；版本（1.0/1.5/2.0/2.5）与档次（Fast/Mini/Standard/Pro）被压进 family_id 字符串里，无法在第三栏结构化呈现。

### 另一个 P2 问题：`catalog_model_id` 混装目录名与接口路径

RunningHub 快照中 `model_id` 同时存在三类形态：

- 接口路径型：`seedance-2.0-mini/text-to-video`
- 展示名型：`Seedance2.0 Text to Video`
- 第三方包装型：`Stephen Chow IP Video Gen(Seedance 2.0)`

这印证 §4.3「官方注册表可以出现目录名与 endpoint 不同的情况，不能把它们合成同一个字段」。P2 必须把 `catalog_model_id` / `endpoint_id` / `request_model_id` 拆开。

## 6. 待处理明细（P2/P3 输入）

### 适配器缺口（3 个唯一模型，均属 laohu）

| 模型 ID | 被登记的节点类型 | 缺口 |
|---|---|---|
| `hunyuan3d-v3.1-text-to-3d` | `text_generation` | 3D 输出无适配器（§4.2「未适配输出」） |
| `hunyuan3d-v3.1-image-to-3d` | `image_generation` | 同上 |
| `kling-lip-sync-tts` | `audio_generation` | Kling 唇形 TTS 已记录缺口 |

> 注：`hunyuan3d-v3.1-text-to-3d` 被登记为 `text_generation` 属于**分类可疑点**，其真实输出是 3D 资产而非文本，P2 需按 `output_contract` 重新判定。这是 §19.3「不能把统一命名做成损失专业差异」的实例。

### 待补能力

| 平台 | 模型 ID | 说明 |
|---|---|---|
| `ai-money` | `whisper-1`（audio_generation） | 有 ID 无档案 |
| `ai-money` | `video-models-from-official-docs`（video_generation） | **疑似占位符 ID，不是真实模型**，P2 需清理 |
| `runninghub` | `f-dev`、`f-dev-lora`（image_generation） | 有 ID 无档案 |
| `runninghub` | `kling-v3.0-4k-motion-control`（video_generation） | 有 ID 无档案 |
| `runninghub` | `ltx-2-19b/text-to-video-lora`（video_generation） | 有 ID 无档案 |
| `modelscope` | 7 项静态候选 | **在启用投影中已全部 ready**，无需补档 |

### 同 ID 多 operation（P2 必须保留为不同叶子）

| 平台 | 模型 ID | operations |
|---|---|---|
| `ai-money` | `doubao-seed-audio-1.0` | `speech_or_audio`、`text_to_audio` |
| `gemini-cli` | `auto` | `chat`、`text_or_image_to_image` |

§8.3.1 要求的测试「同一真实 ID＋相同输出类型＋两个不同操作均保留」即以此为基础；「同名跨站不覆盖」以 337 个双站 ID 为基础。

## 7. 未观测边界（不得标绿）

| 边界 | 状态 |
|---|---|
| ModelScope / 火山引擎 / 即梦 CLI / GPT CLI / Antigravity CLI | **无存量全量目录快照**，只有静态档案 ∪ 用户配置；上游真实全量目录未观测 |
| Agnes | 动态档案代码存在，但连接停用，未进入启用投影；上游目录未观测 |
| RunningHub AI/CN 区域快照 | 已逐条审计（1066 条发现记录），但**未确认账号实际授权范围**——快照存在 ≠ 账号可调用 |
| 用户自定义连接 | `openai-compatible` 已配置但停用且模型列表为空；无法判定其真实可用性 |
| 真实付费生成验证 | **本轮未做**（§0.2 明确禁止） |

## 8. P1 通过判定

| 规划通过条件 | 结果 |
|---|---|
| 每个源条目都有归属或明确未处理状态 | ✅ 1390 条发现记录逐条带 `readiness` 与 `unresolved_reasons`；5 个平台显式标 `not_observed` |
| 全目录与用户启用集合分别可追踪 | ✅ 两条审计线分开输出，计数独立 |
| 没有用少数平台代表全局完成 | ✅ 8 个注册平台逐一审计，含 0 记录平台 |
| 未回写真实用户配置 | ✅ `data/api_providers.json` 与 `static/runninghub/api_providers.json` 哈希与 P0 基线一致 |
| 未编造数量 | ✅ 所有数字可由 `01-provider-coverage.json` 复算 |

**P1 完成。下一步：P2 稳定身份、操作和契约投影。**
