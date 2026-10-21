#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自选股管理模块
管理自选股列表，支持增删改查和批量分析
"""

import json
import os
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from datetime import datetime


@dataclass
class WatchStock:
    """自选股票"""
    code: str           # 股票代码，如 sh600519
    name: str           # 股票名称
    add_time: str       # 添加时间
    category: str       # 分类，如 价值股/成长股/短线股
    notes: str          # 备注
    alert_up: float     # 上涨提醒阈值(%)
    alert_down: float   # 下跌提醒阈值(%)
    cost_price: float   # 成本价(可选)
    hold_days: int      # 持有天数(可选)


class WatchlistManager:
    """自选股管理器"""
    
    def __init__(self, data_file: str = None):
        """
        初始化
        
        Args:
            data_file: 数据文件路径，默认在skill目录下
        """
        if data_file is None:
            skill_dir = os.path.dirname(os.path.abspath(__file__))
            self.data_file = os.path.join(skill_dir, 'watchlist.json')
        else:
            self.data_file = data_file
        
        self.watchlist: Dict[str, WatchStock] = {}
        self.load()
    
    def _normalize_code(self, code: str) -> str:
        """标准化股票代码"""
        code = code.replace('sh', '').replace('sz', '').strip()
        if code.startswith('6'):
            return f'sh{code}'
        elif code.startswith('0') or code.startswith('3'):
            return f'sz{code}'
        return code
    
    def load(self):
        """加载自选股数据"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for code, item in data.items():
                        self.watchlist[code] = WatchStock(**item)
            except Exception as e:
                print(f"加载自选股失败: {e}")
                self.watchlist = {}
    
    def save(self):
        """保存自选股数据"""
        try:
            data = {code: asdict(stock) for code, stock in self.watchlist.items()}
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存自选股失败: {e}")
            return False
    
    def add(self, code: str, name: str, category: str = "默认",
            alert_up: float = 5.0, alert_down: float = -5.0,
            notes: str = "", cost_price: float = 0.0) -> bool:
        """
        添加自选股
        
        Args:
            code: 股票代码
            name: 股票名称
            category: 分类
            alert_up: 上涨提醒阈值(%)
            alert_down: 下跌提醒阈值(%)
            notes: 备注
            cost_price: 成本价
        
        Returns:
            是否添加成功
        """
        normalized_code = self._normalize_code(code)
        
        if normalized_code in self.watchlist:
            print(f"⚠️ {name}({normalized_code}) 已在自选股中")
            return False
        
        stock = WatchStock(
            code=normalized_code,
            name=name,
            add_time=datetime.now().strftime('%Y-%m-%d %H:%M'),
            category=category,
            notes=notes,
            alert_up=alert_up,
            alert_down=alert_down,
            cost_price=cost_price,
            hold_days=0
        )
        
        self.watchlist[normalized_code] = stock
        self.save()
        print(f"✅ 已添加 {name}({normalized_code}) 到自选股")
        return True
    
    def remove(self, code: str) -> bool:
        """
        删除自选股
        
        Args:
            code: 股票代码
        
        Returns:
            是否删除成功
        """
        normalized_code = self._normalize_code(code)
        
        if normalized_code in self.watchlist:
            stock = self.watchlist.pop(normalized_code)
            self.save()
            print(f"✅ 已删除 {stock.name}({normalized_code})")
            return True
        else:
            print(f"⚠️ 股票 {code} 不在自选股中")
            return False
    
    def update(self, code: str, **kwargs) -> bool:
        """
        更新自选股信息
        
        Args:
            code: 股票代码
            **kwargs: 要更新的字段
        
        Returns:
            是否更新成功
        """
        normalized_code = self._normalize_code(code)
        
        if normalized_code not in self.watchlist:
            print(f"⚠️ 股票 {code} 不在自选股中")
            return False
        
        stock = self.watchlist[normalized_code]
        for key, value in kwargs.items():
            if hasattr(stock, key):
                setattr(stock, key, value)
        
        self.save()
        print(f"✅ 已更新 {stock.name}({normalized_code})")
        return True
    
    def get(self, code: str) -> Optional[WatchStock]:
        """
        获取单个自选股
        
        Args:
            code: 股票代码
        
        Returns:
            自选股对象
        """
        normalized_code = self._normalize_code(code)
        return self.watchlist.get(normalized_code)
    
    def get_all(self) -> List[WatchStock]:
        """
        获取所有自选股
        
        Returns:
            自选股列表
        """
        return list(self.watchlist.values())
    
    def get_by_category(self, category: str) -> List[WatchStock]:
        """
        按分类获取自选股
        
        Args:
            category: 分类名称
        
        Returns:
            自选股列表
        """
        return [s for s in self.watchlist.values() if s.category == category]
    
    def get_categories(self) -> List[str]:
        """
        获取所有分类
        
        Returns:
            分类列表
        """
        categories = set(s.category for s in self.watchlist.values())
        return sorted(list(categories))
    
    def clear(self):
        """清空自选股"""
        self.watchlist.clear()
        self.save()
        print("✅ 已清空所有自选股")
    
    def print_list(self, category: str = None):
        """
        打印自选股列表
        
        Args:
            category: 分类筛选，None表示全部
        """
        if category:
            stocks = self.get_by_category(category)
            print(f"\n{'='*70}")
            print(f"自选股列表 - 分类：{category}")
        else:
            stocks = self.get_all()
            print(f"\n{'='*70}")
            print("自选股列表")
        
        print(f"{'='*70}")
        
        if not stocks:
            print("暂无自选股")
            return
        
        print(f"{'代码':<12} {'名称':<10} {'分类':<10} {'上涨提醒':<10} {'下跌提醒':<10} {'备注'}")
        print("-" * 70)
        
        for stock in stocks:
            print(f"{stock.code:<12} {stock.name:<10} {stock.category:<10} "
                  f"{stock.alert_up:>6.1f}%   {stock.alert_down:>6.1f}%   {stock.notes}")
        
        print(f"{'='*70}")
        print(f"共 {len(stocks)} 只股票")
        print(f"{'='*70}\n")
    
    def batch_analyze(self):
        """批量分析所有自选股"""
        from analyzer import StockAnalyzer
        
        stocks = self.get_all()
        if not stocks:
            print("⚠️ 自选股为空，请先添加股票")
            return
        
        analyzer = StockAnalyzer()
        
        print(f"\n{'='*70}")
        print("自选股批量分析")
        print(f"{'='*70}\n")
        
        results = []
        for stock in stocks:
            try:
                result = analyzer.analyze(stock.code, stock.name)
                results.append((stock, result))
                
                # 简表输出
                arrow = "▲" if result.change_pct > 0 else "▼" if result.change_pct < 0 else "→"
                print(f"{stock.code} {stock.name:8} {result.price:>8.2f} {arrow} {result.change_pct:>+6.2f}%  "
                      f"评分:{'★'*result.score}{'☆'*(5-result.score)}  {result.rating}")
            except Exception as e:
                print(f"⚠️ 分析 {stock.name} 失败: {e}")
        
        print(f"\n{'='*70}")
        print(f"分析完成，共 {len(results)} 只股票")
        print(f"{'='*70}\n")
        
        return results
    
    def check_alerts(self):
        """检查自选股提醒"""
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from data_source import MultiDataSource
        
        stocks = self.get_all()
        if not stocks:
            return []
        
        source = MultiDataSource()
        alerts = []
        
        print(f"\n{'='*70}")
        print("自选股异动检查")
        print(f"{'='*70}\n")
        
        for stock in stocks:
            try:
                result = source.fetch_tencent([stock.code])
                if stock.code in result:
                    data = result[stock.code]
                    
                    # 检查上涨提醒
                    if data.change_pct >= stock.alert_up:
                        alerts.append({
                            'type': 'up',
                            'stock': stock,
                            'price': data.price,
                            'change_pct': data.change_pct
                        })
                        print(f"🔔 [{stock.name}] 大涨提醒！")
                        print(f"   当前涨幅：{data.change_pct:+.2f}% (阈值：{stock.alert_up}%)")
                        print(f"   当前价格：{data.price:.2f}")
                    
                    # 检查下跌提醒
                    elif data.change_pct <= stock.alert_down:
                        alerts.append({
                            'type': 'down',
                            'stock': stock,
                            'price': data.price,
                            'change_pct': data.change_pct
                        })
                        print(f"🔔 [{stock.name}] 大跌提醒！")
                        print(f"   当前跌幅：{data.change_pct:.2f}% (阈值：{stock.alert_down}%)")
                        print(f"   当前价格：{data.price:.2f}")
            except Exception as e:
                print(f"⚠️ 检查 {stock.name} 失败: {e}")
        
        if not alerts:
            print("✓ 所有自选股正常，无触发提醒")
        
        print(f"\n{'='*70}\n")
        return alerts


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='自选股管理')
    subparsers = parser.add_subparsers(dest='command', help='子命令')
    
    # 添加
    add_parser = subparsers.add_parser('add', help='添加自选股')
    add_parser.add_argument('code', help='股票代码')
    add_parser.add_argument('name', help='股票名称')
    add_parser.add_argument('--category', '-c', default='默认', help='分类')
    add_parser.add_argument('--up', '-u', type=float, default=5.0, help='上涨提醒阈值(%)')
    add_parser.add_argument('--down', '-d', type=float, default=-5.0, help='下跌提醒阈值(%)')
    add_parser.add_argument('--notes', '-n', default='', help='备注')
    
    # 删除
    remove_parser = subparsers.add_parser('remove', help='删除自选股')
    remove_parser.add_argument('code', help='股票代码')
    
    # 列表
    list_parser = subparsers.add_parser('list', help='显示自选股列表')
    list_parser.add_argument('--category', '-c', help='按分类筛选')
    
    # 分析
    analyze_parser = subparsers.add_parser('analyze', help='批量分析自选股')
    
    # 检查提醒
    alert_parser = subparsers.add_parser('alert', help='检查自选股异动')
    
    # 清空
    clear_parser = subparsers.add_parser('clear', help='清空自选股')
    
    args = parser.parse_args()
    
    manager = WatchlistManager()
    
    if args.command == 'add':
        manager.add(args.code, args.name, args.category, args.up, args.down, args.notes)
    
    elif args.command == 'remove':
        manager.remove(args.code)
    
    elif args.command == 'list':
        manager.print_list(args.category)
    
    elif args.command == 'analyze':
        manager.batch_analyze()
    
    elif args.command == 'alert':
        manager.check_alerts()
    
    elif args.command == 'clear':
        confirm = input("确定要清空所有自选股吗？(yes/no): ")
        if confirm.lower() == 'yes':
            manager.clear()
    
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
