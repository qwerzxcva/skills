#!/usr/bin/env python3
"""
股票监测助手 Skill - 统一入口

功能模块：
- monitor.py: 实时监测盯盘
- query.py: 单股/大盘/批量查询
- market_data.py: 板块/涨跌停榜数据
- data_source.py: 多数据源管理

使用方式：
    from stock_monitor import StockMonitor
    
    monitor = StockMonitor()
    monitor.query_stock("600519")  # 查茅台
    monitor.query_market()          # 查大盘
    monitor.start_monitor(["sh600519", "sz000001"])  # 开始监测
"""

from .data_source import MultiDataSource, StockData
from .query import query_single_stock, query_market_indices, query_batch_stocks
from .market_data import print_plate_data, print_limit_up_list, print_limit_down_list
from .analyzer import StockAnalyzer, AnalysisResult
from .news_monitor import NewsMonitor, NewsItem, Announcement
from .watchlist import WatchlistManager, WatchStock
from .notifier import Notifier, NotificationConfig


class StockMonitor:
    """股票监测助手统一接口"""
    
    def __init__(self):
        self.data_source = MultiDataSource()
        self.watchlist = WatchlistManager()
        self.notifier = Notifier()
        self.news = NewsMonitor()
    
    def query_stock(self, code: str):
        """查询单只股票"""
        return query_single_stock(code)
    
    def query_market(self):
        """查询大盘指数"""
        return query_market_indices()
    
    def query_batch(self, codes: list):
        """批量查询股票"""
        return query_batch_stocks(codes)
    
    def get_plates(self):
        """获取板块数据"""
        return print_plate_data()
    
    def get_limit_up(self):
        """获取涨停榜"""
        return print_limit_up_list()
    
    def get_limit_down(self):
        """获取跌停榜"""
        return print_limit_down_list()
    
    def add_watch(self, code: str, name: str, **kwargs):
        """添加自选股"""
        return self.watchlist.add(code, name, **kwargs)
    
    def remove_watch(self, code: str):
        """删除自选股"""
        return self.watchlist.remove(code)
    
    def get_watchlist(self):
        """获取自选股列表"""
        return self.watchlist.get_all()
    
    def check_watchlist_alerts(self):
        """检查自选股异动"""
        return self.watchlist.check_alerts()
    
    def send_notification(self, title: str, content: str):
        """发送通知"""
        return self.notifier.send(title, content)
    
    def fetch_news(self, code: str):
        """获取新闻"""
        return self.news.fetch_news(code)
    
    def fetch_announcements(self, code: str):
        """获取公告"""
        return self.news.fetch_announcements(code)


__all__ = [
    'StockMonitor',
    'StockAnalyzer',
    'AnalysisResult',
    'NewsMonitor',
    'NewsItem',
    'Announcement',
    'WatchlistManager',
    'WatchStock',
    'Notifier',
    'NotificationConfig',
    'MultiDataSource',
    'StockData',
    'query_single_stock',
    'query_market_indices',
    'query_batch_stocks',
    'print_plate_data',
    'print_limit_up_list',
    'print_limit_down_list'
]

__version__ = '3.1.0'
__author__ = '大闸蟹'
