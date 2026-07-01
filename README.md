# Nova — AI assistant hub

A Flask app with a **menu launcher** and an **AI chat** powered by Google
Gemini (free tier). Built to grow: summarize text/documents, job search, and
scholarship updates are stubbed on the menu and slot in the same way.

The Gemini API key stays **server-side** (`GEMINI_API_KEY`) — the browser talks
to `/api/chat`, which proxies to Gemini, so the key is never exposed.

## Get a free Gemini key
1. Go to **https://aistudio.google.com/app/apikey** (sign in with Google — no card).
2. **Create API key** → copy it.

## Run locally
```bash
python -m venv .venv
.venv\Scripts\activate               # Windows
pip install -r requirements.txt
set GEMINI_API_KEY=your-key-here      # Windows  (export GEMINI_API_KEY=... on macOS/Linux)
python app.py
```
Open **http://127.0.0.1:5004**. Without a key the app still runs — the chat
just replies that it isn't configured. Check `/health` to see if the key loaded.

## Deploy (Render)
Push to GitHub, then **New + → Blueprint** on Render. It reads `render.yaml`
and prompts you for `GEMINI_API_KEY`. Free tier, HTTPS to Gemini works fine.

## Files
```
aiassistant/
├── app.py                 # routes + Gemini proxy
├── templates/             # base, index (menu), chat
├── static/css/style.css
├── static/js/chat.js
├── requirements.txt
├── render.yaml, Procfile
└── README.md
```

## Config
- `GEMINI_API_KEY` — your key (required for chat).
- `GEMINI_MODEL` — defaults to `gemini-1.5-flash`; set to another Gemini model if you prefer.
