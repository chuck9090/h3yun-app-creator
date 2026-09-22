# -*- coding: utf-8 -*-
"""资料库 API + library.md 刷新(F3) + 夜间整理标记(F4) + 角色门槛(F8) 回归测试。

运行(工作目录 = backend/):
    python -X utf8 tests/test_library.py

覆盖 TODO F14 第 6/7 项:
  1. library API:重名 409;非创建者非 admin 改/删他人资料 403;上传+删除清文件顺序;
  2. 删除资料后 library.md 立即刷新(F3)——删除后不再含该资料名;
  3. 夜间超 _MAX_TOTAL_CHARS 时只把真正入模的文档标 learned,其余保持 pending(F4);
  4. viewer 作为创建者调用 analyze 不再 403(F8)。

使用独立 tempfile 环境(DB/密钥/项目/资料库/知识库全部重定向),不联网、强制无 LLM。
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# ---- 强制无 LLM(必须在导入 app.core.config 之前设置) ----
os.environ["H3AC_ADMIN_EMAIL"] = "libtest_admin@local"
os.environ["H3AC_ADMIN_PASSWORD"] = "LibTest123!"
for _k in ("H3AC_LLM_BASE_URL", "H3AC_LLM_API_KEY", "H3AC_LLM_MODEL"):
    os.environ[_k] = ""

from fastapi.testclient import TestClient          # noqa: E402

from app.core import config as C                    # noqa: E402
from app.core import security as sec                # noqa: E402
from app.db import database as db                   # noqa: E402

# ---- 独立 tempfile 环境:全部数据目录重定向,绝不污染真实 data/ ----
TMP = tempfile.mkdtemp(prefix="h3ac_lib_test_")
C.DATA_DIR = os.path.join(TMP, "data")
C.DB_PATH = os.path.join(C.DATA_DIR, "test.db")
C.SECRET_FILE = os.path.join(C.DATA_DIR, "secret.key")
C.PROJECTS_DIR = os.path.join(TMP, "projects")
C.LIBRARY_DIR = os.path.join(C.DATA_DIR, "library")
C.LIBRARY_UPLOAD_DIR = os.path.join(C.LIBRARY_DIR, "uploads")
C.KNOWLEDGE_DIR = os.path.join(C.DATA_DIR, "knowledge")
os.makedirs(C.DATA_DIR, exist_ok=True)

from app.main import app                            # noqa: E402
from app.services import library as libsvc          # noqa: E402
from app.services import llm as llm_mod             # noqa: E402
from app.services import nightly                    # noqa: E402

STAMP = "%d" % int(time.time())
client = TestClient(app)                            # 不用 with → 不触发 startup 建管理员
db.init_db()

_PASS, _FAIL = [], []


def check(tag, cond, detail=""):
    (_PASS if cond else _FAIL).append(tag)
    print("  %s %-46s %s" % ("[OK]" if cond else "[XX]", tag, detail))


def _data(resp):
    try:
        return resp.json().get("data")
    except Exception:
        return None


def _mk_user(email, role, name):
    u = db.get_user_by_email(email)
    if not u:
        u = db.create_user(email, sec.hash_password("Test12345!"), role=role, display_name=name)
    return u


def _login(cli, uid):
    cli.cookies.set(C.COOKIE_NAME, sec.create_token(uid))


def _create_item(cli, name, desc=""):
    r = cli.post("/api/library/items", json={"name": name, "description": desc})
    return r, _data(r)


def _upload(cli, item_id, filename, content):
    return cli.post("/api/library/items/%d/documents" % item_id,
                    files={"file": (filename, content.encode("utf-8"), "text/plain")})


def _library_md():
    p = os.path.join(C.KNOWLEDGE_DIR, "library.md")
    if not os.path.isfile(p):
        return ""
    with open(p, encoding="utf-8") as f:
        return f.read()


class _FakeProvider:
    """可用但离线的假 provider:直接返回结构化 analysis,不联网。"""
    name = "fake"
    available = True

    def complete(self, system, user, json_mode=False):
        return json.dumps({"analysis": "## 假整理\n- 业务领域:测试\n- 功能模块:测试"},
                          ensure_ascii=False)


def main():
    print("=" * 72)
    print("资料库 API / F3 / F4 / F8 回归测试")
    print("=" * 72)

    admin = _mk_user("libtest_admin@local", "admin", "资料库测试管理员")
    designer = _mk_user("libtest_designer@local", "designer", "资料库测试设计者")
    viewer = _mk_user("libtest_viewer@local", "viewer", "资料库测试只读用户")

    _login(client, admin["id"])
    dclient = TestClient(app)
    _login(dclient, designer["id"])
    vclient = TestClient(app)
    _login(vclient, viewer["id"])

    try:
        # ============================================================ 1. API 基础/权限
        name1 = "基础资料_%s" % STAMP
        r, it1 = _create_item(client, name1, "基础资料描述")
        check("创建资料", r.status_code == 200 and it1 and it1.get("name") == name1,
              "status=%d" % r.status_code)
        iid1 = it1["id"]

        r, _ = _create_item(client, name1, "重名")
        check("重名创建返回 409", r.status_code == 409, "status=%d" % r.status_code)

        r = dclient.patch("/api/library/items/%d" % iid1, json={"description": "篡改"})
        check("非创建者非 admin 改他人资料 403", r.status_code == 403, "status=%d" % r.status_code)
        r = dclient.delete("/api/library/items/%d" % iid1)
        check("非创建者非 admin 删他人资料 403", r.status_code == 403, "status=%d" % r.status_code)

        # 上传 + 删除清文件顺序
        r = _upload(client, iid1, "base.txt", "第一行内容\n第二行内容")
        doc = _data(r)
        check("上传资料文档", r.status_code == 200 and doc and doc.get("id"), "status=%d" % r.status_code)
        doc_id = doc["id"]
        stored = db.get_document(doc_id)["stored_path"]
        check("上传原件已落盘", os.path.isfile(stored), "path=%s" % os.path.basename(stored))
        r = client.delete("/api/library/documents/%d" % doc_id)
        check("删除文档成功", r.status_code == 200, "status=%d" % r.status_code)
        check("删除后原件文件不存在", not os.path.isfile(stored))
        check("删除后 DB 无该文档记录", db.get_document(doc_id) is None)

        # ============================================================ 2. F3:删除后 library.md 刷新
        name3 = "刷新测试资料_%s" % STAMP
        r, it3 = _create_item(client, name3, "删除后应清出知识库")
        iid3 = it3["id"]
        _upload(client, iid3, "refresh.txt", "该资料正文内容ABC")
        md = _library_md()
        check("F3 创建/上传后 library.md 含该资料", name3 in md)
        libsvc.render_library_digest()          # 确保当前状态已编译入库
        check("F3 手动重编译后仍含该资料", name3 in _library_md())
        r = client.delete("/api/library/items/%d" % iid3)
        check("删除资料成功", r.status_code == 200, "status=%d" % r.status_code)
        md_after = _library_md()
        check("F3 删除后 library.md 不再含该资料", name3 not in md_after)

        # ============================================================ 3. F8:viewer 创建者 analyze
        name8 = "viewer资料_%s" % STAMP
        r, it8 = _create_item(vclient, name8, "viewer 创建")
        check("F8 viewer 可创建资料", r.status_code == 200, "status=%d" % r.status_code)
        iid8 = it8["id"]
        r = _upload(vclient, iid8, "v.txt", "viewer 上传的文档")
        check("F8 viewer 创建者可上传文档", r.status_code == 200, "status=%d" % r.status_code)
        r = vclient.post("/api/library/items/%d/analyze" % iid8)
        check("F8 viewer(创建者)analyze 不再 403", r.status_code == 200, "status=%d" % r.status_code)
        r = vclient.post("/api/library/items/%d/analyze" % iid1)
        check("F8 viewer(非创建者)analyze 仍 403", r.status_code == 403, "status=%d" % r.status_code)

        # ============================================================ 4. F4:只标真正入模的文档
        name4 = "F4测试资料_%s" % STAMP
        r, it4 = _create_item(client, name4, "超长文档集")
        iid4 = it4["id"]
        big = "x" * nightly._MAX_DOC_CHARS         # 每份正文 = 单文件上限
        doc_ids = []
        for k in range(4):
            d = db.add_document(None, "existing_system", "big%d.txt" % k,
                                os.path.join(C.LIBRARY_UPLOAD_DIR, "big%d.txt" % k),
                                ".txt", len(big), parsed_text=big,
                                uploaded_by=str(admin["id"]), library_id=iid4)
            doc_ids.append(d["id"])
        fake = _FakeProvider()
        item4 = db.get_library_item(iid4)
        docs4 = db.list_library_documents(iid4)
        _md, used = nightly._analyze_item(fake, item4, docs4)
        check("F4 _analyze_item 返回 (markdown, used_ids)",
              isinstance(used, list) and 0 < len(used) < len(docs4),
              "used=%d / docs=%d" % (len(used), len(docs4)))
        check("F4 used_ids 是真正入模的前缀子集", used == doc_ids[:len(used)],
              "used=%s" % used)

        # analyze_library_item:只标 used_ids
        orig_get_provider = llm_mod.get_provider
        llm_mod.get_provider = lambda: fake
        try:
            res = nightly.analyze_library_item(iid4)
        finally:
            llm_mod.get_provider = orig_get_provider
        check("F4 analyze_library_item 成功", bool(res.get("ok")), "res=%s" % (res.get("ok"),))
        learned_ok, pending_ok = True, True
        for did in doc_ids:
            st = db.get_document(did)["status"]
            if did in used:
                learned_ok = learned_ok and (st == "learned")
            else:
                pending_ok = pending_ok and (st != "learned")
        check("F4 analyze 只把 used_ids 标 learned", learned_ok)
        check("F4 analyze 未入模文档保持非 learned", pending_ok,
              "status=%s" % [db.get_document(d)["status"] for d in doc_ids])

        # nightly_learn:再次整理也不得把未入模文档标 learned
        llm_mod.get_provider = lambda: fake
        try:
            nightly.nightly_learn("test")
        finally:
            llm_mod.get_provider = orig_get_provider
        tail_ok = all(db.get_document(d)["status"] != "learned" for d in doc_ids if d not in used)
        check("F4 nightly_learn 未入模文档仍非 learned(下次待处理)", tail_ok,
              "status=%s" % [db.get_document(d)["status"] for d in doc_ids])
    finally:
        try:
            shutil.rmtree(TMP, ignore_errors=True)
        except Exception:
            pass

    print("\n" + "=" * 72)
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项:%s" % _FAIL)
    print("=" * 72)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
