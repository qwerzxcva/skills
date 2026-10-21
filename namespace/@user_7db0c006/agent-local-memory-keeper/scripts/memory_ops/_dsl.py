# memory_ops/_dsl.py - 数值过滤 DSL + 指标自动抽取（F18 阶段2 从 __init__.py 抽出）
# 自包含：仅依赖 re，不引用 __init__ 其它符号，故无循环导入。
# 所有符号由 __init__.py 显式重导出，调用方 memory_ops.parse_filter / .eval_filter 等解析不变。
import re

# 指标名白名单：只收敛这些明确是「投资指标」的词，避免把年份/版本/序号当指标抽出来。
# 同义异名（中文/英文/简称）通过 _ATTR_METRIC_ALIAS 归一到一个规范 key，避免
# "回撤" 与 "最大回撤"、"动量" 与 "momentum" 散落成两个字段。
_ATTR_METRIC_WHITELIST = {
    "pe", "pb", "roe", "roa", "eps", "ps", "股息率", "dividend",
    "动量", "momentum", "回撤", "最大回撤", "drawdown", "maxdrawdown",
    "beta", "夏普", "sharpe", "波动率", "vol", "rps", "涨跌幅", "收益率",
    "return", "换手率", "turnover", "估值", "valuation", "仓位", "position",
    "胜率", "winrate", "集中度", "concentration", "杠杆", "leverage",
# 因子测试核心量（量化回测：逐个验证 IC/IR → 组合打分）
    "ic", "ir", "information_coefficient", "information_ratio",
    "信息系数", "信息比率", "alpha", "cagr", "sortino",
    "暴露", "冗余", "命中率", "exposure", "redundancy", "hitrate", "tvalue",
}
# 归一表：抽取到的原始名 → 规范存储 key（小写）。未列出的按原名存。
_ATTR_METRIC_ALIAS = {
    "最大回撤": "maxdrawdown", "回撤": "maxdrawdown",
    "drawdown": "maxdrawdown", "maxdrawdown": "maxdrawdown",
    "动量": "momentum", "momentum": "momentum",
    "夏普": "sharpe", "sharpe": "sharpe",
    "波动率": "vol", "vol": "vol",
    "收益率": "return", "return": "return",
    "换手率": "turnover", "turnover": "turnover",
    "估值": "valuation", "valuation": "valuation",
    "仓位": "position", "position": "position",
    "胜率": "winrate", "winrate": "winrate",
    "集中度": "concentration", "concentration": "concentration",
    "杠杆": "leverage", "leverage": "leverage",
# 因子测试指标归一（信息系数/信息比率/索提诺/暴露/冗余/命中率 → 规范 key）
    "信息系数": "ic", "information_coefficient": "ic", "ic": "ic",
    "信息比率": "ir", "information_ratio": "ir", "ir": "ir",
    "索提诺": "sortino", "sortino": "sortino",
    "暴露": "exposure", "exposure": "exposure",
    "冗余": "redundancy", "redundancy": "redundancy",
    "命中率": "hitrate", "hitrate": "hitrate",
}
# 易误抽的黑名单 token：年份/版本/季度/序号/编号等，命中即跳过。
_ATTR_BLACKLIST_TOKEN = {
    "年", "月", "日", "版本", "版", "季度", "第", "号", "期", "页",
    "步", "次", "条", "个", "篇", "张", "批", "轮",
}
_ATTR_NUM_RE = re.compile(
    r"(?P<name>[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff_%\.\-]{0,15}?)"
    r"(?P<sep>[=：:\-\s])?"          # 可选分隔：等号/冒号/横杠/空格（覆盖 PE=28.5 / 回撤-15% / 动量0.82 / pe 28.5）
    r"(?P<num>\d+(?:\.\d+)?)"
    r"(?P<pct>%|％|pct|倍|倍率)?"
)


def _coerce_metric_value(num: str, sep, pct):
    """把正则捕获的数值字符串转成 float。

    - 横杠分隔（sep='-'）视为负值（如「回撤-15%」「差值-5」），契合投资指标向下语义。
    - 带 %/％/pct 的按比率(0-1)存（15% → 0.15）；「倍」保持原数（如 2 倍）。"""
    v = float(num)
    if sep == "-":
        v = -abs(v)
    if pct:
        if pct in ("倍", "倍率"):
            return v
        return round(v / 100.0, 6)
    return v


def _norm_attr_key(name: str):
    """把指标名归一为规范 key（同义异名 → 规范存储名）。"""
    return _ATTR_METRIC_ALIAS.get(name.strip().lower(), name.strip().lower())


def _extract_attrs(text: str):
    """从文本正则抽取 指标名=数值 配对，返回 {name: value}。

    - 仅白名单指标名入库；命中黑名单 token 的 name 跳过。
    - 同 name 多次出现取**最后**一个（后写覆盖前写，符合「最新结论」语义）。
    - 不确定/口语（"约三十倍"）不抽——交给后续可选 LLM 增强。"""
    if not text:
        return {}
    out = {}
    for m in _ATTR_NUM_RE.finditer(text):
        name = m.group("name").strip().lower()
        if name in _ATTR_BLACKLIST_TOKEN:
            continue
        if name not in _ATTR_METRIC_WHITELIST:
            continue
            # 同义异名归一（回撤/最大回撤 → maxdrawdown；动量/momentum → momentum）
        key = _ATTR_METRIC_ALIAS.get(name, name)
        out[key] = _coerce_metric_value(m.group("num"), m.group("sep"), m.group("pct"))
    return out


def _merge_attrs(base: dict, extra: dict):
    """合并显式 --attr 与自动抽取结果。--attr 显式优先（用户明确值 > 自动猜），
    其余自动抽取补全。返回新 dict，不动入参。"""
    merged = dict(base or {})
    for k, v in (extra or {}).items():
        if k not in merged:           # 显式 --attr 已给的，不被猜测覆盖
            merged[k] = v
    return merged


    # ---------- 数值过滤 DSL（够用即可版） ----------
    # 词法：字段 比较符 值 [AND|OR 字段 比较符 值]...
    # 字段：数值属性走 attrs（pe/pb/momentum…）；字符串属性支持 scene/domain/subdomain/tag/type。
    # 比较符：> >= < <= = != （数值与字符串通用，字符串仅 = / != 有意义）。
    # 安全：手写递归下降解析，严禁 eval/exec；字段名白名单限制。
_ATTR_FILTER_FIELDS = {
    "pe", "pb", "roe", "roa", "eps", "ps", "股息率", "dividend", "动量",
    "momentum", "回撤", "drawdown", "beta", "夏普", "sharpe", "波动率", "vol",
    "rps", "涨跌幅", "收益率", "return", "换手率", "turnover", "估值",
    "valuation", "仓位", "position", "胜率", "winrate", "最大回撤",
    "maxdrawdown", "集中度", "concentration", "杠杆", "leverage",
# F1：因子测试核心量——与 _ATTR_METRIC_WHITELIST 对齐，使 recall --filter "ic>0.1" 可用
    "ic", "ir", "alpha", "cagr", "sortino", "exposure", "redundancy", "hitrate", "tvalue",
}
# P-audit（全量体检）：记忆级通用评分字段也可被 --filter 数值 DSL 过滤（非投资因子 attrs）。
# _match_clause 对它们从记忆顶层读取，而非 mem['attrs']。
_MEM_LEVEL_NUM_FIELDS = {"confidence", "importance", "relevance_score", "relevance",
                         "access_count", "access", "age_days", "thermal_weight"}
_STR_FILTER_FIELDS = {"scene", "domain", "subdomain", "tag", "type",
                      "state", "priority", "area", "about_axis"}  # v4.0.0/4.1.0：状态机/优先级/领域/四轴也可过滤
_CMP_RE = re.compile(r"(>=|<=|!=|=|>|<)")
# F5：允许未引号字符串值含冒号（如 tag=st:verified），word 模式扩展可含 : - . / 但不含空格/比较符
_TOK_RE = re.compile(r"\s*("
                     r">=|<=|!=|=|>|<|"
                     r"AND|OR|"
                     r"[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff_:\.\/\-]{0,63}|"
                     r"-?\d+(?:\.\d+)?|"
                     r"\"[^\"]*\"|'[^']*'"
                     r")\s*")


def parse_filter(expr: str):
    """解析 --filter 表达式 → list of clause dict。

    clause: {"field": str, "op": str, "value": float|str, "kind": "num"|"str"}
    返回空 list 表示无过滤（空表达式）。非法语法抛 ValueError（带位置信息）。"""
    if not expr or not expr.strip():
        return []
    toks = [t for t in _TOK_RE.findall(expr) if t.strip()]
    if not toks:
        raise ValueError("filter 表达式为空或无法分词")
    clauses = []
    i = 0
    n = len(toks)
    expect_conn = False  # 第一条子句后必须出现 AND/OR
    last_conn = None     # F15：记录前导连接符（第一条子句为 None），供 eval_filter 支持 OR
    while i < n:
        if expect_conn:
            conn = toks[i].upper()
            if conn not in ("AND", "OR"):
                raise ValueError("filter 第 %d 个 token '%s' 应为 AND/OR 连接符" % (i + 1, toks[i]))
            last_conn = conn   # F15：记录连接符
            i += 1
            expect_conn = False
            if i >= n:
                raise ValueError("filter 以连接符 %s 结尾，缺少后续子句" % conn)
        field = toks[i]
        # F4：字段归一（中文别名→规范存储 key），使「夏普>1」经 _norm_attr_key 命中 sharpe
        fid = _norm_attr_key(field)
        if fid not in _ATTR_FILTER_FIELDS and fid not in _STR_FILTER_FIELDS \
                and fid not in _MEM_LEVEL_NUM_FIELDS:
            raise ValueError("filter 字段 '%s' 不在允许列表" % field)
        i += 1
        if i >= n:
            raise ValueError("filter 字段 '%s' 后缺少比较符" % field)
        opm = _CMP_RE.fullmatch(toks[i])
        if not opm:
            raise ValueError("filter 第 %d 个 token '%s' 不是合法比较符(> >= < <= = !=)" % (i + 1, toks[i]))
        op = toks[i]
        i += 1
        if i >= n:
            raise ValueError("filter 比较符 '%s' 后缺少值" % op)
        raw_val = toks[i].strip()
        if fid in _STR_FILTER_FIELDS:
            if raw_val.startswith('"') and raw_val.endswith('"'):
                raw_val = raw_val[1:-1]
            elif raw_val.startswith("'") and raw_val.endswith("'"):
                raw_val = raw_val[1:-1]
            if op not in ("=", "!="):
                raise ValueError("字符串字段 '%s' 仅支持 = / !=（不支持 %s）" % (field, op))
            clauses.append({"field": fid, "op": op, "value": raw_val, "kind": "str", "conn": last_conn})
        else:
            try:
                val = float(raw_val)
            except ValueError:
                raise ValueError("filter 数值字段 '%s' 的值 '%s' 不是合法数字" % (field, raw_val))
            clauses.append({"field": fid, "op": op, "value": val, "kind": "num", "conn": last_conn})
        i += 1
        expect_conn = True
    return clauses


def _cmp(op: str, a, b):
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == "=":
        return a == b
    if op == "!=":
        return a != b
    return False


def _match_clause(mem: dict, c: dict):
    if c["kind"] == "str":
        f = c["field"]
        if f == "tag":
            return _cmp(c["op"], c["value"] in (mem.get("tags") or []), True)
        return _cmp(c["op"], mem.get(f), c["value"])
    if c["field"] in _MEM_LEVEL_NUM_FIELDS:
        val = mem.get(c["field"])   # 记忆级评分（confidence/importance/...）从顶层读
    else:
        val = (mem.get("attrs") or {}).get(c["field"])  # 投资因子等结构化指标
    if val is None:
        return False
    return _cmp(c["op"], val, c["value"])


def eval_filter(mem: dict, clauses):
    """对单条 mem 求值 filter clauses（F15：支持 AND/OR 左结合，无括号优先级）。

    数值字段从 mem['attrs'] 取，缺失即该子句 False；字符串字段 scene/domain/
    subdomain/type 读顶层，tag 走 tags 包含判定。空 clauses → 全通过。"""
    if not clauses:
        return True
    result = None
    for c in clauses:
        ok = _match_clause(mem, c)
        conn = c.get("conn")
        if conn is None:
            result = ok
        elif conn == "AND":
            result = result and ok
        elif conn == "OR":
            result = result or ok
    return result
