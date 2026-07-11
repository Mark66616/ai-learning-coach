# AI Learning Coach

一套面向 WorkBuddy 的 AI 辅助学习方法集合 Skill，提供六种可独立调用的学习方法，覆盖从路径设计到理解验证的完整学习闭环。每种方法都融入了学习科学环节（预习评估、刻意练习、错误日志、间隔重复复习、元认知复盘），并配套静态校验与可配置的真实 Agent 行为测试。

## 核心特点

- **方法集合，而非流程流水线**：六个方法可独立触发，不强制走完整个流程。
- **主文件只负责路由**：`SKILL.md` 根据用户意图选择最匹配的一种方法，选定后完整读取对应 reference 执行。
- **契约驱动**：每个方法都有明确的「何时使用 / 必要输入 / 执行流程 / 输出契约 / 边界情况 / 禁止事项」，可被静态校验。
- **零第三方依赖**：校验与行为测试脚本只使用 Python 标准库。
- **可配置 Agent 测试**：支持对接任意可通过命令行启动的 Agent（如 Codex）执行行为场景。

## 六种学习方法

| 方法 | 解决的问题 | 典型输入 |
|---|---|---|
| [学习阶梯](skills/ai-learning-coach/references/learning-ladder.md) | 从新手逐步达到熟练或精通 | 主题、当前水平、目标水平 |
| [聚焦学习计划](skills/ai-learning-coach/references/focused-learning-plan.md) | 在有限时间内聚焦高价值内容 | 主题、已有基础、可用时间 |
| [苏格拉底评估](skills/ai-learning-coach/references/socratic-assessment.md) | 通过逐题回答检查掌握情况 | 测试主题、范围或刚学内容 |
| [一页速查表](skills/ai-learning-coach/references/one-page-cheat-sheet.md) | 把主题压缩成便于复习的一页 | 主题、使用场景或已学范围 |
| [资源筛选](skills/ai-learning-coach/references/resource-curation.md) | 找少而精且当前可用的学习资源 | 主题、水平、偏好或限制 |
| [费曼验证](skills/ai-learning-coach/references/feynman-validation.md) | 用自己的话讲解并暴露理解缺口 | 概念、用户自己的讲解 |

### 方法选择规则

- 用户明确指定方法时，直接采用对应方法。
- 用户未指定时，根据目标与阶段只选择最相关的一种方法；仅当缺失信息会显著改变结果时提问，且一次只问一个关键问题。
- 互动式方法（苏格拉底评估、费曼验证）每轮只执行当前动作，等待用户真实回答后再继续，不模拟用户回答。
- 完成后默认只推荐一个最相关的下一步。

## 项目结构

```text
ai-learning-coach/
├── skills/
│   └── ai-learning-coach/
│       ├── SKILL.md                      # 主文件：路由与通用约束
│       ├── references/                   # 六种方法的详细契约
│       │   ├── learning-ladder.md
│       │   ├── focused-learning-plan.md
│       │   ├── socratic-assessment.md
│       │   ├── one-page-cheat-sheet.md
│       │   ├── resource-curation.md
│       │   └── feynman-validation.md
│       ├── scripts/                      # 校验与行为测试脚本
│       │   ├── validate_skill.py
│       │   └── run_behavior_tests.py
│       └── tests/                        # 行为基线与场景
│           ├── baseline.md
│           ├── scenarios.json
│           └── README.md
├── harness-engine/                       # pytest 学习实践产物
├── docs/                                 # 设计文档与优化计划
├── pyproject.toml
├── LICENSE
└── README.md
```

## 使用方式

在 WorkBuddy 对话中使用以下关键词即可触发对应方法：

| 触发意图 | 关键词示例 |
|---|---|
| 学习阶梯 | 「学习阶梯」「学习路径」「怎么进阶」 |
| 聚焦学习计划 | 「学习计划」「二八学习」「限时学习」 |
| 苏格拉底评估 | 「考考我」「自测」「苏格拉底」 |
| 一页速查表 | 「速查表」「一页纸」「复习卡」 |
| 资源筛选 | 「推荐资源」「学习资源」「资源筛选」 |
| 费曼验证 | 「费曼」「验证理解」「讲给你听」 |

## 安装

本 Skill 安装为用户级 Skill，位于 `~/.workbuddy/skills/ai-learning-coach/`。将项目中的 `skills/ai-learning-coach/` 目录复制到该路径即可被 WorkBuddy 识别。

## 测试与校验

### 环境要求

- Python ≥ 3.13（脚本仅依赖标准库，无需安装第三方包）

### 验证命令

```bash
# 1. 静态校验器自测
python3 skills/ai-learning-coach/scripts/validate_skill.py --self-test

# 2. 行为运行器自测
python3 skills/ai-learning-coach/scripts/run_behavior_tests.py --self-test

# 3. 校验 skill 结构与 scenarios.json
python3 skills/ai-learning-coach/scripts/validate_skill.py
```

### 运行真实 Agent 行为测试

每个 `--agent-arg` 对应启动参数数组中的一个元素，`{prompt}` 占位符会被替换为当前场景提示词：

```bash
python3 skills/ai-learning-coach/scripts/run_behavior_tests.py \
  --agent-arg codex \
  --agent-arg exec \
  --agent-arg=--skip-git-repo-check \
  --agent-arg '{prompt}'
```

### 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 全部硬断言通过 |
| 1 | 场景超时、Agent 非零退出、stdout 为空或断言失败 |
| 2 | 配置无效或未提供 Agent 命令 |

### 断言类型

- `contains` / `not_contains`：精确子串
- `regex`：Python 正则
- `max_questions`：限制问号总数
- `min_checkboxes`：未完成复选框最少数量
- `min_sessions` / `max_sessions`：学习次数边界
- `max_sections` / `max_content_chars`：速查表区块与字符预算

主观质量项放入 `manual_review`，不影响退出码。新增场景见 [`tests/README.md`](skills/ai-learning-coach/tests/README.md)。

## 通用约束

- 使用用户已提供的信息，不重复询问；不确定但不影响主要结果时，明确合理假设并继续。
- 练习任务和完成标准必须可观察、可检查。
- 涉及时效性资源、链接、版本或可用性时必须核验当前状态；无法核验时明确说明限制，不编造链接、可用性或「最新」结论。
- 复习时间建议可以给出；只有自动化工具实际成功后，才能声称提醒已创建。

## 适用 / 不适用

**适用于**：学习路径设计、限时学习计划、互动自测、知识压缩、学习资源筛选和理解验证。

**不适用于**：代写作业或考试答案、替用户完成应由其亲自进行的练习，以及与学习辅导无关的通用问答。

## 许可证

[MIT License](LICENSE) © 2026 Yves
