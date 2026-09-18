# -*- coding: utf-8 -*-
"""控件构造器 —— 新引擎（Console/SheetDesigner SaveForm）设计态控件列表。
每个控件 {Key, Type(老枚举), Options, ChildControls}；newbuilder 负责转 SchemaStr/BizSheetStr。
必填/只读在新引擎 SaveForm 载荷中无对应键（UI 侧另存），故 required/readonly 参数仅作定义标注。"""
import json
import uuid

# FormControlType 数值（老枚举，FormLayout.type 用；已对照 UI 载荷实证）：
# … 9 地址 / 10 位置 / 15 附件 / 16 图片 / 201 流水号 见下方新控件段
# （2026-09-11 类型试验线上样本 fixtures/types7_ui_save_payload.json 逐字）
T_TEXTBOX, T_TEXTAREA, T_DATETIME, T_NUMBER = 1, 2, 3, 4
T_RADIO, T_CHECKBOX_LIST, T_DROPDOWN, T_SWITCH = 5, 6, 7, 8
T_AREA, T_MAP = 9, 10
T_MULTIUSER, T_USER, T_DEPARTMENT, T_MULTIDEPT = 11, 12, 13, 14
T_ATTACHMENT, T_PHOTO = 15, 16
T_GROUP_TITLE, T_LAYOUT, T_DESCRIPTION, T_GRID_VIEW, T_TAB = 101, 102, 103, 104, 105
T_SEQNO = 201
T_QUERY, T_MULTI_QUERY = 301, 302
T_FORMULA = 304                # 公式控件（2026-09-16 类型试验线上样本逐字）
T_ROLLUP = 501                 # 汇总控件（2026-09-16 类型试验线上样本逐字）

# ControlKey 字符串（ControlKey/FormLayout.options.ControlKey 用）
K_TEXTBOX = "FormTextBox"
K_TEXTAREA = "FormTextArea"
K_DATETIME = "FormDateTime"
K_NUMBER = "FormNumber"
K_RADIO = "FormRadioButtonList"
K_CHECKBOX_LIST = "FormCheckboxList"
K_DROPDOWN = "FormDropDownList"
K_SWITCH = "FormCheckbox"
K_USER = "FormUser"
K_DEPARTMENT = "FormDepartment"
K_MULTIUSER = "FormMultiUser"
K_MULTIDEPT = "FormMultiDepartment"
K_ATTACHMENT = "FormAttachment"
K_PHOTO = "FormPhoto"
K_AREA = "FormAreaSelect"
K_MAP = "FormMap"
K_GROUP_TITLE = "FormGroupTitle"
K_LAYOUT = "FormLayout"
K_DESCRIPTION = "FormDescription"
K_SEQNO = "FormSeqNo"
K_QUERY = "FormQuery"
K_GRIDVIEW = "FormGridView"      # 子表（明细表）；子表行 = 独立 child schema
K_FORMULA = "FormFormula"        # 公式控件
K_ROLLUP = "FormRollup"          # 汇总控件

TYPE_OF_KEY = {
    K_TEXTBOX: T_TEXTBOX, K_TEXTAREA: T_TEXTAREA, K_DATETIME: T_DATETIME,
    K_NUMBER: T_NUMBER, K_RADIO: T_RADIO, K_CHECKBOX_LIST: T_CHECKBOX_LIST,
    K_DROPDOWN: T_DROPDOWN, K_SWITCH: T_SWITCH, K_USER: T_USER,
    K_DEPARTMENT: T_DEPARTMENT, K_MULTIUSER: T_MULTIUSER,
    K_MULTIDEPT: T_MULTIDEPT,
    K_ATTACHMENT: T_ATTACHMENT, K_PHOTO: T_PHOTO, K_AREA: T_AREA, K_MAP: T_MAP,
    K_GROUP_TITLE: T_GROUP_TITLE, K_LAYOUT: T_LAYOUT,
    K_DESCRIPTION: T_DESCRIPTION, K_SEQNO: T_SEQNO, K_QUERY: T_QUERY,
    K_FORMULA: T_FORMULA, K_ROLLUP: T_ROLLUP,
}
# 只占版面的布局项（不进 SchemaStr.Properties、无 DataField）
LAYOUT_KEYS = (K_GROUP_TITLE, K_DESCRIPTION)


def _common(key, label, ckey, summary=""):
    """UI 载荷里所有类型都带的基础 Options 键（对照 fixtures/types7_ui_save_payload.json）"""
    opt = {
        "DataField": key,
        "DisplayName": label,
        "Description": "",
        "ControlKey": ckey,
        "Summary": summary or "",
        "DisplayRule": {"Rule": ""},
        "PlaceHolder": "",
        "ComputationRule": {"Rule": ""},
        "DefaultValueRuleType": 2,
        "DataLinkSchemaCode": "",
        "DataLinkSchema": {},
        "DataLinkCondition": [],
        "DataLinkResult": "",
        "DataLinkResultFunction": "",
    }
    return opt


def control(key, label, ckey, extra=None, summary=""):
    opt = _common(key, label, ckey, summary)
    if extra:
        opt.update(extra)
    return {"Key": key, "Type": TYPE_OF_KEY[ckey], "Options": opt,
            "ChildControls": None}


# ---- 基础控件 ----
def text(key, label, required=False, readonly=False, placeholder="", summary="", default="",
         rule=""):
    """单行文本。必填/只读：新引擎另存，参数留作设计稿标注。
    rule: 隐藏条件文本（如 {applytype}=="新料号"），空 = 默认可见。"""
    extra = {"Mode": "Normal",
             "NoRepeatTipMessage": "不允许重复录入信息。",
             "PlaceHolder": placeholder,
             "NoRepeat": False,
             "DefaultValue": default}
    if rule:
        extra["DisplayRule"] = {"Rule": rule}
    return control(key, label, K_TEXTBOX, extra=extra, summary=summary)


def textarea(key, label, required=False, readonly=False, rows=3, default=""):
    extra = {"Rows": rows, "OpenRichText": False, "VoiceInput": False,
             "DefaultValue": default}
    return control(key, label, K_TEXTAREA, extra=extra)


def number(key, label, required=False, readonly=False, decimal=0, default=None,
           rule=""):
    extra = {"DecimalPlaces": decimal, "DataFormatType": "0", "ShowMode": "0",
             "Percentage": False, "ShowBarChart": False, "RollupSettings": []}
    if default is not None:
        extra["DefaultValue"] = default
    if rule:
        extra["DisplayRule"] = {"Rule": rule}
    return control(key, label, K_NUMBER, extra=extra)


def date_field(key, label, required=False, readonly=False, datetime_mode="yyyy-mm-dd",
               rule=""):
    return control(key, label, K_DATETIME,
                   extra={"DateTimeMode": datetime_mode, "Width": "100%",
                          **({"DisplayRule": {"Rule": rule}} if rule else {})})


def switch_field(key, label, required=False, readonly=False, checked=False):
    """开关（是/否）。Options 逐字对照 UI：DefaultItems=[是/否] IsCheckbox="true"。
    DefaultValue: 勾选="true" 否则 "false"（Properties 同款字符串）。"""
    return control(key, label, K_SWITCH,
                   extra={"DefaultItems": ["是/否"],
                          "DefaultValue": "true" if checked else "false",
                          "IsCheckbox": "true",
                          "DataDictItemName": "",
                          "Checked": bool(checked)})


def member(key, label, required=False, readonly=False, multi=False,
           rule=""):
    """成员（单选/多选）。Options 对照 UI 真实载荷（D001599e98... 读回，权威）：
    FormUser/FormMultiUser type 12/11；默认取当前用户等规则未配则留空。"""
    ckey = K_MULTIUSER if multi else K_USER
    extra = {
        "DisplayRule": {"Rule": rule},
        "UnitSelectionRange": "", "IsRelatedMember": False,
        "ShowUnActive": False, "UseDataCache": True, "CurrentUserId": False,
        "MappingControls": "", "OrgUnitVisible": False, "UserVisible": True,
        "OwnDepVisible": False, "OwnDepUsersVisble": True,
        "IsMultiple": bool(multi), "ShowCurUser": False,
        "DefaultValueRule": {"value": "", "label": "", "nodes": []},
    }
    return control(key, label, ckey, extra=extra)


def department(key, label, required=False, readonly=False, multi=False,
               rule=""):
    """部门（单选/多选）。对照 UI 真实载荷：type 13/14；部门无 ShowCurUser。"""
    ckey = K_DEPARTMENT if not multi else K_MULTIDEPT
    extra = {
        "DisplayRule": {"Rule": rule},
        "UnitSelectionRange": "", "IsRelatedMember": False,
        "ShowUnActive": False, "UseDataCache": True, "CurrentUserId": False,
        "MappingControls": "", "OrgUnitVisible": True, "UserVisible": False,
        "OwnDepVisible": True, "OwnDepUsersVisble": False,
        "IsMultiple": bool(multi),
        "DefaultValueRule": {"value": "", "label": "", "nodes": []},
    }
    if multi:
        extra["DefaultValue"] = ""
    return control(key, label, ckey, extra=extra)


# ---- 单选 / 多选 / 下拉（UI 存储值 = 所选文本本身）----
def radio(key, label, items, required=False, default=""):
    extra = {"SelectShowMode": "0", "TransferItems": K_RADIO,
             "DataDictItemName": "", "ItemColors": [], "ColorSwitch": False,
             "DataSource": "Custom",
             "DefaultItems": list(items), "DefaultValue": default}
    return control(key, label, K_RADIO, extra=extra)


def checkbox_list(key, label, items, required=False, default_items=()):
    """复选。DefaultValue 用分号连接（与导入数据多值格式一致）；无默认=""
    Options 逐字对照 UI（含 IsCheckbox=false）。"""
    dv = ";".join(default_items)
    extra = {"SelectShowMode": "0", "TransferItems": K_CHECKBOX_LIST,
             "DataDictItemName": "", "ItemColors": [], "ColorSwitch": False,
             "DataSource": "Custom",
             "DefaultItems": list(items), "DefaultValue": dv,
             "IsCheckbox": False}
    return control(key, label, K_CHECKBOX_LIST, extra=extra)


def dropdown(key, label, items, required=False, default="", rule=""):
    """下拉。值即显示文本。rule 同 text()。"""
    extra = {"SelectShowMode": "0", "TransferItems": K_DROPDOWN,
             "DataDictItemName": "", "ItemColors": [], "ColorSwitch": False,
             "DataSource": "Custom",
             "DefaultItems": list(items), "DefaultValue": default}
    if rule:
        extra["DisplayRule"] = {"Rule": rule}
    return control(key, label, K_DROPDOWN, extra=extra)


def assoc_dropdown(key, label, boschema_code, mapping_field, filter_rule="",
                   app_package="", rule=""):
    """联动下拉：选项来自另一张表（DataSource=Association）+ 级联过滤。
    Options 键集逐字对照线上样本（类型试验 F0000021 Association 形态，2026-09-09）：
    DataSource/BOSchemaCode/BOSchemaInfo(JSON串)/MappingField(存值列)/
    AssociationFilter{Rule}/AssociationFields(JSON串)/MappingControls/MappingProperties；
    另外剔掉 _common 的 PlaceHolder/DataLink 键（同 query()）。
    DefaultItems=[] 不落占位项（UI 从 Custom 改型才残留 选项1/2/3）。
    filter_rule: 规则文本（如 {源表编码.dictcategory}=="特性代码" AND
    CONTAINS({源表编码.applyto},{bigcat})）；rule: hideWhen 同 text()。"""
    opt = _common(key, label, K_DROPDOWN)
    opt = {k: v for k, v in opt.items()
           if k not in ("PlaceHolder", "DataLinkSchemaCode", "DataLinkSchema",
                        "DataLinkCondition", "DataLinkResult",
                        "DataLinkResultFunction")}
    boschema_info = json.dumps(
        {"AppPackage": app_package, "AppGroup": "",
         "AppMenu": boschema_code, "IsChildSchema": False}, ensure_ascii=False,
                      separators=(",", ":"))
    assoc_fields = json.dumps({"isDefault": True, "fieldSetting": []},
                              ensure_ascii=False, separators=(",", ":"))
    opt.update({
        "DisplayRule": {"Rule": rule},
        "TransferItems": K_DROPDOWN, "SelectShowMode": "0",
        "DataDictItemName": "", "DefaultItems": [], "DefaultValue": None,
        "ColorSwitch": False, "ItemColors": [],
        "DataSource": "Association",
        "BOSchemaCode": boschema_code, "BOSchemaInfo": boschema_info,
        "MappingField": mapping_field,
        "AssociationFilter": {"Rule": filter_rule},
        "MappingControls": "",
        "AssociationFields": assoc_fields, "MappingProperties": "{}",
    })
    return {"Key": key, "Type": T_DROPDOWN, "Options": opt,
            "ChildControls": None}


# ---- 布局项（无 DataField，不进 Properties）----
_LAYOUT_NS = uuid.UUID("6f1d5a3c-9b2e-4a77-8f10-2c9d4e7b5a31")


def layout_key(def_key):
    """布局项（分组标题/描述）在 FormLayout 与 HTML 里的 key：线上是 **GUID**
    （UI 每加一个就发新号），短码当 key 存不住 —— 2026-09-11 线上实证：用定义短码
    保存后回读 key=None、verify 判缺字段。这里用 uuid5(固定命名空间, 短码) 定值：
    同一张表的同一布局项永远同号，verify 才能不靠 registry 复算期望键。
    定义侧短码存控件 Dict 的 DefKey，只供 layout 行引用。"""
    return str(uuid.uuid5(_LAYOUT_NS, str(def_key)))


def _layout_opt(ckey, display_name, extra=None):
    """布局项（分组标题/描述）的 Options。线上样本只有三四个键，无 Summary/DataField。"""
    opt = {"DisplayName": display_name}
    if extra:
        opt.update(extra)
    if ckey:
        opt["ControlKey"] = ckey      # 分组标题线上**不带** ControlKey（2026-09-11 样本）
    return opt


def group_title(key, title, alignment="left"):
    """分组标题（type 101）。Options 逐字对照线上样本：{DisplayName, Title, Alignment}，
    **没有 ControlKey**（设计器保存的就是这三个键）。
    短码只留在 DefKey（layout 行引用用）；Key 是 layout_key 出的 GUID。"""
    return {"Key": layout_key(key), "DefKey": key, "Type": T_GROUP_TITLE,
            "Options": _layout_opt(None, title, {"Title": title,
                                                 "Alignment": alignment}),
            "ChildControls": None}


def description(key, content="", display_name="描述说明", rule=None):
    """描述/说明文字（type 103，ControlKey FormDescription）。
    content = 富文本 HTML（如 "<p>描述</p>"）；DisplayRule 线上是空字典 {}。"""
    opt = _layout_opt(K_DESCRIPTION, display_name,
                      {"Content": content, "DisplayRule": {}})
    if rule:
        opt["DisplayRule"] = {"Rule": rule}
    return {"Key": layout_key(key), "DefKey": key, "Type": T_DESCRIPTION,
            "Options": opt, "ChildControls": None}


# ---- 新控件（流水号/图片/附件/位置/地址）----
# 键集对照线上样本：比老控件窄 —— 无 PlaceHolder/ComputationRule/DataLink* 键
def _plain(key, label, ckey, extra=None, rule=None, summary=""):
    """新控件 FormLayout Options 基础键。rule=None 表示**不带** DisplayRule 键
    （流水号线上就没有）；rule="" 或规则文本 → 落 {"Rule": ...}。"""
    opt = {"DataField": key, "DisplayName": label, "Description": "",
           "ControlKey": ckey, "Summary": summary}
    if rule is not None:
        opt["DisplayRule"] = {"Rule": rule}
    if extra:
        opt.update(extra)
    return opt


def _ctl(key, ckey, opt, extra=None):
    c = {"Key": key, "Type": TYPE_OF_KEY[ckey], "Options": opt,
         "ChildControls": None}
    if extra:
        c.update(extra)
    return c


def seqno(key="SeqNo", label="流水号", prefix="", datetime_mode="YYYY",
          increment=8):
    """流水号（type 201）。**表单级**键由 build_schema_str 联动：
    EnableSeqNo=true / SeqNoDateFormat / SeqNoPrefix / SeqNoStructure / SeqNoLength
    （SeqNoLength = 前缀长 + 日期段长 + 序号位数）。
    static: DateTimeMode 支持 YYYY / YYYYMM / YYYYMMDD 等（段长按字符串长度算）。
    prefix 非空只落 Prefix 选项（线上样本 prefix 为空，非空形态未实证）。"""
    opt = _plain(key, label, K_SEQNO, rule=None)
    opt.update({
        "Prefix": prefix,
        "DateTimeMode": datetime_mode,
        "SeqNoStructure": [{"Type": 1, "Value": datetime_mode},
                           {"Type": 2, "IncreNum": increment, "Value": "1"}],
        "IncrementNum": increment,
    })
    return _ctl(key, K_SEQNO, opt, {"SeqNoPrefix": prefix,
                                    "SeqNoDateFormat": datetime_mode})


def photo(key, label, multiple=False, camera_only=False, watermark=False,
          compression=False, rule=""):
    """图片（type 16，ControlKey FormPhoto）。multiple=多选上传；
    camera_only=仅拍照；watermark=加水印；compression=压缩。"""
    opt = _plain(key, label, K_PHOTO, rule=rule or "",
                 extra={"UploadMultiple": bool(multiple),
                        "CameraOnly": bool(camera_only),
                        "HasWatermark": bool(watermark),
                        "Compression": bool(compression)})
    return _ctl(key, K_PHOTO, opt)


def attachment(key, label, max_upload_size=10, rule=""):
    """附件（type 15，ControlKey FormAttachment）。max_upload_size 单位 MB（线上默认 10）。
    必填/只读/是否允许多附件等由界面另存。"""
    opt = _plain(key, label, K_ATTACHMENT, rule=rule or "",
                 extra={"MaxUploadSize": max_upload_size})
    return _ctl(key, K_ATTACHMENT, opt)


def location(key, label, meters=500, pc_enabled=True, editable=False,
             range_="0", rule=""):
    """位置（type 10，ControlKey FormMap）。**注意**：Meters/LocationPCEnabled/
    LocationEditable 不在 FormLayout/Properties 里，而走载荷顶层独立的
    ControlSettingsStr（见 newbuilder.build_control_settings）—— 存在返回的
    control["ControlSettings"] 里，由 newbuilder 收集。
    range_: 定位范围选项（线上 "0"）；data-locationrangelimit 线上写 "undefined"。"""
    opt = _plain(key, label, K_MAP, rule=rule or "", extra={"Range": range_})
    return _ctl(key, K_MAP, opt, {"ControlSettings": {
        "LocationPCEnabled": "true" if pc_enabled else "false",
        "Meters": str(meters),
        "LocationEditable": "true" if editable else "false"}})


def area(key, label, area_mode="P-C-T", show_detail=True, rule="",
         default=None):
    """地址（type 9，ControlKey FormAreaSelect）。area_mode 如 "P-C-T"
    （省-市-县；其它档位未实证）；show_detail=允许填详细地址；default 为
    {"adcode","adname","Detail"} 三键字典（Properties 侧存 JSON 串）。"""
    dv = default or {"adcode": "", "adname": "", "Detail": ""}
    opt = _plain(key, label, K_AREA, rule=rule or "",
                 extra={"AreaMode": area_mode,
                        "ShowDetailAddr": bool(show_detail),
                        "DefaultValue": dict(dv)})
    return _ctl(key, K_AREA, opt)




# ---- 公式控件（FormFormula，type 304）----
# 逐字对照线上样本 fixtures/formula_ui_save_payload.json（2026-09-16 类型试验 F0000026）。
# 与普通字段的差别：
#   ① FormLayout.type = 304、ControlKey = "FormFormula"，但 **SchemaStr.Properties
#      的 ControlKey = 7**（与数字控件同存储型）；
#   ② FormLayout 条目的 key 是 **GUID** + DataFieldEditable=true（短码 key 存不住，
#      同布局项，见 layout_key）；DataField 仍是字段编码；
#   ③ 规则正文落两处：Properties.ComputationRule = **纯文本**，
#      FormLayout.options.ComputationRule / HTML data-computationrule = {"Rule": 文本}；
#   ④ Properties 多 Referenceable/DataFormatType/DecimalPlaces/ShowMode，
#      少 RollupSettings/ShowBarChart/PlaceHolder（数字控件那套键一个不带）。
_FORMULA_NS = uuid.UUID("b47c2e91-3d6a-4f80-9c15-7a8e6d2b41f9")
FORMULA_BIND_TYPES = ("number",)     # 线上只实证过 number（数字型公式）
FORMULA_DATETIME_MODE = "yyyy-mm-dd hh:mm"   # FormLayout 侧（HTML 侧写 hh:ii）


def formula_key(def_key):
    """公式控件在 FormLayout 里的 key：线上是 GUID（同布局项）。用 uuid5(固定命名空间,
    字段编码) 定值 —— 同一字段每次构建同号，verify 才能不靠 registry 复算期望键。"""
    return str(uuid.uuid5(_FORMULA_NS, str(def_key)))


def formula(key, label, rule, bind_type="number", decimal=0, rule_hide=""):
    """公式控件（type 304，ControlKey FormFormula）。rule = 公式正文，字段引用写
    花括号里的**字段编码**（如 "{price}*{qty}"），加减乘除/括号照引擎语法。
    bind_type 目前只实证 "number"；decimal = 小数位（线上默认 0）。
    rule_hide 同名冲突不用：hideWhen 走 DisplayRule（第四参叫 hide 更清楚，但
    controls 层统一用 rule 命名，这里用 rule_hide 以免和公式正文撞名）。
    返回的 control["Key"] 仍是**字段编码**（Properties/DataField 用），
    FormLayout 的 GUID key 取 control["LayoutKey"]。"""
    if bind_type not in FORMULA_BIND_TYPES:
        raise ValueError("%s: 公式控件 bindType 目前只实证 %s（得到 %r）"
                         % (key, "/".join(FORMULA_BIND_TYPES), bind_type))
    opt = {"DataField": key, "DisplayName": label, "Description": "",
           "ControlKey": K_FORMULA, "Summary": "",
           "DisplayRule": {"Rule": rule_hide},
           "ComputationRule": {"Rule": rule},
           "BindType": bind_type, "DecimalPlaces": int(decimal),
           "DateTimeMode": FORMULA_DATETIME_MODE, "ShowMode": 0,
           "Referenceable": True}
    return {"Key": key, "DefKey": key, "LayoutKey": formula_key(key),
            "Type": T_FORMULA, "Options": opt, "ChildControls": None,
            "Standalone": True,        # 只能单独成行（UI 样本是 FormLayout 顶层条目）
            "FormulaRule": rule}


# ---- 汇总控件（FormRollup，type 501）----
# 逐字对照线上样本 fixtures/rollup_ui_save_payload.json（2026-09-16 类型试验 F0000029-F0000035）。
# 与公式控件的差别：
#   ① FormLayout.type = 501、ControlKey = "FormRollup"，但 SchemaStr.Properties 的
#      ControlKey 仍是 **7**（存储型同数字控件，同公式）；
#   ② FormLayout 条目的 key 是**字段编码**（不是 GUID）、**没有** DataFieldEditable
#      —— 与普通字段同款（公式是 GUID + DataFieldEditable）；
#   ③ 配置落 RollupSettings：[{RollupType, Expression, SourceSchemaCode,
#      PropertyMapping}]，FormLayout 与 Properties 两处**同值**；
#   ④ Properties 无 ComputationRule；ShowMode 是 int 0、DataFormatType 空串、
#      末尾 RollupSettings + DecimalPlaces（数字控件那套 ShowBarChart 一个不带）；
#   ⑤ HTML data-rollupsettings 线上是设计器自己序列化失败的 "[object Object]"
#      （平台不看 HTML，真配置只在 FormLayout/Properties）—— 照抄，别"修好"。
ROLLUP_TYPES = {                 # 汇总方式（帮助文档只列这四种，线上样本同款）
    "sum": 1, "count": 5, "max": 6, "min": 7}
ROLLUP_DATETIME_MODE = "yyyy-mm-dd hh:mm"   # FormLayout 侧（HTML 侧写 hh:ii）
ROLLUP_ATTR_JUNK = "[object Object]"        # HTML data-rollupsettings 的线上原样
# UI 自动加的首条件（只统计已生效数据）：每组条件的第一条都是它
ROLLUP_STATUS_COND = ("Status", "Fixed", 1)


def rollup_cond(prop, value_type="Fixed", value=None):
    """一条汇总筛选条件（源侧字段名由调用方拼好：主表字段=裸编码、子表列=子表码.列编码）。
    两种形状的键序照抄线上样本（Fixed 那条无 SubOperator 且 Id 在末尾，PropertyName 那条
    Id 在首、带 SubOperator:null）——服务端读回会重排成自己的形状，键序只是表象。"""
    if value_type == "PropertyName":
        return {"Id": str(uuid.uuid4()), "PropertyName": prop, "Operator": "Equal",
                "SubOperator": None, "ValueType": "PropertyName", "Value": value}
    return {"PropertyName": prop, "Operator": "Equal", "ValueType": "Fixed",
            "Value": value, "Id": str(uuid.uuid4())}


def rollup(key, label, kind, source_code, source_property, groups,
           decimal=0, rule_hide=""):
    """汇总控件（type 501，ControlKey FormRollup）。
    kind: sum/count/max/min（ROLLUP_TYPES）；
    source_code: 数据源 schema 编码（**主表表单编码**，或**子表 child schema 编码**）；
    source_property: 被汇总的源字段编码（计数的源字段没有数值语义，任选一个即可）；
    groups: 筛选条件组 [ [cond, ...], ... ] —— 外层**或**、内层**且**（rollup_cond 产物）；
            Status=1 那条由 dsl 侧按需预置，这里只收最终条件。
    decimal: 小数位（界面可配）；rule_hide: hideWhen 隐藏条件文本。
    与公式控件一样只能单独成行（Standalone）。"""
    rt = ROLLUP_TYPES.get(kind)
    if rt is None:
        raise ValueError("%s: 汇总方式 %r 不支持（实证集合 %s）"
                         % (key, kind, "/".join(sorted(ROLLUP_TYPES))))
    settings = {
        "RollupType": rt,
        "Expression": [list(g) for g in groups],
        "SourceSchemaCode": source_code,
        "PropertyMapping": {"SourceSchemaCode": source_code,
                            "SourcePropertyName": source_property},
    }
    opt = {"DataField": key, "DisplayName": label, "Description": "",
           "ControlKey": K_ROLLUP, "Summary": "",
           "DisplayRule": {"Rule": rule_hide},
           "RollupSettings": [settings],
           "BindType": "number", "DecimalPlaces": int(decimal),
           "DateTimeMode": ROLLUP_DATETIME_MODE, "ShowMode": 0}
    return {"Key": key, "DefKey": key, "Type": T_ROLLUP, "Options": opt,
            "ChildControls": None,
            "Standalone": True,        # 只能单独成行（UI 样本是 FormLayout 顶层条目）
            "RollupKind": kind, "RollupSource": source_code}


def query(key, label, boschema_code, app_package="", required=False, multi=False,
          rule=""):
    """关联表单控件（FormQuery/FormMultiQuery）。Options 逐字对照 UI 样本 F0000007：
    键集、BOSchemaInfo/AssociationFields 的 JSON 字符串形式完全一致。
    rule: 隐藏条件文本（同 text()，仅 DisplayRule.Rule 变化，其余键位不动）。"""
    ckey = K_QUERY if not multi else "FormMultiQuery"
    boschema_info = json.dumps(
        {"AppPackage": app_package, "AppGroup": "",
         "AppMenu": boschema_code, "IsChildSchema": False}, ensure_ascii=False,
                      separators=(",", ":"))
    fields = json.dumps({"isDefault": True, "fieldSetting": []}, ensure_ascii=False,
                          separators=(",", ":"))
    extra = {
        "BOSchemaCode": boschema_code,
        "AssociationFilter": {"Rule": ""},
        "BOSchemaName": "",
        "IsListView": "",
        "BOSchemaInfo": boschema_info,
        "BOFilter": "",
        "AssociationFields": fields,
        "InputByScan": False,
        "ScanUpdateEnable": False,
        "DataRule": "",
        "MappingControls": "",
        "MappingProperties": "{}",
        "IsMultiple": False,
        "MappingField": "",
        "Width": "100%",
    }
    opt = _common(key, label, ckey)
    # 规范样本的关联控件不含 PlaceHolder/DataLink 键，替换为规范键集
    opt = {k: v for k, v in opt.items()
           if k not in ("PlaceHolder", "DataLinkSchemaCode", "DataLinkSchema",
                        "DataLinkCondition", "DataLinkResult",
                        "DataLinkResultFunction")}
    if rule:
        opt["DisplayRule"] = {"Rule": rule}
    opt.update(extra)
    return {"Key": key, "Type": TYPE_OF_KEY[ckey], "Options": opt,
            "ChildControls": None}
