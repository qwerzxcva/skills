# 优化示例集 — Before / After 完整代码对比

> 本文件收录三大优化策略的完整代码示例，覆盖 Python / Java / JavaScript / Go / Rust / C# 六种语言。
> 每个示例包含优化前代码、优化后代码和预期收益。

---

## 策略 01 · 缓存优先

> 适用场景：频繁读取且变更不频繁的数据

### 示例 1.1：Redis 缓存用户信息（Python）

**场景：** 用户信息接口被高频调用，数据库查询成为瓶颈

#### ❌ 优化前

```python
from fastapi import FastAPI
from database import get_db

app = FastAPI()

@app.get("/api/users/{user_id}")
async def get_user(user_id: int):
    # 每次请求都查数据库，2000 QPS 时数据库承受 2000 次查询/秒
    async with get_db() as db:
        result = await db.execute(
            "SELECT id, name, email, avatar FROM users WHERE id = %s",
            (user_id,)
        )
        user = await result.fetchone()
    if not user:
        return {"error": "User not found"}
    return dict(user)
```

**问题分析：**
- 每次请求 1 次 DB 查询
- 用户信息变更频率低（平均每天 < 1 次）
- 2000 QPS × 1 DB 查询 = 数据库压力巨大

#### ✅ 优化后

```python
import json
import redis.asyncio as redis
from fastapi import FastAPI
from database import get_db

app = FastAPI()
redis_client = redis.from_url("redis://localhost:6379/0")

CACHE_TTL = 300  # 5 分钟过期

@app.get("/api/users/{user_id}")
async def get_user(user_id: int):
    # 1. 先查缓存
    cached = await redis_client.get(f"user:{user_id}")
    if cached:
        return json.loads(cached)  # 缓存命中，直接返回

    # 2. 缓存未命中，查数据库
    async with get_db() as db:
        result = await db.execute(
            "SELECT id, name, email, avatar FROM users WHERE id = %s",
            (user_id,)
        )
        user = await result.fetchone()

    if not user:
        return {"error": "User not found"}

    user_dict = dict(user)

    # 3. 写入缓存
    await redis_client.setex(
        f"user:{user_id}",
        CACHE_TTL,
        json.dumps(user_dict, ensure_ascii=False)
    )

    return user_dict

# 缓存失效：用户信息更新时主动删除
async def invalidate_user_cache(user_id: int):
    await redis_client.delete(f"user:{user_id}")
```

**预期收益：**
- 缓存命中率 ~95%（用户信息变更频率低）
- DB 查询从 2000 QPS 降至 ~100 QPS
- 响应时间从 ~20ms 降至 ~2ms
- 实施难度：⭐ 低

---

### 示例 1.2：Spring Cache 注解式缓存（Java）

**场景：** 商品详情接口，数据变更频率低

#### ❌ 优化前

```java
@Service
public class ProductService {
    @Autowired
    private ProductRepository productRepository;

    public Product getProduct(Long id) {
        // 每次都查库
        return productRepository.findById(id)
            .orElseThrow(() -> new NotFoundException("Product not found"));
    }
}
```

#### ✅ 优化后

```java
@Service
public class ProductService {
    @Autowired
    private ProductRepository productRepository;

    @Cacheable(value = "products", key = "#id")  // 自动缓存
    public Product getProduct(Long id) {
        return productRepository.findById(id)
            .orElseThrow(() -> new NotFoundException("Product not found"));
    }

    @CacheEvict(value = "products", key = "#product.id")  // 更新时失效
    public Product updateProduct(Product product) {
        return productRepository.save(product);
    }
}

// application.yml
/*
spring:
  cache:
    type: redis
    redis:
      time-to-live: 300000  # 5 分钟
*/
```

**预期收益：**
- 一行注解实现缓存，代码改动最小
- 缓存命中率 ~90%
- 实施难度：⭐ 低

---

## 策略 02 · 异步处理

> 适用场景：耗时超过 500ms 的非核心业务逻辑

### 示例 2.1：异步发送通知（Python Celery）

**场景：** 用户注册后发送欢迎邮件 + 短信，耗时 2-5s，阻塞注册接口

#### ❌ 优化前

```python
@app.post("/api/register")
async def register(data: RegisterRequest):
    # 1. 创建用户（核心逻辑，50ms）
    user = await create_user(data)

    # 2. 发送欢迎邮件（阻塞 1-3s）
    await send_welcome_email(user.email, user.name)

    # 3. 发送短信通知（阻塞 1-2s）
    await send_sms(user.phone, "注册成功！")

    # 用户等 3-5s 才收到响应，体验差
    return {"user_id": user.id, "message": "注册成功"}
```

#### ✅ 优化后

```python
from celery import Celery

celery_app = Celery('tasks', broker='redis://localhost:6379/1')

@celery_app.task
def send_welcome_email_task(email, name):
    send_welcome_email(email, name)  # 不再阻塞主线程

@celery_app.task
def send_sms_task(phone, message):
    send_sms(phone, message)

@app.post("/api/register")
async def register(data: RegisterRequest):
    # 1. 创建用户（核心逻辑）
    user = await create_user(data)

    # 2. 异步发送通知（立即返回，不等待）
    send_welcome_email_task.delay(user.email, user.name)
    send_sms_task.delay(user.phone, "注册成功！")

    # 响应时间从 3-5s 降至 ~50ms
    return {"user_id": user.id, "message": "注册成功"}
```

**预期收益：**
- 接口响应时间从 3-5s 降至 ~50ms
- 用户体验大幅提升
- 邮件/短信失败不影响注册流程
- 实施难度：⭐⭐ 中

---

### 示例 2.2：异步报告生成（JavaScript BullMQ）

**场景：** 导出 10 万条数据的 Excel 报告，耗时 30s+

#### ❌ 优化前

```javascript
app.post('/api/reports/export', async (req, res) => {
  // 同步生成报告，30s+ 阻塞，前端超时
  const data = await Order.findAll({ /* 10 万条 */ });
  const buffer = await generateExcel(data);  // 耗时 30s
  res.setHeader('Content-Type', 'application/vnd.ms-excel');
  res.send(buffer);
});
```

#### ✅ 优化后

```javascript
import { Queue, Worker } from 'bullmq';

const reportQueue = new Queue('reports', { connection: redis });

// API：提交任务，立即返回
app.post('/api/reports/export', async (req, res) => {
  const job = await reportQueue.add('generate', {
    userId: req.user.id,
    filters: req.body.filters,
  });
  res.json({
    taskId: job.id,
    status: 'processing',
    message: '报告生成中，请稍后通过 /api/reports/status/:taskId 查询',
  });
});

// Worker：后台处理
const worker = new Worker('reports', async (job) => {
  const data = await Order.findAll({ where: job.data.filters });
  const buffer = await generateExcel(data);
  const url = await uploadToS3(buffer, `report-${job.id}.xlsx`);
  return { url };
}, { connection: redis });

// 查询任务状态
app.get('/api/reports/status/:taskId', async (req, res) => {
  const job = await reportQueue.getJob(req.params.taskId);
  if (!job) return res.status(404).json({ error: '任务不存在' });
  if (await job.isCompleted()) {
    const result = job.returnvalue;
    return res.json({ status: 'completed', downloadUrl: result.url });
  }
  res.json({ status: 'processing', progress: job.progress });
});
```

**预期收益：**
- 接口响应从 30s+ 降至 ~100ms（提交任务即可）
- 用户体验：异步下载，不阻塞操作
- 支持大规模数据处理
- 实施难度：⭐⭐ 中

---

## 策略 03 · 索引优化

> 适用场景：涉及 WHERE 过滤、ORDER BY 排序的慢查询

### 示例 3.1：订单查询索引优化（SQL）

**场景：** 按用户 ID 查询最近订单，排序创建时间，查询耗时 3s

#### ❌ 优化前

```sql
-- 慢查询：3.2s
SELECT id, user_id, amount, status, created_at
FROM orders
WHERE user_id = 12345
  AND status = 'paid'
ORDER BY created_at DESC
LIMIT 20;

-- EXPLAIN 结果：
-- type: ALL (全表扫描)
-- rows: 2,000,000 (扫描 200 万行)
-- Extra: Using where; Using filesort
```

**问题分析：**
- 全表扫描 200 万行
- 无索引支撑 WHERE 和 ORDER BY
- Using filesort：额外的排序操作

#### ✅ 优化后

```sql
-- 添加联合索引
ALTER TABLE orders
ADD INDEX idx_user_status_created (user_id, status, created_at DESC);

-- 优化后的查询（SQL 不变，索引生效）
SELECT id, user_id, amount, status, created_at
FROM orders
WHERE user_id = 12345
  AND status = 'paid'
ORDER BY created_at DESC
LIMIT 20;

-- EXPLAIN 结果：
-- type: ref (索引查找)
-- rows: 50 (只扫描 50 行)
-- Extra: Using index condition
```

**预期收益：**
- 查询时间从 3.2s 降至 0.005s
- 扫描行数从 200 万降至 50
- 完全消除 filesort
- 实施难度：⭐ 低

---

### 示例 3.2：避免索引失效的常见错误

```sql
-- ❌ 索引失效：在索引列上使用函数
SELECT * FROM orders WHERE DATE(created_at) = '2026-06-01';
-- ✅ 索引生效：范围查询
SELECT * FROM orders
WHERE created_at >= '2026-06-01' AND created_at < '2026-06-02';

-- ❌ 索引失效：左侧模糊查询
SELECT * FROM users WHERE name LIKE '%张';
-- ✅ 索引生效：右侧模糊
SELECT * FROM users WHERE name LIKE '张%';

-- ❌ 索引失效：隐式类型转换
SELECT * FROM orders WHERE user_id = '12345';  -- user_id 是 INT，传入 STRING
-- ✅ 索引生效：类型匹配
SELECT * FROM orders WHERE user_id = 12345;

-- ❌ 索引失效：OR 条件导致放弃索引
SELECT * FROM orders WHERE user_id = 1 OR amount > 1000;
-- ✅ 索引生效：UNION 替代 OR
SELECT * FROM orders WHERE user_id = 1
UNION
SELECT * FROM orders WHERE amount > 1000;
```

---

## 综合案例：API 接口从 P0 到优化的完整过程

**场景：** 电商订单列表接口，数据量 100 万订单，当前响应 8s

### Step 1：思维链评估

```
<thinking>
复杂度分析：
- 当前 SQL 无索引，ORDER BY + WHERE 导致全表扫描 + filesort
- O(n) 全表扫描 × O(n log n) 排序 = O(n² log n) 级别
- 100 万行数据量下完全不可接受

I/O 识别：
- 1 次全表扫描查询（3s）
- 循环内查询用户信息（N+1，50ms × N）
- 循环内查询商品信息（N+1，50ms × N）

边界条件：
- 订单量 100 万时已需 8s
- 扩大 10 倍（1000 万）预计 80s+，完全不可用
</thinking>
```

### Step 2：问题定位

```
🔴 1. 全表扫描：orders 表缺少 (user_id, status, created_at) 联合索引
🔴 2. N+1 查询：循环内查询 users 表和 products 表
🟡 3. 无 limit 保护：未限制返回条数上限
```

### Step 3：优化实施

```python
# 优化后的完整代码
from functools import lru_cache

@app.get("/api/orders")
async def list_orders(
    user_id: int,
    status: str = None,
    page: int = 1,
    page_size: int = 20,
):
    # 修复 1：强制 limit 上限
    page_size = min(page_size, 100)

    # 修复 2：单条 SQL + JOIN 替代 N+1
    query = """
        SELECT
            o.id, o.amount, o.status, o.created_at,
            u.name as user_name,
            p.name as product_name
        FROM orders o
        LEFT JOIN users u ON o.user_id = u.id
        LEFT JOIN products p ON o.product_id = p.id
        WHERE o.user_id = %s
    """
    params = [user_id]

    if status:
        query += " AND o.status = %s"
        params.append(status)

    query += " ORDER BY o.created_at DESC LIMIT %s OFFSET %s"
    params.extend([page_size, (page - 1) * page_size])

    async with get_db() as db:
        result = await db.execute(query, params)
        orders = await result.fetchall()

    return [dict(o) for o in orders]
```

```sql
-- 修复 3：添加联合索引
ALTER TABLE orders
ADD INDEX idx_user_status_created (user_id, status, created_at DESC);
```

### Step 4：自检清单

```
✅ 1. 嵌套循环：已消除，使用 JOIN 替代 N+1
✅ 2. 响应时间：预估 50ms，在 200ms 以内
✅ 3. 降级限流：已添加 limit 保护
✅ 4. 索引：已添加联合索引
✅ 5. 并发安全：只读操作，无并发问题
```

### 最终收益

| 指标 | 优化前 | 优化后 | 提升 |
|------|-------|-------|------|
| 响应时间 | 8s | 50ms | **160x** |
| DB 查询次数 | 1 + N×2 | 1 | **N×2 → 0** |
| 扫描行数 | 100 万 | 50 | **20000x** |
| 并发支持 | ~10 QPS | ~2000 QPS | **200x** |

---

## 策略 01 · 缓存优先 — Go / Rust / C# 补充

### 示例 1.3：go-cache 本地缓存（Go + Gin）

**场景：** 用户信息接口高频调用，减少数据库压力

#### ❌ 优化前

```go
func getUser(c *gin.Context) {
    userID := c.Param("id")
    // 每次请求都查数据库
    var user User
    if err := db.Where("id = ?", userID).First(&user).Error; err != nil {
        c.JSON(404, gin.H{"error": "User not found"})
        return
    }
    c.JSON(200, user)
}
```

#### ✅ 优化后

```go
import "github.com/patrickmn/go-cache"

var userCache = cache.New(5*time.Minute, 10*time.Minute)

func getUser(c *gin.Context) {
    userID := c.Param("id")

    // 1. 先查缓存
    if val, found := userCache.Get("user:" + userID); found {
        c.JSON(200, val.(User))
        return
    }

    // 2. 缓存未命中，查数据库
    var user User
    if err := db.Where("id = ?", userID).First(&user).Error; err != nil {
        c.JSON(404, gin.H{"error": "User not found"})
        return
    }

    // 3. 写入缓存
    userCache.Set("user:"+userID, user, cache.DefaultExpiration)
    c.JSON(200, user)
}
```

**预期收益：**
- 缓存命中率 ~90%（用户信息变更频率低）
- DB 查询从 2000 QPS 降至 ~200 QPS
- 响应时间从 ~15ms 降至 ~0.5ms（本地缓存无网络开销）
- 实施难度：⭐ 低

---

### 示例 1.4：moka 缓存商品详情（Rust + actix-web）

**场景：** 商品详情接口，数据变更频率低

#### ❌ 优化前

```rust
async fn get_product(path: web::Path<i64>) -> HttpResponse {
    let product_id = path.into_inner();

    // 每次都查数据库
    let product = sqlx::query_as!(Product,
        "SELECT id, name, price, description FROM products WHERE id = $1",
        product_id
    ).fetch_optional(&db_pool).await;

    match product {
        Ok(Some(p)) => HttpResponse::Ok().json(p),
        Ok(None) => HttpResponse::NotFound().json(serde_json::json!({"error": "Not found"})),
        Err(_) => HttpResponse::InternalServerError().finish(),
    }
}
```

#### ✅ 优化后

```rust
use moka::future::Cache;
use once_cell::sync::Lazy;

static PRODUCT_CACHE: Lazy<Cache<i64, Product>> = Lazy::new(|| {
    Cache::builder()
        .max_capacity(10_000)
        .time_to_live(std::time::Duration::from_secs(300)) // 5 分钟 TTL
        .build()
});

async fn get_product(path: web::Path<i64>) -> HttpResponse {
    let product_id = path.into_inner();

    // 先查缓存，未命中时自动加载
    let product = PRODUCT_CACHE.get_or_insert_with(product_id, async {
        sqlx::query_as!(Product,
            "SELECT id, name, price, description FROM products WHERE id = $1",
            product_id
        ).fetch_optional(&db_pool).await.unwrap()
    }).await;

    match product {
        Some(p) => HttpResponse::Ok().json(p),
        None => HttpResponse::NotFound().json(serde_json::json!({"error": "Not found"})),
    }
}
```

**预期收益：**
- moka 是高性能并发缓存，读写均无锁
- 缓存命中率 ~95%
- 响应时间从 ~10ms 降至 ~0.01ms
- 实施难度：⭐ 低

---

### 示例 1.5：IMemoryCache 注入式缓存（C# + ASP.NET Core）

**场景：** 商品详情接口，利用 DI 容器管理缓存生命周期

#### ❌ 优化前

```csharp
[HttpGet("products/{id}")]
public async Task<ActionResult<Product>> GetProduct(int id)
{
    // 每次都查数据库
    var product = await _context.Products.FindAsync(id);
    if (product == null) return NotFound();
    return product;
}
```

#### ✅ 优化后

```csharp
public class ProductService
{
    private readonly IMemoryCache _cache;
    private readonly AppDbContext _context;

    public ProductService(IMemoryCache cache, AppDbContext context)
    {
        _cache = cache;
        _context = context;
    }

    public async Task<Product?> GetProductAsync(int id)
    {
        return await _cache.GetOrCreateAsync($"product:{id}", async entry =>
        {
            entry.AbsoluteExpirationRelativeToNow = TimeSpan.FromMinutes(5);
            return await _context.Products
                .AsNoTracking()
                .FirstOrDefaultAsync(p => p.Id == id);
        });
    }
}

// Controller
[HttpGet("products/{id}")]
public async Task<ActionResult<Product>> GetProduct(int id)
{
    var product = await _productService.GetProductAsync(id);
    if (product == null) return NotFound();
    return product;
}
```

**预期收益：**
- 利用 DI 容器，缓存生命周期由框架管理
- `AsNoTracking()` 减少变更追踪开销
- 一行 `GetOrCreateAsync` 实现缓存逻辑
- 实施难度：⭐ 低

---

## 策略 02 · 异步处理 — Go / Rust / C# 补充

### 示例 2.3：Goroutine 异步发送通知（Go）

**场景：** 用户注册后发送欢迎邮件 + 短信

#### ❌ 优化前

```go
func register(c *gin.Context) {
    var req RegisterRequest
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(400, gin.H{"error": err.Error()})
        return
    }

    user, err := createUser(req)
    if err != nil {
        c.JSON(500, gin.H{"error": err.Error()})
        return
    }

    // 同步发送邮件（1-3s）
    sendWelcomeEmail(user.Email, user.Name)
    // 同步发送短信（1-2s）
    sendSMS(user.Phone, "注册成功！")

    // 用户等 3-5s 才收到响应
    c.JSON(200, gin.H{"user_id": user.ID, "message": "注册成功"})
}
```

#### ✅ 优化后

```go
func register(c *gin.Context) {
    var req RegisterRequest
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(400, gin.H{"error": err.Error()})
        return
    }

    user, err := createUser(req)
    if err != nil {
        c.JSON(500, gin.H{"error": err.Error()})
        return
    }

    // 异步发送通知，不阻塞响应
    go func() {
        if err := sendWelcomeEmail(user.Email, user.Name); err != nil {
            log.Printf("发送欢迎邮件失败: %v", err)
        }
    }()
    go func() {
        if err := sendSMS(user.Phone, "注册成功！"); err != nil {
            log.Printf("发送短信失败: %v", err)
        }
    }()

    // 响应时间从 3-5s 降至 ~50ms
    c.JSON(200, gin.H{"user_id": user.ID, "message": "注册成功"})
}
```

**预期收益：**
- 利用 goroutine 原生并发，无需额外框架
- 接口响应从 3-5s 降至 ~50ms
- 实施难度：⭐ 低（Go 原生支持）
- **注意：** goroutine 无重试机制，生产环境建议用 `asynq` 等任务队列

---

### 示例 2.4：tokio::spawn 异步任务（Rust）

**场景：** 数据处理完成后异步通知

#### ❌ 优化前

```rust
async fn process_data(data: web::Json<ProcessRequest>) -> HttpResponse {
    // 核心处理逻辑
    let result = expensive_processing(&data).await;

    // 同步发送通知（阻塞 1-2s）
    send_notification(&data.user_id, &result).await;
    // 同步记录审计日志（阻塞 500ms）
    write_audit_log(&data, &result).await;

    // 用户等 1.5-2.5s
    HttpResponse::Ok().json(result)
}
```

#### ✅ 优化后

```rust
async fn process_data(data: web::Json<ProcessRequest>) -> HttpResponse {
    // 核心处理逻辑
    let result = expensive_processing(&data).await;

    // 异步发送通知（fire-and-forget，带错误日志）
    let user_id = data.user_id.clone();
    let result_clone = result.clone();
    tokio::spawn(async move {
        if let Err(e) = send_notification(&user_id, &result_clone).await {
            tracing::error!("发送通知失败: {}", e);
        }
    });

    // 异步记录审计日志
    let data_clone = data.into_inner();
    let result_clone2 = result.clone();
    tokio::spawn(async move {
        if let Err(e) = write_audit_log(&data_clone, &result_clone2).await {
            tracing::error!("记录审计日志失败: {}", e);
        }
    });

    // 响应时间从 1.5-2.5s 降至 ~200ms
    HttpResponse::Ok().json(result)
}
```

**预期收益：**
- `tokio::spawn` 零成本抽象，无额外线程开销
- 接口响应从 1.5-2.5s 降至 ~200ms
- 实施难度：⭐ 低（Rust 异步运行时原生支持）

---

### 示例 2.5：BackgroundService 异步报告生成（C#）

**场景：** 导出大量数据的 Excel 报告

#### ❌ 优化前

```csharp
[HttpPost("reports/export")]
public async Task<IActionResult> ExportReport([FromBody] ReportFilter filter)
{
    // 同步生成报告，30s+ 阻塞，前端超时
    var data = await _context.Orders
        .Where(o => filter.IsMatch(o))
        .ToListAsync();
    var buffer = GenerateExcel(data); // 耗时 30s
    return File(buffer, "application/vnd.ms-excel", "report.xlsx");
}
```

#### ✅ 优化后

```csharp
// API：提交任务，立即返回
[HttpPost("reports/export")]
public async Task<IActionResult> ExportReport([FromBody] ReportFilter filter)
{
    var job = new ReportJob
    {
        Id = Guid.NewGuid(),
        UserId = User.GetUserId(),
        Filter = filter,
        Status = ReportStatus.Pending,
        CreatedAt = DateTime.UtcNow,
    };
    _context.ReportJobs.Add(job);
    await _context.SaveChangesAsync();

    // 入队后台处理
    _channelWriter.TryWrite(job.Id);

    return Accepted(new { taskId = job.Id, status = "processing" });
}

// 后台服务
public class ReportBackgroundService : BackgroundService
{
    private readonly ChannelReader<Guid> _reader;
    private readonly IServiceProvider _services;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        await foreach (var jobId in _reader.ReadAllAsync(stoppingToken))
        {
            using var scope = _services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();

            var job = await db.ReportJobs.FindAsync(jobId);
            if (job == null) continue;

            try
            {
                job.Status = ReportStatus.Processing;
                await db.SaveChangesAsync(stoppingToken);

                var data = await db.Orders
                    .Where(o => job.Filter.IsMatch(o))
                    .AsNoTracking()
                    .ToListAsync(stoppingToken);
                var buffer = GenerateExcel(data);
                var url = await UploadToS3(buffer, $"report-{jobId}.xlsx");

                job.Status = ReportStatus.Completed;
                job.DownloadUrl = url;
            }
            catch (Exception ex)
            {
                job.Status = ReportStatus.Failed;
                job.Error = ex.Message;
            }
            await db.SaveChangesAsync(stoppingToken);
        }
    }
}
```

**预期收益：**
- 接口响应从 30s+ 降至 ~100ms
- `BackgroundService` 由 ASP.NET Core 托管，无需额外进程
- 支持任务状态查询和错误处理
- 实施难度：⭐⭐ 中

---

## 策略 03 · 索引优化 — Go / C# 补充

> 索引优化的核心是 SQL 层面的 DDL，与语言无关。以下补充各语言的索引定义方式和查询优化写法。

### 示例 3.3：Go sqlx 索引优化查询

```go
// 优化前：全表扫描
func getOrders(userID int64, status string) ([]Order, error) {
    return []Order{}, sqlx.Select(&db,
        "SELECT * FROM orders WHERE user_id = $1 AND status = $2 ORDER BY created_at DESC",
        userID, status)
}

// 优化后：确保索引存在 + 查询走索引
// 1. 先创建索引（迁移脚本）
// CREATE INDEX idx_orders_user_status_created ON orders(user_id, status, created_at DESC);

// 2. 查询代码不变，索引自动生效
func getOrders(userID int64, status string, page, pageSize int) ([]Order, error) {
    offset := (page - 1) * pageSize
    return []Order{}, sqlx.Select(&db,
        `SELECT id, user_id, amount, status, created_at
         FROM orders
         WHERE user_id = $1 AND status = $2
         ORDER BY created_at DESC
         LIMIT $3 OFFSET $4`,
        userID, status, pageSize, offset)
}
```

### 示例 3.4：EF Core 索引注解（C#）

```csharp
// 方式 1：Data Annotation
[Index(nameof(UserId), nameof(Status), nameof(CreatedAt), Name = "idx_user_status_created")]
public class Order
{
    public long Id { get; set; }
    public long UserId { get; set; }
    public string Status { get; set; } = "";
    public decimal Amount { get; set; }
    public DateTime CreatedAt { get; set; }

    // 导航属性
    public User User { get; set; } = null!;
}

// 方式 2：Fluent API（更灵活）
protected override void OnModelCreating(ModelBuilder modelBuilder)
{
    modelBuilder.Entity<Order>(entity =>
    {
        entity.HasIndex(o => new { o.UserId, o.Status, o.CreatedAt })
              .HasDatabaseName("idx_user_status_created")
              .HasSortOrder(0, 0, SortOrder.Descending); // created_at DESC
    });
}

// 查询（EF Core 自动生成走索引的 SQL）
var orders = await _context.Orders
    .Where(o => o.UserId == userId && o.Status == "paid")
    .OrderByDescending(o => o.CreatedAt)
    .Take(20)
    .AsNoTracking()
    .ToListAsync();
```

---

## 综合案例补充：Go 版本

**场景：** 电商订单列表接口（Go + Gin + GORM），数据量 100 万订单，当前响应 8s

### 优化后的完整代码

```go
func listOrders(c *gin.Context) {
    userID, _ := strconv.ParseInt(c.Query("user_id"), 10, 64)
    status := c.Query("status")
    page, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
    pageSize, _ := strconv.Atoi(c.DefaultQuery("page_size", "20"))

    // 修复 1：强制 limit 上限
    if pageSize <= 0 { pageSize = 20 }
    if pageSize > 100 { pageSize = 100 }
    offset := (page - 1) * pageSize

    // 修复 2：单条 SQL + JOIN 替代 N+1
    query := `
        SELECT
            o.id, o.amount, o.status, o.created_at,
            u.name as user_name,
            p.name as product_name
        FROM orders o
        LEFT JOIN users u ON o.user_id = u.id
        LEFT JOIN products p ON o.product_id = p.id
        WHERE o.user_id = ?`
    args := []interface{}{userID}

    if status != "" {
        query += " AND o.status = ?"
        args = append(args, status)
    }

    query += " ORDER BY o.created_at DESC LIMIT ? OFFSET ?"
    args = append(args, pageSize, offset)

    var results []map[string]interface{}
    db.Raw(query, args...).Scan(&results)

    c.JSON(200, results)
}
```

```sql
-- 修复 3：添加联合索引
ALTER TABLE orders
ADD INDEX idx_user_status_created (user_id, status, created_at DESC);
```

### 最终收益

| 指标 | 优化前 | 优化后 | 提升 |
|------|-------|-------|------|
| 响应时间 | 8s | 50ms | **160x** |
| DB 查询次数 | 1 + N×2 | 1 | **N×2 → 0** |
| 扫描行数 | 100 万 | 50 | **20000x** |
| 并发支持 | ~10 QPS | ~2000 QPS | **200x** |
