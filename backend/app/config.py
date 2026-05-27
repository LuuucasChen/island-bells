"""岛屿铃钱记 — 配置模块"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # 数据库
    DATABASE_URL: str = "mysql+pymysql://bells:bellspass@localhost:3306/island_bells?charset=utf8mb4"

    # 微信小程序
    WECHAT_APPID: str = ""
    WECHAT_SECRET: str = ""

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 72

    # 房间
    ROOM_CODE_LENGTH: int = 6
    MAX_PLAYERS: int = 9

    # 超时
    ACTION_TIMEOUT_SECONDS: int = 30

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
