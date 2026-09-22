# -*- coding: utf-8 -*-
"""运行时配置(仅运维用环境变量;普通用户不接触配置文件)。"""
import os

# config.py 位于 backend/app/core/,向上三层 = backend/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT_DIR = os.path.dirname(BASE_DIR)                                     # 仓库根
# 运行数据目录(代码与数据分离):默认 <root>/data,可用 H3AC_DATA_DIR 覆盖。
# 仓库内只保留代码;DB/上传件/密钥/项目工作区/知识库产物都在这里。
DATA_DIR = os.environ.get("H3AC_DATA_DIR") or os.path.join(ROOT_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
AVATAR_DIR = os.path.join(DATA_DIR, "avatars")
DB_PATH = os.path.join(DATA_DIR, "h3yun-app-creator.db")
SECRET_FILE = os.path.join(DATA_DIR, "secret.key")
PROJECTS_DIR = os.path.join(DATA_DIR, "projects")
KNOWLEDGE_DIR = os.path.join(DATA_DIR, "knowledge")
# 全局资料库(所有用户共享):上传原件落这里,夜间编译成 knowledge/library.md
LIBRARY_DIR = os.path.join(DATA_DIR, "library")
LIBRARY_UPLOAD_DIR = os.path.join(LIBRARY_DIR, "uploads")

COOKIE_NAME = os.environ.get("H3AC_COOKIE_NAME", "h3_session")
TOKEN_TTL = int(os.environ.get("H3AC_TOKEN_TTL", 7 * 24 * 3600))
COOKIE_SECURE = os.environ.get("H3AC_COOKIE_SECURE", "").lower() in ("1", "true", "yes")
COOKIE_SAMESITE = os.environ.get("H3AC_COOKIE_SAMESITE", "lax")

ADMIN_EMAIL = os.environ.get("H3AC_ADMIN_EMAIL", "admin@local")
# 仅在显式设置 H3AC_ADMIN_PASSWORD 时,startup 才自动创建管理员;否则保持 0 用户,
# 由前端登录页调用 POST /api/auth/bootstrap 完成首次初始化。不再有硬编码弱口令默认值。
ADMIN_PASSWORD = os.environ.get("H3AC_ADMIN_PASSWORD", "")

DEFAULT_BASE_URL = os.environ.get("H3AC_H3_BASE_URL", "https://www.h3yun.com/")

_cors = os.environ.get("H3AC_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
CORS_ORIGINS = [o.strip() for o in _cors.split(",") if o.strip()]

NIGHTLY_HOUR = int(os.environ.get("H3AC_NIGHTLY_HOUR", 2))
NIGHTLY_MIN = int(os.environ.get("H3AC_NIGHTLY_MIN", 0))

MAX_UPLOAD_MB = int(os.environ.get("H3AC_MAX_UPLOAD_MB", 30))

# 首次激活码有效期(天):管理员建号后生成的「一次性激活码」超过该天数即失效
ACTIVATION_TTL_DAYS = int(os.environ.get("H3AC_ACTIVATION_TTL_DAYS", 7))

# 后台任务看门狗:running 任务超过该分钟数未刷新进度即视为卡死,自动标记失败并允许重试
JOB_TIMEOUT_MIN = int(os.environ.get("H3AC_JOB_TIMEOUT_MIN", 30))
# 启动时是否把残留 running 任务标记失败(单进程部署保持 1;多 worker 部署须设 0,否则会误杀在跑任务)
FAIL_ORPHAN_JOBS = os.environ.get("H3AC_FAIL_ORPHAN_JOBS", "1").lower() not in ("0", "false", "no")

# ---- AI 上下文预算(参考资料如何喂给模型) ----
# 单次生成可用的参考资料 token 预算;超出即按"表格/字段优先"截断。
CTX_TOKEN_BUDGET = int(os.environ.get("H3AC_CTX_TOKEN_BUDGET", 120000))
# 参考资料总量超过该阈值时,切换为"目录 + 由模型按需取文件"(agent 式)模式。
# 须 >= CTX_TOKEN_BUDGET,否则运行时按预算处理(不会进入 truncated 档)。
CTX_CATALOG_THRESHOLD = int(os.environ.get("H3AC_CTX_CATALOG_THRESHOLD", 1000000))
# 目录模式下模型单次最多可索取的文件数,以及最多索取轮数。
CTX_MAX_SELECT_FILES = int(os.environ.get("H3AC_CTX_MAX_SELECT_FILES", 12))
CTX_MAX_SELECT_ROUNDS = int(os.environ.get("H3AC_CTX_MAX_SELECT_ROUNDS", 2))
# 单个文件在紧凑渲染里保留的数据行样例上限(字段清单不受此限,永远保留)。
CTX_SAMPLE_ROWS = int(os.environ.get("H3AC_CTX_SAMPLE_ROWS", 8))
# 需求/清单类表格保留的行数上限:这类表的**每一行都是需求项**(如「功能清单」「模块与功能」),
# 不能只取样例。列数 ≤ CTX_LIST_MAX_COLS 的表视为清单表,连同「需求清单」类文件一并放宽到该上限。
CTX_MAX_LIST_ROWS = int(os.environ.get("H3AC_CTX_MAX_LIST_ROWS", 200))
CTX_LIST_MAX_COLS = int(os.environ.get("H3AC_CTX_LIST_MAX_COLS", 6))

# ---- 内嵌图片识别(Excel/Word/PDF 里的截图、扫描件) ----
# 单个文件最多识别多少张内嵌图片;0 = 不识别图片。
IMG_MAX_PER_FILE = int(os.environ.get("H3AC_IMG_MAX_PER_FILE", 6))
# 扫描件 PDF:正文少于该字符数即视为"无文字层",改用整页渲染识别。
PDF_OCR_MIN_CHARS = int(os.environ.get("H3AC_PDF_OCR_MIN_CHARS", 40))
# 扫描件 PDF 最多渲染识别的页数。
PDF_OCR_MAX_PAGES = int(os.environ.get("H3AC_PDF_OCR_MAX_PAGES", 8))
# 单张图片入模上限(MB),超过则跳过并说明。
IMG_MAX_MB = int(os.environ.get("H3AC_IMG_MAX_MB", 4))
