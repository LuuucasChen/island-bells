"""岛屿铃钱记 — FastAPI 依赖注入"""

from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.utils.security import decode_token
from app.utils import UnauthorizedException
from app.models import User

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """从 JWT token 中获取当前用户"""
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise UnauthorizedException("Token 无效或已过期")

    user_id = payload.get("sub")
    if user_id is None:
        raise UnauthorizedException("Token 缺少用户信息")

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        raise UnauthorizedException("Token 用户信息无效")

    user = db.query(User).filter(User.id == uid).first()
    if user is None:
        raise UnauthorizedException("用户不存在")

    return user
