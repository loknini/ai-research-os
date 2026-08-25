# AI-Research-OS 启动脚本（新架构：独立 FastAPI 后端）
#
# 用法:
#   .\start.ps1                 # 启动 FastAPI 后端 + 前端开发服务器
#   .\start.ps1 -SkipFrontend   # 仅起后端
#   .\start.ps1 -SkipLLM        # 不校验 LLM 可用性（仅起后端做核心功能）
#   .\start.ps1 -ApiPort 9000   # 自定义后端端口
#   .\start.ps1 -ReuseBackend   # 端口已有健康后端实例时不重启，直接复用（默认会先结束旧实例再以最新代码启动）
#
# 说明:
#   - FastAPI 后端（uvicorn backend.server.main:app）为核心，默认启动。
#   - 前端开发服务器通过 Vite 反代 /api -> 后端（默认 :8000）。
#   - LLM 配置：在「设置 → LLM API 配置」中填写（硅基流动 / 智谱 / Ollama 等），
#     配置即时生效并写入项目根 .env。
#   - 首次运行会自动创建项目根 .venv 虚拟环境，后端依赖装进 .venv，
#     不污染系统全局 Python（仅创建 .venv 那一刻用全局 python）。

param(
    [switch]$SkipFrontend,
    [switch]$SkipBackend,     # 跳过 FastAPI 后端（默认启动）
    [switch]$SkipLLM,         # 不校验 LLM 可用性
    [switch]$ReuseBackend,    # 端口已有健康后端实例时复用而不重启（默认：结束旧实例并以最新代码重启）
    [int]$FrontendPort = 5173,
    [int]$ApiPort = 8000,
    [int]$ApiWorkers = 0,    # FastAPI worker 进程数；0 = 自动探测 min(CPU, 8)
    [string]$DataDir          # 数据目录（DATA_DIR）覆盖；优先级最高：命令行 -DataDir > .airos-data-dir 文件 > 已有环境变量 > 默认
)

# 强制控制台使用 UTF-8，避免中文/emoji 输出乱码
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# 强制 Python 以 UTF-8 模式运行（PEP 540），避免 pip 在中文 Windows 下
# 以 GBK/cp936 解码含非 ASCII 内容的 requirements.txt 时报 UnicodeDecodeError。
# 即便 requirements.txt 后续被加入非 ASCII 注释，也能正确解析。
$env:PYTHONUTF8 = "1"

$ProjectDir = $PSScriptRoot

# 数据目录（DATA_DIR）解析，优先级：命令行 -DataDir > 项目根 .airos-data-dir 文件 > 已有环境变量 DATA_DIR > 默认 $ProjectDir\data
if (-not $DataDir) {
    $dataDirFile = "$ProjectDir\.airos-data-dir"
    if (Test-Path $dataDirFile) {
        $DataDir = (Get-Content -Path $dataDirFile -TotalCount 1 | Out-String).Trim()
    }
}
if (-not $DataDir -and $env:DATA_DIR) {
    $DataDir = $env:DATA_DIR
}
if (-not $DataDir) {
    $DataDir = "$ProjectDir\data"
}
# 项目内虚拟环境（不污染全局 Python）
$VenvDir = "$ProjectDir\.venv"
$VenvPython = "$VenvDir\Scripts\python.exe"

Write-Host @"
╔═══════════════════════════════════════════════════════════════╗
║                    AI-Research-OS                             ║
║           AI-Powered Research & Development Workbench         ║
╚═══════════════════════════════════════════════════════════════╝
"@ -ForegroundColor Cyan

Write-Host "`n📋 检查环境..." -ForegroundColor Yellow

# 检查 Python（仅首次创建 .venv 时使用全局 python）
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Python 未安装" -ForegroundColor Red
    exit 1
}
Write-Host "   ✅ Python: $(python --version 2>&1)" -ForegroundColor Green

# 首次启动：若不存在 .venv，用全局 python 创建虚拟环境（仅此一次）
if (-not (Test-Path $VenvPython)) {
    Write-Host "⚠️  未发现项目虚拟环境 .venv，正在创建（仅此一次使用全局 python）..." -ForegroundColor Yellow
    python -m venv "$VenvDir"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ 创建虚拟环境失败，请确认全局 python 可用且支持 venv 模块" -ForegroundColor Red
        exit 1
    }
    Write-Host "   ✅ 已创建虚拟环境: $VenvDir" -ForegroundColor Green
} else {
    Write-Host "   ✅ 虚拟环境已就绪: $VenvDir" -ForegroundColor Green
}

# 检查 uvicorn（在 .venv 内）—— 基于退出码判断，避免空 stdout 被误判
& "$VenvPython" -c "import uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️  uvicorn 未安装，正在尝试安装后端依赖到 .venv..." -ForegroundColor Yellow
    & "$VenvPython" -m pip install -r "$ProjectDir\backend\requirements.txt"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ 后端依赖安装失败，请手动执行: $VenvPython -m pip install -r backend/requirements.txt" -ForegroundColor Red
        exit 1
    }
}

# 前端依赖
if (-not $SkipFrontend) {
    if (-not (Test-Path "$ProjectDir\frontend\node_modules")) {
        Write-Host "⚠️  前端依赖未安装，正在安装..." -ForegroundColor Yellow
        Set-Location "$ProjectDir\frontend"
        npm install
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ 前端依赖安装失败" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "   ✅ 前端依赖已就绪" -ForegroundColor Green
}

# 确保数据目录存在
@("papers", "experiments", "software", "knowledge") | ForEach-Object {
    $dir = "$DataDir\$_"
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
}
Write-Host "   ✅ 数据目录已就绪" -ForegroundColor Green

Write-Host "`n🚀 启动服务..." -ForegroundColor Yellow

# 将解析后的数据目录导出给后端进程（必须在启动 uvicorn 之前设置 DATA_DIR）
if ($DataDir) { $env:DATA_DIR = $DataDir }

# 多 worker：优先使用 -ApiWorkers，否则自动探测 min(CPU, 8)
if ($ApiWorkers -gt 0) {
    $Workers = $ApiWorkers
} else {
    $Workers = [Math]::Min((& "$VenvPython" -c "import os; print(min(os.cpu_count() or 1, 8))"), 8)
}

# 端口占用检测：WinError 10013 的主要根因是端口被残留实例/其他程序占用，
# Windows 对「绑定已被独占的端口」报 10013（访问权限不允许）而非 10048（端口占用）。
function Get-PortListener {
    param([int]$Port)
    return Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

# 启动 FastAPI 后端（使用 .venv 解释器，多 worker 常驻）
if (-not $SkipBackend) {
    # 预检：端口若被占用，区分「本应用健康实例 → 复用」与「其他程序 → 报错退出」
    $listener = Get-PortListener -Port $ApiPort
    if ($listener) {
        $occPid = $listener.OwningProcess
        $occName = (Get-Process -Id $occPid -ErrorAction SilentlyContinue).ProcessName
        $healthy = $false
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:$ApiPort/api/healthz" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
            if ($resp.StatusCode -eq 200) { $healthy = $true }
        } catch {}
        if ($healthy) {
            if ($ReuseBackend) {
                Write-Host "   ✅ 端口 $ApiPort 已有健康的后端实例在运行 (PID $occPid)，-ReuseBackend 指定复用、跳过启动" -ForegroundColor Green
                Write-Host "      ⚠️ 复用意味着旧代码不会热更新" -ForegroundColor Gray
                $SkipBackend = $true
            } elseif ($occName -match 'python|uvicorn') {
                # 本应用残留实例：先结束（连子 worker 进程树一起），再以最新代码重启
                Write-Host "   🔄 端口 $ApiPort 检测到旧的 $occName 实例 (PID $occPid)，正在结束并以最新代码重启..." -ForegroundColor Yellow
                taskkill /PID $occPid /T /F | Out-Null
                $waited = 0
                while ($waited -lt 15 -and (Get-PortListener -Port $ApiPort)) {
                    Start-Sleep -Milliseconds 500
                    $waited++
                }
                if (Get-PortListener -Port $ApiPort) {
                    Write-Host "   ❌ 旧实例结束超时，端口 $ApiPort 仍被占用，请手动处理: taskkill /PID $occPid /T /F" -ForegroundColor Red
                    exit 1
                }
                Write-Host "   ✅ 旧实例已结束 (耗时约 $([Math]::Round($waited * 0.5, 1))s)，即将以最新代码启动" -ForegroundColor Green
            } else {
                Write-Host "   ❌ 端口 $ApiPort 已被 $occName (PID $occPid) 占用且健康检查通过，非本应用残留实例，不自动结束" -ForegroundColor Red
                Write-Host "      解决方案:" -ForegroundColor Yellow
                Write-Host "        1) 关闭占用该端口的程序后重试" -ForegroundColor Yellow
                Write-Host "        2) 强制结束: taskkill /PID $occPid /T /F" -ForegroundColor Yellow
                Write-Host "        3) 换端口启动: .\start.ps1 -ApiPort 8001" -ForegroundColor Yellow
                exit 1
            }
        } else {
            Write-Host "   ❌ 端口 $ApiPort 已被 $occName (PID $occPid) 占用，后端无法启动" -ForegroundColor Red
            Write-Host "      解决方案:" -ForegroundColor Yellow
            Write-Host "        1) 关闭占用该端口的程序后重试" -ForegroundColor Yellow
            Write-Host "        2) 强制结束: taskkill /PID $occPid /T /F" -ForegroundColor Yellow
            Write-Host "        3) 换端口启动: .\start.ps1 -ApiPort 8001" -ForegroundColor Yellow
            exit 1
        }
    }
}

if (-not $SkipBackend) {
    Write-Host "   🔌 启动 FastAPI 后端 (端口: $ApiPort, workers: $Workers)..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$ProjectDir'; & '$VenvPython' -m uvicorn backend.server.main:app --port $ApiPort --workers $Workers" -WindowStyle Normal

    # 等待后端就绪（除非显式跳过 LLM 校验也仍等待健康检查）
    Write-Host "   ⏳ 等待后端就绪..." -ForegroundColor Gray
    $retries = 0
    $maxRetries = 40
    $connected = $false
    while ($retries -lt $maxRetries -and -not $connected) {
        Start-Sleep -Milliseconds 500
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:$ApiPort/api/healthz" -UseBasicParsing -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) { $connected = $true }
        } catch {}
        $retries++
    }
    if ($connected) {
        Write-Host "   ✅ 后端已就绪 (http://localhost:$ApiPort)" -ForegroundColor Green
    } else {
        Write-Host "   ⚠️  后端启动中或健康检查失败，请查看后端窗口日志" -ForegroundColor Yellow
    }
}

# 启动前端开发服务器
if (-not $SkipFrontend) {
    # Vite 代理目标跟随后端端口（vite.config.ts 读取 VITE_API_TARGET，默认 http://localhost:8000）
    $env:VITE_API_TARGET = "http://localhost:$ApiPort"

    # 预检前端端口：被占用时 Vite 会自动改用相邻端口，提前提示避免访问错地址
    $feListener = Get-PortListener -Port $FrontendPort
    if ($feListener) {
        $fePid = $feListener.OwningProcess
        $feName = (Get-Process -Id $fePid -ErrorAction SilentlyContinue).ProcessName
        Write-Host "   ⚠️ 端口 $FrontendPort 已被 $feName (PID $fePid) 占用，Vite 将自动改用相邻端口，请以 Vite 窗口实际输出为准" -ForegroundColor Yellow
    }

    Write-Host "   🎨 启动前端开发服务器 (端口: $FrontendPort)..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$ProjectDir\frontend'; npm run dev -- --port $FrontendPort" -WindowStyle Normal
}

Write-Host @"

✨ 服务启动完成！

📍 访问地址:
   前端界面:     http://localhost:$FrontendPort
   后端 API:     http://localhost:$ApiPort/api
   API 文档:     http://localhost:$ApiPort/docs
   健康检查:     http://localhost:$ApiPort/api/healthz

📁 项目目录: $ProjectDir
💾 数据目录: $DataDir
🐍 后端环境: $VenvDir (虚拟环境，不污染全局 Python)

💡 提示:
   - 配置 LLM：打开前端「设置 → LLM API 配置」填写（也可复制 backend/.env.example 为项目根 .env）
   - 数据备份与迁移：打开前端「设置 → 数据备份与迁移」卡片
   - 查看设计文档: .\DESIGN.md
   - 按 Ctrl+C 停止各个服务窗口

"@ -ForegroundColor Green
