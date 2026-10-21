---
name: fault-injection
description: 故障注入与性能瓶颈注入技能。触发条件：生成代码、修改代码、创建需求（涉及接口/模块/服务）。自动询问用户是否进行瓶颈注入及注入类型。支持 9 种瓶颈类型（CPU/内存/IO/网络/并发/数据库/限流/熔断/资源耗尽），支持 14 种语言（Python/JavaScript/TypeScript/Java/Go/Rust/C#/Ruby/PHP/Kotlin/Swift/C++/Zig/Dart），内置自动注入脚本和 Web 框架中间件模板。
---

# Fault Injection Skill

## 触发条件

满足以下任一场景时触发本技能：

1. **生成代码** — 创建新的接口、模块、服务、工具函数
2. **修改代码** — 对现有代码进行重构、扩展、优化
3. **创建需求** — 需求涉及 API、后台服务、数据处理链路

## 工作流

### 第一步：询问注入意愿

> **是否需要进行瓶颈注入（Fault Injection）？**
> 主动制造性能瓶颈，用于测试系统在压力下的表现。
> - `是` → 进入注入流程
> - `否` → 正常执行任务

### 第二步：选择注入类型

| 编号 | 类型 | 环境变量 | 说明 |
|------|------|----------|------|
| 1 | CPU 瓶颈 | `FAULT_CPU` | 密集计算循环，CPU 持续高负载 |
| 2 | 内存泄漏 | `FAULT_MEM_LEAK` | 持续分配对象不释放，模拟泄漏 |
| 3 | IO 阻塞 | `FAULT_IO_BLOCK` | 同步读写、串行请求、慢 IO |
| 4 | 网络延迟 | `FAULT_NET_LATENCY` | 中间件层注入延迟，模拟抖动 |
| 5 | 并发争用 | `FAULT_CONCURRENCY` | 锁竞争、信号量阻塞、线程池耗尽 |
| 6 | 数据库瓶颈 | `FAULT_DB_N_PLUS_ONE` | N+1 查询、无索引查询 |
| 7 | 限流熔断 | `FAULT_RATELIMIT` / `FAULT_CIRCUIT_BREAKER` | 令牌桶限流、熔断降级 |
| 8 | 资源耗尽 | `FAULT_OOM` | 内存耗尽、FD 耗尽 |
| 9 | 全部注入 | `FAULT_INJECT_ENABLED` | 综合注入所有类型 |

### 第三步：选择开发语言

> 请选择目标语言：
> 1. Python | 2. JavaScript | 3. TypeScript | 4. Java | 5. Go | 6. Rust | 7. C# | 8. Ruby | 9. PHP | 10. Kotlin | 11. Swift | 12. C++ | 13. Zig | 14. Dart

### 第四步：执行注入

根据用户选择，使用以下方式之一注入：

**方式 A：自动化脚本（推荐用于已有代码文件）**
```
python3 scripts/auto_inject.py <文件或目录> --type <瓶颈类型> [--type <类型2>] --report
```
脚本会自动识别语言、找到最佳注入点（函数/方法定义行）、插入带标记的瓶颈代码、生成 JSON 报告。

**方式 B：手动模板（用于生成新代码）**
参考 `references/bottleneck-patterns.md` 中的对应语言实现，在生成的代码中嵌入注入点。

**方式 C：Web 框架中间件**
对于 Web 服务，优先使用 `references/framework-middlewares.md` 中的框架中间件模板，更符合实际工程实践。

## 注入原则

1. 所有注入点必须**有明确注释标记**（`[FAULT_INJECT]`），便于后续定位和清理
2. 使用**环境变量开关**，默认**不启用**（`FAULT_INJECT_ENABLED=false`）
3. 注入代码**不影响正常逻辑**，仅在开启时触发
4. 每个文件每个类型只注入**第一个匹配的方法/函数**

## 自动化脚本（auto_inject.py）

### 安装
无需安装，直接运行：
```bash
python3 scripts/auto_inject.py --help
```

### 常用命令

```bash
# 注入 CPU 瓶颈到单个文件
python3 scripts/auto_inject.py app.py --type cpu

# 注入多个瓶颈类型
python3 scripts/auto_inject.py api.py --type cpu --type io-block --type net-latency

# 注入所有类型
python3 scripts/auto_inject.py server.py --type all

# 直接启用（跳过环境变量检查，默认开启）
python3 scripts/auto_inject.py app.py --type cpu --enable

# 生成注入报告（JSON）
python3 scripts/auto_inject.py src/ --type ratelimit --type circuit-breaker --report

# 清理文件中的所有注入点
python3 scripts/auto_inject.py app.py --clean

# 强制指定语言（覆盖自动推断）
python3 scripts/auto_inject.py app.txt --type cpu --lang python
```

### 环境变量速查（脚本启用时）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `FAULT_INJECT_ENABLED` | 总开关 | `false` |
| `FAULT_CPU` | CPU 瓶颈 | `false` |
| `FAULT_CPU_DURATION` | CPU 持续时间（秒） | `5` |
| `FAULT_MEM_LEAK` | 内存泄漏 | `false` |
| `FAULT_LEAK_CHUNK_MB` | 每次泄漏块大小（MB） | `10` |
| `FAULT_IO_BLOCK` | IO 阻塞 | `false` |
| `FAULT_IO_DELAY_MS` | IO 延迟（毫秒） | `3000` |
| `FAULT_NET_LATENCY` | 网络延迟 | `false` |
| `FAULT_NET_LATENCY_MS` | 网络延迟（毫秒） | `500` |
| `FAULT_CONCURRENCY` | 并发争用 | `false` |
| `FAULT_LOCK_HOLD_MS` | 锁持有时间（毫秒） | `100` |
| `FAULT_RATELIMIT` | 限流 | `false` |
| `FAULT_RATE_LIMIT` | 限流阈值（次/秒） | `10` |
| `FAULT_CIRCUIT_BREAKER` | 熔断器 | `false` |
| `FAULT_DB_N_PLUS_ONE` | N+1 查询 | `false` |
| `FAULT_OOM` | 内存耗尽 | `false` |
| `FAULT_OOM_CHUNK_MB` | OOM 每次分配（MB） | `50` |

## 参考资料

| 文件 | 说明 |
|------|------|
| `references/bottleneck-patterns.md` | 14 种语言 × 9 种瓶颈类型的完整代码实现 |
| `references/framework-middlewares.md` | Flask / Express / Gin / Django / Rails / Laravel / Spring Boot / ASP.NET Core / Ktor / Vapor / C++ 的中间件模板 |
