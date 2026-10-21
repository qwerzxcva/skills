---
name: screenshot-reverse-engineer
description: Reverse-engineer webpage, app, mini-program, dashboard, and component screenshots into two deliverables: an AI/frontend engineering development prompt and a structured page function design document. Use when the user uploads or references UI screenshots and asks to analyze, restore, clone, document, or generate implementation prompts from visual pages, including single screenshots, multiple state screenshots, partial component screenshots, PC web, mobile H5, app, mini-program, and admin-system UI.
---

# Screenshot Reverse Engineer

## Overview

Use this skill to analyze UI screenshots objectively and produce:

1. An engineering development prompt for AI coding or frontend reconstruction.
2. A page function design document for product, design, and engineering collaboration.

Base every conclusion on visible screenshot evidence and user-provided notes. Do not invent unseen business logic, visual elements, or modules.

If no valid screenshot or screenshot description is provided, reply exactly:

```text
请上传页面截图，开始逆向分析并生成开发提示词与设计文档。
```

## Input Handling

Accept one or more of:

- Single page screenshot.
- Multiple screenshots of one page or multiple pages.
- State screenshots such as default, modal, loading, empty, error, selected, hover, active, or disabled states.
- User notes about terminal type, technology stack, business domain, target platform, or reconstruction fidelity.

For multiple screenshots, assign IDs before analysis:

- 截图 1：[page/state name]
- 截图 2：[page/state name]
- 截图 3：[page/state name]

Then decide whether they represent one page with multiple states or separate pages. Merge shared visual rules only when supported by the screenshots.

## Evidence Labels

Use these labels consistently:

- 【确定】: clearly visible and directly confirmable in the screenshot.
- 【估算】: visual parameters that can only be approximated, such as color, spacing, size, radius, font, shadow.
- 【推测】: behavior or business logic inferred from common UI patterns, not directly proven by the screenshot.
- 【待补充】: cannot be confirmed without more screenshots, product requirements, or design files.
- 【不适用】: the screenshot scope does not contain this item, such as page layout rules for a tiny component crop.

Never present 【估算】, 【推测】, or 【待补充】 as confirmed facts.

## Default Technology Stack

If the user does not specify a stack, use:

- PC Web: React + TypeScript + Tailwind CSS.
- Admin system: React + TypeScript + Ant Design-style components when the screenshot visually matches that pattern, marked 【推测】.
- Mobile H5: React or Vue with responsive layout.
- WeChat mini-program: native WeChat mini-program components or Taro, marked 【待补充】 unless specified.
- App UI: React Native or Flutter-style implementation notes, marked 【待补充】 unless specified.

If a component library or design system appears likely, mark it 【推测】, for example Ant Design, Element Plus, iOS native, or Material Design.

## Required Workflow

Follow this sequence:

1. Overall judgment: terminal, page type, business domain, visual style, scenario.
2. Screenshot state classification: default, detail, form, modal, loading, empty, error, selected, or multi-state.
3. Visual system breakdown: color, typography, radius, shadow, border, icon style, whitespace, density, brand tendency.
4. Functional module breakdown: top-to-bottom primary modules, submodules, and atomic functions.
5. Element and interaction analysis: buttons, inputs, filters, nav, tags, cards, tables, lists, modals, popovers, forms.
6. Layout architecture analysis: Flex, Grid, fixed sidebars, top nav, fluid layout, grid rules, responsive behavior.
7. State completion: hover, active, disabled, loading, empty, error, validation, selected, success where applicable.
8. Deliverable 1: engineering development prompt.
9. Deliverable 2: page function design document.

## Output Format

Use this exact top-level structure. If a section is not applicable, write 【不适用】 and explain briefly.

```markdown
---
# 第一部分：基础逆向研判（前置说明）

1. 适配终端：PC端 / 移动端 / 平板 / 微信小程序 / APP / 【待补充】
2. 页面类型：首页 / 列表页 / 表单页 / 详情页 / 弹窗 / 导航页 / 工作台 / 组件局部 / 【待补充】
3. 业务领域：后台管理 / 电商 / 办公协同 / 资讯 / 工具类 / 内容社区 / 数据分析 / 【待补充】
4. 截图状态：默认态 / 弹窗态 / 加载态 / 空状态 / 错误态 / 选中态 / 多状态组合 / 【待补充】
5. 整体视觉风格：简约商务 / 科技风 / 扁平化 / 移动端原生 / 数据看板 / 轻量工具 / 【估算】
6. 识别可信度说明：列出【估算】【推测】【待补充】区域

---
# 第二部分：工程开发提示词（可直接复制使用）

## 用途说明

本提示词用于 AI 复刻页面、编写前端代码、生成组件、还原 UI 样式与交互逻辑，适配主流前端技术栈。

## 开发提示词正文

请根据以下页面逆向分析结果，生成一个高还原度的前端页面。

### 1. 技术栈要求

- 默认使用：[根据输入或默认技术栈规则填写]
- 使用组件化开发方式
- 样式需模块化、可维护
- 页面需具备基础响应式能力
- 不引入截图中不存在的额外功能

### 2. 页面目标

- 页面终端：
- 页面类型：
- 业务场景：
- 复刻目标：尽量还原截图中的布局、视觉风格、模块结构、控件样式与基础交互

### 3. 全局视觉要求

- 主色：
- 背景色：
- 文本色：
- 边框色：
- 字体：
- 圆角：
- 阴影：
- 间距：

### 4. 布局要求

- 使用 [Flex / Grid / 固定侧栏 / 顶部导航 / 双栏布局 / 单列流式布局]
- 页面宽度、高度、滚动区域按截图结构实现
- 模块需按截图从上到下、从左到右排列
- 移动端需保持内容可读、控件可点击、无横向溢出

### 5. 模块清单

依次实现以下模块：

1. [模块名称]
   - 位置：
   - 功能：
   - 子元素：
   - 样式：
   - 交互：

2. [模块名称]
   - 位置：
   - 功能：
   - 子元素：
   - 样式：
   - 交互：

### 6. 控件要求

- 按钮：
- 输入框：
- 下拉选择：
- 表格 / 列表：
- 卡片：
- 图标：

### 7. 交互规则

- 点击交互：
- 悬浮交互：
- 表单交互：
- 切换交互：
- 弹窗交互：
- 滚动交互：

### 8. 输出要求

- 输出完整可运行页面代码
- 保持组件结构清晰
- 不添加截图中不存在的营销文案或额外模块
- 对无法确认的业务数据使用合理 mock 数据，并标注为模拟数据
- 保持视觉还原优先，其次是交互完整性

---
# 第三部分：页面功能设计文档

## 1. 整体风格规范

### 1.1 视觉风格定义

描述页面整体调性、视觉密度、版式特征、质感、光影、图标风格、留白规则、品牌倾向。

### 1.2 全局色彩规范

- 主色：
- 辅助色：
- 背景色：
- 卡片色：
- 文本主色：
- 文本次色：
- 边框色：
- 强调色：
- 成功色：
- 警告色：
- 错误色：

### 1.3 全局字体规范

- 字体家族：
- 一级标题：
- 二级标题：
- 正文：
- 辅助文本：
- 按钮文字：
- 表格文字：
- 行高规则：
- 字重规则：
- 对齐规则：

### 1.4 通用基础样式

- 标准圆角：
- 卡片圆角：
- 按钮圆角：
- 输入框圆角：
- 边框样式：
- 阴影样式：
- 分割线样式：
- 页面边距：
- 模块间距：
- 控件间距：

## 2. 整体架构与布局规则

- 布局类型：
- 页面结构：
- 栅格体系：
- 主要内容宽度：
- 侧栏 / 顶栏规则：
- 固定区域：
- 滚动区域：
- 响应式规则：
- 层级关系：

## 3. 核心功能模块拆解（自上而下排序）

### 模块1：[模块名称]

- 模块位置：
- 模块功能：
- 包含子元素：
- 样式特征：
- 数据内容：
- 状态说明：
- 交互规则：
- 识别可信度：

### 模块2：[模块名称]

- 模块位置：
- 模块功能：
- 包含子元素：
- 样式特征：
- 数据内容：
- 状态说明：
- 交互规则：
- 识别可信度：

## 4. 控件与交互设计

### 4.1 通用控件清单

- 按钮：
- 输入框：
- 搜索框：
- 下拉选择：
- 单选 / 复选：
- 标签：
- 图标：
- 卡片：
- 列表项：
- 表格：
- 分页：
- Tab：
- 弹窗：
- 浮层：
- Toast / 提示：
- 其他：

### 4.2 全量交互规则

1. 点击交互：
2. 悬浮状态：
3. 表单交互：
4. 切换 / 选项卡：
5. 弹窗 / 浮层：
6. 滚动 / 滑动：
7. 状态反馈：

## 5. 非功能约束与补充说明

- 适配要求：
- 浏览器 / 系统兼容建议：
- 组件复用建议：
- 可访问性建议：
- 性能建议：
- 数据 mock 规则：
- 截图识别限制：
- 待业务方确认事项：
- 待补充截图状态：
```

## Quality Rules

- Quantify colors, dimensions, font sizes, spacing, radius, and shadow where possible.
- Mark all uncertain visual values with 【估算】.
- Mark inferred interactions or business rules with 【推测】.
- Mark missing information with 【待补充】.
- Do not add modules, copy, data, or workflows not visible in screenshots unless the user explicitly provides them.
- For partial screenshots, still use the required output structure and mark page-level sections 【不适用】 where needed.
- For multiple screenshots, analyze each screenshot first, then merge common rules and state transitions.
- Mock data must be labeled as mock data and must not pretend to be real business data.
- Keep the engineering prompt concise and directly usable for AI coding.
- Keep the design document structured, reviewable, and implementation-oriented.
