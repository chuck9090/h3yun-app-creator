# h3yun-app-creator 架构与接口契约(v2)

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
└─ data/  运行数据目录(代码与数据分离,gitignore;`H3AC_DATA_DIR` 可覆盖)
      ├─ h3yun-app-creator.db / secret.key / uploads/ / avatars/
      ├─ projects/<slug>/  项目工作区(定义/方案/流程图/ER/需求)
      ├─ library/uploads/  全局资料库上传件(全用户共享,夜间整理)
      └─ knowledge/        设计知识库产物(corpus.* / patterns.md / library.md)
```

**代码与数据分离**:仓库内**只有代码**(无任何内置样本/凭据);
DB/上传件/密钥/项目工作区/知识库产物/凭据都在 `data/`。

**前后端完全分离**:两个独立目录、独立依赖、独立启动;后端**不托管前端静态资源**。
开发期:`localhost:8991`(前端) ↔ `localhost:8990`(后端),同 host 不同端口 → Cookie 天然共享
(端口可由 `start.ps1` 的 `-BackendPort` / `-FrontendPort` 调整;前端 `/api` 代理目标取自
`H3AC_BACKEND_PORT`,由启动脚本自动传递)。
生产期:用反向代理(nginx)把二者置于同一源(或同域不同路径)。

## 1. 用户操作流程(对应实现)

| # | 用户动作 | 前端 | 后端 |
|---|---|---|---|
| 1 | 打开网址 | 调 `GET /api/auth/me`;401 → 跳登录页 | Cookie 会话校验 |
| 2 | 邮件+密码登录 | 登录页 | `POST /api/auth/login` 下发 httpOnly Cookie |
| 3 | 看到自己的/被授权的项目 | 项目列表 | `GET /api/projects`(owner 或 member) |
| 4 | 新建项目:项目名称 / 应用编码 / 引擎编码 / h3_token | 新建弹窗 | `POST /api/projects`(engineCode 用户填/由 token 预填) |
| 5 | 上传资料(需求清单/会议纪要/其他)+ 富文本补充 | 需求步骤页 | 文档解析 + 需求保存(需求清单限一份,重复 409) |
| 6 | 点「生成方案」→ 系统设计方案(**客户可交付格式**:标题1=模块/标题2=表单/编号业务内容,不含 key 与界面配置) | 方案页 | `POST .../plan/generate` |
| 7 | 打开方案编辑页改 markdown | md 编辑器 | `PUT .../plan` |
| 8 | 点「生成业务流程图」 | 流程图页(Mermaid) | `POST .../flowchart/generate` |
| 9 | 不满意→改方案→重生成流程图(循环) | 同上 | 同上 |
| 10 | 点「生成 ER 图」 | ER 页(React Flow + 结构化编辑器) | `POST .../design/generate` |
| 11 | 改表名/加表/改字段名/控件类型/加字段 | ER 编辑器 | `PUT .../design` |
| 12 | 点「生成氚云应用」 | 部署页 | `POST .../deploy`(写 sheets JSON → 引擎建表) |

**状态机**:`draft → planned → flowcharted → designed → deployed`(失败 → `failed`)。

**资料库(全局共享)**:任何登录用户可在左侧「资料库」**新建「资料」(名称唯一 + 描述)**,再在其下上传已有系统文档;
夜间批处理 (`nightly_learn`) 用 LLM 把该资料下的文档整理成《已有系统梳理》(写入 `library_items.analysis`),
并编译进 `data/knowledge/library.md`,供**所有项目**生成方案/ER 时按**资料名称**勾选参考(`projects.ref_items`)。

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

## 3. 数据模型(SQLite,`data/h3yun-app-creator.db`)

```
users          id, email(唯一,登录名), password_hash(可为空=未设密码), display_name, avatar,
               activation_token(激活码哈希,空=无待激活), activation_expires(激活码过期 epoch),
               role(admin|designer|viewer), active, token_version(会话失效), created_at, updated_at
projects       id, slug(系统生成的序列号 proj_0001…,唯一,即目录名), title,
               app_code, engine_code(用户填写), h3_token(加密存储),
               status(已达成阶段: draft|planned|flowcharted|designed|deployed;见下), owner_id,
               ref_items(本项目勾选参考的全局资料 id 列表,JSON), created_at, updated_at
project_members project_id, user_id, role(viewer|designer), created_at   (联合主键)
documents      id, project_id, library_id, kind(existing_system|requirement|meeting|other), filename,
               stored_path, ext, size, parsed_text, summary, tags,
               extract_json(结构化抽取缓存)/extract_status/extract_at,
               status, uploaded_by, created_at
               # library_id 非空 = 资料库文档(先设 project_id 为空);否则为项目私有文档
library_items  id, name(唯一,全平台), description, analysis(AI 整理内容), analysis_at,
               analysis_error, created_by, created_at, updated_at
settings       key, value(JSON字符串)         # LLM 配置等(避免让用户编辑配置文件)
jobs           id, kind, title, variant(同 kind 内的参数区分,如 deploy: force/normal),
               project_id, user_id, status(running|done|failed),
               progress(JSON 进度明细[{ts,level,text,pct}]), result(JSON 结果), error, detail,
               created_at, updated_at
events         id, project_id, kind, message, created_at
```

**凭据**:`projects.h3_token` 用服务端密钥(AES 或派生密钥 XOR+HMAC)加密存储,接口**绝不回显**。
`engineCode` 由**用户在建/改项目时填写**(`projects.engine_code`;前端粘贴 h3_token 会自动带出)。
`appCode` 可后填。`baseUrl` 默认 `https://www.h3yun.com/`。

**项目状态**:`projects.status` 表示**已达成的最高阶段**,**只进不退**。生成应用失败时**不**把状态
降级(保留 `designed`),失败详情由任务 `jobs.error` 与 `events` 承载;因此部署失败后仍可重试,
工作台门禁不会把用户锁死。前端 `statusRank` 另对历史 `failed` 值兜底按 `designed` 处理。

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
POST /api/auth/bootstrap   {email,password}               # 仅当系统无用户(首个管理员)
POST /api/auth/login       {email,password}
                           # 正常:下发 httpOnly Cookie,data=用户;
                           # 账号已创建但未设密码:data={needPassword:true,email},前端引导设置
POST /api/auth/set-initial-password  {email,code,password}  # 首次设置密码:须凭管理员发的一次性激活码,成功后直接登录
POST /api/auth/logout
GET  /api/auth/me                                         # 未登录 401;返回含 avatar/hasPassword
PATCH /api/auth/profile    {displayName}                  # 用户改自己的显示名
POST /api/auth/avatar      multipart: file                # 上传自定义头像(png/jpg/jpeg/gif/webp/bmp,≤5MB)
POST /api/auth/password    {oldPassword,newPassword}
```

**首次登录(一次性激活码)**:管理员仅凭邮箱建号时,系统生成**一次性激活码**(存哈希 + 有效期
`H3AC_ACTIVATION_TTL_DAYS` 天,默认 7),创建响应里的 `data.activationCode` 仅返回这一次,由管理员线下
转交用户;用户凭「邮箱 + 激活码 + 新密码」完成激活。激活码一次性、可作废/重生成,因此**未认证者无法抢注账号**
(对照:无此机制的旧方案,任何人只要知道邮箱即可抢先设置密码)。密码一律 PBKDF2-SHA256 加盐哈希存储,不存明文、不可逆。
login 对未设密码账号返回 `needPassword`(不做密码校验,用于引导)。
头像存 `data/avatars/<uid>_<ts>.<ext>`,读取走 `GET /api/users/{uid}/avatar`(未设置返回 404,前端回退默认头像)。

### 用户(admin;目录/头像为登录用户可见)
```
GET    /api/users                                 # admin:全部用户(含 hasPassword/activationPending/avatar)
GET    /api/users/directory                       # 登录用户:精简清单(id/邮箱/显示名),供共享选择
GET    /api/users/{id}/avatar                     # 登录用户:头像文件(未设置 404)
POST   /api/users          {email,password?}      # admin:密码留空 → 初始无密码并返回一次性 activationCode;
                                                  #       给了 password 则直接可登录(无激活码)
POST   /api/users/{id}/activation                 # admin:为未设密码用户重新生成激活码(旧码立即失效)
PATCH  /api/users/{id}     {displayName?,role?,active?,password?}   # password 留空=不修改
DELETE /api/users/{id}
```

### 项目
```
GET    /api/projects                              # 拥有或被授权
POST   /api/projects       {title,engineCode,name?,appCode?,h3Token?}   # name(slug) 留空则系统生成 proj_0001…
GET    /api/projects/{id}
PATCH  /api/projects/{id}  {title?,engineCode?,appCode?,h3Token?}
DELETE /api/projects/{id}
GET    /api/projects/{id}/members
POST   /api/projects/{id}/members   {userId,role}     # 仅项目所有者或管理员;被共享者不能转授
DELETE /api/projects/{id}/members/{userId}            # 仅项目所有者或管理员
```

### 文档
```
POST   /api/projects/{id}/documents   multipart: file, kind
GET    /api/projects/{id}/documents
GET    /api/documents/{docId}
DELETE /api/documents/{docId}
```

### 资料库(全局共享;登录用户)
```
GET    /api/library/items                                    # 资料列表(名称/描述/文档数/整理状态)
POST   /api/library/items         {name,description}         # 新建资料(name 唯一,冲突 409)
GET    /api/library/items/{id}                               # 详情(描述 + 文档 + AI 整理内容 analysis)
PATCH  /api/library/items/{id}    {name?,description?}       # 创建者或 admin
DELETE /api/library/items/{id}                               # 创建者或 admin(级联删文档)
POST   /api/library/items/{id}/documents   multipart: file   # 上传文档到该资料(创建者或 admin)
DELETE /api/library/documents/{docId}                        # 删除资料库文档(创建者或 admin)
POST   /api/library/items/{id}/analyze                       # 手动触发整理(创建者或 designer+)
```
文档在夜间由 LLM 整理成《已有系统梳理》回填该资料(`analysis`),并编译进
`data/knowledge/library.md`,供所有项目生成方案/ER 时按资料名称勾选参考。

### 项目参考资料
```
GET /api/projects/{id}/ref-docs    → data:{ids:[...], library:[资料清单]}   # 本项目已选 + 可选清单
PUT /api/projects/{id}/ref-docs    {ids:[...]}                              # 项目写权限
```

### 需求 / 方案 / 流程图 / ER / 部署```
GET/PUT  /api/projects/{id}/requirement            {html,text}
GET      /api/projects/{id}/plan                    {markdown}
POST     /api/projects/{id}/plan/generate           → data:{job,created}   (异步任务,见下)
PUT      /api/projects/{id}/plan                    {markdown}
GET      /api/projects/{id}/flowchart               {mermaid}
POST     /api/projects/{id}/flowchart/generate      → data:{job,created}   (异步任务)
PUT      /api/projects/{id}/flowchart               {mermaid}
GET      /api/projects/{id}/design                  data:{sheets,dicts,groups,automations}
POST     /api/projects/{id}/design/generate         → data:{job,created}   (异步任务)
PUT      /api/projects/{id}/design                  {sheets,dicts,groups,automations}
                                                    → data:{design:{...},check,error}
GET      /api/projects/{id}/design/check            → data:<check 结果>{project,sheets,warnings,error}
GET      /api/projects/{id}/design/er               → data:{nodes,edges}
POST     /api/projects/{id}/deploy                  body:{force?:bool} → data:{job,created}  (异步任务)
POST     /api/projects/{id}/verify                  → data:{job,created}   (异步任务)
GET      /api/projects/{id}/credentials/status      → data:{configured,appCode,hasToken,tokenValid,tokenExpired,engineCode}
POST     /api/projects/{id}/preview                 {sheet} → data:{payload:{SchemaStr,BizSheetStr,ControlSettingsStr}}
```

#### 异步任务(生成 / 核对)
`plan|flowchart|design|deploy|verify` 均为**后台异步任务**,POST 立即返回 `{job, created}`:
- `job` 为任务快照;`created=false` 表示**同项目同 kind 且 variant 一致、已有运行中任务、已复用**
  (幂等,防重复点击/多端重复触发)。
- **variant** 用于区分同一 kind 内的不同参数:deploy 的普通部署=`normal`、强制重存=`force`。
  若已有运行中任务但 `variant` 不一致(如普通部署在跑又点强制重存),返回 **409**(`JobConflict`),
  **绝不静默顶替**高危操作语义。
- 真实产物在任务 `result` 里(如 design 的 `{sheets,dicts,groups,automations,provider,check,error}`、
  deploy 的 `{sheets,groups,moved,automations,all_ok}`),`progress` 为逐条进度明细。
- **进度是细粒度的**:每一步都带 `pct(0-100)`,前端进度条据此实时推进;`text` 描述当前动作
  (如"结构化抽取 3/12:表单.xlsx"),`level` ∈ info|success|warning|error。任务进行中即可看到
  执行明细与百分比,不必等到结束。

#### 参考资料如何喂给模型(预算 + 结构化抽取 + 目录模式)
方案/ER 生成时,参考资料 = 本项目文档 + 勾选的资料库资料。为避免"文件一多就塞爆上下文",链路为:
1. **结构化抽取**(`services/extract.py`):按类型处理并**缓存**到 `documents.extract_json`——
   Excel/DOCX 的表格抽成「列名(字段清单,无损)+ 数据行样例」;PDF/文本抽正文;
   **内嵌图片**(Excel/Word 里的截图、PDF 里的图、扫描件整页)交给视觉模型识别成文本并一并纳入;
   同一文件重复生成时直接复用缓存,不重复抽取与识别。
   任何"没抽到内容 / 图片没识别 / 未配置视觉模型"都会给出明确说明(`note`),不静默丢失。
2. **预算装配**(`services/context.py`):估算 token(中文按 1 字≈1 token,偏保守):
   - ≤ `H3AC_CTX_TOKEN_BUDGET` → `inline`,全部紧凑内容一次喂入;
   - 超预算但 ≤ `H3AC_CTX_CATALOG_THRESHOLD` → `truncated`,按文件均分预算截断,
     **字段清单永远完整保留**(渲染时字段在前、数据行/正文在后);
   - > 目录阈值 → `catalog`,只给「文件目录 + 一行简介」,再由模型按需索取具体文件
     (agent 式,`H3AC_CTX_MAX_SELECT_FILES` / `H3AC_CTX_MAX_SELECT_ROUNDS` 控制)。
3. 截断/未纳入/图片无法识别等都会写进进度明细(`level=warning`),**不静默降级**。

轮询查询:
```
GET /api/projects/{id}/jobs?active=1   (登录用户)  → data:{items:[job,...]}  本项目任务(active=1 仅运行中)
GET /api/jobs/{jobId}                  (登录用户)  → data:job
```
`job` = `{id,kind,title,projectId,userId,status(running|done|failed),progress:[{ts,level,text,pct}],result,error,detail,createdAt,updatedAt}`。

前端进入步骤时先查 `active=1` 的任务以**恢复「处理中」**,运行中禁用按钮;完成后重新拉取内容。
**进度展示统一在右侧「生成进度」侧栏**(可收起为右下角悬浮图标,悬浮图标显示运行中任务的最大百分比);
**各阶段标题显示该阶段任务的百分比**(plan→plan、flowchart→flowchart、design→design、deploy→deploy/verify),
阶段内容区不再内嵌进度面板。
任务跑在**进程内线程池**(单进程部署假设):
- **看门狗**:running 任务超过 `H3AC_JOB_TIMEOUT_MIN` 分钟(默认 30)无进度更新,查询/提交时自动标记 failed,
  释放占位,避免任务卡死后该项目该动作永久无法重试。
- **启动清理**:进程重启后残留的 running 任务会被启动逻辑标记 failed(避免前端卡死);
  多 worker 部署须设 `H3AC_FAIL_ORPHAN_JOBS=0` 关闭,否则会误杀其它 worker 正在跑的任务。
- 幂等锁为进程内锁;多 worker 场景需自行引入 DB 级占位或心跳租约。

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
GET  /api/jobs                (admin)             任务总表(异步任务历史)
```

**首次初始化**:仅当 `H3AC_ADMIN_PASSWORD` 环境变量显式设置时才在启动时自动建管理员;
否则系统保持 0 用户,前端登录页据 `needsBootstrap` 显示「初始化管理员」表单(调 `/api/auth/bootstrap`)。
不再使用硬编码弱口令。

## 6. 前端路由

```
/login
/                       → 重定向 /projects
/projects               项目列表 + 新建
/projects/:id           工作台(步骤条):需求 → 方案 → 流程图 → ER设计 → 生成应用
/library                资料库:上传/查看全平台共享的已有系统资料
/users                  (admin)
/settings               (admin, LLM)
```

## 7. AI Provider

- 配置来源:**DB settings 表**(管理员在「系统设置」页填写)→ 回退环境变量 `H3AC_LLM_*` → 回退启发式。
- `provider.name`: `llm` | `heuristic`。
- 任何 AI 产出都**并经过引擎清洗/校验**(`h3service.design.clean_design` + `run_check`),失败回退启发式。

## 8. 环境变量(仅运维用,用户不接触)

| 变量 | 默认 | 说明 |
|---|---|---|
| `H3AC_DATA_DIR` | `<仓库根>/data` | **运行数据目录**(DB/密钥/上传件/工作区/知识库产物);代码与数据分离 |
| `H3AC_SECRET` | 自动生成 `data/secret.key` | Cookie/JWT/凭据加密密钥 |
| `H3AC_ADMIN_EMAIL` / `H3AC_ADMIN_PASSWORD` | 空(不自动建) | **设置后**才在启动时创建管理员;未设置则走前端「初始化管理员」 |
| `H3AC_LLM_BASE_URL` / `H3AC_LLM_API_KEY` / `H3AC_LLM_MODEL` | 空 | LLM(可被 DB 设置覆盖) |
| `H3AC_CORS_ORIGINS` | `http://localhost:8991,http://127.0.0.1:8991`(另含旧 5173) | 允许的前端源 |
| `H3AC_COOKIE_SECURE` | 空(HTTP) | 生产 HTTPS 置 `1` |
| `H3AC_NIGHTLY_HOUR` / `H3AC_NIGHTLY_MIN` | `2` / `0` | 夜间知识库批处理 |
| `H3AC_MAX_UPLOAD_MB` | `30` | 单文件上传上限 |
| `H3AC_ACTIVATION_TTL_DAYS` | `7` | 新用户「一次性激活码」有效期(天) |
| `H3AC_JOB_TIMEOUT_MIN` | `30` | 后台任务超时(分钟无进度即判失败) |
| `H3AC_FAIL_ORPHAN_JOBS` | `1` | 启动时清理残留 running 任务(多 worker 须设 `0`) |
| `H3AC_CTX_TOKEN_BUDGET` | `120000` | 单次生成可用的参考资料 token 预算(超出按字段优先截断) |
| `H3AC_CTX_CATALOG_THRESHOLD` | `1000000` | 参考资料超过该 token 量 → 切「目录 + 按需取件」模式 |
| `H3AC_CTX_MAX_SELECT_FILES` / `H3AC_CTX_MAX_SELECT_ROUNDS` | `12` / `2` | 目录模式下模型单次/总索取文件数上限 |
| `H3AC_CTX_SAMPLE_ROWS` | `8` | 紧凑渲染中单表保留的数据行样例上限(字段清单不受限) |
| `H3AC_CTX_MAX_LIST_ROWS` / `H3AC_CTX_LIST_MAX_COLS` | `200` / `6` | **清单表**(列数 ≤ 该值,如需求清单「功能清单」)保留的行数上限;每行都是需求项,不取样例 |
| `H3AC_IMG_MAX_PER_FILE` | `6` | 单文件最多识别的内嵌图片数(0=不识别) |
| `H3AC_PDF_OCR_MIN_CHARS` / `H3AC_PDF_OCR_MAX_PAGES` | `40` / `8` | 扫描件判定阈值与整页识别页数上限 |
| `H3AC_IMG_MAX_MB` | `4` | 单张图片入模上限(MB) |

## 9. 接口现状与边界(重要)

- **认证通道**:全部氚云调用走**个人身份授权**(`Authorization: Bearer <h3_token>` + `EngineCode` 头)。
  **已不使用 OpenApi(EngineCode + EngineSecret)**;`engineSecret` 已从配置与代码中移除。
- **应用创建**:**本系统不自动创建氚云应用**。用户先在氚云后台创建应用,再把 `appCode` 填入项目
  (新建项目时可留空,生成应用前补填)。系统负责应用内的表单/自动化/分组。
- **业务数据接口:本方案不需要**。流程只完成"搭建应用结构"(表结构 + 自动化定义),
  不涉及表单记录(数据)的增删改查;因此不提供数据导入/导出/查询能力。
- **载荷基准**:氚云 UI 真实载荷样本在 `fixtures/`(生成逻辑逐字对照),见 `fixtures/README.md`。
