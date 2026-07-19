"""岛屿铃钱记 — API/WebSocket 层逻辑 bug 修复回归测试 (A1-A14)

覆盖:
- A1  结束房间强杀进行中手牌退款
- A2  历史接口底牌可见性
- A3  check 不再被静默转成 call
- A4  进行中入座/离局/站起守卫 + 最终结算口径 + 重进不双份
- A5  活跃度 touch 补齐 (以 rebuy 验证)
- A6  手动结算接口校验
- A7  rebuy 状态校验
- A8  start_game 校验前置 + 事务化
- A9  房间数值校验
- A10 /state 剔除 mucked_players
- A11 WebSocket 房间成员鉴权
- A12 next-round 推进守卫 (依赖引擎 turn 守卫生效)
- A13 手动同步接口 (manual_sync)
- A14 WS 聊天刷新活跃度 / 心跳不续命
"""

import json
import uuid
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.models import User, Room, RoomPlayer, Hand, Bet, Pot, HandResult
from app.utils.security import create_token
from app.utils import activity_tracker
import app.api.ws.game_ws as ws_module


def _auth(user_id: int) -> dict:
    token = create_token({"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def _mk_user(db, nickname: str) -> User:
    user = User(openid=f"openid_{uuid.uuid4().hex[:12]}", nickname=nickname, avatar_url="")
    db.add(user)
    db.commit()
    return user


def _setup_playing_room(client, db, n_players: int = 2, initial: int = 1000, sb: int = 25, bb: int = 50):
    """创建房间 → n 名玩家入座 → 开始游戏，返回上下文"""
    owner = _mk_user(db, "岛主")
    users = [owner] + [_mk_user(db, f"居民{i}") for i in range(1, n_players)]

    resp = client.post(
        "/v1/rooms",
        json={"name": "修复测试", "initial_chips": initial, "sb_amount": sb, "bb_amount": bb},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 200, resp.text
    room_id = resp.json()["room_id"]
    room_code = resp.json()["room_code"]

    for u in users[1:]:
        resp = client.post(f"/v1/rooms/{room_code}/join", headers=_auth(u.id))
        assert resp.status_code == 200, resp.text

    for i, u in enumerate(users):
        resp = client.post(f"/v1/rooms/{room_id}/sit", json={"seat_number": i}, headers=_auth(u.id))
        assert resp.status_code == 200, resp.text

    resp = client.post(f"/v1/rooms/{room_id}/start", headers=_auth(owner.id))
    assert resp.status_code == 200, resp.text
    hand_id = resp.json()["hand_id"]

    db.expire_all()
    players = (
        db.query(RoomPlayer)
        .filter(RoomPlayer.room_id == room_id)
        .order_by(RoomPlayer.seat_number)
        .all()
    )
    pid_to_uid = {p.id: p.user_id for p in players}
    uid_to_pid = {p.user_id: p.id for p in players}

    return SimpleNamespace(
        owner=owner,
        users=users,
        room_id=room_id,
        room_code=room_code,
        hand_id=hand_id,
        pid_to_uid=pid_to_uid,
        uid_to_pid=uid_to_pid,
        initial=initial,
    )


def _state(client, room_id: int, user_id: int) -> dict:
    resp = client.get(f"/v1/rooms/{room_id}/state", headers=_auth(user_id))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _act(client, ctx, action: str, amount: int = 0, expected: int = 200):
    """让当前轮到行动的玩家执行动作"""
    st = _state(client, ctx.room_id, ctx.owner.id)
    turn_pid = st["current_hand"]["turn_player_id"]
    assert turn_pid is not None, "当前没有轮到任何玩家行动"
    uid = ctx.pid_to_uid[turn_pid]
    resp = client.post(
        f"/v1/rooms/{ctx.room_id}/action",
        json={"action": action, "amount": amount},
        headers=_auth(uid),
    )
    assert resp.status_code == expected, resp.text
    return resp, turn_pid


def _finish_hand_by_fold(client, ctx):
    """当前行动玩家 fold，两人局直接进入 settling"""
    _, folded_pid = _act(client, ctx, "fold")
    st = _state(client, ctx.room_id, ctx.owner.id)
    assert st["current_hand"]["status"] == "settling"
    return folded_pid


def _settle(client, ctx):
    resp = client.post(f"/v1/rooms/{ctx.room_id}/settle", headers=_auth(ctx.owner.id))
    assert resp.status_code == 200, resp.text
    return resp


# ==================== A1 结束房间强杀手牌退款 ====================


def test_a1_finish_room_refunds_active_hand(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)

    # SB (preflop 先行动) raise 75 → 底池 = 25 + 50 + 75 = 150
    resp, _ = _act(client, ctx, "raise", amount=75)
    assert resp.json()["pot_total"] == 150

    # 手牌进行中直接结束房间
    resp = client.post(f"/v1/rooms/{ctx.room_id}/end-game", headers=_auth(ctx.owner.id))
    assert resp.status_code == 200, resp.text
    settlement = resp.json()["settlement"]

    # 所有玩家筹码恢复，全房间净盈亏总和为 0
    assert len(settlement) == 2
    assert sum(s["net_profit"] for s in settlement) == 0
    for s in settlement:
        assert s["final_chips"] == ctx.initial
        assert s["net_profit"] == 0

    # 手牌被置 settled、pot_total 清零、不生成 Pot/HandResult
    db_session.expire_all()
    hand = db_session.query(Hand).filter(Hand.id == ctx.hand_id).first()
    assert hand.status == "settled"
    assert hand.pot_total == 0
    assert db_session.query(Pot).filter(Pot.hand_id == ctx.hand_id).count() == 0
    assert db_session.query(HandResult).filter(HandResult.hand_id == ctx.hand_id).count() == 0


def test_a1_finish_room_settling_showdown_no_cap(client, db_session):
    """强杀正常 showdown 的 settling 手牌 (有 fold 记录): 引擎未 cap，须全额退款

    旧口径按 min(投入, max_folded_bet) 退款 — 本场景 max_folded=0 会全池蒸发。
    """
    ctx = _setup_playing_room(client, db_session, n_players=3)

    # Preflop (3 人: UTG 先行动): UTG 0 注 fold, SB call, BB check
    # (每轮下注结束后 API 自动推进阶段)
    _act(client, ctx, "fold")
    _act(client, ctx, "call")
    _act(client, ctx, "check")

    # flop / turn / river: 两家一路 check, river 结束后自动进 showdown (settling)
    for _ in range(3):
        _act(client, ctx, "check")
        _act(client, ctx, "check")

    db_session.expire_all()
    hand = db_session.query(Hand).filter(Hand.id == ctx.hand_id).first()
    assert hand.status == "settling"
    assert not hand.ended_by_fold

    # 强杀: 底池 = SB 50 + BB 50 = 100, 应全额退回
    resp = client.post(f"/v1/rooms/{ctx.room_id}/end-game", headers=_auth(ctx.owner.id))
    assert resp.status_code == 200, resp.text
    settlement = resp.json()["settlement"]

    assert sum(s["net_profit"] for s in settlement) == 0
    for s in settlement:
        assert s["final_chips"] == ctx.initial
        assert s["net_profit"] == 0


def test_a1_finish_room_settling_ended_by_fold_no_double_refund(client, db_session):
    """强杀 ended_by_fold 的 settling 手牌: 引擎已退未跟注部分，强杀不得重复退款"""
    ctx = _setup_playing_room(client, db_session, n_players=2)

    # SB all-in, BB fold → 自动 settling (ended_by_fold), 引擎已退 SB 未跟注部分
    _act(client, ctx, "allin")
    _act(client, ctx, "fold")

    db_session.expire_all()
    hand = db_session.query(Hand).filter(Hand.id == ctx.hand_id).first()
    assert hand.status == "settling"
    assert hand.ended_by_fold == 1

    resp = client.post(f"/v1/rooms/{ctx.room_id}/end-game", headers=_auth(ctx.owner.id))
    assert resp.status_code == 200, resp.text
    settlement = resp.json()["settlement"]

    # 全部筹码恰好退回 (重复退款会让净盈亏总和 > 0)
    assert sum(s["net_profit"] for s in settlement) == 0
    for s in settlement:
        assert s["final_chips"] == ctx.initial
        assert s["net_profit"] == 0


# ==================== A2 历史接口底牌可见性 ====================


def test_a2_history_hides_others_hole_cards_in_progress(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)
    other = ctx.users[1]
    my_pid = ctx.uid_to_pid[other.id]

    resp = client.get(f"/v1/hands/{ctx.hand_id}", headers=_auth(other.id))
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # 进行中: hole_cards 只含本人，all_hole_cards 为空
    assert set(data["hole_cards"].keys()) == {str(my_pid)}
    assert len(data["hole_cards"][str(my_pid)]) == 2
    assert data["all_hole_cards"] == {}
    assert len(data["my_hole_cards"]) == 2


def test_a2_history_rejects_non_member(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)
    outsider = _mk_user(db_session, "路人")

    resp = client.get(f"/v1/hands/{ctx.hand_id}", headers=_auth(outsider.id))
    assert resp.status_code in (403, 404)


def test_a2_history_settled_excludes_folded(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)
    folded_pid = _finish_hand_by_fold(client, ctx)
    winner_pid = next(pid for pid in ctx.pid_to_uid if pid != folded_pid)
    _settle(client, ctx)

    winner_uid = ctx.pid_to_uid[winner_pid]
    folded_uid = ctx.pid_to_uid[folded_pid]

    # 赢家视角: 已结算详情剔除 fold 玩家
    resp = client.get(f"/v1/hands/{ctx.hand_id}", headers=_auth(winner_uid))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "settled"
    assert str(folded_pid) not in data["hole_cards"]
    assert str(folded_pid) not in data["all_hole_cards"]
    assert str(winner_pid) in data["hole_cards"]

    # fold 玩家视角: 公共口径同样剔除，但自己的底牌仍可通过 my_hole_cards 回顾
    resp = client.get(f"/v1/hands/{ctx.hand_id}", headers=_auth(folded_uid))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert str(folded_pid) not in data["hole_cards"]
    assert len(data["my_hole_cards"]) == 2


# ==================== A3 check 不再被转成 call ====================


def test_a3_check_rejected_when_to_call_positive(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)
    # preflop SB 先行动，需要跟注 25 → check 必须 400
    _act(client, ctx, "check", expected=400)


def test_a3_check_recorded_as_check_when_free(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)

    _act(client, ctx, "call")            # SB 跟注
    resp, bb_pid = _act(client, ctx, "check")  # BB 无需跟注 → check 合法
    data = resp.json()
    assert data["action"] == "check"
    assert data["amount"] == 0

    # Bet 流水记为 action="check", amount=0
    db_session.expire_all()
    check_bets = (
        db_session.query(Bet)
        .filter(Bet.hand_id == ctx.hand_id, Bet.player_id == bb_pid, Bet.action == "check")
        .all()
    )
    assert len(check_bets) == 1
    assert check_bets[0].amount == 0


# ==================== A4 入座/离局/站起守卫 ====================


def test_a4_sit_rejected_during_hand_allowed_between_hands(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)

    # 牌局进行中加入 (不入座) 允许
    late = _mk_user(db_session, "迟到者")
    resp = client.post(f"/v1/rooms/{ctx.room_code}/join", headers=_auth(late.id))
    assert resp.status_code == 200, resp.text

    # 进行中入座 → 400
    resp = client.post(f"/v1/rooms/{ctx.room_id}/sit", json={"seat_number": 5}, headers=_auth(late.id))
    assert resp.status_code == 400

    # 手牌结束后 (两手之间) 入座 → 200
    _finish_hand_by_fold(client, ctx)
    _settle(client, ctx)
    resp = client.post(f"/v1/rooms/{ctx.room_id}/sit", json={"seat_number": 5}, headers=_auth(late.id))
    assert resp.status_code == 200, resp.text


def test_a4_leave_auto_fold_and_game_continues(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=3)

    # 当前轮到行动的玩家离局
    st = _state(client, ctx.room_id, ctx.owner.id)
    leaver_pid = st["current_hand"]["turn_player_id"]
    leaver_uid = ctx.pid_to_uid[leaver_pid]

    resp = client.delete(f"/v1/rooms/{ctx.room_id}/leave", headers=_auth(leaver_uid))
    assert resp.status_code == 200, resp.text

    # 自动补了一条 fold
    db_session.expire_all()
    fold_bets = (
        db_session.query(Bet)
        .filter(Bet.hand_id == ctx.hand_id, Bet.player_id == leaver_pid, Bet.action == "fold")
        .all()
    )
    assert len(fold_bets) == 1

    # 牌局可继续: turn 推进到其他玩家，且后续行动成功
    st = _state(client, ctx.room_id, ctx.owner.id)
    assert st["current_hand"]["status"] == "betting"
    assert st["current_hand"]["turn_player_id"] is not None
    assert st["current_hand"]["turn_player_id"] != leaver_pid
    _act(client, ctx, "call")

    # 离局者仍出现在最终结算，全房间净盈亏总和为 0
    resp = client.post(f"/v1/rooms/{ctx.room_id}/end-game", headers=_auth(ctx.owner.id))
    assert resp.status_code == 200, resp.text
    settlement = resp.json()["settlement"]
    assert len(settlement) == 3
    assert leaver_pid in {s["player_id"] for s in settlement}
    assert sum(s["net_profit"] for s in settlement) == 0


def test_a4_stand_auto_fold(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=3)

    st = _state(client, ctx.room_id, ctx.owner.id)
    stander_pid = st["current_hand"]["turn_player_id"]
    stander_uid = ctx.pid_to_uid[stander_pid]

    # 未 fold 的参与者 (即使 chip>0) 也可站起，但会先被自动 fold
    resp = client.post(f"/v1/rooms/{ctx.room_id}/stand", headers=_auth(stander_uid))
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    fold_bets = (
        db_session.query(Bet)
        .filter(Bet.hand_id == ctx.hand_id, Bet.player_id == stander_pid, Bet.action == "fold")
        .all()
    )
    assert len(fold_bets) == 1

    player = db_session.query(RoomPlayer).filter(RoomPlayer.id == stander_pid).first()
    assert player.seat_number == -1

    # 牌局继续
    st = _state(client, ctx.room_id, ctx.owner.id)
    assert st["current_hand"]["status"] == "betting"
    assert st["current_hand"]["turn_player_id"] != stander_pid


def test_a4_rejoin_reuses_row_no_double_buyin(client, db_session):
    owner = _mk_user(db_session, "岛主")
    joiner = _mk_user(db_session, "居民")

    resp = client.post("/v1/rooms", json={"initial_chips": 1000}, headers=_auth(owner.id))
    room_id = resp.json()["room_id"]
    room_code = resp.json()["room_code"]

    resp = client.post(f"/v1/rooms/{room_code}/join", headers=_auth(joiner.id))
    assert resp.status_code == 200

    resp = client.delete(f"/v1/rooms/{room_id}/leave", headers=_auth(joiner.id))
    assert resp.status_code == 200

    # 离局后重进: 复用原行
    resp = client.post(f"/v1/rooms/{room_code}/join", headers=_auth(joiner.id))
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    rows = (
        db_session.query(RoomPlayer)
        .filter(RoomPlayer.room_id == room_id, RoomPlayer.user_id == joiner.id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].is_active == 1
    assert rows[0].chip_count == 1000  # 没有双份买入


# ==================== A5 活跃度 touch (rebuy 验证) ====================


def test_a5_rebuy_touches_activity_tracker(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)
    _finish_hand_by_fold(client, ctx)
    _settle(client, ctx)

    # 把房间活跃时间拨到 10 分钟前，模拟久无行动
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    activity_tracker._room_last_action[ctx.room_id] = stale

    resp = client.post(
        f"/v1/rooms/{ctx.room_id}/rebuy",
        json={"amount": 500},
        headers=_auth(ctx.owner.id),
    )
    assert resp.status_code == 200, resp.text

    assert activity_tracker.get(ctx.room_id) > stale


# ==================== A6 手动结算校验 ====================


def test_a6_manual_settle_validation(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)
    folded_pid = _finish_hand_by_fold(client, ctx)
    winner_pid = next(pid for pid in ctx.pid_to_uid if pid != folded_pid)

    db_session.expire_all()
    pot = db_session.query(Pot).filter(Pot.hand_id == ctx.hand_id).first()
    assert pot is not None
    eligible = [int(x) for x in pot.eligible_player_ids.split(",") if x]
    assert winner_pid in eligible

    url = f"/v1/hands/{ctx.hand_id}/settle"
    headers = _auth(ctx.owner.id)

    # 金额与池不符 → 400
    resp = client.post(url, json={"results": [{"pot_id": pot.id, "winner_ids": [winner_pid], "amount": pot.amount - 1}]}, headers=headers)
    assert resp.status_code == 400

    # 负数金额 → 400
    resp = client.post(url, json={"results": [{"pot_id": pot.id, "winner_ids": [winner_pid], "amount": -pot.amount}]}, headers=headers)
    assert resp.status_code == 400

    # 赢家不在 eligible → 400
    resp = client.post(url, json={"results": [{"pot_id": pot.id, "winner_ids": [folded_pid], "amount": pot.amount}]}, headers=headers)
    assert resp.status_code == 400

    # 其他手牌的 pot → 400
    resp = client.post(url, json={"results": [{"pot_id": 999999, "winner_ids": [winner_pid], "amount": pot.amount}]}, headers=headers)
    assert resp.status_code == 400

    # 遗漏 pot (分配不完整) → 400
    resp = client.post(url, json={"results": []}, headers=headers)
    assert resp.status_code == 400

    # 合法结算 → 200
    resp = client.post(url, json={"results": [{"pot_id": pot.id, "winner_ids": [winner_pid], "amount": pot.amount}]}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["winner_id"] == winner_pid
    assert resp.json()["results"][0]["amount_won"] == pot.amount


# ==================== A7 rebuy 状态校验 ====================


def test_a7_rebuy_rejected_for_participant_mid_hand(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)

    # 当前行动玩家 all-in
    _, allin_pid = _act(client, ctx, "allin")
    allin_uid = ctx.pid_to_uid[allin_pid]

    # 本手参与者补给 → 400
    resp = client.post(
        f"/v1/rooms/{ctx.room_id}/rebuy",
        json={"amount": 500},
        headers=_auth(allin_uid),
    )
    assert resp.status_code == 400


def test_a7_rebuy_rejected_when_not_playing(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)

    resp = client.post(f"/v1/rooms/{ctx.room_id}/end-game", headers=_auth(ctx.owner.id))
    assert resp.status_code == 200

    # finished 状态补给 → 400
    resp = client.post(
        f"/v1/rooms/{ctx.room_id}/rebuy",
        json={"amount": 500},
        headers=_auth(ctx.owner.id),
    )
    assert resp.status_code == 400


# ==================== A8 start_game 校验前置 + 事务化 ====================


def test_a8_start_game_zero_chips_rolls_back(client, db_session):
    owner = _mk_user(db_session, "岛主")
    joiner = _mk_user(db_session, "居民")

    resp = client.post("/v1/rooms", json={"initial_chips": 1000}, headers=_auth(owner.id))
    room_id = resp.json()["room_id"]
    room_code = resp.json()["room_code"]

    resp = client.post(f"/v1/rooms/{room_code}/join", headers=_auth(joiner.id))
    assert resp.status_code == 200

    for i, u in enumerate([owner, joiner]):
        resp = client.post(f"/v1/rooms/{room_id}/sit", json={"seat_number": i}, headers=_auth(u.id))
        assert resp.status_code == 200

    # 直接把两名玩家筹码清零 (绕过创建校验)
    db_session.expire_all()
    for p in db_session.query(RoomPlayer).filter(RoomPlayer.room_id == room_id).all():
        p.chip_count = 0
    db_session.commit()

    resp = client.post(f"/v1/rooms/{room_id}/start", headers=_auth(owner.id))
    assert resp.status_code == 400

    # 房间状态回滚，仍是 waiting，未卡 playing
    db_session.expire_all()
    room = db_session.query(Room).filter(Room.id == room_id).first()
    assert room.status == "waiting"
    assert db_session.query(Hand).filter(Hand.room_id == room_id).count() == 0


# ==================== A9 数值校验 ====================


def test_a9_create_room_rejects_non_positive_numbers(client, db_session):
    owner = _mk_user(db_session, "岛主")

    # 负盲注 (sb=-100, bb=-50 满足 bb>=sb*2 的旧漏洞)
    resp = client.post("/v1/rooms", json={"sb_amount": -100, "bb_amount": -50}, headers=_auth(owner.id))
    assert resp.status_code == 422

    # 零初始筹码
    resp = client.post("/v1/rooms", json={"initial_chips": 0}, headers=_auth(owner.id))
    assert resp.status_code == 422

    # 零盲注
    resp = client.post("/v1/rooms", json={"sb_amount": 0}, headers=_auth(owner.id))
    assert resp.status_code == 422


def test_a9_update_room_validation(client, db_session):
    owner = _mk_user(db_session, "岛主")
    resp = client.post("/v1/rooms", json={"initial_chips": 1000}, headers=_auth(owner.id))
    room_id = resp.json()["room_id"]

    # 负数 → 422
    resp = client.patch(f"/v1/rooms/{room_id}", json={"sb_amount": -5}, headers=_auth(owner.id))
    assert resp.status_code == 422

    # 已有玩家 (岛主行在建房时自动创建) 禁止改 initial_chips → 400
    resp = client.patch(f"/v1/rooms/{room_id}", json={"initial_chips": 5000}, headers=_auth(owner.id))
    assert resp.status_code == 400

    # 破坏 bb >= 2*sb → 400
    resp = client.patch(f"/v1/rooms/{room_id}", json={"sb_amount": 30}, headers=_auth(owner.id))
    assert resp.status_code == 400

    # 合法修改 → 200
    resp = client.patch(f"/v1/rooms/{room_id}", json={"sb_amount": 20}, headers=_auth(owner.id))
    assert resp.status_code == 200


# ==================== A10 /state 剔除 mucked_players ====================


def _play_checkdown_to_showdown(client, ctx):
    """两名玩家全程 check/call 到 showdown"""
    _act(client, ctx, "call")    # SB preflop
    _act(client, ctx, "check")   # BB preflop → flop
    for _ in range(3):           # flop / turn / river 双方 check
        _act(client, ctx, "check")
        _act(client, ctx, "check")
    st = _state(client, ctx.room_id, ctx.owner.id)
    assert st["current_hand"]["status"] == "settling"


def test_a10_state_hides_mucked_player(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)
    _play_checkdown_to_showdown(client, ctx)

    st = _state(client, ctx.room_id, ctx.owner.id)
    aggressor_pid = st["current_hand"]["last_aggressor_id"]
    mucker_pid = next(pid for pid in ctx.pid_to_uid if pid != aggressor_pid)
    mucker_uid = ctx.pid_to_uid[mucker_pid]

    # 非最后激进者选择盖牌
    resp = client.post(
        f"/v1/rooms/{ctx.room_id}/reveal",
        json={"action": "muck"},
        headers=_auth(mucker_uid),
    )
    assert resp.status_code == 200, resp.text

    st = _state(client, ctx.room_id, ctx.owner.id)
    hand = st["current_hand"]
    assert mucker_pid in hand["mucked_players"]

    # all_hole_cards 与 evaluations 均剔除 muck 玩家
    assert str(mucker_pid) not in hand["all_hole_cards"]
    assert str(mucker_pid) not in hand["evaluations"]
    assert str(aggressor_pid) in hand["all_hole_cards"]
    assert str(aggressor_pid) in hand["evaluations"]


# ==================== A11 WebSocket 房间成员鉴权 ====================


@pytest.fixture
def ws_db(db_session, monkeypatch):
    """让 WS 处理器使用测试数据库"""
    sm = sessionmaker(autocommit=False, autoflush=False, bind=db_session.bind)
    monkeypatch.setattr(ws_module, "SessionLocal", sm)
    return db_session


def test_a11_ws_rejects_non_member(client, ws_db):
    owner = _mk_user(ws_db, "岛主")
    outsider = _mk_user(ws_db, "路人")

    resp = client.post("/v1/rooms", json={}, headers=_auth(owner.id))
    room_id = resp.json()["room_id"]

    token = create_token({"sub": str(outsider.id)})
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/rooms/{room_id}?token={token}"):
            pass
    assert exc_info.value.code == 4003


def test_a11_ws_rejects_bad_token(client, ws_db):
    owner = _mk_user(ws_db, "岛主")
    resp = client.post("/v1/rooms", json={}, headers=_auth(owner.id))
    room_id = resp.json()["room_id"]

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/rooms/{room_id}?token=not-a-token"):
            pass
    assert exc_info.value.code == 4001


def test_a11_ws_member_connects_and_pings(client, ws_db):
    owner = _mk_user(ws_db, "岛主")
    resp = client.post("/v1/rooms", json={}, headers=_auth(owner.id))
    room_id = resp.json()["room_id"]

    token = create_token({"sub": str(owner.id)})
    with client.websocket_connect(f"/ws/rooms/{room_id}?token={token}") as ws:
        ws.send_text(json.dumps({"type": "ping"}))
        for _ in range(3):
            msg = json.loads(ws.receive_text())
            if msg["type"] == "pong":
                break
        else:
            pytest.fail("未收到 pong")


# ==================== A12 next-round 推进守卫 ====================


def test_a12_advance_shortcut_rejected_when_turn_pending(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)

    # 有玩家未行动时推进 → 400 (路由自身守卫)
    resp = client.post(f"/v1/rooms/{ctx.room_id}/advance", headers=_auth(ctx.owner.id))
    assert resp.status_code == 400


def test_a12_next_round_rejected_when_turn_pending(client, db_session):
    ctx = _setup_playing_room(client, db_session, n_players=2)

    # 有玩家未行动时推进 → 400 (依赖引擎 advance_round 的 turn 守卫)
    resp = client.post(f"/v1/hands/{ctx.hand_id}/next-round", headers=_auth(ctx.owner.id))
    assert resp.status_code == 400


# ==================== A13 手动同步接口 ====================


def test_a13_manual_sync_member_ok(client, db_session):
    """房间成员调用 /sync 应返回 200 {ok: true}"""
    ctx = _setup_playing_room(client, db_session, n_players=2)
    resp = client.post(f"/v1/rooms/{ctx.room_id}/sync", headers=_auth(ctx.owner.id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


def test_a13_manual_sync_non_member_rejected(client, db_session):
    """非房间成员调用 /sync 应被拒绝"""
    ctx = _setup_playing_room(client, db_session, n_players=2)
    outsider = _mk_user(db_session, "路人")
    resp = client.post(f"/v1/rooms/{ctx.room_id}/sync", headers=_auth(outsider.id))
    assert resp.status_code in (403, 404)


# ==================== A14 WS 聊天刷新活跃度 / 心跳不续命 ====================


def test_a14_chat_touches_activity_tracker(client, ws_db):
    """发送 chat 消息后 activity_tracker 时间戳应被更新"""
    owner = _mk_user(ws_db, "岛主")
    resp = client.post("/v1/rooms", json={}, headers=_auth(owner.id))
    room_id = resp.json()["room_id"]

    # 把活跃时间拨到 15 分钟前，模拟久无行动
    stale = datetime.now(timezone.utc) - timedelta(minutes=15)
    activity_tracker._room_last_action[room_id] = stale

    token = create_token({"sub": str(owner.id)})
    with client.websocket_connect(f"/ws/rooms/{room_id}?token={token}") as ws:
        ws.send_text(json.dumps({"type": "chat", "content": "大家好"}))
        # 等待一条广播回去 (chat 会广播给同房间玩家，也包含自己)
        for _ in range(3):
            msg = json.loads(ws.receive_text())
            if msg["type"] == "chat":
                break

    # 聊天应已刷新活跃度时间戳
    updated = activity_tracker.get(room_id)
    assert updated is not None
    assert updated > stale


def test_a14_ping_does_not_touch_activity_tracker(client, ws_db):
    """仅发送 ping 心跳时 activity_tracker 不应被重置"""
    owner = _mk_user(ws_db, "岛主")
    resp = client.post("/v1/rooms", json={}, headers=_auth(owner.id))
    room_id = resp.json()["room_id"]

    # 先清除此房间的活跃度记录，确保 ping 前未有时间戳
    activity_tracker._room_last_action.pop(room_id, None)

    token = create_token({"sub": str(owner.id)})
    with client.websocket_connect(f"/ws/rooms/{room_id}?token={token}") as ws:
        ws.send_text(json.dumps({"type": "ping"}))
        for _ in range(3):
            msg = json.loads(ws.receive_text())
            if msg["type"] == "pong":
                break

    # 心跳不应创建活跃度记录
    assert room_id not in activity_tracker._room_last_action
