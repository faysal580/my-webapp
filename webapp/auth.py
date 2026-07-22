"""
Simple username/password auth for the Visual Team Console.
=============================================================
Users live in one of two places (checked in this order):

  1. The APP_USERS environment variable — a JSON object mapping
     username -> hashed password, e.g.:
         APP_USERS={"faysal": "pbkdf2:sha256:...", "sabbir": "pbkdf2:sha256:..."}
     This is the recommended way on Render: set it in the service's
     "Environment" tab so it survives redeploys without touching code.

  2. data/users.json — a local fallback file with the same shape,
     used automatically if APP_USERS isn't set (handy for local testing).

Never store plain-text passwords in either place — always use a hash.
Run `python add_user.py` to generate one interactively.
"""
import json
import os

from werkzeug.security import check_password_hash

BASE_DIR = os.path.dirname(__file__)
USERS_FILE = os.path.join(BASE_DIR, "data", "users.json")


def _load_users():
    raw = os.environ.get("APP_USERS")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            print("WARNING: APP_USERS env var is not valid JSON — ignoring it.")

    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            print(f"WARNING: could not read {USERS_FILE} — ignoring it.")

    return {}


def verify_user(username, password):
    """Return True if username/password is a valid login."""
    if not username or not password:
        return False
    users = _load_users()
    pw_hash = users.get(username)
    if not pw_hash:
        return False
    return check_password_hash(pw_hash, password)
