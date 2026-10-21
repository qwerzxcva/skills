import os
import akshare as ak
import pandas as pd
from datetime import datetime


class StockPriceA:
    def __init__(self):
        self.currency = 'RMB'
        self.base_dir = self._get_data_dir()
        os.makedirs(self.base_dir, exist_ok=True)
        self.cache_file = os.path.join(self.base_dir, 'a_stock_cache.csv')
        self.name_cache_file = os.path.join(self.base_dir, 'a_stock_name_cache.csv')
    
    def _get_data_dir(self) -> str:
        # 使用当前目录下的 data 目录，避免沙箱权限问题
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
    
    def _format_symbol(self, symbol: str) -> str:
        if len(symbol) == 6:
            if symbol.startswith('6'):
                return 'sh' + symbol
            else:
                return 'sz' + symbol
        return symbol
    
    def get_stock_name(self, symbol: str) -> str:
        try:
            formatted_symbol = self._format_symbol(symbol)
            
            cache_df = self._load_name_cache()
            if cache_df is not None:
                stock_data = cache_df[cache_df['symbol'] == formatted_symbol]
                if not stock_data.empty:
                    return stock_data.iloc[0]['name']
            
            cache_df = self._refresh_name_cache()
            if cache_df is not None:
                stock_data = cache_df[cache_df['symbol'] == formatted_symbol]
                if not stock_data.empty:
                    return stock_data.iloc[0]['name']
            
            return formatted_symbol
        except Exception:
            return formatted_symbol
    
    def _load_name_cache(self):
        if not os.path.exists(self.name_cache_file):
            return None
        try:
            cache_df = pd.read_csv(self.name_cache_file, dtype={'symbol': str})
            if 'fetch_date' in cache_df.columns:
                fetch_date = cache_df.iloc[0]['fetch_date']
                today = datetime.now().strftime('%Y-%m-%d')
                if fetch_date == today:
                    return cache_df
            return cache_df
        except Exception:
            return None
    
    def _refresh_name_cache(self):
        try:
            os.makedirs(os.path.dirname(self.name_cache_file), exist_ok=True)
            df = ak.stock_info_a_code_name()
            df['symbol'] = df['code'].apply(lambda x: 'sh' + x if x.startswith('6') else 'sz' + x)
            df['fetch_date'] = datetime.now().strftime('%Y-%m-%d')
            df['fetch_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            df = df[['symbol', 'name', 'fetch_date', 'fetch_time']]
            df.to_csv(self.name_cache_file, index=False, encoding='utf-8')
            return df
        except Exception:
            return None
    
    def _should_refresh(self, symbol: str) -> bool:
        if not os.path.exists(self.cache_file):
            return True
        
        try:
            cache_df = pd.read_csv(self.cache_file, dtype={'symbol': str})
            cache_data = cache_df[cache_df['symbol'] == symbol]
            if cache_data.empty:
                return True
            cache_time = pd.to_datetime(cache_data.iloc[0]['timestamp'])
            if (datetime.now() - cache_time).total_seconds() > 3600:
                return True
        except Exception:
            return True
        
        return False
    
    def _save_cache(self, symbol: str, price: float, name: str):
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        cache_data = []
        if os.path.exists(self.cache_file):
            cache_df = pd.read_csv(self.cache_file, dtype={'symbol': str})
            cache_df = cache_df[cache_df['symbol'] != symbol]
            cache_data = cache_df.to_dict('records')
        
        cache_data.append({
            'symbol': symbol,
            'price': price,
            'name': name,
            'currency': self.currency,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
        df = pd.DataFrame(cache_data)
        df['symbol'] = df['symbol'].astype(str)
        df.to_csv(self.cache_file, index=False, encoding='utf-8')
    
    def _load_cache(self, symbol: str):
        if not os.path.exists(self.cache_file):
            return None
        try:
            cache_df = pd.read_csv(self.cache_file, dtype={'symbol': str})
            cache_data = cache_df[cache_df['symbol'] == symbol]
            if not cache_data.empty:
                return {
                    'price': float(cache_data.iloc[0]['price']),
                    'name': cache_data.iloc[0]['name'],
                    'currency': cache_data.iloc[0]['currency'],
                    'from_cache': True
                }
        except Exception:
            pass
        return None
    
    def get_price(self, symbol: str) -> dict:
        try:
            original_symbol = symbol
            
            cache_result = self._load_cache(original_symbol)
            if cache_result and not self._should_refresh(original_symbol):
                return cache_result
            
            formatted_symbol = self._format_symbol(original_symbol)
            
            today = datetime.now().strftime('%Y-%m-%d')
            df = ak.stock_zh_a_daily(symbol=formatted_symbol, start_date=today, end_date=today)
            
            if df.empty:
                df = ak.stock_zh_a_daily(symbol=formatted_symbol, start_date='2026-01-01', end_date=today)
            
            if not df.empty:
                last_row = df.iloc[-1]
                price = float(last_row['close'])
                name = self.get_stock_name(original_symbol)
                self._save_cache(original_symbol, price, name)
                return {
                    'price': price,
                    'name': name,
                    'currency': self.currency,
                    'from_cache': False
                }
            else:
                if cache_result:
                    return cache_result
                return {'error': f"未找到股票代码 {original_symbol}"}
        except Exception as e:
            cache_result = self._load_cache(original_symbol)
            if cache_result:
                return cache_result
            return {'error': f"获取A股价格失败：{str(e)}"}
    
    def get_price_at_date(self, symbol: str, date: str) -> dict:
        try:
            original_symbol = symbol
            formatted_symbol = self._format_symbol(original_symbol)
            
            df = ak.stock_zh_a_daily(symbol=formatted_symbol, start_date=date, end_date=date)
            
            if df.empty:
                start_date = (datetime.strptime(date, '%Y-%m-%d') - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
                df = ak.stock_zh_a_daily(symbol=formatted_symbol, start_date=start_date, end_date=date)
            
            if df.empty:
                return {'error': f"未找到股票代码 {original_symbol} 的历史数据"}
            
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            
            target_date = date
            while target_date:
                filtered = df[df['date'] == target_date]
                if not filtered.empty:
                    price = float(filtered.iloc[0]['close'])
                    name = self.get_stock_name(original_symbol)
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
            
            return {'error': f"无法找到 {original_symbol} 在 {date} 附近的交易数据"}
        except Exception as e:
            return {'error': f"获取A股历史价格失败：{str(e)}"}
    
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