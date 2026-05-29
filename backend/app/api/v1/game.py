"""岛屿铃钱记 — 游戏 API"""

import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, Room, RoomPlayer, Hand, Bet, Pot, HandResult, Rebuy
from app.engine.hand_engine import HandEngine, get_active_seated_players
from app.engine.deck import cards_from_json
from app.engine.evaluator import evaluate_hand, get_hand_type, get_hand_type_name
from app.utils import BadRequestException, ForbiddenException, NotFoundException
from app.utils import activity_tracker
from app.api.ws.game_ws import manager as ws_manager

router = APIRouter()


class BetRequest(BaseModel):
    action: str   # call / raise / allin / fold / check
    amount: int = 0

    def get_action(self) -> str:
        """将 check 转换为 call (amount=0)"""
        if self.action == "check":
            return "call"
        return self.action


class SettleResultItem(BaseModel):
    pot_id: int
    winner_ids: list[int]
    amount: int


class SettleRequest(BaseModel):
    results: list[SettleResultItem]


class RebuyRequest(BaseModel):
    amount: int


def _get_room_or_404(db: Session, room_id: int) -> Room:
    room = db.query(Room).filter(Room.id == room_id).first()
    if room is None:
        raise NotFoundException("岛屿不存在")
    return room


def _get_player_or_404(db: Session, room_id: int, user_id: int) -> RoomPlayer:
    player = db.query(RoomPlayer).filter(
        RoomPlayer.room_id == room_id,
        RoomPlayer.user_id == user_id,
        RoomPlayer.is_active == 1,
    ).first()
    if player is None:
        raise NotFoundException("你不在这个岛屿上")
    return player


@router.post("/rooms/{room_id}/start")
async def start_game(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """开始游戏 (岛主操作)"""
    room = _get_room_or_404(db, room_id)

    if room.owner_id != current_user.id:
        raise ForbiddenException("只有岛主可以开始游戏")

    if room.status != "waiting":
        raise BadRequestException("游戏已经开始或已结束")

    # 检查入座人数
    seated = db.query(RoomPlayer).filter(
        RoomPlayer.room_id == room_id,
        RoomPlayer.is_active == 1,
        RoomPlayer.seat_number >= 0,
    ).count()

    if seated < 2:
        raise BadRequestException("至少需要2名已入座居民")

    room.status = "playing"
    db.commit()

    # 自动开始第一季
    engine = HandEngine(db, room)
    hand = engine.start_new_hand()

    # 记录活跃时间，启动死牌局倒计时
    activity_tracker.touch(room_id)

    # WebSocket 广播
    await ws_manager.broadcast_to_room(room_id, {
        "type": "game_started",
        "data": {"room_id": room_id, "hand_id": hand.id},
    })

    return {
        "message": "游戏已开始",
        "hand_id": hand.id,
        "hand_number": hand.hand_number,
        "current_round": hand.current_round,
        "pot_total": hand.pot_total,
    }


@router.post("/rooms/{room_id}/new-hand")
async def new_hand(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """开始新一季 (岛主操作)"""
    room = _get_room_or_404(db, room_id)

    if room.owner_id != current_user.id:
        raise ForbiddenException("只有岛主可以开始新一季")

    if room.status != "playing":
        raise BadRequestException("游戏未在进行中")

    # 检查上一季是否已结算
    last_hand = (
        db.query(Hand)
        .filter(Hand.room_id == room_id)
        .order_by(Hand.hand_number.desc())
        .first()
    )
    if last_hand and last_hand.status != "settled":
        raise BadRequestException("上一季尚未完成收获")

    engine = HandEngine(db, room)
    hand = engine.start_new_hand()

    # 新一手开局也属于活跃事件，重置死牌局倒计时
    activity_tracker.touch(room_id)

    # WebSocket 广播
    await ws_manager.broadcast_to_room(room_id, {
        "type": "new_hand",
        "data": {
            "hand_id": hand.id,
            "hand_number": hand.hand_number,
            "dealer_player_id": hand.dealer_player_id,
            "sb_player_id": hand.sb_player_id,
            "bb_player_id": hand.bb_player_id,
            "current_round": hand.current_round,
            "pot_total": hand.pot_total,
        },
    })

    return {
        "hand_id": hand.id,
        "hand_number": hand.hand_number,
        "current_round": hand.current_round,
        "pot_total": hand.pot_total,
    }


@router.post("/hands/{hand_id}/next-round")
async def advance_round(hand_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """推进到下一阶段 (岛主操作)"""
    hand = db.query(Hand).filter(Hand.id == hand_id).first()
    if hand is None:
        raise NotFoundException("季节不存在")

    room = _get_room_or_404(db, hand.room_id)

    if room.owner_id != current_user.id:
        raise ForbiddenException("只有岛主可以推进阶段")

    engine = HandEngine(db, room)
    hand = engine.advance_round(hand)

    # WebSocket 广播
    await ws_manager.broadcast_to_room(hand.room_id, {
        "type": "round_advance",
        "data": {
            "hand_id": hand.id,
            "current_round": hand.current_round,
            "status": hand.status,
            "pot_total": hand.pot_total,
        },
    })

    return {
        "hand_id": hand.id,
        "current_round": hand.current_round,
        "status": hand.status,
        "pot_total": hand.pot_total,
    }


@router.post("/hands/{hand_id}/bet")
async def place_bet(hand_id: int, req: BetRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """玩家投入铃钱"""
    hand = db.query(Hand).filter(Hand.id == hand_id).first()
    if hand is None:
        raise NotFoundException("季节不存在")

    player = _get_player_or_404(db, hand.room_id, current_user.id)

    room = _get_room_or_404(db, hand.room_id)
    engine = HandEngine(db, room)
    bet = engine.place_bet(hand, player, req.action, req.amount)

    # 重新加载 hand 获取更新后的数据
    db.refresh(hand)

    # 玩家下注行动属于活跃事件
    activity_tracker.touch(hand.room_id)

    # WebSocket 广播
    await ws_manager.broadcast_to_room(hand.room_id, {
        "type": "game_update",
        "data": {
            "hand_id": hand.id,
            "player_id": player.id,
            "action": req.action,
            "amount": bet.amount,
            "pot_total": hand.pot_total,
            "current_round": hand.current_round,
        },
    })

    return {
        "bet_id": bet.id,
        "action": bet.action,
        "amount": bet.amount,
        "pot_total": hand.pot_total,
        "player_chip_count": player.chip_count,
    }


@router.post("/hands/{hand_id}/settle")
async def settle_hand(hand_id: int, req: SettleRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """提交收获结果 (岛主操作)"""
    hand = db.query(Hand).filter(Hand.id == hand_id).first()
    if hand is None:
        raise NotFoundException("季节不存在")

    room = _get_room_or_404(db, hand.room_id)

    if room.owner_id != current_user.id:
        raise ForbiddenException("只有岛主可以提交收获")

    engine = HandEngine(db, room)
    results = engine.settle_hand(hand, [r.dict() for r in req.results])

    # WebSocket 广播
    await ws_manager.broadcast_to_room(hand.room_id, {
        "type": "hand_settled",
        "data": {
            "hand_id": hand.id,
            "results": [{"winner_id": r.winner_id, "amount_won": r.amount_won} for r in results],
        },
    })

    return {
        "hand_id": hand.id,
        "status": "settled",
        "results": [{"winner_id": r.winner_id, "amount_won": r.amount_won, "is_split": r.is_split} for r in results],
    }


@router.post("/rooms/{room_id}/rebuy")
async def rebuy(room_id: int, req: RebuyRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """补给铃钱"""
    room = _get_room_or_404(db, room_id)
    player = _get_player_or_404(db, room_id, current_user.id)

    engine = HandEngine(db, room)
    rebuy_record = engine.rebuy(player, req.amount)

    # WebSocket 广播
    await ws_manager.broadcast_to_room(room_id, {
        "type": "rebuy",
        "data": {
            "player_id": player.id,
            "amount": req.amount,
            "new_chip_count": player.chip_count,
        },
    })

    return {
        "rebuy_id": rebuy_record.id,
        "amount": req.amount,
        "new_chip_count": player.chip_count,
    }


@router.post("/rooms/{room_id}/end-game")
async def end_game(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """结束游戏并计算最终结算 (岛主操作)"""
    room = _get_room_or_404(db, room_id)

    if room.owner_id != current_user.id:
        raise ForbiddenException("只有岛主可以结束游戏")

    if room.status == "finished":
        raise BadRequestException("游戏已结束")

    settlement = await _finish_room_impl(db, room, reason="owner")

    return {
        "message": "游戏已结束",
        "room_id": room_id,
        "settlement": settlement,
    }


async def _finish_room_impl(db: Session, room: Room, reason: str = "owner") -> list[dict]:
    """结束房间的实现逻辑（HTTP 路由与后台死牌局清理共用）。

    不做任何权限校验，调用方需自行验证。返回最终结算列表。
    """
    room_id = room.id

    # 结算当前未完成的季
    active_hand = (
        db.query(Hand)
        .filter(Hand.room_id == room_id, Hand.status.in_(["betting", "settling"]))
        .first()
    )
    if active_hand:
        active_hand.status = "settled"
        active_hand.settled_at = datetime.now(timezone.utc)

    room.status = "finished"
    room.closed_at = datetime.now(timezone.utc)
    db.commit()

    # 计算最终结算: 所有玩家 (包括已离岛但 is_active=1 的)
    all_players = (
        db.query(RoomPlayer)
        .filter(RoomPlayer.room_id == room.id, RoomPlayer.is_active == 1)
        .all()
    )

    settlement = []
    for p in all_players:
        user = db.query(User).filter(User.id == p.user_id).first()
        rebuy_total = (
            db.query(func.coalesce(func.sum(Rebuy.amount), 0))
            .filter(Rebuy.room_player_id == p.id)
            .scalar()
        )
        net = p.chip_count - room.initial_chips - rebuy_total
        settlement.append({
            "player_id": p.id,
            "user_id": p.user_id,
            "nickname": user.nickname if user else "未知",
            "initial_chips": room.initial_chips,
            "final_chips": p.chip_count,
            "rebuy_total": rebuy_total,
            "net_profit": net,
        })

    # 按净收益排序
    settlement.sort(key=lambda s: s["net_profit"], reverse=True)

    # WebSocket 广播
    await ws_manager.broadcast_to_room(room_id, {
        "type": "game_ended",
        "data": {
            "room_id": room_id,
            "settlement": settlement,
            "reason": reason,
        },
    })

    # 从活跃度跟踪表中移除该房间
    activity_tracker.remove(room_id)

    return settlement


@router.post("/rooms/{room_id}/advance")
async def advance_round_shortcut(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """推进到下一阶段 (岛主操作，自动查找当前活跃季)"""
    room = _get_room_or_404(db, room_id)

    if room.owner_id != current_user.id:
        raise ForbiddenException("只有岛主可以推进阶段")

    active_hand = (
        db.query(Hand)
        .filter(Hand.room_id == room_id, Hand.status == "betting")
        .order_by(Hand.hand_number.desc())
        .first()
    )
    if active_hand is None:
        raise BadRequestException("当前没有进行中的季节")

    # 必须所有在场玩家都已操作完毕才能推进
    if active_hand.turn_player_id is not None:
        raise BadRequestException("还有玩家未操作，无法推进")

    engine = HandEngine(db, room)
    hand = engine.advance_round(active_hand)

    ws_data = {
        "hand_id": hand.id,
        "current_round": hand.current_round,
        "status": hand.status,
        "pot_total": hand.pot_total,
    }
    # 进入 showdown 时附加 ended_by_fold + community_cards
    if hand.status == "settling":
        ws_data["ended_by_fold"] = bool(hand.ended_by_fold)
        ws_data["community_cards"] = json.loads(hand.community_cards) if hand.community_cards else []

    await ws_manager.broadcast_to_room(hand.room_id, {
        "type": "round_advance",
        "data": ws_data,
    })

    return {
        "hand_id": hand.id,
        "current_round": hand.current_round,
        "status": hand.status,
        "pot_total": hand.pot_total,
    }


@router.post("/rooms/{room_id}/settle")
async def settle_hand_shortcut(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """收获结算 (岛主操作，自动评估牌力确定赢家)"""
    room = _get_room_or_404(db, room_id)

    if room.owner_id != current_user.id:
        raise ForbiddenException("只有岛主可以结算")

    settling_hand = (
        db.query(Hand)
        .filter(Hand.room_id == room_id, Hand.status == "settling")
        .order_by(Hand.hand_number.desc())
        .first()
    )
    if settling_hand is None:
        # 幂等: 如果已结算，返回成功而非报错
        settled_hand = (
            db.query(Hand)
            .filter(Hand.room_id == room_id, Hand.status == "settled")
            .order_by(Hand.hand_number.desc())
            .first()
        )
        if settled_hand:
            return {"hand_id": settled_hand.id, "status": "already_settled", "results": []}
        raise BadRequestException("当前没有待结算的季节")

    # 自动评估牌力确定赢家
    engine = HandEngine(db, room)
    hand_results = engine.settle_hand(settling_hand, results=None)

    # 获取牌力评估信息用于广播
    evaluations = engine.get_hand_evaluations(settling_hand)

    await ws_manager.broadcast_to_room(settling_hand.room_id, {
        "type": "hand_settled",
        "data": {
            "hand_id": settling_hand.id,
            "results": [
                {"winner_id": r.winner_id, "amount_won": r.amount_won}
                for r in hand_results
            ],
        },
    })

    return {
        "hand_id": settling_hand.id,
        "status": "settled",
        "results": [
            {"winner_id": r.winner_id, "amount_won": r.amount_won, "is_split": r.is_split}
            for r in hand_results
        ],
        "evaluations": {
            str(pid): ev for pid, ev in evaluations.items()
        },
    }


@router.post("/rooms/{room_id}/muck")
async def muck_hand(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """盖牌: 因 fold 结束的牌局，赢家选择不展示手牌"""
    player = _get_player_or_404(db, room_id, current_user.id)

    settling_hand = (
        db.query(Hand)
        .filter(Hand.room_id == room_id, Hand.status == "settling")
        .order_by(Hand.hand_number.desc())
        .first()
    )
    if settling_hand is None:
        raise BadRequestException("当前没有待结算的季节")
    if not settling_hand.ended_by_fold:
        raise BadRequestException("只有因弃牌结束的牌局才能盖牌")

    # 验证调用者是唯一存活玩家 (赢家)
    all_bets = db.query(Bet).filter(Bet.hand_id == settling_hand.id).all()
    folded_ids = {b.player_id for b in all_bets if b.action == "fold"}
    alive = [p for p in get_active_seated_players(db, room_id) if p.id not in folded_ids]
    if len(alive) != 1 or alive[0].id != player.id:
        raise ForbiddenException("只有赢家可以选择是否盖牌")

    settling_hand.muck_player_id = player.id
    db.commit()

    await ws_manager.broadcast_to_room(room_id, {
        "type": "muck_chosen",
        "data": {"hand_id": settling_hand.id, "player_id": player.id},
    })

    return {"message": "已选择盖牌", "player_id": player.id}


class RevealRequest(BaseModel):
    action: str  # "show" | "muck"


@router.post("/rooms/{room_id}/reveal")
async def reveal_hand(room_id: int, req: RevealRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Showdown 亮牌/盖牌决定"""
    player = _get_player_or_404(db, room_id, current_user.id)

    settling_hand = (
        db.query(Hand)
        .filter(Hand.room_id == room_id, Hand.status == "settling")
        .order_by(Hand.hand_number.desc())
        .first()
    )
    if settling_hand is None:
        raise BadRequestException("当前没有待结算的季节")
    if settling_hand.ended_by_fold:
        raise BadRequestException("因弃牌结束的牌局使用盖牌功能")

    # 验证玩家是存活的 (非 fold)
    all_bets = db.query(Bet).filter(Bet.hand_id == settling_hand.id).all()
    folded_ids = {b.player_id for b in all_bets if b.action == "fold"}
    if player.id in folded_ids:
        raise BadRequestException("已弃牌的玩家不能亮牌")

    if req.action not in ("show", "muck"):
        raise BadRequestException("无效操作，必须是 show 或 muck")

    # last_aggressor 不能盖牌
    if req.action == "muck" and player.id == settling_hand.last_aggressor_id:
        raise BadRequestException("最后激进者必须亮牌")

    # 解析当前已亮牌/盖牌列表
    current_revealed = set()
    if settling_hand.revealed_players:
        current_revealed = {int(x) for x in settling_hand.revealed_players.split(",") if x}

    current_mucked = set()
    if settling_hand.mucked_players:
        current_mucked = {int(x) for x in settling_hand.mucked_players.split(",") if x}

    # 已经做过决定的玩家不能重复操作
    if player.id in current_revealed or player.id in current_mucked:
        raise BadRequestException("你已经做过决定了")

    if req.action == "show":
        current_revealed.add(player.id)
        settling_hand.revealed_players = ",".join(str(x) for x in sorted(current_revealed))
    else:  # muck
        current_mucked.add(player.id)
        settling_hand.mucked_players = ",".join(str(x) for x in sorted(current_mucked))

    db.commit()

    # 判断是否所有人都已决定 (亮牌 + 盖牌 == 存活玩家数)
    alive_players = [p for p in get_active_seated_players(db, room_id) if p.id not in folded_ids]
    alive_ids = {p.id for p in alive_players}
    all_decided = (current_revealed | current_mucked) >= alive_ids

    await ws_manager.broadcast_to_room(room_id, {
        "type": "player_revealed",
        "data": {
            "hand_id": settling_hand.id,
            "player_id": player.id,
            "action": req.action,
            "revealed_players": list(current_revealed),
            "mucked_players": list(current_mucked),
            "all_decided": all_decided,
        },
    })

    return {
        "message": "已亮牌" if req.action == "show" else "已盖牌",
        "player_id": player.id,
        "action": req.action,
        "revealed_players": list(current_revealed),
        "mucked_players": list(current_mucked),
        "all_decided": all_decided,
    }


@router.post("/rooms/{room_id}/action")
async def player_action_shortcut(room_id: int, req: BetRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """玩家操作快捷路由 (自动查找当前活跃季，自动推进轮次)"""
    active_hand = (
        db.query(Hand)
        .filter(Hand.room_id == room_id, Hand.status == "betting")
        .order_by(Hand.hand_number.desc())
        .first()
    )
    if active_hand is None:
        raise BadRequestException("当前没有进行中的季节")

    player = _get_player_or_404(db, room_id, current_user.id)
    room = _get_room_or_404(db, room_id)
    engine = HandEngine(db, room)
    bet = engine.place_bet(active_hand, player, req.get_action(), req.amount)

    db.refresh(active_hand)

    # 玩家下注行动属于活跃事件，重置死牌局倒计时
    activity_tracker.touch(room_id)

    # === 自动推进: 本轮下注结束 → 自动进入下一阶段 ===
    advanced = False
    if active_hand.turn_player_id is None and active_hand.status == "betting":
        engine.advance_round(active_hand)
        db.refresh(active_hand)
        advanced = True

    # === 弃牌自动结算: fold 导致直接进入 settling ===
    auto_ended = False
    if active_hand.status == "settling" and not advanced:
        auto_ended = True

    # 构造 WS 广播数据
    ws_data = {
        "hand_id": active_hand.id,
        "player_id": player.id,
        "action": req.action,
        "amount": bet.amount,
        "pot_total": active_hand.pot_total,
        "current_round": active_hand.current_round,
        "status": active_hand.status,
        "turn_player_id": active_hand.turn_player_id,
    }

    if advanced or auto_ended:
        # 推进后: 附加公共牌 + ended_by_fold 标记
        ws_data["community_cards"] = json.loads(active_hand.community_cards) if active_hand.community_cards else []
        ws_data["ended_by_fold"] = bool(active_hand.ended_by_fold)
        ws_type = "round_advance"
    else:
        ws_type = "game_update"

    await ws_manager.broadcast_to_room(active_hand.room_id, {
        "type": ws_type,
        "data": ws_data,
    })

    return {
        "bet_id": bet.id,
        "action": bet.action,
        "amount": bet.amount,
        "pot_total": active_hand.pot_total,
        "player_chip_count": player.chip_count,
        "advanced": advanced,
        "current_round": active_hand.current_round,
        "status": active_hand.status,
    }


@router.get("/rooms/{room_id}/state")
async def get_game_state(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取当前游戏状态"""
    room = _get_room_or_404(db, room_id)
    _get_player_or_404(db, room_id, current_user.id)

    try:
        return _build_game_state(db, room, current_user)
    except Exception:
        logger.exception("Failed to build game state for room %s", room_id)
        raise


def _build_game_state(db: Session, room: Room, current_user: User) -> dict:

    # 当前进行中的季 (betting/settling) 或最近已结算的季
    active_hand = (
        db.query(Hand)
        .filter(Hand.room_id == room.id, Hand.status.in_(["betting", "settling"]))
        .first()
    )

    # 如果没有活跃的，查找最近结算的（用于显示结算结果）
    settled_hand = None
    if not active_hand:
        settled_hand = (
            db.query(Hand)
            .filter(Hand.room_id == room.id, Hand.status == "settled")
            .order_by(Hand.hand_number.desc())
            .first()
        )

    display_hand = active_hand or settled_hand

    hand_data = None
    if display_hand:
        # 获取收获篮
        pots = db.query(Pot).filter(Pot.hand_id == display_hand.id).all()

        # 获取本季所有投入
        bets = db.query(Bet).filter(Bet.hand_id == display_hand.id).order_by(Bet.created_at).all()

        # 获取玩家列表
        players = db.query(RoomPlayer).filter(
            RoomPlayer.room_id == room.id,
            RoomPlayer.is_active == 1,
            RoomPlayer.seat_number >= 0,
        ).order_by(RoomPlayer.seat_number).all()

        # 计算每人本轮投入
        round_bets = [b for b in bets if b.round == display_hand.current_round]
        player_round_bets = {}
        for b in round_bets:
            player_round_bets[b.player_id] = player_round_bets.get(b.player_id, 0) + b.amount

        # 已 fold 的玩家
        folded_ids = {b.player_id for b in bets if b.action == "fold"}

        players_data = []
        for p in players:
            user = db.query(User).filter(User.id == p.user_id).first()
            role = None
            if p.id == display_hand.dealer_player_id:
                role = "D"
            elif p.id == display_hand.sb_player_id:
                role = "SB"
            elif p.id == display_hand.bb_player_id:
                role = "BB"

            players_data.append({
                "player_id": p.id,
                "user_id": p.user_id,
                "nickname": user.nickname if user else "",
                "avatar_url": user.avatar_url if user else "",
                "seat_number": p.seat_number,
                "chip_count": p.chip_count,
                "bet_this_round": player_round_bets.get(p.id, 0),
                "is_folded": p.id in folded_ids,
                "role": role,
            })

        hand_data = {
            "hand_id": display_hand.id,
            "hand_number": display_hand.hand_number,
            "current_round": display_hand.current_round,
            "status": display_hand.status,
            "pot_total": display_hand.pot_total,
            "turn_player_id": display_hand.turn_player_id,
            "pots": [
                {
                    "pot_id": pot.id,
                    "pot_type": pot.pot_type,
                    "pot_level": pot.pot_level,
                    "amount": pot.amount,
                }
                for pot in pots
            ],
            "players": players_data,
            "bets": [
                {
                    "bet_id": b.id,
                    "player_id": b.player_id,
                    "round": b.round,
                    "action": b.action,
                    "amount": b.amount,
                }
                for b in bets
            ],
            # 公共牌（所有人可见）
            "community_cards": json.loads(display_hand.community_cards) if display_hand.community_cards else [],
            # 结算辅助
            "ended_by_fold": bool(display_hand.ended_by_fold),
            "muck_player_id": display_hand.muck_player_id,
            "last_aggressor_id": display_hand.last_aggressor_id,
            "revealed_players": [int(x) for x in (display_hand.revealed_players or "").split(",") if x],
            "mucked_players": [int(x) for x in (display_hand.mucked_players or "").split(",") if x],
        }

        # 当前用户的手牌（只返回自己的，不暴露他人）
        my_player = next((p for p in players if p.user_id == current_user.id), None)
        if my_player and display_hand.hole_cards:
            hole_data = json.loads(display_hand.hole_cards)
            my_cards = hole_data.get(str(my_player.id), [])
            hand_data["my_hole_cards"] = my_cards
        else:
            hand_data["my_hole_cards"] = []

        # showdown 时返回所有存活玩家的手牌（用于内联展示）
        # fold 玩家不返回，muck 玩家不返回
        if display_hand.status in ("settling", "settled") and display_hand.hole_cards:
            hole_data = json.loads(display_hand.hole_cards)
            muck_pid = display_hand.muck_player_id
            folded_pids = {
                b.player_id for b in db.query(Bet)
                .filter(Bet.hand_id == display_hand.id, Bet.action == "fold")
                .all()
            }
            all_hole_cards = {}
            for pid_str, cards in hole_data.items():
                pid = int(pid_str)
                # 跳过 fold 和 muck 的玩家
                if pid in folded_pids:
                    continue
                if muck_pid and pid == muck_pid:
                    continue
                all_hole_cards[pid_str] = cards
            hand_data["all_hole_cards"] = all_hole_cards
        else:
            hand_data["all_hole_cards"] = {}

        # 牌力评估（showdown 时返回所有存活玩家的牌型）
        if display_hand.status in ("settling", "settled"):
            engine = HandEngine(db, room)
            evals = engine.get_hand_evaluations(display_hand)
            hand_data["evaluations"] = {
                str(pid): ev for pid, ev in evals.items()
            }
        else:
            hand_data["evaluations"] = {}

        # 我的实时牌型评估: flop/turn/river 阶段且我有 2 张手牌时返回
        # 用于前端在底部手牌区显示「当前牌型」
        my_eval = None
        if (
            my_player
            and display_hand.hole_cards
            and display_hand.community_cards
            and display_hand.current_round in ("flop", "turn", "river", "showdown")
        ):
            try:
                hole_data = json.loads(display_hand.hole_cards)
                my_cards_raw = hole_data.get(str(my_player.id), [])
                comm_cards = cards_from_json(display_hand.community_cards)
                if len(my_cards_raw) == 2 and len(comm_cards) >= 3:
                    hole_objs = cards_from_json(json.dumps(my_cards_raw))
                    score = evaluate_hand(hole_objs, comm_cards)
                    my_eval = {
                        "hand_type": get_hand_type(score),
                        "hand_type_name": get_hand_type_name(score),
                    }
            except Exception:
                my_eval = None
        hand_data["my_evaluation"] = my_eval

    # 如果牌局已结束，附加最终结算数据
    final_settlement = None
    if room.status == "finished":
        all_players = (
            db.query(RoomPlayer)
            .filter(RoomPlayer.room_id == room.id, RoomPlayer.is_active == 1)
            .all()
        )
        settlement_list = []
        for p in all_players:
            user = db.query(User).filter(User.id == p.user_id).first()
            rebuy_total = (
                db.query(func.coalesce(func.sum(Rebuy.amount), 0))
                .filter(Rebuy.room_player_id == p.id)
                .scalar()
            )
            net = p.chip_count - room.initial_chips - rebuy_total
            settlement_list.append({
                "player_id": p.id,
                "user_id": p.user_id,
                "nickname": user.nickname if user else "未知",
                "initial_chips": room.initial_chips,
                "final_chips": p.chip_count,
                "rebuy_total": rebuy_total,
                "net_profit": net,
            })
        settlement_list.sort(key=lambda s: s["net_profit"], reverse=True)
        final_settlement = settlement_list

    # 最近一次已结算的牌局 id，用于前端「牌局回顾」按钮
    _last_row = (
        db.query(Hand.id)
        .filter(Hand.room_id == room.id, Hand.status == "settled")
        .order_by(Hand.hand_number.desc())
        .first()
    )
    last_settled_hand_id = _last_row[0] if _last_row else None

    return {
        "room_id": room.id,
        "room_name": room.name,
        "room_status": room.status,
        "owner_id": room.owner_id,
        "bb_amount": room.bb_amount,
        "sb_amount": room.sb_amount,
        "initial_chips": room.initial_chips,
        "current_hand": hand_data,
        "final_settlement": final_settlement,
        "last_settled_hand_id": last_settled_hand_id,
    }


@router.post("/rooms/{room_id}/sync")
async def manual_sync(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """手动同步：广播 manual_sync 让房间内所有玩家重新拉取最新 state。

    仅需请求者是房间内玩家（避免被外部滥用）；不修改任何业务状态、不重置死牌局计时器。
    """
    _get_room_or_404(db, room_id)
    _get_player_or_404(db, room_id, current_user.id)

    await ws_manager.broadcast_to_room(room_id, {
        "type": "manual_sync",
        "data": {"room_id": room_id, "by_user_id": current_user.id},
    })
    return {"ok": True}
