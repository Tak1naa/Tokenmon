import sys, time, os
sys.path.insert(0, "/home/takina/Widgets")
os.environ.setdefault("QT_QPA_PLATFORM", sys.argv[1] if len(sys.argv) > 1 else "xcb")
sys.argv = ["tokenmon"]
import tokenmon as tm
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
from PySide6.QtGui import QScreen

app = QApplication([])
print("platform:", app.platformName())

def make_panel():
    panel = QWidget()
    v = QVBoxLayout(panel)
    v.addWidget(QLabel("Token 用量  2,215,154"))
    v.addWidget(QLabel("费用      ¥0.3755"))
    return panel

def screen_grab(w):
    g = w.geometry()
    scr = app.primaryScreen()
    return scr.grabWindow(0, g.x(), g.y(), g.width(), g.height()).toImage()

def wait(t):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)

w = tm.BallWindow()
w.attach_panel(make_panel())
w.set_skin("great")
w.show()
w.move(80, 80)
wait(0.4)
w.open_panel()
wait(0.6)
before = screen_grab(w)          # 切换前(超级球)
w.set_skin("pokeball")           # 切换
wait(0.5)
after = screen_grab(w)           # 切换后(应全是精灵球)
w2 = tm.BallWindow()
w2.attach_panel(make_panel())
w2.set_skin("pokeball")
w2.show(); w2.move(560, 80); w2.open_panel()
wait(0.6)
fresh = screen_grab(w2)          # 参照: 全新精灵球
w.close(); w2.close()
wait(0.2)

def diff(a, b):
    n = 0; locs = []
    h = min(a.height(), b.height()); wd = min(a.width(), b.width())
    for y in range(h):
        for x in range(wd):
            if a.pixelColor(x, y) != b.pixelColor(x, y):
                n += 1
                if len(locs) < 14: locs.append((x, y))
    return n, locs

n1, l1 = diff(before, after)   # 切换前后屏幕差异(应有: 顶部颜色变化)
n2, l2 = diff(after, fresh)    # 切换后 vs 全新参照(0 = 无滞留)
print(f"switch before/after diff = {n1}px")
print(f"after vs fresh diff = {n2}px  {'OK' if n2 == 0 else 'LINGER!'}")
if n2: print("locs:", l2)
