"""Local SQLite store: settings, behaviour events (for learning), presenters, file observations.

Every call opens and closes its own connection, so it is safe across Flask threads.
Events older than RETENTION_DAYS are pruned automatically. Chat text is never stored verbatim.
"""
import json
import sqlite3
import threading
import time
from contextlib import closing

from . import paths

RETENTION_DAYS = 180
_init_lock = threading.Lock()
_initialised = set()

DEFAULTS = {
    "recording_root": None,          # filled lazily with paths.default_recording_root()
    "loudness_target": -16.0,        # LUFS integrated, finished episode
    "true_peak": -1.0,               # dBTP ceiling, finished episode
    "speech_target": -20.0,          # LUFS short-term while speaking, raw recording tracks
    "leveler_enabled": False,        # inline live leveler (Sawti in the signal path)
    "leveler_output": "BlackHole 16ch",
    "auto_prepare": False,           # operator opts in; audio mutations never run automatically
    "autofix": {},                   # action -> True once learned/approved
    "llm_model": "qwen3:4b",
    "source_names": {},              # mode -> {source_id: display name}
    "templates": {},                 # mode -> template path
    "show_name": {"local": "Podcast", "zoom": "Zoom Show"},
    "learning_folder": None,
}


def _db_path():
    return paths.data_dir() / "sawti.sqlite3"


def connect():
    path = _db_path()
    key = str(path)
    conn = sqlite3.connect(path, timeout=10)
    if key not in _initialised:
        with _init_lock:
            if key not in _initialised:
                _migrate_events(conn, path)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
                    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, data TEXT);
                    CREATE INDEX IF NOT EXISTS events_kind ON events(kind, ts);
                    CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                        consent INTEGER NOT NULL DEFAULT 0, embedding TEXT, created REAL);
                    CREATE TABLE IF NOT EXISTS observations(path TEXT PRIMARY KEY, directory TEXT, filename TEXT,
                        suffix TEXT, modified REAL, seen REAL);
                    """
                )
                conn.execute("DELETE FROM events WHERE ts < ?", (time.time() - RETENTION_DAYS * 86400,))
                conn.commit()
                _initialised.add(key)
    return conn


def _migrate_events(conn, path):
    """Preserve the 2.2 database before upgrading its incompatible event schema.

    Never translate old free-text prompt logs into the new learning events.
    The backup is private local data; no database is committed to Git.
    """
    columns = {row[1] for row in conn.execute('PRAGMA table_info(events)')}
    if not columns or {'ts', 'kind', 'data'} <= columns:
        return
    if columns != {'id', 'date', 'category', 'message'}:
        conn.close()
        raise RuntimeError('Unrecognised Sawti database schema; no migration was applied.')
    backup = path.with_name('sawti-before-v3.sqlite3')
    if backup.exists():
        conn.close()
        raise RuntimeError('A pre-upgrade backup already exists. Preserve and review it before retrying migration.')
    with closing(sqlite3.connect(backup)) as saved:
        conn.backup(saved)
    backup.chmod(0o600)
    # Keep a legacy archive table as well as the protected pre-upgrade backup.
    with conn:
        conn.execute('ALTER TABLE events RENAME TO events_v2_2')
        conn.execute('CREATE TABLE events(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, data TEXT)')


# ---------- settings ----------
def get(key, default=None):
    with closing(connect()) as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row:
        return json.loads(row[0])
    if default is not None:
        return default
    if key == "recording_root":
        return str(paths.default_recording_root())
    value = DEFAULTS.get(key)
    return json.loads(json.dumps(value))  # copy


def put(key, value):
    with closing(connect()) as db, db:
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))


def all_settings():
    return {k: get(k) for k in DEFAULTS}


# ---------- events ----------
def log(kind, **data):
    with closing(connect()) as db, db:
        db.execute("INSERT INTO events(ts,kind,data) VALUES (?,?,?)",
                   (time.time(), kind, json.dumps(data, ensure_ascii=False)))


def events(kind=None, since=None, limit=2000):
    q, args = "SELECT ts,kind,data FROM events WHERE 1=1", []
    if kind:
        kinds = [kind] if isinstance(kind, str) else list(kind)
        q += " AND kind IN (%s)" % ",".join("?" * len(kinds))
        args += kinds
    if since:
        q += " AND ts >= ?"
        args.append(since)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    with closing(connect()) as db:
        rows = db.execute(q, args).fetchall()
    return [dict(ts=r[0], kind=r[1], **json.loads(r[2] or "{}")) for r in rows]


def clear_learning():
    with closing(connect()) as db, db:
        db.execute("DELETE FROM events")
        db.execute("DELETE FROM observations")
    put("autofix", {})


# ---------- presenters ----------
def people():
    with closing(connect()) as db:
        rows = db.execute("SELECT id,name,consent,embedding FROM people ORDER BY name").fetchall()
    return [dict(id=r[0], name=r[1], enrolled=bool(r[2] and r[3])) for r in rows]


def add_person(name, consent):
    name = " ".join((name or "").split())
    if not (1 <= len(name) <= 80):
        raise ValueError("Enter a presenter name (1–80 characters).")
    if consent is not True:
        raise ValueError("Tick the consent box: the presenter must agree to a stored voice signature.")
    with closing(connect()) as db, db:
        db.execute("INSERT INTO people(name,consent,created) VALUES (?,?,?) "
                   "ON CONFLICT(name) DO UPDATE SET consent=1", (name, 1, time.time()))


def remove_person(person_id):
    with closing(connect()) as db, db:
        db.execute("DELETE FROM people WHERE id=?", (int(person_id),))


def set_embedding(person_id, vector):
    with closing(connect()) as db, db:
        cur = db.execute("UPDATE people SET embedding=? WHERE id=? AND consent=1",
                         (json.dumps(vector), int(person_id)))
        if cur.rowcount == 0:
            raise ValueError("Add the presenter with consent first.")


def embeddings():
    with closing(connect()) as db:
        rows = db.execute("SELECT name,embedding FROM people WHERE consent=1 AND embedding IS NOT NULL").fetchall()
    return [(r[0], json.loads(r[1])) for r in rows]


# ---------- file observations (learning) ----------
def save_observations(rows):
    with closing(connect()) as db, db:
        db.executemany("INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?,?)", rows)


def observations(limit=3000):
    with closing(connect()) as db:
        return db.execute("SELECT directory,filename,suffix,modified FROM observations "
                          "ORDER BY modified DESC LIMIT ?", (limit,)).fetchall()
