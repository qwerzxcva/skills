---
slug: zhangzhong-mobile-dev
displayName: 掌中 · 移动端原生与跨端开发
name: zhangzhong-mobile-dev
description: >-
  掌中 · 移动端原生与跨端开发——移动端原生与跨端开发 skill。用「选型决策 → 架构设计 → 功能开发 → 测试 → 发布」全流程
  指导移动 App 开发：iOS(Swift/SwiftUI)、Android(Kotlin/Compose)、跨端(Flutter/React Native) 选型与
  架构模式、原生能力接入、性能与适配、签名与上架，输出移动端技术方案 + 开发规范。面向金融/车联网等移动 App。
  触发词：移动开发、移动端、App 开发、iOS 开发、Android 开发、Swift、Kotlin、Flutter、React Native、
  跨端开发、原生开发、上架、应用商店、mobile app、移动应用、鸿蒙、HarmonyOS、HarmonyOS NEXT、ArkTS、ArkUI、华为上架。
license: MIT
agent_created: true
version: 1.1.0
---

# 掌中 (zhangzhong-mobile-dev) · 移动端原生与跨端开发

## 一、定位

`掌中` 是移动端原生与跨端开发 skill。它补齐 vibecoding 生态中"移动端原生开发"这一空白，
把移动 App 开发从"零散代码片段"收敛为**选型→架构→开发→测试→发布**的全流程方法论，
重点覆盖：

1. **技术选型**：原生（Swift/Kotlin）vs 跨端（Flutter/RN）的决策依据。
2. **架构模式**：MVVM/MVI、分层、依赖注入、状态管理。
3. **原生能力**：推送、定位、相机、支付、安全（Keychain/Keystore）。
4. **发布落地**：签名、打包、上架、合规（隐私政策/权限）。

## 二、何时使用

- 移动开发 / 移动端 / App 开发
- iOS 开发 / Android 开发 / Swift / Kotlin / SwiftUI / Compose
- Flutter / React Native / 跨端开发 / 原生开发
- 上架 / 应用商店 / 签名 / 打包
- 移动应用架构 / 状态管理 / 移动端性能

## 三、前置信息

| 输入 | 说明 | 缺失时 |
|---|---|---|
| 业务场景 | App 定位、核心功能、目标用户 | 问一个阻塞性问题 |
| 平台范围 | iOS / Android / 双端 / 跨端 | 问一个阻塞性问题 |
| 团队能力 | 原生 or Web 技术栈熟悉度 | 影响选型，默认双端跨端 |
| 上架要求 | 是否需上架、目标地区 | 默认中国区 + 海外 |

## 四、工作流（agent 执行）

```
步骤 1  选型决策   : 按「性能要求/团队栈/迭代速度/原生能力依赖/长期维护」给选型结论（原生 vs 跨端）；
                    涉及国内全终端覆盖时必须先查 references/harmonyos.md 的立项判据，决策表须含鸿蒙列。
步骤 2  架构设计   : 定分层架构（UI/状态/领域/数据），选状态管理（SwiftUI/Compose/Provider/Riverpod），
                    定义模块边界与依赖注入。
步骤 3  功能开发   : 按功能拆解，输出可编译的最小实现骨架 + 关键页面代码。
步骤 4  原生接入   : 推送/定位/相机/支付/安全存储等原生能力接入要点（含权限申请）。
步骤 5  测试       : 单元/UI/真机测试要点，性能与适配（多分辨率、刘海屏、深色模式）。
步骤 6  发布       : 签名配置、打包（App Store/各安卓商店/AppGallery 鸿蒙）、隐私合规、审核要点；
                    鸿蒙上架按 references/harmonyos.md 第五节执行（证书/Profile/隐私-权限一致性核对）。
步骤 7  交付       : 输出技术方案 + 开发规范 + 关键代码骨架。
```

## 五、移动开发要点（必守）

1. **安全**：密钥/Token 用 Keychain/Keystore 存储，禁止硬编码，传输加密，敏感数据脱敏。
2. **权限最小化**：按需申请权限，隐私政策声明数据用途（上架硬要求）。
3. **适配**：多分辨率/刘海屏/深色模式/无障碍。
4. **性能**：启动优化、列表复用、图片降采样、内存泄漏防泄漏。
5. **状态管理**：单一数据流，避免状态散落。

## 六、质量门控

1. 选型结论必须给「为什么」，对比原生/跨端的取舍，禁止拍脑袋。
2. 涉及敏感数据（金融/支付/隐私）必须给安全方案，禁止裸奔。
3. 发布方案须含签名/合规/审核要点，禁止只写代码不写落地。

## 七、输出格式

```
# 移动端技术方案
业务场景 / 平台范围 / 选型结论与理由
## 架构设计（分层/状态管理/模块边界）
## 关键功能实现骨架
## 原生能力接入清单
## 测试与适配方案
## 发布与合规（签名/隐私/审核）
```

## 八、目录

- `references/tech-selection.md` — 原生 vs 跨端选型决策矩阵
- `references/architecture.md` — 移动端架构模式与状态管理
- `references/release.md` — 签名/打包/上架/合规要点
- `references/harmonyos.md` — 鸿蒙（HarmonyOS NEXT）适配：立项判据、ArkTS/ArkUI 速览、含鸿蒙列的选型决策表、Android 迁移路径、AppGallery 上架要点（v1.1 新增）

## 九、免责声明

移动开发平台迭代快，本 skill 提供方法论与规范，具体 API 以官方最新文档为准；
上架与合规以各应用商店最新政策为准。
