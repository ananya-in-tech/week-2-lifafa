# Lifafa

**Your family's lena-dena, remembered. Photograph the shagun register or just say the entry out loud. Lifafa keeps track of who gave what at your functions, and what you gave back at theirs. Nothing leaves your laptop.**

Built for the [Hacktoberfest 2026 Open-Source AI Challenge, Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12) (Oct 12–18, 2026).
Post draft: [SUBMISSION.md](SUBMISSION.md)

## The problem

At Indian weddings and functions, someone sits with a notebook and writes down every *lifafa* (envelope): who gave it, from where, and how much. Families keep these registers for years, because when *you're* invited next, you give back something similar. That's *lena-dena*. It runs both ways and goes on for decades.

The notebooks get lost, the handwriting is hard to read, nobody remembers what you gave at *their* daughter's wedding, and three hundred thank-you messages go out unevenly.

## What Lifafa does

| | |
|---|---|
| **📷 Read the register** | Photograph a page. Gemma 4's vision reads the handwriting (Hindi script too). Code checks the page total, flags duplicates and odd amounts, and you confirm before anything is saved. |
| **🎤 Speak an entry** | At the shagun table, say *"Sharma ji Kanpur se 2100 aur chaandi ka sikka"* or *"Gupta aunty from Lucknow gave 5100"*. Whisper transcribes it and Gemma fills in the entry. Lifafa reads it back aloud and adds it only after you tap or say **"haan" / "yes"**. You can also upload a WhatsApp voice note or type the sentence. |
| **🌐 Indian languages** | English and Hindi, plus Bengali, Marathi, Tamil, Telugu, Gujarati, Kannada, Malayalam, Punjabi and Urdu (Whisper auto-detects). |
| **↩️ Return gifts** | *"Humne Verma ji ke bete ki shaadi mein 11,000 aur ek ghadi di"* is saved as a gift **we gave** at **their occasion**, on the same person's page as what they gave us. |
| **👥 People** | One page per person or family: what they gave, what we gave back, the balance, and a hint for next time. Import phone contacts (.vcf, or the contact picker on Android Chrome) so WhatsApp numbers fill in. Similar records can be merged. |
| **🔤 Cross-script matching** | "शर्मा जी, कानपूर" spoken in Hindi links to "Sharma ji, Kanpur" from the register, so one person stays one person across scripts and spellings. |
| **💌 Thank-you tracking** | Notes in English or Hindi that never mention the amount, ready to open in WhatsApp, with the date each was sent. |
| **🔎 Lena-dena search** | "Sharma Kanpur" shows everything they gave at your functions and everything you gave at theirs. |

```
Browser ──► FastAPI (lifafa/) ──► SQLite + register photos in data/
   │                ├──────────► Whisper large-v3-turbo (faster-whisper, CPU)   speech → text
   │                └──────────► Ollama on 127.0.0.1 ──► gemma4:e2b             photo/text → entry
   └── read-back uses the device's own voices (cloud voices are skipped)
```

## Why it runs on open models, locally

- **It's family money data.** Who gave how much, and the voices of relatives at a wedding, shouldn't go to a cloud API.
- **It's affordable to run.** A wedding means 20–30 register pages and dozens of spoken entries. Local inference costs nothing per page or per minute of audio, so a ₹299-per-event price works.
- **It's shaped for India.** Hindi script kept as written, number words like "इक्कीस सौ" understood, grammar rules decide whether *we* gave or *they* gave, and names match across scripts.

## Accuracy and speed

Measured on a CPU-only laptop (i5-1240P, 12 GB RAM, no GPU):

- **Register pages:** on a test page Gemma read all 6 rows correctly, with one small Hindi spelling slip. The ₹1 mismatch with the written total was flagged. About 10–30 s per page warm.
- **Voice:** Whisper large-v3-turbo transcribed Hindi and Indian-English test clips word for word, including "इक्कीस सौ" as 2100 and "ग्यारह हज़ार" as 11,000. The smaller Whisper model got the Hindi amounts wrong. One spoken entry takes about 20 s end to end: about 12 s to transcribe and 3 s to understand.

## Run it

Requirements: Python 3.12+, [Ollama](https://ollama.com/download).

```bash
ollama pull gemma4:e2b
```

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
```

```bash
pwsh scripts/dev.ps1
```

Open http://localhost:8020. The first voice entry downloads the Whisper model (about 1.6 GB, once). Samples are in [`samples/`](samples/): a register page and spoken Hindi and English clips.

```bash
.venv/Scripts/python -m pytest -q
```

## Deploy (free demo on Render)

[`render.yaml`](render.yaml) deploys a free demo with AI and voice turned off (Gemma plus Whisper need about 8 GB of RAM; Render's free tier has 512 MB). Events, typed entries, people, return gifts, search, thank-you notes and CSV all work there. Photo reading and voice run locally.

## Privacy

- Inference only on `127.0.0.1`; the app refuses to start with a remote host or a `:cloud` model unless `ALLOW_REMOTE_AI=true`.
- Speech is transcribed on this computer by Whisper. Lifafa doesn't use the browser's speech recognition, which sends audio to Google. The read-back uses on-device voices only.
- Photos are re-encoded with no metadata before Gemma sees them. Photos, contacts and the ledger live in `data/`, which is git-ignored.
- Contact import keeps only name, phone and city.

## License

MIT
