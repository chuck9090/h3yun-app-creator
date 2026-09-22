# h3yun-app-creator —— 氚云应用生成平台

把「需求文档 → 系统设计方案 → 业务流程图 → ER 表图谱 → 生成氚云应用」固化成一条流水线。

**确定性部分(建表/核对/ER/载荷)全部脚本化,零 LLM 依赖;智能部分(需求→设计)由 AI 完成。**
前后端分离 + 工程化,用户**不需要填写或上传任何配置文件**。

```
浏览器 ──(httpOnly Cookie 会话)──▶ 前端 frontend/(React+TS+AntD,5173)
                                        │  /api 代理
                                        ▼
                                 后端 backend/(FastAPI,8000)
                                   ├─ 账号/权限 · 项目 · 文档 · 任务
                                   ├─ AI 编排(方案 md / 流程图 / ER)
                                   └─ 引擎桥接(调用根目录 h3*)
                                        ▼
                    引擎 h3design/h3platform/h3verify/h3service
                                        ▼
                    data/projects/<slug>/  ←→  氚云线上应用
```

## 快速开始

```powershell
pwsh -File start.ps1          # 后端 8000 + 前端 5173(自动装依赖)
```

访问 <http://localhost:5173>。**首次使用**:系统无用户时,登录页会显示「初始化管理员」,
由你设置邮箱与密码(不再有默认弱口令)。若要在启动时自动建管理员,先设环境变量
`H3AC_ADMIN_EMAIL` / `H3AC_ADMIN_PASSWORD`。

## 用户操作流程

1. 打开网址 → 未登录跳登录页 → **邮件 + 密码**登录;
2. 看到**自己的 / 别人授权给你的**项目列表;
3. 「新建项目」填:**项目名称 · 引擎编码(engineCode) · h3_token**(应用编码 appCode 可后填;粘贴 h3_token 会自动带出 engineCode;项目编号由系统自动生成);
4. 工作台「需求」:拖拽上传已有系统文档/需求/会议记录,或富文本补充;
5. 「生成方案」→ 系统设计方案(HTML 展示,底层 markdown);可进编辑页改;
6. 「生成业务流程图」→ Mermaid 图;不满意 → 回改方案 → 重生成,直到正确;
7. 「生成 ER 图」→ 可视化表图谱;可改表名、加表、改字段名、控件类型、加字段;
8. 「生成氚云应用」→ 据 ER 结构构造表单/自动化 JSON 写入氚云:先建表 → 按分组归入应用菜单 → 建触发器;
9. (可选)左侧「资料库」→ 新建一份「资料」(名称唯一 + 描述)并上传已有系统文档(全平台共享);
   系统每天夜间把资料下的文档整理成 AI 分析,供**所有项目**在「需求」页按资料名称勾选参考。

## 目录

```
h3yun-app-creator/
├─ frontend/              独立前端工程(React 18 + TS + Vite + AntD + React Flow + Mermaid)
├─ backend/               独立后端工程(FastAPI + 原生 sqlite3)
│   ├─ app/core/          配置 · 安全(Cookie/JWT/凭据加密) · 依赖(RBAC)
│   ├─ app/db/            SQLite 仓储
│   ├─ app/api/           路由:auth/users/projects/documents/pipeline/deploy/settings/system
│   ├─ app/services/      AI 服务:llm/plan/flowchart/design/parsing/nightly
│   ├─ app/engine_bridge.py   引擎桥接(凭据注入/落盘/校验/部署)
│   └─ tests/             核心 API · 流水线 · 真实服务冒烟
├─ h3design/              控件工厂 · SaveForm 载荷 · JSON DSL · 自动化 DSL · 知识库编译器
├─ h3platform/            连接层:Console SaveForm/LoadForm + Automatic SaveTrigger(个人身份授权)
├─ h3verify/              表单/自动化只读回读比对
├─ h3service/             引擎 service 层 + AI 启发式 + 知识库编译
├─ docs/                  ARCHITECTURE.md(契约) · web_platform.md(部署) · schema_doc.md(DSL)
│                         design_assistant.md(设计 SOP) · knowledge.md · platform_gotchas.md
├─ fixtures/              氚云载荷实证基准(**开发资产**,生成逻辑逐字对照;见 fixtures/README.md)
├─ start.ps1              一键启动(前后端双进程)
└─ data/                  **运行数据目录**(gitignore;可用 H3AC_DATA_DIR 覆盖)
                           ├─ h3yun-app-creator.db         用户/项目/文档索引/设置/任务
                           ├─ secret.key           服务端密钥(会话/凭据加密)
                           ├─ uploads/             上传原件
                           ├─ projects/<slug>/     项目工作区(定义/方案/流程图/ER/需求)
                           ├─ library/uploads/     全局资料库上传件(全用户共享,夜间整理)
                           └─ knowledge/           设计知识库产物(语料全部来自用户资料)
```

> **代码与数据分离**:仓库内**只有代码**(无内置样本、无凭据)。所有运行数据都在 `data/`,
> 首次运行自动创建。

## 关键设计

- **前后端分离**:两个独立工程、独立依赖、独立启动;开发期 Vite 代理 `/api`,生产期 nginx 同源反代。
- **代码与数据分离**:仓库只含代码;运行数据(DB/上传件/密钥/项目工作区/知识库产物)统一在 `data/`。
- **会话安全**:httpOnly Cookie + 自签 JWT;凭据(h3_token)加密存库,接口**绝不回显**。
- **凭据安全**:每个项目独立凭据;Web 端**绝不回落到运行目录 config**(否则会误建到别的应用)。
- **人机闸门**:AI 只产出方案/流程图/ER 草案;**「生成氚云应用」是一次显式点击**,且发布前必经引擎 `check` 校验。
- **AI 产出必过引擎**:LLM 生成的 ER 结构经 `h3service.design.clean_design` 清洗(剔幻觉键/非法类型/规范化 key)后再用。
- **AI 参考 = 用户资料**:出方案/表单结构的参考资料来自**用户上传的文档**(已有系统/需求/会议)
  与本部署已建项目语料(`data/knowledge/`),**不含任何内置样本**;复用时自动把不合规 key 规范化为驼峰并同步重写引用。
- **建表顺序**:按 `assoc` 依赖拓扑排序,被引用表先建;随后自动**归组**(应用菜单分组)并建**自动化(触发器)**。

## 文档

| 文件 | 内容 |
|---|---|
| `docs/ARCHITECTURE.md` | **接口契约**(前后端/引擎三方),改接口先改这里 |
| `docs/web_platform.md` | 部署与运维(开发/生产/环境变量/备份) |
| `docs/schema_doc.md` | 表单 JSON DSL 完整格式(控件类型/key 规则/子表/公式/联动/自动化) |
| `docs/design_assistant.md` | 粗需求 → 设计的 SOP(表盘点/漏项自检/覆盖检查) |
| `docs/knowledge.md` | 设计知识库(资料来源=用户项目) |
| `docs/platform_gotchas.md` | 氚云平台坑位(实证记录) |

## 测试

```powershell
# 后端(cwd=backend/)
python -X utf8 tests/test_core_api.py        # 认证/用户/项目/文档
python -X utf8 tests/test_pipeline_api.py    # 需求→方案→流程图→ER→部署
python -X utf8 tests/test_automations.py     # 自动化全链路 + 分组计划 + 设计清洗安全(路径穿越)
python -X utf8 tests/test_security.py        # 会话/权限/上传/凭据安全
python -X utf8 tests/smoke_real_server.py    # 真实端口 + Cookie 冒烟

# 前端(cwd=frontend/)
npm run typecheck && npm run build:only
```

## 安全基线

- **用户不接触配置文件**:仓库内无任何 `config.json`;凭据在页面输入、加密存库、接口不回显;
  engineCode 新增项目时填写(粘贴 h3_token 自动带出)。
- **凭据不回落**:每个项目独立凭据;Web 端绝不回落到运行目录 `data/config.json`。
- **会话**:httpOnly Cookie + 自签 JWT;登出/改密/停用即失效(token 版本)。
- **输入围栏**:表单/自动化 key 白名单(防路径穿越写任意文件);AI 产出经 `clean_design` 清洗。
- **部署安全**:线上探测失败**不自动换码**(避免孤儿表/断关联);字段数不符判**失败**(不假成功);
  `force` 仅管理员可用且前端二次确认。
- **首次初始化无默认弱口令**;上传分块校验大小、扩展名白名单。
