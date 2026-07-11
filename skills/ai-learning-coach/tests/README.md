# AI Learning Coach 测试

本目录保存静态契约的规则推演基线与可执行的 Agent 行为场景。所有脚本只使用 Python 标准库。

## 验证命令

```bash
python3 skills/ai-learning-coach/scripts/validate_skill.py --self-test
python3 skills/ai-learning-coach/scripts/run_behavior_tests.py --self-test
python3 skills/ai-learning-coach/scripts/validate_skill.py
```

前两个命令分别验证静态校验器和行为运行器自身；第三个命令校验当前 skill 结构及 `scenarios.json`。真实 Agent 行为测试需要显式传入命令参数。

## 运行真实 Agent

每个重复的 `--agent-arg` 都对应参数数组中的一个元素。某一个参数可以包含 `{prompt}`，运行器会在该参数中替换当前场景提示词；没有占位符时，提示词会作为最后一个参数追加。运行器使用参数数组直接启动进程，不经过 shell。

例如使用 Codex：

```bash
python3 skills/ai-learning-coach/scripts/run_behavior_tests.py \
  --agent-arg codex \
  --agent-arg exec \
  --agent-arg=--skip-git-repo-check \
  --agent-arg '{prompt}'
```

也可指定其他场景文件：

```bash
python3 skills/ai-learning-coach/scripts/run_behavior_tests.py \
  --scenarios /absolute/path/to/scenarios.json \
  --agent-arg /absolute/path/to/agent-wrapper \
  --agent-arg '{prompt}'
```

不要把 API token、密钥或完整敏感命令写入场景文件。诊断会脱敏名称包含 `TOKEN`、`KEY`、`SECRET` 或 `PASSWORD` 的环境变量值，并只保留 stderr 末尾 500 个字符。

## 退出码和结果

- `0`：全部硬断言通过。
- `1`：至少一个场景超时、Agent 非零退出、stdout 为空或包含非法 UTF-8 替换字符，或断言失败；运行器会继续执行其余场景。
- `2`：配置无效、未提供 Agent 命令，或命令不存在/无法启动。配置会在任何 Agent 场景执行前完整验证。

每条结果格式为 `[PASS|FAIL|ERROR] <id>: <summary>`。stdout 是唯一 Agent 响应来源；stderr 只用于失败诊断。`manual_review` 只提示需要人工判断的质量项，不影响退出码。

## 新增场景

在 `scenarios.json` 的 `scenarios` 数组追加对象，提供唯一的 `id`、非空 `description`、`prompt` 和 `assertions`。可选字段为正整数 `timeout_seconds` 与字符串数组 `manual_review`。随后依次运行静态校验器自测、行为运行器自测和静态常规校验。

断言仅支持：

- `contains`、`not_contains`：精确子串数组。
- `regex`：Python `re` 正则数组。
- `max_questions`：移除 fenced code block 与 Markdown 引用行后，限制 `?` 和 `？` 总数。
- `min_checkboxes`：移除 fenced code block 后，统计行首允许空白的未完成 `- [ ]`。
- `min_sessions`、`max_sessions`：移除 fenced code block 后，统计唯一的 `## 第 N 次学习` 阿拉伯数字编号。
- `max_sections`、`max_content_chars`：统计速查表一级标题后首个内容到自测问题区块结束的二级标题与 Unicode 码点；代码块、参考答案和复习时间表不计入。

硬断言只应检查稳定、确定性的文本或数量边界。诸如方法是否最合适、解释是否准确、资源是否优质、问题难度是否恰当等主观质量必须放进 `manual_review`，不要用脆弱关键词伪装成自动验收。

离线资源场景的硬断言只拦截明确的定位符结构：URI scheme、`www.`、Markdown 链接目标、IPv4/IPv6，以及带 `/path` 的域名（包括 Unicode 域名）。无路径裸域名可能与 `MCP.server` 之类点号标识符无法稳定区分，因此留给 `manual_review`，不作为硬失败。
