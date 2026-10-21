---
name: 尾盘选股法
description: 尾盘选股法。从沪市和深市筛选符合条件的股票。当用户需要筛选股票、寻找投资机会、或根据技术指标选股时，应使用此技能。支持量比、流通市值、换手率、涨幅、均线多头排列、成交量台阶式上升等10维度筛选（两阶段架构）。
allowed-tools: 
disable: false
---

# 尾盘选股法

从沪深股市筛选符合特定条件的股票。采用两阶段筛选架构，效率与精确度兼顾。

## 使用场景

- 寻找短期交易机会
- 根据技术指标筛选股票
- 盘前/盘中选股
- 筛选活跃股票

## 筛选条件（两阶段，共9项）

### 市场筛选
- **沪市A股**：600/601/603/605xxx
- **深市A股**：000/001/002/003xxx
- **排除**：创业板(300xxx)、科创板(688xxx)、B股、新三板

### 第一阶段：实时行情筛选（4项，无需K线，速度快）
| # | 条件 | 标准 | 数据来源 |
|---|------|------|---------|
| 1 | 流通市值 | 50-200亿（中等市值，流动性好） | 腾讯API字段[44] |
| 2 | 换手率 | 5%-10%（交易活跃但非过度炒作） | 腾讯API字段[38] |
| 3 | 涨幅 | 3%-5%（有较强上涨动能，过滤弱势股） | 腾讯API字段[32] |
| 4 | 量比 | 1.2-5（成交量放大但非过度放量） | 腾讯API字段[49] |

### 第二阶段：K线技术分析（6项，需调用K线API）
| # | 条件 | 标准 | 数据来源 |
|---|------|------|---------|
| 5 | 价格 > MA5 | 实时价格站稳5日均线 | 从K线前复权数据自算 |
| 6 | 价格 > MA10 | 实时价格站稳10日均线 | 从K线前复权数据自算 |
| 7 | 价格 > MA20 | 实时价格站稳20日均线 | 从K线前复权数据自算 |
| 8 | 价格 > 今日均价 | 实时价格 > 成交额/成交量 | 腾讯API字段[37][6] |
| 9 | 均线多头排列 | MA5 > MA10（短期均线向上发散） | 从K线前复权数据自算 |
| 10 | 成交量台阶式上升 | 近3日均量 > 前3日均量 × 1.2 | 从K线前复权数据自算 |

## 使用方法

### 1. 运行筛选脚本

**运行筛选：**
```bash
python3 ~/.workbuddy/skills/stock-screener/scripts/screen_stocks.py
```

**限制处理数量（快速测试）：**
```bash
python3 ~/.workbuddy/skills/stock-screener/scripts/screen_stocks.py --limit 500
```

### 2. 在代码中调用

```python
import sys
sys.path.insert(0, '~/.workbuddy/skills/stock-screener/scripts')
from screen_stocks import screen_stocks_batch, get_all_stock_codes

# 获取股票代码列表
codes = get_all_stock_codes()

# 执行筛选
results = screen_stocks_batch(codes)

# 处理结果
for stock in results:
    print(f"{stock['code']} {stock['name']} - 涨幅: {stock['change_pct']}%")
```

### 3. 自定义筛选条件

修改 `scripts/screen_stocks.py` 中的 `filter_stocks()` 函数：

```python
def filter_stocks(stocks_data: Dict) -> List[Dict]:
    filtered = []
    
    for code, data in stocks_data.items():
        # 自定义条件
        if not (条件1 <= data['指标1'] <= 条件2):
            continue
        
        filtered.append(data)
    
    return filtered
```

## 数据字段说明

| 字段 | 说明 | 单位 |
|------|------|------|
| code | 股票代码 | - |
| name | 股票名称 | - |
| price | 当前价格 | 元 |
| change_pct | 涨跌幅 | % |
| volume | 成交量 | 手 |
| amount | 成交额 | 万 |
| turnover | 换手率 | % |
| volume_ratio | 量比 | - |
| market_cap | 流通市值 | 亿 |
| pe | 市盈率 | - |
| pb | 市净率 | - |
| high | 最高价 | 元 |
| low | 最低价 | 元 |
| open | 开盘价 | 元 |
| prev_close | 昨收价 | 元 |

## 数据源

- **腾讯财经API**：`http://qt.gtimg.cn`
- 实时数据，无需认证
- 支持批量查询（每次最多约100只）

## 数据源

- **实时行情API**：`http://qt.gtimg.cn/q=`
  - 成交额=[37]（万元），涨幅=[32]，换手率=[38]，量比=[49]，流通市值=[44]，行业板块=[47]
  - 解析方式：`fields = raw.split('"')[1].split('~')`
- **K线API**：`https://web.ifzq.gtimg.cn/appstock/app/fqkline/get`
  - 使用前复权数据 `qfqday`，格式：[日期,开盘,收盘,最高,最低,量]
  - 腾讯K线格式 high=[3]、low=[4]（与注释顺序相反，以实际代码为准）

## 注意事项

1. **量比字段**：直接使用腾讯API字段[49]，非K线自算，收盘后正常有值
2. **均线自算**：MA5/10/20从K线前复权数据自行计算，腾讯实时API无对应字段
3. **均价计算**：今日均价 = 成交额(万元)×10000 / (成交量(手)×100)
4. **今日收盘**：均线条件计算使用当日收盘价（非实时价格），需收盘后运行
5. **API限制**：腾讯API无明确频率限制，建议批量查询（每批100只）
6. **建议运行时段**：尾盘 14:30-15:00（最佳），早盘 09:35-11:30

---

⚠️ **风险提示**：投资需谨慎，概不构成投资建议。
