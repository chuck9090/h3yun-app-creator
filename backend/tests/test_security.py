# -*- coding: utf-8 -*-
"""安全加固回归测试(独立临时 DB/env,不触碰开发数据)。

运行(工作目录 = backend/):
    python -X utf8 tests/test_security.py

覆盖:S2/S3/S4/M7/M8/M9/B6 —— 标准信封 health、未登录 401、bootstrap 仅在 0 用户时可用、
     登出后旧 Cookie 失效、改密后旧 token 失效、viewer 访问 /api/jobs 403、
     上传超限 413、非法扩展名 400、slug 大小写冲突 409、知识库按可见项目过滤。
"""
import base64
import http.cookies
import json
import os
import shutil
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# ---- 独立环境变量(必须在导入 app.core.config 之前设置) ----
ADMIN_EMAIL = "admin@sec.local"
ADMIN_PASSWORD = "adminPass123"
NEW_PASSWORD = "newPass456"
VIEWER_EMAIL = "viewer@sec.local"
VIEWER_PASSWORD = "viewer123"

os.environ["H3AC_SECRET"] = "h3ac-security-test-secret"
os.environ["H3AC_ADMIN_EMAIL"] = ADMIN_EMAIL
os.environ["H3AC_ADMIN_PASSWORD"] = ""            # 不自动建管理员 → 走 bootstrap
os.environ["H3AC_MAX_UPLOAD_MB"] = "1"            # 上传上限 1MB,便于构造超限
for _k in ("H3AC_LLM_BASE_URL", "H3AC_LLM_API_KEY", "H3AC_LLM_MODEL"):
    os.environ[_k] = ""

from fastapi.testclient import TestClient            # noqa: E402

from app.core import config as C                     # noqa: E402
from app.db import database as db                    # noqa: E402

TMP = tempfile.mkdtemp(prefix="h3ac_sec_test_")
C.DATA_DIR = os.path.join(TMP, "data")
C.DB_PATH = os.path.join(C.DATA_DIR, "test.db")
C.SECRET_FILE = os.path.join(C.DATA_DIR, "secret.key")
C.PROJECTS_DIR = os.path.join(TMP, "projects")
os.makedirs(C.DATA_DIR, exist_ok=True)

from app.main import app, run_migrations           # noqa: E402

run_migrations()                                     # 建表 + token_version 幂等迁移
client = TestClient(app)                             # 不用 with → 不触发 startup 副作用

PASSED = []


def ok(cond, label):
    if not cond:
        raise AssertionError("断言失败:%s" % label)
    PASSED.append(label)


def b64(obj):
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def fake_h3_token(enginecode="SECENG", exp=9999999999, loginname="tester"):
    return "%s.%s.x" % (b64({"alg": "HS256", "typ": "JWT"}),
                        b64({"enginecode": enginecode, "exp": exp, "loginname": loginname}))


def _cookie_value(resp):
    """从响应 Set-Cookie 提取会话 token(避免 httpx cookie jar 同名冲突)。"""
    c = http.cookies.SimpleCookie()
    for raw in resp.headers.get_list("set-cookie"):
        c.load(raw)
    return c[C.COOKIE_NAME].value if C.COOKIE_NAME in c else None


def _login(cli, email, password):
    r = cli.post("/api/auth/login", json={"email": email, "password": password})
    cli.cookies.clear()
    val = _cookie_value(r)
    if val:
        cli.cookies.set(C.COOKIE_NAME, val)
    return r


def run():
    # 1) /api/health 标准信封 + needsBootstrap
    r = client.get("/api/health")
    j = r.json()
    ok(r.status_code == 200 and j.get("ok") is True and isinstance(j.get("data"), dict),
       "health 返回标准信封 {ok,data,message}")
    for key in ("provider", "llm", "needsBootstrap", "knowledge", "version"):
        ok(key in j["data"], "health.data 含字段 %s" % key)
    ok(j["data"]["needsBootstrap"] is True, "0 用户时 needsBootstrap=True")

    # 2) 未登录 → 401
    ok(client.get("/api/auth/me").status_code == 401, "未登录 /api/auth/me 返回 401")
    ok(client.get("/api/projects").status_code == 401, "未登录 /api/projects 返回 401")

    # 3) bootstrap 仅在 0 用户时可用
    r = client.post("/api/auth/bootstrap", json={
        "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "displayName": "安全测试管理员"})
    ok(r.status_code == 200 and r.json()["ok"], "bootstrap 创建首个管理员成功")
    client.cookies.clear()
    client.cookies.set(C.COOKIE_NAME, _cookie_value(r))
    ok(db.count_users() == 1, "库中只有 1 个用户")
    r = client.post("/api/auth/bootstrap", json={
        "email": "again@sec.local", "password": "xxxxxx", "displayName": "x"})
    ok(r.status_code == 400, "已存在用户时 bootstrap 返回 400")
    ok(client.get("/api/health").json()["data"]["needsBootstrap"] is False,
       "有用户后 needsBootstrap=False")

    # 4) 登出后旧 Cookie 失效(M8)
    r = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    ok(r.status_code == 200, "管理员登录成功")
    ok(client.get("/api/auth/me").status_code == 200, "登录态 /api/auth/me 正常")
    old_token = _cookie_value(r)
    ok(bool(old_token), "已下发会话 Cookie")
    r = client.post("/api/auth/logout")
    ok(r.status_code == 200, "登出成功")
    stale = TestClient(app)
    stale.cookies.set(C.COOKIE_NAME, old_token)
    ok(stale.get("/api/auth/me").status_code == 401,
       "登出后旧 Cookie 再请求 /api/auth/me 返回 401")

    # 5) 改密后旧 token 失效(M8)
    r = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    ok(r.status_code == 200, "重新登录成功")
    old_token = _cookie_value(r)
    r = client.post("/api/auth/password", json={
        "oldPassword": ADMIN_PASSWORD, "newPassword": NEW_PASSWORD})
    ok(r.status_code == 200, "修改密码成功")
    stale = TestClient(app)
    stale.cookies.set(C.COOKIE_NAME, old_token)
    ok(stale.get("/api/auth/me").status_code == 401, "改密后旧 token 再请求返回 401")
    r = _login(client, ADMIN_EMAIL, NEW_PASSWORD)
    ok(r.status_code == 200, "新密码可登录(携带新 token)")

    # 6) viewer 访问 /api/jobs 403(M9)
    r = client.post("/api/users", json={
        "email": VIEWER_EMAIL, "password": VIEWER_PASSWORD,
        "displayName": "只读用户", "role": "viewer"})
    ok(r.status_code == 200, "admin 创建 viewer 成功")
    r = client.get("/api/jobs")
    ok(r.status_code == 200, "admin 可访问 /api/jobs")
    vclient = TestClient(app)
    r = _login(vclient, VIEWER_EMAIL, VIEWER_PASSWORD)
    ok(r.status_code == 200, "viewer 登录成功")
    ok(vclient.get("/api/jobs").status_code == 403, "viewer 访问 /api/jobs 返回 403")

    # 7) 知识库按可见项目过滤(M9)
    admin_names = client.get("/api/knowledge/summary").json()["data"]["names"]
    viewer_names = vclient.get("/api/knowledge/summary").json()["data"]["names"]
    ok(viewer_names == [], "viewer(无可见项目)知识库 names 为空")
    ok(len(viewer_names) <= len(admin_names), "viewer 知识库条目不超过 admin")

    # 8) slug 大小写不敏感冲突(B6)
    r = client.post("/api/projects", json={
        "name": "SecProj", "title": "安全测试项目", "engineCode": "SECENG", "appCode": "", "h3Token": fake_h3_token()})
    ok(r.status_code == 200 and r.json()["ok"], "创建项目 SecProj 成功")
    pid = r.json()["data"]["id"]
    r = client.post("/api/projects", json={
        "name": "secproj", "title": "重复", "engineCode": "ENG", "appCode": "", "h3Token": ""})
    ok(r.status_code == 409, "slug 大小写冲突返回 409")

    # 9) 非法扩展名 400
    r = client.post("/api/projects/%d/documents" % pid,
                    files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
                    data={"kind": "other"})
    ok(r.status_code == 400, "非法扩展名上传返回 400")

    # 10) 上传超限 413(env H3AC_MAX_UPLOAD_MB=1,传 2MB)
    r = client.post("/api/projects/%d/documents" % pid,
                    files={"file": ("big.txt", b"a" * (2 * 1024 * 1024), "text/plain")},
                    data={"kind": "other"})
    ok(r.status_code == 413, "超过 1MB 上限返回 413")

    # 11) 合法小文件仍可上传(M7 未破坏既有逻辑)
    r = client.post("/api/projects/%d/documents" % pid,
                    files={"file": ("ok.txt", "需求正文".encode("utf-8"), "text/plain")},
                    data={"kind": "requirement"})
    ok(r.status_code == 200 and r.json()["ok"], "合法 txt 上传成功")


def main():
    try:
        run()
    except AssertionError as e:
        print("[FAIL] %s" % e)
        traceback.print_exc()
        return 1
    except Exception:
        print("[ERROR] 测试执行异常")
        traceback.print_exc()
        return 1
    finally:
        try:
            shutil.rmtree(TMP, ignore_errors=True)
        except Exception:
            pass
    print("=" * 60)
    for i, label in enumerate(PASSED, 1):
        print("  %2d. OK  %s" % (i, label))
    print("=" * 60)
    print("全部通过:%d 项断言" % len(PASSED))
    return 0


if __name__ == "__main__":
    sys.exit(main())
