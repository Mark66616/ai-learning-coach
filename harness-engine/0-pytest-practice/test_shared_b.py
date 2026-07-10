"""
测试文件 B —— 同样使用 conftest.py 中的共享 fixture

和 test_shared_a.py 在不同文件，但共享同一份 fixture 定义。
这体现了 conftest.py 的价值：一次定义，多处复用。
"""


def test_emails_first_is_work(sample_emails):
    """不同的测试文件，同样的 fixture，不需要重复定义"""
    assert sample_emails[0]["label"] == "work"


def test_emails_last_is_spam(sample_emails):
    assert sample_emails[-1]["label"] == "spam"


def test_classify_personal(classifier):
    """classifier fixture 在这里也能用，依赖链自动解析"""
    result = classifier("您的快递已签收")
    assert result == "personal"


def test_llm_client_call_count(classifier, mock_llm_client):
    """同一个测试可以同时用多个 fixture"""
    # mock_llm_client 是 module scope，前面的测试可能已经调用过
    # 所以先记录当前值，再验证增量
    before = mock_llm_client["call_count"]
    classifier("测试1")   # +1
    classifier("测试2")   # +1
    assert mock_llm_client["call_count"] == before + 2
    assert mock_llm_client["connected"] is True
