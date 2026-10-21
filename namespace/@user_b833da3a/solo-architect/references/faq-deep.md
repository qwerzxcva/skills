# 深度 FAQ — 边缘场景与进阶优化

> 本文件补充 SKILL.md 主 FAQ 未覆盖的进阶优化场景，供高级开发者和架构师参考。

---

## 缓存策略 · 进阶问题

**Q：Redis 缓存和本地内存缓存怎么选？**

A：根据场景选择，也可以组合使用（多级缓存）：

| 维度 | 本地缓存（Caffeine / LRU） | Redis 缓存 |
|-----|--------------------------|-----------|
| 延迟 | ~0.01ms（进程内） | ~1ms（网络往返） |
| 容量 | 受 JVM/进程内存限制 | 可独立扩展至 GB 级 |
| 一致性 | 多实例间不一致 | 集中式，天然一致 |
| 适用场景 | 高频热点数据、只读配置 | 共享数据、需要一致性 |
| 典型实现 | Python: `lru_cache` / Java: Caffeine / JS: `lru-cache` | Python: `redis` / Java: `Jedis` / JS: `ioredis` |

**推荐的多级缓存架构：**
```
请求 → 本地缓存（L1，10ms TTL）→ Redis（L2，5min TTL）→ 数据库
```
- L1 命中：延迟最低，适合真正的热点数据
- L2 命中：延迟可接受，适合共享数据
- DB 兜底：保证数据不丢

---

**Q：缓存和数据库一致性怎么保证？**

A：根据业务容忍度选择策略：

| 策略 | 一致性 | 复杂度 | 适用场景 |
|-----|-------|-------|---------|
| Cache Aside（旁路缓存） | 最终一致 | ⭐ 低 | 大多数场景的推荐方案 |
| Write Through（写穿透） | 强一致 | ⭐⭐ 中 | 金融账户、库存 |
| Write Behind（写回） | 延迟一致 | ⭐⭐⭐ 高 | 日志、统计数据 |

**Cache Aside 实现要点：**
```
读：先查缓存 → 命中返回 → 未命中查 DB → 写入缓存
写：先更新 DB → 再删除缓存（不是更新缓存！）
```

**为什么删除缓存而不是更新缓存？**
- 避免并发写导致缓存和 DB 不一致
- 删除 + 惰性加载（Lazy Load）是更安全的方案
- 如需更强一致性，使用延迟双删：`删缓存 → 更新DB → 延迟500ms → 再删缓存`

---

**Q：缓存穿透、击穿、雪崩怎么处理？**

A：这是三个不同的缓存问题：

| 问题 | 原因 | 解决方案 |
|-----|------|---------|
| **缓存穿透** | 查询不存在的数据，缓存永远不命中 | 布隆过滤器 / 缓存空值（TTL 短） |
| **缓存击穿** | 热点 key 过期瞬间大量请求打到 DB | 互斥锁 / 永不过期 + 异步刷新 |
| **缓存雪崩** | 大量 key 同时过期 | TTL 随机偏移 / 多级缓存 / 熔断降级 |

```python
# 缓存穿透：布隆过滤器示例
from pybloom_live import ScalableBloomFilter

bloom = ScalableBloomFilter(initial_capacity=1000000)

# 启动时加载所有合法 ID
async def init_bloom():
    async for user_id in db.execute("SELECT id FROM users"):
        bloom.add(user_id)

@app.get("/api/users/{user_id}")
async def get_user(user_id: int):
    if user_id not in bloom:  # O(1) 快速判断
        return {"error": "User not found"}  # 不查 DB

    # 正常缓存逻辑...
```

---

## 异步处理 · 进阶问题

**Q：Celery / RabbitMQ / Kafka 怎么选？**

A：根据场景选择：

| 维度 | Celery + Redis | RabbitMQ | Kafka |
|-----|---------------|----------|-------|
| 定位 | Python 任务队列 | 通用消息代理 | 分布式流平台 |
| 吞吐量 | 万级/s | 十万级/s | 百万级/s |
| 消息持久化 | 依赖 Redis 配置 | 原生支持 | 原生支持（磁盘） |
| 消息顺序 | 不保证 | 单队列有序 | 单 Partition 有序 |
| 适用场景 | 中小项目异步任务 | 微服务解耦 | 大数据流、日志、事件溯源 |
| 运维复杂度 | ⭐ 低 | ⭐⭐ 中 | ⭐⭐⭐ 高 |

**选型建议：**
- **< 10 万 QPS 的 Python 项目** → Celery + Redis（最简单）
- **微服务间解耦** → RabbitMQ（功能全面）
- **大数据量 / 事件驱动架构** → Kafka（吞吐最强）

---

**Q：异步任务失败了怎么办？**

A：完整的异步任务需要包含以下容错机制：

```python
# Celery 完整容错配置示例
@celery_app.task(
    bind=True,                    # 支持自引用
    max_retries=3,                # 最大重试次数
    default_retry_delay=60,       # 重试间隔（指数退避更好）
    acks_late=True,               # 任务执行完才确认
    reject_on_worker_lost=True,   # Worker 崩溃时重新入队
)
def send_notification(self, user_id, message):
    try:
        user = get_user(user_id)
        send_email(user.email, message)
    except (ConnectionError, TimeoutError) as exc:
        # 网络错误，可重试
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
    except ValueError:
        # 业务错误，不重试，记录日志
        logger.error(f"Invalid data for user {user_id}")
        return {"status": "failed", "reason": "invalid_data"}
```

**容错检查清单：**
- [ ] 设置最大重试次数（避免无限重试）
- [ ] 使用指数退避（避免雪崩）
- [ ] 区分可重试错误和不可重试错误
- [ ] 死信队列兜底（最终失败的任务）
- [ ] 监控告警（任务积压、失败率）

---

## 索引优化 · 进阶问题

**Q：联合索引的字段顺序怎么排？**

A：遵循**最左前缀原则**：

```
索引 (A, B, C) 可以优化：
✅ WHERE A = ?
✅ WHERE A = ? AND B = ?
✅ WHERE A = ? AND B = ? AND C = ?
❌ WHERE B = ?                    （跳过了 A）
❌ WHERE C = ?                    （跳过了 A, B）
✅ WHERE A = ? AND C = ?          （A 走索引，C 不走）
```

**字段排序建议：**
1. **区分度高的字段在前**（如 user_id 比 status 更适合在前）
2. **等值查询字段在前，范围查询在后**（`WHERE status = 'paid' AND created_at > ?` → status 在前）
3. **ORDER BY 字段放在最后**（用于排序优化）

**常见错误：**
```sql
-- ❌ 区分度低的字段在前
INDEX (status, user_id, created_at)
-- status 只有几个值，过滤效果差

-- ✅ 区分度高的字段在前
INDEX (user_id, status, created_at)
-- user_id 唯一，快速缩小范围
```

---

**Q：索引越多越好吗？**

A：**不是。** 索引有代价：

| 代价 | 说明 |
|-----|------|
| 写入变慢 | 每次 INSERT/UPDATE/DELETE 都要更新索引 |
| 占用空间 | 一个索引可能占用原表 10-30% 的空间 |
| 优化器困惑 | 索引太多时，查询优化器可能选错索引 |

**建议：**
- 一张表索引数控制在 **5-8 个**以内
- 优先建联合索引，覆盖多个查询场景
- 用 **慢查询日志 + EXPLAIN** 验证索引效果，不盲目建索引
- 定期用 `pt-index-usage` 工具清理无用索引

---

**Q：大数据量分页怎么优化？**

A：传统 `LIMIT offset, size` 在 offset 很大时性能极差：

```sql
-- ❌ 深分页：扫描 100 万行只取 20 行
SELECT * FROM orders ORDER BY id LIMIT 1000000, 20;
-- 耗时 3s

-- ✅ 方案 1：游标分页（推荐）
SELECT * FROM orders WHERE id > 1000000 ORDER BY id LIMIT 20;
-- 耗时 0.005s，利用主键索引直接定位

-- ✅ 方案 2：子查询延迟关联
SELECT * FROM orders o
INNER JOIN (
    SELECT id FROM orders ORDER BY id LIMIT 1000000, 20
) tmp ON o.id = tmp.id;
-- 子查询只查索引（覆盖索引），速度更快

-- ✅ 方案 3：ES / 搜索引擎
-- 超过千万级数据，考虑 Elasticsearch 做搜索和分页
```

**分页方案对比：**

| 方案 | 适用场景 | 深分页性能 | 实现复杂度 |
|-----|---------|-----------|-----------|
| LIMIT offset | 传统分页，需要跳页 | 差（O(offset)） | ⭐ |
| 游标分页 | App/无限滚动 | 优（O(1)） | ⭐ |
| 延迟关联 | 必须支持跳页 | 良 | ⭐⭐ |
| ES 搜索 | 搜索 + 分页 | 优 | ⭐⭐⭐ |

---

## 架构层面 · 进阶问题

**Q：微服务和单体架构在性能方面的权衡？**

A：没有银弹，关键看规模：

| 维度 | 单体架构 | 微服务架构 |
|-----|---------|-----------|
| 网络开销 | 无（进程内调用） | 有（服务间 HTTP/gRPC） |
| 延迟 | 低（函数调用 ~0.01ms） | 高（网络调用 ~5-50ms） |
| 扩展性 | 整体扩缩 | 按服务独立扩缩 |
| 瓶颈定位 | 简单（单进程 profile） | 复杂（需要分布式追踪） |
| 适用阶段 | MVP / 小团队 / QPS < 1万 | 成熟产品 / 大团队 / QPS > 1万 |

**建议：**
- **起步阶段**：单体 + 模块化设计（为拆分留后路）
- **瓶颈出现时**：先做性能优化（缓存/索引/异步），80% 的性能问题不需要拆微服务
- **确实需要时**：按业务域拆分，优先拆出独立高频服务

---

**Q：如何建立性能优化的持续监控体系？**

A：建议三层监控：

```
L1：基础设施监控
├── CPU / 内存 / 磁盘 IO / 网络流量
├── 工具：Prometheus + Grafana
└── 告警：CPU > 80%、内存 > 85%

L2：应用性能监控（APM）
├── 接口延迟 P50/P95/P99
├── DB 查询耗时 & 慢查询
├── 外部调用耗时
├── 工具：SkyWalking / Jaeger / Datadog
└── 告警：P99 > 1s、慢查询 > 500ms

L3：业务指标监控
├── 核心业务转化率
├── 错误率 & 异常类型分布
├── 工具：自定义 Dashboard
└── 告警：错误率 > 1%、转化率下降 > 20%
```

**关键指标基线：**
- API P95 < 200ms
- DB 慢查询 < 100ms
- 缓存命中率 > 90%
- 错误率 < 0.1%

---

## Go 语言 · 进阶问题

**Q：Go 项目用什么缓存方案？**

A：根据场景选择：

| 方案 | 类型 | 适用场景 | 延迟 | 容量 |
|-----|------|---------|------|------|
| `go-cache` | 进程内 | 单实例、数据量 < 10万 | ~0.01ms | 受进程内存限制 |
| `ristretto` | 进程内 | 高性能、高并发读取 | ~0.01ms | 受进程内存限制 |
| `bigcache` | 进程内 | 海量数据、避免 GC 压力 | ~0.05ms | 可配置，堆外思路 |
| Redis | 分布式 | 多实例共享、需要一致性 | ~1ms | 独立扩展 |

**推荐组合：**
```
请求 → go-cache（L1，进程内 1min TTL）→ Redis（L2，分布式 5min TTL）→ 数据库
```

```go
// go-cache 基本用法
import "github.com/patrickmn/go-cache"

c := cache.New(5*time.Minute, 10*time.Minute)

// 写
c.Set("user:123", user, cache.DefaultExpiration)

// 读
if val, found := c.Get("user:123"); found {
    user = val.(User)
}
```

```go
// ristretto 高性能缓存
import "github.com/dgraph-io/ristretto"

cache, _ := ristretto.NewCache(&ristretto.Config{
    NumCounters: 1_000_000, // 跟踪频率的 key 数量
    MaxCost:     100 << 20, // 最大缓存成本（100MB）
    BufferItems: 64,        // 每个 Get buffer 的大小
})

cache.Set("user:123", user, 1) // cost = 1
if val, found := cache.Get("user:123"); found {
    user = val.(User)
}
```

---

## Rust 语言 · 进阶问题

**Q：Rust 的异步生态怎么选？**

A：核心选择是异步运行时，其余生态围绕它构建：

| 运行时 | 特点 | 适用场景 |
|--------|------|---------|
| `tokio` | 生态最丰富、社区标准 | 绝大多数场景的首选 |
| `async-std` | API 更接近标准库 | 轻量应用、标准库风格偏好 |

**异步任务队列选型：**

| 方案 | 适用场景 | 说明 |
|-----|---------|------|
| `tokio::spawn` | 轻量级 fire-and-forget | 进程内，无持久化 |
| `sidekiq-rs` | 需要 Redis 支持的任务队列 | 兼容 Sidekiq 协议 |
| 自定义 Channel | 进程内任务调度 | `tokio::sync::mpsc` + Worker |

```rust
// tokio::spawn 基本用法
tokio::spawn(async move {
    if let Err(e) = send_notification(user_id, message).await {
        tracing::error!("通知失败: {}", e);
    }
});

// 带 JoinHandle 等待结果
let handle = tokio::spawn(async move {
    expensive_computation()
});
let result = handle.await?;
```

```rust
// tokio Channel 任务队列模式
let (tx, mut rx) = tokio::sync::mpsc::channel::<Task>(100);

// 生产者
tx.send(Task { id: 1, payload: data }).await?;

// 消费者（Worker）
tokio::spawn(async move {
    while let Some(task) = rx.recv().await {
        process_task(task).await;
    }
});
```

---

## C#/.NET · 进阶问题

**Q：EF Core 有哪些常见的性能陷阱？**

A：以下是最高频的性能问题：

### 1. N+1 查询（延迟加载）

```csharp
// ❌ 延迟加载导致 N+1
var orders = _context.Orders.ToList(); // 1 次查询
foreach (var order in orders)
{
    var userName = order.User.Name; // 每条触发 1 次查询！
}

// ✅ 使用 Include 预加载
var orders = _context.Orders
    .Include(o => o.User)
    .ToList(); // 1 次 JOIN 查询
```

### 2. 变更追踪开销

```csharp
// ❌ 只读场景仍使用变更追踪
var users = _context.Users.ToList();

// ✅ 只读场景关闭追踪，性能提升 2-3x
var users = _context.Users.AsNoTracking().ToList();
```

### 3. ToList() 时机过早

```csharp
// ❌ 先全量加载再内存过滤
var users = _context.Users.ToList()
    .Where(u => u.CreatedAt > DateTime.Now.AddDays(-30));

// ✅ 在数据库端过滤
var users = _context.Users
    .Where(u => u.CreatedAt > DateTime.Now.AddDays(-30))
    .ToList();
```

### 4. 分页无上限保护

```csharp
// ❌ 客户端可传入任意 pageSize
var users = _context.Users
    .Skip((page - 1) * pageSize)
    .Take(pageSize)  // pageSize 可能是 100000！
    .ToList();

// ✅ 强制上限
pageSize = Math.Min(pageSize, 100);
```

### 5. Select N+1（投影未优化）

```csharp
// ❌ 加载完整实体再手动映射
var users = _context.Users.ToList();
var dtos = users.Select(u => new UserDto(u.Name, u.Email)).ToList();

// ✅ 直接在查询中投影，只查需要的列
var dtos = _context.Users
    .Select(u => new UserDto(u.Name, u.Email))
    .ToList();
```

| 陷阱 | 性能影响 | 修复难度 |
|------|---------|---------|
| N+1 延迟加载 | 🔴 严重 | ⭐ 低（加 Include） |
| 变更追踪 | 🟡 中等 | ⭐ 低（加 AsNoTracking） |
| ToList 过早 | 🔴 严重 | ⭐ 低（调整查询位置） |
| 分页无上限 | 🟡 高 | ⭐ 低（加 Math.Min） |
| 投影未优化 | 🟡 中等 | ⭐ 低（用 Select 投影） |
