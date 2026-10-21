# -*- coding: utf-8 -*-
"""
代理防护（国内直连守卫）— v9.6

🔴 重要限制：本工具全部数据源为腾讯财经/东方财富等国内接口，
开启代理/VPN（走海外 IP）反而会被数据源拒绝或超时。

策略：
1. detect_proxy_env() 检测环境变量中配置的系统代理；
2. ensure_direct_connection() 安装无代理 opener，让本进程内所有
   urllib.request.urlopen 请求绕过系统代理直连国内数据源（幂等）；
3. proxy_warning() / diagnose_network_error() 输出中文排障提示。

纯标准库，零依赖。
"""

import os
import urllib.request
import logging

logger = logging.getLogger(__name__)

# 常见代理环境变量（大小写均检测）
_PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
                   "https_proxy", "all_proxy")

_installed = False


def detect_proxy_env() -> dict:
    """检测环境变量中配置的代理，返回 {变量名: 值}（可能为空字典）。"""
    found = {}
    for k in _PROXY_ENV_KEYS:
        v = os.environ.get(k, "").strip()
        if v:
            found[k] = v
    return found


def ensure_direct_connection() -> bool:
    """安装无代理 opener，确保国内数据源直连（幂等）。

    腾讯/东财接口只接受国内直连，经代理出海会被拒绝。本进程所有
    urllib.request.urlopen 调用都会使用该 opener。

    Returns:
        True 本次完成安装；False 此前已安装（跳过）。
    """
    global _installed
    if _installed:
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    urllib.request.install_opener(opener)
    _installed = True
    logger.info("Installed no-proxy opener for domestic direct connection")
    return True


def is_direct_opener_active() -> bool:
    """当前全局 opener 是否已是无代理直连状态（供测试/自检使用）。
    注：Py3.11 下 ProxyHandler({}) 空代理表不会被 opener 保留，
    无 ProxyHandler 即直连。"""
    opener = urllib.request._opener
    if opener is None:
        return False
    for h in getattr(opener, "handlers", []):
        if isinstance(h, urllib.request.ProxyHandler):
            return not getattr(h, "proxies", {})
    return True


def proxy_warning() -> str:
    """检测到代理环境变量时返回中文警告；未检测到返回空字符串。"""
    proxies = detect_proxy_env()
    if not proxies:
        return ""
    names = ", ".join(sorted(set(k.upper() for k in proxies)))
    return (f"⚠️ 检测到系统代理（{names}）。数据源为腾讯/东财国内接口，"
            f"需国内直连，开代理/VPN 反而会失败。已自动切换直连模式，"
            f"若仍失败请关闭代理后重试。")


def diagnose_network_error(err) -> str:
    """根据网络错误与代理环境给出中文排障提示。"""
    msg = str(err or "").lower()
    proxies = detect_proxy_env()
    looks_proxy = ("proxy" in msg or "tunnel" in msg
                   or "proxyconnectionerror" in msg.replace(" ", ""))
    if proxies or looks_proxy:
        return ("疑似代理/VPN 干扰：数据源为腾讯/东财国内接口，需国内直连。"
                "请关闭代理（或为国内域名配置代理绕过）后重试")
    return "请检查网络连接是否正常"
