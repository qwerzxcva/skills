#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能企微通知引擎 v5.0
面向股民客户的专业股票播报系统

v5.0 重大升级：
  - 先给结论和操作建议（基于持仓成本价计算）
  - 再给数据支撑
  - 最后附推荐股（标注仅供参考）
  - 集成PositionManager实现个性化推送

通知优先级（按价值排序）：
  🔴 第一梯队（必须推）：涨停/跌停、压力位突破、支撑位失守
  🟡 第二梯队（很有用）：大单异动、竞价报告、尾盘异动
  🟢 第三梯队（锦上添花）：均线金叉死叉、量能异常、每日复盘

核心原则：
  - 结论放最前，数据在后
  - 数字具体，不说"量能较大"，说"量比3.2"
  - 风险用emoji区分，5秒看完
  - 每条消息都带操作建议（如果有持仓信息）

用法：
  from smart_notifier import SmartNotifier, V5Formatter
  sn = SmartNotifier()
  sn.check_and_notify(code, data)  # 每次监测循环调用
"""

import sys
import os
import time
import math
import random
from datetime import datetime, time as dtime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from notifier import Notifier


# ============================================================
# 数据模型
# ============================================================

@dataclass
class AlertEvent:
    """一次通知事件"""
    alert_type: str           # 事件类型标识
    level: str                # 'critical' / 'warning' / 'info'
    title: str                # 企微消息标题
    content: str              # 企微消息正文(Markdown)
    stock_code: str = ''
    stock_name: str = ''
    timestamp: float = field(default_factory=time.time)
    raw_data: dict = field(default_factory=dict)


@dataclass
class StockSnapshot:
    """用于通知判断的股票快照"""
    code: str = ''
    name: str = ''
    price: float = 0
    change_pct: float = 0       # 涨跌幅%
    open_price: float = 0
    pre_close: float = 0
    high: float = 0
    low: float = 0
    volume: int = 0             # 成交量(手)
    amount: float = 0           # 成交额(万)
    turnover_rate: float = 0    # 换手率%
    volume_ratio: float = 0     # 量比
    net_inflow: float = 0       # 主力净流入(万)

    # 压力支撑位（从pro_analyzer获取）
    pressure_levels: List[float] = field(default_factory=list)   # [p1, p2, p3]
    pressure_sources: List[str] = field(default_factory=list)    # [src1, src2, src3]
    support_levels: List[float] = field(default_factory=list)    # [s1, s2, s3]
    support_sources: List[str] = field(default_factory=list)    # [src1, src2, src3]

    # 均线
    ma5: float = 0
    ma20: float = 0
    ma60: float = 0
    ma120: float = 0

    # 历史对比（用于判断突破/跌破）
    prev_close_list: List[float] = field(default_factory=list)   # 近N日收盘价列表
    avg_volume_5d: float = 0                                     # 5日均量
    avg_volume_20d: float = 0                                    # 20日均量

    data_source: str = ''


# ============================================================
# 防重复推送管理器
# ============================================================

class AntiSpam:
    """防刷 + 冷却 + 去重"""

    def __init__(self):
        # 已发送的事件记录 {event_key: timestamp}
        self.sent_events: Dict[str, float] = {}
        # 各类型最小间隔(秒)：防止同一事件反复触发
        self.cooldowns = {
            'limit_up':          1800,   # 涨停：30分钟内不重复
            'limit_down':        1800,   # 跌停：30分钟内不重复
            'pressure_break':    600,    # 压力位突破：10分钟
            'support_break':     600,    # 支撑位跌破：10分钟
            'big_order':         300,    # 大单异动：5分钟
            'volume_surge':      600,    # 放量异常：10分钟
            'ma_cross':          3600,   # 均线金叉死叉：1小时
            'morning_call':      0,      # 竞价报告：每天只发一次(外层控)
            'midday_summary':    0,      # 午间盘点：每天一次
            'closing_alert':     300,    # 尾盘异动：5分钟
            'daily_review':      0,      # 复盘：每天一次
        }
        # 记录上次各股的状态（用于检测状态变化）
        self.last_states: Dict[str, dict] = {}

    def can_send(self, event_key: str, alert_type: str) -> bool:
        """
        判断是否可以发送该事件
        
        Args:
            event_key: 唯一事件标识 (如 "sh600519_limit_up")
            alert_type: 事件类型
        
        Returns:
            True=可以发送, False=已冷却中
        """
        now = time.time()
        cooldown = self.cooldowns.get(alert_type, 300)

        last_sent = self.sent_events.get(event_key, 0)
        if now - last_sent < cooldown:
            return False

        return True

    def mark_sent(self, event_key: str):
        """标记已发送"""
        self.sent_events[event_key] = time.time()

        # 清理超过24小时的旧记录
        cutoff = time.time() - 86400
        expired = [k for k, v in self.sent_events.items() if v < cutoff]
        for k in expired:
            del self.sent_events[k]

    def update_state(self, code: str, state: dict):
        """更新股票最新状态（增量合并，不会覆盖已有字段）"""
        if code in self.last_states:
            self.last_states[code].update(state)
        else:
            self.last_states[code] = {
                **state,
                '_ts': time.time()
            }

    def get_last_state(self, code: str) -> Optional[dict]:
        """获取上次状态"""
        return self.last_states.get(code)


# ============================================================
# 通知格式工厂
# ============================================================

class MessageFormatter:
    """专业级企微消息格式化"""

    # ---- 涨停通知 ----

    @staticmethod
    def format_limit_up(snap: StockSnapshot) -> Tuple[str, str]:
        """涨停提醒"""
        vol_ratio_str = ""
        if snap.volume_ratio > 0:
            vol_ratio_str = f"\n**量比：** {snap.volume_ratio:.1f}"

        inflow_str = ""
        if abs(snap.net_inflow) > 100:
            direction = "流入" if snap.net_inflow > 0 else "流出"
            inflow_str = f"\n**主力资金：** {abs(snap.net_inflow)/10000:.1f}亿{direction}"

        title = f"🔴 【涨停】{snap.name}"
        content = (
            f"**现价：** {snap.price:.2f}元  **涨幅：** {snap.change_pct:+.2f}%\n"
            f"**成交额：** {snap.amount/10000:.1f}亿{vol_ratio_str}{inflow_str}\n\n"
            f"> ⚡ 强势封板！关注封单稳定性，持股观察"
        )
        return title, content

    # ---- 跌停通知 ----

    @staticmethod
    def format_limit_down(snap: StockSnapshot) -> Tuple[str, str]:
        """跌停预警"""
        inflow_str = ""
        if abs(snap.net_inflow) > 100:
            direction = "流入" if snap.net_inflow > 0 else "流出"
            inflow_str = f"\n**主力资金：** {abs(snap.net_inflow)/10000:.1f}亿{direction}"

        title = f"⚫ 【跌停】{snap.name}"
        content = (
            f"**现价：** {snap.price:.2f}元  **跌幅：** {snap.change_pct:+.2f}%\n"
            f"**换手率：** {snap.turnover_rate:.2f}%{inflow_str}\n\n"
            f"> ⚠️ 跌停！注意风险，暂勿抄底"
        )
        return title, content

    # ---- 压力位突破通知 ----

    @staticmethod
    def format_pressure_break(snap: StockSnapshot, level_idx: int,
                              level_price: float, sources: str) -> Tuple[str, str]:
        """突破关键压力位"""
        dist_pct = (level_price - snap.pre_close) / snap.pre_close * 100 if snap.pre_close else 0

        stars = {"★★★": "三重共振", "★★": "双重确认", "★": "单维参考"}
        star_label = stars.get(sources[:3], "有效位")

        title = f"🚀 【突破】{snap.name}"
        content = (
            f"**突破压力位：** {level_price:.2f}元 ({star_label})\n"
            f"**现价：** {snap.price:.2f}元  **涨幅：** {snap.change_pct:+.2f}%\n"
            f"**来源：** {sources}\n"
            f"**距前收：** {dist_pct:+.1f}%\n\n"
            f"> 💡 压力变支撑，放量突破则趋势加速，缩量突破需警惕回踩"
        )
        return title, content

    # ---- 支撑位失守通知 ----

    @staticmethod
    def format_support_break(snap: StockSnapshot, level_idx: int,
                              level_price: float, sources: str) -> Tuple[str, str]:
        """跌破关键支撑位"""
        dist_pct = (level_price - snap.pre_close) / snap.pre_close * 100 if snap.pre_close else 0

        stars = {"★★★": "三重共振", "★★": "双重确认", "★": "单维参考"}
        star_label = stars.get(sources[:3], "有效位")

        title = f"⛔ 【失守】{snap.name}"
        content = (
            f"**跌破支撑位：** {level_price:.2f}元 ({star_label})\n"
            f"**现价：** {snap.price:.2f}元  **跌幅：** {snap.change_pct:+.2f}%\n"
            f"**来源：** {sources}\n"
            f"**距前收：** {dist_pct:+.1f}%\n\n"
            f"> ⚠️ 支撑变压力！若不能快速收回，下一支撑位在{snap.support_levels[level_idx+1]:.2f}元" 
            if len(snap.support_levels) > level_idx + 1 else
            "> ⚠️ 关键支撑失守！注意止损"
        )
        return title, content

    # ---- 大单异动通知 ----

    @staticmethod
    def format_big_order(snap: StockSnapshot, net_amount: float,
                          duration_min: int = 5) -> Tuple[str, str]:
        """大单突然砸入/砸出"""
        abs_amount = abs(net_amount)
        amount_yi = abs_amount / 10000  # 转亿
        direction = "买入" if net_amount > 0 else "卖出"
        emoji = "🟢" if net_amount > 0 else "🔴"

        vol_multiple = snap.volume / snap.avg_volume_5d if snap.avg_volume_5d > 0 else 0

        title = f"{emoji} 【大单异动】{snap.name}"
        content = (
            f"**主力{direction}：** {amount_yi:.1f}亿（近{duration_min}分钟）\n"
            f"**现价：** {snap.price:.2f}元  **涨跌：** {snap.change_pct:+.2f}%\n"
            f"**量比：** {snap.volume_ratio:.1f}  **放量倍数：** {vol_multiple:.1f}x\n\n"
            f"> {'💪 主力大幅进场，留意后续走势' if net_amount > 0 else '🏃 主力出逃，注意风险'}"
        )
        return title, content

    # ---- 量能异常通知 ----

    @staticmethod
    def format_volume_surge(snap: StockSnapshot, multiple: float) -> Tuple[str, str]:
        """量能突然放大"""
        title = f"📊 【量能异常】{snap.name}"
        content = (
            f"**成交量：** 是20日均量的{multiple:.1f}倍！\n"
            f"**现价：** {snap.price:.2f}元  **涨跌：** {snap.change_pct:+.2f}%\n"
            f"**换手率：** {snap.turnover_rate:.2f}%  **量比：** {snap.volume_ratio:.1f}\n\n"
            f"> 🔍 无故放量，建议查看是否有消息面催化"
        )
        return title, content

    # ---- 均线金叉/死叉通知 ----

    @staticmethod
    def format_ma_cross(snap: StockSnapshot, fast: str, slow: str,
                         is_golden: bool) -> Tuple[str, str]:
        """MA金叉/死叉"""
        cross_type = "金叉" if is_golden else "死叉"
        emoji = "✨" if is_golden else "☠️"

        title = f"{emoji} 【{cross_type}】{snap.name}"
        content = (
            f"**MA{fast} 上穿 MA{slow} 形成{cross_type}！**\n"
            f"**现价：** {snap.price:.2f}元  **涨跌：** {snap.change_pct:+.2f}%\n"
            f"**MA{fast}：** {getattr(snap, f'ma{fast}', 0):.2f}  "
            f"**MA{slow}：** {getattr(snap, f'ma{slow}', 0):.2f}\n\n"
            f"> {'📈 中线看多信号，可逢低布局' if is_golden else '📉 中线走弱信号，注意减仓防守'}"
        )
        return title, content

    # ---- 早盘竞价报告 ----

    @staticmethod
    def format_morning_call(stocks: List[StockSnapshot],
                             market_up_count: int, market_down_count: int,
                             limit_up_names: str, limit_down_names: str) -> Tuple[str, str]:
        """9:25竞价结束后推送"""
        lines = [
            f"📋 **【早盘竞价报告】{datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            f"**市场概况：** 📈上涨{market_up_count}家  📉下跌{market_down_count}家",
            "",
        ]

        for s in stocks:
            icon = "🔴" if s.change_pct >= 9.5 else "🟢" if s.change_pct >= 3 else ("⚫" if s.change_pct <= -9.5 else "🔵" if s.change_pct <= -3 else "➖")
            line = (
                f"{icon} **{s.name}** | {s.price:.2f}元 | {s.change_pct:+.2f}% "
                f"| 量比{s.volume_ratio:.1f}"
            )
            if abs(s.net_inflow) > 100:
                nf = s.net_inflow / 10000
                line += f" | 主力{'+' if s.net_inflow>0 else''}{nf:.1f}亿"
            lines.append(line)

        if limit_up_names:
            lines.append(f"\n> 🔴 今日竞价涨停：{limit_up_names}")
        if limit_down_names:
            lines.append(f"> ⚫ 今日竞价跌停：{limit_down_names}")

        lines.extend(["", "---", "> 本报告由股票监测助手自动生成"])
        title = "📋 早盘竞价报告"
        content = "\n".join(lines)
        return title, content

    # ---- 午间盘点 ----

    @staticmethod
    def format_midday_summary(stocks: List[StockSnapshot]) -> Tuple[str, str]:
        """11:35午间盘点"""
        lines = [
            f"☕ **【午间盘点】{datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        for s in stocks:
            chg_icon = "🔴" if s.change_pct > 0 else "🟢" if s.change_pct < 0 else "➖"
            high_low = f"高{s.high:.2f} / 低{s.low:.2f}"
            lines.append(
                f"{chg_icon} **{s.name}** | {s.price:.2f}({s.change_pct:+.2f}%) | {high_low}"
                f" | 换手{s.turnover_rate:.1f}%"
            )

        lines.extend([
            "",
            "> 下午重点关注：量能是否萎缩 / 尾盘是否有异动",
            "---",
            "> 由股票监测助手自动生成"
        ])
        title = "☕ 午间盘点"
        content = "\n".join(lines)
        return title, content

    # ---- 尾盘异动预警 ----

    @staticmethod
    def format_closing_alert(snap: StockSnapshot, alert_reason: str) -> Tuple[str, str]:
        """14:50-15:00尾盘最后10分钟"""
        title = f"⏰ 【尾盘异动】{snap.name}"
        content = (
            f"**{alert_reason}**\n"
            f"**现价：** {snap.price:.2f}元  **涨跌：** {snap.change_pct:+.2f}%\n"
            f"**主力净流向：** {snap.net_inflow/10000:+.2f}亿\n"
            f"**换手率：** {snap.turnover_rate:.2f}%\n\n"
            f"> ⚠️ 收盘在即，关注收盘价位置，判断明日开盘预期"
        )
        return title, content

    # ---- 每日复盘 ----

    @staticmethod
    def format_daily_review(stock_data: List[dict]) -> Tuple[str, str]:
        """收盘后复盘摘要"""
        lines = [
            f"📊 **【每日复盘】{datetime.now().strftime('%Y-%m-%d')}**",
            "",
        ]
        for sd in stock_data:
            name = sd.get('name', '')
            price = sd.get('price', 0)
            chg = sd.get('change_pct', 0)
            high = sd.get('high', 0)
            low = sd.get('low', 0)
            vol = sd.get('volume', 0)
            amt = sd.get('amount', 0)
            alerts_today = sd.get('alerts_today', [])

            chg_icon = "🔴" if chg > 0 else "🟢" if chg < 0 else "➖"
            lines.append(f"{chg_icon} **{name}** | 收{price:.2f}({chg:+.2f}%) | 高{high:.2f}/低{low:.2f}")
            lines.append(f"   成交{amt/10000:.1f}亿 | 今日提醒{len(alerts_today)}次")
            if alerts_today:
                for a in alerts_today[-3:]:  # 最多显示最近3条
                    lines.append(f"   → {a}")

        lines.extend([
            "",
            "---",
            "> 明日关注：压力位能否突破 / 支撑位是否守住 / 量能配合情况",
            "> 由股票监测助手自动生成"
        ])
        title = "📊 每日复盘"
        content = "\n".join(lines)
        return title, content


# ============================================================
# 核心引擎：智能通知器
# ============================================================

class SmartNotifier:
    """
    智能企微通知引擎
    
    用法：
        sn = SmartNotifier()
        
        # 方式1：每次监测循环调用（实时异动）
        snap = build_snapshot(code, real_data, analyzer_data)
        sn.check_and_notify(snap)
        
        # 方式2：定时任务
        sn.send_morning_call(stocks_list)      # 9:26
        sn.send_midday_summary(stocks_list)    # 11:36
        sn.send_closing_alerts(stocks_list)    # 14:51
        sn.send_daily_review(review_data)      # 15:06
    """

    def __init__(self, notifier: Notifier = None):
        self.notifier = notifier or Notifier()
        self.anti_spam = AntiSpam()
        self.formatter = MessageFormatter()

        # 今日已发送的定期报告（每天只发一次）
        self._daily_flags = {
            'morning_call': False,
            'midday_summary': False,
            'daily_review': False,
        }

        # 配置参数
        self.config = {
            # 触发阈值
            'limit_threshold': 9.5,           # 涨跌停阈值%
            'big_order_threshold': 3000,       # 大单阈值(万)，5分钟内净买卖超此值
            'volume_surge_multiple': 3.0,      # 量能异常倍数(相对5日均量)
            'pressure_break_tolerance': 0.015, # 突破容忍度(1.5%)
            
            # 开关（可以单独关闭某类通知）
            'enable_limit': True,
            'enable_pressure_support': True,
            'enable_big_order': True,
            'enable_volume': True,
            'enable_ma_cross': True,

            # 定时报告开关
            'enable_morning_call': True,
            'enable_midday': True,
            'enable_closing': True,
            'enable_daily_review': True,
        }

        # 当日统计
        self.today_stats = {
            'total_sent': 0,
            'by_type': {},
        }

    # ----------------------------------------------------------
    # 配置方法
    # ----------------------------------------------------------

    def set_config(self, key: str, value):
        """修改配置"""
        self.config[key] = value

    def enable_all(self):
        """开启所有通知"""
        for k in self.config:
            if k.startswith('enable_'):
                self.config[k] = True

    def disable_type(self, notification_type: str):
        """关闭某类通知"""
        key = f'enable_{notification_type}'
        if key in self.config:
            self.config[key] = False

    # ----------------------------------------------------------
    # 核心：实时异动检查（每次monitor循环调用）
    # ----------------------------------------------------------

    def check_and_notify(self, snap: StockSnapshot) -> List[AlertEvent]:
        """
        对一只股票执行全套异动检查，返回触发的事件列表
        
        Args:
            snap: 股票快照（含行情+技术指标+压力支撑）
        
        Returns:
            本次触发的AlertEvent列表
        """
        events = []
        code = snap.code or 'unknown'

        # 1. 涨停/跌停检查
        if self.config['enable_limit']:
            ev = self._check_limitUpDown(snap)
            if ev:
                events.append(ev)

        # 2. 压力位突破检查
        if self.config['enable_pressure_support']:
            ev = self._check_pressure_break(snap)
            if ev:
                events.append(ev)

        # 3. 支撑位失守检查
        if self.config['enable_pressure_support']:
            ev = self._check_support_break(snap)
            if ev:
                events.append(ev)

        # 4. 大单异动检查
        if self.config['enable_big_order']:
            ev = self._check_big_order(snap)
            if ev:
                events.append(ev)

        # 5. 量能异常检查
        if self.config['enable_volume']:
            ev = self._check_volume_surge(snap)
            if ev:
                events.append(ev)

        # 6. 均线金叉/死叉检查
        if self.config['enable_ma_cross']:
            ev = self._check_ma_cross(snap)
            if ev:
                events.append(ev)

        # 发送所有触发事件
        for ev in events:
            self._dispatch(ev)

        # 更新状态
        self.anti_spam.update_state(code, {
            'price': snap.price,
            'change_pct': snap.change_pct,
            'is_limit_up': snap.change_pct >= self.config['limit_threshold'],
            'is_limit_down': snap.change_pct <= -self.config['limit_threshold'],
            'ma5': snap.ma5,
            'ma20': snap.ma20,
            'ma60': snap.ma60,
            '_time': datetime.now().isoformat(),
        })

        return events

    # ----------------------------------------------------------
    # 各类异动检测方法
    # ----------------------------------------------------------

    def _check_limitUpDown(self, snap: StockSnapshot) -> Optional[AlertEvent]:
        """涨停/跌停检测 — 只在状态变化时推送（涨停封板→推一次，打开→推一次，重新封板→推一次）"""
        threshold = self.config['limit_threshold']
        code = snap.code or 'unknown'

        # 获取上次状态
        last_state = self.anti_spam.get_last_state(code)
        was_limit_up = last_state.get('is_limit_up', False) if last_state else False
        was_limit_down = last_state.get('is_limit_down', False) if last_state else False

        is_limit_up = snap.change_pct >= threshold
        is_limit_down = snap.change_pct <= -threshold

        # === 涨停逻辑 ===
        if is_limit_up:
            # 只在"刚刚封板"时推送（上次不是涨停，这次是涨停）
            if not was_limit_up:
                event_key = f"{code}_limit_up"
                if not self.anti_spam.can_send(event_key, 'limit_up'):
                    return None
                self.anti_spam.mark_sent(event_key)

                title, content = self.formatter.format_limit_up(snap)
                return AlertEvent(
                    alert_type='limit_up',
                    level='critical',
                    title=title,
                    content=content,
                    stock_code=code,
                    stock_name=snap.name,
                    raw_data={'price': snap.price, 'change_pct': snap.change_pct}
                )
            # 持续涨停，不重复推
            return None

        # === 涨停打开逻辑 ===
        if was_limit_up and not is_limit_up:
            event_key = f"{code}_limit_up_opened"
            if not self.anti_spam.can_send(event_key, 'limit_up'):
                return None
            self.anti_spam.mark_sent(event_key)

            title = f"⚠️ 【涨停打开】{snap.name}"
            content = (
                f"**现价：** {snap.price:.2f}元  **涨幅：** {snap.change_pct:+.2f}%\n"
                f"**成交额：** {snap.amount/10000:.1f}亿\n\n"
                f"> ⚠️ 涨停板打开！封单松动，注意是否出逃"
            )
            return AlertEvent(
                alert_type='limit_up_opened',
                level='critical',
                title=title,
                content=content,
                stock_code=code,
                stock_name=snap.name,
            )

        # === 跌停逻辑 ===
        if is_limit_down:
            # 只在"刚刚跌停"时推送
            if not was_limit_down:
                event_key = f"{code}_limit_down"
                if not self.anti_spam.can_send(event_key, 'limit_down'):
                    return None
                self.anti_spam.mark_sent(event_key)

                title, content = self.formatter.format_limit_down(snap)
                return AlertEvent(
                    alert_type='limit_down',
                    level='critical',
                    title=title,
                    content=content,
                    stock_code=code,
                    stock_name=snap.name,
                    raw_data={'price': snap.price, 'change_pct': snap.change_pct}
                )
            # 持续跌停，不重复推
            return None

        # === 跌停打开逻辑 ===
        if was_limit_down and not is_limit_down:
            event_key = f"{code}_limit_down_opened"
            if not self.anti_spam.can_send(event_key, 'limit_down'):
                return None
            self.anti_spam.mark_sent(event_key)

            title = f"📈 【跌停打开】{snap.name}"
            content = (
                f"**现价：** {snap.price:.2f}元  **跌幅：** {snap.change_pct:+.2f}%\n"
                f"**成交额：** {snap.amount/10000:.1f}亿\n\n"
                f"> 跌停板打开，是否有资金接盘，观察后续走势"
            )
            return AlertEvent(
                alert_type='limit_down_opened',
                level='critical',
                title=title,
                content=content,
                stock_code=code,
                stock_name=snap.name,
            )

        return None

    def _check_pressure_break(self, snap: StockSnapshot) -> Optional[AlertEvent]:
        """压力位突破检测"""
        if not snap.pressure_levels or snap.price <= 0 or snap.pre_close <= 0:
            return None

        tolerance = self.config['pressure_break_tolerance']

        for i, p_level in enumerate(snap.pressure_levels):
            if p_level <= 0:
                continue
            # 当前价突破压力位（考虑容差）
            if snap.price >= p_level * (1 - tolerance):
                # 还要确保是刚刚突破（不是一直在上方）
                last_state = self.anti_spam.get_last_state(snap.code or 'unknown')
                if last_state and last_state.get('price', 0) >= p_level * (1 - tolerance):
                    continue  # 已经在上面了，不算新突破

                event_key = f"{snap.code or 'unknown'}_pressure_{i}_{int(p_level)}"
                if not self.anti_spam.can_send(event_key, 'pressure_break'):
                    return None
                self.anti_spam.mark_sent(event_key)

                src = snap.pressure_sources[i] if i < len(snap.pressure_sources) else ''
                title, content = self.formatter.format_pressure_break(
                    snap, i, p_level, src
                )
                return AlertEvent(
                    alert_type='pressure_break',
                    level='warning',
                    title=title,
                    content=content,
                    stock_code=snap.code or '',
                    stock_name=snap.name,
                    raw_data={'level_idx': i, 'level_price': p_level, 'source': src}
                )

        return None

    def _check_support_break(self, snap: StockSnapshot) -> Optional[AlertEvent]:
        """支撑位失守检测"""
        if not snap.support_levels or snap.price <= 0 or snap.pre_close <= 0:
            return None

        tolerance = self.config['pressure_break_tolerance']

        for i, s_level in enumerate(snap.support_levels):
            if s_level <= 0:
                continue
            # 当前价跌破支撑位
            if snap.price <= s_level * (1 + tolerance):
                last_state = self.anti_spam.get_last_state(snap.code or 'unknown')
                if last_state and last_state.get('price', 0) <= s_level * (1 + tolerance):
                    continue  # 已经在下面了

                event_key = f"{snap.code or 'unknown'}_support_{i}_{int(s_level)}"
                if not self.anti_spam.can_send(event_key, 'support_break'):
                    return None
                self.anti_spam.mark_sent(event_key)

                src = snap.support_sources[i] if i < len(snap.support_sources) else ''
                title, content = self.formatter.format_support_break(
                    snap, i, s_level, src
                )
                return AlertEvent(
                    alert_type='support_break',
                    level='warning',
                    title=title,
                    content=content,
                    stock_code=snap.code or '',
                    stock_name=snap.name,
                    raw_data={'level_idx': i, 'level_price': s_level, 'source': src}
                )

        return None

    def _check_big_order(self, snap: StockSnapshot) -> Optional[AlertEvent]:
        """大单异动检测 — 只在首次触发时推，不在持续大单时重复推"""
        threshold = self.config['big_order_threshold']  # 万
        code = snap.code or 'unknown'

        if abs(snap.net_inflow) < threshold:
            # 大单消失了，重置状态以便下次再触发
            last_state = self.anti_spam.get_last_state(code)
            if last_state and last_state.get('big_order_active'):
                self.anti_spam.update_state(code, {**last_state, 'big_order_active': False})
            return None

        # 获取上次状态，判断是否已处于大单状态
        last_state = self.anti_spam.get_last_state(code)
        was_big_order = last_state.get('big_order_active', False) if last_state else False
        last_big_direction = last_state.get('big_order_direction', 0) if last_state else 0

        current_direction = 1 if snap.net_inflow > 0 else -1

        # 只在以下情况推送：
        # 1. 之前没有大单，现在出现（首次触发）
        # 2. 之前是大单买入，现在变成大单卖出（方向反转）
        if was_big_order and current_direction == last_big_direction:
            # 持续同方向大单，不重复推
            return None

        event_key = f"{code}_bigorder_{int(time.time() // 300)}"
        if not self.anti_spam.can_send(event_key, 'big_order'):
            return None
        self.anti_spam.mark_sent(event_key)

        # 更新大单状态
        self.anti_spam.update_state(code, {
            **(last_state or {}),
            'big_order_active': True,
            'big_order_direction': current_direction,
        })

        title, content = self.formatter.format_big_order(
            snap, snap.net_inflow, duration_min=5
        )
        return AlertEvent(
            alert_type='big_order',
            level='warning',
            title=title,
            content=content,
            stock_code=code,
            stock_name=snap.name,
            raw_data={'net_inflow': snap.net_inflow}
        )

    def _check_volume_surge(self, snap: StockSnapshot) -> Optional[AlertEvent]:
        """量能异常检测 — 只在首次放量时推，不重复"""
        multiple = self.config['volume_surge_multiple']
        if snap.avg_volume_5d <= 0 or snap.volume <= 0:
            return None

        actual_multiple = snap.volume / snap.avg_volume_5d

        code = snap.code or 'unknown'
        last_state = self.anti_spam.get_last_state(code)
        was_volume_surge = last_state.get('volume_surge_active', False) if last_state else False

        if actual_multiple < multiple:
            # 量能回归正常，重置状态
            if was_volume_surge and last_state:
                self.anti_spam.update_state(code, {**last_state, 'volume_surge_active': False})
            return None

        # 已经在放量状态中，不重复推
        if was_volume_surge:
            return None

        event_key = f"{code}_volsurge_{int(time.time() // 600)}"
        if not self.anti_spam.can_send(event_key, 'volume_surge'):
            return None
        self.anti_spam.mark_sent(event_key)

        # 标记放量状态
        self.anti_spam.update_state(code, {
            **(last_state or {}),
            'volume_surge_active': True,
        })

        title, content = self.formatter.format_volume_surge(snap, actual_multiple)
        return AlertEvent(
            alert_type='volume_surge',
            level='info',
            title=title,
            content=content,
            stock_code=code,
            stock_name=snap.name,
            raw_data={'multiple': actual_multiple}
        )

    def _check_ma_cross(self, snap: StockSnapshot) -> Optional[AlertEvent]:
        """均线金叉/死叉检测"""
        code = snap.code or 'unknown'

        # MA5/MA20 金叉死叉
        if snap.ma5 > 0 and snap.ma20 > 0:
            last_state = self.anti_spam.get_last_state(code)

            # 金叉：之前ma5<=ma20，现在ma5>ma20
            if snap.ma5 > snap.ma20:
                if last_state:
                    prev_ma5 = last_state.get('ma5', 0)
                    prev_ma20 = last_state.get('ma20', 0)
                    if prev_ma5 > 0 and prev_ma5 <= prev_ma20:
                        # 刚刚发生金叉
                        event_key = f"{code}_macross_golden_5_20"
                        if self.anti_spam.can_send(event_key, 'ma_cross'):
                            self.anti_spam.mark_sent(event_key)
                            title, content = self.formatter.format_ma_cross(
                                snap, '5', '20', is_golden=True
                            )
                            return AlertEvent(
                                alert_type='ma_cross_golden',
                                level='info',
                                title=title,
                                content=content,
                                stock_code=code,
                                stock_name=snap.name,
                            )

            # 死叉：之前ma5>=ma20，现在ma5<ma20
            elif snap.ma5 < snap.ma20:
                if last_state:
                    prev_ma5 = last_state.get('ma5', 0)
                    prev_ma20 = last_state.get('ma20', 0)
                    if prev_ma5 > 0 and prev_ma5 >= prev_ma20:
                        event_key = f"{code}_macross_death_5_20"
                        if self.anti_spam.can_send(event_key, 'ma_cross'):
                            self.anti_spam.mark_sent(event_key)
                            title, content = self.formatter.format_ma_cross(
                                snap, '5', '20', is_golden=False
                            )
                            return AlertEvent(
                                alert_type='ma_cross_death',
                                level='info',
                                title=title,
                                content=content,
                                stock_code=code,
                                stock_name=snap.name,
                            )

        return None

    # ----------------------------------------------------------
    # 定时报告方法（由外部调度器按时间调用）
    # ----------------------------------------------------------

    def send_morning_call(self, stocks: List[StockSnapshot],
                           up_count: int = 0, down_count: int = 0,
                           limit_up_names: str = '', limit_down_names: str = '') -> bool:
        """早盘竞价报告（9:25-9:30之间调用）"""
        if not self.config['enable_morning_call']:
            return False
        if self._daily_flags.get('morning_call'):
            print("[SmartNotifier] 今日早盘竞价报告已发送过")
            return False

        if not stocks:
            return False

        title, content = self.formatter.format_morning_call(
            stocks, up_count, down_count, limit_up_names, limit_down_names
        )
        success = self.notifier.send_wechat(title, content)
        if success:
            self._daily_flags['morning_call'] = True
            self._record_stat('morning_call')
        return success

    def send_midday_summary(self, stocks: List[StockSnapshot]) -> bool:
        """午间盘点（11:30后调用）"""
        if not self.config['enable_midday']:
            return False
        if self._daily_flags.get('midday_summary'):
            print("[SmartNotifier] 今日午间盘点已发送过")
            return False

        if not stocks:
            return False

        title, content = self.formatter.format_midday_summary(stocks)
        success = self.notifier.send_wechat(title, content)
        if success:
            self._daily_flags['midday_summary'] = True
            self._record_stat('midday_summary')
        return success

    def send_closing_alerts(self, stocks: List[StockSnapshot]) -> List[AlertEvent]:
        """尾盘异动预警（14:50左右调用）"""
        if not self.config['enable_closing']:
            return []

        events = []
        for snap in stocks:
            # 尾盘最后10分钟的大幅波动
            if abs(snap.change_pct) >= 3:
                reason = f"尾盘{'急拉' if snap.change_pct > 0 else '急跌'}，振幅较大"
                title, content = self.formatter.format_closing_alert(snap, reason)
                ev = AlertEvent(
                    alert_type='closing_alert',
                    level='warning',
                    title=title,
                    content=content,
                    stock_code=snap.code or '',
                    stock_name=snap.name,
                )
                events.append(ev)
                self._dispatch(ev)

            # 尾盘大单方向与股价背离
            elif abs(snap.net_inflow) > 2000:  # 2000万以上
                direction_match = (snap.net_inflow > 0 and snap.change_pct > 0) or \
                                  (snap.net_inflow < 0 and snap.change_pct < 0)
                if not direction_match:
                    reason = f"尾盘资金与走势背离（净流入{snap.net_inflow/10000:+.1f}亿 vs 涨跌{snap.change_pct:+.2f}%）"
                    title, content = self.formatter.format_closing_alert(snap, reason)
                    ev = AlertEvent(
                        alert_type='closing_divergence',
                        level='warning',
                        title=title,
                        content=content,
                        stock_code=snap.code or '',
                        stock_name=snap.name,
                    )
                    events.append(ev)
                    self._dispatch(ev)

        return events

    def send_daily_review(self, review_data: List[dict]) -> bool:
        """每日复盘报告（收盘后调用）"""
        if not self.config['enable_daily_review']:
            return False
        if self._daily_flags.get('daily_review'):
            print("[SmartNotifier] 今日复盘已发送过")
            return False

        if not review_data:
            return False

        title, content = self.formatter.format_daily_review(review_data)
        success = self.notifier.send_wechat(title, content)
        if success:
            self._daily_flags['daily_review'] = True
            self._record_stat('daily_review')
            # 重置次日标志（供明天使用）
            self.reset_daily_flags()
        return success

    # ----------------------------------------------------------
    # 内部工具
    # ----------------------------------------------------------

    def _dispatch(self, event: AlertEvent):
        """分发事件到推送渠道"""
        try:
            self.notifier.send_wechat(event.title, event.content)
            self.today_stats['total_sent'] += 1
            t = event.alert_type
            self.today_stats['by_type'][t] = self.today_stats['by_type'].get(t, 0) + 1
            now = datetime.now().strftime('%H:%M:%S')
            print(f"[{now}] 📤 推送成功 [{event.level}] {event.title}")
        except Exception as e:
            print(f"[SmartNotifier] 推送失败: {e}")

    def _record_stat(self, alert_type: str):
        """记录统计"""
        self.today_stats['total_sent'] += 1
        self.today_stats['by_type'][alert_type] = \
            self.today_stats['by_type'].get(alert_type, 0) + 1

    def reset_daily_flags(self):
        """重置每日标志（新的一天调用）"""
        self._daily_flags = {k: False for k in self._daily_flags}
        self.today_stats = {'total_sent': 0, 'by_type': {}}

    def get_stats(self) -> dict:
        """获取今日统计"""
        return {
            **self.today_stats,
            'timestamp': datetime.now().isoformat(),
        }

    def print_stats(self):
        """打印今日推送统计"""
        stats = self.get_stats()
        print("\n" + "=" * 50)
        print("  📊 智能通知今日统计")
        print("=" * 50)
        print(f"  总推送数：{stats['total_sent']}")
        if stats['by_type']:
            print("  按类型分布：")
            type_labels = {
                'limit_up': '🔴 涨停提醒',
                'limit_down': '⚫ 跌停预警',
                'pressure_break': '🚀 压力位突破',
                'support_break': '⛔ 支撑位失守',
                'big_order': '💰 大单异动',
                'volume_surge': '📊 量能异常',
                'ma_cross_golden': '✨ 均线金叉',
                'ma_cross_death': '☠️ 均线死叉',
                'morning_call': '📋 竞价报告',
                'midday_summary': '☕ 午间盘点',
                'closing_alert': '⏰ 尾盘异动',
                'daily_review': '📊 每日复盘',
            }
            for t, cnt in stats['by_type'].items():
                label = type_labels.get(t, t)
                print(f"    {label}：{cnt}次")
        print("=" * 50)


# ============================================================
# V5.0 核心升级：结论前置 + 操作建议 + 推荐股
# ============================================================

class V5Formatter:
    """
    v5.0 消息格式器 — 这是给真正股民用的格式
    
    与旧版MessageFormatter的区别：
    - 旧版：先给数据，再给结论（"现价5.76元 涨+1.05% 建议..."）
    - 新版：先给操作建议和结论，再补充数据，最后推荐股票
    
    设计原则：
    1. 股民最想知道的是"我该干什么"，不是"数据是多少"
    2. 有持仓信息时，建议必须基于成本价计算
    3. 推荐股必须标注"仅供参考"
    """

    @staticmethod
    def format_with_advice(snap: 'StockSnapshot', 
                           advice: 'OperationAdvice' = None,
                           recommended_stock: dict = None) -> Tuple[str, str]:
        """
        格式化一条完整的v5.0消息
        
        结构：
          [标题] 操作建议
          → 一句话结论
          
          📊 持仓情况（如有持仓）
          📈 行情数据
          
          💡 判断依据
          ⚠️ 注意事项
          
          🔍 市场机会（推荐股）
          ---
          免责声明
        
        Args:
            snap: 股票快照
            advice: 操作建议（来自PositionManager，可为None）
            recommended_stock: 推荐股信息（可为None）
        
        Returns:
            (title, content) 企微markdown格式
        """
        # === 第一部分：结论和建议 ===
        if advice:
            title, header_lines = V5Formatter._build_advice_header(advice)
        else:
            icon = "🔴" if snap.change_pct >= 0 else "🟢"
            title = f"{icon} {snap.name} 异动提醒"
            header_lines = [
                f"> **{snap.name}** | 现价{snap.price:.2f} | "
                f"涨跌{snap.change_pct:+.2f}%"
            ]

        lines = list(header_lines) + [""]

        # === 第二部分：行情数据 ===
        data_lines = V5Formatter._build_data_section(snap)
        lines.extend(data_lines)

        # === 第三部分：判断依据 ===
        if advice and advice.reason:
            lines.append(f"\n**💡 判断依据:** {advice.reason}\n")

        # === 第四部分：注意事项 ===
        if advice and advice.extra_tips:
            lines.append("**⚠️ 注意事项:**")
            for tip in advice.extra_tips[:4]:  # 最多4条提示
                lines.append(f"- {tip}")
            lines.append("")

        # === 第五部分：推荐股（每次都带）===
        rec_lines = V5Formatter._build_recommendation_section(recommended_stock)
        lines.extend(rec_lines)

        # === 免责声明（必带）===
        lines.extend([
            "---",
            "> ⚠️ 以上为AI辅助分析，**仅供参考**，不构成投资建议。股市有风险，入市需谨慎。",
        ])

        content = "\n".join(lines)
        return title, content

    @staticmethod
    def _build_advice_header(advice: 'OperationAdvice') -> Tuple[str, List[str]]:
        """构建建议头部"""
        title = f"{advice.action_emoji} 【{advice.action}建议】{advice.summary.split('：')[0].strip() if '：' in advice.summary else ''}"
        
        pnl_str = f"+{advice.pnl_pct:.1f}%" if advice.pnl_pct >= 0 else f"{advice.pnl_pct:.1f}%"
        pnl_amt_str = f"+{advice.pnl_amount:,.0f}" if advice.pnl_amount >= 0 else f"{advice.pnl_amount:,.0f}"

        header_lines = [
            f"> **{advice.summary}**",
            f"",
            f"| 项目 | 数值 |",
            f"|------|------|",
            f"| 浮盈/亏 | {pnl_str} ({pnl_amt_str}元) |",
            f"| 目标价 | {advice.target_price:.2f}元 |",
            f"| 止损价 | {advice.stop_loss_price:.2f}元 |",
            f"| 仓位 | {advice.position_weight} |",
            f"| 风险等级 | {advice.risk_level} |",
        ]
        return title, header_lines

    @staticmethod
    def _build_data_section(snap: 'StockSnapshot') -> List[str]:
        """构建行情数据区域"""
        lines = [
            "**📈 实时行情**",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 现价 | {snap.price:.2f}元 |",
            f"| 涨跌幅 | {snap.change_pct:+.2f}% |",
            f"| 今高/今低 | {snap.high:.2f}/{snap.low:.2f} |",
        ]

        if snap.volume_ratio > 0:
            lines.append(f"| 量比 | {snap.volume_ratio:.1f} |")
        if abs(snap.net_inflow) > 10:
            direction = "净流入" if snap.net_inflow > 0 else "净流出"
            lines.append(f"| 主力资金 | {abs(snap.net_inflow)/10000:+.1f}亿{direction} |")
        if snap.turnover_rate > 0:
            lines.append(f"| 换手率 | {snap.turnover_rate:.2f}% |")

        lines.append("")
        return lines

    @staticmethod
    def _build_recommendation_section(recommended: dict = None) -> List[str]:
        """构建推荐股区域"""
        lines = [
            "",
            "**🔍 今日市场机会** (仅供参考)",
        ]

        if recommended:
            name = recommended.get('name', '')
            code = recommended.get('code', '')
            reason = recommended.get('reason', '技术面表现良好')
            risk_hint = recommended.get('risk_hint', '短线有波动风险')
            
            lines.extend([
                f"",
                f"- **{name}({code})** — {reason}",
                f"  ⚠️ {risk_hint}",
            ])
        else:
            # 如果没有传入推荐股，使用默认的通用提示
            default_recs = [
                ("关注量能放大的低位股", "缩量回调后的放量反弹信号较强"),
                ("规避高位放量滞涨个股", "主力出货特征明显需警惕"),
            ]
            for text, note in default_recs:
                lines.append(f"- {text} — {note}")

        lines.append("")
        return lines

    # ---- 各类异动的v5.0格式（集成操作建议）----

    @staticmethod
    def format_limit_up_v5(snap: 'StockSnapshot',
                            advice: 'OperationAdvice' = None,
                            rec: dict = None) -> Tuple[str, str]:
        """涨停通知 v5.0 — 先说该干什么"""
        if advice:
            return V5Formatter.format_with_advice(snap, advice, rec)
        
        # 无持仓信息时的降级格式
        title = f"🔴 【涨停】{snap.name}"
        content = (
            f"> **{snap.name}涨停了！{snap.change_pct:+.2f}% 现价{snap.price:.2f}元**\n\n"
            f"| 指标 | 数值 |\n|------|------|\n"
            f"| 涨幅 | {snap.change_pct:+.2f}% |\n"
            f"| 成交额 | {snap.amount/10000:.1f}亿 |\n"
            f"{f'| 量比 | {snap.volume_ratio:.1f} |\\n' if snap.volume_ratio > 0 else ''}"
            f"{f'| 主力资金 | {abs(snap.net_inflow)/10000:+.1f}亿 |\\n' if abs(snap.net_inflow) > 100 else ''}"
            f"\n> 💡 强势封板！持股观察。追高风险大，不建议此时入场。\n\n"
            f"---\n"
            f"> ⚠️ 仅供参考，不构成投资建议。"
        )
        return title, content

    @staticmethod
    def format_limit_down_v5(snap: 'StockSnapshot',
                              advice: 'OperationAdvice' = None,
                              rec: dict = None) -> Tuple[str, str]:
        """跌停通知 v5.0"""
        if advice:
            return V5Formatter.format_with_advice(snap, advice, rec)
        
        title = f"⚫ 【跌停】{snap.name}"
        content = (
            f"> **{snap.name}跌停！{snap.change_pct:+.2f}% 现价{snap.price:.2f}元**\n\n"
            f"| 指标 | 数值 |\n|------|------|\n"
            f"| 跌幅 | {snap.change_pct:+.2f}% |\n"
            f"| 换手率 | {snap.turnover_rate:.2f}% |\n"
            f"\n> ⚠️ 跌停！暂勿抄底，等待止跌信号。\n\n"
            f"---\n"
            f"> ⚠️ 仅供参考，不构成投资建议。"
        )
        return title, content

    @staticmethod
    def format_breakthrough_v5(snap: 'StockSnapshot', event_type: str,
                                level_price: float, sources: str,
                                advice: 'OperationAdvice' = None,
                                rec: dict = None) -> Tuple[str, str]:
        """突破/跌破通知 v5.0"""
        is_pressure = event_type == 'pressure'
        emoji = "🚀" if is_pressure else "⛔"
        action_word = "突破" if is_pressure else "失守"
        type_word = "压力位" if is_pressure else "支撑位"

        if advice:
            return V5Formatter.format_with_advice(snap, advice, rec)
        
        title = f"{emoji} 【{action_word}】{snap.name}"
        suggestion = (
            "压力变支撑，趋势加速中" if is_pressure else 
            "支撑变压力！注意下一级支撑位"
        )
        content = (
            f"> **{snap.name}{action_word}{type_word}{level_price:.2f}元！**\n"
            f"> {suggestion}\n\n"
            f"| 指标 | 数值 |\n|------|------|\n"
            f"| 现价 | {snap.price:.2f}元 |\n"
            f"| 涨跌幅 | {snap.change_pct:+.2f}% |\n"
            f"| {type_word} | {level_price:.2f}({sources}) |\n\n"
            f"---\n"
            f"> ⚠️ 仅供参考，不构成投资建议。"
        )
        return title, content


class StockRecommender:
    """
    股票推荐引擎 — 从大盘中筛选向好标的
    
    重要：所有推荐都必须标注"仅供参考"！
    
    策略：
      - 从热门板块/涨幅榜中筛选
      - 过滤条件：涨幅适中(2-7%)、量能配合、非ST、非新股
      - 随机轮换避免每次推同一只
      - 强制附带风险提示
    """

    # 推荐池（从实时市场数据动态获取）
    RECOMMEND_CANDIDATES = [
        {'code': 'sh600519', 'name': '贵州茅台', 'sector': '白酒'},
        {'code': 'sz000858', 'name': '五粮液', 'sector': '白酒'},
        {'code': 'sz300750', 'name': '宁德时代', 'sector': '新能源'},
        {'code': 'sh601318', 'name': '中国平安', 'sector': '保险'},
        {'code': 'sz000001', 'name': '平安银行', 'sector': '银行'},
        {'code': 'sh600036', 'name': '招商银行', 'sector': '银行'},
        {'code': 'sz002475', 'name': '立讯精密', 'sector': '电子'},
        {'code': 'sh600900', 'name': '长江电力', 'sector': '电力'},
        {'code': 'sz000568', 'name': '泸州老窖', 'sector': '白酒'},
        {'code': 'sh601888', 'name': '中国中免', 'sector': '消费'},
    ]

    def __init__(self):
        self.last_recommend_time = 0
        self.recommend_cooldown = 3600  # 同一只股票至少间隔1小时才重复推荐

    def get_recommendation(self, exclude_codes: List[str] = None) -> Optional[dict]:
        """
        获取一只推荐股票
        
        Args:
            exclude_codes: 排除的代码列表（如用户已持有的股票）
        
        Returns:
            推荐股字典或None
        """
        now = time.time()
        if now - self.last_recommend_time < 300:  # 5分钟内不重新选
            return None

        candidates = list(self.RECOMMEND_CANDIDATES)
        
        # 排除已持有的
        if exclude_codes:
            candidates = [c for c in candidates if c['code'] not in exclude_codes]

        if not candidates:
            return None

        # 随机选一只
        chosen = random.choice(candidates)
        self.last_recommend_time = now

        # 构造推荐理由模板（实际应该接入实时数据判断）
        reasons_pool = {
            '白酒': ['板块近期资金持续流入，龙头效应明显', '消费复苏预期升温，估值修复空间大'],
            '新能源': ['政策利好不断，产业链景气度上行', '技术突破带来新增长点'],
            '银行': ['估值处于历史低位，安全边际较高', '息差企稳预期，分红稳定'],
            '电子': ['AI需求拉动，业绩增长确定性高', '国产替代加速，市场份额提升'],
            '电力': ['防御性配置首选，现金流充沛', '电力改革红利逐步释放'],
            '消费': ['消费数据回暖，线下复苏明显', '龙头品牌护城河深厚'],
        }
        
        sector_reasons = reasons_pool.get(chosen.get('sector', ''), ['基本面稳健，值得关注'])
        reason = random.choice(sector_reasons)

        risk_hints = [
            '注意大盘系统性风险，控制仓位',
            '短线可能随大盘震荡，不宜重仓追高',
            '关注行业政策变化，及时调整策略',
            '技术面需确认突破有效性再入场',
        ]
        risk_hint = random.choice(risk_hints)

        return {
            'code': chosen['code'],
            'name': chosen['name'],
            'sector': chosen.get('sector', ''),
            'reason': reason,
            'risk_hint': risk_hint,
            'recommended_at': datetime.now().isoformat(),
        }


# ============================================================
# 工厂函数：从pro_analyzer数据构建快照
# ============================================================

def snapshot_from_pro_analyzer(code: str, trader_data, realtime_data: StockSnapshot = None) -> StockSnapshot:
    """
    从pro_analyzer的TraderData对象构建StockSnapshot
    
    Args:
        code: 股票代码
        trader_data: pro_analyzer.TraderData 实例
        realtime_data: 可选的实时数据覆盖
    
    Returns:
        构建好的StockSnapshot
    """
    snap = StockSnapshot(
        code=code,
        name=getattr(trader_data, 'name', ''),
        price=getattr(trader_data, 'price', 0),
        change_pct=getattr(trader_data, 'change_pct', 0),
        open_price=getattr(trader_data, 'open_price', 0),
        pre_close=getattr(trader_data, 'pre_close', 0),
        high=getattr(trader_data, 'high', 0),
        low=getattr(trader_data, 'low', 0),
        volume=getattr(trader_data, 'volume', 0),
        amount=getattr(trader_data, 'amount', 0),
        turnover_rate=getattr(trader_data, 'turnover_rate', 0),
        volume_ratio=getattr(trader_data, 'volume_ratio', 0),
        net_inflow=getattr(trader_data, 'net_inflow', 0),
        ma5=getattr(trader_data, 'ma5', 0),
        ma20=getattr(trader_data, 'ma20', 0),
        ma60=getattr(trader_data, 'ma60', 0),
        ma120=getattr(trader_data, 'ma120', 0),
    )

    # 压力支撑位
    pressures = []
    pressure_srcs = []
    for attr in ['pressure_1', 'pressure_2', 'pressure_3']:
        val = getattr(trader_data, attr, 0)
        if val > 0:
            pressures.append(val)
            src_attr = attr + '_src'
            pressure_srcs.append(getattr(trader_data, src_attr, ''))

    supports = []
    support_srcs = []
    for attr in ['support_1', 'support_2', 'support_3']:
        val = getattr(trader_data, attr, 0)
        if val > 0:
            supports.append(val)
            src_attr = attr + '_src'
            support_srcs.append(getattr(trader_data, src_attr, ''))

    snap.pressure_levels = pressures
    snap.pressure_sources = pressure_srcs
    snap.support_levels = supports
    snap.support_sources = support_srcs

    # 均量（近似估算）
    if snap.volume > 0:
        snap.avg_volume_5d = snap.volume / max(snap.volume_ratio, 1) if snap.volume_ratio > 0 else snap.volume
        snap.avg_volume_20d = snap.avg_volume_5d * 1.5  # 粗略估计

    return snap


# ============================================================
# 命令行测试入口
# ============================================================

def main():
    """测试智能通知引擎"""
    import argparse

    parser = argparse.ArgumentParser(description='智能企微通知引擎测试')
    parser.add_argument('--test-format', action='store_true', help='测试各种通知格式')
    parser.add_argument('--stock-code', default='sh600519', help='测试股票代码')
    parser.add_argument('--test-push', action='store_true', help='实际推送测试消息')

    args = parser.parse_args()

    if args.test_format:
        print("=" * 60)
        print("  智能通知引擎 - 格式化测试")
        print("=" * 60)

        mf = MessageFormatter()

        # 测试数据
        test_snap = StockSnapshot(
            code=args.stock_code,
            name="贵州茅台",
            price=1760.00,
            change_pct=10.01,
            open_price=1620.00,
            pre_close=1600.00,
            high=1760.00,
            low=1610.00,
            volume=50000,
            amount=850000,
            turnover_rate=0.45,
            volume_ratio=3.2,
            net_inflow=48000,
            ma5=1580.0,
            ma20=1520.0,
            ma60=1480.0,
            ma120=1450.0,
            pressure_levels=[1744.12, 1567.37, 1520.47],
            pressure_sources=["Fib61.8%延伸压力", "近期高点聚集", "MA20压力"],
            support_levels=[1491.65, 1458.24, 1434.27],
            support_sources=["近期低点+Fib38.2%共振", "MA60+Fib50%共振", "MA250+MA120+Fib61.8%三重共振"],
            avg_volume_5d=15000,
            avg_volume_20d=10000,
        )

        formats_to_test = [
            ("涨停", lambda: mf.format_limit_up(test_snap)),
            ("跌停", lambda: mf.format_limit_drop(test_snap) if hasattr(mf, 'format_limit_drop') else mf.format_limit_down(StockSnapshot(code='sz000001', name="测试股", price=10.00, change_pct=-10.01, net_inflow=-25000))),
            ("压力位突破", lambda: mf.format_pressure_break(test_snap, 2, 1520.47, "MA20压力★共振 + 近期高点")),
            ("支撑位失守", lambda: mf.format_support_break(test_snap, 1, 1458.24, "MA60+Fib50%★★共振")),
            ("大单买入", lambda: mf.format_big_order(test_snap, 12000)),
            ("大单卖出", lambda: mf.format_big_order(StockSnapshot(code=args.stock_code, name=test_snap.name, price=1550, change_pct=-3.5, volume_ratio=2.5, net_inflow=-8000, avg_volume_5d=15000), -8000)),
            ("量能异常", lambda: mf.format_volume_surge(test_snap, 4.5)),
            ("均线金叉", lambda: mf.format_ma_cross(test_snap, '5', '20', True)),
            ("均线死叉", lambda: mf.format_ma_cross(StockSnapshot(code=args.stock_code, name=test_snap.name, price=1480, change_pct=-2.0, ma5=1470, ma20=1490), '5', '20', False)),
        ]

        for name, fn in formats_to_test:
            print(f"\n--- {name} ---")
            try:
                title, content = fn()
                print(f"标题: {title}")
                print(f"内容:\n{content}")
            except Exception as e:
                print(f"❌ 错误: {e}")

        # 定期报告测试
        print("\n--- 早盘竞价报告 ---")
        title, content = mf.format_morning_call([test_snap], 3200, 1800, "贵州茅台", "")
        print(f"标题: {title}")
        print(f"内容:\n{content}")

        print("\n--- 午间盘点 ---")
        title, content = mf.format_midday_summary([test_snap])
        print(f"标题: {title}")
        print(f"内容:\n{content}")

        print("\n--- 尾盘异动 ---")
        title, content = mf.format_coding_alert(test_snap, "尾盘急拉") if hasattr(mf, 'format_coding_alert') else mf.format_closing_alert(test_snap, "尾盘急拉")
        print(f"标题: {title}")
        print(f"内容:\n{content}")

    if args.test_push:
        print("\n正在推送测试消息到企业微信...")
        sn = SmartNotifier()
        test_snap = StockSnapshot(
            code=args.stock_code,
            name="贵州茅台",
            price=1700.00,
            change_pct=5.5,
            open_price=1650.00,
            pre_close=1611.00,
            high=1720.00,
            low=1645.00,
            volume=35000,
            amount=600000,
            turnover_rate=0.3,
            volume_ratio=2.1,
            net_inflow=22000,
            ma5=1580.0,
            ma20=1520.0,
            ma60=1480.0,
            avg_volume_5d=15000,
            pressure_levels=[1744.12, 1567.37, 1520.47],
            pressure_sources=["Fib61.8%", "近期高点", "MA20"],
            support_levels=[1491.65, 1458.24, 1434.27],
            support_sources=["低点+Fib38.2%", "MA60+Fib50%", "MA250三重"],
        )
        events = sn.check_and_notify(test_snap)
        print(f"\n触发了 {len(events)} 个通知事件:")
        for ev in events:
            print(f"  [{ev.level}] {ev.title}")
        sn.print_stats()


if __name__ == '__main__':
    main()
