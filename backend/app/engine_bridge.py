# -*- coding: utf-8 -*-
"""引擎桥接:把后端项目模型 → 引擎(h3service)所需凭据/结构,并调用确定性能力。

用户只提供 `h3_token` + `appCode`;`engineCode` 从 token(JWT)自动解析。
"""
import base64
import json
import os
import sys
import time

from .core import config as C
from .core import security as sec

# 引擎在仓库根目录,加入 import 路径
if C.ROOT_DIR not in sys.path:
    sys.path.insert(0, C.ROOT_DIR)

from h3service import design as ENGINE_DESIGN      # noqa: E402
from h3service import engine as ENGINE             # noqa: E402


# ---------------------------------------------------------------- token
def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def normalize_token(token: str) -> str:
    token = (token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def parse_h3_token(token: str) -> dict:
    """解析 h3_token(JWT)取 enginecode/exp/loginname。

    **安全说明**:此处**只解析 payload、不验签**(没有氚云公钥,无法在本地验证);
    因此 token 的真伪最终由氚云平台在真实调用时判定(Authorization 无效即被拒)。
    这里只用于:①自动取得 engineCode(用户无需手填);②判断是否过期以给出提示。
    - 缺少 `exp` 视为**不可用**(宁可保守,避免来源不明的 token 被当作有效)。
    - 返回 `raw` 供后续拼 Authorization;接口层**绝不回显**。
    """
    token = normalize_token(token)
    out = {"valid": False, "engineCode": "", "expiresAt": 0, "expired": True,
           "loginName": "", "userId": "", "raw": token}
    if not token or token.count(".") != 2:
        return out
    try:
        payload = json.loads(_b64d(token.split(".")[1]))
    except Exception:
        return out
    exp = int(payload.get("exp", 0) or 0)
    if not payload.get("enginecode") or not exp:
        return out                      # 缺 enginecode 或 exp → 视为不可用
    out["valid"] = True
    out["engineCode"] = payload.get("enginecode", "") or ""
    out["loginName"] = payload.get("loginname", "") or ""
    out["userId"] = payload.get("userid", "") or ""
    out["expiresAt"] = exp
    out["expired"] = exp < int(time.time())
    return out


def build_cfg(project: dict) -> dict:
    """项目 → 引擎凭据 dict(不落配置文件)。

    engineCode **以用户填写并入库的 projects.engine_code 为准**;为空时才回退 token 解析
    (兼容旧数据)。authorization 用 h3_token。
    """
    token = normalize_token(sec.decrypt_secret(project.get("h3_token", "")))
    info = parse_h3_token(token)
    engine_code = (project.get("engine_code") or "").strip() or info.get("engineCode", "")
    return {
        "baseUrl": C.DEFAULT_BASE_URL,
        "authorization": ("Bearer " + token) if token else "",
        "engineCode": engine_code,
        "appCode": project.get("app_code", ""),
    }


def credentials_status(project: dict) -> dict:
    token = normalize_token(sec.decrypt_secret(project.get("h3_token", "")))
    info = parse_h3_token(token)
    engine_code = (project.get("engine_code") or "").strip() or info.get("engineCode", "")
    return {
        "configured": bool(engine_code and project.get("app_code")
                           and info["valid"] and not info["expired"]),
        "appCode": project.get("app_code", ""),
        "engineCode": engine_code,
        "hasToken": bool(token),
        "tokenValid": info["valid"],
        "tokenExpired": info["expired"],
        "loginName": info.get("loginName", ""),
        "expiresAt": info.get("expiresAt", 0),
    }


# ---------------------------------------------------------------- 落盘 & 校验
def sync_sheets(slug: str, design: dict, app_code: str = "") -> dict:
    """design(ER 结构/自动化) → projects/<slug>/sheets|automations/*.json,并跑离线校验。"""
    res = ENGINE_DESIGN.write_design(slug, design, app_code=app_code)
    check = None
    try:
        check = ENGINE.run_check(slug, app_code=app_code)
    except ENGINE.EngineError as e:
        res["error"] = str(e)
    except Exception as e:      # DSL 抛出的 ValueError 等
        res["error"] = str(e)
    return {"written": res.get("written", []),
            "automations": res.get("automations", []),
            "design": res.get("design"),
            "error": res.get("error", ""), "check": check}


def read_sheets_design(slug: str) -> dict:
    return ENGINE_DESIGN.read_design(slug)


def er_graph(slug: str, app_code: str = "") -> dict:
    return ENGINE.er_graph(slug, app_code=app_code or None)


def preview(slug: str, sheet: str, cfg=None) -> dict:
    return ENGINE.preview_payload(slug, sheet, cfg)


# ---------------------------------------------------------------- 部署 & 核对
def deploy(slug: str, cfg: dict, force: bool = False, progress=None) -> dict:
    """建表 → 归组(应用菜单分组) → 建自动化。all_ok = 三者都成功。"""
    def _p(msg, pct=None):
        if progress:
            progress(msg, pct=pct)

    _p("建表:写入氚云表单定义…", pct=20)
    res = ENGINE.run_build(slug, None, cfg, force=force, allow_root=False)

    grp = {"groups": [], "moved": [], "all_ok": True}
    _p("归组:整理应用菜单分组…", pct=60)
    try:
        grp = ENGINE.run_group(slug, cfg, allow_root=False)
    except Exception as e:
        grp = {"groups": [], "moved": [],
               "groupsError": str(e)[:400], "all_ok": False}
    res["groups"] = grp.get("groups", [])
    res["moved"] = grp.get("moved", [])
    if grp.get("groupsError"):
        res["groupsError"] = grp["groupsError"]

    auto = {"automations": [], "all_ok": True}
    _p("自动化:创建/更新触发器…", pct=80)
    try:
        auto = ENGINE.run_autobuild(slug, cfg, None, allow_root=False)
    except Exception as e:
        auto = {"automations": [{"key": "-", "created": False, "err": str(e)[:400]}],
                "all_ok": False}
    res["automations"] = auto.get("automations", [])
    res["all_ok"] = (bool(res.get("all_ok")) and bool(grp.get("all_ok"))
                     and bool(auto.get("all_ok")))
    return res


def verify(slug: str, cfg: dict, progress=None) -> dict:
    """回读核对表单 + 自动化。"""
    def _p(msg, pct=None):
        if progress:
            progress(msg, pct=pct)

    _p("回读表单定义…", pct=30)
    res = ENGINE.run_verify(slug, None, cfg, allow_root=False)
    _p("回读自动化…", pct=70)
    try:
        auto = ENGINE.run_autoverify(slug, cfg, None, allow_root=False)
        res["automations"] = auto.get("automations", [])
        res["all_ok"] = bool(res.get("all_ok")) and bool(auto.get("all_ok"))
    except Exception:
        res.setdefault("automations", [])
    return res


def refresh_knowledge() -> dict:
    """编译设计知识库:项目 DSL(corpus/patterns)+ 全局资料库(library.md)。"""
    info = ENGINE.refresh_knowledge()
    try:
        from .services import library as library_service
        lib = library_service.render_library_digest()
        if isinstance(info, dict):
            info["library"] = lib.get("items", 0)
    except Exception:
        pass
    return info
