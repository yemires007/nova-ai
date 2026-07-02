# Nova — AI Assistant Hub

A full-stack AI web app built around one idea: a **doing** assistant for *your*
content. Chat, ask questions about your documents, analyze datasets, study,
and automate — powered by **Google Gemini**.

**🔗 Live demo:** https://nova-ai-xrhy.onrender.com

---

## Features

**Open to everyone**
- **Chat with AI** — Gemini-powered chat with rich Markdown answers: syntax-highlighted code, tables, math (KaTeX) and diagrams/flowcharts (Mermaid), plus one-click **expert personas** (resume reviewer, study coach, data analyst, coder, writer).
- **Summarize** — paste text or upload **Word / PDF / .txt** and get the gist.
- **Chat with your document (RAG)** — upload a PDF/Word/CSV and ask questions answered *from its contents*.
- **Job search** — live remote jobs (Remotive) by keyword, category, location & company.
- **Scholarship updates** — curated opportunities.

**Pro**
- **Data analysis** — upload a CSV/Excel → clean (dedupe, fill/drop missing), profile, **visualize** (histograms, bar charts, correlation heatmap) and get an **AI interpretation**.
- **Study Mode** — turn notes into flashcards, quizzes, key points or plain-English explanations.
- **Smart Productivity** — tasks, notes, and meeting-transcript → action items.
- **Custom Workflows** — chain AI steps (summarize → translate → improve …) and save the result to Notes.

**Platform**
- Accounts, **Free/Pro subscriptions** (Paystack), **password reset** (email via Resend).
- **Shareable public chats** with comments. **Export** any chat to Markdown/PDF.
- Dark/light mode, drag-and-drop uploads, animated UI.

## Tech stack
Flask · SQLAlchemy (SQLite locally / **PostgreSQL** in prod) · **Google Gemini API** ·
pandas · matplotlib · pypdf · python-docx · Flask-WTF (CSRF) · Flask-Limiter ·
Werkzeug auth · Jinja · vanilla JS (marked, DOMPurify, highlight.js, KaTeX, Mermaid) ·
gunicorn · deployed on **Render**.

## Run locally
```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
# create a .env next to app.py with at least:
#   GEMINI_API_KEY=your-google-ai-studio-key
python app.py                     # http://127.0.0.1:5004
```
Get a free Gemini key at https://aistudio.google.com/app/apikey.

## Environment variables
| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Google Gemini key (required for chat) |
| `SECRET_KEY` | Flask session secret |
| `DATABASE_URL` | Postgres in prod; defaults to local SQLite |
| `GEMINI_MODEL` | optional (default `gemini-2.5-flash`) |
| `PAYSTACK_SECRET_KEY` | optional — real payments; demo upgrade if blank |
| `RESEND_API_KEY`, `MAIL_FROM` | optional — password-reset email; on-screen link if blank |

## Deploy (Render)
Push to GitHub, then **New + → Blueprint**. `render.yaml` provisions a free
Postgres, wires `DATABASE_URL`, generates `SECRET_KEY`, and prompts for the
optional keys. Pinned to Python 3.11. The app auto-migrates new columns on
startup, so redeploys are safe.

## Security
Content-Security-Policy + security headers, CSRF protection, per-IP rate
limiting, Werkzeug-hashed passwords, and Secure/HttpOnly/SameSite cookies.

---

_A portfolio project by **Adeyemi Oluwaseyi Alao**. Demo software — not medical,
financial or professional advice._
