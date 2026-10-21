#!/usr/bin/env python3
"""
股票筛选器 - 从沪市和深市筛选符合条件的股票
数据源：腾讯财经API
"""

import requests
import json
import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime

def get_kline_data(code: str, days: int = 30) -> List[Dict]:
    """
    获取股票K线数据（日线）
    使用腾讯API
    
    Args:
        code: 股票代码
        days: 获取多少天的数据
    
    Returns:
        K线数据列表
    """
    # 添加市场前缀
    if code.startswith('6'):
        full_code = f"sh{code}"
    else:
        full_code = f"sz{code}"
    
    # 腾讯K线API（前复权）
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full_code},day,,,{days},qfq"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://stockpage.10jqka.com.cn/'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        data = response.json()
        
        klines = []
        
        # 解析腾讯K线数据格式（前复权数据在qfqday字段）
        if 'data' in data and full_code in data['data']:
            stock_data = data['data'][full_code]
            # 使用前复权数据 qfqday
            day_key = 'qfqday' if 'qfqday' in stock_data else 'day'
            if day_key in stock_data:
                for item in stock_data[day_key]:
                    # 腾讯K线API格式: [日期, 收盘价, 开盘价, 最高价, 最低价, 成交量]
                    if len(item) >= 6:
                        klines.append({
                            'date': item[0],
                            'close': float(item[1]),
                            'open': float(item[2]),
                            'high': float(item[3]),
                            'low': float(item[4]),
                            'volume': int(float(item[5]))
                        })
        
        return klines
        
    except Exception as e:
        # 静默失败，返回空列表
        return []


def calculate_ma(klines: List[Dict], days: int) -> Optional[float]:
    """
    计算移动平均线
    
    Args:
        klines: K线数据列表
        days: 计算多少日均线
    
    Returns:
        均线值，数据不足返回None
    """
    if len(klines) < days:
        return None
    
    # 取最近days天的收盘价
    recent_closes = [k['close'] for k in klines[-days:]]
    return sum(recent_closes) / days


def get_stock_data(codes: List[str]) -> Dict:
    """
    从腾讯API获取股票数据
    
    Args:
        codes: 股票代码列表，如 ['600000', '000001']
    
    Returns:
        股票数据字典
    """
    # 构建URL，添加sh/sz前缀
    code_list = []
    for code in codes:
        if code.startswith('6'):
            code_list.append(f"sh{code}")
        else:
            code_list.append(f"sz{code}")
    
    url = f"http://qt.gtimg.cn/q={','.join(code_list)}"
    
    try:
        response = requests.get(url, timeout=10)
        response.encoding = 'gbk'
        
        result = {}
        lines = response.text.strip().split(';')
        
        for line in lines:
            if '=' not in line:
                continue
                
            parts = line.split('=')
            if len(parts) < 2:
                continue
                
            # 解析股票代码
            code_key = parts[0].strip().replace('v_', '').replace('sh', '').replace('sz', '')
            data_str = parts[1].strip().strip('"')
            
            if not data_str:
                continue
                
            fields = data_str.split('~')
            if len(fields) < 45:
                continue
            
            try:
                # 解析关键字段
                # 成交额使用字段[37]（万元），比字段[7]更准确
                amount = float(fields[37]) if len(fields) > 37 and fields[37] else float(fields[7])
                # 涨幅使用字段[32]，字段[5]不是涨幅
                change_pct = float(fields[32]) if len(fields) > 32 and fields[32] else float(fields[5])
                
                result[code_key] = {
                    'code': code_key,
                    'name': fields[1],  # 股票名称
                    'price': float(fields[3]),  # 当前价格
                    'change_pct': change_pct,  # 涨跌幅% - 使用字段[32]
                    'volume': float(fields[6]),  # 成交量（手）
                    'amount': amount,  # 成交额（万）- 使用字段[37]
                    'turnover': float(fields[38]) if fields[38] else 0,  # 换手率%
                    'volume_ratio': float(fields[49]) if len(fields) > 49 and fields[49] else 0,  # 量比
                    'market_cap': float(fields[44]) if len(fields) > 44 and fields[44] else 0,  # 流通市值（亿）
                    'pe': float(fields[39]) if fields[39] else 0,  # 市盈率
                    'pb': float(fields[46]) if fields[46] else 0,  # 市净率
                    'high': float(fields[33]),  # 最高价
                    'low': float(fields[34]),  # 最低价
                    'open': float(fields[4]),  # 开盘价
                    'prev_close': float(fields[2]),  # 昨收
                }
            except (ValueError, IndexError) as e:
                print(f"解析 {code_key} 数据失败: {e}")
                continue
        
        return result
        
    except Exception as e:
        print(f"获取数据失败: {e}")
        return {}


def filter_stocks(stocks_data: Dict, check_ma: bool = True) -> List[Dict]:
    """
    根据条件筛选股票

    市场筛选：
    - 沪市A股：600/601/603/605xxx
    - 深市A股：000/001/002/003xxx
    - 排除：创业板(300xxx)、科创板(688xxx)、B股、新三板

    第一阶段：实时行情筛选（无需K线）
    1. 流通市值：50-200亿
    2. 换手率：5%-10%
    3. 涨幅：2.5%-5%
    4. 量比：1.2-5（腾讯API字段[49]）

    第二阶段：K线技术分析（需调用K线API）
    5. 实时价格 > 5日均线
    6. 实时价格 > 10日均线
    7. 实时价格 > 20日均线
    8. 实时价格 > 今日均价
    9. 均线多头向上发散：MA5 > MA10

    Args:
        stocks_data: 股票数据字典
        check_ma: 是否检查均线条件

    Returns:
        符合条件的股票列表
    """
    filtered = []
    
    for code, data in stocks_data.items():
        try:
            # ========== 市场筛选 ==========
            # 只保留沪市A股(600/601/603/605xxx)和深市A股(000/001/002/003xxx)
            # 排除: 创业板(300xxx)、科创板(688xxx)、B股(200xxx)、新三板(430/830xxx)
            if not (code.startswith(('600', '601', '603', '605', '000', '001', '002', '003'))):
                continue

            # ========== 第一阶段：基础条件（无需K线数据）============

            # 条件1：流通市值 50-200亿
            market_cap = data.get('market_cap', 0)
            if not (50 <= market_cap <= 200):
                continue

            # 条件2：换手率 5%-10%
            turnover = data.get('turnover', 0)
            if not (5 <= turnover <= 10):
                continue

            # 条件3：涨幅 3%-5%
            change_pct = data.get('change_pct', 0)
            if not (3 <= change_pct <= 5):
                continue

            # 条件4：量比 1.2-5（直接使用腾讯API字段[49]，无需K线）
            volume_ratio = data.get('volume_ratio', 0)
            if not (1.2 <= volume_ratio <= 5):
                continue
            
            # ========== 均线条件 ==========
            if check_ma:
                current_price = data['price']
                
                # 条件8：实时价格 > 今日均价（优先检查，不需要历史数据）
                amount = data.get('amount', 0) * 10000  # 万转元
                volume = data.get('volume', 0) * 100  # 手转股
                if volume > 0:
                    avg_price = amount / volume
                    if current_price <= avg_price:
                        continue
                    data['avg_price'] = avg_price
                else:
                    continue

                # 获取今日最低价，用于判断K线是否在均线上方
                today_low = data.get('low', 0)

                # 尝试获取K线数据计算均线
                klines = get_kline_data(code, days=30)

                if len(klines) >= 20:
                    # 条件5：实时价格 > 5日均线
                    ma5 = calculate_ma(klines, 5)
                    if ma5 and current_price <= ma5:
                        continue

                    # 条件6：实时价格 > 10日均线
                    ma10 = calculate_ma(klines, 10)
                    if ma10 and current_price <= ma10:
                        continue

                    # 条件7：实时价格 > 20日均线
                    ma20 = calculate_ma(klines, 20)
                    if ma20 and current_price <= ma20:
                        continue

                    # 条件9：均线多头向上发散：MA5 > MA10
                    if ma5 and ma10:
                        if not (ma5 > ma10):
                            continue

                    # 保存均线数据
                    if ma5: data['ma5'] = ma5
                    if ma10: data['ma10'] = ma10
                    if ma20: data['ma20'] = ma20
                # 如果K线数据获取失败，只检查今日均价条件
            
            # 所有条件满足，加入结果
            filtered.append(data)
            
        except Exception as e:
            continue
    
    # 按涨幅排序
    filtered.sort(key=lambda x: x['change_pct'], reverse=True)
    
    return filtered


def get_all_stock_codes() -> List[str]:
    """
    获取沪深所有股票代码
    从文件加载或使用内置范围
    """
    # 尝试从文件加载
    code_file = '/Users/Jiang/WorkBuddy/Claw/all_stock_codes.txt'
    try:
        with open(code_file, 'r') as f:
            codes = [line.strip() for line in f if line.strip()]
        print(f"从文件加载 {len(codes)} 只股票代码")
        return codes
    except FileNotFoundError:
        print(f"代码文件不存在: {code_file}")
        print("使用内置代码范围...")
    
    # 内置代码范围（备用）
    codes = []
    
    # 沪市主板
    for i in range(600000, 610000):
        codes.append(f"{i:06d}")
    for i in range(601000, 602000):
        codes.append(f"{i:06d}")
    for i in range(603000, 604000):
        codes.append(f"{i:06d}")
    for i in range(605000, 606000):
        codes.append(f"{i:06d}")
    
    # 科创板
    for i in range(688000, 689000):
        codes.append(f"{i:06d}")
    
    # 深市主板
    for i in range(1, 10000):
        codes.append(f"{i:06d}")
    
    # 创业板
    for i in range(300000, 302000):
        codes.append(f"{i}")
    
    return codes


def screen_stocks_batch(codes: List[str], batch_size: int = 100, check_ma: bool = True) -> List[Dict]:
    """
    批量筛选股票
    
    Args:
        codes: 股票代码列表
        batch_size: 每批处理的代码数量
        check_ma: 是否检查均线条件
    
    Returns:
        符合条件的股票列表
    """
    all_filtered = []
    
    # 分批处理
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        print(f"处理第 {i//batch_size + 1} 批，共 {len(batch)} 只股票...")
        
        # 获取数据
        data = get_stock_data(batch)
        
        # 筛选（传入check_ma参数）
        filtered = filter_stocks(data, check_ma=check_ma)
        all_filtered.extend(filtered)
        
        print(f"  本批符合条件: {len(filtered)} 只")
    
    # 最终排序
    all_filtered.sort(key=lambda x: x['change_pct'], reverse=True)
    
    # 去重（根据代码去重，保留第一条）
    seen = set()
    unique_results = []
    for stock in all_filtered:
        if stock['code'] not in seen:
            seen.add(stock['code'])
            unique_results.append(stock)
    
    return unique_results


def format_stock_info(stock: Dict) -> str:
    """格式化股票信息输出"""
    base_info = (
        f"{stock['code']} {stock['name']} | "
        f"价格: {stock['price']:.2f} | "
        f"涨幅: {stock['change_pct']:+.2f}% | "
        f"量比: {stock['volume_ratio']:.2f} | "
        f"换手: {stock['turnover']:.2f}% | "
        f"市值: {stock['market_cap']:.2f}亿"
    )
    
    # 添加均线和均价信息
    extra_info = []
    if 'avg_price' in stock:
        extra_info.append(f"均价: {stock['avg_price']:.2f}")
    if 'ma5' in stock:
        extra_info.append(f"MA5: {stock['ma5']:.2f}")
    if 'ma10' in stock:
        extra_info.append(f"MA10: {stock['ma10']:.2f}")
    if 'ma20' in stock:
        extra_info.append(f"MA20: {stock['ma20']:.2f}")
    
    if extra_info:
        return base_info + "\n      " + " | ".join(extra_info)
    
    return base_info


def is_trading_hours():
    """检查当前是否为A股交易时段（工作日9:30-11:30 / 13:00-15:00）"""
    import datetime
    now = datetime.datetime.now()
    weekday = now.weekday()  # 0=周一, 6=周日
    if weekday >= 5:  # 周六周日
        return False, f"今日({now.strftime('%A')})为非交易日"
    hour, minute = now.hour, now.minute
    t = hour * 60 + minute
    morning = 9 * 60 + 30 <= t <= 11 * 60 + 30  # 9:30-11:30
    afternoon = 13 * 60 <= t <= 15 * 60          # 13:00-15:00
    if not (morning or afternoon):
        if t < 9 * 60 + 30:
            status = f"未到开盘时间（9:30开市），当前{now.strftime('%H:%M')}）"
        elif t <= 11 * 60 + 30:
            status = f"午间休市（11:30-13:00），当前{now.strftime('%H:%M')}）"
        else:
            status = f"已收盘（15:00收市），当前{now.strftime('%H:%M')}）"
        return False, status
    return True, ""


if __name__ == "__main__":
    import argparse

    # 交易时段校验
    in_trading, msg = is_trading_hours()
    if not in_trading:
        print("=" * 80)
        print("⚠️  非交易时段运行提示")
        print("=" * 80)
        print(f"  {msg}")
        print("  午盘选股法依赖实时量比数据，午休时段（11:30-13:00）量比数据可能不完整，")
        print("  建议在以下时段运行以获得最佳结果：")
        print("    早盘：09:35 - 11:30")
        print("    尾盘：14:30 - 15:00（最佳窗口）")
        print("=" * 80)
        print()

    parser = argparse.ArgumentParser(description='股票筛选器')
    parser.add_argument('--limit', type=int, default=500, help='最多处理多少只股票（默认500，全量设为0）')
    args = parser.parse_args()

    print("=" * 80)
    print("股票筛选器")
    print("=" * 80)
    print("第一阶段：市值50-200亿 | 换手5-10% | 涨幅2.5-5% | 量比1.2-5（API字段）")
    print("第二阶段：价格>MA5/MA10/MA20/均价 | MA5>MA10（K线计算）")
    print("=" * 80)

    # 获取所有股票代码
    all_codes = get_all_stock_codes()

    # 限制处理数量
    if args.limit > 0 and len(all_codes) > args.limit:
        print(f"\n限制处理前 {args.limit} 只股票（共 {len(all_codes)} 只）")
        all_codes = all_codes[:args.limit]
    else:
        print(f"\n共加载 {len(all_codes)} 只股票代码")

    # 执行技术筛选
    print()
    results = screen_stocks_batch(all_codes)

    # 输出结果
    print("\n" + "=" * 80)
    print(f"筛选完成！共找到 {len(results)} 只符合条件的股票")
    print("=" * 80)

    if not results:
        print("\n没有找到符合条件的股票")
        exit(0)

    print("\n【筛选结果】\n")
    for i, stock in enumerate(results[:20], 1):
        print(f"{i:2d}. {format_stock_info(stock)}")
    if len(results) > 20:
        print(f"\n... 还有 {len(results) - 20} 只股票未显示")

