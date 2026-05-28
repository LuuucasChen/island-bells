#!/bin/bash
# 岛屿铃钱记 — 生产环境启动脚本 (方案 B: MySQL Docker 容器 + 后端直接运行)
#
# 前置条件:
#   1. 安装 Docker
#   2. 安装 Python 3.11+ 和 pip
#   3. 复制 .env.example 为 .env 并修改密码
#
# 用法:
#   chmod +x start_prod.sh
#   ./start_prod.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")/backend"

echo "========================================"
echo "  岛屿铃钱记 — 生产环境启动"
echo "========================================"

# ========== 1. 启动 MySQL 容器 ==========
echo ""
echo "[1/4] 启动 MySQL 容器..."

# 检查容器是否已存在
if docker ps -a --format '{{.Names}}' | grep -q '^island_bells_mysql$'; then
    echo "  → MySQL 容器已存在，跳过创建"
    docker start island_bells_mysql 2>/dev/null || true
else
    # 从 .env 读取配置
    if [ -f "$SCRIPT_DIR/.env" ]; then
        source "$SCRIPT_DIR/.env"
    fi

    MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD:-tanukichi_root}
    MYSQL_PASSWORD=${MYSQL_PASSWORD:-nookring2024}
    MYSQL_DATABASE=${MYSQL_DATABASE:-island_bells}
    MYSQL_USER=${MYSQL_USER:-bells}

    docker run -d \
        --name island_bells_mysql \
        --restart unless-stopped \
        -p 3306:3306 \
        -e MYSQL_ROOT_PASSWORD="$MYSQL_ROOT_PASSWORD" \
        -e MYSQL_DATABASE="$MYSQL_DATABASE" \
        -e MYSQL_USER="$MYSQL_USER" \
        -e MYSQL_PASSWORD="$MYSQL_PASSWORD" \
        -v island_bells_data:/var/lib/mysql \
        mysql:8.0 \
        --character-set-server=utf8mb4 \
        --collation-server=utf8mb4_unicode_ci

    echo "  → MySQL 容器已创建，等待初始化..."
    sleep 10
fi

# ========== 2. 等待 MySQL 就绪 ==========
echo ""
echo "[2/4] 等待 MySQL 就绪..."
MAX_RETRIES=30
RETRY_COUNT=0
while ! docker exec island_bells_mysql mysqladmin ping -h localhost --silent 2>/dev/null; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "  ✗ MySQL 启动超时"
        exit 1
    fi
    echo "  → 等待中... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done
echo "  ✓ MySQL 已就绪"

# ========== 3. 安装 Python 依赖 ==========
echo ""
echo "[3/5] 安装 Python 依赖..."
cd "$BACKEND_DIR"
pip install -q -r requirements.txt

# ========== 4. 创建日志目录 ==========
echo ""
echo "[4/5] 初始化日志目录..."
LOG_DIR="$(dirname "$SCRIPT_DIR")/logs"
mkdir -p "$LOG_DIR"
chmod 755 "$LOG_DIR"
echo "  → 日志目录: $LOG_DIR"

# 安装日志轮转 cron (如未安装)
CRON_LINE="*/15 * * * * $SCRIPT_DIR/rotate_logs.sh"
if ! crontab -l 2>/dev/null | grep -qF "rotate_logs.sh"; then
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "  → 已安装日志轮转 cron (每15分钟)"
fi

# ========== 5. 启动后端服务 ==========
echo ""
echo "[5/5] 启动后端服务..."

# 加载环境变量
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# 确保设置了生产环境标识
export APP_ENV=prod

echo ""
echo "========================================"
echo "  ✓ 启动完成"
echo "  后端: http://0.0.0.0:8000"
echo "  API 文档: http://0.0.0.0:8000/docs"
echo "  数据库: MySQL (Docker 容器)"
echo "  日志: $LOG_DIR"
echo "========================================"
echo ""

# 启动 uvicorn (前台运行，可用 Ctrl+C 停止)
# 生产环境建议用 systemd 管理，参考 deploy/island-bells.service
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level warning --access-log
