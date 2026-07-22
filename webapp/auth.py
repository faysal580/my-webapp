"""
Username/password auth for the Visual Team Console, with self-service
password changes.

Accounts start out defined in one of these two places:

  1. The APP_USERS environment variable — a JSON object mapping
     username -> hashed password, e.g.:
         APP_USERS={"faysal": "scrypt:...", "sabbir": "scrypt:..."}
     This is the recommended way on Render: set it in the service's
     "Environment" tab so it survives redeploys without touching code.

  2. data/users.json — a local fallback file with the same shape,
     used automatically if APP_USERS isn't set (handy for local testing).

If GITHUB_TOKEN / GITHUB_REPO are configured (see github_store.py), the
FIRST time a user logs in those starting accounts are copied into
data/users.json on the repo's "app-data" branch — from then on, GitHub
becomes the source of truth, so that when someone changes their password
(see change_password below) the new hash is committed there and survives
every future redeploy. Without GitHub configured, password changes are
saved to the local users.json file instead (lost on next Render redeploy,
same caveat as profiles.py).

Run `python add_user.py` to add a brand new user (generates a hash for
APP_USERS / the seed file). Existing users change their own password from
the Profile page in the app.
"""
import json
import os

from werkzeug.security import check_password_hash, generate_password_hash

import github_store

BASE_DIR = os.path.dirname(__file__)
USERS_FILE = os.path.join(BASE_DIR, "data", "users.json")
USERS_PATH_REPO = "data/users.json"  # path inside the repo's app-data branch


def _seed_users():
    """Starting accounts, from APP_USERS or the local fallback file."""
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


def _load_users():
    """Current username -> password hash map. GitHub is the source of
    truth once it has a users.json (so password changes persist); until
    then it's seeded from APP_USERS / the local file."""
    if github_store._configured():
        content, _ = github_store.get_file(USERS_PATH_REPO)
        if content:
            try:
                return json.loads(content.decode("utf-8"))
            except json.JSONDecodeError:
                print("WARNING: data/users.json on GitHub is not valid JSON")
        # Not created yet on GitHub — seed it from APP_USERS/local so future
        # password changes have something to build on.
        seed = _seed_users()
        if seed:
            try:
                github_store.put_file(
                    USERS_PATH_REPO,
                    json.dumps(seed, indent=2, ensure_ascii=False).encode("utf-8"),
                    "Seed users.json",
                )
            except Exception as e:
                print(f"WARNING: could not seed users.json on GitHub: {e}")
        return seed

    return _seed_users()


def _save_users(users, message):
    if github_store._configured():
        github_store.put_file(
            USERS_PATH_REPO,
            json.dumps(users, indent=2, ensure_ascii=False).encode("utf-8"),
            message,
        )
    else:
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)


def verify_user(username, password):
    """Return True if username/password is a valid login."""
    if not username or not password:
        return False
    users = _load_users()
    pw_hash = users.get(username)
    if not pw_hash:
        return False
    return check_password_hash(pw_hash, password)


def change_password(username, current_password, new_password):
    """Verify the current password, then set a new one. Raises ValueError
    with a user-facing message on failure."""
    if not verify_user(username, current_password):
        raise ValueError("বর্তমান পাসওয়ার্ড ভুল।")
    if not new_password or len(new_password) < 4:
        raise ValueError("নতুন পাসওয়ার্ড কমপক্ষে ৪ ক্যারেক্টার হতে হবে।")
    if new_password == current_password:
        raise ValueError("নতুন পাসওয়ার্ড আগেরটার মতোই — অন্য কিছু দিন।")

    users = _load_users()
    users[username] = generate_password_hash(new_password)
    _save_users(users, f"Change password: {username}")


# ── Admin (owner) controls ──────────────────────────────────────────────
# The owner is anyone whose username is listed in the ADMIN_USERS env var
# (comma-separated, e.g. ADMIN_USERS=Faysal). Without it, nobody sees the
# Admin panel — set it on Render, Environment tab.

def is_admin(username):
    raw = os.environ.get("ADMIN_USERS", "")
    admins = {u.strip() for u in raw.split(",") if u.strip()}
    return username in admins


def list_usernames():
    """All usernames that currently have login access."""
    return sorted(_load_users().keys())


def admin_set_password(username, new_password):
    """Owner-initiated password reset — no current password needed. Raises
    ValueError with a user-facing message on failure."""
    users = _load_users()
    if username not in users:
        raise ValueError("এই নামে কোনো ইউজার নেই।")
    if not new_password or len(new_password) < 4:
        raise ValueError("নতুন পাসওয়ার্ড কমপক্ষে ৪ ক্যারেক্টার হতে হবে।")

    users[username] = generate_password_hash(new_password)
    _save_users(users, f"Admin reset password: {username}")


def add_or_update_user(username, password):
    """Create a brand-new account, or overwrite an existing one's password."""
    username = (username or "").strip()
    if not username:
        raise ValueError("ইউজারনেম খালি রাখা যাবে না।")
    if not password or len(password) < 4:
        raise ValueError("পাসওয়ার্ড কমপক্ষে ৪ ক্যারেক্টার হতে হবে।")

    users = _load_users()
    is_new = username not in users
    users[username] = generate_password_hash(password)
    _save_users(users, f"{'Add' if is_new else 'Update'} user: {username}")


def delete_user(username):
    """Remove a user's login access entirely."""
    users = _load_users()
    if username not in users:
        raise ValueError("এই নামে কোনো ইউজার নেই।")
    del users[username]
    _save_users(users, f"Delete user: {username}")
