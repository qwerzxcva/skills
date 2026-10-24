# Android NDK / JNI 原生开发规程

来源基准：android-native-bootstrap（SKILL.md 的 JNI/CMake/ABI 决断与 Failure Handling 表）+ 实战补齐。

## 一、工程骨架（最小可用）

`app/build.gradle.kts`：
```kotlin
android {
  ndkVersion = "27.0.12077973"          // 与 SDK Manager 实装版本一致，不要写死未知版本
  defaultConfig {
    externalNativeBuild { cmake { cppFlags += "-std=c++20" } }
    ndk { abiFilters += listOf("arm64-v8a") }   // 先只出一个 ABI，体积与构建时间减半
  }
  externalNativeBuild { cmake { path = file("src/main/cpp/CMakeLists.txt") } }
}
```

`CMakeLists.txt`：
```cmake
cmake_minimum_required(VERSION 3.22.1)
project(nativelib LANGUAGES CXX)
add_library(nativelib SHARED native-lib.cpp)
target_link_libraries(nativelib android log)
```

加载：`System.loadLibrary("nativelib")`（名字去 `lib` 前缀与 `.so` 后缀）。

## 二、JNI 符号与签名

- 静态注册符号名：`Java_<包名下划线化>_<类名>_<方法名>`，包名 `com.a.b` → `Java_com_a_b_MyClass_method`。名字里有 `_` 或重载时必须用 `RegisterNatives` 动态注册。
- 签名速查：`Z`boolean `B`byte `C`char `S`short `I`int `J`long `F`float `D`double `V`void `Ljava/lang/String;` `[I` `[Ljava/lang/Object;`
- 优先 `RegisterNatives`：避免符号名漂移，且能一次性校验签名。
- `extern "C"` + `JNIEXPORT`/`JNICALL` 不可省；C++ 里漏 `extern "C"` → 链接期找不到符号。

## 三、引用与线程（崩溃主因）

- **局部引用**只在当前 native 调用栈内有效。循环里创建大量对象要 `DeleteLocalRef`，或让 JVM 自动清理（有限额，约 512）。
- **全局引用**跨调用/跨线程持有 Java 对象必须 `NewGlobalRef`，不用时 `DeleteGlobalRef`，否则泄漏。
- **线程**：native 线程访问 JVM 必须 `AttachCurrentThread` 拿 `JNIEnv`，退出前 `DetachCurrentThread`；`JNIEnv*` 不能跨线程缓存。
- `JNI_OnLoad` 里保存 `JavaVM*`（`env->GetJavaVM(&vm)`），后续线程用它 attach。
- 从 native 回调 Java：`AttachCurrentThread` → `CallVoidMethod` → `DetachCurrentThread`；异常需 `ExceptionCheck`/`ExceptionDescribe` 处理，不能忽略。

## 四、跨语言边界纪律

- **panic / 异常不穿越边界**：C++ 异常必须在 JNI 函数内 catch 并转成 Java 异常（`ThrowNew`）或返回错误码。
- 字符串转换：`GetStringUTFChars` 必须配 `ReleaseStringUTFChars`；高频转换用 `GetStringCritical` 或改用 byte[] 传参。
- 大数组：用 `GetPrimitiveArrayCritical` 期间不做任何 JNI 调用（会死锁）。
- 所有权：native 对象用 `long` 句柄 + `nativeDestroy()` 显式释放；不要依赖 finalizer。
- 每帧路径禁止分配：预分配 buffer，避免在渲染/音频回调里 `new`。

## 五、排错对照表

| 现象 | 定位顺序 |
|---|---|
| `UnsatisfiedLinkError: dlopen failed` | ABI 是否匹配设备 (`abiFilters`) → `.so` 是否打进 APK (`unzip -l`) → 依赖的系统库版本 |
| `UnsatisfiedLinkError: No implementation found` | 符号名（包名/类名/下划线）→ 是否 `extern "C"` → 是否被 `static` → 重载需 `RegisterNatives` |
| CMake 找不到源文件 | 检查 `CMakeLists.txt` 里相对路径（相对于该 CMakeLists 所在目录）→ 再动 Gradle |
| `abiFilters` 生效但产物缺失 | NDK 是否安装该 ABI → 查看 `build/intermediates/cxx` → Gradle 变体是否被裁剪 |
| 升级 AGP/NDK 后构建失败 | **只回滚你改的那一项版本**，回到仓库锁定的版本组合，不要连坐降级 |
| 随机 SIGSEGV | 局部引用溢出 → 线程未 attach → 释放后使用（`-fsanitize=address` 调试构建） |

## 六、原生模块审查清单

- [ ] `abiFilters` 有明确理由（默认只要 `arm64-v8a`）
- [ ] 所有 `Get*Chars` 都有对应 `Release*`
- [ ] 所有 `NewGlobalRef` 都有 `DeleteGlobalRef`
- [ ] native 回调路径有 `ExceptionCheck`
- [ ] `long` 句柄有对应 `nativeDestroy`，并处理重复释放（置 0 + 判空）
- [ ] 热点路径无分配、无 `JNIEnv` 跨线程缓存
- [ ] Release 构建开 `-O2` 且保留符号表用于 native 崩溃栈还原（`ndk-stack`）
- [ ] CMake 与 Gradle 的 C++ 标准一致