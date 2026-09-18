# -*- coding: utf-8 -*-
"""氚云设计态 HTTP 封装(个人身份授权:Authorization Bearer h3_token + EngineCode)。

覆盖:`/v1/functionnode`(建分组/移动)、`/v1/formdesign/save`、`/v1/schema`。

**不含业务数据读写**:本方案只负责"搭建应用结构"(表/字段/子表/自动化),
不涉及表单记录(数据)的增删改查。历史 OpenApi(EngineCode+EngineSecret)实现已移除。
"""
import json
import os
import time
import urllib.request
import urllib.error

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.environ.get("H3F_DATA_DIR") or os.path.join(_ROOT, "data")
CONFIG_PATH = os.path.join(_DATA_DIR, "config.json")
# 运行数据目录 data/config.json(仓库内无凭据文件);凭据由调用方注入 H3(cfg)

# 响应键大小写不一（设计态接口 camelCase，LoadForm 回读 PascalCase），统一不区分大小写取值
def _ci(d, *keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        for kk, vv in d.items():
            if kk.lower() == k.lower():
                return vv
    return None


class H3Error(Exception):
    def __init__(self, message, raw=None):
        super().__init__(message)
        self.raw = raw


class H3:
    def __init__(self, cfg=None):
        if cfg is None:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        self.base_url = cfg["baseUrl"].rstrip("/") + "/"
        self.engine_code = cfg["engineCode"]
        self.authorization = cfg["authorization"]
        self.app_code = cfg.get("appCode", "")
        self.app_name = cfg.get("appName", "")

    def _call(self, url, payload=None, timeout=120, headers_extra=None,
              method=None):
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if method is None:
            method = "POST" if data else "GET"
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("EngineCode", self.engine_code)
        if headers_extra:
            for k, v in headers_extra.items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise H3Error(f"HTTP {e.code} on {url.split('?')[0]}", e.read().decode("utf-8", "replace"))
        except urllib.error.URLError as e:
            raise H3Error(f"network error: {e}")
        if not body.strip():
            raise H3Error(f"empty response from {url.split('?')[0]}")
        try:
            return json.loads(body)
        except ValueError:
            raise H3Error(f"non-JSON response from {url.split('?')[0]}: {body[:300]}")

    # ---- web 接口（Authorization + EngineCode）----
    def _web_headers(self):
        return {"Authorization": self.authorization}

    def _check_web(self, resp):
        if resp is None:
            raise H3Error("empty response")
        ok = _ci(resp, "successful")
        if ok is False or _ci(resp, "errorCode") is not None:
            msg = _ci(resp, "errorMessage") or _ci(resp, "message") or "unknown error"
            raise H3Error(msg, resp)
        return _ci(resp, "returnData") if "returnData" in resp else resp

    def save_form(self, schema_request):
        """保存表单结构（建表）。schema_request 为 FormSchemaRequest 同构 dict。"""
        url = self.base_url + "v1/formdesign/save"
        resp = self._call(url, schema_request, headers_extra=self._web_headers())
        return self._check_web(resp)

    def get_schema(self, schema_code):
        """读取已保存的表单结构（用于回读验证）。无此表单返回 None。"""
        url = (self.base_url + "v1/schema?schemaCode=" + schema_code + "&timestamp=-1")
        resp = self._call(url, headers_extra=self._web_headers())
        ec = _ci(resp, "errorCode")
        if ec and "isnull" in str(ec):
            return None
        if _ci(resp, "successful") is False:
            raise H3Error(_ci(resp, "errorMessage") or "schema read failed", resp)
        return _ci(resp, "returnData") or resp

    # ---- 表单分组（应用菜单分组；v1/functionnode，载荷逐字对照 UI，2026-09-09）----
    def create_group(self, app_code, display_name, parent_code=None):
        """建分组（nodeType=230）。顶层分组 parentCode=appCode（可省 = 顶层）。
        UI 实证建组是两步：create 落一个 32hex 分组码（非表单编码格式），
        随后必须 update 改名 —— 客户端 create 后要跟 update_group。返回 (code, objectId)。"""
        payload = {"appCode": app_code, "parentCode": parent_code or app_code,
                   "displayName": display_name, "nodeType": 230, "icon": ""}
        resp = self._call(self.base_url + "v1/functionnode", payload,
                          headers_extra=self._web_headers())
        return self._node_keys(self._check_web(resp))

    def update_group(self, app_code, group_code, object_id, display_name,
                     parent_code=None):
        """分组改名/落定（update 载荷 = create 全套字段 + code/objectId/summary）。"""
        payload = {"appCode": app_code, "parentCode": parent_code or app_code,
                   "displayName": display_name, "nodeType": 230, "icon": "",
                   "code": group_code, "objectId": object_id, "summary": ""}
        resp = self._call(self.base_url + "v1/functionnode/update", payload,
                          headers_extra=self._web_headers())
        return self._check_web(resp)

    def move_node(self, code, parent_code):
        """归组/移动：PUT v1/functionnode/sort。code=表单编码或分组码，
        parentCode=目标分组码（表单置回顶层 = appCode）。"""
        resp = self._call(self.base_url + "v1/functionnode/sort",
                          {"code": code, "parentCode": parent_code},
                          method="PUT", headers_extra=self._web_headers())
        return self._check_web(resp)

    @staticmethod
    def _node_keys(resp):
        """从 functionnode 响应取 (code, node_id)：兼容顶层或 ReturnData 嵌套、键大小写。
        实证（2026-09-09）：create 响应 = {id: GUID, code: 32hex}；update 载荷要用
        objectId 字段传同一个 GUID（UI 载荷同）。"""
        d = resp
        if isinstance(d, dict):
            rd = None
            for k, v in d.items():
                if k.lower() == "returndata":
                    rd = v
            if isinstance(rd, dict):
                d = rd
        code, oid = _ci(d, "code"), _ci(d, "id") or _ci(d, "objectid")
        if code and oid:
            return code, oid
        raise H3Error("functionnode 响应缺 code/id: %s" % str(resp)[:300], resp)
