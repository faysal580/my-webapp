"""
Add / update a login user for the Visual Team Console.
=========================================================
Usage:
    python add_user.py

It asks for a username and password, hashes the password, and writes
the result into data/users.json (creating it if needed, merging with
any existing users). For local testing that's all you need — restart
the app and log in.

For Render (or any host with an ephemeral filesystem), copy the
printed APP_USERS value into the service's Environment tab instead,
so it survives redeploys.
"""
import getpass
import json
import os
import sys

from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(__file__)
USERS_FILE = os.path.join(BASE_DIR, "data", "users.json")


def load_existing():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def main():
    username = input("Username: ").strip()
    if not username:
        print("Username can't be empty.")
        sys.exit(1)

    password = getpass.getpass("Password: ").strip()
    confirm = getpass.getpass("Confirm password: ").strip()
    if not password:
        print("Password can't be empty.")
        sys.exit(1)
    if password != confirm:
        print("Passwords don't match.")
        sys.exit(1)

    users = load_existing()
    users[username] = generate_password_hash(password)

    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

    print(f"\nSaved. {USERS_FILE} now has {len(users)} user(s).")
    print("\nFor Render, set this as the APP_USERS environment variable instead")
    print("(Dashboard -> your service -> Environment -> Add Environment Variable):\n")
    print(json.dumps(users, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
