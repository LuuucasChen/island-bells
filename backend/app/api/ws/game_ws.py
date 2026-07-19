"""岛屿铃钱记 — 游戏 WebSocket 处理器"""

import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Dict, Set

from app.database import SessionLocal
from app.models import RoomPlayer
from app.utils import activity_tracker
from app.utils.security import decode_token

logger = logging.getLogger(__name__)

router = APIRouter()

# 心跳超时: 客户端每 25s 发一次 ping，60s 内未收到任何消息视为死连接
_HEARTBEAT_TIMEOUT = 60


class ConnectionManager:
    """管理 WebSocket 连接，按房间分组"""

    def __init__(self):
        # room_id -> set of websocket connections
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        # websocket -> user_id
        self.ws_user_map: Dict[WebSocket, int] = {}

    async def connect(self, websocket: WebSocket, room_id: int, user_id: int):
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = set()
        self.active_connections[room_id].add(websocket)
        self.ws_user_map[websocket] = user_id

    def disconnect(self, websocket: WebSocket, room_id: int):
        if room_id in self.active_connections:
            self.active_connections[room_id].discard(websocket)
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]
        self.ws_user_map.pop(websocket, None)

    async def broadcast_to_room(self, room_id: int, message: dict):
        """向房间内所有连接广播消息"""
        if room_id in self.active_connections:
            data = json.dumps(message, ensure_ascii=False)
            dead = []
            # 用 list() 复制一份，避免迭代时 set 变化
            for ws in list(self.active_connections[room_id]):
                try:
                    await ws.send_text(data)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.disconnect(ws, room_id)

    async def send_to_user(self, room_id: int, user_id: int, message: dict):
        """向房间内特定用户发送消息"""
        if room_id in self.active_connections:
            data = json.dumps(message, ensure_ascii=False)
            for ws in self.active_connections[room_id]:
                if self.ws_user_map.get(ws) == user_id:
                    try:
                        await ws.send_text(data)
                    except Exception:
                        pass

    def get_room_users(self, room_id: int) -> list[int]:
        """获取房间内在线用户 ID 列表"""
        if room_id not in self.active_connections:
            return []
        return [self.ws_user_map[ws] for ws in self.active_connections[room_id] if ws in self.ws_user_map]


manager = ConnectionManager()


def authenticate_ws(token: str) -> int | None:
    """从 WebSocket 连接的 token 参数中验证用户身份"""
    payload = decode_token(token)
    if payload is None:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def _is_room_member(room_id: int, user_id: int) -> bool:
    """校验用户是否是房间活跃成员 (is_active=1 的 RoomPlayer 行)"""
    db = SessionLocal()
    try:
        return (
            db.query(RoomPlayer)
            .filter(
                RoomPlayer.room_id == room_id,
                RoomPlayer.user_id == user_id,
                RoomPlayer.is_active == 1,
            )
            .first()
            is not None
        )
    finally:
        db.close()


@router.websocket("/ws/rooms/{room_id}")
async def ws_game(websocket: WebSocket, room_id: int, token: str = Query(...)):
    """游戏 WebSocket 端点 — 房间内实时通信"""
    user_id = authenticate_ws(token)
    if user_id is None:
        await websocket.close(code=4001, reason="认证失败")
        return

    # 房间成员鉴权: 非成员拒绝连接
    if not _is_room_member(room_id, user_id):
        await websocket.close(code=4003, reason="非房间成员")
        return

    await manager.connect(websocket, room_id, user_id)

    # 通知房间内其他玩家
    await manager.broadcast_to_room(room_id, {
        "type": "player_online",
        "user_id": user_id,
    })

    try:
        while True:
            # 带超时的接收: 超时未收到任何消息 (含 ping) 则判定为死连接
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=_HEARTBEAT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.info("ws heartbeat timeout, closing connection for user %s in room %s", user_id, room_id)
                try:
                    await websocket.close(code=1001, reason="心跳超时")
                except Exception:
                    pass
                break

            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            # 聊天消息
            if msg_type == "chat":
                # 聊天属于玩家活跃行为，重置死牌局倒计时 (心跳不算，防止挂着的页面续命)
                activity_tracker.touch(room_id)
                await manager.broadcast_to_room(room_id, {
                    "type": "chat",
                    "user_id": user_id,
                    "content": msg.get("content", ""),
                })
            # 心跳
            elif msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, room_id)
        await manager.broadcast_to_room(room_id, {
            "type": "player_offline",
            "user_id": user_id,
        })
