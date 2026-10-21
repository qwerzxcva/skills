# Kotlin专家 — 模板与范例

> 本文件为 `kotlin-specialist` 的配套模板。所有 `<X>` 占位需结合用户实际场景替换，**禁止编造数据/密钥/业务规则**。

## 一、工作流要点

- 用 viewModelScope/lifecycleScope 管理取消
- Flow 用 stateIn/shareIn 避免重复订阅
- 用密封类建模状态
- 用类型安全 DSL 减少样板

## 二、质量自检清单

- [ ] 协程作用域是否随生命周期取消
- [ ] 是否主线程更新 UI
- [ ] Flow 是否正确处理背压
- [ ] 是否避免 GlobalScope
- [ ] 密封类是否覆盖全状态

## 三、工件示例（KotlinModuleSpec）

```json
{
  "module": "feed",
  "target": "Android",
  "coroutines": "viewModelScope",
  "notes": "Flow 用 stateIn 缓存"
}
```

## 四、常见陷阱

- 用 GlobalScope 致泄漏
- 在 IO 线程更新 UI
- Flow 多次 collect 重复工作
