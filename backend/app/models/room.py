"""岛屿铃钱记 — 房间(岛屿)模型"""

from sqlalchemy import Column, String, Integer, SmallInteger, DateTime, Enum, ForeignKey, func
from app.database import Base


class Room(Base):
    __tablename__ = "room"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_code = Column(String(6), unique=True, nullable=False, index=True)
    name = Column(String(64), default="")
    owner_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    status = Column(Enum("waiting", "playing", "finished"), default="waiting", nullable=False)
    max_players = Column(SmallInteger, default=9)
    initial_chips = Column(Integer, default=10000)
    sb_amount = Column(Integer, default=25)
    bb_amount = Column(Integer, default=50)
    dealer_seat = Column(SmallInteger, default=0)
    created_at = Column(DateTime, server_default=func.now())
    closed_at = Column(DateTime, nullable=True)


class RoomPlayer(Base):
    __tablename__ = "room_player"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("room.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    seat_number = Column(SmallInteger, nullable=False)
    chip_count = Column(Integer, default=0, nullable=False)
    is_active = Column(Integer, default=1, nullable=False)  # 1=True, 0=False
    joined_at = Column(DateTime, server_default=func.now())
    left_at = Column(DateTime, nullable=True)
