# 城市规划师（city-planner）Skill

依据中国国土空间规划体系与现行国标（已做时效核查）的规划方案生成与成果交付全流程 Skill：从方案框架、合规保障、多场景适配到控规专项，一键产出可直接汇报的 **Word（docx）/ PPT（pptx）/ 控规指标 CSV**。

## 适用场景
- 规划方案构思与文本生成：战略 / 产业 / 文旅 / 城市更新 / 村庄 / 控规
- 规划依据梳理（法律/国标/地标/上位规划，含时效核查）与合规自检（用地编码/阈值/四线）
- 指标体系核算、开发强度与 15 分钟生活圈配套校核
- 政府汇报 / 专家评审 / 招商推介多场景适配，成果 docx / PPT / 控规 CSV 一键生成

## 内置知识
- `references/planning-framework.md`：规划通用框架（8 步法）+ 类型化模块（核心知识库）
- `references/indicators.md`：指标体系定义、口径与阈值库
- `references/standards-and-basis.md`：规划依据引用库（含时效核查）
- `references/regulatory-plan.md`：控规工作流（GB 50137 用地编码、四线管控、开发强度、15 分钟生活圈、图则深度）
- `references/site-analysis.md`：地块定位与地图工作流（DXF/图片红线解析、投影坐标坑、与 build_report.py 打通）
- `references/local-policies.md`：地方政策差异指引（按属地适配绿建/装配式/停车/海绵/日照等，全国主要省/市速查）
- `references/local_policy_db.json`：地方政策结构化库（覆盖全国主要省/市 + 全国通用 `other` 基准，按 `aliases` 匹配；绿建星级/装配率/新能源/海绵数值，供脚本读取，与 architect 共用）
- `references/planning-principles.md`：规划设计基本原则与方法论
- `assets/outline-template.md`：报告 JSON 提纲模板

## 使用方法
1. 在对话中描述项目（背景、上位规划、区位、类型、受众），本 Skill 会产出结构化方案并给 JSON。
2. （推荐）先定位红线，让建议按属地精准落地：
   ```bash
   pip install ezdxf            # DXF 解析（按需）
   python scripts/site_analyze.py --dxf 红线.dxf --coords "118.09,24.48" --outdir ./site
   # 图片/PDF：自动 OCR 识别坐标/地址（需 pip install pytesseract pillow pymupdf + Tesseract 引擎含 chi_sim）
   python scripts/site_analyze.py --image 红线.png --outdir ./site
   # 读图中坐标戳或地址后手动传（更稳）
   python scripts/site_analyze.py --address "厦门市思明区环岛路" --outdir ./site
   ```
   产出 `site_brief.json` + `site_map.html`（浏览器打开看红线位置与周边路网）。
   - 脚本在定位后会**联网检索周边 15 分钟生活圈配套**（OpenStreetMap：教育/医疗/商业/绿地/交通），自动产出「场地研判」要点；离线/被墙自动降级，可加 `--no-surroundings` 跳过，`--radius 1500` 调整步行半径。
3. 将方案 JSON 保存为 `report.json`，运行生成器（可注入定位简报）：
   ```bash
   pip install -r scripts/requirements.txt   # 一次性装齐全部依赖
   python scripts/build_report.py report.json --site ./site/site_brief.json --outdir ./out
   ```
4. 多场景与控规导出：
   ```bash
   python scripts/build_report.py report.json --scenario government   # 政府汇报蓝配色
   python scripts/build_report.py report.json --scenario review       # 专家评审绿配色
   python scripts/build_report.py report.json --scenario investment   # 招商推介红配色
   python scripts/build_report.py report.json --no-pptx               # 仅产出 docx + 控规 CSV
   ```
   - 字体按操作系统**自动选择**（Windows 微软雅黑/宋体、macOS PingFang SC/Songti SC、Linux Noto CJK），无需手动设置即可避免缺字显示异常。
   - 控规场景在 JSON 中填入 `regulatory` 字段，脚本额外导出 **GIS 可导入的控规指标 CSV** 与合规核对 CSV。
   - `scenario` 字段：命令行 `--scenario` 优先；命令行取默认值时回退到 JSON 中的 `scenario` 字段。

## 示例
- `scripts/example_report.json`：片区规划样例（含场地定位、规划依据、指标体系、控规字段与多场景标注）

## 规范时效
截至 2026-07，规划领域以 **国土空间规划体系 + 现行国标** 为准：用地分类以 **TD/T 1055 用地用海分类**、**GB 50137 城市用地分类与规划建设用地标准** 为准；强制性内容（三区三线、四线管控、公共安全）以属地现行国土空间规划与控规图则为准；具体阈值以原规范表与属地文件为准。引用时优先用现行有效版本，被替代的条文不得再单独引用。

## 发布 / 分发
- `name: city-planner`，`version: 1.1.0`
- 用 skill-creator 的 `package_skill.py` 打包为 zip 分发；或按 CodeBuddy skill 目录放置：
  - 用户级：`~/.codebuddy/skills/city-planner/`（跨项目可用）
  - 项目级：`.codebuddy/skills/city-planner/`（与团队共享）
