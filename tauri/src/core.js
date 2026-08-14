// TokenMon 前端纯逻辑层: 格式化 / 会话统计 / 展示决策。
// 无 DOM、无 Tauri API 依赖, 可用 node 单测(tauri/tests/core.test.mjs)。

export const SKINS = { pokeball: "精灵球", master: "大师球", great: "超级球", ultra: "高级球" };
export const DEFAULT_SKIN = "pokeball";

export const BALL = 64;      // 球体显示尺寸
export const PANEL_W = 200;  // 面板宽度
export const SNAP_TH = 48;   // 边缘吸附阈值(px)
export const ANIM_STEPS = 12;
export const ANIM_MS = 60; // 实验: 加大帧间隔测试 resize 风暴

export const DETAIL_FIELDS = [
  ["prompt", "Prompt"],
  ["completion", "Completion"],
  ["reasoning", "Reasoning"],
  ["cache_miss", "Cache Miss"],
  ["session_cache_hit", "Session Hit"],
  ["session_cache_miss", "Session Miss"],
  ["session_delta", "本会话增量"],
  ["rate", "实时速率"],
];

// ---------------- 格式化(与 Python _fmt_* 一致) ----------------

function formatInt(n) {
  return Math.round(n).toLocaleString("en-US");
}

export function fmtTokens(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  return formatInt(Number(n));
}

export function fmtMoney(n, currency) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  const sym = typeof currency === "string" && currency ? currency : "$";
  return sym + Number(n).toFixed(4);
}

export function fmtShort(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  const f = Number(n);
  if (f >= 1_000_000) return (f / 1_000_000).toFixed(1) + "M";
  if (f >= 1_000) return (f / 1_000).toFixed(1) + "k";
  return formatInt(f);
}

export function fmtMoneyShort(n, currency) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  const sym = typeof currency === "string" && currency ? currency : "$";
  const f = Number(n);
  if (f >= 1_000) return sym + (f / 1_000).toFixed(1) + "k";
  return sym + f.toFixed(2);
}

// ---------------- 展示决策(与 Python 版 _hidden/has_logs 一致) ----------------

export function hiddenRows(gtype) {
  if (gtype === "deepseek" || gtype === "openrouter") return new Set(["total", "cache"]);
  if (gtype === "litellm") return new Set(["cache"]);
  return new Set();
}

export function hasLogs(gw) {
  const gtype = String(gw.type || "").toLowerCase();
  const base = String(gw.base_url || "");
  return (
    gtype === "litellm" ||
    (gtype === "custom" && Boolean(String(gw.logs_url || "").trim())) ||
    base.startsWith("mock://")
  );
}

// ---------------- 会话统计(移植 _apply_usage 的增量/速率部分) ----------------

export class SessionStats {
  constructor() {
    this.prevTotal = null;
    this.prevCost = null;
    this.sessionTokens = 0;
    this.sessionCost = 0;
    this.rate = 0;
    this.lastUpdate = null; // ms
  }

  apply(usage, nowMs = Date.now()) {
    const elapsed = this.lastUpdate === null ? null : (nowMs - this.lastUpdate) / 1000;
    if (usage.total !== null && usage.total !== undefined) {
      if (this.prevTotal !== null) {
        const delta = usage.total - this.prevTotal;
        if (delta >= 0) {
          this.sessionTokens += delta;
          if (elapsed) this.rate = 0.85 * this.rate + 0.15 * (delta / elapsed);
        } else {
          this.rate = 0;
        }
      }
      this.prevTotal = usage.total;
    } else {
      this.prevTotal = null;
    }
    if (usage.cost !== null && usage.cost !== undefined) {
      if (this.prevCost !== null && usage.cost >= this.prevCost) {
        this.sessionCost += usage.cost - this.prevCost;
      }
      this.prevCost = usage.cost;
    } else {
      this.prevCost = null;
    }
    this.lastUpdate = nowMs;
  }
}

// ---------------- 详情缓存(与 Python 版 _detail_cache 一致) ----------------

export function buildDetailCache(usage, stats) {
  const cache = {};
  for (const [key, label] of DETAIL_FIELDS) {
    if (key === "session_delta") {
      const v = usage.total !== null && usage.total !== undefined
        ? stats.sessionTokens
        : stats.sessionCost;
      cache[key] = {
        show: v > 0,
        label,
        text: usage.total !== null && usage.total !== undefined
          ? fmtTokens(v)
          : fmtMoney(v, usage.currency),
      };
    } else if (key === "rate") {
      cache[key] = {
        show: usage.total !== null && usage.total !== undefined,
        label,
        text: (stats.rate >= 0 ? "+" : "") + stats.rate.toFixed(1) + " tok/s",
      };
    } else {
      const v = usage[key];
      const show = v !== null && v !== undefined;
      cache[key] = { show, label, text: show ? fmtTokens(v) : "—" };
    }
  }
  return cache;
}

// ---------------- 状态文本 ----------------

export function nowTime() {
  const d = new Date();
  const p = (x) => String(x).padStart(2, "0");
  return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
}
