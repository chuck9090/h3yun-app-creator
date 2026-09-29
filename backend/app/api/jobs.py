# -*- coding: utf-8 -*-
"""任务路由:轮询查询异步生成/核对任务的进度与结果。

  GET /api/active-jobs                     我可见的运行中任务(跨项目)
  GET /api/projects/{id}/jobs?active=1&limit=30   项目任务列表(active=1 仅运行中)
  GET /api/jobs/{job_id}                   单个任务(含进度明细/结果)

注意:`GET /api/jobs`(管理员任务总表)已由 system.py 提供,故这里的跨项目查询
须另用 `/api/active-jobs`,避免与其路径冲突。
前端据此在切页/刷新后恢复「处理中」状态,并展示进度明细。
"""
from fastapi import APIRouter, Depends, HTTPException

from ..core import deps
from ..db import database as db
from ..services import jobs as jobs_service

router = APIRouter(prefix="/api", tags=["jobs"])


def _ok(data=None, message=""):
    return {"ok": True, "data": data if data is not None else {}, "message": message}


@router.get("/active-jobs")
def my_active_jobs(limit: int = 50, user=Depends(deps.require_user)):
    """当前用户可见的**运行中**任务(跨项目)。

    用于刷新页面后重新发现「处理中」的任务并恢复进度显示;管理员不限项目。
    """
    if user.get("role") == "admin":
        pids = None
    else:
        pids = [p["id"] for p in db.list_projects(owner_id=user["id"], member_of=user["id"])]
    return _ok({"items": jobs_service.active_jobs(pids, limit=limit)})


@router.get("/projects/{id}/jobs")
def project_jobs(id: int, active: int = 0, limit: int = 30,
                 user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    items = jobs_service.project_jobs(p["id"], limit=limit, active_only=bool(active))
    return _ok({"items": items})


@router.get("/jobs/{job_id}")
def get_job(job_id: int, user=Depends(deps.require_user)):
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "任务不存在")
    pid = j.get("project_id") or 0
    if pid:
        deps.get_project(pid, user)          # 校验对该项目的访问权
    elif user.get("role") != "admin":
        raise HTTPException(403, "无权查看该任务")
    return _ok(jobs_service.job_public(j))
