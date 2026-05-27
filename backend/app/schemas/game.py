"""岛屿铃钱记 — 游戏相关 Schema"""

from pydantic import BaseModel


class BetRequest(BaseModel):
    action: str  # call / raise / allin / fold
    amount: int = 0  # raise 时的金额


class SettleRequest(BaseModel):
    results: list[dict]  # [{pot_id, winner_ids, amounts}]


class RebuyRequest(BaseModel):
    amount: int  # 补给铃钱数量


class GameEvent(BaseModel):
    """WebSocket 广播事件"""
    type: str
    data: dict = {}
