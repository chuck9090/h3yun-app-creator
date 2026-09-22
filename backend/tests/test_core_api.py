# -*- coding: utf-8 -*-
"""核心 API 端到端冒烟测试(认证 / 用户 / 项目 / 文档 / 权限)。

运行:
    python -X utf8 backend/tests/test_core_api.py

测试使用独立临时 SQLite 与独立 projects 目录,不触碰开发数据。
"""
import base64
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

ADMIN_EMAIL = "admin@test.local"
ADMIN_PASSWORD = "admin123456"

os.environ["H3AC_SECRET"] = "h3ac-test-secret-not-for-production"
os.environ["H3AC_ADMIN_EMAIL"] = ADMIN_EMAIL
os.environ["H3AC_ADMIN_PASSWORD"] = ADMIN_PASSWORD
os.environ["H3AC_LLM_BASE_URL"] = ""
os.environ["H3AC_LLM_API_KEY"] = ""
os.environ["H3AC_LLM_MODEL"] = ""

from fastapi.testclient import TestClient            # noqa: E402

from app.core import config as C                     # noqa: E402
from app.db import database as db                    # noqa: E402

TMP = tempfile.mkdtemp(prefix="h3ac_test_")
C.DATA_DIR = os.path.join(TMP, "data")
C.DB_PATH = os.path.join(C.DATA_DIR, "test.db")
C.SECRET_FILE = os.path.join(C.DATA_DIR, "secret.key")
C.PROJECTS_DIR = os.path.join(TMP, "projects")
os.makedirs(C.DATA_DIR, exist_ok=True)

from app.main import app                            # noqa: E402

client = TestClient(app)                             # 不使用 with → 不触发 startup 自动建管理员
db.init_db()

PASSED = []


def ok(cond, label):
    if not cond:
        raise AssertionError("断言失败:%s" % label)
    PASSED.append(label)


def b64(obj):
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def fake_h3_token(enginecode="TESTENG", exp=9999999999, loginname="tester"):
    header = b64({"alg": "HS256", "typ": "JWT"})
    payload = b64({"enginecode": enginecode, "exp": exp, "loginname": loginname})
    return "%s.%s.x" % (header, payload)


def run():
    # 1) 未登录 → 401
    r = client.get("/api/auth/me")
    ok(r.status_code == 401, "未登录访问 /me 返回 401")

    # 2) bootstrap:仅当无用户
    r = client.post("/api/auth/bootstrap", json={
        "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "displayName": "测试管理员"})
    ok(r.status_code == 200 and r.json()["ok"], "bootstrap 初始化管理员成功")
    ok(r.json()["data"]["role"] == "admin", "bootstrap 返回 admin")
    ok(db.count_users() == 1, "库中只有 1 个用户")

    # 3) 再 bootstrap → 400
    r = client.post("/api/auth/bootstrap", json={
        "email": "x@test.local", "password": "xxxxxx", "displayName": "x"})
    ok(r.status_code == 400, "重复 bootstrap 返回 400")

    # 4) me
    r = client.get("/api/auth/me")
    ok(r.status_code == 200 and r.json()["data"]["email"] == ADMIN_EMAIL, "登录态 /me 正确")

    # 5) 用 login 再登录一次(验证密码校验)
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    ok(r.status_code == 200 and r.json()["ok"], "admin 登录成功")
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-pass"})
    ok(r.status_code == 401, "错误密码登录返回 401")

    # 6) 建普通用户(viewer)
    r = client.post("/api/users", json={
        "email": "viewer@test.local", "password": "viewer123",
        "displayName": "只读用户", "role": "viewer"})
    ok(r.status_code == 200 and r.json()["ok"], "admin 创建 viewer 用户成功")
    viewer_id = r.json()["data"]["id"]
    r = client.post("/api/users", json={
        "email": "viewer@test.local", "password": "viewer123",
        "displayName": "重复", "role": "viewer"})
    ok(r.status_code == 409, "重复邮箱创建用户返回 409")

    # 7) 非法 token 建项目 → 400
    r = client.post("/api/projects", json={
        "name": "bad_proj", "title": "坏项目", "engineCode": "ENG", "appCode": "APP1", "h3Token": "not-a-jwt"})
    ok(r.status_code == 400, "非法 h3_token 建项目返回 400")

    # 8) 非法 slug → 400
    r = client.post("/api/projects", json={
        "name": "1bad", "title": "坏 slug", "engineCode": "ENG", "appCode": "APP1", "h3Token": fake_h3_token()})
    ok(r.status_code == 400, "非法 slug 返回 400")

    # 9) 合法 JWT 建项目
    token = fake_h3_token()
    r = client.post("/api/projects", json={
        "name": "test_proj", "title": "测试项目", "engineCode": "ENG_TEST", "appCode": "APP_TEST", "h3Token": token})
    ok(r.status_code == 200 and r.json()["ok"], "创建项目成功")
    proj = r.json()["data"]
    pid = proj["id"]
    ok(proj["slug"] == "test_proj" and proj["hasToken"] is True, "项目返回 slug/hasToken")
    ok("h3_token" not in proj and "h3Token" not in proj, "项目响应不含 token 明文字段")
    ok(os.path.isdir(os.path.join(C.PROJECTS_DIR, "test_proj")), "项目工作区目录已创建")

    # slug 冲突 → 409
    r = client.post("/api/projects", json={
        "name": "test_proj", "title": "重复", "engineCode": "ENG", "appCode": "", "h3Token": ""})
    ok(r.status_code == 409, "slug 冲突返回 409")

    # 10) 项目列表
    r = client.get("/api/projects")
    ok(r.status_code == 200 and len(r.json()["data"]) == 1, "项目列表返回 1 条")
    ok(r.json()["data"][0]["canWrite"] is True, "owner canWrite=True")
    ok(r.json()["data"][0]["role"] == "designer", "owner role=designer")

    # 11) 上传 .txt 文档
    r = client.post("/api/projects/%d/documents" % pid,
                    files={"file": ("requirement.txt", "需求正文第一行\n\n\n第二行".encode("utf-8"),
                                    "text/plain")},
                    data={"kind": "requirement"})
    ok(r.status_code == 200 and r.json()["ok"], "上传 txt 文档成功")
    doc = r.json()["data"]
    ok(doc["parsedLength"] > 0 and "parsedText" not in doc, "上传响应只含长度不含全文")
    doc_id = doc["id"]

    # 非法 kind
    r = client.post("/api/projects/%d/documents" % pid,
                    files={"file": ("a.txt", b"x", "text/plain")},
                    data={"kind": "bogus"})
    ok(r.status_code == 400, "非法 kind 返回 400")

    # 12) 文档列表 / 详情
    r = client.get("/api/projects/%d/documents" % pid)
    ok(r.status_code == 200 and len(r.json()["data"]) == 1, "文档列表返回 1 条")
    r = client.get("/api/documents/%d" % doc_id)
    ok(r.status_code == 200 and "parsedText" in r.json()["data"], "文档详情含全文")
    ok("第二行" in r.json()["data"]["parsedText"], "txt 解析内容正确")

    # 13) 成员授权(viewer)
    r = client.post("/api/projects/%d/members" % pid, json={"userId": viewer_id, "role": "viewer"})
    ok(r.status_code == 200 and r.json()["ok"], "添加 viewer 成员成功")
    r = client.post("/api/projects/%d/members" % pid, json={"userId": viewer_id, "role": "boss"})
    ok(r.status_code == 400, "非法成员角色返回 400")

    # viewer 客户端
    vclient = TestClient(app)
    r = vclient.post("/api/auth/login", json={"email": "viewer@test.local", "password": "viewer123"})
    ok(r.status_code == 200, "viewer 登录成功")

    r = vclient.get("/api/projects")
    ok(r.status_code == 200 and len(r.json()["data"]) == 1, "viewer 能看到被授权项目")
    ok(r.json()["data"][0]["canWrite"] is False, "viewer canWrite=False")
    ok(r.json()["data"][0]["role"] == "viewer", "viewer role=viewer")

    r = vclient.get("/api/projects/%d" % pid)
    ok(r.status_code == 200, "viewer 可读取项目详情")
    r = vclient.get("/api/projects/%d/documents" % pid)
    ok(r.status_code == 200, "viewer 可读取文档列表")

    # 权限拒绝(写操作)
    r = vclient.post("/api/projects/%d/documents" % pid,
                     files={"file": ("x.txt", b"x", "text/plain")},
                     data={"kind": "other"})
    ok(r.status_code == 403, "viewer 上传文档返回 403")
    r = vclient.patch("/api/projects/%d" % pid, json={"title": "改名"})
    ok(r.status_code == 403, "viewer 修改项目返回 403")
    r = vclient.post("/api/projects/%d/members" % pid, json={"userId": 1, "role": "viewer"})
    ok(r.status_code == 403, "viewer 授权成员返回 403")

    # 14) 非 admin 访问用户管理
    r = vclient.get("/api/users")
    ok(r.status_code == 403, "viewer 访问用户管理返回 403")

    # 15) 改密码
    r = client.post("/api/auth/password", json={"oldPassword": "wrong", "newPassword": "abcdef"})
    ok(r.status_code == 400, "错误旧密码改密返回 400")
    r = client.post("/api/auth/password", json={"oldPassword": ADMIN_PASSWORD, "newPassword": "abcdef"})
    ok(r.status_code == 200, "修改密码成功")
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "abcdef"})
    ok(r.status_code == 200, "新密码可登录")

    # 16) logout
    r = client.post("/api/auth/logout")
    ok(r.status_code == 200, "登出成功")
    r = client.get("/api/auth/me")
    ok(r.status_code == 401, "登出后 /me 返回 401")

    # 重新登录做清理
    client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "abcdef"})

    # 17) 清理:移除成员 / 删除文档 / 删除项目 / 删除用户
    r = client.delete("/api/projects/%d/members/%d" % (pid, viewer_id))
    ok(r.status_code == 200, "移除成员成功")
    r = client.delete("/api/documents/%d" % doc_id)
    ok(r.status_code == 200, "删除文档成功")
    r = client.get("/api/documents/%d" % doc_id)
    ok(r.status_code == 404, "已删除文档返回 404")
    r = client.delete("/api/projects/%d" % pid)
    ok(r.status_code == 200, "删除项目成功")
    r = client.get("/api/projects/%d" % pid)
    ok(r.status_code == 404, "已删除项目返回 404")
    r = client.delete("/api/users/%d" % viewer_id)
    ok(r.status_code == 200, "删除用户成功")


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
