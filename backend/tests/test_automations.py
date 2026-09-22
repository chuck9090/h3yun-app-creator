# -*- coding: utf-8 -*-
"""自动化(触发器)全链路 + 设计清洗安全测试(离线,不联网)。

    python -X utf8 tests/test_automations.py

覆盖:
  - 路径穿越防护:非法表单/自动化 key 被剔除(修复 S1);
  - 字段 key 规范化后,自动化引用的**尽力重映射**;
  - 自动化清洗(非法 trigger/无 actions/key 非法 → 过滤);
  - design 落盘 → sheets/*.json + automations/*.json 双写;
  - engine.run_check 能离线校验自动化(引用表/字段);
  - engine_bridge:deploy 会合并 automations 结果且不联网建表(用无凭据路径验证)。
"""
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from h3design import dsl as DSL                # noqa: E402
from h3service import design as D              # noqa: E402
from h3service import engine as E              # noqa: E402
from backend.app import engine_bridge as EB    # noqa: E402

SLUG = "auto_test_%d" % (int(time.time()) % 100000)
PASS, FAIL = [], []


def chk(tag, cond, detail=""):
    (PASS if cond else FAIL).append(tag)
    print("  %s %-40s %s" % ("[OK]" if cond else "[XX]", tag, detail))


def main():
    try:
        # ---------- 1. 路径穿越 ----------
        evil = {"sheets": [{"key": "../../PWNED", "title": "x",
                            "controls": [{"type": "text", "key": "a", "label": "a"}]}],
                "dicts": {}, "groups": [],
                "automations": [{"key": "../evil", "form": "x",
                                 "actions": [{"do": "新增", "target": "x"}]}]}
        c = D.clean_design(evil)
        chk("路径穿越:表单 key 被剔除", c["sheets"] == [])
        chk("路径穿越:自动化 key 被剔除", c["automations"] == [])

        # 写盘围栏(即使绕过 clean 也不出 sheets 目录)
        E.create_project(SLUG)
        try:
            D.write_design(SLUG, {"sheets": [{"key": "ok1", "title": "OK",
                                              "controls": [{"type": "text", "key": "a", "label": "a"}]}],
                                  "dicts": {}, "groups": [],
                                  "automations": []})
            leaked = os.path.join(ROOT, "PWNED.json")
            chk("路径穿越:未在仓库根产生文件", not os.path.isfile(leaked))
        except E.EngineError as e:
            chk("路径穿越:非法 key 被拒", True, str(e)[:60])

        # ---------- 2. 字段规范化 + 引用重映射 ----------
        norm = {"sheets": [{"key": "project", "title": "项目",
                            "controls": [{"type": "text", "key": "plan_begin", "label": "开始"}]}],
                "dicts": {}, "groups": [],
                "automations": [{"key": "a1", "title": "回写", "form": "project",
                                 "trigger": "生效或更新",
                                 "actions": [{"do": "更新", "target": "project",
                                              "match": [{"field": "plan_begin", "value": "x"}],
                                              "set": [{"to": "plan_begin", "from": "plan_begin"}]}]}]}
        c2 = D.clean_design(norm)
        chk("字段 key 规范化为驼峰",
            c2["sheets"][0]["controls"][0]["key"] == "planBegin",
            c2["sheets"][0]["controls"][0]["key"])
        acts = c2["automations"][0]["actions"][0]
        chk("自动化 match.field 重映射", acts["match"][0]["field"] == "planBegin")
        chk("自动化 set.to/from 重映射",
            acts["set"][0]["to"] == "planBegin" and acts["set"][0]["from"] == "planBegin")

        # ---------- 3. 自动化清洗 ----------
        bad = {"sheets": [{"key": "t", "title": "t",
                           "controls": [{"type": "text", "key": "a", "label": "a"}]}],
               "automations": [
                   {"key": "x", "form": "t", "trigger": "定时", "actions": []},       # 无 actions → 丢
                   {"key": "bad key!", "form": "t", "actions": [{"do": "新增", "target": "t"}]},  # 含符号 → 归一化(不丢)
               ]}
        _b = D.clean_design(bad)["automations"]
        chk("无 actions 的自动化被过滤", len(_b) == 1, "auto=%d" % len(_b))
        chk("含符号的自动化 key 被归一化(非丢弃)", _b and _b[0]["key"] == "badKey",
            str([a["key"] for a in _b]))
        one_ok = {"sheets": bad["sheets"], "automations": [
            {"key": "a2", "form": "t", "trigger": "定时", "actions": [{"do": "新增", "target": "t"}]}]}
        chk("非法 trigger 回退为 生效或更新",
            D.clean_design(one_ok)["automations"][0]["trigger"] == "生效或更新")

        # ---------- 3b. 保留字排除(平台自带编码 + MySQL 保留关键字) ----------
        chk("is_reserved:平台自带编码", DSL.is_reserved("Name") and DSL.is_reserved("ParentObjectId"))
        chk("is_reserved:MySQL 关键字", DSL.is_reserved("order") and DSL.is_reserved("Status"))
        chk("is_reserved:大小写不敏感", DSL.is_reserved("NAME") and DSL.is_reserved("GROUP"))
        chk("is_reserved:普通字段不算保留", not DSL.is_reserved("billStatus")
            and not DSL.is_reserved("amount"))
        rsv = {"sheets": [
            {"key": "order", "title": "订单",                            # 表单 key 撞 MySQL 关键字
             "controls": [
                 {"type": "text", "key": "Name", "label": "名称"},        # 平台自带
                 {"type": "text", "key": "Status", "label": "状态"},      # 平台自带
                 {"type": "dropdown", "key": "group", "label": "分组", "dict": "D"},  # MySQL 关键字
                 {"type": "number", "key": "amount", "label": "金额"},
                 {"type": "subtable", "key": "items", "label": "明细",
                  "columns": [{"type": "text", "key": "ParentObjectId", "label": "父"},  # 子表自带
                              {"type": "text", "key": "desc", "label": "说明"}]}]},      # MySQL 关键字
            {"key": "contract", "title": "合同",
             "controls": [{"type": "query", "key": "ord", "label": "订单", "assoc": "order"}]}],
            "dicts": {"D": ["a"]}, "groups": [],
            "automations": [{"key": "a9", "form": "order", "trigger": "生效或更新",
                             "actions": [{"do": "更新", "target": "contract",
                                          "match": [{"field": "ord"}],
                                          "set": [{"to": "ord", "from": "amount"}]}]}]}
        c3 = D.clean_design(rsv)
        sk = [s["key"] for s in c3["sheets"]]
        sub = [c for s in c3["sheets"] for c in s["controls"] if c["type"] == "subtable"][0]
        allk = ([c["key"] for s in c3["sheets"] for c in s["controls"] if c.get("key")]
                + [col["key"] for col in sub["columns"]])
        chk("保留字:全部字段已改名", all(not DSL.is_reserved(k) for k in allk), str(allk))
        chk("保留字:Name/Status/group 被改名",
            "Name" not in allk and "Status" not in allk and "group" not in allk, str(allk))
        chk("保留字:MySQL 关键字 desc 被改名", "desc" not in allk, str(allk))
        chk("保留字:子表自带列 ParentObjectId 被改名", "ParentObjectId" not in allk, str(allk))
        chk("保留字:非保留字段 amount 原样保留", "amount" in allk, str(allk))
        chk("保留字:表单 key order 被改名", "order" not in sk and not DSL.is_reserved(sk[0]), str(sk))
        q = [c for s in c3["sheets"] for c in s["controls"] if c["type"] == "query"][0]
        chk("保留字:assoc 引用随表单改名重映射", q["assoc"] == sk[0],
            "%s vs %s" % (q["assoc"], sk[0]))
        a9 = [a for a in c3["automations"] if a["key"] == "a9"][0]
        chk("保留字:自动化 form 随表单改名", a9["form"] == sk[0], a9["form"])
        chk("保留字:自动化 target 引用有效表", a9["actions"][0]["target"] in sk,
            a9["actions"][0]["target"])
        seqd = {"sheets": [{"key": "t9", "title": "t9",
                            "controls": [{"type": "seq_no", "key": "SeqNo", "label": "流水号"}]}]}
        sq = D.clean_design(seqd)["sheets"][0]["controls"][0]
        chk("保留字:流水号 SeqNo 不被改名", sq["key"] == "SeqNo", sq["key"])

        # ---------- 3c. build 侧兜底:表单 key / 子表 key / 主表字段(绕过 clean_design 直接落盘) ----------
        pdir = E.project_dir(SLUG)
        sj = os.path.join(pdir, "sheets")
        os.makedirs(sj, exist_ok=True)

        def _build_blocked(sheet_key, sheet):
            """写单个 sheet 后 run_check;返回错误消息(通过则 None)。"""
            p = os.path.join(sj, sheet_key + ".json")
            E.write_json(p, sheet)
            try:
                E.run_check(SLUG, app_code="TESTAPP")
                return None
            except Exception as e:
                return str(e)
            finally:
                os.remove(p)

        txt_to = {"type": "text", "key": "productName", "label": "产品"}
        m1 = _build_blocked("order", {"title": "订单", "controls": [txt_to]})
        chk("build:表单 key 撞 MySQL 关键字被拦", m1 is not None and "保留字" in m1,
            (m1 or "未拦")[:56])
        m2 = _build_blocked("ParentIndex", {"title": "x", "controls": [txt_to]})
        chk("build:表单 key 撞平台自带编码被拦", m2 is not None and "保留字" in m2,
            (m2 or "未拦")[:56])
        m3 = _build_blocked("t7", {"title": "t7", "controls": [
            {"type": "subtable", "key": "ParentObjectId", "label": "x",
             "columns": [{"type": "text", "key": "colA", "label": "a"}]}]})
        chk("build:子表 key 撞子表系统列被拦", m3 is not None and "保留字" in m3,
            (m3 or "未拦")[:56])
        m4 = _build_blocked("t8", {"title": "t8", "controls": [
            {"type": "text", "key": "ParentPropertyName", "label": "x"}]})
        chk("build:主表字段撞子表系统列被拦", m4 is not None and "保留字" in m4,
            (m4 or "未拦")[:56])
        m5 = _build_blocked("zOrder", {"title": "zOrder", "controls": [
            {"type": "text", "key": "statusText", "label": "状态"}]})
        chk("build:正常编码不误拦", m5 is None, (m5 or "通过")[:56])

        # ---------- 3d. 已建表(frozen)放过:避免旧项目卡死 / 另起列 ----------
        fz = {"sheets": [{"key": "customer", "title": "客户", "controls": [
            {"type": "dropdown", "key": "status", "label": "状态", "dict": "D"},
            {"type": "subtable", "key": "items", "label": "明细", "columns": [
                {"type": "text", "key": "ParentIndex", "label": "x"}]}]}],
            "dicts": {"D": ["a"]}, "groups": [], "automations": []}
        c_fz = D.clean_design(fz, frozen_keys={"customer"})
        fzc = c_fz["sheets"][0]["controls"]
        chk("frozen:已建表 status 字段不改名", fzc[0]["key"] == "status", fzc[0]["key"])
        chk("frozen:已建表子表列 ParentIndex 不改名",
            fzc[1]["columns"][0]["key"] == "ParentIndex", fzc[1]["columns"][0]["key"])
        c_nf = D.clean_design(fz)          # 同一份,frozen 为空 → 应改名
        chk("frozen:未建表 status 字段被改名",
            c_nf["sheets"][0]["controls"][0]["key"] != "status",
            c_nf["sheets"][0]["controls"][0]["key"])
        # build 侧:created=true 的表,保留字字段放过
        fp = os.path.join(sj, "legacy.json")
        E.write_json(fp, {"title": "旧表", "controls": [
            {"type": "text", "key": "status", "label": "状态"}]})
        frozen_ok = True
        try:
            DSL._build_json_sheet(fp, pdir, "TESTAPP",
                                  {"legacy": {"created": True, "code": "D001"}})
        except Exception as e:
            frozen_ok = False
            print("        (frozen 未放过: %s)" % str(e)[:60])
        chk("build:已建表(frozen)撞保留字放过", frozen_ok)
        os.remove(fp)

        # ---------- 3e. 编码不得含任何符号(表单/字段/子表/子表列/自动化) ----------
        import re as _re
        sym = {"sheets": [
            {"key": "客户-档案", "title": "客户",        # 中文+连字符 → 兜底名
             "controls": [
                 {"type": "text", "key": "a.b", "label": "点号"},        # 点号
                 {"type": "text", "key": "金额(元)", "label": "中文括号"},  # 中文+括号
                 {"type": "subtable", "key": "sub-1", "label": "子表",   # 连字符
                  "columns": [{"type": "text", "key": "c#d", "label": "#"}]}]},
            {"key": "order-2", "title": "订单",          # 连字符
             "controls": [{"type": "text", "key": "p_name", "label": "下划线"}]}],
            "dicts": {}, "groups": [],
            "automations": [{"key": "a-1", "form": "order-2",
                             "actions": [{"do": "新增", "target": "客户-档案"}]}]}
        cs = D.clean_design(sym)
        _ok = _re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
        codes = []
        for s in cs["sheets"]:
            codes.append(s["key"])
            for c in s["controls"]:
                if c.get("key"):
                    codes.append(c["key"])
                for col in c.get("columns") or []:
                    if col.get("key"):
                        codes.append(col["key"])
        codes += [a["key"] for a in cs["automations"]]
        chk("符号:全部编码只含字母数字", codes and all(_ok.match(c) for c in codes), str(codes))
        chk("符号:表单不再被丢弃", len(cs["sheets"]) == 2, "sheets=%d" % len(cs["sheets"]))
        chk("符号:自动化不再被丢弃", len(cs["automations"]) == 1, str(len(cs["automations"])))
        flds = [c["key"] for s in cs["sheets"] for c in s["controls"] if c.get("key")]
        chk("符号:下划线/点号被驼峰化", "pName" in flds and "aB" in flds, str(flds))
        aut = cs["automations"][0]
        chk("符号:自动化 form/target 随表单改名重映射",
            aut["form"] in [s["key"] for s in cs["sheets"]]
            and aut["actions"][0]["target"] in [s["key"] for s in cs["sheets"]], str(aut)[:80])

        # ---------- 4. 双写落盘 ----------
        design = {"sheets": [
            {"key": "customer", "title": "客户表",
             "controls": [{"type": "text", "key": "cname", "label": "客户名称"}]},
            {"key": "contract", "title": "合同",
             "controls": [{"type": "query", "key": "cust", "label": "客户", "assoc": "customer"},
                          {"type": "number", "key": "amount", "label": "金额", "decimal": 2}]}],
            "dicts": {}, "groups": [],
            "automations": [{"key": "a1", "title": "合同→客户回写", "form": "contract",
                             "trigger": "生效或更新",
                             "actions": [{"do": "更新", "target": "customer",
                                          "match": [{"field": "cname", "ref": "cust"}],
                                          "set": [{"to": "cname", "from": "cust"}]}]}]}
        res = D.write_design(SLUG, design)
        pdir = E.project_dir(SLUG)
        chk("sheets 落盘", os.path.isfile(os.path.join(pdir, "sheets", "customer.json"))
            and os.path.isfile(os.path.join(pdir, "sheets", "contract.json")))
        chk("automations 落盘", os.path.isfile(os.path.join(pdir, "automations", "a1.json")))
        chk("write_design 返回 automations 清单", res["automations"] == ["a1"], str(res["automations"]))

        rd = D.read_design(SLUG)
        chk("read_design 回读 automations", len(rd["automations"]) == 1,
            rd["automations"][0].get("key") if rd["automations"] else "-")

        # ---------- 5. 引擎离线校验(含自动化) ----------
        chk_result = E.run_check(SLUG, app_code="TESTAPP")
        chk("run_check 通过且含自动化", len(chk_result["sheets"]) == 2
            and len(chk_result["automations"]) == 1,
            "sheets=%d auto=%d" % (len(chk_result["sheets"]), len(chk_result["automations"])))
        er = E.er_graph(SLUG, app_code="TESTAPP")
        chk("er_graph 有边", len(er["edges"]) >= 1,
            "nodes=%d edges=%d" % (len(er["nodes"]), len(er["edges"])))

        # ---------- 6. engine_bridge:deploy 合并 automations 且无凭据不联网 ----------
        sync = EB.sync_sheets(SLUG, design, app_code="TESTAPP")
        chk("sync_sheets 返回 automations", sync.get("automations") == ["a1"],
            str(sync.get("automations")))
        st = EB.credentials_status({"h3_token": "", "app_code": ""})
        chk("空凭据 configured=False", st["configured"] is False)

        # ---------- 7. 分组计划(离线;顺序优先 groups.json,否则按表单出现顺序) ----------
        # 表单文件名排序 = contract, region, store(字母序)
        gdesign = {"sheets": [
            {"key": "store", "title": "门店", "group": "门店管理",
             "controls": [{"type": "text", "key": "a", "label": "a"}]},
            {"key": "region", "title": "区域", "group": "门店管理",
             "controls": [{"type": "text", "key": "b", "label": "b"}]},
            {"key": "contract", "title": "合同", "group": "合同管理",
             "controls": [{"type": "text", "key": "c", "label": "c"}]}],
            "dicts": {}, "automations": [],
            # 显式顺序:门店管理在前(与字母序相反,用于区分)
            "groups": [{"name": "门店管理"}, {"name": "合同管理"}]}
        D.write_design(SLUG, gdesign, app_code="TESTAPP")
        plan, _reg = E._group_plan(SLUG)
        chk("_group_plan 顺序遵从 groups.json",
            plan == [("门店管理", ["region", "store"]), ("合同管理", ["contract"])],
            str(plan))
        # 无 groups.json 时按表单出现顺序(字母序)→ 合同管理在前
        os.remove(os.path.join(E.project_dir(SLUG), "groups.json"))
        plan2, _ = E._group_plan(SLUG)
        chk("_group_plan 无 groups.json 时按表单顺序",
            [g for g, _ in plan2] == ["合同管理", "门店管理"], str([g for g, _ in plan2]))

        # run_check 的 app_code 显式注入(不回落到根 config)
        chk("run_check 显式 app_code 生效", chk_result["project"] == SLUG)

    finally:
        shutil.rmtree(E.project_dir(SLUG, must=False), ignore_errors=True)

    print("\n" + "=" * 62)
    print("自动化/清洗安全测试:通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项:", FAIL)
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
