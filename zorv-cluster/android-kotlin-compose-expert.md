# Kotlin / Jetpack Compose 专家规程

来源基准：awesome-android-agent-skills（compose-ui / android-architecture / android-viewmodel / android-data-layer 四份 SKILL.md 的方法论）。

## 一、Compose 状态与重组（最高频出错区）

1. **状态提升（UDF）**：Composable 尽量无状态。状态放调用方，`value: T` 进、`onValueChange: (T) -> Unit` 出。有状态壳 = 一个 `XxxScreen(state, onEvent)` + 外层 `rememberXxxState()`。
2. **只读派生用 `derivedStateOf`**：UI 只关心阈值/汇总时（如列表首项是否 >0、是否显示"回到顶部"），用 `derivedStateOf` 包住，避免每次滚动触发整体重组。
3. **Lambda 稳定性**：给子组件传 `viewModel::onEvent` 这类方法引用，或用 `remember` 包 lambda；不要每次重组新建 lambda 导致子组件被判 unstable 而重组。
4. **集合/对象稳定性**：`List<T>` 默认 unstable。用 `ImmutableList`(kotlinx.collections.immutable) 或 `@Immutable`/`@Stable` 标注数据类；`data class` 里含 `var` 字段会破坏稳定性。
5. **`rememberSaveable`** 只给需要跨进程重建存活的 UI 状态（输入框、滚动位置），不要滥用存业务数据。
6. **LazyColumn**：必须给 `key`；不要在 item 内部读会高频变化的全局 state；`contentPadding` 不要用外层 padding 模拟。
7. **副作用边界**：`LaunchedEffect(key)` 的 key 必须真实表达"什么变了才重跑"；一次性事件用 `Channel`/`SharedFlow` 收，不要在 Composable 里直接改 state 造成循环。

## 二、分层与模块化

标准多模块骨架（生产项目）：
- `:app` 入口，串 feature
- `:core:model` 纯 Kotlin 领域模型（**禁止依赖 Android SDK**）
- `:core:domain` UseCase + Repository 接口
- `:core:data` Repository 实现、Room、Retrofit、DataSource
- `:core:ui` 共享 Composable、Theme、资源
- `:feature:*` 单功能模块，只依赖 `:core:domain` 与 `:core:ui`

审查红线：
- domain 层出现 `android.*` import → 违规
- feature 之间互相依赖 → 违规
- `:core:ui` 反向依赖 feature → 违规

## 三、依赖注入（Hilt）

- 接口 → 实现用 `@Binds`（抽象类里），比 `@Provides` 更省生成代码；需要构造参数/第三方类型才用 `@Provides`。
- Scope：`@Singleton` 只给真正的全局单例（数据库、OkHttp、Repository）；ViewModel 用 `@HiltViewModel` 不手动 scope。
- 不要在 Composable 里 `EntryPointAccessors` 硬取依赖。

## 四、ViewModel / 协程

- UI 状态单一来源：`StateFlow<UiState>`，`collectAsStateWithLifecycle()` 收集（不是 `collectAsState`）。
- Repository 的 suspend 函数必须 **main-safe**：内部用 `withContext(Dispatchers.IO)`，不要要求调用方切线程。
- 结构化并发：`viewModelScope` 内并行用 `coroutineScope { async {} }`，禁止 `GlobalScope`。
- 冷流 `flow {}` 每个收集者独立执行；需要共享用 `stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), initial)`。
- 一次性事件（导航、Toast）用 `Channel(Channel.BUFFERED).receiveAsFlow()`。

## 五、数据层（离线优先）

- 单一可信源（SSOT）：Room 为真相，网络只负责刷新；UI 只 observe DAO 的 Flow。
- Retrofit + kotlinx.serialization；DTO 与 domain model 分离，mapper 显式。
- 冲突策略写清楚：服务端优先 / 本地优先 / 时间戳合并，不许"看情况"。
- 分页用 Paging 3，`RemoteMediator` 处理本地+远程混合。

## 六、交付前自检清单

- [ ] 每个 public Composable 有 `@Preview`（有状态壳的用无状态版 + 假数据）
- [ ] 没有在 Composable 内直接做 IO / 阻塞调用
- [ ] 没有 `Modifier` 顺序错误（`padding` 在 `background` 前会导致背景不含 padding，按意图确认）
- [ ] Lazy 列表全部带 `key`
- [ ] domain 层无 Android 依赖
- [ ] 硬编码颜色/字号已换成 `MaterialTheme.colorScheme` / `typography`
- [ ] 新增依赖走 version catalog（`libs.versions.toml`），不散落版本号

## 常见反模式

| 症状 | 根因 | 修法 |
|---|---|---|
| 输入框每输一个字整屏重组 | state 提升到顶层且无 `derivedStateOf` | 局部 state + 派生只读 |
| LazyColumn 滚动卡顿 | item 无 key / item 内读全局 state | 加 key，状态下沉 |
| 返回后台回来数据丢失 | 用 `remember` 存了需重建的状态 | 改 `rememberSaveable` 或放 ViewModel |
| ViewModel 越来越胖 | 业务逻辑没下沉 UseCase | 抽 UseCase，VM 只做状态编排 |