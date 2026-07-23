"""
Small persisted app-wide settings — currently just Maintenance Mode.

Same GitHub-or-local pattern as auth.py / profiles.py (see github_store.py)
so the setting survives Render redeploys instead of living only on the
ephemeral disk. Falls back to a local JSON file under data/ when
GITHUB_TOKEN / GITHUB_REPO aren't set (fine for local testing).
"""
import json
import os

import github_store

BASE_DIR = os.path.dirname(__file__)
SETTINGS_FILE = os.path.join(BASE_DIR, "data", "settings.json")
SETTINGS_PATH_REPO = "data/settings.json"  # path inside the repo's app-data branch

_DEFAULTS = {"maintenance": False, "maintenance_message": ""}


def _load():
    if github_store._configured():
        content, _ = github_store.get_file(SETTINGS_PATH_REPO)
        if content:
            try:
                data = json.loads(content.decode("utf-8"))
                return {**_DEFAULTS, **data}
            except json.JSONDecodeError:
                print("WARNING: data/settings.json on GitHub is not valid JSON")
        return dict(_DEFAULTS)

    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return {**_DEFAULTS, **json.load(f)}
        except (json.JSONDecodeError, OSError):
            print(f"WARNING: could not read {SETTINGS_FILE} — using defaults.")

    return dict(_DEFAULTS)


def _save(data, message):
    if github_store._configured():
        github_store.put_file(
            SETTINGS_PATH_REPO,
            json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"),
            message,
        )
    else:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def is_maintenance_on():
    return bool(_load().get("maintenance"))


def get_maintenance_message():
    return _load().get("maintenance_message") or ""


def set_maintenance(on, message=""):
    """Turn maintenance mode on/off, with an optional message shown to
    blocked users on the login page and (for anyone already logged in)
    on the maintenance screen."""
    data = _load()
    data["maintenance"] = bool(on)
    data["maintenance_message"] = (message or "").strip()
    _save(data, f"Maintenance mode {'ON' if on else 'OFF'}")
