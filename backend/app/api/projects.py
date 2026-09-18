# -*- coding: utf-8 -*-
"""项目路由。见 docs/ARCHITECTURE.md §5「项目」。

要点:
  - slug 即目录名,字母开头,仅含字母/数字/下划线,最长 48;
  - h3_token 用 security.encrypt_secret 加密存储,接口绝不回显;
  - engineCode 由**用户在建/改项目时填写**(也支持从 token 预填);appCode 可后填。
"""
import os
import re
import shutil

from fastapi import APIRouter, Depends, HTTPException

from .. import engine_bridge as EB
from .. import storage
from ..core import deps
from ..core import security as sec
from ..db import database as db
from ..schemas import MemberIn, ProjectCreate, ProjectUpdate

router = APIRouter(prefix="/api", tags=["projects"])

_SLUG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,47}$")
_MEMBER_ROLES = ("viewer", "designer")


def _result(data=None, message=""):
    return {"ok": True, "data": data, "message": message}


def _view(p, user):
    """项目对外视图 + canWrite/role。"""
    pub = deps.project_public(p)
    if user["role"] == "admin" or p.get("owner_id") == user["id"]:
        role = "designer"
    else:
        role = db.project_member_role(p["id"], user["id"]) or "viewer"
    pub["role"] = role
    pub["canWrite"] = role == "designer"
    return pub


def _valid_token(project_body_token):
    token = EB.normalize_token(project_body_token)
    if not token:
        return ""
    info = EB.parse_h3_token(token)
    if not info.get("valid") or info.get("expired"):
        raise HTTPException(400, "h3_token 无效或已过期")
    return token


def _member_view(m):
    return {"userId": m["user_id"], "role": m["role"],
            "email": m.get("email", ""), "displayName": m.get("display_name", "")}


@router.get("/projects")
def list_projects(user=Depends(deps.get_current_user)):
    if user["role"] == "admin":
        rows = db.list_projects()
    else:
        rows = db.list_projects(member_of=user["id"])
    return _result([_view(p, user) for p in rows])


@router.post("/projects")
def create_project(body: ProjectCreate, user=Depends(deps.get_current_user)):
    if not _SLUG_RE.match(body.name or ""):
        raise HTTPException(400, "项目标识不合法:需字母开头,仅含字母/数字/下划线,最长 48 位")
    if db.get_project_by_slug(body.name):
        raise HTTPException(409, "项目标识已存在")
    # Windows 文件系统大小写不敏感:精确匹配之外再做一次 LOWER(slug) 查重,
    # 避免 Store / store 指向同一目录导致数据互相覆盖。
    lowered = body.name.lower()
    for existing in db.list_projects():
        if (existing.get("slug") or "").lower() == lowered:
            raise HTTPException(409, "项目标识已存在(大小写不敏感)")
    token = _valid_token(body.h3Token)
    p = db.create_project(body.name, body.title, body.appCode or "",
                          (body.engineCode or "").strip(),
                          sec.encrypt_secret(token) if token else "",
                          owner_id=user["id"])
    storage.project_dir(p["slug"], create=True)
    return _result(_view(p, user), "项目已创建")


@router.get("/projects/{pid}")
def get_project(pid: int, user=Depends(deps.get_current_user)):
    p = deps.get_project(pid, user)
    return _result(_view(p, user))


@router.patch("/projects/{pid}")
def update_project(pid: int, body: ProjectUpdate, user=Depends(deps.get_current_user)):
    p = deps.project_writable(pid, user)
    fields = {}
    if body.title is not None:
        fields["title"] = body.title
    if body.appCode is not None:
        fields["app_code"] = body.appCode
    if body.engineCode is not None and body.engineCode.strip():
        fields["engine_code"] = body.engineCode.strip()
    if body.h3Token is not None:
        token = _valid_token(body.h3Token)
        if token:
            fields["h3_token"] = sec.encrypt_secret(token)
    if fields:
        p = db.update_project(pid, **fields)
    return _result(_view(p, user), "项目已更新")


@router.delete("/projects/{pid}")
def delete_project(pid: int, user=Depends(deps.get_current_user)):
    p = deps.project_writable(pid, user)
    if not (user["role"] == "admin" or p.get("owner_id") == user["id"]):
        raise HTTPException(403, "仅项目所有者或管理员可删除项目")
    db.delete_project(pid)
    folder = storage.project_dir(p["slug"])
    if os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)
    return _result(None, "项目已删除")


@router.get("/projects/{pid}/members")
def list_members(pid: int, user=Depends(deps.get_current_user)):
    deps.get_project(pid, user)
    return _result([_member_view(m) for m in db.list_members(pid)])


@router.post("/projects/{pid}/members")
def add_member(pid: int, body: MemberIn, user=Depends(deps.get_current_user)):
    deps.project_writable(pid, user)
    if body.role not in _MEMBER_ROLES:
        raise HTTPException(400, "角色只能是 viewer 或 designer")
    if not db.get_user_by_id(body.userId):
        raise HTTPException(404, "用户不存在")
    db.set_member(pid, body.userId, body.role)
    return _result([_member_view(m) for m in db.list_members(pid)], "成员已授权")


@router.delete("/projects/{pid}/members/{userId}")
def remove_member(pid: int, userId: int, user=Depends(deps.get_current_user)):
    deps.project_writable(pid, user)
    db.remove_member(pid, userId)
    return _result(None, "成员已移除")
