# Find Skills Enhanced · WorkBuddy Skill

场景驱动+关键词双模式技能发现工具，跨平台兼容（macOS / Linux / Windows）。

当用户用自然语言描述场景/需求（如"我想做一个海报""帮我分析股票"），或明确说"安装技能/find skills/找个skill"时，自动从**官方内置、本地已安装、SkillHub、虾评、GitHub、ClawHub** 六层联合搜索并推荐最合适的技能，支持一键安装与一键发布。

## 特性

- **场景语义理解**：自动从自然语言提取意图/领域/关键词/语言
- **六层联合搜索**：官方内置 → 本地已安装 → 本地 marketplace 缓存 → SkillHub → 虾评 → GitHub → ClawHub
- **Top 3 最优推荐**：四维综合评分（匹配度+来源权重+热度+可用性）+ 反馈分，只推荐最优 3 个
- **评分可视化**：星级 + 评分条 + 四维明细，直观展示推荐依据
- **多语言支持**：自动检测用户语言，中文/英文双语输出
- **用户反馈学习**：基于选择/安装/好评/差评动态调整后续推荐
- **推荐理由**：每个推荐附带为什么适合这个场景
- **一键安装**：自动检测客户端（WorkBuddy/CodeBuddy），支持所有来源安装
- **一键发布**：内置腾讯 SkillHub CLI 发布全流程（登录 → 预检 → 发布 → 更新）
- **跨平台**：macOS / Linux / Windows（Git Bash / WSL / PowerShell）均可使用

## 安装

### 方式一：SkillHub 安装（推荐）

在 WorkBuddy 中搜索「Find Skills Enhanced」一键安装，或使用 CLI：

```bash
skillhub install find-skills-enhanced --scope user
```

### 方式二：手动安装

```bash
# macOS / Linux
git clone https://github.com/lvdez/find-skills-enhanced.git \
  ~/.workbuddy/skills/find-skills-enhanced
```

## 使用

在 WorkBuddy 对话中直接描述场景即可：

```
用户：我想做一个海报
助手：🔍 为你精选 Top 3 个技能...（星级 + 评分条 + 四维明细 + 推荐理由 + 安装指引）

用户：Find a skill for making charts
助手：🔍 Top 3 skills picked for you...（English output）
```

## 技能搜索渠道

| 优先级 | 渠道 | 说明 |
|--------|------|------|
| 1 | 官方内置技能 | WorkBuddy 自带，无需安装 |
| 2 | 本地已安装 | 你已经装好的 |
| 3 | 本地 marketplace 缓存 | 之前下载过的缓存 |
| 4-① | SkillHub 官方市场 | 官方认证技能 |
| 4-② | 虾评技能市场 | 中文技能重点来源 |
| 4-③ | GitHub 开源仓库 | 搜索含 SKILL.md 的仓库 |
| 4-④ | ClawHub / Vercel Skills | Fallback |

## 发布技能到 SkillHub

本技能内置 Step 6 发布流程，支持将自建技能发布到腾讯 SkillHub（skillhub.cn）：

```bash
# 登录（需先在官网完成实名认证 + 创建 skh_ Token）
skillhub login --key skh_你的Token --host https://api.skillhub.cn

# 预检
skillhub publish <技能目录> --dry-run

# 发布（Windows 加 PYTHONIOENCODING=utf-8 防中文乱码）
PYTHONIOENCODING=utf-8 skillhub publish <技能目录> --changelog "发布说明"
```

> 注意：发布目录中**不要包含 LICENSE 文件**（平台拒绝该文件类型）。

## 项目结构

```
find-skills-enhanced/
├── SKILL.md           # 技能说明（本技能的核心）
├── README.md          # 本文件
└── _meta.json         # 元数据（slug/version/owner）
```

## 作者

**lvdez** · Find Skills Enhanced

## License

MIT License
