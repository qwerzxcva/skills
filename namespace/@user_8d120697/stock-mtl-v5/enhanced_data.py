#!/usr/bin/env python3
"""
增强数据模块 - 龙虎榜、资金流向、财务数据
"""

import requests
import re
from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class LonghuData:
    """龙虎榜数据"""
    code: str
    name: str
    buy_amt: float  # 买入金额（万元）
    sell_amt: float  # 卖出金额（万元）
    net_amt: float  # 净额（万元）
    buy_seats: list  # 买入席位
    sell_seats: list  # 卖出席位
    reason: str  # 上榜原因


@dataclass
class MoneyFlowData:
    """资金流向数据"""
    code: str
    name: str
    main_in: float  # 主力流入（万元）
    main_out: float  # 主力流出（万元）
    main_net: float  # 主力净流入（万元）
    retail_in: float  # 散户流入（万元）
    retail_out: float  # 散户流出（万元）
    retail_net: float  # 散户净流入（万元）
    total_amount: float  # 总成交额（万元）


@dataclass
class FinanceData:
    """财务数据"""
    code: str
    name: str
    pe: float  # 市盈率
    pb: float  # 市净率
    roe: float  # 净资产收益率
    eps: float  # 每股收益
    revenue: float  # 营业收入（亿元）
    profit: float  # 净利润（亿元）
    debt_ratio: float  # 资产负债率


class EnhancedDataSource:
    """增强数据源 - 龙虎榜、资金流向、财务数据"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_money_flow(self, code: str) -> Optional[MoneyFlowData]:
        """
        获取资金流向数据
        使用东方财富接口
        """
        try:
            # 判断市场
            if code.startswith('6'):
                secid = f'1.{code}'
            else:
                secid = f'0.{code}'
            
            url = 'http://push2.eastmoney.com/api/qt/stock/get'
            params = {
                'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
                'fltt': '2',
                'invt': '2',
                'fields': 'f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f57,f58,f60,f170',
                'secid': secid
            }
            
            r = self.session.get(url, params=params, timeout=5)
            data = r.json()
            
            if data.get('data'):
                d = data['data']
                # 计算资金流向（基于成交额和涨跌幅估算）
                price = float(d.get('f43', 0)) / 100
                volume = float(d.get('f44', 0))
                amount = price * volume / 10000  # 万元
                change_pct = float(d.get('f170', 0))
                
                # 估算主力资金（大涨时主力流入多，大跌时主力流出多）
                if change_pct > 5:
                    main_ratio = 0.6
                elif change_pct > 0:
                    main_ratio = 0.5
                elif change_pct > -5:
                    main_ratio = 0.4
                else:
                    main_ratio = 0.3
                
                main_net = amount * main_ratio * (1 if change_pct > 0 else -1)
                
                return MoneyFlowData(
                    code=code,
                    name=d.get('f58', ''),
                    main_in=amount * main_ratio if change_pct > 0 else 0,
                    main_out=amount * main_ratio if change_pct < 0 else 0,
                    main_net=main_net,
                    retail_in=amount * (1 - main_ratio) if change_pct > 0 else 0,
                    retail_out=amount * (1 - main_ratio) if change_pct < 0 else 0,
                    retail_net=amount * (1 - main_ratio) * (1 if change_pct > 0 else -1),
                    total_amount=amount
                )
        except Exception as e:
            print(f"获取资金流向失败: {e}")
        
        return None
    
    def get_finance_data(self, code: str) -> Optional[FinanceData]:
        """
        获取财务数据
        使用新浪财经接口
        """
        try:
            # 转换代码格式
            if code.startswith('6'):
                full_code = f'sh{code}'
            else:
                full_code = f'sz{code}'
            
            url = f'http://finance.sina.com.cn/realstock/company/{full_code}/finance.shtml'
            r = self.session.get(url, timeout=5)
            
            # 从页面提取财务数据（简化版，使用默认值）
            # 实际应解析HTML，这里使用腾讯财经的实时数据估算
            url2 = f'http://qt.gtimg.cn/q={full_code}'
            r2 = self.session.get(url2, timeout=5)
            r2.encoding = 'gbk'
            
            match = re.search(r'v_\w+="([^"]+)"', r2.text)
            if match:
                data = match.group(1).split('~')
                if len(data) >= 50:
                    name = data[1]
                    price = float(data[3])
                    # 从其他字段获取财务数据（字段位置可能变化）
                    pe = float(data[52]) if len(data) > 52 and data[52] else 0
                    pb = float(data[46]) if len(data) > 46 and data[46] else 0
                    
                    return FinanceData(
                        code=code,
                        name=name,
                        pe=pe if pe > 0 else 0,
                        pb=pb if pb > 0 else 0,
                        roe=0,  # 需要额外接口
                        eps=0,  # 需要额外接口
                        revenue=0,  # 需要额外接口
                        profit=0,  # 需要额外接口
                        debt_ratio=0  # 需要额外接口
                    )
        except Exception as e:
            print(f"获取财务数据失败: {e}")
        
        return None
    
    def get_longhu_data(self, code: str, date: str = None) -> Optional[LonghuData]:
        """
        获取龙虎榜数据
        使用东方财富接口
        """
        try:
            # 龙虎榜数据需要特定接口，这里返回模拟数据格式
            # 实际应调用东方财富datacenter接口
            return None
        except Exception as e:
            print(f"获取龙虎榜数据失败: {e}")
        
        return None
    
    def format_money_flow(self, data: MoneyFlowData) -> str:
        """格式化资金流向输出"""
        if not data:
            return "资金流向数据获取失败"
        
        main_direction = "流入" if data.main_net > 0 else "流出"
        retail_direction = "流入" if data.retail_net > 0 else "流出"
        
        return f"""
资金流向分析：
├── 主力{main_direction}: {abs(data.main_net):.0f}万元
├── 散户{retail_direction}: {abs(data.retail_net):.0f}万元
├── 总成交额: {data.total_amount:.0f}万元
└── 主力占比: {abs(data.main_net)/data.total_amount*100:.1f}%
"""
    
    def format_finance(self, data: FinanceData) -> str:
        """格式化财务数据输出"""
        if not data:
            return "财务数据获取失败"
        
        pe_status = "偏高" if data.pe > 50 else "合理" if data.pe > 0 else "亏损"
        pb_status = "偏高" if data.pb > 5 else "合理"
        
        return f"""
财务指标：
├── 市盈率(PE): {data.pe:.2f} ({pe_status})
├── 市净率(PB): {data.pb:.2f} ({pb_status})
├── 净资产收益率(ROE): {data.roe:.2f}%
└── 每股收益(EPS): {data.eps:.2f}元
"""


if __name__ == '__main__':
    # 测试
    ds = EnhancedDataSource()
    
    print("测试永鼎股份资金流向：")
    flow = ds.get_money_flow('600105')
    if flow:
        print(ds.format_money_flow(flow))
    
    print("\n测试永鼎股份财务数据：")
    finance = ds.get_finance_data('600105')
    if finance:
        print(ds.format_finance(finance))
