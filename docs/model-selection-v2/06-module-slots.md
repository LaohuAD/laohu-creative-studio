# P6 模块模型设置与 Hypit 槽位复用（进行中）

- 生成时间：2026-09-22
- 依据：《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§10.2、§10.4、§10.5、§10.8、§16 P6、§17 D 系列
- 复现命令：`.venv/bin/python -m unittest discover -s tests -p "test_module_slot_contracts.py"`

> **状态：P6 未完成。** 本轮完成"模块与槽位契约层"；**Hypit 设置页尚未换成公共控件**，模块绑定的 REST 接口与项目 binding 差异报告未做。

---

## 1. 本轮交付

| 文件 | 类型 | 职责 |
|---|---|---|
| `studio_module_models.py` | 新增 | 模块注册、槽位模板契约（§10.5）、选择基数声明、绑定校验 |
| `tests/test_module_slot_contracts.py` | 新增 | 19 项行为回归 |

## 2. 复用而非复制（§14.1）

`hypit_slot_descriptors()` **直接从 `studio_hypit_models.SUPPORTED_HYPIT_CAPABILITIES` 生成**，不另写一份能力清单。测试断言槽位集合与桥接声明逐项一致：

```python
self.assertEqual({slot["id"] for slot in descriptors}, from_bridge)
```

这样 Hypit 桥接扩展槽位时，模块契约自动跟随，不会出现"两处各写一份、慢慢漂移"。

## 3. 已完成的验证

### 3.1 D04：audio 与 voice 是不同槽位

两者输出都是 audio，但**按能力标识区分**，不取第一个 audio 默认：

| 槽位 | `capability_name` | 必需场景 |
|---|---|---|
| `audio` | `audio-generation` | `text_prompt` |
| `voice` | `speech-generation` | `text_prompt` + `voice_reference` |

### 3.2 D05：模块不支持的能力必须明确拒绝

`unsupported_capability_reason("hypit", name)` 直接读模块声明（music-generation、AI 应用等），每条都带中英文拒绝原因。测试断言：支持的能力不得被误报为不支持。

### 3.3 D14 / §10.2：候选池多选、固定槽位单选

| 模块 | `selection_policy` |
|---|---|
| `canvas` | `multiple`（候选池多选） |
| `hypit` | `fixed`（固定单选槽位） |
| 画布内的真实节点槽位 | `fixed`（与候选池不是同一对象） |

### 3.4 D06 / §10.5：绑定必须落到槽位真实允许的输出

`validate_slot_binding()` 检查节点类型、输出媒体、操作 allowlist、档案状态与适配器状态：

- 固定图片槽绑定输出视频的工具 → `HOST_OUTPUT_UNSUPPORTED`
- 语音槽绑定音乐节点 → `HOST_OUTPUT_UNSUPPORTED`
- 适配器缺口 / 档案未确认 → `ADAPTER_MISSING` / `PROFILE_UNCONFIRMED`
- 未声明 allowlist 时**不额外限制**，避免凭空收窄能力

### 3.5 一处实现决定：声明每次重建

`module_descriptors()` 每次调用重建，因此调用方拿到并修改的槽位字典**不会污染后续校验**。这起初是我测试写法的一个障碍，但它其实是正确性质，已补断言固化：

```python
first["allowed_operations"] = ["tampered"]
self.assertEqual(smm.slot_descriptor("hypit", "image")["allowed_operations"], [])
```

配套把校验拆成可传入显式槽位声明的 `validate_option_against_slot(slot, option)` 纯函数，便于单独验证 allowlist 分支。

## 4. 请求幂等与固定槽位（本轮验证）

### 4.1 D09/D10：幂等只按调用方输入判定

`_request_fingerprint()` 只吃调用方 payload 并剔除 `request_id`，**不引用模块设置**。测试断言其函数体内不含 `settings_record` / `read_binding` / `defaults` 任何来源，且字典顺序不影响结果。

`submit_request` 的调用顺序经断言固化：

```
1. input_fingerprint = _request_fingerprint(payload)   ← 先算指纹
2. 查已有任务并返回（指纹不符则 409）                    ← 不重新解释旧请求
3. binding = read_binding(project_id)                  ← 才读当前模块绑定
4. _project_constraints(...) 投影
5. 写入前再查一次                                       ← 防并发重复创建
```

这满足 §11.6「先用 module/project/request_id 查已接收任务；只有新 request_id 才解析当前模块默认」。

### 4.2 §10.4：语音不得被归成音乐

`speech` kind 归一化为 `audio`（不是 `music`）；`voice` 与 `audio` 是 `_SLOTS` 里两个独立槽位，虽然 `_SLOT_NODE_TYPES` 都是 `audio_generation`，但**槽位才是权威**，不得按 kind 取第一个默认。

### 4.3 D11 收敛：覆盖从隐藏路径变为可观测来源（本轮完成）

**先查依赖，再动手。** `static/hypit-endpoint.mjs:277` 明确转发这些字段：

```js
for (const key of ["provider_id", "provider", "model", "model_id", "slot"]) {
    if (constraints[key] !== undefined) projected[key] = constraints[key];
}
```

**原生 Endpoint 主动依赖这条覆盖路径**，因此按 §10.7「明确收敛并保留受限兼容」，不能直接禁止。

现状核对：覆盖**已经**受能力约束——`_resolve_profile` 强制 `node_type == _SLOT_NODE_TYPES[slot]`，随后校验 `validation_mode == strict`、`readiness == ready`、`runnable != false`，参数走 `_validate_parameters`。真正的缺口是它**不可观测**（一次绕过模块设置的调用与正常调用在记录上无法区分）。

收敛做法：

| 变化 | 效果 |
|---|---|
| 新增 `model_source` 字段 | 无覆盖或与绑定一致 → `module_settings`；显式改动 → `runtime_override` |
| 新增 `module_slot` 字段 | 记录该请求实际落的槽位 |
| 保留原校验链 | 覆盖仍须是槽位允许、档案就绪的模型，非法覆盖 400 且零执行 |

端到端验证：

| 用例 | 结果 |
|---|---|
| 不传 provider/model | `model_source = module_settings`，`module_slot = image` |
| 显式传 `model: image-2`（绑定是 image-1） | 200，`model_source = runtime_override`，模型确为 image-2 |
| 显式传不存在的模型 | 400「不在当前用户启用白名单中」，执行器零调用 |

**遗留边界**：目前只做到「可观测 + 仍受能力约束」。按槽位 `runtime_model_override: deny` 做**硬拒绝**需要先与原生 Endpoint 的使用方式对齐（它可能用于合法的按调用选模型），在确认前不擅自关闭，避免打断你正在用的原生调用。

## 5. D07/D08 端到端验证（本轮补齐）

用假执行器（自带 fixture 目录、无网络、无付费）跑完整 HTTP 链路：

| 用例 | 观测结果 |
|---|---|
| **D07** 保存 image 槽 = `image-1` → 提交 `req-1` | 执行器收到 `model: image-1` |
| **D07** 改槽位 = `image-2` → 提交新 `req-2` | 执行器收到 `model: image-2`（新请求用最新绑定） |
| **D08/D09** 改设置后用**同一** `req-1` 重试 | 返回**同一个 task_id**；`generate` 调用次数仍为 **1**；任务记录里 `request.model` 仍是 `image-1`（提交时冻结） |
| **D10** 同一 `req-1` 换显式输入 | **409**，且执行次数不变 |
| 槽位未配置时提交 | **400「请先为…配置工作台模型」**，执行器零调用 |

这把上一轮只是"机制层"的结论升级为**端到端可复现**。

## 6. 项目 binding 差异报告（D14/E14）

产出 `docs/model-selection-v2/06-binding-diff-report.json`（只读比对，不修改任何项目配置）：

| 项 | 结果 |
|---|---|
| `data/hypit_settings.json`（模块设置） | **不存在**（用户尚未保存过 Hypit 模块设置） |
| 旧项目 binding | 1 个，5 个槽位 |
| 实际覆盖 | **0 个**——5 个槽位的 `provider`/`model` 全为空、`region` 为 null |

**结论**：没有真实的非默认项目覆盖，因此不存在「未确认前不得抹掉」的用户决策；§15.4 第 3 项要求的差异报告已产出且为空。迁移只需把空的旧记录保留为历史证据，新请求统一走模块设置。

## 7. Hypit 槽位候选复用共享投影（本轮）

### 7.1 做了什么

`enabledModels(slot)` 原本自己重写 `runnable === true && validation_mode === 'strict'` 与节点类型筛选，正是 §20.1 警告的「看起来统一、实际两套规则」。改为新增 `slotOptions(slot)` 优先消费目录的扁平选项投影（§9.4），只在投影缺失时才回退旧推导。

设置页另补取 `/api/model-capabilities` 的 `options`——**这一步是必需的**：原先 `state.catalog` 来自 `/api/studio/hypit/models/capabilities`，那个响应只有家族树、没有扁平选项。**第一版改动漏了这一步，实际是空转的**（`slotOptions()` 恒返回 `null`，一路走回退分支）。

### 7.2 加了守卫，防止再次空转

投影缺失时不再安静回退，而是写入 `state.projectionAvailable = false` 并在控制台 `console.warn` 一次。这正是上一轮差点让我误报完成的那个坑。

### 7.3 跨边界契约测试

| 用例 | 断言 |
|---|---|
| `/api/model-capabilities` 携带投影 | `options` 非空、`catalog_revision` 以 `rev_` 开头 |
| 投影字段 = 前端消费字段 | 逐个断言 `option_id`/`node_type`/`runnable`/`connection_id`/`catalog_model_id`/`region_id`/`parameters`/`inputs` |
| 设置页装载 | `api-settings.html` 加载 `hypit-settings.js` 且存在 `#hypitSlots` |
| 投影缺失不静默 | 函数体内必须出现 `projectionAvailable = false` 与 `console.warn` |

> 顺带纠正一处事实：`static/hypit.html` 是**原生 Studio 宿主页**（加载 `hypit-project.js`），不是设置页；Hypit 槽位设置位于 `static/api-settings.html` 的「模块模型」区。

### 7.4 浏览器验证（本轮完成）

新增 `tests/browser/hypit-slot-candidates.html` 桩页面 + `tests/test_hypit_slot_candidates_browser.py`：

- **零服务器、零用户数据**：`fetch` 全部被拦截并返回本地假数据，页面用 `file://` 打开。
- **判别方式**：投影里放一个家族树中不存在的模型 `fixture-projected-only-model`，家族树里放一个投影中不存在的 `fixture-family-tree-model`。谁出现就说明谁在生效。

| 用例 | 结果 |
|---|---|
| 槽位渲染投影系列标签 | ✅ 界面出现投影的 `canonical_family_label`（「桩系列」「桩文本系列」）；家族树模型**未**出现 |
| 设置页请求投影来源 | ✅ `window.__fixture.requests` 含 `/api/model-capabilities` |
| 渲染出模型下拉 | ✅ `select` 与 `option` 均非空 |
| **交互后取到投影模型** | ✅ 选定投影系列后，二级下拉出现 `fixture-projected-only-model`，且家族树模型不在候选中 |

> 这解决了前两轮「改完没浏览器验证」的缺口。之所以能安全做到，是因为桩页面完全绕开了服务与数据目录——不再需要为验证而启动第二个进程。

## 7.5 槽位 UI 换公共控件：本轮尝试后回退（未落地）

尝试内容：把 `renderSlot` 里的三个 `<select>` 换成内联 `mountModelConfigControl`，提交时写 `state.settings.defaults[slot]` 并 `markDirty()`。

**回退原因（必须记录，避免下轮重走）**：

| 阻塞点 | 细节 |
|---|---|
| 假 DOM 用例依赖旧标记 | `tests/test_hypit_settings_ui.py::test_autosave_race_keeps_latest_draft_and_server_revision` 用桩 DOM 断言 `hypitSlots.innerHTML` 含 `RunningHub · AI/CN`，这正是旧 `<select>` 的产物 |
| 补"候选兜底摘要"反而扩大失败 | 为保住上面那条断言的保护意图，我在卡片里保留了一份候选摘要；结果 4 项浏览器用例同时失败，失败数从 1 涨到 5 |
| 预算耗尽 | 继续修补存在把仓库留在破损状态的风险 |

**处理**：整轮回退，回到改动前的绿色状态（1021 项通过、0 失败）。本轮**没有净功能增量**。

**下一轮正确顺序**：先改桩 DOM 用例的断言（改成断言"候选数据含两个 RunningHub 站点"而不是渲染 HTML），再换 UI，最后同步 4 项浏览器断言；不要用"兜底摘要"绕过，那会让两套 UI 同时存在。

### 7.6 阻塞项已解除（本轮完成）

按 7.5 的记录，先做第 1 步：把桩 DOM 用例从「断言渲染 HTML」改成「断言候选数据」。

| 变化 | 内容 |
|---|---|
| 新增只读诊断导出 | `window.hypitSlotCandidates(slot)` 返回候选（含 `option_id`/`provider_id`/`model_id`/`region`/`label`/`parameters`/`inputs`）；`window.hypitSlotSelection(slot)` 返回当前选择；`window.hypitProjectionAvailable()` 返回投影是否可用 |
| 用例断言改写 | 不再检查 `hypitSlots.innerHTML` 是否含 `RunningHub · AI/CN`，改为检查候选**数据**里同时存在两个站点（且 `region === 'cn'` 的候选存在），失败时输出完整候选标签便于定位 |

**意义**：槽位 UI 换成公共控件时，这条用例不会再因为标记变化而误报——屏障从"必须同时改 UI 与断言"变成"只改 UI"。同时 `hypitProjectionAvailable()` 让 7.2 节的投影可用性可以从用例里直接读到，而不是只能靠控制台日志。

**状态**：1021 项通过、0 失败。**槽位 UI 本身仍未替换**，但下一轮可以直接动手，无需再处理这把锁。

**已就绪的前提**（本轮之前完成、未回退）：inline 表现（P4 第 9 节）、候选来源统一到共享投影、桩页面验证设施。

### 7.7 槽位 UI 已换成内联公共控件（本轮完成）

按 7.6 解除阻塞后的顺序执行：

| 变化 | 内容 |
|---|---|
| `renderSlot` | 三个 `<select>` 换成 `<div class="hypit-model-config" data-model-config-slot="…">` 挂载点 |
| `mountSlotControls()` | 每个槽位挂载一个 `presentation: 'inline'` 的公共控件；候选来自 `enabledModels(slot)`（即共享投影） |
| `onCommit` | 只写该槽位的 `state.settings.defaults[slot]`（provider/model/region/parameters）并 `markDirty()`；**不整页重渲染**，避免销毁正在进行交互的控件 |
| 无候选槽位 | 不挂载、不伪造选项，仍显示「未接入」 |

**没有**再使用「候选兜底摘要」——上一轮就是它让新旧两套 UI 并存、4 项用例同时失败。

浏览器验证（桩页面，零服务器零数据）：

| 用例 | 结果 |
|---|---|
| 挂载内联公共控件 | ✅ `.model-config` 与 `.model-config-popover.is-inline` 均存在 |
| 三栏顺序 | ✅ `family|platform|variant` |
| 候选来自共享投影 | ✅ 第一栏显示投影系列「桩系列」；家族树模型**未**出现 |
| 交互取到投影模型 | ✅ 点击系列后第三栏出现 `fixture-projected-only-model` |
| 无候选槽位标注 | ✅ 恰好 3 个槽位显示「未接入」（桩数据只提供 text/image） |
| 请求投影来源 | ✅ 请求列表含 `/api/model-capabilities` |

## 8. 明确未完成的 P6 项

| 规划要求 | 状态 | 说明 |
|---|---|---|
| Hypit 设置页换成公共三栏控件（§16 P6 第 3 项） | ✅ **已完成** | 见第 7.7 节，浏览器验证通过 |
| Hypit 设置页浏览器验证 | ✅ 已完成 | 见第 7.4、7.7 节 |
| 模块绑定仓储与 REST 接口（§11.2） | ❌ 未做 | `GET /api/studio/model-options`、`PATCH .../slots/{slot_id}` 等未新增；现有 `/api/studio/hypit/models` 路由保持不变 |
| 新请求使用最新模块绑定（D07） | ⚠️ 未复验 | `studio_hypit_models` 已有模块设置与 `_request_fingerprint`，本轮未补测 |
| 执行中任务保持冻结（D08） | ⚠️ 未复验 | 同上 |
| 默认变化后同 request_id 幂等（D09/D10） | ⚠️ 未复验 | 已有实现，本轮未补测 |
| 项目 binding 差异报告（D14/E14） | ❌ 未做 | 需读 `data/hypit_bindings/` 并与模块设置比对 |
| 画布候选池多选的实际保存 | ❌ 未做 | 仅声明了 `selection_policy`，未接保存 |

## 5. 测试证据

| 命令 | 结果 |
|---|---|
| `test_module_slot_contracts.py` | **26 项通过**（含 4 项跨边界契约） |
| `test_hypit_slot_candidates_browser.py` | **4 项通过**（真实浏览器，桩数据；已随 UI 替换更新断言） |
| `test_hypit_request_idempotency.py` | **20 项通过**（含 4 项端到端） |
| `tools/check_regression.py` | **1006 项通过，1 skip，exit 0**（P5 后 967 → +39），**失败 0** |
| 受保护配置哈希（6 项） | ⚠️ 5 项未改动；`data/indexes` 为上轮既有偏差，本轮**无新写入**（`results.json` mtime 仍为 17:23:44） |
| push / merge / 发布 | 均未进行 |

**P6 未完成，继续。**
