"""数据解析/聚合纯函数测试。"""
import tokenmon


# ---- _as_number / get_path / _sum_field ----

def test_as_number():
    assert tokenmon._as_number(None) is None
    assert tokenmon._as_number(True) is None
    assert tokenmon._as_number(False) is None
    assert tokenmon._as_number(42) == 42
    assert tokenmon._as_number(4.5) == 4.5
    assert tokenmon._as_number("1,234") == 1234.0
    assert tokenmon._as_number("abc") is None
    assert tokenmon._as_number([]) is None
    assert tokenmon._as_number(0) == 0  # 合法的 0 不能丢


def test_get_path():
    data = {"a": {"b": {"c": 1}}, "d": [1, 2]}
    assert tokenmon.get_path(data, "a.b.c") == 1
    assert tokenmon.get_path(data, "a.b.x") is None
    assert tokenmon.get_path(data, "x") is None
    assert tokenmon.get_path(data, "d") == [1, 2]


def test_sum_field():
    items = [{"t": 1}, {"t": 2.5}, {}, {"t": "3"}, {"t": None}, "junk"]
    assert tokenmon._sum_field(items, "t") == 6.5
    assert tokenmon._sum_field([{"x": 1}], "t") is None
    assert tokenmon._sum_field([], "t") is None


# ---- 用户消息提取 ----

def test_first_user_message_str():
    assert tokenmon._first_user_message("hi") == "hi"
    assert tokenmon._first_user_message("  你好  ") == "你好"
    assert tokenmon._first_user_message("  ") is None
    assert tokenmon._first_user_message("{}") is None
    assert tokenmon._first_user_message(None) is None


def test_first_user_message_json_string():
    assert (tokenmon._first_user_message(
        '[{"role":"user","content":"hello"}]') == "hello")
    assert (tokenmon._first_user_message(
        '{"role":"assistant","content":"x"}') is None)
    # 裸文本直接作为消息; 以 [/{ 开头但解析失败才算无消息
    assert tokenmon._first_user_message("not json") == "not json"
    assert tokenmon._first_user_message('{"broken":') is None


def test_first_user_message_multimodal():
    msgs = [{"role": "user", "content": [{"type": "text", "text": " 看图 "}]}]
    assert tokenmon._first_user_message(msgs) == "看图"


def test_extract_user_prompt_normal():
    rows = [{"messages": [{"role": "user", "content": "  你好  "}]}]
    assert tokenmon._extract_user_prompt(rows) == "你好"


def test_extract_user_prompt_mcp_fallback():
    rows = [
        {"call_type": "call_mcp_tool",
         "messages": [{"role": "user", "content": "mcp 消息"}]},
        {"messages": [{"role": "assistant", "content": "assistant only"}]},
    ]
    # 第一遍跳过 MCP 行,第二遍(allow_mcp)取到 MCP 消息
    assert tokenmon._extract_user_prompt(rows) == "mcp 消息"


def test_extract_user_prompt_empty():
    assert tokenmon._extract_user_prompt([]) == "（无文本）"
    assert tokenmon._extract_user_prompt([{"messages": None}]) == "（无文本）"


def test_truncate_prompt():
    assert tokenmon._truncate_prompt("  a   b  ") == "a b"
    long = "x" * 200
    out = tokenmon._truncate_prompt(long)
    assert len(out) == 120
    assert out.endswith("…")
    assert tokenmon._truncate_prompt("短") == "短"


# ---- LiteLLM 日志聚合 ----

def _row(sid, rid, tokens=None, prompt_tokens=None, completion_tokens=None,
         start="2026-08-13T10:00:00", call_type=None, messages=None):
    row = {"session_id": sid, "request_id": rid, "startTime": start}
    if tokens is not None:
        row["total_tokens"] = tokens
    if prompt_tokens is not None:
        row["prompt_tokens"] = prompt_tokens
    if completion_tokens is not None:
        row["completion_tokens"] = completion_tokens
    if call_type:
        row["call_type"] = call_type
    if messages is not None:
        row["messages"] = messages
    return row


def test_parse_litellm_logs_groups_and_sorts():
    rows = [
        _row("s1", "r1", tokens=10, start="2026-08-13T10:00:00",
             messages=[{"role": "user", "content": "第一句"}]),
        _row("s1", "r2", tokens=20, start="2026-08-13T10:01:00"),
        _row("s2", "r3", tokens=5, start="2026-08-13T09:00:00",
             messages=[{"role": "user", "content": "第二句"}]),
    ]
    convs = tokenmon._parse_litellm_logs(rows, limit=10)
    assert [c.source_id for c in convs] == ["s1", "s2"]
    assert convs[0].tokens == 30
    assert convs[0].requests == 2
    assert convs[0].prompt == "第一句"
    assert convs[0].last_time == "2026-08-13T10:01:00"
    assert convs[1].tokens == 5
    assert convs[1].requests == 1


def test_parse_litellm_logs_fallback_prompt_completion():
    rows = [
        _row("s1", "r1", prompt_tokens=7, completion_tokens=3,
             messages=[{"role": "user", "content": "hi"}]),
    ]
    convs = tokenmon._parse_litellm_logs(rows, limit=10)
    assert convs[0].tokens == 10


def test_parse_litellm_logs_limit():
    rows = [_row(f"s{i}", f"r{i}", tokens=i) for i in range(10)]
    convs = tokenmon._parse_litellm_logs(rows, limit=3)
    assert len(convs) == 3


def test_parse_litellm_logs_no_session_uses_request_id():
    rows = [
        _row("", "r1", tokens=1, start="2026-08-13T10:00:00"),
        _row("", "r2", tokens=2, start="2026-08-13T11:00:00"),
    ]
    convs = tokenmon._parse_litellm_logs(rows, limit=10)
    assert len(convs) == 2
    assert {c.tokens for c in convs} == {1, 2}


# ---- custom 对话解析 ----

def test_parse_custom_conversations_envelope_and_order():
    data = {"data": [
        {"prompt": "旧", "tokens": 1, "time": "2026-08-13T10:00:00"},
        {"prompt": "新", "totalTokens": 2, "time": "2026-08-13T11:00:00"},
    ]}
    convs = tokenmon._parse_custom_conversations(data, limit=10)
    assert [c.prompt for c in convs] == ["新", "旧"]
    assert convs[0].tokens == 2


def test_parse_custom_conversations_zero_tokens_preserved():
    convs = tokenmon._parse_custom_conversations(
        [{"prompt": "零", "tokens": 0, "time": "2026-08-13T10:00:00"}], 10)
    assert convs[0].tokens == 0
    assert convs[0].tokens is not None


def test_parse_custom_conversations_zero_cost_preserved():
    convs = tokenmon._parse_custom_conversations(
        [{"prompt": "零", "tokens": 5, "cost": 0}], 10)
    assert convs[0].spend == 0
    assert convs[0].spend is not None


def test_parse_custom_conversations_truncates_prompt():
    convs = tokenmon._parse_custom_conversations(
        [{"prompt": "x" * 300, "tokens": 10}], 10)
    assert len(convs[0].prompt) == 120
    assert convs[0].prompt.endswith("…")


def test_parse_custom_conversations_junk():
    assert tokenmon._parse_custom_conversations([1, 2], 10) == []
    assert tokenmon._parse_custom_conversations({"x": 1}, 10) == []
    assert tokenmon._parse_custom_conversations(None, 10) == []
