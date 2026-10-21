#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
规划用地红线定位与地图生成（city-planner skill）

根据用地红线（DXF/DWG/图片/PDF）与坐标/地址，识别地块位置，产出：
  - site_brief.json : 属地政策(规划口径)、气候区、地块几何(面积/周长/朝向)、规划建议、merge 片段
  - site_map.html   : 浏览器可看的交互地图（Leaflet + OSM 底图，标注红线位置与定位点）

与 architect/scripts/site_analyze.py 同源，但本脚本面向「规划」语境：
  - 规划建议聚焦 三区三线、开发强度、15 分钟生活圈、控规用地编码(GB 50137)、四线管控；
  - merge 片段以规划指标口径导出（category/name/unit/recent/future/attr），
    供 city-planner/scripts/build_report.py 用 --site 注入。

用法示例：
  python site_analyze.py --dxf 红线.dxf --coords "121.47,31.23" --outdir ./site
  python site_analyze.py --image 红线.png --outdir ./site          # 自动 OCR 坐标注记
  python site_analyze.py --address "厦门市思明区环岛路XX地块" --outdir ./site
  python site_analyze.py --coords "118.09,24.48" --area 50000 --outdir ./site   # 仅坐标+估算面积

说明：
  - 坐标系统一为 WGS84 经纬度；若红线为 CGCS2000 高斯投影(如 4547)，加 --epsg 4547 精校正。
  - DXF 解析依赖 ezdxf（pip install ezdxf）；投影转换依赖 pyproj（pip install pyproj）；
    自动 OCR 依赖 pytesseract + Tesseract OCR（可选，缺失时改用 AI 读图或手动 --coords/--address）。
"""

import argparse
import csv
import html
import io
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime

# 运行时不写 __pycache__，避免生成 .pyc 被打包/上传工具误判为二进制
sys.dont_write_bytecode = True

# ---------- 依赖（缺失时给友好提示） ----------
try:
    import ezdxf
except ImportError:
    ezdxf = None

try:
    import pyproj
except ImportError:
    pyproj = None

try:
    from PIL import Image
except ImportError:
    Image = None


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_POLICY_DB = os.path.join(HERE, "..", "references", "local_policy_db.json")

EARTH_R = 6371000.0  # 米

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _to_float(s):
    if s is None:
        return None
    try:
        return float(str(s).strip())
    except (ValueError, TypeError):
        return None


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def ring_area_m2(ring):
    """鞋带公式算投影面积（米），ring: [(lat, lng), ...]"""
    if len(ring) < 3:
        return 0.0
    # 以质心为原点转局部平面坐标
    lat0 = sum(p[0] for p in ring) / len(ring)
    lng0 = sum(p[1] for p in ring) / len(ring)
    mx = EARTH_R * math.radians(lat0)
    my = EARTH_R * math.radians(lng0) * math.cos(math.radians(lat0))
    pts = []
    for lat, lng in ring:
        x = EARTH_R * math.radians(lat) - mx
        y = EARTH_R * math.radians(lng) * math.cos(math.radians(lat0)) - my
        pts.append((x, y))
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def ring_perimeter_m(ring):
    if len(ring) < 2:
        return 0.0
    total = 0.0
    for i in range(len(ring)):
        a = ring[i]
        b = ring[(i + 1) % len(ring)]
        total += haversine(a[0], a[1], b[0], b[1])
    return total


def ring_orientation_deg(ring):
    """用最长边估计主轴朝向（正北=0°，顺时针）"""
    if len(ring) < 2:
        return 0.0
    best = (0.0, 0.0)
    for i in range(len(ring)):
        a = ring[i]
        b = ring[(i + 1) % len(ring)]
        d = haversine(a[0], a[1], b[0], b[1])
        if d > best[0]:
            best = (d, (a, b))
    _, (a, b) = best
    dy = b[0] - a[0]
    dx = (b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    ang = math.degrees(math.atan2(dx, dy))
    return (ang + 360.0) % 360.0


# ---------------------------------------------------------------------------
# 地理编码 / 反查
# ---------------------------------------------------------------------------

def geocode(address):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": address, "format": "json", "limit": "1"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "site_analyze/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


def reverse_geocode(lat, lng):
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
        {"lat": lat, "lon": lng, "format": "json", "accept-language": "zh-CN"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "site_analyze/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data.get("display_name", "")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# DXF / 投影
# ---------------------------------------------------------------------------

def project_to_wgs84(x, y, epsg):
    if not epsg or not pyproj:
        return y, x  # 已是经纬度（假定 lng, lat）
    transformer = pyproj.Transformer.from_crs(
        pyproj.CRS.from_epsg(int(epsg)), pyproj.CRS.from_epsg(4326), always_xy=True
    )
    lng, lat = transformer.transform(x, y)
    return lat, lng


def load_dxf(path, epsg):
    if not ezdxf:
        raise RuntimeError("缺少 ezdxf：pip install ezdxf")
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    polylines = []
    for e in msp:
        t = e.dxftype()
        pts = []
        if t in ("LWPOLYLINE", "POLYLINE"):
            try:
                pts = [(v[0], v[1]) for v in e.get_points()]
            except Exception:
                continue
        elif t == "LINE":
            pts = [(e.dxf.start[0], e.dxf.start[1]), (e.dxf.end[0], e.dxf.end[1])]
        if pts:
            ring = [project_to_wgs84(x, y, epsg) for x, y in pts]
            polylines.append(ring)
    return polylines


# ---------------------------------------------------------------------------
# OCR（可选）
# ---------------------------------------------------------------------------

def ocr_coords_from_image(path):
    """尝试用 Tesseract 识别图框中的坐标注记，返回候选 (lat, lng) 列表。"""
    if not Image:
        return [], "未安装 Pillow（pip install pillow）"
    try:
        import pytesseract
    except ImportError:
        return [], "未安装 pytesseract（pip install pytesseract + Tesseract OCR）"
    img = Image.open(path).convert("RGB")
    text = pytesseract.image_to_string(img, lang="chi_sim+eng")
    return find_coords_in_text(text), text


def find_coords_in_text(text):
    """从 OCR 文本中粗略提取候选经纬度（十进制或度分秒），结果不可靠，仅供人工复核。"""
    cands = []
    # 1) 中文标注："经度 118.09 纬度 24.48" 或 "东经 118.09 北纬 24.48"
    for lng, lat in re.findall(
        r"(?:经度|东经|Lng|LNG|X)\s*[:：]?\s*([1-9]\d\.\d{2,6})\s*[,\s]+\s*"
        r"(?:纬度|北纬|Lat|LAT|Y)\s*[:：]?\s*([1-9]\d\.\d{2,6})", text
    ):
        cands.append((float(lat), float(lng)))
    # 2) 连续十进制坐标对（3 位整数+小数），如 118.094 24.481 或 118.09,24.48
    decs = [float(x) for x in re.findall(
        r"(?<![.\d])(1[0-3]\d\.\d{2,6}|2[0-3]\d\.\d{2,6})(?![.\d])", text)][:20]
    for i in range(0, len(decs) - 1, 2):
        a, b = decs[i], decs[i + 1]
        # 中国范围：经度 100~135，纬度 18~54
        if 100 <= a <= 135 and 18 <= b <= 54:
            cands.append((b, a))
        elif 100 <= b <= 135 and 18 <= a <= 54:
            cands.append((a, b))
        else:
            cands.append((a, b))
    # 3) 度分秒：121°29'12"E（粗略取度值，供提示）
    for d in re.findall(r"(\d{2,3})\s*[°]\s*\d{1,2}\s*['′]\s*\d{1,2}\s*[\"″]?", text):
        try:
            cands.append((float(d), float(d)))
        except ValueError:
            pass
    # 去重（保留顺序）
    seen, uniq = set(), []
    for c in cands:
        key = (round(c[0], 4), round(c[1], 4))
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq[:10]


# ---------------------------------------------------------------------------
# 区域 / 政策 / 气候 匹配
# ---------------------------------------------------------------------------

MAJOR_CITIES = {
    "北京": {"zone": "严寒B/寒冷A交界", "wind": "西北", "note": "冬季漫长寒冷，需强化保温与日照间距；绿色建筑与装配式要求高。"},
    "上海": {"zone": "夏热冬冷", "wind": "东南", "note": "梅雨高湿、夏季闷热，重视通风遮阳与防洪排涝（海绵城市）。"},
    "广州": {"zone": "夏热冬暖", "wind": "东南", "note": "长夏无冬、台风多发，重视隔热、防雨与抗风。"},
    "深圳": {"zone": "夏热冬暖", "wind": "东南", "note": "台风多发、湿热，重视抗风、隔热与自然通风。"},
    "成都": {"zone": "温和", "wind": "静风偏北", "note": "全年温和、静风频率高，重视雾霾扩散与通风廊道。"},
    "武汉": {"zone": "夏热冬冷", "wind": "东南", "note": "火炉城市，冬冷夏热，重视遮阳通风与水体调蓄。"},
    "西安": {"zone": "寒冷", "wind": "东北", "note": "冬季干冷、夏季炎热，重视保温与降水蓄集。"},
    "杭州": {"zone": "夏热冬冷", "wind": "东南", "note": "梅雨高湿，重视防潮通风与海绵调蓄。"},
    "南京": {"zone": "夏热冬冷", "wind": "东南", "note": "夏热冬冷、冬季湿冷，重视保温与通风。"},
    "重庆": {"zone": "夏热冬冷", "wind": "静风", "note": "地形湿热、静风多雾，重视通风廊道与防涝。"},
    "天津": {"zone": "寒冷", "wind": "西北", "note": "冬季干冷，重视保温与风速防护。"},
    "苏州": {"zone": "夏热冬冷", "wind": "东南", "note": "同上海，重视通风遮阳与海绵。"},
    "厦门": {"zone": "夏热冬暖", "wind": "东南", "note": "湿热、台风，重视通风、防潮与抗风。"},
    "福州": {"zone": "夏热冬暖", "wind": "东南", "note": "湿热多雨，重视通风防潮。"},
    "青岛": {"zone": "寒冷", "wind": "东南", "note": "海洋性寒冷，重视海风防护与保温。"},
    "大连": {"zone": "寒冷", "wind": "偏南", "note": "海洋性寒冷，重视保温与防风。"},
    "沈阳": {"zone": "严寒", "wind": "西北", "note": "严寒漫长，强保温与采暖节能。"},
    "哈尔滨": {"zone": "严寒", "wind": "西北", "note": "严寒极冷，强保温与防冻。"},
    "昆明": {"zone": "温和", "wind": "西南", "note": "四季如春，重视通风与采光。"},
    "长沙": {"zone": "夏热冬冷", "wind": "西北", "note": "夏热冬冷，重视遮阳通风。"},
    "郑州": {"zone": "寒冷", "wind": "东北", "note": "冬冷夏热，重视保温与通风。"},
    "济南": {"zone": "寒冷", "wind": "西南", "note": "冬冷夏热，重视保温。"},
    "宁波": {"zone": "夏热冬冷", "wind": "东南", "note": "沿海湿热，重视防潮通风。"},
    "东莞": {"zone": "夏热冬暖", "wind": "东南", "note": "湿热台风，重视抗风通风。"},
    "佛山": {"zone": "夏热冬暖", "wind": "东南", "note": "同广州，重视隔热通风。"},
    "无锡": {"zone": "夏热冬冷", "wind": "东南", "note": "同苏州，重视通风海绵。"},
    "合肥": {"zone": "夏热冬冷", "wind": "东南", "note": "夏热冬冷，重视遮阳通风。"},
    "南昌": {"zone": "夏热冬冷", "wind": "西北", "note": "夏热冬冷，重视通风。"},
    "贵阳": {"zone": "温和", "wind": "静风", "note": "温和湿润，重视通风防潮。"},
    "南宁": {"zone": "夏热冬暖", "wind": "东南", "note": "湿热，重视通风防潮。"},
    "海口": {"zone": "夏热冬暖", "wind": "东南", "note": "热带，台风多，强抗风通风。"},
    "兰州": {"zone": "寒冷", "wind": "西北", "note": "干燥寒冷，重视保温与风沙防护。"},
    "太原": {"zone": "寒冷", "wind": "西北", "note": "冬冷夏热，重视保温。"},
    "石家庄": {"zone": "寒冷", "wind": "西北", "note": "冬冷夏热，重视保温与雾霾扩散。"},
}


def load_policy_db(path=None):
    path = path or DEFAULT_POLICY_DB
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def region_from_reverse(display_name):
    if not display_name:
        return None
    for key in MAJOR_CITIES:
        if key in display_name:
            return key
    for prov in ["北京", "上海", "天津", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
                 "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
                 "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
                 "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门"]:
        if prov in display_name:
            return prov
    return None


def policy_for_region(region, db):
    """按 region（城市名/省名）匹配属地政策。db 可传完整 JSON 或 regions 子表；
    优先按别名（aliases）匹配，未命中回退 other（全国通用基准）。region 为空也回退 other。"""
    if not db:
        return None
    regions = db.get("regions", db) if isinstance(db, dict) else {}
    if not region:
        return regions.get("other")
    for key, val in regions.items():
        if key in region or region in key:
            return val
        for alias in (val.get("aliases") or []):
            if alias and (alias in region or region in alias):
                return val
    return regions.get("other")


def city_climate(region):
    return MAJOR_CITIES.get(region)


# ---------------------------------------------------------------------------
# 规划专项：建议 & merge 片段（city-planner 口径）
# ---------------------------------------------------------------------------

def build_suggestions(region, city, metrics, policy):
    sugg = []
    if policy:
        rn = policy.get("name", region or "属地")
        sugg.append(
            f"属地 {rn}：绿色建筑最低 {policy.get('green_star','—')}；"
            f"装配率建议 ≥{policy.get('prefab_rate','—')}%；"
            f"新能源车位 ≥{policy.get('new_energy','—')}%；"
            f"海绵城市径流控制率 ≥{policy.get('sponge','—')}%。"
        )
        for note in policy.get("notes", []) or []:
            sugg.append(f"属地提示：{note}。")
    if city:
        sugg.append(f"气候区【{city['zone']}】，主导风向 {city['wind']}：{city['note']}。")
    area, per, _, orient = metrics
    cat = "小型地块" if area < 5000 else ("中型地块" if area < 30000 else "大型地块")
    if area > 0:
        sugg.append(
            f"红线面积约 {area:,.0f}㎡（{cat}），周长 {per:,.0f}m，主轴朝向约 {orient:.0f}°（正北为 0°）。"
            f"建议结合路网与景观定主要轴线，并衔接控规路网与用地布局。"
        )
    # —— 规划专项 ——
    sugg.append(
        "落实「三区三线」：建设应落位城镇开发边界内，避让生态保护红线与永久基本农田；"
        "生态/农业空间严格管控，不得擅自占用。"
    )
    sugg.append(
        "衔接上位规划与控规：开发强度（容积率/建筑密度/高度/绿地率）须符合总规、专项规划与控规图则；"
        "用地性质按 GB 50137 编码（大类/中类）与周边相容。"
    )
    sugg.append(
        "社区营造：按 15 分钟生活圈配置教育、医疗、养老、文化、体育、商业等公共服务与绿地，"
        "提升步行可达与混合利用。"
    )
    sugg.append(
        "请在规划 JSON 的 basis 显式引用上述属地与上位规划规定；indicators 已预置地方底线供脚本核对。"
    )
    return sugg


def merge_fragment(region, policy):
    """供 build_report.py 注入的片段（规划指标口径）。"""
    rn = policy.get("name", region or "属地") if policy else (region or "属地")
    basis = [
        f"三区三线管控（{rn}，须核对属地现行规划）：建设应落位城镇开发边界内，"
        f"避让生态保护红线与永久基本农田，生态/农业空间严格管控。",
        f"上位规划衔接（{rn}）：开发强度、用地性质、配套设施须符合国土空间总规、"
        f"专项规划与控规图则（GB 50137 用地分类）。",
    ]
    if policy:
        basis.append(
            f"属地政策（{rn}，需核对现行规定）：绿建最低 {policy.get('green_star','—')}；"
            f"装配率 ≥{policy.get('prefab_rate','—')}%；新能源车位 ≥{policy.get('new_energy','—')}%；"
            f"海绵城市径流控制率 ≥{policy.get('sponge','—')}%。"
        )
        for note in policy.get("notes", []) or []:
            basis.append(f"属地提示：{note}（以 {rn} 现行规定为准）。")
    indicators = [
        {"category": "空间管控", "name": "三区三线衔接", "unit": "—", "recent": "—", "future": "—",
         "attr": "约束性", "note": f"{rn}：城镇开发边界内建设，避让生态/农业空间"},
        {"category": "开发强度", "name": "容积率", "unit": "—", "recent": "—", "future": "—",
         "attr": "预期性", "note": f"{rn}：衔接控规/密度分区"},
        {"category": "开发强度", "name": "建筑密度", "unit": "%", "recent": "—", "future": "—",
         "attr": "预期性", "note": f"{rn}：按控规"},
        {"category": "开发强度", "name": "绿地率", "unit": "%", "recent": "—", "future": "—",
         "attr": "约束性", "note": f"{rn}：≥30（新区）/≥25（旧区）"},
        {"category": "公共服务", "name": "15分钟生活圈配套覆盖率", "unit": "%", "recent": "—", "future": "—",
         "attr": "预期性", "note": "社区公服步行可达覆盖"},
        {"category": "绿色低碳", "name": "绿建星级", "unit": "级", "recent": "—", "future": "—",
         "attr": "约束性", "note": f"{rn}属地底线 ≥{policy.get('green_star','—')}" if policy else "约束性"},
    ]
    return {"basis": basis, "indicators": indicators}


# ---------- 周边分析（OpenStreetMap Overpass，联网可选） ----------
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QL = """[out:json][timeout:25];
(
  node["amenity"~"^(school|kindergarten|university|college|hospital|clinic|doctors|dentist|pharmacy|bank|post_office|restaurant|cafe|marketplace)$"](around:{radius},{lat},{lng});
  node["shop"](around:{radius},{lat},{lng});
  node["leisure"~"^(park|garden|playground|pitch|sports_centre|recreation_ground)$"](around:{radius},{lat},{lng});
  node["highway"="bus_stop"](around:{radius},{lat},{lng});
  node["railway"~"^(station|halt|subway_entrance|train_station|tram_stop)$"](around:{radius},{lat},{lng});
  node["public_transport"="station"](around:{radius},{lat},{lng});
  node["amenity"="ferry_terminal"](around:{radius},{lat},{lng});
);
out body;"""

_CAT_LABELS = {"education": "教育", "medical": "医疗", "commercial": "商业", "green": "公园绿地", "transit": "交通"}


def _categorize(tags):
    a = tags.get("amenity", "")
    if a in ("school", "kindergarten", "university", "college"):
        return "education"
    if a in ("hospital", "clinic", "doctors", "dentist", "pharmacy"):
        return "medical"
    if tags.get("railway") in ("station", "halt", "subway_entrance", "train_station", "tram_stop") \
       or tags.get("public_transport") == "station" or a == "ferry_terminal" or tags.get("highway") == "bus_stop":
        return "transit"
    if tags.get("leisure") in ("park", "garden", "playground", "pitch", "sports_centre", "recreation_ground"):
        return "green"
    if tags.get("shop") or a in ("bank", "post_office", "restaurant", "cafe", "marketplace"):
        return "commercial"
    return None


def query_overpass(lat, lng, radius=1000):
    ql = OVERPASS_QL.format(lat=lat, lng=lng, radius=radius)
    data = urllib.parse.urlencode({"data": ql}).encode("utf-8")
    req = urllib.request.Request(OVERPASS_URL, data=data, headers={"User-Agent": "city-planner-site-analyze/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8")).get("elements", [])


def analyze_surroundings(lat, lng, radius=1000):
    """联网检索地块周边 15 分钟生活圈配套（OpenStreetMap）。失败则降级，不阻断主流程。"""
    try:
        els = query_overpass(lat, lng, radius)
    except Exception as e:
        return {"ok": False, "error": str(e), "counts": {},
                "summary": f"周边分析需联网（OpenStreetMap），本次未执行：{e}；15 分钟生活圈配套请自行补充现状调研。"}
    counts = {}
    for el in els:
        c = _categorize(el.get("tags", {}))
        if c:
            counts[c] = counts.get(c, 0) + 1
    summary = _surroundings_summary(counts, radius)
    return {"ok": True, "counts": counts, "summary": summary}


def _surroundings_summary(counts, radius):
    edu = counts.get("education", 0); med = counts.get("medical", 0)
    com = counts.get("commercial", 0); grn = counts.get("green", 0); trn = counts.get("transit", 0)
    lines = [f"以地块为中心 {radius} m（约 15 分钟步行）范围内，OSM 检索到：教育 {edu} 处、医疗 {med} 处、"
             f"商业服务 {com} 处、公园绿地 {grn} 处、交通站点 {trn} 处。"]
    has = [n for k, n in _CAT_LABELS.items() if counts.get(k)]
    if len(has) >= 4:
        lines.append("配套较为完整，基本满足 15 分钟生活圈「教育-医疗-商业-绿地-交通」复合需求，可作社区生活圈覆盖佐证。")
    elif has:
        lines.append(f"当前检索到{'、'.join(has)}，其余类型建议补充现状调研或核对属地公共服务设施规划，勿仅以 OSM 覆盖判定达标。")
    else:
        lines.append("范围内 OSM 设施稀疏，可能为新建区/产业园区或数据缺失；生活圈配套须以实地调研与控规公服配置为准。")
    return "\n".join(lines)


def build_site_assessment(region, city, policy, surroundings):
    """生成结构化「场地研判」要点：区位 / 交通 / 配套 / 底线 / 风险。"""
    rn = (policy or {}).get("name", region or "属地")
    items = []
    zone = f"，气候区【{city['zone']}】" if city else ""
    items.append(f"区位：位于{rn}{zone}；建议结合区域战略与上位规划明确项目定位。")
    counts = (surroundings or {}).get("counts", {})
    if surroundings and surroundings.get("ok"):
        trn = counts.get("transit", 0)
        items.append(f"交通：15 分钟范围检索到轨道/公交站点 {trn} 处" +
                     ("，对外联系与公交接驳基础较好。" if trn > 0 else "，公共交通覆盖较弱，需重点校核慢行与公交接驳。"))
    else:
        items.append("交通：联网周边分析未执行，公交/轨道可达性请结合现状路网与轨道规划校核。")
    if surroundings and surroundings.get("ok"):
        items.append("配套：" + surroundings.get("summary", "").split("\n")[-1])
    items.append("底线：落实三区三线（城镇开发边界内建设，避让生态/农业空间）；开发强度与用地性质衔接控规图则（GB 50137）。")
    if policy:
        items.append(f"属地底线：绿建≥{policy.get('green_star')}、装配率≥{policy.get('prefab_rate')}%、"
                     f"新能源车位≥{policy.get('new_energy')}%、海绵≥{policy.get('sponge')}%（以{rn}现行规定为准）。")
    items.append("风险：定位与红线几何为估算/辅助结果，最终以勘测坐标与图面为准；周边配套来自 OSM，存在数据缺失，须实地校核。")
    return items


# ---------------------------------------------------------------------------
# 地图 HTML
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>规划用地地图</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  html,body{margin:0;height:100%;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
  #map{height:100%}
  .side{position:absolute;top:10px;right:10px;z-index:1000;width:280px;max-height:90%;overflow:auto;
        background:#fff;padding:12px 14px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.2);font-size:13px}
  .side h1{font-size:15px;margin:0 0 6px}
  .side h2{font-size:13px;margin:12px 0 4px;color:#1b5e20}
  .side p{margin:3px 0;line-height:1.5}
  .side ul{margin:3px 0;padding-left:18px}
  .side .tag{display:inline-block;background:#e8f5e9;color:#1b5e20;border-radius:4px;padding:1px 6px;margin:1px}
</style>
</head>
<body>
<div id="map"></div>
<div class="side">
  <h1>规划用地地图</h1>
  <p><b>位置：</b>__ADDR__</p>
  <p><b>坐标：</b>__LAT__, __LNG__</p>
  <p><b>红线面积：</b>__AREA__ ㎡　<b>周长：</b>__PERI__ m</p>
  <p><b>主轴朝向：</b>__ORI__°（正北为 0°）</p>
  <p><b>气候区：</b>__CLIMATE__</p>
  <h2>规划建议</h2>
  <ul>__SUGG__</ul>
  <p style="color:#777;font-size:11px">底图 © OpenStreetMap；红线为估算落位，请以勘测坐标为准。</p>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  var center = [__LAT__, __LNG__];
  var map = L.map('map').setView(center, 15);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
    {{maxZoom:19, attribution:'© OpenStreetMap'}}).addTo(map);
  L.marker(center).addTo(map).bindPopup('定位点：__ADDR__');
  var redlines = __REDLINES__;
  function styleRed(){{return {{color:'#d32f2f', weight:3, fillColor:'#ffcdd2', fillOpacity:.35}};}}
  redlines.forEach(function(r){{
    var pts = r.map(function(p){{return [p[0], p[1]];}});
    L.polygon(pts, styleRed()).addTo(map);
  }});
  if (redlines.length) {{
    var all = []; redlines.forEach(function(r){ all = all.concat(r); });
    map.fitBounds(all.map(function(p){return [p[0],p[1]];}));
  }}
</script>
</body>
</html>
"""


def build_map_html(brief, redlines):
    loc = brief.get("location", {})
    geo = brief.get("geometry", {})
    climate = brief.get("climate") or "—"
    sugg = "".join(f"<li>{html.escape(s)}</li>" for s in (brief.get("suggestions") or []))
    return (
        HTML_TEMPLATE
        .replace("__ADDR__", html.escape(loc.get("address") or "—"))
        .replace("__LAT__", str(loc.get("lat")))
        .replace("__LNG__", str(loc.get("lng")))
        .replace("__AREA__", f"{geo.get('area_m2',0):,.0f}")
        .replace("__PERI__", f"{geo.get('perimeter_m',0):,.0f}")
        .replace("__ORI__", f"{geo.get('orientation_deg',0):.0f}")
        .replace("__CLIMATE__", html.escape(climate))
        .replace("__SUGG__", sugg)
        .replace("__REDLINES__", json.dumps([[list(p) for p in r] for r in redlines], ensure_ascii=False))
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="规划用地红线定位与地图生成（city-planner）")
    ap.add_argument("--dxf", help="红线 DXF/DWG 文件路径")
    ap.add_argument("--image", help="红线图片/PDF 截图（尝试自动 OCR 坐标）")
    ap.add_argument("--coords", help="中心点经纬度，格式 'lng,lat' 或 'lat,lng'（自动判向）")
    ap.add_argument("--address", help="地名/地址，用 Nominatim 地理编码")
    ap.add_argument("--area", type=float, help="已知用地面积(㎡)，无红线时估算用")
    ap.add_argument("--epsg", help="红线投影坐标系 EPSG（如 4547=CGCS2000 高斯），缺省按经纬度")
    ap.add_argument("--outdir", default="./site", help="输出目录，默认 ./site")
    ap.add_argument("--policy-db", help="地方政策库 JSON 路径")
    ap.add_argument("--no-map", action="store_true", help="不生成 site_map.html")
    ap.add_argument("--no-surroundings", action="store_true", help="跳过联网周边分析（OpenStreetMap）")
    ap.add_argument("--radius", type=int, default=1000, help="周边分析步行半径(米)，默认 1000（约 15 分钟）")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    lat = lng = None
    redlines = []

    # 1) 定位
    if args.coords:
        parts = [float(x) for x in re.split(r"[,\s]+", args.coords.strip()) if x]
        if len(parts) >= 2:
            a, b = parts[0], parts[1]
            # 经度范围 [-180,180]，纬度 [-90,90]；通常用户输入 lng,lat
            if abs(a) <= 90 and abs(b) > 90:
                lat, lng = a, b
            else:
                lng, lat = a, b
    elif args.address:
        try:
            lat, lng = geocode(args.address)
            print(f"[定位] 地址「{args.address}」→ {lat}, {lng}")
        except Exception as e:
            print(f"[错误] 地理编码失败：{e}")
            sys.exit(1)

    if lat is None or lng is None:
        print("[错误] 必须提供 --coords 或 --address 以定位地块。")
        sys.exit(1)

    # 2) 红线
    if args.dxf:
        redlines = load_dxf(args.dxf, args.epsg)
        print(f"[红线] 从 DXF 解析到 {len(redlines)} 条闭合线段")
    elif args.image:
        cands, msg = ocr_coords_from_image(args.image)
        print(f"[OCR] {msg}")
        if cands:
            print("[OCR] 从图中识别到候选坐标（仅供参考，务必复核）：")
            for lat, lng in cands:
                print(f"      约 lat={lat:.4f}, lng={lng:.4f}（如需采用，改用 --coords {lng},{lat}）")
        else:
            print("[OCR] 未识别到可信坐标；请用 --coords 或 --address 手动指定。")
        # 图片无法自动得到红线几何，仅作定位辅助

    # 3) 几何指标
    if redlines:
        outer = max(redlines, key=lambda r: ring_area_m2(r))
        area = ring_area_m2(outer)
        peri = ring_perimeter_m(outer)
        ori = ring_orientation_deg(outer)
    else:
        area = args.area or 0.0
        peri = 0.0
        ori = 0.0
    geometry = {"area_m2": area, "perimeter_m": peri, "orientation_deg": ori}

    # 4) 区域 / 政策 / 气候
    try:
        display = reverse_geocode(lat, lng)
    except Exception:
        display = ""
    region = region_from_reverse(display)
    db = load_policy_db(args.policy_db)
    policy = policy_for_region(region, db)
    city = city_climate(region)
    climate = city["zone"] if city else "—"

    metrics = (area, peri, 0.0, ori)
    suggestions = build_suggestions(region, city, metrics, policy)

    # 4.5) 周边分析（联网，可跳过）
    surroundings = None
    if not args.no_surroundings:
        print(f"[周边] 检索 {args.radius} m 内 OpenStreetMap 配套…")
        surroundings = analyze_surroundings(lat, lng, args.radius)
        if surroundings.get("ok"):
            print(f"[周边] 完成：{surroundings.get('summary', '').splitlines()[0]}")
        else:
            print(f"[周边] 未执行：{surroundings.get('error', '未知')}")
    else:
        surroundings = {"ok": False, "counts": {}, "summary": "已用 --no-surroundings 跳过周边分析。"}
    site_assessment = build_site_assessment(region, city, policy, surroundings)

    brief = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": {
            "dxf": os.path.basename(args.dxf) if args.dxf else None,
            "image": os.path.basename(args.image) if args.image else None,
            "coords": args.coords,
            "address": args.address,
            "epsg": args.epsg,
        },
        "location": {
            "lat": lat, "lng": lng,
            "address": args.address or display or "—",
            "province": region, "city": region,
            "display_name": display,
        },
        "geometry": geometry,
        "climate": climate,
        "region": region,
        "policy": policy,
        "surroundings": surroundings,
        "site_assessment": site_assessment,
        "suggestions": suggestions,
        "merge": merge_fragment(region, policy),
    }

    # 5) 输出
    brief_path = os.path.join(args.outdir, "site_brief.json")
    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=2)
    print(f"[产出] site_brief.json → {brief_path}")

    if not args.no_map:
        html_path = os.path.join(args.outdir, "site_map.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(build_map_html(brief, redlines))
        print(f"[产出] site_map.html  → {html_path}")

    print("\n=== 场地简报（规划口径）===")
    print(f"位置：{brief['location']['address']}（{region or '未知属地'}）")
    print(f"坐标：{lat}, {lng}")
    print(f"红线面积：{area:,.0f}㎡　周长：{peri:,.0f}m　朝向：{ori:.0f}°")
    print(f"气候区：{climate}")
    if surroundings and surroundings.get("ok"):
        print("\n周边配套（15 分钟生活圈，OSM）：")
        print(f"  {surroundings.get('summary', '').splitlines()[0]}")
        print(f"  {surroundings.get('summary', '').splitlines()[-1] if len(surroundings.get('summary', '').splitlines()) > 1 else ''}")
    print("\n场地研判：")
    for s in site_assessment:
        print(f"  - {s}")
    print("\n规划建议：")
    for s in suggestions:
        print(f"  - {s}")


if __name__ == "__main__":
    main()
