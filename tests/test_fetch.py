"""抓取逻辑测试(以 mock 替换网络层)。"""
from unittest import mock

import tokenmon


# ---- custom 用量 ----

def test_fetch_usage_custom_default_fields():
    payload = {
        "promptTokens": 100, "completionTokens": 50, "reasoningTokens": 10,
        "cacheHitTokens": 120, "cacheMissTokens": 30,
        "sessionCacheHitTokens": 120, "sessionCacheMissTokens": 30,
        "totalTokens": 150, "cost": 0.5, "currency": "¥",
    }
    gw = {"type": "custom", "base_url": "http://gw/usage", "api_key": ""}
    with mock.patch("tokenmon._get_json", return_value=payload) as gj:
        u = tokenmon.fetch_usage(gw)
    gj.assert_called_once()
    assert u.total == 150
    assert u.prompt == 100
    assert u.completion == 50
    assert u.reasoning == 10
    assert u.cache_hit == 120
    assert u.cost == 0.5
    assert u.currency == "¥"


def test_fetch_usage_custom_zero_values_not_lost():
    payload = {"totalTokens": 0, "cost": 0, "currency": "$"}
    gw = {"type": "custom", "base_url": "http://gw/usage"}
    with mock.patch("tokenmon._get_json", return_value=payload):
        u = tokenmon.fetch_usage(gw)
    assert u.total == 0
    assert u.total is not None
    assert u.cost == 0


def test_fetch_usage_custom_field_override():
    payload = {"data": {"total_tokens": 55, "total_cost": 0.2}}
    gw = {"type": "custom", "base_url": "http://gw/usage",
          "fields": {"total": "data.total_tokens", "cost": "data.total_cost"}}
    with mock.patch("tokenmon._get_json", return_value=payload):
        u = tokenmon.fetch_usage(gw)
    assert u.total == 55
    assert u.cost == 0.2


def test_fetch_usage_custom_legacy_paths():
    payload = {"data": {"total_tokens": 55, "total_cost": 0.2}}
    gw = {"type": "custom", "base_url": "http://gw/usage",
          "tokens_path": "data.total_tokens", "cost_path": "data.total_cost"}
    with mock.patch("tokenmon._get_json", return_value=payload):
        u = tokenmon.fetch_usage(gw)
    assert u.total == 55
    assert u.cost == 0.2


def test_fetch_usage_mock():
    u = tokenmon.fetch_usage({"type": "custom", "base_url": "mock://usage"})
    assert u.total == 2215154
    assert u.cost == 0.3755
    assert u.currency == "¥"


# ---- litellm 用量 ----

def test_fetch_usage_litellm_top_level():
    gw = {"type": "litellm", "base_url": "http://gw"}
    with mock.patch("tokenmon._get_json",
                    return_value={"total_tokens": 100, "total_cost": 1.5}):
        u = tokenmon.fetch_usage(gw)
    assert u.total == 100
    assert u.cost == 1.5


def test_fetch_usage_litellm_api_keys_dict():
    gw = {"type": "litellm", "base_url": "http://gw"}
    with mock.patch("tokenmon._get_json", return_value={"api_keys": {
            "a": {"total_tokens": 10}, "b": {"total_tokens": 20}}}):
        u = tokenmon.fetch_usage(gw)
    assert u.total == 30


def test_fetch_usage_litellm_data_list():
    gw = {"type": "litellm", "base_url": "http://gw"}
    with mock.patch("tokenmon._get_json", return_value={"data": [
            {"total_tokens": 7}, {"total_tokens": 3}]}):
        u = tokenmon.fetch_usage(gw)
    assert u.total == 10


# ---- deepseek 余额 ----

def test_fetch_usage_deepseek_zero_remaining_not_fallback():
    """余额恰为 0 时不能回退到 total_balance(充值总额)。"""
    payload = {
        "is_available": True,
        "balance_infos": [{
            "currency": "CNY",
            "total_remaining": 0,
            "total_balance": 100,
            "granted_balance": 50, "topped_up_balance": 50,
        }],
    }
    gw = {"type": "deepseek", "base_url": "https://api.deepseek.com", "api_key": "sk-x"}
    with mock.patch("tokenmon._get_json", return_value=payload):
        u = tokenmon.fetch_usage(gw)
    assert u.balance == 0
    assert u.balance is not None
    assert u.cost == 100  # 已用 = 赠送 + 充值 - 余额


def test_fetch_usage_deepseek_has_used():
    payload = {
        "is_available": True,
        "balance_infos": [{"currency": "USD", "total_remaining": 42.5,
                           "total_used": 7.5, "granted_balance": 50}],
    }
    gw = {"type": "deepseek", "base_url": "", "api_key": "sk-x"}
    with mock.patch("tokenmon._get_json", return_value=payload):
        u = tokenmon.fetch_usage(gw)
    assert u.balance == 42.5
    assert u.cost == 7.5
    assert u.currency == "$"


def test_fetch_usage_deepseek_unavailable():
    gw = {"type": "deepseek", "base_url": "", "api_key": "sk-x"}
    with mock.patch("tokenmon._get_json", return_value={"is_available": False}):
        try:
            tokenmon.fetch_usage(gw)
        except ValueError as exc:
            assert "不可用" in str(exc)
        else:
            raise AssertionError("应抛出 ValueError")


# ---- 对话抓取 ----

def test_fetch_conversations_custom():
    payload = [{"prompt": "hi", "tokens": 10, "time": "2026-08-13T10:00:00"}]
    gw = {"type": "custom", "base_url": "http://gw",
          "logs_url": "http://gw/logs", "logs_limit": 10, "logs_page_size": 100}
    with mock.patch("tokenmon._get_json", return_value=payload):
        convs = tokenmon.fetch_conversations(gw)
    assert convs[0].prompt == "hi"
    assert convs[0].tokens == 10


def test_fetch_conversations_custom_no_logs_url():
    gw = {"type": "custom", "base_url": "http://gw",
          "logs_url": "", "logs_limit": 10, "logs_page_size": 100}
    assert tokenmon.fetch_conversations(gw) == []


def test_fetch_conversations_mock():
    gw = {"type": "custom", "base_url": "mock://usage",
          "logs_url": "", "logs_limit": 10, "logs_page_size": 100}
    convs = tokenmon.fetch_conversations(gw)
    assert len(convs) == 10
