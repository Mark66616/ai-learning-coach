# pytest 一页速查表

> 基于苏格拉底测试（方法3）作答情况定制，重点标注测试中暴露的薄弱点。

---

## 一句话定义

pytest 是 Python 测试框架，核心机制是**测试发现**（按命名规则自动收集测试）+ **fixture 依赖注入**（按参数名自动调用函数并注入返回值）+ **parametrize 数据驱动**（1 个函数 + N 组数据 = N 个用例）。

---

## 五大核心概念

| # | 概念 | 一句话 | 你的薄弱度 |
|---|------|--------|-----------|
| 1 | uv run | 直接用 `.venv` 的 Python 执行命令，**不改 PATH、不激活环境** | ⚠️ 高 |
| 2 | fixture | `@pytest.fixture` 装饰的函数，pytest 按参数名匹配后**调用它**，把**返回值**注入 | ⚠️ 中 |
| 3 | yield | yield 前 = setup，yield 后 = teardown；yield 让函数**挂起**而非结束 | ✅ 掌握 |
| 4 | scope | 控制 fixture **被调用几次**：function=每测试1次，module=每文件1次，session=全程1次 | ⚠️ 最高 |
| 5 | conftest.py | 跨文件共享 fixture，**只向下传递不向上**，子目录能看见父级的 | ⚠️ 高 |

---

## 常见错误（你在测试中犯过的）

### ❌ 错误 1：把 `uv run` 等同于"激活虚拟环境"

```powershell
# ❌ 错误理解：uv run 会把 .venv\Scripts 加到 PATH
# ✅ 正确理解：uv run 等价于直接用 .venv\Scripts\python.exe -m pytest
uv run pytest test_basics.py -v
```

| 机制 | 是否改 PATH | 是否需要每次带前缀 |
|------|------------|------------------|
| `uv run pytest` | 不改 | 是，每次都要带 |
| `Activate.ps1` | 改当前终端（临时） | 激活后可直接敲 `pytest` |
| 系统环境变量 | 永久改 | 不用带前缀，但污染全局 |

### ❌ 错误 2：把 fixture 类比为"全局变量"

```python
@pytest.fixture
def numbers():
    return [1, 2, 3]

def test_sum(numbers):  # numbers 不是全局变量
    assert sum(numbers) == 6
```

| | 全局变量 | fixture |
|---|---|---|
| 本质 | 静态值 | **函数**，按需调用 |
| 生命周期 | 一直存在 | pytest 按 scope 控制创建/销毁 |
| 谁赋值 | 代码里 `x = ...` | pytest **调用函数**，拿返回值注入 |

### ❌ 错误 3：scope=module 时认为每个测试都调用 fixture

```
scope="function"（默认）：3个测试 → fixture 调用 3 次（每测试1次）
scope="module"：         3个测试 → fixture 调用 1 次（整文件共享）
scope="session"：        3个测试 → fixture 调用 1 次（全程共享）
```

```python
@pytest.fixture(scope="module")   # ← 整个 .py 只调用 1 次
def conn():
    return {"id": 1}

def test_a(conn): assert conn["id"] == 1  # ✅
def test_b(conn): assert conn["id"] == 1  # ✅ 拿到同一个对象
def test_c(conn): assert conn["id"] == 1  # ✅ 不会重新调用
```

### ❌ 错误 4：conftest 可见性规则正确但结论搞反

```
项目根/
├── conftest.py          ← fixture A：对根目录 ✅ + 子目录 ✅
├── test_root.py         ← 能用 A ✅
└── subdir/
    ├── conftest.py      ← fixture B：只对 subdir ✅
    └── test_sub.py      ← 能用 A ✅ + B ✅
```

**口诀**：conftest.py 只向下传递，不向上。子目录能看见父级的，父级看不见子级的。

### ❌ 错误 5：parametrize 不写 ids 时中文数据被转义

```python
# 不写 ids → 中文变成 \u4f1a\u8bae，可读性差
@pytest.mark.parametrize("text,expected", [
    ("会议改到下午3点", "work"),
], ids=["work_email"])  # ← 写 ids，输出 test_parse[work_email]
```

---

## 真实例子

### 例 1：fixture + yield + scope 完整流程

```python
@pytest.fixture(scope="module")
def db():
    conn = {"data": [1, 2, 3], "open": True}
    print("setup")          # 整个文件只执行 1 次
    yield conn
    conn["open"] = False
    print("teardown")       # 所有测试跑完后执行 1 次

def test_a(db):
    assert db["open"] is True

def test_b(db):
    assert db["data"][0] == 1
```

执行顺序：`setup → test_a → test_b → teardown`

### 例 2：parametrize + fixture 组合

```python
@pytest.fixture
def classifier():
    return lambda text: "work" if "会议" in text else "other"

@pytest.mark.parametrize("text,expected", [
    ("会议改到下午3点", "work"),
    ("你好", "other"),
], ids=["work_case", "other_case"])
def test_classify(classifier, text, expected):
    assert classifier(text) == expected
```

- fixture `classifier` → scope 默认 function → 2 个用例各调用 1 次 = 共 2 次
- parametrize → 生成 2 个用例
- 输出：`test_classify[work_case]` / `test_classify[other_case]`

---

## 使用前检查清单

写测试前快速过一遍：

- [ ] 文件名是否以 `test_` 开头或 `_test` 结尾？
- [ ] 测试函数是否以 `test_` 开头？
- [ ] fixture 参数名是否和 `@pytest.fixture` 函数名完全一致？
- [ ] 使用 yield 时，setup 在 yield 前、teardown 在 yield 后？
- [ ] module scope 的 fixture 在同文件多测试间共享，是否会导致状态污染？
- [ ] conftest.py 是否放在正确的目录层级？
- [ ] parametrize 的参数名字符串和函数签名是否一一对应？
- [ ] parametrize 是否写了 ids（尤其是中文数据）？

---

## 5 个快速自测问题（30 秒内回答）

1. **`uv run pytest` 和 `.venv\Scripts\Activate.ps1` 后再敲 `pytest`，哪个会修改系统 PATH？**
   > 都不会修改**系统** PATH。Activate 只改**当前终端**的 PATH（临时的）；uv run 根本不改 PATH，直接用 .venv 的解释器执行。

2. **scope="module"，3 个测试用同一个 fixture，fixture 函数被调用几次？**
   > 1 次。整个 .py 文件共享同一个 fixture 实例。

3. **fixture 是"全局变量"吗？为什么？**
   > 不是。fixture 是函数，pytest 按需调用它拿返回值。全局变量是静态值，没有执行时机概念；fixture 可以 yield 做 setup/teardown。

4. **子目录的 conftest.py 里定义的 fixture，父目录的测试文件能用吗？**
   > 不能。conftest.py 只向下传递，不向上传递。

5. **parametrize 不写 ids，数据是中文时 `-v` 输出会怎样？**
   > 中文会被转义成 `\uXXXX`，可读性很差。建议写 ids。

---

## 间隔复习提醒

| 次数 | 日期 | 做什么 |
|------|------|--------|
| 第 1 次 | 1 天后（07-12） | 重答 5 个自测问题，答错的概念回到速查表重读 |
| 第 2 次 | 3 天后（07-14） | 同上 |
| 第 3 次 | 7 天后（07-18） | 同上 + 重做苏格拉底测试第 4、5 题（scope 和 conftest） |
| 第 4 次 | 21 天后（08-01） | 完整重跑一遍自测问题 |

> 复习时只重测自测问题，答对就跳过，答错回到对应章节重读。不要每次都从头通读。
