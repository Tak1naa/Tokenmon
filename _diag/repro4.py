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

def diff(a, b):
    n = 0; locs = []
    h = min(a.height(), b.height()); wd = min(a.width(), b.width())
    for y in range(h):
        for x in range(wd):
            if a.pixelColor(x, y) != b.pixelColor(x, y):
                n += 1
                if len(locs) < 14: locs.append((x, y))
    return n, locs

def scenario(open_state, from_skin, to_skin, close_after=False):
    w = tm.BallWindow()
    w.attach_panel(make_panel())
    w.set_skin(from_skin)
    w.show(); w.move(80, 80)
    wait(0.4)
    if open_state:
        w.open_panel(); wait(0.5)
    w.set_skin(to_skin)
    wait(0.4)
    if close_after:
        w.close_panel(); wait(0.5)
    after = win_grab(w)
    w.close()
    w2 = tm.BallWindow()
    w2.attach_panel(make_panel())
    w2.set_skin(to_skin)
    w2.show(); w2.move(560, 80)
    wait(0.4)
    if open_state:
        w2.open_panel(); wait(0.5)
    if close_after:
        w2.close_panel(); wait(0.5)
    fresh = win_grab(w2)
    w2.close()
    wait(0.2)
    n, locs = diff(after, fresh)
    tag = "OK" if n == 0 else "LINGER!"
    print(f"{'open ' if open_state else 'closed'} {from_skin:>8}->{to_skin:<8} {'+close ' if close_after else '':<7} diff={n}px {tag} {locs[:8]}")
    return n

total = 0
for open_state in (False, True):
    for a, b in [("great", "pokeball"), ("pokeball", "great"), ("master", "great"), ("great", "master"), ("ultra", "heal")]:
        total += scenario(open_state, a, b)
    # 切换后关闭
    for a, b in [("great", "pokeball"), ("pokeball", "great")]:
        total += scenario(True, a, b, close_after=True)
print("TOTAL lingering px:", total)
