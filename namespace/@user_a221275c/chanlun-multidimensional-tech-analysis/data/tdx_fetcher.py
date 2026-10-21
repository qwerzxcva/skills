"""
TDX 通达信数据获取层
基于TDX MCP Connector获取行情和资金流向数据，标准化输出pandas DataFrame
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


class TDXFetcher:
    """通达信数据获取器，封装TDX MCP调用并标准化输出"""

    REQUIRED_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume']
    OPTIONAL_COLUMNS = ['amount', 'turnover', 'amplitude', 'pct_chg']

    def __init__(self):
        self._cache = {}

    # --- 数据标准化 ---

    def _standardize_ohlcv(self, raw_data: list) -> pd.DataFrame:
        """
        将TDX返回的原始数据标准化为统一DataFrame

        raw_data格式: [{'date': '20240601', 'open': 10.5, 'high': 10.8, ...}, ...]
        """
        if not raw_data:
            return pd.DataFrame(columns=self.REQUIRED_COLUMNS)

        df = pd.DataFrame(raw_data)

        # 统一列名映射
        col_map = {
            'trade_date': 'date', 'date': 'date',
            'open': 'open', 'OPEN': 'open',
            'high': 'high', 'HIGH': 'high',
            'low': 'low', 'LOW': 'low',
            'close': 'close', 'CLOSE': 'close',
            'vol': 'volume', 'volume': 'volume', 'VOL': 'volume',
            'amount': 'amount', 'AMOUNT': 'amount',
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        # 确保必需列存在
        for col in self.REQUIRED_COLUMNS:
            if col not in df.columns:
                if col == 'volume':
                    df['volume'] = 0
                else:
                    raise ValueError(f"缺少必需列: {col}，可用列: {list(df.columns)}")

        # 类型转换
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0).astype(int)

        # 列排序
        columns = [c for c in self.REQUIRED_COLUMNS if c in df.columns]
        columns += [c for c in self.OPTIONAL_COLUMNS if c in df.columns]
        df = df[columns]

        # 去重排序
        df = df.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)

        # 处理异常值
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col].clip(lower=0.01)

        # 确保 high >= max(open, close) >= min(open, close) >= low
        df['high'] = df[['high', 'open', 'close']].max(axis=1)
        df['low'] = df[['low', 'open', 'close']].min(axis=1)

        return df

    def _standardize_fund_flow(self, raw_data: list) -> pd.DataFrame:
        """将资金流向原始数据标准化"""
        if not raw_data:
            return pd.DataFrame()

        df = pd.DataFrame(raw_data)
        col_map = {
            'trade_date': 'date',
            'main_net_inflow': 'main_net_inflow',
            'super_large_net_inflow': 'super_large_net_inflow',
            'large_net_inflow': 'large_net_inflow',
            'medium_net_inflow': 'medium_net_inflow',
            'small_net_inflow': 'small_net_inflow',
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
        return df.sort_values('date').reset_index(drop=True) if 'date' in df.columns else df

    # --- 通用辅助 ---

    def validate_df(self, df: pd.DataFrame) -> bool:
        """验证DataFrame是否满足分析最低要求"""
        if df is None or df.empty:
            return False
        if len(df) < 30:  # 至少30根K线
            return False
        for col in self.REQUIRED_COLUMNS:
            if col not in df.columns:
                return False
            if df[col].isna().all():
                return False
        return True

    def slice_period(self, df: pd.DataFrame, start_date=None, end_date=None) -> pd.DataFrame:
        """按日期切片"""
        if start_date:
            df = df[df['date'] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df['date'] <= pd.to_datetime(end_date)]
        return df.reset_index(drop=True)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加基础技术指标（均线、MACD等辅助计算）"""
        df = df.copy()

        # 均线
        for period in [5, 10, 20, 60, 120, 250]:
            df[f'ma{period}'] = df['close'].rolling(window=period).mean()

        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['dif'] = ema12 - ema26
        df['dea'] = df['dif'].ewm(span=9, adjust=False).mean()
        df['macd'] = 2 * (df['dif'] - df['dea'])

        # 波动率（20日）
        df['atr20'] = df['high'].rolling(20).max() - df['low'].rolling(20).min()
        df['volatility'] = df['close'].pct_change().rolling(20).std()

        # 量比
        df['volume_ma5'] = df['volume'].rolling(5).mean()
        df['volume_ratio'] = np.where(df['volume_ma5'] > 0, df['volume'] / df['volume_ma5'], 1.0)

        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """获取数据摘要"""
        if df.empty:
            return {}
        last = df.iloc[-1]
        first = df.iloc[0]
        start_d = df['date'].iloc[0]
        end_d = df['date'].iloc[-1]
        start_d = start_d.date() if hasattr(start_d, 'date') else str(start_d)[:10]
        end_d = end_d.date() if hasattr(end_d, 'date') else str(end_d)[:10]
        return {
            'symbol': '',
            'period': 'daily',
            'start_date': str(start_d),
            'end_date': str(end_d),
            'total_bars': len(df),
            'start_price': round(float(first['close']), 2),
            'end_price': round(float(last['close']), 2),
            'change_pct': round(float((last['close'] - first['close']) / first['close'] * 100), 2),
            'max_price': round(float(df['high'].max()), 2),
            'min_price': round(float(df['low'].min()), 2),
            'avg_volume': int(df['volume'].mean()),
        }
