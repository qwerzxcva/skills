# 规划报告 JSON 提纲模板（成果交付·一键产出）

> 告别熬夜调格式——本文件是 `scripts/build_report.py` 的输入模板：把报告整理成下面的 JSON，运行脚本即可一键产出 `<标题>.docx`、`<标题>.pptx`，含控规地块时还自动导出 `控规指标表.csv`（GIS 可导入）。
> 所有字段均可缺省；按需增删 `sections` 与各 `blocks`。直接复制下方示例、替换占位内容即可。

## 字段说明

| 字段 | 说明 |
|---|---|
| `title` | 报告主标题（封面+文件名） |
| `subtitle` | 副标题，如"策划建议书""控制性详细规划" |
| `client` | 委托/属地单位 |
| `date` | 日期，如 `2026-07` |
| `basis` | 规划依据条目数组（四类法，见 `references/standards-and-basis.md`） |
| `sections` | 章节数组，每章含 `chapter`(章名)、`intro`(可选导语)、`blocks`(内容块) |
| `sections[].blocks[].type` | `h`(二级标题)、`p`(段落)、`bullets`(项目符号)、`numbered`(编号)，后两者用 `items` 数组 |
| `indicators` | 指标体系数组：`category/name/unit/recent/future/attr` |
| `projects` | 重点项目库数组：`name/content/scale/period/owner` |
| `regulatory` | （可选）控规地块数组：`code/use_code/use_name/area/far/density/height/green/facility/note`；存在时自动生成「控规指标表」并导出 GIS 可导入的 CSV |
| `scenario` | （可选）成果场景：`standard` 通用 / `government` 政府汇报 / `review` 专家评审 / `investment` 招商推介；影响 PPT 强调色与封面标注（文风由 AI 按场景调整） |
| `four_lines` | （可选）四线管控数组：`type`(紫线/绿线/蓝线/黄线) / `scope`(管控范围) / `requirement`(管控要求)；存在时自动生成「四线管控」章节并标注管控要求 |

## 完整示例（可直接拿来跑）

```json
{
  "title": "厦门市思明东部发展战略规划",
  "subtitle": "策划建议书",
  "client": "厦门市思明区",
  "date": "2026-07",
  "scenario": "government",
  "basis": [
    "《中华人民共和国城乡规划法》（2019 修正版）",
    "《厦门市国土空间总体规划（2021—2035）》",
    "GB 50137-2011《城市用地分类与规划建设用地标准》",
    "TD/T 1062-2021《社区生活圈规划技术指南》"
  ],
  "sections": [
    {
      "chapter": "一、规划背景",
      "intro": "思明东部地处厦门岛东部，是岛内'更大提升'战略的核心承载区。",
      "blocks": [
        {"type": "h", "text": "1.1 宏观形势"},
        {"type": "p", "text": "两岸融合发展示范区建设提速，区域协同迎来新机遇。"},
        {"type": "bullets", "items": ["区位优越，滨海资源富集", "存量空间大，更新潜力突出"]},
        {"type": "numbered", "items": ["衔接'十五五'开局", "落实三区三线管控"]}
      ]
    },
    {
      "chapter": "二、目标定位",
      "blocks": [
        {"type": "h", "text": "2.1 总体定位"},
        {"type": "p", "text": "打造成为两岸融合示范、滨海活力的城市新客厅。"}
      ]
    }
  ],
  "indicators": [
    {"category": "空间", "name": "人均建设用地", "unit": "㎡/人", "recent": "≤110", "future": "≤100", "attr": "约束性"},
    {"category": "公服", "name": "15 分钟生活圈覆盖率", "unit": "%", "recent": "85", "future": "100", "attr": "预期性"}
  ],
  "projects": [
    {"name": "东部滨海活力带", "content": "岸线整治+慢行系统", "scale": "3.2 km", "period": "近期", "owner": "区住建局"}
  ],
  "regulatory": [
    {"code": "A-01", "use_code": "R2", "use_name": "二类居住用地", "area": "4.20", "far": "2.8", "density": "22", "height": "80", "green": "35", "facility": "12班幼儿园", "note": "轨交站点500m内"}
  ],
  "four_lines": [
    {"type": "绿线", "scope": "东侧滨海公园及防护绿地", "requirement": "绿线内用地不得改作他用，控规应规定绿化率指标与具体坐标"},
    {"type": "蓝线", "scope": "员当湖及入海沟渠", "requirement": "蓝线内禁止填埋占用、影响水系安全，控规规定保护要求与控制指标"},
    {"type": "紫线", "scope": "八卦楼等历史建筑", "requirement": "紫线内禁止大拆大建，建设须专家论证+公示+备案"}
  ]
}
```

## 运行

```bash
python "<本skill目录>/scripts/build_report.py" report.json --outdir ./output
# 只出 Word：加 --no-docx；只出 PPT：加 --no-pptx
# 含 regulatory 时默认导出「<标题>_控规指标表.csv」，并可导出「<标题>_合规核对.csv」（指标越界/千人指标配套预警），可加 --no-csv 关闭
# 多场景：--scenario government|review|investment 切换 PPT 配色与封面标注（需 JSON 含 scenario 字段或显式传参）
# 跨平台字体：--body-font "Songti SC" --head-font "PingFang SC"（macOS）/ --head-font "微软雅黑"（Windows 雅黑）
# 冒烟测试样例：scripts/example_report.json（含场景/四线/超长章节分页 + 控规地块示例）
# 缺依赖先：pip install python-docx python-pptx
```
