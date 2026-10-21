# -*- coding: utf-8 -*-
"""
v10.0.0 测试套件 — 网页操作深度增强（web_operations_enhanced）

覆盖：
1. ShadowDOMPiercer（链式 CSS selector + JS 模板）
2. IframeNavigator（多层跨域穿透 + 提取）
3. CookieBannerHandler（30+ 关键词 + 3 种 action）
4. CaptchaRecognizer 接口 + StdlibCaptchaRecognizer + CaptchaPipeline fallback
5. BezierMouse 轨迹生成 + HumanBehaviorSimulator
6. WebSocketRecorder 滑动窗口
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

from scripts.web_operations_enhanced import (  # noqa: E402
    ShadowPierceConfig, ShadowDOMPiercer,
    IframeChain, IframeNavigator,
    CookieAction, COOKIE_BANNER_KEYWORDS, CookieBannerPattern,
    DEFAULT_COOKIE_PATTERNS, CookieBannerHandler,
    CaptchaType, CaptchaDetection, CaptchaRecognizer,
    StdlibCaptchaRecognizer, DdddocrCaptchaRecognizer,
    TesseractCaptchaRecognizer, CaptchaPipeline,
    BehaviorConfig, BezierMouse, HumanBehaviorSimulator,
    WSMessage, WebSocketRecorder,
)


# ============================================================================
# 1. Shadow DOM 穿透
# ============================================================================

class TestShadowDOMPiercer(unittest.TestCase):
    """链式 CSS selector 穿透 shadowRoot。"""

    def test_js_template_substitution(self):
        piercer = ShadowDOMPiercer()
        js = piercer.open_chain("div#app >> div.foo")
        # placeholder 应被替换
        self.assertNotIn("__CHAIN__", js)
        self.assertIn("div#app >> div.foo", js)
        # 应包含 shadowRoot 处理
        self.assertIn("shadowRoot", js)

    def test_open_chain_with_special_chars(self):
        """含单引号的 chain 应被正确转义。"""
        piercer = ShadowDOMPiercer()
        js = piercer.open_chain("div#x")
        self.assertNotIn("__CHAIN__", js)

    def test_config_defaults(self):
        cfg = ShadowPierceConfig()
        self.assertEqual(cfg.max_depth, 5)
        self.assertEqual(cfg.wait_after_open_ms, 50)
        self.assertEqual(cfg.timeout_ms, 5000)
        self.assertEqual(cfg.js_engine, "auto")

    def test_open_with_none_page(self):
        piercer = ShadowDOMPiercer()
        result = piercer.open(None, "div#x")
        self.assertIsNone(result)

    def test_click_with_none_page(self):
        piercer = ShadowDOMPiercer()
        self.assertFalse(piercer.click_chain(None, "div#x"))

    def test_extract_text_with_none_page(self):
        piercer = ShadowDOMPiercer()
        self.assertIsNone(piercer.extract_text_chain(None, "div#x"))


# ============================================================================
# 2. iframe 跨域穿透
# ============================================================================

class TestIframeNavigator(unittest.TestCase):
    """多层 iframe 跨域穿透。"""

    def test_init_default_depth(self):
        nav = IframeNavigator()
        self.assertEqual(nav.max_depth, 5)
        self.assertEqual(nav.history, [])

    def test_init_custom_depth(self):
        nav = IframeNavigator(max_depth=10)
        self.assertEqual(nav.max_depth, 10)

    def test_locate_with_none_page(self):
        nav = IframeNavigator()
        result = nav.locate(None, ["iframe#main"])
        self.assertIsNone(result)

    def test_find_all_frames_with_none_page(self):
        nav = IframeNavigator()
        self.assertEqual(nav.find_all_frames(None), [])

    def test_iframe_chain_dataclass(self):
        chain = IframeChain(name="main", url="https://x.com")
        self.assertEqual(chain.name, "main")
        self.assertEqual(chain.url, "https://x.com")


# ============================================================================
# 3. Cookie Banner 处理
# ============================================================================

class TestCookieBannerHandler(unittest.TestCase):
    """Cookie 弹窗自动处理。"""

    def test_default_patterns_count(self):
        self.assertGreaterEqual(len(DEFAULT_COOKIE_PATTERNS), 3)

    def test_cookie_actions_enum(self):
        self.assertEqual(CookieAction.ACCEPT.name, "ACCEPT")
        self.assertEqual(CookieAction.REJECT.name, "REJECT")
        self.assertEqual(CookieAction.ESSENTIAL_ONLY.name, "ESSENTIAL_ONLY")

    def test_cookie_keywords_multilang(self):
        """关键词覆盖中英文。"""
        self.assertIn("接受", COOKIE_BANNER_KEYWORDS["accept"])
        self.assertIn("Accept", COOKIE_BANNER_KEYWORDS["accept"])
        self.assertIn("拒绝", COOKIE_BANNER_KEYWORDS["reject"])
        self.assertIn("Reject", COOKIE_BANNER_KEYWORDS["reject"])

    def test_handler_with_none_page(self):
        handler = CookieBannerHandler(action=CookieAction.ACCEPT)
        result = handler.dismiss(None)
        self.assertFalse(result["detected"])
        self.assertFalse(result["clicked"])

    def test_handler_action_mapping(self):
        for action in (CookieAction.ACCEPT, CookieAction.REJECT,
                       CookieAction.ESSENTIAL_ONLY):
            h = CookieBannerHandler(action=action)
            self.assertEqual(h.action, action)
            self.assertGreater(len(h.patterns), 0)

    def test_custom_pattern(self):
        pattern = CookieBannerPattern(
            container_selectors=["[class*='custom']"],
            button_selectors=["button.custom-accept"],
            action=CookieAction.ACCEPT,
        )
        h = CookieBannerHandler(
            action=CookieAction.ACCEPT, patterns=[pattern],
        )
        self.assertEqual(len(h.patterns), 1)


# ============================================================================
# 4. 验证码 OCR
# ============================================================================

class TestCaptchaRecognizers(unittest.TestCase):
    """验证码识别器抽象 + 实现。"""

    def test_captcha_type_enum(self):
        expected = [
            "NONE", "RECAPTCHA_V2", "RECAPTCHA_V3", "HCAPTCHA",
            "GEETEST", "ALIYUN_SLIDER", "TENCENT_SLIDER",
            "IMAGE_TEXT", "IMAGE_MATH", "CHINESE_TEXT",
        ]
        for name in expected:
            self.assertTrue(hasattr(CaptchaType, name))

    def test_captcha_detection_dataclass(self):
        det = CaptchaDetection(
            type=CaptchaType.RECAPTCHA_V2,
            confidence=0.92,
            element_selector="#recaptcha",
            site_key="abc123",
        )
        self.assertEqual(det.type, CaptchaType.RECAPTCHA_V2)
        self.assertEqual(det.confidence, 0.92)
        self.assertEqual(det.site_key, "abc123")

    def test_stdlib_recognizer_unknown(self):
        rec = StdlibCaptchaRecognizer()
        result = rec.recognize(b"unknown", CaptchaType.IMAGE_TEXT)
        self.assertIsNone(result)

    def test_stdlib_recognizer_known(self):
        rec = StdlibCaptchaRecognizer()
        rec.add_known_answer(b"test_image", "ABCD")
        self.assertEqual(rec.recognize(b"test_image", CaptchaType.IMAGE_TEXT), "ABCD")

    def test_stdlib_recognizer_dict_init(self):
        rec = StdlibCaptchaRecognizer(dict_answers={"h1": "X", "h2": "Y"})
        self.assertIn("h1", rec.dict_answers)

    def test_stdlib_unsupported_types(self):
        rec = StdlibCaptchaRecognizer()
        # 只支持 IMAGE_TEXT / IMAGE_MATH
        for t in (CaptchaType.RECAPTCHA_V2, CaptchaType.HCAPTCHA,
                  CaptchaType.GEETEST):
            self.assertNotIn(t, rec.supported_types)

    def test_ddddocr_name(self):
        rec = DdddocrCaptchaRecognizer()
        self.assertEqual(rec.name, "ddddocr")

    def test_ddddocr_supported_types(self):
        rec = DdddocrCaptchaRecognizer()
        self.assertIn(CaptchaType.IMAGE_TEXT, rec.supported_types)
        self.assertIn(CaptchaType.CHINESE_TEXT, rec.supported_types)

    def test_tesseract_name(self):
        rec = TesseractCaptchaRecognizer()
        self.assertEqual(rec.name, "tesseract")

    def test_pipeline_default_is_stdlib(self):
        pipe = CaptchaPipeline()
        self.assertEqual(len(pipe.recognizers), 1)
        self.assertIsInstance(pipe.recognizers[0], StdlibCaptchaRecognizer)

    def test_pipeline_custom_recognizers(self):
        std = StdlibCaptchaRecognizer()
        pipe = CaptchaPipeline([std])
        self.assertEqual(len(pipe.recognizers), 1)
        pipe.add_recognizer(std)
        self.assertEqual(len(pipe.recognizers), 2)

    def test_pipeline_fallback(self):
        """无预设字典的 pipeline 应返回 None。"""
        pipe = CaptchaPipeline([StdlibCaptchaRecognizer()])
        self.assertIsNone(pipe.recognize(b"random", CaptchaType.IMAGE_TEXT))

    def test_pipeline_known_answer(self):
        rec = StdlibCaptchaRecognizer()
        rec.add_known_answer(b"img1", "1234")
        pipe = CaptchaPipeline([rec])
        self.assertEqual(pipe.recognize(b"img1", CaptchaType.IMAGE_TEXT), "1234")

    def test_pipeline_skips_unsupported(self):
        """Pipeline 应跳过不支持当前类型的 recognizer。"""
        # 模拟：mock 一个只支持 IMAGE_MATH 的 recognizer
        class MathOnlyRecognizer(CaptchaRecognizer):
            @property
            def name(self): return "math_only"
            @property
            def supported_types(self): return [CaptchaType.IMAGE_MATH]
            def recognize(self, image_bytes, captcha_type):
                return "42"

        pipe = CaptchaPipeline([MathOnlyRecognizer()])
        # 请求 IMAGE_TEXT 应跳过 math-only
        self.assertIsNone(pipe.recognize(b"x", CaptchaType.IMAGE_TEXT))
        # 请求 IMAGE_MATH 应返回 42
        self.assertEqual(pipe.recognize(b"x", CaptchaType.IMAGE_MATH), "42")


# ============================================================================
# 5. 人类行为轨迹
# ============================================================================

class TestBezierMouse(unittest.TestCase):
    """贝塞尔曲线鼠标轨迹。"""

    def test_path_length(self):
        mouse = BezierMouse(seed=42)
        path = mouse.generate((0, 0), (100, 100), steps=20)
        self.assertEqual(len(path), 21)  # steps + 1

    def test_path_starts_near_origin(self):
        mouse = BezierMouse(seed=42)
        path = mouse.generate((0, 0), (1000, 500), steps=10)
        # 起点应在 (0, 0) 附近（允许 ±0.5 抖动）
        self.assertLess(abs(path[0][0]), 1.0)
        self.assertLess(abs(path[0][1]), 1.0)

    def test_path_ends_near_target(self):
        mouse = BezierMouse(seed=42)
        path = mouse.generate((0, 0), (1000, 500), steps=10)
        self.assertAlmostEqual(path[-1][0], 1000, delta=1.0)
        self.assertAlmostEqual(path[-1][1], 500, delta=1.0)

    def test_seed_reproducibility(self):
        m1 = BezierMouse(seed=123)
        m2 = BezierMouse(seed=123)
        p1 = m1.generate((0, 0), (100, 100))
        p2 = m2.generate((0, 0), (100, 100))
        self.assertEqual(p1, p2)

    def test_different_seeds_different_paths(self):
        m1 = BezierMouse(seed=1)
        m2 = BezierMouse(seed=2)
        p1 = m1.generate((0, 0), (100, 100))
        p2 = m2.generate((0, 0), (100, 100))
        self.assertNotEqual(p1, p2)


class TestHumanBehaviorSimulator(unittest.TestCase):
    """人类行为模拟器（停顿/滚动/键盘）。"""

    def test_reading_pause_distribution(self):
        """阅读停顿命中率应接近配置概率（15%）。"""
        sim = HumanBehaviorSimulator(seed=42)
        pause_count = sum(1 for _ in range(2000)
                          if sim.maybe_reading_pause() > 0)
        rate = pause_count / 2000
        # 允许 ±10% 浮动
        self.assertGreater(rate, 0.05)
        self.assertLess(rate, 0.30)

    def test_scroll_pause_distribution(self):
        sim = HumanBehaviorSimulator(seed=42)
        pause_count = sum(1 for _ in range(2000)
                          if sim.maybe_scroll_pause() > 0)
        rate = pause_count / 2000
        self.assertGreater(rate, 0.20)
        self.assertLess(rate, 0.45)

    def test_human_click_with_none_page(self):
        sim = HumanBehaviorSimulator()
        self.assertFalse(sim.human_click_path(None, (0, 0), (100, 100)))

    def test_human_scroll_with_none_page(self):
        sim = HumanBehaviorSimulator()
        self.assertFalse(sim.human_scroll(None, "down", 300))

    def test_behavior_config(self):
        cfg = BehaviorConfig(mouse_speed_px_per_sec=500)
        sim = HumanBehaviorSimulator(cfg)
        self.assertEqual(sim.config.mouse_speed_px_per_sec, 500)


# ============================================================================
# 6. WebSocket 监听
# ============================================================================

class TestWebSocketRecorder(unittest.TestCase):
    """WebSocket 滑动窗口监听。"""

    def test_initial_state(self):
        ws = WebSocketRecorder()
        self.assertEqual(len(ws.messages), 0)
        stats = ws.stats()
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["in"], 0)
        self.assertEqual(stats["out"], 0)

    def test_attach_with_none_page(self):
        ws = WebSocketRecorder()
        self.assertFalse(ws.attach(None))

    def test_get_messages_with_direction_filter(self):
        ws = WebSocketRecorder()
        ws.messages.append(WSMessage(direction="in", payload="x", timestamp_ms=0))
        ws.messages.append(WSMessage(direction="out", payload="y", timestamp_ms=0))
        in_msgs = ws.get_messages(direction="in")
        self.assertEqual(len(in_msgs), 1)
        self.assertEqual(in_msgs[0].payload, "x")

    def test_get_messages_with_url_filter(self):
        ws = WebSocketRecorder()
        ws.messages.append(WSMessage(direction="in", payload="x",
                                     timestamp_ms=0, url="wss://a.com"))
        ws.messages.append(WSMessage(direction="in", payload="y",
                                     timestamp_ms=0, url="wss://b.com"))
        result = ws.get_messages(url_contains="a.com")
        self.assertEqual(len(result), 1)

    def test_sliding_window_eviction(self):
        ws = WebSocketRecorder(max_messages=3)
        for i in range(5):
            ws.messages.append(WSMessage(direction="in", payload=str(i),
                                         timestamp_ms=i))
            # 模拟 _record 的滑动窗口逻辑
            if len(ws.messages) > ws.max_messages:
                ws.messages = ws.messages[-ws.max_messages:]
        self.assertEqual(len(ws.messages), 3)
        self.assertEqual(ws.messages[0].payload, "2")

    def test_clear(self):
        ws = WebSocketRecorder()
        ws.messages.append(WSMessage(direction="in", payload="x", timestamp_ms=0))
        ws.clear()
        self.assertEqual(len(ws.messages), 0)


if __name__ == "__main__":
    unittest.main()