#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""TokenMon —— 精灵球悬浮窗,实时监控 LLM 网关 token 用量。

极简版(Tkinter 重构): 仅 Python 标准库(tkinter + urllib),零第三方依赖,
冻结后约 30-40MB。球体/皮肤为预渲染图片(assets/,由 packaging/generate_assets.py
用 Qt 绘制代码一次性生成;运行时不再需要任何 GUI 框架)。

特性:
  * 无边框置顶悬浮球,4 种皮肤,可拖动;靠近屏幕左右边缘自动吸附并旋转 90°
  * 点击展开/收起面板: token/缓存/费用/余额、详情下拉、最近对话、手动刷新
  * 右键菜单: 展开/皮肤/刷新/设置(窗口置顶、编辑配置、打开配置目录、重载配置)/退出
  * Windows: 键色透明,球体可真正悬浮于桌面;Linux: 深色卡片窗
  * 无系统托盘(标准库限制);退出走右键菜单或面板 ×
  * 支持 LiteLLM / OpenRouter / DeepSeek / 自定义 JSON 网关

要求: Python >= 3.11(仅标准库,无 PySide6)
用法:
  python3 tokenmon.py                 # 启动
  python3 tokenmon.py --once          # 只抓取一次并打印(无需图形环境)
  python3 tokenmon.py --once --logs   # 附带最近对话列表
  python3 tokenmon.py --smoke 5       # 启动 5 秒后自动退出(冒烟测试)
  python3 tokenmon.py --config PATH
"""

import argparse
import os
import sys
import threading
import time
from pathlib import Path

import tkinter as tk

from tokenmon_core import *  # noqa: F401,F403 —— 数据层(配置/抓取/格式化)
from tokenmon_core import (  # noqa: F401 —— 兼容旧脚本/测试引用私有名
    _as_number, _as_int, _sum_field, _sum_num, _get_json, _mock_usage,
    _fmt_tokens, _fmt_money, _fmt_short, _fmt_money_short, _rows_from_envelope,
    _first_user_message, _truncate_prompt, _extract_user_prompt,
    _parse_litellm_logs, _parse_custom_conversations, _mock_conversations,
    _open_with_default_app, _FIELD_NAMES, _FIELDS_TOML, _MCP_CALL_TYPES,
    _bootstrap_python, _safe_print,
)

# 皮肤: 名称 → 显示名(图片在 assets/,由 generate_assets.py 生成)
SKINS = {"pokeball": "精灵球", "master": "大师球", "great": "超级球", "ultra": "高级球"}
DEFAULT_SKIN = "pokeball"

BALL = 64            # 球体显示尺寸
PANEL_W = 200        # 面板宽度
DARK = "#16181d"
PANEL_BG = "#1e222b"
TEXT_COLOR = "#eef0f3"
SUB_COLOR = "#8b93a1"
DIM_COLOR = "#6e7681"
GOOD = "#3fb950"
BAD = "#f85149"
KEY = "#ff00ff"      # Windows 键色(该颜色像素变为全透明)
SNAP_TH = 48         # 边缘吸附阈值(px)
SCALE = 4            # 图片渲染倍数(256px → 显示 64px)
ANIM_STEPS = 12      # 开合动画帧数
ANIM_MS = 16         # 每帧间隔

DETAIL_FIELDS = [
    ("prompt", "Prompt"),
    ("completion", "Completion"),
    ("reasoning", "Reasoning"),
    ("cache_miss", "Cache Miss"),
    ("session_cache_hit", "Session Hit"),
    ("session_cache_miss", "Session Miss"),
    ("session_delta", "本会话增量"),
    ("rate", "实时速率"),
]


def _is_windows():
    return os.name == "nt"


def _asset_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / "assets"
    return Path(__file__).resolve().parent / "assets"


def _img_path(name: str) -> Path:
    return _asset_dir() / f"{name}.png"


class TokenMonApp:
    def __init__(self, cfg: dict, config_path=None, smoke: int = 0):
        self.cfg = cfg
        self.gw = cfg["gateway"]
        self.config_path = Path(config_path) if config_path else CONFIG_PATH
        self.interval = float(cfg["gateway"].get("refresh_seconds", 5))
        self.logs_interval = float(cfg["gateway"].get("logs_refresh_seconds", 60))
        self.skin = DEFAULT_SKIN
        self.docked = None          # None / "left" / "right"(吸附边缘)
        self._open = False          # 面板展开
        self._anim_job = None
        self._stop = threading.Event()
        self._prev_total = None
        self._prev_cost = None
        self._session_tokens = 0
        self._session_cost = 0.0
        self._rate = 0.0
        self._last_update = None
        self._always_on_top = bool(cfg["window"].get("always_on_top", True))
        self._usage = None
        self._convs = []
        self._convs_visible = False
        self._detail_cache = {}
        self._press = None
        self._moved = False

        gtype = str(self.gw.get("type", "")).lower()
        self._hidden = set()
        if gtype in ("deepseek", "openrouter"):
            self._hidden |= {"total", "cache"}
        elif gtype == "litellm":
            self._hidden |= {"cache"}
        base = str(self.gw.get("base_url", ""))
        self.has_logs = (gtype == "litellm"
                         or (gtype == "custom"
                             and bool(str(self.gw.get("logs_url", "")).strip()))
                         or base.startswith("mock://"))

        self.root = tk.Tk()
        self.root.title("TokenMon")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self._always_on_top)
        bg = KEY if _is_windows() else DARK
        self.root.configure(bg=bg)
        if _is_windows():
            self.root.attributes("-transparentcolor", KEY)
        self.root.geometry(f"{BALL}x{BALL}+300+200")
        self._base_pos = (300, 200)

        self.canvas = tk.Canvas(self.root, bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack()
        self._imgs = {}
        self._load_assets()
        self.panel = tk.Frame(self.canvas, bg=DARK)
        self._build_panel()
        self._draw_closed()

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_menu)
        self.root.bind("<Escape>", lambda e: self.close_panel() if self._open else None)

        if smoke > 0:
            self.root.after(smoke * 1000, self.quit)
        self.refresh_now()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        threading.Thread(target=self._logs_loop, daemon=True).start()

    # ---------------- 图片资源 ----------------
    def _load_assets(self):
        kinds = ("ball", "ball_r", "ball_l", "half_top", "half_bot",
                 "halfL_r", "halfR_r", "halfL_l", "halfR_l")
        for skin in SKINS:
            for kind in kinds:
                p = _img_path(f"{kind}_{skin}")
                if not p.exists():
                    continue
                img = tk.PhotoImage(file=str(p))
                if kind in ("half_top", "half_bot"):
                    img = img.subsample(SCALE, SCALE)
                elif kind in ("halfL_r", "halfR_r", "halfL_l", "halfR_l"):
                    img = img.subsample(SCALE, SCALE)
                else:
                    img = img.subsample(SCALE, SCALE)
                self._imgs[f"{kind}_{skin}"] = img

    def _img(self, kind: str) -> tk.PhotoImage:
        return self._imgs[f"{kind}_{self.skin}"]

    def set_skin(self, name: str):
        if name in SKINS:
            self.skin = name
            if self._open:
                self._draw_open(self._open_progress())
            else:
                self._draw_closed()

    # ---------------- 布局绘制 ----------------
    def _draw_closed(self):
        self.canvas.configure(width=BALL, height=BALL)
        self.canvas.delete("all")
        kind = "ball_r" if self.docked == "right" else ("ball_l" if self.docked == "left" else "ball")
        self.canvas.create_image(0, 0, image=self._img(kind), anchor="nw", tags="ball")
        self._set_geometry(BALL, BALL)

    def _open_progress(self):
        return 1.0 if self._open else 0.0

    def _draw_open(self, p: float):
        """展开态: 普通 = 球上下分离、面板居中; 吸附 = 左右分离。"""
        self.canvas.delete("all")
        if self.docked:
            w = BALL + PANEL_W
            h = max(BALL, BALL + int((self.panel_h() - BALL) * p))
            by = (h - BALL) // 2
            self.canvas.configure(width=w, height=h)
            if self.docked == "right":
                lk, rk = "halfL_r", "halfR_r"
            else:
                lk, rk = "halfR_l", "halfL_l"
            gap = int((PANEL_W) * p)
            self.canvas.create_image(0, by, image=self._img(lk), anchor="nw", tags="h1")
            self.canvas.create_image(BALL + gap, by, image=self._img(rk), anchor="nw", tags="h2")
            self.canvas.create_window(BALL, 0, window=self.panel,
                                      anchor="nw", width=PANEL_W, height=h, tags="panel")
            x = self._base_pos[0] + BALL - w if self.docked == "right" else self._base_pos[0]
            y = self._base_pos[1] - (h - BALL) // 2
            self._set_geometry(w, h, x=x, y=y)
        else:
            w = PANEL_W
            h = BALL + int(self.panel_h() * p)
            gap = int((self.panel_h()) * p)
            cx = (PANEL_W - BALL) // 2
            self.canvas.configure(width=w, height=h)
            self.canvas.create_image(cx, 0, image=self._img("half_top"), anchor="nw", tags="h1")
            self.canvas.create_image(cx, BALL // 2 + gap, image=self._img("half_bot"),
                                     anchor="nw", tags="h2")
            self.canvas.create_window(0, BALL // 2, window=self.panel,
                                      anchor="nw", width=PANEL_W, height=int(self.panel_h() * p),
                                      tags="panel")
            x = self._base_pos[0] - (PANEL_W - BALL) // 2
            self._set_geometry(w, h, x=x, y=self._base_pos[1])

    def panel_h(self) -> int:
        return max(1, self.panel.winfo_reqheight() + 4)

    def _set_geometry(self, w, h, x=None, y=None):
        if x is None:
            x = self.root.winfo_x()
        if y is None:
            y = self.root.winfo_y()
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ---------------- 开合动画 ----------------
    def _animate_to(self, target_open: bool):
        if self._anim_job:
            self.root.after_cancel(self._anim_job)
        steps = ANIM_STEPS
        start = 1.0 if self._open else 0.0
        end = 1.0 if target_open else 0.0

        def frame(i):
            if self._stop.is_set():
                return
            p = start + (end - start) * (i / steps)
            self._draw_open(p)
            if i < steps:
                self._anim_job = self.root.after(ANIM_MS, frame, i + 1)
            else:
                self._anim_job = None
                self._open = target_open
                if not target_open:
                    self._draw_closed()
        frame(1)

    def open_panel(self):
        if self._open:
            return
        self._open = True
        self._animate_to(True)

    def close_panel(self):
        if not self._open:
            return
        self._animate_to(False)

    def toggle_panel(self):
        if self._open:
            self.close_panel()
        else:
            self.open_panel()

    # ---------------- 交互 ----------------
    def _on_press(self, ev):
        self._press = (ev.x_root, ev.y_root)
        self._moved = False

    def _on_drag(self, ev):
        if self._press is None:
            return
        dx = ev.x_root - self._press[0]
        dy = ev.y_root - self._press[1]
        if abs(dx) + abs(dy) > 4:
            self._moved = True
            if self.docked:
                self.docked = None  # 拖动即解除吸附
            self._set_geometry(self.root.winfo_width(), self.root.winfo_height(),
                               x=self.root.winfo_x() + dx,
                               y=self.root.winfo_y() + dy)
            self._press = (ev.x_root, ev.y_root)
            if not self._open:
                self._draw_closed()

    def _on_release(self, ev):
        if not self._moved:
            self.toggle_panel()
        else:
            self._maybe_snap()
        self._press = None

    def _maybe_snap(self):
        if self._open:
            return
        x = self.root.winfo_x()
        sw = self.root.winfo_screenwidth()
        if abs(x) <= SNAP_TH:
            dock, tx = "left", 0
        elif abs(sw - BALL - x) <= SNAP_TH:
            dock, tx = "right", sw - BALL
        else:
            dock, tx = None, None
        self.docked = dock
        if dock is not None:
            self._set_geometry(BALL, BALL, x=tx, y=self.root.winfo_y())
        self._draw_closed()

    def _on_menu(self, ev):
        m = tk.Menu(self.root, tearoff=0, bg=PANEL_BG, fg=TEXT_COLOR,
                    activebackground="#2a2f3a", activeforeground="#ffffff")
        m.add_command(label="收起" if self._open else "展开面板",
                      command=self.toggle_panel)
        m.add_command(label="刷新", command=self.refresh_now)
        skins = tk.Menu(m, tearoff=0, bg=PANEL_BG, fg=TEXT_COLOR,
                        activebackground="#2a2f3a")
        for name, label in SKINS.items():
            skins.add_command(label=label, command=lambda n=name: self.set_skin(n))
        m.add_cascade(label="皮肤", menu=skins)
        m.add_cascade(label="设置", menu=self._build_settings_menu(m))
        m.add_separator()
        m.add_command(label="退出", command=self.quit)
        try:
            m.tk_popup(ev.x_root, ev.y_root)
        finally:
            m.grab_release()

    # ---------------- 面板 ----------------
    def _build_panel(self):
        self.panel.config(bg=DARK)
        for wgt in self.panel.winfo_children():
            wgt.destroy()
        # 标题行: ● TokenMon [⟳] [×]
        title = tk.Frame(self.panel, bg=DARK)
        title.pack(fill="x", padx=10, pady=(6, 0))
        self._dot = tk.Label(title, text="●", bg=DARK, fg=GOOD, font=("", 10))
        self._dot.pack(side="left")
        tk.Label(title, text="TokenMon", bg=DARK, fg="#c8cdd4",
                 font=("", 10, "bold")).pack(side="left", padx=(4, 0))
        tk.Button(title, text="⟳", command=self.refresh_now, bg=DARK, fg="#9aa0a6",
                  relief="flat", bd=0, activebackground=DARK,
                  activeforeground="#ffffff", font=("", 10),
                  cursor="hand2").pack(side="right")
        tk.Button(title, text="×", command=self.quit, bg=DARK, fg="#9aa0a6",
                  relief="flat", bd=0, activebackground=DARK,
                  activeforeground="#ffffff", font=("", 10),
                  cursor="hand2").pack(side="right")
        # 统计行
        self._rows = {}
        for key, label in (("total", "Token 用量"), ("cache", "缓存命中"),
                           ("cost", "费用"), ("balance", "余额")):
            row = tk.Frame(self.panel, bg=DARK)
            self._rows[key] = (row, tk.Label(row, bg=DARK, fg=TEXT_COLOR,
                                             font=("", 11, "bold")))
            tk.Label(row, text=label, bg=DARK, fg="#c8cdd4",
                     font=("", 10)).pack(side="left")
            self._rows[key][1].pack(side="right")
        self._sync_rows()
        # 按钮行
        btns = tk.Frame(self.panel, bg=DARK)
        btns.pack(fill="x", padx=10, pady=(4, 2))
        for text, cmd in (("详情", self._show_details), ("对话", self._toggle_convs),
                          ("皮肤", self._skin_menu), ("设置", self._settings_menu)):
            tk.Button(btns, text=text, command=cmd, bg=PANEL_BG, fg="#9aa0a6",
                      relief="flat", bd=0, padx=7, pady=2, font=("", 9),
                      activebackground="#2a2f3a", activeforeground="#ffffff",
                      cursor="hand2").pack(side="left", padx=(0, 4))
        # 状态行
        self._status = tk.Label(self.panel, text="启动中…", bg=DARK, fg=DIM_COLOR,
                                font=("", 8), anchor="w")
        self._status.pack(fill="x", padx=10, pady=(0, 4))
        # 最近对话区
        self._convs_frame = tk.Frame(self.panel, bg=DARK)
        self._convs_header = tk.Label(self._convs_frame, text="最近对话", bg=DARK,
                                      fg="#e3350d", font=("", 9, "bold"), anchor="w")
        self._convs_header.pack(fill="x", padx=2, pady=(2, 0))
        self._convs_box = tk.Frame(self._convs_frame, bg=PANEL_BG)
        self._convs_box.pack(fill="both", expand=True, padx=2, pady=2)
        self._convs_status = tk.Label(self._convs_frame, text="", bg=DARK,
                                      fg=DIM_COLOR, font=("", 8))
        self._convs_status.pack(fill="x", padx=2)

    def _sync_rows(self):
        for key, (row, val) in self._rows.items():
            if key == "balance":
                row.pack_forget()
            elif key in self._hidden:
                row.pack_forget()
            else:
                row.pack(fill="x", padx=12, pady=(3, 0))

    def _set_balance_row(self, show: bool):
        row = self._rows["balance"][0]
        if show:
            row.pack(fill="x", padx=12, pady=(3, 0))
        else:
            row.pack_forget()

    # ---------------- 数据更新 ----------------
    def _apply_usage(self, usage):
        self._usage = usage
        now = time.monotonic()
        elapsed = now - self._last_update if self._last_update else None
        if usage.total is not None:
            if self._prev_total is not None:
                delta = usage.total - self._prev_total
                if delta >= 0:
                    self._session_tokens += delta
                    if elapsed:
                        self._rate = 0.85 * self._rate + 0.15 * (delta / elapsed)
                else:
                    self._rate = 0.0
            self._prev_total = usage.total
        else:
            self._prev_total = None
        if usage.cost is not None:
            if self._prev_cost is not None and usage.cost >= self._prev_cost:
                self._session_cost += usage.cost - self._prev_cost
            self._prev_cost = usage.cost
        else:
            self._prev_cost = None
        self._last_update = now

        vals = {
            "total": (usage.total, _fmt_tokens),
            "cache": (usage.cache_hit, _fmt_tokens),
            "cost": (usage.cost, lambda v: _fmt_money(v, usage.currency)),
            "balance": (usage.balance, lambda v: _fmt_money(v, usage.currency)),
        }
        for key, (row, val) in self._rows.items():
            if key in self._hidden:
                continue
            v, fmt = vals[key]
            if v is not None:
                row.pack(fill="x", padx=12, pady=(3, 0)) if not row.winfo_ismapped() else None
                val.config(text=fmt(v))
            elif key == "balance":
                self._set_balance_row(False)
            elif row.winfo_ismapped():
                row.pack_forget()
        if usage.balance is not None:
            self._set_balance_row(True)
            self._rows["balance"][1].config(
                text=_fmt_money(usage.balance, usage.currency))

        # 详情缓存
        cache = {}
        for key, label in DETAIL_FIELDS:
            if key == "session_delta":
                v = self._session_tokens if usage.total is not None else self._session_cost
                show = v > 0
                text = (_fmt_tokens(v) if usage.total is not None
                        else _fmt_money(v, usage.currency))
            elif key == "rate":
                show = usage.total is not None
                text = f"{self._rate:+.1f} tok/s"
            else:
                v = getattr(usage, key, None)
                show = v is not None
                text = _fmt_tokens(v) if show else "—"
            cache[key] = (show, label, text)
        self._detail_cache = cache

        base = str(self.gw.get("base_url", "")).rstrip("/") or "已连接"
        self.set_status(f"{base} · 更新于 {time.strftime('%H:%M:%S')}")

    def _apply_convs(self, convs):
        self._convs = convs
        for wgt in self._convs_box.winfo_children():
            wgt.destroy()
        if not convs:
            tk.Label(self._convs_box, text="无数据", bg=PANEL_BG, fg=DIM_COLOR,
                     font=("", 8)).pack(anchor="w", padx=6, pady=4)
        else:
            for c in convs:
                line = tk.Frame(self._convs_box, bg=PANEL_BG)
                line.pack(fill="x", padx=6, pady=1)
                tk.Label(line, text=c.prompt, bg=PANEL_BG, fg=TEXT_COLOR,
                         font=("", 8), anchor="w", justify="left",
                         wraplength=170).pack(side="left", fill="x", expand=True)
                tk.Label(line, text=_fmt_tokens(c.tokens), bg=PANEL_BG,
                         fg=GOOD, font=("", 8, "bold")).pack(side="right")
            self._convs_status.config(text=f"共 {len(convs)} 条")
        self._convs_status.config(text=f"共 {len(convs)} 条" if convs else "无数据")

    def set_status(self, text: str, error: bool = False):
        self._status.config(text=text[:60])
        self._dot.config(fg=BAD if error else GOOD)

    def refresh_now(self):
        def work():
            try:
                usage = fetch_usage(self.gw)
                self.root.after(0, self._apply_usage, usage)
            except Exception as exc:
                self.root.after(0, self.set_status, f"错误: {str(exc)[:50]}", True)
        threading.Thread(target=work, daemon=True).start()

    def _poll_loop(self):
        while not self._stop.wait(self.interval):
            self.refresh_now()

    def _logs_loop(self):
        if not self.has_logs:
            return
        self._stop.wait(1.0)
        while not self._stop.is_set():
            try:
                convs = fetch_conversations(self.gw)
                self.root.after(0, self._apply_convs, convs)
            except Exception:
                pass
            self._stop.wait(self.logs_interval)

    # ---------------- 菜单 ----------------
    def _show_details(self):
        m = tk.Menu(self.root, tearoff=0, bg=PANEL_BG, fg=TEXT_COLOR,
                    activebackground="#2a2f3a")
        any_show = False
        for key, label, text in self._detail_cache.values():
            if not key:
                continue
            show = self._detail_cache[key][0]
            if show:
                any_show = True
                row = tk.Frame(m, bg=PANEL_BG)
                tk.Label(row, text=label, bg=PANEL_BG, fg=SUB_COLOR,
                         font=("", 9)).pack(side="left", padx=8)
                tk.Label(row, text=text, bg=PANEL_BG, fg=TEXT_COLOR,
                         font=("", 9)).pack(side="right", padx=8)
                m.add_cascade(label="", menu=None)  # 占位,实际用 add_command?
        # 简化: 用 add_command 逐行
        m.delete(0, "end")
        if not any_show:
            m.add_command(label="暂无数据", state="disabled")
        else:
            for key, label, text in self._detail_cache.values():
                if self._detail_cache[key][0]:
                    m.add_command(label=f"{label}   {text}")
        self._popup_menu(m)

    def _toggle_convs(self):
        if self._convs_visible:
            self._convs_frame.pack_forget()
            self._convs_visible = False
        else:
            self._convs_frame.pack(fill="x", padx=8, pady=(0, 4))
            self._convs_visible = True
        self._resize_for_panel()

    def _skin_menu(self):
        m = tk.Menu(self.root, tearoff=0, bg=PANEL_BG, fg=TEXT_COLOR,
                    activebackground="#2a2f3a")
        for name, label in SKINS.items():
            m.add_command(label=label, command=lambda n=name: self.set_skin(n))
        self._popup_menu(m)

    def _build_settings_menu(self, parent=None):
        m = tk.Menu(parent or self.root, tearoff=0, bg=PANEL_BG, fg=TEXT_COLOR,
                    activebackground="#2a2f3a")
        m.add_checkbutton(label="窗口置顶", variable=tk.BooleanVar(value=self._always_on_top),
                          command=self._toggle_topmost)
        m.add_separator()
        m.add_command(label="编辑配置…", command=self._edit_config)
        m.add_command(label="打开配置目录", command=self._open_config_dir)
        m.add_separator()
        m.add_command(label="重载配置", command=self._reload_config)
        return m

    def _settings_menu(self):
        self._popup_menu(self._build_settings_menu())

    def _toggle_topmost(self):
        self._always_on_top = not self._always_on_top
        self.root.attributes("-topmost", self._always_on_top)
        self.set_status("窗口置顶已开启" if self._always_on_top else "窗口置顶已关闭")

    def _edit_config(self):
        err = _open_with_default_app(self.config_path)
        self.set_status(f"打开编辑器失败: {err}" if err else "已打开编辑器,保存后点「重载配置」生效",
                        error=bool(err))

    def _open_config_dir(self):
        err = _open_with_default_app(self.config_path.parent)
        if err:
            self.set_status(f"打开目录失败: {err}", error=True)

    def _reload_config(self):
        try:
            cfg = load_config(self.config_path)
        except Exception as exc:
            self.set_status(f"重载失败: {exc}", error=True)
            return
        self.cfg = cfg
        self.gw = cfg["gateway"]
        self.interval = float(cfg["gateway"].get("refresh_seconds", 5))
        self.logs_interval = float(cfg["gateway"].get("logs_refresh_seconds", 60))
        gtype = str(self.gw.get("type", "")).lower()
        self._hidden = set()
        if gtype in ("deepseek", "openrouter"):
            self._hidden |= {"total", "cache"}
        elif gtype == "litellm":
            self._hidden |= {"cache"}
        base = str(self.gw.get("base_url", ""))
        self.has_logs = (gtype == "litellm"
                         or (gtype == "custom"
                             and bool(str(self.gw.get("logs_url", "")).strip()))
                         or base.startswith("mock://"))
        self._build_panel()
        self._resize_for_panel()
        self.set_status("配置已重载")

    def _resize_for_panel(self):
        if self._open:
            self._draw_open(1.0)

    def _popup_menu(self, m):
        try:
            m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            m.grab_release()

    # ---------------- 退出 ----------------
    def quit(self):
        self._stop.set()
        try:
            self.root.destroy()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(prog="tokenmon")
    parser.add_argument("--config", default=None,
                        help=f"配置文件路径(默认 {CONFIG_PATH})")
    parser.add_argument("--once", action="store_true",
                        help="只抓取一次用量并打印,不启动 GUI")
    parser.add_argument("--logs", action="store_true",
                        help="与 --once 连用: 附带最近对话列表")
    parser.add_argument("--smoke", type=int, default=0, metavar="N",
                        help="启动 GUI,N 秒后自动退出(冒烟测试)")
    args = parser.parse_args()

    path = Path(args.config) if args.config else CONFIG_PATH
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG, encoding="utf-8")
        if os.name != "nt":
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        _safe_print("[tokenmon] 已生成默认配置: " + str(path) + "\n          请编辑 api_key/base_url 后重新运行。")
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
            return 1
        _safe_print(json.dumps(usage.to_dict(), indent=2, ensure_ascii=False))
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

    app = TokenMonApp(cfg, config_path=path, smoke=args.smoke)
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
