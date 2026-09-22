# -*- coding: utf-8 -*-
"""业务流程图生成(mermaid)。

  generate_flowchart(plan_markdown) -> {mermaid, provider, nodes, edges, dense}

**唯一依据 = 《系统设计方案》**(方案已包含完整字段、业务逻辑与表间关系,是流水线的源头):
流程图不再看原始需求/参考资料,以免与方案口径不一致。
有 LLM:输出分模块、干净可读的 mermaid `flowchart`;**看板/报表类不进流程图**(非业务流转)。
无 LLM / LLM 失败:按方案解析「模块 → 表单」,生成分模块纵向链骨架。
返回的 mermaid 一定是可被 mermaid.js 渲染的合法文本(以 flowchart/graph 开头)。
"""
import re

from . import llm
from .context import is_report_entity

_SYSTEM = """你是业务流程建模专家。请根据《系统设计方案》输出一张**分模块、干净可读**的业务流程图。
**唯一依据是这份方案**(方案里已写明每个表单的字段、业务逻辑与表间关系),不要臆造方案之外的内容。

【范围】
0. 只画**业务表单**(发生在业务流转链上的单据/档案);**看板 / 报表 / 统计 / 分析 / 总览 / 监控 类一律排除**,
   它们是对数据的展示,不在业务流程里(方案中若出现这些模块或表单,直接跳过)。

【总体形态】
1. 只输出 mermaid 源码,图类型必须是 `flowchart LR`(模块**横向**排布),不要输出任何解释;
2. **每个模块**用一个 `subgraph` 分区,**模块名与顺序取自方案的各级标题**(方案本身就是 H1=模块);
   子图内先写 `direction TB`(模块内纵向、模块间横向):
   ```
   flowchart LR
     subgraph M1["销售管理"]
       direction TB
       A[潜在/成交客户] --> B[报价单] --> C[销售订单]
     end
     subgraph M2["采购管理"]
       direction TB
       P1[供应商] --> P2[采购申请] --> P3[采购订单]
     end
   ```
3. **节点 = 业务表单**(用表单名,如「报价单」「销售订单」「采购申请」),不要出现表编码/key;
4. 关键单据用矩形 `[名称]`;辅助/状态类用圆角 `(名称)`;起止用 `([名称])`。

【边的纪律(最重要:直接决定图是否清晰)】
5. **只画「业务流转」**:上一环节完成后**驱动/生成/推进**到下一环节(提交、审批、生成、入库、出库、发货、对账、开票…),用 `-->|动作|` 标注;
6. **严禁**画「静态引用关系」——例如「物料档案被报价单引用」「客户档案为销售订单提供客户」「BOM 为工单提供数据」。
   基础资料/档案类表单**作为独立节点列出即可,不要连"被引用"的边**(参考:主数据通常孤立摆在模块内)。
   ⚠ 这是流程图变蜘蛛网的首要原因,必须避免;
7. **每个模块内只画一条主流程链**(按方案中的业务先后纵向串联),确有分支才分叉,用 `|条件|` 标注(如 `-->|不合格|`);
8. **跨模块只保留关键交接**(如 `销售订单 -->|发货| 销售出库单`、`采购订单 -->|到货| 采购入库单`),
   每个模块对外一般不超过 3 条;不要跨模块连"参考/查询/统计"类关系;
9. 控制规模:总边数 ≈ 节点数 × 1.0~1.2,**不得超过节点数的 1.5 倍**;宁可少画也不要画满。

10. 不要输出 ``` 代码块以外的内容;若用 ```mermaid 包裹也可,但内部只能是 mermaid 源码。"""


def _user_prompt(plan_markdown):
    return "【系统设计方案(唯一依据)】\n%s" % (plan_markdown or "(空)")


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
        if not title or title in seen or is_report_entity(title):
            continue                                # 看板/报表类不进流程图
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


# 方案尾部固定章节(不是模块,不参与建图)
_TAIL_SECTIONS = {"项目概述", "模块与表关系", "关键口径", "待确认"}


def _plan_structure(plan_markdown: str, exclude_reports: bool = True):
    """从方案解析出 [(模块名, [表单名, ...]), ...]。

    新格式:H1=模块、H2=表单(H2 后首个非空行须为「业务内容」)。
    `exclude_reports=True`(默认)排除**看板/报表**类模块与表单(它们不进流程图与 ER);
    方案完整性校验时可传 False(方案里本就该包含看板/报表,只是后续不建表)。
    识别不到则回退:全部表单归入一个「业务表单」模块。
    """
    lines = (plan_markdown or "").splitlines()
    modules = []
    cur_mod = None
    seen = set()
    for i, ln in enumerate(lines):
        m = _HEADING.match(ln)
        if not m:
            continue
        lvl = len(m.group(1))
        title = m.group(2).strip().strip("`").strip()
        if lvl == 1:
            cur_mod = None
            # 模块名不单独判报表:交给**表单级**过滤(与 ER 的判定口径一致)。
            # 若某模块下的表单全被过滤,该空模块会在最后被剔除(自然消失)。
            if title and title not in _TAIL_SECTIONS:
                cur_mod = (title, [])
                modules.append(cur_mod)
            continue
        if lvl != 2 or cur_mod is None or not title or title in seen:
            continue
        if exclude_reports and is_report_entity(title):   # 看板/报表表单:跳过
            continue
        nxt = ""
        for j in range(i + 1, min(i + 6, len(lines))):
            t = lines[j].strip()
            if t:
                nxt = t
                break
        if not nxt.startswith("业务内容"):
            continue
        seen.add(title)
        cur_mod[1].append(title)

    modules = [(name, forms) for name, forms in modules if forms]
    if modules:
        return modules
    # 回退:仅表单清单,单模块
    forms = [t for _, t in _tables_from_plan(plan_markdown)
             if not (exclude_reports and is_report_entity(t))]
    return [("业务表单", forms)] if forms else []


_NODE_DECL = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\s*(?:\[\[|\[\(|\[/|\[\\|\[|[\(\{])")
_MMD_DIRECTIVE = re.compile(
    r"^\s*(subgraph|end|direction|style|classDef|class|linkStyle|click|%%)\b")


def flow_stats(mermaid: str):
    """粗略统计 (节点数, 边数),用于评估图是否过密。

    节点 = **去重后的节点 id**。注意要匹配**行内任意位置**的声明,因为 mermaid 常见的
    链式写法 `A[客户] --> B[报价单] --> C[销售订单]` 会把多个节点写在同一行
    (只数行首会把 3 个节点误算成 1 个,进而把正常图误判为"过密")。
    """
    text = mermaid or ""
    edges = len(re.findall(r"--?>", text))
    ids = set()
    for ln in text.splitlines():
        if _MMD_DIRECTIVE.match(ln):          # subgraph/direction/style… 不是节点
            continue
        for m in _NODE_DECL.finditer(ln):
            ids.add(m.group(1))
    return len(ids), edges


def _sanitize_id(key: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]", "", key or "")
    if not s or not s[0].isalpha():
        s = "n" + s
    return "T" + s


def _heuristic_flow(plan_markdown: str) -> str:
    """离线骨架:按模块分区,每个模块内把表单纵向串联成主流程链。

    无 LLM 时无法得知真实业务流转,故只在**模块内**按方案顺序串联(诚实、可读),
    不臆造跨模块关系。看板/报表类已由 _plan_structure 排除。
    """
    modules = _plan_structure(plan_markdown)
    if not modules:
        from h3service.ai import HeuristicProvider
        prop = HeuristicProvider().propose(plan_markdown or "")
        titles = [t.get("title") or t.get("key") for t in (prop.get("tables") or [])
                  if t.get("key") and not is_report_entity(t.get("title") or t.get("key"))]
        modules = [("业务表单", titles)] if titles else []

    lines = ["flowchart LR"]
    if not modules:
        lines.append("  S([未识别到表单])")
        return "\n".join(lines)

    # 模块内串联;记录「表单名 → 节点 id」以便补跨模块边
    form_to_id, seq = {}, 0
    for mi, (name, forms) in enumerate(modules, 1):
        mod_id = "Mod%d" % mi
        safe_name = str(name).replace('"', "'")
        lines.append('  subgraph %s["%s"]' % (mod_id, safe_name))
        lines.append("    direction TB")
        prev = None
        for f in forms:
            if f in form_to_id:                 # 同名表单只声明一次
                prev = form_to_id[f]
                continue
            seq += 1
            nid = "N%d" % seq
            form_to_id[f] = nid
            label = str(f).replace('"', "'")
            lines.append('    %s["%s"]' % (nid, label))
            if prev:
                lines.append("    %s --> %s" % (prev, nid))
            prev = nid
        lines.append("  end")

    # 末端:无 LLM 时无法得知真实跨模块流转,故【不补】样本关系(那些多是"引用/关联"静态边,
    # 正是把图拉花的元凶)。每个模块保持一条干净的纵向主流程链,交由用户/LLM 再精修。
    return "\n".join(lines)


def generate_flowchart(plan_markdown: str) -> dict:
    """生成业务流程图(**唯一依据 = 系统设计方案**)。

    返回 {mermaid, provider, nodes, edges, dense}。若 LLM 产出的图**过密**
    (边数 > 节点数 × 1.6),会回退为「分模块纵向链」骨架,保证图可读(不出现蜘蛛网)。
    """
    provider = llm.get_provider()
    mmd = ""
    if getattr(provider, "available", False):
        try:
            mmd = _extract_mermaid(provider.complete(_SYSTEM, _user_prompt(plan_markdown)))
        except Exception:
            mmd = ""

    if _valid(mmd):
        nodes, edges = flow_stats(mmd)
        dense = nodes > 0 and edges > max(12, int(nodes * 1.6))
        if not dense:
            return {"mermaid": mmd, "provider": provider.name,
                    "nodes": nodes, "edges": edges, "dense": False}
        # 过密 → 回退为分模块骨架,避免给用户一张无法阅读的蜘蛛网
        fallback = _heuristic_flow(plan_markdown)
        fn, fe = flow_stats(fallback)
        return {"mermaid": fallback, "provider": "%s+密度回退" % provider.name,
                "nodes": fn, "edges": fe, "dense": True,
                "denseStats": {"nodes": nodes, "edges": edges}}

    fallback = _heuristic_flow(plan_markdown)
    fn, fe = flow_stats(fallback)
    return {"mermaid": fallback, "provider": "heuristic",
            "nodes": fn, "edges": fe, "dense": False}
