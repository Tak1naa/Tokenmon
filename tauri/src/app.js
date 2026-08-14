// TokenMon 前端主逻辑: 窗口几何 / 开合动画 / 拖动吸附 / 菜单 / 轮询。
// 后端命令见 src-tauri/src/lib.rs; 纯逻辑见 core.js。

import {
  SKINS, DEFAULT_SKIN, BALL, PANEL_W, SNAP_TH, ANIM_STEPS, ANIM_MS,
  fmtTokens, fmtMoney, fmtShort, fmtMoneyShort,
  hiddenRows, hasLogs, SessionStats, buildDetailCache, nowTime,
} from "./core.js";

const { invoke } = window.__TAURI__.core;
const { getCurrentWindow, LogicalPosition, LogicalSize, PhysicalSize } =
  window.__TAURI__.window;
const { listen } = window.__TAURI__.event;

const appWindow = getCurrentWindow();
const $ = (id) => document.getElementById(id);

const state = {
  gw: null,
  platform: "x11", // windows / x11 / wayland
  configPath: "",
  skin: DEFAULT_SKIN,
  open: false,
  docked: null,          // null | 'left' | 'right'
  animTimer: null,
  alwaysOnTop: true,
  usage: null,
  convs: [],
  convsVisible: false,
  hidden: new Set(),
  logsOn: false,
  stats: new SessionStats(),
  detailCache: {},
  panelH: 180,
  basePos: { x: 300, y: 200 },  // 球左上角的屏幕坐标(物理)
  press: null,           // {sx, sy, wx, wy, w, h}
  moved: false,
};

// ---------------------------------------------------------------------------
// 窗口几何
// ---------------------------------------------------------------------------

function stageBox(w, h) {
  const s = $("stage");
  s.style.width = w + "px";
  s.style.height = h + "px";
}

// 逻辑坐标辅助: X11 下窗口系统按逻辑尺寸应用, 读取的物理值需除以 scaleFactor
async function sf() {
  return appWindow.scaleFactor();
}

async function setWindow(w, h, x, y) {
  await appWindow.setSize(new LogicalSize(Math.round(w), Math.round(h)));
  if (x !== undefined && y !== undefined) {
    await appWindow.setPosition(new LogicalPosition(Math.round(x), Math.round(y)));
  }
}

// Linux 失效模式修复(参考 cc-switch linux_fix.rs):
// GTK surface 与 WebView 的 input region 协商失败时, 窗口整体不响应点击。
// ±1px 伪 resize 触发 size_allocate -> 重新 attach input surface。
async function nudgeInput() {
  if (state.platform !== "wayland" && state.platform !== "x11") return;
  const s = await appWindow.outerSize();
  if (s.width === 0 || s.height === 0) return;
  await appWindow.setSize(new PhysicalSize(s.width + 1, s.height));
  await new Promise((r) => setTimeout(r, 100));
  await appWindow.setSize(new PhysicalSize(s.width, s.height));
}

function halfStyle(topT, botT) {
  document.querySelector(".c-top").style.transform = topT;
  document.querySelector(".c-bot").style.transform = botT;
}

function measurePanel() {
  const p = $("panel");
  p.style.display = "block";
  const h = p.scrollHeight;
  if (!state.open) p.style.display = "none";
  return h + 4;
}

// 展开时球在窗口内的偏移(物理=逻辑, 缩放 1 时一致)
function ballOffset() {
  if (state.docked) return { x: 0, y: 0 };
  return { x: (PANEL_W - BALL) / 2, y: 0 };
}

function windowPosFromBase(base, w, h) {
  const off = ballOffset();
  let x = base.x - off.x;
  let y = base.y - off.y;
  if (state.docked === "right") x = base.x + BALL - w;
  if (state.docked === "left") x = base.x;
  if (state.docked) y = base.y - Math.round((h - BALL) / 2);
  return { x, y };
}

function basePosFromWindow(wx, wy, w, h) {
  const off = ballOffset();
  let x = wx + off.x;
  let y = wy + off.y;
  if (state.docked === "right") x = wx + w - BALL;
  if (state.docked) y = wy + Math.round((h - BALL) / 2);
  return { x, y };
}

async function drawClosed() {
  state.open = false;
  $("panel").style.display = "none";
  const st = $("stage");
  st.className = state.docked ? "docked-" + state.docked : "";
  const bw = $("ballwrap");
  bw.style.left = "0px";
  bw.style.top = "0px";
  halfStyle("translateY(0px)", "translateY(0px)"); // 容器自带 top 定位
  stageBox(BALL, BALL);
  const pos = windowPosFromBase(state.basePos, BALL, BALL);
  await setWindow(BALL, BALL, pos.x, pos.y);
}

async function drawOpen(p) {
  const panelH = state.panelH;
  const gap = Math.round(panelH * p);
  if (state.docked) {
    const w = BALL + PANEL_W;
    const h = Math.max(BALL, BALL + Math.round((panelH - BALL) * p));
    const by = Math.round((h - BALL) / 2);
    stageBox(w, h);
    const bw = $("ballwrap");
    bw.style.left = "0px";
    bw.style.top = by + "px";
    const panel = $("panel");
    panel.style.left = BALL + "px";
    panel.style.top = "0px";
    panel.style.width = PANEL_W + "px";
    panel.style.height = h + "px";
    panel.style.display = p > 0 ? "block" : "none";
    if (state.docked === "right") halfStyle("translateY(0px)", "translateY(" + gap + "px)");
    else halfStyle("translateY(-" + gap + "px)", "translateY(0px)");
    const pos = windowPosFromBase(state.basePos, w, h);
    await setWindow(w, h, pos.x, pos.y);
  } else {
    const w = PANEL_W;
    const h = BALL + Math.round(panelH * p);
    const cx = (PANEL_W - BALL) / 2;
    stageBox(w, h);
    const bw = $("ballwrap");
    bw.style.left = cx + "px";
    bw.style.top = "0px";
    const panel = $("panel");
    panel.style.left = "0px";
    panel.style.top = BALL / 2 + "px";
    panel.style.width = PANEL_W + "px";
    panel.style.height = Math.round(panelH * p) + "px";
    panel.style.display = p > 0 ? "block" : "none";
    halfStyle("translateY(0px)", "translateY(" + gap + "px)"); // 下半容器从 top:32 下移
    const pos = windowPosFromBase(state.basePos, w, h);
    await setWindow(w, h, pos.x, pos.y);
  }
  // 注意: 动画期间不读回 outerPosition 更新 basePos —— X11 下 outerPosition
  // 含 CSD 装饰偏移, 每帧读回会导致窗口逐帧漂移(球向上跳)。
  // 位置同步移到 animateTo 完成后进行一次。
}

// ---------------------------------------------------------------------------
// 开合动画
// ---------------------------------------------------------------------------

function animateTo(target) {
  if (state.animTimer) {
    clearTimeout(state.animTimer);
    state.animTimer = null;
  }
  const steps = ANIM_STEPS;
  const start = state.open ? 1 : 0;
  const end = target ? 1 : 0;
  let i = 1;
  const frame = async () => {
    const p = start + (end - start) * (i / steps);
    await drawOpen(p);
    if (i < steps) {
      i += 1;
      state.animTimer = setTimeout(frame, ANIM_MS);
    } else {
      state.animTimer = null;
      state.open = target;
      if (!target) await drawClosed();
      else state.panelH = measurePanel();
      nudgeInput(); // 尺寸变化后重新激活输入(Linux input region 失效)
      // 动画结束后读一次实际位置同步 basePos
      const f = await sf();
      const pos = await appWindow.outerPosition();
      const size = await appWindow.outerSize();
      state.basePos = basePosFromWindow(
        pos.x / f, pos.y / f,
        size.width / f, size.height / f,
      );
    }
  };
  frame();
}

function openPanel() {
  if (state.open) return;
  state.panelH = measurePanel();
  state.open = true;
  animateTo(true);
}

function closePanel() {
  if (!state.open) return;
  animateTo(false);
}

function togglePanel() {
  if (state.open) closePanel();
  else openPanel();
}

// ---------------------------------------------------------------------------
// 拖动 / 吸附
// ---------------------------------------------------------------------------

async function onPointerDown(e) {
  if (e.button !== 0) return;
  // 面板按钮/标题按钮/菜单区域不参与拖动与开合判定
  if (e.target.closest("button") || e.target.closest("#menu")) return;
  try { e.currentTarget.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
  const pos = await appWindow.outerPosition();
  const size = await appWindow.outerSize();
  const f = await sf();
  state.press = { sx: e.screenX, sy: e.screenY, wx: pos.x / f, wy: pos.y / f, w: size.width / f, h: size.height / f };
  state.moved = false;
}

async function onPointerMove(e) {
  if (!state.press) return;
  const dx = e.screenX - state.press.sx;
  const dy = e.screenY - state.press.sy;
  if (Math.abs(dx) + Math.abs(dy) > 4) {
    state.moved = true;
    if (state.docked) {
      state.docked = null; // 拖动即解除吸附
      $("stage").className = "";
    }
    if (state.platform === "wayland") {
      // Wayland 无程序化移动 API, 交给系统拖动(XDG 协议)
      try {
        await appWindow.startDragging();
      } catch (err) {
        /* 忽略: 部分合成器不支持 */
      }
      return;
    }
    const nx = state.press.wx + dx;
    const ny = state.press.wy + dy;
    await setWindow(state.press.w, state.press.h, nx, ny);
    state.basePos = basePosFromWindow(nx, ny, state.press.w, state.press.h);
  }
}

async function onPointerUp() {
  if (!state.press) return;
  if (!state.moved) {
    togglePanel();
  } else {
    await maybeSnap();
  }
  state.press = null;
}

async function maybeSnap() {
  if (state.open) return;
  if (state.platform === "wayland") return; // Wayland 无法程序化移动窗口
  const mon = await appWindow.currentMonitor();
  if (!mon) return;
  const wa = mon.workArea;
  const pos = await appWindow.outerPosition();
  const f = await sf();
  const x = pos.x / f;
  let dock = null;
  let tx = null;
  if (Math.abs(x - wa.x / f) <= SNAP_TH) {
    dock = "left";
    tx = wa.x / f;
  } else if (Math.abs((wa.x + wa.width) / f - BALL - x) <= SNAP_TH) {
    dock = "right";
    tx = (wa.x + wa.width) / f - BALL;
  }
  state.docked = dock;
  if (dock !== null) {
    await setWindow(BALL, BALL, tx, pos.y);
    state.basePos = { x: tx, y: pos.y };
  }
  await drawClosed();
}

// ---------------------------------------------------------------------------
// 数据更新
// ---------------------------------------------------------------------------

// ---------------- 球身文字 ----------------

function ballTextValue() {
  if (!state.usage) return "";
  const gtype = String(state.gw ? state.gw.type : "").toLowerCase();
  if (gtype === "deepseek" || gtype === "openrouter") {
    return fmtMoneyShort(state.usage.cost, state.usage.currency);
  }
  return fmtShort(state.usage.total);
}

function updateBallText() {
  const el = $("ball-text");
  const t = ballTextValue();
  el.textContent = t;
  // 字号自适应: 球 32px 显示尺寸, 上半球可用宽度 ~30px
  let size = 11;
  el.style.fontSize = size + "px";
  while (size > 5 && el.scrollWidth > 30) {
    size -= 1;
    el.style.fontSize = size + "px";
  }
}

function setStatus(text, error = false) {
  $("status").textContent = String(text).slice(0, 60);
  $("dot").style.color = error ? "#f85149" : "#3fb950";
}

function applyUsage(u) {
  state.usage = u;
  state.stats.apply(u);
  const rows = {
    total: [u.total, fmtTokens],
    cache: [u.cache_hit, fmtTokens],
    cost: [u.cost, (v) => fmtMoney(v, u.currency)],
    balance: [u.balance, (v) => fmtMoney(v, u.currency)],
  };
  for (const [key, [v, fmt]] of Object.entries(rows)) {
    const row = document.querySelector('.row[data-key="' + key + '"]');
    const noVal = v === null || v === undefined;
    if (state.hidden.has(key) || (key === "balance" && noVal)) {
      row.style.display = "none";
      continue;
    }
    row.style.display = "flex";
    $("v-" + key).textContent = noVal ? "—" : fmt(v);
  }
  state.detailCache = buildDetailCache(u, state.stats);
  updateBallText();
  const base = String(state.gw.base_url || "").replace(/\/+$/, "") || "已连接";
  setStatus(base + " · 更新于 " + nowTime());
}

function applyConvs(convs) {
  state.convs = convs;
  const box = $("convs-box");
  box.innerHTML = "";
  const status = $("convs-status");
  if (!convs.length) {
    const d = document.createElement("div");
    d.className = "conv-line";
    d.innerHTML = '<span class="cp" style="color:#6e7681">无数据</span>';
    box.appendChild(d);
    status.textContent = "无数据";
    return;
  }
  for (const c of convs) {
    const line = document.createElement("div");
    line.className = "conv-line";
    const p = document.createElement("span");
    p.className = "cp";
    p.textContent = c.prompt;
    const t = document.createElement("span");
    t.className = "ct";
    t.textContent = fmtTokens(c.tokens);
    line.appendChild(p);
    line.appendChild(t);
    box.appendChild(line);
  }
  status.textContent = "共 " + convs.length + " 条";
}

async function refreshNow() {
  try {
    const u = await invoke("fetch_usage");
    applyUsage(u);
  } catch (e) {
    setStatus("错误: " + String((e && e.message) || e).slice(0, 60), true);
  }
}

async function fetchConvs() {
  if (!state.logsOn) return;
  try {
    const convs = await invoke("fetch_conversations");
    applyConvs(convs);
  } catch (e) {
    /* 对话列表失败静默降级 */
  }
}

// ---------------------------------------------------------------------------
// 皮肤 / 设置
// ---------------------------------------------------------------------------

function setSkin(name) {
  if (!SKINS[name]) return;
  state.skin = name;
  $("half-top").src = "skins/ball_" + name + ".svg";
  $("half-bot").src = "skins/ball_" + name + ".svg";
  if (state.open) drawOpen(1);
  else drawClosed();
}

async function toggleTopmost() {
  state.alwaysOnTop = !state.alwaysOnTop;
  try {
    await invoke("set_always_on_top", { on: state.alwaysOnTop });
  } catch (e) {
    setStatus("置顶切换失败", true);
    return;
  }
  setStatus(state.alwaysOnTop ? "窗口置顶已开启" : "窗口置顶已关闭");
}

async function editConfig() {
  try {
    const p = await invoke("edit_config");
    setStatus("已打开编辑器, 保存后点「重载配置」生效 (" + p + ")");
  } catch (e) {
    setStatus("打开编辑器失败", true);
  }
}

async function openConfigDir() {
  try {
    await invoke("open_config_dir");
  } catch (e) {
    setStatus("打开目录失败", true);
  }
}

async function reloadConfig() {
  const payload = await invoke("reload_config");
  applyConfig(payload);
  if (payload.error) setStatus(payload.error, true);
  else setStatus("配置已重载");
  refreshNow();
}

// ---------------------------------------------------------------------------
// 菜单
// ---------------------------------------------------------------------------

let menuPos = { x: 0, y: 0 };
let menuRestore = null; // {w, h} 菜单扩展窗口前的尺寸

function showMenu(x, y, items) {
  const m = $("menu");
  m.innerHTML = "";
  for (const it of items) {
    if (it.sep) {
      const d = document.createElement("div");
      d.className = "msep";
      m.appendChild(d);
      continue;
    }
    const d = document.createElement("div");
    d.className = "mi" + (it.disabled ? " disabled" : "");
    const lab = document.createElement("span");
    lab.textContent = it.label;
    d.appendChild(lab);
    if (it.checked) {
      const t = document.createElement("span");
      t.className = "tick";
      t.textContent = "✓";
      d.appendChild(t);
    }
    d.addEventListener("click", () => {
      if (it.disabled) return;
      hideMenu();
      it.run();
    });
    m.appendChild(d);
  }
  menuPos = { x, y };
  m.hidden = false;
  const mw = m.offsetWidth;
  const mh = m.offsetHeight;
  appWindow.innerSize().then(async (size) => {
    // clientX/Y 是逻辑(CSS)像素, 窗口尺寸换算成逻辑再比较
    const sf = await appWindow.scaleFactor();
    const lw = size.width / sf;
    const lh = size.height / sf;
    const nw = Math.max(lw, x + mw + 6);
    const nh = Math.max(lh, y + mh + 6);
    if (nw > lw || nh > lh) {
      menuRestore = { w: lw, h: lh };
      await appWindow.setSize(new LogicalSize(nw, nh));
    }
    m.style.left = x + "px";
    m.style.top = y + "px";
  });
}

async function hideMenu() {
  $("menu").hidden = true;
  if (menuRestore) {
    await appWindow.setSize(new LogicalSize(menuRestore.w, menuRestore.h));
    menuRestore = null;
  }
}

// 各菜单的内容
function contextItems() {
  return [
    { label: state.open ? "收起面板" : "展开面板", run: togglePanel },
    { label: "刷新", run: refreshNow },
    { label: "皮肤", run: () => showMenu(menuPos.x, menuPos.y, skinItems()) },
    { label: "设置", run: () => showMenu(menuPos.x, menuPos.y, settingsItems()) },
    { sep: true },
    { label: "退出", run: () => invoke("quit") },
  ];
}

function detailsItems() {
  const items = [];
  for (const [key, entry] of Object.entries(state.detailCache)) {
    if (entry.show) {
      items.push({ label: entry.label + "    " + entry.text, disabled: true });
    }
  }
  if (!items.length) items.push({ label: "暂无数据", disabled: true });
  return items;
}

function skinItems() {
  return Object.entries(SKINS).map(([name, label]) => ({
    label,
    checked: state.skin === name,
    run: () => setSkin(name),
  }));
}

function settingsItems() {
  return [
    { label: "窗口置顶", checked: state.alwaysOnTop, run: toggleTopmost },
    { sep: true },
    { label: "编辑配置…", run: editConfig },
    { label: "打开配置目录", run: openConfigDir },
    { sep: true },
    { label: "重载配置", run: reloadConfig },
  ];
}

// ---------------------------------------------------------------------------
// 托盘事件
// ---------------------------------------------------------------------------

async function handleTray(event) {
  switch (event) {
    case "tm-toggle":
      if (state.open) closePanel();
      else openPanel();
      break;
    case "tm-refresh":
      refreshNow();
      break;
    case "tm-skin-pokeball": setSkin("pokeball"); break;
    case "tm-skin-master": setSkin("master"); break;
    case "tm-skin-great": setSkin("great"); break;
    case "tm-skin-ultra": setSkin("ultra"); break;
    case "tm-topmost": toggleTopmost(); break;
    case "tm-edit-config": editConfig(); break;
    case "tm-open-config-dir": openConfigDir(); break;
    case "tm-reload-config": reloadConfig(); break;
    default: break;
  }
}

// ---------------------------------------------------------------------------
// 初始化
// ---------------------------------------------------------------------------

function applyConfig(payload) {
  state.gw = payload.gateway;
  state.alwaysOnTop = payload.window.always_on_top;
  state.configPath = payload.config_path;
  state.hidden = hiddenRows(String(state.gw.type || ""));
  state.logsOn = hasLogs(state.gw);
  const refreshSec = Number(state.gw.refresh_seconds || 5);
  const logsSec = Number(state.gw.logs_refresh_seconds || 60);
  clearInterval(window.__tmPoll);
  clearInterval(window.__tmLogs);
  window.__tmPoll = setInterval(refreshNow, refreshSec * 1000);
  if (state.logsOn) {
    setTimeout(fetchConvs, 1000);
    window.__tmLogs = setInterval(fetchConvs, logsSec * 1000);
  }
  if (payload.error) setStatus(payload.error, true);
}

async function init() {
  // 事件绑定
  const stage = $("stage");
  stage.addEventListener("pointerdown", onPointerDown);
  stage.addEventListener("pointermove", onPointerMove);
  stage.addEventListener("pointerup", onPointerUp);
  stage.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    showMenu(e.clientX, e.clientY, contextItems());
  });
  document.addEventListener("click", (e) => {
    // 排除按钮: 按钮点击先 showMenu, 同一 click 冒泡到这里不能立刻关掉刚开的菜单
    if (!$("menu").hidden && !$("menu").contains(e.target) && !e.target.closest("button") && e.target !== stage) {
      hideMenu();
    }
  });
  document.addEventListener("contextmenu", (e) => {
    if (!$("menu").hidden) e.preventDefault();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.open) closePanel();
  });
  $("btn-refresh").addEventListener("click", refreshNow);
  $("btn-close").addEventListener("click", () => invoke("hide_ball"));
  for (const btn of document.querySelectorAll("#btns button")) {
    btn.addEventListener("click", () => {
      const act = btn.dataset.act;
      const pos = btn.getBoundingClientRect();
      if (act === "details") showMenu(pos.left, pos.bottom + 4, detailsItems());
      else if (act === "convs") toggleConvs();
      else if (act === "skin") showMenu(pos.left, pos.bottom + 4, skinItems());
      else if (act === "settings") showMenu(pos.left, pos.bottom + 4, settingsItems());
    });
  }

  for (const ev of [
    "tm-toggle", "tm-refresh",
    "tm-skin-pokeball", "tm-skin-master", "tm-skin-great", "tm-skin-ultra",
    "tm-topmost", "tm-edit-config", "tm-open-config-dir", "tm-reload-config",
  ]) {
    listen(ev, () => handleTray(ev));
  }

  // 配置与初始绘制
  const payload = await invoke("get_config");
  state.platform = await invoke("get_platform");
  applyConfig(payload);
  const pos = await appWindow.outerPosition();
  const f = await sf();
  state.basePos = { x: pos.x / f, y: pos.y / f };
  await drawClosed();
  updateBallText();
  nudgeInput(); // 首次显示后重新激活输入
  refreshNow();
}

function toggleConvs() {
  state.convsVisible = !state.convsVisible;
  $("convs").hidden = !state.convsVisible;
  if (state.open) {
    state.panelH = measurePanel();
    drawOpen(1);
  }
}

init();
