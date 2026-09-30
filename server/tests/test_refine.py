# -*- coding: utf-8 -*-
"""AI 对话式微调 + 版本快照/回滚 + 阶段过期(stale)测试。

运行(工作目录 = server/):
    python -X utf8 tests/test_refine.py

覆盖:
  1. storage 快照/历史/阶段指纹(stage_src)与 stale 判定;
  2. plan/flowchart/design 三个 refine 函数(注入假 provider,不联网);
  3. API 层:PUT 记录快照 → refine 接口(异步任务)→ 产物更新 + 快照追加 + 下游 stale →
     /history 列表 → /history/restore 回滚 → /stages 状态。
使用独立临时环境,绝不触碰真实 server/data。
"""
import json
import os
import shutil
import sys
import tempfile
import time

SERVER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVER)

# ---- 独立临时环境 + 管理员 + 关闭环境变量 LLM(必须在导入 config 之前) ----
_TMP = tempfile.mkdtemp(prefix="h3ac_refine_test_")
os.environ["H3AC_DATA_DIR"] = _TMP
STAMP = "%d" % int(time.time())
ADMIN_EMAIL = "refine_%s@local" % STAMP
ADMIN_PASSWORD = "RefineTest123!"
os.environ["H3AC_ADMIN_EMAIL"] = ADMIN_EMAIL
os.environ["H3AC_ADMIN_PASSWORD"] = ADMIN_PASSWORD
for _k in ("H3AC_LLM_BASE_URL", "H3AC_LLM_API_KEY", "H3AC_LLM_MODEL"):
    os.environ[_k] = ""

from fastapi.testclient import TestClient          # noqa: E402

from app.core import config as C                    # noqa: E402
from app.db import database as db                   # noqa: E402
from app.main import app                            # noqa: E402
from app import storage                             # noqa: E402
from app.services import llm as llm_service         # noqa: E402
from app.services import plan as plan_service       # noqa: E402
from app.services import flowchart as fc_service     # noqa: E402
from app.services import design as design_service   # noqa: E402

# 显式把数据路径指向临时目录(双保险)
C.DATA_DIR = _TMP
C.UPLOAD_DIR = os.path.join(_TMP, "uploads")
C.DB_PATH = os.path.join(_TMP, "test.db")
C.SECRET_FILE = os.path.join(_TMP, "secret.key")
C.PROJECTS_DIR = os.path.join(_TMP, "projects")
C.KNOWLEDGE_DIR = os.path.join(_TMP, "knowledge")
C.LIBRARY_DIR = os.path.join(_TMP, "library")
C.LIBRARY_UPLOAD_DIR = os.path.join(_TMP, "library", "uploads")

_PASS, _FAIL = [], []


def check(tag, cond, detail=""):
    (_PASS if cond else _FAIL).append(tag)
    print("  %s %-46s %s" % ("[OK]" if cond else "[XX]", tag, detail))


# ---- 假 LLM Provider:按 system 特征识别阶段,返回合法产物 ----
class FakeProvider:
    name = "llm"
    available = True

    def complete(self, system, user, json_mode=False):
        if "《系统设计方案》的**编辑**" in system:
            return "# 模块甲\n## 表单甲\n业务内容:\n1. 已按用户指令微调后的内容,字段A、字段B。\n"
        if "业务流程图(Mermaid)的**编辑**" in system:
            return "flowchart LR\n  subgraph M1[\"模块甲\"]\n    direction TB\n    A[表单甲] --> B[表单乙]\n  end"
        if "ER 结构(JSON)的**编辑**" in system:
            return json.dumps({
                "sheets": [{"key": "t1", "title": "表甲", "layout": "auto4",
                            "controls": [{"type": "text", "key": "f1", "label": "字段甲(改)"},
                                         {"type": "text", "key": "f2", "label": "字段乙"}]}],
                "dicts": {}, "groups": [], "automations": [],
            }, ensure_ascii=False)
        return ""


_REAL_GET_PROVIDER = llm_service.get_provider


def _patch_llm():
    llm_service.get_provider = lambda: FakeProvider()


def _data(resp):
    try:
        return resp.json().get("data")
    except Exception:
        return None


def _run_job(c, resp):
    data = _data(resp)
    jid = (data or {}).get("job", {}).get("id")
    for _ in range(600):
        j = _data(c.get("/api/jobs/%s" % jid))
        if j and j.get("status") != "running":
            return j
        time.sleep(0.05)
    return {"status": "timeout", "result": {}, "error": "job timeout"}


PLAN_V1 = "# 模块甲\n## 表单甲\n业务内容:\n1. 字段A、字段B;\n"
MMD_V1 = "flowchart LR\n  subgraph M1[\"模块甲\"]\n    direction TB\n    A[表单甲]\n  end\n"
DESIGN_V1 = {"sheets": [{"key": "t1", "title": "表甲", "layout": "auto4",
                         "controls": [{"type": "text", "key": "f1", "label": "字段甲"}]}],
             "dicts": {}, "groups": [], "automations": []}


# ==================================================================
print("AI 微调/快照/回滚测试  tmp=%s" % _TMP)

# ---------- 1. storage 单元:快照/历史/指纹 ----------
print("\n[1] storage 快照与阶段指纹")
slug = "unit_proj"
storage.project_dir(slug, create=True)
storage.set_plan(slug, PLAN_V1)
storage.set_stage(slug, "plan")
check("快照写入返回 id", storage.record_snapshot(slug, "plan", PLAN_V1, origin="edit")["id"] != "")
storage.set_plan(slug, PLAN_V1 + "\n新增一行")
storage.record_snapshot(slug, "plan", PLAN_V1 + "\n新增一行", origin="refine", instruction="加一行")
hist = storage.list_history(slug, "plan")
check("历史有 2 条且最新在前", len(hist) == 2 and hist[0]["origin"] == "refine", str(len(hist)))
check("历史项含指令摘要", hist[0]["instruction"] == "加一行")
snap = storage.read_snapshot(slug, "plan", hist[1]["id"])
check("可读回指定快照原文", snap == PLAN_V1)

# 指纹 / stale:流程图 src = 方案 hash;方案变则流程图 stale
storage.set_flowchart(slug, MMD_V1)
storage.set_stage(slug, "flowchart", src=storage.stage_src(slug, "flowchart"))
check("刚记录后流程图非 stale", storage.get_stages(slug)["flowchart"]["stale"] is False)
storage.set_plan(slug, PLAN_V1 + "\n再改一次")
check("方案变后流程图 stale=True", storage.get_stages(slug)["flowchart"]["stale"] is True)
check("plan 阶段无 stale(恒 False)", storage.get_stages(slug)["plan"]["stale"] is False)

# ---------- 2. service refine(注入假 provider) ----------
print("\n[2] refine 服务函数")
fp = FakeProvider()
r = plan_service.refine_plan(PLAN_V1, "把字段A改成字段甲", provider=fp)
check("plan.refine 返回 markdown", r["markdown"].startswith("# 模块甲") and r["provider"] == "llm")
r = fc_service.refine_flowchart(MMD_V1, "加一条边", plan_markdown=PLAN_V1, provider=fp)
check("flowchart.refine 输出合法 mermaid", str(r.get("mermaid", "")).startswith("flowchart"))
r = design_service.refine_design(DESIGN_V1, "字段甲改名", provider=fp)
dkeys = [c["key"] for s in r["sheets"] for c in s.get("controls", [])]
check("design.refine 保留已有字段 key", "f1" in dkeys, str(dkeys))


# 违规 provider:把已有表 t1 改名/删字段
class BadProvider:
    name = "llm"
    available = True

    def complete(self, system, user, json_mode=False):
        if "ER 结构(JSON)的**编辑**" in system:
            return json.dumps({
                "sheets": [{"key": "t9", "title": "被改名", "layout": "auto4",
                            "controls": [{"type": "text", "key": "fx", "label": "x"}]}],
                "dicts": {}, "groups": [], "automations": [],
            }, ensure_ascii=False)
        return ""


try:
    design_service.refine_design(DESIGN_V1, "随便改改字段", provider=BadProvider())
    check("design.refine 拒绝已有编码变更", False)
except RuntimeError as e:
    check("design.refine 拒绝已有编码变更", "拒绝" in str(e) or "编码" in str(e), str(e)[:40])
# 删除意图**也不能**绕过守卫(删除请走 ER 编辑器)
try:
    design_service.refine_design(DESIGN_V1, "删除表甲这张表", provider=BadProvider())
    check("删除意图也拒绝(不绕过)", False)
except RuntimeError:
    check("删除意图也拒绝(不绕过)", True)

# 子表列 key 改动也要被拦
DESIGN_SUB = {"sheets": [{"key": "t1", "title": "表甲", "layout": "auto4", "controls": [
    {"type": "subtable", "key": "items", "label": "明细", "columns": [
        {"type": "text", "key": "srv", "label": "服务"}]}]}],
    "dicts": {}, "groups": [], "automations": []}


class SubRename:
    name = "llm"
    available = True

    def complete(self, system, user, json_mode=False):
        if "ER 结构(JSON)的**编辑**" in system:
            return json.dumps({"sheets": [{"key": "t1", "title": "表甲", "layout": "auto4",
                "controls": [{"type": "subtable", "key": "items", "label": "明细", "columns": [
                    {"type": "text", "key": "service", "label": "服务"}]}]}],
                "dicts": {}, "groups": [], "automations": []}, ensure_ascii=False)
        return ""


try:
    design_service.refine_design(DESIGN_SUB, "改动明细列", provider=SubRename())
    check("子表列改名被拦", False)
except RuntimeError:
    check("子表列改名被拦", True)

# 冻结集一致时:仅改显示名不改 key → 通过(带 frozen_keys,模拟已建表)
FP_PROVIDER_OUT = {"sheets": [{"key": "t1", "title": "表甲", "layout": "auto4", "controls": [
    {"type": "text", "key": "f1", "label": "字段甲改名后"}]}],
    "dicts": {}, "groups": [], "automations": []}


class RenameLabel:
    name = "llm"
    available = True

    def complete(self, system, user, json_mode=False):
        return json.dumps(FP_PROVIDER_OUT, ensure_ascii=False)


r = design_service.refine_design(DESIGN_V1, "把字段甲改个显示名", provider=RenameLabel(),
                                 frozen_keys={"t1"})
check("改显示名(保留 key)通过", r["sheets"][0]["controls"][0]["key"] == "f1")

# 无 LLM 时应报错
try:
    plan_service.refine_plan(PLAN_V1, "x", provider=llm_service.Provider())
    check("plan.refine 未配大模型须报错", False)
except RuntimeError:
    check("plan.refine 未配大模型须报错", True)

# ---------- 3. API 端到端 ----------
print("\n[3] API:微调 / 历史 / 回滚 / stages")
_patch_llm()
with TestClient(app) as c:
    c.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    name = "refine_%s" % STAMP
    c.post("/api/projects", json={"title": "微调测试项目", "name": name,
                                  "engineCode": "REFENG", "appCode": "", "h3Token": ""})
    p = db.get_project_by_slug(name)
    pid = p["id"]

    # 初版:方案 + 流程图 + ER
    c.put("/api/projects/%s/plan" % pid, json={"markdown": PLAN_V1})
    c.put("/api/projects/%s/flowchart" % pid, json={"mermaid": MMD_V1})
    c.put("/api/projects/%s/design" % pid, json=DESIGN_V1)

    st = _data(c.get("/api/projects/%s/stages" % pid))
    check("PUT 后 stages 含三阶段", all(k in st for k in ("plan", "flowchart", "design")), str(list(st)))
    check("初版流程图非 stale", st["flowchart"]["stale"] is False)

    # 微调方案(并验证不触碰其他阶段文件)
    flow_before = storage.read_text(name, "flowchart.mmd")
    design_before = storage.read_text(name, "design.json")
    j = _run_job(c, c.post("/api/projects/%s/plan/refine" % pid, json={"instruction": "调整表单甲"}))
    check("plan_refine 任务成功", j.get("status") == "done", j.get("error", ""))
    check("方案已被微调(内容变化)", storage.get_plan(name) != PLAN_V1)
    check("微调方案未触碰 flowchart.mmd", storage.read_text(name, "flowchart.mmd") == flow_before)
    check("微调方案未触碰 design.json", storage.read_text(name, "design.json") == design_before)
    st = _data(c.get("/api/projects/%s/stages" % pid))
    check("方案微调后流程图 stale=True", st["flowchart"]["stale"] is True)

    # 微调流程图
    j = _run_job(c, c.post("/api/projects/%s/flowchart/refine" % pid, json={"instruction": "加一条边"}))
    check("flowchart_refine 任务成功", j.get("status") == "done", j.get("error", ""))
    st = _data(c.get("/api/projects/%s/stages" % pid))
    check("流程图微调后 non-stale", st["flowchart"]["stale"] is False)

    # 微调 ER
    j = _run_job(c, c.post("/api/projects/%s/design/refine" % pid, json={"instruction": "字段甲改名"}))
    check("design_refine 任务成功", j.get("status") == "done", j.get("error", ""))
    d = storage.get_design(name)
    keys = [x["key"] for s in d["sheets"] for x in s.get("controls", [])]
    check("ER 微调保留已有 key(f1 未改名)", "f1" in keys, str(keys))

    # 历史与回滚
    items = _data(c.get("/api/projects/%s/history?stage=plan" % pid))["items"]
    check("方案历史含初版与微调版", len(items) >= 2)
    first_id = items[-1]["id"]  # 最早(初版)
    rr = c.post("/api/projects/%s/history/restore" % pid,
                json={"stage": "plan", "id": first_id})
    check("回滚接口成功", rr.status_code == 200)
    check("回滚后方案=初版", storage.get_plan(name) == PLAN_V1)
    items2 = _data(c.get("/api/projects/%s/history?stage=plan" % pid))["items"]
    check("回滚本身也记一条历史", len(items2) == len(items) + 1)

    # 未配 LLM 时 refine 应 400(恢复真实 get_provider)
    llm_service.get_provider = _REAL_GET_PROVIDER
    rb = c.post("/api/projects/%s/plan/refine" % pid, json={"instruction": "x"})
    check("未配大模型时 refine 返回 400", rb.status_code == 400, str(rb.status_code))

# ==================================================================
print("\n" + "=" * 62)
print("AI 微调测试:通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
if _FAIL:
    print("失败项:%s" % "、".join(_FAIL))
print("=" * 62)
shutil.rmtree(_TMP, ignore_errors=True)
sys.exit(1 if _FAIL else 0)
