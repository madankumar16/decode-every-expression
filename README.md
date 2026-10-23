<h1 align="center">😊 Decode Every Expression</h1>

<p align="center">
  A web app that watches your face through the webcam and tells you,<br>
  in real time, which of 7 emotions you're showing.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white">
  <img src="https://img.shields.io/badge/TensorFlow-FF6F00?style=flat-square&logo=tensorflow&logoColor=white">
  <img src="https://img.shields.io/badge/OpenCV-5C3EE8?style=flat-square&logo=opencv&logoColor=white">
  <img src="https://img.shields.io/badge/Flask-000000?style=flat-square&logo=flask&logoColor=white">
  <img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white">
</p>

<!-- 📸 Add a screenshot or GIF of the dashboard detecting a face here -->

---

## ✨ Features

- 🎥 **Live webcam detection** — frames stream to the server over Socket.IO
- 🧠 **7 emotions** — Angry, Disgust, Fear, Happy, Sad, Surprise, Neutral, each with a confidence score
- 👥 **Works with more than one face** in the frame
- 💬 **Simple reading of the mood** — for example "Looks pleasantly surprised" or "Looks focused", plus an overall positive / negative / neutral label
- 📊 **Dashboard** showing the emotion scores
- 📸 **Private snapshots** — save a frame with one click; only you can see it (up to 20)
- 🔑 **Real accounts** — hashed passwords, and you can delete your snapshots or your whole account from the Account page

---

## 🧠 How it works

```text
 Browser webcam ──► frame sent over Socket.IO
                         │
                         ▼
              OpenCV finds faces (Haar cascade)
                         │
                         ▼
          Each face → grayscale, 64×64 → CNN model (Keras)
                         │
                         ▼
        7 emotion scores ──► top emotion + confidence + mood reading
                         │
                         ▼
               Results drawn live on the dashboard
```

---

## 🚀 Run it

The app needs a `SECRET_KEY` to sign sessions and **refuses to start without one**. Generate a key with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### With Python (on your computer)

```bash
git clone https://github.com/madankumar16/decode-every-expression.git
cd decode-every-expression
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cd face_emotion_detection/webapp
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python app.py
```

Then open **http://127.0.0.1:7860** and allow camera access. (Set a `PORT` environment variable to use a different port.)

For quick local testing only, `FLASK_DEBUG=1 python app.py` starts with a throwaway key instead. Never use `FLASK_DEBUG=1` on a server.

### With Docker

```bash
docker build -t decode-every-expression .
docker run -p 7860:7860 -e SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" decode-every-expression
```

Open **http://localhost:7860**. Accounts and snapshots live inside the container, so they are lost when it is recreated (see Deploy below).

### Run the tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## ☁️ Deploy (Docker / Hugging Face Spaces / Render / Cloud Run)

The Dockerfile runs the app with Gunicorn as a non-root user. Set these environment variables on your host (see `.env.example`):

| Variable | Required | What it does |
|---|---|---|
| `SECRET_KEY` | **Yes** | Signs sessions. The app refuses to start without it. Generate one with the command above. |
| `DATABASE_PATH`, `CAPTURE_DIR` | Recommended | Put these on **persistent storage** (for example `/data/app.db` and `/data/captures`). Otherwise all accounts and snapshots are wiped on every redeploy or restart. |
| `TRUST_PROXY` | Usually `1` | Set when your host terminates HTTPS in front of the app (Hugging Face, Render, Cloud Run). |
| `SESSION_COOKIE_SAMESITE` | No | `Lax` by default. Set `None` so sign-in also works inside the huggingface.co Space page; the direct `*.hf.space` link works either way. |
| `SITE_OWNER`, `CONTACT_EMAIL`, `CONTACT_PHONE`, `BUSINESS_ADDRESS` | No | Shown in the footer. |
| `ALLOWED_ORIGINS` | No | Extra sites allowed to open the live socket. Leave empty. |
| `RATELIMIT_STORAGE_URI` | No | e.g. `redis://…` if you run more than one instance. |

The app can be embedded in a Hugging Face Space (`huggingface.co` and `*.hf.space`); other sites can't put it in an iframe.

> This app needs a long-running server for its live WebSocket connection, so it is **not** suitable for Vercel serverless functions.

---

## 🔐 Security summary

- Real accounts in SQLite with scrypt-hashed passwords; generic login errors; session reset on login.
- CSRF tokens on every form and on the snapshot API; sign-out is POST-only.
- Rate limits on sign-in, sign-up, snapshots and account deletion.
- Live socket only accepts signed-in users from the same site; frames are size-checked and throttled.
- Snapshots are validated, re-encoded (metadata stripped), stored outside the public folder and served only to their owner (max 20 per user).
- Strict Content-Security-Policy (framing allowed only by this site and Hugging Face), HSTS, `nosniff`, `Referrer-Policy`, `Permissions-Policy` (camera only on this site).
- Debug mode off by default; no external scripts or fonts (fonts are self-hosted).

---

## 📁 Project layout

```text
face_emotion_detection/
├── src/
│   ├── emotion_model.h5                       ← trained emotion model
│   └── haarcascade_frontalface_default.xml    ← face detector
└── webapp/
    ├── app.py                                 ← Flask + Socket.IO server, accounts, security
    ├── templates/   (base, home, login, register, dashboard, account, error)
    └── static/      (css, js, fonts, img, vendor/socket.io)
tests/test_app.py                              ← security and behaviour tests (pytest)
Dockerfile                                     ← Gunicorn, non-root user
.env.example                                   ← settings to copy to your host
requirements.txt  requirements-dev.txt
```

---

## 🛠️ Built with

Flask · Flask-SocketIO · Flask-WTF · Flask-Limiter · Gunicorn · OpenCV · TensorFlow / Keras · NumPy · Docker

---

## 🗺️ Next steps

- [ ] Show emotion history over time on the dashboard
- [ ] Add a privacy policy and terms page

---

## 📜 Third-party licences

- Outfit and Inter fonts — SIL Open Font License 1.1 (`static/fonts/*-OFL.txt`)
- Socket.IO client — MIT (`static/vendor/socket.io-client.LICENSE`)
- `haarcascade_frontalface_default.xml` — OpenCV (Intel License Agreement, included in the file header)

---

<p align="center">Made by <a href="https://github.com/madankumar16">Madan Kumar S</a> · ECE, VTU '28</p>
