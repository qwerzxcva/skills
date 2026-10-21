# 用户场景记忆向导（taxonomy wizard）

> 配套 `mem_bridge.py taxonomy` 子命令。本文是**给 Agent 用的对话引导话术模板**：
> 当用户首次使用 keeper、或说"帮我规划记忆分类/我的记忆太乱"时，按下面四步在对话里引导他
> 生成一套**专属自己的记忆分类树**（而不是用我们预设的 investment/work/personal/project）。
> 目标：**让他高频的专属场景有独立分支、独立热位配额，不被通用问题稀释**。

---

## 一、为什么需要它（用户痛点）

用户常问的"量化回测技巧"和"今天聊的午饭"如果都堆在 `work` 里，高频的量化经验会被
通用记忆稀释——召回时排不到热位、衰减时一起被冷处理。用户专属分类树解决这个：
- 量化域有独立热位配额（如 ≤8），永远保住自己的热位；
- 子域（回测/风控/因子）让召回更精准；
- 每域独立留存策略（量化记忆可以比闲聊记忆活更久）。

---

## 二、引导四步（对话式，非问卷）

### Step 1 — 锚定身份（读 USER.md 已有信息，不重复问）
> "我记得你是做 **{roles}** 的，平时高频用到的是 **{scenarios}** 这类场景，对吧？
> 还有没有我漏掉、但你经常要我记的东西？"

预期产出：`user_profile.name / roles / scenarios`。

### Step 2 — 归并顶层域（3–6 个）
> "我们给记忆分几个大筐，我的建议是：**{建议的 3–6 个顶层域}**。
> 比如你最常用的是量化，那就单独一个『金融量化』筐，别和『工作杂项』混。
> 你觉得这几个筐够吗？要加/合并哪个？"

规则：
- 顶层域 **3–6 个**，超过 6 个会难维护、易走错分支。
- 每个顶层域给一个 `label`（中文名）+ `key`（英文/拼音短标识）。

### Step 3 — 配子域 + 关键词（每域 ≤4 子域）
> "『金融量化』这个筐里，你平时会反复记哪几类？比如 **回测 / 风控 / 因子**？
> 每类给我 2–3 个『一看到就知道归这类的词』，比如回测类你常说『滑点』『过拟合』。"

规则：
- 子域 **每域 ≤4 个**，防止树过深。
- 每个子域给 `label` + `key` + `keywords`（用于自动路由的命中词）。
- 这些关键词在 taxonomy 落地后**自动生效**：新记忆落库时会被自动归类，不必事后手动 `--reclassify`（后者仅用于 taxonomy 变更后的存量重路由）。

### Step 4 — 配配额与留存（防稀释 + 遗忘宽松度）
> "每个筐我建议给一个『热位上限』，量化这种高频的给 **8**、闲聊给 **3**，这样高频域不会被挤冷。
> 另外量化记忆很重要，我让它『**120 天没动才考虑归档、且重要性≥0.3**』才沉底，比默认的 90 天宽松些，行吗？"

规则：
- `heat_budget`：每域热位软上限（全局热位上限仍是 25，这里是每域配额）。
- `retention`：`{stale_days, min_importance}`——每域归档阈值，重要域可放宽。

---

## 三、生成 taxonomy.json（Agent 产出，用户确认后落地）

引导完后，Agent 生成如下 JSON（**先给用户看 `_format_taxonomy` 渲染结果确认，再 apply**）：

```json
{
  "version": 1,
  "created": "2026-07-26",
  "user_profile": {"name": "路人甲", "roles": ["量化", "开发", "小说"], "scenarios": ["回测", "Skill开发"]},
  "domains": [
    {"key": "quant", "label": "金融量化", "keywords": ["回测", "因子", "止损", "净值"],
     "heat_budget": 8, "retention": {"stale_days": 120, "min_importance": 0.3},
     "subdomains": [
        {"key": "backtest", "label": "回测", "keywords": ["滑点", "过拟合", "参数敏感性"]},
        {"key": "risk", "label": "风控", "keywords": ["仓位", "止损线", "最大回撤"]}
     ]},
    {"key": "novel", "label": "小说创作", "keywords": ["大纲", "人物", "情节"],
     "heat_budget": 5, "subdomains": []}
  ],
  "fallback_domain": "general"
}
```

### 落地命令（Agent 代执行）
```bash
# 1) 持久化（向导产物 → store/taxonomy.json，原子写+校验）
python mem_bridge.py taxonomy --apply --json /path/to/taxonomy.json
# 2) 查看确认
python mem_bridge.py taxonomy --show
# 3) 把现有记忆按新树重分类（先 dry-run 预览，再确认执行）
python mem_bridge.py taxonomy --reclassify --dry-run
python mem_bridge.py taxonomy --reclassify
```

---

## 四、行为约定（Advisory 模式）

- **reclassify 是 advisory（弱匹配也存）**：关键词命中即归类，未命中任何自定义域的记忆
  **保留原 domain**（绝不强行推到 fallback），不破坏 work/investment 等既定分类。
- **子域优先**：一条记忆同时命中子域词和顶层域词时，归到更具体的子域。
- **幂等**：reclassify 可重跑，已正确分类的记忆不再变更。
- **向后兼容**：`taxonomy.json` 不存在时，行为等同默认（KNOWN_DOMAINS），旧库零影响。
- **每域配额/留存** 在 P4 接入 `compute_thermal` / `reflect` 后才真正生效（见计划文档 P4）；
  当前 P2 阶段 reclassify 已能落 domain/subdomain + `sub:` 标签，子域检索（`recall --tag sub:`）立即可用。

---

## 五、示例：量化+小说用户的最终树

```
=== 用户记忆分类树（taxonomy）===

用户: 路人甲 | 角色: 量化、开发、小说 | 高频场景: 回测、Skill开发

- 金融量化（quant）  热位配额≤8  留存:120d/imp≥0.3
    - 回测（backtest）  关键词:滑点、过拟合、参数敏感性
    - 风控（risk）      关键词:仓位、止损线、最大回撤
- 小说创作（novel）  热位配额≤5

回退域(fallback): general
```
