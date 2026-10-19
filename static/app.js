// Lifafa — the family gift ledger. Everything stays on this computer.

import { alertIn, api, app, dialog, dialogBody, esc, openDialog, prettyDate, rupees, toast } from "./util.js";
import { peopleView, personView, searchView } from "./people.js";
import { voicePanel } from "./voice.js";

// --- home ----------------------------------------------------------------------------------

async function home() {
  const [events, health] = await Promise.all([api("/events"), api("/health")]);
  const all = events.reduce((a, e) => ({ guests: a.guests + e.guests, cash: a.cash + e.cash_total }), { guests: 0, cash: 0 });
  app.innerHTML = `
    <h1>Every lifafa, remembered.</h1>
    <p class="lede">Photograph the shagun register. Lifafa reads the handwriting, checks the totals, and keeps a ledger you can search
      the next time you're invited, so you know what each family gave at yours.</p>
    <p class="muted">${health.ai.available ? "● " : "○ "}${esc(health.ai.message)}</p>
    ${events.length ? `<div class="stats">
        <div class="stat"><span class="muted">Events</span><b>${events.length}</b></div>
        <div class="stat"><span class="muted">Guests recorded</span><b>${all.guests}</b></div>
        <div class="stat"><span class="muted">Shagun recorded</span><b>${rupees(all.cash)}</b></div>
      </div>` : ""}
    <div class="card">
      <h2>New event</h2>
      <form id="new-event" class="grid2">
        <input name="name" required maxlength="80" placeholder="Riya's wedding">
        <input name="event_date" type="date" aria-label="Date">
        <input name="from_name" maxlength="60" placeholder="Thank-you notes signed by (e.g. The Agarwal family)">
        <button class="btn">Create event</button>
      </form>
    </div>
    ${events.length ? `<h2>Your events</h2><ul class="events">${events.map((e) => `
      <li><a href="#/event/${e.id}">
        <b>${esc(e.name)}</b> <span class="muted">${prettyDate(e.event_date)}</span><br>
        <span class="muted">${e.guests} guests · ${rupees(e.cash_total)}</span>
        ${e.to_review ? `<span class="chip warn">${e.to_review} to check</span>` : ""}
      </a></li>`).join("")}</ul>` : ""}`;

  document.getElementById("new-event").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    try {
      const e = await api("/events", { method: "POST", body: JSON.stringify({
        name: f.get("name"), event_date: f.get("event_date") || null, from_name: f.get("from_name") || null }) });
      location.hash = `#/event/${e.id}`;
    } catch (err) { toast(err.message); }
  });
}

// --- event ---------------------------------------------------------------------------------

let pending = []; // pages read but not yet added: [{file, rows, check, written_total, latency_ms, message}]

async function eventView(id) {
  const [e, events] = await Promise.all([api(`/events/${id}`), api("/events")]);
  const s = e.summary;
  app.innerHTML = `
    <p class="muted"><a href="#/">← All events</a></p>
    <div class="row" style="justify-content:space-between">
      <h1>${esc(e.name)}</h1>
      <div class="row">
        <a class="btn ghost small" href="/api/events/${e.id}/export.csv">Export CSV</a>
      </div>
    </div>
    <p class="muted">${prettyDate(e.event_date)}${e.from_name ? ` · notes signed “${esc(e.from_name)}”` : ""}</p>
    <div class="stats">
      <div class="stat"><span class="muted">Guests</span><b>${s.guests}</b></div>
      <div class="stat"><span class="muted">Cash</span><b>${rupees(s.cash_total)}</b></div>
      <div class="stat"><span class="muted">Gifts</span><b>${s.gifts}</b></div>
      <div class="stat"><span class="muted">Thanked</span><b>${s.thanked}/${s.guests}</b></div>
    </div>

    <div class="card">
      <h2>Add register pages</h2>
      <p class="muted">Take a clear, straight photo of each page. Gemma reads one page at a time on this computer (about 10–60 seconds each).
        Location data is removed from the photo first.</p>
      <label class="btn" style="margin-top:8px">Choose page photos
        <input type="file" id="pages" accept="image/*" multiple hidden>
      </label>
      <div id="pending"></div>
    </div>

    <div class="card">
      <h2>Speak an entry</h2>
      <p class="muted">At the shagun table: say the name, place and amount in English, Hindi or another Indian language.
        Lifafa reads it back and adds it only when you confirm. Listening and understanding both happen on this computer.</p>
      <div id="voice"></div>
    </div>

    <div class="card">
      <div class="row" style="justify-content:space-between">
        <h2>Ledger</h2>
        <input id="filter" type="search" placeholder="Filter this event" style="max-width:240px">
      </div>
      ${s.to_review ? `<p class="banner warn">${s.to_review} row${s.to_review > 1 ? "s" : ""} need a second look (highlighted).</p>` : ""}
      <div class="table-wrap"><table>
        <thead><tr><th>Name</th><th>Place</th><th class="amt">Amount</th><th>Gift</th><th></th></tr></thead>
        <tbody id="ledger">${e.entries.map(entryRow).join("")}</tbody>
      </table></div>
      ${e.entries.length ? "" : `<p class="muted">No entries yet. Add a page photo above, or type one below.</p>`}
      <form id="add-entry" class="row" style="margin-top:12px">
        <input name="name" required maxlength="80" placeholder="Name" style="flex:2;min-width:140px">
        <input name="place" maxlength="60" placeholder="Place" style="flex:1;min-width:100px">
        <input name="amount" type="number" min="0" placeholder="₹ Amount" style="flex:1;min-width:100px">
        <input name="gift" maxlength="80" placeholder="Gift (optional)" style="flex:1;min-width:120px">
        <button class="btn ghost">Add</button>
      </form>
    </div>
    ${e.pages.length ? `<div class="card"><h2>Pages</h2>${e.pages.map((p, i) => `
      <p>Page ${i + 1}: ${p.rows} rows, ${rupees(p.read_total)}
        ${p.check ? (p.check.matches ? `<span class="chip ok">matches written total</span>`
          : `<span class="chip warn">written total ${rupees(p.written_total)}</span>`) : ""}
        <button class="linkish" data-photo="${esc(p.file)}">view photo</button></p>`).join("")}</div>` : ""}`;

  renderPending(e);
  bindEvent(e);
  voicePanel(document.getElementById("voice"), { mode: "received", eventId: e.id, events, onSaved: () => eventView(e.id) });
}

function entryRow(n) {
  return `
    <tr data-id="${n.id}" class="${n.review ? "flag" : ""}" data-search="${esc(`${n.name} ${n.place || ""} ${n.gift || ""}`.toLowerCase())}">
      <td>${n.contact_id ? `<a href="#/person/${n.contact_id}"><b>${esc(n.name)}</b></a>` : `<b>${esc(n.name)}</b>`}${n.source === "voice" ? ' <span class="muted" title="Added by voice">🎤</span>' : ""}
        ${n.review ? `<br><span class="chip warn">${esc(n.review)}</span>` : ""}</td>
      <td>${esc(n.place || "")}</td>
      <td class="amt">${rupees(n.amount)}</td>
      <td>${esc(n.gift || "")}</td>
      <td class="row" style="justify-content:flex-end;flex-wrap:nowrap">
        ${n.review ? `<button class="btn ghost small" data-act="ok">Looks right</button>` : ""}
        <button class="btn ghost small" data-act="edit">Edit</button>
        <button class="btn ${n.thanked ? "ghost" : ""} small" data-act="thanks" title="${n.thanked_at ? `Thanked ${prettyDate(n.thanked_at)}` : ""}">${n.thanked ? "Thanked ✓" : "Thank"}</button>
      </td>
    </tr>`;
}

function bindEvent(e) {
  document.getElementById("pages").addEventListener("change", (ev) => readPages(e, [...ev.target.files]));

  document.getElementById("filter").addEventListener("input", (ev) => {
    const q = ev.target.value.toLowerCase().trim();
    document.querySelectorAll("#ledger tr").forEach((tr) => { tr.hidden = q && !tr.dataset.search.includes(q); });
  });

  document.getElementById("add-entry").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    try {
      await api(`/events/${e.id}/entries`, { method: "POST", body: JSON.stringify({
        name: f.get("name"), place: f.get("place") || null, amount: f.get("amount") ? Number(f.get("amount")) : null,
        gift: f.get("gift") || null }) });
      eventView(e.id);
    } catch (err) { toast(err.message); }
  });

  app.querySelectorAll("[data-photo]").forEach((b) =>
    b.addEventListener("click", () => openDialog(`<img src="/api/pages/${esc(b.dataset.photo)}" alt="Register page"><p><button class="btn ghost" data-close>Close</button></p>`)));

  document.getElementById("ledger").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-act]");
    if (!btn) return;
    const id = btn.closest("tr").dataset.id;
    const n = e.entries.find((x) => String(x.id) === id);
    if (btn.dataset.act === "ok") {
      await api(`/entries/${id}`, { method: "PATCH", body: JSON.stringify({ reviewed: true }) });
      eventView(e.id);
    } else if (btn.dataset.act === "edit") {
      editEntry(e, n);
    } else {
      thankEntry(e, n);
    }
  });
}

function editEntry(e, n) {
  openDialog(`
    <h2>Edit entry</h2>
    <form id="edit" class="grid2">
      <label>Name<input name="name" required maxlength="80" value="${esc(n.name)}"></label>
      <label>Place<input name="place" maxlength="60" value="${esc(n.place || "")}"></label>
      <label>Amount (₹)<input name="amount" type="number" min="0" value="${n.amount ?? ""}"></label>
      <label>Gift<input name="gift" maxlength="80" value="${esc(n.gift || "")}"></label>
      <label>WhatsApp number<input name="phone" inputmode="tel" placeholder="98xxxxxxxx" value="${esc(n.phone || "")}"></label>
      <label>Note<input name="note" maxlength="200" value="${esc(n.note || "")}"></label>
    </form>
    <div class="row" style="justify-content:space-between;margin-top:14px">
      <button class="btn ghost" id="del" style="color:var(--maroon)">Delete</button>
      <div class="row"><button class="btn ghost" data-close>Cancel</button><button class="btn" id="save">Save</button></div>
    </div>`);
  document.getElementById("save").addEventListener("click", async () => {
    const f = new FormData(document.getElementById("edit"));
    try {
      await api(`/entries/${n.id}`, { method: "PATCH", body: JSON.stringify({
        name: f.get("name"), place: f.get("place") || null, gift: f.get("gift") || null, note: f.get("note") || null,
        phone: f.get("phone") || "", amount: f.get("amount") === "" ? null : Number(f.get("amount")), reviewed: true }) });
      dialog.close();
      eventView(e.id);
    } catch (err) { alertIn(err.message); }
  });
  document.getElementById("del").addEventListener("click", async () => {
    if (document.getElementById("del").dataset.sure !== "1") {
      document.getElementById("del").dataset.sure = "1";
      document.getElementById("del").textContent = "Tap again to delete";
      return;
    }
    await api(`/entries/${n.id}`, { method: "DELETE" });
    dialog.close();
    eventView(e.id);
  });
}

async function thankEntry(e, n, lang = "en") {
  const t = await api(`/entries/${n.id}/thanks?lang=${lang}`);
  openDialog(`
    <h2>Thank ${esc(n.name)}</h2>
    <div class="row"><button class="btn ${lang === "en" ? "" : "ghost"} small" data-lang="en">English</button>
      <button class="btn ${lang === "hi" ? "" : "ghost"} small" data-lang="hi">हिंदी</button></div>
    <pre class="msg">${esc(t.text)}</pre>
    <p class="muted">The note never mentions the amount, on purpose.</p>
    <div class="row" style="justify-content:flex-end">
      <button class="btn ghost" id="copy">Copy</button>
      ${t.whatsapp ? `<a class="btn ghost" href="${esc(t.whatsapp)}" target="_blank" rel="noopener">Open in WhatsApp</a>` : ""}
      <button class="btn" id="done">${n.thanked ? "Mark not thanked" : "Mark as thanked"}</button>
    </div>
    ${t.whatsapp ? "" : `<p class="muted">Add their number (Edit) to open the note straight in WhatsApp.</p>`}`);
  dialogBody.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => thankEntry(e, n, b.dataset.lang)));
  document.getElementById("copy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(t.text); document.getElementById("copy").textContent = "Copied ✓"; } catch { /* select manually */ }
  });
  document.getElementById("done").addEventListener("click", async () => {
    await api(`/entries/${n.id}`, { method: "PATCH", body: JSON.stringify({ thanked: !n.thanked }) });
    dialog.close();
    eventView(e.id);
  });
}

// --- reading pages -------------------------------------------------------------------------

async function readPages(e, files) {
  for (let i = 0; i < files.length; i++) {
    const box = document.getElementById("pending");
    const status = document.createElement("p");
    status.className = "loading";
    status.textContent = `Reading page ${i + 1} of ${files.length}… Gemma is going through the handwriting.`;
    box.prepend(status);
    const form = new FormData();
    form.append("photo", files[i]);
    try {
      const result = await api(`/events/${e.id}/read-page`, { method: "POST", body: form });
      pending.push({ ...result, eventId: e.id });
    } catch (err) {
      toast(err.message);
    }
    status.remove();
    renderPending(e);
  }
}

function renderPending(e) {
  const box = document.getElementById("pending");
  const mine = pending.filter((p) => p.eventId === e.id);
  box.innerHTML = mine.map((p, i) => {
    const c = p.check;
    const banner = !p.ai ? `<p class="banner warn">${esc(p.message)}</p>`
      : c && c.written_total !== null ? (c.matches
        ? `<p class="banner ok">✓ Rows add up to ${rupees(c.read_total)}, matching the total written on the page.</p>`
        : `<p class="banner warn">The page says ${rupees(c.written_total)}, but the rows add up to ${rupees(c.read_total)}
           (${c.difference > 0 ? "short by" : "over by"} ${rupees(Math.abs(c.difference))}). Compare each amount with the photo before adding.</p>`)
      : p.message ? `<p class="banner warn">${esc(p.message)}</p>`
      : `<p class="banner ok">Read ${p.rows.length} rows (${rupees(c?.read_total)}). No total written on the page to check against.</p>`;
    return `
    <div class="card" data-pending="${i}" style="background:var(--paper)">
      <div class="review-layout">
        <img class="page-photo" src="/api/pages/${esc(p.file)}" alt="Register page photo" data-zoom="${esc(p.file)}">
        <div>
          <h3 style="margin:0">Check this page</h3>
          ${banner}
          <div class="table-wrap"><table>
            <thead><tr><th>Name</th><th>Place</th><th class="amt">₹</th><th>Gift</th><th></th></tr></thead>
            <tbody>${p.rows.map((r, j) => `
              <tr class="${r.review ? "flag" : ""}" data-row="${j}">
                <td><input data-f="name" value="${esc(r.name)}" maxlength="80">${r.review ? `<span class="chip warn">${esc(r.review)}</span>` : ""}</td>
                <td><input data-f="place" value="${esc(r.place || "")}" maxlength="60"></td>
                <td class="amt"><input data-f="amount" type="number" min="0" value="${r.amount ?? ""}"></td>
                <td><input data-f="gift" value="${esc(r.gift || "")}" maxlength="80"></td>
                <td><button class="linkish" data-drop="${j}" aria-label="Remove row">✕</button></td>
              </tr>`).join("")}</tbody>
          </table></div>
          <p class="row" style="margin-top:6px"><button class="linkish" data-addrow>+ add a row it missed</button></p>
          <div class="row" style="justify-content:flex-end;margin-top:10px">
            <button class="btn ghost" data-discard>Discard page</button>
            <button class="btn" data-save>Add ${p.rows.length} entries to the ledger</button>
          </div>
        </div>
      </div>
    </div>`;
  }).join("");

  box.querySelectorAll("[data-pending]").forEach((card) => {
    const p = mine[Number(card.dataset.pending)];
    const sync = () => card.querySelectorAll("tr[data-row]").forEach((tr) => {
      const r = p.rows[Number(tr.dataset.row)];
      tr.querySelectorAll("input").forEach((inp) => {
        r[inp.dataset.f] = inp.dataset.f === "amount" ? (inp.value === "" ? null : Number(inp.value)) : inp.value.trim() || null;
      });
    });
    card.querySelector("[data-zoom]").addEventListener("click", () =>
      openDialog(`<img src="/api/pages/${esc(p.file)}" alt="Register page"><p><button class="btn ghost" data-close>Close</button></p>`));
    card.querySelectorAll("[data-drop]").forEach((b) => b.addEventListener("click", () => {
      sync(); p.rows.splice(Number(b.dataset.drop), 1); renderPending(e);
    }));
    card.querySelector("[data-addrow]").addEventListener("click", () => {
      sync(); p.rows.push({ name: "", place: null, amount: null, gift: null, review: null }); renderPending(e);
    });
    card.querySelector("[data-discard]").addEventListener("click", () => {
      pending = pending.filter((x) => x !== p); renderPending(e);
    });
    card.querySelector("[data-save]").addEventListener("click", async (ev) => {
      sync();
      const rows = p.rows.filter((r) => r.name).map((r) => ({ name: r.name, place: r.place, amount: r.amount, gift: r.gift }));
      ev.target.disabled = true;
      try {
        await api(`/events/${e.id}/pages`, { method: "POST", body: JSON.stringify({
          file: p.file, written_total: p.written_total ?? null, latency_ms: p.latency_ms ?? null, rows }) });
        pending = pending.filter((x) => x !== p);
        eventView(e.id);
      } catch (err) { ev.target.disabled = false; toast(err.message); }
    });
  });
}

document.getElementById("top-search").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const q = new FormData(ev.target).get("q").trim();
  if (q) location.hash = `#/search/${encodeURIComponent(q)}`;
});

// --- router --------------------------------------------------------------------------------

function route() {
  const h = location.hash;
  let m;
  if ((m = h.match(/^#\/event\/(\d+)/))) return eventView(Number(m[1])).catch((err) => toast(err.message));
  if ((m = h.match(/^#\/search\/(.+)/))) return searchView(decodeURIComponent(m[1]));
  if ((m = h.match(/^#\/person\/(\d+)/))) return personView(Number(m[1])).catch((err) => toast(err.message));
  if ((m = h.match(/^#\/people(?:\/(.*))?/))) return peopleView(decodeURIComponent(m[1] || ""));
  return home();
}
window.addEventListener("hashchange", route);
route();
