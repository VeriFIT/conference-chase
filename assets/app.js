"use strict";

const DAY = 86400000;
const DATE_FIELDS = [
  ["abstract_deadline", "Abstract"],
  ["submission_deadline", "Submission"],
  ["notification", "Notification"],
  ["final_version", "Final version"],
];

const state = {
  data: null,
  view: "cards",
  query: "",
  categories: new Set(),
  showPast: false,
  localTime: false,
  sort: { key: "submission", dir: 1 },
};

const $ = (sel) => document.querySelector(sel);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}

/* ---------- Dates ---------- */

/** Offset in hours of a timezone label: AoE, UTC, UTC+2, UTC-5:30. */
function tzOffset(tz) {
  if (!tz || tz === "UTC") return 0;
  if (tz === "AoE") return -12;
  const m = /^UTC([+-])(\d{1,2})(?::(\d{2}))?$/.exec(tz);
  if (!m) return 0;
  const hours = Number(m[2]) + Number(m[3] || 0) / 60;
  return m[1] === "-" ? -hours : hours;
}

/** Absolute instant of a deadline; date-only deadlines end at 23:59 in their timezone. */
function deadlineInstant(value, tz) {
  if (!value) return null;
  const [d, t = "23:59"] = value.split("T");
  const [y, mo, da] = d.split("-").map(Number);
  const [h, mi] = t.split(":").map(Number);
  return new Date(Date.UTC(y, mo - 1, da, h, mi) - tzOffset(tz || "AoE") * 3600000);
}

/** Plain calendar date as a Date at local noon (for display / timeline placement). */
function calendarDate(value) {
  if (!value) return null;
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d, 12);
}

const fmtDay = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });
const fmtDayTime = new Intl.DateTimeFormat(undefined, {
  day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short",
});

function formatDeadline(value, tz) {
  if (!value) return "—";
  if (state.localTime) return fmtDayTime.format(deadlineInstant(value, tz));
  const day = fmtDay.format(calendarDate(value));
  const time = value.includes("T") ? ` ${value.split("T")[1]}` : "";
  return `${day}${time} ${tz || "AoE"}`;
}

function formatDay(value) {
  return value ? fmtDay.format(calendarDate(value)) : "—";
}

function formatRange(start, end) {
  if (!start) return "";
  return end && end !== start ? `${formatDay(start)} – ${formatDay(end)}` : formatDay(start);
}

function countdown(instant, now) {
  const diff = instant - now;
  if (diff <= 0) return { text: `closed ${Math.floor(-diff / DAY)}d ago`, cls: "past" };
  const d = Math.floor(diff / DAY);
  const h = Math.floor((diff % DAY) / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  const text = d > 0 ? `${d}d ${h}h ${m}m left` : `${h}h ${m}m left`;
  return { text, cls: d < 14 ? "urgent" : d < 31 ? "soon" : "" };
}

/* ---------- Data shaping ---------- */

function categoryColor(category) {
  const idx = state.data.categories.indexOf(category);
  return `var(--cat-${(idx < 0 ? 0 : idx) % 6})`;
}

/** Flatten to one entry per round, with the submission instant precomputed. */
function roundEntries(conf) {
  return conf.editions.flatMap((edition) => edition.rounds.map((round) => ({
    conf, edition, round,
    submission: deadlineInstant(round.submission_deadline, round.timezone),
  })));
}

function matchesFilters(conf) {
  if (state.categories.size && !state.categories.has(conf.category)) return false;
  if (!state.query) return true;
  const q = state.query.toLowerCase();
  return [conf.acronym, conf.name, conf.category, ...conf.editions.map((e) => e.location)]
    .some((s) => s && s.toLowerCase().includes(q));
}

/** Upcoming round with the earliest deadline, else the most recent past one. */
function nextRound(conf, now) {
  const entries = roundEntries(conf).filter((e) => e.submission);
  const upcoming = entries.filter((e) => e.submission >= now).sort((a, b) => a.submission - b.submission);
  if (upcoming.length) return upcoming[0];
  return entries.sort((a, b) => b.submission - a.submission)[0] || null;
}

/* ---------- Views ---------- */

function renderCards(confs, now) {
  const withNext = confs.map((conf) => ({ conf, next: nextRound(conf, now) }));
  const upcoming = withNext.filter((x) => x.next && x.next.submission >= now)
    .sort((a, b) => a.next.submission - b.next.submission);
  const past = withNext.filter((x) => x.next && x.next.submission < now)
    .sort((a, b) => b.next.submission - a.next.submission);
  const unknown = withNext.filter((x) => !x.next).sort((a, b) => a.conf.acronym.localeCompare(b.conf.acronym));

  let html = upcoming.length
    ? `<div class="grid">${upcoming.map((x) => card(x.conf, x.next, now)).join("")}</div>`
    : `<p class="empty">No upcoming deadlines match the filters.</p>`;
  if (state.showPast && past.length) {
    html += `<h2 class="section-title">Deadline passed — next edition not announced yet</h2>
      <div class="grid">${past.map((x) => card(x.conf, x.next, now)).join("")}</div>`;
  }
  if (unknown.length) {
    html += `<h2 class="section-title">No dates known yet</h2>
      <div class="grid">${unknown.map((x) => emptyCard(x.conf)).join("")}</div>`;
  }
  return html;
}

function cardHead(conf, edition) {
  const title = edition ? `${conf.acronym} ${edition.year}` : conf.acronym;
  const low = edition && edition.confidence === "low"
    ? ` <span class="badge badge-low" title="Low confidence — verify on the official site">unverified</span>` : "";
  return `<div class="card-head">
      <div><h3 class="card-title">${esc(title)}${low}</h3><p class="card-name">${esc(conf.name)}</p></div>
      <span class="badge badge-cat">${esc(conf.category)}</span>
    </div>`;
}

function link(url, text) {
  return url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : "";
}

function rebuttalText(round) {
  if (!round.rebuttal_start && !round.rebuttal_end) return null;
  return formatRange(round.rebuttal_start || round.rebuttal_end, round.rebuttal_end);
}

function datesList(round, edition, now) {
  const row = (label, text, doneAt) =>
    `<dt>${label}</dt><dd${doneAt && doneAt < now ? ' class="done"' : ""}>${esc(text)}</dd>`;
  const items = DATE_FIELDS.map(([key, label]) => {
    const value = round[key];
    if (!value && key === "abstract_deadline") return "";
    const isDeadline = key.endsWith("deadline");
    const instant = isDeadline ? deadlineInstant(value, round.timezone) : calendarDate(value);
    const text = isDeadline ? formatDeadline(value, round.timezone) : formatDay(value);
    const html = row(label, text, instant);
    // The rebuttal period sits between submission and notification.
    const rebuttal = rebuttalText(round);
    return key === "submission_deadline" && rebuttal
      ? html + row("Rebuttal", rebuttal, calendarDate(round.rebuttal_end || round.rebuttal_start))
      : html;
  });
  if (round.page_limit) items.push(row("Page limit", round.page_limit));
  const links = [
    round.cfp && round.cfp !== edition.cfp && link(round.cfp, "Call for papers"),
    link(round.submission_link, "Submit"),
  ].filter(Boolean).join("");
  return `<dl class="dates">${items.join("")}</dl>`
    + (links ? `<div class="round-links">${links}</div>` : "")
    + (round.notes ? `<div class="round-notes">${esc(round.notes)}</div>` : "");
}

function card(conf, next, now) {
  const { edition, round } = next;
  const cd = countdown(next.submission, now);
  const rounds = edition.rounds.length > 1
    ? edition.rounds.map((r) => `<div class="round-name">${esc(r.name)}</div>${datesList(r, edition, now)}`).join("")
    : datesList(round, edition, now);
  const meta = [edition.location, formatRange(edition.conference_start, edition.conference_end)]
    .filter(Boolean).map(esc).join(" · ");
  const links = [
    link(edition.cfp, "Call for papers"),
    link(edition.link, "Website"),
    edition.source !== edition.link && edition.source !== edition.cfp && link(edition.source, "Source"),
  ].filter(Boolean).join("");
  const checked = edition.last_checked ? `checked ${esc(edition.last_checked)}` : "";
  return `<article class="card${cd.cls === "past" ? " is-past" : ""}" style="--c:${categoryColor(conf.category)}">
      ${cardHead(conf, edition)}
      ${meta ? `<div class="card-meta">${meta}</div>` : ""}
      <div class="countdown ${cd.cls}" data-deadline="${next.submission.getTime()}"
        data-prefix="${edition.rounds.length > 1 ? esc(`${round.name}: `) : ""}">
        ${edition.rounds.length > 1 ? `${esc(round.name)}: ` : ""}${cd.text}</div>
      ${rounds}
      <div class="card-links">${links}<span class="card-meta" title="${esc(edition.notes || "")}">${checked}</span></div>
    </article>`;
}

function emptyCard(conf) {
  return `<article class="card is-empty" style="--c:${categoryColor(conf.category)}">
      ${cardHead(conf, null)}
      <div class="card-meta">Dates not announced or not gathered yet${conf.last_checked ? ` (checked ${esc(conf.last_checked)})` : ""}.</div>
      <div class="card-links">${link(conf.homepage, "Homepage")}</div>
    </article>`;
}

function renderTimeline(confs, now) {
  const start = new Date(now.getFullYear(), now.getMonth() - (state.showPast ? 3 : 0), 1);
  const end = new Date(start.getFullYear(), start.getMonth() + 13, 1);
  const span = end - start;
  const pos = (date) => ((date - start) / span) * 100;
  const inRange = (date) => date && date >= start && date < end;

  const months = [];
  for (let d = new Date(start); d < end; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) {
    const label = d.toLocaleDateString(undefined, { month: "short", ...(d.getMonth() === 0 ? { year: "2-digit" } : {}) });
    months.push(`<div class="tl-month" style="left:${pos(d)}%"></div>
      <span class="tl-month-label" style="left:${pos(d)}%">${esc(label)}</span>`);
  }
  const grid = months.join("");
  const today = `<div class="tl-today" style="left:${pos(now)}%" title="Today"></div>`;

  const rows = [];
  for (const conf of confs) {
    const marks = [];
    let firstMark = Infinity;
    for (const { edition, round } of roundEntries(conf)) {
      const cs = calendarDate(edition.conference_start);
      const ce = calendarDate(edition.conference_end) || cs;
      if (cs && ce >= start && cs < end) {
        const l = Math.max(0, pos(cs));
        const r = Math.min(100, pos(new Date(ce.getTime() + DAY)));
        marks.push(`<div class="tl-span" style="left:${l}%;width:${r - l}%"
          title="${esc(`${conf.acronym} ${edition.year}: ${formatRange(edition.conference_start, edition.conference_end)} ${edition.location || ""}`)}"></div>`);
      }
      const rs = calendarDate(round.rebuttal_start || round.rebuttal_end);
      const re = calendarDate(round.rebuttal_end) || rs;
      if (rs && re >= start && rs < end) {
        const l = Math.max(0, pos(rs));
        const r = Math.min(100, pos(new Date(re.getTime() + DAY)));
        const roundLabel = edition.rounds.length > 1 ? ` (${round.name})` : "";
        marks.push(`<div class="tl-rebuttal" style="left:${l}%;width:${r - l}%"
          title="${esc(`${conf.acronym} ${edition.year}${roundLabel} — Rebuttal: ${rebuttalText(round)}`)}"></div>`);
      }
      for (const [key, label] of DATE_FIELDS) {
        const value = round[key];
        const date = key.endsWith("deadline") ? deadlineInstant(value, round.timezone) : calendarDate(value);
        if (!inRange(date)) continue;
        if (key === "submission_deadline") firstMark = Math.min(firstMark, date >= now ? date : Infinity);
        const roundLabel = edition.rounds.length > 1 ? ` (${round.name})` : "";
        const text = key.endsWith("deadline") ? formatDeadline(value, round.timezone) : formatDay(value);
        marks.push(`<div class="tl-mark ${key.split("_")[0]}" style="left:${pos(date)}%"
          title="${esc(`${conf.acronym} ${edition.year}${roundLabel} — ${label}: ${text}`)}"></div>`);
      }
    }
    if (marks.length) rows.push({ conf, firstMark, marks });
  }
  if (!rows.length) return `<p class="empty">No dates in this period match the filters.</p>`;
  rows.sort((a, b) => a.firstMark - b.firstMark || a.conf.acronym.localeCompare(b.conf.acronym));
  // A single "today" line spans the whole chart, so the per-row track only holds the grid.
  const body = rows.map(({ conf, marks }) => `
    <div class="tl-row" style="--c:${categoryColor(conf.category)}">
      <div class="tl-label" title="${esc(conf.name)}">${esc(conf.acronym)}</div>
      <div class="tl-track">${grid.replace(/<span[^>]*>.*?<\/span>/g, "")}${today}${marks.join("")}</div>
    </div>`).join("");
  return `<div class="timeline"><div class="tl-inner">
      <div class="tl-row tl-axis"><div></div><div class="tl-track">${grid}</div></div>
      ${body}
    </div>
    <div class="tl-legend">
      <span><i class="tl-mark abstract"></i>Abstract</span>
      <span><i class="tl-mark submission"></i>Submission</span>
      <span><i class="tl-rebuttal" style="position:static;display:inline-block;width:18px;transform:none;--c:var(--muted)"></i>Rebuttal</span>
      <span><i class="tl-mark notification"></i>Notification</span>
      <span><i class="tl-mark final"></i>Final version</span>
      <span><i class="tl-span" style="position:static;display:inline-block;width:22px;transform:none;--c:var(--muted)"></i>Conference</span>
      <span><i class="tl-today" style="position:static;display:inline-block;height:12px"></i>Today</span>
    </div></div>`;
}

const TABLE_COLUMNS = [
  { key: "acronym", label: "Conference", value: (e) => e.conf.acronym },
  { key: "category", label: "Category", value: (e) => e.conf.category },
  { key: "year", label: "Year", value: (e) => e.edition.year },
  { key: "round", label: "Round", value: (e) => e.round.name },
  { key: "abstract", label: "Abstract", value: (e) => deadlineInstant(e.round.abstract_deadline, e.round.timezone) },
  { key: "submission", label: "Submission", value: (e) => e.submission },
  { key: "rebuttal", label: "Rebuttal", value: (e) => calendarDate(e.round.rebuttal_start || e.round.rebuttal_end) },
  { key: "notification", label: "Notification", value: (e) => calendarDate(e.round.notification) },
  { key: "final", label: "Final", value: (e) => calendarDate(e.round.final_version) },
  { key: "location", label: "Location", value: (e) => e.edition.location || "" },
  { key: "dates", label: "Conference dates", value: (e) => calendarDate(e.edition.conference_start) },
  { key: "links", label: "Links", value: () => null },
];

function renderTable(confs, now) {
  let entries = confs.flatMap(roundEntries);
  if (!state.showPast) entries = entries.filter((e) => !e.submission || e.submission >= now);
  if (!entries.length) return `<p class="empty">No rounds match the filters.</p>`;
  const col = TABLE_COLUMNS.find((c) => c.key === state.sort.key) || TABLE_COLUMNS.find((c) => c.key === "submission");
  entries.sort((a, b) => {
    const va = col.value(a), vb = col.value(b);
    if (va == null || va === "") return 1; // unknown values always last
    if (vb == null || vb === "") return -1;
    return (va < vb ? -1 : va > vb ? 1 : 0) * state.sort.dir;
  });
  const head = TABLE_COLUMNS.map((c) => {
    const sort = c.key === state.sort.key ? (state.sort.dir > 0 ? "ascending" : "descending") : "none";
    if (c.key === "links") return `<th>${c.label}</th>`;
    return `<th data-sort="${c.key}" aria-sort="${sort}">${c.label}</th>`;
  }).join("");
  const rows = entries.map(({ conf, edition, round, submission }) => {
    const name = edition.link
      ? `<a href="${esc(edition.link)}" target="_blank" rel="noopener">${esc(conf.acronym)}</a>` : esc(conf.acronym);
    const low = edition.confidence === "low" ? ` <span class="badge badge-low">unverified</span>` : "";
    return `<tr class="${submission && submission < now ? "is-past" : ""}">
      <td>${name}${low}</td>
      <td><span class="badge badge-cat" style="--c:${categoryColor(conf.category)}">${esc(conf.category)}</span></td>
      <td class="num">${edition.year}</td>
      <td>${esc(round.name)}</td>
      <td class="num">${esc(round.abstract_deadline ? formatDeadline(round.abstract_deadline, round.timezone) : "—")}</td>
      <td class="num"><strong>${esc(formatDeadline(round.submission_deadline, round.timezone))}</strong></td>
      <td class="num">${esc(rebuttalText(round) || "—")}</td>
      <td class="num">${esc(formatDay(round.notification))}</td>
      <td class="num">${esc(formatDay(round.final_version))}</td>
      <td>${esc(edition.location || "")}</td>
      <td class="num">${esc(formatRange(edition.conference_start, edition.conference_end))}</td>
      <td class="table-links">${[link(round.cfp || edition.cfp, "CFP"), link(round.submission_link, "Submit")].filter(Boolean).join(" ")}</td>
    </tr>`;
  }).join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

/* ---------- State, URL hash, wiring ---------- */

function render() {
  const now = new Date();
  const confs = state.data.conferences.filter(matchesFilters);
  const views = { cards: renderCards, timeline: renderTimeline, table: renderTable };
  $("#view").innerHTML = views[state.view](confs, now);
  document.querySelectorAll(".tabs button").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.view === state.view)));
  document.querySelectorAll(".chip").forEach((c) =>
    c.setAttribute("aria-pressed", String(state.categories.has(c.dataset.category))));
  writeHash();
}

function tickCountdowns() {
  const now = new Date();
  document.querySelectorAll(".countdown[data-deadline]").forEach((el) => {
    const cd = countdown(new Date(Number(el.dataset.deadline)), now);
    el.textContent = el.dataset.prefix + cd.text;
    el.className = `countdown ${cd.cls}`;
  });
}

function writeHash() {
  const p = new URLSearchParams();
  if (state.view !== "cards") p.set("view", state.view);
  if (state.query) p.set("q", state.query);
  if (state.categories.size) p.set("cat", [...state.categories].join("|"));
  if (state.showPast) p.set("past", "1");
  if (state.localTime) p.set("local", "1");
  const hash = p.toString();
  history.replaceState(null, "", hash ? `#${hash}` : location.pathname + location.search);
}

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  state.view = ["cards", "timeline", "table"].includes(p.get("view")) ? p.get("view") : "cards";
  state.query = p.get("q") || "";
  state.categories = new Set((p.get("cat") || "").split("|").filter((c) => state.data.categories.includes(c)));
  state.showPast = p.get("past") === "1";
  state.localTime = p.get("local") === "1";
  $("#search").value = state.query;
  $("#show-past").checked = state.showPast;
  $("#local-time").checked = state.localTime;
}

function setup() {
  $("#categories").innerHTML = state.data.categories.map((c) =>
    `<button class="chip" data-category="${esc(c)}" style="--c:${categoryColor(c)}" aria-pressed="false">${esc(c)}</button>`).join("");
  $("#categories").addEventListener("click", (ev) => {
    const chip = ev.target.closest(".chip");
    if (!chip) return;
    const c = chip.dataset.category;
    state.categories.has(c) ? state.categories.delete(c) : state.categories.add(c);
    render();
  });
  document.querySelector(".tabs").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-view]");
    if (btn) { state.view = btn.dataset.view; render(); }
  });
  $("#search").addEventListener("input", (ev) => { state.query = ev.target.value.trim(); render(); });
  $("#show-past").addEventListener("change", (ev) => { state.showPast = ev.target.checked; render(); });
  $("#local-time").addEventListener("change", (ev) => { state.localTime = ev.target.checked; render(); });
  $("#view").addEventListener("click", (ev) => {
    const th = ev.target.closest("th[data-sort]");
    if (!th) return;
    const key = th.dataset.sort;
    state.sort = { key, dir: state.sort.key === key ? -state.sort.dir : 1 };
    render();
  });
  window.addEventListener("hashchange", () => { readHash(); render(); });
  setInterval(tickCountdowns, 30000);
}

async function main() {
  try {
    const resp = await fetch("data/conferences.json", { cache: "no-cache" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    state.data = await resp.json();
  } catch (err) {
    $("#view").innerHTML = `<p class="empty">Could not load conference data (${esc(err.message)}).</p>`;
    return;
  }
  $("#updated").textContent = `updated ${formatDay(state.data.updated)} · ${state.data.conferences.length} conferences`;
  setup();
  readHash();
  render();
}

main();
