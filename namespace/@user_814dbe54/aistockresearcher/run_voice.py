# -*- coding: utf-8 -*-
"""stock-researcher v9.4.0 语音交互入口。

用法：
    python run_voice.py              # 语音循环（STT 不可用时自动降级文本输入）
    python run_voice.py --text       # 强制文本输入模式
    python run_voice.py --no-tts     # 不播报，仅打印

示例指令：预测茅台 / 分析600519 / 量化体检 / A股板块排名 /
          上证指数体制 / 情景分析 / 自上而下全景 / 帮助 / 退出
"""
import sys
from pathlib import Path

# v9.6 字节码防护：禁止生成本地模块的 __pycache__/*.pyc（交付包禁二进制）
sys.dont_write_bytecode = True

# 保证 scripts/ 可导入（与 runtests.py 一致）
_SCRIPTS = str(Path(__file__).resolve().parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from stock_researcher.voice_interface import VoiceResearchChat  # noqa: E402


def main() -> None:
    tts = "--no-tts" not in sys.argv
    if "--text" in sys.argv:
        # 注入非默认 listen，使 run() 判定为非语音路径 → 文本输入循环
        chat = VoiceResearchChat(listen=lambda timeout=8: None, tts=tts)
    else:
        chat = VoiceResearchChat(tts=tts)
    chat.run()


if __name__ == "__main__":
    main()
