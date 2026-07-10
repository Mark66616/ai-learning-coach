# 最简单的测试：一个函数 + 一个 assert
def add(a, b):
    return a + b

def test_add_positive():
    assert add(1, 2) == 3

def test_add_negative():
    assert add(-1, -2) == -3

def test_add_zero():
    assert add(0, 0) == 0

def test_add_mixed():
    assert add(-1, 1) == 0

# 当前项目使用uv管理虚拟环境，所以要使用uv run激活虚拟环境
# uv run pytest test_basics.py -v
# 执行结果：
# ========================================================================================= test session starts ==========================================================================================
# platform win32 -- Python 3.13.12, pytest-9.1.1, pluggy-1.6.0 -- E:\dev_space\pycharm\ai-learning-coach\.venv\Scripts\python.exe
# cachedir: .pytest_cache
# rootdir: E:\dev_space\pycharm\ai-learning-coach
# configfile: pyproject.toml
# collected 4 items
#
# test_basics.py::test_add_positive PASSED                                                                                                                                                          [ 25%]
# test_basics.py::test_add_negative PASSED                                                                                                                                                          [ 50%]
# test_basics.py::test_add_zero PASSED                                                                                                                                                              [ 75%]
# test_basics.py::test_add_mixed PASSED                                                                                                                                                             [100%]
# ========================================================================================== 4 passed in 0.01s ===========================================================================================

# # 只运行匹配名称的测试
# uv run pytest test_basics.py -v -k "positive"
#