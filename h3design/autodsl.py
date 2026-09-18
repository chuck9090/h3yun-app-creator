# -*- coding: utf-8 -*-
"""自动化（触发器）DSL：automations/*.json → SaveTrigger 载荷（见 automation.py）。

项目目录：projects/<name>/automations/<key>.json，一条自动化一个文件。
声明形态（字段明细与实证依据见 docs/schema_doc.md 自动化章节）：

{
  "title": "采购订单生效后回写合同",
  "form": "采购订单",              // 触发表单：本项目表单 key 或 schema 编码
  "trigger": "生效或更新",          // 生效 | 失效 | 生效或更新
  "sortKey": 1,                    // 可选；缺省按文件名为该表单内第 1、2…条
  "names": {},                     // 可选：外部编码 → 显示名（RelationSchemaCodeAlias 用）
  "when": [ {"field": "供应商", "value": "1231"} ],   // 可选；外层数组=或、内层=且
  "actions": [
    { "do": "更新",                // 新增 | 更新 | 删除
      "target": "采购合同",
      "state": "生效",             // 生效(缺省) | 发起流程
      "isInsert": true,            // 仅 do=更新：匹配不到就新增（缺省 true）
      "match": [ {"field": "$ObjectId", "ref": "$ObjectId"} ],   // 定位**目标**记录
      "set":   [ {"to": "供应商", "from": "供应商"} ],            // 源字段 → 目标字段
      "owner": true,               // 缺省 true：自动补 OwnerId/OwnerDeptId 两条拥有者映射
      "sub": {                     // 写**目标表的子表**：两级动作（外层定位父 + 内层写行）
        "table": "明细",
        "set": [ {"to": "数量", "from": "明细.数量"} ]
      } } ] }

字段引用写法：
    主表字段 = 裸 key；子表列 = `子表key.列key`；系统字段 = `$ObjectId`/`$OwnerId`/
    `$OwnerDeptId`（子表行的 ObjectId 写 `明细.$ObjectId`）。
when 只筛**触发表主表字段**（子表列条件未实证）；match/set 的源侧可引用子表列
（线上样本已用 `<触发表别名>.<子表别名>.<列码>` 实证）。"""
import json
import os

from . import automation as AUT
from . import dsl as D


def _form_inv(proj_dir, form_key):
    """本项目表单的字段清单 {main:{key:label}, subs:{subkey:{colkey:label}}, title}；
    表单不是本项目定义（外部编码）→ None（字段存在性不校验，原样透传）。"""
    if not form_key:
        return None
    p = os.path.join(proj_dir, "sheets", "%s.json" % form_key)
    if not os.path.isfile(p):
        return None
    sheet = D._read_json(p)
    main, subs = {}, {}
    for c in sheet.get("controls") or []:
        if not isinstance(c, dict) or c.get("type") in D.LAYOUT_TYPES:
            continue
        if c.get("type") == "subtable":
            subs[str(c.get("key"))] = {str(col.get("key")): (col.get("label") or "")
                                       for col in (c.get("columns") or [])
                                       if isinstance(col, dict) and col.get("key")}
        elif c.get("key"):
            main[str(c["key"])] = c.get("label") or str(c["key"])
    return {"main": main, "subs": subs, "title": sheet.get("title") or form_key}


def _form_ref(ref, registry, proj_dir, who, what):
    """表引用 → (编码, 显示名, 本项目表单 key 或 None, 字段清单或 None)。"""
    ref = str(ref or "").strip()
    if not ref:
        raise ValueError("%s: %s 为空（写本项目表单 key 或 schema 编码）" % (who, what))
    rec = (registry or {}).get(ref) or {}
    if rec.get("code"):
        return rec["code"], rec.get("title") or ref, ref, _form_inv(proj_dir, ref)
    if len(ref) >= 20 and not ref.isdigit():
        return ref, ref, None, None
    raise ValueError("%s: %s %r 不是本项目表单 key（registry 里无编码），也不像 schema "
                     "编码 —— 外部表请直接写它的完整编码" % (who, what, ref))


def _sub_code(form_key, sub_key, registry, who, what="子表"):
    """子表 key → child schema 编码。目标是外部编码时，子表也得直接写子表编码。"""
    sub_key = str(sub_key or "").strip()
    if form_key:
        subs = ((registry or {}).get(form_key) or {}).get("subs") or {}
        code = (subs.get(sub_key) or {}).get("code")
        if code:
            return code
        raise ValueError("%s: %s %r 在表单 %s 的 registry 里没有编码（已建子表: %s）——"
                         "先建表再用，或子表直接写子表编码"
                         % (who, what, sub_key, form_key,
                            ", ".join(sorted(subs)) or "（无）"))
    if len(sub_key) >= 20:      # 子表编码长度不固定（27/37/40 位都见过）
        return sub_key
    raise ValueError("%s: 目标表是外部编码时，%s %r 必须直接写子表编码"
                     % (who, what, sub_key))


def _split(txt, who):
    """字段引用 → (子表key 或 None, 字段key)。`$` 前缀原样保留在字段 key 上。"""
    t = str(txt or "").strip()
    if not t:
        raise ValueError("%s: 字段引用为空" % who)
    if t.startswith("$"):
        return None, t
    if "." in t:
        a, b = t.split(".", 1)
        return a.strip(), b.strip()
    return None, t


def _main_field(key, inv, who, what):
    """主表字段 key → 编码；系统字段写 $X 或裸 X 都收，本项目表单校验存在性。"""
    if key.startswith("$"):
        key = key[1:]
    if key in AUT.SYS_FIELDS:
        return key
    if inv is not None and key not in inv["main"]:
        raise ValueError("%s: %s %r 不是该表单的主表字段（现有 %s；系统字段写 %s）"
                         % (who, what, key, ", ".join(sorted(inv["main"])) or "（无）",
                            "/".join("$" + s for s in AUT.SYS_FIELDS)))
    return key


def _sub_field(sub, key, inv, who, what):
    """子表列 key → 列编码（原样）；本项目表单校验存在性。"""
    if key.startswith("$"):
        key = key[1:]
        if key not in AUT.SYS_FIELDS:
            raise ValueError("%s: %s 的 $%s 不是系统字段（只有 %s）"
                             % (who, what, key, "/".join(AUT.SYS_FIELDS)))
        return key
    if inv is not None:
        cols = inv["subs"].get(sub)
        if cols is None:
            raise ValueError("%s: %s 引用子表 %r，但该表单没有这个子表（现有 %s）"
                             % (who, what, sub, ", ".join(sorted(inv["subs"])) or "（无）"))
        if key not in cols:
            raise ValueError("%s: %s 子表 %s 没有列 %r（现有 %s）"
                             % (who, what, sub, key, ", ".join(sorted(cols)) or "（无）"))
    return key


def _groups(raw, who, what):
    """条件声明 → 条件组列表（外层=或、内层=且；单组可省一层）。"""
    if raw in (None, [], ""):
        return []
    nested = isinstance(raw, list) and raw and isinstance(raw[0], list)
    if not isinstance(raw, list) or not (nested or all(isinstance(g, dict)
                                                       for g in raw)):
        raise ValueError("%s: %s 须为条件数组（单组「且」）或条件组数组（多组「或」）"
                         % (who, what))
    out = raw if nested else [raw]
    for grp in out:
        if not isinstance(grp, list) or not grp:
            raise ValueError("%s: %s 每个条件组须为非空数组: %r" % (who, what, grp))
        for it in grp:
            if not isinstance(it, dict):
                raise ValueError("%s: %s 条件须为对象: %r" % (who, what, it))
            if (it.get("op") or "=") != "=":
                raise ValueError("%s: %s 条件只实证过等值（op 缺省 `=`）——得到 %r"
                                 % (who, what, it.get("op")))
    return out


def _one_of(it, who, what):
    """条件的 value（固定值）/ ref（取字段）二选一 → ("Fixed"|"PropertyName", 值)"""
    has_v, ref = "value" in it, it.get("ref")
    if has_v == (ref is not None):
        raise ValueError("%s: %s 条件须且只须 value（固定值）或 ref（取字段）其一: %r"
                         % (who, what, it))
    return ("Fixed", it["value"]) if has_v else ("PropertyName", ref)


# ---------------------------------------------------------------------
def _when_conds(spec, who, t_alias, t_inv):
    """触发条件 when → Condition.Expression（DNF，Id 必带）。
    触发表主表字段；动态引用写 `<触发表别名>.<字段码>`（ParentCondition 实证同款，
    触发条件本身只有固定值样本，动态引用属推定 —— 线上 verify 会回读比对）。"""
    out = []
    for grp in _groups(spec.get("when"), who, "when"):
        conds = []
        for it in grp:
            sub, key = _split(it.get("field"), who)
            if sub is not None:
                raise ValueError(
                    "%s: when.field 只支持触发表的**主表字段**（子表列触发条件未实证，"
                    "子表行筛选请写进动作的 match）——得到 %r" % (who, it.get("field")))
            prop = _main_field(key, t_inv, who, "when.field")
            kind, val = _one_of(it, who, "when")
            if kind == "PropertyName":
                rsub, rkey = _split(val, who)
                if rsub is not None:
                    raise ValueError("%s: when.ref 只支持触发表主表字段 —— 得到 %r"
                                     % (who, val))
                val = "%s.%s" % (t_alias, _main_field(rkey, t_inv, who, "when.ref"))
            conds.append(AUT.auto_cond(prop, kind, val))
        out.append(conds)
    return out


def _match_conds(acts, who, tgt_inv, src_ref):
    """动作 match → ParentCondition（更新/删除定位目标记录；Id 必带）。
    field 是**目标**表的字段，ref 是**源**字段。"""
    out = []
    for grp in _groups(acts.get("match"), who, "match"):
        conds = []
        for it in grp:
            sub, key = _split(it.get("field"), who)
            if sub is not None:
                raise ValueError(
                    "%s: match.field 只支持**目标主表字段**（目标子表列定位未实证）"
                    "——得到 %r" % (who, it.get("field")))
            prop = _main_field(key, tgt_inv, who, "match.field")
            kind, val = _one_of(it, who, "match")
            if kind == "PropertyName":
                _, val = src_ref(val, who, "match.ref")
            conds.append(AUT.auto_cond(prop, kind, val))
        out.append(conds)
    return out


def _match_v2(acts, who, tgt_inv, src_ref):
    """写目标表子表时外层动作的 ParentConditionV2（定位父记录；无 Id、带 SubOperator）"""
    out = []
    for grp in _groups(acts.get("match"), who, "match"):
        conds = []
        for it in grp:
            sub, key = _split(it.get("field"), who)
            if sub is not None:
                raise ValueError("%s: match.field 只支持**目标主表字段** —— 得到 %r"
                                 % (who, it.get("field")))
            prop = _main_field(key, tgt_inv, who, "match.field")
            kind, val = _one_of(it, who, "match")
            if kind == "PropertyName":
                _, val = src_ref(val, who, "match.ref")
            conds.append(AUT.parent_cond_v2(prop, kind, val))
        out.append(conds)
    return out


# ---------------------------------------------------------------------
def _build_automation(path, proj_dir, app_code, registry, sort_key=1,
                      operation="isUpdate"):
    key = os.path.splitext(os.path.basename(path))[0]
    proj = os.path.basename(os.path.abspath(proj_dir))
    spec = D._read_json(path)
    who = key
    # operation 可给字符串，也可给 callable(key, form_code) —— 调用方用它按"线上是否已有
    # 这条（ObjectId 是确定性 uuid5）"决定 isAdd/isUpdate

    trg = spec.get("trigger")
    if trg not in AUT.TRIGGER_TYPES:
        raise ValueError("%s: trigger 须为 %s 之一（生效=数据生效时、失效=数据失效时、"
                         "生效或更新=生效或者更新时）——得到 %r"
                         % (who, "/".join(AUT.TRIGGER_TYPES), trg))
    etype = AUT.TRIGGER_TYPES[trg]

    form_code, form_name, form_key, t_inv = _form_ref(
        spec.get("form"), registry, proj_dir, who, "form（触发表单）")
    t_alias = AUT.alias_of(form_code)
    names = spec.get("names") or {}
    form_name = names.get(form_code) or names.get(form_key) or form_name
    used = []                       # 引到的 schema 编码（RelatedSchemaCodeAliases）
    src_subs = []                   # 动作读到的触发表子表 key

    def name_of(fkey, fcode):
        """目标表在 RelationSchemaCodeAlias 里的显示名：names 覆盖 > registry.title > 编码"""
        if fcode in names:
            return names[fcode]
        if fkey and fkey in names:
            return names[fkey]
        title = ((registry or {}).get(fkey) or {}).get("title") if fkey else None
        return title or None

    def note(code):
        if code and code not in used:
            used.append(code)

    def src_ref(txt, who2, what):
        """源侧字段引用 → (子表key 或 None, SourceField 串)"""
        sub, key = _split(txt, who2)
        if sub is None:
            code = _main_field(key, t_inv, who2, what)
            return None, "%s.%s" % (t_alias, code)
        code = _sub_field(sub, key, t_inv, who2, what)
        cc = _sub_code(form_key, sub, registry, who2)
        note(cc)
        if sub not in src_subs:
            src_subs.append(sub)
        return sub, "%s.%s.%s" % (t_alias, AUT.alias_of(cc), code)

    acts = spec.get("actions")
    if not isinstance(acts, list) or not acts:
        raise ValueError("%s: 必须声明非空 actions 数组" % who)
    note(form_code)

    built = []
    for i, a in enumerate(acts):
        if not isinstance(a, dict):
            raise ValueError("%s: actions[%d] 须为对象: %r" % (who, i, a))
        do = a.get("do") or "新增"
        plugin = AUT.PLUGIN_OF_DO.get(do)
        if not plugin:
            raise ValueError("%s: actions[%d].do 须为 %s 之一 ——得到 %r"
                             % (who, i, "/".join(AUT.PLUGIN_OF_DO), do))
        state = a.get("state") or "生效"
        if state not in AUT.TARGET_STATES:
            raise ValueError("%s: actions[%d].state 须为 %s 之一 ——得到 %r"
                             % (who, i, "/".join(AUT.TARGET_STATES), state))
        if do == "删除" and (a.get("set") or a.get("sub")):
            raise ValueError("%s: actions[%d] 是删除动作，不能带 set/sub（删除不写字段）"
                             % (who, i))
        tgt_code, tgt_name, tgt_key, tgt_inv = _form_ref(
            a.get("target"), registry, proj_dir, who, "actions[%d].target" % i)
        sub_spec = a.get("sub")
        if sub_spec is not None and not isinstance(sub_spec, dict):
            raise ValueError("%s: actions[%d].sub 须为对象 {table, set}" % (who, i))
        act_sub = _sub_code(tgt_key, (sub_spec or {}).get("table"), registry, who,
                            "actions[%d].sub.table" % i) if sub_spec else None

        # ---- 字段映射（外层 = 目标**主表**字段）----
        has_set = bool(a.get("set"))
        maps = []
        for m in a.get("set") or []:
            if not isinstance(m, dict) or "to" not in m or "from" not in m:
                raise ValueError("%s: actions[%d].set 每项须为 {to, from}: %r"
                                 % (who, i, m))
            _, sref = src_ref(m["from"], who, "set.from")
            tsub, tkey = _split(m["to"], who)
            if tsub is not None:
                raise ValueError(
                    "%s: actions[%d].set.to 不能带子表前缀（%r）—— 目标子表列写进 "
                    "sub.set" % (who, i, m["to"]))
            maps.append(AUT.mapping(sref, _main_field(tkey, tgt_inv, who, "set.to")))
        # 拥有者映射：写主表字段时自动补；只写子表（无 set）时不补 —— 线上样本同款
        if a.get("owner", True) and (has_set or not sub_spec):
            for sysf in AUT.OWNER_AUTO:
                maps.append(AUT.mapping("%s.%s" % (t_alias, sysf), sysf))

        # 定位条件 / 内层子表映射：都要先解析（会登记源子表 → 决定 SourceId）
        if sub_spec:
            tgt_sub_code = _sub_code(tgt_key, sub_spec.get("table"), registry, who)
            inner, v2 = [], _match_v2(a, who, tgt_inv, src_ref)
            for m in sub_spec.get("set") or []:
                if not isinstance(m, dict) or "to" not in m or "from" not in m:
                    raise ValueError("%s: actions[%d].sub.set 每项须为 {to, from}: %r"
                                     % (who, i, m))
                _, sref = src_ref(m["from"], who, "sub.set.from")
                tsub, tkey = _split(m["to"], who)
                if tsub is not None and tsub != sub_spec.get("table"):
                    raise ValueError("%s: actions[%d].sub.set.to %r 的子表前缀不是 "
                                     "sub.table(%r)" % (who, i, m["to"],
                                                        sub_spec.get("table")))
                col = _sub_field(sub_spec.get("table"), tkey, tgt_inv, who,
                                 "sub.set.to")
                inner.append(AUT.mapping(sref, "%s.%s" % (tgt_sub_code, col)))
            if not inner:
                raise ValueError("%s: actions[%d].sub.set 不能为空（没有要写的子表列）"
                                 % (who, i))
            pcond, v2cond = [], v2
        elif plugin == "updatedata" or plugin == "removedata":
            inner, tgt_sub_code = [], None
            pcond = _match_conds(a, who, tgt_inv, src_ref)
            v2cond = []
            if not pcond:
                raise ValueError("%s: actions[%d] 是%s动作，必须用 match 说明定位哪条"
                                 "目标记录（否则会全表更新）"
                                 % (who, i, "更新" if plugin == "updatedata" else "删除"))
        else:
            inner, tgt_sub_code, pcond, v2cond = [], None, [], []

        # SourceId：动作读到了触发表的子表列 → 子表编码（按子表行触发），否则主表编码
        src_id = form_code if not src_subs else \
            _sub_code(form_key, src_subs[0], registry, who, "源子表")
        note(tgt_code)
        note(act_sub)
        # RelationSchemaCodeAlias 每条 = [主别名, 子别名(无子表则同主别名), 表单名]；
        # 目标表那条线上写主别名两次（子表别名不进这里，见 a4 实证）
        rel = [[t_alias, AUT.alias_of(src_id) if src_subs else t_alias, form_name],
               [AUT.alias_of(tgt_code), AUT.alias_of(tgt_code),
                name_of(tgt_key, tgt_code) or tgt_name]]
        aliases_j = [{"Alias": AUT.alias_of(c), "SchemaCode": c} for c in used]
        st = AUT.TARGET_STATES[state]
        obj_id = AUT.action_object_id(proj, key, str(i))
        children = [] if not sub_spec else [
            AUT.action("insertdata", etype, form_code, src_id,
                       [app_code, tgt_code, tgt_sub_code], aliases_j, rel,
                       AUT.action_object_id(proj, key, "%d.0" % i),
                       state=st, insert_mappings=inner, child_target=True,
                       nested=True)]

        if sub_spec:
            # 写目标表的子表：外层定位/新建父记录，内层写子表行。
            # 没写 set（只想同步子表行）→ 外层只创建子表（线上样本同款）
            built.append(AUT.action("insertdata", etype, form_code, src_id,
                                    [app_code, tgt_code, tgt_code], aliases_j, rel,
                                    obj_id, state=st, insert_mappings=maps,
                                    only_create=not has_set,
                                    parent_condition_v2=v2cond,
                                    children=children))
        elif plugin == "insertdata":
            built.append(AUT.action("insertdata", etype, form_code, src_id,
                                    [app_code, tgt_code, tgt_code], aliases_j, rel,
                                    obj_id, state=st, insert_mappings=maps))
        elif plugin == "updatedata":
            is_insert = bool(a.get("isInsert", True))
            built.append(AUT.action("updatedata", etype, form_code, src_id,
                                    [app_code, tgt_code, tgt_code], aliases_j, rel,
                                    obj_id, state=st, is_insert=is_insert,
                                    parent_condition=pcond, update_mappings=maps,
                                    insert_mappings=maps if is_insert else []))
        else:
            built.append(AUT.action("removedata", etype, form_code, src_id,
                                    [app_code, tgt_code, tgt_code], aliases_j, rel,
                                    obj_id, parent_condition=pcond))

    return {"key": key,
            "title": spec.get("title") or key,
            "form_key": form_key, "form_code": form_code, "form_name": form_name,
            "trigger": trg, "excute_type": etype, "sort_key": sort_key,
            "payload": AUT.build_trigger({
                "objectId": AUT.trigger_object_id(proj, key),
                "schema_code": form_code,
                "display_name": spec.get("title") or key,
                "excute_type": etype,
                "expression": _when_conds(spec, who, t_alias, t_inv),
                "aliases": [{"Alias": AUT.alias_of(c), "SchemaCode": c}
                            for c in used],
                "actions": built,
                "sort_key": spec.get("sortKey") or sort_key,
                "app_code": app_code,
                "operation": (operation(key, form_code) if callable(operation)
                              else operation)}),
            "_source": os.path.relpath(path, proj_dir)}


def _sort_keys(specs):
    """同表单内按「显式 sortKey 优先、否则文件名序」自动排 1..n（界面 SortKey 语义）"""
    out, seq = {}, {}
    for key, path in specs:
        form = str(D._read_json(path).get("form") or "")
        seq[form] = seq.get(form, 0) + 1
        out[key] = seq[form]
    return out


def load_automations(proj_dir, app_code, registry, operation="isUpdate"):
    """项目全部自动化 → [builder 产物]，按 (触发表单, 排序号) 排。无 automations/ → []。"""
    ad = os.path.join(proj_dir, "automations")
    if not os.path.isdir(ad):
        return []
    specs = [(os.path.splitext(fn)[0], os.path.join(ad, fn))
             for fn in sorted(os.listdir(ad)) if fn.endswith(".json")]
    if not specs:
        return []
    seq = _sort_keys(specs)
    out = [_build_automation(p, proj_dir, app_code, registry,
                             sort_key=seq[k], operation=operation)
           for k, p in specs]
    out.sort(key=lambda a: (a["form_code"], a["sort_key"], a["key"]))
    return out


def load_automation(proj_dir, ref, app_code, registry, operation="isUpdate"):
    """单条自动化（ref = key 或 sheets 同名）。"""
    p = os.path.join(proj_dir, "automations", "%s.json" % ref)
    if not os.path.isfile(p):
        raise ValueError("项目 %s 没有自动化 %r（automations/%s.json 不存在）"
                         % (proj_dir, ref, ref))
    return _build_automation(p, proj_dir, app_code, registry, operation=operation)
