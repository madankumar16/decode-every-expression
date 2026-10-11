# EmotiSense — Decode Every Expression

A Flask web app that estimates seven facial expressions (happy, sad, surprise, anger, fear, disgust, neutral) from a webcam in real time.

## Run it on your computer

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cd face_emotion_detection/webapp
FLASK_DEBUG=1 python app.py       # Windows (PowerShell): $env:FLASK_DEBUG=1; python app.py
```

Open http://127.0.0.1:7860. `FLASK_DEBUG=1` is for your own computer only.

## Run the tests

```bash
pytest -q
```

## Deploy (Docker / Hugging Face Spaces / Render / Cloud Run)

The Dockerfile runs the app with Gunicorn as a non-root user. Set these environment variables on your host (see `.env.example`):

| Variable | Required | What it does |
|---|---|---|
| `SECRET_KEY` | **Yes** | Signs sessions. The app refuses to start without it. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. |
| `TRUST_PROXY` | Usually `1` | Set when your host terminates HTTPS in front of the app. |
| `SITE_OWNER`, `CONTACT_EMAIL`, `CONTACT_PHONE`, `BUSINESS_ADDRESS` | Recommended | Shown (and clickable) in the footer and policy pages. |
| `DATABASE_PATH`, `CAPTURE_DIR` | Recommended | Put these on **persistent** storage, or accounts reset on every redeploy. |
| `ALLOWED_ORIGINS` | No | Extra sites allowed to open the live socket. Leave empty. |
| `RATELIMIT_STORAGE_URI` | No | e.g. `redis://…` if you run more than one instance. |

> This app needs a long-running server for its live WebSocket connection, so it is **not** suitable for Vercel serverless functions.

## Security summary

- Real accounts in SQLite with scrypt-hashed passwords; generic login errors; session reset on login.
- CSRF tokens on every form and on the snapshot API; sign-out is POST-only.
- Rate limits on sign-in, sign-up, snapshots and account deletion.
- Live socket only accepts signed-in users from the same site; frames are size-checked and throttled.
- Snapshots are validated, re-encoded (metadata stripped), stored outside the public folder and served only to their owner (max 20 per user).
- Strict Content-Security-Policy, HSTS, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy` (camera only on this site).
- Debug mode off by default; no external scripts or fonts (fonts are self-hosted, SIL Open Font License, see `static/fonts`).
- Users can view their data and delete snapshots or their whole account from the Account page.

## Third-party licences

- Outfit and Inter fonts — SIL Open Font License 1.1 (`static/fonts/*-OFL.txt`)
- Socket.IO client — MIT (`static/vendor/socket.io-client.LICENSE`)
- `haarcascade_frontalface_default.xml` — OpenCV (Intel License Agreement, included in the file header)
