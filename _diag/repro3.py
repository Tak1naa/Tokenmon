import sys, time, os
sys.path.insert(0, "/home/takina/Widgets")
os.environ.setdefault("QT_QPA_PLATFORM", sys.argv[1] if len(sys.argv) > 1 else "xcb")
sys.argv = ["tokenmon"]
import tokenmon as tm
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout

app = QApplication([])
print("platform:", app.platformName())

def make_panel():
    panel = QWidget()
    v = QVBoxLayout(panel)
    v.addWidget(QLabel("Token 用量  2,215,154"))
    v.addWidget(QLabel("费用      ¥0.3755"))
    return panel

def win_grab(w):
    return app.primaryScreen().grabWindow(int(w.winId())).toImage()

def wait(t):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)

w = tm.BallWindow()
w.attach_panel(make_panel())
w.set_skin("great")
w.show(); w.move(80, 80)
wait(0.5)
print("geo:", w.geometry().getRect())
w.open_panel()
wait(0.6)
before = win_grab(w)
w.set_skin("pokeball")
wait(0.4)
after = win_grab(w)
w2 = tm.BallWindow()
w2.attach_panel(make_panel())
w2.set_skin("pokeball")
w2.show(); w2.move(560, 80); w2.open_panel()
wait(0.6)
fresh = win_grab(w2)
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

n1, l1 = diff(before, after)
n2, l2 = diff(after, fresh)
print(f"before/after diff = {n1}px (超球→精灵 应>0)")
print(f"after vs fresh = {n2}px  {'OK' if n2 == 0 else 'LINGER!'} {l2}")
