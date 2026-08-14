"""配置加载与校验测试。"""
import pytest

import tokenmon


def _write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_config_defaults(tmp_path):
    p = _write(tmp_path, '[gateway]\ntype = "custom"\nbase_url = "mock://usage"\n')
    cfg = tokenmon.load_config(p)
    gw = cfg["gateway"]
    assert gw["type"] == "custom"
    assert gw["refresh_seconds"] == 5
    assert gw["logs_limit"] == 10
    assert gw["logs_page_size"] == 100
    assert gw["logs_refresh_seconds"] == 60
    assert cfg["window"]["always_on_top"] is True
    assert cfg["window"]["decorated"] is False


def test_load_config_type_lowercased(tmp_path):
    p = _write(tmp_path, '[gateway]\ntype = "Custom"\nbase_url = "mock://usage"\n')
    assert tokenmon.load_config(p)["gateway"]["type"] == "custom"


@pytest.mark.parametrize("bad", ["unknown", "LIT", "1", ""])
def test_load_config_rejects_unknown_type(tmp_path, bad):
    p = _write(tmp_path, f'[gateway]\ntype = "{bad}"\nbase_url = "x"\n')
    with pytest.raises(ValueError):
        tokenmon.load_config(p)


def test_load_config_refresh_seconds_min_1(tmp_path):
    p = _write(tmp_path, '[gateway]\ntype = "custom"\nbase_url = "m"\nrefresh_seconds = 0\n')
    with pytest.raises(ValueError, match="refresh_seconds"):
        tokenmon.load_config(p)
    p = _write(tmp_path, '[gateway]\ntype = "custom"\nbase_url = "m"\nrefresh_seconds = -3\n')
    with pytest.raises(ValueError, match="refresh_seconds"):
        tokenmon.load_config(p)
    p = _write(tmp_path, '[gateway]\ntype = "custom"\nbase_url = "m"\nrefresh_seconds = "abc"\n')
    with pytest.raises(ValueError, match="refresh_seconds"):
        tokenmon.load_config(p)
    p = _write(tmp_path, '[gateway]\ntype = "custom"\nbase_url = "m"\nrefresh_seconds = 2.5\n')
    assert tokenmon.load_config(p)["gateway"]["refresh_seconds"] == 2.5


def test_load_config_logs_refresh_min_10(tmp_path):
    p = _write(tmp_path, '[gateway]\ntype = "custom"\nbase_url = "m"\nlogs_refresh_seconds = 9\n')
    with pytest.raises(ValueError):
        tokenmon.load_config(p)


def test_load_config_requires_gateway_section(tmp_path):
    p = _write(tmp_path, '[window]\nalways_on_top = false\n')
    with pytest.raises(ValueError, match="gateway"):
        tokenmon.load_config(p)


def test_load_config_fields_validation(tmp_path):
    p = _write(tmp_path,
               '[gateway]\ntype = "custom"\nbase_url = "m"\n'
               '[gateway.fields]\nunknown_field = "x"\n')
    with pytest.raises(ValueError, match="未知字段"):
        tokenmon.load_config(p)
    p = _write(tmp_path,
               '[gateway]\ntype = "custom"\nbase_url = "m"\n'
               '[gateway.fields]\nprompt = 123\n')
    with pytest.raises(ValueError, match="映射表"):
        tokenmon.load_config(p)


def test_load_config_valid_field_override(tmp_path):
    p = _write(tmp_path,
               '[gateway]\ntype = "custom"\nbase_url = "m"\n'
               '[gateway.fields]\ntotal = "data.total_tokens"\ncost = "data.cost"\n')
    cfg = tokenmon.load_config(p)
    assert cfg["gateway"]["fields"]["total"] == "data.total_tokens"
