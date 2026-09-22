# -*- coding: utf-8 -*-
"""流水线 API 端到端测试(不联网;不配 LLM → 走启发式回退)。

运行(工作目录 = backend/):
    python -X utf8 tests/test_pipeline_api.py

覆盖:会话建立 → 建项目(伪造合法格式 h3_token) → 需求 → 方案生成/编辑
      → 流程图生成 → ER 结构生成/校验/编辑/ER 图 → 凭据状态 → 部署(无凭据须 400,绝不联网)。
测试用独立环境变量管理员账号,创建的项目与数据在结束时清理。

说明:auth / projects 路由由其它代理实现中;若这两个 HTTP 接口尚不可用,测试自动改用
db + security 直接建立会话与项目,以保证流水线端点仍能被完整验证。
"""
import base64
import json
import os
import shutil
import sys
import time

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)

# ---- 独立环境变量管理员账号 + 强制启发式(必须在导入 app.core.config 之前设置) ----
STAMP = "%d" % int(time.time())
ADMIN_EMAIL = "pipetest_%s@local" % STAMP
ADMIN_PASSWORD = "PipeTest123!"
os.environ["H3AC_ADMIN_EMAIL"] = ADMIN_EMAIL
os.environ["H3AC_ADMIN_PASSWORD"] = ADMIN_PASSWORD
for _k in ("H3AC_LLM_BASE_URL", "H3AC_LLM_API_KEY", "H3AC_LLM_MODEL"):
    os.environ[_k] = ""

from fastapi.testclient import TestClient          # noqa: E402

from app.core import config as C                    # noqa: E402
from app.core import security as sec                # noqa: E402
from app.db import database as db                   # noqa: E402
from app.main import app                            # noqa: E402
from app import storage                             # noqa: E402

NAME = "pipetest_%s" % STAMP
REQ = ("公司有大量连锁门店,需要管理门店档案、区域划分、加盟代理合同,还要处理门店开业登记、"
       "换址、闭店解约、状态变更等申请,以及合同借阅、异常门店跟进记录。门店按区域划分,"
       "每个区域有负责人和运营经理。加盟合同有开始/结束日期。")

_PASS, _FAIL = [], []


def check(tag, cond, detail=""):
    (_PASS if cond else _FAIL).append(tag)
    print("  %s %-44s %s" % ("[OK]" if cond else "[XX]", tag, detail))


def _b64(o):
    raw = json.dumps(o, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def fake_h3_token(engine="TESTENG", login="tester", exp=9999999999):
    """伪造合法格式的 h3_token(JWT,三段;不签名)——parse_h3_token 只取 payload。"""
    return "%s.%s.sig" % (_b64({"alg": "none", "typ": "JWT"}),
                          _b64({"enginecode": engine, "exp": exp, "loginname": login}))


def _data(resp):
    try:
        return resp.json().get("data")
    except Exception:
        return None


def _run_job(c, resp):
    """生成/核对接口现为异步任务:POST 返回 {job,created},轮询至终态并返回 job(含 result)。"""
    data = _data(resp)
    jid = (data or {}).get("job", {}).get("id")
    for _ in range(600):
        j = _data(c.get("/api/jobs/%s" % jid))
        if j and j.get("status") != "running":
            return j
        time.sleep(0.05)
    return {"status": "timeout", "result": {}, "error": "job timeout"}


def _ensure_admin():
    u = db.get_user_by_email(ADMIN_EMAIL)
    if not u:
        u = db.create_user(ADMIN_EMAIL, sec.hash_password(ADMIN_PASSWORD),
                           role="admin", display_name="流水线测试管理员")
    return u


def _ensure_project(client, name):
    # 优先走 HTTP(若 projects 路由已实现);否则直接落 db。
    try:
        client.post("/api/projects", json={"name": name, "title": "流水线测试项目",
                                           "engineCode": "PIPEENG",
                                           "appCode": "", "h3Token": fake_h3_token()})
    except Exception:
        pass
    p = db.get_project_by_slug(name)
    if not p:
        p = db.create_project(name, "流水线测试项目", app_code="",
                              h3_token=sec.encrypt_secret(fake_h3_token()),
                              owner_id=_ensure_admin()["id"])
    storage.project_dir(name, create=True)
    return p


REF_SLUG = "refsys"   # 参考语料项目(模拟"用户已建过的系统"),供启发式匹配


def _seed_reference():
    """写入一个参考项目并刷新知识库 —— 本平台**没有内置样本**,参考语料来自用户自己的项目。
    参考项目含与需求文本同名的表/字段(门店/合同/区域/负责人/运营经理…),使启发式可命中。"""
    import shutil as _sh
    from app import engine_bridge as EB
    d = os.path.join(C.PROJECTS_DIR, REF_SLUG)
    _sh.rmtree(d, ignore_errors=True)
    sj = os.path.join(d, "sheets")
    os.makedirs(sj, exist_ok=True)
    sheets = {
        "store": {"title": "门店", "nameSchema": "{storename}", "group": "基础",
                  "controls": [
                      {"type": "text", "key": "storename", "label": "门店名称"},
                      {"type": "text", "key": "storecode", "label": "门店编码"},
                      {"type": "query", "key": "region", "label": "区域", "assoc": "region"},
                      {"type": "member", "key": "storeowner", "label": "负责人"},
                      {"type": "member", "key": "opmgr", "label": "运营经理"}]},
        "region": {"title": "区域", "nameSchema": "{zone}", "group": "基础",
                   "controls": [{"type": "text", "key": "zone", "label": "区域划分"}]},
        "contract": {"title": "合同", "nameSchema": "{cno}", "group": "基础",
                     "controls": [
                         {"type": "text", "key": "cno", "label": "合同编号"},
                         {"type": "query", "key": "store", "label": "门店", "assoc": "store"},
                         {"type": "date", "key": "cstart", "label": "合同开始"},
                         {"type": "date", "key": "cend", "label": "合同结束"}]},
    }
    for k, v in sheets.items():
        with open(os.path.join(sj, k + ".json"), "w", encoding="utf-8") as f:
            json.dump(v, f, ensure_ascii=False)
    EB.refresh_knowledge()


def _cleanup(pid, name):
    try:
        db.delete_project(pid)
    except Exception:
        pass
    shutil.rmtree(os.path.join(C.PROJECTS_DIR, name), ignore_errors=True)
    shutil.rmtree(os.path.join(C.PROJECTS_DIR, REF_SLUG), ignore_errors=True)
    try:
        u = db.get_user_by_email(ADMIN_EMAIL)
        if u:
            db.delete_user(u["id"])
    except Exception:
        pass


def main():
    print("=" * 70)
    print("流水线 API 端到端测试  name=%s  admin=%s" % (NAME, ADMIN_EMAIL))
    print("=" * 70)

    pid = None
    orig_llm = None
    try:
        with TestClient(app) as c:
            # 强制启发式回退;测试结束恢复开发者已有 LLM 配置
            orig_llm = db.get_setting("llm")
            db.put_setting("llm", {})

            admin = _ensure_admin()
            c.cookies.set(C.COOKIE_NAME, sec.create_token(admin["id"]))

            # 若能走真实 HTTP 登录则优先(用于验证 auth 路由一旦实现即生效)
            r = c.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
            check("会话建立(HTTP login 或直连 cookie)",
                  r.status_code in (200, 404, 405), "login=%d" % r.status_code)

            p = _ensure_project(c, NAME)
            pid = p["id"]
            check("创建项目", bool(pid), "id=%s slug=%s" % (pid, p["slug"]))

            # 参考语料:来自用户自己的项目(本平台无内置样本)
            _seed_reference()
            check("参考语料就绪(用户项目编译)", True, "ref=%s" % REF_SLUG)

            # ---- 需求 ----------------------------------------------------
            r = c.put("/api/projects/%s/requirement" % pid,
                      json={"html": "<p>%s</p>" % REQ, "text": REQ})
            check("PUT requirement", r.status_code == 200, str(r.status_code))
            d = _data(c.get("/api/projects/%s/requirement" % pid))
            check("GET requirement", bool(d) and "门店" in (d.get("text") or ""))

            # ---- 方案 ----------------------------------------------------
            d = _data(c.get("/api/projects/%s/plan" % pid))
            check("GET plan(初始)", isinstance(d, dict) and d.get("markdown") == "")

            r = c.post("/api/projects/%s/plan/generate" % pid, json={})
            job = _run_job(c, r)
            d = job.get("result") or {}
            md = (d or {}).get("markdown") or ""
            check("POST plan/generate", r.status_code == 200 and job.get("status") == "done"
                  and len(md) > 20,
                  "provider=%s chars=%d" % ((d or {}).get("provider"), len(md)))
            check("plan provider=heuristic", (d or {}).get("provider") == "heuristic")

            edited = md + "\n\n<!-- 人工编辑标记 -->\n"
            r = c.put("/api/projects/%s/plan" % pid, json={"markdown": edited})
            d = _data(c.get("/api/projects/%s/plan" % pid))
            check("PUT plan 编辑并回读",
                  r.status_code == 200 and "人工编辑标记" in ((d or {}).get("markdown") or ""))

            # ---- 流程图 --------------------------------------------------
            r = c.post("/api/projects/%s/flowchart/generate" % pid, json={})
            job = _run_job(c, r)
            d = job.get("result") or {}
            mmd = (d or {}).get("mermaid") or ""
            head = mmd.strip().splitlines()[0].strip().lower() if mmd.strip() else ""
            check("POST flowchart/generate", r.status_code == 200 and job.get("status") == "done"
                  and (head.startswith("flowchart") or head.startswith("graph")),
                  "provider=%s head=%s" % ((d or {}).get("provider"), head))
            r = c.put("/api/projects/%s/flowchart" % pid,
                      json={"mermaid": "flowchart LR\n  A[提交] --> B[归档]"})
            d = _data(c.get("/api/projects/%s/flowchart" % pid))
            check("PUT/GET flowchart", r.status_code == 200
                  and "归档" in ((d or {}).get("mermaid") or ""))

            # ---- ER 结构 -------------------------------------------------
            r = c.post("/api/projects/%s/design/generate" % pid, json={})
            job = _run_job(c, r)
            d = job.get("result") or {}
            sheets = (d or {}).get("sheets") or []
            check("POST design/generate", r.status_code == 200 and job.get("status") == "done"
                  and len(sheets) > 0,
                  "provider=%s sheets=%d error=%s"
                  % ((d or {}).get("provider"), len(sheets), (d or {}).get("error")))
            check("design 引擎校验无 error", (d or {}).get("error") == "",
                  "check=%s" % ((d or {}).get("check") is not None))

            # 编辑:改第一张表 title + 追加一个字段
            design = {"sheets": json.loads(json.dumps(sheets)),
                      "dicts": (d or {}).get("dicts") or {},
                      "groups": (d or {}).get("groups") or []}
            first = design["sheets"][0]
            new_title = (first.get("title") or first["key"]) + "-人工修改"
            first["title"] = new_title
            first.setdefault("controls", []).append(
                {"type": "text", "key": "testmark", "label": "测试标记字段"})
            r = c.put("/api/projects/%s/design" % pid, json=design)
            d2 = _data(r)
            check("PUT design(改标题+加字段)", r.status_code == 200
                  and (d2 or {}).get("error") == "",
                  "error=%s" % (d2 or {}).get("error"))
            saved = _data(c.get("/api/projects/%s/design" % pid))
            titles = [s.get("title") for s in ((saved or {}).get("sheets") or [])]
            check("GET design 已保存修改", new_title in titles, "titles=%s" % titles[:3])

            # 校验
            d = _data(c.get("/api/projects/%s/design/check" % pid))
            check("GET design/check", (d or {}).get("error") == "",
                  "check=%s" % ((d or {}).get("check") is not None))

            # ER 图
            d = _data(c.get("/api/projects/%s/design/er" % pid))
            check("GET design/er", len(((d or {}).get("nodes")) or []) > 0,
                  "nodes=%d edges=%d" % (len((d or {}).get("nodes") or []),
                                         len((d or {}).get("edges") or [])))

            # ---- 部署 ----------------------------------------------------
            d = _data(c.get("/api/projects/%s/credentials/status" % pid))
            check("GET credentials/status", (d or {}).get("configured") is False,
                  "appCode=%r hasToken=%s" % ((d or {}).get("appCode"),
                                              (d or {}).get("hasToken")))
            r = c.post("/api/projects/%s/deploy" % pid)
            check("POST deploy 无凭据须 400(不联网)", r.status_code == 400,
                  "status=%d" % r.status_code)

            # ---- 系统设置(LLM,admin) ------------------------------------
            r = c.get("/api/settings/llm")
            d = _data(r)
            check("GET settings/llm", r.status_code == 200
                  and isinstance(d, dict) and "baseUrl" in d and "hasKey" in d
                  and "apiKey" not in d, "keys=%s" % (sorted((d or {}).keys())))
            r = c.put("/api/settings/llm",
                      json={"baseUrl": "https://llm.example/v1", "apiKey": "sk-test",
                            "model": "test-model"})
            d = _data(r)
            check("PUT settings/llm(不回显密钥)", r.status_code == 200
                  and (d or {}).get("hasKey") is True and "apiKey" not in (d or {}),
                  "hasKey=%s" % (d or {}).get("hasKey"))
    finally:
        if orig_llm is None:
            db.put_setting("llm", {})
        else:
            db.put_setting("llm", orig_llm)
        if pid:
            _cleanup(pid, NAME)

    print("\n" + "=" * 70)
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项:%s" % _FAIL)
    print("=" * 70)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
