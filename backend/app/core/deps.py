# -*- coding: utf-8 -*-
"""FastAPI 依赖:认证(Cookie 会话)与授权(RBAC + 项目级)。"""
from fastapi import Depends, HTTPException, Request

from . import security as sec
from .config import COOKIE_NAME
from ..db import database as db

ROLE_RANK = {"viewer": 1, "designer": 2, "admin": 3}


def get_current_user(request: Request):
    """从 httpOnly Cookie 解析会话用户;未登录 401。"""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "未登录")
    payload = sec.decode_token(token)
    if not payload:
        raise HTTPException(401, "会话已过期,请重新登录")
    user = db.get_user_by_id(payload.get("sub"))
    if not user or not user.get("active"):
        raise HTTPException(401, "用户不存在或已停用")
    if int(payload.get("ver", 0)) != int(user.get("token_version") or 0):
        raise HTTPException(401, "会话已失效,请重新登录")
    return user


def require_user(user=Depends(get_current_user)):
    return user


def _at_least(user, role):
    if ROLE_RANK.get(user.get("role"), 0) < ROLE_RANK[role]:
        raise HTTPException(403, "权限不足:需要 %s" % role)
    return user


def require_editor(user=Depends(get_current_user)):
    return _at_least(user, "designer")


def require_admin(user=Depends(get_current_user)):
    return _at_least(user, "admin")


def get_project(pid: int, user=Depends(get_current_user), write: bool = False):
    """取项目并校验访问权:admin 全通;owner 可写;成员按角色(viewer 只读)。"""
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "项目不存在")
    if user["role"] == "admin" or p.get("owner_id") == user["id"]:
        return p
    role = db.project_member_role(pid, user["id"])
    if not role:
        raise HTTPException(403, "无权访问该项目")
    if write and ROLE_RANK.get(role, 0) < ROLE_RANK["designer"]:
        raise HTTPException(403, "你在该项目只有只读权限")
    return p


def project_writable(pid: int, user=Depends(require_editor)):
    return get_project(pid, user, write=True)


def project_public(p: dict) -> dict:
    """项目对外视图:绝不回显 h3_token。"""
    if not p:
        return p
    return {
        "id": p["id"], "slug": p["slug"], "title": p["title"],
        "appCode": p.get("app_code", ""), "engineCode": p.get("engine_code", ""),
        "status": p.get("status", "draft"),
        "ownerId": p.get("owner_id", 0), "createdAt": p.get("created_at", ""),
        "updatedAt": p.get("updated_at", ""),
        "hasToken": bool(p.get("h3_token")),
    }


def user_public(u: dict) -> dict:
    if not u:
        return u
    return {"id": u["id"], "email": u["email"], "displayName": u.get("display_name", ""),
            "role": u.get("role", ""), "active": bool(u.get("active")),
            "avatar": u.get("avatar", "") or "",
            "hasPassword": bool(u.get("password_hash")),
            "activationPending": bool(u.get("activation_token")),
            "createdAt": u.get("created_at", "")}
