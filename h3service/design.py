# -*- coding: utf-8 -*-
"""设计落盘层:方案(proposal)/表单结构(design) ↔ 标准 sheets/*.json。

职责
----
- 定义 Web 端与引擎之间的**设计数据契约**(纯 dict,便于 JSON 传输)。
- 清洗 AI/用户产出的控件(类型白名单 + 允许键白名单,剔除幻觉键)。
- 把设计写成引擎标准格式的 `projects/<名>/sheets/*.json + dicts.json + groups.json + automations/*.json`。
- 回读现有项目定义,供前端 ER 图/编辑器使用。

不联网;合法性由 `engine.run_check` 兜底(DSL/平台约束)。
"""
import json
import os
import re

from . import engine as E

# 控件类型 → 允许的额外键(通用键另加)。与 docs/schema_doc.md 控件表一致。
COMMON_KEYS = {"type", "key", "label", "required", "readonly", "hideWhen", "uiNote"}
TYPE_KEYS = {
    "text": {"default", "placeholder"},
    "textarea": {"rows", "default"},
    "number": {"decimal", "default"},
    "date": {"datetime"},
    "switch": {"checked"},
    "radio": {"dict", "options", "default"},
    "dropdown": {"dict", "options", "default", "assoc", "assocField", "filter"},
    "checkbox_list": {"dict", "options", "defaults"},
    "member": {"multi"},
    "department": {"multi"},
    "query": {"assoc", "multi"},
    "seq_no": {"prefix", "datetime", "increment"},
    "image": {"multiple", "cameraOnly", "watermark", "compression"},
    "attachment": {"maxSize"},
    "location": {"meters", "pcEnabled", "editable"},
    "address": {"areaMode", "showDetail"},
    "formula": {"rule", "decimal", "bindType"},
    "group_title": {"align"},
    "description": {"content", "title"},
    "subtable": {"columns", "fixed"},
}
# 子表列支持的类型(见 docs/schema_doc.md「子表」)
COLUMN_TYPES = {"text", "textarea", "number", "date", "switch", "radio",
                "dropdown", "checkbox_list", "attachment", "image"}
# 布局项(不是字段,key 只作引用名,不受字段命名约束)
LAYOUT_ITEM_TYPES = {"group_title", "description"}
# 顶层键(表单文件)
SHEET_KEYS = {"title", "nameSchema", "useOwner", "layout", "group", "controls"}
# 表单 key / 自动化 key = 文件名,必须防路径穿越(字母开头、纯字母数字)
_NAME_OK = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,47}$")
# 自动化允许的键(见 docs/schema_doc.md「自动化」)
AUTO_KEYS = {"key", "title", "form", "trigger", "sortKey", "names", "when", "actions"}
AUTO_ACTION_KEYS = {"do", "target", "state", "isInsert", "match", "set", "owner", "sub"}
AUTO_TRIGGERS = {"生效", "失效", "生效或更新"}
AUTO_DOS = {"新增", "更新", "删除"}

_LAYOUT_ITEMS = {"group_title", "description"}


def clean_control(spec, in_subtable=False):
    """按类型白名单清洗单个控件;返回 None 表示丢弃(非法/未知类型)。

    - 剔除 AI 幻觉键,只留 DSL 认识的键;
    - 子表列内类型受限(COLUMN_TYPES),布局项不能作列。
    """
    if not isinstance(spec, dict):
        return None
    t = (spec.get("type") or "").strip()
    if t not in TYPE_KEYS:
        return None
    if in_subtable and t not in COLUMN_TYPES:
        return None
    out = {"type": t}
    # key:布局项/流水号可省;其余必须有
    key = spec.get("key")
    if key:
        out["key"] = str(key).strip()
    elif t not in _LAYOUT_ITEMS and t != "seq_no":
        return None
    allow = COMMON_KEYS | TYPE_KEYS[t]
    for k, v in spec.items():
        if k in ("type", "key") or k not in allow:
            continue
        if v is None:
            continue
        if k == "columns" and t == "subtable":
            cols = [clean_control(c, in_subtable=True) for c in (v or [])]
            out["columns"] = [c for c in cols if c]
        elif k == "filter" and isinstance(v, list):
            out["filter"] = [f for f in v if isinstance(f, dict) and f.get("field")]
        else:
            out[k] = v
    return out


def clean_sheet(sheet):
    """清洗一张表单定义;返回 None 表示非法(含 key 非法/为空)。

    **key 即 sheets/<key>.json 的文件名**,必须字母开头、纯字母数字(同样防路径穿越)。
    """
    if not isinstance(sheet, dict):
        return None
    key = str(sheet.get("key") or "").strip()
    if not _NAME_OK.match(key):
        return None
    controls = [clean_control(c) for c in (sheet.get("controls") or [])]
    controls = [c for c in controls if c]
    out = {"key": key,
           "title": sheet.get("title") or key,
           "nameSchema": sheet.get("nameSchema") or "",
           "useOwner": bool(sheet.get("useOwner")),
           "layout": sheet.get("layout") or "auto4",
           "group": sheet.get("group") or ""}
    out["controls"] = controls
    out["_kmap"] = normalize_sheet_keys(out)
    return out


def clean_automation(spec):
    """清洗一条自动化定义;返回 None 表示非法。见 docs/schema_doc.md「自动化」。"""
    if not isinstance(spec, dict):
        return None
    key = str(spec.get("key") or "").strip()
    if not _NAME_OK.match(key):
        return None
    form = str(spec.get("form") or "").strip()
    if not form:
        return None
    trigger = spec.get("trigger") or "生效或更新"
    if trigger not in AUTO_TRIGGERS:
        trigger = "生效或更新"
    out = {"key": key, "form": form, "trigger": trigger,
           "title": spec.get("title") or key}
    if isinstance(spec.get("sortKey"), int):
        out["sortKey"] = spec["sortKey"]
    if isinstance(spec.get("names"), dict) and spec["names"]:
        out["names"] = spec["names"]
    when = [w for w in (spec.get("when") or [])
            if isinstance(w, dict) and w.get("field")]
    if when:
        out["when"] = when
    actions = []
    for a in spec.get("actions") or []:
        if not isinstance(a, dict):
            continue
        do = a.get("do") or "新增"
        if do not in AUTO_DOS or not a.get("target"):
            continue
        act = {"do": do, "target": str(a["target"])}
        if a.get("state") in ("生效", "发起流程"):
            act["state"] = a["state"]
        if isinstance(a.get("isInsert"), bool):
            act["isInsert"] = a["isInsert"]
        if isinstance(a.get("owner"), bool):
            act["owner"] = a["owner"]
        match = [m for m in (a.get("match") or [])
                 if isinstance(m, dict) and m.get("field")]
        if match:
            act["match"] = match
        set_ = [s for s in (a.get("set") or [])
                if isinstance(s, dict) and s.get("to")]
        if set_:
            act["set"] = set_
        sub = a.get("sub")
        if isinstance(sub, dict) and sub.get("table"):
            sset = [s for s in (sub.get("set") or [])
                    if isinstance(s, dict) and s.get("to")]
            act["sub"] = {"table": str(sub["table"]), "set": sset}
        actions.append(act)
    if not actions:
        return None
    out["actions"] = actions
    return out


# ---------------------------------------------------------------- key 规范化
_KEY_OK = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
_REF = re.compile(r"\{([A-Za-z0-9_]+)\}")


def _camel(k):
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", k or "") if p]
    if not parts:
        return None
    out = parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
    if not out or not out[0].isalpha():
        out = "f" + out
    return out


def _norm_key(k, used):
    if k and _KEY_OK.match(k):
        used.add(k)
        return k
    base = _camel(k) or "field"
    cand, i = base, 2
    while cand in used:
        cand = base + str(i)
        i += 1
    used.add(cand)
    return cand


def normalize_sheet_keys(sheet):
    """把不合规**字段** key 规范化成驼峰(字母开头、无下划线),并同步重写全部引用。

    历史项目线上已建的表,key 里可能有下划线(如 plan_begin/is_paid,规则对已建表放过)。
    **作为新项目模板复用时必须规范化**,否则 `check`/`build` 会拒绝。

    - 布局项(group_title/description)**不规范化**:其 key 只是引用名,可随便起,
      且 layout 行靠它引用;若强行改名,layout 会悬空。
    - 流水号(seq_no)编码恒为 `SeqNo`,key 不参与字段命名约束。
    - 引用同步:`layout` 行、`nameSchema` 占位、`hideWhen`、`rule`、`filter.ref`。
    返回 `kmap`(旧字段码 → 新字段码,用于自动化引用重映射;无改动则空 dict)。
    """
    controls = sheet.get("controls") or []
    used, kmap = set(), {}

    def take(k):
        nk = _norm_key(k, used)
        if nk != k:
            kmap[k] = nk
        return nk

    for c in controls:
        t = c.get("type")
        if c.get("key") and t not in LAYOUT_ITEM_TYPES:
            c["key"] = take(c["key"])
        if t == "subtable":
            for col in c.get("columns") or []:
                if col.get("key"):
                    col["key"] = take(col["key"])
    if not kmap:
        return kmap

    def rw(s):
        if not isinstance(s, str):
            return s
        return _REF.sub(lambda m: "{%s}" % kmap.get(m.group(1), m.group(1)), s)

    sheet["nameSchema"] = rw(sheet.get("nameSchema") or "")
    if isinstance(sheet.get("layout"), list):
        sheet["layout"] = [[kmap.get(x, x) for x in row] if isinstance(row, list)
                           else kmap.get(row, row) for row in sheet["layout"]]
    for c in controls:
        if c.get("hideWhen"):
            c["hideWhen"] = rw(c["hideWhen"])
        if c.get("rule"):
            c["rule"] = rw(c["rule"])
        for it in c.get("filter") or []:
            if isinstance(it, dict) and it.get("ref"):
                it["ref"] = kmap.get(it["ref"], it["ref"])
        for col in c.get("columns") or []:
            if col.get("hideWhen"):
                col["hideWhen"] = rw(col["hideWhen"])
    return kmap


def _remap_automation(auto, alias):
    """把自动化里引用的**旧字段码**按 alias 重映射(尽力;跨表同名冲突不处理)。
    引用位置:when.field、match[].field/ref、set[].from、sub.set[].from、
    set[].to/sub.set[].to(目标字段)、字段串 `子表.列` 的两段。"""
    if not alias:
        return auto

    def one(v):
        if not isinstance(v, str) or not v or v.startswith("$"):
            return v
        if "." in v:
            return ".".join(alias.get(p, p) for p in v.split("."))
        return alias.get(v, v)

    for w in auto.get("when") or []:
        if w.get("field"):
            w["field"] = one(w["field"])
    for a in auto.get("actions") or []:
        for m in a.get("match") or []:
            for k in ("field", "ref"):
                if m.get(k):
                    m[k] = one(m[k])
        for s in a.get("set") or []:
            for k in ("to", "from"):
                if s.get(k):
                    s[k] = one(s[k])
        sub = a.get("sub")
        if isinstance(sub, dict):
            for s in sub.get("set") or []:
                for k in ("to", "from"):
                    if s.get(k):
                        s[k] = one(s[k])
    return auto


def clean_design(design):
    """清洗整个设计:去重表 key、过滤空表、规范 dicts/groups/automations。

    `automations`(触发器)遵循 docs/schema_doc.md 的 DSL;其中字段引用会按
    字段 key 规范化结果做**尽力重映射**(同一别名在多个表单出现时不做区分)。
    """
    if not isinstance(design, dict):
        raise E.EngineError("设计数据必须是对象")
    seen, sheets, alias = set(), [], {}
    for s in design.get("sheets") or []:
        cs = clean_sheet(s)
        if not cs or cs["key"] in seen:
            continue
        seen.add(cs["key"])
        alias.update(cs.pop("_kmap", {}) or {})
        sheets.append(cs)
    dicts = {}
    for cat, vals in (design.get("dicts") or {}).items():
        if not cat or not isinstance(vals, list):
            continue
        dicts[str(cat)] = [v for v in vals if isinstance(v, (str, dict))]
    groups = [g if isinstance(g, str) else (g or {}).get("name")
              for g in (design.get("groups") or [])]
    groups = [g for g in groups if g]
    seen_a, automations = set(), []
    for a in design.get("automations") or []:
        ca = clean_automation(a)
        if not ca or ca["key"] in seen_a:
            continue
        seen_a.add(ca["key"])
        automations.append(_remap_automation(ca, alias))
    return {"sheets": sheets, "dicts": dicts, "groups": groups,
            "automations": automations}


# ---------------------------------------------------------------- 落盘 / 回读
def _under(parent, path):
    """确认 path 位于 parent 目录内(防路径穿越)。"""
    rp, pp = os.path.realpath(path), os.path.realpath(parent)
    return rp == pp or rp.startswith(pp + os.sep)


def write_design(name, design, app_code=""):
    """把设计写入 projects/<name>/。返回 {written, automations, check, error}。
    落盘后立即跑离线 check;校验失败也会写盘(便于前端改后重存),由调用方决定是否回滚。
    """
    pdir = E.project_dir(name)
    d = clean_design(design)
    if not d["sheets"]:
        raise E.EngineError("设计里没有任何表单(sheets 为空)")
    sj = os.path.join(pdir, "sheets")
    os.makedirs(sj, exist_ok=True)
    # 清理旧的 sheets(避免残留已删除的表)
    for fn in os.listdir(sj):
        if fn.endswith(".json"):
            os.remove(os.path.join(sj, fn))
    written = []
    for s in d["sheets"]:
        target = os.path.join(sj, s["key"] + ".json")
        if not _under(sj, target):      # 双保险:key 已校验,仍做路径围栏
            raise E.EngineError("非法表单 key: %r" % s["key"])
        E.write_json(target,
                     {k: s[k] for k in ("title", "nameSchema", "useOwner",
                                        "layout", "group", "controls")
                      if s.get(k) not in ("", None) or k in ("title", "controls")})
        written.append(s["key"])
    if d["dicts"]:
        E.write_json(os.path.join(pdir, "dicts.json"), d["dicts"])
    if d["groups"]:
        E.write_json(os.path.join(pdir, "groups.json"),
                     [{"name": g} for g in d["groups"]])
    # 自动化:一条一文件,文件名 = key
    aj = os.path.join(pdir, "automations")
    os.makedirs(aj, exist_ok=True)
    for fn in os.listdir(aj):
        if fn.endswith(".json"):
            os.remove(os.path.join(aj, fn))
    written_a = []
    for a in d["automations"]:
        target = os.path.join(aj, a["key"] + ".json")
        if not _under(aj, target):
            raise E.EngineError("非法自动化 key: %r" % a["key"])
        E.write_json(target, a)
        written_a.append(a["key"])
    result = {"written": written, "automations": written_a,
              "design": d, "check": None, "error": ""}
    try:
        result["check"] = E.run_check(name, app_code=app_code)
    except Exception as e:
        result["error"] = str(e)
    return result


def read_design(name):
    """回读项目定义(原始 JSON,不经 dsl),供前端展示/编辑。"""
    pdir = E.project_dir(name)
    sj = os.path.join(pdir, "sheets")
    sheets = []
    if os.path.isdir(sj):
        for key in sorted(os.path.splitext(f)[0] for f in os.listdir(sj)
                          if f.endswith(".json")):
            try:
                raw = E.read_json(os.path.join(sj, key + ".json"))
            except Exception:
                continue
            sheets.append({
                "key": key, "title": raw.get("title") or key,
                "nameSchema": raw.get("nameSchema") or "",
                "useOwner": bool(raw.get("useOwner")),
                "layout": raw.get("layout") or "auto4",
                "group": raw.get("group") or "",
                "controls": raw.get("controls") or [],
            })
    dicts, groups, automations = {}, [], []
    for fn, tgt in (("dicts.json", "dicts"), ("groups.json", "groups")):
        p = os.path.join(pdir, fn)
        if os.path.isfile(p):
            try:
                val = E.read_json(p)
                if tgt == "dicts":
                    dicts = val
                else:
                    groups = [g if isinstance(g, str) else (g or {}).get("name")
                              for g in (val or [])]
            except Exception:
                pass
    aj = os.path.join(pdir, "automations")
    if os.path.isdir(aj):
        for fn in sorted(os.listdir(aj)):
            if fn.endswith(".json"):
                try:
                    automations.append(E.read_json(os.path.join(aj, fn)))
                except Exception:
                    pass
    return {"project": name, "sheets": sheets, "dicts": dicts,
            "groups": [g for g in groups if g], "automations": automations}


# ---------------------------------------------------------------- 方案(表级)
def read_proposal(name):
    p = os.path.join(E.project_dir(name), "PROPOSAL.json")
    return E.read_json(p) if os.path.isfile(p) else None


def write_proposal(name, proposal):
    E.write_json(os.path.join(E.project_dir(name), "PROPOSAL.json"), proposal)
    return proposal


def read_requirement(name):
    p = os.path.join(E.project_dir(name), "requirement.md")
    return open(p, encoding="utf-8").read() if os.path.isfile(p) else ""


def write_requirement(name, text):
    E.write_json(os.path.join(E.project_dir(name), "requirement.json"),
                 {"text": text})
    with open(os.path.join(E.project_dir(name), "requirement.md"),
              "w", encoding="utf-8") as f:
        f.write(text or "")
    return {"chars": len(text or "")}
