"""
Nova — an AI assistant hub.

A Flask app with a menu launcher and an AI chat powered by Google Gemini
(free tier). The Gemini API key lives only on the server (GEMINI_API_KEY env
var) and is never exposed to the browser — the page talks to /api/chat, which
proxies to Gemini.

More features (summarize text/documents, job search, scholarship updates) are
stubbed on the menu as "coming soon" and will slot in the same way.

Run locally:
    set GEMINI_API_KEY=...   (Windows)   /   export GEMINI_API_KEY=...
    python app.py            # http://127.0.0.1:5004
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    # load the .env sitting next to this file, regardless of the working dir
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

app = Flask(__name__)

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
SYSTEM_PROMPT = (
    "You are Nova, a friendly, concise AI assistant featured on Adeyemi "
    "Oluwaseyi Alao's portfolio. Answer helpfully and clearly. Use short "
    "paragraphs or bullet points. If you're unsure, say so."
)

# Menu of features. `ready` ones are live; others show as "coming soon".
FEATURES = [
    {"key": "chat", "icon": "💬", "title": "Chat with AI",
     "desc": "Ask anything — powered by Google Gemini.", "url": "/chat",
     "ready": True},
    {"key": "summarize", "icon": "📝", "title": "Summarize text or document",
     "desc": "Paste text or upload a file and get the gist.", "url": "#",
     "ready": False},
    {"key": "jobs", "icon": "💼", "title": "Job search",
     "desc": "Find the latest remote jobs by keyword.", "url": "#",
     "ready": False},
    {"key": "scholarships", "icon": "🎓", "title": "Scholarship updates",
     "desc": "Browse the latest scholarship opportunities.", "url": "#",
     "ready": False},
]


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #
def gemini_reply(messages):
    """messages: [{role: 'user'|'assistant', text: str}]. Returns (reply, error)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, ("AI chat isn't switched on yet — the site owner needs to "
                      "add a GEMINI_API_KEY. Everything else still works.")

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={key}")
    contents = []
    for m in messages:
        text = str(m.get("text", "")).strip()[:4000]
        if not text:
            continue
        role = "model" if m.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": text}]})
    if not contents:
        return None, "Say something and I'll reply."

    body = json.dumps({
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 800},
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:300]
        app.logger.warning("Gemini HTTP %s: %s", exc.code, detail)
        if exc.code in (400, 403):
            return None, "The AI key looks invalid or lacks access. Check GEMINI_API_KEY."
        if exc.code == 429:
            return None, "The AI is busy (rate limit) — try again in a moment."
        return None, f"AI service error ({exc.code}). Please try again."
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("Gemini error: %s", exc)
        return None, "Couldn't reach the AI service. Please try again."

    # extract text
    candidates = data.get("candidates") or []
    if not candidates:
        # often a safety block
        return None, "The AI didn't return a response (it may have been filtered). Try rephrasing."
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    return (text or "…(empty response)"), None


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html", features=FEATURES)


@app.route("/chat")
def chat_page():
    return render_template("chat.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return jsonify(reply="No message received.", error=True), 400
    reply, err = gemini_reply(messages[-20:])   # cap context to last 20 turns
    if err:
        return jsonify(reply=err, error=True)
    return jsonify(reply=reply)


@app.route("/health")
def health():
    return jsonify(gemini_configured=bool(os.environ.get("GEMINI_API_KEY")),
                   model=GEMINI_MODEL)


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug, port=5004)
