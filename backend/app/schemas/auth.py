# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=128)
    password: str = Field(..., min_length=1, max_length=128)


class BootstrapIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=128)
    password: str = Field(..., min_length=6, max_length=128)
    displayName: str = ""


class PasswordIn(BaseModel):
    oldPassword: str
    newPassword: str = Field(..., min_length=6, max_length=128)


class SetInitialPasswordIn(BaseModel):
    """首次登录设置密码(账号已由管理员创建、尚未设置密码)。"""
    email: str = Field(..., min_length=3, max_length=128)
    code: str = Field(..., min_length=4, max_length=128)
    password: str = Field(..., min_length=6, max_length=128)


class ProfileIn(BaseModel):
    displayName: str = Field(..., min_length=1, max_length=64)
