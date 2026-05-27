"""岛屿铃钱记 — 德州扑克牌力评估器

从 7 张牌中选出最佳 5 张组合，返回牌型等级 + 比较键。

牌型等级 (从高到低):
  10 = 皇家同花顺 Royal Flush
   9 = 同花顺 Straight Flush
   8 = 四条 Four of a Kind
   7 = 葫芦 Full House
   6 = 同花 Flush
   5 = 顺子 Straight
   4 = 三条 Three of a Kind
   3 = 两对 Two Pair
   2 = 一对 One Pair
   1 = 高牌 High Card
"""

from itertools import combinations
from typing import Optional
from app.engine.deck import Card


# 牌型名称映射
HAND_TYPE_NAMES = {
    10: "皇家同花顺",
    9: "同花顺",
    8: "四条",
    7: "葫芦",
    6: "同花",
    5: "顺子",
    4: "三条",
    3: "两对",
    2: "一对",
    1: "高牌",
}


def evaluate_5cards(cards: list[Card]) -> tuple:
    """
    评估 5 张牌的牌力，返回可排序的 tuple。
    tuple 格式: (牌型等级, 主要比较值, 次要比较值...)
    越大的 tuple 表示越强的牌。
    """
    ranks = sorted([c.rank for c in cards], reverse=True)
    suits = [c.suit for c in cards]

    is_flush = len(set(suits)) == 1

    # 检查顺子 (A=14 可以作为 1 用: A-2-3-4-5)
    is_straight, straight_high = _check_straight(ranks)

    # 统计点数出现次数
    rank_counts = {}
    for r in ranks:
        rank_counts[r] = rank_counts.get(r, 0) + 1
    # 按 (次数 desc, 点数 desc) 排序
    sorted_counts = sorted(rank_counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    counts = [c for _, c in sorted_counts]
    sorted_ranks = [r for r, _ in sorted_counts]

    # 皇家同花顺
    if is_flush and is_straight and straight_high == 14 and 13 in ranks:
        return (10,)

    # 同花顺
    if is_flush and is_straight:
        return (9, straight_high)

    # 四条
    if counts[0] == 4:
        kicker = sorted_ranks[1]
        return (8, sorted_ranks[0], kicker)

    # 葫芦
    if counts[0] == 3 and counts[1] == 2:
        return (7, sorted_ranks[0], sorted_ranks[1])

    # 同花
    if is_flush:
        return (6, *ranks)

    # 顺子
    if is_straight:
        return (5, straight_high)

    # 三条
    if counts[0] == 3:
        kickers = [r for r in ranks if r != sorted_ranks[0]]
        return (4, sorted_ranks[0], *sorted(kickers, reverse=True))

    # 两对
    if counts[0] == 2 and counts[1] == 2:
        pair_high = max(sorted_ranks[0], sorted_ranks[1])
        pair_low = min(sorted_ranks[0], sorted_ranks[1])
        kicker = sorted_ranks[2]
        return (3, pair_high, pair_low, kicker)

    # 一对
    if counts[0] == 2:
        pair_rank = sorted_ranks[0]
        kickers = sorted([r for r in ranks if r != pair_rank], reverse=True)
        return (2, pair_rank, *kickers)

    # 高牌
    return (1, *ranks)


def _check_straight(ranks: list[int]) -> tuple[bool, int]:
    """检查是否顺子，返回 (is_straight, high_card)"""
    unique = sorted(set(ranks), reverse=True)
    if len(unique) < 5:
        return False, 0

    # 常规顺子
    for i in range(len(unique) - 4):
        if unique[i] - unique[i + 4] == 4:
            # 确认连续
            if all(unique[i + j] - unique[i + j + 1] == 1 for j in range(4)):
                return True, unique[i]

    # A-2-3-4-5 (wheel)
    if 14 in unique and all(r in unique for r in [2, 3, 4, 5]):
        return True, 5

    return False, 0


def evaluate_hand(hole_cards: list[Card], community_cards: list[Card]) -> tuple:
    """
    评估德州扑克手牌（2 张手牌 + 3-5 张公共牌）
    从 7 张牌中选出最佳 5 张组合。
    返回可排序的 tuple。
    """
    all_cards = hole_cards + community_cards
    if len(all_cards) < 5:
        raise ValueError(f"至少需要 5 张牌，当前 {len(all_cards)} 张")

    best = None
    for combo in combinations(all_cards, 5):
        score = evaluate_5cards(list(combo))
        if best is None or score > best:
            best = score

    return best


def get_hand_type(score: tuple) -> int:
    """从评分 tuple 提取牌型等级"""
    return score[0] if score else 0


def get_hand_type_name(score: tuple) -> str:
    """从评分 tuple 获取牌型中文名"""
    return HAND_TYPE_NAMES.get(get_hand_type(score), "未知")


def compare_hands(
    player_hands: dict[int, tuple],
) -> list[int]:
    """
    多人比牌，返回赢家 player_id 列表（支持平局多人）

    player_hands: {player_id: score_tuple}
    """
    if not player_hands:
        return []

    best_score = max(player_hands.values())
    winners = [pid for pid, score in player_hands.items() if score == best_score]
    return winners


def evaluate_all_players(
    hole_cards_map: dict[int, list[Card]],
    community_cards: list[Card],
) -> dict[int, dict]:
    """
    评估所有玩家的牌力

    返回: {player_id: {"score": tuple, "hand_type": int, "hand_type_name": str}}
    """
    results = {}
    for pid, hole in hole_cards_map.items():
        if len(hole) < 2 or len(community_cards) < 3:
            continue
        score = evaluate_hand(hole, community_cards)
        results[pid] = {
            "score": score,
            "hand_type": get_hand_type(score),
            "hand_type_name": get_hand_type_name(score),
        }
    return results
