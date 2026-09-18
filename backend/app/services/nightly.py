# -*- coding: utf-8 -*-
"""夜间批处理:对「已有系统」文档做总结分类,并刷新设计知识库。"""
import threading
import time

from ..core import config as C
from .. import engine_bridge as EB
from ..db import database as db


def nightly_learn(trigger="manual") -> dict:
    from .llm import get_provider, extract_json
    job = db.add_job("nightly_learn", "触发:%s" % trigger)
    provider = get_provider()
    docs = [d for d in db.list_documents() if d.get("kind") == "existing_system"
            and d.get("status") != "learned"]
    learned, failed = 0, 0
    for d in docs:
        try:
            text = (d.get("parsed_text") or "")[:12000]
            if provider.available:
                out = extract_json(provider.complete(
                    "你是企业信息化顾问。阅读用户的「已有系统文档」,输出 JSON:"
                    '{"summary":"200字内摘要","domain":"业务领域","tags":["主题词"]}',
                    "文件名:%s\n内容:\n%s" % (d["filename"], text), json_mode=True))
                summary = out.get("summary", "")
                tags = out.get("tags", [])
            else:
                tags = [k for k in ("客户", "合同", "项目", "门店", "人员", "申请",
                                    "报销", "预算", "任务", "库存", "订单")
                        if k in text]
                summary = "文件:%s\n主题:%s" % (d["filename"], "、".join(tags) or "-")
            db.update_document(d["id"], summary=summary,
                               tags=",".join(tags), status="learned")
            learned += 1
        except Exception:
            failed += 1
    try:
        kb = EB.refresh_knowledge()
    except Exception as e:
        db.finish_job(job, "error", "知识库刷新失败:%s" % e)
        return {"job": job, "learned": learned, "failed": failed, "error": str(e)}
    detail = "提供者:%s 学习:%d 失败:%d 知识库:%s 项目/%s 表" % (
        provider.name, learned, failed,
        kb.get("projects", len(kb.get("names", []))), kb.get("tables", ""))
    db.finish_job(job, "done", detail)
    return {"job": job, "learned": learned, "failed": failed,
            "provider": provider.name, "knowledge": kb, "detail": detail}


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
