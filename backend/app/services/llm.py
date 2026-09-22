# -*- coding: utf-8 -*-
"""AI Provider 抽象。

配置优先级:DB settings(key='llm') → 环境变量 H3AC_LLM_* → 无(启发式)。
所有产出交由引擎清洗/校验(见 services/plan|flowchart|design)。
"""
import json
import os
import re

from ..db import database as db
from ..core import security as sec

_SETTING_KEY = "llm"


def get_llm_config() -> dict:
    """→ {baseUrl, apiKey, model, source}"""
    cfg = db.get_setting(_SETTING_KEY) or {}
    base = (cfg.get("baseUrl") or "").strip()
    model = (cfg.get("model") or "").strip()
    key_enc = cfg.get("apiKey", "")
    api_key = sec.decrypt_secret(key_enc) if key_enc else ""
    source = "db"
    if not (base and api_key and model):
        base = os.environ.get("H3AC_LLM_BASE_URL", "").strip()
        api_key = os.environ.get("H3AC_LLM_API_KEY", "").strip()
        model = os.environ.get("H3AC_LLM_MODEL", "").strip()
        source = "env"
    return {"baseUrl": base, "apiKey": api_key, "model": model, "source": source}


class Provider:
    name = "heuristic"
    available = False

    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        raise RuntimeError("LLM 未配置")


class LLMProvider(Provider):
    name = "llm"
    available = True

    def __init__(self, base_url, api_key, model, timeout=180):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        import httpx
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.2,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": "Bearer " + self.api_key,
                   "Content-Type": "application/json"}
        with httpx.Client(timeout=self.timeout) as cli:
            r = cli.post(self.base_url + "/chat/completions", json=body, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError("LLM HTTP %d: %s" % (r.status_code, r.text[:300]))
        data = r.json()
        try:
            return data["choices"][0]["message"]["content"]
        except Exception:
            raise RuntimeError("LLM 响应结构异常: %s" % json.dumps(data)[:300])

    def complete_vision(self, system: str, user: str, image_data_url: str,
                        timeout: int = None) -> str:
        """多模态识别(OpenAI 兼容 image_url)。模型不支持视觉时由调用方兜底。"""
        import httpx
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ]},
            ],
            "temperature": 0.1,
        }
        headers = {"Authorization": "Bearer " + self.api_key,
                   "Content-Type": "application/json"}
        with httpx.Client(timeout=timeout or self.timeout) as cli:
            r = cli.post(self.base_url + "/chat/completions", json=body, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError("LLM(视觉) HTTP %d: %s" % (r.status_code, r.text[:300]))
        data = r.json()
        try:
            return data["choices"][0]["message"]["content"]
        except Exception:
            raise RuntimeError("LLM(视觉)响应结构异常: %s" % json.dumps(data)[:300])


def get_provider() -> Provider:
    cfg = get_llm_config()
    if cfg["baseUrl"] and cfg["apiKey"] and cfg["model"]:
        return LLMProvider(cfg["baseUrl"], cfg["apiKey"], cfg["model"])
    return Provider()


def extract_json(text: str) -> dict:
    """从 LLM 输出抠出 JSON 对象(容忍 ```json 包裹/前后说明)。"""
    if not text:
        raise ValueError("空输出")
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    else:
        i, j = text.find("{"), text.rfind("}")
        if i >= 0 and j > i:
            text = text[i:j + 1]
    return json.loads(text)
