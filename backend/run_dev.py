"""岛屿铃钱记 — 本地开发启动脚本 (SQLite 模式)

无需 Docker/MySQL，直接用 SQLite 启动后端
仅用于开发演示，生产环境请使用 deploy/start_prod.sh

用法: python run_dev.py
"""

import os

# 设置环境变量，让 database.py 使用 SQLite
os.environ["APP_ENV"] = "dev"
os.environ["DATABASE_URL"] = "sqlite:///./dev.db"

# 必须在 import app 之前设置好环境变量
from app.database import engine  # noqa: F401
from app.main import app  # main.py lifespan 会自动建表

# SQLite 兼容：外键支持
from sqlalchemy import event


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


print()
print("=" * 50)
print("  岛屿铃钱记 — 开发服务器 (SQLite)")
print("  http://localhost:8000")
print("  API 文档: http://localhost:8000/docs")
print("=" * 50)
print()

import uvicorn

uvicorn.run(app, host="0.0.0.0", port=8000)
