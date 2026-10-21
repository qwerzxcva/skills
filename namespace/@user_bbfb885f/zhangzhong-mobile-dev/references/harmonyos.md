# 掌中 · 鸿蒙（HarmonyOS NEXT）开发要点

> v1.1.0 新增。覆盖「是否要上鸿蒙 → 技术怎么选 → Android 怎么迁 → 怎么上架」四个决策点。
> 适用对象：金融/政企/车联网等需要覆盖国内全终端的 App 团队。

## 一、定位：什么时候必须考虑鸿蒙

HarmonyOS NEXT（星河版，不再兼容 AOSP）自 2024Q4 商用后，国内新增设备占比持续上升。
2026 年国内市场华为新机出货占比已回到前二，**金融、政务、央国企客户招标普遍把鸿蒙适配列为硬性条款**。

判据（满足任一即应立项鸿蒙适配）：
1. 客户合同/招标书明确要求 HarmonyOS NEXT 版本；
2. App 在国内安卓渠道活跃用户中华为设备占比 ≥ 20%；
3. 政企/金融/医疗等行业客户（设备集采华为比例高）；
4. 竞品已上架鸿蒙版且被客户拿来做对比。

可以不急的情况：纯海外发行、内部工具且设备统一采购非华为、Web/小程序已覆盖该场景。

## 二、技术栈速览

| 项 | 内容 |
|---|---|
| 语言 | **ArkTS**（TypeScript 超集，声明式 UI）＋ 少量 C++（Native 能力） |
| UI 框架 | **ArkUI**（声明式，类似 SwiftUI/Compose 的心智模型） |
| 工程结构 | AppScope + entry（HAP）+ 共享 library（HAR/HSP） |
| IDE | DevEco Studio（基于 IntelliJ 平台） |
| 状态管理 | @State/@Prop/@Link/@Provide/@Consume + AppStorage/PersistentStorage |
| 网络/存储 | @ohos.net.http、@kit.ArkData（Preferences/RelationalStore） |
| 推送 | Push Kit（华为推送服务，APNs/厂商通道之外的独立通道） |
| 支付 | Payment Kit / IAP Kit；微信/支付宝鸿蒙版 SDK 已可用但能力裁剪 |
| 安全 | KeyStore（HUKS）、加密框架 Crypto Framework、可信执行环境 |

心智映射（降低学习成本）：
- ArkTS ≈ TS + 装饰器驱动的声明式 UI；Compose 的 `@Composable` ≈ ArkUI 的 `@Builder`/`@Component`；
- Android 的 ViewModel+StateFlow ≈ ArkUI 的 @Observed/@ObjectLink + AppStorage；
- AndroidManifest ≈ module.json5（abilities/权限/requestPermissions）。

## 三、选型决策表（在原「原生 vs 跨端」上加鸿蒙列）

| 维度 | iOS 原生 | Android 原生 | 鸿蒙原生 | Flutter | RN |
|---|---|---|---|---|---|
| 性能上限 | 高 | 高 | 高 | 较高 | 中 |
| 团队栈要求 | Swift | Kotlin | ArkTS(TS) | Dart | JS/TS |
| 鸿蒙 NEXT 支持 | — | ✗（不兼容 AOSP） | **原生** | 社区适配（ohos 分支，成熟度中） | 社区适配（成熟度低-中） |
| 三端复用 | ✗ | ✗ | ✗ | iOS/Android 强，鸿蒙弱 | iOS/Android 强，鸿蒙弱 |
| 金融级安全能力 | 强 | 强 | 强（HUKS/TEE） | 依赖原生桥 | 依赖原生桥 |

**结论口径（v1.1 起统一）**：
- 金融/政企/车联网且要求鸿蒙 → **鸿蒙原生 ArkTS**（安全与审核最稳）；
- 创业团队快速验证、无鸿蒙硬要求 → Flutter 双端先行，鸿蒙观察社区适配成熟度；
- 已有 RN/Flutter 存量 → 鸿蒙侧独立 ArkTS 重写核心页面，底层领域逻辑用 TS 复用部分代码。

## 四、Android → 鸿蒙迁移路径（≥5 条注意事项）

1. **代码不可直接迁移**：AOSP API 全部不可用（WebView、Google Play 服务、Support/AndroidX 库都没有），按「页面重写、领域逻辑翻译」预算工作量，常见比例是 Android 工作量的 60–80%（UI 重写为主）。
2. **Kotlin → ArkTS 翻译纪律**：数据类→interface/class，协程→async/await（ArkTS 基于 Promise），Flow→@Observed 状态或自研事件流；不要试图保留 Java 时代的设计（ findViewById 心智在声明式 UI 下是有害的）。
3. **三方 SDK 逐一盘点替代**：推送（个推/极光→Push Kit + 厂商自有）、统计（友盟→华为分析或自研）、支付、地图、扫码、分享——列「SDK 替代矩阵表」，每个标注：官方鸿蒙 SDK / 社区版 / 无替代需自研。
4. **权限模型差异**：鸿蒙权限分 normal/system_basic/available level，敏感权限（通讯录、精确位置、相册）走「权限申请弹窗 + 用途说明」，且部分权限仅系统应用可申；上架审核会逐项核对 privacy 声明。
5. **Web 容器方案**：鸿蒙 ArkWeb 与 Android WebView 行为差异（JS Bridge、Cookie 同步、文件下载），存量 H5 混合页要做回归清单。
6. **签名为两套**：调试证书/发布证书 + Profile（类似 iOS provisioning），CI 上要为鸿蒙单独建签名流水线，不能复用 Android keystore。
7. **灰度与回滚**：鸿蒙版上架初期用户基数小，建议独立渠道包+独立崩溃监控，不要与 Android 共用同一灰度开关。

## 五、鸿蒙上架要点（AppGallery Connect）

1. **账号与资质**：华为开发者账号实名认证（企业）；金融类 App 需行业资质文件（与安卓商店类似但单独提交）。
2. **签名**：发布证书 + 发布 Profile（AppGallery Connect 申请），.app 包上传。
3. **审核关注点**：
   - 隐私政策与权限用途一致性（逐项核对，鸿蒙审核对此最严）；
   - 不调用未公开 API、不携带 AOSP 残留库（打不进包，但混合工程常见配置错误）；
   - 支付类须接华为支付或持牌第三方支付鸿蒙 SDK；
   - 备案信息（ICP/App 备案）与安卓一致。
4. **上架节奏**：首次审核 3–7 个工作日（实测中位数），比国内安卓商店略快；版本更新 1–3 天。
5. **元数据**：图标/截图需鸿蒙设备实拍或模拟器截图（折叠屏/平板建议各一套），描述避免「安卓版」字样。

## 六、质量门控（本章节专属）

1. 鸿蒙选型结论必须写进选型决策表并给「为什么」，禁止「客户要所以做」一句话带过。
2. 迁移方案必须含「SDK 替代矩阵表」，缺表不放行。
3. 上架方案必须含隐私-权限一致性核对清单，禁止只写「提交审核」。
