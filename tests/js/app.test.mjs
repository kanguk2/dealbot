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
  for (const n of ["config", "notifiers", "feed", "seen", "runs", "interests", "links", "requests"]) {
    assert.deepEqual([...call("validate", json(`schemas/${n}.schema.json`), json(`data/${n}.json`))], [], n);
  }
});

test("validator blocks bad settings before saving", () => {
  const cfg = json("data/config.json");
  cfg.categories[0].keywords = [];
  cfg.min_days_left = -1;
  cfg.schedule.interval_hours = 0;
  delete cfg.feed_limit;
  const errs = [...call("validate", json("schemas/config.schema.json"), cfg)].join("\n");
  assert.match(errs, /keywords: 최소 1개/);
  assert.match(errs, /min_days_left: 0 이상/);
  assert.match(errs, /interval_hours: 1 이상/);
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

test("cadence text comes from config.schedule.interval_hours", () => {
  assert.equal(call("cadenceText", { schedule: { interval_hours: 6 } }),
    "6시간마다 자동으로 찾고, '지금 새로 찾기'를 누르면 바로 찾습니다");
  assert.match(call("cadenceText", json("data/config.json")), /^24시간마다 /);
  assert.equal(call("cadenceText", {}), "실행 간격 미설정");
  assert.equal(call("cadenceText", { schedule: { times: ["09:00"] } }), "실행 간격 미설정");
});

test("schedule schema: interval_hours 1..168 integer, old times field rejected", () => {
  const schema = json("schemas/config.schema.json");
  const withSchedule = (schedule) => ({ ...json("data/config.json"), schedule });
  for (const n of [1, 24, 168]) {
    assert.deepEqual([...call("validate", schema, withSchedule({ interval_hours: n, timezone: "Asia/Seoul" }))], [], String(n));
  }
  for (const n of [0, 169, 2.5]) {
    assert.ok(call("validate", schema, withSchedule({ interval_hours: n, timezone: "Asia/Seoul" })).length, String(n));
  }
  const extra = [...call("validate", schema, withSchedule({ interval_hours: 24, timezone: "Asia/Seoul", times: ["09:00"] }))].join(" | ");
  assert.match(extra, /times/);
  const old = [...call("validate", schema, withSchedule({ times: ["09:00"], timezone: "Asia/Seoul" }))].join(" | ");
  assert.match(old, /interval_hours: 필수/);
});

// ---- run requests (지금 새로 찾기)

test("localIso writes local time with the UTC offset", () => {
  const fake = (y, mo, d, hh, mm, ss, offsetMin) => ({
    getFullYear: () => y, getMonth: () => mo - 1, getDate: () => d, getHours: () => hh,
    getMinutes: () => mm, getSeconds: () => ss, getTimezoneOffset: () => offsetMin,
  });
  assert.equal(call("localIso", fake(2026, 10, 18, 9, 5, 7, -540)), "2026-10-18T09:05:07+09:00");
  assert.equal(call("localIso", fake(2026, 1, 2, 3, 4, 5, 0)), "2026-01-02T03:04:05+00:00");
  assert.equal(call("localIso", fake(2026, 12, 31, 23, 59, 59, 300)), "2026-12-31T23:59:59-05:00");
  assert.equal(call("localIso", fake(2026, 3, 4, 10, 0, 0, -330)), "2026-03-04T10:00:00+05:30");
  assert.equal(call("localIso", fake(2026, 3, 4, 10, 0, 0, 570)), "2026-03-04T10:00:00-09:30");
  // a real Date round-trips to the same instant and matches the requests schema pattern
  const d = new Date(Date.UTC(2026, 9, 18, 1, 2, 3));
  const iso = call("localIso", d);
  assert.match(iso, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/);
  assert.equal(new Date(iso).getTime(), d.getTime());
});

test("openRequest returns the oldest open request or null", () => {
  assert.equal(call("openRequest", null), null);
  assert.equal(call("openRequest", { requests: [] }), null);
  assert.equal(call("openRequest", {}), null);
  const done = { id: "a", requested_at: "2026-10-18T08:00:00+09:00", status: "done", done_at: "2026-10-18T09:00:00+09:00" };
  assert.equal(call("openRequest", { requests: [done] }), null);
  const o1 = { id: "b", requested_at: "2026-10-18T09:10:00+09:00", status: "open", done_at: null };
  const o2 = { id: "c", requested_at: "2026-10-18T09:20:00+09:00", status: "open", done_at: null };
  assert.equal(call("openRequest", { requests: [done, o1, o2] }).id, "b");
});

test("requestNoteHtml is empty without a request and escapes the time", () => {
  assert.equal(call("requestNoteHtml", null), "");
  const html = call("requestNoteHtml", { id: "x", requested_at: "2026-10-18T09:10:00+09:00", status: "open", done_at: null });
  assert.match(html, /새로 찾기 요청 접수됨/);
  assert.match(html, /\(\d{1,2}\/\d{1,2} \d{2}:\d{2}\)/);
  const evil = call("requestNoteHtml", { id: "x", requested_at: "<img src=x onerror=alert(1)>", status: "open", done_at: null });
  assert.doesNotMatch(evil, /<img/);
  assert.match(evil, /&lt;img src=x onerror=alert\(1\)&gt;/);
});

// ---- picks, interests and link collections (default view)

const plain = (x) => JSON.parse(JSON.stringify(x));
const TODAY = "2026-10-17";

test("bracketBrand takes a leading [brand] or (brand) only", () => {
  assert.equal(call("bracketBrand", "[KB Pay] 10월 적립"), "KB Pay");
  assert.equal(call("bracketBrand", "  (토스) 행운퀴즈"), "토스");
  assert.equal(call("bracketBrand", "10월 적립 [KB Pay]"), null);
  assert.equal(call("bracketBrand", "[]빈 괄호"), null);
  assert.equal(call("bracketBrand", null), null);
});

test("deriveTerms extracts the [brand] and category keywords in the title, max 3, no duplicates", () => {
  assert.deepEqual(plain(call("deriveTerms", { title: "[네이버페이] 포인트 적립 이벤트" }, ["포인트", "적립", "캐시백"])),
    ["네이버페이", "포인트", "적립"]);
  assert.deepEqual(plain(call("deriveTerms", { title: "Naver 포인트" }, ["naver", "NAVER", "쿠폰"])), ["naver", "NAVER"],
    "keyword match is case-insensitive; distinct spellings are kept");
  assert.deepEqual(plain(call("deriveTerms", { title: "[A] a b c d" }, ["a", "b", "c", "d"])).length, 3);
  assert.deepEqual(plain(call("deriveTerms", { title: "[적립] 적립왕" }, ["적립"])), ["적립"], "brand == keyword is deduped");
  assert.deepEqual(plain(call("deriveTerms", { title: "그냥 딜" })), []);
});

test("interestScore counts matching terms over title, summary and source name", () => {
  const it = deal({ title: "네이버페이 적립", summary: "KB 카드 결제", source: "rss:ppomppu_coupon" });
  assert.equal(call("interestScore", it, ["네이버", "kb", "뽐뿌", "카카오"]), 3);
  assert.equal(call("interestScore", it, []), 0);
  assert.equal(call("interestScore", deal({ summary: null }), ["null"]), 0);
});

test("valueScore prefers free, big discounts, closing soon and new", () => {
  const base = deal({ summary: null, status: "seen" });
  assert.equal(call("valueScore", base, TODAY), 0);
  assert.ok(call("valueScore", deal({ price_krw: 0 }), TODAY) > call("valueScore", deal(), TODAY));
  assert.ok(call("valueScore", deal({ discount_pct: 50 }), TODAY) > call("valueScore", deal({ discount_pct: 10 }), TODAY));
  assert.ok(call("valueScore", deal({ ends: "2026-10-20" }), TODAY) > call("valueScore", deal({ ends: "2026-11-30" }), TODAY));
  assert.ok(call("valueScore", deal({ status: "new" }), TODAY) > call("valueScore", deal(), TODAY));
});

test("pickDeals with no terms is generic, best value first, capped at n", () => {
  const pool = [deal({ id: "a" }), deal({ id: "b", price_krw: 0 }), deal({ id: "c", discount_pct: 40 }), deal({ id: "d" })];
  const r = plain(call("pickDeals", pool, { terms: [], saved: [] }, 2, TODAY));
  assert.equal(r.mode, "generic");
  assert.deepEqual(r.items.map((i) => i.id), ["b", "c"]);
  assert.equal(plain(call("pickDeals", pool, null, 4, TODAY)).mode, "generic", "missing interests file");
});

test("pickDeals with matching terms is interest mode, more matches first", () => {
  const pool = [
    deal({ id: "free", price_krw: 0, title: "무료 쿠폰" }),
    deal({ id: "one", title: "네이버페이 적립" }),
    deal({ id: "two", title: "네이버페이 KB 적립" }),
  ];
  const r = plain(call("pickDeals", pool, { terms: ["네이버", "KB"] }, 4, TODAY));
  assert.equal(r.mode, "interest");
  assert.deepEqual(r.items.map((i) => i.id), ["two", "one"], "non-matching deals are not mixed in");
});

test("pickDeals falls back to generic when no deal matches the terms", () => {
  const pool = [deal({ id: "a" }), deal({ id: "b", price_krw: 0 })];
  const r = plain(call("pickDeals", pool, { terms: ["카카오"] }, 4, TODAY));
  assert.equal(r.mode, "generic");
  assert.deepEqual(r.items.map((i) => i.id), ["b", "a"]);
});

test("pickDeals excludes ignored and expired deals and dedupes by id (page item wins)", () => {
  const pool = [
    deal({ id: "x", status: "bought", title: "페이지 쪽" }),
    deal({ id: "ign", status: "ignored", price_krw: 0 }),
    deal({ id: "old", ends: "2026-10-16", price_krw: 0 }),
    deal({ id: "today", ends: TODAY }),
    deal({ id: "x", status: "new", title: "recent 쪽" }),
  ];
  const r = plain(call("pickDeals", pool, { terms: [] }, 10, TODAY));
  assert.deepEqual(r.items.map((i) => i.id).sort(), ["today", "x"]);
  assert.equal(r.items.find((i) => i.id === "x").title, "페이지 쪽");
  assert.deepEqual(plain(call("pickDeals", [], { terms: ["a"] }, 4, TODAY)), { mode: "generic", items: [] });
});

const groups = () => [
  { id: "points", name: "포인트 모음", tags: ["포인트", "페이"], links: [{ title: "뽐뿌", url: "https://a.com", note: "" }] },
  { id: "cards", name: "카드사 이벤트", tags: ["카드"], links: [{ title: "카드고릴라", url: "https://b.com", note: "캐시백 비교" }] },
  { id: "hot", name: "핫딜", tags: ["핫딜"], links: [{ title: "루리웹", url: "https://c.com", note: "게임" }] },
];

test("rankLinks keeps the file order without interests", () => {
  const r = plain(call("rankLinks", groups(), []));
  assert.deepEqual(r.map((g) => g.id), ["points", "cards", "hot"]);
  assert.deepEqual(r.map((g) => g.match), [0, 0, 0]);
  assert.deepEqual(plain(call("rankLinks", groups())).map((g) => g.id), ["points", "cards", "hot"]);
});

test("rankLinks puts groups matching interests first, by match count, stable otherwise", () => {
  const r = plain(call("rankLinks", groups(), ["게임", "캐시백", "KB카드"]));
  // cards: 캐시백 (note) + KB카드 (contains tag 카드) = 2; hot: 게임 = 1; points: 0
  assert.deepEqual(r.map((g) => [g.id, g.match]), [["cards", 2], ["hot", 1], ["points", 0]]);
  const r2 = plain(call("rankLinks", groups(), ["네이버페이"]));
  assert.equal(r2[0].id, "points", "term containing a tag (네이버페이 ⊃ 페이) matches");
  assert.equal(r2[0].match, 1);
});

test("rankLinks: an empty link note does not make every term match", () => {
  const r = plain(call("rankLinks", groups(), ["전혀없는말"]));
  assert.deepEqual(r.map((g) => g.match), [0, 0, 0]);
});

test("committed links.json ranks and renders", () => {
  const r = call("rankLinks", json("data/links.json").groups, ["카드"]);
  assert.ok(r[0].match > 0);
  const html = call("linksHtml", r);
  assert.match(html, /badge-new">관심</);
  assert.doesNotMatch(html, /undefined|null/);
});

test("linksHtml marks matching groups and escapes names, titles, notes and URLs", () => {
  const html = call("linksHtml", [
    { name: "<b>모음</b>", match: 1, links: [{ title: "<img src=x onerror=alert(1)>", url: 'https://e.com/"><script>x</script>', note: "<i>n</i>" }] },
    { name: "다른", match: 0, links: [{ title: "t", url: "https://e.com", note: "" }] },
  ]);
  assert.doesNotMatch(html, /<b>모음|<img|<script|<i>n/);
  assert.match(html, /&lt;b&gt;모음&lt;\/b&gt;/);
  assert.match(html, /href="https:\/\/e.com\/&quot;&gt;&lt;script&gt;/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.equal((html.match(/link-group match/g) || []).length, 1);
  assert.equal((html.match(/badge-new">관심/g) || []).length, 1);
  assert.equal((html.match(/<span>/g) || []).length, 1, "empty note renders no span");
});

test("deal card: ☆/★ 관심 button and opts.marks=false hides 샀음/무시", () => {
  const plainCard = call("dealCardHtml", deal(), "포인트", TODAY);
  assert.match(plainCard, /data-act="interest" class="star" aria-pressed="false">☆ 관심</);
  assert.match(plainCard, /data-act="bought"/);
  assert.match(plainCard, /data-act="ignored"/);
  const saved = call("dealCardHtml", deal({ status: "bought" }), "포인트", TODAY, { saved: true });
  assert.match(saved, /class="star on" aria-pressed="true">★ 관심</);
  assert.match(saved, /data-act="bought" class="on"/);
  const pick = call("dealCardHtml", deal(), "포인트", TODAY, { saved: false, marks: false });
  assert.match(pick, /☆ 관심/);
  assert.doesNotMatch(pick, /data-act="bought"|data-act="ignored"/);
  const undef = call("dealCardHtml", deal(), "포인트", TODAY, { marks: undefined });
  assert.match(undef, /data-act="bought"/, "only an explicit false hides the marks");
});

test("deal card in picks mode still escapes everything", () => {
  const html = call("dealCardHtml", deal({ id: "\"><script>1</script>", title: "<svg onload=x>", summary: "<script>y</script>" }),
    "<i>c</i>", TODAY, { saved: true, marks: false });
  assert.doesNotMatch(html, /<svg|<script|<i>c/);
});
