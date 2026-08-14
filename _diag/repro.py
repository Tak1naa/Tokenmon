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

w = tm.BallWindow()
w.attach_panel(make_panel())
w.set_skin("great")
w.show()
w.move(120, 120)

def wait(t):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)

wait(0.3)
w.open_panel()
wait(0.5)
print("opened, size:", w.width(), "x", w.height())
w.set_skin("pokeball")
wait(0.3)
img_after = w.grab().toImage()
w2 = tm.BallWindow()
w2.attach_panel(make_panel())
w2.set_skin("pokeball")
w2.show(); w2.move(320, 120); w2.open_panel()
wait(0.5)
img_fresh = w2.grab().toImage()
w.close(); w2.close()

n = 0; locs = []
h = min(img_after.height(), img_fresh.height()); wd = min(img_after.width(), img_fresh.width())
for y in range(h):
    for x in range(wd):
        if img_after.pixelColor(x, y) != img_fresh.pixelColor(x, y):
            n += 1
            if len(locs) < 12: locs.append((x, y))
print(f"great->pokeball open: diff vs fresh = {n}px")
print("sample locs:", locs)
