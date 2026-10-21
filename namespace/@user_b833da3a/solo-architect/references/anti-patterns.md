# 反模式详解 — 错误示例、修复方案与检测方法

> 本文件收录四大硬性反模式的详细解析，包含多语言错误示例、修复代码和检测方法。
> 覆盖语言：Python / Java / JavaScript / Go / Rust / C#。

---

## 反模式 01：N+1 查询

**定义：** 在循环内部执行数据库查询或 API 调用，导致请求数随数据量线性增长。

**严重程度：** 🔴 严重 — 1000 条数据可能产生 1000+ 次数据库调用

### ❌ Python（Django ORM）

```python
# 错误：每个用户都查询一次订单表
users = User.objects.all()
for user in users:
    orders = Order.objects.filter(user_id=user.id)  # N+1！
    user.order_count = len(orders)
```

### ✅ Python（Django ORM）修复

```python
# 正确：使用 prefetch_related 一次性获取关联数据
from django.db.models import Count

users = User.objects.annotate(
    order_count=Count('order')
).all()
# 仅 1 条 SQL，使用 LEFT JOIN + GROUP BY
```

---

### ❌ Java（MyBatis）

```java
// 错误：循环中逐个查询
List<User> users = userMapper.selectAll();
for (User user : users) {
    List<Order> orders = orderMapper.selectByUserId(user.getId()); // N+1！
    user.setOrderCount(orders.size());
}
```

### ✅ Java（MyBatis）修复

```java
// 正确：先批量获取所有用户 ID，一次查询所有订单
List<User> users = userMapper.selectAll();
List<Long> userIds = users.stream().map(User::getId).collect(Collectors.toList());

// 一次 IN 查询获取所有订单
List<Order> allOrders = orderMapper.selectByUserIds(userIds);

// 在内存中按 user_id 分组
Map<Long, List<Order>> orderMap = allOrders.stream()
    .collect(Collectors.groupingBy(Order::getUserId));

users.forEach(user ->
    user.setOrderCount(orderMap.getOrDefault(user.getId(), Collections.emptyList()).size())
);
```

---

### ❌ JavaScript（Sequelize）

```javascript
// 错误：循环中 await 逐个查询
const users = await User.findAll();
for (const user of users) {
  const orders = await Order.findAll({ where: { userId: user.id } }); // N+1！
  user.dataValues.orderCount = orders.length;
}
```

### ✅ JavaScript（Sequelize）修复

```javascript
// 正确：使用 include 预加载关联
const users = await User.findAll({
  attributes: {
    include: [
      [sequelize.fn('COUNT', sequelize.col('Orders.id')), 'orderCount']
    ]
  },
  include: [{
    model: Order,
    attributes: []
  }],
  group: ['User.id'],
  raw: true
});
```

---

### ❌ Go（GORM）

```go
// 错误：循环中逐个查询订单
var users []User
db.Find(&users)
for _, user := range users {
    var orders []Order
    db.Where("user_id = ?", user.ID).Find(&orders) // N+1！
    user.OrderCount = len(orders)
}
```

### ✅ Go（GORM）修复

```go
// 正确：使用 Preload 预加载关联
var users []User
db.Preload("Orders").Find(&users)
for i := range users {
    users[i].OrderCount = len(users[i].Orders)
}

// 或使用 Joins + 聚合查询（更高效）
type UserWithCount struct {
    ID         uint
    Name       string
    OrderCount int
}
var results []UserWithCount
db.Model(&User{}).
    Select("users.id, users.name, COUNT(orders.id) as order_count").
    Joins("LEFT JOIN orders ON orders.user_id = users.id").
    Group("users.id").
    Find(&results)
```

---

### ❌ Rust（sqlx）

```rust
// 错误：循环中逐条查询
let users = sqlx::query_as!(User, "SELECT id, name FROM users")
    .fetch_all(&pool).await?;

for user in &users {
    let orders = sqlx::query_as!(Order,
        "SELECT * FROM orders WHERE user_id = $1", user.id  // N+1！
    ).fetch_all(&pool).await?;
}
```

### ✅ Rust（sqlx）修复

```rust
// 正确：一次 IN 查询 + 内存分组
let users = sqlx::query_as!(User, "SELECT id, name FROM users")
    .fetch_all(&pool).await?;

let user_ids: Vec<i64> = users.iter().map(|u| u.id).collect();

let all_orders = sqlx::query_as!(Order,
    "SELECT * FROM orders WHERE user_id = ANY($1)", &user_ids
).fetch_all(&pool).await?;

let order_map: HashMap<i64, Vec<Order>> = all_orders.into_iter()
    .fold(HashMap::new(), |mut map, order| {
        map.entry(order.user_id).or_default().push(order);
        map
    });
```

---

### ❌ C#（EF Core）

```csharp
// 错误：循环中逐个查询（延迟加载 N+1）
var users = _context.Users.ToList();
foreach (var user in users)
{
    var orderCount = _context.Orders.Count(o => o.UserId == user.Id); // N+1！
    user.OrderCount = orderCount;
}
```

### ✅ C#（EF Core）修复

```csharp
// 正确：使用 Include 预加载 + 投影
var users = _context.Users
    .Include(u => u.Orders)
    .Select(u => new {
        u.Id,
        u.Name,
        OrderCount = u.Orders.Count
    })
    .ToList();
```

### 🔍 检测方法

| 检测方式 | 说明 |
|---------|------|
| SQL 日志分析 | 开启 ORM 的 SQL 日志，查找同一表的重复查询模式 |
| APM 工具 | New Relic / Datadog 会标记 "N+1 query" 警告 |
| 代码审查 | 搜索循环内的 `query` / `find` / `select` / `get` 调用 |
| 单元测试 | 使用计数器 mock，断言 DB 调用次数 ≤ 预期 |
| Go GORM 扫描 | 搜索 `for range` 内的 `db.Where` / `db.Find` / `db.First` |
| Rust sqlx 审查 | 搜索 `for` 循环内的 `query_as!` / `fetch_one` / `fetch_all` |
| EF Core 审查 | 搜索 `foreach` 内的 `_context.` / `.Where(` / `.Count(` |

---

## 反模式 02：同步阻塞 I/O

**定义：** 在高并发接口的主线程中使用同步的文件/网络操作，阻塞整个请求处理线程。

**严重程度：** 🔴 严重 — 单次阻塞可能拖慢所有并发请求

### ❌ Python（Flask）

```python
# 错误：同步读取文件阻塞整个请求
@app.route('/report')
def generate_report():
    data = open('large_data.json').read()  # 同步阻塞！文件 100MB 时阻塞数秒
    report = process(data)
    return jsonify(report)
```

### ✅ Python（FastAPI 异步）

```python
# 正确：使用异步文件 I/O
import aiofiles
from fastapi import FastAPI

@app.get('/report')
async def generate_report():
    async with aiofiles.open('large_data.json', 'r') as f:
        data = await f.read()  # 异步读取，不阻塞事件循环
    report = process(data)
    return report
```

---

### ❌ Java（Spring Boot）

```java
// 错误：在 Web 线程中同步调用外部 API
@GetMapping("/user-info")
public UserInfo getUserInfo(String userId) {
    // 同步 HTTP 调用，阻塞 Tomcat 线程
    String response = restTemplate.getForObject(
        "https://api.example.com/users/" + userId, String.class); // 阻塞！
    return parseUserInfo(response);
}
```

### ✅ Java（Spring WebFlux）

```java
// 正确：使用 WebClient 异步非阻塞
@GetMapping("/user-info")
public Mono<UserInfo> getUserInfo(String userId) {
    return webClient.get()
        .uri("/users/" + userId)
        .retrieve()
        .bodyToMono(String.class)
        .map(this::parseUserInfo);
}
```

---

### ❌ JavaScript（Node.js）

```javascript
// 错误：使用同步 fs 操作
app.get('/data', (req, res) => {
  const data = fs.readFileSync('./data.json', 'utf-8'); // 阻塞事件循环！
  res.json(JSON.parse(data));
});
```

### ✅ JavaScript（Node.js）修复

```javascript
// 正确：使用异步 fs 或 stream
app.get('/data', async (req, res) => {
  const data = await fs.promises.readFile('./data.json', 'utf-8');
  res.json(JSON.parse(data));
});

// 更好的方案：大文件用 stream
app.get('/large-data', (req, res) => {
  const stream = fs.createReadStream('./large-data.json');
  stream.pipe(res);
});
```

---

### ❌ Go（net/http）

```go
// 错误：HTTP handler 中无超时的同步调用
func getUserInfo(w http.ResponseWriter, r *http.Request) {
    resp, err := http.Get("https://api.example.com/users/123") // 无超时！
    if err != nil {
        http.Error(w, err.Error(), 500)
        return
    }
    defer resp.Body.Close()
    body, _ := io.ReadAll(resp.Body) // 可能阻塞数秒
    w.Write(body)
}
```

### ✅ Go 修复

```go
// 正确：使用 context.WithTimeout 控制超时
func getUserInfo(w http.ResponseWriter, r *http.Request) {
    ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
    defer cancel()

    req, _ := http.NewRequestWithContext(ctx, "GET",
        "https://api.example.com/users/123", nil)
    resp, err := http.DefaultClient.Do(req)
    if err != nil {
        http.Error(w, err.Error(), 504)
        return
    }
    defer resp.Body.Close()

    // 流式拷贝，不一次性加载到内存
    w.Header().Set("Content-Type", "application/json")
    io.Copy(w, resp.Body)
}
```

---

### ❌ Rust（标准库）

```rust
// 错误：在 async fn 中使用同步文件读取
async fn generate_report() -> Vec<u8> {
    let data = std::fs::read_to_string("large_data.json") // 阻塞 tokio 线程！
        .unwrap();
    process_data(&data)
}
```

### ✅ Rust 修复

```rust
// 正确：使用 tokio::fs 异步文件操作
async fn generate_report() -> Vec<u8> {
    let data = tokio::fs::read_to_string("large_data.json").await
        .unwrap();
    process_data(&data)
}

// 更好：大文件用流式读取
use tokio::io::AsyncReadExt;
async fn generate_report_stream() -> Vec<u8> {
    let mut file = tokio::fs::File::open("large_data.json").await.unwrap();
    let mut buffer = Vec::with_capacity(8192);
    file.read_to_end(&mut buffer).await.unwrap();
    buffer
}
```

---

### ❌ C#（ASP.NET Core）

```csharp
// 错误：在异步方法中使用 .Result 同步等待
[HttpGet("user-info")]
public UserInfo GetUserInfo(string userId)
{
    var response = httpClient.GetAsync($"https://api.example.com/users/{userId}")
        .Result;  // 死锁风险！阻塞线程池线程
    var json = response.Content.ReadAsStringAsync().Result;
    return JsonSerializer.Deserialize<UserInfo>(json);
}
```

### ✅ C# 修复

```csharp
// 正确：全链路 async/await
[HttpGet("user-info")]
public async Task<UserInfo> GetUserInfo(string userId)
{
    var response = await httpClient.GetAsync(
        $"https://api.example.com/users/{userId}");
    response.EnsureSuccessStatusCode();
    var json = await response.Content.ReadAsStringAsync();
    return JsonSerializer.Deserialize<UserInfo>(json);
}
```

### 🔍 检测方法

| 检测方式 | 说明 |
|---------|------|
| 关键词扫描 | 搜索 `readFileSync` / `writeFileSync` / `restTemplate.get` / `open().read()` |
| 线程池监控 | Tomcat 线程池活跃线程数持续接近上限 |
| APM 链路追踪 | 请求在 I/O 阶段耗时占比异常高 |
| 压力测试 | 并发 100 时响应时间线性增长（而非平稳） |
| Go 扫描 | 搜索无 `context` 的 `http.Get` / `io.ReadAll` |
| Rust 扫描 | 搜索 async fn 中的 `std::fs::` 调用 |
| C# 扫描 | 搜索 `.Result` / `Thread.Sleep` / `.GetAwaiter().GetResult()` |

---

## 反模式 03：内存泄漏风险

**定义：** 在全局变量或未销毁的事件监听器中持续缓存数据，导致内存使用量只增不减。

**严重程度：** 🟡 高 — 线上长期运行后可能触发 OOM

### ❌ Python

```python
# 错误：全局字典持续增长，无清理机制
_cache = {}

def get_user(user_id):
    if user_id not in _cache:
        _cache[user_id] = db.query_user(user_id)  # 永远不会被清理！
    return _cache[user_id]
```

### ✅ Python（使用 LRU 缓存）

```python
from functools import lru_cache

@lru_cache(maxsize=10000)  # 限制缓存大小，LRU 自动淘汰
def get_user(user_id):
    return db.query_user(user_id)
```

---

### ❌ Java

```java
// 错误：静态 Map 无限增长
public class UserCache {
    private static final Map<Long, User> cache = new HashMap<>();

    public static User getUser(Long id) {
        return cache.computeIfAbsent(id, k -> userDao.findById(k)); // 永远增长！
    }
}
```

### ✅ Java（使用 Caffeine 缓存）

```java
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;

public class UserCache {
    private static final Cache<Long, User> cache = Caffeine.newBuilder()
        .maximumSize(10000)           // 限制最大条目数
        .expireAfterWrite(5, TimeUnit.MINUTES)  // 5 分钟过期
        .build();

    public static User getUser(Long id) {
        return cache.get(id, k -> userDao.findById(k));
    }
}
```

---

### ❌ JavaScript（Node.js）

```javascript
// 错误：事件监听器未移除，闭包持有引用
class EventBus {
  constructor() {
    this.listeners = {};
  }

  on(event, callback) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(callback); // 只增不减！
  }
  // 缺少 off() 方法！
}
```

### ✅ JavaScript 修复

```javascript
class EventBus {
  constructor() {
    this.listeners = new Map();
  }

  on(event, callback) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event).add(callback);
    // 返回取消订阅函数
    return () => this.listeners.get(event)?.delete(callback);
  }

  off(event, callback) {
    this.listeners.get(event)?.delete(callback);
  }

  // 防御：限制单事件最大监听数
  on(event, callback, maxListeners = 100) {
    const set = this.listeners.get(event);
    if (set && set.size >= maxListeners) {
      console.warn(`Event "${event}" has ${set.size} listeners, possible leak`);
    }
    // ...
  }
}
```

---

### ❌ Go

```go
// 错误：sync.Map 只存不删
var userCache sync.Map

func getUser(id int64) *User {
    if val, ok := userCache.Load(id); ok {
        return val.(*User)
    }
    user := db.QueryUser(id)
    userCache.Store(id, user) // 永远不会被清理！
    return user
}
```

### ✅ Go 修复

```go
import "github.com/patrickmn/go-cache"

// 正确：使用 go-cache 带 TTL 自动过期
var userCache = cache.New(5*time.Minute, 10*time.Minute)

func getUser(id int64) *User {
    if val, found := userCache.Get(fmt.Sprintf("user:%d", id)); found {
        return val.(*User)
    }
    user := db.QueryUser(id)
    userCache.Set(fmt.Sprintf("user:%d", id), user, cache.DefaultExpiration)
    return user
}
```

---

### ❌ Rust

```rust
// 错误：Arc<HashMap> 只写不清理
use std::sync::Arc;
use std::collections::HashMap;
use parking_lot::Mutex;

lazy_static! {
    static ref CACHE: Arc<Mutex<HashMap<u64, User>>> = Arc::new(Mutex::new(HashMap::new()));
}

fn get_user(id: u64) -> User {
    let cache = CACHE.lock();
    if let Some(user) = cache.get(&id) {
        return user.clone();
    }
    drop(cache);
    let user = db_query_user(id);
    CACHE.lock().insert(id, user.clone()); // 永远增长！
    user
}
```

### ✅ Rust 修复

```rust
use moka::sync::Cache;

// 正确：使用 moka 缓存，自动过期 + 容量限制
static CACHE: once_cell::sync::Lazy<Cache<u64, User>> = once_cell::sync::Lazy::new(|| {
    Cache::builder()
        .max_capacity(10_000)
        .time_to_live(std::time::Duration::from_secs(300)) // 5 分钟 TTL
        .build()
});

fn get_user(id: u64) -> User {
    CACHE.get_with(id, || db_query_user(id))
}
```

---

### ❌ C#

```csharp
// 错误：静态字典只加不删
public class UserCache
{
    private static readonly ConcurrentDictionary<long, User> _cache = new();

    public static User GetUser(long id)
    {
        return _cache.GetOrAdd(id, _ => UserRepository.FindById(id)); // 永远增长！
    }
}
```

### ✅ C# 修复

```csharp
using Microsoft.Extensions.Caching.Memory;

// 正确：使用 IMemoryCache（依赖注入，带过期策略）
public class UserCache
{
    private readonly IMemoryCache _cache;

    public UserCache(IMemoryCache cache) => _cache = cache;

    public User GetUser(long id)
    {
        return _cache.GetOrCreate(id, entry =>
        {
            entry.AbsoluteExpirationRelativeToNow = TimeSpan.FromMinutes(5);
            entry.Size = 1;
            return UserRepository.FindById(id);
        });
    }
}

// 注册时设置大小限制
builder.Services.AddMemoryCache(options =>
{
    options.SizeLimit = 10000;
});
```

### 🔍 检测方法

| 检测方式 | 说明 |
|---------|------|
| 堆内存监控 | RSS / Heap Used 持续上升且 GC 后不回落 |
| 关键词扫描 | 搜索全局 `Map` / `HashMap` / `Object` 且无 `delete` / `remove` / `maxSize` |
| Node.js | `process.memoryUsage()` 定期打点 + `--max-old-space-size` 告警 |
| Java | VisualVM / MAT 分析堆转储，查找大对象和 GC Root 引用链 |
| Go | `pprof` 堆分析：`go tool pprof http://localhost:6060/debug/pprof/heap` |
| Rust | `valgrind` / `heaptrack` 检测内存增长，或监控进程 RSS |
| C# | `dotnet-counters monitor` / dotMemory 分析堆增长 |

---

## 反模式 04：无上限数据拉取

**定义：** 列表查询和分页接口缺少 limit 限制，数据量增长后可能导致内存溢出或响应超时。

**严重程度：** 🟡 高 — 默认必须包含 limit，最大值不超过 100

### ❌ Python（SQLAlchemy）

```python
# 错误：无 limit，拉取全表
users = session.query(User).all()  # 如果有 100 万用户？全量加载到内存！
```

### ✅ Python 修复

```python
# 正确：强制分页 + limit
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

def get_users(page=1, page_size=DEFAULT_PAGE_SIZE):
    page_size = min(page_size, MAX_PAGE_SIZE)  # 强制上限
    offset = (page - 1) * page_size
    return session.query(User).offset(offset).limit(page_size).all()
```

---

### ❌ Java（JPA）

```java
// 错误：无分页
List<User> users = userRepository.findAll(); // 全表加载！
```

### ✅ Java 修复

```java
// 正确：使用 Pageable 分页
Page<User> getUsers(int page, int size) {
    size = Math.min(size, 100);  // 强制上限
    return userRepository.findAll(PageRequest.of(page, size));
}
```

---

### ❌ JavaScript（Mongoose）

```javascript
// 错误：无 limit
const users = await User.find({}); // 全量！
```

### ✅ JavaScript 修复

```javascript
const MAX_LIMIT = 100;

async function getUsers(page = 1, limit = 20) {
  limit = Math.min(limit, MAX_LIMIT);  // 强制上限
  const skip = (page - 1) * limit;
  return User.find({}).skip(skip).limit(limit).lean();
}
```

---

### ❌ Go（GORM）

```go
// 错误：无 limit，全量查询
var users []User
db.Find(&users) // 如果有 100 万用户？全量加载！
```

### ✅ Go 修复

```go
const (
    DefaultPageSize = 20
    MaxPageSize     = 100
)

func GetUsers(page, pageSize int) ([]User, int64) {
    if pageSize <= 0 {
        pageSize = DefaultPageSize
    }
    if pageSize > MaxPageSize {
        pageSize = MaxPageSize // 强制上限
    }
    offset := (page - 1) * pageSize

    var users []User
    var total int64
    db.Model(&User{}).Count(&total)
    db.Offset(offset).Limit(pageSize).Find(&users)
    return users, total
}
```

---

### ❌ Rust（sqlx）

```rust
// 错误：无 LIMIT 的全量查询
let users = sqlx::query_as!(User, "SELECT * FROM users")
    .fetch_all(&pool).await?; // 全量加载！
```

### ✅ Rust 修复

```rust
const DEFAULT_PAGE_SIZE: i64 = 20;
const MAX_PAGE_SIZE: i64 = 100;

async fn get_users(
    pool: &PgPool,
    page: i64,
    page_size: i64,
) -> Result<Vec<User>, sqlx::Error> {
    let page_size = page_size.clamp(1, MAX_PAGE_SIZE);
    let offset = (page - 1) * page_size;

    sqlx::query_as!(
        User,
        "SELECT * FROM users ORDER BY id LIMIT $1 OFFSET $2",
        page_size, offset
    )
    .fetch_all(pool)
    .await
}
```

---

### ❌ C#（EF Core）

```csharp
// 错误：无分页，全表加载
var users = _context.Users.ToList(); // 全量！
```

### ✅ C# 修复

```csharp
const int DefaultPageSize = 20;
const int MaxPageSize = 100;

public async Task<(List<User> Users, int Total)> GetUsers(int page = 1, int pageSize = DefaultPageSize)
{
    pageSize = Math.Min(pageSize, MaxPageSize); // 强制上限

    var total = await _context.Users.CountAsync();
    var users = await _context.Users
        .OrderBy(u => u.Id)
        .Skip((page - 1) * pageSize)
        .Take(pageSize)
        .AsNoTracking() // 只读场景，提升性能
        .ToListAsync();

    return (users, total);
}
```

### 🔍 检测方法

| 检测方式 | 说明 |
|---------|------|
| SQL 日志 | 查找 `SELECT` 语句不带 `LIMIT` 的情况 |
| ORM 审计 | 搜索 `.all()` / `findAll()` / `find({})` 无 `.limit()` / `.take()` |
| API 测试 | 不传分页参数时，检查返回数据量是否有上限 |
| 内存监控 | 接口调用后 Heap 使用量突增 |
| Go GORM | 搜索 `db.Find(` 无 `.Limit(` 的模式 |
| Rust sqlx | 搜索 `fetch_all` 对应的 SQL 无 `LIMIT` 子句 |
| EF Core | 搜索 `.ToList()` / `.ToListAsync()` 无 `.Take()` 的模式 |

---

## 反模式严重程度速查

| 反模式 | Python | Java | JavaScript | Go | Rust | C# | 1000条时影响 | 100万条时影响 |
|-------|--------|------|-----------|-----|------|-----|------------|-------------|
| N+1 查询 | Django ORM N+1 | MyBatis 循环查询 | Sequelize N+1 | GORM 循环 db.Where | sqlx 循环 fetch | EF Core 延迟加载 | ~10s 响应 | 连接池耗尽 |
| 同步阻塞 I/O | Flask sync read | RestTemplate 阻塞 | readFileSync | http.Get 无超时 | std::fs 在 async fn | Task.Result 死锁 | 请求排队 | 服务不可用 |
| 内存泄漏 | 全局 dict | static HashMap | 全局 Map | sync.Map 不删 | Arc\<HashMap\> | static ConcurrentDict | 内存缓增 | OOM 崩溃 |
| 无上限拉取 | .all() 无 limit | findAll() 无分页 | find({}) 无 limit | db.Find() 无 Limit | fetch_all() 无 LIMIT | ToList() 无 Take | 响应变慢 | 内存溢出 |
