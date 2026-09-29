# AI-Research-OS 启动脚本（新架构：独立 FastAPI 后端）
#
# 用法:
#   .\start.ps1                 # 启动 FastAPI 后端 + 前端开发服务器
#   .\start.ps1 -SkipFrontend   # 仅起后端
#   .\start.ps1 -SkipLLM        # 不校验 LLM 可用性（仅起后端做核心功能）
#   .\start.ps1 -ApiPort 9000   # 自定义后端端口
#   .\start.ps1 -ReuseBackend   # 端口已有健康后端实例时不重启，直接复用（默认会先结束旧实例再以最新代码启动）
#   .\start.ps1 -Restart        # 重启模式：结束后端+前端（如正在运行）后以最新代码重新启动
#   .\start.ps1                 # 默认后台启动：不弹新终端，日志进 logs/，用 .\stop.ps1 停止
#   .\start.ps1 -ShowTerminals  # 调试模式：为前后端分别打开可见终端
#
# ⚠️ 不要用系统 python 手动再起一个 uvicorn（即使不同端口）：
#   双后端共享同一 SQLite 会造成慢性 database is locked（reindex 500 事故根因）。
#   如需多开，先换 DATA_DIR 再起；健康检查 /api/healthz 会报 siblingInstances。
#
# 说明:
#   - FastAPI 后端（uvicorn backend.server.main:app）为核心，默认启动。
#   - 前端开发服务器通过 Vite 反代 /api -> 后端（默认 :8000）。
#   - LLM 配置：在「设置 → LLM API 配置」中填写（硅基流动 / 智谱 / Ollama 等），
#     配置即时生效并写入项目根 .env。
#   - 首次运行会自动创建项目根 .venv；每次启动按 requirements 指纹检查依赖，
#     有变化或缺失时同步进 .venv，不污染系统全局 Python。

param(
    [switch]$SkipFrontend,
    [switch]$SkipBackend,     # 跳过 FastAPI 后端（默认启动）
    [switch]$SkipLLM,         # 不校验 LLM 可用性
    [switch]$ReuseBackend,    # 端口已有健康后端实例时复用而不重启（默认：结束旧实例并以最新代码重启）
    [switch]$Restart,         # 重启模式：结束后端+前端（如正在运行）后以最新代码重新启动
    [int]$FrontendPort = 5173,
    [int]$ApiPort = 8000,
    [int]$ApiWorkers = 0,    # worker 数；Windows 后台固定 1，交互模式/其它平台 0 = 自动 min(CPU, 4)
    [string]$DataDir,         # 数据目录（DATA_DIR）覆盖；优先级最高：命令行 -DataDir > .airos-data-dir 文件 > 已有环境变量 > 默认
    [switch]$Background,      # 向后兼容：后台现为默认行为，此开关保留但无需再传
    [switch]$ShowTerminals,   # 调试模式：为前后端分别打开可见终端
    [string]$LogDir = ""      # 默认后台日志目录；留空则为 $ProjectDir\logs（git 已忽略）
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
# 默认使用后台模式，避免启动脚本退出/IDE 终端关闭时误伤服务，也不额外弹窗。
# -Background 为旧版兼容参数；需要实时终端日志时显式传 -ShowTerminals。
$UseBackground = -not $ShowTerminals
if ($Background -and $ShowTerminals) {
    Write-Host "❌ -Background 与 -ShowTerminals 不能同时使用" -ForegroundColor Red
    exit 1
}

# 后台日志目录
if (-not $LogDir) {
    $LogDir = "$ProjectDir\logs"
}
$env:LOG_DIR = $LogDir
# 项目内虚拟环境（不污染全局 Python）
$VenvDir = "$ProjectDir\.venv"
$VenvPython = "$VenvDir\Scripts\python.exe"
$RequirementsFile = "$ProjectDir\backend\requirements.txt"
$RequirementsStamp = "$VenvDir\.airos-requirements.sha256"

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

# requirements.txt 内容变化或直接依赖缺失时同步 .venv。
# 不能只检查 uvicorn：已有虚拟环境可能缺少后来新增的 jsonschema 等依赖。
$RequirementsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $RequirementsFile).Hash.ToLowerInvariant()
$InstalledRequirementsHash = ""
if (Test-Path -LiteralPath $RequirementsStamp) {
    $InstalledRequirementsHash = (Get-Content -LiteralPath $RequirementsStamp -Raw).Trim()
}
$BackendImportsReady = $false
if ($InstalledRequirementsHash -eq $RequirementsHash) {
    & "$VenvPython" -c "import aiosqlite, dotenv, fastapi, jsonschema, multipart, pydantic, pydantic_settings, pymupdf, requests, sqlite3, sqlite_vec, uvicorn; c=sqlite3.connect(':memory:'); c.enable_load_extension(True); sqlite_vec.load(c); assert c.execute('select vec_version()').fetchone()[0]" 2>$null
    $BackendImportsReady = ($LASTEXITCODE -eq 0)
}
if (-not $BackendImportsReady) {
    Write-Host "⚠️  后端依赖有更新或不完整，正在同步到 .venv..." -ForegroundColor Yellow
    & "$VenvPython" -m pip install -r "$RequirementsFile"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ 后端依赖安装失败，请手动执行: $VenvPython -m pip install -r backend/requirements.txt" -ForegroundColor Red
        exit 1
    }
    & "$VenvPython" -c "import aiosqlite, dotenv, fastapi, jsonschema, multipart, pydantic, pydantic_settings, pymupdf, requests, sqlite3, sqlite_vec, uvicorn; c=sqlite3.connect(':memory:'); c.enable_load_extension(True); sqlite_vec.load(c); assert c.execute('select vec_version()').fetchone()[0]" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ 后端依赖安装后仍无法导入，请检查上方 pip 输出" -ForegroundColor Red
        exit 1
    }
    Set-Content -LiteralPath $RequirementsStamp -Value $RequirementsHash -Encoding Ascii -NoNewline
}
Write-Host "   ✅ 后端依赖已就绪" -ForegroundColor Green

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

# Windows 后台服务固定单 worker：Uvicorn 的 Windows multiprocess supervisor 会处理并
# 向 spawn workers 转发 console signals；某些 IDE task runner 会对后台子树发送 Ctrl+C，
# 导致所有 workers 在启动期一起退出。单 async worker 仍可并发处理 I/O，并减少 SQLite
# 单写锁竞争。显式 -ShowTerminals 时保留多 worker 调试/压测能力。
$IsWindowsRuntime = ($env:OS -eq "Windows_NT")
if ($IsWindowsRuntime -and $UseBackground) {
    $Workers = 1
    if ($ApiWorkers -gt 1) {
        Write-Host "   ⚠️ Windows 后台模式为稳定性固定使用 1 worker；-ApiWorkers $ApiWorkers 已忽略。多 worker 请使用 -ShowTerminals。" -ForegroundColor Yellow
    }
} elseif ($ApiWorkers -gt 0) {
    $Workers = $ApiWorkers
} else {
    $Workers = [Math]::Min((& "$VenvPython" -c "import os; print(min(os.cpu_count() or 1, 4))"), 4)
}

# 端口占用检测：WinError 10013 的主要根因是端口被残留实例/其他程序占用，
# Windows 对「绑定已被独占的端口」报 10013（访问权限不允许）而非 10048（端口占用）。
function Get-PortListener {
    param([int]$Port)
    return Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

# 启动器 stdout/stderr 日志轮转：超 10MB 后保留最近 5 份。
# 应用自身的 app/error/access 日志由 Python logging 按日轮转。
function Rotate-Log {
    param([string]$Path)
    if ((Test-Path -LiteralPath $Path) -and ((Get-Item -LiteralPath $Path).Length -gt 10MB)) {
        if (Test-Path -LiteralPath "$Path.5") {
            Remove-Item -LiteralPath "$Path.5" -Force
        }
        for ($index = 4; $index -ge 1; $index--) {
            $source = "$Path.$index"
            if (Test-Path -LiteralPath $source) {
                Move-Item -LiteralPath $source -Destination "$Path.$($index + 1)" -Force
            }
        }
        Move-Item -LiteralPath $Path -Destination "$Path.1" -Force
    }
}

# 真正的无控制台后台进程。Start-Process -WindowStyle Hidden 只隐藏窗口，进程仍可能
# 继承启动终端的 console，在 IDE 结束任务或终端发送 Ctrl+C 时收到 SIGINT。
# cmd.exe 作为稳定包装进程等待实际服务；CreateNoWindow 则把整棵子进程树从 console
# 控制事件中隔离。Command 的 stdout/stderr 必须由调用方重定向到文件。
function Start-NoConsoleCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $env:ComSpec
    $startInfo.Arguments = "/d /s /c $Command"
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    return [System.Diagnostics.Process]::Start($startInfo)
}

# 重启模式：先结束后端+前端旧进程，再以最新代码启动
if ($Restart) {
    Write-Host "`n🔄 重启模式：清理旧进程..." -ForegroundColor Yellow

    # 结束后端
    if (-not $SkipBackend) {
        $beListener = Get-PortListener -Port $ApiPort
        if ($beListener) {
            $bePid = $beListener.OwningProcess
            $beName = (Get-Process -Id $bePid -ErrorAction SilentlyContinue).ProcessName
            Write-Host "   🔄 结束后端进程 $beName (PID $bePid)..." -ForegroundColor Yellow
            taskkill /PID $bePid /T /F | Out-Null
            $waited = 0
            while ($waited -lt 15 -and (Get-PortListener -Port $ApiPort)) {
                Start-Sleep -Milliseconds 500
                $waited++
            }
            if (Get-PortListener -Port $ApiPort) {
                Write-Host "   ⚠️ 后端进程结束超时，端口 $ApiPort 仍被占用" -ForegroundColor Red
            } else {
                Write-Host "   ✅ 后端已停止 (耗时约 $([Math]::Round($waited * 0.5, 1))s)" -ForegroundColor Green
            }
        } else {
            Write-Host "   ℹ️ 后端未在运行（端口 $ApiPort 空闲）" -ForegroundColor Gray
        }
    }

    # 结束前端
    if (-not $SkipFrontend) {
        $feListener = Get-PortListener -Port $FrontendPort
        if ($feListener) {
            $fePid = $feListener.OwningProcess
            $feName = (Get-Process -Id $fePid -ErrorAction SilentlyContinue).ProcessName
            Write-Host "   🔄 结束前端进程 $feName (PID $fePid)..." -ForegroundColor Yellow
            taskkill /PID $fePid /T /F | Out-Null
            $waited = 0
            while ($waited -lt 15 -and (Get-PortListener -Port $FrontendPort)) {
                Start-Sleep -Milliseconds 500
                $waited++
            }
            if (Get-PortListener -Port $FrontendPort) {
                Write-Host "   ⚠️ 前端进程结束超时，端口 $FrontendPort 仍被占用" -ForegroundColor Red
            } else {
                Write-Host "   ✅ 前端已停止 (耗时约 $([Math]::Round($waited * 0.5, 1))s)" -ForegroundColor Green
            }
        } else {
            Write-Host "   ℹ️ 前端未在运行（端口 $FrontendPort 空闲）" -ForegroundColor Gray
        }
    }

    Write-Host "   ✅ 旧进程已清理，即将以最新代码重启`n" -ForegroundColor Green
}

# 跨端口重复实例预检：同端口残留由下方端口检查处理；这里查心跳文件，
# 发现**其它端口**仍有活着的后端在用同一数据目录 → 直接 abort。
# （双后端共享同一 SQLite 是慢性锁竞争之源，reindex 500 事故根因。）
if (-not $SkipBackend) {
    $hbFile = "$DataDir\.backend_supervisors.json"
    if (Test-Path $hbFile) {
        try {
            $hb = Get-Content -LiteralPath $hbFile -Raw -ErrorAction Stop | ConvertFrom-Json
            $nowMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
            $liveForeign = @()
            foreach ($prop in ($hb.PSObject.Properties)) {
                if ([int]$prop.Value.port -eq $ApiPort) { continue }  # 同端口走下方端口逻辑（复用/重启）
                $ageSec = ($nowMs - [long]$prop.Value.updatedAt) / 1000
                if ($ageSec -gt 120) { continue }  # 心跳过期 = 已死，忽略
                $alive = Get-Process -Id ([int]$prop.Name) -ErrorAction SilentlyContinue
                if ($alive) {
                    $liveForeign += "supervisor PID $($prop.Name)（端口 $($prop.Value.port)，$([Math]::Round($ageSec))s 前心跳）"
                }
            }
            if ($liveForeign.Count -gt 0) {
                Write-Host "   ❌ 检测到其它后端实例正在使用同一数据目录 ($DataDir):" -ForegroundColor Red
                $liveForeign | ForEach-Object { Write-Host "      - $_" -ForegroundColor Red }
                Write-Host "      双后端共享 SQLite 必然导致 database is locked。请先停掉它们再启动。" -ForegroundColor Yellow
                Write-Host "      可按上述 PID 逐个结束，或直接复用已有实例（前端 proxy 指向其端口）。" -ForegroundColor Yellow
                exit 1
            }
        } catch {
            # 心跳文件损坏/不可读：忽略，按无残留继续（后端启动后会重写）
        }
    }
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
    if ($UseBackground) {
        if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
        Rotate-Log "$LogDir\backend.log"
        Rotate-Log "$LogDir\backend.err.log"
        # Windows venv 的 python.exe 是 redirector，外层 cmd.exe 同步等待真正的 Uvicorn；
        # PID 文件因此稳定指向可用于 taskkill /T 的完整后端进程树。
        if ($IsWindowsRuntime) {
            $backendCommand = '""{0}" -m backend.server.windows_daemon --port {1} 1>>"{2}" 2>>"{3}""' -f $VenvPython, $ApiPort, "$LogDir\backend.log", "$LogDir\backend.err.log"
        } else {
            $backendCommand = '""{0}" -m uvicorn backend.server.main:app --port {1} --workers {2} 1>>"{3}" 2>>"{4}""' -f $VenvPython, $ApiPort, $Workers, "$LogDir\backend.log", "$LogDir\backend.err.log"
        }
        $beProc = Start-NoConsoleCommand -Command $backendCommand -WorkingDirectory $ProjectDir
        Set-Content -LiteralPath "$LogDir\backend.pid" -Value $beProc.Id -Encoding Ascii -NoNewline
        Write-Host "   🔇 后台运行中 (PID $($beProc.Id)，日志: $LogDir\backend.log)" -ForegroundColor Gray
    } else {
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$ProjectDir'; & '$VenvPython' -m uvicorn backend.server.main:app --port $ApiPort --workers $Workers" -WindowStyle Normal
    }

    # 等待后端就绪（除非显式跳过 LLM 校验也仍等待健康检查）
    Write-Host "   ⏳ 等待后端就绪..." -ForegroundColor Gray
    $retries = 0
    $maxRetries = 40
    $connected = $false
    $backendExited = $false
    while ($retries -lt $maxRetries -and -not $connected) {
        Start-Sleep -Milliseconds 500
        if ($UseBackground -and $beProc.HasExited) {
            $backendExited = $true
            break
        }
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:$ApiPort/api/healthz" -UseBasicParsing -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) { $connected = $true }
        } catch {}
        $retries++
    }
    if ($connected) {
        Write-Host "   ✅ 后端已就绪 (http://localhost:$ApiPort)" -ForegroundColor Green
    } elseif ($backendExited) {
        $backendExitCode = "unknown"
        try {
            $beProc.WaitForExit()
            $backendExitCode = $beProc.ExitCode
        } catch {}
        Write-Host "   ❌ 后端进程在健康检查完成前退出 (exit code: $backendExitCode)" -ForegroundColor Red
        Write-Host "      错误日志: $LogDir\backend.err.log" -ForegroundColor Yellow
        if (Test-Path -LiteralPath "$LogDir\backend.err.log") {
            Get-Content -LiteralPath "$LogDir\backend.err.log" -Tail 20 | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
        }
        exit 1
    } else {
        $diagnosticTarget = if ($UseBackground) { "$LogDir\backend.err.log" } else { "后端窗口日志" }
        Write-Host "   ⚠️  后端启动中或健康检查失败，请查看 $diagnosticTarget" -ForegroundColor Yellow
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
    if ($UseBackground) {
        if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
        Rotate-Log "$LogDir\frontend.log"
        Rotate-Log "$LogDir\frontend.err.log"
        $npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
        if (-not $npmCmd) { $npmCmd = "npm" }
        $frontendCommand = '""{0}" run dev -- --port {1} 1>>"{2}" 2>>"{3}""' -f $npmCmd, $FrontendPort, "$LogDir\frontend.log", "$LogDir\frontend.err.log"
        $feProc = Start-NoConsoleCommand -Command $frontendCommand -WorkingDirectory "$ProjectDir\frontend"
        Set-Content -LiteralPath "$LogDir\frontend.pid" -Value $feProc.Id -Encoding Ascii -NoNewline
        Write-Host "   🔇 后台运行中 (PID $($feProc.Id)，日志: $LogDir\frontend.log)" -ForegroundColor Gray
    } else {
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$ProjectDir\frontend'; npm run dev -- --port $FrontendPort" -WindowStyle Normal
    }
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
   - 查看设计文档: .\docs\SYSTEM-DESIGN.md
   - 停止服务: .\stop.ps1（-ShowTerminals 模式也可在服务窗口按 Ctrl+C）
"@ -ForegroundColor Green

if ($UseBackground) {
    Write-Host @"

🔇 后台模式已启用（无新终端）：
   后端日志: $LogDir\backend.log
   后端错误: $LogDir\backend.err.log
   前端日志: $LogDir\frontend.log
   前端错误: $LogDir\frontend.err.log
   停止服务: .\stop.ps1
   实时跟踪: Get-Content $LogDir\backend.log -Wait -Tail 50
"@ -ForegroundColor Yellow
}
