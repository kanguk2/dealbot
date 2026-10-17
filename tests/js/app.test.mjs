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

// ---- feed page (Flight Watch style redesign)

const deal = (over = {}) => ({
  id: "d1", status: "seen", category: "points", title: "네이버페이 포인트 적립", url: "https://example.com/1",
  source: "rss:ppomppu_coupon", price_krw: null, original_price_krw: null, discount_pct: null,
  ends: null, summary: "선착순 1만 명", ...over,
});

test("search query needs every word, case-insensitive, over title/summary/source name", () => {
  const it = deal({ title: "Naver Pay 포인트", summary: "선착순 적립" });
  assert.equal(call("matchesQuery", it, ""), true);
  assert.equal(call("matchesQuery", it, "   "), true);
  assert.equal(call("matchesQuery", it, "naver"), true);
  assert.equal(call("matchesQuery", it, "NAVER 선착순"), true);
  assert.equal(call("matchesQuery", it, "뽐뿌"), true, "source display name is searchable");
  assert.equal(call("matchesQuery", it, "naver 카카오"), false, "all words must match");
  assert.equal(call("matchesQuery", deal({ summary: undefined }), "undefined"), false);
});

test("source info names known sites and falls back to a generic badge", () => {
  assert.equal(call("sourceInfo", "rss:ppomppu_coupon").name, "뽐뿌");
  assert.equal(call("sourceInfo", "rss:ppomppu_hotdeal").cls, "ppomppu");
  assert.equal(call("sourceInfo", "rss:ruliweb_hotdeal").name, "루리웹");
  assert.equal(call("sourceInfo", "search").name, "웹 검색");
  assert.equal(call("sourceInfo", "epic_free").name, "에픽게임즈");
  assert.equal(call("sourceInfo", "rss:foo_bar").cls, "other");
  assert.equal(call("sourceInfo", "custom").cls, "other");
  assert.equal(call("sourceInfo", null).cls, "other");
});

test("days left counts calendar days", () => {
  assert.equal(call("daysLeft", "2026-10-17", "2026-10-17"), 0);
  assert.equal(call("daysLeft", "2026-10-19", "2026-10-17"), 2);
  assert.equal(call("daysLeft", "2026-11-01", "2026-10-31"), 1);
});

test("deal card: free, discount, unknown price", () => {
  const free = call("dealCardHtml", deal({ price_krw: 0, original_price_krw: 5000 }), "포인트", "2026-10-17");
  assert.match(free, /class="free">무료</);
  assert.match(free, /<s>5,000원<\/s>/);
  const sale = call("dealCardHtml", deal({ price_krw: 7000, original_price_krw: 10000, discount_pct: 30 }), "포인트", "2026-10-17");
  assert.match(sale, /<strong>7,000원<\/strong><span class="pct">-30%<\/span><s>10,000원<\/s>/);
  const unknown = call("dealCardHtml", deal(), "포인트", "2026-10-17");
  assert.match(unknown, /혜택 내용은 본문 확인/);
  assert.match(unknown, /마감일 정보 없음/);
  assert.doesNotMatch(unknown, /무료|null|undefined|NaN/);
});

test("deal card: deadline shows 오늘 / D-n and flags ≤2 days as soon", () => {
  const card = (ends) => call("dealCardHtml", deal({ ends }), "포인트", "2026-10-17");
  assert.match(card("2026-10-17"), /class="deal-due soon">~10\/17 마감 · 오늘</);
  assert.match(card("2026-10-19"), /class="deal-due soon">~10\/19 마감 · D-2</);
  assert.match(card("2026-10-20"), /class="deal-due">~10\/20 마감 · D-3</);
});

test("deal card escapes title, summary and URL (no XSS)", () => {
  const html = call("dealCardHtml", deal({
    title: "<b>굵게</b><img src=x onerror=alert(1)>", summary: "<script>x</script>",
    url: 'https://e.com/"><script>alert(1)</script>', status: "new",
  }), "<i>cat</i>", "2026-10-17");
  assert.doesNotMatch(html, /<b>|<img|<script|<i>/);
  assert.match(html, /&lt;b&gt;굵게&lt;\/b&gt;/);
  assert.match(html, /href="https:\/\/e.com\/&quot;&gt;&lt;script&gt;/);
  assert.match(html, /badge-new/);
});

test("run chart: latest 14 runs, oldest first, error runs amber, empty message", () => {
  assert.match(call("runChartSvg", { runs: [] }), /실행 기록이 쌓이면/);
  assert.match(call("runChartSvg", null), /실행 기록이 쌓이면/);
  const runs = { runs: Array.from({ length: 20 }, (_, i) => ({
    at: `2026-10-${String(20 - i).padStart(2, "0")}T09:00:00+09:00`, new: i, found: i + 1,
    errors: i === 0 ? [{ source: "rss:x", error: "HTTP 404" }] : [],
  })) };
  const svg = call("runChartSvg", runs);
  assert.equal((svg.match(/<rect /g) || []).length, 14);
  assert.equal((svg.match(/trend-bar err/g) || []).length, 1);
  assert.match(svg, /최근 14회 · 합계 91건/);  // 0+1+...+13
  const bars = [...svg.matchAll(/<rect class="trend-bar( err)?" x="([\d.]+)"/g)];
  assert.equal(bars[bars.length - 1][1], " err", "newest run (index 0) is drawn last, on the right");
});

test("cadence text comes from config.schedule.times", () => {
  assert.equal(call("cadenceText", { schedule: { times: ["09:00", "19:00"] } }), "매일 09:00 · 19:00 KST에 확인");
  assert.equal(call("cadenceText", json("data/config.json")).startsWith("매일 "), true);
  assert.equal(call("cadenceText", {}), "실행 시간 미설정");
});
