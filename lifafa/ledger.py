"""Lena-dena: search every event for a person, plus thank-you notes and CSV export."""

import csv
import io
import re
from urllib.parse import quote


def rupees(x: int | float | None) -> str:
    if x is None:
        return ""
    s = str(int(round(x)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = f"{head},{tail}"
    return f"₹{s}"


def thank_you(entry: dict, event: dict, language: str = "en") -> str:
    """Never mentions the amount: thanking someone for '₹5,100' would be rude."""
    name = entry["name"]
    occasion = event["name"]
    sign = event.get("from_name") or "the family"
    gift = entry.get("gift")
    if language == "hi":
        g = f" और सुंदर {gift} के लिए" if gift else " और उपहार के लिए"
        return (f"आदरणीय {name},\n{occasion} में आपके आशीर्वाद{g} हृदय से धन्यवाद। "
                f"आपकी उपस्थिति ने हमारी खुशी दोगुनी कर दी।\nसादर, {sign}")
    g = f" and the lovely {gift}" if gift else " and your generous gift"
    return (f"Dear {name},\nThank you so much for your blessings{g} at {occasion}. "
            f"Having you with us made the day even more special.\nWith love, {sign}")


def whatsapp_link(phone: str | None, text: str) -> str | None:
    """Opens WhatsApp with the note filled in. The family presses send; Lifafa never sends anything."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        digits = "91" + digits
    return f"https://wa.me/{digits}?text={quote(text)}"


def to_csv(entries: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Place", "Amount (₹)", "Gift", "Phone", "Note", "Thanked"])
    for e in entries:
        w.writerow([e["name"], e.get("place") or "", e.get("amount") or "", e.get("gift") or "", e.get("phone") or "",
                    e.get("note") or "", "yes" if e.get("thanked") else ""])
    return "﻿" + buf.getvalue()  # BOM so Excel shows ₹ and Hindi correctly
