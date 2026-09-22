# -*- coding: utf-8 -*-
"""系统设计方案生成(markdown)。

  generate_plan(requirement_text, documents_text="", instruction=None) -> {markdown, provider}

有 LLM:按内置设计 SOP 生成**客户可交付**的《系统设计方案》Markdown
(格式:标题1=模块、标题2=表单、其下编号列出业务内容;**不含字段 key、不含界面配置** —— 那是 ER 阶段的事),
**参考资料 = 用户上传的文档(已有系统/需求/会议) + 本部署已建项目的语料**,不含任何内置样本。
无 LLM / LLM 失败:回退 h3service.ai.HeuristicProvider,拼一份草案。
任何异常都在本模块内部兜底,绝不抛给接口(失败即回退启发式)。
"""
import os
import re

from ..core import config as C
from . import llm
from .context import REFERENCE_GUARD

_SYSTEM = """你是氚云低代码平台的企业系统架构师,负责把「粗业务需求」整理成一份**可直接给客户评审**的《系统设计方案》(Markdown)。

**这份方案是后续「业务流程图」与「ER 结构」的唯一依据** —— 因此必须写全:每个业务表单的**全部字段**、
**业务逻辑/规则**、以及表单之间的**关系**。漏写字段或规则,后续就会漏建字段或漏配自动化。

写作要求:
- 面向客户:只讲业务,**不出现任何技术实现细节** —— 不写字段的英文编码/key、不写数据库表名、
  不写界面该如何配置(那些属于后续 ER 设计,不在本方案中);
- 字段用**中文业务名称**逐个列出(如"合同编号、签订日期、用款金额");可顺带注明类型/是否必填/默认值,
  如"签订日期(日期,必填)"、"金额(元)(金额,2 位小数)";
- 每个表单的「业务内容」用**阿拉伯数字逐项**列出,一项一句,便于客户逐条阅读与确认。

设计 SOP:
1. 先对照【设计知识库】找同类历史项目,复用其业务命名与口径;
2. **模块划分与顺序必须与需求清单的「功能模块」一致**(见资料中的「需求清单」/【需求清单·必须设计的表单】),
   不得自创模块名或顺序;同一模块的表单排在一起;
3. **需求清单中列出的每一个表单都必须出现(一个不漏)**;
4. 每个表单先写「业务内容:」,再逐项列出:
   ① **全部字段**(一个不漏,含主表字段与**子表/明细的列**),子表写成「XX明细:列1、列2、…」;
   ② **业务规则**(取值来源、计算公式、默认值、状态流转、校验与审批口径);
   ③ **与其他表单的关系**(这条记录由哪个表单生成、关联/引用哪个表单、会回写/联动哪个表单);
   ④ **流程触发**(该表单生效/提交后,是否**生成/推进**下一张表单);
5. 说明模块之间、表单之间的关系(由哪个生成、关联/联动哪个、回写哪个),被引用的表单应先在方案中出现;
6. 写明关键口径(编号规则、状态取值、金额与数量口径、审批/流程口径);
7. 主动补客户没想到、但同类系统通常都有的表/字段/规则,列到「待确认」并标 ▲;
8. 无法确定且影响大的项,列到「待确认」,逐条编号并标 ?;
9. 本次需求以资料中的「需求清单」为**基准**(覆盖完整但可能简略),用「会议纪要」「其他」补充细化;
   【设计知识库】/【外部参考资料】仅供复用口径与设计惯例,**不得**引入与本次需求无关的模块。

**看板 / 报表 / 统计 / 分析 / 总览 / 监控 类**(它们是对数据的展示,不是业务实体):
- 方案里可以保留(供客户了解),但请**单独成模块**(模块名含「看板 / 报表 / 统计 / 分析」等),
  或表单名含这些字眼即可 —— 后续生成流程图与 ER 时**会自动排除**(不建表、不进应用)。

输出格式(严格使用以下章节结构,**纯 Markdown,不要寒暄、不要代码块围栏**):
# 项目概述
(业务背景、建设目标、范围、整体思路;可在此概述模块之间的关系)
# <模块名>
## <表单名>
业务内容:
1. <第一条:如 用于录入某某,字段:字段A、字段B(类型/必填)、…>
2. <第二条:如 XX明细:列A、列B、…>
3. <第三条:业务规则,如 金额 = 数量 × 单价,保留 2 位小数>
4. <第四条:关系,如 由【报价单】转来;关联【客户档案】>
5. <第五条:流程,如 生效后生成【发货单】>
# <下一个模块名>
## <表单名>
业务内容:
1. ...
# 模块与表关系
(逐条说明:某表单 → 生成/关联/回写 某表单)
# 关键口径
(编号 / 状态 / 金额 / 数量 / 审批 等统一口径)
# 待确认
1. ? <需客户决策的事项>
2. ▲ <建议补充项>

【结构范例(行业、公司、表单、字段均为虚构,仅供格式参考,与实际项目无关)】
# 项目概述
面向连锁零售企业,建设门店与商品、销售打通的业务系统,统一基础资料与单据流转。
# 基础资料
## 商品档案
业务内容:
1. 用于录入商品基础信息,字段:商品编码、商品名称、规格、单位、商品分类、标准售价、成本价、是否启用;
2. 价格明细:生效日期、销售价、采购价;
3. 商品编码由系统按「分类码+流水」自动生成,只读;
4. 停用的商品不再出现在开单选择中。
## 门店档案
业务内容:
1. 用于录入门店基础信息,字段:门店编码、门店名称、所属区域、店长、开业日期、状态;
2. 一个区域下可以有多个门店。
# 销售管理
## 销售订单
业务内容:
1. 用于录入客户销售订单,字段:订单编号、客户、下单日期、交货日期、销售员、订单状态、备注;
2. 商品明细:商品、数量、单价、金额;
3. 订单金额 = 各明细金额之和,提交时自动计算;
4. 流程结束时:按商品明细生成【发货单】,订单状态更新为「已发货」。
# 模块与表关系
- 销售订单 → 发货单:订单生效后生成发货单;
- 销售订单 --关联--> 客户档案、商品档案(含价格明细子表)。
# 关键口径
- 编码:商品编码系统生成、只读;订单编号按「SO+年月+流水」;
- 状态:草稿 / 审批中 / 已生效 / 已作废;
- 金额:单价含税,金额 = 数量 × 单价,保留 2 位小数。
# 待确认
1. ? 是否需要多门店库存调拨?
2. ▲ 建议补充商品图片与条码字段,便于扫码开单。
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
    # F3 双保险:生成前按当前 DB 现算 library.md,避免读到已删除资料
    try:
        from .library import render_library_digest
        render_library_digest()
    except Exception:
        pass
    parts = []
    # 全局资料库(用户上传的已有系统资料)优先,其次是已建项目语料
    for name in ("library.md", "corpus.md", "patterns.md"):
        txt = _read_knowledge_head(name, max_lines_per_file)
        if txt:
            parts.append("### 知识库文件 %s\n%s" % (name, txt))
    return "\n\n".join(parts) or "(暂无参考语料:可在「资料库」上传已有系统资料)"


def _user_prompt(requirement_text, reference_text, instruction):
    parts = ["【业务需求补充说明(用户手填,与下方资料中的「需求清单」共同构成完整需求)】\n%s"
             % (requirement_text or "(空)")]
    if reference_text and reference_text.strip():
        parts.append("【需求资料与参考资料(按下方守则区分使用)】\n%s" % reference_text.strip())
        parts.append(REFERENCE_GUARD)
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


def _heuristic_plan(requirement_text):
    """无 LLM 回退:用已积累的项目语料匹配结果拼一份 markdown 草案。

    输出采用与 LLM 一致的**客户可交付格式**(模块 H1 / 表单 H2 / 编号业务内容);
    启发式没有模块与字段级信息,故模块占位、业务内容仅给角色与依据。
    """
    from h3service.ai import HeuristicProvider
    prop = HeuristicProvider().propose(requirement_text or "")
    tables = prop.get("tables") or []
    relations = prop.get("relations") or []
    matched = prop.get("matchedProjects") or []

    lines = ["# 项目概述", "",
             prop.get("summary") or "未命中历史样本,需人工从零设计。", "",
             "> 本方案由启发式知识库匹配生成,**模块划分与业务内容需人工/接入 LLM 完善**。", ""]

    lines += ["# 业务表单(模块归属待人工确认)", ""]
    if tables:
        for t in tables:
            title = t.get("title") or t.get("key") or "未命名表单"
            bits = []
            if t.get("role"):
                bits.append("角色:%s" % t["role"])
            if t.get("rationale"):
                bits.append("依据:%s" % t["rationale"])
            lines += ["## %s" % title, "", "业务内容:", "",
                      "1. %s" % ("；".join(bits) or "字段与业务规则待补充。"), ""]
    else:
        lines += ["(未命中历史样本:请人工补充模块与表单)", ""]

    lines += ["# 模块与表关系", ""]
    if relations:
        for r in relations:
            lines.append("- %s --(%s)--> %s" % (r.get("from", ""), r.get("field", ""),
                                                r.get("to", "")))
    else:
        lines.append("(待补充:请人工确认表单间关联)")
    lines.append("")

    lines += ["# 关键口径", "",
              "- 编码规则、状态取值、金额/数量口径需人工确认;",
              "- 下拉/单选一般存所选文本本身,需要代码位的另建字典表;",
              "- 单据类表单使用系统拥有者(申请人/申请部门),不要写成字段。", ""]

    lines += ["# 待确认", ""]
    n = 0
    for a in (prop.get("assumptions") or []):
        n += 1
        lines.append("%d. ▲ %s" % (n, a))
    for g in (prop.get("gaps") or []):
        n += 1
        lines.append("%d. ? %s" % (n, g))
    if n == 0:
        lines.append("1. ? 模块划分、表单结构与字段口径需人工确认。")
    lines.append("")

    if matched:
        lines += ["---", "", "参考已积累语料:%s" % "、".join(matched)]
    return "\n".join(lines).strip()


def generate_plan(requirement_text: str, reference_text: str = "",
                  instruction: str = None, progress=None, provider=None) -> dict:
    def _p(msg, pct=None, level="info"):
        if progress:
            progress(msg, pct=pct, level=level)

    provider = provider or llm.get_provider()
    if getattr(provider, "available", False):
        _p("组装提示词(设计 SOP + 知识库节选)", pct=72)
        try:
            system = _SYSTEM + "\n\n【设计知识库(节选)】\n" + _knowledge_digest()
            _p("调用大模型生成系统设计方案…", pct=78)
            raw = provider.complete(system, _user_prompt(requirement_text, reference_text, instruction))
            _p("解析模型输出", pct=92)
            md = _strip_fence(raw)
            if md and len(md) >= 20:
                return {"markdown": md, "provider": provider.name}
            _p("模型输出过短,回退启发式草案", pct=94, level="warning")
        except Exception as e:
            _p("大模型调用失败(%s),回退启发式草案" % str(e)[:160], pct=94, level="warning")
    else:
        _p("未配置大模型,使用启发式知识库生成草案", pct=78, level="warning")
    return {"markdown": _heuristic_plan(requirement_text), "provider": "heuristic"}
