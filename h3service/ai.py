# -*- coding: utf-8 -*-
"""AI 编排层:需求文档 → 方案(表级) → 表单结构(字段级)。

两种 provider
-------------
- `HeuristicProvider`:零依赖、离线。用**设计知识库**按需求关键词匹配历史项目,
  命中即把该项目的表/字段结构作为草案(复用而非从零),再交人工改。**无 LLM 也能跑通闭环**。
- `OpenAICompatProvider`:调用 OpenAI 兼容接口(base_url 可换成任意国产/私有模型),
  提示词内嵌 DSL 约束与设计 SOP,要求返回严格 JSON。

选择:环境变量 H3F_LLM_BASE_URL / H3F_LLM_API_KEY / H3F_LLM_MODEL 齐全 → LLM,否则启发式。
"""
import json
import os
import re

from . import engine as E

KNOWLEDGE = E.KNOWLEDGE

# ---------------------------------------------------------------- 提示词
CONTROL_TYPES = ("text, textarea, number, date, switch, radio, dropdown, "
                 "checkbox_list, member, department, query, seq_no, image, "
                 "attachment, location, address, formula, group_title, "
                 "description, subtable")

_SYS_PROPOSE = """你是氚云低代码平台的企业系统架构师。用户会给你一段"大概的业务需求"。
你的任务:参照提供的【历史系统设计语料】,输出一份**表级方案**——把客户没想到但同类系统必然要有的
表、关系和口径主动补齐,并标注置信度。

硬性要求:
1) 先找同类历史项目;能复用的表/字段语义码直接复用,保持跨项目一致。
2) 输出严格 JSON(不要 markdown 代码块),结构:
{{"summary":"一句话方案概述",
 "tables":[{{"key":"t_customer","title":"客户表","role":"主数据|单据|字典|档案|流水|汇总",
            "fields_hint":["客户名称","联系人"],"rationale":"依据","confidence":"high|medium|low"}}],
 "relations":[{{"from":"t_contract","to":"t_customer","field":"customer","kind":"关联|联动"}}],
 "assumptions":["需求未提但按惯例默认的项,标 ▲"],
 "gaps":["无法确定、需人工确认的项,标 ?"]}}
3) 表 key 用短语义码:小写字母+数字,字母开头,无下划线(如 customer/contract/docno)。
4) 字段语义码复用常见惯例(remark/pname/pcode/customer/prj/docno/items/total/is_paid 等)。
5) 宁可多补常规项(状态/日期/负责人/备注/附件/子表/金额),也不要漏。

【可用控件类型】""" + CONTROL_TYPES + """

【历史语料】
{corpus}
"""

_SYS_DESIGN = """你是氚云低代码平台的表单设计器。根据方案与需求,输出**每张表的完整字段结构**。
输出严格 JSON(不要 markdown 代码块),结构:
{{"sheets":[{{"key":"customer","title":"客户表","nameSchema":"{{cname}}","useOwner":false,
   "group":"基础资料","layout":"auto4",
   "controls":[
     {{"type":"text","key":"cname","label":"客户名称","required":true}},
     {{"type":"dropdown","key":"ctype","label":"客户类型","dict":"客户类型"}},
     {{"type":"query","key":"prj","label":"关联项目","assoc":"project"}},
     {{"type":"subtable","key":"items","label":"明细",
        "columns":[{{"type":"text","key":"srv","label":"服务名称"}},
                   {{"type":"number","key":"qty","label":"数量","decimal":2}}]}}
   ]}}],
 "dicts":{{"客户类型":["企业","个人"]}},
 "groups":["基础资料","业务管理"]}}

硬性规则(违反会导致建表失败):
1) 字段 key:字母开头、只含字母数字、无下划线;禁止平台自带名
   (Name/SeqNo/CreatedTime/CreatedBy/ModifiedTime/ModifiedBy/OwnerId/OwnerDeptId/Status/State/ObjectId/WorkflowInstanceId)。
2) query 的 assoc = 目标表的 key;必须先建被引用表,不要自引用。
3) dropdown/radio/checkbox_list 必须有 dict(引用 dicts)或 options(字面量)。
4) member/department/query 若多选则 multi:true。
5) useOwner:true 时前端会自动带申请人/申请部门系统字段,不要把 owner 写进 controls。
6) formula 的 rule 只能引用**本表**字段编码,写 {{字段编码}};只能单独成行。
7) layout 默认 "auto4"(每行 4 列)。
8) 单据类表(申请/合同/报销)建议 useOwner:true;主数据/字典表 useOwner:false。

【可用控件类型】""" + CONTROL_TYPES + """
"""


def _corpus_digest(max_projects=6, max_tables_per=14):
    """知识库摘要:给 LLM 看"过去怎么建的"(紧凑)。"""
    try:
        corpus = E.read_json(os.path.join(KNOWLEDGE, "corpus.json"))
    except Exception:
        return "(暂无参考语料:请上传已有系统/需求资料)"
    lines = []
    for p in corpus.get("projects", [])[:max_projects]:
        lines.append("## 项目 %s" % p["name"])
        for t in p["tables"][:max_tables_per]:
            flds = ", ".join("%s(%s)" % (f.get("label") or f.get("key"),
                                         f.get("type")) for f in t.get("fields", []))
            lines.append("- %s %s: %s" % (t["key"], t["title"], flds))
    return "\n".join(lines) or "(无)"


def _extract_json(text):
    """从 LLM 输出里抠出第一个 JSON 对象(容忍 ```json 包裹与前后废话)。"""
    if not text:
        raise E.EngineError("LLM 返回空")
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    else:
        i, j = text.find("{"), text.rfind("}")
        if i >= 0 and j > i:
            text = text[i:j + 1]
    try:
        return json.loads(text)
    except Exception as e:
        raise E.EngineError("LLM 输出不是合法 JSON: %s" % e)


# ---------------------------------------------------------------- provider
class AIProvider:
    name = "base"

    def propose(self, requirement, hints=None):
        raise NotImplementedError

    def design(self, requirement, proposal=None, base_design=None):
        raise NotImplementedError


class HeuristicProvider(AIProvider):
    """知识库匹配:拿历史项目当草案。离线、确定性、可解释。"""
    name = "heuristic"

    def _match(self, requirement):
        try:
            corpus = E.read_json(os.path.join(KNOWLEDGE, "corpus.json"))
        except Exception:
            return []
        req = requirement or ""
        scored = []
        for p in corpus.get("projects", []):
            words = set()
            for t in p["tables"]:
                words.add(t.get("title") or "")
                for f in t.get("fields", []):
                    words.add(f.get("label") or "")
            for cat, vals in (p.get("enums") or {}).items():
                words.add(cat)
                for v in vals:
                    words.add(v.get("name") if isinstance(v, dict) else v)
            score = sum(1 for w in words if w and len(str(w)) >= 2 and str(w) in req)
            scored.append((score, p))
        scored.sort(key=lambda x: -x[0])
        # 只取**最佳匹配的 1 个**历史项目(合并多个会把无关表也搬进来);
        # 分数为 0 表示无有效匹配 → 返回空,由调用方提示人工/LLM 介入。
        return [scored[0][1]] if scored and scored[0][0] > 0 else []

    def propose(self, requirement, hints=None):
        matches = self._match(requirement)
        tables, relations, assumptions = [], [], []
        for p in matches:
            for t in p["tables"]:
                tables.append({
                    "key": t["key"], "title": t["title"], "role": "参考历史表",
                    "fields_hint": [f.get("label") or f.get("key")
                                    for f in t.get("fields", [])][:12],
                    "rationale": "复用历史项目「%s」" % p["name"],
                    "confidence": "medium",
                })
                for r in t.get("relations") or []:
                    relations.append({"from": t["key"], "to": r["target"],
                                      "field": r["field"], "kind": "关联"})
        if not tables:
            assumptions.append("未命中历史项目,需人工从零设计或接入 LLM 生成")
        return {
            "summary": "基于历史项目「%s」复用的候选方案(启发式匹配,建议接入 LLM 或人工完善)"
                       % "、".join(p["name"] for p in matches),
            "tables": tables, "relations": relations,
            "assumptions": assumptions,
            "gaps": ["启发式仅做项目级匹配,字段级设计需人工确认或启用 LLM"],
            "provider": self.name, "matchedProjects": [p["name"] for p in matches],
        }

    def design(self, requirement, proposal=None, base_design=None):
        matches = self._match(requirement)
        sheets, dicts, groups = [], {}, []
        for proj in matches:
            for t in proj["tables"]:
                sheets.append({"key": t["key"], "title": t["title"],
                               "nameSchema": t.get("nameSchema") or "",
                               "useOwner": bool(t.get("useOwner")),
                               "group": t.get("group") or "",
                               "layout": t.get("layout") or "auto4",
                               "controls": t.get("fields") or []})
            for cat, vals in (proj.get("enums") or {}).items():
                dicts.setdefault(cat, [v.get("name") if isinstance(v, dict) else v
                                       for v in vals])
            for g in proj.get("groups") or []:
                if g not in groups:
                    groups.append(g)
        return {"sheets": sheets, "dicts": dicts, "groups": groups,
                "provider": self.name}


class OpenAICompatProvider(AIProvider):
    """OpenAI 兼容接口(可换任意 base_url)。"""
    name = "llm"

    def __init__(self, base_url, api_key, model, timeout=120):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _chat(self, system, user):
        import httpx
        url = self.base_url + "/chat/completions"
        body = {"model": self.model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "temperature": 0.2,
                "response_format": {"type": "json_object"}}
        headers = {"Authorization": "Bearer " + self.api_key,
                   "Content-Type": "application/json"}
        with httpx.Client(timeout=self.timeout) as cli:
            r = cli.post(url, json=body, headers=headers)
        if r.status_code >= 400:
            raise E.EngineError("LLM HTTP %d: %s" % (r.status_code, r.text[:300]))
        data = r.json()
        try:
            return data["choices"][0]["message"]["content"]
        except Exception:
            raise E.EngineError("LLM 响应结构异常: %s" % json.dumps(data)[:300])

    def propose(self, requirement, hints=None):
        user = "【业务需求】\n%s\n\n【补充线索】%s" % (requirement or "",
                                             json.dumps(hints or {}, ensure_ascii=False))
        out = _extract_json(self._chat(_SYS_PROPOSE.format(corpus=_corpus_digest()), user))
        out["provider"] = self.name
        return out

    def design(self, requirement, proposal=None, base_design=None):
        user = ("【业务需求】\n%s\n\n【已确认方案】\n%s\n\n【参考历史语料】\n%s"
                % (requirement or "",
                   json.dumps(proposal or {}, ensure_ascii=False),
                   _corpus_digest()))
        out = _extract_json(self._chat(_SYS_DESIGN, user))
        out["provider"] = self.name
        return out


def get_provider():
    base = os.environ.get("H3F_LLM_BASE_URL", "").strip()
    key = os.environ.get("H3F_LLM_API_KEY", "").strip()
    model = os.environ.get("H3F_LLM_MODEL", "").strip()
    if base and key and model:
        return OpenAICompatProvider(base, key, model)
    return HeuristicProvider()
