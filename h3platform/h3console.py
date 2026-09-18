# -*- coding: utf-8 -*-
"""氚云设计器控制台接口（新引擎真实建表端点）：
POST {base}/Console/SheetDesigner/OnAction
表单编码 x-www-form-urlencoded: PostData=<JSON字符串>"""
import json
import urllib.parse
import urllib.request
import urllib.error

from . import api as h3api

CONFIG_PATH = h3api.CONFIG_PATH


class ConsoleError(Exception):
    def __init__(self, message, raw=None):
        super().__init__(message)
        self.raw = raw


class H3Console:
    def __init__(self, cfg=None):
        if cfg is None:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        self.base_url = cfg["baseUrl"].rstrip("/") + "/"
        self.authorization = cfg["authorization"]
        self.engine_code = cfg["engineCode"]

    def _call(self, post_json, headers_extra=None, timeout=120,
              endpoint="Console/SheetDesigner/OnAction"):
        body = urllib.parse.urlencode(
            {"PostData": json.dumps(post_json, ensure_ascii=False)}).encode("utf-8")
        req = urllib.request.Request(self.base_url + endpoint,
                                     data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
        req.add_header("Authorization", self.authorization)
        req.add_header("EngineCode", self.engine_code)
        if headers_extra:
            for k, v in headers_extra.items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise ConsoleError(f"HTTP {e.code}", e.read().decode("utf-8", "replace"))
        except urllib.error.URLError as e:
            raise ConsoleError(f"network error: {e}")
        if not raw.strip():
            raise ConsoleError("empty response")
        try:
            return json.loads(raw)
        except ValueError:
            raise ConsoleError("non-JSON response: " + raw[:300])

    def action(self, name, **extra):
        """任意 OnAction 动作"""
        payload = {"ActionName": name}
        payload.update(extra)
        return self._call(payload)

    def load_form(self, sheet_code):
        """设计器加载表单（完整设计态，含 SchemaStr/BizSheetStr 原文）"""
        return self.action("LoadForm", id=sheet_code)

    # ---- 自动化（触发器）：另一套端点 /Automatic/OnAction -------------------
    def auto_action(self, post_json, timeout=120):
        return self._call(post_json, timeout=timeout,
                          endpoint="Automatic/OnAction")

    def save_trigger(self, payload):
        """保存一条自动化。payload = automation.build_trigger(...) 的产物
        （信封已含 ActionName=SaveTrigger）。"""
        return self.auto_action(payload)

    def load_triggers(self, sheet_code):
        """读回表单下全部自动化 → ReturnData.Triggers[]（与保存载荷同形）"""
        return self.auto_action({"ActionName": "LoadTriggers",
                                 "SchemaCode": sheet_code})


def save_form_console(console, sheet_code, engine_code, app_code, parent_code,
                      display_name, schema_dict, biz_dict,
                      name_schema="", display_setting=1, pc_layout="1",
                      pc_layout_config=('{"LayoutType":1,"TitleFontWeight":400,'
                                        '"TitleWidth":84,"TitleAlign":"left","BorderShow":false}'),
                      mobile_layout="1",
                      mobile_layout_config=('{"LayoutType":1,"TitleFontWeight":400,'
                                            '"TitleWidth":80,"TitleAlign":"left","BorderShow":false}'),
                      node_type=200, icon="icon-cgfk", open_type=0,
                      enable_data_acl=True, control_settings_str="[]",
                      describe_image_list=(), summary="", extra_top=None):
    """构造并调用设计器 SaveForm。schema_dict/biz_dict 为 dict，内部会序列化为字符串字段。"""
    payload = {
        "ActionName": "SaveForm",
        "SheetCode": sheet_code,
        "EngineCode": engine_code,
        "AppCode": app_code,
        "ParentCode": parent_code,
        "DisplayName": display_name,
        "DisplaySetting": display_setting,
        "PCLayout": pc_layout,
        "PCLayoutConfig": pc_layout_config,
        "MobileLayout": mobile_layout,
        "MobileLayoutConfig": mobile_layout_config,
        "NodeType": node_type,
        "Icon": icon,
        "OpenType": open_type,
        "IsBindBizService": False,
        "SchemaStr": json.dumps(schema_dict, ensure_ascii=False),
        "BizSheetStr": json.dumps(biz_dict, ensure_ascii=False),
        "ControlSettingsStr": control_settings_str,
        "DescribeImageList": list(describe_image_list),
        "Summary": summary,
    }
    if extra_top:
        payload.update(extra_top)
    return console._call(payload)
