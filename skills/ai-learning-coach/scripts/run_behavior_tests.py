#!/usr/bin/env python3
"""Run AI Learning Coach behavior scenarios against a configurable agent."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable


TEXT_ASSERTIONS = {"contains", "not_contains", "regex"}
COUNT_ASSERTIONS = {
    "max_questions",
    "min_checkboxes",
    "min_sessions",
    "max_sessions",
    "max_sections",
    "max_content_chars",
}
ALLOWED_ASSERTIONS = TEXT_ASSERTIONS | COUNT_ASSERTIONS
TOP_LEVEL_FIELDS = {"version", "scenarios"}
SCENARIO_FIELDS = {"id", "description", "prompt", "timeout_seconds", "assertions", "manual_review"}
SENSITIVE_NAME_RE = re.compile(r"TOKEN|KEY|SECRET|PASSWORD", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
SESSION_RE = re.compile(r"^##\s+第\s*(\d+)\s*次学习(?:\s*[:：].*)?\s*$", re.MULTILINE)
CHECKBOX_RE = re.compile(r"^\s*-\s+\[ \]", re.MULTILINE)
H2_RE = re.compile(r"^##\s+(.+?)\s*$")


def _diagnostic(level: str, scenario_id: str, summary: str) -> None:
    print(f"[{level}] {scenario_id}: {summary}")


def _redact(text: str) -> str:
    secrets = {
        value
        for name, value in os.environ.items()
        if value and SENSITIVE_NAME_RE.search(name)
    }
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def _stderr_summary(stderr: str | bytes | None) -> str:
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    redacted = _redact(stderr or "").strip()[-500:]
    return " ".join(redacted.splitlines())


def _without_fenced_code(text: str) -> str:
    kept: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        match = FENCE_RE.match(line)
        if fence is None and match:
            fence = match.group(1)[0]
            continue
        if fence is not None:
            if match and match.group(1)[0] == fence:
                fence = None
            continue
        kept.append(line)
    return "\n".join(kept)


def _question_count(text: str) -> int:
    visible = _without_fenced_code(text)
    visible = "\n".join(line for line in visible.splitlines() if not re.match(r"^\s*>", line))
    return visible.count("?") + visible.count("？")


def _cheat_sheet_content(text: str) -> str:
    """Extract H1 body through the self-test block, excluding answers/review/code."""
    lines = text.splitlines()
    h1_index = next((i for i, line in enumerate(lines) if re.match(r"^#\s+\S", line)), -1)
    selected: list[str] = []
    in_fence: str | None = None
    saw_self_test = False
    excluded_headings = {"参考答案", "复习时间表"}
    for line in lines[h1_index + 1 :]:
        fence_match = FENCE_RE.match(line)
        if in_fence is None and fence_match:
            in_fence = fence_match.group(1)[0]
            continue
        if in_fence is not None:
            if fence_match and fence_match.group(1)[0] == in_fence:
                in_fence = None
            continue
        heading = H2_RE.match(line)
        if heading:
            title = heading.group(1).strip()
            if title in excluded_headings:
                break
            if saw_self_test:
                break
            if title == "自测问题":
                saw_self_test = True
        selected.append(line)
    return "\n".join(selected).strip()


def _assertion_failures(response: str, assertions: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for expected in assertions.get("contains", []):
        if expected not in response:
            failures.append(f"missing required text {expected!r}")
    for forbidden in assertions.get("not_contains", []):
        if forbidden in response:
            failures.append(f"contains forbidden text {forbidden!r}")
    for pattern in assertions.get("regex", []):
        if re.search(pattern, response) is None:
            failures.append(f"regex did not match {pattern!r}")

    if "max_questions" in assertions:
        actual = _question_count(response)
        limit = assertions["max_questions"]
        if actual > limit:
            failures.append(f"questions {actual} exceed maximum {limit}")
    countable = _without_fenced_code(response)
    if "min_checkboxes" in assertions:
        actual = len(CHECKBOX_RE.findall(countable))
        limit = assertions["min_checkboxes"]
        if actual < limit:
            failures.append(f"checkboxes {actual} below minimum {limit}")
    session_count = len(set(SESSION_RE.findall(countable)))
    if "min_sessions" in assertions and session_count < assertions["min_sessions"]:
        failures.append(f"sessions {session_count} below minimum {assertions['min_sessions']}")
    if "max_sessions" in assertions and session_count > assertions["max_sessions"]:
        failures.append(f"sessions {session_count} exceed maximum {assertions['max_sessions']}")
    if "max_sections" in assertions or "max_content_chars" in assertions:
        content = _cheat_sheet_content(response)
        sections = sum(1 for line in content.splitlines() if H2_RE.match(line))
        if "max_sections" in assertions and sections > assertions["max_sections"]:
            failures.append(f"content sections {sections} exceed maximum {assertions['max_sections']}")
        chars = len(content)
        if "max_content_chars" in assertions and chars > assertions["max_content_chars"]:
            failures.append(f"content characters {chars} exceed maximum {assertions['max_content_chars']}")
    return failures


def _validate_config(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["top level must be an object"]
    for field in sorted(set(data) - TOP_LEVEL_FIELDS):
        errors.append(f"unknown top-level field: {field}")
    if type(data.get("version")) is not int or data.get("version") != 1:
        errors.append("version must be integer 1")
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list):
        errors.append("scenarios must be an array")
        return errors
    if not scenarios:
        errors.append("scenarios must not be empty")
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        label = f"scenarios[{index}]"
        if not isinstance(scenario, dict):
            errors.append(f"{label} must be an object")
            continue
        for field in sorted(set(scenario) - SCENARIO_FIELDS):
            errors.append(f"{label}: unknown field {field}")
        for field in ("id", "description", "prompt"):
            if not isinstance(scenario.get(field), str) or not scenario[field]:
                errors.append(f"{label}.{field} must be a non-empty string")
        scenario_id = scenario.get("id")
        if isinstance(scenario_id, str):
            if scenario_id in seen:
                errors.append(f"{label}.id is duplicate: {scenario_id}")
            seen.add(scenario_id)
        timeout = scenario.get("timeout_seconds", 120)
        if type(timeout) is not int or timeout <= 0:
            errors.append(f"{label}.timeout_seconds must be a positive integer")
        manual = scenario.get("manual_review", [])
        if not isinstance(manual, list) or any(not isinstance(item, str) for item in manual):
            errors.append(f"{label}.manual_review must be an array of strings")
        assertions = scenario.get("assertions")
        if not isinstance(assertions, dict):
            errors.append(f"{label}.assertions must be an object")
            continue
        for key, value in assertions.items():
            item_label = f"{label}.assertions.{key}"
            if key not in ALLOWED_ASSERTIONS:
                errors.append(f"{item_label} is unknown")
            elif key in TEXT_ASSERTIONS:
                if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                    errors.append(f"{item_label} must be an array of strings")
                elif key == "regex":
                    for pattern in value:
                        try:
                            re.compile(pattern)
                        except re.error as exc:
                            errors.append(f"{item_label} contains invalid regex {pattern!r} ({exc})")
            elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"{item_label} must be a non-negative integer")
    return errors


def _load_scenarios(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return None, [f"cannot read {path}: {exc}"]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [f"invalid JSON at line {exc.lineno}: {exc.msg}"]
    errors = _validate_config(data)
    return data if isinstance(data, dict) else None, errors


def _agent_command(agent_args: list[str], prompt: str) -> list[str]:
    placeholder_indexes = [i for i, arg in enumerate(agent_args) if "{prompt}" in arg]
    if placeholder_indexes:
        command = list(agent_args)
        index = placeholder_indexes[0]
        command[index] = command[index].replace("{prompt}", prompt)
        return command
    return [*agent_args, prompt]


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.kill()
        except ProcessLookupError:
            pass


def _run_agent(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_process_tree(process)
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            command[0],
            timeout,
            output=stdout,
            stderr=stderr,
        ) from exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def run_scenarios(path: Path, agent_args: list[str]) -> int:
    data, config_errors = _load_scenarios(path)
    if not agent_args:
        config_errors.append("agent command is not configured")
    placeholder_count = sum("{prompt}" in arg for arg in agent_args)
    if placeholder_count > 1:
        config_errors.append("{prompt} may appear in only one agent argument")
    if config_errors:
        for error in config_errors:
            _diagnostic("ERROR", "config", error)
        return 2
    assert data is not None

    executable = agent_args[0]
    if shutil.which(executable) is None:
        _diagnostic("ERROR", "infrastructure", "agent command was not found")
        return 2

    failed = False
    for scenario in data["scenarios"]:
        scenario_id = scenario["id"]
        command = _agent_command(agent_args, scenario["prompt"])
        try:
            result = _run_agent(command, scenario.get("timeout_seconds", 120))
        except subprocess.TimeoutExpired as exc:
            failed = True
            stderr = _stderr_summary(exc.stderr)
            summary = f"agent timed out after {scenario.get('timeout_seconds', 120)} seconds"
            if stderr:
                summary += f"; stderr: {stderr}"
            _diagnostic("FAIL", scenario_id, summary)
            continue
        except OSError as exc:
            _diagnostic("ERROR", "infrastructure", f"agent command could not start: {_redact(str(exc))}")
            return 2

        stderr = _stderr_summary(result.stderr)
        if result.returncode != 0:
            failed = True
            summary = f"agent exited with status {result.returncode}"
            if stderr:
                summary += f"; stderr: {stderr}"
            _diagnostic("FAIL", scenario_id, summary)
            continue
        response = result.stdout.strip()
        if not response:
            failed = True
            summary = "agent produced empty stdout"
            if stderr:
                summary += f"; stderr: {stderr}"
            _diagnostic("FAIL", scenario_id, summary)
            continue
        if "�" in response:
            failed = True
            _diagnostic("FAIL", scenario_id, "stdout contained invalid UTF-8 replacement characters")
            continue
        failures = _assertion_failures(response, scenario["assertions"])
        if failures:
            failed = True
            _diagnostic("FAIL", scenario_id, "; ".join(failures))
            continue
        manual = scenario.get("manual_review", [])
        summary = "hard assertions passed"
        if manual:
            summary += "; manual review: " + " | ".join(manual)
        _diagnostic("PASS", scenario_id, summary)
    return 1 if failed else 0


def _self_scenario(scenario_id: str, prompt: str, assertions: dict[str, Any] | None = None, timeout: int = 2) -> dict[str, Any]:
    return {
        "id": scenario_id,
        "description": scenario_id,
        "prompt": prompt,
        "timeout_seconds": timeout,
        "assertions": assertions or {},
    }


def run_self_tests() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        agent = root / "agent.py"
        agent.write_text(
            """import os
import subprocess
import sys
import time

prompt = sys.argv[-1]
if prompt == "success":
    print("expected response")
elif prompt == "fail-assertion":
    print("wrong response")
elif prompt == "nonzero":
    print("ignored stdout")
    print("agent failed", file=sys.stderr)
    raise SystemExit(7)
elif prompt == "timeout":
    time.sleep(1.0)
    print("too late")
elif prompt == "empty":
    pass
elif prompt == "invalid-utf8":
    sys.stdout.buffer.write(b"bad\\xffoutput")
elif prompt == "secret":
    print(os.environ["BEHAVIOR_TEST_SECRET"], file=sys.stderr)
    raise SystemExit(3)
elif prompt == "counts":
    print('''# 速查表
引言
## 核心
内容
  - [ ] 任务一
- [ ] 任务二
## 第 1 次学习：开始
## 第 1 次学习：重复不重复计数
## 自测问题
> 引用中的问题？
```python
print("代码里的问题?")
```
## 参考答案
''' + "不计入预算" * 1000 + '''
## 复习时间表
不计入预算''')
elif prompt == "count-failures":
    print('''# 速查表
## 核心
短内容？
## 第 1 次学习
- [ ] 唯一任务
## 自测问题
问题？''')
elif prompt == "budget-prefix":
    print('''# 速查表
## 核心
短内容
## 参考答案补充
''' + "必须计入预算" * 100 + '''
## 自测问题
问题''')
elif prompt == "quick-self-test-prefix":
    print('''# 速查表
## 核心
短内容
## 快速自测说明
这不是正式自测标题
## 不得隐藏的正文
''' + "必须计入预算" * 100 + '''
## 自测问题
问题''')
elif prompt == "reversed-order":
    print('''# 速查表
## 参考答案
答案
## 自测问题
问题''')
elif prompt == "dash-arg":
    if "--leading-option" not in sys.argv:
        raise SystemExit(9)
    print("expected response")
elif prompt == "fenced-counts":
    print('''```markdown
- [ ] 代码示例中的任务
## 第 1 次学习
```''')
elif prompt.startswith("tree-timeout:"):
    marker = prompt.split(":", 1)[1]
    subprocess.Popen([
        sys.executable,
        "-c",
        "import pathlib,sys,time; time.sleep(1.5); pathlib.Path(sys.argv[1]).write_text('leaked', encoding='utf-8')",
        marker,
    ])
    time.sleep(10)
else:
    print(prompt)
""",
            encoding="utf-8",
        )
        agent_args = [sys.executable, str(agent), "{prompt}"]
        scenarios_path = root / "scenarios.json"

        def execute(scenarios: list[dict[str, Any]], args: list[str] | None = None) -> tuple[int, str]:
            scenarios_path.write_text(json.dumps({"version": 1, "scenarios": scenarios}), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = run_scenarios(scenarios_path, agent_args if args is None else args)
            return code, output.getvalue()

        cases: list[tuple[str, Callable[[], tuple[int, str]], Callable[[int, str], bool]]] = [
            ("success", lambda: execute([_self_scenario("ok", "success", {"contains": ["expected"], "not_contains": ["wrong"], "regex": ["response$"]})]), lambda c, o: c == 0 and "[PASS] ok:" in o),
            ("assertion failure", lambda: execute([_self_scenario("assert", "fail-assertion", {"contains": ["expected"]})]), lambda c, o: c == 1 and "[FAIL] assert:" in o),
            ("unconfigured command", lambda: execute([_self_scenario("never", "success")], []), lambda c, o: c == 2 and "[ERROR] config:" in o),
            ("command not found", lambda: execute([_self_scenario("never", "success")], [str(root / "missing-command")]), lambda c, o: c == 2 and "[ERROR] infrastructure:" in o),
            ("nonzero exit", lambda: execute([_self_scenario("nonzero", "nonzero")]), lambda c, o: c == 1 and "status 7" in o),
            ("timeout continues", lambda: execute([_self_scenario("slow", "timeout", timeout=0), _self_scenario("after", "success", {"contains": ["expected"]})]), lambda c, o: c == 2 and "positive integer" in o),
            ("empty stdout", lambda: execute([_self_scenario("empty", "empty")]), lambda c, o: c == 1 and "empty stdout" in o),
            ("invalid UTF-8", lambda: execute([_self_scenario("encoding", "invalid-utf8")]), lambda c, o: c == 1 and "replacement" in o),
            ("all assertion counts", lambda: execute([_self_scenario("counts", "counts", {"max_questions": 0, "min_checkboxes": 2, "min_sessions": 1, "max_sessions": 1, "max_sections": 4, "max_content_chars": 200})]), lambda c, o: c == 0 and "[PASS] counts:" in o),
        ]

        # Use a fractional subprocess delay while keeping scenario timeouts valid integers.
        agent.write_text(agent.read_text(encoding="utf-8").replace("time.sleep(1.0)", "time.sleep(2.0)"), encoding="utf-8")
        cases[5] = (
            "timeout continues",
            lambda: execute([_self_scenario("slow", "timeout", timeout=1), _self_scenario("after", "success", {"contains": ["expected"]})]),
            lambda c, o: c == 1 and "[FAIL] slow:" in o and "[PASS] after:" in o,
        )

        cases.extend([
            (
                "prompt appended without placeholder",
                lambda: execute([_self_scenario("append", "success", {"contains": ["expected"]})], [sys.executable, str(agent)]),
                lambda c, o: c == 0 and "[PASS] append:" in o,
            ),
            (
                "nonzero exit continues",
                lambda: execute([_self_scenario("bad-exit", "nonzero"), _self_scenario("after-exit", "success", {"contains": ["expected"]})]),
                lambda c, o: c == 1 and "[FAIL] bad-exit:" in o and "[PASS] after-exit:" in o,
            ),
            (
                "every count boundary can fail",
                lambda: execute([
                    _self_scenario("max-questions", "count-failures", {"max_questions": 1}),
                    _self_scenario("min-checkboxes", "count-failures", {"min_checkboxes": 2}),
                    _self_scenario("min-sessions", "count-failures", {"min_sessions": 2}),
                    _self_scenario("max-sessions", "count-failures", {"max_sessions": 0}),
                    _self_scenario("max-sections", "count-failures", {"max_sections": 2}),
                    _self_scenario("max-content-chars", "count-failures", {"max_content_chars": 10}),
                ]),
                lambda c, o: c == 1 and all(f"[FAIL] {name}:" in o for name in ("max-questions", "min-checkboxes", "min-sessions", "max-sessions", "max-sections", "max-content-chars")),
            ),
            (
                "answer-prefix cannot bypass content budget",
                lambda: execute([_self_scenario("budget-prefix", "budget-prefix", {"max_content_chars": 100})]),
                lambda c, o: c == 1 and "[FAIL] budget-prefix:" in o,
            ),
            (
                "quick-self-test prefix cannot bypass content budget",
                lambda: execute([_self_scenario("quick-prefix", "quick-self-test-prefix", {"max_content_chars": 100})]),
                lambda c, o: c == 1 and "[FAIL] quick-prefix:" in o,
            ),
            (
                "question-answer order regex",
                lambda: execute([_self_scenario("order", "reversed-order", {"regex": [r"(?s)## 自测问题.*## 参考答案"]})]),
                lambda c, o: c == 1 and "[FAIL] order:" in o,
            ),
            (
                "fenced code does not satisfy count minimums",
                lambda: execute([
                    _self_scenario("fenced-checkbox", "fenced-counts", {"min_checkboxes": 1}),
                    _self_scenario("fenced-session", "fenced-counts", {"min_sessions": 1}),
                ]),
                lambda c, o: c == 1 and "[FAIL] fenced-checkbox:" in o and "[FAIL] fenced-session:" in o,
            ),
        ])

        def timeout_kills_process_tree() -> tuple[int, str]:
            marker = root / "grandchild-leak.txt"
            code, output = execute([_self_scenario("tree", f"tree-timeout:{marker}", timeout=1)])
            time.sleep(1.7)
            return code, output + f"\nmarker_exists={marker.exists()}"

        cases.append((
            "timeout kills grandchild process",
            timeout_kills_process_tree,
            lambda c, o: c == 1 and "[FAIL] tree:" in o and "marker_exists=False" in o,
        ))

        url_pattern = r"(?is)^(?!.*(?:\b[a-zA-Z][a-zA-Z0-9+.-]*:[^\s]|\bwww\.|\[[^\]\r\n]*\]\(\s*[^)\s]+|(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])|(?<![A-Fa-f0-9:])(?=[A-Fa-f0-9:]*[A-Fa-f0-9])(?:[A-Fa-f0-9]{0,4}:){2,}[A-Fa-f0-9]{0,4}(?![A-Fa-f0-9:])|(?<![\w.-])(?:[\w-]+\.)+[\w-]+/[^\s]+)).*$"
        cases.append((
            "offline URL forms are rejected",
            lambda: execute([
                _self_scenario("scheme-url", "ftp://example.invalid/resource", {"regex": [url_pattern]}),
                _self_scenario("mailto-uri", "mailto:coach@example.invalid", {"regex": [url_pattern]}),
                _self_scenario("www-url", "www.example.invalid", {"regex": [url_pattern]}),
                _self_scenario("markdown-link", "[资源](example.com/path)", {"regex": [url_pattern]}),
                _self_scenario("ipv4", "192.0.2.10", {"regex": [url_pattern]}),
                _self_scenario("ipv6", "2001:db8::1", {"regex": [url_pattern]}),
                _self_scenario("domain-path", "example.dev/guide", {"regex": [url_pattern]}),
                _self_scenario("unicode-domain-path", "学习.中国/指南", {"regex": [url_pattern]}),
                _self_scenario("dotted-identifier", "MCP.server", {"regex": [url_pattern]}),
            ]),
            lambda c, o: c == 1
            and all(f"[FAIL] {name}:" in o for name in ("scheme-url", "mailto-uri", "www-url", "markdown-link", "ipv4", "ipv6", "domain-path", "unicode-domain-path"))
            and "[PASS] dotted-identifier:" in o,
        ))

        reminder_pattern = r"(?s)^(?=.*未创建系统提醒)(?!.*(?:我(?:已|已经)?(?:为你|帮你)?(?:创建|设置)(?:了|好|好了)?提醒|提醒(?:已|已经)(?:创建|设置)(?=$|[。！？!?，,；;：:\s]|并))).*$"
        reminder_assertions = {"contains": ["未创建系统提醒"], "regex": [reminder_pattern]}
        cases.append((
            "reminder disclaimer is required",
            lambda: execute([
                _self_scenario("honest-reminder", "未创建系统提醒", reminder_assertions),
                _self_scenario("qualified-denial", "未创建系统提醒，不能声称已经创建提醒。", reminder_assertions),
                _self_scenario("missing-disclaimer", "这里只提供复习建议", reminder_assertions),
                _self_scenario("contradict-first-person", "未创建系统提醒，但我已为你创建提醒。", reminder_assertions),
                _self_scenario("contradict-reminder-status", "未创建系统提醒；提醒已经设置。", reminder_assertions),
            ]),
            lambda c, o: c == 1
            and "[PASS] honest-reminder:" in o
            and "[PASS] qualified-denial:" in o
            and "[FAIL] missing-disclaimer:" in o
            and "[FAIL] contradict-first-person:" in o
            and "[FAIL] contradict-reminder-status:" in o,
        ))

        def cli_leading_agent_arg() -> tuple[int, str]:
            scenarios_path.write_text(
                json.dumps({"version": 1, "scenarios": [_self_scenario("dash", "dash-arg", {"contains": ["expected"]})]}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--scenarios",
                    str(scenarios_path),
                    f"--agent-arg={sys.executable}",
                    f"--agent-arg={agent}",
                    "--agent-arg=--leading-option",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            return result.returncode, result.stdout + result.stderr

        cases.append(("leading-dash agent arg via equals", cli_leading_agent_arg, lambda c, o: c == 0 and "[PASS] dash:" in o))

        # Configuration must be rejected before the otherwise-valid first scenario runs.
        def invalid_regex() -> tuple[int, str]:
            return execute([
                _self_scenario("would-run", "success"),
                _self_scenario("bad-regex", "success", {"regex": ["["]}),
            ])

        cases.insert(3, ("invalid regex prevalidation", invalid_regex, lambda c, o: c == 2 and "invalid regex" in o and "[PASS] would-run:" not in o))

        previous_secret = os.environ.get("BEHAVIOR_TEST_SECRET")
        os.environ["BEHAVIOR_TEST_SECRET"] = "sensitive-self-test-value"
        try:
            cases.append(("stderr redaction", lambda: execute([_self_scenario("secret", "secret")]), lambda c, o: c == 1 and "[REDACTED]" in o and "sensitive-self-test-value" not in o))
            failures = 0
            for name, operation, check in cases:
                try:
                    code, output = operation()
                    passed = check(code, output)
                except Exception as exc:  # pragma: no cover - defensive self-test reporting
                    passed = False
                    output = str(exc)
                if passed:
                    print(f"[PASS] self-test: {name}")
                else:
                    failures += 1
                    print(f"[FAIL] self-test: {name}: {_redact(output).strip()[-500:]}")
        finally:
            if previous_secret is None:
                del os.environ["BEHAVIOR_TEST_SECRET"]
            else:
                os.environ["BEHAVIOR_TEST_SECRET"] = previous_secret
        return 1 if failures else 0


def main() -> int:
    default_scenarios = Path(__file__).resolve().parent.parent / "tests" / "scenarios.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run isolated runner regression tests")
    parser.add_argument("--scenarios", type=Path, default=default_scenarios, help="scenario JSON path")
    parser.add_argument("--agent-arg", action="append", default=[], help="one agent argv item; repeat for every item")
    args = parser.parse_args()
    if args.self_test:
        return run_self_tests()
    return run_scenarios(args.scenarios, args.agent_arg)


if __name__ == "__main__":
    raise SystemExit(main())
