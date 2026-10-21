---
name: find-skills-enhanced
slug: find-skills-enhanced
displayName: Find Skills 增强版（场景驱动技能发现）
version: "1.3.0"
summary: 场景驱动+关键词双模式的技能发现引擎，支持六层联合搜索与一键安装
description: 场景驱动+关键词双模式技能发现工具。当用户用自然语言描述场景/需求（如"我想做一个海报""帮我分析股票"），或明确说"安装技能/find skills/找个skill"时，自动从官方内置、本地已安装、SkillHub、虾评、GitHub、ClawHub 六层联合搜索并推荐最优 3 个技能（四维综合评分+星级+可视化评分条），支持多语言输出（中文/英文）、用户反馈学习（动态调整推荐权重）与一键安装。跨平台兼容（macOS/Linux/Windows）。
tags: [技能发现, 效率工具, AI工具, WorkBuddy, CodeBuddy]
license: MIT
platforms: [WorkBuddy, CodeBuddy, Claude Code, QClaw]
category: 效率工具
language: zh-CN
author: lvdez
agent_created: true
xiaping_trigger: ["AI","效率","技能","工具"]
xiaping_category: ["效率工具"]
xiaping_tags: ["AI工具","技能发现","WorkBuddy"]
xiaping_eval_strategy: developer
---

# find-skills-enhanced（场景技能匹配器）

## Overview

本技能用于**场景驱动的技能发现引擎**——用户用自然语言描述需求，系统自动理解意图，联合搜索并推荐最合适的技能。

**核心能力**：
- **场景语义理解**：自动从自然语言提取意图/领域/关键词/语言
- **六层联合搜索**：官方内置 → 本地已安装 → 本地 marketplace 缓存 → SkillHub → 虾评 → GitHub → ClawHub
- **Top 3 最优推荐**：四维综合评分（匹配度+来源权重+热度+可用性）+ 反馈分，只推荐最优 3 个
- **评分可视化**：星级 + 评分条 + 四维明细，直观展示推荐依据
- **多语言支持**：自动检测用户语言，中文/英文双语输出
- **用户反馈学习**：基于选择/安装/好评/差评动态调整后续推荐
- **一键安装**：自动检测客户端（WorkBuddy/CodeBuddy），支持所有来源安装
- **跨平台兼容**：macOS / Linux / Windows（Git Bash / WSL / PowerShell）

---

## 核心流程

### Step 1：理解用户场景

从用户的自然语言描述中提取：
1. **任务意图**：用户想做什么？
2. **领域标签**：属于哪个领域？
3. **搜索关键词**：中英文都要（用于远程搜索）
4. **用户语言**：检测用户输入语言，决定推荐结果输出语言（见下方多语言机制）

**示例**：
- "我想做一个海报" → 意图：设计/制图；领域：内容创作；关键词：poster, design, 海报, 设计
- "帮我分析今天的大盘" → 意图：股票分析；领域：金融；关键词：stock, A股, 大盘, 分析
- "Find a skill for making charts" → 意图：数据可视化；领域：数据分析；关键词：chart, visualization, 图表

---

### Step 1.5：多语言支持（语言检测 + 多语言输出）

**语言检测规则**（优先级从高到低）：
1. 用户本次输入若含中文字符 → **中文输出**
2. 用户本次输入全为英文 → **英文输出**
3. 输入混合或无法判断 → 检查系统环境变量 `LANG`/`LC_ALL`：含 `zh` 用中文，含 `en` 用英文
4. 仍无法判断 → 默认中文（本技能主要面向中文用户）

**当前支持语言**：

| 语言 | 识别特征 | 输出模板 |
|------|----------|----------|
| 中文（zh-CN） | 输入含汉字 | 中文模板（默认） |
| English（en） | 输入全为英文 | 英文模板 |

**英文模板对应关系**（输出时全部切换为英文）：

| 中文文案 | 英文文案 |
|----------|----------|
| 🔍 为你精选 Top 3 个技能 | 🔍 Top 3 skills picked for you |
| 匹配理由 | Why it fits |
| 来源 | Source |
| 可用性 | Availability |
| ⬇️ 需安装（安装：回复"安装第N个"） | ⬇️ Install (reply "install #N") |
| ✅ 无需安装直接使用 | ✅ Ready to use |
| 💡 备选：另有 N 个相关技能未上榜 | 💡 {N} more candidates (reply "show all") |
| 👉 需要我安装第几个，或调整推荐方向？ | 👉 Which one should I install, or refine the search? |
| 评分 | Score |
| 匹配度 / 来源 / 热度 / 可用性 | Match / Source / Popularity / Usability |

**多语言注意事项**：
- 搜索关键词始终**中英双语**提交，不受输出语言影响（保证搜索召回率）
- 评分、星级、推荐逻辑与语言无关，仅文案模板切换
- 远程技能的描述若为其他语言，尽量翻译成输出语言的一句话说明

---

### Step 2：三层联合搜索

#### 2.1 第一层：官方内置技能（WorkBuddy 自带，无需安装）

扫描官方内置技能目录，读取每个技能的 `name` 和 `description`：

```bash
# macOS
ls /Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/

# Windows（程序安装目录下查找）
ls "C:/Program Files/WorkBuddy/resources/builtin-skills/" 2>/dev/null || \
ls "$LOCALAPPDATA/Programs/WorkBuddy/resources/builtin-skills/" 2>/dev/null
```

> **跨平台提示**：若上列路径不存在，可用 `Glob`/`Grep` 工具在系统内搜索 `builtin-skills` 目录，或跳过本层（本地已安装 + 远程市场仍可覆盖大部分场景）。

用 `Read` 工具读取每个技能的 `SKILL.md` YAML frontmatter，与用户场景做**语义匹配**。

**匹配规则**（按优先级）：
1. 用户场景关键词直接出现在技能 description 中 → 高分
2. 技能 name 与用户意图高度相关 → 高分
3. 技能 description 与用户领域相关 → 中分

---

#### 2.2 第二层：本地已安装技能

扫描以下两个位置的已安装技能：

```bash
# 用户级技能
ls ~/.workbuddy/skills/

# 项目级技能（当前工作区）
ls .workbuddy/skills/ 2>/dev/null || echo "无项目级技能"
```

用 `Read` 工具读取每个技能的 `SKILL.md` YAML frontmatter，提取 `name` 和 `description`，与用户场景做**语义匹配**。

> **注意**：如果本地已安装技能在 Step 2.1 官方内置中也出现，去重，只保留最高优先级的记录。

---

#### 2.3 第三层：远程技能市场（完全替代 `find-skills` 的搜索能力）

**先检查本地 marketplace 缓存**（原 `find-skills` Step 5 逻辑）：

```bash
ls ~/.workbuddy/skills-marketplace/skills 2>/dev/null
```

如果缓存目录中存在与用户需求匹配的技能，直接复制安装，无需远程下载：

```bash
cp -r ~/.workbuddy/skills-marketplace/skills/<skill-folder-name> ~/.workbuddy/skills/<skill-folder-name>
```

---

**远程搜索**（原 `find-skills` Step 2/2b 逻辑）：

如果本地缓存无结果，则按以下顺序搜索远程技能市场：

---

**① SkillHub 官方市场**（主要来源，优先搜索）：
```bash
curl -s "https://lightmake.site/api/v1/search?q=<URL-encoded 中文关键词>&limit=10"
curl -s "https://lightmake.site/api/v1/search?q=<URL-encoded English keywords>&limit=10"
```

过滤 `score < 0.05` 的低相关结果。

**①b 腾讯 SkillHub CLI**（skillhub.cn，已安装 CLI 时优先）：
```bash
# 搜索技能
skillhub search <关键词>

# 安装技能
skillhub install <slug> --scope user

# 登录（发布技能需要）
skillhub login --key skh_你的Token --host https://api.skillhub.cn
```

---

**② 虾评技能市场**（中文技能重点来源）：

虾评 API Base URL：`https://xiaping.coze.com`（注意：不是 `coze.site`）

**搜索技能**：
```bash
# 搜索技能（按关键词）
curl -s "https://xiaping.coze.com/api/skills/search?q=<URL-encoded 关键词>&limit=10"

# 获取技能详情
curl -s "https://xiaping.coze.com/api/skills/<skill-id>"

# 获取技能下载链接
curl -s "https://xiaping.coze.com/api/skills/<skill-id>/download"
```

**需要先加载 `虾评指南` 技能**（路径：`~/.workbuddy/skills/虾评指南/SKILL.md`），按其中 §1.1 + §1.2 的规范执行搜索和下载。

> **重要**：虾评是中文技能的核心来源，对于中文场景的技能搜索，虾评的结果往往比 SkillHub 更相关。

---
**③ GitHub 技能仓库**（开源技能来源）：

搜索 GitHub 上包含 WorkBuddy / Claw 技能的文件。

> **认证说明**：GitHub 搜索 API 需要认证。如果环境变量 `GITHUB_TOKEN` 已设置，自动带上认证（5000次/小时）；否则使用匿名访问（60次/小时，可能不够用）。

```bash
# 如果有 GitHub Token，带上认证
if [ -n "$GITHUB_TOKEN" ]; then
  AUTH_HEADER="-H \"Authorization: Bearer $GITHUB_TOKEN\""
else
  AUTH_HEADER=""
fi

# 搜索包含 SKILL.md 的代码
curl -s $AUTH_HEADER "https://api.github.com/search/code?q=filename:SKILL.md+<关键词>&per_page=10"

# 搜索技能相关仓库
curl -s $AUTH_HEADER "https://api.github.com/search/repositories?q=<URL-encoded 关键词>+skill+in:name,description&per_page=10"
```

> **注意**：GitHub Code Search API 的 `filename:SKILL.md` 搜索需要认证才能使用。如果没有 `GITHUB_TOKEN`，退化为只搜索 repositories（仓库搜索匿名可用）。

**安装方式**：
```bash
# 从 GitHub 克隆技能仓库
git clone "https://github.com/<user>/<repo>.git" <target-skills-dir>/<skill-name>/

# 验证安装
ls <target-skills-dir>/<skill-name>/SKILL.md
```

> **注意**：GitHub 搜索结果需要人工判断是否为有效技能（检查是否包含 `SKILL.md`），因为是代码搜索，可能返回非技能文件。

---

**④ Fallback 来源**（SkillHub + 虾评 + GitHub 均无结果时使用）：
```bash
# Vercel Skills CLI
npx skills find [query]

# ClawHub
npx clawhub search [query]
```

> **重要**：远程搜索结果只作为**补充推荐**，优先级低于本地已安装技能。

---

### Step 2.4：客户端检测（安装前必须执行）

在安装任何远程技能之前，**必须先检测当前客户端**，以决定技能安装到哪个目录：

```bash
echo $__CFBundleIdentifier
```

| `__CFBundleIdentifier` 含 | 客户端 | 目标技能目录 |
|---------------------------|--------|----------------|
| `codebuddy` | CodeBuddy | `~/.codebuddy/skills/` |
| 其他/空/未设置 | WorkBuddy（默认） | `~/.workbuddy/skills/` |

**默认当作 WorkBuddy**：如果该变量为空、未设置或包含 `codebuddy` 以外的值，一律当作 WorkBuddy 处理。

**Windows 路径注意**：在 Git Bash 中 `~` 指向用户主目录（`C:\Users\<用户名>`），命令中的 `<target-skills-dir>` 写 `~/.workbuddy/skills` 即可；若执行 python/CLI 类命令需要 Windows 路径，用 `cygpath -w <posix路径>` 转换。

---

### Step 3：综合评分与 Top 3 最优推荐

将各层搜索结果合并去重后，对每个技能计算**综合评分**，筛选出**最优 3 个**推荐给用户（其余作为备选附在末尾）。

**评分公式**（总分 100 分 + 反馈分 ±15）：

```
综合评分 = 匹配度(40) + 来源权重(25) + 热度(20) + 可用性(15) + 反馈分(±8, 见 Step 5.5)
```

| 评分维度 | 满分 | 打分规则 |
|----------|------|----------|
| **匹配度** | 40 | 语义/关键词命中程度：description 直接含场景关键词 35-40；含义相关但未命中关键词 20-34；仅名称相关 10-19；弱相关 <10 |
| **来源权重** | 25 | 官方内置 25；本地已安装 22；SkillHub 官方市场 18；虾评 15；GitHub 开源 12；ClawHub/Vercel 10 |
| **热度** | 20 | 按 downloads/installs/star 分档：≥1000 计 20；≥100 计 15；≥10 计 10；<10 计 5；无数据按来源默认 8 |
| **可用性** | 15 | 本地已安装/官方内置（免安装直接用）15；有明确安装命令 12；需人工判断或认证 8；来源不稳定 5 |

**降级剔除规则**（满足任一即不进入推荐）：
- 综合评分 < 40 分（弱相关，浪费用户注意力）
- 与用户场景完全不匹配（匹配度 < 10）
- 已明确废弃/无法安装的技能

**去重规则**：
- 同一个技能在多层出现时，保留**最高来源权重**的那条记录，标注其最佳状态（如"✅ 已安装"）
- 例如：本地已安装 `AI图片生成无水印`，同时 SkillHub 也有，只保留本地记录并显示"✅ 已安装"

**推荐数量规则**：
- 默认**固定推荐 3 个**，按综合评分从高到低排列
- 若有效候选 < 3 个，则全部推荐（并说明"只找到 N 个高度匹配"）
- 若有效候选 > 3 个，展示 Top 3 + 一行"另有 N 个备选：技能A、技能B……如需查看回复'查看全部'"

---

### Step 4：输出推荐结果（Top 3 最优推荐 + 评分可视化）

**输出格式**：只展示综合评分最高的 **3 个**技能，每个带星级、**可视化评分条**、四维评分明细、推荐理由与安装指引。

**可视化约定**：
- **星级**：★★★★★ = 强烈推荐（≥80分）｜★★★★ = 推荐（≥65分）｜★★★ = 可尝试（≥50分）
- **评分条**：`████████░░ 92/100` 用实心块 `█` 表示得分比例（每 10 分一个块，满分 10 块），直观展示总分
- **四维明细**：一行内展示 4 个维度的得分（匹配/来源/热度/可用性），帮助用户理解"为什么是这个分数"

```
🔍 为你精选 Top 3 个技能（搜索范围：官方内置 + 本地已安装 + 远程市场）

【第1名】★★★★★ {技能名}
   综合评分：█████████░ 92/100
   评分明细：匹配 38/40 · 来源 25/25 · 热度 18/20 · 可用性 11/15
   一句话说明：{一句话简介}
   匹配理由：{为什么最适合这个场景——点出用户需求关键词}
   来源：{官方内置/本地已安装/SkillHub/虾评/GitHub/ClawHub}
   可用性：✅ 无需安装直接使用 / ⬇️ 需安装（安装：回复"安装第1个"）

【第2名】★★★★ {技能名}
   综合评分：███████░░░ 78/100
   评分明细：匹配 30/40 · 来源 18/25 · 热度 15/20 · 可用性 15/15
   一句话说明：{一句话简介}
   匹配理由：{与第1名的差异化定位，如"如果你需要X功能，选这个"}
   来源：{来源}
   可用性：⬇️ 需安装（安装：回复"安装第2个"）

【第3名】★★★ {技能名}
   综合评分：██████░░░░ 61/100
   评分明细：匹配 22/40 · 来源 15/25 · 热度 12/20 · 可用性 12/15
   一句话说明：{一句话简介}
   匹配理由：{适用边界，如"适合轻量/临时需求"}
   来源：{来源}
   可用性：⬇️ 需安装（安装：回复"安装第3个"）

💡 备选：另有 {N} 个相关技能未上榜（回复"查看全部"可浏览）
👉 需要我安装第几个，或调整推荐方向？
```

**评分条绘制规则**：
- 总分 100 分 → 10 个块，每个块代表 10 分
- 得分块用 `█`，未得分块用 `░`，后附数字 `{总分}/100`
- 四维明细按 `维度 得分/满分` 用 `·` 分隔，一行展示

**输出原则**：
- **宁缺毋滥**：只推荐真正匹配的技能，不为了凑 3 个而塞入弱相关项
- **差异化**：Top 3 之间尽量覆盖不同定位（轻量/专业/免费），方便用户按需选择
- **简洁**：每个技能 7-8 行以内，突出"为什么选它"而不是罗列参数
- **有行动指引**：结尾必须给出"安装第 N 个 / 查看全部 / 调整方向"的下一步选项

---

### Step 5：一键安装（如需）

如果用户选择安装远程技能，按以下流程执行：

**安装前必须执行客户端检测**（见 Step 2.4），确定目标目录 `<target-skills-dir>`。

#### 5.1 从本地 marketplace 缓存安装（优先）

如果 Step 2.3 的本地缓存检查已找到匹配技能：

```bash
cp -r ~/.workbuddy/skills-marketplace/skills/<skill-folder-name> <target-skills-dir>/<skill-folder-name>
```

验证安装：
```bash
ls <target-skills-dir>/<skill-folder-name>/SKILL.md
```

如果目标目录已存在同名技能，明确询问用户：跳过 / 替换 / 重命名。

#### 5.2 从 SkillHub 远程安装

**方式 A：腾讯 SkillHub CLI（推荐，跨平台）**：
```bash
# 安装到用户级技能目录
skillhub install <slug> --scope user --dir ~/.workbuddy/skills

# 指定版本
skillhub install <slug> --version <version> --scope user --dir ~/.workbuddy/skills
```

**方式 B：SkillHub Web API 下载**：
```bash
TMPDIR=$(mktemp -d)
curl -L -o "$TMPDIR/skill.zip" "https://lightmake.site/api/v1/download?slug=<slug>"
mkdir -p <target-skills-dir>/<slug>
unzip -o "$TMPDIR/skill.zip" -d <target-skills-dir>/<slug>
rm -rf "$TMPDIR"
ls <target-skills-dir>/<slug>/SKILL.md
```

> **Windows 提示**：Git Bash 默认无 `unzip`，可用 `tar -xf` 解压 zip（Windows 10+ 自带 tar 支持 zip）：
> ```bash
> tar -xf "$TMPDIR/skill.zip" -C <target-skills-dir>/<slug>
> ```

指定版本安装（Web API）：
```bash
curl -L -o "$TMPDIR/skill.zip" "https://lightmake.site/api/v1/download?slug=<slug>&version=<version>"
```

#### 5.3 从虾评远程安装

**先加载 `虾评指南` 技能**（路径：`~/.workbuddy/skills/虾评指南/SKILL.md`），按其中 §1.2 的下载安装流程执行：

```bash
# 1. 获取下载链接
curl -s "https://xiaping.coze.com/api/skills/<skill-id>/download"

# 2. 下载技能 ZIP
TMPDIR=$(mktemp -d)
curl -L -o "$TMPDIR/skill.zip" "<download-url>"

# 3. 解压到目标目录
mkdir -p <target-skills-dir>/<skill-name>
unzip -o "$TMPDIR/skill.zip" -d <target-skills-dir>/<skill-name>

# 4. 清理
rm -rf "$TMPDIR"

# 5. 验证安装
ls <target-skills-dir>/<skill-name>/SKILL.md
```

> **注意**：虾评的下载流程可能需要认证（API Key / Token），具体参考 `虾评指南` 技能中的 §0.2 注册流程和 §1.2 下载安装流程。

#### 5.4 从 ClawHub 远程安装

```bash
TMPDIR=$(mktemp -d)
curl -L -o "$TMPDIR/skill.zip" "https://clawhub.com/api/download?slug=<slug>"
mkdir -p <target-skills-dir>/<slug>
unzip -o "$TMPDIR/skill.zip" -d <target-skills-dir>/<slug>
rm -rf "$TMPDIR"
ls <target-skills-dir>/<slug>/SKILL.md
```

#### 5.5 从 GitHub 开源仓库安装

**先搜索确认仓库包含技能文件**：
```bash
# 搜索包含 SKILL.md 的代码
curl -s "https://api.github.com/search/code?q=filename:SKILL.md+<关键词>&per_page=10"
```

找到目标仓库后，克隆安装：
```bash
TMPDIR=$(mktemp -d)
git clone "https://github.com/<user>/<repo>.git" "$TMPDIR/<skill-name>"
mkdir -p <target-skills-dir>/<skill-name>
cp -r "$TMPDIR/<skill-name>" <target-skills-dir>/

# 验证安装
ls <target-skills-dir>/<skill-name>/SKILL.md

# 清理
rm -rf "$TMPDIR"
```

> **注意**：GitHub 搜索结果需要人工判断是否为有效技能（检查是否包含 `SKILL.md`）。

#### 5.6 从 Vercel Skills CLI 安装（Fallback）

```bash
npx skills add <owner/repo@skill> -g -y
```

如果安装在 `~/.agents/skills/` 而不是 `<target-skills-dir>`，则创建软链接：
```bash
ln -s ../../.agents/skills/<skill-name> <target-skills-dir>/<skill-name>
```

---

安装完成后，提示用户："✅ {技能名} 已安装，现在可以直接用啦！"

---

### Step 5.5：用户反馈学习（动态调整推荐）

**目的**：根据用户对推荐的实际反馈，动态调整后续推荐的评分权重，让推荐越来越贴合个人偏好。

**反馈采集点**（在输出推荐后主动询问或被动捕获）：

| 反馈类型 | 触发方式 | 捕获内容 |
|----------|----------|----------|
| **选择反馈** | 用户回复"安装第 N 个" | 记录选中技能 + 未选技能，提升所选技能权重 |
| **安装反馈** | 安装成功/失败 | 记录安装结果，成功技能加分 |
| **好评反馈** | 用户说"这个很好用/推荐得好" | 记录技能 + 场景，后续同场景优先推荐 |
| **差评反馈** | 用户说"这个不行/不合适" | 记录技能 + 场景，后续同场景降低该技能权重 |
| **调整反馈** | 用户说"换一个/再找找" | 记录当前推荐未命中，调整匹配策略 |

**权重调整规则**（每次反馈调整一次，累积生效）：

| 反馈 | 权重调整 |
|------|----------|
| 用户选择/安装成功 | 该技能 +5 分（下次同场景优先） |
| 用户好评 | 该技能 +3 分，且同来源技能 +1 分 |
| 用户差评 | 该技能 -8 分（短期内不再进 Top 3） |
| 用户换一个 | 当前 Top 3 整体 -2 分，扩大搜索范围重试 |

**实现方式（轻量，不引入数据库）**：
1. 在当前会话内用会话变量记录用户偏好（`preferred_slug` / `avoided_slug` / `scenario_prefs`）
2. 跨会话持久化（可选）：写入 `~/.workbuddy/skills/find-skills/feedback.json`，结构如下：

```json
{
  "scenarios": {
    "poster_design": {
      "preferred": ["AI图片生成无水印"],
      "avoided": ["claw-poster-generator"],
      "score_boost": {"AI图片生成无水印": 5},
      "count": 3
    }
  }
}
```

**在 Step 3 评分时叠加反馈分**：
```
综合评分 = 匹配度(40) + 来源权重(25) + 热度(20) + 可用性(15) + 反馈分(±8)
```

**注意事项**：
- 反馈分只作用于**相同或相似场景**，不跨场景污染推荐
- 单技能反馈分累计上限 ±15 分，防止极端偏好固化
- 用户从未反馈时，反馈分为 0，不影响首次推荐
- 差评技能在 3 次推荐周期内不进 Top 3（除非候选不足）

---

## Step 6：发布技能到 SkillHub（进阶）

当用户需要将自建技能发布到腾讯 SkillHub（skillhub.cn）时，按以下流程执行：

**前置条件**：
1. 已注册 skillhub.cn 账号并完成**实名认证**（个人中心 → 实名认证，腾讯云人脸核身）
2. 已创建 API Token（个人中心 → API keys → 创建，`skh_` 开头）

**安装 CLI**（如未安装）：
```bash
# macOS / Linux
curl -fsSL https://skillhub.cn/install/install.sh | bash -s -- --cli-only

# Windows：下载 https://skillhub.cn/install/install.sh 后，用 Python 解压 tar.gz 包，
# 将 cli/skills_store_cli.py 复制到 ~/.skillhub/，并在 ~/.local/bin/ 创建 skillhub 包装脚本
```

**登录 + 发布**：
```bash
# 1. 登录（Token 保存在 ~/.skillhub/）
skillhub login --key skh_你的Token --host https://api.skillhub.cn

# 2. 验证身份
skillhub auth whoami

# 3. 本地预检（不发起网络请求，只校验元数据+打包）
skillhub publish <技能目录> --dry-run

# 4. 正式发布（Windows 必须设 PYTHONIOENCODING=utf-8，否则中文/emoji 报 GBK 编码错误）
PYTHONIOENCODING=utf-8 skillhub publish <技能目录> --changelog "发布说明"
```

**SKILL.md 元数据要求**（腾讯 SkillHub）：
```yaml
---
slug: your-skill-name        # 全网唯一，小写字母+数字+连字符
displayName: 你的技能名称
version: 1.0.0
summary: 一句话简介
description: 详细描述
tags: [标签1, 标签2, 标签3]
license: MIT
---
```

**已知坑位**：
- **必须实名认证**才能发布，否则报"权限不足: 请先完成实名认证"
- **不允许上传 LICENSE 文件**，报"不允许的文件类型: LICENSE"，发布目录中不要放 LICENSE
- 发布后状态为 `pending_review`（审核中），通过三线安全审核后自动上架（通常 3-7 天）
- 更新技能：相同 slug + 提升 version + `--changelog` 说明变更
- Windows 路径：publish 传 Windows 风格路径（`C:\Users\...`），Git Bash 下用 `cygpath -w` 转换

---

## 触发词参考

| 用户表达 | 触发方式 |
|----------|----------|
| "我想做XXX" | 自动触发场景理解 |
| "帮我找XXX的技能" | 直接触发三层搜索 |
| "有没有能XXX的工具" | 触发三层搜索 |
| "这个场景应该用哪个技能" | 触发匹配推荐 |
| "我想做一个海报" | 自然语言场景 → 匹配设计类技能 |

**重要**：
- 本技能是**唯一的技能发现入口**，已完全替代 `find-skills`（其 description 已被标记为 DEPRECATED）
- 所有"找技能/安装技能/发现能力"的请求都由本技能处理

---

## 示例对话

**用户**："我想做一个海报，有没有合适的技能？"

**助手**：
```
🔍 为你精选 Top 3 个技能（搜索范围：官方内置 + 本地已安装 + 远程市场）

【第1名】★★★★★ AI图片生成无水印
   综合评分：█████████░ 90/100
   评分明细：匹配 36/40 · 来源 22/25 · 热度 17/20 · 可用性 15/15
   一句话说明：支持文生图、图生图，8通道（龙虾Lovart/即梦/通义等）
   匹配理由：海报设计核心是图片生成，该技能多通道可用且你已安装
   来源：本地已安装
   可用性：✅ 无需安装直接使用

【第2名】★★★★ poster-maker
   综合评分：███████░░░ 74/100
   评分明细：匹配 30/40 · 来源 18/25 · 热度 14/20 · 可用性 12/15
   一句话说明：专为主题海报设计的技能，含排版模板
   匹配理由：如果你需要成品模板和排版建议，选这个更省事
   来源：SkillHub 官方市场
   可用性：⬇️ 需安装（安装：回复"安装第2个"）

【第3名】★★★ claw-poster-generator
   综合评分：██████░░░░ 55/100
   评分明细：匹配 22/40 · 来源 10/25 · 热度 11/20 · 可用性 12/15
   一句话说明：ClawHub 社区海报生成技能，支持批量生成
   匹配理由：适合一次性生成多张海报的批量需求
   来源：ClawHub 社区
   可用性：⬇️ 需安装（安装：回复"安装第3个"）

💡 备选：另有 2 个相关技能未上榜（回复"查看全部"可浏览）
👉 需要我安装第几个，或调整推荐方向？
```

**英文场景示例**：
**用户**："Find a skill for making charts"

**助手**：
```
🔍 Top 3 skills picked for you (search: built-in + local + remote)

【#1】★★★★★ chart-skill
   Score: █████████░ 91/100
   Detail: Match 38/40 · Source 22/25 · Popularity 16/20 · Usability 15/15
   Why it fits: Chart creation is your core need, and this skill is already installed
   Source: Local (installed)
   Availability: ✅ Ready to use
...
👉 Which one should I install, or refine the search?
```

---

## 🔌 技能体系结合分析

### 🔗 协作链路

```
用户场景描述 / 明确要找技能
   → find-skills（场景技能匹配器）（本技能）← 唯一入口，已完全替代官方原 find-skills
       ├─ 第一层：官方内置技能扫描 → 直接推荐
       ├─ 第二层：本地已安装技能扫描 → 直接推荐
       ├─ 第三层：本地 marketplace 缓存检查 → 优先本地安装
       └─ 第四层：远程技能市场搜索 → 补充推荐
```

**下游调用**：
- 命中本地技能 → 直接调用对应技能
- 命中远程技能 → 按客户端检测结果安装 → 再调用

### ♻️ 与 `find-skills` 的关系

- **`find-skills`（官方插件目录）的 description 已被标记为 DEPRECATED**，不会主动触发
- **本技能已完全覆盖 `find-skills`（官方插件）的所有能力**：
  - ✅ SkillHub 远程搜索
  - ✅ ClawHub / Vercel Skills CLI fallback
  - ✅ 客户端检测（CodeBuddy / WorkBuddy）
  - ✅ 本地 marketplace 缓存检查
  - ✅ 一键安装（SkillHub / ClawHub / Vercel / GitHub）
- **本技能新增官方 `find-skills` 不具备的能力**：
  - ✅ 官方内置技能扫描
  - ✅ 本地已安装技能扫描
  - ✅ 场景语义理解（不是关键词搜索）
  - ✅ 推荐理由输出

> **结论**：官方 `find-skills` 插件文件可保留（官方插件目录，删除会被覆盖），但其 description 已失效，不会再被触发。所有技能发现请求都由本技能处理。

### 📊 体系优化建议

- `find-skills` 的 SKILL.md 已被标记为 DEPRECATED，后续官方插件更新可能会覆盖此修改，需留意
- 建议定期确认 `find-skills` 的 description 是否被正确禁用

### 🎯 使用场景映射

| 业务线 | 典型场景 | 推荐的技能 |
|--------|------------|------------|
| 自媒体 | "我想做小红书封面" | `AI图片生成无水印` / `封面图生成` |
| 自媒体 | "帮我写公众号文章" | `写公众号` / `公众号长文创作` |
| 量化交易 | "帮我分析今天的大盘" | `A股数据获取` / `A股市场情绪分析` |
| 公司经营 | "我想记录今天的反思" | `每日反思` / `Get笔记` |
| 公司经营 | "帮我发邮件给客户" | `email-skill` |

---

## 📝 版本迭代记录

| 版本 | 日期 | 更新内容摘要 | 操作人 |
|------|------|------------|--------|
| v1.3.0 | 2026-08-23 | 三大新特性：① 多语言支持（Step 1.5 语言检测+中英文输出模板）；② 评分可视化（Step 4 星级+评分条+四维明细）；③ 用户反馈学习（Step 5.5 选择/安装/好评/差评动态调权，反馈分±8） | lvdez |
| v1.2.0 | 2026-08-23 | 新增 Top 3 最优推荐机制：四维综合评分（匹配度40+来源权重25+热度20+可用性15）、降级剔除规则、星级输出格式、差异化推荐原则 | lvdez |
| v1.1.0 | 2026-08-23 | 完善迭代：更新标题/元数据为 enhanced；新增 Step 6 腾讯 SkillHub CLI 发布全流程；官方内置目录支持 Windows 路径；安装命令补充 tar 替代 unzip 的 Windows 解法；客户端检测补充 cygpath 路径说明；更新 tags/platforms/描述 | lvdez |
| v1.0.0 | 2026-08-23 | 基于社区 find-skills 增强改造：更新 slug/元数据为 find-skills-enhanced，去除原作者引流信息，适配腾讯 SkillHub 发布规范 | lvdez |
