# -*- coding: utf-8 -*-
"""自动化（触发器）载荷构造：与 SheetDesigner/SaveForm 完全无关的另一套端点。

保存: POST {base}/Automatic/OnAction   表单段 PostData={"ActionName":"SaveTrigger", ...}
读回: 同端点 PostData={"ActionName":"LoadTriggers","SchemaCode":<表单码>}
      → ReturnData.Triggers[]（与保存载荷同形，是自动化版的 verify 面）

结构（2026-09-16 应用 D001599zdh「自动化四大操作场景讲解」6 份载荷逐字实证）：
  信封 {ObjectId, SchemaCode(触发表), DisplayName, ExcuteType, Condition{},
        Action[]}，其中**动作是树**：Action[i].ChildrenTriggerAction 再套一层，
  写目标表的子表就是「外层定位/新建父记录 + 内层真正写子表行」两级。
  触发条件 = DNF（外层**或**、内层**且**，`Id` 必带），与汇总控件条件同源。

平台对键集是**归一化**的：设计器新建自动化时只发精简键集（Operation:"isAdd"，
缺 Code/IsDevMode/OnlyCreateChildren 等，见 fixtures/automation_删除时.json），服务端
照收 —— 工厂发一份**规范全量**形态即可，不必逐字对齐某个 UI 样本。"""
import uuid

# 触发时机（ExcuteType）。界面另有定时/按钮/日期字段触发，不需要，一律 null。
#   111=数据生效时  113=数据失效时  114=数据生效或者更新时
TRIGGER_TYPES = {"生效": 111, "失效": 113, "生效或更新": 114}

# 动作插件。PluginAction 恒为单元素同名列表；DisplayName 三档固定文案
# （只有顶层动作有 DisplayName，内层子动作恒为 null）。
PLUGIN_OF_DO = {"新增": "insertdata", "更新": "updatedata", "删除": "removedata"}
PLUGIN_LABEL = {"insertdata": "新增数据", "updatedata": "更新数据",
                "removedata": "删除数据"}

# 目标记录的数据状态（RequestMapping.State）：1=生效 2=发起流程
TARGET_STATES = {"生效": 1, "发起流程": 2}

SOURCE_TYPE = 1        # 字段映射来源：1=表单字段（其余档位未实证）
VALUE_SET_TYPE = 1     # 赋值方式：1=取字段值（固定值/公式未实证）
# DataSetType 按插件/作用域分档（6 份界面样例 + 线上在跑的自动化一致）：
#   新增/更新 → 1；删除主表记录 → 2；删除**子表行**（动作读到了触发表的子表列，
#   即 SourceId 是子表编码）→ 4。
#   删除动作写 1 线上实测**不生效**（目标行原样留着），故不能一刀切写 1。
DATASET_TYPE = {"insertdata": 1, "updatedata": 1, "removedata": 2}
DATASET_TYPE_CHILD_DELETE = 4
DATASET_TYPE_DEFAULT = 1


def dataset_type(plugin, source_code, form_code):
    """删除动作分「删主表记录=2 / 删子表行=4」，其余插件恒 1。"""
    if plugin != "removedata":
        return DATASET_TYPE.get(plugin, DATASET_TYPE_DEFAULT)
    return DATASET_TYPE_CHILD_DELETE if source_code != form_code \
        else DATASET_TYPE["removedata"]

# 系统字段在 DSL 里用 $ 前缀写（$ObjectId / $OwnerId / $OwnerDeptId），生成时去掉 $
# —— 与用户自建的、同名的普通字段区分开。
SYS_FIELDS = ("ObjectId", "OwnerId", "OwnerDeptId")
# 写**主表**时自动补的两条拥有者映射（界面同款：源同名→目标同名），
# 不带的话目标数据归属为空、数据权限会丢。定义里 "owner": false 可关掉。
OWNER_AUTO = ("OwnerId", "OwnerDeptId")


def auto_cond(prop, value_type="Fixed", value=None):
    """自动化条件项（触发条件 Expression / 动作的 ParentCondition）。
    与汇总控件条件同形，差异：**Id 必带**、**无 SubOperator**。键序照线上。"""
    return {"Id": str(uuid.uuid4()), "PropertyName": prop, "Operator": "Equal",
            "ValueType": value_type, "Value": value}


def parent_cond_v2(prop, value_type="Fixed", value=None):
    """动作的 ParentConditionV2（写子表时定位父记录用）：**无 Id**、带 SubOperator。"""
    return {"PropertyName": prop, "Operator": "Equal", "SubOperator": None,
            "ValueType": value_type, "Value": value}


def mapping(source_field, target_field):
    """字段映射项。两处 SourceField 写法：主表字段 `<表别名>.<字段码>`，
    子表列 `<表别名>.<子表别名>.<列码>`；目标侧主表裸码、子表 `<子表码>.<列码>`。"""
    return {"SourceField": source_field, "SourceType": SOURCE_TYPE,
            "TargetField": target_field, "ValueSetType": VALUE_SET_TYPE,
            "Extension": {"AssociationPropertyName": ""}}


def alias_of(code):
    """别名恒为 <编码>@1（一条自动化内每个表只有一个别名；自关联多别名未实证）。"""
    return "%s@1" % code


def _req_insert(target_value, state, insert_mappings, rel_aliases, child_target,
                nested):
    r = {}
    if child_target:
        r["GroupByMainPropertyMappings"] = True     # 按主表记录分组写子表行
    r["TargetSchemaValue"] = list(target_value)
    r["State"] = state
    r["InsertFieldMappings"] = insert_mappings
    r["RelationSchemaCodeAlias"] = rel_aliases
    if child_target:
        r["ChildCondition"] = []
    if not nested:      # 线上只有顶层动作带 FinishStartActivity（内层子动作不带）
        r["FinishStartActivity"] = True
    return r


def _req_update(target_value, is_insert, state, parent_condition,
                update_mappings, insert_mappings, rel_aliases):
    return {"TargetSchemaValue": list(target_value),
            "IsInsert": bool(is_insert),     # 匹配不到就新增（界面"没有则新增"）
            "State": state,
            "ParentCondition": parent_condition,
            "ChildCondition": [],
            "UpdateFieldMappings": update_mappings,
            "InsertFieldMappings": insert_mappings,
            "RelationSchemaCodeAlias": rel_aliases,
            "FinishStartActivity": True}


def _req_remove(target_value, parent_condition, rel_aliases):
    return {"TargetSchemaValue": list(target_value),
            "RelationSchemaCode": [],
            "ParentCondition": parent_condition,
            "ChildCondition": [],
            "RelationSchemaCodeAlias": rel_aliases}


def action(plugin, trigger_type, form_code, source_code, target_value,
           related_aliases, rel_aliases, obj_id, state=None, is_insert=False,
           parent_condition=None, parent_condition_v2=None,
           insert_mappings=None, update_mappings=None,
           only_create=False, only_update=False, only_remove=False,
           group_by=None, children=None, child_target=False, nested=False):
    """一个动作节点。
    children = 子动作列表（写目标表子表时的内层动作）；
    target_value = [AppCode, 目标主表码, 目标主表码或目标子表码]；
    nested=True 时 DisplayName 为 null、ChildrenTriggerAction 为 null（线上内层
    叶子动作同款）；顶层叶子动作 ChildrenTriggerAction 是**空列表**（两种都见过）。
    GroupByPropertyMappings：线上删除动作恒 false，其余 true（6 份样本一致）。"""
    if plugin == "insertdata":
        req = _req_insert(target_value, state, insert_mappings or [],
                          rel_aliases, child_target, nested)
    elif plugin == "updatedata":
        req = _req_update(target_value, is_insert, state, parent_condition or [],
                          update_mappings or [], insert_mappings or [],
                          rel_aliases)
    elif plugin == "removedata":
        req = _req_remove(target_value, parent_condition or [], rel_aliases)
    else:
        raise ValueError("未知动作插件 %r" % plugin)
    if group_by is None:
        group_by = plugin != "removedata"
    return {"Condition": [],
            "ChildrenTriggerAction": (children if children is not None
                                      else (None if nested else [])),
            "PluginCode": plugin,
            "PluginAction": [plugin],
            "ObjectId": obj_id,
            "DisplayName": None if nested else PLUGIN_LABEL[plugin],
            "SourceId": source_code,
            "SourceIdAlias": alias_of(source_code),
            "SourceCode": "",
            "SchemaCode": form_code,
            "SchemaCodeAlias": alias_of(form_code),
            "TriggerType": trigger_type,
            "RequestMapping": req,
            "ResponseMapping": {},
            "DataSetType": dataset_type(plugin, source_code, form_code),
            "RelatedSchemaCodeAliases": related_aliases,
            "ParentConditionV2": parent_condition_v2 or [],
            "OnlyCreateChildren": only_create,
            "OnlyUpdateChildren": only_update,
            "OnlyRemoveChildren": only_remove,
            "GroupByPropertyMappings": group_by,
            "SourceIsCondition": False,
            "GroupByPropertyMappings_Children": (True if child_target else None)}


def build_trigger(spec):
    """动作树 + 信封 → SaveTrigger 载荷。spec 由 dsl 层解析后传入：
    {objectId, schema_code, display_name, excute_type, expression, aliases,
     actions, sort_key, app_code, operation}
    Operation：ObjectId 已存在（重存/更新）写 "isUpdate"，首次新建写 "isAdd"
    —— 界面新建时发的就是 isAdd（见 fixtures/automation_删除时.json）。"""
    return {"ObjectId": spec["objectId"],
            "SchemaCode": spec["schema_code"],
            "DisplayName": spec["display_name"],
            "ExcuteType": spec["excute_type"],
            "Condition": {"Expression": spec["expression"],
                          "UpdatedFiled": {"Value": [], "Text": ""},
                          "ExcuteConfig": None,
                          "TriggerTypeList": None,
                          "ExcuteTypeList": [spec["excute_type"]],
                          "DateFieldTrigger": None,
                          "ButtonTrigger": None,
                          "Schedule": None,
                          "RelatedSchemaCodeAliases": spec["aliases"]},
            "ConditionExpressionText": "",
            "Action": spec["actions"],
            "State": True,
            "SortKey": spec["sort_key"],
            "ExpressionEditable": True,
            "CustomBizObjectSchema": None,
            "Code": "",
            "IsDevMode": False,
            "ActionName": "SaveTrigger",
            "AppCode": spec["app_code"],
            "Operation": spec.get("operation") or "isUpdate"}


# 自动化/动作 ObjectId 的 uuid5 命名空间 —— 固定值，保证同一定义每次都生成同一批
# GUID：重存即更新那条自动化，而不是又建一条重复的（ObjectId 是平台侧主键）。
_NS = uuid.UUID("6f1c2ab0-0f4d-5a7e-9c31-8d2b4e6a7f10")


def trigger_object_id(proj, key):
    return str(uuid.uuid5(_NS, "%s/%s" % (proj, key)))


def action_object_id(proj, key, path):
    return str(uuid.uuid5(_NS, "%s/%s#%s" % (proj, key, path)))
