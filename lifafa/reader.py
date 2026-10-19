"""Register page photo → rows. Gemma reads the handwriting; code checks every number.

Photos are re-encoded first (no EXIF), and nothing is saved until the family reviews the rows.
"""

import base64
import io
import re

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lifafa import ai

MAX_SIDE = 1600  # handwriting needs more pixels than a photo check
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
BIG_AMOUNT = 200_000


class RawRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=80)
    place: str | None = Field(None, max_length=60)
    amount: int | None = Field(None, ge=0, le=100_000_000)
    gift: str | None = Field(None, max_length=80)


class RawPage(BaseModel):
    """Exactly what the model may return."""

    model_config = ConfigDict(extra="forbid")
    entries: list[RawRow] = Field(default_factory=list, max_length=60)
    page_total: int | None = Field(None, ge=0, le=1_000_000_000)


class BadPhoto(Exception):
    pass


PROMPT = """This is a photo of a page from a handwritten shagun register: the list a family keeps of who gave which gift at a wedding or function.

Read every guest row, top to bottom. For each row return:
- name: the guest's name exactly as written. Keep Hindi/Devanagari script as written; do not translate or transliterate. Do not include the gift or the amount in the name.
- place: the town or relation written next to it (e.g. "Kanpur", "Mama ji's side"), or null.
- amount: the cash amount as a whole number of rupees. "5100/-", "Rs 5,100" and "₹5100" are all 5100. Null if no cash amount is written.
- gift: a non-cash gift written on that row (e.g. "silver glass set"), or null.
Also return page_total if a total is written on the page, else null.

Only include rows that are actually on the page. Never invent names or amounts. Skip headings and crossed-out rows."""


def inline_schema(model: type[BaseModel]) -> dict:
    """Shape the Pydantic schema for Ollama's constrained decoding: inline "$ref"s, and make every field
    required (nullable ones can still be null). Optional fields let the model skip them, and it will:
    left optional, `entries` came back missing on a page with six clear rows."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            out = {k: walk(v) for k, v in node.items()}
            if "properties" in out:
                out["required"] = list(out["properties"])
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)



def clean_photo(raw: bytes) -> bytes:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BadPhoto("That photo is too large (max 20 MB).")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise BadPhoto("That file isn't a photo Lifafa can read.") from e
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    clean = Image.new("RGB", img.size)
    clean.paste(img)  # fresh image: no EXIF, no location
    out = io.BytesIO()
    clean.save(out, "JPEG", quality=88)
    return out.getvalue()


async def read_page(jpeg: bytes) -> tuple[RawPage, int]:
    messages = [{"role": "user", "content": PROMPT, "images": [base64.b64encode(jpeg).decode()]}]
    reply = await ai.chat(messages, schema=inline_schema(RawPage), num_predict=1500)
    try:
        return RawPage.model_validate_json(reply.content), reply.latency_ms
    except ValidationError as e:
        raise ai.AiUnavailable("The model's answer didn't validate.") from e


# --- checks (pure functions, unit-tested) -----------------------------------------------------

def _norm(s: str | None) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (s or "").lower()).split())


def tidy_row(r: RawRow) -> dict:
    """Clean what the model returned and say why a human should look at it, if they should."""
    name = re.sub(r"^\s*\d+[.)]?\s+", "", r.name).strip()  # "3. Verma family" → "Verma family"
    gift = (r.gift or "").strip() or None
    if gift:  # the model sometimes glues the gift onto the name
        name = re.sub(r"\s*[+&,(-]?\s*" + re.escape(gift) + r"\)?\s*$", "", name, flags=re.I).strip() or name
    reasons = []
    if not name:
        reasons.append("no name")
    if r.amount is None and not gift:
        reasons.append("no amount or gift")
    if r.amount is not None and r.amount > BIG_AMOUNT:
        reasons.append("unusually large amount")
    if r.amount is not None and 0 < r.amount < 11:
        reasons.append("unusually small amount")
    return {"name": name or "(unreadable)", "place": (r.place or "").strip() or None, "amount": r.amount, "gift": gift,
            "review": ", ".join(reasons) or None}


def mark_duplicates(rows: list[dict], existing: list[dict]) -> None:
    """Same name and amount twice in one event usually means a page was photographed twice."""
    seen = {(_norm(e["name"]), e.get("amount")) for e in existing}
    for r in rows:
        key = (_norm(r["name"]), r.get("amount"))
        if key in seen:
            r["review"] = ", ".join(filter(None, [r.get("review"), "possible duplicate"]))
        seen.add(key)


def total_check(rows: list[dict], written_total: int | None) -> dict:
    read = sum(r["amount"] or 0 for r in rows)
    if written_total is None:
        return {"read_total": read, "written_total": None, "matches": None, "difference": None}
    return {"read_total": read, "written_total": written_total, "matches": read == written_total,
            "difference": written_total - read}
