#!/usr/bin/env python3
"""
股票实时监测助手 v5.0 - Skill版本
支持多数据源交叉验证、异动提醒、智能企微通知、持仓管理

v5.0 重大升级（产品化改造）：
  - 集成 PositionManager：记录成本价/仓位，计算浮盈亏，给操作建议
  - 集成 V5Formatter：先给结论和数据，最后附推荐股（标注仅供参考）
  - 集成 StockRecommender：从大盘筛选向好标的
  - 集成 OnboardingFlow：新股民交互式引导
  - 集成 Guardian：进程守护自动重启
  - 通知格式全面重构：结论前置 → 数据 → 推荐 → 免责声明

v4.0 能力保留：
  - SmartNotifier 智能通知引擎（8种异动 + 4种定时报告）
  - 多数据源交叉验证
  - 防刷机制 + 冷却控制
"""

import sys
import os
import io
import time
import json
from datetime import datetime
from typing import Dict, List, Optional

# Windows GBK终端兼容：强制UTF-8输出
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_source import MultiDataSource, StockData

# 尝试导入Windows弹窗
try:
    from win10toast import ToastNotifier
    TOAST_AVAILABLE = True
except ImportError:
    TOAST_AVAILABLE = False

# 尝试导入推送通知
try:
    from notifier import Notifier
    NOTIFIER_AVAILABLE = True
except ImportError:
    NOTIFIER_AVAILABLE = False

# 尝试导入智能通知引擎
try:
    from smart_notifier import (
        SmartNotifier, StockSnapshot as SmartSnapshot,
        V5Formatter, StockRecommender
    )
    SMART_NOTIFIER_AVAILABLE = True
except ImportError:
    SMART_NOTIFIER_AVAILABLE = False
    V5Formatter = None
    StockRecommender = None

# 尝试导入持仓管理器
try:
    from position_manager import PositionManager, OperationAdvice
    POSITION_MANAGER_AVAILABLE = True
except ImportError:
    POSITION_MANAGER_AVAILABLE = False
    PositionManager = None
    OperationAdvice = None

# 尝试导入pro_analyzer（用于获取压力支撑位等深度数据）
try:
    from pro_analyzer import TraderAnalyzer
    PRO_ANALYZER_AVAILABLE = True
except ImportError:
    PRO_ANALYZER_AVAILABLE = False


class StockMonitorSkill:
    """股票监测Skill主类 v5.0 — 产品化版本"""
    
    def __init__(self, smart_notify: bool = True):
        self.data_source = MultiDataSource()
        self.watch_list: Dict[str, dict] = {}
        self.history: Dict[str, List[StockData]] = {}
        self.toaster = ToastNotifier() if TOAST_AVAILABLE else None
        self.notifier = Notifier() if NOTIFIER_AVAILABLE else None
        self.running = False
        self.alert_log = []
        
        # 智能通知引擎（v4.0+）
        self.smart_notifier: Optional[SmartNotifier] = None
        if smart_notify and SMART_NOTIFIER_AVAILABLE and NOTIFIER_AVAILABLE:
            self.smart_notifier = SmartNotifier(notifier=self.notifier)
            print("[智能通知引擎已加载] ✅")
        
        # v5.0新增：持仓管理器
        self.position_manager: Optional[PositionManager] = None
        if POSITION_MANAGER_AVAILABLE:
            self.position_manager = PositionManager()
            positions = self.position_manager.list_positions()
            if positions:
                print(f"[持仓管理已加载] ✅ ({len(positions)}只持仓)")
            else:
                print("[持仓管理已加载] (暂无持仓，用 position_manager.py add 添加)")
        
        # v5.0新增：推荐引擎
        self.recommender: Optional[StockRecommender] = None
        if StockRecommender is not None:
            self.recommender = StockRecommender()
        
        # 深度分析器缓存（用于获取压力支撑位）
        self.analyzer_cache: Dict[str, dict] = {}
        self._analyzer_last_update: float = 0
        self._ANALYZER_CACHE_TTL = 300
        
    def parse_stock_args(self, stocks_str: str) -> List[dict]:
        """解析股票参数"""
        stocks = []
        for item in stocks_str.split(','):
            parts = item.strip().split(':')
            if len(parts) >= 1:
                code = parts[0]
                name = parts[1] if len(parts) > 1 else code
                threshold = float(parts[2]) if len(parts) > 2 else 2.0
                stocks.append({
                    'code': code,
                    'name': name,
                    'threshold': threshold
                })
        return stocks
    
    def add_stock(self, code: str, name: str = None, threshold: float = 2.0):
        """添加监测股票"""
        self.watch_list[code] = {
            'name': name or code,
            'threshold': threshold,
            'last_alert': None,
            'alert_count': 0
        }
        
    def show_notification(self, title: str, message: str):
        """显示通知（仅终端打印，不推企微——企微由智能通知引擎统一管理）"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"\n{'='*60}")
        print(f"[{timestamp}] [{title}]")
        print(message)
        print('='*60)
        
        # 记录到日志
        self.alert_log.append({
            'time': timestamp,
            'title': title,
            'message': message
        })
        
        # 注意：已移除企微推送和Windows弹窗
        # 企微推送由智能通知引擎(SmartNotifier)统一管理，避免重复
    
    def check_alerts(self, code: str, data: StockData):
        """
        传统提醒检查（已降级为仅日志记录）
        
        企微推送已统一由智能通知引擎(SmartNotifier)管理
        这里只记录日志，不再触发任何推送/弹窗
        """
        config = self.watch_list.get(code)
        if not config:
            return
        
        # 记录到日志（不推送、不弹窗）
        if abs(data.change_pct) >= config['threshold']:
            direction = "大涨" if data.change_pct > 0 else "大跌"
            timestamp = datetime.now().strftime('%H:%M:%S')
            self.alert_log.append({
                'time': timestamp,
                'title': f'[{direction}] {data.name}',
                'message': f'涨跌幅: {data.change_pct:+.2f}% 当前价: {data.price:.2f}'
            })
    
    def monitor_once(self):
        """执行一次监测（v4.1：静默模式，只在异动时推送企微）"""
        codes = list(self.watch_list.keys())
        if not codes:
            return False
        
        # 获取多源数据
        all_data = self.data_source.fetch_all(codes)
        verified_data = self.data_source.cross_verify(all_data)
        
        for code, data in verified_data.items():
            # 保存历史
            if code not in self.history:
                self.history[code] = []
            self.history[code].append(data)
            if len(self.history[code]) > 100:
                self.history[code].pop(0)
            
            # 传统提醒（仅日志，不推送）
            self.check_alerts(code, data)
            
            # v4.1：智能通知引擎（唯一推送渠道，只在状态变化时推送）
            if self.smart_notifier and SMART_NOTIFIER_AVAILABLE:
                self._smart_notify_check(code, data)
        
        return True
    
    def _smart_notify_check(self, code: str, data: StockData):
        """
        构建快照并调用智能通知引擎（v5.0：集成持仓建议+推荐股）
        
        v5.0 改进：
          1. 如果有持仓信息 → 操作建议前置
          2. 每条消息末尾附推荐股（标注仅供参考）
        """
        try:
            # 尝试获取深度分析数据（含压力支撑位、均线等）
            analyzer_data = self._get_analyzer_data(code)
            
            # 计算pre_close（用当前价和涨跌幅反推）
            pre_close = 0
            if data.change_pct and data.change_pct != -100:
                pre_close = data.price / (1 + data.change_pct / 100)
            
            # === v5.0: 获取操作建议（如果有持仓）===
            advice = None
            if self.position_manager and self.position_manager.has_position(code):
                advice = self.position_manager.get_advice(
                    code, current_price=data.price, change_pct=data.change_pct
                )
            
            # === v5.0: 获取推荐股 ===
            recommended = None
            if self.recommender:
                exclude_codes = list(self.position_manager.positions.keys()) if self.position_manager else []
                recommended = self.recommender.get_recommendation(exclude_codes=exclude_codes)
            
            # 构建快照
            snap = SmartSnapshot(
                code=code,
                name=data.name,
                price=data.price,
                change_pct=data.change_pct,
                open_price=getattr(data, 'open', 0) or 0,
                pre_close=pre_close,
                high=data.high or data.price,
                low=data.low or data.price,
                volume=getattr(data, 'volume', 0) or 0,
                amount=getattr(data, 'amount', 0) or 0,
                turnover_rate=analyzer_data.get('turnover_rate', 0),
                volume_ratio=analyzer_data.get('volume_ratio', 0),
                net_inflow=analyzer_data.get('net_inflow', 0),
                ma5=analyzer_data.get('ma5', 0),
                ma20=analyzer_data.get('ma20', 0),
                ma60=analyzer_data.get('ma60', 0),
                ma120=analyzer_data.get('ma120', 0),
                pressure_levels=analyzer_data.get('pressure_levels', []),
                pressure_sources=analyzer_data.get('pressure_sources', []),
                support_levels=analyzer_data.get('support_levels', []),
                support_sources=analyzer_data.get('support_sources', []),
            )
            
            # 计算均量（从历史数据估算）
            if code in self.history and len(self.history[code]) >= 5:
                recent_vols = [h.volume for h in self.history[code][-5:] if h.volume > 0]
                if recent_vols:
                    snap.avg_volume_5d = sum(recent_vols) / len(recent_vols)
                    snap.avg_volume_20d = snap.avg_volume_5d * 1.5
            
            # 调用智能通知引擎
            events = self.smart_notifier.check_and_notify(snap)
            
            # === v5.0: 如果有建议且触发了事件，额外推送一条带建议的完整消息 ===
            if advice and events and V5Formatter is not None:
                title, content = V5Formatter.format_with_advice(
                    snap, advice=advice, recommended_stock=recommended
                )
                try:
                    self.notifier.send_wechat(title, content)
                    print(f"[V5建议] 已推送 {advice.action}建议 ✅")
                except Exception as e:
                    print(f"[V5建议] 推送失败: {e}")
            
        except Exception as e:
            # 打印错误便于排查
            print(f"[SmartNotifier错误] {code}: {e}")
    
    def _get_analyzer_data(self, code: str) -> dict:
        """
        获取股票的深度分析数据（压力支撑位等）
        使用缓存机制避免频繁调用分析接口
        """
        now = time.time()
        
        # 缓存有效则直接返回
        if code in self.analyzer_cache and (now - self._analyzer_last_update) < self._ANALYZER_CACHE_TTL:
            return self.analyzer_cache[code]
        
        result = {
            'turnover_rate': 0, 'volume_ratio': 0, 'net_inflow': 0,
            'ma5': 0, 'ma20': 0, 'ma60': 0, 'ma120': 0,
            'pressure_levels': [], 'pressure_sources': [],
            'support_levels': [], 'support_sources': [],
        }
        
        if not PRO_ANALYZER_AVAILABLE:
            return result
        
        try:
            analyzer = TraderAnalyzer()
            trader_data = analyzer.analyze(code)
            if trader_data:
                result.update({
                    'turnover_rate': getattr(trader_data, 'turnover_rate', 0),
                    'volume_ratio': getattr(trader_data, 'volume_ratio', 0),
                    'net_inflow': getattr(trader_data, 'net_inflow', 0),
                    'ma5': getattr(trader_data, 'ma5', 0),
                    'ma20': getattr(trader_data, 'ma20', 0),
                    'ma60': getattr(trader_data, 'ma60', 0),
                    'ma120': getattr(trader_data, 'ma120', 0),
                    'pressure_levels': [
                        getattr(trader_data, 'pressure_1', 0),
                        getattr(trader_data, 'pressure_2', 0),
                        getattr(trader_data, 'pressure_3', 0),
                    ],
                    'pressure_sources': [
                        getattr(trader_data, 'pressure_1_src', ''),
                        getattr(trader_data, 'pressure_2_src', ''),
                        getattr(trader_data, 'pressure_3_src', ''),
                    ],
                    'support_levels': [
                        getattr(trader_data, 'support_1', 0),
                        getattr(trader_data, 'support_2', 0),
                        getattr(trader_data, 'support_3', 0),
                    ],
                    'support_sources': [
                        getattr(trader_data, 'support_1_src', ''),
                        getattr(trader_data, 'support_2_src', ''),
                        getattr(trader_data, 'support_3_src', ''),
                    ],
                })
                # 更新缓存
                self.analyzer_cache[code] = result
                self._analyzer_last_update = now
                
        except Exception as e:
            pass  # 分析失败返回空结果
        
        return result
    
    def start(self, interval: int = 30, duration: int = 60):
        """开始监测"""
        self.running = True
        total_seconds = duration * 60
        elapsed = 0
        
        print("\n" + "="*60)
        print("  股票实时监测助手 v5.0 🦀")
        print("  产品化版本：持仓建议 + 推荐股 + 进程守护")
        print("="*60)
        print(f"监测股票: {len(self.watch_list)} 只")
        for code, config in self.watch_list.items():
            print(f"  - {config['name']}({code}): 提醒阈值 {config['threshold']}%")
        print(f"监测间隔: {interval}秒")
        print(f"监测时长: {duration}分钟")
        print(f"数据源: 腾讯+东财+新浪 (交叉验证)")
        if self.smart_notifier:
            print("智能通知: ✅ 已启用")
            if self.position_manager:
                pos = self.position_manager.list_positions()
                print(f"持仓管理: ✅ 已加载 ({len(pos)}只)")
            if self.recommender:
                print("推荐引擎: ✅ 已加载")
        else:
            print("智能通知: ❌ 未加载")
        print("="*60)
        print("提示：使用 guardian.py 可实现自动守护，进程中断自动重启")
        print("按 Ctrl+C 停止监测\n")
        
        try:
            while self.running and elapsed < total_seconds:
                self.monitor_once()
                time.sleep(interval)
                elapsed += interval
                
                # 每5分钟显示一次简短进度
                remaining = (total_seconds - elapsed) // 60
                if elapsed % 300 == 0 and elapsed > 0:
                    # 获取最新价格用于进度显示
                    status_parts = []
                    for code, config in self.watch_list.items():
                        if code in self.history and self.history[code]:
                            last = self.history[code][-1]
                            icon = "▲" if last.change_pct > 0 else "▼"
                            status_parts.append(f"{config['name']}{icon}{last.price:.2f}({last.change_pct:+.2f}%)")
                    status = " | ".join(status_parts) if status_parts else ""
                    print(f"[{elapsed//60}min/{remaining}min] {status}")
                    
        except KeyboardInterrupt:
            print("\n\n[停止] 用户中断监测")
        finally:
            self.running = False
            self.print_summary()
    
    def print_summary(self):
        """打印监测总结"""
        print("\n" + "="*60)
        print("  监测总结")
        print("="*60)
        
        for code, config in self.watch_list.items():
            print(f"\n{config['name']}({code}):")
            print(f"  提醒次数: {config['alert_count']}")
            
            if code in self.history and self.history[code]:
                first = self.history[code][0]
                last = self.history[code][-1]
                print(f"  起始价格: {first.price:.2f}")
                print(f"  最新价格: {last.price:.2f}")
                print(f"  期间涨跌: {last.change_pct:+.2f}%")
        
        if self.alert_log:
            print(f"\n传统提醒共触发 {len(self.alert_log)} 次")
        
        # 智能通知统计（v4.0）
        if self.smart_notifier:
            self.smart_notifier.print_stats()
        
        print("="*60)


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='股票实时监测助手 v4.0')
    parser.add_argument('stocks', help='股票列表，格式: 代码:名称:阈值,代码:名称:阈值')
    parser.add_argument('--interval', '-i', type=int, default=30, help='监测间隔(秒)')
    parser.add_argument('--duration', '-d', type=int, default=60, help='监测时长(分钟)')
    parser.add_argument('--no-smart-notify', action='store_true', help='禁用智能通知引擎')
    
    args = parser.parse_args()
    
    # 创建监测器
    monitor = StockMonitorSkill(smart_notify=not args.no_smart_notify)
    
    # 解析股票参数
    stocks = monitor.parse_stock_args(args.stocks)
    for s in stocks:
        monitor.add_stock(s['code'], s['name'], s['threshold'])
    
    # 开始监测
    monitor.start(interval=args.interval, duration=args.duration)


if __name__ == '__main__':
    main()
