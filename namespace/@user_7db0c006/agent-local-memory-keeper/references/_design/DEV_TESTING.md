# 测试协议与「结论先取证」铁律（开发者 / 维护者内部参考）

> ⚠️ **本文件是开发者 / 维护者内部参考，普通用户无需阅读。**
> 它规定 skill 自带验证组件怎么跑、以及文档/发版断言的纪律。普通用户请回 `SKILL.md` 十、深入阅读 找对应文档。

> ⚠️ **测试套件位置（必读）**：本节列出的 `regression_v390.py` / `deep_sim_test.py` / `test_op_consistency.py`
 / `p1p2_tests.py` / `keeper_daemon/_selftest.py` **均维护在 keeper 开发实验室（非本发布包）**，经 `.skillhubignore` 刻意排除、不随 SkillHub 发布包发布（保持发布包精简，且测试需真实记忆库 + fastembed 方能跑）。**发版前请从开发实验室副本运行这些套件**；请勿在已安装的技能目录（如 `~/.workbuddy/skills/agent-local-memory-keeper`）直接 `python scripts/verify_claims.py`（会报文件不存在）。**例外：`scripts/verify_claims.py` 随发布包自带**——在已安装技能目录下直接
`python scripts/verify_claims.py` 即可跑（实测 20 条 claim 全绿）；若报文件不存在，
先确认当前工作目录是技能根目录。发布包内自带门禁为
`scripts/publish_gate.py` + `scripts/run_gate.py`。

---

## 一、铁律 · 结论先取证（verify-before-conclude）

本 skill 反复踩过两类「凭文字下结论」的坑：
1. 本地 `_meta.json`/`_skillhub_meta.json` 写着某版本就以为「已发布」，但本地 meta 会滞后（如发布后 `_meta.json` 仍显示上一版），发布是否真正落地须以集中账本 + SkillHub live `latestVersion` 取证（平台无 set-current API，但发布后 live 通常自动跟随，仅当 `install`/搜索仍拉旧版时才去后台把版本设为 current）。
2. 报告/SKILL.md 文字声称「配置集中在 X 文件」，实际 grep 在 Y 处。

**规则**：任何「功能集中在 X / 已发布 / 版本是 Y」类断言，**必须先 grep 代码或查 live API 取证，禁止凭报告 / 印象 / 本地 meta 断言**。

**可执行化身**：`scripts/verify_claims.py` 的 `config_doc_matches_code` 静态检查强制「SKILL.md 配置段列举的键 ↔ `KEEPER_DEFAULTS` 完全对称」——文档宣称的开关必须能被代码 grep 到。发版前必须跑 `python scripts/verify_claims.py`（全绿才允许发）。

---

## 二、测试协议（防"连环 verify"陷阱）

文档里宣传的命令/参数，必须能用 **本 skill 自带的 `verify_claims.py`** 一次性批量断言。任何"文档写了但代码没做"的虚标，verify_claims 会立刻报 FAIL。

```bash
# 跑全部内置 claim（覆盖关键 API + 重要参数）
python scripts/verify_claims.py

# 跑子集（用 id 子串过滤）
python scripts/verify_claims.py --filter "max-age|review|key-hint"

# 跑外部自定义 claim（CI 集成场景）
python scripts/verify_claims.py --claims /path/to/custom.json

# 保留测试库（调试用）
python scripts/verify_claims.py --keep --root /tmp/my_test
```

**配套回归套件**：

| 入口 | 用途 | 触发时机 |
|---|---|---|
| `python -m unittest discover -s scripts/tests -p "test_*.py"` | **主力回归套件**（`scripts/tests/` 下 29 个用例文件，unittest 风格，零第三方依赖） | 改动代码后；发版前必跑 |
| `python scripts/verify_claims.py` | 一条 claim = 一次跑 + 一次断言 → 结构化 verdict JSON | 文档改动后；发版前必跑 |
| `python mem_bridge.py selftest` | WB↔keeper 桥接回归（隔离库，18 项） | 改动 mem_bridge / 发版前必跑 |
| `python keeper_daemon/_selftest.py` | daemon 冷/热召回 + 自愈（ALL PASS） | 改动 daemon 后；发版前建议跑 |
| `python scripts/publish_gate.py` | 发布前门禁（三道：cookbook / tests / claims） | 发版前必跑 |
| `python scripts/publish_gate.py --only tests` | 只跑集成测试（定位「只有 tests 红」） | 门禁红灯在 tests 时 |
| `python scripts/publish_gate.py --timeout 5400` | 统一覆盖各闸门超时（默认分档：cookbook 300 / tests 3600 / claims 900） | 机器极慢时 |

> ⚠️ **已移除的旧套件（2026-09-05 核对）**：`regression_v390.py`、`deep_sim_test.py`、
> `test_op_consistency.py`、`p1p2_tests.py` 四个脚本**当前已不存在于本 skill**（早期版本遗留，
> 后未随重构迁移）。此前本表仍把它们列为「发版前必跑」，属**死链**——照着跑会直接报
> `No such file`。其覆盖面已由 `scripts/tests/` 下的新用例承接（含 contract / hook /
> import / 并发写 / 路径穿越 / 敏感扫描等）。若在 CHANGELOG 旧条目里看到这些文件名，
> 那是历史记录，不代表文件仍存在。

**协议硬规则**：
1. **一条 claim = 一次跑 + 一次断言**。脚本输出 `{"ok": bool, "n_pass": int, "n_fail": int, "claims": [...]}` 结构化 verdict，**禁止**对 verdict 再 grep / 再 read / 再 verify。
2. **用 python -c / json.load 在脚本内消费**。本 skill 的脚本对 JSON 输出做了 `json.loads` + 字段路径断言（如 `assert_json_has(d, "entries.0.summary", "foo")`），避免 shell 层 `grep -o` 漏字段。
3. **失败时一次性出 `actual` 字段**（前 200 字符），定位用；不要因为"actual 不够清楚"再跑一次。
4. **环境隔离**：默认测试库走唯一临时目录，跑完自动删；`--keep` 才保留（不污染真实记忆）。
5. **CI/发版前**：必须全部 0 FAIL；任何 FAIL 视为 P0 阻塞。

**发版前检查清单**（2026-09-05 核对为**实际可跑**的命令，旧清单里的 4 个脚本已不存在）：
```bash
# 1) 主力回归：scripts/tests/ 下 29 个用例文件
python -m unittest discover -s scripts/tests -p "test_*.py"

# 2) 桥接回归（隔离库，不碰真实记忆）
python mem_bridge.py selftest

# 3) 文档 claim 校验
python scripts/verify_claims.py

# 4) daemon 自检（改动 daemon 时）
python keeper_daemon/_selftest.py

# 5) 发布门禁
python scripts/publish_gate.py
```
全部 0 失败方可发版；任一 FAIL 视为 P0 阻塞。
