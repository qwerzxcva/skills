# -*- coding: utf-8 -*-
"""v9.4.0 语音交互 — Windows 零依赖 TTS/STT + 自然语言命令解析。

设计要点（与项目既有模块一致：纯函数 + 可注入依赖，测试不发网络请求）：
  1. TTS：优先 pyttsx3（可选）→ Windows SAPI（经 PowerShell 5.1，
     因 pwsh 7 未预装 System.Speech，必须显式调用 5.1 路径）→ 静默降级。
  2. STT：优先 vosk（可选离线模型）→ Windows SAPI 听写 → 不可用时
     VoiceResearchChat.run() 自动降级为文本输入循环。
  3. 命令引擎：parse_voice_command 把中文口语指令解析为
     (intent, code, params)，覆盖 预测/体检/板块排名/指数体制/
     情景分析/自上而下/大佬圆桌/知识库存取（v9.7）/帮助/退出 等意图。
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

__all__ = [
    "speak", "listen_once", "stt_available", "summarize_for_speech",
    "parse_voice_command", "VoiceResearchChat",
]

# PowerShell 5.1（Windows 自带，含 System.Speech 程序集；pwsh 7 无）
_PS51 = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

# 常见口语标的 → 标准代码
_CODE_ALIASES = {
    "茅台": "600519", "贵州茅台": "600519",
    "腾讯": "hk:00700", "宁德时代": "300750",
    "中国平安": "601318", "招商银行": "600036",
    "比亚迪": "002594", "五粮液": "000858",
    "上证指数": "idx:SSE", "上证": "idx:SSE", "大盘": "idx:SSE",
    "沪深300": "idx:HS300", "恒生指数": "idx:HSI", "恒指": "idx:HSI",
    "纳斯达克": "idx:IXIC", "纳指": "idx:IXIC",
    "标普": "idx:SPX", "标普500": "idx:SPX",
    "日经": "idx:N225", "黄金": "gold:comex", "原油": "crude:wti",
    "苹果": "us:AAPL", "英伟达": "us:NVDA", "特斯拉": "us:TSLA",
}

_MARKET_WORDS = {"a股": "cn", "港股": "hk", "美股": "us"}


# ─── TTS / STT ─────────────────────────────────────────────────────────────


def speak(text: str, engine: str = "auto", rate: int = 0) -> bool:
    """播报文本。engine: auto/pyttsx3/sapi/off。返回是否真实发声。"""
    if not text or engine == "off":
        return False
    if engine in ("auto", "pyttsx3"):
        try:
            import pyttsx3  # type: ignore
            eng = pyttsx3.init()
            if rate:
                try:
                    eng.setProperty("rate", max(80, min(300, 160 + rate * 20)))
                except Exception:
                    pass
            eng.say(text)
            eng.runAndWait()
            return True
        except Exception:
            if engine == "pyttsx3":
                return False
    # Windows SAPI 兜底（文本经临时文件传递，规避命令行转义问题）
    if os.name == "nt" and os.path.exists(_PS51):
        try:
            fd, tmp = tempfile.mkstemp(suffix=".txt", prefix="sr_voice_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            script = (
                "Add-Type -AssemblyName System.Speech; "
                f"$t = Get-Content -Raw -Encoding UTF8 '{tmp}'; "
                f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.Rate = {max(-10, min(10, rate))}; $s.Speak($t)"
            )
            subprocess.run([_PS51, "-NoProfile", "-Command", script],
                           timeout=max(30, len(text) // 5), check=False,
                           capture_output=True)
            return True
        except Exception:
            return False
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
    return False


def stt_available() -> bool:
    """语音识别是否可用（vosk 或 Windows SAPI 听写）。"""
    try:
        import vosk  # noqa: F401
        return True
    except Exception:
        pass
    return os.name == "nt" and os.path.exists(_PS51)


def listen_once(timeout: int = 8, engine: str = "auto") -> Optional[str]:
    """录一次音并转文字；失败/静音返回 None。"""
    if engine in ("auto", "vosk"):
        try:
            import vosk  # type: ignore
            import queue
            import sounddevice  # type: ignore
            model_dir = os.environ.get("VOSK_MODEL_PATH", "")
            if model_dir and os.path.isdir(model_dir):
                q: "queue.Queue[bytes]" = queue.Queue()

                def _cb(indata, frames, time_info, status):
                    q.put(bytes(indata))

                with sounddevice.RawInputStream(samplerate=16000, blocksize=8000,
                                                dtype="int16", channels=1,
                                                callback=_cb):
                    rec = vosk.KaldiRecognizer(vosk.Model(model_dir), 16000)
                    import time as _t
                    end = _t.time() + timeout
                    while _t.time() < end:
                        data = q.get()
                        if rec.AcceptWaveform(data):
                            import json as _json
                            txt = _json.loads(rec.Result()).get("text", "").strip()
                            if txt:
                                return txt
        except Exception:
            if engine == "vosk":
                return None
    # SAPI 听写兜底
    if os.name == "nt" and os.path.exists(_PS51):
        try:
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$r = New-Object System.Speech.Recognition.SpeechRecognitionEngine; "
                "$r.SetInputToDefaultAudioDevice; "
                "$r.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar)); "
                f"$res = $r.Recognize([TimeSpan]::FromSeconds({int(timeout)})); "
                "if ($res) { $res.Text }"
            )
            out = subprocess.run([_PS51, "-NoProfile", "-Command", script],
                                 timeout=timeout + 15, check=False,
                                 capture_output=True, text=True)
            txt = (out.stdout or "").strip()
            return txt or None
        except Exception:
            return None
    return None


# ─── 播报文本压缩 ───────────────────────────────────────────────────────────


def summarize_for_speech(reply: str, max_chars: int = 300) -> str:
    """把文本结果压缩为适合播报的口语文本。

    去 Markdown 记号/URL/表情，中文间空白压缩，超长截断到句尾并附提示。
    """
    if not reply:
        return ""
    txt = re.sub(r"```[\s\S]*?```", " 代码块省略 ", reply)
    txt = re.sub(r"https?://\S+", "", txt)
    txt = re.sub(r"[*#>`|_\-=~]+", " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    txt = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", txt)
    txt = txt.strip()
    if len(txt) <= max_chars:
        return txt
    cut = txt[:max_chars]
    for sep in ("。", "；", "，", " "):
        idx = cut.rfind(sep)
        if idx >= max_chars // 2:
            cut = cut[: idx + 1]
            break
    return cut.rstrip("，； ") + "（更多内容见终端输出）"


# ─── 自然语言命令解析 ───────────────────────────────────────────────────────


def parse_voice_command(text: str) -> Dict[str, Any]:
    """把口语指令解析为结构化命令。

    返回 {"intent": ..., "code": ..., "params": {...}, "echo": 确认语}。
    intent 取值: predict/quant_check/sector_ranking/index_regime/scenario/
    topdown/masters/kb_save/kb_search/kb_quant/help/exit/unknown。
    """
    s = (text or "").strip()
    low = s.lower()
    out: Dict[str, Any] = {"intent": "unknown", "code": None,
                           "params": {}, "echo": ""}
    if not s:
        return out
    if re.search(r"退出|再见|结束|停止|bye", s):
        out.update(intent="exit", echo="好的，已退出。")
        return out
    if re.search(r"帮助|怎么用|帮助我|使用说明|help", low):
        out.update(intent="help", echo="支持：预测某只股票、量化体检、板块排名、指数体制、情景分析、自上而下全景、大佬圆桌、保存分析到知识库、查询知识库。")
        return out

    # 1) 提取代码/别名
    code: Optional[str] = None
    for alias, std in sorted(_CODE_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if alias in s:
            code = std
            break
    if code is None:
        m = re.search(r"(?:代码|股票)?[:：]?\s*((?:hk|us|idx|gold|silver|crude|sh|sz)?:?\s*\d{4,6}(?:\.(?:HK|SS|SZ))?(?:\.US)?)", s, re.I)
        if m:
            code = re.sub(r"\s+", "", m.group(1))
        else:
            # 美股代码：需上下文明确（us:/美股/US），不用 \b（中文也是单词字符）
            m = re.search(r"([A-Za-z]{1,5})", s)
            if m and re.search(r"us:|美股|US", s):
                code = "us:" + m.group(1).upper()

    # 2) 意图判别（按特异性从高到低）
    # v9.7 知识库交互：保存分析/检索笔记/回读量化（关键词优先判别）
    # v9.8 支持口语指定 12 适配器目标（如“保存到 ragflow 知识库”）
    if re.search(r"知识库|笔记", s):
        target = ""
        for word, t in (("ragflow", "ragflow"), ("fastgpt", "fastgpt"),
                        ("maxkb", "maxkb"), ("语雀", "yuque"), ("飞书", "feishu"),
                        ("notion", "notion"), ("思源", "siyuan"),
                        ("logseq", "logseq"), ("obsidian", "obsidian"),
                        ("ima", "ima"), ("dify", "dify")):
            if word in low:
                target = t
                break
        query = re.sub(r"知识库|笔记|查一下|查询|搜索|搜一下|找一下|查找|读取|回顾"
                       r"|帮我|请|把|将|到|里|中|的"
                       r"|ragflow|fastgpt|maxkb|语雀|飞书|notion|思源"
                       r"|logseq|obsidian|ima|dify|本地", "", s).strip()
        if re.search(r"体检|量化|形态|预测分析", s):
            out.update(intent="kb_quant",
                       params={"query": query or (code or ""),
                               "target": target or None},
                       echo=f"从知识库回读数据做量化分析：{query or code or '全部'}。")
        elif re.search(r"保存|存档|入库|同步|记下来", s):
            if code:
                out.update(intent="kb_save", code=code,
                           params={"target": target or None},
                           echo=f"开始分析并保存到知识库：{code}。")
            else:
                out.update(intent="kb_save",
                           echo="请告诉我要保存哪只股票到知识库，比如：把茅台保存到知识库。")
        else:
            out.update(intent="kb_search",
                       params={"query": query or (code or ""),
                               "target": target or None},
                       echo=f"开始检索知识库：{query or code or '全部'}。")
        return out
    if re.search(r"板块.{0,4}(排名|强度|比较)|板块排名", s):
        market = "cn"
        for word, mk in _MARKET_WORDS.items():
            if word in low:
                market = mk
                break
        out.update(intent="sector_ranking", params={"market": market},
                   echo=f"开始{market.upper()}板块相对强度排名。")
        return out
    if re.search(r"(指数|大盘|市场).{0,4}(体制|状态)|体制分类", s):
        out.update(intent="index_regime", code=code or "sh000001",
                   echo=f"开始分析指数市场体制：{code or 'sh000001'}。")
        return out
    if re.search(r"情景|压力测试|宏观假设", s):
        out.update(intent="scenario",
                   echo="开始宏观情景概率加权分析。")
        return out
    if re.search(r"自上而下|全景|总览|市场全貌", s):
        market = "cn"
        for word, mk in _MARKET_WORDS.items():
            if word in low:
                market = mk
                break
        out.update(intent="topdown", params={"market": market},
                   echo=f"开始生成{market.upper()}自上而下全景报告。")
        return out
    if re.search(r"体检|量化指标|回撤|夏普", s):
        if code:
            out.update(intent="quant_check", code=code,
                       echo=f"开始量化体检：{code}。")
        else:
            out.update(intent="quant_check",
                       echo="请告诉我体检哪只股票或指数。")
        return out
    if re.search(r"大佬|大师|圆桌|高手们|名人", s):
        if code:
            out.update(intent="masters", code=code,
                       echo=f"开始大佬圆桌：{code}。")
        else:
            out.update(intent="masters",
                       echo="请告诉我圆桌讨论哪只股票，比如：大佬们怎么看茅台。")
        return out
    if re.search(r"预测|分析|看看|怎么样|走势|行情|研报|涨跌", s):
        if code:
            out.update(intent="predict", code=code,
                       echo=f"开始分析：{code}。")
        else:
            out.update(intent="predict",
                       echo="请告诉我要分析哪只股票，比如：预测茅台。")
        return out
    # 仅有代码时也默认预测
    if code:
        out.update(intent="predict", code=code, echo=f"开始分析：{code}。")
        return out
    out["echo"] = "没听懂指令，说“帮助”可查看支持的功能。"
    return out


# ─── 语音会话 ───────────────────────────────────────────────────────────────


class VoiceResearchChat:
    """语音/文本交互会话。

    参数均可注入以便测试：
      listen    : (timeout) -> Optional[str]，默认 listen_once
      speak_fn  : (text) -> bool，默认 speak
      executor  : (cmd: Dict) -> str，命令执行器；默认走内置分发
                  （调用 stock_predict.predict 与 v9.0 命令底层模块）
      tts       : 是否播报（False 时仅打印）
    """

    def __init__(self, listen: Optional[Callable] = None,
                 speak_fn: Optional[Callable] = None,
                 executor: Optional[Callable] = None,
                 tts: bool = True, listen_timeout: int = 8):
        self.listen = listen or listen_once
        self.speak_fn = speak_fn or speak
        self.executor = executor or self._default_execute
        self.tts = tts
        self.listen_timeout = listen_timeout
        self.history: List[Dict[str, str]] = []

    # ---- 命令执行（默认实现，可被注入替换） ----

    def _default_execute(self, cmd: Dict[str, Any]) -> str:
        intent = cmd.get("intent")
        try:
            if intent == "exit":
                return "好的，已退出。"
            if intent == "help":
                return ("支持指令示例：预测茅台 / 分析600519 / 量化体检 / "
                        "A股板块排名 / 上证指数体制 / 情景分析 / 自上而下全景 / "
                        "大佬们怎么看茅台。")
            if intent == "predict" and cmd.get("code"):
                import sys
                from pathlib import Path
                _sp = str(Path(__file__).resolve().parents[2])
                if _sp not in sys.path:
                    sys.path.insert(0, _sp)
                from stock_predict import predict
                r = predict(cmd["code"], silent=True, quick_mode=True)
                if "error" in r:
                    return f"分析失败：{r['error']}"
                mc = r.get("monte_carlo", {}).get("5d", {})
                return (f"{r.get('name', cmd['code'])}当前价"
                        f"{r.get('price', {}).get('price', '未知')}，"
                        f"信号{r.get('signal', '未知')}，"
                        f"置信度{r.get('confidence', 0):.0%}，"
                        f"五日上涨概率{mc.get('up', 0):.0%}，"
                        f"综合评分{r.get('score', {}).get('total', 0):.0f}。")
            if intent == "sector_ranking":
                from stock_researcher.sector_analysis.relative_strength import (
                    rps_ranking, SectorRelativeStrength)
                return SectorRelativeStrength.format_ranking(
                    rps_ranking(market=cmd.get("params", {}).get("market", "cn")),
                    market=cmd.get("params", {}).get("market", "cn"))
            if intent == "index_regime":
                from stock_researcher.index_analysis.market_regime import (
                    MarketRegimeClassifier)
                return MarketRegimeClassifier.format(
                    MarketRegimeClassifier().classify(cmd.get("code") or "sh000001"))
            if intent == "scenario":
                from stock_researcher.quantitative.scenario_engine import (
                    MacroScenarioEngine)
                eng = MacroScenarioEngine()
                return MacroScenarioEngine.format(eng.analyze(0.08, 0.20, None))
            if intent == "topdown":
                from stock_researcher.analysis.top_down import TopDownReport
                return TopDownReport.format(
                    TopDownReport().build(market=cmd.get("params", {}).get("market", "cn")))
            if intent == "quant_check" and cmd.get("code"):
                from stock_researcher.data.global_market import fetch_global_kline
                from stock_researcher import compute_quant_metrics, format_quant_metrics
                kline = fetch_global_kline(cmd["code"], days=120)
                closes = [float(k.get("close", 0)) for k in (kline or []) if k.get("close")]
                if len(closes) < 30:
                    return f"{cmd['code']} 历史数据不足，无法体检。"
                return format_quant_metrics(cmd["code"], compute_quant_metrics(closes))
            # v9.7 知识库交互：保存分析 / 检索 / 回读量化（不联网，v9.8 可指定适配器）
            if intent == "kb_save" and cmd.get("code"):
                import sys
                from pathlib import Path
                _sp = str(Path(__file__).resolve().parents[2])
                if _sp not in sys.path:
                    sys.path.insert(0, _sp)
                from stock_predict import predict, fetch_quote_kline
                from stock_researcher.knowledge_sync import save_analysis_to_kb
                r = predict(cmd["code"], silent=True, quick_mode=True)
                if "error" in r:
                    return f"分析失败，无法保存知识库：{r['error']}"
                _, kl = fetch_quote_kline(cmd["code"], silent=True, days=120)
                prices = [k["close"] for k in (kl or []) if k.get("close")]
                res = save_analysis_to_kb(
                    cmd["code"], r, prices,
                    target=cmd.get("params", {}).get("target"))
                if res.get("ok"):
                    return (f"已保存到知识库（{res.get('adapter')}）："
                            f"{res.get('title')}，状态 {res.get('status')}。")
                return f"保存知识库失败：{res.get('error')}"
            if intent == "kb_search":
                from stock_researcher.knowledge_sync import search_knowledge
                query = cmd.get("params", {}).get("query") or ""
                if not query:
                    return "请告诉我要在知识库里查什么，比如：查一下知识库里的茅台。"
                hits = search_knowledge(
                    query, target=cmd.get("params", {}).get("target"), limit=3)
                if not hits:
                    return f"知识库未找到与 “{query}” 相关的笔记。"
                lines = [f"知识库命中 {len(hits)} 条："]
                for h in hits:
                    lines.append(f"- {h.get('title', '')}："
                                 f"{(h.get('snippet') or '')[:80]}")
                return "\n".join(lines)
            if intent == "kb_quant":
                from stock_researcher.knowledge_sync import kb_quant_forecast
                query = cmd.get("params", {}).get("query") or ""
                if not query:
                    return "请告诉我要用哪条知识库数据做量化，比如：用知识库里的茅台数据体检。"
                rep = kb_quant_forecast(
                    query, target=cmd.get("params", {}).get("target"))
                if not rep.get("ok"):
                    return rep.get("error", "知识库量化失败。")
                m = rep["metrics"]
                pf = rep["pattern_forecast"]
                if pf.get("data_mode") == "ok":
                    fc = (f"未来5日预期"
                          f"{pf.get('predicted_pct', 0):+.2f}%，"
                          f"上涨概率{pf.get('prob_up', 0):.0f}%。")
                else:
                    fc = "历史形态匹配不足，未给出方向预测。"
                return (f"知识库回读 {rep.get('name') or rep.get('code')}"
                        f"（{rep.get('points')} 个价格点，存档于"
                        f"{rep.get('saved_at', '未知')}）："
                        f"总收益{m.get('total_return_pct', 0):+.2f}%，"
                        f"夏普{m.get('sharpe_ratio') or '—'}，"
                        f"最大回撤{m.get('max_drawdown_pct', 0):.2f}%。{fc}")
            if intent == "masters" and cmd.get("code"):
                import sys
                from pathlib import Path
                _sp = str(Path(__file__).resolve().parents[2])
                if _sp not in sys.path:
                    sys.path.insert(0, _sp)
                from stock_predict import fetch_quote_kline
                from stock_researcher.agents.master_input import MasterInput
                from stock_researcher.agents.master_council import MasterCouncil
                q, kl = fetch_quote_kline(cmd["code"], silent=True, days=250)
                if not q or "error" in q:
                    return f"圆桌失败：{(q or {}).get('error', '行情获取失败')}"
                inp = MasterInput.from_market(
                    code=q.get("code", cmd["code"]), name=q.get("name", ""),
                    price=q.get("price", 0), pe=q.get("pe", 0),
                    closes=[k["close"] for k in (kl or [])],
                )
                rep = MasterCouncil().analyze(inp)
                if rep.valid_count == 0:
                    return f"{cmd['code']} 数据不足，大佬们无法给出意见。"
                return MasterCouncil.format(rep)
            return cmd.get("echo") or "没听懂指令，说“帮助”可查看支持的功能。"
        except Exception as e:
            return f"执行失败：{e}"

    # ---- 会话 ----

    def handle_text(self, text: str) -> str:
        """处理一轮输入（文本或 STT 结果），返回回复文本。"""
        cmd = parse_voice_command(text)
        reply = self.executor(cmd)
        self.history.append({"user": text, "reply": reply})
        if self.tts:
            try:
                self.speak_fn(summarize_for_speech(reply))
            except Exception:
                pass
        return reply

    def run(self, max_turns: int = 0) -> None:
        """主循环。STT 不可用时降级为文本输入；max_turns>0 限制轮数。"""
        use_voice = stt_available() and self.listen is listen_once
        if not use_voice and self.listen is listen_once:
            print("ℹ️ 语音识别不可用，已降级为文本输入。")
        print("🎙️ 股票研究员语音交互（说“帮助”查看指令，“退出”结束）")
        turns = 0
        while True:
            try:
                if use_voice:
                    print("🎤 请说话…")
                    user = self.listen(timeout=self.listen_timeout)
                    if user:
                        print(f"🗣️ 识别：{user}")
                else:
                    user = input("📝 指令> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user:
                continue
            reply = self.handle_text(user)
            print(reply)
            turns += 1
            if parse_voice_command(user).get("intent") == "exit":
                break
            if max_turns and turns >= max_turns:
                break
