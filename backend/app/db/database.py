# -*- coding: utf-8 -*-
"""SQLite 仓储层。

单一事实来源:文件系统 `projects/<slug>/` 存定义/方案/流程图/需求/上传件;
DB 只存**索引 · 状态 · 权限 · 凭据 · 审计**,避免双写不一致。
原生 sqlite3,无 ORM 依赖。
"""
import json
import os
import sqlite3
import time

from ..core import config as C

_STATUSES = ("draft", "planned", "flowcharted", "designed", "deployed", "failed")
DOC_KINDS = ("existing_system", "requirement", "meeting", "other")
ROLES = ("admin", "designer", "viewer")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  display_name TEXT DEFAULT '',
  role TEXT NOT NULL DEFAULT 'designer',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  app_code TEXT DEFAULT '',
  engine_code TEXT DEFAULT '',
  h3_token TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft',
  owner_id INTEGER DEFAULT 0,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS project_members (
  project_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL DEFAULT 'viewer',
  created_at TEXT,
  PRIMARY KEY (project_id, user_id)
);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER,
  kind TEXT NOT NULL DEFAULT 'other',
  filename TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  ext TEXT DEFAULT '',
  size INTEGER DEFAULT 0,
  parsed_text TEXT DEFAULT '',
  summary TEXT DEFAULT '',
  tags TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'uploaded',
  uploaded_by TEXT DEFAULT '',
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT DEFAULT '',
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  detail TEXT DEFAULT '',
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER,
  kind TEXT,
  message TEXT,
  created_at TEXT
);
"""


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def connect():
    os.makedirs(C.DATA_DIR, exist_ok=True)
    c = sqlite3.connect(C.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = connect()
    try:
        c.executescript(_SCHEMA)
        c.commit()
    finally:
        c.close()


def _row(r):
    return dict(r) if r is not None else None


def _rows(rs):
    return [dict(r) for r in rs]


# ================================================================ users
def create_user(email, password_hash, role="designer", display_name=""):
    now = _now()
    c = connect()
    try:
        cur = c.execute("INSERT INTO users(email,password_hash,display_name,role,active,"
                        "created_at,updated_at) VALUES(?,?,?,?,1,?,?)",
                        (email.lower().strip(), password_hash, display_name or email, role,
                         now, now))
        c.commit()
        return get_user_by_id(cur.lastrowid)
    finally:
        c.close()


def get_user_by_email(email):
    c = connect()
    try:
        return _row(c.execute("SELECT * FROM users WHERE email=?",
                              ((email or "").lower().strip(),)).fetchone())
    finally:
        c.close()


def get_user_by_id(uid):
    c = connect()
    try:
        return _row(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    finally:
        c.close()


def get_user(uid):
    return get_user_by_id(uid)


def list_users():
    c = connect()
    try:
        return _rows(c.execute("SELECT id,email,display_name,role,active,created_at "
                               "FROM users ORDER BY id").fetchall())
    finally:
        c.close()


def update_user(uid, **fields):
    fields["updated_at"] = _now()
    cols = ", ".join("%s=?" % k for k in fields)
    c = connect()
    try:
        c.execute("UPDATE users SET %s WHERE id=?" % cols, list(fields.values()) + [uid])
        c.commit()
        return get_user_by_id(uid)
    finally:
        c.close()


def delete_user(uid):
    c = connect()
    try:
        c.execute("DELETE FROM users WHERE id=?", (uid,))
        c.execute("DELETE FROM project_members WHERE user_id=?", (uid,))
        c.commit()
    finally:
        c.close()


def count_users():
    c = connect()
    try:
        return c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    finally:
        c.close()


# ================================================================ projects
def create_project(slug, title, app_code="", engine_code="", h3_token="", owner_id=0):
    now = _now()
    c = connect()
    try:
        cur = c.execute("INSERT INTO projects(slug,title,app_code,engine_code,h3_token,"
                        "status,owner_id,created_at,updated_at) VALUES(?,?,?,?,?,'draft',?,?,?)",
                        (slug, title, app_code, engine_code, h3_token, owner_id, now, now))
        c.commit()
        return get_project(cur.lastrowid)
    finally:
        c.close()


def get_project(pid):
    c = connect()
    try:
        return _row(c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
    finally:
        c.close()


def get_project_by_slug(slug):
    c = connect()
    try:
        return _row(c.execute("SELECT * FROM projects WHERE slug=?", (slug,)).fetchone())
    finally:
        c.close()


def list_projects(owner_id=None, member_of=None):
    c = connect()
    try:
        if owner_id is not None:
            return _rows(c.execute("SELECT * FROM projects WHERE owner_id=? "
                                   "ORDER BY updated_at DESC", (owner_id,)).fetchall())
        if member_of is not None:
            return _rows(c.execute(
                "SELECT DISTINCT p.* FROM projects p LEFT JOIN project_members m "
                "ON m.project_id=p.id WHERE p.owner_id=? OR m.user_id=? "
                "ORDER BY p.updated_at DESC", (member_of, member_of)).fetchall())
        return _rows(c.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall())
    finally:
        c.close()


def update_project(pid, **fields):
    fields["updated_at"] = _now()
    cols = ", ".join("%s=?" % k for k in fields)
    c = connect()
    try:
        c.execute("UPDATE projects SET %s WHERE id=?" % cols, list(fields.values()) + [pid])
        c.commit()
        return get_project(pid)
    finally:
        c.close()


def delete_project(pid):
    c = connect()
    try:
        c.execute("DELETE FROM projects WHERE id=?", (pid,))
        c.execute("DELETE FROM project_members WHERE project_id=?", (pid,))
        c.execute("DELETE FROM events WHERE project_id=?", (pid,))
        c.execute("DELETE FROM documents WHERE project_id=?", (pid,))
        c.commit()
    finally:
        c.close()


# ================================================================ members
def set_member(project_id, user_id, role="viewer"):
    c = connect()
    try:
        c.execute("INSERT INTO project_members(project_id,user_id,role,created_at) "
                  "VALUES(?,?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role",
                  (project_id, user_id, role, _now()))
        c.commit()
    finally:
        c.close()


def project_member_role(project_id, user_id):
    c = connect()
    try:
        r = c.execute("SELECT role FROM project_members WHERE project_id=? AND user_id=?",
                      (project_id, user_id)).fetchone()
        return r["role"] if r else None
    finally:
        c.close()


def list_members(project_id):
    c = connect()
    try:
        return _rows(c.execute(
            "SELECT m.user_id, m.role, u.email, u.display_name FROM project_members m "
            "LEFT JOIN users u ON u.id=m.user_id WHERE m.project_id=? ORDER BY m.user_id",
            (project_id,)).fetchall())
    finally:
        c.close()


def remove_member(project_id, user_id):
    c = connect()
    try:
        c.execute("DELETE FROM project_members WHERE project_id=? AND user_id=?",
                  (project_id, user_id))
        c.commit()
    finally:
        c.close()


# ================================================================ documents
def add_document(project_id, kind, filename, stored_path, ext, size,
                 parsed_text="", uploaded_by=""):
    now = _now()
    c = connect()
    try:
        cur = c.execute(
            "INSERT INTO documents(project_id,kind,filename,stored_path,ext,size,"
            "parsed_text,status,uploaded_by,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,'uploaded',?,?,?)",
            (project_id, kind, filename, stored_path, ext, size, parsed_text,
             uploaded_by, now, now))
        c.commit()
        return get_document(cur.lastrowid)
    finally:
        c.close()


def get_document(doc_id):
    c = connect()
    try:
        return _row(c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())
    finally:
        c.close()


def list_documents(project_id=None, kind=None, limit=500):
    c = connect()
    try:
        sql, args = "SELECT * FROM documents WHERE 1=1", []
        if project_id is not None:
            sql += " AND project_id=?"
            args.append(project_id)
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return _rows(c.execute(sql, args).fetchall())
    finally:
        c.close()


def update_document(doc_id, **fields):
    fields["updated_at"] = _now()
    cols = ", ".join("%s=?" % k for k in fields)
    c = connect()
    try:
        c.execute("UPDATE documents SET %s WHERE id=?" % cols, list(fields.values()) + [doc_id])
        c.commit()
        return get_document(doc_id)
    finally:
        c.close()


def delete_document(doc_id):
    doc = get_document(doc_id)
    c = connect()
    try:
        c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        c.commit()
    finally:
        c.close()
    if doc and doc.get("stored_path") and os.path.isfile(doc["stored_path"]):
        try:
            os.remove(doc["stored_path"])
        except Exception:
            pass
    return doc


# ================================================================ settings
def get_setting(key, default=None):
    c = connect()
    try:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not r:
            return default
        try:
            return json.loads(r["value"])
        except Exception:
            return r["value"]
    finally:
        c.close()


def put_setting(key, value):
    c = connect()
    try:
        c.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                  (key, json.dumps(value, ensure_ascii=False), _now()))
        c.commit()
    finally:
        c.close()


def all_settings():
    c = connect()
    try:
        out = {}
        for r in c.execute("SELECT key,value FROM settings").fetchall():
            try:
                out[r["key"]] = json.loads(r["value"])
            except Exception:
                out[r["key"]] = r["value"]
        return out
    finally:
        c.close()


# ================================================================ jobs / events
def add_job(kind, detail=""):
    now = _now()
    c = connect()
    try:
        cur = c.execute("INSERT INTO jobs(kind,status,detail,created_at,updated_at) "
                        "VALUES(?,'running',?,?,?)", (kind, detail, now, now))
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def finish_job(job_id, status="done", detail=""):
    c = connect()
    try:
        c.execute("UPDATE jobs SET status=?, detail=?, updated_at=? WHERE id=?",
                  (status, (detail or "")[:4000], _now(), job_id))
        c.commit()
    finally:
        c.close()


def list_jobs(limit=50):
    c = connect()
    try:
        return _rows(c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?",
                               (limit,)).fetchall())
    finally:
        c.close()


def add_event(project_id, kind, message):
    c = connect()
    try:
        c.execute("INSERT INTO events(project_id,kind,message,created_at) VALUES(?,?,?,?)",
                  (project_id, kind, (message or "")[:2000], _now()))
        c.commit()
    finally:
        c.close()


def list_events(project_id, limit=50):
    c = connect()
    try:
        return _rows(c.execute("SELECT * FROM events WHERE project_id=? "
                               "ORDER BY id DESC LIMIT ?", (project_id, limit)).fetchall())
    finally:
        c.close()
