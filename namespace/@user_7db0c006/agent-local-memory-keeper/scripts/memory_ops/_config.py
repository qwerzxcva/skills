# -*- coding: utf-8 -*-
"""配置与默认值（F18 阶段2 从 memory_ops 单体抽出，零行为变化）。

仅依赖标准库 os；所有符号被 memory_ops/__init__.py 原位重导出，调用方无感。
跨平台零配置默认路径、tier / 矛盾检测枚举常量集中于此，便于单测与审查。
"""
import os


def user_store_override():
    """用户级显式指定：~/.keeper/store_root（一行路径）。

    用途：库不在默认位置时（例如放在 D 盘、移动硬盘、网络盘），把路径写进这个
    文件即可，无需设环境变量、也不必把机器特定路径写进代码。
        优先级仅次于 AI_MEMORY_STORE 环境变量。文件不存在/为空 → 返回 None。
    """
    try:
        p = os.path.join(os.path.expanduser("~"), ".keeper", "store_root")
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8-sig") as f:
            v = (f.readline() or "").strip().strip('"').strip("'")
        return v or None
    except Exception as _e:
        # 4.9.17（同族：不再静默回退）：文件存在却读不了（权限/编码/IO）时，旧实现静默
        # 回退默认库根 → 用户「记忆凭空消失」。显式告警，让「读不到配置」≠「配置没设」。
        import sys as _sys
        _sys.stderr.write(
            "[⚠ config] 读取 ~/.keeper/store_root 失败，已回退默认库根（可能读错库）: %s\n" % _e)
        return None


def _default_root():
    """跨平台零配置默认路径：
    - 设了 AI_MEMORY_STORE 环境变量 → 用它（最高优先级）。
    - 否则读 ~/.keeper/store_root（用户级显式指定，见 user_store_override）。
    - 都没有 → 平台默认：Windows ~/AI记忆，mac/Linux ~/.ai-memory。
    首次 deposit/recall 时目录与 index 会自动创建，开箱即用。
    """
    env = os.environ.get("AI_MEMORY_STORE")
    if env:
        return env
    ov = user_store_override()
    if ov:
        return ov
    home = os.path.expanduser("~")
    if os.name == "nt":
        return os.path.join(home, "AI记忆")
    return os.path.join(home, ".ai-memory")


DEFAULT_ROOT = _default_root()

TIERS = ("seed", "working", "curated", "core")
# 可被"纠正"推翻的目标类别
CONTRADICTABLE = ("best_practice", "workflow", "architecture_decision", "technical_constraint")
# 能推翻他人的类别
CORRECTING = ("correction", "knowledge_gap")
# #13 修复：矛盾检测 embedding 语义比对阈值——语义相似度≥此值且含对立信号时触发矛盾
CONTRADICTION_SEM_THRESHOLD = 0.65
# #13：对立信号词对（A 说做 / B 说不做 → 疑似矛盾）
_OPPOSITE_MARKERS = {
    "pos": ("必须", "应该", "推荐", "建议", "always", "要", "需要", "用", "选", "采用"),
    "neg": ("不要", "别", "避免", "切忌", "禁止", "never", "别用", "不用", "不选", "不采用"),
}
