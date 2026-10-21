#!/usr/bin/env python3
"""
fault-injection 自动化注入脚本
用法:
  python3 auto_inject.py <file> --type <bottleneck_type> [--enable] [--report]

支持的瓶颈类型:
  cpu | mem-leak | io-block | net-latency | concurrency |
  db-n-plus-one | ratelimit | circuit-breaker | oom | all

支持的扩展名 → 语言映射:
  .py .pyw                     → python
  .js .jsx .ts .tsx .mjs       → javascript
  .java                        → java
  .go                          → go
  .rs                          → rust
  .cs                          → csharp
  .rb                          → ruby
  .php                         → php
  .kt .kts                     → kotlin
  .swift                       → swift
  .cpp .cc .cxx .h .hpp        → cpp
  .zig                         → zig
  .vue .svelte                 → vue
  .dart                        → dart
"""

import os
import re
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

# ============================================================
# 瓶颈类型 → 环境变量名映射
# ============================================================
BOTTLENECK_ENV_MAP = {
    "cpu":               "FAULT_CPU",
    "mem-leak":          "FAULT_MEM_LEAK",
    "io-block":          "FAULT_IO_BLOCK",
    "net-latency":       "FAULT_NET_LATENCY",
    "concurrency":       "FAULT_CONCURRENCY",
    "db-n-plus-one":     "FAULT_DB_N_PLUS_ONE",
    "ratelimit":         "FAULT_RATELIMIT",
    "circuit-breaker":   "FAULT_CIRCUIT_BREAKER",
    "oom":               "FAULT_OOM",
    "all":               "FAULT_INJECT_ENABLED",
}

# ============================================================
# 语言 → 扩展名映射
# ============================================================
EXT_TO_LANG = {
    ".py":   "python",
    ".pyw":  "python",
    ".js":   "javascript",
    ".jsx":  "javascript",
    ".ts":   "typescript",
    ".tsx":  "typescript",
    ".mjs":  "javascript",
    ".cjs":  "javascript",
    ".java": "java",
    ".go":   "go",
    ".rs":   "rust",
    ".cs":   "csharp",
    ".rb":   "ruby",
    ".php":  "php",
    ".kt":   "kotlin",
    ".kts":  "kotlin",
    ".swift": "swift",
    ".cpp":  "cpp",
    ".cc":  "cpp",
    ".cxx":  "cpp",
    ".h":    "cpp",
    ".hpp":  "cpp",
    ".zig":  "zig",
    ".vue":  "vue",
    ".svelte": "svelte",
    ".dart": "dart",
}

# ============================================================
# 各语言注入点前缀注释（用于标记和清理）
# ============================================================
MARKER = "FAULT_INJECT"

def marker_comment(lang: str, bottleneck_type: str, pattern_name: str) -> str:
    markers = {
        "python":    f"# [{MARKER}] {bottleneck_type} | {pattern_name}",
        "javascript": f"// [{MARKER}] {bottleneck_type} | {pattern_name}",
        "typescript": f"// [{MARKER}] {bottleneck_type} | {pattern_name}",
        "java":      f"// [{MARKER}] {bottleneck_type} | {pattern_name}",
        "go":        f"// [{MARKER}] {bottleneck_type} | {pattern_name}",
        "rust":      f"// [{MARKER}] {bottleneck_type} | {pattern_name}",
        "csharp":    f"// [{MARKER}] {bottleneck_type} | {pattern_name}",
        "ruby":      f"# [{MARKER}] {bottleneck_type} | {pattern_name}",
        "php":       f"// [{MARKER}] {bottleneck_type} | {pattern_name}",
        "kotlin":    f"// [{MARKER}] {bottleneck_type} | {pattern_name}",
        "swift":     f"// [{MARKER}] {bottleneck_type} | {pattern_name}",
        "cpp":       f"// [{MARKER}] {bottleneck_type} | {pattern_name}",
        "zig":       f"// [{MARKER}] {bottleneck_type} | {pattern_name}",
        "vue":       f"<!-- [{MARKER}] {bottleneck_type} | {pattern_name} -->",
        "svelte":    f"<!-- [{MARKER}] {bottleneck_type} | {pattern_name} -->",
        "dart":      f"// [{MARKER}] {bottleneck_type} | {pattern_name}",
    }
    return markers.get(lang, f"// [{MARKER}] {bottleneck_type} | {pattern_name}")

def end_marker(lang: str) -> str:
    markers = {
        "python":    "# [/FAULT_INJECT]",
        "javascript": "// [/FAULT_INJECT]",
        "typescript": "// [/FAULT_INJECT]",
        "java":      "// [/FAULT_INJECT]",
        "go":        "// [/FAULT_INJECT]",
        "rust":      "// [/FAULT_INJECT]",
        "csharp":    "// [/FAULT_INJECT]",
        "ruby":      "# [/FAULT_INJECT]",
        "php":       "// [/FAULT_INJECT]",
        "kotlin":    "// [/FAULT_INJECT]",
        "swift":     "// [/FAULT_INJECT]",
        "cpp":       "// [/FAULT_INJECT]",
        "zig":       "// [/FAULT_INJECT]",
        "vue":       "<!-- [/FAULT_INJECT] -->",
        "svelte":    "<!-- [/FAULT_INJECT] -->",
        "dart":      "// [/FAULT_INJECT]",
    }
    return markers.get(lang, "// [/FAULT_INJECT]")

def fault_block(lang: str, env_var: str, body: str, enabled: bool = False) -> str:
    """生成条件注入代码块"""
    body = body.strip()
    cond = f'{env_var} == "true"' if enabled else f'os.getenv("{env_var}", "false") == "true"'

    templates = {
        "python": f'if os.getenv("{env_var}", "false") == "true":\n    pass  # TODO: inject bottleneck',
        "javascript": f'if (process.env.{env_var} === "true") {{\n  // TODO: inject bottleneck\n}}',
        "typescript": f'if (process.env.{env_var} === "true") {{\n  // TODO: inject bottleneck\n}}',
        "java": f'if ("true".equals(System.getenv("{env_var}"))) {{\n    // TODO: inject bottleneck\n}}',
        "go": f'if os.Getenv("{env_var}") == "true" {{\n    // TODO: inject bottleneck\n}}',
        "rust": f'if std::env::var("{env_var}").unwrap_or_default() == "true" {{\n    // TODO: inject bottleneck\n}}',
        "csharp": f'if (Environment.GetEnvironmentVariable("{env_var}") == "true") {{\n    // TODO: inject bottleneck\n}}',
        "ruby": f'if ENV["{env_var}"] == "true"\n  # TODO: inject bottleneck\nend',
        "php": f'if (getenv("{env_var}") === "true") {{\n    // TODO: inject bottleneck\n}}',
        "kotlin": f'if (System.getenv("{env_var}") == "true") {{\n    // TODO: inject bottleneck\n}}',
        "swift": f'if ProcessInfo.processInfo.environment["{env_var}"] == "true" {{\n    // TODO: inject bottleneck\n}}',
        "cpp": f'if (std::getenv("{env_var}") && std::string(std::getenv("{env_var}")) == "true") {{\n    // TODO: inject bottleneck\n}}',
        "zig": f'if (std.os.getenv("{env_var}")) |val| {{\n    if (std.mem.eql(u8, val, "true")) {{\n        // TODO: inject bottleneck\n    }}\n}}',
        "vue": f'<!-- template: inject in <script> -->\n<script>\nif (process.env.{env_var} === "true") {{\n  // TODO: inject bottleneck\n}}\n</script>',
        "svelte": f'<script>\nif (process.env.{env_var} === "true") {{\n  // TODO: inject bottleneck\n}}\n</script>',
        "dart": f'if (Platform.environment["{env_var}"] == "true") {{\n  // TODO: inject bottleneck\n}}',
    }
    return templates.get(lang, f'// TODO: {env_var} inject')

# ============================================================
# 注入点查找逻辑
# ============================================================

def find_injection_points(content: str, lang: str) -> list:
    """
    扫描代码文件，找出最佳注入点（函数/方法定义行）。
    返回: [{'line': int, 'indentation': str, 'signature': str}]
    """
    patterns = {
        "python": [
            r'^(\s*)(def\s+\w+\s*\([^)]*\)\s*(?:->\s*\w+)?:)',
            r'^(\s*)(async\s+def\s+\w+\s*\([^)]*\)\s*(?:->\s*\w+)?:)',
            r'^(\s*)(class\s+\w+\s*(?:\([^)]*\))?:)',
        ],
        "javascript": [
            r'^(\s*)(async\s+)?function\s+\w+\s*\([^)]*\)',
            r'^(\s*)const\s+\w+\s*=\s*(?:async\s+)?\([^)]*\)\s*=>',
            r'^(\s*)class\s+\w+',
        ],
        "typescript": [
            r'^(\s*)(async\s+)?function\s+\w+\s*[<(]',
            r'^(\s*)const\s+\w+\s*[:=]\s*(?:async\s+)?\([^)]*\)\s*(?::\s*\w+)?\s*=>',
            r'^(\s*)class\s+\w+',
            r'^(\s*)(@[\w]+\s+)?(async\s+)?(\w+)\s*\([^)]*\)\s*:\s*\w+',
        ],
        "java": [
            r'^\s*(public|private|protected)?\s*(static)?\s*\w+\s+\w+\s*\([^)]*\)',
            r'^\s*(@[\w]+(\([^)]*\))?\s+)*(public|private|protected)?\s*(static)?\s*\w+\s+\w+\s*\([^)]*\)',
        ],
        "go": [
            r'^func\s+(\([^)]+\)\s*)?\w+\s*\([^)]*\)',
            r'^func\s+\w+\s*\([^)]*\)',
        ],
        "rust": [
            r'^(\s*)(pub\s+)?(async\s+)?fn\s+\w+\s*[<(]',
            r'^(\s*)(pub\s+)?(async\s+)?struct\s+\w+',
        ],
        "csharp": [
            r'^\s*(public|private|protected|internal)?\s*(static)?\s*(async)?\s*\w+\s+\w+\s*\([^)]*\)',
            r'^\s*(\[.*\]\s+)*(public|private|protected|internal)?\s*(static)?\s*\w+\s+\w+\s*\([^)]*\)',
        ],
        "ruby": [
            r'^(\s*)(def\s+\w+)',
            r'^(\s*)(class\s+\w+)',
        ],
        "php": [
            r'^\s*(public|private|protected)?\s*function\s+\w+\s*\([^)]*\)',
        ],
        "kotlin": [
            r'^\s*(fun\s+\w+\s*[<(])',
            r'^\s*(suspend\s+fun\s+\w+\s*[<(])',
            r'^\s*(@[\w]+(\([^)]*\))?\s+)*(fun\s+\w+\s*[<(])',
        ],
        "swift": [
            r'^(\s*)(func\s+\w+\s*[<(])',
            r'^(\s*)(class\s+\w+)',
        ],
        "cpp": [
            r'^\s*(void|int|bool|std::\w+|auto|\w+)\s+\w+\s*\([^)]*\)\s*(const)?\s*\{',
            r'^\s*(\w+)\s+(\w+)\s*\([^)]*\)\s*(const)?\s*\{',
        ],
        "zig": [
            r'^(\s*)fn\s+\w+\s*[<(]',
        ],
        "vue": [
            r'^\s*(async\s+)?function\s+\w+\s*\([^)]*\)',
            r'^\s*const\s+\w+\s*=\s*(async\s+)?\([^)]*\)\s*=>',
        ],
        "svelte": [
            r'^\s*(async\s+)?function\s+\w+\s*\([^)]*\)',
            r'^\s*const\s+\w+\s*=\s*(async\s+)?\([^)]*\)\s*=>',
        ],
        "dart": [
            r'^\s*(Future<\w+>|Stream<\w+>|\w+)\s+\w+\s*\([^)]*\)\s*(async)?',
            r'^\s*(@[\w]+(\([^)]*\))?\s+)*(Future<\w+>|Stream<\w+>|\w+)\s+\w+\s*\([^)]*\)',
        ],
    }

    lang_patterns = patterns.get(lang, patterns["javascript"])
    results = []
    lines = content.split("\n")

    for i, line in enumerate(lines, 1):
        for pat in lang_patterns:
            m = re.match(pat, line.strip())
            if m:
                indent = m.group(1) if m.lastindex >= 1 else ""
                sig = line.strip()
                results.append({
                    "line": i,
                    "indentation": indent,
                    "signature": sig,
                    "match_pattern": pat,
                })
                break
    return results


def build_injection_block(lang: str, bottleneck_type: str, env_var: str) -> str:
    """根据瓶颈类型生成完整注入代码块"""
    mc = marker_comment(lang, bottleneck_type, env_var)
    em = end_marker(lang)

    blocks = {
        "cpu": {
            "python": f"""{mc}
import time
_cpu_end = time.time() + float(os.getenv("FAULT_CPU_DURATION", "5"))
while time.time() < _cpu_end:
    _ = sum(i * i for i in range(10000))
{em}""",
            "javascript": f"""{mc}
const _cpuEnd = Date.now() + parseInt(process.env.FAULT_CPU_DURATION || "5000");
let _r = 0;
while (Date.now() < _cpuEnd) {{ for (let i = 0; i < 10000; i++) _r += i * i; }}
{em}""",
            "typescript": f"""{mc}
const _cpuEnd = Date.now() + parseInt(process.env.FAULT_CPU_DURATION || "5000");
let _r = 0;
while (Date.now() < _cpuEnd) {{ for (let i = 0; i < 10000; i++) _r += i * i; }}
{em}""",
            "java": f"""{mc}
long _cpuEnd = System.currentTimeMillis() + Long.parseLong(System.getenv("FAULT_CPU_DURATION") != null ? System.getenv("FAULT_CPU_DURATION") : "5000");
long _r = 0;
while (System.currentTimeMillis() < _cpuEnd) {{ for (int i = 0; i < 10000; i++) _r += (long)i * i; }}
{em}""",
            "go": f"""{mc}
import "time"
_cpuEnd := time.Now().Add(5 * time.Second)
if d := os.Getenv("FAULT_CPU_DURATION"); d != "" {{
    if parsed, err := time.ParseDuration(d); err == nil {{ _cpuEnd = time.Now().Add(parsed) }}
}}
var _r float64
for time.Now().Before(_cpuEnd) {{ for i := 0; i < 10000; i++ {{ _r += float64(i*i) }} }}
{em}""",
            "rust": f"""{mc}
use std::time::{{Duration, Instant}};
let _dur_secs: u64 = std::env::var("FAULT_CPU_DURATION").unwrap_or_else(|_| "5".to_string()).parse().unwrap_or(5);
let _end = Instant::now() + Duration::from_secs(_dur_secs);
let mut _r: f64 = 0.0;
while Instant::now() < _end {{ for i in 0..10000_i32 {{ _r += (i*i) as f64; }} }}
{em}""",
            "csharp": f"""{mc}
int _durMs = int.Parse(Environment.GetEnvironmentVariable("FAULT_CPU_DURATION") ?? "5000");
var _end = DateTime.UtcNow.AddMilliseconds(_durMs);
long _r = 0;
while (DateTime.UtcNow < _end) {{ for (int i = 0; i < 10000; i++) _r += (long)i * i; }}
{em}""",
            "ruby": f"""{mc}
_cpu_end = Time.now + (ENV['FAULT_CPU_DURATION'] || '5').to_i
_r = 0
while Time.now < _cpu_end
  10000.times {{ |i| _r += i * i }}
end
{em}""",
            "php": f"""{mc}
$_cpuEnd = microtime(true) + (int)(getenv('FAULT_CPU_DURATION') ?: 5);
$_r = 0;
while (microtime(true) < $_cpuEnd) {{ for ($i = 0; $i < 10000; $i++) {{ $_r += $i * $i; }} }}
{em}""",
            "kotlin": f"""{mc}
val _cpuEndMs = System.currentTimeMillis() + (System.getenv("FAULT_CPU_DURATION") ?: "5000").toLong()
var _r = 0L
while (System.currentTimeMillis() < _cpuEndMs) {{ for (i in 0 until 10000) {{ _r += (i * i).toLong() }} }}
{em}""",
            "swift": f"""{mc}
let _cpuDur = (ProcessInfo.processInfo.environment["FAULT_CPU_DURATION"] ?? "5")
let _cpuEnd = Date().addingTimeInterval(Double(_cpuDur) ?? 5.0)
var _r = 0
while Date() < _cpuEnd {{ for i in 0..<10000 {{ _r += i * i }} }}
{em}""",
            "cpp": f"""{mc}
#include <chrono>
auto _cpuEnd = std::chrono::steady_clock::now() + std::chrono::seconds(5);
long long _r = 0;
while (std::chrono::steady_clock::now() < _cpuEnd) {{
    for (int i = 0; i < 10000; i++) _r += (long long)i * i;
}}
{em}""",
            "zig": f"""{mc}
const std = @import("std");
const now = std.time.milliTimestamp();
const end = now + 5000;
var r: i64 = 0;
while (now < end) {{
    for (0..10000) |i| r += @as(i64, i) * @as(i64, i);
}}
{em}""",
            "vue": f"""{mc}
// CPU bottleneck injected in script section
const _cpuEnd = Date.now() + parseInt(process.env.FAULT_CPU_DURATION || "5000");
let _r = 0;
while (Date.now() < _cpuEnd) {{ for (let i = 0; i < 10000; i++) _r += i * i; }}
{em}""",
            "svelte": f"""{mc}
const _cpuEnd = Date.now() + parseInt(process.env.FAULT_CPU_DURATION || "5000");
let _r = 0;
while (Date.now() < _cpuEnd) {{ for (let i = 0; i < 10000; i++) _r += i * i; }}
{em}""",
            "dart": f"""{mc}
final _cpuEnd = DateTime.now().add(Duration(milliseconds: int.parse(Platform.environment["FAULT_CPU_DURATION"] ?? "5000")));
int _r = 0;
while (DateTime.now().isBefore(_cpuEnd)) {{ for (int i = 0; i < 10000; i++) _r += i * i; }}
{em}""",
        },
        "io-block": {
            "python": f"""{mc}
import time
import requests as _fi_requests
_delay = int(os.getenv("FAULT_IO_DELAY_MS", "3000"))
time.sleep(_delay / 1000)
{em}""",
            "javascript": f"""{mc}
const _ioDelay = parseInt(process.env.FAULT_IO_DELAY_MS || "3000");
await new Promise(r => setTimeout(r, _ioDelay));
{em}""",
            "typescript": f"""{mc}
const _ioDelay = parseInt(process.env.FAULT_IO_DELAY_MS || "3000");
await new Promise(r => setTimeout(r, _ioDelay));
{em}""",
            "java": f"""{mc}
try {{ Thread.sleep(Long.parseLong(System.getenv("FAULT_IO_DELAY_MS") != null ? System.getenv("FAULT_IO_DELAY_MS") : "3000")); }} catch (InterruptedException e) {{ Thread.currentThread().interrupt(); }}
{em}""",
            "go": f"""{mc}
import "time"
if d := os.Getenv("FAULT_IO_DELAY_MS"); d != "" {{
    if ms, err := strconv.Atoi(d); err == nil {{ time.Sleep(time.Duration(ms) * time.Millisecond) }}
}} else {{ time.Sleep(3 * time.Second) }}
{em}""",
            "rust": f"""{mc}
use std::time::Duration;
let _io_delay_ms: u64 = std::env::var("FAULT_IO_DELAY_MS").unwrap_or_else(|_| "3000".to_string()).parse().unwrap_or(3000);
std::thread::sleep(Duration::from_millis(_io_delay_ms));
{em}""",
            "csharp": f"""{mc}
int _ioDelay = int.Parse(Environment.GetEnvironmentVariable("FAULT_IO_DELAY_MS") ?? "3000");
await Task.Delay(_ioDelay);
{em}""",
            "ruby": f"""{mc}
sleep((ENV['FAULT_IO_DELAY_MS'] || '3000').to_i / 1000.0)
{em}""",
            "php": f"""{mc}
usleep((int)(getenv('FAULT_IO_DELAY_MS') ?: '3000') * 1000);
{em}""",
            "kotlin": f"""{mc}
val _ioDelayMs = (System.getenv("FAULT_IO_DELAY_MS") ?: "3000").toLong()
Thread.sleep(_ioDelayMs);
{em}""",
            "swift": f"""{mc}
let _ioDelay = (ProcessInfo.processInfo.environment["FAULT_IO_DELAY_MS"] ?? "3000")
Thread.sleep(useconds_t: UInt64(Int(Double(_ioDelay) ?? 3000.0) * 1000));
{em}""",
            "cpp": f"""{mc}
#include <thread>
#include <chrono>
int _ioDelay = atoi(std::getenv("FAULT_IO_DELAY_MS") ?: "3000");
std::this_thread::sleep_for(std::chrono::milliseconds(_ioDelay > 0 ? _ioDelay : 3000));
{em}""",
            "zig": f"""{mc}
const std = @import("std");
const ms: u64 = std.fmt.parseInt(u64, std.os.getenv("FAULT_IO_DELAY_MS") orelse "3000", 10) catch 3000;
std.time.sleep(ms * 1000000);
{em}""",
            "dart": f"""{mc}
await Future.delayed(Duration(milliseconds: int.parse(Platform.environment["FAULT_IO_DELAY_MS"] ?? "3000")));
{em}""",
        },
        "net-latency": {
            "python": f"""{mc}
import time
_delay = int(os.getenv("FAULT_NET_LATENCY_MS", "500"))
time.sleep(_delay / 1000)
{em}""",
            "javascript": f"""{mc}
const _latency = parseInt(process.env.FAULT_NET_LATENCY_MS || "500");
await new Promise(r => setTimeout(r, _latency));
{em}""",
            "typescript": f"""{mc}
const _latency = parseInt(process.env.FAULT_NET_LATENCY_MS || "500");
await new Promise(r => setTimeout(r, _latency));
{em}""",
            "java": f"""{mc}
try {{ Thread.sleep(Long.parseLong(System.getenv("FAULT_NET_LATENCY_MS") != null ? System.getenv("FAULT_NET_LATENCY_MS") : "500")); }} catch (InterruptedException e) {{ Thread.currentThread().interrupt(); }}
{em}""",
            "go": f"""{mc}
import "time"
if ms := os.Getenv("FAULT_NET_LATENCY_MS"); ms != "" {{
    if parsed, _ := strconv.Atoi(ms); _ == nil {{ time.Sleep(time.Duration(parsed) * time.Millisecond) }}
}} else {{ time.Sleep(500 * time.Millisecond) }}
{em}""",
            "rust": f"""{mc}
use std::time::Duration;
let _latency_ms: u64 = std::env::var("FAULT_NET_LATENCY_MS").unwrap_or_else(|_| "500".to_string()).parse().unwrap_or(500);
std::thread::sleep(Duration::from_millis(_latency_ms));
{em}""",
            "csharp": f"""{mc}
int _latency = int.Parse(Environment.GetEnvironmentVariable("FAULT_NET_LATENCY_MS") ?? "500");
await Task.Delay(_latency);
{em}""",
            "ruby": f"""{mc}
sleep((ENV['FAULT_NET_LATENCY_MS'] || '500').to_i / 1000.0)
{em}""",
            "php": f"""{mc}
usleep((int)(getenv('FAULT_NET_LATENCY_MS') ?: '500') * 1000);
{em}""",
            "kotlin": f"""{mc}
val _latencyMs = (System.getenv("FAULT_NET_LATENCY_MS") ?: "500").toLong()
Thread.sleep(_latencyMs);
{em}""",
            "swift": f"""{mc}
let _latency = (ProcessInfo.processInfo.environment["FAULT_NET_LATENCY_MS"] ?? "500")
Thread.sleep(useconds_t: UInt64(Int(Double(_latency) ?? 500.0) * 1000));
{em}""",
            "cpp": f"""{mc}
#include <thread><chrono>
int _lat = atoi(std::getenv("FAULT_NET_LATENCY_MS") ?: "500");
std::this_thread::sleep_for(std::chrono::milliseconds(_lat > 0 ? _lat : 500));
{em}""",
            "dart": f"""{mc}
await Future.delayed(Duration(milliseconds: int.parse(Platform.environment["FAULT_NET_LATENCY_MS"] ?? "500")));
{em}""",
        },
        "concurrency": {
            "python": f"""{mc}
import threading, time
_lock = threading.Lock()
_lockHoldMs = float(os.getenv("FAULT_LOCK_HOLD_MS", "100")) / 1000
with _lock:
    time.sleep(_lockHoldMs)
{em}""",
            "javascript": f"""{mc}
// Concurrency bottleneck: mutex held for FAULT_LOCK_HOLD_MS
const _lockHoldMs = parseInt(process.env.FAULT_LOCK_HOLD_MS || "100");
await new Promise(r => setTimeout(r, _lockHoldMs));
{em}""",
            "typescript": f"""{mc}
const _lockHoldMs = parseInt(process.env.FAULT_LOCK_HOLD_MS || "100");
await new Promise(r => setTimeout(r, _lockHoldMs));
{em}""",
            "java": f"""{mc}
import java.util.concurrent.locks.ReentrantLock;
static final ReentrantLock _lock = new ReentrantLock();
{{
    long _holdMs = Long.parseLong(System.getenv("FAULT_LOCK_HOLD_MS") != null ? System.getenv("FAULT_LOCK_HOLD_MS") : "100");
    _lock.lock();
    try {{ Thread.sleep(_holdMs); }} catch (InterruptedException e) {{ Thread.currentThread().interrupt(); }} finally {{ _lock.unlock(); }}
}}
{em}""",
            "go": f"""{mc}
import "sync"
var _mu sync.Mutex
_holdMs := 100
if h := os.Getenv("FAULT_LOCK_HOLD_MS"); h != "" {{
    if parsed, err := time.ParseDuration(h + "ms"); err == nil {{ _holdMs = int(parsed.Milliseconds()) }}
}}
_mu.Lock()
time.Sleep(time.Duration(_holdMs) * time.Millisecond)
_mu.Unlock()
{em}""",
            "rust": f"""{mc}
use std::sync::Mutex;
lazy_static::lazy_static! {{ static ref _MU: Mutex<()> = Mutex::new(()); }}
let _hold_ms: u64 = std::env::var("FAULT_LOCK_HOLD_MS").unwrap_or_else(|_| "100".to_string()).parse().unwrap_or(100);
let _guard = _MU.lock().unwrap();
std::thread::sleep(std::time::Duration::from_millis(_hold_ms));
{em}""",
            "csharp": f"""{mc}
private static readonly object _lock = new object();
int _holdMs = int.Parse(Environment.GetEnvironmentVariable("FAULT_LOCK_HOLD_MS") ?? "100");
lock (_lock) {{ Thread.Sleep(_holdMs); }}
{em}""",
            "ruby": f"""{mc}
@_mutex ||= Mutex.new
_hold = (ENV['FAULT_LOCK_HOLD_MS'] || '100').to_i / 1000.0
@_mutex.synchronize {{ sleep(_hold) }}
{em}""",
            "php": f"""{mc}
$fp = fopen('/tmp/fault_lock_', 'a');
if (flock($fp, LOCK_EX)) {{
    usleep((int)(getenv('FAULT_LOCK_HOLD_MS') ?: '100') * 1000);
    flock($fp, LOCK_UN);
}}
fclose($fp);
{em}""",
            "kotlin": f"""{mc}
val _lockHoldMs = (System.getenv("FAULT_LOCK_HOLD_MS") ?: "100").toLong()
java.util.concurrent.locks.ReentrantLock().use {{ l ->
    l.lock()
    try {{ Thread.sleep(_lockHoldMs) }} finally {{ l.unlock() }}
}}
{em}""",
            "swift": f"""{mc}
let _holdMs = (ProcessInfo.processInfo.environment["FAULT_LOCK_HOLD_MS"] ?? "100")
Thread.sleep(useconds_t: UInt64(Int(Double(_holdMs) ?? 100.0) * 1000));
{em}""",
            "cpp": f"""{mc}
#include <mutex>
static std::mutex _mu;
int _holdMs = atoi(std::getenv("FAULT_LOCK_HOLD_MS") ?: "100");
{{ std::lock_guard<std::mutex> _l(_mu); std::this_thread::sleep_for(std::chrono::milliseconds(_holdMs)); }}
{em}""",
            "dart": f"""{mc}
int _holdMs = int.parse(Platform.environment["FAULT_LOCK_HOLD_MS"] ?? "100");
await Future.delayed(Duration(milliseconds: _holdMs));
{em}""",
        },
        "mem-leak": {
            "python": f"""{mc}
import os
_leak = os.getenv("FAULT_MEM_LEAK", "false")
if _leak == "true":
    _chunkMb = int(os.getenv("FAULT_LEAK_CHUNK_MB", "10"))
    __import__('sys')._leak_cache.append(bytearray(_chunkMb * 1024 * 1024))
{em}""",
            "javascript": f"""{mc}
if (process.env.FAULT_MEM_LEAK === "true") {{
    const _chunkMb = parseInt(process.env.FAULT_LEAK_CHUNK_MB || "10");
    global._faultLeakCache = global._faultLeakCache || [];
    global._faultLeakCache.push(Buffer.alloc(_chunkMb * 1024 * 1024));
}}
{em}""",
            "typescript": f"""{mc}
if (process.env.FAULT_MEM_LEAK === "true") {{
    const _chunkMb = parseInt(process.env.FAULT_LEAK_CHUNK_MB || "10");
    (global as any)._faultLeakCache = (global as any)._faultLeakCache || [];
    (global as any)._faultLeakCache.push(Buffer.alloc(_chunkMb * 1024 * 1024));
}}
{em}""",
            "java": f"""{mc}
if ("true".equals(System.getenv("FAULT_MEM_LEAK"))) {{
    int _chunkMb = Integer.parseInt(System.getenv("FAULT_LEAK_CHUNK_MB") != null ? System.getenv("FAULT_LEAK_CHUNK_MB") : "10");
    java.nio.ByteBuffer _bb = java.nio.ByteBuffer.allocateDirect(_chunkMb * 1024 * 1024);
}}
{em}""",
            "go": f"""{mc}
if os.Getenv("FAULT_MEM_LEAK") == "true" {{
    chunkMb := 10
    if c := os.Getenv("FAULT_LEAK_CHUNK_MB"); c != "" {{
        if parsed, err := strconv.Atoi(c); err == nil {{ chunkMb = parsed }}
    }}
    _leakSlice = append(_leakSlice, make([]byte, chunkMb*1024*1024))
}}
{em}""",
            "rust": f"""{mc}
if std::env::var("FAULT_MEM_LEAK").unwrap_or_default() == "true" {{
    let chunk_mb: usize = std::env::var("FAULT_LEAK_CHUNK_MB").unwrap_or_else(|_| "10".to_string()).parse().unwrap_or(10);
    unsafe {{ LEAK_CACHE.push_back(vec![0u8; chunk_mb * 1024 * 1024]); }}
}}
{em}""",
            "csharp": f"""{mc}
if (Environment.GetEnvironmentVariable("FAULT_MEM_LEAK") == "true") {{
    int _chunkMb = int.Parse(Environment.GetEnvironmentVariable("FAULT_LEAK_CHUNK_MB") ?? "10");
    _memoryHolder.Add(new byte[_chunkMb * 1024 * 1024]);
}}
{em}""",
            "ruby": f"""{mc}
if ENV['FAULT_MEM_LEAK'] == 'true'
  @_leak_cache ||= []
  chunk = "\x00" * ((ENV['FAULT_LEAK_CHUNK_MB'] || '10').to_i * 1024 * 1024)
  @_leak_cache << chunk
end
{em}""",
            "php": f"""{mc}
if (getenv('FAULT_MEM_LEAK') === 'true') {{
    $chunkMb = (int)(getenv('FAULT_LEAK_CHUNK_MB') ?: 10);
    $_GLOBALS['_fault_mem'][] = str_repeat("\\x00", $chunkMb * 1024 * 1024);
}}
{em}""",
            "kotlin": f"""{mc}
if (System.getenv("FAULT_MEM_LEAK") == "true") {{
    val chunkMb = (System.getenv("FAULT_LEAK_CHUNK_MB") ?: "10").toInt()
    _memoryLeakHolder.add(ByteArray(chunkMb * 1024 * 1024))
}}
{em}""",
            "swift": f"""{mc}
if ProcessInfo.processInfo.environment["FAULT_MEM_LEAK"] == "true" {{
    let chunkMb = Int(ProcessInfo.processInfo.environment["FAULT_LEAK_CHUNK_MB"] ?? "10") ?? 10
    _leakStorage.append([UInt8](repeating: 0, count: chunkMb * 1024 * 1024))
}}
{em}""",
            "cpp": f"""{mc}
if (std::getenv("FAULT_MEM_LEAK") && std::string(std::getenv("FAULT_MEM_LEAK")) == "true") {{
    int _chunkMb = 10;
    if (auto p = std::getenv("FAULT_LEAK_CHUNK_MB")) _chunkMb = atoi(p);
    _leakVector.emplace_back(_chunkMb * 1024 * 1024, 0);
}}
{em}""",
            "dart": f"""{mc}
if (Platform.environment["FAULT_MEM_LEAK"] == "true") {{
    final chunkMb = int.parse(Platform.environment["FAULT_LEAK_CHUNK_MB"] ?? "10");
    _leakHolder.add(List.filled(chunkMb * 1024 * 1024, 0));
}}
{em}""",
        },
        "ratelimit": {
            "python": f"""{mc}
import time, os
_limit = int(os.getenv("FAULT_RATE_LIMIT", "10"))
_now = time.time()
__import__('sys')._rate_cache = getattr(__import__('sys'), '_rate_cache', [])
__import__('sys')._rate_cache = [t for t in __import__('sys')._rate_cache if _now - t < 1]
if len(__import__('sys')._rate_cache) >= _limit:
    raise Exception(f"[{MARKER}] Rate limit: {{_limit}}/s exceeded")
__import__('sys')._rate_cache.append(_now)
{em}""",
            "javascript": f"""{mc}
// Rate limit: {os.getenv("FAULT_RATE_LIMIT", "10")} req/s
const _rlLimit = parseInt(process.env.FAULT_RATE_LIMIT || "10");
const _now = Date.now();
if (!global._rlMap) global._rlMap = {{}};
global._rlMap[_reqKey] = (global._rlMap[_reqKey] || []).filter(t => _now - t < 1000);
if (global._rlMap[_reqKey].length >= _rlLimit) throw new Error(`[FAULT] Rate limit: ${{_rlLimit}}/s`);
global._rlMap[_reqKey].push(_now);
{em}""",
            "go": f"""{mc}
_mu2.Lock()
defer _mu2.Unlock()
_limit := 10
if l := os.Getenv("FAULT_RATE_LIMIT"); l != "" {{ if parsed, err := strconv.Atoi(l); err == nil {{ _limit = parsed }} }}
_now := time.Now()
_rateWindow = append(_rateWindow, _now)
_cutoff := _now.Add(-time.Second)
var _newWindow []time.Time
for _, t := range _rateWindow {{ if t.After(_cutoff) {{ _newWindow = append(_newWindow, t) }} }}
_rateWindow = _newWindow
if len(_rateWindow) > _limit {{ panic("[FAULT] rate limit exceeded") }}
{em}""",
        },
        "circuit-breaker": {
            "python": f"""{mc}
import os, time
if os.getenv("FAULT_CIRCUIT_BREAKER", "false") == "true":
    raise Exception(f"[{MARKER}] Circuit open — FAULT_CIRCUIT_BREAKER triggered")
{em}""",
            "javascript": f"""{mc}
if (process.env.FAULT_CIRCUIT_BREAKER === "true") {{
    throw new Error(`[FAULT] Circuit breaker OPEN — FAULT_CIRCUIT_BREAKER triggered`);
}}
{em}""",
            "go": f"""{mc}
if os.Getenv("FAULT_CIRCUIT_BREAKER") == "true" {{
    panic("FAULT circuit breaker OPEN")
}}
{em}""",
        },
        "oom": {
            "python": f"""{mc}
import os
if os.getenv("FAULT_OOM", "false") == "true":
    _chunkMb = int(os.getenv("FAULT_OOM_CHUNK_MB", "50"))
    __import__('sys')._oom_cache = getattr(__import__('sys'), '_oom_cache', [])
    while True:
        __import__('sys')._oom_cache.append(bytearray(_chunkMb * 1024 * 1024))
{em}""",
            "javascript": f"""{mc}
if (process.env.FAULT_OOM === "true") {{
    const _chunkMb = parseInt(process.env.FAULT_OOM_CHUNK_MB || "50");
    while(true) {{ global._oomCache = global._oomCache || []; global._oomCache.push(Buffer.alloc(_chunkMb * 1024 * 1024)); }}
}}
{em}""",
            "go": f"""{mc}
if os.Getenv("FAULT_OOM") == "true" {{
    chunkMb := 50
    if c := os.Getenv("FAULT_OOM_CHUNK_MB"); c != "" {{ if parsed, err := strconv.Atoi(c); err == nil {{ chunkMb = parsed }} }}
    for {{ _oomSlice = append(_oomSlice, make([]byte, chunkMb*1024*1024)) }}
}}
{em}""",
        },
        "all": {
            "python": f"""{mc}
# ALL bottleneck injection — FAULT_INJECT_ENABLED=true activates all patterns below
# See references/bottleneck-patterns.md for full implementations
{em}""",
        },
    }

    lang_blocks = blocks.get(bottleneck_type, {})
    return lang_blocks.get(lang, f"{mc}\n# TODO: implement {bottleneck_type} for {lang}\n{em}")


# ============================================================
# 核心注入逻辑
# ============================================================

def inject_into_file(filepath: str, bottleneck_types: list, enable: bool = False) -> dict:
    """对单个文件执行注入，返回注入报告"""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    ext = Path(filepath).suffix
    lang = EXT_TO_LANG.get(ext, "javascript")

    points = find_injection_points(content, lang)
    report = {
        "file": filepath,
        "language": lang,
        "injected_at": datetime.now().isoformat(),
        "bottleneck_types": bottleneck_types,
        "injection_points": [],
        "env_vars": [],
    }

    lines = content.split("\n")
    # 按行号从大到小排序，这样插入不会影响前面的行号
    points_sorted = sorted(points, key=lambda p: p["line"], reverse=True)

    for btype in bottleneck_types:
        env_var = BOTTLENECK_ENV_MAP.get(btype, f"FAULT_{btype.upper()}")
        report["env_vars"].append(env_var)

        for point in points_sorted:
            line_no = point["line"]
            block = build_injection_block(lang, btype, env_var)

            # 插入到函数定义后的第一行
            if line_no - 1 < len(lines):
                indent = point["indentation"]
                block_lines = [indent + l for l in block.split("\n")]
                lines.insert(line_no, "\n".join(block_lines))

                report["injection_points"].append({
                    "bottleneck_type": btype,
                    "env_var": env_var,
                    "line": line_no,
                    "signature": point["signature"],
                })
                break  # 每个类型只注入第一个匹配点

    new_content = "\n".join(lines)

    # 写入文件
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    return report


def clean_injection(filepath: str) -> dict:
    """清理文件中的所有注入点"""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    new_lines = []
    inside_block = False
    removed = []

    for i, line in enumerate(lines):
        if f"[{MARKER}]" in line:
            inside_block = True
            removed.append(i + 1)
            continue
        if "[/FAULT_INJECT]" in line:
            inside_block = False
            continue
        if not inside_block:
            new_lines.append(line)

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return {"file": filepath, "removed_lines": removed, "count": len(removed)}


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Fault Injection CLI — 自动向代码文件注入性能瓶颈",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 注入 CPU 瓶颈
  python3 auto_inject.py app.py --type cpu

  # 注入多个瓶颈
  python3 auto_inject.py api.py --type cpu --type io-block --type net-latency

  # 注入所有类型
  python3 auto_inject.py server.py --type all

  # 直接启用（不依赖环境变量）
  python3 auto_inject.py app.py --type cpu --enable

  # 生成注入报告
  python3 auto_inject.py app.py --type cpu --type mem-leak --report

  # 清理注入点
  python3 auto_inject.py app.py --clean

  # 批量注入
  python3 auto_inject.py src/ --type ratelimit --report
        """
    )
    parser.add_argument("target", help="目标文件或目录路径")
    parser.add_argument("--type", "-t", action="append", default=[],
                        choices=["cpu", "mem-leak", "io-block", "net-latency",
                                 "concurrency", "db-n-plus-one", "ratelimit",
                                 "circuit-breaker", "oom", "all"],
                        help="瓶颈注入类型（可多次指定）")
    parser.add_argument("--enable", "-e", action="store_true",
                        help="直接启用注入（不依赖环境变量，默认关闭）")
    parser.add_argument("--report", "-r", action="store_true",
                        help="生成 JSON 注入报告")
    parser.add_argument("--report-output", "-o", default="fault-injection-report.json",
                        help="报告输出路径（默认: fault-injection-report.json）")
    parser.add_argument("--clean", "-c", action="store_true",
                        help="清理文件中的注入点而非注入")
    parser.add_argument("--lang", "-l", choices=list(set(EXT_TO_LANG.values())),
                        help="强制指定语言（默认从文件扩展名推断）")

    args = parser.parse_args()

    if not args.type and not args.clean:
        parser.print_help()
        print("\n⚠️  必须指定 --type 或 --clean")
        sys.exit(1)

    target = Path(args.target)
    reports = []

    if target.is_dir():
        # 递归处理目录下所有支持的文件
        files = []
        for ext in EXT_TO_LANG:
            files.extend(target.rglob(f"*{ext}"))
        files = list(set(files))
    else:
        files = [target]

    if not files:
        print(f"⚠️  未找到任何支持的文件: {target}")
        sys.exit(1)

    print(f"\n🔍 找到 {len(files)} 个文件\n")

    for f in files:
        try:
            if args.clean:
                result = clean_injection(str(f))
                print(f"  ✅ 清理完成 [{result['count']} 处]: {f}")
                reports.append(result)
            else:
                result = inject_into_file(str(f), args.type, args.enable)
                print(f"  ✅ 注入完成 [{len(result['injection_points'])} 处]: {f}")
                for pt in result["injection_points"]:
                    print(f"     - {pt['bottleneck_type']} @ line {pt['line']}: {pt['signature'][:60]}")
                reports.append(result)
        except Exception as e:
            print(f"  ❌ 失败 [{f}]: {e}")

    if args.report and reports:
        report_obj = {
            "generated_at": datetime.now().isoformat(),
            "total_files": len(reports),
            "files": reports,
        }
        with open(args.report_output, "w", encoding="utf-8") as f:
            json.dump(report_obj, f, indent=2, ensure_ascii=False)
        print(f"\n📄 报告已生成: {args.report_output}")

    print("\n🎯 环境变量速查:")
    all_vars = set()
    for r in reports:
        all_vars.update(r.get("env_vars", []))
    for v in sorted(all_vars):
        print(f"   {v}=true")

if __name__ == "__main__":
    main()
