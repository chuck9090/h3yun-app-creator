# -*- coding: utf-8 -*-
"""引擎执行层:项目定义 → 氚云载荷 / 建表 / 只读核对 / ER 图。

设计原则
--------
- **无副作用输出**:不 print、不 sys.exit;失败抛 `EngineError`,调用方决定怎么呈现。
- **复用而非重复**:底层复用 h3design/h3platform/h3verify。
- **离线可用**:check / er_graph / preview_payload 不联网,便于 Web 端预览与测试。
"""
import json
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# 运行数据目录(代码与数据分离):仓库内只保留代码;DB/上传件/项目工作区/
# 知识库产物/凭据都放这里。默认 <root>/data,可用 H3AC_DATA_DIR 覆盖。
DATA_DIR = os.environ.get("H3AC_DATA_DIR") or os.path.join(ROOT, "data")
PROJECTS = os.path.join(DATA_DIR, "projects")
KNOWLEDGE = os.path.join(DATA_DIR, "knowledge")
CONFIG = os.path.join(DATA_DIR, "config.json")

import h3design.dsl as DSL          # noqa: E402
import h3verify.verify as V         # noqa: E402


class EngineError(Exception):
    """引擎层可预期的失败(定义错误/缺凭据/平台拒绝)。"""


# ---------------------------------------------------------------- 路径与配置
def project_dir(name, must=True):
    p = os.path.join(PROJECTS, name)
    if must and not os.path.isdir(p):
        raise EngineError("项目 %r 不存在（%s）" % (name, p))
    return p


def list_projects():
    if not os.path.isdir(PROJECTS):
        return []
    import re
    skip = re.compile(r"(^_)|(e2e)|(smoke)|(^web_tmp)", re.I)
    return sorted(d for d in os.listdir(PROJECTS)
                  if os.path.isdir(os.path.join(PROJECTS, d))
                  and not skip.search(d))


def create_project(name, app_code=""):
    """建目录 + 可选写项目级 config.json(含 appCode)。已存在则报错。"""
    p = project_dir(name, must=False)
    if os.path.isdir(p):
        raise EngineError("项目 %r 已存在" % name)
    os.makedirs(os.path.join(p, "sheets"), exist_ok=True)
    if app_code:
        write_json(os.path.join(p, "config.json"), {
            "appCode": app_code,
            "_note": "仅 appCode;凭据沿用运行目录 data/config.json 或由 Web 端凭据库注入",
        })
    return p


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    """原子写:先写同目录临时文件再 os.replace,避免中途崩溃/并发把文件写坏
    (registry.json 损坏会导致批量孤儿表,见 docs/platform_gotchas.md)。"""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_registry(name):
    """读 registry;文件损坏时**不静默当空**——抛错让人介入,避免批量重新发码。"""
    p = os.path.join(project_dir(name), "registry.json")
    if not os.path.isfile(p):
        return {}
    try:
        return read_json(p)
    except Exception as e:
        raise EngineError("registry.json 损坏,拒绝继续(避免批量换码): %s" % e)


def save_registry(name, reg):
    write_json(os.path.join(project_dir(name), "registry.json"), reg)


def resolve_config(name, cfg=None, allow_root=True):
    """凭据优先级:显式传入(Web 凭据库) > 项目 config.json > 运行目录 config.json。

    **Web 端必须传 allow_root=False**:运行目录 config.json 指向的应用会变,
    回落会把表误建到别的应用(见 docs/platform_gotchas.md「静默回落到根 config」)。
    """
    if cfg:
        return cfg
    cands = [os.path.join(project_dir(name, must=False), "config.json")]
    if allow_root:
        cands.append(CONFIG)
    for cand in cands:
        if cand and os.path.isfile(cand):
            try:
                c = read_json(cand)
                if c:
                    return c
            except Exception:
                pass
    return {"appCode": ""}


def _require_online(cfg):
    for k in ("baseUrl", "authorization", "engineCode", "appCode"):
        if not cfg.get(k):
            raise EngineError("缺凭据 %s —— 发布/核对需项目 config.json 或运行目录 data/config.json 完整配置" % k)


# ---------------------------------------------------------------- 编码生成
def new_sheet_code(app_code):
    return app_code[:7] + "".join(random.choice("0123456789abcdef") for _ in range(32))


def new_child_code(app_code):
    """子表 child schema 编码:appCode前7位 + F + 32位hex(40位)。"""
    return app_code[:7] + "F" + "".join(random.choice("0123456789abcdef") for _ in range(32))


# ---------------------------------------------------------------- 装载与校验
def check_registry(name):
    """check/preview 用 registry:给已声明但未建表的表单补占位编码,
    让 assoc/query 与汇总控件在**建表前**也能解析。"""
    reg = dict(load_registry(name) or {})
    sj = os.path.join(project_dir(name), "sheets")
    if os.path.isdir(sj):
        for fn in os.listdir(sj):
            if not fn.endswith(".json"):
                continue
            k = os.path.splitext(fn)[0]
            e = dict(reg.get(k) or {})
            if not e.get("code"):
                e["code"] = "0" * 39
            subs = dict(e.get("subs") or {})
            for spec in DSL.sheet_sub_specs(os.path.join(sj, fn)):
                s = dict(subs.get(spec["key"]) or {})
                if not s.get("code"):
                    s["code"] = "0" * 7 + "F" + "0" * 32
                subs[spec["key"]] = s
            if subs:
                e["subs"] = subs
            reg[k] = e
    return reg


def load_sheets(name, app_code="", registry=None):
    return DSL.load_project(project_dir(name), app_code,
                            registry if registry is not None else load_registry(name))


def _resolve_targets(name, sheets, targets):
    keys = list(targets) if targets else sorted(sheets)
    bad = [k for k in keys if k not in sheets]
    if bad:
        raise EngineError("表单 %s 不在项目 %r（现有 %s）"
                          % (bad, name, sorted(sheets)))
    return keys


def run_check(name, targets=None, app_code=None):
    """离线校验。返回结构化结果;定义有误抛 EngineError。

    `app_code`:Web 端应显式传入项目自身 appCode(避免回落到运行目录 config 的应用);
    为 None 时按默认行为解析(项目/运行目录 config)。
    """
    cfg = {"appCode": app_code} if app_code is not None else resolve_config(name)
    reg = check_registry(name)
    try:
        sheets = DSL.load_project(project_dir(name), cfg.get("appCode", ""), reg)
    except Exception as e:
        raise EngineError("表单定义装载失败: %s" % e)
    out = {"project": name, "sheets": [], "automations": [], "warnings": []}
    for key in _resolve_targets(name, sheets, targets):
        d = sheets[key]()
        n_rules = sum(1 for c in d["fields"]
                      if (c.get("Options") or {}).get("DisplayRule", {}).get("Rule"))
        n_rows = sum(1 for g in d.get("layout", []) if isinstance(g, list))
        subs = d.get("subs") or []
        item = {
            "key": key, "title": d["title"], "fields": len(d["fields"]),
            "rules": n_rules, "rows": n_rows,
            "assoc": list(d["assoc"] or []),
            "subtables": [{"key": s["key"], "columns": len(s["cols"])} for s in subs],
            "extras": len(d.get("extras") or []),
            "group": d.get("group") or "",
        }
        lk = d.get("legacy_keys") or []
        if lk:
            item["legacyKeys"] = list(lk)
            out["warnings"].append("%s: 线上已建,命名不合规的放过: %s" % (key, ", ".join(lk)))
        out["sheets"].append(item)
    # 自动化(automations/*.json)离线装载校验
    adir = os.path.join(project_dir(name), "automations")
    if os.path.isdir(adir):
        from h3design import autodsl as AD
        try:
            autos = AD.load_automations(project_dir(name), cfg.get("appCode", ""), reg)
        except Exception as e:
            raise EngineError("自动化定义有误: %s" % e)
        for it in autos:
            out["automations"].append({
                "key": it["key"], "title": it["title"], "trigger": it["trigger"],
                "actions": len(it["payload"]["Action"]),
                "form": it["form_key"] or it["form_code"],
            })
    return out


# ---------------------------------------------------------------- ER 图
def er_graph(name, targets=None, app_code=None):
    """从 sheets/*.json 生成 ER 图数据(节点=表,边=query/联动下拉的 assoc 关系)。
    离线、不联网;字段作为节点属性供前端展开。
    关系解析:优先读原始定义里的 `assoc`(本地表 key);legacy(forms.py)则用
    dsl 记录的 `assoc_schema_code` 反查 registry 得到表 key。"""
    cfg = {"appCode": app_code} if app_code is not None else resolve_config(name)
    reg = check_registry(name)
    try:
        sheets = DSL.load_project(project_dir(name), cfg.get("appCode", ""), reg)
    except Exception as e:
        raise EngineError("表单定义装载失败: %s" % e)
    keys = _resolve_targets(name, sheets, targets)
    code2key = {v.get("code"): k for k, v in (load_registry(name) or {}).items()
                if isinstance(v, dict) and v.get("code")}
    nodes, edges = [], []
    for key in keys:
        d = sheets[key]()
        # 原始 JSON spec:含本地 assoc 表 key(仅 JSON 项目有;legacy 用编码反查)
        raw_specs = {}
        p = os.path.join(project_dir(name), "sheets", key + ".json")
        if os.path.isfile(p):
            try:
                raw = read_json(p)
                raw_specs = {c.get("key"): c for c in (raw.get("controls") or [])
                             if isinstance(c, dict)}
            except Exception:
                pass
        fields = []
        for c in d["fields"]:
            opts = c.get("Options") or {}
            subs = c.get("ChildControls") or []
            fk = c.get("Key", "")
            spec = raw_specs.get(fk) or {}
            fields.append({
                "key": fk,
                "label": opts.get("DisplayName", ""),
                "type": spec.get("type") or c.get("Type"),
                "required": bool(spec.get("required")),
                "readonly": bool(spec.get("readonly")),
                "assoc": spec.get("assoc") or "",
                "isSubtable": bool(subs),
                "columns": [{"key": x.get("Key"),
                             "label": (x.get("Options") or {}).get("DisplayName", "")}
                            for x in subs],
            })
            if spec.get("assoc"):
                target_key, kind = spec["assoc"], "关联"
            else:
                code = (d.get("assoc") or {}).get(fk, {}).get("assoc_schema_code")
                target_key, kind = code2key.get(code, code), "关联"
            if target_key:
                if spec.get("type") == "dropdown":
                    kind = "联动"
                edges.append({"source": key, "target": target_key, "field": fk,
                              "label": opts.get("DisplayName") or fk, "kind": kind})
        nodes.append({"id": key, "title": d["title"], "group": d.get("group") or "",
                      "useOwner": bool(d.get("useOwner")), "fields": fields})
    return {"project": name, "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------- 载荷预览(离线)
def preview_payload(name, sheet_key, cfg=None):
    """生成 SaveForm 三段载荷但**不发送**(Web 端"发布前预览"用)。"""
    from h3design import newbuilder as NB
    c = resolve_config(name, cfg, allow_root=False)
    # 用 check_registry(带占位编码):建表前预览也能解析 assoc/子表,不必先 build
    reg = dict(check_registry(name))
    # 预注册子表编码,保证载荷里子表码有值(正式 build 同样处理)
    p = os.path.join(project_dir(name), "sheets", sheet_key + ".json")
    if os.path.isfile(p):
        sreg = reg.setdefault(sheet_key, {}).setdefault("subs", {})
        for spec in DSL.sheet_sub_specs(p):
            sreg.setdefault(spec["key"], {}).setdefault("code", new_child_code(c.get("appCode", "")))
    sheets = DSL.load_project(project_dir(name), c.get("appCode", ""), reg)
    if sheet_key not in sheets:
        raise EngineError("表单 %r 不在项目 %r" % (sheet_key, name))
    form = sheets[sheet_key]()
    code = (reg.get(sheet_key) or {}).get("code") or new_sheet_code(c.get("appCode", ""))
    subs = form.get("subs") or []
    schema = NB.build_schema_str(form["fields"], form["name_schema"],
                                 assoc=form["assoc"], app_package=c.get("appCode", ""),
                                 subs=subs)
    biz = NB.build_biz_sheet(code, form["fields"],
                             layout=form.get("layout"), subs=subs)
    settings = NB.build_control_settings(form["fields"])
    return {
        "project": name, "sheet": sheet_key, "title": form["title"],
        "payload": {"SchemaStr": schema, "BizSheetStr": biz,
                    "ControlSettingsStr": settings},
    }


# ---------------------------------------------------------------- 建表(联网)
def _expect_field_count(form):
    n = (len(form["fields"]) + len(form.get("extras") or [])
         + sum(1 + len(s["cols"]) for s in (form.get("subs") or [])))
    return n + (2 if form.get("useOwner") else 0)


def _live_design_count(con, code):
    """线上表设计树的字段数。表**确实不存在** → None;
    读失败(网络/认证/HTTP 异常) → 抛 EngineError(**中止**,绝不当作不存在去换码建表)。
    判据:平台查不到表时错误串含 "isnull"(见 docs/platform_gotchas.md)。"""
    try:
        rd = con.load_form(code)
    except Exception as e:
        raise EngineError("LoadForm 失败(网络/认证),已中止以免误建/换码: %s" % e)
    if rd and rd.get("Successful") is True:
        return len(V.collect_live(rd.get("ReturnData"))[0])
    blob = json.dumps(rd, ensure_ascii=False) if rd else ""
    if "isnull" in blob.lower():
        return None
    raise EngineError("LoadForm 返回异常,已中止: %s" % blob[:200])


def build_sheet(name, sheet_key, cfg=None, force=False):
    """建/核对一张表。返回 {key, created, code, detail, err}。

    - 线上已存在且结构一致 → 跳过(created=True);
    - 线上已存在但字段数不符 → **created=False**(不再假成功),需 --force 重存或人工核对;
    - 注册表有码但线上探测不到 → **沿用原码**重建(绝不自动换码,避免断关联/孤儿表);
    - 从未发过码 → 才新发编码。
    """
    from h3platform.h3console import H3Console, save_form_console
    from h3design import newbuilder as NB
    c = resolve_config(name, cfg)
    _require_online(c)
    reg = dict(load_registry(name))
    con = H3Console(c)
    app = c["appCode"]
    rec = reg.get(sheet_key) or {}
    code = rec.get("code")
    live_n = _live_design_count(con, code) if code else None
    if code and live_n is not None and not force:
        form = load_sheets(name, app, reg)[sheet_key]()
        n_expect = _expect_field_count(form)
        if live_n == n_expect:
            reg[sheet_key] = {"code": code, "created": True, "title": form["title"],
                              "detail": "线上已存在，字段结构一致", "err": "",
                              "subs": rec.get("subs", {})}
            save_registry(name, reg)
            return {"key": sheet_key, "skipped": True, "created": True,
                    "code": code, "detail": "线上已存在且结构一致", "err": ""}
        return {"key": sheet_key, "skipped": True, "created": False, "code": code,
                "detail": "线上已存在但字段数不符,已跳过(需 force 重存或人工核对)",
                "err": "字段数不符 %d != %d" % (live_n, n_expect)}
    # 注意:code 有值但 live_n 为 None(表确实不存在)时**沿用原码**,不换码。
    if not code:
        code = new_sheet_code(app)
    reg.setdefault(sheet_key, {})["code"] = code
    p = os.path.join(project_dir(name), "sheets", sheet_key + ".json")
    if os.path.isfile(p):
        sreg = reg.setdefault(sheet_key, {}).setdefault("subs", {})
        for spec in DSL.sheet_sub_specs(p):
            ent = sreg.setdefault(spec["key"], {})
            if force or not ent.get("code"):
                ent["code"] = new_child_code(app)
    sheets = DSL.load_project(project_dir(name), app, reg)
    form = sheets[sheet_key]()
    subs = form.get("subs") or []
    schema = NB.build_schema_str(form["fields"], form["name_schema"],
                                 assoc=form["assoc"], app_package=app, subs=subs)
    biz = NB.build_biz_sheet(code, form["fields"], layout=form.get("layout"), subs=subs)
    settings = NB.build_control_settings(form["fields"])
    err, ok = "", False
    try:
        resp = save_form_console(con, code, c["engineCode"], app, app,
                                 form["title"], schema, biz, pc_layout=1,
                                 mobile_layout=1, control_settings_str=settings)
        ok = bool(resp and resp.get("Successful") is True)
        if not ok and resp:
            err = json.dumps(resp, ensure_ascii=False)[:500]
    except Exception as e:
        err = str(e)[:500]
    n_expect = _expect_field_count(form)
    detail = ""
    if ok:
        time.sleep(0.5)
        rd = con.load_form(code).get("ReturnData")
        live = V.collect_live(rd)
        detail = ("fields=%d nameSchema=%s" % (n_expect, rd.get("NameSchema")))
        if len(live[0]) != n_expect:
            ok, err = False, "字段数不符 %d != %d（可能子表编码被 UI 改动）" \
                % (len(live[0]), n_expect)
    reg[sheet_key] = {"code": code, "created": ok, "title": form["title"],
                      "detail": detail, "err": err[:500],
                      "subs": (reg.get(sheet_key) or {}).get("subs", {})}
    save_registry(name, reg)
    return {"key": sheet_key, "skipped": False, "created": ok, "code": code,
            "detail": detail, "err": err}


def build_order(name, keys):
    """按 assoc 依赖做拓扑排序:**被引用表先建**。
    循环依赖/legacy(无 JSON)按原顺序兜底,不会死循环。"""
    reg = load_registry(name)
    code2key = {v.get("code"): k for k, v in reg.items()
                if isinstance(v, dict) and v.get("code")}
    sj = os.path.join(project_dir(name), "sheets")
    deps = {}
    for key in keys:
        refs = set()
        p = os.path.join(sj, key + ".json")
        if os.path.isfile(p):
            try:
                raw = read_json(p)
                for c in raw.get("controls") or []:
                    a = (c or {}).get("assoc")
                    if a:
                        refs.add(a)
            except Exception:
                pass
        deps[key] = {r for r in refs if r in keys}
    order, temp, done = [], set(), set()

    def visit(k):
        if k in done or k in temp:
            return
        temp.add(k)
        for d in sorted(deps.get(k) or ()):
            if d != k:
                visit(d)
        temp.discard(k)
        done.add(k)
        order.append(k)

    for k in keys:
        visit(k)
    return order


def run_build(name, targets=None, cfg=None, force=False, allow_root=True):
    """批量建表:先检查定义 → 按依赖拓扑排序(被引用表先建) → 逐张建/跳过。"""
    cfg = resolve_config(name, cfg, allow_root=allow_root)
    reg = load_registry(name)
    sheets = DSL.load_project(project_dir(name), cfg.get("appCode", ""), reg)
    keys = _resolve_targets(name, sheets, targets)
    keys = build_order(name, keys)
    results = []
    for key in keys:
        try:
            results.append(build_sheet(name, key, cfg=cfg, force=force))
        except EngineError as e:
            results.append({"key": key, "created": False, "code": "",
                            "detail": "", "err": str(e)})
    return {"project": name, "sheets": results, "order": keys,
            "all_ok": all(r.get("created") for r in results)}


def run_verify(name, targets=None, cfg=None, allow_root=True):
    """只读回读比对。返回每表报告与汇总。"""
    from h3platform.h3console import H3Console
    c = resolve_config(name, cfg, allow_root=allow_root)
    _require_online(c)
    reg = load_registry(name)
    con = H3Console(c)
    sheets = DSL.load_project(project_dir(name), c.get("appCode", ""), reg)
    results, all_ok = [], True
    for key in _resolve_targets(name, sheets, targets):
        code = (reg.get(key) or {}).get("code")
        if not code:
            results.append({"key": key, "ok": False, "report": "未建表（registry 无编码）"})
            all_ok = False
            continue
        try:
            rd = con.load_form(code)
        except Exception as e:
            results.append({"key": key, "ok": False, "report": "LoadForm 异常: %s" % e})
            all_ok = False
            continue
        if not (rd and rd.get("Successful") is True):
            results.append({"key": key, "ok": False, "report": "LoadForm 失败: %s" % rd})
            all_ok = False
            continue
        r = V.compare(sheets[key](), rd["ReturnData"])
        results.append({"key": key, "ok": r["ok"],
                        "report": V.format_report("表", code, sheets[key](), rd["ReturnData"])})
        all_ok = all_ok and r["ok"]
    return {"project": name, "sheets": results, "all_ok": all_ok}


# ---------------------------------------------------------------- 自动化(联网)
def run_autobuild(name, cfg=None, targets=None, allow_root=True):
    """建/更新自动化(触发器)。ObjectId 为定值,重复运行=更新同一条。
    须在**表单全部建好后**执行(触发器引用表单编码)。"""
    from h3platform.h3console import H3Console
    from h3design import autodsl as AD, automation as AUT
    from h3verify import autoverify as AV
    c = resolve_config(name, cfg, allow_root=allow_root)
    _require_online(c)
    reg = load_registry(name)
    con = H3Console(c)
    live = {}

    def _live_ids(form_code):
        if form_code not in live:
            live[form_code] = {t.get("ObjectId")
                               for t in AV.triggers_of(con.load_triggers(form_code))}
        return live[form_code]

    items = AD.load_automations(
        project_dir(name), c["appCode"], reg,
        operation=lambda key, form_code: (
            "isUpdate" if AUT.trigger_object_id(name, key) in _live_ids(form_code)
            else "isAdd"))
    if targets:
        want = set(targets)
        items = [it for it in items if it["key"] in want]
    results = []
    for it in items:
        try:
            resp = con.save_trigger(it["payload"])
            ok = bool(resp and resp.get("Successful") is True)
            err = "" if ok else json.dumps(resp, ensure_ascii=False)[:400]
        except Exception as e:
            ok, err = False, str(e)[:400]
        results.append({"key": it["key"], "created": ok,
                        "objectId": it["payload"].get("ObjectId", ""),
                        "title": it["title"],
                        "form": it["form_key"] or it["form_code"], "err": err})
    return {"project": name, "automations": results,
            "all_ok": all(r["created"] for r in results) if results else True}


def run_autoverify(name, cfg=None, targets=None, allow_root=True):
    """只读回读比对自动化(LoadTriggers)。安全可重复。"""
    from h3platform.h3console import H3Console
    from h3design import autodsl as AD, automation as AUT
    from h3verify import autoverify as AV
    c = resolve_config(name, cfg, allow_root=allow_root)
    _require_online(c)
    reg = load_registry(name)
    con = H3Console(c)
    items = AD.load_automations(project_dir(name), c["appCode"], reg)
    if targets:
        want = set(targets)
        items = [it for it in items if it["key"] in want]
    cache, out, all_ok = {}, [], True
    for it in items:
        code = it["form_code"]
        if code not in cache:
            cache[code] = AV.triggers_of(con.load_triggers(code))
        trg = [t for t in cache[code]
               if t.get("ObjectId") == AUT.trigger_object_id(name, it["key"])]
        res = AV.compare(it["payload"], trg[0]) if trg else None
        ok = bool(res and res["ok"])
        all_ok = all_ok and ok
        out.append({"key": it["key"], "title": it["title"], "ok": ok,
                    "report": AV.format_report(it["key"], it["title"], code, res,
                                               len(cache[code]))})
    return {"project": name, "automations": out, "all_ok": all_ok}


# ---------------------------------------------------------------- 表单分组(联网)
def _group_plan(name, order_hint=None):
    """读 sheets/*.json 的 group 字段 → [(分组名, [表key...])],顺序 = order_hint 优先,
    否则按 groups.json 声明顺序,再否则按表单出现顺序;空分组名的表跳过。"""
    reg = load_registry(name)
    pdir = project_dir(name)
    sj = os.path.join(pdir, "sheets")
    pairs = []
    if os.path.isdir(sj):
        for fn in sorted(os.listdir(sj)):
            if not fn.endswith(".json"):
                continue
            key = os.path.splitext(fn)[0]
            try:
                raw = read_json(os.path.join(sj, fn))
            except Exception:
                continue
            g = (raw.get("group") or "").strip()
            if g:
                pairs.append((key, g))
    if order_hint is None:
        order_hint = []
        gp = os.path.join(pdir, "groups.json")
        if os.path.isfile(gp):
            try:
                for x in read_json(gp) or []:
                    name = x if isinstance(x, str) else (x or {}).get("name")
                    if name:
                        order_hint.append(name)
            except Exception:
                pass
    seen, order = set(), []
    for g in (order_hint or []):
        g = (g or "").strip()
        if g and g not in seen:
            seen.add(g)
            order.append(g)
    for _k, g in pairs:
        if g not in seen:
            seen.add(g)
            order.append(g)
    out = [(g, [k for k, gg in pairs if gg == g]) for g in order]
    return out, reg


def run_group(name, cfg=None, allow_root=True):
    """建/应用表单分组(应用菜单归类):按 sheets 的 group 建组并移入。

    - 幂等:分组码/objectId 存 registry `_groups`,已有组跳过不重建;
    - 每次运行把声明的表**移回**所属分组(界面拖走的会归位);
    - 平台无分组读/删接口,多余分组只能在界面删(见 docs/platform_gotchas.md)。
    """
    from h3platform import api as H3A
    c = resolve_config(name, cfg, allow_root=allow_root)
    _require_online(c)
    app = c["appCode"]
    h3 = H3A.H3(c)
    plan, reg = _group_plan(name)
    if not plan:
        return {"project": name, "groups": [], "moved": [], "all_ok": True,
                "detail": "没有声明分组"}
    greg = reg.setdefault("_groups", {})
    groups_out, order = [], []
    for g, _keys in plan:
        ent = greg.get(g) or {}
        if ent.get("code") and ent.get("objectId"):
            groups_out.append({"group": g, "code": ent["code"], "created": True,
                               "detail": "已存在,跳过"})
        else:
            try:
                code, oid = h3.create_group(app, g)
                time.sleep(0.3)
                h3.update_group(app, code, oid, g)   # create→update 两步落定(UI 同款)
                greg[g] = {"code": code, "objectId": oid}
                groups_out.append({"group": g, "code": code, "created": True, "detail": ""})
            except Exception as e:
                groups_out.append({"group": g, "code": "", "created": False,
                                   "detail": str(e)[:300]})
        time.sleep(0.2)
    save_registry(name, reg)
    moved, all_ok = [], all(bool(x["created"]) for x in groups_out)
    for g, keys in plan:
        gc = (greg.get(g) or {}).get("code")
        if not gc:
            all_ok = False
            continue
        for key in keys:
            sheet_code = (reg.get(key) or {}).get("code")
            if not sheet_code:
                moved.append({"table": key, "group": g, "ok": False,
                              "detail": "未建表(registry 无编码)"})
                all_ok = False
                continue
            try:
                h3.move_node(sheet_code, gc)
                moved.append({"table": key, "group": g, "ok": True, "detail": ""})
            except Exception as e:
                moved.append({"table": key, "group": g, "ok": False,
                              "detail": str(e)[:200]})
                all_ok = False
            time.sleep(0.2)
    return {"project": name, "groups": groups_out, "moved": moved, "all_ok": all_ok}


# ---------------------------------------------------------------- 知识库
def refresh_knowledge(project_names=None):
    """从 data/projects/ 重新编译知识库(语料全部来自用户自己的项目,无内置样本)。"""
    from h3design import memory as MEM
    corpus = MEM.build_corpus(PROJECTS, project_names or None)
    merged = MEM.write_corpus(corpus, KNOWLEDGE)
    if merged is None:
        cur, p = {}, os.path.join(KNOWLEDGE, "corpus.json")
        if os.path.isfile(p):
            try:
                cur = MEM.corpus_stats(read_json(p))
            except Exception:
                cur = {}
        out = {"preserved": True, "note": "无可编译内容,保留现有知识库"}
        out.update(cur)
        return out
    out = MEM.corpus_stats(merged)
    out["preserved"] = False
    out["local"] = len(corpus.get("projects") or [])
    return out
