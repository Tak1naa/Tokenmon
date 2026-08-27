// TokenMon 前端主逻辑: 窗口几何 / 开合动画 / 拖动吸附 / 菜单 / 轮询。
// 后端命令见 src-tauri/src/lib.rs; 纯逻辑见 core.js。

import {
  SKINS, DEFAULT_SKIN, BALL, PANEL_W, SNAP_TH, ANIM_STEPS, ANIM_MS,
  fmtTokens, fmtMoney, fmtShort, fmtMoneyShort,
  hiddenRows, SessionStats, buildDetailCache, nowTime,
  COMPANIONS, PET_STATES, pickCompanion, resolvePetState, petMessage,
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
  pendingToggle: false, // 动画期间的排队切换(快速连点)
  alwaysOnTop: true,
  usage: null,
  hidden: new Set(),
  logsOn: false,
  stats: new SessionStats(),
  detailCache: {},
  companion: COMPANIONS[0],
  companionLocked: false,
  petState: PET_STATES.BOOT,
  lastActivityAt: null,
  panelH: 180,
  basePos: { x: 300, y: 200 },  // 球左上角的屏幕坐标(物理)
  press: null,           // {sx, sy, wx, wy, w, h}
  moved: false,
};

const PET_MODE_TEXT = {
  [PET_STATES.BOOT]: "等待连接",
  [PET_STATES.IDLE]: "安静陪伴",
  [PET_STATES.REFRESH]: "专注巡查",
  [PET_STATES.ACTIVE]: "发现新用量",
  [PET_STATES.ERROR]: "需要帮助",
  [PET_STATES.REST]: "短暂休息",
};

const PET_EMOTE = {
  [PET_STATES.BOOT]: "…",
  [PET_STATES.IDLE]: "♥",
  [PET_STATES.REFRESH]: "⌁",
  [PET_STATES.ACTIVE]: "✦",
  [PET_STATES.ERROR]: "!",
  [PET_STATES.REST]: "z",
};

// ---------------------------------------------------------------------------
// 窗口几何
// ---------------------------------------------------------------------------

function stageBox(w, h) {
  const s = $("stage");
  s.style.width = w + "px";
  s.style.height = h + "px";
}

function syncStageClasses() {
  const classes = [];
  if (state.docked) classes.push("docked-" + state.docked);
  classes.push(state.open ? "pet-open" : "pet-idle");
  $("stage").className = classes.join(" ");
}

function persistPetPreferences() {
  localStorage.setItem("tokenmon.companion", state.companion.id);
  localStorage.setItem("tokenmon.companionLocked", String(state.companionLocked));
  localStorage.setItem("tokenmon.skin", state.skin);
}

function loadPetPreferences() {
  const id = localStorage.getItem("tokenmon.companion");
  const selected = COMPANIONS.find((item) => item.id === id);
  if (selected) state.companion = selected;
  state.companionLocked = localStorage.getItem("tokenmon.companionLocked") === "true";
  const skin = localStorage.getItem("tokenmon.skin");
  if (skin && SKINS[skin]) state.skin = skin;
}

function updateCompanionUI() {
  const companion = state.companion;
  $("companion-art").src = "companions/" + companion.id + ".svg";
  $("companion-art").alt = companion.name;
  $("pet-name").textContent = companion.name + " · " + companion.element + "系伙伴";
  $("pet-message").textContent = petMessage(companion, state.petState, state.usage);
  $("pet-mode").textContent = PET_MODE_TEXT[state.petState];
  $("pet-emote").textContent = PET_EMOTE[state.petState];
  $("pet-hero").dataset.state = state.petState;
}

function setPetState(next) {
  state.petState = next;
  updateCompanionUI();
}

function chooseCompanion(id = null) {
  const next = id
    ? COMPANIONS.find((item) => item.id === id) || state.companion
    : pickCompanion(COMPANIONS, state.companion?.id, state.companionLocked);
  if (!next) return;
  state.companion = next;
  persistPetPreferences();
  updateCompanionUI();
}

// 逻辑坐标辅助: X11 下窗口系统按逻辑尺寸应用, 读取的物理值需除以 scaleFactor
async function sf() {
  return appWindow.scaleFactor();
}

async function setWindow(w, h, x, y, moveWindow = false) {
  // 每帧等待 resize 完成再进入下一帧: 合成器会合并连续 resize,
  // fire-and-forget 会导致动画只剩首尾两帧(看起来没有动画)
  await appWindow.setSize(new LogicalSize(Math.round(w), Math.round(h)));
  // 开合期间保持单窗口左上角不动。Wayland/XWayland 对重定位语义不
  // 一致；球的居中位移改由内容动画承担。拖动和吸附仍明确请求移动。
  if (moveWindow && x !== undefined && y !== undefined) {
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
  const panel = $("panel");
  panel.style.display = "none";
  panel.classList.remove("genie-prep", "genie-expanded", "genie-closing");
  syncStageClasses();
  const bw = $("ballwrap");
  bw.style.left = "0px";
  bw.style.top = "0px";
  halfStyle("translateY(0px)", "translateY(0px)"); // 容器自带 top 定位
  stageBox(BALL, BALL);
  const pos = windowPosFromBase(state.basePos, BALL, BALL);
  await setWindow(BALL, BALL, pos.x, pos.y);
}

async function drawOpen(p, applyMotion = true, keepBallAtOrigin = false) {
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
    panel.style.height = applyMotion ? h + "px" : panel.style.height;
    panel.style.display = p > 0 ? "block" : "none";
    if (applyMotion) {
      if (state.docked === "right") halfStyle("translateY(0px)", "translateY(" + gap + "px)");
      else halfStyle("translateY(-" + gap + "px)", "translateY(0px)");
    }
    const pos = windowPosFromBase(state.basePos, w, h);
    await setWindow(w, h, pos.x, pos.y);
  } else {
    const w = PANEL_W;
    const h = BALL + Math.round(panelH * p);
    const cx = keepBallAtOrigin ? 0 : ballOffset().x;
    stageBox(w, h);
    const bw = $("ballwrap");
    bw.style.left = cx + "px";
    bw.style.top = "0px";
    const panel = $("panel");
    panel.style.left = "0px";
    panel.style.top = BALL / 2 + "px";
    panel.style.width = PANEL_W + "px";
    panel.style.height = applyMotion ? Math.round(panelH * p) + "px" : panel.style.height;
    panel.style.display = p > 0 ? "block" : "none";
    if (applyMotion) {
      halfStyle("translateY(0px)", "translateY(" + gap + "px)"); // 下半容器从 top:32 下移
    }
    const pos = windowPosFromBase(state.basePos, w, h);
    try {
      await setWindow(w, h, pos.x, pos.y);
      const s = await appWindow.outerSize();
      invoke("tm_report", { rect: "RESIZE w=" + s.width + " h=" + s.height });
    } catch (err) {
      invoke("tm_report", { rect: "RESIZE-ERR " + String(err) });
    }
  }
  // 注意: 动画期间不读回 outerPosition 更新 basePos —— X11 下 outerPosition
  // 含 CSD 装饰偏移, 每帧读回会导致窗口逐帧漂移(球向上跳)。
  // 位置同步由 open/close 流程结束时统一进行。
}

// ---------------------------------------------------------------------------
// 开合动画
// ---------------------------------------------------------------------------

// 开合动画: GTK/Linux 合成器会合并连续窗口 resize(逐帧 resize 只剩首尾帧),
// 因此改为「窗口一次到位 + 内容 CSS transition 平滑过渡」:
// 展开时窗口立即变为最终尺寸(球心保持不动), 球体分离与面板展开由
// CSS transition(0.28s easeOut)驱动, 平滑且不会被合成器吞掉。
const OPEN_MS = 420;
const OPEN_EASE = "cubic-bezier(0.16, 1, 0.3, 1)";

function setHalfTransition(on) {
  const t = on ? ("transform " + OPEN_MS + "ms " + OPEN_EASE) : "none";
  document.querySelector(".c-top").style.transition = t;
  document.querySelector(".c-bot").style.transition = t;
}

function setBallPositionTransition(on) {
  $("ballwrap").style.transition = on
    ? ("left " + OPEN_MS + "ms " + OPEN_EASE)
    : "none";
}

function setPanelTransition(on) {
  const t = on
    ? ("height " + OPEN_MS + "ms " + OPEN_EASE +
       ", transform " + OPEN_MS + "ms " + OPEN_EASE +
       ", opacity " + Math.round(OPEN_MS * .7) + "ms ease-out" +
       ", border-radius " + OPEN_MS + "ms " + OPEN_EASE +
       ", filter " + Math.round(OPEN_MS * .55) + "ms ease-out")
    : "none";
  $("panel").style.transition = t;
}

async function syncBasePos() {
  const f = await sf();
  const pos = await appWindow.outerPosition();
  const size = await appWindow.outerSize();
  state.basePos = basePosFromWindow(
    pos.x / f, pos.y / f,
    size.width / f, size.height / f,
  );
}

function finishAnim() {
  invoke("tm_report", { rect: "ANIM-FINISH pending=" + state.pendingToggle });
  state.animTimer = null;
  setHalfTransition(false);
  setPanelTransition(false);
  setBallPositionTransition(false);
  nudgeInput(); // 尺寸变化后重新激活输入(Linux input region 失效)
  // 开合期间窗口会变尺寸；部分 Wayland 合成器会把透明窗口的
  // outerPosition 暂时报为 (0, 0)。锚点只在拖动/吸附时更新，不能在
  // 动画结束后用这个不可靠的回读值覆盖，否则收起会跳到左上角。
  // 动画期间被吞的切换操作(快速连点)在动画完成后执行
  if (state.pendingToggle) {
    state.pendingToggle = false;
    togglePanel();
  }
}

function openPanel() {
  if (state.open || state.animTimer) return;
  invoke("tm_report", { rect: "ANIM-OPEN" });
  if (!state.companionLocked) chooseCompanion();
  state.panelH = measurePanel();
  state.open = true;
  syncStageClasses();
  // 1) DOM 起始态: 半片合拢, 面板 0 高
  halfStyle("translateY(0px)", "translateY(0px)");
  const panel = $("panel");
  panel.classList.remove("genie-closing", "genie-expanded");
  panel.classList.add("genie-prep");
  panel.style.height = "0px";
  panel.style.display = "block";
  // 2) 窗口一次到位(球心不动), 布局到展开态(不动半片/面板, 由过渡接管)
  //    无论窗口 resize 是否完成, 都触发过渡(resize 失败只影响窗口尺寸,
  //    不影响开合状态机)
  // 放大窗口时先让球留在原处；下一帧再与面板一起滑到居中位置。
  drawOpen(1, false, true)
    .catch(() => {})
    .then(() => {
      setHalfTransition(true);
      setPanelTransition(true);
      setBallPositionTransition(true);
      requestAnimationFrame(() => {
        const gap = state.docked ? PANEL_W : state.panelH;
        if (state.docked === "left") halfStyle("translateY(-" + gap + "px)", "translateY(0px)");
        else halfStyle("translateY(0px)", "translateY(" + gap + "px)");
        panel.classList.remove("genie-prep");
        panel.classList.add("genie-expanded");
        if (!state.docked) $("ballwrap").style.left = ballOffset().x + "px";
        panel.style.height = state.panelH + "px";
      });
    });
  state.animTimer = setTimeout(finishAnim, OPEN_MS + 80);
}

function closePanel() {
  if (!state.open || state.animTimer) return;
  invoke("tm_report", { rect: "ANIM-CLOSE" });
  // 1) CSS 过渡收拢: 下半球归位 + 面板收起
  setHalfTransition(true);
  setPanelTransition(true);
  setBallPositionTransition(true);
  const panel = $("panel");
  requestAnimationFrame(() => {
    halfStyle("translateY(0px)", "translateY(0px)");
    if (!state.docked) $("ballwrap").style.left = "0px";
    panel.classList.remove("genie-expanded");
    panel.classList.add("genie-closing");
    panel.style.height = "0px";
  });
  // 2) 过渡结束后窗口回到 64x64(容错: 即使 resize 失败也释放状态机)
  state.animTimer = setTimeout(() => {
    state.open = false;
    if (state.pendingToggle) {
      // 快速连点反向: 窗口保持展开尺寸直接反向动画, 避免 64->400
      // 紧邻 resize 被 GTK 合并吞掉(那会导致"打不开")
      state.pendingToggle = false;
      state.animTimer = null;
      openPanel();
      return;
    }
    drawClosed()
      .catch(() => {})
      .then(finishAnim);
  }, OPEN_MS + 80);
}

function togglePanel() {
  if (state.animTimer) {
    // 动画进行中: 排队取反, 动画完成后执行(避免点击被吞)
    invoke("tm_report", { rect: "ANIM-PENDING" });
    state.pendingToggle = true;
    return;
  }
  invoke("tm_report", { rect: "ANIM-TOGGLE open=" + state.open });
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
      syncStageClasses();
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
    await setWindow(state.press.w, state.press.h, nx, ny, true);
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
    await setWindow(BALL, BALL, tx, pos.y, true);
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
    return fmtMoneyShort(state.usage.balance, state.usage.currency);
  }
  return fmtShort(state.usage.total);
}

function updateBallText() {
  const el = $("ball-text");
  const t = ballTextValue();
  el.textContent = t;
  // 字号自适应: 球内尽量大(上半球可用宽度 ~54px)
  let size = 22;
  el.style.fontSize = size + "px";
  while (size > 8 && el.scrollWidth > 54) {
    size -= 1;
    el.style.fontSize = size + "px";
  }
}

function setStatus(text, error = false) {
  $("status").textContent = String(text).slice(0, 60);
  $("dot").style.color = error ? "#f85149" : "#3fb950";
}

function applyUsage(u) {
  const previousUsage = state.usage;
  state.usage = u;
  state.stats.apply(u);
  const nextPetState = resolvePetState({
    usage: u,
    previousUsage,
    now: Date.now(),
    lastActivityAt: state.lastActivityAt,
  });
  // The first successful sample starts the inactivity clock too. Otherwise a
  // gateway whose numbers stay flat from launch would never reach "rest".
  if (nextPetState === PET_STATES.ACTIVE || state.lastActivityAt === null) {
    state.lastActivityAt = Date.now();
  }
  setPetState(nextPetState);
  const rows = {
    total: [u.total, fmtTokens],
    cache: [u.cache_hit, fmtTokens],
    cost: [u.cost, (v) => fmtMoneyShort(v, u.currency)],
    balance: [u.balance, (v) => fmtMoneyShort(v, u.currency)],
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

async function refreshNow() {
  setPetState(PET_STATES.REFRESH);
  try {
    const u = await invoke("fetch_usage");
    applyUsage(u);
  } catch (e) {
    setStatus("错误: " + String((e && e.message) || e).slice(0, 60), true);
    setPetState(PET_STATES.ERROR);
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
  persistPetPreferences();
  invoke("set_tray_skin", { skin: name }).catch(() => {});
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

function showCompanionNotice() {
  setStatus("宠物角色为非商业同人素材；详情见 companions/ATTRIBUTION.md");
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
    { label: "伙伴", run: () => showMenu(menuPos.x, menuPos.y, companionItems()) },
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

function companionItems() {
  const items = [
    { label: "随机伙伴", run: () => { state.companionLocked = false; chooseCompanion(); } },
    {
      label: "锁定当前伙伴",
      checked: state.companionLocked,
      run: () => {
        state.companionLocked = !state.companionLocked;
        persistPetPreferences();
        updateCompanionUI();
      },
    },
    { sep: true },
  ];
  for (const companion of COMPANIONS) {
    items.push({
      label: companion.name,
      checked: state.companion.id === companion.id,
      run: () => chooseCompanion(companion.id),
    });
  }
  return items;
}

function settingsItems() {
  return [
    { label: "窗口置顶", checked: state.alwaysOnTop, run: toggleTopmost },
    { sep: true },
    { label: "编辑配置…", run: editConfig },
    { label: "打开配置目录", run: openConfigDir },
    { sep: true },
    { label: "重载配置", run: reloadConfig },
    { sep: true },
    { label: "关于宠物素材", run: showCompanionNotice },
  ];
}

// ---------------------------------------------------------------------------
// 托盘事件
// ---------------------------------------------------------------------------

async function handleTray(event) {
  invoke("tm_report", { rect: "TRAY-EVT:" + event });
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
  const refreshSec = Number(state.gw.refresh_seconds || 5);
  clearInterval(window.__tmPoll);
  window.__tmPoll = setInterval(refreshNow, refreshSec * 1000);
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
      else if (act === "companion") showMenu(pos.left, pos.bottom + 4, companionItems());
      else if (act === "skin") showMenu(pos.left, pos.bottom + 4, skinItems());
      else if (act === "settings") showMenu(pos.left, pos.bottom + 4, settingsItems());
    });
  }

  for (const ev of [
    "tm-toggle", "tm-refresh",
    "tm-skin-pokeball", "tm-skin-master", "tm-skin-great", "tm-skin-ultra",
    "tm-topmost", "tm-edit-config", "tm-open-config-dir", "tm-reload-config",
  ]) {
    listen(ev, () => {
      invoke("tm_report", { rect: "LISTEN:" + ev });
      handleTray(ev);
    });
  }

  // 配置与初始绘制
  loadPetPreferences();
  $("half-top").src = "skins/ball_" + state.skin + ".svg";
  $("half-bot").src = "skins/ball_" + state.skin + ".svg";
  updateCompanionUI();
  const payload = await invoke("get_config");
  state.platform = await invoke("get_platform");
  applyConfig(payload);
  const pos = await appWindow.outerPosition();
  const f = await sf();
  state.basePos = { x: pos.x / f, y: pos.y / f };
  await drawClosed();
  updateBallText();
  clearInterval(window.__tmPetIdle);
  window.__tmPetIdle = setInterval(() => {
    if (state.petState === PET_STATES.ERROR || state.petState === PET_STATES.REFRESH) return;
    const next = resolvePetState({
      usage: state.usage,
      previousUsage: state.usage,
      now: Date.now(),
      lastActivityAt: state.lastActivityAt,
    });
    if (next !== state.petState) setPetState(next);
  }, 30_000);
  nudgeInput(); // 首次显示后重新激活输入
  refreshNow();
}

init();
