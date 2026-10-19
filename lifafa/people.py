"""Contacts: one record per person or family, linking what they gave us with what we gave back.

Pure functions only (no database import), so the DB migration can use person_key too.
"""

import re
from difflib import SequenceMatcher

HONORIFICS = {"ji", "jee", "sahab", "saheb", "aunty", "auntie", "uncle", "family", "parivar", "mr", "mrs", "smt", "shri",
              "sh", "dr", "जी", "श्री", "श्रीमती", "परिवार", "आंटी", "आन्टी", "अंकल", "साहब", "साहेब", "श्रीमान"}


def tokens(s: str | None) -> list[str]:
    # Split on spaces and punctuation only: Devanagari vowel signs aren't "\w", so [^\w] would cut "मिश्रा" apart.
    return [t for t in re.split(r"[\s,.;:!?()\[\]{}\"'/+&-]+", (s or "").lower()) if t]


def core_name(name: str | None) -> str:
    words = tokens(name)
    core = [w for w in words if w not in HONORIFICS]
    return " ".join(core or words)


def person_key(name: str | None, place: str | None) -> tuple[str, str]:
    """'Sharma ji' + 'Kanpur' and 'Sharma Uncle' + 'kanpur' are the same person."""
    return core_name(name), " ".join(tokens(place))


# --- cross-script matching -------------------------------------------------------------------
# A voice entry in Hindi gives "शर्मा जी, कानपूर"; the register page said "Sharma ji, Kanpur".
# Romanise Devanagari, then compare consonant skeletons so spelling and script differences don't matter.

_CONS = {"क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
         "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
         "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
         "ष": "sh", "स": "s", "ह": "h", "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f", "ळ": "l"}
_VOWELS = {"अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऋ": "ri"}
_MATRAS = {"ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ृ": "ri"}
_NASAL = {"ं": "n", "ँ": "n", "ः": "h"}
_VIRAMA, _NUKTA = "्", "़"


def romanise(text: str) -> str:
    """Rough Devanagari → Latin, good enough to compare names (not for display)."""
    out, chars, i = [], list(text), 0
    while i < len(chars):
        ch = chars[i]
        if i + 1 < len(chars) and chars[i + 1] == _NUKTA and ch + _NUKTA in _CONS:
            ch, i = ch + _NUKTA, i + 1
        if ch in _CONS:
            out.append(_CONS[ch])
            nxt = chars[i + 1] if i + 1 < len(chars) else ""
            if nxt in _MATRAS:
                out.append(_MATRAS[nxt])
                i += 1
            elif nxt != _VIRAMA:
                out.append("a")  # inherent vowel; skeleton() drops vowels anyway
            else:
                i += 1
        elif ch in _VOWELS:
            out.append(_VOWELS[ch])
        elif ch in _NASAL:
            out.append(_NASAL[ch])
        elif ch not in (_VIRAMA, _NUKTA):
            out.append(ch)
        i += 1
    return "".join(out)


def skeleton(text: str | None) -> str:
    """Consonants only, with common spelling variants folded: शर्मा / Sharma / Sharmaa → 'shrm'."""
    t = romanise(core_name(text)).lower()
    t = re.sub(r"ow\b", "o", t)                      # Lucknow ~ लखनऊ
    t = t.replace("ck", "k").replace("ph", "f").replace("w", "v").replace("z", "j").replace("q", "k")
    t = re.sub(r"c(?!h)", "k", t)
    t = re.sub(r"([kgtdbj])h", r"\1", t)             # aspirates: kh/k, dh/d, bh/b are spelled both ways
    t = re.sub(r"(?<![sc])h", "", t)                 # Delhi ~ दिल्ली; keep sh/ch
    t = re.sub(r"[aeiouy\s]", "", t)                 # vowels and y (Jaipur ~ जयपुर, Bhatia ~ भाटिया)
    return re.sub(r"(.)\1+", r"\1", t)


def place_skeleton(place: str | None) -> str:
    return skeleton(" ".join(tokens(place)))


def find_contact(contacts: list[dict], name: str | None, place: str | None) -> dict | None:
    """Exact match first; otherwise a single cross-script match ("शर्मा जी, कानपूर" → "Sharma ji, Kanpur")."""
    key = person_key(name, place)
    exact = next((c for c in contacts if person_key(c["name"], c.get("place")) == key), None)
    if exact:
        return exact
    sk, psk = skeleton(name), place_skeleton(place)
    if len(sk) < 2:
        return None
    same = [c for c in contacts if skeleton(c["name"]) == sk and place_skeleton(c.get("place")) == psk]
    return same[0] if len(same) == 1 else None


def suggestions(contacts: list[dict], name: str, place: str | None = None, limit: int = 5) -> list[dict]:
    """Likely matches for a name, e.g. 'Sharma ji' → 'Ramesh Sharma (Kanpur)' from the phone's contacts."""
    want = {skeleton(w) for w in core_name(name).split()} - {""}
    if not want:
        return []
    scored = []
    for c in contacts:
        have = {skeleton(w) for w in core_name(c["name"]).split()} - {""}
        overlap = len(want & have) / max(len(want), 1)
        fuzzy = SequenceMatcher(None, skeleton(name), skeleton(c["name"])).ratio()
        score = max(overlap, fuzzy * 0.8)
        if place and c.get("place") and place_skeleton(place) == place_skeleton(c["place"]):
            score += 0.2
        if score >= 0.5:
            scored.append((score, c))
    return [c for _, c in sorted(scored, key=lambda x: -x[0])[:limit]]


def search(contacts: list[dict], query: str) -> list[dict]:
    words = [w for w in tokens(query) if w not in HONORIFICS] or tokens(query)
    digits = re.sub(r"\D", "", query)
    out = []
    for c in contacts:
        fields = f"{c['name']} {c.get('place') or ''} {c.get('relation') or ''}"
        hay = " ".join(tokens(fields))
        sk_hay = {skeleton(w) for w in tokens(fields)}
        # "sharma" finds "शर्मा जी" and "मिश्रा" finds "Mishra ji": compare words across scripts too
        hit = words and all(w in hay or (len(skeleton(w)) >= 2 and skeleton(w) in sk_hay) for w in words)
        if hit or (len(digits) >= 4 and digits in re.sub(r"\D", "", c.get("phone") or "")):
            out.append(c)
    return out


def clean_phone(raw: str | None) -> str | None:
    """Indian mobiles to 10 digits; other numbers kept with their country code."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if 10 <= len(digits) <= 15 else None


def parse_vcf(text: str) -> list[dict]:
    """Contacts exported from a phone or Google Contacts (.vcf). Only name, mobile and city are kept."""
    people = []
    for card in re.findall(r"BEGIN:VCARD(.*?)END:VCARD", text, flags=re.S | re.I):
        card = re.sub(r"\r?\n[ \t]", "", card)  # unfold continued lines
        fields: dict[str, list[str]] = {}
        for line in card.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            name = key.split(";")[0].split(".")[-1].upper()
            if "ENCODING=QUOTED-PRINTABLE" in key.upper():
                value = _quoted_printable(value)
            fields.setdefault(name, []).append(value.strip())
        full = (fields.get("FN") or [""])[0]
        if not full and fields.get("N"):
            parts = [p for p in fields["N"][0].split(";") if p]
            full = " ".join(reversed(parts[:2]))
        phone = next((clean_phone(t) for t in fields.get("TEL", []) if clean_phone(t)), None)
        city = None
        for adr in fields.get("ADR", []):
            parts = adr.split(";")
            if len(parts) > 3 and parts[3].strip():
                city = parts[3].strip()
                break
        full = full.replace("\\,", ",").strip()
        if full:
            people.append({"name": full[:80], "phone": phone, "place": city[:60] if city else None})
    return people


def _quoted_printable(v: str) -> str:
    import quopri

    try:
        return quopri.decodestring(v.encode()).decode("utf-8", "replace")
    except Exception:
        return v


def balance(received: list[dict], given: list[dict]) -> dict:
    """Both sides of lena-dena for one person, and a gentle hint for the next occasion."""
    got = sum(e.get("amount") or 0 for e in received)
    gave = sum(g.get("amount") or 0 for g in given)
    last_received = received[0] if received else None
    hint = None
    if last_received and last_received.get("amount"):
        hint = (f"They gave {_r(last_received['amount'])} at {last_received['event_name']}. "
                "Families usually return a similar amount, often with a small gift.")
    elif last_received and last_received.get("gift"):
        hint = f"They gave {last_received['gift']} at {last_received['event_name']}."
    return {"received_total": got, "given_total": gave, "difference": got - gave, "hint": hint}


def _r(n: int) -> str:
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = f"{head},{tail}"
    return f"₹{s}"
