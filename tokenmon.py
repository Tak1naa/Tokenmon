#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""TokenMon —— 精灵球悬浮窗,实时监控 LLM API 网关的 token 用量。

功能:
  * 宝可梦精灵球样式的无边框置顶悬浮球,实时显示 token 用量缩写,
    可拖动;左键展开/收起主界面,右键菜单(显示主界面 / 退出)
  * 主界面: token 用量 / 缓存命中 / 费用三项主指标,详情下拉
    (Prompt/Completion/Reasoning/缓存明细/会话增量/实时速率),
    最近对话面板(最近 N 次对话的 prompt 与 token 总量)
  * 系统托盘图标: Windows 原生;Linux(GNOME)需 AppIndicator 扩展,
    不可用时自动降级,精灵球照常工作
  * 支持 LiteLLM proxy / OpenRouter / 自定义 JSON 网关

要求: Python >= 3.11(tomllib)+ PySide6
      Windows: pip install pyside6
      Fedora:  sudo dnf install python3-pyside6

用法:
  python3 tokenmon.py                # 启动悬浮窗
  python3 tokenmon.py --once         # 只抓取一次数据并打印(无需 GUI)
  python3 tokenmon.py --once --logs  # 附带最近对话列表
  python3 tokenmon.py --smoke 10     # 启动 GUI 10 秒后自动退出(无显示测试)
  python3 tokenmon.py --config PATH  # 指定配置文件
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

import argparse
import json
import threading
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


# --------------------------------------------------------------------------
# Qt 区(PySide6 GUI)—— --once 模式不依赖本区
# --------------------------------------------------------------------------
HAVE_QT = False
QT_IMPORT_ERROR = ""
try:
    from PySide6.QtCore import (Qt, QObject, QPoint, QRect, QRectF, QPointF,
                                QTimer, Signal, Slot, QLockFile, Property,
                                QPropertyAnimation, QEasingCurve)
    from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QFontMetrics, QIcon,
                               QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                               QRegion)
    from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMenu,
                                   QPushButton, QScrollArea, QSystemTrayIcon,
                                   QVBoxLayout, QWidget, QWidgetAction)
    HAVE_QT = True
except Exception as _exc:  # pragma: no cover - 无 PySide6 时 --once 仍可用
    QT_IMPORT_ERROR = str(_exc)

if HAVE_QT:

    BALL_SIZE = 64

    DETAIL_FIELDS = [
        ("prompt", "Prompt", "num"),
        ("completion", "Completion", "num"),
        ("reasoning", "Reasoning", "num_gt0"),
        ("cache_miss", "Cache Miss", "num"),
        ("session_cache_hit", "Session Hit", "num"),
        ("session_cache_miss", "Session Miss", "num"),
        ("session_delta", "本会话增量", "num"),
        ("rate", "实时速率", "rate"),
    ]

    APP_STYLESHEET = """
    QMenu {
        background-color: #1e222b;
        color: #eef0f3;
        border: 1px solid #3a3f4a;
        border-radius: 8px;
        padding: 4px;
    }
    QMenu::item { padding: 5px 18px 5px 10px; border-radius: 5px; }
    QMenu::item:selected { background: rgba(255, 255, 255, 0.10); }
    QMenu::separator { height: 1px; background: #3a3f4a; margin: 4px 6px; }
    QFrame#panel {
        background-color: #16181d;
        border-radius: 14px;
    }
    QFrame#convrow { border-bottom: 1px solid rgba(255, 255, 255, 0.05); }
    QLabel[cls="dot"] { color: #3fb950; font-size: 13px; }
    QLabel[cls="dot"][err="true"] { color: #f85149; }
    QLabel[cls="caption"] { color: #c8cdd4; font-size: 12px; font-weight: 600; }
    QLabel[cls="status"] { color: #6e7681; font-size: 11px; }
    QLabel[cls="row-label"] { color: #c8cdd4; font-size: 13px; }
    QLabel[cls="row-value"] { color: #eef0f3; font-size: 15px; font-weight: 600; }
    QLabel[cls="detail-label"] { color: #8b93a1; font-size: 12px; }
    QLabel[cls="detail-value"] { color: #eef0f3; font-size: 13px; }
    QLabel[cls="conv-header"] { color: #e3350d; font-size: 12px; font-weight: 700; }
    QLabel[cls="conv-prompt"] { color: #eef0f3; font-size: 12px; }
    QLabel[cls="conv-tokens"] { color: #3fb950; font-size: 12px; font-weight: 600; }
    QLabel[cls="conv-sub"] { color: #6e7681; font-size: 10px; }
    QPushButton[cls="btn"] {
        background: transparent; color: #9aa0a6; border: none;
        border-radius: 6px; padding: 2px 8px; font-size: 13px;
    }
    QPushButton[cls="btn"]:hover { background: rgba(255, 255, 255, 0.08); color: #ffffff; }
    QPushButton[cls="btn"]:pressed { background: rgba(255, 255, 255, 0.15); }
    QScrollArea#convs {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 8px;
    }
    """

    # ----------------------------------------------------------------------
    # 精灵球绘制(唯一绘制源,悬浮球与托盘图标共用)
    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    # 皮肤(精灵球 / 大师球 / 超级球 / 高级球)
    # ----------------------------------------------------------------------
    # 各球外观按宝可梦官方设定:
    #   精灵球 = 红上半 + 白下半; 大师球 = 紫上半 + 顶部粉色 M 徽记(官方无"双耳");
    #   超级球 = 蓝上半 + 球内两侧红色矩形侧块; 高级球 = 深色上半 + 顶部黄色横纹
    # 侧块几何(球坐标系,球心 32,32,球半径 30.5):
    #   bump_dx = 左块左边距球左缘的距离; bump_dy = 距球顶; bump_w/bump_h = 尺寸
    SKINS = {
        "pokeball": {"label": "精灵球", "top_hi": "#ef3a26", "top_lo": "#cf2410"},
        "master": {"label": "大师球", "top_hi": "#8a4fd8", "top_lo": "#551fa8",
                   "emblem": "M", "emblem_color": "#f04f9e"},
        "great": {"label": "超级球", "top_hi": "#3f7fe0", "top_lo": "#1d55b3",
                  "bumps": True, "bump_w": 10.0, "bump_h": 8.0,
                  "bump_dx": 3.5, "bump_dy": 18.0},
        "ultra": {"label": "高级球", "top_hi": "#3d4046", "top_lo": "#17181c",
                  "stripe": "#ffd733"},
    }
    DEFAULT_SKIN = "pokeball"

    # 球身文字字体缓存: 按文字内容缓存最终字号,避免每帧重建 QFont/QFontMetrics
    _FONT_CACHE: dict = {}

    def _add_skin_actions(menu: QMenu, current: str, on_pick,
                          submenu: bool = True) -> None:
        """给菜单加皮肤选项。

        submenu=True: 放进「皮肤」子菜单(右键菜单与托盘菜单共用,避免挤占其他项);
        submenu=False: 直接平铺在 menu 里(主界面的「皮肤 ▾」按钮就是专用菜单,
        再套一层子菜单纯属多余)。
        """
        target = menu.addMenu("皮肤") if submenu else menu
        for name, spec in SKINS.items():
            act = target.addAction(spec["label"])
            act.setCheckable(True)
            act.setChecked(name == current)
            act.triggered.connect(lambda _checked=False, n=name: on_pick(n))

    def draw_pokeball(p: QPainter, rect: QRectF, text=None, skin=None):
        skin = skin or SKINS[DEFAULT_SKIN]
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = rect.center().x(), rect.center().y()
        r = min(rect.width(), rect.height()) / 2 - 1.5
        ball_circle = QRectF(cx - r, cy - r, 2 * r, 2 * r)

        top = QPainterPath()
        top.moveTo(cx - r, cy)
        # Qt 角度: 0°=3点钟方向,逆时针为正; 0°→180° 经 12 点方向画上半圆
        top.arcTo(ball_circle, 0, 180)
        top.closeSubpath()
        grad = QLinearGradient(cx, cy - r, cx, cy)
        grad.setColorAt(0.0, QColor(skin["top_hi"]))
        grad.setColorAt(1.0, QColor(skin["top_lo"]))
        p.fillPath(top, QBrush(grad))

        bottom = QPainterPath()
        bottom.moveTo(cx - r, cy)
        # 180°→360° 经 6 点方向画下半圆
        bottom.arcTo(ball_circle, 180, 180)
        bottom.closeSubpath()
        p.fillPath(bottom, QBrush(QColor("#f8f9fa")))

        # 高级球: 上半的黄色横纹(裁剪在球内)
        # 注意: 必须用 IntersectClip —— 球两半打开时 paintEvent 已有半圆裁剪,
        # 直接 setClipPath 会替换掉它,横纹会渗进两半之间的空隙。
        if skin.get("stripe"):
            clip = QPainterPath()
            clip.addEllipse(ball_circle)
            p.save()
            p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
            p.fillRect(QRectF(cx - r, cy - r + 9, 2 * r, 5), QColor(skin["stripe"]))
            p.restore()

        band_h = 8.0
        band = QRectF(cx - r, cy - band_h / 2, 2 * r, band_h)
        p.fillRect(band, QColor("#1e2023"))
        p.fillRect(QRectF(band.left(), band.top(), band.width(), 1),
                   QColor(255, 255, 255, 18))
        p.fillRect(QRectF(band.left(), band.bottom() - 1, band.width(), 1),
                   QColor(0, 0, 0, 40))

        # 中央按钮: 白底 + 深色圆环
        p.setPen(QPen(QColor("#3a3d45"), 2))
        p.setBrush(QBrush(QColor("#f8f9fa")))
        p.drawEllipse(QPointF(cx, cy), 10.5, 10.5)
        if skin.get("mark"):
            f = QFont()
            f.setBold(True)
            f.setPixelSize(9)
            p.setFont(f)
            p.setPen(QColor(skin.get("mark_color") or skin["top_lo"]))
            p.drawText(QRectF(cx - 10.5, cy - 10.5, 21, 21),
                       Qt.AlignmentFlag.AlignCenter, skin["mark"])

        p.setPen(QPen(QColor("#26282d"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # 顶部徽记(大师球的 M): 画在数据文字上方,不与按钮/文字重叠
        emblem = skin.get("emblem")
        emblem_h = r - band_h / 2 - 13.0
        if emblem:
            ef = QFont()
            ef.setBold(True)
            es = 14
            while es >= 8:
                ef.setPixelSize(es)
                if QFontMetrics(ef).horizontalAdvance(emblem) <= 2 * r - 8:
                    break
                es -= 1
            p.setFont(ef)
            p.setPen(QColor(skin.get("emblem_color", "#ffffff")))
            p.drawText(QRectF(cx - r, cy - r + 1, 2 * r, emblem_h - 1),
                       Qt.AlignmentFlag.AlignCenter, emblem)

        # 超级球: 球内两侧的红色矩形侧块(不伸出球体,圆角 2px)
        if skin.get("bumps"):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#e3350d"))
            bw = skin.get("bump_w", 10.0)
            bh = skin.get("bump_h", 15.0)
            bdx = skin.get("bump_dx", 1.5)
            bdy = skin.get("bump_dy", 10.0)
            p.drawRoundedRect(QRectF(cx - r + bdx, cy - r + bdy, bw, bh), 2, 2)
            p.drawRoundedRect(QRectF(cx + r - bdx - bw, cy - r + bdy, bw, bh), 2, 2)

        if text:
            # 有徽记的球(大师球)文字下移避开徽记,字号起点也更小
            text_area = QRectF(cx - r, cy - r + (emblem_h + 1 if emblem else 0),
                               2 * r, (13.0 if emblem else r - band_h / 2))
            font = _FONT_CACHE.get((text, bool(emblem)))
            if font is None:
                font = QFont()
                font.setBold(True)
                size = 11 if emblem else 13
                # 顶部半圆的实际可用宽度(球径减去两侧边距),比固定 48px 更宽松
                max_w = max(40.0, 2 * r - 10)
                while size >= 6:  # 最小 6pt,长金额/长数字也能完整放下
                    font.setPixelSize(size)
                    if QFontMetrics(font).horizontalAdvance(text) <= max_w:
                        break
                    size -= 1
                if len(_FONT_CACHE) < 64:
                    _FONT_CACHE[(text, bool(emblem))] = font
            p.setFont(font)
            p.setPen(QColor(0, 0, 0, 90))
            p.drawText(text_area.translated(0, 1), Qt.AlignmentFlag.AlignCenter, text)
            p.setPen(QColor(255, 255, 255))
            p.drawText(text_area, Qt.AlignmentFlag.AlignCenter, text)
        p.restore()

    def make_pokeball_icon(skin_name=None) -> QIcon:
        pm = QPixmap(BALL_SIZE, BALL_SIZE)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        draw_pokeball(painter, QRectF(0, 0, BALL_SIZE, BALL_SIZE),
                      skin=SKINS.get(skin_name or DEFAULT_SKIN))
        painter.end()
        return QIcon(pm)

    # ----------------------------------------------------------------------
    # 悬浮球
    # ----------------------------------------------------------------------
    SPLIT_GAP = 28  # 球左右两半打开时的最大间距(像素)

    class PokeballWidget(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setMouseTracking(True)
            self._text = "—"
            self._gap = 0.0
            self.skin = SKINS[DEFAULT_SKIN]
            self.setFixedSize(BALL_SIZE, BALL_SIZE)

        def _get_gap(self):
            return self._gap

        def _set_gap(self, value: float):
            self._gap = float(value)
            self.setFixedWidth(BALL_SIZE + int(round(self._gap)))
            self.update()

        # QPropertyAnimation 动画值: 左右两半分离的间距(像素)
        gap = Property(float, _get_gap, _set_gap)

        def set_text(self, text: str):
            self._text = text
            self.update()

        def set_skin(self, name: str):
            self.skin = SKINS.get(name, SKINS[DEFAULT_SKIN])
            self.update()

        def enterEvent(self, ev):
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        def leaveEvent(self, ev):
            self.unsetCursor()

        def paintEvent(self, ev):
            p = QPainter(self)
            # repaint() 不会自动清背景: 先整体清空,任何残留像素都不可能存活
            # (X11/Wayland 上切换皮肤后旧皮肤滞留就是这类残留)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(self.rect(), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            if self._gap <= 0:
                # 合拢态: 整球一次画完
                draw_pokeball(p, QRectF(0, 0, BALL_SIZE, BALL_SIZE),
                              self._text, skin=self.skin)
            else:
                # 打开态: 两半裁剪绘制,不画文字 —— 文字位于中缝会被撕成两半,
                # 出现"半截字符挂在两半上"的沙漏状残影;面板已在中间显示数据
                p.save()
                p.setClipRect(QRectF(0, 0, BALL_SIZE / 2, BALL_SIZE))
                draw_pokeball(p, QRectF(0, 0, BALL_SIZE, BALL_SIZE),
                              None, skin=self.skin)
                p.restore()
                p.save()
                p.translate(self._gap, 0)
                p.setClipRect(QRectF(BALL_SIZE / 2, 0, BALL_SIZE / 2, BALL_SIZE))
                draw_pokeball(p, QRectF(0, 0, BALL_SIZE, BALL_SIZE),
                              None, skin=self.skin)
                p.restore()
            p.end()

    class BallWindow(QWidget):
        """单窗口精灵球: 合拢时只有 64px 圆球;打开时同一窗口向下扩展,面板从球下展开。

        面板与球同属一个窗口 —— 无弹出层、无定位请求,Wayland 上天然可靠。
        点击面板区域正常交互;点击球 / 托盘 / Esc 收起。
        """

        clicked = Signal()
        quit_requested = Signal()
        skin_changed = Signal(str)

        PANEL_GAP = 6
        PANEL_WIDTH = 320

        def __init__(self):
            super().__init__(None,
                             Qt.WindowType.FramelessWindowHint
                             | Qt.WindowType.WindowStaysOnTopHint
                             | Qt.WindowType.Tool)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setWindowTitle("TokenMon")
            self._ball = PokeballWidget(self)
            self._panel = None
            self._panel_h = 0
            self._open_progress = 0.0
            self._base_pos = None
            self._skin_name = DEFAULT_SKIN
            # Wayland 顶层窗口不能程序化移动: 居中只能靠球在窗口内下移
            self._wayland = "wayland" in QApplication.platformName().lower()

            self._press_global = None
            self._moved = False

            # 开合动画: 球左右分离 + 窗口向下展开面板,同一个进度属性驱动
            self._anim = QPropertyAnimation(self, b"open_progress", self)
            self._anim.setDuration(260)
            self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._apply_open(0.0)

        # ---- 开合进度(动画属性) ----
        def _get_open_progress(self):
            return self._open_progress

        def _set_open_progress(self, value: float):
            self._open_progress = float(value)
            self._apply_open(self._open_progress)

        open_progress = Property(float, _get_open_progress, _set_open_progress)

        def _apply_open(self, t: float):
            if t <= 0:
                if self._panel is not None:
                    self._panel.hide()
                self._ball.gap = 0
                self._ball.move(0, 0)
                if not self._wayland and self._base_pos is not None:
                    self.move(self._base_pos)
                self.setFixedSize(BALL_SIZE, BALL_SIZE)
                self._update_mask()
                return
            # 目标: 球与面板垂直居中(球心 = 面板中心)
            ph = self._panel_h
            m = self.PANEL_GAP
            shift = max(0.0, ph / 2 + m - BALL_SIZE / 2)  # 球心相对窗口顶的位移
            h_full = int(ph + 2 * m)
            gap = int(round(self.PANEL_WIDTH * t))
            self._ball.gap = gap
            w = BALL_SIZE + gap
            h = int(round(BALL_SIZE + (h_full - BALL_SIZE) * t))
            if not self._wayland and self._base_pos is not None:
                # X11/Windows: 窗口上移 shift,球在窗口内同步下移 → 球在屏幕上保持原位
                self.move(self._base_pos - QPoint(0, int(round(shift * t))))
            self.setFixedSize(w, max(h, BALL_SIZE))
            self._ball.move(0, int(round(shift * t)))
            if self._panel is not None:
                self._panel.setVisible(True)
                self._panel.move(BALL_SIZE // 2, m)
            self._update_mask()

        def set_skin(self, name: str):
            if name not in SKINS:
                return
            self._skin_name = name
            self._ball.set_skin(name)
            self._update_mask()  # 超级球等皮肤有侧凸起,遮罩需扩展
            # 部分平台(X11/Windows)在 setMask 改变窗口形状后不会自动清除
            # 旧遮罩区域外的残留像素 —— 同步重绘,避免切换皮肤后旧皮肤滞留
            self._ball.repaint()
            self.repaint()

        def _ball_shape_region(self, gap: int, ball_y: int) -> QRegion:
            """球两半(半圆)+ 皮肤侧凸起的遮罩区域,与绘制几何严格一致。

            注意: 不能用"内切椭圆"近似半圆 —— 椭圆在接缝处会缩成一点,
            把球中间竖直切掉一条(旧的实现就是这么画的,遮罩错位)。
            半圆必须用 QPainterPath 的弧线构造,gap=0 时两半并成整圆。
            """
            region = QRegion()
            # 多边形栅格化会把弧线内缩 ~1px,弧矩形整体外扩 1px 补偿,
            # 确保遮罩始终不小于实际绘制(多出的透明区无害)。
            inflate = 1.0
            arc_rect = QRectF(-inflate, ball_y - inflate,
                              BALL_SIZE + 2 * inflate, BALL_SIZE + 2 * inflate)
            # 左半: 12 点 → 9 点 → 6 点(逆时针 180°),弦沿 x=32 竖直方向
            left = QPainterPath()
            left.moveTo(BALL_SIZE / 2, ball_y)
            left.arcTo(arc_rect, 90, 180)
            left.closeSubpath()
            region |= QRegion(left.toFillPolygon().toPolygon())
            # 右半: 6 点 → 3 点 → 12 点,整体右移 gap
            right = QPainterPath()
            right.moveTo(BALL_SIZE / 2 + gap, ball_y + BALL_SIZE)
            right.arcTo(arc_rect.translated(gap, 0), -90, 180)
            right.closeSubpath()
            region |= QRegion(right.toFillPolygon().toPolygon())
            # 皮肤元素都在球体轮廓内(超级球侧块/大师球徽记),圆遮罩已覆盖,无需扩展
            return region

        def _update_mask(self):
            gap = int(round(self._ball.gap))
            ball_y = self._ball.y()
            region = self._ball_shape_region(gap, ball_y)
            if self._open_progress > 0 and self._panel is not None:
                py = self._panel.y()
                bottom = self.height() - py
                if bottom > 0:
                    region |= QRegion(QRect(BALL_SIZE // 2, py,
                                            self.width() - BALL_SIZE // 2, bottom))
            self.setMask(region)

        def attach_panel(self, panel):
            self._panel = panel
            self._panel.setParent(self)
            self._panel_h = panel.sizeHint().height()
            self._panel.hide()

        def panel_resized(self):
            if self._panel is None:
                return
            self._panel_h = self._panel.sizeHint().height()
            if self._open_progress > 0:
                self._apply_open(self._open_progress)

        def is_open(self) -> bool:
            return self._open_progress >= 0.5

        def open_panel(self):
            if self._panel is None:
                return
            self._panel_h = self._panel.sizeHint().height()
            self._base_pos = self.pos()  # 记录合拢位置,收起时移回
            self._anim.stop()
            self._anim.setStartValue(self._open_progress)
            self._anim.setEndValue(1.0)
            self._anim.start()

        def close_panel(self):
            self._anim.stop()
            self._anim.setStartValue(self._open_progress)
            self._anim.setEndValue(0.0)
            self._anim.start()

        def keyPressEvent(self, ev):
            if ev.key() == Qt.Key.Key_Escape:
                self.close_panel()
            else:
                super().keyPressEvent(ev)

        def set_text(self, usage: Usage):
            if usage.total is not None:
                self._ball.set_text(_fmt_short(usage.total))
            elif usage.balance is not None:
                self._ball.set_text(_fmt_money_short(usage.balance, usage.currency))
            elif usage.cost is not None:
                self._ball.set_text(_fmt_money_short(usage.cost, usage.currency))
            else:
                self._ball.set_text("—")
            # 不再设置窗口 tooltip: 悬浮提示是独立的第二个表面,盖在球上观感像叠层

        def mousePressEvent(self, ev):
            if ev.button() == Qt.MouseButton.LeftButton:
                self._press_global = ev.globalPosition().toPoint()
                self._moved = False

        def mouseMoveEvent(self, ev):
            if self._press_global is None or self._moved:
                return
            delta = ev.globalPosition().toPoint() - self._press_global
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self._moved = True
                self._press_global = None
                if self.windowHandle() is not None:
                    self.windowHandle().startSystemMove()

        def mouseReleaseEvent(self, ev):
            if ev.button() == Qt.MouseButton.LeftButton:
                if self._press_global is not None and not self._moved:
                    self.clicked.emit()
                self._press_global = None

        def contextMenuEvent(self, ev):
            menu = QMenu(self)
            menu.addAction("显示主界面", lambda: self.clicked.emit())
            _add_skin_actions(menu, self._skin_name, self.skin_changed.emit)
            menu.addSeparator()
            menu.addAction("退出", lambda: self.quit_requested.emit())
            menu.exec(ev.globalPos())

    # ----------------------------------------------------------------------
    # 主界面
    # ----------------------------------------------------------------------
    class ConvRow(QFrame):
        def __init__(self, conv: Conversation):
            super().__init__()
            self.setObjectName("convrow")
            v = QVBoxLayout(self)
            v.setContentsMargins(6, 4, 6, 4)
            v.setSpacing(1)
            top = QHBoxLayout()
            top.setSpacing(8)
            prompt = QLabel(conv.prompt)
            prompt.setProperty("cls", "conv-prompt")
            prompt.setWordWrap(True)
            top.addWidget(prompt, 1)
            tokens = QLabel(_fmt_tokens(conv.tokens))
            tokens.setProperty("cls", "conv-tokens")
            top.addWidget(tokens, 0, Qt.AlignmentFlag.AlignTop)
            v.addLayout(top)
            parts = []
            if conv.requests and conv.requests > 1:
                parts.append(f"{conv.requests} 次请求")
            if conv.last_time:
                parts.append(conv.last_time[:16].replace("T", " "))
            sub = QLabel(" · ".join(parts) if parts else " ")
            sub.setProperty("cls", "conv-sub")
            v.addWidget(sub)

    class MainPanel(QWidget):
        """精灵球对半打开后弹出的菜单内容(由 Controller 嵌进 QMenu 的 QWidgetAction)。"""

        quit_requested = Signal()
        collapsed = Signal()
        size_changed = Signal()
        skin_changed = Signal(str)

        def __init__(self, cfg: dict, has_logs: bool = True):
            super().__init__()
            self._cfg = cfg
            self._interval = cfg["gateway"]["refresh_seconds"]
            self._detail_cache = {}
            self._dot_err = False
            self._convs_visible = False
            self._pending_convs = None  # 面板未展开时暂存的最新对话数据
            self._usage_seen = False  # 是否已收到第一次用量数据
            self._skin_name = DEFAULT_SKIN
            self._build_ui()
            if not has_logs:
                self._btn_convs.hide()  # 网关无日志接口(如 deepseek),不显示对话入口

        def _build_ui(self):
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            panel = QFrame()
            panel.setObjectName("panel")
            outer.addWidget(panel)
            v = QVBoxLayout(panel)
            self._v = v
            v.setContentsMargins(12, 10, 12, 10)
            v.setSpacing(5)

            hdr = QHBoxLayout()
            hdr.setSpacing(6)
            self._dot = QLabel("●")
            self._dot.setProperty("cls", "dot")
            title = QLabel("TokenMon")
            title.setProperty("cls", "caption")
            self._interval_label = QLabel(f"⟳ {self._interval:.0f}s")
            self._interval_label.setProperty("cls", "caption")
            btn_collapse = QPushButton("—")
            btn_collapse.setProperty("cls", "btn")
            btn_collapse.setToolTip("收起(回到精灵球)")
            btn_collapse.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn_collapse.clicked.connect(self.collapsed.emit)
            btn_quit = QPushButton("×")
            btn_quit.setProperty("cls", "btn")
            btn_quit.setToolTip("退出 TokenMon")
            btn_quit.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn_quit.clicked.connect(self.quit_requested.emit)
            hdr.addWidget(self._dot)
            hdr.addWidget(title)
            hdr.addStretch(1)
            hdr.addWidget(self._interval_label)
            hdr.addWidget(btn_collapse)
            hdr.addWidget(btn_quit)
            v.addLayout(hdr)

            # 三个主指标行; 按网关类型预隐藏拿不到的指标
            # (deepseek/openrouter 无 token/缓存统计, litellm 无缓存字段)
            self._row_keys = ["total", "cache", "cost"]
            self._rows = {}
            for key, label in (("total", "Token 用量"),
                               ("cache", "缓存命中"), ("cost", "费用")):
                self._rows[key] = self._add_row(v, label)
            self._hidden_by_config = set()
            gtype = str(self._cfg["gateway"].get("type", "")).lower()
            if gtype in ("deepseek", "openrouter"):
                self._hidden_by_config |= {"total", "cache"}
            elif gtype == "litellm":
                self._hidden_by_config |= {"cache"}
            for key in self._hidden_by_config:
                self._set_row_visible(key, False)
            self._balance_row = None
            self._balance_val = None

            foot = QHBoxLayout()
            foot.setSpacing(8)
            self._btn_details = QPushButton("详情 ▾")
            self._btn_details.setProperty("cls", "btn")
            self._btn_details.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._btn_details.clicked.connect(self._show_details)
            self._btn_convs = QPushButton("对话 ▾")
            self._btn_convs.setProperty("cls", "btn")
            self._btn_convs.setToolTip("最近十次对话的 prompt 与 token 用量")
            self._btn_convs.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._btn_convs.clicked.connect(self._toggle_convs)
            self._btn_skin = QPushButton("皮肤 ▾")
            self._btn_skin.setProperty("cls", "btn")
            self._btn_skin.setToolTip("切换精灵球皮肤(精灵球/大师球/超级球/高级球)")
            self._btn_skin.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._btn_skin.clicked.connect(self._show_skins)
            # 按钮右对齐: 右缘与上方参数行的数值右缘对齐(12+296=308)
            for btn in (self._btn_details, self._btn_convs, self._btn_skin):
                btn.setFixedHeight(22)  # 与参数行同高,行距一致
            self._status = QLabel("启动中…")
            self._status.setProperty("cls", "status")
            self._status.setToolTip("")
            foot.addWidget(self._status)
            foot.addStretch(1)
            foot.addWidget(self._btn_details)
            foot.addWidget(self._btn_convs)
            foot.addWidget(self._btn_skin)
            v.addLayout(foot)

            # 最近对话面板(默认收起)
            self._convs_panel = QFrame()
            cv = QVBoxLayout(self._convs_panel)
            cv.setContentsMargins(0, 2, 0, 0)
            cv.setSpacing(4)
            ch = QHBoxLayout()
            self._convs_header = QLabel("最近对话")
            self._convs_header.setProperty("cls", "conv-header")
            self._convs_status = QLabel("")
            self._convs_status.setProperty("cls", "status")
            ch.addWidget(self._convs_header)
            ch.addStretch(1)
            ch.addWidget(self._convs_status)
            cv.addLayout(ch)
            self._convs_scroll = QScrollArea()
            self._convs_scroll.setObjectName("convs")
            self._convs_scroll.setWidgetResizable(True)
            self._convs_scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._convs_container = QWidget()
            self._convs_container.setStyleSheet("background: transparent;")
            self._convs_layout = QVBoxLayout(self._convs_container)
            self._convs_layout.setContentsMargins(6, 6, 6, 6)
            self._convs_layout.setSpacing(4)
            self._convs_scroll.setWidget(self._convs_container)
            self._convs_scroll.setFixedHeight(200)
            cv.addWidget(self._convs_scroll)
            self._convs_panel.hide()
            v.addWidget(self._convs_panel)

            self.setFixedWidth(320)

        def _add_row(self, parent, label: str):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label)
            lbl.setProperty("cls", "row-label")
            val = QLabel("—")
            val.setProperty("cls", "row-value")
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            h.addWidget(lbl)
            h.addStretch(1)
            h.addWidget(val)
            parent.addWidget(row)
            return row, val

        def _set_row_visible(self, key: str, visible: bool):
            """主指标行按需显隐: 用插删而非 setVisible(隐藏会污染布局最小尺寸)。"""
            row, _val = self._rows[key]
            in_layout = row.parent() is not None
            if visible == in_layout:
                return
            if visible:
                # 插回原相对位置: 前面还有几个可见行就插到第几个(1 = 表头之后)
                pos = 1 + sum(1 for k in self._row_keys[: self._row_keys.index(key)]
                              if self._rows[k][0].parent() is not None)
                self._v.insertWidget(pos, row)
                row.show()
            else:
                self._v.removeWidget(row)
                row.hide()
                row.setParent(None)
            self._v.activate()
            self.adjustSize()
            self.size_changed.emit()

        def _ensure_balance_row(self):
            """余额行按需插入(deepseek 等只有余额的网关); 用插删而非隐藏,避免布局最小尺寸残留。"""
            if self._balance_row is not None:
                return
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel("余额")
            lbl.setProperty("cls", "row-label")
            self._balance_val = QLabel("—")
            self._balance_val.setProperty("cls", "row-value")
            self._balance_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            h.addWidget(lbl)
            h.addStretch(1)
            h.addWidget(self._balance_val)
            # 插在最后一个可见主指标行之后(行可能被隐藏,不能写死索引)
            pos = 1 + sum(1 for k in self._row_keys
                          if self._rows[k][0].parent() is not None)
            self._v.insertWidget(pos, row)
            self._balance_row = row
            self.adjustSize()
            self.size_changed.emit()

        def _remove_balance_row(self):
            if self._balance_row is None:
                return
            row = self._balance_row
            self._v.removeWidget(row)
            row.hide()
            row.setParent(None)  # 立即脱离面板: 待删 widget 仍会污染布局最小尺寸
            row.deleteLater()
            self._balance_row = None
            self._balance_val = None
            self._v.activate()
            self.adjustSize()
            self.size_changed.emit()

        def _show_details(self):
            menu = QMenu(self)
            for key, label, _kind in DETAIL_FIELDS:
                show, text = self._detail_cache.get(key, (False, ""))
                if not show:
                    continue
                w = QWidget()
                h = QHBoxLayout(w)
                h.setContentsMargins(10, 2, 10, 2)
                h.setSpacing(12)
                l1 = QLabel(label)
                l1.setProperty("cls", "detail-label")
                l2 = QLabel(text)
                l2.setProperty("cls", "detail-value")
                l2.setAlignment(Qt.AlignmentFlag.AlignRight)
                h.addWidget(l1)
                h.addStretch(1)
                h.addWidget(l2)
                act = QWidgetAction(menu)
                act.setDefaultWidget(w)
                menu.addAction(act)
            if menu.isEmpty():
                menu.addAction("暂无数据").setEnabled(False)
            menu.exec(self._btn_details.mapToGlobal(
                QPoint(0, self._btn_details.height())))

        def _show_skins(self):
            menu = QMenu(self)
            _add_skin_actions(menu, self._skin_name, self.skin_changed.emit,
                              submenu=False)
            menu.exec(self._btn_skin.mapToGlobal(QPoint(0, self._btn_skin.height())))

        def set_skin_name(self, name: str):
            self._skin_name = name if name in SKINS else DEFAULT_SKIN

        def _toggle_convs(self):
            self._convs_visible = not self._convs_visible
            self._convs_panel.setVisible(self._convs_visible)
            self._btn_convs.setText("对话 ▴" if self._convs_visible else "对话 ▾")
            if self._convs_visible and self._pending_convs is not None:
                self._rebuild_convs(self._pending_convs)
                self._pending_convs = None
            # setVisible 触发的布局重算是延迟的: 先同步重算内层布局,再按 sizeHint 收缩
            self._v.activate()
            self.adjustSize()
            self.size_changed.emit()

        def set_conversations(self, convs):
            if self._convs_visible:
                self._rebuild_convs(convs)
            else:
                # 面板收起时不重建 widget,展开时再用最新数据一次性重建
                self._pending_convs = convs

        def _rebuild_convs(self, convs):
            while self._convs_layout.count():
                item = self._convs_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            if not convs:
                empty = QLabel("无数据")
                empty.setProperty("cls", "status")
                self._convs_layout.addWidget(empty)
            else:
                for c in convs:
                    self._convs_layout.addWidget(ConvRow(c))
            self._convs_layout.addStretch(1)

        def set_logs_status(self, text: str):
            self._convs_status.setText(text)

        def set_status(self, text: str, error: bool = False):
            # 状态在左、按钮在右: 超长时中间省略,完整内容放 tooltip
            self._status.setToolTip(text)
            self._status.setText(QFontMetrics(self._status.font()).elidedText(
                text, Qt.TextElideMode.ElideMiddle, 120))
            if error != self._dot_err:
                self._dot_err = error
                self._dot.setProperty("err", error)
                self._dot.style().unpolish(self._dot)
                self._dot.style().polish(self._dot)

        def update(self, usage: Usage, session_tokens, session_cost, rate):
            self._usage_seen = True
            # 主指标行: 有值就显示/刷新; 收不到值的行隐藏(首次数据到达前保持占位)
            vals = {
                "total": (usage.total, _fmt_tokens),
                "cache": (usage.cache_hit, _fmt_tokens),
                "cost": (usage.cost, lambda v: _fmt_money(v, usage.currency)),
            }
            for key, (row, val) in self._rows.items():
                if key in self._hidden_by_config:
                    continue
                v, fmt = vals[key]
                if v is not None:
                    if row.parent() is None:
                        self._set_row_visible(key, True)
                    val.setText(fmt(v))
                elif row.parent() is not None:
                    self._set_row_visible(key, False)

            if usage.balance is not None:
                self._ensure_balance_row()
                self._balance_val.setText(_fmt_money(usage.balance, usage.currency))
            elif self._balance_row is not None:
                self._remove_balance_row()

            cache = {}
            for key, _label, kind in DETAIL_FIELDS:
                if key == "session_delta":
                    v = session_tokens if usage.total is not None else session_cost
                    show = v > 0
                    text = (_fmt_tokens(v) if usage.total is not None
                            else _fmt_money(v, usage.currency))
                elif key == "rate":
                    show = usage.total is not None
                    text = f"{rate:+.1f} tok/s"
                else:
                    v = getattr(usage, key, None)
                    show = (v is not None and v > 0) if kind == "num_gt0" else v is not None
                    text = _fmt_tokens(v) if show else "—"
                cache[key] = (show, text)
            self._detail_cache = cache
            # 详情下拉无任何可用数据时隐藏按钮(如 deepseek 只有余额);
            # 用 isHidden 判断自身显隐标记,isVisible 会受父窗口隐藏影响
            has_any = any(show for show, _ in cache.values())
            if has_any != (not self._btn_details.isHidden()):
                self._btn_details.setVisible(has_any)
                self.adjustSize()
                self.size_changed.emit()

    # ----------------------------------------------------------------------
    # 托盘 / 线程桥 / 控制器
    # ----------------------------------------------------------------------
    class TrayIcon(QSystemTrayIcon):
        def __init__(self, on_toggle, on_quit, icon=None):
            super().__init__(icon if icon is not None else make_pokeball_icon())
            self.setToolTip("TokenMon · 等待数据…")
            menu = QMenu()
            menu.addAction("显示/隐藏主界面", on_toggle)
            menu.addSeparator()
            menu.addAction("退出", on_quit)
            self.setContextMenu(menu)
            self.activated.connect(self._on_activated)
            self._on_toggle = on_toggle

        def _on_activated(self, reason):
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                self._on_toggle()

    class Bridge(QObject):
        """轮询线程 → 主线程的信号桥(跨线程 emit 自动排队到主线程执行)。"""

        usage_ready = Signal(object)
        usage_error = Signal(str)
        logs_ready = Signal(list)
        logs_error = Signal(str)

    class Controller(QObject):
        def __init__(self, cfg: dict):
            super().__init__()
            self._cfg = cfg
            gw = cfg["gateway"]
            self._interval = gw["refresh_seconds"]
            self._logs_interval = gw["logs_refresh_seconds"]
            self._stop = threading.Event()
            self._prev_total = None
            self._prev_cost = None
            self._session_tokens = 0
            self._session_cost = 0.0
            self._rate = 0.0
            self._last_update = None

            self._bridge = Bridge()
            self._bridge.usage_ready.connect(self.on_usage)
            self._bridge.usage_error.connect(self.on_usage_error)
            self._bridge.logs_ready.connect(self.on_logs)
            self._bridge.logs_error.connect(self.on_logs_error)

            self._ball = BallWindow()
            self._ball.clicked.connect(self.toggle_main)
            self._ball.quit_requested.connect(self.quit)
            self._skin_name = self._load_skin()
            self._ball.set_skin(self._skin_name)
            self._ball.skin_changed.connect(self._on_skin_changed)

            # 面板是球窗口的一部分(attach_panel 后成为子控件):
            # 打开时两半向两侧分离,面板从中间展开 —— 单窗口,无弹出层
            gw0 = cfg["gateway"]
            gtype0 = str(gw0.get("type", "")).lower()
            base0 = str(gw0.get("base_url", ""))
            has_logs = (gtype0 == "litellm"
                        or (gtype0 == "custom" and bool(str(gw0.get("logs_url", "")).strip()))
                        or base0.startswith("mock://"))
            self._panel = MainPanel(cfg, has_logs=has_logs)
            self._ball.attach_panel(self._panel)
            self._panel.quit_requested.connect(self.quit)
            self._panel.collapsed.connect(self._ball.close_panel)
            self._panel.size_changed.connect(self._ball.panel_resized)
            self._panel.skin_changed.connect(self._on_skin_changed)
            self._panel.set_skin_name(self._skin_name)

            self._tray_ok = False
            if QSystemTrayIcon.isSystemTrayAvailable():
                self._tray_ok = True
                self._tray = TrayIcon(self.toggle_main, self.quit,
                                      make_pokeball_icon(self._skin_name))
                self._tray.show()
            notes = []
            if not self._tray_ok:
                notes.append("托盘不可用(需 AppIndicator 扩展)")
            if (bool(cfg["window"].get("always_on_top", True))
                    and "wayland" in QApplication.platformName().lower()):
                notes.append("Wayland 置顶可能无效")
            if notes:
                self._panel.set_status("; ".join(notes) + "(精灵球照常用)")

        # ---- 窗口行为 ----
        def show_ball(self):
            self._ball.show()

        # ---- 皮肤 ----
        @staticmethod
        def _load_skin() -> str:
            try:
                name = (CONFIG_DIR / "skin").read_text(encoding="utf-8").strip()
            except OSError:
                return DEFAULT_SKIN
            return name if name in SKINS else DEFAULT_SKIN

        def _on_skin_changed(self, name: str):
            if name not in SKINS:
                return
            self._skin_name = name
            self._ball.set_skin(name)
            self._panel.set_skin_name(name)
            if self._tray_ok:
                self._tray.setIcon(QIcon())  # 先清空再设置,Windows 托盘图标缓存才会刷新
                self._tray.setIcon(make_pokeball_icon(name))
            try:
                (CONFIG_DIR / "skin").write_text(name + "\n", encoding="utf-8")
            except OSError:
                pass

        def toggle_main(self):
            if self._ball.is_open():
                self._ball.close_panel()
            else:
                self._ball.open_panel()

        def quit(self):
            if self._stop.is_set():
                return
            self._stop.set()
            QApplication.instance().quit()

        # ---- 数据轮询 ----
        # 用量与对话列表各占一个线程: 慢日志接口(如 litellm 分页)不再阻塞用量刷新。
        # 两个循环都是"抓取完成后再等一个间隔",慢请求不会造成连击;
        # 连续失败按指数退避,断网时不会硬锤网关。
        _USAGE_BACKOFF_CAP = 60.0
        _LOGS_BACKOFF_CAP = 300.0

        def start(self):
            self._threads = [
                threading.Thread(target=self._usage_loop,
                                 name="tokenmon-usage", daemon=True),
                threading.Thread(target=self._logs_loop,
                                 name="tokenmon-logs", daemon=True),
            ]
            for t in self._threads:
                t.start()

        def _usage_loop(self):
            failures = 0
            while not self._stop.is_set():
                try:
                    usage = fetch_usage(self._cfg["gateway"])
                    failures = 0
                    self._bridge.usage_ready.emit(usage)
                    delay = self._interval
                except Exception as exc:  # 网络错误/网关报错,不崩溃
                    failures += 1
                    delay = min(self._interval * (2 ** failures),
                                self._USAGE_BACKOFF_CAP)
                    self._bridge.usage_error.emit(str(exc))
                self._stop.wait(delay)

        def _logs_loop(self):
            self._stop.wait(1.0)  # 启动 1 秒后先抓一次对话列表
            failures = 0
            while not self._stop.is_set():
                try:
                    convs = fetch_conversations(self._cfg["gateway"])
                    failures = 0
                    self._bridge.logs_ready.emit(convs)
                    delay = self._logs_interval
                except Exception as exc:
                    failures += 1
                    delay = min(self._logs_interval * (2 ** failures),
                                self._LOGS_BACKOFF_CAP)
                    self._bridge.logs_error.emit(str(exc))
                self._stop.wait(delay)

        @Slot(object)
        def on_usage(self, usage: Usage):
            if self._stop.is_set():  # 应用已退出,丢弃排队中的信号
                return
            now = time.monotonic()
            elapsed = now - self._last_update if self._last_update else None

            # 会话增量 = 两次轮询的累计差值之和; 速率 = 相邻两次轮询的增量/间隔(平滑)
            if usage.total is not None:
                if self._prev_total is not None:
                    delta = usage.total - self._prev_total
                    if delta >= 0:
                        self._session_tokens += delta
                        if elapsed:
                            inst = delta / elapsed
                            self._rate = 0.85 * self._rate + 0.15 * inst
                    else:
                        self._rate = 0.0  # 网关计数回滚/重置: 速率清零,会话从新基准继续累计
                self._prev_total = usage.total
            else:
                self._prev_total = None  # 该轮缺测: 丢弃基准,避免恢复后增量虚高
            if usage.cost is not None:
                if self._prev_cost is not None and usage.cost >= self._prev_cost:
                    self._session_cost += usage.cost - self._prev_cost
                self._prev_cost = usage.cost
            else:
                self._prev_cost = None
            self._last_update = now

            self._ball.set_text(usage)
            self._panel.update(usage, self._session_tokens, self._session_cost, self._rate)
            base = str(self._cfg["gateway"].get("base_url", "")).rstrip("/") or "已连接"
            self._panel.set_status(f"{base} · 更新于 {time.strftime('%H:%M:%S')}")

            if self._tray_ok:
                if usage.total is not None:
                    brief = _fmt_short(usage.total)
                elif usage.balance is not None:
                    brief = _fmt_money_short(usage.balance, usage.currency)
                elif usage.cost is not None:
                    brief = _fmt_money(usage.cost, usage.currency)
                else:
                    brief = "—"
                total_txt = _fmt_tokens(usage.total) if usage.total is not None else "—"
                cache_txt = (_fmt_tokens(usage.cache_hit)
                             if usage.cache_hit is not None else "—")
                self._tray.setToolTip(
                    f"TokenMon · {brief}\n累计 {total_txt} · 缓存 {cache_txt}")

        @Slot(str)
        def on_usage_error(self, msg: str):
            if self._stop.is_set():
                return
            self._panel.set_status(f"错误: {msg[:72]}", error=True)

        @Slot(list)
        def on_logs(self, convs):
            if self._stop.is_set():
                return
            self._panel.set_conversations(convs)
            self._panel.set_logs_status("已更新" if convs else "无数据")

        @Slot(str)
        def on_logs_error(self, msg: str):
            if self._stop.is_set():
                return
            self._panel.set_logs_status("无数据")
            self._panel.set_conversations([])

    # ----------------------------------------------------------------------
    # GUI 入口
    # ----------------------------------------------------------------------
    def run_gui(cfg: dict, smoke: int = 0) -> int:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        app = QApplication(sys.argv)
        app.setApplicationName("TokenMon")
        app.setQuitOnLastWindowClosed(False)  # 关窗只隐藏,托盘/菜单才是真退出
        app.setStyleSheet(APP_STYLESHEET)
        app.setWindowIcon(make_pokeball_icon())

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)  # 锁文件目录必须存在,否则 tryLock 必败
        lock = QLockFile(str(CONFIG_DIR / "tokenmon.lock"))
        lock.setStaleLockTime(0)  # 仅按 PID 判活
        if not lock.tryLock(100):
            _safe_print("TokenMon 已在运行。")
            return 0

        ctrl = Controller(cfg)
        ctrl._lock = lock  # 保持引用,防止锁被回收
        ctrl.start()
        ctrl.show_ball()
        if smoke > 0:
            QTimer.singleShot(smoke * 1000, app.quit)
        return app.exec()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        prog="tokenmon", description="精灵球悬浮窗实时监控 LLM 网关 token 用量(Windows/Linux)"
    )
    parser.add_argument("--config", default=None,
                        help=f"配置文件路径(默认 {CONFIG_PATH})")
    parser.add_argument("--once", action="store_true",
                        help="只抓取一次用量并打印,不启动 GUI(调试配置)")
    parser.add_argument("--logs", action="store_true",
                        help="与 --once 连用: 额外抓取最近对话列表")
    parser.add_argument("--smoke", type=int, default=0, metavar="N",
                        help="启动 GUI,N 秒后自动退出(无显示环境测试)")
    args = parser.parse_args()

    path = Path(args.config) if args.config else CONFIG_PATH
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG, encoding="utf-8")
        if os.name != "nt":
            try:
                os.chmod(path, 0o600)  # 配置含 api_key,收紧权限
            except OSError:
                pass
        _safe_print(f"[tokenmon] 已生成默认配置: {path}\n          请编辑 api_key/base_url 后重新运行。")
        return 1

    try:
        cfg = load_config(path)
    except (tomllib.TOMLDecodeError, OSError, ValueError) as exc:
        _safe_print(f"[tokenmon] 配置错误 {path}: {exc}", file=sys.stderr)
        return 1

    if args.once:
        try:
            usage = fetch_usage(cfg["gateway"])
        except Exception as exc:
            _safe_print(f"[tokenmon] 抓取失败: {exc}", file=sys.stderr)
            _safe_print(f"[tokenmon] 配置文件: {path}", file=sys.stderr)
            gw = cfg["gateway"]
            key_state = "已填" if gw.get("api_key") else "未填"
            _safe_print(f"[tokenmon] 网关: type={gw['type']} base_url={gw.get('base_url')!r} api_key={key_state}",
                        file=sys.stderr)
            base = str(gw.get("base_url", ""))
            if "127.0.0.1:8080" in base:
                _safe_print("[tokenmon] 提示: base_url 看起来还是默认配置,请编辑配置文件指向你的网关,", file=sys.stderr)
                _safe_print('          或先体验演示数据: base_url = "mock://usage"', file=sys.stderr)
            elif "api.deepseek.com" in base:
                _safe_print("[tokenmon] 提示: DeepSeek 官方 API 没有 token 用量统计端点,但支持余额查询 ——", file=sys.stderr)
                _safe_print('          把配置改为 type = "deepseek" 即可显示余额;', file=sys.stderr)
                _safe_print("          要监控 token 用量需指向 LiteLLM proxy 或你自己的统计网关。", file=sys.stderr)
            elif gw.get("type") == "custom":
                _safe_print("[tokenmon] 提示: custom 类型要求 base_url 直接返回用量统计 JSON,", file=sys.stderr)
                _safe_print('          请确认它指向统计端点而不是服务商官网。', file=sys.stderr)
            return 1
        _safe_print(json.dumps(usage.to_dict(), indent=2, ensure_ascii=False))
        gw_out = dict(cfg["gateway"])
        if gw_out.get("api_key"):
            k = gw_out["api_key"]
            gw_out["api_key"] = k[:4] + "…" + k[-4:] if len(k) > 12 else "***"
        _safe_print("配置:", json.dumps(gw_out, ensure_ascii=False))
        if args.logs:
            try:
                convs = fetch_conversations(cfg["gateway"])
            except Exception as exc:
                _safe_print(f"[tokenmon] 最近对话抓取失败: {exc}", file=sys.stderr)
            else:
                _safe_print("最近对话:")
                _safe_print(json.dumps([c.to_dict() for c in convs],
                                       indent=2, ensure_ascii=False))
        return 0

    if not HAVE_QT:
        _safe_print("[tokenmon] 缺少 PySide6:", file=sys.stderr)
        _safe_print(f"           {QT_IMPORT_ERROR}", file=sys.stderr)
        _safe_print("           Windows: pip install pyside6", file=sys.stderr)
        _safe_print("           Fedora:  sudo dnf install python3-pyside6", file=sys.stderr)
        return 1

    return run_gui(cfg, args.smoke)


if __name__ == "__main__":
    sys.exit(main())
