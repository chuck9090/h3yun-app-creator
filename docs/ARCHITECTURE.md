# h3factory 架构与接口契约(v2)

> 前后端分离 + 工程化。本文件是**后端 / 前端 / 引擎三方的接口契约**。
> 改接口先改本文件。

## 0. 总览

```
┌─ frontend/  独立前端工程(React + TypeScript + Vite + AntD)
│    浏览器 → 用户操作:登录/建项目/传需求/看方案/流程图/ER编辑/生成应用
│    只通过 HTTP API 与后端通信(带 Cookie 会话);不依赖任何配置文件的填写
├─ backend/   独立后端工程(FastAPI)
│    认证(邮件+Cookie) · 项目 · 文档 · AI 流水线 · 部署编排(调用引擎)
├─ 引擎(根目录)  h3design / h3platform / h3verify / h3service
│    确定性能力:定义校验 · 建表(SaveForm) · 回读核对 · ER 图 · 载荷预览 · 知识库
└─ data/  运行数据目录(代码与数据分离,gitignore;`H3F_DATA_DIR` 可覆盖)
      ├─ h3factory.db / secret.key / uploads/
      ├─ projects/<slug>/  项目工作区(定义/方案/流程图/ER/需求)
      └─ knowledge/        设计知识库产物
```

**代码与数据分离**:仓库内**只有代码**(无任何内置样本/凭据);
DB/上传件/密钥/项目工作区/知识库产物/凭据都在 `data/`。

**前后端完全分离**:两个独立目录、独立依赖、独立启动;后端**不托管前端静态资源**。
开发期:`localhost:5173`(前端) ↔ `localhost:8000`(后端),同 host 不同端口 → Cookie 天然共享。
生产期:用反向代理(nginx)把二者置于同一源(或同域不同路径)。

## 1. 用户操作流程(对应实现)

| # | 用户动作 | 前端 | 后端 |
|---|---|---|---|
| 1 | 打开网址 | 调 `GET /api/auth/me`;401 → 跳登录页 | Cookie 会话校验 |
| 2 | 邮件+密码登录 | 登录页 | `POST /api/auth/login` 下发 httpOnly Cookie |
| 3 | 看到自己的/被授权的项目 | 项目列表 | `GET /api/projects`(owner 或 member) |
| 4 | 新建项目:项目名称 / 应用编码 / 引擎编码 / h3_token | 新建弹窗 | `POST /api/projects`(engineCode 用户填/由 token 预填) |
| 5 | 上传文件(拖拽)+ 富文本需求 | 需求步骤页 | 文档解析 + 需求保存 |
| 6 | 点「生成方案」→ 系统设计方案(HTML 展示,底层 md) | 方案页 | `POST .../plan/generate` |
| 7 | 打开方案编辑页改 markdown | md 编辑器 | `PUT .../plan` |
| 8 | 点「生成业务流程图」 | 流程图页(Mermaid) | `POST .../flowchart/generate` |
| 9 | 不满意→改方案→重生成流程图(循环) | 同上 | 同上 |
| 10 | 点「生成 ER 图」 | ER 页(React Flow + 结构化编辑器) | `POST .../design/generate` |
| 11 | 改表名/加表/改字段名/控件类型/加字段 | ER 编辑器 | `PUT .../design` |
| 12 | 点「生成氚云应用」 | 部署页 | `POST .../deploy`(写 sheets JSON → 引擎建表) |

**状态机**:`draft → planned → flowcharted → designed → deployed`(失败 → `failed`)。

## 2. 技术选型(开源工具评估结论)

| 能力 | 选型 | 理由 |
|---|---|---|
| 业务流程图 | **Mermaid**(`mermaid` ^12) | LLM 最擅长的图语法(文本→图),前端零成本渲染,支持 flowchart/时序;可再导出 SVG。备选 grafana?不需要。 |
| ER 图渲染+编辑 | **React Flow**(`@xyflow/react` ^12)+ 结构化编辑器 | ER 需**可编辑**(改表名/加表/改字段/控件类型),纯渲染工具(Mermaid/dbdiagram)做不到;React Flow 交互成熟 |
| ER/流程图静态导出 | Mermaid(`erDiagram`) | 便于复制/归档,AI 也能直接产出 |
| Markdown 渲染 | `react-markdown` + `remark-gfm` | 标准、安全 |
| Markdown 编辑 | `@uiw/react-md-editor` | 开箱即用、支持预览 |
| 富文本需求 | `react-quill` | 成熟富文本 |
| 前端框架 | React 18 + TS + Vite + AntD 5 | 工程化、类型安全 |
| 后端 | FastAPI + 原生 sqlite3 仓储 | 无额外 ORM 依赖,稳定;Pydantic 校验 |
| 会话 | httpOnly Cookie + 自签 JWT | 比 localStorage 安全;前后端分离下同 host 共享 |

## 3. 数据模型(SQLite,`data/h3factory.db`)

```
users          id, email(唯一,登录名), password_hash, display_name, role(admin|designer|viewer),
               active, token_version(会话失效), created_at, updated_at
projects       id, slug(目录名,唯一), title, app_code, engine_code(用户填写), h3_token(加密存储),
               status, owner_id, created_at, updated_at
project_members project_id, user_id, role(viewer|designer), created_at   (联合主键)
documents      id, project_id, kind(existing_system|requirement|meeting|other), filename,
               stored_path, ext, size, parsed_text, summary, tags, status, uploaded_by, created_at
settings       key, value(JSON字符串)         # LLM 配置等(避免让用户编辑配置文件)
jobs           id, kind, status, detail, created_at, updated_at
events         id, project_id, kind, message, created_at
```

**凭据**:`projects.h3_token` 用服务端密钥(AES 或派生密钥 XOR+HMAC)加密存储,接口**绝不回显**。
`engineCode` 由**用户在建/改项目时填写**(`projects.engine_code`;前端粘贴 h3_token 会自动带出)。
`appCode` 可后填。`baseUrl` 默认 `https://www.h3yun.com/`。

## 4. 项目工作区(文件,`data/projects/<slug>/`)

```
plan.md             系统设计方案(markdown,AI 生成/用户编辑)
flowchart.mmd       业务流程图(mermaid 源码)
design.json         ER 结构({sheets,dicts,groups,automations}) —— 用户编辑后的权威结构
requirement.json    需求富文本(HTML)
uploads/            原始上传文件
sheets/*.json       部署时由 design.json 生成(引擎消费)
automations/*.json  部署时由 design.json.automations 生成(引擎消费,一条一文件,文件名=key)
registry.json       引擎建表编码注册表
```

### 4.1 自动化定义(design.json.automations[])

元素遵循 `docs/schema_doc.md` 的「自动化」DSL,字段:
`{ key(文件名,必填,同表单 key 命名规则), title, form(触发表单 key), trigger(生效|失效|生效或更新), sortKey?, names?, when?, actions[] }`。
`actions[]` 元素:`{ do(新增|更新|删除), target(目标表单 key), state?, isInsert?, match?, set?, owner?, sub? }`。
**引用规则**:字段引用为**表单内字段编码**;`form`/`target` 为表 key。清洗时会做 key 规范化后的引用重映射(尽力)。

## 5. API 契约(`/api`,除标注外均需登录)

统一响应:`{ "ok": bool, "data": any, "message": str }`;错误:`HTTP 4xx/5xx + {ok:false,message}`。

### 认证(公开)
```
POST /api/auth/bootstrap   {email,password,displayName}   # 仅当系统无用户
POST /api/auth/login       {email,password}               # 下发 httpOnly Cookie
POST /api/auth/logout
GET  /api/auth/me                                         # 未登录 401
POST /api/auth/password    {oldPassword,newPassword}
```

### 用户(admin)
```
GET    /api/users
POST   /api/users          {email,password,displayName,role}
PATCH  /api/users/{id}     {displayName?,role?,active?,password?}
DELETE /api/users/{id}
```

### 项目
```
GET    /api/projects                              # 拥有或被授权
POST   /api/projects       {name,title,appCode,h3Token}
GET    /api/projects/{id}
PATCH  /api/projects/{id}  {title?,appCode?,h3Token?}
DELETE /api/projects/{id}
GET    /api/projects/{id}/members
POST   /api/projects/{id}/members   {userId,role}
DELETE /api/projects/{id}/members/{userId}
```

### 文档
```
POST   /api/projects/{id}/documents   multipart: file, kind
GET    /api/projects/{id}/documents
GET    /api/documents/{docId}
DELETE /api/documents/{docId}
```

### 需求 / 方案 / 流程图 / ER / 部署
```
GET/PUT  /api/projects/{id}/requirement            {html,text}
GET      /api/projects/{id}/plan                    {markdown}
POST     /api/projects/{id}/plan/generate           → data:{markdown, provider}
PUT      /api/projects/{id}/plan                    {markdown}
GET      /api/projects/{id}/flowchart               {mermaid}
POST     /api/projects/{id}/flowchart/generate      → data:{mermaid, provider}
PUT      /api/projects/{id}/flowchart               {mermaid}
GET      /api/projects/{id}/design                  data:{sheets,dicts,groups,automations}
POST     /api/projects/{id}/design/generate         → data:{sheets,dicts,groups,automations,provider,check,error}
PUT      /api/projects/{id}/design                  {sheets,dicts,groups,automations}
                                                    → data:{design:{...},check,error}
GET      /api/projects/{id}/design/check            → data:<check 结果>{project,sheets,warnings,error}
GET      /api/projects/{id}/design/er               → data:{nodes,edges}
POST     /api/projects/{id}/deploy                  body:{force?:bool}
                                                    → data:{project,sheets:[{key,created,code,err,...}],
                                                            groups:[{group,code,created,detail}],
                                                            moved:[{table,group,ok,detail}],
                                                            automations:[{key,created,objectId,err,...}],all_ok}
POST     /api/projects/{id}/verify                  → data:{project,sheets,all_ok}
GET      /api/projects/{id}/credentials/status      → data:{configured,appCode,hasToken,tokenValid,tokenExpired,engineCode}
POST     /api/projects/{id}/preview                 {sheet} → data:{payload:{SchemaStr,BizSheetStr,ControlSettingsStr}}
```

**统一信封**:所有 `/api/*`(含 `/api/health`)均返回 `{ok, data, message}`;**前端 `unwrap()` 取 `data`**。
`error` 字段为引擎校验错误文本(空串=通过);校验失败也保存(便于继续编辑),由前端提示。
`deploy` 的 `force` 为**请求体布尔字段**(非 query),会整表重存并抹掉界面手工配置,仅限 owner/admin,需二次确认。

### 系统 / 设置 / 知识库
```
GET  /api/health                                    data:{ok,provider,llm,needsBootstrap,knowledge,version}
GET  /api/settings/llm        (admin)               data:{baseUrl,model,hasKey}
PUT  /api/settings/llm        (admin)               {baseUrl,apiKey,model}
GET  /api/knowledge/summary   (登录用户,按可见项目过滤/或 admin)
POST /api/knowledge/refresh   (designer)
GET  /api/jobs                (登录用户)
```

**首次初始化**:仅当 `H3F_ADMIN_PASSWORD` 环境变量显式设置时才在启动时自动建管理员;
否则系统保持 0 用户,前端登录页据 `needsBootstrap` 显示「初始化管理员」表单(调 `/api/auth/bootstrap`)。
不再使用硬编码弱口令。

## 6. 前端路由

```
/login
/                       → 重定向 /projects
/projects               项目列表 + 新建
/projects/:id           工作台(步骤条):需求 → 方案 → 流程图 → ER设计 → 生成应用
/users                  (admin)
/settings               (admin, LLM)
```

## 7. AI Provider

- 配置来源:**DB settings 表**(管理员在「系统设置」页填写)→ 回退环境变量 `H3F_LLM_*` → 回退启发式。
- `provider.name`: `llm` | `heuristic`。
- 任何 AI 产出都**并经过引擎清洗/校验**(`h3service.design.clean_design` + `run_check`),失败回退启发式。

## 8. 环境变量(仅运维用,用户不接触)

| 变量 | 默认 | 说明 |
|---|---|---|
| `H3F_DATA_DIR` | `<仓库根>/data` | **运行数据目录**(DB/密钥/上传件/工作区/知识库产物);代码与数据分离 |
| `H3F_SECRET` | 自动生成 `data/secret.key` | Cookie/JWT/凭据加密密钥 |
| `H3F_ADMIN_EMAIL` / `H3F_ADMIN_PASSWORD` | 空(不自动建) | **设置后**才在启动时创建管理员;未设置则走前端「初始化管理员」 |
| `H3F_LLM_BASE_URL` / `H3F_LLM_API_KEY` / `H3F_LLM_MODEL` | 空 | LLM(可被 DB 设置覆盖) |
| `H3F_CORS_ORIGINS` | `http://localhost:5173` | 允许的前端源 |
| `H3F_COOKIE_SECURE` | 空(HTTP) | 生产 HTTPS 置 `1` |
| `H3F_NIGHTLY_HOUR` / `H3F_NIGHTLY_MIN` | `2` / `0` | 夜间知识库批处理 |
| `H3F_MAX_UPLOAD_MB` | `30` | 单文件上传上限 |

## 9. 接口现状与边界(重要)

- **认证通道**:全部氚云调用走**个人身份授权**(`Authorization: Bearer <h3_token>` + `EngineCode` 头)。
  **已不使用 OpenApi(EngineCode + EngineSecret)**;`engineSecret` 已从配置与代码中移除。
- **应用创建**:**本系统不自动创建氚云应用**。用户先在氚云后台创建应用,再把 `appCode` 填入项目
  (新建项目时可留空,生成应用前补填)。系统负责应用内的表单/自动化/分组。
- **业务数据接口:本方案不需要**。流程只完成"搭建应用结构"(表结构 + 自动化定义),
  不涉及表单记录(数据)的增删改查;因此不提供数据导入/导出/查询能力。
- **载荷基准**:氚云 UI 真实载荷样本在 `fixtures/`(生成逻辑逐字对照),见 `fixtures/README.md`。
