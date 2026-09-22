# -*- coding: utf-8 -*-
"""全局资料库:把用户新建的「资料」(含上传文档)编译成 AI 可参考的知识库产物。

产物 `data/knowledge/library.md` —— 与 corpus.md / patterns.md 并列,
由 plan / design 生成时作为参考资料读取。语料全部来自用户上传的资料,不含内置样本。
"""
import os

from ..core import config as C
from ..db import database as db

_LIBRARY_MD = "library.md"
_MAX_DOC_CHARS = 12000


def _item_body(item):
    """一份资料的正文:AI 分析(优先)→ 各文档摘要 → 文档正文截断。"""
    analysis = (item.get("analysis") or "").strip()
    if analysis:
        return analysis
    docs = db.list_library_documents(item["id"])
    parts = []
    for d in docs:
        summary = (d.get("summary") or "").strip()
        if not summary:
            summary = (d.get("parsed_text") or "").strip()[:_MAX_DOC_CHARS // 2]
        if summary:
            parts.append("### 文档:%s\n%s" % (d.get("filename") or ("#%s" % d.get("id")), summary))
    return "\n\n".join(parts)


def library_context(item):
    """一份资料喂给 AI 的正文(含描述 + 分析/摘要)。供项目按名称参考时使用。"""
    head = "# %s" % item.get("name", "")
    desc = (item.get("description") or "").strip()
    body = _item_body(item)
    return "\n\n".join(x for x in (head, desc, body) if x).strip()


def render_library_digest():
    """把全部资料编译成 `data/knowledge/library.md`(名称 · 描述 · 分析);返回统计。

    资料由 DB 管理,删除即删除:无资料时产物同步清空(避免 AI 参考到已删资料)。
    """
    os.makedirs(C.KNOWLEDGE_DIR, exist_ok=True)
    items = db.list_library_items()
    lines = ["# 已有系统资料库(全局共享)", "",
             "由用户新建资料并上传文档、夜间由大模型整理,**供新项目设计参考**。勿手改。", ""]
    if not items:
        lines += ["(暂无共享资料:可在左侧「资料库」新建资料并上传已有系统文档)", ""]
    for it in items:
        lines.append("## %s" % it.get("name", ""))
        desc = (it.get("description") or "").strip()
        if desc:
            lines.append("- 说明:%s" % desc)
        body = _item_body(it)
        if body:
            lines.append(body)
        lines.append("")
    path = os.path.join(C.KNOWLEDGE_DIR, _LIBRARY_MD)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return {"items": len(items), "path": path, "written": True}
