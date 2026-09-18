# -*- coding: utf-8 -*-
from typing import Optional

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=48,
                      description="项目标识(slug,目录名):字母数字下划线")
    title: str = Field(..., min_length=1, max_length=120, description="项目名称")
    engineCode: str = Field(..., min_length=1, max_length=64,
                            description="氚云引擎编码(目标应用后台获取,必填)")
    appCode: str = Field("", max_length=64, description="氚云应用编码(可后填)")
    h3Token: str = Field("", max_length=4096, description="氚云 h3_token(JWT)")


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    engineCode: Optional[str] = None
    appCode: Optional[str] = None
    h3Token: Optional[str] = None


class MemberIn(BaseModel):
    userId: int
    role: str = "viewer"
