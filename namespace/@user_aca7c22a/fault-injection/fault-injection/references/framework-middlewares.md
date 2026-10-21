# Web 框架瓶颈注入中间件参考

> 本文档提供各主流 Web 框架的瓶颈注入中间件实现，覆盖 Flask、Express、Django、Spring Boot、Gin、Echo、Laravel、Rails、AspNetCore、Ktor。

---

## 通用环境变量（所有中间件共享）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `FAULT_INJECT_ENABLED` | 总开关 | `false` |
| `FAULT_CPU` | CPU 瓶颈 | `false` |
| `FAULT_IO_DELAY_MS` | IO 延迟（ms） | `3000` |
| `FAULT_NET_LATENCY_MS` | 网络延迟（ms） | `500` |
| `FAULT_CONCURRENCY` | 并发争用 | `false` |
| `FAULT_LOCK_HOLD_MS` | 锁持有时间（ms） | `100` |
| `FAULT_RATELIMIT` | 限流 | `false` |
| `FAULT_RATE_LIMIT` | 限流阈值（次/秒） | `10` |
| `FAULT_CIRCUIT_BREAKER` | 熔断器 | `false` |
| `FAULT_OOM` | 内存耗尽 | `false` |

---

## 1. Python — Flask

### 瓶颈注入中间件

```python
import os
import time
from flask import Flask, request, jsonify

# =============================================
# 瓶颈注入中间件 (Fault Injection Middleware)
# 挂载方式: app.wsgi_app = FaultInjectMiddleware(app.wsgi_app, app)
# 或使用 @app.before_request
# =============================================
class FaultInjectMiddleware:
    def __init__(self, app, flask_app):
        self.app = app
        self.flask_app = flask_app
        self._rl_cache = {}   # 限流滑动窗口

    def __call__(self, environ, start_response):
        if os.getenv("FAULT_INJECT_ENABLED", "false") != "true":
            return self.app(environ, start_response)

        # --- 网络延迟 ---
        if os.getenv("FAULT_NET_LATENCY") == "true":
            latency = int(os.getenv("FAULT_NET_LATENCY_MS", "500"))
            time.sleep(latency / 1000)

        # --- 限流 ---
        if os.getenv("FAULT_RATELIMIT") == "true":
            key = request.remote_addr or "default"
            limit = int(os.getenv("FAULT_RATE_LIMIT", "10"))
            now = time.time()
            self._rl_cache.setdefault(key, [])
            self._rl_cache[key] = [t for t in self._rl_cache[key] if now - t < 1]
            if len(self._rl_cache[key]) >= limit:
                return jsonify({"error": "[FAULT] Rate limit exceeded", "limit": f"{limit}/s"}), 429
            self._rl_cache[key].append(now)

        # --- 熔断 ---
        if os.getenv("FAULT_CIRCUIT_BREAKER") == "true":
            return jsonify({"error": "[FAULT] Circuit breaker OPEN"}), 503

        return self.app(environ, start_response)


# Flask 请求前置钩子（更简单的方式）
def fault_inject_before_request():
    if os.getenv("FAULT_CPU") == "true":
        duration = float(os.getenv("FAULT_CPU_DURATION", "5"))
        end_time = time.time() + duration
        while time.time() < end_time:
            _ = sum(i * i for i in range(5000))

    if os.getenv("FAULT_IO_DELAY") == "true":
        time.sleep(int(os.getenv("FAULT_IO_DELAY_MS", "3000")) / 1000)

    if os.getenv("FAULT_RATELIMIT") == "true":
        key = f"{request.remote_addr}:{request.endpoint}"
        limit = int(os.getenv("FAULT_RATE_LIMIT", "10"))
        now = time.time()
        if not hasattr(fault_inject_before_request, '_cache'):
            fault_inject_before_request._cache = {}
        fault_inject_before_request._cache.setdefault(key, [])
        fault_inject_before_request._cache[key] = [
            t for t in fault_inject_before_request._cache[key] if now - t < 1
        ]
        if len(fault_inject_before_request._cache[key]) >= limit:
            return jsonify({"error": "Rate limit exceeded"}), 429
        fault_inject_before_request._cache[key].append(now)

    if os.getenv("FAULT_CIRCUIT_BREAKER") == "true":
        return jsonify({"error": "Circuit breaker OPEN"}), 503


# 挂载方法:
# app = Flask(__name__)
# app.before_request(fault_inject_before_request)
```

---

## 2. JavaScript / TypeScript — Express.js

```typescript
// middleware/faultInject.ts
import { Request, Response, NextFunction } from "express";

// 限流滑动窗口存储
const rateLimitCache = new Map<string, number[]>();

// CPU 密集任务
function cpuBottleneck() {
  if (process.env.FAULT_CPU !== "true") return;
  const duration = parseInt(process.env.FAULT_CPU_DURATION || "5000");
  const end = Date.now() + duration;
  let r = 0;
  while (Date.now() < end) {
    for (let i = 0; i < 10000; i++) r += i * i;
  }
}

// Express 中间件
export function faultInject(req: Request, res: Response, next: NextFunction) {
  // 总开关
  if (process.env.FAULT_INJECT_ENABLED !== "true") return next();

  // --- CPU ---
  if (process.env.FAULT_CPU === "true") {
    cpuBottleneck();
  }

  // --- 网络延迟 ---
  if (process.env.FAULT_NET_LATENCY === "true") {
    const latency = parseInt(process.env.FAULT_NET_LATENCY_MS || "500");
    setTimeout(next, latency);
    return;
  }

  // --- IO 阻塞 ---
  if (process.env.FAULT_IO_BLOCK === "true") {
    const delay = parseInt(process.env.FAULT_IO_DELAY_MS || "3000");
    setTimeout(next, delay);
    return;
  }

  // --- 限流 ---
  if (process.env.FAULT_RATELIMIT === "true") {
    const key = req.ip || "default";
    const limit = parseInt(process.env.FAULT_RATE_LIMIT || "10");
    const now = Date.now();
    const window = 1000;
    if (!rateLimitCache.has(key)) rateLimitCache.set(key, []);
    const timestamps = rateLimitCache.get(key)!.filter(t => now - t < window);
    if (timestamps.length >= limit) {
      res.status(429).json({ error: "[FAULT] Rate limit exceeded", limit: `${limit}/s` });
      return;
    }
    timestamps.push(now);
    rateLimitCache.set(key, timestamps);
  }

  // --- 熔断 ---
  if (process.env.FAULT_CIRCUIT_BREAKER === "true") {
    res.status(503).json({ error: "[FAULT] Circuit breaker OPEN" });
    return;
  }

  next();
}

// 挂载方式（全局）:
// app.use(faultInject)
//
// 挂载方式（路由级）:
// app.get("/api/orders", faultInject, orderController)
```

### Express — 熔断器封装（使用 opossum）

```typescript
import CircuitBreaker from "opossum";

const options = {
  timeout: 3000,        // 请求超时
  errorThresholdPercentage: 50,  // 错误率 > 50% 时断开
  resetTimeout: 5000,    // 5秒后重试
};

export function createCircuitBreaker(fn: Function, name: string) {
  const breaker = new CircuitBreaker(fn, options);

  if (process.env.FAULT_CIRCUIT_BREAKER === "true") {
    // 人为打开熔断器
    breaker.open();
  }

  return breaker;
}
```

---

## 3. Java — Spring Boot

### 过滤器实现

```java
package com.example.filters;

import javax.servlet.*;
import javax.servlet.http.*;
import java.io.IOException;
import java.util.concurrent.ConcurrentHashMap;

public class FaultInjectFilter implements Filter {

    // 限流滑动窗口
    private static final ConcurrentHashMap<String, Long[]> rateLimitMap = new ConcurrentHashMap<>();

    @Override
    public void doFilter(ServletRequest req, ServletResponse res, FilterChain chain)
            throws IOException, ServletException {

        HttpServletRequest request = (HttpServletRequest) req;
        HttpServletResponse response = (HttpServletResponse) res;

        if (!"true".equals(System.getenv("FAULT_INJECT_ENABLED"))) {
            chain.doFilter(req, res);
            return;
        }

        // --- 网络延迟 ---
        if ("true".equals(System.getenv("FAULT_NET_LATENCY"))) {
            int latency = Integer.parseInt(
                System.getenv("FAULT_NET_LATENCY_MS") != null ? System.getenv("FAULT_NET_LATENCY_MS") : "500"
            );
            Thread.sleep(latency);
        }

        // --- 限流 ---
        if ("true".equals(System.getenv("FAULT_RATELIMIT"))) {
            String key = request.getRemoteAddr();
            int limit = Integer.parseInt(
                System.getenv("FAULT_RATE_LIMIT") != null ? System.getenv("FAULT_RATE_LIMIT") : "10"
            );
            long now = System.currentTimeMillis();
            rateLimitMap.putIfAbsent(key, new Long[0]);
            Long[] timestamps = rateLimitMap.get(key);
            Long[] filtered = java.util.Arrays.stream(timestamps)
                .filter(t -> now - t < 1000)
                .toArray(Long[]::new);
            if (filtered.length >= limit) {
                response.setStatus(429);
                response.getWriter().write("{\"error\": \"[FAULT] Rate limit exceeded\"}");
                return;
            }
            rateLimitMap.put(key, java.util.Arrays.copyOf(
                java.util.stream.Stream.concat(java.util.stream.Stream.of(now), java.util.stream.Stream.of(filtered)).toArray(Long[]::new),
                filtered.length + 1
            ));
            rateLimitMap.put(key, java.util.Arrays.copyOfRange(
                java.util.stream.Stream.concat(java.util.stream.Stream.of(now), java.util.stream.Stream.of(filtered)).toArray(Long[]::new),
                0, filtered.length + 1
            ));
        }

        // --- 熔断 ---
        if ("true".equals(System.getenv("FAULT_CIRCUIT_BREAKER"))) {
            response.setStatus(503);
            response.getWriter().write("{\"error\": \"[FAULT] Circuit breaker OPEN\"}");
            return;
        }

        chain.doFilter(req, res);
    }
}
```

### 注册方式

```java
// 在 @SpringBootApplication 类中注册
@Bean
public FilterRegistrationBean<FaultInjectFilter> faultInjectFilter() {
    FilterRegistrationBean<FaultInjectFilter> bean = new FilterRegistrationBean<>();
    bean.setFilter(new FaultInjectFilter());
    bean.addUrlPatterns("/*");
    bean.setOrder(Ordered.HIGHEST_PRECEDENCE + 10);
    return bean;
}
```

---

## 4. Go — Gin

### 中间件实现

```go
package middleware

import (
	"net/http"
	"os"
	"strconv"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

// 限流滑动窗口
var (
	rlMutex    sync.Mutex
	rlWindow   = make(map[string][]int64)
	rlLimit    = 10
	rlWindowMs = 1000
)

func init() {
	if l := os.Getenv("FAULT_RATE_LIMIT"); l != "" {
		if parsed, err := strconv.Atoi(l); err == nil {
			rlLimit = parsed
		}
	}
}

// FaultInject — Gin 瓶颈注入中间件
func FaultInject() gin.HandlerFunc {
	return func(c *gin.Context) {
		if os.Getenv("FAULT_INJECT_ENABLED") != "true" {
			c.Next()
			return
		}

		// --- 网络延迟 ---
		if os.Getenv("FAULT_NET_LATENCY") == "true" {
			latencyMs := 500
			if l := os.Getenv("FAULT_NET_LATENCY_MS"); l != "" {
				if parsed, err := strconv.Atoi(l); err == nil {
					latencyMs = parsed
				}
			}
			time.Sleep(time.Duration(latencyMs) * time.Millisecond)
		}

		// --- IO 阻塞 ---
		if os.Getenv("FAULT_IO_BLOCK") == "true" {
			delayMs := 3000
			if d := os.Getenv("FAULT_IO_DELAY_MS"); d != "" {
				if parsed, err := strconv.Atoi(d); err == nil {
					delayMs = parsed
				}
			}
			time.Sleep(time.Duration(delayMs) * time.Millisecond)
		}

		// --- 限流 ---
		if os.Getenv("FAULT_RATELIMIT") == "true" {
			key := c.ClientIP()
			now := time.Now().UnixMilli()
			rlMutex.Lock()
			cutoff := now - rlWindowMs
			rlWindow[key] = append(rlWindow[key], now)
			var valid []int64
			for _, t := range rlWindow[key] {
				if t > cutoff {
					valid = append(valid, t)
				}
			}
			rlWindow[key] = valid
			if len(valid) > rlLimit {
				rlMutex.Unlock()
				c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
					"error":  "[FAULT] Rate limit exceeded",
					"limit":  strconv.Itoa(rlLimit) + "/s",
				})
				return
			}
			rlMutex.Unlock()
		}

		// --- 熔断 ---
		if os.Getenv("FAULT_CIRCUIT_BREAKER") == "true" {
			c.AbortWithStatusJSON(503, gin.H{
				"error": "[FAULT] Circuit breaker OPEN",
			})
			return
		}

		c.Next()
	}
}
```

### 挂载方式

```go
func main() {
	r := gin.Default()

	// 全局挂载
	r.Use(middleware.FaultInject())

	// 路由级挂载
	r.GET("/api/orders", middleware.FaultInject(), getOrders)
}
```

---

## 5. JavaScript — Fastify

```typescript
// 挂载方式（全局）
import Fastify from "fastify";

const fastify = Fastify({ logger: true });

fastify.addHook("onRequest", async (request, reply) => {
  if (process.env.FAULT_INJECT_ENABLED !== "true") return;

  if (process.env.FAULT_NET_LATENCY === "true") {
    const latency = parseInt(process.env.FAULT_NET_LATENCY_MS || "500");
    await new Promise(r => setTimeout(r, latency));
  }

  if (process.env.FAULT_RATELIMIT === "true") {
    const key = request.ip;
    const limit = parseInt(process.env.FAULT_RATE_LIMIT || "10");
    const now = Date.now();
    if (!global._fastifyRl) global._fastifyRl = {};
    if (!global._fastifyRl[key]) global._fastifyRl[key] = [];
    global._fastifyRl[key] = global._fastifyRl[key].filter(t => now - t < 1000);
    if (global._fastifyRl[key].length >= limit) {
      reply.code(429).send({ error: "[FAULT] Rate limit exceeded" });
      return;
    }
    global._fastifyRl[key].push(now);
  }

  if (process.env.FAULT_CIRCUIT_BREAKER === "true") {
    reply.code(503).send({ error: "[FAULT] Circuit breaker OPEN" });
    return;
  }
});

await fastify.listen({ port: 3000 });
```

---

## 6. Python — Django

```python
# myapp/middleware.py
import os
import time
from django.http import JsonResponse

class FaultInjectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._rl_cache = {}

    def __call__(self, request):
        if os.getenv("FAULT_INJECT_ENABLED", "false") != "true":
            return self.get_response(request)

        # 网络延迟
        if os.getenv("FAULT_NET_LATENCY") == "true":
            latency = int(os.getenv("FAULT_NET_LATENCY_MS", "500"))
            time.sleep(latency / 1000)

        # 限流
        if os.getenv("FAULT_RATELIMIT") == "true":
            key = self._get_rl_key(request)
            limit = int(os.getenv("FAULT_RATE_LIMIT", "10"))
            now = time.time()
            self._rl_cache.setdefault(key, [])
            self._rl_cache[key] = [t for t in self._rl_cache[key] if now - t < 1]
            if len(self._rl_cache[key]) >= limit:
                return JsonResponse({"error": "[FAULT] Rate limit exceeded"}, status=429)
            self._rl_cache[key].append(now)

        # 熔断
        if os.getenv("FAULT_CIRCUIT_BREAKER") == "true":
            return JsonResponse({"error": "[FAULT] Circuit breaker OPEN"}, status=503)

        return self.get_response(request)

    def _get_rl_key(self, request):
        return f"{request.META.get('REMOTE_ADDR')}:{request.path}"
```

注册到 `settings.py`:
```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'myapp.middleware.FaultInjectMiddleware',  # 添加在这里
    # ...
]
```

---

## 7. Ruby — Rails

```ruby
# app/middleware/fault_inject_middleware.rb
class FaultInjectMiddleware
  RATE_LIMIT_WINDOW = 1  # 秒
  RATE_LIMIT_DEFAULT = 10

  def initialize(app)
    @app = app
    @rl_cache = {}
  end

  def call(env)
    unless ENV['FAULT_INJECT_ENABLED'] == 'true'
      return @app.call(env)
    end

    # 网络延迟
    if ENV['FAULT_NET_LATENCY'] == 'true'
      latency_ms = (ENV['FAULT_NET_LATENCY_MS'] || '500').to_i
      sleep(latency_ms / 1000.0)
    end

    # 限流
    if ENV['FAULT_RATELIMIT'] == 'true'
      key = "#{env['REMOTE_ADDR']}:#{env['PATH_INFO']}"
      limit = (ENV['FAULT_RATE_LIMIT'] || "#{RATE_LIMIT_DEFAULT}").to_i
      now = Time.now.to_f

      @rl_cache[key] ||= []
      @rl_cache[key].select! { |t| now - t < RATE_LIMIT_WINDOW }

      if @rl_cache[key].size >= limit
        return [429, { 'Content-Type' => 'application/json' },
          [{ error: '[FAULT] Rate limit exceeded' }.to_json]]
      end
      @rl_cache[key] << now
    end

    # 熔断
    if ENV['FAULT_CIRCUIT_BREAKER'] == 'true'
      return [503, { 'Content-Type' => 'application/json' },
        [{ error: '[FAULT] Circuit breaker OPEN' }.to_json]]
    end

    @app.call(env)
  end
end
```

注册到 `config/application.rb`:
```ruby
config.middleware.use FaultInjectMiddleware
```

---

## 8. PHP — Laravel

```php
<?php
// app/Http/Middleware/FaultInject.php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;

class FaultInject
{
    private static $rateLimitCache = [];

    public function handle(Request $request, Closure $next)
    {
        if (getenv('FAULT_INJECT_ENABLED') !== 'true') {
            return $next($request);
        }

        // 网络延迟
        if (getenv('FAULT_NET_LATENCY') === 'true') {
            $latencyMs = (int)(getenv('FAULT_NET_LATENCY_MS') ?: 500);
            usleep($latencyMs * 1000);
        }

        // IO 阻塞
        if (getenv('FAULT_IO_BLOCK') === 'true') {
            $delayMs = (int)(getenv('FAULT_IO_DELAY_MS') ?: 3000);
            usleep($delayMs * 1000);
        }

        // 限流
        if (getenv('FAULT_RATELIMIT') === 'true') {
            $key = $request->ip() . ':' . $request->path();
            $limit = (int)(getenv('FAULT_RATE_LIMIT') ?: 10);
            $now = microtime(true);

            if (!isset(self::$rateLimitCache[$key])) {
                self::$rateLimitCache[$key] = [];
            }
            self::$rateLimitCache[$key] = array_filter(
                self::$rateLimitCache[$key],
                fn($t) => $now - $t < 1
            );

            if (count(self::$rateLimitCache[$key]) >= $limit) {
                return response()->json([
                    'error' => '[FAULT] Rate limit exceeded',
                    'limit' => "{$limit}/s",
                ], 429);
            }
            self::$rateLimitCache[$key][] = $now;
        }

        // 熔断
        if (getenv('FAULT_CIRCUIT_BREAKER') === 'true') {
            return response()->json([
                'error' => '[FAULT] Circuit breaker OPEN',
            ], 503);
        }

        return $next($request);
    }
}
```

注册到 `app/Http/Kernel.php`:
```php
protected $middlewareAliases = [
    'fault.inject' => \App\Http\Middleware\FaultInject::class,
];
```

使用（全局）: `config/app.php` 的 `$middleware` 中注册。
使用（路由）: `Route::get('/api/orders', [OrderController::class, 'index'])->middleware('fault.inject');`

---

## 9. C# — ASP.NET Core

```csharp
// Middleware/FaultInjectMiddleware.cs
using Microsoft.AspNetCore.Http;
using System.Collections.Concurrent;

public class FaultInjectMiddleware
{
    private readonly RequestDelegate _next;
    private static readonly ConcurrentDictionary<string, List<long>> _rateLimitCache = new();

    public FaultInjectMiddleware(RequestDelegate next) => _next = next;

    public async Task InvokeAsync(HttpContext context)
    {
        if (Environment.GetEnvironmentVariable("FAULT_INJECT_ENABLED") != "true")
        {
            await _next(context);
            return;
        }

        // 网络延迟
        if (Environment.GetEnvironmentVariable("FAULT_NET_LATENCY") == "true")
        {
            int latencyMs = int.Parse(
                Environment.GetEnvironmentVariable("FAULT_NET_LATENCY_MS") ?? "500"
            );
            await Task.Delay(latencyMs);
        }

        // 限流
        if (Environment.GetEnvironmentVariable("FAULT_RATELIMIT") == "true")
        {
            string key = context.Connection.RemoteIpAddress?.ToString() + ":" + context.Request.Path;
            int limit = int.Parse(Environment.GetEnvironmentVariable("FAULT_RATE_LIMIT") ?? "10");
            long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

            if (!_rateLimitCache.ContainsKey(key))
                _rateLimitCache[key] = new List<long>();

            _rateLimitCache[key] = _rateLimitCache[key]
                .Where(t => now - t < 1000)
                .Append(now)
                .ToList();

            if (_rateLimitCache[key].Count > limit)
            {
                context.Response.StatusCode = 429;
                await context.Response.WriteAsJsonAsync(
                    new { error = "[FAULT] Rate limit exceeded", limit = $"{limit}/s" }
                );
                return;
            }
        }

        // 熔断
        if (Environment.GetEnvironmentVariable("FAULT_CIRCUIT_BREAKER") == "true")
        {
            context.Response.StatusCode = 503;
            await context.Response.WriteAsJsonAsync(
                new { error = "[FAULT] Circuit breaker OPEN" }
            );
            return;
        }

        await _next(context);
    }
}
```

注册到 `Program.cs`:
```csharp
// 全局
app.UseMiddleware<FaultInjectMiddleware>();

// 或路由级
app.UseWhen(ctx => ctx.Request.Path.StartsWithSegments("/api"),
    appBuilder => appBuilder.UseMiddleware<FaultInjectMiddleware>());
```

---

## 10. Kotlin — Ktor

```kotlin
// io.ktor.samples.faultinject.FaultInjectPlugin.kt
package io.ktor.samples.faultinject

import io.ktor.application.*
import io.ktor.features.*
import io.ktor.request.*
import io.ktor.response.*
import java.util.concurrent.ConcurrentHashMap

val FaultInjectPlugin = createApplicationPlugin("FaultInject") {
    val rlCache = ConcurrentHashMap<String, MutableList<Long>>()

    onCall { call ->
        if (System.getenv("FAULT_INJECT_ENABLED") != "true") return@onCall

        // 网络延迟
        if (System.getenv("FAULT_NET_LATENCY") == "true") {
            val latencyMs = (System.getenv("FAULT_NET_LATENCY_MS") ?: "500").toLong()
            kotlinx.coroutines.delay(latencyMs)
        }

        // 限流
        if (System.getenv("FAULT_RATELIMIT") == "true") {
            val key = "${call.request.origin.remoteHost}:${call.request.path()}"
            val limit = (System.getenv("FAULT_RATE_LIMIT") ?: "10").toInt()
            val now = System.currentTimeMillis()

            rlCache.getOrPut(key) { mutableListOf() }.let { list ->
                list.removeIf { now - it > 1000 }
                list.add(now)
                if (list.size > limit) {
                    call.respond(
                        io.ktor.http.HttpStatusCode.TooManyRequests,
                        mapOf("error" to "[FAULT] Rate limit exceeded", "limit" to "$limit/s")
                    )
                    return@onCall
                }
            }
        }

        // 熔断
        if (System.getenv("FAULT_CIRCUIT_BREAKER") == "true") {
            call.respond(
                io.ktor.http.HttpStatusCode.ServiceUnavailable,
                mapOf("error" to "[FAULT] Circuit breaker OPEN")
            )
            return@onCall
        }
    }
}

// 挂载方式
fun Application.module() {
    install(FaultInjectPlugin)
    // ...
}
```

---

## 11. Swift — Vapor

```swift
// Sources/App/middleware/FaultInjectMiddleware.swift
import Vapor

struct FaultInjectMiddleware: Middleware {
    private static var rateLimitCache: [String: [Date]] = [:]
    private static let rateLimitQueue = DispatchQueue(label: "fault.ratelimit")

    func respond(to req: Request, chainingTo next: Responder) -> EventLoopFuture<Response> {
        guard ProcessInfo.processInfo.environment["FAULT_INJECT_ENABLED"] == "true" else {
            return next.respond(to: req)
        }

        // 网络延迟
        if ProcessInfo.processInfo.environment["FAULT_NET_LATENCY"] == "true" {
            let latencyMs = Double(ProcessInfo.processInfo.environment["FAULT_NET_LATENCY_MS"] ?? "500") ?? 500
            return req.eventLoop.sleep(.milliseconds(Int(latencyMs)))
                .flatMap { _ in next.respond(to: req) }
        }

        // 限流
        if ProcessInfo.processInfo.environment["FAULT_RATELIMIT"] == "true" {
            let key = req.remoteAddress?.ipAddress ?? "default"
            let limit = Int(ProcessInfo.processInfo.environment["FAULT_RATE_LIMIT"] ?? "10") ?? 10
            let now = Date()

            return Self.rateLimitQueue.sync {
                var timestamps = Self.rateLimitCache[key] ?? []
                timestamps = timestamps.filter { now.timeIntervalSince($0) < 1.0 }
                timestamps.append(now)
                Self.rateLimitCache[key] = timestamps

                if timestamps.count > limit {
                    return true
                }
                return false
            }.flatMap { exceeded -> EventLoopFuture<Response> in
                if exceeded {
                    return try! req.Response(
                        status: .tooManyRequests,
                        body: "[FAULT] Rate limit exceeded"
                    )
                }
                return next.respond(to: req)
            }
        }

        // 熔断
        if ProcessInfo.processInfo.environment["FAULT_CIRCUIT_BREAKER"] == "true" {
            return try! req.Response(
                status: .serviceUnavailable,
                body: "[FAULT] Circuit breaker OPEN"
            )
        }

        return next.respond(to: req)
    }
}

// 挂载方式（全局）:
// app.middleware.use(FaultInjectMiddleware())
```

---

## 12. C++ — 使用 Nginx 作为注入层

> 对于 C++ 服务，建议在 Nginx 层做网络延迟和限流注入，更可靠。

### Nginx 配置（故障注入）

```nginx
# nginx.conf — 瓶颈注入配置
# 启用方式: nginx -c /path/to/fault-nginx.conf

http {
    # --- 限流 ---
    limit_req_zone $binary_remote_addr zone=fault_limit:10m rate=10r/s;

    server {
        listen 8080;

        location / {
            # --- 网络延迟注入 ---
            set $latency 0;
            set $latency_ms 500;
            if ($http_x_fault_net_latency = "true") {
                set $latency_ms $http_x_fault_net_latency_ms;
            }

            # 在变量中注入延迟
            echo_after_body $echo_request_method;
        }

        # --- 熔断 ---
        location /health {
            if ($http_x_fault_circuit_breaker = "true") {
                return 503 '{"error": "[FAULT] Circuit breaker OPEN"}';
            }
            return 200 'ok';
        }
    }
}
```

### C++ 应用层注入示例

```cpp
// fault_inject.h — C++ 瓶颈注入头文件
#pragma once
#include <chrono>
#include <thread>
#include <mutex>
#include <cstdlib>
#include <ctime>
#include <map>

namespace FaultInject {

struct Config {
    bool enabled = false;
    bool cpu_bottleneck = false;
    int cpu_duration_ms = 5000;
    bool io_block = false;
    int io_delay_ms = 3000;
    bool net_latency = false;
    int net_latency_ms = 500;
    bool ratelimit = false;
    int rate_limit = 10;
    bool circuit_breaker = false;
};

class RateLimiter {
public:
    bool allow(const std::string& key, int limit) {
        auto now = std::chrono::steady_clock::now();
        std::lock_guard<std::mutex> lock(mutex_);
        auto& window = cache_[key];
        window.erase(
            std::remove_if(window.begin(), window.end(),
                [&](auto t) { return now - t > std::chrono::seconds(1); }),
            window.end()
        );
        if (window.size() >= static_cast<size_t>(limit)) return false;
        window.push_back(now);
        return true;
    }
private:
    std::mutex mutex_;
    std::map<std::string, std::vector<std::chrono::steady_clock::time_point>> cache_;
};

class Injector {
public:
    static Injector& instance() {
        static Injector inst;
        return inst;
    }

    void configure(const Config& cfg) { cfg_ = cfg; }

    bool check(const std::string& env_key, bool default_val = false) {
        const char* val = std::getenv(env_key.c_str());
        if (val && std::string(val) == "true") return true;
        return default_val;
    }

    int getInt(const std::string& env_key, int default_val) {
        const char* val = std::getenv(env_key.c_str());
        return val ? std::atoi(val) : default_val;
    }

    void injectCpu() {
        if (!cfg_.enabled || !cfg_.cpu_bottleneck) return;
        if (!check("FAULT_CPU", false)) return;
        auto end = std::chrono::steady_clock::now() +
            std::chrono::milliseconds(getInt("FAULT_CPU_DURATION", cfg_.cpu_duration_ms));
        long long r = 0;
        while (std::chrono::steady_clock::now() < end) {
            for (int i = 0; i < 10000; ++i) r += i * i;
        }
    }

    void injectNetLatency() {
        if (!cfg_.enabled || !check("FAULT_NET_LATENCY", false)) return;
        std::this_thread::sleep_for(
            std::chrono::milliseconds(getInt("FAULT_NET_LATENCY_MS", cfg_.net_latency_ms)));
    }

    bool injectRatelimit(const std::string& key) {
        if (!cfg_.enabled || !check("FAULT_RATELIMIT", false)) return true;
        return rateLimiter_.allow(key, getInt("FAULT_RATE_LIMIT", cfg_.rate_limit));
    }

    bool injectCircuitBreaker() {
        if (!cfg_.enabled || !check("FAULT_CIRCUIT_BREAKER", false)) return false;
        return true; // 返回 true 表示触发熔断
    }

private:
    Config cfg_;
    RateLimiter rateLimiter_;
};

} // namespace FaultInject

// 使用示例:
//   FaultInject::Injector& fi = FaultInject::Injector::instance();
//   fi.configure({.enabled = true});
//   fi.injectCpu();
//   fi.injectNetLatency();
```

---

## 框架支持速查表

| 框架 | 语言 | 中间件名称 | 全局挂载 | 路由级挂载 |
|------|------|----------|----------|-----------|
| Flask | Python | `FaultInjectMiddleware` | `app.wsgi_app = ...` | `@app.before_request` |
| Django | Python | `FaultInjectMiddleware` | `settings.MIDDLEWARE` | `view decorator` |
| Express | JS/TS | `faultInject` | `app.use(faultInject)` | `app.get(path, faultInject, handler)` |
| Fastify | JS/TS | `onRequest` hook | `addHook("onRequest")` | plugin scoped |
| Spring Boot | Java | `FaultInjectFilter` | `@Bean FilterRegistrationBean` | `@WebFilter` |
| Gin | Go | `FaultInject()` | `r.Use(FaultInject())` | `r.GET("/x", FaultInject(), h)` |
| Rails | Ruby | `FaultInjectMiddleware` | `config.middleware.use` | `config.middleware.insert_after` |
| Laravel | PHP | `FaultInject` | `$middleware` | route `.middleware('fault.inject')` |
| ASP.NET Core | C# | `FaultInjectMiddleware` | `app.UseMiddleware<...>()` | `app.UseWhen` |
| Ktor | Kotlin | `FaultInjectPlugin` | `install(FaultInjectPlugin)` | route-level plugin |
| Vapor | Swift | `FaultInjectMiddleware` | `app.middleware.use(...)` | — |
| C++ | C++ | `FaultInject::Injector` | Nginx 层 | 直接调用 |
