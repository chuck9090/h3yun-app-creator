# -*- coding: utf-8 -*-
"""自动化回读校验：期望载荷（h3design.autodsl 构建）vs 线上 LoadTriggers 里的同一条。

平台对自动化的键集是**归一化**的（新建时只发精简键集也照收，见
fixtures/automation_删除时.json），且条件是 DNF、动作是树、映射列表**无序**——
逐字节比对没有意义。这里按语义比：
  - 忽略随机/服务端字段（Id/ObjectId/SortKey/Operation/Modified*/DisplayName）
  - 字段映射（Insert/UpdateFieldMappings）按 (源,目标) 集合比
  - 别名表（RelatedSchemaCodeAliases / RelationSchemaCodeAlias）按集合比
  - 其余逐节点比；我方多出的**空列表/空字典/None/false** 视为线上省略（不算差异）"""
IGNORE = ("Id", "ObjectId", "SortKey", "Operation", "ModifiedBy", "ModifiedName",
          "ModifiedTime", "DisplayName", "Code", "IsDevMode",
          # 信封/服务端回显：保存载荷带的 ActionName/AppCode，回读时原样带回来
          "ActionName", "AppCode")
MAP_KEYS = ("InsertFieldMappings", "UpdateFieldMappings")
ALIAS_KEYS = ("RelatedSchemaCodeAliases", "RelationSchemaCodeAlias")


def _empty(v):
    """空值语义：None/[]/{}/"" 视为"线上省略"。0/false **不算空**（真值，要逐字比）。"""
    if isinstance(v, (bool, int, float)):
        return False
    return v in (None, [], {}, "")


def _drop(o):
    if isinstance(o, dict):
        return {k: _drop(v) for k, v in o.items() if k not in IGNORE}
    if isinstance(o, list):
        return [_drop(v) for v in o]
    return o


def _key(o):
    import json
    return json.dumps(o, ensure_ascii=False, sort_keys=True)


def diff(mine, live, path, out, key=None):
    """递归比对，差异写入 out（多行文本）"""
    if _empty(mine) and _empty(live):
        return          # 双方都是空值形态（null vs [] vs 缺键）—— 平台归一化噪音
    if isinstance(mine, dict) and isinstance(live, dict):
        for k in sorted(set(mine) | set(live)):
            if k not in live:
                if not _empty(mine[k]):       # 我方多出的空值 = 线上省略，不算差异
                    out.append("  多余 %s.%s = %s"
                               % (path, k, _key(mine[k])[:140]))
            elif k not in mine:
                if not _empty(live[k]):     # 线上多出的空值 = 服务端归一化补的
                    out.append("  缺失 %s.%s = %s" % (path, k, _key(live[k])[:160]))
            else:
                diff(mine[k], live[k], "%s.%s" % (path, k), out, k)
    elif isinstance(mine, list) and isinstance(live, list):
        if key in MAP_KEYS:
            ms = {_key([m.get("SourceField"), m.get("TargetField")]) for m in mine}
            ls = {_key([m.get("SourceField"), m.get("TargetField")]) for m in live}
            for x in sorted(ls - ms):
                out.append("  映射缺失 %s %s" % (path, x))
            for x in sorted(ms - ls):
                out.append("  映射多出 %s %s" % (path, x))
        elif key in ALIAS_KEYS:
            ms = {_key(x) for x in mine}
            ls = {_key(x) for x in live}
            for x in sorted(ls - ms):
                out.append("  别名缺失 %s %s" % (path, x))
            for x in sorted(ms - ls):
                out.append("  别名多出 %s %s" % (path, x))
        elif len(mine) != len(live):
            out.append("  长度差 %s: 我 %d 线上 %d\n    我=%s\n    线上=%s"
                       % (path, len(mine), len(live), _key(mine)[:300],
                          _key(live)[:300]))
        else:
            for i, (m, l) in enumerate(zip(mine, live)):
                diff(m, l, "%s[%d]" % (path, i), out, None)
    elif mine != live:
        out.append("  值不同 %s\n    我   = %s\n    线上 = %s"
                   % (path, _key(mine)[:200], _key(live)[:200]))


def triggers_of(rd):
    """LoadTriggers 响应 → 触发器列表（ReturnData.Triggers / ReturnData 本身是列表）"""
    rd = rd or {}
    data = rd.get("ReturnData")
    if isinstance(data, dict):
        for k in ("Triggers", "triggers"):
            if isinstance(data.get(k), list):
                return data[k]
        return []
    if isinstance(data, list):
        return data
    return []


def compare(expected_payload, live_trigger):
    """期望载荷 vs 线上同一条 → {"ok", "diffs"}"""
    out = []
    diff(_drop(expected_payload), _drop(live_trigger), "Trigger", out, None)
    return {"ok": not out, "diffs": out}


def format_report(key, name, code, res, n_live=0):
    lines = ["== 自动化 %s（%s）%s ==" % (key, name, code)]
    if res is None:
        lines.append("线上没有这条自动化（ObjectId 对不上，先 autobuild）")
        lines.append("核对结果: FAIL")
    else:
        for line in res["diffs"]:
            lines.append(line)
        lines.append("核对结果: %s%s"
                      % ("PASS" if res["ok"] else "FAIL",
                         "" if n_live <= 1 else "（该表共 %d 条自动化）" % n_live))
    return "\n".join(lines)
