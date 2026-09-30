# 服务器部署指南(Linux + Windows)

> 本文是**完整逐步手册**,面向把平台部署到一台正式服务器。接口契约见 `dev/docs/architecture.md`,
> 开发/内网快速启动见 `dev/docs/web_platform.md`。**代码与数据分离**:仓库内只有代码,
> 所有运行数据(DB/密钥/上传件/项目工作区)都在 `server/data/` 目录(可用 `H3AC_DATA_DIR` 覆盖)。

---

## 0. 部署架构与前置条件

```
浏览器 ──https──▶ 反向代理(Nginx / IIS)
                     ├─ /            → 前端静态产物 web/dist/(React 构建结果)
                     └─ /api/        → 后端 FastAPI(127.0.0.1:8990, systemd/服务托管)
                                          └─ 调用 server/h3*(纯标准库引擎)
                                              └─ server/data/ 运行数据(SQLite + 上传件 + 密钥)
```

**端口约定**:后端 `8990`(仅监听 `127.0.0.1`,由反向代理暴露),前端静态由 Nginx/IIS 提供 `80/443`。
对外**只开放 80/443**,后端端口不直接对外。

**前置条件**

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.10+(含 `venv`) | 后端 + `server/` 下的引擎 `h3design/h3platform/h3verify/h3service`(**纯标准库**,无额外依赖) |
| Node.js | 18+ | **仅构建前端时**需要;产物 `web/dist` 为纯静态 |
| 反向代理 | Nginx 1.18+ / IIS 10(ARR) | 托管静态 + 反代 `/api` |
| 系统 | Ubuntu 20.04+/CentOS 7+/Windows Server 2016+ | |

**内存/磁盘**:后端常驻约 200~400MB;`server/data/` 随上传件与项目增长,建议预留 ≥10GB 并纳入备份。
**SQLite 要求**:`server/data/` 必须放在**本地磁盘**(WAL 模式,不支持 NFS/网络盘)。

---

## 1. 通用准备(两种系统都要做)

### 1.1 拉取代码

```bash
# 目录示例:Linux 用 /opt/h3yun-app-creator,Windows 用 D:\apps\h3yun-app-creator
sudo git clone <你的仓库地址> /opt/h3yun-app-creator
# 或上传代码压缩包后解压
```

### 1.2 规划运行数据目录(强烈建议独立于代码)

生产环境把运行数据放到独立目录,便于备份与权限隔离(下文以 Linux `/var/lib/h3yun-app-creator`
为例;Windows 用 `D:\apps\h3ac-data`)。后端通过 `H3AC_DATA_DIR` 指向它,首次运行自动建表与建目录。

### 1.3 会话/凭据密钥(**必须固定**)

平台用**同一个密钥**签发会话 Cookie 并加密各项目的 `h3_token`。生产环境**必须显式设置 `H3AC_SECRET`**:

```bash
# 生成一个 48 字节随机密钥(hex 或 base64 均可)
python3 -c "import secrets; print(secrets.token_hex(48))"
```

> **务必妥善保存 `H3AC_SECRET`**:它与 `data/secret.key` 二选一(环境变量优先)。
> 密钥一旦变化或丢失,已有 `h3_token` 将无法解密,所有用户会话也会失效。

### 1.4 环境变量(写入独立 env 文件,不写进代码)

下文 Linux 用 `/etc/h3ac.env`、Windows 用系统环境变量或 NSSM 参数。**完整变量表见第 5 节**。
最小生产集:

```ini
H3AC_DATA_DIR=/var/lib/h3yun-app-creator
H3AC_SECRET=<上一步生成的随机密钥>
H3AC_COOKIE_SECURE=1
H3AC_CORS_ORIGINS=https://你的域名
# 可选:启动时自动建管理员(仅首次,建好后可删除这两行)
# H3AC_ADMIN_EMAIL=admin@example.com
# H3AC_ADMIN_PASSWORD=<强密码>
```

---

## 2. Linux 部署(Nginx + systemd)

以 Ubuntu/Debian 为例(CentOS 把 `apt` 换成 `dnf`,`www-data` 换成 `nginx`)。

### 2.1 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git
# 仅构建前端需要 Node 18+(推荐用 NodeSource 或 nvm)
node -v   # 确认 >= 18
```

### 2.2 创建后端虚拟环境并安装依赖

```bash
cd /opt/h3yun-app-creator/server
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### 2.3 构建前端静态产物

```bash
cd /opt/h3yun-app-creator/web
npm ci                 # 首次:严格按 lock 安装
npm run build:only     # 产物:web/dist/
```

> 可选:`npm run typecheck` 先做类型检查。构建产物 `dist/` 由 Nginx 托管,**构建机与运行机可分离**。

### 2.4 准备数据目录并授权

```bash
sudo mkdir -p /var/lib/h3yun-app-creator
# 专用系统用户运行后端(不给登录 shell),避免 root 运行
sudo useradd --system --no-create-home --shell /usr/sbin/nologin h3ac || true
sudo chown -R h3ac:h3ac /var/lib/h3yun-app-creator
sudo chown -R h3ac:h3ac /opt/h3yun-app-creator/web/dist
```

### 2.5 写入环境变量文件

```bash
sudo tee /etc/h3ac.env >/dev/null <<'EOF'
H3AC_DATA_DIR=/var/lib/h3yun-app-creator
H3AC_SECRET=请替换为上一步生成的随机密钥
H3AC_COOKIE_SECURE=1
H3AC_CORS_ORIGINS=https://你的域名
EOF
sudo chmod 600 /etc/h3ac.env
sudo chown root:root /etc/h3ac.env
```

### 2.6 注册 systemd 服务

```bash
sudo tee /etc/systemd/system/h3ac-server.service >/dev/null <<'EOF'
[Unit]
Description=h3yun-app-creator server (FastAPI)
After=network.target

[Service]
Type=simple
User=h3ac
Group=h3ac
WorkingDirectory=/opt/h3yun-app-creator/server
EnvironmentFile=/etc/h3ac.env
# 单 worker:后台生成任务是进程内线程,多 worker 会重复跑定时任务并加剧 SQLite 锁竞争
ExecStart=/opt/h3yun-app-creator/server/.venv/bin/python -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8990 --workers 1
Restart=on-failure
RestartSec=3
# 仅本地反向代理访问,无需对外
[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now h3ac-server
sudo systemctl status h3ac-server --no-pager
curl -s http://127.0.0.1:8990/    # 应返回 {"ok": true, ...}
```

### 2.7 配置 Nginx(同源:静态 + 反代 /api)

```bash
sudo tee /etc/nginx/sites-available/h3ac.conf >/dev/null <<'EOF'
server {
    listen 80;
    server_name 你的域名;

    # 上传件上限:需 >= H3AC_MAX_UPLOAD_MB(默认 30MB),留余量
    client_max_body_size 40m;

    # 前端静态产物
    root /opt/h3yun-app-creator/web/dist;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;   # 前端用 HashRouter,回退到 index 即可
    }

    # 反代后端(/api 前缀原样保留,proxy_pass 末尾不加斜杠)
    location /api/ {
        proxy_pass http://127.0.0.1:8990;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;            # 生成类请求可能较久
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/h3ac.conf /etc/nginx/sites-enabled/h3ac.conf
sudo nginx -t && sudo systemctl reload nginx
```

> **必须同源**:前端与 `/api` 用同一域名,httpOnly Cookie 才能正常携带。
> 用 `proxy_pass http://127.0.0.1:8990;`(不带路径),可让 `/api/xxx` 原样转发到后端 `/api/xxx`。

### 2.8 启用 HTTPS(可选但推荐)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d 你的域名
```

> HTTPS 下 `H3AC_COOKIE_SECURE=1` 才能让浏览器正常回传会话 Cookie;若暂用 HTTP,请改为空。

### 2.9 初始化管理员

浏览器打开 `https://你的域名`。**系统无用户时**,登录页显示「初始化管理员」,由你设置邮箱与密码
(无默认弱口令)。或提前在 `/etc/h3ac.env` 设置 `H3AC_ADMIN_EMAIL` / `H3AC_ADMIN_PASSWORD` 自动创建后删除。

### 2.10 放行防火墙

```bash
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp   # 不要对公网开放 8990
```

---

## 3. Windows Server 部署(NSSM + Nginx/IIS)

### 3.1 安装依赖

- **Python 3.10+**:安装时勾选 “Add Python to PATH”。
- **Node.js 18+**:仅构建前端(可在构建机构建后把 `dist` 拷到服务器)。
- **NSSM**(把后端注册为 Windows 服务):<https://nssm.cc/download> 解压后把 `nssm.exe` 放入 `PATH`。
- **Nginx for Windows**(或 IIS + ARR):<http://nginx.org/en/download.html>。

```powershell
# 后端虚拟环境
cd D:\apps\h3yun-app-creator\server
python -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\pip install -r requirements.txt

# 构建前端
cd D:\apps\h3yun-app-creator\web
npm ci
npm run build:only      # 产物 D:\apps\h3yun-app-creator\web\dist
```

> 也可直接用仓库自带脚本:`pwsh -File start.ps1 -Prod`(仅构建前端,不启 dev server)。

### 3.2 设置系统环境变量

```powershell
[Environment]::SetEnvironmentVariable("H3AC_DATA_DIR",     "D:\apps\h3ac-data",           "Machine")
[Environment]::SetEnvironmentVariable("H3AC_SECRET",        "<生成的随机密钥>",             "Machine")
[Environment]::SetEnvironmentVariable("H3AC_COOKIE_SECURE", "1",                            "Machine")
[Environment]::SetEnvironmentVariable("H3AC_CORS_ORIGINS",  "https://你的域名",             "Machine")
New-Item -ItemType Directory -Force -Path "D:\apps\h3ac-data" | Out-Null
# 生成密钥:python -c "import secrets; print(secrets.token_hex(48))"
```

### 3.3 用 NSSM 注册后端服务

```powershell
$py = "D:\apps\h3yun-app-creator\server\.venv\Scripts\python.exe"
nssm install H3ACServer $py
nssm set H3ACServer AppParameters "-X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8990 --workers 1"
nssm set H3ACServer AppDirectory "D:\apps\h3yun-app-creator\server"
nssm set H3ACServer Start SERVICE_AUTO_START
nssm set H3ACServer AppStdout "D:\apps\h3ac-data\server.out.log"
nssm set H3ACServer AppStderr "D:\apps\h3ac-data\server.err.log"
nssm start H3ACServer
# 验证
Invoke-RestMethod http://127.0.0.1:8990/    # 应返回 ok: true
```

> **替代方案(不用 NSSM)**:用「任务计划程序」创建“计算机启动时”触发的任务,
> 程序填 `.venv\Scripts\python.exe`,参数填 `-X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8990`,
> 起始于填 `server` 目录。缺点是无自动重启与日志轮转,故推荐 NSSM。

### 3.4 Nginx for Windows 反向代理

编辑 `conf\nginx.conf`(路径按你的安装位置):

```nginx
worker_processes 1;
events { worker_connections 1024; }
http {
    include       mime.types;
    default_type  application/octet-stream;
    sendfile      on;
    client_max_body_size 40m;

    server {
        listen       80;
        server_name  你的域名;
        root         D:/apps/h3yun-app-creator/web/dist;
        index        index.html;

        location / {
            try_files $uri $uri/ /index.html;
        }
        location /api/ {
            proxy_pass http://127.0.0.1:8990;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 300s;
        }
    }
}
```

```powershell
# 启动 Nginx(把 nginx 目录加入 PATH 或写全路径)
Start-Process nginx
nginx -s reload
```

### 3.5 用 IIS 反向代理(替代 Nginx)

1. 安装 **IIS**、**URL Rewrite**、**Application Request Routing (ARR)** 三个模块;
2. IIS 管理器 → 服务器节点 → ARR → 勾选 *Enable proxy*;
3. 新建站点指向 `web\dist`,站点根放 `web.config`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="api-proxy" stopProcessing="true">
          <match url="^api/(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:8990/api/{R:1}" />
        </rule>
      </rules>
    </rewrite>
    <security>
      <requestFiltering>
        <!-- 上传上限,单位字节;与 H3AC_MAX_UPLOAD_MB 对齐 -->
        <requestLimits maxAllowedContentLength="41943040" />
      </requestFiltering>
    </security>
  </system.webServer>
</configuration>
```

### 3.6 HTTPS 与防火墙

- 证书可导入 IIS(绑定 443)或 Nginx(`listen 443 ssl;`);启用 HTTPS 后保持 `H3AC_COOKIE_SECURE=1`。
- 防火墙只放行 80/443;`8990` 仅本机回环访问:

```powershell
New-NetFirewallRule -DisplayName "H3AC HTTP"  -Direction Inbound -Protocol TCP -LocalPort 80  -Action Allow
New-NetFirewallRule -DisplayName "H3AC HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
```

---

## 4. 升级 / 备份 / 恢复

### 4.1 升级

```bash
# Linux
cd /opt/h3yun-app-creator
git pull
. server/.venv/bin/activate && pip install -r server/requirements.txt
(cd web && npm ci && npm run build:only)
sudo systemctl restart h3ac-server && sudo systemctl reload nginx
```

```powershell
# Windows
cd D:\apps\h3yun-app-creator
git pull
& .\server\.venv\Scripts\pip install -r server\requirements.txt
Push-Location web; npm ci; npm run build:only; Pop-Location
nssm restart H3ACServer
```

> 数据库迁移是**幂等**的,后端启动时自动执行,无需手工迁移。

### 4.2 备份(核心就是备份 `data/`)

**必须备份**的内容(默认 `<server>/data`,生产已被 `H3AC_DATA_DIR` 指向):

```bash
# Linux:先停写或直接冷备
sudo tar czf /backup/h3ac-$(date +%F).tgz -C /var/lib/h3yun-app-creator .
```

```powershell
# Windows
Compress-Archive -Path "D:\apps\h3ac-data\*" -DestinationPath "D:\backup\h3ac-$(Get-Date -Format yyyyMMdd).zip"
```

关键路径:

| 路径 | 内容 | 重要度 |
|---|---|---|
| `data/h3yun-app-creator.db` | 用户/项目/文档索引/设置/任务 | 高 |
| `data/secret.key` | 服务端密钥(**或改用 `H3AC_SECRET` 环境变量**) | **最高** |
| `data/uploads/` `data/library/` | 上传原件与资料库文件 | 高 |
| `data/projects/<slug>/` | plan/flowchart/design/需求/sheets/automations | 高 |
| `data/knowledge/` | 设计知识库产物 | 中(可重建) |

> 建议同时把 `H3AC_SECRET`(或 `secret.key`)单独抄一份离线保存——它是解密 `h3_token` 的唯一钥匙。
> 也可配 `sqlite3 data/h3yun-app-creator.db ".backup '/backup/db.sqlite'"` 做在线热备。

### 4.3 恢复

把备份的 `data/` 原样还原到 `H3AC_DATA_DIR`(或恢复 `H3AC_SECRET`)后重启后端即可。

---

## 5. 环境变量速查(仅运维)

| 变量 | 默认 | 说明 |
|---|---|---|
| `H3AC_DATA_DIR` | `<server>/data` | 运行数据目录(DB/密钥/上传件/工作区/知识库) |
| `H3AC_SECRET` | 自动生成 `data/secret.key` | **生产建议注入**:会话 JWT 与凭据加密密钥(**必须固定**) |
| `H3AC_COOKIE_SECURE` | 空(HTTP) | HTTPS 部署置 `1` |
| `H3AC_CORS_ORIGINS` | localhost:8991 等 | 允许的前端源(逗号分隔);同源反代时填公网域名 |
| `H3AC_ADMIN_EMAIL` / `H3AC_ADMIN_PASSWORD` | 空 | 设置后才在启动时建管理员;否则走前端「初始化管理员」 |
| `H3AC_MAX_UPLOAD_MB` | `30` | 单文件上限(反向代理的 body 上限需不小于此值) |
| `H3AC_COOKIE_SAMESITE` | `lax` | 同源部署保持默认 |
| `H3AC_LLM_BASE_URL` / `H3AC_LLM_API_KEY` / `H3AC_LLM_MODEL` | 空 | LLM 回退配置;管理员也可在「系统设置」页填写(优先) |
| `H3AC_H3_BASE_URL` | `https://www.h3yun.com/` | 氚云开放平台地址 |
| `H3AC_NIGHTLY_HOUR` / `H3AC_NIGHTLY_MIN` | `2` / `0` | 每晚知识库批处理时间 |
| `H3AC_JOB_TIMEOUT_MIN` | `30` | 后台任务超时(分钟无进度判失败) |
| `H3AC_FAIL_ORPHAN_JOBS` | `1` | 启动清理残留任务;**多 worker 部署须设 `0`** |
| `H3AC_TOKEN_TTL` | `604800` | 会话有效期(秒) |
| `H3AC_ACTIVATION_TTL_DAYS` | `7` | 新用户激活码有效期(天) |
| 其余 `H3AC_CTX_*` / `H3AC_IMG_*` / `H3AC_PDF_*` | 见 `dev/docs/web_platform.md` | AI 上下文与图片识别预算 |

---

## 6. 部署后验收清单

- [ ] `curl http://127.0.0.1:8990/` 返回 `{"ok": true, ...}`;`/docs` 可打开 API 文档。
- [ ] 浏览器访问 `https://域名` → 未登录跳登录页 → 能「初始化管理员」并登录。
- [ ] 登录后 Cookie 为 httpOnly;HTTPS 下响应头含 `Secure`。
- [ ] 新建项目 → 填 `engineCode` + `h3_token` → 「需求」上传需求清单 → 「生成方案」任务正常轮询出结果。
- [ ] 上传一个接近上限(如 25MB)的文件不被拒(验证代理 `client_max_body_size` / `requestLimits`)。
- [ ] 「系统设置」配置好大模型(或设置 `H3AC_LLM_*`),生成方案标记为 `llm` 而非 `heuristic`。
- [ ] 重启后端服务后,数据仍在、会话可恢复(`data/` 与密钥未变)。

---

## 7. 常见问题

| 现象 | 原因 / 解决 |
|---|---|
| 前端能开但 `/api` 全 502 | 后端未起或端口不符;查 `systemctl status h3ac-server` / NSSM 日志;确认反代指向 `127.0.0.1:8990` |
| 登录成功但立刻掉线 | 前后端**非同源**或 HTTPS 下未设 `H3AC_COOKIE_SECURE=1`;确保同一域名反代 `/api` |
| 上传大文件报 413 | Nginx `client_max_body_size` / IIS `maxAllowedContentLength` 小于文件;调到 ≥ `H3AC_MAX_UPLOAD_MB` |
| 重启后凭据/会话全失效 | `H3AC_SECRET` 变了或 `secret.key` 丢失;恢复到原密钥 |
| 生成任务卡在「处理中」 | 后端被重启过(残留任务);确认 `H3AC_FAIL_ORPHAN_JOBS=1`(单 worker) |
| 起了多个实例卡死 | 重复启动多个后端进程致 SQLite 锁竞争;关闭多余进程,只保留 systemd/NSSM 托管的那一个 |
| 多 worker 下任务重复/被杀 | 生成任务是**进程内线程**,建议 `--workers 1`;若坚持多 worker,须设 `H3AC_FAIL_ORPHAN_JOBS=0` |
| `data/` 放网络盘后偶发锁死 | SQLite WAL 不支持网络文件系统;把 `H3AC_DATA_DIR` 指到本地磁盘 |

> 说明:`--workers 1` 是**推荐且默认**部署形态——后台生成任务基于进程内线程池,
> 定时知识库批处理也是进程内线程;多 worker 会导致定时任务重复执行并放大 SQLite 锁竞争。
