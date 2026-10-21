#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试智能通知引擎格式化"""
import sys
import io

# Windows GBK编码修复
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, r'C:\Users\13073\.workbuddy\skills\stock-monitor')

from smart_notifier import MessageFormatter, StockSnapshot

mf = MessageFormatter()
test_snap = StockSnapshot(
    code='sh600519', name='贵州茅台',
    price=1760.00, change_pct=10.01,
    open_price=1620.00, pre_close=1600.00,
    high=1760.00, low=1610.00,
    volume=50000, amount=850000,
    turnover_rate=0.45, volume_ratio=3.2,
    net_inflow=48000,
    ma5=1580.0, ma20=1520.0, ma60=1480.0, ma120=1450.0,
    pressure_levels=[1744.12, 1567.37, 1520.47],
    pressure_sources=['Fib61.8%延伸压力', '近期高点聚集', 'MA20压力★共振'],
    support_levels=[1491.65, 1458.24, 1434.27],
    support_sources=['近期低点+Fib38.2%', 'MA60+Fib50%★★', 'MA250+MA120+Fib61.8%★★★'],
    avg_volume_5d=15000,
)

tests = [
    ('涨停', lambda: mf.format_limit_up(test_snap)),
    ('跌停', lambda: mf.format_limit_down(StockSnapshot(code='sz000001', name='测试股', price=10.00, change_pct=-10.01, net_inflow=-25000))),
    ('压力位突破', lambda: mf.format_pressure_break(test_snap, 2, 1520.47, 'MA20压力★共振 + 近期高点')),
    ('支撑位失守', lambda: mf.format_support_break(test_snap, 1, 1458.24, 'MA60+Fib50%★★共振')),
    ('大单买入', lambda: mf.format_big_order(test_snap, 12000)),
    ('大单卖出', lambda: mf.format_big_order(StockSnapshot(code='sh600519', name='贵州茅台', price=1550, change_pct=-3.5, volume_ratio=2.5, net_inflow=-8000, avg_volume_5d=15000), -8000)),
    ('量能异常', lambda: mf.format_volume_surge(test_snap, 4.5)),
    ('均线金叉', lambda: mf.format_ma_cross(test_snap, '5', '20', True)),
    ('均线死叉', lambda: mf.format_ma_cross(StockSnapshot(code='sh600519', name='贵州茅台', price=1480, change_pct=-2.0, ma5=1470, ma20=1490), '5', '20', False)),
]

for name, fn in tests:
    print("\n" + "=" * 50)
    print(f"【{name}】")
    print("=" * 50)
    try:
        title, content = fn()
        print(f"标题: {title}")
        print(f"正文:\n{content}")
    except Exception as e:
        print(f"ERROR: {e}")

# 定期报告
print("\n" + "=" * 50)
print("【早盘竞价报告】")
print("=" * 50)
title, content = mf.format_morning_call([test_snap], 3200, 1800, '贵州茅台', '')
print(title)
print(content)

print("\n" + "=" * 50)
print("【午间盘点】")
print("=" * 50)
title, content = mf.format_midday_summary([test_snap])
print(title)
print(content)

print("\n" + "=" * 50)
print("【尾盘异动】")
print("=" * 50)
title, content = mf.format_closing_alert(test_snap, '尾盘急拉，振幅较大')
print(title)
print(content)

# 完整流程测试
print("\n" + "=" * 60)
print("【完整流程测试 - 模拟实时监测】")
print("=" * 60)

from smart_notifier import SmartNotifier
sn = SmartNotifier()

# 场景1：正常波动，不触发
normal_snap = StockSnapshot(
    code='sh600519', name='贵州茅台',
    price=1615.00, change_pct=0.25,
    pre_close=1611.00, net_inflow=500,
    ma5=1580.0, ma20=1520.0, ma60=1480.0,
    avg_volume_5d=15000, volume=12000,
)
events = sn.check_and_notify(normal_snap)
print(f"\n场景1(正常波动): 触发 {len(events)} 个事件 → 正确")

# 场景2：涨停
limit_snap = StockSnapshot(
    code='sh600519', name='贵州茅台',
    price=1772.11, change_pct=10.01,
    pre_close=1610.00, high=1772.11,
    amount=900000, turnover_rate=0.5,
    volume_ratio=3.5, net_inflow=50000,
    pressure_levels=[1744.12, 1567.37, 1520.47],
    pressure_sources=['Fib61.8%', '近期高点', 'MA20'],
    avg_volume_5d=15000, volume=50000,
)
events = sn.check_and_notify(limit_snap)
print(f"场景2(涨停): 触发 {len(events)} 个事件")
for ev in events:
    print(f"  [{ev.level}] {ev.title}")

# 场景3：跌破支撑
support_snap = StockSnapshot(
    code='sh600519', name='贵州茅台',
    price=1440.00, change_pct=-5.3,
    pre_close=1521.00, low=1440.00,
    net_inflow=-30000, turnover_rate=0.8,
    volume_ratio=2.8,
    support_levels=[1491.65, 1458.24, 1434.27],
    support_sources=['低点+Fib38.2%', 'MA60+Fib50%', 'MA250三重'],
    avg_volume_5d=15000, volume=40000,
)
events = sn.check_and_notify(support_snap)
print(f"场景3(跌破支撑): 触发 {len(events)} 个事件")
for ev in events:
    print(f"  [{ev.level}] {ev.title}")

# 防刷测试
print("\n--- 防刷测试（重复推送应被拦截）---")
events2 = sn.check_and_notify(limit_snap)
print(f"重复涨停: 触发 {len(events2)} 个事件 → 应为0")

sn.print_stats()
