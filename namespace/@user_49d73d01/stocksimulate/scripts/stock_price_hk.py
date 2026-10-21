import os
import akshare as ak
import pandas as pd
from datetime import datetime


class StockPriceHK:
    def __init__(self):
        self.currency = 'HKD'
        self.base_dir = self._get_data_dir()
        os.makedirs(self.base_dir, exist_ok=True)
        self.cache_file = os.path.join(self.base_dir, 'hk_stock_cache.csv')
        self.last_fetch_time = None
    
    def _get_data_dir(self) -> str:
        # 使用当前目录下的 data 目录，避免沙箱权限问题
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
    
    def _is_trading_time(self) -> bool:
        now = datetime.now()
        weekday = now.weekday()
        if weekday >= 5:
            return False
        hour = now.hour
        minute = now.minute
        total_minutes = hour * 60 + minute
        trading_start = 9 * 60
        trading_end = 16 * 60
        return trading_start <= total_minutes <= trading_end
    
    def _should_refresh(self) -> bool:
        if not os.path.exists(self.cache_file):
            return True
        
        try:
            df = pd.read_csv(self.cache_file)
            if df.empty:
                return True
            last_time_str = df.iloc[0].get('fetch_time', '')
            if not last_time_str:
                return True
            last_time = datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S')
            diff_minutes = (datetime.now() - last_time).total_seconds() / 60
            
            if self._is_trading_time():
                if diff_minutes > 15:
                    return True
            else:
                return False
        except Exception:
            return True
        
        return False
    
    def _save_cache(self, df):
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        df['fetch_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        df.to_csv(self.cache_file, index=False, encoding='utf-8')
    
    def _load_cache(self):
        if not os.path.exists(self.cache_file):
            return None
        try:
            df = pd.read_csv(self.cache_file, dtype={'代码': str})
            return df
        except Exception:
            return None
    
    def get_price(self, symbol: str) -> dict:
        try:
            df = None
            use_cache = not self._should_refresh()
            
            if use_cache:
                df = self._load_cache()
                if df is None:
                    df = ak.stock_hk_spot()
                    self._save_cache(df)
                    use_cache = False
            else:
                df = ak.stock_hk_spot()
                self._save_cache(df)
            
            stock_data = df[df['代码'] == symbol]
            if not stock_data.empty:
                price = float(stock_data.iloc[0]['最新价'])
                name = stock_data.iloc[0]['中文名称']
                return {
                    'price': price,
                    'name': name,
                    'currency': self.currency,
                    'from_cache': use_cache
                }
            else:
                return {'error': f"未找到股票代码 {symbol}"}
        except Exception as e:
            return {'error': f"获取港股价格失败：{str(e)}"}
    
    def get_price_at_date(self, symbol: str, date: str) -> dict:
        try:
            df = ak.stock_hk_daily(symbol)
            
            if df.empty:
                return {'error': f"未找到股票代码 {symbol} 的历史数据"}
            
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            target_date = date
            
            while target_date:
                filtered = df[df['date'] == target_date]
                if not filtered.empty:
                    price = float(filtered.iloc[0]['close'])
                    name = self._get_stock_name(symbol, df)
                    return {
                        'price': price,
                        'name': name,
                        'currency': self.currency,
                        'trade_date': target_date,
                        'from_cache': False
                    }
                
                target_date = self._get_prev_trading_date(target_date)
                if target_date is None:
                    break
            
            return {'error': f"无法找到 {symbol} 在 {date} 附近的交易数据"}
        except Exception as e:
            return {'error': f"获取港股历史价格失败：{str(e)}"}
    
    def _get_stock_name(self, symbol: str, df: pd.DataFrame) -> str:
        try:
            spot_df = ak.stock_hk_spot()
            stock_data = spot_df[spot_df['代码'] == symbol]
            if not stock_data.empty:
                return stock_data.iloc[0]['中文名称']
        except Exception:
            pass
        return f"港股{symbol}"
    
    def _get_prev_trading_date(self, date_str: str) -> str:
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d')
            for i in range(1, 10):
                prev_date = date - pd.Timedelta(days=i)
                if prev_date.weekday() < 5:
                    return prev_date.strftime('%Y-%m-%d')
            return None
        except Exception:
            return None