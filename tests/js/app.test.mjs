// UI logic tests: node --test tests/js
// app.js is a browser script, so it is loaded into a vm context with tiny stubs.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");
const json = (p) => JSON.parse(read(p));

function loadApp(hostname = "kanguk2.github.io", pathname = "/dealbot/docs/") {
  const ctx = {
    console, TextEncoder, TextDecoder, btoa, atob, setTimeout, clearTimeout,
    location: { hostname, pathname },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: { addEventListener() {} },
  };
  vm.createContext(ctx);
  vm.runInContext(read("docs/app.js"), ctx);
  return (expr) => vm.runInContext(expr, ctx);
}
const app = loadApp();
const call = (fn, ...args) => app(fn)(...args);

test("repo is detected from the Pages URL (root or /docs)", () => {
  assert.equal(app("repo()"), "kanguk2/dealbot");
  assert.equal(loadApp("someone.github.io", "/other/")("repo()"), "someone/other");
});

test("committed data passes the schemas in the browser validator", () => {
  for (const n of ["config", "notifiers", "feed", "seen", "runs"]) {
    assert.deepEqual([...call("validate", json(`schemas/${n}.schema.json`), json(`data/${n}.json`))], [], n);
  }
});

test("validator blocks bad settings before saving", () => {
  const cfg = json("data/config.json");
  cfg.categories[0].keywords = [];
  cfg.min_days_left = -1;
  cfg.schedule.times.push("25:00");
  delete cfg.feed_limit;
  const errs = [...call("validate", json("schemas/config.schema.json"), cfg)].join("\n");
  assert.match(errs, /keywords: 최소 1개/);
  assert.match(errs, /min_days_left: 0 이상/);
  assert.match(errs, /25:00/);
  assert.match(errs, /feed_limit: 필수/);
});

test("validator follows $ref into $defs (feed items)", () => {
  const feed = { run_at: null, items: [{ id: "x" }], pending: [], bought: [] };
  const errs = [...call("validate", json("schemas/feed.schema.json"), feed)];
  assert.ok(errs.some((e) => e.includes("items[0].title: 필수")));
});

test("base64 round-trips Korean and large content", () => {
  const s = "한글 ✓ " + "x".repeat(100000);
  assert.equal(call("b64decode", call("b64encode", s)), s);
});

test("ended deals are hidden on the page", () => {
  const items = [{ ends: "2026-10-16" }, { ends: "2026-10-17" }, { ends: null }];
  assert.equal(call("visibleItems", items, "2026-10-17").length, 2);
});

test("month stats use the run log and bought history", () => {
  const feed = {
    items: [{ id: "a", status: "bought", found_at: "2026-10-17T09:00:00+09:00", price_krw: 1000, original_price_krw: 3000 }],
    bought: [{ id: "b", status: "bought", found_at: "2026-10-02T09:00:00+09:00", price_krw: 0, original_price_krw: 5000 },
             { id: "c", status: "bought", found_at: "2026-09-30T09:00:00+09:00", price_krw: 0, original_price_krw: 9000 }],
  };
  const runs = { runs: [{ at: "2026-10-17T09:00:00+09:00", new: 3 }, { at: "2026-10-01T09:00:00+09:00", new: 2 },
                        { at: "2026-09-30T09:00:00+09:00", new: 7 }] };
  const s = call("monthStats", feed, runs, new Date(2026, 9, 17));
  assert.deepEqual({ ...s }, { found: 5, bought: 2, saved: 7000 });
});

test("guide renders MANUAL.md: headings with anchors, tables, code, no raw markdown", () => {
  const html = call("renderMarkdown", read("MANUAL.md"));
  assert.match(html, /<h1 id="딜봇-사용-설명서">/);
  assert.match(html, /<table>/);
  assert.match(html, /<pre><code>/);
  assert.doesNotMatch(html, /\*\*[^*]+\*\*/, "bold left unrendered");
  assert.doesNotMatch(html, /<p>\s*\|/, "table rendered as a paragraph");
  assert.doesNotMatch(html, /<p>#/, "heading rendered as a paragraph");
});

test("guide markdown: lists, links, escaping", () => {
  const html = call("renderMarkdown", "- a [x](https://e.com) `<b>`\n  - nested\n- [readme](README.md)\n\n1. one\n2. two\n\n<script>");
  assert.match(html, /<ul><li>a <a href="https:\/\/e.com" target="_blank"/);
  assert.match(html, /<code>&lt;b&gt;<\/code>/);
  assert.match(html, /<ul><li>nested<\/li><\/ul>/);
  assert.match(html, /href="https:\/\/github.com\/kanguk2\/dealbot\/blob\/main\/README.md"/);
  assert.match(html, /<ol><li>one<\/li><li>two<\/li><\/ol>/);
  assert.match(html, /&lt;script&gt;/);
});

test("slug matches GitHub heading anchors", () => {
  assert.equal(call("slug", "정기 점검"), "정기-점검");
  assert.equal(call("slug", "알림 채널 켜고 끄기, 새 채널 추가"), "알림-채널-켜고-끄기-새-채널-추가");
});
