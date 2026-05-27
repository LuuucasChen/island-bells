"""岛屿铃钱记 — FastAPI 应用入口"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.v1 import auth, room, game, history
from app.api.ws import game_ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown


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
