"""岛屿铃钱记 — 历史 API"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, Room, RoomPlayer, Hand, Bet, Pot, HandResult, Rebuy
from app.utils import NotFoundException

router = APIRouter()


@router.get("/rooms/{room_id}/hands")
async def get_hands(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取岛屿的季节列表"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if room is None:
        raise NotFoundException("岛屿不存在")

    hands = (
        db.query(Hand)
        .filter(Hand.room_id == room_id)
        .order_by(Hand.hand_number)
        .all()
    )

    return {
        "room_id": room_id,
        "room_name": room.name,
        "hands": [
            {
                "hand_id": h.id,
                "hand_number": h.hand_number,
                "current_round": h.current_round,
                "status": h.status,
                "pot_total": h.pot_total,
                "created_at": h.created_at.isoformat() if h.created_at else None,
                "settled_at": h.settled_at.isoformat() if h.settled_at else None,
            }
            for h in hands
        ],
    }


@router.get("/hands/{hand_id}")
async def get_hand_detail(hand_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取季节详情"""
    hand = db.query(Hand).filter(Hand.id == hand_id).first()
    if hand is None:
        raise NotFoundException("季节不存在")

    # 获取所有投入
    bets = db.query(Bet).filter(Bet.hand_id == hand_id).order_by(Bet.created_at).all()

    # 获取收获篮
    pots = db.query(Pot).filter(Pot.hand_id == hand_id).all()

    # 获取收获结果
    results = db.query(HandResult).filter(HandResult.hand_id == hand_id).all()

    return {
        "hand_id": hand.id,
        "hand_number": hand.hand_number,
        "current_round": hand.current_round,
        "status": hand.status,
        "pot_total": hand.pot_total,
        "dealer_player_id": hand.dealer_player_id,
        "sb_player_id": hand.sb_player_id,
        "bb_player_id": hand.bb_player_id,
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
        "pots": [
            {
                "pot_id": p.id,
                "pot_type": p.pot_type,
                "pot_level": p.pot_level,
                "amount": p.amount,
                "eligible_player_ids": p.eligible_player_ids,
            }
            for p in pots
        ],
        "results": [
            {
                "result_id": r.id,
                "pot_id": r.pot_id,
                "winner_id": r.winner_id,
                "amount_won": r.amount_won,
                "is_split": bool(r.is_split),
            }
            for r in results
        ],
        "created_at": hand.created_at.isoformat() if hand.created_at else None,
        "settled_at": hand.settled_at.isoformat() if hand.settled_at else None,
    }


@router.get("/users/{user_id}/games")
async def get_user_games(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取用户游戏历史"""
    # 获取用户参与的所有房间
    room_players = (
        db.query(RoomPlayer)
        .filter(RoomPlayer.user_id == user_id)
        .all()
    )

    games = []
    for rp in room_players:
        room = db.query(Room).filter(Room.id == rp.room_id).first()
        if room is None:
            continue

        # 统计该房间的季数
        hand_count = db.query(Hand).filter(Hand.room_id == room.id).count()

        # 计算该用户在这个房间的净铃钱 (最终铃钱 - 初始铃钱 - 补给)
        rebuy_total = (
            db.query(func.coalesce(func.sum(Rebuy.amount), 0))
            .filter(Rebuy.room_player_id == rp.id)
            .scalar()
        )

        # 计算收获总额
        winnings = (
            db.query(func.coalesce(func.sum(HandResult.amount_won), 0))
            .join(Hand, Hand.id == HandResult.hand_id)
            .filter(Hand.room_id == room.id, HandResult.winner_id == rp.id)
            .scalar()
        )

        # 净收益 = 最终铃钱 - 初始铃钱 - 补给
        total_profit = rp.chip_count - room.initial_chips - rebuy_total

        games.append({
            "room_id": room.id,
            "room_name": room.name,
            "room_code": room.room_code,
            "hand_count": hand_count,
            "total_profit": total_profit,
            "initial_chips": room.initial_chips,
            "final_chips": rp.chip_count if rp.is_active else 0,
            "rebuy_total": rebuy_total,
            "status": room.status,
            "created_at": room.created_at.isoformat() if room.created_at else None,
        })

    # 按时间倒序
    games.sort(key=lambda g: g["created_at"] or "", reverse=True)

    return {"games": games, "total": len(games)}


@router.get("/users/{user_id}/stats")
async def get_user_stats(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取用户统计"""
    # 参与的游戏数
    total_games = db.query(RoomPlayer).filter(RoomPlayer.user_id == user_id).count()

    # 参与的季数 (作为 player 参与)
    player_ids = [
        rp.id for rp in db.query(RoomPlayer).filter(RoomPlayer.user_id == user_id).all()
    ]

    total_hands = 0
    total_profit = 0
    wins = 0

    for pid in player_ids:
        rp = db.query(RoomPlayer).filter(RoomPlayer.id == pid).first()
        if rp is None:
            continue

        room = db.query(Room).filter(Room.id == rp.room_id).first()
        if room is None:
            continue

        hand_count = db.query(Hand).filter(Hand.room_id == room.id).count()
        total_hands += hand_count

        # 净收益
        rebuy_total = (
            db.query(func.coalesce(func.sum(Rebuy.amount), 0))
            .filter(Rebuy.room_player_id == pid)
            .scalar()
        )
        profit = rp.chip_count - room.initial_chips - rebuy_total
        total_profit += profit

        if profit > 0:
            wins += 1

    win_rate = (wins / total_games * 100) if total_games > 0 else 0

    return {
        "total_games": total_games,
        "total_hands": total_hands,
        "total_profit": total_profit,
        "win_rate": round(win_rate, 1),
    }
