# -*- coding: utf-8 -*-
"""认证路由(邮件 + Cookie 会话)。见 docs/ARCHITECTURE.md §5「认证」。

首次登录:管理员创建的用户初始**没有密码**(password_hash 为空),login 会返回
`needPassword=true`,前端引导其设置新密码(不走邮件),再签发会话。
"""
import os
import time

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile

from ..core import config as C
from ..core import deps
from ..core import security as sec
from ..db import database as db
from ..schemas import BootstrapIn, LoginIn, PasswordIn, ProfileIn, SetInitialPasswordIn

router = APIRouter(prefix="/api/auth", tags=["auth"])

_AVATAR_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
_AVATAR_MAX_MB = 5


def _result(data=None, message=""):
    return {"ok": True, "data": data, "message": message}


def _issue(response, user):
    """按用户当前 token_version 签发会话 Cookie。"""
    ver = int(user.get("token_version") or 0)
    sec.set_session_cookie(response, sec.create_token(user["id"], ver))


def _avatar_path(filename):
    return os.path.join(C.AVATAR_DIR, filename) if filename else ""


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
    if not user:
        raise HTTPException(401, "邮箱或密码错误")
    if not user.get("active"):
        raise HTTPException(403, "账号已停用")
    if not user.get("password_hash"):
        # 账号已创建但尚未设置密码:引导首次登录设置密码(不走邮件)
        return _result({"needPassword": True, "email": user["email"]},
                       "该账号尚未设置密码,请先设置密码")
    if not sec.verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(401, "邮箱或密码错误")
    _issue(response, user)
    return _result(deps.user_public(user), "登录成功")


@router.post("/set-initial-password")
def set_initial_password(body: SetInitialPasswordIn, response: Response):
    """首次登录设置密码:须凭管理员生成的一次性激活码;成功后直接登录。"""
    user = db.get_user_by_email(body.email)
    if not user or not user.get("active"):
        raise HTTPException(400, "账号不存在或已停用,请联系管理员")
    if user.get("password_hash"):
        raise HTTPException(400, "该账号已设置密码,请直接登录")
    token = user.get("activation_token") or ""
    if not token or not sec.token_matches(body.code, token):
        raise HTTPException(400, "激活码不正确")
    exp = int(user.get("activation_expires") or 0)
    if exp and int(time.time()) > exp:
        raise HTTPException(400, "激活码已过期,请联系管理员重新生成")
    db.update_user(user["id"], password_hash=sec.hash_password(body.password),
                   activation_token="", activation_expires=0)
    user = db.get_user_by_id(user["id"])
    _issue(response, user)
    return _result(deps.user_public(user), "密码已设置,登录成功")


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


@router.patch("/profile")
def update_profile(body: ProfileIn, user=Depends(deps.get_current_user)):
    """用户修改自己的显示名称。"""
    name = (body.displayName or "").strip()
    if not name:
        raise HTTPException(400, "显示名称不能为空")
    return _result(deps.user_public(db.update_user(user["id"], display_name=name)), "资料已更新")


@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user=Depends(deps.get_current_user)):
    """上传自定义头像(png/jpg/jpeg/gif/webp/bmp,≤5MB);文件名带时间戳以利缓存刷新。"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _AVATAR_EXTS:
        raise HTTPException(400, "不支持的图片类型:%s(允许:%s)"
                            % (ext or "(无扩展名)", "、".join(_AVATAR_EXTS)))
    max_bytes = _AVATAR_MAX_MB * 1024 * 1024
    _CHUNK = 64 * 1024
    buf = bytearray()
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(413, "头像超过 %d MB 上限" % _AVATAR_MAX_MB)
    if not buf:
        raise HTTPException(400, "文件内容为空")

    os.makedirs(C.AVATAR_DIR, exist_ok=True)
    # 清理旧头像(同一用户的其它扩展名)
    for old in os.listdir(C.AVATAR_DIR):
        if old.startswith("%d_" % user["id"]):
            try:
                os.remove(os.path.join(C.AVATAR_DIR, old))
            except Exception:
                pass
    filename = "%d_%d%s" % (user["id"], int(time.time() * 1000), ext)
    with open(os.path.join(C.AVATAR_DIR, filename), "wb") as f:
        f.write(bytes(buf))
    updated = db.update_user(user["id"], avatar=filename)
    return _result(deps.user_public(updated), "头像已更新")


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
