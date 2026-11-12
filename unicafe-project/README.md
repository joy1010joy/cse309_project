# UniCafe

University cafe food pre-order platform with FastAPI, Firestore, and a static frontend.

## Features

- Student registration / login (JWT)
- Public menu browsing with stock availability
- Pre-orders with atomic multi-item stock deduction
- Order lifecycle: `pending → confirmed → preparing → ready → completed` (plus cancellation where allowed)
- Notifications (best-effort; never fail a committed order)
- Feedback on completed orders
- Admin: menu CRUD, inventory, orders, users, dashboard, reports/CSV, AI insights
- AI chat + recommendations with safe fallbacks when Gemini is unavailable

## Architecture

- `main.py` — FastAPI app, CORS, static mount, health
- `app/routers/` — HTTP routes
- `app/services/` — business logic
- `app/repositories/` — Firestore / FakeFirestore persistence
- `app/models/schemas.py` — request/response contracts
- `static/index.html` — single-page frontend

## Requirements

- Recommended: **Python 3.11+**
- Current local environment may use Python 3.9; some Google client libraries warn about 3.9 EOL. Prefer upgrading when possible.

## Setup

```bash
cd unicafe-project
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Copy environment variables into a local `.env` (never commit this file):

| Variable | Purpose |
|---|---|
| `JWT_SECRET_KEY` | Required in production for JWT signing |
| `JWT_ALGORITHM` | Default `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime |
| `FIREBASE_CREDENTIALS_PATH` | Path to Firebase service-account JSON |
| `GEMINI_API_KEY` | Optional; AI falls back when absent |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_FULL_NAME` | Optional bootstrap admin (created only if email missing) |
| `CORS_ORIGINS` | Comma-separated origins |
| `PROJECT_TIMEZONE` | Default `Asia/Dhaka` |

Firebase: place your service account JSON locally (ignored by git) and point `FIREBASE_CREDENTIALS_PATH` at it. See `FIREBASE_SETUP.md`.

Passwords are hashed with **pbkdf2_sha256** (passlib), not bcrypt.

## Run

```bash
cd unicafe-project
source .venv/bin/activate
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open: http://127.0.0.1:8000

## Tests

Unit tests use in-memory `FakeFirestore` only (no production Firestore):

```bash
cd unicafe-project
source .venv/bin/activate
PYTHONPATH=. pytest -q
```

## API overview

- Auth: `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`
- Menu: `GET /api/menu`, admin CRUD under `/api/admin/menu`
- Orders: `POST /api/orders`, `GET /api/orders/history`, `PUT /api/orders/{id}/cancel`
- Admin orders: `GET /api/admin/orders`, `PUT /api/admin/orders/{id}/status`
- Profile: `GET|PUT /api/profile`
- Notifications: `/api/notifications...`
- Feedback: `POST|GET /api/feedback`
- Dashboard: `GET /api/admin/dashboard`
- Reports: `/api/admin/reports/{daily,monthly,popular-items,export}`
- AI: `POST /api/ai/chat`, `GET /api/ai/recommendations`, `GET /api/admin/ai/insights`
- Health: `GET /api/health`

## Admin bootstrap

If `ADMIN_EMAIL` and `ADMIN_PASSWORD` are set and that email does not already exist, the app creates an admin on startup. No demo passwords are published in this repository.

## Revenue semantics

Dashboard and reports exclude cancelled orders from revenue. Non-cancelled orders contribute to totals.

## Known limitations

- Password change is not implemented in the UI/API (profile updates name/email/university ID only).
- AI quality depends on a configured Gemini key; otherwise fallbacks are returned.
- Python 3.9 works for this coursework setup but is below Google’s current recommended baseline.
