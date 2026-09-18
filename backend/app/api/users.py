# -*- coding: utf-8 -*-
"""用户管理路由(仅 admin)。见 docs/ARCHITECTURE.md §5「用户」。"""
from fastapi import APIRouter, Depends, HTTPException

from ..core import deps
from ..core import security as sec
from ..db import database as db
from ..schemas import UserCreate, UserUpdate

router = APIRouter(prefix="/api", tags=["users"])


def _result(data=None, message=""):
    return {"ok": True, "data": data, "message": message}


@router.get("/users")
def list_users(admin=Depends(deps.require_admin)):
    return _result([deps.user_public(u) for u in db.list_users()])


@router.post("/users")
def create_user(body: UserCreate, admin=Depends(deps.require_admin)):
    if body.role not in db.ROLES:
        raise HTTPException(400, "非法角色:%s" % body.role)
    if len(body.password or "") < 6:
        raise HTTPException(400, "密码至少 6 位")
    if db.get_user_by_email(body.email):
        raise HTTPException(409, "邮箱已存在")
    user = db.create_user(body.email, sec.hash_password(body.password),
                          role=body.role, display_name=body.displayName or body.email)
    return _result(deps.user_public(user), "用户已创建")


@router.patch("/users/{uid}")
def update_user(uid: int, body: UserUpdate, admin=Depends(deps.require_admin)):
    user = db.get_user_by_id(uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    fields = {}
    invalidate = False
    if body.displayName is not None:
        fields["display_name"] = body.displayName
    if body.role is not None:
        if body.role not in db.ROLES:
            raise HTTPException(400, "非法角色:%s" % body.role)
        fields["role"] = body.role
    if body.active is not None:
        fields["active"] = 1 if body.active else 0
        invalidate = True
    if body.password is not None:
        if len(body.password) < 6:
            raise HTTPException(400, "密码至少 6 位")
        fields["password_hash"] = sec.hash_password(body.password)
        invalidate = True
    if invalidate and "token_version" in user:
        fields["token_version"] = int(user.get("token_version") or 0) + 1
    if not fields:
        return _result(deps.user_public(user), "无变更")
    return _result(deps.user_public(db.update_user(uid, **fields)), "用户已更新")


@router.delete("/users/{uid}")
def delete_user(uid: int, admin=Depends(deps.require_admin)):
    user = db.get_user_by_id(uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    if uid == admin["id"]:
        raise HTTPException(400, "不能删除当前登录账号")
    if "token_version" in user:
        # 删除前自增,确保残留 token 立即失效(删除后用户不存在同样会被拒)
        db.update_user(uid, token_version=int(user.get("token_version") or 0) + 1)
    db.delete_user(uid)
    return _result(None, "用户已删除")
