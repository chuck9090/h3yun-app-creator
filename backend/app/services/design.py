# -*- coding: utf-8 -*-
"""ER 结构生成({sheets,dicts,groups,automations})。

  generate_design(plan_markdown, flowchart_mmd="", reference_text="")
      -> {sheets, dicts, groups, automations, provider}

**依据 = 《系统设计方案》 + 《业务流程图》**:方案给出每个表单的完整字段与业务规则,
流程图给出表单之间的**流转关系**(据此生成自动化/触发器);两者口径一致(流程图本身也源于方案)。
**看板/报表类不建表**(非业务实体,由氚云端 SQL 报表另配)。
有 LLM:提示模型输出严格 JSON(表/字段/控件类型/关联/枚举/自动化);
无 LLM / LLM 失败:回退 h3service.ai.HeuristicProvider.design()(其语料来自用户已建项目)。
**无论哪条路径,产出都必须经 h3service.design.clean_design 清洗(剔幻觉键/非法类型/规范化 key)。**
"""
from . import llm
from .context import REFERENCE_GUARD, is_report_entity

_SYSTEM = """你是氚云低代码平台的表单设计器。请依据**两份材料**输出每张业务表的完整字段结构
**以及表单之间的自动化(触发器)**:
  - 《系统设计方案》:H1=模块、H2=**业务表单**,表单下「业务内容」逐项给出该表的**字段(中文名)、子表/明细、业务规则**;
  - 《业务流程图》:给出表单之间的**业务流转关系**(A 完成后生成/推进到 B)——据此判断要配哪些**自动化**。
两者口径一致(流程图也是从方案生成的);字段的**英文编码(key)由你生成**,须遵守下方 key 命名硬规则。

【范围(重要)】
- 只建**业务表**(方案里发生在业务流转链上的单据/档案);
- **看板 / 报表 / 统计 / 分析 / 总览 / 监控 类一律不建表** —— 它们是对数据的展示,
  由氚云端 SQL 报表/高级数据源另配,不属于本应用的表单(方案中若出现这些模块/表单,直接跳过);
- 只设计与方案+流程图相关的内容,**不得引入方案之外的表、字段或自动化**。
只输出严格 JSON(不要 markdown 代码块、不要解释),结构:
{"sheets":[{"key":"customer","title":"客户表","nameSchema":"{cname}","useOwner":false,
  "group":"基础资料","layout":"auto4",
  "controls":[
    {"type":"text","key":"cname","label":"客户名称","required":true},
    {"type":"dropdown","key":"ctype","label":"客户类型","dict":"客户类型"},
    {"type":"query","key":"prj","label":"关联项目","assoc":"project"},
    {"type":"subtable","key":"items","label":"明细",
      "columns":[{"type":"text","key":"srv","label":"服务名称"},
                 {"type":"number","key":"qty","label":"数量","decimal":2}]}
  ]}],
 "dicts":{"客户类型":["企业","个人"]},
 "groups":["基础资料","业务管理"],
 "automations":[
   {"key":"a1","title":"合同生效后回写客户累计","form":"contract","trigger":"生效或更新",
    "sortKey":1,
    "when":[{"field":"status","value":"已生效"}],
    "actions":[{"do":"更新","target":"customer","match":[{"field":"cname","ref":"customer"}],
                "set":[{"to":"total","from":"amount"}],"owner":true}]}
 ]}

【自动化 DSL 规则】(见氚云自动化:某表数据生效/失效/更新时自动增删改别的表)
- 元素键:`key`(文件名,字母开头纯字母数字,唯一)、`title`、`form`(触发表单 key)、
  `trigger`(只能是 生效 / 失效 / 生效或更新 三者之一)、`sortKey`(可选数字)、
  `when`(可选触发条件数组,只能筛**触发表主表**字段)、`actions`(必填,非空)。
- action:`do`(新增/更新/删除)、`target`(目标表单 key)、`state`(可选 生效/发起流程)、
  `isInsert`(仅 do=更新:匹配不到是否新增,默认 true)、
  `match`(定位目标记录,**更新/删除必填**)、`set`(源字段→目标字段映射)、
  `owner`(可选 bool,默认 true 补拥有者)、
  `sub`(可选,写目标表的子表:`{"table":"子表key","set":[{"to":"目标列","from":"源字段"}]}`)。
- 字段引用写法:`when.field`/`set.from`/`match.ref`/`sub.set.from` 引用**源或目标对应表的字段编码**
  (子表列写 `子表key.列key`;系统字段写 `$ObjectId`/`$OwnerId`/`$OwnerDeptId`);
  `match.field`/`set.to`/`sub.set.to` 引用**目标表**字段(子表列写进 sub.set 且不带子表前缀)。
- 没有明确需要联动写表的场景时,`automations` 给空数组 []。

【key 命名硬规则(违反会导致建表失败,check 会拦)】
1. 字段 key、表单 key、子表 key、子表列 key、自动化 key 一律:**只含英文字母与数字,必须字母开头,
  不得出现任何符号**(下划线/连字符/空格/点号/括号/斜杠/中文 都不行)
   (plan_begin ✗ → planBegin ✓;客户-档案 ✗ → customerFile ✓;1ab ✗;金额(元) ✗ → amount ✓);
2. **不得占用保留字**,否则建表或 SQL 报表会失败:
   - 平台自带编码(主表/子表/中间表都有):ObjectId、Name、CreatedBy、OwnerId、OwnerDeptId、
     CreatedTime、ModifiedBy、ModifiedTime、WorkflowInstanceId、Status、State、SeqNo、
     ParentObjectId、ParentPropertyName、ParentIndex、ValueIndex、PropertyValue;
   - **MySQL 保留关键字**(字段编码会成为数据库列名,撞上会让 SQL 报表/高级数据源报错):
     status、order、group、key、desc、select、from、where、rank、system、values、index、range、
     char、int、float、decimal、date、time、if、in、is、and、or、not、null、left、right、join 等;
     换成业务别名即可(如 status → billStatus、order → saleOrder、group → mgroup);
3. `query` 的 `assoc` = 另一张表的 key(不要自引用,被引用表先建);
4. `dropdown` / `radio` / `checkbox_list` 必须给 `dict`(引用 dicts 的分类名)或 `options`(字面量数组),二者其一;
5. `useOwner:true` 时申请人与申请部门是系统字段,不要把 owner 写进 controls;
6. 子表列只支持:text / textarea / number / date / switch / radio / dropdown / checkbox_list / attachment / image;
7. `formula` 的 `rule` 只能引用**本表**字段编码,写 {{字段编码}},且只能单独成行;
8. layout 默认 "auto4"(每行 4 列)。

【可用控件类型与额外键】
- text(default, placeholder) / textarea(rows, default) / number(decimal, default)
- date(datetime) / switch(checked)
- radio(dict 或 options, default) / dropdown(dict 或 options, default, hideWhen)
- checkbox_list(dict 或 options, defaults) / member(multi) / department(multi)
- query(assoc, multi) / seq_no(prefix, datetime, increment;key 可省,编码恒为 SeqNo)
- image(multiple, cameraOnly, watermark, compression) / attachment(maxSize)
- location(meters, pcEnabled, editable) / address(areaMode, showDetail)
- formula(rule, decimal, bindType=number) / group_title(align) / description(content, title)
- subtable(columns, fixed)

请遵循设计 SOP:
1. `groups` 的名称与顺序**与方案的模块(H1)一致**,每个表的 `group` 取其所属模块;不得自创模块名;
   **看板/报表类模块不出现在 groups 里**(已整体排除);
2. **方案里列出的每一个业务表单都必须设计出来(一个不漏)**;命中知识库同类系统的表/字段语义码优先复用;
3. 主动补齐常规的状态/日期/负责人/备注/附件/明细子表/金额等字段;
4. 依据**业务流程图**里"A → B"的流转,判断 B 是否需要自动化(A 生效时生成/回写 B);
   只在确有联动写表的场景配 `automations`,否则给空数组。"""


def _user_prompt(plan_markdown, flowchart_mmd="", reference_text=""):
    parts = ["【系统设计方案(唯一字段与规则的来源)】\n%s" % (plan_markdown or "(空)")]
    if flowchart_mmd and flowchart_mmd.strip():
        parts.append("【业务流程图(表单间的业务流转,用于判断自动化)】\n```mermaid\n%s\n```"
                     % flowchart_mmd.strip())
    if reference_text and reference_text.strip():
        parts.append("【参考资料(仅供字段命名/口径参考,非本项目需求)】\n%s" % reference_text.strip())
        parts.append(REFERENCE_GUARD)
    return "\n\n".join(parts)


def _clean(design):
    """清洗设计;失败返回 None。"""
    from h3service.design import clean_design
    try:
        out = clean_design(design)
    except Exception:
        return None
    return out if out.get("sheets") else None


def _strip_reports(design):
    """剔除看板/报表类表与只含它们的模块(它们不进 ER、也不生成应用)。

    自动化只在**引用了被剔除的表**时才丢弃(不按"未命中保留集合"误删)。
    """
    dropped = set()
    sheets, groups = [], []
    for s in design.get("sheets") or []:
        if is_report_entity(s.get("title") or s.get("key")):
            dropped.add(s.get("key"))
            continue
        if is_report_entity(s.get("group")):
            s = dict(s)
            s["group"] = ""            # 模块被排除:表保留但去掉模块归属
        sheets.append(s)
    keep_groups = {s.get("group") for s in sheets if s.get("group")}
    for g in design.get("groups") or []:
        if is_report_entity(g) or g not in keep_groups:
            continue
        groups.append(g)
    out = dict(design)
    out["sheets"] = sheets
    out["groups"] = groups

    def _refs_removed(a):
        # 只按**表 key** 判断:`form`(触发表)、`actions[].target`(目标表)、`sub.table`(目标子表)。
        # 注意 `match[].ref` 是**字段**引用(源侧取值),不是表 key,不能拿来判表。
        if a.get("form") in dropped:
            return True
        for act in a.get("actions") or []:
            if act.get("target") in dropped:
                return True
            if (act.get("sub") or {}).get("table") in dropped:
                return True
        return False

    out["automations"] = [a for a in (design.get("automations") or [])
                          if not _refs_removed(a)]
    return out


def _heuristic(plan_markdown):
    from h3service.ai import HeuristicProvider
    return HeuristicProvider().design(plan_markdown or "")


def generate_design(plan_markdown: str, flowchart_mmd: str = "",
                    reference_text: str = "", progress=None, provider=None) -> dict:
    def _p(msg, pct=None, level="info"):
        if progress:
            progress(msg, pct=pct, level=level)

    provider = provider or llm.get_provider()
    used = "heuristic"
    cleaned = None
    if getattr(provider, "available", False):
        try:
            _p("调用大模型生成 ER 结构…", pct=78)
            raw = provider.complete(
                _SYSTEM, _user_prompt(plan_markdown, flowchart_mmd, reference_text),
                json_mode=True)
            _p("解析并清洗模型输出", pct=90)
            cleaned = _clean(llm.extract_json(raw))
            if cleaned:
                used = provider.name
        except Exception as e:
            cleaned = None
            _p("大模型生成失败(%s),回退启发式" % str(e)[:160], pct=90, level="warning")
    else:
        _p("未配置大模型,使用启发式生成 ER 结构", pct=78, level="warning")
    if not cleaned:
        cleaned = _clean(_heuristic(plan_markdown))
        used = "heuristic"
    if not cleaned:
        cleaned = {"sheets": [], "dicts": {}, "groups": [], "automations": []}
    removed = len(cleaned.get("sheets") or [])
    cleaned = _strip_reports(cleaned)
    dropped = removed - len(cleaned.get("sheets") or [])
    if dropped:
        _p("已排除 %d 张看板/报表(不建表、不进应用)" % dropped, pct=92, level="info")
    cleaned["provider"] = used
    return cleaned
