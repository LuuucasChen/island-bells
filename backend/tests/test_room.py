"""岛屿铃钱记 — 房间 API 测试"""

from app.models import User
from app.utils.security import create_token


def _auth_header(user_id: int) -> dict:
    token = create_token({"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def test_create_room(client, db_session):
    user = User(openid="owner_openid", nickname="岛主", avatar_url="")
    db_session.add(user)
    db_session.commit()

    resp = client.post(
        "/v1/rooms",
        json={"name": "测试岛屿", "initial_chips": 5000, "sb_amount": 25, "bb_amount": 50},
        headers=_auth_header(user.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "room_code" in data
    assert len(data["room_code"]) == 6
    assert data["name"] == "测试岛屿"


def test_create_room_bb_too_small(client, db_session):
    user = User(openid="owner2_openid", nickname="岛主2", avatar_url="")
    db_session.add(user)
    db_session.commit()

    resp = client.post(
        "/v1/rooms",
        json={"sb_amount": 50, "bb_amount": 50},
        headers=_auth_header(user.id),
    )
    assert resp.status_code == 400


def test_join_room(client, db_session):
    owner = User(openid="owner3_openid", nickname="岛主3", avatar_url="")
    joiner = User(openid="joiner_openid", nickname="居民", avatar_url="")
    db_session.add_all([owner, joiner])
    db_session.commit()

    # 创建房间
    resp = client.post(
        "/v1/rooms",
        json={"name": "加入测试"},
        headers=_auth_header(owner.id),
    )
    room_code = resp.json()["room_code"]

    # 加入房间
    resp = client.post(
        f"/v1/rooms/{room_code}/join",
        headers=_auth_header(joiner.id),
    )
    assert resp.status_code == 200


def test_join_room_twice(client, db_session):
    owner = User(openid="owner4_openid", nickname="岛主4", avatar_url="")
    db_session.add(owner)
    db_session.commit()

    resp = client.post(
        "/v1/rooms",
        json={"name": "重复加入测试"},
        headers=_auth_header(owner.id),
    )
    room_code = resp.json()["room_code"]

    # 创建者先加入
    resp = client.post(
        f"/v1/rooms/{room_code}/join",
        headers=_auth_header(owner.id),
    )

    # 再次加入应冲突
    resp = client.post(
        f"/v1/rooms/{room_code}/join",
        headers=_auth_header(owner.id),
    )
    assert resp.status_code == 409


def test_sit_and_stand(client, db_session):
    owner = User(openid="owner5_openid", nickname="岛主5", avatar_url="")
    db_session.add(owner)
    db_session.commit()

    resp = client.post(
        "/v1/rooms",
        json={"name": "入座测试"},
        headers=_auth_header(owner.id),
    )
    # 创建房间时岛主已自动加入，无需再 join
    room_id = resp.json()["room_id"]

    # 入座
    resp = client.post(
        f"/v1/rooms/{room_id}/sit",
        json={"seat_number": 0},
        headers=_auth_header(owner.id),
    )
    assert resp.status_code == 200
    assert resp.json()["seat_number"] == 0

    # 站起
    resp = client.post(
        f"/v1/rooms/{room_id}/stand",
        headers=_auth_header(owner.id),
    )
    assert resp.status_code == 200
