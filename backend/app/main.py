"""岛屿铃钱记 — FastAPI 应用入口"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine, SessionLocal
from app.api.v1 import auth, room, game, history
from app.api.ws import game_ws
from app.utils import activity_tracker
# 导入所有模型，确保 SQLAlchemy 知道它们的存在
from app.models import User, Room, RoomPlayer, Hand, Bet, Pot, HandResult, Rebuy  # noqa: F401


# 死牌局阈值：5 分钟无玩家下注行动则自动结束房间
DEAD_ROOM_TIMEOUT = timedelta(minutes=5)
# 清理扫描间隔
DEAD_ROOM_SCAN_INTERVAL = 30  # 秒


async def _dead_room_cleaner() -> None:
    """后台任务：定期扫描活跃度表，自动结束超过 5 分钟无行动的牌局。"""
    # 延迟导入避免循环依赖
    from app.api.v1.game import _finish_room_impl

    while True:
        try:
            now = datetime.now(timezone.utc)
            for room_id, last in activity_tracker.snapshot().items():
                if now - last < DEAD_ROOM_TIMEOUT:
                    continue
                db = SessionLocal()
                try:
                    room = db.query(Room).filter(Room.id == room_id).first()
                    if room is None or room.status != "playing":
                        # 房间不存在或已不在进行中，直接从表中移除
                        activity_tracker.remove(room_id)
                        continue
                    await _finish_room_impl(db, room, reason="dead_room_timeout")
                    logging.info("[dead_room_cleaner] 房间 %s 超时自动结束", room_id)
                finally:
                    db.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            # 单次异常不允许中断后台任务
            logging.exception("[dead_room_cleaner] 扫描异常")
        await asyncio.sleep(DEAD_ROOM_SCAN_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时自动建表（如果不存在）
    Base.metadata.create_all(bind=engine)
    # 启动死牌局后台清理任务
    cleaner_task = asyncio.create_task(_dead_room_cleaner())
    try:
        yield
    finally:
        cleaner_task.cancel()
        try:
            await cleaner_task
        except (asyncio.CancelledError, Exception):
            pass


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
