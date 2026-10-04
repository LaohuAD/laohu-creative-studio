# P0 基线盘点与保护

- 生成时间：2026-09-22
- 依据文档：《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》第 2 节、第 16 节 P0
- 本文件只记录文件与功能差异，不记录任何密钥内容。

---

## 1. 仓库与工作区状态

| 项目 | 值 |
|---|---|
| 当前分支 | `codex/warm-studio-settings` |
| 本地 HEAD | `0c64049` 发布 v2026.09.22：设置自动保存、RunningHub 双站点与画布选择器统一 |
| 文档远程基线 | `597524a698ddcc7010a08f65c2ae44eceef4c66f`，应用版本 `2026.09.19` |
| 本地领先文档基线 | 1 个提交（`0c64049`） |
| 工作区状态 | **干净**，`git status --short` 为 0 项；`git diff` 与 `git diff --cached` 均为空 |
| 远端 `origin/main` | 仍是 `597524a`（未被我改动，远端 VERSION = `2026.09.19`） |
| 远端 `origin/codex/warm-studio-settings` | `0c64049`（本轮任务开始前已存在，非本次操作） |
| 本地 `VERSION` | `2026.09.22` |

**结论：没有未提交改动需要保护，不需要 stash。** 用户此前的成果已由 `0c64049` 承载。

> 说明：`0c64049` 及其远端分支与 PR 是**本轮任务开始之前**的既有状态。本轮 P0–P9 默认不 push、不合并、不发布。

## 2. 与远程规划基线的差异（`597524a` → `0c64049`）

`0c64049` 含 61 个文件、+8992 / −3961 行。与本次 V2 规划直接相关的既有成果：

| 领域 | 本地已有成果 | 规划对应条目 |
|---|---|---|
| RunningHub 双站 | AI 站 / CN 站并列卡片、各自独立启用开关与凭据、站点停用置灰、模型与应用带 `· AI / · CN` 徽章 | §4.3、§10、E01–E03 |
| 画布候选按站点隔离 | `_runninghub_catalog_scopes()`、`region_profiles`、前端 `normalizeRegion/profileForRegion` | §8.3.1、E01 |
| 自动保存 | API/ComfyUI/Hypit 设置自动保存，取消手动保存入口，`expected_revision` 串行写入 | §12.2、F01–F03 |
| Hypit 模块设置 | `data/hypit_settings.json` 为唯一权威来源，`read_binding` 返回 `source=module_settings` | §10.2.1、§10.6、§15.4 |
| Hypit 原生主题 | `static/css/hypit-native-theme.css` + `hypit_runtime._ensure_native_theme()` 可重复注入并备份 | 与本轮无冲突 |
| 画布模型选择器 | `renderCapabilityModelPicker` 三段（模型→平台→运行模式）、搜索、能力徽章、真实模型 ID 预览 | §5、A01–A15 |
| 参数面板 | `capabilityParameterIsAdvanced` 分层、单列紧凑、短值不拆字 | §6、C14 |
| 暖色语义色板 | `--studio-*` 变量族，浅/深色两套 | §19.6 |
| 品牌更名 | 「老胡画梦枋」/ `laohu-creative-studio`，仓库地址同步 | 与本轮无冲突 |
| 新增测试 | `test_api_settings_autosave.py`、`test_comfyui_autosave.py`、`test_hypit_settings_ui.py`、`test_runninghub_sites_ui.py`、`test_runninghub_workflow_regions.py`、`test_studio_model_picker.py` | §17 部分覆盖 |
| 删除文件 | 仓库根目录 `赞赏.png`（无任何引用；素材副本仍在 `assets/input/temporary/image/赞赏.png`） | 无影响 |

**规划 §1.3 中“远程已核查发现”的若干项，在本地仍需改造**（详见第 5 节冲突项）。

## 3. 前后端实际运行版本

| 项目 | 值 |
|---|---|
| 后端服务 | PID `19389`，启动于 `2026-09-20 22:14:01`，端口 3000 |
| 启动解释器 | `/opt/homebrew/Cellar/python@3.14/3.14.5/.../Python`（**系统 Python，非项目 `.venv`**） |
| `/api/app-info` 返回 | `version = 2026.09.22`，`update_notes.version = 2026.09.22` |
| 后端源码新鲜度 | 启动后仅 `tests/test_workbench_model_picker.py` 有改动；**应用模块无过期**，运行后端即当前代码 |
| 自动重载 | 已启用（`INFINITE_CANVAS_AUTO_RELOAD` 默认 1；uvicorn `reload`，`reload_dirs=[项目根]`、`reload_includes=["*.py"]`） |
| 前端资源缓存标识 | 由 `VERSION` + 文件 mtime 动态生成，实测 `smart-canvas.js?v=2026.09.22.1789919949066435445` |

**结论：前后端版本一致，未出现“新前端连旧后端”。** 后续改动 Python 时服务会自动重载；如需重启必须走 `local_runtime.py` 受管入口并先检查活跃任务（§2.4）。

## 4. 受保护配置哈希（测试前基线）

存储：`cache/p0-protected-hashes-before.json`（`cache/` 已被 `.gitignore` 忽略）。

| 受保护对象 | 状态 | 摘要 |
|---|---|---|
| `data/api_providers.json` | present | `sha256:45d5b32b…4e0b4`（537,377 B） |
| `static/runninghub/api_providers.json` | present | `sha256:c44c0bef…dd488`（2,729 B） |
| `data/canvases/`（3 文件） | present | `dir_sha256:00807dd6…a63527` |
| `data/indexes/`（4 文件） | present | `dir_sha256:20f14f20…aa760b` |
| `data/hypit_bindings/`（1 文件） | present | `dir_sha256:ef9db306…ea9b6` |
| `API/`（2 文件） | present | `dir_sha256:883e2582…5e208f0`（只记哈希，不读取内容） |
| `data/hypit_settings.json` | **not present** | 用户尚未保存过 Hypit 模块设置 |
| `.env` | **not present** | — |

**P0 基线回归运行后复检：`git status --short` 为 0 项，受保护数据未被测试写入。**

## 5. 已有实现与函数映射表（§14.3）

全部 19 个入口均已定位，**没有任何一项缺失**：

| 函数 | 位置 | 本轮归属 |
|---|---|---|
| `renderCapabilityPickerOption` | `static/js/smart-canvas.js:3792` | 收敛为公共组件薄包装（P4/P5） |
| `renderCapabilityPickerStage` | `static/js/smart-canvas.js:3808` | 同上 |
| `renderCapabilityModelPicker` | `static/js/smart-canvas.js:3814` | 同上 |
| `resolveCapabilityFamilyPickerSelection` | `static/js/smart-canvas.js:3501` | 同上 |
| `capabilityPickerVariantGroups` | `static/js/smart-canvas.js:3452` | 同上 |
| `capabilityPickerPlatformEntries` | `static/js/smart-canvas.js:3474` | 同上 |
| `bindDynamicParams` | `static/js/smart-canvas.js:7660` | 改为挂载公共控件（P5） |
| `capabilityOptionLabel` | `static/js/smart-canvas.js:4194` | 保留本地化，补原因码（P3/P4） |
| `renderCapabilityModelName` | `static/js/smart-canvas.js:4295` | 顶部真实 ID 行（P4） |
| `renderExecutionConfigPanel` | `static/js/smart-canvas.js:4326` | 宿主 glue（P5） |
| `renderCapabilityParameterControl` | `static/js/smart-canvas.js:4452` | 公共参数渲染器（P4） |
| `renderCapabilitySettingsControl` | `static/js/smart-canvas.js:4656` | 高级齿轮（P4） |
| `capabilityParameterIsAdvanced` | `static/js/smart-canvas.js:4671` | 改为显式 `ui.level` + 旧字段兼容（P3） |
| `renderCapabilityParameterBundleForSource` | `static/js/smart-canvas.js:4674` | 参数协调（P3/P4） |
| `effectiveParameters` | `static/js/smart-canvas.js:25505` | 拆分“合法化建议”与“运行取值”（P3，C07/C09） |
| `mediaLimits` | `static/js/smart-model-capabilities.js:36` | 补组合约束（P3，B10） |
| `familiesAcrossProviders` | `static/js/smart-model-capabilities.js:225` | 改为身份索引驱动（P2） |
| `variantSelectionKey` | `static/js/smart-model-capabilities.js:285` | 改为稳定机器标识（P2，A11） |
| `resolveVideoExecutionMode` | `static/js/smart-model-capabilities.js:360` | 降级为推荐线索（P3，B17） |

### 关键后端与数据位置

| 位置 | 现状 |
|---|---|
| `model_capabilities.py` | `ModelCapabilityRegistry.load/build_catalog`、动态档案、预检、request_mapping |
| `data/model_capabilities/registry.json` | `schema_version: 1`，`updated_at: 2026-08-25`，**恰为 8 个 provider**：`ai-money`、`runninghub`、`modelscope`、`volcengine`、`jimeng-cli`、`codex-cli`、`agnes`、`gemini-cli` |
| `data/model_capabilities/providers/*.json` | 8 个档案齐备（agnes 406 B、ai-money 86,723 B、codex-cli 2,976 B、gemini-cli 2,121 B、jimeng-cli 8,585 B、modelscope 2,411 B、runninghub 3,135 B、volcengine 576 B） |
| `data/model_capabilities/snapshots/` | 4 个：`ai-money-catalog.json`、`runninghub-cn.json`（1.31 MB）、`runninghub-global.json`（1.44 MB）、`runninghub-official-public.json`（1.31 MB） |
| `studio_hypit_models.py` | `_SLOTS = ("text","image","video","audio","voice")`；`SUPPORTED_HYPIT_CAPABILITIES` / `UNSUPPORTED_HYPIT_CAPABILITIES`（music-generation 明确列为不支持）；模块设置落盘 `data/hypit_settings.json` |
| `static/hypit-models.mjs`、`static/hypit-endpoint.mjs` | 原生桥接能力与输入/返回转换 |

### 规划 §14.2 建议新增文件：**全部不存在**，需新建

`studio_model_selection.py`、`studio_module_models.py`、`static/js/model-config-core.js`、`static/js/model-config-control.js`、`static/css/model-config-control.css`、`data/model_capabilities/model-identities.json`、`data/model_capabilities/model-selection.schema.json`、`tests/test_model_selection_v2.py`、`tests/test_module_model_bindings.py`、`docs/model-selection-v2/`。

## 6. 现有测试入口

| 入口 | 说明 |
|---|---|
| `tools/check_regression.py` | 统一回归入口（Python 测试 + 前端语法检查），本机唯一验收命令 |
| `tests/*.py` | 43 个测试文件 |
| 浏览器用例 | `tools/check_creation_browser.cjs`、`check_canvas_relations.cjs`、`check_media_timeline.cjs`、`check_node_presentation.cjs`；需 Playwright + Chrome，默认目标 `CANVAS_TEST_URL`（默认 `http://127.0.0.1:3001`） |

### 解释器

| 解释器 | 状态 |
|---|---|
| `.venv/bin/python` | **Python 3.14.5，依赖齐备（`requests`/`fastapi` 可用）——本轮唯一可用解释器** |
| `python3`（`/opt/homebrew`） | Python 3.14.5，**缺 `requests`/`fastapi`**，直接跑回归会产生 25 个假失败 |

## 7. 当前测试失败清单

| 命令 | 结果 |
|---|---|
| `.venv/bin/python tools/check_regression.py` | **831 项通过，1 skip，exit 0**；用时 31.1 s |
| 失败/错误测试 | **无** |

日志中 `ERROR:root:画布任务状态持久化失败 [one]` 是测试**有意模拟磁盘写入失败**产生的业务日志，不是测试失败。

## 8. 已确认的冲突与待确认项（进入 P2/P3 前必须处理）

| 编号 | 冲突 | 证据 | 规划口径 |
|---|---|---|---|
| C-01 | **三段顺序口径不一致** | `AGENTS.md:9` 写「家族→具体变体/运行模式→支持的平台」，`docs/工作台改造与验收.md` 写「模型家族、模式与平台」；实现与 CSS 是**模型→平台→运行模式**（`smart-canvas.js:3899-3901`，`.capability-picker-stage-platform{grid-column:2}`、`-variant{grid-column:3}`） | §1.2 明确「保持 模型→平台→运行模式；此前本地"模型→模式→平台"的旧顺序不再作为目标」→ **以规划为准，需同步修订 AGENTS.md 与验收文档** |
| C-02 | 测试命名沿用旧顺序词 | `test_workbench_model_picker.py::test_generation_renderers_use_one_family_variant_platform_picker_and_one_bundle` | 同上，P2 内改名 |
| C-03 | 两个已配置平台被隐藏 | `static/js/api-settings.js:152` `HIDDEN_PROVIDER_IDS = new Set(['agnes','openai-compatible'])`，而用户 `data/api_providers.json` 实际配置了 `agnes` 与 `openai-compatible` | §4.1 要求覆盖 Agnes；§10.2.1「用户已删除或停用的条目不得因档案更新自动恢复」→ 隐藏已配置平台与该条冲突，需恢复可见入口 |
| C-04 | 中文兜底表未同步 | `static/js/api-settings.js:679` `'api.runningHubComfyuiNav':'RunningHub ComfyUI'`，而 i18n 已是「AI 应用」 | §6.8、§19.6 文案一致性 |
| C-05 | 新 PRD 状态落后 | `docs/画布节点模型与参数选择器重构PRD.md` 标「需求已确认，待实现验收」，主要项实际已落地 | P9 更新 |
| C-06 | 遗留扁平下拉仍在 | `renderExecutionPlatformControl()` 仍被 `renderVolcengineParams`、`renderVolcengineVideoParams`、`renderMsParams` 使用 | §9.4、§14.3 收敛 |
| C-07 | 死代码 | `renderCapabilityFamilyControl`、`renderCapabilityVariantControl` 无调用者；`static/js/api-settings.js:4709 saveKeyOnly()` 无调用者 | P9 清理 |

## 9. 环境缺口（不阻塞，但影响验收强度）

| 缺口 | 影响 | 处理 |
|---|---|---|
| 资料包附件缺失 | 附录 B 的 `README_交给本地AI.md`、`reference/原始PRD_V1.md`、`reference/laohu_原始目录快照_597524a.json`、`reference/laohu_262项分类工作表.{json,csv}`、`tools/inventory_model_sources.py`、`TOOL_CHECK_REPORT.md` 在本机未找到（已搜 `下载/`、`~/Downloads`、`~/Desktop` 及项目上级目录） | P1 直接以本地 `data/model_capabilities/snapshots/ai-money-catalog.json` 为权威来源审计；不依赖工作表分类建议 |
| Playwright 未安装 | `tools/check_*.cjs` 浏览器用例无法直接运行 | Chrome 153 已安装，P8 可用 DevTools Protocol 或最小化针对性用例；不擅自更换测试框架（§16.1） |
| 运行服务用系统 Python | 与 `.venv` 不是同一解释器 | 不改动用户运行服务；P8 验收如需隔离服务，使用独立端口 |

## 10. P0 通过判定

| 规划通过条件 | 结果 |
|---|---|
| 没有覆盖用户修改 | ✅ 工作区干净，未执行 `reset`/`clean`/`checkout`/`stash` |
| 能清楚区分旧有失败与新引入失败 | ✅ 基线 831 项通过、0 失败，后续任何失败均可判定为新引入 |
| 未提交改动识别 | ✅ 无未提交改动（既有成果已由 `0c64049` 承载） |
| 受保护配置哈希建立 | ✅ 7 项对象已记录 |
| 最小基线测试运行 | ✅ `tools/check_regression.py` 831 项通过 |
| 前后端运行版本核对 | ✅ 均为 `2026.09.22`，后端源码未过期 |

**P0 完成。下一步：P1 全平台源目录与能力覆盖审计。**
