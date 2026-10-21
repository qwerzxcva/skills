# 设计文档：缠论多维分析「分析报告 + 技能卡」融合为统一 Skill

- 日期：2026-07-09
- 作者：航宇（WorkBuddy 自动执行）
- 所属技能：`chanlun-multi-dim-analysis`
- 流程阶段：Phase 1 Brainstorming → 设计文档（待批准进入 Plan/TDD）

---

## 1. 背景与目标

当前技能生成 **两份独立 HTML**：
- `output/<symbol>_<date>_analysis.html` —— 专业分析报告（`report_template.html`）
- `output/<symbol>_<date>_skillcard.html` —— 游戏卡风技能卡（`skillcard_template.html`）

二者**取数独立、引擎各跑一次、字段体系不互通**，维护成本高、产物分散。

**目标**：将两者融合为**一个统一的 Skill**，执行一次引擎、输出**一份完整 HTML**，遵循规则：
- 相同功能模块合并为一个；
- 不同功能各自保留为独立模块；
- 整份 HTML 结构清晰、样式美观、可直接浏览器查看。

**已确认决策**（用户选择）：
- 整体风格：**专业报告风**（以分析报告白底专业风为主体；技能卡游戏化元素收敛为顶部「技能概览」卡片，配色适配报告风）。
- 脚本组织：**保留旧脚本 + 新增统一入口**（新增 `gen_unified.py` + `unified_template.html`；旧 `run_analysis.py` / `gen_skillcard.py` 及两份旧模板保留可单独调用，向后兼容）。

---

## 2. 模块映射（融合规则落地）

| 模块 | 来源 | 处理方式 |
|------|------|----------|
| 头部（标的/日期/综合信号徽章） | 报告 + 卡 | **合并** → 统一头部（标的名 + 信号徽章，专业风） |
| K线主图（缠论笔/线段/中枢 + 成交量 + 标注） | 报告（大图） / 卡（简化图） | **合并** → 采用报告大图，删卡简化图（避免重复） |
| 综合结论 / 诊断 / 策略 | 报告（最终结论+综合分析表） + 卡（多维贡献+综合诊断+周期视角） | **合并** → 单一「综合研判」模块 |
| 缠论方法论四模块 | 报告 + 卡 | **合并** → 一个方法论区块 |
| 数据来源 / Footer | 报告 + 卡 | **合并** |
| MACD / KDJ / RSI / OBV 指标共振 | 报告独有 | **保留**（报告专属区块） |
| 近30日形态速览 / 共振打分 / 背离 | 报告独有 | **保留**（报告专属区块） |
| 四维信号贡献 + 仪表盘 | 报告独有 | **保留**（报告专属区块） |
| 属性雷达图 / 技能效果条 / 冷却时间 / 消耗资源(仓位条) / 技能描述 | 卡独有（游戏化） | **保留** → 聚合为顶部「技能概览」卡片 |
| 多维信号贡献公式 | 卡独有 | **保留** → 融入技能概览卡 |

**融合后单份 HTML 模块顺序（专业报告风）**：
1. 统一头部（标的 / 日期区间 / 综合信号徽章）
2. **技能概览卡**（游戏化元素聚合，报告风配色适配）
   - 技能名 / 英文名 / 稀有度 / 等级徽章
   - 属性雷达图（四维：缠论/K线/资金/量能）
   - 技能效果条 + 多维信号贡献公式
   - 冷却时间 + 消耗资源（仓位条 `{{POS_PCT}}`）
   - 关键价位表
3. K线主图（缠论 + 成交量 + 标注）
4. 技术指标：MACD / KDJ / RSI / OBV 共振
5. 近30日形态速览 / 多指标共振打分 / 背离
6. 四维信号贡献 + 趋势研判仪表盘
7. **综合研判**（合并）：最终趋势结论 + 多维综合分析表（缠论诊断 / 量价 / 资金 / 风险 / 策略）
8. 缠论方法论四模块
9. 页脚（数据来源声明）

---

## 3. 数据层设计（核心：一次运行，双逻辑复用）

### 3.1 统一取数 + 引擎
新增 `gen_unified.py`，取数沿用已验证路径（`tdx-pro` 的 `get_kline_data`，与 `gen_skillcard.py` 一致，513050 已跑通）：
```
series = get_kline_data(SYMBOL, period='daily', count=380, calculate_ma=True)
→ 构造 df（open/high/low/close/volume/date，reverse+sort）
analyzer = ChanlunAnalyzer(SYMBOL, NAME, period='daily')
result = analyzer.run(df)
```
仅**一次**引擎运行，后续报告渲染与技能卡字段构造均复用此 `result`。

### 3.2 抽取技能卡派生逻辑为纯函数
将 `gen_skillcard.py` 中约 130+ 行游戏化派生逻辑抽为 `build_skillcard_fields(result, df, last_price, ...)`，返回 dict：
```
{
  skill_name, skill_en, rarity, rarity_cls, skill_level, skill_icon,
  attrs: [(维度, signal), ...],            # 用于雷达/属性条
  radar_vals100: [..四维0-100..],
  cooldown, effect_desc, effect_tp,
  calc_formula, contribs,
  key_levels: [(名称,值,距离), ...],
  pos_pct (取自 result['summary']['position_pct']，复用审查修复的结构化字段),
  trend_cn, sig, conf, sig_label, sig_color,
  last_price, change_pct, fund_trend, fund_int, fund5, fund20,
  diag_chan/vol/fund/risk/strategy, ...
}
```
**修复点**：`gen_skillcard.py` 原硬编码 `CHAN_DIR/TDX_DIR` 绝对路径（跨会话失效）与 `{{GEN_DATE}}` 死代码——统一入口用 `__file__` 相对定位，移除硬编码。

### 3.3 报告渲染逻辑复用
复用 `run_analysis.py` 现有注入方式：8 类 JSON 数据块（`REPORT_DATA_JSON` / `CHAN_DATA_JSON` / `CANDLE_DATA_JSON` / `FUND_DATA_JSON` / `VOLUME_DATA_JSON` / `LEVELS_DATA_JSON` / `RECENT_PATTERNS_JSON` / `KLINE_ANALYSIS_JSON`）注入模板，前端 `<script>` 动态填充各容器（kline/macd/kdj/rsi/obv/gauge、components/resonance/confidence/divergence/pattern/final-conclusion/diag-*）。

---

## 4. 模板设计（`unified_template.html`）

- **基础**：以 `report_template.html` 为骨架（白底专业风、`.chart-panel`、红边 `#e74c3c`、深色字）。
- **新增区块**：在头部之后插入「技能概览卡」`<div id="skill-overview">`，含：
  - 游戏化徽章行（技能名/英文名/稀有度/等级）
  - `<div id="radar">` 雷达图容器 + ECharts 初始化 JS（从技能卡迁移）
  - 属性条 / 技能效果条 HTML（由 `build_skillcard_fields` 生成）
  - 冷却时间 / 消耗资源（仓位条，宽度 `{{POS_PCT}}%`）
  - 关键价位表
- **JS 合并**：保留报告全部 ECharts 初始化（kline/macd/kdj/rsi/obv/gauge + 动态填充）+ 新增雷达图初始化（读 `{{SKILLCARD_JSON}}` 数据）。
- **配色**：技能概览卡沿用报告风白底卡片，强调色用红 `#e74c3c` / 金 `#d4a017`，**不引入深色背景**，保证风格统一。
- **占位符**：报告占位符（`{{SYMBOL}}` 等）+ 技能卡占位符（`{{SKILL_NAME}}` / `{{RARITY}}` / `{{POS_PCT}}` / `{{SKILLCARD_JSON}}` 等）全部保留并填充。

---

## 5. 渲染层设计（`gen_unified.py`）

```
1. 解析参数：SYMBOL, NAME（默认查名）
2. 取数 + 引擎运行（一次）→ result, df
3. report_payload = 构造 8 类 JSON（复用 run_analysis 逻辑）
4. card_fields   = build_skillcard_fields(result, df, ...)
5. 读 unified_template.html
6. 替换：报告占位符（report_payload）+ 卡占位符（card_fields）+ {{SKILLCARD_JSON}}=json.dumps(card_fields)
7. 写 output/<symbol>_<date>_unified.html
```

命令行：`python gen_unified.py 513050 "中概互联网ETF"`

---

## 6. TDD 任务分解（Phase 3 执行，每任务 2–5 分钟）

- **T1 统一入口取数+引擎**：在 `gen_unified.py` 实现取数→`analyzer.run(df)`，返回 `result, df`。测试：对 513050 断言 `result['analysis']['fusion']` 存在、引擎无异常。
- **T2 抽取 `build_skillcard_fields`**：从 `gen_skillcard.py` 抽出纯函数。测试：断言返回含 `skill_name/rarity/radar_vals100/pos_pct/key_levels`，`pos_pct` 等于 `result['summary']['position_pct']`。
- **T3 建 `unified_template.html` 骨架+CSS**：基于报告模板，插入技能概览卡区块与雷达容器，配色适配。测试：模板含 `id="skill-overview"`、`id="radar"`、`id="chart-kline"`、`id="final-conclusion"`，且无 JS 语法错误（加载检查）。
- **T4 渲染逻辑**：`gen_unified.py` 注入全部占位符 + `{{SKILLCARD_JSON}}`。测试：渲染后 HTML 不含任何 `{{...}}` 残留；含技能概览数据；JSON 合法。
- **T5 端到端验证**：跑 `gen_unified.py 513050 "中概互联网ETF"`，生成单份 HTML。测试：文件存在、大小合理、关键区块文本（信号值/诊断/方法论）均出现。
- **T6 代码审查 + SKILL.md 更新**：审查改动；在 SKILL.md「执行流程」增加统一产物步骤（默认出一份 unified HTML，旧命令保留可单独调用）；清理临时文件。

---

## 7. 风险与边界

- **字段不互通**：报告用 JSON 注入 + 前端填充；技能卡用 Python 预渲染 HTML。融合采用「Python 预渲染技能卡区块 HTML 字符串 + 报告 JSON 注入」混合方案，互不污染。
- **ECharts CDN 依赖**：断网仅文字/表格可读（已在诚实边界声明，不改）。
- **向后兼容**：旧 `run_analysis.py` / `gen_skillcard.py` 不删不改调用方式，仅新增文件；SKILL.md 注明三种产物均可生成。
- **绝对路径**：统一入口用 `__file__` 推导目录，杜绝 `C:\Users\...` 硬编码。

---

## 8. 验收标准

1. 执行 `python gen_unified.py 513050 "中概互联网ETF"` 产出**一份** HTML。
2. 该 HTML 同时包含：技能概览卡（雷达/属性条/冷却资源/关键价位）+ 报告全部模块（K线大图/四指标/形态/共振/综合研判/方法论）。
3. 无未替换占位符、无 JS 报错、无重复 K 线图。
4. 旧两份产物仍可独立生成（回归不受影响）。
5. SKILL.md 执行流程已更新，描述自洽、可直接实现。
