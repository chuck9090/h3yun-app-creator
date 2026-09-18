# 部署与运维(前后端分离)

> 接口契约见 `docs/ARCHITECTURE.md`。本文件讲**怎么跑**。

## 1. 开发/内网单机(最快)

```powershell
pwsh -File start.ps1                 # 后端 8000 + 前端 5173,自动装依赖
```

访问 <http://localhost:5173>。**首次使用**:系统无用户时,登录页显示「初始化管理员」,
由你设定邮箱+密码(无默认弱口令)。若要在启动时自动建管理员,先设置
`H3F_ADMIN_EMAIL` / `H3F_ADMIN_PASSWORD`。

只启动单个:

```powershell
pwsh -File start.ps1 -BackendOnly
pwsh -File start.ps1 -FrontendOnly
```

## 2. 手工分别启动

```powershell
# 后端(工作目录 backend/)
python -X utf8 -m pip install -r requirements.txt
python -X utf8 -m uvicorn app.main:app --host localhost --port 8000 --reload

# 前端(工作目录 frontend/)
npm install
npm run dev            # http://localhost:5173,/api 代理到 8000
```

## 3. 生产部署(静态 + 反向代理)

```powershell
pwsh -File start.ps1 -Prod          # 构建前端 frontend/dist
# 后端以多 worker 运行(去掉 --reload):
cd backend; python -X utf8 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

nginx 参考(同源,保证 Cookie 携带):

```nginx
server {
    listen 80;
    server_name h3factory.example.com;

    location / {                       # 前端静态产物
        root /opt/h3factory/frontend/dist;
        try_files $uri $uri/ /index.html;   # HashRouter 其实不需要,但无害
    }
    location /api/ {                   # 反代后端
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 4. 用户视角的操作流程(无需碰任何配置文件)

1. 打开网址 → 未登录跳登录页 → 邮件+密码登录;
2. 项目列表(自己的 + 别人授权给你的);
3. 「新建项目」:填**项目名称 / 项目标识 / 引擎编码(engineCode) / h3_token**;应用编码(appCode)可后填;
   粘贴 h3_token 会自动带出 engineCode(仍可修改);
4. 工作台「需求」:拖拽上传已有系统文档 / 需求 / 会议记录,或富文本补充;
5. 「生成方案」→ HTML 展示系统设计方案(底层 markdown);可进编辑页改;
6. 「生成业务流程图」(Mermaid);不满意→回改方案→重生成;
7. 「生成 ER 图」→ 可视化表图谱;可改表名/加表/改字段/控件类型/加字段;
   并可编辑**自动化(触发器)**:某表数据生效/失效/更新时自动增删改别的表(条件、动作、字段映射、写子表);
8. 「生成氚云应用」→ 据 ER 结构生成 `sheets/*.json` + `automations/*.json` 并写入氚云(**先建表 → 按分组归入应用菜单 → 后建触发器**);可回读核对。

## 5. 环境变量(仅运维)

| 变量 | 默认 | 说明 |
|---|---|---|
| `H3F_DATA_DIR` | `<仓库根>/data` | **运行数据目录**(DB/密钥/上传件/工作区/知识库产物) |
| `H3F_SECRET` | 自动生成 `data/secret.key` | 会话 JWT 与凭据加密密钥 |
| `H3F_ADMIN_EMAIL` / `H3F_ADMIN_PASSWORD` | 空(不自动建) | **设置后**才在启动时创建管理员;未设置则走前端「初始化管理员」 |
| `H3F_CORS_ORIGINS` | `http://localhost:5173` | 允许的前端源(逗号分隔) |
| `H3F_COOKIE_SECURE` | 空(HTTP) | 生产 HTTPS 置 `1` |
| `H3F_LLM_BASE_URL` / `H3F_LLM_API_KEY` / `H3F_LLM_MODEL` | 空 | LLM 回退配置;管理员也可在「系统设置」页填写(优先) |
| `H3F_NIGHTLY_HOUR` / `H3F_NIGHTLY_MIN` | `2` / `0` | 每晚知识库批处理 |
| `H3F_MAX_UPLOAD_MB` | `30` | 单文件上限 |

## 6. 数据与备份(代码与数据分离)

**仓库内只有代码**;所有运行数据在 `data/`(默认 `<仓库根>/data`,可用 `H3F_DATA_DIR` 覆盖):

| 路径 | 内容 |
|---|---|
| `data/h3factory.db` | 用户/项目/文档索引/设置/任务(元数据) |
| `data/uploads/` | 上传原件 |
| `data/secret.key` | 服务端密钥(**必须备份,丢失则凭据无法解密**) |
| `data/projects/<slug>/` | 项目工作区:plan.md / flowchart.mmd / design.json / requirement.* / sheets/*.json / automations/*.json |
| `data/knowledge/` | 设计知识库产物(corpus.*/patterns.md) |

备份 = 整个 `data/` 目录。

## 7. 测试

```powershell
# 后端(cwd=backend/)
python -X utf8 tests/test_core_api.py        # 认证/用户/项目/文档 49 项
python -X utf8 tests/test_pipeline_api.py    # 需求→方案→流程图→ER→部署 20 项
python -X utf8 tests/test_automations.py     # 自动化全链路 + 分组计划 + 设计清洗安全 19 项
python -X utf8 tests/test_security.py        # 会话/权限/上传/凭据安全 33 项
python -X utf8 tests/smoke_real_server.py    # 真实端口 + Cookie 冒烟 16 项

# 前端(cwd=frontend/)
npm run typecheck
npm run build:only
```

## 8. 说明:AI 参考资料来源

- **AI 出方案/表单结构的参考资料** = ①用户在本项目上传的文档(已有系统/需求/会议等,直接作为
  模型上下文)+ ②本部署已建项目的语料(`data/knowledge/`,`engine_bridge.refresh_knowledge` 编译)。
  **不含任何内置样本。**
- `h3design/h3platform/h3verify/h3service` 是**确定性引擎**,Web 后端直接复用。
- 凭据由用户在新建项目时提供、加密存库,且**绝不回落到运行目录配置**(避免误建到别的应用);
  仓库内不存在任何凭据文件。
