# -*- coding: utf-8 -*-
"""真实进程集成冒烟:启动 uvicorn 真实端口,走 Cookie 会话跑完整流水线。

    python -X utf8 tests/smoke_real_server.py

覆盖:健康检查 → 初始化/登录(Cookie) → 建项目(解析 h3_token) → 上传文档
      → 需求 → 方案 → 流程图 → ER → 校验 → 部署(未配置应 400)。
不联网建表。
"""
import base64
import json
import os
import subprocess
import sys
import time

import httpx

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BACKEND)
PORT = int(os.environ.get("H3AC_SMOKE_PORT", "8899"))
BASE = "http://127.0.0.1:%d" % PORT
ADMIN = ("smoke_admin@local", "smoke12345")
PWD = os.path.dirname(os.path.abspath(__file__))


def fake_token(engine="SMOKEENG"):
    def b64(o):
        return base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()
    return "%s.%s.sig" % (b64({"alg": "none"}),
                          b64({"enginecode": engine, "exp": 9999999999,
                               "loginname": "smoke"}))


def run_job(c, resp):
    """生成/核对接口是异步任务:POST 返回 {job,created},轮询至终态并返回 job(含 result)。"""
    data = (resp.json() or {}).get("data") or {}
    jid = (data.get("job") or {}).get("id")
    job = {}
    for _ in range(600):
        job = c.get("/api/jobs/%s" % jid).json().get("data") or {}
        if job.get("status") != "running":
            return job
        time.sleep(0.2)
    return job


# 参考系统设计(表/字段名与冒烟需求文本同词,便于启发式匹配)
REF_DESIGN = {
    "dicts": {}, "groups": ["基础"], "automations": [],
    "sheets": [
        {"key": "store", "title": "门店", "nameSchema": "{storename}", "group": "基础",
         "controls": [
             {"type": "text", "key": "storename", "label": "门店名称"},
             {"type": "query", "key": "region", "label": "区域", "assoc": "region"},
             {"type": "member", "key": "storeowner", "label": "负责人"}]},
        {"key": "region", "title": "区域", "nameSchema": "{zone}", "group": "基础",
         "controls": [{"type": "text", "key": "zone", "label": "区域划分"}]},
        {"key": "contract", "title": "合同", "nameSchema": "{cno}", "group": "基础",
         "controls": [
             {"type": "text", "key": "cno", "label": "合同编号"},
             {"type": "query", "key": "store", "label": "门店", "assoc": "store"},
             {"type": "member", "key": "person", "label": "人员"}]},
    ],
}


def main():
    env = dict(os.environ)
    env["H3AC_ADMIN_EMAIL"] = ADMIN[0]
    env["H3AC_ADMIN_PASSWORD"] = ADMIN[1]
    env["H3AC_SMOKE"] = "1"
    proc = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "uvicorn",
                             "app.main:app", "--host", "127.0.0.1", "--port", str(PORT),
                             "--log-level", "warning"],
                            cwd=BACKEND, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    ok, fail = [], []

    def chk(tag, cond, detail=""):
        (ok if cond else fail).append(tag)
        print("  %s %-34s %s" % ("[OK]" if cond else "[XX]", tag, detail))

    try:
        for _ in range(60):
            try:
                httpx.get(BASE + "/api/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        with httpx.Client(base_url=BASE, timeout=30, follow_redirects=True) as c:
            h = c.get("/api/health").json()
            hd = h.get("data") or {}
            chk("health", h.get("ok"), "needsBootstrap=%s" % hd.get("needsBootstrap"))

            r = c.post("/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
            if r.status_code != 200:
                r = c.post("/api/auth/bootstrap",
                           json={"email": ADMIN[0], "password": ADMIN[1], "displayName": "smoke"})
            chk("login/bootstrap(cookie)", r.status_code == 200, str(r.status_code))
            chk("cookie set", any(k for k in c.cookies.keys()), list(c.cookies.keys()))

            me = c.get("/api/auth/me").json()
            chk("auth/me", me.get("ok"), me.get("data", {}).get("email"))

            # 参考语料:本平台无内置样本,先建一个"用户已建过的系统"并编译知识库,
            # 使启发式(未配 LLM)有可匹配的同类项目。
            ref = c.post("/api/projects", json={"name": "refsys", "title": "参考系统",
                                                "engineCode": "REFENG",
                                                "appCode": "", "h3Token": fake_token()})
            ref_pid = (ref.json().get("data") or {}).get("id")
            if ref_pid:
                c.put("/api/projects/%d/design" % ref_pid, json=REF_DESIGN)
                c.post("/api/knowledge/refresh")
                chk("参考语料就绪", True, "refsys")
            else:
                chk("参考语料就绪", False, "建参考项目失败")

            slug = "smoke_real_%d" % (int(time.time()) % 100000)
            # appCode 故意留空:凭据判定为"未配置",deploy 应 400 —— 保证冒烟**不发起真实联网**
            r = c.post("/api/projects", json={"name": slug, "title": "冒烟项目",
                                              "engineCode": "SMOKEENG",
                                              "appCode": "", "h3Token": fake_token()})
            chk("create project", r.status_code == 200, str(r.status_code))
            pid = r.json()["data"]["id"]
            chk("token not echoed", "h3Token" not in json.dumps(r.json()),
                "hasToken=%s" % r.json()["data"].get("hasToken"))

            r = c.post("/api/projects/%d/documents" % pid,
                       files={"file": ("需求.txt", "客户 合同 项目 门店 人员".encode("utf-8"),
                                       "text/plain")}, data={"kind": "requirement"})
            chk("upload document", r.status_code == 200, str(r.status_code))

            c.put("/api/projects/%d/requirement" % pid,
                  json={"html": "<p>门店合同项目系统</p>", "text": "门店 合同 项目 人员"})
            job = run_job(c, c.post("/api/projects/%d/plan/generate" % pid, json={}))
            md = (job.get("result") or {}).get("markdown") or ""
            chk("plan/generate", job.get("status") == "done" and len(md) > 100,
                "provider=%s" % (job.get("result") or {}).get("provider"))
            chk("plan 进度含百分比", any(isinstance(p.get("pct"), (int, float))
                                     for p in job.get("progress") or []),
                "%d 步" % len(job.get("progress") or []))

            job = run_job(c, c.post("/api/projects/%d/flowchart/generate" % pid, json={}))
            mmd = (job.get("result") or {}).get("mermaid") or ""
            chk("flowchart/generate", mmd.strip().lower().startswith(("flowchart", "graph")),
                mmd.splitlines()[0] if mmd else "")

            job = run_job(c, c.post("/api/projects/%d/design/generate" % pid, json={}))
            design = job.get("result") or {}
            chk("design/generate", job.get("status") == "done" and design.get("sheets"),
                "sheets=%d err=%s" % (len(design.get("sheets", [])),
                                      (design.get("error") or "")[:40]))
            sheets = design.get("sheets") or []
            if sheets:
                # 同表自更新:match/set 引用的字段都在该表内,语义有效
                s0 = sheets[0]
                f0 = (s0.get("controls") or [{}])[0].get("key") or "id"
                design["automations"] = [{
                    "key": "a1", "title": "冒烟自动化", "form": s0["key"],
                    "trigger": "生效或更新",
                    "actions": [{"do": "更新", "target": s0["key"],
                                 "match": [{"field": f0, "ref": f0}],
                                 "set": [{"to": f0, "from": f0}]}]}]
            r = c.put("/api/projects/%d/design" % pid, json=design).json()
            chk("design 保存(含自动化)", r.get("ok") and len(r["data"]["automations"]) == 1
                and not r["data"].get("error"),
                "auto=%d err=%s" % (len(r["data"].get("automations", [])),
                                    (r["data"].get("error") or "")[:50]))
            d2 = c.get("/api/projects/%d/design" % pid).json()["data"]
            chk("design 回读自动化", len(d2.get("automations") or []) == 1)
            ck = c.get("/api/projects/%d/design/check" % pid).json()["data"]
            chk("design/check 单层且含自动化", isinstance(ck.get("sheets"), list)
                and len(ck.get("automations") or []) == 1,
                "sheets=%d auto=%d err=%s" % (len(ck.get("sheets") or []),
                                              len(ck.get("automations") or []),
                                              (ck.get("error") or "")[:40]))

            er = c.get("/api/projects/%d/design/er" % pid).json()["data"]
            chk("design/er", er["nodes"], "nodes=%d edges=%d" % (len(er["nodes"]), len(er["edges"])))

            r = c.post("/api/projects/%d/deploy" % pid, json={})
            chk("deploy blocked (no appCode, 不联网)", r.status_code == 400, str(r.status_code))
            cs = c.get("/api/projects/%d/credentials/status" % pid).json()["data"]
            chk("credentials status", cs.get("configured") is False,
                "appCode=%r tokenValid=%s" % (cs.get("appCode"), cs.get("tokenValid")))

            c.delete("/api/projects/%d" % pid)
            if ref_pid:
                c.delete("/api/projects/%d" % ref_pid)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print("\n" + "=" * 62)
    print("真实服务冒烟:通过 %d / 失败 %d" % (len(ok), len(fail)))
    if fail:
        print("失败项:", fail)
    print("=" * 62)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
