"""
User profile storage: full name, bio, email, avatar image.

Backed by GitHub (via github_store.py) when GITHUB_TOKEN + GITHUB_REPO are
set, so profiles survive Render redeploys. Falls back to local files under
data/ (for local testing only — Render will lose these on the next deploy).
"""
import json
import mimetypes
import os

import github_store

BASE_DIR = os.path.dirname(__file__)

PROFILES_PATH = "data/profiles.json"     # path inside the repo's data branch
AVATAR_DIR = "data/avatars"              # path inside the repo's data branch

LOCAL_PROFILES_FILE = os.path.join(BASE_DIR, "data", "profiles.json")
LOCAL_AVATAR_DIR = os.path.join(BASE_DIR, "data", "avatars")

ALLOWED_AVATAR_EXT = {"png", "jpg", "jpeg", "webp"}
MAX_AVATAR_BYTES = 4 * 1024 * 1024  # 4 MB

DEFAULT_PROFILE = {"full_name": "", "bio": "", "email": "", "avatar": ""}

# In-memory cache so we don't re-fetch avatar bytes from GitHub on every
# page view. Cleared automatically when a new avatar is saved.
_avatar_cache = {}


def use_github():
    return github_store._configured()


def _load_all():
    if use_github():
        content, _ = github_store.get_file(PROFILES_PATH)
        if content:
            try:
                return json.loads(content.decode("utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}
    if os.path.exists(LOCAL_PROFILES_FILE):
        try:
            with open(LOCAL_PROFILES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_all(profiles, message):
    if use_github():
        data = json.dumps(profiles, indent=2, ensure_ascii=False).encode("utf-8")
        github_store.put_file(PROFILES_PATH, data, message)
    else:
        os.makedirs(os.path.dirname(LOCAL_PROFILES_FILE), exist_ok=True)
        with open(LOCAL_PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)


def get_profile(username):
    profiles = _load_all()
    profile = dict(DEFAULT_PROFILE)
    profile.update(profiles.get(username, {}))
    return profile


def update_profile(username, full_name, bio, email):
    profiles = _load_all()
    profile = dict(DEFAULT_PROFILE)
    profile.update(profiles.get(username, {}))
    profile["full_name"] = (full_name or "").strip()
    profile["bio"] = (bio or "").strip()
    profile["email"] = (email or "").strip()
    profiles[username] = profile
    _save_all(profiles, f"Update profile: {username}")
    return profile


def save_avatar(username, file_storage):
    """Save an uploaded avatar image. Returns the stored avatar key (e.g. 'visual.png')."""
    filename = file_storage.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_AVATAR_EXT:
        raise ValueError("এই ফরম্যাট সাপোর্ট করে না। PNG, JPG বা WEBP ব্যবহার করুন।")

    data = file_storage.read()
    if not data:
        raise ValueError("ছবিটা খালি বা পড়া যায়নি।")
    if len(data) > MAX_AVATAR_BYTES:
        raise ValueError("ছবির সাইজ ৪ MB এর বেশি হতে পারবে না।")

    avatar_key = f"{username}.{ext}"

    if use_github():
        github_store.put_file(f"{AVATAR_DIR}/{avatar_key}", data, f"Update avatar: {username}")
    else:
        os.makedirs(LOCAL_AVATAR_DIR, exist_ok=True)
        with open(os.path.join(LOCAL_AVATAR_DIR, avatar_key), "wb") as f:
            f.write(data)

    mimetype = mimetypes.guess_type(avatar_key)[0] or "image/png"
    _avatar_cache[username] = (data, mimetype)

    profiles = _load_all()
    profile = dict(DEFAULT_PROFILE)
    profile.update(profiles.get(username, {}))
    profile["avatar"] = avatar_key
    profiles[username] = profile
    _save_all(profiles, f"Update avatar: {username}")
    return avatar_key


def get_avatar_bytes(username):
    """Return (bytes, mimetype) for a user's avatar, or (None, None) if none set."""
    if username in _avatar_cache:
        return _avatar_cache[username]

    profile = get_profile(username)
    avatar_key = profile.get("avatar")
    if not avatar_key:
        return None, None

    if use_github():
        content, _ = github_store.get_file(f"{AVATAR_DIR}/{avatar_key}")
    else:
        path = os.path.join(LOCAL_AVATAR_DIR, avatar_key)
        content = None
        if os.path.exists(path):
            with open(path, "rb") as f:
                content = f.read()

    if content is None:
        return None, None

    mimetype = mimetypes.guess_type(avatar_key)[0] or "image/png"
    _avatar_cache[username] = (content, mimetype)
    return content, mimetype
