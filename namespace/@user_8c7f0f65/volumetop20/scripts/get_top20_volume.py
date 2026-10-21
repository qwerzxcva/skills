# -*- coding: utf-8 -*-
"""
成交额TOP20数据获取脚本
用于获取同花顺问财成交额排名前20的股票数据
"""

import json
import os
import datetime
import sys

# 数据保存路径
DATA_DIR = r'C:\Users\10590\.qclaw\workspace\data\volume_monitor'
REPORT_DIR = r'C:\Users\10590\.qclaw\workspace'

def save_json(data, filename=None):
    """保存数据到JSON文件"""
    if filename is None:
        date_str = datetime.datetime.now().strftime('%Y%m%d')
        filename = f'baseline_top20_{date_str}.json'
    
    filepath = os.path.join(DATA_DIR, filename)
    os.makedirs(DATA_DIR, exist_ok=True)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"✅ 数据已保存: {filepath}")
    return filepath

def save_report(markdown_content, filename=None):
    """保存报告到Markdown文件"""
    if filename is None:
        date_str = datetime.datetime.now().strftime('%Y%m%d')
        filename = f'成交额TOP20分析报告_{date_str}.md'
    
    filepath = os.path.join(REPORT_DIR, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(markdown_content)
    
    print(f"✅ 报告已保存: {filepath}")
    return filepath

def generate_markdown(data):
    """生成Markdown格式报告"""
    stocks = data.get('stocks', [])
    date_str = data.get('data_date', datetime.datetime.now().strftime('%Y-%m-%d'))
    
    # 计算板块统计
    industry_stats = {}
    for stock in stocks:
        industry = stock.get('industry', '其他').split('-')[0]  # 取一级行业
        if industry not in industry_stats:
            industry_stats[industry] = {
                'count': 0,
                'volume': 0,
                'change_sum': 0,
                'stocks': []
            }
        
        # 解析成交额
        volume_str = stock.get('volume', '0')
        try:
            volume = float(volume_str.replace('亿', '').replace(',', ''))
        except:
            volume = 0
        
        # 解析涨跌幅
        change_str = stock.get('change_pct', '0')
        try:
            change = float(change_str.replace('%', '').replace('+', ''))
        except:
            change = 0
        
        industry_stats[industry]['count'] += 1
        industry_stats[industry]['volume'] += volume
        industry_stats[industry]['change_sum'] += change
        industry_stats[industry]['stocks'].append(stock.get('name', ''))
    
    # 按成交额排序
    sorted_industries = sorted(industry_stats.items(), key=lambda x: x[1]['volume'], reverse=True)
    
    # 构建Markdown
    md = f"""# 📊 成交额TOP20分析报告

**数据日期**: {date_str}
**生成时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}

---

## 一、成交额TOP20排名

| 排名 | 名称 | 涨跌幅 | 成交额 | 同花顺行业 | 现价 | 代码 |
|---|---|---|---|---|---|---|
"""
    
    for i, stock in enumerate(stocks[:20], 1):
        name = stock.get('name', '')
        change = stock.get('change_pct', '0')
        volume = stock.get('volume', '0')
        industry = stock.get('industry', '')
        price = stock.get('price', '')
        code = stock.get('code', '')
        
        md += f"| {i} | {name} | {change} | {volume} | {industry} | {price} | {code} |\n"
    
    md += """
---

## 二、板块分布统计

| 板块 | 数量 | 占比 | 成交额 | 均涨幅 | 代表股票 |
|---|---|---|---|---|---|
"""
    
    total_volume = sum(s['volume'] for s in industry_stats.values())
    
    for industry, stats in sorted_industries:
        count = stats['count']
        pct = round(count / 20 * 100, 0)
        vol = round(stats['volume'], 2)
        avg_change = round(stats['change_sum'] / count, 2) if count > 0 else 0
        stocks_str = '/'.join(stats['stocks'][:5])  # 最多显示5只
        
        md += f"| {industry} | {count}只 | {int(pct)}% | {vol}亿 | {avg_change}% | {stocks_str} |\n"
    
    md += """
---

## 三、板块分析

| 板块 | 评级 | 逻辑 | 风险提示 |
|---|---|---|---|
"""
    
    # 自动生成板块分析
    for industry, stats in sorted_industries[:7]:
        avg_change = stats['change_sum'] / stats['count'] if stats['count'] > 0 else 0
        count = stats['count']
        vol = stats['volume']
        
        # 简单评级逻辑
        if avg_change >= 5:
            rating = "⭐⭐⭐⭐"
            logic = "板块强势上涨，资金积极介入"
            risk = "注意追高风险，可能面临回调"
        elif avg_change >= 2:
            rating = "⭐⭐⭐⭐"
            logic = "资金持续流入，板块表现良好"
            risk = "关注持续性，防范轮动"
        elif avg_change >= 0:
            rating = "⭐⭐⭐"
            logic = "稳中有升，震荡为主"
            risk = "等待方向确认"
        elif avg_change >= -2:
            rating = "⭐⭐"
            logic = "小幅调整，观望为主"
            risk = "谨慎入场"
        else:
            rating = "⭐"
            logic = "板块走弱，注意规避"
            risk = "资金持续流出"
        
        md += f"| {industry} | {rating} | {logic} | {risk} |\n"
    
    md += f"""
---

## 四、核心结论

**数据统计**：
- 总成交额: {total_volume:.2f}亿
- 覆盖行业: {len(industry_stats)}个
- 统计股票: {len(stocks)}只

**分析师**: qclaw小助手 🤖
**数据来源**: 同花顺问财
"""
    
    return md

def update_baseline(stocks_data):
    """更新基准数据文件"""
    date_str = datetime.datetime.now().strftime('%Y%m%d')
    
    data = {
        "update_time": datetime.datetime.now().isoformat(),
        "data_date": datetime.datetime.now().strftime('%Y-%m-%d'),
        "query": "成交额从大到小排序前20",
        "stocks": stocks_data
    }
    
    filepath = save_json(data)
    
    # 生成并保存Markdown报告
    md = generate_markdown(data)
    report_path = save_report(md)
    
    return filepath, report_path

if __name__ == '__main__':
    print("=" * 50)
    print("成交额TOP20数据获取脚本")
    print("=" * 50)
    print()
    print("请使用浏览器自动化方式获取数据：")
    print("1. 访问 https://www.iwencai.com")
    print("2. 输入查询：成交额从大到小排序前20，涨跌幅，成交额，同花顺行业，现价，代码")
    print("3. 获取数据后，调用 update_baseline() 函数保存")
    print()
    print("示例：")
    print("  from get_top20_volume import update_baseline")
    print("  update_baseline([{'rank': 1, 'code': '300502', ...}, ...])")
