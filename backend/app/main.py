# -*- coding: utf-8 -*-
"""h3yun-app-creator 后端入口(FastAPI)。

    python -X utf8 -m uvicorn app.main:app --host localhost --port 8000 --reload

产物:API 文档 /docs;前端为独立工程(frontend/),本服务不托管静态资源。
"""
import os
import sqlite3
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.core import config as C          # noqa: E402
from app.core import security as sec      # noqa: E402
from app.db import database as db         # noqa: E402
from app.services import nightly          # noqa: E402
from app.services.jobs import JobConflict  # noqa: E402

app = FastAPI(title="氚云应用生成平台 API", version="2.0.0",
              description="氚云应用生成流水线:需求 → 方案 → 流程图 → ER → 生成应用")

app.add_middleware(
    CORSMiddleware,
    allow_origins=C.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _add_cols(c, table, cols):
    """幂等补列。

    并发多实例(或误启多个进程)同时启动时,"读 PRAGMA 时列不存在、随后 ALTER" 存在竞态:
    另一个进程可能已抢先加列,导致本进程 ALTER 报 `duplicate column name`。
    这里把该错误视为"已迁移"忽略,避免启动阶段异常把 worker 卡死(历史故障根因)。
    """
    have = {r["name"] for r in c.execute("PRAGMA table_info(%s)" % table).fetchall()}
    for name, ddl in cols:
        if name in have:
            continue
        try:
            c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, ddl))
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise


def run_migrations():
    """幂等迁移:建表 + 补列(users.token_version 会话失效;projects.engine_code;jobs 任务字段)。"""
    db.init_db()
    c = db.connect()
    try:
        _add_cols(c, "users", [("token_version", "INTEGER DEFAULT 0"),
                               ("avatar", "TEXT DEFAULT ''"),
                               ("activation_token", "TEXT DEFAULT ''"),
                               ("activation_expires", "INTEGER DEFAULT 0")])
        _add_cols(c, "projects", [("engine_code", "TEXT DEFAULT ''"),
                                  ("ref_items", "TEXT DEFAULT '[]'")])
        _add_cols(c, "documents", [("library_id", "INTEGER"),
                                   ("extract_json", "TEXT DEFAULT ''"),
                                   ("extract_status", "TEXT DEFAULT ''"),
                                   ("extract_at", "TEXT DEFAULT ''")])
        _add_cols(c, "jobs", [("title", "TEXT DEFAULT ''"), ("variant", "TEXT DEFAULT ''"),
                              ("project_id", "INTEGER DEFAULT 0"), ("user_id", "INTEGER DEFAULT 0"),
                              ("progress", "TEXT DEFAULT '[]'"), ("result", "TEXT DEFAULT ''"),
                              ("error", "TEXT DEFAULT ''")])
        c.commit()
    finally:
        c.close()


@app.on_event("startup")
def _startup():
    run_migrations()
    # 进程重启后,残留的 running 任务(线程已不存在)标记为失败,避免前端卡在「处理中」。
    # 多 worker 部署须设 H3AC_FAIL_ORPHAN_JOBS=0,否则新 worker 会误杀其它 worker 正在跑的任务。
    if C.FAIL_ORPHAN_JOBS:
        try:
            db.fail_orphan_jobs()
        except Exception:
            pass
    # 仅当显式设置 H3AC_ADMIN_PASSWORD 时才自动创建管理员,且绝不打印明文口令。
    if db.count_users() == 0 and C.ADMIN_PASSWORD:
        try:
            db.create_user(C.ADMIN_EMAIL, sec.hash_password(C.ADMIN_PASSWORD),
                           role="admin", display_name="管理员")
            print("=" * 60)
            print("  已创建管理员:%s" % C.ADMIN_EMAIL)
            print("  请用环境变量 H3AC_ADMIN_PASSWORD 的值登录")
            print("=" * 60)
        except Exception:
            pass
    corpus = os.path.join(C.KNOWLEDGE_DIR, "corpus.json")
    if not os.path.isfile(corpus):
        try:
            from app import engine_bridge as EB
            EB.refresh_knowledge()
        except Exception:
            pass
    nightly.start_scheduler()


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"ok": False, "message": str(exc)[:500]})


@app.exception_handler(JobConflict)
async def _job_conflict(_: Request, exc: JobConflict):
    return JSONResponse(status_code=409, content={"ok": False, "message": str(exc)})


@app.get("/")
def root():
    return {"ok": True, "name": "氚云应用生成平台 API", "version": "2.0.0", "docs": "/docs"}


from app.api import include_routers      # noqa: E402
include_routers(app)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8000)
