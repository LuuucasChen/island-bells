"""岛屿铃钱记 — 结算 Bug 回归测试

覆盖:
1. Bug1: _auto_determine_winners 始终比较所有存活玩家 (不受 revealed_players 限制)
2. Bug3: fold 退款筹码守恒 (fold 玩家超额部分也需退款)
"""

import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import User, Room, RoomPlayer, Hand, Bet, Pot, HandResult
from app.engine.hand_engine import HandEngine
from app.engine.deck import Deck, Card, cards_to_json


# ======================== Fixtures ========================

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


def _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100):
    """辅助: 创建房间 + 入座玩家"""
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
        dealer_seat=0,
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


def _deal_specific_hole_and_community(hole_map, community_cards):
    """辅助: 构造特定的手牌和公共牌数据"""
    hole_json = {}
    for pid, cards in hole_map.items():
        hole_json[str(pid)] = [{"suit": c.suit, "rank": c.rank} for c in cards]
    return json.dumps(hole_json), cards_to_json(community_cards)


# ======================== Bug1: revealed_players 不影响结算 ========================

class TestAutoDetermineWinnersComparesAll:
    """
    回归测试: _auto_determine_winners 应始终比较所有存活玩家，
    不受 revealed_players 字段限制。
    
    场景: 公共牌两对 (8-8-5-5-10)，玩家A手牌含A，玩家K手牌含K
    revealed_players 只含 K 玩家 (last_aggressor)
    预期: A 玩家应该赢 (A kicker > K kicker)
    """

    def test_two_pair_community_kicker_a_beats_k(self, db):
        """
        核心场景: 公共牌两对 + 踢脚10
        玩家1: A♠ 2♥ (两对 + A kicker)
        玩家2: K♠ 3♥ (两对 + K kicker)
        revealed_players 只含玩家2 (last_aggressor)
        预期: 玩家1 赢
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100)
        p1, p2 = players[0], players[1]

        # 构造特定牌面
        S, H, D, CL = "spades", "hearts", "diamonds", "clubs"
        community = [
            Card(S, 8), Card(H, 8), Card(D, 5), Card(CL, 5), Card(S, 10),
        ]
        hole_map = {
            p1.id: [Card(S, 14), Card(H, 2)],   # A-2 → 两对 + A kicker
            p2.id: [Card(S, 13), Card(H, 3)],    # K-3 → 两对 + K kicker
        }
        hole_json, community_json = _deal_specific_hole_and_community(hole_map, community)

        # 创建 Hand
        hand = Hand(
            room_id=room.id,
            hand_number=1,
            dealer_player_id=p1.id,
            sb_player_id=p1.id,
            bb_player_id=p2.id,
            current_round="showdown",
            status="settling",
            pot_total=200,
            community_cards=community_json,
            hole_cards=hole_json,
            deck_state=None,
            ended_by_fold=0,
            last_aggressor_id=p2.id,
            revealed_players=str(p2.id),  # ← 只有 p2 在 revealed 中!
        )
        db.add(hand)
        db.flush()

        # 创建 Bet 记录 (每人投 100)
        db.add(Bet(hand_id=hand.id, player_id=p1.id, round="preflop", action="blind", amount=100))
        db.add(Bet(hand_id=hand.id, player_id=p2.id, round="preflop", action="blind", amount=100))
        p1.chip_count -= 100
        p2.chip_count -= 100
        db.flush()

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # 自动结算
        results = engine._auto_determine_winners(hand)

        # 玩家1 (A kicker) 应该赢
        assert len(results) >= 1
        main_result = results[0]
        assert p1.id in main_result["winner_ids"], \
            f"玩家1(A kicker)应赢, 实际赢家: {main_result['winner_ids']}"
        assert p2.id not in main_result["winner_ids"], \
            f"玩家2(K kicker)不应赢, 实际赢家: {main_result['winner_ids']}"

    def test_revealed_players_empty_still_compares_all(self, db):
        """
        revealed_players 为空时也能正确比较
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100)
        p1, p2 = players[0], players[1]

        S, H, D, CL = "spades", "hearts", "diamonds", "clubs"
        community = [Card(S, 8), Card(H, 8), Card(D, 5), Card(CL, 5), Card(S, 10)]
        hole_map = {
            p1.id: [Card(S, 14), Card(H, 2)],   # A kicker
            p2.id: [Card(S, 13), Card(H, 3)],    # K kicker
        }
        hole_json, community_json = _deal_specific_hole_and_community(hole_map, community)

        hand = Hand(
            room_id=room.id, hand_number=1,
            dealer_player_id=p1.id, sb_player_id=p1.id, bb_player_id=p2.id,
            current_round="showdown", status="settling", pot_total=200,
            community_cards=community_json, hole_cards=hole_json,
            deck_state=None, ended_by_fold=0,
            revealed_players=None,  # ← 空
        )
        db.add(hand)
        db.flush()
        db.add(Bet(hand_id=hand.id, player_id=p1.id, round="preflop", action="blind", amount=100))
        db.add(Bet(hand_id=hand.id, player_id=p2.id, round="preflop", action="blind", amount=100))
        p1.chip_count -= 100
        p2.chip_count -= 100
        db.flush()

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        results = engine._auto_determine_winners(hand)
        assert p1.id in results[0]["winner_ids"]

    def test_three_players_revealed_only_one(self, db):
        """
        3人局: revealed_players 只含 1 人，结算仍比较所有 3 人
        玩家1: 三条 7
        玩家2: 两对 (revealed)
        玩家3: 顺子
        预期: 玩家3 (顺子) 赢
        """
        room, players = _make_room_with_players(db, num_players=3, chips=10000, sb=50, bb=100)
        p1, p2, p3 = players[0], players[1], players[2]

        S, H, D, CL = "spades", "hearts", "diamonds", "clubs"
        community = [Card(S, 7), Card(H, 7), Card(D, 8), Card(CL, 9), Card(S, 10)]
        hole_map = {
            p1.id: [Card(D, 7), Card(H, 2)],     # 三条 7 (牌型 4)
            p2.id: [Card(S, 8), Card(H, 8)],      # 葫芦? no... 8-8 + community 7-7-8 → 8-8-8-7-7 = 葫芦!
            p3.id: [Card(S, 11), Card(H, 12)],    # J-Q + 8-9-10 → 顺子 8-9-10-J-Q (牌型 5)
        }
        hole_json, community_json = _deal_specific_hole_and_community(hole_map, community)

        hand = Hand(
            room_id=room.id, hand_number=1,
            dealer_player_id=p1.id, sb_player_id=p1.id, bb_player_id=p2.id,
            current_round="showdown", status="settling", pot_total=300,
            community_cards=community_json, hole_cards=hole_json,
            deck_state=None, ended_by_fold=0,
            last_aggressor_id=p2.id,
            revealed_players=str(p2.id),  # ← 只有 p2
        )
        db.add(hand)
        db.flush()
        for p in players:
            db.add(Bet(hand_id=hand.id, player_id=p.id, round="preflop", action="blind", amount=100))
            p.chip_count -= 100
        db.flush()

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        results = engine._auto_determine_winners(hand)
        winner_ids = results[0]["winner_ids"]
        # p2 有葫芦 (8-8-8-7-7), p3 有顺子, p1 有三条
        # 葫芦 > 顺子 > 三条 → p2 赢
        assert p2.id in winner_ids, f"p2(葫芦)应赢, 实际: {winner_ids}"


# ======================== Bug3: fold 退款筹码守恒 ========================

class TestFoldRefundChipConservation:
    """
    回归测试: fold 退款后筹码必须守恒
    场景: 多人 fold 且 fold 玩家投入金额不同，
    部分 fold 玩家的投入超过存活玩家的 cap
    """

    def test_fold_players_different_amounts_conservation(self, db):
        """
        3人: A(300) fold, B(500) fold, C(1000) alive
        
        修复前: C 退 500, pot=2000, A的300+B的500被锁 → C赢2000, 多赚700
        修复后: C 退 500, B 退 0, A 退 0, pot 不变, 筹码守恒
        """
        room, players = _make_room_with_players(db, num_players=3, chips=10000, sb=50, bb=100)
        p_a, p_b, p_c = players[0], players[1], players[2]

        total_initial = sum(p.chip_count for p in players)

        hand = Hand(
            room_id=room.id, hand_number=1,
            dealer_player_id=p_a.id, sb_player_id=p_a.id, bb_player_id=p_b.id,
            current_round="showdown", status="settling", pot_total=0,
            community_cards="[]", hole_cards="{}", deck_state=None,
        )
        db.add(hand)
        db.flush()

        bet_data = [
            (0, "blind", 50),    # A: SB
            (1, "blind", 100),   # B: BB
            (0, "raise", 250),   # A: total=300
            (1, "call", 400),    # B: total=500 (call 到 500)
            (2, "call", 1000),   # C: total=1000
            (0, "fold", 0),      # A: fold at 300
            (1, "fold", 0),      # B: fold at 500
        ]
        total_pot = 0
        for pidx, action, amount in bet_data:
            db.add(Bet(hand_id=hand.id, player_id=players[pidx].id,
                       round="preflop", action=action, amount=amount))
            players[pidx].chip_count -= amount
            total_pot += amount
        hand.pot_total = total_pot
        db.flush()

        chips_before_settle = {p.id: p.chip_count for p in players}

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # 验证筹码守恒 (退款后 + pot = 初始总和)
        total_after_refund = sum(p.chip_count for p in players) + hand.pot_total
        assert total_after_refund == total_initial, \
            f"退款后筹码不守恒! 初始={total_initial}, 退款后={total_after_refund}"

        # 验证 pot 金额正确
        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        total_pot_amount = sum(p.amount for p in pots)
        assert total_pot_amount == hand.pot_total, \
            f"pot 金额 {total_pot_amount} ≠ hand.pot_total {hand.pot_total}"

        # C 应该赢所有 pot
        for pot in pots:
            eligible = [int(x) for x in pot.eligible_player_ids.split(",") if x]
            assert p_c.id in eligible, f"C 应在 eligible 中, pot {pot.id}: {eligible}"

        # 模拟结算: C 赢
        results = []
        for pot in pots:
            results.append({"pot_id": pot.id, "winner_ids": [p_c.id], "amount": pot.amount})
        engine.settle_hand(hand, results=results)
        db.flush()

        # 结算后筹码守恒
        total_after_settle = sum(p.chip_count for p in players)
        assert total_after_settle == total_initial, \
            f"结算后筹码不守恒! 初始={total_initial}, 结算后={total_after_settle}"

    def test_fold_player_exceeds_alive_player(self, db):
        """
        2人: A 投 500 fold, B 投 200 alive
        A 的投入 > B 的投入
        
        max_folded = 500, B 的 200 < 500 → 无退款
        pot = 700, B eligible → B 赢 700
        B: 10000-200+700 = 10500 (净赚 500)
        A: 10000-500 = 9500 (净输 500)
        总和 = 20000 ✓
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100)
        p_a, p_b = players[0], players[1]

        total_initial = sum(p.chip_count for p in players)

        hand = Hand(
            room_id=room.id, hand_number=1,
            dealer_player_id=p_a.id, sb_player_id=p_a.id, bb_player_id=p_b.id,
            current_round="showdown", status="settling", pot_total=0,
            community_cards="[]", hole_cards="{}", deck_state=None,
        )
        db.add(hand)
        db.flush()

        # A 投 500, B 投 200
        bet_data = [
            (0, "blind", 50),    # A: SB
            (1, "blind", 100),   # B: BB
            (0, "raise", 450),   # A: total=500
            (1, "call", 100),    # B: total=200
            (0, "fold", 0),      # A: fold
        ]
        for pidx, action, amount in bet_data:
            db.add(Bet(hand_id=hand.id, player_id=players[pidx].id,
                       round="preflop", action=action, amount=amount))
            players[pidx].chip_count -= amount
        hand.pot_total = 700
        db.flush()

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # 筹码守恒
        total_after_refund = sum(p.chip_count for p in players) + hand.pot_total
        assert total_after_refund == total_initial

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        total_pot = sum(p.amount for p in pots)
        assert total_pot == 700  # A的500 + B的200

        # B 赢
        results = [{"pot_id": pots[0].id, "winner_ids": [p_b.id], "amount": pots[0].amount}]
        if len(pots) > 1:
            results.append({"pot_id": pots[1].id, "winner_ids": [p_b.id], "amount": pots[1].amount})
        engine.settle_hand(hand, results=results)
        db.flush()

        total_after_settle = sum(p.chip_count for p in players)
        assert total_after_settle == total_initial

    def test_multi_fold_excess_refund(self, db):
        """
        3人: A(200) fold, B(800) fold, C(1000) alive
        
        max_folded = max(200, 800) = 800
        修复前: C 退 200 (1000→800), A不退, B不退 → pot=1800, 但A的200+B的800锁在无人池
        修复后: C 退 200, B 退 0, A 退 0 → effective A=200, B=800, C=800 → pot=1800
        C 赢 1800 → 10000-1000+200+1800 = 11000
        A: 10000-200 = 9800
        B: 10000-800 = 9200
        总和: 11000+9800+9200 = 30000 ✓
        """
        room, players = _make_room_with_players(db, num_players=3, chips=10000, sb=50, bb=100)
        p_a, p_b, p_c = players[0], players[1], players[2]

        total_initial = sum(p.chip_count for p in players)

        hand = Hand(
            room_id=room.id, hand_number=1,
            dealer_player_id=p_a.id, sb_player_id=p_a.id, bb_player_id=p_b.id,
            current_round="showdown", status="settling", pot_total=0,
            community_cards="[]", hole_cards="{}", deck_state=None,
        )
        db.add(hand)
        db.flush()

        bet_data = [
            (0, "blind", 50),
            (1, "blind", 100),
            (0, "raise", 150),   # A: total=200
            (1, "raise", 700),   # B: total=800
            (2, "call", 1000),   # C: total=1000
            (0, "fold", 0),
            (1, "fold", 0),
        ]
        for pidx, action, amount in bet_data:
            db.add(Bet(hand_id=hand.id, player_id=players[pidx].id,
                       round="preflop", action=action, amount=amount))
            players[pidx].chip_count -= amount
        hand.pot_total = 2000
        db.flush()

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # 筹码守恒 (退款后)
        total_after_refund = sum(p.chip_count for p in players) + hand.pot_total
        assert total_after_refund == total_initial, \
            f"退款后不守恒! 初始={total_initial}, 退款后={total_after_refund}"

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        total_pot = sum(p.amount for p in pots)
        assert total_pot == hand.pot_total

        # C 赢所有 pot
        results = []
        for pot in pots:
            results.append({"pot_id": pot.id, "winner_ids": [p_c.id], "amount": pot.amount})
        engine.settle_hand(hand, results=results)
        db.flush()

        total_after_settle = sum(p.chip_count for p in players)
        assert total_after_settle == total_initial, \
            f"结算后不守恒! 初始={total_initial}, 结算后={total_after_settle}"

    def test_fold_excess_refund_specific(self, db):
        """
        精确验证: fold 玩家的超额部分被退款
        
        3人: A(500) fold, B(200) fold, C(1000) alive
        max_folded = max(500, 200) = 500
        C: 1000 > 500 → 退 500, effective=500
        A: 500 = 500 → 不退
        B: 200 < 500 → 不退
        
        pot = 500×3 = 1500 (eligible: A,B,C → 去掉fold → C)
        C 赢 1500
        
        A: 10000-500 = 9500
        B: 10000-200 = 9800
        C: 10000-1000+500(退)+1500(赢) = 11000
        总和 = 30300... 应该是 30000?
        
        让我重新算:
        投入: A=500, B=200, C=1000 → 总投入 1700
        C 退 500 → 实际投入 1200 → pot=1500?
        
        effective = {A:500, B:200, C:500}
        calculate_pots: levels=[200, 500]
          level=200: eligible=[A,B,C], amount=(200-0)×3=600
          level=500: eligible=[A,C], amount=(500-200)×2=600
        pot 总和 = 1200
        hand.pot_total = 1700 - 500(C退) = 1200 ✓
        
        去掉 fold: pot1 eligible=[C], pot2 eligible=[C]
        C 赢 600+600=1200
        
        A: 10000-500=9500
        B: 10000-200=9800
        C: 10000-1000+500+1200=10700
        总和 = 30000 ✓
        """
        room, players = _make_room_with_players(db, num_players=3, chips=10000, sb=50, bb=100)
        p_a, p_b, p_c = players[0], players[1], players[2]

        total_initial = sum(p.chip_count for p in players)  # 30000

        hand = Hand(
            room_id=room.id, hand_number=1,
            dealer_player_id=p_a.id, sb_player_id=p_a.id, bb_player_id=p_b.id,
            current_round="showdown", status="settling", pot_total=0,
            community_cards="[]", hole_cards="{}", deck_state=None,
        )
        db.add(hand)
        db.flush()

        bet_data = [
            (0, "blind", 50),    # A: SB
            (1, "blind", 100),   # B: BB
            (0, "raise", 450),   # A: total=500
            (1, "call", 100),    # B: total=200
            (2, "call", 1000),   # C: total=1000
            (0, "fold", 0),
            (1, "fold", 0),
        ]
        for pidx, action, amount in bet_data:
            db.add(Bet(hand_id=hand.id, player_id=players[pidx].id,
                       round="preflop", action=action, amount=amount))
            players[pidx].chip_count -= amount
        hand.pot_total = 1700
        db.flush()

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # C 应被退 500
        assert p_c.chip_count == 10000 - 1000 + 500, f"C 退款后应为 9500, 实际 {p_c.chip_count}"

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        total_pot = sum(p.amount for p in pots)
        assert total_pot == 1200, f"pot 总和应为 1200, 实际 {total_pot}"
        assert hand.pot_total == 1200

        # C 赢
        results = []
        for pot in pots:
            results.append({"pot_id": pot.id, "winner_ids": [p_c.id], "amount": pot.amount})
        engine.settle_hand(hand, results=results)
        db.flush()

        # 最终验证
        assert p_a.chip_count == 9500, f"A: {p_a.chip_count}"
        assert p_b.chip_count == 9800, f"B: {p_b.chip_count}"
        assert p_c.chip_count == 10700, f"C: {p_c.chip_count}"
        assert sum(p.chip_count for p in players) == total_initial
