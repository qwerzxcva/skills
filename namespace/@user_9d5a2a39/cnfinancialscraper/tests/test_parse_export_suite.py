# -*- coding: utf-8 -*-
"""解析/导出/行情层合并测试（原 7 个测试文件合并，减少文件数）：
- docx_picture：report_exporter export_with_images / MarkdownExporter
- zip_utf8：crawl_packager 中文文件名 ZIP
- html2md：块级/行内/表格/图片/代码/边界
- markdown_exporter：单文件/批量/ZIP/中文文件名
- web_parser：产品解析与财务指标抽取
- bse_scraper：北交所数据（mock，无网络）
- market_data_scraper：LPR / 国债收益率曲线（mock，无网络）
"""
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts.report_exporter import WordExporter, MarkdownExporter as _WordMdExporter
from scripts.crawl_packager import _write_zip_utf8, set_zip_encoding, package_with_images
from scripts.html2md import convert, convert_with_tables
from scripts.markdown_exporter import (MarkdownExporter, export_to_markdown,
                                       batch_to_markdown, _safe_filename)
from scripts.web_parser import (extract_financial_metrics,
                                format_product_summary,
                                parse_product_from_html)


# ════════════ A. docx_picture：WordExporter 图片导出 ════════════

class TestWordExporterWithImages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # 准备测试图片（1x1 PNG）
        png_data = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa3\x8b\x80\x00\x00\x00"
            b"\x00IEND\xaeB`\x82"
        )
        self.img_path = Path(self.tmp) / "test.png"
        self.img_path.write_bytes(png_data)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_export_with_images_md_fallback(self):
        # 即使没装 python-docx，fallback 也能写 MD
        we = WordExporter()
        data = {
            "title": "测试报告",
            "metadata": {"source": "财联社", "date": "2026-07-29"},
            "sections": [
                {"heading": "一、引言", "level": 1,
                 "paragraphs": ["这是引言段落"],
                 "images": [{"path": str(self.img_path), "caption": "测试图"}]},
                {"heading": "二、结论", "level": 1,
                 "paragraphs": ["这是结论段落"],
                 "images": []},
            ]
        }
        out = we.export_with_images(data, output_path=str(Path(self.tmp) / "out.docx"))
        self.assertTrue(Path(out).exists())

    def test_markdown_exporter_basic(self):
        me = _WordMdExporter(output_dir=self.tmp)
        data = {"title": "测试", "source": "财联社",
                "content": "<h2>子标题</h2><p>正文</p>"}
        out = me.export(data)
        self.assertTrue(Path(out).exists())
        text = Path(out).read_text(encoding="utf-8")
        self.assertIn("测试", text)
        self.assertIn("财联社", text)


# ════════════ B. zip_utf8：中文文件名 ZIP ════════════

class TestWriteZipUtf8(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ascii_filename_no_extra(self):
        # 纯 ASCII 不应附加 extra 字段
        f = Path(self.tmp) / "ascii.txt"
        f.write_text("hello", encoding="utf-8")
        zip_path = Path(self.tmp) / "out.zip"
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            _write_zip_utf8(zf, str(f), "ascii.txt")
        # 验证能正常读取
        with zipfile.ZipFile(zip_path) as zf:
            self.assertIn("ascii.txt", zf.namelist())

    def test_chinese_filename_preserved(self):
        f = Path(self.tmp) / "源.txt"
        f.write_text("数据", encoding="utf-8")
        zip_path = Path(self.tmp) / "out.zip"
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            _write_zip_utf8(zf, str(f), "源文件.txt")
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            # 中文文件名应保留
            self.assertTrue(any("源文件" in n for n in names), f"中文丢失: {names}")


class TestPackageWithImages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_basic(self):
        # 模拟有图片的内容
        img_dir = Path(self.tmp) / "imgs"
        img_dir.mkdir()
        img = img_dir / "测试.png"
        img.write_bytes(b"\x89PNG fake image data")

        items = [
            {"name": "新闻1", "content": "正文1", "image_map": {"https://x/a.png": str(img)}},
            {"name": "新闻2", "content": "正文2", "image_map": {}},
        ]
        zip_path = package_with_images(items, zip_name="中文测试",
                                       output_dir=self.tmp)
        self.assertTrue(Path(zip_path).exists())
        # 验证包含中文图片名
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            self.assertTrue(any("测试" in n for n in names))


class TestSetZipEncoding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fix_zip(self):
        # 创建一个中文 ZIP
        f = Path(self.tmp) / "原.txt"
        f.write_text("内容", encoding="utf-8")
        zip_path = Path(self.tmp) / "src.zip"
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("原文件.txt", "数据")
        # 修复
        fixed = set_zip_encoding(str(zip_path))
        self.assertTrue(Path(fixed).exists())
        with zipfile.ZipFile(fixed) as zf:
            names = zf.namelist()
            self.assertEqual(len(names), len(set(names)),
                             f"修复后的 ZIP 不应包含重复条目: {names}")
            self.assertEqual(names.count("原文件.txt"), 1)


# ════════════ C. html2md：HTML → Markdown 转换 ════════════

class TestHtml2MdBasic(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(convert(""), "")
        self.assertEqual(convert(None), "")

    def test_paragraph(self):
        md = convert("<p>hello world</p>")
        self.assertIn("hello world", md)

    def test_headings(self):
        for i in range(1, 7):
            md = convert(f"<h{i}>标题</h{i}>")
            self.assertIn(f"{'#' * i} 标题", md)

    def test_bold_italic(self):
        md = convert("<p><strong>bold</strong> and <em>italic</em></p>")
        self.assertIn("**bold**", md)
        self.assertIn("*italic*", md)

    def test_link(self):
        md = convert('<a href="https://example.com">链接</a>')
        self.assertIn("[链接](https://example.com)", md)

    def test_image_with_map(self):
        md = convert('<img src="https://x.com/a.png" alt="图">',
                     image_map={"https://x.com/a.png": "./a.png"})
        self.assertIn("![图](./a.png)", md)

    def test_image_without_map(self):
        md = convert('<img src="https://x.com/a.png" alt="图">')
        self.assertIn("![图](https://x.com/a.png)", md)

    def test_line_break(self):
        md = convert("a<br>b")
        self.assertIn("a\nb", md)

    def test_horizontal_rule(self):
        md = convert("<hr>")
        self.assertIn("---", md)

    def test_drop_script(self):
        md = convert("<p>前<script>alert(1)</script>后</p>")
        self.assertNotIn("alert", md)
        self.assertIn("前后", md)

    def test_drop_style(self):
        md = convert("<style>body{}</style><p>内容</p>")
        self.assertNotIn("body", md)
        self.assertIn("内容", md)

    def test_blockquote(self):
        md = convert("<blockquote>引用文字</blockquote>")
        self.assertIn("引用文字", md)

    def test_unordered_list(self):
        md = convert("<ul><li>a</li><li>b</li></ul>")
        self.assertIn("- a", md)
        self.assertIn("- b", md)

    def test_ordered_list(self):
        md = convert("<ol><li>a</li><li>b</li></ol>")
        self.assertIn("1. a", md)
        self.assertIn("1. b", md)


class TestHtml2MdCode(unittest.TestCase):
    def test_inline_code(self):
        md = convert("<p>看 <code>x</code> 变量</p>")
        self.assertIn("`x`", md)

    def test_pre_block(self):
        md = convert("<pre>print('hi')</pre>")
        self.assertIn("```", md)
        self.assertIn("print('hi')", md)

    def test_pre_with_language(self):
        md = convert('<pre><code class="language-python">print(1)</code></pre>')
        self.assertIn("```python", md)


class TestHtml2MdTable(unittest.TestCase):
    def test_simple_table(self):
        html = ('<table><thead><tr><th>A</th><th>B</th></tr></thead>'
                '<tbody><tr><td>1</td><td>2</td></tr></tbody></table>')
        md = convert_with_tables(html)
        self.assertIn("| A | B |", md)
        self.assertIn("| --- | --- |", md)
        self.assertIn("| 1 | 2 |", md)

    def test_table_with_pipe_in_cell(self):
        html = ('<table><thead><tr><th>标题</th></tr></thead>'
                '<tbody><tr><td>有|竖线</td></tr></tbody></table>')
        md = convert_with_tables(html)
        # | 应被转义
        self.assertIn("\\|", md)


class TestHtml2MdEdge(unittest.TestCase):
    def test_relative_url_resolved(self):
        md = convert('<a href="/page">链接</a>', base_url="https://x.com")
        self.assertIn("https://x.com/page", md)

    def test_already_absolute(self):
        md = convert('<a href="https://y.com/p">x</a>', base_url="https://x.com")
        self.assertIn("https://y.com/p", md)

    def test_nested_strong_in_link(self):
        md = convert('<a href="https://x.com"><strong>重点</strong></a>')
        self.assertIn("**重点**", md)
        self.assertIn("https://x.com", md)

    def test_iframe_to_text(self):
        md = convert('<iframe src="https://x.com/embed"></iframe>')
        self.assertIn("[iframe:", md)
        self.assertIn("x.com/embed", md)

    def test_unclosed_tag_tolerant(self):
        # 容错：未闭合的 <p> 不应崩
        md = convert("<p>hello")
        self.assertIn("hello", md)

    def test_html_entities_decoded(self):
        # html.parser 默认 decode entity；这是预期行为
        md = convert("<p>5 &lt; 10 &amp; true</p>")
        self.assertIn("5 < 10", md)
        self.assertIn("& true", md)


class TestHtml2MdWhitespace(unittest.TestCase):
    def test_multiple_newlines_collapsed(self):
        md = convert("<p>a</p>\n\n\n\n<p>b</p>")
        # 不应超过 2 个连续换行
        self.assertNotIn("\n\n\n", md)

    def test_whitespace_in_text_collapsed(self):
        md = convert("<p>hello     world</p>")
        self.assertIn("hello world", md)


# ════════════ D. markdown_exporter：单文件/批量/合并/ZIP ════════════

class TestSafeFilename(unittest.TestCase):
    def test_chinese_kept(self):
        self.assertEqual(_safe_filename("贵州茅台"), "贵州茅台")

    def test_illegal_chars_replaced(self):
        self.assertEqual(_safe_filename('a/b\\c:d*e?f"g<h>i|j'), "a_b_c_d_e_f_g_h_i_j")

    def test_empty_safe(self):
        self.assertEqual(_safe_filename(""), "untitled")

    def test_whitespace_normalized(self):
        self.assertEqual(_safe_filename("a  b\tc"), "a_b_c")


class TestSingleExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.exp = MarkdownExporter(output_dir=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_html_content_converted(self):
        data = {
            "title": "测试标题",
            "source": "财联社",
            "url": "https://x.com",
            "published_at": "2026-07-29",
            "content": "<h2>子标题</h2><p>正文内容</p>",
        }
        path = self.exp.export(data)
        self.assertTrue(Path(path).exists())
        text = Path(path).read_text(encoding="utf-8")
        self.assertIn("# 测试标题", text)
        self.assertIn("## 子标题", text)
        self.assertIn("正文内容", text)
        self.assertIn("**来源**: 财联社", text)

    def test_md_content_kept(self):
        data = {
            "title": "MD 测试",
            "content": "# Already MD\n\n正文",
        }
        path = self.exp.export(data)
        text = Path(path).read_text(encoding="utf-8")
        # 原始 MD 不应被二次转换
        self.assertIn("# Already MD", text)


class TestBatchExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.exp = MarkdownExporter(output_dir=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_batch_creates_structure(self):
        items = [
            {"title": "新闻1", "source": "财联社", "content": "<p>c1</p>"},
            {"title": "新闻2", "source": "新华财经", "content": "<p>c2</p>"},
        ]
        res = self.exp.build_batch_export(items, batch_id="b1")
        self.assertEqual(res["count"], "2")
        self.assertTrue(Path(res["dir"]).exists())
        self.assertTrue(Path(res["index"]).exists())
        self.assertTrue(Path(res["metadata"]).exists())
        self.assertTrue(Path(res["zip"]).exists())

        # 索引文件应包含目录
        idx_text = Path(res["index"]).read_text(encoding="utf-8")
        self.assertIn("新闻1", idx_text)
        self.assertIn("财联社", idx_text)

    def test_chinese_filename_in_zip(self):
        items = [{"title": "中文测试", "source": "测试媒体", "content": "<p>x</p>"}]
        res = self.exp.build_batch_export(items, batch_id="中文批次")
        with zipfile.ZipFile(res["zip"]) as zf:
            names = zf.namelist()
            # 中文应保留
            self.assertTrue(any("测试媒体" in n for n in names), f"中文文件名丢失: {names}")


class TestMergeMd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.exp = MarkdownExporter(output_dir=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_merge_with_toc(self):
        # 先创建 2 个 MD 文件
        f1 = self.exp.export({"title": "文章甲", "content": "<p>内容甲</p>"})
        f2 = self.exp.export({"title": "文章乙", "content": "<p>内容乙</p>"})
        merged = self.exp.merge_files([f1, f2], f"{self.tmp}/merged.md", toc=True)
        text = Path(merged).read_text(encoding="utf-8")
        self.assertIn("# 合并报告", text)
        self.assertIn("## 目录", text)
        self.assertIn("文章甲", text)
        self.assertIn("文章乙", text)


class TestZipEncoding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_zip_round_trip_chinese(self):
        # 写入中文文件名的 MD
        md = Path(self.tmp) / "中文文档.md"
        md.write_text("# 测试", encoding="utf-8")
        # 创建 media 目录
        media = Path(self.tmp) / "media"
        media.mkdir()
        img = media / "图片.png"
        img.write_bytes(b"\x89PNG fake")

        zip_path = Path(self.tmp) / "out.zip"
        exp = MarkdownExporter(output_dir=self.tmp)
        exp.generate_zip(str(md), media_dir=str(media), zip_path=str(zip_path))

        # 重新打开 ZIP 验证
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            # 中文文件名应保留（可能路径前缀不同）
            all_text = " ".join(names)
            self.assertIn("中文文档", all_text)
            self.assertIn("图片.png", all_text)


# ════════════ E. web_parser：产品解析与财务指标 ════════════

class TestExtractFinancialMetrics:
    """Test extract_financial_metrics function"""

    def test_extracts_return_1m(self):
        text = "近1月收益率：5.23% 近3月收益率：12.5%"
        metrics = extract_financial_metrics(text)
        assert "return_1m" in metrics
        assert metrics["return_1m"] == 5.23

    def test_extracts_return_3m(self):
        text = "近3月收益: -3.14%"
        metrics = extract_financial_metrics(text)
        assert "return_3m" in metrics
        assert metrics["return_3m"] == -3.14

    def test_extracts_return_6m(self):
        text = "近6月收益率: 8.5"
        metrics = extract_financial_metrics(text)
        assert "return_6m" in metrics
        assert metrics["return_6m"] == 8.5

    def test_extracts_return_1y(self):
        text = "近1年收益率: 15.67%"
        metrics = extract_financial_metrics(text)
        assert "return_1y" in metrics
        assert metrics["return_1y"] == 15.67

    def test_extracts_return_3y(self):
        text = "近3年收益率： 45.2%"
        metrics = extract_financial_metrics(text)
        assert "return_3y" in metrics
        assert metrics["return_3y"] == 45.2

    def test_extracts_return_ytd(self):
        text = "今年来收益率: +8.91%"
        metrics = extract_financial_metrics(text)
        assert "return_ytd" in metrics
        assert metrics["return_ytd"] == 8.91

    def test_extracts_negative_values(self):
        text = "近1月收益率: -2.5% 近1年收益：-10.3"
        metrics = extract_financial_metrics(text)
        assert metrics["return_1m"] == -2.5
        assert metrics["return_1y"] == -10.3

    def test_handles_empty_text(self):
        metrics = extract_financial_metrics("")
        assert isinstance(metrics, dict)

    def test_handles_text_without_metrics(self):
        metrics = extract_financial_metrics("这是一段无关文本，没有任何收益率数据")
        assert metrics == {} or all(v is not None for v in metrics.values())

    def test_handles_multiple_colon_formats(self):
        """Test both ： (full-width) and : (half-width) colons"""
        text = "近1月收益率: 3.21% 近3月收益： 7.89%"
        metrics = extract_financial_metrics(text)
        assert metrics.get("return_1m") == 3.21
        assert metrics.get("return_3m") == 7.89

    def test_handles_no_percent_sign(self):
        text = "近1月收益: 5.5"
        metrics = extract_financial_metrics(text)
        assert metrics.get("return_1m") == 5.5


class TestFormatProductSummary:
    """Test format_product_summary function"""

    def test_formats_fund_summary(self):
        info = {
            "product_name": "华夏成长混合",
            "product_code": "000001",
            "product_type": "混合型",
            "nav": "1.2345",
            "fund_manager": "张三",
            "fund_company": "华夏基金",
        }
        summary = format_product_summary(info)
        assert isinstance(summary, str)
        assert "华夏成长混合" in summary
        assert "000001" in summary

    def test_handles_minimal_info(self):
        info = {"product_name": "测试基金"}
        summary = format_product_summary(info)
        assert "测试基金" in summary

    def test_handles_empty_dict(self):
        summary = format_product_summary({})
        assert isinstance(summary, str)


class TestParseProductFromHtml:
    """Test parse_product_from_html function"""

    def test_unsupported_type_returns_error(self):
        result = parse_product_from_html("<html></html>", "unsupported_type")
        assert "error" in result
        assert "不支持" in result["error"]

    def test_fund_type_does_not_crash_on_empty_html(self):
        """parse_product_from_html should handle minimal HTML gracefully"""
        result = parse_product_from_html("<html><body><h1>Test</h1></body></html>", "fund")
        assert isinstance(result, dict)
        # Should not raise; may return empty or error result

    def test_etf_type_does_not_crash(self):
        result = parse_product_from_html("<html></html>", "etf")
        assert isinstance(result, dict)

    def test_stock_type_does_not_crash(self):
        result = parse_product_from_html("<html></html>", "stock")
        assert isinstance(result, dict)

    def test_fof_type_does_not_crash(self):
        result = parse_product_from_html("<html></html>", "fof")
        assert isinstance(result, dict)

    def test_advisor_type_does_not_crash(self):
        result = parse_product_from_html("<html></html>", "advisor")
        assert isinstance(result, dict)


# ════════════ F. bse_scraper：北交所数据（mock） ════════════

class TestBseStocks(unittest.TestCase):

    def _fake_em_data(self):
        return {"data": {"diff": [
            {"f12": "837592", "f14": "华信永道", "f13": "837592",
             "f26": "2023-02-16", "f100": "信息技术", "f2": 12.5},
        ]}}

    def test_parse_em_fallback(self):
        """北交所原生接口失败时应降级到东方财富并正确解析。"""
        from exchange_scraper import get_bse_stocks
        # 原生接口返回异常参数错误
        with mock.patch("exchange_scraper._fetch_bse_native", return_value=None), \
             mock.patch("exchange_scraper._fetch_em_bse_stocks",
                        return_value=self._fake_em_data()["data"]["diff"] and [{
                            "code": "837592", "name": "华信永道",
                            "short_code": "837592", "listing_date": "2023-02-16",
                            "industry": "信息技术", "market": "bj",
                        }]):
            r = get_bse_stocks(limit=10)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["code"], "837592")
        self.assertEqual(r[0]["name"], "华信永道")
        self.assertEqual(r[0]["market"], "bj")

    def test_empty_on_failure_bse(self):
        from exchange_scraper import get_bse_stocks
        with mock.patch("exchange_scraper._fetch_bse_native", return_value=None), \
             mock.patch("exchange_scraper._fetch_em_bse_stocks", return_value=[]):
            self.assertEqual(get_bse_stocks(), [])

    def test_parse_native_bse(self):
        """北交所原生接口正常返回时应直接解析。"""
        from exchange_scraper import get_bse_stocks
        native = '[{"xxzqdm":"837592","jc":"华信永道","ssrq":"2023-02-16","hy":"信息技术"}]'
        with mock.patch("exchange_scraper._fetch_bse_native", return_value=native):
            r = get_bse_stocks()
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["code"], "837592")
        self.assertEqual(r[0]["name"], "华信永道")


class TestBseIpo(unittest.TestCase):

    def test_parse_native_ipo(self):
        from exchange_scraper import get_bse_ipo
        native = '[{"xxzqdm":"920001","jc":"某北交所公司","zt":"已注册","sxrq":"2026-07-31"}]'
        with mock.patch("exchange_scraper._fetch_bse_native", return_value=native):
            r = get_bse_ipo(limit=10)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["code"], "920001")
        self.assertEqual(r[0]["status"], "已注册")
        self.assertEqual(r[0]["market"], "bj")

    def test_empty_on_failure_ipo(self):
        from exchange_scraper import get_bse_ipo
        with mock.patch("exchange_scraper._fetch_bse_native", return_value=None), \
             mock.patch("exchange_scraper.get_ipo_calendar", return_value=[]):
            self.assertEqual(get_bse_ipo(), [])


# ════════════ G. market_data_scraper：LPR / 国债收益率曲线 ════════════

class TestLprRates(unittest.TestCase):

    def test_parse(self):
        from market_data_scraper import get_lpr_rates
        records = [
            {"showDateCN": "2026-07-20", "1Y": "3.00", "5Y": "3.50"},
            {"showDateCN": "2026-06-22", "1Y": "3.45", "5Y": "3.95"},
        ]
        with mock.patch("market_data_scraper._requests.post") as m:
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"records": records}
            m.return_value = resp
            r = get_lpr_rates(days=90)
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0]["date"], "2026-07-20")
        self.assertEqual(r[0]["one_year"], 3.0)
        self.assertEqual(r[0]["five_year"], 3.5)

    def test_empty_on_failure_lpr(self):
        from market_data_scraper import get_lpr_rates
        with mock.patch("market_data_scraper._requests.post") as m:
            m.side_effect = Exception("网络错误")
            self.assertEqual(get_lpr_rates(), [])


class TestBondYieldCurve(unittest.TestCase):

    def _fake_data(self):
        # 模拟 inityc 返回：索引→期限代码 + 数值列表（含完整曲线 seriesData）
        codes = {"3": "R01Y", "11": "R02Y", "13": "R03Y", "4": "R05Y",
                 "0": "R07Y", "1": "R10Y", "2": "R30Y"}
        series = []
        # 生成 0-30 年曲线，收益率从 1.0 线性到 3.0
        for year in range(0, 301):
            y = year / 10.0
            series.append([y, 1.0 + y * 0.05])
        curve_obj = {"seriesData": series, "worktime": "2026-07-31",
                     "ycDefName": "中债国债收益率曲线(到期)"}
        return [codes, [10, [curve_obj]]]

    def test_parse_terms(self):
        from market_data_scraper import get_bond_yield_curve
        with mock.patch("market_data_scraper._requests.post") as m:
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.json.return_value = self._fake_data()
            m.return_value = resp
            r = get_bond_yield_curve()
        self.assertEqual(r["date"], "2026-07-31")
        self.assertIn("1Y", r["terms"])
        self.assertIn("10Y", r["terms"])
        self.assertIn("30Y", r["terms"])
        # 1Y 收益 ≈ 1.0 + 1*0.05 = 1.05
        self.assertAlmostEqual(r["terms"]["1Y"], 1.05, places=2)
        # 利差
        self.assertIn("spread_10_2", r)

    def test_error_response(self):
        from market_data_scraper import get_bond_yield_curve
        with mock.patch("market_data_scraper._requests.post") as m:
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.json.return_value = [{"11": "R01Y"}, [10, []]]
            m.return_value = resp
            r = get_bond_yield_curve()
        self.assertIn("warning", r)  # 曲线数据为空时应返回警告

    def test_network_failure(self):
        from market_data_scraper import get_bond_yield_curve
        with mock.patch("market_data_scraper._requests.post") as m:
            m.side_effect = Exception("超时")
            r = get_bond_yield_curve()
        self.assertIn("error", r)


class TestDateNormalize(unittest.TestCase):

    def test_normalize(self):
        from market_data_scraper import _normalize_date
        self.assertEqual(_normalize_date("2026/7/1"), "2026-07-01")
        self.assertEqual(_normalize_date("2026-07-31 00:00:00"), "2026-07-31")
        self.assertEqual(_normalize_date(""), "")
        self.assertEqual(_normalize_date(None), "")


if __name__ == "__main__":
    unittest.main()
