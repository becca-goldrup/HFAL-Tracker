/* NY Hospital Financial Assistance Tracker - dashboard logic.
   Reads data/hospitals.json (made by tools/build_dashboard.py). No build step needed. */
"use strict";

const GRADES = ["A", "B", "C", "D", "F"];
// Map dots sit on light map tiles in both themes, so they always use the light-mode set.
const MAP_COLORS = { A: "#262262", B: "#0080a0", C: "#9a9890", D: "#e9a533", F: "#c4471b", R: "#ffffff" };
const state = {
  data: null,
  filters: { search: "", region: "", system: "", grade: "", criterion: "" },
  sort: { key: "name", dir: 1 },
  map: null, markers: null, mapFitted: false,
  lastFocus: null,
  lang: (() => { try { return localStorage.getItem("hfal-lang") || "en"; } catch { return "en"; } })(),
};

/* ---------------------------------------------------------------- helpers */
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
const pct = (n, d) => (d ? Math.round((100 * n) / d) : 0);
const isRange = (h) => h.grade_best !== h.grade_worst;
const gradeClass = (h) => (isRange(h) ? "g-R" : `g-${h.grade}`);
const gradeRank = (h) => GRADES.indexOf(h.grade_worst) + (isRange(h) ? 0.5 : 0);
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const criterion = (key) => state.data.criteria.find((c) => c.key === key);
// Language: public tabs can show Spanish (docs/i18n.js); the staff tab stays English.
const hasES = () => typeof ES_UI !== "undefined";
const t = (en, vars = {}) => ((state.lang === "es" && hasES() && ES_UI[en]) || en).replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? ""));
const cLabel = (c) => (state.lang === "es" && hasES() && ES_CRITERIA[c.key] ? ES_CRITERIA[c.key][0] : c.label);
const cLaw = (c) => (state.lang === "es" && hasES() && ES_CRITERIA[c.key] ? ES_CRITERIA[c.key][1] : c.law);

const nyToday = () => new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });

/* ---------------------------------------------------------------- load */
fetch("data/hospitals.json")
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((pub) => {
    if (!pub.datasets) {  // older single-dataset data file
      pub = Object.assign({}, pub, { published: { dataset: "baseline" },
        datasets: { baseline: { label: pub.source, source: pub.source, generated: pub.generated, hospitals: pub.hospitals } } });
    }
    state.pub = pub;
    state.data = { repo: pub.repo, generated: pub.generated, fpl_year: pub.fpl_year, criteria: pub.criteria,
                   policy_statement_auto_fail: pub.policy_statement_auto_fail };
    useDataset(previewChoice() || pub.published.dataset);
    init();
  })
  .catch((e) => {
    $("main").innerHTML = `<div class="card">Could not load the data (${esc(e.message)}).
      If you opened this file directly, serve the docs/ folder instead (see README).</div>`;
  });

function init() {
  applyStatic();
  $("#lang-toggle").addEventListener("click", () => setLang(state.lang === "es" ? "en" : "es"));
  buildFilters();
  renderRubric();
  renderCriteriaGuide();
  bindEvents();
  showTab((location.hash || "#overview").slice(1));
  render();
}

/* ---------------------------------------------------------------- filters */
function buildFilters() {
  const hs = state.data.hospitals;
  const counties = [...new Set(hs.map((h) => h.county).filter(Boolean))].sort();
  $("#f-region").innerHTML = `<option value="">${t("All of New York")}</option>
    <option value="nyc">${t("New York City")}</option><option value="non-nyc">${t("Outside New York City")}</option>
    <optgroup label="${t("County")}">${counties.map((c) => `<option value="county:${esc(c)}">${esc(c)}</option>`).join("")}</optgroup>`;
  const systems = [...new Set(hs.map((h) => h.system))].sort((a, b) => a.localeCompare(b));
  $("#f-system").innerHTML = `<option value="">${t("All systems")}</option>` +
    systems.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  const hasRanges = hs.some(isRange);
  $("#f-grade").innerHTML = `<option value="">${t("All grades")}</option>` +
    GRADES.map((g) => `<option value="${g}">${g}</option>`).join("") +
    (hasRanges ? `<option value="range">${t("Grade pending review")}</option>` : "");
  $("#f-criterion").innerHTML = `<option value="">${t("Any requirement")}</option>` +
    state.data.criteria.map((c) => `<option value="${c.key}">${esc(cLabel(c))}</option>`).join("");
  // keep the current choices when the lists are rebuilt (e.g. after switching language)
  ["region", "system", "grade", "criterion"].forEach((k) => { const el = $(`#f-${k}`); if (el) el.value = state.filters[k] || ""; });
}

function filtered() {
  const f = state.filters;
  const q = f.search.trim().toLowerCase();
  return state.data.hospitals.filter((h) => {
    if (q && !`${h.name} ${h.city} ${h.system} ${h.county}`.toLowerCase().includes(q)) return false;
    if (f.region === "nyc" && !h.nyc) return false;
    if (f.region === "non-nyc" && h.nyc) return false;
    if (f.region.startsWith("county:") && h.county !== f.region.slice(7)) return false;
    if (f.system && h.system !== f.system) return false;
    if (f.grade === "range" && !isRange(h)) return false;
    if (f.grade && f.grade !== "range" && (isRange(h) || h.grade !== f.grade)) return false;
    if (f.criterion && h.criteria[f.criterion] !== "no") return false;
    return true;
  });
}

function setFilter(key, value) {
  state.filters[key] = value;
  const el = { search: "#f-search", region: "#f-region", system: "#f-system", grade: "#f-grade", criterion: "#f-criterion" }[key];
  $(el).value = value;
  render();
}

/* ---------------------------------------------------------------- events */
function bindEvents() {
  document.querySelectorAll(".tabs button").forEach((b) =>
    b.addEventListener("click", () => { location.hash = b.dataset.tab; }));
  window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
  const on = (sel, key, ev = "change") => $(sel).addEventListener(ev, (e) => { state.filters[key] = e.target.value; render(); });
  on("#f-search", "search", "input");
  on("#f-region", "region"); on("#f-system", "system"); on("#f-grade", "grade"); on("#f-criterion", "criterion");
  $("#f-reset").addEventListener("click", () => {
    Object.keys(state.filters).forEach((k) => (state.filters[k] = ""));
    ["#f-search", "#f-region", "#f-system", "#f-grade", "#f-criterion"].forEach((s) => ($(s).value = ""));
    render();
  });
  document.querySelectorAll("th[data-sort]").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.sort;
    state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : 1 };
    renderTable(filtered());
  }));
  $("#table tbody").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-id]"); if (tr) openDrawer(+tr.dataset.id);
  });
  $("#table tbody").addEventListener("keydown", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openDrawer(+tr.dataset.id); }
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-open-id]"); if (b) openDrawer(+b.dataset.openId);
    const g = e.target.closest("[data-goto-grade]");
    if (g) { setFilter("grade", g.dataset.gotoGrade); location.hash = "hospitals"; }
    const c = e.target.closest("[data-goto-criterion]");
    if (c) { setFilter("criterion", c.dataset.gotoCriterion); location.hash = "hospitals"; }
  });
  $("#d-close").addEventListener("click", closeDrawer);
  $("#drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#drawer").hidden) closeDrawer(); });
}

function showTab(route) {
  let [tab, sub] = String(route || "").split("/");
  if (tab === "health") { tab = "staff"; sub = "health"; }  // old links
  if (!["overview", "hospitals", "map", "staff"].includes(tab)) tab = "overview";
  // The public filters don't apply to the staff tab.
  document.querySelector('section.filters[aria-label="Filters"]').hidden = tab === "staff";
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== `panel-${tab}`));
  window.scrollTo(0, 0);
  if (tab === "map") { initMap(); state.map.invalidateSize(); renderMap(filtered()); }
  if (tab === "staff") ensureStaff().then(() => showStaffSection(sub));
}

/* ---------------------------------------------------------------- render */
function render() {
  const list = filtered();
  const total = state.data.hospitals.length;
  $("#f-count").textContent = list.length === total ? t("Showing all {n} hospitals", { n: total })
    : t("Showing {a} of {b} hospitals", { a: list.length, b: total });
  renderOverview(list);
  renderTable(list);
  if (state.map) renderMap(list);
}

function renderOverview(list) {
  const n = list.length;
  const graded = list.filter((h) => !isRange(h));
  const countA = graded.filter((h) => h.grade === "A").length;
  const countF = graded.filter((h) => h.grade === "F").length;
  const stats = criteriaStats(list);
  const worst = stats.filter((s) => s.yes + s.no > 0).sort((a, b) => a.rate - b.rate)[0];
  const filteredView = n !== state.data.hospitals.length;
  $("#tiles").innerHTML = [
    tile(t("Hospitals"), n, list.some(isRange) ? t("{n} with grades pending review", { n: list.filter(isRange).length }) : t(filteredView ? "in this view" : "statewide")),
    tile(t("Meet every requirement"), countA, t("{p}% of hospitals", { p: pct(countA, n) })),
    tile(t("Graded F"), countF, t("{p}% of hospitals", { p: pct(countF, n) })),
    worst ? tile(t("Biggest gap"), esc(cLabel(worst)), t("only {p}% meet it", { p: worst.rate }), true) : tile(t("Biggest gap"), "–", ""),
  ].join("");

  // Grades
  const rows = GRADES.map((g) => ({ g, count: graded.filter((h) => h.grade === g).length }));
  const ranges = list.filter(isRange).length;
  const max = Math.max(1, ...rows.map((r) => r.count), ranges);
  $("#grade-chart").innerHTML = rows.map((r) => `
      <button class="hbar clickable" data-goto-grade="${r.g}" title="${r.count} hospitals graded ${r.g}. Select to list them.">
        <span class="lbl"><span class="badge g-${r.g}">${r.g}</span></span>
        <span class="track"><span class="fill" style="width:${(100 * r.count) / max}%;background:var(--g-${r.g})"></span></span>
        <span class="val">${pct(r.count, n)}% <span class="of">(${r.count})</span></span>
      </button>`).join("") + (ranges ? `
      <button class="hbar clickable" data-goto-grade="range" title="Grades that depend on items still under review">
        <span class="lbl"><span class="badge g-R">?</span></span>
        <span class="track"><span class="fill" style="width:${(100 * ranges) / max}%;background:var(--muted)"></span></span>
        <span class="val">${pct(ranges, n)}% <span class="of">(${ranges})</span></span>
      </button>` : "");

  // Requirements
  const sorted = [...stats].sort((a, b) => a.rate - b.rate);
  $("#criteria-chart").innerHTML = sorted.map((s) => `
      <button class="hbar clickable" data-goto-criterion="${s.key}"
        title="${s.yes} meet it · ${s.no} fall short${s.review ? ` · ${s.review} need review` : ""}. Select to list hospitals that fall short.">
        <span class="lbl">${esc(cLabel(s))}<span class="sec">${esc(sectionName(s.section))}</span></span>
        <span class="track"><span class="fill" style="width:${s.rate}%"></span></span>
        <span class="val">${s.rate}% <span class="of">${s.yes}/${s.yes + s.no}</span></span>
      </button>`).join("");

}

function renderRubric() {
  const total = state.data.criteria.length;
  const autoF = [t("no financial assistance application is posted"), t("the application is not the full NYS Uniform Application")];
  if (state.data.policy_statement_auto_fail) autoF.push(t("the full financial assistance policy is not posted"));
  const rows = [
    ["A", t("Meets all {n} requirements.", { n: total })],
    ["B", t("Falls short on 1 to 3 requirements.")],
    ["C", t("Falls short on 4 to 6 requirements.")],
    ["D", t("Falls short on 7 to 9 requirements.")],
    ["F", t("Falls short on 10 or more requirements, or automatically if {clauses}.", { clauses: autoF.join(t(", or ")) })],
  ];
  $("#rubric").innerHTML = rows.map(([g, text]) =>
    `<div class="rubric-row"><dt><span class="badge g-${g}">${g}</span></dt><dd>${text}</dd></div>`).join("") +
    (state.data.hospitals.some(isRange) ? `<div class="rubric-row"><dt><span class="badge g-R">?</span></dt>
      <dd>${t("Grade pending review: some items couldn't be confirmed automatically, so the grade is shown as a range until a person checks them.")}</dd></div>` : "");
}

function renderCriteriaGuide() {
  // Grouped the way CSS's spreadsheet groups them; each group says which document is judged.
  const groups = [
    ["MATERIALS ON WEBSITE", "Website materials", "Judged from everything the hospital posts."],
    ["APPLICATION", "The application", "Judged from the financial assistance application only."],
    ["PLAIN LANGUAGE SUMMARY", "The plain language summary", "Judged from the plain language summary only."],
  ];
  $("#criteria-guide").innerHTML = groups.map(([key, title, note]) => {
    const items = state.data.criteria.filter((c) => c.section === key);
    if (!items.length) return "";
    return `<h3 class="guide-group">${t(title)} <span class="guide-note">${t(note)}</span></h3>
      <dl class="guide-list">${items.map((c) => `<div class="guide-row">
        <dt>${esc(cLabel(c))}</dt><dd>${esc(cLaw(c))}</dd></div>`).join("")}</dl>`;
  }).join("");
}

function tile(label, value, note, small = false) {
  return `<div class="tile"><div class="label">${label}</div>
    <div class="value${small ? " small" : ""}">${value}</div><div class="note">${note}</div></div>`;
}

function sectionName(s) {
  return t({ "MATERIALS ON WEBSITE": "Website materials", APPLICATION: "Application", "PLAIN LANGUAGE SUMMARY": "Plain language summary" }[s] || s);
}

function criteriaStats(list) {
  return state.data.criteria.map((c) => {
    let yes = 0, no = 0, review = 0;
    list.forEach((h) => { const v = h.criteria[c.key]; if (v === "yes") yes++; else if (v === "no") no++; else if (v === "review") review++; });
    return { ...c, yes, no, review, rate: pct(yes, yes + no) };
  });
}

function renderTable(list) {
  const { key, dir } = state.sort;
  const val = (h) => (key === "grade" ? gradeRank(h) : key === "issues" ? h.issues : String(h[key] || "").toLowerCase());
  const rows = [...list].sort((a, b) => (val(a) > val(b) ? dir : val(a) < val(b) ? -dir : a.name.localeCompare(b.name)));
  document.querySelectorAll("th[data-sort]").forEach((th) =>
    th.setAttribute("aria-sort", th.dataset.sort === key ? (dir === 1 ? "ascending" : "descending") : "none"));
  $("#table tbody").innerHTML = rows.map((h) => `
    <tr data-id="${h.id}" tabindex="0" aria-label="${esc(h.name)}, grade ${esc(h.grade)}">
      <td><span class="name">${esc(h.name)}</span><span class="city">${esc(h.city)}</span></td>
      <td class="hide-sm">${esc(h.system)}</td>
      <td class="hide-sm">${esc(h.county.replace(" County", ""))}</td>
      <td><span class="badge ${gradeClass(h)}">${esc(h.grade)}</span></td>
      <td class="num">${h.issues}${h.needs_review ? ` <span style="color:var(--st-review)" title="${h.needs_review} need review">+${h.needs_review}?</span>` : ""}</td>
    </tr>`).join("");
  $("#table-empty").hidden = rows.length > 0;
}

/* ---------------------------------------------------------------- map */
function initMap() {
  if (state.map) return;
  state.map = L.map("map", { scrollWheelZoom: false }).setView([42.9, -75.5], 7);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(state.map);
  state.map.on("focus", () => state.map.scrollWheelZoom.enable());
  state.map.on("blur", () => state.map.scrollWheelZoom.disable());
  state.markers = L.layerGroup().addTo(state.map);
  renderLegend();
}

function renderLegend() {
  $("#legend").innerHTML = GRADES.map((g) => `<span><span class="sw" style="background:${MAP_COLORS[g]}"></span>${g}</span>`).join("") +
    (state.data.hospitals.some(isRange) ? `<span><span class="sw" style="background:${MAP_COLORS.R};border-style:dashed"></span>${t("Pending review")}</span>` : "") +
    `<span style="margin-left:auto">${t("Hover a dot for details · select it for links")}</span>`;
}

function renderMap(list) {
  state.markers.clearLayers();
  const ring = "#ffffff";  // map tiles are light in both themes
  const pts = [];
  // Draw worse grades last so they sit on top where dots overlap.
  [...list].sort((a, b) => gradeRank(a) - gradeRank(b)).forEach((h) => {
    if (h.lat == null) return;
    const fill = isRange(h) ? MAP_COLORS.R : MAP_COLORS[h.grade];
    const m = L.circleMarker([h.lat, h.lon], {
      radius: 7, weight: 2, color: isRange(h) ? "#52514e" : ring, dashArray: isRange(h) ? "3 2" : null,
      fillColor: fill, fillOpacity: 0.95,
    });
    const url = safeUrl(h.hfa_url);
    m.bindTooltip(`<strong>${esc(h.name)}</strong><br>${esc(h.address)}, ${esc(h.city)}<br>
      ${esc(h.system)}<br>${t("Grade")} <strong>${esc(h.grade)}</strong> · ${h.issues} ${t(h.issues === 1 ? "gap" : "gaps")}`,
      { className: "hosp-tip", direction: "top", offset: [0, -6] });
    m.bindPopup(`<strong>${esc(h.name)}</strong><br>${esc(h.address)}, ${esc(h.city)}<br>${esc(h.system)}
      <div class="pop-actions">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${t("Financial assistance page ↗")}</a>` : ""}
      <button class="linkbtn" data-open-id="${h.id}">${t("Details")}</button></div>`);
    m.addTo(state.markers);
    pts.push([h.lat, h.lon]);
  });
  if (!state.mapFitted && pts.length) { state.map.fitBounds(pts, { padding: [10, 10], maxZoom: 8 }); state.mapFitted = true; }
}

/* ---------------------------------------------------------------- detail */
function openDrawer(id) {
  const h = state.data.hospitals.find((x) => x.id === id);
  if (!h) return;
  state.lastFocus = document.activeElement;
  const list = (status) => state.data.criteria.filter((c) => h.criteria[c.key] === status);
  const no = list("no"), review = list("review"), yes = list("yes"), unknown = list("unknown");
  const url = safeUrl(h.hfa_url);
  const n = h.notes || {};
  const fact = (label, v) => (v ? `<dt>${label}</dt><dd>${esc(v)}</dd>` : "");
  const summary = isRange(h)
    ? t("Grade depends on {n} item(s) still under review: between {best} and {worst}.",
        { n: h.needs_review, best: `<strong>${h.grade_best}</strong>`, worst: `<strong>${h.grade_worst}</strong>` })
    : h.grade === "A" ? t("Meets every requirement checked.")
    : t("Falls short on {n} of {total} requirements", { n: `<strong>${h.issues}</strong>`, total: state.data.criteria.length }) +
      (h.auto_fail ? t(", including one that means an automatic F (no application posted, or not the full NYS Uniform Application).") : ".");
  const req = (c, cls, mark) => `<div class="req ${cls}"><div class="req-title"><span class="mark ${cls}" aria-hidden="true">${mark}</span>
      ${esc(cLabel(c))}</div><p class="law">${esc(cLaw(c))}</p></div>`;
  $("#d-body").innerHTML = `
    <div class="d-head"><span class="badge lg ${gradeClass(h)}" aria-label="Grade ${esc(h.grade)}">${esc(isRange(h) ? "?" : h.grade)}</span>
      <div><h2 id="d-name">${esc(h.name)}</h2>
      <div class="d-meta">${esc(h.address)}${h.address ? ", " : ""}${esc(h.city)}, NY ${esc(h.zip)}<br>
        ${esc(h.system)}${h.county ? ` · ${esc(h.county)}` : ""}</div></div></div>
    <p class="d-summary">${summary}</p>
    ${url ? `<a class="btn" href="${esc(url)}" target="_blank" rel="noopener">${t("Hospital's financial assistance page ↗")}</a>` : ""}
    ${no.length ? `<div class="d-section"><h3>${t("Where it falls short ({n})", { n: no.length })}</h3>${no.map((c) => req(c, "no", "✕")).join("")}</div>` : ""}
    ${review.length ? `<div class="d-section"><h3>${t("Needs review ({n})", { n: review.length })}</h3>${review.map((c) => req(c, "review", "?")).join("")}</div>` : ""}
    ${yes.length ? `<div class="d-section"><details class="met"><summary>${t("Requirements met ({n})", { n: yes.length })}</summary>
      <ul>${yes.map((c) => `<li><span class="mark yes" aria-hidden="true">✓</span>${esc(cLabel(c))}</li>`).join("")}</ul></details></div>` : ""}
    ${unknown.length ? `<p class="hint">${t("{n} requirement(s) have no data.", { n: unknown.length })}</p>` : ""}
    ${serviceArea(h)}
    <div class="d-section"><h3>${t("Details")}</h3><dl class="facts">
      ${fact(t("Languages"), n.languages_available)}${fact(t("Help line"), n.contact_phone)}
      ${fact(t("Income limit (application)"), h.max_fpl ? t("{x} of the Federal Poverty Level", { x: h.max_fpl }) : "")}
      ${fact(t("Time limit"), n.timeframe_notes)}${fact(t("Inconsistencies"), n.inconsistency_notes)}
      ${fact(t("Application notes"), n.application_notes)}${fact(t("Summary notes"), n.summary_notes)}
      ${fact(t("Notes"), n.general_notes)}${fact(t("Other notes"), n.other_notes)}
      ${fact(t("Last checked"), h.last_checked || state.data.source)}</dl></div>`;
  state.openId = id;
  $("#drawer").hidden = false;
  $("#drawer-backdrop").hidden = false;
  $("#d-close").focus();
}

function closeDrawer() {
  $("#drawer").hidden = true;
  $("#drawer-backdrop").hidden = true;
  if (state.lastFocus) state.lastFocus.focus();
}


/* ================================================================ CSS staff workspace
   Decisions are kept in this browser (localStorage) until downloaded and uploaded to
   GitHub, where a workflow applies them (tools/apply_reviews.py). */
const staff = { decisions: {}, key: "" };

function storageGet(k, fallback) {
  try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
}
function storageSet(k, v) {
  try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window: decisions last this visit only */ }
}

function initStaff() {
  const repo = state.data.repo || "becca-goldrup/HFAL-Tracker";
  $("#run-btn").href = `https://github.com/${repo}/actions/workflows/check.yml`;
  $("#rv-name").value = storageGet("hfal-reviewer", "");
  $("#rv-name").addEventListener("input", (e) => storageSet("hfal-reviewer", e.target.value));
  ["#rv-system", "#rv-req", "#rv-show"].forEach((s) => $(s).addEventListener("change", renderReview));
  $("#staff-ds").addEventListener("change", (e) => selectStaffDataset(e.target.value));

  $("#review-list").addEventListener("click", (e) => {
    const b = e.target.closest("[data-decide]");
    if (!b) return;
    const id = b.closest("[data-item]").dataset.item;
    const value = b.dataset.decide;
    if (value) staff.decisions[id] = { ...(staff.decisions[id] || {}), decision: value };
    else delete staff.decisions[id];
    storageSet(staff.key, staff.decisions);
    renderReview();
  });
  $("#review-list").addEventListener("input", (e) => {
    if (!e.target.matches("textarea[data-note]")) return;
    const id = e.target.closest("[data-item]").dataset.item;
    staff.decisions[id] = { ...(staff.decisions[id] || {}), note: e.target.value };
    storageSet(staff.key, staff.decisions);
  });
  $("#rv-clear").addEventListener("click", () => {
    if (!confirm("Clear all the decisions saved in this browser for this check?")) return;
    staff.decisions = {};
    storageSet(staff.key, {});
    renderReview();
    if (health.data) renderHealthSites();
  });
}

// Fill the staff sections from the selected AI check's data.
function applyStaff() {
  const d = state.data;
  const lr = d.last_run;
  const newest = state.staffKey && state.staffKey === state.pub.latest_ai;
  $("#run-status").innerHTML = lr
    ? `${newest ? "Newest check" : "This check"}: <strong>${esc(lr.date)}</strong> with ${esc(lr.model.replace(/^us\.(amazon|anthropic)\./, "").replace(/-v\d.*$/, ""))}.
       ${lr.websites} websites: ${lr.graded} graded, ${lr.unchanged} unchanged${lr.problems ? `, ${lr.problems} couldn't be checked` : ""}.
       Estimated cost about $${Number(lr.cost).toFixed(2)}.`
    : "No AI check has run yet. The dashboard currently shows CSS's September 2025 review.";

  staff.key = `hfal-review:${state.staffKey || "none"}`;
  staff.decisions = storageGet(staff.key, {});
  const items = d.review || [];
  const systems = [...new Set(items.map((i) => i.system))].sort((a, b) => a.localeCompare(b));
  $("#rv-system").innerHTML = `<option value="">All systems</option>` +
    systems.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  const reqs = [...new Set(items.map((i) => i.requirement))].sort();
  $("#rv-req").innerHTML = `<option value="">All requirements</option>` +
    reqs.map((r) => `<option value="${esc(r)}">${esc(r)}</option>`).join("");
  renderReview();
}

function decided(id) {
  const x = staff.decisions[id];
  return x && (x.decision === "yes" || x.decision === "no") ? x.decision : "";
}

function renderReview() {
  const items = state.data.review || [];
  const done = items.filter((i) => decided(i.id)).length;
  $("#progress-fill").style.width = items.length ? `${(100 * done) / items.length}%` : "0%";
  $("#progress-text").textContent = items.length ? `${done} of ${items.length} flagged items reviewed` : "";
  $("#sub-review-count").textContent = items.length ? String(items.length - done) : "";
  const all = savedDecisions();
  const fixes = all.filter((x) => x.override).length;
  $("#send-summary").textContent = all.length
    ? `Ready to send: ${all.length - fixes} review decision${all.length - fixes === 1 ? "" : "s"}` +
      `${fixes ? ` and ${fixes} correction${fixes === 1 ? "" : "s"} from the Data health tab` : ""}. Submit them to GitHub below.`
    : "Decide at least one item above (or correct an answer in the Data health tab), then send your decisions here.";
  renderSubmit(all);

  if (!state.data.last_run) {
    $("#review-list").innerHTML = `<p class="empty">Flagged items appear here after the first AI check.</p>`;
    return;
  }
  const sys = $("#rv-system").value, req = $("#rv-req").value, show = $("#rv-show").value;
  const shown = items.filter((i) => (!sys || i.system === sys) && (!req || i.requirement === req) &&
    (show === "all" || (show === "todo" ? !decided(i.id) : !!decided(i.id))));
  if (!shown.length) {
    $("#review-list").innerHTML = `<p class="empty">${items.length
      ? (show === "todo" ? "Nothing left to review here. Nice work." : "No items match these filters.")
      : "No items need review right now."}</p>`;
    return;
  }
  // Group by website, so each hospital page's items sit together.
  const groups = new Map();
  shown.forEach((i) => { if (!groups.has(i.hfa_url)) groups.set(i.hfa_url, []); groups.get(i.hfa_url).push(i); });
  $("#review-list").innerHTML = [...groups.values()].map((group) => {
    const g = group[0];
    const more = g.hospitals.length - 1;
    const url = safeUrl(g.hfa_url);
    return `<article class="rv-site">
      <header class="rv-site-head">
        <h4>${esc(g.hospitals[0])}${more ? ` <span class="rv-more">+ ${more} more hospital${more === 1 ? "" : "s"}</span>` : ""}</h4>
        <p class="rv-meta">${esc(g.system)}${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener">Financial assistance page ↗</a>` : ""}</p>
        ${more ? `<details class="rv-hosp"><summary>Hospitals on this page</summary><p>${g.hospitals.map(esc).join(", ")}</p></details>` : ""}
        ${(g.site_notes || []).map((n) => `<p class="rv-site-note">${esc(n)}</p>`).join("")}
      </header>
      ${group.map(reviewItem).join("")}
    </article>`;
  }).join("");
}

function reviewItem(i) {
  const dec = decided(i.id);
  const note = (staff.decisions[i.id] || {}).note || "";
  const reason = i.reason.replace(/^NEEDS REVIEW \([^)]*\):\s*/, "");
  const ev = (i.evidence || []).map((e) => {
    const url = safeUrl(e.url);
    return `<li>${e.doc ? `<span class="rv-doc">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(e.doc)} ↗</a>` : esc(e.doc)}</span>` : ""}
      <q>${esc(e.quote)}</q></li>`;
  }).join("");
  return `<div class="rv-item${dec ? " is-done" : ""}" data-item="${esc(i.id)}">
    <div class="rv-head"><span class="rv-req">${esc(i.requirement)}</span><span class="rv-sec">${esc(sectionName(i.section))}</span></div>
    <p class="rv-law">${esc(i.law)}</p>
    <p class="rv-why"><strong>Why it's flagged:</strong> ${esc(reason)}</p>
    ${ev ? `<details class="rv-ev"><summary>Quoted text (${i.evidence.length})</summary><ul>${ev}</ul></details>` : ""}
    <div class="rv-actions" role="group" aria-label="Decision for ${esc(i.requirement)}">
      <button type="button" data-decide="yes" class="rv-btn yes" aria-pressed="${dec === "yes"}">✓ Meets requirement</button>
      <button type="button" data-decide="no" class="rv-btn no" aria-pressed="${dec === "no"}">✕ Falls short</button>
      ${dec ? `<button type="button" data-decide="" class="text-btn">Undo</button>` : ""}
    </div>
    <textarea data-note rows="1" placeholder="Add a note (optional)">${esc(note)}</textarea>
  </div>`;
}

// "Submit to GitHub": a pre-filled issue that a GitHub workflow applies automatically
// (.github/workflows/apply-review-issue.yml). Large sets are split so each link stays short enough.
function issueUrl(batch, part, parts) {
  const repo = state.data.repo || "becca-goldrup/HFAL-Tracker";
  const name = ($("#rv-name").value || "").trim();
  const today = nyToday();
  const payload = { reviewer: name, submitted: today, dataset: state.staffKey, data_generated: state.data.generated,
    decisions: batch.map((x) => Object.assign({ id: x.id, d: x.decision }, x.note ? { n: x.note } : {}, x.override ? { o: 1 } : {})) };
  const title = `[Review decisions] ${batch.length} decision${batch.length === 1 ? "" : "s"} on the ${staffDatasetName()} from ${name || "CSS staff"}` +
    (parts > 1 ? ` part ${part} of ${parts}` : "");
  const body = "These decisions were made in the Equity Lens dashboard. Submitting this issue applies them " +
    "automatically; please don't edit the block below.\n\n```json\n" + JSON.stringify(payload) + "\n```";
  return `https://github.com/${repo}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
}

function submitBatches(all) {
  const batches = [];
  let cur = [];
  for (const x of all) {
    if (cur.length && issueUrl(cur.concat([x]), 1, 1).length > 7000) { batches.push(cur); cur = []; }
    cur.push(x);
  }
  if (cur.length) batches.push(cur);
  return batches;
}

function renderSubmit(all) {
  const box = $("#submit-batches");
  if (!all.length) {
    box.innerHTML = `<button class="btn" type="button" disabled>Submit to GitHub ↗</button>`;
    return;
  }
  const batches = submitBatches(all);
  box.innerHTML = batches.map((b, i) => `<a class="btn" target="_blank" rel="noopener" data-batch="${i}"
      href="${esc(issueUrl(b, i + 1, batches.length))}">${batches.length > 1 ? `Submit part ${i + 1} of ${batches.length} (${b.length})` : "Submit to GitHub"} ↗</a>`).join("") +
    (batches.length > 1 ? `<p class="hint">Your decisions are split into ${batches.length} parts so each fits in one GitHub page. Submit each part.</p>` : "");
}

// Every saved decision: flagged items settled in this tab, plus corrections made in the Data health tab.
function savedDecisions() {
  const byId = Object.fromEntries((state.data.review || []).map((i) => [i.id, i]));
  return Object.entries(staff.decisions).filter(([, x]) => x.decision === "yes" || x.decision === "no").map(([id, x]) => {
    const item = byId[id] || {};
    return { id, hfa_url: x.hfa_url || item.hfa_url, column: x.column || item.column,
             requirement: x.requirement || item.requirement, decision: x.decision, note: x.note || "",
             override: !!x.override && !item.id, hospitals: x.hospitals || item.hospitals || [] };
  }).filter((x) => x.hfa_url && x.column);
}

/* ================================================================ Data health
   How each AI answer was decided (docs/data/health-<check>.json, made by tools/build_dashboard.py).
   Loaded only when the tab is opened. */
const BASIS = {
  quote:   { label: "Verified by a quote", short: "Quote verified", color: "#0080a0",
             about: "The AI quoted the hospital's document, and the tool found that exact text in the document it downloaded." },
  absence: { label: "Accepted: nothing found", short: "Nothing found", color: "#8cc3d3",
             about: "Nothing problematic was found, e.g. no deadline wording anywhere. The tool also scanned the documents itself for such wording before accepting." },
  review:  { label: "Needs a person", short: "Needs review", color: "#e9a533",
             about: "The tool couldn't confirm the AI's answer, so it is waiting for CSS staff in the For CSS staff tab." },
  staff:   { label: "Decided by CSS staff", short: "Staff decision", color: "var(--g-A)",
             about: "A CSS reviewer settled this answer." },
  carried: { label: "Not re-checked", short: "2025 value", color: "#b5b4ad",
             about: "The AI couldn't check this website (it blocks automated access), so the value from CSS's 2025 review is kept." },
};
const BASIS_ORDER = ["quote", "absence", "review", "staff", "carried"];
const health = { data: null, key: "", loading: "", filter: { status: "all", cause: "", req: "" }, open: new Set(), editing: new Set() };

function showHealth() {
  const key = state.staffKey;
  if (health.data && health.key === key) return renderHealth();
  if (health.loading === key) return;
  health.loading = key;
  $("#health-root").innerHTML = `<p class="empty">Loading…</p>`;
  if (!key) {
    $("#health-root").innerHTML = `<p class="empty">Data health details appear here after the first AI check.</p>`;
    return;
  }
  fetch(`data/health-${key}.json`)
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => {
      if (state.staffKey !== key) return;
      Object.assign(health, { data: d, key, loading: "" });
      health.open.clear(); health.editing.clear();
      renderHealth();
    })
    .catch(() => {
      health.loading = "";
      $("#health-root").innerHTML = `<p class="empty">No data health details for this check.</p>`;
    });
}

function hBar(counts, total) {
  return `<div class="h-stack" role="img" aria-label="${BASIS_ORDER.map((b) => `${BASIS[b].label}: ${counts[b] || 0}`).join(", ")}">` +
    BASIS_ORDER.filter((b) => counts[b]).map((b) =>
      `<span style="width:${(100 * counts[b]) / total}%;background:${BASIS[b].color}" title="${BASIS[b].label}: ${counts[b]}"></span>`).join("") +
    `</div>`;
}

function renderHealth() {
  const d = health.data;
  const sites = d.sites;
  const all = sites.flatMap((s) => s.items);
  const total = all.length;
  const t = d.totals;
  const finalSites = sites.filter((s) => s.status === "checked" && !s.items.some((i) => i.basis === "review"));
  const hospitalsFinal = finalSites.reduce((n, s) => n + s.hospitals.length, 0);
  const hospitalsAll = sites.reduce((n, s) => n + s.hospitals.length, 0);
  const p = d.pipeline;
  const models = [...new Set(sites.map((s) => s.model.replace(/^us\.(amazon|anthropic)\./, "").replace(/-v\d.*$/, "").replace(" (json)", "")).filter(Boolean))];

  // Causes and requirements among review items
  const causeCount = {}, reqCount = {};
  sites.forEach((s) => s.items.forEach((i) => {
    if (i.basis !== "review") return;
    causeCount[i.cause || "other"] = (causeCount[i.cause || "other"] || 0) + 1;
    reqCount[i.key] = (reqCount[i.key] || 0) + 1;
  }));
  const causeRows = Object.entries(causeCount).sort((a, b) => b[1] - a[1]);
  const reqRows = Object.entries(reqCount).sort((a, b) => b[1] - a[1]);
  const maxCause = Math.max(1, ...causeRows.map((r) => r[1]));
  const maxReq = Math.max(1, ...reqRows.map((r) => r[1]));
  const f = health.filter;

  $("#health-root").innerHTML = `
    <div class="stats">
      ${tile("Websites checked by AI", `${p.graded}<span class="of-total"> / ${p.websites}</span>`, `${p.blocked} block automated access`)}
      ${tile("Answers verified by a quote", t.quote, `${pct(t.quote, total)}% of ${total} answers`)}
      ${tile("Answers waiting for a person", t.review, `${pct(t.review, total)}% of answers`)}
      ${tile("Hospitals fully verified", hospitalsFinal, `of ${hospitalsAll} have nothing left to review`)}
    </div>

    <section class="fig">
      <h2 class="fig-title">How certain the answers are</h2>
      ${hBar(t, total)}
      <div class="h-legend-inline">${BASIS_ORDER.map((b) => `<span><span class="h-sw" style="background:${BASIS[b].color}"></span>${BASIS[b].short} (${t[b] || 0})</span>`).join("")}</div>
      <details class="h-explain"><summary>How answers are decided</summary>
        <ol class="pipeline">
        <li><strong>Download.</strong> A browser visits each hospital's financial assistance page and saves the linked documents
          (applications, summaries, policies). ${p.downloaded} of ${p.websites} websites downloaded; ${p.blocked} block automated access.</li>
        <li><strong>AI reads.</strong> ${esc(models.join(", ") || "The AI")} read each website's documents and answered the 17 questions,
          quoting the text behind each answer. It is told to answer "unclear" rather than guess.</li>
        <li><strong>Tool checks.</strong> A program, not the AI, checks every quote against the downloaded documents, rejects
          headings as evidence, scans the documents itself for deadline, asset and immigration wording, and catches answers that contradict each other.</li>
        <li><strong>Accept or flag.</strong> ${t.quote} answers were accepted with a verified quote and ${t.absence} because nothing problematic was found.
          ${t.review} were flagged for a person.</li>
        <li><strong>People decide.</strong> CSS staff settle flagged items in the For CSS staff tab${t.staff ? `; ${t.staff} settled so far` : ""}.
          A hospital's grade is final only when nothing is left to review.</li>
      </ol>
        <dl class="h-legend">${BASIS_ORDER.map((b) => `<div class="h-legend-row">
        <dt><span class="h-sw" style="background:${BASIS[b].color}"></span>${BASIS[b].label}
          <span class="h-num">${t[b] || 0} (${pct(t[b] || 0, total)}%)</span></dt><dd>${BASIS[b].about}</dd></div>`).join("")}</dl>
      </details>
    </section>

    <div class="h-two">
      <section class="fig">
        <h2 class="fig-title">Why answers need a person</h2>
        <div class="hbars h-causes">${causeRows.map(([k, n]) => `
          <button class="hbar clickable${f.cause === k ? " is-on" : ""}" data-h-cause="${esc(k)}">
            <span class="lbl">${esc(d.causes[k] || "Other")}</span>
            <span class="track"><span class="fill" style="width:${(100 * n) / maxCause}%;background:${BASIS.review.color}"></span></span>
            <span class="val">${n}</span></button>`).join("")}</div>
        <p class="src">Select a cause to list the websites below.</p>
      </section>
      <section class="fig">
        <h2 class="fig-title">Which requirements need a person most</h2>
        <div class="hbars h-causes">${reqRows.map(([k, n]) => `
          <button class="hbar clickable${f.req === k ? " is-on" : ""}" data-h-req="${esc(k)}">
            <span class="lbl">${esc(d.labels[k])}</span>
            <span class="track"><span class="fill" style="width:${(100 * n) / maxReq}%;background:${BASIS.review.color}"></span></span>
            <span class="val">${n}</span></button>`).join("")}</div>
        <p class="src">Select a requirement to list the websites below.</p>
      </section>
    </div>

    <section class="fig h-sites-fig">
      <h2 class="fig-title">Hospital websites</h2>
      <p class="fig-sub">Each square is one of the 17 requirements, colored by how it was decided. Select a website to see every answer, the AI's confidence, and the quote behind it.</p>
      <div class="h-controls">
        <div class="seg" role="group" aria-label="Show">
          ${[["all", "All"], ["review", "Has items to review"], ["final", "Final grade"], ["blocked", "Couldn't be checked"]].map(([v, l]) =>
            `<button type="button" data-h-status="${v}" aria-pressed="${f.status === v}">${l}</button>`).join("")}
        </div>
        ${f.cause || f.req ? `<p class="h-active">Showing websites with
          ${f.cause ? `<strong>${esc(d.causes[f.cause] || "other causes")}</strong>` : ""}${f.cause && f.req ? " on " : ""}${f.req ? `<strong>${esc(d.labels[f.req])}</strong>` : ""}
          <button type="button" class="text-btn" data-h-clear>Clear</button></p>` : ""}
      </div>
      <div id="h-sites"></div>
    </section>
    <div class="h-legend-inline">${BASIS_ORDER.map((b) => `<span><span class="h-sw" style="background:${BASIS[b].color}"></span>${BASIS[b].short}</span>`).join("")}</div>`;
  renderHealthSites();
}

function healthSiteMatches(s) {
  const f = health.filter;
  const review = s.items.filter((i) => i.basis === "review");
  if (f.status === "review" && !review.length) return false;
  if (f.status === "final" && (s.status !== "checked" || review.length)) return false;
  if (f.status === "blocked" && s.status === "checked") return false;
  if (f.cause && !review.some((i) => (i.cause || "other") === f.cause && (!f.req || i.key === f.req))) return false;
  if (f.req && !review.some((i) => i.key === f.req)) return false;
  return true;
}

function renderHealthSites() {
  const d = health.data;
  const shown = d.sites.filter(healthSiteMatches);
  $("#h-sites").innerHTML = !shown.length ? `<p class="empty">No websites match.</p>` : `
    <table class="h-table"><thead><tr>
      <th scope="col">Website</th><th scope="col" class="hide-sm">System</th><th scope="col">The 17 answers</th>
      <th scope="col" class="num">To review</th><th scope="col">Grade</th></tr></thead><tbody>
    ${shown.map((s) => {
      const nrev = s.items.filter((i) => i.basis === "review").length;
      const open = health.open.has(s.id);
      const more = s.hospitals.length - 1;
      return `<tr class="h-row" data-h-site="${esc(s.id)}" tabindex="0" aria-expanded="${open}">
        <td><span class="name">${esc(s.hospitals[0])}</span>${more ? `<span class="city">+ ${more} more hospital${more === 1 ? "" : "s"}</span>` : ""}</td>
        <td class="hide-sm">${esc(s.system)}</td>
        <td><span class="h-squares">${s.items.map((i) => `<i style="background:${BASIS[i.basis].color}" title="${esc(d.labels[i.key])}: ${BASIS[i.basis].label}"></i>`).join("")}</span></td>
        <td class="num">${s.status === "checked" ? nrev : "–"}</td>
        <td><span class="badge ${/ to /.test(s.grade) ? "g-R" : "g-" + esc(s.grade)}">${esc(s.grade)}</span></td></tr>
      ${open ? `<tr class="h-detail"><td colspan="5">${healthDetail(s)}</td></tr>` : ""}`;
    }).join("")}</tbody></table>`;
}

function healthDetail(s) {
  const d = health.data;
  const docs = s.documents || [];
  const url = safeUrl(s.hfa_url);
  const nrev = s.items.filter((i) => i.basis === "review").length;
  const meta = s.status === "checked"
    ? `Checked ${esc(s.last_checked)} by ${esc(s.model.replace(/^us\.(amazon|anthropic)\./, ""))}. Read ${docs.filter((x) => !x.error).length} documents` +
      `${docs.some((x) => x.scanned) ? ` (${docs.filter((x) => x.scanned).length} scanned)` : ""}` +
      `${docs.some((x) => x.error) ? `; ${docs.filter((x) => x.error).length} couldn't be downloaded` : ""}.`
    : `Not checked: ${esc(s.problem)}. Values below are from CSS's 2025 review.`;
  return `<div class="h-detail-box">
    <p class="h-meta">${meta} ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">Financial assistance page ↗</a>` : ""}</p>
    ${s.hospitals.length > 1 ? `<p class="h-meta">Hospitals on this page: ${s.hospitals.map(esc).join(", ")}</p>` : ""}
    ${(s.notes || []).map((n) => `<p class="rv-site-note">${esc(n)}</p>`).join("")}
    <ul class="h-items">${s.items.map((i) => {
      const doc = safeUrl(i.url);
      const id = `${s.id}|${i.column}`;
      const mine = staff.decisions[id];
      const pending = mine && (mine.decision === "yes" || mine.decision === "no");
      const editing = health.editing.has(id);
      const edit = pending
        ? `<p class="h-edit-state">Your change: <strong>${mine.decision === "yes" ? "meets requirement" : "falls short"}</strong>
             (not sent yet) <button type="button" class="text-btn" data-h-undo="${esc(id)}">Undo</button></p>`
        : editing
          ? `<div class="h-edit" data-h-edit-id="${esc(id)}" data-site="${esc(s.id)}" data-column="${esc(i.column)}">
               <div class="rv-actions">
                 <button type="button" class="rv-btn yes" data-h-set="yes">✓ Meets requirement</button>
                 <button type="button" class="rv-btn no" data-h-set="no">✕ Falls short</button>
                 <button type="button" class="text-btn" data-h-cancel="${esc(id)}">Cancel</button></div>
               <input type="text" class="h-note" placeholder="Why? (optional, saved with the change)"></div>`
          : `<button type="button" class="text-btn h-edit-link" data-h-start="${esc(id)}">Edit</button>`;
      return `<li class="h-item${pending ? " is-edited" : ""}">
        <span class="h-sw" style="background:${BASIS[i.basis].color}"></span>
        <div><div class="h-item-head"><strong>${esc(d.labels[i.key])}</strong>
          <span class="h-ans h-${esc(i.value)}">${i.value === "review" ? "needs review" : esc(i.value)}</span>
          <span class="h-how">${BASIS[i.basis].short}${i.cause ? ` · ${esc(d.causes[i.cause] || "")}` : ""}${i.confidence ? ` · AI confidence: ${esc(i.confidence)}` : ""}</span></div>
          ${i.quote ? `<p class="h-quote">${i.doc ? `<span class="rv-doc">${doc ? `<a href="${esc(doc)}" target="_blank" rel="noopener">${esc(i.doc)} ↗</a>` : esc(i.doc)}</span>` : ""}<q>${esc(i.quote)}</q></p>` : ""}
          ${i.basis !== "quote" && i.reason ? `<p class="h-reason">${esc(i.reason)}</p>` : ""}
          ${edit}
        </div></li>`;
    }).join("")}</ul>
    <div class="send-actions">
      ${nrev ? `<button type="button" class="btn btn-secondary" data-h-review="${esc(s.system)}">Review this system's flagged items →</button>` : ""}
      <a href="#staff/review" class="text-btn h-send-link">Send your changes (Review, step 2) →</a>
    </div>
  </div>`;
}

document.addEventListener("click", (e) => {
  if (!health.data) return;
  const f = health.filter;
  const st = e.target.closest("[data-h-status]");
  if (st) { f.status = st.dataset.hStatus; renderHealth(); return; }
  const c = e.target.closest("[data-h-cause]");
  if (c) { f.cause = f.cause === c.dataset.hCause ? "" : c.dataset.hCause; f.status = "all"; renderHealth(); scrollToSites(); return; }
  const r = e.target.closest("[data-h-req]");
  if (r) { f.req = f.req === r.dataset.hReq ? "" : r.dataset.hReq; f.status = "all"; renderHealth(); scrollToSites(); return; }
  if (e.target.closest("[data-h-clear]")) { f.cause = ""; f.req = ""; renderHealth(); return; }
  const start = e.target.closest("[data-h-start]");
  if (start) { health.editing.add(start.dataset.hStart); renderHealthSites(); return; }
  const cancel = e.target.closest("[data-h-cancel]");
  if (cancel) { health.editing.delete(cancel.dataset.hCancel); renderHealthSites(); return; }
  const undo = e.target.closest("[data-h-undo]");
  if (undo) { delete staff.decisions[undo.dataset.hUndo]; storageSet(staff.key, staff.decisions); renderHealthSites(); renderReview(); return; }
  const set = e.target.closest("[data-h-set]");
  if (set) {
    const box = set.closest("[data-h-edit-id]");
    const site = health.data.sites.find((x) => x.id === box.dataset.site);
    const item = site.items.find((x) => x.column === box.dataset.column);
    const id = box.dataset.hEditId;
    staff.decisions[id] = { decision: set.dataset.hSet, note: box.querySelector(".h-note").value.trim(),
      override: item.basis !== "review", hfa_url: site.hfa_url, column: item.column,
      requirement: health.data.labels[item.key], hospitals: site.hospitals };
    storageSet(staff.key, staff.decisions);
    health.editing.delete(id);
    renderHealthSites(); renderReview();
    return;
  }
  const rv = e.target.closest("[data-h-review]");
  if (rv) { location.hash = "staff/review"; $("#rv-system").value = rv.dataset.hReview; $("#rv-show").value = "todo"; renderReview(); return; }
  const row = e.target.closest("tr[data-h-site]");
  if (row && !e.target.closest("a")) {
    const id = row.dataset.hSite;
    health.open.has(id) ? health.open.delete(id) : health.open.add(id);
    renderHealthSites();
  }
});
document.addEventListener("keydown", (e) => {
  const row = e.target.closest && e.target.closest("tr[data-h-site]");
  if (row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); row.click(); }
});
function scrollToSites() {
  const el = document.querySelector(".h-sites-fig");
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}


/* ================================================================ datasets & staff shell
   hospitals.json holds every public dataset; staff.json (review queue, last run, changes)
   loads only when the CSS staff tab opens. */
const PREVIEW_KEY = "hfal-preview-dataset";

function previewChoice() {
  try { return sessionStorage.getItem(PREVIEW_KEY) || ""; } catch { return ""; }
}

function useDataset(key) {
  const pub = state.pub;
  const k = pub.datasets[key] ? key : pub.published.dataset;
  const ds = pub.datasets[k];
  state.datasetKey = k;
  Object.assign(state.data, { hospitals: ds.hospitals, source: ds.source, generated: ds.generated });
  const m = /^AI-assisted check \((.*)\)$/.exec(ds.source || "");
  const source = m ? t("AI-assisted check ({date})", { date: m[1] }) : t(ds.source);
  $("#source-line").textContent = t("Data: {source} · Updated {date}", { source, date: ds.generated });
  document.querySelectorAll(".src-name").forEach((el) => (el.textContent = source));
  const banner = $("#preview-banner");
  const previewing = k !== pub.published.dataset;
  banner.hidden = !previewing;
  if (previewing) {
    banner.innerHTML = `<div class="wrap"><strong>Preview only:</strong> the public tabs are showing
      <em>${esc(ds.label)}</em>. Everyone else sees <em>${esc(pub.datasets[pub.published.dataset].label)}</em>.
      <button type="button" class="text-btn" data-stop-preview>Stop preview</button>
      <a class="text-btn" href="#staff/status">Publish it</a></div>`;
  }
}

function setPreview(key) {
  try { key === state.pub.published.dataset ? sessionStorage.removeItem(PREVIEW_KEY) : sessionStorage.setItem(PREVIEW_KEY, key); } catch { /* ignore */ }
  useDataset(key);
  state.map && state.markers && (state.mapFitted = true);
  buildFilters();
  render();
  if (state.staffLoaded) renderPublish();
}

document.addEventListener("click", (e) => {
  if (e.target.closest("[data-stop-preview]")) setPreview(state.pub.published.dataset);
});

const STAFF_KEY = "hfal-staff-dataset";
const staffCache = {};
const aiKeys = () => Object.keys(state.pub.datasets).filter((k) => state.pub.datasets[k].kind === "ai");
const staffDatasetName = () => (state.staffKey ? `AI check of ${state.pub.datasets[state.staffKey].date}` : "AI check");

function ensureStaff() {
  if (!state.staffInit) { initStaff(); state.staffInit = true; }
  let key = state.staffKey;
  if (key === undefined) {
    let saved = "";
    try { saved = sessionStorage.getItem(STAFF_KEY) || ""; } catch { /* ignore */ }
    const keys = aiKeys();
    key = keys.includes(saved) ? saved : keys.includes(state.datasetKey) ? state.datasetKey : (state.pub.latest_ai || keys[0] || "");
  }
  return state.staffLoadedKey === key ? Promise.resolve() : selectStaffDataset(key);
}

// Pick which AI check the staff sections (status, review, data health) work on. The public tabs don't change.
function selectStaffDataset(key) {
  state.staffKey = key;
  try { sessionStorage.setItem(STAFF_KEY, key); } catch { /* ignore */ }
  renderStaffPicker();
  const load = !key ? Promise.resolve({}) : staffCache[key] ? Promise.resolve(staffCache[key])
    : fetch(`data/staff-${key}.json`).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }).catch(() => ({}));
  return load.then((s) => {
    if (state.staffKey !== key) return;
    if (key) staffCache[key] = s;
    Object.assign(state.data, { review: s.review || [], last_run: s.last_run || null,
                                since_baseline: s.since_baseline || null, history: s.history || [] });
    state.staffLoaded = true;
    state.staffLoadedKey = key;
    applyStaff();
    renderPublish();
    renderChanges();
    if (!$("#staff-health").hidden) showHealth();
  });
}

function renderStaffPicker() {
  const keys = aiKeys();
  const live = state.pub.published.dataset;
  const sel = $("#staff-ds");
  sel.innerHTML = keys.length
    ? keys.map((k) => `<option value="${k}"${k === state.staffKey ? " selected" : ""}>AI check of ${esc(state.pub.datasets[k].date)}${
        k === state.pub.latest_ai ? " (newest)" : ""}${k === live ? " · published" : ""}</option>`).join("")
    : `<option value="">No AI checks yet</option>`;
  const many = keys.length > 1;
  sel.hidden = !many;
  $("#staff-ds-label").textContent = many ? "Working on" : "";
  $("#staff-ds-note").innerHTML = !keys.length ? "No AI check has run yet."
    : many ? "Overview, Review and Data health all show this check. The public tabs only change when you publish."
    : `Showing the <strong>AI check of ${esc(state.pub.datasets[keys[0]].date)}</strong>. Overview, Review and Data health all use it; the public tabs only change when you publish.`;
}

function showStaffSection(sub) {
  if (!["status", "review", "health"].includes(sub)) sub = "status";
  document.querySelectorAll(".subnav button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.sub === sub)));
  document.querySelectorAll(".staff-sub").forEach((el) => (el.hidden = el.id !== `staff-${sub}`));
  if (sub === "health") showHealth();
}

document.addEventListener("click", (e) => {
  const b = e.target.closest(".subnav [data-sub]");
  if (b) location.hash = `staff/${b.dataset.sub}`;
});

const ANSWER = { yes: "Meets", no: "Falls short", review: "Needs review", unknown: "No data" };

function renderChanges() {
  const sb = state.data.since_baseline;
  const hist = state.data.history || [];
  const ans = (v) => `<span class="h-ans h-${esc(v)}">${ANSWER[v] || esc(v)}</span>`;
  let html = "";
  if (!sb) {
    html = `<p class="empty-feed">Changes appear here after the first AI check.</p>`;
  } else if (!sb.items.length) {
    html = `<p class="empty-feed">No settled answer in this check disagrees with CSS's September 2025 review.
      ${sb.counts.now_review ? `(${sb.counts.now_review.toLocaleString()} answers are waiting in the Review tab instead.)` : ""}</p>`;
  } else {
    const c = sb.counts;
    html = `<p class="changes-sum"><strong>${c.answers.toLocaleString()}</strong> settled answers at ${c.websites} websites
        (${c.hospitals} hospitals) disagree with CSS's September 2025 review. Either the hospital changed its documents,
        the rules changed (for example the ${state.data.fpl_year} poverty guidelines), or one of the two reviews is wrong.
        ${c.now_review ? `Answers the AI couldn't confirm aren't listed; they're in the <a href="#staff/review">Review</a> tab.` : ""}</p>
      <div class="feed">${sb.items.map((g) => {
        const names = g.hospitals.length > 3 ? `${g.hospitals.slice(0, 3).join(", ")} and ${g.hospitals.length - 3} more` : g.hospitals.join(", ");
        return `<details class="item"><summary><strong>${esc(names)}</strong>
            <span class="hint">${g.changes.length} answer${g.changes.length === 1 ? "" : "s"} differ</span></summary>
          <ul class="chg-list">${g.changes.map((ch) => `<li><span>${esc(ch.label)}</span> ${ans(ch.before)} → ${ans(ch.after)}</li>`).join("")}</ul>
          <a class="text-btn" href="${esc(g.hfa_url)}" target="_blank" rel="noopener">Financial assistance page ↗</a></details>`;
      }).join("")}</div>`;
  }
  $("#feed").innerHTML = html;
  $("#history-box").innerHTML = !hist.length ? "" : `<details class="h-explain"><summary>Check history</summary>
      <p class="hint">Each AI check compares a website with the one before it. If a hospital's documents haven't changed, the earlier answers are kept.</p>
      <table class="hist"><thead><tr><th>Date</th><th>Websites</th><th>What happened</th><th>Compared with</th></tr></thead><tbody>
      ${hist.map((h) => `<tr><td>${esc(h.date)}</td><td>${h.websites}</td>
        <td>${Object.entries(h.why).map(([w, n]) => `${n} ${esc(w)}`).join("; ") ||
              `${h.graded} graded, ${h.unchanged} unchanged`}${h.problems ? `; ${h.problems} couldn't be checked` : ""}</td>
        <td>${esc(h.compared_with || "")}</td></tr>`).join("")}</tbody></table></details>`;
}

function renderPublish() {
  const pub = state.pub;
  const live = pub.published.dataset;
  const viewing = state.datasetKey;
  const pendingNote = (key) => {
    if (pub.datasets[key].kind !== "ai") return "Verified by CSS staff by hand.";
    const hs = pub.datasets[key].hospitals;
    const pending = hs.filter((h) => h.grade_best !== h.grade_worst).length;
    return pending ? `${pending} of ${hs.length} hospitals still have items waiting for review; their grades show as ranges (for example "B to D").`
      : "Every hospital has a final grade.";
  };
  $("#publish-box").innerHTML = `<div class="ds-list">${Object.entries(pub.datasets).map(([key, ds]) => `
    <div class="ds-row${key === live ? " is-live" : ""}">
      <div class="ds-main">
        <div class="ds-name">${esc(ds.label)}
          ${key === live ? `<span class="ds-tag live">Published</span>` : ""}
          ${key === viewing && key !== live ? `<span class="ds-tag">You're previewing this</span>` : ""}</div>
        <div class="ds-note">${esc(pendingNote(key))}
          ${key === live && pub.published.by ? ` Published by ${esc(pub.published.by)} on ${esc(pub.published.date)}.` : ""}</div>
      </div>
      <div class="ds-actions">
        ${key === viewing ? "" : `<button type="button" class="btn btn-secondary" data-preview="${key}">Preview</button>`}
        ${key === live ? "" : `<a class="btn" target="_blank" rel="noopener" href="${esc(publishUrl(key, ds.label))}">Publish ↗</a>`}
      </div>
    </div>`).join("")}</div>
    ${Object.keys(pub.datasets).length < 2 ? `<p class="hint">The AI-check dataset appears here after the first AI check.</p>` : ""}
    <p class="hint">Publish opens a pre-filled GitHub issue; select <strong>Submit new issue</strong> and the public tabs switch for everyone within a few minutes.</p>`;
}

function publishUrl(key, label) {
  const repo = state.data.repo || "becca-goldrup/HFAL-Tracker";
  const name = ($("#rv-name") && $("#rv-name").value || "").trim();
  const today = nyToday();
  const payload = { reviewer: name, submitted: today, publish: key, decisions: [] };
  const title = `[Review decisions] Publish: ${label}`;
  const body = `Switch the dashboard's public tabs (Overview, Hospitals, Map) to show: ${label}.\n\n` +
    "Submitting this issue applies it automatically; please don't edit the block below.\n\n```json\n" + JSON.stringify(payload) + "\n```";
  return `https://github.com/${repo}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
}

document.addEventListener("click", (e) => {
  const p = e.target.closest("[data-preview]");
  if (p) { setPreview(p.dataset.preview); location.hash = "overview"; }
});


/* Service area: what the hospital lists vs. the legal minimum (its county + every bordering county,
   from the US Census Bureau's county adjacency file). */
function serviceArea(h) {
  const req = h.psa_required || [];
  if (!req.length && !h.psa_listed) return "";
  const listed = (h.psa_listed || "").trim();
  const m = listed.match(/^(.*?)(?:\s*\|\s*)?"(.*)"$/s);
  const summary = m ? m[1].trim() : listed;
  const quote = m ? m[2].trim() : "";
  const status = h.criteria && h.criteria.psa_compliant_2007;
  const verdict = t({ yes: "Meets the requirement", no: "Falls short of the requirement", review: "Needs review", unknown: "" }[status] || "");
  return `<div class="d-section"><h3>${t("Service area")}</h3>
    ${verdict ? `<p class="psa-verdict psa-${esc(status)}">${verdict}</p>` : ""}
    <dl class="facts">
      <dt>${t("The hospital's wording")}</dt><dd>${quote ? `<q>${esc(quote)}</q>` : `<span class="hint">${t(listed ? "No sentence cited." : "Not recorded in this dataset.")}</span>`}</dd>
      ${summary && summary !== "Not described in the documents" ? `<dt>${t("Areas the AI read")}</dt><dd>${esc(summary)} <span class="hint">${t("(AI summary, not verified)")}</span></dd>` : ""}
      ${summary === "Not described in the documents" ? `<dt>${t("Areas listed")}</dt><dd>${t("Not described in the hospital's documents")}</dd>` : ""}
      ${req.length ? `<dt>${t("Required at minimum")}</dt><dd><strong>${esc(req[0])}</strong> ${t("and every bordering county:")}
        ${req.slice(1).map(esc).join(", ")} <span class="hint">${t("(US Census county adjacency)")}</span></dd>` : ""}
    </dl></div>`;
}


/* ---------------------------------------------------------------- language */
function applyStatic() {
  const es = state.lang === "es" && hasES();
  document.documentElement.lang = es ? "es" : "en";
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    if (el.dataset.en === undefined) el.dataset.en = el.innerHTML;
    el.innerHTML = es && ES_STATIC[el.dataset.i18n] ? ES_STATIC[el.dataset.i18n] : el.dataset.en;
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    if (el.dataset.enPlaceholder === undefined) el.dataset.enPlaceholder = el.placeholder;
    el.placeholder = es && ES_PLACEHOLDER[el.dataset.i18nPlaceholder] ? ES_PLACEHOLDER[el.dataset.i18nPlaceholder] : el.dataset.enPlaceholder;
  });
  const btn = $("#lang-toggle");
  btn.textContent = es ? "English" : "Español";
  btn.lang = es ? "en" : "es";
}

function setLang(lang) {
  state.lang = lang;
  try { localStorage.setItem("hfal-lang", lang); } catch { /* ignore */ }
  applyStatic();
  useDataset(state.datasetKey);  // also refreshes the source line
  buildFilters();
  renderRubric();
  renderCriteriaGuide();
  render();
  if (state.map) renderLegend();
  if (!$("#drawer").hidden && state.openId != null) openDrawer(state.openId);
}
