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
import uuid

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
  avatar TEXT DEFAULT '',
  activation_token TEXT DEFAULT '',
  activation_expires INTEGER DEFAULT 0,
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
  ref_items TEXT DEFAULT '[]',
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS project_members (
  project_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL DEFAULT 'viewer',
  created_at TEXT,
  PRIMARY KEY (project_id, user_id)
);
CREATE TABLE IF NOT EXISTS library_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  description TEXT DEFAULT '',
  analysis TEXT DEFAULT '',
  analysis_at TEXT DEFAULT '',
  analysis_error TEXT DEFAULT '',
  created_by INTEGER DEFAULT 0,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER,
  library_id INTEGER,
  kind TEXT NOT NULL DEFAULT 'other',
  filename TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  ext TEXT DEFAULT '',
  size INTEGER DEFAULT 0,
  parsed_text TEXT DEFAULT '',
  summary TEXT DEFAULT '',
  tags TEXT DEFAULT '',
  extract_json TEXT DEFAULT '',
  extract_status TEXT DEFAULT '',
  extract_at TEXT DEFAULT '',
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
  title TEXT DEFAULT '',
  variant TEXT DEFAULT '',
  project_id INTEGER DEFAULT 0,
  user_id INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'running',
  progress TEXT DEFAULT '[]',
  result TEXT DEFAULT '',
  error TEXT DEFAULT '',
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
    c = sqlite3.connect(C.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=30000")   # 后台任务与请求并发写时不立刻报 locked
        # WAL:读写并发(任务线程写进度时不阻塞请求读)。已为 WAL 时该语句只读不回写,
        # 无锁开销,可安全地在每次连接兜底设置;并发多实例也能各自完成一次转换。
        c.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return c


def init_db():
    c = connect()
    try:
        try:
            c.execute("PRAGMA journal_mode=WAL")   # 允许读写并发(任务线程写进度)
        except Exception:
            pass
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
        return _rows(c.execute("SELECT id,email,display_name,role,active,avatar,password_hash,"
                               "activation_token,created_at FROM users ORDER BY id").fetchall())
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
    """创建项目。`slug` 为空时由系统按主键生成序列号(proj_0001…)作为目录名。"""
    now = _now()
    c = connect()
    try:
        auto = not (slug or "").strip()
        if auto:
            slug = "tmp_" + uuid.uuid4().hex      # 占位,保证 UNIQUE 成立
        cur = c.execute("INSERT INTO projects(slug,title,app_code,engine_code,h3_token,"
                        "status,owner_id,created_at,updated_at) VALUES(?,?,?,?,?,'draft',?,?,?)",
                        (slug, title, app_code, engine_code, h3_token, owner_id, now, now))
        pid = cur.lastrowid
        if auto:
            slug = "proj_%04d" % pid
            c.execute("UPDATE projects SET slug=? WHERE id=?", (slug, pid))
        c.commit()
        return get_project(pid)
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
                 parsed_text="", uploaded_by="", library_id=None):
    now = _now()
    c = connect()
    try:
        cur = c.execute(
            "INSERT INTO documents(project_id,library_id,kind,filename,stored_path,ext,size,"
            "parsed_text,status,uploaded_by,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,'uploaded',?,?,?)",
            (project_id, library_id, kind, filename, stored_path, ext, size, parsed_text,
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


# ================================================================ 全局资料库
def create_library_item(name, description="", created_by=0):
    now = _now()
    c = connect()
    try:
        cur = c.execute("INSERT INTO library_items(name,description,created_by,created_at,updated_at) "
                        "VALUES(?,?,?,?,?)", (name.strip(), description or "", created_by, now, now))
        c.commit()
        return get_library_item(cur.lastrowid)
    finally:
        c.close()


def get_library_item(item_id):
    c = connect()
    try:
        return _row(c.execute("SELECT * FROM library_items WHERE id=?", (item_id,)).fetchone())
    finally:
        c.close()


def get_library_item_by_name(name):
    c = connect()
    try:
        return _row(c.execute("SELECT * FROM library_items WHERE name=?", ((name or "").strip(),)).fetchone())
    finally:
        c.close()


def list_library_items():
    c = connect()
    try:
        return _rows(c.execute("SELECT * FROM library_items ORDER BY id DESC").fetchall())
    finally:
        c.close()


def update_library_item(item_id, **fields):
    fields["updated_at"] = _now()
    cols = ", ".join("%s=?" % k for k in fields)
    c = connect()
    try:
        c.execute("UPDATE library_items SET %s WHERE id=?" % cols, list(fields.values()) + [item_id])
        c.commit()
        return get_library_item(item_id)
    finally:
        c.close()


def delete_library_item(item_id):
    c = connect()
    try:
        c.execute("DELETE FROM library_items WHERE id=?", (item_id,))
        c.execute("DELETE FROM documents WHERE library_id=?", (item_id,))
        c.commit()
    finally:
        c.close()


def list_library_documents(library_id):
    """某个资料下的全部文档。"""
    c = connect()
    try:
        return _rows(c.execute("SELECT * FROM documents WHERE library_id=? ORDER BY id",
                               (library_id,)).fetchall())
    finally:
        c.close()


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
def add_job(kind, detail="", project_id=0, user_id=0, title="", variant=""):
    now = _now()
    c = connect()
    try:
        cur = c.execute(
            "INSERT INTO jobs(kind,title,variant,project_id,user_id,status,detail,created_at,updated_at) "
            "VALUES(?,?,?,?,?,'running',?,?,?)",
            (kind, title, variant, project_id, user_id, detail, now, now))
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def create_job(kind, project_id=0, user_id=0, title="", detail="", variant="") -> dict:
    jid = add_job(kind, detail=detail, project_id=project_id, user_id=user_id,
                  title=title, variant=variant)
    return get_job(jid)


def get_job(job_id):
    c = connect()
    try:
        return _row(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    finally:
        c.close()


def find_active_job(project_id, kind):
    """某项目某类型当前正在运行的任务(用于幂等:已有则复用,避免重复触发)。"""
    c = connect()
    try:
        return _row(c.execute(
            "SELECT * FROM jobs WHERE project_id=? AND kind=? AND status='running' "
            "ORDER BY id DESC LIMIT 1", (project_id, kind)).fetchone())
    finally:
        c.close()


def list_project_jobs(project_id, limit=30, active_only=False):
    c = connect()
    try:
        sql = "SELECT * FROM jobs WHERE project_id=?"
        if active_only:
            sql += " AND status='running'"
        sql += " ORDER BY id DESC LIMIT ?"
        return _rows(c.execute(sql, (project_id, limit)).fetchall())
    finally:
        c.close()


def append_job_progress(job_id, text, level="info", pct=None):
    """向任务追加一条进度明细(JSON 数组,保留最近 200 条)。"""
    c = connect()
    try:
        r = c.execute("SELECT progress FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not r:
            return
        try:
            items = json.loads(r["progress"] or "[]")
        except Exception:
            items = []
        items.append({"ts": _now(), "level": level, "text": text, "pct": pct})
        items = items[-200:]
        c.execute("UPDATE jobs SET progress=?, updated_at=? WHERE id=?",
                  (json.dumps(items, ensure_ascii=False), _now(), job_id))
        c.commit()
    finally:
        c.close()


def finish_job(job_id, status="done", detail="", result=None, error=""):
    c = connect()
    try:
        c.execute("UPDATE jobs SET status=?, detail=?, result=?, error=?, updated_at=? WHERE id=?",
                  (status, (detail or "")[:4000],
                   json.dumps(result, ensure_ascii=False, default=str) if result is not None else "",
                   (error or "")[:4000], _now(), job_id))
        c.commit()
    finally:
        c.close()


def reap_stale_jobs(project_id=None, ttl_minutes=30):
    """看门狗:把长时间未更新进度的 running 任务标记失败。

    任务跑在进程内线程里;若 runner 卡死且不再上报进度,updated_at 便停止刷新,
    超过 ttl 即视为卡死并释放「同项目同 kind 唯一运行」的占用,使前端可重新触发。
    正常执行的任务每次上报进度都会刷新 updated_at,不会被误判。
    """
    cutoff = time.strftime("%Y-%m-%d %H:%M:%S",
                           time.localtime(time.time() - max(1, ttl_minutes) * 60))
    c = connect()
    try:
        sql = ("UPDATE jobs SET status='failed', error=?, updated_at=? "
               "WHERE status='running' AND updated_at < ?")
        args = ["任务超时(超过 %d 分钟无进度),已终止" % ttl_minutes, _now(), cutoff]
        if project_id is not None:
            sql += " AND project_id=?"
            args.append(project_id)
        c.execute(sql, args)
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


def fail_orphan_jobs(reason="服务重启,任务中断"):
    """启动时把残留的 running 任务标记失败。

    任务跑在进程内线程池,进程重启后这些任务已不存在;若不清理,前端会永远
    显示「处理中」。(单进程部署假设;多 worker 场景下请勿在启动时调用。)
    """
    c = connect()
    try:
        c.execute("UPDATE jobs SET status='failed', error=?, updated_at=? "
                  "WHERE status='running'", (reason, _now()))
        c.commit()
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
