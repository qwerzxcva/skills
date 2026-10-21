#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻/公告监控模块
监控股票相关新闻、公告、研报
"""

import requests
import json
import re
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import quote


@dataclass
class NewsItem:
    """新闻条目"""
    title: str
    url: str
    source: str
    publish_time: str
    summary: str = ""
    sentiment: str = "中性"  # 正面/负面/中性


@dataclass
class Announcement:
    """公告条目"""
    title: str
    type: str  # 业绩预告/重大事项/股权变动/ etc.
    publish_date: str
    content: str = ""


class NewsMonitor:
    """新闻公告监控器"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def _get_stock_prefix(self, code: str) -> str:
        """获取股票代码前缀"""
        code = code.replace('sh', '').replace('sz', '')
        if code.startswith('6'):
            return 'sh' + code
        elif code.startswith('0') or code.startswith('3'):
            return 'sz' + code
        return code
    
    def fetch_news(self, stock_code: str, days: int = 3) -> List[NewsItem]:
        """
        获取股票相关新闻
        
        Args:
            stock_code: 股票代码
            days: 获取最近几天的新闻
        
        Returns:
            新闻列表
        """
        news_list = []
        prefix_code = self._get_stock_prefix(stock_code)
        pure_code = prefix_code.replace('sh', '').replace('sz', '')
        
        try:
            # 新浪财经新闻接口
            url = f"https://search.api.sina.com.cn/?c=news&q={pure_code}&page=1&num=20"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if 'result' in data and 'list' in data['result']:
                    for item in data['result']['list']:
                        news = NewsItem(
                            title=item.get('title', ''),
                            url=item.get('url', ''),
                            source=item.get('media', '未知来源'),
                            publish_time=item.get('datetime', ''),
                            summary=item.get('summary', '')[:100] + '...' if len(item.get('summary', '')) > 100 else item.get('summary', '')
                        )
                        # 简单情感分析
                        news.sentiment = self._analyze_sentiment(news.title + news.summary)
                        news_list.append(news)
        except Exception as e:
            print(f"获取新闻失败: {e}")
        
        return news_list[:10]  # 返回最近10条
    
    def fetch_announcements(self, stock_code: str, days: int = 7) -> List[Announcement]:
        """
        获取股票公告
        
        Args:
            stock_code: 股票代码
            days: 获取最近几天的公告
        
        Returns:
            公告列表
        """
        announcements = []
        prefix_code = self._get_stock_prefix(stock_code)
        pure_code = prefix_code.replace('sh', '').replace('sz', '')
        
        try:
            # 东方财富公告接口
            url = f"http://data.eastmoney.com/notices/getdata.ashx?StockCode={pure_code}&CodeType=1&PageIndex=1&PageSize=20"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                # 处理JSONP格式
                text = response.text
                if text.startswith('var data='):
                    text = text[9:]
                if text.endswith(';'):
                    text = text[:-1]
                
                data = json.loads(text)
                if 'data' in data:
                    for item in data['data']:
                        ann = Announcement(
                            title=item.get('NOTICETITLE', ''),
                            type=item.get('ANN_RELCOLUMNSNAME', '其他公告'),
                            publish_date=item.get('NOTICEDATE', '')[:10],
                            content=item.get('NOTICECONTENT', '')[:200] + '...' if len(item.get('NOTICECONTENT', '')) > 200 else item.get('NOTICECONTENT', '')
                        )
                        announcements.append(ann)
        except Exception as e:
            print(f"获取公告失败: {e}")
        
        return announcements[:10]
    
    def _analyze_sentiment(self, text: str) -> str:
        """
        简单情感分析
        
        Args:
            text: 文本内容
        
        Returns:
            情感倾向：正面/负面/中性
        """
        positive_words = ['利好', '增长', '上涨', '突破', '涨停', '业绩大增', '超预期', '收购', '合作', '中标', '订单', '扩张']
        negative_words = ['利空', '下跌', '跌停', '亏损', '下滑', '减持', '解禁', '处罚', '违规', '风险', '暴雷', '退市']
        
        pos_count = sum(1 for word in positive_words if word in text)
        neg_count = sum(1 for word in negative_words if word in text)
        
        if pos_count > neg_count:
            return "正面"
        elif neg_count > pos_count:
            return "负面"
        return "中性"
    
    def check_important_news(self, stock_code: str) -> dict:
        """
        检查重要新闻和公告
        
        Args:
            stock_code: 股票代码
        
        Returns:
            重要信息汇总
        """
        news = self.fetch_news(stock_code, days=1)
        announcements = self.fetch_announcements(stock_code, days=1)
        
        # 筛选重要信息
        important_keywords = ['业绩', '预告', '重组', '收购', '重大合同', '中标', '减持', '增持', '解禁', '分红', '送转']
        
        important_news = []
        for n in news:
            if any(kw in n.title for kw in important_keywords):
                important_news.append(n)
        
        important_ann = []
        for a in announcements:
            if any(kw in a.title for kw in important_keywords) or '重大' in a.type:
                important_ann.append(a)
        
        return {
            'has_important': len(important_news) > 0 or len(important_ann) > 0,
            'important_news': important_news,
            'important_announcements': important_ann,
            'latest_news': news[:3] if news else [],
            'latest_announcements': announcements[:3] if announcements else []
        }
    
    def print_news_report(self, stock_code: str, stock_name: str = ""):
        """
        打印新闻公告报告
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
        """
        name = stock_name or stock_code
        prefix_code = self._get_stock_prefix(stock_code)
        
        print(f"\n{'='*60}")
        print(f"{name}({prefix_code}) 新闻公告监控")
        print(f"{'='*60}")
        
        # 检查重要信息
        important = self.check_important_news(stock_code)
        
        if important['has_important']:
            print("\n🔔 【重要提醒】发现重要新闻/公告！")
            print("-" * 60)
            
            for news in important['important_news']:
                sentiment_emoji = "📈" if news.sentiment == "正面" else "📉" if news.sentiment == "负面" else "📊"
                print(f"{sentiment_emoji} [新闻] {news.title}")
                print(f"   来源：{news.source} | 时间：{news.publish_time}")
                if news.summary:
                    print(f"   摘要：{news.summary}")
                print()
            
            for ann in important['important_announcements']:
                print(f"📋 [公告] {ann.title}")
                print(f"   类型：{ann.type} | 日期：{ann.publish_date}")
                print()
        else:
            print("\n✓ 今日无重要新闻/公告")
        
        # 最新新闻
        print("\n📰 【最新新闻】")
        print("-" * 60)
        news_list = self.fetch_news(stock_code, days=3)
        if news_list:
            for i, news in enumerate(news_list[:5], 1):
                sentiment_emoji = "📈" if news.sentiment == "正面" else "📉" if news.sentiment == "负面" else "📊"
                print(f"{i}. {sentiment_emoji} {news.title}")
                print(f"   {news.source} | {news.publish_time}")
        else:
            print("暂无新闻")
        
        # 最新公告
        print("\n📋 【最新公告】")
        print("-" * 60)
        ann_list = self.fetch_announcements(stock_code, days=7)
        if ann_list:
            for i, ann in enumerate(ann_list[:5], 1):
                print(f"{i}. [{ann.type}] {ann.title}")
                print(f"   日期：{ann.publish_date}")
        else:
            print("暂无公告")
        
        print(f"\n{'='*60}")
        print("免责声明：以上信息仅供参考，不构成投资建议")
        print(f"{'='*60}\n")


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='新闻公告监控')
    parser.add_argument('code', help='股票代码，如600519')
    parser.add_argument('--name', '-n', default='', help='股票名称')
    
    args = parser.parse_args()
    
    monitor = NewsMonitor()
    monitor.print_news_report(args.code, args.name)


if __name__ == '__main__':
    main()
