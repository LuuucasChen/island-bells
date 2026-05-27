"""岛屿铃钱记 — 标准扑克牌发牌器

52 张牌，4 花色 x 13 点数
rank: 2-14 (11=J, 12=Q, 13=K, 14=A)
suit: spades / hearts / diamonds / clubs
"""

import random
import json
from dataclasses import dataclass, asdict
from typing import Optional


SUITS = ["spades", "hearts", "diamonds", "clubs"]
RANKS = list(range(2, 15))  # 2-14


@dataclass
class Card:
    suit: str
    rank: int

    def to_dict(self) -> dict:
        return {"suit": self.suit, "rank": self.rank}

    @classmethod
    def from_dict(cls, d: dict) -> "Card":
        return cls(suit=d["suit"], rank=d["rank"])

    @property
    def rank_str(self) -> str:
        """显示用: 2-10, J, Q, K, A"""
        mapping = {11: "J", 12: "Q", 13: "K", 14: "A"}
        return mapping.get(self.rank, str(self.rank))

    @property
    def suit_symbol(self) -> str:
        symbols = {"spades": "♠", "hearts": "♥", "diamonds": "♦", "clubs": "♣"}
        return symbols.get(self.suit, "?")

    def __repr__(self):
        return f"{self.suit_symbol}{self.rank_str}"


class Deck:
    """标准 52 张扑克牌堆"""

    def __init__(self):
        self.cards = [Card(suit=s, rank=r) for s in SUITS for r in RANKS]
        random.shuffle(self.cards)

    def deal(self, n: int = 1) -> list[Card]:
        """发 n 张牌"""
        if n > len(self.cards):
            raise ValueError(f"牌堆剩余 {len(self.cards)} 张，不足 {n} 张")
        dealt = self.cards[:n]
        self.cards = self.cards[n:]
        return dealt

    def burn(self, n: int = 1):
        """烧掉 n 张牌（德州扑克规则：每轮发公共牌前烧一张）"""
        self.deal(n)  # 丢弃

    @property
    def remaining(self) -> int:
        return len(self.cards)

    def to_json(self) -> str:
        """序列化剩余牌堆（用于存储到 DB）"""
        return json.dumps([c.to_dict() for c in self.cards])

    @classmethod
    def from_json(cls, json_str: str) -> "Deck":
        """从 JSON 恢复牌堆"""
        deck = cls.__new__(cls)
        deck.cards = [Card.from_dict(d) for d in json.loads(json_str)]
        return deck


def cards_to_json(cards: list[Card]) -> str:
    """将牌列表序列化为 JSON 字符串"""
    return json.dumps([c.to_dict() for c in cards])


def cards_from_json(json_str: str) -> list[Card]:
    """从 JSON 字符串恢复牌列表"""
    if not json_str:
        return []
    return [Card.from_dict(d) for d in json.loads(json_str)]
