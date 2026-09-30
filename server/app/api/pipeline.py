# -*- coding: utf-8 -*-
"""流水线路由(需求 / 方案 / 流程图 / ER)。

契约见 dev/docs/architecture.md §5:
  GET/PUT  /api/projects/{id}/requirement
  GET/POST/PUT /api/projects/{id}/plan[/generate]
  GET/POST/PUT /api/projects/{id}/flowchart[/generate]
  GET/POST/PUT /api/projects/{id}/design[/generate]
  GET  /api/projects/{id}/design/check
  GET  /api/projects/{id}/design/er

统一响应 {ok,data,message};写操作校验项目写权限。
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import engine_bridge as EB
from .. import storage
from ..core import deps
from ..db import database as db
from ..schemas import pipeline as S
from ..services import design as design_service
from ..services import flowchart as flowchart_service
from ..services import flowchart_svg as flowchart_svg_service
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
        storage.record_snapshot(slug, "plan", res["markdown"], origin="generate",
                                provider=res.get("provider"))
        storage.set_stage(slug, "plan")
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
    storage.record_snapshot(p["slug"], "plan", body.markdown, origin="edit")
    storage.set_stage(p["slug"], "plan")
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
        storage.record_snapshot(slug, "flowchart", res["mermaid"], origin="generate",
                                provider=res.get("provider"))
        storage.set_stage(slug, "flowchart", src=storage.stage_src(slug, "flowchart"))
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
    storage.record_snapshot(p["slug"], "flowchart", body.mermaid, origin="edit")
    storage.set_stage(p["slug"], "flowchart", src=storage.stage_src(p["slug"], "flowchart"))
    db.update_project(p["id"], status="flowcharted")
    return _ok({"mermaid": body.mermaid})


@router.get("/projects/{id}/flowchart/svg")
def get_flowchart_svg(id: int, fmt: str = "svg", user=Depends(deps.require_user)):
    """把当前业务流程图渲染成**分区泳道式 SVG**(可下载)。

    - `fmt=svg`(默认):返回 image/svg+xml,可直接下载/打开;
    - `fmt=png`:栅格化为 PNG(需 `pip install cairosvg`,缺失时返回明确提示)。
    渲染为**确定性**、零 LLM 依赖的纯 Python 实现(见 services/flowchart_svg.py)。
    """
    p = deps.get_project(id, user)
    mmd = storage.get_flowchart(p["slug"])
    if not (mmd or "").strip():
        raise HTTPException(400, "尚未生成业务流程图,请先完成「业务流程图」阶段")
    res = flowchart_svg_service.render_svg(mmd, title="业务流程图")
    if not res.get("ok"):
        raise HTTPException(400, res.get("message") or "无法渲染流程图")
    svg = res["svg"]
    if str(fmt).lower() == "png":
        try:
            import cairosvg
            png = cairosvg.svg2png(bytestring=svg.encode("utf-8"), scale=2)
        except Exception as exc:                       # 依赖缺失或栅格化失败
            raise HTTPException(500, "PNG 导出需要 cairosvg(可 `pip install cairosvg`):%s" % exc)
        return Response(content=png, media_type="image/png",
                        headers={"Content-Disposition": 'attachment; filename="flowchart.png"'})
    return Response(content=svg, media_type="image/svg+xml; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="flowchart.svg"'})


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
        storage.record_snapshot(slug, "design", design, origin="generate",
                                provider=res.get("provider"))
        storage.set_stage(slug, "design", src=storage.stage_src(slug, "design"))
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
    storage.record_snapshot(p["slug"], "design", design, origin="edit")
    storage.set_stage(p["slug"], "design", src=storage.stage_src(p["slug"], "design"))
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


# ---------------------------------------------------------------- AI 微调(对话式)
def _require_llm():
    """微调依赖对自然语言指令的理解,必须已配置大模型(启发式无法胜任)。"""
    if not llm_service.get_provider().available:
        raise HTTPException(400, "AI 微调需先在「系统设置」配置大模型")


@router.post("/projects/{id}/plan/refine")
def refine_plan(id: int, body: S.RefineIn, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    _require_llm()
    slug, pid = p["slug"], p["id"]
    if not (storage.get_plan(slug) or "").strip():
        raise HTTPException(400, "尚未生成系统设计方案")

    def runner(progress):
        progress("读取当前方案", pct=15)
        current = storage.get_plan(slug)          # 任务执行时重读,确保用最新内容
        res = plan_service.refine_plan(current, body.instruction, progress=progress)
        new_md = res["markdown"]
        # 改动摘要:方案里的表单集合变化(可见地暴露 AI 是否越界)
        added, removed = [], []
        try:
            from ..services import flowchart as fc
            old_f = [f for _, fs in fc._plan_structure(current, exclude_reports=False) for f in fs]
            new_f = [f for _, fs in fc._plan_structure(new_md, exclude_reports=False) for f in fs]
            added = [x for x in new_f if x not in old_f]
            removed = [x for x in old_f if x not in new_f]
        except Exception:
            pass
        if removed:
            progress("注意:微调后有 %d 个表单从方案中消失(%s);如非本意请回滚"
                     % (len(removed), "、".join(removed[:8])), pct=94, level="warning")
        progress("保存微调后的方案", pct=96)
        storage.set_plan(slug, new_md)            # 只写本阶段文件(plan.md)
        storage.record_snapshot(slug, "plan", new_md, origin="refine",
                                instruction=body.instruction, provider=res.get("provider"))
        storage.set_stage(slug, "plan")
        db.add_event(pid, "plan", "AI 微调方案")
        parts = []
        if added:
            parts.append("新增表单:%s" % "、".join(added[:8]))
        if removed:
            parts.append("移除表单:%s" % "、".join(removed[:8]))
        detail = "已微调方案" + ("(" + ";".join(parts) + ")" if parts else "(未增删表单)")
        return {"markdown": new_md, "provider": res.get("provider"),
                "changeSummary": {"addedForms": added, "removedForms": removed},
                "_detail": detail}

    job, created = jobs_service.submit(pid, user["id"], "plan_refine", runner)
    return _ok({"job": job, "created": created})


@router.post("/projects/{id}/flowchart/refine")
def refine_flowchart(id: int, body: S.RefineIn, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    _require_llm()
    slug, pid = p["slug"], p["id"]
    if not (storage.get_flowchart(slug) or "").strip():
        raise HTTPException(400, "尚未生成业务流程图")

    def runner(progress):
        progress("读取当前流程图与方案", pct=15)
        current = storage.get_flowchart(slug)      # 任务执行时重读
        plan_md = storage.get_plan(slug)
        old_nodes, old_edges = flowchart_service.flow_stats(current)
        res = flowchart_service.refine_flowchart(current, body.instruction, plan_md,
                                                 progress=progress)
        storage.set_flowchart(slug, res["mermaid"])  # 只写本阶段文件(flowchart.mmd)
        storage.record_snapshot(slug, "flowchart", res["mermaid"], origin="refine",
                                instruction=body.instruction, provider=res.get("provider"))
        storage.set_stage(slug, "flowchart", src=storage.stage_src(slug, "flowchart"))
        db.add_event(pid, "flowchart", "AI 微调业务流程图")
        return {"mermaid": res["mermaid"], "provider": res.get("provider"),
                "nodes": res.get("nodes", 0), "edges": res.get("edges", 0),
                "_detail": "已微调流程图(节点 %d→%d,边 %d→%d)"
                           % (old_nodes, res.get("nodes", 0),
                              old_edges, res.get("edges", 0))}

    job, created = jobs_service.submit(pid, user["id"], "flowchart_refine", runner)
    return _ok({"job": job, "created": created})


@router.post("/projects/{id}/design/refine")
def refine_design(id: int, body: S.RefineIn, user=Depends(deps.require_user)):
    p = deps.get_project(id, user, write=True)
    _require_llm()
    slug, pid = p["slug"], p["id"]
    if not (storage.get_design(slug).get("sheets") or []):
        raise HTTPException(400, "尚未生成 ER 结构")

    def runner(progress):
        progress("读取当前 ER 结构与来源", pct=15)
        current = storage.get_design(slug)         # 任务执行时重读
        plan_md = storage.get_plan(slug)
        mmd = storage.get_flowchart(slug)
        res = design_service.refine_design(current, body.instruction, plan_md, mmd,
                                           progress=progress,
                                           frozen_keys=EB.frozen_keys(slug))
        design = {"sheets": res.get("sheets") or [],
                  "dicts": res.get("dicts") or {},
                  "groups": res.get("groups") or [],
                  "automations": res.get("automations") or []}
        progress("落盘表单/自动化定义并做离线校验(%d 张表)" % len(design["sheets"]), pct=94)
        design, check, error = _sync(slug, p.get("app_code", ""), design)
        storage.set_design(slug, design)           # 只写本阶段文件(design.json + 派生 sheets/automations)
        storage.record_snapshot(slug, "design", design, origin="refine",
                                instruction=body.instruction, provider=res.get("provider"))
        storage.set_stage(slug, "design", src=storage.stage_src(slug, "design"))
        db.add_event(pid, "design", "AI 微调 ER 结构")
        payload = _design_payload(design, res.get("provider"), check, error)
        payload["_detail"] = "已微调 ER 结构(%d 表/%d 自动化)" % (
            len(design["sheets"]), len(design.get("automations") or []))
        return payload

    job, created = jobs_service.submit(pid, user["id"], "design_refine", runner)
    return _ok({"job": job, "created": created})


# ---------------------------------------------------------------- 历史 / 阶段状态
@router.get("/projects/{id}/history")
def get_history(id: int, stage: str, user=Depends(deps.require_user)):
    """某阶段的历史版本列表(最新在前),供回滚。"""
    p = deps.get_project(id, user)
    if stage not in storage.STAGES:
        raise HTTPException(400, "未知阶段 %r" % stage)
    return _ok({"items": storage.list_history(p["slug"], stage)})


@router.post("/projects/{id}/history/restore")
def restore_history(id: int, body: S.HistoryRestoreIn, user=Depends(deps.require_user)):
    """把某阶段回滚到指定历史版本(回滚本身也记一条历史)。"""
    p = deps.get_project(id, user, write=True)
    slug, pid = p["slug"], p["id"]
    text = storage.read_snapshot(slug, body.stage, body.id)
    if text is None:
        raise HTTPException(404, "历史版本不存在")
    if body.stage == "plan":
        storage.set_plan(slug, text)
        storage.record_snapshot(slug, "plan", text, origin="restore")
        storage.set_stage(slug, "plan")
        db.update_project(pid, status="planned")
    elif body.stage == "flowchart":
        storage.set_flowchart(slug, text)
        storage.record_snapshot(slug, "flowchart", text, origin="restore")
        storage.set_stage(slug, "flowchart", src=storage.stage_src(slug, "flowchart"))
        db.update_project(pid, status="flowcharted")
    else:
        try:
            design = json.loads(text)
        except Exception:
            raise HTTPException(400, "历史版本内容损坏,无法回滚")
        design, check, error = _sync(slug, p.get("app_code", ""), design)
        storage.set_design(slug, design)
        storage.record_snapshot(slug, "design", design, origin="restore")
        storage.set_stage(slug, "design", src=storage.stage_src(slug, "design"))
        db.update_project(pid, status="designed")
    db.add_event(pid, body.stage, "回滚到历史版本")
    return _ok({"stage": body.stage, "stages": storage.get_stages(slug)})


@router.get("/projects/{id}/stages")
def get_stages(id: int, user=Depends(deps.require_user)):
    """各阶段状态:是否已有产物 + 是否因上游变化而过期(stale)。"""
    p = deps.get_project(id, user)
    return _ok(storage.get_stages(p["slug"]))
