"""岛屿铃钱记 — 完整游戏流程演示脚本"""
import os, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DATABASE_URL'] = 'sqlite:///./dev.db'

import requests
from app.utils.security import create_token
from app.database import SessionLocal
from app.models import User

db = SessionLocal()

users = {}
for name in ['OwnerTanuki', 'ResidentGoose', 'ResidentEagle']:
    u = User(openid=f'demo3_{name}', nickname=name, avatar_url='')
    db.add(u)
    db.commit()
    db.refresh(u)
    users[name] = {'id': u.id, 'token': create_token({'sub': str(u.id)})}
db.close()

BASE = 'http://localhost:8000'

def api(method, path, user_name, data=None):
    t = users[user_name]['token']
    headers = {'Authorization': f'Bearer {t}', 'Content-Type': 'application/json'}
    r = getattr(requests, method)(f'{BASE}{path}', json=data, headers=headers)
    return r.json()

lines = []

def log(msg):
    lines.append(msg)

log('='*55)
log('  Island Bells - Full Game Flow Demo')
log('='*55)

# 1 Create
res = api('post', '/v1/rooms', 'OwnerTanuki', {'name': 'BellsIsland', 'initial_chips': 10000, 'sb_amount': 25, 'bb_amount': 50})
code = res['room_code']
rid = res['room_id']
log(f'[1] Create island: DodoCode={code} RoomID={rid}')

# 2 Join
for name in ['OwnerTanuki', 'ResidentGoose', 'ResidentEagle']:
    res = api('post', f'/v1/rooms/{code}/join', name)
    log(f'[2] {name} joined: pid={res.get("player_id","ERR")}')

# 3 Sit
for name, seat in [('OwnerTanuki',0),('ResidentGoose',3),('ResidentEagle',5)]:
    res = api('post', f'/v1/rooms/{rid}/sit', name, {'seat_number': seat})
    log(f'[3] {name} seat={seat}: ok')

# 4 Players
res = api('get', f'/v1/rooms/{rid}/players', 'OwnerTanuki')
log('[4] Players:')
for p in res['players']:
    log(f'  seat {p["seat_number"]}: {p["nickname"]} bells={p["chip_count"]}')

# 5 Start
res = api('post', f'/v1/rooms/{rid}/start', 'OwnerTanuki')
hid = res['hand_id']
log(f'[5] Start game: hand_id={hid} round={res["current_round"]} pot={res["pot_total"]}')

# 6 State
res = api('get', f'/v1/rooms/{rid}/state', 'OwnerTanuki')
h = res['current_hand']
log(f'[6] Game state: round={h["current_round"]} pot={h["pot_total"]}')
for p in h['players']:
    role = p.get('role','')
    log(f'  {p["nickname"]} [{role}] bells={p["chip_count"]} bet={p.get("bet_this_round",0)}')

# 7 Preflop betting
res = api('post', f'/v1/hands/{hid}/bet', 'OwnerTanuki', {'action':'call','amount':0})
log(f'[7] Owner calls: pot={res["pot_total"]}')
res = api('post', f'/v1/hands/{hid}/bet', 'ResidentGoose', {'action':'call','amount':0})
log(f'[7] Goose calls: pot={res["pot_total"]}')
res = api('post', f'/v1/hands/{hid}/bet', 'ResidentEagle', {'action':'raise','amount':100})
log(f'[7] Eagle raises 100: pot={res["pot_total"]}')
res = api('post', f'/v1/hands/{hid}/bet', 'OwnerTanuki', {'action':'call','amount':0})
log(f'[7] Owner calls: pot={res["pot_total"]}')
res = api('post', f'/v1/hands/{hid}/bet', 'ResidentGoose', {'action':'call','amount':0})
log(f'[7] Goose calls: pot={res["pot_total"]}')

# 8 Advance to flop
res = api('post', f'/v1/hands/{hid}/next-round', 'OwnerTanuki')
log(f'[8] Advance: round={res["current_round"]} pot={res["pot_total"]}')

# 9 Flop betting
res = api('post', f'/v1/hands/{hid}/bet', 'OwnerTanuki', {'action':'call','amount':0})
log(f'[9] Owner checks: pot={res["pot_total"]}')
res = api('post', f'/v1/hands/{hid}/bet', 'ResidentGoose', {'action':'raise','amount':200})
log(f'[9] Goose raises 200: pot={res["pot_total"]}')
res = api('post', f'/v1/hands/{hid}/bet', 'ResidentEagle', {'action':'fold','amount':0})
log(f'[9] Eagle folds')
res = api('post', f'/v1/hands/{hid}/bet', 'OwnerTanuki', {'action':'call','amount':0})
log(f'[9] Owner calls: pot={res["pot_total"]}')

# 10 Advance to showdown
log('[10] Advance to showdown:')
for _ in range(3):
    res = api('post', f'/v1/hands/{hid}/next-round', 'OwnerTanuki')
    log(f'  -> round={res.get("current_round")} status={res.get("status")} pot={res.get("pot_total")}')
    if res.get('status') == 'settling': break

# 11 Pots
res = api('get', f'/v1/rooms/{rid}/state', 'ResidentGoose')
h = res['current_hand']
pots = h['pots']
log(f'[11] Pots: {len(pots)}')
for pot in pots:
    log(f'  {pot["pot_type"]} pot: amount={pot["amount"]}')

# 12 Settle
settle = {'results': [{'pot_id': pots[0]['pot_id'], 'winner_ids': [2], 'amount': pots[0]['amount']}]}
res = api('post', f'/v1/hands/{hid}/settle', 'OwnerTanuki', settle)
log(f'[12] Settled: status={res["status"]}')
for r in res['results']:
    log(f'  winner_id={r["winner_id"]} amount_won={r["amount_won"]}')

# 13 Final bells
res = api('get', f'/v1/rooms/{rid}/players', 'OwnerTanuki')
log('[13] Final bells:')
for p in res['players']:
    log(f'  {p["nickname"]}: {p["chip_count"]} bells')

# 14 History
res = api('get', f'/v1/rooms/{rid}/hands', 'OwnerTanuki')
log('[14] Hand history:')
for h in res['hands']:
    log(f'  Season #{h["hand_number"]}: round={h["current_round"]} pot={h["pot_total"]} status={h["status"]}')

log('')
log('='*55)
log('  ALL DONE - Game flow completed!')
log('='*55)

# Write to file
with open('d:/poker/backend/demo_output.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('\n'.join(lines))