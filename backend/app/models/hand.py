"""岛屿铃钱记 — 手牌(一季)模型"""

from sqlalchemy import Column, Integer, SmallInteger, String, Text, DateTime, Enum, ForeignKey, func
from app.database import Base


class Hand(Base):
    __tablename__ = "hand"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("room.id"), nullable=False, index=True)
    hand_number = Column(Integer, nullable=False)
    dealer_player_id = Column(Integer, ForeignKey("room_player.id"), nullable=False)
    sb_player_id = Column(Integer, ForeignKey("room_player.id"), nullable=False)
    bb_player_id = Column(Integer, ForeignKey("room_player.id"), nullable=False)
    current_round = Column(
        Enum("preflop", "flop", "turn", "river", "showdown"),
        default="preflop", nullable=False
    )
    status = Column(
        Enum("betting", "settling", "settled"),
        default="betting", nullable=False
    )
    pot_total = Column(Integer, default=0)
    turn_player_id = Column(Integer, ForeignKey("room_player.id"), nullable=True)  # 当前该行动的玩家

    # 扑克牌数据
    community_cards = Column(String(512), nullable=True)  # JSON: [{"suit":"spades","rank":14},...]
    hole_cards = Column(Text, nullable=True)  # JSON: {"player_id_str": [{"suit","rank"},...]}
    deck_state = Column(Text, nullable=True)  # JSON: 剩余牌堆（用于续发公共牌）

    # 结算辅助字段
    ended_by_fold = Column(SmallInteger, default=0)  # 1=因 fold 结束 (赢家可选盖牌)
    muck_player_id = Column(Integer, ForeignKey("room_player.id"), nullable=True)  # 选择盖牌的赢家

    # Showdown 亮牌阶段
    last_aggressor_id = Column(Integer, ForeignKey("room_player.id"), nullable=True)  # 最后激进者 (必须亮牌)
    revealed_players = Column(String(256), nullable=True)  # 逗号分隔的已亮牌 player_id
    mucked_players = Column(String(256), nullable=True)  # 逗号分隔的已盖牌 player_id

    created_at = Column(DateTime, server_default=func.now())
    settled_at = Column(DateTime, nullable=True)


class Bet(Base):
    __tablename__ = "bet"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hand_id = Column(Integer, ForeignKey("hand.id"), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey("room_player.id"), nullable=False)
    round = Column(
        Enum("preflop", "flop", "turn", "river"),
        nullable=False
    )
    action = Column(
        Enum("blind", "call", "raise", "allin", "fold", "check"),
        nullable=False
    )
    amount = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class Pot(Base):
    __tablename__ = "pot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hand_id = Column(Integer, ForeignKey("hand.id"), nullable=False, index=True)
    pot_type = Column(Enum("main", "side"), nullable=False)
    pot_level = Column(Integer, default=0, nullable=False)
    amount = Column(Integer, nullable=False)
    eligible_player_ids = Column(String(512), nullable=True)  # 逗号分隔的 player ID 列表


class HandResult(Base):
    __tablename__ = "hand_result"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hand_id = Column(Integer, ForeignKey("hand.id"), nullable=False, index=True)
    pot_id = Column(Integer, ForeignKey("pot.id"), nullable=False)
    winner_id = Column(Integer, ForeignKey("room_player.id"), nullable=False)
    amount_won = Column(Integer, nullable=False)
    is_split = Column(Integer, default=0)  # 0=False, 1=True


class Rebuy(Base):
    __tablename__ = "rebuy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_player_id = Column(Integer, ForeignKey("room_player.id"), nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
