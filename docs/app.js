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

/* ---------------------------------------------------------------- load */
fetch("data/hospitals.json")
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((data) => { state.data = data; init(); })
  .catch((e) => {
    $("main").innerHTML = `<div class="card">Could not load the data (${esc(e.message)}).
      If you opened this file directly, serve the docs/ folder instead (see README).</div>`;
  });

function init() {
  const d = state.data;
  $("#source-line").textContent = `Data: ${d.source} · Updated ${d.generated}`;
  document.querySelectorAll(".src-name").forEach((el) => (el.textContent = d.source));
  buildFilters();
  renderRubric();
  renderCriteriaGuide();
  initStaff();
  bindEvents();
  showTab((location.hash || "#overview").slice(1));
  render();
}

/* ---------------------------------------------------------------- filters */
function buildFilters() {
  const hs = state.data.hospitals;
  const counties = [...new Set(hs.map((h) => h.county).filter(Boolean))].sort();
  $("#f-region").innerHTML = `<option value="">All of New York</option>
    <option value="nyc">New York City</option><option value="non-nyc">Outside New York City</option>
    <optgroup label="County">${counties.map((c) => `<option value="county:${esc(c)}">${esc(c)}</option>`).join("")}</optgroup>`;
  const systems = [...new Set(hs.map((h) => h.system))].sort((a, b) => a.localeCompare(b));
  $("#f-system").innerHTML = `<option value="">All systems</option>` +
    systems.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  const hasRanges = hs.some(isRange);
  $("#f-grade").innerHTML = `<option value="">All grades</option>` +
    GRADES.map((g) => `<option value="${g}">${g}</option>`).join("") +
    (hasRanges ? `<option value="range">Grade pending review</option>` : "");
  $("#f-criterion").innerHTML = `<option value="">Any requirement</option>` +
    state.data.criteria.map((c) => `<option value="${c.key}">${esc(c.label)}</option>`).join("");
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

function showTab(tab) {
  if (!["overview", "hospitals", "map", "staff"].includes(tab)) tab = "overview";
  // The public filters don't apply to the staff workspace.
  document.querySelector('section.filters[aria-label="Filters"]').hidden = tab === "staff";
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== `panel-${tab}`));
  window.scrollTo(0, 0);
  if (tab === "map") { initMap(); state.map.invalidateSize(); renderMap(filtered()); }
}

/* ---------------------------------------------------------------- render */
function render() {
  const list = filtered();
  const total = state.data.hospitals.length;
  $("#f-count").textContent = list.length === total ? `Showing all ${total} hospitals`
    : `Showing ${list.length} of ${total} hospitals`;
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
    tile("Hospitals", n, list.some(isRange) ? `${list.filter(isRange).length} with grades pending review` : (filteredView ? "in this view" : "statewide")),
    tile("Meet every requirement", countA, `${pct(countA, n)}% of hospitals`),
    tile("Graded F", countF, `${pct(countF, n)}% of hospitals`),
    worst ? tile("Biggest gap", esc(worst.label), `only ${worst.rate}% meet it`, true) : tile("Biggest gap", "–", ""),
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
        <span class="lbl">${esc(s.label)}<span class="sec">${esc(sectionName(s.section))}</span></span>
        <span class="track"><span class="fill" style="width:${s.rate}%"></span></span>
        <span class="val">${s.rate}% <span class="of">${s.yes}/${s.yes + s.no}</span></span>
      </button>`).join("");

  // Feed
  const changes = state.data.changes || [];
  $("#feed").innerHTML = changes.length
    ? changes.slice(0, 60).map((c) => `<div class="item"><div class="date">${esc(c.date)}</div>
        <strong>${esc(c.hospital)}</strong>: ${esc(c.field)} changed
        ${c.old ? `from "${esc(c.old)}" ` : ""}to "${esc(c.new)}"</div>`).join("")
    : `<p class="empty-feed">None yet. This tracker currently shows the baseline from ${esc(state.data.source)};
       changes will appear here after each automated check.</p>`;
}

function renderRubric() {
  const total = state.data.criteria.length;
  const autoF = ["no financial assistance application is posted", "the application is not the full NYS Uniform Application"];
  if (state.data.policy_statement_auto_fail) autoF.push("the full financial assistance policy is not posted");
  const rows = [
    ["A", `Meets all ${total} requirements.`],
    ["B", "Falls short on 1 to 3 requirements."],
    ["C", "Falls short on 4 to 6 requirements."],
    ["D", "Falls short on 7 to 9 requirements."],
    ["F", `Falls short on 10 or more requirements, or automatically if ${autoF.join(", or ")}.`],
  ];
  $("#rubric").innerHTML = rows.map(([g, text]) =>
    `<div class="rubric-row"><dt><span class="badge g-${g}">${g}</span></dt><dd>${text}</dd></div>`).join("") +
    (state.data.hospitals.some(isRange) ? `<div class="rubric-row"><dt><span class="badge g-R">?</span></dt>
      <dd>Grade pending review: some items couldn't be confirmed automatically, so the grade is shown as a range until a person checks them.</dd></div>` : "");
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
    return `<h3 class="guide-group">${title} <span class="guide-note">${note}</span></h3>
      <dl class="guide-list">${items.map((c) => `<div class="guide-row">
        <dt>${esc(c.label)}</dt><dd>${esc(c.law)}</dd></div>`).join("")}</dl>`;
  }).join("");
}

function tile(label, value, note, small = false) {
  return `<div class="tile"><div class="label">${label}</div>
    <div class="value${small ? " small" : ""}">${value}</div><div class="note">${note}</div></div>`;
}

function sectionName(s) {
  return { "MATERIALS ON WEBSITE": "Website materials", APPLICATION: "Application", "PLAIN LANGUAGE SUMMARY": "Plain language summary" }[s] || s;
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
  $("#legend").innerHTML = GRADES.map((g) => `<span><span class="sw" style="background:${MAP_COLORS[g]}"></span>${g}</span>`).join("") +
    (state.data.hospitals.some(isRange) ? `<span><span class="sw" style="background:${MAP_COLORS.R};border-style:dashed"></span>Pending review</span>` : "") +
    `<span style="margin-left:auto">Hover a dot for details · select it for links</span>`;
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
      ${esc(h.system)}<br>Grade <strong>${esc(h.grade)}</strong> · ${h.issues} gap${h.issues === 1 ? "" : "s"}`,
      { className: "hosp-tip", direction: "top", offset: [0, -6] });
    m.bindPopup(`<strong>${esc(h.name)}</strong><br>${esc(h.address)}, ${esc(h.city)}<br>${esc(h.system)}
      <div class="pop-actions">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">Financial assistance page ↗</a>` : ""}
      <button class="linkbtn" data-open-id="${h.id}">Details</button></div>`);
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
    ? `Grade depends on ${h.needs_review} item${h.needs_review === 1 ? "" : "s"} still under review: between <strong>${h.grade_best}</strong> and <strong>${h.grade_worst}</strong>.`
    : h.grade === "A" ? "Meets every requirement checked."
    : `Falls short on <strong>${h.issues}</strong> of ${state.data.criteria.length} requirements` +
      (h.auto_fail ? ", including one that means an automatic F (no application posted, or not the full NYS Uniform Application)." : ".");
  const req = (c, cls, mark) => `<div class="req ${cls}"><div class="req-title"><span class="mark ${cls}" aria-hidden="true">${mark}</span>
      ${esc(c.label)}</div><p class="law">${esc(c.law)}</p></div>`;
  $("#d-body").innerHTML = `
    <div class="d-head"><span class="badge lg ${gradeClass(h)}" aria-label="Grade ${esc(h.grade)}">${esc(isRange(h) ? "?" : h.grade)}</span>
      <div><h2 id="d-name">${esc(h.name)}</h2>
      <div class="d-meta">${esc(h.address)}${h.address ? ", " : ""}${esc(h.city)}, NY ${esc(h.zip)}<br>
        ${esc(h.system)}${h.county ? ` · ${esc(h.county)}` : ""}</div></div></div>
    <p class="d-summary">${summary}</p>
    ${url ? `<a class="btn" href="${esc(url)}" target="_blank" rel="noopener">Hospital's financial assistance page ↗</a>` : ""}
    ${no.length ? `<div class="d-section"><h3>Where it falls short (${no.length})</h3>${no.map((c) => req(c, "no", "✕")).join("")}</div>` : ""}
    ${review.length ? `<div class="d-section"><h3>Needs review (${review.length})</h3>${review.map((c) => req(c, "review", "?")).join("")}</div>` : ""}
    ${yes.length ? `<div class="d-section"><details class="met"><summary>Requirements met (${yes.length})</summary>
      <ul>${yes.map((c) => `<li><span class="mark yes" aria-hidden="true">✓</span>${esc(c.label)}</li>`).join("")}</ul></details></div>` : ""}
    ${unknown.length ? `<p class="hint">${unknown.length} requirement(s) have no data.</p>` : ""}
    <div class="d-section"><h3>Details</h3><dl class="facts">
      ${fact("Languages", n.languages_available)}${fact("Help line", n.contact_phone)}
      ${fact("Income limit (application)", h.max_fpl ? `${h.max_fpl} of the Federal Poverty Level` : "")}
      ${fact("Time limit", n.timeframe_notes)}${fact("Inconsistencies", n.inconsistency_notes)}
      ${fact("Application notes", n.application_notes)}${fact("Summary notes", n.summary_notes)}
      ${fact("Notes", n.general_notes)}${fact("Other notes", n.other_notes)}
      ${fact("Last checked", h.last_checked || state.data.source)}</dl></div>`;
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
  const d = state.data;
  const repo = d.repo || "becca-goldrup/HFAL-Tracker";
  $("#run-btn").href = `https://github.com/${repo}/actions/workflows/check.yml`;
  $("#rv-upload").href = `https://github.com/${repo}/upload/main/data/reviews`;
  const lr = d.last_run;
  $("#run-status").innerHTML = lr
    ? `Last check: <strong>${esc(lr.date)}</strong> with ${esc(lr.model.replace(/^us\.(amazon|anthropic)\./, "").replace(/-v\d.*$/, ""))}.
       ${lr.websites} websites: ${lr.graded} graded, ${lr.unchanged} unchanged${lr.problems ? `, ${lr.problems} couldn't be checked` : ""}.
       Estimated cost about $${Number(lr.cost).toFixed(2)}.`
    : "No AI check has run yet. The dashboard currently shows CSS's September 2025 review.";

  staff.key = `hfal-review:${d.generated}`;
  staff.decisions = storageGet(staff.key, {});
  $("#rv-name").value = storageGet("hfal-reviewer", "");
  $("#rv-name").addEventListener("input", (e) => storageSet("hfal-reviewer", e.target.value));

  const items = d.review || [];
  const systems = [...new Set(items.map((i) => i.system))].sort((a, b) => a.localeCompare(b));
  $("#rv-system").innerHTML = `<option value="">All systems</option>` +
    systems.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  const reqs = [...new Set(items.map((i) => i.requirement))].sort();
  $("#rv-req").innerHTML = `<option value="">All requirements</option>` +
    reqs.map((r) => `<option value="${esc(r)}">${esc(r)}</option>`).join("");
  ["#rv-system", "#rv-req", "#rv-show"].forEach((s) => $(s).addEventListener("change", renderReview));

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
  $("#rv-download").addEventListener("click", downloadDecisions);
  $("#rv-clear").addEventListener("click", () => {
    if (!confirm("Clear all the decisions saved in this browser?")) return;
    staff.decisions = {};
    storageSet(staff.key, {});
    renderReview();
  });
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
  $("#send-summary").textContent = done
    ? `You've decided ${done} item${done === 1 ? "" : "s"}. Download them and upload the file to apply them.`
    : "Decide at least one item above, then send your decisions here.";
  $("#rv-download").disabled = !done;

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

function downloadDecisions() {
  const items = state.data.review || [];
  const name = ($("#rv-name").value || "").trim();
  const decisions = items.filter((i) => decided(i.id)).map((i) => ({
    id: i.id, hfa_url: i.hfa_url, column: i.column, requirement: i.requirement,
    decision: decided(i.id), note: (staff.decisions[i.id] || {}).note || "", hospitals: i.hospitals,
  }));
  const today = new Date().toISOString().slice(0, 10);
  const blob = new Blob([JSON.stringify({ reviewer: name, submitted: today, data_generated: state.data.generated,
    decisions }, null, 1)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  link.download = `reviews-${today}${slug ? "-" + slug : ""}.json`;
  document.body.appendChild(link);
  link.click();
  link.parentNode.removeChild(link);
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
