# -*- coding: utf-8 -*-
"""用户管理路由(仅 admin;目录/头像为登录用户可见)。见 docs/ARCHITECTURE.md §5「用户」。"""
import os
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..core import config as C
from ..core import deps
from ..core import security as sec
from ..db import database as db
from ..schemas import UserCreate, UserUpdate

router = APIRouter(prefix="/api", tags=["users"])


def _result(data=None, message=""):
    return {"ok": True, "data": data, "message": message}


def _activation_expiry():
    return int(time.time()) + C.ACTIVATION_TTL_DAYS * 86400


def _with_code(user, code):
    data = deps.user_public(user)
    data["activationCode"] = code
    return data


@router.get("/users")
def list_users(admin=Depends(deps.require_admin)):
    return _result([deps.user_public(u) for u in db.list_users()])


@router.get("/users/directory")
def users_directory(user=Depends(deps.get_current_user)):
    """登录用户可见的精简用户清单(仅 id/邮箱/显示名,供项目共享选择对象)。"""
    return _result([{"id": u["id"], "email": u["email"],
                     "displayName": u.get("display_name") or u["email"]}
                    for u in db.list_users() if u.get("active")])


@router.get("/users/{uid}/avatar")
def get_avatar(uid: int, user=Depends(deps.get_current_user)):
    """读取用户头像(登录用户可见);未设置或文件缺失返回 404,前端回退默认头像。"""
    target = db.get_user_by_id(uid)
    if not target or not target.get("avatar"):
        raise HTTPException(404, "未设置头像")
    path = os.path.join(C.AVATAR_DIR, target["avatar"])
    if not os.path.isfile(path):
        raise HTTPException(404, "头像文件不存在")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@router.post("/users")
def create_user(body: UserCreate, admin=Depends(deps.require_admin)):
    if body.role not in db.ROLES:
        raise HTTPException(400, "非法角色:%s" % body.role)
    if db.get_user_by_email(body.email):
        raise HTTPException(409, "邮箱已存在")
    password = (body.password or "").strip()
    if password and len(password) < 6:
        raise HTTPException(400, "密码至少 6 位")
    # 管理员直接给密码:用户可直接登录
    if password:
        user = db.create_user(body.email, sec.hash_password(password), role=body.role,
                              display_name=body.displayName or body.email)
        return _result(deps.user_public(user), "用户已创建")
    # 密码留空:生成一次性激活码,用户首次登录凭激活码自行设置密码
    user = db.create_user(body.email, "", role=body.role,
                          display_name=body.displayName or body.email)
    code = sec.new_activation_code()
    user = db.update_user(user["id"], activation_token=sec.hash_token(code),
                          activation_expires=_activation_expiry())
    return _result(_with_code(user, code),
                   "用户已创建,请将激活码发给该用户用于首次设置密码")


@router.post("/users/{uid}/activation")
def regenerate_activation(uid: int, admin=Depends(deps.require_admin)):
    """为「尚未设置密码」的用户重新生成一次性激活码(旧码立即失效)。"""
    user = db.get_user_by_id(uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    if user.get("password_hash"):
        raise HTTPException(400, "该用户已设置密码,无需激活码")
    code = sec.new_activation_code()
    user = db.update_user(uid, activation_token=sec.hash_token(code),
                          activation_expires=_activation_expiry())
    return _result(_with_code(user, code), "已生成新的激活码")


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
    if body.password:                       # 留空 = 不修改
        if len(body.password) < 6:
            raise HTTPException(400, "密码至少 6 位")
        fields["password_hash"] = sec.hash_password(body.password)
        fields["activation_token"] = ""      # 已设密码则作废待激活状态
        fields["activation_expires"] = 0
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
    avatar = user.get("avatar")
    db.delete_user(uid)
    if avatar:
        try:
            os.remove(os.path.join(C.AVATAR_DIR, avatar))
        except Exception:
            pass
    return _result(None, "用户已删除")
