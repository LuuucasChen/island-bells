#!/usr/bin/env bash
# 岛屿铃钱记 — 生产启动脚本 (SQLite 模式)
# 用法: ./deploy/start.sh

set -e

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$APP_DIR/backend"
WEB_DIR="$APP_DIR/web"

echo "======================================"
echo "  岛屿铃钱记 — 生产部署 (SQLite)"
echo "======================================"

# ---------- 1. 后端依赖 ----------
echo "[1/4] 安装后端依赖..."
cd "$BACKEND_DIR"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt

# ---------- 2. 前端构建 ----------
echo "[2/4] 构建前端..."
cd "$WEB_DIR"

if ! command -v node &> /dev/null; then
    echo "❌ 未检测到 Node.js，请安装 Node.js 18+ 后重试"
    exit 1
fi

npm install --production=false
npm run build
echo "✅ 前端构建完成 → web/dist/"

# ---------- 3. 初始化数据库 ----------
echo "[3/4] 初始化 SQLite 数据库..."
cd "$BACKEND_DIR"
source venv/bin/activate
export DATABASE_URL="sqlite:///./data/island_bells.db"

# 创建数据目录
mkdir -p data

python3 -c "
import os
os.environ['DATABASE_URL'] = 'sqlite:///./data/island_bells.db'
from app.database import Base, engine
from app.models import User, Room, RoomPlayer, Hand, Bet, Pot, HandResult, Rebuy
Base.metadata.create_all(bind=engine)
print('✅ 数据库表已就绪')
"

# ---------- 4. 启动服务 ----------
echo "[4/4] 启动后端服务..."
echo "  API:     http://0.0.0.0:8000"
echo "  API文档: http://0.0.0.0:8000/docs"
echo "  前端:    由 Nginx 提供 web/dist/ 静态文件"
echo ""

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info
