// Voice entry: speak in English, Hindi or another Indian language → Whisper + Gemma on this computer →
// a draft that is read back aloud and confirmed (by tap, or by saying "haan" / "yes") before saving.

import { api, esc, rupees } from "./util.js";

let languages = { auto: "Auto-detect", en: "English", hi: "हिन्दी (Hindi)" };
const health = api("/health").then((h) => { if (h.voice?.languages) languages = h.voice.languages; return h; }).catch(() => null);

const LANG_KEY = "lifafa:lang";
const savedLang = () => { try { return localStorage.getItem(LANG_KEY) || "auto"; } catch { return "auto"; } };

/**
 * Render a voice panel into `host`.
 * opts: { mode: "received" | "given", eventId?, contact?, events: [{id,name}], onSaved() }
 */
export async function voicePanel(host, opts) {
  const h = await health;
  if (h && !h.voice?.enabled) {
    // Demo servers (e.g. Render's free tier) don't have the memory for Whisper + Gemma.
    host.innerHTML = `<p class="banner warn">Voice entry runs on your own computer (Whisper + Gemma need about 8 GB of memory),
      so it's turned off on this demo server. Run Lifafa locally to speak entries in English, Hindi and other Indian languages.</p>`;
    return;
  }
  const canRecord = !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
  host.innerHTML = `
    <div class="voice">
      <div class="row">
        <button class="btn mic" data-rec ${canRecord ? "" : "disabled"} aria-pressed="false">🎤 <span>Speak an entry</span></button>
        <select data-lang aria-label="Language" style="max-width:190px">
          ${Object.entries(languages).map(([k, v]) => `<option value="${k}" ${k === savedLang() ? "selected" : ""}>${esc(v)}</option>`).join("")}
        </select>
        <label class="row muted" style="gap:6px"><input type="checkbox" data-handsfree style="width:auto"> Hands-free confirm</label>
      </div>
      <p class="muted" data-hint>${opts.mode === "given"
        ? "e.g. “Humne Verma ji ke bete ki shaadi mein 11,000 aur ek ghadi di”"
        : "e.g. “Sharma ji Kanpur se 2100 aur chaandi ka sikka” · “Gupta aunty from Lucknow gave 5100”"}
        ${canRecord ? "" : " · The mic isn't available here: upload a voice note or type instead."}</p>
      <div class="row">
        <input data-text placeholder="…or type it the way you'd say it" maxlength="400" style="flex:1;min-width:220px">
        <button class="btn ghost small" data-go>Understand</button>
        <label class="btn ghost small">Voice note<input type="file" accept="audio/*,.opus,.ogg,.m4a,.mp3,.wav" data-file hidden></label>
      </div>
      <div data-out></div>
    </div>`;

  const $ = (s) => host.querySelector(s);
  const out = $("[data-out]");
  const lang = () => $("[data-lang]").value;
  $("[data-lang]").addEventListener("change", () => { try { localStorage.setItem(LANG_KEY, lang()); } catch {} });

  let rec = null;
  $("[data-rec]").addEventListener("click", async () => {
    if (rec) { rec.stop(); return; }
    try {
      rec = await record(30000, (secs) => { $("[data-rec] span").textContent = `Listening… ${secs}s · tap to stop`; });
      $("[data-rec]").setAttribute("aria-pressed", "true");
      const blob = await rec.done;
      rec = null;
      $("[data-rec]").setAttribute("aria-pressed", "false");
      $("[data-rec] span").textContent = "Speak an entry";
      await send(blob, "speech.webm");
    } catch (err) {
      rec = null;
      $("[data-rec] span").textContent = "Speak an entry";
      out.innerHTML = `<p class="banner warn">${esc(err.message || "Couldn't use the microphone.")}</p>`;
    }
  });
  $("[data-file]").addEventListener("change", (ev) => { const f = ev.target.files?.[0]; if (f) send(f, f.name); ev.target.value = ""; });
  $("[data-go]").addEventListener("click", () => understandText());
  $("[data-text]").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); understandText(); } });

  async function understandText() {
    const text = $("[data-text]").value.trim();
    if (text.length < 2) return;
    out.innerHTML = `<p class="loading">Understanding…</p>`;
    try {
      const d = await api("/voice/understand", { method: "POST", body: JSON.stringify({ text, language: lang(), event_id: opts.eventId ?? null }) });
      showDraft(d);
    } catch (err) { out.innerHTML = `<p class="banner warn">${esc(err.message)}</p>`; }
  }

  async function send(blob, name) {
    out.innerHTML = `<p class="loading">Listening back to what you said… (Whisper on this computer, about 10 seconds)</p>`;
    const form = new FormData();
    form.append("audio", blob, name);
    form.append("language", lang());
    if (opts.eventId) form.append("event_id", String(opts.eventId));
    try {
      showDraft(await api("/voice/entry", { method: "POST", body: form }));
    } catch (err) { out.innerHTML = `<p class="banner warn">${esc(err.message)}</p>`; }
  }

  function showDraft(d) {
    const e = d.entry;
    if (opts.mode === "given" && opts.contact && !e.name) e.name = opts.contact.name;
    const direction = e.direction;
    const linked = d.contact || (opts.mode === "given" ? opts.contact : null);
    out.innerHTML = `
      <div class="confirm">
        <p class="muted">Heard: “${esc(d.transcript)}”</p>
        <div class="row" role="radiogroup" aria-label="Direction">
          <label class="chip ${direction === "received" ? "plain" : ""}"><input type="radio" name="dir" value="received" ${direction === "received" ? "checked" : ""} hidden>They gave us</label>
          <label class="chip ${direction === "given" ? "plain" : ""}"><input type="radio" name="dir" value="given" ${direction === "given" ? "checked" : ""} hidden>We gave them</label>
        </div>
        <div class="grid2" style="margin-top:10px">
          <label>Name<input data-f="name" value="${esc(e.name || "")}" maxlength="80"></label>
          <label>Place / relation<input data-f="place" value="${esc(e.place || "")}" maxlength="60"></label>
          <label>Amount (₹)<input data-f="amount" type="number" min="0" value="${e.amount ?? ""}"></label>
          <label>Gift<input data-f="gift" value="${esc(e.gift || "")}" maxlength="80"></label>
          <label data-recv>Our event
            <select data-f="event_id">${opts.events.map((ev) => `<option value="${ev.id}" ${ev.id === d.event_id ? "selected" : ""}>${esc(ev.name)}</option>`).join("")}</select>
          </label>
          <label data-give>Their occasion<input data-f="occasion" value="${esc(e.occasion || "")}" maxlength="100" placeholder="Verma ji's son's wedding"></label>
          <label data-give>Date<input data-f="occasion_date" type="date"></label>
        </div>
        <p class="muted" data-person>${linked ? `Linked to <b>${esc(linked.name)}</b>${linked.place ? ` (${esc(linked.place)})` : ""}${linked.phone ? ` · ${esc(linked.phone)}` : ""}`
          : `New person${d.suggestions?.length ? ` · or link to: ${d.suggestions.map((s) => `<button class="linkish" data-link="${s.id}">${esc(s.name)}${s.place ? ` (${esc(s.place)})` : ""}</button>`).join(", ")}` : ""}`}</p>
        <div data-missing>${d.missing.map((m) => `<p class="banner warn">${esc(m)}</p>`).join("")}</div>
        <p class="readback">🔊 ${esc(d.readback)}</p>
        <div class="row" style="justify-content:flex-end">
          <button class="btn ghost" data-cancel>Cancel</button>
          <button class="btn ghost" data-again>Say again</button>
          <button class="btn" data-save>${direction === "given" ? "Yes, save return gift" : "Yes, add entry"}</button>
        </div>
      </div>`;

    let contactId = linked?.id ?? null;
    const box = out.querySelector(".confirm");
    const q = (s) => box.querySelector(s);
    const dir = () => box.querySelector('input[name="dir"]:checked').value;
    const syncDir = () => {
      box.querySelectorAll("[data-recv]").forEach((x) => { x.hidden = dir() !== "received"; });
      box.querySelectorAll("[data-give]").forEach((x) => { x.hidden = dir() !== "given"; });
      box.querySelectorAll('[role="radiogroup"] label').forEach((l) => l.classList.toggle("plain", l.querySelector("input").checked));
      q("[data-save]").textContent = dir() === "given" ? "Yes, save return gift" : "Yes, add entry";
    };
    box.querySelectorAll('input[name="dir"]').forEach((r) => r.addEventListener("change", syncDir));
    box.querySelectorAll('[role="radiogroup"] label').forEach((l) => l.addEventListener("click", () => { l.querySelector("input").checked = true; syncDir(); }));
    syncDir();
    box.querySelectorAll("[data-link]").forEach((b) => b.addEventListener("click", () => {
      contactId = Number(b.dataset.link);
      q("[data-person]").innerHTML = `Linked to <b>${esc(b.textContent)}</b>`;
    }));
    q("[data-cancel]").addEventListener("click", () => { stopSpeaking(); out.innerHTML = ""; });
    q("[data-again]").addEventListener("click", () => { stopSpeaking(); out.innerHTML = ""; host.querySelector("[data-rec]").click(); });
    q("[data-save]").addEventListener("click", save);

    async function save() {
      stopSpeaking();
      const v = (k) => box.querySelector(`[data-f="${k}"]`).value.trim();
      const amount = v("amount") === "" ? null : Number(v("amount"));
      const problems = [];
      if (!v("name") && !contactId) problems.push("Who was it? Add a name.");
      if (amount === null && !v("gift")) problems.push("Add an amount or a gift.");
      if (dir() === "given" && !v("occasion")) problems.push("At which of their functions?");
      if (problems.length) { q("[data-missing]").innerHTML = problems.map((m) => `<p class="banner warn">${esc(m)}</p>`).join(""); return; }
      q("[data-save]").disabled = true;
      try {
        if (dir() === "received") {
          await api(`/events/${v("event_id")}/entries`, { method: "POST", body: JSON.stringify({
            name: v("name") || linked?.name, place: v("place") || null, amount, gift: v("gift") || null,
            contact_id: contactId, source: "voice" }) });
        } else {
          await api("/given", { method: "POST", body: JSON.stringify({
            contact_id: contactId, name: v("name") || null, place: v("place") || null, occasion: v("occasion"),
            occasion_date: v("occasion_date") || null, amount, gift: v("gift") || null, source: "voice" }) });
        }
        out.innerHTML = `<p class="banner ok">✓ Saved: ${esc(v("name") || linked?.name)} · ${esc([rupees(amount), v("gift")].filter(Boolean).join(" + "))}</p>`;
        opts.onSaved?.();
      } catch (err) {
        q("[data-save]").disabled = false;
        q("[data-missing]").innerHTML = `<p class="banner warn">${esc(err.message)}</p>`;
      }
    }

    speak(d.readback, d.language).then(async () => {
      if (!host.querySelector("[data-handsfree]").checked || d.missing.length || !box.isConnected) return;
      q(".readback").textContent = "🎤 Say “haan” / “yes” to save, or “nahi” / “no”…";
      try {
        const r = await record(3500);
        const form = new FormData();
        form.append("audio", await r.done, "answer.webm");
        form.append("language", d.language || lang());
        const a = await api("/voice/answer", { method: "POST", body: form });
        if (!box.isConnected) return;
        if (a.answer === "yes") save();
        else if (a.answer === "no") { out.innerHTML = `<p class="banner warn">Cancelled (“${esc(a.transcript)}”).</p>`; }
        else q(".readback").textContent = `Didn't catch that (“${a.transcript}”). Tap a button.`;
      } catch { q(".readback").textContent = "Tap a button to confirm."; }
    });
  }
}

// --- microphone & speech ------------------------------------------------------------------------

async function record(maxMs, onTick) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((t) => MediaRecorder.isTypeSupported?.(t)) || "";
  const mr = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
  const chunks = [];
  mr.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  const started = Date.now();
  const tick = onTick ? setInterval(() => onTick(Math.round((Date.now() - started) / 1000)), 500) : null;
  const done = new Promise((resolve) => {
    mr.onstop = () => {
      clearInterval(tick);
      stream.getTracks().forEach((t) => t.stop());
      resolve(new Blob(chunks, { type: mr.mimeType || "audio/webm" }));
    };
  });
  mr.start();
  const timer = setTimeout(() => mr.state !== "inactive" && mr.stop(), maxMs);
  return { stop: () => { clearTimeout(timer); if (mr.state !== "inactive") mr.stop(); }, done };
}

const VOICE_LANG = { hi: "hi-IN", en: "en-IN", bn: "bn-IN", mr: "mr-IN", ta: "ta-IN", te: "te-IN", gu: "gu-IN", kn: "kn-IN", ml: "ml-IN", pa: "pa-IN", ur: "ur-IN" };

function speak(text, language) {
  // The browser's own voices (installed on this device) read the entry back before saving.
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve();
    const u = new SpeechSynthesisUtterance(text);
    const want = VOICE_LANG[language] || "en-IN";
    // Only on-device voices: browsers also offer cloud voices, which would send the entry off this computer.
    const local = speechSynthesis.getVoices().filter((v) => v.localService);
    const voice = local.find((v) => v.lang === want) || local.find((v) => v.lang.startsWith(want.slice(0, 2)));
    if (!voice && local.length === 0) return resolve();
    if (voice) u.voice = voice;
    u.lang = voice?.lang || want;
    u.onend = u.onerror = () => resolve();
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
    setTimeout(resolve, 15000);
  });
}

function stopSpeaking() { try { speechSynthesis.cancel(); } catch {} }
