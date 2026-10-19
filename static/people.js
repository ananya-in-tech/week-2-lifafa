// People: one page per person or family, with both sides of lena-dena:
// what they gave at our functions, and what we gave back at theirs.

import { alertIn, api, app, dialog, esc, openDialog, prettyDate, rupees, toast } from "./util.js";
import { voicePanel } from "./voice.js";

export async function peopleView(q = "") {
  const list = await api(`/contacts${q ? `?q=${encodeURIComponent(q)}` : ""}`);
  const picker = "contacts" in navigator && "ContactsManager" in window;
  app.innerHTML = `
    <p class="muted"><a href="#/">← Events</a></p>
    <div class="row" style="justify-content:space-between"><h1>People</h1></div>
    <p class="lede">Everyone in your ledger. Import your phone contacts so thank-you notes open straight in WhatsApp.</p>
    <div class="card">
      <div class="row">
        <label class="btn ghost">Import contacts (.vcf)<input type="file" id="vcf" accept=".vcf,text/vcard,text/x-vcard" hidden></label>
        ${picker ? `<button class="btn ghost" id="pick">Pick from phone</button>` : ""}
        <span class="muted">Export a .vcf from your phone's Contacts app or contacts.google.com. Only names, numbers and city are kept, on this computer.</span>
      </div>
      <form id="add-person" class="row" style="margin-top:12px">
        <input name="name" required maxlength="80" placeholder="Name" style="flex:2;min-width:160px">
        <input name="place" maxlength="60" placeholder="Place" style="flex:1;min-width:110px">
        <input name="phone" inputmode="tel" placeholder="Phone" style="flex:1;min-width:130px">
        <button class="btn ghost">Add person</button>
      </form>
    </div>
    <input id="people-filter" type="search" placeholder="Filter people" value="${esc(q)}">
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>Name</th><th>Phone</th><th class="amt">They gave</th><th class="amt">We gave</th><th></th></tr></thead>
      <tbody>${list.map((c) => `
        <tr>
          <td><a href="#/person/${c.id}"><b>${esc(c.name)}</b></a> <span class="muted">${esc(c.place || "")}</span></td>
          <td>${esc(c.phone || "")}</td>
          <td class="amt">${c.received_count ? rupees(c.received_total) : ""}</td>
          <td class="amt">${c.given_count ? rupees(c.given_total) : ""}</td>
          <td>${c.unthanked ? `<span class="chip warn">${c.unthanked} to thank</span>` : ""}</td>
        </tr>`).join("")}</tbody>
    </table></div>${list.length ? "" : `<p class="muted">Nobody yet.</p>`}</div>`;

  document.getElementById("vcf").addEventListener("change", async (ev) => {
    const f = ev.target.files?.[0];
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    try {
      const r = await api("/contacts/import-vcf", { method: "POST", body: form });
      await peopleView(q);
      toast(`Found ${r.found} contacts: ${r.added} added, ${r.updated} updated with a phone number.`, "ok");
    } catch (err) { toast(err.message); }
  });
  document.getElementById("pick")?.addEventListener("click", async () => {
    try {
      const picked = await navigator.contacts.select(["name", "tel"], { multiple: true });
      const rows = picked.filter((p) => p.name?.[0]).map((p) => ({ name: p.name[0].slice(0, 80), phone: p.tel?.[0] || null }));
      const r = await api("/contacts/import-picked", { method: "POST", body: JSON.stringify(rows) });
      await peopleView(q);
      toast(`${r.added} added, ${r.updated} updated.`, "ok");
    } catch (err) { if (err.name !== "AbortError") toast(err.message); }
  });
  document.getElementById("add-person").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    try {
      const c = await api("/contacts", { method: "POST", body: JSON.stringify({
        name: f.get("name"), place: f.get("place") || null, phone: f.get("phone") || null }) });
      location.hash = `#/person/${c.id}`;
    } catch (err) { toast(err.message); }
  });
  let t;
  document.getElementById("people-filter").addEventListener("input", (ev) => {
    clearTimeout(t);
    t = setTimeout(() => { location.hash = `#/people/${encodeURIComponent(ev.target.value.trim())}`; }, 350);
  });
}

export async function personView(id) {
  const [c, events] = await Promise.all([api(`/contacts/${id}`), api("/events")]);
  const b = c.balance;
  app.innerHTML = `
    <p class="muted"><a href="#/people">← People</a></p>
    <div class="row" style="justify-content:space-between">
      <h1>${esc(c.name)}</h1>
      <button class="btn ghost small" id="edit">Edit details</button>
    </div>
    <p class="muted">${[c.place, c.relation, c.phone].filter(Boolean).map(esc).join(" · ") || "No details yet"}</p>
    <div class="stats">
      <div class="stat"><span class="muted">They gave us</span><b>${rupees(b.received_total)}</b></div>
      <div class="stat"><span class="muted">We gave them</span><b>${rupees(b.given_total)}</b></div>
      <div class="stat"><span class="muted">${b.difference >= 0 ? "We've returned less by" : "We've given more by"}</span><b>${rupees(Math.abs(b.difference))}</b></div>
    </div>
    ${b.hint ? `<p class="banner ok">${esc(b.hint)}</p>` : ""}

    <div class="card">
      <h2>They gave at our functions</h2>
      ${c.received.length ? `<ul class="history">${c.received.map((n) => `
        <li><a href="#/event/${n.event_id}">${esc(n.event_name)}${n.event_date ? ` · ${prettyDate(n.event_date)}` : ""}</a>
          <span>${rupees(n.amount)}${n.gift ? `${n.amount ? " + " : ""}${esc(n.gift)}` : ""}
            ${n.thanked ? `<span class="chip ok">thanked${n.thanked_at ? ` ${prettyDate(n.thanked_at)}` : ""}</span>` : `<span class="chip warn">not thanked</span>`}</span></li>`).join("")}</ul>`
      : `<p class="muted">Nothing recorded yet.</p>`}
    </div>

    <div class="card">
      <h2>We gave at their functions</h2>
      ${c.given.length ? `<ul class="history">${c.given.map((g) => `
        <li><span>${esc(g.occasion)}${g.occasion_date ? ` · ${prettyDate(g.occasion_date)}` : ""}</span>
          <span>${rupees(g.amount)}${g.gift ? `${g.amount ? " + " : ""}${esc(g.gift)}` : ""}
            <button class="linkish" data-del-given="${g.id}" aria-label="Delete">✕</button></span></li>`).join("")}</ul>`
      : `<p class="muted">No return gifts recorded yet.</p>`}
      <h3 style="margin-top:16px">Add a return gift</h3>
      <form id="given" class="grid2">
        <input name="occasion" required maxlength="100" placeholder="Their occasion, e.g. ${esc(c.name)}'s daughter's wedding">
        <input name="occasion_date" type="date" aria-label="Date">
        <input name="amount" type="number" min="0" placeholder="₹ Amount">
        <input name="gift" maxlength="80" placeholder="Gift (e.g. silver bowl)">
        <button class="btn">Save return gift</button>
      </form>
      <div id="voice-given" style="margin-top:12px"></div>
    </div>

    ${c.possible_duplicates.length ? `<div class="card"><h2>Same person?</h2>
      <p class="muted">These look similar. Merging moves everything into ${esc(c.name)}.</p>
      ${c.possible_duplicates.map((d) => `<p><a href="#/person/${d.id}">${esc(d.name)}</a> <span class="muted">${esc(d.place || "")} ${esc(d.phone || "")}</span>
        <button class="btn ghost small" data-merge="${d.id}">Merge into ${esc(c.name)}</button></p>`).join("")}</div>` : ""}`;

  document.getElementById("given").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    try {
      await api("/given", { method: "POST", body: JSON.stringify({
        contact_id: c.id, occasion: f.get("occasion"), occasion_date: f.get("occasion_date") || null,
        amount: f.get("amount") ? Number(f.get("amount")) : null, gift: f.get("gift") || null }) });
      personView(id);
    } catch (err) { toast(err.message); }
  });
  app.querySelectorAll("[data-del-given]").forEach((btn) => btn.addEventListener("click", async () => {
    if (btn.dataset.sure !== "1") { btn.dataset.sure = "1"; btn.textContent = "delete?"; return; }
    await api(`/given/${btn.dataset.delGiven}`, { method: "DELETE" });
    personView(id);
  }));
  app.querySelectorAll("[data-merge]").forEach((btn) => btn.addEventListener("click", async () => {
    if (btn.dataset.sure !== "1") { btn.dataset.sure = "1"; btn.textContent = "Tap again to merge"; return; }
    await api(`/contacts/${btn.dataset.merge}/merge-into/${c.id}`, { method: "POST" });
    personView(id);
  }));
  document.getElementById("edit").addEventListener("click", () => editContact(c, () => personView(id)));
  voicePanel(document.getElementById("voice-given"), { mode: "given", contact: c, events, onSaved: () => personView(id) });
}

function editContact(c, done) {
  openDialog(`
    <h2>Edit ${esc(c.name)}</h2>
    <form id="ce" class="grid2">
      <label>Name<input name="name" required maxlength="80" value="${esc(c.name)}"></label>
      <label>Place<input name="place" maxlength="60" value="${esc(c.place || "")}"></label>
      <label>WhatsApp number<input name="phone" inputmode="tel" value="${esc(c.phone || "")}"></label>
      <label>Relation<input name="relation" maxlength="60" placeholder="Mama ji, neighbour…" value="${esc(c.relation || "")}"></label>
      <label style="grid-column:1/-1">Notes<input name="notes" maxlength="300" value="${esc(c.notes || "")}"></label>
    </form>
    <div class="row" style="justify-content:flex-end;margin-top:14px">
      <button class="btn ghost" data-close>Cancel</button><button class="btn" id="cs">Save</button>
    </div>`);
  document.getElementById("cs").addEventListener("click", async () => {
    const f = new FormData(document.getElementById("ce"));
    try {
      await api(`/contacts/${c.id}`, { method: "PATCH", body: JSON.stringify(Object.fromEntries([...f.entries()].map(([k, v]) => [k, v || null]))) });
      dialog.close();
      done();
    } catch (err) { alertIn(err.message); }
  });
}

export async function searchView(q) {
  const found = q ? await api(`/search?q=${encodeURIComponent(q)}`) : [];
  document.querySelector("#top-search input").value = q;
  app.innerHTML = `
    <p class="muted"><a href="#/">← Events</a></p>
    <h1>Lena-dena: “${esc(q)}”</h1>
    <p class="lede">What they gave at your functions, and what you gave at theirs. Handy before the next invitation.</p>
    ${found.length ? `<div class="card">${found.map((p) => `
      <div class="person">
        <div class="row" style="justify-content:space-between">
          <div><a href="#/person/${p.id}"><b style="font-size:1.1rem">${esc(p.name)}</b></a> <span class="muted">${esc(p.place || "")}</span></div>
          <span><span class="chip plain">gave ${rupees(p.balance.received_total)}</span> <span class="chip ok">we gave ${rupees(p.balance.given_total)}</span></span>
        </div>
        <ul class="history">
          ${p.received.map((h) => `<li><a href="#/event/${h.event_id}">← ${esc(h.event_name)}${h.event_date ? ` · ${prettyDate(h.event_date)}` : ""}</a>
            <span>${rupees(h.amount)}${h.gift ? `${h.amount ? " + " : ""}${esc(h.gift)}` : ""}</span></li>`).join("")}
          ${p.given.map((g) => `<li><span>→ ${esc(g.occasion)}${g.occasion_date ? ` · ${prettyDate(g.occasion_date)}` : ""}</span>
            <span>${rupees(g.amount)}${g.gift ? `${g.amount ? " + " : ""}${esc(g.gift)}` : ""}</span></li>`).join("")}
        </ul>
        ${p.balance.hint ? `<p class="muted">${esc(p.balance.hint)}</p>` : ""}
      </div>`).join("")}</div>` : `<p class="lede">Nobody matching “${esc(q)}” yet. Try a surname, a town or a phone number.</p>`}`;
}
