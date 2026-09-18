# -*- coding: utf-8 -*-
"""h3service —— 引擎 service 层。

把确定性能力(定义校验/建表/自动化/回读核对/ER 图/载荷预览/知识库)抽成
**无 IO 输出、可复用**的接口,返回结构化结果或抛异常。

- 供 Web 后端(FastAPI)与其他程序调用;不依赖 CLI。
- 完全沿用 `data/projects/<名>/` 目录结构。
- 一个 Web 项目 == 一个 `data/projects/<名>/` 目录。
"""
