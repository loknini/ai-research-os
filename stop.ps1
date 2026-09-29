# AI-Research-OS 停止脚本（配合 start.ps1 默认后台模式使用；-ShowTerminals 模式可直接关窗口）
#
# 用法:
#   .\stop.ps1                  # 按 pid 文件精准停止，无则按端口兜底
#   .\stop.ps1 -ApiPort 9000    # 后端用了自定义端口时保持一致
#
# 说明:
#   - 优先读 logs\state\*.pid 精准结束（taskkill /T 连子进程树一起，避免 npm 残留 node/vite 孤儿）；
#   - pid 文件缺失/过期时回退到端口探测（与 start.ps1 同一逻辑）；
#   - 只动本应用进程：pid 对不上 python/node/uvicorn 时跳过并提示手动处理。

param(
    [int]$ApiPort = 8000,
    [int]$FrontendPort = 5173,
    [string]$LogDir = ""
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectDir = $PSScriptRoot
if (-not $LogDir) {
    $LogDir = "$ProjectDir\logs"
}
if (-not [System.IO.Path]::IsPathRooted($LogDir)) {
    $LogDir = Join-Path $ProjectDir $LogDir
}
$LogDir = [System.IO.Path]::GetFullPath($LogDir)
$StateDir = Join-Path $LogDir "state"
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

function Get-PortListener {
    param([int]$Port)
    return Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Stop-ByPidFile {
    param([string]$Name, [string]$PidFile, [string]$ExpectedProcess)
    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $false
    }
    $pidValue = (Get-Content -LiteralPath $PidFile -Raw -ErrorAction SilentlyContinue).Trim()
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    $pidInt = 0
    if (-not [int]::TryParse($pidValue, [ref]$pidInt)) {
        Write-Host "   ⚠️ $Name pid 文件内容非法，已清理" -ForegroundColor Yellow
        return $false
    }
    $proc = Get-Process -Id $pidInt -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Host "   ℹ️ $Name (PID $pidInt) 已不在运行" -ForegroundColor Gray
        return $true
    }
    # PID 可能被系统回收复用：只对本应用进程下手
    if ($proc.ProcessName -notmatch $ExpectedProcess) {
        Write-Host "   ⚠️ PID $pidInt 现为 $($proc.ProcessName)，疑似已复用，跳过（请手动确认）" -ForegroundColor Yellow
        return $false
    }
    Write-Host "   🔄 停止 $Name (PID $pidInt)..." -ForegroundColor Yellow
    taskkill /PID $pidInt /T /F 2>$null | Out-Null
    $waited = 0
    while ($waited -lt 30 -and (Get-Process -Id $pidInt -ErrorAction SilentlyContinue)) {
        Start-Sleep -Milliseconds 200
        $waited++
    }
    return $true
}

function Stop-ByPort {
    param([string]$Name, [int]$Port, [string]$ExpectedProcess)
    $listener = Get-PortListener -Port $Port
    if (-not $listener) {
        Write-Host "   ℹ️ $Name 未在运行（端口 $Port 空闲）" -ForegroundColor Gray
        return
    }
    $occPid = $listener.OwningProcess
    $occName = (Get-Process -Id $occPid -ErrorAction SilentlyContinue).ProcessName
    if ($occName -notmatch $ExpectedProcess) {
        Write-Host "   ⚠️ 端口 $Port 由 $occName (PID $occPid) 占用，无法确认属于本应用，已跳过" -ForegroundColor Yellow
        return
    }
    Write-Host "   🔄 端口 $Port 仍有 $occName (PID $occPid)，正在结束..." -ForegroundColor Yellow
    taskkill /PID $occPid /T /F 2>$null | Out-Null
    $waited = 0
    while ($waited -lt 15 -and (Get-PortListener -Port $Port)) {
        Start-Sleep -Milliseconds 500
        $waited++
    }
    if (Get-PortListener -Port $Port) {
        Write-Host "   ❌ 端口 $Port 仍被占用，请手动处理: taskkill /PID $occPid /T /F" -ForegroundColor Red
    } else {
        Write-Host "   ✅ $Name 已停止" -ForegroundColor Green
    }
}

Write-Host "`n🛑 停止 AI-Research-OS..." -ForegroundColor Yellow

$backendPidFile = if (Test-Path -LiteralPath "$StateDir\backend.pid") { "$StateDir\backend.pid" } else { "$LogDir\backend.pid" }
$frontendPidFile = if (Test-Path -LiteralPath "$StateDir\frontend.pid") { "$StateDir\frontend.pid" } else { "$LogDir\frontend.pid" }
$beStopped = Stop-ByPidFile "后端" $backendPidFile '^(cmd|python|uvicorn|powershell|pwsh)$'
$feStopped = Stop-ByPidFile "前端" $frontendPidFile '^(node|npm|cmd)$'

# pid 文件缺失/过期/复用时，用端口兜底（-Restart 杀不干净的重灾区）
if (-not $beStopped) { Stop-ByPort "后端" $ApiPort '^(python|uvicorn)$' }
if (-not $feStopped) { Stop-ByPort "前端" $FrontendPort '^(node|npm)$' }

# 进程树退出后，把所有已退出 Worker 的 PID 日志按日期归档。
if (Test-Path -LiteralPath $VenvPython) {
    & $VenvPython -m backend.server.core.log_maintenance prepare --log-dir "$LogDir" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   ⚠️ 服务已停止，但日志归档失败；可稍后手动运行维护命令" -ForegroundColor Yellow
    }
}

Write-Host "`n✅ 停止完成" -ForegroundColor Green
