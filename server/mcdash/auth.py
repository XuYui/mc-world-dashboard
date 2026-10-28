"""Logging in with the game account: name + the password used for /login (AuthMe).

AuthMe's database is opened read-only and only its bcrypt hash is compared; the password itself is
never stored or logged. A successful login gives a random session token (an HttpOnly cookie) that
lives in memory, so restarting the dashboard logs everyone out. Failed attempts are rate limited
per account and per address.
"""
import secrets
import sqlite3
import threading
import time

from . import config

try:
    import bcrypt
except ImportError:          # the page still works; logging in is just unavailable
    bcrypt = None

SESSION_SECONDS = 7 * 86400
FAIL_WINDOW = 15 * 60
FAIL_LIMIT = 5

_lock = threading.Lock()
_sessions = {}               # token -> (name, uuid, expires)
_fails = {}                  # key -> [timestamps]


def available():
    return bcrypt is not None


def _hash_of(name):
    con = sqlite3.connect("file:%s?mode=ro" % config.AUTHME_DB, uri=True, timeout=5)
    try:
        row = con.execute("SELECT password FROM authme WHERE username = ?", (name.lower(),)).fetchone()
    finally:
        con.close()
    return row[0] if row else None


def check_password(name, password):
    if bcrypt is None or not password:
        return False
    h = _hash_of(name)
    if not h or not h.startswith(("$2a$", "$2b$", "$2y$")):
        return False
    h = "$2b$" + h[4:]           # PHP-style $2y$ is the same algorithm
    try:
        return bcrypt.checkpw(password.encode("utf-8"), h.encode("ascii"))
    except ValueError:
        return False


def _recent(key, now):
    lst = [t for t in _fails.get(key, []) if now - t < FAIL_WINDOW]
    _fails[key] = lst
    return lst


def blocked(name, addr):
    """Seconds to wait before another attempt for this account or address (0 = allowed)."""
    now = time.time()
    with _lock:
        waits = []
        for key in ("n:" + name.lower(), "a:" + addr):
            lst = _recent(key, now)
            if len(lst) >= FAIL_LIMIT:
                waits.append(FAIL_WINDOW - (now - lst[0]))
        return int(max(waits)) + 1 if waits else 0


def failed(name, addr):
    now = time.time()
    with _lock:
        for key in ("n:" + name.lower(), "a:" + addr):
            _recent(key, now).append(now)


def login(name, uuid):
    token = secrets.token_urlsafe(32)
    with _lock:
        now = time.time()
        for t in [t for t, s in _sessions.items() if s[2] < now]:
            del _sessions[t]
        _sessions[token] = (name, uuid, now + SESSION_SECONDS)
    return token


def logout(token):
    with _lock:
        _sessions.pop(token, None)


def who(token):
    """(name, uuid) for a valid session token, else None."""
    if not token:
        return None
    with _lock:
        s = _sessions.get(token)
        if not s or s[2] < time.time():
            _sessions.pop(token, None)
            return None
        return s[0], s[1]
