# -*- coding: utf-8 -*-
"""API 路由聚合。"""
from . import (auth, users, projects, documents, pipeline, deploy, settings, system)  # noqa: F401


def include_routers(app):
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(projects.router)
    app.include_router(documents.router)
    app.include_router(pipeline.router)
    app.include_router(deploy.router)
    app.include_router(settings.router)
