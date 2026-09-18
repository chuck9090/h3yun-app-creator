# h3factory 前端(独立工程)

React 18 + TypeScript + Vite + Ant Design 5。**前后端分离**:本工程只通过 HTTP API 与后端通信
(`/api`,开发期经 Vite 代理到 `http://localhost:8000`),不加载任何配置文件。

## 依赖与脚本

```bash
npm install
npm run dev          # 开发: http://localhost:5173 (/api 代理到后端 8000)
npm run build:only   # 生产构建 → dist/
npm run typecheck    # 类型检查
npm run preview      # 预览构建产物(注意:preview 不含 /api 代理,生产用 nginx)
```

## 页面与路由

| 路由 | 页面 | 说明 |
|---|---|---|
| `/login` | 登录 | 邮件+密码;系统无用户时显示「初始化管理员」 |
| `/projects` | 项目列表 | 新建项目(项目名称 / 项目标识 / 应用编码 / h3_token) |
| `/projects/:id` | 工作台 | Steps:需求 → 方案 → 流程图 → ER 设计 → 生成应用 |
| `/settings` | 系统设置(admin) | 配置 LLM(OpenAI 兼容接口) |
| `/users` | 用户管理(admin) | 增删改用户、角色、启停、重置密码 |

## 技术选型(见 docs/ARCHITECTURE.md §2)

- 业务流程图:**Mermaid**(文本→图,LLM 友好,前端零成本渲染)
- ER 图:**React Flow**(需可编辑:改表名/加表/改字段/控件类型)
- 方案 markdown:`react-markdown` 渲染 + `@uiw/react-md-editor` 编辑
- 需求富文本:`react-quill`

## 鉴权

会话在 **httpOnly Cookie** 中(非 localStorage)。启动时调 `GET /api/auth/me` 判断登录态,
401 由 axios 拦截器统一跳转 `/login`。

## 生产部署

`npm run build:only` 产出 `dist/`,由 nginx 等静态服务器托管,并把 `/api` 反向代理到后端,
确保**同源**(Cookie 才能携带)。
