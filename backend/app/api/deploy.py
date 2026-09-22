# -*- coding: utf-8 -*-
"""部署路由(生成氚云应用 / 回读核对 / 凭据状态 / 载荷预览)。契约见 docs/ARCHITECTURE.md §5。

  POST /api/projects/{id}/deploy
  POST /api/projects/{id}/verify
  GET  /api/projects/{id}/credentials/status
  POST /api/projects/{id}/preview  {sheet}

注意:deploy/verify 会真实联网调用氚云;凭据缺失或过期时直接 400 拒绝(绝不回落到根 config.json)。
"""
from fastapi import APIRouter, Depends, HTTPException

from .. import engine_bridge as EB
from .. import storage
from ..core import deps
from ..db import database as db
from ..schemas import pipeline as S
from ..services import jobs as jobs_service

router = APIRouter(prefix="/api", tags=["deploy"])


def _ok(data=None, message=""):
    return {"ok": True, "data": data if data is not None else {}, "message": message}


@router.post("/projects/{id}/deploy")
def deploy(id: int, body: S.DeployIn = None, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    force = bool(body.force) if body else False
    if force and user.get("role") != "admin":
        # force 会整表重存并抹掉界面手工配置(危险);仅管理员可用
        raise HTTPException(403, "强制重存(force)会抹掉线上界面手工配置,仅管理员可用")

    design = storage.get_design(p["slug"])
    if not design.get("sheets"):
        raise HTTPException(400, "尚未生成 ER 结构,无法生成应用")

    # 保证 sheets/*.json 与 automations/*.json 与当前 design.json 一致,并做离线校验
    storage.project_dir(p["slug"], create=True)
    try:
        sync = EB.sync_sheets(p["slug"], design, app_code=p.get("app_code", ""))
    except Exception as e:
        raise HTTPException(400, "表单/自动化定义校验失败:%s" % e)
    if sync.get("error"):
        raise HTTPException(400, "表单/自动化定义校验失败:%s" % sync["error"])

    status = EB.credentials_status(p)
    if not status.get("configured"):
        raise HTTPException(
            400, "氚云凭据未配置或已过期(appCode / h3_token 缺失或无效),无法生成应用")

    slug, pid = p["slug"], p["id"]

    def runner(progress):
        progress("准备部署载荷", pct=5)
        cfg = EB.build_cfg(p)
        res = EB.deploy(slug, cfg, force, progress=progress)
        ok = bool(res.get("all_ok"))
        if ok:
            db.update_project(pid, status="deployed")
        db.add_event(pid, "deploy",
                     "生成氚云应用:%s(表单 %d 张 / 分组 %d 个 / 自动化 %d 条%s)"
                     % ("成功" if ok else "失败", len(res.get("sheets") or []),
                        len(res.get("groups") or []),
                        len(res.get("automations") or []),
                        ", force=true" if force else ""))
        res["_detail"] = ("表单 %d / 分组 %d / 自动化 %d"
                          % (len(res.get("sheets") or []), len(res.get("groups") or []),
                             len(res.get("automations") or [])))
        return res

    job, created = jobs_service.submit(
        pid, user["id"], "deploy", runner,
        title="生成氚云应用(force)" if force else "生成氚云应用",
        variant=("force" if force else "normal"))
    return _ok({"job": job, "created": created})


@router.post("/projects/{id}/verify")
def verify(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    if not EB.credentials_status(p).get("configured"):
        raise HTTPException(400, "氚云凭据未配置或已过期,无法回读核对")
    slug, pid = p["slug"], p["id"]

    def runner(progress):
        res = EB.verify(slug, EB.build_cfg(p), progress=progress)
        db.add_event(pid, "verify", "回读核对:%s" % ("通过" if res.get("all_ok") else "存在差异"))
        res["_detail"] = "通过" if res.get("all_ok") else "存在差异"
        return res

    job, created = jobs_service.submit(pid, user["id"], "verify", runner)
    return _ok({"job": job, "created": created})


@router.get("/projects/{id}/credentials/status")
def credentials_status(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    return _ok(EB.credentials_status(p))


@router.post("/projects/{id}/preview")
def preview(id: int, body: S.PreviewIn, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    storage.project_dir(p["slug"], create=True)
    try:
        res = EB.preview(p["slug"], body.sheet, EB.build_cfg(p))
    except Exception as e:
        raise HTTPException(400, "载荷预览失败:%s" % e)
    return _ok(res)
