#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TokenMon Lite —— 极致精简版(仅标准库 tkinter + urllib,零第三方依赖)。

球体/皮肤为预渲染图片(assets/,由完整版 Qt 绘制代码一次性生成),
数据抓取复用 tokenmon.py 的纯逻辑层(不依赖 PySide6)。

与完整版(Qt)的差异:
  * Linux: 窗口为深色卡片(无逐像素透明,球体边缘为圆内图案)
  * Windows: 键色透明,球体可真正悬浮于桌面
  * 无开合动画、无系统托盘(退出用右键菜单)

用法:
  python3 tokenmon_lite.py [--config PATH] [--smoke N]
"""
import argparse
import os
import sys
import threading
import time
from pathlib import Path

import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tokenmon as tm  # 仅使用其纯逻辑层(无 PySide6 时 HAVE_QT=False)

BALL = 64
DARK = "#16181d"
PANEL_BG = "#1e222b"
KEY = "#ff00ff"  # Windows 键色(该颜色像素变为全透明)


def is_windows():
    return os.name == "nt"


def asset_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / "assets"
    return Path(__file__).resolve().parent / "assets"


class LiteApp:
    def __init__(self, cfg: dict, smoke: int = 0):
        self.cfg = cfg
        self.gw = cfg["gateway"]
        self.interval = float(cfg["gateway"].get("refresh_seconds", 5))
        self.skin = "pokeball"
        self._stop = threading.Event()
        self._prev_total = None
        self._prev_cost = None
        self._press = None
        self._moved = False

        self.root = tk.Tk()
        self.root.title("TokenMon")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        bg = KEY if is_windows() else DARK
        self.root.configure(bg=bg)
        if is_windows():
            self.root.attributes("-transparentcolor", KEY)
        self.root.geometry(f"{BALL}x{BALL}+300+200")

        self.canvas = tk.Canvas(self.root, width=BALL, height=BALL,
                                bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.ball_img = None
        self._load_ball()

        # 面板(默认收起)
        self.panel = tk.Frame(self.root, bg=DARK)
        self._build_panel()
        self._open = False

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_menu)

        if smoke > 0:
            self.root.after(smoke * 1000, self.quit)
        self.refresh_now()
        threading.Thread(target=self._poll_loop, daemon=True).start()

    # ---- 渲染 ----
    def _load_ball(self):
        kind = "ball" if is_windows() else "card"
        f = asset_dir() / f"{kind}_{self.skin}.png"
        img = tk.PhotoImage(file=str(f))
        self.ball_img = img.subsample(4, 4)  # 256 → 64
        self.canvas.delete("ball")
        self.canvas.create_image(0, 0, image=self.ball_img, anchor="nw",
                                 tags="ball")
        self.canvas.image = self.ball_img  # 防止被 GC

    def _build_panel(self):
        self._vals = {}
        for label, key in (("Token 用量", "total"),
                           ("缓存命中", "cache"), ("费用", "cost")):
            row = tk.Frame(self.panel, bg=DARK)
            row.pack(fill="x", padx=12, pady=(2, 0))
            tk.Label(row, text=label, bg=DARK, fg="#c8cdd4",
                     font=("", 10)).pack(side="left")
            v = tk.Label(row, text="—", bg=DARK, fg="#eef0f3",
                         font=("", 11, "bold"))
            v.pack(side="right")
            self._vals[key] = v
        btns = tk.Frame(self.panel, bg=DARK)
        btns.pack(fill="x", padx=12, pady=(6, 8))
        for text, cmd in (("刷新", self.refresh_now),
                          ("皮肤", self._skin_menu),
                          ("退出", self.quit)):
            tk.Button(btns, text=text, command=cmd, bg=PANEL_BG, fg="#9aa0a6",
                      activebackground="#2a2f3a", activeforeground="#ffffff",
                      relief="flat", bd=0, padx=8, pady=2,
                      font=("", 9)).pack(side="left", padx=(0, 6))

    # ---- 数据 ----
    def _apply_usage(self, usage):
        self._vals["total"].config(
            text=tm._fmt_tokens(usage.total) if usage.total is not None else "—")
        self._vals["cache"].config(
            text=tm._fmt_tokens(usage.cache_hit) if usage.cache_hit is not None else "—")
        self._vals["cost"].config(
            text=tm._fmt_money(usage.cost, usage.currency)
            if usage.cost is not None else "—")

    def refresh_now(self):
        def work():
            try:
                usage = tm.fetch_usage(self.gw)
                self.root.after(0, self._apply_usage, usage)
            except Exception as exc:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _poll_loop(self):
        while not self._stop.wait(self.interval):
            self.refresh_now()

    # ---- 交互 ----
    def _on_press(self, ev):
        self._press = (ev.x_root, ev.y_root)
        self._moved = False

    def _on_drag(self, ev):
        if self._press is None:
            return
        if abs(ev.x_root - self._press[0]) + abs(ev.y_root - self._press[1]) > 4:
            self._moved = True
            x = self.root.winfo_x() + ev.x_root - self._press[0]
            y = self.root.winfo_y() + ev.y_root - self._press[1]
            self.root.geometry(f"+{x}+{y}")
            self._press = (ev.x_root, ev.y_root)

    def _on_release(self, ev):
        if not self._moved:
            self.toggle_panel()
        self._press = None

    def toggle_panel(self):
        self._open = not self._open
        if self._open:
            self.panel.pack(after=self.canvas, fill="x")
            h = BALL + self.panel.winfo_reqheight()
        else:
            self.panel.pack_forget()
            h = BALL
        self.root.geometry(f"{BALL}x{h}+{self.root.winfo_x()}+{self.root.winfo_y()}")

    def _on_menu(self, ev):
        m = tk.Menu(self.root, tearoff=0, bg=PANEL_BG, fg="#eef0f3")
        m.add_command(label="展开/收起", command=self.toggle_panel)
        skins = tk.Menu(m, tearoff=0, bg=PANEL_BG, fg="#eef0f3")
        for name, spec in tm.SKINS.items():
            skins.add_command(
                label=spec["label"],
                command=lambda n=name: self.set_skin(n))
        m.add_cascade(label="皮肤", menu=skins)
        m.add_separator()
        m.add_command(label="退出", command=self.quit)
        try:
            m.tk_popup(ev.x_root, ev.y_root)
        finally:
            m.grab_release()

    def _skin_menu(self):
        m = tk.Menu(self.root, tearoff=0, bg=PANEL_BG, fg="#eef0f3")
        for name, spec in tm.SKINS.items():
            m.add_command(label=spec["label"],
                          command=lambda n=name: self.set_skin(n))
        try:
            m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            m.grab_release()

    def set_skin(self, name):
        if name in tm.SKINS:
            self.skin = name
            self._load_ball()

    def quit(self):
        self._stop.set()
        try:
            self.root.destroy()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(prog="tokenmon-lite")
    parser.add_argument("--config", default=None)
    parser.add_argument("--smoke", type=int, default=0)
    args = parser.parse_args()
    path = Path(args.config) if args.config else tm.CONFIG_PATH
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tm.DEFAULT_CONFIG, encoding="utf-8")
        print(f"[tokenmon-lite] 已生成默认配置: {path}")
        return 1
    try:
        cfg = tm.load_config(path)
    except Exception as exc:
        print(f"[tokenmon-lite] 配置错误: {exc}", file=sys.stderr)
        return 1
    LiteApp(cfg, smoke=args.smoke).root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
