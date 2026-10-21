# Android 测试驱动开发（JUnit 版）

TDD 就是红 → 绿循环。本模块是让这个循环产出**值得保留的测试**的参考：什么是好测试、测试放哪、反模式、循环纪律。每一节在每个循环周期都适用——在循环前和循环中查阅，不是事后补救。

项目存在 `.qoder/context/`、CONTEXT.md 或 docs/ 业务文档时先读，测试命名与接口词汇要与项目领域语言一致。

## 什么是好测试

测试通过**公开接口**验证行为，不验证实现细节。实现可以整个重写，测试不应改。好测试读起来像规格说明书："运单号为空时拒绝提交"一眼说明能力存在，且不 care 内部结构，扛得住重构。

## 接缝：测试放哪（Android 版）

**接缝（seam）** 是测试的公开边界：不伸手进去就能观察到行为的接口。测试只活在接缝上，绝不贴着内部实现写。

| 可测（优先） | 谨慎 | 不测 |
|-------------|------|------|
| 纯函数/工具类（校验/格式化/计算） | Repository/DataSource（需 mock 网络与 Room） | Activity/Fragment/Compose UI 本身 |
| Model 转换（DTO→领域模型/枚举映射/状态机） | UseCase/Interactor、ViewModel（用 turbine 收 Flow 断言） | 依赖硬件/系统服务的胶水（相机/蓝牙拉起） |
| 参数组装逻辑 | 本地数据源（Room 用 in-memory DB / Robolectric 影子环境） | Application/清单配置等入口代码 |

需要 Android 框架类（Context/Resources/SharedPreferences）的纯逻辑，优先 **Robolectric 本地单测**（`@RunWith(RobolectricTestRunner::class)`）而不是上 emulator——秒级反馈；只有必须真机/模拟器验证的交互才进 `androidTest`（Espresso）。

**只在预先约定的接缝写测试**。动手前写下本次要测的接缝并与用户确认。没确认的接缝不写测试——测试资源有限，事先约定是让测试投入落在关键路径和复杂逻辑上，而不是每个边角。

问用户："公开接口是哪个？我们在哪几个接缝上测？"

## 反模式

- **耦合实现**：mock 内部协作者、测私有方法、绕开接口走旁路。信号：重构代码但行为没变，测试却红了。
- **自证预言（tautological）**：断言用与实现相同的方式算期望值，构造上必过，永远不可能与代码分歧。期望值必须来自独立真源：已知正确字面量、手工演算样例、spec。
- **水平切片**：先写完全部测试再写全部实现。批量测试验证的是**想象中的**行为，测的是形状而不是行为。改用**垂直切片**：一个测试 → 一个实现 → 重复，每个测试都是响应上一循环教训的曳光弹。

## 循环纪律

- **先红后绿**：先写失败测试，跑 `./gradlew :module:testDebugUnitTest --tests "com.example.YourTest"` 确认红，再写刚好够过的实现。不预写未来测试，不加投机功能。
- **一次一片**：每循环一个接缝、一个测试、一个最小实现。
- **重构不属于循环**：重构属于评审阶段（见 references/04-code-review.md），不属于红绿实现循环。

## Android 测试实操约定

- 测试文件镜像源码目录；类名 `{被测类}Test`；test 方法名写场景："空列表返回空视图状态"。
- 每个测试只断言一件事；失败信息要能说清"期望什么、实际什么"。
- mock 优先 **mockk**（Kotlin 友好）；Flow 断言用 **turbine**；协程测试用 `runTest` + `StandardTestDispatcher` 控制时间，**禁止真实 `delay` 等待**。
- 只 mock 接缝处的依赖，不 mock 值对象与数据类。
- 测试间无共享可变状态；`@Before`/`@After` 重置；不测 Android Framework 本身。
- 截图对比（Paparazzi/Robolectric screenshot）归 CI 与视觉回归，不进红绿循环。
