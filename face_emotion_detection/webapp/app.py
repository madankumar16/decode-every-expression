"""EmotiSense web app: real-time facial expression estimation.

Configuration comes from environment variables (see README.md and
.env.example). Nothing secret is stored in this file.
"""
import base64
import binascii
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

import cv2
import numpy as np
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, send_from_directory, session, url_for)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


DEBUG = env_flag("FLASK_DEBUG", False)
TESTING = env_flag("APP_TESTING", False)

# --------------------------------------------------------------------------
# App and security configuration
# --------------------------------------------------------------------------
app = Flask(__name__)

secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    if DEBUG or TESTING:
        secret_key = secrets.token_hex(32)  # throwaway key for local use only
    else:
        raise RuntimeError(
            "SECRET_KEY is not set. Generate one with "
            "`python -c \"import secrets; print(secrets.token_hex(32))\"` "
            "and set it as an environment variable on your host.")

INSTANCE_DIR = os.environ.get("INSTANCE_DIR", os.path.join(BASE_DIR, "instance"))

app.config.update(
    SECRET_KEY=secret_key,
    DEBUG=DEBUG,
    TESTING=TESTING,
    MAX_CONTENT_LENGTH=3 * 1024 * 1024,  # 3 MB per request
    SESSION_COOKIE_NAME="es_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=env_flag("SESSION_COOKIE_SECURE", not (DEBUG or TESTING)),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    WTF_CSRF_TIME_LIMIT=None,  # token lives as long as the session
    DATABASE_PATH=os.environ.get("DATABASE_PATH", os.path.join(INSTANCE_DIR, "app.db")),
    CAPTURE_DIR=os.environ.get("CAPTURE_DIR", os.path.join(INSTANCE_DIR, "captures")),
    MAX_CAPTURES_PER_USER=20,
)

# Behind a reverse proxy (Hugging Face, Render, Cloud Run, nginx...) trust
# exactly one hop so request.remote_addr and HTTPS detection are correct.
if env_flag("TRUST_PROXY", False):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Business / contact details shown in the footer and policies. Set these on
# your host; anything left unset is simply not shown.
SITE = {
    "name": os.environ.get("SITE_NAME", "EmotiSense"),
    "owner": os.environ.get("SITE_OWNER", "").strip(),
    "email": os.environ.get("CONTACT_EMAIL", "").strip(),
    "phone": os.environ.get("CONTACT_PHONE", "").strip(),
    "address": os.environ.get("BUSINESS_ADDRESS", "").strip(),
    "policy_date": "11 October 2026",
}

csrf = CSRFProtect(app)
limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
    default_limits=["600 per hour"],
    headers_enabled=True,
)

# Same-origin only unless ALLOWED_ORIGINS lists extra origins (comma separated).
_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
socketio = SocketIO(
    app,
    async_mode="threading",
    cors_allowed_origins=_origins or None,
    max_http_buffer_size=1_000_000,
)

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    terms_accepted_at TEXT NOT NULL,
    age_confirmed_at TEXT NOT NULL
);
"""


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE_PATH"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db_path = app.config["DATABASE_PATH"]
    os.makedirs(os.path.dirname(db_path), mode=0o700, exist_ok=True)
    os.makedirs(app.config["CAPTURE_DIR"], mode=0o700, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
    try:
        os.chmod(db_path, 0o600)
    except OSError:
        pass


init_db()

# --------------------------------------------------------------------------
# Authentication helpers
# --------------------------------------------------------------------------
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
PASSWORD_MIN, PASSWORD_MAX = 10, 128
# Used so failed logins for unknown emails take as long as wrong passwords.
_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))


@app.before_request
def load_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        g.user = get_db().execute(
            "SELECT id, username, email, created_at FROM users WHERE id = ?",
            (user_id,)).fetchone()
        if g.user is None:
            session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please sign in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def start_session(user_id):
    session.clear()  # drop any pre-login session data (prevents fixation)
    session.permanent = True
    session["user_id"] = user_id


def user_capture_dir(user_id):
    return os.path.join(app.config["CAPTURE_DIR"], str(int(user_id)))

# --------------------------------------------------------------------------
# Security headers and template context
# --------------------------------------------------------------------------
@app.after_request
def security_headers(response):
    scheme = "wss" if request.is_secure else "ws"
    csp = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data: blob:; "
        "media-src 'self' blob:; "
        "font-src 'self'; "
        f"connect-src 'self' {scheme}://{request.host}; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers.setdefault("Content-Security-Policy", csp)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(self), microphone=(), geolocation=(), payment=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if request.is_secure or app.config["SESSION_COOKIE_SECURE"]:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if g.get("user") is not None:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.context_processor
def inject_site():
    return {"site": SITE, "current_year": datetime.now().year}

# --------------------------------------------------------------------------
# Emotion model (loaded on first use so the site starts quickly)
# --------------------------------------------------------------------------
EMOTION_LABELS = ['Angry', 'Disgust', 'Fear', 'Happy', 'Sad', 'Surprise', 'Neutral']
_model = None
_model_lock = threading.Lock()
_cascade = cv2.CascadeClassifier(
    os.path.join(BASE_DIR, '..', 'src', 'haarcascade_frontalface_default.xml'))


def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from tensorflow.keras.models import load_model  # heavy import
                _model = load_model(
                    os.path.join(BASE_DIR, '..', 'src', 'emotion_model.h5'), compile=False)
    return _model


def interpret(emotions, confidence):
    dominant = max(emotions, key=emotions.get)
    intensity = "High" if confidence > 70 else "Moderate" if confidence > 40 else "Low"
    if dominant == 'Happy' and emotions['Surprise'] > 20:
        insight = "Looks pleasantly surprised"
    elif dominant == 'Neutral' and emotions['Happy'] > 10:
        insight = "Looks slightly positive"
    elif emotions['Angry'] > 15 or emotions['Disgust'] > 15:
        insight = "Shows signs of disapproval"
    elif dominant == 'Neutral' and confidence > 80:
        insight = "Looks focused"
    else:
        insight = f"Looks {dominant.lower()}"
    sentiment = ("Positive" if dominant in ('Happy', 'Surprise') else
                 "Negative" if dominant in ('Angry', 'Sad', 'Fear', 'Disgust') else "Neutral")
    return {'intensity': intensity, 'insight': insight, 'sentiment': sentiment}


DATA_URL_RE = re.compile(r"^data:image/(jpeg|png);base64,([A-Za-z0-9+/=]+)$")


def decode_image(data_url, max_bytes):
    """Return a BGR image from a data URL, or None if it isn't a valid image."""
    if not isinstance(data_url, str) or len(data_url) > max_bytes * 4 // 3 + 64:
        return None
    match = DATA_URL_RE.match(data_url)
    if not match:
        return None
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) > max_bytes:
        return None
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def analyse_frame(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = _cascade.detectMultiScale(gray, 1.3, 5)
    results = []
    totals = {label: 0.0 for label in EMOTION_LABELS}
    if len(faces) == 0:
        return results, totals
    model = get_model()
    for (x, y, w, h) in faces:
        roi = cv2.resize(gray[y:y + h, x:x + w], (64, 64)) / 255.0
        preds = model.predict(np.reshape(roi, (1, 64, 64, 1)), verbose=0)[0]
        idx = int(np.argmax(preds))
        confidence = float(preds[idx] * 100)
        face_emotions = {label: float(preds[i] * 100) for i, label in enumerate(EMOTION_LABELS)}
        results.append({
            'box': [int(x), int(y), int(w), int(h)],
            'emotion': EMOTION_LABELS[idx],
            'confidence': confidence,
            'emotions': face_emotions,
            'analysis': interpret(face_emotions, confidence),
        })
        for label, value in face_emotions.items():
            totals[label] = max(totals[label], value)
    return results, totals

# --------------------------------------------------------------------------
# Real-time socket: signed-in users only, size-checked and throttled
# --------------------------------------------------------------------------
_last_frame_at = {}
MIN_FRAME_INTERVAL = 0.15  # seconds (about 6 frames a second at most)


@socketio.on('connect')
def on_connect():
    if session.get("user_id") is None:
        return False  # reject anonymous connections
    return None


@socketio.on('disconnect')
def on_disconnect(*_args):
    _last_frame_at.pop(request.sid, None)


@socketio.on('process_frame')
def handle_frame(data):
    if session.get("user_id") is None or not isinstance(data, dict):
        return
    now = time.monotonic()
    if now - _last_frame_at.get(request.sid, 0.0) < MIN_FRAME_INTERVAL:
        return  # drop frames that arrive too fast
    _last_frame_at[request.sid] = now
    frame = decode_image(data.get('image'), max_bytes=600_000)
    if frame is None:
        return
    try:
        faces, totals = analyse_frame(frame)
    except Exception:  # never leak internals to the browser
        app.logger.exception("Frame analysis failed")
        return
    emit('emotion_results', {'faces': faces, 'global_emotions': totals})

# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@app.route('/')
def home():
    return render_template('home.html')


@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per minute; 30 per hour", methods=["POST"])
def register():
    if g.user is not None:
        return redirect(url_for('dashboard'))
    form = {"username": "", "email": ""}
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        form = {"username": username, "email": email}
        errors = []
        if not USERNAME_RE.match(username):
            errors.append("Username must be 3–30 characters: letters, numbers, dot, dash or underscore.")
        if len(email) > 254 or not EMAIL_RE.match(email):
            errors.append("Enter a valid email address.")
        if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
            errors.append(f"Password must be {PASSWORD_MIN}–{PASSWORD_MAX} characters long.")
        if request.form.get('age_confirm') != 'yes':
            errors.append("You must confirm you are 18 or older.")
        if request.form.get('terms_accept') != 'yes':
            errors.append("You must accept the Terms and Privacy Policy.")
        if not errors:
            now = utcnow()
            try:
                db = get_db()
                cur = db.execute(
                    "INSERT INTO users (username, email, password_hash, created_at, "
                    "terms_accepted_at, age_confirmed_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (username, email, generate_password_hash(password), now, now, now))
                db.commit()
            except sqlite3.IntegrityError:
                errors.append("That username or email is already registered.")
            else:
                start_session(cur.lastrowid)
                flash("Your account is ready. Press “Start camera” when you're set.", "success")
                return redirect(url_for('dashboard'))
        for message in errors:
            flash(message, "error")
        return render_template('register.html', form=form), 400
    return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def login():
    if g.user is not None:
        return redirect(url_for('dashboard'))
    email = ""
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        row = get_db().execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
        stored = row["password_hash"] if row else _DUMMY_HASH
        if check_password_hash(stored, password) and row is not None:
            start_session(row["id"])
            return redirect(url_for('dashboard'))
        flash("Incorrect email or password.", "error")
        return render_template('login.html', email=email), 401
    return render_template('login.html', email=email)


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash("You've been signed out.", "success")
    return redirect(url_for('home'))


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


def list_captures(user_id):
    folder = user_capture_dir(user_id)
    if not os.path.isdir(folder):
        return []
    return sorted((f for f in os.listdir(folder) if f.endswith('.jpg')), reverse=True)


@app.route('/account')
@login_required
def account():
    return render_template('account.html', captures=list_captures(g.user["id"]))


@app.route('/captures/<path:filename>')
@login_required
def capture_file(filename):
    if not re.fullmatch(r"capture_\d{8}_\d{6}_[0-9a-f]{8}\.jpg", filename):
        abort(404)
    return send_from_directory(user_capture_dir(g.user["id"]), filename)


@app.route('/capture', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def capture():
    data = request.get_json(silent=True) or {}
    frame = decode_image(data.get('image'), max_bytes=2_000_000)
    if frame is None:
        return jsonify({'error': 'That image could not be read.'}), 400
    ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])  # strips metadata
    if not ok:
        return jsonify({'error': 'That image could not be saved.'}), 400
    folder = user_capture_dir(g.user["id"])
    os.makedirs(folder, mode=0o700, exist_ok=True)
    name = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}.jpg"
    with open(os.path.join(folder, name), 'wb') as fh:
        fh.write(jpeg.tobytes())
    # Keep only the newest snapshots so we never hold more than needed.
    for old in list_captures(g.user["id"])[app.config["MAX_CAPTURES_PER_USER"]:]:
        os.remove(os.path.join(folder, old))
    return jsonify({'message': 'Snapshot saved to your account.'}), 201


@app.route('/account/captures/delete', methods=['POST'])
@login_required
def delete_captures():
    shutil.rmtree(user_capture_dir(g.user["id"]), ignore_errors=True)
    flash("All your snapshots have been deleted.", "success")
    return redirect(url_for('account'))


@app.route('/account/delete', methods=['POST'])
@login_required
@limiter.limit("5 per minute")
def delete_account():
    row = get_db().execute(
        "SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)).fetchone()
    if not check_password_hash(row["password_hash"], request.form.get('password') or ''):
        flash("That password is incorrect, so your account was not deleted.", "error")
        return redirect(url_for('account'))
    shutil.rmtree(user_capture_dir(g.user["id"]), ignore_errors=True)
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (g.user["id"],))
    db.commit()
    session.clear()
    flash("Your account and all its data have been permanently deleted.", "success")
    return redirect(url_for('home'))


@app.route('/privacy')
def privacy():
    return render_template('legal/privacy.html')


@app.route('/terms')
def terms():
    return render_template('legal/terms.html')


@app.route('/cookies')
def cookies():
    return render_template('legal/cookies.html')


@app.route('/refunds')
def refunds():
    return render_template('legal/refunds.html')


@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='img/favicon.svg'), code=301)


@app.route('/robots.txt')
def robots():
    body = "User-agent: *\nDisallow: /dashboard\nDisallow: /account\nDisallow: /captures/\n"
    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}

# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
def error_page(code, title, message):
    return render_template('error.html', code=code, title=title, message=message), code


@app.errorhandler(404)
def not_found(_e):
    return error_page(404, "Page not found", "That page doesn't exist or has moved.")


@app.errorhandler(413)
def too_large(_e):
    return error_page(413, "Too large", "That upload is too big.")


@app.errorhandler(429)
def too_many(_e):
    return error_page(429, "Slow down", "Too many attempts. Please wait a minute and try again.")


@app.errorhandler(CSRFError)
def csrf_error(_e):
    return error_page(400, "Form expired", "Your form expired. Go back, refresh the page and try again.")


@app.errorhandler(500)
def server_error(_e):
    return error_page(500, "Something went wrong", "Please try again in a moment.")


if __name__ == "__main__":
    # Local development only. In production run:  gunicorn -w 1 --threads 50 app:app
    socketio.run(app, host=os.environ.get("HOST", "127.0.0.1"),
                 port=int(os.environ.get("PORT", 7860)),
                 debug=DEBUG, allow_unsafe_werkzeug=DEBUG)
