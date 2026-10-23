"""Security and behaviour tests. Run with:  pytest -q"""
import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np
import pytest

WEBAPP = os.path.join(os.path.dirname(__file__), "..", "face_emotion_detection", "webapp")
_tmp = tempfile.mkdtemp()
os.environ["APP_TESTING"] = "1"
os.environ["INSTANCE_DIR"] = _tmp
sys.path.insert(0, os.path.abspath(WEBAPP))

import app as webapp  # noqa: E402

PASSWORD = "correct horse battery"


@pytest.fixture()
def client():
    webapp.limiter.reset()
    with webapp.app.app_context():
        db = webapp.get_db()
        db.execute("DELETE FROM users")
        db.commit()
    shutil.rmtree(webapp.app.config["CAPTURE_DIR"], ignore_errors=True)
    os.makedirs(webapp.app.config["CAPTURE_DIR"], exist_ok=True)
    with webapp.app.test_client() as c:
        yield c


def csrf_from(resp):
    match = re.search(r'name="csrf_token" value="([^"]+)"', resp.get_data(as_text=True))
    assert match, "page has no CSRF token"
    return match.group(1)


def register(c, username="alice", email="alice@example.com", password=PASSWORD, consent=True):
    token = csrf_from(c.get("/register"))
    data = {"csrf_token": token, "username": username, "email": email, "password": password}
    if consent:
        data.update(age_confirm="yes")
    return c.post("/register", data=data)


def logout(c):
    token = csrf_from(c.get("/dashboard"))
    return c.post("/logout", data={"csrf_token": token})


def jpeg_data_url():
    img = np.full((60, 80, 3), 200, np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def page_csrf(c):
    m = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/dashboard").get_data(as_text=True))
    return m.group(1)


# ---------- configuration ----------
def test_debug_off_and_secure_cookie_defaults():
    assert webapp.app.debug is False
    assert webapp.app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert webapp.app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_refuses_to_start_without_secret_key_in_production():
    env = {k: v for k, v in os.environ.items() if k not in ("APP_TESTING", "SECRET_KEY", "FLASK_DEBUG")}
    env["INSTANCE_DIR"] = tempfile.mkdtemp()
    proc = subprocess.run([sys.executable, "-c", "import app"], cwd=os.path.abspath(WEBAPP),
                          env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "SECRET_KEY is not set" in proc.stderr


def test_security_headers(client):
    r = client.get("/")
    h = r.headers
    assert "default-src 'self'" in h["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert "camera=(self)" in h["Permissions-Policy"]
    assert h["Referrer-Policy"] == "strict-origin-when-cross-origin"


# ---------- pages ----------
@pytest.mark.parametrize("path", ["/", "/login", "/register", "/robots.txt"])
def test_public_pages_load(client, path):
    assert client.get(path).status_code == 200


def test_every_page_has_title_and_description(client):
    for path in ["/", "/login", "/register"]:
        html = client.get(path).get_data(as_text=True)
        assert re.search(r"<title>[^<]{5,}</title>", html), path
        assert re.search(r'<meta name="description" content="[^"]{20,}"', html), path
        assert 'rel="icon"' in html, path


def test_custom_404(client):
    r = client.get("/no-such-page")
    assert r.status_code == 404
    assert "Page not found" in r.get_data(as_text=True)


def test_no_external_scripts_or_fonts(client):
    html = client.get("/").get_data(as_text=True)
    assert "googleapis" not in html and "cdn." not in html


def test_old_unauthenticated_endpoint_removed(client):
    assert client.get("/get_emotions").status_code == 404


# ---------- authentication ----------
def test_dashboard_requires_login(client):
    r = client.get("/dashboard")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_register_requires_age_confirmation(client):
    r = register(client, consent=False)
    assert r.status_code == 400
    assert client.get("/dashboard").status_code == 302


def test_register_validates_input(client):
    assert register(client, username="<script>", email="x@example.com").status_code == 400
    assert register(client, username="bob", email="not-an-email").status_code == 400
    assert register(client, username="bob", email="b@example.com", password="short").status_code == 400


def test_password_is_hashed(client):
    register(client)
    with webapp.app.app_context():
        stored = webapp.get_db().execute("SELECT password_hash FROM users").fetchone()[0]
    assert PASSWORD not in stored
    assert stored.startswith(("scrypt:", "pbkdf2:"))


def test_duplicate_account_rejected(client):
    register(client)
    logout(client)
    assert register(client, username="alice2", email="ALICE@example.com").status_code == 400


def test_login_rejects_wrong_password_and_accepts_right_one(client):
    register(client)
    logout(client)
    token = csrf_from(client.get("/login"))
    r = client.post("/login", data={"csrf_token": token, "email": "alice@example.com", "password": "wrong password!"})
    assert r.status_code == 401
    assert client.get("/dashboard").status_code == 302
    r = client.post("/login", data={"csrf_token": token, "email": "alice@example.com", "password": PASSWORD})
    assert r.status_code == 302
    assert client.get("/dashboard").status_code == 200


def test_unknown_email_gets_same_message(client):
    token = csrf_from(client.get("/login"))
    r = client.post("/login", data={"csrf_token": token, "email": "nobody@example.com", "password": PASSWORD})
    assert r.status_code == 401
    assert "Incorrect email or password." in r.get_data(as_text=True)


def test_forms_require_csrf_token(client):
    r = client.post("/login", data={"email": "a@example.com", "password": PASSWORD})
    assert r.status_code == 400
    assert "Form expired" in r.get_data(as_text=True)


def test_logout_needs_post(client):
    register(client)
    assert client.get("/logout").status_code == 405
    assert logout(client).status_code == 302
    assert client.get("/dashboard").status_code == 302


def test_login_is_rate_limited(client):
    token = csrf_from(client.get("/login"))
    codes = [client.post("/login", data={"csrf_token": token, "email": "x@example.com", "password": "nope nope nope"}).status_code
             for _ in range(12)]
    assert 429 in codes


def test_user_input_is_escaped(client):
    token = csrf_from(client.get("/login"))
    r = client.post("/login", data={"csrf_token": token, "email": '"><script>alert(1)</script>', "password": "x"})
    html = r.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html


# ---------- snapshots ----------
def test_capture_requires_login(client):
    r = client.post("/capture", json={"image": jpeg_data_url()})
    assert r.status_code in (302, 400)  # redirected to login (or rejected without CSRF)


def test_capture_rejects_non_images(client):
    register(client)
    headers = {"X-CSRFToken": page_csrf(client)}
    assert client.post("/capture", json={"image": "data:image/jpeg;base64,AAAA"}, headers=headers).status_code == 400
    assert client.post("/capture", json={"image": "<svg onload=alert(1)>"}, headers=headers).status_code == 400


def test_capture_is_private_and_deletable(client):
    register(client)
    r = client.post("/capture", json={"image": jpeg_data_url()}, headers={"X-CSRFToken": page_csrf(client)})
    assert r.status_code == 201
    html = client.get("/account").get_data(as_text=True)
    name = re.search(r"capture_\d{8}_\d{6}_[0-9a-f]{8}\.jpg", html).group(0)
    assert client.get(f"/captures/{name}").status_code == 200
    assert client.get(f"/static/captures/{name}").status_code == 404  # not public any more

    logout(client)
    register(client, username="mallory", email="m@example.com")
    assert client.get(f"/captures/{name}").status_code == 404  # other users can't see it
    assert client.get("/captures/../app.db").status_code == 404


def test_delete_account_removes_everything(client):
    register(client)
    client.post("/capture", json={"image": jpeg_data_url()}, headers={"X-CSRFToken": page_csrf(client)})
    token = csrf_from(client.get("/account"))
    r = client.post("/account/delete", data={"csrf_token": token, "password": "wrong password!"})
    with webapp.app.app_context():
        assert webapp.get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    with webapp.app.app_context():
        user_id = webapp.get_db().execute("SELECT id FROM users").fetchone()[0]
    user_dir = webapp.user_capture_dir(user_id)
    assert os.listdir(user_dir)
    r = client.post("/account/delete", data={"csrf_token": token, "password": PASSWORD})
    assert r.status_code == 302
    with webapp.app.app_context():
        assert webapp.get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    assert not os.path.exists(user_dir)


# ---------- real-time socket ----------
def test_socket_rejects_anonymous_users(client):
    sc = webapp.socketio.test_client(webapp.app, flask_test_client=client)
    assert not sc.is_connected()


def test_socket_works_for_signed_in_users(client, monkeypatch):
    register(client)
    monkeypatch.setattr(webapp, "analyse_frame", lambda frame: ([], {k: 0.0 for k in webapp.EMOTION_LABELS}))
    sc = webapp.socketio.test_client(webapp.app, flask_test_client=client)
    assert sc.is_connected()
    sc.emit("process_frame", {"image": jpeg_data_url()})
    received = sc.get_received()
    assert received and received[0]["name"] == "emotion_results"
    sc.emit("process_frame", {"image": "x" * 2_000_000})  # oversized: ignored, no crash
    sc.disconnect()


def test_interpret_labels():
    out = webapp.interpret({k: 0.0 for k in webapp.EMOTION_LABELS} | {"Happy": 90.0}, 90.0)
    assert out["sentiment"] == "Positive" and out["intensity"] == "High"
