"""岛屿铃钱记 — 历史相关 Schema"""

from pydantic import BaseModel


class HandSummary(BaseModel):
    hand_id: int
    hand_number: int
    pot_total: int
    status: str
    created_at: str


class HandDetail(BaseModel):
    hand_id: int
    hand_number: int
    dealer_player_id: int
    sb_player_id: int
    bb_player_id: int
    current_round: str
    status: str
    pot_total: int
    bets: list[dict]
    pots: list[dict]
    results: list[dict]


class UserGameHistory(BaseModel):
    room_id: int
    room_name: str
    hand_count: int
    total_profit: int
    created_at: str


class UserStats(BaseModel):
    total_games: int
    total_hands: int
    total_profit: int
    win_rate: float
