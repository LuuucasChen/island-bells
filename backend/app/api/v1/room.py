"""岛屿铃钱记 — 房间(岛屿) API"""

import random
import string
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, Room, RoomPlayer
from app.utils import BadRequestException, ForbiddenException, NotFoundException, ConflictException
from app.api.ws.game_ws import manager as ws_manager
from app.utils.animal_names import get_random_island_name, get_random_character_name

router = APIRouter()


def _generate_room_code(length: int = 6) -> str:
    """生成渡渡鸟码 (6位大写字母+数字)"""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


class CreateRoomRequest(BaseModel):
    name: str = ""
    nickname: str = ""
    initial_chips: int = 10000
    sb_amount: int = 25
    bb_amount: int = 50
    max_players: int = 9


class JoinRoomRequest(BaseModel):
    nickname: str = ""


class SitRequest(BaseModel):
    seat_number: int


class UpdateRoomRequest(BaseModel):
    name: str | None = None
    initial_chips: int | None = None
    sb_amount: int | None = None
    bb_amount: int | None = None
    max_players: int | None = None


@router.post("")
async def create_room(req: CreateRoomRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """创建岛屿"""
    # 设置岛主昵称
    if req.nickname:
        current_user.nickname = req.nickname
    elif not current_user.nickname:
        current_user.nickname = get_random_character_name([])
    db.commit()

    # 生成唯一渡渡鸟码
    for _ in range(10):
        code = _generate_room_code()
        if not db.query(Room).filter(Room.room_code == code).first():
            break
    else:
        raise BadRequestException("无法生成渡渡鸟码，请重试")

    if req.bb_amount < req.sb_amount * 2:
        raise BadRequestException("大树费必须至少是树苗费的2倍")

    room = Room(
        room_code=code,
        name=req.name or get_random_island_name(),
        owner_id=current_user.id,
        initial_chips=req.initial_chips,
        sb_amount=req.sb_amount,
        bb_amount=req.bb_amount,
        max_players=min(req.max_players, 9),
    )
    db.add(room)
    db.commit()
    db.refresh(room)

    # 自动将岛主加入 RoomPlayer（未入座状态）
    owner_player = RoomPlayer(
        room_id=room.id,
        user_id=current_user.id,
        seat_number=-1,
        chip_count=room.initial_chips,
    )
    db.add(owner_player)
    db.commit()

    return {"room_code": room.room_code, "room_id": room.id, "name": room.name}


@router.get("/random-island-name")
async def random_island_name():
    """获取随机岛屿名"""
    return {"name": get_random_island_name()}


@router.get("/{room_id}/random-nickname")
async def random_nickname(room_id: int, db: Session = Depends(get_db)):
    """获取随机角色名（排除房间内已使用的昵称）"""
    players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room_id, RoomPlayer.is_active == 1).all()
    used_names = []
    for p in players:
        user = db.query(User).filter(User.id == p.user_id).first()
        if user and user.nickname:
            used_names.append(user.nickname)
    name = get_random_character_name(used_names)
    return {"nickname": name}


@router.get("/{room_code}")
async def get_room(room_code: str, db: Session = Depends(get_db)):
    """查看岛屿信息 (加入前预览)"""
    room = db.query(Room).filter(Room.room_code == room_code).first()
    if room is None:
        raise NotFoundException("岛屿不存在")

    players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id, RoomPlayer.is_active == 1).all()

    return {
        "room_id": room.id,
        "room_code": room.room_code,
        "name": room.name,
        "owner_id": room.owner_id,
        "status": room.status,
        "max_players": room.max_players,
        "initial_chips": room.initial_chips,
        "sb_amount": room.sb_amount,
        "bb_amount": room.bb_amount,
        "player_count": len(players),
    }


@router.post("/{room_code}/join")
async def join_room(room_code: str, req: JoinRoomRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """加入岛屿"""
    room = db.query(Room).filter(Room.room_code == room_code).first()
    if room is None:
        raise NotFoundException("岛屿不存在")

    if room.status == "finished":
        raise BadRequestException("岛屿已结束")

    # 检查是否已在房间
    existing = db.query(RoomPlayer).filter(
        RoomPlayer.room_id == room.id,
        RoomPlayer.user_id == current_user.id,
        RoomPlayer.is_active == 1,
    ).first()
    if existing:
        raise ConflictException("你已经在这个岛屿上")

    # 检查人数
    active_count = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id, RoomPlayer.is_active == 1).count()
    if active_count >= room.max_players:
        raise BadRequestException("岛屿已满")

    # 设置昵称: 如果提供了昵称，检查房间内唯一性；否则自动生成随机昵称
    existing_players = db.query(RoomPlayer).filter(
        RoomPlayer.room_id == room.id, RoomPlayer.is_active == 1
    ).all()
    used_names = []
    for p in existing_players:
        user = db.query(User).filter(User.id == p.user_id).first()
        if user and user.nickname:
            used_names.append(user.nickname)

    if req.nickname:
        nickname = req.nickname
        if nickname in used_names:
            raise BadRequestException(f"昵称 '{nickname}' 在该岛屿已被使用")
    else:
        nickname = get_random_character_name(used_names)

    current_user.nickname = nickname
    db.commit()

    player = RoomPlayer(
        room_id=room.id,
        user_id=current_user.id,
        seat_number=-1,  # 未入座
        chip_count=room.initial_chips,
    )
    db.add(player)
    db.commit()
    db.refresh(player)

    # 广播新玩家加入
    await ws_manager.broadcast_to_room(room.id, {
        "type": "player_joined",
        "data": {
            "user_id": current_user.id,
            "nickname": current_user.nickname,
            "player_id": player.id,
        },
    })

    return {"player_id": player.id, "room_id": room.id}


@router.delete("/{room_id}/leave")
async def leave_room(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """离开岛屿"""
    from datetime import datetime, timezone

    player = db.query(RoomPlayer).filter(
        RoomPlayer.room_id == room_id,
        RoomPlayer.user_id == current_user.id,
        RoomPlayer.is_active == 1,
    ).first()
    if player is None:
        raise NotFoundException("你不在这个岛屿上")

    player.is_active = 0
    player.left_at = datetime.now(timezone.utc)
    db.commit()

    return {"message": "已离岛"}


@router.post("/{room_id}/sit")
async def sit_down(room_id: int, req: SitRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """登岛入座"""
    player = db.query(RoomPlayer).filter(
        RoomPlayer.room_id == room_id,
        RoomPlayer.user_id == current_user.id,
        RoomPlayer.is_active == 1,
    ).first()
    if player is None:
        raise NotFoundException("你不在这个岛屿上")

    if not (0 <= req.seat_number <= 8):
        raise BadRequestException("座位号无效 (0-8)")

    # 检查座位是否被占
    occupied = db.query(RoomPlayer).filter(
        RoomPlayer.room_id == room_id,
        RoomPlayer.seat_number == req.seat_number,
        RoomPlayer.is_active == 1,
    ).first()
    if occupied:
        raise ConflictException("座位已被占")

    player.seat_number = req.seat_number
    db.commit()

    # 广播玩家入座
    await ws_manager.broadcast_to_room(room_id, {
        "type": "player_sat",
        "data": {
            "user_id": current_user.id,
            "nickname": current_user.nickname,
            "seat_number": req.seat_number,
        },
    })

    return {"seat_number": player.seat_number}


@router.post("/{room_id}/stand")
async def stand_up(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """离岛站起"""
    room = db.query(Room).filter(Room.id == room_id).first()

    player = db.query(RoomPlayer).filter(
        RoomPlayer.room_id == room_id,
        RoomPlayer.user_id == current_user.id,
        RoomPlayer.is_active == 1,
    ).first()
    if player is None:
        raise NotFoundException("你不在这个岛屿上")

    # 游戏进行中: 仅允许铃钱耗尽的玩家离岛
    if room and room.status == "playing" and player.chip_count > 0:
        raise BadRequestException("游戏进行中不能离岛")

    player.seat_number = -1
    db.commit()

    return {"message": "已站起"}


@router.patch("/{room_id}")
async def update_room(room_id: int, req: UpdateRoomRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """修改岛屿设置 (仅岛主，游戏开始前)"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if room is None:
        raise NotFoundException("岛屿不存在")

    if room.owner_id != current_user.id:
        raise ForbiddenException("只有岛主可以修改设置")

    if room.status != "waiting":
        raise BadRequestException("游戏已开始，无法修改")

    if req.name is not None:
        room.name = req.name
    if req.initial_chips is not None:
        room.initial_chips = req.initial_chips
    if req.sb_amount is not None:
        room.sb_amount = req.sb_amount
    if req.bb_amount is not None:
        room.bb_amount = req.bb_amount
    if req.max_players is not None:
        room.max_players = min(req.max_players, 9)

    db.commit()

    return {"message": "设置已更新"}


@router.get("/{room_id}/players")
async def get_players(room_id: int, db: Session = Depends(get_db)):
    """获取岛屿上的玩家列表"""
    players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room_id, RoomPlayer.is_active == 1).all()
    result = []
    for p in players:
        user = db.query(User).filter(User.id == p.user_id).first()
        result.append({
            "player_id": p.id,
            "user_id": p.user_id,
            "nickname": user.nickname if user else "",
            "avatar_url": user.avatar_url if user else "",
            "seat_number": p.seat_number,
            "chip_count": p.chip_count,
        })
    return {"players": result}
