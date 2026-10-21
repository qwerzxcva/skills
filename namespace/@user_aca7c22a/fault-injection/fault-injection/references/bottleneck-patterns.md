# 主流开发语言瓶颈注入模式参考

> 本文档提供 9 种瓶颈类型在 9 种主流语言中的具体实现代码。
> 所有注入点均使用条件开关（环境变量/配置），默认**不启用**，需显式开启。

---

## 注入点开关规范

```python
# Python
import os
FAULT_ENABLED = os.getenv("FAULT_INJECT_ENABLED", "false").lower() == "true"

# JavaScript/TypeScript
const FAULT_ENABLED = process.env.FAULT_INJECT_ENABLED === "true";

# Java
boolean faultEnabled = "true".equals(System.getenv("FAULT_INJECT_ENABLED"));

# Go
faultEnabled := os.Getenv("FAULT_INJECT_ENABLED") == "true"

# Rust
let fault_enabled = std::env::var("FAULT_INJECT_ENABLED").unwrap_or_default() == "true";

# C#
var faultEnabled = Environment.GetEnvironmentVariable("FAULT_INJECT_ENABLED") == "true";

# Ruby
FAULT_ENABLED = ENV['FAULT_INJECT_ENABLED'] == 'true'

# PHP
$faultEnabled = getenv('FAULT_INJECT_ENABLED') === 'true';

# Kotlin
val faultEnabled = System.getenv("FAULT_INJECT_ENABLED") == "true"
```

---

## 1. CPU 瓶颈 (CPU Bottleneck)

### Python
```python
import time
import os

def cpu_intensive_task():
    if os.getenv("FAULT_CPU", "false") == "true":
        # 模拟高 CPU 负载
        end_time = time.time() + float(os.getenv("FAULT_CPU_DURATION", "5"))
        result = 0
        while time.time() < end_time:
            result += sum(i * i for i in range(10000))
    # 正常业务逻辑
    return "done"
```

### JavaScript / TypeScript
```typescript
function cpuIntensiveTask() {
  if (process.env.FAULT_CPU === "true") {
    const duration = parseInt(process.env.FAULT_CPU_DURATION || "5000");
    const endTime = Date.now() + duration;
    let result = 0;
    while (Date.now() < endTime) {
      for (let i = 0; i < 10000; i++) result += i * i;
    }
  }
  return "done";
}
```

### Java
```java
public class CpuBottleneck {
    public static void cpuIntensive() {
        if ("true".equals(System.getenv("FAULT_CPU"))) {
            long duration = Long.parseLong(System.getenv("FAULT_CPU_DURATION") != null ? System.getenv("FAULT_CPU_DURATION") : "5000");
            long endTime = System.currentTimeMillis() + duration;
            long result = 0;
            while (System.currentTimeMillis() < endTime) {
                for (int i = 0; i < 10000; i++) result += (long) i * i;
            }
        }
    }
}
```

### Go
```go
import (
    "os"
    "time"
    "math"
)

func cpuIntensive() {
    if os.Getenv("FAULT_CPU") == "true" {
        duration := 5 * time.Second
        if d := os.Getenv("FAULT_CPU_DURATION"); d != "" {
            if parsed, err := time.ParseDuration(d); err == nil {
                duration = parsed
            }
        }
        endTime := time.Now().Add(duration)
        var result float64
        for time.Now().Before(endTime) {
            for i := 0; i < 10000; i++ {
                result += math.Pow(float64(i), 2)
            }
        }
    }
}
```

### Rust
```rust
use std::time::{Duration, Instant};

fn cpu_intensive() {
    if std::env::var("FAULT_CPU").unwrap_or_default() == "true" {
        let duration_secs: u64 = std::env::var("FAULT_CPU_DURATION")
            .unwrap_or_else(|_| "5".to_string())
            .parse().unwrap_or(5);
        let end_time = Instant::now() + Duration::from_secs(duration_secs);
        let mut result: f64 = 0.0;
        while Instant::now() < end_time {
            for i in 0..10000_i32 {
                result += (i * i) as f64;
            }
        }
    }
}
```

### C#
```csharp
public static void CpuIntensive() {
    if (Environment.GetEnvironmentVariable("FAULT_CPU") == "true") {
        int durationMs = 5000;
        var durationStr = Environment.GetEnvironmentVariable("FAULT_CPU_DURATION");
        if (!string.IsNullOrEmpty(durationStr)) int.TryParse(durationStr, out durationMs);
        var endTime = DateTime.UtcNow.AddMilliseconds(durationMs);
        long result = 0;
        while (DateTime.UtcNow < endTime) {
            for (int i = 0; i < 10000; i++) result += (long)i * i;
        }
    }
}
```

### Ruby
```ruby
require 'time'

def cpu_intensive
  if ENV['FAULT_CPU'] == 'true'
    duration = (ENV['FAULT_CPU_DURATION'] || '5').to_i
    end_time = Time.now + duration
    result = 0
    while Time.now < end_time
      10000.times { |i| result += i * i }
    end
  end
end
```

### PHP
```php
function cpuIntensive() {
    if (getenv('FAULT_CPU') === 'true') {
        $duration = (int)(getenv('FAULT_CPU_DURATION') ?: 5);
        $endTime = microtime(true) + $duration;
        $result = 0;
        while (microtime(true) < $endTime) {
            for ($i = 0; $i < 10000; $i++) {
                $result += $i * $i;
            }
        }
    }
}
```

### Kotlin
```kotlin
fun cpuIntensive() {
    if (System.getenv("FAULT_CPU") == "true") {
        val durationMs = (System.getenv("FAULT_CPU_DURATION") ?: "5000").toLong()
        val endTime = System.currentTimeMillis() + durationMs
        var result = 0L
        while (System.currentTimeMillis() < endTime) {
            for (i in 0 until 10000) {
                result += (i * i).toLong()
            }
        }
    }
}
```

---

## 2. 内存泄漏 (Memory Leak)

### Python
```python
import os
import gc

_leak_cache = []  # 泄漏容器，外部不可见

def memory_leak_trigger():
    """每次调用向 _leak_cache 添加 10MB 数据，不释放"""
    if os.getenv("FAULT_MEM_LEAK", "false") == "true":
        data = bytearray(10 * 1024 * 1024)  # 10MB
        _leak_cache.append(data)
    # 正常逻辑...
    return True

def memory_leak_reset():
    """显式清理，配合测试重置"""
    global _leak_cache
    _leak_cache.clear()
    gc.collect()
```

### JavaScript / TypeScript
```typescript
const _leakCache: any[] = [];

function memoryLeakTrigger() {
  if (process.env.FAULT_MEM_LEAK === "true") {
    // 分配 10MB 并永久持有引用
    const buffer = Buffer.alloc(10 * 1024 * 1024);
    _leakCache.push(buffer);
  }
  return true;
}

function memoryLeakReset() {
  _leakCache.length = 0;
}
```

### Java
```java
import java.util.*;
import java.nio.ByteBuffer;

public class MemoryLeakBottleneck {
    private static final List<ByteBuffer> leakCache = new ArrayList<>();

    public static void triggerLeak() {
        if ("true".equals(System.getenv("FAULT_MEM_LEAK"))) {
            ByteBuffer buffer = ByteBuffer.allocateDirect(10 * 1024 * 1024);
            leakCache.add(buffer);
        }
    }

    public static void resetLeak() {
        leakCache.clear();
    }
}
```

### Go
```go
var leakCache [][]byte

func MemoryLeakTrigger() {
    if os.Getenv("FAULT_MEM_LEAK") == "true" {
        data := make([]byte, 10*1024*1024) // 10MB
        leakCache = append(leakCache, data)
    }
}

func MemoryLeakReset() {
    leakCache = nil
    leakCache = [][]byte{}
}
```

### Rust
```rust
use std::collections::VecDeque;

static mut LEAK_CACHE: VecDeque<Vec<u8>> = VecDeque::new();

fn memory_leak_trigger() {
    if std::env::var("FAULT_MEM_LEAK").unwrap_or_default() == "true" {
        // 注意：unsafe 仅用于演示，生产环境勿用
        let data = vec![0u8; 10 * 1024 * 1024]; // 10MB
        unsafe { LEAK_CACHE.push_back(data); }
    }
}
```

### C#
```csharp
using System.Collections.Generic;

public static class MemoryLeakBottleneck {
    private static readonly List<byte[]> _leakCache = new List<byte[]>();

    public static void TriggerLeak() {
        if (Environment.GetEnvironmentVariable("FAULT_MEM_LEAK") == "true") {
            var buffer = new byte[10 * 1024 * 1024]; // 10MB
            _leakCache.Add(buffer);
        }
    }

    public static void ResetLeak() {
        _leakCache.Clear();
    }
}
```

### Ruby
```ruby
@leak_cache = []

def memory_leak_trigger
  if ENV['FAULT_MEM_LEAK'] == 'true'
    # 分配 10MB 并永久持有引用
    data = "\x00" * (10 * 1024 * 1024)
    @leak_cache << data
  end
end

def memory_leak_reset
  @leak_cache.clear
end
```

### PHP
```php
$_GLOBALS['_fault_leak_cache'] = [];

function memoryLeakTrigger() {
    if (getenv('FAULT_MEM_LEAK') === 'true') {
        $data = str_repeat("\x00", 10 * 1024 * 1024); // 10MB
        $_GLOBALS['_fault_leak_cache'][] = $data;
    }
}

function memoryLeakReset() {
    $_GLOBALS['_fault_leak_cache'] = [];
}
```

### Kotlin
```kotlin
object MemoryLeakBottleneck {
    private val leakCache = mutableListOf<ByteArray>()

    fun triggerLeak() {
        if (System.getenv("FAULT_MEM_LEAK") == "true") {
            val buffer = ByteArray(10 * 1024 * 1024) // 10MB
            leakCache.add(buffer)
        }
    }

    fun resetLeak() {
        leakCache.clear()
    }
}
```

---

## 3. IO 阻塞 (IO Blocking)

### Python
```python
import os
import time
import requests

def blocking_io_call(url):
    if os.getenv("FAULT_IO_BLOCK", "false") == "true":
        delay = int(os.getenv("FAULT_IO_DELAY_MS", "3000"))
        time.sleep(delay / 1000)
    response = requests.get(url, timeout=10)
    return response.json()
```

### JavaScript / TypeScript
```typescript
import https from "https";

async function blockingIoCall(url: string) {
  if (process.env.FAULT_IO_BLOCK === "true") {
    const delay = parseInt(process.env.FAULT_IO_DELAY_MS || "3000");
    await new Promise(resolve => setTimeout(resolve, delay));
  }
  // 同步阻塞的 fetch（Node < 18）
  const res = await fetch(url);
  return res.json();
}
```

### Java
```java
import java.net.HttpURLConnection;
import java.net.URL;

public static String blockingIoCall(String urlStr) throws Exception {
    if ("true".equals(System.getenv("FAULT_IO_BLOCK"))) {
        int delay = Integer.parseInt(
            System.getenv("FAULT_IO_DELAY_MS") != null ? System.getenv("FAULT_IO_DELAY_MS") : "3000"
        );
        Thread.sleep(delay);
    }
    URL url = new URL(urlStr);
    HttpURLConnection conn = (HttpURLConnection) url.openConnection();
    conn.setRequestMethod("GET");
    // 读响应...
    return "response";
}
```

### Go
```go
import (
    "net/http"
    "os"
    "strconv"
    "time"
)

func BlockingIoCall(url string) (*http.Response, error) {
    if os.Getenv("FAULT_IO_BLOCK") == "true" {
        delay := 3000
        if d := os.Getenv("FAULT_IO_DELAY_MS"); d != "" {
            if parsed, err := strconv.Atoi(d); err == nil {
                delay = parsed
            }
        }
        time.Sleep(time.Duration(delay) * time.Millisecond)
    }
    return http.Get(url)
}
```

### Rust
```rust
use std::time::Duration;
use std::env;

fn blocking_io_call(url: &str) {
    if env::var("FAULT_IO_BLOCK").unwrap_or_default() == "true" {
        let delay_ms: u64 = env::var("FAULT_IO_DELAY_MS")
            .unwrap_or_else(|_| "3000".to_string())
            .parse().unwrap_or(3000);
        std::thread::sleep(Duration::from_millis(delay_ms));
    }
    // 实际 IO 操作...
}
```

### C#
```csharp
public static async Task<string> BlockingIoCall(string url) {
    if (Environment.GetEnvironmentVariable("FAULT_IO_BLOCK") == "true") {
        int delayMs = int.Parse(
            Environment.GetEnvironmentVariable("FAULT_IO_DELAY_MS") ?? "3000"
        );
        await Task.Delay(delayMs);
    }
    using var client = new HttpClient();
    return await client.GetStringAsync(url);
}
```

### Ruby
```ruby
require 'net/http'
require 'uri'
require 'time'

def blocking_io_call(url)
  if ENV['FAULT_IO_BLOCK'] == 'true'
    delay_ms = (ENV['FAULT_IO_DELAY_MS'] || '3000').to_i
    sleep(delay_ms / 1000.0)
  end
  URI.parse(url).open.read
end
```

### PHP
```php
function blockingIoCall(string $url): string {
    if (getenv('FAULT_IO_BLOCK') === 'true') {
        $delayMs = (int)(getenv('FAULT_IO_DELAY_MS') ?: 3000);
        usleep($delayMs * 1000); // 微秒
    }
    return file_get_contents($url);
}
```

### Kotlin
```kotlin
import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.delay

suspend fun blockingIoCall(urlStr: String): String {
    if (System.getenv("FAULT_IO_BLOCK") == "true") {
        val delayMs = (System.getenv("FAULT_IO_DELAY_MS") ?: "3000").toLong()
        delay(delayMs)
    }
    val url = URL(urlStr)
    val conn = url.openConnection() as HttpURLConnection
    conn.requestMethod = "GET"
    return conn.inputStream.bufferedReader().readText()
}
```

---

## 4. 网络延迟 (Network Latency)

### Python
```python
import os
import time

class NetworkLatencyMiddleware:
    def process_request(self, req, env):
        if os.getenv("FAULT_NET_LATENCY", "false") == "true":
            latency = int(os.getenv("FAULT_NET_LATENCY_MS", "500"))
            time.sleep(latency / 1000)
        return req
```

### JavaScript / TypeScript
```typescript
// Express 中间件示例
function networkLatencyMiddleware(req: any, res: any, next: any) {
  if (process.env.FAULT_NET_LATENCY === "true") {
    const latency = parseInt(process.env.FAULT_NET_LATENCY_MS || "500");
    setTimeout(next, latency);
  } else {
    next();
  }
}
```

### Java
```java
public class NetworkLatencyFilter implements Filter {
    @Override
    public void doFilter(ServletRequest req, ServletResponse res, FilterChain chain)
            throws IOException, ServletException {
        if ("true".equals(System.getenv("FAULT_NET_LATENCY"))) {
            int latency = Integer.parseInt(
                System.getenv("FAULT_NET_LATENCY_MS") != null ? System.getenv("FAULT_NET_LATENCY_MS") : "500"
            );
            Thread.sleep(latency);
        }
        chain.doFilter(req, res);
    }
}
```

### Go
```go
import (
    "net/http"
    "os"
    "strconv"
    "time"
)

func NetworkLatencyMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if os.Getenv("FAULT_NET_LATENCY") == "true" {
            latencyMs, _ := strconv.Atoi(os.Getenv("FAULT_NET_LATENCY_MS"))
            if latencyMs == 0 {
                latencyMs = 500
            }
            time.Sleep(time.Duration(latencyMs) * time.Millisecond)
        }
        next.ServeHTTP(w, r)
    })
}
```

### Rust (Actix-web)
```rust
use actix_web::{dev::ServiceRequest, Error};
use std::env;

async fn network_latency_middleware(req: ServiceRequest) -> Result<(), Error> {
    if env::var("FAULT_NET_LATENCY").unwrap_or_default() == "true" {
        let latency_ms: u64 = env::var("FAULT_NET_LATENCY_MS")
            .unwrap_or_else(|_| "500".to_string())
            .parse().unwrap_or(500);
        tokio::time::sleep(std::time::Duration::from_millis(latency_ms)).await;
    }
    Ok(())
}
```

### C# (.NET Middleware)
```csharp
public class NetworkLatencyMiddleware {
    private readonly RequestDelegate _next;
    public NetworkLatencyMiddleware(RequestDelegate next) => _next = next;

    public async Task InvokeAsync(HttpContext context) {
        if (Environment.GetEnvironmentVariable("FAULT_NET_LATENCY") == "true") {
            int latencyMs = int.Parse(
                Environment.GetEnvironmentVariable("FAULT_NET_LATENCY_MS") ?? "500"
            );
            await Task.Delay(latencyMs);
        }
        await _next(context);
    }
}
```

### Ruby (Rack Middleware)
```ruby
class NetworkLatencyMiddleware
  def initialize(app)
    @app = app
  end

  def call(env)
    if ENV['FAULT_NET_LATENCY'] == 'true'
      latency_ms = (ENV['FAULT_NET_LATENCY_MS'] || '500').to_i
      sleep(latency_ms / 1000.0)
    end
    @app.call(env)
  end
end
```

### PHP
```php
// 简单演示，实际建议在 Web Server 层面 (Nginx) 处理
function networkLatencyMiddleware() {
    if (getenv('FAULT_NET_LATENCY') === 'true') {
        $latencyMs = (int)(getenv('FAULT_NET_LATENCY_MS') ?: 500);
        usleep($latencyMs * 1000);
    }
}
```

### Kotlin (Ktor)
```kotlin
import io.ktor.server.plugins.*
import io.ktor.server.request.*
import kotlinx.coroutines.delay

class NetworkLatencyPlugin(config: Configuration) {
    class Configuration { var latencyMs: Long = 500 }

    suspend fun intercept(call: ApplicationCall) {
        if (System.getenv("FAULT_NET_LATENCY") == "true") {
            delay(config.latencyMs)
        }
    }
}
```

---

## 5. 并发争用 (Concurrency Contention)

### Python
```python
import os
import threading
import time

_lock = threading.Lock()
_lock_held_duration = float(os.getenv("FAULT_LOCK_HOLD_MS", "100")) / 1000

def critical_section():
    if os.getenv("FAULT_CONCURRENCY", "false") == "true":
        with _lock:
            time.sleep(_lock_held_duration)  # 持有锁 100ms 阻塞其他线程
    return "result"
```

### JavaScript / TypeScript
```typescript
import { Mutex } from "async-mutex";

const mutex = new Mutex();
const lockHoldMs = parseInt(process.env.FAULT_LOCK_HOLD_MS || "100");

async function criticalSection() {
  if (process.env.FAULT_CONCURRENCY === "true") {
    const release = await mutex.acquire();
    await new Promise(resolve => setTimeout(resolve, lockHoldMs));
    release();
  }
  return "result";
}
```

### Java
```java
import java.util.concurrent.locks.*;
import java.time.Duration;

public class ConcurrencyBottleneck {
    private static final ReentrantLock lock = new ReentrantLock();

    public static void criticalSection() {
        if ("true".equals(System.getenv("FAULT_CONCURRENCY"))) {
            long holdMs = Long.parseLong(
                System.getenv("FAULT_LOCK_HOLD_MS") != null ? System.getenv("FAULT_LOCK_HOLD_MS") : "100"
            );
            lock.lock();
            try {
                Thread.sleep(holdMs);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            } finally {
                lock.unlock();
            }
        }
    }
}
```

### Go
```go
import (
    "os"
    "sync"
    "time"
)

var mu sync.Mutex

func CriticalSection() {
    if os.Getenv("FAULT_CONCURRENCY") == "true" {
        mu.Lock()
        holdMs := 100
        if h := os.Getenv("FAULT_LOCK_HOLD_MS"); h != "" {
            if parsed, err := time.ParseDuration(h + "ms"); err == nil {
                holdMs = int(parsed.Milliseconds())
            }
        }
        time.Sleep(time.Duration(holdMs) * time.Millisecond)
        mu.Unlock()
    }
}
```

### Rust
```rust
use std::sync::{Mutex, Arc};
use std::env;

lazy_static::lazy_static! {
    static ref MU: Mutex<()> = Mutex::new(());
}

fn critical_section() {
    if env::var("FAULT_CONCURRENCY").unwrap_or_default() == "true" {
        let hold_ms: u64 = env::var("FAULT_LOCK_HOLD_MS")
            .unwrap_or_else(|_| "100".to_string())
            .parse().unwrap_or(100);
        let _guard = MU.lock().unwrap();
        std::thread::sleep(std::time::Duration::from_millis(hold_ms));
    }
}
```

### C#
```csharp
using System.Threading;

public static class ConcurrencyBottleneck {
    private static readonly object _lock = new object();

    public static void CriticalSection() {
        if (Environment.GetEnvironmentVariable("FAULT_CONCURRENCY") == "true") {
            int holdMs = int.Parse(
                Environment.GetEnvironmentVariable("FAULT_LOCK_HOLD_MS") ?? "100"
            );
            lock (_lock) {
                Thread.Sleep(holdMs);
            }
        }
    }
}
```

### Ruby
```ruby
require 'thread'

@mutex = Mutex.new
LOCK_HOLD_MS = (ENV['FAULT_LOCK_HOLD_MS'] || '100').to_i

def critical_section
  if ENV['FAULT_CONCURRENCY'] == 'true'
    @mutex.synchronize do
      sleep(LOCK_HOLD_MS / 1000.0)
    end
  end
  'result'
end
```

### PHP
```php
$_GLOBALS['_fault_mutex'] = true;

function criticalSection(): string {
    if (getenv('FAULT_CONCURRENCY') === 'true') {
        $holdMs = (int)(getenv('FAULT_LOCK_HOLD_MS') ?: 100);
        usleep($holdMs * 1000);
        // PHP 原生不支持锁，用 flock 模拟争用
        $fp = fopen('/tmp/fault_lock', 'w');
        if (flock($fp, LOCK_EX)) {
            usleep($holdMs * 1000);
            flock($fp, LOCK_UN);
        }
        fclose($fp);
    }
    return 'result';
}
```

### Kotlin
```kotlin
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.thread

object ConcurrencyBottleneck {
    private val lock = ReentrantLock()

    fun criticalSection() {
        if (System.getenv("FAULT_CONCURRENCY") == "true") {
            val holdMs = (System.getenv("FAULT_LOCK_HOLD_MS") ?: "100").toLong()
            lock.lock()
            try {
                Thread.sleep(holdMs)
            } finally {
                lock.unlock()
            }
        }
    }
}
```

---

## 6. 数据库瓶颈 (Database Bottleneck)

### Python
```python
import os

def db_query_no_index():
    """无索引查询瓶颈"""
    if os.getenv("FAULT_DB_NO_INDEX", "false") == "true":
        # 模拟大表全表扫描
        return "SELECT * FROM orders WHERE date > '2020-01-01'"  # 缺索引
    return "SELECT id FROM orders WHERE id = 1"  # 有索引

def db_n_plus_one():
    """N+1 查询瓶颈"""
    if os.getenv("FAULT_DB_N_PLUS_ONE", "false") == "true":
        return "开启"  # 代码层面表现为循环内查询
    return "关闭"
```

### JavaScript / TypeScript
```typescript
// ORM 层注入 N+1
async function fetchOrdersWithUsers() {
  if (process.env.FAULT_DB_N_PLUS_ONE === "true") {
    // 每次循环查一次数据库，触发 N+1
    const orders = await db.query("SELECT * FROM orders");
    for (const order of orders) {
      order.user = await db.query(`SELECT * FROM users WHERE id = ${order.userId}`);
    }
    return orders;
  }
  // 正常：JOIN 查询
  return db.query("SELECT o.*, u.* FROM orders o JOIN users u ON o.user_id = u.id");
}
```

### Java (MyBatis/Spring)
```java
// 无索引查询注入
public class DbBottleneckMapper {

    // FAULT_DB_NO_INDEX=true 时，此查询会命中无索引字段
    @Select("SELECT * FROM orders WHERE status = #{status} AND created_at > #{since}")
    List<Order> findOrdersWithoutIndex(@Param("status") String status, @Param("since") Date since);
}
```

### Go
```go
// N+1 查询瓶颈
func FetchOrdersWithUsers(db *sql.DB, enableFault bool) ([]Order, error) {
    rows, err := db.Query("SELECT id, user_id FROM orders")
    if err != nil {
        return nil, err
    }
    defer rows.Close()

    var orders []Order
    for rows.Next() {
        var o Order
        if err := rows.Scan(&o.ID, &o.UserID); err != nil {
            return nil, err
        }
        if enableFault || os.Getenv("FAULT_DB_N_PLUS_ONE") == "true" {
            // N+1: 每条订单单独查用户
            db.QueryRow("SELECT * FROM users WHERE id = ?", o.UserID).Scan(&o.User)
        } else {
            // 正常：JOIN
        }
        orders = append(orders, o)
    }
    return orders, nil
}
```

### C#
```csharp
// Entity Framework N+1
public class DbBottleneckRepository {
    private readonly AppDbContext _ctx;

    public async Task<List<Order>> GetOrdersWithUsers(bool faultNPlusOne) {
        var orders = await _ctx.Orders.ToListAsync(); // 触发 N+1 如果启用
        if (faultNPlusOne || Environment.GetEnvironmentVariable("FAULT_DB_N_PLUS_ONE") == "true") {
            foreach (var order in orders) {
                _ctx.Entry(order).Reference(o => o.User).LoadAsync(); // 每条1次查询
            }
        }
        return orders;
    }
}
```

### PHP (Laravel Eloquent)
```php
// N+1 瓶颈
function fetchOrdersWithUsers($enableFault = false) {
    $orders = Order::all(); // SELECT * FROM orders

    if ($enableFault || getenv('FAULT_DB_N_PLUS_ONE') === 'true') {
        foreach ($orders as $order) {
            $order->user; // 触发 N+1: SELECT * FROM users WHERE id = ?
        }
    }

    return $orders;
}
```

### Kotlin (Spring JPA)
```kotlin
// N+1 瓶颈
fun getOrdersWithUsers(faultEnabled: Boolean): List<Order> {
    val orders = orderRepository.findAll()
    if (faultEnabled || System.getenv("FAULT_DB_N_PLUS_ONE") == "true") {
        return orders.map { order ->
            order.user // 触发懒加载 N+1
        }
    }
    // 正常：JOIN FETCH
    return orderRepository.findAllWithUsers()
}
```

---

## 7. 限流与熔断 (Rate Limiting & Circuit Breaker)

### Python
```python
import os
import time
from functools import wraps

_rate_limit_window = {}
RATE_LIMIT = int(os.getenv("FAULT_RATE_LIMIT", "10"))  # 每秒 10 次

def rate_limit():
    if os.getenv("FAULT_RATELIMIT", "false") != "true":
        return
    key = id(time)  # 简化示例
    now = time.time()
    _rate_limit_window[key] = _rate_limit_window.get(key, [])
    _rate_limit_window[key] = [t for t in _rate_limit_window[key] if now - t < 1]
    if len(_rate_limit_window[key]) >= RATE_LIMIT:
        raise Exception(f"[Fault] Rate limit exceeded: {RATE_LIMIT}/s")
    _rate_limit_window[key].append(now)
```

### JavaScript / TypeScript
```typescript
// 简单固定窗口限流
const rateLimitMap = new Map<string, number[]>();
const RATE_LIMIT = parseInt(process.env.FAULT_RATE_LIMIT ?? "10");

function checkRateLimit(key: string) {
  if (process.env.FAULT_RATELIMIT !== "true") return;
  const now = Date.now();
  const window = 1000;
  if (!rateLimitMap.has(key)) rateLimitMap.set(key, []);
  const timestamps = rateLimitMap.get(key)!.filter(t => now - t < window);
  if (timestamps.length >= RATE_LIMIT) {
    throw new Error(`[Fault] Rate limit exceeded: ${RATE_LIMIT}/s`);
  }
  timestamps.push(now);
  rateLimitMap.set(key, timestamps);
}
```

### Java ( Resilience4j 风格)
```java
import io.github.resilience4j.circuitbreaker.*;
import java.time.Duration;

public class CircuitBreakerBottleneck {

    private static final CircuitBreaker cb = CircuitBreaker.of("default",
        CircuitBreakerConfig.custom()
            .failureRateThreshold(50)
            .waitDurationInOpenState(Duration.ofSeconds(5))
            .build());

    public static <T> T execute(Supplier<T> supplier) {
        if ("true".equals(System.getenv("FAULT_CIRCUIT_BREAKER"))) {
            return cb.executeSupplier(supplier);
        }
        return supplier.get();
    }
}
```

### Go (Sentinel-go / 自实现)
```go
import (
    "os"
    "sync"
    "time"
)

type RateLimiter struct {
    mu       sync.Mutex
    count    int
    resetAt  time.Time
    limit    int
    enabled  bool
}

func NewRateLimiter(limit int, enabled bool) *RateLimiter {
    return &RateLimiter{limit: limit, enabled: enabled, resetAt: time.Now().Add(time.Second)}
}

func (r *RateLimiter) Allow() error {
    if !r.enabled {
        return nil
    }
    if os.Getenv("FAULT_RATELIMIT") != "true" {
        return nil
    }
    r.mu.Lock()
    defer r.mu.Unlock()
    now := time.Now()
    if now.After(r.resetAt) {
        r.count = 0
        r.resetAt = now.Add(time.Second)
    }
    r.count++
    if r.count > r.limit {
        return errors.New("[Fault] rate limit exceeded")
    }
    return nil
}
```

### Rust
```rust
use std::collections::VecDeque;
use std::time::{Duration, Instant};

struct RateLimiter {
    window: VecDeque<Instant>,
    limit: usize,
    enabled: bool,
}

impl RateLimiter {
    fn new(limit: usize, enabled: bool) -> Self {
        Self { window: VecDeque::new(), limit, enabled }
    }

    fn allow(&mut self) -> Result<(), String> {
        if !self.enabled { return Ok(()); }
        if std::env::var("FAULT_RATELIMIT").unwrap_or_default() != "true" {
            return Ok(());
        }
        let now = Instant::now();
        let window = Duration::from_secs(1);
        while self.window.front().map(|t| now.duration_since(*t) > window).unwrap_or(false) {
            self.window.pop_front();
        }
        if self.window.len() >= self.limit {
            return Err("[Fault] rate limit exceeded".to_string());
        }
        self.window.push_back(now);
        Ok(())
    }
}
```

### C# (.NET Resilience)
```csharp
using Microsoft.Extensions.Http;
using Polly;
using Polly.CircuitBreaker;

public static class ResilienceBottleneck {
    public static IAsyncPolicy<HttpResponseMessage> CircuitBreakerPolicy =>
        Policy<HttpResponseMessage>
            .Handle<HttpRequestException>()
            .OrResult(r => (int)r.StatusCode >= 500)
            .CircuitBreakerAsync(
                handledEventsAllowedBeforeBreaking: 5,
                durationOfBreak: TimeSpan.FromSeconds(5)
            );

    public static bool IsEnabled =>
        Environment.GetEnvironmentVariable("FAULT_CIRCUIT_BREAKER") == "true";
}
```

### Ruby
```ruby
class RateLimiter
  def initialize(limit:, enabled: false)
    @limit = limit
    @enabled = enabled || ENV['FAULT_RATELIMIT'] == 'true'
    @requests = []
  end

  def allow
    return unless @enabled
    if ENV['FAULT_RATELIMIT'] != 'true'
      return
    end
    @requests.select! { |t| Time.now - t < 1 }
    if @requests.size >= @limit
      raise "[Fault] Rate limit exceeded: #{@limit}/s"
    end
    @requests << Time.now
  end
end
```

### PHP
```php
class RateLimiter {
    private int $limit;
    private bool $enabled;
    private array $requests = [];

    public function __construct(int $limit = 10, bool $enabled = false) {
        $this->limit = $limit;
        $this->enabled = $enabled || getenv('FAULT_RATELIMIT') === 'true';
    }

    public function allow(): void {
        if (!$this->enabled || getenv('FAULT_RATELIMIT') !== 'true') {
            return;
        }
        $now = microtime(true);
        $this->requests = array_filter($this->requests, fn($t) => $now - $t < 1);
        if (count($this->requests) >= $this->limit) {
            throw new \Exception("[Fault] Rate limit exceeded: {$this->limit}/s");
        }
        $this->requests[] = $now;
    }
}
```

### Kotlin (Resilience4j)
```kotlin
import io.github.resilience4j.circuitbreaker.*
import java.time.Duration

object CircuitBreakerBottleneck {
    private val config = CircuitBreakerConfig.builder()
        .failureRateThreshold(50f)
        .waitDurationInOpenState(Duration.ofSeconds(5))
        .build()

    val circuitBreaker = CircuitBreaker.of("default", config)

    fun <T> execute(supplier: () -> T): T {
        return if (System.getenv("FAULT_CIRCUIT_BREAKER") == "true") {
            circuitBreeck.executeSupplier(supplier)
        } else {
            supplier()
        }
    }
}
```

---

## 8. 资源耗尽 (Resource Exhaustion)

### Python
```python
import os
import sys

_resource_cache = []

def exhaust_memory():
    """持续申请内存直到 OOM"""
    if os.getenv("FAULT_OOM", "false") == "true":
        chunk_mb = int(os.getenv("FAULT_OOM_CHUNK_MB", "50"))
        while True:
            _resource_cache.append(bytearray(chunk_mb * 1024 * 1024))

def exhaust_fds():
    """耗尽文件描述符"""
    if os.getenv("FAULT_FD", "false") == "true":
        fds = []
        while True:
            try:
                fds.append(open("/dev/null", "r"))
            except OSError:
                break  # FD 耗尽
```

### JavaScript / TypeScript
```typescript
const memoryChunks: Buffer[] = [];

function exhaustMemory() {
  if (process.env.FAULT_OOM === "true") {
    const chunkMb = parseInt(process.env.FAULT_OOM_CHUNK_MB || "50");
    while (true) {
      memoryChunks.push(Buffer.alloc(chunkMb * 1024 * 1024));
    }
  }
}
```

### Java
```java
import java.util.*;

public class ResourceExhaustion {
    private static final List<byte[]> MEMORY_HOLDER = new ArrayList<>();

    public static void exhaustMemory() {
        if ("true".equals(System.getenv("FAULT_OOM"))) {
            int chunkMb = Integer.parseInt(
                System.getenv("FAULT_OOM_CHUNK_MB") != null ? System.getenv("FAULT_OOM_CHUNK_MB") : "50"
            );
            while (true) {
                MEMORY_HOLDER.add(new byte[chunkMb * 1024 * 1024]);
            }
        }
    }
}
```

### Go
```go
import "os"

func ExhaustMemory() {
    if os.Getenv("FAULT_OOM") == "true" {
        chunkMb := 50
        if c := os.Getenv("FAULT_OOM_CHUNK_MB"); c != "" {
            if parsed, err := strconv.Atoi(c); err == nil {
                chunkMb = parsed
            }
        }
        for {
            _ = make([]byte, chunkMb*1024*1024)
        }
    }
}
```

### C#
```csharp
public static class ResourceExhaustion {
    private static readonly List<byte[]> _memoryHolder = new List<byte[]>();

    public static void ExhaustMemory() {
        if (Environment.GetEnvironmentVariable("FAULT_OOM") == "true") {
            int chunkMb = int.Parse(
                Environment.GetEnvironmentVariable("FAULT_OOM_CHUNK_MB") ?? "50"
            );
            while (true) {
                _memoryHolder.Add(new byte[chunkMb * 1024 * 1024]);
            }
        }
    }
}
```

### PHP
```php
function exhaustMemory() {
    if (getenv('FAULT_OOM') === 'true') {
        $chunkMb = (int)(getenv('FAULT_OOM_CHUNK_MB') ?: 50);
        while (true) {
            $GLOBALS['_fault_mem'][] = str_repeat("\x00", $chunkMb * 1024 * 1024);
        }
    }
}
```

### Kotlin
```kotlin
object ResourceExhaustion {
    private val memoryHolder = mutableListOf<ByteArray>()

    fun exhaustMemory() {
        if (System.getenv("FAULT_OOM") == "true") {
            val chunkMb = (System.getenv("FAULT_OOM_CHUNK_MB") ?: "50").toInt()
            while (true) {
                memoryHolder.add(ByteArray(chunkMb * 1024 * 1024))
            }
        }
    }
}
```

---

## 完整使用示例

### Python Flask 应用（带全部注入点）

```python
import os
from flask import Flask, jsonify
# === 瓶颈注入点 1: CPU ===
# === 瓶颈注入点 2: 内存泄漏 ===
# === 瓶颈注入点 3: IO 阻塞 ===
# === 瓶颈注入点 4: 并发争用 ===
# === 瓶颈注入点 5: 限流 ===
# === 瓶颈注入点 6: 数据库 N+1 ===

app = Flask(__name__)

@app.route("/api/orders")
def get_orders():
    # [Fault Injection Point] CPU bottleneck
    # [Fault Injection Point] IO blocking
    # [Fault Injection Point] Rate limit
    # [Fault Injection Point] DB N+1
    return jsonify([])

if __name__ == "__main__":
    app.run()
```

### Node.js Express 应用（带全部注入点）

```typescript
import express from "express";
// === Fault Injection Points ===
// CPU: FAULT_CPU=true
// Memory Leak: FAULT_MEM_LEAK=true
// IO Block: FAULT_IO_BLOCK=true
// Net Latency: FAULT_NET_LATENCY=true
// Concurrency: FAULT_CONCURRENCY=true
// Rate Limit: FAULT_RATELIMIT=true
// DB N+1: FAULT_DB_N_PLUS_ONE=true

const app = express();
app.get("/api/orders", (req, res) => {
  // [Fault Injection Point] ...
  res.json([]);
});
```

---

## 环境变量快速参考

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `FAULT_INJECT_ENABLED` | 总开关 | `false` |
| `FAULT_CPU` | CPU 瓶颈 | `false` |
| `FAULT_CPU_DURATION` | CPU 持续时间（秒） | `5` |
| `FAULT_MEM_LEAK` | 内存泄漏 | `false` |
| `FAULT_IO_BLOCK` | IO 阻塞 | `false` |
| `FAULT_IO_DELAY_MS` | IO 延迟（毫秒） | `3000` |
| `FAULT_NET_LATENCY` | 网络延迟 | `false` |
| `FAULT_NET_LATENCY_MS` | 网络延迟（毫秒） | `500` |
| `FAULT_CONCURRENCY` | 并发争用 | `false` |
| `FAULT_LOCK_HOLD_MS` | 锁持有时间（毫秒） | `100` |
| `FAULT_RATELIMIT` | 限流 | `false` |
| `FAULT_RATE_LIMIT` | 限流阈值（次/秒） | `10` |
| `FAULT_CIRCUIT_BREAKER` | 熔断器 | `false` |
| `FAULT_DB_NO_INDEX` | 无索引查询 | `false` |
| `FAULT_DB_N_PLUS_ONE` | N+1 查询 | `false` |
| `FAULT_OOM` | 内存耗尽 | `false` |
| `FAULT_OOM_CHUNK_MB` | 每次申请内存大小（MB） | `50` |
| `FAULT_FD` | 文件描述符耗尽 | `false` |
