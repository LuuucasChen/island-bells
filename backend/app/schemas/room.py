"""岛屿铃钱记 — 房间(岛屿)相关 Schema"""

from pydantic import BaseModel, Field


class CreateRoomRequest(BaseModel):
    name: str = ""
    initial_chips: int = Field(10000, gt=0)
    sb_amount: int = Field(25, gt=0)
    bb_amount: int = Field(50, gt=0)
    max_players: int = 9


class JoinRoomRequest(BaseModel):
    pass


class SitRequest(BaseModel):
    seat_number: int


class UpdateRoomRequest(BaseModel):
    name: str | None = None
    initial_chips: int | None = Field(None, gt=0)
    sb_amount: int | None = Field(None, gt=0)
    bb_amount: int | None = Field(None, gt=0)
    max_players: int | None = None


class RoomResponse(BaseModel):
    room_id: int
    room_code: str
    name: str
    status: str
    max_players: int
    initial_chips: int
    sb_amount: int
    bb_amount: int
    player_count: int


class PlayerInfoResponse(BaseModel):
    player_id: int
    user_id: int
    nickname: str
    avatar_url: str
    seat_number: int
    chip_count: int


class PlayerListResponse(BaseModel):
    players: list[PlayerInfoResponse]
