# -*- coding: utf-8 -*-
"""ER 结构生成({sheets,dicts,groups,automations})。

  generate_design(plan_markdown, requirement_text="", documents_text="")
      -> {sheets, dicts, groups, automations, provider}

有 LLM:提示模型输出严格 JSON(表/字段/控件类型/关联/枚举/自动化),内嵌 docs/schema_doc.md 的
控件类型表与 key 命名硬规则;**参考资料 = 用户上传的文档 + 已生成方案 + 需求**(无内置样本)。
无 LLM / LLM 失败:回退 h3service.ai.HeuristicProvider.design()(其语料来自用户已建项目)。
**无论哪条路径,产出都必须经 h3service.design.clean_design 清洗(剔幻觉键/非法类型/规范化 key)。**
"""
from . import llm
from .context import REFERENCE_GUARD

_SYSTEM = """你是氚云低代码平台的表单设计器。根据《系统设计方案》与原始需求,输出每张表的完整字段结构
**以及表单之间的自动化(触发器)**。
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
1. 字段 key、表单 key、子表 key、子表列 key、自动化 key 一律:字母开头、只含字母数字、**不得有下划线**
   (plan_begin ✗ → planBegin 或 planbegin ✓;1ab ✗);
2. 不得占用平台自带编码:Name、SeqNo、CreatedTime、CreatedBy、ModifiedTime、ModifiedBy、
   OwnerId、OwnerDeptId、Status、State、ObjectId、WorkflowInstanceId;
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

请遵循设计 SOP:命中知识库同类系统的表/字段语义码优先复用,主动补齐常规的
状态/日期/负责人/备注/附件/明细子表/金额等字段。
**只设计与【系统设计方案】【业务需求】相关的表;【参考资料】仅用于字段命名与口径参考,
不得引入业务需求未提及的表、字段或自动化。**"""


def _user_prompt(plan_markdown, requirement_text, reference_text=""):
    parts = ["【系统设计方案(基于本项目需求产出)】\n%s" % (plan_markdown or "(空)"),
             "【业务需求(本项目的唯一需求来源)】\n%s" % (requirement_text or "(空)")]
    if reference_text and reference_text.strip():
        parts.append("【参考资料(非本项目需求,仅供字段/口径/设计惯例参考)】\n%s"
                     % reference_text.strip())
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


def _heuristic(requirement_text, plan_markdown):
    from h3service.ai import HeuristicProvider
    text = requirement_text or plan_markdown or ""
    return HeuristicProvider().design(text)


def generate_design(plan_markdown: str, requirement_text: str = "",
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
                _SYSTEM, _user_prompt(plan_markdown, requirement_text, reference_text),
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
        cleaned = _clean(_heuristic(requirement_text, plan_markdown))
        used = "heuristic"
    if not cleaned:
        cleaned = {"sheets": [], "dicts": {}, "groups": [], "automations": []}
    cleaned["provider"] = used
    return cleaned
