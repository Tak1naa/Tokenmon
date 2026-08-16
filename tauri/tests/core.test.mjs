import test from "node:test";
import assert from "node:assert/strict";
import {
  fmtTokens, fmtMoney, fmtShort, fmtMoneyShort,
  hiddenRows, SessionStats, buildDetailCache,
} from "../src/core.js";

test("fmtTokens 千分位", () => {
  assert.equal(fmtTokens(2215154), "2,215,154");
  assert.equal(fmtTokens(123), "123");
  assert.equal(fmtTokens(null), "—");
});

test("fmtMoney 固定 4 位", () => {
  assert.equal(fmtMoney(0.3755, "¥"), "¥0.3755");
  assert.equal(fmtMoney(1.5), "$1.5000");
  assert.equal(fmtMoney(null, "$"), "—");
});

test("fmtShort 紧凑格式", () => {
  assert.equal(fmtShort(2215154), "2.2M");
  assert.equal(fmtShort(123456), "123.5k");
  assert.equal(fmtShort(1234), "1.2k");
  assert.equal(fmtShort(999), "999");
  assert.equal(fmtShort(null), "—");
});

test("fmtMoneyShort", () => {
  assert.equal(fmtMoneyShort(0.3755, "¥"), "¥0.38");
  assert.equal(fmtMoneyShort(1500, "$"), "$1.5k");
});

test("hiddenRows 按网关类型", () => {
  assert.deepEqual([...hiddenRows("custom")], []);
  assert.deepEqual([...hiddenRows("litellm")], ["cache"]);
  assert.deepEqual([...hiddenRows("deepseek")].sort(), ["cache", "total"]);
  assert.deepEqual([...hiddenRows("openrouter")].sort(), ["cache", "total"]);
});

test("SessionStats 增量与速率", () => {
  const s = new SessionStats();
  s.apply({ total: 100, cost: 1 }, 1000);
  s.apply({ total: 130, cost: 1.3 }, 2000); // +30 tok / 1s
  assert.equal(s.sessionTokens, 30);
  assert.ok(Math.abs(s.sessionCost - 0.3) < 1e-9);
  assert.ok(s.rate > 3 && s.rate < 15); // 0.15 * (30/1s) = 4.5
  s.apply({ total: 120, cost: 1.3 }, 3000); // 回退 → rate 归零
  assert.equal(s.rate, 0);
});

test("buildDetailCache 展示规则", () => {
  const u = { total: 100, prompt: 60, completion: 40, reasoning: null, cache_hit: null,
              cache_miss: 5, session_cache_hit: null, session_cache_miss: null,
              cost: 0.5, currency: "¥", balance: null };
  const s = new SessionStats();
  s.apply({ total: 100, cost: 0.5 }, 1000);
  const c = buildDetailCache(u, s);
  assert.equal(c.prompt.show, true);
  assert.equal(c.prompt.text, "60");
  assert.equal(c.reasoning.show, false);
  assert.equal(c.rate.show, true);
  assert.ok(c.rate.text.endsWith("tok/s"));
  assert.equal(c.session_delta.show, false); // 尚无增量
  s.apply({ total: 120, cost: 0.8 }, 2000); // 会话增量 0.3
  const c2 = buildDetailCache({ ...u, total: null, cost: 0.8 }, s);
  assert.equal(c2.session_delta.show, true); // cost 口径
  assert.ok(c2.session_delta.text.startsWith("¥"));
});
