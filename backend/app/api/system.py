# -*- coding: utf-8 -*-
"""系统:健康检查/知识库。

(由核心维护,勿删)
"""
import os

from fastapi import APIRouter, Depends

from ..core import config as C
from ..core import deps
from ..db import database as db
from ..services import llm as llm_service

router = APIRouter(prefix="/api", tags=["system"])

_KNOWLEDGE_CORPUS = os.path.join(C.KNOWLEDGE_DIR, "corpus.json")


@router.get("/health")
def health():
    provider = llm_service.get_provider()
    return {"ok": True, "message": "", "data": {
        "provider": provider.name, "llm": provider.name == "llm",
        "needsBootstrap": db.count_users() == 0,
        "knowledge": os.path.isfile(_KNOWLEDGE_CORPUS),
        "version": "2.0.0"}}


@router.get("/jobs")
def list_jobs(limit: int = 50, user=Depends(deps.require_admin)):
    return {"ok": True, "message": "", "data": db.list_jobs(limit)}


@router.get("/knowledge/summary")
def knowledge_summary(user=Depends(deps.require_user)):
    if not os.path.isfile(_KNOWLEDGE_CORPUS):
        return {"ok": True, "message": "",
                "data": {"projects": 0, "tables": 0, "names": []}}
    import json
    with open(_KNOWLEDGE_CORPUS, encoding="utf-8") as f:
        c = json.load(f)
    projects = c.get("projects", [])
    if user["role"] != "admin":
        # 非 admin 仅能看到自己可见项目(拥有或被授权)的知识库条目,避免泄露全部项目名
        visible = {p.get("slug") for p in db.list_projects(member_of=user["id"])}
        projects = [x for x in projects if x.get("name") in visible]
    return {"ok": True, "message": "", "data": {
        "projects": len(projects),
        "tables": sum(len(x.get("tables", [])) for x in projects),
        "names": [x["name"] for x in projects],
    }}


@router.post("/knowledge/refresh")
def knowledge_refresh(user=Depends(deps.require_editor)):
    from .. import engine_bridge as EB
    try:
        info = EB.refresh_knowledge()
    except Exception as e:
        return {"ok": False, "message": "知识库刷新失败: %s" % e}
    return {"ok": True, "message": "已刷新设计知识库", "data": info}
