# AI Pulse — Macro, Arena & SIP Cockpit

A lightweight, zero-dependency personal AI & macro intelligence dashboard built for both **Desktop** and **Mobile (PWA / Add to Home Screen)**.

## What It Tracks
- **Top Status Weather Bar (`GREEN` / `AMBER` / `BLUE`):**
  - **🟢 GREEN:** Normal AI media noise — keep your SIPs untouched on autopilot.
  - **🟡 AMBER:** Real infrastructure/hyperscaler shift (outages, Microsoft/Oracle cloud deal changes, workforce moves, open-weight disruption) — 3-minute brief.
  - **🔵 BLUE:** Market / tech pullback detected — monthly SIP installment buys more units at a discount.
- **LMSYS Chatbot Arena Leaderboard:** Overall Elo, Coding/SRE, and Open-Weights (vLLM / OpenShift self-hosting notes).
- **Live Markets & Your 3 SIPs:** Live AMFI NAVs via `api.mfapi.in` for **PPFAS Flexi Cap** (`122639`), **Motilal Oswal Nifty 500** (`147625`), and **Edelweiss Mid Cap** (`140228`), plus Global & Indian stock bellwethers (`NVDA`, `MSFT`, `ORCL`, `GOOGL`, `META`, `^NDX`, `^CNXIT`, `^NSEI`).
- **30-Day Forward Impact Radar:** Global Big Tech, Indian Stocks & Your ₹10k/mo SIP Position, and OpenShift/K8s Platform Engineering career takeaways.

---

## Quick Start (Local Realtime Server — Mac + Phone)

```bash
cd /Users/rakeshsharmapandyala/projects/ai-pulse
python3 server.py
```

* **On your Mac:** open `http://localhost:8090`
* **On your phone (same Wi-Fi):** open `http://<your-mac-ip>:8090`
* **1-Tap Live Sync:** Tap **Sync** in the top bar anytime. `server.py` runs `fetch_pulse.py` server-side in parallel (no browser CORS limits), refreshing **Artificial Analysis Leaderboard**, **8 Yahoo Finance stocks/indices**, **3 AMFI SIP NAVs**, **Hacker News**, **3 tech RSS feeds**, and a fresh **Gemini AI 30-day brief** in ~8–10 seconds for all devices.

*(Or run `python3 fetch_pulse.py` standalone for CLI / GitHub Actions.)*

---

## Gemini API Key

1. Create a key at **Google AI Studio**: https://aistudio.google.com/apikey
2. Either export it before starting the server:
   ```bash
   export GEMINI_API_KEY="your-key-here"
   python3 server.py
   ```
   or tap **⚙️** in the app and paste it (stored only in that browser).

---

## Sync Policy — On-Demand Only

There is **no scheduled or automated sync**. Gemini is called only when you tap **Sync** (or run `python3 fetch_pulse.py` yourself). No cron jobs, no GitHub Actions.

---

## Using as a Mobile App (iPhone & Android)

With `server.py` running on your Mac, on the same Wi-Fi:
- **iOS (Safari):** Open `http://<your-mac-ip>:8090` -> **Share** -> **Add to Home Screen**.
- **Android (Chrome):** Open the URL -> **⋮ Menu** -> **Add to Home screen**.
