# P4 公共控件与紧凑样式

- 生成时间：2026-09-22
- 依据：《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》§5、§9、§13.3、§13.4、§16 P4、§17 A 系列
- 复现命令：
  - `.venv/bin/python -m unittest discover -s tests -p "test_model_config_control.py"`
  - `.venv/bin/python tools/check_regression.py`

---

## 1. 交付物

| 文件 | 类型 | 职责（§9.2） |
|---|---|---|
| `static/js/model-config-core.js` | 新增 | **纯状态核心**：`committed / pathDraft / preview` 三态、候选投影、搜索与标签、摘要与真实标识行。无 DOM、无网络、无持久化 |
| `static/js/model-config-control.js` | 新增 | **公共 UI**：三栏选择器、顶部真实 ID、参数面板（常用/高级）、portal 浮层、键盘与视口处理、生命周期接口 |
| `static/css/model-config-control.css` | 新增 | 紧凑样式，全部 `.model-config-*` 命名空间 |
| `tests/browser/model-config-demo.html` | 新增 | 假数据浏览器验收页（`test_only`，不含真实目录、不发网络请求） |
| `tests/test_model_config_control.py` | 新增 | 22 项测试：13 项纯状态机 + 5 项产物/样式 + 9 项真实浏览器 |
| `docs/model-selection-v2/04-control-*.png` | 新增 | 桌面 / 高级参数 / 窄屏截图证据 |

**宿主接口**（§9.3）：

```javascript
const instance = mountModelConfigControl(container, {
  context, catalog, selection, presentation,
  onPreview, onCommit, onParametersChange, onValidationChange
});
instance.updateCatalog(next); instance.updateContext(next);
instance.updateSelection(next); instance.open(); instance.close(); instance.destroy();
```

## 2. 状态机与“单次提交”（§5.6）

三个对象严格分离，`act(state, event, payload)` 返回 `{state, effects}`，`effects.persist` 标明是否写持久化：

| 事件 | 持久化 | 弹层 | 测试 |
|---|---|---|---|
| 打开 | 否 | 打开 | — |
| 点击模型 | **否** | 保持 | `test_a02_*` |
| 点击平台 | **否** | 保持 | `test_a01_*` |
| hover / 键盘 focus 运行模式 | **否**（只触发 `onPreview`） | 保持 | `test_a04_*` |
| 点击合法叶子 | **是，一次完整选择** | 收起 | `test_a06_leaf_click_*` |
| 点击被禁用模式 | 否 | 保持并显示原因 | `test_a06_blocked_*` |
| Escape / 点击外部 | 否 | 收起并恢复已选 | `test_a07_*` |
| 目录更新 | 否 | 清理过期预览、保留已选身份 | `updateCatalog` |

**hover 零写入**已由真实浏览器验证：`window.__demo.commits.length === 0` 且 `previews > 0`。

## 3. 紧凑密度（§5.3）

| 目标 | 实现 | 验证 |
|---|---|---|
| 三栏比例 26% / 25% / 49% | `grid-template-columns: minmax(150px,26fr) minmax(150px,25fr) minmax(250px,49fr)` | 样式断言 |
| 总高 `min(560, vh-32)` | `place()` 动态设置 `max-height` | 浏览器浮层边界用例 |
| 普通列表行 32–38px | `min-height: 34px` | 样式断言 |
| 有徽章的第三栏 48–62px | `min-height: 48px` | 样式断言 |
| 标题 12–13px、正常字重、不独占宽侧栏 | 标题在列内，带序号圆点 | 截图 |
| 徽章 ≤4 个、11–12px | `slice(0, 4)` + `.model-config-badge` | 截图 |
| 各列独立滚动 | `overflow-y: auto` 于 `.model-config-stage-options` | 实现 |
| 窄屏逐层导航、不横向溢出 | `@media (max-width:720px)` 单列，实测 620px 视口为 580px 单轨道 | 截图 + 度量 |

## 4. 浮层、键盘与事件清理

- **portal**：浮层挂到 `#model-config-portal`（`position: fixed`），不放在随画布 transform 缩放的层内（§13.3）。
- **碰撞与翻转**：下方优先，空间不足翻到上方，左右与上下夹取到视口内；`resize` / `scroll` 重新定位。浏览器用例断言浮层四边均在视口内。
- **键盘**：`focus` 与 `mouseenter` 触发同一份只读预览；`Escape` 关闭并把焦点还给触发按钮（§13.4）。
- **滚动隔离**：弹层内 `wheel` / `scroll` 停止冒泡，不触发画布缩放或平移（§13.3）。
- **destroy**：移除全部监听、卸载根节点与浮层；重复 `destroy()` 幂等（浏览器用例验证 `leftBehind === 0`）。

## 5. 实现过程中发现并修复的缺陷

| 缺陷 | 现象 | 修复 |
|---|---|---|
| **预览重渲染破坏键盘焦点** | `focus` 触发预览 → 整表重渲染 → 被聚焦元素被销毁 → 浏览器派发 `blur` → 预览被立即清除，A05 失效 | 预览变化改为**原位切换 `is-previewing` 类**，不重建列表（同时改善 §13.2 hover 性能） |
| **首次打开时平台栏为空** | 无已选值时草稿路径为空 → 平台/运行模式两栏空白 | 浏览路径回落到第一个候选，三栏始终有内容（A08）；**不写任何持久化，不代表已选中** |
| **空状态误显示** | 未输入搜索词也显示「没有匹配的模型、模式或平台」 | 仅在 `search` 非空且无结果时显示（截图前后对比可见） |
| **参数摘要与选择摘要重复** | 第二行重复显示模型/平台/模式 | 按 §5.1 拆分为 `selectionParts`（第一行）与 `summaryParts`（第二行只放 `5秒 · 720p`） |
| 测试页未销毁旧实例 | 旧浮层残留在 portal，干扰断言 | 测试页新增 `destroyAll()`，并在每例 `setUp` 清理 |

## 6. 测试证据

| 命令 | 结果 |
|---|---|
| `test_model_config_control.py` | **23 项通过**（13 纯状态 + 5 产物 + 10 真实浏览器） |
| `tools/check_regression.py` | 累计见 P6 文档；本轮后为 **1022 项通过** |
| `node --check` 两个新 JS | 通过 |
| 受保护配置哈希（6 项） | 全部未改动 |

### 用例与验收项对应

| 用例 | 验收项 |
|---|---|
| `test_a01_stage_order_is_model_platform_variant` | A01 三栏顺序；第三栏只含该平台实际提供的模式 |
| `test_three_columns_render_in_order` | A01 真实 DOM 顺序 + 单实例 |
| `test_a02_family_click_only_updates_draft` | A02 点击模型只更新草稿、不保存完整选择 |
| `test_a04_hover_preview_never_persists` | A04 hover 零写入 + 移开恢复 |
| `test_hover_previews_without_any_commit` | A04 真实浏览器：`commits === 0`、顶部 ID 行高亮 |
| `test_keyboard_focus_gives_same_preview_as_hover` | A05 键盘 focus 同 hover |
| `test_a06_leaf_click_commits_exactly_once` / `test_leaf_click_commits_once_and_closes` | A06 单次提交、收起、无半组合 |
| `test_a06_blocked_leaf_is_rejected_without_persisting` | 被禁用模式给具体原因且不写库 |
| `test_a07_cancel_restores_committed_selection` / `test_escape_discards_without_commit` | A07 Escape 不保存并恢复 |
| `test_a08_single_platform_single_variant_still_shows_three_stages` | A08 单一平台单一模式仍三栏 |
| `test_a09_search_matches_real_id_and_alias` | A09 按真实 ID / 任务模式搜索，无结果空状态 |
| `test_a10_unavailable_selected_option_stays_visible` | A10 已选失效条目保留可见 |
| `test_a13_large_catalog_projection_is_fast` | A13 1000 条目录下 20 次投影 < 2s |
| `test_common_parameters_inline_and_advanced_only_behind_gear` | C14 常用直接铺开、高级只在齿轮内 |
| `test_popover_stays_inside_viewport` | A14 浮层不溢出视口 |
| `test_destroy_removes_listeners_and_persists_nothing` | F15 关闭控件无重复监听 |
| `test_namespaced_styles_avoid_global_selectors` | §19.6 不依赖宿主宽泛选择器 |
| `test_density_targets_match_plan` | §5.3 密度目标 |

### 截图证据

| 文件 | 内容 |
|---|---|
| `04-control-popover.png` | 桌面：顶部真实 ID 行 + 搜索 + 能力标签 + 三栏 + 常用参数铺开 |
| `04-control-advanced.png` | 点开齿轮后的高级参数 |
| `04-control-narrow.png` | 620px 窄屏：单列逐层，不横向溢出 |

## 7. 安全与隔离

| 项 | 结果 |
|---|---|
| 控件是否读密钥或发网络请求 | **否**。`onCommit` 由宿主注入；控件本身不发起任何请求（§9.2） |
| hover / render / 默认值展示是否触发 `onCommit` | 否（测试断言 commits 为 0） |
| 测试是否写入真实用户数据 | 否（假目录 + 演示页） |
| 是否 push/merge/发布 | 否 |

## 9. 内联表现（补做，本轮）

§16 P4 第 4 项要求 inline / popover 两种宿主表现共用同一套控件。实现方式：`presentation: 'inline'` 时
弹层内容就地渲染到宿主体内（`.model-config-popover.is-inline`），**不挂 portal、不隐藏、不做视口定位**，
状态机与提交语义完全复用同一份代码，没有第二套渲染逻辑。

| 行为差异 | popover | inline |
|---|---|---|
| 承载位置 | `#model-config-portal`（`position: fixed`） | 宿主体内（`position: static`） |
| 触发方式 | 点击触发按钮 | 直接展开，触发条隐藏 |
| 提交后 | 收起弹层 | 保持可见（宿主常驻展示） |
| 外部点击关闭 | 是 | 否（内联不适用） |
| 视口碰撞定位 | 是 | 否 |

浏览器用例 `test_inline_presentation_renders_in_place_without_portal` 断言：就地渲染、portal 内 0 个弹层、
三栏顺序正确、常用参数铺开、提交恰好一次且提交后**不隐藏**。

## 8. 未完成的 P4 边界

| 项 | 状态 | 归属 |
|---|---|---|
| `presentation: "inline"`（模块设置内联表现） | ✅ 已实现（见第 9 节） | — |
| 浮层的完整键盘导航（方向键在栏间移动、Enter 选择） | 当前支持 Tab 顺序 + focus 预览 + Escape；方向键栅格导航未实现 | P5（画布接入时补齐） |
| 深色主题对比度实测 | 使用语义变量，未单独跑深色截图 | P8 验收 |
| 参数控件的滑块 / 步进器形态 | 目前为分段网格与枚举网格 | P5（按 §6.2 决策表补 number/step 控件） |
| 与其他弹层的层级关系（画布工具条、节点参数层） | 用 `z-index: 9400`，未与现有层级栈联测 | P5 |

**P4 完成。下一步：P5 画布五类节点接入。**
