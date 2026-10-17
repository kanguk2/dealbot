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
const RSS_LABEL = { ruliweb: "루리웹", ppomppu: "뽐뿌", quasarzone: "퀘이사존", algumon: "알구몬" };

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

const PAGE = 60;
const STATUS_FILTERS = { active: ["new", "seen"], bought: ["bought"], ignored: ["ignored"], all: ["new", "seen", "bought", "ignored"] };

async function initFeed() {
  const ui = { cat: "*", status: "active", shown: PAGE };
  let feed = { items: [] }, cats = {};
  const list = document.getElementById("list");

  const [feedRes, runsRes, cfgRes] = await Promise.allSettled([
    readFile("data/feed.json"), readFile("data/runs.json"), readFile("data/config.json")]);
  if (feedRes.status === "rejected") {
    list.innerHTML = `<p class="empty">피드를 불러오지 못했습니다: ${esc(feedRes.reason.message)}</p>`;
    return;
  }
  feed = feedRes.value.data;
  if (cfgRes.status === "fulfilled") for (const c of cfgRes.value.data.categories || []) cats[c.id] = c.name;
  renderRun(runsRes.status === "fulfilled" ? runsRes.value.data : null);
  renderStats(feed.items);

  const catIds = [...new Set([...Object.keys(cats), ...feed.items.map((i) => i.category)])];
  const tabs = document.getElementById("cats");
  tabs.replaceChildren(...[["*", "전체"], ...catIds.map((id) => [id, cats[id] || id])].map(([id, name]) =>
    h("button", { class: id === ui.cat ? "on" : "", onclick: () => { ui.cat = id; ui.shown = PAGE; draw(); } }, name)));

  const statusSel = document.getElementById("status");
  statusSel.addEventListener("change", () => { ui.status = statusSel.value; ui.shown = PAGE; draw(); });
  document.getElementById("more").addEventListener("click", () => { ui.shown += PAGE; draw(); });

  list.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button[data-act]");
    if (!btn) return;
    const id = btn.closest("article").dataset.id;
    const item = feed.items.find((i) => i.id === id);
    const next = item.status === btn.dataset.act ? "seen" : btn.dataset.act;
    const prev = item.status;
    item.status = next; draw();
    try {
      await updateFile("data/feed.json", (data) => {
        const target = (data.items || []).find((i) => i.id === id);
        if (!target) throw new Error("항목이 피드에서 사라졌습니다 (오래돼 잘렸을 수 있음)");
        target.status = next;
      }, `ui: mark ${id} ${next}`);
      toast(next === "bought" ? "샀음으로 표시했습니다" : next === "ignored" ? "무시했습니다" : "표시를 해제했습니다");
      renderStats(feed.items);
    } catch (e) {
      item.status = prev; draw();
      toast(`저장 실패: ${e.message}`, "error");
    }
  });

  function draw() {
    for (const b of tabs.children) b.classList.toggle("on", b.textContent === (ui.cat === "*" ? "전체" : cats[ui.cat] || ui.cat));
    const allowed = STATUS_FILTERS[ui.status];
    const rows = feed.items.filter((i) => (ui.cat === "*" || i.category === ui.cat) && allowed.includes(i.status));
    const today = new Date(); today.setHours(0, 0, 0, 0);
    list.innerHTML = rows.slice(0, ui.shown).map((it) => {
      let due = "";
      if (it.ends) {
        const days = Math.round((new Date(it.ends + "T00:00:00") - today) / 86400000);
        due = `<span class="due${days <= 2 ? " soon" : ""}">~${mmdd(it.ends)}${days >= 0 ? ` (D-${days})` : " (마감)"}</span>`;
      }
      const price = priceText(it);
      return `<article class="card s-${esc(it.status)}" data-id="${esc(it.id)}">
        <div class="meta">${esc(cats[it.category] || it.category)} · ${esc(sourceLabel(it.source))} · ${esc(fmtDateTime(it.found_at))}${it.status === "new" ? ' <span class="badge">NEW</span>' : ""}</div>
        <a class="title" href="${esc(it.url)}" target="_blank" rel="noopener noreferrer">${esc(it.title)}</a>
        ${price || due ? `<div class="price">${price} ${due}</div>` : ""}
        ${it.summary ? `<p class="summary">${esc(it.summary)}</p>` : ""}
        <div class="actions">
          <button data-act="bought" class="${it.status === "bought" ? "on" : ""}">샀음</button>
          <button data-act="ignored" class="${it.status === "ignored" ? "on" : ""}">무시</button>
        </div></article>`;
    }).join("") || `<p class="empty">표시할 딜이 없습니다.</p>`;
    document.getElementById("more").hidden = rows.length <= ui.shown;
    document.getElementById("count").textContent = `${rows.length}건`;
  }
  draw();
}

function renderRun(runs) {
  const el = document.getElementById("run");
  const banner = document.getElementById("banner");
  const last = runs && runs.runs && runs.runs[0];
  if (!last) {
    el.textContent = "아직 실행 기록이 없습니다.";
    banner.textContent = "딜봇이 한 번도 실행되지 않았습니다. Codex Automation 설정을 확인하세요.";
    banner.hidden = false;
    return;
  }
  const hours = (Date.now() - new Date(last.at)) / 3600000;
  el.innerHTML = `마지막 실행 <b>${esc(fmtDateTime(last.at))}</b> · 찾음 ${last.found} · 새 딜 ${last.new} · 알림 ${last.notified}` +
    (last.errors.length ? ` · <span class="err" title="${esc(last.errors.map((e) => `${e.source}: ${e.error}`).join("\n"))}">오류 ${last.errors.length}</span>` : "");
  if (hours >= 24) {
    banner.textContent = `딜봇이 ${Math.floor(hours)}시간째 실행되지 않았습니다. Codex Automation 실행 기록을 확인하세요.`;
    banner.hidden = false;
  }
}

function renderStats(items) {
  const now = new Date();
  const ym = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const month = items.filter((i) => (i.found_at || "").startsWith(ym));
  const bought = month.filter((i) => i.status === "bought");
  const saved = bought.reduce((s, i) => s + (i.original_price_krw != null && i.price_krw != null ? Math.max(0, i.original_price_krw - i.price_krw) : 0), 0);
  document.getElementById("stats").textContent =
    `이번 달 ${month.length}건 잡음 · 샀음 ${bought.length}건 · 아낀 금액(추정) ${won(saved)}`;
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
  let cfg, nts, schemas, original;
  try {
    const [c, n, sc, sn] = await Promise.all([readFile("data/config.json"), readFile("data/notifiers.json"),
      readFile("schemas/config.schema.json"), readFile("schemas/notifiers.schema.json")]);
    cfg = c.data; nts = n.data; schemas = { config: sc.data, notifiers: sn.data };
    original = { config: JSON.stringify(cfg), notifiers: JSON.stringify(nts), times: JSON.stringify(cfg.schedule.times) };
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
    const times = cfg.schedule.times;
    if (!cfg.quiet_hours) cfg.quiet_hours = null;
    const quietOn = !!cfg.quiet_hours;
    return h("div", null,
      field("실행 시간 (Codex Automation 주기와 맞추세요)", h("div", { class: "times" },
        times.map((t, i) => h("span", { class: "time" },
          h("input", { type: "time", value: t, onchange: (e) => (times[i] = e.target.value) }),
          h("button", { type: "button", "aria-label": "삭제", onclick: () => { times.splice(i, 1); draw(); } }, "×"))),
        h("button", { type: "button", onclick: () => { times.push("12:00"); draw(); } }, "+"))),
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: quietOn,
        onchange: (e) => { cfg.quiet_hours = e.target.checked ? { start: "23:00", end: "08:00" } : null; draw(); } }), "조용한 시간 (즉시 알림을 다음 실행으로 미룸)"),
      quietOn ? h("div", { class: "row" },
        field("시작", h("input", { type: "time", value: cfg.quiet_hours.start, onchange: (e) => (cfg.quiet_hours.start = e.target.value) })),
        field("끝", h("input", { type: "time", value: cfg.quiet_hours.end, onchange: (e) => (cfg.quiet_hours.end = e.target.value) }))) : null,
      field("검색 힌트 (Codex 웹 검색에 씀)", tagInput(cfg.search_hints, "입력 후 Enter")),
      h("div", { class: "row" },
        field("피드 보관 건수", numInput(cfg, "feed_limit", { min: 10, max: 5000 })),
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

  function draw() {
    main.replaceChildren(...[
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
    cfg.schedule.times = [...new Set(cfg.schedule.times.filter(Boolean))].sort();
    const errors = [...validate(schemas.config, cfg).map((e) => `config ${e}`),
      ...validate(schemas.notifiers, nts).map((e) => `notifiers ${e}`), ...crossCheck()];
    if (errors.length) {
      out.className = "result error";
      out.replaceChildren(h("b", null, "저장하지 않았습니다. 고칠 곳:"), h("ul", null, errors.map((e) => h("li", null, e))));
      return;
    }
    const jobs = [];
    if (JSON.stringify(cfg) !== original.config) jobs.push(["data/config.json", cfg, "ui: update config"]);
    if (JSON.stringify(nts) !== original.notifiers) jobs.push(["data/notifiers.json", nts, "ui: update notifiers"]);
    if (!jobs.length) { out.className = "result"; out.textContent = "바뀐 내용이 없습니다."; return; }
    btn.disabled = true; out.className = "result"; out.textContent = "저장 중…";
    try {
      // These files belong to the UI (Codex never writes them), so a conflict just retries with the fresh sha.
      for (const [path, obj, msg] of jobs) await updateFile(path, () => obj, msg);
      const timesChanged = JSON.stringify(cfg.schedule.times) !== original.times;
      original = { config: JSON.stringify(cfg), notifiers: JSON.stringify(nts), times: JSON.stringify(cfg.schedule.times) };
      out.className = "result ok";
      out.replaceChildren(h("b", null, "저장했습니다."), timesChanged
        ? h("p", null, `실행 시간을 ${cfg.schedule.times.join(", ")}(으)로 바꿨습니다. Codex Automation 주기도 같이 바꾸세요.`)
        : h("p", null, "실행 시간을 바꿨다면 Codex Automation 주기도 바꾸세요."));
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

// ------------------------------------------------------------------ boot

document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  (page === "settings" ? initSettings() : initFeed()).catch((e) => toast(e.message, "error"));
});
