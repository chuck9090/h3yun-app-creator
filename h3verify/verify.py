# -*- coding: utf-8 -*-
"""LoadForm 只读回读校验：把"期望"（loader 构建的控件结构）与线上表单比对。
不 SaveForm，可安全重复运行。核对项：
  - 字段数 / 缺字段 / 额外字段
  - 每字段 DisplayRule 隐藏条件文本（期望 vs 线上）
  - 一行多列（type 102）行节点数（layout 里 list 组的个数）
  - NameSchema
报告 dict 供调用方输出（stdout + data/projects/<项目>/logs/verify_report.txt UTF-8）。"""
import json
import time

MAX_SHOW = 10


def ci(d, name):
    """dict 大小写不敏感取值（LoadForm 用 PascalCase，SaveForm 用 camelCase）"""
    for k in d:
        if k.lower() == name.lower():
            return d[k]
    return None


def walk_items(node):
    """递归收集控件/行节点 dict（含一行多列行节点内 columns/childControls 子项）"""
    out = []
    if isinstance(node, dict):
        if ci(node, "Options") is not None or ci(node, "type") is not None \
                or ci(node, "Key") is not None:
            out.append(node)
        for v in node.values():
            out.extend(walk_items(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(walk_items(v))
    return out


def _parse_dmc(rd):
    dmc = rd.get("DesignModeContent")
    dmc = json.loads(dmc) if isinstance(dmc, str) else dmc
    return dmc


def collect_live(rd):
    """DesignModeContent → (by_code{key: Options}, rows[行节点], names)"""
    items = walk_items(_parse_dmc(rd))
    by_code, rows = {}, []
    for d in items:
        o = ci(d, "Options") or ci(d, "options") or {}
        ty = ci(d, "type")
        cols = ci(d, "columns") or ci(d, "childControls")
        # 子表(104)节点虽有 columns，但整行占表单底，不算一行多列(102)行组
        if ty == 102 or (cols is not None and ci(d, "Key") is None and ty != 104):
            rows.append(d)
            continue
        key = ci(o, "DataField") or ci(d, "Key")
        if key:
            by_code.setdefault(key, o)
    return by_code, rows


def expected_rules(form):
    """loader 产物 → {code: 期望 DisplayRule 文本}（空串=常显）。
    布局项（分组标题/描述）没有 DataField，回读设计树按 key 收集 —— 同样登记。
    子表：子表主编码（key=child schema code）与其每列 dotted code
    （code.列key）作为普通期望字段 —— LoadForm 设计树中 104 节点以
    options.DataField 收集，与主字段同路径比对。"""
    expect = {}
    for c in list(form["fields"]) + list(form.get("extras") or []):
        r = (c.get("Options") or {}).get("DisplayRule")
        expect[c["Key"]] = r.get("Rule") if isinstance(r, dict) else ""
    for s in form.get("subs") or []:
        code = s.get("code")
        if not code:
            continue      # 未建表（registry 无 subs 编码）时只比主字段
        expect.setdefault(code, "")
        for col in s["cols"]:
            expect.setdefault("%s.%s" % (code, col["Key"]), "")
    return expect


def expected_layout_rows(form):
    """layout 里一行多列（list）组数；单控件整行不计行组"""
    return sum(1 for g in form.get("layout", []) if isinstance(g, list))


def _ctrl_opt(ctl):
    """控件 dict（{Key, Options{...}}）或裸 Options → Options 字典。
    期望侧是前者，live_by_code 收集的是后者。"""
    if isinstance(ctl, dict) and "Options" not in ctl:
        return ctl
    return (ctl or {}).get("Options") or {}


def _rule_field(ctl, name):
    """Options 里某个规则键的规则文本（FormLayout/回读侧是 {Rule: ..} 字典，
    宽容处理裸字符串与 RuleText）。name: AssociationFilter / ComputationRule。"""
    o = _ctrl_opt(ctl)
    if not isinstance(o, dict):
        return ""
    af = o.get(name)
    if isinstance(af, dict):
        for k in ("Rule", "RuleText"):
            if k in af:
                return af[k] or ""
        return ""
    return af or ""


def _af_rule(ctl):
    """控件/裸 Options 的 AssociationFilter 规则文本（联动下拉）"""
    return _rule_field(ctl, "AssociationFilter")


def _rollup_key(ctl):
    """汇总配置的规整串：条件里的 Id 是**客户端随机 GUID**（UI 每次重存会换），
    比对时丢掉；键序也归一（PropertyMapping 线上自己就有两种键序）。"""
    def drop(o):
        if isinstance(o, dict):
            return {k: drop(v) for k, v in o.items() if k != "Id"}
        if isinstance(o, list):
            return [drop(v) for v in o]
        return o
    rs = _ctrl_opt(ctl).get("RollupSettings")
    return json.dumps(drop(rs), ensure_ascii=False, sort_keys=True)


def _rollup_map(rd):
    """线上服务端补全的 RollupSettingsMap {字段编码: [ {Success, RollupType, ...} ]}
    —— RollupType/SourceSchemaCode/PropertyMapping 会被服务端补成完整形态（多
    TargetSchemaCode/SourceMainSchemaCode 等），所以**只拿 Success 当校验位**。"""
    m = rd.get("RollupSettingsMap")
    return m if isinstance(m, dict) else {}


def _norm_rule(s):
    """规则文本规整比对：去 NBSP/空白漂移。UI 重存会在规则串头尾、AND 两侧、
    函数逗号后插 NBSP、给 ==/!= 加空格（2026-09-09 实证）——语义比对前规整。"""
    return "".join(str(s or "").replace(" ", " ").split())


def _settings_of(controls):
    """期望侧：位置控件的 ControlSettings（控件 dict 上的独立键）→ {key: {k: 文本}}"""
    out = {}
    for c in controls:
        cs = c.get("ControlSettings")
        if cs:
            out[c["Key"]] = {str(k): str(v) for k, v in cs.items()}
    return out


def _live_settings(rd):
    """线上侧：LoadForm ReturnData.ControlSettings（**首字母大写**：Key/DataField/
    Options；SaveForm 收的是小写 key/dataField/options）→ {key: {k: 文本}}"""
    out = {}
    for e in (rd.get("ControlSettings") or []):
        if not isinstance(e, dict):
            continue
        k = ci(e, "Key") or ci(e, "DataField")
        o = ci(e, "Options") or {}
        if k:
            out[k] = {str(kk): str(vv) for kk, vv in o.items()}
    return out


def compare(form, rd):
    """form = loader 产物；rd = LoadForm ReturnData → 核对结果 dict"""
    expect = expected_rules(form)
    live_by_code, rows = collect_live(rd)
    miss, extra, bad, badf = [], [], [], []
    for code in expect:
        if code not in live_by_code:
            miss.append(code)
            continue
        o = live_by_code[code]
        r = o.get("DisplayRule") or {}
        got = r.get("Rule") if isinstance(r, dict) else ""
        if (expect[code] or "") != (got or ""):
            bad.append((code, expect[code], got))
    # 联动下拉 AssociationFilter：期望带规则的才比；规则有 NBSP/空白漂移，
    # 规整（去全部空白）后语义比对；线上重存后整条丢失也视为不符
    for c in form["fields"]:
        exp = _norm_rule(_af_rule(c))
        if not exp:
            continue
        got = _norm_rule(_af_rule(live_by_code.get(c["Key"])))
        if exp != got:
            badf.append((c["Key"], exp, got))
    # 公式控件 ComputationRule（公式正文）：期望带公式的才比；同 _norm_rule 规整
    # 空白（UI 重存可能插 NBSP/空格）后语义比对；线上整条丢公式也视为不符
    badfx = []
    for c in form["fields"]:
        exp = _norm_rule(_rule_field(c, "ComputationRule"))
        if not exp:
            continue
        got = _norm_rule(_rule_field(live_by_code.get(c["Key"]), "ComputationRule"))
        if exp != got:
            badfx.append((c["Key"], exp, got))
    # 汇总控件 RollupSettings：期望带配置的才比（规整掉条件 Id/键序后语义比对）；
    # 线上整条丢失也算不符
    badru = []
    for c in form["fields"]:
        if not _ctrl_opt(c).get("RollupSettings"):
            continue
        if _rollup_key(c) != _rollup_key(live_by_code.get(c["Key"])):
            badru.append((c["Key"], _rollup_key(c)[:400],
                          _rollup_key(live_by_code.get(c["Key"]))[:400]))
    # 服务端校验位：RollupSettingsMap[字段][0].Success —— 服务端真去解析了源表与源字段，
    # False（或这条缺失）说明数据源/字段没解析到（编码写错、字段不存在、被删）
    badrs = []
    rmap = _rollup_map(rd)
    for c in form["fields"]:
        if not _ctrl_opt(c).get("RollupSettings"):
            continue
        ent = rmap.get(c["Key"])
        if not ent:
            badrs.append((c["Key"], "RollupSettingsMap 无此字段（服务端没认这条配置）"))
        elif not (ent[0] or {}).get("Success"):
            badrs.append((c["Key"], "Success=false（数据源/源字段没解析到）"))
    for code in live_by_code:
        # 系统拥有者字段（OwnerId/OwnerDeptId）经 UI 布局加入，属正常存在，不算额外
        if code not in expect and code not in ("_id", "ObjectId",
                                               "OwnerId", "OwnerDeptId"):
            extra.append(code)
    # 位置控件设置（ControlSettingsStr）：期望有才比，逐键比文本
    exp_set = _settings_of(form["fields"])
    live_set = _live_settings(rd)
    badset = []
    for k, want in exp_set.items():
        got_s = live_set.get(k)
        if got_s is None:
            badset.append((k, want, None))
            continue
        for kk, vv in want.items():
            if got_s.get(kk) != vv:
                badset.append(("%s.%s" % (k, kk), vv, got_s.get(kk)))
    row_sizes = [len(ci(d, "columns") or ci(d, "childControls") or []) for d in rows]
    n_expect_rows = expected_layout_rows(form)
    name_live = rd.get("NameSchema")
    # extra（线上比定义多的字段）只提示不判失败：用户在界面加字段是常态，定义可随后同步
    ok = (not miss and not bad and not badf and not badfx and not badset
          and not badru and not badrs and len(rows) == n_expect_rows)
    return {"ok": ok,
            "fields_expect": len(expect), "fields_live": len(live_by_code),
            "miss": miss, "extra": extra[:MAX_SHOW], "bad": bad[:MAX_SHOW],
            "badf": badf[:MAX_SHOW], "badfx": badfx[:MAX_SHOW],
            "badru": badru[:MAX_SHOW], "badrs": badrs[:MAX_SHOW],
            "badset": badset[:MAX_SHOW],
            "rows_expect": n_expect_rows, "rows_live": len(rows),
            "row_sizes": row_sizes,
            "name_expect": form.get("name_schema", ""), "name_live": name_live}


def format_report(tag, code, form, rd):
    """核对结果 → 多行文本（PASS/FAIL + 明细），可写日志或直出"""
    r = compare(form, rd)
    lines = ["== %s %s ==" % (tag, code)]
    subs = form.get("subs") or []
    n_sub = len(subs)
    n_scol = sum(len(s["cols"]) for s in subs)
    lines.append("字段: 期望 %d 实得 %d | 规则: 不符 %d%s%s%s%s%s | 行组(102): 期望 %d 实得 %d (%s)%s"
                 % (r["fields_expect"], r["fields_live"], len(r["bad"]),
                    (" | 联动过滤: 不符 %d" % len(r["badf"])) if r["badf"] else "",
                    (" | 公式: 不符 %d" % len(r["badfx"])) if r["badfx"] else "",
                    (" | 汇总: 不符 %d" % len(r["badru"])) if r["badru"] else "",
                    (" | 汇总校验位: 异常 %d" % len(r["badrs"])) if r["badrs"] else "",
                    (" | 位置设置: 不符 %d" % len(r["badset"])) if r["badset"] else "",
                    r["rows_expect"], r["rows_live"], r["row_sizes"],
                    (" | 子表: %d(列%d)" % (n_sub, n_scol)) if n_sub else ""))
    if r["miss"]:
        lines.append("缺字段(%d): %s" % (len(r["miss"]), r["miss"][:MAX_SHOW]))
    if r["extra"]:
        lines.append("INFO 线上多出字段（UI 后加，定义未同步）: %s" % r["extra"])
    for k, e, g in r["bad"][:MAX_SHOW]:
        lines.append("规则不符 %s\n    期望 %s\n    实得 %s" % (k, e, g))
    for k, e, g in r["badf"][:MAX_SHOW]:
        lines.append("联动过滤不符 %s\n    期望 %s\n    实得 %s" % (k, e, g))
    for k, e, g in r["badfx"][:MAX_SHOW]:
        lines.append("公式不符 %s\n    期望 %s\n    实得 %s" % (k, e, g))
    for k, e, g in r["badru"][:MAX_SHOW]:
        lines.append("汇总不符 %s\n    期望 %s\n    实得 %s" % (k, e, g))
    for k, msg in r["badrs"][:MAX_SHOW]:
        lines.append("汇总校验位 %s: %s" % (k, msg))
    for k, e, g in r["badset"][:MAX_SHOW]:
        if g is None:
            lines.append("位置设置缺失 %s（期望 %s；线上无此控件的 ControlSettings）" % (k, e))
        else:
            lines.append("位置设置不符 %s\n    期望 %s\n    实得 %s" % (k, e, g))
    if r["name_expect"] and r["name_live"] != r["name_expect"]:
        lines.append("NameSchema 期望 %s 实得 %s" % (r["name_expect"], r["name_live"]))
    lines.append("核对结果: %s" % ("PASS" if r["ok"] else "FAIL"))
    return "\n".join(lines)
