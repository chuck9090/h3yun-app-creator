# -*- coding: utf-8 -*-
"""参考资料 → 喂给模型的上下文(带 token 预算、结构化优先、目录式按需取件)。

三种模式:
  inline    总预算内 → 全部文件的紧凑内容一次喂入;
  truncated 超预算但未超目录阈值 → 按文件均分预算,优先保留"字段/列名",数据行与正文截断;
  catalog   超目录阈值 → 只给「文件目录 + 一行简介」,再由模型按需索取具体文件(agent 式)。

"紧凑内容"来自 services.extract 的结构化抽取(列名/字段无损,数据行只留样例),
因此相对于直接把 parsed_text 全量拼接,既省 token 又不丢字段信息。
"""
import json
import time

from ..core import config as C
from ..db import database as db
from . import extract as EX

MODE_INLINE = "inline"
MODE_TRUNCATED = "truncated"
MODE_CATALOG = "catalog"

_MAX_PROSE_CHARS = 4000      # 单文件正文(非表格)在紧凑渲染里的上限

# ---------------------------------------------------------------- 资料角色与分组
# 项目上传文档按用户选择的「资料类型」区分角色:
#   requirement 需求清单 —— 本次用户需求的**基准与总纲**;每项目**只允许一份**;
#   meeting     会议纪要 —— 对需求的补充:澄清细节、补规则/例外、明确含糊处(可多份);
#   other       其他     —— 其余补充资料,同样用于补齐需求未展开处(可多份);
#   existing_system 现有系统资料(历史数据,已收敛到「资料库」)。
# 资料库勾选的资料则属**外部参考资料**:同类系统的既有资料,不是本项目需求。
_DOC_GROUPS = (
    ("requirement", "【需求清单(本项目需求的基准与总纲)】"),
    ("meeting", "【会议纪要(用于补充与细化上述需求)】"),
    ("other", "【其他补充资料(用于补齐需求未展开处)】"),
    ("existing_system", "【现有系统资料(参考)】"),
)
_DOC_LABEL = {"requirement": "需求清单", "meeting": "会议纪要", "other": "其他",
              "existing_system": "现有系统资料"}
_DOC_ORDER = {k: i for i, (k, _) in enumerate(_DOC_GROUPS)}
# 资料库勾选的资料属"外部参考资料",由 pipeline 拼在项目需求资料之后,带此标题以示区分。
EXTERNAL_REF_TITLE = "【外部参考资料(同类系统的既有资料,非本项目需求,仅供字段/口径参考)】"

# 供 plan / design / flowchart 组装提示词时复用。资料分两类:本项目需求资料(含基准的
# 「需求清单」)与外部参考资料;若不显式区分,模型要么把外部资料当成本次需求照搬,要么
# 忽略会议纪要等补充。出处:实测「参考资料被当成项目需求」「需求清单与补充资料不分」。
REFERENCE_GUARD = """【资料使用守则(必须遵守)】
下面提供的资料分两类,请严格区分、各自按规则使用:

一、本项目需求资料(节标题为「需求清单」「会议纪要」「其他」)
1. 「需求清单」是本次用户需求的**基准与总纲**(记录了必须实现的模块与表单),
   其内容可能较简略,但**必须完整覆盖**;
2. 「会议纪要」「其他」是对需求的**补充**:澄清细节、补充规则与例外、明确含糊之处;
3. 设计时以「需求清单」为主线组织表与模块,再用补充资料把需求未展开的细节补齐
   (需求清单是骨架,补充资料是血肉),二者结合构成本次项目的**完整需求**。

二、外部参考资料(节标题为「外部参考资料」)
4. 它们是同类系统的既有资料,**不是本项目需求**;
5. 仅可用于借鉴字段命名/字段类型/通用口径/设计惯例;
6. **不得**把其中出现、但本项目需求未提及的表、字段、模块、流程、审批照搬进结果。

通用规则:
7. 若资料之间、或资料与本项目需求冲突,一律以「需求清单」为准;
8. 输出前自检:是否存在"只因外部参考资料里有、而本项目需求中并无依据"的表/模块?如有,删除。"""
_EXTRACT_SCHEMA = 2          # 抽取缓存结构版本(结构变更时递增,旧缓存自动失效)


def estimate_tokens(text: str) -> int:
    """保守估算 token:中文按 1 字≈1 token,非中文按 4 字符≈1 token(宁高不低)。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cjk + (len(text) - cjk) / 4) + 1


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 抽取 + 缓存
def get_or_extract(doc, provider, on_step=None):
    """取文档的结构化抽取结果;有缓存直接复用,否则抽取后写库缓存。

    缓存键纳入「抽取结构版本 + 是否启用视觉 + 抽取实现版本」:先未配视觉时缓存的
    "需配置视觉模型"note,在事后配好视觉后会自动失效并重新识别(避免复用陈旧结果)。
    """
    vis = bool(EX._vision_enabled(provider))
    ext_ver = getattr(EX, "VERSION", 1)
    cached = doc.get("extract_json")
    if cached:
        try:
            data = json.loads(cached)
            if (data.get("_schema") == _EXTRACT_SCHEMA
                    and bool(data.get("_vis")) == vis
                    and data.get("_ext_ver") == ext_ver):
                data.pop("_schema", None)
                data.pop("_vis", None)
                data.pop("_ext_ver", None)
                data["_cached"] = True
                return data
        except Exception:
            pass
    if on_step:
        on_step(doc)
    data = EX.extract_document(doc, provider)
    dump = dict(data, _schema=_EXTRACT_SCHEMA, _vis=vis, _ext_ver=ext_ver)
    try:
        db.update_document(doc["id"], extract_json=json.dumps(dump, ensure_ascii=False),
                           extract_status=data.get("status", ""), extract_at=_now())
    except Exception:
        pass
    data["_cached"] = False
    return data


# ---------------------------------------------------------------- 渲染
def render_compact(ext, max_rows, text_chars=_MAX_PROSE_CHARS):
    """把抽取结果渲染成紧凑文本。

    **先列全部表的字段清单(列名,完整不截断),再单独给数据样例行**,最后正文。
    这样即使整体超长被截断,字段清单也永远保留 —— 字段信息不会因"文件太大"而丢失。
    """
    tables = ext.get("tables") or []
    parts = []
    if tables:
        fields = ["【表结构/字段清单(完整)】"]
        for t in tables:
            cols = [c for c in (t.get("columns") or []) if c]
            fields.append("- 表「%s」(%d 列):%s"
                          % (t.get("name", ""), len(cols), " | ".join(cols)))
        parts.append("\n".join(fields))
        samples = []
        for t in tables:
            rows = t.get("rows") or []
            if not rows:
                continue
            cols = [c for c in (t.get("columns") or []) if c]
            # 清单表(列数少、行多,如「功能清单」)每行都是需求项:保留全部行,不只取样例
            cap = max_rows
            if len(cols) <= C.CTX_LIST_MAX_COLS:
                cap = max(cap, C.CTX_MAX_LIST_ROWS)
            cap = min(cap, len(rows))
            label = "全量" if cap >= len(rows) else "前 %d 行" % cap
            samples.append("表「%s」数据(共 %d 行,%s):"
                           % (t.get("name", ""), t.get("rowCount", len(rows)), label))
            for r in rows[:cap]:
                samples.append("  " + " | ".join(r))
        if samples:
            parts.append("【数据清单/样例】\n" + "\n".join(samples))
    text = (ext.get("text") or "").strip()
    images = ext.get("images") or []
    img_texts = [(i.get("from"), i.get("text")) for i in images if i.get("text")]
    if img_texts:
        lines = ["【图片识别内容(内嵌截图/扫描件)】"]
        for src, t in img_texts:
            lines.append("▸ %s:\n%s" % (src, t))
        parts.append("\n".join(lines))
    img_notes = [i["note"] for i in images if i.get("note")]
    if text:
        if len(text) > text_chars:
            text = text[:text_chars] + "\n…(正文已截断)"
        parts.append(text)
    if ext.get("note"):
        parts.append("(说明:%s)" % ext["note"])
    if img_notes:
        parts.append("(图片说明:%s)" % "、".join(img_notes[:4]))
    return "\n\n".join(parts).strip()


def _extract_summary(ext):
    t = len(ext.get("tables") or [])
    txt = len(ext.get("text") or "")
    imgs = [i for i in (ext.get("images") or []) if i.get("text")]
    bits = []
    if t:
        bits.append("%d 张表" % t)
    if txt:
        bits.append("正文 %d 字" % txt)
    if imgs:
        bits.append("%d 张图片已识别" % len(imgs))
    if ext.get("note"):
        bits.append(ext["note"])
    return "、".join(bits) or (ext.get("status") or "空")


def _catalog_line(ext, filename, doc_kind=""):
    n_tables = len(ext.get("tables") or [])
    n_cols = sum(len(t.get("columns") or []) for t in ext.get("tables") or [])
    n_rows = sum(t.get("rowCount") or 0 for t in ext.get("tables") or [])
    prose_len = len(ext.get("text") or "")
    n_imgs = len([i for i in (ext.get("images") or []) if i.get("text")])
    bits = []
    if n_tables:
        bits.append("%d 张表/%d 列/%d 行" % (n_tables, n_cols, n_rows))
    if prose_len:
        bits.append("正文 %d 字" % prose_len)
    if n_imgs:
        bits.append("%d 张图片已识别" % n_imgs)
    if ext.get("note"):
        bits.append(ext["note"])
    head = ""
    text = (ext.get("text") or "").strip()
    if text:
        head = text[:60].replace("\n", " ")
    label = _DOC_LABEL.get(doc_kind or "other", "其他")
    return "- [%s] %s:%s%s" % (label, filename, "、".join(bits) or "空",
                              (" — " + head) if head else "")


# ---------------------------------------------------------------- 需求清单:必做表单
def _forms_from_ext(ext):
    """从结构化抽取的表格里"挖出"表单清单。

    识别列名含「表单」的列(如需求清单的「表单名称」),取其非空值作为**必做表单名**。
    过滤掉备注/小标题类噪声(以冒号结尾、含换行或过长),避免把「部署+培训：」等当成表单。
    """
    out = []
    for t in ext.get("tables") or []:
        cols = t.get("columns") or []
        idx = next((i for i, c in enumerate(cols) if c and "表单" in c), None)
        if idx is None:
            continue
        for r in t.get("rows") or []:
            if idx >= len(r):
                continue
            v = (r[idx] or "").strip()
            if not v or v in out:
                continue
            if v.endswith((":", "：")) or "\n" in v or len(v) > 40:
                continue
            out.append(v)
    return out


def forms_checklist(forms):
    """把「必须设计的表单清单」渲染成提示词里的硬约束块(来自需求清单,置于最前)。"""
    forms = [f for f in (forms or []) if f]
    if not forms:
        return ""
    lines = ["【需求清单·必须设计的表单(共 %d 个,一个都不能漏)】" % len(forms)]
    lines += ["%d. %s" % (i + 1, f) for i, f in enumerate(forms)]
    lines.append("以上表单来自用户的需求清单,是本次项目的**必做项**:设计方案的表盘点与 ER 结构"
                 "都必须逐一覆盖、不得遗漏;确有不做的,须在「待确认」中逐条说明理由。")
    return "\n".join(lines)


def missing_forms(forms, titles):
    """返回 forms 中未出现在 titles 里的项(按包含关系做宽松匹配),供生成后校验提示。"""
    ts = [t or "" for t in (titles or [])]
    out = []
    for f in forms or []:
        if not f:
            continue
        if any(f in t or t in f for t in ts):
            continue
        out.append(f)
    return out


# ---------------------------------------------------------------- 组装
def build_reference(docs, provider, progress=None, pct_range=(5, 55)):
    """docs = [{id, filename, ext, stored_path, parsed_text?}] → 参考上下文字典。

    progress(text, pct=None, level="info") 用于上报"正在抽取哪个文件"。
    """
    docs = list(docs or [])
    # 按资料类型排序:需求清单(基准)在前,会议纪要/其他(补充)在后,便于模型分主次、
    # 也让截断时优先保留需求清单。
    docs.sort(key=lambda d: _DOC_ORDER.get(d.get("kind"), len(_DOC_ORDER)))
    n = len(docs)
    lo, hi = pct_range
    material = []
    notes = []
    required_forms = []                             # 需求清单里的必做表单(供提示词硬约束)

    def _pct(i):
        return lo + int((hi - lo) * (i + 1) / max(1, n))

    for i, d in enumerate(docs):
        fn = d.get("filename") or ("#%s" % d.get("id"))
        ext = get_or_extract(d, provider,
                             on_step=lambda dd, i=i, fn=fn: progress and progress(
                                 "结构化抽取 %d/%d:%s" % (i + 1, n, fn), pct=_pct(i) - 3))
        cached = ext.pop("_cached", False)
        if progress:
            if cached:
                progress("复用已缓存抽取结果:%s" % fn, pct=_pct(i), level="info")
            else:
                progress("已抽取 %s(%s)" % (fn, _extract_summary(ext)), pct=_pct(i))
        is_req = (d.get("kind") or "") == "requirement"
        mrows = C.CTX_MAX_LIST_ROWS if is_req else C.CTX_SAMPLE_ROWS
        compact = render_compact(ext, mrows)
        material.append({
            "id": d.get("id"), "filename": fn,
            "tokens": estimate_tokens(compact), "compact": compact,
            "status": ext.get("status"), "kind": ext.get("kind"),
            "docKind": d.get("kind") or "other",
            "tables": len(ext.get("tables") or []),
            "catalog": _catalog_line(ext, fn, d.get("kind")),
        })
        if is_req:
            for f in _forms_from_ext(ext):
                if f not in required_forms:
                    required_forms.append(f)
        if ext.get("status") in ("unsupported", "empty") and ext.get("note"):
            notes.append("%s:%s" % (fn, ext["note"]))
        elif ext.get("note"):
            notes.append("%s:%s" % (fn, ext["note"][:160]))
        for im in (ext.get("images") or []):
            if im.get("note"):
                notes.append("%s(%s):%s" % (fn, im.get("from"), im["note"][:160]))

    total = sum(m["tokens"] for m in material)
    budget = max(1000, C.CTX_TOKEN_BUDGET)
    # 目录阈值须 >= 预算;运维若把它配得比预算还小,这里会被提升为预算。
    # 此时不会出现 truncated 档(第一个 if 已把 total<=budget 的分支收走),属预期行为。
    threshold = max(budget, C.CTX_CATALOG_THRESHOLD)
    # 去重:同一提示可能同时来自"文件级"与"图片级",按提示正文(冒号后)去重
    seen_note, deduped = set(), []
    for n in notes:
        key = n.split(":", 1)[-1].strip()
        if key in seen_note:
            continue
        seen_note.add(key)
        deduped.append(n)
    notes = deduped

    if total <= budget:
        text = _join_inline(material)
        return {"mode": MODE_INLINE, "text": text, "catalog": "", "material": material,
                "notes": notes, "totalTokens": total, "requiredForms": required_forms}

    if total <= threshold:
        # 超预算但未到目录阈值:均分预算,字段优先(渲染顺序保证了表格在前)
        share = max(500, budget // max(1, n))
        kept, dropped = [], []
        for m in material:
            if m["tokens"] <= share:
                kept.append(m)
            else:
                m = dict(m)
                m["compact"] = _truncate_tokens(m["compact"], share)
                m["truncated"] = True
                kept.append(m)
                notes.append("%s:内容较长,已按预算截断%s"
                             % (m["filename"],
                                "(字段/列名已完整保留)" if m.get("tables") else ""))
        text = _join_inline(kept)
        return {"mode": MODE_TRUNCATED, "text": text, "catalog": "", "material": material,
                "notes": notes, "totalTokens": total, "budget": budget,
                "requiredForms": required_forms}

    # 目录模式
    catalog = "\n".join(m["catalog"] for m in material)
    return {"mode": MODE_CATALOG, "text": "", "catalog": catalog, "material": material,
            "notes": notes, "totalTokens": total, "requiredForms": required_forms}


def _join_inline(material):
    """按资料类型分组渲染:需求清单(基准)在前、会议纪要/其他(补充)在后。

    分组标题同时是给模型的**角色信号**(配合 REFERENCE_GUARD),让模型分清
    "哪个是需求基准、哪些是补充",而不是把所有文件当成一锅资料。
    """
    blocks = []
    known = set(_DOC_ORDER)
    for key, title in _DOC_GROUPS:
        items = [m for m in material if m.get("compact") and (m.get("docKind") or "other") == key]
        if not items:
            continue
        blocks.append(title)
        for m in items:
            blocks.append("### 文件:%s\n%s" % (m["filename"], m["compact"]))
    for m in material:                                  # 兜底:未知类型(不丢内容)
        if m.get("compact") and (m.get("docKind") or "other") not in known:
            blocks.append("### 文件:%s\n%s" % (m["filename"], m["compact"]))
    return "\n\n".join(blocks)


def _truncate_tokens(text, token_budget):
    """按估算 token 近似截断(保留前半,表格/字段在渲染里本就靠前)。

    逐字符累计 token 成本(中文 1、非中文 0.25),保证**含截断后缀在内**的结果
    满足 `estimate_tokens(结果) <= token_budget`;预算小到放不下后缀时退化为
    只截正文、不加后缀(仍满足上述不变量)。
    """
    if token_budget <= 0:
        return ""
    if estimate_tokens(text) <= token_budget:
        return text
    suffix = "\n…(已截断)"
    body_budget = token_budget - estimate_tokens(suffix)
    if body_budget > 0:
        tail = suffix
    else:
        # 预算过小,放不下完整后缀:退化为只截正文,留出 0.25 的取整余量
        tail = ""
        body_budget = token_budget - 0.25
    left, out = float(body_budget), []
    for ch in text:
        cost = 1.0 if "\u4e00" <= ch <= "\u9fff" else 0.25
        if cost > left:
            break
        out.append(ch)
        left -= cost
    return "".join(out).rstrip() + tail


def fit_reference(library_text, ref_text, budget=None):
    """合并「资料库正文 + 项目参考正文」,保证总估算 token ≤ 预算。

    返回 (library_text', ref_text', note);note 为空表示未截断。
    优先保留项目参考资料 ref_text:超限时先截断 library_text,仍超再截 ref_text。
    无条件不变量:`estimate_tokens(lib_out) + estimate_tokens(ref_out) <= budget`
    (budget 很小也成立);library_text 为空时原样返回、不改 ref_text。
    """
    if not (library_text or "").strip():
        return library_text, ref_text, ""
    if budget is None:
        budget = max(1000, C.CTX_TOKEN_BUDGET)
    budget = max(0, budget)
    lib, ref = library_text or "", ref_text or ""
    lib_t, ref_t = estimate_tokens(lib), estimate_tokens(ref)
    if lib_t + ref_t <= budget:
        return library_text, ref_text, ""

    # 优先保 ref:先压缩 library
    room_lib = max(0, budget - ref_t)
    out_lib = _truncate_tokens(lib, room_lib) if lib_t > room_lib else lib
    out_lib_t = estimate_tokens(out_lib)
    if out_lib_t + ref_t <= budget:
        return out_lib, ref, "参考资料超出预算,已压缩资料库正文"

    # 压缩 library 后仍超:再压缩 ref
    room_ref = max(0, budget - out_lib_t)
    out_ref = _truncate_tokens(ref, room_ref) if ref_t > room_ref else ref
    return out_lib, out_ref, "参考资料超出预算,已同时压缩资料库正文与项目参考"


# ---------------------------------------------------------------- 目录模式:按需取件
_SELECT_SYS = """你在为「系统设计方案」挑选参考资料。下面会给出:业务需求,以及可用资料的**目录**
(每个文件一行,含文件名与内容规模)。
请只输出 JSON:{"files": ["文件名1", "文件名2"]},列出你为完成这份设计**最需要**阅读的文件。
规则:
- 只从目录里出现的文件名中选择,原样复制文件名;
- 最多选 %d 个;优先选"表/字段/列"最多的资料(它们信息量最大);
- 若目录已足够设计,可返回空数组 [];
- 只输出 JSON,不要解释。"""


def _material_by_name(material):
    return {m["filename"]: m for m in material}


def resolve_catalog(provider, reference, requirement, progress=None):
    """目录模式:让模型按需索取文件,返回其紧凑内容(受预算约束)。

    返回 (text, used_names);模型不可用或索取失败时,退化为"信息量最大的前 N 个"。
    """
    material = reference["material"]
    by_name = _material_by_name(material)
    order = list(by_name.keys())
    catalog = reference["catalog"]
    budget = max(1000, C.CTX_TOKEN_BUDGET)
    max_files = max(1, C.CTX_MAX_SELECT_FILES)

    selected = []
    if getattr(provider, "available", False):
        for rnd in range(max(1, C.CTX_MAX_SELECT_ROUNDS)):
            if progress:
                progress("目录模式:第 %d 轮挑选资料(共 %d 个文件可选)"
                         % (rnd + 1, len(order)), pct=60)
            from .llm import extract_json
            try:
                out = extract_json(provider.complete(
                    _SELECT_SYS % max_files,
                    "【业务需求】\n%s\n\n【资料目录】\n%s\n\n已选:%s"
                    % (requirement or "(空)", catalog, "、".join(selected) or "(无)"),
                    json_mode=True))
                wanted = [str(x).strip() for x in (out.get("files") or [])]
            except Exception as e:
                reference["notes"].append("目录挑选失败(%s),改用按信息量取件" % str(e)[:120])
                break
            fresh = [w for w in wanted if w in by_name and w not in selected]
            selected.extend(fresh)
            if not fresh or len(selected) >= max_files:
                break

    if not selected:
        # 回退:按 token 从多到少(即信息量最大)取前 N 个
        ranked = sorted(material, key=lambda m: -m["tokens"])
        selected = [m["filename"] for m in ranked[:max_files]]
        reference["notes"].append("目录模式未指定文件,已自动选取信息量最大的 %d 份" % len(selected))

    # 受预算约束:按选择顺序纳入,超出即截断或停止
    text, used, spent = [], [], 0
    share = max(500, budget // max(1, len(selected)))
    for name in selected:
        m = by_name.get(name)
        if not m:
            continue
        piece = m["compact"]
        if estimate_tokens(piece) > share:
            piece = _truncate_tokens(piece, share)
        cost = estimate_tokens(piece)
        # F13:单件仍超剩余预算时再截短一次,避免首件(used 为空时不 break)撑爆预算
        remaining = budget - spent
        if cost > remaining:
            piece = _truncate_tokens(piece, max(200, remaining))
            cost = estimate_tokens(piece)
        if spent + cost > budget and used:
            reference["notes"].append("预算已满,剩余 %d 份资料未纳入" % (len(selected) - len(used)))
            break
        text.append("### 文件:%s\n%s" % (name, piece))
        used.append(name)
        spent += cost
    reference["selected"] = used
    reference["mode"] = MODE_CATALOG + ":resolved"
    return "\n\n".join(text), used
