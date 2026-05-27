"""岛屿铃钱记 — 认证 API 测试"""

from app.models import User
from app.utils.security import create_token


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_me_requires_auth(client):
    resp = client.get("/v1/auth/me")
    assert resp.status_code == 403  # No credentials


def test_me_with_valid_token(client, db_session):
    # 创建测试用户
    user = User(openid="test_openid_123", nickname="测试居民", avatar_url="")
    db_session.add(user)
    db_session.commit()

    token = create_token({"sub": str(user.id)})
    resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["nickname"] == "测试居民"
