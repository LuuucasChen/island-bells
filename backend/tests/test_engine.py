"""岛屿铃钱记 — 游戏引擎单元测试"""

from app.engine.hand_engine import (
    calculate_pots,
    validate_bet_action,
    next_round,
    rotate_dealer,
    assign_positions,
    get_action_order,
    ROUND_ORDER,
)


class TestRoundTransition:
    """阶段转换测试"""

    def test_next_round_sequence(self):
        assert next_round("preflop") == "flop"
        assert next_round("flop") == "turn"
        assert next_round("turn") == "river"
        assert next_round("river") == "showdown"

    def test_next_round_showdown_is_none(self):
        assert next_round("showdown") is None

    def test_round_order(self):
        assert ROUND_ORDER == ["preflop", "flop", "turn", "river", "showdown"]


class TestSeatRotation:
    """座位/角色轮转测试"""

    def test_rotate_dealer_basic(self):
        seats = [0, 3, 5, 7]
        # 当前庄位 0, 下一个应该是 3
        assert rotate_dealer(seats, 0) == 3
        # 当前庄位 3, 下一个应该是 5
        assert rotate_dealer(seats, 3) == 5
        # 当前庄位 7, 回到 0
        assert rotate_dealer(seats, 7) == 0

    def test_rotate_dealer_two_players(self):
        seats = [0, 5]
        assert rotate_dealer(seats, 0) == 5
        assert rotate_dealer(seats, 5) == 0

    def test_assign_positions_three_plus(self):
        seats = [1, 3, 5]
        pos = assign_positions(seats, dealer_seat=1)
        assert pos["dealer_seat"] == 1
        assert pos["sb_seat"] == 3
        assert pos["bb_seat"] == 5

    def test_assign_positions_two_players(self):
        """2人对局: 庄家=SB"""
        seats = [0, 4]
        pos = assign_positions(seats, dealer_seat=0)
        assert pos["dealer_seat"] == 0
        assert pos["sb_seat"] == 0   # 庄家=SB
        assert pos["bb_seat"] == 4

    def test_assign_positions_too_few(self):
        import pytest
        from app.utils import BadRequestException
        with pytest.raises(BadRequestException):
            assign_positions([5], dealer_seat=5)

    def test_get_action_order_preflop(self):
        seats = [0, 2, 4]
        order = get_action_order(seats, dealer_seat=0, current_round="preflop")
        # Preflop: UTG (BB后一位) 先行动
        # D=0, SB=2, BB=4, UTG=0 (after BB=4, next is 0)
        assert order[0] == 0  # UTG
        assert len(order) == 3

    def test_get_action_order_postflop(self):
        seats = [0, 2, 4]
        order = get_action_order(seats, dealer_seat=0, current_round="flop")
        # Postflop: SB(庄家后一位) 先行动
        assert order[0] == 2  # SB first
        assert order[-1] == 0  # Dealer last


class TestBetValidation:
    """下注校验测试"""

    def test_fold_always_valid(self):
        result = validate_bet_action("fold", 0, 1000, 0, 100, 50)
        assert result["valid"] is True
        assert result["actual_amount"] == 0

    def test_call_when_no_bet(self):
        """当前没有加注时，call 等于 check"""
        result = validate_bet_action("call", 0, 1000, 0, 0, 50)
        assert result["valid"] is True
        assert result["actual_amount"] == 0

    def test_call_normal(self):
        """标准 call: 补齐到当前最高注"""
        result = validate_bet_action("call", 0, 1000, 50, 200, 50)
        assert result["valid"] is True
        assert result["actual_amount"] == 150  # 200 - 50

    def test_call_short_stack(self):
        """铃钱不够 call 全额时，all-in"""
        result = validate_bet_action("call", 0, 80, 50, 200, 50)
        assert result["valid"] is True
        assert result["actual_amount"] == 80  # 只有80, 全部投入

    def test_raise_valid(self):
        result = validate_bet_action("raise", 300, 1000, 50, 200, 50)
        assert result["valid"] is True
        assert result["actual_amount"] == 300

    def test_raise_too_small(self):
        """追加金额不满足最小加注"""
        result = validate_bet_action("raise", 50, 1000, 50, 200, 50)
        # 需要追加到 200+50=250, 当前已有50, 还需200, 但只加了50
        assert result["valid"] is False

    def test_allin_always_valid(self):
        result = validate_bet_action("allin", 0, 500, 0, 200, 50)
        assert result["valid"] is True
        assert result["actual_amount"] == 500

    def test_check_valid(self):
        result = validate_bet_action("check", 0, 1000, 0, 0, 50)
        assert result["valid"] is True
        assert result["actual_amount"] == 0

    def test_unknown_action(self):
        result = validate_bet_action("unknown_action", 0, 1000, 0, 0, 50)
        assert result["valid"] is False


class TestPotCalculation:
    """收获篮(Pot)计算测试"""

    def test_simple_pot(self):
        """3人等额投入 → 1个主收获篮"""
        bets = [
            {"player_id": 1, "total_bet": 100},
            {"player_id": 2, "total_bet": 100},
            {"player_id": 3, "total_bet": 100},
        ]
        pots = calculate_pots(bets)
        assert len(pots) == 1
        assert pots[0]["pot_type"] == "main"
        assert pots[0]["amount"] == 300
        assert len(pots[0]["eligible_player_ids"]) == 3

    def test_side_pot(self):
        """
        3人: P1投入100, P2投入200, P3投入200
        → 主收获篮: 100×3 = 300 (3人都有资格)
        → 副收获篮: (200-100)×2 = 200 (P2,P3有资格)
        """
        bets = [
            {"player_id": 1, "total_bet": 100},
            {"player_id": 2, "total_bet": 200},
            {"player_id": 3, "total_bet": 200},
        ]
        pots = calculate_pots(bets)
        assert len(pots) == 2
        assert pots[0]["pot_type"] == "main"
        assert pots[0]["amount"] == 300
        assert len(pots[0]["eligible_player_ids"]) == 3
        assert pots[1]["pot_type"] == "side"
        assert pots[1]["amount"] == 200
        assert len(pots[1]["eligible_player_ids"]) == 2

    def test_multiple_side_pots(self):
        """
        4人: P1=50, P2=100, P3=200, P4=200
        → 主: 50×4=200
        → 副1: (100-50)×3=150
        → 副2: (200-100)×2=200
        """
        bets = [
            {"player_id": 1, "total_bet": 50},
            {"player_id": 2, "total_bet": 100},
            {"player_id": 3, "total_bet": 200},
            {"player_id": 4, "total_bet": 200},
        ]
        pots = calculate_pots(bets)
        assert len(pots) == 3
        assert pots[0]["amount"] == 200
        assert pots[1]["amount"] == 150
        assert pots[2]["amount"] == 200

    def test_empty_bets(self):
        pots = calculate_pots([])
        assert pots == []

    def test_zero_bets(self):
        """所有玩家投入为0"""
        bets = [
            {"player_id": 1, "total_bet": 0},
            {"player_id": 2, "total_bet": 0},
        ]
        pots = calculate_pots(bets)
        assert pots == []
