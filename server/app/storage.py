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
import hashlib
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
    """全局资料库上传件落盘(server/data/library/uploads/);与项目上传件分开存放。"""
    safe = re.sub(r"[^\w.\-]+", "_", filename or "upload")[:120] or "upload"
    os.makedirs(C.LIBRARY_UPLOAD_DIR, exist_ok=True)
    stored = os.path.join(C.LIBRARY_UPLOAD_DIR, "%d_%s" % (int(time.time() * 1000), safe))
    with open(stored, "wb") as f:
        f.write(content)
    return stored, os.path.splitext(safe)[1].lower()


# ---- 版本快照 / 阶段指纹(AI 微调与回滚) -------------------------------
# 每次「生成 / AI 微调 / 手动保存 / 回滚」都会把该阶段的新版本存一份快照,
# 形成版本时间线(最新一条即当前产物),支持回滚到任意历史版本。
# `.stages.json` 记录各阶段的**上游内容指纹**,用于判定下游是否已过期(stale)。
_HISTORY_DIR = ".history"
_STAGES_FILE = ".stages.json"
_STAGE_EXT = {"plan": "md", "flowchart": "mmd", "design": "json"}
_HISTORY_KEEP = 30
STAGES = ("plan", "flowchart", "design")


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _sha1(text):
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def stage_src(slug, stage):
    """某阶段的**上游内容指纹**;上游内容变化即说明该阶段产物已过期。

    依赖链:方案=源头;流程图只依方案;ER 依「方案 + 流程图」。
    """
    if stage == "flowchart":
        return _sha1(get_plan(slug))
    if stage == "design":
        return _sha1(get_plan(slug) + "\n---\n" + get_flowchart(slug))
    return _sha1(get_plan(slug))


def _history_dir(slug, stage, create=False):
    d = os.path.join(project_dir(slug), _HISTORY_DIR, stage)
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def _history_index(slug, stage):
    p = os.path.join(_history_dir(slug, stage), "index.json")
    if not os.path.isfile(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def record_snapshot(slug, stage, content, origin="generate", instruction="", provider=""):
    """把某阶段产物存一份快照(版本时间线;最新一条即当前内容);仅保留最近 N 条。"""
    d = _history_dir(slug, stage, create=True)
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=1)
    hid = "%d_%s" % (int(time.time() * 1000), _sha1(text)[:8])
    fname = "%s.%s" % (hid, _STAGE_EXT.get(stage, "txt"))
    with open(os.path.join(d, fname), "w", encoding="utf-8") as f:
        f.write(text)
    idx = _history_index(slug, stage)
    idx.append({"id": hid, "file": fname, "at": _now(), "origin": origin,
                "instruction": (instruction or "")[:500], "provider": provider or "",
                "bytes": len(text.encode("utf-8"))})
    dropped = idx[:-_HISTORY_KEEP] if len(idx) > _HISTORY_KEEP else []
    idx = idx[-_HISTORY_KEEP:]
    for it in dropped:
        try:
            os.remove(os.path.join(d, it.get("file") or ""))
        except Exception:
            pass
    with open(os.path.join(d, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    return idx[-1]


def list_history(slug, stage):
    """该阶段的历史版本(最新在前,不含 file 字段)。"""
    out = []
    for it in reversed(_history_index(slug, stage)):
        out.append({"id": it.get("id"), "at": it.get("at", ""),
                    "origin": it.get("origin", ""), "instruction": it.get("instruction", ""),
                    "provider": it.get("provider", ""), "bytes": it.get("bytes", 0)})
    return out


def read_snapshot(slug, stage, hid):
    for it in _history_index(slug, stage):
        if it.get("id") == hid:
            p = os.path.join(_history_dir(slug, stage), it.get("file") or "")
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    return f.read()
            return None
    return None


def set_stage(slug, stage, src=None, at=None):
    """记录阶段状态:src=上游内容指纹(有则用于 stale 判定);at=更新时间。"""
    raw = read_json_file(slug, _STAGES_FILE, {}) or {}
    rec = dict(raw.get(stage) or {})
    if src is not None:
        rec["src"] = src
    rec["at"] = at or _now()
    raw[stage] = rec
    return write_json_file(slug, _STAGES_FILE, raw)


def get_stages(slug):
    """各阶段状态:{stage: {at, stale}};stale=上游内容已变化(下游需重生成)。"""
    raw = read_json_file(slug, _STAGES_FILE, {}) or {}
    out = {}
    for st in STAGES:
        rec = raw.get(st) or {}
        fresh = rec.get("src")
        out[st] = {"at": rec.get("at", ""),
                   "stale": bool(fresh) and fresh != stage_src(slug, st)}
    return out
