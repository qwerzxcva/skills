import os
import csv
import json
import argparse
import pandas as pd
from datetime import datetime

from stock_price_hk import StockPriceHK
from stock_price_a import StockPriceA


def get_data_dir() -> str:
    # 使用当前目录下的 data 目录，避免沙箱权限问题
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')


BASE_DIR = get_data_dir()
os.makedirs(BASE_DIR, exist_ok=True)

ACCOUNT_FILE = os.path.join(BASE_DIR, "account.csv")
HOLDINGS_FILE = os.path.join(BASE_DIR, "holdings.csv")
TRANSACTIONS_FILE = os.path.join(BASE_DIR, "transactions.csv")


def init_account(rmb_amount: float = 1000000.0, hkd_amount: float = 1000000.0) -> str:
    try:
        if os.path.exists(ACCOUNT_FILE):
            os.remove(ACCOUNT_FILE)
        if os.path.exists(HOLDINGS_FILE):
            os.remove(HOLDINGS_FILE)
        if os.path.exists(TRANSACTIONS_FILE):
            os.remove(TRANSACTIONS_FILE)

        with open(ACCOUNT_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['currency', 'initial_amount', 'current_amount'])
            writer.writerow(['RMB', rmb_amount, rmb_amount])
            writer.writerow(['HKD', hkd_amount, hkd_amount])

        with open(HOLDINGS_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['symbol', 'name', 'quantity', 'avg_cost', 'market', 'currency'])

        with open(TRANSACTIONS_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['datetime', 'action', 'symbol', 'name', 'quantity', 'price', 'total_amount', 'market', 'currency'])

        return f"账户初始化成功！\n人民币初始资金：¥{rmb_amount:,.2f}\n港币初始资金：HK${hkd_amount:,.2f}"
    except Exception as e:
        return f"账户初始化失败：{str(e)}"


def get_stock_price(symbol: str, market: str, date: str = None) -> dict:
    try:
        market = market.lower()
        original_symbol = symbol

        if market == 'hk':
            stock_price = StockPriceHK()
            if date:
                return stock_price.get_price_at_date(original_symbol, date)
            return stock_price.get_price(original_symbol)
        elif market == 'cn':
            stock_price = StockPriceA()
            if date:
                return stock_price.get_price_at_date(original_symbol, date)
            return stock_price.get_price(original_symbol)
        else:
            return {'error': f"不支持的市场类型：{market}"}
    except Exception as e:
        return {'error': f"获取股票价格失败：{str(e)}"}


def read_account() -> dict:
    if not os.path.exists(ACCOUNT_FILE):
        init_account()
    df = pd.read_csv(ACCOUNT_FILE)
    return {row['currency']: {'initial': row['initial_amount'], 'current': row['current_amount']}
            for _, row in df.iterrows()}


def write_account(account: dict):
    with open(ACCOUNT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['currency', 'initial_amount', 'current_amount'])
        for currency, amounts in account.items():
            writer.writerow([currency, amounts['initial'], amounts['current']])


def read_holdings() -> pd.DataFrame:
    if not os.path.exists(HOLDINGS_FILE):
        init_account()
    return pd.read_csv(HOLDINGS_FILE, dtype={'symbol': str})


def write_holdings(holdings: pd.DataFrame):
    # 确保symbol字段为字符串类型
    holdings['symbol'] = holdings['symbol'].astype(str)
    holdings.to_csv(HOLDINGS_FILE, index=False, encoding='utf-8')


def log_transaction(action: str, symbol: str, name: str, quantity: int, price: float, total_amount: float, market: str, currency: str, trade_date: str = None):
    if trade_date:
        timestamp = trade_date + ' 09:30:00'
    else:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(TRANSACTIONS_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, action, symbol, name, quantity, price, total_amount, market, currency])


def buy_stock(symbol: str, quantity: int, market: str, date: str = None) -> str:
    try:
        price_info = get_stock_price(symbol, market, date)
        if 'error' in price_info:
            return price_info['error']

        price = price_info['price']
        name = price_info['name']
        currency = price_info['currency']
        trade_date = price_info.get('trade_date', date)
        total_amount = price * quantity

        account = read_account()
        if currency not in account:
            return f"账户中没有{currency}资金"

        if account[currency]['current'] < total_amount:
            return f"资金不足！当前{currency}余额：{account[currency]['current']:,.2f}，需要：{total_amount:,.2f}"

        holdings = read_holdings()

        existing = holdings[(holdings['symbol'] == symbol) & (holdings['market'] == market.lower())]
        if not existing.empty:
            idx = existing.index[0]
            old_quantity = holdings.loc[idx, 'quantity']
            old_cost = holdings.loc[idx, 'avg_cost']
            new_total_cost = old_cost * old_quantity + total_amount
            new_quantity = old_quantity + quantity
            holdings.loc[idx, 'quantity'] = new_quantity
            holdings.loc[idx, 'avg_cost'] = new_total_cost / new_quantity
        else:
            new_row = pd.DataFrame([{
                'symbol': symbol,
                'name': name,
                'quantity': quantity,
                'avg_cost': price,
                'market': market.lower(),
                'currency': currency
            }])
            holdings = pd.concat([holdings, new_row], ignore_index=True)

        account[currency]['current'] -= total_amount
        write_account(account)
        write_holdings(holdings)
        log_transaction('buy', symbol, name, quantity, price, total_amount, market.lower(), currency, trade_date)

        result = f"买入成功！\n股票：{name}({symbol})\n数量：{quantity}股\n单价：{currency} {price:,.2f}\n总价：{currency} {total_amount:,.2f}\n剩余{currency}资金：{account[currency]['current']:,.2f}"
        if trade_date:
            result += f"\n交易日期：{trade_date}"
        return result
    except Exception as e:
        return f"买入失败：{str(e)}"


def sell_stock(symbol: str, quantity: int, market: str) -> str:
    try:
        price_info = get_stock_price(symbol, market)
        if 'error' in price_info:
            return price_info['error']

        price = price_info['price']
        name = price_info['name']
        currency = price_info['currency']
        total_amount = price * quantity

        holdings = read_holdings()
        existing = holdings[(holdings['symbol'] == symbol) & (holdings['market'] == market.lower())]

        if existing.empty:
            return f"未持有该股票：{symbol}"

        idx = existing.index[0]
        available_quantity = holdings.loc[idx, 'quantity']

        if available_quantity < quantity:
            return f"持仓不足！当前持有：{available_quantity}股，欲卖出：{quantity}股"

        account = read_account()

        if holdings.loc[idx, 'quantity'] == quantity:
            holdings = holdings.drop(idx)
        else:
            holdings.loc[idx, 'quantity'] -= quantity

        account[currency]['current'] += total_amount
        write_account(account)
        write_holdings(holdings)
        log_transaction('sell', symbol, name, quantity, price, total_amount, market.lower(), currency)

        return f"卖出成功！\n股票：{name}({symbol})\n数量：{quantity}股\n单价：{currency} {price:,.2f}\n总价：{currency} {total_amount:,.2f}\n当前{currency}资金：{account[currency]['current']:,.2f}"
    except Exception as e:
        return f"卖出失败：{str(e)}"


def show_portfolio() -> str:
    try:
        account = read_account()
        holdings = read_holdings()

        rmb_initial = account.get('RMB', {}).get('initial', 0)
        hkd_initial = account.get('HKD', {}).get('initial', 0)
        rmb_current = account.get('RMB', {}).get('current', 0)
        hkd_current = account.get('HKD', {}).get('current', 0)

        total_initial = rmb_initial + hkd_initial

        holdings_value_rmb = 0
        holdings_value_hkd = 0

        result = "=" * 80 + "\n"
        result += "                    股票模拟仓 - 持仓报表\n"
        result += "=" * 80 + "\n\n"

        result += "【账户资金】\n"
        result += f"  人民币初始资金：¥{rmb_initial:,.2f}\n"
        result += f"  港币初始资金：  HK${hkd_initial:,.2f}\n"
        result += f"  总初始资金：    ¥+HK${total_initial:,.2f}\n\n"

        if holdings.empty:
            result += "【持仓明细】\n"
            result += "  暂无持仓\n\n"
            result += "【账户总览】\n"
            result += f"  总资产：       ¥{rmb_current:,.2f} + HK${hkd_current:,.2f}\n"
            result += f"  总盈利：       ¥{rmb_current - rmb_initial:,.2f} + HK${hkd_current - hkd_initial:,.2f}\n"
            result += f"  总收益率：     {(rmb_current + hkd_current - total_initial) / total_initial * 100:.2f}%\n"
            result += "=" * 80
            return result

        result += "【持仓明细】\n"
        result += "-" * 80 + "\n"
        result += f"{'股票名称':<15} {'代码':<12} {'持仓数量':<8} {'平均成本':<12} {'当前价格':<12} {'市值':<12} {'盈亏':<12} {'盈亏比例':<10}\n"
        result += "-" * 80 + "\n"

        cache_warnings = []
        for _, row in holdings.iterrows():
            price_info = get_stock_price(row['symbol'], row['market'])
            current_price = price_info.get('price', row['avg_cost']) if 'error' not in price_info else row['avg_cost']
            if price_info.get('cache_warning'):
                cache_warnings.append(price_info['cache_warning'])

            quantity = int(row['quantity'])
            avg_cost = row['avg_cost']
            currency = row['currency']

            market_value = current_price * quantity
            profit = market_value - avg_cost * quantity
            profit_ratio = (profit / (avg_cost * quantity)) * 100 if avg_cost > 0 else 0

            if currency == 'RMB':
                holdings_value_rmb += market_value
            else:
                holdings_value_hkd += market_value

            profit_str = f"{currency} {profit:,.2f}"
            if profit >= 0:
                profit_str = "+" + profit_str

            result += f"{row['name']:<15} {row['symbol']:<12} {quantity:<8} {currency} {avg_cost:>7,.2f} {currency} {current_price:>7,.2f} {currency} {market_value:>7,.2f} {profit_str:>12} {profit_ratio:>9.2f}%\n"

        result += "-" * 80 + "\n\n"

        total_assets_rmb = rmb_current + holdings_value_rmb
        total_assets_hkd = hkd_current + holdings_value_hkd
        total_current = total_assets_rmb + total_assets_hkd
        total_profit = total_current - total_initial
        total_profit_ratio = (total_profit / total_initial) * 100 if total_initial > 0 else 0

        result += "【账户总览】\n"
        result += f"  人民币持仓市值：¥{holdings_value_rmb:,.2f}\n"
        result += f"  港币持仓市值：  HK${holdings_value_hkd:,.2f}\n"
        result += f"  人民币现金：    ¥{rmb_current:,.2f}\n"
        result += f"  港币现金：      HK${hkd_current:,.2f}\n"
        result += "-" * 40 + "\n"
        result += f"  总资产：        ¥{total_assets_rmb:,.2f} + HK${total_assets_hkd:,.2f}\n"
        result += f"  总盈利：        ¥+HK${total_profit:,.2f}\n"
        result += f"  总收益率：      {total_profit_ratio:,.2f}%\n"
        result += "=" * 80

        # 添加缓存警告
        if cache_warnings:
            for warning in cache_warnings:
                result += f"\n⚠️ {warning}"

        return result
    except Exception as e:
        return f"获取持仓失败：{str(e)}"


def reset_account() -> str:
    return init_account(1000000.0, 1000000.0)


def main():
    parser = argparse.ArgumentParser(description='股票模拟仓管理工具')
    parser.add_argument('--init', action='store_true', help='初始化账户')
    parser.add_argument('--rmb', type=float, default=1000000.0, help='人民币初始金额')
    parser.add_argument('--hkd', type=float, default=1000000.0, help='港币初始金额')
    parser.add_argument('--buy', action='store_true', help='买入股票')
    parser.add_argument('--sell', action='store_true', help='卖出股票')
    parser.add_argument('--symbol', type=str, help='股票代码')
    parser.add_argument('--quantity', type=int, help='交易数量')
    parser.add_argument('--market', type=str, help='市场类型(hk/cn)')
    parser.add_argument('--date', type=str, help='交易日期(格式: YYYY-MM-DD)，用于模拟历史日期买入')
    parser.add_argument('--show', action='store_true', help='查看持仓')
    parser.add_argument('--price', action='store_true', help='获取股票价格')
    parser.add_argument('--reset', action='store_true', help='重置账户')

    args = parser.parse_args()

    if args.init:
        print(init_account(args.rmb, args.hkd))
    elif args.buy:
        if not args.symbol or not args.quantity or not args.market:
            print("买入股票需要指定 --symbol, --quantity 和 --market 参数")
        else:
            print(buy_stock(args.symbol, args.quantity, args.market, args.date))
    elif args.sell:
        if not args.symbol or not args.quantity or not args.market:
            print("卖出股票需要指定 --symbol, --quantity 和 --market 参数")
        else:
            print(sell_stock(args.symbol, args.quantity, args.market))
    elif args.show:
        print(show_portfolio())
    elif args.price:
        if not args.symbol or not args.market:
            print("获取股票价格需要指定 --symbol 和 --market 参数")
        else:
            print(get_stock_price(args.symbol, args.market, args.date))
    elif args.reset:
        print(reset_account())
    else:
        print("股票模拟仓管理工具")
        print("=" * 40)
        print("使用方法：")
        print("  python main.py --init [--rmb 金额] [--hkd 金额]  # 初始化账户")
        print("  python main.py --buy --symbol 代码 --quantity 数量 --market hk/cn [--date YYYY-MM-DD]  # 买入股票")
        print("  python main.py --sell --symbol 代码 --quantity 数量 --market hk/cn  # 卖出股票")
        print("  python main.py --show  # 查看持仓")
        print("  python main.py --price --symbol 代码 --market hk/cn [--date YYYY-MM-DD]  # 获取股票价格")
        print("  python main.py --reset  # 重置账户")
        print("=" * 40)


if __name__ == "__main__":
    main()
