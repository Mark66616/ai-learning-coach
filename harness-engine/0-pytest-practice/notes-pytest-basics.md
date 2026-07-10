# pytest 实用笔记

## 一、为什么直接敲 `pytest` 报错？

### 问题现象

在 PowerShell 中执行 `pytest test_basics.py -v`，报错：

```
无法将"pytest"项识别为 cmdlet、函数、脚本文件或可运行程序的名称
```

### 原因

用 uv 管理的项目，虚拟环境（`.venv`）是**隔离**的：

- `pytest.exe` 装在 `.venv\Scripts\` 目录下
- 该目录**不在系统 PATH** 中
- PowerShell 只在 PATH 里找可执行文件，找不到就报 CommandNotFoundException

`uv pip list` 能看到 pytest，是因为 uv 自动读取项目 `.venv`；但直接在终端敲 `pytest` 走的是系统 PATH，两套机制不同。

### 解决方案

| 方法 | 命令 | 适用场景 |
|------|------|----------|
| **uv run（推荐）** | `uv run pytest test_basics.py -v` | 日常使用，无需激活 |
| **激活虚拟环境** | `.\.venv\Scripts\Activate.ps1` | 需要连续执行多条命令 |
| **完整路径** | `.\.venv\Scripts\pytest.exe test_basics.py -v` | 临时跑一次 |

> 激活报「禁止运行脚本」时，先执行一次（管理员 PowerShell）：
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

---

## 二、pytest 测试方法的命名规则

### 默认规则

pytest **默认**按以下规则发现测试：

| 类型 | 默认规则 | 示例 |
|------|----------|------|
| 测试文件 | 文件名以 `test_` 开头或以 `_test` 结尾 | `test_basics.py` |
| 测试函数 | 函数名以 `test_` 开头 | `def test_add_positive():` |
| 测试类 | 类名以 `Test` 开头（且无 `__init__`） | `class TestCalculator:` |

### 是固定的吗？

**不是强制的**，可以在 `pyproject.toml` 中自定义：

```toml
[tool.pytest.ini_options]
python_files = ["test_*.py", "*_test.py", "check_*.py"]
python_functions = ["test_*", "check_*"]
python_classes = ["Test*", "Check*"]
```

但一般情况下**保持默认**即可，社区约定俗成就是 `test_` 前缀。

---

## 三、`-k` 参数：按关键字筛选测试

### 基本用法

`-k` 后跟一个表达式，pytest 会用**子串匹配**完整的测试 ID（`文件名::函数名`）来筛选。

```bash
# 只跑名字里含 "positive" 的
uv run pytest test_basics.py -v -k "positive"
# → 只执行 test_add_positive
```

### 支持多个关键字（表达式语法）

`-k` 支持 `or`、`and`、`not` 三个逻辑运算符：

| 运算符 | 含义 | 示例 | 效果 |
|--------|------|------|------|
| `or` | 任一匹配即选中 | `-k "positive or negative"` | 跑 positive + negative |
| `and` | 同时包含两个词 | `-k "add and positive"` | 名字里同时有 add 和 positive |
| `not` | 排除匹配项 | `-k "not zero"` | 跑除 zero 外的所有 |

### 实际验证

```bash
uv run pytest test_basics.py -v -k "positive or negative"
```

输出：

```
collected 4 items / 2 deselected / 2 selected

test_basics.py::test_add_positive PASSED          [ 50%]
test_basics.py::test_add_negative PASSED          [100%]

2 passed, 2 deselected in 0.01s
```

完美选中了两个测试，另外两个被 deselected。

### 注意事项

- `-k` 匹配的是**完整测试 ID 的子串**，不是只匹配函数名后半段
- 匹配范围包括：文件名、类名、函数名（甚至参数化测试的参数 ID）
- 表达式需要用引号包裹（PowerShell 用双引号 `"..."`）

---

## 四、常用命令速查

```bash
# 跑全部测试
uv run pytest -v

# 跑指定文件
uv run pytest test_basics.py -v

# 按关键字筛选
uv run pytest -k "positive"
uv run pytest -k "positive or negative"
uv run pytest -k "not zero"

# 只看失败的（失败即停）
uv run pytest -x

# 显示打印输出（配合 print）
uv run pytest -s

# 生成详细报告
uv run pytest --tb=short
```

---

## 五、fixture —— 依赖注入式测试数据准备

### 核心概念

fixture = 用 `@pytest.fixture` 装饰的函数，为测试提供**预备数据/资源**。测试函数把 fixture 名当参数，pytest 自动调用 fixture 并把返回值"注射"进来（依赖注入）。

### 基本用法

```python
@pytest.fixture
def numbers():
    return [1, 2, 3, 4, 5]

def test_sum(numbers):       # 参数名 "numbers" 匹配 fixture 名 → 自动注入
    assert sum(numbers) == 15
```

### yield：setup 与 teardown 的分界线

```python
@pytest.fixture
def temp_file(tmp_path):
    # ---- setup（yield 之前）----
    file_path = tmp_path / "test_data.json"
    file_path.write_text('{"status": "ok"}')

    yield file_path    # ← 把值交给测试，函数在此"暂停"

    # ---- teardown（yield 之后，测试跑完后执行）----
    if file_path.exists():
        file_path.unlink()
```

### scope：控制 fixture 创建几次

| scope | 创建频率 | 典型场景 |
|-------|----------|----------|
| `"function"`（默认） | 每个测试函数各创建一次 | 每个测试需要独立数据 |
| `"module"` | 整个 .py 文件只创建一次 | 共享的模型连接 |
| `"session"` | 整个 pytest 运行只创建一次 | 数据库连接池 |

### fixture 链式依赖

fixture 可以依赖其他 fixture，pytest 自动按依赖顺序执行：

```python
@pytest.fixture
def database():
    return {"connected": True}

@pytest.fixture
def user_repo(database):      # ← 参数是另一个 fixture
    return {"db": database}
```

### conftest.py：跨文件共享 fixture

放在项目根目录或子目录，里面的 fixture 自动对同目录及子目录下所有测试可见，**不需要 import**。

**目录结构：**

```
0-pytest-practice/
├── conftest.py          ← 共享 fixture 定义在这里
├── test_shared_a.py     ← 直接用 conftest 的 fixture，无需 import
└── test_shared_b.py     ← 同样直接用，两个文件共享同一份定义
```

**conftest.py 示例：**

```python
import pytest

# fixture 1：测试数据（function scope，每个测试都创建新的）
@pytest.fixture
def sample_emails():
    return [
        {"id": "e1", "text": "项目周会改到周五", "label": "work"},
        {"id": "e2", "text": "您的快递已签收", "label": "personal"},
        {"id": "e3", "text": "限时优惠点击领取", "label": "spam"},
    ]

# fixture 2：带 setup/teardown 的资源（module scope，每个文件只创建一次）
@pytest.fixture(scope="module")
def mock_llm_client():
    print("\n  [conftest] 创建模拟 LLM 连接")
    client = {"model": "gpt-4", "connected": True, "call_count": 0}
    yield client
    print("\n  [conftest] 关闭模拟 LLM 连接")

# fixture 3：fixture 依赖 fixture（链式注入也能跨文件工作）
@pytest.fixture
def classifier(mock_llm_client):
    def classify(text: str) -> str:
        mock_llm_client["call_count"] += 1
        if not text:
            return "unknown"
        if "优惠" in text or "领取" in text:
            return "spam"
        if "快递" in text:
            return "personal"
        if "会议" in text or "项目" in text:
            return "work"
        return "unknown"
    return classify
```

**test_shared_a.py（文件 A）：**

```python
# 注意：没有 from conftest import ... 这一行！

def test_emails_count(sample_emails):          # ← conftest 的 fixture
    assert len(sample_emails) == 3

def test_classify_spam(classifier):             # ← 链式依赖也自动解析
    assert classifier("限时优惠点击领取") == "spam"
```

**test_shared_b.py（文件 B）：**

```python
# 同样不需要 import，两个文件共享同一份 fixture 定义

def test_emails_first_is_work(sample_emails):
    assert sample_emails[0]["label"] == "work"

def test_llm_client_call_count(classifier, mock_llm_client):
    """同一个测试可以同时用多个 fixture"""
    before = mock_llm_client["call_count"]
    classifier("测试1")
    classifier("测试2")
    assert mock_llm_client["call_count"] == before + 2
```

**运行验证：**

```bash
uv run pytest test_shared_a.py test_shared_b.py -v -s
```

```
test_shared_a.py::test_emails_count            PASSED
test_shared_a.py::test_classify_spam           PASSED  [conftest] 创建 LLM 连接
test_shared_b.py::test_emails_first_is_work    PASSED
test_shared_b.py::test_llm_client_call_count   PASSED  [conftest] 关闭 LLM 连接
9 passed
```

**关键观察：**

1. 两个测试文件都没有 `import conftest`，fixture 自动可用
2. `mock_llm_client` 是 module scope → 每个文件创建一次（共 2 次 setup + 2 次 teardown）
3. `classifier` 依赖 `mock_llm_client`，跨文件的依赖链也能自动解析
4. 一个测试函数可以同时注入多个 fixture（如 `test_llm_client_call_count`）

> **注意**：module scope 的 fixture 在同一文件内是共享的，前面测试对状态的修改会影响后面的测试。所以 `test_llm_client_call_count` 里用 `before` 记录初始值，验证**增量**而不是绝对值。

### 与 harness 的对应关系

| pytest fixture 概念 | harness 中的对应 |
|---------------------|------------------|
| fixture 提供测试数据 | 加载测试数据集 |
| yield 的 setup/teardown | 模型连接 / 资源清理 |
| scope | 控制资源复用粒度 |
| fixture + parametrize | 批量加载测试集 → 逐条评估 |

---

## 六、`@pytest.mark.parametrize` —— 数据驱动测试

### 结构解剖

```python
@pytest.mark.parametrize(
    "text,expected",                    # ① 参数名字符串（逗号分隔）
    [                                   # ② 数据列表
        ("会议改到下午3点", "work"),       #    每个元组 = 一组测试数据
        ("您的快递已签收", "personal"),
        ("限时优惠点击领取", "spam"),
        ("", "unknown"),
    ],
    ids=["work_email", "personal_email", "spam_email", "empty_input"]  # ③ 可选：用例名
)
def test_classify(classifier, text, expected):
    result = classifier(text)
    assert result == expected
```

### 三个参数详解

**① 参数名字符串**

一个普通字符串，逗号分隔参数名，对应测试函数的参数列表：

| 写法 | 含义 |
|------|------|
| `"x"` | 一个参数 |
| `"text,expected"` | 两个参数 |
| `"a,b,c"` | 三个参数 |
| `["text", "expected"]` | 列表写法（等价于逗号字符串，更清晰） |

**② 数据列表**

一个 list，每个元素是一组测试数据。格式与参数名一一对应：

```python
("会议改到下午3点", "work")
#  ↑               ↑
#  text            expected
```

- 4 个元素 = 4 个测试用例
- 元素可以是元组 `(tuple)` 或列表 `[list]`
- 单参数时，每个元素直接是一个值，不用包元组：`[1, 2, 3, 4, 5]`

**③ ids（可选）**

给每组数据起人类可读的名字，显示在 `-v` 输出中：

```
test_classify[work_email]     PASSED
test_classify[personal_email] PASSED
```

不写 ids 时 pytest 自动用数据值当名字，但中文数据会变成转义码，可读性差。**建议写 ids**。

### 不同写法示例

```python
# 单参数：直接给值列表
@pytest.mark.parametrize("number", [1, 2, 3, 4, 5])
def test_positive(number):
    assert number > 0

# 双参数：元组列表
@pytest.mark.parametrize("input,expected", [
    (1, 1),
    (2, 4),
    (3, 9),
])
def test_square(input, expected):
    assert input ** 2 == expected

# 参数名用列表（更清晰）
@pytest.mark.parametrize(["text", "expected"], [
    ("hello", "work"),
])
def test_classify(text, expected): ...

# 不写 ids（中文数据可读性差）
@pytest.mark.parametrize("text,expected", [
    ("会议改到下午3点", "work"),
])
def test_no_ids(text, expected): ...
# 输出：test_no_ids[\u4f1a\u8bae...]  ← 不可读
```

### 本质理解

parametrize = **1 个测试函数 + N 组数据 = N 个独立测试用例**

pytest 自动展开，每组数据生成一个独立用例，互不影响。这比手写 N 个 `def test_xxx()` 干净得多，也是 harness 批量评估的核心模式：

| pytest 概念 | harness 对应 |
|-------------|-------------|
| parametrize 的数据 | 测试数据集 |
| 测试函数体 | 评估逻辑 |
| assert | 评估指标判定 |
