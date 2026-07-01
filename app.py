"""
Nova — an AI assistant hub.

Flask app with a menu launcher and tools (chat, summarize, jobs, scholarships),
user accounts, persisted chat history + saved summaries (SQLAlchemy — SQLite
locally, Postgres in production via DATABASE_URL), and subscription plans
(Free / Pro) with a pricing page.

The Gemini API key stays server-side (GEMINI_API_KEY); the browser only talks
to /api/chat.

Run locally:
    # put GEMINI_API_KEY in a .env next to this file, then:
    python app.py            # http://127.0.0.1:5004
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request, session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except ImportError:
    Limiter = None

BASE_DIR = Path(__file__).resolve().parent

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
    import docx  # python-docx
except ImportError:
    docx = None


def _db_uri():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///" + str(BASE_DIR / "nova.db")
    if url.startswith("postgres://"):        # Render/Heroku style -> SQLAlchemy style
        url = url.replace("postgres://", "postgresql://", 1)
    return url


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-nova-key")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
app.config["SQLALCHEMY_DATABASE_URI"] = _db_uri()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
csrf = CSRFProtect(app)

if Limiter is not None:
    limiter = Limiter(key_func=get_remote_address, app=app,
                      default_limits=["300 per hour"],
                      storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"))
else:
    class _NoLimiter:
        def limit(self, *_a, **_k):
            return lambda f: f
    limiter = _NoLimiter()

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
SYSTEM_PROMPT = (
    "You are Nova, a friendly, concise AI assistant. Answer helpfully and "
    "clearly. Use Markdown when useful — headings, bullet points, tables, and "
    "fenced code blocks with a language tag. If you're unsure, say so."
)
FREE_MAX_CONVERSATIONS = 5   # Pro removes this cap


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
def utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    pwd_hash = db.Column(db.String(255), nullable=False)
    plan = db.Column(db.String(20), nullable=False, default="free")  # free | pro
    created_at = db.Column(db.DateTime, default=utcnow)
    conversations = db.relationship("Conversation", backref="user", lazy=True,
                                    cascade="all, delete-orphan")
    summaries = db.relationship("SavedSummary", backref="user", lazy=True,
                                cascade="all, delete-orphan")

    @property
    def is_pro(self):
        return self.plan == "pro"


class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(160), default="New chat")
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow)
    messages = db.relationship("Message", backref="conversation", lazy=True,
                               cascade="all, delete-orphan",
                               order_by="Message.id")


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversation.id"), nullable=False)
    role = db.Column(db.String(12), nullable=False)   # user | assistant
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class SavedSummary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    source = db.Column(db.String(200), default="text")
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


with app.app_context():
    db.create_all()


# --------------------------------------------------------------------------- #
# Auth helpers
# --------------------------------------------------------------------------- #
def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


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
# Hardening: security headers + error pages
# --------------------------------------------------------------------------- #
@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # allow the CDN libs used to render rich AI responses (markdown/code/math/diagrams)
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "connect-src 'self'; base-uri 'self'; frame-ancestors 'none'"
    )
    return resp


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, message="That page doesn't exist."), 404


@app.errorhandler(429)
def rate_limited(_e):
    if request.path.startswith("/api/"):
        return jsonify(reply="You're going too fast — please slow down.", error=True), 429
    return render_template("error.html", code=429,
                           message="Too many requests — please slow down."), 429


@app.errorhandler(500)
def server_error(_e):
    return render_template("error.html", code=500, message="Something went wrong."), 500


# --------------------------------------------------------------------------- #
# Content: menu + scholarships
# --------------------------------------------------------------------------- #
FEATURES = [
    {"icon": "💬", "title": "Chat with AI",
     "desc": "Ask anything, with rich formatted answers.", "endpoint": "chat_page", "gated": False},
    {"icon": "📝", "title": "Summarize text or document",
     "desc": "Paste text or upload Word/PDF/txt and get the gist.", "endpoint": "summarize", "gated": True},
    {"icon": "💼", "title": "Job search",
     "desc": "Find the latest remote jobs by keyword, category & location.", "endpoint": "jobs", "gated": True},
    {"icon": "🎓", "title": "Scholarship updates",
     "desc": "Browse current scholarship opportunities.", "endpoint": "scholarships", "gated": True},
]

PRO_TOOLS = [
    {"icon": "📚", "title": "AI Study Mode", "desc": "Flashcards, quizzes and guided learning."},
    {"icon": "✅", "title": "Smart Productivity", "desc": "Tasks, reminders, notes & meeting summaries."},
    {"icon": "🤝", "title": "Collaboration", "desc": "Share chats and work with your team."},
    {"icon": "⚡", "title": "Custom Workflows", "desc": "Automate: summarize → translate → save → notify."},
]

SCHOLARSHIPS = [
    {"title": "Mastercard Foundation Scholars Program", "provider": "Mastercard Foundation",
     "level": "Undergraduate & Master's", "region": "Africa",
     "blurb": "Full funding for academically talented young people, especially from Africa.",
     "url": "https://mastercardfdn.org/all/scholars/"},
    {"title": "Chevening Scholarships", "provider": "UK Government", "level": "Master's", "region": "Global",
     "blurb": "Fully-funded one-year master's study in the UK for future leaders.",
     "url": "https://www.chevening.org/"},
    {"title": "DAAD Scholarships", "provider": "DAAD (Germany)", "level": "Master's & PhD", "region": "Global",
     "blurb": "Funding to study and research in Germany.",
     "url": "https://www.daad.de/en/study-and-research-in-germany/scholarships/"},
    {"title": "Fulbright Foreign Student Program", "provider": "US Government", "level": "Master's & PhD", "region": "Global",
     "blurb": "Graduate study, research and teaching in the United States.",
     "url": "https://foreign.fulbrightonline.org/"},
    {"title": "Commonwealth Scholarships", "provider": "Commonwealth (UK)", "level": "Master's & PhD", "region": "Commonwealth",
     "blurb": "Funded UK study for students from Commonwealth nations.",
     "url": "https://cscuk.fcdo.gov.uk/scholarships/"},
    {"title": "Women Techmakers Scholarship", "provider": "Google", "level": "Undergraduate & Graduate", "region": "Global",
     "blurb": "Support for students in computer science and technology.",
     "url": "https://www.womentechmakers.com/scholars"},
]

JOB_CATEGORIES = [
    ("", "All categories"), ("software-dev", "Software Development"), ("data", "Data"),
    ("devops", "DevOps / Sysadmin"), ("design", "Design"), ("product", "Product"),
    ("marketing", "Marketing"), ("sales", "Sales / Business"),
    ("customer-support", "Customer Support"), ("finance-legal", "Finance / Legal"),
    ("hr", "HR"), ("qa", "QA"), ("writing", "Writing"), ("all-others", "All others"),
]

PLANS = {
    "free": {"name": "Free", "price": "₦0", "period": "forever",
             "features": ["Chat with AI", "Summarize documents", "Job search",
                          "Scholarship updates", f"Save up to {FREE_MAX_CONVERSATIONS} chats"]},
    "pro": {"name": "Pro", "price": "₦2,500", "period": "/month",
            "features": ["Everything in Free", "Unlimited saved chats & summaries",
                         "AI Study Mode", "Smart Productivity (tasks, reminders, notes)",
                         "Collaboration & sharing", "Custom automation workflows",
                         "Priority responses"]},
}


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #
def gemini_reply(messages):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, "AI chat isn't configured yet — a GEMINI_API_KEY is needed."
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
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1200},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        app.logger.warning("Gemini HTTP %s: %s", exc.code, exc.read().decode('utf-8', 'ignore')[:200])
        if exc.code in (400, 403):
            return None, "The AI key looks invalid or lacks access."
        if exc.code == 429:
            return None, "The AI is busy (quota/rate limit) — try again shortly."
        return None, f"AI service error ({exc.code})."
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("Gemini error: %s", exc)
        return None, "Couldn't reach the AI service. Please try again."
    candidates = data.get("candidates") or []
    if not candidates:
        return None, "The AI didn't return a response (it may have been filtered)."
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    return (text or "…(empty response)"), None


# --------------------------------------------------------------------------- #
# Summarizer + file extraction
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
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sentences) <= max_sentences:
        n = len(text.split())
        return text, {"sentences": len(sentences), "kept": len(sentences), "words_in": n, "words_out": n}
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
            scored.append((sum(freq.get(w, 0) for w in words) / (len(words) ** 0.5), idx, s))
        scored.sort(reverse=True)
        chosen = [s for _, _, s in sorted(scored[:max_sentences], key=lambda t: t[1])]
    summary = " ".join(chosen)
    return summary, {"sentences": len(sentences), "kept": len(chosen),
                     "words_in": len(text.split()), "words_out": len(summary.split())}


def extract_file_text(fs):
    name = (fs.filename or "").lower()
    if name.endswith((".txt", ".md", ".csv")):
        return fs.read().decode("utf-8", "ignore"), None
    if name.endswith(".pdf"):
        if PdfReader is None:
            return None, "PDF support isn't installed on the server."
        try:
            return "\n".join((p.extract_text() or "") for p in PdfReader(fs).pages), None
        except Exception as exc:  # noqa: BLE001
            return None, f"Couldn't read that PDF: {exc}"
    if name.endswith(".docx"):
        if docx is None:
            return None, "Word (.docx) support isn't installed on the server."
        try:
            return "\n".join(p.text for p in docx.Document(fs).paragraphs), None
        except Exception as exc:  # noqa: BLE001
            return None, f"Couldn't read that Word file: {exc}"
    if name.endswith(".doc"):
        return None, "Old .doc isn't supported — save as .docx or PDF."
    return None, "Unsupported file — upload .txt, .md, .pdf or .docx."


# --------------------------------------------------------------------------- #
# Jobs (Remotive)
# --------------------------------------------------------------------------- #
def fetch_jobs(search="", category="", company="", location="", fetch=50, show=24):
    url = "https://remotive.com/api/remote-jobs?limit=" + str(fetch)
    if search:
        url += "&search=" + urllib.parse.quote(search)
    if category:
        url += "&category=" + urllib.parse.quote(category)
    if company:
        url += "&company_name=" + urllib.parse.quote(company)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; NovaJobs/1.0)", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("Remotive error: %s", exc)
        return None, "Couldn't fetch jobs right now. Please try again."
    loc = location.strip().lower()
    jobs = []
    for j in (data.get("jobs") or []):
        jl = (j.get("candidate_required_location") or "Remote")
        if loc and loc not in jl.lower() and "worldwide" not in jl.lower() and "anywhere" not in jl.lower():
            continue
        jobs.append({"title": j.get("title", ""), "company": j.get("company_name", ""),
                     "location": jl, "category": j.get("category", ""),
                     "date": (j.get("publication_date") or "")[:10], "url": j.get("url", "#")})
        if len(jobs) >= show:
            break
    return jobs, None


# --------------------------------------------------------------------------- #
# Routes — menu + auth
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html", features=FEATURES, pro_tools=PRO_TOOLS)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")
    f = request.form
    name, username = f.get("name", "").strip(), f.get("username", "").strip()
    pwd, confirm = f.get("password", ""), f.get("confirm", "")
    if not name:
        flash("Please enter your name.", "error")
    elif len(username) < 3:
        flash("Username must be at least 3 characters.", "error")
    elif len(pwd) < 6:
        flash("Password must be at least 6 characters.", "error")
    elif pwd != confirm:
        flash("Passwords do not match.", "error")
    elif User.query.filter_by(username=username).first():
        flash("That username is taken.", "error")
    else:
        db.session.add(User(name=name, username=username, pwd_hash=generate_password_hash(pwd)))
        db.session.commit()
        flash("Account created — please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", form=f), 400


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", next=request.args.get("next", ""))
    username = request.form.get("username", "").strip()
    pwd = request.form.get("password", "")
    nxt = request.form.get("next", "")
    u = User.query.filter_by(username=username).first()
    if u and check_password_hash(u.pwd_hash, pwd):
        session.clear()
        session["user_id"] = u.id
        flash(f"Welcome, {u.name}.", "success")
        return redirect(nxt if nxt and nxt.startswith("/") else url_for("index"))
    flash("Invalid username or password.", "error")
    return render_template("login.html", next=nxt), 400


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("index"))


# --------------------------------------------------------------------------- #
# Subscription
# --------------------------------------------------------------------------- #
@app.route("/pricing")
def pricing():
    return render_template("pricing.html", plans=PLANS)


@app.route("/subscribe", methods=["POST"])
@login_required
def subscribe():
    user = current_user()
    user.plan = "pro"
    db.session.commit()
    flash("🎉 You're on Pro now! (Demo upgrade — real billing via Paystack/Stripe coming.)", "success")
    return redirect(url_for("index"))


@app.route("/downgrade", methods=["POST"])
@login_required
def downgrade():
    user = current_user()
    user.plan = "free"
    db.session.commit()
    flash("Switched back to the Free plan.", "success")
    return redirect(url_for("pricing"))


# --------------------------------------------------------------------------- #
# Chat + history
# --------------------------------------------------------------------------- #
@app.route("/chat")
def chat_page():
    convo, messages = None, []
    user = current_user()
    cid = request.args.get("c", type=int)
    if user and cid:
        convo = db.session.get(Conversation, cid)
        if not convo or convo.user_id != user.id:
            abort(404)
        messages = [{"role": m.role, "text": m.content} for m in convo.messages]
    return render_template("chat.html", conversation_id=convo.id if convo else None,
                           preload=messages)


@app.route("/api/chat", methods=["POST"])
@csrf.exempt
@limiter.limit("20 per minute")
def api_chat():
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return jsonify(reply="No message received.", error=True), 400
    reply, err = gemini_reply(messages[-20:])
    if err:
        return jsonify(reply=err, error=True)

    convo_id = payload.get("conversation_id")
    user = current_user()
    if user:
        last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
        convo = db.session.get(Conversation, convo_id) if convo_id else None
        if not convo or convo.user_id != user.id:
            # enforce free-plan cap on number of saved conversations
            if not user.is_pro:
                count = Conversation.query.filter_by(user_id=user.id).count()
                if count >= FREE_MAX_CONVERSATIONS:
                    return jsonify(reply=reply, conversation_id=None,
                                   notice="Free plan saves up to %d chats. Upgrade to Pro to keep more."
                                   % FREE_MAX_CONVERSATIONS)
            title = (last_user["text"][:60] if last_user else "New chat")
            convo = Conversation(user_id=user.id, title=title)
            db.session.add(convo)
            db.session.flush()
        if last_user:
            db.session.add(Message(conversation_id=convo.id, role="user", content=last_user["text"][:8000]))
        db.session.add(Message(conversation_id=convo.id, role="assistant", content=reply[:8000]))
        convo.updated_at = utcnow()
        db.session.commit()
        return jsonify(reply=reply, conversation_id=convo.id)
    return jsonify(reply=reply, conversation_id=None)


@app.route("/history")
@login_required
def history():
    user = current_user()
    convos = Conversation.query.filter_by(user_id=user.id).order_by(Conversation.updated_at.desc()).all()
    sums = SavedSummary.query.filter_by(user_id=user.id).order_by(SavedSummary.id.desc()).all()
    return render_template("history.html", conversations=convos, summaries=sums,
                           limit=FREE_MAX_CONVERSATIONS)


@app.route("/conversation/<int:cid>/delete", methods=["POST"])
@login_required
def delete_conversation(cid):
    convo = db.session.get(Conversation, cid)
    if convo and convo.user_id == current_user().id:
        db.session.delete(convo)
        db.session.commit()
        flash("Chat deleted.", "success")
    return redirect(url_for("history"))


# --------------------------------------------------------------------------- #
# Summarize / jobs / scholarships
# --------------------------------------------------------------------------- #
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
        text, source = extracted, upload.filename
    if not text.strip():
        flash("Paste some text or upload a document.", "error")
        return render_template("summarize.html"), 400
    summary, stats = summarize_text(text, max_sentences=5)
    db.session.add(SavedSummary(user_id=current_user().id, source=source, content=summary))
    db.session.commit()
    return render_template("summarize.html", summary=summary, stats=stats, source=source, saved=True)


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
    return render_template("jobs.html", jobs=results, error=err, q=q, category=category,
                           company=company, location=location, categories=JOB_CATEGORIES)


@app.route("/scholarships")
@login_required
def scholarships():
    return render_template("scholarships.html", scholarships=SCHOLARSHIPS)


@app.route("/health")
def health():
    return jsonify(gemini_configured=bool(os.environ.get("GEMINI_API_KEY")),
                   model=GEMINI_MODEL, pdf=PdfReader is not None, docx=docx is not None,
                   db=app.config["SQLALCHEMY_DATABASE_URI"].split(":")[0])


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "1") == "1", port=5004)
