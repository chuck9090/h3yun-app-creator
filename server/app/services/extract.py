# -*- coding: utf-8 -*-
"""按文件类型做**结构化抽取**(不是摘要):保留字段/列名/枚举等细节。

  extract_document(doc, provider=None) -> {
      "status": "ok" | "empty" | "unsupported" | "error",
      "kind":   "spreadsheet" | "docx" | "pdf" | "text" | "image",
      "tables": [{"name": "Sheet1", "columns": [...], "rows": [[...]], "rowCount": n}],
      "text":   "正文(已清洗,截断)",
      "images": [{"from": "docx内嵌#1"|"xlsx:Sheet1!D5"|"pdf第1页"|"独立图片",
                  "text": "视觉识别结果", "note": "未识别时的说明"}],
      "note":   "整体说明(非 ok 时一定有值,避免静默丢失)",
  }

设计要点:
  - Excel/DOCX 的表格 → 「列名(字段清单,无损)+ 数据行样例」。
  - **内嵌图片**(Excel 里的截图/Word 里的流程截图/扫描件 PDF)会交给视觉模型识别成文本,
    字段信息不再被静默丢弃;识别结果一并进"文本",供后续参考。
  - 无内容 / 图片未识别 / 未配置视觉模型等,**一律给出 note**,让调用方能在进度里暴露出来。
  - 纯函数,不读库、不写库(缓存由 services.context 负责)。
"""
import base64
import os
import re

VERSION = 3                 # 抽取逻辑版本(供缓存失效判断,改动抽取行为时递增)
MAX_TEXT = 200_000          # 单文件正文上限(字符)
MAX_ROWS = 400              # 单表抽取的数据行上限
MAX_COLS = 80               # 单表列数上限
MAX_TABLES = 60             # 单文件表数上限
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
_IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
# 图片"格式名"→ MIME(openpyxl 的 Image.format 形如 'png'/'jpeg',不是扩展名)
_FORMAT_MIME = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg",
                "gif": "image/gif", "bmp": "image/bmp",
                "tiff": "image/tiff", "webp": "image/webp"}

_VISION_SYS = ("你是企业信息化顾问。请识别图片中的业务/系统信息(尤其是表单名、字段名、字段类型、"
               "枚举取值、流程步骤),用 Markdown 结构化列出;看不清的不要编造。")


def _clean(text):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_TEXT]


def _from_config():
    from ..core import config as C
    return C


def _mime_for_format(fmt, default="image/png"):
    """按**图片格式名**映射 MIME(如 openpyxl 的 Image.format='jpeg')。"""
    return _FORMAT_MIME.get(str(fmt or "").strip().lower(), default)


def _mime_for_name(name, default="image/png"):
    """按**文件名/资源名**的后缀映射 MIME(如 pypdf 的 'Im0.jpeg'),忽略大小写。"""
    ext = os.path.splitext(str(name or ""))[1].lower()
    return _IMAGE_MIME.get(ext, default)


def _cell(v):
    return "" if v is None else str(v).strip()


def _to_table(name, header, rows):
    """把二维行转成结构化表:首行非空者当列名,其余为数据行。"""
    header = [_cell(h) for h in (header or [])][:MAX_COLS]
    while header and not header[-1]:
        header.pop()
    if not header:
        return None
    out_rows = []
    for r in rows[:MAX_ROWS]:
        cells = [_cell(v) for v in (r or [])][:len(header)]
        if any(cells):
            out_rows.append(cells)
    return {"name": name or "表", "columns": header, "rows": out_rows,
            "rowCount": len(out_rows)}


# ---------------------------------------------------------------- 视觉识别
def _vision_enabled(provider):
    return (provider is not None and getattr(provider, "available", False)
            and hasattr(provider, "complete_vision"))


def _vision(raw: bytes, mime: str, provider, label: str):
    """bytes → 数据 URL → 视觉识别;返回 {"from","text"} 或 {"from","note"}。"""
    if not _vision_enabled(provider):
        return {"from": label, "note": "需配置支持视觉的大模型才能识别该图片(当前未配置)"}
    if len(raw) > _from_config().IMG_MAX_MB * 1024 * 1024:
        return {"from": label, "note": "图片超过 %dMB,未做视觉识别" % _from_config().IMG_MAX_MB}
    url = "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))
    try:
        txt = provider.complete_vision(_VISION_SYS,
                                       "文件名相关:%s\n请结构化识别这张图片里的信息。" % label, url)
        if (txt or "").strip():
            return {"from": label, "text": _clean(txt)}
        return {"from": label, "note": "视觉识别返回空内容"}
    except Exception as e:
        return {"from": label, "note": "视觉识别失败:%s" % str(e)[:200]}


def _vision_image_file(path, ext, provider, label=None):
    if not _vision_enabled(provider):
        return {"from": label or "独立图片",
                "note": "图片内容需配置支持视觉的大模型才能识别(当前未配置)"}
    try:
        raw = open(path, "rb").read()
    except Exception as e:
        return {"from": label or "独立图片", "note": "读取图片失败:%s" % str(e)[:120]}
    return _vision(raw, _IMAGE_MIME.get(str(ext or "").lower(), "image/png"), provider,
                   label or "独立图片")


# ---------------------------------------------------------------- Excel
def _xlsx_grid(ws):
    """工作表 → 二维字符串网格(行数上限 MAX_ROWS+20,去尾部全空行)。"""
    grid = []
    for row in ws.iter_rows(values_only=True):
        grid.append([_cell(v) for v in row])
        if len(grid) > MAX_ROWS + 20:
            break
    while grid and not any(grid[-1]):
        grid.pop()
    return grid


def _fill_merged(ws, grid):
    """把合并单元格的值填满其覆盖区域。

    Excel 里「功能模块」这类列常用**纵向合并**;openpyxl 只在左上角返回值,其余为 None。
    不填充会丢失数据行的模块归属(实测需求清单因此塌成 1 列、只剩「序号」)。
    """
    ncol = max((len(r) for r in grid), default=0)
    for r in grid:
        if len(r) < ncol:
            r.extend([""] * (ncol - len(r)))
    for rng in ws.merged_cells.ranges:
        r0, c0 = rng.min_row - 1, rng.min_col - 1
        if r0 >= len(grid) or c0 >= ncol:
            continue
        v = grid[r0][c0]
        if not v:
            continue
        for r in range(r0, min(rng.max_row, len(grid))):
            for c in range(c0, min(rng.max_col, ncol)):
                if not grid[r][c]:
                    grid[r][c] = v


def _find_header(grid, scan=12):
    """找表头行:前 scan 行里第一个**非空单元格 ≥2** 的行。

    用于跳过被合并的标题行(如 A1:F1「功能清单」,原始只有 1 个非空格);
    否则标题行会被误当表头,`_to_table` 再裁掉尾部空列,整表被压成 1 列。
    """
    for i, row in enumerate(grid[:scan]):
        if sum(1 for c in row if c) >= 2:
            return i
    return None


def _sheet_to_table(ws, raw, filled):
    """一个工作表 → 结构化表(识别标题行/表头行;数据行取合并填充后的网格)。"""
    hi = _find_header(raw)
    if hi is None:                                   # 单列清单:退化为首个非空行为表头
        hi = next((i for i, r in enumerate(raw) if any(r)), None)
        if hi is None:
            return None
    title = ""
    if hi > 0:                                       # 表头之上的独立标题行(如「功能清单」)
        top = [c for c in raw[hi - 1] if c]
        if len(top) == 1:
            title = top[0]
    t = _to_table(title or ws.title, raw[hi], filled[hi + 1:])
    if t and title:
        t["title"] = title
    return t


def _extract_xlsx(path, provider):
    from openpyxl import load_workbook
    tables, texts, images = [], [], []
    limit = _from_config().IMG_MAX_PER_FILE
    wb = load_workbook(path, data_only=True)      # 非 read_only:需要 ws._images
    try:
        for ws in wb.worksheets:
            if len(tables) >= MAX_TABLES:
                break
            grid = _xlsx_grid(ws)
            if grid:
                raw = [list(r) for r in grid]        # 表头/标题识别用原始值
                _fill_merged(ws, grid)               # 数据行用合并填充后的值
                t = _sheet_to_table(ws, raw, grid)
                if t:
                    tables.append(t)
                else:                                # 未识别出表:文本兜底,避免内容静默丢失
                    flat = "\n".join(" | ".join(c for c in r if c)
                                     for r in grid if any(r))
                    if flat.strip():
                        texts.append(flat[:MAX_TEXT])
            if limit <= 0:
                continue
            ws_images = list(getattr(ws, "_images", []) or [])
            if ws_images and not _vision_enabled(provider):
                images.append({"from": "xlsx:%s" % ws.title,
                               "note": "检测到 %d 张内嵌图片,需配置支持视觉的大模型才能识别"
                                       % len(ws_images)})
                continue
            for im in ws_images:
                if len(images) >= limit:
                    break
                try:
                    anchor = getattr(im.anchor, "_from", None)
                    where = ("%s!R%dC%d" % (ws.title, anchor.row + 1, anchor.col + 1)
                             if anchor else ws.title)
                except Exception:
                    where = ws.title
                try:
                    raw = im._data() if callable(getattr(im, "_data", None)) else im.ref
                    data = raw.read() if hasattr(raw, "read") else raw
                    mime = _mime_for_format(getattr(im, "format", ""))
                    images.append(_vision(data, mime, provider, "xlsx:%s" % where))
                except Exception as e:
                    images.append({"from": "xlsx:%s" % where,
                                   "note": "抽取内嵌图片失败:%s" % str(e)[:120]})
    finally:
        wb.close()
    return {"tables": tables, "text": "\n\n".join(texts), "images": images}


# ---------------------------------------------------------------- Word
def _docx_pics(doc):
    """收集 DOCX 内所有内嵌图片(inline + 浮动/锚定),按 rId 去重。

    返回 [(rId, part), ...]。优先遍历 body 里的 a:blip(inline 与锚定同源),
    遍历异常时回退到只取 inline_shapes(老逻辑)。
    """
    from docx.oxml.ns import qn
    seen, out = set(), []
    try:
        parts = getattr(doc.part, "related_parts", None) or {}
        for blip in doc.element.body.iter(qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            if not rid or rid in seen:
                continue
            part = parts.get(rid)
            if part is None:
                continue
            seen.add(rid)
            out.append((rid, part))
        if out:
            return out
    except Exception:
        seen, out = set(), []
    try:
        for shape in doc.inline_shapes:
            try:
                rid = shape._inline.graphic.graphicData.pic.blipFill.blip.embed
                part = doc.part.related_parts[rid]
            except Exception:
                continue
            if rid in seen:
                continue
            seen.add(rid)
            out.append((rid, part))
    except Exception:
        pass
    return out


def _extract_docx(path, provider):
    from docx import Document
    doc = Document(path)
    prose = [(p.text or "").strip() for p in doc.paragraphs if (p.text or "").strip()]
    tables = []
    for i, table in enumerate(doc.tables[:MAX_TABLES]):
        grid = [[_cell(c.text) for c in row.cells] for row in table.rows]
        grid = [r for r in grid if any(r)]
        if not grid:
            continue
        t = _to_table("表格%d" % (i + 1), grid[0], grid[1:])
        if t:
            tables.append(t)
    images, limit = [], _from_config().IMG_MAX_PER_FILE
    if limit > 0:
        pics = _docx_pics(doc)
        if pics and not _vision_enabled(provider):
            images.append({"from": "docx内嵌图",
                           "note": "检测到 %d 张内嵌图片,需配置支持视觉的大模型才能识别"
                                   % len(pics)})
        elif _vision_enabled(provider):
            for i, (_rid, part) in enumerate(pics):
                if len(images) >= limit:
                    break
                try:
                    raw = part.blob
                    ct = getattr(part, "content_type", "image/png")
                    images.append(_vision(raw, ct, provider, "docx内嵌图#%d" % (i + 1)))
                except Exception as e:
                    images.append({"from": "docx内嵌图#%d" % (i + 1),
                                   "note": "抽取内嵌图片失败:%s" % str(e)[:120]})
    return {"tables": tables, "text": "\n".join(prose), "images": images}


# ---------------------------------------------------------------- PDF
def _pdf_render_page(page, dpi=150):
    import fitz
    pix = page.get_pixmap(dpi=dpi)
    return pix.tobytes("png")


def _extract_pdf(path, provider):
    from pypdf import PdfReader
    reader = PdfReader(path)
    text = "\n".join((pg.extract_text() or "") for pg in reader.pages)
    images, limit = [], _from_config().IMG_MAX_PER_FILE
    C = _from_config()
    # 1) 内嵌图片(矢量 PDF 里贴的截图)
    if limit > 0 and _vision_enabled(provider):
        for pi, page in enumerate(reader.pages):
            if len(images) >= limit:
                break
            try:
                page_imgs = list(page.images)
            except Exception:
                page_imgs = []
            for ii, im in enumerate(page_imgs):
                if len(images) >= limit:
                    break
                try:
                    name = getattr(im, "name", "") or ""
                    mime = (_mime_for_name(name, "")
                            or getattr(im, "content_type", "")
                            or "image/png")
                    images.append(_vision(im.data, mime, provider,
                                          "pdf第%d页内嵌图#%d" % (pi + 1, ii + 1)))
                except Exception as e:
                    images.append({"from": "pdf第%d页内嵌图#%d" % (pi + 1, ii + 1),
                                   "note": "抽取内嵌图片失败:%s" % str(e)[:120]})
    # 2) 扫描件:几乎没有文字层 → 整页渲染识别(内嵌图已占用的配额需扣减,合计不超过 limit)
    if len(text.strip()) < C.PDF_OCR_MIN_CHARS and limit > 0:
        if not _vision_enabled(provider):
            images.append({"from": "pdf(扫描件)",
                           "note": "PDF 无文字层(疑似扫描件),需配置支持视觉的大模型才能识别"})
        else:
            remaining = limit - len(images)
            if remaining > 0:
                try:
                    import fitz
                    doc = fitz.open(path)
                    for pi in range(min(len(doc), C.PDF_OCR_MAX_PAGES, remaining)):
                        try:
                            png = _pdf_render_page(doc[pi])
                            images.append(_vision(png, "image/png", provider,
                                                  "pdf第%d页(整页)" % (pi + 1)))
                        except Exception as e:
                            images.append({"from": "pdf第%d页(整页)" % (pi + 1),
                                           "note": "整页渲染失败:%s" % str(e)[:120]})
                    doc.close()
                except Exception as e:
                    images.append({"from": "pdf(扫描件)",
                                   "note": "扫描件渲染失败:%s" % str(e)[:120]})
    return {"tables": [], "text": text, "images": images}


# ---------------------------------------------------------------- 文本
def _extract_text(path):
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030", "latin-1"):
        try:
            with open(path, "rb") as f:
                return {"tables": [], "text": f.read().decode(enc), "images": []}
        except (UnicodeDecodeError, LookupError):
            continue
    with open(path, "rb") as f:
        return {"tables": [], "text": f.read().decode("utf-8", "replace"), "images": []}


# ---------------------------------------------------------------- 独立图片
def _extract_image(path, ext, provider):
    return {"tables": [], "text": "",
            "images": [_vision_image_file(path, ext, provider)]}


# ---------------------------------------------------------------- 汇总
def _merge_notes(status, tables, text, images, kind):
    """给出"为什么不是 ok"的明确说明,避免静默丢失。"""
    if tables or text.strip() or any(i.get("text") for i in images):
        return ""
    if images and any(i.get("note") for i in images):
        return "、".join(i["note"] for i in images if i.get("note"))[:400]
    if kind == "pdf":
        return "PDF 未提取到文字或可识别图片(可能是纯图片扫描件,或需要视觉模型)"
    if kind == "image":
        return "图片未识别出内容"
    return "未提取到任何文字或表格内容"


def extract_document(doc, provider=None) -> dict:
    """doc 为 documents 行(dict):需 filename / stored_path / ext。"""
    path = (doc or {}).get("stored_path") or ""
    name = (doc or {}).get("filename") or ""
    ext = ((doc or {}).get("ext") or os.path.splitext(path)[1] or "").lower()
    if not path or not os.path.isfile(path):
        return {"status": "error", "kind": "unknown", "tables": [], "text": "",
                "images": [], "note": "原件不存在(可能已被删除)"}
    try:
        if ext in (".xlsx", ".xlsm"):
            body, kind = _extract_xlsx(path, provider), "spreadsheet"
        elif ext == ".docx":
            body, kind = _extract_docx(path, provider), "docx"
        elif ext == ".pdf":
            body, kind = _extract_pdf(path, provider), "pdf"
        elif ext in _IMAGE_EXTS:
            body, kind = _extract_image(path, ext, provider), "image"
        else:
            body, kind = _extract_text(path), "text"
    except Exception as e:
        return {"status": "error", "kind": "unknown", "tables": [], "text": "",
                "images": [], "note": "解析失败:%s" % str(e)[:200]}
    body["text"] = _clean(body.get("text"))
    tables = body.get("tables") or []
    images = body.get("images") or []
    text = body.get("text") or ""
    out = {"kind": kind, "tables": tables, "text": text, "images": images,
           "note": body.get("note") or ""}
    note = _merge_notes(None, tables, text, images, kind)
    if note and not out["note"]:
        out["note"] = note
    out["status"] = ("ok" if (tables or text.strip() or any(i.get("text") for i in images))
                     else ("unsupported" if out["note"] else "empty"))
    out["filename"] = name
    return out
