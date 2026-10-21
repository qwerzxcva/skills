---
name: app-android-build
description: "泊聆 APP 原生重写工程（APP_android，Kotlin/Compose）一条命令编译 APK 并装机。当改了 APP_android/ 下代码后需要真机验证、用户说\"编译 Android 工程装机/编译 APP_android/打包原生 APK\"时使用。触发词：编译APP_android、装机、打包APK、原生编译"
---

# APP_android 原生工程编译装机流水线

把 [APP_android/](../../../APP_android/)（原生 Kotlin/Compose 重写工程）的改动编译成 APK 并装到手机，全程命令行。

> **与 UniApp 版编译装机（HBuilderX + _native 壳 + DCloud www）的区别**：本 skill 面向 `APP_android/`（纯原生 Compose 工程），无 HBuilderX 资源生成、无 UTS 拷贝、无 DCloud www 复用那些 UniApp 特有步骤。

---

## 何时使用

- 改了 `APP_android/` 下任何源码（`.kt` / `build.gradle.kts` / `AndroidManifest.xml` / `res/`）后需要真机验证
- 用户要求"编译 APP_android""装原生包""打包 APK"

**不适用**：
- 改 UniApp 工程 `APP/` → 走 HBuilderX 本地打包流程（`APP/build-and-install.ps1`）
- 只改固件 `AIHardWare/` → 走 `idf.py build && idf.py -p COM5 flash`

---

## 直接执行

```powershell
powershell -File APP_android\build-and-install.ps1
```

只编译不装机（快速验证能否编过）：

```powershell
powershell -File APP_android\build-and-install.ps1 -SkipInstall
```

脚本依次执行，任一步失败即终止：

1. **前置校验** — wrapper jar 存在、local.properties 就绪（缺则自动生成）
2. **Gradle 编译** — `gradlew.bat assembleDebug`，回显 BUILD/错误关键行
3. **校验 APK 产物** — 确认 app-debug.apk 生成 + 时间戳
4. **adb install -r** + 校验设备 `versionName/lastUpdateTime`

---

## 必须知道的几个坑

### 1. JAVA_HOME 必须指向 JDK 17+（系统默认 java 是 1.8）

AGP 8.7.3 要求 JDK 17+，系统默认 `java` 是 1.8，直接 `gradlew` 会失败：

```
Could not resolve com.android.tools.build:gradle:8.7.3
> Dependency requires at least JVM runtime version 11. This build uses a Java 8 JVM.
```

脚本内设 `$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'`（OpenJDK 21），**只影响当前进程**。手动跑 gradlew 前也要设。

### 2. gradle-wrapper.jar 是二进制，无法由文本工具生成

首次或 wrapper jar 缺失时，从 UniApp 壳工程拷贝（两者 AGP/Gradle 版本兼容，jar 通用）：

```powershell
Copy-Item APP\_native\HBuilder-HelloUniApp\gradle\wrapper\gradle-wrapper.jar `
          APP_android\gradle\wrapper\
```

`gradlew.bat` / `gradlew` 同理拷贝（这两个是文本脚本，但直接拷最稳，避免行尾问题）。

### 3. Gradle 版本需与 AGP 匹配，用国内镜像加速

APP_android 用 **AGP 8.7.3 + Gradle 8.11.1**（与 UniApp 壳工程一致，复用 `~/.gradle/wrapper/dists/gradle-8.11.1-bin` 缓存）。`gradle-wrapper.properties` 的 `distributionUrl` 指向腾讯镜像：

```
distributionUrl=https\://mirrors.cloud.tencent.com/gradle/gradle-8.11.1-bin.zip
```

首次仍需下载大量依赖（Compose BOM/AndroidX/Retrofit/Room/Kotlin），5–10 分钟正常。

### 4. PowerShell 5.1 对 native 命令的 stderr 误报

`java -version`、`gradlew.bat` 等 native 命令的 stderr 在 PowerShell 5.1 里走 `2>&1` 会被包成 ErrorRecord，看着像报错实则成功。**判成败看 `$LASTEXITCODE` 和 "BUILD SUCCESSFUL"，不要看有没有红字。**（与 PowerShell 7+ 行为不同。）

### 5. 覆盖升级需同包名同签名

工程固定包名 `com.boling.device`（无 debug 后缀），与原 UniApp 一致以支持覆盖升级。但覆盖安装要求签名一致——若签名不匹配（`INSTALL_FAILED_UPDATE_INCOMPATIBLE`），先卸载旧包再装：

```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb uninstall com.boling.device
& $adb install -r app\build\outputs\apk\debug\app-debug.apk
```

### 6. 包名与原 UniApp 相同 → 两者不能共存

装机后原 UniApp APP 会被覆盖（同包名）。要并存认证旧版，需改 `applicationId` 或加 `applicationIdSuffix`（但那样不能覆盖升级原包，二选一）。

---

## 关键路径

| | |
|---|---|
| 工程 | `APP_android` |
| 包名 | `com.boling.device` |
| Gradle | 8.11.1（腾讯镜像） |
| AGP | 8.7.3 |
| JBR | `C:\Program Files\Android\Android Studio\jbr` (OpenJDK 21) |
| adb | `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe` |
| APK 产物 | `APP_android\app\build\outputs\apk\debug\app-debug.apk` |
| 协议规格 | [APP_android/docs/](../../../APP_android/docs/) |

---

## 验证装机结果

```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb shell dumpsys package com.boling.device | Select-String "versionName|lastUpdateTime"
```

首次装机后需在手机上授予运行时权限（蓝牙/位置/录音/相机），否则 BLE/录音功能不可用。
