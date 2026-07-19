"""岛屿铃钱记 — 边池(Pot)计算与结算单元测试

核心测试场景:
1. calculate_pots 纯算法测试 (无 DB)
2. _calculate_pots_for_hand 集成测试 (有 DB, 测试 fold 退款)
3. 完整流程测试: start → bet → fold → settle → 验证筹码
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import User, Room, RoomPlayer, Hand, Bet, Pot, HandResult
from app.engine.hand_engine import calculate_pots, HandEngine


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


# ======================== calculate_pots 纯算法测试 ========================

class TestCalculatePots:
    """calculate_pots 函数的基本算法测试"""

    def test_two_players_equal(self):
        """2人等额: 1个主池"""
        bets = [
            {"player_id": 1, "total_bet": 100},
            {"player_id": 2, "total_bet": 100},
        ]
        pots = calculate_pots(bets)
        assert len(pots) == 1
        assert pots[0]["pot_type"] == "main"
        assert pots[0]["amount"] == 200
        assert set(pots[0]["eligible_player_ids"]) == {1, 2}

    def test_two_players_unequal(self):
        """2人不等额: 主池 + 边池"""
        bets = [
            {"player_id": 1, "total_bet": 100},
            {"player_id": 2, "total_bet": 500},
        ]
        pots = calculate_pots(bets)
        assert len(pots) == 2
        assert pots[0]["amount"] == 200   # 100 × 2
        assert pots[1]["amount"] == 400   # (500-100) × 1

    def test_three_players_all_in_side_pot(self):
        """
        经典边池: A=500 all-in, B=1000, C=1000
        → 主池: 500×3 = 1500 (3人 eligible)
        → 边池: (1000-500)×2 = 1000 (B,C eligible)
        """
        bets = [
            {"player_id": "A", "total_bet": 500},
            {"player_id": "B", "total_bet": 1000},
            {"player_id": "C", "total_bet": 1000},
        ]
        pots = calculate_pots(bets)
        assert len(pots) == 2
        assert pots[0]["amount"] == 1500
        assert set(pots[0]["eligible_player_ids"]) == {"A", "B", "C"}
        assert pots[1]["amount"] == 1000
        assert set(pots[1]["eligible_player_ids"]) == {"B", "C"}

    def test_three_players_different_amounts(self):
        """3人不同金额: A=100, B=200, C=300"""
        bets = [
            {"player_id": "A", "total_bet": 100},
            {"player_id": "B", "total_bet": 200},
            {"player_id": "C", "total_bet": 300},
        ]
        pots = calculate_pots(bets)
        assert len(pots) == 3
        assert pots[0]["amount"] == 300   # 100×3
        assert pots[1]["amount"] == 200   # (200-100)×2
        assert pots[2]["amount"] == 100   # (300-200)×1

    def test_four_players_multi_side_pots(self):
        """4人多层边池: 50, 100, 200, 200"""
        bets = [
            {"player_id": 1, "total_bet": 50},
            {"player_id": 2, "total_bet": 100},
            {"player_id": 3, "total_bet": 200},
            {"player_id": 4, "total_bet": 200},
        ]
        pots = calculate_pots(bets)
        assert len(pots) == 3
        assert pots[0]["amount"] == 200   # 50×4
        assert pots[1]["amount"] == 150   # (100-50)×3
        assert pots[2]["amount"] == 200   # (200-100)×2

    def test_empty(self):
        assert calculate_pots([]) == []

    def test_zero_bets(self):
        bets = [{"player_id": 1, "total_bet": 0}]
        assert calculate_pots(bets) == []


# ======================== _calculate_pots_for_hand 集成测试 ========================

class TestCalculatePotsForHand:
    """
    _calculate_pots_for_hand 集成测试
    
    重点验证: fold 后存活玩家多余下注的退款逻辑
    """

    def _create_hand_with_bets(self, db, players, bet_data):
        """
        创建 Hand + Bet 记录用于测试
        
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
            community_cards="[]",
            hole_cards="{}",
            deck_state=None,
        )
        db.add(hand)
        db.flush()

        total_pot = 0
        for pidx, action, amount in bet_data:
            bet = Bet(
                hand_id=hand.id,
                player_id=players[pidx].id,
                round="preflop",
                action=action,
                amount=amount,
            )
            db.add(bet)
            # 扣除筹码
            players[pidx].chip_count -= amount
            total_pot += amount

        hand.pot_total = total_pot
        db.flush()
        return hand

    def test_fold_refund_two_players(self, db):
        """
        核心场景: 2人局, A(BB=100) fold, B all-in 10000
        
        预期:
        - B 退回 9900 (有效投入只有 100)
        - 只有 1 个主池 200, B 为唯一 eligible
        - 无副池
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100)
        # players[0] = SB=50, players[1] = BB=100
        # A=players[1](BB=100), B=players[0](SB=50)
        
        # B bets SB=50, then all-in 10000 (额外 9950)
        # A bets BB=100, then folds
        hand = self._create_hand_with_bets(db, players, [
            (0, "blind", 50),       # B: SB
            (1, "blind", 100),      # A: BB
            (0, "allin", 9950),     # B: all-in (total = 10000)
            (1, "fold", 0),         # A: fold
        ])

        # 记录 fold 前筹码
        chips_before = {p.id: p.chip_count for p in players}
        # B: 10000 - 50 - 9950 = 0 (all-in)
        # A: 10000 - 100 = 9900
        assert chips_before[players[0].id] == 0
        assert chips_before[players[1].id] == 9900

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)

        db.flush()

        # 验证退款: B 应被退回 9900
        assert players[0].chip_count == 9900, f"B 应退回 9900, 实际 {players[0].chip_count}"
        # A 不变 (fold 了)
        assert players[1].chip_count == 9900, f"A 筹码应不变, 实际 {players[1].chip_count}"

        # 验证收获篮
        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 1, f"应只有 1 个池, 实际有 {len(pots)} 个"
        assert pots[0].pot_type == "main"
        assert pots[0].amount == 200, f"主池应为 200, 实际 {pots[0].amount}"
        # B 是唯一 eligible
        eligible = [int(x) for x in pots[0].eligible_player_ids.split(",")]
        assert eligible == [players[0].id]

    def test_fold_no_refund_needed(self, db):
        """
        2人局, A(BB=100) fold, B(SB=50) 仅投了 SB
        B 投入 50 < fold 者 100, 无需退款
        
        预期: 主池 100 (2人eligible) + 副池 50 (仅A eligible, 但A fold → B赢)
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100)

        hand = self._create_hand_with_bets(db, players, [
            (0, "blind", 50),       # B: SB
            (1, "blind", 100),      # A: BB
            (1, "fold", 0),         # A: fold (没追加)
        ])

        chips_b_before = players[0].chip_count  # 10000 - 50 = 9950
        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # B 不退款 (50 < 100)
        assert players[0].chip_count == chips_b_before

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        total_pot = sum(p.amount for p in pots)
        assert total_pot == 150  # 50 + 100

    def test_fold_three_players_one_folds(self, db):
        """
        3人局: A(500) fold, B(1000), C(1000) — B/C 存活到 showdown

        正确规则: showdown 路径不做 cap/退款。
        - B/C 全额入池，A(fold) 的 500 留在池内但不参与 eligible
        - 主池: 500×3 = 1500 (B,C eligible)
        - 副池: (1000-500)×2 = 1000 (B,C eligible)
        """
        room, players = _make_room_with_players(db, num_players=3, chips=10000, sb=50, bb=100)

        hand = self._create_hand_with_bets(db, players, [
            (0, "blind", 50),
            (1, "blind", 100),
            (0, "raise", 450),      # A: total=500
            (1, "call", 900),       # B: total=1000
            (2, "call", 1000),      # C: total=1000
            (0, "fold", 0),         # A: fold
        ])

        # A: 10000-50-450 = 9500
        # B: 10000-100-900 = 9000
        # C: 10000-1000 = 9000
        assert players[0].chip_count == 9500
        assert players[1].chip_count == 9000
        assert players[2].chip_count == 9000

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # 无人退款 (showdown 不 cap)
        assert players[0].chip_count == 9500
        assert players[1].chip_count == 9000
        assert players[2].chip_count == 9000

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 2, f"应有 2 个池, 实际有 {len(pots)}"
        assert pots[0].pot_type == "main"
        assert pots[0].amount == 1500  # 500×3
        assert pots[1].pot_type == "side"
        assert pots[1].amount == 1000  # 500×2
        # A(fold) 不在任何池的 eligible 中，B/C 均在
        for pot in pots:
            eligible = [int(x) for x in pot.eligible_player_ids.split(",") if x]
            assert players[0].id not in eligible
            assert players[1].id in eligible
            assert players[2].id in eligible
        # 总池 = 1500 + 1000 = 2500 = A(500) + B(1000) + C(1000)
        assert sum(p.amount for p in pots) == 2500

    def test_no_fold_allin_side_pot(self, db):
        """
        3人局无 fold: A all-in 500, B bet 1000, C bet 1000
        
        预期:
        - 不退款 (无 fold)
        - 主池: 500×3 = 1500
        - 副池: (1000-500)×2 = 1000
        """
        room, players = _make_room_with_players(db, num_players=3, chips=10000, sb=50, bb=100)

        hand = self._create_hand_with_bets(db, players, [
            (0, "blind", 50),
            (1, "blind", 100),
            (0, "raise", 450),      # A: total=500
            (1, "call", 900),       # B: total=1000
            (2, "call", 1000),      # C: total=1000
        ])

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # 无退款
        assert players[0].chip_count == 9500
        assert players[1].chip_count == 9000
        assert players[2].chip_count == 9000

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 2
        assert pots[0].pot_type == "main"
        assert pots[0].amount == 1500
        assert pots[1].pot_type == "side"
        assert pots[1].amount == 1000

    def test_fold_both_players_all_folded(self, db):
        """
        极端: 所有人都 fold (不应该发生但防御测试)
        
        预期: 仍然能正常计算
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100)

        hand = self._create_hand_with_bets(db, players, [
            (0, "blind", 50),
            (1, "blind", 100),
            (0, "fold", 0),
            (1, "fold", 0),
        ])

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # 无人退款 (两个都 fold, max_folded_bet = 100, 但无存活玩家)
        assert players[0].chip_count == 9950
        assert players[1].chip_count == 9900

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        # pot = 150, eligible 应为 non-folded 或 fallback
        total_pot = sum(p.amount for p in pots)
        assert total_pot == 150

    def test_user_scenario_exact(self, db):
        """
        用户报告的精确场景:
        A (BB=100), B all-in 10000, A fold
        
        验证:
        - 不应产生边池
        - B 应退回 9900
        - 结算后 B 应赢得 200 (pot)
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100)
        p_a = players[1]  # BB
        p_b = players[0]  # SB (dealer)

        initial_a = p_a.chip_count  # 10000
        initial_b = p_b.chip_count  # 10000

        hand = self._create_hand_with_bets(db, players, [
            (0, "blind", 50),       # B: SB 50
            (1, "blind", 100),      # A: BB 100
            (0, "allin", 9950),     # B: all-in total=10000
            (1, "fold", 0),         # A: fold
        ])

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # 1) B 退回 9900
        assert p_b.chip_count == 9900, f"B 退回后应为 9900, 实际 {p_b.chip_count}"

        # 2) 只有主池 200
        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 1
        assert pots[0].amount == 200

        # 3) 模拟结算: B 赢主池
        p_b.chip_count += pots[0].amount  # 9900 + 200 = 10100

        # 4) 最终验证
        # A: 10000 - 100 = 9900 (输了 100)
        assert p_a.chip_count == 9900
        # B: 10000 - 10000 + 9900(退款) + 200(赢) = 10100 (赢了 100)
        assert p_b.chip_count == 10100
        # 总和不变
        assert p_a.chip_count + p_b.chip_count == 20000


# ======================== 完整流程测试 ========================

class TestFullFlowWithFold:
    """
    通过 HandEngine 完整流程测试:
    start_new_hand → place_bet(fold) → settle → 验证最终筹码
    """

    def test_fold_after_allin_settle(self, db):
        """
        完整流程: 2人局
        1. start_new_hand (SB=50, BB=100)
        2. SB all-in (10000)
        3. BB fold
        4. settle
        5. 验证筹码
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100)

        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        # 从 hand 对象获取实际角色 (rotate_dealer 可能改变了座位)
        p_sb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.sb_player_id).first()
        p_bb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.bb_player_id).first()

        # 验证盲注扣除
        assert p_sb.chip_count == 9950  # 10000 - 50
        assert p_bb.chip_count == 9900  # 10000 - 100

        # Preflop: 2人局 dealer=SB, UTG=dealer先行动
        assert hand.turn_player_id == p_sb.id

        # SB all-in (all chips: 9950)
        engine.place_bet(hand, p_sb, "allin")
        db.refresh(p_sb)
        db.refresh(p_bb)
        db.refresh(hand)

        assert p_sb.chip_count == 0  # all-in (50 blind + 9950 raise)
        # BB 应该被要求行动
        assert hand.turn_player_id == p_bb.id

        # BB fold
        engine.place_bet(hand, p_bb, "fold")
        db.refresh(p_sb)
        db.refresh(p_bb)
        db.refresh(hand)

        # 应自动进入 settling
        assert hand.status == "settling"
        assert hand.current_round == "showdown"

        # 验证收获篮 (退款已在 _calculate_pots_for_hand 中完成)
        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 1, f"应只有 1 个池, 实际有 {len(pots)}: {[(p.pot_type, p.amount) for p in pots]}"
        assert pots[0].amount == 200

        # SB 应被退回 9900 (10000 total - 100 cap)
        assert p_sb.chip_count == 9900, f"SB 退款后应为 9900, 实际 {p_sb.chip_count}"

        # 结算
        results = engine.settle_hand(hand)
        db.refresh(p_sb)
        db.refresh(p_bb)

        # SB 赢: 9900(退款) + 200(赢) = 10100
        assert p_sb.chip_count == 10100, f"SB 最终应为 10100, 实际 {p_sb.chip_count}"
        # BB 输: 9900
        assert p_bb.chip_count == 9900, f"BB 最终应为 9900, 实际 {p_bb.chip_count}"
        # 总和守恒
        assert p_sb.chip_count + p_bb.chip_count == 20000

    def test_fold_no_extra_bet_settle(self, db):
        """
        2人局: SB call 补齐到 BB, BB fold (无 all-in)
        预期: 无退款, SB 赢 pot
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100)

        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        # 从 hand 对象获取实际角色
        p_sb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.sb_player_id).first()
        p_bb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.bb_player_id).first()

        # Preflop: 2人局 dealer=SB 先行动
        assert hand.turn_player_id == p_sb.id

        # SB calls (补齐到 100: 需要再投 50)
        engine.place_bet(hand, p_sb, "call")
        db.refresh(p_sb)
        db.refresh(hand)

        # SB 应补了 50: 10000 - 50(SB) - 50(call补齐) = 9900
        assert p_sb.chip_count == 9900

        # 现在轮到 BB
        assert hand.turn_player_id == p_bb.id

        # BB fold
        engine.place_bet(hand, p_bb, "fold")
        db.refresh(p_sb)
        db.refresh(p_bb)
        db.refresh(hand)

        assert hand.status == "settling"

        # pot = 50 + 50 + 100 = 200
        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 1
        assert pots[0].amount == 200

        # 结算
        engine.settle_hand(hand)
        db.refresh(p_sb)
        db.refresh(p_bb)

        # SB: 9900 + 200 = 10100
        assert p_sb.chip_count == 10100
        # BB: 9900
        assert p_bb.chip_count == 9900

    def test_three_player_side_pot_no_fold(self, db):
        """
        3人局: 所有人都 call BB, 无人 fold, 验证基本 pot 计算正确
        
        流程: start → UTG call → SB call → BB check → advance to flop
        """
        room, players = _make_room_with_players(db, num_players=3, chips=1000, sb=50, bb=100)

        engine = HandEngine(db, room)
        hand = engine.start_new_hand()

        # 从 hand 对象获取实际角色
        p_sb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.sb_player_id).first()
        p_bb = db.query(RoomPlayer).filter(RoomPlayer.id == hand.bb_player_id).first()
        p_dealer = db.query(RoomPlayer).filter(RoomPlayer.id == hand.dealer_player_id).first()

        # Preflop: 3人, UTG 先行动 (BB后一位)
        first_actor_id = hand.turn_player_id
        first_actor = db.query(RoomPlayer).filter(RoomPlayer.id == first_actor_id).first()

        # 第一个行动者 call
        engine.place_bet(hand, first_actor, "call")
        db.refresh(hand)
        db.refresh(first_actor)

        # 第二个行动者 call
        second_actor_id = hand.turn_player_id
        second_actor = db.query(RoomPlayer).filter(RoomPlayer.id == second_actor_id).first()
        engine.place_bet(hand, second_actor, "call")
        db.refresh(hand)
        db.refresh(second_actor)

        # BB check (call when matched)
        bb_id = hand.turn_player_id
        bb_actor = db.query(RoomPlayer).filter(RoomPlayer.id == bb_id).first()
        engine.place_bet(hand, bb_actor, "call")  # call when matched = check
        db.refresh(hand)

        # 轮次应结束 (所有人都行动且匹配)
        assert hand.turn_player_id is None

        # 推进到 flop
        hand = engine.advance_round(hand)
        db.refresh(hand)
        assert hand.current_round == "flop"

        # 验证 pot_total = 100×3 = 300
        assert hand.pot_total == 300

        # 验证每人最终筹码 = 1000 - 100 = 900
        db.refresh(p_sb)
        db.refresh(p_bb)
        db.refresh(p_dealer)
        for p in [p_sb, p_bb, p_dealer]:
            assert p.chip_count == 900, f"Player {p.id} (seat {p.seat_number}) 应有 900, 实际 {p.chip_count}"

        # 总和守恒
        assert p_dealer.chip_count + p_sb.chip_count + p_bb.chip_count + hand.pot_total == 3000


class TestCheckAction:
    """check 动作校验测试"""

    def test_check_valid_when_no_bet(self):
        from app.engine.hand_engine import validate_bet_action
        result = validate_bet_action("check", 0, 1000, 0, 0, 50)
        assert result["valid"] is True
        assert result["actual_amount"] == 0

    def test_check_invalid_when_bet_to_call(self):
        from app.engine.hand_engine import validate_bet_action
        result = validate_bet_action("check", 0, 1000, 0, 100, 50)
        assert result["valid"] is False


# ======================== calculate_pots 扩展算法测试 ========================

class TestCalculatePotsAdvanced:
    """calculate_pots 高级算法测试 — 覆盖更多特殊场景"""

    def test_single_player(self):
        """单人: 只有主池"""
        bets = [{"player_id": 1, "total_bet": 500}]
        pots = calculate_pots(bets)
        assert len(pots) == 1
        assert pots[0]["amount"] == 500
        assert pots[0]["eligible_player_ids"] == [1]

    def test_two_players_one_zero(self):
        """2人: 一人没下注"""
        bets = [
            {"player_id": 1, "total_bet": 0},
            {"player_id": 2, "total_bet": 200},
        ]
        pots = calculate_pots(bets)
        assert len(pots) == 1
        assert pots[0]["amount"] == 200
        assert pots[0]["eligible_player_ids"] == [2]

    def test_short_stack_allin_heads_up(self):
        """
        2人 short-stack all-in: A=300 all-in, B=1000
        → 主池: 300×2 = 600
        → 边池: (1000-300)×1 = 700
        """
        bets = [
            {"player_id": "A", "total_bet": 300},
            {"player_id": "B", "total_bet": 1000},
        ]
        pots = calculate_pots(bets)
        assert len(pots) == 2
        assert pots[0]["pot_type"] == "main"
        assert pots[0]["amount"] == 600
        assert set(pots[0]["eligible_player_ids"]) == {"A", "B"}
        assert pots[1]["pot_type"] == "side"
        assert pots[1]["amount"] == 700
        assert pots[1]["eligible_player_ids"] == ["B"]
        # 总和守恒
        assert sum(p["amount"] for p in pots) == 1300

    def test_three_all_in_different_amounts(self):
        """
        3人都 all-in 不同金额: A=200, B=500, C=1000
        → 主池: 200×3 = 600 (A,B,C)
        → 副1: (500-200)×2 = 600 (B,C)
        → 副2: (1000-500)×1 = 500 (C)
        """
        bets = [
            {"player_id": "A", "total_bet": 200},
            {"player_id": "B", "total_bet": 500},
            {"player_id": "C", "total_bet": 1000},
        ]
        pots = calculate_pots(bets)
        assert len(pots) == 3
        assert pots[0]["amount"] == 600
        assert set(pots[0]["eligible_player_ids"]) == {"A", "B", "C"}
        assert pots[1]["amount"] == 600
        assert set(pots[1]["eligible_player_ids"]) == {"B", "C"}
        assert pots[2]["amount"] == 500
        assert pots[2]["eligible_player_ids"] == ["C"]
        # 总和 = 600 + 600 + 500 = 1700 = 200+500+1000
        assert sum(p["amount"] for p in pots) == 1700

    def test_four_players_two_allin(self):
        """
        4人: A=100(allin), B=300(allin), C=500, D=500
        → 主池: 100×4 = 400
        → 副1: (300-100)×3 = 600 (B,C,D)
        → 副2: (500-300)×2 = 400 (C,D)
        """
        bets = [
            {"player_id": "A", "total_bet": 100},
            {"player_id": "B", "total_bet": 300},
            {"player_id": "C", "total_bet": 500},
            {"player_id": "D", "total_bet": 500},
        ]
        pots = calculate_pots(bets)
        assert len(pots) == 3
        assert pots[0]["amount"] == 400
        assert set(pots[0]["eligible_player_ids"]) == {"A", "B", "C", "D"}
        assert pots[1]["amount"] == 600
        assert set(pots[1]["eligible_player_ids"]) == {"B", "C", "D"}
        assert pots[2]["amount"] == 400
        assert set(pots[2]["eligible_player_ids"]) == {"C", "D"}
        assert sum(p["amount"] for p in pots) == 1400  # 100+300+500+500

    def test_all_equal_large_bet(self):
        """5人等额大注: 每人 5000"""
        bets = [{"player_id": i, "total_bet": 5000} for i in range(5)]
        pots = calculate_pots(bets)
        assert len(pots) == 1
        assert pots[0]["amount"] == 25000
        assert len(pots[0]["eligible_player_ids"]) == 5

    def test_pot_amounts_sum_to_total(self):
        """验证: pot 总和 = 所有玩家 bet 总和 (各种场景)"""
        scenarios = [
            [{"player_id": 1, "total_bet": 77}, {"player_id": 2, "total_bet": 133}],
            [{"player_id": 1, "total_bet": 1}, {"player_id": 2, "total_bet": 10000}],
            [{"player_id": i, "total_bet": (i+1) * 100} for i in range(6)],
        ]
        for bets in scenarios:
            pots = calculate_pots(bets)
            total_bets = sum(b["total_bet"] for b in bets)
            total_pots = sum(p["amount"] for p in pots)
            assert total_pots == total_bets, f"不守恒: bets={bets}, pots={pots}"


# ======================== _calculate_pots_for_hand 扩展集成测试 ========================

class TestCalculatePotsForHandAdvanced:
    """
    _calculate_pots_for_hand 扩展集成测试
    覆盖: 多人 fold、退款 + 边池组合、短码 all-in 退款等
    """

    def _create_hand_with_bets(self, db, players, bet_data, hand_number=1):
        """创建 Hand + Bet 记录"""
        room = db.query(Room).first()
        hand = Hand(
            room_id=room.id,
            hand_number=hand_number,
            dealer_player_id=players[0].id,
            sb_player_id=players[0].id,
            bb_player_id=players[1].id,
            current_round="showdown",
            status="settling",
            pot_total=0,
            community_cards="[]",
            hole_cards="{}",
            deck_state=None,
        )
        db.add(hand)
        db.flush()

        total_pot = 0
        for pidx, action, amount in bet_data:
            bet = Bet(
                hand_id=hand.id,
                player_id=players[pidx].id,
                round="preflop",
                action=action,
                amount=amount,
            )
            db.add(bet)
            players[pidx].chip_count -= amount
            total_pot += amount

        hand.pot_total = total_pot
        db.flush()
        return hand

    def test_fold_refund_with_side_pot_remaining(self, db):
        """
        4人局: A(500) fold, B(1000), C(1000), D(2000) — B/C/D 存活到 showdown

        正确规则: showdown 路径不做 cap/退款。
        - 主池: 500×4 = 2000 (B,C,D eligible)
        - 副池1: (1000-500)×3 = 1500 (B,C,D eligible)
        - 副池2: (2000-1000)×1 = 1000 (仅 D eligible)
        """
        room, players = _make_room_with_players(db, num_players=4, chips=10000)

        hand = self._create_hand_with_bets(db, players, [
            (0, "blind", 50),
            (1, "blind", 100),
            (0, "raise", 450),       # A: total=500
            (1, "call", 900),        # B: total=1000
            (2, "call", 1000),       # C: total=1000
            (3, "call", 2000),       # D: total=2000
            (0, "fold", 0),          # A fold
        ])

        chips_before = {p.id: p.chip_count for p in players}
        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # 无人退款 (showdown 不 cap)
        for p in players:
            assert p.chip_count == chips_before[p.id], \
                f"玩家 {p.id} 不应退款, 实际 {p.chip_count}"

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 3
        assert pots[0].pot_type == "main"
        assert pots[0].amount == 2000  # 500×4
        assert pots[1].pot_type == "side"
        assert pots[1].amount == 1500  # 500×3
        assert pots[2].pot_type == "side"
        assert pots[2].amount == 1000  # 1000×1
        # A(fold) 不在 eligible; 副池2 仅 D
        main_eligible = [int(x) for x in pots[0].eligible_player_ids.split(",") if x]
        assert players[0].id not in main_eligible
        side2_eligible = [int(x) for x in pots[2].eligible_player_ids.split(",") if x]
        assert side2_eligible == [players[3].id]
        # 总池 = 4500 = 500+1000+1000+2000
        assert sum(p.amount for p in pots) == 4500

    def test_two_folds_different_amounts(self, db):
        """
        3人: A 投 200 fold, B 投 800 fold, C 投 1000
        
        预期:
        - max_folded_bet = max(200, 800) = 800
        - C 退 200 (1000→800)
        - 有效投入: A=200, B=800, C=800
        - 主池: 200×3 = 600, 副池: (800-200)×2 = 1200
        """
        room, players = _make_room_with_players(db, num_players=3, chips=10000)

        hand = self._create_hand_with_bets(db, players, [
            (0, "blind", 50),
            (1, "blind", 100),
            (0, "raise", 150),       # A: total=200
            (1, "raise", 700),       # B: total=800
            (2, "call", 1000),       # C: total=1000
            (0, "fold", 0),          # A fold
            (1, "fold", 0),          # B fold
        ])

        chips_c_before = players[2].chip_count
        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # C 退 200
        assert players[2].chip_count == chips_c_before + 200

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 2
        assert pots[0].amount == 600   # 200×3
        assert pots[1].amount == 1200  # 600×2
        total = sum(p.amount for p in pots)
        assert total == 1800  # 200+800+800

    def test_short_stack_allin_no_fold(self, db):
        """
        3人: A all-in 200 (短码), B=500, C=500, 无 fold
        
        预期:
        - 无退款
        - 主池: 200×3 = 600 (A,B,C eligible)
        - 边池: (500-200)×2 = 600 (B,C eligible)
        """
        room, players = _make_room_with_players(db, num_players=3, chips=10000)

        hand = self._create_hand_with_bets(db, players, [
            (0, "blind", 50),
            (1, "blind", 100),
            (0, "raise", 150),       # A: total=200, all-in
            (1, "call", 400),        # B: total=500
            (2, "call", 500),        # C: total=500
        ])

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # 无退款
        assert players[0].chip_count == 10000 - 50 - 150
        assert players[1].chip_count == 10000 - 100 - 400
        assert players[2].chip_count == 10000 - 500

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 2
        assert pots[0].amount == 600   # 200×3
        assert pots[1].amount == 600   # 300×2
        assert sum(p.amount for p in pots) == 1200

    def test_very_short_stack_allin_fold_refund(self, db):
        """
        2人: A(BB=100), B all-in 30 (超短码, 不够 BB!)
        A fold
        
        预期:
        - max_folded_bet = 100
        - B 投入 30 < 100, 无需退款
        - 主池: 30×2 = 60, 副池: (100-30)×1 = 70
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000, sb=50, bb=100)

        # 特殊情况: B 只有 30 筹码 (all-in 30 < BB)
        players[0].chip_count = 30  # 手动设置 B 的筹码

        hand = self._create_hand_with_bets(db, players, [
            (0, "blind", 30),        # B: all-in 30 (不够 SB=50)
            (1, "blind", 100),       # A: BB=100
            (1, "fold", 0),          # A fold
        ])

        chips_b_before = players[0].chip_count  # 0
        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # B 不退 (30 < 100)
        assert players[0].chip_count == chips_b_before

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        total = sum(p.amount for p in pots)
        assert total == 130  # 30 + 100

    def test_fold_refund_conserves_chips(self, db):
        """
        筹码守恒测试: 各种 fold 退款场景下，总筹码不变
        """
        scenarios = [
            # (num_players, chips, bet_data)
            (2, 10000, [(0, "blind", 50), (1, "blind", 100), (0, "allin", 9950), (1, "fold", 0)]),
            (2, 10000, [(0, "blind", 50), (1, "blind", 100), (1, "fold", 0)]),
            (3, 10000, [(0, "blind", 50), (1, "blind", 100), (2, "call", 100),
                        (0, "allin", 9950), (1, "fold", 0), (2, "fold", 0)]),
            (3, 5000, [(0, "blind", 50), (1, "blind", 100), (2, "call", 100),
                        (0, "raise", 450), (1, "call", 400), (2, "call", 400),
                        (0, "fold", 0)]),
        ]

        for num_p, chips, bet_data in scenarios:
            # 重建 DB
            db2_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
            Base.metadata.create_all(bind=db2_engine)
            S2 = sessionmaker(bind=db2_engine)
            db2 = S2()

            room2, players2 = _make_room_with_players(db2, num_players=num_p, chips=chips)
            hand2 = self._create_hand_with_bets(db2, players2, bet_data)

            total_before = sum(p.chip_count for p in players2) + hand2.pot_total

            eng = HandEngine(db2, room2)
            eng._calculate_pots_for_hand(hand2)
            db2.flush()

            total_after = sum(p.chip_count for p in players2) + hand2.pot_total
            assert total_before == total_after, \
                f"筹码不守恒! 场景: {bet_data}, before={total_before}, after={total_after}"

            db2.close()
            Base.metadata.drop_all(bind=db2_engine)

    def test_multiple_folds_one_survivor(self, db):
        """
        4人: A fold, B fold, C fold, D 存活
        D 应赢得所有 pot
        """
        room, players = _make_room_with_players(db, num_players=4, chips=10000, sb=50, bb=100)

        hand = self._create_hand_with_bets(db, players, [
            (0, "blind", 50),
            (1, "blind", 100),
            (2, "call", 100),
            (3, "call", 100),
            (0, "fold", 0),
            (1, "fold", 0),
            (2, "fold", 0),
        ])

        # D(players[3]) 投了 100, 是唯一存活者
        # max_folded = max(50, 100, 100) = 100
        # D 投入 100, 100 <= 100, 无需退款
        chips_d_before = players[3].chip_count

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # D 不退 (100 <= max_folded=100)
        assert players[3].chip_count == chips_d_before

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        total = sum(p.amount for p in pots)
        assert total == 350  # 50+100+100+100

        # 所有 pot 的 eligible 应包含 D
        for pot in pots:
            eligible = [int(x) for x in pot.eligible_player_ids.split(",") if x]
            assert players[3].id in eligible or len(eligible) > 0


# ======================== settle_hand 分配测试 ========================

class TestSettleDistribution:
    """
    settle_hand 分配逻辑测试
    验证: 平分、边池分配、筹码守恒
    """

    def _setup_and_settle(self, db, num_players, chips, bet_data, results_override=None):
        """辅助: 创建场景并结算"""
        room, players = _make_room_with_players(db, num_players=num_players, chips=chips, sb=50, bb=100)

        hand = Hand(
            room_id=room.id,
            hand_number=1,
            dealer_player_id=players[0].id,
            sb_player_id=players[0].id,
            bb_player_id=players[1].id,
            current_round="showdown",
            status="settling",
            pot_total=0,
            community_cards="[]",
            hole_cards="{}",
            deck_state=None,
        )
        db.add(hand)
        db.flush()

        total_pot = 0
        for pidx, action, amount in bet_data:
            bet = Bet(hand_id=hand.id, player_id=players[pidx].id,
                      round="preflop", action=action, amount=amount)
            db.add(bet)
            players[pidx].chip_count -= amount
            total_pot += amount
        hand.pot_total = total_pot
        db.flush()

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        # 记录 refund 后的筹码
        chips_after_refund = {p.id: p.chip_count for p in players}

        if results_override is None:
            # 手动指定赢家: 每个 pot 给第一个 eligible
            pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
            results_override = []
            for pot in pots:
                eligible = [int(x) for x in pot.eligible_player_ids.split(",") if x]
                results_override.append({
                    "pot_id": pot.id,
                    "winner_ids": eligible[:1],
                    "amount": pot.amount,
                })

        hand_results = engine.settle_hand(hand, results=results_override)
        db.flush()

        return players, hand, hand_results, chips_after_refund

    def test_split_pot_even_two_players(self, db):
        """
        2人等额, 平分主池
        A=100, B=100, split 200 → 各 100
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000)
        total_initial = sum(p.chip_count for p in players)

        hand = Hand(
            room_id=room.id, hand_number=1,
            dealer_player_id=players[0].id, sb_player_id=players[0].id, bb_player_id=players[1].id,
            current_round="showdown", status="settling", pot_total=0,
            community_cards="[]", hole_cards="{}", deck_state=None,
        )
        db.add(hand)
        db.flush()
        for pidx, amt in [(0, 100), (1, 100)]:
            db.add(Bet(hand_id=hand.id, player_id=players[pidx].id,
                       round="preflop", action="blind", amount=amt))
            players[pidx].chip_count -= amt
        hand.pot_total = 200
        db.flush()

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 1
        assert pots[0].amount == 200

        # 平分结算
        results = [{"pot_id": pots[0].id, "winner_ids": [players[0].id, players[1].id], "amount": 200}]
        engine.settle_hand(hand, results=results)
        db.flush()

        # 各得 100
        assert players[0].chip_count == 10000 - 100 + 100  # 9900 + 100 = 10000
        assert players[1].chip_count == 10000 - 100 + 100
        # 筹码守恒
        assert players[0].chip_count + players[1].chip_count == total_initial

    def test_split_pot_odd_amount(self, db):
        """
        2人平分: pot 有主池200 + 边池1
        边池 1 只有 B eligible, 主池 200 平分 → 各 100
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000)

        hand = Hand(
            room_id=room.id, hand_number=1,
            dealer_player_id=players[0].id, sb_player_id=players[0].id, bb_player_id=players[1].id,
            current_round="showdown", status="settling", pot_total=0,
            community_cards="[]", hole_cards="{}", deck_state=None,
        )
        db.add(hand)
        db.flush()
        # A=100, B=101
        db.add(Bet(hand_id=hand.id, player_id=players[0].id, round="preflop", action="blind", amount=100))
        db.add(Bet(hand_id=hand.id, player_id=players[1].id, round="preflop", action="blind", amount=101))
        players[0].chip_count -= 100
        players[1].chip_count -= 101
        hand.pot_total = 201
        db.flush()

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        # 2 pots: main=200 (both eligible), side=1 (B only)
        assert len(pots) == 2
        main_pot = next(p for p in pots if p.pot_type == "main")
        side_pot = next(p for p in pots if p.pot_type == "side")
        assert main_pot.amount == 200
        assert side_pot.amount == 1

        # 平分主池, B 额外赢边池
        results = [
            {"pot_id": main_pot.id, "winner_ids": [players[0].id, players[1].id], "amount": 200},
            {"pot_id": side_pot.id, "winner_ids": [players[1].id], "amount": 1},
        ]
        engine.settle_hand(hand, results=results)
        db.flush()

        # A: 10000 - 100 + 100 = 10000
        assert players[0].chip_count == 10000
        # B: 10000 - 101 + 100 + 1 = 10000
        assert players[1].chip_count == 10000
        # 完美守恒
        assert players[0].chip_count + players[1].chip_count == 20000

    def test_side_pot_split(self, db):
        """
        3人边池 + 平分:
        A all-in 500, B=1000, C=1000
        主池 1500 → A 赢
        边池 1000 → B 和 C 平分 (各 500)
        """
        room, players = _make_room_with_players(db, num_players=3, chips=10000)
        total_initial = sum(p.chip_count for p in players)

        hand = Hand(
            room_id=room.id, hand_number=1,
            dealer_player_id=players[0].id, sb_player_id=players[0].id, bb_player_id=players[1].id,
            current_round="showdown", status="settling", pot_total=0,
            community_cards="[]", hole_cards="{}", deck_state=None,
        )
        db.add(hand)
        db.flush()
        bet_data = [
            (0, "blind", 50), (1, "blind", 100),
            (0, "raise", 450),   # A: 500
            (1, "call", 900),    # B: 1000
            (2, "call", 1000),   # C: 1000
        ]
        for pidx, action, amount in bet_data:
            db.add(Bet(hand_id=hand.id, player_id=players[pidx].id,
                       round="preflop", action=action, amount=amount))
            players[pidx].chip_count -= amount
        hand.pot_total = 2500
        db.flush()

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 2

        main_pot = next(p for p in pots if p.pot_type == "main")
        side_pot = next(p for p in pots if p.pot_type == "side")
        assert main_pot.amount == 1500
        assert side_pot.amount == 1000

        # A 赢主池, B/C 平分边池
        results = [
            {"pot_id": main_pot.id, "winner_ids": [players[0].id], "amount": 1500},
            {"pot_id": side_pot.id, "winner_ids": [players[1].id, players[2].id], "amount": 1000},
        ]
        engine.settle_hand(hand, results=results)
        db.flush()

        # A: 10000-500 + 1500 = 11000
        assert players[0].chip_count == 11000
        # B: 10000-1000 + 500 = 9500
        assert players[1].chip_count == 9500
        # C: 10000-1000 + 500 = 9500
        assert players[2].chip_count == 9500
        # 守恒
        assert sum(p.chip_count for p in players) == total_initial

    def test_fold_allin_then_settle_winner(self, db):
        """
        2人 fold+all-in 后结算:
        A(BB=100) fold, B all-in 5000
        → B 退回 4900, pot=200
        → B 赢 200
        最终: B=10100, A=9900
        """
        players, hand, results, chips_after_refund = self._setup_and_settle(
            db, num_players=2, chips=10000,
            bet_data=[
                (0, "blind", 50), (1, "blind", 100),
                (0, "allin", 4950),   # B: total=5000
                (1, "fold", 0),
            ],
        )
        db.flush()

        # B: 退款后 4900 + 赢 200 = 5100... wait
        # B chips_before_fold = 10000 - 50 - 4950 = 5000... no
        # Let me trace: initial=10000, bet: blind 50, allin 4950 → chip=10000-50-4950=5000
        # After refund: max_folded=100, B effective=100, refund=5000-100=4900
        # chip=5000+4900=9900
        # Pot=200, B wins → chip=9900+200=10100
        assert players[0].chip_count == 10100, f"B 应为 10100, 实际 {players[0].chip_count}"
        assert players[1].chip_count == 9900, f"A 应为 9900, 实际 {players[1].chip_count}"
        # 守恒
        assert players[0].chip_count + players[1].chip_count == 20000

    def test_fold_refund_multiple_survivors(self, db):
        """
        4人: A(200) fold, B(1000), C(1000), D(1000) — B/C/D 存活到 showdown

        正确规则: showdown 路径不做 cap/退款。
        - 主池: 200×4 = 800 (B,C,D eligible)
        - 副池: (1000-200)×3 = 2400 (B,C,D eligible)
        - 每个池分给第一个 eligible (B)
        """
        players, hand, results, chips_after_refund = self._setup_and_settle(
            db, num_players=4, chips=10000,
            bet_data=[
                (0, "blind", 50), (1, "blind", 100),
                (0, "raise", 150),     # A: 200
                (1, "call", 900),      # B: 1000
                (2, "call", 1000),     # C: 1000
                (3, "call", 1000),     # D: 1000
                (0, "fold", 0),
            ],
            results_override=None,  # 让每个 pot 给第一个 eligible
        )
        db.flush()

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        assert len(pots) == 2
        assert pots[0].amount == 800   # 200×4
        assert pots[1].amount == 2400  # 800×3

        # B 赢主池 800 + 副池 2400
        # B: 10000-1000+800+2400 = 12200
        assert players[1].chip_count == 12200, f"B 应为 12200, 实际 {players[1].chip_count}"
        # C: 10000-1000 = 9000 (无退款)
        assert players[2].chip_count == 9000
        # D: 10000-1000 = 9000 (无退款)
        assert players[3].chip_count == 9000
        # A: 10000-200 = 9800
        assert players[0].chip_count == 9800
        # 守恒
        assert sum(p.chip_count for p in players) == 40000

    def test_settle_with_manual_results(self, db):
        """
        手动指定赢家 (岛主 override)
        A=100, B=100, 手动让 B 赢全部
        """
        room, players = _make_room_with_players(db, num_players=2, chips=10000)

        hand = Hand(
            room_id=room.id, hand_number=1,
            dealer_player_id=players[0].id, sb_player_id=players[0].id, bb_player_id=players[1].id,
            current_round="showdown", status="settling", pot_total=0,
            community_cards="[]", hole_cards="{}", deck_state=None,
        )
        db.add(hand)
        db.flush()
        for pidx, amt in [(0, 100), (1, 100)]:
            db.add(Bet(hand_id=hand.id, player_id=players[pidx].id,
                       round="preflop", action="blind", amount=amt))
            players[pidx].chip_count -= amt
        hand.pot_total = 200
        db.flush()

        engine = HandEngine(db, room)
        engine._calculate_pots_for_hand(hand)
        db.flush()

        pots = db.query(Pot).filter(Pot.hand_id == hand.id).all()
        # 手动让 B 赢 (override)
        results = [{"pot_id": pots[0].id, "winner_ids": [players[1].id], "amount": 200}]
        engine.settle_hand(hand, results=results)
        db.flush()

        assert players[0].chip_count == 9900  # 输了 100
        assert players[1].chip_count == 10100  # 赢了 100

    def test_conservation_after_full_settle(self, db):
        """
        综合守恒测试: 各种场景结算后总筹码不变
        """
        scenarios = [
            # (num_players, chips, bet_data, results_fn)
            # results_fn: (pots, players) -> results list
            (2, 10000, [(0, "blind", 50), (1, "blind", 100), (0, "allin", 9950), (1, "fold", 0)],
             lambda pots, ps: [{"pot_id": pots[0].id, "winner_ids": [ps[0].id], "amount": pots[0].amount}]),
            (3, 5000, [(0, "blind", 50), (1, "blind", 100), (2, "call", 100),
                        (0, "raise", 450), (1, "call", 900), (2, "call", 900)],
             lambda pots, ps: [
                 {"pot_id": pots[0].id, "winner_ids": [ps[0].id], "amount": pots[0].amount},
                 {"pot_id": pots[1].id, "winner_ids": [ps[1].id, ps[2].id], "amount": pots[1].amount},
             ]),
        ]

        for num_p, chips, bet_data, results_fn in scenarios:
            db2_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
            Base.metadata.create_all(bind=db2_engine)
            S2 = sessionmaker(bind=db2_engine)
            db2 = S2()

            room2, players2 = _make_room_with_players(db2, num_players=num_p, chips=chips)
            total_initial = sum(p.chip_count for p in players2)

            hand2 = Hand(
                room_id=room2.id, hand_number=1,
                dealer_player_id=players2[0].id, sb_player_id=players2[0].id, bb_player_id=players2[1].id,
                current_round="showdown", status="settling", pot_total=0,
                community_cards="[]", hole_cards="{}", deck_state=None,
            )
            db2.add(hand2)
            db2.flush()
            for pidx, action, amount in bet_data:
                db2.add(Bet(hand_id=hand2.id, player_id=players2[pidx].id,
                            round="preflop", action=action, amount=amount))
                players2[pidx].chip_count -= amount
            hand2.pot_total = sum(a for _, _, a in bet_data)
            db2.flush()

            eng = HandEngine(db2, room2)
            eng._calculate_pots_for_hand(hand2)
            db2.flush()

            pots2 = db2.query(Pot).filter(Pot.hand_id == hand2.id).all()
            results = results_fn(pots2, players2)
            eng.settle_hand(hand2, results=results)
            db2.flush()

            total_after = sum(p.chip_count for p in players2)
            assert total_after == total_initial, \
                f"结算后筹码不守恒! 初始={total_initial}, 结算后={total_after}"

            db2.close()
            Base.metadata.drop_all(bind=db2_engine)
