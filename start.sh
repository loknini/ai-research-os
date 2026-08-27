#!/usr/bin/env bash
#
# AI-Research-OS 启动脚本（macOS / Linux 版，镜像 start.ps1）
#
# 用法:
#   ./start.sh                                # 启动 FastAPI 后端 + 前端开发服务器
#   ./start.sh --skip-frontend                # 仅起后端
#   ./start.sh --skip-backend                 # 仅起前端
#   ./start.sh --api-port 9000                # 自定义后端端口
#   ./start.sh --api-workers 4                # 指定 FastAPI worker 进程数（多 worker 抗并发）
#   ./start.sh --data-dir ~/Sync/airos-data  # 把 DATA_DIR 指到同步盘（双设备单数据源）
#   ./start.sh --restart                     # 重启模式：结束后端+前端（如正在运行）后重新启动
#
# 说明:
#   - 与 Windows 版 start.ps1 行为对齐；兼容 bash 3.2（macOS 默认 /bin/bash）。
#   - 仅使用 POSIX + bash 3.2 特性（无关联数组 / readarray / bash4 专属语法）。
#   - FastAPI 后端（uvicorn backend.server.main:app）为核心，默认启动。
#   - 后端以多 worker 进程运行（--workers N，默认 min(CPU, 8)），提升并发与健壮性；
#     不使用 --reload（生产式常驻）。
#   - 前端开发服务器通过 Vite 反代 /api -> 后端（默认 :8000）。
#   - LLM 配置：在前端「设置 → LLM API 配置」中填写，写入项目根 .env。
#   - 首次运行会自动创建项目根 .venv；每次启动按 requirements 指纹检查依赖，
#     有变化或缺失时同步进 .venv，不污染系统全局 Python。

# 用脚本所在目录推导项目根目录（禁止硬编码绝对路径）
SOURCE="${BASH_SOURCE[0]}"
PROJECT_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"

# ---- 默认参数 ----
API_PORT=8000
FRONTEND_PORT=5173
SKIP_FRONTEND=""
SKIP_BACKEND=""
DATA_DIR_ARG=""
API_WORKERS=""   # 手动指定的 worker 数；留空则自动探测 min(cpu_count, 8)
RESTART=""       # 重启模式：结束后端+前端旧进程后以最新代码重新启动

# ---- 帮助信息 ----
print_help() {
  cat <<'EOF'
AI-Research-OS 启动脚本（macOS / Linux）

用法:
  ./start.sh [选项]

选项:
  -d, --data-dir <path>      把后端数据目录 DATA_DIR 指到指定路径（如 Syncthing 同步盘）。
                             优先级: 命令行 -d > 项目根 .airos-data-dir 文件 > 已有环境变量
                             DATA_DIR > 默认 <项目根>/data。后端会在该目录自动建库建表。
  -s, --skip-frontend        不启动前端开发服务器（仅起后端）。
  -b, --skip-backend         不启动后端（仅起前端；核心功能需另行提供 /api）。
  -p, --api-port <port>      后端端口（默认 8000）。
  -w, --api-workers <n>      FastAPI worker 进程数（默认自动探测 min(CPU, 8)）。
  -f, --frontend-port <port> 前端端口（默认 5173）。
  -r, --restart              重启模式：结束后端+前端（如正在运行）后以最新代码重新启动。
  -h, --help                 显示本帮助并退出。

示例:
  ./start.sh --data-dir ~/Sync/airos-data         # 双设备单数据源：数据放在同步盘
  ./start.sh --skip-frontend --api-port 9000       # 仅起后端，用自定义端口
  ./start.sh --restart                             # 重启后端+前端

提示: 也可把数据目录路径写进项目根 .airos-data-dir 文件（首行即路径），
      之后直接 ./start.sh 即可，无需每次传 --data-dir。
EOF
}

# ---- 长选项转短选项（bash 3.2 的 getopts 不支持长选项，这里先做一层翻译）----
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --data-dir)         ARGS+=("-d" "$2"); shift 2;;
    --data-dir=*)       ARGS+=("-d" "${1#*=}"); shift;;
    --skip-frontend)    ARGS+=("-s"); shift;;
    --skip-backend)     ARGS+=("-b"); shift;;
    --api-port)         ARGS+=("-p" "$2"); shift 2;;
    --api-port=*)       ARGS+=("-p" "${1#*=}"); shift;;
    --api-workers)      ARGS+=("-w" "$2"); shift 2;;
    --api-workers=*)    ARGS+=("-w" "${1#*=}"); shift;;
    --frontend-port)    ARGS+=("-f" "$2"); shift 2;;
    --frontend-port=*)  ARGS+=("-f" "${1#*=}"); shift;;
    --restart)          ARGS+=("-r"); shift;;
    --help)             ARGS+=("-h"); shift;;
    *)                  ARGS+=("$1"); shift;;
  esac
done
set -- "${ARGS[@]}"

# ---- POSIX getopts 解析短选项 ----
while getopts ":d:sbp:f:w:rh" opt; do
  case "$opt" in
    d) DATA_DIR_ARG="$OPTARG";;
    s) SKIP_FRONTEND=1;;
    b) SKIP_BACKEND=1;;
    p) API_PORT="$OPTARG";;
    f) FRONTEND_PORT="$OPTARG";;
    w) API_WORKERS="$OPTARG";;
    r) RESTART=1;;
    h) print_help; exit 0;;
    \?) echo "未知选项: -$OPTARG" >&2; print_help; exit 1;;
    :)  echo "选项 -$OPTARG 需要一个参数" >&2; exit 1;;
  esac
done

# ---- 数据目录解析（优先级: -d > .airos-data-dir 文件 > 已有 $DATA_DIR 环境变量 > 默认）----
if [ -n "$DATA_DIR_ARG" ]; then
  RESOLVED_DATA_DIR="$DATA_DIR_ARG"
elif [ -f "$PROJECT_DIR/.airos-data-dir" ]; then
  # 读取首行作为路径；剔除 Windows 换行符 \r 与首尾空白
  RESOLVED_DATA_DIR="$(head -n 1 "$PROJECT_DIR/.airos-data-dir" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
elif [ -n "${DATA_DIR:-}" ]; then
  RESOLVED_DATA_DIR="$DATA_DIR"
else
  RESOLVED_DATA_DIR="$PROJECT_DIR/data"
fi
export DATA_DIR="$RESOLVED_DATA_DIR"

# ---- 虚拟环境隔离 ----
VENV_DIR="$PROJECT_DIR/.venv"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"   # 项目内虚拟环境解释器（即 .venv/bin/python）
REQUIREMENTS_FILE="$PROJECT_DIR/backend/requirements.txt"
REQUIREMENTS_STAMP="$VENV_DIR/.airos-requirements.sha256"

echo "AI-Research-OS"
echo "AI-Powered Research & Development Workbench"
echo ""
echo "检查环境..."

# 首次启动：若不存在 .venv，用系统 python3 创建虚拟环境（仅此一次）
if [ ! -x "$VENV_PYTHON" ]; then
  echo "未发现项目虚拟环境 .venv，正在创建（仅此一次使用系统 python3）..."
  if ! command -v python3 >/dev/null 2>&1; then
    echo "未找到 python3，请先安装 Python 3" >&2
    exit 1
  fi
  python3 -m venv "$VENV_DIR" || { echo "创建虚拟环境失败，请确认 python3 可用且支持 venv 模块" >&2; exit 1; }
  echo "  已创建虚拟环境: $VENV_DIR"
else
  echo "  虚拟环境已就绪: $VENV_DIR"
fi

# requirements.txt 内容变化或直接依赖缺失时同步 .venv。
# 不能只检查 uvicorn：已有虚拟环境可能缺少后来新增的 jsonschema 等依赖。
REQUIREMENTS_HASH=$("$VENV_PYTHON" -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$REQUIREMENTS_FILE")
INSTALLED_REQUIREMENTS_HASH=$(cat "$REQUIREMENTS_STAMP" 2>/dev/null || true)
BACKEND_IMPORTS_READY=""
if [ "$REQUIREMENTS_HASH" = "$INSTALLED_REQUIREMENTS_HASH" ] && \
   "$VENV_PYTHON" -c "import aiosqlite, dotenv, fastapi, jsonschema, multipart, pydantic, pydantic_settings, pypdf, requests, uvicorn" >/dev/null 2>&1; then
  BACKEND_IMPORTS_READY=1
fi
if [ -z "$BACKEND_IMPORTS_READY" ]; then
  echo "后端依赖有更新或不完整，正在同步到 .venv..."
  "$VENV_PYTHON" -m pip install -r "$REQUIREMENTS_FILE" || {
    echo "后端依赖安装失败，请手动执行: $VENV_PYTHON -m pip install -r backend/requirements.txt" >&2
    exit 1
  }
  "$VENV_PYTHON" -c "import aiosqlite, dotenv, fastapi, jsonschema, multipart, pydantic, pydantic_settings, pypdf, requests, uvicorn" >/dev/null 2>&1 || {
    echo "后端依赖安装后仍无法导入，请检查上方 pip 输出" >&2
    exit 1
  }
  printf '%s' "$REQUIREMENTS_HASH" > "$REQUIREMENTS_STAMP"
fi
echo "  后端依赖已就绪"

# 前端依赖
if [ -z "$SKIP_FRONTEND" ]; then
  if [ ! -d "$PROJECT_DIR/frontend/node_modules" ]; then
    echo "前端依赖未安装，正在安装..."
    ( cd "$PROJECT_DIR/frontend" && npm install ) || { echo "前端依赖安装失败" >&2; exit 1; }
  fi
  echo "  前端依赖已就绪"
fi

# 确保数据目录存在
mkdir -p "$DATA_DIR" || { echo "无法创建数据目录: $DATA_DIR" >&2; exit 1; }
echo "  数据目录已就绪: $DATA_DIR"

# 日志文件
BACKEND_LOG="$PROJECT_DIR/.airos-backend.log"
FRONTEND_LOG="$PROJECT_DIR/.airos-frontend.log"

# ---- 后台子进程管理（clean shutdown）----
PIDS=""

# 递归杀掉进程及其所有子进程（处理 uvicorn --reload / npm run dev 的子树）
kill_tree() {
  local pid="$1"
  local sig="$2"
  local children
  children="$(pgrep -P "$pid" 2>/dev/null)"
  for child in $children; do
    kill_tree "$child" "$sig"
  done
  kill "-$sig" "$pid" 2>/dev/null
}

# 按端口号查找并杀掉监听进程（重启模式用）
kill_port() {
  local port="$1"
  local label="$2"
  local pids=""

  # 优先 lsof（macOS 自带，Linux 大多也有）
  if command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  fi

  # fallback: fuser（部分 Linux）
  if [ -z "$pids" ] && command -v fuser >/dev/null 2>&1; then
    pids=$(fuser "tcp/${port}" 2>/dev/null | sed 's/[^0-9 ]//g' | tr -s ' ' '\n' | grep -v '^$' | tr '\n' ' ' || true)
  fi

  if [ -n "$pids" ]; then
    echo "  重启: 结束 $label (端口 $port, PID: $pids)..."
    for pid in $pids; do
      kill_tree "$pid" TERM
    done
    sleep 1
    for pid in $pids; do
      kill_tree "$pid" KILL 2>/dev/null
    done
    # 等待端口释放
    local waited=0
    while [ $waited -lt 15 ]; do
      local still=""
      if command -v lsof >/dev/null 2>&1; then
        still=$(lsof -ti tcp:"$port" 2>/dev/null || true)
      fi
      [ -z "$still" ] && break
      sleep 0.5
      waited=$((waited + 1))
    done
    echo "  $label 已停止"
    return 0
  else
    echo "  $label 未在运行（端口 $port 空闲）"
    return 1
  fi
}

cleanup() {
  echo ""
  echo "收到停止信号，正在关闭服务..."
  for pid in $PIDS; do
    kill_tree "$pid" TERM
  done
  sleep 1
  for pid in $PIDS; do
    kill_tree "$pid" KILL
  done
  echo "已退出。"
  exit 0
}
trap cleanup SIGINT SIGTERM

# 重启模式：先结束后端+前端旧进程，再以最新代码启动
if [ -n "$RESTART" ]; then
  echo ""
  echo "重启模式：清理旧进程..."

  if [ -z "$SKIP_BACKEND" ]; then
    kill_port "$API_PORT" "后端"
  fi

  if [ -z "$SKIP_FRONTEND" ]; then
    kill_port "$FRONTEND_PORT" "前端"
  fi

  echo "  旧进程已清理，即将以最新代码重启"
fi

echo ""
echo "启动服务..."

# 多 worker：优先使用 --api-workers，否则自动探测 min(cpu_count, 8)
if [ -n "$API_WORKERS" ]; then
  WORKERS="$API_WORKERS"
else
  WORKERS=$( "$VENV_PYTHON" -c "import os; print(min(os.cpu_count() or 1, 8))" )
fi

# 启动 FastAPI 后端（使用 .venv 解释器，多 worker 常驻）
if [ -z "$SKIP_BACKEND" ]; then
  echo "  启动 FastAPI 后端 (端口: $API_PORT, workers: $WORKERS)..."
  ( cd "$PROJECT_DIR" && "$VENV_PYTHON" -m uvicorn backend.server.main:app --port "$API_PORT" --workers "$WORKERS" ) >> "$BACKEND_LOG" 2>&1 &
  PIDS="$PIDS $!"
fi

# 启动前端开发服务器
if [ -z "$SKIP_FRONTEND" ]; then
  echo "  启动前端开发服务器 (端口: $FRONTEND_PORT)..."
  ( cd "$PROJECT_DIR/frontend" && npm run dev -- --port "$FRONTEND_PORT" ) >> "$FRONTEND_LOG" 2>&1 &
  PIDS="$PIDS $!"
fi

# 健康检查（轮询 /api/healthz）
if [ -z "$SKIP_BACKEND" ]; then
  echo "  等待后端就绪..."
  HEALTH_URL="http://127.0.0.1:${API_PORT}/api/healthz"
  RETRIES=0
  MAX_RETRIES=40
  CONNECTED=0
  while [ "$RETRIES" -lt "$MAX_RETRIES" ] && [ "$CONNECTED" -eq 0 ]; do
    if curl -s -o /dev/null -m 2 "$HEALTH_URL"; then
      CONNECTED=1
    else
      RETRIES=$((RETRIES + 1))
      sleep 0.5
    fi
  done
  if [ "$CONNECTED" -eq 1 ]; then
    echo "  后端已就绪 ($HEALTH_URL)"
  else
    echo "  后端启动中或健康检查失败，请查看日志: $BACKEND_LOG"
  fi
fi

echo ""
echo "服务启动完成！"
echo ""
echo "访问地址:"
echo "  前端界面:     http://localhost:$FRONTEND_PORT"
echo "  后端 API:     http://localhost:$API_PORT/api"
echo "  API 文档:     http://localhost:$API_PORT/docs"
echo "  健康检查:     http://localhost:$API_PORT/api/healthz"
echo ""
echo "项目目录: $PROJECT_DIR"
echo "数据目录: $DATA_DIR"
echo "后端环境: $VENV_DIR (虚拟环境，不污染全局 Python)"
echo ""
echo "提示:"
echo "  - 配置 LLM：打开前端「设置 -> LLM API 配置」填写"
echo "  - 数据备份与迁移：打开前端「设置 -> 数据备份与迁移」卡片"
echo "  - 查看设计文档: $PROJECT_DIR/docs/SYSTEM-DESIGN.md"
echo "  - 按 Ctrl+C 停止所有服务（会清理后端 / 前端进程）"
echo ""

# 阻塞等待，交给 trap 处理 Ctrl+C / 终止信号
wait
