"""
测试文件 A —— 使用 conftest.py 中的共享 fixture

注意：这个文件里没有任何 import conftest 的语句！
pytest 会自动发现 conftest.py 中的 fixture 并注入。
"""

# 没有from conftest import ... 这一行！


def test_emails_count(sample_emails):
    """直接使用 conftest.py 里的 sample_emails fixture"""
    assert len(sample_emails) == 3


def test_emails_have_ids(sample_emails):
    ids = [e["id"] for e in sample_emails]
    assert ids == ["e1", "e2", "e3"]


def test_classify_spam(classifier):
    """使用 conftest.py 里的 classifier fixture（它又依赖 mock_llm_client）"""
    result = classifier("限时优惠点击领取")
    assert result == "spam"


def test_classify_work(classifier):
    result = classifier("项目周会改到周五")
    assert result == "work"


def test_classify_empty(classifier):
    result = classifier("")
    assert result == "unknown"
