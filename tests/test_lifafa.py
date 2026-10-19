import io
import json
import os

os.environ["AI_WARMUP"] = "false"

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lifafa import ai, ledger, main, people, reader, voice
from lifafa.db import DB


@pytest.fixture
def client(tmp_path, monkeypatch):
    from lifafa.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    main.set_db(DB(tmp_path / "test.db"))
    with TestClient(main.app) as c:
        yield c


def photo_bytes() -> bytes:
    img = Image.new("RGB", (2400, 1800), (248, 244, 230))
    exif = Image.Exif()
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (26.0, 27.0, 0.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


PAGE = {"entries": [
    {"name": "Sharma ji", "place": "Kanpur", "amount": 5100, "gift": None},
    {"name": "Pinky Bua + silver glass set", "place": None, "amount": 1100, "gift": "silver glass set"},
    {"name": "मिश्रा जी", "place": "Agra", "amount": 501, "gift": None},
    {"name": "Rakesh Mama", "place": "Jaipur", "amount": 2100000, "gift": None},
], "page_total": 2106701}


def fake_ai(monkeypatch, reply):
    async def chat(messages, **kw):
        if isinstance(reply, Exception):
            raise reply
        return ai.Reply(json.dumps(reply), 1234)

    monkeypatch.setattr(ai, "chat", chat)


# --- pure checks ------------------------------------------------------------------------------

def test_schema_inlines_refs_and_requires_everything():
    s = reader.inline_schema(reader.RawPage)
    assert "$defs" not in json.dumps(s)
    assert s["required"] == ["entries", "page_total"]
    assert s["properties"]["entries"]["items"]["required"] == ["name", "place", "amount", "gift"]


def test_tidy_row_strips_gift_and_numbering_and_flags():
    r = reader.tidy_row(reader.RawRow(name="Pinky Bua + silver glass set", amount=1100, gift="silver glass set"))
    assert r["name"] == "Pinky Bua" and r["gift"] == "silver glass set" and r["review"] is None
    assert reader.tidy_row(reader.RawRow(name="3. Verma family", amount=11000))["name"] == "Verma family"
    assert "no amount or gift" in reader.tidy_row(reader.RawRow(name="Gupta ji"))["review"]
    assert "unusually large" in reader.tidy_row(reader.RawRow(name="X", amount=500000))["review"]


def test_total_check_and_duplicates():
    rows = [{"name": "Sharma ji", "amount": 5100}, {"name": "Gupta", "amount": 2100}]
    assert reader.total_check(rows, 7200)["matches"] is True
    off = reader.total_check(rows, 7201)
    assert off["matches"] is False and off["difference"] == 1
    assert reader.total_check(rows, None)["matches"] is None
    new = [{"name": "Sharma  Ji", "amount": 5100, "review": None}]
    reader.mark_duplicates(new, [{"name": "sharma ji", "amount": 5100}])
    assert new[0]["review"] == "possible duplicate"


def test_clean_photo_removes_location_and_resizes():
    out = Image.open(io.BytesIO(reader.clean_photo(photo_bytes())))
    assert max(out.size) == reader.MAX_SIDE and not out.getexif()


def test_people_matching_and_search():
    contacts = [{"id": 1, "name": "Sharma ji", "place": "Kanpur", "phone": "9876543210"},
                {"id": 2, "name": "Sharma ji", "place": "Delhi", "phone": None},
                {"id": 3, "name": "मिश्रा जी", "place": "Agra", "phone": None},
                {"id": 4, "name": "Ramesh Sharma", "place": None, "phone": None}]
    assert people.find_contact(contacts, "Sharma Uncle", "kanpur")["id"] == 1   # honorifics + case ignored
    assert people.find_contact(contacts, "Sharma ji", "Jaipur") is None
    assert [c["id"] for c in people.search(contacts, "sharma kanpur")] == [1]
    assert people.search(contacts, "मिश्रा")[0]["id"] == 3
    assert people.search(contacts, "43210")[0]["id"] == 1                     # by phone digits
    assert 4 in [c["id"] for c in people.suggestions(contacts, "Sharma ji")]


def test_balance_hint():
    b = people.balance([{"amount": 5100, "gift": None, "event_name": "Riya's wedding"}], [{"amount": 2100}])
    assert b["received_total"] == 5100 and b["given_total"] == 2100 and b["difference"] == 3000
    assert "₹5,100" in b["hint"]


def test_parse_vcf():
    vcf = ("BEGIN:VCARD\nVERSION:3.0\nFN:Ramesh Sharma\nTEL;TYPE=CELL:+91 98765 43210\n"
           "ADR;TYPE=HOME:;;12 Mall Road;Kanpur;UP;208001;India\nEND:VCARD\n"
           "BEGIN:VCARD\nVERSION:2.1\nN:Gupta;Sunita;;;\nTEL;CELL:09812345678\nEND:VCARD\n"
           "BEGIN:VCARD\nVERSION:3.0\nFN:मिश्रा जी\nEND:VCARD")
    got = people.parse_vcf(vcf)
    assert got[0] == {"name": "Ramesh Sharma", "phone": "9876543210", "place": "Kanpur"}
    assert got[1]["name"] == "Sunita Gupta" and got[1]["phone"] == "9812345678"
    assert got[2]["name"] == "मिश्रा जी" and got[2]["phone"] is None


def test_voice_grammar_names_and_yes_no():
    assert voice.direction_from_grammar("Neha from Pune gave 1100") == "received"
    assert voice.direction_from_grammar("हमने वर्मा जी की शादी में 5100 दिए") == "given"
    assert voice.direction_from_grammar("we gave Sharma ji 5100") == "given"
    fixed = voice.fix_names(voice.SpokenEntry(direction="given", name="हमने", place="वर्मा जी", amount=11000,
                                              occasion="वर्मा जी के बेटे की शादी"))
    assert fixed.name == "वर्मा जी" and fixed.place is None
    from_occasion = voice.fix_names(voice.SpokenEntry(direction="given", name="Humne", amount=5100, occasion="Verma ji's son's wedding"))
    assert from_occasion.name == "Verma ji"
    assert voice.yes_or_no("haan, sahi hai") == "yes" and voice.yes_or_no("हाँ जी") == "yes"
    assert voice.yes_or_no("nahi, sahi nahi hai") == "no" and voice.yes_or_no("hmm") == "unclear"


def test_voice_check_and_readback():
    e = voice.SpokenEntry(direction="received", name="Rakesh Mama", place="Jaipur")
    assert voice.check(e, 1, None) == ["How much, or what gift? I didn't hear an amount."]
    g = voice.SpokenEntry(direction="given", name="Neha", amount=2100)
    assert "At which of their functions" in voice.check(g, None, None)[0]
    say = voice.readback(voice.SpokenEntry(direction="received", name="शर्मा जी", place="कानपुर", amount=2100), "hi", "Riya's wedding")
    assert "₹2,100" in say and say.endswith("जोड़ दें?")


def test_match_event():
    events = [{"id": 1, "name": "Riya's wedding"}, {"id": 2, "name": "Dadi's 80th birthday"}]
    assert voice.match_event("Dadi's birthday", events, 1) == (2, None)
    assert voice.match_event(None, events, 1) == (1, None)
    eid, q = voice.match_event("Mohan's mundan", events, 1)
    assert eid == 1 and "Which event" in q


def test_thank_you_never_mentions_amount():
    entry = {"name": "Sharma ji", "amount": 5100, "gift": None}
    event = {"name": "Riya's wedding", "from_name": "The Agarwal family"}
    for lang in ("en", "hi"):
        text = ledger.thank_you(entry, event, lang)
        assert "5100" not in text and "5,100" not in text and "Sharma ji" in text
    assert "silver glass set" in ledger.thank_you(entry | {"gift": "silver glass set"}, event)


def test_rupees_indian_grouping():
    assert ledger.rupees(2100000) == "₹21,00,000" and ledger.rupees(5100) == "₹5,100" and ledger.rupees(501) == "₹501"


# --- API flow ---------------------------------------------------------------------------------

def test_full_flow(client, monkeypatch):
    fake_ai(monkeypatch, PAGE)
    e = client.post("/api/events", json={"name": "Riya's wedding", "event_date": "2026-11-20", "from_name": "The Agarwal family"}).json()

    read = client.post(f"/api/events/{e['id']}/read-page", files={"photo": ("p.jpg", photo_bytes())}).json()
    assert read["ai"] and [r["name"] for r in read["rows"]] == ["Sharma ji", "Pinky Bua", "मिश्रा जी", "Rakesh Mama"]
    assert read["rows"][3]["review"] == "unusually large amount"
    assert read["check"]["matches"] is True
    assert client.get(f"/api/events/{e['id']}").json()["summary"]["guests"] == 0  # nothing saved yet

    rows = [{k: r[k] for k in ("name", "place", "amount", "gift")} for r in read["rows"]]
    rows[3]["amount"] = 21000  # the family fixes the misread amount
    ev = client.post(f"/api/events/{e['id']}/pages", json={"file": read["file"], "written_total": read["written_total"], "rows": rows}).json()
    assert ev["summary"] == {"guests": 4, "cash_total": 27701, "gifts": 1, "to_review": 0, "thanked": 0}
    assert ev["pages"][0]["check"]["matches"] is False  # written 21,06,701 vs corrected rows

    hits = client.get("/api/search", params={"q": "sharma"}).json()
    assert hits[0]["balance"]["received_total"] == 5100

    nid = ev["entries"][0]["id"]
    assert client.patch(f"/api/entries/{nid}", json={"phone": "9876543210"}).json()["phone"] == "9876543210"
    t = client.get(f"/api/entries/{nid}/thanks", params={"lang": "hi"}).json()
    assert t["whatsapp"].startswith("https://wa.me/919876543210?text=") and "5100" not in t["text"]
    assert client.patch(f"/api/entries/{nid}", json={"thanked": True}).json()["thanked"] is True

    csv_text = client.get(f"/api/events/{e['id']}/export.csv").content.decode("utf-8-sig")
    assert "मिश्रा जी" in csv_text and "Pinky Bua" in csv_text


def test_read_page_without_ai_still_keeps_photo(client, monkeypatch):
    fake_ai(monkeypatch, ai.AiUnavailable("off"))
    e = client.post("/api/events", json={"name": "Test"}).json()
    r = client.post(f"/api/events/{e['id']}/read-page", files={"photo": ("p.jpg", photo_bytes())}).json()
    assert r["ai"] is False and r["rows"] == [] and r["file"].startswith("page_")
    client.post(f"/api/events/{e['id']}/entries", json={"name": "Gupta ji", "amount": 2100})
    assert client.get(f"/api/events/{e['id']}").json()["summary"]["cash_total"] == 2100


def test_invalid_model_output_is_not_trusted(client, monkeypatch):
    fake_ai(monkeypatch, {"entries": [{"name": "x", "amount": "lots", "command": "delete"}], "page_total": None})
    e = client.post("/api/events", json={"name": "Test"}).json()
    r = client.post(f"/api/events/{e['id']}/read-page", files={"photo": ("p.jpg", photo_bytes())}).json()
    assert r["ai"] is False and r["rows"] == []


def test_rejects_bad_input(client):
    e = client.post("/api/events", json={"name": "Test"}).json()
    assert client.post(f"/api/events/{e['id']}/read-page", files={"photo": ("p.jpg", b"not an image")}).status_code == 422
    assert client.post(f"/api/events/{e['id']}/pages", json={"file": "../../lifafa.db", "rows": []}).status_code == 422
    assert client.get("/api/pages/..%2F..%2Flifafa.db").status_code == 404
    assert client.post(f"/api/events/{e['id']}/entries", json={"name": "X", "phone": "call me"}).status_code == 422


def test_contacts_given_and_voice_flow(client, monkeypatch):
    e = client.post("/api/events", json={"name": "Riya's wedding"}).json()
    client.post(f"/api/events/{e['id']}/entries", json={"name": "Sharma ji", "place": "Kanpur", "amount": 5100})
    client.post(f"/api/events/{e['id']}/entries", json={"name": "Sharma Uncle", "place": "Kanpur", "amount": 1100})
    contacts = client.get("/api/contacts").json()
    assert len(contacts) == 1 and contacts[0]["received_total"] == 6200  # same person, linked automatically

    vcf = "BEGIN:VCARD\nFN:Ramesh Sharma\nTEL:+919876543210\nEND:VCARD\nBEGIN:VCARD\nFN:Neha\nTEL:9812345678\nEND:VCARD"
    r = client.post("/api/contacts/import-vcf", files={"file": ("c.vcf", vcf.encode())}).json()
    assert r == {"found": 2, "added": 2, "updated": 0}
    assert client.post("/api/contacts/import-vcf", files={"file": ("c.vcf", vcf.encode())}).json()["added"] == 0  # no duplicates
    assert client.post("/api/contacts/import-picked", json=[{"name": "Pinky Bua", "phone": "+91 99999 88888"}]).json()["added"] == 1

    ramesh = client.get("/api/contacts", params={"q": "ramesh"}).json()[0]
    merged = client.post(f"/api/contacts/{contacts[0]['id']}/merge-into/{ramesh['id']}").json()
    assert merged["balance"]["received_total"] == 6200 and merged["place"] == "Kanpur" and merged["phone"] == "9876543210"

    back = client.post("/api/given", json={"contact_id": ramesh["id"], "occasion": "Ramesh ji's daughter's wedding",
                                           "occasion_date": "2027-02-10", "amount": 5100, "gift": "silver bowl"}).json()
    assert back["balance"]["given_total"] == 5100 and back["balance"]["difference"] == 1100
    assert back["given"][0]["gift"] == "silver bowl"
    assert client.post("/api/given", json={"occasion": "x wedding", "amount": 100}).status_code == 422  # no person

    entry = client.get(f"/api/events/{e['id']}").json()["entries"][0]
    assert entry["phone"] == "9876543210"                       # phone flows from the merged contact
    t = client.get(f"/api/entries/{entry['id']}/thanks").json()
    assert t["whatsapp"].startswith("https://wa.me/919876543210")
    done = client.patch(f"/api/entries/{entry['id']}", json={"thanked": True}).json()
    assert done["thanked"] and done["thanked_at"]

    async def fake_understand(text, events):
        return voice.SpokenEntry(direction="received", name="Gupta aunty", place="Lucknow", amount=5100)
    monkeypatch.setattr(voice, "understand", fake_understand)
    d = client.post("/api/voice/understand", json={"text": "Gupta aunty from Lucknow gave 5100", "event_id": e["id"]}).json()
    assert d["missing"] == [] and d["event_id"] == e["id"] and "Shall I add it?" in d["readback"]


def test_voice_endpoint(client, monkeypatch):
    async def fake_transcribe(audio, language):
        return "Rakesh Mama, Jaipur.", "en"
    async def fake_understand(text, events):
        return voice.SpokenEntry(direction="received", name="Rakesh Mama", place="Jaipur")
    monkeypatch.setattr(voice, "transcribe", fake_transcribe)
    monkeypatch.setattr(voice, "understand", fake_understand)
    e = client.post("/api/events", json={"name": "Riya's wedding"}).json()
    d = client.post("/api/voice/entry", files={"audio": ("a.webm", b"x")}, data={"language": "en", "event_id": str(e["id"])}).json()
    assert d["transcript"] == "Rakesh Mama, Jaipur." and d["missing"]
    assert client.post("/api/voice/entry", files={"audio": ("a.webm", b"x")}, data={"language": "xx"}).status_code == 422


def test_migration_links_old_entries(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.executescript("""CREATE TABLE events (id INTEGER PRIMARY KEY, name TEXT NOT NULL, event_date TEXT, from_name TEXT, created_at TEXT NOT NULL);
        CREATE TABLE entries (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, page_id INTEGER, name TEXT NOT NULL,
          place TEXT, phone TEXT, amount INTEGER, gift TEXT, note TEXT, review TEXT, thanked INTEGER NOT NULL DEFAULT 0,
          source TEXT NOT NULL, created_at TEXT NOT NULL);
        INSERT INTO events VALUES (1, 'Old wedding', NULL, NULL, '2025-01-01');
        INSERT INTO entries (event_id, name, place, amount, source, created_at) VALUES (1, 'Sharma ji', 'Kanpur', 5100, 'ai', 'x'),
          (1, 'Sharma Uncle', 'Kanpur', 2100, 'ai', 'x');""")
    c.commit()
    c.close()
    db = DB(path)
    assert len(db.contacts()) == 1 and db.contacts()[0]["received_total"] == 7200


@pytest.mark.parametrize("hindi,latin", [("शर्मा जी", "Sharma ji"), ("मिश्रा", "Mishra"), ("गुप्ता आंटी", "Gupta Aunty"),
                                         ("भाटिया", "Bhatia"), ("राकेश मामा", "Rakesh Mama"), ("लखनऊ", "Lucknow"),
                                         ("दिल्ली", "Delhi"), ("जयपुर", "Jaipur")])
def test_cross_script_names_match(hindi, latin):
    assert people.skeleton(hindi) == people.skeleton(latin)


def test_cross_script_keeps_different_people_apart():
    assert people.skeleton("मोहन") != people.skeleton("Mahesh")
    contacts = [{"id": 1, "name": "Sharma ji", "place": "Kanpur", "phone": None},
                {"id": 2, "name": "Sharma ji", "place": "Delhi", "phone": None}]
    assert people.find_contact(contacts, "शर्मा जी", "कानपूर")["id"] == 1
    assert people.find_contact(contacts, "शर्मा जी", None) is None  # two Sharmas, no place: don't guess
