#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""TokenMon 数据层 —— 配置加载 / 网关抓取 / 解析聚合 / 格式化。

纯标准库实现(无 GUI 依赖): GUI 层(tokenmon.py)与资产生成工具都复用它。
提供: load_config、fetch_usage、fetch_conversations、Usage、Conversation、
各解析/格式化纯函数,以及 CONFIG_PATH 等常量。
"""

import os
import sys


def _bootstrap_python():
    """PATH 里的 python3 可能是旧版本(pyenv 等),自动改投 >= 3.11 的解释器。"""
    if sys.version_info >= (3, 11):
        return
    if os.environ.get("TOKENMON_REEXEC"):
        return  # 改投过仍不满足,走下方报错
    import shutil
    import subprocess

    candidates = []
    if os.name == "nt":
        py = shutil.which("py")
        if py:
            candidates.append([py, "-3"])
    else:
        for p in ("/usr/bin/python3", "/usr/bin/python3.13", "/usr/bin/python3.12",
                  "/usr/bin/python3.11"):
            candidates.append([p])
    for cand in candidates:
        try:
            if os.path.realpath(cand[0]) == os.path.realpath(sys.executable):
                continue
            r = subprocess.run(
                [*cand, "-c",
                 "import sys;print(sys.version_info.major, sys.version_info.minor)"],
                capture_output=True, text=True, timeout=15,
            )
            parts = r.stdout.split()
            if r.returncode == 0 and len(parts) == 2 and tuple(map(int, parts)) >= (3, 11):
                os.environ["TOKENMON_REEXEC"] = "1"
                os.execv(cand[0], [*cand, *sys.argv])
        except Exception:
            continue
    try:
        print(f"[tokenmon] 需要 Python >= 3.11(当前 {sys.version.split()[0]})", file=sys.stderr)
        if os.name == "nt":
            print("           请安装 Python 3.11+: https://www.python.org/downloads/", file=sys.stderr)
        else:
            print("           请用系统 Python 运行: /usr/bin/python3 tokenmon.py", file=sys.stderr)
    except Exception:
        pass
    sys.exit(1)


_bootstrap_python()

import json
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path


def _safe_print(*args, **kwargs):
    """pythonw(Windows 免控制台)下 stdout/stderr 为 None,打印需兜底。"""
    try:
        print(*args, **kwargs)
    except Exception:
        pass


def get_config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "tokenmon"
    home_default = Path.home() / ".config" / "tokenmon"
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", str(home_default.parent))) / "tokenmon"
    # Flatpak 沙箱(VSCode 等)会把 XDG_CONFIG_HOME 重定向到 ~/.var/app/...,
    # 但用户编辑的总是宿主 home 下的配置 —— 已存在则优先用它
    if xdg != home_default and (home_default / "config.toml").exists():
        return home_default
    return xdg


CONFIG_DIR = get_config_dir()
CONFIG_PATH = CONFIG_DIR / "config.toml"
USER_AGENT = "tokenmon/2.0"

# custom 网关字段映射的唯一事实来源: 默认配置文本与抓取逻辑都从这里生成,
# 改字段只需动这一处。
DEFAULT_FIELD_MAP = {
    "prompt": "promptTokens",
    "completion": "completionTokens",
    "reasoning": "reasoningTokens",
    "cache_hit": "cacheHitTokens",
    "cache_miss": "cacheMissTokens",
    "session_cache_hit": "sessionCacheHitTokens",
    "session_cache_miss": "sessionCacheMissTokens",
    "total": "totalTokens",
    "cost": "cost",
    "currency": "currency",
}

_FIELDS_TOML = "\n".join(f'  {k} = "{v}"' for k, v in DEFAULT_FIELD_MAP.items())

DEFAULT_CONFIG = f"""\
# TokenMon 配置 —— 首次运行自动生成,编辑后重启生效
# 支持三种网关类型: custom | litellm | openrouter

[gateway]
type = "custom"             # custom | litellm | openrouter | deepseek
base_url = "http://127.0.0.1:8080/usage"   # custom 网关返回 token 统计 JSON 的地址; 体验演示数据可填 "mock://usage"
api_key = ""                # 留空则不发送鉴权头; litellm 用 x-api-key, openrouter/custom 用 Bearer
refresh_seconds = 5         # 用量轮询间隔(秒,>=1),越小越实时,别打爆网关

# 最近对话列表(主界面"对话"面板显示最近 N 次对话的 prompt 与 token 总量)
logs_url = ""               # 仅 custom: 返回最近对话 JSON 数组的地址,留空禁用
logs_limit = 10             # 展示最近 N 条对话 (1..50)
logs_page_size = 100        # litellm /spend/logs 每页条数 (1..1000)
logs_refresh_seconds = 60   # 对话列表刷新间隔(秒,>=10,独立于 refresh_seconds)

# 仅 custom 类型生效: 程序字段名 = 响应 JSON 中的点分路径。
# 默认映射已适配常见网关返回(如 Claude Code 风格的 cacheHitTokens/reasoningTokens 等);
# 字段缺失时对应行自动隐藏(currency 如 "¥" 或 "$"):
[gateway.fields]
{_FIELDS_TOML}

# custom 的 logs_url 约定返回 JSON 数组(按时间升序,最新的在末尾):
#   [{{"prompt": "用户第一句话…", "tokens": 12345, "time": "2026-08-13T10:00:00"}}]
# 也兼容 {{"data": [...]}} 信封; tokens 键名接受 tokens/total_tokens/totalTokens。

[window]
always_on_top = true        # 置顶: Windows/X11 原生生效; Wayland 无协议,尽力而为
decorated = false           # 主界面边框(精灵球永远无边框); 想要系统标题栏可改 true
"""


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------
_FIELD_NAMES = set(DEFAULT_FIELD_MAP)


def _as_int(cfg_value, key: str, lo: int, hi: int) -> int:
    try:
        v = int(cfg_value)
    except (TypeError, ValueError):
        raise ValueError(f"[gateway] {key} 必须是整数")
    if not lo <= v <= hi:
        raise ValueError(f"[gateway] {key} 必须在 {lo}..{hi} 之间")
    return v


def load_config(path: Path) -> dict:
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    if "gateway" not in cfg:
        raise ValueError(f"{path}: 缺少 [gateway] 段")
    gw = cfg["gateway"]
    gw.setdefault("type", "litellm")
    gw.setdefault("base_url", "")
    gw.setdefault("api_key", "")
    gw.setdefault("refresh_seconds", 5)
    try:
        refresh = float(gw["refresh_seconds"])
    except (TypeError, ValueError):
        raise ValueError("[gateway] refresh_seconds 必须是数字(秒)")
    if refresh < 1:
        raise ValueError("[gateway] refresh_seconds 不能小于 1 秒(否则轮询会空转)")
    gw["refresh_seconds"] = refresh
    gw.setdefault("logs_url", "")
    gw.setdefault("logs_limit", 10)
    gw.setdefault("logs_page_size", 100)
    gw.setdefault("logs_refresh_seconds", 60)
    if not isinstance(gw.get("logs_url"), str):
        raise ValueError("[gateway] logs_url 必须是字符串")
    gw["logs_limit"] = _as_int(gw["logs_limit"], "logs_limit", 1, 50)
    gw["logs_page_size"] = _as_int(gw["logs_page_size"], "logs_page_size", 1, 1000)
    try:
        gw["logs_refresh_seconds"] = float(gw["logs_refresh_seconds"])
    except (TypeError, ValueError):
        raise ValueError("[gateway] logs_refresh_seconds 必须是数字(秒)")
    if gw["logs_refresh_seconds"] < 10:
        raise ValueError("[gateway] logs_refresh_seconds 不能小于 10 秒")
    cfg.setdefault("window", {"always_on_top": True, "decorated": False})
    cfg["window"].setdefault("always_on_top", True)
    cfg["window"].setdefault("decorated", False)
    gtype = gw.get("type")
    if not isinstance(gtype, str):
        raise ValueError("[gateway] type 必须是字符串(litellm/openrouter/custom)")
    gtype = gtype.lower()
    if gtype not in ("litellm", "openrouter", "custom", "deepseek"):
        raise ValueError(f"未知 gateway type: {gtype!r} (可选: litellm/openrouter/custom/deepseek)")
    gw["type"] = gtype
    if gtype == "custom" and "fields" in gw:
        if not isinstance(gw["fields"], dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in gw["fields"].items()
        ):
            raise ValueError('[gateway.fields] 必须是 字段名 = "JSON点分路径" 的映射表')
        unknown = set(gw["fields"]) - _FIELD_NAMES
        if unknown:
            raise ValueError(
                "[gateway.fields] 未知字段名: " + ", ".join(sorted(unknown))
                + " (可选: " + ", ".join(sorted(_FIELD_NAMES)) + ")"
            )
    return cfg


def _open_with_default_app(path: Path) -> str | None:
    """用系统默认方式打开文件/目录(文本编辑器/文件管理器);失败返回错误信息。"""
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return None
        if path.is_file():
            import shlex
            import subprocess
            editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
            if editor:
                subprocess.Popen([*shlex.split(editor), str(path)])
                return None
        import subprocess
        subprocess.Popen(["xdg-open", str(path)])
        return None
    except Exception as exc:
        return str(exc)


# --------------------------------------------------------------------------
# 数据模型
# --------------------------------------------------------------------------
class Usage:
    """一次轮询的用量快照。各字段可为 None(网关不提供该指标)。

    内部字段名(小写下划线) ↔ JSON 字段由 [gateway.fields] 映射。
    """

    __slots__ = (
        "prompt", "completion", "reasoning", "cache_hit", "cache_miss",
        "session_cache_hit", "session_cache_miss", "total", "cost",
        "balance", "currency", "raw",
    )

    def __init__(self, prompt=None, completion=None, reasoning=None, cache_hit=None,
                 cache_miss=None, session_cache_hit=None, session_cache_miss=None,
                 total=None, cost=None, balance=None, currency=None, raw=None):
        self.prompt = prompt
        self.completion = completion
        self.reasoning = reasoning
        self.cache_hit = cache_hit
        self.cache_miss = cache_miss
        self.session_cache_hit = session_cache_hit
        self.session_cache_miss = session_cache_miss
        self.total = total
        self.cost = cost
        self.balance = balance
        self.currency = currency
        self.raw = raw or {}

    def to_dict(self):
        return {
            "prompt": self.prompt, "completion": self.completion,
            "reasoning": self.reasoning, "cache_hit": self.cache_hit,
            "cache_miss": self.cache_miss, "session_cache_hit": self.session_cache_hit,
            "session_cache_miss": self.session_cache_miss, "total": self.total,
            "cost": self.cost, "balance": self.balance, "currency": self.currency,
        }


class Conversation:
    """一次对话的聚合快照(prompt + token 总量)。"""

    __slots__ = ("prompt", "tokens", "spend", "requests", "last_time", "source_id")

    def __init__(self, prompt="（无文本）", tokens=None, spend=None, requests=1,
                 last_time=None, source_id=""):
        self.prompt = prompt
        self.tokens = tokens
        self.spend = spend
        self.requests = requests
        self.last_time = last_time
        self.source_id = source_id

    def to_dict(self):
        return {
            "prompt": self.prompt, "tokens": self.tokens, "spend": self.spend,
            "requests": self.requests, "last_time": self.last_time,
            "source_id": self.source_id,
        }


# --------------------------------------------------------------------------
# 数据抓取(用量)
# --------------------------------------------------------------------------
def _as_number(v):
    """把 int/float/数字字符串转成数值,其余(含 None)返回 None。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def get_path(data, dotted: str):
    """按点分路径取嵌套字段,如 'data.total_tokens'。"""
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _sum_field(items, key):
    """对一组 dict 的字段求和(忽略缺失/非数值项); 全空时返回 None。"""
    total = 0.0
    found = False
    for it in items:
        if isinstance(it, dict):
            v = _as_number(it.get(key))
            if v is not None:
                total += v
                found = True
    return total if found else None


class FetchError(Exception):
    """带 HTTP 状态码的抓取错误,消息含完整请求 URL。"""

    def __init__(self, msg, http_code=None):
        super().__init__(msg)
        self.http_code = http_code


def _get_json(url: str, headers: dict):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} {exc.reason}: {url}", http_code=exc.code) from None
    except urllib.error.URLError as exc:
        raise FetchError(f"网络错误 {exc.reason}: {url}") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise FetchError(f"响应不是合法 JSON: {url}") from None


def _mock_usage():
    return Usage(
        prompt=2105876, completion=109278, reasoning=79503,
        cache_hit=1988736, cache_miss=117140,
        session_cache_hit=1988736, session_cache_miss=117140,
        total=2215154, cost=0.3755, currency="¥", raw={"mock": True},
    )


def fetch_usage(gw: dict) -> Usage:
    """按网关类型抓取用量。异常向上抛,由调用方统一处理。"""
    gtype = gw["type"].lower()
    base = str(gw.get("base_url", "")).rstrip("/")
    key = gw.get("api_key") or ""
    headers = {"User-Agent": USER_AGENT}

    if base.startswith("mock://"):
        return _mock_usage()

    if gtype == "litellm":
        if not base:
            raise ValueError("litellm 网关需要配置 base_url")
        if key:
            headers["x-api-key"] = key
        data = _get_json(f"{base}/usage", headers)
        # 不同 LiteLLM 版本返回结构不一: 顶层聚合 / 按 key 的 api_keys / 列表 data,逐一兼容
        tokens = _as_number(data.get("total_tokens"))
        cost = _as_number(data.get("total_cost"))
        if tokens is None and isinstance(data.get("api_keys"), dict):
            tokens = _sum_field(data["api_keys"].values(), "total_tokens")
        if cost is None and isinstance(data.get("api_keys"), dict):
            cost = _sum_field(data["api_keys"].values(), "total_cost")
        if tokens is None and isinstance(data.get("data"), list):
            tokens = _sum_field(data["data"], "total_tokens")
        if cost is None and isinstance(data.get("data"), list):
            cost = _sum_field(data["data"], "total_cost")
        return Usage(total=tokens, cost=cost, currency="$", raw=data)

    if gtype == "openrouter":
        if not key:
            raise ValueError("openrouter 网关需要配置 api_key")
        headers["Authorization"] = f"Bearer {key}"
        data = _get_json("https://openrouter.ai/api/v1/auth/key", headers)
        usage = (data.get("data") or {}).get("usage") or {}
        credits = _as_number(usage.get("total_usage"))
        # OpenRouter 的 total_usage 以 credit 计,$1 = 1000 credit
        cost = credits / 1000.0 if credits is not None else None
        return Usage(cost=cost, currency="$", raw=data)

    if gtype == "deepseek":
        # DeepSeek 官方无 token 用量统计,只提供余额查询(参考 cc_switch 的查询方式)
        if not key:
            raise ValueError("deepseek 网关需要配置 api_key")
        headers["Authorization"] = f"Bearer {key}"
        url = f"{base or 'https://api.deepseek.com'}/user/balance"
        data = _get_json(url, headers)
        if not data.get("is_available"):
            raise ValueError("DeepSeek 余额查询不可用(is_available=false)")
        infos = data.get("balance_infos") or []
        info = infos[0] if infos and isinstance(infos[0], dict) else {}
        currency = str(info.get("currency") or "CNY")
        sym = {"CNY": "¥", "USD": "$"}.get(currency.upper(), currency)
        # 实际接口只有 total_balance/granted_balance/topped_up_balance;
        # total_remaining/total_used 是 cc_switch extractor 的字段,兼容两者
        remaining = _as_number(info.get("total_remaining"))
        balance = remaining if remaining is not None else _as_number(info.get("total_balance"))
        cost = _as_number(info.get("total_used"))
        if cost is None and balance is not None:
            # 接口无 total_used: 已用 = 赠送 + 充值 - 当前余额
            granted = _as_number(info.get("granted_balance")) or 0
            topped = _as_number(info.get("topped_up_balance")) or 0
            used = granted + topped - balance
            cost = used if used >= 0 else None
        return Usage(balance=balance, cost=cost, currency=sym, raw=data)

    # custom —— 按 [gateway.fields] 映射取数,默认适配 cacheHitTokens 风格 JSON
    if not base:
        raise ValueError("custom 网关需要配置 base_url")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = _get_json(base, headers)
    fields = {**DEFAULT_FIELD_MAP, **(gw.get("fields") or {})}
    # 旧式配置兼容: tokens_path/cost_path 直接映射 total/cost
    if gw.get("tokens_path") and not gw.get("fields"):
        fields["total"] = gw["tokens_path"]
    if gw.get("cost_path") and not gw.get("fields"):
        fields["cost"] = gw["cost_path"]
    vals = {}
    for fname, path in fields.items():
        if fname == "currency":
            v = get_path(data, path)
            vals[fname] = v if isinstance(v, str) else None
        else:
            vals[fname] = _as_number(get_path(data, path))
    return Usage(raw=data, **vals)


# --------------------------------------------------------------------------
# 数据抓取(最近对话)
# --------------------------------------------------------------------------
_MCP_CALL_TYPES = {"call_mcp_tool", "list_mcp_tools", "mcp"}


def _rows_from_envelope(data):
    if isinstance(data, dict):
        rows = data.get("data")
        return rows if isinstance(rows, list) else []
    if isinstance(data, list):
        return data
    return []


def _sum_num(rows, *keys):
    total = 0.0
    found = False
    for r in rows:
        for k in keys:
            v = _as_number(r.get(k))
            if v is not None:
                total += v
                found = True
                break
    return total if found else None


def _first_user_message(messages):
    if messages is None:
        return None
    if isinstance(messages, str):
        s = messages.strip()
        if not s or s == "{}":
            return None
        if s[:1] not in ("[", "{"):
            return s  # 非 JSON 的裸文本直接当用户消息(部分网关把 messages 存成纯文本)
        try:
            messages = json.loads(s)
        except ValueError:
            return None
    if isinstance(messages, dict):
        messages = [messages]
    if not isinstance(messages, list):
        return None
    for m in messages:
        if not isinstance(m, dict):
            continue
        if str(m.get("role") or "").lower() == "user":
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                return c.strip()
            if isinstance(c, list):  # 多模态块
                for part in c:
                    if isinstance(part, dict) and isinstance(part.get("text"), str) \
                            and part["text"].strip():
                        return part["text"].strip()
    return None


def _truncate_prompt(text: str, maxlen: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= maxlen else text[: maxlen - 1] + "…"


def _extract_user_prompt(rows):
    """组内按 startTime 升序取第一条 user 消息文本。"""
    for allow_mcp in (False, True):
        for r in rows:
            if not allow_mcp and str(r.get("call_type") or "") in _MCP_CALL_TYPES:
                continue
            msg = _first_user_message(r.get("messages"))
            if msg:
                return _truncate_prompt(msg)
    return "（无文本）"


def _parse_litellm_logs(rows, limit: int):
    """把 LiteLLM spend/logs 行按 session_id(缺则 request_id)聚合成对话列表。"""
    groups = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("session_id") or "")
        rid = str(row.get("request_id") or "")
        key = sid or rid or f"__single_{len(groups)}"
        groups.setdefault(key, []).append(row)
    convs = []
    for key, group_rows in groups.items():
        group_rows.sort(key=lambda r: str(r.get("startTime") or ""))
        tokens = _sum_num(group_rows, "total_tokens")
        if tokens is None:
            p = _sum_num(group_rows, "prompt_tokens")
            c = _sum_num(group_rows, "completion_tokens")
            tokens = (p or 0) + (c or 0) if (p is not None or c is not None) else None
        last_time = max((str(r.get("startTime") or "") for r in group_rows), default="")
        convs.append(Conversation(
            prompt=_extract_user_prompt(group_rows),
            tokens=tokens,
            spend=_sum_num(group_rows, "spend"),
            requests=len(group_rows),
            last_time=last_time or None,
            source_id=key,
        ))
    convs.sort(key=lambda c: c.last_time or "", reverse=True)
    return convs[:limit]


def _fetch_litellm_conversations(base: str, headers: dict, limit: int, page_size: int):
    def page_url(ep: str, page: int) -> str:
        return f"{base}{ep}?page={page}&page_size={page_size}&sort_by=startTime&sort_order=desc"

    # v2 优先,404 降级 /spend/logs/ui;两者都是 {data, total_pages} 信封带分页
    for ep in ("/spend/logs/v2", "/spend/logs/ui"):
        try:
            data = _get_json(page_url(ep, 1), headers)
        except FetchError as exc:
            if exc.http_code in (404, 405):
                continue
            raise
        rows = _rows_from_envelope(data)
        total_pages = data.get("total_pages") or 1  # 键缺失或 null 都按 1 页处理
        page = 1
        convs = _parse_litellm_logs(rows, limit)
        deadline = time.monotonic() + 20.0  # 分页总时长预算,防慢网关拖住轮询
        while (len(convs) < limit and page < min(int(total_pages), 3)
               and time.monotonic() < deadline):
            page += 1
            try:
                data = _get_json(page_url(ep, page), headers)
            except Exception:
                break
            rows = [*rows, *_rows_from_envelope(data)]
            convs = _parse_litellm_logs(rows, limit)
        return convs

    # 旧版 /spend/logs: 无分页,返回裸数组
    data = _get_json(f"{base}/spend/logs", headers)
    return _parse_litellm_logs(_rows_from_envelope(data), limit)


def _parse_custom_conversations(data, limit: int):
    if isinstance(data, dict):  # 兼容 {"data": [...]} 信封
        for k in ("conversations", "logs", "data"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
        else:
            return []
    if not isinstance(data, list):
        return []
    convs = []
    for item in data:
        if not isinstance(item, dict):
            continue
        prompt = item.get("prompt") or item.get("question") or item.get("text")
        prompt = _truncate_prompt(prompt) if prompt else "（无文本）"
        tokens = None
        for k in ("tokens", "total_tokens", "totalTokens"):
            v = _as_number(item.get(k))
            if v is not None:
                tokens = v
                break
        spend = _as_number(item.get("spend"))
        if spend is None:
            spend = _as_number(item.get("cost"))
        convs.append(Conversation(
            prompt=prompt,
            tokens=tokens,
            spend=spend,
            requests=1,
            last_time=str(item.get("time") or item.get("startTime") or "") or None,
            source_id=str(item.get("id") or item.get("session_id") or ""),
        ))
    # 约定网关按时间升序返回; 有 time 字段时按它排,否则保持原顺序反转取尾部
    convs.reverse()
    convs.sort(key=lambda c: c.last_time or "", reverse=True)
    return convs[:limit]


def _mock_conversations():
    samples = [
        ("帮我优化 tokenmon,做成精灵球样式,并适配 Windows", 123456, "2026-08-13T11:30:00"),
        ("写一个 litellm 网关的用量聚合脚本", 88912, "2026-08-13T10:12:00"),
        ("解释一下 OpenRouter 的 credit 计费规则", 45210, "2026-08-12T21:47:00"),
        ("重构 FastAPI 项目,拆分路由模块", 210330, "2026-08-12T16:05:00"),
        ("用 Rust 写一个 JSON 解析器", 78020, "2026-08-12T09:21:00"),
        ("帮我调试 postgres 慢查询", 56784, "2026-08-11T19:40:00"),
        ("翻译一段技术文档", 8120, "2026-08-11T15:02:00"),
        ("写单元测试覆盖边界情况", 43150, "2026-08-11T10:55:00"),
        ("给 NAS 设计一个备份策略", 15340, "2026-08-10T22:18:00"),
        ("解释 Python GIL 与 asyncio", 28760, "2026-08-10T14:33:00"),
    ]
    return [
        Conversation(prompt=p, tokens=t, spend=round(t * 0.000002, 4),
                     requests=1, last_time=ts, source_id=f"mock-{i}")
        for i, (p, t, ts) in enumerate(samples)
    ]


def fetch_conversations(gw: dict) -> list:
    """抓取最近对话列表。异常向上抛,由调用方降级为"无数据"。"""
    base = str(gw.get("base_url", "")).rstrip("/")
    key = gw.get("api_key") or ""
    limit = int(gw.get("logs_limit", 10))
    page_size = int(gw.get("logs_page_size", 100))
    headers = {"User-Agent": USER_AGENT}
    gtype = gw["type"].lower()

    if base.startswith("mock://") or str(gw.get("logs_url", "")).startswith("mock://"):
        return _mock_conversations()

    if gtype == "litellm":
        if not base:
            raise ValueError("litellm 网关需要配置 base_url")
        if key:
            headers["x-api-key"] = key
        return _fetch_litellm_conversations(base, headers, limit, page_size)

    if gtype == "custom":
        url = str(gw.get("logs_url") or "").strip()
        if not url:
            return []
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return _parse_custom_conversations(_get_json(url, headers), limit)
    return []


# --------------------------------------------------------------------------
# 格式化(纯函数,CLI 与 GUI 共用)
# --------------------------------------------------------------------------
def _fmt_tokens(n) -> str:
    try:
        return f"{int(round(n)):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_money(n, currency=None) -> str:
    try:
        f = float(n)
    except (TypeError, ValueError):
        return "—"
    sym = currency if isinstance(currency, str) and currency else "$"
    return f"{sym}{f:.4f}"


def _fmt_short(n) -> str:
    """悬浮球用紧凑格式: 2.2M / 123k / 1,234"""
    try:
        f = float(n)
    except (TypeError, ValueError):
        return "—"
    if f >= 1_000_000:
        return f"{f / 1_000_000:.1f}M"
    if f >= 1_000:
        return f"{f / 1_000:.1f}k"
    return f"{int(round(f)):,}"


def _fmt_money_short(n, currency=None) -> str:
    """悬浮球用紧凑金额: $0.38 / ¥1.2k"""
    try:
        f = float(n)
    except (TypeError, ValueError):
        return "—"
    sym = currency if isinstance(currency, str) and currency else "$"
    if f >= 1_000:
        return f"{sym}{f / 1_000:.1f}k"
    return f"{sym}{f:.2f}"

