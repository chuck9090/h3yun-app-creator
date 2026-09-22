# h3yun-app-creator 一键启动(Windows PowerShell 7) —— 前后端分离,双进程
#
# 用法:
#   pwsh -File start.ps1                 # 同时启动后端(8000)+ 前端 dev(5173)
#   pwsh -File start.ps1 -BackendOnly    # 只启动后端
#   pwsh -File start.ps1 -FrontendOnly   # 只启动前端
#   pwsh -File start.ps1 -Prod           # 构建前端静态产物(不启 dev server)
#
# 访问: http://localhost:5173   (前端; /api 自动代理到后端 8000)
# API 文档: http://localhost:8000/docs
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$Prod,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "== 氚云应用生成平台(前后端分离)==" -ForegroundColor Cyan

function Ensure-BackendDeps {
    python -X utf8 -c "import fastapi, uvicorn, httpx, openpyxl, docx, pypdf" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "安装后端依赖 ..." -ForegroundColor Yellow
        python -X utf8 -m pip install -r "$root\backend\requirements.txt" --index-url https://pypi.org/simple
    }
}

function Ensure-FrontendDeps {
    if (-not (Test-Path -LiteralPath "$root\frontend\node_modules")) {
        Write-Host "安装前端依赖 ..." -ForegroundColor Yellow
        Push-Location -LiteralPath "$root\frontend"
        try { npm install --no-audit --no-fund } finally { Pop-Location }
    }
}

$startBackend = -not $FrontendOnly
$startFrontend = -not $BackendOnly

if ($startBackend -and -not $SkipInstall) { Ensure-BackendDeps }
if (($startFrontend -or $Prod) -and -not $SkipInstall) { Ensure-FrontendDeps }

# 生产:构建前端静态产物(dist/ 由 nginx 或任意静态服务器托管;本脚本仅构建)
if ($Prod) {
    Push-Location -LiteralPath "$root\frontend"
    try {
        Write-Host "构建前端 ..." -ForegroundColor Yellow
        npm run build:only
    } finally { Pop-Location }
    Write-Host "前端已构建到 frontend\dist\ —— 用 nginx 托管,并把 /api 反代到后端。" -ForegroundColor Green
    if (-not $startBackend) { exit 0 }
}

$procs = @()
if ($startBackend) {
    # 首次初始化:仅当显式设置 H3AC_ADMIN_PASSWORD 时才在启动时自动建管理员;
    # 否则系统保持 0 用户,由前端登录页「初始化管理员」完成(不再有默认弱口令)。
    if ($env:H3AC_ADMIN_PASSWORD) {
        if (-not $env:H3AC_ADMIN_EMAIL) { $env:H3AC_ADMIN_EMAIL = "admin@local" }
        Write-Host "将创建管理员:$env:H3AC_ADMIN_EMAIL(密码取自 H3AC_ADMIN_PASSWORD)" -ForegroundColor Yellow
    } else {
        Write-Host "未设置 H3AC_ADMIN_PASSWORD:首次访问前端将引导你创建管理员。" -ForegroundColor Yellow
    }
    Write-Host "启动后端: http://localhost:$BackendPort" -ForegroundColor Green
    $procs += Start-Process python -PassThru -WorkingDirectory "$root\backend" `
        -ArgumentList @("-X","utf8","-m","uvicorn","app.main:app","--host","localhost","--port","$BackendPort","--reload")
}

if ($startFrontend) {
    Write-Host "启动前端: http://localhost:$FrontendPort" -ForegroundColor Green
    $procs += Start-Process npm.cmd -PassThru -WorkingDirectory "$root\frontend" `
        -ArgumentList @("run","dev","--","--port","$FrontendPort")
}

if ($Procs.Count -eq 0) { Write-Host "无进程启动。" ; exit 0 }

Write-Host "`n按 Ctrl+C 停止。" -ForegroundColor Yellow
try {
    Wait-Process -Id ($procs | ForEach-Object { $_.Id })
} finally {
    foreach ($p in $procs) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "已停止。" -ForegroundColor Cyan
}
