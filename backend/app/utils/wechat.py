"""岛屿铃钱记 — 微信 API 客户端"""

import httpx
from app.config import settings

CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


async def code2session(code: str) -> dict | None:
    """
    调用微信 code2session 接口，用临时 code 换取 openid 和 session_key
    返回: {"openid": "...", "session_key": "..."} 或 None
    """
    params = {
        "appid": settings.WECHAT_APPID,
        "secret": settings.WECHAT_SECRET,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(CODE2SESSION_URL, params=params)
        if resp.status_code == 200:
            data = resp.json()
            if "openid" in data:
                return data
    return None
