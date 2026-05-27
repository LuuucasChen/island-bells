"""岛屿铃钱记 — 认证 API"""

import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.utils.security import create_token
from app.utils.wechat import code2session

router = APIRouter()


class LoginRequest(BaseModel):
    code: str
    nickname: str = ""
    avatar_url: str = ""


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


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    """微信登录：用 code 换取 openid，创建或更新用户，返回 JWT"""
    wx_data = await code2session(req.code)
    if wx_data is None:
        from app.utils import UnauthorizedException
        raise UnauthorizedException("微信登录失败")

    openid = wx_data["openid"]

    # 查找或创建用户
    user = db.query(User).filter(User.openid == openid).first()
    if user is None:
        user = User(
            openid=openid,
            nickname=req.nickname,
            avatar_url=req.avatar_url,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # 更新昵称和头像
        if req.nickname:
            user.nickname = req.nickname
        if req.avatar_url:
            user.avatar_url = req.avatar_url
        db.commit()

    token = create_token({"sub": str(user.id)})

    return LoginResponse(
        token=token,
        user={
            "id": user.id,
            "nickname": user.nickname,
            "avatar_url": user.avatar_url,
        },
    )


@router.post("/demo", response_model=LoginResponse)
async def demo_login(req: DemoLoginRequest, db: Session = Depends(get_db)):
    """网页版 Demo 登录：无需微信，直接创建用户并返回 JWT"""
    openid = f"demo_web_{uuid.uuid4().hex[:8]}"
    nickname = req.nickname or "居民"

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
