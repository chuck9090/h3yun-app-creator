# -*- coding: utf-8 -*-
"""认证路由(邮件 + Cookie 会话)。见 docs/ARCHITECTURE.md §5「认证」。"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..core import config as C
from ..core import deps
from ..core import security as sec
from ..db import database as db
from ..schemas import BootstrapIn, LoginIn, PasswordIn

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _result(data=None, message=""):
    return {"ok": True, "data": data, "message": message}


def _issue(response, user):
    """按用户当前 token_version 签发会话 Cookie。"""
    ver = int(user.get("token_version") or 0)
    sec.set_session_cookie(response, sec.create_token(user["id"], ver))


@router.post("/bootstrap")
def bootstrap(body: BootstrapIn, response: Response):
    """仅当系统尚无任何用户时可初始化管理员。"""
    if db.count_users() > 0:
        raise HTTPException(400, "系统已初始化,请直接登录")
    user = db.create_user(body.email, sec.hash_password(body.password),
                          role="admin", display_name=body.displayName or body.email)
    _issue(response, user)
    return _result(deps.user_public(user), "初始化完成")


@router.post("/login")
def login(body: LoginIn, response: Response):
    user = db.get_user_by_email(body.email)
    if not user or not sec.verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(401, "邮箱或密码错误")
    if not user.get("active"):
        raise HTTPException(403, "账号已停用")
    _issue(response, user)
    return _result(deps.user_public(user), "登录成功")


@router.post("/logout")
def logout(request: Request, response: Response):
    """登出:自增 token_version 使已签发的所有 token 立即失效,并清除 Cookie。"""
    token = request.cookies.get(C.COOKIE_NAME)
    if token:
        payload = sec.decode_token(token)
        if payload:
            user = db.get_user_by_id(payload.get("sub"))
            if user and "token_version" in user:
                db.update_user(user["id"],
                               token_version=int(user.get("token_version") or 0) + 1)
    sec.clear_session_cookie(response)
    return _result(None, "已退出登录")


@router.get("/me")
def me(user=Depends(deps.get_current_user)):
    return _result(deps.user_public(user))


@router.post("/password")
def change_password(body: PasswordIn, user=Depends(deps.get_current_user)):
    if not sec.verify_password(body.oldPassword, user.get("password_hash", "")):
        raise HTTPException(400, "原密码不正确")
    fields = {"password_hash": sec.hash_password(body.newPassword)}
    if "token_version" in user:
        # 改密后使旧 token 全部失效(含当前请求所用 token)
        fields["token_version"] = int(user.get("token_version") or 0) + 1
    db.update_user(user["id"], **fields)
    return _result(None, "密码已更新")
