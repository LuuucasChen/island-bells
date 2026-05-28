"""岛屿铃钱记 — FastAPI 应用入口"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.api.v1 import auth, room, game, history
from app.api.ws import game_ws
# 导入所有模型，确保 SQLAlchemy 知道它们的存在
from app.models import User, Room, RoomPlayer, Hand, Bet, Pot, HandResult, Rebuy  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时自动建表（如果不存在）
    Base.metadata.create_all(bind=engine)
    yield
    # 关闭时清理资源


app = FastAPI(
    title="岛屿铃钱记",
    description="线下卡牌游戏铃钱管理工具后端 API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API 路由
app.include_router(auth.router, prefix="/v1/auth", tags=["认证"])
app.include_router(room.router, prefix="/v1/rooms", tags=["岛屿"])
app.include_router(game.router, prefix="/v1", tags=["游戏"])
app.include_router(history.router, prefix="/v1", tags=["历史"])

# WebSocket 路由
app.include_router(game_ws.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "岛屿铃钱记"}
