# -*- coding: utf-8 -*-
"""设计记忆编译器 —— 把 projects/ 下已建/已设计系统编译成可复用的设计知识库。

用途(AI 层「粗需求 → 设计」的检索底座):
  过去做过哪些系统、每张表有哪些字段/子表/关联、哪些枚举、哪些自动化、
  界面手工配置的意图(uiNote)与领域设计文档在哪 —— 全部编译成紧凑、可读的知识库,
  让 AI 接到一个大概的需求时先"翻旧账",按同类系统的惯例补齐客户没想到的表/字段/关系。

确定性、零 LLM:只读 projects/ 下的定义文件,不联网、不需要凭据。

产物(默认落 <root>/knowledge/):
  corpus.json     机器可读全量(表/字段/子表/关联/枚举/自动化/文档索引)
  corpus.md       人/AI 可读的按项目表盘点(含 uiNote)
  patterns.md     跨项目共识:枚举字典 / 常见字段 / 表关系图 / 自动化样例 / 文档索引
"""
import json
import os
import re

# 跳过测试/锚点项目(下划线前缀、e2e、smoke)与缓存目录
_SKIP_DIRS = {"__pycache__"}
_SKIP_RE = re.compile(r"(^_)|(e2e)|(smoke)|(^web_tmp)", re.I)
# 字段上值得保留的设计键(其余忽略,保持知识库紧凑)
_FIELD_KEYS = ("required", "readonly", "default", "dict", "options",
               "assoc", "assocField", "filter", "rule", "hideWhen",
               "uiNote", "placeholder", "prefix", "datetime", "increment",
               "checked", "defaults", "multi", "decimals", "decimal",
               "maxSize", "meters", "areaMode", "rows",
               "content", "title", "align")   # 布局项(group_title/description)用


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _list_dirs(path):
    if not os.path.isdir(path):
        return []
    return sorted(d for d in os.listdir(path)
                  if os.path.isdir(os.path.join(path, d))
                  and d not in _SKIP_DIRS and not _SKIP_RE.search(d))


def _norm_field(ctrl):
    """控件 → 紧凑字段记录:只留 key/label/type + 有值的设计键。"""
    rec = {"key": ctrl.get("key", ""), "label": ctrl.get("label", ""),
           "type": ctrl.get("type", "")}
    for k in _FIELD_KEYS:
        if k in ctrl and ctrl[k] not in (None, "", [], {}):
            rec[k] = ctrl[k]
    if ctrl.get("type") == "subtable":
        rec["columns"] = [_norm_field(c) for c in ctrl.get("columns") or []]
    return rec


def _relations(fields):
    """从 query/dropdown(assoc) 抽出表间关联边。"""
    out = []
    for f in fields:
        if f.get("assoc"):
            out.append({"field": f["key"], "label": f.get("label", ""),
                        "target": f["assoc"], "kind": f.get("type")})
    return out


def scan_sheet(path):
    """sheets/*.json → 表记录。"""
    d = _read_json(path)
    fields = [_norm_field(c) for c in d.get("controls") or []]
    subs = [f for f in fields if f["type"] == "subtable"]
    return {
        "source": "json",
        "title": d.get("title", ""),
        "nameSchema": d.get("nameSchema", ""),
        "useOwner": bool(d.get("useOwner")),
        "group": d.get("group", ""),
        "layout": d.get("layout", ""),
        "fields": fields,
        "relations": _relations(fields),
        "subtables": [{"key": s["key"], "label": s["label"],
                       "columns": len(s.get("columns") or [])} for s in subs],
    }


def _legacy_tables(proj_dir):
    """legacy(forms.py)项目:表清单从 registry.json 取(字段定义在 forms.py,不解析)。"""
    rp = os.path.join(proj_dir, "registry.json")
    if not os.path.isfile(rp):
        return []
    try:
        reg = _read_json(rp)
    except Exception:
        return []
    out = []
    for k, v in sorted(reg.items()):
        if k.startswith("_") or not isinstance(v, dict):
            continue
        out.append({"source": "legacy", "key": k, "title": v.get("title", ""),
                    "nameSchema": "", "useOwner": None, "group": "",
                    "fields": [], "relations": [], "subtables": [],
                    "note": v.get("detail", "")})
    return out


def _scan_automations(proj_dir):
    adir = os.path.join(proj_dir, "automations")
    if not os.path.isdir(adir):
        return []
    out = []
    for fn in sorted(os.listdir(adir)):
        if not fn.endswith(".json"):
            continue
        try:
            d = _read_json(os.path.join(adir, fn))
        except Exception:
            continue
        acts = []
        for a in d.get("actions") or []:
            acts.append({"do": a.get("do", ""), "target": a.get("target", ""),
                         "state": a.get("state", ""),
                         "hasSub": bool(a.get("sub"))})
        out.append({"key": os.path.splitext(fn)[0], "title": d.get("title", ""),
                    "form": d.get("form", ""), "trigger": d.get("trigger", ""),
                    "when": d.get("when"), "actions": acts,
                    "note": d.get("_note", "")})
    return out


def scan_project(projects_dir, name):
    """一个 projects/<name>/ → 项目记录。"""
    pdir = os.path.join(projects_dir, name)
    rec = {"name": name, "tables": [], "enums": {}, "automations": [],
           "groups": [], "docs": {}}
    sj = os.path.join(pdir, "sheets")
    if os.path.isdir(sj):
        for fn in sorted(os.listdir(sj)):
            if fn.endswith(".json"):
                rec["tables"].append(dict(scan_sheet(os.path.join(sj, fn)),
                                          key=os.path.splitext(fn)[0]))
    if not rec["tables"]:
        rec["tables"] = _legacy_tables(pdir)
        if rec["tables"]:
            rec["kind"] = "legacy"
    else:
        rec["kind"] = "json"
    dj = os.path.join(pdir, "dicts.json")
    if os.path.isfile(dj):
        try:
            rec["enums"] = _read_json(dj)
        except Exception:
            pass
    gj = os.path.join(pdir, "groups.json")
    if os.path.isfile(gj):
        try:
            rec["groups"] = [g.get("name") if isinstance(g, dict) else g
                             for g in _read_json(gj)]
        except Exception:
            pass
    rec["automations"] = _scan_automations(pdir)
    for doc in ("DESIGN.md", "UI_manual_config.md", "analysis_sql.md", "DELIVER.md"):
        if os.path.isfile(os.path.join(pdir, doc)):
            rec["docs"][doc] = "projects/%s/%s" % (name, doc)
    return rec


def build_corpus(projects_dir, names=None):
    """names=None 时扫全部实项目(跳过 _ 前缀测试项目);给定则只扫指定项目名。"""
    corpus = {"projects": []}
    for name in (names if names is not None else _list_dirs(projects_dir)):
        if os.path.isdir(os.path.join(projects_dir, name)):
            corpus["projects"].append(scan_project(projects_dir, name))
    return corpus


# ---------------------------------------------------------------- 渲染
def _md_escape(s):
    return str(s).replace("|", "\\|")


def _render_field(f, indent="  "):
    bits = ["`%s`" % f.get("key", ""), f.get("label", ""), "(%s)" % f.get("type", "")]
    for k in ("required", "readonly", "dict", "assoc", "rule", "hideWhen",
              "default", "options", "uiNote"):
        if k in f:
            v = f[k]
            if isinstance(v, list):
                v = "/".join(str(x) for x in v)
            bits.append("%s=%s" % (k, v))
    line = indent + "- " + " ".join(str(b) for b in bits if b)
    cols = f.get("columns")
    if cols:
        line += "\n" + indent + "  - 列: " + "; ".join(
            "%s(%s)" % (c.get("label") or c.get("key"), c.get("type")) for c in cols)
    return line


def render_corpus_md(corpus):
    """按项目盘点,含字段与 uiNote —— 给 AI 看"过去怎么建的"。"""
    L = ["# 设计语料(过往系统盘点)",
         "",
         "由知识库编译器从 `data/projects/` 编译(Web 端建/改项目后自动)。**勿手改**。",
         "用途:新需求先在这里找同类系统,按既有惯例补齐表/字段/关系。", ""]
    for p in corpus["projects"]:
        L.append("## 项目 `%s` (%s) %s" % (p["name"], p.get("kind", ""),
                                           "/".join(p.get("groups") or [])))
        for f, path in sorted((p.get("docs") or {}).items()):
            L.append("- 文档: [`%s`](%s)" % (f, path))
        for t in p["tables"]:
            hdr = "### %s · %s" % (t["key"], t["title"])
            meta = []
            if t.get("group"):
                meta.append("分组=%s" % t["group"])
            if t.get("useOwner") is not None:
                meta.append("useOwner=%s" % t["useOwner"])
            if t.get("nameSchema"):
                meta.append("标题=%s" % t["nameSchema"])
            if meta:
                hdr += "  _(" + ", ".join(meta) + ")_"
            L.append(hdr)
            if t.get("note"):
                L.append("- %s" % t["note"])
            for fl in t["fields"]:
                L.append(_render_field(fl))
            if t.get("relations"):
                L.append("- 关联: " + ", ".join(
                    "%s→%s" % (r["field"], r["target"]) for r in t["relations"]))
            L.append("")
        if p["automations"]:
            L.append("#### 自动化")
            for a in p["automations"]:
                L.append("- `%s` %s [%s@%s] 动作:%s%s"
                         % (a["key"], a["title"], a["form"], a["trigger"],
                            ",".join("%s→%s" % (x["do"], x["target"]) for x in a["actions"]),
                            ("  // " + a["note"]) if a.get("note") else ""))
            L.append("")
    return "\n".join(L)


def render_patterns_md(corpus):
    """跨项目共识:枚举/常见字段/关系图/自动化样例。"""
    enum_vals = {}
    field_stat = {}
    rel_edges = []
    for p in corpus["projects"]:
        for cat, vals in (p.get("enums") or {}).items():
            vals = [v.get("name") if isinstance(v, dict) else v for v in vals]
            enum_vals.setdefault(cat, {"values": [], "src": []})
            for v in vals:
                if v not in enum_vals[cat]["values"]:
                    enum_vals[cat]["values"].append(v)
            enum_vals[cat]["src"].append(p["name"])
        for t in p["tables"]:
            for fl in t["fields"]:
                key = (fl.get("key"), fl.get("type"))
                st = field_stat.setdefault(key, {"labels": [], "n": 0})
                st["n"] += 1
                if fl.get("label") and fl["label"] not in st["labels"]:
                    st["labels"].append(fl["label"])
            for r in t.get("relations") or []:
                rel_edges.append(("%s.%s" % (t["key"], r["field"]), r["target"],
                                  p["name"]))
    L = ["# 设计共识(跨项目汇总)", "",
         "由知识库编译器从 `data/projects/` 编译。**勿手改**。", ""]
    L.append("## 枚举字典(合并去重)")
    for cat in sorted(enum_vals):
        e = enum_vals[cat]
        L.append("- **%s**: %s  _(%s)_"
                 % (cat, "、".join(_md_escape(v) for v in e["values"]),
                    ",".join(sorted(set(e["src"])))))
    L.append("")
    L.append("## 常见字段(语义码 → 类型 / 常见显示名 / 出现次数)")
    for (key, typ), st in sorted(field_stat.items(),
                                 key=lambda x: -x[1]["n"]):
        if st["n"] < 2:
            continue   # 只留跨表复现的语义码,单个的噪音大
        L.append("- `%s` (%s) x%d — %s"
                 % (key, typ, st["n"], "/".join(_md_escape(x) for x in st["labels"])))
    L.append("")
    L.append("## 表关系图(源.字段 → 目标表)")
    for src, target, proj in sorted(set(rel_edges)):
        L.append("- [%s] %s → %s" % (proj, src, target))
    L.append("")
    L.append("## 自动化样例")
    seen = False
    for p in corpus["projects"]:
        for a in p["automations"]:
            seen = True
            L.append("- [%s] %s: %s @ %s → %s"
                     % (p["name"], a["key"], a["title"], a["trigger"],
                        ", ".join("%s %s" % (x["do"], x["target"]) for x in a["actions"])))
    if not seen:
        L.append("- (暂无)")
    L.append("")
    L.append("## 领域设计文档索引")
    for p in corpus["projects"]:
        for f, path in sorted((p.get("docs") or {}).items()):
            L.append("- [%s] %s: %s" % (p["name"], f, path))
    L.append("")
    return "\n".join(L)


def write_corpus(corpus, out_dir, keep_if_empty=True):
    """写入知识库产物。

    语料**全部来自用户自己的资料**(`data/projects/<名>/` 下用户建/上传的项目定义),
    不含任何内置样本。无任何项目且 `keep_if_empty` 时保留现有产物(不清空)。
    """
    projects = corpus.get("projects") or []
    if not projects and keep_if_empty and os.path.isfile(os.path.join(out_dir, "corpus.json")):
        return None
    out = {"projects": projects}
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "corpus.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "corpus.md"), "w", encoding="utf-8") as f:
        f.write(render_corpus_md(out))
    with open(os.path.join(out_dir, "patterns.md"), "w", encoding="utf-8") as f:
        f.write(render_patterns_md(out))
    return out


def corpus_stats(corpus):
    return {"projects": len(corpus.get("projects", [])),
            "tables": sum(len(p.get("tables", [])) for p in corpus.get("projects", [])),
            "automations": sum(len(p.get("automations", []))
                               for p in corpus.get("projects", []))}


def write_knowledge(projects_dir, out_dir):
    return write_corpus(build_corpus(projects_dir), out_dir)
