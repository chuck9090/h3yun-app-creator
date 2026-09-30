# -*- coding: utf-8 -*-
"""夜间批处理:把「资料库」资料下的文档整理成 AI 分析,并刷新设计知识库。"""
import threading
import time

from ..core import config as C
from .. import engine_bridge as EB
from ..db import database as db

_MAX_DOC_CHARS = 12000
_MAX_TOTAL_CHARS = 40000


def _doc_text(d):
    return (d.get("parsed_text") or "").strip()[:_MAX_DOC_CHARS]


def _fallback_analysis(item, docs):
    """无 LLM 时的回退:按文件名与关键词做个朴素整理。"""
    kws = ("客户", "合同", "项目", "门店", "人员", "申请", "报销", "预算",
           "任务", "库存", "订单", "审批", "流程")
    lines = ["## %s" % item.get("name", "")]
    if (item.get("description") or "").strip():
        lines.append(item["description"].strip())
    lines.append("")
    lines.append("### 涉及文档")
    for d in docs:
        text = _doc_text(d)
        hit = [k for k in kws if k in text]
        lines.append("- %s%s" % (d.get("filename") or "", ("(主题:%s)" % "、".join(hit)) if hit else ""))
    return "\n".join(lines).strip()


def _analyze_item(provider, item, docs):
    """对一份资料下的全部文档做 AI 整理;返回 (markdown, used_ids)。

    used_ids 为真正编入本次 LLM 输入的文档 id(F4):超 _MAX_TOTAL_CHARS 被
    break 掉的文档不在其中,调用方只应把 used_ids 标 learned。
    """
    if provider.available:
        from .llm import extract_json
        blocks = []
        used_ids = []
        total = 0
        for d in docs:
            text = _doc_text(d)
            if not text:
                continue
            block = "### 文档:%s\n%s" % (d.get("filename") or "", text)
            if total + len(block) > _MAX_TOTAL_CHARS:
                break
            blocks.append(block)
            used_ids.append(d["id"])
            total += len(block)
        out = extract_json(provider.complete(
            "你是企业信息化顾问。阅读用户提供的资料(同一份「资料」下的多份文档),"
            "整理成一份结构化的《已有系统梳理》Markdown,供后续做新系统设计时参考。"
            "严格输出 JSON:{\"analysis\":\"Markdown 正文\"}。"
            "analysis 建议包含:业务领域、功能模块、关键表单/表及主字段、关键流程/审批、"
            "与其他模块的关联、可复用的设计惯例。只基于给到的内容,不要编造。",
            "资料名称:%s\n资料描述:%s\n\n%s"
            % (item.get("name", ""), item.get("description", ""), "\n\n".join(blocks)),
            json_mode=True))
        md = (out.get("analysis") or "").strip()
        if md:
            return md, used_ids
    # fallback:读全部文档且无长度 break,故全部视为已入模
    return _fallback_analysis(item, docs), [d["id"] for d in docs]


def nightly_learn(trigger="manual") -> dict:
    job = db.add_job("nightly_learn", "触发:%s" % trigger)
    from .llm import get_provider
    provider = get_provider()
    items = db.list_library_items()
    learned, skipped, failed = 0, 0, 0
    for it in items:
        docs = db.list_library_documents(it["id"])
        if not docs:
            skipped += 1
            continue
        # 已有分析且无新文档(全部 learned)则跳过,避免每晚重复调用 LLM
        pending = [d for d in docs if d.get("status") != "learned"]
        if (it.get("analysis") or "").strip() and not pending:
            skipped += 1
            continue
        try:
            analysis, used_ids = _analyze_item(provider, it, docs)
            db.update_library_item(it["id"], analysis=analysis, analysis_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                                   analysis_error="")
            for d in pending:
                if d["id"] in used_ids:                 # F4:只标真正入模的文档
                    db.update_document(d["id"], status="learned")
            learned += 1
        except Exception as e:
            db.update_library_item(it["id"], analysis_error=str(e)[:1000])
            failed += 1
    try:
        kb = EB.refresh_knowledge()
    except Exception as e:
        db.finish_job(job, "error", "知识库刷新失败:%s" % e)
        return {"job": job, "learned": learned, "failed": failed, "error": str(e)}
    detail = "提供者:%s 整理资料:%d 跳过:%d 失败:%d 知识库:%s 项目/%s 表" % (
        provider.name, learned, skipped, failed,
        kb.get("projects", 0), kb.get("tables", ""))
    db.finish_job(job, "done", detail)
    return {"job": job, "learned": learned, "skipped": skipped, "failed": failed,
            "provider": provider.name, "knowledge": kb, "detail": detail}


def analyze_library_item(item_id: int) -> dict:
    """手动整理某一份资料(管理员/上传者触发)。"""
    item = db.get_library_item(item_id)
    if not item:
        return {"ok": False, "message": "资料不存在"}
    from .llm import get_provider
    provider = get_provider()
    docs = db.list_library_documents(item_id)
    if not docs:
        return {"ok": False, "message": "该资料下还没有文档"}
    analysis, used_ids = _analyze_item(provider, item, docs)
    db.update_library_item(item_id, analysis=analysis, analysis_at=time.strftime("%Y-%m-%d %H:%M:%S"), analysis_error="")
    for d in docs:
        if d["id"] in used_ids:                         # F4:只标真正入模的文档
            db.update_document(d["id"], status="learned")
    try:
        EB.refresh_knowledge()
    except Exception:
        pass
    return {"ok": True, "provider": provider.name,
            "item": db.get_library_item(item_id)}


def _seconds_until_next():
    now = time.localtime()
    target = time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                          C.NIGHTLY_HOUR, C.NIGHTLY_MIN, 0, 0, 0, -1))
    if target <= time.time():
        target += 86400
    return target - time.time()


def start_scheduler():
    def loop():
        while True:
            time.sleep(_seconds_until_next())
            try:
                nightly_learn("schedule")
            except Exception:
                pass
    t = threading.Thread(target=loop, name="h3-nightly", daemon=True)
    t.start()
    return t
