# Rust 系统级开发规程

来源基准：onsails/skills 的 rust-dev（FAIL FAST 标准、workspace 架构、错误链保留）+ 实战补齐。

## 一、错误处理（最硬的一条）

**快速判定：看到 `if let Err` 或 `match ... Err` 却没有 `return Err` 也没有 `?`，就是 bug——错误被吞了。**

- 库 crate：`thiserror` 定义枚举错误，一个变体一种可区分原因，禁止 `Other(String)` 兜底。
- 应用/CLI：`anyhow::Result` + `.context("做什么时失败")`，错误信息带动作语义。
- 保链：`#[from]` / `#[source]` 保留底层错误，不要 `map_err(|e| anyhow!("{}", e))` 把链拍平。
- `unwrap()` 只允许在测试、`const` 初始化、以及能证明的不变量旁（附 SAFETY/理由注释）。生产代码用 `expect("不可能发生的原因")`。
- `panic!` 不进库的公开 API；库只 return Err。
- 可选错误不当错误：`Option` 表达"可能没有"，`Result` 表达"可能失败"，不要混用。

## 二、Workspace 与模块

- 多 crate 布局：`crates/core`（纯逻辑，无 IO）、`crates/io`、`crates/cli`（bin）。依赖单向：cli → io → core，**不许回指**。
- 版本统一在根 `Cargo.toml` 的 `[workspace.dependencies]`，各 crate `dep = { workspace = true }`，禁止各写一个版本。
- feature flags：默认关掉重依赖（如 `serde`、`tls`）；`default = []`，避免下游被拖进不需要的东西。
- 拆分阈值：单文件 > 500 行，或测试代码占文件 50%+ → 拆（测试移到 `tests/` 或子模块）。
- `pub` 最小化：能 `pub(crate)` 就别 `pub`。

## 三、所有权与性能

- 参数优先借用：`&str` 而非 `String`，`&[T]` 而非 `Vec<T>`；需要有时拥有用 `Cow<'_, str>`。
- 热路径不 clone：先测量再优化，`cargo build --release` + `perf`/`criterion`；不要为了躲借用检查器到处 `clone()`。
- 迭代器优先于索引循环；`Vec::with_capacity` 预分配；避免 `collect()` 到中间 Vec 再 `map()`。
- `Arc<Mutex<T>>` 是起点不是终点：读多写少用 `RwLock`；跨线程消息传递用 channel 而不是共享可变状态。

## 四、unsafe 门槛

- 每个 `unsafe` 块必须有 `// SAFETY:` 注释，写明"为什么这里的不变量成立"。
- 不变量无法用一段话讲清 → 说明你不该用 unsafe。
- FFI 边界全部视为 unsafe：指针判空、长度校验、生命周期不得超越调用方。

## 五、异步

- `async` 里禁止阻塞调用（`std::fs`、`std::thread::sleep`）；用 `tokio::fs` / `spawn_blocking`。
- 跨 `await` 持有 `std::sync::MutexGuard` → 编译报错或死锁风险，改 `tokio::sync::Mutex`。
- `select!` 分支必须可取消安全，否则用 `spawn` + `JoinHandle`。

## 六、与 Android / Kotlin 的 FFI

- 导出：`#[no_mangle] pub extern "C" fn java_pkg_Class_method(...)`，或直接用 `jni` crate 的 `JNIEnv`。
- **panic 绝不跨 FFI 边界**：函数体外层 `std::panic::catch_unwind`，把 panic 转成错误码或 Java 异常（`env.throw_new`）。
- 目标三元组：`aarch64-linux-android`（另有 `armv7`、`x86_64`）；用 `cargo-ndk` 打包进 `jniLibs/<abi>/lib*.so`。
- 传字符串用 `JString` → `env.get_string()` → Rust 侧持有；返回时 `env.new_string()`。
- 跨语言对象用 `Box::into_raw` 出句柄（`jlong`），配套 `Box::from_raw` 释放；重复释放要在 Kotlin 侧置 0 防御。

## 七、门禁与自检清单

- [ ] `cargo clippy -- -D warnings` 通过
- [ ] `cargo fmt --check` 通过
- [ ] 没有裸 `unwrap()`（除测试与带理由的不变量）
- [ ] 错误链未被拍平（`source()` 可追溯到底层）
- [ ] 公开 API 的错误类型是可匹配的枚举，不是字符串
- [ ] workspace 依赖版本统一，无重复版本
- [ ] 每个 `unsafe` 有 SAFETY 注释
- [ ] FFI 入口有 `catch_unwind`