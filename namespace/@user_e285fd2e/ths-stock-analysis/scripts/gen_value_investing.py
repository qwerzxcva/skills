# -*- coding: utf-8 -*-
"""能力 #13 价值投资配置（模板，全参数化）

【定位】不是择时报告，是**框架性配置参考**：把巴菲特、格雷厄姆、彼得·林奇、博格、达利欧、塔勒布等人的
公开理论落成「哪类资产适合定投、哪类适合低价买入持仓不动、组合怎么配比与再平衡」的可执行清单。
本能力**不要求频繁更新数据** —— 配比与阈值是长期框架，只有「有效性锚点」漂移超阈值或超期才需重算
（判定逻辑在 `value_investing.py`：`--status` 看是否仍有效）。

【⚠️ 单一数据源约定（改动前必读）】
`ALLOC` 是**配比的唯一来源** —— 下面「执行总表」的占比列由它生成，
<b>value_backtest.py</b>（组合回测）与 `value_investing.summary_alloc()`（缓存摘要）也都直接读它。
**改配比只改 ALLOC 一处**；`MAIN` 的资产名必须与 ALLOC 完全一致（`build()` 里有断言）。
`LEG_MAP`（value_backtest.py）按这些名字映射回测标的，改名要同步改三处。

【v8 重构（2026-09-30，用户要求「写得太长、重复性高，合并」）】
原 8 区块 13 表 → **4 区块 6 表**：
- **删掉「去哪儿查」类教程**（原 9 行查询渠道表、支付宝「指数红绿灯」路径等）——用户原话
  「关于股息率等你不用告诉我去哪查，你查好给我就行，并标注目前情况、历史分位」
- **合并**原「★ 一页执行表 + 02 资产总表 + 05 配比 + 06 场外申购清单」→ 新 **01 执行总表**
  （总表 + 当下估值表 + 再平衡铁律）
- **合并**原「03 判据与证据 + 07 回测」→ 新 **02 判据与证据**
- 原「01 理论框架」（6 张卡）压成一行一作者，与回避清单合成 **04**
- 删表：口径对比 A~E、个股分布、再平衡频率敏感度（结论改写成文字）、查询渠道
- **新增「目前情况 / 该怎么做」列**（用户要求标注当下判断）

历史沿革（供追溯，勿删）：v3 删「A股宽基」（同窗口实测落后标普500 16.8pct/年）；v5 删「公募REITs/美债/可转债」；
v6 加场外基金代码；v7 接受 QDII 额度限制并定策略、加估值速查。

【v13 整理（2026-10-08，用户要求「整个 html 重新整理一下，简洁明了」）】
按**用户实际会用的顺序**重排编号，并删掉纯教学内容（正文减约 1/3）：
- **01 每月怎么做** ← 原 01 的「每月表」**提到最前**（资金口径已收敛为「只看月结余、与存款无关」）
- **02 五类资产：买什么 · 怎么投 · 怎么撤** ← 原「执行总表」＋「再平衡铁律」
- **03 现在贵不贵** ← 原「估值表」（原挂在 01 下的子块，现独立成节）
- **04 判据与证据** ← 原 02（PILLARS / 跨资产对比 / 定投期限 / 回测 / 逐年）
- **05 不做什么** ← 原 04 的回避清单（理论出处统一留页脚 NOTE，不再单列一表）
- **删**：原 03「三个指标怎么看」（PE/PB/股息率教学，用户已知）、六位作者理论表、
  `MAIN_NOTE`（金额换算示例，其中「A 类 / C 类怎么选」一句并入 02 节 hint）、
  `VAL_INSIGHT`（与 `CORE_INSIGHT` 重复）
- `CORE_INSIGHT` 由 8 句压到 3 句；QDII 说明去掉口语赘述，保留限额表与三条路

风格：与其它能力统一 —— 浅色金融仪表盘、深蓝 #1f3a93 + 金 #c9a227、
`.insight` 金色结论条、`.sum-row/.sum-tag` 摘要行、tabular-nums、页脚口径免责。
红线：**不出现个股买卖建议、不承诺收益、不虚构数据**；理论引用一律标注为公开出版物；
      **实测数据必须同时给出样本区间、口径与「未计成本」声明**。
"""
import os
from datetime import date as _date, timedelta as _td

BASE = os.environ.get("THS_WORKSPACE", os.getcwd())
# ⚠️ 生成日由调用方（`value_investing.render()`）通过环境变量 `THS_VALUE_DATE` 注入；独立运行用兜底字面量。
#    修复（2026-10-08）：此前 `DATE` 是**死字面量** → 换一天重新生成时，模板仍按旧日期命名文件
#    （`价值投资配置_<旧日期>.html`），**会覆盖上期报告**；而 `value_investing` 记的是新日期
#    → 缓存里 `html` 指向一个不存在的文件。实测在 10-08 重新生成时踩到。
DATE = os.environ.get("THS_VALUE_DATE") or "2026-09-30"
# 有效期**必须跟着 DATE 走**（此前写死 "2027-03-29"）：否则报告写「有效至 3-29」、
# 而 `value_investing` 按生成日 +180 天算出「有效至 4-06」，两处口径不一致。
VALID_UNTIL = (_date.fromisoformat(DATE) + _td(days=180)).isoformat()
GEN = "框架性配置参考 · 非择时报告"
VALID_VER = "v13"
DATE_VAL = "2026-09-30"   # 估值/股息率数据的核实日（不随生成日变化）

# ================= 数据 =================
CFG = {
    "name": "价值投资配置",
    "code": "长期资产 · 定投与持仓框架",
    "verdict": "A股红利低波收息 + 美股宽基定投 + 股债黄金跨象限",
    "verdict_short": "长期配置框架",
}
HERO_KPIS = [
    ("5 类", "资产（全部核心，无「可选」项）", "gd"),
    ("4.7 年", "回测区间（2021-11 起）", "gd"),
    ("−2.23%", "沪深300 近 5 年一次性年化", "dn"),
    ("+14.6%", "标普500ETF 近 5 年一次性年化", "up"),
]
CORE_INSIGHT = ("💡 <b>一条判据</b>：赚价格的定投（美股宽基、黄金）；赚分红的等便宜了买（A股红利低波）；"
                "两者都不靠的按比例配（债券、现金）。<b>A股宽基已按数据删掉</b>——近 5 年沪深300 一次性年化 "
                "<b>−2.23%</b>、回撤 −37.9%，同期标普500ETF <b>+14.55%</b>、回撤 −24.9%，收益更低而波动更大。"
                "<b>需要盯的只有 5 个数字</b>：红利低波股息率 4.30% / PE 分位 43% / PB 分位 22%、"
                "标普500 PE 分位 57%、以及你的月结余。其余设好就不用管。")

# 配比 = 唯一数据源（value_backtest.py / value_investing.py 都读它）
# (资产, 类别, 稳健, 平衡（默认）, 进取, 作用)
# ⚠️ 改这里必须同步三处（2026-10-08 起由 check_build 的 V1 校验兜住）：
#    ① `ALLOC_NOTE` 的风险资产占比行；② `MAIN` 里跟着平衡档走的硬编码占比
#    （美股「月结余 × %」、黄金「月结余 × % × 3」、以及「目标 = 月结余 × %」那处）；
#    ③ 跑 `value_backtest.py --all --forward <按本表顺序的 5 个假设年化>` 重算 `BT2` / `BT2_YEAR`。
ALLOC = [
    ("A股红利低波", "核心", "21%", "21%", "15%", "现金流（收息）"),
    ("美股宽基（QDII）", "核心", "21%", "33%", "47%", "长期增长（定投主力，上限 50%）"),
    ("国内债券", "核心", "26%", "16%", "8%", "压组合波动"),
    ("黄金", "核心", "12%", "12%", "15%", "跨象限对冲（上限 20%）"),
    ("现金 / 货币", "核心", "20%", "18%", "15%", "流动性与再平衡弹药（15%~20%）"),
]
ALLOC_NOTE = ("A股个股（可选子额度）：合计 ≤20%、单只 ≤8%，<b>从「A股红利低波」那一档内切出，不额外占权重</b>。"
              "风险资产占比（美股宽基 + 红利低波）：<b>稳健 42% / 平衡 54% / 进取 62%</b>。"
              "现金档于 <b>2026-10-08 上调</b>（原 7% / 8% / 10%）——为房贷、婚期与职业转换留出更厚的缓冲，"
              "降低部分主要来自债券与黄金（两者前瞻假设均约 3%），<b>预期收益代价很小、流动性明显变厚</b>。")

# ---------- 你的真实资金口径（数据源：D:\AI\记账 真实账本 2026-01~09；账户快照 2026-08-21）----------
# ⚠️ 2026-10-08 用户要求简化：「别考虑我现有存款了，只根据我以后的收支，告诉我每月应该怎么办就行」
#    → 报告正文**只渲染月度分配**（MON_* 那几个）；
#      下面 CAP_/HOLD/RES_/TOTAL_ASSETS/CAPITAL/AMT 保留作**数据留档**、本期**未渲染**。
#      若日后要恢复「存量视角」（每档该有多少 / 已持有 / 还差），按此口径算回来加一张表即可：
#      总金融资产 = 现金类 + 已持基金现值；可配置 = 总金融资产 − 应急金 − 专项。
# 口径说明（改这些数字即可让下面所有金额联动，不必改表格）：
#   经常性口径 = 剔除「一次性收入（购房补贴/学费代偿）」「理财申购与收益」「出差垫付与报销」
#   —— 这三类都会扭曲"月结余"（实测：出差净额 +28,762、理财净额 −5,537，混进来就失真）
CAP_CASH = 271563.71          # 现金类合计（支付宝 / 微信 / 工商银行 / 招商银行）
CAP_STOCK = 20067.11          # 股票账户（已持仓 → 计入「A股红利低波」的可选子额度，不额外占权重）
# 🔴 已持有的场外基金（2026-10-08 用户告知；**这两笔钱在 8-21 账户快照里已经不在现金账上**，
#    所以必须单独计入总资产，否则「可投资金」会漏掉 7 万、还会把「债券档」算成没配过）
HOLD = [
    ("景顺长城安景一年持有混合A", "013225", "偏债混合（债 87.6%/股 5.2%/现金 2.9%）",
     "国内债券", 49760.00, "⚠️ 每份锁定一年 → 2027-07-10 前不可赎回"),
    ("中银国有企业债A", "001235", "纯债（不投股票）",
     "国内债券", 20022.00, "满 6 个月免赎回费 → 2027-01-10 起可免费赎回"),
]
HOLD_BY_LEG = {}
for _n, _c, _t, _leg, _v, _note in HOLD:
    HOLD_BY_LEG[_leg] = HOLD_BY_LEG.get(_leg, 0.0) + _v
HOLD_TOTAL = sum(h[4] for h in HOLD)
MON_INCOME = 14916.79         # 经常性收入月均（9 个月）
MON_EXPENSE = 12137.29        # 经常性支出月均（9 个月）
MON_SURPLUS = 2779.50         # 月结余 = 收入 − 支出
RES_EMERGENCY = 72823.72      # 应急金 = 6 个月经常性支出（不参与再平衡）
# ⚠️ 婚期/职业转换专项：账本里**没有**婚礼/彩礼支出记录，所以这不是实测值，是**保守默认**。
#    依据是本文档自己的《期限铁律》——「3 年内要用的钱不进入任何一档」，而 2027 婚礼在 3 年内。
#    **金额可调**：改成 0 则全部可投；改成 150000 则更保守。改这一行，下面金额自动重算。
RES_EXTRA = 100000.00         # 2027 婚礼 / 职业转换专项（可调）
TOTAL_ASSETS = CAP_CASH + HOLD_TOTAL                     # 总金融资产（现金 + 已持基金）
CAPITAL = TOTAL_ASSETS - RES_EMERGENCY - RES_EXTRA      # 可配置资产（一次性口径）
AMT = {r[0]: CAPITAL * int(r[3].rstrip("%")) / 100 for r in ALLOC}        # 平衡档 × 可投资金
MON_AMT = {r[0]: MON_SURPLUS * int(r[3].rstrip("%")) / 100 for r in ALLOC}  # 平衡档 × 月结余

# 01 执行总表：资产名必须与 ALLOC 完全一致（占比列由 ALLOC 生成）
# (资产, 操作方式, 场外基金（代码）, 怎么投, 怎么撤, 现在该怎么做（截至 2026-09-30）)
MAIN = [
    ("A股红利低波", "低价买入 · 持仓不动",
     "华泰柏瑞中证红利低波ETF联接 <b>007466</b>(A) / 007467(C)",
     "股息率 <b>&gt;5%</b> 时一次性建仓；股息再投资",
     "股息率 &lt;3.5% → 减半；成分股大范围削减分红 → 换标的",
     "<b>分批建仓 —— 不一笔投、也不定投</b><div style='margin-top:3px'>把这一档的钱分 <b>3 份，每月买 1 份</b>，"
     "3 个月建完</div>"
     "<div style='font-size:11.5px;color:var(--ink-3);margin-top:3px'>为什么：股息率 4.30% 还没到 5% 的一次性买入线，"
     "但 PB 处近 10 年 22% 分位、已属「不贵」→ <b>既不必等，也不该一次押上</b></div>"),
    ("美股宽基（QDII）", "定投",
     "宝盈纳指100 <b>019736</b>(A)"
     "<div style='font-size:11.5px;color:var(--ink-3)'>天弘 018043 · 国泰 160213</div>",
     "<b>每日扣款</b>，投 <b>月结余 × 33%</b>；回撤 &gt;20% → 当月 1.5 倍；<b>溢价 &gt;3% → 停买</b>"
     "<div style='font-size:11.5px;color:#8a6d12;margin-top:3px'>"
     "⚠️ <b>为何必须日投</b>：QDII 单日限额常只有 10 元/只 → 月投一天买不满（见下方限额测算）；"
     "<b>须拆 5~6 只（不同基金公司）</b>、每日各买约 10 元</div>"
     "<div style='font-size:11.5px;color:var(--ink-3);margin-top:2px'>"
     "⏱ <b>收益上每日与每月无实质区别</b>（4.72 年同总投入：标普500ETF +0.26%、黄金 −0.35%）"
     "——日投是「买不买得到」的问题，不是收益问题</div>",
     "不设止盈；估值极端只减不加。<b>溢价高是「停买」不是「卖」</b>",
     "<b>本月照常定投，不加倍</b><div style='margin-top:3px'>投「月结余 × 33%」，用 2~3 只基金分摊</div>"
     "<div style='font-size:11.5px;color:var(--ink-3);margin-top:3px'>为什么：标普500 PE 分位 57%（中段）、"
     "PB 分位 94%（偏高）→ <b>偏贵但没到极端</b>；加倍要等回撤 &gt;20%，现未达。"
     "月结余 &gt;10,300 元时，超出 3,410 元/月的部分留货币基金</div>"),
    ("国内债券", "一次性配置",
     "易方达中债7-10年期国开行债券指数 <b>003358</b>(A)",
     "一次性按比例配足，<b>不定投</b>",
     "股债比偏离目标 → 随再平衡一起调整",
     "<b>本档暂停买入</b><div style='margin-top:3px'>你已持有 013225（锁定至 2027-07-10）＋ 001235，均为债券档且<b>已超配</b> → 不再加仓，等占比回落再恢复</div>"
     "<div style='font-size:11.5px;color:var(--ink-3);margin-top:3px'>为什么：债券日波动只有股票的 1/5~1/10，"
     "<b>定投摊平没有意义</b>，只会让钱躺在场外</div>"),
    ("黄金", "定投 / 回调分批",
     "华安黄金易ETF联接 <b>000216</b>(A) / 000217(C)",
     "<b>每月 1 次</b>；自高点回撤 &gt;15% → 加倍",
     "占比 &gt;20% 或累计涨幅 &gt;50% → 减回 15%",
     "<b>每月 10 号投一笔</b><div style='margin-top:3px'>按「月结余 × 12%」投，不必按季（按季容易忘）</div>"
     "<div style='font-size:11.5px;color:var(--ink-3);margin-top:3px'>为什么：近 5 年已涨 19.89%、回撤可达 −30.5%，"
     "现处偏高位区间；占比 12% 已够 → <b>不追高，也不减</b></div>"),
    ("现金 / 货币", "常备流动性",
     "余额宝（天弘余额宝货币 <b>000198</b>）",
     "应急金 = 6 个月支出 + 再平衡弹药",
     "只在补其他资产时动用",
     "<b>现在先留足（优先做）</b><div style='margin-top:3px'>6 个月支出放余额宝，这部分不参与再平衡；"
     "另留「美股待投资金」</div>"
     "<div style='font-size:11.5px;color:var(--ink-3);margin-top:3px'>为什么：<b>唯一不需要判断行情的动作</b>，先做掉</div>"),
]
MONTHLY_HEAD = ("资产", "每月投（元）", "怎么投")

_DCA_MON = MON_AMT["美股宽基（QDII）"]
_DCA_DAY = _DCA_MON / 21
_DCA_WEEK = _DCA_MON / 4.333
QDII_WARN = (
    "QDII 限额是<b>单日单账户单基金</b>（81 只中位数 100 元/日、<b>25 只 ≤10 元/日</b>；"
    "宝盈纳指100 起投/单笔/单日各 10 元），且<b>额度按基金公司合并</b>（同公司多只不能各买 10 元）。"
    "<table style='margin:6px 0;font-size:12px'>"
    "<tr><th>买法</th><th>单日需买</th><th>能否买进去</th></tr>"
    f"<tr><td>月投</td><td>{_DCA_MON:,.0f} 元（集中在一天）</td>"
    "<td><b style='color:var(--red)'>✗ 全市场合计约 155 元/日 → 差 6 倍</b></td></tr>"
    f"<tr><td>周投</td><td>{_DCA_WEEK:,.0f} 元</td>"
    "<td><b style='color:var(--red)'>✗ 仍超 155 元/日</b></td></tr>"
    f"<tr><td><b>日投</b></td><td><b>{_DCA_DAY:,.0f} 元</b></td>"
    "<td><b style='color:var(--green)'>✓ 可行 —— 拆 5~6 只（跨公司）</b></td></tr></table>"
    "<b>三条路</b>：① 拆 5~6 只跨公司、每日各买约 10 元；② 用自动抢额度工具；"
    "③ <b>开证券账户买场内 ETF（513500 / 513100）—— 不限购、一次配满、费率更低，额度紧时更省事</b>"
    "（代价：溢价率 &gt;3% 时不买）。"
    "<div style='font-size:11.5px;color:var(--ink-3);margin-top:4px'>"
    "⏱ 收益上每日与每月<b>实测无实质区别</b>（4.72 年同总投入：标普500ETF +0.26%、黄金 −0.35%）"
    "——日投解决的是「买不到」，不是「收益更高」。　"
    "来源：中国证券报 2026-09-21、万家基金公告 2026-09-23、各平台申购页 2026-10-08；额度每日变，下单前看页面。</div>")


# 01 当下估值（数据 2026-09-30 核实；来源与日期见 VAL_SRC）
# (资产, PE(TTM), PE 分位, PB, PB 分位, 股息率, 目前情况 / 该怎么做)
VAL_HEAD = ("资产", "PE(TTM)", "PE 分位", "PB", "PB 分位", "股息率", "目前情况 / 该怎么做")
VAL = [
    ("<b>A股红利低波</b><div style='font-size:11px;color:var(--ink-3)'>中证红利低波动指数</div>",
     "8.52", "近 10 年 <b>43%</b>", "0.87",
     "近 10 年 <b>22%</b><div style='font-size:11px;color:var(--ink-3)'>深度破净</div>",
     "<b>4.30%</b>",
     "<b>未达 5% 触发线</b>（差 0.1~0.7pct），但 PB 处近 10 年 22% 分位 → "
     "<b>属「不贵」区间：可分批建仓 / 持有收息，不必等 5% 才买，也别一次性重仓</b>。"
     "<div style='color:#8a6d12;font-size:11.5px;margin-top:3px'>⚠️ 结构提示：前十大重仓 7 家是银行（约占 71%），"
     "它不是均衡红利组合，真正的风险源是银行息差与资产质量</div>"),
    ("<b>标普500</b><div style='font-size:11px;color:var(--ink-3)'>（美股宽基）</div>",
     "25.13", "近 10 年 <b>57%</b>", "5.52", "近 10 年 <b>94%</b> ⚠️", "1.03%",
     "<b>偏贵但不极端</b>（PE 处中段，PB 接近历史高位）→ <b>继续定投、不加倍</b>"
     "（加倍条件是回撤 &gt;20%，现未达）"),
    ("<b>纳斯达克100</b><div style='font-size:11px;color:var(--ink-3)'>（美股宽基）</div>",
     "29.91", "近 10 年 45%", "—", "—", "—",
     "与标普500同理 → <b>继续定投、不加倍</b>"),
    ("国内债券", "不适用", "—", "—", "—", "—",
     "不适用 PE / PB / 股息率，<b>看的是利率</b>。近 5 年年化 <b>+4.47%</b>、回撤仅 −2.3% —— "
     "其中含 2022-2024 利率下行的红利，<b>不要指望重复</b>"),
    ("黄金", "不适用", "—", "—", "—", "—",
     "不适用（无现金流）。近 5 年 +19.89% 但回撤 −30.5% → <b>已在偏高位区间，占比 12% 不再加</b>"),
]
VAL_SRC = ("来源与日期：中证红利低波动指数 8.52 / 0.87 / 4.30% —— 雪球 2026-09-16"
           "（另一来源 2026-09-24 为 8.57 / 0.77 / 4.89%）；标普500 25.13 / 5.52 / 1.03% 与纳指100 29.91 —— "
           "雪球 2026-09-11 / 09-10；债券与黄金为同花顺接口近 5 年实测。"
           "<b>自算核对</b>（<b>value_valuation_check.py</b>：红利低波 ETF 前十大重仓按权重归一）→ "
           "PE 6.96 / PB 0.90 / 已实现股息率 5.85%，且自算前十大合计权重 25.0% 与官方 25.5% 交叉验证一致。"
           "<b>两个股息率口径不同</b>：指数口径是「分红 ÷ 现价」，自算口径是「近 12 个月已实现分红回报」"
           "（用前复权收益 − 未复权收益反推）—— <b>两者都看，别混用</b>。")
RULES_SHORT = [
    ("再平衡（机械执行）", "任一资产实际占比偏离目标 <b>±25% 相对值</b>（目标 20% → 低于 15% 或高于 25%）即拉回；"
                          "年末兜底检查一次；<b>优先用新钱补低配</b>，不卖高配。"
                          "再平衡频率（月/季/年）对收益影响 &lt;0.15pct，但<b>不再平衡会让回撤放大约 3pct</b>"),
    ("卖出只允许两种情况", "<b>估值极高</b> 或 <b>逻辑破坏</b> —— <b>价格下跌不在其中</b>"),
    ("单一资产上限", "美股宽基 ≤50%、黄金 ≤20%、现金 15%~20%。<b>5 类已经够用，不要靠加品种来安心</b>"),
    ("期限铁律", "3 年内要用的钱不进入任何一档；应急金单独放货币基金，不参与再平衡"),
]

# 02 判据卡（3 张）
PILLARS = [
    ("定投", "收益来自<b>价格上行</b> + 长期向上 + 波动大",
     "<b>两个前提同时成立才定投</b>。满足时下跌能买到更多份额，回升时这部分份额贡献超额收益。",
     "单边上涨 → 定投<b>跑输</b>一次性；<b>下行 + 高波动 → 定投只是亏得慢，该换成真正上行的标的</b>"),
    ("低价买入 · 持仓不动", "收益来自<b>现金分红</b>，且有可量化的「便宜」阈值",
     "<b>三条同时成立</b>：① 可锚定的现金回报；② 明确阈值（股息率 &gt;5%）；③ 不靠上涨赚钱。",
     "这类资产<b>不适合定投</b>：定投会在股息率低（贵）时照样买，把股息率摊薄成平庸水平"),
    ("一次性配置", "波动小，只为降低组合波动",
     "债券与现金的日波动只有股票的 1/5~1/10，<b>定投摊平的意义接近于零</b>，比例由「股债比」决定。",
     "用定投建债券仓 → 一年后可能还有一半资金没投出去，白白损失票息"),
]

# 02 跨资产同窗口对比（近 5 年）
CMP_HEAD = ("资产", "一次性年化", "最大回撤", "年化波动", "月定投 IRR")
CMP = [
    ("沪深300（A股大盘）", "−2.23%", "<b>−37.9%</b>", "18.0%", "+3.56%"),
    ("中证500（A股中盘）", "+1.04%", "−39.7%", "22.7%", "+8.18%"),
    ("<b>标普500ETF（QDII）</b>", "<b>+14.55%</b>", "−24.9%", "18.8%", "<b>+20.42%</b>"),
    ("<b>纳指100ETF（QDII）</b>", "<b>+18.09%</b>", "−27.5%", "23.5%", "<b>+29.22%</b>"),
    ("<b>红利低波ETF（A股）</b>", "+10.65%", "<b>−14.2%</b>", "<b>15.9%</b>", "+8.35%"),
    ("黄金ETF", "+19.87%", "−30.5%", "18.0%", "+22.23%"),
]

# 02 定投期限与胜率（A股全市场等权，全部起点滚动，2016-08 起）
HORIZON_HEAD = ("定投年限", "总收益中位", "胜率", "最差窗口", "年化 IRR 中位")
HORIZON = [
    ("1 年", "+5.1%", "67%", "<b>−25.3%</b>", "+11.3%"),
    ("3 年", "+19.8%", "<b>87.5%</b>", "−16.2%", "+12.8%"),
    ("5 年", "+31.1%", "<b>92.9%</b>", "−7.4%", "+11.1%"),
    ("8 年", "+68.2%", "100%", "+25.1%", "+12.9%"),
]

# 02 回测（2021-11-17 ~ 2026-10-08 / 1183 交易日 / 4.69 年）
BT2_HEAD = ("档位", "累计收益", "年化", "最大回撤", "年化波动", "夏普", "前瞻中枢（假设）")
BT2 = [
    ("稳健", "+54.0%", "+9.63%", "−5.8%", "6.3%", "<b>1.25</b>", "+4.61%"),
    ("平衡（默认）", "+63.3%", "<b>+11.01%</b>", "−8.0%", "8.1%", "1.16", "+5.12%"),
    ("进取", "+74.7%", "+12.62%", "−10.9%", "10.2%", "1.10", "+5.42%"),
]
BT2_YEAR_HEAD = ("年份", "稳健", "平衡", "进取")
BT2_YEAR = [
    ("2021（自 11-17）", "+2.1%", "+2.2%", "+1.8%"),
    ("2022", "+0.5%", "<b>−1.3%</b>", "−3.3%"),
    ("2023", "+11.8%", "+14.7%", "+17.9%"),
    ("2024", "+18.2%", "+21.6%", "+25.2%"),
    ("2025", "+10.1%", "+11.6%", "+14.7%"),
    ("2026（至 10-08）", "+3.4%", "+4.4%", "+5.2%"),
    ("滚动 12 个月最差", "<b>+0.5%</b>", "−1.3%", "−3.4%"),
]
EVID_INSIGHT = ("💡 <b>A股宽基为什么删</b>：同一时间、同一口径下它<b>收益低 16.8pct/年、回撤还大 13pct</b> —— "
                "定投能改善它（月定投 IRR +3.56%），但改善后仍远低于直接定投美股宽基（+20.42%）。"
                "不过 <b>「不配 A股」≠「不配 A股资产」</b>：A股内部最稳的恰恰是<b>红利低波</b>"
                "（回撤 −14.2%、波动 15.9%，比标普500还小）。"
                "<br><b>定投要投多久</b>：<b>3 年胜率 87.5%、5 年 92.9%、8 年 100%</b> —— 不需要 10 年，"
                "但 <b>1 年窗口是真的会亏</b>（胜率 67%、最差 −25%）。所以「定投期 ≥3 年」要写进纪律，而不是靠感觉。"
                "<br><b>口径提醒</b>：等权每日再平衡含波动收割，比买入持有高约 4.9pct/年，<b>不是可交易收益</b>；"
                "同期 A股个股收益中位数是 <b>−22.5%</b>、<b>64.2%</b> 的股票亏钱 —— 所以「分散」比「择时」重要得多。")
BT2_INSIGHT = ("💡 <b>回测怎么读（关键）</b>：这 4.69 年本身是<b>美股 +90.1%、黄金 +127.8% 的双重大牛市</b> —— "
               "平衡档 10.45pct 里，美股（33%×14.66% = 4.84）与黄金（12%×19.17% = 2.30）就占了 "
               "<b>7.14pct（68%）</b>。所以 <b>① 回撤数据比收益数据可信</b>（回撤是这段历史里真实发生过的）；"
               "<b>② 规划时用「前瞻中枢」那一列</b>（按长期保守假设：红利低波 8% / 美股 7% / 债券 3% / 黄金 3% / 现金 1.6%，"
               "加权只有 4.9%~5.6%），<b>这个差额就是「这段窗口有多特殊」的量化表达</b>。"
               "<br>口径：ETF 用未复权价格（现金分红被除权剔除 → <b>系统性低估</b>）；含单边 10bp 交易成本；"
               "未计 QDII 溢价、申赎费与税费；<b>样本只有一轮市场环境，不可外推</b>。")

# 05 不做什么（八条硬约束；理论出处统一放页脚，不再单列一表）
AVOID = [
    ("加杠杆 / 融资 / 期权", "任何会强制平仓的结构都会让「长期持有」变成不可能；先保证不归零"),
    ("单一行业或主题重仓（&gt;20%）", "微盘 / 次新 / 概念联动无估值锚；好行业单一年份回撤 40%+ 也很常见"),
    ("随机买个股长期持有", "近 9.7 年 A股个股收益中位数 <b>−22.5%</b>、<b>64.2%</b> 的股票亏钱、"
                          "前 1.2% 的股票贡献 67.7% 总收益 —— 不选就买 = 赌自己是那 1.2%"),
    ("用 3 年内要用的钱做长期配置", "期限错配是散户亏钱的第一原因：被迫在低点卖出"),
    ("追溢价买 QDII / 追高买热门 ETF", "QDII 溢价 &gt;3% 相当于先亏 3%；热门 ETF 高位重仓等于买在情绪顶"),
    ("把黄金 / 债券当收益引擎", "它们是组合的稳定器（低相关、低波动），不是赚钱主力"),
    ("频繁交易与天天看净值", "成本是唯一确定的负收益；高频交易把「时间复利」换成「手续费复利」"),
    ("因短期下跌卖出长期仓位", "卖出只允许两种情况：估值极高、逻辑破坏 —— 价格下跌不在其中"),
]

# 有效性判据（与 value_investing.py 的 ANCHORS 必须一致）
ANCHOR_TEXT = ("沪深300 000300.SH（±25%）、黄金ETF 518880.SH（±30%）、纳指ETF 513100.SH（±30%）、"
               "红利低波ETF 512890.SH（±25%）、10年国债ETF 511260.SH（±5%）")
NOTE = ("<b>理论依据（均为公开出版物，非投资建议）</b>：巴菲特致股东信；格雷厄姆《聪明的投资者》；"
        "彼得·林奇《彼得·林奇的成功投资》；约翰·博格《共同基金常识》；瑞·达利欧《原则》；纳西姆·塔勒布《反脆弱》。"
        "本报告是对上述框架的<b>工程化整理</b>，不代表上述作者本人观点。"
        "<b>数据口径（必读）</b>：实测数据来自<b>本地日线库前复权（含分红再投），区间 2016-08-23 ~ 2026-09-28</b>，"
        "由 <b>value_evidence.py</b> 计算、可复现；个股日收益按 ±25% 截尾、当日有效样本 &lt;200 只的日子剔除。"
        "<b>「等权·每日再平衡」是理论组合</b>，含波动收割，<b>不是可直接买入的产品收益</b>；"
        "指数与 ETF 数据经同花顺接口取得，<b>接口窗口上限 5 年</b>（按自然日算、贴边也会返回空）。"
        "<b>跨资产对比中：指数为价格指数（不含分红）、ETF 为未复权价格（分红被除权剔除）→ 两者都低估真实收益</b>；"
        "横向比较成立，绝对值不可外推。"
        "<b>03 节估值数据</b>经 2026-09-30 联网核实并标注来源与日期；<b>自算口径</b>来自 <b>value_valuation_check.py</b>"
        "（前十大重仓按权重归一，<b>仅覆盖前十大、不等于整只指数</b>）。"
        "所有回测与估算<b>均未计交易成本、税费、跟踪误差与申赎费率</b>。历史数据不代表未来。"
        "<b>报告性质</b>：框架性资产配置参考（模型输出），<b>不含个股买卖建议、不做点位预测、不承诺任何收益</b>；"
        "配比与阈值是可讨论的起点，落地前请结合自身收支、负债、年龄与风险承受能力调整。"
        "<b>有效性判据（本能力不要求频繁更新）</b>：生成日 {DATE}，有效至 {VALID_UNTIL}（≤180 天）；"
        "同时监测 5 个锚点（" + ANCHOR_TEXT + "），任一锚点自生成日起漂移超过其阈值则本配置需重新生成。"
        "<b>已知边界</b>：① QDII 有额度与溢价问题，<b>当前紧张程度见 01 节专项说明</b>；② 汇率波动会放大或抵消海外资产收益；"
        "③ A股红利类资产的股息税按持有期限差异化，长期持有更有利；④ 本报告未考虑个人税务、社保与商业保险配置；"
        "⑤ 02 节的基金代码经 2026-09-30 核实，但<b>份额类别、限购额度与费率会变动</b>，下单前以支付宝页面为准；"
        "⑥ 回测<b>窗口仅 4.69 年、且含美股与黄金的双重大牛市</b>，收益不可外推（前瞻中枢另列），"
        "<b>回撤数据比收益数据更可信</b>。"
        "投资有风险，决策请独立判断。本报告仅供研究参考，不构成个人投资建议。"
        ).replace("{DATE}", DATE).replace("{VALID_UNTIL}", VALID_UNTIL)

TPL = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>价值投资配置___DATE__</title>
<style>
  :root {
    --brand:#1f3a93; --brand-2:#2f56c9; --brand-soft:#eef1fa;
    --gold:#c9a227; --gold-soft:#faf5e3;
    --red:#e5484d; --green:#2fa36b;
    --bg:#f4f5f7; --surface:#ffffff; --border:#e8eaee;
    --ink:#18202f; --ink-2:#5b6470; --ink-3:#9aa1ad;
    --radius:14px;
    --shadow-sm:0 1px 3px rgba(24,32,47,.06);
    --shadow-md:0 6px 20px rgba(24,32,47,.08);
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--bg); color:var(--ink); font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; font-size:14px; line-height:1.6; }
  .wrap { max-width:1200px; margin:0 auto; padding:24px 24px 60px; }
  .num { font-variant-numeric:tabular-nums; font-feature-settings:"tnum"; }
  .pill { display:inline-block; font-size:11px; font-weight:700; padding:3px 10px; border-radius:20px; }
  .pill.brand { background:var(--brand-soft); color:var(--brand); border:1px solid #d5def5; }
  .pill.gold { background:var(--gold-soft); color:#8a6d12; border:1px solid #eddcab; }
  .hero { background:linear-gradient(150deg,#ffffff 30%,#fbfcfe 100%); border:1px solid var(--border); border-radius:18px; box-shadow:var(--shadow-md); padding:24px 28px; display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:16px; position:relative; overflow:hidden; }
  .hero::before { content:""; position:absolute; right:-70px; top:-70px; width:240px; height:240px; border-radius:50%; background:radial-gradient(circle,rgba(201,162,39,.12),transparent 65%); }
  .hero::after { content:""; position:absolute; left:-50px; bottom:-90px; width:200px; height:200px; border-radius:50%; background:radial-gradient(circle,rgba(31,58,147,.06),transparent 70%); }
  .hero .big { position:relative; z-index:1; min-width:0; flex:1 1 320px; }
  .hero .title { font-size:24px; font-weight:800; letter-spacing:-.5px; }
  .hero .tcode { font-size:14px; color:var(--ink-3); font-weight:600; letter-spacing:.5px; margin-left:8px; vertical-align:3px; }
  .hero .sub { margin-top:8px; font-size:12.5px; color:var(--ink-3); }
  .hero .sub .pill { margin-right:6px; }
  .hero .kpis { display:flex; gap:24px; position:relative; z-index:1; flex-wrap:wrap; flex:0 1 auto; }
  .hero .kpi { text-align:right; }
  .hero .kpi .v { font-size:17px; font-weight:800; }
  .hero .kpi .v.up { color:var(--red); } .hero .kpi .v.dn { color:var(--green); } .hero .kpi .v.gd { color:var(--gold); } .hero .kpi .v.hot { color:var(--red); }
  .hero .kpi .k { font-size:11.5px; color:var(--ink-3); margin-top:2px; }
  .sec { display:flex; align-items:center; justify-content:space-between; margin:30px 2px 12px; }
  .sec h2 { font-size:15px; font-weight:700; letter-spacing:.2px; display:flex; align-items:center; gap:9px; }
  .sec h2 .no { font-size:11px; font-weight:800; color:#fff; background:linear-gradient(180deg,var(--gold),#a8871d); border-radius:5px; padding:2px 6px; letter-spacing:0; }
  .sec h2::after { content:""; width:4px; height:16px; border-radius:2px; background:linear-gradient(180deg,var(--gold),var(--brand)); }
  .sec .hint { font-size:12px; color:var(--ink-3); font-weight:400; }
  .card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:16px 18px; box-shadow:var(--shadow-sm); }
  .card h3 { font-size:13.5px; font-weight:700; margin-bottom:8px; display:flex; align-items:center; gap:8px; }
  .card h3 .unit { font-size:11px; color:var(--ink-3); font-weight:400; }
  .sub-h { font-size:12px; font-weight:700; color:var(--brand); margin:16px 0 8px; display:flex; align-items:center; gap:7px; }
  .sub-h::before { content:""; width:3px; height:12px; border-radius:2px; background:var(--brand-2); }
  .grid-2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:14px; }
  .grid-3 { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th { text-align:left; font-size:11.5px; color:var(--ink-3); font-weight:600; padding:6px 8px; border-bottom:2px solid var(--border); white-space:nowrap; }
  td { padding:7px 8px; border-bottom:1px dashed #f0f1f4; vertical-align:top; }
  tbody tr:nth-child(even) { background:#fafbfc; }
  tbody tr:hover { background:var(--brand-soft); }
  .insight { margin-top:12px; padding:10px 14px; border-radius:10px; background:linear-gradient(120deg,#fdf9ec,#faf3d8); border:1px solid #eddcab; font-size:12.5px; font-weight:600; color:#8a6d12; line-height:1.7; }
  .srcnote { margin-top:8px; font-size:11px; color:var(--ink-3); line-height:1.7; }
  .sum-row { display:flex; align-items:baseline; gap:8px; padding:9px 0; border-bottom:1px dashed #f0f1f4; font-size:13px; flex-wrap:wrap; }
  .sum-row:last-child { border-bottom:none; }
  .sum-tag { flex-shrink:0; font-size:11px; font-weight:800; color:#fff; background:linear-gradient(180deg,var(--gold),#a8871d); border-radius:5px; padding:2px 9px; }
  .sum-tag2 { flex-shrink:0; font-size:11px; font-weight:800; color:var(--brand); background:var(--brand-soft); border:1px solid #d5def5; border-radius:5px; padding:2px 9px; }
  .note { font-size:11px; color:var(--ink-3); margin-top:16px; line-height:1.8; border-top:1px dashed var(--border); padding-top:12px; }
  .scroll { overflow-x:auto; }
  .scroll table { min-width:780px; }
  .wmain table { min-width:1080px; }
  @media print { body{background:#fff} .card{box-shadow:none} }
  @media (max-width:760px) { .hero{flex-direction:column;align-items:flex-start} .hero .kpis{width:100%;justify-content:space-between} }
</style></head><body><div class="wrap">

<div class="hero">
  <div class="big">
    <div class="title">__NAME__<span class="tcode">__CODE__</span></div>
    <div class="sub"><span class="pill gold">能力 #13</span><span class="pill brand">__GEN__</span>
      <span class="pill brand">生成 __DATE__</span><span class="pill brand">有效至 __VALID_UNTIL__</span></div>
  </div>
  <div class="kpis">__HERO_KPIS__</div>
</div>

<div class="insight">__CORE_INSIGHT__</div>

<div class="sec"><h2><span class="no">01</span>每月怎么做</h2><span class="hint">每月 10 号发钱后按此表分配 · 只看月结余，与存款无关</span></div>
<div class="card scroll"><table>
<tr>__MONTHLY_HEAD__</tr>
__MONTHLY_ROWS__
</table></div>
<div class="card" style="margin-top:12px;border-color:#f0c9c9;background:#fffbfb">
<div style="font-size:13px;font-weight:700;color:var(--red);margin-bottom:6px">⚠️ 美股这一类买不到足额，怎么办</div>
<div style="font-size:12.5px;color:var(--ink-2)">__QDII_WARN__</div></div>

<div class="sec"><h2><span class="no">02</span>五类资产：买什么 · 怎么投 · 怎么撤</h2><span class="hint">占比三档 = 稳健 / 平衡（默认）/ 进取 · 场外 10 元起、可自动定投 · 长期持有统一选 A 类（1 年以内才选 C 类）</span></div>
<div class="card scroll wmain"><table>
<tr>__MAIN_HEAD__</tr>
__MAIN_ROWS__
</table></div>
<div class="sub-h">怎么调：再平衡与执行铁律</div>
<div class="card">__RULES_SHORT__</div>

<div class="sec"><h2><span class="no">03</span>现在贵不贵</h2><span class="hint">数据 2026-09-30 核实 · 看历史分位，不看绝对值</span></div>
<div class="card scroll"><table>
<tr>__VAL_HEAD__</tr>
__VAL_ROWS__
</table>
<div class="srcnote">__VAL_SRC__</div></div>

<div class="sec"><h2><span class="no">04</span>判据与证据</h2><span class="hint">为什么这样分 · 定投要投多久 · 这套配比过去跑出什么</span></div>
<div class="grid-3">__PILLARS__</div>
<div class="sub-h">跨资产同窗口对比（近 5 年，同口径）</div>
<div class="card scroll"><table>
<tr>__CMP_HEAD__</tr>
__CMP_ROWS__
</table></div>
<div class="sub-h">定投要投多久才安全（A股全市场等权，全部起点滚动）</div>
<div class="card scroll"><table>
<tr>__HORIZON_HEAD__</tr>
__HORIZON_ROWS__
</table></div>
<div class="insight">__EVID_INSIGHT__</div>
<div class="sub-h">这套配比的历史回测与压力边界（2021-11 ~ 2026-10，4.69 年）</div>
<div class="card scroll"><table>
<tr>__BT2_HEAD__</tr>
__BT2_ROWS__
</table></div>
<div class="sub-h">逐年收益</div>
<div class="card scroll"><table>
<tr>__BT2_YEAR_HEAD__</tr>
__BT2_YEAR_ROWS__
</table></div>
<div class="insight">__BT2_INSIGHT__</div>

<div class="sec"><h2><span class="no">05</span>不做什么</h2><span class="hint">八条硬约束 —— 比「买什么」更影响最终结果</span></div>
<div class="card">__AVOID__</div>

<div class="note">__NOTE__</div>
</div></body></html>"""


# ================= 渲染 =================
def hero_kpis():
    return "".join(f'<div class="kpi"><div class="v {cls}">{v}</div><div class="k">{k}</div></div>'
                   for v, k, cls in HERO_KPIS)


def _thead(head):
    return "".join(f"<th>{h}</th>" for h in head)


def _num_rows(rows):
    return "".join("<tr>" + "".join(f'<td class="num" style="font-size:12.5px">{c}</td>' for c in r) + "</tr>"
                   for r in rows)


def main_rows():
    """执行总表：占比列**由 ALLOC 生成**（单一数据源），资产名需与 ALLOC 一一对应。"""
    amap = {r[0]: r for r in ALLOC}
    out = []
    for name, mode, fund, how, sell, now in MAIN:
        a = amap[name]
        out.append(f'<tr><td><b>{name}</b>'
                   f'<div style="font-size:11.5px;color:var(--brand);font-weight:700;margin-top:2px">{mode}</div></td>'
                   f'<td style="font-size:12px">{fund}</td>'
                   f'<td class="num" style="white-space:nowrap;font-size:12.5px">'
                   f'{a[2]} / <b style="color:var(--brand)">{a[3]}</b> / {a[4]}</td>'
                   f'<td style="font-size:12px">{how}</td>'
                   f'<td style="font-size:12px;color:var(--ink-2)">{sell}</td>'
                   f'<td style="font-size:12px;border-left:2px solid #eddcab;background:#fffdf6">{now}</td></tr>')
    out.append('<tr style="background:var(--brand-soft)"><td><b>合计</b></td>'
               '<td style="font-size:12px;color:var(--ink-2)">5 类资产，全部为核心</td>'
               '<td class="num"><b>100% / 100% / 100%</b></td>'
               '<td colspan="3" style="font-size:12px;color:var(--ink-2)">'
               '占比顺序 = 稳健 / <b>平衡（默认）</b> / 进取　·　' + ALLOC_NOTE + '</td></tr>')
    return "".join(out)


def pillars_cards():
    return "".join(f'<div class="card"><h3>{t}</h3>'
                   f'<div style="font-size:12px;color:var(--brand);font-weight:700;margin-bottom:6px">适用：{cond}</div>'
                   f'<div style="font-size:12.5px;color:var(--ink-2)">{rule}</div>'
                   f'<div style="margin-top:8px;padding-top:8px;border-top:1px dashed #f0f1f4;'
                   f'font-size:12px;color:var(--green)">反例：{bad}</div></div>'
                   for t, cond, rule, bad in PILLARS)


def monthly_rows():
    """每月 10 号发薪后的分配 —— **只看月结余，与现有存款无关**（2026-10-08 用户要求简化）。

    用户原话：「你别考虑我现有存款了，你就当我没存款，只根据我以后的收支，
    告诉我每月应该怎么办就行」——月结余 = 收入 − 支出，本来就与存款无关，
    所以删掉了原来那套「总资产 / 可配置资产 / 目标金额 / 已持有 / 还差」的静态盘点。
    """
    bond_m = MON_AMT["国内债券"]          # 债券暂停 → 其额度并入现金留存
    cash_m = MON_AMT["现金 / 货币"]
    how = {
        "A股红利低波": "每月买 1 笔；股息再投资",
        "美股宽基（QDII）": "拆 5~6 只（<b>跨基金公司</b>），<b>每日各买约 10 元</b>（单日限额所迫）",
        "国内债券": "<b>暂停</b> —— 现有持仓已超配（见下）",
        "黄金": "每月 1 笔（不必按季）",
        "现金 / 货币": "留存（含被暂停的债券额）",
    }
    rows = []
    for r in ALLOC:
        k = r[0]
        if k == "国内债券":
            cell = (f"<b>0</b><div style='font-size:11px;color:var(--ink-3)'>"
                    f"原 {MON_AMT[k]:,.0f} 暂停</div>")
        elif k == "现金 / 货币":
            cell = (f"<b>{cash_m + bond_m:,.0f}</b><div style='font-size:11px;color:var(--ink-3)'>"
                    f"{cash_m:,.0f} ＋ 债券 {bond_m:,.0f}</div>")
        else:
            cell = f"<b>{MON_AMT[k]:,.0f}</b>"
        rows.append(f'<tr><td><b>{k}</b></td><td class="num">{cell}</td>'
                    f'<td style="font-size:12px;color:var(--ink-2)">{how.get(k, "")}</td></tr>')
    rows.append(f'<tr><td><b>合计</b></td><td class="num"><b>{MON_SURPLUS:,.0f}</b></td>'
                f'<td style="font-size:12px;color:var(--ink-2)">'
                f'＝ 月结余（收入 {MON_INCOME:,.0f} − 支出 {MON_EXPENSE:,.0f}）</td></tr>')
    rows.append(
        '<tr><td colspan="3" style="font-size:12px;color:var(--ink-2);background:#fcfcfd;line-height:1.8">'
        f'<b>唯一例外的债券</b>：你已持有的 013225（景顺长城安景一年持有混合A，<b>锁定至 2027-07-10</b>）'
        f'＋ 001235（中银国有企业债A）都属于债券档、且已<b>超配</b> → 所以本档每月不买债券，'
        f'那 {bond_m:,.0f} 元先并入现金留存，等债券占比回落到目标再恢复。'
        '　<b>其余四档按上表每月照投即可，各档占比自动维持</b>，不需要再盯任何「目标数」。'
        '　<b>只有一种情况停投某档</b>：它触了单档上限（美股 ≤50%、黄金 ≥20%）→ 该档停投、钱转低配档。'
        '</td></tr>')
    return "".join(rows)


def rules_short():
    return "".join(f'<div class="sum-row"><span class="sum-tag">{tag}</span>'
                   f'<span style="flex:1;color:var(--ink-2)">{desc}</span></div>'
                   for tag, desc in RULES_SHORT)


def avoid_rows():
    return "".join(f'<div class="sum-row"><span class="sum-tag2">✕</span>'
                   f'<span style="flex:1;color:var(--ink-2)"><b>{a}</b> —— {b}</span></div>'
                   for a, b in AVOID)


def build():
    # 断言：执行总表与 ALLOC 必须一一对应（防双份数据漂移）
    assert [m[0] for m in MAIN] == [a[0] for a in ALLOC], \
        f"MAIN 的资产名与 ALLOC 不一致：{[m[0] for m in MAIN]} vs {[a[0] for a in ALLOC]}"
    out = TPL
    rep = {
        "__NAME__": CFG["name"], "__CODE__": CFG["code"], "__GEN__": GEN,
        "__DATE__": DATE, "__VALID_UNTIL__": VALID_UNTIL,
        "__HERO_KPIS__": hero_kpis(), "__CORE_INSIGHT__": CORE_INSIGHT,
        "__MAIN_HEAD__": _thead(("资产 · 操作方式", "场外基金（支付宝可买）", "稳健 / 平衡 / 进取",
                                 "怎么投", "怎么撤", f"现在该怎么做（截至 {DATE_VAL}）")),
        "__MAIN_ROWS__": main_rows(),
        "__MONTHLY_HEAD__": _thead(MONTHLY_HEAD), "__MONTHLY_ROWS__": monthly_rows(),
        "__QDII_WARN__": QDII_WARN,
        "__VAL_HEAD__": _thead(VAL_HEAD), "__VAL_ROWS__": _num_rows(VAL),
        "__VAL_SRC__": VAL_SRC,
        "__RULES_SHORT__": rules_short(),
        "__PILLARS__": pillars_cards(),
        "__CMP_HEAD__": _thead(CMP_HEAD), "__CMP_ROWS__": _num_rows(CMP),
        "__HORIZON_HEAD__": _thead(HORIZON_HEAD), "__HORIZON_ROWS__": _num_rows(HORIZON),
        "__EVID_INSIGHT__": EVID_INSIGHT,
        "__BT2_HEAD__": _thead(BT2_HEAD), "__BT2_ROWS__": _num_rows(BT2),
        "__BT2_YEAR_HEAD__": _thead(BT2_YEAR_HEAD), "__BT2_YEAR_ROWS__": _num_rows(BT2_YEAR),
        "__BT2_INSIGHT__": BT2_INSIGHT,
        "__AVOID__": avoid_rows(), "__NOTE__": NOTE,
    }
    for k, v in rep.items():
        out = out.replace(k, v)
    left = [k for k in rep if k in out]
    assert not left, f"有未替换的占位符：{left}"
    assert "__" + "DATE__" not in out
    return out


if __name__ == "__main__":
    body = build()
    op = os.path.join(BASE, f"价值投资配置_{DATE.replace('-', '')}.html")
    with open(op, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    print(f"OK -> {op} | size: {os.path.getsize(op)} bytes")
