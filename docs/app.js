/* DealBot UI: reads/writes data/*.json in the GitHub repo. No framework, no build. */
"use strict";

// ------------------------------------------------------------------ repo & storage

const LS = { token: "dealbot.token", repo: "dealbot.repo" };
const BRANCH = "main";
const DEFAULT_REPO = "kanguk2/dealbot";

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch (e) { /* private mode: token just won't persist */ }
  return null;
}

function detectRepo() {
  const saved = store(LS.repo);
  if (saved) return saved;
  const host = location.hostname;
  if (host.endsWith(".github.io")) {
    const owner = host.split(".")[0];
    const repo = location.pathname.split("/").filter(Boolean)[0];
    if (repo) return `${owner}/${repo}`;
  }
  return DEFAULT_REPO;
}

const isLocal = ["localhost", "127.0.0.1", ""].includes(location.hostname);
const token = () => store(LS.token) || "";
const repo = () => detectRepo();

// ------------------------------------------------------------------ GitHub Contents API

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

function b64encode(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

function b64decode(b64) {
  const bin = atob(b64.replace(/\n/g, ""));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

async function gh(path, opts = {}) {
  const headers = { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" };
  if (token()) headers.Authorization = `Bearer ${token()}`;
  if (opts.body) headers["Content-Type"] = "application/json";
  const res = await fetch(`https://api.github.com/repos/${repo()}/${path}`, { cache: "no-store", ...opts, headers });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).message || msg; } catch (e) { /* not JSON */ }
    throw new ApiError(res.status, `GitHub ${res.status}: ${msg}`);
  }
  return res.json();
}

/** Read a repo text file (e.g. MANUAL.md) without needing a token. */
async function readText(path) {
  const url = isLocal ? `../${path}` : `https://raw.githubusercontent.com/${repo()}/${BRANCH}/${path}?t=${Date.now()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new ApiError(res.status, `${path}: ${res.status}`);
  return res.text();
}

/** Read a repo file as JSON. Returns {data, sha}; sha is null when read without the API. */
async function readFile(path) {
  if (token()) {
    try {
      const meta = await gh(`contents/${path}?ref=${BRANCH}`);
      return { data: JSON.parse(b64decode(meta.content)), sha: meta.sha };
    } catch (e) {
      if (e.status !== 401) throw e;
      store(LS.token, null); // expired or revoked: read anonymously, ask again on the next save
    }
  }
  // No token: local dev server (repo root) or public raw file.
  const url = isLocal ? `../${path}` : `https://raw.githubusercontent.com/${repo()}/${BRANCH}/${path}?t=${Date.now()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new ApiError(res.status, `${path}: ${res.status}`);
  return { data: await res.json(), sha: null };
}

async function writeFile(path, data, sha, message) {
  const body = { message, branch: BRANCH, content: b64encode(JSON.stringify(data, null, 2) + "\n") };
  if (sha) body.sha = sha;
  return gh(`contents/${path}`, { method: "PUT", body: JSON.stringify(body) });
}

/**
 * GET -> mutate -> PUT. On a sha conflict (409, or 422 for a stale sha) re-read and retry once.
 * mutate(data) edits in place (or returns a replacement); returning false skips the write.
 */
async function updateFile(path, mutate, message) {
  if (!token() && !(await askToken())) throw new ApiError(401, "토큰을 넣지 않아 저장하지 않았습니다.");
  let reauthed = false;
  for (let attempt = 1; ; attempt++) {
    const { data, sha } = await readFile(path);
    const out = mutate(data);
    if (out === false) return data;
    const next = out === undefined ? data : out;
    try {
      await writeFile(path, next, sha, message);
      return next;
    } catch (e) {
      if (attempt < 2 && (e.status === 409 || e.status === 422)) continue;
      if (!reauthed && (e.status === 401 || e.status === 403)) {
        store(LS.token, null);
        reauthed = true;
        if (await askToken("저장된 토큰이 만료됐거나 쓰기 권한이 없습니다. 새 토큰을 넣어 주세요.")) { attempt = 0; continue; }
      }
      throw e;
    }
  }
}

// ------------------------------------------------------------------ mini JSON Schema validator
// Supports the subset used in schemas/: type, enum, required, properties, additionalProperties,
// items, minItems, maxItems, uniqueItems, minLength, maxLength, minimum, maximum, pattern, $ref (#/$defs).

function typeOf(v) {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  if (typeof v === "number") return Number.isInteger(v) ? "integer" : "number";
  return typeof v;
}

function validate(schema, value) {
  const errors = [];
  const root = schema;
  const resolve = (s) => (s && s.$ref ? root.$defs[s.$ref.replace("#/$defs/", "")] : s);
  const walk = (s, v, path) => {
    s = resolve(s);
    if (!s || s === true) return;
    const t = typeOf(v);
    if (s.type) {
      const types = [].concat(s.type);
      const ok = types.includes(t) || (t === "integer" && types.includes("number"));
      if (!ok) { errors.push(`${path}: ${types.join("|")} 이어야 함`); return; }
    }
    if (s.enum && !s.enum.some((e) => JSON.stringify(e) === JSON.stringify(v))) errors.push(`${path}: ${s.enum.join(", ")} 중 하나여야 함`);
    if (t === "string") {
      if (s.minLength != null && v.length < s.minLength) errors.push(`${path}: 비어 있으면 안 됨`);
      if (s.maxLength != null && v.length > s.maxLength) errors.push(`${path}: ${s.maxLength}자 이하`);
      if (s.pattern && !new RegExp(s.pattern).test(v)) errors.push(`${path}: 형식이 맞지 않음 ("${v}")`);
    }
    if (t === "integer" || t === "number") {
      if (s.minimum != null && v < s.minimum) errors.push(`${path}: ${s.minimum} 이상`);
      if (s.maximum != null && v > s.maximum) errors.push(`${path}: ${s.maximum} 이하`);
    }
    if (t === "array") {
      if (s.minItems != null && v.length < s.minItems) errors.push(`${path}: 최소 ${s.minItems}개 필요`);
      if (s.maxItems != null && v.length > s.maxItems) errors.push(`${path}: 최대 ${s.maxItems}개`);
      if (s.uniqueItems && new Set(v.map((x) => JSON.stringify(x))).size !== v.length) errors.push(`${path}: 중복 항목`);
      if (s.items) v.forEach((x, i) => walk(s.items, x, `${path}[${i}]`));
    }
    if (t === "object") {
      for (const k of s.required || []) if (!(k in v)) errors.push(`${path}.${k}: 필수`);
      for (const [k, x] of Object.entries(v)) {
        if (s.properties && k in s.properties) walk(s.properties[k], x, `${path}.${k}`);
        else if (s.additionalProperties === false) errors.push(`${path}.${k}: 알 수 없는 필드`);
        else if (typeof s.additionalProperties === "object") walk(s.additionalProperties, x, `${path}.${k}`);
      }
    }
  };
  walk(schema, value, "$");
  return errors;
}

// ------------------------------------------------------------------ small helpers

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** h("div", {class: "x", onclick: fn}, child, "text", [children]) */
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k in el && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) if (c != null && c !== false) el.append(c.nodeType ? c : String(c));
  return el;
}

const won = (n) => `${n.toLocaleString("ko-KR")}원`;
const mmdd = (iso) => (iso ? `${+iso.slice(5, 7)}/${+iso.slice(8, 10)}` : "");
const SOURCE_LABEL = { epic_free: "에픽", search: "검색" };
const RSS_LABEL = { ruliweb: "루리웹", ppomppu: "뽐뿌", quasarzone: "퀘이사존", algumon: "알구몬", seoul: "서울시" };

function sourceLabel(src) {
  if (!src) return "";
  if (SOURCE_LABEL[src]) return SOURCE_LABEL[src];
  if (src.startsWith("rss:")) { const id = src.slice(4); return RSS_LABEL[id.split("_")[0]] || id; }
  return src;
}

function priceText(it) {
  const p = it.price_krw, o = it.original_price_krw, pct = it.discount_pct;
  if (p === 0) return o ? `무료 <s>${won(o)}</s>` : "무료";
  const bits = [];
  if (p != null) bits.push(`<b>${won(p)}</b>`);
  if (pct) bits.push(`<span class="pct">-${pct}%</span>`);
  if (o && p != null && o > p) bits.push(`<s>${won(o)}</s>`);
  return bits.join(" ");
}

function fmtDateTime(iso) {
  const d = new Date(iso);
  return isNaN(d) ? iso : `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function toast(msg, kind = "") {
  let el = document.getElementById("toast");
  if (!el) { el = h("div", { id: "toast" }); document.body.append(el); }
  el.textContent = msg;
  el.className = `show ${kind}`;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.className = ""), kind === "error" ? 6000 : 2500);
}

// ------------------------------------------------------------------ feed page
// The feed shows only the latest run's results (each Codex run replaces data/feed.json items).
// The page polls for a newer run and redraws itself. Layout follows the Flight Watch page:
// hero with month stats, a "딜 찾기" filter panel, a card grid, and a run-history chart.

const PAGE = 40;
const REFRESH_MS = 3 * 60 * 1000;
const STATUS_FILTERS = { active: ["new", "seen"], bought: ["bought"], ignored: ["ignored"], all: ["new", "seen", "bought", "ignored"] };
const SOURCES = {
  ppomppu: { mark: "뽐", name: "뽐뿌", cls: "ppomppu" },
  ruliweb: { mark: "루", name: "루리웹", cls: "ruliweb" },
  seoul: { mark: "서", name: "내 손안에 서울", cls: "seoul" },
  search: { mark: "검", name: "웹 검색", cls: "search" },
  epic_free: { mark: "E", name: "에픽게임즈", cls: "epic" },
};

/** Local YYYY-MM-DD for "today" comparisons with item.ends. */
function todayIso(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Deals whose end date already passed are never shown, even before the next run removes them. */
function visibleItems(items, today = todayIso()) {
  return items.filter((i) => !i.ends || i.ends >= today);
}

/** Free-text filter over title, summary and source name. */
function matchesQuery(it, q) {
  const words = (q || "").toLowerCase().split(/\s+/).filter(Boolean);
  const hay = `${it.title} ${it.summary || ""} ${sourceInfo(it.source).name}`.toLowerCase();
  return words.every((w) => hay.includes(w));
}

function sourceInfo(src) {
  if (!src) return { mark: "?", name: "알 수 없음", cls: "other" };
  if (SOURCES[src]) return SOURCES[src];
  if (src.startsWith("rss:")) {
    const site = src.slice(4).split("_")[0];
    return SOURCES[site] || { mark: site.slice(0, 1).toUpperCase(), name: sourceLabel(src), cls: "other" };
  }
  return { mark: src.slice(0, 1).toUpperCase(), name: src, cls: "other" };
}

function daysLeft(ends, today = todayIso()) {
  return Math.round((Date.parse(ends + "T00:00:00Z") - Date.parse(today + "T00:00:00Z")) / 86400000);
}

/**
 * One deal card (HTML string). Everything user-controlled goes through esc().
 * opts.saved: ☆/★ 관심 state; opts.marks === false hides 샀음/무시 (deals no longer on this run's page).
 */
function dealCardHtml(it, catName, today = todayIso(), opts = {}) {
  const s = sourceInfo(it.source);
  const p = it.price_krw, o = it.original_price_krw, pct = it.discount_pct;
  let price;
  if (p === 0) price = `<div class="deal-price"><strong class="free">무료</strong>${o ? `<s>${won(o)}</s>` : ""}</div>`;
  else if (p != null) price = `<div class="deal-price"><strong>${won(p)}</strong>${pct ? `<span class="pct">-${pct}%</span>` : ""}${o && o > p ? `<s>${won(o)}</s>` : ""}</div>`;
  else if (pct) price = `<div class="deal-price"><strong>-${pct}%</strong></div>`;
  else price = `<div class="deal-price unknown"><strong>혜택 내용은 본문 확인</strong></div>`;
  let due = `<span class="deal-due">마감일 정보 없음</span>`;
  if (it.ends) {
    const d = daysLeft(it.ends, today);
    due = `<span class="deal-due${d <= 2 ? " soon" : ""}">~${mmdd(it.ends)} 마감 · ${d === 0 ? "오늘" : `D-${d}`}</span>`;
  }
  return `<article class="deal-card s-${esc(it.status)}" data-id="${esc(it.id)}">
    <div class="deal-top">
      <div class="deal-source"><span class="source-logo ${s.cls}">${esc(s.mark)}</span>${esc(s.name)}</div>
      <a class="deal-arrow" href="${esc(it.url)}" target="_blank" rel="noopener noreferrer" aria-label="원글 열기">↗</a>
    </div>
    <p class="deal-kicker">${esc(catName)}${it.status === "new" ? '<span class="badge-new">NEW</span>' : ""}</p>
    <a class="deal-title" href="${esc(it.url)}" target="_blank" rel="noopener noreferrer">${esc(it.title)}</a>
    ${price}
    ${it.summary ? `<p class="deal-summary">${esc(it.summary)}</p>` : ""}
    <div class="deal-foot">${due}
      <div class="deal-actions">
        <button data-act="interest" class="star${opts.saved ? " on" : ""}" aria-pressed="${!!opts.saved}">${opts.saved ? "★" : "☆"} 관심</button>
        ${opts.marks === false ? "" : `<button data-act="bought" class="${it.status === "bought" ? "on" : ""}">샀음</button>
        <button data-act="ignored" class="${it.status === "ignored" ? "on" : ""}">무시</button>`}
      </div>
    </div>
  </article>`;
}

/** Bar chart of new deals per run (oldest -> newest). Runs with errors are drawn in amber. */
function runChartSvg(runs, count = 14) {
  const list = ((runs && runs.runs) || []).slice(0, count).reverse();
  if (!list.length) return '<p class="muted">실행 기록이 쌓이면 여기에 회차별로 잡힌 딜 수가 표시됩니다.</p>';
  const W = 760, H = 220, left = 40, right = 750, top = 14, bottom = 186;
  const max = Math.max(4, ...list.map((r) => r.new));
  const step = (right - left) / list.length;
  const bw = Math.min(36, step * 0.6);
  const y = (v) => bottom - (v / max) * (bottom - top);
  const grid = [0, 0.5, 1].map((f) => {
    const v = Math.round(max * f), yy = y(v);
    return `<line class="trend-grid" x1="${left}" x2="${right}" y1="${yy}" y2="${yy}"/><text class="trend-axis" x="${left - 8}" y="${yy + 4}" text-anchor="end">${v}</text>`;
  }).join("");
  const bars = list.map((r, i) => {
    // error runs keep a visible stub even with 0 new deals
    const x = left + step * i + (step - bw) / 2, h = Math.max(r.errors.length ? 8 : 2, bottom - y(r.new));
    const label = `${fmtDateTime(r.at)} · 새 딜 ${r.new}건 · 찾음 ${r.found}건${r.errors.length ? ` · 오류 ${r.errors.length}` : ""}`;
    return `<rect class="trend-bar${r.errors.length ? " err" : ""}" x="${x.toFixed(1)}" y="${(bottom - h).toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="5"><title>${esc(label)}</title></rect>`;
  }).join("");
  const first = list[0], last = list[list.length - 1];
  const axis = `<text class="trend-axis" x="${left}" y="${H - 6}">${esc(fmtDateTime(first.at))}</text>` +
    (list.length > 1 ? `<text class="trend-axis" x="${right}" y="${H - 6}" text-anchor="end">${esc(fmtDateTime(last.at))}</text>` : "");
  const total = list.reduce((s, r) => s + r.new, 0);
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="최근 ${list.length}회 실행에서 새로 잡힌 딜 수">${grid}${bars}${axis}</svg>
    <div class="trend-legend"><span><i style="background:var(--brand)"></i>새 딜 수</span><span><i style="background:#f0a020"></i>오류가 있었던 실행</span><span>최근 ${list.length}회 · 합계 ${total}건</span></div>`;
}

/** Filter tabs: 전체 + every configured category (+ any category only seen in the feed), with counts. */
function categoryTabs(cats, items) {
  const count = (id) => items.filter((i) => id === "*" || i.category === id).length;
  const ids = [...new Set([...Object.keys(cats), ...items.map((i) => i.category)])];
  return [{ id: "*", name: "전체", count: count("*") }, ...ids.map((id) => ({ id, name: cats[id] || id, count: count(id) }))];
}

/** "24시간마다 자동 확인 · 요청하면 바로" from config.schedule.interval_hours. */
function cadenceText(config) {
  const hours = config && config.schedule && config.schedule.interval_hours;
  if (hours) return `${hours}시간마다 자동으로 찾고, '지금 새로 찾기'를 누르면 바로 찾습니다`;
  return "실행 간격 미설정";
}

// ------------------------------------------------------------------ run requests (지금 새로 찾기)
// The button appends an open request to data/requests.json. The PC's Codex task polls about hourly
// and runs when one is open (scripts/due.py); the run closes it. If the PC is off, GitHub Actions
// picks it up after 2 hours (script sources only).

/** ISO time with the browser's UTC offset, e.g. 2026-10-18T10:05:00+09:00 */
function localIso(d = new Date()) {
  const pad = (n) => String(Math.abs(n)).padStart(2, "0");
  const off = -d.getTimezoneOffset();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` +
    `${off >= 0 ? "+" : "-"}${pad(Math.trunc(off / 60))}:${pad(off % 60)}`;
}

/** The oldest open request, or null. */
function openRequest(requests) {
  const open = ((requests && requests.requests) || []).filter((r) => r.status === "open");
  return open.length ? open[0] : null;
}

function requestNoteHtml(req) {
  if (!req) return "";
  return `<b>새로 찾기 요청 접수됨</b> (${esc(fmtDateTime(req.requested_at))}) · PC가 켜져 있으면 15분 안에 찾아서 이 화면이 자동으로 바뀝니다. PC가 꺼져 있으면 약 2~3시간 뒤 GitHub가 기본 소스(RSS)만 확인합니다.`;
}

// ------------------------------------------------------------------ picks & interests
// Default view (no search/filter): a few representative deals plus curated link collections.
// ☆ 관심 on a card saves it to data/interests.json and derives interest terms from it; from then
// on the picks and the links favour those terms (and Codex searches for them first).

const PICK_COUNT = 4;
const emptyInterests = () => ({ terms: [], saved: [] });

/** "[KB Pay] 10월 적립" -> "KB Pay" */
function bracketBrand(title) {
  const m = (title || "").match(/^\s*[\[(]([^\])]{1,20})[\])]/);
  return m ? m[1].trim() : null;
}

/** Terms learned from a starred deal: its [brand] plus category keywords found in the title. */
function deriveTerms(item, keywords = []) {
  const title = (item.title || "").toLowerCase();
  const out = [];
  const brand = bracketBrand(item.title);
  if (brand) out.push(brand);
  for (const k of keywords) if (k && title.includes(k.toLowerCase())) out.push(k);
  return [...new Set(out)].slice(0, 3);
}

function interestScore(it, terms) {
  const hay = `${it.title} ${it.summary || ""} ${sourceInfo(it.source).name}`.toLowerCase();
  return terms.reduce((s, t) => s + (t && hay.includes(t.toLowerCase()) ? 1 : 0), 0);
}

/** Generic "how good is this deal" score for the default picks. */
function valueScore(it, today = todayIso()) {
  let s = 0;
  if (it.price_krw === 0) s += 2;
  if (it.discount_pct) s += it.discount_pct / 25;
  if (it.ends && daysLeft(it.ends, today) <= 7) s += 1;
  if (it.summary) s += 0.3;
  if (it.status === "new") s += 0.5;
  return s;
}

/**
 * Representative deals. With interest terms: deals matching them, best first ("interest").
 * Without terms, or when nothing matches: the best deals overall ("generic").
 */
function pickDeals(pool, interests, n = PICK_COUNT, today = todayIso()) {
  const seen = new Set();
  const open = visibleItems(pool, today).filter((i) => i.status !== "ignored" && !seen.has(i.id) && seen.add(i.id));
  const terms = (interests && interests.terms) || [];
  const byValue = (a, b) => valueScore(b, today) - valueScore(a, today);
  if (terms.length) {
    const hits = open.map((i) => [i, interestScore(i, terms)]).filter(([, s]) => s > 0)
      .sort((a, b) => b[1] - a[1] || byValue(a[0], b[0])).map(([i]) => i);
    if (hits.length) return { mode: "interest", items: hits.slice(0, n) };
  }
  return { mode: "generic", items: open.sort(byValue).slice(0, n) };
}

/** Link groups, those matching interest terms first; each group gets a match count. */
function rankLinks(groups, terms = []) {
  const low = terms.map((t) => t.toLowerCase());
  const score = (g) => low.filter((t) => [...g.tags, g.name, ...g.links.map((l) => `${l.title} ${l.note}`)]
    .some((x) => x.toLowerCase().includes(t) || t.includes(x.toLowerCase()))).length;
  return groups.map((g, i) => ({ ...g, match: score(g), order: i }))
    .sort((a, b) => b.match - a.match || a.order - b.order);
}

function linksHtml(groups) {
  return groups.map((g) => `<div class="link-group${g.match ? " match" : ""}">
    <h4>${esc(g.name)}${g.match ? '<span class="badge-new">관심</span>' : ""}</h4>
    <div class="link-list">${g.links.map((l) => `<a class="link-card" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">
      <b>${esc(l.title)}</b>${l.note ? `<span>${esc(l.note)}</span>` : ""}<i>↗</i></a>`).join("")}</div>
  </div>`).join("");
}

async function initFeed() {
  const ui = { cat: "*", status: "active", q: "", shown: PAGE };
  let feed = { run_at: null, items: [], pending: [], bought: [], recent: [] }, cats = {}, runs = null, config = null;
  let interests = emptyInterests(), linkGroups = [], requests = { requests: [] };
  const $ = (id) => document.getElementById(id);
  const list = $("list");

  async function load() {
    const [feedRes, runsRes, cfgRes, intRes, linkRes, reqRes] = await Promise.allSettled([
      readFile("data/feed.json"), readFile("data/runs.json"), readFile("data/config.json"),
      readFile("data/interests.json"), readFile("data/links.json"), readFile("data/requests.json")]);
    if (feedRes.status === "rejected") throw feedRes.reason;
    feed = { run_at: null, items: [], pending: [], bought: [], recent: [], ...feedRes.value.data };
    runs = runsRes.status === "fulfilled" ? runsRes.value.data : null;
    if (cfgRes.status === "fulfilled") {
      config = cfgRes.value.data;
      cats = {};
      for (const c of config.categories || []) cats[c.id] = c.name;
    }
    interests = intRes.status === "fulfilled" ? { ...emptyInterests(), ...intRes.value.data } : emptyInterests();
    linkGroups = linkRes.status === "fulfilled" ? linkRes.value.data.groups || [] : [];
    requests = reqRes.status === "fulfilled" ? reqRes.value.data : { requests: [] };
    drawRequest();
    renderRun(runs, feed, config);
    renderStats(feed, runs);
    fillCategories();
    $("trend").innerHTML = runChartSvg(runs);
    draw();
  }

  function fillCategories() {
    const tabs = categoryTabs(cats, visibleItems(feed.items));
    if (!tabs.some((t) => t.id === ui.cat)) ui.cat = "*";
    $("cat-tabs").replaceChildren(...tabs.map((t) => h("button", {
      type: "button", role: "tab", class: `cat-tab${t.id === ui.cat ? " on" : ""}`, "aria-selected": String(t.id === ui.cat),
      onclick: () => { ui.cat = t.id; ui.shown = PAGE; fillCategories(); draw(); },
    }, t.name, h("span", { class: "n" }, String(t.count)))));
  }

  async function refresh(manual) {
    const btn = $("refresh");
    btn.disabled = true; btn.textContent = "불러오는 중…";
    const before = runs && runs.runs && runs.runs[0] && runs.runs[0].at;
    try {
      await load();
      const after = runs && runs.runs && runs.runs[0] && runs.runs[0].at;
      if (after && after !== before && before) toast(`새 실행 결과로 갱신했습니다 (${fmtDateTime(after)})`);
      else if (manual) toast("최신 상태입니다");
    } catch (e) {
      if (manual) toast(`불러오지 못했습니다: ${e.message}`, "error");
    } finally {
      btn.disabled = false; btn.textContent = "↻ 게시 데이터 새로고침";
    }
  }

  // Auto refresh: poll the run log; when a newer run landed, reload everything.
  async function checkForUpdate() {
    if (document.hidden) return;
    try {
      const latest = (await readFile("data/runs.json")).data;
      const at = latest.runs && latest.runs[0] && latest.runs[0].at;
      const current = runs && runs.runs && runs.runs[0] && runs.runs[0].at;
      if (at && at !== current) await refresh(false);
    } catch (e) { /* offline or rate-limited: try again next tick */ }
  }
  setInterval(checkForUpdate, REFRESH_MS);
  setInterval(() => { if (openRequest(requests)) checkForUpdate(); }, 60 * 1000); // faster while waiting
  document.addEventListener("visibilitychange", checkForUpdate);

  $("refresh").addEventListener("click", () => refresh(true));

  function drawRequest() {
    const req = openRequest(requests);
    const btn = $("request-run"), note = $("request-note");
    btn.disabled = !!req;
    btn.textContent = req ? "⏳ 찾는 중 (요청됨)" : "⚡ 지금 새로 찾기";
    note.hidden = !req;
    note.innerHTML = requestNoteHtml(req);
  }

  $("request-run").addEventListener("click", async () => {
    const req = { id: `r${Date.now()}`, requested_at: localIso(), status: "open", done_at: null };
    const prev = requests;
    requests = { requests: [...(requests.requests || []), req] };
    drawRequest();
    try {
      await updateFile("data/requests.json", (data) => {
        const list = (data && data.requests) || [];
        if (openRequest(data)) return false; // someone already asked; nothing to add
        return { requests: [...list, req].slice(-50) };
      }, "ui: request run");
      toast("요청했습니다. 새 결과가 나오면 이 화면이 자동으로 바뀝니다");
    } catch (e) {
      requests = prev; drawRequest();
      toast(`요청 실패: ${e.message}`, "error");
    }
  });
  $("status").addEventListener("change", (e) => { ui.status = e.target.value; ui.shown = PAGE; draw(); });
  $("q").addEventListener("input", (e) => { ui.q = e.target.value; ui.shown = PAGE; draw(); });
  $("more").addEventListener("click", () => { ui.shown += PAGE; draw(); });

  const findItem = (id) => feed.items.find((i) => i.id === id) || (feed.recent || []).find((i) => i.id === id);
  const isSaved = (id) => interests.saved.some((s) => s.id === id);

  async function toggleInterest(item) {
    const saving = !isSaved(item.id);
    const cat = ((config && config.categories) || []).find((c) => c.id === item.category);
    const learned = saving ? deriveTerms(item, cat ? cat.keywords : []) : [];
    const prev = JSON.parse(JSON.stringify(interests));
    const apply = (data) => {
      data.terms = data.terms || []; data.saved = data.saved || [];
      if (saving) {
        data.saved = [{ id: item.id, title: item.title, url: item.url, source: item.source, category: item.category, saved_at: todayIso() },
          ...data.saved.filter((s) => s.id !== item.id)].slice(0, 50);
        data.terms = [...new Set([...data.terms, ...learned])].slice(0, 30);
      } else {
        data.saved = data.saved.filter((s) => s.id !== item.id);
      }
      return data;
    };
    interests = apply(interests); draw();
    try {
      await updateFile("data/interests.json", (data) => apply({ ...emptyInterests(), ...data }),
        `ui: ${saving ? "save" : "unsave"} interest ${item.id}`);
      toast(saving
        ? (learned.length ? `관심에 저장했습니다. 다음부터 '${learned.join(" · ")}' 위주로 보여줍니다` : "관심에 저장했습니다")
        : "관심에서 뺐습니다 (관심 키워드는 설정에서 지울 수 있습니다)");
    } catch (e) {
      interests = prev; draw();
      toast(`저장 실패: ${e.message}`, "error");
    }
  }

  async function onCardClick(ev) {
    const btn = ev.target.closest("button[data-act]");
    if (!btn) return;
    const id = btn.closest("article").dataset.id;
    const item = findItem(id);
    if (!item) return;
    if (btn.dataset.act === "interest") return toggleInterest(item);
    const next = item.status === btn.dataset.act ? "seen" : btn.dataset.act;
    const prev = item.status;
    item.status = next; draw();
    try {
      await updateFile("data/feed.json", (data) => {
        const target = (data.items || []).find((i) => i.id === id);
        if (!target) throw new Error("새 실행으로 목록이 바뀌었습니다. 새로고침하세요");
        target.status = next;
        // keep the notification queue in step so 무시 also stops a pending digest
        for (const p of data.pending || []) if (p.id === id) p.status = next;
      }, `ui: mark ${id} ${next}`);
      toast(next === "bought" ? "샀음으로 표시했습니다" : next === "ignored" ? "무시했습니다" : "표시를 해제했습니다");
      renderStats(feed, runs);
    } catch (e) {
      item.status = prev; draw();
      toast(`저장 실패: ${e.message}`, "error");
    }
  }
  list.addEventListener("click", onCardClick);
  $("pick-list").addEventListener("click", onCardClick);

  /** Default view only (no search, no filters): representative or interest-based picks + curated links. */
  function drawPicks(today) {
    const isDefault = !ui.q.trim() && ui.cat === "*" && ui.status === "active";  // picks only on the 전체 tab
    $("picks").hidden = !isDefault;
    if (!isDefault) return;
    const onPage = new Set(feed.items.map((i) => i.id));
    const picks = pickDeals([...feed.items, ...(feed.recent || [])], interests, PICK_COUNT, today);
    const terms = interests.terms;
    const interestMode = picks.mode === "interest";
    $("picks-kicker").textContent = interestMode ? "MY PICKS" : "PICKS";
    $("picks-title").textContent = interestMode ? "관심 딜" : "대표 딜";
    $("picks-note").innerHTML = interestMode
      ? `관심: ${terms.map((t) => `<span class="chip">${esc(t)}</span>`).join(" ")} · <a href="settings.html#interests">관심 키워드 고치기</a>`
      : terms.length
        ? `관심 키워드(${terms.map(esc).join(" · ")})에 맞는 딜이 아직 없어 최근 딜 중 혜택이 큰 것을 골랐습니다.`
        : "최근 딜 중 혜택이 큰 것을 골랐습니다. 카드의 <b>☆ 관심</b>을 누르면 다음부터 그쪽 위주로 보여줍니다.";
    $("pick-list").innerHTML = picks.items.length
      ? picks.items.map((it) => dealCardHtml(it, cats[it.category] || it.category, today,
          { saved: isSaved(it.id), marks: onPage.has(it.id) })).join("")
      : '<p class="muted">아직 보여줄 딜이 없습니다. 아래 모아보기에서 바로 둘러보세요.</p>';
    $("links").innerHTML = linksHtml(rankLinks(linkGroups, terms));
  }

  function draw() {
    const allowed = STATUS_FILTERS[ui.status];
    const today = todayIso();
    drawPicks(today);
    const rows = visibleItems(feed.items, today).filter((i) =>
      (ui.cat === "*" || i.category === ui.cat) && allowed.includes(i.status) && matchesQuery(i, ui.q));
    $("result-count").textContent = `THIS RUN / ${String(rows.length).padStart(2, "0")}`;
    if (rows.length) {
      list.innerHTML = rows.slice(0, ui.shown).map((it) =>
        dealCardHtml(it, cats[it.category] || it.category, today, { saved: isSaved(it.id) })).join("");
    } else {
      const filtered = feed.items.length > 0;
      list.innerHTML = `<div class="empty-state">
        <h3>${filtered ? "조건에 맞는 딜이 없습니다." : feed.run_at ? "이번 실행에서 새로 잡힌 딜이 없습니다." : "아직 실행 결과가 없습니다."}</h3>
        <p>${filtered ? "검색어나 분야·상태 필터를 바꿔 보세요."
          : feed.run_at ? `${esc(fmtDateTime(feed.run_at))} 실행에서 조건에 맞는 새 딜이 없었습니다. 위의 대표 딜과 모아보기를 둘러보거나, 키워드·조건을 넓히려면 설정에서 바꾸세요.`
          : "Codex가 처음 실행되면 이 화면에 결과가 나타납니다. 그 전에는 위의 모아보기 링크를 둘러보세요."}</p>
        <a class="request-button" href="${filtered || feed.run_at ? "settings.html" : "guide.html"}">${filtered || feed.run_at ? "검색 조건 바꾸기 ↗" : "사용 가이드 보기 ↗"}</a>
      </div>`;
    }
    $("more").hidden = rows.length <= ui.shown;
  }

  try { await load(); }
  catch (e) {
    list.innerHTML = `<div class="empty-state"><h3>피드를 불러오지 못했습니다.</h3><p>${esc(e.message)}</p></div>`;
    $("refresh-label").textContent = "불러오지 못했습니다";
  }
}

function renderRun(runs, feed, config) {
  const label = document.getElementById("refresh-label");
  const meta = document.getElementById("run");
  const banner = document.getElementById("banner");
  const last = runs && runs.runs && runs.runs[0];
  banner.hidden = true;
  if (config) document.getElementById("cadence").textContent =
    `${cadenceText(config)} · 새로고침은 게시된 결과만 다시 읽으며 사이트를 즉시 검색하지 않습니다.`;
  if (!last) {
    label.innerHTML = '<span class="status-dot stale"></span>첫 실행 대기';
    meta.textContent = "";
    banner.textContent = "딜봇이 아직 한 번도 실행되지 않았습니다. PC에 작업 스케줄러(DealBot tick)를 등록하고 한 번 실행하세요(가이드 참고).";
    banner.hidden = false;
    return;
  }
  const hours = (Date.now() - new Date(last.at)) / 3600000;
  label.innerHTML = `<span class="status-dot${hours >= ((config && config.schedule && config.schedule.interval_hours) || 24) + 3 ? " stale" : ""}"></span>최근 실행 ${esc(fmtDateTime(last.at))} KST`;
  meta.innerHTML = `${esc(fmtDateTime(feed.run_at || last.at))} 실행 · 찾음 ${last.found} · 새 딜 ${last.new} · 알림 ${last.notified}` +
    (last.errors.length ? ` · <span class="err" title="${esc(last.errors.map((e) => `${e.source}: ${e.error}`).join("\n"))}">오류 ${last.errors.length}</span>` : "");
  const interval = (config && config.schedule && config.schedule.interval_hours) || 24;
  if (hours >= interval + 3) { // same slack as the Actions fallback (due.py --slack 3)
    banner.textContent = `딜봇이 ${Math.floor(hours)}시간째 실행되지 않았습니다. PC의 DealBot tick 기록(.tmp/tick.log)과 GitHub Actions 로그를 확인하세요.`;
    banner.hidden = false;
  }
}

/** Month totals: found deals from the run log, bought deals from feed.bought + the current page. */
function monthStats(feed, runs, now = new Date()) {
  const ym = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const found = ((runs && runs.runs) || []).filter((r) => r.at.startsWith(ym)).reduce((s, r) => s + r.new, 0);
  const ids = new Set();
  const bought = [...feed.items.filter((i) => i.status === "bought"), ...(feed.bought || [])]
    .filter((i) => (i.found_at || "").startsWith(ym) && !ids.has(i.id) && ids.add(i.id));
  const saved = bought.reduce((s, i) => s + (i.original_price_krw != null && i.price_krw != null ? Math.max(0, i.original_price_krw - i.price_krw) : 0), 0);
  return { found, bought: bought.length, saved };
}

function renderStats(feed, runs) {
  const s = monthStats(feed, runs);
  document.getElementById("stats").innerHTML =
    `<div class="stat"><b>${s.found}건</b><span>이번 달 잡은 딜</span></div>` +
    `<div class="stat"><b>${s.bought}건</b><span>샀음</span></div>` +
    `<div class="stat"><b>${won(s.saved)}</b><span>아낀 금액(추정)</span></div>`;
}

// ------------------------------------------------------------------ settings page

const CHANNEL_TYPES = {
  slack: { label: "Slack", env: ["DEALBOT_SLACK_WEBHOOK"], target: "표시용 채널명 (예: #dealbot)" },
  discord: { label: "Discord", env: ["DEALBOT_DISCORD_WEBHOOK"], target: "표시용 채널명" },
  telegram: { label: "Telegram", env: ["DEALBOT_TELEGRAM_TOKEN", "DEALBOT_TELEGRAM_CHAT_ID"], target: "chat_id (비우면 DEALBOT_TELEGRAM_CHAT_ID 사용)" },
  ntfy: { label: "ntfy (폰 푸시)", env: ["DEALBOT_NTFY_TOPIC", "DEALBOT_NTFY_TOKEN (선택)"], target: "토픽명 (비우면 DEALBOT_NTFY_TOPIC 사용 · 공개 저장소면 비워 두기)" },
  pushover: { label: "Pushover (폰 푸시)", env: ["DEALBOT_PUSHOVER_TOKEN", "DEALBOT_PUSHOVER_USER"], target: "(사용 안 함)" },
  kakao: { label: "카카오톡 나에게 보내기", env: ["DEALBOT_KAKAO_REST_KEY", "DEALBOT_KAKAO_REFRESH_TOKEN"], target: "me" },
  email: { label: "이메일", env: ["DEALBOT_SMTP_HOST", "DEALBOT_SMTP_USER", "DEALBOT_SMTP_PASS", "DEALBOT_EMAIL_TO (선택)"], target: "받을 주소 (비우면 DEALBOT_EMAIL_TO)" },
};
const PRIORITIES = { instant: "즉시", daily: "하루 묶음", weekly: "주간 묶음" };

/** Chip-style list editor; mutates arr in place. */
function tagInput(arr, placeholder) {
  const input = h("input", { type: "text", placeholder, enterkeyhint: "done" });
  const wrap = h("div", { class: "tags", onclick: () => input.focus() });
  const add = () => {
    for (const part of input.value.split(",")) {
      const v = part.trim();
      if (v && !arr.includes(v)) arr.push(v);
    }
    input.value = ""; draw();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
    else if (e.key === "Backspace" && !input.value && arr.length) { arr.pop(); draw(); }
  });
  input.addEventListener("blur", add);
  function draw() {
    wrap.replaceChildren(...arr.map((v, i) => h("span", { class: "chip" }, v,
      h("button", { type: "button", "aria-label": `${v} 삭제`, onclick: (e) => { e.stopPropagation(); arr.splice(i, 1); draw(); } }, "×"))), input);
  }
  draw();
  return wrap;
}

function field(label, control, hint) {
  // A div, not a label: some controls (checkbox groups, tag inputs) contain their own labels.
  return h("div", { class: "field" }, h("span", null, label), control, hint ? h("small", null, hint) : null);
}

function numInput(obj, key, { min, max, nullable }) {
  return h("input", { type: "number", inputmode: "numeric", min, max, value: obj[key] ?? "",
    placeholder: nullable ? "제한 없음" : "",
    oninput: (e) => { const v = e.target.value.trim(); obj[key] = v === "" ? (nullable ? null : undefined) : Number(v); } });
}

function check(obj, key, label) {
  return h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!obj[key], onchange: (e) => (obj[key] = e.target.checked) }), label);
}

function setCheck(arr, value, label) {
  return h("label", { class: "check" }, h("input", { type: "checkbox", checked: arr.includes(value),
    onchange: (e) => { const i = arr.indexOf(value); if (e.target.checked && i < 0) arr.push(value); if (!e.target.checked && i >= 0) arr.splice(i, 1); } }), label);
}

async function initSettings() {
  const main = document.getElementById("forms");
  let cfg, nts, ints, schemas, original;
  const snapshot = () => ({ config: JSON.stringify(cfg), notifiers: JSON.stringify(nts), interests: JSON.stringify(ints) });
  try {
    const [c, n, sc, sn, si] = await Promise.all([readFile("data/config.json"), readFile("data/notifiers.json"),
      readFile("schemas/config.schema.json"), readFile("schemas/notifiers.schema.json"), readFile("schemas/interests.schema.json")]);
    const i = await readFile("data/interests.json").catch(() => ({ data: emptyInterests() }));
    cfg = c.data; nts = n.data; ints = { ...emptyInterests(), ...i.data };
    schemas = { config: sc.data, notifiers: sn.data, interests: si.data };
    original = snapshot();
  } catch (e) {
    main.innerHTML = `<p class="empty">설정을 불러오지 못했습니다: ${esc(e.message)}</p>`;
    return;
  }
  const fresh = new WeakSet(); // categories/channels added in this session: id still editable

  function sourceOptions() {
    return ["search", ...Object.keys(cfg.rss_feeds || {}).map((k) => `rss:${k}`), "epic_free"];
  }
  const sourceName = (s) => (s === "search" ? "웹 검색 (Codex)" : s === "epic_free" ? "에픽 무료게임" : `RSS ${s.slice(4)}`);

  function categoryCard(cat, idx) {
    const opts = [...new Set([...sourceOptions(), ...cat.sources])];
    return h("section", { class: `card cat${cat.enabled ? "" : " off"}` },
      h("div", { class: "row head" },
        h("input", { class: "name", type: "text", value: cat.name, placeholder: "카테고리 이름", oninput: (e) => (cat.name = e.target.value) }),
        check(cat, "enabled", "켜기"),
        h("button", { type: "button", class: "danger", onclick: () => { if (confirm(`'${cat.name}' 카테고리를 지울까요?`)) { cfg.categories.splice(idx, 1); draw(); } } }, "삭제")),
      fresh.has(cat) ? field("ID (영문 소문자·숫자·_-)", h("input", { type: "text", value: cat.id, oninput: (e) => (cat.id = e.target.value.trim()) }), "피드 항목이 이 ID로 분류됩니다. 저장 후엔 바꾸지 않는 게 좋습니다.") : null,
      field("키워드", tagInput(cat.keywords, "입력 후 Enter"), "RSS 소스는 키워드가 하나라도 들어간 글만 잡습니다."),
      field("제외어", tagInput(cat.exclude, "입력 후 Enter")),
      field("소스", h("div", { class: "checks" }, opts.map((s) => setCheck(cat.sources, s, sourceName(s))))),
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!cat.rss_all,
        onchange: (e) => { if (e.target.checked) cat.rss_all = true; else delete cat.rss_all; } }),
        "RSS 글 전부 받기 (키워드 검사 안 함, 핫딜 게시판용)"),
      h("div", { class: "row" },
        field("최소 할인율 %", numInput(cat, "min_discount_pct", { min: 0, max: 100, nullable: true })),
        field("최대 가격 (원)", numInput(cat, "max_price_krw", { min: 0, nullable: true }))),
      field("우선순위", h("select", { onchange: (e) => (cat.priority = e.target.value) },
        Object.entries(PRIORITIES).map(([v, l]) => h("option", { value: v, selected: cat.priority === v }, l)))));
  }

  function feedsEditor() {
    const rows = Object.entries(cfg.rss_feeds || {});
    const rename = (oldId, newId) => {
      newId = newId.trim();
      if (!newId || newId === oldId) return;
      cfg.rss_feeds = Object.fromEntries(Object.entries(cfg.rss_feeds).map(([k, v]) => [k === oldId ? newId : k, v]));
      for (const c of cfg.categories) c.sources = c.sources.map((s) => (s === `rss:${oldId}` ? `rss:${newId}` : s));
      draw();
    };
    return h("div", null,
      rows.map(([id, url]) => h("div", { class: "row feedrow" },
        h("input", { type: "text", value: id, class: "fid", onchange: (e) => rename(id, e.target.value) }),
        h("input", { type: "url", value: url, oninput: (e) => (cfg.rss_feeds[id] = e.target.value.trim()) }),
        h("button", { type: "button", class: "danger", onclick: () => { delete cfg.rss_feeds[id]; for (const c of cfg.categories) c.sources = c.sources.filter((s) => s !== `rss:${id}`); draw(); } }, "×"))),
      h("button", { type: "button", onclick: () => { let n = 1; while (cfg.rss_feeds[`feed${n}`]) n++; cfg.rss_feeds[`feed${n}`] = "https://"; draw(); } }, "+ RSS 추가"));
  }

  function scheduleEditor() {
    if (!cfg.quiet_hours) cfg.quiet_hours = null;
    const quietOn = !!cfg.quiet_hours;
    return h("div", null,
      field("자동 실행 간격 (시간)", numInput(cfg.schedule, "interval_hours", { min: 1, max: 168 }),
        "마지막 실행 후 이 시간이 지나면 다음 확인(15분마다) 때 자동으로 찾습니다. 피드의 '지금 새로 찾기'를 누르면 간격과 상관없이 바로 찾습니다."),
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: quietOn,
        onchange: (e) => { cfg.quiet_hours = e.target.checked ? { start: "23:00", end: "08:00" } : null; draw(); } }), "조용한 시간 (즉시 알림을 다음 실행으로 미룸)"),
      quietOn ? h("div", { class: "row" },
        field("시작", h("input", { type: "time", value: cfg.quiet_hours.start, onchange: (e) => (cfg.quiet_hours.start = e.target.value) })),
        field("끝", h("input", { type: "time", value: cfg.quiet_hours.end, onchange: (e) => (cfg.quiet_hours.end = e.target.value) }))) : null,
      field("검색 힌트 (Codex 웹 검색에 씀)", tagInput(cfg.search_hints, "입력 후 Enter")),
      field("마감까지 최소 남은 일수", numInput(cfg, "min_days_left", { min: 0, max: 365 }),
        "실행 시각 기준으로 마감일이 이 일수보다 가까운 딜은 잡지 않습니다. 이미 끝난 딜은 항상 빠집니다. 0이면 오늘 마감까지 포함. 마감일을 모르는 딜은 통과합니다."),
      h("div", { class: "row" },
        field("한 번에 보여줄 최대 건수", numInput(cfg, "feed_limit", { min: 10, max: 5000 })),
        field("중복 판정 보관 일수", numInput(cfg, "seen_ttl_days", { min: 1, max: 365 }))));
  }

  function channelCard(ch, idx) {
    const meta = CHANNEL_TYPES[ch.type] || { label: ch.type, env: [], target: "" };
    return h("section", { class: `card chan${ch.enabled ? "" : " off"}` },
      h("div", { class: "row head" },
        h("strong", { class: "name" }, meta.label, fresh.has(ch) ? null : h("small", null, ` (${ch.id})`)),
        check(ch, "enabled", "켜기"),
        h("button", { type: "button", class: "danger", onclick: () => { if (confirm(`'${ch.id}' 채널을 지울까요?`)) { nts.channels.splice(idx, 1); draw(); } } }, "삭제")),
      fresh.has(ch) ? field("ID", h("input", { type: "text", value: ch.id, oninput: (e) => (ch.id = e.target.value.trim()) })) : null,
      field("대상", h("input", { type: "text", value: ch.target, placeholder: meta.target, oninput: (e) => (ch.target = e.target.value.trim()) })),
      field("받을 우선순위", h("div", { class: "checks" }, Object.entries(PRIORITIES).map(([v, l]) => setCheck(ch.priorities, v, l)))),
      h("p", { class: "hint" }, "토큰은 여기 넣지 않습니다. Codex 시크릿(환경변수)에 넣으세요: ", meta.env.map((e, i) => [i ? ", " : "", h("code", null, e)])));
  }

  function formatEditor() {
    const f = nts.format;
    return h("div", null,
      check(f, "group_by_category", "카테고리별로 메시지 나누기"),
      check(f, "include_summary", "요약 포함"),
      h("div", { class: "row" },
        field("메시지당 최대 항목", numInput(f, "max_items_per_message", { min: 1, max: 20 })),
        field("피드 주소 (알림 하단 링크)", h("input", { type: "url", value: f.feed_url || "", oninput: (e) => (f.feed_url = e.target.value.trim()) }))));
  }

  function interestsEditor() {
    return h("div", null,
      field("관심 키워드", tagInput(ints.terms, "예: 네이버페이, 캐시백 (Enter)"),
        "피드 첫 화면의 '관심 딜'과 모아보기가 이 키워드 위주로 바뀝니다. Codex도 다음 검색부터 이 키워드를 먼저 찾습니다. 피드 카드의 ☆ 관심을 누르면 자동으로 추가됩니다."),
      field(`☆ 관심으로 저장한 딜 (${ints.saved.length})`, ints.saved.length
        ? h("div", { class: "saved-list" }, ints.saved.map((s, idx) => h("div", { class: "saved-row" },
            h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer" }, s.title),
            h("small", null, s.saved_at),
            h("button", { type: "button", class: "danger", "aria-label": "삭제", onclick: () => { ints.saved.splice(idx, 1); draw(); } }, "×"))))
        : h("p", { class: "hint" }, "아직 없습니다. 피드에서 마음에 드는 딜의 ☆ 관심을 누르세요.")));
  }

  function draw() {
    main.replaceChildren(...[
      h("h2", { id: "interests" }, "관심사"), h("section", { class: "card" }, interestsEditor()),
      h("h2", null, "카테고리"),
      cfg.categories.map(categoryCard),
      h("button", { type: "button", class: "add", onclick: () => {
        let n = cfg.categories.length + 1; while (cfg.categories.some((c) => c.id === `cat${n}`)) n++;
        const cat = { id: `cat${n}`, name: "새 카테고리", enabled: true, keywords: [], exclude: [], sources: ["search"], min_discount_pct: null, max_price_krw: null, priority: "instant" };
        fresh.add(cat); cfg.categories.push(cat); draw();
      } }, "+ 카테고리 추가"),
      h("h2", null, "RSS 피드"), h("section", { class: "card" }, feedsEditor()),
      h("h2", null, "실행·기타"), h("section", { class: "card" }, scheduleEditor()),
      h("h2", null, "알림 채널"),
      nts.channels.map(channelCard),
      h("div", { class: "row" },
        h("select", { id: "newtype" }, Object.entries(CHANNEL_TYPES).map(([v, m]) => h("option", { value: v }, m.label))),
        h("button", { type: "button", class: "add", onclick: () => {
          const type = document.getElementById("newtype").value;
          let id = type, n = 2; while (nts.channels.some((c) => c.id === id)) id = `${type}${n++}`;
          const ch = { id, type, enabled: true, target: "", priorities: ["instant"] };
          fresh.add(ch); nts.channels.push(ch); draw();
        } }, "+ 채널 추가")),
      h("h2", null, "메시지 형식"), h("section", { class: "card" }, formatEditor())].flat());
  }

  function crossCheck() {
    const errs = [];
    const ids = cfg.categories.map((c) => c.id);
    ids.forEach((id, i) => { if (ids.indexOf(id) !== i) errs.push(`카테고리 ID 중복: ${id}`); });
    const chIds = nts.channels.map((c) => c.id);
    chIds.forEach((id, i) => { if (chIds.indexOf(id) !== i) errs.push(`채널 ID 중복: ${id}`); });
    for (const c of cfg.categories) for (const s of c.sources)
      if (s.startsWith("rss:") && !(s.slice(4) in (cfg.rss_feeds || {}))) errs.push(`${c.name}: 없는 RSS ${s}`);
    const secret = /token|webhook|secret|password|api[_-]?key|hooks\.slack\.com/i;
    for (const ch of nts.channels) if (secret.test(ch.target)) errs.push(`${ch.id}: 대상에 토큰·웹훅 주소를 넣지 마세요 (Codex 시크릿에 넣기)`);
    return errs;
  }

  document.getElementById("save").addEventListener("click", async (ev) => {
    const btn = ev.currentTarget;
    const out = document.getElementById("result");
    document.activeElement && document.activeElement.blur(); // flush pending tag input
    const errors = [...validate(schemas.config, cfg).map((e) => `config ${e}`),
      ...validate(schemas.notifiers, nts).map((e) => `notifiers ${e}`),
      ...validate(schemas.interests, ints).map((e) => `관심사 ${e}`), ...crossCheck()];
    if (errors.length) {
      out.className = "result error";
      out.replaceChildren(h("b", null, "저장하지 않았습니다. 고칠 곳:"), h("ul", null, errors.map((e) => h("li", null, e))));
      return;
    }
    const jobs = [];
    if (JSON.stringify(cfg) !== original.config) jobs.push(["data/config.json", cfg, "ui: update config"]);
    if (JSON.stringify(nts) !== original.notifiers) jobs.push(["data/notifiers.json", nts, "ui: update notifiers"]);
    if (JSON.stringify(ints) !== original.interests) jobs.push(["data/interests.json", ints, "ui: update interests"]);
    if (!jobs.length) { out.className = "result"; out.textContent = "바뀐 내용이 없습니다."; return; }
    btn.disabled = true; out.className = "result"; out.textContent = "저장 중…";
    try {
      // These files belong to the UI (Codex never writes them), so a conflict just retries with the fresh sha.
      for (const [path, obj, msg] of jobs) await updateFile(path, () => obj, msg);
      original = snapshot();
      out.className = "result ok";
      out.replaceChildren(h("b", null, "저장했습니다."), h("p", null, "다음 실행부터 반영됩니다."));
      draw();
    } catch (e) {
      out.className = "result error"; out.textContent = `저장 실패: ${e.message}`;
    } finally { btn.disabled = false; }
  });

  draw();
}

/**
 * Ask for the PAT once, the first time something needs to be saved (or after it was rejected).
 * The token can't ship with the page: Pages is public, so anyone could use it.
 * Resolves true when a working token is stored, false if the user cancels.
 */
function askToken(reason) {
  return new Promise((resolve) => {
    const input = h("input", { type: "password", autocomplete: "off", placeholder: "github_pat_…" });
    const msg = h("p", { class: "muted" });
    const dlg = h("dialog", { class: "tokdlg" },
      h("form", { method: "dialog", onsubmit: async (e) => {
        e.preventDefault();
        const value = input.value.trim();
        if (!value) return;
        store(LS.token, value);
        msg.textContent = "확인 중…";
        try {
          await gh("");
          dlg.close(); dlg.remove(); resolve(true);
        } catch (err) {
          store(LS.token, null);
          msg.textContent = `토큰을 쓸 수 없습니다: ${err.message}`;
        }
      } },
        h("b", null, "GitHub 저장 권한이 필요합니다"),
        h("p", null, reason || "변경 내용을 저장소에 커밋하려면 토큰이 한 번 필요합니다. 이 브라우저에만 기억합니다."),
        h("p", { class: "muted" }, `저장소 ${repo()} · Fine-grained PAT, Contents: Read and write`),
        input, msg,
        h("div", { class: "row" },
          h("button", { type: "submit", class: "primary" }, "확인"),
          h("button", { type: "button", onclick: () => { dlg.close(); dlg.remove(); resolve(false); } }, "취소"))));
    document.body.append(dlg);
    dlg.showModal();
    input.focus();
  });
}

// ------------------------------------------------------------------ guide page (MANUAL.md)
// A small Markdown renderer for the subset MANUAL.md uses: headings, paragraphs, lists,
// tables, fenced code, blockquotes, rules, and inline code/bold/links. No CDN by design.

/** GitHub-style heading anchor: lowercase, drop punctuation, spaces -> '-'. */
function slug(text) {
  return text.trim().toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu, "").replace(/\s/g, "-");
}

function mdInline(s) {
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
  s = esc(s)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) => {
      let url = href.replace(/&amp;/g, "&");
      if (/^[\w./-]+\.md(#.*)?$/.test(url) && !url.startsWith("MANUAL.md")) {
        url = `https://github.com/${repo()}/blob/${BRANCH}/${url}`; // other repo docs open on GitHub
      } else if (url.startsWith("MANUAL.md#")) url = url.slice(9);
      if (!/^(https?:\/\/|#)/.test(url)) return label;
      const ext = url.startsWith("http") ? ' target="_blank" rel="noopener noreferrer"' : "";
      return `<a href="${esc(url)}"${ext}>${label}</a>`;
    });
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[+i])}</code>`);
}

function renderMarkdown(md) {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0;
  const isTableSep = (l) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(l);
  const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    let m;
    if ((m = line.match(/^```/))) {
      const buf = [];
      for (i++; i < lines.length && !/^```/.test(lines[i]); i++) buf.push(lines[i]);
      i++;
      out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`);
    } else if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
      const n = m[1].length;
      out.push(`<h${n} id="${esc(slug(m[2].replace(/[`*]/g, "")))}">${mdInline(m[2])}</h${n}>`);
      i++;
    } else if (/^(-{3,}|\*{3,})\s*$/.test(line)) {
      out.push("<hr>"); i++;
    } else if (line.startsWith(">")) {
      const buf = [];
      for (; i < lines.length && lines[i].startsWith(">"); i++) buf.push(lines[i].replace(/^>\s?/, ""));
      out.push(`<blockquote>${renderMarkdown(buf.join("\n"))}</blockquote>`);
    } else if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const head = cells(line);
      const rows = [];
      for (i += 2; i < lines.length && lines[i].includes("|") && lines[i].trim(); i++) rows.push(cells(lines[i]));
      out.push(`<div class="tablewrap"><table><thead><tr>${head.map((c) => `<th>${mdInline(c)}</th>`).join("")}</tr></thead><tbody>` +
        rows.map((r) => `<tr>${r.map((c) => `<td>${mdInline(c)}</td>`).join("")}</tr>`).join("") + "</tbody></table></div>");
    } else if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      out.push(renderList(lines, i, (next) => (i = next)));
    } else {
      const buf = [];
      for (; i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|>|\s*([-*]|\d+\.)\s|(-{3,})\s*$)/.test(lines[i]); i++) buf.push(lines[i].trim());
      out.push(`<p>${mdInline(buf.join(" "))}</p>`);
    }
  }
  return out.join("\n");
}

/** Lists with nesting by indentation; continuation lines join the current item. */
function renderList(lines, start, setIndex) {
  const indentOf = (l) => l.match(/^\s*/)[0].length;
  const base = indentOf(lines[start]);
  const ordered = /^\s*\d+\./.test(lines[start]);
  const items = [];
  let i = start;
  while (i < lines.length) {
    const l = lines[i];
    if (!l.trim()) {
      // a blank line ends the list unless the next line continues it at this level or deeper
      if (i + 1 < lines.length && indentOf(lines[i + 1]) > base && lines[i + 1].trim()) { i++; continue; }
      break;
    }
    const ind = indentOf(l);
    const bullet = l.match(/^\s*([-*]|\d+\.)\s+(.*)$/);
    if (bullet && ind === base) { items.push({ text: [bullet[2]], children: [] }); i++; continue; }
    if (ind > base && items.length) {
      if (bullet) { items[items.length - 1].children.push(renderList(lines, i, (n) => (i = n))); continue; }
      if (/^\s*```/.test(l)) {
        const buf = [];
        for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) buf.push(lines[i].slice(ind));
        i++;
        items[items.length - 1].children.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`);
        continue;
      }
      items[items.length - 1].text.push(l.trim()); i++; continue;
    }
    break;
  }
  setIndex(i);
  const tag = ordered ? "ol" : "ul";
  return `<${tag}>${items.map((it) => `<li>${mdInline(it.text.join(" "))}${it.children.join("")}</li>`).join("")}</${tag}>`;
}

async function initGuide() {
  const el = document.getElementById("guide");
  try {
    el.innerHTML = renderMarkdown(await readText("MANUAL.md"));
    const toc = [...el.querySelectorAll("h2")].map((hd) => h("a", { href: `#${hd.id}` }, hd.textContent));
    document.getElementById("toc").replaceChildren(...toc);
    if (location.hash) document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView();
  } catch (e) {
    el.innerHTML = `<p class="empty">가이드를 불러오지 못했습니다: ${esc(e.message)}</p>`;
  }
}

// ------------------------------------------------------------------ boot

document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  const init = { settings: initSettings, guide: initGuide }[page] || initFeed;
  init().catch((e) => toast(e.message, "error"));
});
