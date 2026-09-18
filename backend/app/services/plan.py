# -*- coding: utf-8 -*-
"""系统设计方案生成(markdown)。

  generate_plan(requirement_text, documents_text="", instruction=None) -> {markdown, provider}

有 LLM:按内置设计 SOP 生成结构化《系统设计方案》Markdown,
**参考资料 = 用户上传的文档(已有系统/需求/会议) + 本部署已建项目的语料**,不含任何内置样本。
无 LLM / LLM 失败:回退 h3service.ai.HeuristicProvider,拼一份草案。
任何异常都在本模块内部兜底,绝不抛给接口(失败即回退启发式)。
"""
import os
import re

from ..core import config as C
from . import llm

_SYSTEM = """你是氚云低代码平台的企业系统架构师,负责把「粗业务需求」整理成一份可评审的《系统设计方案》(Markdown)。
请严格遵循以下设计 SOP:
1. 先对照【设计知识库】找同类历史项目;能复用的表、关系、字段语义码直接复用,保持跨项目一致;
2. 盘点建议的表(表 key / 表单名 / 角色 / 依据 / 置信度),置信度用 ●(确定)/▲(推断)/?(存疑) 三档标注;
3. 说明表与表的关系(关联 query / 联动 dropdown / 子表),被引用的表必须排在前面;
4. 写明关键口径(编码、状态、金额、日期、审批、存名称还是代码等);
5. 主动补客户没想到、但同类系统通常都有的表/字段/关系,逐条标 ▲ 并给默认值;
6. 无法确定且影响大的项,统一列到「待确认」并标 ?;
7. 列出需在氚云界面手工配置的项(必填/只读/审批流/联动/视图等)。

硬性约束:
- 字段 key 必须字母开头、只含字母数字、无下划线,且避开平台自带编码
  (Name/SeqNo/CreatedTime/CreatedBy/ModifiedTime/ModifiedBy/OwnerId/OwnerDeptId/Status/State/ObjectId/WorkflowInstanceId);
- 输出纯 Markdown,严格使用下面的章节结构,不要输出与方案无关的寒暄。

# 系统设计方案
## 一、项目概述
## 二、表盘点
| 表 key | 表单名 | 角色 | 依据 | 置信度 |
|---|---|---|---|---|
## 三、表关系
## 四、关键口径
## 五、漏项补全(▲ 建议,请确认)
## 六、待确认(? 必须人工决策)
## 七、界面手工配置项
"""


def _read_knowledge_head(name, max_lines):
    p = os.path.join(C.KNOWLEDGE_DIR, name)
    if not os.path.isfile(p):
        return ""
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return ""
    head = lines[:max_lines]
    if len(lines) > max_lines:
        head.append("...(已截断)")
    return "\n".join(head)


def _knowledge_digest(max_lines_per_file=120):
    parts = []
    for name in ("corpus.md", "patterns.md"):
        txt = _read_knowledge_head(name, max_lines_per_file)
        if txt:
            parts.append("### 知识库文件 %s\n%s" % (name, txt))
    return "\n\n".join(parts) or "(暂无参考语料:可在本项目上传已有系统/需求资料)"


def _user_prompt(requirement_text, documents_text, instruction):
    parts = ["【业务需求】\n%s" % (requirement_text or "(空)")]
    if documents_text and documents_text.strip():
        parts.append("【补充文档(已解析文本)】\n%s" % documents_text.strip())
    if instruction and instruction.strip():
        parts.append("【额外指令】\n%s" % instruction.strip())
    return "\n\n".join(parts)


def _strip_fence(text):
    """剥掉 ```markdown 围栏(整体包裹或夹杂在前后说明之间);保留正文。"""
    t = (text or "").strip()
    m = re.search(r"```(?:markdown|md)?\s*\n(.*?)```", t, re.S)
    if m:
        return m.group(1).strip()
    return t


_CONF = {"high": "●", "medium": "▲", "low": "?"}


def _heuristic_plan(requirement_text):
    """无 LLM 回退:用已积累的项目语料匹配结果拼一份 markdown 草案。"""
    from h3service.ai import HeuristicProvider
    prop = HeuristicProvider().propose(requirement_text or "")
    tables = prop.get("tables") or []
    relations = prop.get("relations") or []
    matched = prop.get("matchedProjects") or []

    lines = ["# 系统设计方案(启发式草案)", ""]
    lines.append("> 本方案由启发式知识库匹配生成,未经 LLM 润色。"
                 "**启发式草案,建议接入 LLM 或人工完善**。")
    lines.append("")

    lines += ["## 一、项目概述", "", prop.get("summary") or "未命中历史样本,需人工从零设计。", ""]

    lines += ["## 二、表盘点", "",
              "| 表 key | 表单名 | 角色 | 依据 | 置信度 |",
              "|---|---|---|---|---|"]
    if tables:
        for t in tables:
            lines.append("| %s | %s | %s | %s | %s |" % (
                t.get("key", ""), t.get("title", ""), t.get("role", ""),
                t.get("rationale", ""), _CONF.get(t.get("confidence"), "▲")))
    else:
        lines.append("| - | - | - | 未命中历史样本 | ? |")
    lines.append("")

    lines += ["## 三、表关系", ""]
    if relations:
        for r in relations:
            lines.append("- `%s` --(%s)--> `%s`" % (
                r.get("from", ""), r.get("field", ""), r.get("to", "")))
    else:
        lines.append("(待补充:请人工确认表间关联)")
    lines.append("")

    lines += ["## 四、关键口径", "",
              "- 字段 key:字母开头、纯字母数字、无下划线,避开平台自带编码;",
              "- 下拉默认存所选文本本身,需要代码位的另建字典表;",
              "- 单据类表单使用系统拥有者(申请人/申请部门),不要写进字段。", ""]

    lines += ["## 五、漏项补全(▲ 建议,请确认)", ""]
    assumptions = prop.get("assumptions") or []
    if assumptions:
        for a in assumptions:
            lines.append("- ▲ %s" % a)
    else:
        lines.append("- ▲ 建议按标准表型补齐:名称/编码/状态/日期/负责人/备注/附件。")
    lines.append("")

    lines += ["## 六、待确认(? 必须人工决策)", ""]
    gaps = prop.get("gaps") or []
    if gaps:
        for g in gaps:
            lines.append("- ? %s" % g)
    else:
        lines.append("- ? 表结构与字段口径需人工确认。")
    lines.append("")

    lines += ["## 七、界面手工配置项", "",
              "- 必填 / 只读 / 审批流 / 字段联动 / 列表视图等平台 API 无法配置的项,建表后到氚云界面另配。", ""]

    if matched:
        lines += ["---", "", "参考已积累语料:%s" % "、".join(matched)]
    return "\n".join(lines).strip()


def generate_plan(requirement_text: str, documents_text: str = "",
                  instruction: str = None) -> dict:
    provider = llm.get_provider()
    if getattr(provider, "available", False):
        try:
            system = _SYSTEM + "\n\n【设计知识库(节选)】\n" + _knowledge_digest()
            raw = provider.complete(system, _user_prompt(requirement_text, documents_text, instruction))
            md = _strip_fence(raw)
            if md and len(md) >= 20:
                return {"markdown": md, "provider": provider.name}
        except Exception:
            pass
    return {"markdown": _heuristic_plan(requirement_text), "provider": "heuristic"}
