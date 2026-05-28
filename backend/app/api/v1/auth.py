"""岛屿铃钱记 — 认证 API"""

import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.utils.security import create_token

router = APIRouter()


class LoginResponse(BaseModel):
    token: str
    user: dict


class UserInfoResponse(BaseModel):
    id: int
    openid: str
    nickname: str
    avatar_url: str


class DemoLoginRequest(BaseModel):
    nickname: str = "居民"


@router.post("/demo", response_model=LoginResponse)
async def demo_login(req: DemoLoginRequest, db: Session = Depends(get_db)):
    """网页版 Demo 登录：无需微信，直接创建用户并返回 JWT"""
    openid = f"demo_web_{uuid.uuid4().hex[:8]}"
    # 未提供昵称时随机生成动森角色名
    from app.utils.animal_names import get_random_character_name
    nickname = req.nickname if req.nickname and req.nickname != "居民" else get_random_character_name()

    user = User(
        openid=openid,
        nickname=nickname,
        avatar_url="",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token({"sub": str(user.id)})

    return LoginResponse(
        token=token,
        user={
            "id": user.id,
            "nickname": user.nickname,
            "avatar_url": user.avatar_url,
        },
    )


@router.get("/me", response_model=UserInfoResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserInfoResponse(
        id=current_user.id,
        openid=current_user.openid,
        nickname=current_user.nickname,
        avatar_url=current_user.avatar_url,
    )
