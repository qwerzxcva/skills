#!/usr/bin/env python3
"""
股票查询模块 - 单股/大盘/批量查询
"""

import sys
import argparse
from data_source import MultiDataSource


def query_single_stock(code: str, name: str = None):
    """查询单只股票行情"""
    source = MultiDataSource()
    
    # 自动补全代码前缀
    if not code.startswith(('sh', 'sz')):
        if code.startswith('6'):
            code = 'sh' + code
        else:
            code = 'sz' + code
    
    result = source.fetch_tencent([code])
    
    if code in result:
        d = result[code]
        arrow = '▲' if d.change_pct > 0 else '▼' if d.change_pct < 0 else '→'
        
        print(f"\n{'='*50}")
        print(f"股票名称: {d.name}")
        print(f"股票代码: {d.code}")
        print(f"{'='*50}")
        print(f"当前价格: {d.price:.2f} 元")
        print(f"涨跌额: {d.change:+.2f} 元")
        print(f"涨跌幅: {arrow} {d.change_pct:+.2f}%")
        print(f"今日开盘: {d.open:.2f} 元")
        print(f"今日最高: {d.high:.2f} 元")
        print(f"今日最低: {d.low:.2f} 元")
        print(f"昨日收盘: {d.pre_close:.2f} 元")
        print(f"成交量: {d.volume:,} 手")
        print(f"成交额: {d.amount/10000:.2f} 万元")
        print(f"{'='*50}")
        print(f"数据来源: {d.source}")
        print(f"数据时间: {d.timestamp}")
        print(f"{'='*50}\n")
        return True
    else:
        print(f"❌ 未获取到股票 {code} 的数据")
        return False


def query_market_indices():
    """查询大盘指数"""
    source = MultiDataSource()
    indices = ['sh000001', 'sz399001', 'sz399006', 'sh000688']
    results = source.fetch_tencent(indices)
    
    print(f"\n{'='*60}")
    print(f"今日大盘行情 ({results.get('sh000001', type('obj', (object,), {'timestamp': 'N/A'})()).timestamp[:8] if 'sh000001' in results else 'N/A'})")
    print(f"{'='*60}")
    print(f"{'指数名称':<12} {'当前点位':>10} {'涨跌幅':>10} {'涨跌额':>10}")
    print(f"{'-'*60}")
    
    for code in indices:
        if code in results:
            d = results[code]
            arrow = '▲' if d.change_pct > 0 else '▼' if d.change_pct < 0 else '→'
            print(f"{d.name:<12} {d.price:>10.2f} {arrow}{d.change_pct:>+9.2f}% {d.change:>+10.2f}")
    
    print(f"{'='*60}\n")
    return True


def query_batch_stocks(stock_list: list):
    """批量查询多只股票"""
    source = MultiDataSource()
    
    # 处理代码格式
    codes = []
    for item in stock_list:
        code = item.strip()
        if not code.startswith(('sh', 'sz')):
            if code.startswith('6'):
                code = 'sh' + code
            else:
                code = 'sz' + code
        codes.append(code)
    
    results = source.fetch_tencent(codes)
    
    print(f"\n{'='*80}")
    print(f"股票批量查询结果")
    print(f"{'='*80}")
    print(f"{'股票名称':<10} {'代码':<10} {'价格':>8} {'涨跌幅':>10} {'涨跌额':>10} {'成交量':>12}")
    print(f"{'-'*80}")
    
    for code in codes:
        if code in results:
            d = results[code]
            arrow = '▲' if d.change_pct > 0 else '▼' if d.change_pct < 0 else '→'
            print(f"{d.name:<10} {d.code:<10} {d.price:>8.2f} {arrow}{d.change_pct:>+9.2f}% {d.change:>+10.2f} {d.volume:>12,}")
        else:
            print(f"{'N/A':<10} {code:<10} {'--':>8} {'--':>10} {'--':>10} {'--':>12}")
    
    print(f"{'='*80}\n")
    return True


def main():
    parser = argparse.ArgumentParser(description='股票查询工具')
    parser.add_argument('--single', '-s', help='查询单只股票，如：600519 或 sh600519')
    parser.add_argument('--market', '-m', action='store_true', help='查询大盘指数')
    parser.add_argument('--batch', '-b', help='批量查询，逗号分隔，如：600519,000001,300061')
    
    args = parser.parse_args()
    
    if args.single:
        query_single_stock(args.single)
    elif args.market:
        query_market_indices()
    elif args.batch:
        stocks = args.batch.split(',')
        query_batch_stocks(stocks)
    else:
        # 默认查询大盘
        query_market_indices()


if __name__ == '__main__':
    main()
