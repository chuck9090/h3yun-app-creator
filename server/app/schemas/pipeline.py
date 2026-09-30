# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RequirementIn(BaseModel):
    html: str = ""
    text: str = ""


class PlanIn(BaseModel):
    markdown: str = ""


class FlowchartIn(BaseModel):
    mermaid: str = ""


class DesignIn(BaseModel):
    sheets: List[Dict[str, Any]] = []
    dicts: Dict[str, Any] = {}
    groups: List[Any] = []
    automations: List[Dict[str, Any]] = []


class PreviewIn(BaseModel):
    sheet: str


class DeployIn(BaseModel):
    force: bool = False


class GenerateIn(BaseModel):
    """空体即可;预留参数(如重新生成时覆盖的提示)。"""
    instruction: Optional[str] = None


class LLMSettingsIn(BaseModel):
    baseUrl: str = ""
    apiKey: str = ""
    model: str = ""


class RefDocsIn(BaseModel):
    """项目选择参考的全局资料库资料 id 列表。"""
    ids: List[int] = []


class LibraryItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""


class LibraryItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
