"""
conftest.py — pytest 的"共享配置文件"

这个文件不需要被 import，pytest 会自动发现它。
里面定义的 fixture 对同目录及子目录下所有测试文件自动可见。

验证方式：
    cd harness-engine/0-pytest-practice
    uv run pytest test_shared_a.py test_shared_b.py -v -s

你会看到两个不同文件里的测试都能拿到 conftest.py 中定义的 fixture，
但代码里没有任何 import 语句。
"""

import pytest


# ============================================================
# 共享 fixture 1：测试数据
# ============================================================

@pytest.fixture
def sample_emails():
    """提供一批邮件测试数据。

    放在 conftest.py 里，test_shared_a.py 和 test_shared_b.py 都能直接用，
    不需要 import。
    """
    return [
        {"id": "e1", "text": "项目周会改到周五", "label": "work"},
        {"id": "e2", "text": "您的快递已签收", "label": "personal"},
        {"id": "e3", "text": "限时优惠点击领取", "label": "spam"},
    ]


# ============================================================
# 共享 fixture 2：带 setup/teardown 的资源
# ============================================================

@pytest.fixture(scope="module")
def mock_llm_client():
    """模拟一个 LLM 客户端连接。

    scope="module"：每个测试文件只创建一次。
    两个测试文件 → 这个 fixture 会执行 2 次 setup + 2 次 teardown。
    """
    print("\n  [conftest mock_llm_client] 创建模拟 LLM 连接")

    client = {
        "model": "gpt-4",
        "connected": True,
        "call_count": 0,
    }

    yield client

    print("\n  [conftest mock_llm_client] 关闭模拟 LLM 连接")


# ============================================================
# 共享 fixture 3：fixture 依赖 fixture（链式）
# ============================================================

@pytest.fixture
def classifier(mock_llm_client):
    """依赖 mock_llm_client fixture。

    链式依赖：classifier → mock_llm_client
    pytest 自动解析依赖顺序，先执行 mock_llm_client，再执行 classifier。
    """

    def classify(text: str) -> str:
        mock_llm_client["call_count"] += 1
        if not text:
            return "unknown"
        if "优惠" in text or "领取" in text:
            return "spam"
        if "快递" in text:
            return "personal"
        if "会议" in text or "周会" in text or "项目" in text:
            return "work"
        return "unknown"

    return classify
