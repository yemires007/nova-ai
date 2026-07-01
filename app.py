"""
Nova — an AI assistant hub.

A Flask app with a menu launcher and four tools:
  * Chat with AI      — Google Gemini (open to everyone)
  * Summarize         — extractive summary of pasted text or an uploaded .txt/.pdf
  * Job search        — live remote jobs via the free Remotive API
  * Scholarships      — a curated list of opportunities

Accounts (register / log in) gate the last three features. The Gemini API key
stays server-side (GEMINI_API_KEY); the browser only talks to /api/chat.

Run locally:
    # put GEMINI_API_KEY in a .env file next to this app, then:
    python app.py            # http://127.0.0.1:5004
"""
import json
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Flask, flash, g, jsonify, redirect, render_template, request, session,
    url_for,
)
from flask_wtf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except ImportError:
    Limiter = None

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "nova.db"

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    import docx  # python-docx, for Word .docx files
except ImportError:
    docx = None

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-nova-key")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB upload cap
csrf = CSRFProtect(app)

# --- rate limiting (per client IP) ---
if Limiter is not None:
    limiter = Limiter(
        key_func=get_remote_address, app=app,
        default_limits=["300 per hour"],
        storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
    )
else:                                   # graceful no-op if the package is absent
    class _NoLimiter:
        def limit(self, *_a, **_k):
            return lambda f: f
    limiter = _NoLimiter()


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self'; connect-src 'self'; "
        "base-uri 'self'; frame-ancestors 'none'"
    )
    return resp


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404,
                           message="That page doesn't exist."), 404


@app.errorhandler(429)
def rate_limited(_e):
    if request.path.startswith("/api/"):
        return jsonify(reply="You're sending messages too fast — please slow down.",
                       error=True), 429
    return render_template("error.html", code=429,
                           message="Too many requests — please slow down and try again."), 429


@app.errorhandler(500)
def server_error(_e):
    return render_template("error.html", code=500,
                           message="Something went wrong on our end."), 500

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
SYSTEM_PROMPT = (
    "You are Nova, a friendly, concise AI assistant featured on Adeyemi "
    "Oluwaseyi Alao's portfolio. Answer helpfully and clearly, using short "
    "paragraphs or bullet points. If you're unsure, say so."
)

FEATURES = [
    {"key": "chat", "icon": "💬", "title": "Chat with AI",
     "desc": "Ask anything — powered by Google Gemini.", "endpoint": "chat_page",
     "gated": False},
    {"key": "summarize", "icon": "📝", "title": "Summarize text or document",
     "desc": "Paste text or upload a .txt/.pdf and get the gist.",
     "endpoint": "summarize", "gated": True},
    {"key": "jobs", "icon": "💼", "title": "Job search",
     "desc": "Find the latest remote jobs by keyword.", "endpoint": "jobs",
     "gated": True},
    {"key": "scholarships", "icon": "🎓", "title": "Scholarship updates",
     "desc": "Browse current scholarship opportunities.", "endpoint": "scholarships",
     "gated": True},
]

SCHOLARSHIPS = [
    {"title": "Mastercard Foundation Scholars Program", "provider": "Mastercard Foundation",
     "level": "Undergraduate & Master's", "region": "Africa",
     "blurb": "Full funding (tuition, living, travel) for academically talented "
              "young people, especially from Africa.",
     "url": "https://mastercardfdn.org/all/scholars/"},
    {"title": "Chevening Scholarships", "provider": "UK Government",
     "level": "Master's", "region": "Global",
     "blurb": "Fully-funded one-year master's study in the UK for future leaders.",
     "url": "https://www.chevening.org/"},
    {"title": "DAAD Scholarships", "provider": "DAAD (Germany)",
     "level": "Master's & PhD", "region": "Global",
     "blurb": "Funding for international students to study and research in Germany.",
     "url": "https://www.daad.de/en/study-and-research-in-germany/scholarships/"},
    {"title": "Fulbright Foreign Student Program", "provider": "US Government",
     "level": "Master's & PhD", "region": "Global",
     "blurb": "Graduate study, research and teaching in the United States.",
     "url": "https://foreign.fulbrightonline.org/"},
    {"title": "Commonwealth Scholarships", "provider": "Commonwealth (UK)",
     "level": "Master's & PhD", "region": "Commonwealth countries",
     "blurb": "Funded UK study for students from Commonwealth nations.",
     "url": "https://cscuk.fcdo.gov.uk/scholarships/"},
    {"title": "Google / Women Techmakers Scholarship", "provider": "Google",
     "level": "Undergraduate & Graduate", "region": "Global",
     "blurb": "Support for students in computer science and technology fields.",
     "url": "https://www.womentechmakers.com/scholars"},
]


# --------------------------------------------------------------------------- #
# Database + auth
# --------------------------------------------------------------------------- #
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                username   TEXT NOT NULL UNIQUE,
                pwd_hash   TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def current_user():
    uid = session.get("user_id")
    if uid is None:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Please log in to use that feature.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_user():
    return {"user": current_user()}


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #
def gemini_reply(messages):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, ("AI chat isn't switched on yet — the site owner needs to "
                      "add a GEMINI_API_KEY.")
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
        url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        app.logger.warning("Gemini HTTP %s: %s", exc.code, exc.read().decode("utf-8", "ignore")[:200])
        if exc.code in (400, 403):
            return None, "The AI key looks invalid or lacks access."
        if exc.code == 429:
            return None, "The AI is busy (rate limit) — try again shortly."
        return None, f"AI service error ({exc.code})."
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("Gemini error: %s", exc)
        return None, "Couldn't reach the AI service. Please try again."

    candidates = data.get("candidates") or []
    if not candidates:
        return None, "The AI didn't return a response (it may have been filtered). Try rephrasing."
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    return (text or "…(empty response)"), None


# --------------------------------------------------------------------------- #
# Summarizer (extractive, pure-Python — no external API)
# --------------------------------------------------------------------------- #
STOPWORDS = set("""a an the and or but if while of to in on for with as by at from
into is are was were be been being this that these those it its he she they we you
i me my our your their his her them us do does did have has had not no so than then
there here what which who whom how when where why can could should would will just
about above below over under again more most some such only own same too very""".split())


def summarize_text(text, max_sentences=5):
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return "", {}
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 0]
    if len(sentences) <= max_sentences:
        return text, {"sentences": len(sentences), "kept": len(sentences),
                      "words_in": len(text.split()), "words_out": len(text.split())}

    freq = {}
    for w in re.findall(r"[a-zA-Z']+", text.lower()):
        if w in STOPWORDS or len(w) <= 2:
            continue
        freq[w] = freq.get(w, 0) + 1
    if not freq:
        chosen = sentences[:max_sentences]
    else:
        scored = []
        for idx, s in enumerate(sentences):
            words = re.findall(r"[a-zA-Z']+", s.lower())
            if not words:
                continue
            score = sum(freq.get(w, 0) for w in words) / (len(words) ** 0.5)
            scored.append((score, idx, s))
        scored.sort(reverse=True)
        picked = sorted(scored[:max_sentences], key=lambda t: t[1])  # keep original order
        chosen = [s for _, _, s in picked]

    summary = " ".join(chosen)
    stats = {"sentences": len(sentences), "kept": len(chosen),
             "words_in": len(text.split()), "words_out": len(summary.split())}
    return summary, stats


def extract_file_text(file_storage):
    name = (file_storage.filename or "").lower()
    if name.endswith((".txt", ".md", ".csv")):
        return file_storage.read().decode("utf-8", "ignore"), None
    if name.endswith(".pdf"):
        if PdfReader is None:
            return None, "PDF support isn't installed on the server."
        try:
            reader = PdfReader(file_storage)
            return "\n".join((p.extract_text() or "") for p in reader.pages), None
        except Exception as exc:  # noqa: BLE001
            return None, f"Couldn't read that PDF: {exc}"
    if name.endswith(".docx"):
        if docx is None:
            return None, "Word (.docx) support isn't installed on the server."
        try:
            document = docx.Document(file_storage)
            return "\n".join(p.text for p in document.paragraphs), None
        except Exception as exc:  # noqa: BLE001
            return None, f"Couldn't read that Word file: {exc}"
    if name.endswith(".doc"):
        return None, "Old .doc format isn't supported — please save as .docx or PDF."
    return None, "Unsupported file — upload a .txt, .md, .pdf, or .docx."


# --------------------------------------------------------------------------- #
# Jobs (Remotive free API)
# --------------------------------------------------------------------------- #
# Remotive job categories (slug, label) for the filter dropdown.
JOB_CATEGORIES = [
    ("", "All categories"),
    ("software-dev", "Software Development"),
    ("data", "Data"),
    ("devops", "DevOps / Sysadmin"),
    ("design", "Design"),
    ("product", "Product"),
    ("marketing", "Marketing"),
    ("sales", "Sales / Business"),
    ("customer-support", "Customer Support"),
    ("finance-legal", "Finance / Legal"),
    ("hr", "HR"),
    ("qa", "QA"),
    ("writing", "Writing"),
    ("all-others", "All others"),
]


def fetch_jobs(search="", category="", company="", location="", fetch=50, show=24):
    url = "https://remotive.com/api/remote-jobs?limit=" + str(fetch)
    if search:
        url += "&search=" + urllib.parse.quote(search)
    if category:
        url += "&category=" + urllib.parse.quote(category)
    if company:
        url += "&company_name=" + urllib.parse.quote(company)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; NovaJobs/1.0)",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("Remotive error: %s", exc)
        return None, "Couldn't fetch jobs right now. Please try again."

    loc = location.strip().lower()
    jobs = []
    for j in (data.get("jobs") or []):
        job_loc = (j.get("candidate_required_location") or "Remote")
        if loc:
            jl = job_loc.lower()
            if loc not in jl and "worldwide" not in jl and "anywhere" not in jl:
                continue
        jobs.append({
            "title": j.get("title", ""),
            "company": j.get("company_name", ""),
            "location": job_loc,
            "category": j.get("category", ""),
            "date": (j.get("publication_date") or "")[:10],
            "url": j.get("url", "#"),
        })
        if len(jobs) >= show:
            break
    return jobs, None


# --------------------------------------------------------------------------- #
# Routes — menu + auth
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html", features=FEATURES)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")
    db = get_db()
    f = request.form
    name = f.get("name", "").strip()
    username = f.get("username", "").strip()
    pwd = f.get("password", "")
    confirm = f.get("confirm", "")
    if not name:
        flash("Please enter your name.", "error")
    elif len(username) < 3:
        flash("Username must be at least 3 characters.", "error")
    elif len(pwd) < 6:
        flash("Password must be at least 6 characters.", "error")
    elif pwd != confirm:
        flash("Passwords do not match.", "error")
    elif db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        flash("That username is taken.", "error")
    else:
        db.execute("INSERT INTO users (name, username, pwd_hash, created_at) VALUES (?,?,?,?)",
                   (name, username, generate_password_hash(pwd),
                    datetime.now(timezone.utc).isoformat()))
        db.commit()
        flash("Account created — please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", form=f), 400


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", next=request.args.get("next", ""))
    db = get_db()
    username = request.form.get("username", "").strip()
    pwd = request.form.get("password", "")
    nxt = request.form.get("next", "")
    row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if row and check_password_hash(row["pwd_hash"], pwd):
        session.clear()
        session["user_id"] = row["id"]
        flash(f"Welcome, {row['name']}.", "success")
        return redirect(nxt if nxt and nxt.startswith("/") else url_for("index"))
    flash("Invalid username or password.", "error")
    return render_template("login.html", next=nxt), 400


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("index"))


# --------------------------------------------------------------------------- #
# Routes — features
# --------------------------------------------------------------------------- #
@app.route("/chat")
def chat_page():
    return render_template("chat.html")


@app.route("/api/chat", methods=["POST"])
@csrf.exempt
@limiter.limit("20 per minute")
def api_chat():
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return jsonify(reply="No message received.", error=True), 400
    reply, err = gemini_reply(messages[-20:])
    return jsonify(reply=err or reply, error=bool(err))


@app.route("/summarize", methods=["GET", "POST"])
@login_required
@limiter.limit("40 per hour")
def summarize():
    if request.method == "GET":
        return render_template("summarize.html")
    text = request.form.get("text", "")
    source = "pasted text"
    upload = request.files.get("document")
    if upload and upload.filename:
        extracted, err = extract_file_text(upload)
        if err:
            flash(err, "error")
            return render_template("summarize.html", text=text), 400
        text = extracted
        source = upload.filename
    if not text.strip():
        flash("Paste some text or upload a document.", "error")
        return render_template("summarize.html"), 400
    summary, stats = summarize_text(text, max_sentences=5)
    return render_template("summarize.html", summary=summary, stats=stats, source=source)


@app.route("/jobs")
@login_required
@limiter.limit("60 per hour")
def jobs():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    company = request.args.get("company", "").strip()
    location = request.args.get("location", "").strip()
    results, err = (None, None)
    if q or category or company or location:
        results, err = fetch_jobs(q, category, company, location)
    return render_template("jobs.html", jobs=results, error=err, q=q,
                           category=category, company=company, location=location,
                           categories=JOB_CATEGORIES)


@app.route("/scholarships")
@login_required
def scholarships():
    return render_template("scholarships.html", scholarships=SCHOLARSHIPS)


@app.route("/health")
def health():
    return jsonify(gemini_configured=bool(os.environ.get("GEMINI_API_KEY")),
                   model=GEMINI_MODEL, pdf=PdfReader is not None)


init_db()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug, port=5004)
