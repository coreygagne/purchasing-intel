/* Purchasing research UI. Vanilla JS, no build step.
   All text that comes from the web is inserted as text nodes, never HTML. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const state = { status: null, job: null, comparison: null, tab: "suppliers", history: null };

// ------------------------------------------------------------------ DOM helpers
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "html") throw new Error("raw html not allowed");
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
function safeUrl(u) {
  try { const x = new URL(u); return (x.protocol === "http:" || x.protocol === "https:") ? x.href : null; }
  catch { return null; }
}
// `img`: the listing's picture, shown when the link is hovered or focused
function link(url, text, cls, img) {
  const u = safeUrl(url);
  if (!u) return h("span", { class: cls }, text || url || "");
  const pic = img && /^https?:\/\//.test(img) ? img : null;
  return h("a", { href: u, target: "_blank", rel: "noopener noreferrer", class: cls, "data-img": pic }, text || hostOf(u));
}
function hostOf(u) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } }
async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  return { ok: res.ok, status: res.status, body };
}

// ------------------------------------------------------------------ formatting
const dtFmt = new Intl.DateTimeFormat("en-CA", { dateStyle: "medium", timeStyle: "short" });
const dFmt = new Intl.DateTimeFormat("en-CA", { dateStyle: "medium" });
function tokensText(v) {
  if (v && typeof v === "object") return `${v.input_tokens ?? "?"} in / ${v.output_tokens ?? "?"} out`;
  return String(v);
}

function when(iso) { if (!iso) return "unknown time"; const d = new Date(iso); return isNaN(d) ? iso : dtFmt.format(d); }
function day(iso) { const d = new Date(iso); return isNaN(d) ? iso : dFmt.format(d); }
function ago(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(s)) return "";
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} minutes ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} hours ago`;
  return `${Math.round(s / 86400)} days ago`;
}
// "/ ft", "/ m", "/ 1,000 ft" for prices quoted per length; "/M?" when the unit is unclear
function perText(o) {
  if (!o || !o.per_length) return "";
  if (o.per_length === "?") return " / M (unit unclear)";
  const q = Number(o.per_length_qty || 1);
  return ` / ${q !== 1 ? `${q.toLocaleString("en-CA")} ` : ""}${o.per_length}`;
}
function money(v, cur) {
  if (v === null || v === undefined) return "n/a";
  const n = Number(v).toLocaleString("en-CA", { minimumFractionDigits: 2, maximumFractionDigits: v < 1 ? 4 : 2 });
  return `${cur || "?"} ${n}`;
}
const COUNTRY = { CA: "Canada", US: "United States", CN: "China", GB: "United Kingdom", DE: "Germany", MX: "Mexico",
  JP: "Japan", AU: "Australia", FR: "France", IT: "Italy", IN: "India", KR: "South Korea", TW: "Taiwan" };
function country(cc) { return cc ? (COUNTRY[cc] || cc) : "country unknown"; }

// ------------------------------------------------------------------ provenance marks
const MARK_TEXT = { quoted: "Quoted", snippet: "Snippet", calculated: "Calculated", estimated: "Estimated",
  quote: "Quote required", unknown: "Unknown", risk: "Unverified" };
const MARK_TIP = {
  quoted: "Stated by the source: supplier page data or a shopping listing.",
  snippet: "Seen only in a search-result snippet. May be outdated; open the page to confirm.",
  calculated: "Arithmetic on quoted values (unit price, currency conversion, totals).",
  estimated: "Uses your stated assumptions (shipping, duty, surtax, brokerage).",
  quote: "The supplier doesn't publish a price; ask for a quote.",
  unknown: "Not available from the evidence.",
};
function mark(kind, text) {
  return h("span", { class: `mark ${kind}`, title: MARK_TIP[kind] || "" }, text || MARK_TEXT[kind]);
}
function priceMark(o) {
  if (o.price_type === "quote_required") return mark("quote");
  if (o.price_type === "unclear") return mark("unknown", "Unclear");
  if (o.price_basis === "snippet") return mark("snippet");
  if (["structured_data", "shopping_api", "llm_verified"].includes(o.price_basis)) {
    return mark("quoted", o.price_basis === "llm_verified" ? "Quoted, AI-read" : "Quoted");
  }
  return mark("unknown");
}
function basisMark(b) {
  return mark({ quoted: "quoted", calculated: "calculated", assumption: "estimated", rate: "calculated",
    unknown: "unknown" }[b] || "unknown", { rate: "Tax rate", assumption: "Your assumption" }[b]);
}
function legend() {
  return h("div", { class: "legend", "aria-label": "What the marks mean" },
    ["quoted", "snippet", "calculated", "estimated", "quote"].map((k) =>
      h("span", {}, mark(k), h("span", {}, MARK_TIP[k].split(".")[0]))));
}

// ------------------------------------------------------------------ status & setup
async function loadStatus() {
  const r = await api("/api/status");
  state.status = r.body;
  const pill = $("#status-pill");
  const ok = r.ok && r.body.ready;
  pill.classList.toggle("ok", ok);
  const prov = r.body?.providers || [];
  const has = (name) => prov.some((p) => p.configured && p.name.startsWith(name));
  const extra = [];
  if (has("SerpApi") && r.body?.web_search !== "SerpApi (Google)") extra.push("Google Shopping");
  const aiRejected = !!r.body?.ai_key_rejected;
  if (has("Claude") && !aiRejected) extra.push("AI reading");
  pill.querySelector("span").textContent = ok ? `Ready: ${[r.body.web_search, ...extra].join(" + ")}${aiRejected ? " · AI key rejected" : ""}` : "Setup needed";
  pill.classList.toggle("warn", ok && aiRejected);
  $("#search-btn").disabled = !ok;
  updateCostHint();
}
function setupNotice(setup) {
  const s = setup || state.status?.setup;
  return h("div", { class: "notice" },
    h("h3", {}, "Connect a search provider to start"),
    h("p", { style: "margin:0" }, s?.summary || "No search provider is configured."),
    h("ol", {}, (s?.steps || []).map((x) => h("li", {}, x))),
    keyForm(),
    h("p", { class: "small", style: "margin:10px 0 0" }, s?.docs || ""));
}
// Keys go to this computer's .env file through the local server; they are never shown again.
function keyForm() {
  const msg = h("span", { class: "msg", role: "status" });
  const ak = h("input", { type: "password", id: "key-anthropic", autocomplete: "off", spellcheck: "false", placeholder: "sk-ant-..." });
  const tk = h("input", { type: "password", id: "key-tavily", autocomplete: "off", spellcheck: "false", placeholder: "tvly-... (optional)" });
  const sk = h("input", { type: "password", id: "key-serpapi", autocomplete: "off", spellcheck: "false", placeholder: "optional" });
  const btn = h("button", { class: "btn primary", type: "submit" }, "Save");
  const say = (text, err = false) => { msg.className = err ? "msg err" : "msg"; msg.textContent = text; };
  return h("form", { class: "keyform", onsubmit: async (e) => {
    e.preventDefault();
    const body = { anthropic_api_key: ak.value.trim() || null, tavily_api_key: tk.value.trim() || null,
      serpapi_api_key: sk.value.trim() || null };
    if (!body.anthropic_api_key && !body.tavily_api_key && !body.serpapi_api_key) { say("Paste a key first.", true); return; }
    btn.disabled = true;
    say(body.anthropic_api_key ? "Checking the key with Anthropic..." : "Saving...");
    const r = await api("/api/setup/keys", { method: "POST", body: JSON.stringify(body) });
    btn.disabled = false;
    if (!r.ok) { say(typeof r.body?.detail === "string" ? r.body.detail : "Couldn't save the key.", true); return; }
    ak.value = ""; tk.value = ""; sk.value = "";
    say("Saved on this computer.");
    await loadStatus();
    if (state.status?.ready) { flash(null); renderHome(); }
  } },
    h("label", {}, "Anthropic API key", ak),
    h("label", {}, "Tavily API key (optional, free plan)", tk),
    h("label", {}, "SerpApi key (optional: Google Shopping Canada prices, free plan)", sk),
    h("div", { class: "row" }, btn, msg));
}
function spendText() {
  const sp = state.status?.spend;
  if (!sp || !sp.model) return "";
  if (!sp.estimable) return `Spending can't be estimated for ${sp.model}; check the Anthropic Console.`;
  const limit = sp.budget_usd > 0 ? ` of your US$${sp.budget_usd.toFixed(2)} monthly limit` : "";
  return `Anthropic spend this month: about US$${sp.month_usd.toFixed(2)}${limit} (estimate).`;
}
function providerPanel() {
  const st = state.status;
  if (!st) return null;
  return h("div", { class: "panel" },
    h("h3", {}, "Data sources"),
    st.ai_key_rejected ? h("div", { class: "notice", role: "alert", style: "margin-bottom:12px" },
      h("h3", {}, "Anthropic rejected your saved key"),
      h("p", { style: "margin:0" }, "AI reading is off until you paste a new key below. Searches still run. Create one at ",
        link("https://console.anthropic.com/settings/keys", "console.anthropic.com"), " (API Keys, then Create Key)."),
      keyForm()) : null,
    h("table", { class: "simple" },
      h("thead", {}, h("tr", {}, h("th", {}, "Service"), h("th", {}, "What it does"), h("th", {}, "Status"))),
      h("tbody", {}, st.providers.map((p) => h("tr", {},
        h("td", {}, p.name), h("td", {}, p.role),
        h("td", {}, p.configured ? "Configured" : `Not configured (${p.env})`))))),
    st.ready ? h("details", { style: "margin-top:10px" }, h("summary", {}, "Add or change API keys"), keyForm()) : null,
    h("p", { class: "small muted", style: "margin:10px 0 0" }, spendText()),
    h("p", { class: "small muted", style: "margin:10px 0 0" },
      `Database: ${st.database}. Page reading ${st.page_fetching ? "on" : "off"}${st.page_fetching && st.fetch_fallback ? " (Anthropic web fetch if this server can't connect)" : ""}`,
      st.robots_txt ? ", respecting robots.txt." : "."));
}
function updateCostHint() {
  const depth = document.querySelector('input[name="depth"]:checked')?.value || "standard";
  // web searches per round (see app/discovery.py DEPTH_BUDGET); follow-up rounds stop early when they find nothing new
  const rounds = { quick: [8, 3], standard: [14, 8], deep: [20, 12, 8] }[depth];
  const maps = { quick: 1, standard: 2, deep: 3 }[depth];
  const n = `${rounds[0]} to ${rounds.reduce((a, b) => a + b, 0)}`;
  const credits = depth === "deep" ? `${rounds[0] * 2} to ${rounds.reduce((a, b) => a + b, 0) * 2}` : n;
  const prov = state.status?.providers || [];
  const tav = prov.find((p) => p.name === "Tavily")?.configured;
  const serp = prov.find((p) => p.name === "SerpApi")?.configured;
  const ai = prov.find((p) => p.name.startsWith("Claude"))?.configured;
  const parts = [];
  const web = state.status?.web_search;
  if (web === "Tavily" && tav) parts.push(`${n} web searches (${credits} Tavily credits)`);
  else if (web === "Anthropic web search") parts.push(`${n} Anthropic web searches (about US$0.01 each plus tokens)`);
  else if (serp) parts.push(`${n} web searches`);
  if (serp) parts.push(`1 Google Shopping and ${maps} Google Maps search${maps > 1 ? "es" : ""}`);
  if (ai) parts.push("AI reading on");
  const spend = spendText();
  $("#cost-hint").textContent = (parts.length ? `Uses ${parts.join(", ")}. ` : "") + spend +
    (depth !== "deep" ? " Expensive or higher-risk items are searched one level deeper." : "");
}

// ------------------------------------------------------------------ routing
function route() {
  const m = location.hash.match(/^#\/c\/(\d+)/);
  if (m) openComparison(Number(m[1]));
  else renderHome();
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ home
async function renderHome() {
  document.body.classList.remove("compact");
  $("#filters-apply").hidden = true;
  state.comparison = null;
  const view = $("#view");
  view.replaceChildren();
  if (state.status && !state.status.ready) view.append(setupNotice());
  const [saved, recent] = await Promise.all([api("/api/comparisons?saved=true"), api("/api/searches/recent?limit=15")]);
  const savedList = saved.body || [];
  const recentList = recent.body || [];
  view.append(h("div", { class: "grid-2 home-lists", style: "margin-top:18px" },
    h("section", { class: "panel" }, h("h2", {}, "Saved comparisons"),
      savedList.length ? savedList.map((c) => h("a", { class: "listlink", href: `#/c/${c.id}` },
        h("span", { class: "t" }, c.title, c.verdict?.who ? h("span", { class: "who" }, c.verdict.who) : null),
        h("span", { class: "d" }, verdictStamp(c.verdict), `researched ${day(c.last_researched_at)}`)))
        : h("p", { class: "empty" }, "Nothing saved yet. Open a comparison and choose Save to keep it here.")),
    h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Recent searches"),
      recentList.length ? h("button", { class: "btn small", type: "button", onclick: clearRecent }, "Clear list") : null),
      recentList.length ? recentList.map((s) => s.comparison_id
        ? h("a", { class: "listlink", href: `#/c/${s.comparison_id}` },
          h("span", { class: "t" }, s.query, s.verdict?.who ? h("span", { class: "who" }, s.verdict.who) : null),
          h("span", { class: "d" }, verdictStamp(s.verdict), ago(s.created_at)))
        : h("div", { class: "listlink" }, h("span", { class: "t" }, s.query),
          h("span", { class: s.status === "failed" ? "tag-failed" : "d" },
            s.status === "failed" ? verdictStamp({ kind: "fail", text: "Failed" }) : s.status)))
        : h("p", { class: "empty" }, "Your searches will appear here."))),
    h("div", { style: "margin-top:18px" }, providerPanel()));
}

// A comparison's outcome as a small ink stamp: the recommended price, or what's still needed
function verdictStamp(v) {
  return v ? h("span", { class: `stamp-sm ${v.kind}` }, v.text) : null;
}

async function clearRecent() {
  if (!confirm("Clear the recent searches list? Saved comparisons and price history are kept.")) return;
  const r = await api("/api/searches/recent", { method: "DELETE" });
  if (r.ok) renderHome();
}

// ------------------------------------------------------------------ picture preview
// Hovering (or tabbing to) a listing link shows the listing's picture, so each one needn't be opened. The picture
// loads straight from the seller's site; if it doesn't load, nothing is shown.
const peek = h("div", { class: "peek", hidden: true, "aria-hidden": "true" },
  h("img", { alt: "", referrerpolicy: "no-referrer" }), h("div", { class: "cap" }));
document.body.append(peek);
let peekTimer = null, peekFor = null;
function showPeek(a) {
  peekFor = a;
  const img = peek.querySelector("img");
  img.onload = () => { if (peekFor !== a) return; placePeek(a); peek.hidden = false; };
  img.onerror = () => { peek.hidden = true; };
  peek.querySelector(".cap").textContent = `Picture from ${hostOf(a.href)}`;
  img.src = a.dataset.img;
}
function placePeek(a) {
  const r = a.getBoundingClientRect(), w = 280, hgt = 240;
  const left = Math.min(window.innerWidth - w - 12, Math.max(12, r.left));
  const top = r.bottom + hgt + 12 > window.innerHeight ? Math.max(12, r.top - hgt - 8) : r.bottom + 8;
  peek.style.left = `${left + window.scrollX}px`;
  peek.style.top = `${top + window.scrollY}px`;
}
function hidePeek() { clearTimeout(peekTimer); peekFor = null; peek.hidden = true; }
document.addEventListener("mouseover", (e) => {
  const a = e.target.closest && e.target.closest("a[data-img]");
  if (!a || a === peekFor) return;
  clearTimeout(peekTimer);
  peekTimer = setTimeout(() => showPeek(a), 120);
});
document.addEventListener("mouseout", (e) => {
  const a = e.target.closest && e.target.closest("a[data-img]");
  if (a && !a.contains(e.relatedTarget)) hidePeek();
});
document.addEventListener("focusin", (e) => { const a = e.target.closest && e.target.closest("a[data-img]"); if (a) showPeek(a); });
document.addEventListener("focusout", (e) => { if (e.target.closest && e.target.closest("a[data-img]")) hidePeek(); });
window.addEventListener("scroll", () => { if (!peek.hidden) hidePeek(); }, { passive: true });  // it would float off its link

// ------------------------------------------------------------------ search flow
$("#search-form").addEventListener("submit", (e) => { e.preventDefault(); startResearch(); });

// ------------------------------------------------------------------ filters
// Price uses a two-handle slider on a log scale ($10 to $1,000,000), so cheap and expensive items both get room; the
// ends mean "any". The boxes show and take exact amounts.
const P_MIN = 1, P_SPAN = 5, P_STEPS = 1000;
const posToPrice = (pos) => { const v = 10 ** (P_MIN + (pos / P_STEPS) * P_SPAN); const m = 10 ** Math.floor(Math.log10(v) - 1); return Math.round(v / m) * m; };
const priceToPos = (v) => Math.max(0, Math.min(P_STEPS, Math.round(((Math.log10(Math.max(v, 10)) - P_MIN) / P_SPAN) * P_STEPS)));
function paintSlider() {
  const lo = Number($("#price-lo").value), hi = Number($("#price-hi").value);
  $("#price-slider").style.setProperty("--lo", `${(lo / P_STEPS) * 100}%`);
  $("#price-slider").style.setProperty("--hi", `${(hi / P_STEPS) * 100}%`);
}
["#price-lo", "#price-hi"].forEach((sel) => $(sel).addEventListener("input", (e) => {
  let lo = Number($("#price-lo").value), hi = Number($("#price-hi").value);
  if (lo > hi) { if (e.target.id === "price-lo") hi = lo; else lo = hi; $("#price-lo").value = lo; $("#price-hi").value = hi; }
  $("#price-min").value = lo > 0 ? posToPrice(lo) : "";
  $("#price-max").value = hi < P_STEPS ? posToPrice(hi) : "";
  paintSlider(); filtersChanged();
}));
["#price-min", "#price-max"].forEach((sel) => $(sel).addEventListener("input", () => {
  const mn = $("#price-min").value, mx = $("#price-max").value;
  $("#price-lo").value = mn === "" ? 0 : priceToPos(Number(mn));
  $("#price-hi").value = mx === "" ? P_STEPS : priceToPos(Number(mx));
  paintSlider(); filtersChanged();
}));
["#year-min", "#year-max", "#km-max", "#km-unit", "#hours-max"].forEach((sel) => $(sel).addEventListener("input", filtersChanged));
$("#filters-btn").addEventListener("click", () => toggleFilters());
$("#filters-clear").addEventListener("click", () => { setFilters({}); filtersChanged(); });
$("#filters-apply").addEventListener("click", applyFiltersToResult);
function toggleFilters(open) {
  const panel = $("#filters"), show = open ?? panel.hidden;
  panel.hidden = !show;
  $("#filters-btn").setAttribute("aria-expanded", String(show));
}
function collectFilters() {
  const num = (sel) => { const v = $(sel).value.trim(); return v === "" ? null : Number(v); };
  const km = num("#km-max");
  const f = { price_min: num("#price-min"), price_max: num("#price-max"), year_min: num("#year-min"),
    year_max: num("#year-max"), km_max: km == null ? null : Math.round($("#km-unit").value === "mi" ? km * 1.609344 : km),
    hours_max: num("#hours-max") };
  return Object.fromEntries(Object.entries(f).filter(([, v]) => v != null && !Number.isNaN(v)));
}
function setFilters(f) {
  $("#price-min").value = f.price_min ?? ""; $("#price-max").value = f.price_max ?? "";
  $("#price-lo").value = f.price_min != null ? priceToPos(f.price_min) : 0;
  $("#price-hi").value = f.price_max != null ? priceToPos(f.price_max) : P_STEPS;
  $("#year-min").value = f.year_min ?? ""; $("#year-max").value = f.year_max ?? "";
  $("#km-max").value = f.km_max ?? ""; $("#km-unit").value = "km"; $("#hours-max").value = f.hours_max ?? "";
  paintSlider(); filtersChanged();
}
function filtersChanged() {
  const n = Object.keys(collectFilters()).length;
  $("#filters-btn").textContent = n ? `Filters (${n})` : "Filters";
  $("#filters-btn").classList.toggle("on", n > 0);
}
function filtersText(f) {
  if (!f) return "";
  const parts = [];
  const cad = (v) => money(v, "CAD");
  if (f.price_min != null && f.price_max != null) parts.push(`${cad(f.price_min)} to ${cad(f.price_max)}`);
  else if (f.price_min != null) parts.push(`from ${cad(f.price_min)}`);
  else if (f.price_max != null) parts.push(`up to ${cad(f.price_max)}`);
  if (f.year_min != null || f.year_max != null) parts.push(f.year_min != null && f.year_max != null ? `${f.year_min} to ${f.year_max}` : f.year_min != null ? `${f.year_min} or newer` : `${f.year_max} or older`);
  if (f.km_max != null) parts.push(`up to ${Number(f.km_max).toLocaleString("en-CA")} km`);
  if (f.hours_max != null) parts.push(`up to ${Number(f.hours_max).toLocaleString("en-CA")} hours`);
  return parts.join("; ");
}
async function applyFiltersToResult() {
  if (!state.comparison) return;
  const btn = $("#filters-apply");
  btn.disabled = true;
  const r = await api(`/api/comparisons/${state.comparison.id}/filters`, { method: "PUT", body: JSON.stringify(collectFilters()) });
  btn.disabled = false;
  if (r.ok) { state.comparison = r.body; renderComparison(); }
}
paintSlider();

// Where to look: Thunder Bay, outside it, or both. At least one stays on; the choice is remembered on this computer.
function currentArea() {
  const l = $("#area-local").checked, o = $("#area-outside").checked;
  return l && o ? "both" : l ? "local" : "outside";
}
function setArea(area) {
  $("#area-local").checked = area !== "outside";
  $("#area-outside").checked = area !== "local";
}
try { const saved = localStorage.getItem("pi-area"); if (saved) setArea(saved); } catch { /* storage unavailable */ }
["#area-local", "#area-outside"].forEach((sel) => $(sel).addEventListener("change", (e) => {
  if (!$("#area-local").checked && !$("#area-outside").checked) e.target.checked = true;  // keep one on
  try { localStorage.setItem("pi-area", currentArea()); } catch { /* storage unavailable */ }
}));
$("#photo").addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) searchByPhoto(f); });
// Paste a copied picture anywhere on the page (Cmd/Ctrl+V), or drop one on the search box: no saving a file first
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.kind === "file" && i.type.startsWith("image/"));
  if (!item) return;  // ordinary text pastes are left alone
  e.preventDefault();
  searchByPhoto(item.getAsFile());
});
const box = document.querySelector(".searchbox");
box.addEventListener("dragover", (e) => { if ([...e.dataTransfer.types].includes("Files")) { e.preventDefault(); box.classList.add("drop"); } });
box.addEventListener("dragleave", () => box.classList.remove("drop"));
box.addEventListener("drop", (e) => {
  box.classList.remove("drop");
  const f = [...(e.dataTransfer?.files || [])].find((x) => x.type.startsWith("image/"));
  if (f) { e.preventDefault(); searchByPhoto(f); }
});

// Search by photo: the page shrinks the photo (Claude reads up to about 1,600 px, and it uploads faster), the app
// asks Claude what it shows and what's printed on it, and nothing is searched until you confirm or edit it.
async function searchByPhoto(file) {
  flash(h("div", { class: "progress", role: "status", "aria-live": "polite" },
    h("div", { class: "bar" }, h("i", { style: "width:55%" })), h("div", { class: "step" }, "Reading your photo…")));
  let dataUrl;
  try { dataUrl = await shrinkPhoto(file); } catch {
    flash(photoProblem({ message: "This photo format can't be opened here. Save it as a JPEG or PNG and try again." }));
    return;
  }
  // what's typed in the search box is what they want: the photo adds detail to it
  const context = $("#q").value.trim() || null;
  const r = await api("/api/photo", { method: "POST", body: JSON.stringify({ image: dataUrl, context }) });
  flash(r.ok ? photoCard(r.body, dataUrl) : photoProblem({ message: r.body?.message || r.body?.detail || "The photo couldn't be read.",
    google_lens: r.body?.google_lens }));
}

async function shrinkPhoto(file, max = 1600) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = bad; i.src = url; });
    const scale = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight));
    const c = document.createElement("canvas");
    c.width = Math.round(img.naturalWidth * scale); c.height = Math.round(img.naturalHeight * scale);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", 0.85);
  } finally { URL.revokeObjectURL(url); }
}

function lensLink(url) {
  return h("a", { class: "btn", href: url || "https://lens.google.com/", target: "_blank", rel: "noopener",
    title: "Opens Google Lens in a new tab; upload the same photo there" }, "Try Google Lens");
}

function photoProblem(p) {
  return h("div", { class: "notice", role: "alert" }, h("h3", {}, "Photo not read"),
    h("p", { style: "margin:0 0 10px" }, p.message),
    h("div", { class: "actions" }, lensLink(p.google_lens)),
    h("p", { class: "small muted", style: "margin:8px 0 0" }, "Google Lens opens in a new tab: upload the photo there yourself. Nothing was searched or saved."));
}

function photoCard(p, dataUrl) {
  const input = h("input", { type: "text", value: p.search_query, maxlength: "600", "aria-label": "Search for" });
  // what the photo shows goes along as context: into the quote requests ("From our reference photo: ...")
  const notes = [p.what, p.label_text.length ? `label reads ${p.label_text.slice(0, 4).join(", ")}` : ""].filter(Boolean).join("; ");
  const go = (e) => { e.preventDefault(); const q = input.value.trim(); if (!q) return; $("#q").value = q;
    startResearch({ query: q, extraAnswers: notes ? { photo_notes: notes.slice(0, 200) } : null }); };
  return h("form", { class: "notice info photo-card", onsubmit: go },
    h("img", { src: dataUrl, alt: "Your photo" }),
    h("div", { class: "photo-body" },
      h("h3", {}, p.context ? "Your words, with details from your photo" : "From your photo"),
      p.context ? h("p", { class: "small", style: "margin:0 0 6px" }, "You typed: ", h("b", {}, p.context)) : null,
      h("p", { style: "margin:0 0 6px" }, h("b", {}, p.what || "Item not identified"), " ",
        h("span", { class: `conf ${p.confidence}` }, `${p.confidence} confidence`)),
      h("p", { class: "small", style: "margin:0 0 6px" }, "Text read from the photo: ",
        p.label_text.length ? p.label_text.map((t, i) => [i ? " " : "", h("code", {}, t)]) : h("span", { class: "muted" }, "none readable")),
      p.removed.length ? h("p", { class: "small", style: "margin:0 0 6px" },
        `Left out because it isn't readable in the photo: ${p.removed.join(", ")}.`) : null,
      p.notes ? h("p", { class: "small muted", style: "margin:0 0 10px" }, p.notes) : null,
      h("label", { class: "small", style: "display:block;margin-bottom:4px" }, "Search for (edit if needed)"),
      h("div", { class: "photo-search" }, input, h("button", { class: "btn primary", type: "submit" }, "Research this")),
      h("div", { class: "actions", style: "margin-top:10px" }, lensLink(p.google_lens)),
      h("p", { class: "small muted", style: "margin:8px 0 0" }, p.label,
        p.cost_usd != null ? ` About US$${p.cost_usd.toFixed(4)} of AI use.` : "", " The photo isn't saved.")));
}
document.querySelectorAll('input[name="depth"]').forEach((r) => r.addEventListener("change", updateCostHint));
$("#status-pill").addEventListener("click", () => { location.hash = "#/"; renderHome(); });

async function startResearch(opts = {}) {
  const query = opts.query ?? $("#q").value.trim();
  if (!query) { flash(h("div", { class: "notice info" }, "Type what you need to buy, then choose Research.")); $("#q").focus(); return; }
  const depth = opts.depth || document.querySelector('input[name="depth"]:checked').value;
  const qty = opts.quantity !== undefined ? opts.quantity : (Number($("#qty").value) || null);
  flash(null);
  if (!opts.answers && !opts.comparisonId) {
    // clarify first: a few optional questions, only when the answer would change the results (free, no search)
    const c = await api("/api/clarify", { method: "POST", body: JSON.stringify({ query, quantity: qty }) });
    if (c.ok && (c.body.questions.length || c.body.guide?.broad)) {
      flash(clarifyCard(c.body, (answers) => startResearch({ ...opts, query, depth, quantity: qty, answers: { ...answers, ...(opts.extraAnswers || {}) } }),
        (term) => { $("#q").value = term; startResearch({ ...opts, query: term, depth, quantity: qty }); }));
      return;
    }
  }
  const area = opts.area || currentArea();
  const filters = opts.filters || collectFilters();
  const r = await api("/api/research", { method: "POST", body: JSON.stringify({ query, depth, quantity: qty, area, filters,
    force: !!opts.force, comparison_id: opts.comparisonId ?? null, answers: opts.answers || opts.extraAnswers || null }) });
  if (r.status === 503) { flash(setupNotice(r.body?.setup)); return; }
  if (r.status === 402) {
    flash(h("div", { class: "notice" }, h("h3", {}, "Monthly spending limit reached"), h("p", { style: "margin:0" }, r.body?.message || "")));
    return;
  }
  if (!r.ok) { flash(errorNotice({ message: r.body?.detail?.[0]?.msg || r.body?.detail || "The request was rejected." })); return; }
  if (r.body.duplicate) {
    const d = r.body.duplicate;
    flash(h("div", { class: "notice info" },
      h("h3", {}, "Already researched recently"),
      h("p", { style: "margin:0 0 10px" }, `“${d.title}” was researched ${ago(d.last_researched_at)}. Open it, or search again (uses search credits).`),
      h("div", { class: "actions" },
        h("a", { class: "btn primary", href: `#/c/${d.id}`, onclick: () => flash(null) }, "Open saved result"),
        h("button", { class: "btn", type: "button", onclick: () => startResearch({ query, depth, comparisonId: d.id, answers: opts.answers }) }, "Search again"))));
    return;
  }
  trackJob(r.body.job_id, query);
}

function flash(node) { $("#flash").replaceChildren(...(node ? [node] : [])); }

// Optional questions before searching. Blank = skipped; the research states what it assumed instead.
function clarifyCard(cq, go, pick) {
  const inputs = {};
  const known = Object.entries(cq.known || {}).filter(([, v]) => v !== null && v !== "");
  const form = h("form", { class: "clarify", onsubmit: (e) => { e.preventDefault(); go(collect()); } },
    cq.guide ? guideCard(cq.guide, pick) : null,
    h("h3", {}, cq.guide?.broad ? "Or search as typed - a few questions first (all optional)" : "A few questions first (all optional)"),
    h("p", { class: "small muted", style: "margin:0 0 10px" }, cq.note),
    cq.questions.map((q) => {
      let input;
      if (q.kind === "choice") {
        input = h("div", { class: "choices", role: "radiogroup", "aria-label": q.text },
          q.options.map((o) => h("label", {}, h("input", { type: "radio", name: `cq-${q.id}`, value: o }), h("span", {}, o))));
      } else {
        input = h("input", { type: q.kind === "number" ? "number" : "text", name: `cq-${q.id}`, placeholder: q.placeholder,
          min: q.kind === "number" ? "0" : null, "aria-label": q.text });
      }
      inputs[q.id] = { q, input };
      return h("div", { class: "cq" }, h("div", { class: "qt" }, q.text), input, h("div", { class: "why small muted" }, q.why));
    }),
    known.length ? h("p", { class: "small muted" }, "Using your earlier answers: ", known.map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join("; "), ".") : null,
    h("div", { class: "actions" },
      h("button", { class: "btn primary", type: "submit" }, "Research"),
      h("button", { class: "btn", type: "button", onclick: () => go(Object.fromEntries(cq.questions.map((q) => [q.id, null]))) }, "Skip questions")));
  function collect() {
    const out = {};
    for (const [id, { q, input }] of Object.entries(inputs)) {
      let v = null;
      if (q.kind === "choice") v = input.querySelector("input:checked")?.value || null;
      else v = input.value.trim() || null;
      if (v !== null && q.kind === "number") v = Number(v);
      out[id] = v;
    }
    return out;
  }
  return h("div", { class: "notice info" }, form);
}

// Built-in buying guide for a broad term ("radios"): the main types (pick one to search for it), what to confirm
// with the supplier, and safety flags. General guidance, labelled as such - never search results.
function guideCard(g, pick) {
  return h("section", { class: "guide" },
    h("div", { class: "kind" }, g.broad ? `${g.title}: which type do you need?` : g.title),
    h("p", { style: "margin:2px 0 10px" }, g.intro),
    g.broad && pick ? h("div", { class: "types" }, g.types.map((t) => h("button", { class: "type", type: "button", onclick: () => pick(t.search) },
      h("b", {}, t.name), h("span", { class: "small muted" }, t.for), h("span", { class: "go small" }, `Search for “${t.search}” →`)))) : null,
    h("details", { open: !g.broad }, h("summary", { class: "small" }, "What to confirm with the supplier"),
      h("ul", { class: "bullets small" }, g.checklist.map((c) => h("li", {}, c)))),
    g.hazard ? h("p", { class: "small hazard" }, h("b", {}, "Safety: "), g.hazard) : null,
    h("p", { class: "small muted", style: "margin:6px 0 0" }, g.label));
}

function trackJob(jobId, query) {
  const box = h("div", { class: "progress", role: "status", "aria-live": "polite" },
    h("div", { class: "bar" }, h("i")), h("div", { class: "step" }, `Researching “${query}”…`));
  flash(box);
  $("#search-btn").disabled = true;
  const tick = async () => {
    const r = await api(`/api/jobs/${jobId}`);
    if (!r.ok) { $("#search-btn").disabled = false; flash(errorNotice({ message: "Lost track of the research job (the server may have restarted). Try again." })); return; }
    const j = r.body;
    box.querySelector("i").style.width = `${j.pct}%`;
    const step = box.querySelector(".step");
    if (step.textContent !== j.step) { step.textContent = j.step; step.classList.remove("swap"); void step.offsetWidth; step.classList.add("swap"); }
    if (j.status === "running") { setTimeout(tick, 700); return; }
    $("#search-btn").disabled = !(state.status && state.status.ready);
    loadStatus();  // refresh this month's spend
    if (j.status === "done") { flash(null); location.hash = `#/c/${j.comparison_id}`; if (location.hash === `#/c/${j.comparison_id}`) openComparison(j.comparison_id); }
    else flash(errorNotice(j.error || {}));
  };
  tick();
}

const ERROR_HELP = {
  auth: "The search provider rejected the API key. Check the key in the server's .env file and restart the server.",
  quota: "The search plan's credits are used up. Add credits or wait for the monthly reset, then try again.",
  rate_limit: "Too many searches in a short time. Wait a minute and try again.",
  network: "The server couldn't reach the search provider. Check its internet connection, proxy or firewall rules.",
  timeout: "The search provider didn't answer in time. Try again; if it keeps happening, try Quick depth.",
  not_configured: "No search provider is configured. See the setup steps on the home page.",
  bad_input: "Enter a product name, model number, description or URL.",
};
function errorNotice(err) {
  return h("div", { class: "notice", role: "alert" },
    h("h3", {}, "Research didn't complete"),
    h("p", { style: "margin:0" }, err.message || "Unknown error."),
    ERROR_HELP[err.kind] ? h("p", { style: "margin:8px 0 0" }, ERROR_HELP[err.kind]) : null,
    h("p", { class: "small muted", style: "margin:8px 0 0" }, "No results were invented or saved for this attempt."));
}

// ------------------------------------------------------------------ comparison view
async function openComparison(id) {
  document.body.classList.add("compact");
  const r = await api(`/api/comparisons/${id}`);
  if (!r.ok) { $("#view").replaceChildren(errorNotice({ message: "That comparison no longer exists." })); return; }
  state.comparison = r.body;
  state.history = null;
  $("#q").value = r.body.query;
  state.entering = true;
  renderComparison();
  state.entering = false;
  setFilters(r.body.result.filters || {});
}

function renderComparison() {
  $("#filters-apply").hidden = false;
  const comp = state.comparison;
  const res = comp.result;
  const view = $("#view");
  const offersById = Object.fromEntries(res.offers.map((o) => [o.id, o]));
  view.replaceChildren(
    header(comp, res),
    keyFindings(res, offersById),
    comparisonTable(res),
    tabs(res),
  );
}

function header(comp, res) {
  const id = res.identity;
  const saveBtn = h("button", { class: comp.saved ? "btn" : "btn primary", type: "button", onclick: async () => {
    let title = comp.title;
    if (!comp.saved) {
      const t = prompt("Name this comparison", comp.title);
      if (t === null) return;
      title = t.trim() || comp.title;
    }
    const r = await api(`/api/comparisons/${comp.id}`, { method: "PATCH", body: JSON.stringify({ saved: !comp.saved, title }) });
    if (r.ok) { state.comparison = r.body; renderComparison(); }
  } }, comp.saved ? "Saved (remove)" : "Save");
  return h("div", { class: "result-head" },
    h("div", {},
      h("h1", {}, comp.title),
      h("div", { class: "meta" },
        "Last researched ", h("span", { class: "when" }, when(comp.last_researched_at)), ` (${ago(comp.last_researched_at)}). `,
        id.input_type === "url" ? ["From your link, identified via ", id.source, ". "] : null,
        id.model_tokens?.length ? `Model number matched: ${id.model_tokens.join(", ")}. ` : "No model number given, so equivalence isn't verified. ",
        res.quantity ? `Quantity: ${res.quantity}. ` : "",
        res.area === "local" ? "Searched in Thunder Bay only. " : res.area === "outside" ? "Searched outside Thunder Bay only. " : "",
        filtersText(res.filters) ? [h("b", {}, "Filters: "), `${filtersText(res.filters)}. `] : null,
        h("button", { class: "linkish", type: "button", onclick: () => { setFilters(res.filters || {}); toggleFilters(true); $("#filters").scrollIntoView({ block: "nearest" }); } },
          filtersText(res.filters) ? "Change filters" : "Filter these results")),
      h("details", { class: "legend-box" }, h("summary", {}, "How to read the price marks"), legend())),
    h("div", { class: "actions" },
      saveBtn,
      h("button", { class: "btn", type: "button", title: "Runs a new search and adds new price observations (uses credits)",
        onclick: () => startResearch({ query: comp.query, depth: res.depth, comparisonId: comp.id, quantity: res.quantity ?? null, answers: res.answers || {}, area: res.area || "both", filters: res.filters || {} }) }, "Search again"),
      h("a", { class: "btn", href: `/api/comparisons/${comp.id}/export.csv` }, "Export CSV"),
      h("a", { class: "btn", href: `/api/comparisons/${comp.id}/export.xlsx` }, "Export Excel")));
}

function recCard(kind, rec, res, offersById) {
  const isValue = kind === "value";
  const title = isValue ? "Best overall value" : "Lowest comparable price";
  if (!rec) {
    return h("section", { class: `rec ${isValue ? "value" : ""} none` },
      h("div", { class: "kind" }, title),
      h("div", { class: "price" }, "No recommendation"),
      h("ul", { class: "why" }, (res.recommendations.notes || ["Not enough comparable evidence."]).map((n) => h("li", {}, n))));
  }
  const o = offersById[rec.offer_id] || {};
  const foreign = rec.currency !== "CAD";
  return h("section", { class: `rec ${isValue ? "value" : ""}` },
    h("div", { class: "kind" }, title),
    h("div", { class: "price num" }, money(rec.price, rec.currency), perText(o) ? h("small", {}, perText(o)) : null, " ", priceMark(o),
      foreign && rec.price_cad != null ? h("small", {}, ` ≈ CAD ${Number(rec.price_cad).toFixed(2)} `, mark("calculated")) : null),
    o.pack_qty && o.unit_price_cad != null ? h("div", { class: "small muted" }, `${o.pack_text}: ${money(o.unit_price_cad, "CAD")} per unit `, mark("calculated")) : null,
    rec.per_ft_cad != null && (o.per_length !== "ft" || o.per_length_qty !== 1 || foreign)
      ? h("div", { class: "small muted" }, `${money(rec.per_ft_cad, "CAD")} per foot `, mark("calculated")) : null,
    rec.order_total_cad != null ? h("div", { class: "small" }, `For ${rec.order_length}: about `,
      h("b", {}, money(rec.order_total_cad, "CAD")), " ", mark("calculated"), " before tax and shipping") : null,
    h("div", { class: "who" }, rec.supplier, " ", h("span", { class: "sub" }, `${o.supplier_type || ""}, ${country(o.country)}`)),
    h("div", { class: "small" }, link(rec.url, "Open listing", null, o.image), ` (observed ${when(o.observed_at)})`),
    h("ul", { class: "why" }, rec.explanation.map((e) => h("li", {}, e))),
    (o.flags || []).length ? h("div", { class: "small", style: "margin-top:10px" },
      h("b", {}, "Check before ordering: "), o.flags.slice(0, 3).join(" ")) : null,
    isValue ? h("details", {}, h("summary", { class: "small" }, "How the score was built"),
      h("table", { class: "factors" }, h("tbody", {}, rec.factors.map((f) => h("tr", {},
        h("td", {}, f.factor), h("td", { class: "muted" }, f.evidence),
        h("td", { class: `pts num ${f.points < 0 ? "neg" : ""}` }, f.points))))),
      h("p", { class: "small muted" }, rec.scoring_note)) : null);
}

function keyFindings(res, offersById) {
  const rec = res.recommendations;
  const plain = res.recommendation;
  const watch = [];
  (res.conflicts || []).forEach((c) => watch.push(c.text));
  const q = res.quality || {};
  if ((q.recall_mentions || []).length) watch.push(q.recall_note);
  (rec.notes || []).forEach((n) => { if (rec.lowest) watch.push(n); });
  (res.gaps || []).forEach((g) => watch.push(g));
  const shown = watch.slice(0, 5), more = watch.slice(5);
  const opp = [...(plain?.needed || []), ...(res.opportunities || [])];
  return h("div", { class: "stack" },
    plain ? leadCard(plain, res) : null,
    res.guide ? guideCard(res.guide, (term) => { $("#q").value = term; startResearch({ query: term }); }) : null,
    plain?.judge ? null : h("div", { class: "recs" }, recCard("lowest", rec.lowest, res, offersById), recCard("value", rec.best_value, res, offersById)),
    plain && plain.comparison.length ? picksTable(plain) : null,
    res.market_value ? marketPanel(res.market_value) : null,
    h("div", { class: "grid-2" },
      h("section", { class: `watch ${watch.length ? "" : "calm"}` },
        h("h3", {}, watch.length ? "Watch out for" : "No conflicts or gaps detected"),
        watch.length ? h("ul", { class: "bullets" }, shown.map((w) => h("li", {}, w))) : null,
        more.length ? h("details", {}, h("summary", { class: "small" }, `${more.length} more`),
          h("ul", { class: "bullets" }, more.map((w) => h("li", {}, w)))) : null),
      h("section", { class: "watch calm" },
        h("h3", {}, "Ways to pay less, and what to ask for"),
        opp.length ? h("ul", { class: "bullets" }, [...new Set(opp)].map((t) => h("li", {}, t)))
          : h("p", { class: "empty", style: "margin:0" }, "No wholesale, bulk or quote-only channels were found in this search."))),
    (res.stated_assumptions || []).length ? h("section", { class: "panel assumed" },
      h("h3", {}, "Assumed (questions you skipped or didn't get)"),
      h("ul", { class: "bullets" }, res.stated_assumptions.map((a) => h("li", {}, a)))) : null);
}

function leadCard(plain, res) {
  if (plain.judge) {
    const pages = plain.listing_pages || [];
    const options = plain.judge === "shortlist";
    return h("section", { class: `lead none${state.entering ? " enter" : ""}` }, h("div", { class: "kind stamp" }, options ? "Shortlist - pick a model first" : "For you to judge"),
      h("div", { class: "head" }, options ? "Options found - different models, not ranked by price" : "Listings to compare yourself - no price ranking"),
      plain.judge_note ? h("p", { class: "small", style: "margin:4px 0 8px" }, plain.judge_note) : null,
      pages.length ? h("ul", { class: "why" }, pages.map((p) => h("li", {}, link(p.url, p.supplier, null, p.image), p.local ? " (Thunder Bay)" : "",
        `: ${p.title}`, factsText(p.facts), p.auction && p.price_kind !== "current_bid" ? h("span", { class: "muted" }, " (auction: check it's still open)") : null, p.price != null ? ` - ${p.price_kind === "current_bid" ? "current bid " : ""}${p.currency ? money(p.price, p.currency) : `${Number(p.price).toLocaleString("en-CA")} (currency not stated)`}${p.many ? " seen on this page (one of many ads)" : ""}` : "",
        h("span", { class: "muted" }, ` · ${day(p.observed_at)}`)))) : null,
      (plain.sold || []).length ? h("details", { class: "sold" },
        h("summary", {}, `Sold recently or auction closed (${plain.sold.length}): market evidence, not for sale`),
        h("ul", { class: "why" }, plain.sold.map((p) => h("li", {}, link(p.url, p.supplier, null, p.image), `: ${p.title}`, factsText(p.facts),
          p.price != null ? ` - sold for ${p.currency ? money(p.price, p.currency) : Number(p.price).toLocaleString("en-CA")}` : "",
          h("span", { class: "muted" }, ` · seen ${day(p.observed_at)}`))))) : null,
      h("ul", { class: "why" }, (plain.needed || []).map((n) => h("li", {}, n))),
      h("div", { class: "next" }, h("button", { class: "btn", type: "button", onclick: () => goToTab("suppliers") }, "Suppliers & quote drafts")));
  }
  if (!plain.lead) {
    return h("section", { class: `lead none${state.entering ? " enter" : ""}` }, h("div", { class: "kind stamp" }, "No recommendation yet"),
      h("div", { class: "head" }, "Not enough evidence to recommend a supplier"),
      h("ul", { class: "why" }, (plain.needed || []).map((n) => h("li", {}, n))),
      h("div", { class: "next" }, h("button", { class: "btn primary", type: "button", onclick: () => goToTab("suppliers") }, "Suppliers & quote drafts")));
  }
  const row = (plain.comparison || []).find((r) => r.offer_id === plain.lead.offer_id) || {};
  const vendor = (res.vendors || []).find((v) => (v.offer_ids || []).includes(plain.lead.offer_id));
  const phone = vendor?.phones?.[0]?.value;
  return h("section", { class: `lead${state.entering ? " enter" : ""}` },
    h("div", { class: "lead-top" },
      h("div", {},
        h("div", { class: "kind stamp" }, "Recommended: best-supported option"),
        h("div", { class: "head" }, plain.lead.supplier),
        row.tier ? h("div", { class: "small muted" }, row.tier) : null),
      row.price ? h("div", { class: "figure" },
        h("div", { class: "amount" }, row.price, " ", mark(row.confidence === "low" ? "snippet" : "quoted")),
        row.total_pre_tax != null ? h("div", { class: "small" }, `${money(row.total_pre_tax, "CAD")} before tax`,
          res.quantity ? ` for ${res.quantity}` : "", row.total_complete ? "" : ", some costs unknown") : null) : null),
    h("div", { class: "next" },
      h("a", { class: "btn primary", href: plain.lead.url, target: "_blank", rel: "noopener", "data-img": row.image || null }, "Open listing"),
      phone ? h("a", { class: "btn", href: telHref(phone) }, `Call ${phone}`) : null,
      h("button", { class: "btn", type: "button", onclick: () => goToTab("suppliers") }, "Suppliers & quote drafts")),
    h("ul", { class: "why" }, plain.lead.why.map((w) => h("li", {}, w))),
    h("p", { class: "small muted", style: "margin:8px 0 0" }, plain.distinction));
}

// What a listing states for the filters ("2019, 120,000 km") and what it doesn't ("km not stated")
function factsText(f) {
  if (!f) return null;
  f = { ...f, closed: undefined };
  const said = [f.year, f.km != null ? `${Number(f.km).toLocaleString("en-CA")} km` : null,
    f.hours != null ? `${Number(f.hours).toLocaleString("en-CA")} hours` : null].filter(Boolean);
  const missing = (f.not_stated || []).map((k) => `${k} not stated`);
  if (!said.length && !missing.length) return null;
  return [said.length ? ` (${said.join(", ")})` : "", missing.length ? h("span", { class: "muted" }, ` - ${missing.join(", ")}`) : null];
}

function telHref(phone) {
  return "tel:" + phone.replace(/\s*(ext\.?|x)\s*\d+.*$/i, "").replace(/[^\d+]/g, "");
}

// Jump to a tab below (the next step after reading the verdict)
function goToTab(k) {
  const bar = document.querySelector(".tabs");
  if (!bar) return;
  const btn = [...bar.querySelectorAll("button")][TABS.findIndex(([key]) => key === k)];
  if (btn) btn.click();
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  bar.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" });
}

function picksTable(plain) {
  const rows = plain.comparison;
  return h("section", { class: "panel" },
    h("h3", {}, "Options side by side"),
    h("div", { class: "table-wrap", style: "border:0" }, h("table", { class: "simple picks" },
      h("thead", {}, h("tr", {}, h("th", {}, "Option"), h("th", {}, "Supplier"), h("th", { class: "r" }, "Price"),
        h("th", { class: "r" }, "Total before tax"), h("th", {}, "Evidence"), h("th", {}, "Delivery, stock and terms (supplier says)"),
        h("th", {}, "Compatibility"), h("th", {}, "Risks"))),
      h("tbody", {}, rows.map((r) => h("tr", {},
        h("td", {}, r.labels.map((l, i) => [i ? h("br") : null, h("b", {}, l)])),
        h("td", {}, link(r.url, r.supplier, null, r.image), r.tier ? h("div", { class: "sub" }, r.tier) : null),
        h("td", { class: "r num" }, r.price || "n/a"),
        h("td", { class: "r num" }, r.total_pre_tax != null ? [money(r.total_pre_tax, "CAD"), " ", mark("calculated"),
          r.total_complete ? null : h("div", { class: "sub" }, `excludes ${r.total_unknown.join(", ")}`)] : "n/a"),
        h("td", { class: "small" }, r.evidence, h("div", { class: "sub" }, `${r.confidence} confidence, ${day(r.observed_at)}`)),
        h("td", { class: "small" }, r.delivery, h("div", { class: "sub" }, `Stock: ${r.availability}. Warranty: ${r.warranty}`),
          r.minimum_order ? h("div", { class: "sub" }, `Minimum order: ${r.minimum_order}`) : null,
          r.volume_terms ? h("div", { class: "sub" }, `Volume terms: ${r.volume_terms}`) : null,
          r.pack ? h("div", { class: "sub" }, `Pack: ${r.pack}`) : null),
        h("td", { class: "small" }, r.compatibility),
        h("td", { class: "small" }, r.risks.length ? r.risks.join("; ") : "none noted")))))),
    plain.claims_note ? h("p", { class: "small muted", style: "margin:8px 0 0" }, plain.claims_note) : null,
    (plain.pick_notes || []).map((n) => h("p", { class: "small", style: "margin:8px 0 0" }, n)),
    (plain.missing_picks || []).length ? h("ul", { class: "bullets small", style: "margin-top:8px" },
      plain.missing_picks.map((m) => h("li", {}, m.text))) : null);
}

function marketPanel(mv) {
  const unit = { per_ft: "/ft", per_unit: "/unit", listing: "" }[mv.basis] || "";
  const v = (x) => x == null ? "n/a" : money(x, "CAD") + unit;
  const o = mv.overall_new;
  return h("section", { class: "panel" },
    h("h3", {}, "Market value"),
    o ? h("p", { style: "margin-top:0" }, o.supported
      ? [`New, same item: ${v(o.low)} to ${v(o.high)}, median ${v(o.median)} `, mark("calculated"), ` from ${o.count} asking prices.`]
      : o.note) : h("p", { style: "margin-top:0" }, "No same-item prices to build a market range from."),
    mv.groups.length ? h("div", { class: "table-wrap", style: "border:0" }, h("table", { class: "simple" },
      h("thead", {}, h("tr", {}, h("th", {}, "Group"), h("th", { class: "r" }, "Observations"), h("th", { class: "r" }, "Low"),
        h("th", { class: "r" }, "Median"), h("th", { class: "r" }, "High"), h("th", {}, "Seen"), h("th", {}, "Differences"))),
      h("tbody", {}, mv.groups.map((g) => h("tr", {},
        h("td", {}, g.label, h("details", {}, h("summary", { class: "small" }, "sources"),
          h("ul", { class: "plain small" }, g.observations.map((ob) => h("li", {}, link(ob.url, ob.supplier), ` ${money(ob.price, ob.currency)} (${ob.price_label}, ${day(ob.observed_at)})`)),
            g.set_aside.map((x) => h("li", { class: "muted" }, `Set aside: ${x.supplier} ${money(x.price, x.currency)}: ${x.reason}`))))),
        h("td", { class: "r num" }, g.count),
        h("td", { class: "r num" }, v(g.low)), h("td", { class: "r num" }, g.median != null ? v(g.median) : h("span", { class: "muted", title: g.median_note }, "n/a")),
        h("td", { class: "r num" }, v(g.high)),
        h("td", { class: "small" }, g.first_seen === g.last_seen ? g.first_seen : `${g.first_seen} to ${g.last_seen}`),
        h("td", { class: "small" }, g.differences.join(" ") || "-")))))) : null,
    (mv.valuations || []).length ? h("p", { class: "small" }, "Value estimates from price guides (not offers to sell): ",
      mv.valuations.map((r, i) => [i ? "; " : "", link(r.url, r.supplier), ` ${money(r.low, r.currency)}${r.high != null ? `–${money(r.high, r.currency)}` : ""} (${day(r.observed_at)})`])) : null,
    (mv.indicative_ranges || []).length ? h("p", { class: "small" }, "Indicative ranges (not single prices): ",
      mv.indicative_ranges.map((r, i) => [i ? "; " : "", link(r.url, r.supplier), ` ${money(r.low, r.currency)}–${r.high ?? "?"}${r.moq ? ` (${r.moq})` : ""}`])) : null,
    h("p", { class: "small muted", style: "margin:8px 0 0" }, `Basis: ${mv.basis_label}. ${mv.method} `, mv.notes.join(" ")));
}

// ------------------------------------------------------------------ table
function matchBadge(o) {
  const t = { exact: "Exact model", equivalent: "Equivalent by specs", variant: "Different variant",
    compatible: "Compatible / aftermarket", different: "Different model", unverified: "Not verified" }[o.match_level] || o.match_level;
  const cls = o.match_level === "exact" ? "exact" : (["unverified", "equivalent"].includes(o.match_level) ? "" : "warn");
  return h("span", { class: `badge ${cls}` }, t);
}
function deliveredCell(o) {
  const d = o.delivered;
  if (!d) return h("span", { class: "muted" }, "n/a");
  return h("div", { class: "price-cell" },
    h("span", { class: "v num" }, money(d.value, "CAD")),
    mark(d.label === "estimated" ? "estimated" : "calculated"),
    d.complete ? null : h("span", { class: "sub" }, `excludes ${d.missing.join(", ")}`));
}
// A table cell whose content stays in one block (so phone layout can label it)
function td(attrs, ...kids) { return h("td", attrs, h("div", { class: "cellv" }, ...kids)); }
function offerRow(o, res, colCount) {
  const rec = res.recommendations;
  const cls = ["offer", rec.best_value?.offer_id === o.id ? "pick" : "", rec.lowest?.offer_id === o.id ? "lowest" : ""].join(" ");
  const btn = h("button", { class: "toggle", type: "button", "aria-expanded": "false" }, "Details");
  const row = h("tr", { class: cls },
    td({ "data-label": "Supplier" }, h("div", { class: "sup" }, o.supplier),
      h("div", { class: "sub" }, `${o.supplier_type}, ${country(o.country)}`),
      rec.lowest?.offer_id === o.id ? h("div", { class: "badge" }, "Lowest comparable") : null,
      rec.best_value?.offer_id === o.id ? h("div", { class: "badge exact" }, "Best overall value") : null),
    td({ class: "prod", "data-label": "Product as listed" }, o.product_title, h("div", {}, matchBadge(o),
      o.condition && o.condition !== "new" ? [" ", h("span", { class: "badge warn" }, o.condition)] : null,
      o.is_reference ? [" ", h("span", { class: "badge" }, "Your link")] : null)),
    td({ class: "r", "data-label": "Advertised price" }, h("div", { class: "price-cell" },
      o.price != null ? h("span", { class: "v num" }, money(o.price, o.currency) + (o.price_high ? `–${Number(o.price_high).toFixed(2)}` : "") + perText(o)) :
        h("span", { class: "muted" }, o.price_type === "unclear" ? "unclear" : "not published"),
      priceMark(o))),
    td({ class: "r", "data-label": "Unit price" }, o.per_ft_cad != null ? h("div", { class: "price-cell" },
      h("span", { class: "num" }, money(o.per_ft_cad, "CAD")), h("span", { class: "sub" }, "per foot"),
      o.order_total_cad != null ? h("span", { class: "sub" }, `${money(o.order_total_cad, "CAD")} for your length`) : null, mark("calculated"))
      : o.unit_price_cad != null ? h("div", { class: "price-cell" },
      h("span", { class: "num" }, money(o.unit_price_cad, "CAD")), h("span", { class: "sub" }, o.pack_text), mark("calculated"))
      : h("span", { class: "muted" }, o.pack_qty ? "n/a" : "single / not stated")),
    td({ class: "r", "data-label": "In CAD" }, o.price_cad != null ? h("div", { class: "price-cell" }, h("span", { class: "num" }, (o.price_type === "range" ? "from " : "") + money(o.price_cad, "CAD")),
      o.currency !== "CAD" ? mark("calculated") : null) : h("span", { class: "muted" }, "n/a")),
    td({ class: "r", "data-label": "Delivered / landed" }, deliveredCell(o)),
    td({ class: "terms", "data-label": "Terms" },
      o.availability ? h("div", {}, o.availability) : null,
      o.shipping_text ? h("div", {}, o.shipping_text) : h("div", { class: "muted" }, "shipping not stated"),
      o.warranty ? h("div", {}, o.warranty) : null,
      o.moq ? h("div", {}, o.moq) : null,
      o.rating ? h("div", {}, `${o.rating.value}/${o.rating.best || 5} (${o.rating.count ?? "?"} ratings)`) : null),
    td({ "data-label": "Evidence" }, link(o.url, "Open", null, o.image), h("div", { class: "sub" }, day(o.observed_at)),
      o.flags.length ? h("div", { class: "flagcount" }, `${o.flags.length} flag${o.flags.length > 1 ? "s" : ""}`) : null),
    h("td", { class: "toggle-cell" }, btn));
  const detail = h("tr", { class: "detail", hidden: true }, h("td", { colspan: colCount }, offerDetail(o, res)));
  btn.addEventListener("click", () => {
    const open = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!open));
    detail.hidden = open;
  });
  return [row, detail];
}
function offerDetail(o, res) {
  const src = res.sources.find((s) => s.id === o.source_id);
  const d = o.delivered;
  return h("div", { class: "detail-grid" },
    h("div", {},
      h("h4", { style: "margin-top:0" }, "Where the price came from"),
      h("p", { style: "margin:0" }, priceMark(o), " ", o.price_label || ""),
      o.evidence_quote ? h("blockquote", { class: "evidence" }, o.evidence_quote) : null,
      h("dl", { class: "kv", style: "margin-top:10px" },
        h("dt", {}, "Observed"), h("dd", {}, when(o.observed_at), ` via ${o.provider}`),
        h("dt", {}, "Currency"), h("dd", {}, o.currency ? `${o.currency} (${o.currency_basis})` : "not stated"),
        o.fx_rate && o.currency !== "CAD" ? [h("dt", {}, "Exchange rate"), h("dd", {}, `1 ${o.currency} = ${o.fx_rate} CAD (Bank of Canada, ${o.fx_date})`)] : null,
        h("dt", {}, "Seller country"), h("dd", {}, `${country(o.country)} (${o.country_basis})`),
        h("dt", {}, "Model match"), h("dd", {}, (o.match_notes || []).join(" ")),
        (o.spec_confirmed || []).length || (o.spec_missing || []).length || (o.spec_conflicts || []).length ? [h("dt", {}, "Requested specs"), h("dd", {},
          [(o.spec_confirmed || []).length ? `States: ${o.spec_confirmed.join(", ")}.` : null,
           (o.spec_missing || []).length ? `Doesn't state: ${o.spec_missing.join(", ")}.` : null,
           ...(o.spec_conflicts || []).map((c) => `Differs: ${c}.`)].filter(Boolean).join(" "))] : null,
        o.per_length ? [h("dt", {}, "Priced per"), h("dd", {}, `${perText(o).replace(" / ", "")} (${o.per_length_text})`)] : null,
        Object.keys(o.identifiers || {}).length ? [h("dt", {}, "Identifiers"), h("dd", {}, Object.entries(o.identifiers).map(([k, v]) => `${k}: ${v}`).join(", "))] : null,
        Object.keys(o.specs || {}).length ? [h("dt", {}, "Specs on page"), h("dd", {}, Object.entries(o.specs).map(([k, v]) => `${k}: ${v}`).join("; "))] : null,
        o.bulk ? [h("dt", {}, "Bulk mention"), h("dd", {}, o.bulk)] : null,
        src ? [h("dt", {}, "Source"), h("dd", {}, `${src.id}: `, link(src.url, src.title))] : null),
      (o.flags.length || o.notes.length || o.exclusion_reasons.length) ? h("div", {},
        h("h4", {}, "Flags"),
        h("ul", { class: "bullets" },
          o.exclusion_reasons.map((r) => h("li", {}, `Not compared: ${r}`)),
          o.flags.map((f) => h("li", {}, f)), o.notes.map((n) => h("li", {}, n)))) : null),
    h("div", {},
      h("h4", { style: "margin-top:0" }, d ? (d.kind === "landed" ? "Landed cost (import)" : "Delivered cost") : "Delivered cost"),
      d ? h("table", { class: "costs" }, h("tbody", {},
        d.components.map((c) => h("tr", {}, h("td", {}, c.label, c.note ? h("div", { class: "sub" }, c.note) : null),
          h("td", {}, basisMark(c.basis)), h("td", { class: "r num" }, c.value == null ? "unknown" : money(c.value, "CAD")))),
        h("tr", { class: "total" }, h("td", {}, `Total${d.units > 1 ? ` for ${d.units} units` : ""}`), h("td", {}, mark(d.label === "estimated" ? "estimated" : "calculated")),
          h("td", { class: "r num" }, money(d.value, "CAD"))))) : h("p", { class: "muted" }, "No CAD price to build on."),
      d && d.missing.length ? h("p", { class: "small" }, `Not included (unknown): ${d.missing.join(", ")}. Add assumptions in the Import tab.`) : null,
      d && d.notes?.length ? h("p", { class: "small muted" }, d.notes.join(" ")) : null));
}
function comparisonTable(res) {
  const comparable = res.offers.filter((o) => o.comparable);
  const excluded = res.offers.filter((o) => !o.comparable);
  const head = () => h("thead", {}, h("tr", {},
    h("th", {}, "Supplier"), h("th", {}, "Product as listed"), h("th", { class: "r" }, "Advertised price"),
    h("th", { class: "r" }, "Unit price"), h("th", { class: "r" }, "In CAD"), h("th", { class: "r" }, "Delivered / landed"),
    h("th", {}, "Terms"), h("th", {}, "Evidence"), h("th", {}, h("span", { class: "sr-only" }, "Details"))));
  const COLS = 9;
  return h("section", { style: "margin-top:26px" },
    h("h2", {}, res.recommendation?.judge ? `Priced listings found (${comparable.length})` : `Comparable offers (${comparable.length})`),
    h("p", { class: "small muted", style: "margin-top:-4px" }, res.recommendation?.judge
      ? "Not ranked: these are for you to judge (see above). Shown by price only to make them easy to scan."
      : res.recommendations.basis
      ? `Ranked by ${res.recommendations.basis}. Same item, new condition, single published price, convertible to CAD.`
      : "Offers must be the same item, new, with a single published price convertible to CAD."),
    comparable.length ? h("div", { class: "table-wrap" }, h("table", { class: "cmp" }, head(),
      h("tbody", {}, comparable.map((o) => offerRow(o, res, COLS)))))
      : h("p", { class: "empty" }, "No offers met the comparison rules. See the listings below and the notes above."),
    specDiffs(res),
    excluded.length ? h("details", { class: "excluded" },
      h("summary", {}, `Not compared (${excluded.length}): quote-only, different variants, used/refurbished, ranges or unclear prices`),
      h("div", { class: "table-wrap" }, h("table", { class: "cmp" }, head(), h("tbody", {}, excluded.map((o) => {
        const [row, detail] = offerRow(o, res, COLS);
        row.children[1].firstChild.append(h("div", { class: "sub", style: "margin-top:4px;color:var(--risk)" }, `Not compared: ${o.exclusion_reasons.join("; ")}`));
        return [row, detail];
      }))))) : null);
}

function specDiffs(res) {
  const diffs = res.spec_differences || [];
  const specs = res.identity.key_specs || [];
  if (!diffs.length && !specs.length) return null;
  return h("details", { class: "excluded" },
    h("summary", {}, diffs.length ? `Spec differences between listings (${diffs.length})` : "Specs to compare"),
    specs.length ? h("p", { class: "small" }, "Specs that decide equivalence for this item (AI-suggested, check them on each listing): ", specs.join(", "), ".") : null,
    diffs.length ? h("table", { class: "simple" },
      h("thead", {}, h("tr", {}, h("th", {}, "Spec"), h("th", {}, "Values published on supplier pages"))),
      h("tbody", {}, diffs.map((d) => h("tr", {}, h("td", {}, d.spec),
        h("td", {}, d.values.map((v, i) => [i ? "; " : "", link(v.url, v.supplier), `: ${v.value}`, v.match_level !== "exact" ? ` (${v.match_level})` : ""]))))))
      : h("p", { class: "small muted" }, "No differing specs were published in supplier page data."));
}

// ------------------------------------------------------------------ tabs
const TABS = [["suppliers", "Suppliers & quotes"], ["quality", "Quality & reliability"], ["channels", "Buying channels"],
  ["import", "Import & landed cost"], ["coverage", "Coverage"], ["history", "Price history"], ["sources", "Sources & method"]];
function tabs(res) {
  const panel = h("div", { class: "tabpanel", role: "tabpanel", id: "tabpanel" });
  const bar = h("div", { class: "tabs", role: "tablist" }, TABS.map(([k, label]) => h("button", {
    role: "tab", type: "button", "aria-selected": String(state.tab === k), "aria-controls": "tabpanel",
    onclick: (e) => { state.tab = k; bar.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(b === e.currentTarget))); fillTab(panel, res); },
  }, label)));
  fillTab(panel, res);
  return h("section", {}, bar, panel);
}
function fillTab(panel, res) {
  const f = { suppliers: suppliersTab, quality: qualityTab, channels: channelsTab, import: importTab, coverage: coverageTab,
    history: historyTab, sources: sourcesTab }[state.tab] || suppliersTab;
  panel.replaceChildren(f(res));
  panel.classList.remove("swap"); void panel.offsetWidth; panel.classList.add("swap");
}
function srcRef(res, id) {
  const s = res.sources.find((x) => x.id === id);
  return s ? link(s.url, `${s.id} ${s.domain}`, "src-chip") : h("span", { class: "src-chip" }, id);
}

function contactLine(c, kind) {
  const value = kind === "email" ? h("a", { href: `mailto:${c.value}` }, c.value)
    : kind === "phone" ? h("a", { href: `tel:${c.value.split(/\s*(?:ext\.?|extension|x)\s*\d/i)[0].replace(/[^\d+]/g, "")}` }, c.value) : c.value;
  return h("div", {}, value, h("span", { class: "sub" }, ` from ${c.url ? "" : c.basis}`, c.url ? link(c.url, c.basis) : null,
    c.seen_at ? `, seen ${day(c.seen_at)}` : ""));
}
function suppliersTab(res) {
  const vs = res.vendors;
  if (!vs) return h("p", { class: "empty" }, "This comparison was saved before supplier records existed. Search again to build them.");
  const sum = res.vendor_summary || {};
  const drafts = Object.fromEntries((res.rfq_drafts || []).map((d) => [d.vendor_id, d]));
  const STATUS = { published: "Published price", quote_required: "Quote on request", no_price_seen: "No price seen" };
  return h("div", { class: "stack" },
    h("p", { class: "small muted", style: "margin:0" },
      `${sum.total || 0} suppliers: ${sum.local || 0} in Thunder Bay, ${sum.with_contact || 0} with contact details, `,
      `${sum.with_published_price || 0} with a published price, ${sum.quote_opportunities || 0} worth asking for a quote. `,
      "Local suppliers first. Every contact shows where it was copied from and when; nothing is guessed."),
    vs.length ? vs.map((v) => h("section", { class: `panel vendor tier-${v.tier || "none"}` },
      h("div", { class: "vhead" },
        h("h3", {}, v.website ? link(v.website, v.name) : v.name),
        h("span", { class: `badge ${v.tier === "local" ? "exact" : ""}`, title: v.tier_basis || "" }, v.tier_label),
        h("span", { class: `badge ${v.price_status === "published" ? "" : "warn"}` }, STATUS[v.price_status]),
        v.sells_trade ? h("span", { class: "badge" }, "Trade / volume") : null,
        v.business_kind === "service" ? h("span", { class: "badge", title: "Google Maps lists it as a contractor or service, not a supplier" }, "Contractor / service") : null),
      h("div", { class: "sub" }, [v.type !== "unknown" ? v.type : null, v.map_category].filter(Boolean).join(", ") || "business type not stated",
        v.tier_basis ? ` · location: ${v.tier_basis}` : ""),
      h("div", { class: "vgrid" },
        h("div", {},
          h("h4", {}, "Contact"),
          v.address ? contactLine(v.address, "address") : null,
          v.phones.map((p) => contactLine(p, "phone")),
          v.emails.map((e) => contactLine(e, "email")),
          !v.address && !v.phones.length && !v.emails.length ? h("p", { class: "empty", style: "margin:0" }, "No contact details found in the sources.") : null,
          v.map_listing ? h("div", { class: "small" }, link(v.map_listing, "Google Maps listing")) : null,
          v.rating ? h("div", { class: "small muted" }, `${v.rating.value}/5 from ${v.rating.count ?? "?"} reviews (${v.rating.basis})`) : null),
        h("div", {},
          h("h4", {}, "What they showed"),
          v.lowest ? h("div", {}, link(v.lowest.url, money(v.lowest.price, v.lowest.currency)), " ", h("span", { class: "sub" }, `${v.lowest.price_label}, ${day(v.lowest.observed_at)}${v.lowest.comparable ? "" : " (not comparable - see the offer)"}`)) : null,
          (v.sold_or_bid_prices || []).map((x) => h("div", { class: "small" }, link(x.url, money(x.price, x.currency)), " ",
            h("span", { class: "sub" }, `${x.price_kind === "completed_sale" ? "sold price (not an offer)" : "auction bid (not final)"}, ${day(x.observed_at)}`))),
          v.products.length ? h("ul", { class: "plain small" }, v.products.map((p) => h("li", {}, p))) : h("p", { class: "empty", style: "margin:0" }, "No product listing for this item was found on their site."),
          v.trade_signals.length ? h("div", { class: "small" }, "Trade terms seen: ", v.trade_signals.map((t, i) => [i ? "; " : "", `“${t.text}”`])) : null,
          v.badges.length ? h("div", { class: "small muted" }, `Marketplace badge: ${v.badges.join(", ")} (the marketplace's own label, not proof of quality or seller identity)`) : null),
        h("div", {},
          h("h4", {}, "Ask for a quote"),
          v.quote_opportunity ? h("p", { class: "small", style: "margin:0 0 6px" }, `Why: ${v.quote_reasons.join("; ")}.`)
            : h("p", { class: "empty", style: "margin:0" }, v.business_kind === "service"
              ? "A contractor or service, not a supplier: listed for reference. For the material alone, supply houses are usually cheaper."
              : "Published price available."),
          drafts[v.id] ? rfqBox(drafts[v.id]) : null))))
      : h("p", { class: "empty" }, "No suppliers were identified."));
}
function rfqBox(d) {
  const ta = h("textarea", { class: "rfq", rows: "9", readonly: true, "aria-label": `Quote request to ${d.vendor}` }, d.body);
  const msg = h("span", { class: "small muted", role: "status" });
  return h("div", {},
    h("div", { class: "actions" },
      d.mailto ? h("a", { class: "btn primary", href: d.mailto }, "Open in email") : null,
      h("button", { class: "btn", type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(`Subject: ${d.subject}\n\n${d.body}`); msg.textContent = "Copied."; }
        catch { ta.select(); msg.textContent = "Select and copy the text."; }
      } }, "Copy request"), msg),
    h("p", { class: "small muted", style: "margin:6px 0" }, d.to ? `To ${d.to} (${d.to_basis}). ` : d.phone ? `No email found: call ${d.phone} (${d.phone_basis}). ` : "No email or phone found: use their website's contact form. ",
      "Nothing is sent automatically."),
    h("details", {}, h("summary", { class: "small" }, "Show the draft"), ta));
}

function coverageTab(res) {
  const cov = res.coverage;
  if (!cov) return h("p", { class: "empty" }, "This comparison was saved before the coverage report existed. Search again to build it.");
  const f = cov.found;
  return h("div", { class: "stack" },
    h("section", { class: "panel" }, h("h3", {}, "What was found"),
      h("dl", { class: "kv" },
        h("dt", {}, "Suppliers"), h("dd", {}, `${f.vendors} distinct (${f.local_vendors} in Thunder Bay, ${f.map_listings} from map listings)`),
        h("dt", {}, "Offers"), h("dd", {}, `${f.offers} listings, ${f.priced_offers} with a price: ${f.verified_prices} verified on the page or listing, ${f.snippet_prices} from search snippets only`),
        h("dt", {}, "Quotes needed"), h("dd", {}, `${f.quote_required_vendors} quote on request; ${f.vendors_without_price} showed no price for this item`),
        h("dt", {}, "Other channels"), h("dd", {}, `${f.trade_prices} trade/wholesale prices, ${f.used_listings} used, ${f.auction_bids} auction bids, ${f.completed_sales} completed sales`),
        cov.deepened ? [h("dt", {}, "Depth"), h("dd", {}, cov.deepened)] : null,
        h("dt", {}, "Rounds"), h("dd", {}, cov.rounds.map((r) => `round ${r.round}: ${r.searches} searches, ${r.new_supplier_count} new suppliers, ${r.new_prices} new prices`).join("; ") || "n/a",
          cov.stop_reason ? `. Stopped: ${cov.stop_reason}.` : ""),
        h("dt", {}, "Local search"), h("dd", {}, cov.local_search || "n/a")),
      h("p", { class: "small muted", style: "margin:10px 0 0" }, cov.disclaimer)),
    h("section", { class: "panel" }, h("h3", {}, "Channels searched"),
      h("div", { class: "table-wrap", style: "border:0" }, h("table", { class: "simple" },
        h("thead", {}, h("tr", {}, h("th", {}, "Channel"), h("th", { class: "r" }, "Searches"), h("th", { class: "r" }, "Results"),
          h("th", { class: "r" }, "Sellers"), h("th", { class: "r" }, "Offers (priced)"), h("th", { class: "r" }, "Failed"))),
        h("tbody", {}, cov.channels.map((c) => h("tr", {}, h("td", {}, c.label), h("td", { class: "r num" }, c.searches),
          h("td", { class: "r num" }, c.results), h("td", { class: "r num" }, c.sellers),
          h("td", { class: "r num" }, `${c.offers} (${c.priced})`), h("td", { class: "r num" }, c.failed || "")))))),
      cov.not_relevant.length ? h("div", {}, h("h4", {}, "Not searched because they don't apply"),
        h("ul", { class: "bullets small" }, cov.not_relevant.map((c) => h("li", {}, `${c.label}: ${c.reason}.`)))) : null,
      cov.relevant_not_searched.length ? h("p", { class: "small" }, "Relevant but not reached within this depth's budget: ",
        cov.relevant_not_searched.map((c) => c.label.toLowerCase()).join(", "), ".") : null),
    h("section", { class: "panel" }, h("h3", {}, "Markets"),
      h("table", { class: "simple" }, h("thead", {}, h("tr", {}, h("th", {}, "Market"), h("th", { class: "r" }, "Searches"), h("th", { class: "r" }, "Results"), h("th", { class: "r" }, "Sellers"))),
        h("tbody", {}, cov.markets.map((m) => h("tr", {}, h("td", {}, m.label), h("td", { class: "r num" }, m.searches), h("td", { class: "r num" }, m.results), h("td", { class: "r num" }, m.sellers)))))),
    cov.inaccessible.length || cov.failed_searches.length ? h("section", { class: "panel" }, h("h3", {}, "Couldn't be reached"),
      h("p", { class: "small muted", style: "margin-top:0" }, "A page that couldn't be read may still sell the item."),
      h("ul", { class: "bullets small" },
        cov.inaccessible.map((x) => h("li", {}, link(x.url, x.domain), `: ${x.reason}`)),
        cov.failed_searches.map((x) => h("li", {}, `Search “${x.query}” failed: ${x.error || "error"}`)))) : null,
    cov.next_steps.length ? h("section", { class: "watch" }, h("h3", {}, "Gaps and next steps"),
      h("ul", { class: "bullets" }, cov.next_steps.map((n) => h("li", {}, n)))) : null);
}

function qualityTab(res) {
  const q = res.quality || {};
  const summ = q.summary;
  const quoteList = (items, empty) => items.length ? h("ul", { class: "plain quote-list" }, items.map((m) => h("li", {},
    h("q", {}, m.quote), " ", h("span", { class: "src-chip" }, `(${m.type}${m.exact_model ? ", exact model" : ""}) `), link(m.url, m.domain, "src-chip"))))
    : h("p", { class: "empty" }, empty);
  return h("div", { class: "stack" },
    summ ? h("section", { class: "panel" },
      h("h3", {}, "AI summary of review sources"),
      h("p", { class: "small muted", style: "margin-top:0" }, summ.label,
        summ.verification ? ` ${summ.verification.points_kept} point(s) kept, ${summ.verification.points_rejected} dropped by the checks (quotes not found word-for-word, too short, or figures not in the quotes).` : ""),
      summ.overall_note ? h("p", {}, h("span", { class: "muted" }, `${summ.overall_note_label || "AI comment"}: `), summ.overall_note) : null,
      [["praise", "Recurring praise"], ["criticism", "Recurring criticism"], ["reliability_issues", "Reliability issues"]].map(([k, label]) =>
        h("div", {}, h("h4", {}, label), (summ[k] || []).length ? (summ[k] || []).map((p) => h("div", { class: "point" },
          h("div", { class: "p" }, p.point, " ", p.support ? h("span", { class: `badge ${p.support.pattern ? "exact" : "warn"}` }, p.support.label) : null,
            " ", p.source_ids.map((id) => [" ", srcRef(res, id)])),
          p.quotes.map((qt) => h("div", { class: "q" }, h("q", {}, qt))))) : h("p", { class: "empty" }, "None found in the sources.")))) :
      h("p", { class: "small muted" }, "AI summary is off (no Anthropic key configured). Below are the review sources and verbatim excerpts found by search."),
    (q.themes || []).length ? h("section", { class: "panel" }, h("h3", {}, "Themes in reviews and discussions"),
      h("p", { class: "small muted", style: "margin-top:0" }, q.themes_note),
      h("table", { class: "simple" }, h("tbody", {}, q.themes.map((t) => h("tr", {},
        h("td", {}, h("b", {}, t.theme), h("div", { class: "sub" }, t.kind === "concern" ? "concern" : "praise")),
        h("td", {}, h("span", { class: `badge ${t.pattern ? (t.kind === "concern" ? "warn" : "exact") : ""}` }, t.label),
          h("div", { class: "sub" }, `${t.mentions} mention(s), ${t.exact_model_mentions} about the exact model`)),
        h("td", { class: "small" }, t.quotes.map((qt, i) => [i ? h("br") : null, h("q", {}, qt.quote), " ", link(qt.url, qt.domain, "src-chip")]))))))) : null,
    h("div", { class: "grid-2" },
      h("section", { class: "panel" }, h("h3", {}, "Customer ratings"),
        h("p", { class: "small muted", style: "margin-top:0" }, q.ratings_note),
        (q.ratings || []).length ? h("table", { class: "simple" }, h("tbody", {}, q.ratings.map((r) => h("tr", {},
          h("td", { class: "num" }, `${r.value}/${r.best}`), h("td", {}, `${r.count ?? "?"} ratings`),
          h("td", {}, link(r.url, r.supplier), h("div", { class: "sub" }, r.basis, r.exact_model ? "" : " (not the exact model)")))))) : null),
      h("section", { class: "panel" }, h("h3", {}, "Recalls and safety"),
        h("p", { style: "margin-top:0" }, q.recall_note),
        quoteList(q.recall_mentions || [], ""),
        h("p", { class: "small" }, "Check the official list: ", link(res.import_links?.recalls, "Government of Canada recalls")))),
    h("div", { class: "grid-2" },
      h("section", { class: "panel" }, h("h3", {}, "Reported problems (verbatim excerpts)"),
        quoteList(q.issue_mentions || [], "No problem reports appeared in the search snippets.")),
      h("section", { class: "panel" }, h("h3", {}, "Positive mentions (verbatim excerpts)"),
        quoteList(q.praise_mentions || [], "No independent praise appeared in the search snippets."))),
    h("section", { class: "panel" }, h("h3", {}, "Review and discussion sources"),
      Object.keys(q.sources_by_type || {}).length ? Object.entries(q.sources_by_type).map(([type, items]) => h("div", {},
        h("h4", {}, `${type} (${items.length})`),
        h("ul", { class: "plain quote-list" }, items.map((s) => h("li", {}, link(s.url, s.title),
          s.exact_model ? [" ", h("span", { class: "badge exact" }, "exact model")] : null,
          h("div", { class: "small muted" }, s.excerpt)))))) : h("p", { class: "empty" }, "No review sources were found.")));
}

function channelsTab(res) {
  const chs = res.channels || [];
  return h("div", { class: "stack" },
    chs.length ? chs.map((c) => h("section", { class: "panel" },
      h("h3", {}, `${c.type[0].toUpperCase()}${c.type.slice(1)} (${c.listing_count} listing${c.listing_count > 1 ? "s" : ""})`),
      h("p", { style: "margin-top:0" }, c.suppliers.join(", ")),
      h("dl", { class: "kv" },
        c.lowest_observed ? [h("dt", {}, "Lowest comparable price"), h("dd", {}, c.lowest_observed)] : null,
        c.quote_required.length ? [h("dt", {}, "Quote required"), h("dd", {}, c.quote_required.map((x, i) => [i ? ", " : "", link(x.url, x.supplier)]))] : null,
        c.moq.length ? [h("dt", {}, "Minimum order"), h("dd", {}, c.moq.map((x, i) => [i ? "; " : "", `${x.supplier}: ${x.moq}`]))] : null,
        c.bulk_signals.length ? [h("dt", {}, "Bulk pricing mentioned"), h("dd", {}, c.bulk_signals.map((x, i) => [i ? "; " : "", link(x.url, x.supplier), ` (“${x.signal}”)`]))] : null,
        c.pack_sizes.length ? [h("dt", {}, "Pack sizes"), h("dd", {}, c.pack_sizes.map((x, i) => [i ? "; " : "", `${x.supplier}: ${x.pack} = ${money(x.unit_price_cad, "CAD")}/unit`]))] : null,
        c.price_ranges.length ? [h("dt", {}, "Price ranges"), h("dd", {}, c.price_ranges.map((x, i) => [i ? "; " : "", link(x.url, x.supplier), ` ${money(x.low, x.currency)}–${x.high ?? "?"}`]))] : null),
      h("p", { class: "small muted" }, "General guidance: ", c.guidance)))
      : h("p", { class: "empty" }, "No seller channels were identified."),
    h("section", { class: "panel" }, h("h3", {}, "Similar or alternative items seen (not equivalent)"),
      (res.alternatives || []).length ? h("ul", { class: "plain quote-list" }, res.alternatives.map((a) => h("li", {},
        link(a.url, a.title), ` at ${a.supplier}. `, h("span", { class: "small muted" }, (a.notes || []).join(" "))))) :
        h("p", { class: "empty" }, "None were found."),
      (res.alternatives_ai || []).length ? [h("h4", {}, "Mentioned by sources (AI-read, quote verified)"),
        h("ul", { class: "plain quote-list" }, res.alternatives_ai.map((a) => h("li", {}, h("b", {}, a.name), " ",
          h("q", {}, a.quote), " ", srcRef(res, a.source_id))))] : null));
}

function importTab(res) {
  const a = state.comparison.assumptions && Object.keys(state.comparison.assumptions).length ? state.comparison.assumptions : res.assumptions || {};
  const field = (name, label, hint) => h("label", {}, label,
    h("input", { type: "number", step: "any", min: "0", name, value: a[name] ?? "", placeholder: hint }));
  const form = h("form", { class: "assume" },
    field("intl_shipping_cad", "Shipping for an import order (CAD)", "unknown"),
    field("domestic_shipping_cad", "Shipping when not stated, Canada (CAD)", "unknown"),
    field("duty_pct", "Customs duty (%)", "look up HS code"),
    field("surtax_pct", "Surtax (%)", "check CBSA notices"),
    field("brokerage_cad", "Brokerage / clearance per order (CAD)", "unknown"),
    h("label", {}, "Quantity needed", h("input", { type: "number", min: "0", step: "1", name: "quantity", value: res.quantity ?? "", placeholder: "optional" })),
    h("div", {}, h("button", { class: "btn primary", type: "submit" }, "Recalculate")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const assumptions = {};
    for (const k of ["intl_shipping_cad", "domestic_shipping_cad", "duty_pct", "surtax_pct", "brokerage_cad"]) {
      const v = fd.get(k); if (v !== "" && v !== null) assumptions[k] = Number(v);
    }
    const quantity = fd.get("quantity") ? Number(fd.get("quantity")) : 0;
    const r = await api(`/api/comparisons/${state.comparison.id}/assumptions`, { method: "PUT", body: JSON.stringify({ assumptions, quantity }) });
    if (r.ok) { state.comparison = r.body; state.tab = "import"; renderComparison(); }
  });
  const intl = res.offers.filter((o) => o.price != null && o.country !== "CA");
  return h("div", { class: "stack" },
    h("section", { class: "panel" },
      h("h3", {}, "Your assumptions"),
      h("p", { class: "small muted", style: "margin-top:0" }, "Nothing here is assumed for you. Leave a field blank to keep it unknown. Totals that use these values are marked ", mark("estimated"), ". No new search is run."),
      form),
    h("section", { class: "panel" },
      h("h3", {}, `Listings from outside Canada or with unknown country (${intl.length})`),
      intl.length ? h("table", { class: "simple" },
        h("thead", {}, h("tr", {}, h("th", {}, "Supplier"), h("th", {}, "Country"), h("th", { class: "r" }, "Listed"),
          h("th", { class: "r" }, "In CAD"), h("th", { class: "r" }, "Landed estimate"), h("th", {}, "Not included"))),
        h("tbody", {}, intl.map((o) => h("tr", {},
          h("td", {}, link(o.url, o.supplier, null, o.image)), h("td", {}, `${country(o.country)}`),
          h("td", { class: "r num" }, money(o.price, o.currency) + (o.price_high ? `–${Number(o.price_high).toFixed(2)}` : "")),
          h("td", { class: "r num" }, o.price_cad != null ? [money(o.price_cad, "CAD"), " ", mark("calculated")] : "no FX rate"),
          h("td", { class: "r num" }, o.delivered ? [money(o.delivered.value, "CAD"), " ", mark(o.delivered.label === "estimated" ? "estimated" : "calculated")] : "n/a"),
          h("td", { class: "small" }, o.delivered?.missing?.join(", ") || "nothing")))))
        : h("p", { class: "empty" }, "All priced listings are from Canadian sellers.")),
    Object.keys(res.fx || {}).length ? h("section", { class: "panel" }, h("h3", {}, "Exchange rates used"),
      h("ul", { class: "plain" }, Object.entries(res.fx).map(([cur, r]) => h("li", {}, `1 ${cur} = ${r.rate_to_cad} CAD `, mark("quoted"), ` ${r.source}, ${r.rate_date}`)))) : null,
    res.import_checklist ? h("section", { class: "panel" }, h("h3", {}, res.import_checklist.applies ? "Import checklist" : "Import checklist (no import listings priced, shown for reference)"),
      h("p", { class: "small muted", style: "margin-top:0" }, res.import_checklist.note, ` Reviewed ${res.import_checklist.reviewed}.`),
      h("table", { class: "simple" }, h("tbody", {}, res.import_checklist.items.map((i) => h("tr", {},
        h("td", {}, h("b", {}, i.topic)), h("td", {}, h("span", { class: `badge ${i.status === "known" ? "exact" : (i.status === "unknown" ? "warn" : "")}` },
          { known: "Known", unknown: "Unknown", assumption: "Your assumption", rule: "Rule", check: "Check" }[i.status] || i.status)),
        h("td", { class: "small" }, i.text, i.link ? [" ", link(i.link, "Official source")] : null)))))) : null,
    h("section", { class: "panel" }, h("h3", {}, "Canadian import considerations"),
      h("ul", { class: "plain quote-list" }, (res.import_notes || []).map((n) => h("li", {}, h("b", {}, n.topic), ". ", n.text,
        n.link ? [" ", link(n.link, "Official source")] : null)))));
}

function historyTab(res) {
  const box = h("div", { class: "stack" }, h("p", { class: "muted" }, "Loading price observations…"));
  const render = (hist) => {
    const obs = hist.observations;
    box.replaceChildren(
      h("section", { class: "panel" },
        h("h3", {}, "Price over time (CAD, exact-model new listings)"),
        hist.chartable ? chart(hist) : h("p", { style: "margin-top:0" }, hist.reason),
        h("p", { class: "small muted" }, "Only real observations from your searches are stored. Nothing is interpolated or projected.")),
      h("section", { class: "panel" },
        h("h3", {}, `All recorded observations (${obs.length})`),
        obs.length ? h("div", { class: "table-wrap", style: "border:0" }, h("table", { class: "simple" },
          h("thead", {}, h("tr", {}, h("th", {}, "Observed"), h("th", {}, "Supplier"), h("th", {}, "Product"),
            h("th", { class: "r" }, "Price"), h("th", { class: "r" }, "CAD"), h("th", {}, "Evidence"), h("th", {}, "Match"))),
          h("tbody", {}, obs.slice().reverse().map((o) => h("tr", {},
            h("td", { class: "num" }, when(o.observed_at)), h("td", {}, link(o.url, o.supplier || o.supplier_domain)),
            h("td", {}, o.product_title), h("td", { class: "r num" }, money(o.price, o.currency)),
            h("td", { class: "r num" }, o.price_cad != null ? money(o.price_cad, "CAD") : "n/a"),
            h("td", {}, o.price_basis.replace("_", " ")), h("td", {}, o.match_level || "")))))) : h("p", { class: "empty" }, "No prices recorded yet.")));
  };
  if (state.history) render(state.history);
  else api(`/api/comparisons/${state.comparison.id}/history`).then((r) => { state.history = r.body; render(r.body); });
  return box;
}

function chart(hist) {
  const NS = "http://www.w3.org/2000/svg";
  const s = (tag, attrs, ...kids) => { const el = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v); kids.forEach((k) => el.append(k)); return el; };
  const series = Object.entries(hist.series).filter(([, pts]) => pts.length)
    .sort((a, b) => b[1].length - a[1].length).slice(0, 8);
  const all = series.flatMap(([, p]) => p);
  const t = all.map((p) => new Date(p.observed_at).getTime());
  const v = all.map((p) => p.price_cad);
  const W = 860, H = 300, L = 64, R = 150, T = 16, B = 34;
  const t0 = Math.min(...t), t1 = Math.max(...t) || t0 + 1;
  let v0 = Math.min(...v), v1 = Math.max(...v);
  const pad = (v1 - v0) * 0.15 || v1 * 0.05 || 1; v0 = Math.max(0, v0 - pad); v1 = v1 + pad;
  const x = (ms) => L + (t1 === t0 ? (W - L - R) / 2 : (ms - t0) / (t1 - t0) * (W - L - R));
  const y = (val) => T + (1 - (val - v0) / (v1 - v0)) * (H - T - B);
  const svg = s("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Observed prices in CAD over time by supplier" });
  const grid = s("g", { class: "grid" }), axis = s("g", { class: "axis" });
  for (let i = 0; i <= 4; i++) {
    const val = v0 + (v1 - v0) * i / 4, yy = y(val);
    grid.append(s("line", { x1: L, x2: W - R, y1: yy, y2: yy }));
    const tx = s("text", { x: L - 8, y: yy + 4, "text-anchor": "end" }); tx.textContent = `$${val.toFixed(0)}`; axis.append(tx);
  }
  const days = [...new Set(t.map((ms) => new Date(ms).toISOString().slice(0, 10)))].sort();
  const step = Math.max(1, Math.ceil(days.length / 6));
  days.forEach((d, i) => { if (i % step) return; const tx = s("text", { x: x(new Date(d + "T12:00:00Z").getTime()), y: H - 10, "text-anchor": "middle" }); tx.textContent = day(d + "T12:00:00Z"); axis.append(tx); });
  svg.append(grid, axis);
  const tip = document.querySelector(".tip") || document.body.appendChild(h("div", { class: "tip", hidden: true }));
  const legendEl = h("div", { class: "chart-legend" });
  series.forEach(([name, pts], i) => {
    const color = `var(--series-${i + 1})`;
    const sorted = pts.slice().sort((a, b) => a.observed_at.localeCompare(b.observed_at));
    const g = s("g", { class: "series" });
    g.append(s("path", { d: sorted.map((p, j) => `${j ? "L" : "M"}${x(new Date(p.observed_at).getTime()).toFixed(1)},${y(p.price_cad).toFixed(1)}`).join(" "), stroke: color }));
    sorted.forEach((p) => {
      const c = s("circle", { cx: x(new Date(p.observed_at).getTime()), cy: y(p.price_cad), r: 5, fill: color, tabindex: "0" });
      const label = `${name}: ${money(p.price_cad, "CAD")} on ${when(p.observed_at)} (${p.basis.replace("_", " ")})`;
      c.append(s("title", {}, label));
      const show = (ev) => { tip.textContent = label; tip.hidden = false; const r = c.getBoundingClientRect(); tip.style.left = `${r.left + 10}px`; tip.style.top = `${r.top - 36}px`; };
      c.addEventListener("mouseenter", show); c.addEventListener("focus", show);
      c.addEventListener("mouseleave", () => { tip.hidden = true; }); c.addEventListener("blur", () => { tip.hidden = true; });
      g.append(c);
    });
    if (series.length <= 4) {
      const last = sorted[sorted.length - 1];
      const tx = s("text", { class: "lbl", x: x(new Date(last.observed_at).getTime()) + 10, y: y(last.price_cad) + 4 });
      tx.textContent = name.length > 20 ? name.slice(0, 19) + "…" : name; g.append(tx);
    }
    svg.append(g);
    legendEl.append(h("span", {}, h("i", { style: `background:${color}` }), name));
  });
  return h("div", {}, series.length > 1 ? legendEl : null, svg);
}

function sourcesTab(res) {
  const counts = res.counts || {};
  return h("div", { class: "stack" },
    h("section", { class: "panel" }, h("h3", {}, "How this was researched"),
      h("dl", { class: "kv" },
        h("dt", {}, "Researched"), h("dd", {}, `${when(res.researched_at)}, took ${res.duration_s}s, ${res.depth} depth`),
        h("dt", {}, "Search providers"), h("dd", {}, [res.providers.web, res.providers.shopping].filter(Boolean).join(" and ")),
        h("dt", {}, "AI reading"), h("dd", {}, res.providers.llm ? `${res.providers.llm} (facts verified against source text)` : "off"),
        h("dt", {}, "Usage"), h("dd", {}, Object.entries(res.credits || {}).filter(([k]) => k !== "llm_usage").map(([k, v]) => `${k.replace(/_/g, " ")}: ${tokensText(v)}`).join(", ") || "n/a",
          res.credits?.llm_usage ? `; AI tokens: ${Object.entries(res.credits.llm_usage).filter(([, u]) => u).map(([k, u]) => `${k.replace(/_/g, " ")} ${tokensText(u)}`).join(", ")}` : ""),
        h("dt", {}, "Estimated cost"), h("dd", {}, res.cost_estimate?.usd != null
          ? `about US$${res.cost_estimate.usd.toFixed(2)} in Anthropic charges (list prices checked ${res.cost_estimate.prices_checked}; the Anthropic Console shows actual charges)`
          : (res.credits?.llm_usage || res.credits?.anthropic_web_searches ? "not available for this model" : "no Anthropic charges")),
        h("dt", {}, "Supplier pages read"), h("dd", {}, `${(res.fetch?.attempted || 0) - (res.fetch?.failed || 0)} of ${res.fetch?.attempted || 0}`
          + (res.fetch?.via_anthropic ? ` (${res.fetch.via_anthropic} as text via Anthropic web fetch, because this server couldn't connect)` : "")
          + (res.fetch?.robots_respected ? "; robots.txt respected" : "")),
        h("dt", {}, "Evidence"), h("dd", {}, `${counts.sources} sources, ${counts.offers} listings, ${counts.priced} with prices, ${counts.comparable} comparable`))),
    h("section", { class: "panel" }, h("h3", {}, "Searches run"),
      h("table", { class: "simple" }, h("thead", {}, h("tr", {}, h("th", {}, "Query"), h("th", {}, "Channel / market"), h("th", {}, "Provider"), h("th", {}, "Result"))),
        h("tbody", {}, res.queries.map((q) => h("tr", {}, h("td", {}, q.query, q.domains?.length ? h("div", { class: "sub" }, `on ${q.domains.join(", ")}`) : null,
          q.lead ? h("div", { class: "sub" }, `follow-up: ${q.lead}`) : null),
          h("td", {}, (q.channel || q.purpose).replace(/_/g, " "), h("div", { class: "sub" }, [q.market, q.round ? `round ${q.round}` : null].filter(Boolean).join(", "))), h("td", {}, q.provider || ""),
          h("td", {}, q.status === "ok" ? `${q.result_count} results` : h("span", { style: "color:var(--risk)" }, `${q.status}: ${q.error?.message || ""}`))))))),
    h("section", { class: "panel" }, h("h3", {}, `Sources (${res.sources.length})`),
      h("div", { class: "table-wrap", style: "border:0" }, h("table", { class: "simple" },
        h("thead", {}, h("tr", {}, h("th", {}, "ID"), h("th", {}, "Source"), h("th", {}, "Type"), h("th", {}, "Retrieved"), h("th", {}, "Page read"))),
        h("tbody", {}, res.sources.map((s) => h("tr", {}, h("td", {}, s.id), h("td", {}, link(s.url, s.title), h("div", { class: "sub" }, s.domain)),
          h("td", {}, s.type, s.country ? h("div", { class: "sub" }, country(s.country)) : null), h("td", { class: "num" }, when(s.retrieved_at)),
          h("td", { class: "small" }, s.fetch ? (s.fetch.ok ? (s.fetch.via ? `yes, as text via ${s.fetch.via}, copy dated ${day(s.fetch.fetched_at)} (direct: ${s.fetch.direct_error || "failed"})` : s.fetch.structured ? "yes, price data found" : "yes, no price data") : `no: ${s.fetch.error}`) : "not attempted")))))) ),
    h("section", { class: "panel" }, h("h3", {}, "Limits of this research"),
      h("ul", { class: "bullets" }, res.limits.map((l) => h("li", {}, l)))));
}

// ------------------------------------------------------------------ boot
loadStatus().then(route);
