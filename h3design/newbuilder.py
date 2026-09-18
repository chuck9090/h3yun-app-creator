# -*- coding: utf-8 -*-
"""新引擎 SaveForm 载荷构造：从设计态控件列表生成 SchemaStr/BizSheetStr。
模板逐字对照 UI 真实保存载荷（fixtures/types7_ui_save_payload.json，7 类控件全覆盖）。
字段编码用自定义语义短码（rulename/seqlen 等，已实证可持久化）。"""
import datetime
import json
import uuid

from . import controls as C

# ---- SchemaStr.Properties 的 ControlKey 数值（权威：UI 保存载荷逐字）----
NEW_CTL = {
    "FormTextBox": 14,
    "FormNumber": 7,
    "FormTextArea": 13,
    "FormDateTime": 5,
    "FormDropDownList": 14,        # 下拉/单选/复选与文本框同为字符串存储
    "FormRadioButtonList": 14,
    "FormCheckboxList": 14,
    "FormCheckbox": 1,             # 开关（是/否）布尔
    "FormUser": 26,                # 26=单选（人员/部门同值，v1 读回实证）
    "FormSeqNo": 14,               # 流水号：字符串存储，线上样本 F=14（2026-09-11）
    "FormPhoto": 23,               # 图片（类型试验线上样本逐字）
    "FormAttachment": 24,          # 附件
    "FormMap": 55,                 # 位置
    "FormAreaSelect": 56,          # 地址
    "FormQuery": 50,
    "FormMultiQuery": 51,
    "FormMultiUser": 27,           # 27=多选（人员/部门同值）
    "FormDepartment": 26,
    "FormMultiDepartment": 27,
    "FormGridView": 41,          # 子表主属性（key=child schema 编码；子列=标准存储类型）
    "FormFormula": 7,            # 公式控件：存储型同数字（线上样本 F0000026 逐字）
    "FormRollup": 7,             # 汇总控件：存储型同数字（线上样本 F0000029 逐字）
}

# SchemaStr.Properties 每字段的公共空键（含类型字段名，类型特有键在 EXTRA/下方映射）
EMPTY_STD = ["AssociationSchemaCode", "IsRelatedMember", "DataDictItemName",
             "OptionalValues", "DateTimeMode", "ComputationRule", "DisplayRule",
             "AssociationFilter", "UnitSelectionRange", "DefaultValue",
             "MappingField", "IsFormula", "IsRollup", "LocationRangeLimit",
             "Summary"]

EXTRA_BY_TYPE = {
    "FormTextBox": {"NoRepeat": False},
    "FormNumber": {"ShowMode": "0", "RollupSettings": [], "DecimalPlaces": -1,
                   "DataFormatType": "0", "ShowBarChart": False},
    "FormCheckbox": {"DefaultValue": "false"},
    "FormDropDownList": {"SelectShowMode": 0},
    "FormRadioButtonList": {"SelectShowMode": 0},
    "FormCheckboxList": {"SelectShowMode": "0"},
}

# 新控件（流水号/图片/附件/位置/地址）的 Properties **少几个公共键** ——
# 逐字对照线上样本（fixtures/types7_ui_save_payload.json，2026-09-11 类型试验）
PROP_DROP_KEYS = {
    "FormSeqNo": ("ComputationRule", "DisplayRule"),
    "FormPhoto": ("ComputationRule",),
    "FormAttachment": ("ComputationRule",),
    "FormMap": ("ComputationRule", "LocationRangeLimit"),
    "FormAreaSelect": ("ComputationRule",),
    "FormRollup": ("ComputationRule",),      # 汇总控件没有公式正文那个键
}
# 这些类型 DefaultValue 线上是空串（文本框/选项类的 None 语义不适用）
PROP_EMPTY_DEFAULT = ("FormSeqNo", "FormPhoto", "FormAttachment", "FormMap")


def is_field(ctl):
    """是否为**字段控件**：布局项（分组标题 101 / 描述 103）不进 SchemaStr.Properties。
    以 ControlKey 判定（分组标题线上根本不带 ControlKey）。"""
    ck = (ctl.get("Options") or {}).get("ControlKey")
    return ck not in ("FormGroupTitle", "FormDescription")


def _items_json(opt):
    items = opt.get("DefaultItems") or []
    return json.dumps(items, ensure_ascii=False) if items else ""


def prop_entry(ctl, assoc_schema_code="", assoc_schema_info=None, assoc_fields=None,
               app_package=""):
    """SchemaStr.Properties[code] 条目。ctl 为设计态控件 {Key, Options{...}}"""
    opt = ctl.get("Options") or {}
    ckey = opt.get("ControlKey")
    e = {"ControlKey": NEW_CTL.get(ckey, 14),
         "DisplayName": opt.get("DisplayName", "")}
    for k in EMPTY_STD:
        e[k] = ""
    e["IsRelatedMember"] = False
    e["IsFormula"] = False
    e["IsRollup"] = False
    e["LocationRangeLimit"] = None
    e.update(EXTRA_BY_TYPE.get(ckey, {}))
    if ckey == "FormTextBox" and opt.get("NoRepeat") is not None:
        e["NoRepeat"] = opt["NoRepeat"]
    if ckey == "FormDateTime":
        e["DateTimeMode"] = opt.get("DateTimeMode", "")
    if ckey == "FormCheckbox":
        # UI 样本：无勾选发 "false"；勾选态发 "true"
        e["DefaultValue"] = opt.get("DefaultValue") or "false"
    if ckey in ("FormDropDownList", "FormRadioButtonList", "FormCheckboxList"):
        if ckey == "FormDropDownList" and opt.get("DataSource") == "Association":
            # 联动下拉（选项来自另一张表）：Properties 只落关联三键 + 干净空选项。
            # 逐字对照线上样本 F0000021 —— 无 DataSource/BOSchemaInfo/AssociationFields 键；
            # AssociationFilter 在此侧是纯文本（FormLayout options 侧才是 {Rule:..} 字典）
            e["AssociationSchemaCode"] = opt.get("BOSchemaCode", "")
            e["MappingField"] = opt.get("MappingField", "")
            af = opt.get("AssociationFilter") or {}
            e["AssociationFilter"] = (af.get("Rule", "") if isinstance(af, dict)
                                      else (str(af) if af else ""))
            e["OptionalValues"] = ""      # 占位选项只发生在 UI 改型，工厂直建不带
            e["DefaultValue"] = None
        else:
            e["OptionalValues"] = _items_json(opt)
            dv = opt.get("DefaultValue")
            # UI 语义：复选无默认值=""/null，下拉/单选默认 null
            e["DefaultValue"] = dv if dv else ("" if ckey == "FormCheckboxList" else None)
    if ckey == "FormFormula":
        # 公式控件 Properties（对照线上 F0000026）：ComputationRule = **纯文本**（不是
        # {Rule:..} 字典）；IsFormula=true；末尾多 Referenceable/DataFormatType/
        # DecimalPlaces/ShowMode 四键（DataFormatType 是空串，数字控件才是 "0"），
        # 且**不带** RollupSettings/ShowBarChart/PlaceHolder/DataLink* 那套。
        cr = opt.get("ComputationRule") or {}
        e["ComputationRule"] = cr.get("Rule", "") if isinstance(cr, dict) else (cr or "")
        e["IsFormula"] = True
        e["Referenceable"] = bool(opt.get("Referenceable", True))
        e["DataFormatType"] = ""
        e["DecimalPlaces"] = int(opt.get("DecimalPlaces") or 0)
        e["ShowMode"] = int(opt.get("ShowMode") or 0)
    if ckey == "FormRollup":
        # 汇总控件 Properties（对照线上 F0000029）：RollupSettings 与 FormLayout 侧**同值**；
        # ShowMode 是 **int**（数字控件是字符串 "0"）、DataFormatType 是空串（数字控件 "0"）、
        # 末尾落 RollupSettings + DecimalPlaces；**没有** ComputationRule/ShowBarChart。
        e["IsRollup"] = True
        e["ShowMode"] = int(opt.get("ShowMode") or 0)
        e["DataFormatType"] = ""
        e["RollupSettings"] = opt.get("RollupSettings") or []
        e["DecimalPlaces"] = int(opt.get("DecimalPlaces") or 0)
    if ckey in PROP_EMPTY_DEFAULT:
        e["DefaultValue"] = ""
    if ckey == "FormAreaSelect":
        # 地址：Properties 侧 DefaultValue 是 JSON 串 + 多一个 AreaMode 键
        dv = opt.get("DefaultValue")
        e["DefaultValue"] = json.dumps(dv, ensure_ascii=False,
                                       separators=(",", ":")) \
            if isinstance(dv, dict) else (dv or "")
        e["AreaMode"] = opt.get("AreaMode", "P-C-T")
    if ckey == "FormQuery" and assoc_schema_code:
        e["AssociationSchemaCode"] = assoc_schema_code
        e["AssociationSchemaInfo"] = assoc_schema_info or json.dumps(
            {"AppPackage": app_package, "AppGroup": "",
             "AppMenu": assoc_schema_code, "IsChildSchema": False},
            ensure_ascii=False, separators=(",", ":"))
        e["AssociationFields"] = assoc_fields or json.dumps(
            {"isDefault": True, "fieldSetting": []}, ensure_ascii=False,
            separators=(",", ":"))
    rule = opt.get("DisplayRule")
    if isinstance(rule, dict) and rule.get("Rule"):
        # Properties.DisplayRule = 规则文本（条件串），如 {probe}=="xxx"
        e["DisplayRule"] = rule["Rule"]
    for k in PROP_DROP_KEYS.get(ckey, ()):     # 键集差异：线上样本没有这些键
        e.pop(k, None)
    return e


def _sub_prop(sub):
    """子表主条目（ControlKey 41）。逐字对照 UI 保存样本：
    {'ControlKey':41,'DisplayName':...,AssociationSchemaCode/IsRelatedMember/
    DataDictItemName/OptionalValues/DateTimeMode/DisplayRule/AssociationFilter/
    UnitSelectionRange/NameItems/MappingField/ShowFixedCol/FixedColNum/
    IsFormula/Summary} —— 无 ComputationRule 等普通字段键。"""
    return {
        "ControlKey": 41,
        "DisplayName": sub.get("label", ""),
        "AssociationSchemaCode": "",
        "IsRelatedMember": False,
        "DataDictItemName": "",
        "OptionalValues": "",
        "DateTimeMode": "",
        "DisplayRule": "",
        "AssociationFilter": "",
        "UnitSelectionRange": "",
        "NameItems": "",
        "MappingField": "",
        "ShowFixedCol": False,
        "FixedColNum": sub.get("fixed", 1),
        "IsFormula": False,
        "Summary": "",
    }


def seqno_settings(controls):
    """表单级流水号设置（SchemaStr 顶层）—— 由 FormSeqNo 控件推导。
    线上样本（类型试验 2026-09-11）：EnableSeqNo=true、SeqNoDateFormat=YYYY、
    SeqNoPrefix=""、SeqNoLength=12（= 前缀长 + 日期段长 + 序号位数）、
    SeqNoStructure 是 JSON **字符串**：[{Type:1,Value:"YYYY"},{Type:2,IncreNum:8,Value:"1"}]。
    无流水号控件 → 全空（平台按未开启处理）。"""
    for c in controls:
        o = c.get("Options") or {}
        if o.get("ControlKey") != "FormSeqNo":
            continue
        mode = str(o.get("DateTimeMode") or "")
        prefix = str(o.get("Prefix") or "")
        try:
            inc = int(o.get("IncrementNum") or 0)
        except (TypeError, ValueError):
            inc = 0
        struct = json.dumps(o.get("SeqNoStructure") or [], ensure_ascii=False,
                            separators=(",", ":"))
        return True, mode, prefix, len(prefix) + len(mode) + inc, struct
    return False, "", "", "", ""


def build_schema_str(controls, name_schema, enable_data_acl=True,
                     enable_seqno=None, enable_form_sns=True, enable_task=False,
                     enable_log=False, assoc=None, app_package="", subs=None):
    """enable_seqno=None（缺省）→ 按 controls 里的流水号控件自动推导；显式 True/False 覆盖。"""
    props = {}
    for c in controls:
        if not is_field(c):          # 分组标题/描述：只占版面，不进 Properties
            continue
        a = (assoc or {}).get(c["Key"], {})
        props[c["Key"]] = prop_entry(c, app_package=app_package, **a)
    for s in subs or []:
        # 子表主条目：key = child schema 编码（40 位：appCode前7位+F+32hex）。
        # 键集逐字对照 UI 保存样本（无 ComputationRule/DefaultValue/IsRollup/LocationRangeLimit）
        code = s.get("code")
        if not code:
            raise ValueError("子表 %r 缺注册编码（registry subs 未预注册，先 build）"
                             % s.get("key"))
        props[code] = _sub_prop(s)
        # 子列条目：key = <childcode>.<列编码>，标准字段键集 + ParentKey
        for col in s["cols"]:
            k = "%s.%s" % (code, col["Key"])
            e = prop_entry(col, app_package=app_package)
            e["ParentKey"] = code
            props[k] = e
    seq_on, seq_mode, seq_prefix, seq_len, seq_struct = seqno_settings(controls)
    if enable_seqno is not None:
        seq_on = bool(enable_seqno)
    return {
        "RemovedControls": [],
        "NameSchema": name_schema,
        "EnableDataAcl": enable_data_acl,
        "EnableSeqNo": seq_on,
        "EnableFormSNS": enable_form_sns,
        "EnableTask": enable_task,
        "EnableLog": enable_log,
        "SeqNoDateFormat": seq_mode,
        "SeqNoPrefix": seq_prefix,
        "SeqNoLength": seq_len,
        "DataAclInheritedFrom": "",
        "AssociationMappings": {},
        "SeqNoStructure": seq_struct,
        "Properties": props,
    }


def build_control_settings(controls):
    """载荷顶层 ControlSettingsStr（**独立于 SchemaStr/BizSheetStr 的第三段**）。

    只有位置控件（FormMap）在这里落配置：Meters/LocationPCEnabled/LocationEditable
    在 FormLayout 与 Properties 里都没有键位。Controls 里 control["ControlSettings"]
    存这三键（controls.location() 生成）。样本逐字对照：
    [{"key":"F0000024","dataField":"F0000024","options":{"LocationPCEnabled":"true",
    "Meters":"500","LocationEditable":"false"}}]（值全是字符串）。"""
    out = []
    for c in controls:
        cs = c.get("ControlSettings")
        if cs:
            out.append({"key": c["Key"], "dataField": c["Key"],
                        "options": dict(cs)})
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


# =====================================================================
# HTML（DesignModeContent / RuntimeContent）
# =====================================================================
def hq(s):
    """HTML 属性值转义：双引号 → &quot;（curl 样本风格）"""
    return json.dumps(s, ensure_ascii=False)[1:-1].replace('"', '&quot;')


RULE = '{&quot;Rule&quot;:&quot;&quot;}'
# 公式控件占位输入框的提示语（线上样本逐字）
FORMULA_PLACEHOLDER = "公式型控件会自动计算并实时更新，不支持手动编辑"
# 汇总控件占位输入框的提示语（线上样本逐字）
ROLLUP_PLACEHOLDER = "可根据配置的条件自动汇总计算并实时更新"


def _esc(v):
    return hq(v)


def _escj(v):
    """HTML 属性里的 **JSON 串**转义：只把 & 和 " 变成实体，**不留反斜杠**
    （对照线上：data-seqnostructure="[{&quot;Type&quot;:1,…}]"）。
    hq() 那种 json.dumps 内部转义会多出 \\&quot;，属性值会被读成字面反斜杠。"""
    return str(v).replace("&", "&amp;").replace('"', "&quot;")


def _attrs(opt, key, extra_attrs="", rule=RULE, datafield=None, node_id=None):
    """设计 HTML 通用头属性（类型特有属性由调用方附在 extra_attrs）。
    node_id/datafield 供子表列使用：id=childcode-colcode（-），data-datafield=dotted
    rule=None 表示**不带** data-displayrule（流水号线上就没有）。"""
    idk = node_id if node_id is not None else key
    dfk = datafield if datafield is not None else key
    base = ('id="{i}" style="background-color: rgb(241, 250, 255);"  '
            'data-datafield="{d}"  data-displayname="{dn}"  data-description="{de}"  '
            'data-controlkey="{ck}"  data-summary="{su}"').format(
                i=idk, d=dfk, dn=_esc(opt.get("DisplayName", "")),
                de=_esc(opt.get("Description", "")), ck=opt.get("ControlKey", ""),
                su=_esc(opt.get("Summary", "")))
    if rule is not None:                 # rule=None → 整个 data-displayrule 属性都不出现
        base += '  data-displayrule="%s"' % rule
    return base + extra_attrs


def _row_open():
    return '<div class="row sheet-control" '


def _row_close(label, inner, remove=True, span_cls="col-sm-2", box_cls="col-sm-10"):
    rm = ('    <button class="btn btn-default btn-xs remove" style="display: none;" '
          'type="button" data-buttontype="remomvecontrol">'
          '<span class="icon-sheet icon-delete"></span>\n    </button>') if remove else ""
    return ('    <span class="%s">%s</span>\n'
            '    <div class="%s">\n%s\n    </div>\n%s'
            '</div>') % (span_cls, label, box_cls, inner, rm)


def _chk_items(ctl, tag):
    """单选/复选/开关的选项 HTML；id 用 uuid（与 UI 一致）。tag: radio/checkbox"""
    opt = ctl["Options"]
    parts = []
    for it in (opt.get("DefaultItems") or []):
        uid = str(uuid.uuid4())
        parts.append('<input type="%s" id="%s" disabled="disabled" data-itemid="%s">'
                     '<label for="%s">%s</label>'
                     % (tag, uid, uid, uid, _esc(it)))
    return '<div class="row notdrag">%s</div>' % "".join(parts)


def _rule_attr(opt, opt_key="DisplayRule"):
    """data-displayrule 属性值：空规则用 RULE 常量，带条件则 JSON 转义。
    注意这里走 hq() —— 非空规则会多出反斜杠（`\\&quot;`）。线上容忍这种写法，
    且已建成的表都是这么发的，**不动**（见 docs/platform_gotchas.md）。
    公式控件的 computationrule 有逐字样本，走下面 _rule_attr_exact。"""
    rule = opt.get(opt_key)
    if isinstance(rule, dict) and rule.get("Rule"):
        return hq(json.dumps({"Rule": rule["Rule"]}, ensure_ascii=False))
    return RULE


def _rule_attr_exact(opt, opt_key="ComputationRule"):
    """规则属性的值，**逐字对齐线上**：JSON 用 compact 分隔符、只做实体转义不留
    反斜杠（同 _escj）。线上样本 data-computationrule=
    "{&quot;Rule&quot;:&quot;{F0000027}+{F0000028}&quot;}"。
    空规则时结果与 RULE 常量完全相同。"""
    rule = opt.get(opt_key)
    txt = rule.get("Rule", "") if isinstance(rule, dict) else (rule or "")
    if not txt:
        return RULE
    return _escj(json.dumps({"Rule": txt}, ensure_ascii=False,
                            separators=(",", ":")))


def _bool(v):
    """HTML 属性里的布尔值（线上写小写 true/false）"""
    return "true" if v else "false"


# 布局项（分组标题/描述）的删除按钮：分组标题用 icon-remove-block，描述用 icon-delete
_BTN_GROUP = ('<button type="button" data-buttontype="remomvecontrol" '
              'class="btn btn-default btn-xs remove" style="display: none;">'
              '<span class="icon-sheet icon-remove-block"></span></button>')
_BTN_DESC = ('<button type="button" data-buttontype="remomvecontrol" '
             'class="btn btn-default btn-xs remove" style="display: none;">'
             '<span class="icon-sheet icon-delete"></span></button>')


def seqno_preview(opt):
    """流水号输入框的占位预览（设计器同款）：前缀 + 当前日期段 + 补零后的序号。
    线上样本 YYYY/8 位 → "202600000001"（2026 + 00000001）。"""
    prefix = opt.get("Prefix") or ""
    mode = (opt.get("DateTimeMode") or "").upper()
    now = datetime.datetime.now()
    part = ""
    for tok, fmt in (("YYYY", "%Y"), ("MM", "%m"), ("DD", "%d"),
                     ("HH", "%H"), ("MI", "%M"), ("SS", "%S")):
        if tok in mode:
            part += now.strftime(fmt)
    try:
        inc = int(opt.get("IncrementNum") or 0)
    except (TypeError, ValueError):
        inc = 0
    return prefix + part + str(1).zfill(inc)


def _group_title_html(control, runtime=False):
    """分组标题（type 101）：设计态 class="row page-header"，运行态去掉 row（线上同款）。
    注意整段**没有** data-datafield 等属性——线上就是纯 div + strong。"""
    opt = control["Options"]
    cls = " page-header" if runtime else "row page-header"
    return ('<div class="{cls}" id="{k}" style="position: relative; left: 0px; '
            'top: 0px;background-color: rgb(241, 250, 255); text-align:{al};">'
            '<strong>{t}</strong>{btn}</div>').format(
                cls=cls, k=control["Key"], al=_esc(opt.get("Alignment", "left")),
                t=_esc(opt.get("Title", "")), btn=_BTN_GROUP)


def _description_html(control, runtime=False):
    """描述/说明文字（type 103）：Content 是富文本 HTML，原样嵌入。"""
    opt = control["Options"]
    cls = " page-header page-describle" if runtime \
        else "row page-header page-describle"
    return ('<div class="{cls}" id="{k}" '
            'style="background-color: rgb(241, 250, 255);"><div>{c}</div>{btn}'
            '</div>').format(cls=cls, k=control["Key"],
                             c=opt.get("Content", ""), btn=_BTN_DESC)


def _new_runtime_attrs(control, ck):
    """新控件（流水号/图片/附件/位置/地址）运行态 HTML 的 data-* 属性串，
    用线上那套 `data-x = "v"` 写法（设计态见 design_html 里同名分支）。
    流水号的 SeqNoStructure 线上运行态写的是 JS 串 "[object Object],…"（设计器
    的字符串拼接瑕疵）——这里发真正的 JSON：运行态 HTML 是渲染模板，两处都只是
    装饰（回读的结构以 FormLayout 为准）。"""
    opt = control["Options"]
    sp = "  "
    eq = " = "
    j = lambda k, v: "%sdata-%s%s\"%s\"%s" % (sp, k, eq, v, sp)   # noqa: E731
    out = ""
    if ck == "FormSeqNo":
        # 结构串运行态线上是 JS 拼接瑕疵 "[object Object],[object Object]"
        # （设计态才是真 JSON）—— 运行态 HTML 只是渲染模板，逐字照抄线上
        n_seg = len(opt.get("SeqNoStructure") or [])
        out = (j("prefix", _esc(opt.get("Prefix", "")))
               + j("datetimemode", _esc(opt.get("DateTimeMode", "")))
               + j("seqnostructure", ",".join(["[object Object]"] * n_seg))
               + j("incrementnum", opt.get("IncrementNum", 0)).rstrip())
    elif ck == "FormPhoto":
        out = (j("uploadmultiple", _bool(opt.get("UploadMultiple")))
               + j("cameraonly", _bool(opt.get("CameraOnly")))
               + j("haswatermark", _bool(opt.get("HasWatermark")))
               + j("compression", _bool(opt.get("Compression")))).rstrip()
    elif ck == "FormAttachment":
        out = j("maxuploadsize", opt.get("MaxUploadSize", 10)).rstrip()
    elif ck == "FormMap":
        cs = control.get("ControlSettings") or {}
        out = (j("range", _esc(opt.get("Range", "0")))
               + j("meters", _esc(cs.get("Meters", "500")))
               + j("locationrangelimit", "undefined")
               + j("locationpcenabled", _esc(cs.get("LocationPCEnabled", "true")))
               + j("locationeditable", _esc(cs.get("LocationEditable", "false")))
               ).rstrip()
    elif ck == "FormAreaSelect":
        # 注意 defaultvalue 线上**没有** = 两侧空格（设计器这一条是拼串加的），照抄
        out = (j("areamode", _esc(opt.get("AreaMode", "P-C-T")))
               + j("showdetailaddr", _bool(opt.get("ShowDetailAddr")))
               + 'data-defaultvalue="%s"' % _escj(json.dumps(
                   opt.get("DefaultValue") or {}, ensure_ascii=False,
                   separators=(",", ":")))).rstrip()
    return (" " + out) if out else ""


def _member_dept_html(control):
    """成员/部门（单/多选）。对照 UI 真实载荷 fixtures/types7_ui_save_payload.json"""
    opt = control["Options"]
    ck = opt.get("ControlKey")
    key = control["Key"]
    label = opt.get("DisplayName", "")
    is_user = ck in ("FormUser", "FormMultiUser")
    is_dept = not is_user
    ex = ('  data-unitselectionrange=""  '
          'data-isrelatedmember="false"  data-showunactive="false"  '
          'data-usedatacache="true"  data-currentuserid="false"  '
          'data-mappingcontrols=""  data-orgunitvisible="{ov}"  '
          'data-uservisible="{uv}"  data-owndepvisible="{od}"  '
          'data-owndepusersvisble="{odu}"  data-ismultiple="{im}"').format(
              ov="true" if is_dept else "false",
              uv="false" if is_dept else "true",
              od="true" if is_dept else "false",
              odu="false" if is_dept else "true",
              im="true" if opt.get("IsMultiple") else "false")
    if is_user:
        ex += '  data-showcuruser="false"'
    ex += ('  data-defaultvaluerule=""  data-datalinkschemacode=""  '
           'data-datalinkschema="{{}}"  data-datalinkcondition="[]"  '
           'data-datalinkresult=""')
    ph = "点击选择人员" if is_user else "点击选择部门"
    inner = ('<input class="notdrag" style="width: 100%%;" type="text" '
             'readonly="" placeholder="%s">') % ph
    return (_row_open() + _attrs(opt, key, ex, rule=_rule_attr(opt))
            + "  >\n" + _row_close(label, inner))


def design_html(control, node_id=None, datafield=None, wide=False):
    """逐类型复刻 UI 设计 HTML（见 fixtures/types7_ui_save_payload.json BizSheetStr）。
    node_id/datafield/wide：子表列渲染用 —— id=childcode-colcode、datafield=dotted、
    标签与输入区全宽（col-sm-12，UI 子表单元格样本）。"""
    opt = control["Options"]
    ck = opt.get("ControlKey")
    key = node_id or control["Key"]
    df = datafield or control["Key"]
    label = opt.get("DisplayName", "")
    di = _esc(json.dumps(opt.get("DefaultItems", []), ensure_ascii=False))

    if control.get("Type") == C.T_GROUP_TITLE:      # 布局项：自带 HTML，无 data-* 头
        return _group_title_html(control)
    if control.get("Type") == C.T_DESCRIPTION:
        return _description_html(control)
    if ck in ("FormUser", "FormMultiUser", "FormDepartment",
              "FormMultiDepartment"):
        return _member_dept_html(control)
    if ck == "FormTextBox":
        ex = ('  data-placeholder="{ph}"  data-computationrule="{cr}" '
              'data-defaultvalueruletype="2"  data-datalinkschemacode=""  '
              'data-datalinkschema="{{}}"  data-datalinkcondition="[]"  '
              'data-datalinkresult=""  data-datalinkresultfunction=""  '
              'data-mode="Normal"  data-inputbyscan="false" '
              'data-scanupdateenable="false"  data-norepeat="false" '
              'data-norepeatrange="0"  data-norepeattipmessage="{tip}"  '
              'data-defaultitems="{di}"  data-voiceinput="false"').format(
                  ph=_esc(opt.get("PlaceHolder", "")), cr=RULE,
                  tip=_esc(opt.get("NoRepeatTipMessage", "")), di=di)
        inner = ('<input type="text" readonly="" class="notdrag" '
                 'style="width: 100%%;" placeholder="%s">') % _esc(opt.get("PlaceHolder", ""))
    elif ck == "FormNumber":
        ex = ('  data-placeholder=""  data-computationrule="{cr}" '
              'data-defaultvalueruletype="2"  data-datalinkschemacode=""  '
              'data-datalinkschema="{{}}"  data-datalinkcondition="[]"  '
              'data-datalinkresult=""  data-datalinkresultfunction=""  '
              'data-decimalplaces="{dp}"  data-showmode="0"  data-percentage="false" '
              'data-showbarchart="false"  data-dataformattype="0" '
              'data-rollupsettings=""').format(cr=RULE,
                                               dp=opt.get("DecimalPlaces", 0))
        inner = ('<input readonly="" class="notdrag" style="width: 100%;" '
                 'type="text">')
    elif ck == "FormTextArea":
        ex = ('  data-placeholder="{ph}"  data-computationrule="{cr}" '
              'data-defaultvalueruletype="2"  data-datalinkschemacode=""  '
              'data-datalinkschema="{{}}"  data-datalinkcondition="[]"  '
              'data-datalinkresult=""  data-datalinkresultfunction=""  '
              'data-rows="{rows}"  data-openrichtext="false" '
              'data-voiceinput="false"').format(
                  ph=_esc(opt.get("PlaceHolder", "")), cr=RULE,
                  rows=opt.get("Rows", 3))
        inner = ('<textarea class="notdrag" rows="%s" style="resize:none; '
                 'width:100%%;border:1px solid #ddd; " placeholder="%s">'
                 '</textarea>') % (opt.get("Rows", 3), _esc(opt.get("PlaceHolder", "")))
    elif ck == "FormDateTime":
        ex = ('  data-width="100%"  data-datetimemode="{dm}"').format(
            dm=opt.get("DateTimeMode", "yyyy-mm-dd"))
        ph = "年-月-日 时:分" if "hh:mm" in (opt.get("DateTimeMode", "") or "").lower() \
            else "年-月-日"
        inner = ('<input readonly="" class="notdrag" placeholder="%s" '
                 'style="width: 100%%;" type="text">') % ph
    elif ck == "FormDropDownList":
        if opt.get("DataSource") == "Association":
            # 联动下拉设计 HTML（对照线上样本 F0000021）：datasource 切 Association、
            # 关联键填真值；associationfilter 双层转义同 _rule_attr
            af = opt.get("AssociationFilter") or {}
            rule_txt = (af.get("Rule", "") if isinstance(af, dict) else (af or ""))
            ex = ('  data-transferitems="FormDropDownList"  data-selectshowmode="0"  '
                  'data-datadictitemname=""  data-defaultitems="{di}"  '
                  'data-defaultvalue=""  data-colorswitch="false"  '
                  'data-itemcolors=""  data-datasource="Association"  '
                  'data-boschemacode="{bsc}"  data-boschemainfo="{info}"  '
                  'data-mappingfield="{mf}"  data-associationfilter="{af}"  '
                  'data-mappingcontrols=""  data-associationfields="{aaf}"').format(
                      di=di, bsc=hq(opt.get("BOSchemaCode", "")),
                      info=hq(opt.get("BOSchemaInfo", "")),
                      mf=hq(opt.get("MappingField", "")),
                      af=hq(json.dumps({"Rule": rule_txt}, ensure_ascii=False)),
                      aaf=hq(opt.get("AssociationFields", "")))
        else:
            dv = opt.get("DefaultValue") or ""
            ex = ('  data-transferitems="FormDropDownList"  data-selectshowmode="0"  '
                  'data-datadictitemname=""  data-defaultitems="{di}"  '
                  'data-defaultvalue="{dv}"  data-colorswitch="false"  '
                  'data-itemcolors=""  data-datasource="Custom"  '
                  'data-boschemacode=""  data-boschemainfo=""  data-mappingfield=""  '
                  'data-associationfilter="{af}"').format(
                      di=di, dv=_esc(dv), af=RULE)
        inner = ('<select class="form-control form-group-margin notdrag" '
                 'style="width: 100%%;"></select>')
    elif ck == "FormRadioButtonList":
        ex = ('  data-transferitems="FormRadioButtonList"  data-selectshowmode="0"  '
              'data-datadictitemname=""  data-defaultitems="{di}"  '
              'data-defaultvalue=""  data-colorswitch="false"  '
              'data-itemcolors=""').format(di=di)
        inner = _chk_items(control, "radio")
    elif ck == "FormCheckboxList":
        dv = opt.get("DefaultValue")
        dj = _esc(json.dumps([dv] if dv else [""], ensure_ascii=False))
        ex = ('  data-transferitems="FormCheckboxList"  data-selectshowmode="0"  '
              'data-datadictitemname=""  data-defaultitems="{di}"  '
              'data-defaultvalue="{dj}"  data-colorswitch="false"  '
              'data-itemcolors=""  data-ischeckbox="false"  '
              'data-boschemacode=""  data-mappingfield=""  '
              'data-associationfilter="{af}"').format(di=di, dj=dj, af=RULE)
        inner = _chk_items(control, "checkbox")
    elif ck == "FormCheckbox":  # 开关（是/否）
        dv = "true" if opt.get("Checked") else "false"
        ex = ('  data-defaultitems="[{i}]"  data-defaultvalue="{dv}"  '
              'data-ischeckbox="true"  data-datadictitemname=""').format(
                  i=hq("是/否"), dv=dv)
        uid = str(uuid.uuid4())
        inner = ('<div class="row notdrag"><input disabled="disabled" id="{u}" '
                 'type="checkbox" data-itemid="{u}"><label for="{u}">是/否</label>'
                 '</div>').format(u=uid)
    elif ck == "FormQuery":
        bsc = opt.get("BOSchemaCode", "")
        info = opt.get("BOSchemaInfo", "")
        af = _esc(json.dumps(opt.get("AssociationFields") or
                             {"isDefault": True, "fieldSetting": []},
                             ensure_ascii=False))
        ex = ('  data-width="100%"  data-displayrule="{ru}" '
              'data-boschemacode="{bsc}"  data-associationfilter="{r2}" '
              'data-boschemaname="{bsn}"  data-islistview="{lv}"  '
              'data-boschemainfo="{info}"  data-bofilter=""  '
              'data-associationfields="{af}"  data-inputbyscan="false"  '
              'data-scanupdateenable="false"  data-datarule=""  '
              'data-mappingcontrols=""  data-mappingproperties="{{}}"  '
              'data-ismultiple="false"  data-mappingfield=""').format(
                  ru=RULE, bsc=_esc(bsc), r2=RULE,
                  bsn=_esc(opt.get("BOSchemaName", "")), lv=_esc(opt.get("IsListView", "")),
                  info=_esc(info), af=af)
        inner = ('<div class="form-query-add notdrag" style="border: 1px solid '
                 'rgb(221, 221, 221); border-image: none; height: 42px;"></div>')
    elif ck == "FormSeqNo":          # 流水号：线上没有 data-displayrule
        ex = ('  data-prefix="{pf}"  data-datetimemode="{dm}"  '
              'data-seqnostructure="{st}" data-incrementnum="{inc}"').format(
                  pf=_esc(opt.get("Prefix", "")),
                  dm=_esc(opt.get("DateTimeMode", "")),
                  st=_escj(json.dumps(opt.get("SeqNoStructure") or [],
                                      ensure_ascii=False, separators=(",", ":"))),
                  inc=opt.get("IncrementNum", 0))
        inner = ('<input readonly="" class="notdrag" placeholder="%s" '
                 'style="width: 100%%;" type="text">') % _esc(seqno_preview(opt))
        return (_row_open() + _attrs(opt, key, ex, rule=None) + "  >\n"
                + _row_close(label, inner))
    elif ck == "FormPhoto":
        ex = ('  data-uploadmultiple="{um}"  data-cameraonly="{co}"  '
              'data-haswatermark="{wm}"  data-compression="{cp}"').format(
                  um=_bool(opt.get("UploadMultiple")), co=_bool(opt.get("CameraOnly")),
                  wm=_bool(opt.get("HasWatermark")), cp=_bool(opt.get("Compression")))
        inner = ('<img class="notdrag" '
                 'src="/Content/images/svg/icon-pictureupload.svg">')
    elif ck == "FormAttachment":
        mb = opt.get("MaxUploadSize", 10)
        ex = '  data-maxuploadsize="%s"' % mb
        inner = ('<input class="notdrag" type="file" readonly="" '
                 'placeholder="%sMB">') % mb
    elif ck == "FormMap":
        cs = control.get("ControlSettings") or {}
        ex = ('  data-range="{rg}"  data-meters="{m}"  '
              'data-locationrangelimit="undefined"  data-locationpcenabled="{pc}"  '
              'data-locationeditable="{ed}"').format(
                  rg=_esc(opt.get("Range", "0")), m=_esc(cs.get("Meters", "500")),
                  pc=_esc(cs.get("LocationPCEnabled", "true")),
                  ed=_esc(cs.get("LocationEditable", "false")))
        inner = '<i class="fa icon-dizhi notdrag">读取地理位置</i>'
    elif ck == "FormAreaSelect":
        ex = ('  data-areamode="{am}"  data-showdetailaddr="{sd}"  '
              'data-defaultvalue="{dv}"').format(
                  am=_esc(opt.get("AreaMode", "P-C-T")),
                  sd=_bool(opt.get("ShowDetailAddr")),
                  dv=_escj(json.dumps(opt.get("DefaultValue") or {},
                                      ensure_ascii=False, separators=(",", ":"))))
        inner = ('<div class="notdrag" style="width: 100%;">'
                 '<select class="form-control notdrag" style="width: 33%; '
                 'display: inline-block;"><option>省</option></select>'
                 '<select class="form-control notdrag" style="width: 33%; '
                 'display: inline-block;"><option>市</option></select>'
                 '<select class="form-control notdrag" style="width: 34%; '
                 'display: inline-block;"><option>县</option></select></div>')
    elif ck == "FormFormula":        # 公式控件（type 304）
        # 线上样本：displayrule 与 computationrule 之间**单空格**，bindtype 起的那段
        # 用 ` = ` 写法；占位输入框 readonly + 固定提示语
        ex = (' data-computationrule="{cr}" data-bindtype="{bt}"  '
              'data-decimalplaces="{dp}"  data-datetimemode="yyyy-mm-dd hh:ii"  '
              'data-showmode="{sm}"  data-referenceable="{rf}"  ').format(
                  cr=_rule_attr_exact(opt, "ComputationRule"),
                  bt=_esc(opt.get("BindType", "number")),
                  dp=opt.get("DecimalPlaces", 0), sm=opt.get("ShowMode", 0),
                  rf=_bool(opt.get("Referenceable", True)))
        inner = ('<input type="text" readonly="" placeholder="%s" class="notdrag" '
                 'style="width: 100%%;">') % FORMULA_PLACEHOLDER
        return (_row_open() + _attrs(opt, key, ex, rule=_rule_attr(opt)) + "  >\n"
                + _row_close(label, inner))
    elif ck == "FormRollup":         # 汇总控件（type 501）
        # 线上样本：displayrule 与 rollupsettings 之间**单空格**，其后 `  ` 双空格分隔；
        # data-rollupsettings 是设计器自己的序列化瑕疵 "[object Object]"（照抄）
        ex = (' data-rollupsettings="{rs}"  data-bindtype="{bt}"  '
              'data-decimalplaces="{dp}"  data-datetimemode="yyyy-mm-dd hh:ii"  '
              'data-showmode="{sm}"').format(
                  rs=_esc(C.ROLLUP_ATTR_JUNK), bt=_esc(opt.get("BindType", "number")),
                  dp=opt.get("DecimalPlaces", 0), sm=opt.get("ShowMode", 0))
        inner = ('<input type="text" readonly="" placeholder="%s" class="notdrag" '
                 'style="width: 100%%;">') % ROLLUP_PLACEHOLDER
        return (_row_open() + _attrs(opt, key, ex, rule=_rule_attr(opt)) + "  >\n"
                + _row_close(label, inner))
    else:
        ex = '  data-placeholder=""  data-computationrule="{}"'.format(RULE)
        inner = ""
    if wide:
        return (_row_open() + _attrs(opt, df, ex, node_id=key) + "  >\n"
                + _row_close(label, inner, span_cls="col-sm-12", box_cls="col-sm-12"))
    return _row_open() + _attrs(opt, df, ex, node_id=key) + "  >\n" + _row_close(label, inner)


def runtime_html(control):
    """运行时 HTML（单 div；服务器对简化结构宽容，多类型保存已验证）"""
    opt = control["Options"]
    ck = opt.get("ControlKey")
    if control.get("Type") == C.T_GROUP_TITLE:
        return _group_title_html(control, runtime=True)
    if control.get("Type") == C.T_DESCRIPTION:
        return _description_html(control, runtime=True)
    key = control["Key"]
    base = ('data-datafield = "{k}" data-displayname = "{dn}" '
            'data-description = "{de}" data-controlkey = "{ck}" '
            'data-summary = "{su}"').format(
                k=key, dn=_esc(opt.get("DisplayName", "")),
                de=_esc(opt.get("Description", "")), ck=ck,
                su=_esc(opt.get("Summary", "")))
    if opt.get("DisplayRule") is not None:      # DisplayRule 键都没有（流水号）→ 属性不出现
        base += ' data-displayrule="{ru}"'.format(ru=_rule_attr(opt))
    if ck == "FormFormula":
        # 公式控件（对照线上样本）：computationrule 紧接 displayrule（单空格、= 不留空格），
        # 其后的 bindtype 段才用 ` = ` 写法 —— 不走 _new_runtime_attrs（那套首属性前是
        # 三个空格，且 attribute 之间是四个）。这样这段运行态 HTML 逐字对得上线上。
        base += (' data-computationrule="{cr}" data-bindtype = "{bt}"  '
                 'data-decimalplaces = "{dp}"  '
                 'data-datetimemode = "yyyy-mm-dd hh:ii"  '
                 'data-showmode = "{sm}"  data-referenceable = "{rf}"').format(
                     cr=_rule_attr_exact(opt, "ComputationRule"),
                     bt=_esc(opt.get("BindType", "number")),
                     dp=opt.get("DecimalPlaces", 0), sm=opt.get("ShowMode", 0),
                     rf=_bool(opt.get("Referenceable", True)))
        return "<div class='row sheet-control'  {attrs} > </div>".format(attrs=base)
    if ck == "FormRollup":
        # 汇总控件运行态（对照线上样本）：displayrule 后**单空格**接 rollupsettings，
        # 其余用 ` = ` 写法；无 referenceable。
        base += (' data-rollupsettings = "{rs}"  data-bindtype = "{bt}"  '
                 'data-decimalplaces = "{dp}"  '
                 'data-datetimemode = "yyyy-mm-dd hh:ii"  '
                 'data-showmode = "{sm}"').format(
                     rs=_esc(C.ROLLUP_ATTR_JUNK), bt=_esc(opt.get("BindType", "number")),
                     dp=opt.get("DecimalPlaces", 0), sm=opt.get("ShowMode", 0))
        return "<div class='row sheet-control'  {attrs} > </div>".format(attrs=base)
    return "<div class='row sheet-control'  {attrs}{ex} > </div>".format(
        attrs=base, ex=_new_runtime_attrs(control, ck))


def _child_entry(control, parent_key=""):
    """FormLayout 子条目（单控件，或一行多列的列内控件）：
    旧枚举 type + Options 全量透传。
    成员/部门四类（type 11-14）UI 样本用 uuid key + DataFieldEditable=true"""
    opt = dict(control.get("Options") or {})
    if control.get("Type") not in (C.T_GROUP_TITLE, C.T_DESCRIPTION):
        # 布局项（分组标题/描述）在 FormLayout 里**没有** DataField（线上样本同款）
        opt.setdefault("DataField", control["Key"])
        opt.setdefault("Summary", "")
        opt.setdefault("Description", "")
    if control.get("Type") is None:
        raise ValueError("控件缺 Type（老枚举）：%s" % control["Key"])
    if control["Type"] in (11, 12, 13, 14):
        return {"key": str(uuid.uuid4()), "type": control["Type"],
                "parentKey": parent_key, "options": opt, "DataFieldEditable": True}
    if control["Type"] == C.T_FORMULA:
        # 公式控件（type 304）：线上 FormLayout key 是 **GUID** + DataFieldEditable=true
        # （短码 key 存不住，同布局项）；DataField 仍是字段编码。GUID 用 uuid5 定值
        # （controls.formula_key），verify 才能复算期望键。
        return {"key": control.get("LayoutKey") or C.formula_key(control["Key"]),
                "type": C.T_FORMULA, "parentKey": parent_key,
                "options": opt, "DataFieldEditable": True}
    return {"key": control["Key"], "type": control["Type"],
            "parentKey": parent_key, "options": opt}


def layout_entry(control):
    """FormLayout 条目：旧枚举 type + Options 全量透传。"""
    return _child_entry(control, parent_key=control.get("ParentKey", ""))


LAYOUT_ROW_OPTS = {"Layout": "fourCols", "PercentageBlock": "fourCols-1111",
                   "DisplayName": "一行多列"}
ROW_HTML_KEY = "layout_fourcols"
ROW_COL_CLASS = "col-sm-3 col-xs-3"


def layout_row_entry(controls):
    """一行多列（type 102）FormLayout 条目。columns 与 childControls 双份列出子控件
    （对照用户保存样本 D001599e98...：key 用字段编码、parentKey 指向行 key）。"""
    rowkey = str(uuid.uuid4())
    children = [_child_entry(c, rowkey) for c in controls]
    return {"key": rowkey, "type": 102, "parentKey": "",
            "options": dict(LAYOUT_ROW_OPTS),
            "columns": children, "childControls": children}


def design_row_html(controls):
    """设计态一行多列 HTML：布局行 div 内按列包各自控件 html"""
    cols = []
    for i, c in enumerate(controls):
        cols.append('<div class="%s layoutrow-item ui-sortable ui-droppable" '
                    'data-layoutitem="Col%d" placeholder="将左侧控件拖入此处">\n%s\n'
                    '</div>' % (ROW_COL_CLASS, i + 1, design_html(c)))
    return ('<div class="row layoutrow" data-controlkey="%s" '
            'style="background-color: rgb(241, 250, 255);">\n%s\n</div>'
            % (ROW_HTML_KEY, "\n".join(cols)))


# =====================================================================
# 子表（FormGridView，type 104 / ControlKey 41）
# 逐字对照 UI 真实保存样本（fixtures/child_ref_payload.json：行 GUID key、列 key 全 GUID、
# columns 与 childControls 双份同列表节点；列 DataField = <childcode>.<列编码>）
# =====================================================================
GRID_ROW_ATTRS = ('data-nameitems=""  data-gridviewmode=""  data-gridviewfields=""  '
                  'data-displayfields=""  data-fixedcolnum="{n}"  '
                  'data-showfixedcol="false"  data-mobilegridviewmode="0"')


def grid_layout_entry(sub):
    """子表 type 104 FormLayout 条目。sub = {code,label,cols,fixed}（dsl 产物）"""
    code = sub["code"]
    rowkey = str(uuid.uuid4())

    def col_entry(col):
        opt = dict(col.get("Options") or {})
        opt["DataField"] = "%s.%s" % (code, col["Key"])
        return {"key": str(uuid.uuid4()), "type": col["Type"],
                "parentKey": rowkey, "options": opt,
                "DataFieldEditable": True, "removable": True}

    children = [col_entry(c) for c in sub["cols"]]
    return {"key": rowkey, "type": 104, "parentKey": "",
            "options": {"DataField": code, "DisplayName": sub.get("label", ""),
                        "Description": "", "ControlKey": "FormGridView",
                        "Summary": "", "NameItems": "",
                        "DisplayRule": {"Rule": "", "RuleText": ""},
                        "GridViewMode": "", "GridViewFields": "",
                        "DisplayFields": [], "FixedColNum": sub.get("fixed", 1),
                        "ShowFixedCol": False, "MobileGridViewMode": "0"},
            "DataFieldEditable": True,
            "columns": children, "childControls": children}


def design_grid_html(sub):
    """子表设计态 HTML（SheetGridView）：主 div + 列单元格 td（列控件整行全宽版）
    + 尾随占位 td + 编辑/加列/删除按钮。逐字对照 UI 样本。"""
    code = sub["code"]
    label = _esc(sub.get("label", ""))
    attrs = GRID_ROW_ATTRS.format(n=sub.get("fixed", 1))
    cells = []
    for col in sub["cols"]:
        dotted = "%s.%s" % (code, col["Key"])
        cells.append('<td class="SheetGridView_td ui-sortable ui-droppable" '
                     'style="display: table-cell; min-width: 185px;">\n%s\n</td>'
                     % design_html(col, node_id=dotted.replace(".", "-"),
                                   datafield=dotted, wide=True))
    cells.append('<td class="SheetGridView_td ui-sortable ui-droppable" '
                 'style="min-width: 183px;"></td>')
    return ('<div class="row sheet-control SheetGridView" id="{code}"  '
            'data-datafield="{code}"  data-displayname="{label}"  data-description=""  '
            'data-controlkey="FormGridView"  data-summary=""  {attrs} >'
            '<span class="col-sm-12" style="cursor:pointer">{label}</span>'
            '<div class="col-sm-12 SheetGridView_wrap" style="-ms-overflow-x: auto;">'
            '<table class="table table-bordered">'
            '<tr class="SheetGridView_tr ui-sortable">{cells}</tr></table></div>'
            '<button class="btn btn-default btn-xs editcontrol" style="display: none;" '
            'type="button" data-buttontype="editcontrol">'
            '<span class="glyphicon glyphicon-edit"></span>编辑子表</button>'
            '<button class="btn btn-default btn-xs addtd" type="button" '
            'data-buttontype="addTd"><span class="glyphicon glyphicon-plus"></span>'
            '添加列</button>'
            '<button class="btn btn-default btn-xs remove btn-sheet-del" '
            'style="display: none;" type="button" data-buttontype="remomvecontrol">'
            '<span class="icon-sheet-del icon-remove-block"></span>删除子表</button>'
            '</div>').format(code=code, label=label, attrs=attrs, cells="".join(cells))


def runtime_grid_html(sub):
    """子表运行态 HTML：主 div + table thead 各列一个 th（div.table_th）。
    列属性从列 Options 简取（服务器宽容，类同其它类型简化版）。"""
    code = sub["code"]
    label = _esc(sub.get("label", ""))
    attrs = GRID_ROW_ATTRS.format(n=sub.get("fixed", 1))
    ths = []
    for col in sub["cols"]:
        o = col.get("Options") or {}
        ck = o.get("ControlKey", "")
        clabel = _esc(o.get("DisplayName", col["Key"]))
        ths.append('<th><div class=\'table_th sheet-control\'  '
                   'data-datafield = "{d}"  data-displayname = "{dn}"  '
                   'data-description = ""  data-controlkey = "{ck}"  '
                   'data-summary = ""  data-displayrule="{ru}" >{dn}</div></th>'
                   .format(d="%s.%s" % (code, col["Key"]), dn=clabel, ck=ck, ru=RULE))
    return ('<div class="row sheet-control"  data-datafield = "{code}"  '
            'data-displayname = "{label}"  data-description = ""  '
            'data-controlkey = "FormGridView"  data-summary = ""  {attrs} >'
            '<table class="table table-bordered table-hover table-condensed">'
            '<thead><tr>{ths}</tr></thead></table></div>'
            ).format(code=code, label=label, attrs=attrs, ths="".join(ths))


def runtime_row_html(controls):
    """运行态一行多列：外层 row + 等宽列包各控件 html"""
    cols = "".join('<div class="col-md-3 col-sm-3 col-xs-3">%s</div>'
                   % runtime_html(c) for c in controls)
    return "<div class='row'>%s</div>" % cols


def build_biz_sheet(sheet_code, controls, layout=None, enable_form_sns=True,
                    enable_task=False, enable_log=False, enable_data_acl=True,
                    subs=None):
    """BizSheetStr。layout 缺省 = 全 flat；给出时按序混排：单控件条目 或 行组（4 列）。
    subs：子表（自动排在表单底部整行，不参与一行多列打包）。"""
    seq = layout if layout is not None else list(controls)
    dm = []
    rt = []
    fl = []
    for item in seq:
        if isinstance(item, (list, tuple)):
            dm.append(design_row_html(item))
            rt.append(runtime_row_html(item))
            fl.append(layout_row_entry(item))
        else:
            dm.append(design_html(item))
            rt.append(runtime_html(item))
            fl.append(layout_entry(item))
    for s in subs or []:
        dm.append(design_grid_html(s))
        rt.append(runtime_grid_html(s))
        fl.append(grid_layout_entry(s))
    return {
        "SheetCode": sheet_code,
        "Javascript": "",
        "NewJsCode": "",
        "BehindCode": "",
        "EnableFormSNS": enable_form_sns,
        "EnableTask": enable_task,
        "EnableLog": enable_log,
        "EnableDataAcl": enable_data_acl,
        "DataAclInheritedFrom": "",
        "DesignModeContent": "".join(dm),
        "RuntimeContent": "".join(rt),
        "FormLayout": fl,
    }
