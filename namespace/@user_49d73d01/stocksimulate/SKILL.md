---
name: stock_simulate
description: "股票模拟仓管理技能。管理用户的股票模拟账户，支持设定资金、买入卖出股票、查看持仓盈亏。支持港股和A股，非交易时间也可交易。"
agent_created: true
---

# 股票模拟仓管理

## 初始化安装

首次使用前需安装 Python 依赖：

```bash
pip install -r requirements.txt
```

依赖说明：
- `akshare`: 财经数据接口库，提供股票实时价格数据
- `pandas`: 数据处理库，用于 CSV 文件读写
- `numpy`: 数值计算库（akshare 依赖）

## 使用方式

```bash
# 初始化账户（默认100万人民币+100万港币）
python scripts/main.py --init

# 买入股票（当前日期）
python scripts/main.py --buy --symbol 00700 --quantity 100 --market hk  # 港股
python scripts/main.py --buy --symbol 002594 --quantity 200 --market cn  # A股

# 买入股票（历史日期，模拟过去交易）
python scripts/main.py --buy --symbol 00700 --quantity 100 --market hk --date 2026-01-01
python scripts/main.py --buy --symbol 600036 --quantity 200 --market cn --date 2026-01-01

# 卖出股票
python scripts/main.py --sell --symbol 00700 --quantity 50 --market hk

# 查看持仓
python scripts/main.py --show

# 获取股价（当前价格）
python scripts/main.py --price --symbol 00700 --market hk

# 获取股价（历史价格）
python scripts/main.py --price --symbol 00700 --market hk --date 2026-01-01

# 重置账户
python scripts/main.py --reset
```

## 功能说明

| 功能 | 命令格式 |
|------|----------|
| 初始化账户 | `--init [--rmb 金额] [--hkd 金额]` |
| 买入股票 | `--buy --symbol 代码 --quantity 数量 --market hk/cn [--date YYYY-MM-DD]` |
| 卖出股票 | `--sell --symbol 代码 --quantity 数量 --market hk/cn` |
| 查看持仓 | `--show` |
| 获取股价 | `--price --symbol 代码 --market hk/cn [--date YYYY-MM-DD]` |
| 重置账户 | `--reset` |

## 关键规则

1. **资金限制** - 不允许超出资金额度买入，不允许卖空
2. **资金分开管理** - 人民币和港币独立管理，买港股用港币，买A股用人民币
3. **成本计算** - 多次买入同一股票自动计算平均成本
4. **数据持久化** - 所有数据保存在用户配置目录，重启不丢失
5. **历史日期交易** - 支持使用 `--date` 参数模拟过去日期的交易，系统会自动获取该日期或最近交易日的股价

## 数据存储

用户数据保存在：
- **Windows**: `%APPDATA%\stock-simulate`
- **Linux/Mac**: `~/.config/stock-simulate`

数据文件：`account.csv`（账户）、`holdings.csv`（持仓）、`transactions.csv`（交易记录）

## 示例对话

**用户**: "初始化一个模拟账户，100万人民币和100万港币"
→ 运行 `--init --rmb 1000000 --hkd 1000000`

**用户**: "买100股腾讯"
→ 运行 `--buy --symbol 00700 --quantity 100 --market hk`

**用户**: "在2026年1月1日买100股腾讯"
→ 运行 `--buy --symbol 00700 --quantity 100 --market hk --date 2026-01-01`

**用户**: "看看现在的持仓"
→ 运行 `--show`

**用户**: "重置账户"
→ 运行 `--reset`
