# -*- coding: utf-8 -*-
"""流水线路由(需求 / 方案 / 流程图 / ER)。

契约见 docs/ARCHITECTURE.md §5:
  GET/PUT  /api/projects/{id}/requirement
  GET/POST/PUT /api/projects/{id}/plan[/generate]
  GET/POST/PUT /api/projects/{id}/flowchart[/generate]
  GET/POST/PUT /api/projects/{id}/design[/generate]
  GET  /api/projects/{id}/design/check
  GET  /api/projects/{id}/design/er

统一响应 {ok,data,message};写操作校验项目写权限。
"""
import json

from fastapi import APIRouter, Depends, HTTPException

from .. import engine_bridge as EB
from .. import storage
from ..core import deps
from ..db import database as db
from ..schemas import pipeline as S
from ..services import design as design_service
from ..services import flowchart as flowchart_service
from ..services import jobs as jobs_service
from ..services import llm as llm_service
from ..services import plan as plan_service

router = APIRouter(prefix="/api", tags=["pipeline"])


def _ok(data=None, message=""):
    return {"ok": True, "data": data if data is not None else {}, "message": message}


def _design_payload(design, provider, check=None, error=""):
    return {"sheets": design.get("sheets") or [],
            "dicts": design.get("dicts") or {},
            "groups": design.get("groups") or [],
            "automations": design.get("automations") or [],
            "provider": provider,
            "check": check,
            "error": error or ""}


def _sync(slug, app_code, design):
    """落盘 sheets+automations 并离线校验;返回 (清洗后的 design, check, error)。
    异常也转成 error,不抛出(校验失败仍保存,便于继续编辑)。"""
    storage.project_dir(slug, create=True)
    try:
        res = EB.sync_sheets(slug, design, app_code=app_code)
        return (res.get("design") or design), res.get("check"), res.get("error", "")
    except Exception as e:
        return design, None, str(e)


# ---------------------------------------------------------------- 需求
@router.get("/projects/{id}/requirement")
def get_requirement(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    return _ok(storage.get_requirement(p["slug"]))


@router.put("/projects/{id}/requirement")
def put_requirement(id: int, body: S.RequirementIn, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    storage.set_requirement(p["slug"], body.html, body.text)
    db.add_event(p["id"], "requirement", "更新需求内容")
    return _ok(storage.get_requirement(p["slug"]))


# ---------------------------------------------------------------- 方案
@router.get("/projects/{id}/plan")
def get_plan(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    return _ok({"markdown": storage.get_plan(p["slug"])})


def _selected_library_ids(p):
    try:
        ids = json.loads(p.get("ref_items") or "[]")
    except Exception:
        return []
    out = []
    for x in ids:
        try:
            out.append(int(x))
        except Exception:
            continue
    return out


def _reference_material(p):
    """参考资料素材 = (本项目可抽取文档, 勾选的资料库资料正文)。

    项目文档走结构化抽取(字段无损、数据行限量),按资料类型(需求清单/会议纪要/其他)
    分组渲染(见 context.build_reference);资料库资料是**外部参考资料**(非本项目需求),
    加标题以示区分。
    """
    from ..services import context as ctx
    from ..services import library as library_service
    docs = [d for d in db.list_documents(p["id"]) if d.get("stored_path")]
    ids = _selected_library_ids(p)
    lib_parts = []
    if ids:
        for it in db.list_library_items():
            if it["id"] in ids:
                txt = library_service.library_context(it)
                if txt.strip():
                    lib_parts.append(txt)
    library_text = "\n\n".join(lib_parts)
    if library_text.strip():
        library_text = "%s\n%s" % (ctx.EXTERNAL_REF_TITLE, library_text)
    return docs, library_text


def _library_view(it):
    return {"id": it["id"], "name": it.get("name", ""),
            "description": it.get("description", ""),
            "docCount": len(db.list_library_documents(it["id"])),
            "analysisReady": bool((it.get("analysis") or "").strip())}


@router.get("/projects/{id}/ref-docs")
def get_ref_docs(id: int, user=Depends(deps.require_user)):
    """本项目参考的资料:已勾选 id + 可选资料清单(按名称勾选)。"""
    p = deps.get_project(id, user)
    return _ok({"ids": _selected_library_ids(p),
                "library": [_library_view(it) for it in db.list_library_items()]})


@router.put("/projects/{id}/ref-docs")
def put_ref_docs(id: int, body: S.RefDocsIn, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    valid = {it["id"] for it in db.list_library_items()}
    ids = []
    for x in (body.ids or []):
        try:
            n = int(x)
        except Exception:
            continue
        if n in valid and n not in ids:
            ids.append(n)
    db.update_project(p["id"], ref_items=json.dumps(ids))
    db.add_event(p["id"], "requirement", "更新参考资料(%d 份)" % len(ids))
    return _ok({"ids": ids})


@router.post("/projects/{id}/plan/generate")
def generate_plan(id: int, body: S.GenerateIn = None, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    instruction = (body.instruction if body else None)
    slug, pid = p["slug"], p["id"]

    def runner(progress):
        from ..services import context as ctx
        progress("读取需求与参考资料清单", pct=3)
        requirement = storage.requirement_text(slug)
        docs, library_text = _reference_material(p)
        provider = llm_service.get_provider()
        progress("开始结构化抽取参考资料(共 %d 个文件,已抽取过的会直接复用缓存)"
                 % len(docs), pct=5)
        reference = ctx.build_reference(docs, provider, progress=progress, pct_range=(6, 55))
        progress("组装上下文:模式=%s,约 %d token(预算 %d)" % (
            reference["mode"], reference["totalTokens"], ctx.C.CTX_TOKEN_BUDGET), pct=58)
        ref_text = reference["text"]
        if reference["mode"].startswith(ctx.MODE_CATALOG):
            resolved, used = ctx.resolve_catalog(provider, reference, requirement, progress)
            ref_text = resolved
            progress("目录模式:已按需纳入 %d 份资料" % len(used), pct=70)
        library_text, ref_text, fit_note = ctx.fit_reference(library_text, ref_text)
        blocks = [b for b in (ref_text, library_text) if b and b.strip()]
        reference_text = "\n\n".join(blocks)
        forms = reference.get("requiredForms") or []
        checklist = ctx.forms_checklist(forms)
        if checklist:
            reference_text = "%s\n\n%s" % (checklist, reference_text)
            progress("需求清单:识别出 %d 个必做表单,已作为硬约束" % len(forms), pct=71)
        if fit_note:
            progress("提示:%s" % fit_note, pct=70, level="warning")
        for note in reference["notes"][:6]:
            progress("提示:%s" % note, pct=70, level="warning")

        res = plan_service.generate_plan(requirement, reference_text, instruction,
                                         progress=progress, provider=provider)
        progress("保存方案(provider=%s)" % res.get("provider"), pct=95)
        storage.set_plan(slug, res["markdown"])
        # 方案是后续「业务流程图 / ER」的**唯一依据** → 校验它是否完整覆盖需求清单的表单
        try:
            from ..services import flowchart as fc
            planned = [f for _, fs in fc._plan_structure(res["markdown"], exclude_reports=False)
                       for f in fs]
            report = [f for f in forms if ctx.is_report_entity(f)]
            if report:
                progress("说明:需求清单中的 %d 个看板/报表已按规则排除(不建表、不进流程图与 ER)"
                         % len(report), pct=96)
            missing = ctx.missing_forms(forms, planned)
            if missing:
                progress("提示:需求清单中 %d 个表单未出现在方案里,将影响流程图与 ER"
                         "(可重新生成方案或手工补全):%s"
                         % (len(missing), "、".join(missing[:10])), pct=96, level="warning")
        except Exception:
            pass
        db.update_project(pid, status="planned")
        db.add_event(pid, "plan", "生成系统设计方案(provider=%s)" % res.get("provider"))
        return {"markdown": res["markdown"], "provider": res.get("provider", "heuristic"),
                "referenceMode": reference["mode"],
                "referenceTokens": reference["totalTokens"],
                "referenceFiles": len(docs),
                "_detail": "provider=%s, 参考模式=%s, 约 %d token"
                           % (res.get("provider"), reference["mode"], reference["totalTokens"])}

    job, created = jobs_service.submit(pid, user["id"], "plan", runner)
    return _ok({"job": job, "created": created})


@router.put("/projects/{id}/plan")
def put_plan(id: int, body: S.PlanIn, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    storage.set_plan(p["slug"], body.markdown)
    db.update_project(p["id"], status="planned")
    return _ok({"markdown": body.markdown})


# ---------------------------------------------------------------- 流程图
@router.get("/projects/{id}/flowchart")
def get_flowchart(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    return _ok({"mermaid": storage.get_flowchart(p["slug"])})


@router.post("/projects/{id}/flowchart/generate")
def generate_flowchart(id: int, body: S.GenerateIn = None, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    slug, pid = p["slug"], p["id"]
    # 流程图唯一依据 = 方案:方案为空则无法生成
    if not (storage.get_plan(slug) or "").strip():
        raise HTTPException(400, "尚未生成系统设计方案,请先完成「方案」阶段")

    def runner(progress):
        # 业务流程图的**唯一依据 = 系统设计方案**(方案已含完整字段/业务逻辑/关系);
        # 不再读取原始需求与参考资料,保证与方案口径一致。
        progress("读取系统设计方案", pct=10)
        plan_md = storage.get_plan(slug)
        provider = llm_service.get_provider()
        progress("调用大模型生成业务流程图" if getattr(provider, "available", False)
                 else "未配置大模型,使用启发式生成流程图", pct=55)
        res = flowchart_service.generate_flowchart(plan_md)
        stats = "节点 %d / 边 %d" % (res.get("nodes", 0), res.get("edges", 0))
        if res.get("dense"):
            ds = res.get("denseStats") or {}
            progress("提示:模型产出的流程图过密(节点 %d/边 %d),已自动回退为「分模块」骨架;"
                     "可重新生成以获取更聚焦的流程"
                     % (ds.get("nodes", 0), ds.get("edges", 0)), pct=88, level="warning")
        progress("流程图生成完成(provider=%s,%s),正在保存" % (res.get("provider"), stats), pct=90)
        storage.set_flowchart(slug, res["mermaid"])
        db.update_project(pid, status="flowcharted")
        db.add_event(pid, "flowchart", "生成业务流程图(provider=%s)" % res.get("provider"))
        return {"mermaid": res["mermaid"], "provider": res.get("provider", "heuristic"),
                "nodes": res.get("nodes", 0), "edges": res.get("edges", 0),
                "_detail": "provider=%s, %s" % (res.get("provider"), stats)}

    job, created = jobs_service.submit(pid, user["id"], "flowchart", runner)
    return _ok({"job": job, "created": created})


@router.put("/projects/{id}/flowchart")
def put_flowchart(id: int, body: S.FlowchartIn, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    storage.set_flowchart(p["slug"], body.mermaid)
    db.update_project(p["id"], status="flowcharted")
    return _ok({"mermaid": body.mermaid})


# ---------------------------------------------------------------- ER / 设计
@router.get("/projects/{id}/design")
def get_design(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    return _ok(storage.get_design(p["slug"]))


@router.post("/projects/{id}/design/generate")
def generate_design(id: int, body: S.GenerateIn = None, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    slug, pid = p["slug"], p["id"]
    app_code = p.get("app_code", "")
    if not (storage.get_plan(slug) or "").strip():
        raise HTTPException(400, "尚未生成系统设计方案,请先完成「方案」阶段")

    def runner(progress):
        # ER 的**依据 = 方案(字段/规则) + 业务流程图(表单间流转 → 自动化)**;
        # 看板/报表已在 design 侧排除(不建表、不进应用)。
        progress("读取系统设计方案与业务流程图", pct=15)
        plan_md = storage.get_plan(slug)
        mmd = storage.get_flowchart(slug)
        if not (mmd or "").strip():
            progress("提示:尚未生成业务流程图,自动化判断将仅依据方案", pct=20, level="warning")
        provider = llm_service.get_provider()
        progress("调用大模型生成 ER 结构…", pct=60)
        res = design_service.generate_design(plan_md, mmd, progress=progress, provider=provider)
        design = {"sheets": res.get("sheets") or [],
                  "dicts": res.get("dicts") or {},
                  "groups": res.get("groups") or [],
                  "automations": res.get("automations") or []}
        progress("落盘表单/自动化定义并做离线校验(%d 张表)" % len(design["sheets"]), pct=94)
        design, check, error = _sync(slug, app_code, design)
        storage.set_design(slug, design)
        db.update_project(pid, status="designed")
        db.add_event(pid, "design",
                     "生成 ER 结构(provider=%s, %d 表/%d 自动化)"
                     % (res.get("provider", "heuristic"), len(design["sheets"]),
                        len(design.get("automations") or [])))
        payload = _design_payload(design, res.get("provider", "heuristic"), check, error)
        payload["_detail"] = "provider=%s, %d 表(方案+流程图)" % (
            res.get("provider", "heuristic"), len(design["sheets"]))
        return payload

    job, created = jobs_service.submit(pid, user["id"], "design", runner)
    return _ok({"job": job, "created": created})


@router.put("/projects/{id}/design")
def put_design(id: int, body: S.DesignIn, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    design, check, error = _sync(p["slug"], p.get("app_code", ""), body.model_dump())
    # 存**清洗后**的 design(与 sheets/ 一致),避免编辑器所见与引擎所建分叉
    storage.set_design(p["slug"], design)
    db.update_project(p["id"], status="designed")
    return _ok(_design_payload(design, "user", check, error))


@router.get("/projects/{id}/design/check")
def check_design(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    design = storage.get_design(p["slug"])
    if not design.get("sheets"):
        return _ok({"project": p["slug"], "sheets": [], "warnings": [],
                    "error": "尚未生成 ER 结构"})
    _design, check, error = _sync(p["slug"], p.get("app_code", ""), design)
    if not check:
        return _ok({"project": p["slug"], "sheets": [], "warnings": [], "error": error})
    check = dict(check)
    check["error"] = error or ""
    return _ok(check)


@router.get("/projects/{id}/design/er")
def design_er(id: int, user=Depends(deps.require_user)):
    p = deps.get_project(id, user)
    storage.project_dir(p["slug"], create=True)
    try:
        return _ok(EB.er_graph(p["slug"], app_code=p.get("app_code", "")))
    except Exception as e:
        return _ok({"project": p["slug"], "nodes": [], "edges": [], "error": str(e)})
