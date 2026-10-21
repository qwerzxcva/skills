# 移动端架构模式与状态管理

## 分层架构

```
UI 层（页面/组件）
  ↓
状态层（State Management）
  ↓
领域层（业务逻辑/UseCase）
  ↓
数据层（Repository → 网络/本地/缓存）
```

原则：单向数据流，UI 只读状态，通过事件/意图修改状态。

## 架构模式

| 模式 | 说明 | 适用 |
|---|---|---|
| MVVM | View ↔ ViewModel ↔ Model | 主流，成熟 |
| MVI | 意图驱动，单一不可变状态 | 状态复杂、可预测性强 |
| Clean Architecture | 分层 + 依赖倒置 | 大型、长期维护项目 |

## 状态管理选型

| 平台 | 推荐 | 说明 |
|---|---|---|
| Android (Kotlin) | Compose + ViewModel/StateFlow | 官方推荐 |
| iOS (Swift) | SwiftUI + @State/ObservableObject | 官方推荐 |
| Flutter | Riverpod / Bloc | Riverpod 简洁，Bloc 严谨 |
| React Native | Zustand / Redux Toolkit | Zustand 轻量 |

## 依赖注入

- **Android**：Hilt（官方）
- **iOS**：手动注入 / Swinject
- **Flutter**：Provider / get_it
- **RN**：容器 + Context

## 数据层

- **Repository 模式**：隔离数据来源（网络/本地/缓存），领域层不关心来源。
- **缓存策略**：内存缓存 + 持久化（数据库），先缓存后网络。
- **DTO → 领域模型**：网络返回 DTO，转领域模型再进状态层。

## 安全（金融场景重点）

- 敏感数据（Token/银行卡）存 Keychain（iOS）/Keystore（Android），禁止明文。
- 传输 HTTPS + 证书校验，关键接口加签名。
- 敏感字段展示脱敏，日志不打印敏感信息。

## 常见反模式

- ❌ 页面里堆业务逻辑（应下沉领域层）
- ❌ 状态散落在多个地方（应单一数据流）
- ❌ 密钥硬编码在代码里
