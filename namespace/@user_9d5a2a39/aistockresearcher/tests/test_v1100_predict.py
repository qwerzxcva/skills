# -*- coding: utf-8 -*-
"""
v11.0 多周期预测器测试 (test_v1100_predict.py)

覆盖 prediction_v1100.py：
  - HorizonPrediction / MultiHorizonResult 数据结构
  - detect_asset_type 资产识别（股票/基金/期货/指数）
  - predict_horizon 单周期预测（动量/波动率/支撑压力/驱动风险）
  - predict_multi_horizon 多周期预测（1d/5d/1M/3M/6M）
  - calibrate_probability 历史概率校准
  - 自检
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAssetTypeDetection(unittest.TestCase):
    """资产类型识别测试。"""

    def test_detect_stock(self):
        from stock_researcher.prediction_v1100 import detect_asset_type
        self.assertEqual(detect_asset_type("600519"), "stock")
        self.assertEqual(detect_asset_type("000001"), "stock")
        self.assertEqual(detect_asset_type("300750"), "stock")
        self.assertEqual(detect_asset_type("688981"), "stock")

    def test_detect_fund(self):
        from stock_researcher.prediction_v1100 import detect_asset_type
        # 基金代码段前缀
        self.assertEqual(detect_asset_type("110022"), "fund")
        self.assertEqual(detect_asset_type("161725"), "fund")
        self.assertEqual(detect_asset_type("519677"), "fund")

    def test_detect_futures(self):
        from stock_researcher.prediction_v1100 import detect_asset_type
        self.assertEqual(detect_asset_type("AU"), "futures")
        self.assertEqual(detect_asset_type("CU2502"), "futures")
        self.assertEqual(detect_asset_type("SR"), "futures")

    def test_detect_index(self):
        from stock_researcher.prediction_v1100 import detect_asset_type
        self.assertEqual(detect_asset_type("idx:000300"), "index")
        self.assertEqual(detect_asset_type("IDX:SPX"), "index")


class TestHorizonPrediction(unittest.TestCase):
    """单周期预测测试。"""

    def test_predict_bullish_trend(self):
        from stock_researcher.prediction_v1100 import predict_horizon
        # 构造持续上涨的价格序列
        prices = [100 + i * 0.5 for i in range(60)]
        pred = predict_horizon(prices, horizon="1M", regime="bullish")
        self.assertEqual(pred.horizon, "1M")
        self.assertIn(pred.direction, ("bullish", "neutral", "bearish"))
        self.assertGreater(pred.probability, 0.4)
        self.assertLessEqual(pred.probability, 1.0)
        self.assertGreater(pred.confidence, 0.4)
        self.assertEqual(pred.method, "rule_based")
        self.assertEqual(pred.quality, "derived")  # ≥ 60 样本

    def test_predict_bearish_trend(self):
        from stock_researcher.prediction_v1100 import predict_horizon
        prices = [200 - i * 0.5 for i in range(60)]
        pred = predict_horizon(prices, horizon="1M", regime="bearish")
        self.assertEqual(pred.direction, "bearish")
        self.assertGreater(pred.probability, 0.5)

    def test_predict_neutral_with_short_data(self):
        from stock_researcher.prediction_v1100 import predict_horizon
        prices = [100 + i * 0.1 for i in range(30)]
        pred = predict_horizon(prices, horizon="1d")
        # 短数据 → estimated
        self.assertEqual(pred.quality, "estimated")
        # 用 60 样本测 derived
        prices_long = [100 + i * 0.05 for i in range(60)]
        pred2 = predict_horizon(prices_long, horizon="1d")
        self.assertEqual(pred2.quality, "derived")

    def test_predict_empty_data(self):
        from stock_researcher.prediction_v1100 import predict_horizon
        pred = predict_horizon([], horizon="1d")
        # 数据为空时也返回降级结果
        self.assertEqual(pred.direction, "neutral")
        self.assertEqual(pred.quality, "estimated")

    def test_predict_includes_support_resistance(self):
        from stock_researcher.prediction_v1100 import predict_horizon
        prices = [100 + i * 0.5 for i in range(60)]
        pred = predict_horizon(prices, horizon="1M")
        self.assertGreater(pred.key_support, 0)
        self.assertGreater(pred.key_resistance, 0)
        self.assertLess(pred.key_support, pred.key_resistance)

    def test_predict_drivers_and_risks(self):
        from stock_researcher.prediction_v1100 import predict_horizon
        # 高波动 → 应有风险提示
        prices = [100 + (i % 10) * 5 for i in range(60)]
        pred = predict_horizon(prices, horizon="1M", vol_20d=35.0)
        self.assertGreater(len(pred.risk_factors), 0)

    def test_predict_to_dict(self):
        from stock_researcher.prediction_v1100 import predict_horizon
        prices = [100 + i for i in range(30)]
        pred = predict_horizon(prices, horizon="5d")
        d = pred.to_dict()
        self.assertIn("horizon", d)
        self.assertIn("direction", d)
        self.assertIn("probability", d)


class TestMultiHorizonPrediction(unittest.TestCase):
    """多周期预测测试。"""

    def test_predict_all_horizons(self):
        from stock_researcher.prediction_v1100 import predict_multi_horizon
        prices = [100 + i * 0.5 for i in range(120)]
        result = predict_multi_horizon("TEST", prices=prices)
        self.assertEqual(result.code, "TEST")
        # 默认返回全部 5 个周期
        for h in ("1d", "5d", "1M", "3M", "6M"):
            self.assertIn(h, result.horizons)

    def test_predict_specific_horizons(self):
        from stock_researcher.prediction_v1100 import predict_multi_horizon
        prices = [100 + i * 0.3 for i in range(60)]
        result = predict_multi_horizon("TEST", prices=prices, horizons=["1d", "5d"])
        self.assertEqual(len(result.horizons), 2)
        self.assertIn("1d", result.horizons)
        self.assertIn("5d", result.horizons)

    def test_predict_bullish_signal(self):
        from stock_researcher.prediction_v1100 import predict_multi_horizon
        # 强势上涨趋势
        prices = [100 + i * 1.0 for i in range(120)]
        result = predict_multi_horizon("TEST", prices=prices)
        self.assertEqual(result.overall_signal, "bullish")
        self.assertGreater(result.overall_confidence, 0.5)

    def test_predict_bearish_signal(self):
        from stock_researcher.prediction_v1100 import predict_multi_horizon
        prices = [200 - i * 1.0 for i in range(120)]
        result = predict_multi_horizon("TEST", prices=prices)
        self.assertEqual(result.overall_signal, "bearish")

    def test_predict_empty_prices_returns_degraded(self):
        from stock_researcher.prediction_v1100 import predict_multi_horizon
        result = predict_multi_horizon("EMPTY", prices=[])
        # 价格为空的预测应降级但仍返回结构
        self.assertEqual(result.code, "EMPTY")
        self.assertIn("1d", result.horizons)

    def test_predict_includes_disclaimer(self):
        from stock_researcher.prediction_v1100 import predict_multi_horizon
        result = predict_multi_horizon("TEST", prices=[100 + i for i in range(60)])
        self.assertIn("预测评分", result.disclaimer)

    def test_predict_to_dict_serializable(self):
        from stock_researcher.prediction_v1100 import predict_multi_horizon
        import json
        result = predict_multi_horizon("TEST", prices=[100 + i * 0.3 for i in range(60)])
        d = result.to_dict()
        # 应能 JSON 序列化
        json.dumps(d, ensure_ascii=False)


class TestProbabilityCalibration(unittest.TestCase):
    """概率校准测试。"""

    def test_calibrate_without_history_returns_raw(self):
        from stock_researcher.prediction_v1100 import calibrate_probability
        result = calibrate_probability(0.7, history=None)
        self.assertEqual(result.raw_probability, 0.7)
        self.assertEqual(result.calibrated_probability, 0.7)
        self.assertEqual(result.bucket, "no_history")

    def test_calibrate_with_history(self):
        from stock_researcher.prediction_v1100 import calibrate_probability
        # 模拟历史：raw=0.7 的预测，命中 60%
        history = [(0.7, True)] * 6 + [(0.7, False)] * 4
        result = calibrate_probability(0.7, history=history)
        self.assertEqual(result.bucket, "[0.6-0.8)")
        # 校准概率应接近经验频率 0.6
        self.assertGreater(result.calibrated_probability, 0.55)
        self.assertLess(result.calibrated_probability, 0.75)

    def test_calibrate_different_buckets(self):
        from stock_researcher.prediction_v1100 import calibrate_probability
        # raw=0.2 → bucket [0.2-0.4)
        result = calibrate_probability(0.25, history=[(0.25, True)] * 3)
        self.assertEqual(result.bucket, "[0.2-0.4)")


class TestV11PredictSelfCheck(unittest.TestCase):
    """自检测试。"""

    def test_self_check(self):
        from stock_researcher.prediction_v1100 import self_check
        result = self_check()
        self.assertEqual(result["version"], "v11.0")
        self.assertIn("horizon_days", result)
        self.assertIn("horizon_weights", result)
        self.assertIn("sample_test", result)
        self.assertEqual(len(result["horizon_days"]), 5)


if __name__ == "__main__":
    unittest.main()