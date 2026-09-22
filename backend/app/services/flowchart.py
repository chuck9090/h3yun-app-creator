# -*- coding: utf-8 -*-
"""业务流程图生成(mermaid)。

  generate_flowchart(plan_markdown, requirement_text="", reference_text="") -> {mermaid, provider}

有 LLM:只输出 mermaid `flowchart` 源码(节点用业务语言:提交申请/审批/回写/归档/通知);
可选的 reference_text 非空时作为「参考资料」并入 prompt(为空则行为不变)。
无 LLM / LLM 失败:从方案 markdown 解析表名,或回退启发式样本关系,生成 `flowchart LR` 骨架。
返回的 mermaid 一定是可被 mermaid.js 渲染的合法文本(以 flowchart/graph 开头)。
"""
import re

from . import llm
from .context import REFERENCE_GUARD

_SYSTEM = """你是业务流程建模专家。请根据《系统设计方案》与需求清单,输出一张**以表单为节点**的业务流程图。
要求:
1. 只输出 mermaid 源码,图类型必须是 `flowchart`(推荐 `flowchart LR`),不要输出任何解释;
2. **节点 = 表单**(用表单名,如「报价单」「销售订单」「采购申购单」),不要出现表编码/key 这类技术名;
3. **边 = 表单之间的业务关系**(产生、流转、引用、回写、触发等),用 `-->|动作|` 标注,
   如 `商机跟进表 -->|转报价| 报价单`、`销售订单 -->|发货| 出库细码单`、`出库细码单 -->|汇入| 对账单`;
4. **按模块分组**:用 `subgraph 模块名` 把同一模块的表单聚在一起,模块名与顺序取自需求清单的「功能模块」;
5. 只画资料中的「需求清单」与设计方案中出现过的表单,**不得引入清单外的表单/节点**;
6. 起止节点清晰,必要的分支用 `|条件|` 标注;
7. 不要输出 ``` 代码块以外的内容;若用 ```mermaid 包裹也可,但内部只能是 mermaid 源码。"""


def _user_prompt(plan_markdown, requirement_text, reference_text=""):
    parts = ["【系统设计方案(基于本项目需求产出)】\n%s" % (plan_markdown or "(空)"),
             "【业务需求补充说明(用户手填,与资料中的「需求清单」共同构成完整需求)】\n%s"
             % (requirement_text or "(空)")]
    if reference_text and reference_text.strip():
        parts.append("【需求资料与参考资料(按下方守则区分使用)】\n%s" % reference_text.strip())
        parts.append(REFERENCE_GUARD)
    return "\n\n".join(parts)


def _extract_mermaid(text: str) -> str:
    """从 LLM 输出里抠出 mermaid 源码(容忍 ``` 包裹与前后说明)。"""
    if not text:
        return ""
    t = text.strip()
    m = re.search(r"```(?:mermaid)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    lines = t.splitlines()
    start = None
    for i, ln in enumerate(lines):
        ls = ln.strip().lower()
        if ls.startswith("flowchart") or ls.startswith("graph"):
            start = i
            break
    if start is None:
        return ""
    return "\n".join(ln.rstrip() for ln in lines[start:]).strip()


def _valid(mermaid: str) -> bool:
    if not mermaid or not mermaid.strip():
        return False
    head = mermaid.strip().splitlines()[0].strip().lower()
    return head.startswith("flowchart") or head.startswith("graph")


_TABLE_ROW = re.compile(r"^\|\s*([A-Za-z][A-Za-z0-9]*)\s*\|\s*([^|\n]+?)\s*\|", re.M)


def _tables_from_plan(plan_markdown: str):
    """从方案 markdown 的「表盘点」表格里解析出 (key, 表单名)。"""
    out, seen = [], set()
    for key, title in _TABLE_ROW.findall(plan_markdown or ""):
        if key in seen or key.lower() in ("table",):
            continue
        seen.add(key)
        out.append((key, title.strip().strip("`")))
    return out


def _sanitize_id(key: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]", "", key or "")
    if not s or not s[0].isalpha():
        s = "n" + s
    return "T" + s


def _heuristic_flow(plan_markdown: str, requirement_text: str = "") -> str:
    """离线骨架:方案里的表 + (可选)启发式样本关系。"""
    tables = _tables_from_plan(plan_markdown)
    relations = []
    from h3service.ai import HeuristicProvider
    prop = HeuristicProvider().propose(requirement_text or plan_markdown or "")
    for r in prop.get("relations") or []:
        if r.get("from") and r.get("to"):
            relations.append((r["from"], r["to"], r.get("kind") or "关联"))
    if not tables:
        for t in prop.get("tables") or []:
            tables.append((t.get("key", ""), t.get("title") or t.get("key", "")))

    # 去重表,并补齐关系里出现但表盘点缺失的节点
    titles, order = {}, []
    for key, title in tables:
        if key and key not in titles:
            titles[key] = title or key
            order.append(key)
    for a, b, _ in relations:
        for k in (a, b):
            if k and k not in titles:
                titles[k] = k
                order.append(k)

    lines = ["flowchart LR", "  S((提交申请))"]
    if not order:
        lines.append("  S --> D((归档))")
        return "\n".join(lines)

    lines.append("  S --> %s[%s]" % (_sanitize_id(order[0]), titles[order[0]]))
    for i in range(len(order) - 1):
        a, b = order[i], order[i + 1]
        lines.append("  %s --> %s" % (_sanitize_id(a), _sanitize_id(b)))
    for a, b, kind in relations:
        if a in titles and b in titles:
            lines.append("  %s -->|%s| %s" % (_sanitize_id(a), kind, _sanitize_id(b)))
    lines.append("  %s --> D((归档))" % _sanitize_id(order[-1]))
    return "\n".join(lines)


def generate_flowchart(plan_markdown: str, requirement_text: str = "",
                       reference_text: str = "") -> dict:
    provider = llm.get_provider()
    if getattr(provider, "available", False):
        try:
            user = _user_prompt(plan_markdown, requirement_text, reference_text)
            mmd = _extract_mermaid(provider.complete(_SYSTEM, user))
            if _valid(mmd):
                return {"mermaid": mmd, "provider": provider.name}
        except Exception:
            pass
    return {"mermaid": _heuristic_flow(plan_markdown, requirement_text),
            "provider": "heuristic"}
