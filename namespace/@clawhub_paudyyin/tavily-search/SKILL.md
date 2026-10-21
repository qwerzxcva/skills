---
name: tavily-search
version: "1.0.0"
display_name: "联网搜索（tavily-search）"
display_name_en: "web search (tavily-search)"
description: "web search capability in the information retrieval and search domain. Use when the user wants to AI 优化的搜索接口，专为 Agent 场景设计，返回简洁相关的结果. Triggers: tavily-search, gemini、valyu. Not for requests unrelated to web search. Risk level L0. 中文触发：tavily-search、gemini、valyu。"
description_zh: "AI 优化的搜索接口，专为 Agent 场景设计，返回简洁相关的结果。（类别：四、信息获取与搜索类；风险等级：低）当用户需要联网搜索相关能力、或提到 tavily-search、gemini、valyu 时使用；与联网搜索无关的请求不要触发。"
description_en: "web search capability in the information retrieval and search domain. Use when the user wants to AI 优化的搜索接口，专为 Agent 场景设计，返回简洁相关的结果. Triggers: tavily-search, gemini、valyu. Not for requests unrelated to web search. Risk level L0."
agent_created: true
slug: tavily-search
displayName: "联网搜索（tavily-search）"
summary: "web search capability in the information retrieval and search domain. Use when the user wants to AI 优化的搜索接口，专为 Agent 场景设"
---

# 联网搜索（tavily-search）

## 用途

AI 优化的搜索接口，专为 Agent 场景设计，返回简洁相关的结果。

> 分类：四、信息获取与搜索类（information retrieval and search）  
> 技能类型：联网搜索  
> 风险等级：低  
> 门禁档位：**L0** — 只读 / 无副作用，可直接执行；仍遵守“先确认再改生产”的通用原则。

## 触发条件

- 用户提到 `tavily-search`、需要联网搜索能力，或提出对应诉求时触发。
- 典型触发词：tavily-search、AI 优化的搜索接口，专为 Agent 场景设计，返回简洁相关的结果。
- 关联技能：gemini、valyu。

## 何时不要使用

- 与联网搜索无关的请求：不要触发，交给更合适的技能或直接回答。
- 前置依赖未就绪（未授权 / 缺 CLI / 缺网络）时：**停下并报告**，不要降级为让用户粘贴明文凭据。
- 超出本技能声明范围的目标（其他系统、其他账号）：不越权操作。

## 功能清单

- 面向 Agent 优化的搜索接口
- 返回简洁、相关的搜索结果
- 支持研究型检索

## 标准操作流程

1. 明确查询意图与范围（地区、时间、来源），必要时先向用户澄清。
2. 优先使用免费/无需密钥的来源；需要密钥时走环境变量或密钥引用。
3. 对结果做去重与来源标注，不编造数据。
4. 多来源交叉验证关键事实（价格、天气、政策），给出置信度。
5. 以结构化摘要呈现，附可点击来源。

## 外部依赖与前置检查

- 依赖：Tavily API Key
- 执行前确认依赖已就绪（账号已授权 / CLI 已安装 / 环境变量已设置）。
- 凭据通过环境变量或密钥管理器注入，不落盘、不进版本控制。
- 详细配置见 `references/setup.md`。

## 典型使用场景

1. 需要高质量联网搜索结果
2. Agent 研究任务的数据获取

## 使用提示

需要申请 Tavily API Key。

## 备注

- 关联技能：gemini、valyu。
- 本技能由规划规格 README 自动落地生成，操作细节（具体 API/CLI/连接）应在接入真实运行时补全。
- 通用铁律：先验证现状 → 列影响面 → 取得确认 → 再执行；不可逆或涉钱/涉密的动作用最高门禁。
