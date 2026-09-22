# -*- coding: utf-8 -*-
"""项目运行时工作区(文件系统)。

`projects/<slug>/` 结构与引擎标准格式完全兼容:
    plan.md            系统设计方案(markdown)
    flowchart.mmd      业务流程图(mermaid 源码)
    design.json        ER 结构(权威)
    requirement.json   需求富文本
    uploads/           上传原件
    sheets/*.json      部署时由 design.json 生成(引擎消费)
"""
import json
import os
import re
import time

from .core import config as C


def project_dir(slug: str, create: bool = False) -> str:
    d = os.path.join(C.PROJECTS_DIR, slug)
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def _path(slug, *parts):
    return os.path.join(project_dir(slug, create=True), *parts)


def read_text(slug, name, default=""):
    p = os.path.join(project_dir(slug), name)
    if not os.path.isfile(p):
        return default
    with open(p, encoding="utf-8") as f:
        return f.read()


def write_text(slug, name, text):
    p = _path(slug, name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text or "")
    os.replace(tmp, p)      # 原子替换:并发读不会拿到半截内容
    return p


def read_json_file(slug, name, default=None):
    p = os.path.join(project_dir(slug), name)
    if not os.path.isfile(p):
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json_file(slug, name, obj):
    p = _path(slug, name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)      # 原子替换:并发读不会拿到半截内容
    return p


# ---- 具名读写 ----------------------------------------------------------
def get_plan(slug):
    return read_text(slug, "plan.md")


def set_plan(slug, md):
    return write_text(slug, "plan.md", md)


def get_flowchart(slug):
    return read_text(slug, "flowchart.mmd")


def set_flowchart(slug, mmd):
    return write_text(slug, "flowchart.mmd", mmd)


def get_design(slug):
    return read_json_file(slug, "design.json", {"sheets": [], "dicts": {}, "groups": []})


def set_design(slug, design):
    return write_json_file(slug, "design.json", design)


def get_requirement(slug):
    d = read_json_file(slug, "requirement.json", {})
    return {"html": d.get("html", ""), "text": d.get("text", "")}


def set_requirement(slug, html, text=""):
    # 需求正文也写一份 requirement.md,便于 AI/引擎读取纯文本
    write_text(slug, "requirement.md", text or _strip_html(html))
    return write_json_file(slug, "requirement.json", {"html": html, "text": text})


def requirement_text(slug):
    d = get_requirement(slug)
    return d.get("text") or _strip_html(d.get("html") or "")


def _strip_html(html):
    return re.sub(r"<[^>]+>", " ", html or "").strip()


# ---- 上传 ---------------------------------------------------------------
def save_upload(slug, filename, content: bytes):
    safe = re.sub(r"[^\w.\-]+", "_", filename or "upload")[:120] or "upload"
    folder = _path(slug, "uploads")
    os.makedirs(folder, exist_ok=True)
    stored = os.path.join(folder, "%d_%s" % (int(time.time() * 1000), safe))
    with open(stored, "wb") as f:
        f.write(content)
    return stored, os.path.splitext(safe)[1].lower()


def save_library_upload(filename, content: bytes):
    """全局资料库上传件落盘(data/library/uploads/);与项目上传件分开存放。"""
    safe = re.sub(r"[^\w.\-]+", "_", filename or "upload")[:120] or "upload"
    os.makedirs(C.LIBRARY_UPLOAD_DIR, exist_ok=True)
    stored = os.path.join(C.LIBRARY_UPLOAD_DIR, "%d_%s" % (int(time.time() * 1000), safe))
    with open(stored, "wb") as f:
        f.write(content)
    return stored, os.path.splitext(safe)[1].lower()
