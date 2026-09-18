# -*- coding: utf-8 -*-
"""流水线路由(需求 / 方案 / 流程图 / ER)。

契约见 docs/ARCHITECTURE.md §5:
  GET/PUT  /api/projects/{id}/requirement
  GET/POST/PUT /api/projects/{id}/plan[/generate]
  GET/POST/PUT /api/projects/{id}/flowchart[/generate]
  GET/POST/PUT /api/projects/{id}/design[/generate]
  GET  /api/projects/{id}/design/check
  GET  /api/projects/{id}/design/er

统一响应 {ok,data,message};写操作校验项目写权限。
"""
from fastapi import APIRouter, Depends

from .. import engine_bridge as EB
from .. import storage
from ..core import deps
from ..db import database as db
from ..schemas import pipeline as S
from ..services import design as design_service
from ..services import flowchart as flowchart_service
from ..services import plan as plan_service

router = APIRouter(prefix="/api", tags=["pipeline"])


def _ok(data=None, message=""):
    return {"ok": True, "data": data if data is not None else {}, "message": message}


def _design_payload(design, provider, check=None, error=""):
    return {"sheets": design.get("sheets") or [],
            "dicts": design.get("dicts") or {},
            "groups": design.get("groups") or [],
            "automations": design.get("automations") or [],
            "provider": provider,
            "check": check,
            "error": error or ""}


def _sync(slug, app_code, design):
    """落盘 sheets+automations 并离线校验;返回 (清洗后的 design, check, error)。
    异常也转成 error,不抛出(校验失败仍保存,便于继续编辑)。"""
    storage.project_dir(slug, create=True)
    try:
        res = EB.sync_sheets(slug, design, app_code=app_code)
        return (res.get("design") or design), res.get("check"), res.get("error", "")
    except Exception as e:
        return design, None, str(e)


# ---------------------------------------------------------------- 需求
@router.get("/projects/{id}/requirement")
def get_requirement(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    return _ok(storage.get_requirement(p["slug"]))


@router.put("/projects/{id}/requirement")
def put_requirement(id: int, body: S.RequirementIn, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    storage.set_requirement(p["slug"], body.html, body.text)
    db.add_event(p["id"], "requirement", "更新需求内容")
    return _ok(storage.get_requirement(p["slug"]))


# ---------------------------------------------------------------- 方案
@router.get("/projects/{id}/plan")
def get_plan(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    return _ok({"markdown": storage.get_plan(p["slug"])})


def _reference_docs(pid):
    """本项目上传的全部文档(含「已有系统」)—— 方案/表单结构的**参考资料来源**。"""
    docs = db.list_documents(pid)
    return [d for d in docs if d.get("parsed_text")]


@router.post("/projects/{id}/plan/generate")
def generate_plan(id: int, body: S.GenerateIn = None, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    instruction = (body.instruction if body else None)
    requirement = storage.requirement_text(p["slug"])
    documents_text = storage.collect_documents_text(p["slug"], _reference_docs(p["id"]))
    res = plan_service.generate_plan(requirement, documents_text, instruction)
    storage.set_plan(p["slug"], res["markdown"])
    db.update_project(p["id"], status="planned")
    db.add_event(p["id"], "plan", "生成系统设计方案(provider=%s)" % res.get("provider"))
    return _ok({"markdown": res["markdown"], "provider": res.get("provider", "heuristic")})


@router.put("/projects/{id}/plan")
def put_plan(id: int, body: S.PlanIn, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    storage.set_plan(p["slug"], body.markdown)
    db.update_project(p["id"], status="planned")
    return _ok({"markdown": body.markdown})


# ---------------------------------------------------------------- 流程图
@router.get("/projects/{id}/flowchart")
def get_flowchart(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    return _ok({"mermaid": storage.get_flowchart(p["slug"])})


@router.post("/projects/{id}/flowchart/generate")
def generate_flowchart(id: int, body: S.GenerateIn = None, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    res = flowchart_service.generate_flowchart(storage.get_plan(p["slug"]),
                                               storage.requirement_text(p["slug"]))
    storage.set_flowchart(p["slug"], res["mermaid"])
    db.update_project(p["id"], status="flowcharted")
    db.add_event(p["id"], "flowchart", "生成业务流程图(provider=%s)" % res.get("provider"))
    return _ok({"mermaid": res["mermaid"], "provider": res.get("provider", "heuristic")})


@router.put("/projects/{id}/flowchart")
def put_flowchart(id: int, body: S.FlowchartIn, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    storage.set_flowchart(p["slug"], body.mermaid)
    db.update_project(p["id"], status="flowcharted")
    return _ok({"mermaid": body.mermaid})


# ---------------------------------------------------------------- ER / 设计
@router.get("/projects/{id}/design")
def get_design(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    return _ok(storage.get_design(p["slug"]))


@router.post("/projects/{id}/design/generate")
def generate_design(id: int, body: S.GenerateIn = None, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    documents_text = storage.collect_documents_text(p["slug"], _reference_docs(p["id"]))
    res = design_service.generate_design(storage.get_plan(p["slug"]),
                                         storage.requirement_text(p["slug"]),
                                         documents_text)
    design = {"sheets": res.get("sheets") or [],
              "dicts": res.get("dicts") or {},
              "groups": res.get("groups") or [],
              "automations": res.get("automations") or []}
    design, check, error = _sync(p["slug"], p.get("app_code", ""), design)
    storage.set_design(p["slug"], design)
    db.update_project(p["id"], status="designed")
    db.add_event(p["id"], "design",
                 "生成 ER 结构(provider=%s, %d 表/%d 自动化)"
                 % (res.get("provider", "heuristic"), len(design["sheets"]),
                    len(design.get("automations") or [])))
    return _ok(_design_payload(design, res.get("provider", "heuristic"), check, error))


@router.put("/projects/{id}/design")
def put_design(id: int, body: S.DesignIn, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    design, check, error = _sync(p["slug"], p.get("app_code", ""), body.model_dump())
    # 存**清洗后**的 design(与 sheets/ 一致),避免编辑器所见与引擎所建分叉
    storage.set_design(p["slug"], design)
    db.update_project(p["id"], status="designed")
    return _ok(_design_payload(design, "user", check, error))


@router.get("/projects/{id}/design/check")
def check_design(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    design = storage.get_design(p["slug"])
    if not design.get("sheets"):
        return _ok({"project": p["slug"], "sheets": [], "warnings": [],
                    "error": "尚未生成 ER 结构"})
    _design, check, error = _sync(p["slug"], p.get("app_code", ""), design)
    if not check:
        return _ok({"project": p["slug"], "sheets": [], "warnings": [], "error": error})
    check = dict(check)
    check["error"] = error or ""
    return _ok(check)


@router.get("/projects/{id}/design/er")
def design_er(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    storage.project_dir(p["slug"], create=True)
    try:
        return _ok(EB.er_graph(p["slug"], app_code=p.get("app_code", "")))
    except Exception as e:
        return _ok({"project": p["slug"], "nodes": [], "edges": [], "error": str(e)})
