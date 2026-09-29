import json
import sqlite3
import threading
import time
import uuid
import win32crypt
from .config import data_dir


def encrypt(value):
    return win32crypt.CryptProtectData(json.dumps(value, ensure_ascii=False).encode("utf-8"), "Desktop AI Assistant", None, None, None, 1)


def decrypt(value):
    return json.loads(win32crypt.CryptUnprotectData(value, None, None, None, 1)[1])


class History:
    db: sqlite3.Connection
    lock: threading.RLock

    def __init__(self, path=None):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path or data_dir() / "history.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created REAL, status TEXT, payload BLOB)")
        self.db.execute("UPDATE jobs SET status='interrupted' WHERE status IN ('running', 'writing')")
        self.db.commit()

    def create(self, payload):
        job = uuid.uuid4().hex
        with self.lock, self.db:
            self.db.execute("INSERT INTO jobs VALUES(?,?,?,?)", (job, time.time(), "running", encrypt(payload)))
        return job

    def update(self, job, status, **fields):
        with self.lock, self.db:
            row = self.db.execute("SELECT payload FROM jobs WHERE id=?", (job,)).fetchone()
            if row is None:
                raise ValueError("History entry no longer exists")
            payload = decrypt(row[0])
            payload.update(fields)
            self.db.execute("UPDATE jobs SET status=?,payload=? WHERE id=?", (status, encrypt(payload), job))

    def entries(self):
        with self.lock:
            return [dict(id=row[0], created=row[1], status=row[2], **decrypt(row[3])) for row in self.db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT 250")]

    def get(self, job):
        return next(x for x in self.entries() if x["id"] == job)

    def prune(self, days):
        with self.lock, self.db:
            self.db.execute("DELETE FROM jobs WHERE created < ?", (time.time() - days * 86400,))
            self.db.execute("DELETE FROM jobs WHERE id NOT IN (SELECT id FROM jobs ORDER BY created DESC LIMIT 1000)")

    def clear(self):
        with self.lock, self.db:
            self.db.execute("DELETE FROM jobs")
