"""岛屿铃钱记 — 历史 API"""

import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, Room, RoomPlayer, Hand, Bet, Pot, HandResult, Rebuy
from app.utils import NotFoundException
from app.engine.hand_engine import HandEngine

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
    """获取季节详情（含完整回顾数据：公共牌 / 所有人手牌 / 牌力评估 / 收获汇总）"""
    hand = db.query(Hand).filter(Hand.id == hand_id).first()
    if hand is None:
        raise NotFoundException("季节不存在")

    room = db.query(Room).filter(Room.id == hand.room_id).first()

    # 获取所有投入
    bets = db.query(Bet).filter(Bet.hand_id == hand_id).order_by(Bet.created_at).all()

    # 获取收获篮
    pots = db.query(Pot).filter(Pot.hand_id == hand_id).all()

    # 获取收获结果
    results = db.query(HandResult).filter(HandResult.hand_id == hand_id).all()

    # 公共牌
    community_cards = json.loads(hand.community_cards) if hand.community_cards else []

    # 所有人手牌（key 为 player_id 字符串）
    hole_cards: dict = json.loads(hand.hole_cards) if hand.hole_cards else {}

    # 玩家列表（与当前 game.py /state 结构保持一致）
    players = db.query(RoomPlayer).filter(
        RoomPlayer.room_id == hand.room_id,
        RoomPlayer.is_active == 1,
        RoomPlayer.seat_number >= 0,
    ).order_by(RoomPlayer.seat_number).all()

    # 计算每人本轮投入
    current_round = hand.current_round if hand.current_round in ("preflop", "flop", "turn", "river") else "river"
    round_bets = [b for b in bets if b.round == current_round]
    player_round_bets: dict = {}
    for b in round_bets:
        player_round_bets[b.player_id] = player_round_bets.get(b.player_id, 0) + b.amount

    # 已 fold 的玩家
    folded_ids = {b.player_id for b in bets if b.action == "fold"}

    players_data = []
    for p in players:
        user = db.query(User).filter(User.id == p.user_id).first()
        role = None
        if p.id == hand.dealer_player_id:
            role = "D"
        elif p.id == hand.sb_player_id:
            role = "SB"
        elif p.id == hand.bb_player_id:
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

    # all_hole_cards: 跳过 fold 与 muck 的玩家（与 game.py /state 对齐）
    muck_pid = hand.muck_player_id
    all_hole_cards = {}
    for pid_str, cards in hole_cards.items():
        pid = int(pid_str)
        if pid in folded_ids:
            continue
        if muck_pid and pid == muck_pid:
            continue
        all_hole_cards[pid_str] = cards

    # 当前用户的手牌
    my_player = next((p for p in players if p.user_id == current_user.id), None)
    my_hole_cards = []
    if my_player and hole_cards:
        my_hole_cards = hole_cards.get(str(my_player.id), [])

    # 牌力评估（settled 状态下计算所有存活玩家的牌型）
    evaluations: dict = {}
    if hand.status == "settled" and room is not None:
        try:
            engine = HandEngine(db, room)
            evals = engine.get_hand_evaluations(hand)
            evaluations = {str(pid): ev for pid, ev in evals.items()}
        except Exception:
            # 评估失败不影响其他字段返回
            evaluations = {}

    return {
        "hand_id": hand.id,
        "hand_number": hand.hand_number,
        "current_round": hand.current_round,
        "status": hand.status,
        "pot_total": hand.pot_total,
        "dealer_player_id": hand.dealer_player_id,
        "sb_player_id": hand.sb_player_id,
        "bb_player_id": hand.bb_player_id,
        "ended_by_fold": bool(hand.ended_by_fold),
        "muck_player_id": hand.muck_player_id,
        "mucked_players": [int(x) for x in (hand.mucked_players or "").split(",") if x],
        "revealed_players": [int(x) for x in (hand.revealed_players or "").split(",") if x],
        "community_cards": community_cards,
        "hole_cards": hole_cards,
        "all_hole_cards": all_hole_cards,
        "my_hole_cards": my_hole_cards,
        "evaluations": evaluations,
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
