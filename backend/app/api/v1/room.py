"""岛屿铃钱记 — 房间(岛屿) API"""

import json
import random
import string
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, Room, RoomPlayer, Hand, Bet
from app.utils import BadRequestException, ForbiddenException, NotFoundException, ConflictException
from app.utils import activity_tracker
from app.api.ws.game_ws import manager as ws_manager
from app.utils.animal_names import get_random_island_name, get_random_character_name
from app.engine.hand_engine import HandEngine

router = APIRouter()


def _generate_room_code(length: int = 6) -> str:
    """生成渡渡鸟码 (6位大写字母+数字)"""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


def _get_unsettled_hand(db: Session, room_id: int) -> Hand | None:
    """获取房间当前未结算的手牌 (betting/settling)，无则返回 None"""
    return (
        db.query(Hand)
        .filter(Hand.room_id == room_id, Hand.status.in_(["betting", "settling"]))
        .order_by(Hand.hand_number.desc())
        .first()
    )


def _auto_fold_current_hand(db: Session, room: Room, player: RoomPlayer) -> dict | None:
    """若玩家是当前下注中手牌的未 fold 参与者，自动为其补一条 fold 行动。

    与 /rooms/{id}/action 的 fold 路径一致: 写 Bet(fold) → 推进 turn →
    触发 auto_end 检查 → 本轮结束则自动推进阶段。
    返回 {"hand", "bet", "advanced", "auto_ended"}；无需 fold 时返回 None。
    """
    hand = _get_unsettled_hand(db, room.id)
    if hand is None or hand.status != "betting":
        return None  # settling 阶段下注已结束，无需 fold

    hole = json.loads(hand.hole_cards) if hand.hole_cards else {}
    if str(player.id) not in hole:
        return None  # 非本手参与者

    folded_ids = {
        b.player_id for b in db.query(Bet)
        .filter(Bet.hand_id == hand.id, Bet.action == "fold")
        .all()
    }
    if player.id in folded_ids:
        return None  # 已 fold

    # 补一条 fold 行动
    bet = Bet(
        hand_id=hand.id,
        player_id=player.id,
        round=hand.current_round,
        action="fold",
        amount=0,
    )
    db.add(bet)
    db.flush()

    engine = HandEngine(db, room)
    # 只有轮到该玩家行动时才需要推进 turn；否则 turn 仍指向其他玩家，牌局继续
    if hand.turn_player_id == player.id:
        engine._advance_turn(hand, player, "fold", 0)
    engine._check_auto_end(hand)
    db.flush()
    db.refresh(hand)

    # 本轮下注全部完成则自动推进阶段 (与 /action 的 fold 路径一致)
    advanced = False
    if hand.turn_player_id is None and hand.status == "betting":
        engine.advance_round(hand)
        db.refresh(hand)
        advanced = True

    auto_ended = hand.status == "settling" and not advanced

    # 自动 fold 属于游戏状态变更，重置死牌局倒计时
    activity_tracker.touch(room.id)

    return {"hand": hand, "bet": bet, "advanced": advanced, "auto_ended": auto_ended}


async def _broadcast_auto_fold(room_id: int, fold_info: dict) -> None:
    """自动 fold 后广播牌局变化 (与 /action 的广播口径一致)"""
    hand = fold_info["hand"]
    ws_data = {
        "hand_id": hand.id,
        "player_id": fold_info["bet"].player_id,
        "action": "fold",
        "amount": 0,
        "pot_total": hand.pot_total,
        "current_round": hand.current_round,
        "status": hand.status,
        "turn_player_id": hand.turn_player_id,
    }
    if fold_info["advanced"] or fold_info["auto_ended"]:
        ws_data["community_cards"] = json.loads(hand.community_cards) if hand.community_cards else []
        ws_data["ended_by_fold"] = bool(hand.ended_by_fold)
        ws_type = "round_advance"
    else:
        ws_type = "game_update"
    await ws_manager.broadcast_to_room(room_id, {"type": ws_type, "data": ws_data})


class CreateRoomRequest(BaseModel):
    name: str = ""
    nickname: str = ""
    initial_chips: int = Field(10000, gt=0)
    sb_amount: int = Field(25, gt=0)
    bb_amount: int = Field(50, gt=0)
    max_players: int = 9


class JoinRoomRequest(BaseModel):
    nickname: str = ""


class SitRequest(BaseModel):
    seat_number: int


class UpdateRoomRequest(BaseModel):
    name: str | None = None
    initial_chips: int | None = Field(None, gt=0)
    sb_amount: int | None = Field(None, gt=0)
    bb_amount: int | None = Field(None, gt=0)
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
        max_players=max(2, min(req.max_players, 9)),
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
async def join_room(room_code: str, req: JoinRoomRequest | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """加入岛屿 (body 可省略，昵称缺省自动生成)"""
    room = db.query(Room).filter(Room.room_code == room_code).first()
    if room is None:
        raise NotFoundException("岛屿不存在")

    if room.status == "finished":
        raise BadRequestException("岛屿已结束")

    # 检查是否已有房间记录 (含已离岛 is_active=0)
    existing = db.query(RoomPlayer).filter(
        RoomPlayer.room_id == room.id,
        RoomPlayer.user_id == current_user.id,
    ).first()

    if existing and existing.is_active == 1:
        raise ConflictException("你已经在这个岛屿上")

    if existing:
        # 离岛后重进: 复用原行恢复 is_active，不新建行、不双份买入
        existing.is_active = 1
        existing.left_at = None
        db.commit()

        await ws_manager.broadcast_to_room(room.id, {
            "type": "player_joined",
            "data": {
                "user_id": current_user.id,
                "nickname": current_user.nickname,
                "player_id": existing.id,
            },
        })
        return {"player_id": existing.id, "room_id": room.id}

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

    nickname = req.nickname if req else ""
    if nickname:
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
    player = db.query(RoomPlayer).filter(
        RoomPlayer.room_id == room_id,
        RoomPlayer.user_id == current_user.id,
        RoomPlayer.is_active == 1,
    ).first()
    if player is None:
        raise NotFoundException("你不在这个岛屿上")

    room = db.query(Room).filter(Room.id == room_id).first()

    # 当前未结算手牌的未 fold 参与者: 先自动 fold，避免轮空死锁
    fold_info = _auto_fold_current_hand(db, room, player) if room else None

    player.is_active = 0
    player.left_at = datetime.now(timezone.utc)
    player.seat_number = -1

    # 岛主离岛: 房主迁移给最早加入的其他活跃成员，
    # 否则结算/开新局/结束游戏全部卡死 (这些操作仅岛主可做)
    if room and room.owner_id == current_user.id and room.status != "finished":
        successor = (
            db.query(RoomPlayer)
            .filter(
                RoomPlayer.room_id == room_id,
                RoomPlayer.is_active == 1,
                RoomPlayer.id != player.id,
            )
            .order_by(RoomPlayer.joined_at, RoomPlayer.id)
            .first()
        )
        if successor:
            room.owner_id = successor.user_id

    db.commit()

    if fold_info:
        await _broadcast_auto_fold(room_id, fold_info)

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

    # 牌局进行中 (存在未结算手牌) 不允许中途入座，等下一局开始前再入座
    room = db.query(Room).filter(Room.id == room_id).first()
    if room and room.status == "playing" and _get_unsettled_hand(db, room_id) is not None:
        raise BadRequestException("牌局进行中，请等下一局开始前再入座")

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

    # 入座属于活跃事件，重置死牌局倒计时
    activity_tracker.touch(room_id)

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

    # 当前未结算手牌的未 fold 参与者 (含 all-in): 先自动 fold，再站起
    fold_info = _auto_fold_current_hand(db, room, player) if room else None

    player.seat_number = -1
    db.commit()

    # 站起属于活跃事件，重置死牌局倒计时
    activity_tracker.touch(room_id)

    if fold_info:
        await _broadcast_auto_fold(room_id, fold_info)

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
        # 已有玩家加入后禁止修改初始铃钱，避免结算基准失真
        has_players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room_id).first() is not None
        if has_players:
            raise BadRequestException("已有居民加入，无法修改初始铃钱")
        room.initial_chips = req.initial_chips
    if req.sb_amount is not None:
        room.sb_amount = req.sb_amount
    if req.bb_amount is not None:
        room.bb_amount = req.bb_amount
    if req.max_players is not None:
        room.max_players = max(2, min(req.max_players, 9))

    # 仅在盲注实际被修改时校验配比，避免校验引入前创建的旧房间连改名都被拒
    if req.sb_amount is not None or req.bb_amount is not None:
        if room.bb_amount < room.sb_amount * 2:
            raise BadRequestException("大树费必须至少是树苗费的2倍")

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
