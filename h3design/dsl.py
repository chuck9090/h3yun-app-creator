# -*- coding: utf-8 -*-
"""表单 DSL：项目定义 → 与奥驰 forms.build 同构的控件结构。

项目目录约定（projects/<name>/）：
    config.json      连接配置（缺省则用工厂根 config.json；含凭据，勿提交/分享）
    dicts.json       枚举分类，下拉/单选/复选的选项源
    sheets/*.json    每表单一个 JSON 定义（文件名 = 表单 key）—— 推荐模式
    forms.py         旧版 python 定义（legacy 兼容，格式见 docs/schema_doc.md「legacy 兼容」）

load_project() 返回 {key: loader}，loader() 产出
    {key, title, name_schema, fields, layout, assoc, useOwner}
其中 fields/layout 直接可喂给 newbuilder.build_schema_str / build_biz_sheet；
useOwner 供 build 期望字段数补 OwnerId/OwnerDeptId 两系统字段。
JSON 完整格式见 docs/schema_doc.md。"""
import importlib.util
import json
import os
import re
import sys

from . import controls as C

# =====================================================================
# 系统拥有者字段（OwnerId/OwnerDeptId）：Layout 专用伪控件，
# 不进 fields/Properties（系统字段），Options 逐字对照线上回读样本。
# useOwner=true 后可在 layout 行内以字符串 "OwnerId"/"OwnerDeptId" 引用。
# =====================================================================
_OWNER_OPT = {
    "Key": "OwnerId", "Type": 203, "ChildControls": None, "Options": {
        "DataField": "OwnerId", "DisplayName": "申请人", "Description": "",
        "ControlKey": "FormUser", "Summary": "", "DisplayRule": {"Rule": ""},
        "UnitSelectionRange": "", "IsRelatedMember": False, "ShowUnActive": False,
        "UseDataCache": True, "CurrentUserId": False,
        "MappingControls": '{"ParentId":"OwnerDeptId"}',
        "OrgUnitVisible": False, "UserVisible": True, "OwnDepVisible": False,
        "OwnDepUsersVisble": True, "IsMultiple": False, "ShowCurUser": False}}
_OWNER_DEPT_OPT = {
    "Key": "OwnerDeptId", "Type": 204, "ChildControls": None, "Options": {
        "DataField": "OwnerDeptId", "DisplayName": "申请部门", "Description": "",
        "ControlKey": "FormDepartment", "Summary": "", "DisplayRule": {"Rule": ""},
        "UnitSelectionRange": "", "IsRelatedMember": False, "ShowUnActive": False,
        "UseDataCache": True, "CurrentUserId": False, "MappingControls": "",
        "OrgUnitVisible": True, "UserVisible": False, "OwnDepVisible": True,
        "OwnDepUsersVisble": False, "IsMultiple": False}}


def owner_presets(applicant_label="申请人", dept_label="申请部门"):
    """两个系统拥有者布局项（拷贝后改显示名）"""
    o, d = _OWNER_OPT, _OWNER_DEPT_OPT
    if applicant_label != "申请人":
        o = json.loads(json.dumps(o, ensure_ascii=False))
        o["Options"]["DisplayName"] = applicant_label
    if dept_label != "申请部门":
        d = json.loads(json.dumps(d, ensure_ascii=False))
        d["Options"]["DisplayName"] = dept_label
    return o, d


def _read_json(path, what=""):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dict_entries(proj_dir, cat):
    """dicts.json 中分类枚举 → [{"code":..., "name":...}]。
    条目简写（纯字符串）或 {code?, name, enabled?}；数组顺序即排序。"""
    dp = os.path.join(proj_dir, "dicts.json")
    if not os.path.isfile(dp):
        raise ValueError("引用字典分类 %r 但项目缺 %s" % (cat, dp))
    d = _read_json(dp)
    items = d.get(cat)
    if items is None:
        raise ValueError("dicts.json 缺分类 %r（现有 %s）" % (cat, list(d)))
    out = []
    for it in items:
        if isinstance(it, str):
            out.append({"code": it, "name": it})
        elif isinstance(it, dict):
            if it.get("enabled") is False:
                continue
            name = it["name"]
            out.append({"code": it.get("code") or name, "name": name})
        else:
            raise ValueError("分类 %r 条目须为字符串或对象: %r" % (cat, it))
    if not out:
        raise ValueError("分类 %r 无可启用条目" % cat)
    return out


def _options(proj_dir, spec):
    """控件选项源：dict=分类名引用 dicts.json；options=字面量数组"""
    if spec.get("dict"):
        return [e["name"] for e in _dict_entries(proj_dir, spec["dict"])]
    if spec.get("options"):
        return [str(x) for x in spec["options"]]
    raise ValueError("%s.%s 需 dict 或 options" % (spec.get("key"), spec.get("type")))


def _rule(spec):
    return spec.get("hideWhen") or ""


# 联动下拉(选项来自另一张表)过滤规则序列化。声明形态（schema_doc 联动下拉章节）：
#   {field: 源表字段编码, op: "="(缺省) | "contains", value: 常量字符串 | ref: 本表字段key}
# 实证语法（2026-09-09 类型试验 三处载荷逐字）：常量等值 {源.字段}=="值"、
# 动态引用 {源.字段}=={本表字段}、多值列包含 CONTAINS({源.字段},{本表字段})，
# 条件间 " AND " 连接。发 clean 文本（== 无空格、无 NBSP）——引擎直接接受
# （第一轮无 NBSP 样本保存成功）；NBSP/空格是 UI 重存才插入的漂移。
def _filter_text(spec, src_code, key):
    entries = spec.get("filter")
    if entries in (None, [], ""):
        return ""
    if not isinstance(entries, list):
        raise ValueError("%s: filter 须为条件数组（{field,op,value|ref}）" % key)
    parts = []
    for it in entries:
        if not isinstance(it, dict):
            raise ValueError("%s: filter 条目须为对象: %r" % (key, it))
        f = it.get("field")
        if not isinstance(f, str) or not f:
            raise ValueError("%s: filter 条目缺 field（源表字段编码）: %r" % (key, it))
        op, ref, value = it.get("op", "="), it.get("ref"), it.get("value")
        lhs = "{%s.%s}" % (src_code, f)
        if op == "contains":
            if ref is None or "value" in it:
                raise ValueError("%s: contains 条件须且只须 ref（本表字段 key，"
                                 "CONTAINS 按分号串包含匹配源表该列）: %r" % (key, it))
            parts.append("CONTAINS(%s,{%s})" % (lhs, ref))
        elif op == "=":
            if (ref is None) == ("value" not in it):
                raise ValueError("%s: 等值条件须且只须 value（常量）或 ref"
                                 "（本表字段动态引用）其一: %r" % (key, it))
            if "value" in it:
                if not isinstance(value, str):
                    raise ValueError("%s: 常量 value 须为字符串（数字常量带引号"
                                     "比较未实证）: %r" % (key, it))
                parts.append("%s==%s" % (lhs, json.dumps(value, ensure_ascii=False)))
            else:
                parts.append("%s=={%s}" % (lhs, ref))
        else:
            raise ValueError("%s: filter op 仅支持 =/contains（实证集合），得 %r"
                             % (key, op))
    return " AND ".join(parts)


def _assoc_dropdown(spec, registry, app_code):
    """dropdown spec（带 assoc）→ C.assoc_dropdown 控件。assoc 引 registry 里
    已注册的源表单 key（先建被引用表，同 query）；存值列与过滤条件在此校验。"""
    key, label = spec["key"], spec.get("label") or spec["key"]
    if spec.get("dict") or spec.get("options"):
        raise ValueError("%s: assoc 下拉选项来自另一张表，不能再给 dict/options" % key)
    if spec.get("default") not in (None, ""):
        raise ValueError("%s: assoc 下拉不支持 default（存值/回显语义未实证）" % key)
    mf = spec.get("assocField")
    if not isinstance(mf, str) or not mf:
        raise ValueError("%s: assoc 下拉须声明 assocField（存值列 = 源表字段编码，"
                         "如 \"code\" 存代码、\"name\" 存名称）" % key)
    src = _assoc_code(spec["assoc"], registry, key)
    return C.assoc_dropdown(key, label, src, mf,
                            filter_rule=_filter_text(spec, src, key),
                            app_package=app_code, rule=_rule(spec))


# 子表列支持的控件类型（UI 实证范围：文本/数字/日期/开关/单选/复选/下拉；成员/部门/
# 关联/嵌套子表暂不开放 —— 平台 104 列节点 Options 结构未实证）
GRID_COL_TYPES = ("text", "textarea", "number", "date", "switch",
                  "radio", "dropdown", "checkbox_list",
                  # 2026-09-11 起开放附件/图片列 —— 与主表同款 Options 形状，
                  # 线上实证见 projects/_types7_online trial8（列节点回读逐键比对）
                  "attachment", "image")

# 布局项：只占版面、不是字段（不进 SchemaStr.Properties、不进 verify 的字段集）
#   group_title —— 分组标题（type 101，Options 只有 DisplayName/Title/Alignment）
#   description —— 描述/说明文字（type 103，Content 为富文本 HTML）
LAYOUT_TYPES = ("group_title", "description")


def _build_layout_item(spec):
    """布局项 spec → controls.group_title / controls.description 控件。"""
    t = spec["type"]
    key = spec["key"]
    label = spec.get("label") or spec.get("title") or key
    if t == "group_title":
        align = spec.get("align") or "left"
        if align not in ("left", "center", "right"):
            raise ValueError("%s: group_title 的 align 只支持 left/center/right" % key)
        return C.group_title(key, label, alignment=align)
    content = spec.get("content")
    if content is None:
        content = "<p>%s</p>" % label        # 简写：没给 content 就用 label 兜底
    if not isinstance(content, str):
        raise ValueError("%s: description 的 content 须为 HTML 字符串" % key)
    return C.description(key, content, display_name=spec.get("title") or "描述说明",
                         rule=_rule(spec))


def _assoc_code(assoc, registry, label=""):
    if not assoc:
        return ""
    rec = (registry or {}).get(assoc) or {}
    code = rec.get("code")
    if not code:
        raise ValueError("%s关联表单 %r 未注册（registry 无 code，先建被引用表）"
                         % (label, assoc))
    return code


# =====================================================================
# 汇总控件（type 501）的源解析与条件拼装
# =====================================================================
def _schema_code_of(ref, registry, who):
    """数据源编码。两种写法：
    （a）**本项目表单 key** —— 走 registry 取真实编码（先建被引用表，同 assoc/query）；
    （b）**直接写 schema 编码**（40 位，界面/他人建的表）—— 原样用。"""
    ref = str(ref or "").strip()
    if not ref:
        raise ValueError("%s: 汇总控件必须声明 source（数据源表单 key 或 schema 编码）" % who)
    rec = (registry or {}).get(ref) or {}
    if rec.get("code"):
        return rec["code"]
    if len(ref) >= 32:
        return ref
    raise ValueError("%s: 数据源 %r 不是本项目表单 key（registry 里无编码），也不像 "
                     "schema 编码 —— 外部表请直接写它的完整编码" % (who, ref))


def _is_child_code(code):
    """子表 child schema 编码的形态：`<appCode前7位>F<32位hex>`（40 位，第 8 位是 F）；
    主表表单编码是 39 位。厂商实证：D001599Ff1d…（子表）vs D001599d2883…（主表）。"""
    return len(code) == 40 and code[7] == "F"


def _child_col_keys(proj_dir, source, child):
    """源表 sheets/<source>.json 里子表 <child> 声明的列 key 集合；读不到就 None
    （定义文件不在本工程/名字对不上时不拦，交给线上服务端报错）。"""
    if not proj_dir or not source or not child:
        return None
    p = os.path.join(proj_dir, "sheets", "%s.json" % source)
    try:
        controls = _read_json(p).get("controls") or []
    except Exception:
        return None
    for c in controls:
        if isinstance(c, dict) and c.get("type") == "subtable" \
                and str(c.get("key") or "") == child:
            return {str(col.get("key")) for col in (c.get("columns") or [])
                    if isinstance(col, dict) and col.get("key")}
    return None


def _rollup_source_code(spec, registry, who, proj_dir=None):
    """→ (source_schema_code, is_child, child_col_keys)。sourceChild 给了就是子表汇总：
    子表编码取 registry[源表单]["subs"][子表key]（同项目）或原样 40 位编码。
    直接拿子表编码当 source 也认（形态见 _is_child_code）——子表汇总的条件里
    PropertyName 要带 `<子表码>.` 前缀，光看编码得知道它是不是子表。
    child_col_keys = 子表声明过的列 key（校验筛选条件用），拿不到为 None。"""
    src = _schema_code_of(spec.get("source"), registry, who)
    child = spec.get("sourceChild")
    if child in (None, ""):
        return src, _is_child_code(src), None
    child = str(child).strip()
    src_key = str(spec.get("source") or "").strip()
    rec = (registry or {}).get(src_key) or {}
    sub = ((rec.get("subs") or {}).get(child) or {}).get("code")
    if sub:
        return sub, True, _child_col_keys(proj_dir, src_key, child)
    if len(child) >= 32:
        return child, True, None
    raise ValueError("%s: sourceChild %r 不是 %r 的子表 key（registry 无该子表编码），"
                     "也不像子表编码" % (who, child, spec.get("source")))


def _rollup_groups(spec, who, prefix, self_code, allowed=None):
    """筛选条件 → 条件组（外层**或**、内层**且**）。
    声明形态：[{field,op,value|ref}, ...]（单组"且"简写）或 [[...],[...]]（多组"或"）。
    field = **源侧字段编码**（子表汇总写列编码即可，这里自动加 `<子表码>.` 前缀，
    线上条件里就是这么写的）；ref = **本表字段 key**（生成 `<本表码>.<字段>` 动态引用）。

    子表汇总时 allowed = 该子表声明的列 key：**条件只能筛子表列**，写主表字段会被
    服务端打回 `Rollup条件中存在已删除的字段`（2026-09-16 实证）——这里提前拦住。
    写全 `<子表码>.<列码>` 的也认，比对时剥掉前缀。"""
    fl = spec.get("filters")
    if fl in (None, [], ""):
        return []
    if not isinstance(fl, list):
        raise ValueError("%s: filters 须为条件数组（单组「且」）或条件组数组"
                         "（多组「或」）" % who)
    groups = fl if isinstance(fl[0], list) else [fl]
    out = []
    for grp in groups:
        if not isinstance(grp, list) or not grp:
            raise ValueError("%s: 每个筛选条件组须为非空数组: %r" % (who, grp))
        conds = []
        for it in grp:
            if not isinstance(it, dict):
                raise ValueError("%s: 筛选条件须为对象: %r" % (who, it))
            op = it.get("op", "=")
            if op != "=":
                raise ValueError("%s: 筛选条件 op 只实证过 `=`（等值）——得到 %r"
                                 % (who, op))
            f = it.get("field")
            if not isinstance(f, str) or not f:
                raise ValueError("%s: 筛选条件缺 field（**源表字段编码**）: %r" % (who, it))
            if allowed is not None and f.split(".")[-1] not in allowed:
                raise ValueError(
                    "%s: 筛选条件 field %r 不是源子表的列（可选 %s）。子表为数据源时"
                    "条件只能筛**子表列**，写主表字段会被服务端打回"
                    "「Rollup条件中存在已删除的字段」（2026-09-16 实证）"
                    % (who, f, sorted(allowed)))
            ref, has_val = it.get("ref"), "value" in it
            if (ref is None) == (not has_val):
                raise ValueError("%s: 筛选条件须且只须 value（固定值）或 ref"
                                 "（本表字段 key）其一: %r" % (who, it))
            full = f if (prefix and f.startswith(prefix)) else prefix + f
            if has_val:
                conds.append(C.rollup_cond(full, "Fixed", it["value"]))
            else:
                if not self_code:
                    raise ValueError("%s: 筛选条件引用了本表字段 %r，但本表还没编码"
                                     "（先 build，或改用固定值）" % (who, ref))
                conds.append(C.rollup_cond(full, "PropertyName",
                                           "%s.%s" % (self_code, ref)))
        out.append(conds)
    return out


def _build_rollup(spec, registry, key, label, self_code, proj_dir=None):
    kind = spec.get("rollup")
    if kind not in C.ROLLUP_TYPES:
        raise ValueError("%s: 汇总方式 rollup 须为 %s 之一（得到 %r）；计数=count、"
                         "求和=sum、最大值=max、最小值=min"
                         % (key, "/".join(sorted(C.ROLLUP_TYPES)), kind))
    prop = spec.get("property")
    if not isinstance(prop, str) or not prop.strip():
        raise ValueError("%s: 汇总控件必须声明 property —— **被汇总的源字段编码**"
                         "（计数也是挑源表一个字段来数）" % key)
    src, is_child, child_cols = _rollup_source_code(spec, registry, key, proj_dir)
    prefix = (src + ".") if is_child else ""
    groups = _rollup_groups(spec, key, prefix, self_code, child_cols)
    if spec.get("allStatus"):
        if not groups:
            raise ValueError("%s: allStatus=true（不限定已生效）时必须给 filters —— "
                             "无条件表达式未实证；只想要全部数据就先给一条恒真条件"
                             % key)
    else:
        # UI 默认每组第一条是 Status=1（只统计已生效数据）；不写就当没条件也要带上
        groups = [[C.rollup_cond(*C.ROLLUP_STATUS_COND)] + g for g in (groups or [[]])]
    try:
        dec = int(spec.get("decimal", 0))
    except (TypeError, ValueError):
        raise ValueError("%s: 汇总控件 decimal 须为整数（小数位）" % key)
    return C.rollup(key, label, kind, src, prop.strip(), groups,
                    decimal=dec, rule_hide=_rule(spec))


SEQNO_KEY = "SeqNo"       # 流水号字段编码固定 SeqNo（线上样本同款），定义里可省

# ---------------------------------------------------------------- 保留字（编码不得占用）
# 字段编码会成为氚云 `i_表单编码` / `i_子表控件编码` 表的**列名**，撞上下列两类保留字会出问题。
#
# ① 氚云平台自带编码（见《数据库表结构详解》h3yunpro.github.io/docs/database）：
#    主表 i_表单编码：ObjectId Name CreatedBy OwnerId OwnerDeptId CreatedTime
#                    ModifiedBy ModifiedTime WorkflowInstanceId Status
#    子表 i_子表控件编码：ObjectId Name ParentObjectId ParentPropertyName ParentIndex
#    关联表单多选中间表：ObjectId ValueIndex PropertyValue
#    另：State（系统表 H_* 用）、SeqNo（流水号控件固定编码，普通控件不得占用）
PLATFORM_RESERVED = (
    "ObjectId", "Name", "CreatedBy", "OwnerId", "OwnerDeptId",
    "CreatedTime", "ModifiedBy", "ModifiedTime", "WorkflowInstanceId", "Status",
    "ParentObjectId", "ParentPropertyName", "ParentIndex",
    "ValueIndex", "PropertyValue",
    "State", "SeqNo",
)
# ② MySQL 保留关键字（8.0）：字段编码=列名，列名撞上它会让 SQL 报表/高级数据源里的语句失败。
MYSQL_RESERVED = (
    "ACCESSIBLE", "ADD", "ALL", "ALTER", "ANALYZE", "AND", "AS", "ASC", "ASENSITIVE",
    "BEFORE", "BETWEEN", "BIGINT", "BINARY", "BLOB", "BOTH", "BY", "CALL", "CASCADE",
    "CASE", "CHANGE", "CHAR", "CHARACTER", "CHECK", "COLLATE", "COLUMN", "CONDITION",
    "CONSTRAINT", "CONTINUE", "CONVERT", "CREATE", "CROSS", "CUBE", "CUME_DIST",
    "CURRENT_DATE", "CURRENT_TIME", "CURRENT_TIMESTAMP", "CURRENT_USER", "CURSOR",
    "DATABASE", "DATABASES", "DAY_HOUR", "DAY_MICROSECOND", "DAY_MINUTE", "DAY_SECOND",
    "DEC", "DECIMAL", "DECLARE", "DEFAULT", "DELAYED", "DELETE", "DENSE_RANK", "DESC",
    "DESCRIBE", "DETERMINISTIC", "DISTINCT", "DISTINCTROW", "DIV", "DOUBLE", "DROP",
    "DUAL", "EACH", "ELSE", "ELSEIF", "EMPTY", "ENCLOSED", "ESCAPED", "EXCEPT", "EXISTS",
    "EXIT", "EXPLAIN", "FALSE", "FETCH", "FIRST_VALUE", "FLOAT", "FLOAT4", "FLOAT8",
    "FOR", "FORCE", "FOREIGN", "FROM", "FULLTEXT", "FUNCTION", "GENERATED", "GET",
    "GRANT", "GROUP", "GROUPING", "GROUPS", "HAVING", "HIGH_PRIORITY",
    "HOUR_MICROSECOND", "HOUR_MINUTE", "HOUR_SECOND", "IF", "IGNORE", "IN", "INDEX",
    "INFILE", "INNER", "INOUT", "INSENSITIVE", "INSERT", "INT", "INT1", "INT2", "INT3",
    "INT4", "INT8", "INTEGER", "INTERVAL", "INTO", "IO_AFTER_GTIDS", "IO_BEFORE_GTIDS",
    "IS", "ITERATE", "JOIN", "JSON_TABLE", "KEY", "KEYS", "KILL", "LAG", "LAST_VALUE",
    "LATERAL", "LEAD", "LEADING", "LEAVE", "LEFT", "LIKE", "LIMIT", "LINEAR", "LINES",
    "LOAD", "LOCALTIME", "LOCALTIMESTAMP", "LOCK", "LONG", "LONGBLOB", "LONGTEXT",
    "LOOP", "LOW_PRIORITY", "MASTER_BIND", "MASTER_SSL_VERIFY_SERVER_CERT", "MATCH",
    "MAXVALUE", "MEDIUMBLOB", "MEDIUMINT", "MEDIUMTEXT", "MIDDLEINT",
    "MINUTE_MICROSECOND", "MINUTE_SECOND", "MOD", "MODIFIES", "NATURAL", "NOT",
    "NO_WRITE_TO_BINLOG", "NTH_VALUE", "NTILE", "NULL", "NUMERIC", "OF", "ON",
    "OPTIMIZE", "OPTIMIZER_COSTS", "OPTION", "OPTIONALLY", "OR", "ORDER", "OUT", "OUTER",
    "OUTFILE", "OVER", "PARTITION", "PERCENT_RANK", "PRECISION", "PRIMARY", "PROCEDURE",
    "PURGE", "RANGE", "RANK", "READ", "READS", "READ_WRITE", "REAL", "RECURSIVE",
    "REFERENCES", "REGEXP", "RELEASE", "RENAME", "REPEAT", "REPLACE", "REQUIRE",
    "RESIGNAL", "RESTRICT", "RETURN", "REVOKE", "RIGHT", "RLIKE", "ROW", "ROWS",
    "ROW_NUMBER", "SCHEMA", "SCHEMAS", "SECOND_MICROSECOND", "SELECT", "SENSITIVE",
    "SEPARATOR", "SET", "SHOW", "SIGNAL", "SMALLINT", "SPATIAL", "SPECIFIC", "SQL",
    "SQLEXCEPTION", "SQLSTATE", "SQLWARNING", "SQL_BIG_RESULT", "SQL_CALC_FOUND_ROWS",
    "SQL_SMALL_RESULT", "SSL", "STARTING", "STORED", "STRAIGHT_JOIN", "SYSTEM", "TABLE",
    "TERMINATED", "THEN", "TINYBLOB", "TINYINT", "TINYTEXT", "TO", "TRAILING", "TRIGGER",
    "TRUE", "UNDO", "UNION", "UNIQUE", "UNLOCK", "UNSIGNED", "UPDATE", "USAGE", "USE",
    "USING", "UTC_DATE", "UTC_TIME", "UTC_TIMESTAMP", "VALUES", "VARBINARY", "VARCHAR",
    "VARCHARACTER", "VARYING", "VIRTUAL", "WHEN", "WHERE", "WHILE", "WINDOW", "WITH",
    "WRITE", "XOR", "YEAR_MONTH", "ZEROFILL",
)
# 大小写不敏感：氚云列名与 MySQL 关键字都不区分大小写。
_RESERVED_LOWER = {k.lower() for k in (PLATFORM_RESERVED + MYSQL_RESERVED)}

# 兼容旧名（平台自带编码）
RESERVED_KEYS = PLATFORM_RESERVED


def is_reserved(key):
    """编码（字段/子表列/表单）是否撞上平台自带编码或 MySQL 保留字（不区分大小写）。"""
    return str(key or "").strip().lower() in _RESERVED_LOWER


# 公式正文里的字段引用（{字段编码}），用于构建前校验引用的字段存在
_FORMULA_REF_RE = re.compile(r"\{([^{}]+)\}")


def _check_reserved(key, who=""):
    """编码(字段 / 子表列 / 表单 / 子表)不能占用平台自带编码或 MySQL 保留字。

    **任何时候都拦**(不像命名规则对「线上已建表」放过):这些编码会成为数据库的列名/表名,
    撞上保留字会让氚云建表或在 SQL 报表/高级数据源里报底层错误,与线上是否已建无关。
    """
    if is_reserved(key):
        raise ValueError(
            "%s: 编码 %r 是平台自带编码或 MySQL 保留字,不能自己命名——平台每张表单/子表本来就有"
            "这些列(主表 ObjectId/Name/Status…;子表 ParentObjectId/ParentPropertyName/ParentIndex;"
            "中间表 ValueIndex/PropertyValue),重名会出问题;MySQL 保留字(status/order/group/desc/"
            "key/rank/system/values/index… )还会让 SQL 报表与高级数据源失败。换业务别名即可"
            "(如 status → billStatus、order → saleOrder)。系统字段的引用方式:申请人在 layout 里写"
            " \"OwnerId\"、申请部门写 \"OwnerDeptId\"(配 useOwner: true),其余由平台自动维护。"
            % (who or "表单", key))


# 字段编码命名规则（客户 2026-09-17 口径）：只允许英文字母和数字，必须字母开头，
# 不能有下划线。控件 key / 子表 key / 子表列 key / 表单 key 全按这条走。
KEY_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


def _check_key_name(key, who=""):
    """字段编码命名：字母开头、只含字母数字、不许下划线。"""
    if not KEY_NAME_RE.match(str(key)):
        raise ValueError(
            "%s: 编码 %r 不合规 —— 只能用英文字母和数字、必须以字母开头，不能有下划线。"
            "下划线改驼峰即可：plan_begin → planBegin、stock_left → stockLeft。"
            % (who or "表单", key))


def _keys_frozen(registry, sheet_key):
    """该表线上已建 → 字段编码在平台上已经固定，key 命名规则只能放过
    （改 key = 平台上另起一列，老列的数据留在原处）。"""
    return bool(((registry or {}).get(sheet_key) or {}).get("created"))


def _formula_refs(text):
    """公式正文 → 引用到的字段编码列表（按出现顺序去重）。
    如 "{price}*{qty}" → ["price", "qty"]。"""
    out = []
    for m in _FORMULA_REF_RE.finditer(text or ""):
        r = m.group(1).strip()
        if r and r not in out:
            out.append(r)
    return out


def _build_control(proj_dir, spec, registry, app_code, self_code="", strict=True):
    """strict=False：本表线上已建，字段编码已固定，命名规则放过（见 _keys_frozen）。"""
    t = spec["type"]
    key = spec.get("key") or (SEQNO_KEY if t in ("seq_no", "seqno") else None)
    if not key:
        raise ValueError("控件缺 key（type=%r）；只有流水号可省，编码恒为 %s"
                         % (t, SEQNO_KEY))
    if t not in ("seq_no", "seqno"):        # 流水号的编码本来就是 SeqNo
        if strict:
            # 保留字与命名规则一样:仅**未建表**时拦(已建表线上列已固定,改名=另起一列)
            _check_reserved(key)
            _check_key_name(key)
    if spec.get("assoc") and t not in ("dropdown", "query"):
        raise ValueError("%s: %s 不支持 assoc（选项来自另一张表只有下拉实证过，"
                         "radio/checkbox_list 不能联动）" % (key, t))
    label = spec.get("label") or ("流水号" if t in ("seq_no", "seqno") else key)
    common = {"required": spec.get("required", False),
              "readonly": spec.get("readonly", False)}
    if t == "text":
        return C.text(key, label, default=spec.get("default", ""),
                      placeholder=spec.get("placeholder", ""),
                      rule=_rule(spec))
    if t == "textarea":
        return C.textarea(key, label, rows=spec.get("rows", 3),
                          default=spec.get("default", ""))
    if t == "number":
        return C.number(key, label, decimal=spec.get("decimal", 0),
                        default=spec.get("default"), rule=_rule(spec))
    if t == "date":
        return C.date_field(key, label,
                            datetime_mode=spec.get("datetime", "yyyy-MM-dd"),
                            rule=_rule(spec))
    if t == "switch":
        return C.switch_field(key, label, checked=bool(spec.get("checked", False)))
    if t == "radio":
        return C.radio(key, label, _options(proj_dir, spec),
                       default=spec.get("default", ""))
    if t == "dropdown":
        if spec.get("assoc"):
            return _assoc_dropdown(spec, registry, app_code)
        return C.dropdown(key, label, _options(proj_dir, spec),
                          default=spec.get("default", ""), rule=_rule(spec))
    if t == "checkbox_list":
        return C.checkbox_list(key, label, _options(proj_dir, spec),
                               default_items=spec.get("defaults", ()))
    if t == "member":
        return C.member(key, label, multi=bool(spec.get("multi", False)),
                        rule=_rule(spec))
    if t == "department":
        return C.department(key, label, multi=bool(spec.get("multi", False)),
                            rule=_rule(spec))
    if t == "query":
        code = _assoc_code(spec.get("assoc"), registry, key)
        return C.query(key, label, code, app_package=app_code,
                       multi=bool(spec.get("multi", False)), rule=_rule(spec))
    if t in ("seq_no", "seqno"):
        if spec.get("default") or spec.get("dict") or spec.get("options"):
            raise ValueError("%s: 流水号不能给 default/dict/options（值由平台按规则发号）"
                             % key)
        try:
            inc = int(spec.get("increment", 8))
        except (TypeError, ValueError):
            raise ValueError("%s: 流水号 increment 须为整数（位数，如 8）" % key)
        mode = spec.get("datetime", "YYYY")
        if not isinstance(mode, str) or not mode:
            raise ValueError("%s: 流水号 datetime 须为字符串（如 YYYY/YYYYMM/YYYYMMDD）"
                             % key)
        return C.seqno(key, label, prefix=spec.get("prefix", ""),
                       datetime_mode=mode, increment=inc)
    if t in ("image", "photo"):
        return C.photo(key, label, multiple=bool(spec.get("multiple", False)),
                       camera_only=bool(spec.get("cameraOnly", False)),
                       watermark=bool(spec.get("watermark", False)),
                       compression=bool(spec.get("compression", False)),
                       rule=_rule(spec))
    if t == "attachment":
        try:
            mb = int(spec.get("maxSize", 10))
        except (TypeError, ValueError):
            raise ValueError("%s: 附件的 maxSize 须为整数（MB）" % key)
        return C.attachment(key, label, max_upload_size=mb, rule=_rule(spec))
    if t in ("location", "map"):
        try:
            meters = int(spec.get("meters", 500))
        except (TypeError, ValueError):
            raise ValueError("%s: 位置的 meters 须为整数（米）" % key)
        return C.location(key, label, meters=meters,
                          pc_enabled=bool(spec.get("pcEnabled", True)),
                          editable=bool(spec.get("editable", False)),
                          rule=_rule(spec))
    if t == "address":
        mode = spec.get("areaMode", "P-C-T")
        if mode != "P-C-T":
            raise ValueError("%s: 地址的 areaMode 目前只实证过 P-C-T（省-市-县）" % key)
        return C.area(key, label, area_mode=mode,
                      show_detail=bool(spec.get("showDetail", True)),
                      rule=_rule(spec))
    if t == "formula":
        rule = spec.get("rule")
        if not isinstance(rule, str) or not rule.strip():
            raise ValueError("%s: 公式控件必须有 rule —— 公式正文，字段引用写花括号里的"
                             "**字段编码**（如 \"{price}*{qty}\"）；加减乘除与括号照引擎语法"
                             % key)
        try:
            dec = int(spec.get("decimal", 0))
        except (TypeError, ValueError):
            raise ValueError("%s: 公式控件 decimal 须为整数（小数位）" % key)
        # bindType 只实证 number（C.formula 里拦其余档位）；引用字段的存在性在
        # _build_json_sheet 里校验（那里才有本表全部字段）
        return C.formula(key, label, rule.strip(),
                         bind_type=spec.get("bindType", "number"), decimal=dec,
                         rule_hide=_rule(spec))
    if t == "rollup":
        return _build_rollup(spec, registry, key, label, self_code, proj_dir)
    raise ValueError("未知控件类型 %r（%s）" % (t, key))


def _standalone(ctl, extras_by_key):
    """是否必须**单独成行且作 FormLayout 顶层条目**：布局项（分组标题/描述，key 是 GUID、
    本就不进 Properties）、公式控件（type 304，线上样本是顶层 GUID 条目）与汇总控件
    （type 501，线上样本同样顶层；进一行多列未实证）。"""
    return ctl.get("DefKey") in extras_by_key or bool(ctl.get("Standalone"))


def _resolve_layout(sheet, seq_default, fields_by_key, use_owner,
                    extras_by_key=None, sub_keys=()):
    """layout 定义 → newbuilder.build_biz_sheet 的行序列。
    元素 = 控件 dict（整行单个）或控件 list（一行多列 ≤4）；
    "OwnerId"/"OwnerDeptId" 字符串须 useOwner=true 才可用。
    布局项（分组标题/描述）**只能单独成行**，且与 UI 样本一致作顶层条目
    （extras_by_key 按定义侧短码 DefKey 索引；key 用 GUID 见 controls.layout_key）。
    子表 key 不可进 layout：子表整行自动排在表单底部。"""
    extras_by_key = extras_by_key or {}
    owner = None
    if use_owner:
        owner = dict(zip(("OwnerId", "OwnerDeptId"), owner_presets()))
    lay = sheet.get("layout")
    if lay is None:
        if use_owner:
            raise ValueError("%s: useOwner=true 时必须显式 layout（行内写 OwnerId/OwnerDeptId）"
                             % sheet.get("key"))
        return list(seq_default)                   # 全 flat：按定义顺序每控件一行
    if lay == "auto4":                             # 每 4 个控件一行；布局项独占一行
        rows, cur = [], []

        def flush():
            if cur:
                rows.append(list(cur))
                del cur[:]

        if use_owner:
            cur.extend([owner["OwnerId"], owner["OwnerDeptId"]])
        for item in seq_default:
            if _standalone(item, extras_by_key):   # 布局项/公式：独占一行且是**顶层条目**
                flush()
                rows.append(item)
                continue
            cur.append(item)
            if len(cur) == 4:
                flush()
        flush()
        return rows

    def resolve_one(item):
        if isinstance(item, str):
            if item in fields_by_key:
                return fields_by_key[item]
            if item in extras_by_key:
                return extras_by_key[item]
            if item in sub_keys:
                raise ValueError("%s: 子表 %r 不占一行多列，自动排在表单底部（勿写进 layout）"
                                 % (sheet.get("key"), item))
            if owner and item in owner:
                return owner[item]
            raise ValueError("%s: layout 行内未知 key %r" % (sheet.get("key"), item))
        if isinstance(item, dict):
            if "owner" in item:
                if not use_owner:
                    raise ValueError("layout 含 owner 元素但 useOwner 缺省")
                if str(item["owner"]).lower() in ("user", "owner"):
                    return owner["OwnerId"]
                return owner["OwnerDeptId"]
            if "key" in item and "type" not in item:    # 行内控件对象（仅 key 定位）
                return fields_by_key[item["key"]]
        raise ValueError("layout 行内只能放字段 key 字符串: %r" % (item,))

    seq = []
    for row in lay:
        if not isinstance(row, list):
            raise ValueError("layout 须为行数组 [[k1,k2,...], ...] 或 'auto4'")
        if len(row) > 4:
            raise ValueError("一行多列最多 4 个控件: %r" % row)
        row_ctl = [resolve_one(i) for i in row]
        if len(row_ctl) > 1 and any(c.get("DefKey") in extras_by_key for c in row_ctl):
            raise ValueError("%s: 布局项（分组标题/描述）只能单独成行，不能进一行多列: %r"
                             % (sheet.get("key"), row))
        if len(row_ctl) > 1 and any(c.get("Standalone") for c in row_ctl):
            raise ValueError("%s: 公式/汇总控件只能单独成行（线上样本是 FormLayout 顶层"
                             "条目，进一行多列未实证）: %r" % (sheet.get("key"), row))
        # 布局项/公式与 UI 样本一致作 **顶层条目**（不是 1 子项的 102 行）——它们本来
        # 就只能独占一行；普通单控件行保持既有 102 行包裹（已建成的表就是这么建的，
        # 改了会让 verify 行组期望对不上）
        seq.append(row_ctl[0] if len(row_ctl) == 1
                   and _standalone(row_ctl[0], extras_by_key) else row_ctl)
    return seq


def _build_subtable(sheet_key, spec, proj_dir, registry, app_code, strict=True):
    """子表 spec → {key,label,code,fixed,cols}。
    code：registry[sheet_key]["subs"][subkey]["code"]（child schema 编码，
    建表前由 sheet_sub_specs 预注册；离线 check 未注册时留空占位）。"""
    sk = spec["key"]
    # 子表编码 = 数据库表名 i_<sk>:命名规则与保留字都仅**未建表**时拦(见 strict 说明)
    if strict:
        _check_reserved(sk, "子表")
        _check_key_name(sk, "子表")
    label = spec.get("label") or sk
    if not isinstance(spec.get("columns"), list) or not spec["columns"]:
        raise ValueError("子表 %r.%s 缺 columns 列表" % (sheet_key, sk))
    try:
        fixed = int(spec.get("fixed", 1))
    except (TypeError, ValueError):
        raise ValueError("子表 %r.%s 的 fixed 须为数字" % (sheet_key, sk))
    cols = []
    for csp in spec["columns"]:
        ct, ck = csp.get("type"), csp.get("key")
        if ct not in GRID_COL_TYPES:
            raise ValueError("子表 %r.%s 列 %r: 类型 %r 不支持（子表列支持 %s）"
                             "；成员/部门/关联/嵌套子表/位置/地址/流水号/布局项作列未实证"
                             "——列节点照抄主表同款的 Options 形状，这几类没有可照抄的实证样本"
                             % (sheet_key, sk, ck, ct, "/".join(GRID_COL_TYPES)))
        if csp.get("assoc"):
            raise ValueError("子表 %r.%s 列 %r: 列内 assoc（联动下拉）未实证，暂不支持"
                             % (sheet_key, sk, ck))
        cols.append(_build_control(proj_dir, csp, registry, app_code, strict=strict))
    code = (((registry or {}).get(sheet_key) or {}).get("subs") or {}
            ).get(sk, {}).get("code", "")
    return {"key": sk, "label": label, "code": code, "fixed": fixed, "cols": cols}


def _group_specs(proj_dir):
    """groups.json（可选）→ 有序分组清单 [{name, icon}]；无文件 → None。
    文件为数组或 {"groups": [...]}；条目 = 字符串或 {name}。顺序 = 应用菜单顺序。"""
    gp = os.path.join(proj_dir, "groups.json")
    if not os.path.isfile(gp):
        return None
    d = _read_json(gp)
    lst = d if isinstance(d, list) else (d or {}).get("groups")
    if not isinstance(lst, list):
        raise ValueError("groups.json 须为数组或 {\"groups\": [...]}: %r" % d)
    out = []
    for it in lst:
        if isinstance(it, str) and it.strip():
            out.append({"name": it, "icon": ""})
        elif isinstance(it, dict) and str(it.get("name") or "").strip():
            out.append({"name": str(it["name"]).strip(),
                        "icon": str(it.get("icon") or "")})
        else:
            raise ValueError("groups.json 条目须为字符串或 {name}: %r" % (it,))
    names = [g["name"] for g in out]
    if len(set(names)) != len(names):
        raise ValueError("groups.json 分组名重复: %s" % names)
    return out


def group_order(proj_dir):
    """有序分组名清单；无 groups.json → None（分组不校验、按表单出现顺序归组）。"""
    gs = _group_specs(proj_dir)
    return None if gs is None else [g["name"] for g in gs]


def sheet_sub_specs(path):
    """扫 sheets/<key>.json 顶层子表 spec 列表（建表预注册 child 编码用，
    不加载完整控件树、不联网）。"""
    return [c for c in _read_json(path).get("controls", [])
            if isinstance(c, dict) and c.get("type") == "subtable"]


def _build_json_sheet(path, proj_dir, app_code, registry, group_specs=None):
    sheet = _read_json(path)
    key = os.path.splitext(os.path.basename(path))[0]
    use_owner = bool(sheet.get("useOwner", False))
    group = str(sheet.get("group") or "").strip()
    if group and group_specs is not None \
            and group not in [g["name"] for g in group_specs]:
        raise ValueError("%s: 分组 %r 未在 groups.json 声明（现有 %s）"
                         % (key, group, [g["name"] for g in group_specs]))
    # 表单编码 = 数据库表名 i_<key> / schemaCode:命名规则与保留字都仅**未建表**时拦
    # (线上已建表编码已固定,改 key = 另起一列/新表,老数据留在原处)。
    strict = not _keys_frozen(registry, key)
    if strict:
        _check_reserved(key, "表单 key")
        _check_key_name(key, "表单 key")
    controls, subs, extras, seq_default, fields_by_key, assoc = [], [], [], [], {}, {}
    extras_by_key = {}
    # 本表编码：汇总控件的"本表字段引用"要写成 <本表编码>.<字段>（线上样本同款）。
    # 建表时会把本次要用的编码先写进 registry（check 是占位码）——
    # registry 还没有就留空，报错由 _build_rollup 给出（只在真用到 ref 时才报）。
    self_code = ((registry or {}).get(key) or {}).get("code") or ""
    for spec in sheet.get("controls", []):
        if spec.get("type") == "subtable":
            subs.append(_build_subtable(key, spec, proj_dir, registry, app_code,
                                        strict=strict))
            continue
        if spec.get("type") in LAYOUT_TYPES:          # 分组标题 / 描述：布局项
            ctl = _build_layout_item(spec)
            # 布局项的 Key 是 uuid5(短码)（见 controls.layout_key），定义侧短码在 DefKey：
            # layout 行/去重都按短码走，回读与 verify 比对按 GUID key 走（同线上）
            if ctl["DefKey"] in fields_by_key or ctl["DefKey"] in extras_by_key:
                raise ValueError("%s: 控件 key 重复 %r" % (key, ctl["DefKey"]))
            extras.append(ctl)
            extras_by_key[ctl["DefKey"]] = ctl
            seq_default.append(ctl)
            continue
        ctl = _build_control(proj_dir, spec, registry, app_code, self_code,
                             strict=strict)
        # OwnerId/OwnerDeptId 等平台自带编码在 _build_control 里已拦（_check_reserved）
        if ctl["Key"] in fields_by_key or ctl["Key"] in extras_by_key:
            raise ValueError("%s: 控件 key 重复 %r" % (key, ctl["Key"]))
        controls.append(ctl)
        seq_default.append(ctl)
        fields_by_key[ctl["Key"]] = ctl
        if spec.get("type") in ("query", "dropdown") and spec.get("assoc"):
            # 注册 assoc 关系（check/verify 展示用）；构建载荷侧 query 走 kwargs、
            # 联动下拉走 Options.BOSchemaCode，此处只需登记不重复解析
            assoc[ctl["Key"]] = {"assoc_schema_code":
                                 ctl["Options"].get("BOSchemaCode", "")}
    # 联动下拉的 filter 动态引用（ref）必须指向本表已有字段（级联链上源）
    for spec in sheet.get("controls", []):
        if spec.get("type") != "dropdown" or not spec.get("assoc"):
            continue
        for it in spec.get("filter") or []:
            ref = (it or {}).get("ref")
            if ref is not None and ref not in fields_by_key:
                raise ValueError("%s: filter 动态引用 %r 不是本表字段"
                                 "（ref 写本表单 controls 的 key）" % (key, ref))
    # 公式控件的字段引用必须是**本表字段**（跨主表/子表的公式平台不支持；
    # 引擎里的写法就是裸 {字段编码}，子表列得写 dotted 码、未实证故不开放）
    for spec in sheet.get("controls", []):
        if spec.get("type") != "formula":
            continue
        for ref in _formula_refs(spec.get("rule") or ""):
            if ref not in fields_by_key:
                raise ValueError(
                    "%s: 公式 %r 引用的 {%s} 不是本表字段。本表字段: %s"
                    "（子表列/关联表的字段引用未实证，写不进去）"
                    % (key, spec.get("key") or "", ref,
                       ", ".join(sorted(fields_by_key)) or "（无）"))
    # 汇总控件的筛选条件里 ref（本表字段动态引用）同样必须是本表字段
    for spec in sheet.get("controls", []):
        if spec.get("type") != "rollup":
            continue
        for grp in (spec.get("filters") or []):
            for it in (grp if isinstance(grp, list) else [grp]):
                ref = (it or {}).get("ref")
                if ref is not None and ref not in fields_by_key:
                    raise ValueError("%s: 汇总控件 %r 的筛选条件是拿**源表字段**跟本表 "
                                     "ref 比，ref 必须是本表控件 key —— %r 不是。"
                                     "本表字段: %s"
                                     % (key, spec.get("key") or "", ref,
                                        ", ".join(sorted(fields_by_key)) or "（无）"))
    layout = _resolve_layout(sheet, seq_default, fields_by_key, use_owner,
                             extras_by_key=extras_by_key,
                             sub_keys=tuple(s["key"] for s in subs))
    # 已建表放过的不合规编码点名报出来（防止照旧风格往这张表再加字段）
    legacy_keys = []
    if not strict:
        cand = [key] + [c["Key"] for c in controls] \
            + [s["key"] for s in subs] + [c["Key"] for s in subs for c in s["cols"]]
        legacy_keys = [k for k in cand if not KEY_NAME_RE.match(str(k))]
    return {"key": key,
            "title": sheet.get("title") or key,
            "name_schema": sheet.get("nameSchema") or "",
            "fields": controls, "layout": layout, "assoc": assoc,
            "useOwner": use_owner, "group": group, "extras": extras,
            "subs": subs, "legacy_keys": legacy_keys,
            "_source": os.path.relpath(path, proj_dir)}


def _legacy_loaders(proj_dir, app_code, registry):
    """旧版 forms.py（奥驰样式）→ {key: loader}。forms.py 保持自身约定：
    BUILDERS 表 + build(key, app_code, rule_table_code=, apply_table_code=)"""
    forms_path = os.path.join(proj_dir, "forms.py")
    # legacy forms.py 顶层 import controls —— 新位置在 h3design/；兼容旧工程同目录写法
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # h3design/
    sys.path.insert(0, proj_dir)
    try:
        mod_name = "_legacy_forms_" + str(abs(hash(forms_path)))
        spec = importlib.util.spec_from_file_location(mod_name, forms_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
        sys.path.pop(0)
    builders = getattr(mod, "BUILDERS")
    t1 = ((registry or {}).get("table1") or {}).get("code", "")
    t4 = ((registry or {}).get("table4") or {}).get("code", "")
    out = {}
    for key in builders:
        def loader(key=key):
            return mod.build(key, app_code, rule_table_code=t1,
                             apply_table_code=t4)
        out[key] = loader
    return out


def load_project(proj_dir, app_code, registry):
    """项目全部表单 loader。JSON(sheets/*.json) 优先，legacy forms.py 合并。"""
    out = {}
    sj = os.path.join(proj_dir, "sheets")
    gspecs = _group_specs(proj_dir)
    if os.path.isdir(sj):
        for fn in sorted(os.listdir(sj)):
            if fn.endswith(".json"):
                path = os.path.join(sj, fn)
                out[os.path.splitext(fn)[0]] = (
                    lambda p=path: _build_json_sheet(p, proj_dir, app_code,
                                                     registry, gspecs))
    if os.path.isfile(os.path.join(proj_dir, "forms.py")):
        out.update(_legacy_loaders(proj_dir, app_code, registry))
    if not out:
        raise ValueError("项目 %r 没有定义：缺 sheets/*.json 或 forms.py" % proj_dir)
    return out
