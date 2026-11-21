"""SQLite memory. Each CLI call is a new process, so everything lives here."""
import json
import os
import sqlite3

from . import pack

SCHEMA = """
CREATE TABLE IF NOT EXISTS records(
  id TEXT PRIMARY KEY, org TEXT, type TEXT, at TEXT, author TEXT, client TEXT,
  visibility TEXT, readers TEXT, day INTEGER, suspect INTEGER DEFAULT 0, raw TEXT);
CREATE INDEX IF NOT EXISTS ix_rec_client ON records(client, at);
CREATE TABLE IF NOT EXISTS signals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT, client TEXT, kind TEXT, subject TEXT,
  prio INTEGER, at TEXT, old TEXT, new TEXT, text TEXT, what TEXT);
CREATE INDEX IF NOT EXISTS ix_sig_client ON signals(client, at);
CREATE TABLE IF NOT EXISTS promises(
  id INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT, owner TEXT, what TEXT, due TEXT,
  client TEXT, at TEXT, delivered_by TEXT);
CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, client TEXT, subject TEXT, value TEXT, value_id TEXT,
  at TEXT, record_id TEXT);
CREATE TABLE IF NOT EXISTS prefs(id INTEGER PRIMARY KEY AUTOINCREMENT, person TEXT, day INTEGER, words TEXT);
CREATE TABLE IF NOT EXISTS corrections(
  id INTEGER PRIMARY KEY AUTOINCREMENT, person TEXT, day INTEGER, meeting TEXT, words TEXT,
  client TEXT, subject TEXT, value TEXT, value_id TEXT);
CREATE TABLE IF NOT EXISTS verdicts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, person TEXT, day INTEGER, meeting TEXT, topic TEXT, verdict TEXT, words TEXT);
CREATE TABLE IF NOT EXISTS forgets(id INTEGER PRIMARY KEY AUTOINCREMENT, person TEXT, words TEXT, terms TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def connect(fresh: bool = False) -> sqlite3.Connection:
    path = pack.store_path()
    if fresh and os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def rec_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["readers"] = json.loads(d["readers"] or "[]")
    d["raw"] = json.loads(d["raw"])
    return d


def get_record(conn, rid: str) -> dict | None:
    r = conn.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone()
    return rec_dict(r) if r else None


def meta_get(conn, key, default=None):
    r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def meta_set(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(value)))
