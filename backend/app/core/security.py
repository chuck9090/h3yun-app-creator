# -*- coding: utf-8 -*-
"""安全:密码哈希 · JWT · Cookie 会话 · 凭据加密。

全部标准库实现(不引入 cryptography),适合本地/内网单机部署。
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import time

from . import config as C

_ITER = 120_000


# ---------------------------------------------------------------- 服务端密钥
def _tighten_file_permissions(path: str) -> None:
    """尽力收紧密钥文件权限;失败仅告警,不影响启动。

    Windows 下 os.chmod(0o600) 无效,须用 icacls 去掉继承并只授权当前用户。
    """
    if os.name == "nt":
        user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        if not user:
            return
        try:
            subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", "%s:F" % user],
                           capture_output=True, text=True, timeout=15, check=False)
        except Exception as e:
            print("[warn] 收紧密钥文件 ACL 失败(可忽略):%s" % e)
        return
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


_permission_warned = False


def _warn_if_permissions_loose(path: str) -> None:
    """读取密钥文件时,若权限过宽仅告警一次。"""
    global _permission_warned
    if _permission_warned:
        return
    _permission_warned = True
    if os.name == "nt":
        try:
            out = subprocess.run(["icacls", path], capture_output=True, text=True,
                                 timeout=15, check=False).stdout or ""
        except Exception:
            return
        for token in ("Everyone", "BUILTIN\\Users", "Authenticated Users"):
            if token in out:
                print("[warn] 密钥文件权限过宽,建议使用 H3F_SECRET 环境变量或收紧 ACL:%s"
                      % path)
                break
        return
    try:
        mode = os.stat(path).st_mode & 0o777
        if mode & 0o077:
            print("[warn] 密钥文件权限过宽(%o),建议 chmod 600:%s" % (mode, path))
    except Exception:
        pass


def _secret_bytes() -> bytes:
    """Cookie/JWT 签名与凭据加密的服务端密钥。

    生产环境应通过 `H3F_SECRET` 环境变量注入(优先于落盘文件),避免密钥文件泄露。
    """
    env = os.environ.get("H3F_SECRET", "").strip()
    if env:
        return env.encode("utf-8")
    os.makedirs(C.DATA_DIR, exist_ok=True)
    if os.path.isfile(C.SECRET_FILE):
        with open(C.SECRET_FILE, "rb") as f:
            key = f.read()
        _warn_if_permissions_loose(C.SECRET_FILE)
        return key
    key = secrets.token_bytes(48)
    with open(C.SECRET_FILE, "wb") as f:
        f.write(key)
    _tighten_file_permissions(C.SECRET_FILE)
    return key


def _derive(purpose: bytes, length: int = 32) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", _secret_bytes(), b"h3f:" + purpose,
                               50_000, dklen=length)


# ---------------------------------------------------------------- 密码
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, _ITER)
    return "pbkdf2$%d$%s$%s" % (_ITER, base64.b64encode(salt).decode(),
                                base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_b64, dk_b64 = (stored or "").split("$")
        got = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                                  base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(got, base64.b64decode(dk_b64))
    except Exception:
        return False


# ---------------------------------------------------------------- JWT
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def create_token(user_id: int, ver: int = 0, ttl: int = None) -> str:
    """签发会话 JWT;`ver` 对应用户的 token_version,登出/改密后自增使旧 token 失效。"""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": int(user_id), "ver": int(ver or 0), "iat": now,
               "exp": now + (ttl if ttl is not None else C.TOKEN_TTL)}
    seg = "%s.%s" % (_b64e(json.dumps(header, separators=(",", ":")).encode()),
                     _b64e(json.dumps(payload, separators=(",", ":")).encode()))
    sig = hmac.new(_derive(b"jwt"), seg.encode(), hashlib.sha256).digest()
    return seg + "." + _b64e(sig)


def decode_token(token: str):
    try:
        seg, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(_b64d(sig),
                                   hmac.new(_derive(b"jwt"), seg.encode(), hashlib.sha256).digest()):
            return None
        payload = json.loads(_b64d(seg.split(".")[1]))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


# ---------------------------------------------------------------- 凭据加密(h3_token 静态存储)
def encrypt_secret(plain: str) -> str:
    """认证加密:nonce + XOR(SHA256 流) + HMAC。仅用于本地凭据静态混淆。"""
    if not plain:
        return ""
    data = plain.encode("utf-8")
    nonce = secrets.token_bytes(16)
    key = _derive(b"cred", 32)
    stream = bytearray()
    i = 0
    while len(stream) < len(data):
        stream.extend(hashlib.sha256(key + nonce + i.to_bytes(4, "big")).digest())
        i += 1
    ct = bytes(a ^ b for a, b in zip(data, stream))
    mac = hmac.new(key, nonce + ct, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(nonce + ct + mac).decode()


def decrypt_secret(blob: str) -> str:
    if not blob:
        return ""
    try:
        raw = base64.urlsafe_b64decode(blob.encode("ascii"))
        nonce, ct, mac = raw[:16], raw[16:-16], raw[-16:]
        key = _derive(b"cred", 32)
        if not hmac.compare_digest(mac, hmac.new(key, nonce + ct, hashlib.sha256).digest()[:16]):
            return ""
        stream = bytearray()
        i = 0
        while len(stream) < len(ct):
            stream.extend(hashlib.sha256(key + nonce + i.to_bytes(4, "big")).digest())
            i += 1
        return bytes(a ^ b for a, b in zip(ct, stream)).decode("utf-8", "replace")
    except Exception:
        return ""


# ---------------------------------------------------------------- Cookie
def set_session_cookie(response, token: str):
    response.set_cookie(C.COOKIE_NAME, token, max_age=C.TOKEN_TTL,
                        httponly=True, samesite=C.COOKIE_SAMESITE,
                        secure=C.COOKIE_SECURE, path="/")


def clear_session_cookie(response):
    response.delete_cookie(C.COOKIE_NAME, path="/")
