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
                   {"key": "bad key!", "form": "t", "actions": [{"do": "新增", "target": "t"}]},  # 非法 key → 丢
               ]}
        chk("非法自动化被过滤", D.clean_design(bad)["automations"] == [])
        one_ok = {"sheets": bad["sheets"], "automations": [
            {"key": "a2", "form": "t", "trigger": "定时", "actions": [{"do": "新增", "target": "t"}]}]}
        chk("非法 trigger 回退为 生效或更新",
            D.clean_design(one_ok)["automations"][0]["trigger"] == "生效或更新")

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
