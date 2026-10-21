# -*- coding: utf-8 -*-
"""
AI 分析引擎 (ai_analysis_engine.py) v11.0.0

把 config/settings.json 中已声明但从未调用的 LLM 真正接进来。

支持三种 Provider（自动从 settings.json 或环境变量加载）：
- DeepSeek (provider=deepseek, 默认，国内直连友好)
- OpenAI 兼容 (provider=openai，含通义千问/Moonshot/Groq 等)
- Ollama 本地 (provider=ollama, 离线可用)

🆕 v11.0 模板扩充（11 类）：
v10.0 (7 类) + v11.0 新增 4 类：
  1. 期货专项分析（持仓+龙虎榜+升贴水+跨期套利+展期收益）
  2. 资金流分析（主力/北向/融资/ETF申赎+聪明钱+异动）
  3. 指数预测（PE分位+RS评分+宏观联动+趋势强度）
  4. 组合诊断（业绩归因+再平衡+集中度+风格漂移）

🆕 v11.0 现有模板强化：
  - market_regime: 加入期权 PCR / 波动率曲面 / AH 折溢价
  - macro_outlook: 加入房地产销售 / 社零 / 出口数据
  - risk_report: 加入流动性风险 / 情景分析 / 相关性矩阵
  - sector_rotation: 加入聪明钱动向 / ETF 申赎方向

设计原则：
1. 零依赖核心（urllib 标准库）
2. LLM 不可用时自动降级到模板化输出
3. 提示词模板与响应解析分离
4. 内置免责声明
5. 调用结果缓存
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)


# ============================================================================
# 1. LLM Provider 配置
# ============================================================================

@dataclass
class LLMConfig:
    """LLM 提供方配置。"""
    provider: str = "deepseek"        # deepseek / openai / ollama
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    api_key: str = ""
    temperature: float = 0.3          # 金融分析需要稳定输出
    max_tokens: int = 2000
    timeout: int = 60


# ============================================================================
# 2. LLM 客户端（OpenAI 兼容协议，DeepSeek/Ollama 都走同一接口）
# ============================================================================

class LLMClient:
    """LLM HTTP 客户端（OpenAI Chat Completions 兼容协议）。"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._session_lock = threading.Lock()

    def chat(self, messages: List[Dict[str, str]],
             temperature: Optional[float] = None,
             max_tokens: Optional[int] = None,
             stream: bool = False) -> Dict[str, Any]:
        """发送聊天请求。

        Args:
            messages: [{"role": "user", "content": "..."}]
            temperature: 采样温度（None=用配置）
            max_tokens: 最大 token（None=用配置）
            stream: 是否流式（暂未启用）

        Returns:
            {"success": bool, "content": str, "usage": {...}, "error": ""}
        """
        if not self.config.api_key and self.config.provider != "ollama":
            return {
                "success": False,
                "content": "",
                "error": f"未配置 {self.config.provider} API Key",
            }

        url = f"{self.config.base_url.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
            "stream": stream,
        }

        headers = {
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        try:
            req = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with self._session_lock:
                with urlopen(req, timeout=self.config.timeout) as resp:
                    body = resp.read().decode("utf-8")
                    data = json.loads(body)

            if "choices" not in data or not data["choices"]:
                return {
                    "success": False,
                    "content": "",
                    "error": f"LLM 响应无 choices: {json.dumps(data)[:200]}",
                }

            content = data["choices"][0].get("message", {}).get("content", "")
            return {
                "success": True,
                "content": content,
                "usage": data.get("usage", {}),
                "model": data.get("model", self.config.model),
            }
        except HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")[:300]
            except Exception:
                pass
            return {
                "success": False,
                "content": "",
                "error": f"HTTP {e.code}: {error_body}",
            }
        except URLError as e:
            return {
                "success": False,
                "content": "",
                "error": f"网络错误: {str(e)[:200]}",
            }
        except Exception as e:
            return {
                "success": False,
                "content": "",
                "error": f"调用异常: {str(e)[:200]}",
            }

    def is_available(self) -> bool:
        """检查 LLM 是否可用。"""
        if self.config.provider == "ollama":
            return True
        return bool(self.config.api_key)


# ============================================================================
# 3. 配置加载
# ============================================================================

def load_llm_config(settings_path: Optional[str] = None) -> LLMConfig:
    """从 settings.json 加载 LLM 配置，并支持环境变量覆盖。"""
    config = LLMConfig()

    # 默认值（DeepSeek 已在 settings.json 中声明）
    config.provider = "deepseek"
    config.base_url = "https://api.deepseek.com"
    config.model = "deepseek-chat"

    # 1) 先从 settings.json 读取基础配置
    if settings_path is None:
        candidates = [
            "config/settings.json",
            "../config/settings.json",
            "D:/claude 开发/skill of me/stock-researcher/config/settings.json",
        ]
        for p in candidates:
            if os.path.isfile(p):
                settings_path = p
                break

    if settings_path and os.path.isfile(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            llm_block = settings.get("llm", {})
            if llm_block.get("provider"):
                config.provider = llm_block["provider"]
            if llm_block.get("base_url"):
                config.base_url = llm_block["base_url"]
            if llm_block.get("model"):
                config.model = llm_block["model"]
            if isinstance(llm_block.get("temperature"), (int, float)):
                config.temperature = float(llm_block["temperature"])
            if isinstance(llm_block.get("max_tokens"), int):
                config.max_tokens = llm_block["max_tokens"]
        except Exception as e:
            logger.warning(f"加载 settings.json 失败: {e}")

    # 2) 环境变量覆盖（优先级最高）
    env_provider = os.environ.get("LLM_PROVIDER")
    if env_provider:
        config.provider = env_provider
    env_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    if env_key:
        config.api_key = env_key

    # 3) Provider 特定 base_url 兜底
    if config.provider == "deepseek" and "deepseek" not in config.base_url:
        config.base_url = "https://api.deepseek.com"
    elif config.provider == "openai" and "openai" not in config.base_url:
        config.base_url = "https://api.openai.com"
    elif config.provider == "ollama":
        config.base_url = config.base_url or "http://localhost:11434"

    return config


# ============================================================================
# 4. 提示词模板
# ============================================================================

PROMPT_TEMPLATES = {
    "stock_analysis": """你是中国 A 股市场的资深研究员。请基于以下量化数据，给出专业、客观、有深度的股票分析。

【股票基本信息】
代码：{code}
名称：{name}
市场：{market}

【实时行情】
当前价：{price}
涨跌幅：{change_pct}%
今日最高/最低：{high}/{low}
成交量：{volume}
成交额：{amount}

【估值指标】
市盈率(PE-TTM)：{pe_ttm}
市净率(PB)：{pb}
股息率：{div_yield}

【财务质量】
ROE：{roe}%
毛利率：{gross_margin}%
净利率：{net_margin}%
营收同比增长：{revenue_yoy}%
净利润同比增长：{profit_yoy}%

【技术面】
均线状态：{ma_status}
MACD：{macd}
RSI(14)：{rsi}
趋势判断：{trend}

【预测评分】
综合评分：{score}/100
短期(5日)方向：{short_term_view}
中期(3月)方向：{medium_term_view}

【大师共识】
看多：{bull_count} 位，看空：{bear_count} 位，中性：{neutral_count} 位

请按以下结构输出（每段 ≤150 字）：
1. **核心观点**（一句话定性）
2. **基本面评估**（行业地位/竞争优势/财务质量）
3. **技术面解读**（当前趋势/关键支撑压力位/量价关系）
4. **估值合理性**（与历史/同行对比）
5. **短期催化与风险**（3-5 条要点）
6. **综合评级**（强烈推荐/推荐/中性/谨慎/回避 + 置信度）

注意：评分≠盈利保证。仅供学习参考，不构成投资建议。
""",

    "fund_analysis": """你是公募基金研究专家。请基于以下数据，给出这只基金的深度解读。

【基金基本信息】
基金代码：{code}
基金名称：{name}
基金类型：{fund_type}

【业绩表现】
近1月：{ret_1m}%
近3月：{ret_3m}%
近6月：{ret_6m}%
近1年：{ret_1y}%
近3年：{ret_3y}%
成立以来：{ret_inception}%

【风险指标】
年化波动率：{vol}%
最大回撤：{max_dd}%
夏普比率：{sharpe}
索提诺：{sortino}

【相对基准】
基准名称：{benchmark}
Alpha：{alpha}
Beta：{beta}
信息比率：{ir}

【持仓风格】
前十大持仓占比：{top10_pct}%
持仓行业集中度：{industry_concentration}
平均PE：{avg_pe}

【经理信息】
姓名：{manager_name}
从业年限：{manager_years}年
管理规模：{aum}亿
代表作品：{rep_funds}

请按以下结构输出：
1. **核心定位**（基金类型/投资策略/适合投资者）
2. **业绩归因**（超额收益来源/择时/选股贡献）
3. **风格稳定性**（持仓/行业/规模风格是否漂移）
4. **经理能力评估**（从业背景/代表作/能力圈）
5. **风险点**（3-5 条）
6. **综合评级**（5星制）

注意：历史业绩不代表未来表现。
""",

    "market_regime": """你是 A 股市场策略分析师。请基于以下量化信号，判断当前市场体制。

【指数表现】
上证指数：{sh_close} ({sh_chg}%)
深证成指：{sz_close} ({sz_chg}%)
创业板指：{gem_close} ({gem_chg}%)
沪深300：{hs300_close} ({hs300_chg}%)
科创50：{star50_close} ({star50_chg}%)   # v11.0 新增

【市场宽度】
站上 20 日均线个股占比：{pct_above_ma20}%
站上 60 日均线个股占比：{pct_above_ma60}%
新高-新低比：{new_high_low_ratio}
McClellan 指标：{mcclellan}
Advance-Decline 比率：{ad_ratio}      # v11.0 新增

【波动率】
沪深 300 波动率(20日)：{hs300_vol}%
VIX（中国 ETF 期权隐含波动率）：{cn_vix}
波动率曲面 skew：{vol_skew}            # v11.0 新增
期权 PCR（看跌/看涨比率）：{pcr}      # v11.0 新增

【资金面】
北向资金 5日累计：{north_bound}亿
融资余额变化：{margin_change}亿
两融余额：{margin_total}亿
ETF 当日净申赎：{etf_flow}亿         # v11.0 新增

【跨市场联动】
AH 折溢价指数：{ah_premium}            # v11.0 新增
港股恒生：{hsi_chg}%                  # v11.0 新增
美元/人民币：{usdcny_change}%         # v11.0 新增

【量化信号】
Hurst 指数（市场持续性）：{hurst}
趋势结构评分：{trend_structure}
动量评分：{momentum_score}
市场体制分类：{regime_label}

请按以下结构输出：
1. **市场体制判断**（强势上涨/震荡偏强/震荡/震荡偏弱/弱势下跌 — 选择最接近的一个）
2. **核心驱动**（推动当前体制的 2-3 个关键因素，结合 PCR/资金/波动率多维证据）
3. **板块轮动信号**（当前领涨/领跌板块及逻辑）
4. **关键支撑/压力位**（上证指数）
5. **风险预警**（可能打破当前体制的 3 个触发条件，关注 AH 折溢价与期权 PCR 异动）
6. **策略建议**（仓位建议/风格建议/操作节奏）

注意：市场分析仅供参考，不构成投资建议。
""",

    "master_council": """你是投资大师圆桌会议主持人。下面是 6 位投资大师对同一只股票/资产的观点，请综合给出圆桌结论。

【标的】{target}

【大师观点】
- 沃伦·巴菲特：{buffett_view}
- 本杰明·格雷厄姆：{graham_view}
- 彼得·林奇：{lynch_view}
- 乔治·索罗斯：{soros_view}
- 菲利普·费雪：{fisher_view}
- 霍华德·马克斯：{marks_view}

【共识统计】
看多：{bull_count} 位 | 看空：{bear_count} 位 | 中性：{neutral_count} 位
平均置信度：{avg_confidence}%

【综合数据】
{context}

请按以下结构输出：
1. **圆桌共识**（一致/分歧/明显对立）
2. **共识要点**（多数大师认同的 2-3 个核心观点）
3. **关键分歧**（最不一致的维度及原因）
4. **最具说服力的观点**（你认为哪位大师的逻辑最贴合当前情况 + 理由）
5. **综合建议**（基于圆桌 + 数据，给出 1-2 句话的操作建议）

注意：圆桌分析是思维框架辅助，不构成投资建议。
""",

    "macro_outlook": """你是宏观策略分析师。请基于以下数据，给出当前宏观环境判断。

【经济增长】
GDP 同比：{gdp_yoy}%
PMI 制造业：{pmi_mfg}
PMI 非制造业：{pmi_non_mfg}
工业增加值：{industrial_yoy}%        # v11.0 新增
房地产销售面积同比：{real_estate_yoy}%  # v11.0 新增
社会消费品零售总额同比：{retail_yoy}%   # v11.0 新增
出口同比（人民币）：{export_yoy}%      # v11.0 新增

【通胀】
CPI 同比：{cpi_yoy}%
PPI 同比：{ppi_yoy}%
核心 CPI：{core_cpi_yoy}%             # v11.0 新增

【货币金融】
M2 同比：{m2_yoy}%
社融存量同比：{tsf_yoy}%
新增人民币贷款(本月)：{new_loans}亿
新增人民币存款：{new_deposits}亿       # v11.0 新增

【利率水平】
1年期 LPR：{lpr_1y}%
5年期 LPR：{lpr_5y}%
10年期国债收益率：{bond_10y}%
DR007：{dr007}%                       # v11.0 新增

【外部环境】
美元指数：{dxy}
人民币汇率：{usdcny}
中美10年期利差：{cn_us_spread}%
中美短端利差：{cn_us_short_spread}%   # v11.0 新增
美联储隔夜利率：{fed_funds}%          # v11.0 新增

请按以下结构输出：
1. **经济周期定位**（复苏/过热/滞胀/衰退，结合房地产/社零/出口验证）
2. **货币政策方向**（宽松/中性/收紧 — 预期，关注 DR007 走势）
3. **股市影响**（顺周期/逆周期板块受益逻辑）
4. **债市判断**（利率方向预期）
5. **汇率风险**（人民币贬值/升值压力）
6. **配置建议**（股债商汇配置比例建议）

注意：宏观分析为框架性参考，不构成投资建议。
""",

    "risk_report": """你是组合风险管理专家。请基于以下数据，生成风险评估报告。

【组合概况】
总市值：{total_value}万
持仓数量：{holdings_count} 只
现金比例：{cash_pct}%
行业集中度（HHI）：{industry_hhi}
个股最大权重：{max_weight_pct}%
最近调仓时间：{last_rebalance_days}天前   # v11.0 新增
风格漂移指标：{style_drift}              # v11.0 新增

【风险指标】
组合年化波动率：{portfolio_vol}%
组合最大回撤(1Y)：{max_dd_1y}%
组合最大回撤(3Y)：{max_dd_3y}%
VaR(95%, 1日)：{var_95}%
VaR(99%, 1日)：{var_99}%
Expected Shortfall(95%)：{es_95}%

【压力测试】
2008 情景下回撤：{stress_2008}%
2020 疫情下回撤：{stress_covid}%
利率+100bp 冲击：{ir_shock}%
通胀+200bp 冲击：{inflation_shock}%     # v11.0 新增

【因子暴露】
市场(Beta)：{beta_market}
规模(SMB)：{beta_size}
价值(HML)：{beta_value}
动量(UMD)：{beta_momentum}
质量(RMW)：{beta_quality}

【流动性风险 v11.0】
持仓平均日成交额：{avg_daily_turnover}万
变现 5% 用时(估算)：{days_to_liquidate}天
涨停板持仓占比：{limit_up_holding_pct}%
停牌/退市风险持仓：{suspended_holding}只

【相关性矩阵 v11.0】
最高相关对：{highest_corr_pair}（相关系数 {highest_corr_value}）
最低相关对：{lowest_corr_pair}（相关系数 {lowest_corr_value}）

请按以下结构输出：
1. **整体风险评级**（低/中低/中/中高/高）
2. **集中度风险**（行业/个股/风格）
3. **尾部风险**（黑天鹅情景下的潜在损失，含通胀冲击）
4. **相关性风险**（持仓之间是否分散，结合相关性矩阵）
5. **流动性风险**（变现能力评估，涨停板持仓预警）
6. **优化建议**（3-5 条可执行建议，含再平衡节奏）

注意：历史回撤不代表未来风险。
""",

    "sector_rotation": """你是行业策略分析师。请基于以下数据，分析当前板块轮动格局。

【RPS 排名（相对强度）前 10 行业】
{rps_top10}

【RPS 排名后 10 行业】
{rps_bottom10}

【行业资金流向（5日累计）】
流入：{inflow_top5}
流出：{outflow_bottom5}

【聪明钱动向 v11.0】                       # v11.0 新增
聪明钱净流入前 3：{smart_money_inflow_top3}
聪明钱净流出前 3：{smart_money_outflow_top3}

【ETF 申赎方向 v11.0】                       # v11.0 新增
ETF 净申购前 3：{etf_inflow_top3}
ETF 净赎回前 3：{etf_outflow_top3}

【行业估值分位】
PE 历史分位(全A)：{all_pe_pct}
PB 历史分位(全A)：{all_pb_pct}

【主题热度】
热门主题：{hot_themes}

请按以下结构输出：
1. **当前轮动阶段**（复苏期早段/复苏期中段/过热期/滞胀期/衰退期）
2. **领涨板块逻辑**（为什么这些板块领涨 — 2-3 句话，结合聪明钱与 ETF 流向验证）
3. **弱势板块原因**（为什么这些板块承压）
4. **下一步可能轮动的方向**（基于美林时钟/资金流向/ETF 申赎 推演）
5. **配置建议**（超配/标配/低配的具体行业及理由）

注意：板块分析为框架性参考，不构成投资建议。
""",

# ============================================================================
# v11.0 新增 4 个模板
# ============================================================================

"futures_analysis": """你是期货研究员。请基于以下数据，给出期货合约的深度解读。

【合约基本信息】
合约代码：{contract}
品种：{symbol}
交易所：{exchange}（上期所 SHFE / 大商所 DCE / 郑商所 CZCE / 中金所 CFFEX）
合约月份：{delivery_month}

【行情快照】
最新价：{price}
涨跌：{change} ({change_pct}%)
今开：{open}
最高：{high}
最低：{low}
昨结：{prev_settlement}

【持仓与成交】
持仓量：{open_interest}手
成交量：{volume}手
日增仓：{oi_change}手                  # v11.0 新增
成交额：{turnover}亿

【基差与升贴水 v11.0】
现货价格：{spot_price}                  # v11.0 新增
基差（期-现）：{basis}                  # v11.0 新增
基差率：{basis_pct}%                    # v11.0 新增
近月-远月价差：{spread_near_far}        # v11.0 新增
展期收益年化：{roll_yield}%             # v11.0 新增

【龙虎榜 v11.0】
前 5 名多头持仓：{top5_long}
前 5 名空头持仓：{top5_short}
净持仓集中度：{oi_concentration}%
多空比：{long_short_ratio}

【库存与基本面 v11.0】
库存（交易所周报）：{inventory}
库存环比：{inventory_chg}%
现货升贴水：{spot_premium}%

【波动率与预测】
ATR(20日)：{atr}
20日波动率：{vol_20d}%
60日波动率：{vol_60d}%
5日预测置信区间：{forecast_5d}
20日预测置信区间：{forecast_20d}

请按以下结构输出：
1. **行情定性**（趋势/震荡/反转 — 一句话定性）
2. **持仓结构解读**（多空力量对比，结合龙虎榜与日增仓）
3. **基差与跨期套利机会**（期现套利/跨期套利可行性）
4. **基本面驱动**（库存/供需/季节性规律）
5. **波动率展望**（扩张/压缩预期）
6. **策略建议**（单边/套利/对冲 + 仓位 + 止损位 + 持有周期）

注意：期货分析为框架性参考，不构成投资建议。
""",

"money_flow_analysis": """你是资金流向专家。请基于以下数据，分析资金流向与主力动向。

【标的】
代码：{code}
名称：{name}

【主力资金 v11.0】
主力净流入：{main_net_inflow}亿
超大单净流入：{super_large_net}亿
大单净流入：{large_net}亿
中单净流入：{medium_net}亿
小单净流入：{small_net}亿
主力净流入占比：{main_pct}%

【北向资金 v11.0】
北向持股变化（1日）：{north_1d}亿
北向持股变化（5日）：{north_5d}亿
北向持股变化（20日）：{north_20d}亿
持股比例：{north_holding_pct}%

【融资融券 v11.0】
融资余额：{margin_balance}亿
融资余额变化（1日）：{margin_1d}亿
融资余额变化（5日）：{margin_5d}亿
融券余额：{short_balance}亿
融资买入额占比：{margin_buy_pct}%

【ETF 申赎 v11.0】
对应 ETF 名称：{etf_name}
ETF 净申赎（1日）：{etf_flow_1d}亿
ETF 净申赎（5日）：{etf_flow_5d}亿
ETF 折溢价率：{etf_premium}%

【聪明钱模型 v11.0】
聪明钱评分：{smart_money_score}（0-100）
异常订单笔数：{abnormal_orders}
大单净买入方向：{smart_money_direction}（买入/卖出/中性）

【股价异动 v11.0】
5日内涨停次数：{limit_up_count}
5日内跌停次数：{limit_down_count}
振幅异常（>5%）：{abnormal_amplitude_count}次
成交量异动（>2倍均值）：{abnormal_volume_count}次

请按以下结构输出：
1. **资金面定性**（强势流入/温和流入/中性/温和流出/强势流出）
2. **主力意图解读**（主力资金 + 北向 + 融资 三方验证）
3. **聪明钱动向**（基于大单+异常订单+ETF 流向的复合信号）
4. **股价异动解读**（涨停/振幅/成交量异动的内在原因）
5. **持续性判断**（本次资金流入是趋势性还是脉冲性）
6. **操作建议**（是否跟随资金/何时兑现/关注信号反转）

注意：资金流向数据仅供参考，不构成投资建议。
""",

"index_forecast": """你是指数研究员。请基于以下数据，预测指数未来走势。

【指数基本信息】
代码：{code}
名称：{name}
最新点位：{price}
涨跌：{change_pct}%

【估值分位 v11.0】
PE-TTM：{pe_ttm}
PE 历史分位（10年）：{pe_pct_10y}%
PE 历史分位（5年）：{pe_pct_5y}%
PB 历史分位（10年）：{pb_pct_10y}%
股息率：{div_yield}%

【技术面】
20日均线：{ma20}
60日均线：{ma60}
120日均线：{ma120}
当前相对位置：{ma_position}
RSI(14)：{rsi}
MACD：{macd}

【相对强度 v11.0】
RS(20日) vs 沪深 300：{rs_20d_vs_hs300}
RS(60日) vs 沪深 300：{rs_60d_vs_hs300}
RPS 百分位（市场内）：{rps_pct}%

【趋势强度 v11.0】
ADX(14)：{adx}
趋势结构评分：{trend_score}（0-100）
动量评分：{momentum_score}（0-100）

【宏观联动 v11.0】
社融存量同比：{tsf_yoy}%
10年期国债收益率：{bond_10y}%
工业增加值同比：{industrial_yoy}%
美元指数：{dxy}

【预测】
1月方向预测：{forecast_1m_direction}（概率 {forecast_1m_prob}%）
3月方向预测：{forecast_3m_direction}（概率 {forecast_3m_prob}%）
6月方向预测：{forecast_6m_direction}（概率 {forecast_6m_prob}%）

请按以下结构输出：
1. **当前位置评估**（估值分位+技术位置+趋势强度的三维定位）
2. **驱动逻辑**（推动指数上行的核心逻辑 2-3 条）
3. **风险因素**（可能拖累指数的关键风险 2-3 条）
4. **多周期预测**（1M / 3M / 6M 方向 + 关键催化 + 时间窗）
5. **配置建议**（对应指数 ETF 的加减仓节奏 + 行业暴露建议）

注意：指数预测仅供参考，不构成投资建议。
""",

"portfolio_diagnosis": """你是投顾组合诊断专家。请基于以下数据，对用户持仓进行深度诊断。

【组合概况】
总市值：{total_value}万
持仓数量：{holdings_count} 只
现金比例：{cash_pct}%
组合年化收益率：{annual_return}%
基准年化收益率：{benchmark_return}%
组合 alpha：{alpha}%

【业绩归因 v11.0】
行业配置贡献：{allocation_contribution}%
个股选择贡献：{selection_contribution}%
交互作用贡献：{interaction_contribution}%

【持仓明细（前 10）】
{holdings_detail}

【集中度风险】
行业 HHI 集中度：{industry_hhi}
个股最大权重：{max_weight_pct}%
前 3 大持仓占比：{top3_pct}%
风格漂移指标：{style_drift}        # v11.0 新增

【风格暴露 v11.0】
大盘/小盘：{size_exposure}（1=大盘，0=小盘）
价值/成长：{value_growth_exposure}（1=价值，0=成长）
质量得分：{quality_score}（0-10）
动量得分：{momentum_score}（0-10）

【再平衡建议 v11.0】
上次调仓时间：{last_rebalance_days}天前
目标偏离度：{target_drift}%（vs 战略配置）
建议调仓幅度：{suggested_turnover}%
再平衡方式：{rebalance_method}（定期/阈值/智能）

【回撤与恢复】
当前回撤：{current_dd}%
最大回撤（1Y）：{max_dd_1y}%
回撤恢复天数：{dd_recovery_days}天

请按以下结构输出：
1. **整体评级**（优秀/良好/中等/需调整 — 1-2 句话定性）
2. **超额收益来源**（alpha 的归因分解）
3. **风格漂移检测**（是否偏离用户风险偏好）
4. **集中度风险点**（3-5 条具体风险）
5. **再平衡建议**（明确哪些品种加/减/保持，给出比例与时机）
6. **长期持有建议**（未来 3-6 个月的策略方向）

注意：组合诊断仅供参考，不构成投资建议。
""",
}


# ============================================================================
# 5. AI 分析引擎
# ============================================================================

@dataclass
class AnalysisResult:
    """AI 分析结果。"""
    task_type: str
    success: bool = False
    content: str = ""
    error: str = ""
    model: str = ""
    tokens_used: int = 0
    latency_ms: float = 0.0
    is_fallback: bool = False  # 是否使用了模板兜底
    timestamp: str = ""
    context: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")


class AIAnalysisEngine:
    """AI 分析引擎主类。"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or load_llm_config()
        self.client = LLMClient(self.config)
        self._cache: Dict[str, AnalysisResult] = {}
        self._cache_lock = threading.Lock()

    def is_available(self) -> bool:
        return self.client.is_available()

    def status(self) -> Dict[str, Any]:
        return {
            "provider": self.config.provider,
            "model": self.config.model,
            "base_url": self.config.base_url,
            "available": self.is_available(),
            "api_key_configured": bool(self.config.api_key),
        }

    def _cache_key(self, task_type: str, context: Dict[str, Any]) -> str:
        ctx_str = json.dumps(context, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(f"{task_type}:{ctx_str}".encode("utf-8")).hexdigest()

    def _format_prompt(self, task_type: str, context: Dict[str, Any]) -> str:
        """根据上下文格式化提示词。"""
        template = PROMPT_TEMPLATES.get(task_type)
        if not template:
            raise ValueError(f"未知任务类型: {task_type}")
        try:
            return template.format(**context)
        except KeyError as e:
            # 缺失字段用占位符填充
            missing = e.args[0]
            logger.warning(f"提示词模板缺少字段: {missing}")
            context.setdefault(missing, "N/A")
            return template.format(**context)

    def analyze(self, task_type: str, context: Dict[str, Any],
                use_cache: bool = True) -> AnalysisResult:
        """执行 AI 分析。

        Args:
            task_type: 分析类型 (stock_analysis/fund_analysis/market_regime/...)
            context: 上下文数据
            use_cache: 是否使用缓存

        Returns:
            AnalysisResult
        """
        cache_key = self._cache_key(task_type, context)

        if use_cache:
            with self._cache_lock:
                if cache_key in self._cache:
                    return self._cache[cache_key]

        # 不可用时降级
        if not self.is_available():
            fallback = self._fallback_template(task_type, context)
            result = AnalysisResult(
                task_type=task_type,
                success=True,
                content=fallback,
                is_fallback=True,
                error="LLM 不可用，已使用模板化输出",
                context=context,
            )
            if use_cache:
                with self._cache_lock:
                    self._cache[cache_key] = result
            return result

        # 格式化提示词
        try:
            prompt = self._format_prompt(task_type, context)
        except Exception as e:
            return AnalysisResult(
                task_type=task_type,
                success=False,
                error=f"格式化提示词失败: {e}",
                context=context,
            )

        # 调用 LLM
        start = time.monotonic()
        response = self.client.chat([
            {"role": "system", "content": "你是中国 A 股市场的资深投研专家，输出专业、客观、有数据支撑。结尾必须包含免责声明。"},
            {"role": "user", "content": prompt},
        ])
        latency = (time.monotonic() - start) * 1000

        if not response["success"]:
            fallback = self._fallback_template(task_type, context)
            result = AnalysisResult(
                task_type=task_type,
                success=True,
                content=fallback,
                is_fallback=True,
                error=f"LLM 调用失败: {response['error']}，已降级到模板化输出",
                latency_ms=latency,
                context=context,
            )
        else:
            content = response["content"] + "\n\n---\n⚠️ 免责声明：本分析由 AI 生成，仅供学习研究参考，不构成投资建议。投资有风险，决策需谨慎。"
            result = AnalysisResult(
                task_type=task_type,
                success=True,
                content=content,
                model=response.get("model", self.config.model),
                tokens_used=response.get("usage", {}).get("total_tokens", 0),
                latency_ms=latency,
                context=context,
            )

        if use_cache:
            with self._cache_lock:
                self._cache[cache_key] = result
        return result

    def _fallback_template(self, task_type: str, context: Dict[str, Any]) -> str:
        """LLM 不可用时的模板化输出。"""
        parts = [
            f"📊 **{task_type.upper()} 分析报告（规则引擎版）**",
            "=" * 60,
            "",
            "⚠️ AI 分析引擎未启用（请配置 LLM API Key 启用深度解读）",
            "",
            "【关键数据汇总】",
        ]
        for k, v in context.items():
            parts.append(f"- {k}: {v}")
        parts.append("")
        parts.append("📌 说明：当前输出为规则引擎汇总，未含 AI 深度解读。")
        parts.append("📌 配置方法：设置环境变量 DEEPSEEK_API_KEY 或在 config/settings.json 中填写 llm.api_key。")
        return "\n".join(parts)

    def clear_cache(self):
        with self._cache_lock:
            self._cache.clear()


# ============================================================================
# 6. 便捷函数
# ============================================================================

_engine: Optional[AIAnalysisEngine] = None
_engine_lock = threading.Lock()


def get_engine(settings_path: Optional[str] = None) -> AIAnalysisEngine:
    """获取全局 AI 引擎（单例）。"""
    global _engine
    with _engine_lock:
        if _engine is None:
            config = load_llm_config(settings_path)
            _engine = AIAnalysisEngine(config)
        return _engine


def analyze(task_type: str, context: Dict[str, Any], **kwargs) -> AnalysisResult:
    """便捷函数：调用 AI 分析。"""
    return get_engine().analyze(task_type, context, **kwargs)


# ============================================================================
# 7. 自检
# ============================================================================

def self_check() -> Dict[str, Any]:
    """AI 引擎自检。"""
    engine = get_engine()
    status = engine.status()
    return {
        "version": "v11.0",
        "AIAnalysisEngine": "OK",
        "provider": status["provider"],
        "model": status["model"],
        "api_key_configured": status["api_key_configured"],
        "available": status["available"],
        "prompt_templates": list(PROMPT_TEMPLATES.keys()),
        "template_count": len(PROMPT_TEMPLATES),
        "v11_new_templates": [
            "futures_analysis", "money_flow_analysis",
            "index_forecast", "portfolio_diagnosis",
        ],
        "tip": "设置 DEEPSEEK_API_KEY 环境变量以启用 AI 深度解读" if not status["available"] else "AI 引擎已就绪",
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(self_check(), ensure_ascii=False, indent=2))
