"""岛屿铃钱记 — 游戏 WebSocket 处理器"""

import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from typing import Dict, Set

from app.utils.security import decode_token

router = APIRouter()


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
    return int(user_id)


@router.websocket("/ws/rooms/{room_id}")
async def ws_game(websocket: WebSocket, room_id: int, token: str = Query(...)):
    """游戏 WebSocket 端点 — 房间内实时通信"""
    user_id = authenticate_ws(token)
    if user_id is None:
        await websocket.close(code=4001, reason="认证失败")
        return

    await manager.connect(websocket, room_id, user_id)

    # 通知房间内其他玩家
    await manager.broadcast_to_room(room_id, {
        "type": "player_online",
        "user_id": user_id,
    })

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            # 聊天消息
            if msg_type == "chat":
                await manager.broadcast_to_room(room_id, {
                    "type": "chat",
                    "user_id": user_id,
                    "content": msg.get("content", ""),
                })
            # 心跳
            elif msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)
        await manager.broadcast_to_room(room_id, {
            "type": "player_offline",
            "user_id": user_id,
        })
