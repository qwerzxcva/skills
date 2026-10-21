# -*- coding: utf-8 -*-
"""v7.5.0 升级回归测试 — 编码修复 + 下载加固 + 爬取强化 + 机构名单扩充

覆盖：
1. 编码检测：charset 归一化 / 声明编码验证 / meta charset 字节级探测 /
   中文启发式 / 域名编码记忆 / GBK JSON API 兼容
2. 爬取强化：SSL 证书失败协议降级重试 / 200 空响应自动重试
3. download_file 加固：Referer 注入 / 文本转码 UTF-8 / 反爬页校验 /
   GBK Content-Disposition 文件名乱码修复
4. announcement_scraper：无 requests 时标准库兜底下载 / GBK 文件名修复
5. 机构名单：6 类扩充名录落盘 / load_curated 路径修复 / registry ≥2334 家
全部离线（fake session 注入），不发网络请求。
"""
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

import http_utils as hu
from http_utils import (StdlibResponse, StdlibSession, normalize_charset,
                        remember_domain_encoding, get_domain_encoding,
                        looks_like_chinese_binary, _detect_meta_charset_bytes,
                        _is_ssl_error, _scheme_downgrade, _fix_mojibake_filename,
                        _looks_html_magic, _is_text_download, _extract_filename,
                        http_get, download_file)
import announcement_scraper as ann

SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SKILL_DIR / "data"


class FakeResp:
    """鸭子类型模拟 StdlibResponse（http_get 成功分支只读这些属性）"""
    def __init__(self, code=200, content=b"", headers=None, encoding="utf-8"):
        self.code = code
        self.content = content
        self.headers = headers or {}
        self._encoding = encoding
        self.text = content.decode(encoding, errors="replace")


class FakeSession:
    """按调用次序逐个弹出响应/异常的假 session"""
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, headers=None, timeout=30, **kw):
        self.calls.append({"url": url, "headers": dict(headers or {})})
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _no_sleep():
    """全量测试不等待重试退避"""
    with patch("http_utils.time.sleep"):
        yield


@pytest.fixture
def _clean_hints():
    saved = dict(hu.domain_encoding_hints)
    yield
    hu.domain_encoding_hints.clear()
    hu.domain_encoding_hints.update(saved)


# ════════════════ 1. charset 归一化与编码检测 ════════════════

class TestNormalizeCharset:
    def test_gb_family_unified_to_gb18030(self):
        for alias in ("gb2312", "GBK", "cp936", "x-gbk", "chinese"):
            assert normalize_charset(alias) == "gb18030"

    def test_aliases_and_case_insensitive(self):
        assert normalize_charset("UTF8") == "utf-8"
        assert normalize_charset(" iso-8859-1 ") == "latin-1"
        assert normalize_charset('"gbk"') == "gb18030"

    def test_invalid_returns_none(self):
        assert normalize_charset("not-a-charset-xxx") is None
        assert normalize_charset("") is None
        assert normalize_charset(None) is None


class TestDetectEncoding:
    def setup_method(self):
        self.s = StdlibSession()

    def detect(self, data, hdrs=None, url=""):
        return self.s._detect_encoding(200, hdrs or {}, data, url)

    def test_bom_utf8(self):
        assert self.detect(b"\xef\xbb\xbf<html></html>") == "utf-8"

    def test_declared_gb2312_normalized(self):
        data = "中国人民银行公告".encode("gb18030")
        assert self.detect(data, {"Content-Type": "text/html; charset=gb2312"}) == "gb18030"

    def test_declared_wrong_charset_not_blindly_trusted(self):
        """声称 utf-8 实为 GBK — 严格解码验证失败后启发式纠错"""
        data = "某信托公司发布年度财务报告".encode("gb18030")
        enc = self.detect(data, {"Content-Type": "text/html; charset=utf-8"})
        assert enc == "gb18030"
        assert data.decode(enc) == "某信托公司发布年度财务报告"

    def test_meta_charset_bytes_level(self):
        body = "基金净值公告".encode("gb18030")
        data = b'<html><head><meta charset="gb2312"></head>' + body
        assert self.detect(data, {}) == "gb18030"

    def test_heuristic_gbk_no_declaration(self):
        data = ("关于召开股东大会的通知，请各位股东准时出席。" * 3).encode("gb18030")
        assert self.detect(data, {}) == "gb18030"

    def test_heuristic_utf8_no_declaration(self):
        data = ("关于召开股东大会的通知，请各位股东准时出席。" * 3).encode("utf-8")
        assert self.detect(data, {}) == "utf-8"

    def test_binary_fallback_latin1(self):
        # 高位字节后跟空格（非 GBK 尾字节范围）→ 无法构成 GBK 双字节对，兜底 latin-1
        data = bytes([0x80, 0x20] * 8)
        assert self.detect(data, {}) == "latin-1"

    @pytest.mark.usefixtures("_clean_hints")
    def test_domain_memory_reuse(self):
        remember_domain_encoding("bank.example.cn", "gb18030")
        data = b"\xc4\xe3\xba\xc3"  # 即使歧义也直接复用记忆编码
        assert self.detect(data, {}, "http://bank.example.cn/list.htm") == "gb18030"

    def test_remember_skips_trivial_encodings(self, _clean_hints):
        remember_domain_encoding("a.example.cn", "latin-1")
        remember_domain_encoding("b.example.cn", "ascii")
        assert get_domain_encoding("a.example.cn") is None
        assert get_domain_encoding("b.example.cn") is None


class TestChineseHeuristic:
    def test_pure_ascii_is_utf8(self):
        assert looks_like_chinese_binary(b"hello world 123") == "utf-8"

    def test_gbk_bytes_detected(self):
        data = ("招商银行 平安银行 兴业银行 民生银行 " * 5).encode("gb18030")
        assert looks_like_chinese_binary(data) == "gb18030"

    def test_empty_returns_none(self):
        assert looks_like_chinese_binary(b"") is None

    def test_meta_bytes_detect_http_equiv(self):
        data = ('<meta http-equiv="Content-Type" content="text/html; charset=gbk">'
                "正文").encode("gb18030")
        assert _detect_meta_charset_bytes(data) == "gb18030"


class TestGBKJsonAPI:
    def test_json_loads_gbk_bytes(self):
        """json.loads 对 bytes 仅支持 utf-8/16/32 — GBK API 需先解码"""
        data = '{"name": "华夏基金", "code": "000001"}'.encode("gb18030")
        resp = StdlibResponse("http://a.cn/api", 200, {}, data, encoding="gb18030")
        assert resp.json() == {"name": "华夏基金", "code": "000001"}

    def test_json_utf8_unchanged(self):
        resp = StdlibResponse("http://a.cn/api", 200, {},
                              b'{"ok": true}', encoding="utf-8")
        assert resp.json() == {"ok": True}


# ════════════════ 2. 爬取强化：SSL 降级 + 空响应重试 ════════════════

class TestSSLHelpers:
    def test_is_ssl_error_variants(self):
        assert _is_ssl_error(ssl.SSLError(1, "[SSL] certificate verify failed"))
        assert _is_ssl_error(urllib.error.URLError(ssl.SSLError(1, "cert")))
        assert _is_ssl_error(urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED]"))
        assert not _is_ssl_error(urllib.error.URLError("timed out"))
        assert not _is_ssl_error(ValueError("not network"))

    def test_scheme_downgrade(self):
        assert _scheme_downgrade("https://a.cn/x") == "http://a.cn/x"
        assert _scheme_downgrade("http://a.cn/x") is None


class TestHttpGetHardening:
    def test_ssl_error_downgrades_to_http_once(self):
        ok = FakeResp(content=b"<html>ok</html>")
        fs = FakeSession([urllib.error.URLError(ssl.SSLError(1, "cert verify")), ok])
        resp = http_get("https://bank.example.cn/page", session=fs,
                        retries=3, use_cache=False)
        assert resp is ok
        assert fs.calls[0]["url"].startswith("https://")
        assert fs.calls[1]["url"] == "http://bank.example.cn/page"

    def test_non_ssl_error_no_downgrade(self):
        fs = FakeSession([urllib.error.URLError("timed out")] * 3)
        resp = http_get("https://slow.example.cn/", session=fs,
                        retries=3, use_cache=False)
        assert resp is None
        assert all(c["url"].startswith("https://") for c in fs.calls)

    def test_empty_body_retried_then_success(self):
        fs = FakeSession([FakeResp(content=b""), FakeResp(content=b"real body")])
        resp = http_get("http://empty.example.cn/", session=fs,
                        retries=3, use_cache=False)
        assert resp.content == b"real body"
        assert len(fs.calls) == 2

    def test_retry_empty_disabled(self):
        fs = FakeSession([FakeResp(content=b"")])
        resp = http_get("http://empty.example.cn/", session=fs,
                        retries=3, use_cache=False, retry_empty=False)
        assert resp.content == b""
        assert len(fs.calls) == 1

    def test_success_remembers_domain_encoding(self, _clean_hints):
        fs = FakeSession([FakeResp(content=b"<html>hi</html>", encoding="gb18030")])
        http_get("http://gbk.example.cn/", session=fs, retries=1, use_cache=False)
        assert get_domain_encoding("gbk.example.cn") == "gb18030"


# ════════════════ 3. download_file 加固 ════════════════

class TestDownloadHelpers:
    def test_html_magic(self):
        assert _looks_html_magic(b"<!DOCTYPE html><html>")
        assert _looks_html_magic(b"  <html>")
        assert not _looks_html_magic(b"%PDF-1.4")
        assert not _looks_html_magic(b"")

    def test_is_text_download(self):
        r1 = FakeResp(headers={"Content-Type": "text/html; charset=gb2312"})
        assert _is_text_download("x.bin", r1)
        r2 = FakeResp(headers={"Content-Type": "application/pdf"})
        assert _is_text_download("page.htm", r2)
        assert not _is_text_download("doc.pdf", r2)

    def test_fix_mojibake_filename_roundtrip(self):
        raw = "2026年年度报告.pdf".encode("gb18030").decode("latin-1")
        assert _fix_mojibake_filename(raw) == "2026年年度报告.pdf"

    def test_fix_mojibake_filename_keeps_ascii_and_real_cjk(self):
        assert _fix_mojibake_filename("report.pdf") == "report.pdf"
        assert _fix_mojibake_filename("正常中文.pdf") == "正常中文.pdf"
        assert _fix_mojibake_filename("") == ""

    def test_extract_filename_from_content_disposition_gbk(self):
        mangled = "分红公告.pdf".encode("gb18030").decode("latin-1")
        resp = FakeResp(headers={"Content-Disposition": f'filename="{mangled}"'})
        assert _extract_filename(resp, "http://a.cn/dl?id=1") == "分红公告.pdf"

    def test_extract_filename_utf8_star_form(self):
        resp = FakeResp(headers={
            "Content-Disposition": "attachment; filename*=UTF-8''%E6%B5%8B%E8%AF%95.pdf"})
        assert _extract_filename(resp, "http://a.cn/x") == "测试.pdf"


class TestDownloadFile:
    def test_referer_auto_injected(self, tmp_path):
        fs = FakeSession([FakeResp(content=b"%PDF-1.4 fake",
                                   headers={"Content-Type": "application/pdf"})])
        got = download_file("http://fund.example.cn/ann/1.pdf",
                            save_dir=str(tmp_path), session=fs, use_cache=False)
        assert got and Path(got).read_bytes() == b"%PDF-1.4 fake"
        assert fs.calls[0]["headers"].get("Referer") == "http://fund.example.cn/"

    def test_text_transcoded_to_utf8(self, tmp_path):
        gbk_html = "<html><body>基金净值公告：单位净值 1.234 元</body></html>"
        fs = FakeSession([FakeResp(content=gbk_html.encode("gb18030"),
                                   headers={"Content-Type": "text/html"},
                                   encoding="gb18030")])
        got = download_file("http://gbk.example.cn/page", save_dir=str(tmp_path),
                            filename="page.html", session=fs, use_cache=False)
        assert got is not None and got.endswith("page.html")
        text = Path(got).read_text(encoding="utf-8")
        assert "基金净值公告" in text and "1.234" in text

    def test_anti_crawl_html_not_saved_as_pdf(self, tmp_path):
        fs = FakeSession([FakeResp(content=b"<!DOCTYPE html><html>verify</html>",
                                   headers={"Content-Type": "application/pdf"})])
        got = download_file("http://x.example.cn/a.pdf", save_dir=str(tmp_path),
                            session=fs, use_cache=False)
        assert got is None
        assert list(tmp_path.iterdir()) == []

    def test_empty_body_not_saved(self, tmp_path):
        fs = FakeSession([FakeResp(content=b"")])
        got = download_file("http://x.example.cn/a.txt", save_dir=str(tmp_path),
                            session=fs, retries=1, use_cache=False)
        assert got is None


# ════════════════ 4. announcement_scraper 下载兜底 ════════════════

class TestAnnouncementDownload:
    def test_fix_gbk_filename_static(self):
        raw = "招募说明书.pdf".encode("gb18030").decode("latin-1")
        assert ann.PDFDownloader._fix_gbk_filename(raw) == "招募说明书.pdf"
        assert ann.PDFDownloader._fix_gbk_filename("abc.pdf") == "abc.pdf"

    def test_no_requests_session_falls_back_to_stdlib(self, tmp_path):
        dl = ann.PDFDownloader(download_dir=str(tmp_path))
        dl.session = None   # 模拟无 requests 环境
        save = tmp_path / "out.pdf"
        with patch.object(hu, "download_file", return_value=str(save)) as m:
            assert dl._download_file("http://a.cn/x.pdf", save) is True
        m.assert_called_once()
        kwargs = m.call_args.kwargs
        assert kwargs["save_dir"] == str(tmp_path)
        assert kwargs["filename"] == "out.pdf"

    def test_requests_exception_degrades_to_stdlib(self, tmp_path):
        dl = ann.PDFDownloader(download_dir=str(tmp_path))
        if dl.session is None:
            pytest.skip("requests 未安装，此分支由上一用例覆盖")
        save = tmp_path / "y.pdf"
        with patch.object(dl.session, "get", side_effect=ConnectionError("refused")), \
             patch.object(hu, "download_file", return_value=str(save)) as m:
            assert dl._download_file("http://a.cn/y.pdf", save) is True
        m.assert_called_once()


# ════════════════ 5. 机构名单扩充 ════════════════

EXPANDED_CATEGORIES = ["payment", "wm_subsidiary", "local_amc",
                       "internet_loan", "fund_sales", "credit_service"]


class TestInstitutionRoster:
    def test_curated_bundle_expanded_categories_present(self):
        bundle = json.loads((DATA_DIR / "curated.json").read_text(encoding="utf-8"))
        for cat in EXPANDED_CATEGORIES:
            items = bundle.get(cat)
            assert isinstance(items, list) and items, f"curated.json 缺少类别 {cat}"

    def test_load_curated_path_fix(self):
        """v7.5 回归修复：load_curated 必须能加载 data/curated.json
        （此前误指向已删除的 data/curated/ 目录导致返回空）"""
        import institution_expander as exp
        for cat in ("payment", "fund_sales", "local_amc"):
            items = exp.load_curated(cat)
            assert items and all(i.get("name") for i in items), \
                f"load_curated({cat}) 为空 — 精选名录路径回归未修复"

    def test_registry_total_after_expansion(self):
        reg = json.loads((DATA_DIR / "institution_registry.json")
                         .read_text(encoding="utf-8"))
        assert reg.get("_f") == "c"
        assert len(reg["d"]) >= 2334, "registry 机构总数应 ≥2334（v7.5 扩充后）"
        type_idx = reg["c"].index("type")
        types = {r[type_idx] for r in reg["d"]}
        assert len(types) >= 43
