# -*- coding: utf-8 -*-
"""系统设置(LLM,仅 admin)。契约见 docs/ARCHITECTURE.md §5。

  GET /api/settings/llm   {baseUrl, model, hasKey}
  PUT /api/settings/llm   {baseUrl, apiKey, model}

配置存 db settings 表(key='llm');apiKey 用 security.encrypt_secret 加密,**绝不回显**。
"""
from fastapi import APIRouter, Depends

from ..core import deps
from ..core import security as sec
from ..db import database as db
from ..schemas.pipeline import LLMSettingsIn
from ..services import llm

router = APIRouter(prefix="/api", tags=["settings"])

_SETTING_KEY = "llm"


def _view():
    cfg = llm.get_llm_config()
    return {"baseUrl": cfg.get("baseUrl", ""),
            "model": cfg.get("model", ""),
            "hasKey": bool(cfg.get("apiKey"))}


def _ok(data=None, message=""):
    return {"ok": True, "data": data if data is not None else {}, "message": message}


@router.get("/settings/llm")
def get_llm(user=Depends(deps.require_admin)):
    return _ok(_view())


@router.put("/settings/llm")
def put_llm(body: LLMSettingsIn, user=Depends(deps.require_admin)):
    cur = db.get_setting(_SETTING_KEY) or {}
    api_key = cur.get("apiKey", "")
    if body.apiKey:
        api_key = sec.encrypt_secret(body.apiKey)
    db.put_setting(_SETTING_KEY, {
        "baseUrl": (body.baseUrl or "").strip(),
        "model": (body.model or "").strip(),
        "apiKey": api_key,
    })
    return _ok(_view())
