"""岛屿铃钱记 — 配置模块"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # 环境: dev(本地SQLite) / prod(云端MySQL)
    APP_ENV: str = "dev"

    # 数据库
    # dev 模式默认 SQLite，prod 模式通过 .env 设置 MySQL 连接串
    DATABASE_URL: str = "sqlite:///./dev.db"

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
