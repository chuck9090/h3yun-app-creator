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


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TABLE_ROW = re.compile(r"^\|\s*([A-Za-z][A-Za-z0-9]*)\s*\|\s*([^|\n]+?)\s*\|", re.M)


def _tables_from_plan(plan_markdown: str):
    """从方案解析出表单清单 [(id, 表单名)]。

    新方案格式:模块为 H1、表单为 H2,且表单标题下紧跟「业务内容:」;方案里**无 key**,
    按出现顺序生成稳定 id(form1、form2…)。
    识别不到(旧格式方案 / 用户手改)→ 回退兼容旧的「表盘点」表格。
    """
    text = plan_markdown or ""
    lines = text.splitlines()
    out, seen = [], set()
    for i, ln in enumerate(lines):
        m = _HEADING.match(ln)
        if not m or len(m.group(1)) != 2:          # 只看 H2
            continue
        title = m.group(2).strip().strip("`").strip()
        if not title or title in seen:
            continue
        # 表单标题的判据:后面紧跟的**首个非空行**是「业务内容」(避免把
        # 旧格式的「## 一、项目概述 / ## 二、表盘点 …」等章节标题误当表单)
        nxt = ""
        for j in range(i + 1, min(i + 6, len(lines))):
            t = lines[j].strip()
            if t:
                nxt = t
                break
        if not nxt.startswith("业务内容"):
            continue
        seen.add(title)
        out.append(title)
    if out:
        return [("form%d" % (i + 1), t) for i, t in enumerate(out)]
    rows, s2 = [], set()
    for key, title in _TABLE_ROW.findall(text):
        if key in s2 or key.lower() in ("table",):
            continue
        s2.add(key)
        rows.append((key, title.strip().strip("`")))
    return rows


def _sanitize_id(key: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]", "", key or "")
    if not s or not s[0].isalpha():
        s = "n" + s
    return "T" + s


def _heuristic_flow(plan_markdown: str, requirement_text: str = "") -> str:
    """离线骨架:方案里的表单(H2)按顺序连成流程,并尽力接上启发式样本关系。"""
    tables = _tables_from_plan(plan_markdown)
    from h3service.ai import HeuristicProvider
    prop = HeuristicProvider().propose(requirement_text or plan_markdown or "")
    if not tables:
        for t in prop.get("tables") or []:
            key = t.get("key") or ""
            if key:
                tables.append((key, t.get("title") or key))

    # 去重:保持出现顺序
    titles, order = {}, []
    for key, title in tables:
        if key and key not in titles:
            titles[key] = title or key
            order.append(key)

    # 关系:启发式的 key 关系按「表单名」映射到本方案的表单(方案里已无 key)
    by_title = {str(t).strip(): k for k, t in tables}
    key2title = {t.get("key"): (t.get("title") or t.get("key"))
                 for t in (prop.get("tables") or []) if t.get("key")}
    relations = []
    for r in prop.get("relations") or []:
        ia = by_title.get(str(key2title.get(r.get("from")) or "").strip())
        ib = by_title.get(str(key2title.get(r.get("to")) or "").strip())
        if ia and ib:
            relations.append((ia, ib, r.get("kind") or "关联"))
    for a, b, _ in relations:
        for k in (a, b):
            if k and k not in titles:
                titles[k] = k
                order.append(k)

    lines = ["flowchart LR", "  S((提交申请))"]
    if not order:
        lines.append("  S --> D((归档))")
        return "\n".join(lines)

    # 先声明全部节点(带业务名标签,引号包裹以防标题含标点破坏语法),再画流转与关系
    for k in order:
        label = str(titles[k]).replace('"', "'")
        lines.append('  %s["%s"]' % (_sanitize_id(k), label))
    lines.append("  S --> %s" % _sanitize_id(order[0]))
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
