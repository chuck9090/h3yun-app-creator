# -*- coding: utf-8 -*-
"""业务流程图渲染:把 mermaid `flowchart` 文本渲染成**分区泳道式 SVG**。

设计目标(与本项目「确定性部分全部脚本化、零 LLM 依赖」一致):
不依赖浏览器、不依赖 mermaid.js —— 纯 Python 解析 mermaid 结构 → 计算分区布局
→ 输出**内联样式**的 SVG 文本(可直接下载,也可栅格化为 PNG)。

分区规则
--------
* 每个 `subgraph` = 一条横向**泳道**(带左侧色带与模块名);
* 泳道内表单按出现顺序从左到右排列,节点对齐在同一列网格;
* 同一泳道内的连线:相邻走直线,跨格走泳道下方绕行;
* 跨泳道连线:从节点上下缘出入,经泳道左侧「走廊」纵向绕行(橙线),互不穿越泳道内部。

连线不重叠
----------
所有折线由**水平段 + 竖直段**组成,并按「轨道分配」错开:同一通道内若两段的
投影区间重叠,则自动让到相邻轨道(间距约 13px),从而**允许交叉、消除共线重叠**。
连接线的去重(同一 src→dst 只画一条)也在渲染前完成。

对外接口
--------
  render_svg(mmd, title="业务流程图", subtitle=None) -> dict
      返回 {"svg", "width", "height", "modules", "nodes", "edges", "ok", "message"}
"""
import html
import re

# 每个模块一套配色:(节点填充, 描边, 文字, 泳道底色)
PALETTE = [
    ("#f3e8ff", "#8b5cf6", "#6b21a8", "#faf5ff"),   # 紫
    ("#ffedd5", "#f97316", "#9a3412", "#fff7ed"),   # 橙
    ("#dcfce7", "#22c55e", "#166534", "#f0fdf4"),   # 绿
    ("#dbeafe", "#3b82f6", "#1e40af", "#eff6ff"),   # 蓝
    ("#ccfbf1", "#14b8a6", "#115e59", "#f0fdfa"),   # 青
    ("#e0e7ff", "#6366f1", "#3730a3", "#eef2ff"),   # 靛
    ("#fce7f3", "#ec4899", "#9d174d", "#fdf2f8"),   # 粉
]

# 布局常量
NODE_W, NODE_H = 200, 52
COL_STEP, COL_X0 = 270, 460          # 列间距 / 首列中心(左移留出「走廊带」)
LANE_H, LANE_GAP = 120, 150          # 泳道内容高 / 泳道间距(间距够大以容纳多轨道)
ROW_TOP0 = 150                       # 首条泳道顶部
BAND_X0 = 150                        # 泳道左边
TRACK_STEP = 13                      # 同通道内相邻轨道的间距

FONT = "Microsoft YaHei, PingFang SC, Noto Sans CJK SC, Segoe UI, sans-serif"

_SKIP_HEAD = {"flowchart", "graph", "direction", "classdef", "class",
              "style", "linkstyle", "click", "%%"}
_SUBGRAPH = re.compile(r'^subgraph\s+(\S+?)\s*(?:\[\s*"?([^"\]]*)"?\s*\])?\s*$', re.I)
_END = re.compile(r'^end\s*$', re.I)
_ARROW_SPLIT = re.compile(r'\s*(?:-{2,}>|-\.-+>|={2,}>)\s*')
_LEAD_LABEL = re.compile(r'^\|\s*"?([^|]*?)"?\s*\|\s*(.*)$')
_NODE_ID = re.compile(r'^([A-Za-z][A-Za-z0-9_]*)')
_WRAPPERS = (("[[", "]]"), ("([", "])"), ("[/", "/]"), ("[\\", "\\]"),
             ("{{", "}}"), ("[", "]"), ("(", ")"), ("{", "}"))


def _extract_node(tok):
    """`N1["客户"]` / `N1(客户)` / `N1` → (id, label_or_None)。"""
    tok = (tok or "").strip()
    m = _NODE_ID.match(tok)
    if not m:
        return None, None
    nid = m.group(1)
    rest = tok[m.end():].strip()
    if not rest:
        return nid, None
    label = rest
    for a, b in _WRAPPERS:
        if label.startswith(a):
            inner = label[len(a):]
            if inner.endswith(b):
                inner = inner[:-len(b)]
            label = inner
            break
    label = label.strip().strip('"').strip("'").strip()
    return nid, (label or None)


def parse_flowchart(mmd):
    """解析 mermaid `flowchart` → 结构化 {modules, node_label, edges}。

    modules: [{"id", "name", "forms": [node_id, ...]}]  (按出现顺序)
    edges:   [(src_id, dst_id, label)]
    """
    modules, mod_of, node_label, edges, ordered = [], {}, {}, [], []

    def register(nid, label):
        if label and nid not in node_label:
            node_label[nid] = label
        if nid not in mod_of:
            mod_of[nid] = cur[0] if cur[0] is not None else None
            if cur[0] is not None:
                cur[0]["forms"].append(nid)
            else:
                loose.append(nid)
        if nid not in ordered:
            ordered.append(nid)

    cur = [None]
    loose = []
    for raw in (mmd or "").splitlines():
        ln = raw.strip()
        if not ln:
            continue
        head = ln.split()[0].lower()
        if head in _SKIP_HEAD:
            continue
        m = _SUBGRAPH.match(ln)
        if m:
            mid = (m.group(1) or "").strip().strip('"').strip("'")
            name = (m.group(2) or m.group(1) or "").strip().strip('"').strip("'")
            cur[0] = {"id": mid or ("Mod%d" % (len(modules) + 1)),
                      "name": name or mid or "模块",
                      "forms": []}
            modules.append(cur[0])
            continue
        if _END.match(ln):
            cur[0] = None
            continue

        parts = _ARROW_SPLIT.split(ln)
        if len(parts) > 1:                        # 含连线的行(可能链式)
            prev = None
            for part in parts:
                lm = _LEAD_LABEL.match(part)
                lab = None
                if lm:
                    lab = lm.group(1).strip()
                    part = lm.group(2)
                nid, lbl = _extract_node(part)
                if nid is None:
                    continue
                register(nid, lbl)
                if prev is not None:
                    edges.append((prev, nid, lab))
                prev = nid
        else:                                     # 纯节点声明行
            nid, lbl = _extract_node(ln)
            if nid:
                register(nid, lbl)

    if loose:                                     # 未归入任何 subgraph 的节点
        modules.append({"id": "ModOther", "name": "其他", "forms": loose})
    for m in modules:
        m["forms"] = [f for f in m["forms"]]
    return {"modules": modules, "node_label": node_label, "edges": edges}


def _esc(s):
    return html.escape(str(s), quote=True)


def _font_for(label):
    """按 CJK 宽度自适应字号,保证单行不溢出节点。"""
    n = max(1, len(label or ""))
    size = (NODE_W - 26) / n
    size = max(10.0, min(15.0, size))
    return round(size, 1)


def _polyline(pts, color, marker="arw-g"):
    p = " ".join("%s,%s" % (round(x, 1), round(y, 1)) for x, y in pts)
    return ('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.9" '
            'stroke-linejoin="round" marker-end="url(#%s)"/>' % (p, color, marker))


class _Tracks:
    """正交连线轨道分配器。

    登记已占用的**水平段 / 竖直段**;新线段若与已有线段**投影区间重叠且落到同一轨道**,
    就沿指定方向让到下一个空轨道,从而保证:
      * 允许两条线**交叉**(交叉不视为冲突);
      * 同一段区间内不会有两条线**共线重叠**。
    """

    def __init__(self, step=TRACK_STEP):
        self.step = step
        self.h = []          # 水平段占用:(y, xlo, xhi)
        self.v = []          # 竖直段占用:(x, ylo, yhi)

    def _place(self, used, base, a, b, direction, lo_bound, hi_bound, tries=90):
        lo, hi = (a, b) if a <= b else (b, a)
        gap = self.step - 1
        for i in range(tries):
            v = base + direction * i * self.step
            if (lo_bound is not None and v < lo_bound) or (hi_bound is not None and v > hi_bound):
                continue
            conflict = any(abs(ov - v) < gap and not (hi < olo or lo > ohi)
                           for ov, olo, ohi in used)
            if not conflict:
                used.append((v, lo, hi))
                return v
        v = base + direction * tries * self.step
        used.append((v, lo, hi))
        return v

    def hline(self, y, a, b, direction=1, lo_bound=None, hi_bound=None):
        return self._place(self.h, y, a, b, direction, lo_bound, hi_bound)

    def vline(self, x, a, b, direction=1, lo_bound=None, hi_bound=None):
        return self._place(self.v, x, a, b, direction, lo_bound, hi_bound)


def render_svg(mmd, title="业务流程图", subtitle=None):
    """把 mermaid 流程图渲染为分区泳道式 SVG。"""
    struct = parse_flowchart(mmd)
    modules = [m for m in struct["modules"] if m["forms"]]
    node_label = struct["node_label"]
    raw_edges = struct["edges"]

    # 边去重:同一 src→dst 只保留一条(标签合并),避免重复线完全重叠
    edges, seen_edge = [], {}
    for s, d, lab in raw_edges:
        if s == d:
            continue
        key = (s, d)
        if key in seen_edge:
            i = seen_edge[key]
            old = edges[i][2]
            if lab and lab != old:
                edges[i] = (s, d, (old + " / " + lab) if old else lab)
            continue
        seen_edge[key] = len(edges)
        edges.append((s, d, lab))

    # 扁平图(无 subgraph)兜底:节点过多时按出现顺序切成若干「流程 N」泳道,避免一条超长泳道
    if len(modules) == 1 and len(modules[0]["forms"]) > 8:
        forms = modules[0]["forms"]
        chunk = 8
        modules = [{"id": "ModChunk%d" % (i // chunk + 1),
                    "name": "流程 %d" % (i // chunk + 1),
                    "forms": forms[i:i + chunk]}
                   for i in range(0, len(forms), chunk)]

    if not modules:
        return {"svg": "", "ok": False, "message": "未解析到任何模块/表单",
                "modules": [], "nodes": 0, "edges": len(edges),
                "width": 0, "height": 0}

    # 关键节点标签(缺省回退到 id)
    def lbl(nid):
        return node_label.get(nid) or nid

    max_cols = max(len(m["forms"]) for m in modules)
    pos = {}          # nid -> (module_row, col, x, y)

    def lane_top(r):
        return ROW_TOP0 + r * (LANE_H + LANE_GAP)

    for r, mod in enumerate(modules):
        for c, nid in enumerate(mod["forms"]):
            pos[nid] = (r, c, COL_X0 + COL_STEP * c, lane_top(r) + LANE_H // 2)

    width = max(1240, COL_X0 + COL_STEP * (max_cols - 1) + NODE_W // 2 + 90)
    height = lane_top(len(modules) - 1) + LANE_H + 150 + (60 if any(e[2] for e in edges) else 0)

    L = []
    a = L.append
    a('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
      'font-family="%s">' % (width, height, width, height, FONT))
    a('<defs>')
    a('<marker id="arw-g" markerWidth="9" markerHeight="6" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">'
      '<polygon points="0 0, 9 3, 0 6" fill="#64748b"/></marker>')
    # 每个模块一个同色箭头:跨区线用**来源模块**的主题色,便于一眼分辨线的出处
    for r in range(len(modules)):
        mc = PALETTE[r % len(PALETTE)][1]
        a('<marker id="arw-m%d" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto" '
          'markerUnits="strokeWidth"><polygon points="0 0, 10 3.5, 0 7" fill="%s"/></marker>' % (r, mc))
    a('<filter id="sh" x="-30%" y="-30%" width="160%" height="160%">'
      '<feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#0f172a" flood-opacity="0.15"/></filter>')
    a('</defs>')
    a('<rect x="0" y="0" width="%d" height="%d" fill="#f8fafc"/>' % (width, height))

    # 标题
    a('<text x="56" y="46" font-size="25" font-weight="700" fill="#0f172a">%s</text>' % _esc(title))
    if subtitle:
        a('<text x="56" y="72" font-size="12.5" fill="#64748b">%s</text>' % _esc(subtitle))

    # 图例(模块色 + 连线含义)
    lx = 56
    a('<text x="%d" y="105" font-size="12.5" fill="#64748b">图例</text>' % lx)
    lx += 46
    for r, mod in enumerate(modules):
        f, s, t, _ = PALETTE[r % len(PALETTE)]
        a('<rect x="%d" y="94" width="17" height="13" rx="3" fill="%s" stroke="%s" stroke-width="1.6"/>' % (lx, f, s))
        a('<text x="%d" y="105" font-size="12" fill="#334155">%s</text>' % (lx + 22, _esc(mod["name"])))
        lx += 22 + len(mod["name"]) * 13 + 16
    a('<line x1="%d" y1="100" x2="%d" y2="100" stroke="#64748b" stroke-width="1.8" marker-end="url(#arw-g)"/>' % (lx, lx + 26))
    a('<text x="%d" y="105" font-size="12" fill="#334155">区域内流程</text>' % (lx + 32))
    lx += 120
    # 跨区流转:线色随**来源模块**主题色(示例画三段不同色)
    seg = 11
    demo = [PALETTE[i % len(PALETTE)][1] for i in range(3)]
    last_marker = "arw-m%d" % (min(2, len(modules) - 1) if len(modules) else 0)
    for i, c in enumerate(demo):
        a('<line x1="%d" y1="100" x2="%d" y2="100" stroke="%s" stroke-width="2.4"/>' % (lx + i * seg, lx + (i + 1) * seg, c))
    a('<line x1="%d" y1="100" x2="%d" y2="100" stroke="%s" stroke-width="2.4" marker-end="url(#%s)"/>'
      % (lx + 2 * seg, lx + 3 * seg, demo[2], last_marker))
    a('<text x="%d" y="105" font-size="12" fill="#334155">跨区域流转(线色＝来源模块)</text>' % (lx + 3 * seg + 6))

    # 泳道底
    for r, mod in enumerate(modules):
        f, s, t, bg = PALETTE[r % len(PALETTE)]
        top = lane_top(r)
        a('<rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="%s" stroke="%s" '
          'stroke-width="1.2" stroke-opacity="0.35"/>' % (BAND_X0, top, width - BAND_X0 - 40, LANE_H, bg, s))
        a('<rect x="%d" y="%d" width="6" height="%d" rx="3" fill="%s"/>' % (BAND_X0, top, LANE_H, s))
        a('<text x="52" y="%d" font-size="16" font-weight="700" fill="%s">%s</text>'
          % (top + LANE_H // 2 + 6, t, _esc(mod["name"])))

    # 连线(先画,处于节点下层)
    # 轨道分配:所有水平段/竖直段经 _Tracks 错开,保证「可交叉、不共线重叠」。
    tr = _Tracks()
    corr_right = COL_X0 - NODE_W // 2 - 40          # 走廊带右界
    corr_left = BAND_X0 + 22                          # 走廊带左界

    def gutter_bounds(r_lo, r_hi):
        """两条相邻泳道之间的空隙([泳道底, 下泳道顶])。"""
        top = lane_top(r_lo) + LANE_H
        bot = lane_top(r_hi)
        return top + 16, bot - 16

    for src, dst, elabel in edges:
        if src not in pos or dst not in pos:
            continue
        rs, cs, xs, ys = pos[src]
        rd, cd, xd, yd = pos[dst]
        tip_s = NODE_H // 2                            # 源/目标节点边缘到中心的距离

        if rs == rd:                                   # ---------- 同泳道
            if cd == cs + 1:
                x1, x2 = xs + NODE_W // 2, xd - NODE_W // 2
                y = tr.hline(ys, x1, x2, direction=1)
                if abs(y - ys) < 1:
                    a('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#64748b" stroke-width="1.9" '
                      'marker-end="url(#arw-g)"/>' % (x1, ys, x2, yd))
                else:                                  # 与已有线共线 → 让轨(两端补竖段)
                    a(_polyline([(x1, ys), (x1, y), (x2, y), (x2, yd)], "#64748b", "arw-g"))
                if elabel:
                    a(_edge_label((x1 + x2) / 2, y - 9, elabel))
            else:                                      # 跨格:走泳道下方绕行
                lo, hi = lane_top(rs) + LANE_H + 14, lane_top(rs) + LANE_H + LANE_GAP - 14
                rail = tr.hline(lo, xs, xd, direction=1, lo_bound=lo, hi_bound=hi)
                a(_polyline([(xs, ys + tip_s), (xs, rail), (xd, rail), (xd, yd + tip_s)], "#64748b", "arw-g"))
                if elabel:
                    a(_edge_label((xs + xd) / 2, rail - 9, elabel))
        else:
            mc = PALETTE[rs % len(PALETTE)][1]         # 来源模块主题色
            m_marker = "arw-m%d" % (rs % len(PALETTE))
            if abs(rd - rs) == 1:                      # ---------- 相邻泳道:在两道空隙内换道
                r_lo, r_hi = min(rs, rd), max(rs, rd)
                lo, hi = gutter_bounds(r_lo, r_hi)
                rail = tr.hline(lo, xs, xd, direction=1, lo_bound=lo, hi_bound=hi)
                if rd > rs:
                    pts = [(xs, ys + tip_s), (xs, rail), (xd, rail), (xd, yd - tip_s)]
                else:
                    pts = [(xs, ys - tip_s), (xs, rail), (xd, rail), (xd, yd + tip_s)]
                a(_polyline(pts, mc, m_marker))
                if elabel:
                    a(_edge_label((xs + xd) / 2, rail - 9, elabel, mc))
            else:                                      # ---------- 跨多泳道:走左侧走廊
                # 源侧水平段(在源泳道外侧空隙)
                if rd > rs:
                    s_lo = lane_top(rs) + LANE_H + 14
                    s_hi = lane_top(rs + 1) - 14
                else:
                    s_lo = lane_top(rs - 1) + LANE_H + 14
                    s_hi = lane_top(rs) - 14
                # 走廊 x 轨道(竖直段,向左让轨)
                corridor_x = tr.vline(corr_right, lane_top(min(rs, rd)), lane_top(max(rs, rd)) + LANE_H,
                                      direction=-1, lo_bound=corr_left, hi_bound=corr_right)
                h_src = tr.hline(s_lo, xs, corridor_x, direction=1, lo_bound=s_lo, hi_bound=s_hi)
                # 目标侧水平段
                if rd > rs:
                    d_lo = lane_top(rd - 1) + LANE_H + 14
                    d_hi = lane_top(rd) - 14
                else:
                    d_lo = lane_top(rd) + LANE_H + 14
                    d_hi = lane_top(rd + 1) - 14
                h_dst = tr.hline(d_lo, corridor_x, xd, direction=1, lo_bound=d_lo, hi_bound=d_hi)
                # 端口竖直段(固定 x,仅登记避免误判)
                ys_edge = ys + tip_s if rd > rs else ys - tip_s
                yd_edge = yd - tip_s if rd > rs else yd + tip_s
                pts = [(xs, ys_edge), (xs, h_src), (corridor_x, h_src),
                       (corridor_x, h_dst), (xd, h_dst), (xd, yd_edge)]
                a(_polyline(pts, mc, m_marker))
                if elabel:
                    a(_edge_label((xs + corridor_x) / 2, h_src - 9, elabel, mc))

    # 节点
    for r, mod in enumerate(modules):
        f, s, t, _ = PALETTE[r % len(PALETTE)]
        for nid in mod["forms"]:
            _, _, x, y = pos[nid]
            text = lbl(nid)
            fs = _font_for(text)
            x0, y0 = x - NODE_W // 2, y - NODE_H // 2
            a('<rect x="%s" y="%s" width="%d" height="%d" rx="8" fill="%s" stroke="%s" '
              'stroke-width="1.8" filter="url(#sh)"/>' % (x0, y0, NODE_W, NODE_H, f, s))
            a('<rect x="%s" y="%s" width="5" height="%d" rx="2.5" fill="%s"/>' % (x0, y0, NODE_H, s))
            a('<text x="%s" y="%s" text-anchor="middle" font-size="%s" font-weight="600" '
              'fill="%s">%s</text>' % (x + 2, y + fs * 0.36, fs, t, _esc(text)))
    a('</svg>')

    return {"svg": "\n".join(L), "ok": True, "width": width, "height": height,
            "modules": [m["name"] for m in modules],
            "nodes": sum(len(m["forms"]) for m in modules), "edges": len(edges)}


def _edge_label(x, y, text, color="#475569"):
    """连线标签(带白底,避免压线);`color` 用于跨区线跟随来源模块色。"""
    w = len(text) * 11.5 + 14
    return ('<g><rect x="%s" y="%s" width="%s" height="17" rx="8" fill="#ffffff" '
            'stroke="%s" stroke-width="1"/>'
            '<text x="%s" y="%s" text-anchor="middle" font-size="11.5" fill="%s">%s</text></g>'
            % (x - w / 2, y - 9, w, color, x, y + 3.5, color, _esc(text)))
