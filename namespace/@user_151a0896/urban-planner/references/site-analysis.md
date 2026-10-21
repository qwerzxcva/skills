# 地块定位与地图（city-planner 专项）

> 本文件说明如何用 `scripts/site_analyze.py` 把「用地红线 + 坐标/地址」转成可直接并入规划成果的**场地简报**与**交互地图**，并强调其与 architect skill 的**规划口径差异**：这里关注的是三区三线、开发强度、15 分钟生活圈、控规用地编码（GB 50137）、四线管控，而非单体建筑的体量策略。

## 一、为什么要做这一步（规划视角）

- **让规划依据落"地"**：规划文本里写"衔接上位规划、落实开发强度"，究竟落到哪个地块？定位后，属地政策、气候区、红线几何（面积/周长/朝向）都会进入 `basis` 与 `indicators`，方案有据可依、不空谈。
- **三区三线前置**：建设是否落位城镇开发边界内、是否避让生态/农业空间，应在方案起步就判断，而非送审时才补。
- **控规衔接**：用地性质编码（GB 50137）、开发强度（容积率/密度/高度/绿地率）、15 分钟生活圈配套，都依赖地块位置与面积。
- **成果可交互**：`site_map.html` 让业主/专家在浏览器直接看到地块落位、定位点与周边路网（OSM 底图），汇报更直观。

## 二、输入：你能提供什么

| 材料 | 形式 | 说明 |
|---|---|---|
| 用地红线 | DXF / DWG / CAD 截图 / PDF | DXF 最准；图片可自动 OCR 坐标注记或由 AI 读图后手动给坐标 |
| 坐标 | `lng,lat` 或 `lat,lng` | 红线上的已知点（图框注记、勘测点）；投影坐标（大数）加 `--epsg 4547` |
| 地址 | 地名/门牌 | Nominatim 反查经纬度与属地 |
| 面积 | ㎡ | 无红线时用于估算，配合 `--area` |

> 提示：哪怕只有「一张红线截图 + 大致地址」也能起步。AI 读图识别坐标/地址，再调脚本；若图中是投影坐标（如 40471234.5, 3540123.4），务必加 `--epsg 4547` 做高斯→WGS84 校正。

## 三、用法

```bash
# 1) DXF 红线 + 已知点坐标（推荐）
python scripts/site_analyze.py --dxf 红线.dxf --coords "121.47,31.23" --outdir ./site

# 2) 自动 OCR（图片/PDF 截图，结果需复核）
python scripts/site_analyze.py --image 红线.png --outdir ./site

# 3) AI 读图后手动给坐标
python scripts/site_analyze.py --coords "118.09,24.48" --outdir ./site

# 4) 仅地址定位
python scripts/site_analyze.py --address "厦门市思明区环岛路XX地块" --outdir ./site

# 5) 投影坐标精校正（CGCS2000 高斯带）
python scripts/site_analyze.py --dxf 红线.dxf --epsg 4547 --outdir ./site
```

**依赖**（按需安装）：`pip install ezdxf pyproj pillow pytesseract`（DXF 解析 / 投影转换 / 图片读取 / OCR；OCR 还需系统安装 Tesseract OCR）。缺依赖时脚本会给出友好提示，不影响坐标/地址定位路径。

**周边分析（联网可选）**：脚本在定位后会自动联网检索地块周边（默认 1000 m，约 15 分钟步行）的 OpenStreetMap 设施——教育、医疗、商业、公园绿地、交通站点，量化配套并给出生活圈覆盖判断。离线/被墙时自动降级，不阻断主流程；可加 `--no-surroundings` 完全跳过，`--radius 1500` 调整半径。

```bash
# 6) 跳过联网周边分析（无网络/被墙时）
python scripts/site_analyze.py --coords "118.09,24.48" --no-surroundings --outdir ./site

# 7) 自定义 15 分钟生活圈半径（如 1500 m）
python scripts/site_analyze.py --address "成都市天府新区XX地块" --radius 1500 --outdir ./site
```

## 四、产出

- `site_brief.json`：含 `location`（省/市、地址、经纬度）、`geometry`（面积/周长/朝向）、`climate`（气候区）、`region`、`policy`（属地政策）、`surroundings`（周边配套检索结果，含 `counts`/`summary`）、`site_assessment`（结构化场地研判：区位/交通/配套/底线/风险）、`suggestions`（规划建议）、`merge`（供 `build_report.py` 注入的片段）。
- `site_map.html`：浏览器打开，红线圈定地块、标记定位点，侧栏列出面积/朝向/气候区与规划建议。

## 五、merge 片段（规划口径，与 architect 不同）

`build_report.py` 加 `--site ./site/site_brief.json` 后，会把 `merge` 并入成果：

- **basis**（规划依据）：追加「三区三线管控」「上位规划衔接（总规/专项/控规图则）」「属地政策（绿建/装配率/新能源/海绵）」等条目，并显式标注属地名称与"以现行规定为准"。
- **indicators**（指标体系）：追加规划指标行（category/name/unit/recent/future/attr）：
  - 空间管控：三区三线衔接（约束性）
  - 开发强度：容积率 / 建筑密度 / 绿地率（衔接控规）
  - 公共服务：15分钟生活圈配套覆盖率（预期性）
  - 绿色低碳：绿建星级（约束性，属地底线）
  - 数值初为 `—`，供你在报告中填实际值；脚本会按 `attr` 与 `merge` 注记提示底线。
- **章节**：在 `sections` 最前插入「场地定位与地图」，含位置/几何/气候叙述、规划建议列表、打开 `site_map.html` 的提示。

## 六、与 architect/scripts/site_analyze.py 的差异

| 维度 | architect（建筑） | city-planner（规划） |
|---|---|---|
| 建议重点 | 体量策略、朝向/景观/噪声、绿建/装配率/新能源/海绵（单体） | 三区三线、开发强度、15 分钟生活圈、控规编码、四线 |
| merge 口径 | 建筑指标（绿建星级/装配率…） | 规划指标（容积率/绿地率/生活圈/三区三线） |
| 注入目标 | `build_design.py` | `build_report.py` |

两者共用同一份 `references/local_policy_db.json`（属地政策数值），但解读与落位口径不同：建筑关注单体强制要求，规划关注空间管控与公服配套。

## 七、坐标系统坑（务必看）

- **WGS84 vs CGCS2000**：OSM/Leaflet 用 WGS84；国内勘测常用 CGCS2000 高斯投影。若红线为投影坐标（X/Y 是大数，如 4xxxxxxx），必须 `--epsg 4547`（或对应带号）转换，否则落点会偏到海外。
- **图框注记**：CAD 图框常带带号（如 40 带），OCR 或 AI 读图时注意区分"带号+坐标"与"纯坐标"。
- **复核**：自动定位/识别结果都只是辅助，**最终以勘测坐标与图面为准**；脚本不会也无法保证红线几何的法定精度。
