# 城市规划师 · AI 执行工作流（内部）

> 本节供 AI 执行时遵循，不在介绍页面向用户展示。目标是把用户给的项目资料，转成符合规划逻辑的 JSON，再用 `build_report.py` 产出 Word / PPT / 控规 CSV。全程保持"去 AI 味"：用规划从业者能直接用的语言沟通，不堆术语、不编造数值。

## 总体流程

1. **理清输入**：确认项目类型、上位规划、规划条件、红线/坐标（可选）、汇报场景（government / review / investment）。
2. **（可选）场地定位**：若用户给了红线图 / 坐标 / 地址，先跑 `site_analyze.py` 生成 `site_brief.json` + `site_map.html`，把属地政策与规划底线并入后续报告。
3. **组织 JSON**：按 `assets/outline-template.md` 的结构，把方案框架、目标、策略、指标、依据、合规整理成 JSON。
4. **生成成果**：用 `build_report.py` 输出 docx / pptx / csv。
5. **自检与交付**：核对 `compliance` 通过情况、控规指标阈值、四线内容；把成品路径与下一步建议告诉用户。

## 场地定位（可选但强烈推荐）

```bash
# DXF 红线 + 已知点坐标（最准）
python "<skill_dir>/scripts/site_analyze.py" --dxf 红线.dxf --coords "121.47,31.23" --outdir ./site

# 图片 / PDF 红线（自动 OCR，结果需复核）
python "<skill_dir>/scripts/site_analyze.py" --image 红线.png --outdir ./site

# 仅地址定位
python "<skill_dir>/scripts/site_analyze.py" --address "厦门市思明区环岛路XX地块" --outdir ./site

# 投影坐标（CGCS2000 高斯带，大数）务必加 --epsg
python "<skill_dir>/scripts/site_analyze.py" --dxf 红线.dxf --epsg 4547 --outdir ./site
```

产出 `site_brief.json` + `site_map.html`。`build_report.py --site ./site/site_brief.json` 会把：
- **basis** 并入「三区三线管控 / 上位规划衔接 / 属地政策（绿建星级、装配率、新能源、海绵）」等条目；
- **indicators** 并入「容积率 / 建筑密度 / 绿地率 / 15 分钟生活圈 / 三区三线」等规划指标行（数值初为 `—`，由用户在报告中填实，脚本按 `attr` 与 `merge` 注记提示底线）；
- **sections** 最前插入「场地定位与地图」章节。

新增强化的 `surroundings`（周边 15 分钟生活圈配套，经 OpenStreetMap Overpass 联网获取，失败则跳过）与 `site_assessment`（场地研判：区位 / 交通 / 配套 / 底线 / 风险）也会进入 `suggestions` 与地图侧栏。详见 `references/site-analysis.md`。

## 成果生成

把报告整理为 `build_report.py` 所需的 JSON，用 skill 目录**绝对路径**调用（bash 工作目录通常是项目根而非 skill 目录，相对路径会找不到）：

```bash
python "<skill_dir>/scripts/build_report.py" report.json --outdir ./output \
  [--site site_brief.json] \
  [--scenario government|review|investment]
```

- 含 `regulatory` 字段 → 额外导出控规指标表 CSV + 合规核对 CSV；
- 含 `four_lines` → 自动生成四线章节；
- `--no-docx` / `--no-pptx` / `--no-csv` 可关闭对应输出；
- `--body-font` / `--head-font` 跨平台字体（Windows 宋体 / 微软雅黑，macOS Songti SC / PingFang SC，Linux Noto Sans CJK SC，默认按系统自动）。

输入 JSON 结构（必备字段，详见 `assets/outline-template.md`）：

| 字段 | 说明 |
|---|---|
| `meta` | 标题、副标题、编制单位、日期、场景 |
| `basis` | 规划依据数组（法律 / 国标 / 地标 / 上位规划，含时效） |
| `sections` | 章节数组，含 `title` / `content` / `type` / `key_points` |
| `indicators` | 指标体系数组（category / name / unit / current / future / attr） |
| `compliance` | 合规自检数组（check / standard / attr / status） |
| `regulatory`（可选） | 控规地块表；触发 CSV 导出 |
| `four_lines`（可选） | 四线管控对象；触发四线章节 |

## 依赖与安装

首次使用或报 `ModuleNotFoundError` 时，一次性安装（已提供 `scripts/requirements.txt`）：

```bash
pip install -r "<skill_dir>/scripts/requirements.txt"
```

按需拆装：

- **必装**（Word / PPT / 控规 CSV）：`python-docx python-pptx`
- **场地分析**（DXF / 投影 / 图片 OCR）：`ezdxf pyproj pillow pytesseract`（OCR 还需系统安装 Tesseract OCR）
- **PDF / 红线识别**：`pymupdf`

缺可选依赖时脚本会给出友好提示并降级（如跳过 OCR、跳过 DXF），不影响坐标 / 地址定位路径。冒烟测试样例见 `scripts/example_report.json`（`python build_report.py example_report.json --outdir ./demo`）。

## 规划方法论（写前先读）

- `references/planning-framework.md`：8 步法 + 类型化模块（核心知识库）
- `references/indicators.md`：指标体系定义、口径与阈值库
- `references/standards-and-basis.md`：规划依据引用库（**写前核对时效**）
- `references/regulatory-plan.md`：GB 50137 用地编码 / 四线 / 开发强度 / 15 分钟生活圈 / 图则深度
- `references/local-policies.md` + `local_policy_db.json`：属地政策（**全国主要省 / 市**，以属地现行文件为准）
- `references/planning-principles.md`：规划设计基本原则与方法论

## 质量红线（务必遵守）

- 不编造规范编号、年份、具体数值；拿不准的标注"需核对当地最新规定"。
- 属地政策以 `local_policy_db.json` + `local-policies.md` 为准，且仅为代表性参考，落地前须核对现行文件。
- 指标阈值超 `limit` 时，`compliance` 标 `fail` 并在报告中提示，不擅自"美化"。
- 场地定位 / OCR / 联网周边分析均为辅助，最终以勘测坐标与图面为准。
