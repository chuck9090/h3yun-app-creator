# -*- coding: utf-8 -*-
"""异步任务执行器。

把长耗时的生成/核对动作放到后台线程执行,进度与结果写库(见 database.jobs),
供前端轮询查询;这样切成其他页面 / 刷新 / 关掉再回来都能恢复「处理中」状态。

关键约束:
- **幂等**:同一项目同一 kind 若已有 running 任务,且 `variant` 一致,则复用该任务、
  不再新建(避免重复点击造成重复调用 LLM / 重复建表);若 `variant` 不一致(例如
  「普通部署」与「强制重存 force」),则抛 JobConflict,绝不静默顶替高危操作语义。
- **看门狗**:提交/查询前清理超时未更新进度的 running 任务(见 database.reap_stale_jobs),
  避免任务卡死后该项目该动作永久无法重试。
- 线程内不再依赖 FastAPI 的 request / Depends,所需数据(runner 闭包)在提交前捕获。
- runner 接收一个 `progress(text, level="info", pct=None)` 回调用于上报明细。
  返回值约定:dict 结果写库;可选键 `_detail` 作为任务结束摘要,会从结果中移除。
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from ..core import config as C
from ..db import database as db

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="h3-job")
_lock = threading.Lock()


class JobConflict(Exception):
    """同项目同 kind 已有 running 任务,但本次请求参数(variant)不同。"""


KIND_TITLES = {
    "plan": "生成系统设计方案",
    "flowchart": "生成业务流程图",
    "design": "生成 ER 结构",
    "deploy": "生成氚云应用",
    "verify": "回读核对",
}


def job_public(job) -> dict:
    """DB 行 → 对外视图(解析 progress/result 的 JSON)。"""
    if not job:
        return None
    try:
        progress = json.loads(job.get("progress") or "[]")
    except Exception:
        progress = []
    raw_result = job.get("result") or ""
    result = None
    if raw_result:
        try:
            result = json.loads(raw_result)
        except Exception:
            result = None
    return {
        "id": job["id"], "kind": job.get("kind", ""), "title": job.get("title", ""),
        "projectId": job.get("project_id", 0), "userId": job.get("user_id", 0),
        "status": job.get("status", ""), "progress": progress,
        "result": result, "error": job.get("error", ""), "detail": job.get("detail", ""),
        "createdAt": job.get("created_at", ""), "updatedAt": job.get("updated_at", ""),
    }


def active_job(project_id, kind):
    db.reap_stale_jobs(project_id=project_id, ttl_minutes=C.JOB_TIMEOUT_MIN)
    return job_public(db.find_active_job(project_id, kind))


def project_jobs(project_id, limit=30, active_only=False):
    db.reap_stale_jobs(project_id=project_id, ttl_minutes=C.JOB_TIMEOUT_MIN)
    return [job_public(j) for j in db.list_project_jobs(project_id, limit, active_only)]


def submit(project_id, user_id, kind, runner, title=None, variant=""):
    """创建并后台执行任务;返回 (job_public, created)。

    - 同项目同 kind 已有 running 且 variant 一致 → 复用(created=False)。
    - variant 不一致 → 抛 JobConflict(如普通部署 vs 强制重存),避免语义被顶替。
    """
    db.reap_stale_jobs(project_id=project_id, ttl_minutes=C.JOB_TIMEOUT_MIN)
    with _lock:
        existing = db.find_active_job(project_id, kind)
        if existing:
            if (existing.get("variant") or "") != (variant or ""):
                raise JobConflict("该项目已有同类任务在运行,请等待其完成后再试")
            return job_public(existing), False
        job_id = db.create_job(kind, project_id=project_id, user_id=user_id,
                               title=title or KIND_TITLES.get(kind, kind),
                               variant=variant)["id"]

    def _progress(text, level="info", pct=None):
        try:
            db.append_job_progress(job_id, text, level=level, pct=pct)
        except Exception:
            pass

    def _run():
        try:
            payload = runner(_progress)
            detail = ""
            if isinstance(payload, dict):
                detail = str(payload.pop("_detail", "") or "")[:2000]
            _progress("任务完成", level="success", pct=100)
            db.finish_job(job_id, "done", detail=detail, result=payload)
        except BaseException as e:
            # 任何异常(含 SystemExit 等)都必须把任务落到终态,否则会永久占位
            try:
                _progress("任务失败:%s" % e, level="error")
            except Exception:
                pass
            try:
                db.finish_job(job_id, "failed", detail=str(e)[:500], error=str(e)[:4000])
            except Exception:
                pass

    _executor.submit(_run)
    return job_public(db.get_job(job_id)), True
