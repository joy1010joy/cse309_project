# Authentication notes

UniCafe uses JWT bearer tokens and passlib **pbkdf2_sha256** password hashes.

## Endpoints

- `POST /api/auth/register` — create student account (password min length 8)
- `POST /api/auth/login` — email/password login
- `GET /api/auth/me` — current user profile (never returns `password_hash`)

## Bootstrap admin

Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env`. On startup the app creates that admin **only if** the email does not already exist. Do not commit real credentials.

## Security checklist

- Passwords hashed with pbkdf2_sha256
- JWT signed with `JWT_SECRET_KEY`
- Disabled users cannot login; existing tokens are rejected by `get_current_user`
- Profile responses use safe public fields only
- Admin routes require `is_admin`
