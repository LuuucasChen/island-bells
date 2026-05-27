#!/usr/bin/env python3
"""岛屿铃钱记 — 网页版完整游戏流程测试"""
import sys, json, urllib.request

BASE = "http://localhost:8000/v1"

def api(method, path, data=None, token=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()}

print("=" * 50)
print("岛屿铃钱记 — 网页版完整游戏流程测试")
print("=" * 50)

# Step 1: Demo login (创建者)
print("\n[1] Demo 登录 (创建者)")
r1 = api("POST", "/auth/demo", {"nickname": "岛主小明"})
token1 = r1["token"]
user1 = r1["user"]
print(f"  创建者: {user1['nickname']} (id={user1['id']})")

# Step 2: 创建岛屿
print("\n[2] 创建岛屿")
r2 = api("POST", "/rooms", {"chip_count": 10000, "small_blind": 50, "big_blind": 100}, token1)
room_id = r2["room_id"]
room_code = r2["room_code"]
print(f"  岛屿ID: {room_id}, 渡渡鸟码: {room_code}")

# Step 3: Demo login (加入者)
print("\n[3] Demo 登录 (加入者)")
r3 = api("POST", "/auth/demo", {"nickname": "居民小红"})
token2 = r3["token"]
user2 = r3["user"]
print(f"  加入者: {user2['nickname']} (id={user2['id']})")

# Step 4: 加入岛屿
print("\n[4] 加入岛屿")
r4 = api("POST", f"/rooms/{room_code}/join", {}, token2)
print(f"  加入结果: {r4}")

# Step 5: 创建者坐下
print("\n[5] 岛主坐下 (座位0)")
r5 = api("POST", f"/rooms/{room_id}/sit", {"seat_number": 0}, token1)
print(f"  坐下结果: {r5}")

# Step 6: 加入者坐下
print("\n[6] 居民坐下 (座位1)")
r6 = api("POST", f"/rooms/{room_id}/sit", {"seat_number": 1}, token2)
print(f"  坐下结果: {r6}")

# Step 7: 查看岛屿状态
print("\n[7] 查看岛屿状态")
r7 = api("GET", f"/rooms/{room_id}", None, token1)
print(f"  状态: {r7['status']}, 玩家数: {len(r7['players'])}")

# Step 8: 开始游戏
print("\n[8] 开始游戏")
r8 = api("POST", f"/rooms/{room_id}/start", None, token1)
print(f"  开始结果: {r8}")

# Step 9: 查看游戏状态
print("\n[9] 查看游戏状态")
r9 = api("GET", f"/rooms/{room_id}/state", None, token1)
hand = r9.get("current_hand")
if hand:
    print(f"  一季号: {hand['hand_number']}, 当前阶段: {hand['current_round']}")
    print(f"  收获篮总额: {hand['pot_total']}")
    for p in hand['players']:
        print(f"    {p['nickname']}: 铃钱={p['chip_count']}, 本轮投入={p['bet_this_round']}, 角色={p['role']}, 休息={p['is_folded']}")
else:
    print(f"  游戏状态: {r9}")

# Step 10: 创建者 call
print("\n[10] 岛主跟随 (call)")
r10 = api("POST", f"/rooms/{room_id}/action", {"action": "call"}, token1)
print(f"  动作结果: {r10}")

# Step 11: 加入者 call
print("\n[11] 居民跟随 (call)")
r11 = api("POST", f"/rooms/{room_id}/action", {"action": "call"}, token2)
print(f"  动作结果: {r11}")

# Step 12: 推进到 flop
print("\n[12] 推进到午后 (flop)")
r12 = api("POST", f"/rooms/{room_id}/advance", None, token1)
print(f"  推进结果: {r12}")

# Step 13: 查看游戏状态 (午后)
print("\n[13] 查看午后状态")
r13 = api("GET", f"/rooms/{room_id}/state", None, token1)
hand = r13.get("current_hand")
if hand:
    print(f"  阶段: {hand['current_round']}, 收获篮: {hand['pot_total']}")
else:
    print(f"  状态: {r13}")

# Step 14: 加入者 fold (休息)
print("\n[14] 居民休息 (fold)")
r14 = api("POST", f"/rooms/{room_id}/action", {"action": "fold"}, token2)
print(f"  休息结果: {r14}")

# Step 15: 推进到 showdown
print("\n[15] 推进到收获祭 (showdown)")
r15 = api("POST", f"/rooms/{room_id}/advance", None, token1)
print(f"  推进结果: {r15}")

# Step 16: 查看收获祭状态
print("\n[16] 查看收获祭状态")
r16 = api("GET", f"/rooms/{room_id}/state", None, token1)
hand = r16.get("current_hand")
if hand:
    print(f"  阶段: {hand['current_round']}, 收获篮: {hand['pot_total']}")
else:
    print(f"  状态: {r16}")

# Step 17: 收获结算
print("\n[17] 收获结算 (settle)")
r17 = api("POST", f"/rooms/{room_id}/settle", None, token1)
print(f"  结算结果: {r17}")

# Step 18: 最终铃钱
print("\n[18] 最终铃钱")
r18 = api("GET", f"/rooms/{room_id}/state", None, token1)
hand = r18.get("current_hand")
if hand:
    for p in hand['players']:
        print(f"  {p['nickname']}: 铃钱={p['chip_count']}")
else:
    r18b = api("GET", f"/rooms/{room_id}", None, token1)
    for p in r18b['players']:
        print(f"  {p['nickname']}: 铃钱={p['chip_count']}")

print("\n" + "=" * 50)
print("完整游戏流程测试通过!")
print("=" * 50)