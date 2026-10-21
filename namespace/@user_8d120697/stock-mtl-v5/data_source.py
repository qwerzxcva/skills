#!/usr/bin/env python3
"""
多数据源管理模块
支持: 腾讯财经、东方财富、新浪财经
"""

import requests
import re
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed


@dataclass
class StockData:
    """股票数据对象"""
    code: str
    name: str
    price: float
    pre_close: float
    open: float
    high: float
    low: float
    change: float
    change_pct: float
    volume: int
    amount: float
    source: str
    timestamp: str
    
    @property
    def is_up(self) -> bool:
        return self.change_pct > 0
    
    @property
    def is_down(self) -> bool:
        return self.change_pct < 0


class MultiDataSource:
    """多数据源管理器"""
    
    def __init__(self):
        self.sources = {
            'tencent': self.fetch_tencent,
            'eastmoney': self.fetch_eastmoney,
            'sina': self.fetch_sina
        }
    
    def fetch_tencent(self, codes: List[str]) -> Dict[str, StockData]:
        """腾讯财经 - 秒级刷新"""
        try:
            url = f"http://qt.gtimg.cn/q={','.join(codes)}"
            r = requests.get(url, timeout=5)
            r.encoding = 'gbk'
            
            results = {}
            for line in r.text.strip().split(';'):
                if not line.strip():
                    continue
                match = re.search(r'v_(\w+)="([^"]+)"', line)
                if match:
                    code, data = match.groups()
                    parts = data.split('~')
                    if len(parts) >= 45:
                        pre_close = float(parts[4])
                        price = float(parts[3])
                        results[code] = StockData(
                            code=code,
                            name=parts[1],
                            price=price,
                            pre_close=pre_close,
                            open=float(parts[5]),
                            high=float(parts[33]),
                            low=float(parts[34]),
                            change=round(price - pre_close, 2),
                            change_pct=float(parts[32]),
                            volume=int(parts[36]),
                            amount=float(parts[37]),
                            source='腾讯',
                            timestamp=parts[30]
                        )
            return results
        except Exception as e:
            return {}
    
    def fetch_eastmoney(self, codes: List[str]) -> Dict[str, StockData]:
        """东方财富"""
        results = {}
        for code in codes[:1]:
            try:
                if code.startswith('sh'):
                    secid = f"1.{code[2:]}"
                else:
                    secid = f"0.{code[2:]}"
                
                url = "http://push2.eastmoney.com/api/qt/stock/get"
                params = {
                    'secid': secid,
                    'fields': 'f43,f44,f45,f46,f47,f48,f57,f58,f60,f170'
                }
                r = requests.get(url, params=params, timeout=5)
                data = r.json()
                
                if data.get('data'):
                    d = data['data']
                    pre_close = d.get('f60', 0) / 100
                    price = d.get('f43', 0) / 100
                    results[code] = StockData(
                        code=code,
                        name=d.get('f58'),
                        price=price,
                        pre_close=pre_close,
                        open=d.get('f46', 0) / 100,
                        high=d.get('f44', 0) / 100,
                        low=d.get('f45', 0) / 100,
                        change=round(price - pre_close, 2),
                        change_pct=d.get('f170', 0) / 100,
                        volume=d.get('f47', 0),
                        amount=d.get('f48', 0),
                        source='东财',
                        timestamp=datetime.now().strftime('%H:%M:%S')
                    )
            except:
                pass
        return results
    
    def fetch_sina(self, codes: List[str]) -> Dict[str, StockData]:
        """新浪财经"""
        try:
            headers = {'Referer': 'https://finance.sina.com.cn'}
            url = f"http://hq.sinajs.cn/list={','.join(codes)}"
            r = requests.get(url, headers=headers, timeout=5)
            r.encoding = 'gbk'
            
            results = {}
            for line in r.text.strip().split('\n'):
                match = re.search(r'var hq_str_(\w+)="([^"]*)"', line)
                if match and match.group(2):
                    code, data = match.groups()
                    parts = data.split(',')
                    if len(parts) >= 8:
                        pre_close = float(parts[2]) if parts[2] else 0
                        price = float(parts[3]) if parts[3] else 0
                        results[code] = StockData(
                            code=code,
                            name=parts[0],
                            price=price,
                            pre_close=pre_close,
                            open=float(parts[1]) if parts[1] else 0,
                            high=float(parts[4]) if parts[4] else 0,
                            low=float(parts[5]) if parts[5] else 0,
                            change=round(price - pre_close, 2),
                            change_pct=round((price - pre_close) / pre_close * 100, 2) if pre_close > 0 else 0,
                            volume=int(parts[8]) if parts[8] else 0,
                            amount=0,
                            source='新浪',
                            timestamp=parts[31] if len(parts) > 31 else datetime.now().strftime('%H:%M:%S')
                        )
            return results
        except:
            return {}
    
    def fetch_all(self, codes: List[str]) -> Dict[str, List[StockData]]:
        """并发获取所有数据源"""
        all_data = {}
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self.fetch_tencent, codes): 'tencent',
                executor.submit(self.fetch_eastmoney, codes): 'eastmoney',
                executor.submit(self.fetch_sina, codes): 'sina'
            }
            
            for future in as_completed(futures):
                try:
                    data = future.result()
                    for code, stock in data.items():
                        if code not in all_data:
                            all_data[code] = []
                        all_data[code].append(stock)
                except:
                    pass
        
        return all_data
    
    def cross_verify(self, all_data: Dict[str, List[StockData]]) -> Dict[str, StockData]:
        """交叉验证，返回最可靠的数据"""
        verified = {}
        
        for code, sources in all_data.items():
            if len(sources) == 0:
                continue
            
            if len(sources) == 1:
                verified[code] = sources[0]
                continue
            
            # 多数据源取中位数
            prices = sorted([s.price for s in sources])
            median_price = prices[len(prices) // 2]
            closest = min(sources, key=lambda s: abs(s.price - median_price))
            
            verified[code] = closest
        
        return verified
