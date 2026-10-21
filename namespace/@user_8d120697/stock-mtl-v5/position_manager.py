#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓管理模块 v1.0
记录股民的持仓信息，计算浮盈/亏，给出操作建议

核心能力：
  - 记录每只股票的成本价、仓位（股数）、买入日期
  - 实时计算浮盈/浮亏金额和百分比
  - 基于成本价自动生成止盈/止损/加仓/减仓建议
  - 持仓数据持久化到JSON文件
  - 支持多只股票管理

用法：
  from position_manager import PositionManager
  pm = PositionManager()
  pm.add_position("sh600023", "浙能电力", cost_price=5.60, shares=1000, buy_date="2026-04-20")
  advice = pm.get_advice("sh600023", current_price=5.76)
"""

import json
import os
import math
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict


# ============================================================
# 数据模型
# ============================================================

@dataclass
class Position:
    """单只股票的持仓信息"""
    code: str = ''              # 股票代码 (如 sh600023)
    name: str = ''              # 股票名称
    cost_price: float = 0       # 成本价(元)
    shares: int = 0             # 持仓股数
    buy_date: str = ''          # 买入日期 (YYYY-MM-DD)
    target_price: float = 0     # 目标价(止盈参考，0=未设置)
    stop_loss_price: float = 0  # 止损价(0=未设置)
    notes: str = ''             # 备注

    # 运行时计算的实时数据（不入库）
    current_price: float = 0    # 当前价格
    change_pct: float = 0       # 当日涨跌幅%
    pnl_amount: float = 0       # 浮盈/亏金额(元)
    pnl_pct: float = 0          # 浮盈/亏百分比(%)

    @property
    def total_cost(self) -> float:
        """总成本"""
        return self.cost_price * self.shares

    @property
    def market_value(self) -> float:
        """当前市值"""
        price = self.current_price if self.current_price > 0 else self.cost_price
        return price * self.shares

    def to_dict(self) -> dict:
        """序列化为字典（不含运行时字段）"""
        d = asdict(self)
        # 移除运行时字段
        for k in ['current_price', 'change_pct', 'pnl_amount', 'pnl_pct']:
            d.pop(k, None)
        return d


@dataclass
class OperationAdvice:
    """
    操作建议 — 这是给股民的核心输出
    
    设计理念：结论前置、数字具体、一句话说清该干什么
    """
    action: str = ''            # 操作动作：持有/止盈/止损/减仓/加仓/观望
    action_emoji: str = ''      # 动作对应的emoji
    summary: str = ''           # 一句话总结（最重要的！）
    
    # 关键价位
    target_price: float = 0     # 建议目标价
    stop_loss: float = 0        # 建议止损价
    
    # 当前状态
    pnl_pct: float = 0          # 浮盈%
    pnl_amount: float = 0       # 浮盈金额(元)
    position_weight: str = ''   # 仓位描述（轻仓/中仓/重仓/满仓）
    
    # 理由
    reason: str = ''            # 为什么给这个建议
    risk_level: str = ''        # 风险等级：低/中/高
    
    # 额外提示
    extra_tips: List[str] = field(default_factory=list)


# ============================================================
# 持仓管理器
# ============================================================

class PositionManager:
    """
    持仓管理器
    
    用法：
        pm = PositionManager()
        
        # 新增持仓
        pm.add_position("sh600023", "浙能电力", cost_price=5.60, shares=1000)
        
        # 更新当前价格并获取建议
        advice = pm.get_advice("sh600023", current_price=5.76, change_pct=1.05)
        print(advice.summary)  # → "浙能电力：浮盈+2.9%，建议继续持有，目标6.00元"
        
        # 查看全部持仓概览
        overview = pm.get_overview(current_prices={"sh600023": 5.76})
        
        # 移除持仓
        pm.remove_position("sh600023")
    """

    def __init__(self, config_file: str = None):
        if config_file is None:
            config_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'positions.json'
            )
        self.config_file = config_file
        self.positions: Dict[str, Position] = {}
        self._load()

    # ----------------------------------------------------------
    # CRUD操作
    # ----------------------------------------------------------

    def add_position(self, code: str, name: str, cost_price: float,
                     shares: int, buy_date: str = '', 
                     target_price: float = 0, stop_loss_price: float = 0,
                     notes: str = '') -> bool:
        """
        新增或更新持仓
        
        Args:
            code: 股票代码 (如 sh600023)
            name: 股票名称
            cost_price: 成本价(元)
            shares: 持仓股数
            buy_date: 买入日期 (YYYY-MM-DD)，默认今天
            target_price: 目标价(0=不设置)
            stop_loss_price: 止损价(0=不设置)
            notes: 备注
        
        Returns:
            是否成功
        """
        if not buy_date:
            buy_date = date.today().isoformat()
            
        pos = Position(
            code=code, name=name, cost_price=cost_price,
            shares=shares, buy_date=buy_date,
            target_price=target_price, stop_loss_price=stop_loss_price,
            notes=notes
        )
        self.positions[code] = pos
        self._save()
        print(f"[持仓] 已添加: {name}({code}) 成本{cost_price}元 × {shares}股")
        return True

    def remove_position(self, code: str) -> bool:
        """移除持仓"""
        if code in self.positions:
            pos = self.positions.pop(code)
            self._save()
            print(f"[持仓] 已移除: {pos.name}({code})")
            return True
        return False

    def get_position(self, code: str) -> Optional[Position]:
        """获取某只股票的持仓"""
        return self.positions.get(code)

    def list_positions(self) -> List[Position]:
        """列出所有持仓"""
        return list(self.positions.values())

    def has_position(self, code: str) -> bool:
        """是否持有这只股票"""
        return code in self.positions

    # ----------------------------------------------------------
    # 核心功能：获取操作建议
    # ----------------------------------------------------------

    def get_advice(self, code: str, current_price: float, 
                   change_pct: float = 0) -> Optional[OperationAdvice]:
        """
        获取某只股票的操作建议
        
        这是整个模块最核心的方法。输入当前行情，输出可执行的建议。
        
        Args:
            code: 股票代码
            current_price: 当前价格
            change_pct: 当日涨跌幅%(可选)
        
        Returns:
            OperationAdvice 对象（包含操作建议+理由）
        """
        pos = self.positions.get(code)
        if not pos or not pos.cost_price:
            return None
        
        # 更新实时数据
        pos.current_price = current_price
        pos.change_pct = change_pct
        
        # 计算浮盈
        pos.pnl_amount = (current_price - pos.cost_price) * pos.shares
        pos.pnl_pct = (current_price - pos.cost_price) / pos.cost_price * 100 if pos.cost_price > 0 else 0
        
        # 自动计算目标价和止损价（如果用户没手动设）
        target = pos.target_price if pos.target_price > 0 else round(pos.cost_price * 1.10, 2)
        stop_loss = pos.stop_loss_price if pos.stop_loss_price > 0 else round(pos.cost_price * 0.92, 2)
        
        # 判断仓位轻重
        position_weight = self._classify_position(shares=pos.shares)
        
        # === 核心决策逻辑 ===
        advice = self._make_decision(pos, target, stop_loss, position_weight, change_pct)
        
        return advice

    def _classify_position(self, shares: int) -> str:
        """
        根据股数判断仓位轻重
        注意：这是粗略估计，实际应根据资金总量判断。
        这里用经验值：
          - 轻仓：< 500股
          - 中仓：500-2000股
          - 重仓：2000-5000股  
          - 满仓：> 5000股
        """
        if shares <= 500:
            return "轻仓"
        elif shares <= 2000:
            return "中仓"
        elif shares <= 5000:
            return "重仓"
        else:
            return "满仓"

    def _make_decision(self, pos: Position, target: float, 
                      stop_loss: float, weight: str,
                      change_pct: float) -> OperationAdvice:
        """
        决策引擎：根据当前价格相对成本价的位置给出操作建议
        
        决策矩阵：
          | 浮盈%区间     | 建议         | 风险 |
          |-------------|-------------|------|
          | > +15%      | 减仓锁定利润 | 低   |
          | +8%~15%     | 继续持有     | 低   |
          | +3%~8%      | 持有观察     | 中   |
          | 0~+3%       | 持有观望     | 中   |
          | -3%~0%      | 持有观察     | 中   |
          | -8%~-3%     | 关注风险     | 中高 |
          | <-8%        | 考虑止损     | 高   |
          
        叠加特殊条件：
          - 接近目标价 → 提示止盈机会
          - 接近止损价 → 强烈警示风险
          - 大幅下跌日 → 建议减仓防守
        """
        pnl_pct = pos.pnl_pct
        price = pos.current_price
        tips = []
        
        # === 主决策逻辑 ===
        if pnl_pct >= 15:
            action = "减仓"
            emoji = "💰"
            reason = f"浮盈已达{pnl_pct:.1f}%，建议分批止盈锁定利润"
            risk_level = "低"
            tips.append(f"已到第一目标位，可卖出1/3~1/2仓位")
            tips.append(f"剩余仓位止损上移至成本价{pos.cost_price:.2f}元")
            
        elif pnl_pct >= 8:
            action = "持有"
            emoji = "✅"
            reason = f"浮盈{pnl_pct:.1f}%，趋势良好，继续持有"
            risk_level = "低"
            if price >= target * 0.95:
                tips.append(f"接近目标价{target:.2f}元，关注止盈信号")
                action = "考虑止盈"
                emoji = "🎯"
                
        elif pnl_pct >= 3:
            action = "持有"
            emoji = "✅"
            reason = f"小幅盈利{pnl_pct:.1f}%，趋势向上，耐心持有"
            risk_level = "中"
            tips.append(f"目标价{target:.2f}元，止损位{stop_loss:.2f}元")
            
        elif pnl_pct >= -3:
            action = "持有"
            emoji = "➖"
            reason = f"成本附近震荡，正常波动范围内"
            risk_level = "中"
            if abs(change_pct) > 3:
                tips.append("今日波动较大，注意后续走势")
                
        elif pnl_pct >= -8:
            action = "关注"
            emoji = "⚠️"
            reason = f"浮亏{pnl_pct:.1f}%，需要密切关注"
            risk_level = "中高"
            tips.append(f"若跌破止损位{stop_loss:.2f}元，建议减仓")
            if weight in ["重仓", "满仓"]:
                tips.append(f"{weight}状态，亏损放大快，控制仓位优先")
                
        else:  # pnl_pct < -8
            action = "止损"
            emoji = "🛑"
            reason = f"浮亏已达{pnl_pct:.1f}%，触及风控线"
            risk_level = "高"
            tips.append("强烈建议减仓或止损，避免进一步扩大损失")
            if weight in ["重仓", "满仓"]:
                action = "紧急减仓"
                emoji = "🚨"

        # === 特殊条件叠加 ===
        
        # 价格接近或突破目标价
        if price >= target:
            tips.insert(0, f"⬆️ 已达/超过目标价{target:.2f}元，是止盈的好时机！")
            action = "止盈"
            emoji = "🏆"
        elif price >= target * 0.97:
            tips.append(f"接近目标价{target:.2f}元，准备止盈计划")

        # 价格接近或跌破止损价
        if price <= stop_loss:
            tips.insert(0, f"⬇️ 已触及/跌破止损位{stop_loss:.2f}元！")
            action = "止损"
            emoji = "🛑"
            risk_level = "高"
        elif price <= stop_loss * 1.03:
            tips.append(f"⚠️ 接近止损位{stop_loss:.2f}元，提高警惕")

        # 今日大跌（叠加市场因素）
        if change_pct <= -5:
            tips.append("今日大幅下跌，检查是否有利空消息")
            if risk_level == "中":
                action = "谨慎"
                emoji = "⚠️"
        elif change_pct <= -3:
            tips.append("今日跌幅超3%，注意短期趋势变化")

        # 今日大涨
        if change_pct >= 5:
            tips.append("今日大涨，但不宜追高，回调再考虑")

        summary = self._build_summary(pos.name, action, emoji, pnl_pct, 
                                       price, target, stop_loss, weight)

        return OperationAdvice(
            action=action,
            action_emoji=emoji,
            summary=summary,
            target_price=target,
            stop_loss=stop_loss,
            pnl_pct=pnl_pct,
            pnl_amount=pos.pnl_amount,
            position_weight=weight,
            reason=reason,
            risk_level=risk_level,
            extra_tips=tips,
        )

    def _build_summary(self, name: str, action: str, emoji: str,
                       pnl_pct: float, price: float,
                       target: float, stop_loss: float, weight: str) -> str:
        """
        构建一句话总结
        
        格式：[emoji] 股票名：现价X元，浮盈X%，建议XX，目标X/止损X
        """
        pnl_str = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"
        
        return (
            f"{emoji} {name}：现价{price:.2f}元，"
            f"浮盈{pnl_str}，{weight}"
            f"\n→ {action} | 目标{target:.2f}/止损{stop_loss:.2f}"
        )

    # ----------------------------------------------------------
    # 持仓概览
    # ----------------------------------------------------------

    def get_overview(self, current_prices: Dict[str, float] = None) -> dict:
        """
        获取全部持仓概览
        
        Args:
            current_prices: {code: price} 实时价格字典
        
        Returns:
            包含总市值、总成本、总盈亏等信息的字典
        """
        positions_data = []
        total_cost = 0
        total_market_value = 0
        total_pnl = 0

        for code, pos in self.positions.items():
            price = current_prices.get(code, 0) if current_prices else 0
            if price > 0:
                pos.current_price = price
                pos.pnl_amount = (price - pos.cost_price) * pos.shares
                pos.pnl_pct = (price - pos.cost_price) / pos.cost_price * 100 if pos.cost_price > 0 else 0
            
            total_cost += pos.total_cost
            total_market_value += pos.market_value
            total_pnl += pos.pnl_amount
            
            positions_data.append({
                'code': pos.code,
                'name': pos.name,
                'cost': pos.cost_price,
                'shares': pos.shares,
                'current_price': pos.current_price,
                'pnl_pct': round(pos.pnl_pct, 2),
                'pnl_amount': round(pos.pnl_amount, 2),
                'market_value': round(pos.market_value, 2),
                'buy_date': pos.buy_date,
                'weight': self._classify_position(pos.shares),
            })

        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

        return {
            'positions': positions_data,
            'total_stocks': len(self.positions),
            'total_cost': round(total_cost, 2),
            'total_market_value': round(total_market_value, 2),
            'total_pnl': round(total_pnl, 2),
            'total_pnl_pct': round(total_pnl_pct, 2),
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    # ----------------------------------------------------------
    # 持久化
    # ----------------------------------------------------------

    def _save(self):
        """保存到JSON文件"""
        data = {}
        for code, pos in self.positions.items():
            data[code] = pos.to_dict()
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[持仓] 保存失败: {e}")

    def _load(self):
        """从JSON文件加载"""
        if not os.path.exists(self.config_file):
            return
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for code, pdict in data.items():
                self.positions[code] = Position(**pdict)
        except Exception as e:
            print(f"[持仓] 加载失败: {e}")

    # ----------------------------------------------------------
    # 格式化输出（用于企微推送）
    # ----------------------------------------------------------

    @staticmethod
    def format_advice_for_wechat(advice: OperationAdvice, 
                                  stock_snapshot: dict = None) -> Tuple[str, str]:
        """
        将操作建议格式化为企微消息
        
        这是v5.0的核心改进：先给结论和数据，最后附推荐股
        
        Returns:
            (title, content) 企微markdown格式
        """
        lines = [
            f"## {advice.action_emoji} 【{advice.action}建议】",
            "",
            f"> **{advice.summary}**",
            "",
            "**📊 当前持仓情况**",
            f"| 项目 | 数值 |",
            f"|------|------|",
            f"| 浮盈/亏 | {'+' if advice.pnl_pct>=0 else ''}{advice.pnl_pct:.2f}% |",
            f"| 浮盈/亏金额 | {'+' if advice.pnl_amount>=0 else ''}{advice.pnl_amount:.2f}元 |",
            f"| 目标价 | {advice.target_price:.2f}元 |",
            f"| 止损价 | {advice.stop_loss:.2f}元 |",
            f"| 仓位 | {advice.position_weight} |",
            f"| 风险等级 | {advice.risk_level} |",
            "",
        ]

        # 理由
        lines.append(f"**💡 判断依据:** {advice.reason}")
        lines.append("")
        
        # 额外提示
        if advice.extra_tips:
            lines.append("**⚠️ 注意事项:**")
            for tip in advice.extra_tips:
                lines.append(f"- {tip}")
            lines.append("")

        # 如果有行情快照数据，补充关键指标
        if stock_snapshot:
            lines.append("**📈 行情数据**")
            lines.append(f"| 指标 | 数值 |")
            lines.append(f"|------|------|")
            for label, val in stock_snapshot.items():
                lines.append(f"| {label} | {val} |")
            lines.append("")

        # 免责声明（每次必带）
        lines.extend([
            "---",
            "> ⚠️ 以上为AI辅助分析，仅供参考，不构成投资建议。股市有风险，入市需谨慎。",
        ])

        title = f"{advice.action_emoji} {advice.action}建议"
        content = "\n".join(lines)
        return title, content

    @staticmethod
    def format_overview_for_wechat(overview: dict) -> Tuple[str, str]:
        """
        将持仓概览格式化为企微消息
        """
        lines = [
            f"## 📋 【持仓概览】{overview['update_time']}",
            "",
            f"**总计：** {overview['total_stocks']}只股票 | "
            f"总市值{overview['total_market_value']:,.0f}元 | "
            f"总盈亏{'+' if overview['total_pnl']>=0 else ''}{overview['total_pnl']:,.0f}元"
            f"({'+' if overview['total_pnl_pct']>=0 else ''}{overview['total_pnl_pct']:.2f}%)",
            "",
        ]

        if overview['positions']:
            lines.append("| 股票 | 成本 | 现价 | 盈亏% | 盈亏额 | 仓位 |")
            lines.append("|------|------|------|-------|--------|------|")
            for p in overview['positions']:
                pnl_icon = '🔴' if p['pnl_pct'] >= 0 else '🟢'
                lines.append(
                    f"| {p['name']} | {p['cost']:.2f} | {p['current_price']:.2f} | "
                    f"{pnl_icon} {p['pnl_pct']:+.2f}% | "
                    f"{'+' if p['pnl_amount']>=0 else ''}{p['pnl_amount']:.0f}元 | "
                    f"{p['weight']} |"
                )
        else:
            lines.append("> 暂无持仓记录")

        lines.extend([
            "",
            "---",
            "> 由股票助手自动生成",
        ])

        title = "📋 持仓概览"
        content = "\n".join(lines)
        return title, content


# ============================================================
# 命令行入口
# ============================================================

def main():
    """持仓管理命令行工具"""
    import argparse

    parser = argparse.ArgumentParser(description='持仓管理工具')
    subparsers = parser.add_subparsers(dest='command')

    # 添加持仓
    p_add = subparsers.add_parser('add', help='添加持仓')
    p_add.add_argument('code', help='股票代码')
    p_add.add_argument('--name', required=True, help='股票名称')
    p_add.add_argument('--cost', type=float, required=True, help='成本价')
    p_add.add_argument('--shares', type=int, required=True, help='持股数')
    p_add.add_argument('--date', default='', help='买入日期 YYYY-MM-DD')
    p_add.add_argument('--target', type=float, default=0, help='目标价')
    p_add.add_argument('--stoploss', type=float, default=0, help='止损价')

    # 删除持仓
    p_del = subparsers.add_parser('del', help='删除持仓')
    p_del.add_argument('code', help='股票代码')

    # 列出所有持仓
    subparsers.add_parser('list', help='列出持仓')

    # 查看建议
    p_adv = subparsers.add_parser('advice', help='获取操作建议')
    p_adv.add_argument('code', help='股票代码')
    p_adv.add_argument('--price', type=float, required=True, help='当前价格')
    p_adv.add_argument('--chg', type=float, default=0, help='涨跌幅%')

    args = parser.parse_args()

    pm = PositionManager()

    if args.command == 'add':
        pm.add_position(args.code, args.name, args.cost, args.shares,
                        args.date, args.target, args.stoploss)
    elif args.command == 'del':
        pm.remove_position(args.code)
    elif args.command == 'list':
        ov = pm.get_overview()
        title, content = pm.format_overview_for_wechat(ov)
        print(title)
        print(content)
    elif args.command == 'advice':
        adv = pm.get_advice(args.code, args.price, args.chg)
        if adv:
            title, content = pm.format_advice_for_wechat(adv)
            print(title)
            print(content)
        else:
            print(f"未找到 {args.code} 的持仓记录")
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
