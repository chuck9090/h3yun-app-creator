# -*- coding: utf-8 -*-
"""参考资料上下文 单元/回归测试(不联网;独立临时环境,绝不写真实 data)。

运行(工作目录 = backend/):
    python -X utf8 tests/test_context.py

覆盖 TODO F14 的 1/2/3/4/8,以及本轮修复:
  F2  _truncate_tokens 中文按 token 截断且不超预算;
  F11 CTX_CATALOG_THRESHOLD < CTX_TOKEN_BUDGET 时的预期行为;
  F13 catalog 模式首件超预算仍受预算约束;
  F1  fit_reference 合并资料库正文 + 项目参考正文的总预算不变量;
  F12 (附加) 抽取缓存随「事后启用视觉」失效。
"""
import json
import os
import shutil
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

# ---- 独立临时环境(必须在导入 app.core.config 之前设置) ----
_TMP = tempfile.mkdtemp(prefix="h3ac_ctx_test_")
os.environ["H3AC_DATA_DIR"] = _TMP
for _k in ("H3AC_LLM_BASE_URL", "H3AC_LLM_API_KEY", "H3AC_LLM_MODEL"):
    os.environ[_k] = ""

from app.core import config as C                    # noqa: E402

# 显式把全部数据路径指向临时目录,确保不触碰真实 data
C.DATA_DIR = _TMP
C.UPLOAD_DIR = os.path.join(_TMP, "uploads")
C.DB_PATH = os.path.join(_TMP, "test.db")
C.SECRET_FILE = os.path.join(_TMP, "secret.key")
C.PROJECTS_DIR = os.path.join(_TMP, "projects")
C.KNOWLEDGE_DIR = os.path.join(_TMP, "knowledge")
C.LIBRARY_DIR = os.path.join(_TMP, "library")
C.LIBRARY_UPLOAD_DIR = os.path.join(_TMP, "library", "uploads")

from app.db import database as db                   # noqa: E402
from app.services import context as ctx             # noqa: E402
from app.services import llm                        # noqa: E402
from app.services import plan as plan_service       # noqa: E402
from app.services import design as design_service   # noqa: E402
from app.services import flowchart as flowchart_service  # noqa: E402
from app.api import pipeline                        # noqa: E402

_PASS, _FAIL = [], []


def check(tag, cond, detail=""):
    (_PASS if cond else _FAIL).append(tag)
    print("  %s %-48s %s" % ("[OK]" if cond else "[XX]", tag, detail))


# ---------------------------------------------------------------- 配置临时覆盖
_CFG_SAVED = {}


def _set_cfg(**kw):
    for k, v in kw.items():
        if k not in _CFG_SAVED:
            _CFG_SAVED[k] = getattr(C, k)
        setattr(C, k, v)


def _restore_cfg():
    for k, v in _CFG_SAVED.items():
        setattr(C, k, v)
    _CFG_SAVED.clear()


# ---------------------------------------------------------------- 1. estimate_tokens
def t_estimate():
    e = ctx.estimate_tokens
    check("estimate:空串=0", e("") == 0, "got=%s" % e(""))
    check("estimate:纯中文(中文=2字)", e("中文") == 3, "got=%s" % e("中文"))
    check("estimate:纯 ASCII(abcd)", e("abcd") == 2, "got=%s" % e("abcd"))
    check("estimate:中英混排(中文abcd)", e("中文abcd") == 4, "got=%s" % e("中文abcd"))
    check("estimate:中文 1 字≈1 token(中*100)", e("中" * 100) >= 100,
          "got=%s" % e("中" * 100))
    check("estimate:非中文 4 字符≈1 token(a*400)", e("a" * 400) == 101,
          "got=%s" % e("a" * 400))


# ---------------------------------------------------------------- 2. _truncate_tokens
def t_truncate():
    cn = "中" * 5000
    for b in (500, 2000, 200, 1):
        r = ctx._truncate_tokens(cn, b)
        check("truncate:budget=%d 结果不超预算" % b,
              ctx.estimate_tokens(r) <= b,
              "est=%d len=%d" % (ctx.estimate_tokens(r), len(r)))
    r500 = ctx._truncate_tokens(cn, 500)
    check("truncate:确实截断并带后缀", len(r500) < 5000 and "已截断" in r500,
          "len=%d" % len(r500))
    short = "短文本abc"
    check("truncate:未超预算原样返回", ctx._truncate_tokens(short, 100) == short)
    r200 = ctx._truncate_tokens(cn, 200)
    check("truncate:budget=200 不超预算", ctx.estimate_tokens(r200) <= 200,
          "est=%d" % ctx.estimate_tokens(r200))


# ---------------------------------------------------------------- 3. build_reference 三档
_ORIG_GOE = ctx.get_or_extract


def _fake_goe(doc, provider, on_step=None):
    return {"status": "ok", "kind": "text", "tables": [],
            "text": "中" * doc.get("_n", 0), "images": [], "note": ""}


def t_build_reference():
    ctx.get_or_extract = _fake_goe
    try:
        # inline:total <= budget
        _set_cfg(CTX_TOKEN_BUDGET=2000, CTX_CATALOG_THRESHOLD=100000)
        ref = ctx.build_reference([{"id": 1, "filename": "a.txt", "_n": 100}], None)
        check("build_reference:inline 档", ref["mode"] == ctx.MODE_INLINE,
              "mode=%s total=%d" % (ref["mode"], ref["totalTokens"]))

        # truncated:budget < total <= threshold
        _set_cfg(CTX_TOKEN_BUDGET=2000, CTX_CATALOG_THRESHOLD=100000)
        ref = ctx.build_reference([{"id": 1, "filename": "a.txt", "_n": 3000}], None)
        check("build_reference:truncated 档", ref["mode"] == ctx.MODE_TRUNCATED,
              "mode=%s total=%d" % (ref["mode"], ref["totalTokens"]))

        # catalog:total > threshold
        _set_cfg(CTX_TOKEN_BUDGET=2000, CTX_CATALOG_THRESHOLD=2500)
        ref = ctx.build_reference([{"id": 1, "filename": "a.txt", "_n": 5000}], None)
        check("build_reference:catalog 档", ref["mode"] == ctx.MODE_CATALOG,
              "mode=%s total=%d" % (ref["mode"], ref["totalTokens"]))

        # F11:threshold < budget → 阈值被提升为预算,不再出现 truncated
        _set_cfg(CTX_TOKEN_BUDGET=2000, CTX_CATALOG_THRESHOLD=1000)
        ref = ctx.build_reference([{"id": 1, "filename": "a.txt", "_n": 3000}], None)
        check("F11:threshold<budget 时直接 catalog(无 truncated)",
              ref["mode"] == ctx.MODE_CATALOG,
              "mode=%s total=%d" % (ref["mode"], ref["totalTokens"]))
    finally:
        ctx.get_or_extract = _ORIG_GOE
        _restore_cfg()


# ---------------------------------------------------------------- 4. resolve_catalog
def _material(name, tokens, compact):
    return {"id": 0, "filename": name, "tokens": tokens, "compact": compact,
            "status": "ok", "kind": "text", "tables": 0,
            "catalog": "- %s:正文 %d 字" % (name, len(compact))}


def _ref(material):
    return {"material": material, "catalog": "\n".join(m["catalog"] for m in material),
            "notes": []}


class _PickProvider(object):
    name = "fake"
    available = True

    def __init__(self, files):
        self.files = files

    def complete(self, system, user, json_mode=False):
        return json.dumps({"files": self.files})


def t_resolve_catalog():
    # 4a. 无 provider(available=False)→ 回退取信息量最大前 N
    _set_cfg(CTX_MAX_SELECT_FILES=2)
    mat = [_material("小.txt", 10, "中" * 5),
           _material("大.txt", 300, "中" * 250),
           _material("中.txt", 100, "中" * 80)]
    r = _ref(mat)
    text, used = ctx.resolve_catalog(llm.Provider(), r, "需求")
    check("resolve:无 provider 回退取前 N(按信息量)", len(used) == 2 and used[0] == "大.txt",
          "used=%s" % used)
    check("resolve:无 provider 结果非空", "大.txt" in text)

    # 4b. F13:首件超预算仍受预算约束
    _set_cfg(CTX_TOKEN_BUDGET=100)
    budget = max(1000, C.CTX_TOKEN_BUDGET)
    r = _ref([_material("巨.txt", 5000, "中" * 5000)])
    text, used = ctx.resolve_catalog(llm.Provider(), r, "需求")
    est = ctx.estimate_tokens(text)
    check("F13:首件超预算后仍在预算内", used == ["巨.txt"] and est <= budget + 16,
          "est=%d budget=%d" % (est, budget))

    # 4c. 请求不存在的文件名被忽略
    _set_cfg(CTX_MAX_SELECT_FILES=12, CTX_MAX_SELECT_ROUNDS=2)
    mat = [_material("a.txt", 100, "中" * 50), _material("b.txt", 100, "中" * 50)]
    r = _ref(mat)
    text, used = ctx.resolve_catalog(_PickProvider(["不存在.txt", "a.txt"]), r, "需求")
    check("resolve:不存在的文件名被忽略", used == ["a.txt"] and "不存在" not in text,
          "used=%s" % used)

    # 4d. 两轮去重
    r = _ref([_material("a.txt", 100, "中" * 50), _material("b.txt", 100, "中" * 50)])
    text, used = ctx.resolve_catalog(_PickProvider(["a.txt"]), r, "需求")
    check("resolve:两轮不重复纳入", used.count("a.txt") == 1,
          "used=%s notes=%s" % (used, r["notes"]))
    _restore_cfg()


# ---------------------------------------------------------------- 5. fit_reference (F1)
def t_fit_reference():
    budget = 1000
    lib, ref = "中" * 5000, "中" * 300
    lo, ro, note = ctx.fit_reference(lib, ref, budget=budget)
    check("fit:总预算受限", ctx.estimate_tokens(lo) + ctx.estimate_tokens(ro) <= budget,
          "total=%d budget=%d" % (ctx.estimate_tokens(lo) + ctx.estimate_tokens(ro), budget))
    check("fit:优先保留 ref 未被截", ro == ref)
    check("fit:note 非空", bool(note))

    lo2, ro2, n2 = ctx.fit_reference("", ref, budget=budget)
    check("fit:library 为空时 ref 不变且无 note", ro2 == ref and n2 == "" and lo2 == "")

    lo3, ro3, n3 = ctx.fit_reference("中" * 5000, "中" * 5000, budget=budget)
    check("fit:双超仍在预算内", ctx.estimate_tokens(lo3) + ctx.estimate_tokens(ro3) <= budget,
          "total=%d" % (ctx.estimate_tokens(lo3) + ctx.estimate_tokens(ro3)))
    check("fit:双超 note 非空", bool(n3))

    lo4, ro4, _ = ctx.fit_reference("中" * 500, "中" * 500, budget=1)
    check("fit:budget=1 仍满足不变量",
          ctx.estimate_tokens(lo4) + ctx.estimate_tokens(ro4) <= 1,
          "total=%d" % (ctx.estimate_tokens(lo4) + ctx.estimate_tokens(ro4)))


# ---------------------------------------------------------------- 6. pipeline._reference_material (F14.8)
def t_pipeline_reference():
    db.init_db()
    uid = db.create_user("ctx_test@local", "x", role="admin", display_name="上下文测试")["id"]
    proj = db.create_project("ctxproj", "上下文测试项目", owner_id=uid)
    lib1 = db.create_library_item("大资料A", "描述A", created_by=uid)
    db.update_library_item(lib1["id"], analysis="中" * 8000)
    lib2 = db.create_library_item("大资料B", "描述B", created_by=uid)
    db.update_library_item(lib2["id"], analysis="中" * 8000)
    db.update_project(proj["id"], ref_items=json.dumps([lib1["id"], lib2["id"]]))
    p = db.get_project(proj["id"])

    docs, library_text = pipeline._reference_material(p)
    check("_reference_material:无项目文档", docs == [], "docs=%d" % len(docs))
    check("_reference_material:返回资料库正文", len(library_text) > 10000,
          "len=%d" % len(library_text))
    check("_reference_material:外部资料带标题", ctx.EXTERNAL_REF_TITLE in library_text)

    budget = 3000
    ref_text = "中" * 500
    lo, ro, note = ctx.fit_reference(library_text, ref_text, budget=budget)
    total = ctx.estimate_tokens(lo) + ctx.estimate_tokens(ro)
    check("pipeline:资料库正文经 fit_reference 受总预算约束", total <= budget,
          "total=%d budget=%d note=%s" % (total, budget, bool(note)))
    check("pipeline:项目参考 ref 未被截", ro == ref_text)

    db.delete_project(proj["id"])
    db.delete_user(uid)
    db.delete_library_item(lib1["id"])
    db.delete_library_item(lib2["id"])


# ---------------------------------------------------------------- 附加:F12 缓存失效
def t_extract_cache():
    db.init_db()
    path = os.path.join(_TMP, "doc.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("门店名称 门店编码")
    proj = db.create_project("ctxcache", "缓存测试")  # noqa: F841
    doc = db.add_document(proj["id"], "other", "doc.txt", path, ".txt", 20)
    # 先无视觉(Provider.available=False)抽取并缓存
    d1 = ctx.get_or_extract(doc, llm.Provider())
    check("F12:首次抽取写缓存", d1.get("_cached") is False, "cached=%s" % d1.get("_cached"))
    raw = db.get_document(doc["id"])["extract_json"]
    cache = json.loads(raw)
    check("F12:缓存含结构/视觉/实现版本键",
          cache.get("_schema") == ctx._EXTRACT_SCHEMA and "_vis" in cache and "_ext_ver" in cache,
          "keys=%s" % sorted(cache.keys()))
    # 再次抽取(仍无视觉)→ 复用
    fresh = db.get_document(doc["id"])
    d2 = ctx.get_or_extract(fresh, llm.Provider())
    check("F12:无视觉时复用缓存", d2.get("_cached") is True)

    # 事后启用视觉(带 complete_vision 的假 provider)→ 旧缓存失效,重新抽取
    class _VisProvider(object):
        name = "vis"
        available = True

        def complete_vision(self, system, user, image_data_url, timeout=None):
            return "识别结果"

    d3 = ctx.get_or_extract(fresh, _VisProvider())
    check("F12:启用视觉后缓存失效并重抽取", d3.get("_cached") is False)

    db.delete_project(proj["id"])


# ---------------------------------------------------------------- 7. 资料角色分组(需求清单=基准)
def t_doc_roles():
    ctx.get_or_extract = _fake_goe
    try:
        _set_cfg(CTX_TOKEN_BUDGET=100000, CTX_CATALOG_THRESHOLD=1000000)
        docs = [{"id": 2, "filename": "会议纪要.docx", "kind": "meeting", "_n": 50},
                {"id": 1, "filename": "需求说明书.docx", "kind": "requirement", "_n": 50}]
        ref = ctx.build_reference(docs, None)
        text = ref["text"]
        check("roles:含需求清单分组标题", "【需求清单" in text)
        check("roles:含会议纪要分组标题", "【会议纪要" in text)
        check("roles:需求清单排在会议纪要前(截断也优先保留)",
              text.index("【需求清单") < text.index("【会议纪要")
              and ref["material"][0]["docKind"] == "requirement")
        check("roles:material 带 docKind", ref["material"][0].get("docKind") == "requirement")
        check("roles:catalog 行标注资料类型",
              ctx._catalog_line({"text": "x"}, "a.docx", "requirement").startswith("- [需求清单]"))
        check("roles:catalog 行未知类型归其他",
              ctx._catalog_line({}, "b.docx", "").startswith("- [其他]"))
    finally:
        ctx.get_or_extract = _ORIG_GOE
        _restore_cfg()


# ---------------------------------------------------------------- 8. 资料使用守则(防"参考当需求"/分清主补)
def t_reference_guard():
    g = ctx.REFERENCE_GUARD
    check("guard:守则非空", bool(g))
    check("guard:区分需求基准与外部资料", "基准" in g and "外部参考资料" in g)
    check("guard:会议纪要/其他为补充", "会议纪要" in g and "补充" in g)

    up = plan_service._user_prompt("我要做门店管理", "某旧系统的字段清单", None)
    check("plan:有参考时含守则", g in up)
    check("plan:有参考时标注资料分组", "需求资料与参考资料" in up)
    check("plan:有参考时保留需求原文", "我要做门店管理" in up)
    check("plan:无参考时不含守则", g not in plan_service._user_prompt("我要做门店管理", "", None))

    dup = design_service._user_prompt("方案正文", "flowchart LR\n  A-->B", "旧系统字段")
    check("design:有参考时含守则", g in dup)
    check("design:含流程图输入(用于判断自动化)", "业务流程图" in dup and "A-->B" in dup)
    check("design:无参考时不含守则",
          g not in design_service._user_prompt("方案", "flowchart LR", ""))

    fup = flowchart_service._user_prompt("方案正文")
    check("flowchart:提示只含方案(不看需求/参考)", "系统设计方案" in fup and "方案正文" in fup)
    check("flowchart:不再携带需求/参考资料守则", g not in fup)

    check("plan:强调是流程图与 ER 的唯一依据", "唯一依据" in plan_service._SYSTEM)
    check("plan:要求写全字段/规则/关系",
          "全部字段" in plan_service._SYSTEM and "业务规则" in plan_service._SYSTEM
          and "关系" in plan_service._SYSTEM)
    check("plan:要求看板/报表单独成模块(便于排除)",
          "看板" in plan_service._SYSTEM and "报表" in plan_service._SYSTEM)

    check("design:system 依据方案+业务流程图",
          "系统设计方案" in design_service._SYSTEM and "业务流程图" in design_service._SYSTEM)
    check("design:system 排除看板/报表(不建表)",
          "看板" in design_service._SYSTEM and "不建表" in design_service._SYSTEM)

    check("flowchart:system 唯一依据是方案", "唯一依据" in flowchart_service._SYSTEM)
    check("flowchart:system 排除看板/报表",
          "看板" in flowchart_service._SYSTEM and "报表" in flowchart_service._SYSTEM)
    check("flowchart:system 按模块 subgraph 分组",
          "subgraph" in flowchart_service._SYSTEM and "模块" in flowchart_service._SYSTEM)


# ---------------------------------------------------------------- 9. 需求清单:清单行 + 必做表单
def t_required_forms():
    _set_cfg(CTX_SAMPLE_ROWS=8, CTX_MAX_LIST_ROWS=200, CTX_LIST_MAX_COLS=6)
    rows = [[str(i), "M%d" % (i // 10), "表单%d" % i] for i in range(1, 51)]
    ext = {"tables": [{"name": "功能清单", "columns": ["序号", "模块", "表单名称"],
                       "rows": rows, "rowCount": len(rows)}],
           "text": "", "images": [], "status": "ok"}
    txt = ctx.render_compact(ext, C.CTX_SAMPLE_ROWS)
    check("listrows:清单表(列少)保留全部行", "表单50" in txt, "含表单50=%s" % ("表单50" in txt))

    rows2 = [[str(i), "b", "c", "d", "e", "f", "g", "h"] for i in range(1, 51)]
    ext2 = {"tables": [{"name": "宽表", "columns": ["a", "b", "c", "d", "e", "f", "g", "h"],
                        "rows": rows2, "rowCount": 50}], "text": "", "images": [], "status": "ok"}
    txt2 = ctx.render_compact(ext2, C.CTX_SAMPLE_ROWS)
    check("listrows:宽表仍只取样例", "50 | b" not in txt2, "已按样例截取")

    forms = ctx._forms_from_ext(ext)
    check("forms:从「表单名称」列抽取", forms[:3] == ["表单1", "表单2", "表单3"], str(forms[:3]))
    check("forms:共 50 个且去重", len(forms) == 50, str(len(forms)))

    cl = ctx.forms_checklist(forms[:3])
    check("forms:checklist 标题与数量", "必须设计的表单" in cl and "共 3 个" in cl, cl[:40])
    check("forms:checklist 逐条列出", "1. 表单1" in cl and "3. 表单3" in cl)
    check("forms:空清单返回空串", ctx.forms_checklist([]) == "")

    miss = ctx.missing_forms(["物料主数据", "颜色", "BOM管理"], ["物料主数据", "BOM管理表"])
    check("forms:missing_forms 只留未覆盖项", miss == ["颜色"], str(miss))
    _restore_cfg()


_ORIG_GOE2 = ctx.get_or_extract


def t_build_reference_forms():
    def _goe(doc, provider, on_step=None):
        if doc.get("kind") == "requirement":
            rows = [["1", "物料与库存", "物料主数据"], ["2", "研发与样品", "研发项目"]]
            return {"status": "ok", "kind": "spreadsheet",
                    "tables": [{"name": "功能清单", "columns": ["序号", "功能模块", "表单名称"],
                                "rows": rows, "rowCount": 2}],
                    "text": "", "images": [], "note": ""}
        return {"status": "ok", "kind": "text", "tables": [], "text": "补充",
                "images": [], "note": ""}

    ctx.get_or_extract = _goe
    try:
        _set_cfg(CTX_TOKEN_BUDGET=100000, CTX_CATALOG_THRESHOLD=1000000)
        ref = ctx.build_reference(
            [{"id": 1, "filename": "需求.xlsx", "kind": "requirement"},
             {"id": 2, "filename": "会议.docx", "kind": "meeting"}], None)
        check("build_reference:requiredForms 从需求清单提取",
              ref.get("requiredForms") == ["物料主数据", "研发项目"],
              str(ref.get("requiredForms")))
        check("build_reference:需求表以需求清单分组呈现",
              "【需求清单" in ref["text"] and "物料主数据" in ref["text"])
    finally:
        ctx.get_or_extract = _ORIG_GOE2
        _restore_cfg()


# ---------------------------------------------------------------- 10. 方案格式(客户可交付)
def t_plan_format():
    sys_ = plan_service._SYSTEM
    check("plan:新结构含 模块/表单/业务内容",
          "# <模块名>" in sys_ and "## <表单名>" in sys_ and "业务内容:" in sys_)
    check("plan:不含旧的表盘点/界面配置",
          "表盘点" not in sys_ and "界面手工配置项" not in sys_)
    check("plan:要求字段用中文名、不写 key",
          "中文业务名称" in sys_ and "不写字段的英文编码" in sys_)
    check("plan:含脱敏结构范例(虚构零售)",
          "连锁零售" in sys_ and "商品档案" in sys_)
    check("plan:范例已脱敏(无客户/能源字样)",
          "奥桦" not in sys_ and "能源" not in sys_ and "煤炭" not in sys_)

    md = ("# 项目概述\nx\n# 基础资料\n## 门店档案\n业务内容:\n1. a\n"
          "## 区域档案\n业务内容:\n1. b\n"
          "# 合同管理\n## 加盟合同\n业务内容:\n1. c\n")
    tabs = flowchart_service._tables_from_plan(md)
    check("flowchart:从方案 H2 解析表单(无 key)",
          [t for _, t in tabs] == ["门店档案", "区域档案", "加盟合同"], str(tabs))
    mmd = flowchart_service._heuristic_flow(md)
    check("flowchart:每个节点都带业务名标签",
          all(('["%s"]' % n) in mmd for n in ["门店档案", "区域档案", "加盟合同"]), mmd)
    check("flowchart:仍是合法 mermaid", mmd.startswith("flowchart"), mmd[:20])

    # 无「业务内容」的 H2(如旧格式的章节标题)不应被当成表单
    md_none = "# 系统设计方案\n## 一、项目概述\nxx\n## 二、表盘点\n| 表 key | 表单名 |\n|---|---|\n"
    check("flowchart:无业务内容的 H2 不误判为表单",
          flowchart_service._tables_from_plan(md_none) == [], str(flowchart_service._tables_from_plan(md_none)))

    # 旧格式(表盘点表格,首列是 key)→ 回退解析正确
    md_old = ("# 系统设计方案\n## 一、项目概述\nx\n## 二、表盘点\n"
              "| 表 key | 表单名 | 角色 | 依据 | 置信度 |\n|---|---|---|---|---|\n"
              "| customer | 客户档案 | 主数据 | 需求清单 | ● |\n"
              "| contract | 合同 | 单据 | 需求清单 | ● |\n## 三、表关系\n")
    check("flowchart:旧格式回退解析表盘点",
          flowchart_service._tables_from_plan(md_old) == [("customer", "客户档案"),
                                                          ("contract", "合同")],
          str(flowchart_service._tables_from_plan(md_old)))


# ---------------------------------------------------------------- 11. 看板/报表排除(不进流程图与 ER)
def t_report_excluded():
    check("report:关键词识别看板/报表",
          ctx.is_report_entity("协同看板") and ctx.is_report_entity("库存分析")
          and ctx.is_report_entity("销售报表") and ctx.is_report_entity("库存汇总统计")
          and ctx.is_report_entity("经营总览") and ctx.is_report_entity("异常监控"))
    check("report:业务表单不误判",
          not ctx.is_report_entity("采购订单") and not ctx.is_report_entity("客户档案")
          and not ctx.is_report_entity("出库细码单"))
    # 弱信号只在**结尾**才算:避免误伤「质量分析单 / 工时统计表 / 设备监控台账」这类业务表
    check("report:弱信号需结尾(不误伤业务表)",
          not ctx.is_report_entity("质量分析单")
          and not ctx.is_report_entity("工时统计表")
          and not ctx.is_report_entity("设备监控台账"))

    md = ("# 项目概述\nx\n"
          "# 物料与库存\n## 物料主数据\n业务内容:\n1. 字段:编码、名称\n"
          "## 三态库存视图\n业务内容:\n1. 展示在库/在途/在制\n"
          "# 协同看板\n## 订单进度看板\n业务内容:\n1. 展示订单进度\n"
          "# 决策分析中心\n## 库存分析\n业务内容:\n1. 分析库存周转\n")
    mods = flowchart_service._plan_structure(md)
    names = [n for n, _ in mods]
    forms = [f for _, fs in mods for f in fs]
    check("report:流程图排除看板/报表模块", "协同看板" not in names and "决策分析中心" not in names,
          str(names))
    check("report:流程图排除看板/报表表单",
          "订单进度看板" not in forms and "库存分析" not in forms, str(forms))
    check("report:业务模块与表单保留", names == ["物料与库存"] and "物料主数据" in forms, str(mods))

    mods_all = flowchart_service._plan_structure(md, exclude_reports=False)
    forms_all = [f for _, fs in mods_all for f in fs]
    check("report:校验模式(不排除)可见全部",
          "订单进度看板" in forms_all and "库存分析" in forms_all, str(forms_all))

    # design 侧剔除看板/报表 + 只含它们的模块 + 指向它们的自动化
    fake = {"sheets": [
        {"key": "customer", "title": "客户档案", "group": "基础资料",
         "controls": [{"type": "text", "key": "cname", "label": "客户名称"}]},
        {"key": "board", "title": "订单进度看板", "group": "协同看板",
         "controls": [{"type": "text", "key": "b", "label": "x"}]}],
        "dicts": {}, "groups": ["基础资料", "协同看板"],
        "automations": [{"key": "a1", "form": "customer", "trigger": "生效或更新",
                         "actions": [{"do": "更新", "target": "customer"}]},
                        {"key": "a2", "form": "board", "trigger": "生效或更新",
                         "actions": [{"do": "更新", "target": "customer"}]}]}
    out = design_service._strip_reports(fake)
    keys = [s["key"] for s in out["sheets"]]
    check("report:ER 剔除看板/报表表", keys == ["customer"], str(keys))
    check("report:ER 剔除只含看板的模块", out["groups"] == ["基础资料"], str(out["groups"]))
    check("report:ER 剔除指向被剔除表的自动化",
          [a["key"] for a in out["automations"]] == ["a1"], str(out["automations"]))

    # 自动化只按**表 key** 剔除:未引用被剔除表的一律保留(不误删)
    fake2 = {"sheets": [
        {"key": "customer", "title": "客户档案", "group": "基础资料",
         "controls": [{"type": "text", "key": "cname", "label": "客户名称"}]}],
        "dicts": {}, "groups": ["基础资料"],
        "automations": [
            {"key": "keep1", "form": "customer", "trigger": "生效或更新",
             "actions": [{"do": "更新", "target": "customer"}]},
            # match.ref 是**字段**名(源侧),即便与某个被剔除表 key 同名,也不该误删
            {"key": "keep2", "form": "customer", "trigger": "生效或更新",
             "actions": [{"do": "更新", "target": "customer",
                          "match": [{"field": "cname", "ref": "board"}]}]}]}
    o2 = design_service._strip_reports(fake2)
    check("report:未引用被剔除表的自动化不被误删",
          [a["key"] for a in o2["automations"]] == ["keep1", "keep2"],
          str([a["key"] for a in o2["automations"]]))


def t_flow_stats_and_module_scope():
    # 节点统计必须覆盖**链式一行多节点**,否则正常图会被误判"过密"而回退
    chain = "flowchart LR\n  " + " --> ".join("N%d[X%d]" % (i, i) for i in range(1, 21))
    n, e = flowchart_service.flow_stats(chain)
    check("flowstats:链式 20 节点统计正确", n == 20 and e == 19, "nodes=%d edges=%d" % (n, e))
    check("flowstats:链式不再误判过密", not (e > max(12, int(n * 1.6))),
          "edges=%d n*1.6=%d" % (e, int(n * 1.6)))
    per_line = "flowchart LR\n" + "\n".join("  N%d[X%d]" % (i, i) for i in range(1, 21))
    n2, e2 = flowchart_service.flow_stats(per_line)
    check("flowstats:逐行声明统计正确", n2 == 20 and e2 == 0, "nodes=%d edges=%d" % (n2, e2))
    sub = ('flowchart LR\n  subgraph M1["销售"]\n    direction TB\n'
           '    A[客户] --> B[报价单]\n  end')
    n3, e3 = flowchart_service.flow_stats(sub)
    check("flowstats:subgraph 不计为节点", n3 == 2 and e3 == 1, "nodes=%d edges=%d" % (n3, e3))

    # 模块名含报表词、但模块内有业务表 → 模块与业务表都要保留(只剔报表表单)
    md = ("# 项目概述\nx\n# 统计管理\n"
          "## 采购订单\n业务内容:\n1. 字段:编号\n"
          "## 销售成本统计\n业务内容:\n1. 展示成本\n")
    mods = flowchart_service._plan_structure(md)
    names = [n for n, _ in mods]
    forms = [f for _, fs in mods for f in fs]
    check("report:模块名含报表词不整块丢弃", names == ["统计管理"], str(names))
    check("report:模块内业务表保留、报表表单剔除",
          forms == ["采购订单"], str(forms))


# ---------------------------------------------------------------- main
def main():
    print("=" * 70)
    print("参考资料上下文测试  tmp=%s" % _TMP)
    print("=" * 70)
    try:
        t_estimate()
        t_truncate()
        t_build_reference()
        t_resolve_catalog()
        t_fit_reference()
        t_pipeline_reference()
        t_extract_cache()
        t_doc_roles()
        t_reference_guard()
        t_required_forms()
        t_build_reference_forms()
        t_plan_format()
        t_report_excluded()
        t_flow_stats_and_module_scope()
    finally:
        _restore_cfg()
        ctx.get_or_extract = _ORIG_GOE
        shutil.rmtree(_TMP, ignore_errors=True)

    print("\n" + "=" * 70)
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项:%s" % _FAIL)
    print("=" * 70)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
