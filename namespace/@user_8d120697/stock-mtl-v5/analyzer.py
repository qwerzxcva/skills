#!/usr/bin/env python3
"""
股票分析专家模块
提供个股技术分析、量能分析、大盘对比、操作建议
"""

import sys
sys.path.insert(0, r'C:\Users\13073\.workbuddy\skills\stock-monitor')
from data_source import MultiDataSource, StockData
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class AnalysisResult:
    """分析结果"""
    stock_code: str
    stock_name: str
    price: float
    change_pct: float
    change: float
    open_price: float
    high: float
    low: float
    pre_close: float
    volume: int
    amount: float
    
    # 分析结果
    trend_signal: str  # 趋势信号
    volume_signal: str  # 量能信号
    market_comparison: str  # 大盘对比
    score: int  # 综合评分 0-5
    rating: str  # 评级
    suggestion: str  # 建议
    strategy: str  # 策略
    target_price: float  # 目标价
    stop_loss: float  # 止损价
    
    # 新增：财务数据
    pe: float = 0  # 市盈率
    pb: float = 0  # 市净率
    pe_status: str = ""  # PE评价
    pb_status: str = ""  # PB评价


class StockAnalyzer:
    """股票分析专家"""
    
    def __init__(self):
        self.data_source = MultiDataSource()
        # 延迟导入，避免循环依赖
        try:
            from enhanced_data import EnhancedDataSource
            self.enhanced = EnhancedDataSource()
        except ImportError:
            self.enhanced = None
    
    def analyze(self, code: str, name: str = None) -> AnalysisResult:
        """
        分析单只股票
        
        Args:
            code: 股票代码 (如 sh600105)
            name: 股票名称 (可选)
        
        Returns:
            AnalysisResult: 分析结果
        """
        # 获取股票数据
        stock_data = self.data_source.fetch_tencent([code])
        if code not in stock_data:
            raise ValueError(f"无法获取股票 {code} 的数据")
        
        d = stock_data[code]
        stock_name = name or d.name
        
        # 获取大盘数据
        market_data = self.data_source.fetch_tencent(['sh000001', 'sz399001'])
        
        # 技术分析
        trend_signal = self._analyze_trend(d)
        
        # 量能分析
        volume_signal = self._analyze_volume(d)
        
        # 大盘对比
        market_comparison = self._compare_market(d, market_data)
        
        # 综合评分
        score = self._calculate_score(d, market_data)
        
        # 生成建议
        rating, suggestion, strategy = self._generate_advice(score, d)
        
        # 目标价和止损
        target_price = d.high * 1.05 if d.change_pct > 5 else d.high
        stop_loss = d.low * 0.98
        
        # 获取财务数据
        pe, pb, pe_status, pb_status = 0, 0, "", ""
        if self.enhanced:
            try:
                pure_code = code.replace('sh', '').replace('sz', '')
                finance = self.enhanced.get_finance_data(pure_code)
                if finance:
                    pe = finance.pe
                    pb = finance.pb
                    pe_status = "偏高" if pe > 50 else "合理" if pe > 0 else "亏损"
                    pb_status = "偏高" if pb > 5 else "合理"
            except Exception:
                pass
        
        return AnalysisResult(
            stock_code=code,
            stock_name=stock_name,
            price=d.price,
            change_pct=d.change_pct,
            change=d.change,
            open_price=d.open,
            high=d.high,
            low=d.low,
            pre_close=d.pre_close,
            volume=d.volume,
            amount=d.amount,
            trend_signal=trend_signal,
            volume_signal=volume_signal,
            market_comparison=market_comparison,
            score=score,
            rating=rating,
            suggestion=suggestion,
            strategy=strategy,
            target_price=target_price,
            stop_loss=stop_loss,
            pe=pe,
            pb=pb,
            pe_status=pe_status,
            pb_status=pb_status
        )
    
    def _analyze_trend(self, data: StockData) -> str:
        """技术趋势分析"""
        signals = []
        
        # 涨跌判断
        if data.change_pct > 9.5:
            signals.append("涨停")
        elif data.change_pct > 5:
            signals.append("强势上涨")
        elif data.change_pct > 0:
            signals.append("上涨")
        elif data.change_pct > -5:
            signals.append("下跌")
        else:
            signals.append("大跌")
        
        # 开盘情况
        gap = ((data.open - data.pre_close) / data.pre_close) * 100
        if gap > 5:
            signals.append("大幅高开")
        elif gap > 2:
            signals.append("高开")
        elif gap < -2:
            signals.append("低开")
        
        # 收盘位置
        if data.high == data.price:
            signals.append("收盘最高价")
        elif data.low == data.price:
            signals.append("收盘最低价")
        
        return " | ".join(signals)
    
    def _analyze_volume(self, data: StockData) -> str:
        """量能分析"""
        if data.change_pct > 5 and data.volume > 100000:
            return "量价齐升"
        elif data.change_pct > 5:
            return "缩量上涨"
        elif data.volume > 500000:
            return "放量"
        else:
            return "量能正常"
    
    def _compare_market(self, data: StockData, market_data: Dict) -> str:
        """大盘对比"""
        if 'sh000001' not in market_data:
            return "无法对比"
        
        sh_change = market_data['sh000001'].change_pct
        relative = data.change_pct - sh_change
        
        if relative > 5:
            return f"大幅跑赢大盘 (+{relative:.2f}%)"
        elif relative > 0:
            return f"跑赢大盘 (+{relative:.2f}%)"
        else:
            return f"跑输大盘 ({relative:.2f}%)"
    
    def _calculate_score(self, data: StockData, market_data: Dict) -> int:
        """计算综合评分 0-5"""
        score = 0
        
        # 涨跌评分
        if data.change_pct > 5:
            score += 2
        elif data.change_pct > 0:
            score += 1
        
        # 收盘位置
        if data.high == data.price:
            score += 1
        
        # 量能
        if data.change_pct > 5 and data.volume > 100000:
            score += 1
        
        # 大盘对比
        if 'sh000001' in market_data:
            if data.change_pct > market_data['sh000001'].change_pct:
                score += 1
        
        return min(score, 5)
    
    def _generate_advice(self, score: int, data: StockData) -> Tuple[str, str, str]:
        """生成操作建议"""
        if score >= 4:
            return (
                "强烈推荐",
                "今日强势大涨，资金抢筹明显，明日有望继续冲高。",
                "若已持仓，可继续持有；若未持仓，明日开盘观察，不追高。"
            )
        elif score >= 3:
            return (
                "推荐",
                "今日表现强势，资金关注度高。",
                "可逢低关注，分批建仓。"
            )
        elif score >= 2:
            return (
                "中性偏多",
                "走势尚可，但需观察持续性。",
                "暂观望，等待更明确信号。"
            )
        elif score >= 1:
            return (
                "中性",
                "走势一般，无明显方向。",
                "观望为主，不操作。"
            )
        else:
            return (
                "谨慎",
                "走势偏弱，注意风险。",
                "减仓或离场观望。"
            )
    
    def print_report(self, result: AnalysisResult, push_to_wechat: bool = False):
        """打印分析报告"""
        print("="*60)
        print(f"{result.stock_name}（{result.stock_code}）分析报告")
        print("="*60)
        
        print("\n【一、行情数据】")
        print(f"当前价格：{result.price:.2f} 元")
        print(f"涨跌幅：{result.change_pct:+.2f}%")
        print(f"涨跌额：{result.change:+.2f} 元")
        print(f"今日开盘：{result.open_price:.2f} 元")
        print(f"今日最高：{result.high:.2f} 元")
        print(f"今日最低：{result.low:.2f} 元")
        print(f"昨日收盘：{result.pre_close:.2f} 元")
        print(f"成交量：{result.volume:,} 手")
        print(f"成交额：{result.amount/10000:.2f} 万元")
        
        print("\n【二、技术分析】")
        print(f"趋势信号：{result.trend_signal}")
        print(f"量能信号：{result.volume_signal}")
        print(f"大盘对比：{result.market_comparison}")
        
        print("\n【三、财务指标】")
        if result.pe > 0:
            print(f"市盈率(PE)：{result.pe:.2f} ({result.pe_status})")
            print(f"市净率(PB)：{result.pb:.2f} ({result.pb_status})")
        else:
            print("财务数据暂不可用")
        
        print("\n【四、综合评分】")
        print(f"评分：{'★' * result.score}{'☆' * (5-result.score)} ({result.score}/5)")
        print(f"评级：{result.rating}")
        
        print("\n【五、操作建议】")
        print(f"建议：{result.suggestion}")
        print(f"策略：{result.strategy}")
        print(f"目标价：{result.target_price:.2f} 元")
        print(f"止损价：{result.stop_loss:.2f} 元")
        
        print("\n" + "="*60)
        print("免责声明：以上分析仅供参考，不构成投资建议。")
        print("股市有风险，投资需谨慎。")
        print("="*60)
        
        # 自动推送到企业微信
        if push_to_wechat:
            self._push_to_wechat(result)
    
    def _push_to_wechat(self, result: AnalysisResult):
        """推送分析报告到企微"""
        try:
            from notifier import Notifier
            notifier = Notifier()
            
            stars = "★" * result.score + "☆" * (5 - result.score)
            
            content = f"""**股票名称：** {result.stock_name} ({result.stock_code})

**当前价格：** {result.price:.2f} 元 | **涨跌幅：** {result.change_pct:+.2f}%

**技术面：** {result.trend_signal}
**量能面：** {result.volume_signal}
**大盘对比：** {result.market_comparison}

**财务指标：**
- PE: {result.pe:.2f} ({result.pe_status})
- PB: {result.pb:.2f} ({result.pb_status})

**评分：** {stars} ({result.score}/5) | **评级：** {result.rating}

**操作建议：**
> {result.suggestion}
> 
> **目标价：** {result.target_price:.2f} 元 | **止损价：** {result.stop_loss:.2f} 元

---
> 本报告由股票监测助手自动生成，仅供参考"""
            
            notifier.send_analysis_report(
                stock_name=result.stock_name,
                stock_code=result.stock_code,
                rating=result.rating,
                score=result.score,
                suggestion=f"{result.suggestion}\n目标价:{result.target_price:.2f} 止损价:{result.stop_loss:.2f}"
            )
        except Exception:
            pass  # 推送失败不影响主流程


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='股票分析专家')
    parser.add_argument('code', help='股票代码 (如 sh600105 或 600519)')
    parser.add_argument('--name', '-n', help='股票名称 (可选)')
    parser.add_argument('--push', '-p', action='store_true', help='分析完成后推送到企业微信')
    
    args = parser.parse_args()
    
    # 处理代码格式
    code = args.code
    if not code.startswith(('sh', 'sz')):
        if code.startswith('6'):
            code = 'sh' + code
        else:
            code = 'sz' + code
    
    analyzer = StockAnalyzer()
    result = analyzer.analyze(code, args.name)
    analyzer.print_report(result, push_to_wechat=args.push)


if __name__ == '__main__':
    main()
