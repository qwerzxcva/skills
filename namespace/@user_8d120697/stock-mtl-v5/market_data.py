#!/usr/bin/env python3
"""
市场数据模块 - 板块、涨跌停榜、龙虎榜
"""

import requests
import json
import re
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class PlateData:
    """板块数据"""
    name: str
    code: str
    change_pct: float
    leading_stock: str
    leading_change: float


@dataclass
class LimitUpData:
    """涨停股数据"""
    name: str
    code: str
    price: float
    change_pct: float
    turnover: float  # 换手率
    amount: float    # 成交额（万）
    days: int        # 连板天数


def fetch_plate_data():
    """获取板块涨跌数据（东方财富）"""
    try:
        url = "http://push2ex.eastmoney.com/getTopicZSCX"
        params = {
            'ut': '7eea3edcaed734bea9cbfc24409ed989',
            'dpt': 'wz.zscx',
            'Pageindex': '0',
            'pagesize': '20',
            'sort': 'zdf',
            'sorttype': 'DESC'
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        plates = []
        if 'data' in data and 'data' in data['data']:
            for item in data['data']['data'][:10]:
                plates.append(PlateData(
                    name=item.get('f14', 'N/A'),
                    code=item.get('f12', 'N/A'),
                    change_pct=float(item.get('f3', 0)),
                    leading_stock=item.get('f128', 'N/A'),
                    leading_change=float(item.get('f136', 0))
                ))
        return plates
    except Exception as e:
        print(f"获取板块数据失败: {e}")
        return []


def fetch_limit_up_list():
    """获取涨停榜（新浪）"""
    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        # 使用腾讯数据源获取涨跌幅排序
        url = "http://qt.gtimg.cn/q=sh000001,sz399001"
        
        # 改用东方财富涨停数据
        url = "http://push2ex.eastmoney.com/getTopicZSCX"
        params = {
            'ut': '7eea3edcaed734bea9cbfc24409ed989',
            'dpt': 'wz.zscx',
            'Pageindex': '0',
            'pagesize': '100',
            'sort': 'zdf',
            'sorttype': 'DESC'
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        limit_up_stocks = []
        if 'data' in data and 'data' in data['data']:
            for item in data['data']['data']:
                change_pct = float(item.get('f3', 0))
                if change_pct >= 9.5:  # 接近涨停
                    limit_up_stocks.append({
                        'name': item.get('f14', 'N/A'),
                        'code': item.get('f12', 'N/A'),
                        'change_pct': change_pct,
                        'price': float(item.get('f2', 0)),
                        'turnover': float(item.get('f8', 0)),
                        'amount': float(item.get('f6', 0)) / 10000
                    })
        return limit_up_stocks[:20]  # 返回前20只
    except Exception as e:
        print(f"获取涨停榜失败: {e}")
        return []


def fetch_limit_down_list():
    """获取跌停榜"""
    try:
        url = "http://push2ex.eastmoney.com/getTopicZSCX"
        params = {
            'ut': '7eea3edcaed734bea9cbfc24409ed989',
            'dpt': 'wz.zscx',
            'Pageindex': '0',
            'pagesize': '100',
            'sort': 'zdf',
            'sorttype': 'ASC'  # 升序，跌幅最大在前
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        limit_down_stocks = []
        if 'data' in data and 'data' in data['data']:
            for item in data['data']['data']:
                change_pct = float(item.get('f3', 0))
                if change_pct <= -9.5:  # 接近跌停
                    limit_down_stocks.append({
                        'name': item.get('f14', 'N/A'),
                        'code': item.get('f12', 'N/A'),
                        'change_pct': change_pct,
                        'price': float(item.get('f2', 0)),
                        'turnover': float(item.get('f8', 0)),
                        'amount': float(item.get('f6', 0)) / 10000
                    })
        return limit_down_stocks[:10]
    except Exception as e:
        print(f"获取跌停榜失败: {e}")
        return []


def print_plate_data():
    """打印板块数据"""
    plates = fetch_plate_data()
    
    if not plates:
        print("获取板块数据失败")
        return
    
    print(f"\n{'='*70}")
    print(f"板块涨幅 TOP10")
    print(f"{'='*70}")
    print(f"{'板块名称':<15} {'涨跌幅':>10} {'龙头股':<12} {'龙头涨幅':>10}")
    print(f"{'-'*70}")
    
    for p in plates[:10]:
        arrow = '▲' if p.change_pct > 0 else '▼'
        print(f"{p.name:<15} {arrow}{p.change_pct:>+9.2f}% {p.leading_stock:<12} {p.leading_change:>+10.2f}%")
    
    print(f"{'='*70}\n")


def print_limit_up_list():
    """打印涨停榜"""
    stocks = fetch_limit_up_list()
    
    if not stocks:
        print("获取涨停榜失败")
        return
    
    print(f"\n{'='*80}")
    print(f"涨停榜 TOP20")
    print(f"{'='*80}")
    print(f"{'股票名称':<10} {'代码':<10} {'价格':>8} {'涨幅':>10} {'换手率':>10} {'成交额(万)':>12}")
    print(f"{'-'*80}")
    
    for s in stocks[:20]:
        print(f"{s['name']:<10} {s['code']:<10} {s['price']:>8.2f} {s['change_pct']:>+9.2f}% {s['turnover']:>9.2f}% {s['amount']:>12.0f}")
    
    print(f"{'='*80}\n")


def print_limit_down_list():
    """打印跌停榜"""
    stocks = fetch_limit_down_list()
    
    if not stocks:
        print("获取跌停榜失败")
        return
    
    print(f"\n{'='*80}")
    print(f"跌停榜")
    print(f"{'='*80}")
    print(f"{'股票名称':<10} {'代码':<10} {'价格':>8} {'跌幅':>10} {'换手率':>10} {'成交额(万)':>12}")
    print(f"{'-'*80}")
    
    for s in stocks:
        print(f"{s['name']:<10} {s['code']:<10} {s['price']:>8.2f} {s['change_pct']:>+9.2f}% {s['turnover']:>9.2f}% {s['amount']:>12.0f}")
    
    print(f"{'='*80}\n")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == 'plate':
            print_plate_data()
        elif sys.argv[1] == 'up':
            print_limit_up_list()
        elif sys.argv[1] == 'down':
            print_limit_down_list()
        else:
            print("用法: python market_data.py [plate|up|down]")
    else:
        # 默认显示全部
        print_plate_data()
        print_limit_up_list()
