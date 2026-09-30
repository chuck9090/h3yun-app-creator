# -*- coding: utf-8 -*-
from typing import Any, Optional

from pydantic import BaseModel


class ApiResult(BaseModel):
    ok: bool = True
    message: str = ""
    data: Optional[Any] = None
