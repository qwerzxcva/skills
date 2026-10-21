"""Investment大师 agents"""
from .buffett import BuffettAnalyzer
from .graham import GrahamAnalyzer
from .lynch import LynchAnalyzer
from .technical import TechnicalAgent
from .sentiment import SentimentAnalyzer

# v9.5 大佬策略参考面板（统一快照输入 + 圆桌共识）
from .master_input import MasterInput, MasterResult, score_to_signal
from .soros import SorosAnalyzer
from .fisher import FisherAnalyzer
from .dalio import DalioAnalyzer
from .marks import MarksAnalyzer
from .greenblatt import GreenblattAnalyzer
from .livermore import LivermoreAnalyzer
from .master_council import MasterCouncil, CouncilReport, quick_master_council

__all__ = [
    "BuffettAnalyzer", "GrahamAnalyzer", "LynchAnalyzer",
    "TechnicalAgent", "SentimentAnalyzer",
    # v9.5
    "MasterInput", "MasterResult", "score_to_signal",
    "SorosAnalyzer", "FisherAnalyzer", "DalioAnalyzer", "MarksAnalyzer",
    "GreenblattAnalyzer", "LivermoreAnalyzer",
    "MasterCouncil", "CouncilReport", "quick_master_council",
]
