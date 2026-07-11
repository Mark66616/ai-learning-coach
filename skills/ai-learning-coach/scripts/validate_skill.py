#!/usr/bin/env python3
"""Static validator for the AI Learning Coach skill (standard library only)."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Callable


REFERENCE_FILES = (
    "learning-ladder.md",
    "focused-learning-plan.md",
    "socratic-assessment.md",
    "one-page-cheat-sheet.md",
    "resource-curation.md",
    "feynman-validation.md",
)
REQUIRED_SECTIONS = ("何时使用", "必要输入", "执行流程", "输出契约", "边界情况", "禁止事项")
FEYNMAN_REQUIRED = ("验证模式必须由用户先讲。", "用户完成第二次讲解后，再提供对照解释。")
FEYNMAN_FORBIDDEN = ("AI 先解释", "先给出标准答案", "建立基线解释")
PLAN_REQUIRED = ("- [ ]", "完成日期", "掌握程度", "学习心得")
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
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _read(path: Path, root: Path, errors: list[str]) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"{_relative(path, root)}: file is missing")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{_relative(path, root)}: cannot read UTF-8 text ({exc})")
    return None


def _frontmatter(text: str, path: Path, root: Path, errors: list[str]) -> dict[str, str] | None:
    if not text.startswith("---\n"):
        errors.append(f"{_relative(path, root)}: missing opening frontmatter delimiter")
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        errors.append(f"{_relative(path, root)}: missing closing frontmatter delimiter")
        return None
    fields: dict[str, str] = {}
    for line_number, line in enumerate(text[4:end].splitlines(), 2):
        if not line.strip() or ":" not in line:
            errors.append(f"{_relative(path, root)}:{line_number}: invalid frontmatter field")
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key or key in fields:
            errors.append(f"{_relative(path, root)}:{line_number}: invalid or duplicate frontmatter key")
            continue
        fields[key] = value.strip()
    actual = set(fields)
    expected = {"name", "description"}
    if actual != expected:
        extra = sorted(actual - expected)
        missing = sorted(expected - actual)
        details = []
        if extra:
            details.append("unexpected " + ", ".join(extra))
        if missing:
            details.append("missing " + ", ".join(missing))
        errors.append(f"{_relative(path, root)}: frontmatter must contain only name and description ({'; '.join(details)})")
    name = fields.get("name", "")
    if not NAME_RE.fullmatch(name):
        errors.append(f"{_relative(path, root)}: name must match {NAME_RE.pattern}")
    description = fields.get("description", "")
    if not description.startswith("Use when"):
        errors.append(f"{_relative(path, root)}: description must start with 'Use when'")
    if len(description) > 500:
        errors.append(f"{_relative(path, root)}: description exceeds 500 Unicode code points")
    return fields


def _check_links(path: Path, text: str, root: Path, errors: list[str]) -> None:
    for raw_target in LINK_RE.findall(text):
        target = raw_target.strip().split()[0].strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:", "tel:")):
            continue
        target = target.split("#", 1)[0].split("?", 1)[0]
        candidate = (path.parent / target).resolve()
        if target and not candidate.is_relative_to(root):
            errors.append(f"{_relative(path, root)}: local Markdown link target escapes skill root: {target}")
        elif target and not candidate.exists():
            errors.append(f"{_relative(path, root)}: local Markdown link target does not exist: {target}")


def _validate_scenarios(path: Path, root: Path, errors: list[str]) -> None:
    text = _read(path, root, errors)
    if text is None:
        return
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"{_relative(path, root)}:{exc.lineno}: invalid JSON ({exc.msg})")
        return
    if not isinstance(data, dict):
        errors.append(f"{_relative(path, root)}: top level must be an object")
        return
    for field in sorted(set(data) - TOP_LEVEL_FIELDS):
        errors.append(f"{_relative(path, root)}: unknown top-level field: {field}")
    if type(data.get("version")) is not int or data.get("version") != 1:
        errors.append(f"{_relative(path, root)}: version must be integer 1")
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list):
        errors.append(f"{_relative(path, root)}: scenarios must be an array")
        return
    if not scenarios:
        errors.append(f"{_relative(path, root)}: scenarios must not be empty")
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        label = f"{_relative(path, root)}: scenarios[{index}]"
        if not isinstance(scenario, dict):
            errors.append(f"{label} must be an object")
            continue
        for field in sorted(set(scenario) - SCENARIO_FIELDS):
            errors.append(f"{label}: unknown scenario field: {field}")
        for field in ("id", "description", "prompt"):
            if not isinstance(scenario.get(field), str) or not scenario[field]:
                errors.append(f"{label}.{field} must be a non-empty string")
        scenario_id = scenario.get("id")
        if isinstance(scenario_id, str):
            if scenario_id in seen:
                errors.append(f"{label}.id is duplicate: {scenario_id}")
            seen.add(scenario_id)
        assertions = scenario.get("assertions")
        if not isinstance(assertions, dict):
            errors.append(f"{label}.assertions must be an object")
            assertions = {}
        timeout = scenario.get("timeout_seconds", 120)
        if type(timeout) is not int or timeout <= 0:
            errors.append(f"{label}.timeout_seconds must be a positive integer")
        manual = scenario.get("manual_review", [])
        if not isinstance(manual, list) or any(not isinstance(item, str) for item in manual):
            errors.append(f"{label}.manual_review must be an array of strings")
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


def validate_skill(skill_root: Path) -> list[str]:
    """Return deterministic diagnostics for all contract violations under skill_root."""
    root = skill_root.resolve()
    errors: list[str] = []
    main_path = root / "SKILL.md"
    main_text = _read(main_path, root, errors)
    if main_text is not None:
        _frontmatter(main_text, main_path, root, errors)
        _check_links(main_path, main_text, root, errors)
        for filename in REFERENCE_FILES:
            ref_path = root / "references" / filename
            if not ref_path.exists():
                errors.append(f"references/{filename}: required reference is missing")
            if f"references/{filename}" not in main_text:
                errors.append(f"SKILL.md: required reference is not linked: references/{filename}")
        for heading in (*[f"方法{i}" for i in range(1, 7)], "执行流程"):
            if re.search(rf"^##\s+{re.escape(heading)}\s*$", main_text, re.MULTILINE):
                errors.append(f"SKILL.md: forbidden heading: ## {heading}")
    for filename in REFERENCE_FILES:
        path = root / "references" / filename
        text = _read(path, root, errors) if path.exists() else None
        if text is None:
            continue
        _check_links(path, text, root, errors)
        headings = set(re.findall(r"^##\s+(.+?)\s*$", text, re.MULTILINE))
        for required in REQUIRED_SECTIONS:
            if required not in headings:
                errors.append(f"references/{filename}: missing required section: ## {required}")
    feynman_path = root / "references" / "feynman-validation.md"
    feynman = _read(feynman_path, root, errors) if feynman_path.exists() else None
    if feynman is not None:
        for sentence in FEYNMAN_REQUIRED:
            if sentence not in feynman:
                errors.append(f"references/feynman-validation.md: missing required contract sentence: {sentence}")
        for phrase in FEYNMAN_FORBIDDEN:
            if phrase in feynman:
                errors.append(f"references/feynman-validation.md: forbidden phrase: {phrase}")
    plan_path = root / "references" / "focused-learning-plan.md"
    plan = _read(plan_path, root, errors) if plan_path.exists() else None
    if plan is not None:
        for phrase in PLAN_REQUIRED:
            if phrase not in plan:
                errors.append(f"references/focused-learning-plan.md: missing plan contract: {phrase}")
    _validate_scenarios(root / "tests" / "scenarios.json", root, errors)
    return list(dict.fromkeys(errors))


def _write_valid_fixture(root: Path) -> None:
    (root / "references").mkdir(parents=True)
    (root / "tests").mkdir()
    links = "\n".join(f"[{name}](references/{name})" for name in REFERENCE_FILES)
    (root / "SKILL.md").write_text(
        "---\nname: valid-skill\ndescription: Use when testing the validator.\n---\n\n# Valid\n\n" + links + "\n",
        encoding="utf-8",
    )
    sections = "\n\n".join(f"## {heading}\n\nContent." for heading in REQUIRED_SECTIONS)
    for filename in REFERENCE_FILES:
        extra = ""
        if filename == "feynman-validation.md":
            extra = "\n\n" + "\n".join(FEYNMAN_REQUIRED)
        if filename == "focused-learning-plan.md":
            extra = "\n\n- [ ] Task\n完成日期：____\n掌握程度：____\n学习心得：____"
        (root / "references" / filename).write_text(f"# Reference\n\n{sections}{extra}\n", encoding="utf-8")
    scenario = {
        "version": 1,
        "scenarios": [{
            "id": "valid",
            "description": "Valid scenario",
            "prompt": "Teach me",
            "timeout_seconds": 120,
            "assertions": {"contains": ["x"], "regex": ["x+"], "max_questions": 0},
            "manual_review": ["Check quality"],
        }],
    }
    (root / "tests" / "scenarios.json").write_text(json.dumps(scenario), encoding="utf-8")


def _replace(path: Path, old: str, new: str) -> None:
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def run_self_tests() -> int:
    cases: list[tuple[str, Callable[[Path], None], str]] = []
    main = lambda root: root / "SKILL.md"
    ref = lambda root, name: root / "references" / name
    scenarios = lambda root: root / "tests" / "scenarios.json"
    cases.extend([
        ("missing frontmatter delimiter", lambda r: main(r).write_text(main(r).read_text(encoding="utf-8").removeprefix("---\n"), encoding="utf-8"), "missing opening frontmatter delimiter"),
        ("missing closing frontmatter delimiter", lambda r: _replace(main(r), "\n---\n\n# Valid", "\n\n# Valid"), "missing closing frontmatter delimiter"),
        ("invalid frontmatter line", lambda r: _replace(main(r), "name: valid-skill", "invalid-line"), "invalid frontmatter field"),
        ("duplicate frontmatter key", lambda r: _replace(main(r), "name: valid-skill", "name: valid-skill\nname: duplicate"), "duplicate frontmatter key"),
        ("missing frontmatter name", lambda r: _replace(main(r), "name: valid-skill\n", ""), "missing name"),
        ("missing frontmatter description", lambda r: _replace(main(r), "description: Use when testing the validator.\n", ""), "missing description"),
        ("extra frontmatter", lambda r: _replace(main(r), "description:", "extra: value\ndescription:"), "frontmatter must contain only"),
        ("invalid name", lambda r: _replace(main(r), "name: valid-skill", "name: Invalid_Name"), "name must match"),
        ("description trigger", lambda r: _replace(main(r), "Use when", "Helpful when"), "description must start"),
        ("description length", lambda r: _replace(main(r), "Use when testing the validator.", "Use when " + "界" * 493), "exceeds 500"),
        ("missing reference", lambda r: ref(r, REFERENCE_FILES[0]).unlink(), "required reference is missing"),
        ("unlinked reference", lambda r: _replace(main(r), "references/learning-ladder.md", "references/other.md"), "required reference is not linked"),
        ("missing section", lambda r: _replace(ref(r, REFERENCE_FILES[0]), "## 禁止事项", "## Other"), "missing required section"),
        ("broken local link", lambda r: main(r).write_text(main(r).read_text(encoding="utf-8") + "\n[broken](missing.md)\n", encoding="utf-8"), "link target does not exist"),
        ("absolute local link", lambda r: main(r).write_text(main(r).read_text(encoding="utf-8") + "\n[outside](/etc/hosts)\n", encoding="utf-8"), "link target escapes skill root"),
        ("parent traversal link", lambda r: ((r.parent / "outside.md").write_text("outside", encoding="utf-8"), main(r).write_text(main(r).read_text(encoding="utf-8") + "\n[outside](../outside.md)\n", encoding="utf-8")), "link target escapes skill root"),
        ("symlink escape link", lambda r: ((r.parent / "outside-target.md").write_text("outside", encoding="utf-8"), (r / "escape.md").symlink_to(r.parent / "outside-target.md"), main(r).write_text(main(r).read_text(encoding="utf-8") + "\n[outside](escape.md)\n", encoding="utf-8")), "link target escapes skill root"),
        ("forbidden method heading", lambda r: main(r).write_text(main(r).read_text(encoding="utf-8") + "\n## 方法1\n", encoding="utf-8"), "forbidden heading"),
        ("forbidden flow heading", lambda r: main(r).write_text(main(r).read_text(encoding="utf-8") + "\n## 执行流程\n", encoding="utf-8"), "forbidden heading"),
    ])
    for sentence in FEYNMAN_REQUIRED:
        cases.append((f"missing Feynman sentence {sentence}", lambda r, s=sentence: _replace(ref(r, "feynman-validation.md"), s, ""), "missing required contract sentence"))
    for phrase in FEYNMAN_FORBIDDEN:
        cases.append((f"forbidden Feynman phrase {phrase}", lambda r, p=phrase: ref(r, "feynman-validation.md").write_text(ref(r, "feynman-validation.md").read_text(encoding="utf-8") + p, encoding="utf-8"), "forbidden phrase"))
    for phrase in PLAN_REQUIRED:
        cases.append((f"missing plan contract {phrase}", lambda r, p=phrase: _replace(ref(r, "focused-learning-plan.md"), p, "REMOVED"), "missing plan contract"))
    cases.extend([
        ("missing scenarios file", lambda r: scenarios(r).unlink(), "file is missing"),
        ("invalid JSON", lambda r: scenarios(r).write_text("{", encoding="utf-8"), "invalid JSON"),
        ("scenario top-level array", lambda r: scenarios(r).write_text("[]", encoding="utf-8"), "top level must be an object"),
        ("unknown top-level field", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [], "extra": 1}), encoding="utf-8"), "unknown top-level field"),
        ("scenarios wrong type", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": {}}), encoding="utf-8"), "scenarios must be an array"),
        ("scenarios empty", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": []}), encoding="utf-8"), "scenarios must not be empty"),
        ("scenario element wrong type", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [1]}), encoding="utf-8"), "must be an object"),
        ("float scenario version", lambda r: scenarios(r).write_text(json.dumps({"version": 1.0, "scenarios": []}), encoding="utf-8"), "version must be integer 1"),
        ("boolean scenario version", lambda r: scenarios(r).write_text(json.dumps({"version": True, "scenarios": []}), encoding="utf-8"), "version must be integer 1"),
        ("missing scenario id", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"description": "d", "prompt": "p", "assertions": {}}]}), encoding="utf-8"), ".id must be a non-empty string"),
        ("missing scenario description", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "prompt": "p", "assertions": {}}]}), encoding="utf-8"), ".description must be a non-empty string"),
        ("missing scenario prompt", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "assertions": {}}]}), encoding="utf-8"), ".prompt must be a non-empty string"),
        ("missing scenario assertions", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p"}]}), encoding="utf-8"), ".assertions must be an object"),
        ("wrong scenario description type", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": 1, "prompt": "p", "assertions": {}}]}), encoding="utf-8"), ".description must be a non-empty string"),
        ("wrong scenario prompt type", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": [], "assertions": {}}]}), encoding="utf-8"), ".prompt must be a non-empty string"),
        ("assertions wrong type", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": []}]}), encoding="utf-8"), ".assertions must be an object"),
        ("zero timeout", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": {}, "timeout_seconds": 0}]}), encoding="utf-8"), "timeout_seconds must be a positive integer"),
        ("boolean timeout", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": {}, "timeout_seconds": True}]}), encoding="utf-8"), "timeout_seconds must be a positive integer"),
        ("float timeout", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": {}, "timeout_seconds": 1.5}]}), encoding="utf-8"), "timeout_seconds must be a positive integer"),
        ("invalid manual review", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": {}, "manual_review": [1]}]}), encoding="utf-8"), "manual_review must be an array of strings"),
        ("unknown scenario field", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": {}, "extra": 1}]}), encoding="utf-8"), "unknown scenario field"),
        ("duplicate scenario id", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": {}}, {"id": "x", "description": "d", "prompt": "p", "assertions": {}}]}), encoding="utf-8"), "duplicate"),
        ("scenario field type", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": 3, "description": "d", "prompt": "p", "assertions": {}, "timeout_seconds": 0, "manual_review": "x"}]}), encoding="utf-8"), "must be a non-empty string"),
        ("assertion text type", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": {"contains": "x"}}]}), encoding="utf-8"), "array of strings"),
        ("assertion text item type", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": {"not_contains": [1]}}]}), encoding="utf-8"), "array of strings"),
        ("assertion count type", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": {"max_questions": -1}}]}), encoding="utf-8"), "non-negative integer"),
        ("assertion count boolean", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": {"min_checkboxes": True}}]}), encoding="utf-8"), "non-negative integer"),
        ("assertion count float", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": {"max_sections": 1.0}}]}), encoding="utf-8"), "non-negative integer"),
        ("unknown assertion", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": {"unknown": 1}}]}), encoding="utf-8"), "is unknown"),
        ("invalid regex", lambda r: scenarios(r).write_text(json.dumps({"version": 1, "scenarios": [{"id": "x", "description": "d", "prompt": "p", "assertions": {"regex": ["["]}}]}), encoding="utf-8"), "invalid regex"),
    ])
    failures = 0
    with tempfile.TemporaryDirectory(prefix="validate-skill-") as tmp:
        base = Path(tmp)
        valid = base / "valid"
        _write_valid_fixture(valid)
        valid_errors = validate_skill(valid)
        if valid_errors:
            print("[FAIL] valid fixture: " + " | ".join(valid_errors))
            failures += 1
        else:
            print("[PASS] valid fixture")
        for index, (name, mutate, expected) in enumerate(cases):
            root = base / f"case-{index}"
            _write_valid_fixture(root)
            mutate(root)
            diagnostics = validate_skill(root)
            if any(expected in diagnostic for diagnostic in diagnostics):
                print(f"[PASS] {name}")
            else:
                print(f"[FAIL] {name}: expected {expected!r}; got {diagnostics!r}")
                failures += 1
    if failures:
        print(f"[FAIL] {failures} self-test(s) failed")
        return 1
    print(f"[PASS] all {len(cases) + 1} self-tests passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run isolated validator self-tests")
    parser.add_argument("--skill-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.self_test:
        return run_self_tests()
    root = args.skill_root or Path(__file__).resolve().parent.parent
    errors = validate_skill(root)
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        print(f"[FAIL] validation failed with {len(errors)} error(s)")
        return 1
    print("[PASS] skill validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
