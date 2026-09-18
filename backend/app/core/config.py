# -*- coding: utf-8 -*-
"""运行时配置(仅运维用环境变量;普通用户不接触配置文件)。"""
import os

# config.py 位于 backend/app/core/,向上三层 = backend/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT_DIR = os.path.dirname(BASE_DIR)                                     # 仓库根
# 运行数据目录(代码与数据分离):默认 <root>/data,可用 H3F_DATA_DIR 覆盖。
# 仓库内只保留代码;DB/上传件/密钥/项目工作区/知识库产物都在这里。
DATA_DIR = os.environ.get("H3F_DATA_DIR") or os.path.join(ROOT_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "h3factory.db")
SECRET_FILE = os.path.join(DATA_DIR, "secret.key")
PROJECTS_DIR = os.path.join(DATA_DIR, "projects")
KNOWLEDGE_DIR = os.path.join(DATA_DIR, "knowledge")

COOKIE_NAME = os.environ.get("H3F_COOKIE_NAME", "h3_session")
TOKEN_TTL = int(os.environ.get("H3F_TOKEN_TTL", 7 * 24 * 3600))
COOKIE_SECURE = os.environ.get("H3F_COOKIE_SECURE", "").lower() in ("1", "true", "yes")
COOKIE_SAMESITE = os.environ.get("H3F_COOKIE_SAMESITE", "lax")

ADMIN_EMAIL = os.environ.get("H3F_ADMIN_EMAIL", "admin@local")
# 仅在显式设置 H3F_ADMIN_PASSWORD 时,startup 才自动创建管理员;否则保持 0 用户,
# 由前端登录页调用 POST /api/auth/bootstrap 完成首次初始化。不再有硬编码弱口令默认值。
ADMIN_PASSWORD = os.environ.get("H3F_ADMIN_PASSWORD", "")

DEFAULT_BASE_URL = os.environ.get("H3F_H3_BASE_URL", "https://www.h3yun.com/")

_cors = os.environ.get("H3F_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
CORS_ORIGINS = [o.strip() for o in _cors.split(",") if o.strip()]

NIGHTLY_HOUR = int(os.environ.get("H3F_NIGHTLY_HOUR", 2))
NIGHTLY_MIN = int(os.environ.get("H3F_NIGHTLY_MIN", 0))

MAX_UPLOAD_MB = int(os.environ.get("H3F_MAX_UPLOAD_MB", 30))
