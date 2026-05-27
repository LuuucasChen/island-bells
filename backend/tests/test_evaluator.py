"""岛屿铃钱记 — 德州扑克牌力评估器单元测试

覆盖:
1. evaluate_5cards: 10 种牌型识别
2. 同牌型内大小比较 (kicker, 对子大小等)
3. 跨牌型比较 (高牌 < 一对 < ... < 皇家同花顺)
4. 边界情况: wheel 顺子 (A-2-3-4-5), broadway 顺子 (10-J-Q-K-A)
5. evaluate_hand: 7 选 5 最佳组合
6. compare_hands: 多人比牌 + 平局
"""

import pytest
from app.engine.deck import Card
from app.engine.evaluator import (
    evaluate_5cards,
    evaluate_hand,
    compare_hands,
    get_hand_type,
    get_hand_type_name,
    _check_straight,
    HAND_TYPE_NAMES,
)


# 辅助: 快速创建牌
def C(suit: str, rank: int) -> Card:
    return Card(suit=suit, rank=rank)


# 快捷花色
S, H, D, CL = "spades", "hearts", "diamonds", "clubs"


# ======================== 1. 各牌型识别 ========================

class TestHandTypeIdentification:
    """验证 evaluate_5cards 正确识别 10 种牌型"""

    def test_royal_flush(self):
        """皇家同花顺: A-K-Q-J-10 同花色"""
        cards = [C(S, 14), C(S, 13), C(S, 12), C(S, 11), C(S, 10)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 10
        assert get_hand_type_name(score) == "皇家同花顺"

    def test_straight_flush(self):
        """同花顺: 9-8-7-6-5 同花色"""
        cards = [C(H, 9), C(H, 8), C(H, 7), C(H, 6), C(H, 5)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 9
        assert get_hand_type_name(score) == "同花顺"

    def test_four_of_a_kind(self):
        """四条: 4 张相同点数"""
        cards = [C(S, 8), C(H, 8), C(D, 8), C(CL, 8), C(S, 3)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 8
        assert get_hand_type_name(score) == "四条"

    def test_full_house(self):
        """葫芦: 三条 + 一对"""
        cards = [C(S, 10), C(H, 10), C(D, 10), C(S, 5), C(H, 5)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 7
        assert get_hand_type_name(score) == "葫芦"

    def test_flush(self):
        """同花: 5 张同花色"""
        cards = [C(D, 14), C(D, 10), C(D, 7), C(D, 4), C(D, 2)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 6
        assert get_hand_type_name(score) == "同花"

    def test_straight(self):
        """顺子: 5 张连续"""
        cards = [C(S, 9), C(H, 8), C(D, 7), C(CL, 6), C(S, 5)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 5
        assert get_hand_type_name(score) == "顺子"

    def test_three_of_a_kind(self):
        """三条: 3 张相同点数"""
        cards = [C(S, 7), C(H, 7), C(D, 7), C(CL, 12), C(S, 3)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 4
        assert get_hand_type_name(score) == "三条"

    def test_two_pair(self):
        """两对: 2 组一对"""
        cards = [C(S, 11), C(H, 11), C(D, 4), C(CL, 4), C(S, 9)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 3
        assert get_hand_type_name(score) == "两对"

    def test_one_pair(self):
        """一对: 1 组一对"""
        cards = [C(S, 6), C(H, 6), C(D, 14), C(CL, 10), C(S, 3)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 2
        assert get_hand_type_name(score) == "一对"

    def test_high_card(self):
        """高牌: 不构成任何牌型"""
        cards = [C(S, 14), C(H, 10), C(D, 7), C(CL, 4), C(S, 2)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 1
        assert get_hand_type_name(score) == "高牌"


# ======================== 2. 同牌型内大小比较 ========================

class TestSameTypeComparison:
    """验证同牌型内的正确排序"""

    # --- 同花顺 ---
    def test_straight_flush_higher_wins(self):
        """同花顺: 高牌大的赢"""
        high = evaluate_5cards([C(S, 10), C(S, 9), C(S, 8), C(S, 7), C(S, 6)])
        low = evaluate_5cards([C(H, 9), C(H, 8), C(H, 7), C(H, 6), C(H, 5)])
        assert high > low

    # --- 四条 ---
    def test_four_of_a_kind_higher_quad_wins(self):
        """四条: 四张大的赢"""
        quad_k = evaluate_5cards([C(S, 13), C(H, 13), C(D, 13), C(CL, 13), C(S, 2)])
        quad_5 = evaluate_5cards([C(S, 5), C(H, 5), C(D, 5), C(CL, 5), C(S, 14)])
        assert quad_k > quad_5

    def test_four_of_a_kind_kicker_breaks_tie(self):
        """四条相同: 踢脚大的赢"""
        quad_8_a = evaluate_5cards([C(S, 8), C(H, 8), C(D, 8), C(CL, 8), C(S, 14)])
        quad_8_k = evaluate_5cards([C(S, 8), C(H, 8), C(D, 8), C(CL, 8), C(S, 13)])
        assert quad_8_a > quad_8_k

    # --- 葫芦 ---
    def test_full_house_higher_trips_wins(self):
        """葫芦: 三条大的赢"""
        fh_a = evaluate_5cards([C(S, 14), C(H, 14), C(D, 14), C(S, 5), C(H, 5)])
        fh_k = evaluate_5cards([C(S, 13), C(H, 13), C(D, 13), C(S, 5), C(H, 5)])
        assert fh_a > fh_k

    def test_full_house_pair_breaks_tie(self):
        """葫芦三条相同: 对子大的赢"""
        fh_10_8 = evaluate_5cards([C(S, 10), C(H, 10), C(D, 10), C(S, 8), C(H, 8)])
        fh_10_5 = evaluate_5cards([C(S, 10), C(H, 10), C(D, 10), C(S, 5), C(H, 5)])
        assert fh_10_8 > fh_10_5

    # --- 同花 ---
    def test_flush_high_card_wins(self):
        """同花: 最高牌大的赢"""
        flush_a = evaluate_5cards([C(D, 14), C(D, 8), C(D, 6), C(D, 4), C(D, 2)])
        flush_k = evaluate_5cards([C(S, 13), C(S, 8), C(S, 6), C(S, 4), C(S, 2)])
        assert flush_a > flush_k

    def test_flush_second_card_breaks_tie(self):
        """同花最高牌相同: 第二大牌决定"""
        flush_a_10 = evaluate_5cards([C(D, 14), C(D, 10), C(D, 6), C(D, 4), C(D, 2)])
        flush_a_9 = evaluate_5cards([C(S, 14), C(S, 9), C(S, 6), C(S, 4), C(S, 2)])
        assert flush_a_10 > flush_a_9

    # --- 顺子 ---
    def test_straight_higher_wins(self):
        """顺子: 高牌大的赢"""
        straight_k = evaluate_5cards([C(S, 13), C(H, 12), C(D, 11), C(CL, 10), C(S, 9)])
        straight_10 = evaluate_5cards([C(S, 10), C(H, 9), C(D, 8), C(CL, 7), C(S, 6)])
        assert straight_k > straight_10

    # --- 三条 ---
    def test_trips_higher_wins(self):
        """三条: 三张大的赢"""
        trips_a = evaluate_5cards([C(S, 14), C(H, 14), C(D, 14), C(CL, 8), C(S, 3)])
        trips_k = evaluate_5cards([C(S, 13), C(H, 13), C(D, 13), C(CL, 8), C(S, 3)])
        assert trips_a > trips_k

    def test_trips_kicker_breaks_tie(self):
        """三条相同: 踢脚大的赢"""
        trips_7_k = evaluate_5cards([C(S, 7), C(H, 7), C(D, 7), C(CL, 13), C(S, 3)])
        trips_7_q = evaluate_5cards([C(S, 7), C(H, 7), C(D, 7), C(CL, 12), C(S, 3)])
        assert trips_7_k > trips_7_q

    # --- 两对 ---
    def test_two_pair_higher_pair_wins(self):
        """两对: 大对子大的赢"""
        tp_a_5 = evaluate_5cards([C(S, 14), C(H, 14), C(D, 5), C(CL, 5), C(S, 3)])
        tp_k_q = evaluate_5cards([C(S, 13), C(H, 13), C(D, 12), C(CL, 12), C(S, 3)])
        assert tp_a_5 > tp_k_q

    def test_two_pair_second_pair_breaks_tie(self):
        """两对大对相同: 小对子大的赢"""
        tp_a_8 = evaluate_5cards([C(S, 14), C(H, 14), C(D, 8), C(CL, 8), C(S, 3)])
        tp_a_5 = evaluate_5cards([C(S, 14), C(H, 14), C(D, 5), C(CL, 5), C(S, 3)])
        assert tp_a_8 > tp_a_5

    def test_two_pair_kicker_breaks_tie(self):
        """两对完全相同: 踢脚大的赢"""
        tp_a_k_k = evaluate_5cards([C(S, 14), C(H, 14), C(D, 13), C(CL, 13), C(S, 12)])
        tp_a_k_q = evaluate_5cards([C(S, 14), C(H, 14), C(D, 13), C(CL, 13), C(S, 10)])
        assert tp_a_k_k > tp_a_k_q

    # --- 一对 ---
    def test_one_pair_higher_wins(self):
        """一对: 对子大的赢"""
        pair_a = evaluate_5cards([C(S, 14), C(H, 14), C(D, 8), C(CL, 5), C(S, 3)])
        pair_k = evaluate_5cards([C(S, 13), C(H, 13), C(D, 8), C(CL, 5), C(S, 3)])
        assert pair_a > pair_k

    def test_one_pair_kickers_break_tie(self):
        """一对相同: 踢脚依次比较"""
        pair_8_a = evaluate_5cards([C(S, 8), C(H, 8), C(D, 14), C(CL, 10), C(S, 3)])
        pair_8_k = evaluate_5cards([C(S, 8), C(H, 8), C(D, 13), C(CL, 10), C(S, 3)])
        assert pair_8_a > pair_8_k

    # --- 高牌 ---
    def test_high_card_comparison(self):
        """高牌: 依次比较"""
        hc_a = evaluate_5cards([C(S, 14), C(H, 8), C(D, 6), C(CL, 4), C(S, 2)])
        hc_k = evaluate_5cards([C(S, 13), C(H, 8), C(D, 6), C(CL, 4), C(S, 2)])
        assert hc_a > hc_k


# ======================== 3. 跨牌型比较 ========================

class TestCrossTypeComparison:
    """验证高牌型总是赢低牌型"""

    def test_pair_beats_high_card(self):
        pair = evaluate_5cards([C(S, 2), C(H, 2), C(D, 14), C(CL, 13), C(S, 12)])
        high = evaluate_5cards([C(S, 14), C(H, 13), C(D, 12), C(CL, 11), C(S, 9)])
        assert pair > high

    def test_two_pair_beats_pair(self):
        tp = evaluate_5cards([C(S, 3), C(H, 3), C(D, 4), C(CL, 4), C(S, 14)])
        pair = evaluate_5cards([C(S, 14), C(H, 14), C(D, 13), C(CL, 12), C(S, 11)])
        assert tp > pair

    def test_trips_beats_two_pair(self):
        trips = evaluate_5cards([C(S, 2), C(H, 2), C(D, 2), C(CL, 14), C(S, 13)])
        tp = evaluate_5cards([C(S, 14), C(H, 14), C(D, 13), C(CL, 13), C(S, 12)])
        assert trips > tp

    def test_straight_beats_trips(self):
        straight = evaluate_5cards([C(S, 6), C(H, 5), C(D, 4), C(CL, 3), C(S, 2)])
        trips = evaluate_5cards([C(S, 14), C(H, 14), C(D, 14), C(CL, 13), C(S, 12)])
        assert straight > trips

    def test_flush_beats_straight(self):
        flush = evaluate_5cards([C(D, 8), C(D, 6), C(D, 5), C(D, 3), C(D, 2)])
        straight = evaluate_5cards([C(S, 14), C(H, 13), C(D, 12), C(CL, 11), C(S, 10)])
        assert flush > straight

    def test_full_house_beats_flush(self):
        fh = evaluate_5cards([C(S, 3), C(H, 3), C(D, 3), C(CL, 2), C(S, 2)])
        flush = evaluate_5cards([C(D, 14), C(D, 13), C(D, 12), C(D, 11), C(D, 9)])
        assert fh > flush

    def test_four_beats_full_house(self):
        four = evaluate_5cards([C(S, 2), C(H, 2), C(D, 2), C(CL, 2), C(S, 14)])
        fh = evaluate_5cards([C(S, 14), C(H, 14), C(D, 14), C(CL, 13), C(S, 13)])
        assert four > fh

    def test_straight_flush_beats_four(self):
        sf = evaluate_5cards([C(H, 6), C(H, 5), C(H, 4), C(H, 3), C(H, 2)])
        four = evaluate_5cards([C(S, 14), C(H, 14), C(D, 14), C(CL, 14), C(S, 13)])
        assert sf > four

    def test_royal_flush_beats_straight_flush(self):
        royal = evaluate_5cards([C(S, 14), C(S, 13), C(S, 12), C(S, 11), C(S, 10)])
        sf = evaluate_5cards([C(H, 13), C(H, 12), C(H, 11), C(H, 10), C(H, 9)])
        assert royal > sf


# ======================== 4. 边界情况 ========================

class TestEdgeCases:
    """边界和特殊情况"""

    def test_wheel_straight(self):
        """A-2-3-4-5 顺子 (wheel), high=5"""
        cards = [C(S, 14), C(H, 2), C(D, 3), C(CL, 4), C(S, 5)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 5
        assert score == (5, 5)  # high card = 5

    def test_broadway_straight(self):
        """10-J-Q-K-A 顺子 (broadway), high=14"""
        cards = [C(S, 10), C(H, 11), C(D, 12), C(CL, 13), C(S, 14)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 5
        assert score == (5, 14)

    def test_wheel_is_lowest_straight(self):
        """Wheel (5-high) 是最小的顺子"""
        wheel = evaluate_5cards([C(S, 14), C(H, 2), C(D, 3), C(CL, 4), C(S, 5)])
        six_high = evaluate_5cards([C(S, 6), C(H, 5), C(D, 4), C(CL, 3), C(S, 2)])
        assert six_high > wheel

    def test_wheel_beats_nothing_but_loses_to_6_high_straight(self):
        """Wheel 顺子 > 一对 A"""
        wheel = evaluate_5cards([C(S, 14), C(H, 2), C(D, 3), C(CL, 4), C(S, 5)])
        pair_a = evaluate_5cards([C(S, 14), C(H, 14), C(D, 13), C(CL, 12), C(S, 11)])
        assert wheel > pair_a

    def test_broadway_straight_vs_wheel(self):
        """Broadway (A-high) > Wheel (5-high)"""
        broadway = evaluate_5cards([C(S, 10), C(H, 11), C(D, 12), C(CL, 13), C(S, 14)])
        wheel = evaluate_5cards([C(H, 14), C(D, 2), C(CL, 3), C(S, 4), C(H, 5)])
        assert broadway > wheel

    def test_not_straight_with_gap(self):
        """有间隔不是顺子"""
        cards = [C(S, 10), C(H, 8), C(D, 7), C(CL, 6), C(S, 5)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 1  # 高牌

    def test_not_flush_different_suits(self):
        """不同花色不是同花"""
        cards = [C(S, 14), C(H, 10), C(D, 7), C(CL, 4), C(S, 2)]
        score = evaluate_5cards(cards)
        assert get_hand_type(score) == 1

    def test_full_house_vs_trips(self):
        """葫芦 > 三条 (即使三条点数更大)"""
        fh = evaluate_5cards([C(S, 3), C(H, 3), C(D, 3), C(CL, 2), C(S, 2)])
        trips_a = evaluate_5cards([C(S, 14), C(H, 14), C(D, 14), C(CL, 8), C(S, 3)])
        assert fh > trips_a

    def test_equal_hands_tie(self):
        """完全相同的牌力 = 平局"""
        hand1 = evaluate_5cards([C(S, 14), C(H, 14), C(D, 10), C(CL, 5), C(S, 3)])
        hand2 = evaluate_5cards([C(D, 14), C(CL, 14), C(H, 10), C(S, 5), C(D, 3)])
        assert hand1 == hand2


# ======================== 5. _check_straight 单元测试 ========================

class TestCheckStraight:
    """顺子检测辅助函数"""

    def test_normal_straight(self):
        is_s, high = _check_straight([5, 6, 7, 8, 9])
        assert is_s and high == 9

    def test_broadway(self):
        is_s, high = _check_straight([10, 11, 12, 13, 14])
        assert is_s and high == 14

    def test_wheel(self):
        is_s, high = _check_straight([2, 3, 4, 5, 14])
        assert is_s and high == 5

    def test_not_straight_gap(self):
        is_s, _ = _check_straight([2, 3, 5, 6, 7])
        assert not is_s

    def test_not_straight_pair(self):
        is_s, _ = _check_straight([2, 3, 4, 4, 5])
        assert not is_s  # 有重复，unique < 5

    def test_7_card_straight_pick_best(self):
        """7 张牌中有顺子，能正确检测"""
        is_s, high = _check_straight([2, 5, 6, 7, 8, 9, 14])
        assert is_s and high == 9


# ======================== 6. evaluate_hand (7 选 5) ========================

class TestEvaluateHand:
    """7 张牌选最佳 5 张"""

    def test_best_5_from_7_flush(self):
        """7 张中有同花，选出最佳同花"""
        hole = [C(S, 14), C(S, 13)]
        community = [C(S, 10), C(S, 8), C(S, 3), C(H, 14), C(D, 2)]
        score = evaluate_hand(hole, community)
        assert get_hand_type(score) == 6  # 同花
        # 最佳同花: A-K-10-8-3 of spades

    def test_best_5_from_7_full_house(self):
        """7 张中凑出葫芦"""
        hole = [C(S, 10), C(H, 10)]
        community = [C(D, 10), C(CL, 5), C(S, 5), C(H, 2), C(D, 3)]
        score = evaluate_hand(hole, community)
        assert get_hand_type(score) == 7  # 葫芦: 10s full of 5s

    def test_best_5_from_7_straight(self):
        """7 张中凑出顺子"""
        hole = [C(S, 6), C(H, 7)]
        community = [C(D, 8), C(CL, 9), C(S, 10), C(H, 2), C(D, 3)]
        score = evaluate_hand(hole, community)
        assert get_hand_type(score) == 5  # 顺子: 6-7-8-9-10

    def test_best_5_picks_higher_kicker(self):
        """7 张中选最大踢脚"""
        hole = [C(S, 8), C(H, 8)]
        community = [C(D, 3), C(CL, 4), C(S, 5), C(H, 14), C(D, 13)]
        score = evaluate_hand(hole, community)
        assert get_hand_type(score) == 2  # 一对 8
        # 踢脚应该是 A, K, 5
        assert score == (2, 8, 14, 13, 5)

    def test_best_5_four_of_a_kind(self):
        """7 张中有四条"""
        hole = [C(S, 9), C(H, 9)]
        community = [C(D, 9), C(CL, 9), C(S, 14), C(H, 2), C(D, 3)]
        score = evaluate_hand(hole, community)
        assert get_hand_type(score) == 8  # 四条
        assert score[1] == 9  # 四条是 9
        assert score[2] == 14  # 踢脚是 A

    def test_raises_on_less_than_5_cards(self):
        """少于 5 张牌抛异常"""
        with pytest.raises(ValueError):
            evaluate_hand([C(S, 2)], [C(H, 3), C(D, 4)])


# ======================== 7. compare_hands (多人比牌) ========================

class TestCompareHands:
    """多人比牌 + 平局"""

    def test_single_winner(self):
        """一人赢"""
        hands = {
            1: evaluate_5cards([C(S, 14), C(H, 14), C(D, 10), C(CL, 5), C(S, 3)]),  # 一对 A
            2: evaluate_5cards([C(S, 13), C(H, 13), C(D, 10), C(CL, 5), C(S, 3)]),  # 一对 K
        }
        winners = compare_hands(hands)
        assert winners == [1]

    def test_tie(self):
        """平局"""
        hands = {
            1: evaluate_5cards([C(S, 14), C(H, 14), C(D, 10), C(CL, 5), C(S, 3)]),
            2: evaluate_5cards([C(D, 14), C(CL, 14), C(H, 10), C(S, 5), C(D, 3)]),
        }
        winners = compare_hands(hands)
        assert set(winners) == {1, 2}

    def test_three_way_one_winner(self):
        """三人比牌，一人赢"""
        hands = {
            1: evaluate_5cards([C(S, 6), C(H, 5), C(D, 4), C(CL, 3), C(S, 2)]),  # 顺子 6-high
            2: evaluate_5cards([C(S, 14), C(H, 14), C(D, 13), C(CL, 12), C(S, 11)]),  # 一对 A
            3: evaluate_5cards([C(S, 10), C(H, 10), C(D, 10), C(CL, 5), C(S, 3)]),  # 三条 10
        }
        winners = compare_hands(hands)
        assert winners == [1]

    def test_empty_hands(self):
        """空输入"""
        assert compare_hands({}) == []

    def test_split_pot_scenario(self):
        """分池场景: 两人牌力完全相同"""
        # 公共牌 A-K-Q-J-9 (都是高牌 A)
        community = [C(S, 14), C(H, 13), C(D, 12), C(CL, 11), C(S, 9)]
        # 玩家 1: 手牌 2-3 (最佳 5 张就是公共牌)
        p1 = evaluate_hand([C(H, 2), C(D, 3)], community)
        # 玩家 2: 手牌 4-5 (最佳 5 张也是公共牌)
        p2 = evaluate_hand([C(CL, 4), C(S, 5)], community)
        assert p1 == p2
        winners = compare_hands({1: p1, 2: p2})
        assert set(winners) == {1, 2}


# ======================== 8. evaluate_all_players 集成 ========================

class TestEvaluateAllPlayers:
    """evaluate_all_players 集成测试"""

    def test_basic_evaluation(self):
        from app.engine.evaluator import evaluate_all_players
        hole_map = {
            1: [C(S, 14), C(H, 14)],  # 一对 A
            2: [C(D, 13), C(CL, 13)],  # 一对 K
        }
        community = [C(S, 10), C(H, 8), C(D, 5), C(CL, 3), C(S, 2)]
        results = evaluate_all_players(hole_map, community)

        assert results[1]["hand_type"] == 2  # 一对
        assert results[2]["hand_type"] == 2  # 一对
        assert results[1]["score"] > results[2]["score"]

    def test_skips_insufficient_cards(self):
        from app.engine.evaluator import evaluate_all_players
        hole_map = {
            1: [C(S, 14)],  # 只有 1 张手牌，应跳过
            2: [C(D, 13), C(CL, 13)],
        }
        community = [C(S, 10), C(H, 8), C(D, 5)]
        results = evaluate_all_players(hole_map, community)
        assert 1 not in results
        assert 2 in results
