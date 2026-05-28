"""岛屿铃钱记 — 认证相关 Schema"""

from pydantic import BaseModel


class LoginResponse(BaseModel):
    token: str
    user: dict


class UserInfoResponse(BaseModel):
    id: int
    openid: str
    nickname: str
    avatar_url: str
