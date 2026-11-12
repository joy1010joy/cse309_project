# Firebase setup

## 1. Create a Firebase project

1. Open the Firebase console and create/select a project.
2. Enable **Cloud Firestore**.
3. Create a service account and download the JSON key locally.

## 2. Local configuration

1. Place the JSON file somewhere outside git tracking (recommended: `unicafe-project/serviceAccountKey.json`, already gitignored).
2. In `.env` set:

```bash
FIREBASE_CREDENTIALS_PATH=./serviceAccountKey.json
JWT_SECRET_KEY=replace-with-a-long-random-secret
```

Optional:

```bash
GEMINI_API_KEY=
ADMIN_EMAIL=
ADMIN_PASSWORD=
ADMIN_FULL_NAME=Cafe Admin
PROJECT_TIMEZONE=Asia/Dhaka
```

## 3. Verify

```bash
cd unicafe-project
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/api/health
```

Expected: `{"status":"ok","database":"firestore"}` when credentials load successfully.

## Security

- Never commit `.env` or `serviceAccountKey.json`
- Never print credential contents in logs or tests
- Passwords are hashed with pbkdf2_sha256
