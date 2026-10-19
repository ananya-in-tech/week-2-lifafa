"""Lifafa: a family's lena-dena ledger. Register photos and voice in, a searchable record of
who gave what at our functions and what we gave back at theirs. Everything runs on this computer."""

import asyncio
import logging
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from lifafa import ai, ledger, people, reader, voice
from lifafa.config import ROOT, check_privacy, get_settings
from lifafa.db import DB, now_iso

log = logging.getLogger("lifafa")
_db: DB | None = None


def db() -> DB:
    global _db
    if _db is None:
        _db = DB(get_settings().db_path)
    return _db


def set_db(new: DB) -> None:
    global _db
    _db = new


def page_dir():
    d = get_settings().data_dir / "pages"
    d.mkdir(parents=True, exist_ok=True)
    return d


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    check_privacy(s)
    db()
    if s.ai_enabled and s.ai_warmup:
        async def warm():
            try:
                await ai.chat([{"role": "user", "content": "ok"}], num_predict=1)
            except ai.AiUnavailable as e:
                log.warning("Warm-up skipped: %s", e)
            if s.voice_enabled:
                try:
                    await asyncio.to_thread(voice._whisper)
                except Exception as e:  # first run downloads the model; don't block startup on it
                    log.warning("Whisper warm-up skipped: %s", e)
        asyncio.create_task(warm())
    yield


app = FastAPI(title="Lifafa", version="0.2.0", lifespan=lifespan)

PHONE = r"^(\+?[0-9 ]{10,15})?$"


# --- models -----------------------------------------------------------------------------------

class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=80)
    event_date: date | None = None
    from_name: str | None = Field(None, max_length=60)


class EntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    place: str | None = Field(None, max_length=60)
    phone: str | None = Field(None, pattern=PHONE)
    amount: int | None = Field(None, ge=0, le=100_000_000)
    gift: str | None = Field(None, max_length=80)
    note: str | None = Field(None, max_length=200)
    contact_id: int | None = None
    source: Literal["manual", "voice"] = "manual"


class EntryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=80)
    place: str | None = Field(None, max_length=60)
    phone: str | None = Field(None, pattern=PHONE)
    amount: int | None = Field(None, ge=0, le=100_000_000)
    gift: str | None = Field(None, max_length=80)
    note: str | None = Field(None, max_length=200)
    contact_id: int | None = None
    reviewed: bool | None = None
    thanked: bool | None = None


class PageRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    place: str | None = Field(None, max_length=60)
    amount: int | None = Field(None, ge=0, le=100_000_000)
    gift: str | None = Field(None, max_length=80)


class PageConfirm(BaseModel):
    """The rows the family checked. Saved only now."""

    model_config = ConfigDict(extra="forbid")
    file: str = Field(pattern=r"^page_[a-f0-9]{16}\.jpg$")
    written_total: int | None = Field(None, ge=0)
    latency_ms: int | None = None
    rows: list[PageRow] = Field(max_length=80)


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    place: str | None = Field(None, max_length=60)
    phone: str | None = Field(None, pattern=PHONE)
    relation: str | None = Field(None, max_length=60)
    notes: str | None = Field(None, max_length=300)


class ContactPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=80)
    place: str | None = Field(None, max_length=60)
    phone: str | None = Field(None, pattern=PHONE)
    relation: str | None = Field(None, max_length=60)
    notes: str | None = Field(None, max_length=300)


class PickedContact(BaseModel):
    """From the phone's contact picker (Android Chrome)."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    phone: str | None = Field(None, max_length=30)


class GivenIn(BaseModel):
    """A gift WE gave at THEIR occasion. Either an existing contact, or a name to find or create."""

    model_config = ConfigDict(extra="forbid")
    contact_id: int | None = None
    name: str | None = Field(None, max_length=80)
    place: str | None = Field(None, max_length=60)
    occasion: str = Field(min_length=2, max_length=100)
    occasion_date: date | None = None
    amount: int | None = Field(None, ge=0, le=100_000_000)
    gift: str | None = Field(None, max_length=80)
    note: str | None = Field(None, max_length=200)
    source: Literal["manual", "voice"] = "manual"


class GivenPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    occasion: str | None = Field(None, min_length=2, max_length=100)
    occasion_date: date | None = None
    amount: int | None = Field(None, ge=0, le=100_000_000)
    gift: str | None = Field(None, max_length=80)
    note: str | None = Field(None, max_length=200)


class UnderstandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=2, max_length=400)
    language: str = "auto"
    event_id: int | None = None


# --- helpers ----------------------------------------------------------------------------------

def _event_or_404(eid: int) -> dict:
    e = db().event(eid)
    if not e:
        raise HTTPException(404, "Event not found")
    return e


def _contact_or_404(cid: int) -> dict:
    c = db().contact(cid)
    if not c:
        raise HTTPException(404, "Contact not found")
    return c


def _clean(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def link_contact(name: str, place: str | None, phone: str | None = None, contact_id: int | None = None) -> int:
    """Every ledger line belongs to a person. Reuse the matching contact, or create one."""
    if contact_id is not None:
        _contact_or_404(contact_id)
        return contact_id
    found = people.find_contact(db().contacts(), name, place)
    if found:
        if phone and not found.get("phone"):
            db().update_contact(found["id"], phone=people.clean_phone(phone))
        return found["id"]
    return db().add_contact(name, place, people.clean_phone(phone))


def _event_view(eid: int) -> dict:
    e = _event_or_404(eid)
    entries = db().entries(eid)
    contacts = {c["id"]: c for c in db().contacts()}
    for n in entries:
        c = contacts.get(n.get("contact_id"))
        n["contact"] = {"id": c["id"], "name": c["name"], "phone": c["phone"]} if c else None
        n["phone"] = n.get("phone") or (c["phone"] if c else None)
    pages = []
    for p in db().pages(eid):
        p["check"] = reader.total_check([{"amount": p["read_total"]}], p["written_total"]) if p["written_total"] is not None else None
        pages.append(p)
    return e | {
        "entries": entries,
        "pages": pages,
        "summary": {
            "guests": len(entries),
            "cash_total": sum(n["amount"] or 0 for n in entries),
            "gifts": sum(1 for n in entries if n["gift"]),
            "to_review": sum(1 for n in entries if n["review"]),
            "thanked": sum(1 for n in entries if n["thanked"]),
        },
    }


def _contact_view(cid: int) -> dict:
    c = _contact_or_404(cid)
    received = db().contact_entries(cid)
    given = db().given_for(cid)
    others = [x for x in db().contacts() if x["id"] != cid]
    return c | {"received": received, "given": given, "balance": people.balance(received, given),
                "possible_duplicates": people.suggestions(others, c["name"], c.get("place"), limit=3)}


# --- events -----------------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    s = get_settings()
    return {"status": "ok", "ai": await ai.health(),
            "voice": {"enabled": s.voice_enabled, "model": s.whisper_model, "languages": voice.LANGUAGES}}


@app.get("/api/events")
def list_events():
    return db().events()


@app.post("/api/events", status_code=201)
def create_event(body: EventIn):
    eid = db().add_event(body.name.strip(), body.event_date.isoformat() if body.event_date else None, _clean(body.from_name))
    return _event_view(eid)


@app.get("/api/events/{eid}")
def get_event(eid: int):
    return _event_view(eid)


@app.patch("/api/events/{eid}")
def edit_event(eid: int, body: EventIn):
    _event_or_404(eid)
    db().update_event(eid, name=body.name.strip(), event_date=body.event_date.isoformat() if body.event_date else None,
                      from_name=_clean(body.from_name))
    return _event_view(eid)


@app.delete("/api/events/{eid}", status_code=204)
def delete_event(eid: int):
    _event_or_404(eid)
    db().delete_event(eid)


# --- register pages ---------------------------------------------------------------------------

@app.post("/api/events/{eid}/read-page")
async def read_page(eid: int, photo: UploadFile = File(...)):
    """Read one register page. Returns rows for the family to check; nothing is added to the ledger yet."""
    _event_or_404(eid)
    try:
        jpeg = reader.clean_photo(await photo.read())
    except reader.BadPhoto as e:
        raise HTTPException(422, str(e)) from e
    name = f"page_{secrets.token_hex(8)}.jpg"
    (page_dir() / name).write_bytes(jpeg)
    t = time.perf_counter()
    try:
        raw, latency = await reader.read_page(jpeg)
    except ai.AiUnavailable:
        db().log_ai("read_page", int((time.perf_counter() - t) * 1000), False)
        return {"file": name, "ai": False, "rows": [], "check": None, "latency_ms": None,
                "message": "Gemma isn't available, so this page can't be read automatically. You can type the rows in."}
    db().log_ai("read_page", latency, True)
    rows = [reader.tidy_row(r) for r in raw.entries]
    reader.mark_duplicates(rows, db().entries(eid))
    return {"file": name, "ai": True, "rows": rows, "written_total": raw.page_total,
            "check": reader.total_check(rows, raw.page_total), "latency_ms": latency,
            "message": None if rows else "No rows found on this page. Is it the right photo?"}


@app.post("/api/events/{eid}/pages", status_code=201)
def confirm_page(eid: int, body: PageConfirm):
    _event_or_404(eid)
    if not (page_dir() / body.file).is_file():
        raise HTTPException(422, "That page photo is missing. Read the page again.")
    rows = []
    for r in body.rows:
        row = r.model_dump() | {"review": None}  # the family has checked these rows
        row["contact_id"] = link_contact(row["name"], row["place"])
        rows.append(row)
    page_id = db().add_page(eid, body.file, "read", body.written_total, body.latency_ms)
    db().add_entries(eid, page_id, rows, "ai")
    return _event_view(eid)


# --- entries (received) -----------------------------------------------------------------------

@app.post("/api/events/{eid}/entries", status_code=201)
def add_entry(eid: int, body: EntryIn):
    _event_or_404(eid)
    row = body.model_dump(exclude={"source"})
    row["contact_id"] = link_contact(row["name"], row["place"], row["phone"], row["contact_id"])
    db().add_entries(eid, None, [row], body.source)
    return _event_view(eid)


@app.patch("/api/entries/{nid}")
def edit_entry(nid: int, body: EntryPatch):
    entry = db().entry(nid)
    if not entry:
        raise HTTPException(404, "Entry not found")
    fields = body.model_dump(exclude_unset=True)
    if fields.pop("reviewed", None):
        fields["review"] = None
    if "thanked" in fields:
        fields["thanked_at"] = now_iso() if fields["thanked"] else None
        fields["thanked"] = int(fields["thanked"])
    if "contact_id" in fields and fields["contact_id"] is not None:
        _contact_or_404(fields["contact_id"])
    if fields.get("phone") == "":
        fields["phone"] = None
    if fields.get("phone") and entry.get("contact_id"):
        contact = db().contact(entry["contact_id"])
        if contact and not contact.get("phone"):
            db().update_contact(contact["id"], phone=people.clean_phone(fields["phone"]))
    db().update_entry(nid, **fields)
    return db().entry(nid)


@app.delete("/api/entries/{nid}", status_code=204)
def delete_entry(nid: int):
    if not db().entry(nid):
        raise HTTPException(404, "Entry not found")
    db().delete_entry(nid)


@app.get("/api/entries/{nid}/thanks")
def thanks(nid: int, lang: Literal["en", "hi"] = "en"):
    entry = db().entry(nid)
    if not entry:
        raise HTTPException(404, "Entry not found")
    contact = db().contact(entry["contact_id"]) if entry.get("contact_id") else None
    phone = entry.get("phone") or (contact or {}).get("phone")
    text = ledger.thank_you(entry, _event_or_404(entry["event_id"]), lang)
    return {"text": text, "whatsapp": ledger.whatsapp_link(phone, text), "thanked_at": entry.get("thanked_at")}


@app.get("/api/events/{eid}/export.csv")
def export_csv(eid: int):
    e = _event_or_404(eid)
    safe = "".join(c if c.isalnum() else "-" for c in e["name"]).strip("-") or "event"
    return Response(ledger.to_csv(db().entries(eid)), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe}-shagun.csv"'})


# --- contacts ---------------------------------------------------------------------------------

@app.get("/api/contacts")
def list_contacts(q: str | None = None):
    contacts = db().contacts()
    return people.search(contacts, q[:80]) if q else contacts


@app.post("/api/contacts", status_code=201)
def create_contact(body: ContactIn):
    cid = db().add_contact(body.name.strip(), _clean(body.place), people.clean_phone(body.phone),
                           _clean(body.relation), _clean(body.notes))
    return _contact_view(cid)


@app.get("/api/contacts/{cid}")
def get_contact(cid: int):
    return _contact_view(cid)


@app.patch("/api/contacts/{cid}")
def edit_contact(cid: int, body: ContactPatch):
    _contact_or_404(cid)
    fields = body.model_dump(exclude_unset=True)
    if "phone" in fields:
        fields["phone"] = people.clean_phone(fields["phone"])
    db().update_contact(cid, **{k: (_clean(v) if isinstance(v, str) else v) for k, v in fields.items()})
    return _contact_view(cid)


@app.post("/api/contacts/{cid}/merge-into/{into}")
def merge_contact(cid: int, into: int):
    if cid == into:
        raise HTTPException(422, "Can't merge a contact into itself.")
    _contact_or_404(cid), _contact_or_404(into)
    db().merge_contacts(cid, into)
    return _contact_view(into)


def _import(found: list[dict]) -> dict:
    existing = db().contacts()
    phones = {people.clean_phone(c["phone"]) for c in existing if c.get("phone")}
    added = updated = 0
    for p in found:
        phone = people.clean_phone(p.get("phone"))
        if phone and phone in phones:
            continue
        same = people.find_contact(existing, p["name"], p.get("place"))
        if same:
            if phone and not same.get("phone"):
                db().update_contact(same["id"], phone=phone)
                updated += 1
            continue
        db().add_contact(p["name"].strip()[:80], _clean(p.get("place")), phone)
        added += 1
        if phone:
            phones.add(phone)
    return {"found": len(found), "added": added, "updated": updated}


@app.post("/api/contacts/import-vcf")
async def import_vcf(file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(422, "That contacts file is too large (max 5 MB).")
    found = people.parse_vcf(raw.decode("utf-8", "replace"))
    if not found:
        raise HTTPException(422, "No contacts found. Export a .vcf file from your phone or Google Contacts.")
    return _import(found)


@app.post("/api/contacts/import-picked")
def import_picked(body: list[PickedContact]):
    if len(body) > 2000:
        raise HTTPException(422, "Too many contacts at once.")
    return _import([p.model_dump() for p in body])


# --- given (return gifts) ---------------------------------------------------------------------

@app.post("/api/given", status_code=201)
def add_given(body: GivenIn):
    if body.contact_id is None and not _clean(body.name):
        raise HTTPException(422, "Who did we give it to?")
    if body.amount is None and not _clean(body.gift):
        raise HTTPException(422, "Add an amount or a gift.")
    cid = link_contact(body.name or "", body.place, contact_id=body.contact_id)
    db().add_given(cid, body.occasion.strip(), body.occasion_date.isoformat() if body.occasion_date else None,
                   body.amount, _clean(body.gift), _clean(body.note), body.source)
    return _contact_view(cid)


@app.patch("/api/given/{gid}")
def edit_given(gid: int, body: GivenPatch):
    g = db().given_one(gid)
    if not g:
        raise HTTPException(404, "Not found")
    fields = body.model_dump(exclude_unset=True)
    if "occasion_date" in fields and fields["occasion_date"]:
        fields["occasion_date"] = fields["occasion_date"].isoformat()
    db().update_given(gid, **fields)
    return _contact_view(g["contact_id"])


@app.delete("/api/given/{gid}", status_code=204)
def delete_given(gid: int):
    if not db().given_one(gid):
        raise HTTPException(404, "Not found")
    db().delete_given(gid)


# --- voice ------------------------------------------------------------------------------------

async def _draft_from_text(text: str, language: str, event_id: int | None) -> dict:
    events = db().events()
    t = time.perf_counter()
    try:
        entry = await voice.understand(text, [e["name"] for e in events])
    except ai.AiUnavailable:
        db().log_ai("voice_understand", int((time.perf_counter() - t) * 1000), False)
        raise HTTPException(503, "Gemma isn't running, so I can't understand the sentence. Type the entry instead.")
    db().log_ai("voice_understand", int((time.perf_counter() - t) * 1000), True)
    eid, event_question = voice.match_event(entry.event_phrase, events, event_id)
    event_name = next((e["name"] for e in events if e["id"] == eid), None)
    contacts = db().contacts()
    match = people.find_contact(contacts, entry.name, entry.place) if entry.name else None
    return {
        "transcript": text,
        "language": language,
        "entry": entry.model_dump(),
        "event_id": eid if entry.direction == "received" else None,
        "event_name": event_name if entry.direction == "received" else None,
        "contact": match,
        "suggestions": [] if match or not entry.name else people.suggestions(contacts, entry.name, entry.place, 3),
        "missing": voice.check(entry, eid, event_question),
        "readback": voice.readback(entry, language, event_name),
    }


@app.post("/api/voice/entry")
async def voice_entry(audio: UploadFile = File(...), language: str = Form("auto"), event_id: int | None = Form(None)):
    """Speak one entry. Returns what was heard and a draft to confirm; nothing is saved here."""
    if language not in voice.LANGUAGES:
        raise HTTPException(422, "Unsupported language.")
    t = time.perf_counter()
    try:
        text, detected = await voice.transcribe(await audio.read(), language)
    except voice.VoiceUnavailable as e:
        raise HTTPException(503, str(e)) from e
    db().log_ai("voice_transcribe", int((time.perf_counter() - t) * 1000), bool(text))
    if not text:
        raise HTTPException(422, "I didn't hear anything. Try again a little closer to the mic.")
    return await _draft_from_text(text, detected, event_id)


@app.post("/api/voice/understand")
async def voice_understand(body: UnderstandIn):
    """Same as voice, from typed text (also handy when the mic isn't available)."""
    lang = body.language if body.language != "auto" else ("hi" if any("ऀ" <= ch <= "ॿ" for ch in body.text) else "en")
    return await _draft_from_text(body.text.strip(), lang, body.event_id)


@app.post("/api/voice/answer")
async def voice_answer(audio: UploadFile = File(...), language: str = Form("auto")):
    """Hands-free confirmation: 'haan' / 'yes' / 'nahi' / 'no' in any supported language."""
    try:
        text, _ = await voice.transcribe(await audio.read(), language)
    except voice.VoiceUnavailable as e:
        raise HTTPException(503, str(e)) from e
    return {"transcript": text, "answer": voice.yes_or_no(text)}


# --- search -----------------------------------------------------------------------------------

@app.get("/api/search")
def search(q: str):
    """Lena-dena for everyone matching: what they gave us, what we gave them."""
    out = []
    for c in people.search(db().contacts(), q[:80])[:20]:
        v = _contact_view(c["id"])
        out.append({k: v[k] for k in ("id", "name", "place", "phone", "relation", "received", "given", "balance")})
    return out


@app.get("/api/pages/{name}")
def page_image(name: str):
    path = (page_dir() / name).resolve()
    if path.parent != page_dir().resolve() or not path.is_file():
        raise HTTPException(404, "Page not found")
    return FileResponse(path, media_type="image/jpeg")


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
