"""格式化纯函数测试。"""
import tokenmon


def test_fmt_tokens():
    assert tokenmon._fmt_tokens(2215154) == "2,215,154"
    assert tokenmon._fmt_tokens(0) == "0"
    assert tokenmon._fmt_tokens(None) == "—"
    assert tokenmon._fmt_tokens("abc") == "—"


def test_fmt_money():
    assert tokenmon._fmt_money(0.3755, "¥") == "¥0.3755"
    assert tokenmon._fmt_money(0.3755) == "$0.3755"
    assert tokenmon._fmt_money(None) == "—"
    assert tokenmon._fmt_money("x") == "—"


def test_fmt_short():
    assert tokenmon._fmt_short(2_215_154) == "2.2M"
    assert tokenmon._fmt_short(123_456) == "123.5k"
    assert tokenmon._fmt_short(1234) == "1.2k"
    assert tokenmon._fmt_short(999) == "999"
    assert tokenmon._fmt_short(None) == "—"


def test_fmt_money_short():
    assert tokenmon._fmt_money_short(1234.0, "$") == "$1.2k"
    assert tokenmon._fmt_money_short(0.3755, "¥") == "¥0.38"
    assert tokenmon._fmt_money_short(None) == "—"
