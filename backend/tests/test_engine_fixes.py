"""岛屿铃钱记 — 引擎 Bug 修复回归测试 (E1-E8)

覆盖:
- E1: fold 退款 uncalled-bet 规则 (showdown 不 cap / fold 结束退未跟注部分)
- E2: turn_player_id=None 时任何人不可下注 + place_bet 参与者/在座/未 fold 校验
- E3: advance_round 必须等本轮下注结束
- E4: 最小加注额 = 本轮最后一次加注的增量 (非常数 BB)
- E5: last_aggressor 按 Bet.id (自增序) 取最后激进者
- E6: 平分池余数按庄位距离分配，筹码不蒸发
- E7: 行动/存活判定只看本手参与者 (hole_cards key)
- E8: 前庄家座位消失时庄位轮转不跳位
"""

import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import User, Room, RoomPlayer, Hand, Bet, Pot, HandResult
from app.engine.hand_engine import HandEngine, get_action_order
from app.engine.deck import Card, cards_to_json
from app.utils import BadRequestException


# ======================== Fixtures / 辅助 ========================

@pytest.fixture
def db():
    """每个测试独立的内存数据库"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100, dealer_seat=0):
    """辅助: 创建房间 + 入座玩家 (座位 0..n-1)"""
    owner = User(openid="test_owner", nickname="岛主", avatar_url="")
    db.add(owner)
    db.flush()

    room = Room(
        room_code="TEST01",
        name="测试房间",
        owner_id=owner.id,
        initial_chips=chips,
        sb_amount=sb,
        bb_amount=bb,
        dealer_seat=dealer_seat,
    )
    db.add(room)
    db.flush()

    players = []
    for i in range(num_players):
        u = User(openid=f"player_{i}", nickname=f"玩家{i}", avatar_url="")
        db.add(u)
        db.flush()
        rp = RoomPlayer(
            room_id=room.id,
            user_id=u.id,
            seat_number=i,
            chip_count=chips,
            is_active=1,
        )
        db.add(rp)
        db.flush()
        players.append(rp)

    db.commit()
    return room, players


def _add_player(db, room, seat_number, chips=10000):
    """辅助: 向已有房间追加一名入座玩家 (模拟牌局中途入座)"""
    u = User(openid=f"late_seat{seat_number}", nickname="迟到者", avatar_url="")
    db.add(u)
    db.flush()
    rp = RoomPlayer(
        room_id=room.id,
        user_id=u.id,
        seat_number=seat_number,
        chip_count=chips,
        is_active=1,
    )
    db.add(rp)
    db.commit()
    return rp


def _create_hand_with_bets(db, players, bet_data, ended_by_fold=0,
                           hole_cards="{}", community_cards="[]"):
    """
    辅助: 直接构造 Hand + Bet 记录 (绕过正常流程)

    bet_data: [(player_idx, action, amount), ...]
    """
    room = db.query(Room).first()
    hand = Hand(
        room_id=room.id,
        hand_number=1,
        dealer_player_id=players[0].id,
        sb_player_id=players[0].id,
        bb_player_id=players[1].id,
        current_round="showdown",
        status="settling",
        pot_total=0,
        community_cards=community_cards,
        hole_cards=hole_cards,
        deck_state=None,
        ended_by_fold=ended_by_fold,
    )
    db.add(hand)
    db.flush()

    total_pot = 0
    for pidx, action, amount in bet_data:
        db.add(Bet(
            hand_id=hand.id,
            player_id=players[pidx].id,
            round="preflop",
            action=action,
            amount=amount,
        ))
        players[pidx].chip_count -= amount
        total_pot += amount

    hand.pot_total = total_pot
    db.flush()
    return hand


def _pot_eligible(pot):
    return [int(x) for x in pot.eligible_player_ids.split(",") if x]


# ======================== E1: fold 退款 uncalled-bet 规则 ========================

class TestE1UncalledBetRefund:
    """E1: 正常 showdown 不 cap；fold 到只剩 1 人时只退未跟注部分"""

    def test_showdown_with_folded_player_no_cap(self, db):
        """
        回归①: A 投 100 fold, B/C 各投 500 打到 showdown
        → 总池 1100 (主池 300 + 边池 800), B/C eligible, A 不 eligible
        → 任何人不退款 (修复前被错算成 300)
        """
        room, players = _make_room_with_players(db, num_players=3, chips=10000)
        hand = _create_hand_with_bets(db, players, [
            (0, "blind", 100),   # A: total=100
            (1, "call", 500),    # B: total=500
            (2, "call", 500),    # C: total=500
            (0, "fold", 0),      # A fold (ended_by_fold=0, 正常 showdown)
        ])

        chips_before = {p.id: p.chip_count for p in players}
        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # 无人退款
        for p in players:
            assert p.chip_count == chips_before[p.id]

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 2
        main = next(p for p in pots if p.pot_type == "main")
        side = next(p for p in pots if p.pot_type == "side")
        assert main.amount == 300   # 100×3
        assert side.amount == 800   # 400×2
        assert sum(p.amount for p in pots) == 1100
        # B/C eligible, A(fold) 不 eligible
        for pot in (main, side):
            eligible = _pot_eligible(pot)
            assert players[1].id in eligible
            assert players[2].id in eligible
            assert players[0].id not in eligible

    def test_fold_to_one_uncalled_bet_refunded(self, db):
        """
        回归②: fold 到只剩 1 人, 未跟注部分退回本人
        A(BB=100) fold, B all-in 10000 (ended_by_fold=1)
        → B 退 9900, 主池 200, B 唯一 eligible (保持现有正确行为)
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100)
        hand = _create_hand_with_bets(db, players, [
            (0, "blind", 50),     # B: SB
            (1, "blind", 100),    # A: BB
            (0, "allin", 9950),   # B: all-in total=10000
            (1, "fold", 0),       # A fold
        ], ended_by_fold=1)

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # B 退回未跟注的 9900
        assert players[0].chip_count == 9900
        # A 不变 (fold 者的 100 留在池内)
        assert players[1].chip_count == 9900

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 1
        assert pots[0].amount == 200
        assert _pot_eligible(pots[0]) == [players[0].id]

    def test_folded_zero_bet_showdown_pot_not_zeroed(self, db):
        """
        回归③: UTG 0 注 fold, 两人各 500 打到 showdown
        → 池 1000 不清零 (修复前因 cap=0 全池清零)
        """
        room, players = _make_room_with_players(db, num_players=3, chips=10000)
        hand = _create_hand_with_bets(db, players, [
            (2, "fold", 0),      # UTG: 0 注 fold
            (0, "call", 500),    # A: total=500
            (1, "call", 500),    # B: total=500
        ])

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 1
        assert pots[0].amount == 1000  # 500×2, 不清零
        eligible = _pot_eligible(pots[0])
        assert set(eligible) == {players[0].id, players[1].id}
        # 无人退款
        assert players[0].chip_count == 9500
        assert players[1].chip_count == 9500
        assert players[2].chip_count == 10000


# ======================== E2: turn 守卫 + place_bet 校验 ========================

class TestE2TurnGuard:
    """E2: turn_player_id=None 时任何人不可下注"""

    def test_no_bet_allowed_after_round_ends(self, db):
        """一轮下注结束 (turn=None) 后, 任何玩家下注必须抛 BadRequestException"""
        room, players = _make_room_with_players(db, num_players=2, chips=10000)
        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        p_sb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.sb_player_id).first()
        p_bb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.bb_player_id).first()

        # Preflop: SB call, BB check → 本轮结束
        engine.place_bet(hand, p_sb, "call")
        db.refresh(hand)
        engine.place_bet(hand, p_bb, "check")
        db.refresh(hand)
        assert hand.turn_player_id is None

        # 此时任何玩家 (含本手参与者) 下注都必须被拒绝
        with pytest.raises(BadRequestException):
            engine.place_bet(hand, p_sb, "check")
        with pytest.raises(BadRequestException):
            engine.place_bet(hand, p_bb, "raise", 500)

    def test_non_participant_cannot_bet(self, db):
        """place_bet 校验: 非本手参与者不可下注 (即使伪造 turn 指向他)"""
        room, players = _make_room_with_players(db, num_players=2, chips=10000)
        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        third = _add_player(db, room, seat_number=2)
        # 伪造 turn 指向第三人 (绕过 turn 守卫, 单独验证参与者校验)
        hand.turn_player_id = third.id
        db.flush()

        with pytest.raises(BadRequestException, match="参与者"):
            engine.place_bet(hand, third, "call")

    def test_folded_player_cannot_bet(self, db):
        """place_bet 校验: 已 fold 的玩家不可再行动"""
        room, players = _make_room_with_players(db, num_players=3, chips=10000)
        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        # UTG fold (3 人局牌局继续)
        utg = db.query(RoomPlayer).filter(RoomPlayer.id == hand.turn_player_id).first()
        engine.place_bet(hand, utg, "fold")
        db.refresh(hand)
        assert hand.status == "betting"

        # 伪造 turn 指向已 fold 的 UTG
        hand.turn_player_id = utg.id
        db.flush()
        with pytest.raises(BadRequestException, match="弃牌"):
            engine.place_bet(hand, utg, "call")

    def test_standing_player_cannot_bet(self, db):
        """place_bet 校验: 已离局 (is_active=0) 的参与者不可行动"""
        room, players = _make_room_with_players(db, num_players=2, chips=10000)
        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        actor = db.query(RoomPlayer).filter(RoomPlayer.id == hand.turn_player_id).first()
        # 玩家站起来但未 fold
        actor.is_active = 0
        db.flush()

        with pytest.raises(BadRequestException, match="座位"):
            engine.place_bet(hand, actor, "call")


# ======================== E3: advance_round 守卫 ========================

class TestE3AdvanceRoundGuard:
    """E3: 本轮下注未结束 (turn_player_id 非 None) 时禁止推进"""

    def test_advance_rejected_while_player_pending(self, db):
        """还有玩家未行动时, 岛主不能推进阶段"""
        room, players = _make_room_with_players(db, num_players=2, chips=10000)
        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        # preflop 刚开始, turn = SB, 此时推进必须被拒绝
        assert hand.turn_player_id is not None
        with pytest.raises(BadRequestException):
            engine.advance_round(hand)

        # 完成本轮后可以正常推进
        p_sb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.sb_player_id).first()
        p_bb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.bb_player_id).first()
        engine.place_bet(hand, p_sb, "call")
        db.refresh(hand)
        # SB call 后轮到 BB, 仍不能推进
        assert hand.turn_player_id is not None
        with pytest.raises(BadRequestException):
            engine.advance_round(hand)

        engine.place_bet(hand, p_bb, "check")
        db.refresh(hand)
        assert hand.turn_player_id is None
        engine.advance_round(hand)
        db.refresh(hand)
        assert hand.current_round == "flop"


# ======================== E4: 最小加注额 ========================

class TestE4MinRaise:
    """E4: 最小加注增量 = 本轮最后一次加注的增量"""

    def test_min_raise_follows_last_raise_increment(self, db):
        """BB=100, A raise 到 300 (增量 200) → 下一家最小加注到 500 而非 400"""
        room, players = _make_room_with_players(db, num_players=3, chips=10000, sb=50, bb=100)
        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        # UTG (A) raise 到 300
        p_a = db.query(RoomPlayer).filter(RoomPlayer.id == hand.turn_player_id).first()
        engine.place_bet(hand, p_a, "raise", 300)
        db.refresh(hand)

        # 下一家 (B): 最小加注总额 = 300 + 200 = 500
        p_b = db.query(RoomPlayer).filter(RoomPlayer.id == hand.turn_player_id).first()
        # 加到 400 应被拒绝
        with pytest.raises(BadRequestException, match="最少需要 450"):
            engine.place_bet(hand, p_b, "raise", 350)  # B 已有 SB 50, 350+50=400 < 500
        # 加到 500 合法
        engine.place_bet(hand, p_b, "raise", 450)      # 450+50=500
        db.refresh(hand)

        # 再下一家 (BB): 增量仍为 200 → 最小加注总额 700
        p_c = db.query(RoomPlayer).filter(RoomPlayer.id == hand.turn_player_id).first()
        with pytest.raises(BadRequestException):
            engine.place_bet(hand, p_c, "raise", 500)  # 已有 BB 100, 500+100=600 < 700
        engine.place_bet(hand, p_c, "raise", 600)      # 600+100=700
        db.refresh(hand)
        assert hand.status == "betting"

    def test_min_raise_defaults_to_bb(self, db):
        """无人加注时, 最小加注增量 = BB"""
        room, players = _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100)
        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        p_sb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.turn_player_id).first()
        # SB raise 总额 150 (增量 50 < BB=100) 应被拒绝
        with pytest.raises(BadRequestException):
            engine.place_bet(hand, p_sb, "raise", 100)  # 50+100=150 < 100+100=200
        # 总额 200 合法
        engine.place_bet(hand, p_sb, "raise", 150)      # 50+150=200
        db.refresh(hand)
        p_bb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.turn_player_id).first()
        assert p_bb.id == hand.bb_player_id


# ======================== E5: last_aggressor 按 Bet.id ========================

class TestE5LastAggressor:
    """E5: 同秒多次 raise 时, last_aggressor 必须是最后加注者"""

    def test_same_second_raises_pick_last_by_id(self, db):
        """两条 raise 记录 created_at 相同 (秒级) → 按 id 取后者"""
        room, players = _make_room_with_players(db, num_players=2, chips=10000)
        p1, p2 = players[0], players[1]

        hand = Hand(
            room_id=room.id, hand_number=1,
            dealer_player_id=p1.id, sb_player_id=p1.id, bb_player_id=p2.id,
            current_round="showdown", status="settling", pot_total=600,
            community_cards="[]", hole_cards="{}", deck_state=None,
        )
        db.add(hand)
        db.flush()

        same_time = datetime(2026, 1, 1, 12, 0, 0)
        # p1 先 raise, p2 后 raise, created_at 相同 (模拟同秒)
        db.add(Bet(hand_id=hand.id, player_id=p1.id, round="preflop",
                   action="raise", amount=200, created_at=same_time))
        db.flush()
        db.add(Bet(hand_id=hand.id, player_id=p2.id, round="preflop",
                   action="raise", amount=400, created_at=same_time))
        db.flush()

        engine = HandEngine(db, room)
        engine._compute_last_aggressor(hand)

        assert hand.last_aggressor_id == p2.id, \
            f"last_aggressor 应为后加注的 p2, 实际 {hand.last_aggressor_id}"
        assert hand.revealed_players == str(p2.id)


# ======================== E6: 平分池余数分配 ========================

class TestE6SplitRemainder:
    """E6: 平分池余数按 (座位号 - 庄位) % max_seats 分配, Σ 分配 == 池额"""

    def _settle_split(self, db, players, pot_amount, winner_idxs, dealer_idx=0):
        """辅助: 构造单池并按指定赢家平分"""
        room = db.query(Room).first()
        hand = Hand(
            room_id=room.id, hand_number=1,
            dealer_player_id=players[dealer_idx].id,
            sb_player_id=players[0].id, bb_player_id=players[1].id,
            current_round="showdown", status="settling", pot_total=pot_amount,
            community_cards="[]", hole_cards="{}", deck_state=None,
        )
        db.add(hand)
        db.flush()
        pot = Pot(
            hand_id=hand.id, pot_type="main", pot_level=0, amount=pot_amount,
            eligible_player_ids=",".join(str(players[i].id) for i in winner_idxs),
        )
        db.add(pot)
        db.flush()

        engine = HandEngine(db, room)
        results = [{
            "pot_id": pot.id,
            "winner_ids": [players[i].id for i in winner_idxs],
            "amount": pot_amount,
        }]
        chips_before = {p.id: p.chip_count for p in players}
        hand_results = engine.settle_hand(hand, results=results)
        return hand_results, chips_before

    def test_odd_split_999_two_players(self, db):
        """池 999 两人平分 → 499+500, 余数 1 给庄位距离最近者, 全部分完"""
        room, players = _make_room_with_players(db, num_players=2, chips=10000)
        hand_results, chips_before = self._settle_split(
            db, players, pot_amount=999, winner_idxs=[0, 1], dealer_idx=0,
        )

        # dealer=players[0] (seat 0): 余数 1 归 players[0]
        assert players[0].chip_count == chips_before[players[0].id] + 500
        assert players[1].chip_count == chips_before[players[1].id] + 499
        # Σ 分配 == 池额 (余数不蒸发)
        assert sum(hr.amount_won for hr in hand_results) == 999

    def test_odd_split_1001_three_players(self, db):
        """池 1001 三人平分 → 334+334+333, 余数 2 按庄位顺序给前两人"""
        room, players = _make_room_with_players(db, num_players=3, chips=10000)
        hand_results, chips_before = self._settle_split(
            db, players, pot_amount=1001, winner_idxs=[0, 1, 2], dealer_idx=0,
        )

        # 座位 0(庄),1,2 → 距离 0,1,2 → 余数 2 归 seat0, seat1
        assert players[0].chip_count == chips_before[players[0].id] + 334
        assert players[1].chip_count == chips_before[players[1].id] + 334
        assert players[2].chip_count == chips_before[players[2].id] + 333
        assert sum(hr.amount_won for hr in hand_results) == 1001


# ======================== E7: 本手参与者 ========================

class TestE7HandParticipants:
    """E7: 行动/存活判定只看 hole_cards key, 中途入座者不算, 离局未 fold 者仍算"""

    def test_mid_hand_joiner_gets_no_action(self, db):
        """第三人中途入座: 不分到行动权, 不能下注, SB fold 后牌局正常结束"""
        room, players = _make_room_with_players(db, num_players=2, chips=10000)
        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        p_sb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.sb_player_id).first()
        p_bb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.bb_player_id).first()

        # 牌局进行中, 第三人入座
        third = _add_player(db, room, seat_number=2)

        # 第三人不能下注
        with pytest.raises(BadRequestException):
            engine.place_bet(hand, third, "call")

        # Preflop: SB call → 行动权只能给 BB, 绝不给第三人
        assert hand.turn_player_id == p_sb.id
        engine.place_bet(hand, p_sb, "call")
        db.refresh(hand)
        assert hand.turn_player_id == p_bb.id

        # BB check → 本轮结束
        engine.place_bet(hand, p_bb, "check")
        db.refresh(hand)
        assert hand.turn_player_id is None

        # 推进到 flop, 行动权仍只在参与者之间
        engine.advance_round(hand)
        db.refresh(hand)
        assert hand.turn_player_id in (p_sb.id, p_bb.id)

        # Post-flop BB 先行动 (heads-up 规则), 先 check
        assert hand.turn_player_id == p_bb.id
        engine.place_bet(hand, p_bb, "check")
        db.refresh(hand)

        # SB fold → 牌局正常结束 (不被第三人干扰)
        engine.place_bet(hand, p_sb, "fold")
        db.refresh(hand)
        assert hand.status == "settling"
        assert hand.ended_by_fold == 1

        # 结算: BB 赢, 第三人分文不得
        engine.settle_hand(hand)
        db.refresh(p_sb)
        db.refresh(p_bb)
        db.refresh(third)
        assert p_sb.chip_count == 9900    # 10000 - 50(SB) - 50(call)
        assert p_bb.chip_count == 10100   # 9900 + 200(pot)
        assert third.chip_count == 10000  # 未受影响

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        for pot in pots:
            assert third.id not in _pot_eligible(pot)

    def test_allin_player_stood_up_still_wins_at_showdown(self, db):
        """all-in 玩家 is_active=0 后打到 showdown, 仍按牌力正常分池"""
        room, players = _make_room_with_players(db, num_players=2, chips=10000)
        p1, p2 = players[0], players[1]

        S, H, D, CL = "spades", "hearts", "diamonds", "clubs"
        community = [Card(S, 8), Card(H, 8), Card(D, 5), Card(CL, 5), Card(S, 10)]
        # p2 (已离局的 all-in 玩家) 持 A kicker, 牌力更强
        hole_map = {
            str(p1.id): [{"suit": S, "rank": 13}, {"suit": H, "rank": 3}],   # K kicker
            str(p2.id): [{"suit": S, "rank": 14}, {"suit": H, "rank": 2}],   # A kicker
        }
        hand = Hand(
            room_id=room.id, hand_number=1,
            dealer_player_id=p1.id, sb_player_id=p1.id, bb_player_id=p2.id,
            current_round="showdown", status="settling", pot_total=2000,
            community_cards=cards_to_json(community),
            hole_cards=json.dumps(hole_map),
            deck_state=None, ended_by_fold=0,
        )
        db.add(hand)
        db.flush()
        # 两人各投 1000 (p2 all-in)
        db.add(Bet(hand_id=hand.id, player_id=p1.id, round="preflop", action="call", amount=1000))
        db.add(Bet(hand_id=hand.id, player_id=p2.id, round="preflop", action="allin", amount=1000))
        p1.chip_count -= 1000
        p2.chip_count -= 1000
        # p2 all-in 后离局
        p2.is_active = 0
        db.flush()

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        results = engine._auto_determine_winners(hand)
        assert results, "应有结算结果"
        winner_ids = results[0]["winner_ids"]
        assert p2.id in winner_ids, \
            f"已离局但未 fold 的 p2(A kicker) 应赢, 实际赢家: {winner_ids}"

        engine.settle_hand(hand, results=results)
        db.refresh(p1)
        db.refresh(p2)
        assert p2.chip_count == 10000 - 1000 + 2000  # 赢得全部底池
        assert p1.chip_count == 10000 - 1000


# ======================== E8: 庄位轮转 ========================

class TestE8DealerRotation:
    """E8: 前庄家座位消失时, 庄位移交座位环上下一个大于旧庄位的座位"""

    def test_dealer_seat_gone_rotates_clockwise(self, db):
        """旧庄 seat2 离局, seats=[0,1,3] → 新庄为 seat3 (而非跳位到 seat0/1)"""
        room, players = _make_room_with_players(db, num_players=4, chips=10000, dealer_seat=2)
        # seat2 玩家 (旧庄) 离局
        players[2].is_active = 0
        db.commit()

        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        assert room.dealer_seat == 3, f"新庄应为 seat3, 实际 seat{room.dealer_seat}"
        assert hand.dealer_player_id == players[3].id
        # SB/BB 按座位环顺延: SB=seat0, BB=seat1
        assert hand.sb_player_id == players[0].id
        assert hand.bb_player_id == players[1].id

    def test_dealer_seat_gone_wraps_to_smallest(self, db):
        """旧庄 seat5 离局且没有更大座位, seats=[0,1,3] → 新庄为最小座位 seat0"""
        room, players = _make_room_with_players(db, num_players=3, chips=10000, dealer_seat=5)

        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        assert room.dealer_seat == 0
        assert hand.dealer_player_id == players[0].id


# ======================== E9: Heads-up 行动顺序 ========================

class TestE9HeadsUpActionOrder:
    """E9: 双人局行动顺序 — preflop 庄家(SB)先行动, post-flop BB(非庄家)先行动"""

    def test_heads_up_preflop_sb_first_postflop_bb_first(self):
        """seats=[3,7], 庄=seat3 (=SB), BB=seat7"""
        seats = [3, 7]
        dealer = 3
        # Preflop: SB(=庄家)先行动
        assert get_action_order(seats, dealer, "preflop") == [3, 7]
        # Post-flop: BB 先行动, 庄家最后行动
        for rnd in ("flop", "turn", "river"):
            assert get_action_order(seats, dealer, rnd) == [7, 3], f"{rnd} 应由 BB 先行动"

    def test_heads_up_postflop_turn_goes_to_bb(self, db):
        """引擎级验证: 2 人局推进到 flop 后, 行动权在 BB 而非庄家/SB"""
        room, players = _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100)
        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        p_sb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.sb_player_id).first()
        p_bb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.bb_player_id).first()

        # Preflop: SB call, BB check
        engine.place_bet(hand, p_sb, "call")
        db.refresh(hand)
        engine.place_bet(hand, p_bb, "check")
        db.refresh(hand)

        # 推进到 flop: BB 先行动
        engine.advance_round(hand)
        db.refresh(hand)
        assert hand.turn_player_id == p_bb.id

        # SB 此时不能行动
        with pytest.raises(BadRequestException):
            engine.place_bet(hand, p_sb, "check")
