# 股票价值投资分析助手 (stock-value-invest-guide)

一个「能算、能查、还能把脉」的价值投资分析助手。

- **方法论**：邱国鹭《投资中最简单的事》「三好原则」（好行业 × 好公司 × 好价格）+ 帕特·多尔西《股市真规则》护城河框架 + 安全边际思想。
- **量化层**：反向 DCF、EPV、情景概率加权、杜邦分解、ROIC vs WACC、Piotroski F-Score、Beneish M-Score、Altman Z-Score、盈余质量、5–10 年时间序列。
- **定性层**：护城河来源与宽度、管理层与资本配置、波特五力、行业生命周期、逆向投资、定价权。
- **大师把脉（可选）**：巴菲特 / 芒格 / 段永平单视角或三方会诊。
- **覆盖市场**：A 股 / 港股 / 美股。
- **护栏**：一票否决（含 M/Z-Score，`applicable=True` 才生效）+ 交卷前自检（数据复验 + 反向 7 问 + 量化层一致性）。

> ⚠️ 仅作投资思考框架，不构成任何投资建议。详见 SKILL.md 免责声明。

---

## 快速开始

把整个目录放入你的 Skill 目录（如 `.codebuddy/skills/stock-value-invest-guide/`），然后对话中直接说：

> 分析一下贵州茅台（600519），用价值投资框架看看值不值得买。

或直接触发量化取数（可选）：

```bash
cd scripts
python fetch_stock_data.py --symbol 600519 --market A
python fetch_stock_data.py --symbol 0700.HK --market HK
python fetch_stock_data.py --symbol AAPL  --market US
```

请大师把脉：

> 再用巴菲特和段永平的视角把把脉茅台。

---

## 工作流（Skill 内部）

```
用户输入 → 前置取数校验(5项铁律) → 行业(30%)/公司(35%)/估值(25%)/逆向+定价权(10%)
       → 〔可选〕大师视角 → 综合评分 + 一票否决 → 报告初稿 → 交卷前自检 → 交付
```

评分与结论矩阵、一票否决项、自检三关见 `SKILL.md`。

---

## 目录结构

```
stock-value-invest-guide/
├── SKILL.md                     # 主入口：方法论/流程/评分/否决/自检
├── README.md                    # 本文件
├── LICENSE.txt                  # MIT
├── _meta.json                   # 发布元数据
├── references/                  # 9 个参考手册
│   ├── three-good-principles.md
│   ├── moat-analysis.md
│   ├── financial-quality-models.md
│   ├── valuation-models.md
│   ├── industry-framework.md
│   ├── data-verification-protocol.md
│   ├── time-series-analysis.md
│   ├── contrarian-pricing-power.md
│   └── masters-perspectives.md
├── scripts/                     # 可选加速器（缺失则 LLM 基于现有数据继续分析）
│   ├── fetch_stock_data.py      # yfinance + AkShare 双引擎取数
│   └── value_models.py          # 8 大类量化模型库
└── templates/
    └── analysis-report.md       # 报告模板
```

---

## 可选依赖

脚本非硬依赖。若要用自动取数/算模型：

```bash
pip install yfinance akshare pandas numpy
```

库未安装或网络受限时，Skill 会优雅降级：基于用户上传的财报/数据或联网搜索继续分析，并在报告首页标注「数据降级」。

---

## 发布到 SkillHub

`_meta.json` 已含 `name / slug / version / author / license / description / tags / triggers`。
发布时 SkillHub 会自动补全 `ownerId / publishedAt`。直接打包本目录上传即可。
